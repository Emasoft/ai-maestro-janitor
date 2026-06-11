"""Tests for the migrated OAuth account rotator (scripts/oauth_rotator/rotator.py).

Covers the pure decision helpers (drain-first selection, near-limit / safe-alternate
gating, usage parsing, fingerprinting, expiry) plus the filesystem helpers (0600 slot
+ state round-trip) and a no-secret-in-repo guard. All real — no network, no keychain,
no mocks: pure helpers are called directly; filesystem helpers run against a tmp dir
via monkeypatched module paths.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROTATOR_PY = _HERE.parent / "scripts" / "oauth_rotator" / "rotator.py"


def _load_rotator():
    """Import rotator.py by path (it lives outside any package)."""
    spec = importlib.util.spec_from_file_location("rotator_under_test", _ROTATOR_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rotator = _load_rotator()


def _blob(token: str, *, refresh: str | None = "r", expires_ms: int | None = None) -> dict:
    inner: dict = {"accessToken": token}
    if refresh is not None:
        inner["refreshToken"] = refresh
    if expires_ms is not None:
        inner["expiresAt"] = expires_ms
    return {"claudeAiOauth": inner}


def test_fingerprint_deterministic_and_distinct() -> None:
    """fingerprint is a stable 16-hex digest of the accessToken; empty → ''."""
    a = rotator.fingerprint(_blob("token-AAA"))
    assert a == rotator.fingerprint(_blob("token-AAA"))  # deterministic
    assert a != rotator.fingerprint(_blob("token-BBB"))  # distinguishes tokens
    assert len(a) == 16 and all(c in "0123456789abcdef" for c in a)
    assert rotator.fingerprint(_blob("")) == ""  # no token → empty fp
    assert rotator.fingerprint({}) == ""


def test_switch_threshold_default_97() -> None:
    """The 2026-05-29 decision: SWITCH_AT defaults to 97 on BOTH windows."""
    assert rotator.SWITCH_AT_5H == float(os.environ.get("ROTATOR_SWITCH_AT_5H", "97"))
    assert rotator.SWITCH_AT_7D == float(os.environ.get("ROTATOR_SWITCH_AT_7D", "97"))
    if "ROTATOR_SWITCH_AT_5H" not in os.environ:
        assert rotator.SWITCH_AT_5H == 97.0
    if "ROTATOR_SWITCH_AT_7D" not in os.environ:
        assert rotator.SWITCH_AT_7D == 97.0


def test_is_near_limit_fires_at_threshold_either_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_near_limit trips at >=97 on EITHER window; below stays put; None is fail-safe."""
    monkeypatch.setattr(rotator, "SWITCH_AT_5H", 97.0)
    monkeypatch.setattr(rotator, "SWITCH_AT_7D", 97.0)
    assert rotator.is_near_limit(97.0, 10.0) is True   # 5h at threshold
    assert rotator.is_near_limit(10.0, 99.0) is True   # 7d over threshold
    assert rotator.is_near_limit(96.9, 96.9) is False  # both just below
    assert rotator.is_near_limit(None, 50.0) is False  # unknown 5h, low 7d
    assert rotator.is_near_limit(None, None) is False  # all unknown → never rotate


