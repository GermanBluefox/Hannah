"""hannah-webui – entry point.

Flask app for the standalone Hannah WebUI service. Talks to Hannah Core
exclusively via gRPC (no direct DB/file access, see #27).

Usage:
  python main.py [--config path/to/config.yaml]
"""
from __future__ import annotations

import argparse
import logging
import sys

from hannah_webui.app import create_app
from hannah_webui.config import load as load_config
from hannah_webui.grpc_client import HannahClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("hannah_webui")


def main(config_path: str) -> None:
    cfg = load_config(config_path)

    hannah = HannahClient(cfg.grpc.host, cfg.grpc.port)
    hannah.connect()

    app = create_app(hannah, cfg.secret_key)

    log.info("hannah-webui starting on %s:%d (gRPC=%s:%d)", cfg.host, cfg.port, cfg.grpc.host, cfg.grpc.port)
    try:
        app.run(host=cfg.host, port=cfg.port)
    finally:
        hannah.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hannah WebUI")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()
    main(args.config)
