"""Storage of received screenshots for debugging (bounded ring of files)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


class Inbox:
    def __init__(self, directory: Path, keep: int) -> None:
        self.directory = directory
        self.keep = keep
        directory.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, content_type: str) -> Path:
        ext = ".jpg" if content_type == "image/jpeg" else ".png"
        name = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3] + ext
        path = self.directory / name
        path.write_bytes(data)
        self._prune()
        return path

    def _prune(self) -> None:
        if self.keep <= 0:
            return
        files = sorted(p for p in self.directory.iterdir() if p.suffix in (".png", ".jpg"))
        for old in files[: -self.keep]:
            old.unlink(missing_ok=True)
