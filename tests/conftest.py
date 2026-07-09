"""Shared pytest fixtures for the ai-maestro-janitor test-suite.

TWO protection layers live here:

1. Session-default janitor-state ISOLATION (TRDD-A8DRPZFM, fseventsd plan S1a/S1b).
2. Centralized rotator-path isolation (TRDD-56374Z36, re-surfacing TRDD-14IY6MAD).

── 1. Session-default state isolation (S1a) + real-state write guard (S1b) ─────────────

The 39 GB fseventsd incident (TRDD-ZNN0UK5K) shipped because test isolation was
per-test/opt-in: a module capturing ``Path.home()`` at import escaped it and the suite
corrupted the REAL keepalive closure. Isolation is now the SESSION DEFAULT:

- ``pytest_configure`` (which runs BEFORE collection, so even module-level import-time
  captures in test modules resolve the fake tree) points ``HOME``,
  ``JANITOR_GLOBAL_STATE_DIR``, ``JANITOR_DATA_DIR`` and ``CLAUDE_PLUGIN_DATA`` at a
  per-session tmp tree, and drops ``XDG_STATE_HOME`` — the exact env set the per-module
  ``_isolate_janitor_state`` fixtures used (those remain valid; per-test overrides win).
- A test that genuinely needs the real paths opts out EXPLICITLY with
  ``@pytest.mark.real_state`` — the autouse ``_real_state_optout`` fixture restores the
  saved real env for just that test. Opt-out is deliberate friction: it marks the test as
  touching shared machine state in code review.
- The fake HOME gets a minimal ``.gitconfig`` (the project's public identity) so tests
  that shell out to ``git commit`` keep working without reading the real one.

S1b — the write guard: before the run we snapshot a content manifest (sha256) of the REAL
``~/.claude/janitor-global-state/`` and the REAL plugin DATA dir; at session end we
re-snapshot and FAIL the suite (exitstatus 3) if anything non-excluded changed. The live
daemon on a dev machine legitimately churns liveness/append files every tick, so those are
EXCLUDED BY PATTERN (``*.ts`` stamps, ``*.log``/``*.jsonl``/``*.ndjson`` append logs,
``*.pid``/``*.lock``/``*.flock`` liveness) — the guard protects the CONTENT class that the
fseventsd incident corrupted (staged closure ``*.py``, ``state.json``, flags, quarantine /
last-good records, memory pages), not the daemon's heartbeat. A rare mid-run daemon
version-update restage can false-positive the guard; re-run to confirm before hunting.
Under pytest-xdist the guard runs only in the controller process.

── 2. Rotator-path isolation ────────────────────────────────────────────────────────────

Every rotator test module imports the rotator by path into a module-global ``rotator``
(``rotator = _load_rotator()``). That module resolves ROOT / LOG_FILE / SLOTS / STATE_FILE
ONCE at import to the REAL operational dir under ``~/.claude/plugins/data/.../oauth-rotator/``.
A test that re-points ``ROOT`` (e.g. the bootstrap ``_wire`` helper) but forgets ``LOG_FILE``
makes ``_log`` append to the PRODUCTION ``rotator.log`` — the exact leak that filled it with
fixture ``auto-bootstrap: opening a browser … for seeded@x.com`` lines. TRDD-14IY6MAD fixed
this once with a per-MODULE autouse fixture inside ``test_oauth_rotator.py``; the bootstrap +
cascade modules never got it (``two input paths ≠ SSOT`` — the log path diverged from the
isolated state path). The autouse ``_isolate_rotator_paths`` fixture CENTRALIZES that
protection so EVERY rotator test module — present and future — has its ``ROOT`` + ``LOG_FILE``
redirected to a per-test tmp dir, and a new module can't re-introduce the leak. It is a
deliberate PATH-redirect (NOT a ``_log`` no-op) so the dedicated ``_log`` tests, which re-point
``LOG_FILE`` inside their own body, still assert on real written content. Non-rotator tests are
a fast no-op: no ``rotator`` module global → nothing is patched and a ``tmp_path`` is never
even created for them.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# ─── S1a/S1b module state (filled by pytest_configure) ──────────────────────────────────

_ISOLATION_ENVS = ("HOME", "JANITOR_GLOBAL_STATE_DIR", "JANITOR_DATA_DIR", "CLAUDE_PLUGIN_DATA")
_REAL_ENV: dict[str, str | None] = {}
_SESSION_TMP: Path | None = None
# Session-default temp keychain (TRDD-K3WQ7XM9 P2): every test's `security` calls are scoped
# to THIS isolated keychain via JANITOR_ROTATOR_KEYCHAIN, so NO test can touch the login
# keychain. Round-trip tests override it per-test with the fresh `isolated_keychain` fixture.
_SESSION_KEYCHAIN: str | None = None
# label -> (real dir, before-manifest)
_GUARDED: dict[str, tuple[Path, dict[str, str]]] = {}

# Files the live daemon legitimately churns while a suite runs — excluded from the S1b
# guard so it detects TEST pollution, not daemon liveness. Everything else under the real
# dirs (staged *.py closure, *.flag, quarantine/last-good json, memory pages) stays
# guarded: a test mutating any of those fails the whole suite.
_GUARD_EXCLUDE_SUFFIXES = (
    ".ts", ".log", ".log.1", ".jsonl", ".ndjson", ".pid", ".lock", ".flock",
    # code-review 2026-07-07: integrity .bak mirrors are rewritten beside every primary
    # write; sqlite sidecars (.memgrep index, Chrome profile DBs) churn on any live
    # daemon memory/rotator activity — all daemon-legit, none test-pollution-specific.
    ".bak", ".pyc", ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3",
    # 2026-07-09: daemon-liveness files the LIVE daemon rewrites on any (re)spawn /
    # keepalive restage — pure daemon runtime, never test-written (tests use the
    # isolated JANITOR_GLOBAL_STATE_DIR). `daemon.spawn-history` churns on every daemon
    # spawn; `daemon-keepalive.restage-stamp` on every closure restage. A daemon
    # rollback/respawn mid-suite false-failed the whole publish gate (exit 3) while all
    # tests passed — same class as the already-excluded .ts/.pid stamps + `recovery`.
    ".spawn-history", ".restage-stamp",
)
# Whole subtrees owned by the LIVE daemon's runtime (rewritten on its 60s oauth tick /
# harvest passes) — guarding them would fail the suite whenever the daemon breathes
# mid-run, and the rotator's Chrome profiles subtree alone holds ~4k churning files.
# Rotator test pollution is separately fenced by _isolate_rotator_paths + the
# real_state-marked keychain tests, so excluding these keeps the guard's signal pure.
# `recovery`: the daemon's fleet-recovery per-instance state dir
# (`global-state/recovery/<project>.json`, written by task_session_liveness on every
# ~60s fleet beat — TRDD-324223a6/F3AUDLOG). These are `.json` (so not caught by the
# append-log suffix rules) and are pure daemon runtime, so a live daemon monitoring
# the fleet mid-run would otherwise false-fail the whole publish suite (observed
# 2026-07-09: three <project>.json recovery records tripped the guard during publish.py
# while all 12253 tests passed). Test-owned recovery writes go through the isolated
# JANITOR_GLOBAL_STATE_DIR, never the REAL dir this guard snapshots.
_GUARD_EXCLUDE_PARTS = ("oauth-rotator", ".memgrep", "recovery")


_KEYCHAIN_USABLE_CACHE: bool | None = None


def _keychain_usable() -> bool:
    """Fast probe: is `security` functional for a REAL round-trip — checked against a
    THROWAWAY TEMP keychain, NEVER the user's login keychain (TRDD-K3WQ7XM9 FIX B).

    Previously this add→read→delete'd against the LOGIN keychain; even though its fresh
    item (created by /usr/bin/security) never PROMPTED, it still TOUCHED the real login
    keychain — which the no-real-keychain-in-tests rule forbids, and a fresh `/login` that
    left the keychain locked/prompting made the READ HANG (timed out publish.py's gate at
    600s, 2026-07-09). Now it creates its OWN temp keychain, round-trips one item confined
    to it via the trailing-keychain positional, and deletes it — so a locked/prompting
    login keychain can neither hang nor prompt this probe, and the login keychain is never
    touched. Cached so the (<8s) probe runs at most once per session."""
    global _KEYCHAIN_USABLE_CACHE
    if _KEYCHAIN_USABLE_CACHE is not None:
        return _KEYCHAIN_USABLE_CACHE
    import sys

    _KEYCHAIN_USABLE_CACHE = _security_temp_keychain_roundtrip_ok() if sys.platform == "darwin" else False
    return _KEYCHAIN_USABLE_CACHE


def _security_temp_keychain_roundtrip_ok() -> bool:
    """add→read one item in a THROWAWAY temp keychain (never the login keychain), then
    delete the keychain. True iff the round-trip succeeded. Timeouts/errors → False."""
    import subprocess
    import tempfile

    probe_dir = tempfile.mkdtemp(prefix="janitor-probe-kc-")
    kc = os.path.join(probe_dir, "probe.keychain-db")
    pw, svc, acct = "janitor-probe-pw", "janitor-conftest-probe", "probe@example.test"
    try:
        create = subprocess.run(["security", "create-keychain", "-p", pw, kc],
                                capture_output=True, text=True, timeout=8)
        if create.returncode != 0:
            return False
        subprocess.run(["security", "unlock-keychain", "-p", pw, kc],
                       capture_output=True, text=True, timeout=8)
        add = subprocess.run(["security", "add-generic-password", "-U", "-s", svc, "-a", acct, "-w", "probe", kc],
                             capture_output=True, text=True, timeout=8)
        read = subprocess.run(["security", "find-generic-password", "-s", svc, "-a", acct, "-w", kc],
                              capture_output=True, text=True, timeout=8)
        return add.returncode == 0 and read.returncode == 0 and read.stdout.strip() == "probe"
    except (subprocess.TimeoutExpired, OSError):
        return False
    finally:
        try:
            subprocess.run(["security", "delete-keychain", kc], capture_output=True, text=True, timeout=8)
        except (subprocess.TimeoutExpired, OSError):
            pass
        shutil.rmtree(probe_dir, ignore_errors=True)


@pytest.fixture
def isolated_keychain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> "Iterator[Path]":
    """A REAL but ISOLATED macOS keychain for keychain round-trip tests (TRDD-K3WQ7XM9 FIX B).

    Creates a temp keychain via ``security create-keychain``, points
    ``JANITOR_ROTATOR_KEYCHAIN`` at it (so every rotator/safe_storage ``security`` op is
    confined to it by ``safe_storage.keychain_scope_args()``), and deletes it on teardown.
    A genuine ``security`` round-trip that honors the no-mocks rule while NEVER touching /
    prompting / unlocking the user's real LOGIN keychain — the fix for the ~100× password
    prompt storm the OAuth ``real_state`` tests caused (2026-07-09). Skips off-macOS, when
    ``security`` is absent, or if the temp keychain cannot be created. ``set-keychain-settings``
    with no ``-t`` disables auto-lock so the keychain stays unlocked (no re-prompt) for the
    test's duration."""
    import subprocess as _sp
    import sys as _sys

    if _sys.platform != "darwin" or shutil.which("security") is None:
        pytest.skip("macOS `security` keychain not available")
    kc = tmp_path / "janitor-test.keychain-db"
    pw = "janitor-test-pw"  # noqa: S105 - a throwaway temp-keychain password, not a secret
    try:
        _sp.run(["security", "create-keychain", "-p", pw, str(kc)],
                check=True, capture_output=True, text=True, timeout=15)
        _sp.run(["security", "unlock-keychain", "-p", pw, str(kc)],
                check=True, capture_output=True, text=True, timeout=15)
        # No `-t <timeout>` → auto-lock disabled → the keychain never re-locks (and so never
        # re-prompts) mid-test.
        _sp.run(["security", "set-keychain-settings", str(kc)],
                check=False, capture_output=True, text=True, timeout=15)
    except (_sp.CalledProcessError, _sp.TimeoutExpired, OSError) as exc:
        pytest.skip(f"could not create isolated temp keychain: {exc}")
    monkeypatch.setenv("JANITOR_ROTATOR_KEYCHAIN", str(kc))
    try:
        yield kc
    finally:
        _sp.run(["security", "delete-keychain", str(kc)],
                check=False, capture_output=True, text=True, timeout=15)


