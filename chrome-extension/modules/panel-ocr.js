// modules/panel-ocr.js — OCR取込パネル
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.ocr = function renderOcrPanel(el, ctx) {
  el.innerHTML = `
    <input type="file" id="aisb-ocr-file" accept="image/*,application/pdf" />
    <button id="aisb-ocr-run">OCR実行</button>
    <div id="aisb-ocr-source"></div>
    <pre id="aisb-ocr-result"></pre>
  `;
  el.querySelector("#aisb-ocr-run").addEventListener("click", async () => {
    const fileInput = el.querySelector("#aisb-ocr-file");
    const resultEl = el.querySelector("#aisb-ocr-result");
    const sourceEl = el.querySelector("#aisb-ocr-source");
    sourceEl.textContent = "";
    sourceEl.className = "";
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
    } catch (e) {
      resultEl.textContent = `エラー: ${e}`;
    }
  });
};
