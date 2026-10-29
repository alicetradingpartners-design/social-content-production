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
- `schema.sql` – run in Supabase
- `extraction_prompt.md` – use as the system/user prompt for structured extraction
- This README

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