@pytest.fixture(autouse=True)
def _skip_real_state_when_keychain_prompting(request: "pytest.FixtureRequest") -> None:
    """GLOBAL guard: a `real_state` test that reads the real macOS keychain HANGS when a
    fresh `/login` leaves the keychain prompting. Skip every such test when the keychain
    is unusable, so an unattended publish never hangs (was tripping test_oauth_rotator,
    test_safe_storage, test_cookie_vault on 2026-07-09). Non-real_state tests are a fast
    no-op — the probe only runs for a real_state-marked test, and it is cached. The
    keychain becomes usable again once the user unlocks it / grants `security` access."""
    if request.node.get_closest_marker("real_state") and not _keychain_usable():
        pytest.skip("real macOS keychain locked/prompting for access — skipping real_state test (would hang `security`)")


def _manifest(root: Path) -> dict[str, str]:
    """Content manifest {relpath: sha256} of every guarded file under ``root``."""
    if not root.is_dir():
        return {}
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        if any(part in _GUARD_EXCLUDE_PARTS for part in p.parts):
            continue
        if p.name.endswith(_GUARD_EXCLUDE_SUFFIXES):
            continue
        try:
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            continue  # vanished mid-scan (live daemon churn) — treat as excluded
    return out


def _setup_session_keychain() -> None:
    """Create a session-wide REAL temp keychain and point JANITOR_ROTATOR_KEYCHAIN at it, so
    EVERY test's `security` call is confined to it — the login keychain is never touched
    (TRDD-K3WQ7XM9 P2). macOS-only + best-effort: if `security`/create-keychain is
    unavailable it is a no-op (there is then no `security` to run either). `create-keychain`
    with a known password never prompts, and no-autolock keeps it unlocked all session."""
    global _SESSION_KEYCHAIN
    import subprocess as _sp
    import sys as _sys

    if _sys.platform != "darwin" or shutil.which("security") is None or _SESSION_TMP is None:
        return
    kc = str(_SESSION_TMP / "session.keychain-db")
    pw = "janitor-session-pw"  # throwaway temp-keychain password, not a secret
    try:
        if _sp.run(["security", "create-keychain", "-p", pw, kc],
                   capture_output=True, text=True, timeout=15).returncode != 0:
            return
        _sp.run(["security", "unlock-keychain", "-p", pw, kc], capture_output=True, text=True, timeout=15)
        _sp.run(["security", "set-keychain-settings", kc], capture_output=True, text=True, timeout=15)  # no autolock
    except (_sp.SubprocessError, OSError):
        return
    _SESSION_KEYCHAIN = kc
    os.environ["JANITOR_ROTATOR_KEYCHAIN"] = kc


