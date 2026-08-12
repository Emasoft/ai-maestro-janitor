"""A stale proposal left in a non-LOCAL scope root must not read as a live report (janitor#195).

An older librarian wrote one `memory-reorg-proposed.md` into EVERY memory scope root; the
current one writes a SINGLE file into LOCAL. The other copies were never removed and nothing
refreshes them, so they sit there presenting resolved findings as current.

That is how janitor#195 came to report 22 one-sided-link findings as a link-parsing bug: the
numbers were real, but they were read out of a 22.7-day-old orphan in the USER root. A fresh
run of the very same code produced ZERO — every one had been reciprocated since. A stale
generated artifact is worse than a missing one, because a reader cannot distinguish it from a
live report, and it teaches them to discount the file that also carries the real findings.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "memory_librarian", _ROOT / "scripts" / "detectors" / "memory-librarian.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["memory_librarian"] = mod  # dataclasses resolves via sys.modules
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def lib(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mod = _load()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    (tmp_path / "proj" / ".janitor" / "state").mkdir(parents=True)
    return mod


def test_an_orphan_in_a_non_local_root_is_replaced_with_a_redirect(
    lib, tmp_path: Path
) -> None:
    local, user = tmp_path / "local", tmp_path / "user"
    local.mkdir()
    user.mkdir()
    stale = user / lib.PROPOSAL_NAME
    stale.write_text("# old\n`a.md` links [[b.md]] but ...\n", encoding="utf-8")

    done = lib._redirect_orphaned_proposals([("LOCAL", local), ("USER", user)], local)

    assert done == [stale]
    body = stale.read_text(encoding="utf-8")
    assert "ORPHAN" in body and "links [[" not in body, "the stale findings must be gone"
    assert lib.PROPOSAL_NAME in body, "and it must name the file to read instead"
    assert str(local) not in body, (
        "janitor#243: a USER-scope file is read by EVERY project's session — embedding "
        "ONE project's absolute LOCAL path is correct for only that one reader and "
        "misleading for all the others"
    )


def test_the_LIVE_proposal_is_never_touched(lib, tmp_path: Path) -> None:
    """The redirect must never eat the file it is redirecting to."""
    local = tmp_path / "local"
    local.mkdir()
    live = local / lib.PROPOSAL_NAME
    live.write_text("# live findings\n", encoding="utf-8")

    assert lib._redirect_orphaned_proposals([("LOCAL", local)], local) == []
    assert live.read_text(encoding="utf-8") == "# live findings\n"


def test_redirecting_is_idempotent_so_a_stable_corpus_produces_no_churn(
    lib, tmp_path: Path
) -> None:
    local, user = tmp_path / "local", tmp_path / "user"
    local.mkdir()
    user.mkdir()
    (user / lib.PROPOSAL_NAME).write_text("# old\n", encoding="utf-8")
    scopes = [("LOCAL", local), ("USER", user)]

    assert len(lib._redirect_orphaned_proposals(scopes, local)) == 1
    assert lib._redirect_orphaned_proposals(scopes, local) == [], "second run must be a no-op"


def test_absent_orphans_are_a_silent_no_op(lib, tmp_path: Path) -> None:
    local, user = tmp_path / "local", tmp_path / "user"
    local.mkdir()
    user.mkdir()
    assert lib._redirect_orphaned_proposals([("LOCAL", local), ("USER", user)], local) == []
    assert not (user / lib.PROPOSAL_NAME).exists(), "must not CREATE one where none existed"


def test_content_is_replaced_never_deleted(lib, tmp_path: Path) -> None:
    """The proposal is generated, not a note — but it lives inside a memory STORE, and nothing
    in a memory store is removed by a routine sweep."""
    local, user = tmp_path / "local", tmp_path / "user"
    local.mkdir()
    user.mkdir()
    stale = user / lib.PROPOSAL_NAME
    stale.write_text("# old\n", encoding="utf-8")

    lib._redirect_orphaned_proposals([("LOCAL", local), ("USER", user)], local)
    assert stale.is_file(), "the file must survive; only its misleading content is replaced"
