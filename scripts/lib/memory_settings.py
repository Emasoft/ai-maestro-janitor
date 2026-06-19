# Global wikimem-editor settings + scheduler-stamp primitives (TRDD-c1397102).
#
# All wikimem-editor settings are GLOBAL (machine-wide, NOT per-repo) — the user's
# explicit requirement. The store is one JSON file at the janitor's HARD-CODED
# plugin-DATA path (NOT ${CLAUDE_PLUGIN_DATA}, which at heartbeat time resolves to
# whatever plugin owns the turn — the same trap memory-librarian._resolve_user_scope_dir
# documents). The persistent plugin-DATA dir survives plugin/version updates and is
# backed up, so a user's frequency choices are not lost on an update.
#
# The frequencies are floats in "times per day" (0.5 = once/48h; 0 = DISABLED).
# `interval_s` turns a per-day rate into a seconds-between-runs cadence (inf when
# disabled). The scheduler (TRDD-D) reads `is_due`/`mark_ran` — keyed per
# (intervention × scope × concrete-root) under the machine-wide global-state dir so
# N sessions don't multi-fire the same global intervention, and so iterating
# several roots never starves all-but-the-first (each root has its own stamp).

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import global_state
import state

# Default global settings. Per-day rates are intentionally LOW (the editorial
# passes are token-costly) and every one is disable-able by setting it to 0.
DEFAULTS: dict = {
    "consolidation_per_day": 2.5,   # MERGE pass
    "split_per_day": 4.5,           # SPLIT pass (cheaper, size-triggered)
    "split_max_bytes": 12000,       # a page over this is a SPLIT candidate
    "conflict_per_day": 0.5,        # CONFLICT + fact-verify (once/48h — the costly one)
    "repair_per_day": 3.0,          # REPAIR pass (page-shape/metadata backfill — a few/day)
    "edit_project_scope": False,    # default LOCAL+USER only; PROJECT memory is in-repo
}

_PER_DAY_KEYS = frozenset({"consolidation_per_day", "split_per_day", "conflict_per_day", "repair_per_day"})
_INT_KEYS = frozenset({"split_max_bytes"})
_BOOL_KEYS = frozenset({"edit_project_scope"})

# intervention name -> the per-day settings key that governs its cadence
INTERVENTIONS: dict = {
    "consolidate": "consolidation_per_day",
    "split": "split_per_day",
    "conflict": "conflict_per_day",
    "repair": "repair_per_day",
}

_SECONDS_PER_DAY = 86400


# --------------------------------------------------------------------------- #
# the settings store
# --------------------------------------------------------------------------- #

def settings_dir() -> Path:
    """The janitor's persistent plugin-DATA dir, resolved by the EXPLICIT
    hard-coded path (never ${CLAUDE_PLUGIN_DATA}). `JANITOR_MEMORY_SETTINGS_DIR`
    overrides it for tests."""
    override = os.environ.get("JANITOR_MEMORY_SETTINGS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"


def _settings_path() -> Path:
    return settings_dir() / "memory-settings.json"


def load() -> dict:
    """Return the full settings dict (DEFAULTS overlaid by any persisted values).
    A missing or unreadable store yields the defaults — never crashes."""
    merged = dict(DEFAULTS)
    path = _settings_path()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return merged
    if isinstance(stored, dict):
        for k, val in stored.items():
            if k in DEFAULTS:
                merged[k] = val
    return merged


def _coerce(key: str, raw) -> object:
    """Validate + coerce a raw value for `key`. Fail-fast (ValueError) on a bad
    value — no silent fallback. `raw is None` means 'revert to default'."""
    if key not in DEFAULTS:
        raise ValueError(f"unknown setting {key!r} (known: {sorted(DEFAULTS)})")
    if raw is None:
        return DEFAULTS[key]
    if key in _BOOL_KEYS:
        s = str(raw).strip().lower()
        if s in ("1", "true", "on", "yes"):
            return True
        if s in ("0", "false", "off", "no"):
            return False
        raise ValueError(f"{key} expects a boolean (on/off), got {raw!r}")
    if key in _INT_KEYS:
        n = int(str(raw).strip())
        if n <= 0:
            raise ValueError(f"{key} must be a positive integer, got {n}")
        return n
    # per-day float rate
    f = float(str(raw).strip())
    if f < 0 or math.isnan(f) or math.isinf(f):
        raise ValueError(f"{key} must be a finite rate >= 0 (0 disables), got {raw!r}")
    return f


def get(key: str):
    """Current value of one setting."""
    if key not in DEFAULTS:
        raise ValueError(f"unknown setting {key!r}")
    return load()[key]


def set_value(key: str, raw=None):
    """Persist `key` = coerced(`raw`); `raw is None` reverts to the default.
    Returns the stored value. Atomic write (tmp + os.replace)."""
    value = _coerce(key, raw)
    current = load()
    current[key] = value
    settings_dir().mkdir(parents=True, exist_ok=True)
    state.atomic_write(_settings_path(), json.dumps(current, indent=2, sort_keys=True))
    return value


def interval_s(key: str) -> float:
    """Seconds-between-runs for a per-day rate key. inf when the rate is 0
    (DISABLED). Raises for a non-per-day key."""
    if key not in _PER_DAY_KEYS:
        raise ValueError(f"{key} is not a per-day rate")
    per_day = float(load()[key])
    if per_day <= 0:
        return math.inf
    return _SECONDS_PER_DAY / per_day


# --------------------------------------------------------------------------- #
# scheduler stamps (read by TRDD-D's detector) — machine-wide, per concrete root
# --------------------------------------------------------------------------- #

def interval_s_for(intervention: str) -> float:
    """Cadence (seconds) for an intervention, derived from its governing per-day
    setting. inf when disabled."""
    if intervention not in INTERVENTIONS:
        raise ValueError(f"unknown intervention {intervention!r}")
    return interval_s(INTERVENTIONS[intervention])


def _stamp_path(intervention: str, scope: str, root) -> Path:
    # Machine-wide (global-state dir) so two sessions share one stamp per global
    # intervention; keyed by the concrete root's hash so several roots in a scope
    # each get their own cadence (no starvation).
    h = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    return global_state.global_state_dir() / f"memory-maint-{intervention}-{scope}-{h}.last-run.ts"


def read_last_run(intervention: str, scope: str, root) -> int:
    return state.read_int_state(_stamp_path(intervention, scope, root), default=0)


def mark_ran(intervention: str, scope: str, root, now: int) -> None:
    """Stamp that `intervention` ran for (scope, root) at `now` (epoch seconds)."""
    global_state.init_global_state()
    state.atomic_write(_stamp_path(intervention, scope, root), str(int(now)))


def is_due(intervention: str, scope: str, root, now: int) -> bool:
    """True iff `intervention` is due for (scope, root): enabled AND at least one
    cadence interval has elapsed since the last run."""
    iv = interval_s_for(intervention)
    if iv == math.inf:
        return False
    return (now - read_last_run(intervention, scope, root)) >= iv
