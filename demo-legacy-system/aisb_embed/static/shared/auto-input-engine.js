// shared/auto-input-engine.js
// 仕様書(1.2章)の shared/ 構成に名前が挙がっている自動入力エンジンのプレースホルダ。
//
// 正直な現状: 現時点でこのモジュールを呼び出しているパネルは存在しない。
// 実装予定の姿は「OCR取込パネル(panel-ocr)が抽出したフィールド値を、今開いている
// レガシー画面のフォーム(<input name="...">等)へ自動入力する」機能だが、レガシー
// フォームのDOM構造を書き換える機能は、この差分実装(自然言語→構造化フィルタ検索 /
// モジュール分割リファクタ)の依頼範囲外であり、かつフォーム書き込みは業務データを
// 誤って変更しうるため、ユーザーの明示的な合意なしに実装しない。
//
// ここでは「構造だけ仕様書通りに用意し、機能は空」であることを隠さずコメントする。
// 実装する場合は、対象フォームの要素をどう安全に特定するか(name属性の対応表を
// プロファイル側に持たせる等)を含めて設計してから着手すること。
window.AISB = window.AISB || {};

window.AISB.autoInputEngine = (function () {
  function isImplemented() {
    return false;
  }

  function fillForm() {
    throw new Error(
      "auto-input-engine は未実装のプレースホルダです。レガシーフォームへの自動書き込みは未合意のため実装していません。"
    );
  }

  return { isImplemented, fillForm };
})();
