"""Tests for the /janitor-compact-context backing script (scripts/compact_trigger.py).

SAFETY: every test that exercises main() passes --dry-run and a controlled env, so
the real osascript ESC->/compact is NEVER fired (it would compact the developer's
own live pane). The pure helpers are tested directly; main() is tested via real
subprocess runs with --dry-run.
"""

from __future__ import annotations

import importlib.util as _u
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "compact_trigger.py"


def _import():
    spec = _u.spec_from_file_location("compact_trigger_under_test", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(args: list[str], *, project: Path, iterm: str | None) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "CLAUDE_PROJECT_DIR": str(project)}
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


# ---------- pure helpers ---------------------------------------------------

def test_project_root_honors_env(monkeypatch, tmp_path: Path) -> None:
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert mod._project_root() == tmp_path


def test_write_directive_path_and_content(monkeypatch, tmp_path: Path) -> None:
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    path = mod._write_directive("continue TRDD-31095269 at P3")
    assert path == tmp_path / ".janitor" / "state" / "resume-directive.txt"
    assert path.read_text(encoding="utf-8").strip() == "continue TRDD-31095269 at P3"


def test_build_osascript_targets_uuid_and_sends_esc_then_compact() -> None:
    mod = _import()
    osa = mod._build_osascript("789D8299-5AA2-48CF-9325-3BC972B9BEAE", 2.0)
    assert '"789D8299-5AA2-48CF-9325-3BC972B9BEAE"' in osa, "must match the specific session id"
    assert "character id 27" in osa, "must send a raw ESC byte"
    assert '"/compact"' in osa, "must send /compact"
    assert "delay 2.0" in osa, "must delay before firing so the parent returns first"


# ---------- main() via subprocess, ALWAYS --dry-run -----------------------

def test_dry_run_writes_directive_and_reports_plan(tmp_path: Path) -> None:
    """--dry-run + iTerm set: directive written, plan printed, NO osascript fired."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run(
        ["--dry-run", "--directive", "continue TRDD-31095269 at P3 — read STATE block"],
        project=p,
        iterm="w0t3p0:789D8299-5AA2-48CF-9325-3BC972B9BEAE",
    )
    assert proc.returncode == 0
    assert "DIRECTIVE_WRITTEN" in proc.stdout
    assert "DRY_RUN" in proc.stdout and "789D8299-5AA2-48CF-9325-3BC972B9BEAE" in proc.stdout
    assert "COMPACT_FIRED" not in proc.stdout, "dry-run must not fire"
    written = (p / ".janitor" / "state" / "resume-directive.txt").read_text(encoding="utf-8")
    assert written.strip() == "continue TRDD-31095269 at P3 — read STATE block"


def test_no_iterm_reports_and_still_records_directive(tmp_path: Path) -> None:
    """No ITERM_SESSION_ID: prints NO_ITERM but the resume directive is still recorded."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run(["--directive", "continue TRDD-abcd1234"], project=p, iterm=None)
    assert proc.returncode == 0
    assert "NO_ITERM" in proc.stdout
    assert "COMPACT_FIRED" not in proc.stdout
    assert (p / ".janitor" / "state" / "resume-directive.txt").exists()


def test_no_directive_no_iterm_is_silent_noop(tmp_path: Path) -> None:
    """No directive + no iTerm: writes nothing, prints only NO_ITERM."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run([], project=p, iterm=None)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "NO_ITERM"
    assert not (p / ".janitor" / "state" / "resume-directive.txt").exists()


def test_uuid_regex_accepts_real_rejects_injection() -> None:
    """The UUID guard accepts a real session id and rejects AppleScript-injection."""
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


def test_malformed_iterm_id_refuses_to_fire(tmp_path: Path) -> None:
    """An injection-shaped ITERM_SESSION_ID is rejected (NO_ITERM), never fired.

    The directive is still recorded so the skill can ask the user to /compact.
    """
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run(
        ["--directive", "continue TRDD-abcd1234"],
        project=p,
        iterm='x:" then do shell script "touch /tmp/pwned" --',
    )
    assert proc.returncode == 0
    assert "NO_ITERM" in proc.stdout
    assert "COMPACT_FIRED" not in proc.stdout
    assert (p / ".janitor" / "state" / "resume-directive.txt").exists()
