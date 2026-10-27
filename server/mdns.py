"""Announce the server in the LAN via mDNS so the client can find it without an IP."""

from __future__ import annotations

import logging
import socket

from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

from shared.net import local_ip
from shared.protocol import ANALYZE_PATH, MDNS_SERVICE_NAME, MDNS_SERVICE_TYPE

log = logging.getLogger(__name__)


class MdnsAnnouncer:
    def __init__(self, port: int) -> None:
        self.port = port
        self._zc: AsyncZeroconf | None = None
        self._info: ServiceInfo | None = None

    async def start(self) -> None:
        ip = local_ip()
        host = socket.gethostname().split(".")[0]
        self._info = ServiceInfo(
            MDNS_SERVICE_TYPE,
            f"{MDNS_SERVICE_NAME} ({host}).{MDNS_SERVICE_TYPE}",
            addresses=[socket.inet_aton(ip)],
            port=self.port,
            properties={"path": ANALYZE_PATH},
            server=f"{host}.local.",
        )
        self._zc = AsyncZeroconf()
        await self._zc.async_register_service(self._info)
        log.info("mDNS: announced %s at %s:%d", MDNS_SERVICE_TYPE, ip, self.port)

    async def stop(self) -> None:
        if self._zc and self._info:
            await self._zc.async_unregister_service(self._info)
            await self._zc.async_close()
            self._zc = None
