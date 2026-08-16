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
import state  # noqa: E402
import terminal_trigger  # noqa: E402

# An iTerm session id is a hex UUID (8-4-4-4-12). $ITERM_SESSION_ID is
# `<tty>:<UUID>`. We interpolate the UUID into an `osascript -e` string, so we MUST
# reject anything that isn't hex+dashes — an env var is attacker-settable, and a
# value like `x:" then do shell script "rm -rf ~" --` would otherwise inject
# AppleScript. A security plugin must not ship its own injection sink. (Same guard
# as compact_trigger / resume_trigger.)
_UUID_RE = re.compile(r"^[0-9A-Fa-f-]{8,64}$")

# The slash-commands the phases type into the pane. FIXED module constants (never
# user/env input), so interpolating them into the tmux/osascript send is not an
# injection sink (unlike the UUID, which is validated above).
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
# _fire_phase / _build_osascript) — and we NEVER send a bare Enter or Ctrl+C. WHY it is
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

_HANDOFF_FILENAME = "agent-handoff.md"


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
    """
    reasons: list[str] = []
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
    """The link-only handoff the skill authored, or None when it wasn't written."""
    f = _project_root() / ".janitor" / "state" / _HANDOFF_FILENAME
    try:
        return f.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None


def _build_osascript(
    uuid: str, delay_s: float, *, commands: Sequence[str], esc_first: bool = False
) -> str:
    """AppleScript that targets ONLY the session whose id == uuid, then types each
    command (SOFT — no ESC by default, so the command enqueues rather than interrupting
    the turn). Mirrors compact_trigger._build_osascript.

    The commands are FIXED module constants (never user/env input), so interpolating
    them is not an injection sink — unlike `uuid`, which `_UUID_RE` validates before it
    reaches here. Each command is typed via `write text "<cmd>"` (iTerm appends a
    return); a multi-command list types them back-to-back with a settle between, so the
    bootstrap enqueues `/janitor-arm` then `/janitor-resume` in order.
    """
    lines = [
        f"delay {delay_s}",
        'tell application "iTerm2"',
        "  repeat with w in windows",
        "    repeat with t in tabs of w",
        "      repeat with s in sessions of t",
        f'        if (id of s) is "{uuid}" then',
        "          tell s",
    ]
    if esc_first:
        lines += terminal_trigger.iterm_esc_lines()
    for i, command in enumerate(commands):
        if i:
            lines.append("            delay 0.4")  # let each enqueued command register
        lines.append(f'            write text "{terminal_trigger.applescript_quote(command)}"')
    lines += [
        "          end tell",
        "        end if",
        "      end repeat",
        "    end repeat",
        "  end repeat",
        "end tell",
    ]
    return "\n".join(lines) + "\n"


