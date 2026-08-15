"""The walk invariant every project scanner must satisfy (janitor#99).

Three separate detectors shipped the same defect — scoring a downloaded corpus under a
gitignored dir as the project's own supply chain — and each was found only after it fired
on a real repo. The rule is now old enough to be assumed and young enough to be forgotten,
so it is pinned here rather than in three docstrings nobody greps.

THE RULE: a detector that judges "this project's own code" asks GIT what the project
ships. A hardcoded directory-name list cannot know a given project's `.gitignore`, and
`supply-chain-fingerprints` proved the sharper form of the failure — its list contained
`"_dev"` while the membership test only ever matched a directory literally NAMED `_dev`,
so it silently covered nothing while reading as covered.

The EXEMPTIONS below are the interesting part. They are not "not done yet" — each is a
detector whose subject genuinely IS the gitignored tree, and applying the filter would
disable it. Recording WHY here keeps a future cleanup pass from "fixing" them into
uselessness.
"""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTORS = _PROJECT_ROOT / "scripts" / "detectors"

# Detectors that judge the project's OWN shipped surface — git must be the authority.
_MUST_FILTER = {
    "repo-trust-score.py",
    "typosquat-watcher.py",
    "binary-magic-scanner.py",
    "supply-chain-fingerprints.py",
}

# Detectors that walk a tree but MUST NOT apply the filter, and why. A gitignored path is
# precisely their subject; filtering would silence them completely.
_EXEMPT = {
    "ai-context-poisoning.py": "scans site-packages / node_modules — installed deps are "
                               "gitignored BY DESIGN and are the whole subject",
    "historical-cache-scan.py": "scans package-manager caches, which are gitignored by "
                                "definition",
    "reports-purge.py": "purges reports/, which the janitor's own rules REQUIRE to be "
                        "gitignored",
    "screenshot-purge.py": "purges gitignored test screenshots",
    "agent-context-integrity.py": "asks 'what does the agent LOAD?', not 'what does the repo "
                                  "SHIP?' — a gitignored CLAUDE.md is still auto-loaded into "
                                  "every session, so it is still poisonable (janitor#167)",
    "runaway-file-growth.py": "asks 'what is EATING THE DISK?', not 'what does the repo SHIP?' "
                              "— it walks configured roots outside the repo entirely (default "
                              "/tmp/claude), and the balloons it hunts are logs, caches and "
                              "temp files, i.e. gitignored by nature. Filtering would silence "
                              "it on precisely the files it exists to name (TRDD-XM3FPJC0)",
}
# NB `trashcan-purge.py` is deliberately absent: it uses `iterdir()` on one directory, not
# a recursive walk, so it never had the exposure. Listing it would imply a risk it does not
# carry — an exemption list is only useful if every entry is load-bearing.


def _detector_text(name: str) -> str:
    path = _DETECTORS / name
    assert path.is_file(), f"detector disappeared: {name} — update this test's lists"
    return path.read_text(encoding="utf-8")


def test_own_surface_scanners_ask_git_not_a_name_list() -> None:
    """Each scanner that judges the project's own code must route its walk through the
    shared `drop_gitignored`. Failing here means a scanner is guessing what the project
    ships from directory names — the janitor#99 defect, three times over."""
    missing = [n for n in sorted(_MUST_FILTER) if "drop_gitignored" not in _detector_text(n)]
    assert not missing, (
        "these scanners judge the project's own supply chain but do not ask git what the "
        f"project ships: {missing}. Use git_utils.drop_gitignored on the walk result."
    )


def test_exempt_scanners_are_still_exempt_on_purpose() -> None:
    """The exemptions must stay deliberate. If one of these starts filtering, someone
    'fixed' a detector into uselessness — its subject IS the gitignored tree."""
    wrong = [n for n in sorted(_EXEMPT) if "drop_gitignored" in _detector_text(n)]
    assert not wrong, (
        f"these detectors must NOT filter gitignored paths: {wrong}. Reasons: "
        + "; ".join(f"{n}: {_EXEMPT[n]}" for n in wrong)
    )


def test_every_walking_detector_is_classified() -> None:
    """A NEW scanner must land in one list or the other. This is the half that survives
    the author of the rule: without it, the next tree-walking detector inherits nothing
    and rediscovers janitor#99 on a user's repo instead of here."""
    # `.glob(` is in the token set deliberately. The first version checked only `rglob(` and
    # `os.walk(`, and `agent-context-integrity` — which walks with `.glob("**/…")` — escaped
    # classification entirely. A test that silently covers fewer things than it claims is the
    # same failure this file exists to prevent, one level up.
    walkers = {
        p.name
        for p in sorted(_DETECTORS.glob("*.py"))
        if any(tok in p.read_text(encoding="utf-8") for tok in ("rglob(", "os.walk(", ".glob("))
    }
    # Only detectors that walk the PROJECT tree are in scope. Ones that walk config dirs,
    # the design/ corpus, or memory scopes judge no supply chain and need no verdict.
    out_of_scope = {
        "cross-scope-reference-drift.py", "subagent-scope-drift.py", "stale-task.py",
        "task-pr-mismatch.py", "report-to-trdd-drift.py", "subagent-report.py",
        "memory-maintenance.py", "memory-scope-leak.py", "janitor-self-integrity.py",
        "memory-librarian.py", "trdd-drift.py", "trdd-reminder.py",
        "trdd-state-reconciliation.py", "memgrep-index-health.py", "wikimem-syntax.py",
        "memorize-nudge.py", "project-map-drift.py", "why-in-commits.py",
        "orphaned-resume-flag.py", "ticket-dispatch.py", "mcp-rugpull.py",
        "workflow-security.py", "provenance-audit.py", "package-manager-policy.py",
        "project-memory-tracked.py",
    }
    unclassified = sorted(walkers - _MUST_FILTER - set(_EXEMPT) - out_of_scope)
    assert not unclassified, (
        f"new tree-walking detector(s) with no verdict on the janitor#99 rule: "
        f"{unclassified}. Decide: does it judge the project's OWN shipped code (add to "
        f"_MUST_FILTER and use drop_gitignored) or is a gitignored tree its actual "
        f"subject (add to _EXEMPT with the reason)?"
    )
