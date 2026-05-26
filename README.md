# aoe2coach

[![CI](https://github.com/kw300/aoe2coach/actions/workflows/ci.yml/badge.svg)](https://github.com/kw300/aoe2coach/actions/workflows/ci.yml)

**Age of Empires II is brutally hard to get better at.** A loss often leaves only a vague
sense that something went wrong, while re-watching the replay takes 20 minutes.

**aoe2coach lets players talk to their replays.** Drop in a game, ask what went wrong, and
it coaches from the actual replay context: openings, age-up timings, idle Town Center time,
army choices, upgrades, and the fights that swung the game.

The replay stays in the conversation. Follow-ups can dig into units, battles, economy,
market use, civ bonuses, or recurring habits across recent games without starting over.

**Best results currently come from replays recorded before the February 2026 AoE2 DE
patch.** The full parser exposes villager queues, EAPM, map data, commands, and richer
object timelines for those games. Newer ladder games still run through a lightweight parser
while the rich parser catches up to the updated replay format.

## Demo: Hera vs Sora Kuma

This sample analyzes a Khmer vs Malay Arabia game between
[**Hera**](https://liquipedia.net/ageofempires/Hera) and
[**Sora Kuma**](https://liquipedia.net/ageofempires/Sora_Kuma), two of the strongest AoE2
players in the world. Watch the game, then read the aoe2coach follow-up conversation on the
same replay.

<p>
  <a href="https://www.youtube.com/watch?v=T3ZhmVcX3Vw"><img alt="Play the Hera vs Sora Kuma match VOD on YouTube" src="docs/assets/youtube-card.jpg" width="640"></a>
</p>

<video src="https://github.com/user-attachments/assets/d2434791-f988-42c7-98ce-fce22073eb13" width="640" controls></video>

[Read the sample aoe2coach chat on this game.](reports/example.md)

---

## Getting Started

### 1. Install

```bash
git clone https://github.com/kw300/aoe2coach
cd aoe2coach
python -m venv .venv && source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[full,web]"       # rich parser for older replays
```

For current-patch replays, install `.[fast,web]` instead.

### 2. Configure

```bash
cp env.example .env                # add an Anthropic API key to .env (gitignored)
```

Get an Anthropic key at [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys).
The CLI and browser UI both read configuration from the environment or local `.env`; the
web app never asks for or stores API keys.

### 3. Run

```bash
aoe2coach web                      # opens a browser
```

Then drag in a replay, or pick one from the left pane, and chat with the coach.

Prefer the terminal? The CLI does the same, scriptably:

```bash
aoe2coach find                  # locate replay files
aoe2coach analyze latest        # save a report
aoe2coach trends --last 10      # recurring habits
aoe2coach metrics latest        # stats JSON
aoe2coach minimap latest        # map PNG
```

Bring an API key — a single report is **~$0.05–0.15** on Claude Opus 4.7 (a few cents),
less on Sonnet/Haiku. Saved reports land in `reports/` ([see a sample](reports/example.md)).

## What It Provides

**1. A coaching report with a point of view:**
```
Jian Hei reached Feudal a minute faster — then stalled. A 232-second idle Town Center
right after Feudal cost ~8 villagers, and it never recovered: 71 villagers to 112, no
Imperial, and a Janissary mass that couldn't out-scale Bombards. Top priority: never
idle the TC. You already have the speed; add the villagers.
```

**2. Habit tracking across games** — *"Feudal-Age upgrades are missing in 7 of the last
10 games, and 1,500+ wood is floating by Castle in most games. Fixing those two issues
would clean up the Feudal timing problem."*

**3. Interactive coaching** — `aoe2coach web` opens a browser chat: pick a replay, get the
report, then ask follow-ups ("why was the fight at 25 minutes so expensive?", "what keeps
going wrong?") in a real conversation. (Also available keyless inside Claude via MCP — see
[Other ways to run it](#other-ways-to-run-it).)

## How it works

The core idea: **do the exact, boring stuff in code; let the model do the judgment.**

```
replay file  →  parse  →  compute the stats  →  model coaches on them  →  report
 (.aoe2record)  (mgz)     (villager timings,     (a few KB of JSON,
                           idle TC, build order,   compact metrics)
                           who won each fight)
```

Timings, villager counts, and who lost which fight are computed deterministically in
Python. The model coaches from a few KB of structured stats plus a "what good looks like"
reference, which keeps the report fast, cheap, and grounded in the replay.

### Replay Data Used

- **Age-up timings** (Feudal / Castle / Imperial) and the gaps between them
- **Villager production → idle Town Center detection** — the #1 macro leak ⚡
- **Build order** — every building, named and timestamped
- **Army composition & unique-unit usage**, and **named techs/upgrades researched** ⚡
- **Resource float** — banked resources sitting unspent ⚡
- **Engagement timeline** — when fights happened, losses per side, who won the trade ⚡
- **EAPM** ⚡, **win/loss, civ, map**, and each player's **real ladder ELO** (by profile ID)

⚡ = needs the rich parser (older replays; see [below](#which-replays-work)). Current-patch
games still give ages, build order, civs, and result.

### Bring a Model

The model only sees that small JSON, so any capable model works. Set the provider in `.env`:

| Provider | Set | Notes |
|---|---|---|
| **Anthropic** (default) | `ANTHROPIC_API_KEY` | Best on **Claude Opus 4.7** — prompt caching + adaptive thinking |
| **OpenAI-compatible** | `AOE2COACH_PROVIDER=openai` + `OPENAI_API_KEY` (± `OPENAI_BASE_URL`) | GPT, or **OpenRouter** → any model (Claude/Gemini/…), or a **local** model (Ollama/LM Studio) |

For OpenAI-compatible providers, copy `env.example` to `.env` and set the provider
variables there.

Prefer no API key at all? Run it from Claude via MCP — see [Other ways to run it](#other-ways-to-run-it).

## Which replays work

The replay format changes every patch, and the rich parser
([`mgz`](https://github.com/happyleavesaoc/aoc-mgz)) currently covers the format used
before the February 2026 **Last Chieftains** update:

- **Pre-February-2026 replays → the full treatment** (villager production, idle-TC, EAPM,
  engagement timeline, minimap). Install `.[full]`.
- **February-2026-and-newer replays → lightweight parsing** via
  [`mgz-fast`](https://github.com/AoEInsights/aoc-mgz) — build order, age timings, result,
  fewer deep stats. Install `.[fast]`. *(Why the lag:
  [aoc-mgz #138](https://github.com/happyleavesaoc/aoc-mgz/issues/138).)*

**Want compatible replays to try?** The [`aoc-mgz` replay corpus](https://github.com/happyleavesaoc/aoc-mgz/tree/master/tests/recs)
has older pre-February-2026 AoE2/AoC replay files (`.mgz` / `.aoe2record`), including the
GL.Hera games used for the demos.

## Under the hood

The interesting engineering (documented in [`CLAUDE.md`](CLAUDE.md)):

- **Reverse-engineering an undocumented binary format** that changes every patch, with a
  **dual-backend** design that auto-picks the rich parser or the current-patch one.
- **Battle detection from a coarse signal** — aoe2coach infers engagements from object-count
  drops and keeps that label visible, which helps the coach treat fight data as a strong
  clue rather than a tactical replay.
- **Deterministic metrics, prompt caching, provider-agnostic model support, and BYO-key
  handling** with standard repo hygiene: secrets from env, gitleaks pre-commit, and real
  replays kept out of git.
- A weekly GitHub Action keeps the bundled game-data (unit/civ/tech names) current.

## Other ways to run it

**MCP (no API key) — chat with replays in Claude.** aoe2coach ships a working MCP server
for Claude Code / Desktop (`tools`: `list_replays`, `replay_metrics`, `replay_trends`;
`prompts`: `coach`, `coach_trends`). This path is still being polished, especially setup
packaging and replay-selection UX. Full setup: **[docs/mcp.md](docs/mcp.md)**.

## Roadmap

- **Player personalization and weak-point targeting** — build player profiles from recent
  games, then aim reports at the few recurring habits most likely to move that player up.
- **Trend analysis upgrades** — make `trends --last 10` sharper by grouping mistakes by
  map, civ, matchup, game phase, and loss pattern.
- **Latest-patch rich parsing** — close the current AoE2 patch gap by extracting more data
  from `mgz-fast` and routing old/new replays through the right parser automatically.
- **MCP-first Claude workflow** — polish the Claude Code/Desktop path so players can coach
  from their Claude subscription, with packaged config snippets and clearer replay UX.
- **Model choice and cost profiles** — add documented presets for Opus/Sonnet,
  OpenAI-compatible endpoints, and local models, plus clearer cache/cost reporting.
- **Coaching evaluation harness** — maintain a small anonymized replay corpus with expected
  metric snapshots and golden coaching checks, so parser changes and prompt edits can be
  regression-tested.
- **Coach behavior and game-knowledge tuning** — keep refining the system prompt for
  coaching style, patch-aware AoE2 knowledge, civ/unit nuance, and better follow-up answers.
- **Smarter engagement analysis** — combine object losses with command positions, unit
  costs, and selected-object IDs to estimate where fights happened and what they were worth.
- **Build-order and ELO benchmarks** — compare openings, timings, and civ/map performance
  against matchup-aware templates and public rating-bracket data.

## Limitations

- The rich parser currently covers replays from before the February 2026 AoE2 patch; newer
  ladder games use the lighter parser.
- Engagement analysis is intentionally coarse today. Rich parsing provides build/research/unit
  inputs, map data, starting objects, command positions, and object/resource time series.
  aoe2coach uses drops in those timelines to mark costly fights and the side that bled more
  value. Exact composition, positioning, kill attribution, and pathing-level battle
  reconstruction belong to a future simulation-grade analysis path.

## Credits

Built on [**mgz**](https://github.com/happyleavesaoc/aoc-mgz) and the
[**AoEInsights `mgz-fast`** fork](https://github.com/AoEInsights/aoc-mgz) (replay parsing),
the [**SiegeEngineers aoe2techtree**](https://github.com/SiegeEngineers/aoe2techtree)
dataset (game-data names), and [Claude](https://www.anthropic.com/claude) for the coaching.

## License

MIT — see [LICENSE](LICENSE).
