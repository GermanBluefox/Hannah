"""Configuration loader for hannah-webui."""
from __future__ import annotations

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
    grpc: GrpcConfig = field(default_factory=GrpcConfig)


def load(path: str | Path = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    def _section(cls, key: str):
        data = raw.get(key, {}) or {}
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in fields})

    return Config(
        host=raw.get("host", "127.0.0.1"),
        port=raw.get("port", 5000),
        grpc=_section(GrpcConfig, "grpc"),
    )
