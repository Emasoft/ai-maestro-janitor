"""capture_all_logins.py — walks every rotator account and mints OAuth for each
in sequence, the backing script for /janitor-capture-all-logins. TRDD-GZXTSJSR P3."""

from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))

import capture_all_logins as cal  # noqa: E402


def _make_exec(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env python3\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_known_emails_parses_one_email_per_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`known_emails()` returns the real subprocess's stdout lines, blank lines dropped."""
    fake_rotator = tmp_path / "rotator.py"
    _make_exec(fake_rotator, 'print("a@example.com")\nprint("")\nprint("b@example.com")')
    monkeypatch.setattr(cal, "_ROTATOR_PY", fake_rotator)
    assert cal.known_emails(env={}) == ["a@example.com", "b@example.com"]


def test_known_emails_raises_on_nonzero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A hard failure in the roster listing (rotator.py itself erroring) raises, not swallows."""
    fake_rotator = tmp_path / "rotator.py"
    _make_exec(fake_rotator, 'import sys\nprint("boom", file=sys.stderr)\nsys.exit(3)')
    monkeypatch.setattr(cal, "_ROTATOR_PY", fake_rotator)
    with pytest.raises(RuntimeError, match="boom"):
        cal.known_emails(env={})


def test_known_emails_raises_when_engine_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing rotator.py is an infra failure, not a silent empty roster."""
    monkeypatch.setattr(cal, "_ROTATOR_PY", tmp_path / "does-not-exist.py")
    with pytest.raises(RuntimeError, match="missing"):
        cal.known_emails(env={})


def test_capture_one_strips_claude_plugin_data_from_child_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_child_env()` unsets CLAUDE_PLUGIN_DATA so the rotator's own data-dir guard resolves
    it (a foreign value from another plugin's context mis-routes the rotator otherwise)."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", "/somewhere/else")
    env = cal._child_env()
    assert "CLAUDE_PLUGIN_DATA" not in env


def test_capture_one_raises_when_script_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing slot_capture_browser.py is an infra failure the walker must stop the whole run on."""
    monkeypatch.setattr(cal, "_CAPTURE_PY", tmp_path / "does-not-exist.py")
    with pytest.raises(RuntimeError, match="missing"):
        cal.capture_one("a@example.com", env={})


def test_main_reports_success_when_all_accounts_capture_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The walker: lists 2 accounts, both capture OK -> prints per-account progress, exit 0."""
    monkeypatch.setattr(cal, "known_emails", lambda env=None: ["a@example.com", "b@example.com"])
    calls: list[str] = []

    def fake_capture_one(email: str, *, env=None, timeout=cal.CAPTURE_TIMEOUT_S):
        calls.append(email)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cal, "capture_one", fake_capture_one)
    rc = cal.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == ["a@example.com", "b@example.com"]
    assert "1/2 — capturing a@example.com" in out
    assert "2/2 — capturing b@example.com" in out
    assert "done — 2/2 accounts captured." in out


def test_main_continues_past_one_failed_account_and_reports_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A single account's capture failing (lapsed session) is NOT a hard error — the walk
    continues to the remaining accounts and reports the partial failure at the end."""
    monkeypatch.setattr(cal, "known_emails", lambda env=None: ["a@example.com", "b@example.com"])
    calls: list[str] = []

    def fake_capture_one(email: str, *, env=None, timeout=cal.CAPTURE_TIMEOUT_S):
        calls.append(email)
        if email == "a@example.com":
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="lapsed session")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cal, "capture_one", fake_capture_one)
    rc = cal.main([])
    out_err = capsys.readouterr()
    assert rc == 1  # partial failure still reported via a non-zero exit
    assert calls == ["a@example.com", "b@example.com"]  # b was NOT skipped
    assert "FAILED (rc=1)" in out_err.err
    assert "1/2 captured, 1 failed: a@example.com" in out_err.out


def test_main_fails_fast_when_capture_script_itself_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An infra failure (the capture script is gone) aborts the whole walk immediately —
    it cannot succeed for ANY remaining account either."""
    monkeypatch.setattr(cal, "known_emails", lambda env=None: ["a@example.com", "b@example.com"])
    calls: list[str] = []

    def fake_capture_one(email: str, *, env=None, timeout=cal.CAPTURE_TIMEOUT_S):
        calls.append(email)
        raise RuntimeError("capture script missing: /nope")

    monkeypatch.setattr(cal, "capture_one", fake_capture_one)
    rc = cal.main([])
    assert rc == 1
    assert calls == ["a@example.com"]  # aborted before trying b
    assert "FAILED: capture script missing" in capsys.readouterr().err


def test_main_reports_clean_no_op_when_roster_is_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No known accounts configured -> a clean, non-alarming exit, not a false failure."""
    monkeypatch.setattr(cal, "known_emails", lambda env=None: [])
    rc = cal.main([])
    assert rc == 0
    assert "nothing to capture" in capsys.readouterr().out


def test_main_fails_fast_when_roster_listing_itself_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The roster call failing (rotator.py itself broken) is a hard error — exit 1, no capture
    attempted for anyone."""

    def raiser(env=None):
        raise RuntimeError("engine broken")

    monkeypatch.setattr(cal, "known_emails", raiser)
    rc = cal.main([])
    assert rc == 1
    assert "FAILED to list accounts" in capsys.readouterr().err
