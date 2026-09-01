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
     (transcript mtime, `ttl-regime.json`, `armed-cadence.cron`, the presence breadcrumb).
  2. COMPOSE — the ACTIVE SKILLS in full, then the `llm-ext session-summary`. Zero tokens from
     THIS session (llm-ext runs on its own free models, out of process), which is what "zero
     turn" means — not that no model is involved. **No summary means NO CLEAR** (TRDD-79LXF6PJ):
     the composed handoff that used to be the network-free fallback is gone, so an empty payload
     would clear a session with nothing to resume from. Declining costs a full-price turn;
     clearing blind costs the work.
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
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import active_skills  # noqa: E402
import external_clear as ec  # noqa: E402
import handoff_files  # noqa: E402
import state  # noqa: E402

_LOG = "external-clear"


# The hold's lifetime. 15 minutes (USER, 2026-09-01). It is a CEILING, not a schedule: the hold
# normally ends when the summary lands, seconds-to-minutes later. The TTL exists only so that an
# llm-ext that never returns — a dead network, a wedged free-tier model — degrades the session to
# the mechanical `precompact-handoff.md` instead of holding it forever. An unbounded hold would
# convert one expensive session into a permanently stuck one, which is a worse failure than the
# cost this whole card exists to avoid.
_HOLD_TTL_S = 15 * 60
_PENDING_FILE = "summary-pending.json"


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


