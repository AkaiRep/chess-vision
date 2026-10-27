"""Stage 5: analysis page, buttons, WebSocket push and the full pipeline with Stockfish."""

from __future__ import annotations

import json
from pathlib import Path

import chess
import cv2
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.engine import Engine, EngineSettings, find_stockfish
from shared.config import ServerConfig
from shared.protocol import ANALYZE_PATH, PAIR_PATH, TOKEN_HEADER
from tests.synth import render_board, screenshot

SAMPLES = Path(__file__).parent.parent / "samples"
LAN_PEER = ("192.168.1.20", 50000)
STOCKFISH = find_stockfish()


def png(img) -> bytes:  # type: ignore[no-untyped-def]
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def make_client(tmp_path: Path, engine: Engine | None = None, peer: tuple[str, int] = LAN_PEER) -> TestClient:
    cfg = ServerConfig(
        inbox_dir=tmp_path / "inbox",
        state_file=tmp_path / "state.json",
        mdns=False,
        open_browser=False,
    )
    return TestClient(create_app(cfg, tmp_path / "templates.npz", engine), client=peer)


def send(client: TestClient, img_bytes: bytes) -> dict:  # type: ignore[type-arg]
    token = client.post(PAIR_PATH, json={}).json()["token"]
    resp = client.post(ANALYZE_PATH, content=img_bytes, headers={TOKEN_HEADER: token, "Content-Type": "image/png"})
    assert resp.status_code == 200
    return resp.json()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return make_client(tmp_path)


def test_page_served_on_lan_only(client: TestClient, tmp_path: Path) -> None:
    assert "chess-vision" in client.get("/").text
    outsider = make_client(tmp_path, peer=("8.8.8.8", 1))
    assert outsider.get("/").status_code == 403
    assert outsider.post("/api/flip").status_code == 403


def test_waiting_state(client: TestClient) -> None:
    assert client.get("/api/state").json()["status"] == "waiting"


def test_websocket_receives_new_analysis(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["status"] == "waiting"
        send(client, (SAMPLES / "full_screen_start.png").read_bytes())
        pushed = ws.receive_json()
    assert pushed["fen"].startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w")
    assert "<svg" in pushed["svg"] and pushed["preview"].startswith("data:image/jpeg;base64,")
    assert pushed["my_color"] == "белые"


def test_flip_and_turn_buttons(client: TestClient) -> None:
    send(client, (SAMPLES / "full_screen_start.png").read_bytes())
    turned = client.post("/api/turn").json()
    assert turned["turn"] == "чёрные" and turned["my_turn"] is False
    flipped = client.post("/api/flip").json()
    assert flipped["my_color"] == "чёрные" and flipped["orientation"] == "manual"
    # a new screenshot resets the manual overrides
    fresh = send(client, (SAMPLES / "full_screen_start.png").read_bytes())
    assert fresh["fen"].split()[1] == "w"
    assert client.get("/api/state").json()["orientation"] == "labels"


def test_recalibrate(client: TestClient, tmp_path: Path) -> None:
    send(client, (SAMPLES / "start_position.jpg").read_bytes())
    resp = client.post("/api/recalibrate")
    assert resp.status_code == 200 and resp.json()["fen"].startswith("rnbqkbnr/pppppppp")
    assert (tmp_path / "templates.npz").exists()

    middlegame = chess.Board()
    for san in "e4 e5 Nf3".split():
        middlegame.push_san(san)
    send(client, png(screenshot(render_board(middlegame.fen()))))
    bad = client.post("/api/recalibrate")
    assert bad.status_code == 400 and "Калибровка" in bad.json()["detail"]


@pytest.mark.skipif(STOCKFISH is None, reason="stockfish not installed (set STOCKFISH_PATH)")
def test_full_pipeline_with_engine(tmp_path: Path) -> None:
    assert STOCKFISH is not None
    engine = Engine(STOCKFISH, EngineSettings(think_time_s=0.3, threads=2, hash_mb=32))
    # scholar's mate threat: white to move mates with Qxf7#
    board = chess.Board()
    for san in "e4 e5 Bc4 Nc6 Qh5 Nf6".split():
        board.push_san(san)
    with make_client(tmp_path, engine) as client:  # context manager runs startup/shutdown
        summary = send(client, png(screenshot(render_board(board.fen(), highlight=("g8", "f6")))))
        state = client.get("/api/state").json()
    assert summary["status"] == "ok"
    assert summary["best"] == "Qxf7#" and summary["score"] == "#1"
    assert len(state["lines"]) == 3 and state["eval"]["white_share"] == 1.0
    assert "<svg" in state["svg"] and not state["warnings"]



def test_websocket_push_on_real_uvicorn(tmp_path: Path) -> None:
    """The TestClient does not need a WebSocket library, real uvicorn does: check the real thing."""
    import asyncio
    import socket
    import threading
    import time

    import requests
    import uvicorn
    import websockets

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    cfg = ServerConfig(
        port=port, inbox_dir=tmp_path / "inbox", state_file=tmp_path / "state.json", mdns=False, open_browser=False
    )
    server = uvicorn.Server(uvicorn.Config(create_app(cfg, tmp_path / "templates.npz"), port=port, log_config=None))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    async def scenario() -> dict:  # type: ignore[type-arg]
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            assert json.loads(await ws.recv())["status"] == "waiting"
            token = requests.post(base + PAIR_PATH, json={}).json()["token"]
            body = (SAMPLES / "full_screen_start.png").read_bytes()
            await asyncio.to_thread(
                requests.post,
                base + ANALYZE_PATH,
                data=body,
                headers={TOKEN_HEADER: token, "Content-Type": "image/png"},
            )
            return json.loads(await asyncio.wait_for(ws.recv(), timeout=10))

    try:
        pushed = asyncio.run(scenario())
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    assert pushed["fen"].startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR")
