"""Tests for the cross-platform safe_storage abstraction (scripts/oauth_rotator/safe_storage.py).

Real, no mocks of the code under test:
  * backend selection (env override + platform/tool detection),
  * argv construction (pure builders — asserted without executing),
  * fail-closed write semantics (a present-but-failing store → FAILED, not NO_BACKEND),
  * a REAL OS-keychain round-trip with a MULTI-KILOBYTE secret — the regression guard
    for the 128-byte getpass truncation bug (TRDD-5539cd6e) that cookies would re-trip.
The round-trip test uses a throwaway TEST service (PID-scoped) and deletes it in a
finally, so it never touches production keychain items.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scripts" / "oauth_rotator"))

import safe_storage as ss  # noqa: E402

_TEST_SERVICE = "ai-maestro-janitor-safe-storage-TEST-%d" % os.getpid()


def _real_macos_keychain() -> bool:
    """True iff this box has a usable macOS `security` keychain (for the real round-trip)."""
    if platform.system() != "Darwin":
        return False
    from shutil import which
    return which("security") is not None


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------
def test_detect_backend_honors_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLAUDE_SAFE_STORAGE_BACKEND forces the backend (tests / explicit choice)."""
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "secret_tool")
    assert ss.detect_backend() == "secret_tool"
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "none")
    assert ss.detect_backend() == "none"


def test_detect_backend_macos_when_security_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Darwin with `security` on PATH → macos backend."""
    monkeypatch.delenv("CLAUDE_SAFE_STORAGE_BACKEND", raising=False)
    monkeypatch.setattr(ss.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ss, "_which", lambda t: t == "security")
    assert ss.detect_backend() == "macos"


def test_detect_backend_linux_when_secret_tool_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Linux with secret-tool on PATH → secret_tool backend."""
    monkeypatch.delenv("CLAUDE_SAFE_STORAGE_BACKEND", raising=False)
    monkeypatch.setattr(ss.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ss, "_which", lambda t: t == "secret-tool")
    assert ss.detect_backend() == "secret_tool"


def test_detect_backend_windows_when_powershell_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Windows with powershell on PATH → dpapi backend."""
    monkeypatch.delenv("CLAUDE_SAFE_STORAGE_BACKEND", raising=False)
    monkeypatch.setattr(ss.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ss, "_which", lambda t: t == "powershell")
    assert ss.detect_backend() == "dpapi"


def test_detect_backend_none_when_no_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """A box with no secret-store CLI resolves to 'none' (not a backend that always fails)."""
    monkeypatch.delenv("CLAUDE_SAFE_STORAGE_BACKEND", raising=False)
    monkeypatch.setattr(ss.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ss, "_which", lambda t: False)
    assert ss.detect_backend() == "none"


# ---------------------------------------------------------------------------
# argv construction (pure)
# ---------------------------------------------------------------------------
def test_macos_store_argv_puts_value_on_argv_not_stdin() -> None:
    """The macOS store argv carries the secret as the `-w <value>` arg — the 128-byte
    getpass stdin form is NOT used (TRDD-5539cd6e)."""
    argv = ss.macos_store_argv("svc", "acct", "the-secret-value")
    assert argv[:2] == ["security", "add-generic-password"]
    assert "-U" in argv                      # update existing
    assert "-w" in argv and "the-secret-value" in argv
    assert argv[argv.index("-w") + 1] == "the-secret-value"  # value immediately after -w


def test_secret_tool_argv_shapes() -> None:
    """secret-tool store/lookup/clear argv use service+account attributes (value via stdin)."""
    assert ss.secret_tool_store_argv("svc", "a@x")[:2] == ["secret-tool", "store"]
    assert ss.secret_tool_retrieve_argv("svc", "a@x") == \
        ["secret-tool", "lookup", "service", "svc", "account", "a@x"]
    assert ss.secret_tool_delete_argv("svc", "a@x") == \
        ["secret-tool", "clear", "service", "svc", "account", "a@x"]


# ---------------------------------------------------------------------------
# Fail-closed write semantics (no real keychain — drive the macOS path with a stub)
# ---------------------------------------------------------------------------
def test_store_no_backend_returns_NO_BACKEND(monkeypatch: pytest.MonkeyPatch) -> None:
    """No secret store present → NO_BACKEND so the caller may use its documented fallback."""
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "none")
    assert ss.store("svc", "acct", "x") is ss.StoreResult.NO_BACKEND


def test_store_failed_when_macos_cli_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PRESENT-but-failing keychain (locked/declined → rc!=0) returns FAILED, NOT
    NO_BACKEND — the caller MUST fail closed and never drop a plaintext fallback."""
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "macos")

    class _R:
        returncode = 1
        stdout = ""
        stderr = ""  # run_security reads proc.stdout + proc.stderr (Safe Keychain Protocol, TRDD-K3WQ7XM9)
    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: _R())
    assert ss.store("svc", "acct", "x") is ss.StoreResult.FAILED


