#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""orphaned-memory-maint — notice a memory-maintenance pass that was scheduled and
never ran (janitor#238, TRDD-2112XCKO).

The scheduler (`memory-maintenance.py`) stamps a pending dispatch and prints a bare
`[janitor-memory-<chore>]` marker for the cron turn to hand to a background agent. When
that hand-off fails — a partially-installed plugin registry (#232's shape: skills
present, zero `ai-maestro-janitor:*` agents enumerable), a session that dies between
marker and spawn — the pending record just sits there. Nothing else notices: a dropped
pass and a completed one look identical from the janitor's side.

Confirmed live on #238 (four consecutive drops in one session, three of them LOCAL):
the broken-registry session's PYTHON detectors ran fine throughout — the agent-spawn
step that failed is entirely downstream of this script — so THIS check is self-
contained by design: it reads only this project's own
`.janitor/state/memory-maint-pending.json`, no fleet scan required. See
`scripts/lib/orphaned_memory_maint.py` for the full mechanism (why age alone is not
enough, and why LOCAL gets a tighter bound than USER/PROJECT).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dedupe  # noqa: E402
import findings_ledger  # noqa: E402
import memory_dispatch_claim  # noqa: E402
import memory_settings  # noqa: E402
import orphaned_memory_maint as omm  # noqa: E402
import state  # noqa: E402


def _evaluate_and_emit(
    payload: dict, *, key: str, seen: Path, now: int, default_factor: int, local_factor: int,
) -> None:
    """Apply the orphan rule to one well-formed record and print/ledger a finding if
    it fires. Shared by the legacy slot and every per-dispatch pool record so the two
    can never apply the rule differently."""
    intervention = payload["intervention"]
    scope = payload["scope"]
    root = payload["root"]

    try:
        cadence_s = memory_settings.interval_s_for(intervention)
    except ValueError:
        # An unknown intervention name — a scheduler/lib drift, not this project's fault.
        return

    last_run = memory_settings.read_last_run(intervention, scope, root)
    is_current = omm.pending_is_current(payload, last_run=last_run)
    age_s = omm.pending_age_s(payload, now=now)
    factor = omm.factor_for_scope(scope, default=default_factor, local=local_factor)
    orphaned = is_current and omm.is_orphaned(age_s, cadence_s, factor=factor)
    if not orphaned:
        # Healthy — clear any prior alert for this key so a FUTURE drop is reported
        # fresh rather than suppressed by a stale dedupe entry. A pool key embeds its
        # dispatch_id and is never reused, so this is a no-op there but matches the
        # legacy slot's re-arm behaviour.
        dedupe.emit_forget(seen, key)
        return

    msg = omm.format_finding(intervention, scope, age_s, cadence_s)
    line = dedupe.emit_once(seen, key, f"[orphaned-memory-maint] {msg}")
    if line is None:
        return  # already alerted for this exact drop

    try:
        findings_ledger.record(
            sev="HIGH", code="MEMPASS-ORPHANED", src="orphaned-memory-maint", msg=msg, now=now,
        )
    except Exception as exc:  # noqa: BLE001 - a ledger fault must never break the fire
        state.log_line("orphaned-memory-maint", f"ledger write failed: {exc}")

    state.log_line("orphaned-memory-maint", f"recorded MEMPASS-ORPHANED for {key} ({age_s}s)")
    print(line, flush=True)


def _check_claimed_pool(state_dir: Path, seen: Path, now: int) -> None:
    """Claimed dispatches whose owning agent may be dead (janitor#242, 2026-09-15 fleet
    audit: 11 such records aged 16h-5d). `memory_dispatch_claim.expire_stale_claims` does
    the actual per-record decision (its own chore's cadence x factor, the 6h floor) and
    the rename; this just reports the ones it EXPIRED as a MEMPASS-STALE-CLAIM finding.
    A record explicitly checked in via `complete_claim` (the `complete` subcommand) is
    renamed DONE before it ever reaches this sweep — never a finding."""
    try:
        acted = memory_dispatch_claim.expire_stale_claims(state_dir, now, 0)
    except Exception as exc:  # noqa: BLE001 - a sweep failure must never break the fire
        state.log_line("orphaned-memory-maint", f"expire_stale_claims failed: {exc}")
        return

    for record in acted:
        if record["status"] != "expired":
            continue
        dispatch_id = record["dispatch_id"]
        msg = omm.format_stale_claim(
            record["intervention"], record["scope"], record["age_s"], record["cadence_s"],
        )
        key = f"claim:{dispatch_id}"
        line = dedupe.emit_once(seen, key, f"[orphaned-memory-maint] {msg}")
        if line is None:
            continue  # already alerted for this exact expiry
        try:
            findings_ledger.record(
                sev="HIGH", code="MEMPASS-STALE-CLAIM", src="orphaned-memory-maint",
                msg=msg, now=now,
            )
        except Exception as exc:  # noqa: BLE001
            state.log_line("orphaned-memory-maint", f"ledger write failed: {exc}")
        state.log_line("orphaned-memory-maint", f"recorded MEMPASS-STALE-CLAIM for {key}")
        print(line, flush=True)


def _check_done_pool(state_dir: Path, seen: Path, now: int) -> None:
    """Done records whose recorded `report` path does not exist on disk (c0cbf97d review):
    `complete_claim` now closes a claim even when `--report` is unreadable, storing whatever
    path it was given verbatim. A typo/moved report then closes SILENTLY — the claim reads
    as healthy forever after. This does not reopen the claim (the pass itself DID run and
    check in); it only flags the mismatch so a human can look. Bounded to records completed
    within the last 7 days, or until pruned by `_prune_named`'s keep-20 policy, whichever
    is sooner -- a busy corpus can retire a done record before 7 days elapse, and this
    check simply never sees it (an old miss is not this heartbeats concern any more); and
    deduped per dispatch_id (the state file `seen` already gives us fire-once for free) so
    a permanently-missing report does not repeat every heartbeat."""
    try:
        pool = sorted(state_dir.glob(f"{memory_dispatch_claim.DONE_PREFIX}*.json"))
    except OSError as exc:
        state.log_line("orphaned-memory-maint", f"done pool read failed: {exc}")
        return

    for path in pool:
        dispatch_id = path.name[len(memory_dispatch_claim.DONE_PREFIX):-len(".json")]
        try:
            payload, malformed = omm.read_record(path)
        except Exception as exc:  # noqa: BLE001 - a done-pool read failure must never break the fire
            state.log_line("orphaned-memory-maint", f"done record read failed: {exc}")
            continue
        if malformed or payload is None:
            continue  # not this checks job -- pool-malformed handling already covers it

        completed_at = payload.get("completed_at")
        if not isinstance(completed_at, (int, float)):
            continue  # older done shape or a foreign write -- not this checks concern

        age_s = max(0, now - int(completed_at))
        if age_s > 7 * 24 * 3600:
            continue  # older than 7 days -- not this checks concern any more

        # WHY: report="" makes Path(report) == Path(".") which always exists, so the
        # old `Path(report).exists()` check never fired for a claim closed without
        # --report (48a29226's exact case). Treat absent / empty / non-file the same
        # way -- all three are "the report is missing", just with a different detail.
        # A non-str, non-None value (int/list/dict) is a distinct, genuinely foreign
        # shape -- name its type rather than mislabeling it "empty" (review finding).
        report = payload.get("report")
        if report is None:
            detail = "no report was recorded"
        elif not isinstance(report, str):
            detail = f"report field has unexpected type: {type(report).__name__}"
        elif not report:
            detail = "an empty report path was recorded"
        elif not Path(report).is_file():
            detail = report
        else:
            continue  # report is a real, existing file -- healthy

        intervention = payload["intervention"]
        scope = payload["scope"]
        msg = (
            f"memory-maintenance pass {dispatch_id!r} ({intervention}, {scope}) checked in "
            f"but its report is missing: {detail}"
        )
        key = f"report-missing:{dispatch_id}"
        line = dedupe.emit_once(seen, key, f"[orphaned-memory-maint] {msg}")
        if line is None:
            continue  # already alerted for this exact id
        try:
            findings_ledger.record(
                sev="LOW", code="MEMPASS-REPORT-MISSING", src="orphaned-memory-maint",
                msg=msg, now=now,
            )
        except Exception as exc:  # noqa: BLE001
            state.log_line("orphaned-memory-maint", f"ledger write failed: {exc}")
        state.log_line("orphaned-memory-maint", f"recorded MEMPASS-REPORT-MISSING for {key}")
        print(line, flush=True)


def _check_pool(state_dir: Path, seen: Path, now: int, default_factor: int, local_factor: int) -> None:
    """The per-dispatch claim pool (TRDD-IB5B14QQ): `memory-maintenance.py::_write_pending`
    writes one immutable `memory-maint-pending-<dispatch_id>.json` per dispatch, on top of
    the legacy fixed slot this script already checks. A pending record is only claimable —
    i.e. still sitting here — until `memory_dispatch_claim.claim_one` renames it away; a
    claimed or superseded record does not match this glob at all (janitor#300 / af6340a5),
    so anything this loop sees is, by construction, unclaimed."""
    try:
        pool = memory_dispatch_claim.candidates(state_dir)
    except Exception as exc:  # noqa: BLE001 - a pool read failure must never break the fire
        state.log_line("orphaned-memory-maint", f"pool read failed: {exc}")
        return

    for path in pool:
        dispatch_id = path.name[len(memory_dispatch_claim.PENDING_PREFIX):-len(".json")]
        try:
            payload, malformed = omm.read_record(path)
        except Exception as exc:  # noqa: BLE001
            state.log_line("orphaned-memory-maint", f"pool record read failed: {exc}")
            continue

        if malformed:
            msg = (
                f"memory-maintenance pending pool record at {path} exists but cannot be "
                "parsed — the scheduler's own record of what it dispatched is unreadable. "
                "Investigate/remove the file so a claim or a future dispatch can proceed cleanly."
            )
            line = dedupe.emit_once(seen, f"pool-malformed:{dispatch_id}", f"[orphaned-memory-maint] {msg}")
            if line is not None:
                try:
                    findings_ledger.record(
                        sev="HIGH", code="MEMPASS-MALFORMED", src="orphaned-memory-maint",
                        msg=msg, now=now,
                    )
                except Exception as exc:  # noqa: BLE001
                    state.log_line("orphaned-memory-maint", f"ledger write failed: {exc}")
                print(line, flush=True)
            continue

        if payload is None:
            continue  # claimed/superseded/pruned between the glob and this read — healthy

        _evaluate_and_emit(
            payload, key=f"pool:{dispatch_id}", seen=seen, now=now,
            default_factor=default_factor, local_factor=local_factor,
        )


def main() -> int:
    state.init_state()
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_ORPHANED_MEMORY_MAINT_ENABLED", True):
        return 0

    default_factor = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_ORPHANED_MEMORY_MAINT_FACTOR"),
        omm.DEFAULT_FACTOR,
        detector_name="orphaned-memory-maint",
        var_name="ORPHANED_MEMORY_MAINT_FACTOR",
    ) or omm.DEFAULT_FACTOR
    local_factor = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_ORPHANED_MEMORY_MAINT_LOCAL_FACTOR"),
        omm.LOCAL_FACTOR,
        detector_name="orphaned-memory-maint",
        var_name="ORPHANED_MEMORY_MAINT_LOCAL_FACTOR",
    ) or omm.LOCAL_FACTOR

    now = int(time.time())
    state_dir = state.state_dir()
    seen = state_dir / "orphaned-memory-maint-seen.txt"

    try:
        payload, malformed = omm.read_pending(state_dir)
    except Exception as exc:  # noqa: BLE001 - a read failure must never break the fire
        state.log_line("orphaned-memory-maint", f"read failed: {exc}")
        return 0

    if malformed:
        msg = (
            f"memory-maintenance pending state at {state_dir / omm.PENDING_NAME} "
            "exists but cannot be parsed — the scheduler's own record of what it last "
            "dispatched is unreadable, so a dropped pass here could never be told "
            "apart from a healthy one. Investigate/remove the file so the scheduler "
            "can re-stamp it cleanly."
        )
        line = dedupe.emit_once(seen, "malformed", f"[orphaned-memory-maint] {msg}")
        if line is not None:
            try:
                findings_ledger.record(
                    sev="HIGH", code="MEMPASS-MALFORMED", src="orphaned-memory-maint",
                    msg=msg, now=now,
                )
            except Exception as exc:  # noqa: BLE001
                state.log_line("orphaned-memory-maint", f"ledger write failed: {exc}")
            print(line, flush=True)
    else:
        # The record parses (or is simply absent) — forget the malformed dedupe so a
        # future genuine malformation re-alerts rather than staying suppressed forever.
        dedupe.emit_forget(seen, "malformed")
        if payload is not None:
            key = f"{payload['intervention']}|{payload['scope']}"
            _evaluate_and_emit(
                payload, key=key, seen=seen, now=now,
                default_factor=default_factor, local_factor=local_factor,
            )
            # else: never dispatched — nothing to check, nothing wrong

    # The pool is independent of the legacy slot's state, so it is always checked,
    # even when the legacy slot is itself malformed.
    _check_pool(state_dir, seen, now, default_factor, local_factor)

    # A dead agent's claim never re-arms on its own (unlike an unclaimed pending
    # record, which just sits there and gets checked by _check_pool above) — nothing
    # else in the pipeline ever revisits a memory-maint-claimed-*.json file.
    _check_claimed_pool(state_dir, seen, now)

    # A checked-in claim never gets revisited by anything else -- this is the only
    # place a missing report on a done record would ever surface (c0cbf97d review).
    _check_done_pool(state_dir, seen, now)

    state.rotate_log_if_big("orphaned-memory-maint")
    return 0


if __name__ == "__main__":
    sys.exit(main())
