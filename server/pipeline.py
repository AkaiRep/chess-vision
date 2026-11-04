"""Screenshot -> board -> pieces -> position -> Stockfish, plus the UI overrides.

Two sources: a screenshot from the Windows client, or the board read straight out of the
chess.com page by the browser extension (no recognition needed). The Analyzer keeps the last
input, so the UI buttons (flip, switch side to move, recalibrate) re-evaluate without a new one.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from server.board_locator import BoardLocator, LocatedBoard
from server.calibration import TEMPLATES_PATH, CalibrationError, calibrate, load_or_calibrate
from server.engine import Engine, Line
from server.position import Position, build_position, color_name, position_from_page
from server.recognizer import Recognition, Recognizer
from server.render import board_svg, preview_data_url

log = logging.getLogger(__name__)


@dataclass
class Analysis:
    status: str  # "waiting", "no_board", "invalid", "ok", "game_over", "no_engine", "error"
    message: str = ""
    position: Position | None = None
    lines: list[Line] = field(default_factory=list)
    preview: str = ""
    seq: int = 0
    created: float = field(default_factory=time.time)
    source: str = "screenshot"  # or "page" (browser extension)
    site: str = ""

    def summary(self) -> dict[str, Any]:
        """Short answer for the Windows client."""
        out: dict[str, Any] = {"status": self.status, "message": self.message}
        if self.position:
            out["fen"] = self.position.fen
        if self.lines:
            out["best"] = self.lines[0].san
            out["score"] = self.lines[0].score_text
        return out

    def to_json(self) -> dict[str, Any]:
        """Full state for the web page."""
        pos = self.position
        data: dict[str, Any] = {
            "seq": self.seq,
            "status": self.status,
            "message": self.message,
            "preview": self.preview,
            "source": self.source,
            "site": self.site,
            "time": time.strftime("%H:%M:%S", time.localtime(self.created)),
        }
        if pos is None:
            return data
        best = self.lines[0] if self.lines else None
        data.update(
            fen=pos.fen,
            svg=board_svg(pos, self.lines),
            my_color=color_name(pos.my_color),
            turn=color_name(pos.board.turn),
            my_turn=pos.board.turn == pos.my_color,
            orientation=pos.orientation_source,
            warnings=pos.warnings,
            errors=pos.errors,
            lines=[
                {"san": ln.san, "uci": ln.move.uci(), "score": ln.score_text, "depth": ln.depth, "pv": " ".join(ln.pv_san)}
                for ln in self.lines
            ],
            eval={"text": best.score_text, "white_share": best.white_share} if best else None,
        )
        return data


@dataclass(frozen=True)
class PageBoard:
    """Board as the browser extension read it from the page."""

    placement: str  # FEN piece placement
    flipped: bool  # black at the bottom
    highlighted: list[int]  # last-move squares (python-chess square numbers)
    site: str = "chess.com"


class Analyzer:
    def __init__(self, engine: Engine | None, templates_path: Path = TEMPLATES_PATH) -> None:
        self.engine = engine
        self.templates_path = templates_path
        templates = load_or_calibrate(templates_path)
        self.recognizer = Recognizer(templates)
        self.locator = BoardLocator(templates.theme)
        self._lock = threading.Lock()
        self._img: np.ndarray | None = None
        self._board: LocatedBoard | None = None
        self._recognition: Recognition | None = None
        self._flipped_by_labels: bool | None = None
        self._page: PageBoard | None = None
        self._page_requests = 0
        self._page_requests_lock = threading.Lock()
        self.flip = False
        self.switch_turn = False
        self._seq = 0
        self.latest = Analysis("waiting", "Откройте доску на chess.com или нажмите F8 на Windows")

    # --- entry points (thread-safe) --------------------------------------
    def analyze_image(self, img: np.ndarray) -> Analysis:
        with self._lock:
            self._img = img
            self._page = None
            self.flip = self.switch_turn = False  # overrides apply to one screenshot only
            self._board = self.locator.locate(img)
            if self._board is None:
                self._recognition = None
                return self._publish(
                    Analysis("no_board", "Доска не найдена на скриншоте", preview=preview_data_url(img, None))
                )
            self._recognition = self.recognizer.recognize(self._board)
            self._flipped_by_labels = self.recognizer.flipped_by_labels(self._board)
            return self._evaluate()

    def analyze_page(self, page: PageBoard) -> Analysis | None:
        """Position from the browser extension. None = a newer position arrived meanwhile (skip it)."""
        with self._page_requests_lock:
            self._page_requests += 1
            ticket = self._page_requests
        with self._lock:
            if ticket != self._page_requests:
                return None
            self._page = page
            self.flip = self.switch_turn = False
            return self._evaluate()

    def toggle_flip(self) -> Analysis:
        with self._lock:
            self.flip = not self.flip
            return self._evaluate()

    def toggle_turn(self) -> Analysis:
        with self._lock:
            self.switch_turn = not self.switch_turn
            return self._evaluate()

    def recalibrate(self) -> Analysis:
        """Use the last screenshot (must show the starting position) as the new reference."""
        with self._lock:
            if self._img is None or self._page is not None:
                raise CalibrationError("сначала отправьте скриншот начальной позиции (F8)")
            templates = calibrate(self._img)
            templates.save(self.templates_path)
            self.recognizer = Recognizer(templates)
            self.locator = BoardLocator(templates.theme)
            log.info("recalibrated from the last screenshot")
        return self.analyze_image(self._img)

    # --- internals ---------------------------------------------------------
    def _publish(self, analysis: Analysis) -> Analysis:
        self._seq += 1
        analysis.seq = self._seq
        self.latest = analysis
        return analysis

    def _evaluate(self) -> Analysis:
        result = self._evaluate_position()
        if self._page is not None:
            result.source, result.site = "page", self._page.site
        return result

    def _evaluate_position(self) -> Analysis:
        if self._page is not None:
            page = self._page
            pos = position_from_page(page.placement, page.flipped, page.highlighted, self.flip, self.switch_turn)
            preview = ""
        elif self._img is not None and self._board is not None and self._recognition is not None:
            pos = build_position(self._recognition, self._flipped_by_labels, self.flip, self.switch_turn)
            preview = preview_data_url(self._img, self._board.rect)
        else:
            return self.latest
        log.info("position %s (%s)%s", pos.fen, pos.orientation_source, "" if pos.valid else f" INVALID: {pos.errors}")

        if not pos.valid:
            return self._publish(Analysis("invalid", "Позиция распознана с ошибкой: " + "; ".join(pos.errors), pos, [], preview))
        if pos.board.is_game_over():
            outcome = pos.board.outcome()
            text = "Мат" if pos.board.is_checkmate() else "Ничья"
            if outcome and outcome.winner is not None:
                text += f": победили {color_name(outcome.winner)}"
            return self._publish(Analysis("game_over", text, pos, [], preview))
        if self.engine is None:
            return self._publish(Analysis("no_engine", "Stockfish не найден: brew install stockfish", pos, [], preview))
        try:
            t0 = time.perf_counter()
            lines = self.engine.analyse(pos.board)
            log.info("engine: %s in %.1fs", ", ".join(f"{l.san} {l.score_text}" for l in lines), time.perf_counter() - t0)
        except Exception as exc:  # engine crashed twice in a row
            log.exception("engine error")
            return self._publish(Analysis("error", f"Ошибка движка: {exc}", pos, [], preview))
        message = f"Лучший ход: {lines[0].san} ({lines[0].score_text})" if lines else ""
        return self._publish(Analysis("ok", message, pos, lines, preview))
