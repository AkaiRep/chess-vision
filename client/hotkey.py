"""Global hotkeys via pynput."""

from __future__ import annotations

from collections.abc import Callable

from pynput import keyboard


def to_pynput(spec: str) -> str:
    """Convert a human hotkey like "ctrl+F8" into pynput syntax "<ctrl>+<f8>"."""
    parts = [p.strip() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"empty hotkey: {spec!r}")
    out = []
    for p in parts:
        if p.startswith("<") and p.endswith(">"):
            out.append(p.lower())
        elif len(p) == 1:
            out.append(p.lower())
        else:
            out.append(f"<{p.lower()}>")
    return "+".join(out)


def start_hotkeys(bindings: dict[str, Callable[[], None]]) -> keyboard.GlobalHotKeys:
    """Start a background listener. Callbacks run in the listener thread — keep them short."""
    listener = keyboard.GlobalHotKeys({to_pynput(k): cb for k, cb in bindings.items()})
    listener.start()
    return listener
