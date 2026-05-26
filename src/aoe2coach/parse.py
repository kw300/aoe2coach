"""Layer 1 — parse a ``.aoe2record`` file into structured Python objects.

Two interchangeable backends produce the same :class:`ParsedReplay`:

- **full** (``mgz`` / happyleavesaoc) — the rich path. Named build orders, villager
  production, pre-computed age uptimes + EAPM, the actual winner, the map terrain
  grid, and located starting objects. Supports DE replays up to ~v66.x (everything
  before the Feb-2026 "Last Chieftains" update; see CLAUDE.md / issue #138).
- **fast** (``mgz-fast`` / AoEInsights fork) — the compatibility path. Reads the
  *current* game patch, which full ``mgz`` cannot. Lower-level: we derive what we
  can from the raw command stream; some rich fields stay empty.

``mgz`` and ``mgz-fast`` share the ``mgz`` import name, so only one can be installed
at a time. :func:`parse_replay` detects which is present and dispatches accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import civdata

# AoE2 research tech IDs that correspond to advancing an age (fast backend).
_AGE_TECH = {101: "feudal", 102: "castle", 103: "imperial"}
_AGE_RESEARCH_NAMES = {"Feudal Age", "Castle Age", "Imperial Age"}
_VILLAGER_UNIT_ID = 83


@dataclass
class PlayerReplay:
    """One participant. Fields populated by both backends are at the top; the rich
    block below is filled by the full backend (and best-effort by the fast one)."""

    number: int
    name: str
    civ_id: int | None
    civilization: str
    profile_id: int | None
    color_id: int | None
    team_id: int | None

    # Common (both backends, best-effort)
    age_up_ms: dict[str, int] = field(default_factory=dict)  # {"feudal": 557000, ...}
    build_actions: int = 0
    total_actions: int = 0
    resigned_at_ms: int | None = None

    # Rich (full backend; fast backend leaves most empty)
    winner: bool | None = None
    eapm: int | None = None
    build_order: list[tuple[int, str]] = field(default_factory=list)  # (ms, building)
    building_counts: dict[str, int] = field(default_factory=dict)
    villager_queue_ms: list[int] = field(default_factory=list)
    units_trained: dict[str, int] = field(default_factory=dict)  # non-villager
    research_names: list[str] = field(default_factory=list)  # non-age techs
    # Whole-game samples: (ms, total_objects, total_resources). ~every 6.5s.
    timeseries: list[tuple[int, int, int]] = field(default_factory=list)

    @property
    def is_human(self) -> bool:
        return self.color_id is not None and self.color_id >= 0


@dataclass
class ParsedReplay:
    """A fully parsed replay — the unit of currency for the whole pipeline."""

    path: str
    backend: str  # "full" | "fast"
    game_version: str
    build: int | None
    map_name: str
    map_id: int | None
    map_size: str | None
    diplomacy: str | None
    duration_ms: int
    rated: bool
    speed: float | None
    population_limit: int | None
    players: list[PlayerReplay]
    body_complete: bool  # False if the body stream ended early (fast backend)

    @property
    def duration_label(self) -> str:
        return _fmt_ms(self.duration_ms)

    @property
    def humans(self) -> list[PlayerReplay]:
        return [p for p in self.players if p.is_human]


def _fmt_ms(ms: int | None) -> str:
    if not ms:
        return "—"
    total = ms // 1000
    return f"{total // 60}:{total % 60:02d}"


def _detect_backend() -> str:
    """Return 'full' if the rich mgz model is importable, else 'fast'."""
    try:
        import mgz.model  # noqa: F401  (only full mgz ships this)

        return "full"
    except ImportError:
        try:
            import mgz.fast  # noqa: F401

            return "fast"
        except ImportError as exc:  # pragma: no cover
            raise ValueError(
                "No replay parser installed. Install one:\n"
                '  pip install -e ".[full]"   # rich narratives, replays up to v66.x\n'
                '  pip install -e ".[fast]"   # current game patch (e.g. your own games)\n'
                "They share the 'mgz' import name, so install exactly one. See CLAUDE.md."
            ) from exc


def parse_replay(path: str | Path) -> ParsedReplay:
    """Parse a ``.aoe2record`` into a :class:`ParsedReplay` using whichever backend
    is installed.

    Raises:
        FileNotFoundError: the path does not exist.
        ValueError: no parser installed, or the file is unparseable by the installed
            backend (typically a game patch the backend doesn't support).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No such replay: {path}")

    backend = _detect_backend()
    if backend == "full":
        return _parse_full(path)
    return _parse_fast(path)


# --------------------------------------------------------------------------- #
# Full backend — rich data via mgz.model.parse_match
# --------------------------------------------------------------------------- #


def _td_ms(td) -> int:
    """timedelta → milliseconds."""
    return int(td.total_seconds() * 1000) if td is not None else 0


def _parse_full(path: Path) -> ParsedReplay:
    from mgz import model

    try:
        with path.open("rb") as handle:
            match = model.parse_match(handle)
    except Exception as exc:
        raise ValueError(
            f"Could not parse '{path.name}' with full mgz. If this is a recent patch "
            f"(v67+/Last Chieftains era), full mgz can't read it yet — use the fast "
            f"backend instead (see CLAUDE.md). Underlying error: {exc}"
        ) from exc

    # Age uptimes: {player_number: {"feudal": ms, ...}}
    age_by_player: dict[int, dict[str, int]] = {}
    for up in match.uptimes or []:
        age_label = str(getattr(up.age, "name", up.age)).split(".")[-1].replace("_AGE", "").lower()
        if age_label in ("feudal", "castle", "imperial") and up.player is not None:
            age_by_player.setdefault(up.player.number, {})[age_label] = _td_ms(up.timestamp)

    players: list[PlayerReplay] = []
    by_number: dict[int, PlayerReplay] = {}
    for p in match.players:
        pr = PlayerReplay(
            number=p.number,
            name=p.name or "",
            civ_id=p.civilization_id,
            civilization=(
                str(p.civilization) if p.civilization else civdata.civ_name(p.civilization_id)
            ),
            profile_id=p.profile_id,
            color_id=p.color_id,
            team_id=p.team_id,
            winner=getattr(p, "winner", None),
            eapm=getattr(p, "eapm", None),
            age_up_ms=age_by_player.get(p.number, {}),
            timeseries=[
                (_td_ms(r.timestamp), r.total_objects, r.total_resources)
                for r in (getattr(p, "timeseries", None) or [])
            ],
        )
        players.append(pr)
        by_number[p.number] = pr

    _accumulate_inputs(match.inputs, by_number)

    return ParsedReplay(
        path=str(path),
        backend="full",
        game_version=str(match.game_version),
        build=getattr(match, "build_version", None),
        map_name=getattr(match.map, "name", "Unknown"),
        map_id=getattr(match.map, "id", None),
        map_size=(str(match.map.size) if getattr(match.map, "size", None) else None),
        diplomacy=getattr(match, "diplomacy_type", None),
        duration_ms=_td_ms(match.duration),
        rated=bool(getattr(match, "rated", False)),
        speed=getattr(match, "speed", None),
        population_limit=getattr(match, "population", None),
        players=players,
        body_complete=True,
    )


def _accumulate_inputs(inputs, by_number: dict[int, PlayerReplay]) -> None:
    """Walk the typed input stream, filling build orders / villager / unit / tech."""
    seen_building: dict[int, set] = {n: set() for n in by_number}
    for inp in inputs or []:
        if inp.player is None:
            continue
        player = by_number.get(inp.player.number)
        if player is None:
            continue
        player.total_actions += 1
        t = _td_ms(inp.timestamp)
        payload = inp.payload or {}
        if inp.type == "Build":
            name = payload.get("building") or inp.param or "Building"
            player.build_actions += 1
            player.building_counts[name] = player.building_counts.get(name, 0) + 1
            if name not in seen_building[inp.player.number]:
                seen_building[inp.player.number].add(name)
                player.build_order.append((t, name))
        elif inp.type in ("Queue", "De Queue"):
            unit_id = payload.get("unit_id")
            unit = payload.get("unit") or inp.param
            amount = payload.get("amount", 1) or 1
            if unit_id == _VILLAGER_UNIT_ID:
                player.villager_queue_ms.extend([t] * amount)
            elif unit:
                player.units_trained[unit] = player.units_trained.get(unit, 0) + amount
        elif inp.type == "Research":
            tech = payload.get("technology") or inp.param
            if tech and tech not in _AGE_RESEARCH_NAMES:
                player.research_names.append(tech)


# --------------------------------------------------------------------------- #
# Fast backend — current-patch compatibility via mgz.fast
# --------------------------------------------------------------------------- #


def _parse_fast(path: Path) -> ParsedReplay:
    import mgz.fast.header as fast_header
    from mgz.fast import meta, operation
    from mgz.fast.enums import Action, Operation

    with path.open("rb") as handle:
        try:
            header = fast_header.parse(handle)
        except Exception as exc:
            raise ValueError(
                f"Could not parse '{path.name}' with the fast backend. The game patch "
                f"may be newer than mgz-fast supports — update it (see CLAUDE.md). "
                f"Underlying error: {exc}"
            ) from exc

        de = header.get("de") or {}
        players = _build_players_fast(de.get("players", []))
        by_number = {p.number: p for p in players}
        duration_ms, body_complete = _scan_body_fast(
            handle, meta, operation, Operation, Action, by_number
        )

    return ParsedReplay(
        path=str(path),
        backend="fast",
        game_version=str(header.get("version", "unknown")),
        build=de.get("build"),
        map_id=de.get("rms_map_id"),
        map_name=civdata.map_name(de.get("rms_map_id")),
        map_size=None,
        diplomacy=None,
        duration_ms=duration_ms,
        rated=bool(de.get("rated")),
        speed=de.get("speed"),
        population_limit=de.get("population_limit"),
        players=players,
        body_complete=body_complete,
    )


def _build_players_fast(raw_players: list[dict]) -> list[PlayerReplay]:
    players: list[PlayerReplay] = []
    for idx, p in enumerate(raw_players):
        name = p.get("name")
        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="replace")
        civ_id = p.get("civilization_id")
        players.append(
            PlayerReplay(
                number=p.get("number", idx),
                name=name or "",
                civ_id=civ_id,
                civilization=civdata.civ_name(civ_id),
                profile_id=p.get("profile_id"),
                color_id=p.get("color_id"),
                team_id=p.get("team_id"),
            )
        )
    return players


