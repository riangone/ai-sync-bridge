// modules/panel-ocr.js — OCR取込パネル
//
// 2026-08-31: 「登録用データを作る→新規登録ページを開いて自動入力」の導線を、
// 仕入先検索(panel-web-search.js + shared/auto-input-engine.js)からOCRにも展開した。
// OCRが読み取れるのは他エンティティへのDB参照(select)を持たない自由入力フォームのみ
// (Order/Estimate/PurchaseOrder/Invoice/GoodsReceipt/ServiceOrder等はCustomerId等の
// FK selectが必須で、OCRは既存レコードのIDを読み取れないため対象外——これは
// CompanySearchService/PropertySearchServiceがCustomer/Supplier/Propertyのみを登録先に
// しているのと同じ判断基準)。対象エンティティはinstance("erp"|"dealer")によって
// 出し分ける(サーバー側 GET /api/ocr/entities が単一の判断元)。
//
// テスト用画像もエンティティ選択に連動させた: 対象フォームの項目に合わせたラベル
// (例: Customerなら「会社名/住所/TEL」、Propertyなら「物件名/価格」)でCanvas生成する。
// これはサーバー側 OcrService.FIELD_SYNONYMS_BY_INSTANCE のキー(日本語ラベル)と
// 一致させてあるため、実ビジョンでの読み取り結果がそのまま正規化にヒットする。
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

// エンティティごとのサンプル画像に載せる項目(ラベルはサーバー側の日本語synonymと一致させる)。
// dealerではCustomerの呼称/項目が異なる(氏名/会社名・運転免許証番号等)ため、instance毎に定義。
const OCR_ENTITY_SAMPLES = {
  erp: {
    Customer: {
      label: "会社(顧客)",
      title: "取引先情報 (OCRテスト用サンプル)",
      lines: [
        ["会社名", "サンプル商事株式会社"],
        ["カナ", "サンプルショウジ"],
        ["代表者", "山田 太郎"],
        ["郵便番号", "100-0001"],
        ["住所", "東京都千代田区千代田1-1"],
        ["TEL", "03-1234-5678"],
        ["資本金", "10000000"],
        ["業種", "卸売業"],
      ],
    },
    Supplier: {
      label: "仕入先",
      title: "仕入先情報 (OCRテスト用サンプル)",
      lines: [
        ["仕入先名", "サンプル物流株式会社"],
        ["カテゴリ", "運送業"],
        ["TEL", "03-2345-6789"],
        ["住所", "東京都江東区豊洲2-2"],
        ["担当者", "佐藤 次郎"],
        ["与信枠", "3000000"],
      ],
    },
    Employee: {
      label: "社員",
      title: "社員名簿 (OCRテスト用サンプル)",
      lines: [
        ["氏名", "鈴木 花子"],
        ["部署", "営業部"],
        ["役職", "主任"],
        ["メール", "hanako.suzuki@example.com"],
        ["TEL", "090-1111-2222"],
      ],
    },
    Property: {
      label: "物件",
      title: "物件概要書 (OCRテスト用サンプル)",
      lines: [
        ["物件名", "サンプルビル 3F"],
        ["住所", "東京都渋谷区渋谷3-3"],
        ["価格", "98000000"],
        ["築年月", "2015-04"],
        ["構造", "SRC造"],
      ],
    },
  },
  dealer: {
    Customer: {
      label: "顧客",
      title: "顧客情報 (OCRテスト用サンプル)",
      lines: [
        ["氏名", "田中 一郎"],
        ["カナ", "タナカ イチロウ"],
        ["郵便番号", "150-0002"],
        ["住所", "東京都渋谷区渋谷1-1"],
        ["TEL", "090-3333-4444"],
        ["運転免許証番号", "123456789012"],
      ],
    },
    Supplier: {
      label: "仕入先",
      title: "仕入先情報 (OCRテスト用サンプル)",
      lines: [
        ["仕入先名", "サンプルオークション会場"],
        ["カテゴリ", "オークション"],
        ["TEL", "03-4567-8901"],
        ["住所", "千葉県千葉市美浜区1-1"],
        ["担当者", "高橋 三郎"],
        ["与信枠", "5000000"],
      ],
    },
    Employee: {
      label: "社員",
      title: "社員名簿 (OCRテスト用サンプル)",
      lines: [
        ["氏名", "伊藤 健"],
        ["部署", "整備部"],
        ["役職", "整備士"],
        ["メール", "ken.ito@example.com"],
        ["TEL", "090-5555-6666"],
      ],
    },
  },
};

