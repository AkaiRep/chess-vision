// Service worker: posts positions from content.js to the chess-vision server.
// Requests go from here (not from the chess.com page), so the HTTPS page does not block
// plain-HTTP requests to the Mac in the local network.

"use strict";

importScripts("net.js");

async function setStatus(ok, text) {
  await chrome.storage.local.set({ status: { ok, text, time: Date.now() } });
}

// -> true when the server took the position; false = keep it and retry later.
async function deliver(position) {
  const { server, token } = await chrome.storage.local.get(["server", "token"]);
  if (!server) {
    await setStatus(false, "Адрес сервера не задан: откройте окно расширения и нажмите «Найти сервер».");
    return false;
  }
  let tok = token;
  try {
    if (!tok) tok = await pairAndSave(server);
    let r = await postPosition(server, tok, position);
    if (r.status === 401) {
      tok = await pairAndSave(server); // server got a new secret: try to pair again
      r = await postPosition(server, tok, position);
    }
    if (!r.ok) {
      await setStatus(false, `Сервер ответил ошибкой ${r.status}: ${r.body.detail || ""}`);
      return false;
    }
    if (r.body.status === "ignored") {
      await setStatus(true, "Связь есть, но " + r.body.message);
      return false; // resend once the source is switched on the page
    }
    if (r.body.status === "skipped") return true;
    await setStatus(true, "Позиция отправлена на сервер");
    return true;
  } catch (e) {
    await setStatus(false, `Нет связи с ${server}: ${e.message || e}`);
    return false;
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "position") {
    deliver(msg.position).then((delivered) => sendResponse({ delivered }));
    return true; // async response
  }
  return false;
});
