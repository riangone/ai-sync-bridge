// shared/auto-input-engine.js
// 仕様書(1.2章)の shared/ 構成に名前が挙がっている自動入力エンジン。
//
// 2026-08-20: ユーザーからの明示的な依頼(会社/物件検索の「登録用データを作る」結果を
// レガシー新規登録フォームに書き込みたい)を受けて実装。設計方針:
//   1. 書き込み先フォームを開く行為自体はユーザーがボタンをクリックした時のみ発生する
//      (自動では絶対に発火しない) — これが「明示的な合意」に相当する。
//   2. フィールドへの反映はするが、フォームの送信(submit)は絶対に行わない。
//      最終確認・送信は必ず人間がレガシー画面上のボタンを押して行う。
//   3. 対象フィールドの特定は name 属性の完全一致のみで行う。曖昧一致や推測入力はしない。
//      値が null/undefined/空文字のキーは「分からない項目」として書き込まずスキップする
//      (空文字で上書きして既存入力を消してしまう事故を防ぐため)。
//   4. web_search_service.py の register() が返す normalized JSON のキーは、そもそも
//      demo-legacy-system 側の CUSTOMER_FIELDS/PROPERTY_FIELDS の name 属性と1:1になる
//      よう設計済みなので、ここでは追加の対応表を持たない(name属性そのままで引き当てる)。
window.AISB = window.AISB || {};

window.AISB.autoInputEngine = (function () {
  function isImplemented() {
    return true;
  }

  function cssEscapeName(name) {
    if (window.CSS && typeof CSS.escape === "function") return CSS.escape(name);
    return String(name).replace(/(["\\])/g, "\\$1");
  }

  // doc: 書き込み対象のdocument(通常は新規登録ページを開いたwindowのdocument)
  // data: { フィールド名: 値 } (register()のnormalized JSONをそのまま渡す想定)
  // 戻り値: { filled: [name...], skipped: [name...] } — フォームのsubmitは行わない。
  function fillForm(doc, data) {
    const filled = [];
    const skipped = [];
    Object.keys(data || {}).forEach((key) => {
      const value = data[key];
      if (value === null || value === undefined || value === "") {
        skipped.push(key);
        return;
      }
      const field = doc.querySelector(`[name="${cssEscapeName(key)}"]`);
      if (!field || field.tagName === "BUTTON") {
        skipped.push(key);
        return;
      }
      field.value = String(value);
      field.dispatchEvent(new Event("input", { bubbles: true }));
      field.dispatchEvent(new Event("change", { bubbles: true }));
      filled.push(key);
    });
    return { filled, skipped };
  }

  // entryUrl: レガシーの新規登録ページURL(例: `${LEGACY_ORIGIN}/Customer/Entry`)
  // data: fillFormに渡すのと同じ正規化済みJSON
  // 新規タブで開き、フォームの描画完了を待ってから書き込む。タブを開くのも書き込むのも
  // このPromiseの呼び出し元(=ユーザーのボタンクリック)がきっかけであり、自動実行はしない。
  function openAndFill(entryUrl, data) {
    return new Promise((resolve, reject) => {
      const win = window.open(entryUrl, "_blank");
      if (!win) {
        reject(new Error("ポップアップがブロックされました。ブラウザのポップアップ許可設定を確認してください。"));
        return;
      }
      const deadline = Date.now() + 10000;
      let settled = false;
      function attempt() {
        if (settled) return;
        if (win.closed) {
          settled = true;
          reject(new Error("登録ページのタブが読み込み中に閉じられました。"));
          return;
        }
        let doc = null;
        try {
          doc = win.document;
        } catch (e) {
          doc = null; // クロスオリジン等でアクセス不可
        }
        if (doc && doc.readyState === "complete" && doc.querySelector("form")) {
          settled = true;
          try {
            resolve(fillForm(doc, data));
          } catch (e) {
            reject(e);
          }
          return;
        }
        if (Date.now() < deadline) {
          setTimeout(attempt, 200);
        } else {
          settled = true;
          reject(new Error("登録ページの読み込みがタイムアウトしました(フォームが見つかりません)。"));
        }
      }
      setTimeout(attempt, 250);
    });
  }

  return { isImplemented, fillForm, openAndFill };
})();
