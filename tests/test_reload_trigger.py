"""Tests for the /janitor-reload-plugins backing script (scripts/reload_trigger.py).

SAFETY: every test that exercises main() passes --dry-run and a controlled env, so
the real osascript ESC->/reload-plugins is NEVER fired (it would reload the
developer's own live pane). The pure helper is tested directly; main() is tested
via real subprocess runs with --dry-run.

Unlike the compact trigger, reload records NO resume directive (reloading plugins
does not discard the conversation), so there is no file side effect to assert.
"""

from __future__ import annotations

import importlib.util as _u
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "reload_trigger.py"


def _import():
    spec = _u.spec_from_file_location("reload_trigger_under_test", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(args: list[str], *, iterm: str | None) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", "")}
    # Pin the terminal-kind so these tests exercise the iTerm path deterministically
    # regardless of the host terminal (e.g. running the suite inside tmux). The tmux
    # delegation is covered by test_terminal_trigger.py.
    env["JANITOR_FORCE_TERMINAL_KIND"] = "iterm"
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

def test_build_osascript_targets_uuid_and_sends_esc_then_reload() -> None:
    mod = _import()
    osa = mod._build_osascript("789D8299-5AA2-48CF-9325-3BC972B9BEAE", 2.0)
    assert '"789D8299-5AA2-48CF-9325-3BC972B9BEAE"' in osa, "must match the specific session id"
    assert "character id 27" in osa, "must send a raw ESC byte"
    assert '"/reload-plugins"' in osa, "must send /reload-plugins"
    assert '"/compact"' not in osa, "must NOT send /compact (this is the reload trigger)"
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
    """--dry-run + iTerm set: plan printed, NO osascript fired."""
    proc = _run(["--dry-run"], iterm="w0t3p0:789D8299-5AA2-48CF-9325-3BC972B9BEAE")
    assert proc.returncode == 0
    assert "DRY_RUN" in proc.stdout and "789D8299-5AA2-48CF-9325-3BC972B9BEAE" in proc.stdout
    assert "reload-plugins" in proc.stdout
    assert "RELOAD_FIRED" not in proc.stdout, "dry-run must not fire"


def test_no_iterm_reports_noop() -> None:
    """No ITERM_SESSION_ID: prints only NO_ITERM, fires nothing."""
    proc = _run([], iterm=None)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "NO_ITERM"
    assert "RELOAD_FIRED" not in proc.stdout


def test_malformed_iterm_id_refuses_to_fire() -> None:
    """An injection-shaped ITERM_SESSION_ID is rejected (NO_ITERM), never fired."""
    proc = _run([], iterm='x:" then do shell script "touch /tmp/pwned" --')
    assert proc.returncode == 0
    assert "NO_ITERM" in proc.stdout
    assert "RELOAD_FIRED" not in proc.stdout
