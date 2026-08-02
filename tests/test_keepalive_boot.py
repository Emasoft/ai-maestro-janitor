"""Pre-launch integrity-gate contract for the L0 keepalive (TRDD-DGROUPAB, D-β).

Proves the DATA-staged daemon closure self-heals BEFORE ``import daemon``:
  * a corrupt/truncated/missing staged file is DETECTED against the trusted cache, and
  * RESTAGED from the cache so the next ``import daemon`` resolves clean code (acceptance #1),
  * with FAIL-OPEN (a missing/unreadable cache never blocks the launch) and FAIL-LOUD (when
    the stage is broken AND unrepairable, it logs loudly and returns False — the entry then
    lets ``import daemon`` fail VISIBLY, never a silent crash-loop) (acceptance #2).

No mocks: every test builds REAL on-disk fake cache + staged trees and runs the real gate.
``latest_cache_scripts_dir`` / ``data_scripts_dir`` are repointed via monkeypatch so the host
is never touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS / "lib"))

import keepalive_boot  # type: ignore[import-not-found]  # noqa: E402
import keepalive_stage  # type: ignore[import-not-found]  # noqa: E402
import launchd_keepalive  # type: ignore[import-not-found]  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_janitor_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect every janitor global-state / DATA / HOME path to a per-test tmp tree so no
    keepalive test can read or write the real ~/.claude/janitor-global-state/ or the real
    plugin DATA dir. A frozen module constant (keepalive_boot's old _LOG_DIR,
    launchd_keepalive._DATA_DIR) let these tests pollute production state and corrupt the
    real staged closure, driving a 39 GB fseventsd runaway (TRDD-ZNN0UK5K). Env-based so a
    subprocess that re-imports the libs inherits the SAME isolated tree."""
    home = tmp_path / "_home"
    # Keep the FIXED DATA suffix so data_dir()'s shape assertion still holds on a tmp tree.
    data = home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
    gsd = tmp_path / "_global-state"
    for d in (home, data, gsd):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)


def _make_cache(tmp: Path) -> Path:
    """Build a REAL cache scripts dir holding the full staged closure (verbatim from the repo
    ``scripts/``). Returns the cache scripts dir."""
    cache = tmp / "cache" / "scripts"
    cache.mkdir(parents=True)
    keepalive_stage.stage_closure(SCRIPTS, cache)
    return cache


def _make_stage_from(cache: Path, tmp: Path) -> Path:
    """Build a staged dir as a faithful copy of ``cache`` (the post-install good state)."""
    staged = tmp / "data" / "scripts"
    staged.mkdir(parents=True)
    keepalive_stage.stage_closure(cache, staged)
    return staged


# ── stage_mismatches: the verification primitive ─────────────────────────────


def test_faithful_stage_has_no_mismatches(tmp_path: Path) -> None:
    """A staged closure byte-identical to the cache reports ZERO mismatches."""
    cache = _make_cache(tmp_path)
    staged = _make_stage_from(cache, tmp_path)
    assert keepalive_boot.stage_mismatches(staged, cache) == []


def test_missing_staged_file_is_a_mismatch(tmp_path: Path) -> None:
    """A closure file present in the cache but absent from the stage is flagged."""
    cache = _make_cache(tmp_path)
    staged = _make_stage_from(cache, tmp_path)
    (staged / "daemon.py").unlink()
    assert "daemon.py" in keepalive_boot.stage_mismatches(staged, cache)


def test_corrupt_staged_file_is_a_mismatch(tmp_path: Path) -> None:
    """A truncated/garbled staged file (sha256 differs from the cache) is flagged."""
    cache = _make_cache(tmp_path)
    staged = _make_stage_from(cache, tmp_path)
    (staged / "lib" / "global_state.py").write_text("corrupt!\n", encoding="utf-8")
    assert "lib/global_state.py" in keepalive_boot.stage_mismatches(staged, cache)


# ── Acceptance #1: corrupt → restage from cache → clean ──────────────────────


