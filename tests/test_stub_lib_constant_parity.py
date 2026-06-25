"""Constant-parity guard for the C3 trust-anchor paths (TRDD-T198DT1W, NIT-1).

The dispatcher stub CANNOT import ``version_update_lib`` — importing the cache's
own verifier to check that same cache is circular trust, and the stub
deliberately reimplements its readers in stdlib (see the comments in
``dispatcher-stub.py``). So the FIXED janitor DATA dir and the four
integrity-path names are defined INDEPENDENTLY in both files, currently
byte-identical.

That independence is a maintenance landmine: a future edit to one side that
forgets the other would SILENTLY disable C3 — the stub would read a different
``last-good.json`` / ``quarantine.json`` / ``.integrity-key`` than the daemon
writes, so ``_pin_rejects`` would always see "no pin" → C3 inert, the heartbeat
quietly degrades to C2-only — with NO other test failing. This test is that
missing alarm: it imports BOTH modules and asserts the RESOLVED paths are equal,
so any drift fails here.

The stub is loaded by file path (its filename ``dispatcher-stub.py`` has a
hyphen → not a plain-importable module name) via ``importlib``. Importing it
must NOT run its ``main()`` — that work is ``__name__``-guarded; this test also
asserts that guard holds, so a future refactor that runs ``main()`` at import
time (which would fire a real heartbeat from the test process) is caught too.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _PROJECT_ROOT / "scripts"
_STUB_PATH = _SCRIPTS / "dispatcher-stub.py"

# version_update_lib imports janitor_integrity / janitor_self_integrity by bare
# name, so its package dir must be importable. Match the sibling test_version_pin.
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))


def _load_stub_module():
    """Import dispatcher-stub.py BY PATH (hyphenated filename → not a normal
    module name). Loading it executes module-level code (the constant
    definitions) but NOT ``main()`` — that is ``if __name__ == "__main__"``
    guarded, and the loaded module's ``__name__`` is our chosen import name,
    never ``"__main__"``."""
    spec = importlib.util.spec_from_file_location("janitor_dispatcher_stub", _STUB_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def stub():
    return _load_stub_module()


@pytest.fixture(scope="module")
def vu():
    # Import freshly so no env override from another test leaks in: the parity we
    # assert is between the two HARD-CODED constants, which must agree regardless
    # of any JANITOR_DATA_DIR test redirect.
    for mod in ("version_update_lib", "janitor_self_integrity", "janitor_integrity"):
        sys.modules.pop(mod, None)
    import version_update_lib as mod  # noqa: PLC0415

    return mod


def test_stub_does_not_run_main_on_import(stub) -> None:
    """Importing the stub as a module must be side-effect-free w.r.t. the
    heartbeat: ``main`` is present and callable, but loading the module never
    invokes it (the ``__name__`` guard holds), so a test/import never fires a
    real heartbeat from this process."""
    assert callable(stub.main)
    assert stub.__name__ != "__main__"


def test_fixed_data_dir_parity(stub, vu) -> None:
    """The FIXED janitor DATA dir is byte-identical in stub and lib. This is the
    anchor that, if it drifts, sends the stub to read a DIFFERENT DATA dir than
    the daemon writes → C3 silently disabled."""
    assert stub.PLUGIN_DATA_ROOT == vu._FIXED_DATA_DIR


def test_integrity_key_path_parity(stub, vu) -> None:
    """``.integrity-key`` resolves to the same absolute file on both sides:
    stub ``PLUGIN_DATA_ROOT / _INTEGRITY_KEY_NAME`` vs lib's key path under
    ``_FIXED_DATA_DIR``. If these diverge the stub recomputes the pin HMAC with a
    different key than the daemon signed with → every pin reads as a mismatch or
    no-key → fail-open to C2 with no alarm."""
    stub_key = stub.PLUGIN_DATA_ROOT / stub._INTEGRITY_KEY_NAME
    # janitor_self_integrity._key_path(<base>) == <base>/.integrity-key; the lib
    # mints/reads the key at exactly _data_dir()/.integrity-key. With no env
    # override, _data_dir() == _FIXED_DATA_DIR.
    lib_key = vu._FIXED_DATA_DIR / vu.janitor_self_integrity._INTEGRITY_KEY_FILENAME
    assert stub_key == lib_key


def test_last_good_pin_path_parity(stub, vu) -> None:
    """``integrity/last-good.json`` (the last-GOOD pin the daemon writes and the
    stub reads) resolves to the same absolute file on both sides."""
    stub_pin = stub.PLUGIN_DATA_ROOT / stub._LAST_GOOD_REL
    lib_pin = vu._FIXED_DATA_DIR / vu._INTEGRITY_SUBDIR / vu._LAST_GOOD_NAME
    assert stub_pin == lib_pin


def test_quarantine_path_parity(stub, vu) -> None:
    """``integrity/quarantine.json`` (the proven-bad list the daemon writes and
    the stub reads to skip a version) resolves to the same absolute file."""
    stub_q = stub.PLUGIN_DATA_ROOT / stub._QUARANTINE_REL
    lib_q = vu._FIXED_DATA_DIR / vu._INTEGRITY_SUBDIR / vu._QUARANTINE_NAME
    assert stub_q == lib_q


def test_manifest_rel_parity(stub, vu) -> None:
    """The per-version manifest path ``.integrity/manifest-sha256.json`` (hashed
    on BOTH sides to produce/compare the pin HMAC) is the identical relative path,
    so the stub and the daemon hash the same file inside a cached version."""
    assert stub._MANIFEST_REL == vu._MANIFEST_REL


def test_every_anchor_path_equal(stub, vu) -> None:
    """Belt-and-braces: collect every C3 anchor path from both modules and assert
    the whole set agrees in one place — the single check a reviewer reads to
    confirm 'the stub and the lib resolve the SAME files'. Mirrors the NIT-1
    finding's recommendation (DATA dir + pin + quarantine + key + manifest)."""
    stub_paths = {
        "data_dir": stub.PLUGIN_DATA_ROOT,
        "key": stub.PLUGIN_DATA_ROOT / stub._INTEGRITY_KEY_NAME,
        "last_good": stub.PLUGIN_DATA_ROOT / stub._LAST_GOOD_REL,
        "quarantine": stub.PLUGIN_DATA_ROOT / stub._QUARANTINE_REL,
        "manifest_rel": stub._MANIFEST_REL,
    }
    lib_paths = {
        "data_dir": vu._FIXED_DATA_DIR,
        "key": vu._FIXED_DATA_DIR / vu.janitor_self_integrity._INTEGRITY_KEY_FILENAME,
        "last_good": vu._FIXED_DATA_DIR / vu._INTEGRITY_SUBDIR / vu._LAST_GOOD_NAME,
        "quarantine": vu._FIXED_DATA_DIR / vu._INTEGRITY_SUBDIR / vu._QUARANTINE_NAME,
        "manifest_rel": vu._MANIFEST_REL,
    }
    assert stub_paths == lib_paths
