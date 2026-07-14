"""Tests for the /janitor-resume backing script (scripts/resume_trigger.py) — TRDD-HI0BGQGJ.

SAFETY: every test that exercises main() passes --dry-run and a controlled env, so
the real osascript that types /janitor-resume is NEVER fired (it would resume the
developer's own live pane). The pure helper is tested directly; main() is tested via
real subprocess runs with --dry-run.

Unlike the reload/compact triggers, resume has NO --hard mode: a compaction has
already ended the turn, so SOFT (no ESC) is the only correct mode and there is no
ESC path to test.
"""

from __future__ import annotations

import importlib.util as _u
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "resume_trigger.py"


def _import():
    spec = _u.spec_from_file_location("resume_trigger_under_test", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(args: list[str], *, iterm: str | None, present: bool = False) -> subprocess.CompletedProcess:
    import tempfile

    from conftest import away_home, present_home  # type: ignore[import-not-found]

    env = {"PATH": os.environ.get("PATH", "")}
    # Pin the terminal-kind so these tests exercise the iTerm path deterministically
    # regardless of the host terminal (e.g. running the suite inside tmux). The tmux
    # delegation is covered by test_terminal_trigger.py.
    env["JANITOR_FORCE_TERMINAL_KIND"] = "iterm"
    # Pin USER PRESENCE too: the trigger refuses to type into a pane the user is actively using, and
    # `user_is_present` fails CLOSED — so an unpinned HOME makes the result depend on whether the
    # developer running the suite happened to be typing.
    tmp = Path(tempfile.mkdtemp())
    env["HOME"] = str(present_home(tmp) if present else away_home(tmp))
    if iterm is not None:
        env["ITERM_SESSION_ID"] = iterm
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


# ---------- pure helper -----------------------------------------------------

def test_build_osascript_targets_uuid_and_types_resume() -> None:
    """The osascript targets the specific session id and types /janitor-resume, SOFT."""
    mod = _import()
    osa = mod._build_osascript("789D8299-5AA2-48CF-9325-3BC972B9BEAE", 2.0)
    assert '"789D8299-5AA2-48CF-9325-3BC972B9BEAE"' in osa, "must match the specific session id"
    # SOFT only: a compaction already ended the turn — NO ESC byte is ever sent.
    assert "character id 27" not in osa, "resume is SOFT-only; it must never send an ESC"
    assert '"/janitor-resume"' in osa, "must type /janitor-resume"
    assert '"/compact"' not in osa and '"/reload-plugins' not in osa, "wrong command"
    assert "delay 2.0" in osa, "must delay before firing so the parent returns first"


def test_uuid_regex_accepts_real_rejects_injection() -> None:
    mod = _import()
    assert mod._UUID_RE.match("789D8299-5AA2-48CF-9325-3BC972B9BEAE")
    for bad in (
        'x" then do shell script "touch /tmp/pwned" --',
        'abc"; tell app "Finder"',
        "id with spaces",
        "",
        "../../etc",
    ):
        assert not mod._UUID_RE.match(bad), f"{bad!r} must be rejected"


# ---------- main() via subprocess, ALWAYS --dry-run -----------------------

def test_dry_run_reports_plan_and_does_not_fire() -> None:
    """--dry-run + iTerm set: plan printed, NO osascript fired, NO ESC (SOFT-only)."""
    proc = _run(["--dry-run"], iterm="w0t3p0:789D8299-5AA2-48CF-9325-3BC972B9BEAE")
    assert proc.returncode == 0
    assert "DRY_RUN" in proc.stdout and "789D8299-5AA2-48CF-9325-3BC972B9BEAE" in proc.stdout
    assert "/janitor-resume" in proc.stdout
    assert "ESC->" not in proc.stdout, "resume is SOFT-only — never an ESC"
    assert "RESUME_FIRED" not in proc.stdout, "dry-run must not fire"


def test_no_iterm_reports_noop() -> None:
    """No ITERM_SESSION_ID: prints only NO_ITERM, fires nothing (cron path resumes)."""
    proc = _run([], iterm=None)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "NO_ITERM"
    assert "RESUME_FIRED" not in proc.stdout


def test_malformed_iterm_id_refuses_to_fire() -> None:
    """An injection-shaped ITERM_SESSION_ID is rejected (NO_ITERM), never fired."""
    proc = _run([], iterm='x:" then do shell script "touch /tmp/pwned" --')
    assert proc.returncode == 0
    assert "NO_ITERM" in proc.stdout
    assert "RESUME_FIRED" not in proc.stdout
