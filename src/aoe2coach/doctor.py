"""Offline setup diagnostics. Never send requests or print credentials."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import import_module, metadata
from pathlib import Path

from .config import TASKS, ConfigError, load_config
from .parse import _detect_backend
from .replays import find_replays


@dataclass
class Check:
    name: str
    status: str  # ok | warning | error
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _installed(distribution: str) -> bool:
    try:
        metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return False
    return True


def _importable(module: str) -> bool:
    try:
        import_module(module)
    except Exception:
        return False
    return True


def check_setup() -> list[Check]:
    """Check local dependencies, each task's config, and replay discovery.

    A key's presence does not prove it is valid. Model IDs and endpoint capabilities
    cannot be verified offline; diagnostics deliberately make no API calls.
    """
    checks: list[Check] = []
    if _installed("mgz") and _installed("mgz-fast"):
        checks.append(
            Check(
                "parser",
                "error",
                "Both mgz and mgz-fast are installed and share a module. Create a fresh "
                'virtual environment and install exactly one: ".[full]" or ".[fast]".',
            )
        )
    else:
        try:
            backend = _detect_backend()
        except Exception:
            checks.append(
                Check(
                    "parser",
                    "error",
                    'No working parser found. Install one backend: pip install -e ".[full]" '
                    '(older replays) or pip install -e ".[fast]" (newer replays).',
                )
            )
        else:
            detail = (
                "Rich parser installed; replay patch compatibility still needs a replay check."
                if backend == "full"
                else "Fast parser installed; rich metrics may be unavailable."
            )
            checks.append(Check("parser", "ok", f"{backend}: {detail}"))

    for task in TASKS:
        try:
            config = load_config(require_key=False, task=task)
        except (ConfigError, ValueError):
            # Don't echo arbitrary environment values, URLs, or SDK errors.
            checks.append(
                Check(
                    f"model:{task}",
                    "error",
                    f"Invalid {task} configuration. Check AOE2COACH_{task.upper()}_* "
                    "and global AOE2COACH_* settings against env.example.",
                )
            )
            continue

        if not config.model:
            checks.append(
                Check(
                    f"model:{task}",
                    "error",
                    f"Set AOE2COACH_{task.upper()}_MODEL or a compatible AOE2COACH_MODEL.",
                )
            )
        else:
            checks.append(Check(f"model:{task}", "ok", f"{config.provider} / {config.model}"))

        checks.append(
            Check(
                f"key:{task}",
                "ok" if config.api_key else "error",
                f"{config.api_key_env} is set (validity not checked)."
                if config.api_key
                else f"Set {config.api_key_env} in your environment or local .env.",
            )
        )
        sdk = "anthropic" if config.provider == "anthropic" else "openai"
        checks.append(
            Check(f"sdk:{task}", "ok", f"{sdk} SDK is available.")
            if _importable(sdk)
            else Check(
                f"sdk:{task}",
                "error",
                f"Missing or broken {sdk} SDK. Install it with: pip install {sdk}",
            )
        )

    for name, module, extra in (
        ("web", "flask", "web"),
        ("mcp", "mcp.server.fastmcp", "mcp"),
        ("minimap", "PIL.Image", "viz"),
    ):
        checks.append(
            Check(name, "ok", "Optional feature dependency is available.")
            if _importable(module)
            else Check(
                name,
                "warning",
                f'Optional dependency unavailable. To use {name}: pip install -e ".[{extra}]"',
            )
        )

    try:
        replays = {p.resolve() for p in find_replays()}
        local_replays = {p.resolve() for p in Path.cwd().glob("*.aoe2record") if p.is_file()}
        count = len(replays | local_replays)
    except OSError:
        checks.append(
            Check("replays", "warning", "Replay folders could not be read. Pass a replay path.")
        )
    else:
        checks.append(
            Check("replays", "ok", f"Found {count} replay(s) in game folders or this folder.")
            if count
            else Check(
                "replays",
                "warning",
                "No replays discovered. Pass a replay path to analyze, "
                "or drag one into the web UI.",
            )
        )
    return checks
