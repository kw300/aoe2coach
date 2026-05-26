"""Layer 2 — derive coaching metrics from a :class:`~aoe2coach.parse.ParsedReplay`.

Pure, deterministic Python: no Claude, no I/O. Turns parsed events into the signals
a coach reasons about and produces a compact, JSON-serializable summary.

When the replay was parsed with the **full** backend, this layer additionally
computes the high-value stuff: villager-production gaps (idle Town Center time),
named build orders, true win/loss, and EAPM. With the **fast** backend those rich
fields are simply absent and we fall back to tempo + resignation inference.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .parse import ParsedReplay, PlayerReplay, _fmt_ms

# A Town Center pumps a villager about every 25s. A gap materially larger than that
# (before the boom ends) means the TC sat idle — the #1 sub-expert mistake.
_IDLE_GAP_THRESHOLD_S = 40
_IDEAL_VILL_INTERVAL_S = 25
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


@dataclass
class PlayerMetrics:
    name: str
    civilization: str
    color_id: int | None
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
    idle_tc_gaps: list[dict]  # [{"at": "4:10", "gap_s": 62}]
    longest_idle_gap_s: int | None
    estimated_idle_tc_s: int | None
    build_order: list[str]  # ["House@0:03", "Barracks@9:40", ...]
    building_counts: dict[str, int]
    units_trained: dict[str, int]
    techs_researched: int  # count of distinct techs (not click events)
    techs: list[str]  # the actual techs, in research order (e.g. "Bloodlines", "Blast Furnace")
    # From the whole-game object/resource timeseries (full backend only)
    peak_objects: int | None
    peak_resources: int | None
    objects_lost_total: int | None
    biggest_loss: dict | None  # {"at": "31:18", "count": 44}
    high_float_s: int | None  # seconds banked resources sat above _FLOAT_THRESHOLD

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
    players: list[PlayerMetrics] = field(default_factory=list)
    # Match-level engagement timeline derived from object-count drops (full backend).
    # Each: {"at": "31:18", "losses": {name: n}, "trade_winner": name|None, "total": n}
    battles: list[dict] = field(default_factory=list)

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


def _villager_gaps(queue_ms: list[int]) -> tuple[list[dict], int | None, int | None]:
    """Find idle-TC gaps in villager production during the boom window.

    Returns (gaps, longest_gap_s, estimated_idle_s).
    """
    if not queue_ms:
        return [], None, None
    times = sorted(queue_ms)
    gaps: list[dict] = []
    estimated_idle_ms = 0
    longest = 0
    for prev, cur in zip(times, times[1:], strict=False):
        if prev > _BOOM_WINDOW_S * 1000:
            break
        gap_ms = cur - prev
        if gap_ms > longest:
            longest = gap_ms
        if gap_ms > _IDLE_GAP_THRESHOLD_S * 1000:
            gaps.append({"at": _fmt_ms(prev), "gap_s": gap_ms // 1000})
            estimated_idle_ms += gap_ms - _IDEAL_VILL_INTERVAL_S * 1000
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


def _tech_names(research_names: list[str]) -> list[str]:
    return [name for name in dict.fromkeys(research_names) if name not in _AGE_RESEARCH_NAMES]


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


def build_metrics(parsed: ParsedReplay) -> ReplayMetrics:
    duration_min = parsed.duration_ms / 60000 if parsed.duration_ms else 0

    player_metrics: list[PlayerMetrics] = []
    loss_events_by_name: dict[str, list[tuple[int, int]]] = {}
    for p in parsed.humans:
        feudal = p.age_up_ms.get("feudal")
        castle = p.age_up_ms.get("castle")
        imperial = p.age_up_ms.get("imperial")
        apm = round(p.total_actions / duration_min, 1) if duration_min else None
        gaps, longest, idle = _villager_gaps(p.villager_queue_ms)
        ts_summary, loss_events = _timeseries_metrics(p.timeseries)
        if loss_events:
            loss_events_by_name[p.name] = loss_events

        player_metrics.append(
            PlayerMetrics(
                name=p.name,
                civilization=p.civilization,
                color_id=p.color_id,
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
                idle_tc_gaps=gaps,
                longest_idle_gap_s=longest,
                estimated_idle_tc_s=idle,
                build_order=_build_order_labels(p.build_order),
                building_counts=dict(sorted(p.building_counts.items(), key=lambda kv: -kv[1])),
                units_trained=dict(sorted(p.units_trained.items(), key=lambda kv: -kv[1])),
                techs=(_techs := _tech_names(p.research_names)),
                techs_researched=len(_techs),
                peak_objects=ts_summary["peak_objects"],
                peak_resources=ts_summary["peak_resources"],
                objects_lost_total=ts_summary["objects_lost_total"],
                biggest_loss=ts_summary["biggest_loss"],
                high_float_s=ts_summary["high_float_s"],
            )
        )

    return ReplayMetrics(
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
        players=player_metrics,
        battles=_battles(loss_events_by_name),
    )
