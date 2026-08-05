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
enough, because the watchdog has exactly two callers (`marketplace-refresh`,
`user-plugins-update`) and BOTH are absorbed chores. The six unowned ones had no caller at
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
    """The unabsorbed chores that are provably not running, as `(chore, age_s)`.

    Empty when the host is healthy OR when the evidence does not support a judgement —
    the two are deliberately indistinguishable here, because both mean "say nothing".
    """
    stamps = {c: gs.read_last_run(c) for c in harness_backend.GLOBAL_CHORES}
    # "Has the daemon ever run here?" — ANY chore with a stamp proves it has. Without this,
    # a machine that has only ever run under a server would alarm about chores it never had.
    if not any(ts > 0 for ts in stamps.values()):
        return []

    stale: list[tuple[str, int]] = []
    for chore in harness_backend.unabsorbed_chores():
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
        if not harness_backend.server_runs_chores():
            return 0  # no server claiming the chores ⇒ the daemon is allowed to run them
        if gs.daemon_is_alive():
            return 0  # a live daemon owns the unabsorbed six itself ⇒ nothing is unowned

        now = int(time.time())
        stale = _blackout(now)
        if not stale:
            return 0

        named = ", ".join(f"{c} ({age // 3600}h)" for c, age in stale[:_NAMED_IN_LINE])
        extra = len(stale) - _NAMED_IN_LINE
        if extra > 0:
            named += f", +{extra} more"
        worst_h = stale[0][1] // 3600
        msg = (
            f"[{_NAME}] {len(stale)} machine-global chore(s) have NO owner: a live ai-maestro "
            f"server suppresses the janitor daemon, but does not absorb these — {named}. "
            f"Nothing will run them and nothing will self-heal while the server is up "
            f"(worst: {worst_h}h). Tracked as Emasoft/ai-maestro#111; the janitor cannot close "
            f"this from its side. To restore them now: stop the ai-maestro server, or set "
            f"JANITOR_AIMAESTRO_SERVER_STATE=down to let the daemon spawn."
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
