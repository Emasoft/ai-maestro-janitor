"""Tests for the fleet GitHub-config audit lib (scripts/lib/github_config_audit.py) — TRDD-157OH2D7.

The classifier and the surface/summary/fix helpers are PURE (no gh, no I/O), so they are
unit-testable directly against RepoFacts / payload fixtures. Each finding class has a
positive case AND a falsification (remove the triggering fact → the finding disappears),
per the project rule that a test which still passes after the fix is deleted proves nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import github_config_audit as gca  # noqa: E402
from github_config_audit import RepoFacts, classify_repo  # noqa: E402


def _codes(facts: RepoFacts) -> set[str]:
    return {f.code for f in classify_repo(facts)}


# ---- ruleset fixtures ------------------------------------------------------

def _branch_rs(*rule_types: str) -> dict:
    return {
        "target": "branch",
        "enforcement": "active",
        "rules": [{"type": t} for t in rule_types],
    }


def _tag_rs() -> dict:
    return {"target": "tag", "enforcement": "active", "rules": [{"type": "deletion"}]}


_BASELINE_BRANCH = [
    _branch_rs("deletion", "non_fast_forward"),
    _branch_rs("pull_request", "required_status_checks"),
]


# ---- classify_repo: the finding truth-table --------------------------------

def test_fully_compliant_repo_has_no_findings() -> None:
    """Baseline pair + tag protection + CI present → zero findings (discriminates)."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[*_BASELINE_BRANCH, _tag_rs()], classic_protected=None, has_workflows=True,
    )
    assert _codes(facts) == set()


def test_unprotected_fires_only_when_definitive() -> None:
    """No branch ruleset AND a definite 404 → UNPROTECTED."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[], classic_protected=False, has_workflows=True,
    )
    assert "UNPROTECTED" in _codes(facts)


def test_unprotected_falsified_by_indeterminate_classic() -> None:
    """FALSIFY: classic protection indeterminate (None) → cannot claim UNPROTECTED."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[], classic_protected=None, has_workflows=True,
    )
    assert "UNPROTECTED" not in _codes(facts)


def test_classic_only_protection_claims_no_ruleset_derived_gap() -> None:
    """REGRESSION (code-review): a repo protected ONLY by CLASSIC branch protection (no
    rulesets at all) must NOT be flagged NO_PR_REVIEW / NO_REQUIRED_CHECKS.

    Those two are inferred from the RULE TYPES of the active branch RULESETS. A
    classic-protected repo keeps its `required_pull_request_reviews` /
    `required_status_checks` in the classic-protection body, which this audit does not
    read — so an empty rule-type set proves NOTHING about it. The old gate
    (`has_branch_protection`, which classic satisfies) claimed both gaps anyway, breaking
    the module's never-nag-on-unverifiable rule and making /janitor-github-config-fix
    mutate a compliant repo. NO_TAG_PROTECT is still fair game (tag rulesets WERE read).
    """
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[], classic_protected=True, has_workflows=True,
    )
    codes = _codes(facts)
    assert "NO_PR_REVIEW" not in codes, "cannot claim a gap in rules we never read"
    assert "NO_REQUIRED_CHECKS" not in codes, "cannot claim a gap in rules we never read"
    assert "UNPROTECTED" not in codes, "classic protection IS protection"


def test_ruleset_protected_repo_still_reports_review_and_check_gaps() -> None:
    """The fix must not go too far: a repo protected BY RULESETS whose rules genuinely lack
    pull_request / required_status_checks must STILL report both gaps (we can read those)."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[_branch_rs("deletion", "non_fast_forward"), _tag_rs()],
        classic_protected=None, has_workflows=True,
    )
    codes = _codes(facts)
    assert "NO_PR_REVIEW" in codes
    assert "NO_REQUIRED_CHECKS" in codes


def test_linear_history_fires() -> None:
    """A ruleset carrying required_linear_history → LINEAR_HISTORY, even with full protection."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[_branch_rs("deletion", "non_fast_forward", "required_linear_history"),
                  _branch_rs("pull_request", "required_status_checks"), _tag_rs()],
        classic_protected=None, has_workflows=True,
    )
    assert "LINEAR_HISTORY" in _codes(facts)


def test_linear_history_falsified_without_the_rule() -> None:
    """FALSIFY: drop the required_linear_history rule → LINEAR_HISTORY disappears."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[*_BASELINE_BRANCH, _tag_rs()], classic_protected=None, has_workflows=True,
    )
    assert "LINEAR_HISTORY" not in _codes(facts)


def test_no_pr_review_when_protected_but_no_pr_rule() -> None:
    """Protected (force-push blocked) but no pull_request rule → NO_PR_REVIEW."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[_branch_rs("deletion", "non_fast_forward"), _tag_rs()],
        classic_protected=None, has_workflows=True,
    )
    assert "NO_PR_REVIEW" in _codes(facts)


def test_no_required_checks_only_when_ci_exists() -> None:
    """Protected + PR but no checks rule AND workflows present → NO_REQUIRED_CHECKS."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[_branch_rs("deletion", "non_fast_forward", "pull_request"), _tag_rs()],
        classic_protected=None, has_workflows=True,
    )
    assert "NO_REQUIRED_CHECKS" in _codes(facts)


def test_no_required_checks_suppressed_when_no_ci() -> None:
    """FALSIFY: with no workflows the gap is NO_CI, not NO_REQUIRED_CHECKS."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[_branch_rs("deletion", "non_fast_forward", "pull_request"), _tag_rs()],
        classic_protected=None, has_workflows=False,
    )
    codes = _codes(facts)
    assert "NO_CI" in codes and "NO_REQUIRED_CHECKS" not in codes


