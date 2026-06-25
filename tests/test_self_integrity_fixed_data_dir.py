"""Regression guard for TRDD-DKEYCHN7 — the self-integrity detector's HMAC key
AND its audit chain MUST resolve under the FIXED janitor DATA dir, NEVER under
``$CLAUDE_PLUGIN_DATA``.

THE BUG (fixed here): the detector resolved both trust artifacts via
``$CLAUDE_PLUGIN_DATA`` — the dir of whichever plugin owns the RUNNING turn (the
``${CLAUDE_PLUGIN_DATA}`` foot-gun the project CLAUDE.md warns about). The key +
chain scattered into other plugins' data dirs and did not match across sessions,
so the finding-HMAC / chain tamper-evidence was unverifiable. The fix repoints
both at ``version_update_lib._data_dir()`` — the SAME FIXED dir the C3 pin path
uses.

This test is the missing alarm for a future ``$CLAUDE_PLUGIN_DATA`` regression:
it sets ``CLAUDE_PLUGIN_DATA`` to a BOGUS temp dir and proves the detector's
resolved key path + chain path IGNORE it and live under the FIXED dir instead.
It mirrors the C3 constant-parity guard ``tests/test_stub_lib_constant_parity.py``
(load the hyphenated detector module by path, assert resolved paths).

The detector filename ``janitor-self-integrity.py`` has a hyphen → not a normal
importable module name, so it is loaded by ``importlib`` from its path. Loading
runs the module-level constant/import setup but NOT ``main()`` (that is
``__name__``-guarded), so importing it never fires a real heartbeat.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _PROJECT_ROOT / "scripts"
_DETECTOR_PATH = _SCRIPTS / "detectors" / "janitor-self-integrity.py"

# The detector imports state / version_update_lib / janitor_self_integrity by
# bare name (it inserts scripts/lib at runtime); make that importable here too so
# loading the module by path resolves those imports. Mirrors the sibling
# test_stub_lib_constant_parity / test_version_pin path setup.
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

_BOGUS_PLUGIN_DATA = "/tmp/dkeychn7-bogus-other-plugin-data-DO-NOT-USE"
_KEY_FILENAME = ".integrity-key"
_CHAIN_FILENAME = "janitor-chain.ndjson"


def _load_detector_module():
    """Import janitor-self-integrity.py BY PATH (hyphenated filename → not a
    normal module name). Module-level code runs (the constants + the
    version_update_lib import) but NOT ``main()`` — that is
    ``if __name__ == "__main__"`` guarded, and the loaded module's ``__name__``
    is our chosen import name, never ``"__main__"``."""
    spec = importlib.util.spec_from_file_location(
        "janitor_self_integrity_detector", _DETECTOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def detector(monkeypatch, tmp_path: Path):
    """Load the detector with a BOGUS $CLAUDE_PLUGIN_DATA and a known FIXED dir.

    ``JANITOR_DATA_DIR`` is the FIXED-dir test override honored by
    ``version_update_lib._data_dir()`` (the single canonical resolver the
    detector reuses). Setting it lets us assert against a controlled path
    without touching the real ``~/.claude`` tree. ``CLAUDE_PLUGIN_DATA`` is set
    to a bogus dir that the resolved paths MUST ignore.
    """
    fixed = tmp_path / "fixed-janitor-data"
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", _BOGUS_PLUGIN_DATA)
    monkeypatch.setenv("JANITOR_DATA_DIR", str(fixed))
    # Reload freshly so no module-level state from another test leaks the wrong
    # env snapshot (the resolvers read os.environ live, so a cached module is
    # fine — but a clean import keeps this independent).
    for mod in ("version_update_lib", "janitor_self_integrity", "janitor_integrity"):
        sys.modules.pop(mod, None)
    module = _load_detector_module()
    return module, fixed


def test_key_path_under_fixed_dir_not_plugin_data(detector) -> None:
    """The HMAC key resolves to ``<FIXED dir>/.integrity-key`` and does NOT live
    under the bogus ``$CLAUDE_PLUGIN_DATA``. The key path == the dir the detector
    passes to ``load_or_create_key`` (its ``_fixed_data_dir()``) joined with the
    key filename."""
    module, fixed = detector
    base = module._fixed_data_dir()
    assert base is not None
    key_path = base / _KEY_FILENAME
    assert key_path == fixed / _KEY_FILENAME
    # The whole resolved path must be under the FIXED dir, never the bogus one.
    assert str(key_path).startswith(str(fixed))
    assert _BOGUS_PLUGIN_DATA not in str(key_path)


def test_chain_path_under_fixed_dir_not_plugin_data(detector) -> None:
    """The audit chain resolves to ``<FIXED dir>/janitor-chain.ndjson`` and does
    NOT live under the bogus ``$CLAUDE_PLUGIN_DATA``."""
    module, fixed = detector
    chain_path = module._resolve_audit_chain_path()
    assert chain_path is not None
    assert chain_path == fixed / _CHAIN_FILENAME
    assert str(chain_path).startswith(str(fixed))
    assert _BOGUS_PLUGIN_DATA not in str(chain_path)


def test_key_and_chain_share_the_same_fixed_dir(detector) -> None:
    """Key and chain MUST live in the SAME dir — the chain's HMAC is keyed by the
    key, so a split location is exactly the cross-session mismatch this fix
    removes."""
    module, _fixed = detector
    base = module._fixed_data_dir()
    key_dir = (base / _KEY_FILENAME).parent
    chain_dir = module._resolve_audit_chain_path().parent
    assert key_dir == chain_dir


def test_detector_fixed_dir_equals_version_update_lib_resolver(detector) -> None:
    """The detector's FIXED dir is EXACTLY ``version_update_lib._data_dir()`` — it
    REUSES the single canonical resolver (not a re-derivation), so it can never
    drift from the C3 pin path. This is the parity that, if broken, sends the
    detector's key/chain to a different dir than the rest of the integrity
    subsystem."""
    module, _fixed = detector
    import version_update_lib  # noqa: PLC0415

    assert module._fixed_data_dir() == version_update_lib._data_dir()


def test_ignores_plugin_data_even_without_override(monkeypatch) -> None:
    """With NO ``JANITOR_DATA_DIR`` override, the detector falls back to the
    hard-coded ``_FIXED_DATA_DIR`` — and still IGNORES a bogus
    ``$CLAUDE_PLUGIN_DATA``. This proves the foot-gun env var can never steer the
    key/chain location, override or not."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", _BOGUS_PLUGIN_DATA)
    monkeypatch.delenv("JANITOR_DATA_DIR", raising=False)
    for mod in ("version_update_lib", "janitor_self_integrity", "janitor_integrity"):
        sys.modules.pop(mod, None)
    module = _load_detector_module()
    import version_update_lib  # noqa: PLC0415

    base = module._fixed_data_dir()
    assert base == version_update_lib._FIXED_DATA_DIR
    assert _BOGUS_PLUGIN_DATA not in str(base)
    assert _BOGUS_PLUGIN_DATA not in str(module._resolve_audit_chain_path())
    assert _BOGUS_PLUGIN_DATA not in str(base / _KEY_FILENAME)
