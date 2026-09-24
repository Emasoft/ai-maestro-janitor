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

import argparse
import os
import sys
import time
from collections.abc import Callable, Sequence
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

# TRDD-RAEGS1D5 owner decision 2026-09-23: "retry accordingly for 5 minutes before falling
# back to llm-ext". A raw env var (not a `CLAUDE_PLUGIN_OPTION_*` plugin option) because it is
# a TEST-ONLY lever (advisor §5) to shrink the budget in a test rather than a real tunable an
# operator is meant to configure.
_JEV_RETRY_BUDGET_ENV = "JANITOR_JEV_RETRY_BUDGET_S"
_DEFAULT_JEV_RETRY_BUDGET_S = 300
# T's own ceiling (advisor §4 arithmetic): `ec.LLM_EXT_TIMEOUT_S` (600) is the module's own
# per-attempt ceiling llm-ext's retry machinery was designed around -- `T` never needs to
# exceed it even when most of the 15-minute hold is still free (Jev failed fast).
_LLM_EXT_T_MAX_S = 600.0
# The seconds subtracted off the raw hold-remaining figure before handing the rest to llm-ext,
# so this script's own post-fallback bookkeeping (reading stdout, composing/writing the
# handoff, releasing the hold) has room to run before the hold's own TTL could expire under it.
_LLM_EXT_T_SAFETY_MARGIN_S = 30.0


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    # R2 (advisor review, replacing the design's own `--after-sync-failure`): the SYNC hook
    # (`on-session-start-post-clear-compact.py`) already resolved and verified the transcript
    # it wants summarized -- naming it here lets this lane skip BOTH the pane-claim check
    # (the sidecar the hook consumed is exactly what would otherwise make this run defer to
    # "the hook owns this transcript") and the `previous_transcript()` guess ("newest .jsonl
    # that isn't mine"), which is wrong for a multi-pane project (the exact defect card 5
    # closed). A caller that names its own source is presumed to already own the claim.
    parser.add_argument("--transcript", default="", help="summarize THIS transcript; skips "
                         "the pane-claim check and the previous_transcript() guess")
    return parser.parse_args(list(argv))


