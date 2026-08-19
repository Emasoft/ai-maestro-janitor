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

A DELIBERATE KILL is a second, non-crash instance of the same case, observed
2026-08-13: stopping a background agent with the TaskStop tool does NOT fire
SubagentStop, so its entry survives the kill and rides the nudge path — the
heartbeat then invites a resume of a corpse for up to ``MAX_NUDGES`` fires.
Bounded and fail-open by design, not a defect; but a caller that KNOWS it just
killed an agent should call ``remove()`` itself rather than pay those nudges,
since it holds information neither the hook nor the sweep can infer.
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

# Shorter wall-clock eviction for an entry that has NEVER been nudged
# (janitor#253). Nudge-based eviction (MAX_NUDGES, below) can only age an
# entry that is actually LISTED by directive_lines() — an agent that died
# before ever registering, or that never existed as a live agent at all,
# is surfaced by no directive path, so it is never nudged and would
# otherwise ride the full MAX_AGE_S=7-day backstop, costing a turn per
# heartbeat fire the whole time. A never-nudged entry older than an hour is
# evidence the agent never came up: a live agent that IS being surfaced by
# directive_lines() would have spent at least one nudge within an hour of
# heartbeat fires. An agent that IS progressing (nudges >= 1) keeps the
# full 7-day budget via MAX_AGE_S, unaffected by this shorter window.
#
# ACCEPTED COST, stated so nobody has to rediscover it: `directive_lines()` only runs on
# RESUME paths, so a healthy session that never compacts and never hits a rate limit may
# not list anything for hours. A genuinely long-running agent (>1 h) can therefore still
# be sitting at nudges == 0 and WILL be swept here — after which a later compaction would
# not cue its resume. That is tolerable because this manifest already presumes an agent
# gone after MAX_NUDGES (3) unheeded listings, i.e. the design accepts dropping a live
# agent rather than nagging forever; this only extends the same judgement to the agent
# that no path ever listed. An empty `transcript` is NOT usable as the ghost signal
# instead — `on-subagent-start` deliberately blanks it for workflow-spawned subagents
# (their payload carries the PARENT session's path), so real agents have "" too.
UNNUDGED_MAX_AGE_S = 60 * 60

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

# Agent-type signatures for the agents the JANITOR ITSELF spawns as housekeeping
# (memory-maintenance + security), matched as a substring of the ``description``
# the SubagentStart hook records from the payload's ``agent_type``. A janitor
# background agent is housekeeping the janitor queued — NOT a time-sensitive wait
# — so it must be excluded from the heartbeat cadence FAST probe (TRDD-CI6ZTNB9 /
# issue #89). A controller whose FAST input is a condition it produces itself
# oscillates for free: dispatch emits a `[janitor-memory-*]` marker → the memory
# agent spawns → the pending count flips the tier to FAST → a re-arm burns a turn,
# then the agent finishes and another re-arm burns a second — for every memory
# chore. Keyed on a substring so BOTH the short (`janitor-memory-…`) and the
# plugin-qualified (`ai-maestro-janitor:janitor-memory-…`) agent-type forms match.
_JANITOR_AGENT_SIGNATURES = (
    "janitor-memory-subconscious-agent",
    "janitor-security-agent",
)