// OCR動作確認用のサンプル画像(選択中のエンティティの項目を反映した帳票風テキスト)を
// Canvasで生成してPNGダウンロードさせる。バックエンドの静的アセットに依存せず、
// このファイル単体で完結させるための実装。
function downloadOcrSampleImage(sample) {
  const canvas = document.createElement("canvas");
  canvas.width = 800;
  canvas.height = 120 + sample.lines.length * 44 + 60;
  const g = canvas.getContext("2d");
  g.fillStyle = "#ffffff";
  g.fillRect(0, 0, canvas.width, canvas.height);
  g.strokeStyle = "#333333";
  g.lineWidth = 2;
  g.strokeRect(20, 20, canvas.width - 40, canvas.height - 40);
  g.fillStyle = "#000000";
  g.font = "bold 28px sans-serif";
  g.fillText(sample.title, 50, 70);
  g.font = "20px sans-serif";
  sample.lines.forEach(([k, v], i) => g.fillText(`${k}: ${v}`, 50, 130 + i * 44));
  g.font = "13px sans-serif";
  g.fillStyle = "#666666";
  g.fillText("このファイルはOCR機能の動作確認用に自動生成されたテスト画像です。", 50, canvas.height - 30);

  canvas.toBlob((blob) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "ocr-test-sample.png";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }, "image/png");
}

