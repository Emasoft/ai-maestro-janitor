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
import json
import os
import pwd
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest

# The write sandbox lives in a MODULE (not in conftest) so a CHILD process can import it too —
# see sandbox_guard's docstring. pytest puts this dir on sys.path, so a plain import works.
import sandbox_guard

# ─── S1a/S1b module state (filled by pytest_configure) ──────────────────────────────────

_ISOLATION_ENVS = ("HOME", "JANITOR_GLOBAL_STATE_DIR", "JANITOR_DATA_DIR", "CLAUDE_PLUGIN_DATA")
_REAL_ENV: dict[str, str | None] = {}
_SESSION_TMP: Path | None = None
# Session-default temp keychain (TRDD-K3WQ7XM9 P2): every test's `security` calls are scoped
# to THIS isolated keychain via JANITOR_ROTATOR_KEYCHAIN, so NO test can touch the login
# keychain. Round-trip tests override it per-test with the fresh `isolated_keychain` fixture.
_SESSION_KEYCHAIN: str | None = None
# label -> (real dir, before-manifest, the snapshot fn that BUILT it — sessionfinish must
# re-snapshot with the SAME function or the diff is pure noise)
_GUARDED: dict[str, tuple[Path, dict[str, str], "Callable[[Path], dict[str, str]]"]] = {}

# S1f — the live-daemon witness (see the long note at the _GUARDED setup site).
_DAEMON_WITNESS: dict[str, tuple[int, int] | None] = {}


def daemon_ticked(
    before: tuple[int, int] | None,
    after: tuple[int, int] | None,
    *,
    started_at: int | None = None,
) -> bool:
    """PROOF that one live daemon ran across the whole session. PURE (tested directly).

    True when a LIVE daemon was present at both ends AND its heartbeat ADVANCED. The two
    weaker signals stay False, because each is a way a test leak could hide behind a daemon
    that was not actually doing the writing:
      - no daemon at either end        -> nothing to credit a write to
      - a frozen heartbeat             -> a stale pid file / a wedged process, writing nothing

    A CHANGED pid is explicitly NOT disqualifying (fixed 2026-07-21). It used to be, on the
    reasoning "the daemon we witnessed is not the one that wrote" — but the janitor respawns
    its own daemon as a matter of routine (self-update after a release, `daemon_needs_restart`
    on a stale version, the wedged-daemon kill in `ensure_daemon_running`). A release day is
    therefore the most likely time for a pid to change mid-suite, which made the whole suite
    exit non-zero — through `publish.py`'s G4 gate — precisely while publishing. A test that
    "fails" only when the system under test is behaving normally is worse than no test.

    Relaxing it does not open the hole the check was guarding. `_daemon_witness` verifies the
    pid is a LIVE process at each end, and a leaking test writes project/plugin state, never
    `daemon.pid` + an advancing `daemon.heartbeat.ts` in the REAL global-state dir (every test
    is isolated to a tmp dir). So "a live daemon at both ends with an advanced heartbeat" is
    already proof that a daemon ran and wrote across the window — whether or not it is
    numerically the same process.

    `before is None` is likewise not disqualifying WHEN `started_at` is supplied and the
    daemon's heartbeat is newer than it. That is the "daemon was down at snapshot time and
    came up during the run" case — which is the SAME release-day self-update as above, just
    caught at the other edge (the suite happened to snapshot in the gap between the old
    daemon exiting and the new one writing its pid). It still wrote the files it wrote.
    Requiring `after[1] >= started_at` is what keeps the wedged-daemon negative intact: a
    stale pid file whose process is alive but frozen has a heartbeat OLDER than the run, so
    it is still refused. Without `started_at` we cannot tell those apart, so the answer
    stays False — no clock, no credit.

    A daemon that was alive at the START and is GONE at the end also counts. It wrote what
    it wrote and then left — which is now a FIRST-CLASS event, not an anomaly: since
    v0.59.0 the daemon deliberately exits the moment an ai-maestro server claims the host
    (ARCHITECTURE §7.2), and that is exactly what happened the first time a real server came
    up mid-suite. Refusing it would blame the departed daemon's writes on the tests and fail
    every suite run that overlaps a server start — including `publish.py`'s own gate, which
    is how it was found.

    The one case that stays False is `before is None and after is None`: no daemon at either
    end and no start-time evidence means nothing was running to credit, so any mutation of
    the guarded dirs is a real test leak.
    """
    if after is None:
        return before is not None
    if before is None:
        return started_at is not None and after[1] >= started_at
    return after[1] > before[1]


