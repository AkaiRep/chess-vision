"""FastAPI application: receives screenshots from the client.

Stage 1: authenticate, validate the image, store it in the inbox, reply with its size.
Later stages plug board detection, recognition and the engine in here.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import cv2
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from server.inbox import Inbox
from server.pairing import Pairing
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


def create_app(cfg: ServerConfig) -> FastAPI:
    max_bytes = int(cfg.max_upload_mb * 1024 * 1024)
    inbox = Inbox(cfg.inbox_dir, cfg.keep_inbox)
    pairing = Pairing(cfg.state_file, cfg.token, cfg.pairing_window_s)

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
        log.info("pairing open for %ds: just start the client on Windows", pairing.seconds_left())
        yield
        if announcer:
            await announcer.stop()

    app = FastAPI(title="chess-vision", lifespan=lifespan)

    def require_token(request: Request) -> None:
        if not pairing.check(request.headers.get(TOKEN_HEADER, "")):
            log.warning("rejected request from %s: not paired", _peer(request))
            raise HTTPException(status_code=401, detail="not paired")

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
        h, w = img.shape[:2]
        saved = inbox.save(data, content_type)
        log.info(
            "received %dx%d %s (%d KB) from %s -> %s",
            w, h, content_type, len(data) // 1024, _peer(request), saved.name,
        )
        return {"status": "received", "width": w, "height": h, "file": saved.name}

    return app
