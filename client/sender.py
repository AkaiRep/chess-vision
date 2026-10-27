"""HTTP calls to the server: pairing and screenshot upload."""

from __future__ import annotations

from typing import Any

import requests

from client.capture import EncodedImage
from shared.protocol import ANALYZE_PATH, PAIR_PATH, TOKEN_HEADER


class SendError(Exception):
    pass


class ServerUnreachable(SendError):
    pass


class NotPaired(SendError):
    pass


def _detail(resp: requests.Response) -> str:
    try:
        return str(resp.json().get("detail", resp.text))
    except ValueError:
        return resp.text


def _post(url: str, timeout_s: float, **kwargs: Any) -> requests.Response:
    try:
        return requests.post(url, timeout=timeout_s, **kwargs)
    except requests.ConnectionError as exc:
        raise ServerUnreachable(f"server unreachable at {url}") from exc
    except requests.Timeout as exc:
        raise ServerUnreachable(f"timeout after {timeout_s}s ({url})") from exc


def pair(server_url: str, name: str, timeout_s: float = 5.0) -> str:
    """Ask the server for its secret (only works shortly after the server started)."""
    resp = _post(server_url.rstrip("/") + PAIR_PATH, timeout_s, json={"name": name})
    if resp.status_code != 200:
        raise SendError(f"pairing failed: {_detail(resp)}")
    return str(resp.json()["token"])


def send_image(server_url: str, token: str, image: EncodedImage, timeout_s: float) -> dict[str, Any]:
    resp = _post(
        server_url.rstrip("/") + ANALYZE_PATH,
        timeout_s,
        data=image.data,
        headers={TOKEN_HEADER: token, "Content-Type": image.content_type},
    )
    if resp.status_code == 401:
        raise NotPaired(_detail(resp))
    if resp.status_code != 200:
        raise SendError(f"HTTP {resp.status_code}: {_detail(resp)}")
    return resp.json()
