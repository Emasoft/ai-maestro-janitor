#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Summarize the PREVIOUS session's transcript at SessionStart (TRDD-2F3I2P18, TRDD-RAEGS1D5).

WHY THIS EXISTS AS ITS OWN ENTRY POINT. `external_handoff_clear.py` covers the case where the
JANITOR fires the clear. It cannot cover the case where a HUMAN ends a session — `/clear` has no
hook, and `claude -n` is a brand-new process. Both are the same event from the transcript's point
of view: a session stopped, its `.jsonl` is complete on disk, and the next session starts blank
beside it.

THE ORDERING IS THE POINT, and it is the owner's ruling of 2026-09-01. The new session is ALREADY
cheap — it starts at base context — so there is nothing to save by summarizing first. What must
not happen is the session picking up work before the summary lands, because then it does that work
blind and the injection arrives into a context that has already moved on. So: capture, hold,
summarize, release.

NOTHING HERE COSTS CLAUDE TOKENS. `jev_compact.py compact` (below) runs Jev scoring out of
process against its own provider; this script's whole job is to name the source, take the hold,
invoke it, and wait.

JEV COMPACTION (TRDD-RAEGS1D5, docs_dev/jev-compaction-spec.md card 3) replaced the llm-ext
summary here: instead of `external_clear.summarize_with_retry`, this script now runs
`scripts/jev_compact.py compact` as a subprocess and, on success, composes the injected payload
(facts + the compacted context + a message tail) via `external_clear.compose_handoff`. This
module stays stdlib-only PEP-723 on purpose — `jev_compact.py` is the ONE place `httpx`/`jevctx`
may be imported in-process (see its own module docstring and `tests/test_jev_boundary.py`, which
pins this file into the forbidden-import list). Never `import jevctx`, `httpx`, or
`jev_compaction` here; always reach Jev through a subprocess.

THIN ON PURPOSE (TRDD-RAEGS1D5 card 3 C2): the trddgrep board/STATE-heads discovery, the
`jev_compact.py` subprocess runner, and the exit-code -> findings-ledger mapper used to live in
this file and grew it from 137 to ~530 lines during C1's wiring. They now live in
`scripts/lib/jev_compaction_lane.py` (also stdlib-only, for the same in-process-import reason);
this file is left doing only what an entry point should: read the environment, decide whether
there's anything to summarize, orchestrate the hold/invoke/compose/release sequence, and exit.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import external_clear as ec  # noqa: E402
import external_handoff_clear as ehc  # noqa: E402
import handoff_files  # noqa: E402
import jev_compaction_lane as jcl  # noqa: E402
import state  # noqa: E402

_LOG = "session-summary"

# resolve like every sibling PEP-723 script does: the real plugin root when the harness set it,
# else this script's own parent (scripts/.. == the plugin root) -- see jev_compact.py itself,
# which is exec'd BY PATH by `jcl.run_compact` (it is git-tracked 100755, so its own shebang
# runs it; no `uv run` prefix needed here, matching how the rest of this lane invokes its
# siblings).
PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or str(_SCRIPTS.parent))


def main() -> int:
    """Entry point — wraps `_main` so a crash is LOGGED, not silent (TRDD-QZVAEWQH).

    Measured incident: AgentlensPro 2026-09-02 04:24 took the summary hold and never logged
    READY or FAILED — its stderr went to DEVNULL (fixed separately, at the spawn site in
    on-session-start.py), so nothing on disk said WHY. Re-raising after logging keeps the
    fail-fast contract: the caller's stderr file still gets the traceback, and this line names
    the exception before it propagates.
    """
    try:
        return _main()
    except Exception as exc:  # noqa: BLE001 - log then re-raise, never swallow
        state.log_line(_LOG, f"crashed: {exc!r}")
        raise


