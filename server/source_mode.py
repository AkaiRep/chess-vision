"""Which input the server listens to: screenshots (F8 on Windows) or the chess.com extension.

Both clients keep sending; the one not selected on the analysis page is answered with
status "ignored" and does not touch the analysis. The choice survives restarts.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

SCREENSHOT = "screenshot"
PAGE = "page"
MODE_NAMES = {SCREENSHOT: "скриншот (F8)", PAGE: "расширение chess.com"}


class SourceMode:
    def __init__(self, path: Path, default: str = SCREENSHOT) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._value = self._load(default)

    def _load(self, default: str) -> str:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8")).get("source")
        except FileNotFoundError:
            return default
        except (ValueError, AttributeError) as exc:
            log.warning("broken %s (%s), using %s", self.path, exc, default)
            return default
        return value if value in MODE_NAMES else default

    @property
    def value(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        if value not in MODE_NAMES:
            raise ValueError(f"unknown source {value!r}")
        with self._lock:
            self._value = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"source": value}, indent=2), encoding="utf-8")
        log.info("board source: %s", MODE_NAMES[value])

    def ignored(self) -> dict[str, str]:
        """Answer for a client whose source is not the selected one."""
        return {
            "status": "ignored",
            "message": f"на сервере выбран источник «{MODE_NAMES[self._value]}» — переключите на странице анализа",
        }