def test_store_failed_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hung keychain prompt (TimeoutExpired) fails closed (FAILED), never hangs the daemon."""
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "macos")

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="security", timeout=ss._CLI_TIMEOUT_S)
    monkeypatch.setattr(ss.subprocess, "run", _boom)
    assert ss.store("svc", "acct", "x") is ss.StoreResult.FAILED


def test_store_no_backend_when_security_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """macos backend selected but `security` missing (FileNotFoundError) → NO_BACKEND."""
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "macos")

    def _missing(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(ss.subprocess, "run", _missing)
    assert ss.store("svc", "acct", "x") is ss.StoreResult.NO_BACKEND


def test_retrieve_absent_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """retrieve on a no-backend box returns None (not an exception)."""
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "none")
    assert ss.retrieve("svc", "acct") is None


def test_retrieve_non_base64_is_failsafe_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stored value that is NOT our base64 wrapping (corrupt, or written by something
    else) decodes to None — fail-safe, never a garbled string."""
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "macos")

    class _R:
        returncode = 0
        stdout = "this is not base64 !!!\n"
        stderr = ""  # run_security reads proc.stderr (Safe Keychain Protocol)
    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: _R())
    assert ss.retrieve("svc", "acct") is None


def test_retrieve_unwraps_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    """retrieve base64-decodes what the backend returns — the inverse of store's wrap."""
    import base64 as _b64
    monkeypatch.setenv("CLAUDE_SAFE_STORAGE_BACKEND", "macos")
    wrapped = _b64.b64encode("hello cookie jar 🦝".encode()).decode("ascii")

    class _R:
        returncode = 0
        stdout = wrapped + "\n"  # security appends a trailing newline
        stderr = ""  # run_security reads proc.stderr (Safe Keychain Protocol)
    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: _R())
    assert ss.retrieve("svc", "acct") == "hello cookie jar 🦝"


# ---------------------------------------------------------------------------
# REAL macOS keychain round-trip — the 128-byte truncation regression guard.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _real_macos_keychain(), reason="needs a real macOS `security` keychain")
def test_macos_roundtrip_multi_kilobyte_secret(isolated_keychain) -> None:  # isolated temp keychain — NEVER the login keychain (TRDD-K3WQ7XM9 FIX B)
    """REGRESSION GUARD (TRDD-5539cd6e): a multi-KB secret (a realistic cookie jar) must
    round-trip through the real keychain BYTE-FOR-BYTE — proving the 128-byte getpass
    truncation is gone. Uses a throwaway PID-scoped TEST service; deletes it after."""
    monkeypatch_env = os.environ.pop("CLAUDE_SAFE_STORAGE_BACKEND", None)
    big = '{"cookies":[' + ",".join('{"name":"c%d","value":"%s"}' % (i, "v" * 50)
                                    for i in range(120)) + "]}"
    assert len(big) > 4000, "fixture must exceed the 128-byte getpass buffer by a wide margin"
    try:
        res = ss.store(_TEST_SERVICE, "roundtrip@x.com", big)
        assert res is ss.StoreResult.OK, f"store failed: {res}"
        got = ss.retrieve(_TEST_SERVICE, "roundtrip@x.com")
        assert got == big, (
            "round-trip corrupted the secret: stored %d bytes, read back %s bytes"
            % (len(big), "None" if got is None else len(got))
        )
    finally:
        ss.delete(_TEST_SERVICE, "roundtrip@x.com")
        if monkeypatch_env is not None:
            os.environ["CLAUDE_SAFE_STORAGE_BACKEND"] = monkeypatch_env
    # After delete, retrieve must be None.
    assert ss.retrieve(_TEST_SERVICE, "roundtrip@x.com") is None


@pytest.mark.skipif(not _real_macos_keychain(), reason="needs a real macOS `security` keychain")
def test_macos_roundtrip_preserves_special_chars(isolated_keychain) -> None:  # isolated temp keychain (TRDD-K3WQ7XM9 FIX B)
    """A secret with newlines / quotes / unicode round-trips intact (interior whitespace
    is preserved; only the trailing newline `security -w` adds is stripped)."""
    secret = 'line1\nline2 "quoted" \t café 🦝 end'
    try:
        assert ss.store(_TEST_SERVICE, "special@x.com", secret) is ss.StoreResult.OK
        assert ss.retrieve(_TEST_SERVICE, "special@x.com") == secret
    finally:
        ss.delete(_TEST_SERVICE, "special@x.com")


