#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing script for /janitor-handoff-and-clear (TRDD-Z582IKIR P1).

The `/clear` continuity primitive: a `/clear` resets the session to base-context
with NO residual compaction summary (cheaper in steady state than `/compact`),
but it is UNRECOVERABLE — no scrollback, no summary — and it DESTROYS the
session-scoped heartbeat cron (per code.claude.com/docs/en/scheduled-tasks; only
`--resume`/`--continue` restores it, not `/clear`). So the whole trick is: persist
everything the next session needs to a FILE first, fire `/clear`, then bootstrap
the fresh session to RE-ARM the cron and RESUME from that file.

This script is the analogue of compact_trigger.py, with two structural differences
that `/clear` forces:

  1. It writes the resume state SYNCHRONOUSLY, before firing anything — the
     `resume-directive.txt` pointer AND the `resume-after-clear.flag` (+ `.ts`)
     marker that dispatch.py's `_phase_clear_resume` consumes. There is no
     PostClear hook (unlike the PostCompact hook that writes the compact flag), so
     this script IS the writer, and it MUST finish before `/clear` runs because
     `/clear` is unrecoverable — there is no second chance to record state after.

  2. It injects a TWO-PHASE keystroke sequence into THIS session's own pane:
     phase A types `/clear`; then, after a settle delay long enough for the fresh
     session + its SessionStart hooks to come up, phase B types the BOOTSTRAP —
     `/janitor-arm` (re-arm the cron `/clear` just destroyed) then `/janitor-resume`
     (run the dispatcher stub, which re-enters `_phase_clear_resume` → emits
     `[janitor-resume]` + the handoff directive → the session resumes).

The bootstrap keystroke is LOAD-BEARING, not optional (TRDD-Z582IKIR "step-3→4
bootstrap gap"): a SessionStart hook is a SHELL script and CANNOT call CronCreate
(a MODEL tool) — it only injects context. On a genuinely unattended machine there
is no human to trigger the model turn that would process that injected re-arm
nudge, so the janitor types the re-arm command into its own pane exactly as it
already does for /compact and /reload-plugins.

Both phases are SOFT (no ESC): the invoking skill fires this script and ENDS ITS
TURN, so the enqueued `/clear` runs at that turn boundary, then the bootstrap lands
on the fresh idle prompt. The presence gate is checked ONCE up front so the two
phases are atomic — we never fire `/clear` and then refuse the re-arm because the
user happened to appear in the settle window.

Outside an automatable terminal ($ITERM_SESSION_ID unset and not tmux) self-trigger
isn't available: the script prints NO_ITERM and the skill asks the user to run
`/clear` then `/janitor-arm` manually (the resume state is still recorded, so a
manual clear + re-arm still auto-resumes).
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
# `user_intent` is deliberately NOT imported here any more: the presence CANCEL it backed is
# gone, and the deferral that replaced it lives in terminal_trigger (which consults user_intent
# itself). Re-adding the import here would be the first step back toward a local cancel.
import handoff_files  # noqa: E402
import state  # noqa: E402
import terminal_trigger  # noqa: E402

# The slash-commands the phases type into the pane. FIXED module constants (never
# user/env input) — `terminal_trigger.send_self_command` is the sole sender and it
# validates any pane/session id itself before interpolating anything.
CLEAR_CMD = "/clear"
ARM_CMD = "/janitor-arm"
RESUME_CMD = "/janitor-resume"
# The bootstrap re-arms the cron `/clear` destroyed, THEN resumes from the handoff.
# Ordered: arm first (the cron must exist), resume second (it runs the dispatcher
# stub which consumes the resume-after-clear.flag). Both enqueue back-to-back.
_BOOTSTRAP_CMDS: tuple[str, ...] = (ARM_CMD, RESUME_CMD)
# Public alias: other triggers compose their own bootstrap on top of this pair via
# `spawn_shrink_chain`. Exported so they never open-code (ARM, RESUME) and silently
# drift if the bootstrap ever gains a third step.
BOOTSTRAP_CMDS: tuple[str, ...] = _BOOTSTRAP_CMDS
# Every command this script types, in order. No longer passed to `injection_allowed` (the
# presence cancel is gone) but kept as the one place the full set is named — the `clear` verb
# in `user_intent._VERB_COMMANDS` exists to cover `/clear` from here.
_ALL_CMDS: tuple[str, ...] = (CLEAR_CMD, *_BOOTSTRAP_CMDS)
__all__ = [
    "BOOTSTRAP_CMDS",
    "CLEAR_CMD",
    "_ALL_CMDS",
    "check_handoff_concise",
    "plan_clear",
    "spawn_shrink_chain",
]

# INPUT-SAFETY (wikimem `claude-code-esc-input-semantics`, id:ATOM-ESC-REWIND): every
# phase here is SOFT — a text-then-Enter send with NO leading ESC (esc_first=False in
# _fire_phase) — and we NEVER send a bare Enter or Ctrl+C. WHY it is
# safe despite "never type text+Enter into an unverified pane": the invoking skill ENDS
# ITS TURN right after this fires, so the enqueued `/clear` lands on an IDLE prompt at
# the turn boundary (a slash-command typed into a BUSY pane merely buffers/enqueues — it
# never executes mid-turn), and the bootstrap is delayed by --clear-settle so it lands on
# the FRESH session's idle prompt. Ctrl+C is forbidden (its 2nd press EXITS Claude Code)
# and no ESC is sent (the one destructive keystroke is an Enter into an open rewind menu,
# which only an EMPTY-prompt double-ESC could open — and we send neither).

# Concision contract for the link-only handoff (owner HARD REQUIREMENT, TRDD-Z582IKIR
# P1: "as CONCISE AS POSSIBLE" / "exhaustive COVERAGE by REFERENCE, never by
# inclusion"). A handoff that violates these is not a fatal error — /clear still
# proceeds — but it is WARNED loudly on stderr, because a bloated handoff defeats the
# entire point of preferring /clear over /compact.
_HANDOFF_MAX_BYTES = 4096  # "a few hundred bytes to low KB", never the tens-of-KB a compaction summary runs
_HANDOFF_MAX_FENCE_LINES = 8  # a longer fenced block == inlined payload the handoff must LINK to instead
# A reference is any pointer into the durable payload store: a wikimem wikilink, a
# wikimem atom id, a TRDD id, a memgrep recall hint, or a GitHub issue number. An
# exhaustive-by-reference handoff MUST carry at least one — a handoff with none has
# nothing to recall from, so it is concise but no longer exhaustive.
_REFERENCE_RE = re.compile(r"\[\[|ATOM-[A-Z0-9]|TRDD-[A-Za-z0-9]|memgrep|#\d+")



def plan_clear() -> tuple[list[str], list[str]]:
    """The two keystroke phases, in order: (phase-A `/clear`, phase-B bootstrap).

    Pure — the single source of truth for what gets typed, so tests and the dry-run
    plan agree with what really fires. Phase B re-arms AND resumes, in that order.
    """
    return [CLEAR_CMD], list(_BOOTSTRAP_CMDS)


def check_handoff_concise(
    text: str,
    *,
    max_bytes: int = _HANDOFF_MAX_BYTES,
    max_fence_lines: int = _HANDOFF_MAX_FENCE_LINES,
) -> tuple[bool, list[str]]:
    """Validate the link-only handoff against the concise-but-exhaustive contract.

    PURE. Returns (ok, reasons). A failing handoff is not fatal (the skill still
    clears), but the reasons are surfaced so the concision contract is enforced at
    fire time, not just hoped for. Three checks, each a distinct owner requirement:
      - `too-large`      — over the byte budget (not concise).
      - `no-references`  — carries no pointer into the payload store, so it cannot
                           be exhaustive-by-reference (it links to nothing).
      - `inlined-block`  — a fenced block longer than `max_fence_lines`, i.e. a big
                           chunk of content INLINED instead of replaced with a link.

    A COMPOSER-AUTHORED handoff is exempt from the first TWO, and NOT from the third
    (TRDD-L46IG69Y). `too-large` and `no-references` restate the link-only DESIGN — concise, and
    exhaustive by REFERENCE — and an `llm-ext` prose summary makes the opposite trade on purpose,
    exhaustive by INCLUSION. Measured 2026-09-04 over every composer handoff this host had
    (n=5): 23.8-40.5 KB, so 5.8-9.9x the budget — `too-large` fired on EVERY run, and a warning
    that always fires trains its reader to ignore it. References matched in 5/5 (6-32 hits), but
    only INCIDENTALLY (a summary reproduces ids the session discussed), so leaving that check
    live would let it fire on the summary that happens to name none — intermittent, which looks
    like signal and is worse than always.

    `inlined-block` STAYS LIVE for both producers. Its rationale is link-only but its PREDICATE
    is "a fenced block over `max_fence_lines`", i.e. you pasted a big blob — which stays true of a prose
    summary, and is the one shape where composer output is bloated beyond its own nature
    (llm-ext quoting a source file, not summarizing it). It fired 0/5, so keeping it costs no
    noise, and a check that has earned its keep by staying quiet is not one to drop.

    The fatal ABSENCE check in `main()` is untouched: a failed compose writes nothing, so a
    clear with no handoff is still REFUSED.
    """
    reasons: list[str] = []
    # ONE block, not two guarded lines: membership in the exemption is structural, so a link-only
    # check added inside it inherits the exemption and one added outside is a visible choice.
    if not text.lstrip().startswith(handoff_files.COMPOSED_MARKER):
        if len(text.encode("utf-8")) > max_bytes:
            reasons.append("too-large")
        if not _REFERENCE_RE.search(text):
            reasons.append("no-references")
    # Longest run of lines inside any ``` fenced block — a big inlined blob is exactly
    # the "pasting the full reasoning inline" the owner forbids.
    in_fence = False
    run = 0
    longest = 0
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            if in_fence:
                longest = max(longest, run)
                run = 0
            in_fence = not in_fence
            continue
        if in_fence:
            run += 1
    longest = max(longest, run)
    if longest > max_fence_lines:
        reasons.append("inlined-block")
    return (not reasons, reasons)


def _project_root() -> Path:
    """Mirror lib.state._resolve_project_root so the state files land exactly where
    dispatch.py reads them: CLAUDE_PROJECT_DIR -> git toplevel -> cwd."""
    explicit = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if explicit:
        return Path(explicit)
    try:
        # Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes .git/index.lock
        # and collides with a concurrent `publish.py` commit (janitor#245).
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            env=git_env,
        )
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()

