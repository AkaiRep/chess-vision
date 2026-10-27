"""Find a flat 2D chess board on a screenshot by the colours of its squares.

The board is the largest roughly square blob of "light square" / "dark square" colours
whose 8x8 grid alternates correctly. No perspective: crop + resize to BOARD_SIZE.
The last found rectangle is cached and reused while it still verifies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np

log = logging.getLogger(__name__)

BOARD_SIZE = 800
CELL = BOARD_SIZE // 8
MIN_BOARD_PX = 120  # smaller boards are not worth recognising
MAX_WRONG_CELLS = 2  # cells whose colour is the opposite of what the checker pattern expects
MIN_MATCHING_CELLS = 50  # the rest may be "other" (highlighted squares, pieces covering the edge)


@dataclass(frozen=True)
class BoardTheme:
    """Square colours in BGR. Defaults measured on samples/ (chess.com green)."""

    light: tuple[int, int, int] = (208, 236, 236)
    dark: tuple[int, int, int] = (82, 149, 115)
    tolerance: int = 24  # max per-channel deviation; leaves room for JPEG artefacts


DEFAULT_THEME = BoardTheme()


class SquareShade(Enum):
    LIGHT = "light"
    DARK = "dark"
    OTHER = "other"  # e.g. last-move highlight


@dataclass(frozen=True)
class BoardRect:
    x: int
    y: int
    w: int
    h: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h


@dataclass(frozen=True)
class LocatedBoard:
    rect: BoardRect
    image: np.ndarray  # BOARD_SIZE x BOARD_SIZE BGR, row 0 = top of the screen
    from_cache: bool = False

    def cell(self, row: int, col: int) -> np.ndarray:
        """Cell in screen coordinates: row 0 is the top row, col 0 the left column."""
        return self.image[row * CELL : (row + 1) * CELL, col * CELL : (col + 1) * CELL]


def color_mask(img: np.ndarray, color: tuple[int, int, int], tolerance: int) -> np.ndarray:
    diff = np.abs(img.astype(np.int16) - np.array(color, dtype=np.int16)).max(axis=2)
    return diff <= tolerance


def cell_background(cell: np.ndarray) -> np.ndarray:
    """Median BGR of a thin ring just inside the cell border.

    The ring avoids the centre (where the piece is) and is wide enough that the
    coordinate labels in the corners do not dominate the median.
    """
    h, w = cell.shape[:2]
    a, b = max(1, h // 25), max(2, h // 9)
    ring = np.concatenate(
        [
            cell[a:b, a : w - a].reshape(-1, 3),
            cell[h - b : h - a, a : w - a].reshape(-1, 3),
            cell[b : h - b, a:b].reshape(-1, 3),
            cell[b : h - b, w - b : w - a].reshape(-1, 3),
        ]
    )
    return np.median(ring, axis=0)


def classify_shade(bgr: np.ndarray, theme: BoardTheme) -> SquareShade:
    for shade, color in ((SquareShade.LIGHT, theme.light), (SquareShade.DARK, theme.dark)):
        if np.abs(bgr - np.array(color)).max() <= theme.tolerance:
            return shade
    return SquareShade.OTHER


def grid_shades(img: np.ndarray, rect: BoardRect, theme: BoardTheme) -> list[list[SquareShade]]:
    """Background shade of every cell of `rect` in screen order (row 0 = top)."""
    shades = []
    for r in range(8):
        row = []
        for c in range(8):
            y0, y1 = rect.y + r * rect.h // 8, rect.y + (r + 1) * rect.h // 8
            x0, x1 = rect.x + c * rect.w // 8, rect.x + (c + 1) * rect.w // 8
            row.append(classify_shade(cell_background(img[y0:y1, x0:x1]), theme))
        shades.append(row)
    return shades


def verify_grid(img: np.ndarray, rect: BoardRect, theme: BoardTheme) -> bool:
    """True if the cells alternate like a chess board (top-left square is light)."""
    if rect.w < MIN_BOARD_PX or rect.h < MIN_BOARD_PX:
        return False
    if rect.x < 0 or rect.y < 0 or rect.x + rect.w > img.shape[1] or rect.y + rect.h > img.shape[0]:
        return False
    matching = wrong = 0
    for r, row in enumerate(grid_shades(img, rect, theme)):
        for c, shade in enumerate(row):
            expected = SquareShade.LIGHT if (r + c) % 2 == 0 else SquareShade.DARK
            if shade is expected:
                matching += 1
            elif shade is not SquareShade.OTHER:
                wrong += 1
    return matching >= MIN_MATCHING_CELLS and wrong <= MAX_WRONG_CELLS


def _trim(mask: np.ndarray, rect: BoardRect, min_density: float = 0.25) -> BoardRect:
    """Shave off rows/columns at the edges that are barely covered by square colours."""
    sub = mask[rect.y : rect.y + rect.h, rect.x : rect.x + rect.w]
    cols = np.flatnonzero(sub.mean(axis=0) >= min_density)
    rows = np.flatnonzero(sub.mean(axis=1) >= min_density)
    if cols.size == 0 or rows.size == 0:
        return rect
    return BoardRect(
        rect.x + int(cols[0]),
        rect.y + int(rows[0]),
        int(cols[-1] - cols[0] + 1),
        int(rows[-1] - rows[0] + 1),
    )


def find_board(img: np.ndarray, theme: BoardTheme = DEFAULT_THEME) -> BoardRect | None:
    mask = color_mask(img, theme.light, theme.tolerance) | color_mask(img, theme.dark, theme.tolerance)
    k = max(3, min(img.shape[:2]) // 200)
    closed = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    n, _labels, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)

    order = np.argsort(-stats[1:, cv2.CC_STAT_AREA]) + 1  # skip background label 0
    for label in order:
        x, y, w, h, area = (int(v) for v in stats[label])
        if w < MIN_BOARD_PX or h < MIN_BOARD_PX:
            break  # sorted by area, the rest are smaller still
        if not 0.85 <= w / h <= 1.18:
            continue
        rect = _trim(mask, BoardRect(x, y, w, h))
        if verify_grid(img, rect, theme):
            return rect
        log.debug("component %s rejected by grid check", rect)
    return None


def crop_board(img: np.ndarray, rect: BoardRect) -> np.ndarray:
    crop = img[rect.y : rect.y + rect.h, rect.x : rect.x + rect.w]
    interp = cv2.INTER_AREA if rect.w >= BOARD_SIZE else cv2.INTER_CUBIC
    return cv2.resize(crop, (BOARD_SIZE, BOARD_SIZE), interpolation=interp)


class BoardLocator:
    """Finds the board and remembers where it was for the next screenshot."""

    def __init__(self, theme: BoardTheme = DEFAULT_THEME) -> None:
        self.theme = theme
        self._cached: BoardRect | None = None
        self._cached_shape: tuple[int, ...] | None = None

    def reset(self) -> None:
        self._cached = None
        self._cached_shape = None

    def locate(self, img: np.ndarray) -> LocatedBoard | None:
        if self._cached and self._cached_shape == img.shape and verify_grid(img, self._cached, self.theme):
            return LocatedBoard(self._cached, crop_board(img, self._cached), from_cache=True)

        rect = find_board(img, self.theme)
        if rect is None:
            self.reset()
            return None
        self._cached, self._cached_shape = rect, img.shape
        log.info("board found at x=%d y=%d %dx%d", *rect.as_tuple())
        return LocatedBoard(rect, crop_board(img, rect))