@pytest.mark.skipif(not _real_macos_keychain(), reason="needs a real macOS `security` keychain")
def test_macos_delete_is_idempotent(isolated_keychain) -> None:  # isolated temp keychain (TRDD-K3WQ7XM9 FIX B)
    """delete on an absent item is a no-op (never raises); retrieve then returns None."""
    ss.delete(_TEST_SERVICE, "ghost@x.com")  # never stored
    ss.delete(_TEST_SERVICE, "ghost@x.com")  # again — still fine
    assert ss.retrieve(_TEST_SERVICE, "ghost@x.com") is None


# ---------------------------------------------------------------------------
# THE SAFE KEYCHAIN PROTOCOL (TRDD-K3WQ7XM9 P1) — the choke-point + denied-latch.
# ---------------------------------------------------------------------------
def test_run_security_latch_short_circuits_without_spawning(monkeypatch: pytest.MonkeyPatch) -> None:
    """(P1.b) Once the denied-latch is set, run_security returns spawned=False + denied=True
    WITHOUT launching `security` — so a latched state can NEVER prompt again (asserts zero
    spawn by pointing subprocess.run at a landmine a real spawn would trip)."""
    ss.clear_keychain_denied()

    def _landmine(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("run_security spawned `security` while the latch was set")
    monkeypatch.setattr(ss.subprocess, "run", _landmine)
    ss.set_keychain_denied("test-trip")
    assert ss.keychain_denied_latched() is True
    run = ss.run_security(["security", "find-generic-password", "-s", "x", "-a", "y", "-w"])
    assert run.spawned is False and run.denied is True and run.ok is False
    assert ss.clear_keychain_denied() is True  # and the human clear-path removes it


def test_run_security_timeout_trips_the_latch(monkeypatch: pytest.MonkeyPatch) -> None:
    """(P1.a/d) A real TimeoutExpired from the `security` subprocess bounds the call AND trips
    the persistent latch — the flood-stopping trigger (a hung `-w` read can recur at most once)."""
    ss.clear_keychain_denied()

    def _boom(*a, **k):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd="security", timeout=1)
    monkeypatch.setattr(ss.subprocess, "run", _boom)
    run = ss.run_security(["security", "find-generic-password", "-s", "x", "-a", "y", "-w"], timeout=1)
    assert run.denied is True and run.spawned is True
    assert ss.keychain_denied_latched() is True
    ss.clear_keychain_denied()


def test_run_security_latches_on_denial_not_on_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """(P1.d) A narrow ACL/auth denial marker (errSecAuthFailed) latches; a benign
    'could not be found' does NOT (a normal not-found must never latch + deny everything)."""
    ss.clear_keychain_denied()

    class _Denied:
        returncode = 51
        stdout = ""
        stderr = "SecKeychain: errSecAuthFailed / -25293 authorization denied"
    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: _Denied())
    run = ss.run_security(["security", "find-generic-password", "-s", "x", "-a", "y", "-w"])
    assert run.denied is True and ss.keychain_denied_latched() is True

    ss.clear_keychain_denied()

    class _NotFound:
        returncode = 44
        stdout = ""
        stderr = "security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain."
    monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: _NotFound())
    run = ss.run_security(["security", "find-generic-password", "-s", "x", "-a", "y", "-w"])
    assert run.denied is False and ss.keychain_denied_latched() is False


def test_keychain_scope_args_confines_to_the_env_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    """(P1.iv) The scope lever appends the JANITOR_ROTATOR_KEYCHAIN path so EVERY op is confined
    to that keychain; empty when unset (production → login keychain, argv unchanged)."""
    monkeypatch.setenv("JANITOR_ROTATOR_KEYCHAIN", "/tmp/janitor/test.keychain-db")
    assert ss.keychain_scope_args() == ["/tmp/janitor/test.keychain-db"]
    assert ss.macos_retrieve_argv("svc", "acct")[-1] == "/tmp/janitor/test.keychain-db"
    monkeypatch.delenv("JANITOR_ROTATOR_KEYCHAIN", raising=False)
    assert ss.keychain_scope_args() == []
    assert ss.macos_retrieve_argv("svc", "acct")[-1] == "-w"  # base argv, no keychain scope
