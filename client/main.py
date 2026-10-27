"""Client entry point: hotkey -> screenshot -> POST to the Mac.

Run from the project root:  python -m client   (or start_client.bat)
No configuration needed: the server is found in the LAN and paired with automatically.
"""

from __future__ import annotations

import argparse
import logging
import queue
import socket
import sys
from pathlib import Path
from typing import Any

from client import notify
from client.capture import EncodedImage, grab
from client.discovery import discover_server, is_server
from client.hotkey import start_hotkeys
from client.region_select import select_region
from client.sender import NotPaired, SendError, ServerUnreachable, pair, send_image
from client.state import ClientState
from shared.config import ClientConfig, load_config
from shared.logging_setup import setup_logging

log = logging.getLogger("client")


def _enable_dpi_awareness() -> None:
    """Make tkinter and mss agree on physical pixel coordinates on scaled displays."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()


class ClientApp:
    def __init__(self, cfg: ClientConfig) -> None:
        self.cfg = cfg
        self.state = ClientState.load(cfg.state_file)
        if not cfg.use_saved_region:
            self.state.region = None
        self._events: queue.Queue[str] = queue.Queue()

    def _save_state(self) -> None:
        self.state.save(self.cfg.state_file)

    # --- connection -----------------------------------------------------
    def _server_url(self, rediscover: bool = False) -> str:
        if self.cfg.server_url:
            return self.cfg.server_url
        if self.state.server_url and not rediscover:
            return self.state.server_url
        url = discover_server()
        if not url:
            raise ServerUnreachable("server not found in the local network - is it running on the Mac?")
        if url != self.state.server_url:
            self.state.server_url = url
            self._save_state()
        return url

    def _token(self, url: str, repair: bool = False) -> str:
        if self.cfg.token:
            return self.cfg.token
        if self.state.token and not repair:
            return self.state.token
        self.state.token = pair(url, socket.gethostname())
        self._save_state()
        log.info("paired with %s", url)
        return self.state.token

    def connect(self) -> str:
        """Find the server (using the remembered address if it still answers) and pair."""
        url = self._server_url()
        if not self.cfg.server_url and not is_server(url):
            log.info("remembered server %s does not answer, searching again", url)
            url = self._server_url(rediscover=True)
        self._token(url)
        return url

    def _send(self, image: EncodedImage) -> dict[str, Any]:
        url = self._server_url()
        try:
            return send_image(url, self._token(url), image, self.cfg.timeout_s)
        except ServerUnreachable:
            if self.cfg.server_url:
                raise
            log.info("server moved or restarted, searching again")
            url = self._server_url(rediscover=True)
        except NotPaired:
            if self.cfg.token:
                raise
            log.info("server does not know us any more, pairing again")
            self._token(url, repair=True)
        return send_image(url, self._token(url), image, self.cfg.timeout_s)

    # --- actions --------------------------------------------------------
    def capture_and_send(self) -> bool:
        try:
            image = grab(self.cfg.monitor, self.state.region, self.cfg.image_format, self.cfg.jpeg_quality)
            log.info("captured %dx%d, %d KB", image.width, image.height, len(image.data) // 1024)
            result = self._send(image)
        except (SendError, ValueError, RuntimeError) as exc:
            log.error("send failed: %s", exc)
            self._beep(False)
            return False
        return self._report(result)

    def _report(self, result: dict[str, Any]) -> bool:
        """Log the server's verdict; beep "error" if the position could not be analysed."""
        status = result.get("status")
        if status == "ok":
            log.info("best move %s (%s)  |  %s", result.get("best"), result.get("score"), result.get("fen"))
        elif status == "game_over":
            log.info("%s  |  %s", result.get("message"), result.get("fen"))
        else:
            log.warning("sent, but: %s %s", result.get("message") or status, result.get("fen", ""))
            self._beep(False)
            return False
        self._beep(True)
        return True

    def choose_region(self) -> None:
        region = select_region()
        if region is None:
            log.info("region selection cancelled (keeping %s)", self.state.region or "full monitor")
            return
        self.state.region = region
        self._save_state()
        log.info("capture region saved: %s", region)

    def reset_region(self) -> None:
        self.state.region = None
        self._save_state()
        log.info("capture region reset, capturing monitor %d", self.cfg.monitor)

    def _beep(self, ok: bool) -> None:
        if self.cfg.sound:
            notify.beep(ok)

    # --- main loop ------------------------------------------------------
    def run(self) -> None:
        try:
            log.info("connected to %s", self.connect())
        except SendError as exc:
            log.warning("%s (will retry on %s)", exc, self.cfg.hotkey)

        handlers = {"capture": self.capture_and_send, "select": self.choose_region}
        listener = start_hotkeys(
            {
                self.cfg.hotkey: lambda: self._events.put("capture"),
                self.cfg.select_region_hotkey: lambda: self._events.put("select"),
            }
        )
        log.info(
            "ready: %s = capture & send, %s = select area. Capturing: %s. Ctrl+C to quit.",
            self.cfg.hotkey,
            self.cfg.select_region_hotkey,
            self.state.region or f"monitor {self.cfg.monitor}",
        )
        try:
            while True:
                try:
                    event = self._events.get(timeout=0.5)  # timeout keeps Ctrl+C responsive
                except queue.Empty:
                    continue
                handlers[event]()
        except KeyboardInterrupt:
            log.info("bye")
        finally:
            listener.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="chess-vision client (Windows)")
    parser.add_argument("--config", type=Path, default=None, help="optional config.toml")
    parser.add_argument("--once", action="store_true", help="capture and send once, then exit")
    parser.add_argument("--select-region", action="store_true", help="select capture area and exit")
    parser.add_argument("--reset-region", action="store_true", help="forget the saved area and exit")
    args = parser.parse_args(argv)

    setup_logging("client")
    _enable_dpi_awareness()
    app = ClientApp(load_config(args.config).client)

    if args.reset_region:
        app.reset_region()
        return 0
    if args.select_region:
        app.choose_region()
        return 0
    if args.once:
        return 0 if app.capture_and_send() else 1
    app.run()
    return 0
