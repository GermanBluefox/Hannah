"""Configuration loader for hannah-webui."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class GrpcConfig:
    host: str = "127.0.0.1"
    port: int = 50051


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 5000
    secret_key: str = ""
    grpc: GrpcConfig = field(default_factory=GrpcConfig)


def _load_from_env() -> Config:
    """No config.yaml on disk — read from env vars instead (12-factor style,
    for a future containerized deployment)."""
    return Config(
        host=os.environ.get("HANNAH_WEBUI_HOST", "127.0.0.1"),
        port=int(os.environ.get("HANNAH_WEBUI_PORT", "5000")),
        secret_key=os.environ.get("HANNAH_WEBUI_SECRET_KEY", ""),
        grpc=GrpcConfig(
            host=os.environ.get("HANNAH_WEBUI_GRPC_HOST", "127.0.0.1"),
            port=int(os.environ.get("HANNAH_WEBUI_GRPC_PORT", "50051")),
        ),
    )


def load(path: str | Path = "config.yaml") -> Config:
    config_path = Path(path)
    if not config_path.exists():
        return _load_from_env()

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    def _section(cls, key: str):
        data = raw.get(key, {}) or {}
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in fields})

    return Config(
        host=raw.get("host", "127.0.0.1"),
        port=raw.get("port", 5000),
        secret_key=raw.get("secret_key", ""),
        grpc=_section(GrpcConfig, "grpc"),
    )
