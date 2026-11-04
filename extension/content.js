// Watches the chess.com board and hands every new position to background.js, which posts it
// to the chess-vision server. Runs all the time; the server decides whether to use it.
// Uses findBoard / readBoard from board.js (loaded first, see manifest.json).

"use strict";

(() => {
  const SETTLE_MS = 150; // read once the board has been quiet this long (animations)
  const SCAN_MS = 1000; // look for a (new) board: chess.com navigates without page reloads
  const RETRY_MS = 3000; // server unreachable / not paired / other source selected

  let board = null;
  let observer = null;
  let settleTimer = null;
  let retryTimer = null;
  let current = null; // last position read from the page
  let currentKey = "";
  let deliveredKey = "";
  let sending = false;

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
    observer.observe(board, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"] });
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
      if (result.reason === "busy") settle();
      return;
    }
    current = {
      placement: result.placement,
      flipped: result.flipped,
      highlighted: result.highlighted,
      site: "chess.com",
    };
    currentKey = JSON.stringify(current);
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
    if (board && !settleTimer) settle(); // safety net in case a mutation was missed
  }, SCAN_MS);
  attach();
})();
