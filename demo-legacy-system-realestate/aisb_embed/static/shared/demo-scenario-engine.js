// shared/demo-scenario-engine.js
// 「一目でわかる」ための一括自動演示(シナリオ再生)エンジン。
//
// 背景: templates/ai_intro.html の機能カードは説明を読むだけで、実際にパネルが
// 動く様子を見せられていなかった(=「わかるけど使い方がわからない」)。これを解消する
// ために、各カードから「▶ 自動デモを見る」で対応パネルを自動操作し、AIが使う様子を
// そのまま再生する。データは shared/demo-scenarios.js(システムごとに1本)側で宣言する。
//
// 設計方針(shared/auto-input-engine.js と同じ赤線を継承する):
//   1. 演示の開始は必ずユーザーのクリックが起点(自動では絶対に発火しない)。
//   2. 「送信(submit/新規登録の保存)」は演示の対象にしない。auto-input-engine.jsの
//      openAndFillと同じ境界で、フォームへの反映までは自動化してよいが、レガシー画面上の
//      保存ボタンを押す最終確定操作は必ず人間が行う(=fillForm自体がsubmitを呼ばない設計と
//      一致させる)。
//   3. 途中でユーザーが自分でパネルを操作したら、演示は即座に停止して操作を返す
//      (本物のユーザー操作と演示中の自動操作を奪い合わない)。
//   4. 常に「■ 停止」ボタンで中断できる。
//
// 2026-09-18: 企業・物件検索の「新規登録ページを開いて自動入力」(=openAndFill経由で
// window.open()する)をシナリオに組み込むにあたり、上記2の運用を1点拡張した。
// window.open()はブラウザの「trusted user activationからそう時間が経っていない」
// 制約に縛られており、演示エンジンのel.click()(narrate用のsleepを何度も挟んだ後に
// 発火する合成クリック)から呼ぶとポップアップブロックされる可能性が高い。これを
// 「対象外」で片付けるのではなく、その1クリックだけ本物のユーザー操作に委ねる
// clickReal ステップ(下記)を新設して解決した。openAndFill自体は送信(submit)を
// 一切行わないため、上記の赤線2には抵触しない — 保存の最終確定は従来どおり開いた
// タブ側で人間が行う。
//
// 実装メモ: aisb_embed/static/modules/bootstrap.js は uiBase.initShell() の戻り値
// (host/shadow/root/showPanel)を window.AISB.shell に保持している。shadow は
// mode:"closed" だが、closed が制限するのは外部コードが `host.shadowRoot` から
// 新規に参照を取得することだけであり、bootstrap.js が保持している参照そのものを
// 経由したDOM操作(querySelector/appendChildなど)は問題なく行える。本エンジンは
// その参照を使ってパネル内の要素を操作する。
//
// 2026-09-18: OCR取込のデモ化にあたり、clickRealとは別種の「1点だけ人に委ねる」
// ステップ waitForFileSelected を新設した。input[type=file]の.filesはブラウザが
// read-only保護しておりJSから代入できない(window.open()のポップアップブロックとは
// 異なり回避策自体が存在しない)。そのためファイル選択の1操作だけを人間に委ね、
// それ以外(サンプル画像ダウンロード〜OCR実行〜登録〜自動入力)は既存パターンで
// 自動再生する半自動デモとした。ファイル選択ダイアログを開くクリック自体もclosed
// shadow境界ではshell.hostへのmousedownとして観測されるため、奪い合い防止の
// 即停止ロジックはこの待機中も(clickReal同様)一時的に無効化する必要がある。
window.AISB = window.AISB || {};

