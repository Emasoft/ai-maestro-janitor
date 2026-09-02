"""gitignore-coverage — TRDD-6WM4BFKF.

The classifier is pure: `is_ignored` is injected, so every case here is exercised without a
repo and without git's own behaviour being mocked away at the point that matters.
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DETECTOR = _REPO / "scripts" / "detectors" / "gitignore-coverage.py"
sys.path.insert(0, str(_REPO / "scripts" / "lib"))

import gitignore_coverage as gc  # noqa: E402


def test_a_fully_covered_repo_reports_nothing() -> None:
    """Everything ignored ⇒ no finding. The quiet case must be reachable, or the detector
    would cry wolf on a correct repo and get muted."""
    assert gc.uncovered_classes(lambda _: True) == []


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
    assert gc.tracked_offenders(tracked, lambda _: True) == [".env"]


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
    assert gc.uncovered_classes(lambda _: True) == []          # coverage: perfect
    assert gc.tracked_offenders([".env"], lambda _: True) == [".env"]  # yet still tracked


def test_a_tracked_file_in_an_uncovered_class_is_an_offender_even_with_no_rule() -> None:
    """Criterion 2 as WRITTEN: a `.env` already tracked, no rule anywhere — still contamination.

    `is_ignored` answers False for everything (the repo has no ignore file at all), so only the
    class table's own canonical pattern can classify the tracked paths. Before this the offender
    predicate required the rule to exist, so a tracked secret in an UNCOVERED class never reached
    the contamination line, and the coverage line said "the NEXT such file is published" about a
    file that was already shipping. Protected PROJECT paths stay excluded even when they match.
    """
    private = [
        ".env", "conf/.env.local", "keys/id_rsa.pub", "certs/server.pem", "signing.key",
        ".claude/settings.local.json", "reports/x.md", "scripts_dev/x.py", ".venv/pyvenv.cfg",
        "node_modules/x.js", "assets/.DS_Store", "logs/debug.log", ".trashcan/x",
    ]
    plain = ["src/app.py", "README.md", "environment.md"]
    protected = ["design/tasks/notes.log", ".claude/project/memory/debug.log"]
    offenders = gc.tracked_offenders(private + plain + protected, lambda _: False)
    assert offenders == sorted(private)


def test_class_matcher_shapes_follow_the_canonical_pattern_not_a_loose_substring() -> None:
    """The four pattern shapes in the table, each next to its nearest non-match.

    The `/dir/` shape is the 2026-09-02 fleet-sweep fix: unanchored `reports/` matched a skill's
    tracked `templates/reports/*.md` in another repo and would have prescribed `git rm --cached`
    for it hourly. The rules place `reports/`, `*_dev/` and `.trashcan/` at the ROOT only.
    """
    m = gc.matches_private_class
    assert m("a/b/.env.local") and not m("a/b/env.local")      # bare glob: basename, any depth
    assert m("x/node_modules/y.js") and not m("x/node_modules")  # `dir/`: a dir component, any depth
    assert m("reports/r.md") and not m("reports")               # `/dir/`: the ROOT directory only …
    assert not m("skills/x/templates/reports/r.md")             # … never a nested one
    assert m("scripts_dev/x.py") and not m("pkg/scripts_dev/x.py")
    assert m(".claude/settings.local.json")                     # inner slash: anchored at the root
    assert not m("pkg/.claude/settings.local.json")
    assert not m("keychain.py") and not m("envelope.txt")     # no substring matching


def test_a_path_git_re_includes_with_a_negation_is_never_an_offender() -> None:
    """A `!` line is the user's explicit decision to track — the class matcher must yield to it.

    `.trashcan/.gitkeep` is inside the `.trashcan/` class by name, and `/.trashcan/*` +
    `!/.trashcan/.gitkeep` is how the safe-delete markers are MEANT to be tracked. Without this
    the matcher reported both markers on this very repo as contamination to `git rm --cached`.
    """
    negated = {".trashcan/.gitkeep", ".trashcan/README.txt"}
    tracked = [".trashcan/.gitkeep", ".trashcan/README.txt", ".trashcan/2026/junk.md", ".env"]
    got = gc.tracked_offenders(tracked, lambda _: False, is_negated=lambda p: p in negated)
    assert got == [".env", ".trashcan/2026/junk.md"]


def _seed(repo: Path) -> Callable[..., None]:
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "t@t.t")
    git("config", "user.name", "t")
    return git


def _run_detector(repo: Path) -> list[str]:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    proc = subprocess.run(
        [sys.executable, str(_DETECTOR)], capture_output=True, text=True, env=env, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return [ln for ln in proc.stdout.splitlines() if ln.startswith("⟦gitignore-coverage⟧")]


def test_on_a_seeded_repo_a_negated_marker_is_not_contamination_but_a_tracked_dotenv_is(
    tmp_path: Path,
) -> None:
    """The real-git twin of the negation test: `-v -n` is what lets the detector see the `!`."""
    repo = tmp_path / "seed"
    git = _seed(repo)
    (repo / ".gitignore").write_text("/.trashcan/*\n!/.trashcan/.gitkeep\n")
    (repo / ".trashcan").mkdir()
    (repo / ".trashcan" / ".gitkeep").write_text("")
    (repo / ".env").write_text("x=1\n")
    git("add", ".gitignore", ".trashcan/.gitkeep", ".env")
    git("commit", "-qm", "seed")
    contamination = [ln for ln in _run_detector(repo) if "still TRACKED" in ln]
    assert len(contamination) == 1
    assert ".env" in contamination[0] and ".gitkeep" not in contamination[0]


def test_criterion_2_on_a_seeded_repo_a_tracked_dotenv_with_no_rule_prints_contamination(
    tmp_path: Path,
) -> None:
    """TRDD-6WM4BFKF criterion 2, verbatim, on a REAL repo: tracked `.env`, no `.gitignore`.

    Asserts on the contamination marker and the remedy text, never on silence: the detector
    fails OPEN to silence (no repo, no git, unreadable index), so an empty run proves nothing —
    the review-fork finding that reopened the card's close on 2026-09-02.
    """
    repo = tmp_path / "seed"
    git = _seed(repo)
    (repo / ".env").write_text("x=1\n")
    git("add", ".env")
    git("commit", "-qm", "seed")

    lines = _run_detector(repo)
    coverage = [ln for ln in lines if "NOT covered" in ln]
    contamination = [ln for ln in lines if "still TRACKED: .env" in ln]
    assert coverage and "dotenv (add `.env`)" in coverage[0]
    assert contamination and "git rm --cached" in contamination[0]
    assert (repo / ".gitignore").exists() is False              # the detector only reads
