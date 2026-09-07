"""Local web **chat** UI — pick (or drag in) a replay on the left, talk to the coach.

`aoe2coach web` → opens a browser. Configure `.env` first, then choose a replay (or drag
a `.aoe2record` in); aoe2coach parses it and the coach opens with a report, and you ask
follow-ups. Powered by the same environment-based API path as the CLI.

A thin Flask wrapper over the library (parse → metrics → CoachChat). Optional extra:
    pip install -e ".[full,web]"     # or ".[fast,web]" for current-patch games
"""

from __future__ import annotations

import html
import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4

from . import build_metrics, parse_replay
from .coach import CoachChat, CoachResult, build_opening_message, detect_habits
from .config import ConfigError
from .metrics import ReplayMetrics
from .playercolors import color_hex, color_hex_from_name, color_name
from .report import build_chat_export

try:
    from flask import Flask, Response, render_template_string, request, send_file
    from werkzeug.utils import secure_filename
except ImportError as exc:  # pragma: no cover
    raise SystemExit('The web UI needs Flask:  pip install -e ".[web]"') from exc

_UPLOAD_DIR = Path(tempfile.gettempdir()) / "aoe2coach-uploads"
_MAX_HABITS = 12
_MAX_HABIT_LEN = 160


@dataclass
class _Session:
    chat: CoachChat
    replay: str
    metrics: ReplayMetrics
    focus_player: str | None
    # Visible conversation only; never export hidden metrics or model prompts.
    transcript: list[dict] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)


def _result_payload(result: CoachResult, text_key: str) -> dict:
    return {**result.to_dict(), text_key: result.text}


def _model_error(exc: Exception) -> str:
    if isinstance(exc, ConfigError):
        return str(exc).splitlines()[0]
    # Provider exceptions can contain request internals and credentials.
    return "The model request failed. Check your connection and model settings, then try again."


def _replay_metrics(replay: str) -> ReplayMetrics:
    if not isinstance(replay, str) or not replay.strip():
        raise ValueError("Choose a replay first.")
    if Path(replay).suffix.lower() != ".aoe2record":
        raise ValueError("Choose a .aoe2record file.")
    return build_metrics(parse_replay(replay))


def _validate_focus(metrics, focus_player) -> None:
    if focus_player is not None and (
        not isinstance(focus_player, str) or focus_player not in {p.name for p in metrics.players}
    ):
        raise ValueError("Choose a player from this replay, or select all players.")


