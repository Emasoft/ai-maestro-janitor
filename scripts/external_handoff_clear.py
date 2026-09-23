#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""External (ZERO model turn) handoff-and-clear — the watcher (TRDD-PXP08ZQC).

The gathering + firing half of the external clear; the decisions are PURE and live in
`lib/external_clear.py`. Run one-shot from outside the model:

    external_handoff_clear.py --project-root <path> [--dry-run] [--force]

WHAT MAKES IT ZERO-TURN. Three things have to happen for an abandoned session to shrink, and
today the model does all three. Here:

  1. DECIDE  — `external_clear.should_clear_externally`, from files the session already writes
     (transcript mtime, `armed-cadence.cron`, the presence breadcrumb).
  2. DELEGATE — the compacted-context handoff is composed by the CLEARED session's own
     SessionStart summarizer (`summarize_previous_session.py`, Jev compaction against its own
     provider — not llm-ext), out of process. Zero tokens from THIS session, which is what
     "zero turn" means — not that no model is involved.
     TRDD-QZVAEWQH — THIS SCRIPT NEVER COMPOSES, IN EITHER MODE. It used to: the `--on-resume`
     caller (a SessionStart hook, which has the summarizer's API key) composed inline while the
     keyless daemon lane delegated. That split kept a race alive — an on-resume fire types
     `/clear`, and the NEW session's own SessionStart spawns `summarize_previous_session.py` for
     "the newest transcript that is not mine", which is the SAME transcript the inline compose
     was still summarizing. Two `llm-ext` runs on one transcript, two keyed handoffs. So both
     modes now fire and DELEGATE the compose to the cleared session's own SessionStart
     summarizer (`summarize_previous_session.py`) — see `_run`'s `SUMMARY_DELEGATED` branch.
  3. TYPE    — `clear_trigger`'s ALREADY-RATIFIED verified injection chain, reused verbatim by
     spawning its `--__chain` child with a payload we build. Nothing in `clear_trigger` had to
     change: `_run_chain_payload` takes the pane, the state dir and the directive as DATA, and
     resolves the project root from `CLAUDE_PROJECT_DIR`, which we set for the child.

THE PANE COMES FROM DISK, NOT FROM THE ENVIRONMENT. A process that is not the session cannot see
`TMUX_PANE` / `ITERM_SESSION_ID` — they do not propagate. The session records them at start into
`.janitor/state/terminal-identity.json`; `fleet_restart.recorded_terminal` reads that back and
`external_clear.terminal_from_record` adapts the shape. Without a recorded pane there is no
channel and the watcher declines rather than clearing a session it cannot bootstrap afterwards —
that is the one failure mode that must never happen, because `/clear` destroys the cron and the
bootstrap keystroke is what re-arms it.

DEFAULT OFF (`external_clear.DEFAULT_ENABLED`). Opt in with
`CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED=1`.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import external_clear as ec  # noqa: E402
import handoff_files  # noqa: E402
import state  # noqa: E402

_LOG = "external-clear"


# The hold's lifetime. 15 minutes (USER, 2026-09-01). It is a CEILING, not a schedule: the hold
# normally ends when the compacted context lands, seconds later. The TTL exists only so that a
# `jev_compact.py compact` that never returns — a dead network, a wedged provider — degrades the
# session to the mechanical `precompact-handoff.md` instead of holding it forever. An unbounded hold would
# convert one expensive session into a permanently stuck one, which is a worse failure than the
# cost this whole card exists to avoid.
_HOLD_TTL_S = 15 * 60
_PENDING_FILE = "summary-pending.json"
# TRDD-BDZG8Y8A — ceiling on the verify harness's `--phase before` snapshot taken right before
# the clear keystroke. Local file reads only (its external context probe is switched off), so
# the real cost is well under a second; the bound exists so a wedged harness can never hold the
# fire back for longer than this.
_VERIFY_BEFORE_TIMEOUT_S = 10


def _summary_source_readable(transcript: str) -> bool:
    """READABLE, not merely present: an unreadable or EMPTY transcript is a source we cannot
    summarize, and discovering that AFTER the clear is exactly the loss the capture guard
    exists to prevent. Shared by the capture AND the dry-run report (review-fork, 2026-09-01):
    a dry-run that only checked the path string claimed "would clear" on a 0-byte transcript
    the real run declines — same inputs, opposite reports."""
    if not transcript:
        return False
    try:
        p = Path(transcript)
        return p.is_file() and p.stat().st_size > 0
    except OSError:
        return False


def _capture_summary_source(sd: Path, facts: dict, now: int) -> dict | None:
    """Name the summary's source ON DISK, before anything destructive. None ⇒ do not clear.

    This is the guard that REPLACES "never clear blind" (TRDD-2F3I2P18). The old one waited for
    the finished summary — minutes, network — which is precisely what made the clear arrive too
    late to prevent the cache write it exists to prevent. The real precondition was never "the
    summary exists"; it is "the material the summary will be made FROM is still there, and we
    know where". That is answerable with two syscalls.

    Writing the file before the clear also makes the hold crash-safe: if this process dies
    between the fire and the summary, the next heartbeat finds a pending record with a TTL rather
    than a session that silently resumed with nothing.
    """
    import json  # noqa: PLC0415 - only this path needs it

    transcript = str(facts.get("transcript") or "")
    if not _summary_source_readable(transcript):
        return None

    record = {
        "transcript": transcript,
        "key": handoff_files.session_key(transcript),
        "captured": now,
        "expires": now + _HOLD_TTL_S,
    }
    state.atomic_write(sd / _PENDING_FILE, json.dumps(record, indent=2) + "\n")
    return record


def _release_summary_hold(sd: Path, *, key: str) -> None:
    """Drop the hold. Its ABSENCE is the release signal, so this must be unlink-not-rewrite.

    `key` MUST match the PENDING RECORD's own `key` field or this is a no-op (TRDD-RAEGS1D5
    advisor R4). REQUIRED, no unconditional path -- the ONE production caller
    (`summarize_previous_session.py::_main`, verified via `tldr impact` before this was made
    required) already always has its own lane's key in hand by the time it releases, so there
    is no legitimate caller left that needs to release "whichever record happens to be
    there". Before this guard existed at all the release was unconditional: a lane that just
    finished ITS OWN compaction would unlink `summary-pending.json` even if a SECOND,
    still-in-flight lane had since overwritten it with a different transcript's record. The
    retry-then-llm-ext fallback lane can now hold for up to ~15 minutes (a 5-minute Jev retry
    budget plus the llm-ext attempt) instead of the old <=2-minute single `run_compact` call,
    so two overlapping `/clear`s in the same state dir (a second manual clear while the owner
    iterates, or two panes of one project) collide far more often than before — without this
    check, lane A's release would drop lane B's still-active hold and B's session would then
    resume EARLY, before its own compaction landed, pointing at whichever handoff happens to
    be newest (`pending_summary_key`'s own fallback) rather than B's. A missing/unreadable
    record is treated as "nothing to guard" and falls through to the unlink — a record that's
    already gone means there is nothing left to protect anyway.
    """
    import json  # noqa: PLC0415 - only this path needs it

    try:
        rec = json.loads((sd / _PENDING_FILE).read_text(encoding="utf-8"))
        if str(rec.get("key") or "") != key:
            return  # a DIFFERENT lane's still-active hold -- not ours to release
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        (sd / _PENDING_FILE).unlink()
    except OSError:
        pass


def summary_hold_active(sd: Path, now: int) -> bool:
    """True while a cleared session is waiting for its summary — read by the heartbeat.

    FAIL-OPEN on every uncertainty: a missing file, unreadable JSON, or a malformed `expires`
    all mean "not held". A hold is a REFUSAL to do work, so an unparseable record must never be
    able to stop the session — that would turn a corrupt byte into a wedged host, which is the
    failure mode the TTL exists to bound in the first place.
    """
    import json  # noqa: PLC0415

    try:
        rec = json.loads((sd / _PENDING_FILE).read_text(encoding="utf-8"))
        return now < int(rec["expires"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def pending_summary_key(sd: Path) -> str:
    """The key for the handoff that is (or was just) being composed for this state dir.

    TRDD-QZVAEWQH: `dispatch._phase_clear_resume` needs to point the resumed turn at the
    fresh keyed handoff instead of whatever SessionStart already injected. Read
    `summary-pending.json`'s own `key` field while the record is still present — the common
    case, since a resume racing the hold or landing seconds after release both see it. Fall
    back to the newest handoff GROUP on disk once the record is gone (`_release_summary_hold`
    deletes it on success, and a resume can land after that deletion). Returns "" when neither
    source names a key, so the caller omits the extra note rather than pointing at a guess.
    """
    import json  # noqa: PLC0415

    try:
        rec = json.loads((sd / _PENDING_FILE).read_text(encoding="utf-8"))
        key = str(rec.get("key") or "")
        if key:
            return key
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    group = handoff_files.newest_group(sd)
    if group:
        parsed = handoff_files.parse(group[-1].name)
        if parsed:
            return parsed[0]
    return ""


def _last_turn_age(root: Path, now: int) -> int | None:
    """Seconds since the last turn of ANY kind — the PROMPT-CACHE clock.

    Deliberately raw transcript mtime, NOT `fleet_scan.transcript_activity`'s substantive age:
    a heartbeat fire is a real API request and refreshes the cache even though it is not
    substantive work. Using the substantive age here would claim the cache had expired while
    5-minute beats were keeping it hot, and the watcher would clear a warm session for nothing.
    """
    try:
        import cold_cache_compact  # noqa: PLC0415

        transcript = cold_cache_compact.newest_transcript(root)
        if transcript is None:
            return None
        return max(0, now - int(transcript.stat().st_mtime))
    except (OSError, ValueError, ImportError):
        return None


def _decide(
    root: Path, sd: Path, now: int, *, force: bool, on_resume: bool = False, session_id: str = ""
) -> tuple[ec.ClearVerdict, dict]:
    """Gather every runtime fact and run the pure gate. Returns (verdict, facts-for-logging)."""
    import cold_cache_compact  # noqa: PLC0415
    import dispatch  # noqa: PLC0415 - reuses _cadence_active_waiting rather than re-deriving it
    import fleet_scan  # noqa: PLC0415

    # `user_intent` is deliberately NOT imported: this path knows nothing about whether the
    # user is "present". The only keystroke fact anywhere in the system is the LAST KEYSTROKE
    # TIMESTAMP, and it lives where it is used -- inside the injector, which defers 8 s from it
    # and retries. A presence predicate here is what kept this watcher dead for weeks.

    cron = ""
    try:
        cron = (sd / "armed-cadence.cron").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        pass

    idle_s, trailing_enqueues, awaiting_user = fleet_scan.transcript_activity(str(root), now)
    # TRDD-O7UCNNN2: the gate's idle term must ignore heartbeat-only turns, or an ARMED session
    # (this watcher's whole audience) can never exceed the ~5-min beat cadence and the 1-hour
    # floor below is unreachable by construction. `idle_s` (the substantive age) is kept for
    # logging/comparison only -- `human_idle_s` is what feeds the gate.
    human_idle_s = fleet_scan.human_activity_age(str(root), now)
    # `trailing_enqueues` is deliberately NOT wired into `should_clear_externally` -- it is a
    # DIFFERENT signal (the daemon's wedged-session evidence, TRDD-8DR0X08A F2: how many typed
    # commands sat queued and never executed), not a veto for THIS gate. It cannot substitute for
    # `awaiting_user` either: per `fleet_scan.awaiting_user_decision`'s own docstring it only goes
    # non-zero AFTER something has already been typed, so it would miss the FIRST unanswered
    # `tool_use` -- the one that actually reaches a human. `awaiting_user`, below, is the fix for
    # TRDD-OO301H7D: it used to be bound to `_await` and discarded on this same line.
    # Resolved ONCE and carried in `facts`, because `_capture_summary_source` needs the same
    # transcript the verdict was computed from -- it is what names the summary source on disk
    # for the delegated summarizer to pick up (TRDD-QZVAEWQH).
    newest = cold_cache_compact.newest_transcript(root)
    active_waiting = dispatch._cadence_active_waiting(sd, now)
    in_cooldown = cold_cache_compact.clear_in_cooldown(sd, now=now)
    # RECOVERY GUARD (card 1 follow-up item 2, TRDD-L32WC0H7): this daemon-lane decider used to
    # reach BOTH `should_clear_externally` and `should_clear_on_resume` with no recovery guard
    # at all -- `recovery_pending` defaulted False on both, silently, which is the actual bug
    # this closes. `external_clear.recovery_pending` is the SAME shared helper the SessionStart
    # hook and `dispatch._cadence_active_waiting` use, so the allow-list of pending-recovery
    # flags can never drift between the three callers again.
    recovery_pending = ec.recovery_pending(sd)
    # The user's presence is deliberately NOT gathered (owner, 2026-08-13). It used to be read
    # here and fed to the gate as a hard veto; since the injector handles presence by DELAYING
    # 8 s per keystroke and never cancelling, reading it here could only re-introduce the
    # refusal that kept this watcher dead. See `ec.should_clear_externally`'s docstring.
    #
    # The ONE subprocess on this path, so it is skipped whenever a local fact already refuses.
    # Both vetoes hold regardless of what the probe would say, so probing first would spend a
    # bounded-but-real 5 s per fire to compute an input the gate is about to ignore.
    cache_expired = None if (active_waiting or in_cooldown) else ec.cache_certainly_expired(root)
    # TRDD-2F3I2P18 -- a model/effort switch or a plugin/skill reload kills the prefix OUTRIGHT,
    # so from this gate's point of view it is an expired cache arriving by a different route.
    # OR'd into the existing term rather than given a branch of its own: it wants the same veto
    # set, the same cooldown and the same tests, and a parallel trigger would drift from them.
    # Logged separately below so the ATTRIBUTION stays honest -- "cache expired", "you switched
    # model" and "you reloaded plugins" are the same verdict for very different reasons, and a
    # log line that cannot tell them apart is one nobody can act on.
    prefix_dead = None if (active_waiting or in_cooldown) else ec.prefix_invalidated()
    if prefix_dead:
        state.log_line(_LOG, "prefix invalidated (model/effort switch) -- treating as cache-expired")
        cache_expired = True
    # Probed AFTER the same vetoes, and NOT short-circuited by `prefix_dead`: the probe consumes
    # its cursor, so skipping it when the model switch already fired would leave a pending reload
    # event to trigger a SECOND clear on the next beat -- one dead prefix, two clears.
    # `last_turn_age` doubles as the reload probe's paid-detector: a transcript turn newer
    # than an ack stamp means the re-cache already happened and the event must not fire.
    last_turn_age = _last_turn_age(root, now)
    reload_dead = (
        None
        if (active_waiting or in_cooldown)
        else ec.reload_invalidated(
            sd,
            now=now,
            last_turn_ts=None if last_turn_age is None else now - last_turn_age,
        )
    )
    if reload_dead:
        state.log_line(
            _LOG,
            "prefix invalidated (reload/model-switch stamp) -- treating as cache-expired",
        )
        cache_expired = True
    # SPLIT DELIBERATELY: `gate` is exactly the pure decision's parameters, `facts` is the log
    # record that also carries composer-only fields. They were one dict until `transcript` was
    # added to it, which made every run raise `unexpected keyword argument 'transcript'` -- the
    # whole watcher was dead on arrival and the `# type: ignore[arg-type]` that used to sit on
    # the call is what hid it from mypy. Keep them separate: a composer field can never again
    # reach the gate by being added to the wrong dict.
    gate = {
        "idle_seconds": human_idle_s if human_idle_s is not None else idle_s,
        "last_turn_age_s": last_turn_age,
        "ttl_minutes": ec.DEFAULT_TTL_MINUTES,
        "seconds_to_next_fire": ec.seconds_until_next_fire(cron, now),
        "context_tokens": cold_cache_compact.context_tokens_for(newest),
        "min_context": ec.min_context_tokens(),
        "min_idle_s": cold_cache_compact.clear_min_idle_seconds(),
        "headroom_s": ec.headroom_seconds(),
        "active_waiting": active_waiting,
        "in_cooldown": in_cooldown,
        "awaiting_user": awaiting_user,
        "cache_expired": cache_expired,
        "recovery_pending": recovery_pending,
        # TRDD-79LXF6PJ -- the ONLY trigger that can fire on a busy session, and it is OWNED
        # CONDITIONALLY: while Claude Code still auto-compacts, the janitor must stay out of the
        # way or the session is compacted twice. 0 disables the trigger, so resolving ownership
        # here keeps the pure gate free of the question.
        "context_high_water": (
            0 if ec.harness_auto_compacts() else ec.context_high_water_tokens()
        ),
    }
    # `trailing_enqueues` is log-only (see the comment where it is unpacked above) -- carried in
    # `facts`, never in `gate`, so it stays visible for diagnosis without becoming an undeclared
    # extra keyword `should_clear_externally` would reject.
    facts = {
        **gate,
        "transcript": str(newest) if newest else "",
        "trailing_enqueues": trailing_enqueues,
        # Both ages kept side by side for diagnosis -- TRDD-O7UCNNN2 replaced the substantive
        # age with the human one as the GATE's input, but seeing them diverge is exactly the
        # evidence that the fix is doing something on an armed session.
        "transcript_idle_s": idle_s,
        "human_idle_s": human_idle_s,
    }
    if on_resume:
        # The RESUME gate, not the abandoned-session one. A session loaded seconds ago can never
        # satisfy the long-idle term, so `should_clear_externally` would refuse every resume --
        # which is precisely the shrink that matters most, because the first turn after a cold
        # load re-reads the whole context at full price. The hook has already established the
        # `source`; re-asserting it here keeps the pure gate the single place that enforces it.
        #
        # ADVERSARIAL-REVIEW FINDING, TRDD-L32WC0H7 card 1 follow-up: this confirmatory re-check
        # used to always reuse `gate["context_tokens"]` (the plain tail-only reading), while the
        # SessionStart hook that decided to SPAWN this watcher already measured with the widened
        # `context_tokens_for_resume`. On the exact case item 1 exists for (a tail-window miss) the
        # two readings could disagree: the hook fires (its widened reading found a real number),
        # this confirmatory check re-measures with the narrower reader, gets None again, and
        # silently declines -- so nothing is ever cleared and the hook's own fire decision becomes
        # a no-op, with no signal that it happened. `session_id` (passed by the hook via
        # `--session-id` when it spawns this watcher) lets this re-check use the SAME widened
        # reader on the SAME facts. Absent (a bare CLI `--on-resume` invocation with no
        # `--session-id`) this falls back to the pre-existing plain reading -- unchanged for that
        # caller.
        resume_context_tokens = (
            cold_cache_compact.context_tokens_for_resume(
                newest, project_dir=root, session_id=session_id, now=now
            )
            if session_id
            else gate["context_tokens"]
        )
        verdict = ec.should_clear_on_resume(
            source="resume",
            cache_expired=cache_expired,
            context_tokens=resume_context_tokens,
            min_context=gate["min_context"],
            in_cooldown=in_cooldown,
            already_fired_this_session=False,
            recovery_pending=recovery_pending,
        )
        return verdict, {**facts, "gate": "resume", "context_tokens": resume_context_tokens}
    verdict = ec.should_clear_externally(**gate)
    if force and not verdict.fire and verdict.why.startswith(("idle ", "no-headroom")):
        # --force overrides the two TRIGGER terms ONLY (is it idle enough / would the next fire
        # miss). Every SAFETY veto -- cooldown, active waiting, awaiting-user (a human is being
        # asked a question -- TRDD-OO301H7D), unknown idle, tiny context -- still holds, because
        # those are the ones that protect work, and an operator asking to observe the mechanism
        # has not thereby authorized clearing a session someone is typing into or waiting on.
        # (There is no separate "user present" veto -- that one was removed 2026-08-13; see
        # `ec.should_clear_externally`'s docstring for why re-adding it would silently re-break
        # the whole lever.)
        verdict = ec.ClearVerdict(True, "forced", f"--force (gate said: {verdict.why})")
    return verdict, facts


def _snapshot_before(env: dict[str, str]) -> None:
    """TRDD-BDZG8Y8A — take the harness's own `--phase before` snapshot right before the clear.

    Without it an automated clear left `handoff-clear-verify.json` whatever the last HAND-RUN
    drill wrote, so the resumed session's `--phase after` (its resume cue runs it first)
    compared against a snapshot hours old and its PASS table proved nothing about THIS clear
    (first seen on the 2026-09-02 04:23 AgentlensPro fire). A subprocess, not an import: the
    harness resolves root and state dir from CLAUDE_PROJECT_DIR, which must stay child-only in
    this long-lived daemon process (see `_fire`). Pure local reads by construction — the
    harness's agentlensPro probe is switched off through its own option, so the snapshot
    measures the context with the SAME transcript reader the gate used and never waits on an
    external command: every second between the gate and the keystroke is a second the full
    context could still be re-cached at full price (TRDD-2F3I2P18). Fail-open and bounded — a
    diagnostic must never hold back the clear it exists to measure.
    """
    harness = _SCRIPTS / "handoff_clear_verify.py"
    snap_env = {**env, "CLAUDE_PLUGIN_OPTION_HANDOFF_VERIFY_CONTEXT_COMMAND": ""}
    try:
        proc = subprocess.run(
            [sys.executable, str(harness), "--phase", "before"],
            capture_output=True,
            text=True,
            timeout=_VERIFY_BEFORE_TIMEOUT_S,
            env=snap_env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        state.log_line(
            _LOG,
            f"verify before-snapshot skipped ({exc.__class__.__name__}: {exc}) — firing anyway",
        )
        return
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-200:]
        state.log_line(
            _LOG, f"verify before-snapshot failed rc={proc.returncode}: {tail} — firing anyway"
        )


def _fire(
    root: Path, sd: Path, terminal: dict[str, str], now: int, trigger: str = "", transcript: str = "",
) -> None:
    """Spawn `clear_trigger`'s verified chain against the RECORDED pane.

    `CLAUDE_PROJECT_DIR` is set for the child because `clear_trigger._project_root()` reads it,
    and its fallbacks (git toplevel, then cwd) would resolve to the DAEMON's cwd — writing the
    resume marker into some other tree while the cleared session waits for one that never
    arrives.
    """
    import clear_trigger  # noqa: PLC0415
    import cold_cache_compact  # noqa: PLC0415

    # CHILD-ONLY env. Assigning os.environ["CLAUDE_PROJECT_DIR"] here would poison a
    # Claude-reserved var for the whole parent process — this runs inside the long-lived
    # daemon, so every later plugin in that process would inherit one project's path.
    child_env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
    # BEFORE the spawn, never after: the chain types `/clear` as soon as a pane is free, and a
    # snapshot that lands after the keystroke records the collapsed context and the recreated
    # cron — the `after` phase would then see no delta and report a false FAIL (TRDD-BDZG8Y8A).
    _snapshot_before(child_env)
    clear_trigger._spawn_chain({
        "delay": 0.0,  # no turn to settle out — nothing is running in front of us
        "terminal": terminal,
        "first": clear_trigger.CLEAR_CMD,
        "then": list(clear_trigger._BOOTSTRAP_CMDS),
        "state_dir": str(sd),
        "gate_baseline": clear_trigger._gate_baseline(),
        # The after-phase clause is FIRST for the same reason the skill puts it first
        # (`skills/janitor-handoff-and-clear/SKILL.md:116`): the checks it runs — context size,
        # cron id, resume-flag consumption — are all properties of the FRESH session, and a
        # turn of real work destroys the very deltas being measured.
        #
        # It is here because `_snapshot_before` above is UNCONDITIONAL: without this, every
        # automated fire pays for a `before` snapshot that nothing ever compares against, and
        # `handoff-clear-verify.json` keeps only a `before` key forever (measured on
        # llm-externalizer, 2026-09-03 — TRDD-1QJIZFFW box 5 could not tick by waiting). So this
        # does not ADD a cost; it stops discarding one already paid. The manual path has asked
        # for it all along — the two directives had simply diverged.
        #
        # THE PATH IS INTERPOLATED ABSOLUTE, and every part of that matters. This lane fires
        # FLEET-WIDE, so the resumed session's cwd is the CLEARED project — never this repo. A
        # repo-relative `scripts/...` (the first version of this clause) names a file that does
        # not exist there, and `${CLAUDE_PLUGIN_ROOT}` would only move the dependency to a
        # variable that may not be set in a plain Bash call. The daemon already knows the answer
        # — `_SCRIPTS` is resolved from this module's own location, the same way the `before`
        # call at `_snapshot_before` gets it — so the target session is told, not asked. Note the
        # project context is still correct: the JSON lives in the CLEARED project's
        # `.janitor/state/`, which is where cwd already points; only the SCRIPT is elsewhere.
        #
        # `--script` runs it as a self-contained PEP-723 script instead of resolving against the
        # foreign project's own environment; `--quiet` keeps the pane clean. NO BACKTICKS — this
        # string is TYPED INTO A LIVE PANE, and a backtick is command substitution on any layer
        # that reaches a shell.
        #
        # The skip-on-failure clause restores FAIL-OPEN at the layer that now needs it. The
        # harness is fail-open internally, but that covers the SCRIPT, not a model told to run
        # it: handed a failing FIRST instruction, a model retries, hunts for the file, or asks —
        # and that is the resume path, whose entire purpose is getting straight back to work.
        # KNOWN LIMIT, accepted rather than hidden: under the daemon `_SCRIPTS` resolves inside
        # the VERSION-PINNED plugin cache, and this string is consumed minutes later (the clear
        # lane's whole shape is fire -> /clear -> re-arm -> resume, and a summary hold can add
        # 15 min). A plugin roll in that window leaves the path naming a pruned version. Measured
        # 2026-09-05: 16 versions retained, oldest a week old, no pruning observed and no stable
        # `current` symlink to anchor on instead. The failure is BENIGN and VISIBLE — the skip
        # clause below keeps the resume moving, and box 5 needs an `after` key to appear in the
        # JSON, so a skipped run leaves the box unticked rather than falsely ticked. The
        # path-free fix (hand the session a slash command, which resolves through the live plugin
        # registry) needs a command that does not exist yet. `${CLAUDE_PLUGIN_ROOT}` is NOT a
        # substitute for a reason that does NOT depend on an observation: it points at the same
        # `cache/<version>/` directory, so it would relocate this limit, not remove it. (It was
        # also unset in a plain Bash call in the session that wrote this — but that is ONE
        # environment, not the resumed session's, so do not read it as a general fact.)
        "directive": (
            f'run: uv run --script --quiet "{_SCRIPTS / "handoff_clear_verify.py"}" '
            "--phase after (a diagnostic - if that command fails, skip it and continue with "
            "the rest), then read the injected SessionStart handoff summary (auto-composed "
            "with no model turn - follow its wikimem/TRDD links via memgrep recall on "
            "demand), then resume your prior in-flight task."
        ),
        # Let the chain's warm-cancel probe run ONLY when coldness is what fired us. The other
        # two triggers are idleness/prediction rules that fire with the cache deliberately warm.
        "cache_gated": trigger in (ec.TRIGGER_CACHE_CERTAIN_EXPIRED, ec.TRIGGER_RESUMED_COLD),
        # The reference point for the came-back cancel, which applies to EVERY trigger: a
        # substantive turn newer than this retires the clear. `now` is the same clock the
        # verdict was computed against, so the two can never drift apart.
        "verdict_ts": int(now),
        # TRDD-RAEGS1D5 card 5: the transcript this fire ALREADY resolved and verified
        # readable (`_capture_summary_source`) -- so `_persist_resume_state` can write the
        # per-pane sidecar the fresh session's post-clear-compact hook consumes, instead of
        # that hook guessing "whichever handoff is newest" off the state dir.
        "transcript_path": transcript,
    }, env=child_env)
    # STAMP AT SPAWN, unlike the in-model lever which stamps only on a confirmed send.
    # The difference is real, not a relaxation: there, a refused send meant the USER WAS
    # PRESENT, so stamping would have turned a veto into a two-hour mute. Here presence is
    # already a hard veto upstream, the send is asynchronous (the chain waits for a free pane
    # and retries with long patience), and NOT stamping would respawn a chain on every daemon
    # beat — a spawn storm against a `clear-chain.lock` that only serializes them.
    cold_cache_compact.mark_clear_fired(sd, now=now)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Decide, compose and fire a handoff-and-clear from OUTSIDE the model."
    )
    ap.add_argument("--project-root", default="", help="the session's project root (required "
                    "for a daemon run; defaults to CLAUDE_PROJECT_DIR / cwd)")
    ap.add_argument("--dry-run", action="store_true",
                    help="gather, decide and compose, but write NOTHING and fire NOTHING")
    ap.add_argument("--force", action="store_true",
                    help="override the idle/cache TRIGGER terms; every safety veto still holds")
    ap.add_argument("--on-resume", action="store_true",
                    help="use the RESUME gate (ec.should_clear_on_resume) instead of the "
                         "abandoned-session one: a just-loaded session can never satisfy the "
                         "long-idle term, so the default gate would always refuse it")
    ap.add_argument("--session-id", default="", help="TRDD-L32WC0H7 card 1 follow-up, "
                    "adversarial-review finding: the SessionStart hook that spawns this watcher "
                    "with --on-resume passes its OWN session_id here so the confirmatory "
                    "_decide re-check can use the SAME widened context_tokens_for_resume reader "
                    "the hook already used, instead of silently re-measuring with the narrower "
                    "plain reader and disagreeing with the hook's own fire decision. Absent, "
                    "_decide falls back to the pre-existing plain reading unchanged.")
    args = ap.parse_args()

    root = Path(args.project_root or os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
    sd = root / ".janitor" / "state"
    now = int(time.time())

    if not ec.enabled() and not args.dry_run:
        print(f"DISABLED set {ec.ENABLED_ENV}=1 to opt in")
        return 0
    if not sd.is_dir():
        print(f"NO_JANITOR_STATE {sd}")
        return 0

    # PER-ROOT SINGLEFLIGHT (incident 2026-08-23, external-clear.log): the daemon re-fired while
    # a prior watcher for the SAME session was still summarizing, and the log shows two retry
    # chains interleaved (attempt sequences 1..5 twice, distinct backoffs) — each holding fleet
    # leases, each restarting llm-ext on a transcript the other was growing. One watcher per
    # state dir at a time; a second invocation exits instead of queueing. The lock goes stale
    # after the largest budget any holder can legitimately spend, so a killed watcher can never
    # park the lever forever.
    lock = sd / "external-clear.lock"
    stale_after = ec.summary_deadline_s() + 600
    for _ in range(2):  # second pass only after removing a stale lock
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {now}\n".encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                held_s = now - int(lock.stat().st_mtime)
            except OSError:
                held_s = stale_after + 1  # unreadable ⇒ treat as stale, take over
            if held_s <= stale_after:
                print(f"ALREADY_RUNNING a watcher has held {lock.name} for {held_s}s — exiting")
                return 0
            lock.unlink(missing_ok=True)
    else:
        print("LOCK_RACE could not take the singleflight lock — exiting")
        return 0

    try:
        return _run(root, sd, now, args)
    finally:
        lock.unlink(missing_ok=True)


def _run(root: Path, sd: Path, now: int, args: argparse.Namespace) -> int:
    """The body of `main` past the singleflight lock — split so the lock's try/finally stays
    two lines instead of indenting the whole flow."""
    verdict, facts = _decide(
        root, sd, now, force=args.force, on_resume=args.on_resume, session_id=args.session_id
    )
    print(f"VERDICT {'FIRE' if verdict.fire else 'HOLD'} "
          f"trigger={verdict.trigger or '-'} why={verdict.why} "
          f"transcript_idle_s={facts.get('transcript_idle_s')} "
          f"human_idle_s={facts.get('human_idle_s')}")
    if not verdict.fire:
        return 0

    # The pane is resolved BEFORE the handoff is written: a session we cannot type into must
    # not be cleared at all, and finding that out after writing state would leave a handoff
    # claiming a clear that never happens.
    import fleet_restart  # noqa: PLC0415

    terminal = ec.terminal_from_record(fleet_restart.recorded_terminal(str(root)))
    if terminal.get("kind") == "unknown":
        print("NO_RECORDED_PANE cannot bootstrap after /clear — declining")
        state.log_line(_LOG, "declined: no recorded pane, a cleared session could not re-arm")
        return 0

    # ─── TRDD-2F3I2P18 — CLEAR FIRST, THEN SUMMARIZE ───────────────────────────────────────
    #
    # The old order was compose → verify → fire. `_compose` shells out to llm-ext, which takes
    # MINUTES (a 12 MB transcript did not finish inside a 900 s budget), and through that whole
    # window the session still held its full context. Any turn taken in it paid the exact
    # cache-build write the clear exists to prevent. The clear was gated behind the slowest step
    # in its own chain — measured cost: the owner burned a week of quota in two days, then could
    # not use Claude Code for three (2026-09-01).
    #
    # THE OWNER'S 2026-08-28 INVARIANT ("never execute the /clear unless you have already the
    # certainty of having the summarized context ready to be injected") IS SUPERSEDED, BY THEM,
    # 2026-09-01, on this ground: llm-ext summarizes from the ON-DISK transcript
    # (`external_clear.run_llm_ext_summary` passes `--transcript <path>`), and that append-only
    # `.jsonl` under ~/.claude/projects/ is NOT in the context `/clear` empties. Nothing can be
    # lost by clearing first, so the invariant's premise — that the source dies with the context —
    # does not hold for this composer. It was reasoning about a template composed from LIVE state.
    #
    # THE SAFETY MOVES RATHER THAN DISAPPEARING, which is the only reason this reorder is
    # legitimate. The old guard asked "is the summary ready?" — minutes, network, and it is what
    # made the clear too late to help. The new guard asks "is the transcript CAPTURED and
    # READABLE?" — milliseconds, no network — and that is the real precondition: it is what makes
    # the clear recoverable, because whatever happens after it, the source is named on disk.
    # DRY-RUN RETURNS BEFORE THE CAPTURE (review-fork finding, 2026-09-01): the capture WRITES
    # `summary-pending.json`, which arms the 15-minute hold `dispatch.summary_hold_active`
    # honours — so a dry-run placed after it blocked resumes and chores on a session that was
    # never cleared. A dry-run must write nothing; it reports from `facts` instead.
    if args.dry_run:
        transcript = str(facts.get("transcript") or "")
        if _summary_source_readable(transcript):
            print(f"DRY_RUN would clear via {terminal.get('kind')} then summarize {transcript}")
        else:
            # The SAME predicate the real capture applies, so a dry-run never claims a fire
            # the real run would decline (an empty just-born .jsonl is the common case).
            print("DRY_RUN would decline: transcript missing, empty, or unreadable")
        return 0

    pending = _capture_summary_source(sd, facts, now)
    if pending is None:
        print("NO_TRANSCRIPT declining to clear — cannot name the summary source")
        state.log_line(
            _LOG,
            "declined: the target transcript is missing or unreadable — clearing now would "
            "leave nothing to summarize FROM, which is the one loss this reorder must not "
            "introduce",
        )
        return 0

    # FIRE NOW. Nothing between the gate and this line touches the network or the model: the
    # only work done above is naming the transcript on disk. That is the entire point of
    # TRDD-2F3I2P18 — every second spent here was a second the full context could still be
    # re-cached at full price.
    # TRDD-RAEGS1D5 card 5: `pending["transcript"]` is the SAME transcript `_capture_
    # summary_source` just verified readable -- passed through so `_fire` can name it in the
    # chain payload for `_persist_resume_state` to sidecar.
    _fire(root, sd, terminal, now, trigger=verdict.trigger or "", transcript=pending["transcript"])
    # Consume any pending reload event ONLY now that the chain is actually spawned. The probe in
    # `_decide` deliberately does not consume (review-fork finding, 2026-09-01): a dry-run, a
    # gate veto, or the NO_RECORDED_PANE decline above must leave the event pending so the next
    # beat can still clear a prefix that is still dead.
    ec.consume_reload_events(sd)
    state.log_line(_LOG, f"fired: trigger={verdict.trigger} — {verdict.why}")
    print(f"CLEAR_CHAIN_SPAWNED trigger={verdict.trigger}")

    # TRDD-QZVAEWQH — NEITHER MODE COMPOSES. Both the daemon's abandoned-session lane (no
    # `--on-resume`, keyless under launchd — measured: no shell rc file, `launchctl getenv`, nor
    # `~/.claude/settings.json` env defines OPENROUTER_API_KEY there) and the `--on-resume`
    # SessionStart-hook lane used to differ here: the hook composed inline because it happened to
    # have the key. That let an on-resume fire type `/clear` while its OWN compose was still
    # summarizing the transcript the brand-new session's SessionStart was about to summarize
    # again — two `llm-ext` runs on one transcript, two keyed handoffs. So this branch is now
    # unconditional: fire, then delegate, in both modes.
    #
    # The hold is left ARMED, not released: `summarize_previous_session.py`, spawned detached from
    # the CLEARED session's own SessionStart (which always has the key — it inherits the new
    # session's environment), re-captures the same transcript under its own hold and writes the
    # keyed handoff once jev compaction returns. That is the ONE summarizer for this transcript now —
    # there is no second writer left to race it.
    print(
        f"SUMMARY_DELEGATED key={pending['key'] or handoff_files.UNKEYED_KEY} — the "
        "cleared session's SessionStart summarizer owns it"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
