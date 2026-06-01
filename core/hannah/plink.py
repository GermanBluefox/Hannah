import math
import struct
import wave
import logging

log = logging.getLogger(__name__)

_SAMPLE_RATE   = 16000
_PLINK_FREQ    = 880    # Hz
_PLINK_SECONDS = 0.2
_FADE_MS       = 20


def get_plink_pcm(wav_path: str = "") -> tuple[bytes, float]:
    """Return (pcm_16kHz_mono_16bit, duration_s) for the plink sound."""
    if wav_path:
        try:
            return _load_wav(wav_path)
        except Exception as exc:
            log.warning("Plink-WAV laden fehlgeschlagen (%s) — nutze generierten Ton", exc)
    pcm = _generate_plink()
    return pcm, _PLINK_SECONDS


def _generate_plink() -> bytes:
    n    = int(_PLINK_SECONDS * _SAMPLE_RATE)
    fade = int(_FADE_MS / 1000 * _SAMPLE_RATE)
    samples: list[int] = []
    for i in range(n):
        v = math.sin(2 * math.pi * _PLINK_FREQ * i / _SAMPLE_RATE)
        if i < fade:
            v *= i / fade
        elif i > n - fade:
            v *= (n - i) / fade
        samples.append(int(v * 16000))
    return struct.pack(f"<{n}h", *samples)


def _load_wav(path: str) -> tuple[bytes, float]:
    with wave.open(path, "rb") as wf:
        if wf.getnchannels() != 1 or wf.getframerate() != _SAMPLE_RATE or wf.getsampwidth() != 2:
            raise ValueError(
                f"Plink-WAV muss 16kHz mono 16-bit sein "
                f"(ist: {wf.getframerate()}Hz, {wf.getnchannels()}ch, {wf.getsampwidth()*8}bit)"
            )
        pcm      = wf.readframes(wf.getnframes())
        duration = wf.getnframes() / wf.getframerate()
    return pcm, duration