def _date_label(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return dt.strftime("%Y-%m-%d %H:%M")


def _player_color(color_id: int | None) -> str | None:
    return color_hex(color_id)


def _player_color_value(color_name_value: str | None, color_id: int | None) -> str | None:
    return color_hex_from_name(color_name_value) or _player_color(color_id)


def _fmt_time(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    return f"{seconds // 60}:{seconds % 60:02d}"


def _fmt_seconds(seconds: int | None) -> str:
    return "—" if seconds is None else f"{seconds}s"


def _rating_record(elo: dict | None, profile_id: int | None) -> dict | None:
    if not elo or profile_id is None:
        return None
    return elo.get(profile_id) or elo.get(str(profile_id))


def _rating_for_player(elo: dict | None, player) -> int | None:
    rec = _rating_record(elo, getattr(player, "profile_id", None))
    rating = rec.get("rm_1v1_rating") if rec else None
    return rating if isinstance(rating, int) else None


def _late_check_count(player) -> int | None:
    checks = getattr(player, "build_order_comparison", None)
    if checks is None:
        return None
    return sum(1 for c in checks if c.get("status") in {"late", "missing"})


def _value_class(values: list[int | float | None], index: int, *, lower_better: bool) -> str:
    value = values[index]
    nums = [v for v in values if v is not None]
    if value is None or not nums:
        return "na"
    if len(set(nums)) == 1:
        return "even"
    best = min(nums) if lower_better else max(nums)
    worst = max(nums) if lower_better else min(nums)
    if value == best:
        return "ok"
    if value == worst:
        return "bad"
    return "near"


def _comparison_row(
    metric: str,
    values: list[int | float | None],
    labels: list[str],
    *,
    lower_better: bool,
) -> dict:
    return {
        "metric": metric,
        "values": labels,
        "classes": [
            _value_class(values, idx, lower_better=lower_better) for idx in range(len(values))
        ],
    }


def _comparison(metrics, elo: dict | None) -> dict:
    players = list(metrics.players)
    ratings = [_rating_for_player(elo, p) for p in players]
    headers = [
        {
            "name": p.name,
            "civilization": p.civilization,
            "rating": ratings[idx],
            "color": _player_color_value(
                getattr(p, "color_name", None), getattr(p, "color_id", None)
            ),
            "color_name": getattr(p, "color_name", None)
            or color_name(getattr(p, "color_id", None)),
        }
        for idx, p in enumerate(players)
    ]

    idle = [getattr(p, "estimated_idle_tc_s", None) for p in players]
    vill16 = [getattr(p, "villagers_16m", None) for p in players]
    feudal = [getattr(p, "feudal_time_s", None) for p in players]
    castle = [getattr(p, "castle_time_s", None) for p in players]
    eapm = [getattr(p, "eapm", None) for p in players]
    action_apm = [getattr(p, "command_actions_per_min", None) for p in players]

    rows = [
        _comparison_row(
            "TC idle",
            idle,
            [f"{_fmt_seconds(v)} idle" for v in idle],
            lower_better=True,
        ),
        _comparison_row(
            "Villagers @16",
            vill16,
            ["—" if v is None else f"~{v}" for v in vill16],
            lower_better=False,
        ),
        _comparison_row(
            "Feudal",
            feudal,
            [_fmt_time(v) for v in feudal],
            lower_better=True,
        ),
        _comparison_row(
            "Castle",
            castle,
            [_fmt_time(v) for v in castle],
            lower_better=True,
        ),
    ]
    if any(v is not None for v in eapm):
        rows.append(
            _comparison_row(
                "EAPM",
                eapm,
                ["—" if v is None else f"{v}" for v in eapm],
                lower_better=False,
            )
        )
    elif any(v is not None for v in action_apm):
        rows.append(
            _comparison_row(
                "Actions/min",
                action_apm,
                ["—" if v is None else f"{v:.1f}" for v in action_apm],
                lower_better=False,
            )
        )
    return {"players": headers, "rows": rows}


def _fetch_elo(metrics, *, timeout: float = 2.0) -> dict:
    pids = [p.profile_id for p in metrics.players if getattr(p, "profile_id", None)]
    if not pids:
        return {}
    try:
        from .elo import fetch_ratings

        return fetch_ratings(pids, timeout=timeout) or {}
    except Exception:  # noqa: BLE001
        return {}


def _listed_replays() -> list[Path]:
    """Replays to show: the launch folder + anything dragged in (NOT the savegame folder —
    that fills the UI with current-patch games the rich backend can't read)."""
    seen: dict[Path, Path] = {}
    for p in [
        *Path.cwd().glob("*.aoe2record"),
        *_UPLOAD_DIR.glob("*.aoe2record"),
        *_UPLOAD_DIR.glob("*/*.aoe2record"),
    ]:
        seen.setdefault(p.resolve(), p)

    def mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    return sorted(seen.values(), key=mtime, reverse=True)


def _web_insights(metrics, elo: dict | None = None) -> dict:
    return {
        "timeline": metrics.timeline,
        "detected_habits": [],
        "comparison": _comparison(metrics, elo),
        "players": [
            {
                "name": p.name,
                "civilization": p.civilization,
                "action_plan": p.action_plan[:3],
                "build_order_comparison": p.build_order_comparison,
            }
            for p in metrics.players
        ],
    }


def _web_preview(metrics) -> dict:
    return {
        "source_file": metrics.source_file,
        "map_name": metrics.map_name,
        "map_size": metrics.map_size,
        "duration_label": metrics.to_dict()["duration_label"],
        "recorded_at": metrics.recorded_at,
        "recorded_at_label": _date_label(metrics.recorded_at),
        "recorded_at_source": metrics.recorded_at_source,
        "backend": metrics.backend,
        "body_complete": metrics.body_complete,
        "rated": metrics.rated,
        "players": [
            {
                "name": p.name,
                "civilization": p.civilization,
                "color_id": p.color_id,
                "color": _player_color_value(getattr(p, "color_name", None), p.color_id),
                "color_name": getattr(p, "color_name", None) or color_name(p.color_id),
                "team_id": p.team_id,
                "profile_id": p.profile_id,
                "result": p.result,
                "feudal": p.labels["feudal"],
                "castle": p.labels["castle"],
                "imperial": p.labels["imperial"],
            }
            for p in metrics.players
        ],
    }


def _preview_replay(replay: str) -> dict:
    try:
        metrics = _replay_metrics(replay)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    elo = _fetch_elo(metrics)
    return {"preview": _web_preview(metrics), "insights": _web_insights(metrics, elo)}


def _detect_habits_for_replay(replay: str, focus_player: str | None = None) -> dict:
    try:
        metrics = _replay_metrics(replay)
        _validate_focus(metrics, focus_player)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    try:
        return detect_habits(metrics, focus_player=focus_player)
    except Exception as exc:  # noqa: BLE001
        return {"error": _model_error(exc)}


def _clean_habits(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    habits = []
    seen = set()
    for item in raw:
        text = " ".join(str(item).split())[:_MAX_HABIT_LEN]
        key = text.lower()
        if not text or key in seen:
            continue
        habits.append(text)
        seen.add(key)
        if len(habits) >= _MAX_HABITS:
            break
    return habits


def _export_session(body: dict) -> dict:
    markdown = str(body.get("markdown", "")).strip()
    if not markdown:
        return {"error": "No session content to export."}
    raw_name = str(body.get("filename", "")).strip() or "aoe2coach-session.md"
    name = secure_filename(raw_name) or "aoe2coach-session.md"
    if not name.lower().endswith(".md"):
        name += ".md"
    out_dir = Path.cwd() / "reports" / "session-exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / name
    if out.exists():
        stem, suffix = out.stem, out.suffix
        idx = 2
        while out.exists():
            out = out_dir / f"{stem}-{idx}{suffix}"
            idx += 1
    out.write_text(markdown + "\n", encoding="utf-8")
    return {"path": str(out), "name": out.name}


def _practice_focus_block(habits: list[str], detected_habits: list[str] | None = None) -> str:
    detected_habits = detected_habits or []
    if not habits and not detected_habits:
        return ""
    blocks = []
    if habits:
        bullets = "\n".join(f"- {habit}" for habit in habits)
        blocks.append(
            "User-pinned practice focus for this review. Treat these as the player's "
            "current training goals: prioritize them when the replay evidence supports "
            "them, but do not invent evidence or ignore a bigger replay issue.\n"
            f"{bullets}"
        )
    if detected_habits:
        bullets = "\n".join(f"- {habit}" for habit in detected_habits)
        blocks.append(
            "Lightweight-model candidate habits for this replay. Treat these as "
            "hypotheses to verify against the replay facts, not as guaranteed truths.\n"
            f"{bullets}"
        )
    return "\n\n" + "\n\n".join(blocks)


def _open_session(
    replay: str,
    habits=None,
    focus_player: str | None = None,
    detected_habits=None,
    *,
    sessions: dict[str, _Session] | None = None,
) -> dict:
    try:
        metrics = _replay_metrics(replay)
        _validate_focus(metrics, focus_player)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

    elo = _fetch_elo(metrics, timeout=3.0) or None
    # Trends are skipped on open for speed; pinned and detected habits are retained.
    opening = build_opening_message(metrics, focus_player=focus_player, elo=elo, trends=None)
    opening += _practice_focus_block(_clean_habits(habits), _clean_habits(detected_habits))
    try:
        chat = CoachChat()
        result = chat.send(opening)
    except Exception as exc:  # noqa: BLE001
        return {"error": _model_error(exc)}
    session_id = uuid4().hex
    session = _Session(chat, str(replay), metrics, focus_player)
    session.transcript.append({"role": "assistant", "text": result.text, **result.to_dict()})
    if sessions is not None:
        sessions[session_id] = session
    return {
        "session_id": session_id,
        **_result_payload(result, "report"),
        "insights": _web_insights(metrics, elo),
    }


_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>aoe2coach</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
 :root{color-scheme:dark}
 *{box-sizing:border-box} body{margin:0;font:15px/1.55 system-ui,sans-serif;background:#15171c;color:#e6e6e6;height:100vh;display:flex;overflow:hidden}
 body.resizing{cursor:col-resize;user-select:none}
 #side{width:300px;min-width:220px;max-width:520px;border-right:1px solid #2b2f38;overflow:auto;padding:1rem;flex:0 0 auto}
 #side h1{font-size:1.1rem;margin:.2rem 0 .8rem}
 #side.drag{background:#1a2334}
 #drop{border:1.5px dashed #3a4150;border-radius:10px;padding:1rem;text-align:center;color:#9aa4b2;font-size:.82rem;margin-bottom:.8rem}
 #side.drag #drop{border-color:#3a6df0;color:#cdd3dc}
 #list{min-height:72px;max-height:45vh;overflow:auto}
 .rep{display:block;width:100%;text-align:left;background:#1c1f26;border:1px solid #2b2f38;color:#cdd3dc;padding:.5rem .6rem;border-radius:8px;margin:.3rem 0;cursor:pointer;font-size:.82rem;word-break:break-all}
 .rep:hover{border-color:#3a6df0} .rep.active{border-color:#3a6df0;background:#222838}
 #insights{margin-top:1rem;border-top:1px solid #2b2f38;padding-top:1rem}
 #insights h2{font-size:.78rem;text-transform:uppercase;letter-spacing:0;color:#9aa4b2;margin:.8rem 0 .35rem}
 #insights .mini{display:block;width:100%;border:1px solid #2b2f38;border-radius:8px;background:#0f1115}
 #insights .kv{font-size:.8rem;color:#cdd3dc;margin:.2rem 0}
 #insights .tiny{font-size:.74rem;color:#9aa4b2;margin:.18rem 0}
 #insights ol,#insights ul{margin:.25rem 0 .6rem;padding-left:1.1rem}
 #insights li{font-size:.78rem;margin:.18rem 0;color:#cdd3dc}
 .compareMeta{font-size:.74rem;color:#9aa4b2;margin:.1rem 0 .45rem}
 .h2h{width:100%;border-collapse:collapse;margin:.35rem 0 .9rem;table-layout:fixed}
 .h2h th,.h2h td{border-bottom:1px solid #2b2f38;padding:.38rem .28rem;text-align:left;vertical-align:top;font-size:.72rem;line-height:1.25;overflow-wrap:anywhere}
 .h2h th{color:#9aa4b2;font-size:.66rem;text-transform:uppercase;letter-spacing:0}
 .h2h th:first-child,.h2h td:first-child{width:34%;color:#e6e6e6;font-weight:650}
 .h2h .ok{color:#86efac;font-weight:750}.h2h .bad{color:#fecaca;font-weight:750}.h2h .near{color:#fde68a}.h2h .even{color:#cdd3dc}.h2h .na{color:#9aa4b2}
 .leftVResize{resize:vertical;overflow:auto}
 .mapwrap.leftVResize{height:220px;min-height:115px;max-height:60vh;overflow:hidden;display:flex;flex-direction:column}
 .mapwrap.leftVResize h2{margin-top:0;flex:0 0 auto}
 .mapwrap.leftVResize a{display:block;flex:1 1 auto;min-height:0;height:auto}
 .mapwrap.leftVResize .mini{height:100%;object-fit:contain}
 .timeline{height:330px;max-height:none;overflow:auto;border-top:1px solid #2b2f38;border-bottom:1px solid #2b2f38;padding:.25rem 0;min-height:105px}
 .tl{display:grid;grid-template-columns:2.6rem 3.6rem minmax(0,1fr);gap:.35rem;align-items:start;padding:.3rem 0;border-bottom:1px solid rgba(43,47,56,.55)}
 .tl:last-child{border-bottom:0}.tlTime{font-size:.72rem;color:#cdd3dc;font-weight:700}.tlTag{font-size:.62rem;text-transform:uppercase;letter-spacing:0;color:#9aa4b2;border:1px solid #3a4150;border-radius:6px;padding:.05rem .25rem;text-align:center}.tlText{font-size:.74rem;color:#cdd3dc;line-height:1.32}
 .tl.idle_tc .tlTag{color:#fde68a;border-color:#8a6d2f}.tl.battle .tlTag{color:#fecaca;border-color:#8a3434}.tl.age_up .tlTag{color:#86efac;border-color:#2a7a4e}
 .resize-h{width:6px;flex:0 0 6px;cursor:col-resize;background:#15171c}
 .resize-h:hover,.resize-h.dragging{background:#2d6cdf}
 #main{flex:1;display:flex;flex-direction:column;min-width:340px}
 #log{flex:1;overflow:auto;padding:1.5rem;max-width:980px;margin:0 auto;width:100%}
 .msg{margin:0 0 1rem;padding:.8rem 1rem;border-radius:10px}
 .you{background:#223;border:1px solid #2b3550;margin-left:3rem}
 .coach{background:#1c1f26;border:1px solid #2b2f38;margin-right:3rem}
 .coach h1,.coach h2,.coach h3{font-size:1.05rem;margin:.6rem 0 .3rem} .coach table{border-collapse:collapse;margin:.5rem 0}
 .coach td,.coach th{border:1px solid #2b2f38;padding:.25rem .5rem;font-size:.9rem} .coach code{background:#0f1115;padding:.1rem .3rem;border-radius:4px}
 .previewHead{font-weight:700;margin-bottom:.55rem}.playerGrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:.6rem;margin-top:.7rem}
 .playerPick{background:#171a20;border:1px solid #2b2f38;border-left:4px solid var(--pc,#2b2f38);border-radius:8px;padding:.7rem}.playerPick.won{box-shadow:inset 0 0 0 1px rgba(71,200,117,.45)}.playerPick.lost{opacity:.92}.playerPick strong{display:flex;align-items:center;gap:.35rem;font-size:.95rem}.playerPick .meta{color:#9aa4b2;font-size:.82rem;margin:.2rem 0 .55rem}
 .playerName{color:var(--pc,#cdd3dc);font-weight:750}
 .resultBadge{margin-left:auto;border-radius:999px;padding:.12rem .45rem;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0}
 .resultBadge.won{background:#194f31;color:#86efac;border:1px solid #2a7a4e}.resultBadge.lost{background:#552020;color:#fecaca;border:1px solid #8a3434}.resultBadge.unknown{background:#303642;color:#cdd3dc;border:1px solid #475062}
 .focusBtn{background:#2d6cdf;color:#fff;border:0;border-radius:8px;padding:.45rem .65rem;cursor:pointer;font:inherit;font-size:.82rem}
 .playerPick.selected{border-color:#3a6df0;background:#222838}.focusBtn.selected{background:#263142;border:1px solid #3a4150}
 .responseMeta{border-top:1px solid #2b2f38;padding-top:.55rem;margin-top:.8rem;font-size:.75rem;color:#9aa4b2}
 .plain,.you,.err{white-space:pre-wrap}
 .muted{color:#9aa4b2} .err{color:#ff7676}
 #bar{border-top:1px solid #2b2f38;padding:1rem;display:flex;gap:.6rem;max-width:980px;margin:0 auto;width:100%;align-items:flex-end}
 #q{flex:1;background:#0f1115;border:1px solid #2b2f38;color:#e6e6e6;border-radius:8px;padding:.6rem .8rem;font:inherit;min-height:42px;max-height:180px;resize:vertical}
 button.send{background:#2d6cdf;color:#fff;border:0;border-radius:8px;padding:0 1.1rem;cursor:pointer}
 button:disabled{opacity:.5;cursor:default}
 #practice{width:320px;min-width:240px;max-width:520px;border-left:1px solid #2b2f38;overflow:auto;padding:1rem;flex:0 0 auto}
 #practice h1{font-size:1.05rem;margin:.2rem 0 .8rem}
 #practice h2{font-size:.78rem;text-transform:uppercase;letter-spacing:0;color:#9aa4b2;margin:1rem 0 .45rem}
 .modelNote{font-size:.72rem;color:#9aa4b2;margin:.25rem 0 .55rem}
 #habitForm{display:flex;gap:.45rem;margin:.4rem 0 .8rem}
 #habitInput{flex:1;min-width:0;background:#0f1115;border:1px solid #2b2f38;color:#e6e6e6;border-radius:8px;padding:.5rem .6rem;font:inherit;font-size:.82rem}
 .miniBtn{background:#263142;border:1px solid #3a4150;color:#e6e6e6;border-radius:8px;padding:.45rem .65rem;cursor:pointer;font-size:.78rem}
 .miniBtn.primary{background:#2d6cdf;border-color:#2d6cdf;color:#fff}
 .miniBtn:hover{border-color:#2d6cdf}
 .habit{border:1px solid #2b2f38;background:#1c1f26;border-radius:8px;padding:.55rem .6rem;margin:.45rem 0}
 .habit strong{display:block;font-size:.82rem;line-height:1.3}
 .habit .detail{font-size:.74rem;color:#9aa4b2;margin-top:.25rem}
 .habit .actions{display:flex;gap:.35rem;margin-top:.45rem}
 .empty{font-size:.8rem;color:#9aa4b2;border:1px dashed #3a4150;border-radius:8px;padding:.7rem}
 .practiceHead{display:flex;align-items:center;justify-content:space-between;gap:.6rem;margin:.2rem 0 .8rem}
 .practiceHead h1{margin:0}
 @media(max-width:900px){ #practice{display:none}.resize-h.right{display:none}#side{width:260px} }
</style></head><body>
<div id="side">
  <h1>🏰 aoe2coach</h1>
  <div id="drop" role="button" tabindex="0">⬇ Drag a <code>.aoe2record</code> here<br><span style="font-size:.75rem">or click to upload</span></div>
  <input id="file" type="file" accept=".aoe2record" hidden>
  <div id="list" class="leftVResize" data-vresize-key="list">{{ replays|safe }}</div>
  <div id="insights"></div>
</div>
<div class="resize-h left" id="leftResize" title="Resize replay panel"></div>
<div id="main">
  <div id="log"><div class="msg coach muted">Drag in a replay or pick one on the left. I'll preview it first; choose a player when you're ready to spend tokens on coaching.</div></div>
  <div id="bar"><a id="downloadConversation" hidden>Download conversation</a><textarea id="q" placeholder="Pick a replay first…" disabled rows="1"></textarea><button class="send" id="send" disabled>Send</button></div>
</div>
<div class="resize-h right" id="rightResize" title="Resize practice panel"></div>
<div id="practice">
  <div class="practiceHead"><h1>Practice Focus</h1><button class="miniBtn" id="exportSession" disabled>Export session</button></div>
  <div id="practiceBody"></div>
</div>
<script>
let current=null, sessionId=null, pending=false, currentInsights=null, currentInsightsPath=null, currentPreview=null, currentFocus=null, sessionOpen=false;
let detectedLoading=false, detectedError='', detectedModel='', detectedFocus=null, detectRequestId=0, analyzing=false;
const side=document.getElementById('side'), list=document.getElementById('list'), leftResize=document.getElementById('leftResize'), rightResize=document.getElementById('rightResize');
const log=document.getElementById('log'), q=document.getElementById('q'), send=document.getElementById('send'), insights=document.getElementById('insights');
const practice=document.getElementById('practice'), practiceBody=document.getElementById('practiceBody'), exportSession=document.getElementById('exportSession');
const fileInput=document.getElementById('file');
const HABIT_STORE='aoe2coach.practiceFocus.v1';
function esc(t){ return String(t??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
let conversationLog=[];
function renderMarkdown(node, text){
  if(typeof marked==='undefined'){node.textContent=text;node.classList.add('plain');return;}
  const source=document.createElement('template');
  try{source.innerHTML=marked.parse(text);}catch(e){node.textContent=text;return;}
  const allowed=new Set('P BR HR H1 H2 H3 H4 H5 H6 STRONG EM DEL UL OL LI BLOCKQUOTE PRE CODE TABLE THEAD TBODY TR TH TD A'.split(' '));
  function copy(from,to){
    for(const child of from.childNodes){
      if(child.nodeType===Node.TEXT_NODE){to.appendChild(document.createTextNode(child.textContent));continue;}
      if(child.nodeType!==Node.ELEMENT_NODE)continue;
      if(!allowed.has(child.tagName)){to.appendChild(document.createTextNode(child.outerHTML));continue;}
      const clean=document.createElement(child.tagName.toLowerCase());
      if(child.tagName==='A'){
        try{const url=new URL(child.getAttribute('href'));if(['https:','http:','mailto:'].includes(url.protocol)){clean.href=url.href;clean.rel='noopener noreferrer';clean.target='_blank';}}catch(e){}
      }
      copy(child,clean);to.appendChild(clean);
    }
  }
  copy(source.content,node);
}
function token(value){return Number.isInteger(value)?value.toLocaleString():'unavailable';}
function metadataLabel(meta){
  return (meta.model||'Model unavailable')+' · Input tokens: '+token(meta.input_tokens)+' · Output tokens: '+token(meta.output_tokens);
}
function add(role, text, isHtml, exportText, meta){
  const d=document.createElement('div'); d.className='msg '+role;
  if(isHtml) d.innerHTML=text; // Only locally built preview markup with escaped labels.
  else if(role==='coach') renderMarkdown(d,String(text??''));
  else d.textContent=text;
  if(meta){const m=document.createElement('div');m.className='responseMeta';m.textContent=metadataLabel(meta);d.appendChild(m);}
  log.appendChild(d); log.scrollTop=log.scrollHeight;
  if(exportText!==false && !String(role).includes('muted')) conversationLog.push({role:String(role).includes('you')?'You':(String(role).includes('err')?'Request failed':'Coach'), text:String(exportText??text??''), meta});
  return d;
}
function busy(b){
  pending=b; send.disabled=b||!sessionOpen; q.disabled=b||!sessionOpen;
  const download=document.getElementById('downloadConversation');download.hidden=!sessionId;download.href=sessionId?'/api/export/'+encodeURIComponent(sessionId):'';
  document.querySelectorAll('.rep,[data-analyze]').forEach(x=>x.disabled=b);
  fileInput.disabled=b; syncFocusButtons();
}
async function responseJSON(response){
  try{return await response.json();}catch(e){throw new Error('The server returned an unreadable response. Try again.');}
}
async function postJSON(url, body){
  return responseJSON(await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));
}

function activate(el){ document.querySelectorAll('.rep').forEach(x=>x.classList.remove('active')); if(el) el.classList.add('active'); }
function loadHabits(){ try{ const v=JSON.parse(localStorage.getItem(HABIT_STORE)||'[]'); return Array.isArray(v)?v.filter(Boolean).slice(0,12):[]; }catch(e){ return []; } }
let pinnedHabits=loadHabits();
function saveHabits(){ localStorage.setItem(HABIT_STORE, JSON.stringify(pinnedHabits)); }
function cleanHabit(text){ return String(text||'').replace(/\\s+/g,' ').trim().slice(0,160); }
function practiceHabits(){ return pinnedHabits.map(cleanHabit).filter(Boolean); }
function detectedHabitLabels(){ return detectedHabits().map(h=>cleanHabit(h.label)).filter(Boolean); }
function addHabit(text){ const h=cleanHabit(text); if(!h) return; if(!pinnedHabits.some(x=>x.toLowerCase()===h.toLowerCase())) pinnedHabits.push(h); pinnedHabits=pinnedHabits.slice(0,12); saveHabits(); renderPractice(); }
function removeHabit(index){ pinnedHabits.splice(index,1); saveHabits(); renderPractice(); }
function detectedHabits(){ return ((currentInsights||{}).detected_habits||[]).map((h,i)=>({...h,index:i})); }
function isPinned(text){ return pinnedHabits.some(x=>x.toLowerCase()===cleanHabit(text).toLowerCase()); }
function safeColor(color){ return /^#[0-9a-fA-F]{6}$/.test(color||'')?color:'#cdd3dc'; }
function playerSpan(name,color){ return `<span class="playerName" style="--pc:${safeColor(color)}">${esc(name||'Player')}</span>`; }
function comparisonPlayers(){ return (((currentInsights||{}).comparison||{}).players)||[]; }
function colorForPlayer(name){
  const row=comparisonPlayers().find(p=>p.name===name);
  return row?row.color:null;
}
function colorizePlayers(text, players){
  let rest=String(text||''), out='';
  const names=(players||[]).map(p=>p.name).filter(Boolean).sort((a,b)=>b.length-a.length);
  while(rest.length){
    let hit=null;
    for(const name of names){
      const index=rest.indexOf(name);
      if(index>=0 && (!hit || index<hit.index || (index===hit.index && name.length>hit.name.length))) hit={name,index};
    }
    if(!hit){ out+=esc(rest); break; }
    out+=esc(rest.slice(0,hit.index))+playerSpan(hit.name,colorForPlayer(hit.name));
    rest=rest.slice(hit.index+hit.name.length);
  }
  return out;
}
function wireLeftVerticalResizers(){
  document.querySelectorAll('.leftVResize[data-vresize-key]').forEach(el=>{
    if(el.dataset.vresizeReady) return;
    const storageId='aoe2coach.leftVertical.'+el.dataset.vresizeKey;
    const stored=Number(localStorage.getItem(storageId)||0);
    if(stored>0) el.style.height=Math.max(72,Math.min(700,stored))+'px';
    else if(el.id==='list') el.style.height=Math.max(72,Math.min(180,el.scrollHeight+8))+'px';
    el.dataset.vresizeReady='1';
    if(window.ResizeObserver){
      const observer=new ResizeObserver(entries=>{
        const height=Math.round(entries[0].contentRect.height);
        if(height>0) localStorage.setItem(storageId,String(height));
      });
      observer.observe(el);
    }
  });
}
function syncFocusButtons(){
  document.querySelectorAll('[data-focus]').forEach(btn=>{
    const selected=currentFocus&&btn.dataset.focus===currentFocus;
    btn.textContent=selected?'Selected':'Select player';
    btn.disabled=(!!selected&&!detectedError)||analyzing||pending;
    btn.classList.toggle('selected',!!selected);
    const card=btn.closest('.playerPick'); if(card) card.classList.toggle('selected',!!selected);
  });
}
function renderPractice(){
  if(exportSession) exportSession.disabled=!hasExportableSession();
  const selected=currentFocus?`<div class="habit"><strong>Selected: ${colorizePlayers(currentFocus,comparisonPlayers())}</strong><div class="detail">${detectedLoading?'Detecting habits first…':'Review or pin habits, then run full analysis using your analysis model.'}</div><div class="actions"><button class="miniBtn primary" data-analyze ${detectedLoading||analyzing||pending?'disabled':''}>${analyzing?'Analyzing…':'Run full analysis using analysis model'}</button></div></div>`:'';
  const pinned=pinnedHabits.length?pinnedHabits.map((h,i)=>`<div class="habit"><strong>${esc(h)}</strong><div class="actions"><button class="miniBtn" data-remove="${i}">Remove</button></div></div>`).join(''):'<div class="empty">Add 1-3 habits you want the coach to watch for, or pin detected habits after opening a replay.</div>';
  let detected='';
  const rows=detectedHabits();
  if(detectedLoading) detected='<div class="empty">Detecting candidate habits with your detection model…</div>';
  else if(detectedError) detected=`<div class="empty">Detected habits unavailable: ${esc(detectedError)}</div>`;
  else if(rows.length) detected=rows.map(h=>{
    const pinned=isPinned(h.label);
    const who=h.player?`<div class="detail">${colorizePlayers(h.player,comparisonPlayers())} · ${esc(h.priority||'medium')}</div>`:'';
    return `<div class="habit"><strong>${esc(h.label)}</strong>${who}<div class="detail">${esc(h.detail||'')}</div><div class="actions"><button class="miniBtn" data-pin="${h.index}" ${pinned?'disabled':''}>${pinned?'Pinned':'Pin habit'}</button></div></div>`;
  }).join('');
  else detected=currentFocus?'<div class="empty">No detected habits yet for the selected player.</div>':'<div class="empty">Choose a player to ask your detection model for detected habits.</div>';
  const note=currentFocus?`<div class="modelNote">Detection model: ${esc(detectedModel||'configured model')}</div>`:'';
  practiceBody.innerHTML=`${selected}<h2>Pinned</h2><form id="habitForm"><input id="habitInput" maxlength="160" placeholder="e.g. Stop floating wood"><button class="miniBtn">Add</button></form>${pinned}<h2>Detected</h2>${note}${detected}`;
  syncFocusButtons();
}
function playerHead(p){
  const rating=p.rating?`<div class="compareMeta">${esc(p.rating)} ELO</div>`:'';
  return `${playerSpan(p.name||'Player',p.color)}${rating}`;
}
function renderComparison(compare){
  const players=(compare&&compare.players)||[];
  const rows=(compare&&compare.rows)||[];
  if(!players.length||!rows.length) return '';
  const heads=players.map(p=>`<th>${playerHead(p)}</th>`).join('');
  const body=rows.map(r=>{
    const cells=players.map((_,i)=>`<td class="${esc((r.classes||[])[i]||'na')}">${esc((r.values||[])[i]||'—')}</td>`).join('');
    return `<tr><td>${esc(r.metric)}</td>${cells}</tr>`;
  }).join('');
  return `<h2>Fundamentals</h2><table class="h2h"><thead><tr><th>Metric</th>${heads}</tr></thead><tbody>${body}</tbody></table>`;
}
function timelineTag(type){
  return ({age_up:'Age',building:'Build',idle_tc:'TC',battle:'Fight'}[type]||'Note');
}
function renderTimeline(events){
  const players=comparisonPlayers();
  const rows=(events||[]).map(e=>`<div class="tl ${esc(e.type||'note')}"><div class="tlTime">${esc(e.at)}</div><div class="tlTag">${esc(timelineTag(e.type))}</div><div class="tlText">${colorizePlayers(e.label,players)}</div></div>`).join('');
  return `<h2>Timeline</h2><div class="timeline leftVResize" data-vresize-key="timeline">${rows||'<div class="tiny">No timeline events available.</div>'}</div>`;
}
function renderInsights(data, path){
  const priorHabits=((currentInsights||{}).detected_habits||[]);
  const sameReplay=path&&currentInsightsPath&&path===currentInsightsPath;
  if(data&&sameReplay&&priorHabits.length&&(!(data.detected_habits||[]).length)) data={...data,detected_habits:priorHabits};
  currentInsights=data||null;
  currentInsightsPath=path||null;
  renderPractice();
  insights.innerHTML='';
  if(!data||!path) return;
  const mapUrl='/api/minimap?replay='+encodeURIComponent(path);
  insights.innerHTML=`<div class="mapwrap leftVResize" data-vresize-key="map"><h2>Minimap</h2><a href="${mapUrl}" target="_blank" rel="noreferrer"><img class="mini" src="${mapUrl}" alt="Replay minimap"></a></div>${renderComparison(data.comparison)}${renderTimeline(data.timeline)}`;
  const img=insights.querySelector('img'); if(img) img.onerror=()=>{img.closest('.mapwrap').innerHTML='<h2>Minimap</h2><div class="tiny">Unavailable for this replay/backend.</div>';};
  wireLeftVerticalResizers();
}
async function loadDetectedHabits(focusPlayer){
  if(!current||!currentInsights||!focusPlayer) return;
  const requestId=++detectRequestId;
  detectedLoading=true; detectedError='';
  if(detectedFocus!==focusPlayer){ currentInsights.detected_habits=[]; detectedModel=''; }
  detectedFocus=focusPlayer; renderPractice();
  try{
    const res=await postJSON('/api/detect-habits',{replay:current,focus_player:focusPlayer});
    if(requestId!==detectRequestId) return;
    if(res.error) detectedError=res.error;
    else { currentInsights.detected_habits=res.habits||[]; detectedModel=res.model||''; }
  }catch(e){if(requestId===detectRequestId) detectedError='Could not reach the server. Select the player again to retry.';}
  finally{if(requestId===detectRequestId){detectedLoading=false;renderPractice();}}
}

function previewHtml(preview){
  const map=[preview.map_name, preview.map_size].filter(Boolean).join(' · ');
  const rated=preview.rated?'ranked':'unranked';
  const date=preview.recorded_at_label?` · ${esc(preview.recorded_at_label)}${preview.recorded_at_source==='file_modified'?' file date':''}`:'';
  const players=(preview.players||[]).map(p=>{
    const color=safeColor(p.color);
    const result=(p.result||'unknown').toLowerCase();
    const resultClass=result==='won'?'won':(result==='lost'?'lost':'unknown');
    const resultLabel=result==='won'?'Won':(result==='lost'?'Lost':'Unknown');
    return `<div class="playerPick ${resultClass}" style="--pc:${color}"><strong>${playerSpan(p.name||'Unknown',color)}<span class="resultBadge ${resultClass}">${resultLabel}</span></strong><div class="meta">${esc(p.civilization)}<br>Feudal ${esc(p.feudal)} · Castle ${esc(p.castle)}</div><button class="focusBtn" data-focus="${esc(p.name)}">Select player</button></div>`;
  }).join('');
  return `<div class="previewHead">${esc(map||'Unknown map')}${date} · ${esc(preview.duration_label)} · ${rated} · parser: ${esc(preview.backend)}</div><div class="muted">Previewing uses no coaching model. Pick a player to run habit detection with your configured detection model.</div><div class="playerGrid">${players}</div>`;
}
function mdClean(value){ return String(value??'—').replace(/\\r\\n/g,'\\n').replace(/[|]/g,'/').trim()||'—'; }
function bulletList(values){ return values.length?values.map(v=>`- ${mdClean(v)}`).join('\\n'):'- None'; }
function activeReplayName(){
  return document.querySelector('.rep.active')?.textContent?.trim() || (currentPreview&&currentPreview.source_file) || (current?String(current).split(/[\\\\/]/).pop():'aoe2coach-session');
}
function previewMarkdown(preview){
  if(!preview) return '';
  const players=(preview.players||[]).map(p=>`- ${mdClean(p.name)} (${mdClean(p.civilization)}): ${mdClean(p.result)}; Feudal ${mdClean(p.feudal)}, Castle ${mdClean(p.castle)}, Imperial ${mdClean(p.imperial)}`).join('\\n')||'- None';
  return [
    '## Replay',
    `- File: ${mdClean(preview.source_file||current)}`,
    `- Map: ${mdClean([preview.map_name,preview.map_size].filter(Boolean).join(' / '))}`,
    `- Duration: ${mdClean(preview.duration_label)}`,
    `- Recorded: ${mdClean(preview.recorded_at_label||preview.recorded_at)}`,
    `- Rated: ${preview.rated?'yes':'no'}`,
    `- Parser: ${mdClean(preview.backend)}${preview.body_complete===false?' (partial body scan)':''}`,
    '',
    '## Players',
    players,
  ].join('\\n');
}
function habitsMarkdown(){
  const detected=detectedHabits();
  const detectedLines=detected.length?detected.map(h=>`- ${mdClean(h.label)}${h.player?` (${mdClean(h.player)})`:''}${h.priority?` [${mdClean(h.priority)}]`:''}${h.detail?`: ${mdClean(h.detail)}`:''}`):[];
  return [
    '## Practice Focus',
    `- Selected player: ${mdClean(currentFocus||'None')}`,
    '',
    '### Pinned Habits',
    bulletList(practiceHabits()),
    '',
    '### Detected Habits',
    bulletList(detectedLines.map(x=>x.slice(2))),
  ].join('\\n');
}
function insightsMarkdown(){
  const data=currentInsights||{};
  const compare=(data.comparison||{}), players=compare.players||[], rows=compare.rows||[];
  const out=['## Replay Context'];
  if(players.length&&rows.length){
    out.push('', '### Fundamentals');
    out.push(`| Metric | ${players.map(p=>mdClean(p.name)).join(' | ')} |`);
    out.push(`| --- | ${players.map(()=> '---').join(' | ')} |`);
    rows.forEach(r=>out.push(`| ${mdClean(r.metric)} | ${(r.values||[]).map(mdClean).join(' | ')} |`));
  }
  const events=data.timeline||[];
  out.push('', '### Timeline');
  if(events.length) events.forEach(e=>out.push(`- ${mdClean(e.at)} [${mdClean(timelineTag(e.type))}] ${mdClean(e.label)}`));
  else out.push('- None');
  return out.join('\\n');
}
function discussionMarkdown(){
  const rows=conversationLog.filter(row=>row.text.trim());
  if(!rows.length){
    const visible=(log?.innerText||'').trim();
    return visible?'## Discussion\\n\\n'+visible:'## Discussion\\n- No discussion yet.';
  }
  return '## Discussion\\n\\n'+rows.map(row=>`### ${row.role}\\n\\n${row.text.trim()}${row.meta?'\\n\\n'+metadataLabel(row.meta):''}`).join('\\n\\n');
}
function visibleFallbackMarkdown(){
  return [
    '# aoe2coach Session Export',
    `Exported: ${new Date().toLocaleString()}`,
    `Replay: ${mdClean(activeReplayName())}`,
    '',
    '## Discussion',
    mdClean(log?.innerText||'No discussion yet.'),
    '',
    '## Replay Context',
    mdClean(insights?.innerText||'None'),
    '',
    '## Practice Focus',
    mdClean(practice?.innerText||'None'),
    '',
  ].join('\\n');
}
function exportFilename(){
  const base=activeReplayName().split(/[\\\\/]/).pop().replace(/\\.aoe2record$/i,'');
  const stamp=new Date().toISOString().slice(0,19).replace(/[:T]/g,'-');
  return `${base||'aoe2coach-session'}-${stamp}.md`;
}
function exportMarkdown(){
  if(!currentPreview&&!currentInsights&&!conversationLog.length) return visibleFallbackMarkdown();
  return [
    '# aoe2coach Session Export',
    `Exported: ${new Date().toLocaleString()}`,
    '',
    previewMarkdown(currentPreview),
    '',
    habitsMarkdown(),
    '',
    insightsMarkdown(),
    '',
    discussionMarkdown(),
    '',
  ].join('\\n');
}
function downloadText(filename,text){
  const blob=new Blob([text],{type:'text/markdown;charset=utf-8'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a'); a.href=url; a.download=filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function hasExportableSession(){
  const visible=(log?.innerText||'').trim();
  const initial=visible.startsWith('Drag in a replay or pick one on the left.');
  return !!(current||currentPreview||currentInsights||conversationLog.length||document.querySelector('.rep.active')||(visible&&!initial));
}
async function exportCurrentSession(){
  if(!hasExportableSession()) return;
  const filename=exportFilename();
  const markdown=exportMarkdown();
  let saved='';
  try{
    const res=await postJSON('/api/export-session',{filename,markdown});
    if(res&&res.path) saved=res.path;
  }catch(e){ saved=''; }
  downloadText(filename,markdown);
  add('coach muted',saved?`Exported session. Saved to ${saved}`:'Exported session download.',false,false);
}
function showPreview(res){
  sessionOpen=false; sessionId=null; currentFocus=null;
  if(res.error){ add('coach err','⚠️ '+res.error); current=null; currentPreview=null; q.placeholder='Pick a replay first…'; renderInsights(null,null); return; }
  currentPreview=res.preview; add('coach', previewHtml(res.preview), true, false); q.placeholder='Choose a player to detect habits…'; renderInsights(res.insights,current);
}
function showReport(res){
  if(res.error){ add('coach err','⚠️ '+res.error); sessionOpen=false; sessionId=null; q.placeholder='Choose a player to start coaching…'; }
  else { sessionId=res.session_id; sessionOpen=true; add('coach',res.report,false,undefined,res); q.placeholder=`Ask a follow-up for ${currentFocus||'this player'}…`; renderInsights(res.insights,current); }
}
async function selectFocusPlayer(focusPlayer){
  if(!current||!focusPlayer||pending) return; currentFocus=focusPlayer; sessionOpen=false; sessionId=null; q.value=''; q.placeholder=`Review habits for ${focusPlayer}, then run full analysis using your analysis model…`; busy(false); renderPractice(); loadDetectedHabits(focusPlayer);
}
async function startCoaching(){
  if(!current||!currentFocus||analyzing||pending||detectedLoading) return;
  sessionOpen=false; sessionId=null; analyzing=true; busy(true); renderPractice();
  const wait=add('coach muted',`Running full analysis for ${currentFocus} using your analysis model…`,false,false);
  try{showReport(await postJSON('/api/open',{replay:current,focus_player:currentFocus,habits:practiceHabits(),detected_habits:detectedHabitLabels()}));}
  catch(e){add('coach err','Could not reach the server. Try full analysis again.');}
  finally{wait.remove();analyzing=false;busy(false);renderPractice();if(sessionOpen)q.focus();}
}
function resetReplay(){
  sessionOpen=false;sessionId=null;currentPreview=null;log.innerHTML='';insights.innerHTML='';q.value='';conversationLog=[];
  currentInsights=null;currentInsightsPath=null;currentFocus=null;detectedLoading=false;detectedError='';detectedModel='';detectedFocus=null;++detectRequestId;busy(true);renderPractice();
}
async function openReplay(el){
  if(pending)return;activate(el);current=el.dataset.path;resetReplay();
  const wait=add('coach muted','Reading replay facts…',false,false);
  try{showPreview(await postJSON('/api/preview',{replay:current}));}
  catch(e){add('coach err','Could not reach the server. Select the replay again to retry.');}
  finally{wait.remove();busy(false);renderPractice();}
}
function wire(el){ el.onclick=()=>openReplay(el); }
document.querySelectorAll('.rep').forEach(wire);
async function upload(file){
  if(pending)return;
  if(!file.name.toLowerCase().endsWith('.aoe2record')){add('coach err','Choose a .aoe2record file.');return;}
  activate(null);current=null;resetReplay();
  const wait=add('coach muted','Uploading & previewing '+file.name+'…',false,false);
  try{
    const fd=new FormData();fd.append('file',file);fd.append('habits',JSON.stringify(practiceHabits()));
    const res=await responseJSON(await fetch('/api/upload',{method:'POST',body:fd}));
    if(res.path&&!res.error){const b=document.createElement('button');b.className='rep';b.dataset.path=res.path;b.textContent=res.name;wire(b);list.insertBefore(b,list.firstChild);activate(b);current=res.path;}
    showPreview(res);
  }catch(e){add('coach err','Upload failed. Try uploading the replay again.');}
  finally{wait.remove();busy(false);fileInput.value='';renderPractice();}
}
['dragover','dragenter'].forEach(ev=>side.addEventListener(ev,e=>{e.preventDefault();if(!pending)side.classList.add('drag');}));
['dragleave','drop'].forEach(ev=>side.addEventListener(ev,e=>{e.preventDefault();side.classList.remove('drag');}));
side.addEventListener('drop',e=>{const f=e.dataTransfer.files[0];if(f)upload(f);});
document.getElementById('drop').onclick=()=>{if(!pending)fileInput.click();};
document.getElementById('drop').onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();if(!pending)fileInput.click();}};
fileInput.onchange=()=>{if(fileInput.files[0])upload(fileInput.files[0]);};
async function ask(){
  const message=q.value.trim();if(!message||!sessionId||!sessionOpen||pending)return;
  add('you',message);q.value='';busy(true);const wait=add('coach muted','…',false,false);
  try{
    const res=await postJSON('/api/chat',{session_id:sessionId,message,habits:practiceHabits(),detected_habits:detectedHabitLabels()});
    add(res.error?'coach err':'coach',res.error?('⚠️ '+res.error):res.reply,false,undefined,res.error?null:res);
    if(res.error)q.value=message;
  }catch(e){q.value=message;add('coach err','Connection interrupted. Your message may have reached the server. Check the conversation download before retrying.');}
  finally{wait.remove();busy(false);q.focus();renderPractice();}
}

send.onclick=ask; q.addEventListener('keydown',e=>{ if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask();} });
exportSession.onclick=exportCurrentSession;
log.addEventListener('click',e=>{ const btn=e.target.closest('[data-focus]'); if(btn) selectFocusPlayer(btn.dataset.focus); });
q.addEventListener('input',()=>{ q.style.height='auto'; q.style.height=Math.min(q.scrollHeight,180)+'px'; });
practice.addEventListener('click',e=>{
  const rem=e.target.closest('[data-remove]'); if(rem){ removeHabit(Number(rem.dataset.remove)); return; }
  const pin=e.target.closest('[data-pin]'); if(pin){ const h=detectedHabits()[Number(pin.dataset.pin)]; if(h) addHabit(h.label); }
  const analyze=e.target.closest('[data-analyze]'); if(analyze) startCoaching();
});
practice.addEventListener('submit',e=>{ e.preventDefault(); const input=document.getElementById('habitInput'); addHabit(input.value); input.value=''; input.focus(); });
function storedWidth(el,key,fallback){ const v=Number(localStorage.getItem(key)||fallback); el.style.width=Math.max(220,Math.min(560,v))+'px'; }
function initResize(handle,panel,key,mode){
  storedWidth(panel,key,panel.getBoundingClientRect().width);
  handle.addEventListener('mousedown',e=>{
    e.preventDefault(); const startX=e.clientX, startW=panel.getBoundingClientRect().width; document.body.classList.add('resizing'); handle.classList.add('dragging');
    function move(ev){ const dx=ev.clientX-startX; const raw=mode==='left'?startW+dx:startW-dx; const w=Math.max(220,Math.min(560,raw)); panel.style.width=w+'px'; localStorage.setItem(key,String(Math.round(w))); }
    function up(){ document.removeEventListener('mousemove',move); document.removeEventListener('mouseup',up); document.body.classList.remove('resizing'); handle.classList.remove('dragging'); }
    document.addEventListener('mousemove',move); document.addEventListener('mouseup',up);
  });
}
initResize(leftResize,side,'aoe2coach.leftWidth','left');
initResize(rightResize,practice,'aoe2coach.rightWidth','right');
renderPractice();
wireLeftVerticalResizers();
</script></body></html>"""


def create_app() -> Flask:
    app = Flask(__name__)
    sessions: dict[str, _Session] = {}

    def body() -> dict:
        value = request.get_json(silent=True)
        return value if isinstance(value, dict) else {}

    @app.route("/")
    def index():
        reps = _listed_replays()
        if reps:
            items = "".join(
                f'<button class="rep" data-path="{html.escape(str(p))}">{html.escape(p.name[:60])}</button>'
                for p in reps
            )
        else:
            items = '<div class="muted" style="font-size:.8rem">No replays in this folder yet — drag one in above.</div>'
        return render_template_string(_PAGE, replays=items)

    @app.route("/api/preview", methods=["POST"])
    def api_preview():
        return _preview_replay(body().get("replay", ""))

    @app.route("/api/detect-habits", methods=["POST"])
    def api_detect_habits():
        data = body()
        return _detect_habits_for_replay(data.get("replay", ""), data.get("focus_player"))

    @app.route("/api/open", methods=["POST"])
    def api_open():
        data = body()
        return _open_session(
            data.get("replay", ""),
            data.get("habits", []),
            focus_player=data.get("focus_player"),
            detected_habits=data.get("detected_habits", []),
            sessions=sessions,
        )

    @app.route("/api/upload", methods=["POST"])
    def api_upload():
        f = request.files.get("file")
        if f is None or not f.filename:
            return {"error": "No file uploaded."}
        name = secure_filename(f.filename)
        if not name or Path(name).suffix.lower() != ".aoe2record":
            return {"error": "Choose a .aoe2record file."}
        dest = _UPLOAD_DIR / uuid4().hex / name
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            f.save(dest)
            preview = _preview_replay(str(dest))
            if "error" in preview:
                dest.unlink(missing_ok=True)
                return preview
            try:
                habits = json.loads(request.form.get("habits", "[]"))
            except json.JSONDecodeError:
                habits = []
            return {**preview, "path": str(dest), "name": name, "habits": _clean_habits(habits)}
        except OSError:
            dest.unlink(missing_ok=True)
            return {
                "error": "Could not save this upload. Check available disk space and try again."
            }

    @app.route("/api/export-session", methods=["POST"])
    def api_export_session():
        return _export_session(body())

    @app.route("/api/minimap")
    def api_minimap():
        replay = str(request.args.get("replay", ""))
        if not replay:
            return {"error": "No replay provided."}, 400
        try:
            from .minimap import render_minimap

            stem = secure_filename(Path(replay).stem) or "replay"
            out = _UPLOAD_DIR / f"{stem[:80]}-{uuid4().hex}.minimap.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            render_minimap(replay, out)
            return send_file(out, mimetype="image/png", max_age=0)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}, 404

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        data = body()
        session_id = data.get("session_id")
        session = sessions.get(session_id) if isinstance(session_id, str) else None
        if session_id is None:
            # Compatibility for replay-only clients is safe only with one open session.
            matches = [s for s in sessions.values() if s.replay == data.get("replay")]
            if len(matches) > 1:
                return {
                    "error": "Multiple sessions use this replay. Send the session_id from /api/open."
                }
            session = matches[0] if matches else None
        if session is None:
            return {"error": "Open a replay first."}
        message = data.get("message")
        if not isinstance(message, str) or not message.strip():
            return {"error": "Enter a message first."}
        if not session.lock.acquire(blocking=False):
            return {
                "error": "A reply is still being generated. Wait before sending another message."
            }
        try:
            session.transcript.append({"role": "user", "text": message})
            focus = _practice_focus_block(
                _clean_habits(data.get("habits", [])),
                _clean_habits(data.get("detected_habits", [])),
            )
            prompt = f"{focus}\n\nPlayer message:\n{message}" if focus else message
            result = session.chat.send(prompt)
            session.transcript.append(
                {"role": "assistant", "text": result.text, **result.to_dict()}
            )
            return _result_payload(result, "reply")
        except Exception as exc:  # noqa: BLE001
            error = _model_error(exc)
            session.transcript.append({"role": "error", "text": error})
            return {"error": error}
        finally:
            session.lock.release()

    @app.route("/api/export/<session_id>")
    def api_export(session_id: str):
        session = sessions.get(session_id)
        if session is None:
            return {"error": "Open a replay first."}, 404
        if not session.lock.acquire(blocking=False):
            return {"error": "Wait for the current reply before downloading."}, 409
        try:
            markdown = build_chat_export(
                replay_name=Path(session.replay).name,
                map_name=session.metrics.map_name,
                duration_label=session.metrics.to_dict()["duration_label"],
                players=_web_preview(session.metrics)["players"],
                focus_player=session.focus_player,
                messages=session.transcript,
            )
        finally:
            session.lock.release()
        name = secure_filename(Path(session.replay).stem) or "replay"
        return Response(
            markdown,
            mimetype="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{name}.conversation.md"'},
        )

    return app


def main(host: str = "127.0.0.1", port: int = 8000) -> None:
    import webbrowser

    url = f"http://{host}:{port}"
    print(f"aoe2coach web → {url}  (Ctrl-C to stop)")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
    create_app().run(host=host, port=port, debug=False, threaded=True)
