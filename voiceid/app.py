import argparse
import os
import shutil
from contextlib import asynccontextmanager

import torch
import numpy as np
import yaml
from fastapi import APIRouter, FastAPI, Request, Header
import uvicorn


def _load_config(path: str) -> dict:
    if path and os.path.exists(path):
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def _load_model():
    print("Lade Sprach-Modell (ECAPA-TDNN) auf CPU ...")
    from speechbrain.inference.speaker import EncoderClassifier
    model = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        run_opts={"device": "cpu"},
    )
    torch.set_num_threads(4)
    print("✅ Modell bereit.")
    return model


@asynccontextmanager
async def _lifespan(app: FastAPI):
    cfg    = _load_config(getattr(app.state, "config_path", ""))
    _recog = cfg.get("recognition", {})

    if "unknown_threshold" in _recog:
        app.state.unknown_threshold = float(_recog["unknown_threshold"])
    if "uncertain_threshold" in _recog:
        app.state.uncertain_threshold = float(_recog["uncertain_threshold"])

    disk_path = app.state.disk_path
    mem_path  = app.state.mem_path
    os.makedirs(disk_path, exist_ok=True)
    os.makedirs(mem_path,  exist_ok=True)

    if app.state.classifier is None:
        app.state.classifier = _load_model()

    loaded = 0
    for file in os.listdir(disk_path):
        if file.endswith(".pt"):
            shutil.copy2(os.path.join(disk_path, file), os.path.join(mem_path, file))
            loaded += 1
    print(f"✅ {loaded} Stimmprofil(e) in RAM-Disk geladen ({mem_path}).")

    yield


router = APIRouter()


def get_embedding(classifier, audio_bytes: bytes) -> torch.Tensor:
    signal = torch.from_numpy(np.frombuffer(audio_bytes, dtype=np.int16).copy()).float()
    return classifier.encode_batch(signal).squeeze()


@router.post("/enroll")
async def enroll(request: Request, x_roomie_id: str = Header(...)):
    audio_data  = await request.body()
    classifier  = request.app.state.classifier
    disk_path   = request.app.state.disk_path
    mem_path    = request.app.state.mem_path

    print(f"Enrollment-Probe empfangen für: {x_roomie_id}")
    new_emb   = get_embedding(classifier, audio_data)
    filename  = f"{x_roomie_id}.pt"
    disk_file = os.path.join(disk_path, filename)
    ram_file  = os.path.join(mem_path,  filename)

    if os.path.exists(disk_file):
        old_emb      = torch.load(disk_file, map_location="cpu").squeeze()
        combined_emb = (old_emb * 0.8) + (new_emb * 0.2)
        print(f"Update: Bestehendes Profil für {x_roomie_id} verfeinert.")
    else:
        combined_emb = new_emb
        print(f"Neu: Erstes Profil für {x_roomie_id} erstellt.")

    torch.save(combined_emb, disk_file)
    torch.save(combined_emb, ram_file)
    return {"ok": True, "message": f"Profil für {x_roomie_id} gespeichert."}


@router.post("/identify")
async def identify(request: Request):
    audio_data  = await request.body()
    classifier  = request.app.state.classifier
    mem_path    = request.app.state.mem_path
    unknown_threshold   = request.app.state.unknown_threshold
    uncertain_threshold = request.app.state.uncertain_threshold

    current_emb = get_embedding(classifier, audio_data)
    best_match  = "unknown"
    max_score   = 0.0

    for file in os.listdir(mem_path):
        if file.endswith(".pt"):
            stored_emb = torch.load(os.path.join(mem_path, file), map_location="cpu").squeeze()
            score = torch.nn.functional.cosine_similarity(current_emb, stored_emb, dim=0).item()
            if score > max_score:
                max_score  = score
                best_match = file.replace(".pt", "")

    if max_score < unknown_threshold:
        best_match = "unknown"
    elif max_score < uncertain_threshold:
        print(f"⚠️  Unsichere Erkennung: {best_match} ({max_score:.4f})")

    print(f"Ergebnis: {best_match} (Score: {max_score:.4f})")
    return {"roomie_id": best_match, "confidence": max_score}


def create_app(
    *,
    config_path: str = "",
    classifier=None,
    disk_path: str | None = None,
    mem_path: str | None = None,
    unknown_threshold: float = 0.25,
    uncertain_threshold: float = 0.40,
) -> FastAPI:
    """Factory — pass classifier=<mock> in tests to skip model loading."""
    _app = FastAPI(lifespan=_lifespan)
    _app.state.config_path          = config_path
    _app.state.classifier           = classifier
    _app.state.disk_path            = disk_path or os.environ.get(
        "VOICEID_DISK_PATH", os.path.expanduser("~/hannah/voice_profiles")
    )
    _app.state.mem_path             = mem_path or os.environ.get(
        "VOICEID_MEM_PATH", "/mnt/hannah_mem"
    )
    _app.state.unknown_threshold    = unknown_threshold
    _app.state.uncertain_threshold  = uncertain_threshold
    _app.include_router(router)
    return _app


app = create_app(config_path=os.environ.get("VOICEID_CONFIG", ""))


if __name__ == "__main__":
    _parser = argparse.ArgumentParser(description="Hannah Voice-ID Service")
    _parser.add_argument("--config", default="", help="Pfad zur config.yaml")
    _args = _parser.parse_args()

    _cfg    = _load_config(_args.config)
    _server = _cfg.get("server", {})
    _host   = _server.get("host", "0.0.0.0")
    _port   = int(_server.get("port", 8080))

    _app = create_app(config_path=_args.config)
    uvicorn.run(_app, host=_host, port=_port)
