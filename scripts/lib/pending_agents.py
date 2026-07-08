"""Pending background-agent manifest (TRDD-82OP4EN9 W1) — deterministic fork
resume for unattended nights.

WHY this exists: when a session-limit / rate-limit window kills every in-flight
turn, the MAIN session auto-resumes via ``rate-limited.flag`` →
``[janitor-resume]`` — but its BACKGROUND agents (forks) stay dead unless a
human notices (empirically 2026-07-08: four forks died at the 5h cap and needed
a manual "resume"). This manifest records every live subagent so the resume
directive can LIST them for a deterministic SendMessage-resume instead of
hoping the model remembers its transcript. A resume ping to an agent that
actually finished is HARMLESS (verified 2026-07-08: a completed fork restated
its result and stopped) — so over-listing is safe, under-listing is not.

Writers: ``scripts/hooks/on-subagent-start.py`` (add) and
``scripts/hooks/on-subagent-stop.py`` (remove). Reader: ``dispatch.py``'s
resume phases + keep-going nudge. Every entry point is FAIL-OPEN — a manifest
bug must never break a hook or a heartbeat fire (the survival phases are
load-bearing for the overnight loop).

Payload reality (hook reference, verified 2026-07-08): SubagentStart carries
``agent_id``; SubagentStop's documented schema does NOT — so removal is
best-effort and the TIME SWEEP below is the guaranteed cleanup path for
entries whose Stop never fired (which is exactly the crash case the manifest
exists for).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import time
from pathlib import Path
from typing import Iterator

try:
    import state  # scripts/lib on sys.path (dispatch / detector callers)
except ImportError:  # imported as ``lib.pending_agents`` (hooks put scripts/ on path)
    from lib import state  # type: ignore[no-redef]

MANIFEST_NAME = "pending-agents.json"
_LOCK_NAME = "pending-agents.lock"

# Entries older than this are swept on EVERY read: a Stop event that never
# fired must not leave a ghost forever. 7 days >> any real overnight run,
# << unbounded growth (boundedness invariant, TRDD-7IUTRX29).
MAX_AGE_S = 7 * 24 * 3600

# Hard cap — a runaway spawner cannot grow the file unbounded. Newest win.
MAX_ENTRIES = 50

# The resume directive lists at most this many (token economy: the directive
# rides a model turn; 10 covers any sane parallel fan-out).
MAX_DIRECTIVE_AGENTS = 10

# Bound persisted description length (hook payloads are model-adjacent data).
_MAX_DESC_LEN = 120


def _manifest_path() -> Path:
    return state.state_dir() / MANIFEST_NAME


@contextlib.contextmanager
def _locked() -> Iterator[None]:
    """Serialize read-modify-write across concurrently-firing hooks.

    Parallel Agent spawns fire N SubagentStart hooks at once; without the
    flock two load→append→save cycles interleave and one entry is silently
    lost — exactly the agent the resume directive would then miss.
    """
    lock = state.state_dir() / _LOCK_NAME
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _load_unlocked(now: int) -> list[dict]:
    """Read + sweep the manifest. Corrupt/missing → [] (fail-open, never raises)."""
    try:
        entries = json.loads(_manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(entries, list):
        return []
    out: list[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        agent_id = str(e.get("agentId", "") or "").strip()
        ts = e.get("ts", 0)
        if not isinstance(ts, int):
            ts = 0
        if not agent_id:
            continue
        if now - ts > MAX_AGE_S:
            continue  # the guaranteed cleanup for a Stop that never fired
        out.append(
            {
                "agentId": agent_id,
                "description": str(e.get("description", "") or "")[:_MAX_DESC_LEN],
                "ts": ts,
            }
        )
    return out


def _save_unlocked(entries: list[dict]) -> None:
    state.atomic_write(_manifest_path(), json.dumps(entries, ensure_ascii=False))


def add(agent_id: str, description: str = "", now: int | None = None) -> None:
    """Record a spawned subagent. Fail-open: swallows everything."""
    try:
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            return
        t = int(now if now is not None else time.time())
        with _locked():
            entries = _load_unlocked(t)
            # A re-spawned id refreshes its slot instead of duplicating it.
            entries = [e for e in entries if e["agentId"] != agent_id]
            entries.append(
                {
                    "agentId": agent_id,
                    "description": str(description or "")[:_MAX_DESC_LEN],
                    "ts": t,
                }
            )
            _save_unlocked(entries[-MAX_ENTRIES:])
    except Exception:  # noqa: BLE001 - a manifest bug must never crash a hook
        pass


def remove(agent_id: str, now: int | None = None) -> None:
    """Clear a finished subagent. No-op on empty/unknown id (fail-open)."""
    try:
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            return
        t = int(now if now is not None else time.time())
        with _locked():
            entries = _load_unlocked(t)
            kept = [e for e in entries if e["agentId"] != agent_id]
            if len(kept) != len(entries):
                _save_unlocked(kept)
    except Exception:  # noqa: BLE001 - a manifest bug must never crash a hook
        pass


def pending(now: int | None = None) -> list[dict]:
    """Live (unswept) entries, oldest-first. Fail-open []."""
    try:
        t = int(now if now is not None else time.time())
        return _load_unlocked(t)
    except Exception:  # noqa: BLE001 - readers (resume phases) must never die
        return []


def directive_lines(now: int | None = None) -> list[str]:
    """Resume-directive lines for the newest MAX_DIRECTIVE_AGENTS entries.

    Ids/descriptions come from hook payloads (model-adjacent, untrusted), so
    both are defanged via ``sanitize_for_drift_line`` — a crafted description
    cannot inject a fake ``[janitor-…]`` marker line into the resume turn.
    """
    entries = pending(now)
    if not entries:
        return []
    lines: list[str] = []
    for e in entries[-MAX_DIRECTIVE_AGENTS:]:
        # sanitize_for_drift_line defangs [ ] and strips control chars but keeps
        # newlines — collapse whitespace too, or a multi-line description would
        # smuggle a raw extra line into the resume turn (one line per agent is
        # the contract the whole-line-only marker security model relies on).
        aid = " ".join(state.sanitize_for_drift_line(e["agentId"]).split())[:64]
        desc = " ".join(state.sanitize_for_drift_line(e["description"]).split())[:_MAX_DESC_LEN]
        suffix = f" — {desc}" if desc else ""
        lines.append(f"resume background agent via SendMessage: {aid}{suffix}")
    # One shared note (not per-line — token economy): over-pinging is safe.
    lines.append("(a resume ping to an already-finished agent is harmless — it just restates its result)")
    return lines
