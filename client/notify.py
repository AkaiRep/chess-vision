"""Tiny audible feedback (Windows only, no extra dependencies)."""

from __future__ import annotations

import sys


def beep(ok: bool) -> None:
    if sys.platform != "win32":
        return
    import winsound

    winsound.MessageBeep(winsound.MB_OK if ok else winsound.MB_ICONHAND)
