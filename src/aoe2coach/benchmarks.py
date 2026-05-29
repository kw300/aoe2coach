"""Benchmark reference data — "what good looks like" at various skill levels.

This is the context that turns a stats dump into *coaching*. The configured model
compares a player's parsed metrics against these tiers to say things like "your
11:26 Feudal on a closed map is roughly intermediate — here's how to shave two
minutes off it."

The numbers are approximate community guidance (Dark→Feudal click times etc.),
intentionally given as ranges. They are stable across requests, so this whole
string is sent as a cached system block (see :mod:`aoe2coach.coach`).

Sources of truth for the real game evolve patch to patch; treat these as
ballpark anchors, not gospel. They're easy to tune in one place.
"""

from __future__ import annotations

BENCHMARKS_MARKDOWN = """\
# AoE2 DE coaching benchmarks (approximate, 1v1)

Age-up times below are *research click* times (when the player started the
age-up), measured from game start at normal (1.0) speed equivalents. Closed maps
(Arena, Black Forest, Hideout) are naturally slower than open maps (Arabia).

## Open maps (e.g. Arabia) — Feudal Age click time
| Tier          | Feudal     | Notes |
|---------------|------------|-------|
| Beginner      | 13:00+     | Often idle TC time and floating resources |
| Intermediate  | 10:00–13:00| Decent vill production, some idle time |
| Advanced      | 8:30–10:00 | Tight 22–23 pop scout/archer openings |
| Expert        | < 8:30     | Pro-level drush/fast-feudal pressure |

## Closed maps (e.g. Arena) — Feudal Age click time
Players boom longer behind walls, so Feudal is later by design.
| Tier          | Feudal     | Castle      | Notes |
|---------------|------------|-------------|-------|
| Beginner      | 12:00+     | 18:00+      | |
| Intermediate  | 9:30–12:00 | 14:00–18:00 | |
| Advanced      | 8:00–9:30  | 12:00–14:00 | Fast Castle into knights/crossbow or monks |
| Expert        | < 8:00     | < 12:00     | |

## Villager production & idle Town Center (the highest-impact habit)
This data is available on the **full** backend (`villagers_queued`, `idle_tc_gaps`,
`estimated_idle_tc_s`). A Town Center produces a villager roughly every **25s**.
- A healthy boom shows **near-continuous** production — gaps under ~40s.
- Any gap well over 40s in the first ~16 minutes is idle TC time: villagers, and
  therefore economy, you simply never got. `estimated_idle_tc_s` sums this waste.
- Rough villager-count anchors by the time Castle Age is reached on a closed map:
  beginner ~45–60, intermediate ~60–80, advanced ~80–100+. Fewer villagers than
  your opponent at the same age is usually the root cause of losing the macro game.
- EAPM (`eapm`) is effective actions/min: ~30 is casual, ~60 solid, 100+ is high.
  It's a soft signal — low can mean idle/slow, very high isn't automatically better.

## Resource float & engagements (full backend)
- **Resource float** (`peak_resources`, `high_float_s`): banked resources you aren't
  spending are wasted economy. Sustained banks above ~1500 — especially in Castle/
  Imperial — mean missing production buildings or under-using your economy. Spend it.
- **Engagements** (`battles`): the timeline of object losses. Winning is *not* losing
  the fewest units overall — it's winning the decisive trades while out-producing.
  Find the engagement that swung the game and learn what enabled it (army size, comp,
  upgrades, or a tech/eco lead from before the fight).

## Tempo heuristics (apply on any map)
- Dark Age should be ~loom + age-up with NO idle Town Center time. Continuous
  villager production until ~Castle Age is the single highest-impact habit.
- Feudal→Castle in a Fast Castle build is typically ~4:00–5:00 of uptime.
- A large gap between two players' Feudal times (>90s) usually decides map control.
- "Command actions per minute" here counts only issued commands (build/research/
  move/etc.), NOT true APM. Low values can mean idle time; very high values can
  mean spam, not necessarily good control. Use it as a soft signal only.

## Coaching priorities, in order of impact for most sub-expert players
1. Eliminate idle Town Center time (constant villager production).
2. Don't float resources — spend toward your plan.
3. Age up with a clear purpose (units/eco) already queued.
4. Wall/scout appropriately for the map.
5. Production buildings before, not after, you bank resources.
"""
