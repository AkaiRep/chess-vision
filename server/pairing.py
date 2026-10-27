"""Zero-config authentication.

The server owns one random secret, generated on first start and kept in server_state.json.
A client gets it via POST /pair, which is only allowed from LAN addresses and only during
the pairing window right after the server starts. Afterwards only paired clients get in.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import time
from pathlib import Path

log = logging.getLogger(__name__)


class Pairing:
    def __init__(self, state_file: Path, fixed_token: str = "", window_s: float = 600.0) -> None:
        self.state_file = state_file
        self.window_s = window_s
        self._started = time.monotonic()
        self.token = fixed_token or self._load_or_create()

    def _load_or_create(self) -> str:
        if self.state_file.exists():
            try:
                token = json.loads(self.state_file.read_text(encoding="utf-8"))["token"]
                if isinstance(token, str) and token:
                    return token
            except (ValueError, KeyError) as exc:
                log.warning("broken %s (%s), generating a new secret", self.state_file, exc)
        token = secrets.token_urlsafe(32)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({"token": token}, indent=2), encoding="utf-8")
        log.info("generated a new server secret in %s", self.state_file)
        return token

    def window_open(self) -> bool:
        return time.monotonic() - self._started < self.window_s

    def seconds_left(self) -> int:
        return max(0, int(self.window_s - (time.monotonic() - self._started)))

    def check(self, sent: str) -> bool:
        return hmac.compare_digest(sent.encode(), self.token.encode())
