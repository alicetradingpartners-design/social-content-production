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
