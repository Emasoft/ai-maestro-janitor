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
_UID_RE = re.compile(r"TRDD-\d{8}_\d{6}[+-]\d{4}-([0-9a-fA-F]{8})-")

_MAX_DIRECTIVE_LEN = 280


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


def _inflight_trdd_directive(project_root: Path) -> str:
    """Build a 'continue TRDD-xxxx' directive from the newest in-flight TRDD.

    Reads only the frontmatter (top ~60 lines) of each design/tasks/TRDD-*.md.
    `updated:` is an ISO-8601 string that sorts lexicographically within a
    shared local TZ offset, so a plain string-max picks the most recently
    touched in-flight task — a good "what was I just doing" heuristic.
    """
    tasks_dir = project_root / "design" / "tasks"
    if not tasks_dir.is_dir():
        return ""
    best: tuple[str, str, str] | None = None  # (updated, uid8, title)
    for path in tasks_dir.glob("TRDD-*.md"):
        m = _UID_RE.search(path.name)
        if not m:
            continue
        uid8 = m.group(1).lower()
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


def _record_resume_directive(state) -> None:  # noqa: ANN001 - local module type
    """Determine + persist the post-compact resume directive (or nothing)."""
    state.init_state()
    sd = state.state_dir()
    explicit = _explicit_directive(sd)
    # The explicit pointer is ONE-SHOT: consume it now so a later native
    # auto-compact (with no fresh directive) falls back to the live board instead
    # of replaying a stale "resume at step X".
    _consume_directive_file(sd)
    directive = explicit or _inflight_trdd_directive(state.project_root())
    if not directive:
        state.log_line(
            "post-compact-resume",
            "no in-flight task found; no resume flag written",
        )
        return
    directive = " ".join(directive.split())  # collapse to a single bounded line
    if len(directive) > _MAX_DIRECTIVE_LEN:
        directive = directive[: _MAX_DIRECTIVE_LEN - 3] + "..."
    # Write the timestamp BEFORE the flag: the heartbeat treats the flag as the
    # trigger, so a reader that races in between sees "flag present, ts present"
    # or "neither" — never "flag without ts" (which would misreport the age).
    state.atomic_write(sd / "resume-after-compact.ts", str(int(time.time())))
    state.atomic_write(sd / "resume-after-compact.flag", directive)
    state.log_line("post-compact-resume", f"resume flag written: {directive[:80]}")


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

    try:
        _record_resume_directive(state)
    except Exception as exc:  # noqa: BLE001 - a hook fault must never break compaction
        try:
            state.log_line("post-compact-resume", f"failed: {exc}")
        except Exception:  # noqa: BLE001
            print(f"[post-compact-resume] {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    # Bare main() — side effects live inside it so the module is import-safe
    # (no module-scope sys.exit), matching the other janitor hooks.
    main()