def _teardown_session_keychain() -> None:
    global _SESSION_KEYCHAIN
    if _SESSION_KEYCHAIN is None:
        return
    import subprocess as _sp

    try:
        _sp.run(["security", "delete-keychain", _SESSION_KEYCHAIN], capture_output=True, text=True, timeout=15)
    except (_sp.SubprocessError, OSError):
        pass
    _SESSION_KEYCHAIN = None


@pytest.fixture(autouse=True)
def _clear_keychain_latch_between_tests() -> "Iterator[None]":
    """Reset ALL leakable Safe-Keychain-Protocol state before AND after every test
    (TRDD-K3WQ7XM9 P2) — two distinct cross-test leaks, both fixed here:

    1. The denied-latch file (``$JANITOR_GLOBAL_STATE_DIR/keychain-denied.latch``): a test
       that trips the latch would otherwise short-circuit a later test's `security` ops.
    2. ``JANITOR_ROTATOR_HEADLESS``: the daemon's ``task_oauth_rotator_tick`` sets it via
       ``os.environ[...] = "1"`` DIRECTLY (not monkeypatch), so a full-suite test that
       exercises the daemon tick leaks headless=1 to EVERY later test →
       ``_read_live_primary`` skips its read and returns None (observed: the publish G4
       gate failed only on ``test_write_live_blob_mirrors_to_livebak``, which passed in
       isolation). ``os.environ.pop`` is the direct inverse of that direct set; tests that
       need it set it themselves (via monkeypatch, auto-restored).

    Clearing at SETUP (before the body) is the load-bearing half — it resolves the SAME
    latch path ``run_security`` uses and strips a leaked env, so the test starts clean
    regardless of what an earlier test left behind."""
    def _reset() -> None:
        gsd = os.environ.get("JANITOR_GLOBAL_STATE_DIR", "")
        if gsd:
            try:
                os.remove(os.path.join(gsd, "keychain-denied.latch"))
            except OSError:
                pass
        os.environ.pop("JANITOR_ROTATOR_HEADLESS", None)
    _reset()
    yield
    _reset()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "real_state: opt out of the session-default janitor state isolation for this test "
        "(restores the REAL HOME / JANITOR_GLOBAL_STATE_DIR / JANITOR_DATA_DIR / "
        "CLAUDE_PLUGIN_DATA env). Use ONLY for tests that must observe real machine state.",
    )
    global _SESSION_TMP
    for name in _ISOLATION_ENVS:
        _REAL_ENV[name] = os.environ.get(name)

    # S1b snapshot of the REAL dirs — resolved from the REAL env before we redirect it.
    # Only the xdist controller (or a plain run) owns the guard.
    if not hasattr(config, "workerinput"):
        real_home = Path(_REAL_ENV["HOME"] or str(Path.home()))
        real_gsd = Path(
            _REAL_ENV["JANITOR_GLOBAL_STATE_DIR"] or str(real_home / ".claude" / "janitor-global-state")
        )
        real_data = Path(
            _REAL_ENV["JANITOR_DATA_DIR"]
            or str(real_home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins")
        )
        _GUARDED["global-state"] = (real_gsd, _manifest(real_gsd))
        _GUARDED["plugin-data"] = (real_data, _manifest(real_data))

    _SESSION_TMP = Path(tempfile.mkdtemp(prefix="janitor-test-session-"))
    home = _SESSION_TMP / "_home"
    data = home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
    gsd = _SESSION_TMP / "_global-state"
    for d in (home, data, gsd):
        d.mkdir(parents=True, exist_ok=True)
    # Tests that shell out to `git commit` need an identity now that HOME is fake.
    (home / ".gitconfig").write_text(
        "[user]\n\tname = Emasoft\n\temail = 713559+Emasoft@users.noreply.github.com\n",
        encoding="utf-8",
    )
    os.environ["HOME"] = str(home)
    os.environ["JANITOR_GLOBAL_STATE_DIR"] = str(gsd)
    os.environ["JANITOR_DATA_DIR"] = str(data)
    os.environ["CLAUDE_PLUGIN_DATA"] = str(data)
    os.environ.pop("XDG_STATE_HOME", None)
    _setup_session_keychain()  # session-default temp keychain — no test touches the login keychain


@pytest.fixture(autouse=True)
def _real_state_optout(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore the saved REAL env for tests explicitly marked ``real_state``."""
    if request.node.get_closest_marker("real_state") is None:
        return
    for name, value in _REAL_ENV.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """S1b: fail the suite if the run mutated guarded real state."""
    if not _GUARDED:
        return
    diffs: list[str] = []
    for label, (root, before) in _GUARDED.items():
        after = _manifest(root)
        for rel in sorted(set(before) | set(after)):
            if before.get(rel) == after.get(rel):
                continue
            kind = "ADDED" if rel not in before else ("REMOVED" if rel not in after else "CHANGED")
            diffs.append(f"  [{label}] {kind}: {root / rel}")
    if diffs:
        print("\n" + "=" * 78)
        print("REAL-STATE WRITE GUARD FAILED (TRDD-A8DRPZFM S1b): the test run mutated")
        print("guarded machine state. A test escaped isolation — find and fix it before")
        print("trusting this suite. (A daemon self-update mid-run can rarely false-positive;")
        print("re-run to confirm.) Mutations:")
        print("\n".join(diffs))
        print("=" * 78)
        session.exitstatus = 3


def pytest_unconfigure(config: pytest.Config) -> None:
    global _SESSION_TMP
    _teardown_session_keychain()  # delete the session-default temp keychain
    if _SESSION_TMP is not None:
        shutil.rmtree(_SESSION_TMP, ignore_errors=True)
        _SESSION_TMP = None


# ─── Rotator-path isolation (unchanged behavior) ─────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_rotator_paths(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    rotator = getattr(request.module, "rotator", None)
    if rotator is None or not hasattr(rotator, "LOG_FILE"):
        return  # not a rotator test module — do nothing (and don't force a tmp_path)
    # Lazy: only rotator tests pay for a tmp dir. When the test itself also requests tmp_path,
    # this resolves to the SAME instance, so any test-local re-point of ROOT/STATE_FILE/SLOTS
    # stays consistent while LOG_FILE (which tests routinely forget) stays isolated by default.
    root: Path = request.getfixturevalue("tmp_path")
    monkeypatch.setattr(rotator, "ROOT", root, raising=False)
    monkeypatch.setattr(rotator, "LOG_FILE", root / "rotator.log", raising=False)


# ── Shared tree-built memgrep resolver (F13, wikimem audit) ─────────────────────────────
#
# The user-mem search e2e tests (lib AND hook) exec the real memgrep. F13 changed the
# `find` CLI contract (a literal `-` query reads the query from STDIN), so a STALE
# installed binary on PATH would fail them — the tests MUST run the binary built from
# THIS tree: prebuilt target/ first, cargo build next, PATH only as a last resort.

_MEMGREP_CRATE_DIR = Path(__file__).resolve().parent.parent / "scripts" / "memgrep"


def find_or_build_memgrep() -> str | None:
    """A `memgrep` matching THIS tree's sources, or None (callers then skip)."""
    import subprocess as _subprocess

    for rel in ("target/release/memgrep", "target/debug/memgrep"):
        cand = _MEMGREP_CRATE_DIR / rel
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    cargo = shutil.which("cargo")
    if cargo:
        try:
            _subprocess.run(
                [cargo, "build", "--release", "--manifest-path", str(_MEMGREP_CRATE_DIR / "Cargo.toml")],
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except (_subprocess.CalledProcessError, _subprocess.TimeoutExpired, OSError):
            pass
        built = _MEMGREP_CRATE_DIR / "target" / "release" / "memgrep"
        if built.is_file():
            return str(built)
    return shutil.which("memgrep")


# Resolved once per session — importable by test modules (`from conftest import ...`).
MEMGREP_BIN_PATH = find_or_build_memgrep()
