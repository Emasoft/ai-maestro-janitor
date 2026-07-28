"""Tests for the SessionStart pre-import breadcrumb (janitor#80, PR #96 ported to main).

THE OUTAGE THIS EXISTS FOR. From 2026-06-20 to 2026-07-11 the SessionStart hook raised
ModuleNotFoundError before its first statement — a missing `scripts/lib` sys.path entry —
and Claude Code surfaced nothing. The only symptom was the absence of things nobody
watches: rules stopped updating (`universal-kanban.md` never reached `~/.claude/rules` at
all), reference docs stopped shipping, the memory breadcrumb stopped printing, the
USER-memory mirror stopped syncing. Three weeks, no error anywhere.

`tests/test_hooks_execute.py` now executes every hook, so that cannot recur IN THE REPO.
This is the other half: a DEPLOYMENT whose import breaks — a half-written plugin cache, a
version skew, a partial update — where no test is watching. `_early_log` is therefore
written to work when the `lib` package is exactly what is broken, which is why it
duplicates `state.log_dir()`'s resolution rather than calling it.

Real files, real subprocesses, real `git rev-parse` — no mocks, because every property
under test is about behaviour at the boundary where the normal machinery is unavailable.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HOOK = Path(__file__).resolve().parent.parent / "scripts" / "hooks" / "on-session-start.py"


def _load_hook():
    """Import the hook module by path (its name is not a valid identifier)."""
    spec = importlib.util.spec_from_file_location("on_session_start_under_test", _HOOK)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def hook():
    return _load_hook()


def _log_text(logs_dir: Path) -> str:
    p = logs_dir / "session-start.log"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def test_it_writes_a_line_under_the_explicit_log_dir_override(hook, tmp_path, monkeypatch):
    """JANITOR_LOG_DIR is the first rung, matching state.log_dir()'s own ladder."""
    logs = tmp_path / "explicit-logs"
    monkeypatch.setenv("JANITOR_LOG_DIR", str(logs))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

    hook._early_log("entered")

    assert "entered" in _log_text(logs)


def test_it_falls_back_to_the_project_dir_when_no_override(hook, tmp_path, monkeypatch):
    """Second rung: $CLAUDE_PROJECT_DIR/.janitor/logs — where a session's log belongs."""
    monkeypatch.delenv("JANITOR_LOG_DIR", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

    hook._early_log("entered")

    assert "entered" in _log_text(tmp_path / ".janitor" / "logs")


def test_it_creates_the_log_directory_when_absent(hook, tmp_path, monkeypatch):
    """A first-ever run has no .janitor/logs — the breadcrumb must not need one to exist."""
    monkeypatch.delenv("JANITOR_LOG_DIR", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert not (tmp_path / ".janitor").exists()

    hook._early_log("entered")

    assert (tmp_path / ".janitor" / "logs" / "session-start.log").is_file()


def test_the_line_format_matches_state_log_line(hook, tmp_path, monkeypatch):
    """Both writers share one file, so a mismatched shape would corrupt the log's grammar.

    `state.log_line` writes `[<iso±HHMM>] [s:<8>] <msg>`; the session block appears only
    when CLAUDE_CODE_SESSION_ID is set.
    """
    import re

    logs = tmp_path / "logs"
    monkeypatch.setenv("JANITOR_LOG_DIR", str(logs))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abcdef0123456789")

    hook._early_log("imports ok")

    line = _log_text(logs).strip()
    assert re.match(r"^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}\] \[s:abcdef01\] imports ok$", line)


def test_the_session_block_is_omitted_when_the_id_is_unset(hook, tmp_path, monkeypatch):
    """Graceful degradation to `[ts] <msg>` — the pre-2.1.132 shape."""
    import re

    logs = tmp_path / "logs"
    monkeypatch.setenv("JANITOR_LOG_DIR", str(logs))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

    hook._early_log("entered")

    assert re.match(r"^\[\S+\] entered$", _log_text(logs).strip())


def test_a_logging_fault_never_raises(hook, tmp_path, monkeypatch):
    """The contract: a broken log destination must not become the new way session start breaks.

    Point JANITOR_LOG_DIR at a path whose parent is a FILE, so mkdir cannot succeed.
    """
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("JANITOR_LOG_DIR", str(blocker / "logs"))

    hook._early_log("entered")  # must not raise — that is the whole assertion


def test_it_appends_rather_than_truncating(hook, tmp_path, monkeypatch):
    """"entered" then "imports ok" is the SIGNAL — a truncating writer would erase the pair."""
    logs = tmp_path / "logs"
    monkeypatch.setenv("JANITOR_LOG_DIR", str(logs))

    hook._early_log("entered")
    hook._early_log("imports ok")

    text = _log_text(logs)
    assert "entered" in text and "imports ok" in text
    assert len(text.strip().splitlines()) == 2


def test_a_broken_lib_import_is_LOGGED_and_still_fails(tmp_path):
    """The end-to-end property: the exact outage, reproduced, must now leave a trace.

    Runs the REAL hook as a subprocess with CLAUDE_PLUGIN_ROOT pointed at a tree that has
    no `scripts/lib`, so `from lib import ...` dies exactly as it did for three weeks. The
    hook must (a) leave "entered" and a FATAL line on disk, and (b) still exit non-zero —
    logging the fault must not turn it into a silent success, which would be a worse bug
    than the one being fixed.
    """
    fake_root = tmp_path / "plugin"
    (fake_root / "scripts").mkdir(parents=True)  # scripts/ exists, scripts/lib/ does NOT
    logs = tmp_path / "logs"

    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = str(fake_root)
    env["JANITOR_LOG_DIR"] = str(logs)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env.pop("CLAUDE_CODE_SESSION_ID", None)

    r = subprocess.run(
        [sys.executable, str(_HOOK)],
        capture_output=True, text=True, env=env, timeout=120, check=False,
    )

    text = _log_text(logs)
    assert "entered" in text, f"no breadcrumb written; log={text!r} stderr={r.stderr[-400:]!r}"
    assert "FATAL: lib import failed" in text, f"import death not recorded; log={text!r}"
    assert r.returncode != 0, "the hook must still FAIL — logging must not mask the fault"
