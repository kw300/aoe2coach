"""Layer 2 — derive coaching metrics from a :class:`~aoe2coach.parse.ParsedReplay`.

Pure, deterministic Python: no model calls, no I/O. Turns parsed events into the
signals a coach reasons about and produces a compact, JSON-serializable summary.

When the replay was parsed with the **full** backend, this layer additionally
computes the high-value stuff: villager-production gaps (idle Town Center time),
named build orders, true win/loss, and EAPM. With the **fast** backend those rich
fields are simply absent and we fall back to tempo + resignation inference.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import civdata
from .parse import ParsedReplay, PlayerReplay, _fmt_ms
from .playercolors import color_name as color_name_from_id

# A Town Center pumps a villager about every 25s. A gap materially larger than that
# (before the boom ends) means the TC sat idle — the #1 sub-expert mistake.
_IDLE_GAP_THRESHOLD_S = 40
_IDEAL_VILL_INTERVAL_S = 25
_QUEUE_BURST_MS = 10_000
# Only judge production gaps during the early economy (dark + feudal-ish).
_BOOM_WINDOW_S = 16 * 60

# Battle detection from the object-count timeseries (full backend).
# A drop of this many objects between consecutive samples is a loss event.
_LOSS_DROP_THRESHOLD = 4
# Loss events within this window are one engagement.
_BATTLE_WINDOW_MS = 20_000
# Minimum combined losses for a cluster to count as a "battle".
_BATTLE_MIN_TOTAL = 8
# A player whose losses are <= this fraction of the other's "won the trade".
_TRADE_MARGIN = 0.65
# Banked resources above this are "floating" (economy not being spent).
_FLOAT_THRESHOLD = 1500
_AGE_RESEARCH_NAMES = {"Feudal Age", "Castle Age", "Imperial Age"}
_KEY_TECHS = [
    "Bloodlines",
    "Husbandry",
    "Forging",
    "Iron Casting",
    "Blast Furnace",
    "Scale Barding Armor",
    "Chain Barding Armor",
    "Plate Barding Armor",
    "Light Cavalry",
    "Hussar",
    "Cavalier",
    "Elite Battle Elephant",
]
_CIV_ALIASES = {
    "Maya": "Mayans",
}

_OPEN_MAPS = {
    "arabia",
    "acropolis",
    "gold rush",
    "golden pit",
    "land madness",
    "socotra",
    "valley",
}
_CLOSED_MAPS = {"arena", "hideout", "black forest", "fortress", "hill fort"}
_WATER_MAPS = {"islands", "team islands", "migration", "archipelago"}
_HYBRID_MAPS = {"four lakes", "nomad", "mediterranean", "scandinavia", "baltic"}

_MILITARY_BUILDINGS = {
    "barracks",
    "stable",
    "archery range",
    "siege workshop",
    "monastery",
    "castle",
    "donjon",
}

_CIV_PROFILES = {
    "Britons": "archer tempo and range scaling",
    "Chinese": "flexible economy into tech switches",
    "Franks": "cavalry pressure and strong food economy",
    "Goths": "infantry flood and late-game spam",
    "Huns": "mobile cavalry/CA pressure without houses",
    "Japanese": "infantry/naval flexibility with efficient eco buildings",
    "Maya": "archer economy and long-lasting resources",
    "Mayans": "archer economy and long-lasting resources",
    "Mongols": "hunt-powered tempo into cavalry archers",
    "Persians": "Town Center economy into cavalry or boom",
    "Saracens": "market flexibility and camel/archer switches",
    "Teutons": "slow, durable infantry/knight push",
    "Turks": "gunpowder, gold control, and fast Imperial pressure",
    "Vikings": "strong eco into infantry/archer pressure",
    "Aztecs": "infantry/monk pressure and strong early economy",
    "Bengalis": "elephant/monk scaling and extra villagers on age-up",
    "Berbers": "cheap stable units and mobile Castle Age pressure",
    "Bohemians": "monk/siege/gunpowder control",
    "Bulgarians": "men-at-arms tempo into cavalry/infantry",
    "Burgundians": "early eco upgrades and cavalry timing",
    "Burmese": "infantry/monk pressure with strong attack upgrades",
    "Byzantines": "defensive flexibility and cheap counter units",
    "Celts": "infantry/siege pressure",
    "Cumans": "Feudal boom or cavalry tempo",
    "Dravidians": "infantry/naval pressure with strong wood economy",
    "Ethiopians": "archer/siege pressure",
    "Gurjaras": "camel/counter-unit mobility",
    "Hindustanis": "camel/gunpowder control and strong economy",
    "Incas": "flexible counter units and infantry options",
    "Italians": "archer/naval economy and cheaper age-ups",
    "Khmer": "open tech path, farming efficiency, and elephant/scorpion scaling",
    "Koreans": "defensive archer/siege pressure",
    "Lithuanians": "fast food economy, relics, and cavalry scaling",
    "Magyars": "scout tempo into cavalry archers",
    "Malay": "fast age-ups, infantry/naval pressure, and cheap elephants",
    "Malians": "flexible economy and infantry/cavalry switches",
    "Poles": "farm/gold economy and cavalry pressure",
    "Portuguese": "gold-efficient units and gunpowder/naval options",
    "Romans": "efficient economy into infantry/scorpion pressure",
    "Sicilians": "resilient units, Donjons, and faster Town Centers",
    "Slavs": "farm economy into infantry/siege",
    "Spanish": "Conquistador/gunpowder timing and strong villagers",
    "Tatars": "hill control and cavalry archer scaling",
    "Vietnamese": "durable archers and anti-archer options",
}


@dataclass
class PlayerMetrics:
    name: str
    civilization: str
    color_id: int | None
    color_name: str | None
    team_id: int | None
    profile_id: int | None
    result: str  # "won" | "lost" | "unknown"
    eapm: int | None
    # Age-up times (seconds from start) + derived durations.
    feudal_time_s: int | None
    castle_time_s: int | None
    imperial_time_s: int | None
    dark_age_s: int | None
    feudal_to_castle_s: int | None
    castle_to_imperial_s: int | None
    # Tempo
    command_actions_per_min: float | None
    # Rich (full backend)
    villagers_queued: int
    villagers_16m: int | None
    idle_tc_gaps: list[dict]  # [{"at": "4:10", "gap_s": 62}]
    longest_idle_gap_s: int | None
    estimated_idle_tc_s: int | None
    build_order: list[str]  # ["House@0:03", "Barracks@9:40", ...]
    building_counts: dict[str, int]
    units_trained: dict[str, int]
    techs_researched: int  # count of distinct techs (not click events)
    techs: list[str]  # the actual techs, in research order (e.g. "Bloodlines", "Blast Furnace")
    key_tech_status: list[dict]
    # From the whole-game object/resource timeseries (full backend only)
    peak_objects: int | None
    peak_resources: int | None
    objects_lost_total: int | None
    biggest_loss: dict | None  # {"at": "31:18", "count": 44}
    high_float_s: int | None  # seconds banked resources sat above _FLOAT_THRESHOLD
    # Deterministic coaching features consumed by reports, the web UI, and the model.
    opening: str = "Unclear opening"
    opening_confidence: str = "low"
    build_order_comparison: list[dict] = field(default_factory=list)
    improvement_profile: list[dict] = field(default_factory=list)
    action_plan: list[dict] = field(default_factory=list)

    @property
    def labels(self) -> dict[str, str]:
        return {
            "feudal": _fmt_ms((self.feudal_time_s or 0) * 1000) if self.feudal_time_s else "—",
            "castle": _fmt_ms((self.castle_time_s or 0) * 1000) if self.castle_time_s else "—",
            "imperial": _fmt_ms((self.imperial_time_s or 0) * 1000)
            if self.imperial_time_s
            else "—",
        }


@dataclass
class ReplayMetrics:
    source_file: str
    backend: str
    game_version: str
    build: int | None
    map_name: str
    map_size: str | None
    diplomacy: str | None
    duration_s: int
    rated: bool
    speed: float | None
    population_limit: int | None
    body_complete: bool
    recorded_at: str | None
    recorded_at_source: str | None
    players: list[PlayerMetrics] = field(default_factory=list)
    # Match-level engagement timeline derived from object-count drops (full backend).
    # Each: {"at": "31:18", "losses": {name: n}, "trade_winner": name|None, "total": n}
    battles: list[dict] = field(default_factory=list)
    # Chronological replay events for UI/report rendering. Each event has:
    # {"at": "10:12", "type": "age_up|building|idle_tc|battle", "label": "...", ...}
    timeline: list[dict] = field(default_factory=list)
    matchup_context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration_label"] = _fmt_ms(self.duration_s * 1000)
        return d


def _secs(ms: int | None) -> int | None:
    return None if ms is None else ms // 1000


def _diff(later: int | None, earlier: int | None) -> int | None:
    if later is None or earlier is None:
        return None
    return max(0, later - earlier)


def _blocked_ms(start: int, end: int, blocks: list[tuple[int, int]]) -> int:
    return sum(max(0, min(end, b_end) - max(start, b_start)) for b_start, b_end in blocks)


def _age_research_blocks(player: PlayerReplay) -> list[tuple[int, int]]:
    blocks = []
    for age, reached in player.age_up_ms.items():
        start = player.age_research_ms.get(age)
        if start is not None and reached > start:
            blocks.append((start, reached))
    return blocks


def _queue_batches(queue_ms: list[int]) -> list[tuple[int, int]]:
    grouped: list[tuple[int, int, int]] = []
    for ms in sorted(queue_ms):
        if grouped and ms - grouped[-1][1] <= _QUEUE_BURST_MS:
            start, _last, amount = grouped[-1]
            grouped[-1] = (start, ms, amount + 1)
        else:
            grouped.append((ms, ms, 1))
    return [(start, amount) for start, _last, amount in grouped]


def _villager_gaps(
    queue_ms: list[int], age_research_blocks: list[tuple[int, int]] | None = None
) -> tuple[list[dict], int | None, int | None]:
    """Find idle-TC gaps in villager production during the boom window.

    Returns (gaps, longest_gap_s, estimated_idle_s).
    """
    if not queue_ms:
        return [], None, None
    batches = _queue_batches(queue_ms)
    gaps: list[dict] = []
    estimated_idle_ms = 0
    longest = 0
    for (prev, amount), (cur, _cur_amount) in zip(batches, batches[1:], strict=False):
        if prev > _BOOM_WINDOW_S * 1000:
            break
        expected_next = prev + amount * _IDEAL_VILL_INTERVAL_S * 1000
        if expected_next >= cur:
            continue
        idle_ms = max(
            0,
            cur - expected_next - _blocked_ms(expected_next, cur, age_research_blocks or []),
        )
        if idle_ms > longest:
            longest = idle_ms
        if idle_ms > (_IDLE_GAP_THRESHOLD_S - _IDEAL_VILL_INTERVAL_S) * 1000:
            gaps.append({"at": _fmt_ms(expected_next), "gap_s": idle_ms // 1000})
            estimated_idle_ms += idle_ms
    gaps.sort(key=lambda g: g["gap_s"], reverse=True)
    return gaps[:6], (longest // 1000 if longest else None), (estimated_idle_ms // 1000)


def _result(p: PlayerReplay, all_players: list[PlayerReplay]) -> str:
    if p.winner is True:
        return "won"
    if p.winner is False:
        return "lost"
    # Fast backend fallback: resignation inference.
    humans = [x for x in all_players if x.is_human]
    resigners = {x.number for x in humans if x.resigned_at_ms is not None}
    if p.number in resigners:
        return "lost"
    if resigners and len(humans) == 2:
        return "won"
    return "unknown"


def _build_order_labels(build_order: list[tuple[int, str]], limit: int = 16) -> list[str]:
    return [f"{name}@{_fmt_ms(ms)}" for ms, name in build_order[:limit]]


def _norm(name: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in name).split())


def _first_building_times(build_order: list[tuple[int, str]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for ms, name in sorted(build_order):
        key = _norm(name)
        out.setdefault(key, ms // 1000)
    return out


def _map_style(map_name: str) -> str:
    key = _norm(map_name)
    if key in _OPEN_MAPS:
        return "open"
    if key in _CLOSED_MAPS:
        return "closed"
    if key in _WATER_MAPS:
        return "water"
    if key in _HYBRID_MAPS:
        return "hybrid"
    return "unknown"


def _time_label(seconds: int | None) -> str:
    return _fmt_ms(seconds * 1000) if seconds is not None else "—"


def _opening(_p: PlayerReplay, _building_times: dict[str, int]) -> tuple[str, str]:
    """Do not infer named openings; expose extracted timings instead."""
    return "Unclear opening", "low"


def _target_rows(opening: str, map_style: str) -> list[tuple[str, str, int, str]]:
    """Return (kind, key, target_s, note) rows for build-order comparison."""
    generic_feudal = 12 * 60 if map_style != "closed" else 13 * 60
    return [
        ("age", "feudal", generic_feudal, "A clean Feudal time is the baseline opening check."),
        (
            "building_any",
            "military",
            14 * 60,
            "Openings need some military infrastructure before the game drifts.",
        ),
    ]


def _actual_for_target(
    kind: str, key: str, p: PlayerReplay, building_times: dict[str, int]
) -> int | None:
    if kind == "age":
        return _secs(p.age_up_ms.get(key))
    if kind == "building":
        return building_times.get(key)
    if kind == "building_any":
        vals = [building_times[b] for b in _MILITARY_BUILDINGS if b in building_times]
        return min(vals) if vals else None
    return None


def _build_order_comparison(
    opening: str, map_style: str, p: PlayerReplay, building_times: dict[str, int]
) -> list[dict]:
    rows = []
    for kind, key, target, note in _target_rows(opening, map_style):
        actual = _actual_for_target(kind, key, p, building_times)
        if actual is None:
            status = "missing"
            delta = None
        else:
            delta = actual - target
            if delta <= -45:
                status = "early"
            elif delta <= 45:
                status = "on_time"
            else:
                status = "late"
        rows.append(
            {
                "checkpoint": key.replace("_", " ").title(),
                "actual": _time_label(actual),
                "target": _time_label(target),
                "delta_s": delta,
                "status": status,
                "note": note,
            }
        )
    return rows


def _tech_names(research_names: list[str]) -> list[str]:
    return [name for name in dict.fromkeys(research_names) if name not in _AGE_RESEARCH_NAMES]


def _norm_name(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())


def _civ_techtree(civilization: str) -> dict:
    table = civdata.techtree_table()
    key = civilization if civilization in table else _CIV_ALIASES.get(civilization, civilization)
    if key in table:
        return table[key]
    wanted = _norm_name(civilization)
    for candidate, raw in table.items():
        if _norm_name(candidate) == wanted:
            return raw
    return {}


def _key_tech_status(civilization: str, researched: list[str], *, rich: bool) -> list[dict]:
    if not rich:
        return []
    raw = _civ_techtree(civilization)
    # aoe2techtree stores some researched upgrades by their resulting unit line
    # (e.g. Cavalier, Hussar, Elite Battle Elephant) under Unit rather than Tech.
    available = {civdata.tech_name(t) for t in raw.get("Tech", [])} | {
        civdata.object_name(u) for u in raw.get("Unit", [])
    }
    researched_set = set(researched)
    rows = []
    for tech in _KEY_TECHS:
        if tech in researched_set:
            status = "researched"
        elif tech in available:
            status = "available_not_researched"
        else:
            status = "not_available"
        rows.append({"tech": tech, "status": status})
    return rows


def _timeseries_metrics(ts: list[tuple[int, int, int]]) -> tuple[dict, list[tuple[int, int]]]:
    """Per-player metrics + loss events from (ms, total_objects, total_resources).

    Returns (summary_dict, loss_events) where loss_events is [(ms, objects_lost)].
    A drop in total_objects between samples means units/buildings were lost — almost
    always combat. total_objects mixes units and buildings, so treat as a strong but
    not exact signal.
    """
    if not ts:
        return (
            {
                "peak_objects": None,
                "peak_resources": None,
                "objects_lost_total": None,
                "biggest_loss": None,
                "high_float_s": None,
            },
            [],
        )
    peak_objects = max(o for _, o, _ in ts)
    peak_resources = max(r for _, _, r in ts)
    loss_events: list[tuple[int, int]] = []
    high_float_ms = 0
    for (pms, pobj, pres), (cms, cobj, _cres) in zip(ts, ts[1:], strict=False):
        drop = pobj - cobj
        if drop >= _LOSS_DROP_THRESHOLD:
            loss_events.append((cms, drop))
        if pres > _FLOAT_THRESHOLD:
            high_float_ms += cms - pms
    total_lost = sum(d for _, d in loss_events)
    biggest = max(loss_events, key=lambda e: e[1], default=None)
    summary = {
        "peak_objects": peak_objects,
        "peak_resources": peak_resources,
        "objects_lost_total": total_lost,
        "biggest_loss": ({"at": _fmt_ms(biggest[0]), "count": biggest[1]} if biggest else None),
        "high_float_s": high_float_ms // 1000,
    }
    return summary, loss_events


def _battles(events_by_name: dict[str, list[tuple[int, int]]], limit: int = 8) -> list[dict]:
    """Cluster per-player loss events into engagements with a trade winner.

    Events close in time across both players are one battle; the player who lost
    materially fewer objects "won the trade".
    """
    flat = sorted(
        (ms, name, loss) for name, events in events_by_name.items() for ms, loss in events
    )
    if not flat:
        return []

    clusters: list[list[tuple[int, str, int]]] = []
    current = [flat[0]]
    for ev in flat[1:]:
        if ev[0] - current[-1][0] <= _BATTLE_WINDOW_MS:
            current.append(ev)
        else:
            clusters.append(current)
            current = [ev]
    clusters.append(current)

    battles: list[dict] = []
    for cluster in clusters:
        losses: dict[str, int] = {}
        for _ms, name, loss in cluster:
            losses[name] = losses.get(name, 0) + loss
        total = sum(losses.values())
        if total < _BATTLE_MIN_TOTAL:
            continue
        winner = None
        if len(losses) >= 2:
            lo = min(losses.values())
            hi = max(losses.values())
            if lo <= _TRADE_MARGIN * hi:
                winner = min(losses, key=losses.get)
        battles.append(
            {
                "at": _fmt_ms(cluster[0][0]),
                "_ms": cluster[0][0],
                "losses": dict(sorted(losses.items(), key=lambda kv: -kv[1])),
                "trade_winner": winner,
                "total": total,
            }
        )
    # Keep the biggest engagements, presented in chronological order.
    battles.sort(key=lambda b: -b["total"])
    top = sorted(battles[:limit], key=lambda b: b["_ms"])
    for b in top:
        del b["_ms"]
    return top


def _severity_rank(item: dict) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(item.get("severity"), 3)


def _improvement_profile(p: PlayerMetrics, *, rich: bool) -> list[dict]:
    items: list[dict] = []
    if p.estimated_idle_tc_s is not None and p.estimated_idle_tc_s >= 60:
        biggest = p.idle_tc_gaps[0] if p.idle_tc_gaps else None
        evidence = f"{p.estimated_idle_tc_s}s estimated idle TC"
        if biggest:
            evidence += f"; biggest gap {biggest['gap_s']}s at {biggest['at']}"
        items.append(
            {
                "area": "Town Center uptime",
                "severity": "high",
                "evidence": evidence,
                "recommendation": "Queue villagers before moving the screen or taking fights.",
            }
        )
    late_checks = [c for c in p.build_order_comparison if c["status"] in {"late", "missing"}]
    if late_checks:
        first = late_checks[0]
        items.append(
            {
                "area": "Opening execution",
                "severity": "high" if first["status"] == "missing" else "medium",
                "evidence": (
                    f"{first['checkpoint']} was {first['status']}"
                    f" (actual {first['actual']}, target {first['target']})"
                ),
                "recommendation": "Tighten the early timing checkpoints before adding complexity.",
            }
        )
    if p.high_float_s is not None and p.high_float_s >= 120:
        items.append(
            {
                "area": "Spending and production",
                "severity": "medium",
                "evidence": f"{p.high_float_s}s above {_FLOAT_THRESHOLD} banked resources",
                "recommendation": (
                    "Add production buildings or spend into upgrades before floating grows."
                ),
            }
        )
    reached_later_age = p.castle_time_s is not None or p.imperial_time_s is not None
    if rich and p.techs_researched <= 2 and reached_later_age:
        items.append(
            {
                "area": "Upgrade follow-through",
                "severity": "medium",
                "evidence": f"Only {p.techs_researched} non-age techs researched",
                "recommendation": "Pair each unit choice with its attack/armor/economy upgrades.",
            }
        )
    if p.biggest_loss and p.biggest_loss.get("count", 0) >= 20:
        items.append(
            {
                "area": "Fight selection",
                "severity": "medium",
                "evidence": (
                    f"Biggest object drop was {p.biggest_loss['count']} at {p.biggest_loss['at']}"
                ),
                "recommendation": (
                    "Before committing, check numbers, upgrades, hill position, and reinforcements."
                ),
            }
        )
    if p.eapm is not None and p.eapm < 25:
        items.append(
            {
                "area": "Mechanical tempo",
                "severity": "low",
                "evidence": f"{p.eapm} EAPM",
                "recommendation": (
                    "Use control groups and production hotkeys to reduce idle decision time."
                ),
            }
        )
    items.sort(key=_severity_rank)
    return items[:5]


def _action_plan(profile: list[dict]) -> list[dict]:
    drills = {
        "Town Center uptime": (
            "Play three 16-minute openings and restart whenever the TC is idle over 10 seconds.",
            "Under 45s estimated idle TC before 16:00.",
        ),
        "Opening execution": (
            "Run the opening against the AI until every checkpoint is within 45 seconds.",
            "All opening checkpoints on time or early.",
        ),
        "Spending and production": (
            "At 12, 16, and 20 minutes, add production before taking fights if floating.",
            f"Keep >{_FLOAT_THRESHOLD} banked-resource stretches under 60 seconds.",
        ),
        "Upgrade follow-through": (
            "Before massing a unit line, queue the matching attack/armor or key economy upgrade.",
            "At least one relevant military or economy upgrade with each Castle Age unit switch.",
        ),
        "Fight selection": (
            "Pause mentally before each engagement: upgrades, numbers, hill, reinforcements.",
            "Avoid one large losing object drop in the next replay.",
        ),
        "Mechanical tempo": (
            "Use one control group for TC(s), one for production, and cycle them often.",
            "Raise command/EAPM tempo without sacrificing villager production.",
        ),
    }
    out = []
    for idx, item in enumerate(profile[:3], start=1):
        drill, target = drills.get(
            item["area"],
            ("Replay the first 15 minutes and isolate this habit.", "Show measurable improvement."),
        )
        out.append(
            {
                "priority": idx,
                "focus": item["area"],
                "why": item["evidence"],
                "drill": drill,
                "target": target,
            }
        )
    if not out:
        out.append(
            {
                "priority": 1,
                "focus": "Preserve clean fundamentals",
                "why": "No major deterministic leak was flagged",
                "drill": "Replay the same opening and keep the first 16 minutes equally clean.",
                "target": "Match or beat your current age-up and idle-TC benchmarks.",
            }
        )
    return out


def _label_to_s(label: str) -> int | None:
    try:
        mins, secs = label.split(":", 1)
        return int(mins) * 60 + int(secs)
    except (ValueError, AttributeError):
        return None


def _timeline(
    parsed: ParsedReplay, players: list[PlayerMetrics], battles: list[dict], limit: int = 40
) -> list[dict]:
    by_name = {p.name: p for p in players}
    events: list[dict] = []
    for raw in parsed.humans:
        pm = by_name.get(raw.name)
        if pm is None:
            continue
        for age in ("feudal", "castle", "imperial"):
            s = _secs(raw.age_up_ms.get(age))
            if s is not None:
                events.append(
                    {
                        "_s": s,
                        "at": _time_label(s),
                        "type": "age_up",
                        "player": raw.name,
                        "label": f"{raw.name} reached {age.title()}",
                    }
                )
        for ms, name in raw.build_order[:8]:
            s = ms // 1000
            if _norm(name) in _MILITARY_BUILDINGS or _norm(name) in {
                "market",
                "blacksmith",
                "town center",
            }:
                events.append(
                    {
                        "_s": s,
                        "at": _time_label(s),
                        "type": "building",
                        "player": raw.name,
                        "label": f"{raw.name} built first {name}",
                    }
                )
        for gap in pm.idle_tc_gaps[:3]:
            s = _label_to_s(gap["at"])
            if s is None:
                continue
            events.append(
                {
                    "_s": s,
                    "at": gap["at"],
                    "type": "idle_tc",
                    "player": raw.name,
                    "label": f"{raw.name} had a {gap['gap_s']}s TC idle gap",
                    "severity": "high" if gap["gap_s"] >= 75 else "medium",
                }
            )

    for battle in battles:
        s = _label_to_s(battle["at"])
        if s is None:
            continue
        losses = ", ".join(f"{name} -{count}" for name, count in battle["losses"].items())
        suffix = (
            f"; {battle['trade_winner']} won the trade"
            if battle.get("trade_winner")
            else "; even trade"
        )
        events.append(
            {
                "_s": s,
                "at": battle["at"],
                "type": "battle",
                "label": f"Fight: {losses}{suffix}",
                "total": battle["total"],
            }
        )

    events.sort(key=lambda e: (e["_s"], e["type"], e.get("player", "")))
    trimmed = events[:limit]
    for ev in trimmed:
        del ev["_s"]
    return trimmed


def _matchup_context(metrics: ReplayMetrics) -> dict:
    style = _map_style(metrics.map_name)
    players = [
        {
            "name": p.name,
            "civilization": p.civilization,
            "civ_profile": _CIV_PROFILES.get(p.civilization, "flexible/unknown profile"),
            "opening": p.opening,
            "result": p.result,
        }
        for p in metrics.players
    ]
    notes: list[str] = []
    if style == "open":
        notes.append("Open maps reward early military presence, scouting, and clean Feudal tempo.")
    elif style == "closed":
        notes.append(
            "Closed maps reward clean economy, Castle timing, relic control, and boom decisions."
        )
    elif style == "water":
        notes.append("Water maps usually hinge on dock timing, fish economy, and naval control.")
    elif style == "hybrid":
        notes.append("Hybrid maps split attention between land openings and water/fish control.")
    else:
        notes.append(
            "Map style is not classified; use the concrete timings more than generic map rules."
        )
    if len(players) == 2:
        a, b = players
        notes.append(
            f"{a['civilization']} ({a['civ_profile']}) vs "
            f"{b['civilization']} ({b['civ_profile']}) frames the strategic plan."
        )
    return {"map_style": style, "players": players, "notes": notes}


def build_metrics(parsed: ParsedReplay) -> ReplayMetrics:
    duration_min = parsed.duration_ms / 60000 if parsed.duration_ms else 0
    style = _map_style(parsed.map_name)

    player_metrics: list[PlayerMetrics] = []
    loss_events_by_name: dict[str, list[tuple[int, int]]] = {}
    for p in parsed.humans:
        feudal = p.age_up_ms.get("feudal")
        castle = p.age_up_ms.get("castle")
        imperial = p.age_up_ms.get("imperial")
        apm = round(p.total_actions / duration_min, 1) if duration_min else None
        gaps, longest, idle = _villager_gaps(p.villager_queue_ms, _age_research_blocks(p))
        villagers_16m = (
            3 + sum(1 for ms in p.villager_queue_ms if ms <= _BOOM_WINDOW_S * 1000)
            if p.villager_queue_ms
            else None
        )
        ts_summary, loss_events = _timeseries_metrics(p.timeseries)
        if loss_events:
            loss_events_by_name[p.name] = loss_events
        building_times = _first_building_times(p.build_order)
        opening, opening_confidence = _opening(p, building_times)
        comparison = _build_order_comparison(opening, style, p, building_times)
        techs = _tech_names(p.research_names)

        pm = PlayerMetrics(
            name=p.name,
            civilization=p.civilization,
            color_id=p.color_id,
            color_name=p.color_name or color_name_from_id(p.color_id),
            team_id=p.team_id,
            profile_id=p.profile_id,
            result=_result(p, parsed.players),
            eapm=p.eapm,
            feudal_time_s=_secs(feudal),
            castle_time_s=_secs(castle),
            imperial_time_s=_secs(imperial),
            dark_age_s=_secs(feudal),
            feudal_to_castle_s=_secs(_diff(castle, feudal)),
            castle_to_imperial_s=_secs(_diff(imperial, castle)),
            command_actions_per_min=apm,
            villagers_queued=len(p.villager_queue_ms),
            villagers_16m=villagers_16m,
            idle_tc_gaps=gaps,
            longest_idle_gap_s=longest,
            estimated_idle_tc_s=idle,
            build_order=_build_order_labels(p.build_order),
            building_counts=dict(sorted(p.building_counts.items(), key=lambda kv: -kv[1])),
            units_trained=dict(sorted(p.units_trained.items(), key=lambda kv: -kv[1])),
            techs=techs,
            techs_researched=len(techs),
            key_tech_status=_key_tech_status(p.civilization, techs, rich=parsed.backend == "full"),
            peak_objects=ts_summary["peak_objects"],
            peak_resources=ts_summary["peak_resources"],
            objects_lost_total=ts_summary["objects_lost_total"],
            biggest_loss=ts_summary["biggest_loss"],
            high_float_s=ts_summary["high_float_s"],
            opening=opening,
            opening_confidence=opening_confidence,
            build_order_comparison=comparison,
        )
        pm.improvement_profile = _improvement_profile(pm, rich=parsed.backend == "full")
        pm.action_plan = _action_plan(pm.improvement_profile)
        player_metrics.append(pm)

    battles = _battles(loss_events_by_name)
    metrics = ReplayMetrics(
        source_file=parsed.path,
        backend=parsed.backend,
        game_version=parsed.game_version,
        build=parsed.build,
        map_name=parsed.map_name,
        map_size=parsed.map_size,
        diplomacy=parsed.diplomacy,
        duration_s=parsed.duration_ms // 1000,
        rated=parsed.rated,
        speed=parsed.speed,
        population_limit=parsed.population_limit,
        body_complete=parsed.body_complete,
        recorded_at=parsed.recorded_at,
        recorded_at_source=parsed.recorded_at_source,
        players=player_metrics,
        battles=battles,
    )
    metrics.timeline = _timeline(parsed, player_metrics, battles)
    metrics.matchup_context = _matchup_context(metrics)
    return metrics
