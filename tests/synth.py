"""Synthetic chess.com-style screenshots for tests, with a known FEN.

Pieces are real sprites cut from samples/start_position.jpg (the recogniser is calibrated on
the *other* sample, full_screen_start.png) and re-composited onto squares of any colour,
including the yellow last-move highlight. Coordinate labels are copied the same way.
"""

from __future__ import annotations

import functools
from pathlib import Path

import chess
import cv2
import numpy as np

from server.board_locator import BOARD_SIZE, CELL, crop_board, find_board
from server.calibration import START_WHITE_BOTTOM
from server.position import screen_to_square

SAMPLES = Path(__file__).parent.parent / "samples"
LIGHT = np.array((208, 236, 235), np.float32)  # BGR
DARK = np.array((82, 149, 115), np.float32)
HIGHLIGHT_LIGHT = np.array((130, 246, 245), np.float32)
HIGHLIGHT_DARK = np.array((67, 202, 185), np.float32)
SCREEN_BOARD = (396, 153, 808)  # where the board sits on full_screen_start.png


@functools.cache
def _source_board() -> np.ndarray:
    img = cv2.imread(str(SAMPLES / "start_position.jpg"), cv2.IMREAD_COLOR)
    rect = find_board(img)
    assert rect is not None
    return crop_board(img, rect).astype(np.float32)


def _source_cell(row: int, col: int) -> tuple[np.ndarray, np.ndarray]:
    board = _source_board()
    cell = board[row * CELL : (row + 1) * CELL, col * CELL : (col + 1) * CELL]
    bg = LIGHT if (row + col) % 2 == 0 else DARK
    return cell, bg


LABEL_REGIONS = ((slice(0, 34), slice(0, 22)), (slice(66, 100), slice(76, 100)))


def _sprite_alpha(cell: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """Opacity of the piece: solid inside its outline, soft at the anti-aliased edge."""
    dist = np.linalg.norm(cell - bg, axis=2)
    soft = np.clip((dist - 8) / 40, 0, 1)
    chroma = cell.max(axis=2) - cell.min(axis=2)
    for region in LABEL_REGIONS:  # drop the coloured coordinate labels; pieces are grey
        soft[region][chroma[region] > 25] = 0
    outline = (dist > 30).astype(np.uint8)
    flood = outline.copy()
    mask = np.zeros((CELL + 2, CELL + 2), np.uint8)
    cv2.floodFill(flood, mask, (CELL // 2, 2), 2)  # paint the outside of the piece
    inside = flood != 2
    return np.where(inside & (soft > 0), 1.0, soft).astype(np.float32)


def _sprite(symbol: str, want_light: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    spots = [(r, c) for r in range(8) for c in range(8) if START_WHITE_BOTTOM[r][c] == symbol]
    spots.sort(key=lambda rc: ((rc[0] + rc[1]) % 2 == 0) != want_light)  # preferred shade first
    cell, bg = _source_cell(*spots[0])
    return cell, bg, _sprite_alpha(cell, bg)


def _paint_label(target: np.ndarray, target_bg: np.ndarray, src_row: int, src_col: int, region: tuple[slice, slice]) -> None:
    cell, bg = _source_cell(src_row, src_col)
    label_color = DARK if bg is LIGHT else LIGHT
    patch = cell[region]
    is_label = np.linalg.norm(patch - label_color, axis=2) < 60
    new_color = DARK if target_bg is LIGHT else LIGHT
    target[region][is_label] = new_color


def render_board(
    fen: str,
    flipped: bool = False,
    highlight: tuple[str, str] | None = None,
    size: int = SCREEN_BOARD[2],
    labels: bool = True,
    swap_shades: bool = True,
) -> np.ndarray:
    """Board image for the placement part of `fen`. flipped = black at the bottom.

    swap_shades: take each piece's sprite from the opposite square colour when possible,
    so recognition must not depend on the colour the template was cut from.
    """
    board = chess.BaseBoard(fen.split()[0])
    marked = {chess.parse_square(s) for s in highlight} if highlight else set()
    out = np.zeros((BOARD_SIZE, BOARD_SIZE, 3), np.float32)
    rng = np.random.default_rng(0)
    for r in range(8):
        for c in range(8):
            sq = screen_to_square(r, c, flipped)
            light = (r + c) % 2 == 0
            shade_bg = LIGHT if light else DARK
            bg = (HIGHLIGHT_LIGHT if light else HIGHLIGHT_DARK) if sq in marked else shade_bg
            cell = np.empty((CELL, CELL, 3), np.float32)
            cell[:] = bg
            cell += rng.normal(0, 1.0, cell.shape)
            if labels and c == 0:
                rank = chess.square_rank(sq) + 1
                _paint_label(cell, shade_bg, 8 - rank, 0, (slice(0, 34), slice(0, 22)))
            if labels and r == 7:
                file = chess.square_file(sq)
                _paint_label(cell, shade_bg, 7, file, (slice(66, 100), slice(76, 100)))
            piece = board.piece_at(sq)
            if piece:
                sprite, src_bg, alpha = _sprite(piece.symbol(), want_light=(not light) if swap_shades else light)
                a = alpha[..., None]
                cell = np.where(a > 0, sprite + (1 - a) * (bg - src_bg), cell)  # re-composite onto bg
            out[r * CELL : (r + 1) * CELL, c * CELL : (c + 1) * CELL] = cell
    img = np.clip(out, 0, 255).astype(np.uint8)
    if size != BOARD_SIZE:
        img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA if size < BOARD_SIZE else cv2.INTER_CUBIC)
    return img


def screenshot(board_img: np.ndarray) -> np.ndarray:
    """Put the board on the chess.com page from full_screen_start.png (or a plain page if resized)."""
    size = board_img.shape[0]
    if size == SCREEN_BOARD[2]:
        screen = cv2.imread(str(SAMPLES / "full_screen_start.png"), cv2.IMREAD_COLOR)
        x, y = SCREEN_BOARD[:2]
    else:
        screen = np.full((1080, 1920, 3), (48, 46, 43), np.uint8)
        x, y = 300, 120
    screen[y : y + size, x : x + size] = board_img
    return screen


def jpeg(img: np.ndarray, quality: int = 80) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)
