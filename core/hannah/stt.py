"""
STT-Modul für Hannah — unterstützt mehrere Backends mit Fallback.

Backends (Priorität):
  aws    — AWS Transcribe Streaming      (Cloud, amazon-transcribe SDK)
  azure  — Azure Cognitive Services STT  (schnell, Cloud, 5h/Monat kostenlos)
  remote — faster-whisper-server         (lokal, OpenAI-kompatibel)
  local  — faster-whisper direkt         (immer verfügbar, langsamer)

config.yaml Beispiel:
  stt:
    language: "de"
    no_speech_threshold: 0.6

    # AWS Transcribe (primär, wenn gesetzt) — pip install amazon-transcribe
    aws_key_id: "AKIA..."
    aws_secret_key: "..."
    aws_region: eu-west-1

    # Azure STT
    azure_key: "..."
    azure_region: westeurope

    # Remote STT (sekundär)
    remote_url: "http://psrvai01.gessinger.local:8000"
    remote_model: "Systran/faster-whisper-large-v3"
    remote_timeout: 30.0

    # Lokal (Fallback)
    model: "base"
    device: "cpu"
    compute_type: "int8"
"""

import asyncio
import io
import logging
import wave

import numpy as np
import requests

log = logging.getLogger(__name__)


def _to_wav(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
    pcm = (audio * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class _LocalSTT:
    def __init__(self, cfg: dict):
        from faster_whisper import WhisperModel

        model_size = cfg.get("model", "base")
        device = cfg.get("device", "cpu")
        compute_type = cfg.get("compute_type", "int8")
        log.info(f"Lade Whisper-Modell '{model_size}' ({device}, {compute_type}) ...")
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self._language = cfg.get("language", "de")
        self._no_speech_threshold = cfg.get("no_speech_threshold", 0.6)
        log.info("Whisper bereit.")

    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        segments, _ = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        parts = []
        max_no_speech = 0.0
        for seg in segments:
            max_no_speech = max(max_no_speech, seg.no_speech_prob)
            if seg.no_speech_prob < self._no_speech_threshold:
                parts.append(seg.text.strip())
        text = " ".join(parts).strip()
        log.debug(f"STT (lokal): '{text}' (no_speech={max_no_speech:.2f})")
        return text, max_no_speech


class _AzureSTT:
    """Azure Cognitive Services STT (REST-API, kein SDK nötig)."""

    def __init__(self, cfg: dict):
        self._key      = cfg["azure_key"]
        self._region   = cfg["azure_region"]
        self._language = cfg.get("language", "de-DE")
        if "-" not in self._language:
            self._language = self._language + "-" + self._language.upper()
        self._url = (
            f"https://{self._region}.stt.speech.microsoft.com"
            "/speech/recognition/conversation/cognitiveservices/v1"
        )
        log.info(f"Azure STT konfiguriert: {self._region} ({self._language})")

    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        wav = _to_wav(audio)
        headers = {
            "Ocp-Apim-Subscription-Key": self._key,
            "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
        }
        params = {"language": self._language, "format": "simple"}
        resp = requests.post(self._url, headers=headers, params=params,
                             data=wav, timeout=10)
        resp.raise_for_status()
        data   = resp.json()
        status = data.get("RecognitionStatus", "")
        if status != "Success":
            raise ValueError(f"Azure STT: RecognitionStatus={status}")
        text = data.get("DisplayText", "").strip()
        log.debug(f"STT (azure): '{text}'")
        return text, 0.0


class _RemoteSTT:
    def __init__(self, cfg: dict):
        self._url      = cfg["remote_url"].rstrip("/")
        self._model    = cfg.get("remote_model", "Systran/faster-whisper-large-v3")
        self._language = cfg.get("language", "de")
        self._timeout  = float(cfg.get("remote_timeout", 15.0))
        log.info(f"Remote-STT: {self._url} (Modell: {self._model})")

    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        wav = _to_wav(audio)
        resp = requests.post(
            f"{self._url}/v1/audio/transcriptions",
            files={"file": ("audio.wav", wav, "audio/wav")},
            data={"model": self._model, "language": self._language},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        text = resp.json().get("text", "").strip()
        log.debug(f"STT (remote): '{text}'")
        return text, 0.0


class _AwsTranscribeSTT:
    """
    AWS Transcribe Streaming STT.

    AWS hat keinen einfachen synchronen STT-Endpunkt (Batch läuft über S3 + Polling,
    viel zu langsam für Sprache). Wir nutzen daher die Streaming-API über die async-SDK
    `amazon-transcribe`: Das komplett aufgenommene Audio wird am Stück durchgestreamt und
    das Endergebnis (nur finale, nicht-partielle Segmente) eingesammelt.

    Benötigt:  pip install amazon-transcribe
    IAM-Recht: transcribe:StartStreamTranscription
    """

    def __init__(self, cfg: dict):
        # Lazy import — amazon-transcribe ist optional und nur hier nötig.
        from amazon_transcribe.client import TranscribeStreamingClient  # noqa: F401

        self._region  = cfg.get("aws_region") or cfg.get("polly_region") or "eu-west-1"
        self._key_id  = cfg.get("aws_key_id", "")
        self._secret  = cfg.get("aws_secret_key", "")
        lang = cfg.get("language", "de")
        # Transcribe erwartet BCP-47 ("de-DE"); "de" → "de-DE"
        self._language = lang if "-" in lang else f"{lang}-{lang.upper()}"
        log.info(f"AWS Transcribe STT konfiguriert: {self._region} ({self._language})")

    def _make_client(self):
        from amazon_transcribe.client import TranscribeStreamingClient

        kwargs = {"region": self._region}
        if self._key_id and self._secret:
            # Explizite Credentials aus der Config (sonst: ambiente AWS-Auflösung,
            # z.B. Instance-Profile / Umgebungsvariablen).
            from amazon_transcribe.auth import StaticCredentialResolver
            kwargs["credential_resolver"] = StaticCredentialResolver(self._key_id, self._secret, None)
        return TranscribeStreamingClient(**kwargs)

    async def _stream(self, pcm: bytes) -> str:
        from amazon_transcribe.handlers import TranscriptResultStreamHandler

        client = self._make_client()
        stream = await client.start_stream_transcription(
            language_code=self._language,
            media_sample_rate_hz=16000,
            media_encoding="pcm",
        )

        finals: list[str] = []

        class _Handler(TranscriptResultStreamHandler):
            async def handle_transcript_event(self, transcript_event):
                for result in transcript_event.transcript.results:
                    if not result.is_partial and result.alternatives:
                        finals.append(result.alternatives[0].transcript)

        async def _write():
            chunk = 1024 * 8
            for i in range(0, len(pcm), chunk):
                await stream.input_stream.send_audio_event(audio_chunk=pcm[i:i + chunk])
            await stream.input_stream.end_stream()

        handler = _Handler(stream.output_stream)
        await asyncio.gather(_write(), handler.handle_events())
        return " ".join(finals).strip()

    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        pcm = (audio * 32767).astype(np.int16).tobytes()
        try:
            text = asyncio.run(self._stream(pcm))
        except RuntimeError:
            # Falls dieser Thread bereits einen laufenden Event-Loop hat: eigener Loop.
            loop = asyncio.new_event_loop()
            try:
                text = loop.run_until_complete(self._stream(pcm))
            finally:
                loop.close()
        log.debug(f"STT (aws): '{text}'")
        return text, 0.0


class STT:
    """
    STT mit konfigurierbarer Fallback-Kette: Azure → Remote → Lokal.
    Jede Stufe wird nur versucht wenn sie konfiguriert ist.
    """

    def __init__(self, cfg: dict):
        self._aws:    _AwsTranscribeSTT | None = None
        self._azure:  _AzureSTT  | None = None
        self._remote: _RemoteSTT | None = None

        if cfg.get("aws_transcribe") or (cfg.get("aws_key_id") and cfg.get("aws_secret_key")):
            try:
                self._aws = _AwsTranscribeSTT(cfg)
            except Exception as e:
                log.warning(f"AWS Transcribe nicht verfügbar (amazon-transcribe installiert?): {e}")
        if cfg.get("azure_key") and cfg.get("azure_region"):
            self._azure = _AzureSTT(cfg)
        if cfg.get("remote_url"):
            self._remote = _RemoteSTT(cfg)

        self._local = _LocalSTT(cfg)

        chain = []
        if self._aws:    chain.append("aws")
        if self._azure:  chain.append("azure")
        if self._remote: chain.append("remote")
        chain.append("local")
        log.info(f"STT-Kette: {' → '.join(chain)}")

    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        if self._aws:
            try:
                return self._aws.transcribe(audio)
            except Exception as e:
                log.warning(f"AWS-Transcribe fehlgeschlagen, Fallback auf Azure/Remote/Lokal: {e}")
        if self._azure:
            try:
                return self._azure.transcribe(audio)
            except Exception as e:
                log.warning(f"Azure-STT fehlgeschlagen, Fallback auf Remote/Lokal: {e}")
        if self._remote:
            try:
                return self._remote.transcribe(audio)
            except Exception as e:
                log.warning(f"Remote-STT fehlgeschlagen, Fallback auf lokal: {e}")
        return self._local.transcribe(audio)
