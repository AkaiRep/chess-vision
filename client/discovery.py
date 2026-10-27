"""Find the server in the LAN automatically.

1. mDNS / zeroconf (fast, works on most home networks).
2. Fallback: probe GET /health on every host of this machine's /24 subnet(s).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
from concurrent.futures import ThreadPoolExecutor

import requests

from shared.net import lan_ipv4_addresses
from shared.protocol import DEFAULT_PORT, HEALTH_PATH, MDNS_SERVICE_TYPE, SERVICE_ID

log = logging.getLogger(__name__)

MAX_SUBNETS = 3


def discover_server(mdns_timeout_s: float = 3.0, port: int = DEFAULT_PORT) -> str | None:
    """Return "http://ip:port" of a running server, or None."""
    return discover_mdns(mdns_timeout_s) or scan_subnets(port)


def is_server(url: str, timeout_s: float = 1.0) -> bool:
    try:
        resp = requests.get(url.rstrip("/") + HEALTH_PATH, timeout=timeout_s)
        return resp.ok and resp.json().get("service") == SERVICE_ID
    except (requests.RequestException, ValueError):
        return False


def discover_mdns(timeout_s: float) -> str | None:
    try:
        from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf
    except ImportError:
        log.warning("zeroconf is not installed, skipping mDNS")
        return None

    found: list[str] = []
    done = threading.Event()
    try:
        zc = Zeroconf()
    except OSError as exc:
        log.warning("mDNS unavailable: %s", exc)
        return None

    def on_change(zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        if state_change is not ServiceStateChange.Added or done.is_set():
            return
        info = zeroconf.get_service_info(service_type, name, timeout=int(timeout_s * 1000))
        if not (info and info.port):
            return
        for raw in info.addresses:
            url = f"http://{socket.inet_ntoa(raw)}:{info.port}"
            if is_server(url):
                found.append(url)
                done.set()
                return

    try:
        ServiceBrowser(zc, MDNS_SERVICE_TYPE, handlers=[on_change])
        done.wait(timeout_s)
    finally:
        zc.close()
    if found:
        log.info("found server via mDNS: %s", found[0])
        return found[0]
    log.info("no server via mDNS within %.1fs, scanning the local network", timeout_s)
    return None


def scan_subnets(port: int = DEFAULT_PORT) -> str | None:
    own = lan_ipv4_addresses()
    subnets: list[ipaddress.IPv4Network] = []
    for ip in own:
        net = ipaddress.ip_network(f"{ip}/24", strict=False)
        if net not in subnets:
            subnets.append(net)
    for net in subnets[:MAX_SUBNETS]:
        hosts = [str(h) for h in net.hosts()]
        log.info("scanning %s on port %d (%d hosts)", net, port, len(hosts))
        url = _scan_hosts(hosts, port)
        if url:
            log.info("found server by scan: %s", url)
            return url
    log.warning("server not found in %s", ", ".join(map(str, subnets)) or "any LAN")
    return None


def _port_open(host: str, port: int, timeout_s: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _scan_hosts(hosts: list[str], port: int) -> str | None:
    with ThreadPoolExecutor(max_workers=64) as pool:
        open_hosts = [h for h, ok in zip(hosts, pool.map(lambda h: _port_open(h, port), hosts)) if ok]
    for host in open_hosts:
        url = f"http://{host}:{port}"
        if is_server(url):
            return url
    return None
