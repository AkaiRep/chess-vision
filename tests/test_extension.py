"""Browser extension: board parsing tests (Node) and manifest sanity."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from shared.protocol import DEFAULT_PORT, POSITION_PATH, SERVICE_ID, TOKEN_HEADER

EXT = Path(__file__).parent.parent / "extension"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_board_parser() -> None:
    assert NODE is not None
    proc = subprocess.run(
        [NODE, "--test", str(EXT / "tests" / "board.test.js")], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_manifest_files_exist() -> None:
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    files = [manifest["background"]["service_worker"], manifest["action"]["default_popup"]]
    files += [f for cs in manifest["content_scripts"] for f in cs["js"]]
    for name in files:
        assert (EXT / name).exists(), name


def test_extension_matches_protocol() -> None:
    net = (EXT / "net.js").read_text(encoding="utf-8")
    for value in (f'"{POSITION_PATH}"', f'"{TOKEN_HEADER}"', f'"{SERVICE_ID}"', f"DEFAULT_PORT = {DEFAULT_PORT};"):
        assert value in net, value
