"""WSGI entry point for gunicorn — see deploy/hannah-webui.service.

main.py (Flask's own dev server) stays the local-development entry point;
production runs `gunicorn wsgi:app` instead, so the app object here is built
once at import time, the same way main.py builds it before calling app.run().

Config path comes from HANNAH_WEBUI_CONFIG (default: config.yaml, relative
to the process's working directory) since gunicorn's `module:app` import
convention leaves no room for a --config CLI argument.
"""
import os

from hannah_webui.app import create_app
from hannah_webui.config import load as load_config
from hannah_webui.grpc_client import HannahClient

cfg = load_config(os.environ.get("HANNAH_WEBUI_CONFIG", "config.yaml"))

hannah = HannahClient(cfg.grpc.host, cfg.grpc.port)
hannah.connect()

app = create_app(hannah)