def _release_summary_hold(sd: Path) -> None:
    """Drop the hold. Its ABSENCE is the release signal, so this must be unlink-not-rewrite."""
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
    root: Path, sd: Path, now: int, *, force: bool, on_resume: bool = False
) -> tuple[ec.ClearVerdict, dict]:
    """Gather every runtime fact and run the pure gate. Returns (verdict, facts-for-logging)."""
    import cold_cache_compact  # noqa: PLC0415
    import dispatch  # noqa: PLC0415 - reuses _cadence_active_waiting rather than re-deriving it
    import fleet_scan  # noqa: PLC0415

    # `user_intent` is deliberately NOT imported: this path knows nothing about whether the
    # user is "present". The only keystroke fact anywhere in the system is the LAST KEYSTROKE
    # TIMESTAMP, and it lives where it is used — inside the injector, which defers 8 s from it
    # and retries. A presence predicate here is what kept this watcher dead for weeks.

    cron = ""
    try:
        cron = (sd / "armed-cadence.cron").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        pass

    idle_s, trailing_enqueues, awaiting_user = fleet_scan.transcript_activity(str(root), now)
    # `trailing_enqueues` is deliberately NOT wired into `should_clear_externally` — it is a
    # DIFFERENT signal (the daemon's wedged-session evidence, TRDD-8DR0X08A F2: how many typed
    # commands sat queued and never executed), not a veto for THIS gate. It cannot substitute for
    # `awaiting_user` either: per `fleet_scan.awaiting_user_decision`'s own docstring it only goes
    # non-zero AFTER something has already been typed, so it would miss the FIRST unanswered
    # `tool_use` — the one that actually reaches a human. `awaiting_user`, below, is the fix for
    # TRDD-OO301H7D: it used to be bound to `_await` and discarded on this same line.
    # Resolved ONCE and carried in `facts`, because the composer needs the same transcript the
    # verdict was computed from. Without it there `_compose` had no path to hand llm-ext, and
    # the summary branch would have degraded to template-only on every run — shipping the
    # feature dark in the same commit that exists to un-dark it (TRDD-1QJIZFFW).
    newest = cold_cache_compact.newest_transcript(root)
    active_waiting = dispatch._cadence_active_waiting(sd, now)
    in_cooldown = cold_cache_compact.clear_in_cooldown(sd, now=now)
    # The user's presence is deliberately NOT gathered (owner, 2026-08-13). It used to be read
    # here and fed to the gate as a hard veto; since the injector handles presence by DELAYING
    # 8 s per keystroke and never cancelling, reading it here could only re-introduce the
    # refusal that kept this watcher dead. See `ec.should_clear_externally`'s docstring.
    #
    # The ONE subprocess on this path, so it is skipped whenever a local fact already refuses.
    # Both vetoes hold regardless of what the probe would say, so probing first would spend a
    # bounded-but-real 5 s per fire to compute an input the gate is about to ignore.
    cache_expired = None if (active_waiting or in_cooldown) else ec.cache_certainly_expired(root)
    # TRDD-2F3I2P18 — a model/effort switch or a plugin/skill reload kills the prefix OUTRIGHT,
    # so from this gate's point of view it is an expired cache arriving by a different route.
    # OR'd into the existing term rather than given a branch of its own: it wants the same veto
    # set, the same cooldown and the same tests, and a parallel trigger would drift from them.
    # Logged separately below so the ATTRIBUTION stays honest — "cache expired", "you switched
    # model" and "you reloaded plugins" are the same verdict for very different reasons, and a
    # log line that cannot tell them apart is one nobody can act on.
    prefix_dead = None if (active_waiting or in_cooldown) else ec.prefix_invalidated()
    if prefix_dead:
        state.log_line(_LOG, "prefix invalidated (model/effort switch) — treating as cache-expired")
        cache_expired = True
    # Probed AFTER the same vetoes, and NOT short-circuited by `prefix_dead`: the probe consumes
    # its cursor, so skipping it when the model switch already fired would leave a pending reload
    # event to trigger a SECOND clear on the next beat — one dead prefix, two clears.
    reload_dead = None if (active_waiting or in_cooldown) else ec.reload_invalidated(sd, now=now)
    if reload_dead:
        state.log_line(
            _LOG,
            "prefix invalidated (reload/model-switch stamp) — treating as cache-expired",
        )
        cache_expired = True
    # SPLIT DELIBERATELY: `gate` is exactly the pure decision's parameters, `facts` is the log
    # record that also carries composer-only fields. They were one dict until `transcript` was
    # added to it, which made every run raise `unexpected keyword argument 'transcript'` — the
    # whole watcher was dead on arrival and the `# type: ignore[arg-type]` that used to sit on
    # the call is what hid it from mypy. Keep them separate: a composer field can never again
    # reach the gate by being added to the wrong dict.
    gate = {
        "idle_seconds": idle_s,
        "last_turn_age_s": _last_turn_age(root, now),
        "ttl_minutes": ec.read_ttl_minutes(sd),
        "seconds_to_next_fire": ec.seconds_until_next_fire(cron, now),
        "context_tokens": cold_cache_compact.context_tokens_for(newest),
        "min_context": ec.min_context_tokens(),
        "min_idle_s": cold_cache_compact.clear_min_idle_seconds(),
        "headroom_s": ec.headroom_seconds(),
        "active_waiting": active_waiting,
        "in_cooldown": in_cooldown,
        "awaiting_user": awaiting_user,
        "cache_expired": cache_expired,
        # TRDD-79LXF6PJ — the ONLY trigger that can fire on a busy session, and it is OWNED
        # CONDITIONALLY: while Claude Code still auto-compacts, the janitor must stay out of the
        # way or the session is compacted twice. 0 disables the trigger, so resolving ownership
        # here keeps the pure gate free of the question.
        "context_high_water": (
            0 if ec.harness_auto_compacts() else ec.context_high_water_tokens()
        ),
    }
    # `trailing_enqueues` is log-only (see the comment where it is unpacked above) — carried in
    # `facts`, never in `gate`, so it stays visible for diagnosis without becoming an undeclared
    # extra keyword `should_clear_externally` would reject.
    facts = {
        **gate,
        "transcript": str(newest) if newest else "",
        "trailing_enqueues": trailing_enqueues,
    }
    if on_resume:
        # The RESUME gate, not the abandoned-session one. A session loaded seconds ago can never
        # satisfy the long-idle term, so `should_clear_externally` would refuse every resume —
        # which is precisely the shrink that matters most, because the first turn after a cold
        # load re-reads the whole context at full price. The hook has already established the
        # `source`; re-asserting it here keeps the pure gate the single place that enforces it.
        verdict = ec.should_clear_on_resume(
            source="resume",
            cache_expired=cache_expired,
            context_tokens=gate["context_tokens"],
            min_context=gate["min_context"],
            in_cooldown=in_cooldown,
            already_fired_this_session=False,
        )
        return verdict, {**facts, "gate": "resume"}
    verdict = ec.should_clear_externally(**gate)
    if force and not verdict.fire and verdict.why.startswith(("idle ", "no-headroom")):
        # --force overrides the two TRIGGER terms ONLY (is it idle enough / would the next fire
        # miss). Every SAFETY veto — cooldown, active waiting, awaiting-user (a human is being
        # asked a question — TRDD-OO301H7D), unknown idle, tiny context — still holds, because
        # those are the ones that protect work, and an operator asking to observe the mechanism
        # has not thereby authorized clearing a session someone is typing into or waiting on.
        # (There is no separate "user present" veto — that one was removed 2026-08-13; see
        # `ec.should_clear_externally`'s docstring for why re-adding it would silently re-break
        # the whole lever.)
        verdict = ec.ClearVerdict(True, "forced", f"--force (gate said: {verdict.why})")
    return verdict, facts


