"""Latch-aware OAuth health reporting + graceful degradation (janitor #82) — real, no mocks.

Two defects were fixed at the STATUS/REPORTING layer (the keychain I/O is untouched):

  * fix #1 — a SET keychain denied-latch made `oauth-health` report every account as a
    definite `has_refresh: false` and `lifetime-status.sh` print "no oauth" for all of them.
    A latched store is UNKNOWN-state, not no-credential; it must read "latched".
  * fix #2 — a single hung live-credential read latched the whole store and blinded every
    account. The status command now reads the CLI-written per-account SLOTS FIRST and does the
    flaky live read LAST (only while the latch is clear), so a live hang can no longer erase
    the slot truth already captured, and each unreadable account is labelled "latched", not
    falsely zeroed.

These feed the PURE assembly/degradation layer (`build_oauth_health`) real input dicts, drive
`cmd_oauth_health` with the read functions monkeypatched (so the ORDER + latch-awareness are
exercised without a live keychain), and run the shipped `lifetime-status.sh` end-to-end against
a stub engine. Feeding a pure classifier real dicts / a real script a canned data source is not
mocking the logic under test — it is the only way to test a decision layer without a keychain.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_OAUTH_DIR = _HERE.parent / "scripts" / "oauth_rotator"
_ROTATOR_PY = _OAUTH_DIR / "rotator.py"
_LIFETIME_STATUS = _OAUTH_DIR / "lifetime-status.sh"


def _load_rotator():
    """Import rotator.py by path (it lives outside any package)."""
    spec = importlib.util.spec_from_file_location("rotator_health_under_test", _ROTATOR_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rotator = _load_rotator()


def _blob(*, refresh: bool = True, expires_ms: int | None = None) -> dict:
    """A minimal credential blob in the real `{"claudeAiOauth": {...}}` shape."""
    inner: dict = {"accessToken": "tok"}
    if refresh:
        inner["refreshToken"] = "r"
    if expires_ms is not None:
        inner["expiresAt"] = expires_ms
    return {"claudeAiOauth": inner}


# ---------- PURE build_oauth_health (fix #1 + #2 decision layer) ------------

def test_latched_account_reports_status_latched_not_no_oauth() -> None:
    """A read denied by the latch is UNKNOWN ("latched"), NEVER a definite "no-oauth" (fix #1)."""
    h = rotator.build_oauth_health(["a@x"], None, {"a@x": None}, {"a@x"}, None)
    assert h["a@x"]["status"] == "latched"
    assert h["a@x"]["has_refresh"] is False  # unknown, not a proven-positive either


def test_readable_slot_reports_ok_with_refresh() -> None:
    """A readable refresh-capable slot classifies as "ok" and surfaces has_refresh."""
    h = rotator.build_oauth_health(["a@x"], None, {"a@x": _blob(refresh=True)}, set(), None)
    assert h["a@x"]["status"] == "ok"
    assert h["a@x"]["has_refresh"] is True


def test_genuine_absence_reports_no_oauth() -> None:
    """A None read that is NOT latch-denied (genuinely not-found) stays "no-oauth" (a not-found
    never latches, so it must not be masked as "latched")."""
    h = rotator.build_oauth_health(["a@x"], None, {"a@x": None}, set(), None)
    assert h["a@x"]["status"] == "no-oauth"


def test_live_account_falls_back_to_readable_slot_when_live_blob_absent() -> None:
    """When the flaky live-credential read is skipped/denied (live_blob=None) but the account's
    SLOT is readable, the live account reports from its slot — the live hang does not zero it (fix #2)."""
    h = rotator.build_oauth_health(["live@x"], "live@x", {"live@x": _blob(refresh=True)}, set(), None)
    assert h["live@x"]["status"] == "ok"
    assert h["live@x"]["has_refresh"] is True


def test_one_denied_account_does_not_zero_the_readable_ones() -> None:
    """Per-account truth is preserved: one latch-denied account is "latched" while a sibling
    with a readable slot stays "ok" — one bad read never blinds the whole store (fix #2)."""
    h = rotator.build_oauth_health(
        ["ok@x", "bad@x"], None,
        {"ok@x": _blob(refresh=True), "bad@x": None},
        {"bad@x"}, None,
    )
    assert h["ok@x"]["status"] == "ok" and h["ok@x"]["has_refresh"] is True
    assert h["bad@x"]["status"] == "latched"


def test_live_blob_preferred_over_slot_for_the_live_account() -> None:
    """The fresher live_blob wins over the live account's stored slot when both are present."""
    h = rotator.build_oauth_health(
        ["live@x"], "live@x",
        {"live@x": _blob(refresh=False)},   # stale slot: no refresh
        set(), _blob(refresh=True),          # fresh live blob: refresh-capable
    )
    assert h["live@x"]["has_refresh"] is True


# ---------- cmd_oauth_health (read ORDER + latch-awareness, no live keychain) ----------

def test_cmd_oauth_health_already_latched_marks_all_latched_and_skips_live_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """When the store is ALREADY latched, every slot read short-circuits to None; the command
    labels each account "latched" (not "no oauth") AND skips the prompting live read entirely
    (fix #1 + fix #2). On the pre-#82 code the JSON carried no `status` and read has_refresh:false."""
    monkeypatch.setattr(rotator, "load_state", lambda: {"slots": {"a@x": {}, "b@x": {}}, "live_email": "a@x"})
    monkeypatch.setattr(rotator.safe_storage, "keychain_denied_latched", lambda: True)
    monkeypatch.setattr(rotator, "read_slot", lambda _e: None)  # real read_slot short-circuits while latched
    live_calls: list[int] = []

    def _record_live() -> None:
        # A named function, not `lambda: live_calls.append(1) or None`: `append` returns None,
        # so the `or` was reading a value-less call's result — harmless at runtime, but mypy
        # rejects it (func-returns-value) and gate 2 of publish.py runs mypy.
        live_calls.append(1)

    monkeypatch.setattr(rotator, "read_live_blob", _record_live)

    assert rotator.cmd_oauth_health(True) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["a@x"]["status"] == "latched"
    assert out["b@x"]["status"] == "latched"
    assert live_calls == [], "the flaky live read must be SKIPPED while latched (no prompt risk)"


def test_cmd_oauth_health_live_hang_does_not_erase_slot_truth(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A live-credential read that HANGS and trips the machine-wide latch no longer zeroes the
    per-account truth: the slots are read FIRST, so both accounts keep real data and the flaky
    live read runs LAST (fix #2). On the pre-#82 code the live read ran first, latched, and both
    accounts came back zeroed with no `status` key."""
    monkeypatch.setattr(rotator, "load_state", lambda: {"slots": {"a@x": {}, "b@x": {}}, "live_email": "a@x"})
    latch = {"set": False}
    monkeypatch.setattr(rotator.safe_storage, "keychain_denied_latched", lambda: latch["set"])
    order: list[tuple] = []

    def _slot(email: str) -> dict | None:
        order.append(("slot", email))
        if latch["set"]:
            return None  # faithful: a real slot read short-circuits once the latch is set
        return _blob(refresh=True)

    def _live() -> dict | None:
        order.append(("live",))
        latch["set"] = True  # the flaky app-owned live read trips the machine-wide latch
        return None

    monkeypatch.setattr(rotator, "read_slot", _slot)
    monkeypatch.setattr(rotator, "read_live_blob", _live)

    assert rotator.cmd_oauth_health(True) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["a@x"]["status"] == "ok" and out["a@x"]["has_refresh"] is True
    assert out["b@x"]["status"] == "ok" and out["b@x"]["has_refresh"] is True
    assert order[-1] == ("live",), "the flaky live read must run LAST, after every slot"
    assert order.count(("live",)) == 1


# ---------- lifetime-status.sh end-to-end (the shipped shell decision logic) ----------

def _run_lifetime_status(tmp_path: Path, health: dict) -> subprocess.CompletedProcess:
    """Run the shipped lifetime-status.sh against a STUB engine returning `health` for
    `oauth-health --json`. The stub replaces only the DATA SOURCE, not the logic under test."""
    stub = tmp_path / "stub_rotator.py"
    # Embed the health dict as a PYTHON literal (repr — True/False/None), then json.dumps it
    # at stub runtime. Embedding json.dumps() output directly would inject `false`/`null`,
    # which are not valid Python and would make the stub error to empty stdout.
    stub.write_text(textwrap.dedent(
        """\
        import json, sys
        a = sys.argv[1:]
        if a and a[0] == "print-profiles-root":
            print("/tmp/does-not-exist-janitor82-profiles")
        elif a and a[0] == "oauth-health":
            print(json.dumps(%s))
        """ % repr(health)
    ))
    rot_home = tmp_path / "rot"
    rot_home.mkdir()
    # Run a COPY inside tmp_path, never the in-tree script. `tests/sandbox_guard.py` refuses
    # to spawn a real shell script from the repo, and it is right to: the script's own children
    # (`security`, `launchctl`, …) are invisible to the guard, so an in-tree run would silently
    # escape the sandbox this suite relies on. The copy is byte-identical, so the LOGIC under
    # test is still the shipped one — and the script resolves `rotator.py` from `$0` only as a
    # default, which CLAUDE_ROTATOR_PY overrides here, so relocating it changes nothing.
    script = tmp_path / "lifetime-status.sh"
    script.write_bytes(_LIFETIME_STATUS.read_bytes())
    env = dict(os.environ)
    env.pop("CLAUDE_ROTATOR_PROFILES", None)   # hermetic: don't let a real profiles dir leak in
    env.pop("CLAUDE_PLUGIN_DATA", None)
    env["CLAUDE_ROTATOR_HOME"] = str(rot_home)
    env["CLAUDE_ROTATOR_PY"] = str(stub)
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, env=env,
    )


def test_lifetime_status_shows_latched_not_no_oauth(tmp_path: Path) -> None:
    """Given a latched-state health JSON, the shipped lifetime-status.sh prints "latched" in the
    OAuth column and the "denied-latch" note — never the pre-#82 "no oauth" nor a false
    "URGENT: no account has healthy OAuth" banner (fix #1)."""
    r = _run_lifetime_status(
        tmp_path,
        {"acct@example.com": {"has_refresh": False, "expires_days": None, "expires_at": None, "status": "latched"}},
    )
    out = r.stdout
    assert "latched" in out, out
    assert "no oauth" not in out, out
    assert "URGENT: no account has healthy OAuth" not in out, out
    assert "denied-latch" in out, out
