"""Stage 1: config loading, hotkey parsing, pairing and the /analyze endpoint."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from client.hotkey import to_pynput
from server.app import create_app
from shared.config import ServerConfig, load_config
from shared.net import is_lan_address
from shared.protocol import ANALYZE_PATH, HEALTH_PATH, PAIR_PATH, SERVICE_ID, TOKEN_HEADER

LAN_PEER = ("192.168.1.20", 50000)


def make_cfg(tmp_path: Path, **overrides: object) -> ServerConfig:
    base: dict[str, object] = dict(
        inbox_dir=tmp_path / "inbox",
        state_file=tmp_path / "server_state.json",
        keep_inbox=2,
        mdns=False,
        max_upload_mb=1,
    )
    base.update(overrides)
    return ServerConfig(**base)  # type: ignore[arg-type]


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(make_cfg(tmp_path)), client=LAN_PEER)


@pytest.fixture()
def token(client: TestClient) -> str:
    resp = client.post(PAIR_PATH, json={"name": "pytest"})
    assert resp.status_code == 200
    return resp.json()["token"]


def png_bytes(w: int = 40, h: int = 30) -> bytes:
    ok, buf = cv2.imencode(".png", np.full((h, w, 3), 128, np.uint8))
    assert ok
    return buf.tobytes()


def post(client: TestClient, body: bytes, token: str, ctype: str = "image/png"):
    return client.post(ANALYZE_PATH, content=body, headers={TOKEN_HEADER: token, "Content-Type": ctype})


def test_health_identifies_service(client: TestClient) -> None:
    body = client.get(HEALTH_PATH).json()
    assert body["service"] == SERVICE_ID and body["pairing_open"] is True


def test_accepts_png(client: TestClient, token: str, tmp_path: Path) -> None:
    resp = post(client, png_bytes(), token)
    assert resp.status_code == 200
    assert resp.json()["width"] == 40 and resp.json()["height"] == 30
    assert (tmp_path / "inbox" / resp.json()["file"]).exists()


def test_rejects_bad_token(client: TestClient, token: str) -> None:
    assert post(client, png_bytes(), "wrong").status_code == 401
    assert client.post(ANALYZE_PATH, content=png_bytes()).status_code == 401


def test_rejects_garbage_and_wrong_type(client: TestClient, token: str) -> None:
    assert post(client, b"not an image", token).status_code == 400
    assert post(client, png_bytes(), token, ctype="text/plain").status_code == 415


def test_rejects_too_large(client: TestClient, token: str) -> None:
    assert post(client, b"\0" * (2 * 1024 * 1024), token).status_code == 413


def test_inbox_is_pruned(client: TestClient, token: str, tmp_path: Path) -> None:
    for _ in range(4):
        assert post(client, png_bytes(), token).status_code == 200
    assert len(list((tmp_path / "inbox").iterdir())) == 2


def test_secret_survives_restart(tmp_path: Path) -> None:
    first = TestClient(create_app(make_cfg(tmp_path)), client=LAN_PEER).post(PAIR_PATH, json={}).json()
    second = TestClient(create_app(make_cfg(tmp_path)), client=LAN_PEER).post(PAIR_PATH, json={}).json()
    assert first["token"] == second["token"]


def test_pairing_closed_after_window(tmp_path: Path) -> None:
    c = TestClient(create_app(make_cfg(tmp_path, pairing_window_s=0)), client=LAN_PEER)
    assert c.post(PAIR_PATH, json={}).status_code == 403


def test_pairing_refused_from_internet(tmp_path: Path) -> None:
    c = TestClient(create_app(make_cfg(tmp_path)), client=("8.8.8.8", 1234))
    assert c.post(PAIR_PATH, json={}).status_code == 403


def test_fixed_token_from_config(tmp_path: Path) -> None:
    c = TestClient(create_app(make_cfg(tmp_path, token="fixed")), client=LAN_PEER)
    assert post(c, png_bytes(), "fixed").status_code == 200


@pytest.mark.parametrize(
    ("host", "lan"),
    [("192.168.0.5", True), ("10.1.2.3", True), ("127.0.0.1", True), ("8.8.8.8", False), ("testclient", False)],
)
def test_is_lan_address(host: str, lan: bool) -> None:
    assert is_lan_address(host) is lan


def test_defaults_without_config(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.path is None
    assert cfg.client.server_url == "" and cfg.client.token == ""
    assert cfg.server.inbox_dir.is_absolute() and cfg.client.state_file.is_absolute()


def test_config_example_loads() -> None:
    cfg = load_config(Path(__file__).parent.parent / "config.example.toml")
    assert cfg.client.hotkey == "F8"
    assert cfg.server.inbox_dir.is_absolute()


def test_config_unknown_key(tmp_path: Path) -> None:
    p = tmp_path / "c.toml"
    p.write_text('[client]\nhotkye = "F8"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="hotkye"):
        load_config(p)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [("F8", "<f8>"), ("ctrl+F8", "<ctrl>+<f8>"), ("ctrl+shift+s", "<ctrl>+<shift>+s"), ("<alt>+x", "<alt>+x")],
)
def test_hotkey_parsing(spec: str, expected: str) -> None:
    assert to_pynput(spec) == expected


def test_analyze_finds_board(client: TestClient, token: str) -> None:
    body = (Path(__file__).parent.parent / "samples" / "full_screen_start.png").read_bytes()
    first = post(client, body, token).json()
    assert first["status"] == "board_found"
    assert (first["board"]["x"], first["board"]["y"], first["board"]["w"]) == (396, 153, 808)
    assert post(client, body, token).json()["board"]["cached"] is True
    assert post(client, png_bytes(), token).json()["status"] == "no_board"
