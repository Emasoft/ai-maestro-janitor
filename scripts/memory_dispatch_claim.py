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

import re
import subprocess  # noqa: E402 (module-level statements above force this out of top-of-file order)

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


def _matching_records(
    state_dir: Path, prefix: str, chore: str | None, scope: str | None
) -> list[tuple[str, dict]]:
    """`(dispatch_id, payload)` pairs for every well-formed record under `prefix` whose
    `intervention`/`scope` match the given filters — `None` accepts anything. Shared by
    `_resolve_claim` (over `CLAIMED_PREFIX`) and `complete`'s already-expired fallback
    (over `EXPIRED_PREFIX`), so the two never apply the filter differently."""
    out: list[tuple[str, dict]] = []
    for path in sorted(state_dir.glob(f"{prefix}*.json")):
        payload, malformed = omm.read_record(path)
        if malformed or payload is None:
            continue
        if chore is not None and str(payload.get("intervention") or "") != chore:
            continue
        if scope is not None and str(payload.get("scope") or "") != scope:
            continue
        out.append((path.name[len(prefix):-len(".json")], payload))
    return out

def _reports_dir_candidates(state_dir: Path) -> list[Path]:
    """Ordered, de-duplicated report-dir candidates for `state_dir`'s project — the
    MAIN checkout's reports dir first (when `git worktree list` resolves it), then the
    project's own grandparent reports dir as a fallback (janitor#264: a report written
    under a linked worktree dies with the branch, so a reader must never rely on the
    worktree path alone).

    Returns a LIST, not a single path, because the skeleton writer and the matcher
    (`_find_completion_report`) run in different processes at different times: one call
    to `git worktree list` can succeed while a later one fails (git missing from PATH,
    the 5s timeout, a `.git` lock) — if each independently picked ONE resolved path,
    a skeleton written at the main root would be invisible to a matcher that could only
    resolve the grandparent (2026-09-16 review of this same TRDD). The writer uses
    `candidates[0]`; the matcher globs every candidate, so either resolving or not
    resolving git still finds the same file.

    De-duplicated by RESOLVED path, not the raw string (2026-09-16 follow-up): a
    symlinked project root makes `git worktree list` print the canonical path while
    `state_dir.parent.parent` is still the symlink spelling — two different strings for
    one directory, so the string-equality check below let both through, and every
    report under it was globbed and matched twice. `Path.resolve()` collapses the
    symlink so the true directory is only ever listed once; the kept spelling is
    whichever the caller passed in first, so `candidates[0]` is unchanged for the
    writer.
    """
    project = state_dir.parent.parent
    grandparent = project.joinpath(*_REPORT_SUBDIR)
    try:
        result = subprocess.run(
            ["git", "-C", str(project), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        first_line = result.stdout.splitlines()[0]
        main_root = Path(first_line[len("worktree "):]) if first_line.startswith("worktree ") else None
    except (OSError, subprocess.SubprocessError, IndexError):
        main_root = None
    if main_root is None:
        return [grandparent]
    main_reports = main_root.joinpath(*_REPORT_SUBDIR)
    if main_reports.resolve() == grandparent.resolve():
        return [main_reports]
    return [main_reports, grandparent]


_REPORT_SUBDIR = ("reports", "janitor-memory-subconscious-agent")
_HEADER_SCAN_LINES = 20
_OUTCOME_RE = re.compile(r"<!--\s*janitor-outcome:\s*(mutation|noop[^>]*)\s*-->")


def _find_completion_report(state_dir: Path, dispatch_id: str, stamped_at: int) -> tuple[str, bool] | None:
    """`(report_path, has_outcome_marker)` for the ONE report that names `dispatch_id`
    in its `Claim:` header (in the first `_HEADER_SCAN_LINES` lines) AND was written
    after the claim (mtime newer than `stamped_at`) under `state_dir`'s own project —
    `state_dir` is `<project>/.janitor/state`, so the project root is its grandparent,
    matching every caller (the real detector's `state.state_dir()`, and this module's
    tests, which never touch `state.project_root()` at all).

    Globs EVERY dir `_reports_dir_candidates` returns (janitor#264 review) — the
    skeleton may have landed at the main worktree root while THIS call's own
    `git worktree list` fails, so a single resolved dir is not enough to find it.
    De-duplicated by RESOLVED path (2026-09-16 follow-up, mirrors
    `_reports_dir_candidates`'s own fix): a symlinked project root can still slip a
    second, differently-spelled candidate past that function's own dedup (e.g. one
    candidate resolves cleanly and the other doesn't, or vice versa across two
    processes), and globbing the same real directory twice would double-count every
    file in it as two "matches" for one report — turning a single unambiguous report
    into a spurious multi-match ambiguity.

    The header alone is NOT proof of completion (janitor#242 correction): a chore skill
    writes its `Claim: dispatch_id=...` header at the START of a pass, so it names an
    in-flight report exactly as readily as a finished one. Since TRDD-I8AAJ3PG the claim
    step ALSO creates a header-only skeleton report itself, so a curator still on the old
    per-agent template that writes its own duplicate header produces a SECOND match for
    the same dispatch_id — exactly one of the two ever carries the `<!-- janitor-outcome -->`
    marker written on completion. So: exactly one match -> return it; several matches with
    exactly one marked -> return that one (the marker disambiguates skeleton from finished
    report); otherwise (zero matches, or several with zero or 2+ marked) -> `None` — an
    ambiguous or absent signal must never substitute for the cadence-based expiry this
    backs up.

    Boundary-anchored, not a bare substring (2026-09-16 adversarial review of this same
    TRDD): a plain `needle in text` would also match a LONGER id sharing this one's
    prefix (dispatch ids are `<epoch>-<hex>`, so a naive substring risks exactly that),
    or prose that merely mentions this id in passing (e.g. a "supersedes" note). The
    lookahead requires the id to end at a non-identifier character."""
    paths: list[Path] = []
    seen_resolved: set[Path] = set()
    for reports_dir in _reports_dir_candidates(state_dir):
        try:
            candidates_here = list(reports_dir.glob("*.md"))
        except OSError:
            continue
        for path in candidates_here:
            resolved = path.resolve()
            if resolved in seen_resolved:
                continue
            seen_resolved.add(resolved)
            paths.append(path)
    paths = sorted(paths)
    needle_re = re.compile(re.escape(f"dispatch_id={dispatch_id}") + r"(?![\w-])")
    matches: list[tuple[str, bool]] = []
    for path in paths:
        try:
            if path.stat().st_mtime <= stamped_at:
                continue
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        head = "\n".join(text.splitlines()[:_HEADER_SCAN_LINES])
        if not needle_re.search(head):
            continue
        matches.append((str(path), bool(_OUTCOME_RE.search(text))))
    if len(matches) == 1:
        return matches[0]
    marked = [m for m in matches if m[1]]
    if len(marked) == 1:
        return marked[0]
    return None


def _resolve_claim(
    state_dir: Path, cmd: str, chore: str | None, scope: str | None
) -> tuple[str, dict] | int:
    """Resolve the one in-flight CLAIMED dispatch matching (chore, scope) — both given, or
    neither. Replaces the retired `current-claim` marker file (2026-09-15 review of
    `4a5d3434`): the `memory-maint-claimed-<id>.json` record already carries
    `intervention`/`scope`, so a second file duplicating that state was pure risk — it
    could point at a claim that had since completed or expired — with no information the
    record itself did not already hold. Returns `(dispatch_id, payload)` on exactly one
    match; on zero or multiple matches, prints a diagnostic and returns the exit code 2
    the caller should return."""
    matches = _matching_records(state_dir, CLAIMED_PREFIX, chore, scope)
    if not matches:
        where = f" for {chore}/{scope}" if chore and scope else ""
        print(
            f"memory_dispatch_claim: {cmd}: no claim in flight{where} in {state_dir}",
            file=sys.stderr,
        )
        return 2
    if len(matches) > 1:
        listing = ", ".join(m[0] for m in matches)
        pick = "the positional dispatch_id" if cmd == "complete" else "--chore and --scope"
        print(
            f"memory_dispatch_claim: {cmd}: multiple claims in flight ({listing}) — "
            f"pass {pick} to pick one",
            file=sys.stderr,
        )
        return 2
    return matches[0]


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


def _resolve_report_path(report: str) -> str:
    """Absolutize a report path against the CALLING process's own cwd, right now — empty
    stays empty (see `complete_claim`'s docstring for why)."""
    return os.path.abspath(os.path.expanduser(report)) if report else report


def _write_report_on_claimed(state_dir: Path, dispatch_id: str, report: str) -> bool:
    """Atomically stamp `report` onto dispatch_id's CLAIMED record's `report` field.
    Shared by `set-report` and the claim step's own skeleton-report bookkeeping
    (TRDD-I8AAJ3PG) so there is exactly one place that knows how to do this atomically
    (temp file in the same directory, then `os.replace`). Returns False on a vanished
    record or a write failure; callers decide whether that is fatal (`set-report` is)
    or fail-open (the claim step's own skeleton write is)."""
    claimed_path = state_dir / f"{CLAIMED_PREFIX}{dispatch_id}.json"
    try:
        payload = json.loads(claimed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    payload["report"] = _resolve_report_path(report)
    tmp_path = claimed_path.with_name(claimed_path.name + ".tmp")
    try:
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp_path, claimed_path)
    except OSError:
        return False
    return True


def complete_claim(
    state_dir: Path, dispatch_id: str, report: str, *, now: int | None = None
) -> bool:
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

    `report` is the pass's own report path, recorded as-is on the done record for
    provenance — this function never opens it. A check-in is evidence the pass ran, not
    a verdict on what the report says (see `_run_complete`, which never refuses on an
    unreadable report either).

    Idempotent: completing an already-done id is success, not an error — a retry after a
    lost reply, or a duplicate `complete` call, must not fail. Returns False only when
    `dispatch_id` names neither a claimed, expired, nor an already-done record — an
    unknown id, which the CLI reports and exits non-zero for.

    Reads the source record from its CLAIMED file, or — for a claim the stale-claim sweep
    already expired out from under a slow-but-alive curator — its EXPIRED file (2026-09-15
    review of `4a5d3434`): a pass that reaches `complete` always closes cleanly, whichever
    pool its record currently sits in.
    """
    done_path = state_dir / f"{DONE_PREFIX}{dispatch_id}.json"
    if done_path.is_file():
        return True
    source_path = state_dir / f"{CLAIMED_PREFIX}{dispatch_id}.json"
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        source_path = state_dir / f"{EXPIRED_PREFIX}{dispatch_id}.json"
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
    payload["completed_at"] = now if now is not None else int(datetime.now().timestamp())
    # why: MEMPASS-REPORT-MISSING (orphaned_memory_maint) checks this path from any
    # project's cwd; a relative path stored by a curator with an output_path override
    # or unset $MAIN_ROOT would resolve against the wrong project (review 2026-09-15).
    # An empty report ("") is preserved as-is — the detector correctly flags it missing.
    payload["report"] = _resolve_report_path(report)
    try:
        done_path.write_text(json.dumps(payload), encoding="utf-8")
        source_path.unlink()
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

    Before actually expiring a record that crossed its threshold, check whether the
    curator already finished and just never ran `complete` (janitor#238 EHT,
    TRDD-I8AAJ3PG): `_find_completion_report` looks for exactly one report naming this
    `dispatch_id` in its header. A header match with no `janitor-outcome` marker is a
    pass still IN FLIGHT (the header is written at the START of a pass) — that is not
    evidence either way, so the record falls through to the ordinary age-based expiry
    below, unchanged. A header match WITH the marker closes the claim via `complete_claim`
    (status `"closed"`, not `"expired"`) instead of expiring it.

    Malformed/unreadable claimed files are left alone — a different, already-reported
    finding (MEMPASS-MALFORMED), not this function's job to clean up. An expired record
    is still completable: `complete_claim` reads a `memory-maint-expired-<id>.json` record
    when the CLAIMED one it expected is gone (2026-09-15 review of `4a5d3434`), so a
    slow-but-alive curator that reaches `complete` after its claim was reclaimed still
    closes cleanly instead of racing a re-dispatch of the same chore. Returns one dict per
    record acted on: `{"dispatch_id", "intervention", "status": "expired"|"closed", "age_s",
    "cadence_s", "scope"}` (a `"closed"` record also carries `"report"`).
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

        found = _find_completion_report(state_dir, dispatch_id, payload["stamped_at"])
        if found is not None:
            report_path, has_outcome = found
            if has_outcome and complete_claim(state_dir, dispatch_id, report_path, now=now):
                print(f"MEMPASS-CLOSED-FROM-REPORT {dispatch_id} {chore} report={report_path}")
                acted.append({
                    "dispatch_id": dispatch_id, "intervention": chore, "status": "closed",
                    "age_s": age_s, "cadence_s": cadence_s, "scope": scope,
                    "report": report_path,
                })
                continue
            # else: report exists but is still in flight (no outcome marker yet), or
            # `complete_claim` failed -- lost a race, or the CLAIMED file itself vanished
            # from under us (e.g. another sweep expired it first) -- either way, fall through to
            # ordinary cadence-based expiry below, unchanged.

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


def _run_set_report(argv: list[str]) -> int:
    """`set-report <path> --state-dir <dir> [--chore <chore> --scope <scope>]` — records the
    current pass's report path directly onto its CLAIMED record's `report` field, so a
    later argument-less `complete` can pick it up. Exists because shell variables set in
    one Bash tool call do not survive into the next one (2026-09-15 addendum) — a recipe
    calls this right after computing its report path, in the SAME Bash call, so the value
    is never lost to a later call's fresh shell.

    `--chore`/`--scope` are OPTIONAL, matching arg-less `complete` (janitor#242
    MEMPASS-REPORT-MISSING, 2026-09-15): no chore skill defines a `$SCOPE` shell variable,
    so a required `--scope` was always being called with an empty string, keying the report
    to `(chore, "")` while `claim_one` claimed under `(chore, <real scope>)` — the report
    was silently unfindable by `complete`. Passing neither flag resolves the single
    in-flight claim via `_resolve_claim` (exit 2 if zero or multiple are in flight).
    Passing exactly one of the two is always an error, as is an empty string for either —
    a silently-empty scope is the exact bug this fixes, so it must fail loud, not fall
    back.

    The atomic write itself lives in `_write_report_on_claimed` (shared with the claim
    step's own skeleton-report bookkeeping, TRDD-I8AAJ3PG) — this function only resolves
    which claim is being written to and turns a `False` into the right exit code."""
    ap = argparse.ArgumentParser(
        prog="memory_dispatch_claim.py set-report",
        description="Record the current pass's report path onto its CLAIMED record.",
    )
    ap.add_argument("path")
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--chore", default=None, choices=CHORES)
    ap.add_argument("--scope", default=None)
    args = ap.parse_args(argv)
    state_dir = Path(args.state_dir)

    if args.scope is not None and args.scope == "":
        print("memory_dispatch_claim: set-report: empty --scope", file=sys.stderr)
        return 2
    if (args.chore is None) != (args.scope is None):
        print(
            "memory_dispatch_claim: set-report: --chore and --scope must be given "
            "together, or neither",
            file=sys.stderr,
        )
        return 2

    resolved = _resolve_claim(state_dir, "set-report", args.chore, args.scope)
    if isinstance(resolved, int):
        return resolved
    dispatch_id, _payload = resolved

    if not _write_report_on_claimed(state_dir, dispatch_id, args.path):
        print(
            f"memory_dispatch_claim: set-report: claim {dispatch_id} vanished before "
            "the report could be recorded",
            file=sys.stderr,
        )
        return 2
    return 0


def _run_complete(argv: list[str]) -> int:
    """`complete [<dispatch_id>] --state-dir <dir> [--report <path>] [--chore <c> --scope <s>]`
    — the CLI surface for `complete_claim` (see its docstring for why a dispatch checks
    itself in by id instead of the claim script inferring completion from a report
    filename). `--report` is recorded as-is on the done record for provenance; its content
    is never read.

    `dispatch_id` and `--report` are OPTIONAL (2026-09-15 addendum): a skill recipe's
    `claim` and `complete` steps can land in separate Bash tool calls, and shell
    variables do not survive that boundary. When `dispatch_id` is omitted, `--chore`/
    `--scope` must be given together or neither (mismatched pair is exit 2, same rule
    `set-report` enforces): given both, `_resolve_claim` picks the one matching CLAIMED
    record directly, and — for this explicit-flags form only — a claim already reclaimed
    by `expire_stale_claims` is also accepted from the EXPIRED pool with a warning (the
    M-i guarantee: a pass that reaches `complete` always closes cleanly); given neither,
    `_resolve_claim` picks the single in-flight CLAIMED claim unambiguously (exit 2 if
    zero or multiple are in flight). Passing `dispatch_id` explicitly works exactly as
    before, deriving whichever of chore/scope/report is missing from the CLAIMED (or
    EXPIRED) record itself. `--report`, when given, always wins over whatever the record
    already carries — a one-line stderr note says so when the two disagree. An empty
    `--scope` is always an error (exit 2) rather than a silent empty-string key."""
    ap = argparse.ArgumentParser(
        prog="memory_dispatch_claim.py complete",
        description="Mark a claimed memory-maintenance dispatch DONE, by dispatch_id.",
    )
    ap.add_argument("dispatch_id", nargs="?", default="")
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--report", default=None, help="path to the pass's report (recorded, not parsed)")
    ap.add_argument("--chore", default=None, choices=CHORES)
    ap.add_argument("--scope", default=None)
    args = ap.parse_args(argv)
    state_dir = Path(args.state_dir)

    if args.scope is not None and args.scope == "":
        print("memory_dispatch_claim: complete: empty --scope", file=sys.stderr)
        return 2

    dispatch_id = args.dispatch_id
    chore, scope = args.chore, args.scope
    record_report = ""
    if not dispatch_id:
        if (chore is None) != (scope is None):
            print(
                "memory_dispatch_claim: complete: --chore and --scope must be given "
                "together, or neither, when no dispatch_id is given",
                file=sys.stderr,
            )
            return 2
        resolved = _resolve_claim(state_dir, "complete", chore, scope)
        if isinstance(resolved, int):
            if chore and scope:
                expired = _matching_records(state_dir, EXPIRED_PREFIX, chore, scope)
                if len(expired) != 1:
                    return resolved
                dispatch_id, payload = expired[0]
                print(
                    f"memory_dispatch_claim: complete: {dispatch_id} for {chore}/{scope} "
                    "had already expired — closing it anyway",
                    file=sys.stderr,
                )
            else:
                return resolved
        else:
            dispatch_id, payload = resolved
        chore, scope = chore or str(payload.get("intervention") or ""), scope or str(payload.get("scope") or "")
        record_report = str(payload.get("report") or "")
    else:
        # explicit dispatch_id — derive whichever of chore/scope/report is missing from
        # the CLAIMED record, or the EXPIRED one when the claim has since been reclaimed.
        for prefix in (CLAIMED_PREFIX, EXPIRED_PREFIX):
            try:
                found = json.loads((state_dir / f"{prefix}{dispatch_id}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(found, dict):
                chore = chore or str(found.get("intervention") or "") or None
                scope = scope or str(found.get("scope") or "") or None
                record_report = str(found.get("report") or "")
            break

    report = args.report
    if report is not None and record_report and report != record_report:
        print(
            f"memory_dispatch_claim: complete: --report {report!r} overrides the "
            f"record's own report {record_report!r}",
            file=sys.stderr,
        )
    if report is None:
        report = record_report

    # why: an unreadable/missing report is evidence about the report, not about whether
    # the pass ran — refusing to close the claim here would leave it open until the 6h
    # expiry and re-dispatch a pass that already finished, filing a spurious HIGH finding
    # (janitor#242 review, 2026-09-15). The claim closes either way; only the stderr line
    # differs.
    if report:
        try:
            Path(report).open("rb").close()
        except OSError:
            print(
                f"memory_dispatch_claim: complete: report unreadable ({report}), closed as unknown",
                file=sys.stderr,
            )
    if complete_claim(state_dir, dispatch_id, report):
        return 0
    print(
        f"memory_dispatch_claim: no claimed (or already-done) dispatch "
        f"{dispatch_id!r} in {state_dir}",
        file=sys.stderr,
    )
    return 2

def _run_report_path(argv: list[str]) -> int:
    """`report-path --state-dir <dir> [--chore <chore>] [--scope <scope>]` — prints the
    ONE in-flight claim's recorded `report` field, so a curator READS BACK the path
    `claim` (or `set-report`) already wrote instead of retyping it (janitor#242
    follow-up, 2026-09-16): a mistyped path used to abort the pass with the claim left
    open, since a missing/garbled header match makes the claim indistinguishable from
    an orphaned one.

    `--chore` and `--scope` are OPTIONAL and INDEPENDENT here (2026-09-16 follow-up) —
    unlike `set-report`/`complete`, which require them paired or absent, this verb lets
    a curator narrow by `--chore` alone: it always knows its own chore (`$PASS` in the
    agent template) but not necessarily a `--scope` shell variable at read-back time.
    Under two simultaneous curators on one project (e.g. repair + consolidate), naming
    `--chore` is what stops one from reading back the other's report path; omitting
    both falls back to `_resolve_claim`'s single-in-flight-claim resolution (exit 1 if
    zero or multiple are in flight). An empty string for either is always an error.

    Prints ONLY the bare path on stdout, nothing else — a caller does
    `REPORT_FILE="$(... report-path ...)"`, so a second line would corrupt the captured
    value. Exit 1 (not `_resolve_claim`'s own 2) on zero/multiple claims or an
    empty/missing `report` field — this verb's one job is "give me the path", and any
    of those is simply "no path to give"."""
    ap = argparse.ArgumentParser(
        prog="memory_dispatch_claim.py report-path",
        description="Print the in-flight claim's recorded report path.",
    )
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--chore", default=None, choices=CHORES)
    ap.add_argument("--scope", default=None)
    args = ap.parse_args(argv)
    state_dir = Path(args.state_dir)

    if args.scope is not None and args.scope == "":
        print("memory_dispatch_claim: report-path: empty --scope", file=sys.stderr)
        return 1

    resolved = _resolve_claim(state_dir, "report-path", args.chore, args.scope)
    if isinstance(resolved, int):
        return 1
    _dispatch_id, payload = resolved
    report = str(payload.get("report") or "")
    if not report:
        print("memory_dispatch_claim: report-path: claim has no report field", file=sys.stderr)
        return 1
    print(report)
    return 0


def main() -> int:
    # `complete`/`set-report`/`report-path` are distinct sub-modes (janitor#242 review,
    # 2026-09-15 addendum; report-path added 2026-09-16) checked BEFORE the claim parser
    # below is built — none collides with `--chore` (required there, absent here), and
    # no existing caller ever passes one of these three words as its first argument.
    argv = sys.argv[1:]
    if argv and argv[0] == "complete":
        return _run_complete(argv[1:])
    if argv and argv[0] == "set-report":
        return _run_set_report(argv[1:])
    if argv and argv[0] == "report-path":
        return _run_report_path(argv[1:])

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

    dispatch_id = payload.get("dispatch_id", "")
    scope = payload.get("scope") or ""
    root = payload.get("root") or expected_state_dir.parent.parent

    # TRDD-I8AAJ3PG: the curator was told to paste a header block into its OWN report
    # file, and skipped it — its claim was then reported as orphaned even though the
    # work was done. Creating the report file HERE, with the header already written,
    # removes that step entirely: the curator only has to APPEND. Fail OPEN — an
    # unwritable reports dir must never block a successful claim.
    #
    # The skeleton path is `expected_state_dir.parent.parent / reports/...`, which is
    # only meaningful when expected_state_dir IS `<project>/.janitor/state` (the shape
    # every real caller passes). A bare `--state-dir /tmp/x` would otherwise resolve to
    # `/reports/...` at the filesystem root, and a shallower-but-real dir would write the
    # skeleton beside some unrelated ancestor where nothing ever purges it. Skip the
    # skeleton entirely in that case and fall back to the pre-TRDD-I8AAJ3PG "REPORT
    # HEADER" printout below, which still works with no state-dir shape assumptions.
    report_path: Path | None
    if expected_state_dir.name != "state" or expected_state_dir.parent.name != ".janitor":
        print(
            "memory_dispatch_claim: --state-dir is not <project>/.janitor/state; "
            "no report skeleton created",
            file=sys.stderr,
        )
        report_path = None
    else:
        skeleton_path = (
            # candidates[0]: the main-checkout reports dir when git resolved it, else
            # the grandparent fallback (janitor#264) — see `_reports_dir_candidates`.
            _reports_dir_candidates(expected_state_dir)[0]
            / f"{datetime.now().astimezone().strftime('%Y%m%d_%H%M%S%z')}-{args.chore}-{scope.lower()}.md"
        )
        skeleton_header = (
            f"<!-- generated: {datetime.now().astimezone().isoformat()} by "
            "memory_dispatch_claim (claim step) -->\n"
            f"# {args.chore} pass — {scope} scope\n"
            f"Claim: dispatch_id={dispatch_id}, scope={scope}, root={root}\n\n"
        )
        try:
            skeleton_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                # Exclusive create: two claims for the same chore+scope in the same
                # wall-clock second would otherwise silently overwrite each other's
                # skeleton (2026-09-16 adversarial review) — fail loud into the
                # dispatch_id-suffixed fallback below instead of corrupting a sibling
                # claim's report.
                with skeleton_path.open("x", encoding="utf-8") as f:
                    f.write(skeleton_header)
            except FileExistsError:
                skeleton_path = skeleton_path.with_name(
                    skeleton_path.stem + f"-{dispatch_id}" + skeleton_path.suffix
                )
                with skeleton_path.open("x", encoding="utf-8") as f:
                    f.write(skeleton_header)
            _write_report_on_claimed(state_dir, dispatch_id, str(skeleton_path))
            report_path = skeleton_path
        except OSError as exc:
            print(f"memory_dispatch_claim: warning: could not create report skeleton: {exc}", file=sys.stderr)
            report_path = None

    print(json.dumps(payload))
    # A SEPARATE, greppable line (never folded into the JSON above) so a skill can
    # `grep '^CLAIM_ID='` for the id it must pass to `complete` later, without ever
    # having to parse the JSON — and so every existing parser of the JSON line keeps
    # seeing exactly the same bytes it always has.
    print(f"CLAIM_ID={dispatch_id}")
    if report_path is not None:
        print(f"REPORT_FILE={report_path}")
        print(
            "REPORT FILE created with the header already written — APPEND your report "
            f"to it: {report_path}"
        )
    else:
        # The curator template used to ask the agent to retype <DISPATCH_ID>/<SCOPE>/<ROOT>
        # placeholders into its own printf — a skipped-step-prone agent pastes the literal
        # placeholder text instead of the real values, so the header matches nothing and the
        # claim is reported as orphaned in silence. Printing the finished header line here
        # removes that transcription step entirely (janitor#242 follow-up, 2026-09-16).
        print("REPORT HEADER (paste as the first content lines of your report file, verbatim):")
    print(f"  # {args.chore} pass — {scope} scope")
    print(f"  Claim: dispatch_id={dispatch_id}, scope={scope}, root={root}")
    # Printed in the claiming agent's OWN transcript (janitor#242 orphaned-claim
    # follow-up, 2026-09-16) — an agent that finishes a pass and never runs `complete`
    # leaves the claim orphaned because the close command lived only in a reference
    # file it had to remember to open. Spelling it out here, right after the claim
    # succeeds, needs no memory of a separate doc. `--peek` never claims, so it never
    # reaches this line.
    print("CLOSE YOUR CLAIM WHEN DONE (mandatory; an unclosed claim is reported as orphaned):")
    print(
        f'  uv run --script --quiet "$CLAUDE_PLUGIN_ROOT/scripts/memory_dispatch_claim.py" '
        f'set-report --state-dir "{expected_state_dir}" "<your report file>"'
    )
    print(
        f'  uv run --script --quiet "$CLAUDE_PLUGIN_ROOT/scripts/memory_dispatch_claim.py" '
        f'complete --state-dir "{expected_state_dir}"'
    )
    print(
        f'  (if complete exits 2 with "multiple claims in flight", add '
        # `.get(key, "")` only substitutes on a MISSING key, not a `null` value — this
        # file's own `_run_complete`/`_resolve_claim` already guard the same field with
        # `or ""` (a payload with an explicit `"scope": null` would otherwise print the
        # literal text "None" into a command the curator copy-pastes verbatim).
        f'--chore {args.chore} --scope {scope})'
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
