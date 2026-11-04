"""Browser extension path: board read from the chess.com page -> position -> analysis."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import chess
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.pipeline import Analyzer, PageBoard
from server.position import position_from_page
from shared.config import ServerConfig
from shared.protocol import ANALYZE_PATH, PAIR_PATH, POSITION_PATH, TOKEN_HEADER

LAN_PEER = ("192.168.1.20", 50000)
START = chess.STARTING_BOARD_FEN


def sq(*names: str) -> list[int]:
    return [chess.parse_square(n) for n in names]


def head(fen: str) -> list[str]:
    """FEN without the move counters (the page does not show them)."""
    return fen.split()[:4]


def after(*sans: str) -> chess.Board:
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board


# --- position_from_page ------------------------------------------------------
def test_start_position_white_to_move_even_when_flipped() -> None:
    pos = position_from_page(START, flipped=True, highlighted=[])
    assert pos.fen == chess.STARTING_FEN
    assert pos.my_color == chess.BLACK and pos.orientation_source == "page"


def test_side_to_move_from_last_move() -> None:
    board = after("e4")
    pos = position_from_page(board.board_fen(), flipped=False, highlighted=sq("e2", "e4"))
    assert pos.board.turn == chess.BLACK and pos.last_move == (chess.E2, chess.E4)
    assert pos.fen.split()[1:3] == ["b", "KQkq"] and not pos.warnings


def test_playing_black_after_opponent_moved() -> None:
    board = after("e4", "c5", "Nf3")
    pos = position_from_page(board.board_fen(), flipped=True, highlighted=sq("g1", "f3"))
    assert pos.board.turn == chess.BLACK and pos.my_color == chess.BLACK
    assert head(pos.fen) == head(board.fen())


def test_en_passant_from_last_move() -> None:
    board = after("e4", "a6", "e5", "d5")
    pos = position_from_page(board.board_fen(), flipped=False, highlighted=sq("d7", "d5"))
    assert pos.board.turn == chess.WHITE and pos.board.ep_square == chess.D6
    assert head(pos.fen) == head(board.fen(en_passant="legal"))


def test_no_highlight_means_my_move() -> None:
    board = after("e4", "e5", "Nf3", "Nc6")
    pos = position_from_page(board.board_fen(), flipped=True, highlighted=[])
    assert pos.board.turn == chess.BLACK


def test_manual_overrides() -> None:
    board = after("e4")
    pos = position_from_page(board.board_fen(), False, sq("e2", "e4"), flip=True, switch_turn=True)
    assert pos.orientation_source == "manual" and pos.my_color == chess.BLACK
    assert pos.board.turn == chess.WHITE and pos.warnings  # white just moved and is to move again


def test_invalid_position_reported() -> None:
    pos = position_from_page("8/8/8/8/8/8/8/K7", flipped=False, highlighted=[])
    assert not pos.valid and "нет чёрного короля" in pos.errors


# --- endpoint ----------------------------------------------------------------
def make_client(tmp_path: Path) -> TestClient:
    cfg = ServerConfig(
        inbox_dir=tmp_path / "inbox", state_file=tmp_path / "state.json", mdns=False, open_browser=False
    )
    return TestClient(create_app(cfg, tmp_path / "templates.npz"), client=LAN_PEER)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Server switched to the extension source."""
    c = make_client(tmp_path)
    assert c.post("/api/mode", json={"mode": "page"}).json()["mode"] == "page"
    return c


# --- source switch -------------------------------------------------------------
def test_default_source_is_screenshot_and_page_is_ignored(tmp_path: Path) -> None:
    c = make_client(tmp_path)
    assert c.get("/api/state").json()["mode"] == "screenshot"
    resp = post(c, {"placement": START})
    assert resp.status_code == 200 and resp.json()["status"] == "ignored"
    assert c.get("/api/state").json()["status"] == "waiting"


def test_screenshot_ignored_in_page_mode(client: TestClient) -> None:
    token = client.post(PAIR_PATH, json={}).json()["token"]
    resp = client.post(ANALYZE_PATH, content=b"x", headers={TOKEN_HEADER: token, "Content-Type": "image/png"})
    assert resp.json()["status"] == "ignored" and "расширение" in resp.json()["message"]
    assert client.post(ANALYZE_PATH, content=b"x", headers={TOKEN_HEADER: "bad"}).status_code == 401


def test_source_switch_persists_and_is_pushed(client: TestClient, tmp_path: Path) -> None:
    assert make_client(tmp_path).get("/api/state").json()["mode"] == "page"  # survives a restart
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["mode"] == "page"
        client.post("/api/mode", json={"mode": "screenshot"})
        assert ws.receive_json()["mode"] == "screenshot"
    assert client.post("/api/mode", json={"mode": "telepathy"}).status_code == 400


def post(client: TestClient, body: dict, token: str | None = None):  # type: ignore[no-untyped-def,type-arg]
    if token is None:
        token = client.post(PAIR_PATH, json={"name": "extension"}).json()["token"]
    return client.post(POSITION_PATH, json=body, headers={TOKEN_HEADER: token})


def test_requires_token(client: TestClient) -> None:
    assert post(client, {"placement": START}, token="wrong").status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"placement": "not a fen"},
        {"placement": START, "highlighted": ["z9"]},
        {"placement": "x" * 200},
        {"flipped": True},
    ],
)
def test_rejects_garbage(client: TestClient, body: dict) -> None:  # type: ignore[type-arg]
    assert post(client, body).status_code in (400, 422)


def test_position_pushed_to_page(client: TestClient) -> None:
    board = after("d4", "Nf6")
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["status"] == "waiting"
        summary = post(client, {"placement": board.board_fen(), "highlighted": ["g8", "f6"]}).json()
        pushed = ws.receive_json()
    assert head(summary["fen"]) == head(board.fen())
    assert summary["status"] == "no_engine"  # no Stockfish in this test app
    assert pushed["source"] == "page" and pushed["site"] == "chess.com"
    assert pushed["preview"] == "" and "<svg" in pushed["svg"]


def test_buttons_work_on_page_position(client: TestClient) -> None:
    post(client, {"placement": START})
    assert client.post("/api/turn").json()["turn"] == "чёрные"
    flipped = client.post("/api/flip").json()
    assert flipped["my_color"] == "чёрные" and flipped["source"] == "page"
    assert client.post("/api/recalibrate").status_code == 400  # needs a screenshot
    # the next position from the page resets the overrides
    assert post(client, {"placement": START}).json()["fen"].split()[1] == "w"
    assert client.get("/api/state").json()["orientation"] == "page"


def test_stale_page_position_is_skipped(tmp_path: Path) -> None:
    analyzer = Analyzer(None, tmp_path / "templates.npz")
    results: dict[str, object] = {}

    def run(name: str, page: PageBoard) -> None:
        results[name] = analyzer.analyze_page(page)

    old = PageBoard(START, False, [])
    new = PageBoard(after("e4").board_fen(), False, sq("e2", "e4"))
    with analyzer._lock:  # the engine is "busy" while both positions arrive
        t1 = threading.Thread(target=run, args=("old", old))
        t1.start()
        while analyzer._page_requests < 1:
            time.sleep(0.001)
        t2 = threading.Thread(target=run, args=("new", new))
        t2.start()
        while analyzer._page_requests < 2:
            time.sleep(0.001)
    t1.join()
    t2.join()
    assert results["old"] is None
    assert analyzer.latest.position is not None and analyzer.latest.position.board.turn == chess.BLACK
