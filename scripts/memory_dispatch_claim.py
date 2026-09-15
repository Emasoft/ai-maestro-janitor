#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Claim one memory-maintenance dispatch — the CONSUMED flag the system never had (janitor#242).

`memory-maintenance` emits a bare `[janitor-memory-<chore>]` marker and records the
assignment on disk. The agent then has to find out WHICH assignment is its own, and until
now it was told to read `memory-maint-pending.json` — a single fixed slot the NEXT dispatch
overwrites unconditionally. Measured on a peer host: a `consolidate` dispatch overwrote an
in-flight `repair`'s authority 367 s later on the same root, while `pending-agents.json`
still listed the repair agent as running. The agent was reading a file that had changed
underneath it, and nothing anywhere said so.

`d5df92a7` fixed the WRITE side — every dispatch also gets its own immutable
`memory-maint-pending-<dispatch_id>.json`. But nothing ever NAMED that file to anybody: the
marker is bare (it must be — the cron clause matches it exactly) and the protocol rule still
pointed at the legacy slot. So the durable record existed and had no reader. This script is
the reader.

THE CLAIM IS THE POINT, not the lookup. `os.rename` is atomic on POSIX and on Windows for
this shape, so of two agents racing for the same dispatch exactly one wins and the loser
gets `FileNotFoundError` and moves to the next candidate. That gives three properties the
old fixed slot could not have:

  * an assignment is handed to exactly ONE agent, ever;
  * an agent's assignment cannot change after it is handed over (its file is renamed out of
    the candidate pool and never rewritten);
  * a dispatch that was never picked up stays visibly unclaimed, which is what makes
    `orphaned-memory-maint`'s question answerable at all.

FAIL CLOSED, DELIBERATELY. With no claimable dispatch this exits 2 and prints nothing on
stdout. It must never fall back to "whichever chore looks due" — that is janitor#150, where
a guessing agent ran a pass nobody scheduled, on a scope nobody chose.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import memory_settings  # noqa: E402
import orphaned_memory_maint as omm  # noqa: E402
import state  # noqa: E402

PENDING_PREFIX = "memory-maint-pending-"
CLAIMED_PREFIX = "memory-maint-claimed-"
EXPIRED_PREFIX = "memory-maint-expired-"
DONE_PREFIX = "memory-maint-done-"
LEGACY_NAME = "memory-maint-pending.json"
_EXPIRED_KEEP = 20  # mirrors memory-maintenance.py's own keep-20 prune for pending/claimed
# janitor#242 (2026-09-15 fleet audit + adversarial review): a real consolidate pass over a
# large corpus can legitimately hold a claim for hours, so age-only expiry using a fast
# chore's own cadence would let a fresh agent double-claim a dispatch a LIVE agent is still
# working. This floor is the minimum age ANY claim must reach before expiry, regardless of
# how short its chore's own cadence x factor is.
_STALE_CLAIM_FLOOR_S = 6 * 3600

# The known chores, derived from the one place that already enumerates them (never
# duplicated here) — `--chore` must be one of these, never empty (see main()).
CHORES: tuple[str, ...] = tuple(memory_settings.INTERVENTIONS)


def _dispatch_epoch(path: Path) -> tuple[int, str]:
    """Sort key: the epoch baked into `<epoch>-<hex>`, name as tie-break.

    Parsed rather than stat'd because mtime is not stable across a copy, a restore, or a
    filesystem that rounds it — and picking the wrong "oldest" hands an agent a newer
    assignment while the older one starves.
    """
    stem = path.name[len(PENDING_PREFIX):-len(".json")]
    head = stem.split("-", 1)[0]
    return (int(head) if head.isdigit() else 0, path.name)


def candidates(state_dir: Path) -> list[Path]:
    """Unclaimed per-dispatch files, oldest first. A claimed one is renamed away, so its
    absence from this list is the claim — there is no flag to read and get wrong."""
    try:
        return sorted(state_dir.glob(f"{PENDING_PREFIX}*.json"), key=_dispatch_epoch)
    except OSError:
        return []


