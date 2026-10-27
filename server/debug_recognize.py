"""Debug CLI: find the board on an image and save annotated pictures.

    python -m server.debug_recognize samples/full_screen_start.png [more.png ...] [--out debug_out]

Writes <name>_overlay.png (screenshot with the found rectangle) and <name>_board.png
(800x800 crop with the 8x8 grid and each cell's detected background shade).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from server.board_locator import CELL, BoardLocator, LocatedBoard, SquareShade, grid_shades
from shared.config import PROJECT_ROOT

SHADE_COLORS = {
    SquareShade.LIGHT: (255, 255, 255),
    SquareShade.DARK: (0, 90, 0),
    SquareShade.OTHER: (0, 0, 255),
}


def draw_overlay(img: np.ndarray, board: LocatedBoard) -> np.ndarray:
    out = img.copy()
    r = board.rect
    cv2.rectangle(out, (r.x, r.y), (r.x + r.w - 1, r.y + r.h - 1), (0, 0, 255), 3)
    return out


def draw_board(img: np.ndarray, board: LocatedBoard) -> np.ndarray:
    out = board.image.copy()
    shades = grid_shades(img, board.rect, BoardLocator().theme)
    for i in range(9):
        cv2.line(out, (i * CELL, 0), (i * CELL, 8 * CELL), (255, 0, 255), 1)
        cv2.line(out, (0, i * CELL), (8 * CELL, i * CELL), (255, 0, 255), 1)
    for r in range(8):
        for c in range(8):
            cv2.rectangle(
                out, (c * CELL + 3, r * CELL + 3), (c * CELL + 14, r * CELL + 14), SHADE_COLORS[shades[r][c]], -1
            )
    return out


def process(path: Path, out_dir: Path, locator: BoardLocator) -> bool:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        print(f"{path}: cannot read image")
        return False
    t0 = time.perf_counter()
    board = locator.locate(img)
    ms = (time.perf_counter() - t0) * 1000
    if board is None:
        print(f"{path.name}: board NOT found ({ms:.0f} ms)")
        return False
    r = board.rect
    print(f"{path.name}: board at x={r.x} y={r.y} {r.w}x{r.h} ({ms:.0f} ms{', cached' if board.from_cache else ''})")
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / f"{path.stem}_overlay.png"), draw_overlay(img, board))
    cv2.imwrite(str(out_dir / f"{path.stem}_board.png"), draw_board(img, board))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "debug_out")
    args = parser.parse_args()
    locator = BoardLocator()
    ok = [process(p, args.out, locator) for p in args.images]
    print(f"annotated images in {args.out}")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
