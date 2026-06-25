#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""memory-maintenance — the wikimem-editor SCHEDULER (TRDD-b4b9e27c, the SCHEDULE layer).

This is the SCHEDULE half of the wikimem editor (the plan's four layers:
DETECT → SCHEDULE → EXECUTE → VERIFY). The DETECT layer (`memory-librarian`)
SURFACES reorg candidates; this detector decides WHEN an editorial pass is due,
deduplicates it MACHINE-WIDE, and emits a single forge-proof marker the cron turn
acts on. It NEVER reads the corpus, never runs memgrep, never mutates a page — it
only EMITS one of six bare markers:

    [janitor-memory-split]       → dispatch a background opus agent: /janitor-memory-split
    [janitor-memory-repair]      → dispatch a background opus agent: /janitor-memory-repair
    [janitor-memory-atomize]     → dispatch a background opus agent: /janitor-memory-atomize
    [janitor-memory-harvest]     → dispatch a background opus agent: /janitor-memory-harvest
    [janitor-memory-consolidate] → dispatch a background opus agent: /janitor-memory-consolidate
    [janitor-memory-conflict]    → dispatch a background opus agent: /janitor-memory-conflict

The cron turn (the EXECUTE layer) interprets the marker; this detector cannot
spawn agents — the "a python detector cannot spawn agents, only the main loop can"
contract holds through CC 2.1.181. (TRDD-b4b9e27c STATE block.) Per TRDD-aebedbff the
cron turn does NOT run the editorial pass in its own context: it spawns exactly ONE
background opus agent (Agent tool, run_in_background) that reads & executes the matching
`janitor-memory-<name>` skill on the due scope and returns, fire-and-forget — so the
complex, verify-gated pass never burdens whatever main session fired the heartbeat.

Three load-bearing safety properties, each from a CRITICAL correction in the plan:

  * NEAR-FREE due-check — a `stat` + int-compare on the global last-run stamp via
    `memory_settings.is_due` (NO memgrep here). The heartbeat fires ~5 min; a fire
    with nothing due is essentially free.

  * MACHINE-WIDE dedupe — the scheduler "multiplies per session + starves roots" if
    naive (plan §[HIGH]). Two sessions firing the same heartbeat window would both
    pass `is_due` and both emit. So the whole pick→stamp→emit is serialized under ONE
    machine-wide flock (non-blocking, skip-if-held — the loser stays silent and the
    winner's `mark_ran` advances the stamp so the loser is no longer due). The stamps
    are keyed per (intervention × scope × concrete-root) under `global_state_dir()`,
    so LOCAL/USER dedupe globally while PROJECT keeps a per-repo cadence.

  * ROUND-ROBIN one scope per heartbeat — at most ONE marker per fire. A persisted
    rotation cursor rotates which scope gets first dibs across heartbeats so no scope
    starves; within the chosen scope the first DUE intervention (in a stable cost
    order) fires and ONLY that one is stamped (the rest stay due for a later fire =
    natural fairness). If the cursor's scope has nothing due, the cursor advances and
    the next scope is tried, so an idle scope-of-the-turn never wastes the heartbeat.

Gating (honored before anything is emitted):

  * `memory_txn.editor_enabled()` — the master kill gate (janitor kill-switch OR
    `CLAUDE_PLUGIN_OPTION_WIKIMEM_EDITOR_ENABLED=off`). Off → total no-op.
  * the PROJECT-scope gate — PROJECT memory is in-repo and the pre-push hook blocks
    every pusher except `publish.py`, so editing it defaults OFF; PROJECT is skipped
    unless `memory_settings.get("edit_project_scope")` is on.
  * a frequency of 0 (DISABLED) makes that intervention never due (`is_due` is False).

SECURITY — forge-proof marker. The marker is acted on by the cron turn ONLY when it
appears BARE/EXACT on its own line in the heartbeat STUB's OWN stdout (the cron
prompt's silent-execute clause keys on "a line of exactly `[janitor-memory-…]`").
This detector therefore emits the marker as a bare line and NOTHING ELSE on that
line, mirroring dispatch.py's marker-mimicry defense (`state.sanitize_for_drift_line`
defangs `[`/`]` and bidi controls in any UNTRUSTED text, so a forged
`[janitor-memory-*]` embedded in a TRDD title / note / directive file is rendered
`⟦janitor-memory-*⟧` and never matches the clause). Because emitting is the SOLE
side effect that can trigger a fan-out, and it only happens AFTER the flock + the
`is_due` check + `mark_ran`, a forged marker that did not go through this gate
cannot trigger a pass. (TRDD-b4b9e27c — "a forged marker does NOT trigger".)