def _fire(script: str) -> None:
    """Launch osascript fully detached so the parent returns immediately."""
    subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        ["osascript", "-e", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# --- the CHAINED child (TRDD-0BVF4K7E phase 2) ------------------------------
#
# Replaces the two independent blind timers. Everything below runs in a DETACHED child,
# because the keystrokes must land after THIS turn ends — but unlike the old design the child
# now verifies each command before submitting it, and phase B chains on phase A's verified
# submit instead of a wall clock.

_GATE_STAMP = "clear-observed.ts"

# The chain's /clear injection ceiling. NOT the default 30 s inject give-up: the chain now
# carries a `still_wanted` cache probe (owner directive 2026-08-16) that cancels the moment
# agentlensPro reports the cache WARM, so the CONDITION is the terminator and this clock is
# only the backstop for the probe's "unknown" answers. An hour of 8 s retries against a busy
# pane with a still-cold cache is exactly the patience the feature needs — the give-up at 30 s
# is what left this session un-shrunk for 4+ hours on 2026-08-16.
_CLEAR_CHAIN_GIVEUP_S = 3600.0
_CHAIN_LOCK = "clear-chain.lock"


def came_back_since(verdict_ts: int, idle_s: int, now: int) -> bool:
    """PURE. Did a SUBSTANTIVE turn land after the clear was decided?

    `idle_s` is heartbeat-excluding (`fleet_scan.transcript_activity`), so `now - idle_s` is the
    moment of the last real turn. Strictly greater, not `>=`: a turn in the SAME second as the
    verdict is what the verdict itself was computed from, and `>=` would cancel every chain the
    instant it was fired.

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

    def _persist_resume_state() -> None:
        # Called by inject_until_sent IMMEDIATELY before Enter on /clear, and nowhere else.
        # main() used to write these before firing; once the child can defer for minutes, that
        # ordering resurrects issue #105 — a give-up would leave resume-after-clear.flag for a
        # /clear that never happened, and the next heartbeat would consume it.
        _write_directive(directive)
        _write_clear_marker(directive)
        persisted["done"] = True

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
        # with the same unreachability disease this hook just cured. `transcript_activity`
        # excludes heartbeats (`substantive_age_from_tail`) — the very distinction the long-idle
        # trigger is computed from, so the two can never disagree about what "activity" means.
        if not verdict_ts:
            return True, "no verdict timestamp — continuing"
        try:
            import fleet_scan  # noqa: PLC0415 — lazy; the chain child has scripts/lib on path

            idle_s, _enq, _await = fleet_scan.transcript_activity(
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

    def _still_wanted() -> tuple[bool, str]:
        """Both cancels. The activity check runs for EVERY trigger; the cache check only for a
        chain fired BECAUSE the cache was cold."""
        back_ok, back_why = _user_came_back()
        if not back_ok:
            return False, back_why
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
    subprocess.Popen(  # noqa: S603 - fixed argv (this script + a base64 blob), no shell
        [sys.executable, str(Path(__file__).resolve()), "--__chain", blob],
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
    unrecoverable command in this system.
    """
    terminal = _this_terminal()
    if not terminal_trigger.channel_is_readable(terminal):
        return False, f"channel {terminal.get('kind', '?')!r} cannot be read back"

    # WARN, never block (owner ruling via advisor 2026-08-14): the obligation to author a
    # handoff belongs to the invoking SKILL, which knows what the session was doing. Refusing
    # here would turn a missing handoff into a silently-skipped reload, and the session would
    # keep running stale plugin code — trading a recoverable loss for an invisible one.
    handoff = _read_handoff()
    if handoff is None:
        print(
            "HANDOFF_MISSING no .janitor/state/agent-handoff.md — /clear is unrecoverable; "
            "author the link-only handoff BEFORE shrinking",
            file=sys.stderr,
        )
    else:
        ok, reasons = check_handoff_concise(handoff)
        if not ok:
            print(f"HANDOFF_NOT_CONCISE {','.join(reasons)}", file=sys.stderr)

    _spawn_chain({
        "delay": delay,
        "terminal": terminal,
        "first": CLEAR_CMD,
        "then": list(then),
        "state_dir": str(_project_root() / ".janitor" / "state"),
        "gate_baseline": _gate_baseline(),
        "directive": directive,
        "settle_between_s": settle_between_s,
    })
    return True, "chain spawned"


# Phase outcome constants — what _fire_phase reports back to main.
_FIRED = "FIRED"
_DRY = "DRY"
_NO_ITERM = "NO_ITERM"


def _fire_phase(commands: Sequence[str], *, delay: float, dry_run: bool) -> str:
    """Fire ONE keystroke phase at THIS session's own pane via the same dual-path
    compact_trigger uses: tmux / Linux-GUI / ai-maestro CLI via terminal_trigger, and
    iTerm via our own osascript. Returns `_FIRED` / `_DRY` / `_NO_ITERM`.

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
    if sent != terminal_trigger.USE_ITERM_PATH:
        if sent.startswith("FIRED:"):
            return _FIRED
        if sent.startswith("DRY_RUN:"):
            return _DRY
        # NO_AUTO_TERMINAL:<kind> — a delegated terminal whose target was unresolvable.
        return _NO_ITERM
    # iTerm path (or any terminal terminal_trigger doesn't automate → degrade).
    iterm = os.environ.get("ITERM_SESSION_ID", "").strip()
    if not iterm:
        return _NO_ITERM
    uuid = iterm.split(":")[-1].strip()
    if not _UUID_RE.match(uuid):
        # Injection-shaped session id — refuse to build the osascript. The resume
        # state is still recorded, so the skill can ask the user to clear manually.
        print(f"BAD_ITERM_ID {uuid[:32]}", file=sys.stderr)
        return _NO_ITERM
    if dry_run:
        return _DRY
    _fire(_build_osascript(uuid, delay, commands=commands))
    return _FIRED


def _this_terminal() -> dict[str, str]:
    """THIS session's pane identity, for the read-back wait. tmux is preferred because it can
    be captured cheaply; iTerm needs an osascript round-trip but is readable too. Anything
    else resolves to a kind the reader returns None for — which the wait treats as
    "cannot tell, proceed", never as a refusal."""
    pane = os.environ.get("TMUX_PANE", "").strip()
    if pane:
        return {"kind": "tmux", "pane": pane}
    iterm = os.environ.get("ITERM_SESSION_ID", "").strip()
    if iterm:
        return {"kind": "iterm", "session_id": iterm.split(":")[-1].strip()}
    return {"kind": "unknown"}


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
        "(defaults to a pointer at the link-only agent-handoff.md)",
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
    args = ap.parse_args()

    # 1. Resolve the resume directive. A missing --directive falls back to a pointer at the
    #    link-only handoff, so the post-clear cron always has a resume target (there is no
    #    PostClear hook to synthesise one, unlike the compact path).
    directive = args.directive.strip() or (
        "read .janitor/state/agent-handoff.md FIRST (link-only handoff — follow its "
        "wikimem/TRDD links via memgrep recall on demand), then resume your prior "
        "in-flight task."
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
        free, why = terminal_trigger.wait_until_pane_free(_this_terminal(), giveup_s=120)
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

    # 4. Validate the handoff against the concise-but-exhaustive contract (WARN-only;
    #    /clear still proceeds). A missing handoff on an unrecoverable /clear is worth
    #    a loud stderr line; a bloated one defeats the point of preferring /clear.
    handoff = _read_handoff()
    if handoff is None:
        print(
            "HANDOFF_MISSING no .janitor/state/agent-handoff.md — /clear is "
            "unrecoverable; author the link-only handoff BEFORE clearing",
            file=sys.stderr,
        )
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
    terminal = _this_terminal()

    if args.dry_run:
        boot = ", ".join(_BOOTSTRAP_CMDS)
        print(f"DRY_RUN would chain {CLEAR_CMD} then {boot} on {terminal.get('kind', '?')}")
        return 0

    # ONE chained child, not two blind timers. Phase B waits for phase A's VERIFIED submit
    # plus a real fresh-session signal, so a deferral can never decouple them and strand the
    # session unarmed. `--clear-settle` is retained only as the CHANNEL-UNAVAILABLE fallback
    # below; the chain itself gates on `clear-observed.ts`, not on that clock.
    if terminal_trigger.channel_is_readable(terminal):
        _spawn_chain({
            "delay": delay,
            "terminal": terminal,
            "first": CLEAR_CMD,
            "then": list(_BOOTSTRAP_CMDS),
            "state_dir": str(_project_root() / ".janitor" / "state"),
            "gate_baseline": _gate_baseline(),
            "directive": directive,
        })
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
