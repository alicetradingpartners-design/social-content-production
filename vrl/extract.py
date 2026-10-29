"""Pattern-card extraction with Claude (structured JSON output)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field, ValidationError

from .media import Frame, VideoInfo
from .transcribe import Transcript

log = logging.getLogger(__name__)

MIN_STILLS, MAX_STILLS = 3, 8


class StructureBeat(BaseModel):
    time: str
    description: str


class ReferenceStill(BaseModel):
    frame_number: int
    why_selected: str
    visual_description: str


class PatternCard(BaseModel):
    hook_type: str
    hook_text: str
    first_3_seconds_notes: str
    structure_beats: list[StructureBeat]
    pacing_notes: str
    motion_style: str
    visual_motifs: str
    text_overlays_notes: str
    sfx_opportunities: str
    flow_formatting: str
    why_it_works: str
    viral_hypothesis: str
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    reference_stills: list[ReferenceStill] = Field(default_factory=list)


def _strict(schema: dict) -> dict:
    """Make every object in a JSON schema strict (all properties required, no extras)."""
    if schema.get("type") == "object":
        props = schema.get("properties", {})
        schema["required"] = list(props)
        schema["additionalProperties"] = False
        for p in props.values():
            _strict(p)
    elif schema.get("type") == "array":
        _strict(schema["items"])
    return schema


_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": _STR}
OUTPUT_SCHEMA = _strict({
    "type": "object",
    "properties": {
        "hook_type": _STR,
        "hook_text": _STR,
        "first_3_seconds_notes": _STR,
        "structure_beats": {
            "type": "array",
            "items": {"type": "object", "properties": {"time": _STR, "description": _STR}},
        },
        "pacing_notes": _STR,
        "motion_style": _STR,
        "visual_motifs": _STR,
        "text_overlays_notes": _STR,
        "sfx_opportunities": _STR,
        "flow_formatting": _STR,
        "why_it_works": _STR,
        "viral_hypothesis": _STR,
        "categories": _STR_LIST,
        "tags": _STR_LIST,
        "reference_stills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "frame_number": {"type": "integer"},
                    "why_selected": _STR,
                    "visual_description": _STR,
                },
            },
        },
    },
})


@dataclass
class ExtractionPrompt:
    text: str
    version: str  # "<label>+<sha8>" so edits to the file are always traceable


def load_prompt(path: Path) -> ExtractionPrompt:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"<!--\s*prompt_version:\s*(\S+)\s*-->", text)
    label = m.group(1) if m else "unversioned"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return ExtractionPrompt(text=text, version=f"{label}+{digest}")


@dataclass
class ExtractionResult:
    card: PatternCard
    raw: dict
    model: str  # model that actually served the request (differs from requested on fallback)
    usage: dict


class ExtractionError(RuntimeError):
    pass


def _fmt_time(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def _build_content(filename: str, info: VideoInfo, fps: float, cuts: list[float],
                   transcript: Transcript, frames: list[Frame], total_frames: int) -> list[dict]:
    if cuts:
        shots = len(cuts) + 1
        cut_summary = (
            f"{len(cuts)} hard cuts detected ({shots / info.duration:.2f} shots/sec, "
            f"avg shot {info.duration / shots:.2f}s). Cut times (s): {', '.join(str(c) for c in cuts)}"
            if info.duration else f"{len(cuts)} hard cuts detected: {cuts}"
        )
    else:
        cut_summary = "No hard cuts detected (continuous shot or only soft transitions)."

    if transcript.segments:
        transcript_text = "\n".join(
            f"[{_fmt_time(s['start'])}-{_fmt_time(s['end'])}] {s['text']}" for s in transcript.segments
        )
    elif transcript.full_text:
        transcript_text = transcript.full_text
    else:
        transcript_text = "(no speech detected - likely music/SFX only)"

    header = (
        f"## Metadata\n"
        f"- filename: {filename}\n"
        f"- duration: {info.duration:.2f}s\n"
        f"- resolution: {info.width}x{info.height}\n"
        f"- frames: extracted at {fps} fps ({total_frames} total); {len(frames)} shown below\n\n"
        f"## Measured cuts\n{cut_summary}\n\n"
        f"## Transcript\n{transcript_text}\n\n"
        f"## Frames"
    )
    content: list[dict] = [{"type": "text", "text": header}]
    for f in frames:
        content.append({"type": "text", "text": f"Frame {f.frame_number} @ t={f.timestamp:.1f}s"})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.standard_b64encode(f.path.read_bytes()).decode("ascii"),
            },
        })
    content.append({"type": "text", "text": "Analyze the video materials above and return the JSON pattern card."})
    return content


def extract_pattern_card(
    client: anthropic.Anthropic,
    prompt: ExtractionPrompt,
    *,
    model: str,
    effort: str,
    filename: str,
    info: VideoInfo,
    fps: float,
    cuts: list[float],
    transcript: Transcript,
    frames: list[Frame],
    total_frames: int,
) -> ExtractionResult:
    content = _build_content(filename, info, fps, cuts, transcript, frames, total_frames)

    # Streaming avoids HTTP timeouts on long, image-heavy requests.
    # fallbacks="default": if a safety classifier declines (false positives happen),
    # the API retries on Anthropic's recommended fallback model inside the same call.
    with client.beta.messages.stream(
        model=model,
        max_tokens=32000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={
            "effort": effort,
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
        },
        system=prompt.text,
        messages=[{"role": "user", "content": content}],
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        raise ExtractionError(f"Model declined the request: {details}")
    if message.stop_reason == "max_tokens":
        raise ExtractionError("Response hit max_tokens before the JSON was complete")

    text = next((b.text for b in message.content if b.type == "text"), None)
    if not text:
        raise ExtractionError(f"No text block in response (stop_reason={message.stop_reason})")
    try:
        raw = json.loads(text)
        card = PatternCard.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as e:
        raise ExtractionError(f"Invalid pattern card JSON: {e}") from e

    card.reference_stills = _clean_stills(card.reference_stills, {f.frame_number for f in frames})
    card.tags = _normalize_labels(card.tags)
    card.categories = _normalize_labels(card.categories)

    usage = message.usage.model_dump() if message.usage else {}
    return ExtractionResult(card=card, raw=raw, model=message.model, usage=usage)


def _clean_stills(stills: list[ReferenceStill], valid_frames: set[int]) -> list[ReferenceStill]:
    seen: set[int] = set()
    kept = []
    for s in stills:
        if s.frame_number not in valid_frames:
            log.warning("Dropping reference still for unknown frame %s", s.frame_number)
            continue
        if s.frame_number in seen:
            continue
        seen.add(s.frame_number)
        kept.append(s)
    if len(kept) < MIN_STILLS:
        log.warning("Only %d valid reference stills (expected %d-%d)", len(kept), MIN_STILLS, MAX_STILLS)
    return kept[:MAX_STILLS]


def _normalize_labels(labels: list[str]) -> list[str]:
    out: list[str] = []
    for label in labels:
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
        if slug and slug not in out:
            out.append(slug)
    return out
