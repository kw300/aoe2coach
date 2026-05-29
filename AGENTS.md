# AGENTS.md — guidance for AI agents working on this repo

This file is for AI coding agents developing **aoe2coach**, not for end users
(see `README.md` for them).

## What this project is

A CLI + library that turns an AoE2 DE `.aoe2record` replay into an AI coaching
report. Pipeline: **parse → metrics → coach → report**.

## Architecture map

| Layer | Module | Responsibility | Touches model? |
|-------|--------|----------------|-----------------|
| 1 | `src/aoe2coach/parse.py` | Decode the binary replay into `ParsedReplay`. The **only** module that touches raw bytes. Dual backend: full `mgz` (rich) or `mgz-fast` (current patch), auto-detected. | No |
| 2 | `src/aoe2coach/metrics.py` | Pure, deterministic coaching features → `ReplayMetrics`. | No |
| 3 | `src/aoe2coach/coach.py` | Send metrics + benchmarks to the model, return advice. | **Yes** |
| 4 | `src/aoe2coach/report.py` | Render markdown. | No |
| — | `cli.py` | `find`/`metrics`/`analyze`/`trends`/`minimap`/`web`/`update-data`. | via coach |
| — | `trends.py` | Multi-game aggregation → `TrendSummary` (habits across games). | No |
| — | `elo.py` | Best-effort real ladder ratings by `profile_id` (Relic API), offline-safe. | No |
| — | `minimap.py` | Render terrain-grid PNG (full backend + Pillow). | No |
| — | `webapp.py` | Flask replay browser (`web` extra). | via coach |
| — | `dataupdate.py` | Regenerate bundled `data/*.json` from `mgz.reference` + aoe2techtree. | No |
| — | `mcp_server.py` | Exposes layers 1–2 as MCP tools (hybrid path). | No |
| — | `config.py` | Env + API-key handling. | — |
| — | `benchmarks.py`, `prompts/*.md` | Cached "what good looks like" context (replay + trends). | — |
| — | `civdata.py`, `replays.py` | Bundled-data name resolution; cross-platform replay discovery. | No |
| — | `data/*.json` | Generated name/terrain tables (committed; refreshed by `update-data`). | No |

## Hard rules

1. **Secrets only from the environment.** Provider keys come from `ANTHROPIC_API_KEY`
   or `OPENAI_API_KEY` via `config.load_config()`. Never hard-code a key, never add
   a default value, never log or print it. `.env` is gitignored; `env.example` is
   the template.
2. **Never commit real replays.** They embed player names + Steam IDs (PII). The
   `.gitignore` blocks `*.aoe2record` except an anonymized fixture under
   `tests/fixtures/`. The pre-commit `gitleaks` hook guards secrets.
3. **Keep deterministic work out of the model.** Numbers (timings, counts, win/loss)
   are computed in `metrics.py`. The model coaches on them; it must not recompute
   them. If you need a new metric, add it to layer 2, not to the prompt.
4. **Don't send raw replays to the model.** Only the compact `ReplayMetrics` dict
   (a few KB) plus the static benchmarks go to the model — this is what keeps it
   cheap and keeps the cache prefix stable.

## Model provider conventions

- Provider defaults to `anthropic` with `claude-opus-4-8` for full analysis and
  `claude-haiku-4-5` for habit detection (configurable via `AOE2COACH_MODEL` and
  `AOE2COACH_DETECT_MODEL`). If no provider is set but `OPENAI_API_KEY` exists, the
  provider is `openai` with `gpt-5.5` for full analysis and `gpt-5.4-mini` for habit
  detection. Custom OpenAI-compatible endpoints (`OPENAI_BASE_URL`) require
  endpoint-specific model ids.
- Native Anthropic requests use **adaptive thinking** (`thinking={"type": "adaptive"}`)
  + `output_config` `effort`. Do **not** use `budget_tokens` (removed on current Opus
  models).
- `AOE2COACH_EFFORT` is provider-aware: Anthropic accepts `low|medium|high|xhigh|max`
  and defaults to `high`; hosted OpenAI accepts `none|low|medium|high|xhigh` and defaults
  to `high`. Custom `OPENAI_BASE_URL` endpoints do not receive
  `reasoning_effort` because support varies.
