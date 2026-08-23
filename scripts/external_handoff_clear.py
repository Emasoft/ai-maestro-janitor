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
        # TRDD-79LXF6PJ — the ONLY trigger that can fire on a busy session. 0 means the backstop
        # is off, which is a real state worth noticing rather than a quiet default.
        "context_high_water": ec.context_high_water_tokens(),
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
        got = ec.summarize_with_retry(
            transcript,
            deadline=time.time() + ec.summary_deadline_s(),
            log=lambda m: state.log_line(_LOG, m),
            # TRDD-YOZ9TS3W: engages the progress-observed retry gate so a chunk stuck past
            # LLM_EXT_TIMEOUT_S is given up on instead of restarting the same doomed chunk until
            # the deadline. None (llm-ext unresolvable) simply runs without the gate.
            progress_fn=ec.llm_ext_progress_fn(),
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

    text, reasons = _compose(root, verdict, facts)
    # TRDD-79LXF6PJ — NEVER CLEAR BLIND. With the composed handoff retired there is no
    # network-free floor left: an empty payload means the session would lose everything, and
    # `/clear` is the one operation here that cannot be undone. Declining costs a full-price turn;
    # clearing costs the work. The next fire retries, which is the correct outer loop.
    if not text.strip():
        print("NO_SUMMARY declining to clear — llm-ext produced no summary")
        state.log_line(_LOG, "declined: no llm-ext summary, refusing to clear blind")
        return 0
    if reasons:
        print(f"HANDOFF_NOT_CONCISE {','.join(reasons)}")
        state.log_line(_LOG, f"summary violates the concision contract: {reasons}")

    if args.dry_run:
        print(f"DRY_RUN would clear via {terminal.get('kind')} "
              f"({len(text.encode('utf-8'))}B handoff)")
        print("--- handoff ---")
        print(text)
        return 0

    # TRDD-5RXBI65T — write to a path NOBODY ELSE WILL WRITE, never the shared
    # `agent-handoff.md`. This line was an unconditional `atomic_write` on that shared path, and
    # it destroyed the model-authored handoff twice in two days (2026-08-22 17:38:10 and
    # 2026-08-23 09:22), silently: no `.prev`, and `.janitor/state/` is gitignored.
    #
    # The key is the TARGET session's — `facts["transcript"]`, resolved once at :236 — and NOT
    # this process's `CLAUDE_CODE_SESSION_ID`. That distinction is the whole fix: this script
    # usually runs from the machine-wide daemon, a long-lived singleton that inherits its session
    # id from whichever session launched it (one id held for three days across every project it
    # served). Keying on the writer would file this handoff under a stranger's id, in the state
    # dir of a session that will never look for it — a lost write traded for an unreadable one.
    # An unresolvable target gets the UNKEYED sentinel, NOT the legacy shared path. Writing
    # `agent-handoff.md` here would have reproduced this card's bug verbatim on the very line
    # meant to remove it: an unconditional `atomic_write` to a path other writers use, so two
    # keyless runs would clobber each other and either would destroy a pre-upgrade handoff that
    # is some session's ONLY record. An unkeyed handoff groups slightly wrong and stays readable;
    # a clobbered one is gone. Nothing writes the legacy path any more — it is read-only.
    key = handoff_files.session_key(facts.get("transcript"))
    if not key:
        state.log_line(_LOG, "no target transcript — filing the handoff under the unkeyed group")
    handoff_files.write(sd, key or handoff_files.UNKEYED_KEY, text, now=now)
    _fire(root, sd, terminal, now, trigger=verdict.trigger or "")
    state.log_line(_LOG, f"fired: trigger={verdict.trigger} — {verdict.why}")
    print(f"CLEAR_CHAIN_SPAWNED trigger={verdict.trigger}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
