"""Locate AoE2 DE replay files across platforms.

The whole point of a "transferable" product is that a teammate on Windows, a
friend on macOS/CrossOver, or someone on Linux/Proton can all run it without
hand-typing a path. We search every known install layout and return what we find,
newest first.
"""

from __future__ import annotations

import sys
from pathlib import Path

_GLOB = "**/savegame/**/*.aoe2record"


def _candidate_roots() -> list[Path]:
    """Directories that may contain an AoE2 DE profile + savegame folder."""
    home = Path.home()
    roots: list[Path] = []

    if sys.platform == "darwin":
        # CrossOver bottles — the layout this project was built against.
        cx = home / "Library/Application Support/CrossOver/Bottles"
        if cx.exists():
            roots += [b / "drive_c/users/crossover/Games/Age of Empires 2 DE" for b in cx.iterdir()]
            roots += [b / "drive_c/users/crossover/Games" for b in cx.iterdir()]
        # Steam Play / Whisky / other Wine prefixes commonly live here too.
        roots.append(home / "Library/Application Support/Steam")
    elif sys.platform.startswith("win"):
        # Native Steam install.
        roots += [
            Path("C:/Program Files (x86)/Steam/userdata"),
            home / "Games/Age of Empires 2 DE",
        ]
    else:  # Linux — Proton / Steam compatibility data.
        roots += [
            home / ".steam/steam/steamapps/compatdata",
            home / ".local/share/Steam/steamapps/compatdata",
        ]

    return [r for r in roots if r.exists()]


def find_replays() -> list[Path]:
    """Return all discoverable ``.aoe2record`` files, newest first (deduplicated)."""
    seen: dict[Path, Path] = {}
    for root in _candidate_roots():
        try:
            for f in root.glob(_GLOB):
                seen.setdefault(f.resolve(), f)
        except (PermissionError, OSError):
            continue
    return sorted(seen.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def resolve_replay(arg: str | None) -> Path:
    """Turn a CLI argument into a concrete replay path.

    - A real path → used as-is.
    - ``None`` or ``"latest"`` → the most recent discovered replay.

    Raises FileNotFoundError with a helpful message when nothing matches.
    """
    if arg and arg.lower() != "latest":
        p = Path(arg).expanduser()
        if p.exists():
            return p
        raise FileNotFoundError(f"No such replay: {arg}")

    found = find_replays()
    if not found:
        raise FileNotFoundError(
            "No replays found automatically. Pass a path explicitly:\n"
            "  aoe2coach analyze '/path/to/MP Replay ....aoe2record'\n"
            "Run `aoe2coach find` to see where this tool looks."
        )
    return found[0]
