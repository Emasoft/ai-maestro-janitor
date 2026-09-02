"""Per-session snapshot of enabled-plugin versions, for the `[janitor-reload]` relevance gate.

THE BUG THIS EXISTS FOR (janitor#290 §2, TRDD-38PB1B86). `dispatch._phase_plugin_reload` fires
whenever the daemon's machine-global reload GENERATION (an epoch, bumped on every fleet
`plugins-updated.json` rewrite) exceeds this project's ack — but the server rewrites that epoch
on every fleet refresh even when it lists the SAME plugins at the SAME versions. The generation
is a "something happened somewhere" signal, not a "a plugin THIS session runs actually changed"
signal, so sessions were reloading (and paying the prompt-cache-break tax) for no-op refreshes.

This module supplies the missing per-session truth: a snapshot of (enabled plugin → newest
cached version) taken at session start, and a comparison against the CURRENT newest cached
version for each. Only a real version delta on a plugin THIS session has enabled counts as
relevant; a generation bump with no such delta is silently absorbed (dispatch.py advances the ack
without emitting).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import state  # noqa: E402


def _default_cache_root() -> Path:
    """The user-scope plugin cache root, resolved AT CALL TIME (never a module-level
    constant) — a frozen `Path.home()` would capture the real HOME before a test's
    `monkeypatch.setenv("HOME", ...)` takes effect (same trap `settings_ensurer`
    documents for the settings path)."""
    return Path.home() / ".claude" / "plugins" / "cache"


def _version_key(name: str) -> tuple[int, ...]:
    """Sort key for a semver-ish cache dir name (``3.4.10`` sorts above ``3.4.9``).

    Copied from `launchd_keepalive._version_key` (not imported) to keep this module
    import-light — it is loaded from the SessionStart hook, where every extra import
    is paid on every session start. A non-numeric dir name sorts lowest so it never
    wins over a real version.
    """
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return (-1,)


def newest_cached_version(cache_root: Path, plugin_key: str) -> str | None:
    """Newest version dir name cached for `plugin_key` (``"<name>@<marketplace>"``), or
    `None` when nothing is cached for it. Layout: `<cache_root>/<marketplace>/<name>/<version>/`.
    """
    if "@" not in plugin_key:
        return None
    name, _, marketplace = plugin_key.partition("@")
    plugin_dir = cache_root / marketplace / name
    if not plugin_dir.is_dir():
        return None
    versions = [d.name for d in plugin_dir.iterdir() if d.is_dir()]
    if not versions:
        return None
    return max(versions, key=_version_key)


def snapshot_enabled(settings_path: Path, cache_root: Path | None = None) -> dict[str, str]:
    """`{plugin_key: newest_cached_version}` for every plugin enabled in `settings_path`.

    A plugin with no cache dir yet is skipped (nothing to compare later — `changed_since`
    treats "newly appeared" as its own signal, so omission here is not a loss)."""
    if cache_root is None:
        cache_root = _default_cache_root()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import fleet_plugin_updates  # noqa: PLC0415 -- lazy: avoid the import cost when unused

    out: dict[str, str] = {}
    for key in fleet_plugin_updates.enabled_plugins(settings_path):
        version = newest_cached_version(cache_root, key)
        if version is not None:
            out[key] = version
    return out


def write_snapshot(path: Path, versions: dict[str, str]) -> None:
    """Persist `versions` atomically. `epoch` is informational (debugging), not read back."""
    state.atomic_write(
        path, json.dumps({"epoch": int(time.time()), "versions": versions}, sort_keys=True)
    )


def read_snapshot(path: Path) -> dict[str, str] | None:
    """The `versions` map written by `write_snapshot`, or `None` on absent/malformed —
    NEVER raises, since an unreadable snapshot must fall back to the pre-feature (legacy)
    reload behaviour rather than block or crash the phase that calls it."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    versions = data.get("versions") if isinstance(data, dict) else None
    if not isinstance(versions, dict):
        return None
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in versions.items()):
        return None
    return versions


def changed_since(
    snapshot: dict[str, str], settings_path: Path, cache_root: Path | None = None
) -> dict[str, tuple[str, str]]:
    """`{plugin_key: (old_version, new_version)}` for every currently-enabled plugin whose
    newest cached version differs from `snapshot`'s. A plugin enabled now but absent from the
    snapshot (newly enabled since session start) counts as changed, `old` reported as `"?"`."""
    current = snapshot_enabled(settings_path, cache_root)
    changed: dict[str, tuple[str, str]] = {}
    for key, new in current.items():
        old = snapshot.get(key, "?")
        if old != new:
            changed[key] = (old, new)
    return changed
