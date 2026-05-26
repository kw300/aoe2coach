"""Local web **chat** UI — pick (or drag in) a replay on the left, talk to the coach.

`aoe2coach web` → opens a browser. Configure `.env` first, then choose a replay (or drag
a `.aoe2record` in); aoe2coach parses it and the coach opens with a report, and you ask
follow-ups. Powered by the same environment-based API path as the CLI.

A thin Flask wrapper over the library (parse → metrics → CoachChat). Optional extra:
    pip install -e ".[full,web]"     # or ".[fast,web]" for current-patch games
"""

from __future__ import annotations

import html
import tempfile
from pathlib import Path

from . import build_metrics, parse_replay
from .coach import CoachChat, build_opening_message
from .config import ConfigError

try:
    from flask import Flask, render_template_string, request
    from werkzeug.utils import secure_filename
except ImportError as exc:  # pragma: no cover
    raise SystemExit('The web UI needs Flask:  pip install -e ".[web]"') from exc

_SESSIONS: dict[str, CoachChat] = {}
_UPLOAD_DIR = Path(tempfile.gettempdir()) / "aoe2coach-uploads"


def _listed_replays() -> list[Path]:
    """Replays to show: the launch folder + anything dragged in (NOT the savegame folder —
    that fills the UI with current-patch games the rich backend can't read)."""
    seen: dict[Path, Path] = {}
    for p in [*Path.cwd().glob("*.aoe2record"), *_UPLOAD_DIR.glob("*.aoe2record")]:
        seen.setdefault(p.resolve(), p)

    def mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    return sorted(seen.values(), key=mtime, reverse=True)


def _open_session(replay: str) -> dict:
    try:
        chat = CoachChat()
        metrics = build_metrics(parse_replay(replay))
    except ConfigError as exc:
        return {"error": str(exc).splitlines()[0]}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

    elo = None
    try:
        from .elo import fetch_ratings

        elo = fetch_ratings([p.profile_id for p in metrics.players if p.profile_id]) or None
    except Exception:  # noqa: BLE001
        elo = None
    # Trends are skipped on open for speed (parsing recent games + a bigger prompt is
    # slow); habits are available via the CLI `aoe2coach trends`.
    opening = build_opening_message(metrics, focus_player=None, elo=elo, trends=None)
    try:
        result = chat.send(opening)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    _SESSIONS[str(replay)] = chat
    return {"report": result.text}


