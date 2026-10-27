"""Build piece templates from a screenshot of the starting position.

Works for either orientation (white or black at the bottom). Every piece type is taken
from every square it stands on, so most pieces get both a light- and a dark-square
variant. The board colours are re-measured from the empty squares.

    python -m server.calibration path/to/start_position.png
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import cv2
import numpy as np

from server.board_locator import DEFAULT_THEME, BoardLocator, BoardTheme
from server.recognizer import EMPTY_FRACTION, LABEL_TEMPLATE, Recognizer, Templates, cell_features, label_mask
from shared.config import PROJECT_ROOT

log = logging.getLogger(__name__)

TEMPLATES_PATH = PROJECT_ROOT / "data" / "templates" / "templates.npz"
DEFAULT_CALIBRATION_IMAGE = PROJECT_ROOT / "samples" / "full_screen_start.png"

# Starting position in screen order (row 0 = top) for both orientations.
START_WHITE_BOTTOM = ["rnbqkbnr", "pppppppp", "........", "........", "........", "........", "PPPPPPPP", "RNBQKBNR"]
START_BLACK_BOTTOM = ["RNBKQBNR", "PPPPPPPP", "........", "........", "........", "........", "pppppppp", "rnbkqbnr"]
PIECE_ROWS = (0, 1, 6, 7)


class CalibrationError(Exception):
    pass


def calibrate(img: np.ndarray, theme: BoardTheme = DEFAULT_THEME) -> Templates:
    board = BoardLocator(theme).locate(img)
    if board is None:
        raise CalibrationError("chess board not found on the calibration image")

    feats = [[cell_features(board.cell(r, c)) for c in range(8)] for r in range(8)]
    for r in range(8):
        for c in range(8):
            fraction = feats[r][c][2]
            if r in PIECE_ROWS and fraction < 2 * EMPTY_FRACTION:
                raise CalibrationError(f"expected a piece at row {r} col {c}: is this the starting position?")
            if r not in PIECE_ROWS and fraction >= EMPTY_FRACTION / 2:
                raise CalibrationError(f"expected an empty square at row {r} col {c}: is this the starting position?")

    def piece_brightness(row: int) -> float:
        values = []
        for c in range(8):
            cell = board.cell(row, c)
            gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
            values.append(float(np.median(gray[30:70, 30:70])))
        return float(np.mean(values))

    white_bottom = piece_brightness(7) > piece_brightness(0)
    layout = START_WHITE_BOTTOM if white_bottom else START_BLACK_BOTTOM

    labels: list[str] = []
    features: list[np.ndarray] = []
    for r in PIECE_ROWS:
        for c in range(8):
            labels.append(layout[r][c])
            features.append(feats[r][c][0])

    light = [feats[r][c][3] for r in range(2, 6) for c in range(8) if (r + c) % 2 == 0]
    dark = [feats[r][c][3] for r in range(2, 6) for c in range(8) if (r + c) % 2 == 1]
    measured = BoardTheme(
        light=tuple(int(v) for v in np.median(light, axis=0)),  # type: ignore[arg-type]
        dark=tuple(int(v) for v in np.median(dark, axis=0)),  # type: ignore[arg-type]
        tolerance=theme.tolerance,
    )
    top_label = label_mask(board.cell(0, 0), LABEL_TEMPLATE)
    bottom_label = label_mask(board.cell(7, 0), LABEL_TEMPLATE)
    rank8, rank1 = (top_label, bottom_label) if white_bottom else (bottom_label, top_label)
    has_labels = min(rank8.mean(), rank1.mean()) > 0.05
    if not has_labels:
        log.info("no rank labels found: orientation will be guessed from the pieces")
    templates = Templates(
        labels,
        np.stack(features),
        measured,
        rank8=rank8 if has_labels else None,
        rank1=rank1 if has_labels else None,
    )

    # Self-check: the calibration image itself must be recognised exactly.
    got = Recognizer(templates).recognize(board).labels()
    if ["".join(row) for row in got] != layout:
        raise CalibrationError(f"self-check failed: {got}")
    if has_labels and Recognizer(templates).flipped_by_labels(board) is not (not white_bottom):
        raise CalibrationError("self-check failed: rank labels do not give the orientation")
    log.info(
        "calibrated %d templates (%s at the bottom), light=%s dark=%s",
        len(labels), "white" if white_bottom else "black", measured.light, measured.dark,
    )
    return templates


def load_or_calibrate(path: Path = TEMPLATES_PATH, image: Path = DEFAULT_CALIBRATION_IMAGE) -> Templates:
    """Templates from disk; on first start they are built from the bundled sample."""
    if path.exists():
        try:
            return Templates.load(path)
        except (OSError, KeyError, ValueError) as exc:
            log.warning("cannot read %s (%s), recalibrating", path, exc)
    img = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if img is None:
        raise CalibrationError(f"cannot read calibration image {image}")
    templates = calibrate(img)
    templates.save(path)
    log.info("templates saved to %s", path)
    return templates


def main() -> int:
    parser = argparse.ArgumentParser(description="Build piece templates from a starting-position screenshot")
    parser.add_argument("image", type=Path)
    parser.add_argument("--out", type=Path, default=TEMPLATES_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    img = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if img is None:
        print(f"cannot read {args.image}")
        return 1
    try:
        templates = calibrate(img)
    except CalibrationError as exc:
        print(f"calibration failed: {exc}")
        return 1
    templates.save(args.out)
    print(f"saved {len(templates.labels)} templates to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
