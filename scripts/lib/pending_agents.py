"""Pending background-agent manifest (TRDD-82OP4EN9 W1) — deterministic fork
resume for unattended nights.

WHY this exists: when a session-limit / rate-limit window kills every in-flight
turn, the MAIN session auto-resumes via ``rate-limited.flag`` →
``[janitor-resume]`` — but its BACKGROUND agents (forks) stay dead unless a
human notices (empirically 2026-07-08: four forks died at the 5h cap and needed
a manual "resume"). This manifest records every live subagent so the resume
directive can LIST them for a deterministic SendMessage-resume instead of
hoping the model remembers its transcript.

OVER-LISTING IS CHEAP, NOT FREE (issue #75, 2026-07-09). The original design said
a resume ping to a finished agent is "harmless — it just restates its result",
and made the 7-day age sweep the only cleanup. That reasoning holds for an agent
that COMPLETED. It fails for one that DIED: a `claude-code-guide` fork terminated
deterministically ("Prompt is too long · ~290003 tokens > 200000 limit" — its own
system prompt overflows before any work), and because SubagentStop carries no
``agent_id`` to remove it, the manifest re-nudged a resume of that corpse on EVERY
heartbeat until a human zeroed the file by hand. Resuming it re-ran the identical
over-limit request, forever.

We cannot observe "this agent died" — the hook payload does not carry it (see
below). So we bound the blast radius instead: each entry is listed at most
``MAX_NUDGES`` times and is then dropped. Three unheeded nudges mean the agent
either resumed (and its Stop never cleared it) or cannot be resumed; in both
cases nudging again is waste. Under-listing is still the worse failure, so the
budget is spent before the entry is retired, never withheld.

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

# How many times ONE entry may appear in a resume directive before it is retired.
# The bound that turns the 7-day ghost of issue #75 into three pings. Chosen as
# the smallest number that still tolerates a heartbeat firing while the model is
# mid-turn and cannot act on the directive yet.
MAX_NUDGES = 3

# Bound persisted description length (hook payloads are model-adjacent data).
_MAX_DESC_LEN = 120

# The prefix every agent the JANITOR ITSELF spawns for its own background
# housekeeping carries in its name — janitor-memory-subconscious-agent (the
# memory-maintenance chores) and janitor-security-agent (security sweeps). Issue
# #89: the cadence FAST probe counted these and oscillated the heartbeat tier,
# because the janitor's own [janitor-memory-*] markers RAISE the pending count —
# a controller must never read an input it creates itself. The stored
# `description` is the SubagentStart `agent_type`, which Claude Code reports for a
# PLUGIN subagent in the plugin-scoped form
# `ai-maestro-janitor:janitor-memory-subconscious-agent`, so we match on the
# agent's own NAME (the part after any `<plugin>:` scope) carrying this prefix —
# covering both the scoped form and a bare `janitor-*` name.
_HOUSEKEEPING_NAME_PREFIX = "janitor-"


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


def _normalize(entry: object, now: int) -> dict | None:
    """One raw manifest record → a clean entry, or None if it must be swept.

    Swept when: not a mapping, no agentId, older than MAX_AGE_S (the guaranteed
    cleanup for a Stop that never fired), or its nudge budget is spent (#75).
    An absent/corrupt `nudges` restarts the budget — pre-#75 manifests have no
    such key, and a fresh budget over-nudges by at most MAX_NUDGES, which is the
    safe direction (under-listing loses a real agent).
    """
    if not isinstance(entry, dict):
        return None
    agent_id = str(entry.get("agentId", "") or "").strip()
    if not agent_id:
        return None
    ts = entry.get("ts", 0)
    if not isinstance(ts, int):
        ts = 0
    if now - ts > MAX_AGE_S:
        return None
    nudges = entry.get("nudges", 0)
    if not isinstance(nudges, int) or nudges < 0:
        nudges = 0
    if nudges >= MAX_NUDGES:
        return None
    return {
        "agentId": agent_id,
        "description": str(entry.get("description", "") or "")[:_MAX_DESC_LEN],
        "ts": ts,
        "nudges": nudges,
    }


def _load_unlocked(now: int) -> list[dict]:
    """Read + sweep the manifest. Corrupt/missing → [] (fail-open, never raises)."""
    try:
        entries = json.loads(_manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(entries, list):
        return []
    return [e for e in (_normalize(raw, now) for raw in entries) if e is not None]


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
                    "nudges": 0,  # a re-spawned id gets a fresh nudge budget
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


def is_housekeeping_entry(entry: object) -> bool:
    """True iff `entry` names an agent the janitor spawns for its OWN background
    housekeeping (memory maintenance / security sweeps) — see issue #89.

    Keyed on the stored `description` (the SubagentStart `agent_type`): strip any
    `<plugin>:` scope prefix and test the agent's own name for
    `_HOUSEKEEPING_NAME_PREFIX`. A missing/empty description reads False (fail
    towards "user-relevant", the safe direction — an unidentifiable agent is
    counted, never silently dropped from the resume path or the probe)."""
    if not isinstance(entry, dict):
        return False
    name = str(entry.get("description", "") or "").rsplit(":", 1)[-1].strip()
    return name.startswith(_HOUSEKEEPING_NAME_PREFIX)


def pending_user_relevant(now: int | None = None) -> list[dict]:
    """Live entries EXCLUDING the janitor's OWN housekeeping agents (issue #89).

    The cadence FAST probe (dispatch `_cadence_active_waiting`) must use THIS, not
    `pending()`: a background memory/security chore the janitor itself scheduled is
    housekeeping, NOT "the user is waiting on something time-sensitive", so it must
    not promote the heartbeat to the FAST tier. `pending()` and `directive_lines()`
    stay UNFILTERED on purpose — a housekeeping fork that died at the 5h cap still
    needs a deterministic resume, so the resume path must still see every entry.
    Fail-open []."""
    return [e for e in pending(now) if not is_housekeeping_entry(e)]


def directive_lines(now: int | None = None) -> list[str]:
    """Resume-directive lines for the newest MAX_DIRECTIVE_AGENTS entries.

    CONSUMING read (#75): each listed entry spends one nudge from its budget, and
    an entry whose budget is exhausted is dropped on the next load. This is what
    stops a dead agent from being re-nudged on every heartbeat for MAX_AGE_S. The
    write is best-effort — if it fails, the lines are still returned (a lost nudge
    count over-nudges, which is the safe direction).

    Ids/descriptions come from hook payloads (model-adjacent, untrusted), so
    both are defanged via ``sanitize_for_drift_line`` — a crafted description
    cannot inject a fake ``[janitor-…]`` marker line into the resume turn.
    """
    try:
        t = int(now if now is not None else time.time())
        with _locked():
            entries = _load_unlocked(t)
            listed = entries[-MAX_DIRECTIVE_AGENTS:]
            if not listed:
                return []
            lines = [_directive_line(e) for e in listed]
            shown = {e["agentId"] for e in listed}
            for e in entries:
                if e["agentId"] in shown:
                    e["nudges"] += 1
            _save_unlocked(entries)
    except Exception:  # noqa: BLE001 - the resume phases must never die on a manifest bug
        return []
    # One shared note (not per-line — token economy). It must NOT claim the ping is
    # free: an agent that DIED (terminal API error) re-runs its failing request on
    # every resume, which is exactly how issue #75 burned tokens for a week.
    lines.append(
        "(check each agent's status before resuming: a finished agent just restates its "
        f"result, but a DIED agent re-runs the request that killed it; each is listed at "
        f"most {MAX_NUDGES} times, then dropped)"
    )
    return lines


def _directive_line(entry: dict) -> str:
    """One sanitized resume line. `sanitize_for_drift_line` defangs [ ] and strips
    control chars but keeps newlines — collapse whitespace too, or a multi-line
    description would smuggle a raw extra line into the resume turn (one line per
    agent is the contract the whole-line-only marker security model relies on)."""
    aid = " ".join(state.sanitize_for_drift_line(entry["agentId"]).split())[:64]
    desc = " ".join(state.sanitize_for_drift_line(entry["description"]).split())[:_MAX_DESC_LEN]
    suffix = f" — {desc}" if desc else ""
    return f"resume background agent via SendMessage: {aid}{suffix}"
