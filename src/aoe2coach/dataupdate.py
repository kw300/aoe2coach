"""Regenerate the bundled game-data tables under ``aoe2coach/data/``.

Exposed as ``aoe2coach update-data``. Requires the **full** backend — its
``mgz.reference`` dataset is the authoritative, version-stamped source for
object/tech/civ/map names and terrain colors. Optionally enriches with the
SiegeEngineers aoe2techtree per-civ tech tree.

This is a maintenance command (dev/CI), expected to run against an editable checkout
so it writes into the source tree. A weekly GitHub Action runs it and opens a PR when
the data changes.
"""

from __future__ import annotations

import datetime as _dt
import json
import urllib.request
from pathlib import Path

_AOE2TECHTREE = (
    "https://raw.githubusercontent.com/SiegeEngineers/aoe2techtree/master/data/data.json"
)
DATA_DIR = Path(__file__).resolve().parent / "data"


def _fetch_json(url: str) -> dict | None:
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "aoe2coach-update"}), timeout=60
        ).read()
        return json.loads(raw)
    except Exception as exc:  # network optional — names still come from mgz.reference
        print(f"  (skipped aoe2techtree enrichment: {exc})")
        return None


def build_data(out_dir: Path = DATA_DIR) -> dict:
    """Generate the bundled data tables. Returns the manifest dict."""
    try:
        import mgz.reference as ref
        from mgz.reference import Version
    except ImportError as exc:
        raise SystemExit(
            'update-data needs the full backend. Install it:  pip install -e ".[full]"'
        ) from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    _dataset_id, ds = ref.get_dataset(Version.DE, 0)

    files: dict[str, dict] = {
        "objects.json": {str(k): v for k, v in ds["objects"].items() if v},
        "technologies.json": {str(k): v for k, v in ds["technologies"].items() if v},
        "civilizations.json": {str(k): info["name"] for k, info in ds["civilizations"].items()},
        "maps.json": {str(k): v for k, v in ds["maps"].items() if v},
        "terrain.json": {str(k): v for k, v in ds["terrain"].items()},
    }

    tt = _fetch_json(_AOE2TECHTREE)
    if tt and "civs" in tt:
        files["civ_techtrees.json"] = {
            name: {k: info.get(k, []) for k in ("Building", "Unit", "Tech")}
            for name, info in tt["civs"].items()
        }

    for fname, payload in files.items():
        (out_dir / fname).write_text(
            json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    manifest = {
        "generated": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset_version": ds["dataset"].get("version"),
        "dataset_name": ds["dataset"].get("name"),
        "source": "mgz.reference (+ aoe2techtree civ trees)",
        "counts": {f: len(p) for f, p in files.items()},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    print(f"Generating game data into {DATA_DIR} …")
    print(json.dumps(build_data(), indent=2))
    return 0
