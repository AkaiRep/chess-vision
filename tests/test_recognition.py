"""Stage 3: calibration, recognition, orientation, side to move and FEN."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import chess
import cv2
import numpy as np
import pytest

from server.board_locator import BoardLocator
from server.calibration import CalibrationError, calibrate
from server.position import Position, build_position
from server.recognizer import Recognizer, Templates
from tests.synth import jpeg, render_board, screenshot

SAMPLES = Path(__file__).parent.parent / "samples"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


@pytest.fixture(scope="module")
def templates() -> Templates:
    return calibrate(cv2.imread(str(SAMPLES / "full_screen_start.png"), cv2.IMREAD_COLOR))


@pytest.fixture(scope="module")
def analyse(templates: Templates) -> Callable[..., Position]:
    recognizer = Recognizer(templates)

    def run(img: np.ndarray, **overrides: bool) -> Position:
        board = BoardLocator(templates.theme).locate(img)
        assert board is not None, "board not found"
        recognition = recognizer.recognize(board)
        return build_position(recognition, recognizer.flipped_by_labels(board), **overrides)

    return run


def played(moves: str) -> chess.Board:
    board = chess.Board()
    for san in moves.split():
        board.push_san(san)
    return board


# --- real screenshots ---------------------------------------------------------------


@pytest.mark.parametrize("name", ["start_position.jpg", "full_screen_start.png"])
def test_start_position(analyse: Callable[..., Position], name: str) -> None:
    pos = analyse(cv2.imread(str(SAMPLES / name), cv2.IMREAD_COLOR))
    assert pos.fen == START_FEN
    assert pos.valid and not pos.warnings
    assert pos.orientation_source == "labels"


def test_templates_roundtrip(templates: Templates, tmp_path: Path) -> None:
    path = tmp_path / "t.npz"
    templates.save(path)
    loaded = Templates.load(path)
    assert loaded.labels == templates.labels and loaded.theme == templates.theme
    assert loaded.rank8 is not None and np.array_equal(loaded.rank8, templates.rank8)


def test_calibration_rejects_middlegame() -> None:
    img = screenshot(render_board(played("e4 e5 Nf3 Nc6").fen()))
    with pytest.raises(CalibrationError):
        calibrate(img)


def test_calibration_from_black_side(analyse: Callable[..., Position]) -> None:
    flipped_start = screenshot(render_board(chess.STARTING_FEN, flipped=True))
    templates = calibrate(flipped_start)
    assert sorted(templates.labels) == sorted("RNBQKBNRPPPPPPPPrnbqkbnrpppppppp")
    pos = analyse(flipped_start)
    assert pos.flipped and pos.my_color == chess.BLACK
    assert pos.fen == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"


# --- synthetic positions -------------------------------------------------------------


def test_middlegame_white(analyse: Callable[..., Position]) -> None:
    board = played("e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O")
    pos = analyse(screenshot(render_board(board.fen(), highlight=("e8", "g8"))))
    assert pos.fen == f"{board.board_fen()} w - - 0 1"
    assert not pos.flipped and pos.valid
    assert pos.last_move == (chess.E8, chess.G8)
    assert not pos.warnings  # black moved last, so it is my (white) move: confirmed


def test_playing_black(analyse: Callable[..., Position]) -> None:
    board = played("d4 Nf6 c4 e6 Nc3 Bb4 Qc2")
    pos = analyse(screenshot(render_board(board.fen(), flipped=True, highlight=("d1", "c2"))))
    assert pos.flipped and pos.my_color == chess.BLACK and pos.orientation_source == "labels"
    assert pos.fen == f"{board.board_fen()} b KQkq - 0 1"
    assert pos.valid and not pos.warnings


def test_en_passant_from_highlight(analyse: Callable[..., Position]) -> None:
    board = played("e4 Nf6 e5 d5")
    pos = analyse(screenshot(render_board(board.fen(), highlight=("d7", "d5"))))
    assert pos.fen == f"{board.board_fen()} w KQkq d6 0 1"


def test_warns_when_my_piece_moved_last(analyse: Callable[..., Position]) -> None:
    board = played("e4 e5 Nf3")
    pos = analyse(screenshot(render_board(board.fen(), highlight=("g1", "f3"))))
    assert pos.board.turn == chess.WHITE
    assert any("сторону хода" in w for w in pos.warnings)
    switched = analyse(screenshot(render_board(board.fen(), highlight=("g1", "f3"))), switch_turn=True)
    assert switched.board.turn == chess.BLACK and not switched.warnings


def test_endgame_king_in_top_half(analyse: Callable[..., Position]) -> None:
    fen = "8/5k2/3K4/8/8/8/4P3/8 w - - 0 1"  # my white king walked up: labels still say "white"
    pos = analyse(screenshot(render_board(fen)))
    assert pos.fen == fen and not pos.flipped


def test_promoted_pieces_and_cross_shade(analyse: Callable[..., Position]) -> None:
    fen = "4k3/8/8/8/8/8/QQ6/QQ2K3 w - - 0 1"  # four queens on both square colours
    for swap in (True, False):
        assert analyse(screenshot(render_board(fen, swap_shades=swap))).fen == fen


def test_small_board_and_jpeg(analyse: Callable[..., Position]) -> None:
    board = played("d4 Nf6 c4 e6 Nc3 Bb4 Qc2 O-O a3 Bxc3+ Qxc3")
    img = jpeg(screenshot(render_board(board.fen(), flipped=True, size=420)), quality=75)
    pos = analyse(img)
    assert pos.fen == f"{board.board_fen()} b KQ - 0 1"  # white has not castled yet


def test_orientation_without_labels(analyse: Callable[..., Position]) -> None:
    board = played("d4 Nf6 c4 e6")
    pos = analyse(screenshot(render_board(board.fen(), flipped=True, labels=False)))
    assert pos.orientation_source == "pieces" and pos.flipped
    assert pos.fen == f"{board.board_fen()} b KQkq - 0 1"


def test_manual_flip(analyse: Callable[..., Position]) -> None:
    img = screenshot(render_board(chess.STARTING_FEN))
    pos = analyse(img, flip=True)
    assert pos.flipped and pos.orientation_source == "manual" and pos.my_color == chess.BLACK
    assert pos.board.board_fen() == "RNBKQBNR/PPPPPPPP/8/8/8/8/pppppppp/rnbkqbnr"


def test_invalid_position_is_reported(analyse: Callable[..., Position]) -> None:
    pos = analyse(screenshot(render_board("4k3/8/8/8/8/8/8/K3K3 w - - 0 1")))
    assert not pos.valid
    assert any("короля" in e for e in pos.errors)
