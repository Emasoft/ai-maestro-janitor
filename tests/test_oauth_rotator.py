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
    monkeypatch.setattr(rotator, "_slot_keychain_write", lambda *a, **k: False)
    monkeypatch.setattr(rotator, "_slot_keychain_read", lambda *a, **k: None)
    blob = _blob("secret-token-value", expires_ms=123456789000)
    rotator.write_slot("a@x.com", blob)
    p = slots / "a@x.com.json"
    assert p.exists()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600  # owner-only — no token leak
    assert rotator.read_slot("a@x.com") == blob
    assert rotator.read_slot("nobody@x.com") is None


def _isolate_slot_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point BOTH the primary and backup slot keychain services at throwaway names so a
    test never touches the production slot items (write_slot mirrors to both, Pillar 2)."""
    monkeypatch.setattr(rotator, "SLOT_KEYCHAIN_SERVICE", "Claude Code-rotator-slot-TEST-%d" % os.getpid())
    monkeypatch.setattr(rotator, "SLOT_BACKUP_KEYCHAIN_SERVICE", "Claude Code-rotator-slot-backup-TEST-%d" % os.getpid())


def _purge_slot_keychain(email: str) -> None:
    rotator._slot_keychain_delete(email)
    rotator._slot_keychain_delete(email, service=rotator.SLOT_BACKUP_KEYCHAIN_SERVICE)


def test_keychain_write_keeps_token_out_of_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    """The keychain WRITE helper passes the secret on STDIN, never in argv (M1 fix).

    The `security add-generic-password` argv must end in a bare `-w` (prompt mode) and
    contain NO element holding the token; the token must arrive via `input=` as the
    data + retype-confirm pair. Spies on subprocess.run so it runs on any platform and
    never touches the real keychain.
    """
    SECRET = '{"accessToken":"DO-NOT-LEAK-THIS-TO-PS-0123456789abcdef","refreshToken":"R-secret"}'
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
    assert argv[-1] == "-w"                              # bare -w => prompt-on-stdin mode
    assert not any(SECRET in str(a) for a in argv)       # token NEVER in argv (the whole point)
    assert "DO-NOT-LEAK" not in " ".join(argv)           # no fragment of the token either
    assert seen["input"] == "%s\n%s\n" % (SECRET, SECRET)  # data + retype-confirm on stdin


def test_security_add_password_via_stdin_roundtrips_real_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    """The STDIN-prompt keychain write actually stores the exact bytes in the real macOS keychain. 🐌"""
    if sys.platform != "darwin":
        pytest.skip("real macOS keychain test")
    service = "Claude Code-rotator-stdin-TEST-%d" % os.getpid()
    account = "stdin-test-%d@example.test" % os.getpid()
    blob = _blob("stdin-secret-token-value", expires_ms=123456789000)
    data = json.dumps(blob, separators=(",", ":"))
    try:
        rotator._security_add_password_via_stdin(service, account, data)
        # Read it back via the same security CLI READ path the rotator uses.
        got = rotator._slot_keychain_read(account, service=service)
        assert got == blob                               # exact round-trip, secret never in argv
        # -U overwrite path (the rotator's real hot path): a second write replaces it.
        blob2 = _blob("stdin-secret-token-ROTATED", expires_ms=123456789000)
        rotator._security_add_password_via_stdin(service, account, json.dumps(blob2, separators=(",", ":")))
        assert rotator._slot_keychain_read(account, service=service) == blob2
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