def test_corrupt_stage_is_restaged_from_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance #1: corrupting a staged closure file makes verify_or_restage restage it
    from the cache; afterward the file is byte-identical to the cache and the stage verifies
    clean (the next ``import daemon`` would load good code)."""
    cache = _make_cache(tmp_path)
    staged = _make_stage_from(cache, tmp_path)
    # Repoint resolution at our fake trees and make `staged` look like the canonical DATA dir
    # so _repair takes the production (DATA) path through launchd_keepalive.restage.
    monkeypatch.setattr(launchd_keepalive, "latest_cache_scripts_dir", lambda: cache)
    monkeypatch.setattr(launchd_keepalive, "data_scripts_dir", lambda: staged)

    target = staged / "lib" / "version_update_lib.py"
    good = (cache / "lib" / "version_update_lib.py").read_bytes()
    target.write_text("torn stage\n", encoding="utf-8")
    assert target.read_bytes() != good  # precondition: corrupted

    ok = keepalive_boot.verify_or_restage(str(staged))

    assert ok is True, "a repairable corruption must return True after restage"
    assert target.read_bytes() == good, "the corrupt file must be restored from the cache"
    assert keepalive_boot.stage_mismatches(staged, cache) == [], "stage must verify clean now"


def test_missing_file_is_restaged_from_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deleted staged closure file is re-created from the cache by verify_or_restage."""
    cache = _make_cache(tmp_path)
    staged = _make_stage_from(cache, tmp_path)
    monkeypatch.setattr(launchd_keepalive, "latest_cache_scripts_dir", lambda: cache)
    monkeypatch.setattr(launchd_keepalive, "data_scripts_dir", lambda: staged)

    gone = staged / "daemon.py"
    good = (cache / "daemon.py").read_bytes()
    gone.unlink()
    assert not gone.exists()

    assert keepalive_boot.verify_or_restage(str(staged)) is True
    assert gone.exists() and gone.read_bytes() == good


# ── Acceptance #2 + fail-open / fail-loud ────────────────────────────────────


def test_clean_stage_short_circuits_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An already-faithful stage returns True without restaging (no spurious churn)."""
    cache = _make_cache(tmp_path)
    staged = _make_stage_from(cache, tmp_path)
    monkeypatch.setattr(launchd_keepalive, "latest_cache_scripts_dir", lambda: cache)
    monkeypatch.setattr(launchd_keepalive, "data_scripts_dir", lambda: staged)
    assert keepalive_boot.verify_or_restage(str(staged)) is True


def test_no_cache_is_fail_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FAIL-OPEN: when no cache is resolvable, the gate cannot verify but must NOT block — it
    returns True so the launch proceeds (the import then reveals any real break)."""
    cache = _make_cache(tmp_path)
    staged = _make_stage_from(cache, tmp_path)
    # Corrupt the stage AND make the cache disappear → unverifiable + unrepairable.
    (staged / "daemon.py").write_text("torn\n", encoding="utf-8")
    monkeypatch.setattr(launchd_keepalive, "latest_cache_scripts_dir", lambda: None)
    assert keepalive_boot.verify_or_restage(str(staged)) is True


