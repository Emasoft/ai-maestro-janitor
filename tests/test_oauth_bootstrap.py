"""Tests for the post-login auto-bootstrap in rotator.py (Part B, TRDD-32acd15f).

`_bootstrap_seeded_slots()` LAUNCHES a detached slot_capture_browser for every
account that was SEEDED by a human login (a live claude.ai Chrome session) but
cannot yet self-renew (no refreshToken). The capture runs DETACHED (fire-and-
forget) so it never blocks / starves the 60 s rotation tick; success is observed
on a LATER tick when the slot gains a refreshToken (audit §2).

All real, NO mocks of the code under test:
  * `_bootstrap_eligible` is a pure fn, called directly.
  * `_bootstrap_seeded_slots`: real tmp state.json + real fake Chrome Cookies
    sqlite files drive the session-key check; `read_slot` returns hand-built
    blobs; ONLY the external `slot_capture_browser` LAUNCH is monkeypatched
    to a recorder — so NO browser launches, NO network, NO keychain is touched.
  * `_invoke_slot_capture` mechanics (the uv-run/headful/detached/PID-lock launch
    contract) are tested with subprocess.Popen monkeypatched to a recorder fake,
    so the real argv + detach flags + lockfile are asserted with no process spawn.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROTATOR_PY = _HERE.parent / "scripts" / "oauth_rotator" / "rotator.py"
_EPOCH_OFFSET = 11644473600  # seconds between 1601-01-01 and 1970-01-01


def _load_rotator():
    """Import rotator.py by path (it lives outside any package)."""
    spec = importlib.util.spec_from_file_location("rotator_bootstrap_under_test", _ROTATOR_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rotator = _load_rotator()


def _blob(token: str, *, refresh: str | None) -> dict:
    inner: dict = {"accessToken": token}
    if refresh is not None:
        inner["refreshToken"] = refresh
    return {"claudeAiOauth": inner}


def _make_session(profiles_root: Path, email: str, expiry_days: float | None) -> None:
    """Write a fake Chrome Cookies sqlite for `chrome-profile-<email>`.

    expiry_days None → no Cookies file (no seeded session). Negative → expired.
    """
    if expiry_days is None:
        return
    default = profiles_root / f"chrome-profile-{email}" / "Default"
    default.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(default / "Cookies")
    con.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, expires_utc INTEGER)")
    exp = int((time.time() + expiry_days * 86400 + _EPOCH_OFFSET) * 1_000_000)
    con.execute("INSERT INTO cookies VALUES (?, ?, ?)", ("claude.ai", "sessionKey", exp))
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# PURE eligibility truth table.
# ---------------------------------------------------------------------------
def test_bootstrap_eligible_only_no_refresh_with_session() -> None:
    """Eligible iff it CANNOT self-renew (no refresh) AND HAS a live session to mint from."""
    assert rotator._bootstrap_eligible(False, True) is True
    assert rotator._bootstrap_eligible(False, False) is False  # nothing to mint from
    assert rotator._bootstrap_eligible(True, True) is False    # already self-renews
    assert rotator._bootstrap_eligible(True, False) is False


# ---------------------------------------------------------------------------
# _bootstrap_seeded_slots integration — only the browser subprocess is faked.
# ---------------------------------------------------------------------------
def _wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    slots: dict[str, dict],
) -> list[str]:
    """slots maps email -> {"refresh": str|None, "session": float|None}. Builds
    tmp state.json + fake Cookies, faked read_slot, and a recording stand-in for
    the slot_capture_browser invocation. Returns the recorder list of bootstrapped
    emails the fake "captured"."""
    root = tmp_path / "root"
    (root / "slots").mkdir(parents=True, exist_ok=True)
    profiles = root / "profiles"
    monkeypatch.setattr(rotator, "ROOT", root)
    monkeypatch.setattr(rotator, "SLOTS", root / "slots")
    monkeypatch.setattr(rotator, "STATE_FILE", root / "state.json")
    rotator.save_state({"live_email": None, "live_fp": None,
                        "slots": {e: {} for e in slots}})

    blobs = {e: _blob(e.split("@", 1)[0].upper(), refresh=spec["refresh"])
             for e, spec in slots.items()}
    monkeypatch.setattr(rotator, "read_slot", lambda e: blobs.get(e))
    for email, spec in slots.items():
        _make_session(profiles, email, spec["session"])

    captured: list[str] = []
    # The ONLY external dependency we stub: the detached browser LAUNCH. A real call
    # would Popen Playwright Chrome + hit the OAuth endpoint — forbidden in tests.
    # Returning True models "a capture was LAUNCHED for this email" (the launch contract).
    monkeypatch.setattr(rotator, "_invoke_slot_capture",
                        lambda email: captured.append(email) or True)
    return captured


def test_bootstraps_only_seeded_no_refresh_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Three slots: no-refresh+session (bootstrap), no-refresh+no-session (skip — nothing
    to mint from), has-refresh+session (skip — already self-renews). Only the first is captured."""
    captured = _wire(
        tmp_path,
        monkeypatch,
        {
            "seeded@x.com": {"refresh": None, "session": 20.0},
            "orphan@x.com": {"refresh": None, "session": None},
            "healthy@x.com": {"refresh": "r", "session": 20.0},
        },
    )
    done = rotator._bootstrap_seeded_slots()
    assert captured == ["seeded@x.com"]
    assert done == ["seeded@x.com"]


