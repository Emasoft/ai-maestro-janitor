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
  2. COMPOSE — the handoff is built from on-disk facts (TRDD STATE blocks, git log, the findings
     ledger). No model, no tokens. `--llm-ext` upgrades the prose; the template is what ships.
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
import re
import subprocess
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import external_clear as ec  # noqa: E402
import state  # noqa: E402

_LOG = "external-clear"
# The columns whose cards are genuinely IN FLIGHT. `todo`/`backburner` are queued, not in
# progress, so listing them would bury the one card the next session should actually resume.
_WORK_COLUMNS = ("dev", "testing", "ai_review", "human_review")
_MAX_CARDS = 6
_MAX_COMMITS = 5
_MAX_FINDINGS = 4
_TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
_FRONTMATTER_BYTES = 4096


def _run_git(root: Path, *args: str) -> str:
    """Best-effort `git` in `root`; "" on any failure. Never raises — a repo-less project must
    still get a handoff, just one without the commit section.

    Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes .git/index.lock and
    collides with a concurrent `publish.py` commit (janitor#245).
    """
    try:
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=15,
            env=git_env,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


def _gather_cards(root: Path) -> list[tuple[str, str, str]]:
    """(id, column, title) for every in-flight card, both scopes, newest-updated first."""
    try:
        import trdd_common  # noqa: PLC0415 - lazy: a project without TRDDs pays nothing
    except ImportError:
        return []
    rows: list[tuple[float, str, str, str]] = []
    try:
        files = trdd_common.trdd_files("tasks", str(root))
    except Exception:  # noqa: BLE001 - a malformed design tree must not block the clear
        return []
    for _scope, path in files:
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:_FRONTMATTER_BYTES]
            _status, column = trdd_common.parse_state_text(head)
        except (OSError, ValueError):
            continue
        if column not in _WORK_COLUMNS:
            continue
        uid = trdd_common.extract_uid(path.name)
        if not uid:
            continue
        m = _TITLE_RE.search(head)
        title = (m.group(1) if m else "").strip().strip('"')
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        rows.append((mtime, uid.upper(), column, title))
    rows.sort(reverse=True)
    return [(uid, col, title) for _mt, uid, col, title in rows[:_MAX_CARDS]]


def _gather_commits(root: Path) -> list[tuple[str, str]]:
    """(short-sha, subject) for the most recent commits. The subjects are the WHY index — the
    handoff links to them rather than restating what changed."""
    out = _run_git(root, "log", f"-{_MAX_COMMITS}", "--format=%h %s")
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        sha, _, subject = line.partition(" ")
        if sha and subject:
            rows.append((sha, subject.strip()))
    return rows


def _gather_findings(root: Path) -> list[str]:
    """Unread findings, READ-ONLY. The cursor is deliberately NOT advanced: surfacing a finding
    in a handoff is not the same as a human having seen it, and advancing here would make the
    fresh session's own SessionStart injection silently skip them."""
    try:
        import findings_ledger  # noqa: PLC0415

        lines, _total = findings_ledger.unread_entries(str(root), cap=_MAX_FINDINGS)
    except Exception:  # noqa: BLE001 - the ledger is an extra, never a precondition
        return []
    return [state.sanitize_for_drift_line(line) for line in lines]


def _memory_dir(root: Path) -> str:
    rel = Path(".claude") / "project" / "memory"
    return str(rel) if (root / rel).is_dir() else ""


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
    """Build the handoff and validate it against the concise-but-exhaustive contract.

    Returns (text, reasons) — `reasons` empty means it passed. A failing handoff is REPORTED,
    not silently shipped: `/clear` is unrecoverable and this text is the only thing that
    survives it, so a contract breach here is the last moment anyone can notice.
    """
    import clear_trigger  # noqa: PLC0415

    inputs = ec.HandoffInputs(
        cards=_gather_cards(root),
        commits=_gather_commits(root),
        findings=_gather_findings(root),
        memory_dir=_memory_dir(root),
        trigger=verdict.trigger,
        idle_seconds=facts.get("idle_seconds"),
        context_tokens=facts.get("context_tokens"),
    )
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
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
            state.log_line(_LOG, f"handoff degraded to template: {got.outcome} — {got.detail}")
    text = ec.compose_handoff(
        inputs,
        now_iso=now_iso,
        summary=summary,
        tail=ec.recent_messages(transcript) if transcript else (),
    )
    _ok, reasons = clear_trigger.check_handoff_concise(text)
    return text, reasons


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
            "read .janitor/state/agent-handoff.md FIRST (link-only handoff, auto-composed "
            "with no model turn — follow its wikimem/TRDD links via memgrep recall on "
            "demand), then resume your prior in-flight task."
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
    if reasons:
        print(f"HANDOFF_NOT_CONCISE {','.join(reasons)}")
        state.log_line(_LOG, f"handoff violates the concision contract: {reasons}")

    if args.dry_run:
        print(f"DRY_RUN would clear via {terminal.get('kind')} "
              f"({len(text.encode('utf-8'))}B handoff)")
        print("--- handoff ---")
        print(text)
        return 0

    state.atomic_write(sd / "agent-handoff.md", text)
    _fire(root, sd, terminal, now, trigger=verdict.trigger or "")
    state.log_line(_LOG, f"fired: trigger={verdict.trigger} — {verdict.why}")
    print(f"CLEAR_CHAIN_SPAWNED trigger={verdict.trigger}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
