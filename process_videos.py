#!/usr/bin/env python3
"""Phase 1 processing script: MP4 folder -> frames, transcript, pattern card -> Supabase.

Usage:
    python process_videos.py ./videos                # process every MP4 in ./videos
    python process_videos.py ./videos --dry-run      # no Supabase; write JSON to ./output only
    python process_videos.py ./videos --force        # reprocess videos already marked completed
    python process_videos.py clip.mp4 --fps 2        # single file, denser frames

See README.md for setup and configuration.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from vrl import media
from vrl.extract import extract_pattern_card, load_prompt
from vrl.transcribe import transcribe

log = logging.getLogger("process_videos")

ROOT = Path(__file__).resolve().parent
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path, help="Folder of videos (searched recursively) or a single video file")
    p.add_argument("--fps", type=float, default=float(env("FRAME_FPS", "1")), help="Frame extraction rate (default 1, env FRAME_FPS)")
    p.add_argument("--source", default=env("VIDEO_SOURCE", "manual_upload"), help="videos.source value (default manual_upload)")
    p.add_argument("--model", default=env("EXTRACTION_MODEL", "claude-opus-5-5"), help="Claude model id")
    p.add_argument("--effort", default=env("EXTRACTION_EFFORT", "high"), choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--transcribe", default=env("TRANSCRIBE_BACKEND", "local"), choices=["local", "openai", "none"])
    p.add_argument("--output-dir", type=Path, default=Path(env("OUTPUT_DIR", str(ROOT / "output"))), help="Where frames and JSON are written")
    p.add_argument("--limit", type=int, help="Process at most N videos")
    p.add_argument("--force", action="store_true", help="Reprocess videos already marked completed")
    p.add_argument("--dry-run", action="store_true", help="Skip Supabase; only write local JSON + frames")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def find_videos(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        sys.exit(f"Input not found: {path}")
    return sorted(p for p in path.rglob("*") if p.suffix.lower() in VIDEO_EXTENSIONS and not p.name.startswith("."))


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpcore", "hpack", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    media.check_ffmpeg()
    if args.transcribe == "openai" and not env("OPENAI_API_KEY"):
        sys.exit("TRANSCRIBE_BACKEND=openai needs OPENAI_API_KEY")

    prompt = load_prompt(ROOT / "extraction_prompt.md")
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY or an `ant auth login` profile

    store = None
    if not args.dry_run:
        url, key = env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            sys.exit("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env (or use --dry-run)")
        from vrl.store import Store

        backend = env("FRAME_STORAGE", "local")
        if backend not in ("local", "supabase"):
            sys.exit("FRAME_STORAGE must be local or supabase")
        store = Store(url, key, frames_bucket=env("SUPABASE_FRAMES_BUCKET", "frames") if backend == "supabase" else None)

    videos = find_videos(args.input)
    if args.limit:
        videos = videos[: args.limit]
    if not videos:
        log.warning("No videos found in %s", args.input)
        return 0

    log.info("Processing %d video(s) | model=%s effort=%s fps=%s transcribe=%s prompt=%s%s",
             len(videos), args.model, args.effort, args.fps, args.transcribe, prompt.version,
             " | DRY RUN" if args.dry_run else "")

    settings = {
        "fps": args.fps,
        "max_llm_frames": int(env("MAX_LLM_FRAMES", "40")),
        "frame_max_edge": int(env("FRAME_MAX_EDGE", "1280")),
        "cut_threshold": float(env("SCENE_CUT_THRESHOLD", "0.3")),
        "whisper_model": env("WHISPER_MODEL", "small"),
        "whisper_language": env("WHISPER_LANGUAGE"),
    }

    ok = skipped = failed = 0
    for i, video in enumerate(videos, 1):
        log.info("[%d/%d] %s", i, len(videos), video.name)
        try:
            status = process_one(video, args, settings, prompt, client, store)
        except KeyboardInterrupt:
            raise
        except Exception:  # keep going; the failure is recorded on the video row
            log.exception("  failed: %s", video.name)
            failed += 1
            continue
        if status == "skipped":
            skipped += 1
        else:
            ok += 1

    log.info("Done: %d processed, %d skipped, %d failed", ok, skipped, failed)
    return 1 if failed else 0


def process_one(video: Path, args, settings: dict, prompt, client, store) -> str:
    started = time.monotonic()
    info = media.probe(video)

    video_id = None
    if store:
        existing = store.find_video(video.name, args.source)
        if existing and existing.get("status") == "completed" and not args.force:
            log.info("  already completed (video_id=%s); use --force to reprocess", existing["id"])
            return "skipped"
        video_id = store.start_video(video.name, args.source, str(video.resolve()), info, existing)

    try:
        work_dir = args.output_dir / video.stem
        frames = media.extract_frames(video, work_dir / "frames", settings["fps"], max_edge=settings["frame_max_edge"])
        cuts = media.detect_cuts(video, settings["cut_threshold"])
        log.info("  %.1fs %sx%s | %d frames | %d hard cuts | audio=%s",
                 info.duration, info.width, info.height, len(frames), len(cuts), info.has_audio)

        audio = media.extract_audio(video, work_dir / "audio.wav") if info.has_audio and args.transcribe != "none" else None
        transcript = transcribe(audio, args.transcribe, settings["whisper_model"], settings["whisper_language"])
        if audio:
            audio.unlink(missing_ok=True)
        log.info("  transcript: %d segments, %d chars (%s)", len(transcript.segments), len(transcript.full_text), transcript.backend)

        llm_frames = media.sample_evenly(frames, settings["max_llm_frames"])
        result = extract_pattern_card(
            client, prompt,
            model=args.model, effort=args.effort,
            filename=video.name, info=info, fps=settings["fps"], cuts=cuts,
            transcript=transcript, frames=llm_frames, total_frames=len(frames),
        )
        card = result.card
        log.info("  card: hook=%r | %d beats | %d stills | categories=%s | model=%s | tokens in/out=%s/%s",
                 card.hook_type, len(card.structure_beats), len(card.reference_stills), card.categories,
                 result.model, result.usage.get("input_tokens"), result.usage.get("output_tokens"))

        stills_by_frame = {s.frame_number: s for s in card.reference_stills}
        output = {
            "video": {
                "id": video_id, "filename": video.name, "source": args.source,
                "duration_seconds": info.duration, "width": info.width, "height": info.height,
                "scene_cuts": cuts,
            },
            "pattern_card": card.model_dump(),
            "reference_still_files": {
                n: str(next(f.path for f in frames if f.frame_number == n)) for n in stills_by_frame
            },
            "transcript": {"full_text": transcript.full_text, "segments": transcript.segments, "backend": transcript.backend},
            "model": result.model,
            "prompt_version": prompt.version,
            "usage": result.usage,
        }
        (work_dir / "pattern_card.json").write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

        if store:
            if store.frames_bucket:
                storage_paths = store.upload_frames(video_id, frames)
            else:
                from vrl.store import local_relpath
                storage_paths = {f.frame_number: local_relpath(f.path, ROOT) for f in frames}
            store.write_transcript(video_id, transcript)
            store.write_frames(video_id, frames, storage_paths, result)
            store.write_pattern_card(video_id, result, prompt.version)
            store.mark_completed(video_id, cuts)

        log.info("  done in %.0fs -> %s", time.monotonic() - started, work_dir / "pattern_card.json")
        return "processed"
    except (Exception, KeyboardInterrupt) as e:
        if store and video_id:
            try:
                store.mark_failed(video_id, f"{type(e).__name__}: {e}")
            except Exception:
                log.exception("  could not record failure on video row")
        raise


if __name__ == "__main__":
    sys.exit(main())
