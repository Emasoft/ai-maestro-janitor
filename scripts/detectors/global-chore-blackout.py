#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""global-chore-blackout — alarm when global chores have NO owner at all (ai-maestro#111).

THE CONDITION THIS EXISTS FOR. A live ai-maestro server does not make the janitor daemon
YIELD its absorbed chores — `global_state.ensure_daemon_running` refuses to spawn the daemon
AT ALL ("one daemon per host"). But the server's contract, `SERVER_ABSORBED_TASKS`, claims
only FIVE of the daemon's ELEVEN chores. The other six are not yielded and not absorbed: they
simply run NOWHERE for as long as a server is up.

WHY A WHOLE DETECTOR. The pre-existing staleness watchdog (`daemon_watchdog`) was blind here
by construction: it returned early whenever `server_runs_chores()` was true, for EVERY chore,
so the one signal that could have reported the blackout was disabled by the very condition
that caused it. That gate is now narrowed to absorbed chores only — but narrowing it is not
enough, because the watchdog had exactly two callers (`marketplace-refresh` and the
since-retired `user-plugins-update` shim — TRDD-E39YT9G6) and both were absorbed chores.
The six unowned ones had no caller at
all. This detector is that caller. Measured cost of the gap on the owner's host, 2026-08-05:
eleven chores dark for 10-14 days, zero warnings — including `session-liveness`, the 2-minute
fleet guardian, without which a frozen session is never revived and every per-session
detector it owns (GitHub watch, drift, security) silently stops with it.

READ-ONLY and CHEAP: a handful of file stats on `~/.claude/janitor-control/*.last-run.ts`
plus one liveness probe. No network, no `gh`, no subprocess.

SILENT unless ALL of these hold — anything else is a healthy or unjudgeable host:
  * a live server is claiming the chores (so the daemon is suppressed), AND
  * the daemon is genuinely not alive (a daemon that IS running owns the six itself), AND
  * the daemon has run on this host at least once (else this is a fresh install with nothing
    to be stale — never alarm someone who has not had the feature yet), AND
  * at least one unabsorbed chore is stale past its own cadence + a generous margin.

Emits ONE consolidated line per day naming the worst offenders. One condition gets one alarm:
six separate lines for six symptoms of a single cause is how a real finding gets tuned out.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import daemon_watchdog  # noqa: E402
import dedupe  # noqa: E402
import global_state as gs  # noqa: E402
import harness_backend  # noqa: E402
import state  # noqa: E402

_NAME = "global-chore-blackout"

# How many chore names the drift line spells out before folding the rest into a count.
# The line goes into every session's context on every fire; naming the three worst is
# enough to act on, and the remedy pointer covers the rest.
_NAMED_IN_LINE = 3


def _stale_threshold(cadence: int) -> int:
    """Age past which a chore's completion stamp means it is genuinely not running.

    Same generous shape `daemon_watchdog` uses, and for the same reason: the stamp is
    written at COMPLETION, so it legitimately ages by `cadence` (waiting to be due) plus
    one full-length run before the next one lands. A cadence of margin on top means a
    single slow-but-successful run can never trip this.
    """
    return cadence + daemon_watchdog.MAX_TASK_RUNTIME_S + cadence


def _cadence_of(chore: str) -> int:
    """The chore's configured cadence in seconds, honouring its env override."""
    env_var, default_s = harness_backend.GLOBAL_CHORES[chore]
    return state.coerce_int(os.environ.get(env_var), default_s)


