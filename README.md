# AI-Sync Bridge

既存の業務システムを改修せず、読み取り専用の接続でデータを取り込み、利用者の権限内のデータだけで検索・AI 回答を行い、その経緯を監査ログに残す連携基盤です。

現在の段階はデモ・PoC です。本番導入の前に「[実装状況](#実装状況)」を確認してください。

- 公開デモ: https://aisync.0101.click/
- 概要仕様書: [`presentation/bridge-spec.html`](presentation/bridge-spec.html)(A4 印刷可)
- 説明用スライド: [`presentation/legacy-rag-spec.html`](presentation/legacy-rag-spec.html)
- 初期の設計仕様(現行実装とは不一致): [`docs/original-design-spec.md`](docs/original-design-spec.md)

## 構成

| パス | 内容 |
|---|---|
| `ai-api-server/` | FastAPI の API サーバー |
| `ai-api-server/app/bridge/` | Connector、差分同期、ACL、検索、権限内 RAG、監査ログ |
| `packages/aisb-core/` | サイドパネルの共通コードと、組込み用ミドルウェア |
| `chrome-extension/` | Chrome 拡張版のサイドパネル |
| `demo-legacy-system/` | 模擬の業務システム(製造業 ERP)。公開デモの主役 |
| `demo-legacy-system-crm/` | 模擬の CRM(営業・クレーム管理)。ERP と DB・権限・監査を共有せず、A2A で連携する |
| `demo-legacy-system-{dealer,realestate,koseki,nenkin}/` | 撤退した業種デモ。pm2・Caddy・landing から外し、git タグ `demo-frozen` で凍結している(開発はしない) |
| `landing/` | デモの入口ページとアーキテクチャ資料 |
| `presentation/` | 仕様書と提案資料 |
| `ops/` | OpenCode サーバーのサンドボックス設定、デモの日次リセット、A2A キーの生成 |

## ブリッジの流れ

```
既存の API / DB / 出力ファイル
  → Connector(読み取りのみ)
  → SyncEngine(行ハッシュで差分判定、変更行だけ再埋め込み)
  → BridgeStore(文書・ベクトル・カーソルを永続化)
  → Retriever + ACL(権限フィルタの後に BM25 + ベクトル)
  → GroundedAnswerer(権限内の文書だけを LLM に渡す)
  → AuditLog(同期・検索・回答をハッシュチェーンで記録)
```

取り込み対象・権限・接続方法は導入先ごとの YAML に書きます。例は [`demo-legacy-system/aisb_profile/bridge.yaml`](demo-legacy-system/aisb_profile/bridge.yaml) と [`demo-legacy-system-crm/aisb_profile/bridge.yaml`](demo-legacy-system-crm/aisb_profile/bridge.yaml) です。

## システム間連携(A2A)

導入先ごとのブリッジを、それぞれ1つの Agent として公開します(`ai-api-server/app/bridge/a2a.py`)。相手のシステムには DB や検索ツールを渡さず、質問を委譲して、相手が自分の権限で答えた結論だけを受け取ります。

```
ERP の利用者(営業) ─ ERP Bridge ──A2A(tasks/send)──▶ CRM Bridge
                      │ 委譲の上限: peers[].allowed_roles      │ 相手側の ACL: キーに紐づく Agent 主体
                      │ 監査: a2a.delegated                    │ 監査: a2a.task.received(on_behalf_of 付き)
                      ▼                                        ▼
                   自分の権限で回答                    自分の権限で回答 → 結論だけ返す
```

- 境界は2つあります。呼び出し側は、どのロールが相手へ委譲できるかを `a2a.peers[].allowed_roles` で決めます。受け手側は、相手 Agent のキーに与えたロールの範囲でしか答えません。`on_behalf_of` は監査用の情報で、権限判定には使いません。
- `/a2a`・`/api/a2a/peers`・`/api/a2a/federated-ask` は API キー必須で、匿名は 401 です。Agent 間の通信は本機内だけで行い、公開経路では Caddy が 404 にします。公開するのは Agent Card(`/.well-known/agent.json`)と公開デモ経路(`/api/a2a/demo/*`)です。デモ経路は `/api/bridge/demo` と同じペルソナ・回数制限・応答の許可リストに従います。
- Peer 用のキーは `ops/gen-a2a-secrets.sh` が `ops/secrets/a2a.env`(git 管理外、0600)に生成し、`start-*.sh` が読み込みます。未設定なら A2A の委譲は無効です。

## 起動

Python 3.12 の環境で確認しています。各ディレクトリに仮想環境を作り、依存関係を入れます。

```bash
cd ai-api-server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd ../demo-legacy-system && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

ERP デモだけを動かす場合:

```bash
(cd demo-legacy-system && .venv/bin/python -m uvicorn main:app --port 5010) &
(cd ai-api-server && ./start-erp.sh) &
```

公開経路(リバースプロキシ経由)の ERP デモは、最初にロールを選んで入ります。パスワードはなく、認証ではありません。画面と JSON API の権限は `demo-legacy-system/demo_roles.py` が `aisb_profile/bridge.yaml` の定義に従って判定します。権限制御に未対応の AI パネルは管理者ロールにだけ表示します(表示の制御のみで、API 側は制限していません)。ロール選択と権限制御があるのは ERP デモだけです。

デモは pm2 で起動します(`ecosystem.config.js` に載っているのは ERP と CRM)。データを毎日初期状態へ戻す `ops/reset-demo-data.sh` も同じ2つを対象にしています。CRM は ERP の仮想環境を使います。

```bash
ops/gen-a2a-secrets.sh          # 初回のみ。A2A キーを生成(既存ファイルは上書きしない)
pm2 start ecosystem.config.js
```

公開経路は ERP が `/erp/`、CRM が `/crm/` です。CRM の業務データ API(`/api/{entity}/list`)はブリッジの同期専用で、公開経路からは 404 になります。

LLM の接続先は `ai-api-server/ai-provider.sh` の `AISB_AI_PROVIDER` で選びます(`mock` / `opencode` / `antigravity` / `openai` / `gemini`)。未設定なら `mock` です。`start-*.sh` は既定で `antigravity` を使うため、CLI がない環境では `AISB_AI_PROVIDER=mock` を指定してください。

## テストと実測

```bash
cd ai-api-server
.venv/bin/python tests/test_bridge.py
.venv/bin/python tests/test_a2a.py
.venv/bin/python tests/test_public_surface.py
.venv/bin/python tests/test_ai_guard.py
.venv/bin/python scripts/bench_bridge.py --docs 10000
cd ../demo-legacy-system
.venv/bin/python tests/test_demo_roles.py
```

## 実装状況

| 項目 | 状態 |
|---|---|
| 差分同期、ACL、ハイブリッド検索、権限内 RAG、監査チェーン | 実装・試験済み |
| A2A(Agent Card、tasks/send・get・cancel、委譲の上限、双方向の権限分離) | 実装・試験済み。ERP ⇔ CRM の2者間のみ。ストリーミング・プッシュ通知は未対応、タスクはメモリ保持(再起動で消える)。外部の A2A 実装との相互接続は未検証 |
| 実 LLM での AI 回答 | antigravity で ERP デモの1問を確認した範囲。精度評価は未実施 |
| OpenAI / Gemini の実接続 | 未検証 |
| ODBC 接続(SQL Server / Oracle / Access) | コードのみ。試験は SQLite のみ |
| sqlite-vec | この aarch64 サーバーでは読み込めない |
| 完全閉域での AI 回答 | 未実装(ローカル LLM 用プロバイダがない) |
| SSO、権限の自動同期 | 未実装 |
| 個人情報の自動マスキング | 未実装 |
| ブリッジ以外の API への ACL | 未対応 |
| 業務パネルの実データ接続 | デモモード専用のものが多い |
| ワークフローの定期実行、プッシュ通知の送信 | 未実装 |

実測値は `presentation/bridge-spec.html` の第7章にあります。現状で応答できる目安は 1 万件程度までです。
