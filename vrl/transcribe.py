"""Transcription backends: local faster-whisper, OpenAI Whisper API, or none."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Transcript:
    full_text: str = ""
    segments: list[dict] = field(default_factory=list)  # [{"start": s, "end": s, "text": str}]
    backend: str = "none"


_local_model = None


def _transcribe_local(audio: Path, model_name: str, language: str | None) -> Transcript:
    global _local_model
    from faster_whisper import WhisperModel  # imported lazily: heavy dependency

    if _local_model is None:
        log.info("Loading faster-whisper model %r (first run downloads it)", model_name)
        _local_model = WhisperModel(model_name, device="auto", compute_type="auto")
    # vad_filter skips music-only stretches, which otherwise make Whisper hallucinate lyrics/captions.
    segments, _info = _local_model.transcribe(str(audio), language=language, vad_filter=True)
    segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]
    return Transcript(full_text=" ".join(s["text"] for s in segs).strip(), segments=segs, backend=f"local:{model_name}")


def _transcribe_openai(audio: Path, language: str | None) -> Transcript:
    from openai import OpenAI

    client = OpenAI()
    with audio.open("rb") as fh:
        kwargs = {"model": "whisper-1", "file": fh, "response_format": "verbose_json"}
        if language:
            kwargs["language"] = language
        result = client.audio.transcriptions.create(**kwargs)
    segs = [
        {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
        for s in (result.segments or [])
    ]
    return Transcript(full_text=(result.text or "").strip(), segments=segs, backend="openai:whisper-1")


def transcribe(audio: Path | None, backend: str, model_name: str = "small", language: str | None = None) -> Transcript:
    if audio is None or backend == "none":
        return Transcript(backend="none" if backend == "none" else f"{backend}:no-audio")
    if backend == "local":
        return _transcribe_local(audio, model_name, language)
    if backend == "openai":
        return _transcribe_openai(audio, language)
    raise ValueError(f"Unknown TRANSCRIBE_BACKEND {backend!r} (expected local, openai or none)")