def _blackout(now: int) -> list[tuple[str, int]]:
    """The chores NOTHING will run, and whose stamps prove it, as `(chore, age_s)`.

    Empty when the host is healthy OR when the evidence does not support a judgement —
    the two are deliberately indistinguishable here, because both mean "say nothing".

    The candidate set is `harness_backend.orphaned_chores`, not `unabsorbed_chores`. The
    first version asked only "which chores did the server never absorb?", which misses the
    mirror-image hole: a chore that IS claimed while no live server exists — reachable via
    the operator override, which asserts the server runs chores with no probe to corroborate
    it, and would then yield all five absorbed chores into nothing. A detector for
    ownerless chores that only looks at one of the two ways a chore becomes ownerless is
    the same class of gap it exists to report.
    """
    stamps = {c: gs.read_last_run(c) for c in harness_backend.GLOBAL_CHORES}
    # "Has the daemon ever run here?" — ANY chore with a stamp proves it has. Without this,
    # a machine that has only ever run under a server would alarm about chores it never had.
    if not any(ts > 0 for ts in stamps.values()):
        return []

    stale: list[tuple[str, int]] = []
    for chore in sorted(harness_backend.orphaned_chores(daemon_alive=gs.daemon_is_alive())):
        last = stamps.get(chore, 0)
        # A never-stamped chore on a host where the daemon HAS run is the strongest form of
        # this finding, not a reason to skip: it means the chore has not completed once in
        # the recorded history of this machine. Age is measured from the oldest evidence we
        # have, so the number stays honest rather than inventing an epoch-based age.
        age = now - last if last > 0 else now - min(ts for ts in stamps.values() if ts > 0)
        if age > _stale_threshold(_cadence_of(chore)):
            stale.append((chore, age))
    stale.sort(key=lambda pair: pair[1], reverse=True)
    return stale


def main() -> int:
    # Fail-soft (PRRD S6.1): this detector must never be the reason a heartbeat dies. A
    # blackout report is worth having; it is not worth taking the other detectors down for.
    try:
        # A HANDOVER must be in play. With nothing claimed there is no handover to fall
        # through, and a merely-absent daemon is `daemon_watchdog`'s business — reporting it
        # here too would double-alarm on every transient respawn gap.
        #
        # NOTE the gate that is deliberately NOT here: an earlier version returned early when
        # the daemon was alive, on the reasoning that a live daemon owns whatever the server
        # did not. That is false in the override case — the daemon can be alive and still be
        # yielding chores to a server that does not exist — so the very hole this detector
        # was extended to catch would have been skipped before it was ever computed.
        if not harness_backend.claimed_chores():
            return 0

        now = int(time.time())
        stale = _blackout(now)
        if not stale:
            return 0

        named = ", ".join(f"{c} ({age // 3600}h)" for c, age in stale[:_NAMED_IN_LINE])
        extra = len(stale) - _NAMED_IN_LINE
        if extra > 0:
            named += f", +{extra} more"
        worst_h = stale[0][1] // 3600
        # Name the SHAPE, because the two have opposite remedies: a chore yielded to an
        # absent server is fixed by correcting the claim; a chore dropped by a suppressed
        # daemon is fixed by letting the daemon run.
        if harness_backend.server_is_alive():
            # A live server no longer suppresses us while its claim is PARTIAL — the
            # daemon stays up and covers exactly the unclaimed remainder (daemon.py's
            # §7.2 exit is gated on `server_owns_every_chore`). So reaching here means
            # the daemon that SHOULD be running these is not, which is a daemon-health
            # problem, not a server problem. Telling the operator to stop the server
            # would be a wrong and expensive remedy for it.
            cause = ("these are unclaimed by the live ai-maestro server AND the janitor "
                     "daemon that should cover them is not running")
            remedy = ("check daemon health (kill-switch, crash-loop breaker, OS keepalive) — "
                      "a partial server claim no longer suppresses it")
        else:
            cause = ("these are YIELDED to an ai-maestro server that is NOT running — an "
                     "operator override is asserting the server owns chores with no live "
                     "server behind it")
            remedy = ("unset JANITOR_AIMAESTRO_SERVER_CHORES / "
                      "JANITOR_AIMAESTRO_SERVER_STATE so the daemon takes them back")
        msg = (
            f"[{_NAME}] {len(stale)} machine-global chore(s) have NO owner: {cause} — "
            f"{named}. Nothing will run them and nothing will self-heal (worst: {worst_h}h). "
            f"Tracked as Emasoft/ai-maestro#111. To restore them now: {remedy}."
        )
        if "session-liveness" in {c for c, _ in stale}:
            msg += (
                " session-liveness is among them — while it is dark, frozen sessions are never "
                "recovered and their per-session detectors (GitHub watch, drift, security) stop "
                "reporting entirely."
            )

        # Once per day: the condition changes on the scale of days, and an hourly repeat of an
        # unactionable-from-here finding is how a real alarm becomes noise.
        seen = state.state_dir() / f"{_NAME}-seen.txt"
        out = dedupe.emit_once(seen, f"blackout@{now // 86400}", msg)
        if out is not None:
            print(out)
    except Exception as exc:  # noqa: BLE001 -- fail-soft is the contract
        state.log_line(_NAME, f"skipped: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
