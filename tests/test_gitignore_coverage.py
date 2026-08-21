"""gitignore-coverage — TRDD-6WM4BFKF.

The classifier is pure: `is_ignored` is injected, so every case here is exercised without a
repo and without git's own behaviour being mocked away at the point that matters.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "lib"))

import gitignore_coverage as gc  # noqa: E402


def test_a_fully_covered_repo_reports_nothing() -> None:
    """Everything ignored ⇒ no finding. The quiet case must be reachable, or the detector
    would cry wolf on a correct repo and get muted."""
    assert gc.uncovered_classes(lambda _p: True) == []


def test_an_uncovered_class_is_reported_with_its_canonical_pattern() -> None:
    """The finding must carry the FIX, not just the complaint."""
    only_env_missing = lambda p: p != ".env"  # noqa: E731
    found = gc.uncovered_classes(only_env_missing)
    assert [c.name for c in found] == ["dotenv"]
    assert found[0].pattern == ".env"


def test_every_class_carries_a_pattern_and_a_why() -> None:
    """A finding a reader cannot act on is noise; a table entry without both is unfinished."""
    for c in gc.PRIVATE_CLASSES:
        assert c.probe and c.pattern and c.why, c.name


def test_PROJECT_scope_is_never_reported_as_an_offender() -> None:
    """THE dangerous false positive, and the reason `is_protected` exists.

    `design/**` and `.claude/project/memory/**` are tracked ON PURPOSE — they are the shared
    kanban and the shared wiki, protected by negation lines. If this detector proposed
    untracking them, acting on the advice would delete the board and the memory corpus for
    every contributor. That is a far larger harm than the leak this module prevents, so the
    protection is asserted rather than assumed.
    """
    tracked = [
        "design/tasks/TRDD-x.md",
        ".claude/project/memory/page.md",
        ".env",
    ]
    assert gc.tracked_offenders(tracked, lambda _p: True) == [".env"]


def test_protected_prefixes_are_recognised_with_or_without_a_leading_dot_slash() -> None:
    """`git ls-files` and a hand-written path disagree on `./`; the guard must not care."""
    assert gc.is_protected("design/tasks/x.md")
    assert gc.is_protected("./design/tasks/x.md")
    assert gc.is_protected(".claude/project/memory/p.md")
    assert not gc.is_protected("designs/x.md")  # near-miss must NOT be protected


def test_a_rule_that_exists_does_not_clear_an_already_tracked_file() -> None:
    """The two faults are independent — that is the whole design.

    A `.gitignore` rule does NOT untrack an existing index entry (git keeps them by design), so
    a repo can be fully COVERED and still be shipping the secret. Reporting only coverage would
    miss exactly the case that has already leaked.
    """
    assert gc.uncovered_classes(lambda _p: True) == []          # coverage: perfect
    assert gc.tracked_offenders([".env"], lambda _p: True) == [".env"]  # yet still tracked
