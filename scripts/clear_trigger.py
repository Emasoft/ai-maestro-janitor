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
import os
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import terminal_trigger  # noqa: E402
import user_intent  # noqa: E402

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
_ALL_CMDS: tuple[str, ...] = (CLEAR_CMD, *_BOOTSTRAP_CMDS)

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
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
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


def _user_present() -> bool:
    """True iff we must NOT type into this pane (the user is active here and did not
    ask). The single presence gate for BOTH phases — checked once in main so the
    clear+bootstrap pair is atomic. Fail-OPEN toward firing (an unresolvable presence
    read must not strand an unattended session, which is the whole target of this
    primitive; a redundant injection into an idle pane is merely noise)."""
    try:
        allowed, _ = user_intent.injection_allowed(list(_ALL_CMDS), env=os.environ)
        return not allowed
    except Exception:  # noqa: BLE001 - fail-open toward firing
        return False


def main() -> int:
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

    # 2. Presence gate ONCE, up front — BEFORE writing any resume state (issue #105, the
    #    silent-disarm class). Typing into a pane whose user is mid-sentence clobbers what
    #    they were writing; /clear would additionally wipe their session. If they are present
    #    they will drive the session themselves (the SessionStart re-arm nudge covers them) —
    #    so refuse AND write NOTHING. Recording resume-after-clear.flag here (as this used to,
    #    with the gate placed AFTER the writes) was a silent disarm: /clear never fires, yet
    #    the next heartbeat consumes the flag, emits a spurious [janitor-resume], and clears it
    #    — so a later MANUAL /clear no longer auto-resumes. The flag must exist ONLY when /clear
    #    is actually about to run, which is exactly the invariant this ordering restores.
    if not args.dry_run and _user_present():
        print("USER_PRESENT")
        return 0

    # 3. PERSIST THE RESUME STATE — before firing anything. /clear is unrecoverable, so the
    #    marker + directive MUST be on disk before it runs.
    dpath = _write_directive(directive)
    mpath = _write_clear_marker(directive)
    print(f"DIRECTIVE_WRITTEN {dpath}")
    print(f"CLEAR_MARKER_WRITTEN {mpath}")

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
    status_a = _fire_phase([CLEAR_CMD], delay=delay, dry_run=args.dry_run)
    status_b = _fire_phase(list(_BOOTSTRAP_CMDS), delay=delay + settle, dry_run=args.dry_run)

    if args.dry_run:
        boot = ", ".join(_BOOTSTRAP_CMDS)
        print(
            f"DRY_RUN would fire {CLEAR_CMD} after {delay}s, then {boot} after "
            f"{delay + settle}s"
        )
        return 0
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
