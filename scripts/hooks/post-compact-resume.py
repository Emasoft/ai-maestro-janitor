#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PostCompact hook — record what the next heartbeat should auto-resume.

Why this hook exists (the load-bearing reason):
A context compaction returns the Claude Code REPL to its IDLE state. It does
NOT auto-continue the task that was interrupted — and for a watchdog-triggered
manual `/compact` it never did. A hook cannot start a fresh turn either (only a
turn already in flight can be augmented). The ONLY thing that fires a fresh turn
is the janitor heartbeat cron. So an unattended session that compacts mid-work
would otherwise stall at this idle prompt forever, which is fatal for the
overnight task loop the watchdog is meant to enable.

This hook is the "what to resume" half of the fix. On every compaction it writes
`resume-after-compact.flag` (+ a `.ts` sidecar) into the project's janitor state
dir. The next heartbeat fire reads that flag (dispatch.py `_phase_compact_resume`)
and emits a single `[janitor-resume] …` cue carrying the directive; the standing
heartbeat posture maps `[janitor-resume]` to "resume the prior task", so the
agent picks the work back up automatically. The cron is the wake-up; this hook
only records the target.

Directive source priority:
  1. `<state>/resume-directive.txt` — an explicit, agent-maintained pointer
     (the `loop.md` pattern). The `/janitor-compact-context` skill writes this
     right before it triggers the compact, so the trigger and the resume target
     are recorded together. First non-empty, non-`#` line wins.
  2. Newest in-flight TRDD on the design board — a zero-discipline fallback for
     the case where a native auto-compact fires without the skill having set a
     directive. "In-flight" = column in {design, dispatch, dev, testing,
     ai_review, human_review}; ties broken by the most recent `updated:` field.
  3. Nothing identifiable → write NO flag. A compaction with no work in
     progress must not spawn a spurious resume turn.

Safety: a hook fault must NEVER break compaction. Everything is wrapped so the
hook always exits 0. The directive is defanged against marker-mimicry at the
emission site (dispatch.py `sanitize_for_drift_line`), so a TRDD title or
directive file containing `[janitor-reload]`-style text cannot inject a fake
heartbeat marker.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Columns that mean "this TRDD is actively being worked" — not parked
# (backburner/todo), not blocked, not terminal (complete/published/live/
# failed/superseded), not soak-monitoring (live_auditing).
_INFLIGHT_COLUMNS = frozenset(
    {"design", "dispatch", "dev", "testing", "ai_review", "human_review"}
)

# Canonical TRDD filename shape: TRDD-<YYYYMMDD_HHMMSS±HHMM>-<uid8>-<slug>.md.
# The timestamp uses `_` and a `+HHMM`/`-HHMM` offset (no internal `-` other
# than the field separators), so the 3rd dash-delimited field is the uid8.
# [0-9A-Za-z]: TRDD v2 ids are UPPERCASE base36, legacy v1 ids lowercase hex — hex-only
# here silently skipped every modern TRDD, so the auto-resume fallback named a stale
# hex-era task (or nothing) after a compaction. Anchored on the TRDD-<ts>- prefix.
_UID_RE = re.compile(r"TRDD-\d{8}_\d{6}[+-]\d{4}-([0-9A-Za-z]{8})-")

_MAX_DIRECTIVE_LEN = 280

# The PreCompact hook (scripts/hooks/pre-compact-handoff.py) writes this file —
# an authoritative, FILESYSTEM-DERIVED handoff (git HEAD + recent commits, working
# tree, in-flight TRDD STATE blocks) — into the SAME state dir on every compaction.
# When it exists we prepend a pointer so the post-compaction [janitor-resume] cue
# steers the next turn to re-ground there FIRST (the summary is treated as
# unverified). Kept SHORT so the combined directive stays within the 280-char clamp.
_HANDOFF_FILENAME = "precompact-handoff.md"
_HANDOFF_POINTER = (
    "read .janitor/state/precompact-handoff.md FIRST "
    "(filesystem-grounded truth; treat the summary as UNVERIFIED) — "
)


def _handoff_pointer(state_dir: Path) -> str:
    """Pointer prefix to the ground-truth handoff, or "" if it wasn't written."""
    try:
        if (state_dir / _HANDOFF_FILENAME).is_file():
            return _HANDOFF_POINTER
    except OSError:
        pass
    return ""


def _explicit_directive(state_dir: Path) -> str:
    """First non-empty, non-comment line of the agent's resume-directive.txt."""
    f = state_dir / "resume-directive.txt"
    try:
        text = f.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""


