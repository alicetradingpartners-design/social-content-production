# Viral Reference Learning System – Handoff for Claude

**Project Manager:** Grok  
**Product Owner:** Robby  
**Status:** Phase 1 – Learning storehouse foundation  
**Date:** 2026-10-29

## Goal
Build a system that takes uploaded Instagram/reference videos, deconstructs them (frames, transcript, structure, visuals, SFX opportunities, flow), stores structured “pattern cards,” and later uses that knowledge base to generate viral content briefs (compatible with Higgsfield and similar tools).

## Current phase scope (what Claude should build first)
1. Supabase project with the schema in `schema.sql`
2. A local or simple script (Python preferred) that:
   - Takes a folder of MP4s
   - Extracts frames with ffmpeg (1 fps or configurable)
   - Transcribes with Whisper (local) or an API
   - Calls an LLM (Claude / GPT / Gemini) with the extraction prompt in `extraction_prompt.md`
   - Writes the resulting pattern card + metadata into Supabase
3. Basic storage of frames (local folder or Supabase Storage / R2)
4. Simple query path: either a minimal Next.js page that lists pattern cards, or clear API endpoints / SQL views that a Grok Bot can call

## Architecture (target)
- **Ingest:** Manual upload → folder or Cloudflare R2 bucket
- **Process:** Railway worker (later); local script first
- **Store:** Supabase (Postgres + pgvector) for pattern cards + embeddings
- **Query:** Dashboard + Grok Bot conversational access
- **Generation:** Pattern cards → structured briefs for Higgsfield / other video tools

## Files provided
- `schema.sql` – run in Supabase (re-runnable; the Phase 1 additions at the bottom are `add column if not exists`)
- `extraction_prompt.md` – system prompt for structured extraction (versioned via the `prompt_version` comment on line 1)
- `process_videos.py` – the processing script (CLI)
- `vrl/` – script modules: `media.py` (ffmpeg), `transcribe.py` (Whisper), `extract.py` (Claude), `store.py` (Supabase)
- `requirements.txt`, `.env.example`
- This README

## Running the processing script

### What it does, per video
1. **Probe** duration/resolution with ffprobe.
2. **Frames:** extracts JPEGs at `FRAME_FPS` (default 1 fps), long edge capped at 1280px, into `output/<video>/frames/`.
3. **Cuts:** measures hard-cut timestamps with ffmpeg scene detection, so pacing notes are grounded in real numbers (soft transitions like morphs/masks may not register; treat it as a lower bound).
4. **Transcript:** local faster-whisper (default, with voice-activity filtering so music-only videos don't produce hallucinated text), the OpenAI Whisper API, or none. Videos without an audio track skip this step.
5. **Pattern card:** sends metadata, cut timings, transcript and up to `MAX_LLM_FRAMES` frames (every frame in the first 3s + an even spread) to Claude with `extraction_prompt.md`, using structured JSON output. Besides the original fields the card includes `motion_style`, auto-suggested `categories` and `tags`, and 3–8 `reference_stills` (frame number, `why_selected`, `visual_description`).
6. **Store:** writes `videos`, `frames` (reference stills flagged with `is_reference_still` + `why_selected`), `transcripts` and `pattern_cards` (including `model` and `prompt_version`), and saves the whole result to `output/<video>/pattern_card.json`.

A video that fails is marked `status = 'failed'` with `error_message` and the run continues with the next one. Re-running skips videos already `completed` (matched on filename + source) unless you pass `--force`, which replaces their frames, transcript and card.

### Setup
1. **Install ffmpeg** (includes ffprobe): `brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Debian/Ubuntu).
2. **Python 3.10+ environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Supabase:** open the SQL editor and run `schema.sql`. If you want frames in Supabase Storage (`FRAME_STORAGE=supabase`), also create a bucket named `frames` (Storage → New bucket).
4. **Config:** `cp .env.example .env` and fill in `ANTHROPIC_API_KEY`, `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (Settings → API). The service-role key bypasses RLS, so keep it server-side only.

### Run
```bash
# Try it without touching Supabase: frames + pattern_card.json go to ./output
python process_videos.py ./videos --dry-run --limit 2

# Real run: everything in ./videos (searched recursively for .mp4/.mov/.m4v)
python process_videos.py ./videos

# A single file, denser frames, no transcription
python process_videos.py ./videos/clip.mp4 --fps 2 --transcribe none

# Reprocess videos that already have cards (e.g. after editing the prompt)
python process_videos.py ./videos --force
```
Other flags: `--source` (sets `videos.source`, e.g. `r2`), `--model`, `--effort` (`low`…`max`), `--output-dir`, `-v`. Every flag has an `.env` equivalent; see `.env.example`.

The first local-Whisper run downloads the model (`small` is ~480 MB). On a machine without a GPU, `WHISPER_MODEL=base` is faster; `TRANSCRIBE_BACKEND=openai` avoids the local model entirely.

### Notes
- **Model:** defaults to `claude-opus-5-5` at `high` effort. Requests opt into server-side refusal fallback (`fallbacks: "default"`), so a false-positive safety decline is retried on a fallback model rather than failing; `pattern_cards.model` records the model that actually produced each card.
- **Prompt versioning:** `prompt_version` is the label in `extraction_prompt.md` plus a hash of the file (e.g. `v2+1a2b3c4d`), so any edit to the prompt shows up in the data. Bump the label for intentional revisions.
- **Cost:** each video is one Claude request carrying up to 40 images, so expect roughly 50–70K input tokens per video at the default settings. Lower `MAX_LLM_FRAMES` or `FRAME_MAX_EDGE` to cut cost.
- **Frame paths:** with `FRAME_STORAGE=local`, `frames.storage_path` is a path relative to this repo (`output/...`); with `supabase` it is `frames/<video_id>/frame_00001.jpg` in Storage.
- **Query examples:**
  ```sql
  select v.filename, c.hook_type, c.categories, c.tags, c.viral_hypothesis
  from pattern_cards c join videos v on v.id = c.video_id
  where 'kinetic-typography' = any(c.categories);

  select v.filename, f.timestamp_seconds, f.why_selected, f.storage_path
  from frames f join videos v on v.id = f.video_id
  where f.is_reference_still order by v.filename, f.frame_number;
  ```

## Immediate next steps for Claude
1. Create a new GitHub repo (or use existing) and push these files.
2. Stand up Supabase project and run `schema.sql`.
3. Write the first processing script (Python + ffmpeg + Whisper + LLM call + Supabase insert).
4. Test on 2–3 sample MP4s.
5. Report back with: schema applied, sample pattern card JSON, and any blockers.

## Storage recommendation
- Short-term manual: Google Drive is acceptable for testing.
- Production: Cloudflare R2 (preferred) or Supabase Storage. Avoid relying on Drive for automated triggers.

## Query interface (agreed)
- Simple browsable list of pattern cards (search + filter)
- Grok Bot that can query the knowledge base for pattern discovery and brief generation

## Out of scope for Phase 1
- Full Railway deployment
- Automatic R2 event triggers
- Embedding generation + vector search (can be added once cards exist)
- Higgsfield API integration

## Success criteria for Phase 1
- 5+ pattern cards successfully written to Supabase from real videos
- Extraction quality is useful for remaking content and learning structure
- Clear path to query the data

---
**PM note:** Once the first cards are in Supabase, we will stand up the Grok Bot query layer and plan the Railway worker migration.