def test_is_safe_alternate_requires_below_safe_on_both(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_safe_alternate is True only when BOTH windows are below SAFE (90)."""
    monkeypatch.setattr(rotator, "SAFE_5H", 90.0)
    monkeypatch.setattr(rotator, "SAFE_7D", 90.0)
    assert rotator.is_safe_alternate(10.0, 10.0) is True
    assert rotator.is_safe_alternate(89.9, 89.9) is True
    assert rotator.is_safe_alternate(90.0, 10.0) is False  # 5h at SAFE → not safe
    assert rotator.is_safe_alternate(10.0, 95.0) is False  # 7d over SAFE → not safe


def test_select_drain_first_picks_closest_to_limit() -> None:
    """Drain-first: among healthy alternates pick the highest max(util_5h, util_7d)."""
    fresh: tuple[str, dict, float, float] = ("fresh@x", {"claudeAiOauth": {}}, 5.0, 8.0)
    midway: tuple[str, dict, float, float] = ("mid@x", {"claudeAiOauth": {}}, 60.0, 40.0)
    nearly: tuple[str, dict, float, float] = ("near@x", {"claudeAiOauth": {}}, 85.0, 20.0)
    chosen = rotator.select_drain_first([fresh, midway, nearly])
    assert chosen is not None and chosen[0] == "near@x"  # most-drained wins
    # 7d can be the tightest window, not just 5h:
    chosen2 = rotator.select_drain_first([fresh, ("z@x", {}, 10.0, 88.0)])
    assert chosen2 is not None and chosen2[0] == "z@x"
    assert rotator.select_drain_first([]) is None  # no candidates → None


def test_select_drain_first_stable_on_tie() -> None:
    """On an equal tightest-window utilisation, the first candidate wins (stable)."""
    first: tuple[str, dict, float, float] = ("first@x", {}, 50.0, 30.0)
    second: tuple[str, dict, float, float] = ("second@x", {}, 30.0, 50.0)  # same max() = 50
    chosen = rotator.select_drain_first([first, second])
    assert chosen is not None and chosen[0] == "first@x"


def test_util_parses_window_and_handles_garbage() -> None:
    """_util extracts a window's utilization; None for missing/garbage shapes."""
    usage = {"five_hour": {"utilization": 42}, "seven_day": {"utilization": 7.5}}
    assert rotator._util(usage, "five_hour") == 42.0
    assert rotator._util(usage, "seven_day") == 7.5
    assert rotator._util(usage, "missing_window") is None
    assert rotator._util({"five_hour": "not-a-dict"}, "five_hour") is None
    assert rotator._util(None, "five_hour") is None


def test_expires_in_h_handles_ms_and_seconds() -> None:
    """expires_in_h returns hours-until-expiry from a ms-epoch (and None when absent)."""
    in_two_h_ms = int((time.time() + 2 * 3600) * 1000)
    got = rotator.expires_in_h(_blob("t", expires_ms=in_two_h_ms))
    assert got is not None and 1.9 < got < 2.1
    assert rotator.expires_in_h(_blob("t", refresh=None)) is None  # no expiresAt


def test_write_slot_file_fallback_is_0600_and_roundtrips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With NO keychain present, write_slot files a 0600 slot read_slot round-trips (the Linux-no-keyring fallback)."""
    slots = tmp_path / "slots"
    slots.mkdir()
    monkeypatch.setattr(rotator, "SLOTS", slots)
    # Force the no-keychain branch so the test is deterministic on macOS too and never
    # touches the real keychain: pretend the keychain write fails / has nothing.
    monkeypatch.setattr(rotator, "_slot_keychain_write", lambda *_a, **_k: False)
    monkeypatch.setattr(rotator, "_slot_keychain_read", lambda *_a, **_k: None)
    blob = _blob("secret-token-value", expires_ms=123456789000)
    rotator.write_slot("a@x.com", blob)
    p = slots / "a@x.com.json"
    assert p.exists()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600  # owner-only — no token leak
    assert rotator.read_slot("a@x.com") == blob
    assert rotator.read_slot("nobody@x.com") is None


def test_slot_keychain_write_returns_sentinel_on_called_process_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """SECURITY (P1): `security` PRESENT but the write FAILS (CalledProcessError) must NOT be
    confused with `security` ABSENT (FileNotFoundError). The former returns the distinct
    KEYCHAIN_WRITE_FAILED sentinel (fail-closed); the latter returns plain False (off-mac, the
    Linux keyring / plaintext fallback is legitimate)."""
    # security present but the add fails (locked keychain, declined ACL, non-zero exit).
    def _raise_called(*_a, **_k):
        raise rotator.subprocess.CalledProcessError(1, ["security"])
    monkeypatch.setattr(rotator, "_security_add_password_via_stdin", _raise_called)
    res = rotator._slot_keychain_write("a@x.com", _blob("t"))
    assert res is rotator.KEYCHAIN_WRITE_FAILED         # distinct sentinel, NOT False
    assert res != False                                 # noqa: E712 — sentinel is not falsy-False

    # security ABSENT → FileNotFoundError → falls through to the Linux keyring, which is also
    # absent here → plain False (so the plaintext fallback is reachable off-mac).
    def _raise_notfound(*_a, **_k):
        raise FileNotFoundError("security")
    monkeypatch.setattr(rotator, "_security_add_password_via_stdin", _raise_notfound)
    monkeypatch.setattr(rotator.subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("secret-tool")))
    assert rotator._slot_keychain_write("a@x.com", _blob("t")) is False


def test_write_slot_fails_closed_on_keychain_write_error_no_plaintext(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SECURITY (P1): on a simulated-mac path where `security` is PRESENT but the keychain write
    FAILS, write_slot must FAIL CLOSED — it raises and does NOT drop a 0600 plaintext slot file
    (the exact regression the P4a migration + delete-plaintext-slots eliminated)."""
    slots = tmp_path / "slots"
    slots.mkdir()
    monkeypatch.setattr(rotator, "SLOTS", slots)
    # Keychain present-but-failing: the primary write returns the fail-closed sentinel.
    monkeypatch.setattr(rotator, "_slot_keychain_write",
                        lambda *a, **k: rotator.KEYCHAIN_WRITE_FAILED)
    with pytest.raises(rotator.SlotKeychainWriteError):
        rotator.write_slot("a@x.com", _blob("must-not-leak-to-disk"))
    # The whole point: NO plaintext token file was created on the mac path.
    assert not (slots / "a@x.com.json").exists()
    assert list(slots.glob("*.json")) == []


def test_cmd_tick_survives_fail_closed_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    """P1 fail-closed must NOT crash the unattended tick: a SlotKeychainWriteError from
    cmd_capture is swallowed (the live cred is safe; the slot just isn't mirrored this beat),
    and the tick still proceeds to cmd_auto. The standalone `capture` command still raises."""
    monkeypatch.setattr(rotator, "claude_running", lambda: True)
    monkeypatch.setattr(rotator, "migrate_root_to_canonical", lambda: None)
    # Isolate the side-effecting tick steps so the test touches NO real keychain/state/log:
    # _log_cascade_plan does real keychain+state reads + a real _log write (the daemon's
    # cascade-visibility line), and the except-block _log below also writes — both must be
    # neutered or this unit test leaks into the production rotator.log (TRDD-dfc0959a).
    monkeypatch.setattr(rotator, "_log_cascade_plan", lambda: None)
    monkeypatch.setattr(rotator, "_log", lambda _m: None)
    monkeypatch.setattr(rotator, "_keepalive_refresh", lambda: None)
    monkeypatch.setattr(rotator, "_repair_integrity", lambda: None)
    monkeypatch.setattr(rotator, "_bootstrap_seeded_slots", lambda: None)

    def _boom(_only: bool) -> int:
        raise rotator.SlotKeychainWriteError("keychain locked")
    monkeypatch.setattr(rotator, "cmd_capture", _boom)
    auto_ran: list[bool] = []
    monkeypatch.setattr(rotator, "cmd_auto", lambda: auto_ran.append(True) or 0)
    rc = rotator.cmd_tick(only_if_running=True)   # must NOT raise
    assert rc == 0
    assert auto_ran == [True], "cmd_auto must still run after a fail-closed capture"


def _isolate_slot_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point BOTH the primary and backup slot keychain services at throwaway names so a
    test never touches the production slot items (write_slot mirrors to both, Pillar 2)."""
    monkeypatch.setattr(rotator, "SLOT_KEYCHAIN_SERVICE", "Claude Code-rotator-slot-TEST-%d" % os.getpid())
    monkeypatch.setattr(rotator, "SLOT_BACKUP_KEYCHAIN_SERVICE", "Claude Code-rotator-slot-backup-TEST-%d" % os.getpid())


def _purge_slot_keychain(email: str) -> None:
    rotator._slot_keychain_delete(email)
    rotator._slot_keychain_delete(email, service=rotator.SLOT_BACKUP_KEYCHAIN_SERVICE)


def test_keychain_write_passes_data_as_argv_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """The keychain WRITE helper passes the secret as the argv `-w` VALUE, NOT via the
    stdin-prompt mode (TRDD-5539cd6e). The old bare-`-w` prompt mode read via getpass(),
    whose 128-byte buffer SILENTLY TRUNCATED every OAuth blob -> corrupt unreadable slots.
    The argv value is briefly `ps`-visible, but slot items are already `security`-readable
    by any process, so it adds no exposure. Spies on subprocess.run (no real keychain)."""
    # Fragmented so no contiguous credential literal sits in tracked source
    # (tests/README.md §"fragment-only"); reconstructs byte-identical for the assertion below.
    SECRET = '{"accessToken":"tok-' + '0123456789abcdef' + '","refreshToken":"R-' + 'secret"}'
    seen: dict = {}

    def _spy(argv, **kwargs):  # type: ignore[no-untyped-def]
        seen["argv"] = list(argv)
        seen["input"] = kwargs.get("input")

        class _R:
            returncode = 0
        return _R()

    monkeypatch.setattr(rotator.subprocess, "run", _spy)
    rotator._security_add_password_via_stdin("svc-test", "acct-test", SECRET)
    argv = seen["argv"]
    assert argv[:2] == ["security", "add-generic-password"]
    assert "-U" in argv                                   # update-if-exists (the hot path)
    assert argv[-2] == "-w" and argv[-1] == SECRET        # data is the argv -w VALUE, full + intact
    assert seen["input"] is None                          # NOT the truncating stdin-prompt mode


def test_keychain_write_roundtrips_real_keychain_over_128_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The keychain write stores the EXACT bytes in the real macOS keychain — including
    payloads well over 128 bytes (TRDD-5539cd6e REGRESSION LOCK). The old stdin-prompt mode
    truncated everything >128B to 128B of corrupt JSON; this asserts a realistic ~600B and a
    big ~9000B blob round-trip byte-for-byte. (The original test used an ~80B payload, which is
    UNDER the 128 limit — that is exactly why the truncation bug went unnoticed.) 🐌"""
    if sys.platform != "darwin":
        pytest.skip("real macOS keychain test")
    service = "Claude Code-rotator-wtest-%d" % os.getpid()
    account = "wtest-%d@example.test" % os.getpid()
    try:
        for tok_len in (40, 400, 8000):                  # blobs ~ 130B, ~600B, ~9000B
            blob = _blob("T" * tok_len, refresh="R" * tok_len, expires_ms=123456789000)
            data = json.dumps(blob, separators=(",", ":"))
            assert len(data) > 128                        # the sizes that the old path corrupted
            rotator._security_add_password_via_stdin(service, account, data)
            got = rotator._slot_keychain_read(account, service=service)
            assert got == blob, f"round-trip failed at data len={len(data)} (truncation?)"
    finally:
        rotator._slot_keychain_delete(account, service=service)
    assert rotator._slot_keychain_read(account, service=service) is None  # cleaned up


def test_write_slot_uses_keychain_when_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On a keychain host, write_slot stores the token ENCRYPTED in the keychain (NO plaintext file) and read_slot round-trips it. 🐌"""
    if sys.platform != "darwin":
        pytest.skip("real macOS keychain test")
    slots = tmp_path / "slots"
    slots.mkdir()
    monkeypatch.setattr(rotator, "SLOTS", slots)
    _isolate_slot_keychain(monkeypatch)
    email = "kc-test-%d@example.test" % os.getpid()
    blob = _blob("keychain-secret-token", expires_ms=123456789000)
    try:
        rotator.write_slot(email, blob)
        assert not (slots / (email + ".json")).exists()  # the whole point of P4a: no plaintext file
        assert rotator.read_slot(email) == blob          # served back from the keychain
    finally:
        _purge_slot_keychain(email)
    assert rotator.read_slot(email) is None              # gone after cleanup


def test_read_slot_recovers_from_backup_when_primary_deleted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the PRIMARY slot keychain item is deleted/corrupt, read_slot recovers the token from the redundant backup keychain and re-heals the primary (Pillar 2, Decision 2). 🐌"""
    if sys.platform != "darwin":
        pytest.skip("real macOS keychain test")
    slots = tmp_path / "slots"
    slots.mkdir()
    monkeypatch.setattr(rotator, "SLOTS", slots)
    _isolate_slot_keychain(monkeypatch)
    email = "bak-test-%d@example.test" % os.getpid()
    blob = _blob("mirror-secret-token", expires_ms=123456789000)
    try:
        rotator.write_slot(email, blob)                  # writes primary + backup mirror
        # Simulate someone deleting the PRIMARY keychain item (e.g. via Keychain Access).
        rotator._slot_keychain_delete(email)
        assert rotator._slot_keychain_read(email) is None  # primary gone
        assert rotator._slot_keychain_read(email, service=rotator.SLOT_BACKUP_KEYCHAIN_SERVICE) == blob
        # read_slot transparently recovers from the backup AND re-heals the primary.
        assert rotator.read_slot(email) == blob
        assert rotator._slot_keychain_read(email) == blob  # primary re-healed
    finally:
        _purge_slot_keychain(email)


def test_migrate_slots_to_keychain_verifies_and_keeps_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """migrate_slots_to_keychain copies each legacy plaintext slot into the keychain, verifies by fingerprint, and keeps the files. 🐌"""
    if sys.platform != "darwin":
        pytest.skip("real macOS keychain test")
    slots = tmp_path / "slots"
    slots.mkdir()
    monkeypatch.setattr(rotator, "SLOTS", slots)
    monkeypatch.setattr(rotator, "SLOT_KEYCHAIN_SERVICE", "Claude Code-rotator-slot-TEST-%d" % os.getpid())
    ea = "mig-a-%d@example.test" % os.getpid()
    eb = "mig-b-%d@example.test" % os.getpid()
    a, b = _blob("tok-a"), _blob("tok-b")
    (slots / (ea + ".json")).write_text(json.dumps(a))
    (slots / (eb + ".json")).write_text(json.dumps(b))
    try:
        res = dict(rotator.migrate_slots_to_keychain())
        assert res == {ea: True, eb: True}              # both verified by fingerprint
        assert (slots / (ea + ".json")).exists()        # migration must NOT delete files
        assert rotator.read_slot(ea) == a               # now served from the keychain
    finally:
        rotator._slot_keychain_delete(ea)
        rotator._slot_keychain_delete(eb)


def test_state_roundtrip_is_0600(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """save_state/load_state round-trip through a 0600 file; absent file → default."""
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(rotator, "STATE_FILE", state_file)
    assert rotator.load_state() == {"live_email": None, "live_fp": None, "slots": {}}
    st = {"live_email": "a@x.com", "live_fp": "deadbeef", "slots": {"a@x.com": {}}}
    rotator.save_state(st)
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600
    assert rotator.load_state() == st


def test_no_secrets_committed_in_oauth_rotator() -> None:
    """Guard: the committed rotator code carries NO real tokens or slot blobs.

    A real Claude credential is a long opaque token; the repo must ship only code.
    Fail if any committed source line looks like it embeds an accessToken value or
    a refresh token (as opposed to the *key name* 'accessToken'/'refreshToken').
    """
    rot_dir = _ROTATOR_PY.parent
    offenders: list[str] = []
    for src in rot_dir.glob("*.py"):
        for i, line in enumerate(src.read_text().splitlines(), 1):
            # A literal credential would appear as accessToken assigned a long string
            # constant. Our code only ever assigns it from variables (tok, blob[...]),
            # so any 40+ char quoted value next to accessToken is a red flag.
            if '"accessToken":' in line or "'accessToken':" in line:
                # allow the variable form  "accessToken": tok  /  blob.get(...)
                after = line.split("accessToken")[-1]
                if any(seg.strip(" :\"',") and len(seg.strip(" :\"',")) >= 40 for seg in [after]):
                    offenders.append(f"{src.name}:{i}: {line.strip()[:80]}")
    # Also: no slot json / state.json must be committed under scripts/oauth_rotator/.
    leaked = [p.name for p in rot_dir.rglob("*.json") if p.name not in {"package.json"}]
    assert not offenders, "possible committed token(s): " + "; ".join(offenders)
    assert not leaked, "credential state files committed in plugin: " + ", ".join(leaked)


# ---------------------------------------------------------------------------
# F1 — env-stable root resolution (TRDD-7100178d). The daemon was reading a
# FOREIGN plugin's CLAUDE_PLUGIN_DATA (codex) and finding zero accounts.
# ---------------------------------------------------------------------------
_JANITOR_DD = "ai-maestro-janitor-ai-maestro-plugins"


def _fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the resolver's Path.home() at an isolated tmp HOME (real FS, no mocks)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def test_root_ignores_foreign_plugin_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A foreign plugin's CLAUDE_PLUGIN_DATA (e.g. codex) is IGNORED — the canonical root is derived from the fixed janitor install name, never codex's dir."""
    _fake_home(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "home" / ".claude" / "plugins" / "data" / "codex-openai-codex"))
    canon = rotator._canonical_rotator_root()
    assert canon == tmp_path / "home" / ".claude" / "plugins" / "data" / _JANITOR_DD / "oauth-rotator"
    assert "codex" not in str(canon)


def test_root_trusts_own_plugin_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When CLAUDE_PLUGIN_DATA really points at THIS plugin's data dir, it is used as the canonical root (fast path)."""
    _fake_home(tmp_path, monkeypatch)
    own = tmp_path / "home" / ".claude" / "plugins" / "data" / _JANITOR_DD
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(own))
    assert rotator._canonical_rotator_root() == own / "oauth-rotator"


