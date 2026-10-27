"""Persistent Stockfish process (UCI) with MultiPV analysis."""

from __future__ import annotations

import logging
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.engine

log = logging.getLogger(__name__)

KNOWN_LOCATIONS = ("/opt/homebrew/bin/stockfish", "/usr/local/bin/stockfish", "/usr/games/stockfish")
PV_MOVES = 10  # how many moves of the principal variation to show


def find_stockfish(configured: str = "") -> str | None:
    for candidate in (configured, os.environ.get("STOCKFISH_PATH", "")):
        if candidate and Path(candidate).is_file():
            return candidate
    found = shutil.which("stockfish")
    if found:
        return found
    return next((p for p in KNOWN_LOCATIONS if Path(p).is_file()), None)


@dataclass(frozen=True)
class EngineSettings:
    think_time_s: float = 1.0
    depth: int = 0  # > 0: fixed depth instead of think time
    multipv: int = 3
    threads: int = 0  # 0: all cores but one
    hash_mb: int = 256

    def limit(self) -> chess.engine.Limit:
        return chess.engine.Limit(depth=self.depth) if self.depth > 0 else chess.engine.Limit(time=self.think_time_s)


@dataclass(frozen=True)
class Line:
    move: chess.Move
    san: str
    cp: int | None  # centipawns, White's point of view
    mate: int | None  # moves to mate, White's point of view (+ = White mates)
    depth: int
    pv_san: list[str]

    @property
    def score_text(self) -> str:
        if self.mate is not None:
            return f"#{self.mate}" if self.mate > 0 else f"#-{-self.mate}"
        assert self.cp is not None
        return f"{self.cp / 100:+.2f}"

    @property
    def white_share(self) -> float:
        """0..1 for the evaluation bar (0.5 = equal)."""
        if self.mate is not None:
            return 1.0 if self.mate > 0 else 0.0
        assert self.cp is not None
        return 1 / (1 + 10 ** (-self.cp / 400))


def _san_line(board: chess.Board, moves: list[chess.Move]) -> list[str]:
    b = board.copy(stack=False)
    out = []
    for move in moves[:PV_MOVES]:
        if not b.is_legal(move):
            break
        out.append(b.san(move))
        b.push(move)
    return out


class Engine:
    def __init__(self, path: str, settings: EngineSettings = EngineSettings()) -> None:
        self.path = path
        self.settings = settings
        self._engine: chess.engine.SimpleEngine | None = None
        self._lock = threading.Lock()

    def _start(self) -> chess.engine.SimpleEngine:
        engine = chess.engine.SimpleEngine.popen_uci(self.path)
        threads = self.settings.threads or max(1, (os.cpu_count() or 2) - 1)
        options = {"Threads": threads, "Hash": self.settings.hash_mb}
        engine.configure({k: v for k, v in options.items() if k in engine.options})
        log.info("started %s (%s threads, %d MB hash)", engine.id.get("name", self.path), threads, self.settings.hash_mb)
        return engine

    def start(self) -> None:
        with self._lock:
            if self._engine is None:
                self._engine = self._start()

    def close(self) -> None:
        with self._lock:
            if self._engine is not None:
                try:
                    self._engine.quit()
                except chess.engine.EngineError:
                    pass
                self._engine = None

    def analyse(self, board: chess.Board) -> list[Line]:
        if board.is_game_over():
            return []
        with self._lock:
            for attempt in (1, 2):
                if self._engine is None:
                    self._engine = self._start()
                try:
                    infos = self._engine.analyse(board, self.settings.limit(), multipv=self.settings.multipv)
                    break
                except (chess.engine.EngineTerminatedError, chess.engine.EngineError):
                    log.exception("engine failed (attempt %d), restarting", attempt)
                    try:
                        self._engine.quit()
                    except Exception:  # already dead
                        pass
                    self._engine = None
                    if attempt == 2:
                        raise

        lines = []
        for info in infos:
            pv = info.get("pv")
            score = info.get("score")
            if not pv or score is None:
                continue
            white = score.white()
            lines.append(
                Line(
                    move=pv[0],
                    san=board.san(pv[0]),
                    cp=white.score(),
                    mate=white.mate(),
                    depth=int(info.get("depth", 0)),
                    pv_san=_san_line(board, pv),
                )
            )
        return lines
