// Talking to the chess-vision server; shared by background.js and popup.js.
// Endpoints and header mirror shared/protocol.py.

"use strict";

const DEFAULT_PORT = 8765;
const SERVICE_ID = "chess-vision";
const TOKEN_HEADER = "X-Chess-Vision-Token";
const POSITION_PATH = "/analyze/position";

// Common home subnets; the Mac is looked for on .1-.254 of each (a browser cannot ask for its own IP).
const SCAN_SUBNETS = ["192.168.0", "192.168.1", "192.168.178", "192.168.2", "192.168.31", "10.0.0", "10.0.1", "172.20.10"];
const SCAN_TIMEOUT_MS = 1200;
const SCAN_PARALLEL = 96;

// "192.168.1.5", "http://192.168.1.5:8765/" -> "192.168.1.5:8765"
function normalizeServer(text) {
  let s = String(text || "").trim().replace(/^https?:\/\//i, "").replace(/\/.*$/, "");
  if (!s) return "";
  if (!/:\d+$/.test(s)) s += ":" + DEFAULT_PORT;
  return s;
}

async function fetchJson(url, options = {}, timeoutMs = 15000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const resp = await fetch(url, { ...options, signal: ctrl.signal, cache: "no-store" });
    let body = {};
    try {
      body = await resp.json();
    } catch (e) {
      body = {};
    }
    return { ok: resp.ok, status: resp.status, body };
  } catch (e) {
    if (e.name === "AbortError") throw new Error("сервер не отвечает");
    throw new Error("сервер недоступен");
  } finally {
    clearTimeout(timer);
  }
}

async function isServer(server, timeoutMs = 3000) {
  try {
    const r = await fetchJson(`http://${server}/health`, {}, timeoutMs);
    return r.ok && r.body.service === SERVICE_ID;
  } catch (e) {
    return false;
  }
}

// Gets the token (only works in the first 10 minutes after the server starts) and stores it.
async function pairAndSave(server) {
  const r = await fetchJson(`http://${server}/pair`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: "chrome-extension" }),
  });
  if (!r.ok || !r.body.token) {
    throw new Error(
      r.status === 403
        ? "сопряжение закрыто: перезапустите сервер на маке и подключитесь в течение 10 минут"
        : `сопряжение не удалось (${r.status})`
    );
  }
  await chrome.storage.local.set({ server, token: r.body.token });
  return r.body.token;
}

function postPosition(server, token, position) {
  return fetchJson(`http://${server}${POSITION_PATH}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", [TOKEN_HEADER]: token },
    body: JSON.stringify(position),
  });
}

// Scans the common subnets for /health. onProgress(done, total). -> "ip:port" or "".
async function discoverServer(onProgress) {
  const hosts = [];
  for (const net of SCAN_SUBNETS) for (let i = 1; i <= 254; i++) hosts.push(`${net}.${i}:${DEFAULT_PORT}`);
  let next = 0;
  let done = 0;
  let found = "";
  async function worker() {
    while (!found && next < hosts.length) {
      const host = hosts[next++];
      if (await isServer(host, SCAN_TIMEOUT_MS)) found = found || host;
      done++;
      if (onProgress) onProgress(done, hosts.length);
    }
  }
  await Promise.all(Array.from({ length: SCAN_PARALLEL }, worker));
  return found;
}