def _compose(root: Path, verdict: ec.ClearVerdict, facts: dict) -> tuple[str, list[str]]:
    """Return the llm-ext session summary that becomes the post-`/clear` payload.

    TRDD-79LXF6PJ — THE DAEMON NO LONGER COMPOSES A HANDOFF. It used to emit a three-part
    document: a mechanically-gathered index (in-flight cards, recent commits, open findings), the
    llm-ext summary, and a truncated tail of raw turns. The owner retired that whole shape
    (2026-08-23), having been shown and having declined the narrower option of keeping the free
    index: every compaction goes through the llm-externalizer, and its summary already ends with
    the pending work, so a separately-composed handoff is redundant.

    Returns ("", reasons) when no summary exists — see `main`, which then DECLINES TO CLEAR.

    ⚠ THIS REVERSES A PRIOR OWNER RULING, DELIBERATELY, AND THE REVERSAL IS THE RISKY PART.
    On 2026-08-13 the owner ruled *"the compacting must succeed no matter what"*, and this
    function concluded: *"Degrading to a smaller handoff is survivable; degrading to NO clear is
    not"* — hence the old facts+tail fallback, which needed no network and could always be
    produced. With the handoff gone there is no such floor: if llm-ext cannot summarize, there is
    NOTHING to survive the clear. Clearing anyway would destroy a session with no record at all,
    which is strictly worse than the full-price turn the 2026-08-13 ruling was protecting against
    — one costs money, the other costs the work. So the guarantee moves from "always clear" to
    "never clear blind", per the standing fail-fast rule: it either works as intended or it stops.
    """
    del root, verdict  # the mechanical index they fed is retired; kept in the signature so the
    # call site and its tests keep one shape while this lands.
    transcript = str(facts.get("transcript") or "")

    # THE WIRING (TRDD-1QJIZFFW). `use_llm_ext()` shipped exported, defaulting True, with ZERO
    # callers — a switch whose default was a promise the code did not keep. This is the caller.
    #
    # RETRY, THEN DEGRADE — NEVER BLOCK FOREVER (owner, 2026-08-13: *"the compacting must succeed
    # no matter what. even if it gets timeouts or error or disconnects from the internet for
    # hours"*). `summarize_with_retry` keeps trying across timeouts, 429s and a dead network,
    # taking a fleet-lane ticket per attempt so 20 sessions do not burst at one free-tier
    # endpoint. It stops early only when retrying provably cannot help.
    #
    # What must succeed unconditionally is the CLEAR, and it does: both branches produce a
    # handoff and neither can produce none. When the summary never lands, `compose_handoff`
    # emits the scriptable facts and the message tail alone — no network, no model, always
    # available. Degrading to a smaller handoff is survivable; degrading to NO clear is not,
    # because the un-shrunk session then pays the full-price turn this whole feature exists to
    # prevent. So the summary is best-effort and the clear is the guarantee.
    summary = None
    if ec.use_llm_ext() and transcript:
        # RESUME RUNS ON THE HUMAN'S CLOCK (incident 2026-08-25): this compose executes inside a
        # BLOCKING SessionStart hook, so its budget is one attempt plus a bounded lane wait —
        # never the 2600 s abandoned-session deadline, which froze 16 simultaneously-resumed
        # sessions for 40+ minutes behind the shared llm-ext lane. The abandoned-session path
        # (daemon-driven, nobody watching) keeps the full deadline and the unbounded lane wait.
        on_resume = facts.get("gate") == "resume"
        got = ec.summarize_with_retry(
            transcript,
            deadline=time.time()
            + (ec.resume_summary_deadline_s() if on_resume else ec.summary_deadline_s()),
            log=lambda m: state.log_line(_LOG, m),
            # TRDD-YOZ9TS3W: engages the progress-observed retry gate so a chunk stuck past
            # LLM_EXT_TIMEOUT_S is given up on instead of restarting the same doomed chunk until
            # the deadline. None (llm-ext unresolvable) simply runs without the gate.
            progress_fn=ec.llm_ext_progress_fn(),
            lease_wait_budget_s=ec.RESUME_LEASE_WAIT_S if on_resume else None,
        )
        summary = got.text
        if not summary:
            state.log_line(_LOG, f"no summary: {got.outcome} — {got.detail}")
    if not summary:
        # No template to fall back to any more. The caller reads "" as "do not clear".
        return "", ["no-summary"]

    # ACTIVE SKILLS FIRST, IN FULL, THEN THE SUMMARY (owner, 2026-08-23). The order is the
    # requirement, not a preference: the summary describes a session in which those skills were
    # loaded and therefore refers to them, so a summary injected above (or without) them opens
    # with references that resolve to nothing.
    skills = active_skills.render(transcript) if transcript else ""
    header = f"# Session summary — {time.strftime('%Y-%m-%dT%H:%M:%S%z')} (llm-externalizer)\n\n"
    text = f"{skills}\n\n---\n\n{header}{summary}\n" if skills else f"{header}{summary}\n"

    # THE CONCISION CONTRACT IS DELIBERATELY NOT APPLIED HERE ANY MORE, and that is a ratified
    # constraint being retired for this path — recorded loudly rather than dropped quietly.
    # `check_handoff_concise` (4096 B, no fenced blocks, must carry a reference) governs a
    # LINK-ONLY HANDOFF: a pointer into durable storage, whose whole virtue is not inlining what a
    # link can resolve. This payload is the opposite artifact by design — a compaction RESULT that
    # REPLACES the context, carrying skills reproduced verbatim at the owner's explicit
    # instruction. Judging it by that contract would fail every correct payload and pass only
    # useless ones. The guard still governs the in-session handoff path in `clear_trigger`, which
    # is still link-only; nothing there is weakened.
    return text, []