- **Prompt caching:** on the Anthropic path, system prompt + `benchmarks.py` are the
  stable cached prefix (cache breakpoint on the last system block); the per-replay
  JSON goes in the user turn, after the breakpoint. Don't interpolate volatile data
  (timestamps, the metrics) into the system blocks or you'll bust the cache.

## The two parser backends — important

`mgz` (happyleavesaoc, full) and `mgz-fast` (AoEInsights fork) **both install as the
`mgz` Python module** — they cannot coexist. They're `[full]` and `[fast]` extras in
`pyproject.toml`; base install pulls neither. `parse._detect_backend()` checks for
`mgz.model` (full) and falls back to `mgz.fast`.

- **full** (`mgz`): rich — named build orders, villager production, age uptimes,
  EAPM, real winner, map terrain, located objects. **Cannot parse DE patches after
  the Feb-2026 "Last Chieftains" update** (save_version ≥ 67 — see aoc-mgz #138, the
  `\x60\x0a` offset shift in the player struct). Works up to ~v66.x.
- **fast** (`mgz-fast`): reads the **current** patch (what full mgz can't), but
  lower-level — we derive a subset from the raw command stream; rich fields stay empty.

Picking: analyzing recent/own games → `[fast]`; richest analysis of ≤v66 (pro/test
games) → `[full]`. `_parse_full` and `_parse_fast` both return the same `ParsedReplay`
(rich fields default-empty), so `metrics.py` works with either.

### Full backend API (`mgz.model.parse_match(handle)` → `Match`)
- `match.players[]`: `name`, `civilization`, `civilization_id`, `color_id`,
  `team_id`, `profile_id`, **`winner`** (bool), **`eapm`** (int), `objects[]`
  (`Object(name, position, class_id)`).
- `match.uptimes[]`: `Uptime(timestamp: timedelta, player, age: Age enum)` — age-ups.
- `match.inputs[]`: `Input(type: str, param: str, payload: dict, player, timestamp)`.
  Types incl. `"Build"` (payload `building`/`building_id`), `"Queue"`/`"De Queue"`
  (payload `unit`/`unit_id`/`amount`; villager `unit_id == 83`), `"Research"`
  (payload `technology`). `param` is the human-readable name.
- `match.map`: `name`, `size`, `dimension`, `tiles[]` (`Tile(terrain, elevation, position)`).
- `match.duration` (timedelta), `diplomacy_type`, `rated`, `population`, `chat[]`.

### Fast backend API (`mgz.fast`)
- `mgz.fast.header.parse(handle)` → dict with `de.players` (`number`, `name` bytes,
  `civilization_id`, `profile_id`, `color_id`, `team_id`), `de.rms_map_id`,
  `de.rated`, `de.speed`, `de.population_limit`, `de.build`.
- `mgz.fast.meta(handle)` then loop `mgz.fast.operation(handle)` → `(Operation, payload)`.
  `Operation.SYNC` payload `[0]` = time increment ms (accumulate). `Operation.ACTION`
  payload `(Action, dict)`. Age-ups: `Action.RESEARCH` tech_id ∈ {101,102,103};
  builds `Action.BUILD`; resign `Action.RESIGN`. The body scan degrades gracefully on
  unknown opcodes (returns partial data) — keep it that way.

## Commands

```bash
pip install -e ".[full,dev,mcp]"            # full backend + dev + mcp (or swap full→fast)
pytest                                      # synthetic unit tests + 1 download-on-demand integration test
ruff check . && ruff format .               # lint + format
pre-commit install                          # enable gitleaks + ruff hooks
aoe2coach metrics <compatible.aoe2record>   # smoke-test parse+metrics (no key needed)
```

Note: with `[full]` installed, `aoe2coach metrics latest` on a *current-patch* replay
errors by design (full mgz can't read it) — that's expected; use a ≤v66 replay or `[fast]`.

## Gotchas

- `civdata.CIVILIZATIONS` follows the community DE civ ordering and can lag new
  DLCs by a patch; unknown IDs degrade to `"Civ <id>"`. Update the table when civs
  are added.
- Test fixtures are binary. Keep exactly one small anonymized replay in
  `tests/fixtures/`; don't add more (size + PII).
- `Version.DE` is what `game_version` stringifies to — that's expected.
