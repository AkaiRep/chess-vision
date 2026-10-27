"""Uniform logging for both sides: console + rotating file in logs/<component>.log."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from shared.config import PROJECT_ROOT

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(component: str, level: int = logging.INFO, log_dir: Path | None = None) -> None:
    log_dir = log_dir or PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(FORMAT, datefmt="%H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file = RotatingFileHandler(
        log_dir / f"{component}.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file)
