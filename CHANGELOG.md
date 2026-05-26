# Changelog

All notable changes to this project are documented here. The format is loosely based
on [Keep a Changelog](https://keepachangelog.com/), and this project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Work in progress
- **MCP workflow polish.** The MCP server is available and usable, but the Claude
  Code/Desktop setup path, packaged config snippets, and replay-selection UX are still
  being refined.
- **Latest-patch rich parsing.** Current-patch games work through `mgz-fast`; richer
  villager, unit, map, and engagement signals for the newest replay format remain active
  parser work.

## [0.1.0]

### Added
- **Interactive coaching.** `aoe2coach web` opens a browser chat for replay analysis and
  follow-up questions. `CoachChat` keeps multi-turn replay context over the API.
- **Dual parser backend.** Full `mgz` for richer older-replay analysis and `mgz-fast` for
  current-patch compatibility, auto-detected and installed through the `full` / `fast`
  extras.
- **Engagement timeline.** Infers fights from object-count timelines: when they happened,
  losses per player, and who won each trade, plus resource-float metrics.
- **`aoe2coach trends`.** Multi-game habit analysis: average ages, idle-TC frequency,
  Feudal-time trajectory, win rate, civ/map spread, and a recurring-weakness coaching pass.
- **Real ELO benchmarking.** Fetches ladder ratings by `profile_id` from the Relic
  community API so coaching uses your actual bracket. Offline-safe.
- **Minimap render** (`aoe2coach minimap`) from the full backend's terrain grid.
- **Local web front end** (`aoe2coach web`) to browse replays (players, civs, map) and
  generate reports.
- **`aoe2coach update-data`** plus a weekly GitHub Action that refreshes bundled game-data
  tables (object/tech/civ/map names, terrain colors) from `mgz.reference` and
  aoe2techtree.
- **MCP server (WIP).** Tools (`list_replays`, `replay_metrics`, `replay_trends`) and
  prompts (`coach`, `coach_trends`) let Claude Code/Desktop use local replay metrics without
  an aoe2coach API key. The integration is functional, with setup polish still ongoing.
- **Bring-your-own-model.** `anthropic` (default) or any OpenAI-compatible endpoint
  (`AOE2COACH_PROVIDER=openai` → GPT / OpenRouter / local Ollama).
- **Per-game civ context pack.** Injects the in-game civs' tech-tree + bonus notes so
  coaching is civ-aware, while keeping the cached base prompt lean.

### Notes
- Full `mgz` cannot parse DE replays after the Feb-2026 "Last Chieftains" update
  (aoc-mgz #138); use the `fast` backend for current-patch games.
