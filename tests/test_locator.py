"""Stage 2: finding the board on screenshots."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from server.board_locator import (
    BOARD_SIZE,
    BoardLocator,
    BoardRect,
    SquareShade,
    find_board,
    grid_shades,
)

SAMPLES = Path(__file__).parent.parent / "samples"
HIGHLIGHT_LIGHT = (130, 246, 245)  # BGR, yellowish last-move highlight
HIGHLIGHT_DARK = (67, 202, 185)


def load(name: str) -> np.ndarray:
    img = cv2.imread(str(SAMPLES / name), cv2.IMREAD_COLOR)
    assert img is not None, f"missing sample {name}"
    return img


def assert_rect_close(rect: BoardRect | None, expected: tuple[int, int, int, int], tol: int) -> None:
    assert rect is not None, "board not found"
    for got, exp in zip(rect.as_tuple(), expected):
        assert abs(got - exp) <= tol, f"{rect} vs {expected}"


def test_full_screenshot() -> None:
    assert_rect_close(find_board(load("full_screen_start.png")), (396, 153, 808, 808), tol=1)


def test_cropped_jpeg_sample() -> None:
    img = load("start_position.jpg")
    h, w = img.shape[:2]
    assert_rect_close(find_board(img), (0, 0, w, h), tol=3)


def test_small_board_on_foreign_background() -> None:
    board = cv2.resize(load("start_position.jpg"), (300, 300), interpolation=cv2.INTER_AREA)
    canvas = np.full((700, 1000, 3), (48, 46, 43), np.uint8)
    canvas[61:361, 137:437] = board
    assert_rect_close(find_board(canvas), (137, 61, 300, 300), tol=3)


def test_all_cells_alternate() -> None:
    img = load("full_screen_start.png")
    rect = find_board(img)
    assert rect is not None
    for r, row in enumerate(grid_shades(img, rect, BoardLocator().theme)):
        for c, shade in enumerate(row):
            assert shade is (SquareShade.LIGHT if (r + c) % 2 == 0 else SquareShade.DARK), (r, c)


def test_highlighted_squares() -> None:
    img = load("full_screen_start.png").copy()
    x0, y0, cell = 396, 153, 101

    def paint(row: int, col: int, color: tuple[int, int, int]) -> None:
        sub = img[y0 + row * cell : y0 + (row + 1) * cell, x0 + col * cell : x0 + (col + 1) * cell]
        background = (np.abs(sub.astype(int) - sub[50, 3].astype(int)).max(axis=2) < 20)
        sub[background] = color  # recolour only the square, not the piece

    paint(6, 4, HIGHLIGHT_LIGHT)  # e2 (light)
    paint(4, 4, HIGHLIGHT_DARK)  # e4 (dark)
    rect = find_board(img)
    assert_rect_close(rect, (396, 153, 808, 808), tol=1)
    shades = grid_shades(img, rect, BoardLocator().theme)  # type: ignore[arg-type]
    assert shades[6][4] is SquareShade.OTHER and shades[4][4] is SquareShade.OTHER


def test_cache_and_invalidation() -> None:
    locator = BoardLocator()
    img = load("full_screen_start.png")
    first = locator.locate(img)
    second = locator.locate(img)
    assert first is not None and not first.from_cache
    assert second is not None and second.from_cache and second.rect == first.rect
    assert second.image.shape == (BOARD_SIZE, BOARD_SIZE, 3)
    assert locator.locate(np.zeros_like(img)) is None
    third = locator.locate(img)
    assert third is not None and not third.from_cache


@pytest.mark.parametrize("seed", [0, 1])
def test_no_board(seed: int) -> None:
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 256, (600, 800, 3), dtype=np.uint8)
    assert find_board(noise) is None
    assert find_board(np.full((600, 800, 3), (115, 149, 82), np.uint8)) is None  # one flat green area
