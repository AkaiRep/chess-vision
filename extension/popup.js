// Popup: server address, discovery + pairing, connection status. Uses net.js.

"use strict";

const $ = (id) => document.getElementById(id);

function showStatus(status) {
  if (!status) return;
  $("dot").className = status.ok ? "ok" : "err";
  $("text").textContent = status.text;
  $("time").textContent = status.time ? new Date(status.time).toLocaleTimeString() : "";
}

function busy(on) {
  $("connect").disabled = $("discover").disabled = on;
}

async function connect(server) {
  $("action").textContent = `Проверяю ${server}…`;
  if (!(await isServer(server))) throw new Error(`на ${server} нет сервера chess-vision`);
  $("server").value = server;
  await pairAndSave(server);
  await chrome.storage.local.set({ status: { ok: true, text: "Подключено, жду позицию с chess.com", time: Date.now() } });
  $("action").textContent = "Подключено. Позиции с открытых вкладок chess.com уйдут в течение нескольких секунд.";
}

async function run(task) {
  busy(true);
  try {
    await task();
  } catch (e) {
    $("action").textContent = "Ошибка: " + (e.message || e);
  } finally {
    busy(false);
  }
}

$("connect").onclick = () =>
  run(async () => {
    const server = normalizeServer($("server").value);
    if (!server) throw new Error("введите адрес мака, например 192.168.1.5");
    await connect(server);
  });

$("discover").onclick = () =>
  run(async () => {
    const saved = (await chrome.storage.local.get("server")).server;
    let found = saved && (await isServer(saved)) ? saved : "";
    if (!found) {
      found = await discoverServer((done, total) => {
        $("action").textContent = `Ищу сервер в сети… ${Math.round((done / total) * 100)}%`;
      });
    }
    if (!found) throw new Error("сервер не найден. Введите IP мака вручную (он печатается при старте сервера).");
    await connect(found);
  });

chrome.storage.local.get(["server", "status"]).then(({ server, status }) => {
  if (server) $("server").value = server;
  showStatus(status);
});
chrome.storage.onChanged.addListener((changes) => {
  if (changes.status) showStatus(changes.status.newValue);
});
