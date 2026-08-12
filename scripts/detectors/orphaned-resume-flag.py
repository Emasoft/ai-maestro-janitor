#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""orphaned-resume-flag — notice a session whose wake-up chain silently failed (#125).

`resume-after-compact.flag` is written by the PostCompact hook and cleared by the NEXT
heartbeat fire. An UNCONSUMED one therefore means exactly one thing: a compaction recorded
a resume target that was never delivered, because that session's heartbeat never fired
again — cron dead, expired at the 7-day platform limit, never armed, or the CLI wedged.

Until this detector existed, nothing noticed. The janitor's promise is unattended
continuity and its failure mode was SILENT: the only detector was the human observing that
their sessions had stopped moving. A watchdog whose own failure is invisible is not a
watchdog — so this closes the CLASS, not any single cause.

WHY PER-SESSION AND NOT ONLY IN THE DAEMON. The daemon's `session-liveness` beat is the
natural home and should also carry this. But on a host where a live ai-maestro server owns
the machine, the janitor's daemon is deliberately NOT RUNNING (`_server_owns_host`,
TRDD-5ZVS1DDP §7.2) — which is precisely when nothing is watching. A watchdog that is
absent exactly when it is needed is the bug being fixed, so the check also runs here, where
it costs one `stat` per known project.

PER-PROJECT CHANNELING (TRDD-X92VBFNF) is why this prints almost nothing. A finding about
project X is recorded into X's OWN ledger, so it greets whoever opens X — it is never
surfaced as a drift line here, because an automatic surface must carry only the firing
project's data. The one exception is THIS project's own flag, which is ours to report.
(Fleet-wide views stay behind the explicit `/janitor-findings` and
`/janitor-show-global-status` commands.)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import findings_ledger  # noqa: E402
import orphaned_resume  # noqa: E402
import state  # noqa: E402


def main() -> int:
    state.init_state()
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_ORPHANED_RESUME_ENABLED", True):
        return 0

    factor = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_ORPHANED_RESUME_FACTOR"),
        3,
        detector_name="orphaned-resume-flag",
        var_name="ORPHANED_RESUME_FACTOR",
    ) or 3

    home = os.environ.get("HOME", "").strip() or os.path.expanduser("~")
    projects_root = Path(home) / ".claude" / "projects"
    now = int(time.time())

    try:
        orphans = orphaned_resume.scan(projects_root, now=now, factor=factor)
    except Exception as exc:  # noqa: BLE001 - a scan failure must never break the fire
        state.log_line("orphaned-resume-flag", f"scan failed: {exc}")
        return 0

    if not orphans:
        return 0

    own_root = str(state.project_root())
    seen = state.state_dir() / "orphaned-resume-seen.txt"

    for o in orphans:
        root, age_s, cron = o["root"], o["age_s"], o["armed_cron"]
        msg = orphaned_resume.format_finding(age_s, cron)

        # Record into the AFFECTED project's ledger — not this one's. `record` resolves the
        # target state dir from `project_dir`, which is the whole reason that parameter
        # exists: the session that can OBSERVE the failure is never the session that has it.
        #
        # DAY-BUCKETED, exactly like the drift line below (measured 2026-08-12). The ledger
        # write used to be unconditional while only the stdout line was deduped — so ONE
        # stuck flag wrote a HIGH entry on EVERY fire: 6 entries in 10 minutes on 2026-08-07,
        # 11 total for at most 3 distinct incidents. The ledger is ring-trimmed at 500 lines,
        # so that is not a disk problem, it is a SIGNAL problem: ~288 entries/day evicts every
        # other finding the project ever recorded inside ~2 days, and the SessionStart surface
        # (capped at 10 lines) becomes ten copies of one message with everything else folded
        # away. Worse, the affected project is BY DEFINITION the dark one — nobody is there to
        # notice or `ack` — so the flood lands precisely where it cannot be seen until someone
        # returns, and what greets them is the least informative view the ledger can produce.
        # Keyed by affected project so two orphaned projects cannot suppress each other.
        # Gates the LEDGER WRITE ONLY — not `continue` — because the local log line below is
        # the per-fire forensic trail that shows how long the condition persisted, and the
        # drift line already owns its own key.
        ledger_due = dedupe.emit_once(
            seen, f"ledger@{orphaned_resume.project_slug(root)}@{age_s // 86400}", "due"
        ) is not None
        if ledger_due:
            try:
                findings_ledger.record(
                    sev="HIGH",
                    code="RESUME-ORPHANED",
                    src="orphaned-resume-flag",
                    msg=msg,
                    project_dir=root,
                    now=now,
                )
            except Exception as exc:  # noqa: BLE001 - one bad ledger must not stop the rest
                state.log_line("orphaned-resume-flag", f"ledger write failed for {root}: {exc}")

        # Log the SLUG, never the absolute path — it carries the machine's user name, and
        # this log is read by humans and agents alike.
        # Says which of the two happened. It used to say "recorded" unconditionally, which was
        # true when every fire recorded; now that the ledger is day-bucketed, an unconditional
        # "recorded" would be a false forensic trail — the log is where someone reconstructs
        # how long a condition persisted, so it must not claim writes that did not happen.
        state.log_line(
            "orphaned-resume-flag",
            f"{'recorded' if ledger_due else 'still orphaned (ledger deduped)'} "
            f"RESUME-ORPHANED for {orphaned_resume.project_slug(root)} ({age_s}s)",
        )

        # Surface a drift line ONLY for our own project. Bucketed by day so a genuinely
        # stuck session re-reports occasionally rather than once and never again.
        if os.path.realpath(root) == os.path.realpath(own_root):
            line = dedupe.emit_once(
                seen, f"orphaned@{age_s // 86400}", f"[orphaned-resume-flag] {msg}"
            )
            if line is not None:
                print(line)

    state.rotate_log_if_big("orphaned-resume-flag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
