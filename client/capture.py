"""Screen capture with mss and encoding to PNG/JPEG."""

from __future__ import annotations

import io
import logging
from dataclasses import asdict, dataclass

import mss
import mss.tools

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Region:
    """Rectangle in absolute virtual-desktop pixels (same space as mss)."""

    left: int
    top: int
    width: int
    height: int

    def as_mss(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class EncodedImage:
    data: bytes
    content_type: str
    width: int
    height: int


def virtual_screen() -> Region:
    """Bounding box of all monitors together."""
    with mss.mss() as sct:
        m = sct.monitors[0]
    return Region(m["left"], m["top"], m["width"], m["height"])


def grab(monitor: int, region: Region | None, image_format: str, jpeg_quality: int) -> EncodedImage:
    with mss.mss() as sct:
        if region is not None:
            area = region.as_mss()
        else:
            if not 0 <= monitor < len(sct.monitors):
                raise ValueError(f"monitor {monitor} not found (available: 0..{len(sct.monitors) - 1})")
            area = sct.monitors[monitor]
        shot = sct.grab(area)

    width, height = shot.size
    if image_format == "png":
        data = mss.tools.to_png(shot.rgb, shot.size, level=3)
        assert data is not None
        return EncodedImage(data, "image/png", width, height)
    if image_format == "jpeg":
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("image_format = 'jpeg' requires Pillow: pip install pillow") from exc
        buf = io.BytesIO()
        Image.frombytes("RGB", shot.size, shot.rgb).save(buf, "JPEG", quality=jpeg_quality)
        return EncodedImage(buf.getvalue(), "image/jpeg", width, height)
    raise ValueError(f"unknown image_format {image_format!r}")
