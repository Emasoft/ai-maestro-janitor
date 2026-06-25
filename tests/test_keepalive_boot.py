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
    # Also keep the log file off the host: point the boot-log dir at tmp.
    monkeypatch.setattr(keepalive_boot, "_LOG_DIR", tmp_path / "logdir")

    result = keepalive_boot.verify_or_restage(str(staged))
    assert result is False, "an unrepairable broken stage must return False (fail-loud, not crash)"
    err = capsys.readouterr().err
    assert "keepalive-boot:" in err, "fail-loud must emit a keepalive-boot line to stderr"
    assert "restage FAILED" in err or "no runnable copy" in err


def test_gate_never_raises_on_bad_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """FAIL-OPEN backstop: even a totally bogus argument must not raise out of the gate — it
    swallows everything and returns True so the launch is never aborted by this gate."""
    # Force latest_cache_scripts_dir to blow up; the outer try must still yield True.
    def _explode() -> Path:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(launchd_keepalive, "latest_cache_scripts_dir", _explode)
    assert keepalive_boot.verify_or_restage(object()) is True


def test_loud_helper_writes_stderr_and_logfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """_loud emits to BOTH stderr and the keepalive boot-log file (the operator-visible
    surfaces), and tolerates an unwritable log dir without raising."""
    logdir = tmp_path / "logdir"
    monkeypatch.setattr(keepalive_boot, "_LOG_DIR", logdir)
    keepalive_boot._loud("hello operator")
    assert "keepalive-boot: hello operator" in capsys.readouterr().err
    logged = (logdir / keepalive_boot._LOG_NAME).read_text(encoding="utf-8")
    assert "hello operator" in logged