def payload_matches_chore(payload: object, chore: str) -> bool:
    """True iff `payload` is a well-formed dispatch record whose `intervention` is
    exactly `chore`. No chore-blind branch: an empty or mismatched `chore` matches
    nothing, on purpose — a `[janitor-memory-split]` fire once claimed a queued
    `consolidate` record this way and burned 236k tokens (2026-09-15 fleet audit).
    Factored out of `claim_one`'s loop (TRDD-LDSCQ0NU) so `is_claimable` below
    checks a record with the EXACT SAME predicate a real claim would use, instead
    of a hand-rolled duplicate that could quietly drift from it."""
    if not isinstance(payload, dict):
        return False
    return str(payload.get("intervention") or "") == chore


def is_claimable(state_dir: Path, dispatch_id: str, chore: str) -> bool:
    """Read-only: would `claim_one(state_dir, chore)` be ABLE to claim the
    per-dispatch record named `dispatch_id`, right now? Never renames, never
    consumes — this is a verification read, not a claim.

    TRDD-LDSCQ0NU / janitor#300: `[janitor-memory-<chore>]` used to be printed the
    instant the scheduler decided a chore was due, with no check that the record it
    had just written was actually sitting in the claim pool the spawned agent would
    read from. When the two disagreed, the agent paid a full ~326k-token turn to
    discover there was nothing to claim. The scheduler calls this immediately after
    writing the dispatch, before printing the marker, using the SAME
    `payload_matches_chore` predicate `claim_one` itself applies — so "claimable"
    can never mean two different things in the two places that ask the question.
    """
    path = state_dir / f"{PENDING_PREFIX}{dispatch_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return payload_matches_chore(payload, chore)


class StateDirMismatch(Exception):
    """Raised by `claim_one` (TRDD-N1CPV1QV part (e)) when the oldest matching candidate's
    recorded `state_dir` disagrees with the directory the claim was actually invoked on —
    a spawning session composed the wrong project's path, and a real pool exists there, so
    it must be refused rather than silently reported as an empty pool."""

    def __init__(self, dispatch_id: str, expected: str, found: str) -> None:
        self.dispatch_id = dispatch_id
        self.expected = expected
        self.found = found
        super().__init__(
            f"dispatch {dispatch_id} was written for state_dir {found!r}, "
            f"not {expected!r} — refusing the claim"
        )


def claim_one(
    state_dir: Path, chore: str, expected_state_dir: Path | None = None
) -> dict | None:
    """Atomically claim the oldest unclaimed dispatch matching `chore`, else None.

    `chore` (janitor#275, and the root cause of #280 and #273) restricts the claim to
    dispatches whose `intervention` matches — REQUIRED, never blind. Every caller is
    chore-SPECIFIC: the heartbeat emits one marker (`[janitor-memory-atomize]`, say) and
    the agent it spawns loads that chore's skill. If the queue head belongs to a
    different chore, that agent claimed and consumed an assignment it cannot perform —
    the queue head is renamed out of the pool, so the dispatch that CAN be performed is
    orphaned and the wrong agent does nothing useful. Measured on this host as a
    permanently wedged atomize dispatch (janitor#273), and again 2026-09-15 as a
    `[janitor-memory-split]` fire consuming a queued `consolidate` record (236k tokens
    burned) — the FIFO-blind fallback this function used to fall back to on an empty
    `chore` is gone; call it with the exact chore or not at all.

    Reads BEFORE renaming: a rename we won is unrecoverable for anyone else, so if the read
    then failed the assignment would be lost with nothing left to point at it.
    """
    for path in candidates(state_dir):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # unreadable: leave it for the orphan detector to report, don't consume it
        # Filter BEFORE the rename — a mismatched dispatch must be left in the pool for the
        # agent that can actually run it, which is the whole point. Shared with
        # `is_claimable` (TRDD-LDSCQ0NU) so a read-only check and a real claim never
        # disagree about what counts as claimable.
        if not payload_matches_chore(payload, chore):
            continue
        # TRDD-N1CPV1QV (e): a record with no `state_dir` field at all predates this
        # field (older cached plugin version) — absence is a version gap, not evidence
        # of a wrong directory, so it is accepted with one log line, never refused.
        if expected_state_dir is not None:
            recorded = payload.get("state_dir")
            if not recorded:
                state.log_line(
                    "memory_dispatch_claim",
                    f"dispatch {payload.get('dispatch_id', '?')} has no state_dir field "
                    "(older payload) — accepted",
                )
            elif Path(recorded).expanduser().resolve() != expected_state_dir:
                raise StateDirMismatch(
                    payload.get("dispatch_id", "?"), str(expected_state_dir), recorded
                )
        target = state_dir / f"{CLAIMED_PREFIX}{path.name[len(PENDING_PREFIX):]}"
        try:
            os.rename(path, target)
        except OSError:
            continue  # lost the race (or it vanished) — try the next candidate
        _retire_legacy_mirror(state_dir, payload.get("dispatch_id", ""))
        payload["claimed_path"] = str(target)
        return payload
    return None