def session_transcript_path() -> Path | None:
    """THIS session's own transcript, or None when the session is unknown.

    Owner directive (post-2f463d3b review): a `/reload-plugins` shrink types `/clear` and
    destroys the session's context exactly like a compaction does, but `reload_trigger.py` /
    `reload_skills_trigger.py` never named a `transcript_path`, so the fresh session's
    `on-session-start-post-clear-compact.py` hook had only a pointer to work from instead of
    the actual pre-clear transcript to Jev-compact. Mirrors `dispatch.py::_session_transcript_path`
    (do not re-derive the slug rule -- `memory_scopes.project_slug` is the ONE shared rule) but
    lives here, not there, because BOTH reload triggers already import this module and neither
    owns a copy of the slug logic.

    `CLAUDE_CODE_SESSION_ID` is set by Claude Code in the session's own process environment and
    inherited by any subprocess a Bash-tool call spawns -- both reload triggers run exactly that
    way (module docstrings: "backing script for /janitor-reload-plugins|-skills", invoked from
    the session's own pane). A cron-fired dispatch run has no such variable (TRDD-6P0KUSO9), so
    like `dispatch.py`'s own version this fails open to None rather than guessing "the project's
    newest transcript" -- a wrong transcript threaded into the sidecar would Jev-compact the
    WRONG session's context into this one's resume.
    """
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if not session_id:
        return None
    import memory_scopes  # noqa: PLC0415 -- lazy; scripts/lib is on path, same pattern as the file's other lib imports

    path = (
        Path.home() / ".claude" / "projects"
        / memory_scopes.project_slug(str(_project_root())) / f"{session_id}.jsonl"
    )
    return path if path.is_file() else None