Graceful no-op (never crashes the heartbeat): editor disabled, no scope roots,
nothing due, the flock held by a peer session, or any unexpected error → exit 0 with
no output.
"""

from __future__ import annotations

import errno
import fcntl
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import global_state  # noqa: E402
import memory_content_precheck  # noqa: E402
import memory_scopes  # noqa: E402
import memory_settings  # noqa: E402
import memory_txn  # noqa: E402
import state  # noqa: E402

# intervention -> the exact bare marker the cron turn's silent-execute clause keys
# on. Order is the round-robin priority WITHIN a chosen scope: split first (cheap,
# size-triggered), then repair (page-shape/metadata backfill), then harvest
# (incorporate stray MEMORY.md / loose .md memories into the wiki, once/day), then
# consolidate (merge), then conflict (the costly fact-verify).
_MARKERS: list[tuple[str, str]] = [
    ("split", "[janitor-memory-split]"),
    ("repair", "[janitor-memory-repair]"),
    ("atomize", "[janitor-memory-atomize]"),
    ("harvest", "[janitor-memory-harvest]"),
    ("consolidate", "[janitor-memory-consolidate]"),
    ("conflict", "[janitor-memory-conflict]"),
]

# The scopes the editor may act on, most-specific first (matches memory-librarian's
# LOCAL → PROJECT → USER ordering). PROJECT is gated (see _scopes_in_play).
_SCOPE_ORDER = ("LOCAL", "PROJECT", "USER")


# Scope resolution is the shared SSOT in scripts/lib/memory_scopes.py — extracted
# from this detector + memory-librarian, which carried byte-identical copies (a
# latent divergence bug the moment one was touched; TRDD-87935f21 priority #2).
# _scopes_in_play below layers THIS scheduler's PROJECT-gating on top of the
# shared three-scope resolution; the private alias keeps that call site unchanged.
_resolve_scope_dirs = memory_scopes.resolve_scope_dirs


def _scopes_in_play() -> list[tuple[str, Path]]:
    """The scope roots eligible for editing this fire — existing scopes minus the
    gated-off PROJECT scope. PROJECT is dropped unless the user opted in via
    `edit_project_scope`, because PROJECT memory is in-repo and unpushable outside
    `publish.py` (plan §[CRITICAL] PROJECT-memory commits are unpushable)."""
    edit_project = bool(memory_settings.get("edit_project_scope"))
    out: list[tuple[str, Path]] = []
    for label, root in _resolve_scope_dirs():
        if label == "PROJECT" and not edit_project:
            continue
        out.append((label, root))
    return out


# --------------------------------------------------------------------------- #
# round-robin cursor — persisted machine-wide so the rotation survives across
# heartbeats and is shared by every session (no per-session drift in fairness).
# --------------------------------------------------------------------------- #

def _cursor_path() -> Path:
    return global_state.global_state_dir() / "memory-maint-rr-cursor.ts"


def _read_cursor() -> int:
    return state.read_int_state(_cursor_path(), default=0)


def _write_cursor(value: int) -> None:
    global_state.init_global_state()
    state.atomic_write(_cursor_path(), str(int(value)))


# --------------------------------------------------------------------------- #
# the machine-wide dispatch flock — serialises pick→stamp→emit across sessions.
# A dedicated lock file under global_state_dir(), non-blocking + skip-if-held, in
# the same idiom as global_state.{marketplace,oauth_rotator}_lock (kept local to
# this detector so the SCHEDULE layer adds no surface to shared global_state.py;
# it is detector glue, not a reusable lib primitive). Distinct from
# memory_txn.commit_lock — that per-scope lock guards the EXECUTOR's actual page
# swap; this one guards only the scheduler's decision-to-emit.
# --------------------------------------------------------------------------- #

def _dispatch_lock_path() -> Path:
    return global_state.global_state_dir() / "memory-maint-dispatch.lock"


def _acquire_dispatch_lock() -> int | None:
    """Non-blocking exclusive flock. fd on success, None when a peer holds it
    (caller MUST then skip this fire — never block; the heartbeat re-fires)."""
    global_state.init_global_state()
    fd = os.open(str(_dispatch_lock_path()), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (BlockingIOError, OSError) as exc:
        try:
            os.close(fd)
        finally:
            pass
        if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in (
            errno.EAGAIN, errno.EWOULDBLOCK,
        ):
            return None
        # Unexpected — log, but never crash the heartbeat.
        state.log_line("memory-maintenance", f"unexpected dispatch-lock flock error: {exc}")
        return None


def _release_dispatch_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# the scheduling decision (pure given a clock + the resolved scopes)
# --------------------------------------------------------------------------- #

def _split_max_bytes() -> int:
    """The split size cap (memory_settings split_max_bytes) as an int, or 0 if it
    can't be read — 0 makes content_has_work fail-open for split (never suppress a
    chore on a config glitch; suppressing only ever happens on a PROVEN-idle scope)."""
    try:
        return int(memory_settings.get("split_max_bytes"))
    except (ValueError, TypeError):
        return 0


def _first_due_intervention(scope: str, root: Path, now: int) -> str | None:
    """The first intervention for (scope, root) that is BOTH cadence-due AND has
    actual work, in the stable cost order, or None.

    Cadence-due (`is_due`) is NEAR-FREE (a stat + int-compare on the global stamp).
    The content precheck (`memory_content_precheck.content_has_work`) is a cheap,
    zero-LLM filesystem check that suppresses a cadence-due chore with NOTHING to do
    so it never spawns a ~226-240k no-op opus agent (TRDD-3XS3PDCF, TRDD-8UD3Q7K5).
    It is FAIL-OPEN: only a chore whose idleness is cheaply proven (today: SPLIT's
    size gate, and CONSOLIDATE's structural "no legal-merge pair" gate — issue #64)
    is suppressed; every other chore returns work=True and keeps its cadence-only
    behavior. Because a suppressed chore is simply NOT returned here, it is never
    picked and never stamped (`mark_ran`) — so it re-checks every heartbeat and
    emits the instant work appears (Option A), with NO second cadence gate (the
    scheduler stays the sole cadence authority; the agent still trusts the marker).
    The `and` short-circuits, so the filesystem check runs ONLY for an already
    cadence-due intervention; a fire where nothing is cadence-due stays a pure
    stat-compare. A split that is cadence-due but content-suppressed is not stamped,
    so it stays due and re-checks (a cheap rglob, zero LLM, NO agent spawn) on each
    fire until a page goes over the cap — the deliberate Option-A trade (TRDD-3XS3PDCF):
    ~288 trivial filesystem scans/day instead of ~4.5 240k-token no-op agent spawns."""
    split_cap = _split_max_bytes()
    for intervention, _marker in _MARKERS:
        if memory_settings.is_due(intervention, scope, root, now) and \
           memory_content_precheck.content_has_work(
               intervention, root, split_max_bytes=split_cap
           ):
            return intervention
    return None


def _pick(scopes: list[tuple[str, Path]], cursor: int, now: int) -> tuple[int, str, str, Path] | None:
    """Round-robin pick: starting at `cursor`, return the first scope (in rotation
    order) that has a due intervention, as (next_cursor, intervention, scope_label,
    root). None when nothing is due in any scope.

    `next_cursor` advances PAST the chosen scope so the next heartbeat gives a
    different scope first dibs (fairness). When nothing is due, the cursor is left
    unchanged (no rotation churn on an idle fire)."""
    n = len(scopes)
    if n == 0:
        return None
    for offset in range(n):
        idx = (cursor + offset) % n
        label, root = scopes[idx]
        intervention = _first_due_intervention(label, root, now)
        if intervention is not None:
            return ((idx + 1) % n, intervention, label, root)
    return None


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main() -> int:
    # `--one-shot` is the dispatch.py contract; we accept it (and ignore other args)
    # so the detector is a drop-in roster member.
    _ = sys.argv

    # Master kill gate — off → total no-op (also covers the janitor kill-switch).
    if not memory_txn.editor_enabled():
        return 0

    scopes = _scopes_in_play()
    if not scopes:
        return 0

    now = int(time.time())

    # Cheap pre-check OUTSIDE the lock: is anything due at all? Avoids taking the
    # flock on the overwhelmingly-common idle fire. (The authoritative check is
    # re-done under the lock to close the check-then-stamp race.)
    if _pick(scopes, _read_cursor(), now) is None:
        return 0

    fd = _acquire_dispatch_lock()
    if fd is None:
        # A peer session holds the dispatch lock this fire — skip silently. It will
        # stamp whatever it fires, so we are no longer due; the heartbeat re-fires.
        state.log_line("memory-maintenance", "dispatch lock held by a peer — skipped this fire")
        return 0
    try:
        # Re-read the cursor + re-pick UNDER the lock — a peer that just released the
        # lock may have advanced the cursor and stamped an intervention, so the
        # pre-check decision could be stale.
        cursor = _read_cursor()
        picked = _pick(scopes, cursor, now)
        if picked is None:
            return 0
        next_cursor, intervention, scope_label, root = picked

        # Stamp BEFORE emitting: the stamp is the cross-session dedupe oracle. If we
        # crashed between stamp and emit the worst case is one skipped pass (it
        # re-surfaces next cadence) — strictly safer than emitting-then-crashing,
        # which could let a peer also emit. Only the fired intervention is stamped,
        # so the other due interventions stay due for a later heartbeat (fairness).
        memory_settings.mark_ran(intervention, scope_label, root, now)
        _write_cursor(next_cursor)

        marker = dict(_MARKERS)[intervention]
        state.log_line(
            "memory-maintenance",
            f"due: {intervention} @ {scope_label} ({root}) — emitting {marker}",
        )
        # The marker MUST be bare/exact on its own line (the cron clause keys on
        # that). NEVER routed through sanitize_for_drift_line — that is for UNTRUSTED
        # text; this is our own trusted, constant marker, and defanging it would
        # break the silent-execute clause. The forge-proofing lives in the cron
        # prompt (act only on a bare line in the stub's OWN stdout) + the fact that
        # this emit is the sole fan-out trigger and only fires post-flock/post-stamp.
        print(marker)
    finally:
        _release_dispatch_lock(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