def test_expired_session_is_not_bootstrappable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An EXPIRED claude.ai session has no live sessionKey to mint a refresh from → skip."""
    captured = _wire(
        tmp_path,
        monkeypatch,
        {"stale@x.com": {"refresh": None, "session": -3.0}},
    )
    done = rotator._bootstrap_seeded_slots()
    assert captured == []
    assert done == []


def test_no_eligible_slots_invokes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All slots self-renew → the browser subprocess is never invoked."""
    captured = _wire(
        tmp_path,
        monkeypatch,
        {
            "a@x.com": {"refresh": "r", "session": 20.0},
            "b@x.com": {"refresh": "r", "session": None},
        },
    )
    done = rotator._bootstrap_seeded_slots()
    assert captured == []
    assert done == []


def test_bootstrap_never_raises_on_capture_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing/raising capture is best-effort: it is logged + skipped, never propagated,
    and a LATER eligible slot is still attempted."""
    root = tmp_path / "root"
    (root / "slots").mkdir(parents=True, exist_ok=True)
    profiles = root / "profiles"
    monkeypatch.setattr(rotator, "ROOT", root)
    monkeypatch.setattr(rotator, "SLOTS", root / "slots")
    monkeypatch.setattr(rotator, "STATE_FILE", root / "state.json")
    emails = ["boom@x.com", "ok@x.com"]
    rotator.save_state({"live_email": None, "live_fp": None, "slots": {e: {} for e in emails}})
    blobs = {e: _blob(e.split("@", 1)[0].upper(), refresh=None) for e in emails}
    monkeypatch.setattr(rotator, "read_slot", lambda e: blobs.get(e))
    for e in emails:
        _make_session(profiles, e, 20.0)

    attempted: list[str] = []

    def _capture(email: str) -> bool:
        attempted.append(email)
        if email == "boom@x.com":
            raise RuntimeError("playwright blew up")
        return True

    monkeypatch.setattr(rotator, "_invoke_slot_capture", _capture)
    done = rotator._bootstrap_seeded_slots()  # must NOT raise
    assert set(attempted) == {"boom@x.com", "ok@x.com"}  # the failure didn't abort the loop
    assert done == ["ok@x.com"]                          # only the successful one counts


def test_bootstrap_uses_profiles_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The profiles root honours CLAUDE_ROTATOR_PROFILES (mirrors open-login.sh /
    slot_capture_browser), not just <ROOT>/profiles."""
    root = tmp_path / "root"
    (root / "slots").mkdir(parents=True, exist_ok=True)
    alt_profiles = tmp_path / "elsewhere" / "profiles"
    monkeypatch.setattr(rotator, "ROOT", root)
    monkeypatch.setattr(rotator, "SLOTS", root / "slots")
    monkeypatch.setattr(rotator, "STATE_FILE", root / "state.json")
    monkeypatch.setenv("CLAUDE_ROTATOR_PROFILES", str(alt_profiles))
    rotator.save_state({"live_email": None, "live_fp": None, "slots": {"e@x.com": {}}})
    monkeypatch.setattr(rotator, "read_slot", lambda _: _blob("E", refresh=None))
    _make_session(alt_profiles, "e@x.com", 20.0)  # session lives under the OVERRIDE root
    captured: list[str] = []
    monkeypatch.setattr(rotator, "_invoke_slot_capture",
                        lambda email: captured.append(email) or True)
    done = rotator._bootstrap_seeded_slots()
    assert captured == ["e@x.com"]
    assert done == ["e@x.com"]


