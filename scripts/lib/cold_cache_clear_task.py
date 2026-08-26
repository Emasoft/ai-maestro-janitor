"""cold-cache-clear — the ONE implementation of the beat (TRDD-9ZPU69UC).

Extracted verbatim from ``daemon.py::task_cold_cache_clear`` so BOTH runtime lanes call the
same code instead of porting it:

  * the janitor daemon's Task (``daemon.py`` delegates here), and
  * the ai-maestro server's absorbed lane, which shells out to the auto-rolling
    dispatcher stub — ``<DATA>/dispatcher-stub.py --run-cold-cache-clear`` — so the newest
    cached version's copy of THIS module runs, through the stub's full C2/C3
    verify-before-exec walk, with zero janitor code imported server-side (argv-only
    contract; the dispatcher-stub pattern that kills vendored-copy version skew).

THE WINDOW, and why nothing in-session can cover it: a cron fire's input cost is billed when
the turn STARTS, and the dispatcher stub runs inside that turn. Any in-session check is
therefore reading a bill that has already been paid. Only an out-of-turn actor (the daemon,
or the server's lane) can shrink a cold-cache session BEFORE one begins.

It delegates rather than reimplements — one ``external_handoff_clear.py --project-root <p>``
per candidate. That script owns the gate, the handoff composition (retry loop, fleet lane)
and the injection chain; duplicating any of that here would be a second implementation of an
unrecoverable ``/clear``.

ONE CANDIDATE PER CALL, deliberately. Even with the fleet lane spacing the llm-ext calls,
firing N clears from one beat means N concurrent children each holding a lane ticket, and the
last one's ticket is minutes out — so they would pile up faster than they drain. Draining one
per beat lets a 20-session fleet settle over ~20 beats with at most one child alive at a time.

SAFETY: default-OFF via the same opt-in as the SessionStart half (``external_clear.enabled()``),
never a session the caller cannot identify a pane for, never one whose transcript is ADVANCING
(that is a human working — clearing under them is the one unrecoverable mistake here), and
never twice inside the cooldown (``cold_cache_compact.clear_in_cooldown``). Never raises.

DOUBLE-OWNERSHIP GUARD: the daemon's Task yields per-tick the moment the server's liveness
beat claims ``cold-cache-clear`` (``daemon._task_yielded_to_server`` reads
``harness_backend.claimed_chores()`` fresh each loop), so the two lanes never both fire in a
window; the per-project clear cooldown is the belt-and-braces backstop either way.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import fleet_scan  # noqa: E402  -- sibling lib
import global_state as gs  # noqa: E402
import state  # noqa: E402

_COMPONENT = "cold-cache-clear"


def run_once() -> int:
    """One beat: evaluate the fleet, spawn the watcher for AT MOST one candidate.

    Returns 0 always (fail-open — a tidiness beat must never fail its caller); the
    return type exists so ``dispatch.py --run-cold-cache-clear`` can ``sys.exit`` it.
    """
    try:
        import cold_cache_compact  # noqa: PLC0415
        import external_clear as ec  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 - a missing sibling must not kill the beat
        state.log_line(_COMPONENT, f"cold-cache-clear: libs unavailable: {exc}")
        return 0
    if not ec.enabled():
        return 0  # ships inert, exactly like the SessionStart half — /clear is unrecoverable
    now = int(time.time())
    try:
        fleet = fleet_scan.gather_fleet(now=now)
    except Exception as exc:  # noqa: BLE001 - a scan error must never kill the beat
        state.log_line(_COMPONENT, f"cold-cache-clear: fleet scan failed: {exc}")
        return 0

    watcher = _HERE.parent / "external_handoff_clear.py"
    if not watcher.is_file():
        return 0
    for inst in fleet:
        # `inst.project_root`, NOT `getattr(inst, "root", "")`. The first draft used the getattr
        # form with a default, and `Instance` has no `root` — so it would have read "" for every
        # instance and this whole task would have shipped as a permanent no-op that logs nothing
        # and looks exactly like "no session needed clearing". Attribute access on a known
        # dataclass field is the version that FAILS LOUDLY when the field is renamed.
        root = inst.project_root or ""
        # `active` means the transcript is ADVANCING — a live turn, i.e. someone (or something)
        # is working. Clearing that is unrecoverable, and unlike a keystroke it cannot be
        # deferred-and-retried into safety, so it is a hard skip rather than a wait.
        if not root or inst.active:
            continue
        if inst.pid in (os.getpid(), gs.daemon_pid()):
            continue
        sd = Path(root) / ".janitor" / "state"
        if not sd.is_dir() or cold_cache_compact.clear_in_cooldown(sd, now=now):
            continue
        # KEEP THE WATCHER'S STDOUT (TRDD-UQW5IOAE). It prints exactly the audit line this
        # feature is judged on — `VERDICT FIRE/HOLD … why=…`, plus NO_SUMMARY /
        # HANDOFF_NOT_CONCISE / CLEAR_CHAIN_SPAWNED — and DEVNULL threw every one of them away,
        # in the ENABLED case too. That is why "shadow mode has been running and found nothing"
        # would have been the opposite of the truth: nothing was recorded, so nothing could be
        # found. The SessionStart lane never had this hole (it is blocking and logs its own
        # verdict via state.log_line), so this was the one call site.
        #
        # Appending to the component's own log file, NOT a pipe: the child is detached and
        # nobody survives to read a pipe — a full pipe buffer would simply block it forever.
        # PYTHONUNBUFFERED so a killed child still leaves its lines behind rather than losing a
        # block-buffered tail.
        #
        # ponytail: the child holds this fd across a rotation, so a long-lived watcher keeps
        # writing to <log>.1 after the rename. Harmless at this lifetime (one clear chain);
        # revisit only if the watcher ever becomes long-running.
        # Log the header BEFORE the spawn, not after: it puts the "evaluating <root>" line
        # ahead of the watcher's own lines in the same file (they interleave otherwise), and
        # a beat that dies mid-spawn still says which root it was on.
        state.log_line(_COMPONENT, f"cold-cache-clear: evaluating {root}")
        try:
            log_dir = state.log_dir()
            # Explicit, not inherited from log_line's init_state() side effect — an open() that
            # raises here lands in the except below and SKIPS THE SPAWN, turning an audit-trail
            # improvement into a silent no-op of the whole feature. Measured: it did exactly
            # that to test_it_reads_the_real_project_root_field on the first draft.
            log_dir.mkdir(parents=True, exist_ok=True)
            with (log_dir / f"{_COMPONENT}.log").open("a", encoding="utf-8") as sink:
                subprocess.Popen(  # noqa: S603 - fixed argv, feature-detected script
                    [sys.executable, str(watcher), "--project-root", root],
                    stdout=sink,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env={**os.environ, "CLAUDE_PROJECT_DIR": root, "PYTHONUNBUFFERED": "1"},
                )
        except Exception as exc:  # noqa: BLE001 - one bad spawn must not stop the beat
            state.log_line(_COMPONENT, f"cold-cache-clear: spawn failed for {root}: {exc}")
            continue
        return 0  # one per beat — see the module docstring
    return 0