def _retire_legacy_mirror(state_dir: Path, dispatch_id: str) -> None:
    """Remove the legacy single-slot mirror IFF it describes the dispatch just claimed.

    The scheduler writes the same payload twice — once as `memory-maint-pending-<id>.json`
    (claimable, per-dispatch) and once as `memory-maint-pending.json`, because the installed
    `janitor-heartbeat-protocol` rule still names that fixed path and rules reach sessions on
    their own schedule, not with this code. Nothing ever removed the mirror, so it outlived
    every dispatch it described: janitor#264 reports it still naming `intervention: atomize`
    AFTER that pass had completed — 3 pages atomized, report written, lint 75 -> 35 findings —
    which makes a finished chore indistinguishable from a pending one for anything reading it.

    MATCHED ON dispatch_id, never cleared blindly. The mirror always holds the NEWEST dispatch,
    and the claim order is OLDEST-first, so claiming an older dispatch while a newer one is
    still queued must leave the mirror alone — deleting it there would strand the newer
    assignment for every reader that only knows the legacy path.

    Deliberately NOT a second clearing mechanism (the shape the advisor warned against): this
    is the existing claim path taking responsibility for the copy it renders obsolete. The
    mirror stays UNCLAIMABLE — `claim_one` never hands it to an agent, because its
    single-slot clobbering is exactly what per-dispatch files exist to fix (janitor#242).

    Best-effort: a mirror we fail to remove is stale state, while a raise here would lose an
    assignment already renamed out of the candidate list and unrecoverable for anyone else.
    """
    if not dispatch_id:
        return
    legacy = state_dir / LEGACY_NAME
    try:
        mirrored = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(mirrored, dict) and mirrored.get("dispatch_id") == dispatch_id:
        try:
            legacy.unlink()
        except OSError:
            return


