"""Small network helpers shared by both sides."""

from __future__ import annotations

import ipaddress
import socket


def local_ip() -> str:
    """IP of the interface that routes to the LAN (no packets are actually sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def is_lan_address(host: str) -> bool:
    """True for private (RFC 1918 / link-local / loopback) IPv4/IPv6 addresses."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_private or addr.is_loopback or addr.is_link_local


def lan_ipv4_addresses() -> list[str]:
    """Private IPv4 addresses of this machine, the default-route one first."""
    found: list[str] = []
    primary = local_ip()
    if primary != "127.0.0.1":
        found.append(primary)
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        infos = []
    for info in infos:
        ip = str(info[4][0])
        addr = ipaddress.ip_address(ip)
        if addr.is_private and not addr.is_loopback and not addr.is_link_local and ip not in found:
            found.append(ip)
    return found
