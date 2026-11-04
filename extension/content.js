// Watches the chess.com board and hands every new position to background.js, which posts it
// to the chess-vision server. Runs all the time; the server decides whether to use it.
// Uses findBoard / readBoard from board.js (loaded first, see manifest.json).

"use strict";

(() => {
  const SETTLE_MS = 150; // read once the board has been quiet this long (animations)
  const SCAN_MS = 1000; // look for a (new) board: chess.com navigates without page reloads
  const RETRY_MS = 3000; // server unreachable / not paired / other source selected
  const PROBLEM_MS = 2000; // report a problem only if it lasts this long (re-renders are transient)

  let board = null;
  let observer = null;
  let settleTimer = null;
  let retryTimer = null;
  let current = null; // last position read from the page
  let currentKey = "";
  let deliveredKey = "";
  let sending = false;
  let lastReport = "";
  let failingSince = 0;
  let problemShown = false;

  // Problems go to the popup status, but only from the visible tab and only when they change.
  function report(text, ok = false) {
    if (!alive() || document.visibilityState !== "visible" || text === lastReport) return;
    lastReport = text;
    chrome.runtime.sendMessage({ type: "diag", ok, text }).catch(() => {});
  }

  // A board that cannot be read / is not there: tell the popup only once it persists.
  function problem(text) {
    const now = Date.now();
    if (!failingSince) failingSince = now;
    if (now - failingSince < PROBLEM_MS) return;
    problemShown = true;
    report(text);
  }

  // The board reads fine again: clear a problem shown earlier, even if the position is unchanged.
  function recovered(key) {
    failingSince = 0;
    if (!problemShown) return;
    problemShown = false;
    lastReport = "";
    if (key === deliveredKey) report("Доска читается, позиция на сервере актуальна", true);
  }

  function alive() {
    return Boolean(chrome.runtime && chrome.runtime.id); // false after the extension is reloaded
  }

  function attach() {
    const found = findBoard(document);
    if (found === board) return;
    if (observer) observer.disconnect();
    board = found;
    observer = null;
    if (!board) return;
    observer = new MutationObserver(settle);
    const options = { subtree: true, childList: true, attributes: true, attributeFilter: ["class"] };
    observer.observe(board, options);
    if (board.shadowRoot) observer.observe(board.shadowRoot, options);
    settle();
  }

  function settle() {
    clearTimeout(settleTimer);
    settleTimer = setTimeout(read, SETTLE_MS);
  }

  function read() {
    settleTimer = null;
    if (!board || !board.isConnected) return;
    const result = readBoard(board);
    if (!result.ok) {
      settle(); // look again shortly: usually a re-render or an animation
      problem("Доска найдена, но не читается: " + result.detail);
      return;
    }
    current = {
      placement: result.placement,
      flipped: result.flipped,
      highlighted: result.highlighted,
      site: "chess.com",
    };
    currentKey = JSON.stringify(current);
    recovered(currentKey);
    send();
  }

  async function send() {
    if (sending || !current || currentKey === deliveredKey) return;
    if (!alive()) return stop();
    sending = true;
    const key = currentKey;
    let delivered = false;
    try {
      const reply = await chrome.runtime.sendMessage({ type: "position", position: current });
      delivered = Boolean(reply && reply.delivered);
    } catch (e) {
      delivered = false; // worker restarting or extension reloaded
    }
    sending = false;
    if (delivered) deliveredKey = key;
    if (currentKey !== deliveredKey) {
      clearTimeout(retryTimer);
      retryTimer = setTimeout(send, delivered ? 0 : RETRY_MS);
    }
  }

  let scanTimer = null;
  function stop() {
    clearInterval(scanTimer);
    clearTimeout(settleTimer);
    clearTimeout(retryTimer);
    if (observer) observer.disconnect();
  }

  scanTimer = setInterval(() => {
    if (!alive()) return stop();
    attach();
    if (!board) problem("Доска не найдена: " + describePage(document));
    else if (!settleTimer) settle(); // safety net in case a mutation was missed
  }, SCAN_MS);
  report("Вкладка chess.com подключена, ищу доску…", true);
  attach();
})();
