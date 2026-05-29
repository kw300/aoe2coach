"""Command-line interface: ``aoe2coach <command>``.

Commands:
    find                      List replays discovered on this machine.
    metrics  [replay|latest]  Parse a replay and print its metrics JSON (no model call,
                              no API key needed).
    analyze  [replay|latest]  Full AI coaching report (calls the configured model).

``replay`` may be a path or the literal ``latest`` (the default) for the most
recent discovered replay.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__


def _cmd_find(_args: argparse.Namespace) -> int:
    from .replays import find_replays

    found = find_replays()
    if not found:
        print("No replays found. See README for where aoe2coach looks, or pass a path.")
        return 1
    print(f"Found {len(found)} replay(s), newest first:\n")
    for i, p in enumerate(found[:25]):
        print(f"  [{i}] {p}")
    return 0


def _cmd_metrics(args: argparse.Namespace) -> int:
    from . import build_metrics, parse_replay
    from .replays import resolve_replay

    path = resolve_replay(args.replay)
    metrics = build_metrics(parse_replay(path))
    print(json.dumps(metrics.to_dict(), indent=2, sort_keys=True, default=str))
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    from . import build_metrics, parse_replay
    from .coach import coach_replay
    from .config import load_config
    from .replays import resolve_replay
    from .report import build_report, default_report_path

    config = load_config(require_key=True)  # fail fast before parsing if no key
    path = resolve_replay(args.replay)
    print(f"Parsing {path.name} …", file=sys.stderr)
    metrics = build_metrics(parse_replay(path))

    elo = None
    if not args.no_elo:
        from .elo import fetch_ratings

        pids = [p.profile_id for p in metrics.players if p.profile_id]
        elo = fetch_ratings(pids) or None
        if elo:
            print("Fetched real ladder ratings.", file=sys.stderr)

    print(f"Coaching with {config.model} …\n", file=sys.stderr)
    result = coach_replay(
        metrics,
        config=config,
        focus_player=args.player,
        elo=elo,
        stream=args.stream,
        on_text=(lambda c: print(c, end="", flush=True)) if args.stream else None,
    )
    if not args.stream:
        print(result.text)
    else:
        print()  # newline after streamed output

    print(f"\n[{result.cost_note}]", file=sys.stderr)

    if not args.no_save:
        from pathlib import Path

        report = build_report(metrics, result.text, result.model)
        out = Path(args.out) if args.out else default_report_path(metrics)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"Saved report → {out}", file=sys.stderr)
    return 0


def _cmd_trends(args: argparse.Namespace) -> int:
    from pathlib import Path

    from . import build_metrics, parse_replay
    from .replays import find_replays
    from .trends import aggregate

    if args.replays:
        paths = [Path(p) for p in args.replays]
    else:
        # Oldest-first so trend direction reads chronologically.
        paths = list(reversed(find_replays()[: args.last]))
    if not paths:
        print("No replays to analyze. Pass paths or run `aoe2coach find`.", file=sys.stderr)
        return 1

    metrics_list = []
    for p in paths:
        try:
            metrics_list.append(build_metrics(parse_replay(p)))
        except Exception as exc:  # skip a replay the backend can't read
            print(f"  skip {Path(p).name}: {exc}", file=sys.stderr)
    if not metrics_list:
        print("No parseable replays.", file=sys.stderr)
        return 1

    summary = aggregate(metrics_list, args.player)
    print(
        f"\n{summary.player}: {summary.n_games} games, "
        f"{summary.wins}W-{summary.losses}L "
        f"(win rate {summary.win_rate if summary.win_rate is not None else '—'})",
        file=sys.stderr,
    )
    print(
        f"avg Feudal {summary.avg_feudal_s or '—'}s · avg idle-TC {summary.avg_idle_tc_s or '—'}s "
        f"· Feudal trend: {summary.feudal_direction}\n",
        file=sys.stderr,
    )

    if args.no_coach:
        print(json.dumps(summary.to_dict(), indent=2, default=str))
        return 0

    from .coach import coach_trends
    from .config import load_config

    config = load_config(require_key=True)
    print(f"Analyzing trends with {config.model} …\n", file=sys.stderr)
    result = coach_trends(
        summary,
        config=config,
        stream=args.stream,
        on_text=(lambda c: print(c, end="", flush=True)) if args.stream else None,
    )
    if not args.stream:
        print(result.text)
    else:
        print()
    print(f"\n[{result.cost_note}]", file=sys.stderr)
    return 0


def _cmd_minimap(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .minimap import render_minimap
    from .replays import resolve_replay

    path = resolve_replay(args.replay)
    out = Path(args.out) if args.out else path.with_suffix(".minimap.png")
    render_minimap(path, out)
    print(f"Saved minimap → {out}")
    return 0


def _cmd_web(args: argparse.Namespace) -> int:
    from .webapp import main as web_main

    print(f"Serving replay browser at http://{args.host}:{args.port} (Ctrl-C to stop)")
    web_main(host=args.host, port=args.port)
    return 0


def _cmd_update_data(_args: argparse.Namespace) -> int:
    from .dataupdate import main as update_main

    return update_main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aoe2coach",
        description="AI coaching for Age of Empires II: Definitive Edition replays.",
    )
    parser.add_argument("--version", action="version", version=f"aoe2coach {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("find", help="List replays discovered on this machine.").set_defaults(
        func=_cmd_find
    )

    m = sub.add_parser("metrics", help="Print parsed metrics JSON (no model needed).")
    m.add_argument("replay", nargs="?", default="latest", help="Path or 'latest'.")
    m.set_defaults(func=_cmd_metrics)

    a = sub.add_parser("analyze", help="Generate an AI coaching report (calls the model).")
    a.add_argument("replay", nargs="?", default="latest", help="Path or 'latest'.")
    a.add_argument("--player", help="Coach only the player with this name.")
    a.add_argument("--stream", action="store_true", help="Stream coaching as it's written.")
    a.add_argument("--out", help="Write the report to this path.")
    a.add_argument("--no-save", action="store_true", help="Don't write a report file.")
    a.add_argument("--no-elo", action="store_true", help="Skip fetching real ladder ratings.")
    a.set_defaults(func=_cmd_analyze)

    tr = sub.add_parser("trends", help="Analyze habits across many games + practice plan.")
    tr.add_argument("replays", nargs="*", help="Replay paths (default: your recent games).")
    tr.add_argument("--player", help="Focus player name (default: most frequent across games).")
    tr.add_argument("--last", type=int, default=10, help="How many recent games (default 10).")
    tr.add_argument("--stream", action="store_true", help="Stream the coaching.")
    tr.add_argument("--no-coach", action="store_true", help="Print the trend JSON, skip the model.")
    tr.set_defaults(func=_cmd_trends)

    mm = sub.add_parser("minimap", help="Render a minimap PNG (full backend + viz extra).")
    mm.add_argument("replay", nargs="?", default="latest", help="Path or 'latest'.")
    mm.add_argument("--out", help="Output PNG path.")
    mm.set_defaults(func=_cmd_minimap)

    wb = sub.add_parser("web", help="Launch the local web chat UI (web extra).")
    wb.add_argument("--host", default="127.0.0.1")
    wb.add_argument("--port", type=int, default=8000)
    wb.set_defaults(func=_cmd_web)

    sub.add_parser(
        "update-data", help="Regenerate bundled game-data tables (needs the full backend)."
    ).set_defaults(func=_cmd_update_data)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # config + API + parse errors → one clean line
        # Import lazily to avoid a hard dependency for commands that do not call a model.
        from .config import ConfigError

        try:
            import anthropic

            api_errors = (anthropic.AuthenticationError, anthropic.APIStatusError)
        except ImportError:
            api_errors = ()

        if isinstance(exc, (ConfigError, ValueError, *api_errors)):
            print(f"error: {exc}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())
