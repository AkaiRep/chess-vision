"""Optional config.toml -> typed dataclasses.

Everything works without a config file: the client finds the server in the LAN and pairs
with it automatically. config.toml only overrides defaults (see config.example.toml).
One file holds both sections; the client reads [client], the server reads [server].
Relative paths are resolved against the directory of the config file (or the project root).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, TypeVar

from shared.protocol import DEFAULT_PORT

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"


@dataclass(frozen=True)
class ClientConfig:
    server_url: str = ""  # empty -> find the server automatically (mDNS, then subnet scan)
    token: str = ""  # empty -> pair with the server automatically
    hotkey: str = "F8"
    select_region_hotkey: str = "ctrl+F8"
    monitor: int = 1  # mss numbering: 1 = primary, 0 = all monitors together
    use_saved_region: bool = True
    image_format: str = "png"  # "png" or "jpeg"
    jpeg_quality: int = 90
    timeout_s: float = 15.0
    sound: bool = False  # Windows beep on success / error
    state_file: Path = Path("client_state.json")


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    token: str = ""  # empty -> generated once and kept in state_file
    pairing_window_s: float = 600.0  # new clients may pair this long after server start
    max_upload_mb: float = 25.0
    inbox_dir: Path = Path("server/inbox")
    keep_inbox: int = 50  # how many received screenshots to keep on disk
    mdns: bool = True
    state_file: Path = Path("server_state.json")
    open_browser: bool = True  # open the analysis page on start
    engine_path: str = ""  # empty -> find stockfish on PATH / Homebrew locations
    think_time_s: float = 1.0
    depth: int = 0  # > 0: fixed depth instead of think time
    multipv: int = 3
    threads: int = 0  # 0: all cores but one
    hash_mb: int = 256


@dataclass(frozen=True)
class AppConfig:
    client: ClientConfig = field(default_factory=ClientConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    path: Path | None = None


T = TypeVar("T")


def _build(cls: type[T], raw: dict[str, Any], section: str, base_dir: Path) -> T:
    known = {f.name: f for f in fields(cls)}  # type: ignore[arg-type]
    unknown = set(raw) - set(known)
    if unknown:
        raise ValueError(f"[{section}]: unknown keys {sorted(unknown)}")
    values: dict[str, Any] = {}
    for name, f in known.items():
        value = raw.get(name, f.default)
        if f.type in ("Path", Path):
            p = Path(value)
            value = p if p.is_absolute() else base_dir / p
        values[name] = value
    return cls(**values)


def load_config(path: Path | str | None = None) -> AppConfig:
    """Read config.toml if it exists; otherwise return defaults."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    raw: dict[str, Any] = {}
    base = PROJECT_ROOT
    if cfg_path.exists():
        with cfg_path.open("rb") as fh:
            raw = tomllib.load(fh)
        base = cfg_path.resolve().parent
    return AppConfig(
        client=_build(ClientConfig, raw.get("client", {}), "client", base),
        server=_build(ServerConfig, raw.get("server", {}), "server", base),
        path=cfg_path if cfg_path.exists() else None,
    )