def _manifest_path(state_dir: Path | None = None) -> Path:
    """`state_dir` pins WHICH project's manifest is read. Default (None) is the ambient
    session project — correct for every in-session consumer (hooks, the cadence
    controller reading its own session). A caller deciding about a DIFFERENT project
    (the external-clear watcher handed a --project-root, the future daemon fleet walk)
    MUST pass that project's state dir explicitly: the ambient default silently reads
    the CALLING project's manifest, which let one session's in-flight workflow agents
    veto a clear verdict about an unrelated project (caught by
    test_unknown_idle_holds_end_to_end_and_touches_nothing failing a publish gate)."""
    return (state_dir if state_dir is not None else state.state_dir()) / MANIFEST_NAME


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
    cleanup for a Stop that never fired), never-nudged and older than
    UNNUDGED_MAX_AGE_S (janitor#253 — a ghost that no directive path ever
    surfaced, so nudge-based eviction below could never reach it), or its
    nudge budget is spent (#75).
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
    if nudges == 0 and now - ts > UNNUDGED_MAX_AGE_S:
        return None
    if nudges >= MAX_NUDGES:
        return None
    return {
        "agentId": agent_id,
        "description": str(entry.get("description", "") or "")[:_MAX_DESC_LEN],
        "ts": ts,
        "nudges": nudges,
        # Carried through explicitly: this function REBUILDS each entry from a fixed key
        # set, so any field not named here is silently dropped on the first load — which
        # would delete the one thing a respawn needs, at the moment it is needed most.
        "transcript": str(entry.get("transcript", "") or ""),
        # The LAZY-resolution root (see `resolve_transcript`) — same "carried through
        # explicitly" reasoning: drop this and a respawn loses the only way to find the
        # agent's transcript once `transcript` itself was blanked or never resolvable.
        "agentDir": str(entry.get("agentDir", "") or ""),
        # TRDD-PGN5XSHA: same "carried through explicitly" trap — drop this and a
        # deliberately `TaskStop`-killed agent's entry reverts to looking like a plain
        # in-flight one on the very next load, silently undoing `mark_stopped`.
        "stopped": bool(entry.get("stopped", False)),
    }


def _load_unlocked(now: int, state_dir: Path | None = None) -> list[dict]:
    """Read + sweep the manifest. Corrupt/missing → [] (fail-open, never raises)."""
    try:
        entries = json.loads(_manifest_path(state_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(entries, list):
        return []
    return [e for e in (_normalize(raw, now) for raw in entries) if e is not None]


def _save_unlocked(entries: list[dict]) -> None:
    state.atomic_write(_manifest_path(), json.dumps(entries, ensure_ascii=False))


def add(
    agent_id: str,
    description: str = "",
    now: int | None = None,
    transcript: str = "",
    agent_dir: str = "",
) -> None:
    """Record a spawned subagent. Fail-open: swallows everything.

    `transcript` is the RECOVERY path. Resuming an agent is always preferred and the
    harness does it from the agent's own session — but when a resume fails, the only way to
    respawn the SAME job is to reissue its original prompt, and SubagentStart's payload does
    not carry one. The agent's first user message does, so the transcript path is what makes
    the fallback possible at all. Storing the path (not the prompt) keeps the manifest small
    and always current.

    `agent_dir` is the LAZY-resolution root — the `<session>/subagents` dir the agent's own
    transcript will eventually appear under. It exists because the file the hook needs does
    not exist yet at spawn time (SubagentStart fires before the agent produces its first
    turn), so `transcript` is often blanked or unusable at record time. See
    `resolve_transcript` for the deferred lookup this root makes possible.
    """
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
                    "transcript": str(transcript or ""),
                    "agentDir": str(agent_dir or ""),
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


def mark_stopped(agent_id: str, now: int | None = None) -> None:
    """Record that this agent was deliberately `TaskStop`-killed, not that it finished or
    died (TRDD-PGN5XSHA). Mirrors `remove()` but KEEPS the entry (set `stopped: True`)
    instead of dropping it, so it stays visible for audit while `directive_lines()` and
    the pending count stop treating it as a resume candidate. No-op on empty/unknown id
    (fail-open, same contract as `remove`)."""
    try:
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            return
        t = int(now if now is not None else time.time())
        with _locked():
            entries = _load_unlocked(t)
            changed = False
            for e in entries:
                if e["agentId"] == agent_id and not e["stopped"]:
                    e["stopped"] = True
                    changed = True
            if changed:
                _save_unlocked(entries)
    except Exception:  # noqa: BLE001 - a manifest bug must never crash a caller
        pass


def pending(now: int | None = None, *, state_dir: Path | None = None) -> list[dict]:
    """Live (unswept) entries, oldest-first. Fail-open [].

    `state_dir` selects WHOSE manifest (see `_manifest_path`) — omit for the ambient
    session, pass the target project's state dir when deciding about another project."""
    try:
        t = int(now if now is not None else time.time())
        return _load_unlocked(t, state_dir)
    except Exception:  # noqa: BLE001 - readers (resume phases) must never die
        return []


def is_janitor_agent(entry: dict) -> bool:
    """True iff this manifest entry is a background agent the JANITOR spawned for
    its OWN housekeeping (memory maintenance or security), identified by the
    ``agent_type`` the SubagentStart hook stored in ``description``. Such an agent
    is NOT a time-sensitive wait, so the cadence FAST probe must exclude it
    (TRDD-CI6ZTNB9). Substring match so both the short and plugin-qualified
    agent-type forms register; an empty/absent description is NOT janitor (fail
    toward counting it, which only over-promotes to FAST — the safe direction)."""
    desc = str(entry.get("description", "") or "").lower()
    return any(sig in desc for sig in _JANITOR_AGENT_SIGNATURES)


def pending_external(now: int | None = None, *, state_dir: Path | None = None) -> list[dict]:
    """Live entries EXCLUDING the janitor's own housekeeping agents — the set the
    heartbeat cadence FAST probe must count (TRDD-CI6ZTNB9). A USER-spawned
    background agent (a genuine time-sensitive wait) is still counted; only the
    janitor's memory/security agents are filtered, so the controller stops
    perturbing its own FAST input. Distinct from `pending()`, which the resume
    directive still uses in full (a janitor agent that died is listed there so it
    is not silently stranded)."""
    return [e for e in pending(now, state_dir=state_dir) if not is_janitor_agent(e)]


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
            # TRDD-PGN5XSHA: a `stopped` entry was a deliberate decision, not something to
            # nudge a resume of — excluded from BOTH the listing and the nudge spend below.
            candidates = [e for e in entries if not e["stopped"]]
            listed = candidates[-MAX_DIRECTIVE_AGENTS:]
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
    note = (
        "(check each agent's status before resuming: a finished agent just restates its "
        f"result, but a DIED agent re-runs the request that killed it; each is listed at "
        f"most {MAX_NUDGES} times, then dropped)"
    )
    # The respawn fallback (TRDD-KTXZJC6E part B): only named when it would actually work
    # right now — an entry whose transcript cannot be resolved gets no pointer, so the note
    # never promises a prompt that would come back empty (the "documented and inert" failure
    # this whole card is about, one paragraph away from repeating it).
    # Cheap stat-only pass FIRST: in the common case a transcript sits at the direct path, so
    # this answers the question with no directory walk at all. Only when nothing is findable
    # that way do we pay `resolve_transcript`'s rglob — which is also the case where the note
    # would otherwise be misleading, so the cost lands where correctness needs it and nowhere
    # else. Semantics are unchanged (still "does ANY listed entry resolve?"); only the common
    # path got cheaper.
    if any(_transcript_hit_cheap(e) for e in listed) or any(
        resolve_transcript(e) for e in listed
    ):
        note += (
            " If a resume fails, respawn instead: `respawn_prompt_cli.py <agent-id>` prints "
            "the original prompt to spawn a fresh agent with."
        )
    lines.append(note)
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


# The preamble prepended to a RESPAWNED prompt. The respawned agent starts with a blank
# transcript, so it has no idea part of its job may already be done — and a memory chore
# repeated blindly is not harmless: it re-proposes merges that were already made, re-anchors
# lessons, and burns a window doing it. Idempotency has to be stated, because the agent
# cannot infer it.
RESPAWN_PREAMBLE = (
    "RESUMED JOB — a previous run of THIS EXACT TASK was interrupted, and resuming its "
    "session failed, so you are a fresh agent receiving the original prompt verbatim below.\n"
    "PART OF THE WORK MAY ALREADY BE DONE. Before every change, CHECK whether it is already "
    "applied and skip it if so — verify, do not assume, in either direction. Report at the end "
    "how many items you found already complete.\n"
    "Any transaction the previous run left open was aborted; nothing it COMMITTED was lost.\n"
    "--- ORIGINAL PROMPT FOLLOWS ---\n"
)


def _transcript_hit_cheap(entry: dict) -> bool:
    """True iff this entry's transcript is findable with STATS ONLY — no directory walk.

    Covers both shapes `resolve_transcript` tries before its `rglob`: the stored path and
    the direct `<agentDir>/agent-<id>.jsonl` join. Exists so a caller that only needs to know
    "would the respawn pointer work for ANY of these?" can answer it without walking a
    subagents tree per entry on the resume hot path — where a compaction or rate-limit
    recovery is already in flight and every avoidable syscall is paid at the worst moment.

    Deliberately INCOMPLETE, and safe because of the direction it errs: a workflow-spawned
    transcript nested under `workflows/wf_<runid>/` returns False here even though the full
    resolver would find it, so a caller must fall back to `resolve_transcript` before
    concluding NOTHING resolves. Never the reverse — this never claims a hit the full
    resolver would miss.
    """
    stored = str(entry.get("transcript", "") or "")
    agent_dir = str(entry.get("agentDir", "") or "")
    agent_id = str(entry.get("agentId", "") or "").strip()
    try:
        if stored and Path(stored).is_file():
            return True
        return bool(agent_dir and agent_id and (Path(agent_dir) / f"agent-{agent_id}.jsonl").is_file())
    except OSError:
        return False


def resolve_transcript(entry: dict) -> str:
    """The entry's usable transcript path, resolved LAZILY. Never raises; "" when nothing
    resolves.

    WHY lazy: at SubagentStart time the agent's own transcript file does not exist yet (it is
    created once the agent starts producing turns), so the hook can only record `agentDir` —
    the `<session>/subagents` dir the file will eventually land under — not the file itself.
    This function does the deferred lookup at RESUME time, when the file has had a chance to
    appear.

    WHY rglob: a plain Agent-tool spawn's transcript sits directly at
    `<agentDir>/agent-<id>.jsonl`, but a workflow-spawned subagent's sits one level deeper at
    `<agentDir>/workflows/wf_<runid>/agent-<id>.jsonl` — the run id is not something this
    manifest ever learns, so a fixed-depth join cannot find it. rglob searches both shapes
    with one call; results are sorted first so a repeat call is deterministic even if more
    than one match somehow exists.
    """
    stored = str(entry.get("transcript", "") or "")
    if stored and Path(stored).is_file():
        return stored
    agent_dir = str(entry.get("agentDir", "") or "")
    agent_id = str(entry.get("agentId", "") or "").strip()
    if not agent_dir or not agent_id:
        return ""
    try:
        root = Path(agent_dir)
        direct = root / f"agent-{agent_id}.jsonl"
        if direct.is_file():
            return str(direct)
        matches = sorted(root.rglob(f"agent-{agent_id}.jsonl"))
        if matches:
            return str(matches[0])
    except OSError:
        return ""
    return ""


def respawn_prompt_for(entry: dict) -> str:
    """`respawn_prompt`, but resolving the transcript LAZILY via `resolve_transcript` first —
    the form every caller should use, since the manifest entry alone rarely carries a usable
    `transcript` (see `resolve_transcript`)."""
    return respawn_prompt(resolve_transcript(entry))


def spawn_prompt(transcript_path: str) -> str:
    """The original spawn prompt of an agent, read from the FIRST user message of its
    transcript. Empty string when it cannot be recovered.

    This is the only faithful source: SubagentStart's payload carries no prompt, so a
    respawn that does not read this is guessing at the job it is repeating.
    """
    try:
        path = Path(str(transcript_path or ""))
        if not path.is_file():
            return ""
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict) or rec.get("type") != "user":
                    continue
                msg = rec.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    joined = "\n".join(p for p in parts if p)
                    if joined:
                        return joined
        return ""
    except Exception:  # noqa: BLE001 - recovery must never raise into a hook or dispatch
        return ""


def respawn_prompt(transcript_path: str) -> str:
    """The full prompt to respawn an interrupted agent with, preamble included.

    Empty when the original could not be recovered — the caller must then say the job is
    unrecoverable rather than invent a replacement prompt, because a made-up prompt silently
    does a DIFFERENT job under the same name.
    """
    original = spawn_prompt(transcript_path)
    return f"{RESPAWN_PREAMBLE}{original}" if original else ""