window.AISB.panels.ocr = function renderOcrPanel(el, ctx) {
  const isDealer = ctx.INSTANCE === "dealer";
  const samples = OCR_ENTITY_SAMPLES[isDealer ? "dealer" : "erp"];
  const entityKeys = Object.keys(samples);

  el.innerHTML = `
    <div class="aisb-inline-row">
      <select id="aisb-ocr-entity">
        ${entityKeys.map((k) => `<option value="${k}">${samples[k].label}</option>`).join("")}
      </select>
      <button id="aisb-ocr-sample-download">📥 テスト用画像をダウンロード</button>
    </div>
    <p style="font-size:11px;color:#666;margin:4px 0 10px;">
      選択した登録先フォームに合わせたOCR動作確認用サンプル画像です。ダウンロード後、下のファイル選択で読み込んでください。
    </p>
    <input type="file" id="aisb-ocr-file" accept="image/*,application/pdf" />
    <button id="aisb-ocr-run">OCR実行</button>
    <div id="aisb-ocr-source"></div>
    <pre id="aisb-ocr-result"></pre>
    <div id="aisb-ocr-register-area"></div>
  `;

  const entitySelect = el.querySelector("#aisb-ocr-entity");

  el.querySelector("#aisb-ocr-sample-download").addEventListener("click", () => {
    downloadOcrSampleImage(samples[entitySelect.value]);
  });

  // 「登録用データを作る」→「新規登録ページを開いて自動入力」の描画・配線。
  // panel-web-search.js の renderRegisterBtn()/wireAutofillBtn() と同じ構造。
  function renderRegisterArea() {
    return `<div class="aisb-btn-row">
        <button class="aisb-ocr-register-btn aisb-btn-secondary">登録用データを作る</button>
        <button class="aisb-ocr-autofill-btn aisb-btn-secondary" style="display:none">新規登録ページを開いて自動入力</button>
      </div>
      <pre class="aisb-ocr-normalized" style="display:none"></pre>
      <p class="aisb-ocr-autofill-status" style="display:none"></p>`;
  }

  function wireAutofillBtn(area, entryEntity, normalizedData) {
    const autofillBtn = area.querySelector(".aisb-ocr-autofill-btn");
    const statusEl = area.querySelector(".aisb-ocr-autofill-status");
    autofillBtn.style.display = "inline-block";
    autofillBtn._aisbNormalizedData = normalizedData;
    if (autofillBtn.dataset.wired) return;
    autofillBtn.dataset.wired = "1";
    autofillBtn.addEventListener("click", () => {
      const entryUrl = `${ctx.LEGACY_ORIGIN}/${entryEntity}/Entry`;
      statusEl.style.display = "block";
      statusEl.textContent = "登録ページを開いています...";
      window.AISB.autoInputEngine
        .openAndFill(entryUrl, autofillBtn._aisbNormalizedData)
        .then(({ filled, skipped }) => {
          statusEl.textContent =
            `✅ ${filled.length}項目を自動入力しました(${filled.join(", ")})。` +
            (skipped.length ? ` 未入力: ${skipped.join(", ")}(値が不明なため空欄のままです)。` : "") +
            " 内容を確認のうえ、開いたタブ側で保存してください(自動送信はしていません)。";
        })
        .catch((e) => {
          statusEl.textContent = `⚠ 自動入力に失敗しました: ${e.message || e}`;
        });
    });
  }

  el.querySelector("#aisb-ocr-run").addEventListener("click", async () => {
    const fileInput = el.querySelector("#aisb-ocr-file");
    const resultEl = el.querySelector("#aisb-ocr-result");
    const sourceEl = el.querySelector("#aisb-ocr-source");
    const registerArea = el.querySelector("#aisb-ocr-register-area");
    sourceEl.textContent = "";
    sourceEl.className = "";
    registerArea.innerHTML = "";
    if (!fileInput.files[0]) {
      resultEl.textContent = "ファイルを選択してください";
      return;
    }
    const file = fileInput.files[0];
    const fd = new FormData();
    fd.append("file", file);
    resultEl.textContent = "解析中...";
    try {
      const res = await fetch(`${ctx.API_BASE}/api/ocr`, { method: "POST", body: fd });
      const data = await res.json();
      if (data.source === "opencode-vision") {
        sourceEl.className = "aisb-ws-source aisb-ws-source-real";
        sourceEl.textContent = "🌐 AIビジョンによる実読み取り結果";
      } else if (data.source === "opencode-vision-pdf") {
        sourceEl.className = "aisb-ws-source aisb-ws-source-real";
        sourceEl.textContent = "🌐 AIビジョンによる実読み取り結果(PDFをページ毎に画像化して解析)";
      } else {
        sourceEl.className = "aisb-ws-source aisb-ws-source-mock";
        sourceEl.textContent = file.type === "application/pdf"
          ? "⚠ 演示用の疑似データ(PDF画像化またはAIビジョン接続に失敗)"
          : "⚠ 演示用の疑似データ(AIビジョン未接続)";
      }
      resultEl.textContent = JSON.stringify(data, null, 2);

      if (data.fields && Object.keys(data.fields).length) {
        registerArea.innerHTML = renderRegisterArea();
        registerArea.querySelector(".aisb-ocr-register-btn").addEventListener("click", () => {
          const entity = entitySelect.value;
          const pre = registerArea.querySelector(".aisb-ocr-normalized");
          ctx
            .postJson(`${ctx.API_BASE}/api/ocr/register`, { fields: data.fields, entity })
            .then((res) => {
              pre.textContent = JSON.stringify(res.normalized, null, 2);
              pre.style.display = "block";
              wireAutofillBtn(registerArea, res.entry_entity || entity, res.normalized);
            })
            .catch((e) => alert(`エラー: ${e}`));
        });
      }
    } catch (e) {
      resultEl.textContent = `エラー: ${e}`;
    }
  });
};