_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>aoe2coach</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
 :root{color-scheme:dark}
 *{box-sizing:border-box} body{margin:0;font:15px/1.55 system-ui,sans-serif;background:#15171c;color:#e6e6e6;height:100vh;display:flex}
 #side{width:300px;border-right:1px solid #2b2f38;overflow:auto;padding:1rem}
 #side h1{font-size:1.1rem;margin:.2rem 0 .8rem}
 #side.drag{background:#1a2334}
 #drop{border:1.5px dashed #3a4150;border-radius:10px;padding:1rem;text-align:center;color:#9aa4b2;font-size:.82rem;margin-bottom:.8rem}
 #side.drag #drop{border-color:#3a6df0;color:#cdd3dc}
 .rep{display:block;width:100%;text-align:left;background:#1c1f26;border:1px solid #2b2f38;color:#cdd3dc;padding:.5rem .6rem;border-radius:8px;margin:.3rem 0;cursor:pointer;font-size:.82rem;word-break:break-all}
 .rep:hover{border-color:#3a6df0} .rep.active{border-color:#3a6df0;background:#222838}
 #main{flex:1;display:flex;flex-direction:column}
 #log{flex:1;overflow:auto;padding:1.5rem;max-width:820px;margin:0 auto;width:100%}
 .msg{margin:0 0 1rem;padding:.8rem 1rem;border-radius:10px}
 .you{background:#223;border:1px solid #2b3550;margin-left:3rem}
 .coach{background:#1c1f26;border:1px solid #2b2f38;margin-right:3rem}
 .coach h1,.coach h2,.coach h3{font-size:1.05rem;margin:.6rem 0 .3rem} .coach table{border-collapse:collapse;margin:.5rem 0}
 .coach td,.coach th{border:1px solid #2b2f38;padding:.25rem .5rem;font-size:.9rem} .coach code{background:#0f1115;padding:.1rem .3rem;border-radius:4px}
 .muted{color:#9aa4b2} .err{color:#ff7676}
 #bar{border-top:1px solid #2b2f38;padding:1rem;display:flex;gap:.6rem;max-width:820px;margin:0 auto;width:100%}
 #q{flex:1;background:#0f1115;border:1px solid #2b2f38;color:#e6e6e6;border-radius:8px;padding:.6rem .8rem;font:inherit}
 button.send{background:#2d6cdf;color:#fff;border:0;border-radius:8px;padding:0 1.1rem;cursor:pointer}
 button:disabled{opacity:.5;cursor:default}
</style></head><body>
<div id="side">
  <h1>🏰 aoe2coach</h1>
  <div id="drop">⬇ Drag a <code>.aoe2record</code> here<br><span style="font-size:.75rem">or pick one below</span></div>
  <div id="list">{{ replays|safe }}</div>
</div>
<div id="main">
  <div id="log"><div class="msg coach muted">Drag in a replay or pick one on the left. I'll read it and we'll talk through what to fix — ask anything, including your recurring habits.</div></div>
  <div id="bar"><input id="q" placeholder="Pick a replay first…" disabled><button class="send" id="send" disabled>Send</button></div>
</div>
<script>
let current=null;
const side=document.getElementById('side'), list=document.getElementById('list');
const log=document.getElementById('log'), q=document.getElementById('q'), send=document.getElementById('send');
function md(t){ try{return marked.parse(t);}catch(e){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;');} }
function add(role, text, isHtml){ const d=document.createElement('div'); d.className='msg '+role; d.innerHTML=isHtml?text:md(text); log.appendChild(d); log.scrollTop=log.scrollHeight; return d; }
function busy(b){ send.disabled=b||!current; q.disabled=b||!current; }
async function postJSON(url, body){ const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); return r.json(); }
function activate(el){ document.querySelectorAll('.rep').forEach(x=>x.classList.remove('active')); if(el) el.classList.add('active'); }
function showReport(res){ if(res.error){ add('coach err','⚠️ '+res.error); current=null; q.placeholder='Pick a replay first…'; } else { add('coach', res.report); q.placeholder='Ask a follow-up…'; } busy(false); q.focus(); }
async function openReplay(el){ activate(el); current=el.dataset.path; log.innerHTML=''; q.value=''; busy(true);
  const wait=add('coach muted','Reading the replay and coaching… (~10–20s)'); const res=await postJSON('/api/open',{replay:current}); wait.remove(); showReport(res); }
function wire(el){ el.onclick=()=>openReplay(el); }
document.querySelectorAll('.rep').forEach(wire);
async function upload(file){ current=null; log.innerHTML=''; q.value=''; busy(true);
  const wait=add('coach muted','Uploading & coaching '+file.name+'…'); const fd=new FormData(); fd.append('file',file);
  const res=await (await fetch('/api/upload',{method:'POST',body:fd})).json(); wait.remove();
  if(res.path){ const b=document.createElement('button'); b.className='rep'; b.dataset.path=res.path; b.textContent=res.name; wire(b); list.insertBefore(b,list.firstChild); activate(b); current=res.path; }
  showReport(res); }
['dragover','dragenter'].forEach(ev=>side.addEventListener(ev,e=>{e.preventDefault();side.classList.add('drag');}));
['dragleave','drop'].forEach(ev=>side.addEventListener(ev,e=>{e.preventDefault();side.classList.remove('drag');}));
side.addEventListener('drop',e=>{ const f=e.dataTransfer.files[0]; if(!f) return; if(f.name.toLowerCase().endsWith('.aoe2record')) upload(f); else add('coach err','⚠️ That is not a .aoe2record file.'); });
async function ask(){ const m=q.value.trim(); if(!m||!current) return; add('you', m); q.value=''; busy(true);
  const wait=add('coach muted','…'); const res=await postJSON('/api/chat',{replay:current,message:m}); wait.remove();
  add(res.error?'coach err':'coach', res.error?('⚠️ '+res.error):res.reply); busy(false); q.focus(); }
send.onclick=ask; q.addEventListener('keydown',e=>{ if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask();} });
</script></body></html>"""


def create_app() -> Flask:
    app = Flask(__name__)

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

    @app.route("/api/open", methods=["POST"])
    def api_open():
        return _open_session((request.json or {}).get("replay", ""))

    @app.route("/api/upload", methods=["POST"])
    def api_upload():
        f = request.files.get("file")
        if f is None or not f.filename:
            return {"error": "No file uploaded."}
        name = secure_filename(f.filename) or "upload.aoe2record"
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = _UPLOAD_DIR / name
        f.save(dest)
        return {**_open_session(str(dest)), "path": str(dest), "name": name}

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        body = request.json or {}
        chat = _SESSIONS.get(str(body.get("replay", "")))
        if chat is None:
            return {"error": "Open a replay first."}
        try:
            return {"reply": chat.send(body.get("message", "")).text}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

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
