// レガシーシステム自体には AI 機能は一切ない。素のDOM操作のみ。
// 画面固有のロジック（受注入力の addItem()/recalcTotal() 等）は各テンプレートの
// インラインスクリプトに実装している。ここには全画面共通のユーティリティのみを置く。

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (ev) => {
            if (!window.confirm(form.dataset.confirm)) {
                ev.preventDefault();
            }
        });
    });
});