def _other_janitor_actor_live() -> bool:
    """True iff something OTHER than this test process legitimately writes the janitor's
    machine-global state right now.

    The write-guard's premise — "only this suite and the local daemon touch these paths" —
    was true when the janitor was the only actor on a host. It no longer is. An ai-maestro
    server now claims the host and owns the absorbed chores (ARCHITECTURE §7.2); several
    Claude sessions run heartbeats that write the shared attribution cache; the memory
    subconscious agent edits USER-scope wiki pages that are shared across every project. All
    of that is correct behaviour, and none of it is the suite.

    So for the daemon-owned labels a mutation is no longer evidence of a test leak whenever
    another actor is live. This mirrors the decision already made one section below for the
    CREDENTIAL witness, for the same stated reason: a live Claude session rewrites its own
    token on its own schedule, so failing on it "would cry wolf on the majority of real
    runs — and a guard that cries wolf is a guard people learn to ignore, which is exactly
    how the 2026-07-11 clobber hid in plain sight."

    What is NOT softened: the SOURCE TREE (S1c) and LAUNCHD labels stay hard failures. No
    other actor writes this repo's `scripts/` or registers an OS service mid-run, so there
    the original inference still holds — and the source tree is where the incident that
    motivated the whole guard actually happened. On a quiet host (no daemon, no server) the
    daemon-owned labels remain hard failures too, because then a mutation really is the tests.
    """
    # `scripts/lib` is NOT on sys.path in conftest's context. The first cut of this function
    # imported `harness_backend` bare and let `except Exception` swallow the resulting
    # ModuleNotFoundError, so the probe silently answered False and the guard kept failing
    # every publish while a server was demonstrably alive. A fail-open except clause around
    # an import hides a broken probe as effectively as it hides a broken host, so the path is
    # made explicit here and only the CALL is allowed to degrade.
    # Resolve the liveness file from the REAL home, never from os.environ. HOME is still
    # redirected into a test sandbox when this runs at session finish — which is exactly why
    # `_GUARDED`'s own roots are built from `_REAL_ENV["HOME"]` a few lines below. Calling
    # `harness_backend.server_is_alive()` here instead read `$HOME/.aimaestro/...` inside the
    # sandbox, found nothing, and answered "no server" while one was demonstrably running.
    # That was the second silent failure of this probe in a row: first a swallowed import
    # error, then a redirected env. Both looked identical from outside — "no other actor" —
    # which is the hazard of a fail-open probe, so this reads the path directly and depends
    # on no ambient state at all.
    real_home = _REAL_ENV.get("HOME") or str(Path.home())
    liveness = Path(real_home) / ".aimaestro" / "server-liveness.json"
    try:
        payload = json.loads(liveness.read_text(encoding="utf-8"))
        # Same 90s staleness window the janitor itself applies (ARCHITECTURE §6.1): a
        # crashed server leaves its last file on disk forever, and a stale file must not
        # excuse anything.
        if int(time.time()) - int(payload.get("ts", 0)) <= 90:
            return True
    except Exception:
        pass
    roots = [root for _label, (root, _b, _s) in _GUARDED.items()]
    return _daemon_witness(*roots) is not None


