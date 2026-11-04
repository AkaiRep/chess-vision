// node --test extension/tests/board.test.js   (also run from pytest: tests/test_extension.py)
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { findBoard, readBoard } = require("../board.js");

// --- a tiny fake of the bits of DOM that board.js touches -----------------------
function el(cls, color = "", rect = { width: 0, height: 0 }) {
  const tokens = () => cls.split(/\s+/).filter(Boolean);
  return {
    getAttribute: (name) => (name === "class" ? cls : null),
    style: { backgroundColor: color },
    classList: { contains: (c) => tokens().includes(c) },
    getBoundingClientRect: () => rect,
    _tokens: tokens,
  };
}

function boardEl(children, cls = "board", size = 600) {
  const b = el(cls, "", { width: size, height: size });
  const matches = (child, selector) =>
    selector.split(",").some((s) => child._tokens().includes(s.trim().replace(/^\./, "")));
  b.querySelectorAll = (sel) => children.filter((c) => matches(c, sel));
  b.querySelector = (sel) => children.find((c) => matches(c, sel)) || null;
  return b;
}

const sq = (name) => `square-${"abcdefgh".indexOf(name[0]) + 1}${name[1]}`;
const piece = (code, square, extra = "") => el(`piece ${code} ${sq(square)} ${extra}`);
// chess.com also writes the classes in another order sometimes
const pieceAlt = (code, square) => el(`piece ${sq(square)} ${code}`);
const hl = (square, color = "rgb(255, 255, 51)") => el(`highlight ${sq(square)}`, color);

function startPieces() {
  const out = [];
  const back = ["r", "n", "b", "q", "k", "b", "n", "r"];
  "abcdefgh".split("").forEach((f, i) => {
    out.push(piece("w" + back[i], f + "1"), piece("wp", f + "2"), pieceAlt("bp", f + "7"), piece("b" + back[i], f + "8"));
  });
  return out;
}

function afterE4() {
  return startPieces().filter((p) => !p._tokens().includes("square-52")).concat(piece("wp", "e4"));
}

// --- tests --------------------------------------------------------------------------
test("starting position", () => {
  const r = readBoard(boardEl(startPieces()));
  assert.deepEqual(r, {
    ok: true,
    placement: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR",
    flipped: false,
    highlighted: [],
  });
});

test("flipped board and last move", () => {
  const r = readBoard(boardEl([...afterE4(), hl("e2"), hl("e4")], "board flipped"));
  assert.equal(r.placement, "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR");
  assert.equal(r.flipped, true);
  assert.deepEqual(r.highlighted.sort(), ["e2", "e4"]);
});

test("right-click marks in another colour are ignored", () => {
  const marks = [hl("a5", "rgb(235, 97, 80)"), hl("h5", "rgb(235, 97, 80)"), hl("d4", "rgb(235, 97, 80)")];
  const r = readBoard(boardEl([...afterE4(), hl("e2"), hl("e4"), ...marks]));
  assert.deepEqual(r.highlighted.sort(), ["e2", "e4"]);
});

test("ambiguous highlights give no last move", () => {
  const r = readBoard(boardEl([...afterE4(), hl("e2"), hl("e4"), hl("a3")]));
  assert.deepEqual(r.highlighted, []);
});

test("dragging, promotion dialog and two pieces on a square mean busy", () => {
  assert.equal(readBoard(boardEl([...startPieces(), el("piece wp dragging square-52")])).reason, "busy");
  assert.equal(readBoard(boardEl([...startPieces(), el("promotion-window")])).reason, "busy");
  assert.equal(readBoard(boardEl([...startPieces(), piece("wq", "e2")])).reason, "busy");
});

test("ghost pieces and pieces without a square are skipped", () => {
  const extra = [piece("wq", "d5", "ghost"), el("piece wq")];
  assert.equal(readBoard(boardEl([...startPieces(), ...extra])).placement, "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR");
});

test("board without both kings is not sent", () => {
  assert.equal(readBoard(boardEl([piece("wk", "e1")])).ok, false);
  assert.equal(readBoard(boardEl([])).ok, false);
});

test("findBoard picks the largest real board", () => {
  const small = boardEl(startPieces(), "board", 80);
  const mid = boardEl(startPieces(), "board", 300);
  const big = boardEl(startPieces(), "board", 640);
  const doc = { querySelectorAll: () => [small, big, mid] };
  assert.equal(findBoard(doc), big);
  assert.equal(findBoard({ querySelectorAll: () => [small] }), null);
});