def _fire(root: Path, sd: Path, terminal: dict[str, str], now: int, trigger: str = "") -> None:
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
    clear_trigger._spawn_chain({
        "delay": 0.0,  # no turn to settle out — nothing is running in front of us
        "terminal": terminal,
        "first": clear_trigger.CLEAR_CMD,
        "then": list(clear_trigger._BOOTSTRAP_CMDS),
        "state_dir": str(sd),
        "gate_baseline": clear_trigger._gate_baseline(),
        "directive": (
            "read the injected SessionStart handoff summary FIRST (auto-composed with no "
            "model turn — follow its wikimem/TRDD links via memgrep recall on demand), "
            "then resume your prior in-flight task."
        ),
        # Let the chain's warm-cancel probe run ONLY when coldness is what fired us. The other
        # two triggers are idleness/prediction rules that fire with the cache deliberately warm.
        "cache_gated": trigger in (ec.TRIGGER_CACHE_CERTAIN_EXPIRED, ec.TRIGGER_RESUMED_COLD),
        # The reference point for the came-back cancel, which applies to EVERY trigger: a
        # substantive turn newer than this retires the clear. `now` is the same clock the
        # verdict was computed against, so the two can never drift apart.
        "verdict_ts": int(now),
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
    verdict, facts = _decide(root, sd, now, force=args.force, on_resume=args.on_resume)
    print(f"VERDICT {'FIRE' if verdict.fire else 'HOLD'} "
          f"trigger={verdict.trigger or '-'} why={verdict.why}")
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
    _fire(root, sd, terminal, now, trigger=verdict.trigger or "")
    # Consume any pending reload event ONLY now that the chain is actually spawned. The probe in
    # `_decide` deliberately does not consume (review-fork finding, 2026-09-01): a dry-run, a
    # gate veto, or the NO_RECORDED_PANE decline above must leave the event pending so the next
    # beat can still clear a prefix that is still dead.
    ec.consume_reload_events(sd)
    state.log_line(_LOG, f"fired: trigger={verdict.trigger} — {verdict.why}")
    print(f"CLEAR_CHAIN_SPAWNED trigger={verdict.trigger}")

    # NOW summarize — after the clear, from the path captured BEFORE it. This process outlives
    # the `/clear` it fired (the clear lands in the SESSION's pane; we are a separate process),
    # which is what lets the expensive half run on the far side of the cheap half.
    #
    # `pending["transcript"]` and NOT a fresh `newest_transcript(root)`: after the clear the
    # newest transcript is the NEW, EMPTY one, so re-resolving here would summarize nothing and
    # report success. This is the single most likely way to get this reorder wrong.
    text, reasons = _compose(root, verdict, {**facts, "transcript": pending["transcript"]})
    if reasons:
        state.log_line(_LOG, f"summary violates the concision contract: {reasons}")
    if not text.strip():
        # No summary. The session is ALREADY cleared, so declining is not an option any more —
        # the question is only what it resumes from. The mechanical `precompact-handoff.md`
        # written by the PreCompact hook is the floor, and the hold's TTL releases the session
        # onto it. Leaving `summary-pending.json` in place would be the worse failure: a session
        # held forever on a summary that is never coming.
        state.log_line(
            _LOG,
            "no llm-ext summary AFTER the clear — leaving the hold to expire on its TTL so the "
            "session resumes from the mechanical precompact handoff rather than waiting forever",
        )
        print("NO_SUMMARY_POST_CLEAR degrading to the mechanical handoff")
        return 0

    handoff_files.write(sd, pending["key"] or handoff_files.UNKEYED_KEY, text, now=now)
    _release_summary_hold(sd)
    print(f"SUMMARY_READY {len(text.encode('utf-8'))}B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
