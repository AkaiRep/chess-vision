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

// -> {ok: true, placement, flipped, highlighted} or {ok: false, reason}.
// reason "busy" means "read again a bit later" (piece being dragged, promotion dialog).
function readBoard(boardEl) {
  if (boardEl.querySelector(".dragging, .promotion-window")) return { ok: false, reason: "busy" };

  const grid = Array.from({ length: 8 }, () => Array(8).fill(null)); // grid[rank-1][file-1]
  let whiteKings = 0;
  let blackKings = 0;
  let count = 0;
  for (const el of boardEl.querySelectorAll(".piece")) {
    const cls = classOf(el);
    if (/(?:^|\s)ghost(?=\s|$)/.test(cls)) continue;
    const p = PIECE_RE.exec(cls);
    const s = SQUARE_RE.exec(cls);
    if (!p || !s) continue; // pieces outside the board (promotion choices etc.)
    const file = +s[1];
    const rank = +s[2];
    if (grid[rank - 1][file - 1] !== null) return { ok: false, reason: "busy" }; // mid-animation
    grid[rank - 1][file - 1] = p[1] === "w" ? p[2].toUpperCase() : p[2];
    if (p[2] === "k") p[1] === "w" ? whiteKings++ : blackKings++;
    count++;
  }
  if (count === 0) return { ok: false, reason: "empty board" };
  if (whiteKings !== 1 || blackKings !== 1 || count > 32) return { ok: false, reason: "incomplete board" };

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
    highlighted: lastMoveSquares(boardEl, grid),
  };
}

if (typeof module !== "undefined") module.exports = { findBoard, readBoard };
