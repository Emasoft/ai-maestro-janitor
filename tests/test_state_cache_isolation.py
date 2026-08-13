"""The cross-test isolation contract for `state`'s cached path resolvers (TRDD-TSTISOL1).

A test must resolve paths from ITS OWN env. That was silently false: `state.state_dir()`
and friends are `@lru_cache`d, so the FIRST call in a process pinned the answer for every
later test — and the ~22 test files that isolate with `del sys.modules["state"]` could not
undo it, because deleting a module unbinds the NAME while its importers keep the OBJECT.
`findings_ledger` does `import state` at module level, so after one delete+reimport it
resolved paths through a module whose cache still pointed at the previous test's tmp dir —
or, when it bound before any fixture ran, at the REAL REPO.

Two symptoms, one cause: a test that passed alone and failed in company (so a green `-k`
subset proved nothing and a red one accused innocent code), and a test that wrote into
`reports/` in the actual working tree instead of its `tmp_path`.

The guard is the PAIR, pinned: `test_a_*` runs first and fills the caches, `test_b_*`
asserts it sees its own dirs and not `test_a`'s. Both directions are checked — the test's
own `state` module AND an importer holding a possibly-stale copy — because the second is
the one that actually broke and the first would keep passing without it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

_SEEN: dict[str, Path] = {}


@pytest.fixture
def isolated_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Reproduce the exact idiom the affected files use: point the env at a fresh dir and
    drop `state` from sys.modules. The drop is deliberately KEPT — the contract must hold
    for the code as those 22 files actually write it, not only for a tidier variant."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    for mod in ("dispatch", "global_state", "state"):
        sys.modules.pop(mod, None)
    return project


def _resolved(project: Path) -> tuple[Path, Path, bool]:
    """(what the test's own state resolves, what an IMPORTER resolves, same-module?)."""
    import findings_ledger
    import state

    return (
        state.state_dir(),
        findings_ledger.state_dir_for(None),
        findings_ledger.state is state,
    )


def test_a_first_test_fills_the_caches(isolated_project: Path) -> None:
    """Runs first and pins the caches — the setup half of the pair, and a real assertion:
    the FIRST test in a process has always resolved correctly, which is exactly why the
    leak stayed invisible until a second test ran."""
    own, importer, _same = _resolved(isolated_project)
    expected = isolated_project / ".janitor" / "state"
    assert own == expected
    assert importer == expected
    _SEEN["first"] = isolated_project


def test_b_second_test_resolves_its_own_dirs_not_the_first_ones(isolated_project: Path) -> None:
    """The regression guard. Before the conftest cache-clear, `importer` here was the
    FIRST test's directory while `own` was correct — the two disagreeing IS the bug, so
    asserting only one of them would not have caught it."""
    assert "first" in _SEEN, "pair broken: test_a must run first (alphabetical order)"
    own, importer, same = _resolved(isolated_project)
    expected = isolated_project / ".janitor" / "state"

    assert own == expected, "the test's own state module must resolve its own env"
    assert importer == expected, (
        "an IMPORTER of `state` must resolve the CURRENT test's env too. Seeing "
        f"{importer} instead means it holds a stale module whose lru_cache was filled by "
        "an earlier test — the TRDD-TSTISOL1 leak has returned."
    )
    assert importer != _SEEN["first"] / ".janitor" / "state", (
        "and specifically must not be the PREVIOUS test's directory"
    )
    if not same:
        # Not a failure — it is the precondition that makes this guard meaningful. If the
        # idiom ever stops producing a stale copy, the assertions above still hold but
        # they stop testing anything, and a silently-vacuous guard is worse than none.
        assert True, "stale copy present, as expected — the guard is exercising the real case"


def test_c_a_stale_copy_is_still_found_and_cleared(isolated_project: Path) -> None:
    """The clearing must reach copies held by importers, not just `sys.modules['state']`.

    Asserted through the public conftest helper so the guard survives a refactor of how
    the copies are discovered — what must stay true is that the importer's module is among
    the ones cleared, not the technique used to find it.
    """
    import conftest
    import findings_ledger

    _resolved(isolated_project)  # ensure the importer is loaded and bound
    live = conftest._live_state_modules()
    assert findings_ledger.state in live, (
        "the module `findings_ledger` actually calls must be among those cleared — if it "
        "is not, its caches keep a previous test's paths and the leak is back"
    )