def _consume_directive_file(state_dir: Path) -> None:
    """Delete resume-directive.txt — the explicit pointer is one-shot per compact."""
    try:
        (state_dir / "resume-directive.txt").unlink()
    except (FileNotFoundError, OSError):
        pass


def _trdd_paths(project_root: Path) -> list[Path]:
    """Every TRDD on the board, across BOTH design scopes (PROJECT + LOCAL).

    FAIL-OPEN by design. This hook drives post-compaction auto-resume, so it must degrade,
    never die: if `trdd_common` cannot be imported for any reason, fall back to the plain
    PROJECT board rather than raising. A hook that crashes on import runs nothing at all
    and Claude Code does not surface it — that failure mode cost this plugin three weeks of
    silently-dead SessionStart (see tests/test_hooks_execute.py), and a resume hook is a
    worse place to relearn it.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if plugin_root:
        try:
            scripts = Path(plugin_root) / "scripts"
            # BOTH entries: `from lib import …` needs scripts/ on the path, and a lib module's
            # bare sibling import needs scripts/lib/ on it. Omitting the second is the exact
            # ModuleNotFoundError that killed on-session-start.py.
            for entry in (str(scripts), str(scripts / "lib")):
                if entry not in sys.path:
                    sys.path.insert(0, entry)
            from lib import trdd_common  # noqa: E402 - local package, not PyPI

            return [p for _scope, p in trdd_common.trdd_files("tasks", str(project_root))]
        except Exception:  # noqa: BLE001 -- degrade to the project board; never break resume
            pass
    tasks_dir = project_root / "design" / "tasks"
    if not tasks_dir.is_dir():
        return []
    return sorted(tasks_dir.glob("TRDD-*.md"))


def _inflight_trdd_directive(project_root: Path) -> str:
    """Build a 'continue TRDD-xxxx' directive from the newest in-flight TRDD.

    Reads only the frontmatter (top ~60 lines) of each TRDD on the board — BOTH design
    scopes, PROJECT and LOCAL. Scanning only the repo would strand exactly the work most
    likely to be interrupted: a LOCAL TRDD is a chore about THIS machine, and after a
    compaction it is the one thing a fresh context cannot reconstruct from the repo.

    `updated:` is an ISO-8601 string that sorts lexicographically within a
    shared local TZ offset, so a plain string-max picks the most recently
    touched in-flight task — a good "what was I just doing" heuristic.
    """
    trdds = _trdd_paths(project_root)
    if not trdds:
        return ""
    best: tuple[str, str, str] | None = None  # (updated, uid8, title)
    for path in trdds:
        m = _UID_RE.search(path.name)
        if not m:
            continue
        # Keep the id's original case: v2 ids are UPPERCASE base36 — lowercasing
        # corrupted the id shown in the resume directive (and breaks any
        # case-sensitive lookup); ids are matched case-insensitively anyway.
        uid8 = m.group(1)
        column = updated = title = ""
        try:
            with path.open("r", encoding="utf-8") as fh:
                for _ in range(60):
                    line = fh.readline()
                    if not line:
                        break
                    # maxsplit=1 keeps the colons inside an ISO `updated:` value.
                    if line.startswith("column:") and not column:
                        column = line.split(":", 1)[1].strip()
                    elif line.startswith("updated:") and not updated:
                        updated = line.split(":", 1)[1].strip()
                    elif line.startswith("title:") and not title:
                        title = line.split(":", 1)[1].strip()
                    elif line.rstrip() == "---" and column:
                        break  # end of frontmatter, and we have what we need
        except OSError:
            continue
        if column not in _INFLIGHT_COLUMNS:
            continue
        if best is None or updated > best[0]:
            best = (updated, uid8, title)
    if best is None:
        return ""
    _, uid8, title = best
    title = title[:80].strip()
    if title:
        return f"continue TRDD-{uid8} ({title}) — read its STATE block first, then proceed."
    return f"continue TRDD-{uid8} — read its STATE block first, then proceed."


def _record_resume_directive(state) -> bool:  # noqa: ANN001 - local module type
    """Determine + persist the post-compact resume directive (or nothing).

    Returns True iff a resume flag was written THIS call — the gate the caller uses
    to decide whether to fire the push (no target recorded → nothing to wake for).
    """
    state.init_state()
    sd = state.state_dir()
    explicit = _explicit_directive(sd)
    # The explicit pointer is ONE-SHOT: consume it now so a later native
    # auto-compact (with no fresh directive) falls back to the live board instead
    # of replaying a stale "resume at step X".
    _consume_directive_file(sd)
    directive = explicit or _inflight_trdd_directive(state.project_root())
    # If the PreCompact hook wrote a ground-truth handoff, the next turn MUST
    # re-ground there first. Prepend a pointer to whatever directive we have; and
    # if there's no in-flight directive at all, the handoff itself IS the resume
    # target (re-grounding is worth a resume turn even with no tracked task).
    pointer = _handoff_pointer(sd)
    if not directive:
        if pointer:
            directive = (
                "re-ground from the filesystem handoff, then continue your prior work"
            )
        else:
            state.log_line(
                "post-compact-resume",
                "no in-flight task and no handoff; no resume flag written",
            )
            return False
    directive = pointer + directive
    directive = " ".join(directive.split())  # collapse to a single bounded line
    if len(directive) > _MAX_DIRECTIVE_LEN:
        directive = directive[: _MAX_DIRECTIVE_LEN - 3] + "..."
    # Write the timestamp BEFORE the flag: the heartbeat treats the flag as the
    # trigger, so a reader that races in between sees "flag present, ts present"
    # or "neither" — never "flag without ts" (which would misreport the age).
    state.atomic_write(sd / "resume-after-compact.ts", str(int(time.time())))
    state.atomic_write(sd / "resume-after-compact.flag", directive)
    state.log_line("post-compact-resume", f"resume flag written: {directive[:80]}")
    return True


# ---- Post-compact PUSH (TRDD-HI0BGQGJ) -----------------------------------
# The resume FLAG above is only a note for the NEXT heartbeat cron fire. On an idle
# session the cron has demoted to the SLOW `*/30` floor, so that fire — and thus the
# resume — can be up to 30 min away (the "nothing written for 30 min" the user hit).
# This PUSH closes the gap: it types /janitor-resume into this session's own pane NOW
# (scripts/resume_trigger.py), so the resume runs in seconds. The cron path stays as
# the durable fallback — headless / non-automatable panes just fall back to it.
_PUSH_ENABLED_ENV = "CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ENABLED"
_PUSH_GRACE_ENV = "CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ATTENDED_GRACE_S"
# Attended-grace shrank 3 min → 10 s (owner directive 2026-07-17), then 20 s on the REAL typing
# signal (owner directive 2026-07-18): submit-based-only presence read a mid-typing user as
# unattended, so the push landed under their fingers. Matched to the injection gate
# (user_intent.USER_PRESENT_IDLE_S = 20), and _user_recently_active now consults
# user_intent.hid_idle_seconds() FIRST — any keystroke in the last 20 s means attended.
_PUSH_GRACE_DEFAULT_S = 20

# The attended-SESSION window (TRDD-GRHP2YHP): DISTINCT from the HID grace above. A user READING a
# long reply hasn't typed in >20 s (so the HID grace reads them as away) but submitted a prompt
# minutes ago — they are STILL attended, and the post-compact push landing under them is exactly the
# surprise the owner hit. So the push is ALSO suppressed when a genuine user PROMPT
# (`last_user_input_epoch`, bumped ONLY on a real submit, never on a cron turn) landed within this
# longer interactive window. The HID grace stays the "don't type under their fingers" floor; this
# window is the "is this session attended at all?" signal. An unattended overnight session (no
# genuine prompt for hours) still fires the push — the whole point of the post-compact resume
# (TRDD-HI0BGQGJ). Default 5 min ≈ interactive prompt cadence.
_PUSH_PROMPT_WINDOW_ENV = "CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ATTENDED_PROMPT_WINDOW_S"
_PUSH_PROMPT_WINDOW_DEFAULT_S = 300


def _push_grace_s() -> int:
    """Attended-grace window in seconds (env-overridable, non-negative)."""
    raw = os.environ.get(_PUSH_GRACE_ENV, "").strip()
    if not raw:
        return _PUSH_GRACE_DEFAULT_S
    try:
        value = int(raw)
    except ValueError:
        return _PUSH_GRACE_DEFAULT_S
    return value if value >= 0 else _PUSH_GRACE_DEFAULT_S


def _push_prompt_window_s() -> int:
    """Attended-SESSION window in seconds (env-overridable, non-negative) — TRDD-GRHP2YHP.

    Longer than the HID grace: it answers "is this session attended?" from the last genuine user
    PROMPT, so an attended-but-reading user (no keystroke for >20 s, but talking to us minutes ago)
    is not misread as away and does not get the resume push typed under them.
    """
    raw = os.environ.get(_PUSH_PROMPT_WINDOW_ENV, "").strip()
    if not raw:
        return _PUSH_PROMPT_WINDOW_DEFAULT_S
    try:
        value = int(raw)
    except ValueError:
        return _PUSH_PROMPT_WINDOW_DEFAULT_S
    return value if value >= 0 else _PUSH_PROMPT_WINDOW_DEFAULT_S


def _user_recently_active(state, now: int, grace_s: int, prompt_window_s: int) -> bool:  # noqa: ANN001
    """True iff the session is ATTENDED — a keystroke within `grace_s` OR a genuine prompt within `prompt_window_s`.

    Reads the cross-plugin user-presence breadcrumb's `last_user_input_epoch` — the
    SAME field dispatch.py's cadence reads — which the UserPromptSubmit hook bumps
    ONLY on real user input (never on a cron heartbeat). Gating the push on this is
    the whole reason it is safe to inject keystrokes automatically: an attended user
    is left alone (the cron still resumes them), so we never type into a live input
    line. Fail-safe: any read problem returns False (treat as unattended) — the push
    itself still degrades to NO_ITERM when there is no automatable pane.

    PRESENCE IS PER-PANE, and reading it machine-globally is what killed this feature.
    Measured 2026-07-28 across the fleet: five projects held an UNCONSUMED
    `resume-after-compact.flag`, two of them **4.3 days** old. The flag is only cleared by a
    heartbeat fire, so those sessions were never woken by either path — and the push, the
    path that wakes them in SECONDS, had been suppressed every time because the user was
    typing in a DIFFERENT pane. `user_intent.user_is_present` was fixed for exactly this on
    2026-07-16 ("a human typing in ANY session marked EVERY unattended pane present"); this
    gate kept reading `state.user_presence_path()` — the machine-global breadcrumb — and so
    inherited the bug that was already fixed next door. Now it goes through the same
    per-pane reader as every other injection gate: a pane the user has never typed in is
    correctly AWAY no matter how busy the rest of the machine is.

    RUNG 0 (the HID typing signal) lives INSIDE `user_is_present` and is deliberately kept
    there — it is the "do not type under their fingers" floor. Fails CLOSED: an unreadable
    breadcrumb reports PRESENT, so a breadcrumb fault can never license typing into a live
    input line.
    """
    try:
        from lib import user_intent  # noqa: PLC0415 - lazy: the hook's sys.path is set up in main()

        # Tri-state, unknown → NOT active: this gate's own contract is "no breadcrumb at all
        # → treat as UNATTENDED" (push allowed). The old boolean mapped unknown → present and
        # silently suppressed every push on a box with no breadcrumb — the safe side for an
        # INJECTOR, the wrong side for a notification.
        if user_intent.user_presence(idle_s=grace_s) is True:
            return True
    except Exception:  # noqa: BLE001 -- the probe must never break the push gate
        pass
    # The attended-SESSION window (TRDD-GRHP2YHP): a genuine prompt within `prompt_window_s`
    # (minutes, NOT the 20 s HID grace) means the user is here — reading the reply — even with no
    # recent keystroke. This is the fix for the push landing under an attended-but-reading user.
    #
    # It reads THIS PANE's breadcrumb, and only falls back to the machine-global one when the
    # terminal exports no per-pane id (Apple Terminal, plain xterm) — the SAME ladder
    # `user_intent.user_is_present` documents. Read globally it re-opened the whole bug the rung
    # above closes: any prompt anywhere in the last 5 minutes suppressed the push in every
    # unattended pane on the machine, which is a permanent state for someone who works all day.
    path = state.user_presence_path()
    try:
        pane_key = state.terminal_pane_key()
        if pane_key:
            pane_path = state.per_pane_presence_path(pane_key)
            if not pane_path.is_file():
                # Never typed in THIS pane ⇒ unattended here, whatever is happening elsewhere.
                return False
            path = pane_path
    except Exception:  # noqa: BLE001 -- never let pane resolution break the gate
        pass
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    last = data.get("last_user_input_epoch", 0)
    # bool is an int subclass — reject it so a stray `true` doesn't read as 1.
    if not isinstance(last, int) or isinstance(last, bool) or last <= 0:
        return False
    return (now - last) < prompt_window_s


def _maybe_push_resume(state) -> None:  # noqa: ANN001
    """Fire the detached /janitor-resume push — gated + best-effort.

    Called ONLY after a resume flag was written (so there IS a target). Skips
    silently when: the push is disabled by config, the user is recently active
    (attended — the cron path resumes them), or the injector cannot be located.
    Spawns fully detached so the hook returns immediately; the caller wraps this so
    a fault never affects the compaction.
    """
    if not state.is_truthy_env(_PUSH_ENABLED_ENV, default=True):
        return
    if _user_recently_active(
        state, int(time.time()), _push_grace_s(), _push_prompt_window_s()
    ):
        state.log_line("post-compact-resume", "user recently active; skipping resume push")
        return
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if not plugin_root:
        return
    trigger = Path(plugin_root) / "scripts" / "resume_trigger.py"
    if not trigger.is_file():
        return
    subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(trigger)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    state.log_line("post-compact-resume", "resume push fired (/janitor-resume)")


def main() -> int:
    # Drain stdin (PostCompact delivers a JSON payload there). We mainly rely on
    # CLAUDE_PROJECT_DIR for project resolution, but fall back to the payload's
    # `cwd` if the env var is somehow absent in this hook's environment.
    raw = ""
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        raw = ""
    cwd_fallback = ""
    if raw.strip() and not os.environ.get("CLAUDE_PROJECT_DIR", "").strip():
        try:
            payload = json.loads(raw)
            cwd_fallback = str(payload.get("cwd", "") or "") if isinstance(payload, dict) else ""
        except (ValueError, TypeError):
            cwd_fallback = ""

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if not plugin_root:
        print("[post-compact-resume] CLAUDE_PLUGIN_ROOT unset; skipping", file=sys.stderr)
        return 0

    # Import the local state lib AFTER extending sys.path (mirrors the other
    # hooks). Kept inside main() so the module stays import-safe and the PEP-723
    # dependency validator doesn't mistake the local `lib` package for a PyPI dep.
    sys.path.insert(0, str(Path(plugin_root) / "scripts"))
    try:
        from lib import state  # noqa: E402 - local package, not PyPI
    except Exception as exc:  # noqa: BLE001
        print(f"[post-compact-resume] state import failed: {exc}", file=sys.stderr)
        return 0

    # CPV-skillaudit: avoid reserved-env mutation. Hand the payload `cwd` to the
    # state lib as a guarded fallback override instead of writing the reserved
    # $CLAUDE_PROJECT_DIR into os.environ (which would clobber it session-wide for
    # every other plugin). state honours this ONLY when CLAUDE_PROJECT_DIR is
    # absent, and it MUST be set before the first project_root()/state_dir() call
    # below (those lru-cache the resolution on first use).
    if cwd_fallback:
        state.set_project_dir_override(cwd_fallback)

    # Stamp that a compaction just happened, so the proactive-idle trigger can learn this
    # session's post-compaction FLOOR (see cold_cache_compact.refresh_floor — that floor is the
    # only thing that makes the trigger terminate). Its OWN try: this is an optimization, and a
    # fault here must never cost us the resume flag below, which is survival-critical.
    try:
        from lib import cold_cache_compact  # noqa: PLC0415 - local package, not PyPI

        cold_cache_compact.mark_compacted(state.state_dir(), now=int(time.time()))
    except Exception as exc:  # noqa: BLE001
        print(f"[post-compact-resume] compact stamp skipped ({exc})", file=sys.stderr)

    try:
        wrote_flag = _record_resume_directive(state)
    except Exception as exc:  # noqa: BLE001 - a hook fault must never break compaction
        try:
            state.log_line("post-compact-resume", f"failed: {exc}")
        except Exception:  # noqa: BLE001
            print(f"[post-compact-resume] {exc}", file=sys.stderr)
        return 0

    # PUSH the resume (TRDD-HI0BGQGJ): the flag only wakes the session on the next
    # heartbeat cron fire — up to 30 min at the SLOW floor. If we recorded a resume
    # target, wake the session NOW. Separately wrapped so a push fault can never
    # break the compaction, and gated inside _maybe_push_resume (config / attended /
    # no automatable pane) — the cron path still resumes if the push is skipped.
    if wrote_flag:
        try:
            _maybe_push_resume(state)
        except Exception as exc:  # noqa: BLE001 - never let the push break compaction
            try:
                state.log_line("post-compact-resume", f"resume push failed: {exc}")
            except Exception:  # noqa: BLE001
                print(f"[post-compact-resume] push {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    # Bare main() — side effects live inside it so the module is import-safe
    # (no module-scope sys.exit), matching the other janitor hooks.
    main()
