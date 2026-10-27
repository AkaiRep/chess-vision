"""Server entry point. Run from the project root:  python -m server [--config config.toml]"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import uvicorn

from server.app import create_app, make_engine
from shared.config import load_config
from shared.logging_setup import setup_logging
from shared.net import local_ip


def main() -> int:
    parser = argparse.ArgumentParser(description="chess-vision server (macOS)")
    parser.add_argument("--config", type=Path, default=None, help="path to config.toml")
    args = parser.parse_args()

    setup_logging("server")
    log = logging.getLogger("server")
    cfg = load_config(args.config)
    app = create_app(cfg.server, engine=make_engine(cfg.server))
    log.info("listening on http://%s:%d", local_ip(), cfg.server.port)
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_config=None)
    return 0


raise SystemExit(main())