def _scan_body_fast(handle, meta, operation, Operation, Action, by_number) -> tuple[int, bool]:
    try:
        meta(handle)
    except Exception:
        return 0, False

    t = 0
    complete = False
    seen_building: dict[int, set] = {n: set() for n in by_number}
    while True:
        try:
            op_type, payload = operation(handle)
        except EOFError:
            complete = True
            break
        except Exception:
            break

        if op_type == Operation.SYNC:
            t += payload[0]
        elif op_type == Operation.ACTION:
            action_type, data = payload
            pid = data.get("player_id")
            player = by_number.get(pid)
            if player is None:
                continue
            player.total_actions += 1
            if action_type == Action.RESEARCH:
                age = _AGE_TECH.get(data.get("technology_id"))
                if age and age not in player.age_up_ms:
                    player.age_up_ms[age] = t
            elif action_type == Action.BUILD:
                player.build_actions += 1
                # Name the building from bundled data so build orders read in English.
                name = civdata.object_name(data.get("building_id"))
                player.building_counts[name] = player.building_counts.get(name, 0) + 1
                if name not in seen_building[pid]:
                    seen_building[pid].add(name)
                    player.build_order.append((t, name))
            elif action_type == Action.RESIGN:
                player.resigned_at_ms = t

    return t, complete
