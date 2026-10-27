"""FastAPI application.

- POST /analyze   screenshot from the paired Windows client -> analysis
- GET  /          analysis page (live updates over WebSocket /ws)
- POST /api/...   UI buttons: flip board, switch side to move, recalibrate
The page and its buttons are available from the local network only.
"""

from __future__ import annotations

import asyncio
import logging
import webbrowser
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from server.calibration import TEMPLATES_PATH, CalibrationError
from server.engine import Engine, EngineSettings, find_stockfish
from server.inbox import Inbox
from server.pairing import Pairing
from server.pipeline import Analysis, Analyzer
from shared.config import ServerConfig
from shared.net import is_lan_address
from shared.protocol import (
    ACCEPTED_IMAGE_TYPES,
    ANALYZE_PATH,
    HEALTH_PATH,
    PAIR_PATH,
    SERVICE_ID,
    TOKEN_HEADER,
)

log = logging.getLogger("server")

STATIC_DIR = Path(__file__).parent / "static"


class PairRequest(BaseModel):
    name: str = "?"


def decode_image(data: bytes) -> np.ndarray:
    """Decode PNG/JPEG bytes into a BGR image or raise HTTP 400."""
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="body is not a decodable image")
    return img


def _peer(request: Request) -> str:
    return request.client.host if request.client else "?"


class Hub:
    """Connected browser pages; every new analysis is pushed to all of them."""

    def __init__(self) -> None:
        self._sockets: set[WebSocket] = set()

    async def add(self, ws: WebSocket) -> None:
        self._sockets.add(ws)

    def remove(self, ws: WebSocket) -> None:
        self._sockets.discard(ws)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        for ws in list(self._sockets):
            try:
                await ws.send_json(payload)
            except Exception:  # closed tab
                self._sockets.discard(ws)


def make_engine(cfg: ServerConfig) -> Engine | None:
    path = find_stockfish(cfg.engine_path)
    if path is None:
        log.error("Stockfish not found: install it with `brew install stockfish` (or set engine_path)")
        return None
    settings = EngineSettings(cfg.think_time_s, cfg.depth, cfg.multipv, cfg.threads, cfg.hash_mb)
    return Engine(path, settings)


def create_app(cfg: ServerConfig, templates_path: Path = TEMPLATES_PATH, engine: Engine | None = None) -> FastAPI:
    max_bytes = int(cfg.max_upload_mb * 1024 * 1024)
    inbox = Inbox(cfg.inbox_dir, cfg.keep_inbox)
    pairing = Pairing(cfg.state_file, cfg.token, cfg.pairing_window_s)
    analyzer = Analyzer(engine, templates_path)
    hub = Hub()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        announcer = None
        if cfg.mdns:
            from server.mdns import MdnsAnnouncer

            announcer = MdnsAnnouncer(cfg.port)
            try:
                await announcer.start()
            except Exception:  # discovery is optional, never fail startup because of it
                log.exception("mDNS announcement failed (clients will fall back to a subnet scan)")
                announcer = None
        if engine is not None:
            await run_in_threadpool(engine.start)
        log.info("pairing open for %ds: just start the client on Windows", pairing.seconds_left())
        if cfg.open_browser:
            url = f"http://localhost:{cfg.port}/"
            asyncio.get_running_loop().call_later(1.0, webbrowser.open, url)
            log.info("analysis page: %s", url)
        yield
        if announcer:
            await announcer.stop()
        if engine is not None:
            await run_in_threadpool(engine.close)

    app = FastAPI(title="chess-vision", lifespan=lifespan)

    def require_token(request: Request) -> None:
        if not pairing.check(request.headers.get(TOKEN_HEADER, "")):
            log.warning("rejected request from %s: not paired", _peer(request))
            raise HTTPException(status_code=401, detail="not paired")

    def require_lan(request: Request) -> None:
        if not is_lan_address(_peer(request)):
            raise HTTPException(status_code=403, detail="local network only")

    async def publish(analysis: Analysis) -> dict[str, Any]:
        state = analysis.to_json()
        await hub.broadcast(state)
        return state

    @app.get(HEALTH_PATH)
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": SERVICE_ID, "pairing_open": pairing.window_open()}

    @app.post(PAIR_PATH)
    def pair(body: PairRequest, request: Request) -> dict[str, str]:
        peer = _peer(request)
        if not is_lan_address(peer):
            log.warning("pairing refused for %s: not a LAN address", peer)
            raise HTTPException(status_code=403, detail="pairing is only allowed from the local network")
        if not pairing.window_open():
            log.warning("pairing refused for %r (%s): window closed", body.name, peer)
            raise HTTPException(
                status_code=403,
                detail="pairing window closed: restart the server on the Mac, then retry within 10 minutes",
            )
        log.info("paired client %r from %s", body.name, peer)
        return {"token": pairing.token}

    @app.post(ANALYZE_PATH, dependencies=[Depends(require_token)])
    async def analyze(request: Request) -> dict[str, Any]:
        content_type = request.headers.get("content-type", "").split(";")[0].strip()
        if content_type not in ACCEPTED_IMAGE_TYPES:
            raise HTTPException(status_code=415, detail=f"expected one of {ACCEPTED_IMAGE_TYPES}")
        declared = int(request.headers.get("content-length") or 0)
        if declared > max_bytes:
            raise HTTPException(status_code=413, detail="image too large")
        data = await request.body()
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail="image too large")

        img = decode_image(data)
        saved = inbox.save(data, content_type)
        log.info(
            "received %dx%d %s (%d KB) from %s -> %s",
            img.shape[1], img.shape[0], content_type, len(data) // 1024, _peer(request), saved.name,
        )
        analysis = await run_in_threadpool(analyzer.analyze_image, img)
        await publish(analysis)
        return analysis.summary()

    # --- web UI ------------------------------------------------------------
    @app.get("/", dependencies=[Depends(require_lan)])
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/state", dependencies=[Depends(require_lan)])
    def state() -> dict[str, Any]:
        return analyzer.latest.to_json()

    @app.post("/api/flip", dependencies=[Depends(require_lan)])
    async def flip() -> dict[str, Any]:
        return await publish(await run_in_threadpool(analyzer.toggle_flip))

    @app.post("/api/turn", dependencies=[Depends(require_lan)])
    async def turn() -> dict[str, Any]:
        return await publish(await run_in_threadpool(analyzer.toggle_turn))

    @app.post("/api/recalibrate", dependencies=[Depends(require_lan)])
    async def recalibrate() -> dict[str, Any]:
        try:
            analysis = await run_in_threadpool(analyzer.recalibrate)
        except CalibrationError as exc:
            raise HTTPException(status_code=400, detail=f"Калибровка не удалась: {exc}") from exc
        return await publish(analysis)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        if not is_lan_address(ws.client.host if ws.client else ""):
            await ws.close(code=1008)
            return
        await ws.accept()
        await hub.add(ws)
        try:
            await ws.send_json(analyzer.latest.to_json())
            while True:
                await ws.receive_text()  # keep-alive pings from the page
        except WebSocketDisconnect:
            pass
        finally:
            hub.remove(ws)

    return app
