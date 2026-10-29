# Approved Production Stack – Sound & Motion

**Status:** Approved by product owner (2026-10-29)  
**Purpose:** Reference for any agent (Claude Code, GPT Astra, Grok Bot, etc.) that needs to turn pattern cards into executable video or sound.

## Sound FX
- **Primary:** Freesound API (Python client available). Use `sfx_opportunities` from pattern cards to search and pull previews/downloads.
- **Alternatives:** ZapSplat, Soundly, Lots of Sounds (CC0 + API/MCP friendly).

## Motion Graphics / Programmatic Video
- **Primary recommendation:** Remotion (React/TypeScript) or Revideo (MIT, TypeScript). Official/agent skills exist for Claude Code.
- **Strong alternatives:**
  - HyperFrames (HTML + GSAP, Apache 2.0) – agent-friendly, no React required
  - Motion Canvas (TypeScript, MIT) – excellent for kinetic typography and structured beats
  - Manim (Python) – for precise/diagram-style motion
  - MoviePy (Python) – lightweight composition on top of ffmpeg

## Generation Agent Guidance
Pattern cards + curated reference stills are the source of truth.  
Any model (Claude, GPT Astra, etc.) should:
1. Read the relevant pattern card fields (visual motifs, pacing, text overlays, structure beats, sfx_opportunities).
2. Select or reference the flagged stills.
3. Output code (Remotion / Revideo / HyperFrames) or a structured brief that a renderer can execute.
4. Optionally query Freesound for matching SFX.

## Execution Preference
- **Primary path:** Claude Code + Remotion/Revideo for production-quality, versionable motion graphics.
- **Secondary / exploration path:** GPT Astra + Higgsfield MCP for faster viral-style variations.
- Skills and libraries documented here can be ported to either mind.

## Next Integration Points (after Phase 1 cards exist)
- Freesound lookup from `sfx_opportunities`
- Generation prompt template that consumes a pattern card + reference stills
- Optional Higgsfield or Seedance handoff for non-code paths
