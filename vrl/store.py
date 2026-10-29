"""Supabase persistence: videos, frames, transcripts, pattern_cards (+ optional Storage upload)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from supabase import Client, create_client

from .extract import ExtractionResult
from .media import Frame, VideoInfo
from .transcribe import Transcript

log = logging.getLogger(__name__)

INSERT_BATCH = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, url: str, key: str, frames_bucket: str | None = None):
        self.db: Client = create_client(url, key)
        self.frames_bucket = frames_bucket  # None = keep frames on local disk only

    # -- videos ---------------------------------------------------------------

    def find_video(self, filename: str, source: str) -> dict | None:
        rows = (
            self.db.table("videos").select("*")
            .eq("filename", filename).eq("source", source)
            .order("created_at", desc=True).limit(1).execute().data
        )
        return rows[0] if rows else None

    def start_video(self, filename: str, source: str, storage_path: str, info: VideoInfo,
                    existing: dict | None) -> str:
        fields = {
            "filename": filename,
            "source": source,
            "storage_path": storage_path,
            "duration_seconds": round(info.duration, 3),
            "width": info.width,
            "height": info.height,
            "status": "processing",
            "error_message": None,
        }
        if existing:
            video_id = existing["id"]
            # Reprocessing: clear previous child rows so the run is a clean replace.
            for table in ("frames", "transcripts", "pattern_cards"):
                self.db.table(table).delete().eq("video_id", video_id).execute()
            self.db.table("videos").update(fields).eq("id", video_id).execute()
            return video_id
        return self.db.table("videos").insert(fields).execute().data[0]["id"]

    def mark_failed(self, video_id: str, error: str) -> None:
        self.db.table("videos").update(
            {"status": "failed", "error_message": error[:2000]}
        ).eq("id", video_id).execute()

    def mark_completed(self, video_id: str, cuts: list[float]) -> None:
        self.db.table("videos").update(
            {"status": "completed", "scene_cuts": cuts, "processed_at": _now(), "error_message": None}
        ).eq("id", video_id).execute()

    # -- children -------------------------------------------------------------

    def upload_frames(self, video_id: str, frames: list[Frame]) -> dict[int, str]:
        """Upload frames to Supabase Storage; returns frame_number -> object path."""
        paths: dict[int, str] = {}
        bucket = self.db.storage.from_(self.frames_bucket)
        for f in frames:
            obj = f"{video_id}/{f.path.name}"
            bucket.upload(obj, f.path.read_bytes(),
                          file_options={"content-type": "image/jpeg", "upsert": "true"})
            paths[f.frame_number] = f"{self.frames_bucket}/{obj}"
        return paths

    def write_frames(self, video_id: str, frames: list[Frame], storage_paths: dict[int, str],
                     result: ExtractionResult) -> None:
        stills = {s.frame_number: s for s in result.card.reference_stills}
        rows = []
        for f in frames:
            still = stills.get(f.frame_number)
            rows.append({
                "video_id": video_id,
                "frame_number": f.frame_number,
                "timestamp_seconds": f.timestamp,
                "storage_path": storage_paths.get(f.frame_number, str(f.path)),
                "is_reference_still": still is not None,
                "why_selected": still.why_selected if still else None,
                "visual_description": still.visual_description if still else None,
            })
        for i in range(0, len(rows), INSERT_BATCH):
            self.db.table("frames").insert(rows[i:i + INSERT_BATCH]).execute()

    def write_transcript(self, video_id: str, transcript: Transcript) -> None:
        self.db.table("transcripts").upsert(
            {"video_id": video_id, "full_text": transcript.full_text, "segments": transcript.segments},
            on_conflict="video_id",
        ).execute()

    def write_pattern_card(self, video_id: str, result: ExtractionResult, prompt_version: str) -> None:
        c = result.card
        self.db.table("pattern_cards").upsert(
            {
                "video_id": video_id,
                "hook_type": c.hook_type,
                "hook_text": c.hook_text,
                "first_3_seconds_notes": c.first_3_seconds_notes,
                "structure_beats": [b.model_dump() for b in c.structure_beats],
                "pacing_notes": c.pacing_notes,
                "motion_style": c.motion_style,
                "visual_motifs": c.visual_motifs,
                "text_overlays_notes": c.text_overlays_notes,
                "sfx_opportunities": c.sfx_opportunities,
                "flow_formatting": c.flow_formatting,
                "why_it_works": c.why_it_works,
                "viral_hypothesis": c.viral_hypothesis,
                "tags": c.tags,
                "categories": c.categories,
                "raw_extraction": result.raw,
                "model": result.model,
                "prompt_version": prompt_version,
            },
            on_conflict="video_id",
        ).execute()


def local_relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())