def test_no_tag_protect_when_branch_protected_but_no_tag_ruleset() -> None:
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=list(_BASELINE_BRANCH), classic_protected=None, has_workflows=True,
    )
    assert "NO_TAG_PROTECT" in _codes(facts)


def test_no_ci_fires_independent_of_protection() -> None:
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[*_BASELINE_BRANCH, _tag_rs()], classic_protected=None, has_workflows=False,
    )
    assert "NO_CI" in _codes(facts)


# ---- the silence rules (never-nag-on-unverifiable) -------------------------

def test_non_admin_is_silent() -> None:
    """A viewer who is not an admin cannot fix anything → zero findings."""
    assert classify_repo(RepoFacts(slug="o/r", admin=False)) == []


def test_indeterminate_rulesets_is_silent() -> None:
    """rulesets=None (probe failed) → cannot prove any gap → zero findings."""
    assert classify_repo(RepoFacts(slug="o/r", admin=True, rulesets=None)) == []


def test_unprotected_repo_does_not_double_count_pr_and_checks() -> None:
    """An UNPROTECTED repo emits the headline, not also NO_PR_REVIEW/NO_REQUIRED_CHECKS."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[], classic_protected=False, has_workflows=True,
    )
    codes = _codes(facts)
    assert "UNPROTECTED" in codes
    assert "NO_PR_REVIEW" not in codes and "NO_REQUIRED_CHECKS" not in codes


# ---- summarize + digest (the surface line) ---------------------------------

def _payload(*codes: str) -> dict:
    return {
        "generated_at": 1, "repos_scanned": 13,
        "findings": [{"slug": f"o/r{i}", "code": c, "detail": "d"} for i, c in enumerate(codes)],
    }


def test_summarize_none_when_clean() -> None:
    assert gca.summarize({"repos_scanned": 13, "findings": []}) is None
    assert gca.summarize([1, 2, 3]) is None  # malformed JSON off disk → silent, no crash
    assert gca.summarize(None) is None


def test_summarize_names_counts_and_the_fix_skill() -> None:
    line = gca.summarize(_payload("UNPROTECTED", "LINEAR_HISTORY", "LINEAR_HISTORY"))
    assert line is not None
    assert line.startswith("[github-config]")
    assert "1 UNPROTECTED" in line and "2 required_linear_history" in line
    assert gca.FIX_SKILL in line  # the notification MUST carry the remedy


def test_digest_stable_and_change_sensitive() -> None:
    # Same (slug, code) pairs in a DIFFERENT order → identical digest (order-insensitive).
    pair_a = {"slug": "o/x", "code": "UNPROTECTED", "detail": "d"}
    pair_b = {"slug": "o/y", "code": "LINEAR_HISTORY", "detail": "d"}
    d1 = gca.findings_digest({"repos_scanned": 13, "findings": [pair_a, pair_b]})
    d2 = gca.findings_digest({"repos_scanned": 13, "findings": [pair_b, pair_a]})
    assert d1 == d2
    # A repo getting fixed (one pair removed) → different digest (change-sensitive).
    d3 = gca.findings_digest({"repos_scanned": 13, "findings": [pair_a]})
    assert d1 != d3


# ---- fleet_repo_slugs (catalog parsing) ------------------------------------

def test_fleet_repo_slugs_parses_catalog(tmp_path: Path) -> None:
    catalog = tmp_path / "marketplaces" / "ai-maestro-plugins" / ".claude-plugin"
    catalog.mkdir(parents=True)
    (catalog / "marketplace.json").write_text(
        '{"name":"ai-maestro-plugins","plugins":['
        '{"name":"p1","source":{"source":"url","url":"https://github.com/Emasoft/p1.git"}},'
        '{"name":"p2","source":{"source":"url","url":"https://github.com/Emasoft/p2"}},'
        '{"name":"bad","source":{"source":"local"}}]}',
        encoding="utf-8",
    )
    slugs = gca.fleet_repo_slugs(tmp_path)
    assert slugs == ["Emasoft/p1", "Emasoft/p2"]  # sorted, deduped, malformed skipped


def test_fleet_repo_slugs_empty_on_missing_catalog(tmp_path: Path) -> None:
    assert gca.fleet_repo_slugs(tmp_path) == []


# ---- linear-history removal helpers (the fix core) -------------------------

def test_strip_linear_history_preserves_the_rest() -> None:
    rs = {
        "name": "user-ruleset", "target": "branch", "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
        "bypass_actors": [{"actor_id": 5}],
        "rules": [{"type": "deletion"}, {"type": "required_linear_history"}, {"type": "pull_request"}],
    }
    out = gca.strip_linear_history_payload(rs)
    kept = {r["type"] for r in out["rules"]}
    assert kept == {"deletion", "pull_request"}  # linear-history dropped, the rest kept
    assert out["conditions"] == rs["conditions"]  # conditions preserved
    assert out["bypass_actors"] == rs["bypass_actors"]  # bypass actors preserved


def test_nonbaseline_rulesets_with_linear_history_excludes_baseline_names() -> None:
    """A baseline-named ruleset carrying linear-history is NOT returned (the baseline re-apply
    fixes it); only a user-named one needs the separate PUT."""
    baseline = {"name": "baseline-history-protect", "target": "branch", "enforcement": "active",
                "rules": [{"type": "required_linear_history"}]}
    user = {"name": "my-rules", "target": "branch", "enforcement": "active",
            "rules": [{"type": "required_linear_history"}]}
    got = gca.nonbaseline_rulesets_with_linear_history([baseline, user])
    assert [r["name"] for r in got] == ["my-rules"]
