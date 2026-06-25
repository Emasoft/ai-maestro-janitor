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
    "split_max_bytes": 36000,       # a page over this is a SPLIT candidate (raised 12k→36k: recall returns a memgrep CHUNK + lessons, not the whole page, so larger pages don't bloat context)
    "conflict_per_day": 0.5,        # CONFLICT + fact-verify (once/48h — the costly one)
    "repair_per_day": 3.0,          # REPAIR pass (page-shape/metadata backfill — a few/day)
    "harvest_per_day": 1.0,         # HARVEST pass — incorporate stray MEMORY.md/.md memories into the wiki (once/day)
    "atomize_per_day": 2.0,         # ATOMIZE pass (TRDD-3b9b2040) — segment a free-prose page body into ^id [keywords:…] atoms so each fact is recallable on its own (a couple/day, incremental until the corpus is atomized)
    "edit_project_scope": False,    # default LOCAL+USER only; PROJECT memory is in-repo
    "stagger_enabled": True,        # spread each (project,intervention) to a deterministic time-of-day slot (rate-limit smoothing across projects)
}

_PER_DAY_KEYS = frozenset(
    {"consolidation_per_day", "split_per_day", "conflict_per_day", "repair_per_day", "harvest_per_day", "atomize_per_day"}
)
_INT_KEYS = frozenset({"split_max_bytes"})
_BOOL_KEYS = frozenset({"edit_project_scope", "stagger_enabled"})

# intervention name -> the per-day settings key that governs its cadence
INTERVENTIONS: dict = {
    "consolidate": "consolidation_per_day",
    "split": "split_per_day",
    "conflict": "conflict_per_day",
    "repair": "repair_per_day",
    "harvest": "harvest_per_day",
    "atomize": "atomize_per_day",
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
    Returns the stored value. Atomic write (tmp + os.replace).

    Persists ONLY keys that DEVIATE from the current DEFAULTS — never the whole
    dict. The old wholesale write froze EVERY key (including ones left at their
    default) into the file, so a LATER change to a default was silently masked by
    the stale captured value: the `split_max_bytes` 12k->36k raise was defeated
    for anyone who had ever set any memory setting (the file kept the old 12000).
    Deviation-only persistence lets a default change flow through to every key the
    user never explicitly tuned. `load()` is unchanged — it overlays DEFAULTS with
    whatever keys are present, so a deviations-only file (or `{}`) reads back as
    pure defaults for untouched keys. [TRDD-378c85da]
    """
    value = _coerce(key, raw)
    current = load()
    current[key] = value
    deviations = {k: v for k, v in current.items() if k in DEFAULTS and DEFAULTS[k] != v}
    settings_dir().mkdir(parents=True, exist_ok=True)
    state.atomic_write(_settings_path(), json.dumps(deviations, indent=2, sort_keys=True))
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


def _phase_offset(intervention: str, scope: str, root, interval: float) -> float:
    """Deterministic per-(intervention, scope, root) phase in [0, interval) seconds.

    Different projects (roots) hash to different phases, so their daily passes land
    at different times-of-day — the rate-limit smoothing the scheduler wants when
    many projects come due at once. Stable for a given (intervention, scope, root);
    keyed on the SAME tuple the stamp is, so a project's harvest and repair also
    spread apart (bonus smoothing). Returns 0.0 for a non-finite/zero interval."""
    if not math.isfinite(interval) or interval <= 0:
        return 0.0
    h = hashlib.sha256(f"{intervention}:{scope}:{root}".encode("utf-8")).hexdigest()
    return float(int(h[:16], 16) % int(interval))


def is_due(intervention: str, scope: str, root, now: int) -> bool:
    """True iff `intervention` is due for (scope, root): enabled AND a cadence
    interval has elapsed since the last run.

    With `stagger_enabled` (default ON), the cadence is PHASE-ALIGNED: the due
    moments are the boundaries `k*interval + phase` for a per-(intervention,scope,
    root) phase, so different projects fire at different times-of-day instead of
    clustering. (The machine-wide dispatch flock already serializes a same-window
    pile-up; staggering additionally spreads the daily LOAD across the period.)
    First run (last_run=0) still fires promptly — the most-recent boundary is far
    past epoch-0 — and steady state then aligns to the project's slot.
    `stagger_enabled=off` restores the plain `now - last_run >= interval` cadence."""
    iv = interval_s_for(intervention)
    if iv == math.inf:
        return False
    last = read_last_run(intervention, scope, root)
    if not bool(load().get("stagger_enabled", True)):
        return (now - last) >= iv
    phase = _phase_offset(intervention, scope, root, iv)
    # The most-recent phase-aligned boundary at or before `now` (always <= now for
    # any real clock, since phase < iv). Due iff a NEW boundary has been crossed
    # since the last run — which fires exactly once per interval, at the slot.
    boundary = math.floor((now - phase) / iv) * iv + phase
    return boundary > last


# --------------------------------------------------------------------------- #
# harvest watermark store (TRDD-ab232dbd — the coexistence mirror's idempotency)
#
# The coexistence harvest MIRRORS each raw buffer note into a separate curated
# `memory/wiki/` page and leaves the buffer 100% intact. Re-running it must NOT
# re-mirror an already-mirrored note (else duplicate wiki pages). The watermark is a
# per-(scope, root) JSON map ``{note_name: content_sha256}`` of what has been
# mirrored. Keyed by content hash, not just name, so an EDITED buffer note (new hash)
# correctly re-mirrors instead of going stale. Lives in the global-state dir (like the
# cadence stamps) so two sessions on the same host share one watermark per scope.
# --------------------------------------------------------------------------- #

def harvest_watermark_path(scope: str, root) -> Path:
    # Same per-(scope, root) hash keying as `_stamp_path`, so each concrete root in a
    # scope gets its own watermark (LOCAL/PROJECT/USER never collide, and two projects
    # sharing a scope don't share a mirror ledger).
    h = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    return global_state.global_state_dir() / f"memory-harvest-watermark-{scope}-{h}.json"


def harvest_watermark_read(scope: str, root) -> dict:
    """Return the ``{note_name: content_sha256}`` map of buffer notes already mirrored
    for (scope, root). A missing or CORRUPT watermark degrades to ``{}`` (the harvest
    re-mirrors — safe, additive, never loses a memory) rather than crashing the pass."""
    p = harvest_watermark_path(scope, root)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # Defensive: a hand-edited / wrong-shape file degrades to empty, not a type error.
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def harvest_note_is_mirrored(scope: str, root, note_name: str, note_text: str) -> bool:
    """True iff `note_name` was mirrored AND its content is unchanged since (the stored
    hash matches the hash of `note_text`). An edited buffer note → False → re-mirror."""
    wm = harvest_watermark_read(scope, root)
    return wm.get(note_name) == _content_hash(note_text)


def harvest_mark_mirrored(scope: str, root, note_name: str, note_text: str) -> None:
    """Record that `note_name` (with this exact content) has been mirrored into the
    wiki. Read-modify-write the per-scope map atomically (tmp + os.replace via
    `state.atomic_write`), accumulating across notes within and across passes."""
    global_state.init_global_state()
    wm = harvest_watermark_read(scope, root)
    wm[note_name] = _content_hash(note_text)
    state.atomic_write(harvest_watermark_path(scope, root), json.dumps(wm, sort_keys=True))


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
