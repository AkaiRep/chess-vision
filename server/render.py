"""Pictures for the UI: the board as SVG and a small preview of the screenshot."""

from __future__ import annotations

import base64

import chess
import chess.svg
import cv2
import numpy as np

from server.board_locator import BoardRect
from server.engine import Line
from server.position import Position

ARROW_COLORS = ("#1b8a3acc", "#2f6fd680", "#2f6fd64d")  # best line, then paler 2nd and 3rd
SUSPICIOUS_FILL = "#ff3b3088"
BOARD_COLORS = {  # chess.com-like green theme on the dark page
    "square light": "#ebecd0",
    "square dark": "#739552",
    "square light lastmove": "#f5f682",
    "square dark lastmove": "#b9ca43",
    "margin": "#312e2b",
    "coord": "#a8a49c",
}
PREVIEW_WIDTH = 480


def board_svg(position: Position, lines: list[Line], size: int = 640) -> str:
    board = position.board
    arrows = [
        chess.svg.Arrow(line.move.from_square, line.move.to_square, color=color)
        for line, color in zip(lines, ARROW_COLORS)
    ]
    arrows.reverse()  # draw the best arrow last, on top
    king = board.king(board.turn)
    lastmove = chess.Move(*position.last_move) if position.last_move else None
    return chess.svg.board(
        board,
        orientation=position.my_color,
        arrows=arrows,
        fill={sq: SUSPICIOUS_FILL for sq in position.suspicious},
        lastmove=lastmove,
        check=king if king is not None and board.is_check() else None,
        size=size,
        colors=BOARD_COLORS,
    )


def preview_data_url(img: np.ndarray, rect: BoardRect | None) -> str:
    """Downscaled screenshot with the found board framed, as a JPEG data URL."""
    scale = PREVIEW_WIDTH / img.shape[1]
    small = cv2.resize(img, (PREVIEW_WIDTH, max(1, round(img.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    if rect is not None:
        p0 = (round(rect.x * scale), round(rect.y * scale))
        p1 = (round((rect.x + rect.w) * scale), round((rect.y + rect.h) * scale))
        cv2.rectangle(small, p0, p1, (48, 59, 255), 2)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 75])
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
