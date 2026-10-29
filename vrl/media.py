"""ffmpeg/ffprobe helpers: probing, frame extraction, audio extraction, cut detection."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaError(RuntimeError):
    pass


@dataclass
class VideoInfo:
    duration: float
    width: int | None
    height: int | None
    has_audio: bool


@dataclass
class Frame:
    frame_number: int  # 1-based, matches the file name
    timestamp: float  # seconds from start
    path: Path


def check_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise MediaError(f"{tool} not found on PATH. Install ffmpeg (e.g. `brew install ffmpeg` or `apt install ffmpeg`).")


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise MediaError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{tail}")
    return proc


def probe(video: Path) -> VideoInfo:
    proc = _run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(video),
    ])
    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if vstream is None:
        raise MediaError(f"No video stream in {video}")
    duration = float(data.get("format", {}).get("duration") or vstream.get("duration") or 0)
    return VideoInfo(
        duration=duration,
        width=vstream.get("width"),
        height=vstream.get("height"),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def extract_frames(video: Path, out_dir: Path, fps: float, max_edge: int = 1280, quality: int = 4) -> list[Frame]:
    """Extract frames at `fps` as JPEGs, scaled so the long edge is at most `max_edge`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame_*.jpg"):
        old.unlink()
    scale = (
        f"scale='if(gte(iw,ih),min({max_edge},iw),-2)':'if(gte(iw,ih),-2,min({max_edge},ih))'"
    )
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
        "-vf", f"fps={fps},{scale}", "-q:v", str(quality),
        str(out_dir / "frame_%05d.jpg"),
    ])
    frames = []
    for path in sorted(out_dir.glob("frame_*.jpg")):
        n = int(path.stem.split("_")[1])
        # The fps filter emits its first frame at t=0, then one every 1/fps seconds.
        frames.append(Frame(frame_number=n, timestamp=round((n - 1) / fps, 3), path=path))
    if not frames:
        raise MediaError(f"ffmpeg produced no frames for {video}")
    return frames


def extract_audio(video: Path, out_path: Path) -> Path:
    """Extract 16 kHz mono WAV (what Whisper expects)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out_path),
    ])
    return out_path


_PTS_RE = re.compile(r"pts_time:([0-9.]+)")


def detect_cuts(video: Path, threshold: float = 0.3) -> list[float]:
    """Timestamps (s) of hard cuts using ffmpeg's scene-change score.

    Soft transitions (morphs, slow masks, zooms) often score below the threshold,
    so treat this as a lower bound on the edit rate.
    """
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(video),
            "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise MediaError(f"Scene detection failed for {video}: {proc.stderr[-500:]}")
    return [round(float(m.group(1)), 2) for line in proc.stderr.splitlines()
            if "showinfo" in line and (m := _PTS_RE.search(line))]


def sample_evenly(frames: list[Frame], max_count: int, always_first_seconds: float = 3.0) -> list[Frame]:
    """Pick at most `max_count` frames: every frame in the hook window, then an even spread."""
    if len(frames) <= max_count:
        return frames
    hook = [f for f in frames if f.timestamp < always_first_seconds][:max_count]
    rest = [f for f in frames if f.timestamp >= always_first_seconds]
    slots = max_count - len(hook)
    if slots <= 0 or not rest:
        return hook
    if slots == 1:
        picked = [rest[-1]]
    else:
        step = (len(rest) - 1) / (slots - 1)
        picked = [rest[round(i * step)] for i in range(slots)]
    return hook + picked
