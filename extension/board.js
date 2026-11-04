// Reading the chess.com board out of the page DOM. No Chrome APIs here: the same file is
// loaded as a content script and by the Node tests (extension/tests/).
//
// chess.com markup:
//   <wc-chess-board class="board flipped">           "flipped" = black at the bottom
//     <div class="piece wp square-52"></div>           white pawn on e2 (file 5 = e, rank 2)
//     <div class="highlight square-54" style="background-color: ..."></div>   last move
//   </wc-chess-board>

"use strict";

const BOARD_SELECTOR = "wc-chess-board, chess-board";
const PIECE_RE = /(?:^|\s)([wb])([pnbrqk])(?=\s|$)/;
const SQUARE_RE = /(?:^|\s)square-([1-8])([1-8])(?=\s|$)/;
const MIN_BOARD_PX = 120; // smaller boards are thumbnails / previews

function squareName(file, rank) {
  return "abcdefgh"[file - 1] + rank;
}

function classOf(el) {
  return el.getAttribute("class") || "";
}

function isVisible(el) {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}

// Pieces may live in the board's (open) shadow root instead of its children.
function piecesRoot(boardEl) {
  const shadow = boardEl.shadowRoot;
  return shadow && shadow.querySelector(".piece") ? shadow : boardEl;
}

// For the popup when nothing can be read: what the page looks like.
function describePage(doc) {
  const boards = [...doc.querySelectorAll(BOARD_SELECTOR)].map((el) => {
    const r = el.getBoundingClientRect();
    return `${el.tagName.toLowerCase()} ${Math.round(r.width)}x${Math.round(r.height)}`;
  });
  const pieces = doc.querySelectorAll(".piece").length;
  return boards.length
    ? `доски на странице: ${boards.join(", ")} (меньше ${MIN_BOARD_PX}px не считаются); фигур .piece: ${pieces}`
    : `на странице нет элемента wc-chess-board / chess-board; фигур .piece: ${pieces}`;
}

// The main board of the page: the largest visible one.
function findBoard(doc) {
  let best = null;
  let bestArea = 0;
  for (const el of doc.querySelectorAll(BOARD_SELECTOR)) {
    const r = el.getBoundingClientRect();
    const area = r.width * r.height;
    if (r.width >= MIN_BOARD_PX && r.height >= MIN_BOARD_PX && area > bestArea) {
      best = el;
      bestArea = area;
    }
  }
  return best;
}

// Two highlighted squares of one colour, exactly one of them occupied = the last move.
// Squares marked with a right click have another colour and are left out.
function lastMoveSquares(boardEl, grid) {
  const groups = new Map();
  for (const el of boardEl.querySelectorAll(".highlight")) {
    const m = SQUARE_RE.exec(classOf(el));
    if (!m) continue;
    const color = (el.style && el.style.backgroundColor) || "";
    if (!groups.has(color)) groups.set(color, new Set());
    groups.get(color).add(m[1] + m[2]);
  }
  const candidates = [];
  for (const squares of groups.values()) {
    if (squares.size !== 2) continue;
    const pair = [...squares];
    const occupied = pair.filter((s) => grid[+s[1] - 1][+s[0] - 1] !== null).length;
    if (occupied === 1) candidates.push(pair);
  }
  if (candidates.length !== 1) return [];
  return candidates[0].map((s) => squareName(+s[0], +s[1]));
}

// -> {ok: true, placement, flipped, highlighted} or {ok: false, reason, detail}.
// reason "busy" means "read again a bit later" (piece being dragged, promotion dialog, animation).
function readBoard(boardEl) {
  const root = piecesRoot(boardEl);
  if (root.querySelector(".dragging")) return { ok: false, reason: "busy", detail: "фигуру тащат мышкой" };
  const promo = root.querySelector(".promotion-window");
  if (promo && isVisible(promo)) return { ok: false, reason: "busy", detail: "открыт выбор фигуры" };

  const grid = Array.from({ length: 8 }, () => Array(8).fill(null)); // grid[rank-1][file-1]
  let whiteKings = 0;
  let blackKings = 0;
  let count = 0;
  let unparsed = "";
  for (const el of root.querySelectorAll(".piece")) {
    const cls = classOf(el);
    if (/(?:^|\s)ghost(?=\s|$)/.test(cls)) continue;
    const p = PIECE_RE.exec(cls);
    const s = SQUARE_RE.exec(cls);
    if (!p || !s) {
      unparsed = unparsed || cls; // pieces outside the board (promotion choices etc.)
      continue;
    }
    const file = +s[1];
    const rank = +s[2];
    if (grid[rank - 1][file - 1] !== null) return { ok: false, reason: "busy", detail: "две фигуры на одной клетке" };
    grid[rank - 1][file - 1] = p[1] === "w" ? p[2].toUpperCase() : p[2];
    if (p[2] === "k") p[1] === "w" ? whiteKings++ : blackKings++;
    count++;
  }
  const sample = unparsed ? `; непонятный класс фигуры: "${unparsed}"` : "";
  if (count === 0) return { ok: false, reason: "empty", detail: "на доске не найдено ни одной фигуры" + sample };
  if (whiteKings !== 1 || blackKings !== 1 || count > 32) {
    return {
      ok: false,
      reason: "incomplete",
      detail: `фигур ${count}, белых королей ${whiteKings}, чёрных ${blackKings}` + sample,
    };
  }

  const rows = [];
  for (let rank = 8; rank >= 1; rank--) {
    let row = "";
    let empty = 0;
    for (let file = 1; file <= 8; file++) {
      const piece = grid[rank - 1][file - 1];
      if (piece === null) {
        empty++;
      } else {
        if (empty) row += empty;
        row += piece;
        empty = 0;
      }
    }
    rows.push(empty ? row + empty : row);
  }
  return {
    ok: true,
    placement: rows.join("/"),
    flipped: boardEl.classList.contains("flipped"),
    highlighted: lastMoveSquares(root, grid),
  };
}

if (typeof module !== "undefined") module.exports = { findBoard, readBoard, describePage, piecesRoot };