def complete_claim(state_dir: Path, dispatch_id: str, outcome: str, *, now: int | None = None) -> bool:
    """Mark a claimed dispatch DONE by its own dispatch_id — the primary-key check-in
    that replaces the report-filename correlation `_pass_finished_since` used to guess
    at (janitor#242 adversarial review, 2026-09-15): a report carries no claim id, a
    split report is named `<ts>-split-<scope>-<page-slug>.md` (never matches the exact
    `-<chore>-<scope>` shape the old check assumed), the scope token's case could differ
    from the record's, a manual chore run writes the exact same filename shape as a
    scheduled one, and `reports/` is per-PROJECT while a USER/LOCAL claim's state_dir is
    not. The pass that finished is the one thing that actually knows it finished — so it
    says so, by id, instead of the claim script inferring it from a filename that was
    never designed to be machine-readable evidence.

    Idempotent: completing an already-done id is success, not an error — a retry after a
    lost reply, or a duplicate `complete` call, must not fail. Returns False only when
    `dispatch_id` names neither a claimed nor an already-done record — an unknown id,
    which the CLI reports and exits non-zero for.
    """
    done_path = state_dir / f"{DONE_PREFIX}{dispatch_id}.json"
    if done_path.is_file():
        return True
    claimed_path = state_dir / f"{CLAIMED_PREFIX}{dispatch_id}.json"
    try:
        payload = json.loads(claimed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    payload["completed_at"] = now if now is not None else int(datetime.now().timestamp())
    payload["outcome"] = outcome
    try:
        done_path.write_text(json.dumps(payload), encoding="utf-8")
        claimed_path.unlink()
    except OSError:
        return False
    return True


def _prune_named(state_dir: Path, prefix: str, *, keep: int = _EXPIRED_KEEP) -> None:
    """Keep only the newest `keep` files under `prefix` — mirrors memory-maintenance.py's
    own keep-20 prune for pending/claimed files, applied here because `done`/`expired` are
    new prefixes nothing else in the pipeline sweeps."""
    files = sorted(state_dir.glob(f"{prefix}*.json"))
    for stale in (files[:-keep] if len(files) > keep else []):
        try:
            stale.unlink()
        except OSError:
            pass


def expire_stale_claims(state_dir: Path, now: int, max_age_s: float) -> list[dict]:
    """Reclaim claimed dispatches whose owning agent is provably gone (janitor#242,
    2026-09-15 fleet audit: 11 claimed records aged 16h-5d, permanently un-reclaimable —
    a claim has no "consumed" flag once its agent dies, so the slot was gone for good).

    A finished pass now checks itself in BY DISPATCH ID via `complete_claim` (the
    `memory_dispatch_claim.py complete` subcommand), the moment its report is written —
    that rename to `memory-maint-done-<id>.json` happens THERE, not here (the report-
    filename correlation this function used to do itself was a coincidence match, not a
    primary key — see `complete_claim`'s docstring for the failure modes it had). This
    function's only remaining job is the DEATH-PRESUMPTION path: age alone is not proof
    of death (the adversarial review that caught the original version), so a claimed
    record still sitting here (never explicitly completed) is only expired once its age
    exceeds `max(max_age_s, THIS RECORD'S OWN cadence x factor, _STALE_CLAIM_FLOOR_S)`.
    The per-record cadence (not one blanket value swept over every file) is what stops a
    fast chore's threshold from expiring a different, slower chore's still-healthy claim;
    `max_age_s` is a caller-supplied additional floor (pass 0 to let each record's own
    chore decide).

    # why: `_STALE_CLAIM_FLOOR_S` (6h) is a HARD MINIMUM regardless of the record's own
    # cadence x factor — a LOCAL scope's `LOCAL_FACTOR` of 1 means a chore cadence faster
    # than 6h (e.g. 4h) would otherwise expire a claim before a real pass could plausibly
    # finish it; the floor overrides that, never the reverse.

    Malformed/unreadable claimed files are left alone — a different, already-reported
    finding (MEMPASS-MALFORMED), not this function's job to clean up. Returns one dict per
    record expired: `{"dispatch_id", "intervention", "status": "expired", "age_s",
    "cadence_s", "scope"}`.
    """
    acted: list[dict] = []
    for path in sorted(state_dir.glob(f"{CLAIMED_PREFIX}*.json")):
        payload, malformed = omm.read_record(path)
        if malformed or payload is None:
            continue
        dispatch_id = path.name[len(CLAIMED_PREFIX):-len(".json")]
        chore = payload["intervention"]
        scope = payload["scope"]

        try:
            cadence_s = memory_settings.interval_s_for(chore)
        except ValueError:
            # ponytail: a renamed/retired chore makes this claim immortal (never expired,
            # matching is_orphaned's "disabled never orphans" convention) rather than
            # fail-loud — log it so a stuck claim under a dead chore name is at least
            # visible, upgrade to a MEMPASS finding if this is ever seen in practice.
            state.log_line(
                "memory_dispatch_claim",
                f"claimed dispatch {dispatch_id} has unknown intervention {chore!r} — "
                "never expiring it on cadence grounds",
            )
            cadence_s = math.inf
        factor = omm.factor_for_scope(scope)
        cadence_threshold = cadence_s * factor if math.isfinite(cadence_s) else math.inf
        threshold = max(max_age_s, cadence_threshold, _STALE_CLAIM_FLOOR_S)

        age_s = omm.pending_age_s(payload, now=now)
        if age_s < threshold:
            continue
        target = state_dir / f"{EXPIRED_PREFIX}{dispatch_id}.json"
        try:
            path.rename(target)
        except OSError:
            continue  # lost the race — leave it for the next sweep
        print(f"MEMPASS-EXPIRED {dispatch_id} {chore} age={age_s}")
        acted.append({
            "dispatch_id": dispatch_id, "intervention": chore, "status": "expired",
            "age_s": age_s, "cadence_s": cadence_s, "scope": scope,
        })

    _prune_named(state_dir, DONE_PREFIX)
    _prune_named(state_dir, EXPIRED_PREFIX)
    return acted

def _run_complete(argv: list[str]) -> int:
    """`complete <dispatch_id> --state-dir <dir> --outcome noop|mutation` — the CLI
    surface for `complete_claim` (see its docstring for why a dispatch checks itself in
    by id instead of the claim script inferring completion from a report filename)."""
    ap = argparse.ArgumentParser(
        prog="memory_dispatch_claim.py complete",
        description="Mark a claimed memory-maintenance dispatch DONE, by dispatch_id.",
    )
    ap.add_argument("dispatch_id")
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--outcome", required=True, choices=("noop", "mutation"))
    args = ap.parse_args(argv)
    state_dir = Path(args.state_dir)
    if complete_claim(state_dir, args.dispatch_id, args.outcome):
        return 0
    print(
        f"memory_dispatch_claim: no claimed (or already-done) dispatch "
        f"{args.dispatch_id!r} in {state_dir}",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    # `complete` is a distinct sub-mode (janitor#242 review) checked BEFORE the claim
    # parser below is built — it never collides with `--chore` (required there, absent
    # here), and no existing caller ever passes "complete" as its first argument.
    argv = sys.argv[1:]
    if argv and argv[0] == "complete":
        return _run_complete(argv[1:])

    ap = argparse.ArgumentParser(description=__doc__)
    # default=None (not "") so an EXPLICITLY empty --state-dir is distinguishable from
    # "not given at all" (TRDD-N1CPV1QV part (c)) — a bare falsy check below would treat
    # both the same and silently fall back to cwd resolution.
    ap.add_argument("--state-dir", default=None, help="override the project's .janitor/state")
    ap.add_argument("--peek", action="store_true",
                    help="report the next claimable dispatch WITHOUT claiming it")
    ap.add_argument("--chore", required=True, choices=CHORES,
                    help="claim ONLY a dispatch whose intervention matches (janitor#275) — "
                         "REQUIRED: a chore-blind claim let a [janitor-memory-split] fire "
                         "consume a queued 'consolidate' record and burn 236k tokens "
                         "(2026-09-15 fleet audit)")
    args = ap.parse_args(argv)

    if args.state_dir is not None and args.state_dir.strip() == "":
        print(
            "memory_dispatch_claim: --state-dir was given but empty — refusing to silently "
            "fall back to cwd resolution",
            file=sys.stderr,
        )
        return 4

    state_dir = Path(args.state_dir) if args.state_dir else state.state_dir()
    expected_state_dir = state_dir.expanduser().resolve()

    # TRDD-N1CPV1QV part (e): a dir with NO memory-maint-* files at all is a wrong dir,
    # however it was obtained. The scheduler writes its record BEFORE emitting the marker,
    # so a correct state dir always holds at least one memory-maint-* file — an explicit
    # --state-dir with none is just as wrong as a cwd-resolved one (e.g. a skill that pasted
    # its literal "<the absolute path from the STATE_DIR=<path> line ...>" placeholder
    # verbatim used to exit 2 here, the "nothing claimable" code every skill treats as a
    # correct abstain, so the wrong path was silent). Distinct from the ordinary "pool
    # present but nothing claimable" exit 2 below.
    if not any(state_dir.glob("memory-maint-*")):
        origin = "--state-dir given" if args.state_dir is not None else "cwd-resolved, no --state-dir given"
        print(
            f"memory_dispatch_claim: no memory-maintenance state at all in {state_dir} "
            f"({origin}) — probably the wrong project root, or this project has never "
            "dispatched a memory pass",
            file=sys.stderr,
        )
        return 3

    if args.peek:
        nxt = candidates(state_dir)
        if not nxt:
            print("no claimable dispatch", file=sys.stderr)
            return 2
        print(nxt[0])
        return 0

    try:
        payload = claim_one(state_dir, args.chore, expected_state_dir=expected_state_dir)
    except StateDirMismatch as exc:
        print(f"memory_dispatch_claim: {exc}", file=sys.stderr)
        return 5
    if payload is None:
        # The legacy single slot is NOT a fallback. It is the very file whose clobbering
        # this exists to fix, so consuming it here would reintroduce the bug on exactly the
        # path where two dispatches overlap — the only path where it matters.
        legacy = state_dir / LEGACY_NAME
        hint = " (a legacy pending slot exists but is not claimable — it is not per-dispatch)" \
            if legacy.is_file() else ""
        print(f"no claimable memory-maintenance dispatch in {state_dir}{hint}", file=sys.stderr)
        return 2
    print(json.dumps(payload))
    # A SEPARATE, greppable line (never folded into the JSON above) so a skill can
    # `grep '^CLAIM_ID='` for the id it must pass to `complete` later, without ever
    # having to parse the JSON — and so every existing parser of the JSON line keeps
    # seeing exactly the same bytes it always has.
    print(f"CLAIM_ID={payload.get('dispatch_id', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
