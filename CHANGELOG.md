# Changelog

All notable changes to this project are documented here. The format is loosely based
on [Keep a Changelog](https://keepachangelog.com/), and this project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Flagship + lightweight model workflow.** aoe2coach can use a lightweight model for
  preliminary habit detection and a flagship model for full replay analysis and detailed
  coaching, so users can review practice focus before the more expensive call.
- **Replay-first web workflow.** The browser UI now previews replay facts before a full
  model call, including map/date, player selection, win/loss, minimap, fundamentals, and a
  readable timeline.
- **Practice focus workflow.** Players can choose the coached player, use a lightweight
  model to detect replay-specific habit candidates, pin useful habits, add custom goals,
  and pass pinned/detected habits into the full coaching report as training priorities.
- **Profile and trend goals.** The roadmap now calls out reusable player profiles,
  multi-game trend habits, and trend-driven coaching analysis as explicit goals.
- **Coached-player selection.** Reports can target a selected player after previewing the
  replay, with lightweight habit detection separated from the full-analysis call so users
  can review practice focus before spending tokens.
- **Resizable web review panes.** The replay browser, practice panel, chat input, replay
  list, minimap, and timeline can be resized for repeated review.
- **Replay metadata and player colors.** Preview data now includes replay date/source,
  team/player colors, clearer result labels, and player-colored names across the UI.
- **Key tech status grounding.** Metrics now include deterministic researched /
  available-but-missed / unavailable status for common upgrades, joined against the local
  civ tech tree before the model sees the replay.
- **Improved minimap rendering.** Minimap output handles missing object names more
  gracefully and uses clearer player markers.
- **Session export.** The web UI can export the current replay preview, practice-focus
  habits, fundamentals, timeline, and chat transcript as Markdown, saving a local copy
  under `reports/session-exports/` while also downloading one in the browser.
- **Sample exported session.** README now links to a committed Markdown session export as
  the public sample report.

### Changed
- **Provider-neutral docs, metadata, and UI.** Public copy now frames configuration and full
  analysis around bring-your-own-provider model settings rather than a single vendor.
- **Grounded coaching prompt.** The system prompt now tells the model to trust
  deterministic tech status, avoid recommending unavailable upgrades, and avoid claiming a
  researched tech was missing.
- **Web comparison table.** The left-panel fundamentals table focuses on direct
  player-to-player comparison metrics such as TC idle, villagers at 16 minutes, age timings,
  and EAPM/actions per minute.
- **Timeline readability.** Timeline events use compact typed rows for age-ups, buildings,
  TC idle gaps, and fights.
- **Full-analysis flow.** Player selection now runs lightweight habit detection first; the
  full report is launched explicitly afterward with pinned and detected habits included in
  the model request.
- **Demo video.** README now embeds the updated uploaded demo video asset.

### Fixed
- **Idle-TC estimation.** Villager-production gaps now account for age-up research time and
  queued villager bursts, reducing false idle-TC reports.
- **Detected habits persistence.** Lightweight detected habits no longer disappear when the
  full report refreshes replay insights.
- **Minimap sizing.** The minimap fits its resizable box without an internal scrollbar.
- **Player color normalization.** Full-parser color labels are normalized before metrics
  reach the web UI, minimap, or model context, with raw color IDs used only as a fallback.
  This fixes off-by-one palette mistakes across replay/parser versions.

### Work in progress
- **MCP workflow polish.** The MCP server is available and usable, but client setup,
  packaged config snippets, and replay-selection UX are still being refined.
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
  prompts (`coach`, `coach_trends`) let MCP-compatible clients use local replay metrics
  without an aoe2coach API key. The integration is functional, with setup polish still
  ongoing.
- **Bring-your-own-model.** `anthropic` (default) or any OpenAI-compatible endpoint
  (`AOE2COACH_PROVIDER=openai` → GPT / OpenRouter / local Ollama).
- **Per-game civ context pack.** Injects the in-game civs' tech-tree + bonus notes so
  coaching is civ-aware, while keeping the cached base prompt lean.

### Notes
- Full `mgz` cannot parse DE replays after the Feb-2026 "Last Chieftains" update
  (aoc-mgz #138); use the `fast` backend for current-patch games.
