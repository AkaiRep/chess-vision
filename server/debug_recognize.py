"""Debug CLI: recognise screenshots and save annotated pictures.

    python -m server.debug_recognize samples/full_screen_start.png [more.png ...] [--out debug_out]

Prints the FEN (plus warnings) for every image and writes:
  <name>_overlay.png  the screenshot with the found board framed
  <name>_board.png    the 800x800 board with each cell's recognised piece and score;
                      uncertain cells are framed red, highlighted squares yellow
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from server.board_locator import CELL, BoardLocator, LocatedBoard, SquareShade
from server.calibration import load_or_calibrate
from server.position import build_position
from server.recognizer import EMPTY, Recognition, Recognizer
from shared.config import PROJECT_ROOT


def draw_overlay(img: np.ndarray, board: LocatedBoard) -> np.ndarray:
    out = img.copy()
    r = board.rect
    cv2.rectangle(out, (r.x, r.y), (r.x + r.w - 1, r.y + r.h - 1), (0, 0, 255), 3)
    return out


def draw_board(board: LocatedBoard, recognition: Recognition) -> np.ndarray:
    out = board.image.copy()
    for i in range(9):
        cv2.line(out, (i * CELL, 0), (i * CELL, 8 * CELL), (255, 0, 255), 1)
        cv2.line(out, (0, i * CELL), (8 * CELL, i * CELL), (255, 0, 255), 1)
    for r, row in enumerate(recognition.cells):
        for c, cell in enumerate(row):
            x, y = c * CELL, r * CELL
            if cell.shade is SquareShade.OTHER:
                cv2.rectangle(out, (x + 2, y + 2), (x + CELL - 3, y + CELL - 3), (0, 220, 255), 2)
            if cell.suspicious:
                cv2.rectangle(out, (x + 4, y + 4), (x + CELL - 5, y + CELL - 5), (0, 0, 255), 3)
            text = cell.label if cell.label == EMPTY else f"{cell.label} {cell.score:.2f}"
            cv2.putText(out, text, (x + 22, y + 96), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(out, text, (x + 22, y + 96), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def process(path: Path, out_dir: Path, locator: BoardLocator, recognizer: Recognizer) -> bool:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        print(f"{path}: cannot read image")
        return False
    t0 = time.perf_counter()
    board = locator.locate(img)
    if board is None:
        print(f"{path.name}: board NOT found")
        return False
    recognition = recognizer.recognize(board)
    position = build_position(recognition, recognizer.flipped_by_labels(board))
    ms = (time.perf_counter() - t0) * 1000
    r = board.rect
    print(f"{path.name}: board x={r.x} y={r.y} {r.w}x{r.h}, {ms:.0f} ms, orientation from {position.orientation_source}")
    print(f"  FEN  {position.fen}")
    for msg in position.errors:
        print(f"  ERROR {msg}")
    for msg in position.warnings:
        print(f"  WARN  {msg}")
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / f"{path.stem}_overlay.png"), draw_overlay(img, board))
    cv2.imwrite(str(out_dir / f"{path.stem}_board.png"), draw_board(board, recognition))
    return position.valid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "debug_out")
    args = parser.parse_args()
    templates = load_or_calibrate()
    locator, recognizer = BoardLocator(templates.theme), Recognizer(templates)
    ok = [process(p, args.out, locator, recognizer) for p in args.images]
    print(f"annotated images in {args.out}")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
