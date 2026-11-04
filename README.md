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
| `demo-legacy-system*/` | 模擬の業務システム(ERP、ディーラー、不動産仲介、自治体窓口、年金相談) |
| `landing/` | デモ選択ページとアーキテクチャ資料 |
| `presentation/` | 仕様書と提案資料 |
| `ops/` | OpenCode サーバーのサンドボックス設定 |

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

取り込み対象・権限・接続方法は導入先ごとの YAML に書きます。例は [`demo-legacy-system/aisb_profile/bridge.yaml`](demo-legacy-system/aisb_profile/bridge.yaml) です。ブリッジを設定しているデモは ERP だけです。

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

全デモは pm2 で起動します。先に各デモの仮想環境を用意してください。

```bash
pm2 start ecosystem.config.js
```

LLM の接続先は `ai-api-server/ai-provider.sh` の `AISB_AI_PROVIDER` で選びます(`mock` / `opencode` / `antigravity` / `openai` / `gemini`)。未設定なら `mock` です。`start-*.sh` は既定で `antigravity` を使うため、CLI がない環境では `AISB_AI_PROVIDER=mock` を指定してください。

## テストと実測

```bash
cd ai-api-server
.venv/bin/python tests/test_bridge.py
.venv/bin/python tests/test_ai_guard.py
.venv/bin/python scripts/bench_bridge.py --docs 10000
```

## 実装状況

| 項目 | 状態 |
|---|---|
| 差分同期、ACL、ハイブリッド検索、権限内 RAG、監査チェーン | 実装・試験済み |
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