# ---------------------------------------------------------------------------
# _invoke_slot_capture LAUNCH mechanics (B1+B2). subprocess.Popen is faked to a
# recorder so the real argv / detach flags / PID lockfile are asserted with NO
# process spawned, NO browser, NO network, NO keychain.
# ---------------------------------------------------------------------------
class _FakePopen:
    """Records the launch and exposes a .pid, standing in for a detached child."""

    calls: list[dict] = []

    def __init__(self, argv, **kwargs):  # type: ignore[no-untyped-def]
        # Drain a file-object kwarg (the logfile) so the test doesn't leak an fd —
        # the real Popen would dup it; we just note that one was passed.
        _FakePopen.calls.append({"argv": list(argv), "kwargs": kwargs})
        self.pid = 424242

    def poll(self):  # pragma: no cover - never inspected in these tests
        return None


def _fake_popen_factory():
    _FakePopen.calls = []
    return _FakePopen


def _capture_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point rotator.ROOT at a tmp dir and install the Popen recorder."""
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rotator, "ROOT", root)
    monkeypatch.setattr(rotator.subprocess, "Popen", _fake_popen_factory())
    return root


def test_invoke_slot_capture_launches_uv_run_headful_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1: the capture is launched via `uv run --with playwright python <script> <email>`
    (so Playwright is provisioned) and HEADFUL by default — NO `--headless` unless the env
    flag is set. The launch returns True (a capture was launched)."""
    _capture_root(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDE_ROTATOR_BOOTSTRAP_HEADLESS", raising=False)
    assert rotator._invoke_slot_capture("seed@x.com") is True
    assert len(_FakePopen.calls) == 1
    argv = _FakePopen.calls[0]["argv"]
    assert argv[:5] == ["uv", "run", "--with", "playwright", "python"]
    assert argv[5].endswith("slot_capture_browser.py")
    assert argv[6] == "seed@x.com"
    assert "--headless" not in argv          # HEADFUL by default — the tested-working mode


def test_invoke_slot_capture_headless_only_when_env_truthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1: `--headless` is appended ONLY when CLAUDE_ROTATOR_BOOTSTRAP_HEADLESS is truthy."""
    _capture_root(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDE_ROTATOR_BOOTSTRAP_HEADLESS", "1")
    assert rotator._invoke_slot_capture("seed@x.com") is True
    assert _FakePopen.calls[0]["argv"][-1] == "--headless"
    # A falsey value stays headful.
    monkeypatch.setenv("CLAUDE_ROTATOR_BOOTSTRAP_HEADLESS", "0")
    rotator._bootstrap_pid_path("seed@x.com").unlink(missing_ok=True)  # clear the lock
    assert rotator._invoke_slot_capture("seed@x.com") is True
    assert "--headless" not in _FakePopen.calls[-1]["argv"]


def test_invoke_slot_capture_is_detached_and_writes_pidfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B2: the launch is DETACHED (start_new_session=True, no stdin, log redirected) and a
    per-email PID lockfile is written with the child's pid."""
    _capture_root(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDE_ROTATOR_BOOTSTRAP_HEADLESS", raising=False)
    assert rotator._invoke_slot_capture("seed@x.com") is True
    kw = _FakePopen.calls[0]["kwargs"]
    assert kw["start_new_session"] is True             # own session — survives daemon SIGHUP
    assert kw["stdin"] is rotator.subprocess.DEVNULL   # no inherited stdin
    assert kw["stderr"] is rotator.subprocess.STDOUT   # stderr folded into the logfile
    pid_path = rotator._bootstrap_pid_path("seed@x.com")
    assert pid_path.is_file()
    assert pid_path.read_text().strip() == "424242"    # the launched child's pid


def test_invoke_slot_capture_skips_if_prior_capture_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B2: the PID lock is skip-if-running — when a prior capture for the email is still
    alive, the launch is SKIPPED (returns False) and Popen is NOT called a second time. The
    janitor's detached-PID-worker contract: a slow capture is launched once, not every tick."""
    _capture_root(tmp_path, monkeypatch)
    # Seed a live PID (our own process) into the lockfile → "a capture is already running".
    pid_path = rotator._bootstrap_pid_path("seed@x.com")
    pid_path.write_text(str(os.getpid()), encoding="utf-8")
    assert rotator._invoke_slot_capture("seed@x.com") is False
    assert _FakePopen.calls == []                       # no second launch while one is alive


def test_invoke_slot_capture_relaunches_when_prior_pid_dead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B2: a STALE lockfile (the prior capture already exited) does not block a fresh launch
    — a dead recorded PID is treated as 'no live worker'."""
    _capture_root(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDE_ROTATOR_BOOTSTRAP_HEADLESS", raising=False)
    # PID 999999 is essentially guaranteed not to exist → stale lock.
    rotator._bootstrap_pid_path("seed@x.com").write_text("999999", encoding="utf-8")
    assert rotator._invoke_slot_capture("seed@x.com") is True
    assert len(_FakePopen.calls) == 1                   # relaunched past the stale lock


def test_invoke_slot_capture_inherits_env_keeps_plugin_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1: the child INHERITS the current env — CLAUDE_PLUGIN_DATA is NOT stripped (so the
    capture resolves the SAME rotator ROOT the daemon did). The recorder proves Popen was
    called with no `env=` override (None → inherit) while CLAUDE_PLUGIN_DATA is set."""
    _capture_root(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "plugin-data"))
    assert rotator._invoke_slot_capture("seed@x.com") is True
    kw = _FakePopen.calls[0]["kwargs"]
    # env not passed → Popen inherits os.environ verbatim (the whole point).
    assert kw.get("env") is None
    assert os.environ.get("CLAUDE_PLUGIN_DATA") == str(tmp_path / "plugin-data")


def test_cmd_tick_runs_bootstrap_after_cmd_auto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B2: in cmd_tick the bootstrap runs AFTER cmd_auto so usage-based rotation (which keeps
    the session alive overnight) is never starved by a bootstrap launch. Order is asserted by
    recording the call sequence; all tick steps are stubbed to no-ops."""
    order: list[str] = []
    monkeypatch.setattr(rotator, "claude_running", lambda: True)
    # Isolate the cascade-visibility log so this order test touches NO real keychain/state/log
    # (_log_cascade_plan does real keychain+state reads + a real _log write — TRDD-dfc0959a).
    monkeypatch.setattr(rotator, "_log_cascade_plan", lambda: order.append("cascade-log"))
    monkeypatch.setattr(rotator, "migrate_root_to_canonical", lambda: order.append("migrate"))
    monkeypatch.setattr(rotator, "_keepalive_refresh", lambda: order.append("keepalive"))
    monkeypatch.setattr(rotator, "_repair_integrity", lambda: order.append("repair"))
    monkeypatch.setattr(rotator, "cmd_capture", lambda _b: order.append("capture") or 0)
    monkeypatch.setattr(rotator, "cmd_auto", lambda: order.append("auto") or 0)
    monkeypatch.setattr(rotator, "_bootstrap_seeded_slots", lambda: order.append("bootstrap"))
    rc = rotator.cmd_tick(only_if_running=True)
    assert rc == 0
    assert order.index("bootstrap") > order.index("auto"), \
        "bootstrap must run AFTER cmd_auto so rotation is never starved"