def _main() -> int:
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
    sd = state.state_dir()
    now = int(time.time())
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")

    prev = jcl.previous_transcript(root, session_id)
    if prev is None:
        state.log_line(_LOG, "no previous transcript to summarize — nothing to do")
        return 0

    key = handoff_files.session_key(str(prev))
    # ALREADY SUMMARIZED? Do not pay for it twice. A session that restarts several times in a row
    # would otherwise re-summarize the same transcript on every start, which is exactly the kind
    # of repeated external work this whole card exists to stop paying for.
    if any(p.is_file() for p in handoff_files.newest_group(sd) if key and key in p.name):
        state.log_line(_LOG, f"a handoff already exists for {key} — skipping")
        return 0

    pending = ehc._capture_summary_source(sd, {"transcript": str(prev)}, now)
    if pending is None:
        state.log_line(_LOG, f"previous transcript unreadable ({prev}) — no hold taken")
        return 0

    print(f"SUMMARY_HOLD_TAKEN {prev.name}")
    state.log_line(_LOG, f"holding this session while jev_compact compacts {prev.name}")

    head_paths, heads_unavailable, in_flight_cards = jcl.state_head_paths(root, sd)
    heads_args = ["--state-heads", *head_paths] if head_paths else []

    out_path = sd / f"jev-compacted-{key or handoff_files.UNKEYED_KEY}.md"
    proc, timed_out = jcl.run_compact(
        PLUGIN_ROOT, transcript=str(prev), out_path=out_path, session_key=key,
        heads_args=heads_args,
    )

    if timed_out or proc is None or proc.returncode != jcl.EXIT_OK:
        jcl.handle_nonzero_exit(proc, timed_out=timed_out, sd=sd)
        # The hold's TTL releases the session onto the mechanical handoff (compose_template_
        # handoff). Do NOT clear the hold early here: an immediate release would hand the
        # session a blank context with no explanation, whereas letting the TTL expire produces
        # the documented degrade path — unchanged from the llm-ext-era behaviour.
        state.log_line(
            _LOG,
            "jev_compact produced no compacted context — leaving the hold to expire onto the "
            "mechanical precompact handoff",
        )
        print("SUMMARY_FAILED degrading to the mechanical handoff on TTL")
        return 0

    try:
        compacted_text = out_path.read_text(encoding="utf-8")
    except OSError as exc:
        # jev_compact.py exited 0 (it wrote the file itself, atomically) but this process
        # somehow can't read it back — treat exactly like any other bug exit rather than
        # crash the SessionStart lane over a filesystem race.
        state.log_line(_LOG, f"compacted context written but unreadable ({out_path}): {exc!r}")
        print("SUMMARY_FAILED degrading to the mechanical handoff on TTL")
        return 0

    findings = ["heads: none (trddgrep unavailable)"] if heads_unavailable else []
    # `cards` comes from the SAME board dump `jcl.state_head_paths` already made for the STATE
    # heads, not a fresh fetch -- so composing the facts section costs nothing extra here.
    # WHY this matters (review finding, TRDD-RAEGS1D5 C1): `compose_template_handoff`'s
    # boilerplate NEXT ACTION always reads "read the STATE block of the first in-flight card
    # below" -- an empty `cards=[]` would leave that sentence pointing at nothing every time
    # compaction succeeds, which is worse than the boilerplate being absent.
    inputs = ec.HandoffInputs(trigger="jev-compaction", findings=findings, cards=in_flight_cards)
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    tail = ec.recent_messages(str(prev))
    text = ec.compose_handoff(inputs, now_iso=now_iso, summary=compacted_text, tail=tail)

    handoff_files.write(sd, key or handoff_files.UNKEYED_KEY, text, now=now)
    # The hold releases the moment the artifact lands, not on the 15-minute TTL -- its ABSENCE
    # is the release signal (external_handoff_clear._release_summary_hold), so a resumed
    # session sees the fresh handoff within the same second rather than waiting out the ceiling
    # that exists only to bound a jev_compact that never returns (TRDD-RAEGS1D5 card 3 C2).
    ehc._release_summary_hold(sd)
    print(f"SUMMARY_READY {len(text.encode('utf-8'))}B for {prev.name}")
    state.log_line(_LOG, f"compacted context ready ({len(text)} chars) — hold released")
    return 0


if __name__ == "__main__":
    sys.exit(main())
