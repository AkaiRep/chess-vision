"""Persisted client state: remembered capture region, server address and pairing token."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from client.capture import Region

log = logging.getLogger(__name__)


@dataclass
class ClientState:
    region: Region | None = None
    server_url: str | None = None
    token: str | None = None

    @classmethod
    def load(cls, path: Path) -> ClientState:
        if not path.exists():
            return cls()
        try:
            raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            region = Region(**raw["region"]) if raw.get("region") else None
            return cls(region=region, server_url=raw.get("server_url"), token=raw.get("token"))
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("ignoring broken state file %s: %s", path, exc)
            return cls()

    def save(self, path: Path) -> None:
        raw = {
            "region": self.region.as_mss() if self.region else None,
            "server_url": self.server_url,
            "token": self.token,
        }
        path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
