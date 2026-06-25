from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import torch
from fastapi.testclient import TestClient

from app import create_app, get_embedding


class _FixedClassifier:
    """Always returns a ones-tensor (cosine similarity with itself == 1.0)."""
    def encode_batch(self, _signal):
        return torch.ones(1, 1, 192)


_AUDIO = b"\x00\x01" * 8000  # 16000 bytes of dummy PCM int16


@contextmanager
def _client(tmp_path: Path, classifier=None, **kwargs):
    app = create_app(
        classifier=classifier or _FixedClassifier(),
        disk_path=str(tmp_path / "disk"),
        mem_path=str(tmp_path / "mem"),
        **kwargs,
    )
    with TestClient(app) as client:
        yield client


# ── get_embedding ──────────────────────────────────────────────────────────────

class TestGetEmbedding:
    def test_calls_encode_batch(self):
        clf = MagicMock()
        clf.encode_batch.return_value = torch.ones(1, 1, 192)
        result = get_embedding(clf, _AUDIO)
        assert clf.encode_batch.called
        assert result.shape == (192,)

    def test_squeezes_output(self):
        clf = MagicMock()
        clf.encode_batch.return_value = torch.ones(1, 1, 192)
        result = get_embedding(clf, _AUDIO)
        assert result.dim() == 1


# ── /enroll ────────────────────────────────────────────────────────────────────

class TestEnroll:
    def test_new_profile_returns_ok(self, tmp_path):
        with _client(tmp_path) as client:
            resp = client.post("/enroll", content=_AUDIO, headers={"x-user-id": "1"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_new_profile_written_to_disk(self, tmp_path):
        with _client(tmp_path) as client:
            client.post("/enroll", content=_AUDIO, headers={"x-user-id": "1"})
        assert (tmp_path / "disk" / "1.pt").exists()

    def test_new_profile_written_to_mem(self, tmp_path):
        with _client(tmp_path) as client:
            client.post("/enroll", content=_AUDIO, headers={"x-user-id": "1"})
        assert (tmp_path / "mem" / "1.pt").exists()

    def test_second_enroll_blends_embeddings(self, tmp_path):
        with _client(tmp_path) as client:
            client.post("/enroll", content=_AUDIO, headers={"x-user-id": "1"})
            resp = client.post("/enroll", content=_AUDIO, headers={"x-user-id": "1"})
        assert resp.status_code == 200
        saved = torch.load(str(tmp_path / "disk" / "1.pt"), map_location="cpu")
        # ones * 0.8 + ones * 0.2 == ones  →  all elements == 1.0
        assert torch.allclose(saved, torch.ones_like(saved))

    def test_missing_header_returns_422(self, tmp_path):
        with _client(tmp_path) as client:
            resp = client.post("/enroll", content=_AUDIO)
        assert resp.status_code == 422


# ── /identify ──────────────────────────────────────────────────────────────────

class TestIdentify:
    def test_no_profiles_returns_unknown(self, tmp_path):
        with _client(tmp_path) as client:
            resp = client.post("/identify", content=_AUDIO)
        assert resp.json()["user_id"] == "unknown"

    def test_no_profiles_confidence_zero(self, tmp_path):
        with _client(tmp_path) as client:
            resp = client.post("/identify", content=_AUDIO)
        assert resp.json()["confidence"] == 0.0

    def test_identifies_enrolled_user(self, tmp_path):
        with _client(tmp_path) as client:
            client.post("/enroll", content=_AUDIO, headers={"x-user-id": "1"})
            resp = client.post("/identify", content=_AUDIO)
        assert resp.json()["user_id"] == "1"

    def test_confidence_close_to_one_for_same_embedding(self, tmp_path):
        with _client(tmp_path) as client:
            client.post("/enroll", content=_AUDIO, headers={"x-user-id": "1"})
            resp = client.post("/identify", content=_AUDIO)
        assert resp.json()["confidence"] == pytest.approx(1.0, abs=1e-4)

    def test_below_unknown_threshold_returns_unknown(self, tmp_path):
        # threshold > 1.0 → impossible to match → always "unknown"
        with _client(tmp_path, unknown_threshold=1.1, uncertain_threshold=1.2) as client:
            client.post("/enroll", content=_AUDIO, headers={"x-user-id": "1"})
            resp = client.post("/identify", content=_AUDIO)
        assert resp.json()["user_id"] == "unknown"

    def test_picks_best_of_multiple_profiles(self, tmp_path):
        with _client(tmp_path) as client:
            client.post("/enroll", content=_AUDIO, headers={"x-user-id": "1"})
            # Save a zero-embedding for user "2" directly into the shared dirs
            other_emb = torch.zeros(192)
            torch.save(other_emb, str(tmp_path / "disk" / "2.pt"))
            torch.save(other_emb, str(tmp_path / "mem" / "2.pt"))
            # identify with ones-embedding → user "1" (cos_sim=1) beats user "2" (cos_sim=0)
            resp = client.post("/identify", content=_AUDIO)
        assert resp.json()["user_id"] == "1"


# ── startup profile sync ───────────────────────────────────────────────────────

class TestStartupProfileSync:
    def test_disk_profiles_copied_to_mem_on_startup(self, tmp_path):
        disk = tmp_path / "disk"
        disk.mkdir()
        torch.save(torch.ones(192), disk / "1.pt")

        app = create_app(
            classifier=_FixedClassifier(),
            disk_path=str(disk),
            mem_path=str(tmp_path / "mem"),
        )
        with TestClient(app):
            pass

        assert (tmp_path / "mem" / "1.pt").exists()

    def test_mem_dir_created_if_missing(self, tmp_path):
        assert not (tmp_path / "mem").exists()
        app = create_app(
            classifier=_FixedClassifier(),
            disk_path=str(tmp_path / "disk"),
            mem_path=str(tmp_path / "mem"),
        )
        with TestClient(app):
            pass
        assert (tmp_path / "mem").exists()


# ── config thresholds ──────────────────────────────────────────────────────────

class TestConfigThresholds:
    def test_custom_thresholds_applied(self, tmp_path):
        with _client(tmp_path, unknown_threshold=0.9, uncertain_threshold=0.95) as client:
            client.post("/enroll", content=_AUDIO, headers={"x-user-id": "1"})
            # cos_sim == 1.0 which is >= 0.95 → not uncertain, returns user "1"
            resp = client.post("/identify", content=_AUDIO)
        assert resp.json()["user_id"] == "1"

    def test_config_file_overrides_threshold(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("recognition:\n  unknown_threshold: 1.1\n  uncertain_threshold: 1.2\n")
        app = create_app(
            config_path=str(cfg),
            classifier=_FixedClassifier(),
            disk_path=str(tmp_path / "disk"),
            mem_path=str(tmp_path / "mem"),
        )
        with TestClient(app) as client:
            client.post("/enroll", content=_AUDIO, headers={"x-user-id": "1"})
            resp = client.post("/identify", content=_AUDIO)
        # threshold > 1.0 → unknown even though cos_sim == 1.0
        assert resp.json()["user_id"] == "unknown"