def test_root_falls_back_to_legacy_when_only_legacy_has_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When only the legacy standalone root holds state.json, the resolver returns it (a not-yet-migrated install keeps working — never points at an empty canonical dir)."""
    home = _fake_home(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    legacy = home / ".claude" / "account-rotator"
    legacy.mkdir(parents=True)
    (legacy / "state.json").write_text("{}")
    assert rotator._rotator_root() == legacy


def test_root_prefers_canonical_when_it_has_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Once the canonical root holds state.json it WINS over the legacy root, even if both exist."""
    home = _fake_home(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    legacy = home / ".claude" / "account-rotator"
    legacy.mkdir(parents=True)
    (legacy / "state.json").write_text("{}")
    canon = home / ".claude" / "plugins" / "data" / _JANITOR_DD / "oauth-rotator"
    canon.mkdir(parents=True)
    (canon / "state.json").write_text("{}")
    assert rotator._rotator_root() == canon


def test_root_fresh_install_writes_to_canonical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh install (no state.json anywhere) resolves to the canonical DATA-dir root for the first write."""
    home = _fake_home(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    assert rotator._rotator_root() == home / ".claude" / "plugins" / "data" / _JANITOR_DD / "oauth-rotator"


def test_migrate_root_copies_state_and_opt_in_non_destructively(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """migrate_root_to_canonical copies state.json (0600) + opt-in.flag legacy->canonical, KEEPS the legacy copies, and is idempotent (second call is a no-op)."""
    home = _fake_home(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    legacy = home / ".claude" / "account-rotator"
    legacy.mkdir(parents=True)
    (legacy / "state.json").write_text('{"live_email":"a@x.com","slots":{}}')
    (legacy / "opt-in.flag").write_text("on")
    src_legacy, dst_canon, moved = rotator.migrate_root_to_canonical()
    assert moved is True
    assert (dst_canon / "state.json").read_text() == '{"live_email":"a@x.com","slots":{}}'
    assert (dst_canon / "opt-in.flag").read_text() == "on"
    assert stat.S_IMODE((dst_canon / "state.json").stat().st_mode) == 0o600  # no token leak
    assert (src_legacy / "state.json").is_file()  # NON-destructive — legacy kept
    # idempotent: canonical now has state.json -> second call no-ops
    _, _, moved2 = rotator.migrate_root_to_canonical()
    assert moved2 is False


def test_migrate_root_noop_without_legacy_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no legacy state.json there is nothing to migrate — migrate_root_to_canonical is a no-op and does NOT create a canonical state.json."""
    _fake_home(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    _, canon, moved = rotator.migrate_root_to_canonical()
    assert moved is False
    assert not (canon / "state.json").exists()


# --------------------------------------------------------------------------
# Pillar 2 (TRDD-7100178d): live-credential -livebak mirror + integrity-repair pass
# --------------------------------------------------------------------------
def _isolate_live_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect BOTH live-credential keychain services (primary + -livebak mirror) to
    throwaway TEST services so a live-blob test NEVER touches the user's real
    'Claude Code-credentials' item (account=$USER)."""
    monkeypatch.setattr(rotator, "KEYCHAIN_SERVICE",
                        "Claude Code-credentials-TEST-%d" % os.getpid())
    monkeypatch.setattr(rotator, "LIVE_BACKUP_KEYCHAIN_SERVICE",
                        "Claude Code-credentials-livebak-TEST-%d" % os.getpid())


def _purge_live_keychain() -> None:
    acct = rotator._keychain_account()
    rotator._slot_keychain_delete(acct, service=rotator.KEYCHAIN_SERVICE)
    rotator._slot_keychain_delete(acct, service=rotator.LIVE_BACKUP_KEYCHAIN_SERVICE)


def test_live_backup_mirror_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """The -livebak live-credential mirror round-trips through the real OS keychain. 🐌"""
    if sys.platform != "darwin":
        pytest.skip("keychain round-trip is macOS-only")
    _isolate_live_keychain(monkeypatch)
    blob = _blob("live-tokenAAA")
    try:
        rotator._live_backup_write(blob)
        assert rotator._live_backup_read() == blob
    finally:
        _purge_live_keychain()
    assert rotator._live_backup_read() is None  # gone after cleanup


def test_write_live_blob_mirrors_to_livebak(monkeypatch: pytest.MonkeyPatch) -> None:
    """write_live_blob writes the primary AND the redundant -livebak mirror (Pillar 2). 🐌"""
    if sys.platform != "darwin":
        pytest.skip("keychain round-trip is macOS-only")
    _isolate_live_keychain(monkeypatch)
    blob = _blob("live-tokenBBB")
    try:
        rotator.write_live_blob(blob)
        assert rotator._read_live_primary() == blob   # primary written
        assert rotator._live_backup_read() == blob     # redundant mirror written
    finally:
        _purge_live_keychain()


def test_read_live_blob_prefers_primary_then_livebak(monkeypatch: pytest.MonkeyPatch) -> None:
    """read_live_blob returns the primary when present, else falls back to the -livebak mirror, else None."""
    primary = _blob("PRIMARY")
    mirror = _blob("MIRROR")
    monkeypatch.setattr(rotator, "_read_live_primary", lambda: primary)
    monkeypatch.setattr(rotator, "_live_backup_read", lambda: mirror)
    assert rotator.read_live_blob() == primary            # primary wins
    monkeypatch.setattr(rotator, "_read_live_primary", lambda: None)
    assert rotator.read_live_blob() == mirror             # falls back to the mirror
    monkeypatch.setattr(rotator, "_live_backup_read", lambda: None)
    assert rotator.read_live_blob() is None               # nothing survives anywhere


def test_repair_integrity_restores_live_primary_from_mirror(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_repair_integrity RESTORES the live primary from the -livebak mirror when the primary is gone."""
    monkeypatch.setattr(rotator, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(rotator, "SLOTS", tmp_path / "slots")
    rotator.save_state({"live_email": None, "live_fp": None, "slots": {}})
    mirror = _blob("RESTORED")
    restored: list = []
    monkeypatch.setattr(rotator, "_read_live_primary", lambda: None)     # primary gone
    monkeypatch.setattr(rotator, "_live_backup_read", lambda: mirror)    # mirror survived
    monkeypatch.setattr(rotator, "write_live_blob", lambda b: restored.append(b))
    actions = rotator._repair_integrity()
    assert restored == [mirror]                                          # primary restored from mirror
    assert any("restored primary" in a for a in actions)


def test_repair_integrity_refreshes_mirror_from_primary(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the live primary is healthy, _repair_integrity refreshes the -livebak mirror from it (in-advance backup) and does NOT restore."""
    monkeypatch.setattr(rotator, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(rotator, "SLOTS", tmp_path / "slots")
    rotator.save_state({"live_email": None, "live_fp": None, "slots": {}})
    primary = _blob("PRIMARY-LIVE")
    mirrored: list = []
    monkeypatch.setattr(rotator, "_read_live_primary", lambda: primary)
    monkeypatch.setattr(rotator, "_live_backup_write", lambda b: mirrored.append(b))
    monkeypatch.setattr(rotator, "write_live_blob",
                        lambda b: pytest.fail("must NOT restore when the primary is healthy"))
    rotator._repair_integrity()
    assert mirrored == [primary]                                         # mirror refreshed from primary


def test_repair_integrity_establishes_state_backup(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_repair_integrity establishes the state.json redundant backup mirror when it's missing (pre-integrity file)."""
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(rotator, "STATE_FILE", state_file)
    monkeypatch.setattr(rotator, "SLOTS", tmp_path / "slots")
    # pre-integrity: a bare state.json with NO sidecar / .bak yet
    state_file.write_text(json.dumps({"live_email": None, "live_fp": None, "slots": {}}))
    assert not rotator.integrity.backup_is_consistent(state_file)
    monkeypatch.setattr(rotator, "_read_live_primary", lambda: None)     # neutralise live path
    monkeypatch.setattr(rotator, "_live_backup_read", lambda: None)
    actions = rotator._repair_integrity()
    assert rotator.integrity.backup_is_consistent(state_file)            # mirror now established
    assert any("backup mirror" in a for a in actions)


# --------------------------------------------------------------------------
# F2 (TRDD-7100178d, blocker 5): expiry ladder — rotate on a dead token even with no API
# --------------------------------------------------------------------------
def _ms_in(hours: float) -> int:
    """An absolute expiresAt (ms) `hours` from now (negative = already past)."""
    return int((time.time() + hours * 3600) * 1000)


def test_blob_locally_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    """_blob_locally_expired flags a token at/within EXPIRY_GRACE_H of expiry; None expiresAt → False (fail-safe)."""
    monkeypatch.setattr(rotator, "EXPIRY_GRACE_H", 0.5)
    assert rotator._blob_locally_expired(_blob("t", expires_ms=_ms_in(-1))) is True    # 1h past
    assert rotator._blob_locally_expired(_blob("t", expires_ms=_ms_in(0.25))) is True   # within grace
    assert rotator._blob_locally_expired(_blob("t", expires_ms=_ms_in(10))) is False    # 10h runway
    assert rotator._blob_locally_expired(_blob("t")) is False                            # no expiresAt → never dead


def _usage_ok(util: float = 5.0) -> dict:
    return {"five_hour": {"utilization": util}, "seven_day": {"utilization": util}}


def _setup_auto(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, live_email: str,
                live_blob: dict, slot_blobs: dict, usage: dict) -> list:
    """Wire cmd_auto's seams: tmp state (live_email + slot keys), read_live_blob/read_slot/
    usage_request/_switch_blob faked. `usage` maps accessToken -> (status, data). Returns the
    list _switch_blob records (email, blob, reason) into."""
    monkeypatch.setattr(rotator, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(rotator, "SLOTS", tmp_path / "slots")
    rotator.save_state({"live_email": live_email, "live_fp": rotator.fingerprint(live_blob),
                        "slots": {e: {} for e in slot_blobs}})
    monkeypatch.setattr(rotator, "read_live_blob", lambda: live_blob)
    monkeypatch.setattr(rotator, "read_slot", lambda e: slot_blobs.get(e))
    monkeypatch.setattr(rotator, "usage_request",
                        lambda b: usage.get(b.get("claudeAiOauth", {}).get("accessToken", ""), (0, None)))
    switches: list = []
    monkeypatch.setattr(rotator, "_switch_blob",
                        lambda email, blob, reason: switches.append((email, blob, reason)))
    return switches


def test_cmd_auto_rotates_on_401_token_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 401 (server rejected the live token) rotates to a safe alternate — even when the live token still has local runway."""
    live = _blob("LIVE", expires_ms=_ms_in(50))           # NOT locally expired: 401 alone drives it
    alt = _blob("ALT", expires_ms=_ms_in(50))
    switches = _setup_auto(monkeypatch, tmp_path, live_email="live@x", live_blob=live,
                           slot_blobs={"alt@x": alt}, usage={"LIVE": (401, None), "ALT": (200, _usage_ok())})
    rotator.cmd_auto()
    assert [s[0] for s in switches] == ["alt@x"]


def test_cmd_auto_degraded_rotates_when_api_down_and_live_expired(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """API unreachable (status 0) + live token LOCALLY expired → degraded rotate to the most-runway non-expired alternate (no usage probe)."""
    monkeypatch.setattr(rotator, "EXPIRY_GRACE_H", 0.5)
    live = _blob("LIVE", expires_ms=_ms_in(-2))           # dead
    near_alt = _blob("NEAR", expires_ms=_ms_in(3))        # valid, little runway
    far_alt = _blob("FAR", expires_ms=_ms_in(80))         # valid, most runway → chosen
    # usage map all (0, None) → network down for everyone
    switches = _setup_auto(monkeypatch, tmp_path, live_email="live@x", live_blob=live,
                           slot_blobs={"near@x": near_alt, "far@x": far_alt},
                           usage={"LIVE": (0, None)})
    rotator.cmd_auto()
    assert [s[0] for s in switches] == ["far@x"]          # most-runway alternate wins


def test_cmd_auto_stays_put_when_api_down_but_live_valid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """API unreachable (status 0) but the live token is still valid locally → do NOT churn; stay put."""
    monkeypatch.setattr(rotator, "EXPIRY_GRACE_H", 0.5)
    live = _blob("LIVE", expires_ms=_ms_in(40))           # still valid
    alt = _blob("ALT", expires_ms=_ms_in(80))
    switches = _setup_auto(monkeypatch, tmp_path, live_email="live@x", live_blob=live,
                           slot_blobs={"alt@x": alt}, usage={"LIVE": (0, None)})
    rotator.cmd_auto()
    assert switches == []                                  # transient blip → no rotation


def test_cmd_auto_never_rotates_onto_expired_alternate(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The only alternate is itself locally expired → it is skipped and no switch happens."""
    monkeypatch.setattr(rotator, "EXPIRY_GRACE_H", 0.5)
    live = _blob("LIVE", expires_ms=_ms_in(50))
    dead_alt = _blob("DEAD", expires_ms=_ms_in(-5))       # expired target — must be rejected
    switches = _setup_auto(monkeypatch, tmp_path, live_email="live@x", live_blob=live,
                           slot_blobs={"dead@x": dead_alt}, usage={"LIVE": (401, None), "DEAD": (200, _usage_ok())})
    rotator.cmd_auto()
    assert switches == []


def test_cmd_auto_proactive_swap_on_locally_expiring_live(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A live token with low usage but within the expiry grace window triggers a proactive swap (200 + locally-expiring)."""
    monkeypatch.setattr(rotator, "EXPIRY_GRACE_H", 0.5)
    live = _blob("LIVE", expires_ms=_ms_in(0.2))          # 200 OK, but expiring within grace
    alt = _blob("ALT", expires_ms=_ms_in(80))
    switches = _setup_auto(monkeypatch, tmp_path, live_email="live@x", live_blob=live,
                           slot_blobs={"alt@x": alt},
                           usage={"LIVE": (200, _usage_ok(5.0)), "ALT": (200, _usage_ok(5.0))})
    rotator.cmd_auto()
    assert [s[0] for s in switches] == ["alt@x"]           # rotated before the live token expired


def _tok(blob: dict) -> str:
    """The accessToken inside a credential blob — used to assert WHICH token a switch landed on."""
    return blob.get("claudeAiOauth", {}).get("accessToken", "")


def test_cmd_auto_refreshes_expired_alternate_before_excluding(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """REFRESH-ON-ERR (TRDD-32acd15f, the 2026-06-11 deadlock): an alternate that passed the local
    expiry guard but whose token the server REJECTS (probe 401/403) is refreshed + re-probed BEFORE
    exclusion — so a single stale slot token can no longer make the rotator declare 'all accounts
    maxed' while a fresh alternate exists. The switch lands on the FRESH token and the slot is healed."""
    live = _blob("LIVE", expires_ms=_ms_in(50))
    stale_alt = _blob("ALT_OLD", expires_ms=_ms_in(50))    # local runway fine; the SERVER rejects the token
    fresh_alt = _blob("ALT_NEW", expires_ms=_ms_in(80))    # what refresh_oauth_token mints
    switches = _setup_auto(monkeypatch, tmp_path, live_email="live@x", live_blob=live,
                           slot_blobs={"alt@x": stale_alt},
                           usage={"LIVE": (401, None), "ALT_OLD": (403, None), "ALT_NEW": (200, _usage_ok())})
    monkeypatch.setattr(rotator, "refresh_oauth_token",
                        lambda b: fresh_alt if _tok(b) == "ALT_OLD" else None)
    healed: list = []
    monkeypatch.setattr(rotator, "write_slot", lambda e, b: healed.append((e, _tok(b))))
    rotator.cmd_auto()
    assert [s[0] for s in switches] == ["alt@x"]           # rotated instead of deadlocking
    assert _tok(switches[0][1]) == "ALT_NEW"               # onto the FRESH token, not the stale one
    assert healed == [("alt@x", "ALT_NEW")]                # the lapsed slot was re-minted in the keychain


def test_cmd_auto_does_not_refresh_maxed_429_alternate(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 429 alternate is MAXED, not expired — refreshing cannot un-max it, so it must NOT trigger a
    refresh grant; with no other candidate the rotator correctly stays put (genuinely all-maxed)."""
    live = _blob("LIVE", expires_ms=_ms_in(50))
    maxed_alt = _blob("ALT", expires_ms=_ms_in(80))
    switches = _setup_auto(monkeypatch, tmp_path, live_email="live@x", live_blob=live,
                           slot_blobs={"alt@x": maxed_alt},
                           usage={"LIVE": (401, None), "ALT": (429, None)})
    refreshed: list = []
    monkeypatch.setattr(rotator, "refresh_oauth_token", lambda b: refreshed.append(_tok(b)) or None)
    rotator.cmd_auto()
    assert refreshed == []                                 # 429 (maxed) never triggers a wasted refresh
    assert switches == []                                  # genuinely maxed → no rotation


def test_cmd_auto_excludes_alternate_when_refresh_fails(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the rejected alternate cannot be refreshed (setup-token slot or a dead refresh chain →
    refresh_oauth_token returns None) it is still excluded — refresh-on-err must not rotate onto an
    unusable token, and it must not 'heal' a slot it could not refresh."""
    live = _blob("LIVE", expires_ms=_ms_in(50))
    stale_alt = _blob("ALT_OLD", expires_ms=_ms_in(50))
    switches = _setup_auto(monkeypatch, tmp_path, live_email="live@x", live_blob=live,
                           slot_blobs={"alt@x": stale_alt},
                           usage={"LIVE": (401, None), "ALT_OLD": (401, None)})
    monkeypatch.setattr(rotator, "refresh_oauth_token", lambda b: None)    # refresh chain is dead
    wrote: list = []
    monkeypatch.setattr(rotator, "write_slot", lambda e, b: wrote.append(e))
    rotator.cmd_auto()
    assert switches == []                                  # cannot rotate onto an unrefreshable token
    assert wrote == []                                     # nothing healed when refresh failed


def test_cmd_auto_refresh_on_err_heals_state_index(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A refresh-on-err heal keeps the state.json slots index in LOCKSTEP with the keychain
    (fp + expires_at updated and PERSISTED before the switch) — the F3 self-heal invariant;
    a stale index here is the TRDD-7100178d blocker-6 drift class."""
    live = _blob("LIVE", expires_ms=_ms_in(50))
    stale_alt = _blob("ALT_OLD", expires_ms=_ms_in(50))
    fresh_alt = _blob("ALT_NEW", expires_ms=_ms_in(80))
    switches = _setup_auto(monkeypatch, tmp_path, live_email="live@x", live_blob=live,
                           slot_blobs={"alt@x": stale_alt},
                           usage={"LIVE": (401, None), "ALT_OLD": (403, None), "ALT_NEW": (200, _usage_ok())})
    monkeypatch.setattr(rotator, "refresh_oauth_token",
                        lambda b: fresh_alt if _tok(b) == "ALT_OLD" else None)
    monkeypatch.setattr(rotator, "write_slot", lambda e, b: None)          # keychain write succeeds
    rotator.cmd_auto()
    assert [s[0] for s in switches] == ["alt@x"]
    meta = rotator.load_state()["slots"]["alt@x"]                          # re-read from DISK —
    assert meta["fp"] == rotator.fingerprint(fresh_alt)                    # proves the save landed
    assert meta["expires_at"] == fresh_alt["claudeAiOauth"]["expiresAt"]   # before _switch_blob ran


def test_cmd_auto_refresh_on_err_keychain_refused_skips_index_update(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the keychain REFUSES the healed slot write, the index meta must NOT be updated
    (index claiming the new fp while the keychain holds the old token would be a lie) — but
    rotation still proceeds onto the in-memory fresh token (the anti-deadlock goal)."""
    live = _blob("LIVE", expires_ms=_ms_in(50))
    stale_alt = _blob("ALT_OLD", expires_ms=_ms_in(50))
    fresh_alt = _blob("ALT_NEW", expires_ms=_ms_in(80))
    switches = _setup_auto(monkeypatch, tmp_path, live_email="live@x", live_blob=live,
                           slot_blobs={"alt@x": stale_alt},
                           usage={"LIVE": (401, None), "ALT_OLD": (403, None), "ALT_NEW": (200, _usage_ok())})
    monkeypatch.setattr(rotator, "refresh_oauth_token",
                        lambda b: fresh_alt if _tok(b) == "ALT_OLD" else None)

    def refuse(e: str, b: dict) -> None:
        raise rotator.SlotKeychainWriteError("keychain locked")

    monkeypatch.setattr(rotator, "write_slot", refuse)
    rotator.cmd_auto()
    assert [s[0] for s in switches] == ["alt@x"]                           # still rotated (no deadlock)
    assert _tok(switches[0][1]) == "ALT_NEW"                               # onto the fresh in-memory token
    assert rotator.load_state()["slots"]["alt@x"] == {}                    # index untouched — no false fp


# --------------------------------------------------------------------------
# F2b (TRDD-7100178d): refresh-token keepalive — PREVENT slot expiry (slots only)
# --------------------------------------------------------------------------
class _FakeResp:
    """Minimal urlopen() context-manager stand-in returning a fixed JSON payload."""
    def __init__(self, payload: dict) -> None:
        self._b = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._b

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *a: object) -> bool:
        return False


def test_refresh_oauth_token_maps_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """refresh_oauth_token POSTs the refresh grant to TOKEN_URL and maps access/refresh/expires into a NEW blob, preserving other inner fields; None without a refreshToken."""
    captured: dict = {}

    def _fake_urlopen(req: object, timeout: float = 0) -> _FakeResp:
        captured["body"] = json.loads(req.data.decode())     # type: ignore[attr-defined]
        captured["url"] = req.full_url                        # type: ignore[attr-defined]
        return _FakeResp({"access_token": "NEW", "refresh_token": "NEWR", "expires_in": 28800})

    monkeypatch.setattr(rotator.urllib.request, "urlopen", _fake_urlopen)
    old = _blob("OLD", refresh="OLDR", expires_ms=_ms_in(1))
    old["claudeAiOauth"]["scopes"] = ["keep-me"]
    new = rotator.refresh_oauth_token(old)
    assert new is not None
    inner = new["claudeAiOauth"]
    assert inner["accessToken"] == "NEW"
    assert inner["refreshToken"] == "NEWR"
    assert inner["scopes"] == ["keep-me"]                    # non-token fields preserved
    assert inner["expiresAt"] > _ms_in(7)                    # ~8h of fresh runway
    assert captured["url"] == rotator.TOKEN_URL
    assert captured["body"] == {"grant_type": "refresh_token",
                                "client_id": rotator.CLIENT_ID, "refresh_token": "OLDR"}
    assert rotator.refresh_oauth_token(_blob("X", refresh=None)) is None  # no refreshToken → None


def test_refresh_oauth_token_network_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A network/HTTP failure during the refresh exchange returns None (fail-soft — the slot keeps its old token)."""
    def _boom(req: object, timeout: float = 0) -> _FakeResp:
        raise rotator.urllib.error.URLError("endpoint down")
    monkeypatch.setattr(rotator.urllib.request, "urlopen", _boom)
    assert rotator.refresh_oauth_token(_blob("OLD", refresh="OLDR")) is None


def test_keepalive_refresh_only_near_expiry_refreshable_non_live_slots(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_keepalive_refresh refreshes a near-expiry slot WITH a refreshToken; skips fresh slots, setup-token (no refreshToken) slots, and the live account; updates the index."""
    monkeypatch.setattr(rotator, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(rotator, "SLOTS", tmp_path / "slots")
    monkeypatch.setattr(rotator, "KEEPALIVE_AHEAD_H", 2.0)
    blobs = {
        "near@x": _blob("NEAR", refresh="NR", expires_ms=_ms_in(1)),    # refreshable + expiring → refresh
        "fresh@x": _blob("FRESH", refresh="FR", expires_ms=_ms_in(50)),  # lots of runway → skip
        "setup@x": _blob("SETUP", refresh=None, expires_ms=_ms_in(1)),   # no refreshToken → skip
        "live@x": _blob("LIVE", refresh="LR", expires_ms=_ms_in(1)),     # live account → skip
    }
    written: dict = {}
    monkeypatch.setattr(rotator, "read_slot", lambda e: blobs.get(e))
    monkeypatch.setattr(rotator, "write_slot", lambda e, b: written.__setitem__(e, b))
    monkeypatch.setattr(rotator, "refresh_oauth_token",
                        lambda b: {"claudeAiOauth": {**b["claudeAiOauth"],
                                                     "accessToken": "R-" + b["claudeAiOauth"]["accessToken"],
                                                     "expiresAt": _ms_in(8)}})
    rotator.save_state({"live_email": "live@x", "live_fp": "x",
                        "slots": {e: {"fp": "old", "expires_at": 0} for e in blobs}})
    refreshed = rotator._keepalive_refresh()
    assert refreshed == ["near@x"]                            # only the near-expiry refreshable non-live slot
    assert set(written.keys()) == {"near@x"}
    assert written["near@x"]["claudeAiOauth"]["accessToken"] == "R-NEAR"
    st = rotator.load_state()                                 # index updated for the refreshed slot
    assert st["slots"]["near@x"]["fp"] == rotator.fingerprint(written["near@x"])
    assert st["slots"]["near@x"]["expires_at"] > _ms_in(7)


# ---- _reconcile_live_email: state.json self-heals to the ACTUAL live credential ----
# (TRDD-7100178d#6 stale-index / live-account drift: an out-of-band `claude` login or a
#  reauth that wrote the token but not the index leaves state.live_email pointing at the
#  WRONG account; cmd_auto would then treat the real live account as a rotation target.)

def test_reconcile_live_email_noop_when_in_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Steady state (state.live_fp already matches the live blob): ZERO network, ZERO write."""
    monkeypatch.setattr(rotator, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(rotator, "SLOTS", tmp_path / "slots")
    live = _blob("LIVE-TOKEN")
    calls = {"roles": 0, "save": 0}
    monkeypatch.setattr(rotator, "account_email",
                        lambda *_a, **_k: (calls.__setitem__("roles", calls["roles"] + 1), "WRONG@x")[1])
    monkeypatch.setattr(rotator, "save_state", lambda _s: calls.__setitem__("save", calls["save"] + 1))
    state = {"live_email": "a@x", "live_fp": rotator.fingerprint(live), "slots": {"a@x": {}}}
    out = rotator._reconcile_live_email(state, live)
    assert out["live_email"] == "a@x"   # unchanged
    assert calls["roles"] == 0          # steady state never touches /roles
    assert calls["save"] == 0           # …and never writes


def test_reconcile_live_email_corrects_drift_via_roles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Drift: live-blob fp != state.live_fp → /roles email is authoritative; state corrected + persisted."""
    monkeypatch.setattr(rotator, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(rotator, "SLOTS", tmp_path / "slots")
    live = _blob("REAL-LIVE")
    monkeypatch.setattr(rotator, "account_email", lambda *_a, **_k: "real@x")
    state = {"live_email": "stale@x", "live_fp": "deadbeefdeadbeef",
             "live_429_streak": 5, "slots": {"stale@x": {}, "real@x": {}}}
    out = rotator._reconcile_live_email(state, live)
    assert out["live_email"] == "real@x"                       # corrected to ground truth
    assert out["live_fp"] == rotator.fingerprint(live)         # fp updated to reality
    assert out["live_429_streak"] == 0                         # stale account's streak reset
    assert isinstance(out.get("last_reconcile_at"), float)
    assert rotator.load_state()["live_email"] == "real@x"      # persisted to disk


def test_reconcile_live_email_falls_back_to_slot_fp_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Drift + /roles can't resolve (returns '') → match the live fp against a known slot's blob."""
    monkeypatch.setattr(rotator, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(rotator, "SLOTS", tmp_path / "slots")
    live = _blob("REAL-LIVE")
    monkeypatch.setattr(rotator, "account_email", lambda *_a, **_k: "")  # /roles can't resolve
    monkeypatch.setattr(rotator, "read_slot",
                        lambda em: live if em == "real@x" else _blob("OTHER"))
    state = {"live_email": "stale@x", "live_fp": "deadbeefdeadbeef",
             "slots": {"stale@x": {}, "real@x": {}}}
    out = rotator._reconcile_live_email(state, live)
    assert out["live_email"] == "real@x"                       # resolved by fingerprint match


# ---- TRDD-5539cd6e: slots store claudeAiOauth-only; switch merges; capture verifies ----

def test_write_slot_strips_to_claudeaioauth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """write_slot stores ONLY claudeAiOauth — the ~8KB mcpOAuth section is dropped (smaller
    slot, less keychain bloat + argv exposure). All rotator helpers read via _oauth()."""
    monkeypatch.setattr(rotator, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(rotator, "SLOTS", tmp_path / "slots")
    captured: dict = {}
    monkeypatch.setattr(rotator, "_slot_keychain_write",
                        lambda email, blob, **k: captured.__setitem__("blob", blob) or True)
    full = {"mcpOAuth": {"plugin:x": {"token": "Z" * 5000}},  # the bloat
            "claudeAiOauth": {"accessToken": "A", "refreshToken": "R", "expiresAt": 1}}
    rotator.write_slot("e@x", full)
    assert set(captured["blob"].keys()) == {"claudeAiOauth"}          # mcpOAuth dropped
    assert captured["blob"]["claudeAiOauth"] == full["claudeAiOauth"]  # credential intact


def test_switch_blob_preserves_live_mcpoauth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_switch_blob swaps ONLY claudeAiOauth into the CURRENT live blob, preserving the live
    mcpOAuth — so a rotation never wipes the user's MCP-server OAuth tokens (TRDD-5539cd6e)."""
    monkeypatch.setattr(rotator, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(rotator, "SLOTS", tmp_path / "slots")
    live = {"mcpOAuth": {"notion": "KEEP-ME"},
            "claudeAiOauth": {"accessToken": "OLD-LIVE", "refreshToken": "ro"}}
    written: dict = {}
    monkeypatch.setattr(rotator, "read_live_blob", lambda: live)
    monkeypatch.setattr(rotator, "write_live_blob", lambda b: written.update(blob=b))
    slot = {"claudeAiOauth": {"accessToken": "NEW-ACCT", "refreshToken": "rn"}}
    rotator._switch_blob("new@x", slot, reason="test")
    assert written["blob"]["mcpOAuth"] == {"notion": "KEEP-ME"}              # mcpOAuth preserved
    assert written["blob"]["claudeAiOauth"] == slot["claudeAiOauth"]         # only the account swapped
    assert rotator.load_state()["live_email"] == "new@x"


def test_cmd_capture_fails_loud_on_corrupt_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If a written slot does NOT round-trip (the 128-byte-truncation class of failure),
    cmd_capture returns non-zero and does NOT record it in state — fail loud, never silently
    accept a corrupt slot (the guardrail that would have caught the overnight failure)."""
    monkeypatch.setattr(rotator, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(rotator, "SLOTS", tmp_path / "slots")
    monkeypatch.setattr(rotator, "claude_running", lambda: True)
    monkeypatch.setattr(rotator, "read_live_blob", lambda: _blob("LIVE-TOKEN", expires_ms=_ms_in(8)))
    monkeypatch.setattr(rotator, "account_email", lambda *_a, **_k: "e@x")
    monkeypatch.setattr(rotator, "write_slot", lambda *_a, **_k: None)   # pretend the write happened
    monkeypatch.setattr(rotator, "read_slot", lambda *_a, **_k: None)    # …but it round-trips to garbage
    rc = rotator.cmd_capture(only_if_running=False)
    assert rc == 1                                                       # FAILS LOUD
    assert "e@x" not in rotator.load_state().get("slots", {})            # NOT recorded


# ── persistent decision log (TRDD-924645bb) ─────────────────────────────────────


def test_log_appends_timestamped_line_creating_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_log appends '<ISO-local+offset> <msg>' to LOG_FILE and creates ROOT if absent."""
    root = tmp_path / "missing-root"           # does NOT exist yet
    monkeypatch.setattr(rotator, "ROOT", root)
    monkeypatch.setattr(rotator, "LOG_FILE", root / "rotator.log")
    rotator._log("auto: live a@x.com 5h=15% 7d=35% — within limits")
    assert root.is_dir()                                            # ROOT auto-created
    line = (root / "rotator.log").read_text(encoding="utf-8")
    assert line.endswith("auto: live a@x.com 5h=15% 7d=35% — within limits\n")
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4} ", line)  # local time + GMT offset


def test_log_self_trims_and_starts_on_record_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the log exceeds the cap, _log trims it to the recent tail AND the trimmed file
    starts on a full record (the partial leading line is dropped), so it stays parseable."""
    monkeypatch.setattr(rotator, "ROOT", tmp_path)
    monkeypatch.setattr(rotator, "LOG_FILE", tmp_path / "rotator.log")
    monkeypatch.setattr(rotator, "_LOG_MAX_BYTES", 2000)
    monkeypatch.setattr(rotator, "_LOG_KEEP_BYTES", 1000)
    for i in range(200):                       # ~200 * ~60 bytes ≫ 2000 → forces a trim
        rotator._log("decision number %03d padding-padding-padding" % i)
    data = (tmp_path / "rotator.log").read_text(encoding="utf-8")
    assert len(data.encode()) <= rotator._LOG_MAX_BYTES                 # bounded
    assert re.match(r"^\d{4}-\d{2}-\d{2}T", data)                       # starts on a full record
    assert data.endswith("decision number 199 padding-padding-padding\n")  # most-recent retained


def test_log_never_raises_on_io_error_and_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """A log-IO error must NEVER crash a rotation decision — _log reports to stderr and returns."""
    monkeypatch.setattr(rotator, "ROOT", tmp_path)
    monkeypatch.setattr(rotator, "LOG_FILE", tmp_path)   # a DIRECTORY → open('a') raises IsADirectoryError
    rotator._log("auto: switched a@x -> b@y")            # must not raise
    assert "decision-log append failed" in capsys.readouterr().err


def test_decide_prints_and_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """_decide mirrors a decision to BOTH stdout (manual/daemon) and the persistent log."""
    monkeypatch.setattr(rotator, "ROOT", tmp_path)
    monkeypatch.setattr(rotator, "LOG_FILE", tmp_path / "rotator.log")
    rotator._decide("auto: live a@x.com 5h=99% 7d=10% +LOCALLY-EXPIRING")
    assert "auto: live a@x.com 5h=99% 7d=10% +LOCALLY-EXPIRING" in capsys.readouterr().out
    assert "5h=99% 7d=10%" in (tmp_path / "rotator.log").read_text(encoding="utf-8")


def test_decision_log_carries_emails_and_usage_but_never_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SECURITY: a logged decision line carries account emails + usage %s (for diagnosis) but
    NEVER a token value — the log shares state.json's trust boundary and must not widen leakage."""
    monkeypatch.setattr(rotator, "ROOT", tmp_path)
    monkeypatch.setattr(rotator, "LOG_FILE", tmp_path / "rotator.log")
    rotator._log("auto: switched a@x.com -> b@y.com (target 5h=10% 7d=20%; live a@x.com -> rotate)")
    body = (tmp_path / "rotator.log").read_text(encoding="utf-8")
    assert "a@x.com" in body and "b@y.com" in body                      # emails kept (diagnosable)
    assert "accessToken" not in body and "refreshToken" not in body     # no token KEYS
    assert "sk-ant-" not in body                                        # no token VALUES