def main(
    argv: Sequence[str] = (), *, now_fn: Callable[[], float] = time.time,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    """Entry point — wraps `_main` so a crash is LOGGED, not silent (TRDD-QZVAEWQH).

    Measured incident: AgentlensPro 2026-09-02 04:24 took the summary hold and never logged
    READY or FAILED — its stderr went to DEVNULL (fixed separately, at the spawn site in
    on-session-start.py), so nothing on disk said WHY. Re-raising after logging keeps the
    fail-fast contract: the caller's stderr file still gets the traceback, and this line names
    the exception before it propagates.

    `argv` defaults to `()`, NEVER `sys.argv` — this function is called BOTH as the real CLI
    entry point (`__main__` below passes `sys.argv[1:]` explicitly) AND in-process by
    `tests/test_summarize_previous_session.py` (`sps.main()`, bare). Defaulting to `sys.argv`
    (argparse's own default when no argv is given) would make every in-process test call parse
    PYTEST'S OWN command line instead of this script's -- `-x`, a test node id, etc. would hit
    `--transcript`'s parser as unrecognized arguments and raise `SystemExit(2)` out of every
    single test in that file.

    `now_fn`/`sleep_fn` default to the real `time.time`/`time.sleep` and are threaded straight
    through to `jcl.run_compact_with_fallback` (TRDD-RAEGS1D5 owner review finding #5): EXPLICIT
    parameters, not the module-level mutable `_now_fn`/`_sleep_fn` hooks this used to be --
    those made "the clock a test sees" a piece of global, monkeypatchable state shared across
    every test in the file (order-dependent, easy to leave patched), where an ordinary keyword
    argument a test passes at its own call site is neither.
    """
    try:
        return _main(list(argv), now_fn=now_fn, sleep_fn=sleep_fn)
    except Exception as exc:  # noqa: BLE001 - log then re-raise, never swallow
        state.log_line(_LOG, f"crashed: {exc!r}")
        raise


def _main(
    argv: Sequence[str] = (), *, now_fn: Callable[[], float] = time.time,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
    sd = state.state_dir()
    now = int(time.time())
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    args = _parse_args(argv)

    if args.transcript:
        # R2: an explicit source skips the pane-claim check AND the previous_transcript()
        # guess entirely -- see `_parse_args`'s own comment for why.
        prev = Path(args.transcript)
        if not prev.is_file():
            state.log_line(_LOG, f"--transcript {prev} not found — nothing to do")
            return 0
    else:
        # TRDD-RAEGS1D5 card 5: `on-session-start-post-clear-compact.py` is the ONE composer for a
        # clear that named its transcript in a per-pane sidecar -- a FRESH (<=300s) sidecar means
        # that hook is (about to be) running right now; a `.consumed-*` one WRITTEN in the last 300s
        # means it already ran (or declined to a template) for THIS pane's clear moments ago. Either
        # shape means this detached summarizer must not also compose the same transcript -- "one
        # compose per transcript" (TRDD-QZVAEWQH) would otherwise become two, racing each other to
        # write the keyed handoff. An OLDER `.consumed-*` (review finding, 2026-09-23) is NOT such a
        # signal -- the hook renames a sidecar to `.consumed-<epoch>` the instant it starts, but a
        # crash or a project the janitor stops watching leaves that marker on disk forever; treating
        # ANY consumed marker (of ANY age) as "the hook owns this transcript" would then block this
        # summarizer from EVER running a real compose again for that pane, no matter how many
        # sessions and clears happen afterwards. The epoch is already in the filename (`consumed-
        # <now>` -- `_consume_sidecar`'s own naming), so freshness costs one int parse, not a stat.
        #
        # WHY `pane_key_from_terminal(self_terminal(...))`, not `state.terminal_pane_key(os.environ)`
        # (review finding, 2026-09-23): the WRITER (`clear_trigger._persist_resume_state`) keys the
        # sidecar off `terminal_trigger.self_terminal()`, which STRIPS iTerm's `w0t1p0:` window/tab/
        # pane prefix off `$ITERM_SESSION_ID` before sanitising -- `terminal_pane_key` sanitises the
        # RAW env var instead, so on iTerm the two computed different keys and this summarizer's own
        # sidecar check was comparing against a key nothing would ever write. Reading through the
        # SAME `self_terminal()` call the writer uses is what makes the two sides agree.
        import terminal_trigger  # noqa: PLC0415

        pane_key = state.pane_key_from_terminal(terminal_trigger.self_terminal(os.environ))
        if pane_key:
            fresh_sidecar = sd / f"resume-after-clear.{pane_key}.transcript"
            fresh = fresh_sidecar.is_file() and (now - state.file_mtime(fresh_sidecar)) <= 300
            consumed = False
            for consumed_path in sd.glob(f"resume-after-clear.{pane_key}.transcript.consumed-*"):
                suffix = consumed_path.name.rsplit("-", 1)[-1]
                try:
                    consumed_at = int(suffix)
                except ValueError:
                    continue  # a malformed suffix is not a timestamp this summarizer can trust
                if now - consumed_at <= 300:
                    consumed = True
                    break
            if fresh or consumed:
                state.log_line(
                    _LOG,
                    f"pane {pane_key} sidecar is {'fresh' if fresh else 'consumed'} — the "
                    "post-clear-compact hook owns this transcript, not this summarizer",
                )
                return 0

        prev = jcl.previous_transcript(root, session_id)
        if prev is None:
            state.log_line(_LOG, "no previous transcript to summarize — nothing to do")
            return 0

    key = handoff_files.session_key(str(prev))
    # ALREADY SUMMARIZED? Do not pay for it twice. A session that restarts several times in a row
    # would otherwise re-summarize the same transcript on every start, which is exactly the kind
    # of repeated external work this whole card exists to stop paying for. A TEMPLATE-marked
    # handoff (TRDD-RAEGS1D5 card 5: `on-session-start-post-clear-compact.py`'s own failure
    # fallback) does NOT count as "already summarized" -- it is a fact-only degrade, never a
    # real Jev compose, so this summarizer must still retry a real one on the next SessionStart.
    already_summarized = False
    for p in handoff_files.newest_group(sd):
        if not (key and key in p.name and p.is_file()):
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if content.lstrip().startswith(handoff_files.TEMPLATE_MARKER):
            continue
        already_summarized = True
        break
    if already_summarized:
        state.log_line(_LOG, f"a handoff already exists for {key} — skipping")
        return 0

    pending = ehc._capture_summary_source(sd, {"transcript": str(prev)}, now)
    if pending is None:
        state.log_line(_LOG, f"previous transcript unreadable ({prev}) — no hold taken")
        return 0

    print(f"SUMMARY_HOLD_TAKEN {prev.name}")
    state.log_line(_LOG, f"holding this session while jev_compact compacts {prev.name}")

    head_paths, heads_unavailable, in_flight_cards, other_open_ids_line = jcl.state_head_paths(
        root, sd, str(prev),
    )
    heads_args = ["--state-heads", *head_paths] if head_paths else []
    findings = ["heads: none (trddgrep unavailable)"] if heads_unavailable else []
    # TRDD-O2FNJ4KW: `in_flight_cards` is now only the top `jcl.TOP_CARD_COUNT` -- every other
    # open card is still named, just on this one capped line rather than with its own title.
    # TRDD-O2FNJ4KW follow-up (review correction 3): passed as `HandoffInputs.other_open_ids`
    # below, its own section, never appended into `findings` -- a board-membership fact is not a
    # janitor finding.

    out_path = sd / f"jev-compacted-{key or handoff_files.UNKEYED_KEY}.md"
    # Card 5 two-renderings (TRDD-RAEGS1D5) + TRDD-RAEGS1D5 retune follow-up: this detached lane
    # now gets the SAME size-bounded `--inject-out` companion `on-session-start-post-clear-
    # compact.py` already uses, for the same reason -- `compose_handoff`'s own `max_bytes` below
    # bounds the FINAL assembled handoff only with a raw byte-slice, which cuts the TAIL of an
    # oversized summary (the newest kept items, the pointer line) instead of Jev's own
    # priority-aware trim ever getting to decide what to drop. `tail`/`room` are computed BEFORE
    # `run_compact_with_fallback` so `--inject-max-bytes` can be sized to what `compose_handoff`
    # will actually have room for -- see `external_clear.compose_handoff_room`'s own docstring.
    inject_path = sd / f"jev-compacted-{key or handoff_files.UNKEYED_KEY}.inject.md"
    tail = ec.recent_messages(str(prev))
    room_inputs = ec.HandoffInputs(
        trigger="jev-compaction", findings=findings, cards=in_flight_cards,
        other_open_ids=other_open_ids_line,
    )
    # `room_inputs` may come back with SHORTER card titles than `in_flight_cards` (TRDD-RAEGS1D5
    # room-floor follow-up, round 2): `jcl.trim_cards_for_room` shrinks titles toward "" (every id
    # kept, never dropped) when they would otherwise starve the summary's own room -- see that
    # function's own docstring. Only the SUCCESS path below (which actually injects a summary)
    # reuses `room_inputs.cards`; the `jev-compaction-failed` branch keeps the original, untouched
    # `in_flight_cards` -- shortening titles buys it nothing there, since no summary is being
    # sized.
    room_inputs, inject_max_bytes = jcl.trim_cards_for_room(
        room_inputs, now_iso=time.strftime("%Y-%m-%dT%H:%M:%S%z"), tail=tail,
        transcript_path=str(prev), max_bytes=jcl.LANE_INJECTION_MAX_BYTES, source=jcl.SOURCE_JEV,
    )

    # Owner decision 2026-09-23 (TRDD-RAEGS1D5): retry Jev for up to `_JEV_RETRY_BUDGET_S`
    # (5min), THEN fall back to llm-ext -- both bounded within this run's own 15-minute hold.
    jev_deadline = now_fn() + state.coerce_int(
        os.environ.get(_JEV_RETRY_BUDGET_ENV), _DEFAULT_JEV_RETRY_BUDGET_S
    )
    # T = hold_expiry - now - safety_margin, capped at `_LLM_EXT_T_MAX_S` (advisor §4
    # arithmetic: 570s worst case when Jev used its whole budget, capped at 600 when Jev
    # failed fast and most of the 15-minute hold is still free).
    llm_ext_timeout_s = max(
        0.0, min(float(pending["expires"]) - now_fn() - _LLM_EXT_T_SAFETY_MARGIN_S,
                  _LLM_EXT_T_MAX_S),
    )

    source, compacted_text, detail = jcl.run_compact_with_fallback(
        PLUGIN_ROOT, transcript=str(prev), out_path=out_path, session_key=key,
        heads_args=heads_args, sd=sd, deadline=jev_deadline,
        llm_ext_timeout_s=llm_ext_timeout_s, now_fn=now_fn, sleep_fn=sleep_fn,
        inject_out_path=inject_path, inject_max_bytes=inject_max_bytes,
        max_elided_pointers=jcl.LANE_MAX_ELIDED_POINTERS,
    )

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    if source == jcl.SOURCE_FAILED:
        # Jev exhausted AND the llm-ext fallback also failed (advisor recommendation, §3 item
        # 4): unlike the old single-attempt lane, this run may have spent up to ~5 minutes
        # (Jev) plus most of the hold (llm-ext) proving neither works -- leaving the hold to
        # expire on its own 15-minute TTL at this point would pause the resume for no further
        # reason, since both sources are ALREADY known to have failed. Ensure a template
        # handoff exists for this key (the same fact-only degrade the sync hook writes on its
        # own failure) and release the hold immediately instead of waiting out a TTL whose
        # only original purpose was bounding a `jev_compact` that never returns.
        inputs = ec.HandoffInputs(
            trigger="jev-compaction-failed", findings=findings, cards=in_flight_cards,
            other_open_ids=other_open_ids_line,
        )
        template = ec.compose_template_handoff(inputs, now_iso=now_iso)
        text = f"{handoff_files.TEMPLATE_MARKER}\n{template}"
        handoff_files.write(sd, key or handoff_files.UNKEYED_KEY, text, now=now)
        ehc._release_summary_hold(sd, key=key)
        state.log_line(
            _LOG, f"jev and the llm-ext fallback both failed ({detail}) — template handoff "
            "written, hold released",
        )
        print(f"SUMMARY_FAILED jev and llm-ext fallback both failed: {detail}")
        return 0

    # `cards` comes from the SAME board dump `jcl.state_head_paths` already made for the STATE
    # heads, not a fresh fetch -- so composing the facts section costs nothing extra here.
    # WHY this matters (review finding, TRDD-RAEGS1D5 C1): `compose_template_handoff`'s
    # boilerplate NEXT ACTION always reads "read the STATE block of the first in-flight card
    # below" -- an empty `cards=[]` would leave that sentence pointing at nothing every time
    # compaction succeeds, which is worse than the boilerplate being absent.
    #
    # `trigger` names WHICH source produced this text (cheap diagnostic, advisor §5): a reader
    # of the handoff can tell a Jev compose from an llm-ext fallback summary at a glance.
    trigger = "jev-compaction" if source == jcl.SOURCE_JEV else "jev-compaction-llm-ext-fallback"
    # `cards=room_inputs.cards` (room-floor follow-up), not `in_flight_cards` -- keeps this call's
    # own room faithful to the (possibly title-shortened) facts `inject_max_bytes` was sized
    # against above; see `jcl.trim_cards_for_room`'s own docstring.
    inputs = ec.HandoffInputs(
        trigger=trigger, findings=findings, cards=room_inputs.cards,
        other_open_ids=other_open_ids_line,
    )
    # `tail` was already computed above, before `run_compact_with_fallback`, to size
    # `inject_max_bytes` -- same transcript (`prev` never changes mid-call), reused rather than
    # re-read.
    # Owner review finding #3 (TRDD-RAEGS1D5), fixed at the source: `ec.compose_handoff` now
    # takes `source` and renders the TRUE header itself (see
    # `external_clear._COMPACTED_CONTEXT_HEADS`) -- `source` is already exactly `jcl.SOURCE_JEV`
    # / `jcl.SOURCE_LLM_EXT` ("jev" / "llm-ext"), so no prepended disclaimer is needed here.
    text = ec.compose_handoff(
        inputs, now_iso=now_iso, summary=compacted_text, source=source, tail=tail,
        max_bytes=jcl.LANE_INJECTION_MAX_BYTES,
    )

    handoff_files.write(sd, key or handoff_files.UNKEYED_KEY, text, now=now)
    # The hold releases the moment the artifact lands, not on the 15-minute TTL -- its ABSENCE
    # is the release signal (external_handoff_clear._release_summary_hold), so a resumed
    # session sees the fresh handoff within the same second rather than waiting out the ceiling
    # that exists only to bound a jev_compact that never returns (TRDD-RAEGS1D5 card 3 C2).
    # `key=key` (R4): only release THIS lane's own hold record -- a second, still-in-flight
    # lane's hold (a different transcript, a different key) must survive this release.
    ehc._release_summary_hold(sd, key=key)
    print(f"SUMMARY_READY {len(text.encode('utf-8'))}B for {prev.name} (source={source})")
    state.log_line(_LOG, f"compacted context ready ({len(text)} chars, source={source}) — hold released")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