def _daemon_witness(*roots: Path) -> tuple[int, int] | None:
    """Return `(pid, heartbeat_epoch)` of a RUNNING janitor daemon, or None.

    The daemon writes `daemon.pid` + `daemon.heartbeat.ts` into its global-state dir. The
    dir moved to the plugin-DATA dir (TRDD-2U8AH82F) with the legacy path kept as a
    read-fallback, so check every candidate root rather than assuming one.
    """
    for root in roots:
        for base in (root, root / "global-state"):
            try:
                pid = int((base / "daemon.pid").read_text(encoding="utf-8").strip())
                beat = int((base / "daemon.heartbeat.ts").read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
            try:
                os.kill(pid, 0)  # signal 0 = liveness probe, sends nothing
            except (OSError, ProcessLookupError):
                continue
            return (pid, beat)
    return None

# Files the live daemon legitimately churns while a suite runs — excluded from the S1b
# guard so it detects TEST pollution, not daemon liveness. Everything else under the real
# dirs (staged *.py closure, *.flag, quarantine/last-good json, memory pages) stays
# guarded: a test mutating any of those fails the whole suite.
_GUARD_EXCLUDE_SUFFIXES = (
    ".ts",
    ".log",
    ".log.1",
    ".jsonl",
    ".ndjson",
    ".pid",
    ".lock",
    ".flock",
    # code-review 2026-07-07: integrity .bak mirrors are rewritten beside every primary
    # write; sqlite sidecars (.memgrep index, Chrome profile DBs) churn on any live
    # daemon memory/rotator activity — all daemon-legit, none test-pollution-specific.
    ".bak",
    ".pyc",
    ".db",
    ".db-wal",
    ".db-shm",
    ".sqlite",
    ".sqlite3",
    # 2026-07-09: daemon-liveness files the LIVE daemon rewrites on any (re)spawn /
    # keepalive restage — pure daemon runtime, never test-written (tests use the
    # isolated JANITOR_GLOBAL_STATE_DIR). `daemon.spawn-history` churns on every daemon
    # spawn; `daemon-keepalive.restage-stamp` on every closure restage. A daemon
    # rollback/respawn mid-suite false-failed the whole publish gate (exit 3) while all
    # tests passed — same class as the already-excluded .ts/.pid stamps + `recovery`.
    ".spawn-history",
    ".restage-stamp",
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


# ─── S1e — the HARD WRITE SANDBOX (TRDD-RYZCVVKA) ───────────────────────────────────────
#
# WHY a sandbox and not another fixture: every layer before this one was OPT-IN, and every
# one of them was escaped.
#   * Per-module `_isolate_janitor_state` fixtures (test_keepalive_*.py) redirect the env —
#     yet the REAL keepalive boot log holds 296 lines whose restage SOURCE is a pytest tmp
#     dir. Tests wrote production state straight through their own isolation.
#   * The S1a session-default env redirect still leaves `@pytest.mark.real_state` and any
#     process that resolves a path WITHOUT reading the env.
#   * The S1b/S1c manifest guards only DETECT, after the fact — and S1b explicitly excludes
#     `.log` and `.restage-stamp` as "daemon liveness", which are precisely the two files the
#     2026-07-11 clobber wrote. The guard was blind to its own incident.
#
# So this layer does not ask a test to isolate itself. It makes the write FAIL. The two roots
# below are the ones the suite actually damaged: the user's live `~/.claude` tree, and this
# repo's own source, which was overwritten with the installed v0.39.0 — silently reverting
# committed work and clearing exec bits.
def _real_home() -> Path:
    """The OS's record of this user's home — NOT `$HOME`, and not `expanduser("~")`.

    This used to be `Path(os.path.expanduser("~")).resolve()`, which reads `$HOME` and was
    correct only by IMPORT ORDER: conftest is imported before the session fixture below
    replaces `$HOME` with a temp dir, so the value happened to be the real home.

    That assumption breaks the moment the suite is sharded. An xdist worker is a fresh
    process that inherits the CONTROLLER's already-mutated environment, so it imports this
    file with `$HOME` ALREADY pointing at the fake home — and then every protected path in
    `_SANDBOX_DENY` is computed against the fake tree. The guard would go on reporting that
    it was armed while protecting a temp directory, leaving the user's REAL `~/.claude`
    (live plugin DATA, global-state, rules, memory) unguarded for the whole run. The
    positive control `test_open_write_into_real_claude_tree_is_blocked` is what caught it:
    under `-n` it wrote its probe successfully and failed with DID NOT RAISE.

    `pwd.getpwuid(os.getuid())` answers from the passwd database, which no environment
    mutation can reach — so the value is the same in the controller, in a worker, before or
    after the fixture, and the guard cannot be silently disarmed by inheriting an env.
    """
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    except (KeyError, OSError):  # no passwd entry (a container); fall back, still resolved
        return Path(os.path.expanduser("~")).resolve()


_REAL_HOME_AT_IMPORT = _real_home()
_REPO_ROOT = Path(__file__).resolve().parent.parent

_SANDBOX_DENY: tuple[Path, ...] = (
    _REAL_HOME_AT_IMPORT / ".claude",  # live plugin DATA, global-state, rules, memory
    *(_REPO_ROOT / d for d in ("scripts", "rules", "skills", "agents", "commands", "hooks", "design", ".claude-plugin")),
)

# The guard itself lives in `sandbox_guard` (a MODULE, not conftest code) for one reason: a
# child process cannot import conftest. Patching syscalls here protects only THIS interpreter,
# and a test that spawns `subprocess.run([sys.executable, …])` hands the child a completely
# unpatched Python, free to write anywhere — which is precisely the shape of the incident this
# sandbox exists to prevent, and was demonstrated live on 2026-07-11 when the running daemon
# wrote the real plugin-data dir mid-suite and this sandbox never saw it. `_export_sandbox`
# below installs it in every descendant too, so there is ONE rule enforced in ONE place.
SandboxViolation = sandbox_guard.SandboxViolation
_SANDBOX_BOOT_DIR = _REPO_ROOT / "tests" / "_sandbox_boot"


def _install_write_sandbox() -> None:
    sandbox_guard.install(_SANDBOX_DENY)


def _remove_write_sandbox() -> None:
    sandbox_guard.remove()


def _export_write_sandbox_to_children() -> None:
    """Make every CHILD Python process boot with the same sandbox.

    Two env vars do it: the protected roots (a child cannot recompute them — by the time it
    runs, HOME points into a tmp tree), and a PYTHONPATH carrying `_sandbox_boot/`, whose
    `sitecustomize.py` CPython auto-imports at interpreter startup. Prepended, never replacing
    an existing PYTHONPATH.
    """
    sandbox_guard.publish_roots(_SANDBOX_DENY)
    entries = [str(_SANDBOX_BOOT_DIR), str(_REPO_ROOT / "tests")]
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        entries.extend(e for e in existing.split(os.pathsep) if e and e not in entries)
    os.environ["PYTHONPATH"] = os.pathsep.join(entries)


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
        create = subprocess.run(["security", "create-keychain", "-p", pw, kc], capture_output=True, text=True, timeout=8)
        if create.returncode != 0:
            return False
        subprocess.run(["security", "unlock-keychain", "-p", pw, kc], capture_output=True, text=True, timeout=8)
        add = subprocess.run(["security", "add-generic-password", "-U", "-s", svc, "-a", acct, "-w", "probe", kc], capture_output=True, text=True, timeout=8)
        read = subprocess.run(["security", "find-generic-password", "-s", svc, "-a", acct, "-w", kc], capture_output=True, text=True, timeout=8)
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
        _sp.run(["security", "create-keychain", "-p", pw, str(kc)], check=True, capture_output=True, text=True, timeout=15)
        _sp.run(["security", "unlock-keychain", "-p", pw, str(kc)], check=True, capture_output=True, text=True, timeout=15)
        # No `-t <timeout>` → auto-lock disabled → the keychain never re-locks (and so never
        # re-prompts) mid-test.
        _sp.run(["security", "set-keychain-settings", str(kc)], check=False, capture_output=True, text=True, timeout=15)
    except (_sp.CalledProcessError, _sp.TimeoutExpired, OSError) as exc:
        pytest.skip(f"could not create isolated temp keychain: {exc}")
    monkeypatch.setenv("JANITOR_ROTATOR_KEYCHAIN", str(kc))
    try:
        yield kc
    finally:
        _sp.run(["security", "delete-keychain", str(kc)], check=False, capture_output=True, text=True, timeout=15)


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


# ─── S1i — the NON-FILE witnesses (keychain + launchd) ──────────────────────────────────
#
# Every guard above compares FILE CONTENT, so the two states the suite can damage that are not
# files were invisible to all of them: the macOS KEYCHAIN (where Claude's OAuth credential
# lives) and LAUNCHD (where the daemon's OS service is registered). On 2026-07-12 the whole
# fleet went down and the test suite was the prime suspect for a day — with no evidence either
# way, because nothing was watching those two. These witnesses are that evidence.

_NONFILE_WITNESS: dict[str, str | None] = {}


def _supervised_read(argv: list[str], timeout: int = 8) -> str | None:
    """Run a READ-ONLY probe that the process sandbox (S1h) would otherwise deny.

    The sandbox refuses unscoped `security` and all `launchctl` — correctly, since they are how
    a test would damage the real keychain / real OS service. But the guard's own SUPERVISOR must
    be able to observe exactly what it forbids, so it takes the sandbox's documented escape
    hatch for the duration of the read and hands it straight back. Scoped to one call, restored
    in `finally`.
    """
    import subprocess as _sp

    previous = os.environ.get(sandbox_guard.ENV_ALLOW_REAL)
    os.environ[sandbox_guard.ENV_ALLOW_REAL] = os.path.basename(argv[0])
    try:
        proc = _sp.run(argv, capture_output=True, text=True, timeout=timeout)
        return proc.stdout if proc.returncode == 0 else None
    except (OSError, _sp.SubprocessError):
        return None  # fail-open: a broken security session must not fail the suite
    finally:
        if previous is None:
            os.environ.pop(sandbox_guard.ENV_ALLOW_REAL, None)
        else:
            os.environ[sandbox_guard.ENV_ALLOW_REAL] = previous


def _credential_witness() -> str | None:
    """The REAL Claude OAuth item's modification date — ATTRIBUTES ONLY, never the secret.

    NOTE THE ABSENT `-w`. Reading an item's SECRET when the caller is not on its ACL raises the
    macOS keychain dialog — the prompt FLOOD that once opened hundreds of modals and locked the
    user out. `find-generic-password` WITHOUT `-w` returns attributes only: no secret, no ACL
    check, no prompt. The `mdat` field is all we need; the value is none of our business.
    """
    import sys as _sys

    if _sys.platform != "darwin":
        return None
    out = _supervised_read(["security", "find-generic-password", "-s", "Claude Code-credentials"])
    if not out:
        return None  # absent, or an unreachable security session — nothing to compare
    return next((ln.strip() for ln in out.splitlines() if '"mdat"' in ln), None)


def _launchd_witness() -> str | None:
    """The janitor's registered OS services. A test must never register or tear one down."""
    import sys as _sys

    if _sys.platform != "darwin":
        return None
    out = _supervised_read(["launchctl", "list"])
    if out is None:
        return None
    # Compare only the service LABELS, never the volatile PID/Status columns. `launchctl list`
    # prints `PID<ws>Status<ws>Label`, and a daemon RESPAWN mid-run changes the PID (or flips
    # PID `-`↔<n>) — which is NOT a register/unregister and must not trip the suite-failing
    # witness. The label (last whitespace-delimited field, never spaced) is the true identity.
    labels = []
    for ln in out.splitlines():
        parts = ln.split()
        label = parts[-1] if parts else ""
        if "janitor" in label.lower():
            labels.append(label)
    return "\n".join(sorted(labels))


def _source_manifest(root: Path) -> dict[str, str]:
    """Content manifest of the SOURCE files under ``root`` — only what a clobber would
    damage: ``*.py`` and ``*.sh``.

    Deliberately NOT `_manifest`: that walks every file, and `scripts/memgrep/target/` is
    1.4 GB of gitignored Rust build artifacts (15,285 files — 97% of the tree). Hashing
    them would make session start slow AND make the guard false-positive the moment anyone
    runs `cargo build` mid-suite. The thing the clobber destroyed was source, so source is
    what we guard.
    """
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix not in (".py", ".sh"):
            continue
        if "__pycache__" in p.parts or "target" in p.parts:
            continue
        try:
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            continue
    return out


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
        if _sp.run(["security", "create-keychain", "-p", pw, kc], capture_output=True, text=True, timeout=15).returncode != 0:
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
        "real_state: opt out of the session-default janitor state isolation for this test (restores the REAL HOME / JANITOR_GLOBAL_STATE_DIR / JANITOR_DATA_DIR / CLAUDE_PLUGIN_DATA env). Use ONLY for tests that must observe real machine state.",
    )
    config.addinivalue_line(
        "markers",
        "real_subprocess(*binaries): allow this test to spawn the named REAL machine binaries "
        "(e.g. \"gh\", \"claude\", \"launchctl\"), which the process sandbox denies by default. "
        "Pass no argument to allow all, and \"kill\" to allow signalling a process this test did "
        "not spawn. Deliberate friction: it makes a real machine-touching call visible in review.",
    )
    global _SESSION_TMP
    for name in _ISOLATION_ENVS:
        _REAL_ENV[name] = os.environ.get(name)

    # S1b snapshot of the REAL dirs — resolved from the REAL env before we redirect it.
    # Only the xdist controller (or a plain run) owns the guard.
    if not hasattr(config, "workerinput"):
        real_home = Path(_REAL_ENV["HOME"] or str(Path.home()))
        real_gsd = Path(_REAL_ENV["JANITOR_GLOBAL_STATE_DIR"] or str(real_home / ".claude" / "janitor-global-state"))
        real_data = Path(_REAL_ENV["JANITOR_DATA_DIR"] or str(real_home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"))
        _GUARDED["global-state"] = (real_gsd, _manifest(real_gsd), _manifest)
        _GUARDED["plugin-data"] = (real_data, _manifest(real_data), _manifest)
        # Attribution, NOT an exclusion list (S1f). The janitor's global DAEMON is a real,
        # long-lived process that legitimately writes its OWN state dir several times a
        # minute (memory-guard ps-snapshots, heartbeat stamps, task last-run stamps). If it
        # happens to be alive while the suite runs, its writes are indistinguishable — by
        # filesystem inspection alone — from a test escaping isolation, so the guard failed
        # the suite for work the daemon was *supposed* to do. That is not a cosmetic nit: a
        # guard that cries wolf is a guard people learn to ignore, which is exactly how the
        # 2026-07-11 clobber hid in plain sight.
        #
        # The tempting fix — excluding the offending filenames — is the SAME mistake that
        # made the earlier guard blind to that very incident (it excluded `.log` and
        # `.restage-stamp` as "daemon noise", and those were the two files the incident
        # wrote). So attribute by PROVENANCE instead: record the daemon's pid and heartbeat
        # now, and at session end require PROOF it was ticking (same pid alive at both ends,
        # heartbeat advanced) before crediting any mutation of its own state dir to it.
        # No live daemon ⇒ every mutation is still a hard failure, exactly as before.
        _DAEMON_WITNESS["before"] = _daemon_witness(real_gsd, real_data)
        # Also stamp WHEN the window opened. If no daemon is visible right now, the witness
        # above is None — which happens routinely on a release day, when the suite snapshots
        # in the gap between the old daemon exiting for a self-update and the replacement
        # writing its pid. Without a start time we cannot distinguish "a daemon came up
        # during the run and wrote" from "a wedged daemon has been frozen since before it",
        # so daemon_ticked refuses to credit either. With it, a heartbeat at or after this
        # instant proves the former.
        _DAEMON_WITNESS["started_at"] = int(time.time())  # type: ignore[assignment]
        # S1c — the SOURCE TREE guard (TRDD-RYZCVVKA). On 2026-07-11 this repo's whole
        # daemon closure was silently overwritten with the INSTALLED plugin's v0.39.0
        # copies: committed work reverted in the working tree, exec bits cleared. It was
        # noticed only because a lost +x bit happened to break 22 tests — a clobber of a
        # file WITHOUT an exec bit would have been invisible, and could have been committed
        # as a regression of already-published code.
        #
        # The write path is now refused at the source (`keepalive_stage.stage_closure`),
        # and instrumenting the suite proved nothing in it stages into the repo. This guard
        # is the backstop for that proof: if any test ever writes `scripts/**` again, the
        # suite FAILS and names the file, instead of the damage being found by accident
        # weeks later. Same shape as the two dir guards above, so it costs one manifest.
        _scripts = Path(__file__).resolve().parent.parent / "scripts"
        _GUARDED["source-tree"] = (_scripts, _source_manifest(_scripts), _source_manifest)

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
    # S1e LAST: the env above is now fake, so anything still resolving a REAL protected path is
    # by definition escaping its boundary — and from here on the write itself is refused.
    _install_write_sandbox()
    # S1g: and every CHILD process the suite spawns inherits the same refusal. Patching syscalls
    # above protects only THIS interpreter; a subprocess gets a clean one and can write anywhere.
    # That is not theoretical — it is how the source tree was clobbered, and it is why the live
    # daemon's writes were invisible to the guard above.
    _export_write_sandbox_to_children()
    # S1i: the two states that are NOT files, and so were invisible to every guard above.
    if not hasattr(config, "workerinput"):
        _NONFILE_WITNESS["credential"] = _credential_witness()
        _NONFILE_WITNESS["launchd"] = _launchd_witness()


@pytest.fixture(autouse=True)
def _isolate_control_dir(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory,
                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Point `JANITOR_CONTROL_DIR` at a per-test tmp dir — for EVERY test, unconditionally.

    The fleet control plane (ARCHITECTURE §7.1) lives at a FIXED literal path,
    `~/.claude/janitor-control/`, precisely so a foreign program can stat it without
    reproducing `global_state_dir()`'s resolution ladder. That same fixedness makes it the
    most dangerous thing in the tree to leave unisolated: unlike the ladder, it does NOT
    move when a test sets `JANITOR_GLOBAL_STATE_DIR`, so any test calling
    `set_kill_switch()` writes the REAL
    machine's control plane. A leaked `kill-switch.flag` disarms the whole fleet; a leaked
    `maintenance-mode.flag` silently idles every daemon chore — which is exactly the
    invisible, hours-long suppression that prompted §7.1 in the first place.

    It is done HERE rather than per-file because the failure is silent and the blast radius
    is the user's machine. Three files (`test_daemon_fleet_stop`, `test_fleet_stop_state`,
    `test_session_start_rearm_guard`) were already writing the live path, and the two
    fleet-stop failures that surfaced it were not "a leak" in appearance at all — they read
    as ordinary assertion errors, because a leftover REAL kill-switch outranks a pause and
    quietly changed what the next test observed. Per-file isolation only protects the files
    someone remembered; this protects the ones nobody has written yet.

    A test that needs its own control dir simply sets the variable itself — monkeypatch
    applies its value after this fixture, so an explicit setenv still wins.
    """
    del request  # kept for symmetry with the sibling autouse fixtures
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path_factory.mktemp("janitor-control")))


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


@pytest.fixture(autouse=True)
def _real_subprocess_optout(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Publish the ``real_subprocess`` opt-in for this test (S1h — the PROCESS sandbox).

    The guard reads the allow-list from the ENVIRONMENT rather than from a module global, for
    the same reason the write sandbox does: a CHILD process inherits the env but not our
    globals, and the dangerous binary is usually spawned one level down (a detector shelling
    `gh`, the daemon shelling `claude`). ``monkeypatch.setenv`` scopes it to this test alone,
    so an opt-in can never leak into the next one.
    """
    marker = request.node.get_closest_marker("real_subprocess")
    if marker is None:
        return
    names = ",".join(str(a) for a in marker.args) if marker.args else "*"
    monkeypatch.setenv(sandbox_guard.ENV_ALLOW_REAL, names)


# The env-dependent path resolvers in `state`. All four are `@lru_cache`d, so the FIRST
# call in a process pins the answer for the whole process; the last two are cached
# predicates ABOUT the resolved project and go stale with it.
_STATE_CACHED_RESOLVERS = (
    "project_root",
    "janitor_root",
    "state_dir",
    "log_dir",
    "is_self_scan_target",
    "project_is_ai_maestro",
)


def _live_state_modules() -> list[ModuleType]:
    """Every `state` module OBJECT alive in this process — including stale copies.

    `sys.modules` holds at most one. The others are the reason this exists: ~22 test
    files isolate themselves with `del sys.modules["state"]`, which unbinds the NAME but
    cannot touch the references its importers already hold. `findings_ledger` does
    `import state` at module level, so after one delete+reimport it points at the OLD
    module — whose `state_dir()` is `lru_cache`d to the PREVIOUS test's tmp dir, or, if
    it bound before any fixture ran, to the REAL REPO. Walking the importers finds those
    copies; clearing only `sys.modules["state"]` would leave every one of them pinned.
    """
    found: dict[int, ModuleType] = {}
    current = sys.modules.get("state")
    if isinstance(current, ModuleType):
        found[id(current)] = current
    # list(): an importer's own import can mutate sys.modules while we walk it.
    for mod in list(sys.modules.values()):
        held = getattr(mod, "state", None)
        if isinstance(held, ModuleType) and getattr(held, "__name__", "") == "state":
            found[id(held)] = held
    return list(found.values())


@pytest.fixture(autouse=True)
def _clear_state_path_caches() -> Iterator[None]:
    """Re-resolve `state`'s cached paths for every test, in every live copy of the module.

    THE fix for the cross-test pollution in TRDD-TSTISOL1, applied at the source: the
    contract is 'a test resolves paths from ITS OWN env', and an `lru_cache` filled by an
    earlier test silently broke it. Two symptoms, one cause — a test that passed alone and
    failed in company (so a green `-k` subset proved nothing and a red one accused innocent
    code), and writes that escaped `tmp_path` into the real repo.

    Clearing beats the `del sys.modules` idiom those tests reach for, because clearing
    fixes every HOLDER at once while deleting fixes only the next importer — and nothing
    in `state` captures a path at import time (verified: no module-level env reads; every
    env-dependent path is behind one of these caches), so there is nothing a reimport
    achieves that a clear does not.

    Runs before AND after: before, so the test sees its own env; after, so a test that
    resolved paths under a monkeypatched env cannot hand that answer to the next one once
    monkeypatch has rolled the env back.
    """

    def _clear() -> None:
        for mod in _live_state_modules():
            for name in _STATE_CACHED_RESOLVERS:
                fn = getattr(mod, name, None)
                cache_clear = getattr(fn, "cache_clear", None)
                if cache_clear is not None:
                    cache_clear()

    _clear()
    yield
    _clear()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """S1b: fail the suite if the run mutated guarded real state.

    S1f: a mutation inside the daemon's OWN state dir is credited to the daemon ONLY when we
    can prove it was ticking across the run (same pid alive at both ends AND an advanced
    heartbeat). Those are reported as daemon activity and do not fail the suite. Everything
    else — including any mutation of the source tree, and any global-state write with no live
    daemon to account for it — still fails hard.
    """
    if not _GUARDED:
        return

    before_witness = _DAEMON_WITNESS.get("before")
    after_witness = _daemon_witness(*(root for _l, (root, _b, _s) in _GUARDED.items()))
    # PROOF, not presence — see daemon_ticked() above.
    ticked = daemon_ticked(
        before_witness,
        after_witness,
        started_at=_DAEMON_WITNESS.get("started_at"),  # type: ignore[arg-type]
    )
    # The daemon owns ONLY its own state; it never writes the source tree. Crediting a
    # scripts/** mutation to it would re-open the exact hole S1c exists to close.
    daemon_owned_labels = {"global-state", "plugin-data"}

    diffs: list[str] = []
    daemon_diffs: list[str] = []
    for label, (root, before, snapshot) in _GUARDED.items():
        # Re-snapshot with the SAME function that built `before`. The source-tree guard uses
        # a *.py/*.sh-scoped manifest (the vendored Rust tree under scripts/memgrep/target is
        # 15k gitignored build artifacts); re-snapshotting it with the unscoped _manifest made
        # every .rs/.toml/.DS_Store read as "ADDED" and drowned real failures in noise.
        after = snapshot(root)
        for rel in sorted(set(before) | set(after)):
            if before.get(rel) == after.get(rel):
                continue
            kind = "ADDED" if rel not in before else ("REMOVED" if rel not in after else "CHANGED")
            line = f"  [{label}] {kind}: {root / rel}"
            if (ticked or _other_janitor_actor_live()) and label in daemon_owned_labels:
                daemon_diffs.append(line)
            else:
                diffs.append(line)

    if daemon_diffs and not diffs:
        # Informational, never silent: the reader must be able to tell "the daemon was busy"
        # apart from "the guard found nothing", or a real leak could later hide in this line.
        pid = after_witness[0] if after_witness else "?"
        print(
            f"\n[write-guard] {len(daemon_diffs)} mutation(s) in the janitor's own state dir "
            f"attributed to a LIVE janitor actor (daemon pid {pid}, and/or an ai-maestro server "
            f"owning this host) — not a test leak. These paths are shared: the server, other "
            f"sessions' heartbeats, and the memory agent all write them legitimately. The SOURCE "
            f"TREE and LAUNCHD labels are still hard failures. Mutations:"
        )
        print("\n".join(daemon_diffs))

    # ── S1i: the non-file witnesses ────────────────────────────────────────────────────────
    #
    # LAUNCHD is a hard failure: nothing but a test registers or tears down a janitor OS
    # service mid-run, so a change is unambiguous test pollution.
    #
    # The CREDENTIAL is REPORTED, never failed — and the difference is the whole lesson of the
    # 2026-07-12 incident. The credential DID get rewritten mid-session, the suite was blamed
    # for a day, and it was innocent: Claude Code had refreshed its OWN token. A live Claude
    # session does that on its own schedule, so failing here would cry wolf on the majority of
    # real runs — and conftest's own comment above says why that is fatal: "a guard that cries
    # wolf is a guard people learn to ignore, which is exactly how the 2026-07-11 clobber hid in
    # plain sight." The process sandbox (S1h) now makes a test-caused change structurally
    # impossible (unscoped `security` is denied), so this line is EVIDENCE, not an alarm — the
    # evidence whose absence cost a day of forensics.
    if _NONFILE_WITNESS:
        if _launchd_witness() != _NONFILE_WITNESS.get("launchd"):
            diffs.append("  [launchd] the janitor's registered OS services CHANGED during the run")
        if _credential_witness() != _NONFILE_WITNESS.get("credential"):
            print(
                "\n[keychain-witness] The REAL 'Claude Code-credentials' item was REWRITTEN "
                "during this run (its mdat moved).\n"
                "  This is almost certainly your live Claude Code session refreshing its own "
                "OAuth token — the exact\n"
                "  signature of the 2026-07-12 fleet outage, where the test suite was blamed "
                "for a day and was innocent.\n"
                "  The process sandbox denies the suite any unscoped `security` call, so a "
                "test cannot have done this."
            )

    if diffs:
        print("\n" + "=" * 78)
        print("REAL-STATE WRITE GUARD FAILED (TRDD-A8DRPZFM S1b): the test run mutated")
        print("guarded machine state. A test escaped isolation — find and fix it before")
        print("trusting this suite. (A daemon self-update mid-run can rarely false-positive;")
        print("re-run to confirm.) Mutations:")
        print("\n".join(diffs))
        if daemon_diffs:
            print("\nAlso seen, attributed to the LIVE daemon (not counted as failures):")
            print("\n".join(daemon_diffs))
        print("=" * 78)
        session.exitstatus = 3


def pytest_unconfigure(config: pytest.Config) -> None:
    global _SESSION_TMP
    # S1e FIRST: restore the real syscalls before any teardown below needs them — the session
    # tmp tree is outside every protected root, but the sandbox must never outlive the session.
    _remove_write_sandbox()
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


# ── 3. Deterministic USER-PRESENCE for the self-trigger tests ───────────────────────
#
# The four self-triggers (compact / reload / reload-skills / resume) refuse to type into the
# session's own pane while the USER is at the keyboard (TRDD-RDFWQIFA's sibling): typing `/compact`
# into a pane someone is mid-sentence in DESTROYS what they were writing. It happened.
#
# `user_intent.user_is_present` fails CLOSED — an absent or unreadable breadcrumb means "assume they
# are there" — so a test that does not pin HOME inherits the DEVELOPER's real breadcrumb and its
# result depends on whether whoever ran the suite happened to be typing. That is a test reporting on
# the tester, not the code. These helpers pin it.


def away_home(tmp: Path) -> Path:
    """A HOME whose breadcrumb says the user is UNATTENDED, so injection is permitted."""
    return _presence_home(tmp, present=False)


def present_home(tmp: Path) -> Path:
    """A HOME whose breadcrumb says the user is AT THE KEYBOARD, so injection must be refused."""
    return _presence_home(tmp, present=True)


def _presence_home(tmp: Path, *, present: bool) -> Path:
    import json as _json
    import time as _time

    h = tmp / ("home-present" if present else "home-away")
    (h / ".aimaestro" / "state").mkdir(parents=True, exist_ok=True)
    # `last_user_input_epoch: 0` means "no user input was EVER recorded" → unattended. A fresh epoch
    # means they typed seconds ago.
    (h / ".aimaestro" / "state" / "user-presence.json").write_text(
        _json.dumps(
            {
                "last_user_input_epoch": int(_time.time()) if present else 0,
                "written_at_epoch": int(_time.time()),
            }
        ),
        encoding="utf-8",
    )
    return h


@pytest.fixture(autouse=True)
def _pin_hid_probe_unavailable(monkeypatch):
    """Pin the machine-wide HID typing probe (TRDD-6Q0OYYYH) to 'unavailable' for EVERY test.

    `user_intent.hid_idle_seconds` reads the REAL macOS IOHIDSystem idle time — the seconds
    since the LIVE human's last keystroke. Left unpinned, any presence/injection test would
    flip with whether a person happens to be typing while the suite runs (the
    janitor-keepalive-test-isolation class of flake: real host state leaking into tests).
    None = probe unavailable → every gate falls through to its deterministic breadcrumb
    rungs, the pre-HID behavior the existing tests encode. Tests OF the HID rung override
    this locally with explicit values.

    Pins BOTH module identities of the same file — ``user_intent`` (bare lib import) AND
    ``lib.user_intent`` (the hooks' ``from lib import user_intent``) — because Python gives
    the two import paths distinct module objects and patching only one leaves the other
    live (the dual-import trap: the first run of this fixture missed the hooks' copy and
    the real ioreg probe leaked into a popen-capturing test).
    """
    import importlib
    pinned = False
    for name in ("user_intent", "lib.user_intent"):
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "hid_idle_seconds", lambda **_kw: None)
        pinned = True
    # A suite without scripts/lib on sys.path imports neither identity — nothing there
    # consults the probe, so an unpinned run is safe (`pinned` kept for debuggability).
    del pinned
    yield