def _atomic_write(target: Path, value: str) -> None:
    """Write atomically by rename (tmp + os.replace), so a crash mid-write can never
    leave dispatch reading a half-written resume marker before /clear wipes context."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    tmp.write_text(value, encoding="utf-8")
    os.replace(tmp, target)


def _write_directive(directive: str) -> Path:
    """Persist the one-shot resume pointer (shared with the compact path)."""
    target = _project_root() / ".janitor" / "state" / "resume-directive.txt"
    _atomic_write(target, directive + "\n")
    return target


def _write_clear_marker(directive: str) -> Path:
    """Persist the pre-clear resume marker dispatch.py `_phase_clear_resume` consumes.

    Writes the `.ts` sidecar BEFORE the `.flag` (same ordering rule as
    post-compact-resume.py): the flag is the trigger, so a reader that races in
    between sees "flag+ts present" or "neither present", never "flag without ts"
    (which would misreport the age). There is no PostClear hook, so — unlike the
    compact path where the hook writes the flag — this script is the writer, and it
    runs BEFORE /clear because /clear is unrecoverable.
    """
    sd = _project_root() / ".janitor" / "state"
    _atomic_write(sd / "resume-after-clear.ts", str(int(time.time())))
    target = sd / "resume-after-clear.flag"
    _atomic_write(target, directive)
    return target


def _read_handoff() -> str | None:
    """The most recent handoff, or None when none was written.

    TRDD-5RXBI65T — the NEWEST FILE, deliberately, not the newest group. The two callers ask
    "does a handoff exist, and is it concise", and `check_handoff_concise` judges ONE artifact:
    its budget is what a reader must swallow per handoff, and each file is one handoff. Judging a
    concatenated group would make a session's SECOND handoff trip a contract neither file
    violates — and would force editing the ratified `_HANDOFF_MAX_BYTES` / `_REFERENCE_RE`
    constants, which per-file leaves untouched.
    """
    sd = _project_root() / ".janitor" / "state"
    newest = handoff_files.newest(sd)
    if newest is None:
        return None
    try:
        return newest.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None


# --- the CHAINED child (TRDD-0BVF4K7E phase 2) ------------------------------
#
# Replaces the two independent blind timers. Everything below runs in a DETACHED child,
# because the keystrokes must land after THIS turn ends — but unlike the old design the child
# now verifies each command before submitting it, and phase B chains on phase A's verified
# submit instead of a wall clock.

_GATE_STAMP = "clear-observed.ts"

# Item 1 fix (card 5 orchestrator review): the post-Enter gate `run_chained_inject`
# (scripts/lib/terminal_trigger.py) waits on before this chain persists
# `resume-after-clear.flag` -- duplicated here (not imported; nothing else in this file
# imports terminal_trigger at module scope) because the call below never passes
# `gate_timeout_s`, so this IS the value actually in effect.
_POST_ENTER_GATE_TIMEOUT_S = 180.0  # == terminal_trigger.run_chained_inject gate_timeout_s default, same pin
_POST_ENTER_GATE_MARGIN_S = 600.0  # 10 min slack for a merely-slow (not stuck) gate

# Refinement (c), orchestrator review: same pin as `detectors/model-fallback.py`'s
# `_SCOPED_HIGH` / `_ACCOUNT_HEADROOM` -- duplicated here (module-level, not imported)
# because that detector module is not on the chain child's `sys.path` (only `scripts/lib`
# is) -- so `_pane_policy_conflict_ok`'s no-headroom veto agrees with the daemon's own
# model-fallback decision instead of drifting from it. Module-level (not local to
# `_run_chain_payload`) so a test can assert equality against the originals directly.
_NO_HEADROOM_SCOPED_HIGH = 90.0
_NO_HEADROOM_ACCOUNT_HEADROOM = 90.0

# The chain's /clear injection ceiling. NOT the default 30 s inject give-up: the chain now
# carries a `still_wanted` cache probe (owner directive 2026-08-16) that cancels the moment
# agentlensPro reports the cache WARM, so the CONDITION is the terminator and this clock is
# only the backstop for the probe's "unknown" answers. An hour of 8 s retries against a busy
# pane with a still-cold cache is exactly the patience the feature needs — the give-up at 30 s
# is what left this session un-shrunk for 4+ hours on 2026-08-16.
_CLEAR_CHAIN_GIVEUP_S = 3600.0
_CHAIN_LOCK = "clear-chain.lock"
# Addendum, TRDD-11GAS4LC / issue #306: `inject_until_sent` can DEFER the actual Enter on
# /clear for minutes while the pane is busy, so the gates the Stop hook checked at DECISION
# time (a live agent, a fresh interrupt) can go stale before the LAND. 900s mirrors
# dispatch._KEEP_GOING_AGENT_STALE_DEFAULT -- an agent whose transcript is younger than
# that is "still working" everywhere else in this codebase; using a different number here
# would let dispatch call an agent live while this chain called the same one dead.
_AGENT_LIVE_STALE_S = 900


def came_back_since(verdict_ts: int, idle_s: int, now: int) -> bool:
    """PURE. Did a SUBSTANTIVE turn land after the clear was decided?

    `idle_s` is heartbeat- AND daemon-interrupt-excluding (`fleet_scan.human_activity_age`,
    TRDD-L32WC0H7 / F6), so `now - idle_s` is the moment of the last real HUMAN turn. Strictly
    greater, not `>=`: a turn in the SAME second as the verdict is what the verdict itself was
    computed from, and `>=` would cancel every chain the instant it was fired.

    A false `True` costs one skipped shrink; a false `False` clears a live context with no undo.
    """
    if verdict_ts <= 0:
        return False
    return (now - idle_s) > verdict_ts


def _gate_baseline() -> int:
    """The `clear-observed.ts` value BEFORE we type /clear. The chain waits for STRICTLY
    greater, so a stamp from an earlier clear can never be mistaken for this one."""
    try:
        return int((_project_root() / ".janitor" / "state" / _GATE_STAMP).read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


def _run_chain_payload(payload_b64: str) -> int:
    """CHILD role. Sleep out the settle delay, then run the whole verified chain under a
    singleton lock. Never raises — but ALWAYS logs its outcome.

    The log line is not decoration. The child's stdio is DEVNULL (it must outlive this turn),
    so `run_chained_inject`'s `(ok, why)` reaches nobody otherwise — a give-up would be
    indistinguishable from success, which is the silent-failure shape this project treats as a
    defect in its own right.
    """
    try:
        data = json.loads(base64.b64decode(payload_b64.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return 2
    time.sleep(max(0.0, float(data.get("delay", 0.0))))

    sd = Path(data["state_dir"])
    lock_path = sd / _CHAIN_LOCK
    try:
        sd.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as exc:
        state.log_line("clear-trigger", f"chain: cannot open lock {lock_path}: {exc}")
        return 1
    try:
        # NON-BLOCKING: a second /janitor-handoff-and-clear while one is already pending must
        # NOT queue up behind it — that is how you get two /clear commands typed into one
        # session, the second landing in the fresh one.
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        state.log_line("clear-trigger", "chain: another clear chain is already pending — skipping")
        os.close(lock_fd)
        return 0

    directive = data["directive"]
    # Epoch seconds at which the firing verdict was REACHED. 0/absent disables the
    # came-back cancel rather than faking a reference point — a wrong pin would either
    # cancel every chain or none, and both failures are silent.
    verdict_ts = int(data.get("verdict_ts") or 0)
    persisted = {"done": False}

    # Refinement (b), orchestrator review (TRDD-RAEGS1D5 card 5): `still_wanted` is re-asked
    # roughly every 8s for up to an hour (`_CLEAR_CHAIN_GIVEUP_S`) -- an un-rate-limited log
    # line per veto could write ~450 lines for one stuck pane. One line per DISTINCT reason
    # per `_VETO_LOG_INTERVAL_S`, keyed on the reason so a wedge that clears and later
    # recurs still gets a fresh line.
    _last_veto_log: dict[str, float] = {}
    _VETO_LOG_INTERVAL_S = 60.0

    def _log_veto_once(reason: str, detail: str) -> None:
        now_m = time.monotonic()
        last = _last_veto_log.get(reason, 0.0)
        if now_m - last >= _VETO_LOG_INTERVAL_S:
            _last_veto_log[reason] = now_m
            state.log_line("clear-trigger", detail)

    def _persist_resume_state() -> None:
        # Called by inject_until_sent IMMEDIATELY before Enter on /clear, and nowhere else.
        # main() used to write these before firing; once the child can defer for minutes, that
        # ordering resurrects issue #105 — a give-up would leave resume-after-clear.flag for a
        # /clear that never happened, and the next heartbeat would consume it.
        #
        # Self-veto ordering fix (TRDD-RAEGS1D5 addendum, post-2f463d3b review): flipped BEFORE
        # the writes, not after. `_recovery_ok` below trusts `persisted["done"]` to mean "this
        # chain instance is the one that just wrote resume-after-clear.flag, so don't treat that
        # flag as someone else's unconsumed recovery." If a write raised partway (flag landed on
        # disk, exception before the old post-write flip), `persisted["done"]` would stay False
        # forever and the chain could veto its OWN later re-checks over its own flag. Flipping
        # first means a partial write still counts as "mine" — the narrower failure (treating an
        # aborted write as done) is strictly safer than the self-veto it replaces.
        persisted["done"] = True
        _write_directive(directive)
        _write_clear_marker(directive)
        # TRDD-RAEGS1D5 card 5: when this chain payload NAMES a transcript (every automatic
        # trigger now threads one through — external_handoff_clear, the idle-clear nudge,
        # spawn_shrink_chain), persist a PER-PANE sidecar the fresh session's dedicated hook
        # (on-session-start-post-clear-compact.py) consumes to Jev-compact THAT transcript,
        # never "whichever handoff happens to be newest" (a stale foreign handoff getting
        # injected as if it were this clear's own account, the TRDD-5RXBI65T failure shape).
        # Keyed by PANE, not session or project: two panes of the same project can each have
        # their own clear pending at once and must not cross-contaminate each other's sidecar
        # — the pane is "the one the chain types into" (`data["terminal"]`), and the fresh
        # session's hook resolves the SAME id from its own env via
        # `state.pane_key_from_terminal(terminal_trigger.self_terminal(env))` (both sides share
        # the sanitisation via `state.pane_key_from_terminal`). No pane id
        # (an unresolvable terminal) writes no sidecar — that chain never reaches this
        # verified child anyway (the legacy blind-send fallback in main() never calls this).
        transcript_path = str(data.get("transcript_path") or "").strip()
        if transcript_path:
            try:
                pane_key = state.pane_key_from_terminal(data.get("terminal"))
                if pane_key:
                    sidecar = sd / f"resume-after-clear.{pane_key}.transcript"
                    _atomic_write(sidecar, f"{transcript_path}\n{int(time.time())}\n")
            except Exception as exc:  # noqa: BLE001 — the sidecar is a nice-to-have; never block /clear
                # Review finding (TRDD-RAEGS1D5 card 5): a bare `pass` here would make a
                # SYSTEMATIC failure (e.g. a future `pane_key_from_terminal` regression, a full
                # disk) indistinguishable from "no pane id" — silent forever, with nothing to
                # diagnose why the feature stopped firing. Logging costs nothing and never
                # risks the /clear itself (still never re-raised).
                state.log_line("clear-trigger", f"per-pane sidecar write failed: {exc!r}")
        # TRDD-11GAS4LC addendum: log the context size at the exact moment /clear lands
        # (not at the Stop hook's earlier decision) — the two can be minutes apart while
        # this chain defers on a busy pane, and without this the miss between "decided"
        # and "landed" is unmeasurable.
        try:
            import token_meter  # noqa: PLC0415 — lazy; the chain child has scripts/lib on path

            transcript = os.environ.get("JANITOR_TRANSCRIPT_PATH") or ""
            tokens = token_meter.latest_context_size(transcript) if transcript else None
            if tokens is not None:
                window = token_meter.default_window()
                pct = int(tokens * 100 / window) if window else 0
                state.log_line("clear-trigger", f"clear landing at {tokens} tokens ({pct}% of window)")
        except Exception:  # noqa: BLE001 — telemetry must never block the verified Enter
            pass
        # TRDD-RAEGS1D5 card 5 regression fix (post-2f463d3b review): stamped HERE, not by the
        # parent `spawn_shrink_chain` at spawn time — this closure runs only immediately before
        # the verified Enter, so a chain that self-cancels earlier (recovery pending, warm
        # cache, user came back, busy-pane giveup) never reaches this line and never spends the
        # cooldown window on a `/clear` that didn't land.
        #
        # Item 6 (orchestrator review): `.get(...)`, not `["count_toward_cooldown"]` --
        # `external_handoff_clear.py::_fire` builds a payload for this SAME child without
        # this key at all (it stamps its own way, at spawn, per the advisor's D12
        # spawn-storm reasoning), so a missing key must read as "don't stamp", never as a
        # KeyError. A truly new caller that hand-built a payload and forgot the key would
        # silently not stamp either -- `spawn_shrink_chain` is the one sanctioned way to
        # reach this child for every caller except `_fire`, so that is a narrow, documented,
        # pre-existing contract, not a gap this task introduced.
        if data.get("count_toward_cooldown"):
            try:
                import cold_cache_compact  # noqa: PLC0415 -- lazy; scripts/lib is on path

                cold_cache_compact.mark_clear_fired(sd, now=int(time.time()))
            except Exception:  # noqa: BLE001 — the stamp is best-effort; never block /clear
                pass

    def _clear_still_wanted() -> tuple[bool, str]:
        # Owner directive 2026-08-16: while the pane is busy (the user is typing), do NOT give
        # up on a 30 s clock — keep retrying at the 8 s cadence, but RE-ASK agentlensPro every
        # round whether this project's cache is still expired, and CANCEL the /clear the moment
        # it reports WARM: the user's own turn rebuilt the cache, so clearing now would destroy
        # a LIVE context for nothing.
        #
        # ONLY a definite False cancels. True (still expired) keeps waiting — that IS the
        # window the clear exists for. None (probe absent / unable) ALSO keeps waiting: the
        # chain was fired on a verdict that was valid when made, and cancelling on ignorance is
        # how this lever has gone silently dead before (external_clear's own log records the
        # "cache state unknown — not clearing" epoch). The safety ceiling below bounds the
        # None case; the warm case self-cancels here.
        try:
            import external_clear  # noqa: PLC0415 — lazy; the chain child has scripts/lib on path

            verdict = external_clear.cache_certainly_expired(
                os.environ.get("CLAUDE_PROJECT_DIR") or None
            )
        except Exception:  # noqa: BLE001 — a probe fault must never kill a pending clear
            return True, "cache probe unavailable — continuing"
        if verdict is False:
            return False, "cache is WARM again — a /clear now would destroy a live context"
        return True, "cache still expired" if verdict is True else "cache state unknown — continuing"

    def _user_came_back() -> tuple[bool, str]:
        # The SECOND cancel, and the one that applies to EVERY trigger. A cancel condition must
        # falsify the TRIGGER'S OWN PREMISE, and every rule that fires this chain rests on "no
        # real work is happening here". A substantive turn AFTER the verdict falsifies that
        # exactly — for `long-idle` it is the only thing that does, since a warm cache never
        # contradicted idleness (that mistake vetoed 6 of 6 fires on 2026-08-16).
        #
        # The ceiling below is a TIMEOUT, not protection: it bounds how long a wrong verdict may
        # wait, but it cannot notice the verdict BECOMING wrong. Only this can, and /clear has no
        # undo — no scrollback, no summary — so the loss it prevents is a user's whole context.
        #
        # Pinned to the VERDICT TIMESTAMP, never to "is the pane busy right now". Busy-now is
        # what the injection deferral already handles; re-asking it here would add a second veto
        # with the same unreachability disease this hook just cured. `human_activity_age`
        # (TRDD-L32WC0H7 / F6 — NOT `transcript_activity`, which is heartbeat-INCLUDING per
        # `fleet_scan.py`'s own docstring, so it reads EVERY cron fire as "the user is back" and
        # cancels a pending /clear regardless of whether the session is idle) also excludes the
        # daemon's own `esc_nudge` interrupt record (`fleet_scan._is_interrupt_record`) — so a
        # recovery nudge on a stalled session no longer masquerades as the user returning.
        if not verdict_ts:
            return True, "no verdict timestamp — continuing"
        try:
            import fleet_scan  # noqa: PLC0415 — lazy; the chain child has scripts/lib on path

            idle_s = fleet_scan.human_activity_age(
                os.environ.get("CLAUDE_PROJECT_DIR") or ".", int(time.time())
            )
        except Exception:  # noqa: BLE001 — a probe fault must never kill a pending clear
            return True, "activity probe unavailable — continuing"
        if idle_s is None:
            # Unknown idleness never authorizes the destructive action upstream either
            # (`should_clear_externally` vetoes on it), but here the /clear is ALREADY
            # authorized, so ignorance keeps waiting rather than cancelling — same asymmetry the
            # cache probe uses, for the same reason.
            return True, "idle age unknown — continuing"
        if came_back_since(verdict_ts, idle_s, int(time.time())):
            return False, (f"the session took a real turn {idle_s}s ago, after this clear was "
                           "decided — the user is back")
        return True, f"still idle ({idle_s}s, no turn since the verdict)"

    def _agents_and_interrupt_ok() -> tuple[bool, str]:
        # THIRD cancel, TRDD-11GAS4LC addendum (issue #306 review): `_user_came_back` only
        # catches a COMPLETED human turn — a background agent spawned AFTER the verdict (a
        # review-gate fork, a new lean-worker) is still running with no turn to detect, and a
        # bare Esc/Ctrl-C interrupt with no new turn yet trips neither. Both must still be
        # able to stop a /clear that is minutes from landing while `inject_until_sent` defers
        # on a busy pane. Fail-open on any probe fault, same asymmetry as the two cancels
        # above: an unmeasurable state keeps waiting, it never authorizes a cancel.
        try:
            import pending_agents  # noqa: PLC0415 — lazy; the chain child has scripts/lib on path

            now = int(time.time())
            entries = pending_agents.load_pending(now)
            live = [e for e in entries if pending_agents.agent_is_live(e, now, _AGENT_LIVE_STALE_S)]
            if live:
                return False, f"{len(live)} agent(s) live"
        except Exception:  # noqa: BLE001
            pass
        try:
            import user_intent  # noqa: PLC0415

            secs = user_intent.recently_interrupted(
                os.environ.get("CLAUDE_PROJECT_DIR") or ".",
                transcript_path=os.environ.get("JANITOR_TRANSCRIPT_PATH") or None,
            )
            if secs is not None:
                return False, f"interrupted {int(secs)}s ago — within the cooldown"
        except Exception:  # noqa: BLE001
            pass
        return True, "no live agents, no recent interrupt"

    def _recovery_ok() -> tuple[bool, str]:
        # FOURTH cancel, TRDD-RAEGS1D5 card 5: a rate-limit / API-error resume, or a
        # compact-resume, still unconsumed on disk means dispatch.py's own
        # `_phase_compact_resume` / a rate-limit resume-wake has NOT yet replayed the
        # interrupted task to the model -- a `/clear` right now would destroy the context
        # that replay is about to need before it is ever read. Runs for EVERY trigger, same
        # as `_agents_and_interrupt_ok`: the recovery window is a property of the SESSION,
        # not of why this particular chain fired.
        #
        # `resume-after-clear.flag` is EXCLUDED from the check, but ONLY when THIS CHAIN
        # INSTANCE is the one that wrote it (`persisted["done"]`, flipped by
        # `_persist_resume_state` above -- the same closure scope, so it can only be True
        # after THIS process actually ran that write). A blind file-existence check was
        # reviewed and rejected: `resume-after-clear.flag` has one path per state dir, not
        # one per chain instance, so an existence-only check cannot tell "the flag I am about
        # to / just wrote" from a STALE flag orphaned by a crashed prior chain, or from
        # another PANE's still-pending chain (the state dir is per-project, not per-pane) --
        # either would wrongly forgive a genuinely unconsumed recovery and let `/clear` fire
        # over it. `persisted["done"]` has neither failure mode: it is this process's own
        # record of its own write, so a flag that predates it is never mistaken for one.
        try:
            import external_clear  # noqa: PLC0415 — lazy; the chain child has scripts/lib on path

            if not external_clear.recovery_pending(sd):
                return True, "no recovery pending"
        except Exception:  # noqa: BLE001 — a probe fault must never kill a pending clear
            return True, "recovery probe unavailable — continuing"
        # Lockout fix (TRDD-RAEGS1D5 addendum, post-2f463d3b review): `recovery_pending` treats
        # any of the three flags below as pending at ANY age. `rate-limited.flag` is written on
        # EVERY turn-ending API error (`on-stop-failure.py`) and nothing synchronous consumes it
        # -- the daemon's own sweep runs on its own 24h cadence, not on this check's clock -- so
        # an orphaned flag could veto every automatic `/clear` in the project indefinitely. Bound
        # each flag by the SAME max-age dispatch.py already applies to it, so a flag stops
        # vetoing here exactly when it stops mattering to dispatch.py too.
        now_ts = int(time.time())

        def _clear_resume_armed(sd: Path) -> bool:
            # Mirrors dispatch.py:_phase_clear_resume's own ARMED check exactly (same `>=`
            # tie-break, same two files) so this veto's short bound and that phase's actual
            # consumption never disagree about which case they're in.
            written_at = state.read_int_state(sd / "resume-after-clear.ts", 0)
            observed_at = state.read_int_state(sd / _GATE_STAMP, 0)
            return observed_at > 0 and observed_at >= written_at

        def _flag_fresh(
            flag: Path, since: Path, max_age_s: float, *, recovered_after: int | None = None
        ) -> bool:
            # Item 1 fix (orchestrator review of 1b5ceec8): `read_int_state(since, now_ts)`'s
            # own default used to make a flag with NO `.ts` sidecar read as age 0 -- FRESH
            # FOREVER, an orphaned flag (no writer ever crashes before its sidecar, but a
            # much older code path or a hand-placed flag might) vetoing every automatic
            # `/clear` in the project indefinitely, the exact lockout this age-bound exists
            # to close. Falls back to the FLAG's own mtime instead, the same pattern
            # `on-session-start.py::_inject_post_clear_handoff` already uses for this exact
            # flag (`written_at or state.file_mtime(flag)`) -- a missing sidecar is common
            # (nothing writes one for a hand-dropped or historical flag), never a reason to
            # treat it as brand new.
            if not flag.is_file():
                return False
            written_at = state.read_int_state(since, 0) or state.file_mtime(flag)
            # Item 2 fix: a caller at a SUCCESSFUL Stop (on-stop-token-meter.py) knows this
            # session just ran a full turn to completion -- proof an EARLIER rate-limit/
            # API-error is no longer live, however fresh its flag still reads on its own
            # max-age clock. `recovered_after` is that Stop's own epoch, threaded through
            # `spawn_shrink_chain`'s payload; a flag written BEFORE it predates the proof and
            # stops vetoing regardless of `max_age_s`. A caller with no such evidence (the
            # idle-nudge path, `dispatch.py`) passes None here and keeps the plain age check
            # unchanged -- "the idle path keeps the veto while the flag is fresh."
            if recovered_after is not None and written_at < recovered_after:
                return False
            return (now_ts - written_at) < max_age_s

        def _env_seconds(var: str, default: float, *, hours: bool = False) -> float:
            raw = os.environ.get(var, "").strip()
            try:
                value = float(raw) if raw else default
            except ValueError:
                value = default
            return value * 3600 if hours else value

        # Item 2: ONLY the rate-limited flag gets `recovered_after` -- a compact-resume or a
        # clear-resume being unconsumed is not something a later successful Stop disproves
        # (those two are cleared by their OWN consumer, dispatch.py's resume phases, not by
        # "a turn happened"), so widening the bypass to all three would forgive a genuinely
        # pending resume the same review flagged as a real risk in the age-bound alone.
        _recovered_after_raw = data.get("recovered_after")
        recovered_after = (
            int(_recovered_after_raw) if isinstance(_recovered_after_raw, (int, float)) else None
        )

        any_fresh = (
            _flag_fresh(
                sd / state.RATE_LIMITED_FLAG, sd / "rate-limited-since.ts",
                _env_seconds("CLAUDE_PLUGIN_OPTION_RATE_LIMIT_FLAG_MAX_AGE_HOURS", 24, hours=True),
                recovered_after=recovered_after,
            )
            or _flag_fresh(
                sd / "resume-after-compact.flag", sd / "resume-after-compact.ts",
                _env_seconds("CLAUDE_PLUGIN_OPTION_COMPACT_RESUME_MAX_AGE_S", 86400),
            )
            or _flag_fresh(
                sd / "resume-after-clear.flag", sd / "resume-after-clear.ts",
                # Item 1 fix (card 5 orchestrator review, round 2 after a self-review found
                # the flat bound below unsafe on its own): dispatch.py's own 24h expiry
                # (CLEAR_RESUME_MAX_AGE_S, read independently at scripts/dispatch.py:1762/1788
                # and on-session-start.py:373 -- both LEFT UNCHANGED) assumes something
                # eventually consumes the flag on its own clock; an UNARMED session (no
                # heartbeat) never does, so a chain whose post-Enter gate merely TIMED OUT
                # with the clear never observed by ANY fresh session would otherwise veto
                # every automatic clear in the project for a full day.
                #
                # The short bound must NOT apply once dispatch.py's `_phase_clear_resume`
                # (scripts/dispatch.py:1681) has ARMED -- i.e. a fresh session already
                # stamped `clear-observed.ts` at/after this flag was written, exactly the
                # signal that phase itself gates on (same `>=` tie-break, same comment there:
                # "the tie means the clear landed in the same second the flag was written").
                # Once armed, dispatch's own phase will consume the flag on its NEXT
                # heartbeat -- a matter of minutes, not hours -- so keeping the full 24h
                # backstop here costs nothing and avoids a race: an ARMED-but-not-yet-
                # consumed flag (heartbeat merely hasn't fired since the observation) must
                # keep vetoing, or a second /clear from THIS chain could overwrite the
                # pending resume directive before dispatch.py ever surfaces it. The short
                # bound (gate_timeout_s + a margin) applies only to the genuinely orphaned
                # case: never armed at all.
                (
                    _POST_ENTER_GATE_TIMEOUT_S + _POST_ENTER_GATE_MARGIN_S
                    if not _clear_resume_armed(sd)
                    else _env_seconds("CLAUDE_PLUGIN_OPTION_CLEAR_RESUME_MAX_AGE_S", 86400)
                ),
            )
        )
        if not any_fresh:
            return True, "recovery flags present but all past their max age — treating as stale"
        if persisted["done"]:
            other_pending = (
                (sd / state.RATE_LIMITED_FLAG).is_file()
                or (sd / "resume-after-compact.flag").is_file()
            )
            if not other_pending:
                return True, "only this chain's own resume-after-clear.flag is pending — continuing"
        return False, "recovery pending (rate-limit/API-error or an unconsumed compact-resume)"

    def _pane_policy_conflict_ok() -> tuple[bool, str]:
        # FIFTH cancel (owner report §3.6 finding): `_CHAIN_LOCK` only serialises THIS
        # chain's own retries -- it says nothing about, and is never taken by, the daemon's
        # SEPARATE `pane_actuate.act()` keystroke loop (the model-fallback ladder,
        # `scripts/detectors/model-fallback.py` -> `Event.NO_HEADROOM`; the rotation/recovery
        # rungs, `daemon.py` -> `Event.ROTATION_LANDED` / `RECOVERY_RUNG`), so both actuators
        # CAN type into the same pane in the same window. `pane_policy`'s own module
        # docstring names ONE state that is a conflict REGARDLESS of which event fires:
        # `RETRY_WEDGE`. Every event branch `_at_wedge` handles -- rotation flush, no-headroom
        # flush-then-switch, and every caller-driven rung -- starts by flushing that wedge
        # (`pane_policy._flush_wedge`), so a wedge on screen means the daemon's next beat will
        # press ESC into this exact field: that IS "an actuator must act here", and it is the
        # one such state a text classifier can actually see. Every other pane_policy row
        # either never types (`WORKING`'s NO_HEADROOM is refused outright, `AWAITING_USER`
        # types nothing but a dismiss-only ESC) or needs off-screen state this classifier has
        # no access to (`IDLE`'s CRON_DEAD row) -- widening the veto to cover those would
        # block /clear from ever firing into a normal idle pane, which is the state it MUST
        # be able to type into.
        #
        # Refinement (a), orchestrator review: this reads the pane at the TOP of every
        # `_still_wanted()` call. `inject_until_sent` re-asks `still_wanted` on EVERY loop
        # iteration, before its own typing/verification reads -- so on the iteration that
        # finally reaches Enter, THIS is the read taken at the start of that same iteration,
        # never a value cached from an earlier 8s poll. It is not the literal read
        # `inject_until_sent` uses to verify the typed command (that happens deeper inside
        # `terminal_trigger.py`, a file this task does not own) -- the closest this module
        # can get to "nearest Enter" without touching a file outside its scope.
        try:
            text = terminal_trigger.read_pane_text(data["terminal"])
        except Exception:  # noqa: BLE001 — a probe fault must never kill a pending clear
            return True, "pane read unavailable — continuing"
        if text is None:
            return True, "pane unreadable — continuing"
        try:
            import pane_state  # noqa: PLC0415 — lazy; the chain child has scripts/lib on path

            classified = pane_state.parse(text)
        except Exception:  # noqa: BLE001 — a classification fault must never kill a pending clear
            return True, "pane classification unavailable — continuing"
        if classified.status.kind == pane_state.StatusKind.RETRY_WEDGE:
            _log_veto_once(
                "retry_wedge",
                "clear-trigger: veto — pane shows retry_wedge, pane_policy will flush/switch it",
            )
            return False, "pane shows retry_wedge — pane_policy will flush/switch it, not /clear"

        # Refinement (c), orchestrator review: RETRY_WEDGE above is the one conflict state a
        # pane TEXT read can see. `NO_HEADROOM` cannot be -- it is a usage-PERCENTAGE verdict
        # (`token_burn.model_fallback_verdict`), with no on-screen marker at all. Reused, not
        # reimplemented, from `detectors/model-fallback.py`'s own gate: `require_active=True`
        # pins this to "the window reads 100% NOW" (see that function's own docstring --
        # `require_active=False` is the rotator's early-warning caller, which decides whether
        # to rotate AHEAD of time; `require_active=True` is the model-SWITCH caller, which
        # types into a live pane and must not fire on a merely-high reading). This is the
        # SAME choice: a Stop-boundary clear must not abort on a projection that the window
        # will run out soon, only on one that already has -- otherwise every clear near a
        # window's end aborts and the harness's own ~95%-context auto-compact wins instead.
        #
        # Needs `rotator_usage.accounts_usage()`'s live-account sample (usage dict +
        # `sample_age_s`) -- the SAME probe cache the daemon's own usage-scan heartbeat keeps
        # warm. A detached chain child does not gather this itself, only reads whatever is
        # already on disk. `model_fallback_verdict` already refuses on an unproven or expired
        # snapshot (returns None), so a missing/stale input fails OPEN here too -- the same
        # asymmetry as every other cancel in this function -- and any other probe fault
        # (rotator state absent, import error) fails open identically via the bare except.
        try:
            import rotator_usage  # noqa: PLC0415 — lazy; the chain child has scripts/lib on path
            import token_burn  # noqa: PLC0415

            acct = next(
                (a for a in rotator_usage.accounts_usage() if a.get("is_live")), None
            )
            if acct is not None:
                verdict = token_burn.model_fallback_verdict(
                    acct.get("usage") or {}, int(time.time()),
                    scoped_high=_NO_HEADROOM_SCOPED_HIGH,
                    account_headroom=_NO_HEADROOM_ACCOUNT_HEADROOM,
                    snapshot_age_s=acct.get("sample_age_s"),
                    require_active=True,
                )
                if verdict is not None:
                    _log_veto_once(
                        "no_headroom",
                        f"clear-trigger: veto — model {verdict.get('model')} window exhausted "
                        f"now ({verdict.get('scoped_util')}%), pane_policy will switch it",
                    )
                    return False, (
                        f"model {verdict.get('model')} window exhausted now — pane_policy "
                        "will switch it, not /clear"
                    )
        except Exception:  # noqa: BLE001 — a probe fault must never kill a pending clear
            pass
        return True, "no actuator-conflict state on pane"

    def _still_wanted() -> tuple[bool, str]:
        """Five cancels. The activity + agent/interrupt + recovery + pane-policy-conflict
        checks run for EVERY trigger; the cache check only for a chain fired BECAUSE the cache
        was cold."""
        back_ok, back_why = _user_came_back()
        if not back_ok:
            return False, back_why
        agents_ok, agents_why = _agents_and_interrupt_ok()
        if not agents_ok:
            return False, agents_why
        recovery_ok, recovery_why = _recovery_ok()
        if not recovery_ok:
            return False, recovery_why
        conflict_ok, conflict_why = _pane_policy_conflict_ok()
        if not conflict_ok:
            return False, conflict_why
        if not data.get("cache_gated"):
            return True, back_why
        return _clear_still_wanted()

    try:
        ok, why = terminal_trigger.run_chained_inject(
            data["terminal"],
            first=data["first"],
            then=list(data["then"]),
            gate_stamp=sd / _GATE_STAMP,
            gate_baseline=int(data["gate_baseline"]),
            settle_between_s=float(data.get("settle_between_s", 0.0)),
            pre_submit_first=_persist_resume_state,
            # The condition is the terminator; the clock is only a backstop. One hour, not the
            # default 30 s: a busy pane with a still-cold cache is exactly the state worth
            # outwaiting, and the warm-cancel above fires the moment the session takes a turn.
            giveup_s=_CLEAR_CHAIN_GIVEUP_S,
            # Two cancels, deliberately different in scope (see the two closures above):
            # the ACTIVITY check runs for every trigger; the CACHE check only when `cache_gated`
            # says coldness is what fired us. A warm cache is the NORMAL state of the other
            # triggers — `long-idle` and `next-fire-misses` fire while heartbeats keep the prefix
            # warm (cadence < TTL) — so gating those on "still expired" cancelled them 100% of
            # the time: six long-idle fires in a row on 2026-08-16, the exact unreachability
            # `external_clear.next_fire_misses_cache`'s docstring warns about.
            still_wanted=_still_wanted,
        )
        state.log_line("clear-trigger", f"chain: {'OK' if ok else 'FAILED'} — {why}")
        # TRDD-11GAS4LC addendum: a distinct, greppable line for the specific case this
        # review added gates for — cancelled by `_still_wanted` at (or near) the verified
        # Enter, as opposed to a plain give-up on the giveup_s clock — so the miss rate
        # between the Stop hook's decision and the actual land is measurable on its own.
        if not ok and why.startswith("cancelled — "):
            state.log_line("clear-trigger", f"clear cancelled at land: {why[len('cancelled — '):]}")
        if not ok:
            # 2026-08-02 review finding: the old cleanup here unconditionally unlinked
            # resume-after-clear.{flag,ts} AND resume-directive.txt on ANY chain failure.
            # Both directions of that were wrong, so there is deliberately NO cleanup now:
            # - persist NEVER ran (give-up before typing) ⇒ this child wrote NOTHING, and
            #   resume-directive.txt is SHARED with the compact-resume flow — the unlink was
            #   deleting a directive another flow owned, breaking its pending resume.
            # - persist RAN ⇒ /clear was VERIFIED-submitted (pre_submit fires only
            #   immediately before the verified Enter), so a later-stage failure (the
            #   clear-observed gate timing out on slow SessionStart hooks, the bootstrap
            #   injection giving up) does NOT mean /clear didn't run — and the resume state
            #   is the cleared session's ONLY lifeline; deleting it stranded the session
            #   unarmed and unresumable. The narrow residue (Enter verified-typed yet the
            #   clear genuinely never ran) costs one benign spurious [janitor-resume] on a
            #   live session — strictly cheaper than stranding a cleared one.
            state.log_line(
                "clear-trigger",
                "chain: resume state "
                + ("KEPT (persisted at verified submit)" if persisted["done"] else "untouched (nothing was written)"),
            )
        return 0 if ok else 1
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def _spawn_chain(payload: dict, *, env: dict[str, str] | None = None) -> None:
    """Launch the chained child fully detached so this turn can end (which is what lets the
    typed /clear actually run).

    `env` overrides the child's environment ONLY. Callers that need the child to resolve a
    specific project (the external clear, whose parent is the daemon and whose cwd is
    therefore the wrong tree) pass `CLAUDE_PROJECT_DIR` HERE rather than assigning
    `os.environ[...]` in the parent. Mutating a Claude-reserved var in a long-lived parent
    clobbers it for every later plugin in the same process — CPV flags it as
    CLAUDE_RESERVED_ENV_POISON / ENV_INJECTION, and the flag is right: `state.py` already
    avoids the same trap deliberately (`set_project_dir_override` exists precisely so the
    override never touches `os.environ`). Scoping it to the child keeps the parent clean.
    """
    blob = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    # THE CHAIN CHILD IS THE PROCESS THAT SENDS APPLEEVENTS, so its interpreter must be the
    # stably-signed automation one, NEVER inherited blindly (owner directive 2026-08-16,
    # reaffirmed 2026-08-18: uv is a launcher and must not appear anywhere in the
    # iTerm-control chain). `sys.executable` is correct when the WATCHER spawned us (it
    # already runs under `automation_python_path()`), but wrong when this script is invoked
    # via `uv run` (a skill / the CLI lever): the child would inherit uv's managed CPython,
    # whose TCC grant pins a version-specific path and is silently orphaned by the next
    # `uv python` upgrade. Resolving at THIS chokepoint covers every caller at once.
    # Fallback to sys.executable when nothing resolves: a chain that runs and gets denied
    # at least logs the denial, where no chain at all is silent.
    try:
        import global_state as _gs  # noqa: PLC0415 -- lazy; scripts/lib is on path

        _automation_py = _gs.automation_python_path() or sys.executable
    except Exception:  # noqa: BLE001 -- interpreter resolution must never kill the chain
        _automation_py = sys.executable
    subprocess.Popen(  # noqa: S603 - fixed argv (this script + a base64 blob), no shell
        [_automation_py, str(Path(__file__).resolve()), "--__chain", blob],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )


def spawn_shrink_chain(
    *,
    then: Sequence[str],
    directive: str,
    delay: float = 2.0,
    settle_between_s: float = 0.0,
    transcript_path: str | None = None,
    count_toward_cooldown: bool = True,
    recovered_after: int | None = None,
) -> tuple[bool, str]:
    """Run the verified `/clear` chain with a CALLER-SUPPLIED bootstrap. Returns (spawned, why).

    The public seam for other triggers that need to SHRINK before doing something expensive —
    today `reload_trigger.py --shrink`, whose `/reload-plugins` breaks the prompt-cache prefix
    and so should land on a near-floor context rather than a 500k one (owner directive
    2026-08-14). It exists so those callers reuse THIS chain — the singleton lock, the
    `clear-observed.ts` gate, and the write-resume-state-at-verified-submit ordering — instead
    of growing a second, unverified `/clear` sender. A second sender is how you get two `/clear`
    commands typed into one session, which is the failure `_CHAIN_LOCK` exists to prevent.

    `then` REPLACES the default `[/janitor-arm, /janitor-resume]` bootstrap, so a caller that
    drops either one strands the fresh session unarmed or unresumed. Callers should build on
    `BOOTSTRAP_CMDS` rather than open-coding the pair.

    Returns (False, why) when the pane cannot be read back; the caller must then fall back to
    its own non-shrinking path rather than clear blind — an unverifiable `/clear` is the one
    unrecoverable command in this system. NOTE: "spawned" here means the CHILD was launched,
    never that `/clear` actually landed — the chain can still self-cancel (busy pane timeout,
    warm cache, user came back, recovery pending) before the verified Enter, which is exactly
    why the cooldown stamp below is NOT applied here (see `count_toward_cooldown`).

    `transcript_path` (TRDD-11GAS4LC addendum): threaded into the detached child's env as
    `JANITOR_TRANSCRIPT_PATH`, the same seam `main()`'s `--transcript-path` uses. Without it
    the child's interrupt-cooldown check (`_agents_and_interrupt_ok`) has no session to scope
    to and skips itself — a caller that knows its own transcript (a Stop hook) should pass it.

    TRDD-RAEGS1D5 card 5: ALSO carried into the chain payload's `"transcript_path"` (not just
    the env var above) — that is what `_persist_resume_state` reads to write the per-pane
    sidecar the fresh session's post-clear-compact hook consumes. `reload_trigger.py --shrink`
    is the one caller that still passes None here: a reload is not a compaction, so it must
    write no sidecar and trigger no compose (its own module docstring's contract).

    `count_toward_cooldown` (TRDD-RAEGS1D5 card 5 addendum): this is the one place every
    shrink-chain caller (idle nudge, the Stop-boundary clear, and the two reload triggers)
    funnels through, so it is the one shared site that can stamp the `cold_cache_compact`
    cooldown for all of them without duplicating the stamp call in each caller. Defaults to
    True — a caller that forgets this kwarg is far more likely to be a real automatic
    compaction (idle nudge, Stop-boundary clear) than a reload shrink, so a silent omission
    must fail toward stamping the cooldown, never toward silently bypassing it. The two
    reload triggers (`reload_trigger.py`, `reload_skills_trigger.py`) pass
    `count_toward_cooldown=False` explicitly — a reload-shrink is not a compaction the user
    is waiting out, and stamping it would block a REAL clear from firing for the rest of the
    cooldown window over a `/reload-plugins` that changed nothing about context size.

    `recovered_after` (TRDD-RAEGS1D5 card 5, orchestrator review item 2): the epoch of a
    SUCCESSFUL Stop this call is racing against, carried into the payload so the child's
    `_recovery_ok` can ignore a `rate-limited.flag` written BEFORE that success -- a
    successful Stop already proves any earlier rate-limit/API-error is no longer live,
    however fresh the flag still reads on its own max-age clock. `on-stop-token-meter.py`
    passes its own Stop's `int(time.time())`; every other caller (the idle nudge, the two
    reload triggers) leaves it None and keeps the plain age check unchanged.

    Review finding (post-2f463d3b): the stamp used to fire HERE, right after the child was
    spawned — before anything is verified. A chain that then self-cancels (recovery pending,
    warm cache, user came back, busy-pane giveup) still spent the cooldown window with no
    `/clear` ever landing, locking a REAL clear out until the window expired while the
    harness's own ~95%-context auto-compact wins instead. The flag is therefore carried in
    the payload (below) and stamped by the CHILD, inside `_persist_resume_state` — the one
    callback `run_chained_inject` fires IMMEDIATELY before the verified Enter and nowhere
    else — so an aborted-before-Enter chain never stamps at all. (The daemon's own `_fire`
    path in `external_handoff_clear.py` is untouched: it stamps at spawn deliberately, per
    the advisor's D12 spawn-storm reasoning, and is not a caller of this function.)
    """
    terminal = terminal_trigger.self_terminal(os.environ)
    if not terminal_trigger.channel_is_readable(terminal):
        return False, f"channel {terminal.get('kind', '?')!r} cannot be read back"

    # WARN, never block (owner ruling via advisor 2026-08-14): the obligation to author a
    # handoff belongs to the invoking SKILL, which knows what the session was doing. Refusing
    # here would turn a missing handoff into a silently-skipped reload, and the session would
    # keep running stale plugin code — trading a recoverable loss for an invisible one.
    handoff = _read_handoff()
    if handoff is None:
        print(
            "HANDOFF_MISSING no handoff file found in .janitor/state/ — /clear is "
            "unrecoverable; author a handoff BEFORE shrinking",
            file=sys.stderr,
        )
    else:
        ok, reasons = check_handoff_concise(handoff)
        if not ok:
            print(f"HANDOFF_NOT_CONCISE {','.join(reasons)}", file=sys.stderr)

    chain_env = (
        {**os.environ, "JANITOR_TRANSCRIPT_PATH": transcript_path} if transcript_path else None
    )
    sd = _project_root() / ".janitor" / "state"
    _spawn_chain({
        "delay": delay,
        "terminal": terminal,
        "first": CLEAR_CMD,
        "then": list(then),
        "state_dir": str(sd),
        "gate_baseline": _gate_baseline(),
        "directive": directive,
        "settle_between_s": settle_between_s,
        "transcript_path": transcript_path,
        # TRDD-RAEGS1D5 card 5 regression fix: carried through so the CHILD can stamp the
        # cooldown at the verified Enter instead of the parent stamping blind at spawn.
        "count_toward_cooldown": count_toward_cooldown,
        # TRDD-RAEGS1D5 card 5 item 2: carried through so the CHILD's `_recovery_ok` can
        # ignore a `rate-limited.flag` predating this caller's own successful Stop.
        "recovered_after": recovered_after,
    }, env=chain_env)
    return True, "chain spawned"


# Phase outcome constants — what _fire_phase reports back to main.
_FIRED = "FIRED"
_DRY = "DRY"
_NO_ITERM = "NO_ITERM"


def _fire_phase(commands: Sequence[str], *, delay: float, dry_run: bool) -> str:
    """Fire ONE keystroke phase at THIS session's own pane via `terminal_trigger`
    (tmux / iTerm / Linux-GUI / ai-maestro CLI). Returns `_FIRED` / `_DRY` / `_NO_ITERM`.

    Presence is NOT gated here — main() checks it ONCE up front and passes
    respect_user_presence=False, so the /clear phase and the re-arm phase are atomic:
    we never clear the session and then refuse the re-arm because the user appeared in
    the settle window (which would strand the session unarmed).
    """
    sent = terminal_trigger.send_self_command(
        list(commands),
        delay_s=delay,
        esc_first=False,
        dry_run=dry_run,
        respect_user_presence=False,
    )
    if sent.startswith("FIRED:"):
        return _FIRED
    if sent.startswith("DRY_RUN:"):
        return _DRY
    # No channel this module can drive (delegated but unresolvable, or none at all).
    return _NO_ITERM


# `_user_present()` was REMOVED here (owner directive 2026-08-02: *"the old system that
# cancelled a command or prevented the agent to execute it if the user is PRESENT must go"*).
# It returned "the user is here, so refuse" and `main()` turned that into `USER_PRESENT` +
# exit 0 — which is how the owner, typing this very command at their own keyboard, was told to
# go away. Presence now DEFERS via `terminal_trigger.wait_until_pane_free`: wait for an empty
# field and 8s of no keystrokes, then proceed. Do not reintroduce a cancel here; if the pane
# never frees, the wait's own timeout reports DEFERRED and still writes no state.


def main() -> int:
    # CHILD entry: `clear_trigger.py --__chain <base64-payload>`. Checked before argparse so
    # the child never has to satisfy the human-facing flag surface.
    #
    # Wrapped so `_run_chain_payload`'s "never raises — but ALWAYS logs its outcome" contract is
    # enforced at the BOUNDARY. Its own body is a bare try/finally (the finally releases the
    # chain flock but catches nothing), so anything raised inside — e.g. a hung `osascript`
    # surfacing as `subprocess.TimeoutExpired` from the step executor — used to kill this
    # DEVNULL-stdio child with no log line at all, which is exactly the "give-up
    # indistinguishable from success" shape the docstring calls a defect in its own right.
    if len(sys.argv) >= 3 and sys.argv[1] == "--__chain":
        try:
            return _run_chain_payload(sys.argv[2])
        except Exception as exc:  # noqa: BLE001 - a detached child must log, never vanish
            state.log_line("clear-trigger", f"chain: ABORTED by an unhandled error — {exc!r}")
            return 1

    ap = argparse.ArgumentParser(
        description="Persist a link-only handoff + resume marker, then self-trigger "
        "/clear and bootstrap the fresh session to re-arm + resume."
    )
    ap.add_argument(
        "--directive",
        default="",
        help="one-line resume pointer recorded for the post-clear auto-resume "
        "(defaults to a pointer at the injected SessionStart handoff summary)",
    )
    ap.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="seconds before typing /clear (lets THIS turn settle so the soft "
        "/clear enqueues and runs at the turn boundary)",
    )
    ap.add_argument(
        "--clear-settle",
        type=float,
        default=8.0,
        help="extra seconds after /clear before the bootstrap is typed, so the fresh "
        "session + its SessionStart hooks are up before /janitor-arm lands",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="write the resume state + print the two-phase plan, but fire NOTHING "
        "(for tests — the real /clear would wipe the developer's own pane)",
    )
    ap.add_argument(
        "--transcript-path",
        default=None,
        help=(
            "this session's own transcript — session-scopes the ESC-interrupt cooldown check "
            "so two live sessions of the same project never share one "
            "(see terminal_trigger.inject_until_sent)"
        ),
    )
    args = ap.parse_args()

    # 1. Resolve the resume directive. A missing --directive falls back to a pointer at the
    #    link-only handoff, so the post-clear cron always has a resume target (there is no
    #    PostClear hook to synthesise one, unlike the compact path).
    directive = args.directive.strip() or (
        "read the injected SessionStart handoff summary FIRST (follow its wikimem/TRDD "
        "links via memgrep recall on demand), then resume your prior in-flight task."
    )

    # 2. NO PRESENCE CANCEL. It used to `print("USER_PRESENT"); return 0` here — and that is
    #    exactly how the owner, typing `/janitor-handoff-and-clear` at their own keyboard, got
    #    told to go away. Presence now DEFERS inside `terminal_trigger.inject_until_sent`
    #    (owner's three rules, 2026-08-02): the injector waits for an empty field, stops without
    #    cleanup the moment a key is pressed, and retries every 8 s until the command lands.
    #
    #    The ordering invariant this block used to carry SURVIVES, and is why the writes still
    #    come after: resume state must not exist unless /clear is actually about to run. With
    #    the gate placed after the writes (issue #105) a refused clear still left
    #    `resume-after-clear.flag` on disk, the next heartbeat consumed it, emitted a spurious
    #    [janitor-resume] and cleared it — so a later MANUAL /clear no longer auto-resumed.
    #    Deferral does not reintroduce that: the wait below returns BEFORE any state is
    #    written, so a give-up still writes nothing.
    if not args.dry_run:
        # BOUNDED wait (2026-08-02 review finding): the library default give-up is the
        # injector's 3600s, sized for the DETACHED child — but this call blocks main()
        # (the user's own foreground /janitor-handoff-and-clear turn), and the presence
        # probe's first rung is MACHINE-WIDE HID idle, so typing in any other app kept
        # this spinning for up to an hour while the session looked hung. Two minutes is
        # enough for "finish the sentence you were typing"; past that, defer loudly and
        # let the user re-run — the detached child keeps the long-patience behavior.
        free, why = terminal_trigger.wait_until_pane_free(
            terminal_trigger.self_terminal(os.environ), giveup_s=120
        )
        if not free:
            print(f"DEFERRED {why}", file=sys.stderr)
            return 0

    # 3. THE RESUME STATE IS NO LONGER WRITTEN HERE (TRDD-0BVF4K7E phase 2). It is written by
    #    the chained child, immediately before the VERIFIED Enter on /clear.
    #
    #    The invariant is unchanged and still load-bearing: resume state must exist before
    #    /clear runs, because /clear is unrecoverable and there is no PostClear hook. What
    #    changed is that the child can now DEFER for minutes (rule 2 — the user is typing), and
    #    writing here would mean a deferral that times out leaves `resume-after-clear.flag` on
    #    disk for a clear that never happened. The next heartbeat consumes it, emits a spurious
    #    [janitor-resume], and a later MANUAL /clear no longer auto-resumes — issue #105,
    #    re-introduced by the deferral that makes the injector safe. `pre_submit` is the only
    #    point where "about to clear" is actually true.

    # 4. Validate the handoff. ABSENCE IS FATAL; shape is WARN-only.
    #
    #    OWNER INVARIANT (2026-08-28, hard): "never execute the /clear unless you have
    #    already the certainty of having the summarized context ready to be injected."
    #
    #    This block used to be WARN-only for BOTH cases: it printed "author a handoff BEFORE
    #    clearing" and then cleared anyway. That is the one ordering `/clear` cannot survive —
    #    it is unrecoverable and there is no PostClear hook, so a clear fired without a handoff
    #    destroys the session's context with nothing on disk to restore it. The warning went to
    #    stderr, where an unattended run has no reader. Cost a real incident: a session mid-way
    #    through a TS→Rust migration woke blank (2026-08-28).
    #
    #    ABSENT → REFUSE, and refuse BEFORE any resume state or keystroke is dispatched, so the
    #    session is left exactly as it was. SHAPE (bloated/non-concise) stays a warning: a
    #    bloated handoff still restores the work, it just costs more context than it should —
    #    losing the session to enforce concision would be a worse trade than the defect.
    #    `--dry-run` is EXEMPT: it fires nothing, so there is no context to lose and refusing
    #    would break the one mode that exists to inspect this decision safely.
    handoff = _read_handoff()
    if handoff is None:
        print(
            "HANDOFF_MISSING no handoff file found in .janitor/state/"
            + ("" if args.dry_run else
               " — REFUSING to /clear. /clear is unrecoverable and there is no PostClear hook, "
               "so clearing now would destroy this session's context with nothing on disk to "
               "restore it. Author a handoff first (/janitor-write-handoff), then re-run."),
            file=sys.stderr,
        )
        if not args.dry_run:
            return 1
    else:
        ok, reasons = check_handoff_concise(handoff)
        if not ok:
            print(f"HANDOFF_NOT_CONCISE {','.join(reasons)}", file=sys.stderr)

    # 5. Fire the two phases. Phase A: /clear. Phase B: bootstrap (re-arm + resume),
    #    delayed by --clear-settle so the fresh session is up first. Both soft (no ESC):
    #    the invoking skill ends its turn right after this, so the enqueued /clear runs
    #    at the turn boundary and the bootstrap lands on the fresh idle prompt.
    delay = args.delay
    settle = args.clear_settle
    terminal = terminal_trigger.self_terminal(os.environ)

    if args.dry_run:
        boot = ", ".join(_BOOTSTRAP_CMDS)
        print(f"DRY_RUN would chain {CLEAR_CMD} then {boot} on {terminal.get('kind', '?')}")
        return 0

    # ONE chained child, not two blind timers. Phase B waits for phase A's VERIFIED submit
    # plus a real fresh-session signal, so a deferral can never decouple them and strand the
    # session unarmed. `--clear-settle` is retained only as the CHANNEL-UNAVAILABLE fallback
    # below; the chain itself gates on `clear-observed.ts`, not on that clock.
    if terminal_trigger.channel_is_readable(terminal):
        # Same seam `_spawn_chain`'s own docstring prescribes for `CLAUDE_PROJECT_DIR`: an
        # explicit per-child `env=` dict, never a bare `os.environ[...] = ...` in this
        # long-lived parent — that mutation would clobber every later plugin call in the same
        # process (CPV's CLAUDE_RESERVED_ENV_POISON / ENV_INJECTION class).
        chain_env = (
            {**os.environ, "JANITOR_TRANSCRIPT_PATH": args.transcript_path}
            if args.transcript_path else None
        )
        _spawn_chain({
            "delay": delay,
            "terminal": terminal,
            "first": CLEAR_CMD,
            "then": list(_BOOTSTRAP_CMDS),
            "state_dir": str(_project_root() / ".janitor" / "state"),
            "gate_baseline": _gate_baseline(),
            "directive": directive,
            # TRDD-RAEGS1D5 card 5: named here (the foreground /janitor-handoff-and-clear
            # invocation) exactly as spawn_shrink_chain already does for its callers, so
            # `_persist_resume_state` can write the per-pane sidecar the fresh session's
            # post-clear-compact hook consumes.
            "transcript_path": args.transcript_path,
        }, env=chain_env)
        print("CLEAR_CHAIN_SPAWNED")
        return 0

    # UNREADABLE CHANNEL (wtype/xdotool, or an unresolvable pane): the chain cannot verify
    # anything there, so fall back to the legacy blind two-phase send rather than refusing —
    # refusing would discard a command the user typed themselves, which is the behaviour the
    # owner removed. The resume state must then be written HERE, since no pre_submit runs.
    dpath = _write_directive(directive)
    mpath = _write_clear_marker(directive)
    print(f"DIRECTIVE_WRITTEN {dpath}")
    print(f"CLEAR_MARKER_WRITTEN {mpath}")
    # `_fire_phase` -> `send_self_command` has no per-child `env=` seam (unlike `_spawn_chain`
    # above), so this legacy fallback path uses the scoped, self-restoring env override instead
    # of a bare `os.environ[...] = ...`.
    with terminal_trigger.scoped_transcript_path_env(args.transcript_path):
        status_a = _fire_phase([CLEAR_CMD], delay=delay, dry_run=args.dry_run)
        status_b = _fire_phase(list(_BOOTSTRAP_CMDS), delay=delay + settle, dry_run=args.dry_run)
    # Both phases share the same pane, so they degrade together: if the pane isn't
    # automatable, NEITHER fired. The resume state is still recorded, so a manual
    # /clear + /janitor-arm still auto-resumes.
    if status_a == _NO_ITERM and status_b == _NO_ITERM:
        print("NO_ITERM")
        return 0
    print("CLEAR_FIRED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
