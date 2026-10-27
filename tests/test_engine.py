"""Stage 4: Stockfish integration (skipped when Stockfish is not installed)."""

from __future__ import annotations

from collections.abc import Iterator

import chess
import pytest

from server.engine import Engine, EngineSettings, Line, find_stockfish

STOCKFISH = find_stockfish()
pytestmark = pytest.mark.skipif(STOCKFISH is None, reason="stockfish not installed (set STOCKFISH_PATH)")


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    assert STOCKFISH is not None
    eng = Engine(STOCKFISH, EngineSettings(think_time_s=0.3, threads=2, hash_mb=32))
    eng.start()
    yield eng
    eng.close()


def test_multipv_lines(engine: Engine) -> None:
    lines = engine.analyse(chess.Board())
    assert len(lines) == 3
    assert len({line.move for line in lines}) == 3
    assert all(line.cp is not None and abs(line.cp) < 150 for line in lines)
    assert all(line.pv_san and line.pv_san[0] == line.san for line in lines)


def test_finds_mate_for_black(engine: Engine) -> None:
    board = chess.Board("6k1/5ppp/8/8/3r4/8/5PPP/6K1 b - - 0 1")  # back-rank mate: Rd1#
    lines = engine.analyse(board)
    assert lines[0].san == "Rd1#"
    assert lines[0].mate is not None and lines[0].mate < 0  # White's point of view: Black mates
    assert lines[0].score_text == "#-1" and lines[0].white_share == 0.0


def test_game_over_returns_nothing(engine: Engine) -> None:
    assert engine.analyse(chess.Board("7k/5QQ1/8/8/8/8/8/K7 b - - 0 1")) == []


def test_restarts_after_crash(engine: Engine) -> None:
    assert engine._engine is not None
    engine._engine.quit()  # simulate the process dying
    assert len(engine.analyse(chess.Board())) == 3


def test_score_text() -> None:
    line = Line(chess.Move.from_uci("e2e4"), "e4", 35, None, 20, ["e4"])
    assert line.score_text == "+0.35" and 0.5 < line.white_share < 0.6