window.AISB.demoEngine = (function () {
  const HIGHLIGHT_CLASS = "aisb-demo-highlight";

  let state = "idle"; // idle | running | done
  let runToken = 0;
  let overlay = null;
  let takeoverWired = false;
  // clickReal 実行中のみ設定される。この間はテイクオーバー検知(奪い合い防止)を
  // 一時的に緩める — このクリック自体が「演示の一部として意図的にユーザーへ
  // 委ねた本物のクリック」であり、停止すべき「割り込み」ではないため。
  let pendingRealClick = null;
  // waitForFileSelected 実行中のみ true。ファイル選択ダイアログを開くクリックも
  // shell.hostへのmousedownとして観測されるため、pendingRealClickと同じ理由で
  // テイクオーバー検知をこの間だけ緩める。
  let pendingUserWait = false;

  function isAlive(token) {
    return token === runToken;
  }

  function assertAlive(token) {
    if (!isAlive(token)) {
      const err = new Error("interrupted");
      err.aisbInterrupted = true;
      throw err;
    }
  }

  function sleep(ms, token) {
    return new Promise((resolve) => setTimeout(resolve, ms)).then(() => {
      assertAlive(token);
    });
  }

  function getShell() {
    return window.AISB && window.AISB.shell;
  }

  // ---- ナレーション用オーバーレイ ----
  // ページ本体のlight DOM(document.body直下)に出す。閉じたshadow DOMの外側なので
  // sidebar.cssには依存せず、static/css/site.css 側の .aisb-demo-* クラスだけを使う。
  function ensureOverlay() {
    if (overlay) return overlay;
    const bubble = document.createElement("div");
    bubble.className = "aisb-demo-bubble";
    const text = document.createElement("div");
    text.className = "aisb-demo-bubble-text";
    const stopBtn = document.createElement("button");
    stopBtn.type = "button";
    stopBtn.className = "aisb-demo-bubble-stop";
    stopBtn.textContent = "■ 停止";
    stopBtn.addEventListener("click", () => stop());
    bubble.appendChild(text);
    bubble.appendChild(stopBtn);
    document.body.appendChild(bubble);
    overlay = { bubble, text, stopBtn };
    return overlay;
  }

  function removeOverlay() {
    if (overlay) {
      overlay.bubble.remove();
      overlay = null;
    }
  }

  function narrate(msg) {
    ensureOverlay().text.textContent = msg;
  }

  // ---- パネル内ハイライト ----
  function ensureShadowStyle(shadow) {
    if (shadow.querySelector("#aisb-demo-style")) return;
    const style = document.createElement("style");
    style.id = "aisb-demo-style";
    style.textContent = `
      .${HIGHLIGHT_CLASS} {
        outline: 3px solid #f6a623 !important;
        outline-offset: 2px;
        border-radius: 4px;
        animation: aisb-demo-pulse 1.1s ease-in-out 1;
      }
      @keyframes aisb-demo-pulse {
        0% { box-shadow: 0 0 0 0 rgba(246,166,35,.55); }
        70% { box-shadow: 0 0 0 9px rgba(246,166,35,0); }
        100% { box-shadow: 0 0 0 0 rgba(246,166,35,0); }
      }
    `;
    shadow.appendChild(style);
  }

  function highlight(shadow, el) {
    if (!el) return;
    ensureShadowStyle(shadow);
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add(HIGHLIGHT_CLASS);
    setTimeout(() => el.classList.remove(HIGHLIGHT_CLASS), 1200);
  }

  async function waitFor(shadow, selector, token, timeoutMs) {
    const deadline = Date.now() + (timeoutMs || 8000);
    for (;;) {
      assertAlive(token);
      const el = shadow.querySelector(selector);
      if (el) return el;
      if (Date.now() >= deadline) {
        throw new Error(`要素が見つかりませんでした(${selector})`);
      }
      await sleep(150, token);
    }
  }

  // el のtextContentに substr を含むまで待つ(例: 自動入力後のステータス文言確認)。
  // timeoutMs経過しても含まれなければ、そのまま処理を続行する(エラーにはしない —
  // 文言確認はあくまで演出であり、これが原因で演示全体を失敗させたくないため)。
  async function waitForText(shadow, selector, substr, token, timeoutMs) {
    const el = await waitFor(shadow, selector, token, timeoutMs);
    const deadline = Date.now() + (timeoutMs || 8000);
    while (!(el.textContent || "").includes(substr)) {
      assertAlive(token);
      if (Date.now() >= deadline) break;
      await sleep(150, token);
    }
    return el;
  }

  // 合成クリック(el.click())ではなく、ユーザー自身の本物のクリック(isTrusted)を
  // 待つ。window.open()を伴う操作はブラウザのポップアップブロック対策上、本物の
  // ユーザー操作から呼ぶ必要があるため、この1クリックだけは演示側から発火しない。
  function waitForRealClick(el, token) {
    return new Promise((resolve, reject) => {
      const entry = { el };
      pendingRealClick = entry;
      let interruptTimer = null;
      function finish(fn, arg) {
        if (pendingRealClick !== entry) return;
        pendingRealClick = null;
        el.removeEventListener("click", onClick, true);
        clearInterval(interruptTimer);
        fn(arg);
      }
      function onClick(e) {
        if (!e.isTrusted) return;
        finish(resolve);
      }
      el.addEventListener("click", onClick, true);
      interruptTimer = setInterval(() => {
        if (!isAlive(token)) {
          finish(reject, Object.assign(new Error("interrupted"), { aisbInterrupted: true }));
        }
      }, 200);
    });
  }

  // input[type=file]へのファイル選択(change, files.length>0)を待つ。.filesは
  // ブラウザがread-only保護しておりJSから代入不可能なため、この1操作だけは
  // waitForRealClickと同じ考え方でユーザー自身に委ねる。
  function waitForFileSelected(el, token) {
    return new Promise((resolve, reject) => {
      pendingUserWait = true;
      let interruptTimer = null;
      function finish(fn, arg) {
        if (!pendingUserWait) return;
        pendingUserWait = false;
        el.removeEventListener("change", onChange);
        clearInterval(interruptTimer);
        fn(arg);
      }
      function onChange() {
        if (el.files && el.files.length > 0) finish(resolve);
      }
      el.addEventListener("change", onChange);
      interruptTimer = setInterval(() => {
        if (!isAlive(token)) {
          finish(reject, Object.assign(new Error("interrupted"), { aisbInterrupted: true }));
        }
      }, 200);
    });
  }

  async function typeInto(el, value, token) {
    el.focus();
    el.value = "";
    for (const ch of String(value)) {
      assertAlive(token);
      el.value += ch;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      await sleep(30, token);
    }
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function openPanel(shell, panelId, token) {
    if (shell.root.classList.contains("aisb-collapsed")) {
      shell.root.querySelector("#aisb-toggle").click();
      await sleep(350, token);
    }
    shell.showPanel(panelId);
    await sleep(350, token);
  }

  async function runStep(shell, step, token) {
    switch (step.type) {
      case "narrate":
        narrate(step.text);
        await sleep(step.delayMs || 900, token);
        return;
      case "openPanel":
        if (step.text) narrate(step.text);
        await openPanel(shell, step.panel, token);
        return;
      case "highlight": {
        const el = await waitFor(shell.shadow, step.selector, token, step.timeoutMs);
        highlight(shell.shadow, el);
        await sleep(500, token);
        return;
      }
      case "setValue": {
        const el = await waitFor(shell.shadow, step.selector, token, step.timeoutMs);
        highlight(shell.shadow, el);
        await sleep(200, token);
        await typeInto(el, step.value, token);
        return;
      }
      case "click": {
        const el = await waitFor(shell.shadow, step.selector, token, step.timeoutMs);
        highlight(shell.shadow, el);
        await sleep(350, token);
        assertAlive(token);
        el.click();
        return;
      }
      case "waitFor":
        await waitFor(shell.shadow, step.selector, token, step.timeoutMs);
        return;
      case "waitForText":
        await waitForText(shell.shadow, step.selector, step.contains || "", token, step.timeoutMs);
        return;
      case "clickReal": {
        const el = await waitFor(shell.shadow, step.selector, token, step.timeoutMs);
        highlight(shell.shadow, el);
        if (step.text) narrate(step.text);
        await waitForRealClick(el, token);
        return;
      }
      case "waitForFileSelected": {
        const el = await waitFor(shell.shadow, step.selector, token, step.timeoutMs);
        highlight(shell.shadow, el);
        if (step.text) narrate(step.text);
        await waitForFileSelected(el, token);
        return;
      }
      default:
        return;
    }
  }

  // ユーザーが演示の途中で自分でパネルを操作したら、即座に演示を止めて操作を返す。
  // closed shadow内で発生したイベントも、documentまでバブリングする際にはtargetが
  // シャドウホスト(shell.host)へ再ターゲット化される(Shadow DOM仕様の挙動)ため、
  // documentでの捕捉時に e.target === shell.host かどうかで判定できる。
  // 本エンジン自身の操作はすべて el.click() 等のスクリプト発火であり、実ポインタ由来の
  // mousedownイベント自体が発生しないため、これで「本物のユーザー操作」とだけ判別できる。
  function wireTakeover() {
    if (takeoverWired) return;
    takeoverWired = true;
    document.addEventListener(
      "mousedown",
      (e) => {
        if (state !== "running") return;
        if (overlay && overlay.bubble.contains(e.target)) return;
        const shell = getShell();
        if (shell && shell.host && e.target === shell.host) {
          // clickReal/waitForFileSelectedが待っている本物の操作。奪い合いではない。
          if (pendingRealClick || pendingUserWait) return;
          stop();
        }
      },
      true
    );
  }

  async function run(scenario) {
    if (!scenario || !Array.isArray(scenario.steps)) return;
    const shell = getShell();
    if (!shell) {
      window.alert("AIパネルの初期化が完了していません。少し待ってからもう一度お試しください。");
      return;
    }
    wireTakeover();
    if (state === "running") stop();
    const token = ++runToken;
    state = "running";
    ensureOverlay();
    try {
      for (const step of scenario.steps) {
        assertAlive(token);
        await runStep(shell, step, token);
      }
      assertAlive(token);
      narrate(scenario.doneText || "デモが完了しました。続きは自由に操作してみてください。");
      state = "done";
      await sleep(2600, token);
    } catch (e) {
      if (!e || !e.aisbInterrupted) {
        narrate(`デモを中断しました(${(e && e.message) || "エラー"})`);
        await new Promise((resolve) => setTimeout(resolve, 2200));
      }
    } finally {
      if (token === runToken) {
        removeOverlay();
        state = "idle";
      }
    }
  }

  function stop() {
    runToken++;
    state = "idle";
    removeOverlay();
  }

  return {
    run,
    stop,
    getState: () => state,
  };
})();