def test_broken_stage_unrepairable_returns_false_and_logs_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance #2 (fail-LOUD): when the stage is broken and the restage canNOT fix it
    (here: a cache present for verification but the repair raises), verify_or_restage returns
    False AND emits a loud line — so the entry proceeds to import and FAILS VISIBLY, never a
    silent crash-loop."""
    cache = _make_cache(tmp_path)
    staged = _make_stage_from(cache, tmp_path)
    (staged / "daemon.py").write_text("torn\n", encoding="utf-8")
    monkeypatch.setattr(launchd_keepalive, "latest_cache_scripts_dir", lambda: cache)
    monkeypatch.setattr(launchd_keepalive, "data_scripts_dir", lambda: staged)

    def _boom(_staged: Path, _cache: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(keepalive_boot, "_repair", _boom)
    # The boot log is kept off the host by the autouse fixture (JANITOR_GLOBAL_STATE_DIR →
    # tmp); _state_dir() re-resolves it at call time, so no _LOG_DIR patch is needed.

    result = keepalive_boot.verify_or_restage(str(staged))
    assert result is False, "an unrepairable broken stage must return False (fail-loud, not crash)"
    err = capsys.readouterr().err
    assert "keepalive-boot:" in err, "fail-loud must emit a keepalive-boot line to stderr"
    assert "restage FAILED" in err or "no runnable copy" in err


def test_boot_gate_handles_a_source_checkout_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The L0 boot gate must SURVIVE the repo-clobber refusal, not propagate it
    (TRDD-RYZCVVKA, lead 3).

    `stage_closure` refuses a destination inside a plugin SOURCE checkout, and that guard is
    tested at its own level. But `verify_or_restage` is the ONE production caller whose
    destination is not the DATA dir — it is the running entry's OWN directory. Launch the L0
    entry from a repo checkout (`uv run scripts/daemon_keepalive_entry.py`) and the repair
    target IS the source tree, so the refusal fires inside the pre-launch gate.

    A gate that let `UnsafeStageDestination` escape would abort the launch of the
    MACHINE-WIDE guardian — turning a guard against silent data loss into an outage. It must
    behave like every other unrepairable stage: no raise, loud log, return False, and let
    `import daemon` surface the fault visibly.

    Written because the audit that closed RYZCVVKA could only establish this by reading the
    code: `_repair` raising is caught by a broad `except Exception`, so the handling was
    correct but unproven. This makes it executable."""
    cache = _make_cache(tmp_path)
    # A staged dir that IS a plugin source checkout: a git work tree whose ROOT also carries
    # .claude-plugin/plugin.json — exactly what is_plugin_source_checkout looks for.
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".claude-plugin").mkdir()
    (repo / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    staged = repo / "scripts"
    staged.mkdir()
    monkeypatch.setattr(launchd_keepalive, "latest_cache_scripts_dir", lambda: cache)
    monkeypatch.setattr(launchd_keepalive, "data_scripts_dir", lambda: staged)

    result = keepalive_boot.verify_or_restage(str(staged))

    assert result is False, "a refused (source-checkout) repair must return False, not raise"
    err = capsys.readouterr().err
    assert "keepalive-boot:" in err, "the refusal must be reported loudly, never swallowed"
    # And the guard's whole point: the source tree was NOT written into.
    assert list(staged.iterdir()) == [], "the source checkout must be left untouched"


def test_gate_never_raises_on_bad_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """FAIL-OPEN backstop: even a totally bogus argument must not raise out of the gate — it
    swallows everything and returns True so the launch is never aborted by this gate."""
    # Force latest_cache_scripts_dir to blow up; the outer try must still yield True.
    def _explode() -> Path:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(launchd_keepalive, "latest_cache_scripts_dir", _explode)
    assert keepalive_boot.verify_or_restage(object()) is True


def test_loud_helper_writes_stderr_and_logfile(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """_loud emits to BOTH stderr and the keepalive boot-log file (the operator-visible
    surfaces). The log lands in the CALL-TIME _state_dir() (JANITOR_GLOBAL_STATE_DIR,
    isolated to tmp by the autouse fixture) — never a home-frozen dir (TRDD-ZNN0UK5K)."""
    keepalive_boot._loud("hello operator")
    assert "keepalive-boot: hello operator" in capsys.readouterr().err
    logged = (keepalive_boot._state_dir() / keepalive_boot._LOG_NAME).read_text(
        encoding="utf-8"
    )
    assert "hello operator" in logged


# ── TRDD-ZNN0UK5K regressions: test-state isolation + bounded restage churn ───


def test_state_dir_honors_env_at_call_time_not_frozen_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REGRESSION (TRDD-ZNN0UK5K root cause): _state_dir() re-resolves
    JANITOR_GLOBAL_STATE_DIR at CALL time, so a _loud write lands in whatever the env
    currently points at — never the home-frozen ~/.claude/janitor-global-state constant
    that made these tests pollute the real boot log and corrupt the real staged closure.
    Proven by re-pointing the env mid-test and watching the write follow it."""
    a = tmp_path / "gsd-a"
    b = tmp_path / "gsd-b"
    log = keepalive_boot._LOG_NAME

    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(a))
    assert keepalive_boot._state_dir() == a.resolve(), "state dir must honor the env NOW"
    keepalive_boot._loud("into A")
    assert "into A" in (a / log).read_text(encoding="utf-8")

    # Re-point AFTER the first write: a frozen constant would keep writing to A.
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(b))
    assert keepalive_boot._state_dir() == b.resolve()
    keepalive_boot._loud("into B")
    assert "into B" in (b / log).read_text(encoding="utf-8")
    assert "into B" not in (a / log).read_text(encoding="utf-8"), "A must not receive B's line"


def _wire_persistent_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, list[Path]]:
    """Build a real cache + staged tree with a corrupt staged file, repoint resolution at
    them, and replace launchd_keepalive.restage with a NO-OP SPY (records its calls but
    does NOT fix the stage — so the mismatch persists and the cooldown logic is what we
    observe). Returns (cache, staged, restage_calls)."""
    cache = _make_cache(tmp_path)
    staged = _make_stage_from(cache, tmp_path)
    monkeypatch.setattr(launchd_keepalive, "latest_cache_scripts_dir", lambda: cache)
    monkeypatch.setattr(launchd_keepalive, "data_scripts_dir", lambda: staged)
    (staged / "daemon.py").write_text("torn\n", encoding="utf-8")  # persistent mismatch
    restage_calls: list[Path] = []
    # Spy only — NOT a mock of the code under test; verify_or_restage + the cooldown are real.
    monkeypatch.setattr(launchd_keepalive, "restage", lambda src: restage_calls.append(src))
    return cache, staged, restage_calls


def test_identical_restage_within_cooldown_is_suppressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 2nd verify_or_restage with the SAME unconverged mismatch, inside the cooldown,
    SKIPS the copy — the fsevents-churn half of the runaway (TRDD-ZNN0UK5K). The restage
    spy is called exactly ONCE across two calls."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_KEEPALIVE_RESTAGE_COOLDOWN_S", "300")
    _cache, staged, restage_calls = _wire_persistent_mismatch(tmp_path, monkeypatch)

    r1 = keepalive_boot.verify_or_restage(str(staged))
    r2 = keepalive_boot.verify_or_restage(str(staged))

    assert r1 is False and r2 is False, "an unconverged mismatch returns False both times"
    assert len(restage_calls) == 1, "the 2nd identical restage within cooldown must be skipped"


def test_cooldown_zero_disables_suppression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLAUDE_PLUGIN_OPTION_KEEPALIVE_RESTAGE_COOLDOWN_S=0 turns the suppression OFF — a 2nd
    identical call DOES restage (restage spy called twice)."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_KEEPALIVE_RESTAGE_COOLDOWN_S", "0")
    _cache, staged, restage_calls = _wire_persistent_mismatch(tmp_path, monkeypatch)

    keepalive_boot.verify_or_restage(str(staged))
    keepalive_boot.verify_or_restage(str(staged))

    assert len(restage_calls) == 2, "cooldown=0 must restage on every call (no suppression)"


def test_different_mismatch_signature_restages_within_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Suppression is keyed on the mismatch SIGNATURE (sorted rel-paths): a DIFFERENT set
    of corrupt files restages even inside the cooldown, so a genuinely new torn stage is
    never starved of a repair (TRDD-ZNN0UK5K)."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_KEEPALIVE_RESTAGE_COOLDOWN_S", "300")
    cache, staged, restage_calls = _wire_persistent_mismatch(tmp_path, monkeypatch)

    keepalive_boot.verify_or_restage(str(staged))  # signature: {daemon.py}
    assert len(restage_calls) == 1

    # New torn set: restore daemon.py, corrupt a different closure file → new signature.
    (staged / "daemon.py").write_bytes((cache / "daemon.py").read_bytes())
    (staged / "lib" / "global_state.py").write_text("torn2\n", encoding="utf-8")
    keepalive_boot.verify_or_restage(str(staged))  # signature: {lib/global_state.py}

    assert len(restage_calls) == 2, "a different mismatch signature must not be suppressed"


def test_boot_log_rotates_past_max_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The boot log is size-rotated (<name> → <name>.1) once it exceeds _LOG_MAX_BYTES, so a
    persistent boot fault can never grow it without bound (TRDD-ZNN0UK5K, FIX B2)."""
    state = keepalive_boot._state_dir()  # isolated tmp dir (autouse fixture)
    state.mkdir(parents=True, exist_ok=True)
    log = state / keepalive_boot._LOG_NAME
    log.write_text("x" * (keepalive_boot._LOG_MAX_BYTES + 1), encoding="utf-8")  # over cap

    keepalive_boot._loud("post-rotation line")

    rotated = state / (keepalive_boot._LOG_NAME + ".1")
    assert rotated.is_file(), "the oversized log must rotate to <name>.1"
    assert rotated.stat().st_size > keepalive_boot._LOG_MAX_BYTES, "the .1 holds the old bulk"
    fresh = log.read_text(encoding="utf-8")
    assert "post-rotation line" in fresh, "the new line lands in the fresh log"
    assert len(fresh) < keepalive_boot._LOG_MAX_BYTES, "the new log starts fresh after rotation"
