"""Piece recognition by template matching.

Every cell is reduced to a square-colour independent feature map: the central ~70 % of
the cell in grayscale, with pixels that look like the cell background (light, dark or
highlighted square) replaced by a neutral value. The coordinate labels in the cell
corners fall outside the central crop. Templates of all 12 pieces come from a
calibration screenshot of the starting position (see server/calibration.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from server.board_locator import CELL, BoardTheme, LocatedBoard, SquareShade, cell_background, classify_shade

log = logging.getLogger(__name__)

MARGIN = round(CELL * 0.15)  # crop away 15 % on each side -> central 70 %
SHIFT = 4  # cells are matched with up to +-SHIFT px offset
FG_DISTANCE = 22.0  # BGR distance from the cell background that counts as "piece"
EMPTY_FRACTION = 0.06  # less foreground than this -> empty cell
NEUTRAL = 128.0
MIN_SCORE = 0.70  # below -> suspicious
MIN_MARGIN = 0.06  # best vs best other piece closer than this -> suspicious

EMPTY = "."
PIECES = "PNBRQKpnbrqk"

# Rank number drawn in the top-left corner of the left-most cells ("8" on top when white is
# at the bottom). The template is a tight box; the search window allows a few px of offset.
LABEL_TEMPLATE = (slice(8, 28), slice(4, 18))
LABEL_SEARCH = (slice(4, 32), slice(0, 22))
LABEL_DISTANCE = 40.0


def _foreground(region: np.ndarray, bg: np.ndarray) -> np.ndarray:
    return np.linalg.norm(region.astype(np.float32) - bg.astype(np.float32), axis=2) > FG_DISTANCE


def _feature(region: np.ndarray, bg: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return np.where(_foreground(region, bg), gray, NEUTRAL).astype(np.float32)


def cell_features(cell: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    """-> (template-size feature, feature with SHIFT margin for searching, fg fraction, bg colour)."""
    bg = cell_background(cell)
    inner = cell[MARGIN : CELL - MARGIN, MARGIN : CELL - MARGIN]
    wide = cell[MARGIN - SHIFT : CELL - MARGIN + SHIFT, MARGIN - SHIFT : CELL - MARGIN + SHIFT]
    fraction = float(_foreground(inner, bg).mean())
    return _feature(inner, bg), _feature(wide, bg), fraction, bg


def label_mask(cell: np.ndarray, region: tuple[slice, slice]) -> np.ndarray:
    """Pixels of a coordinate label (anything far from the square colour) as float mask."""
    bg = cell_background(cell)
    patch = cell[region].astype(np.float32)
    return (np.linalg.norm(patch - bg.astype(np.float32), axis=2) > LABEL_DISTANCE).astype(np.float32)


def _match(search: np.ndarray, template: np.ndarray) -> float:
    if template.std() == 0 or search.std() == 0:
        return 0.0
    return float(cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED).max())


@dataclass
class Templates:
    labels: list[str]  # piece letter per template ("P", "n", ...)
    features: np.ndarray  # (N, h, w) float32
    theme: BoardTheme
    empty_fraction: float = EMPTY_FRACTION
    rank8: np.ndarray | None = None  # mask of the "8" label
    rank1: np.ndarray | None = None  # mask of the "1" label

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            labels=np.array(self.labels),
            features=self.features,
            light=np.array(self.theme.light),
            dark=np.array(self.theme.dark),
            tolerance=np.array(self.theme.tolerance),
            empty_fraction=np.array(self.empty_fraction),
            rank8=self.rank8 if self.rank8 is not None else np.zeros((0, 0), np.float32),
            rank1=self.rank1 if self.rank1 is not None else np.zeros((0, 0), np.float32),
        )

    @classmethod
    def load(cls, path: Path) -> Templates:
        with np.load(path) as data:
            theme = BoardTheme(
                light=tuple(int(v) for v in data["light"]),  # type: ignore[arg-type]
                dark=tuple(int(v) for v in data["dark"]),  # type: ignore[arg-type]
                tolerance=int(data["tolerance"]),
            )
            return cls(
                labels=[str(s) for s in data["labels"]],
                features=data["features"].astype(np.float32),
                theme=theme,
                empty_fraction=float(data["empty_fraction"]),
                rank8=data["rank8"] if data["rank8"].size else None,
                rank1=data["rank1"] if data["rank1"].size else None,
            )


@dataclass(frozen=True)
class CellResult:
    label: str  # "." or a piece letter
    score: float  # match score of the chosen label (1.0 for confident empties)
    runner_up: str  # best different label (for debugging)
    margin: float  # score gap to runner_up
    shade: SquareShade  # background shade of the square
    suspicious: bool


@dataclass
class Recognition:
    """Cells in screen order: cells[row][col], row 0 = top of the screen."""

    cells: list[list[CellResult]] = field(default_factory=list)

    def labels(self) -> list[list[str]]:
        return [[c.label for c in row] for row in self.cells]

    def suspicious(self) -> list[tuple[int, int]]:
        return [(r, c) for r, row in enumerate(self.cells) for c, cell in enumerate(row) if cell.suspicious]

    def placement(self) -> str:
        """FEN-like placement in screen order (top row first), not yet oriented."""
        rows = []
        for row in self.labels():
            out, run = "", 0
            for label in row:
                if label == EMPTY:
                    run += 1
                    continue
                out += (str(run) if run else "") + label
                run = 0
            rows.append(out + (str(run) if run else ""))
        return "/".join(rows)


class Recognizer:
    def __init__(self, templates: Templates) -> None:
        self.templates = templates

    def classify_cell(self, cell: np.ndarray) -> CellResult:
        _, wide, fraction, bg = cell_features(cell)
        shade = classify_shade(bg, self.templates.theme)
        if fraction < self.templates.empty_fraction:
            confident = fraction < self.templates.empty_fraction / 2
            return CellResult(EMPTY, 1.0, "?", 1.0, shade, suspicious=not confident)

        best: dict[str, float] = {}
        for label, tmpl in zip(self.templates.labels, self.templates.features):
            score = float(cv2.matchTemplate(wide, tmpl, cv2.TM_CCOEFF_NORMED).max())
            if score > best.get(label, -1.0):
                best[label] = score
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        (label, score), (runner_up, second) = ranked[0], ranked[1]
        margin = score - second
        suspicious = score < MIN_SCORE or margin < MIN_MARGIN
        return CellResult(label, score, runner_up, margin, shade, suspicious)

    def flipped_by_labels(self, board: LocatedBoard) -> bool | None:
        """Orientation from the rank numbers in the left column; None if they are not readable."""
        t = self.templates
        if t.rank8 is None or t.rank1 is None:
            return None
        top = label_mask(board.cell(0, 0), LABEL_SEARCH)
        bottom = label_mask(board.cell(7, 0), LABEL_SEARCH)
        normal = _match(top, t.rank8) + _match(bottom, t.rank1)
        flipped = _match(top, t.rank1) + _match(bottom, t.rank8)
        log.debug("rank labels: normal=%.2f flipped=%.2f", normal, flipped)
        if max(normal, flipped) < 1.0 or abs(normal - flipped) < 0.3:
            return None
        return flipped > normal

    def recognize(self, board: LocatedBoard) -> Recognition:
        cells = [[self.classify_cell(board.cell(r, c)) for c in range(8)] for r in range(8)]
        result = Recognition(cells)
        for r, c in result.suspicious():
            cell = result.cells[r][c]
            log.info(
                "uncertain cell row=%d col=%d: %s %.2f (next %s, margin %.2f)",
                r, c, cell.label, cell.score, cell.runner_up, cell.margin,
            )
        return result
