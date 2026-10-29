-- Viral Reference Learning Storehouse
-- Supabase schema for video deconstruction pattern cards
-- Run this in the Supabase SQL editor (or via migration)

-- Enable pgvector
create extension if not exists vector;

-- Videos table
create table if not exists public.videos (
  id uuid primary key default gen_random_uuid(),
  filename text not null,
  original_url text,
  source text default 'manual_upload', -- manual_upload, ig_saved, etc.
  duration_seconds numeric,
  uploaded_at timestamptz default now(),
  storage_path text, -- R2 / Supabase Storage path
  status text default 'pending', -- pending, processing, completed, failed
  created_at timestamptz default now()
);

-- Frames table
create table if not exists public.frames (
  id uuid primary key default gen_random_uuid(),
  video_id uuid references public.videos(id) on delete cascade,
  frame_number int,
  timestamp_seconds numeric,
  storage_path text,
  visual_description text, -- optional LLM vision note
  created_at timestamptz default now()
);

-- Transcripts table
create table if not exists public.transcripts (
  id uuid primary key default gen_random_uuid(),
  video_id uuid references public.videos(id) on delete cascade unique,
  full_text text,
  segments jsonb, -- timestamped segments if available
  created_at timestamptz default now()
);

-- Pattern cards (the learning unit)
create table if not exists public.pattern_cards (
  id uuid primary key default gen_random_uuid(),
  video_id uuid references public.videos(id) on delete cascade unique,
  hook_type text,
  hook_text text,
  first_3_seconds_notes text,
  structure_beats jsonb, -- array of {time, description}
  pacing_notes text,
  visual_motifs text,
  text_overlays_notes text,
  sfx_opportunities text,
  flow_formatting text,
  why_it_works text,
  viral_hypothesis text,
  raw_extraction jsonb, -- full LLM output for debugging
  embedding vector(1536), -- for semantic search (adjust dim if using different model)
  created_at timestamptz default now()
);

-- Indexes
create index if not exists idx_pattern_cards_embedding on public.pattern_cards using ivfflat (embedding vector_cosine_ops) with (lists = 100);
create index if not exists idx_videos_status on public.videos(status);
create index if not exists idx_videos_uploaded_at on public.videos(uploaded_at desc);

-- RLS (enable and add policies as needed for your auth)
-- alter table public.videos enable row level security;
-- alter table public.pattern_cards enable row level security;
-- (Add policies later based on who should read/write)

comment on table public.pattern_cards is 'Structured learnings extracted from reference videos for viral content production';

-- ---------------------------------------------------------------------------
-- Phase 1 additions (processing script). Safe to re-run on an existing DB.
-- ---------------------------------------------------------------------------

-- Videos: processing diagnostics + measured cut timing
alter table public.videos add column if not exists error_message text;
alter table public.videos add column if not exists width int;
alter table public.videos add column if not exists height int;
alter table public.videos add column if not exists scene_cuts jsonb; -- [seconds, ...] hard cuts detected by ffmpeg
alter table public.videos add column if not exists processed_at timestamptz;

-- Frames: reference stills flagged by the LLM
alter table public.frames add column if not exists is_reference_still boolean default false;
alter table public.frames add column if not exists why_selected text;
create index if not exists idx_frames_video_id on public.frames(video_id);
create index if not exists idx_frames_reference on public.frames(video_id) where is_reference_still;

-- Pattern cards: motion-graphics fields, auto tags, provenance
alter table public.pattern_cards add column if not exists motion_style text;
alter table public.pattern_cards add column if not exists tags text[] default '{}';
alter table public.pattern_cards add column if not exists categories text[] default '{}';
alter table public.pattern_cards add column if not exists model text;          -- model that actually produced the card
alter table public.pattern_cards add column if not exists prompt_version text; -- e.g. "v2+1a2b3c4d" (label + prompt file hash)
create index if not exists idx_pattern_cards_tags on public.pattern_cards using gin (tags);
create index if not exists idx_pattern_cards_categories on public.pattern_cards using gin (categories);
