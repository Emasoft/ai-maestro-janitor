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


def _unresolved_branch_rs() -> dict:
    """A branch ruleset whose per-ruleset DETAIL fetch failed (janitor#244) — kept as a
    rules-less summary shell, tagged so the classifier knows not to trust its emptiness."""
    return {"target": "branch", "enforcement": "active", "_detail_unresolved": True}


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


def test_unresolved_ruleset_detail_does_not_claim_review_and_check_gaps() -> None:
    """janitor#244: a transient per-ruleset detail-fetch failure kept as a rules-less
    summary must NOT be read as evidence of absence. The ONE ruleset that actually carries
    pull_request + required_status_checks failed to resolve → the classifier must stay
    silent on NO_PR_REVIEW/NO_REQUIRED_CHECKS rather than false-flag a compliant repo."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[_branch_rs("deletion", "non_fast_forward"), _unresolved_branch_rs(), _tag_rs()],
        classic_protected=None, has_workflows=True,
    )
    codes = _codes(facts)
    assert "NO_PR_REVIEW" not in codes, "cannot claim a gap in a ruleset we failed to read"
    assert "NO_REQUIRED_CHECKS" not in codes, "cannot claim a gap in a ruleset we failed to read"


def test_unresolved_ruleset_detail_falsified_when_resolved() -> None:
    """FALSIFY: with the SAME ruleset actually resolved (carrying the rules), the gaps
    disappear entirely — proving the silence above is about unresolvability, not content."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[_branch_rs("deletion", "non_fast_forward"),
                  _branch_rs("pull_request", "required_status_checks"), _tag_rs()],
        classic_protected=None, has_workflows=True,
    )
    assert _codes(facts) == set()


def test_unresolved_ruleset_still_counts_as_branch_protection() -> None:
    """An unresolved ruleset still carries `target`/`enforcement` (readable from the list
    endpoint), so it must still count toward branch protection existing — UNPROTECTED must
    not fire just because one ruleset's detail could not be resolved."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[_unresolved_branch_rs()], classic_protected=False, has_workflows=True,
    )
    assert "UNPROTECTED" not in _codes(facts)


def test_resolved_ruleset_findings_survive_a_sibling_being_unresolved() -> None:
    """A rule type genuinely FOUND on a RESOLVED ruleset is still trustworthy evidence even
    when a sibling ruleset's detail is unresolved — LINEAR_HISTORY must still fire."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[_branch_rs("deletion", "non_fast_forward", "required_linear_history"),
                  _unresolved_branch_rs(), _tag_rs()],
        classic_protected=None, has_workflows=True,
    )
    assert "LINEAR_HISTORY" in _codes(facts)


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


def test_summarize_for_slug_none_when_this_repo_clean_or_malformed() -> None:
    assert gca.summarize_for_slug({"repos_scanned": 13, "findings": []}, "o/r0") is None
    assert gca.summarize_for_slug([1, 2, 3], "o/r0") is None  # malformed JSON → silent
    assert gca.summarize_for_slug(None, "o/r0") is None
    # OTHER repos drifted, ours is clean → still None: per-project channeling means the
    # rest of the fleet's problems are invisible here (user directive 2026-07-17).
    assert gca.summarize_for_slug(_payload("UNPROTECTED", "LINEAR_HISTORY"), "o/mine") is None


def test_summarize_for_slug_names_only_this_repo_and_the_scoped_fix() -> None:
    payload = {
        "generated_at": 1, "repos_scanned": 13,
        "findings": [
            {"slug": "o/mine", "code": "UNPROTECTED", "detail": "d"},
            {"slug": "o/mine", "code": "LINEAR_HISTORY", "detail": "d"},
            {"slug": "o/other", "code": "NO_CI", "detail": "d"},
        ],
    }
    line = gca.summarize_for_slug(payload, "o/mine")
    assert line is not None
    assert line.startswith("[github-config]")
    assert "o/mine" in line
    assert "1 UNPROTECTED" in line and "1 required_linear_history" in line
    # The DATA-EXFILTRATION guard: nothing about any other repo — not its name, not its
    # finding class, not even a count that includes it.
    assert "o/other" not in line
    assert "NO_CI" not in line and "no CI workflows" not in line
    # The notification MUST carry the remedy, scoped to THIS repo only.
    assert f"{gca.FIX_SKILL} --slug o/mine" in line


def test_summarize_for_slug_refuses_unsafe_or_missing_slug() -> None:
    """The slug comes off a git remote URL (untrusted); an injection-shaped or absent slug
    surfaces NOTHING — never a fallback to fleet data."""
    payload = _payload("UNPROTECTED")
    assert gca.summarize_for_slug(payload, "") is None
    assert gca.summarize_for_slug(payload, "no-slash") is None
    assert gca.summarize_for_slug(payload, "o/r0 [evil] `x`") is None


def test_payload_for_slug_filters_strictly() -> None:
    payload = _payload("UNPROTECTED", "NO_CI")  # slugs o/r0, o/r1
    assert gca.payload_for_slug(payload, "o/r0")["findings"] == [
        {"slug": "o/r0", "code": "UNPROTECTED", "detail": "d"}
    ]
    assert gca.payload_for_slug(payload, "o/rX")["findings"] == []
    assert gca.payload_for_slug(None, "o/r0")["findings"] == []


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


# ---------- TRDD-88ZVEQY7: the age gate (janitor#244) -----------------------


def test_payload_age_accepts_both_timestamp_shapes() -> None:
    """The two writers disagree: `_read_findings`'s comment claims ISO-8601, but every payload
    measured on the host carries an INT epoch. A reader that assumed either alone would crash
    or mis-age the other, so both must work."""
    now = 1_000_000
    assert gca.payload_age_seconds({"generated_at": now - 3600}, now=now) == 3600
    assert gca.payload_age_seconds({"generated_at": str(now - 3600)}, now=now) == 3600
    iso = "1970-01-12T13:46:40+00:00"  # == epoch 1_000_000
    assert gca.payload_age_seconds({"generated_at": iso}, now=now) == 0


def test_payload_age_is_none_when_unusable_and_never_negative() -> None:
    for bad in ({}, {"generated_at": ""}, {"generated_at": "not-a-date"}, {"generated_at": 0},
                {"generated_at": True}, "not-a-dict", None):
        assert gca.payload_age_seconds(bad, now=1_000_000) is None, bad
    # A payload from the future must not read as a huge negative age.
    assert gca.payload_age_seconds({"generated_at": 2_000_000}, now=1_000_000) == 0


def test_stale_gate_withholds_past_the_factor_and_fails_open_on_unknown() -> None:
    c = gca.AUDIT_CADENCE_S
    assert gca.payload_is_stale(c * gca.STALE_FACTOR) is False, "exactly at the bar is not past it"
    assert gca.payload_is_stale(c * gca.STALE_FACTOR + 1) is True
    # Fail OPEN: an unparseable age must not silence the channel — an age-labelled finding
    # beats no finding.
    assert gca.payload_is_stale(None) is False


def test_age_label_never_omits_the_clause() -> None:
    """A MISSING age reads identically to a fresh one for a hurried reader — which is the
    janitor#244 failure. Unknown must SAY unknown."""
    assert "unknown" in gca.age_label(None)
    assert "22.2d" in gca.age_label(int(22.23 * 86400))
    assert "fresh" in gca.age_label(60)


def test_staleness_line_withholds_without_implying_clean() -> None:
    line = gca.staleness_line(30 * 86400, "Emasoft/ai-maestro-janitor")
    assert "WITHHELD" in line and "Nothing is claimed" in line
    assert "Emasoft/ai-maestro-janitor" in line
    # It must carry the live-probe remedy, not leave the reader stuck with a dead payload.
    assert "/janitor-github-config-fix" in line


# ---- NO_PR_REVIEW honours the builder's conditional-PR ruling (janitor#283) ----

def test_no_pr_review_is_silent_where_the_builder_omits_the_rule() -> None:
    """THE janitor#283 fixture: a solo-owned standalone repo (pr_review_expected=False,
    the gatherer's resolution of require_pull_request_for) with no pull_request rule is
    BASELINED CORRECTLY by our own builder — flagging it contradicts the SSOT, and the
    fix path would re-impose the rule the USER's 2026-08-13 ruling removed. This test
    FAILS on the pre-fix classifier (which emitted the finding unconditionally)."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[_branch_rs("deletion", "non_fast_forward"), _tag_rs()],
        classic_protected=None, has_workflows=True,
        pr_review_expected=False,
    )
    assert "NO_PR_REVIEW" not in _codes(facts)


def test_no_pr_review_still_fires_where_the_builder_demands_the_rule() -> None:
    """FALSIFY the fix's over-reach: identical facts with pr_review_expected=True (harness
    repo / someone else's repo) must still flag the genuinely missing rule."""
    facts = RepoFacts(
        slug="o/r", admin=True, default_branch="main",
        rulesets=[_branch_rs("deletion", "non_fast_forward"), _tag_rs()],
        classic_protected=None, has_workflows=True,
        pr_review_expected=True,
    )
    assert "NO_PR_REVIEW" in _codes(facts)


def test_gatherer_resolves_pr_review_expected_from_the_builder_predicate(monkeypatch) -> None:
    """ONE predicate, the builder's own: gather_repo_facts must carry
    require_pull_request_for(slug) into the facts — the classifier is pure and never
    probes. Both answers are exercised so a hardcoded field cannot pass."""
    monkeypatch.setattr(gca.bpl, "viewer_is_admin", lambda _s: True)
    monkeypatch.setattr(gca.bpl, "detect_default_branch", lambda _s: "main")
    monkeypatch.setattr(gca, "_full_rulesets", lambda _s: [])
    monkeypatch.setattr(gca, "_classic_protected", lambda _s, _b: None)
    monkeypatch.setattr(gca, "_has_workflows", lambda _s: False)
    for answer in (False, True):
        monkeypatch.setattr(gca.bpl, "require_pull_request_for", lambda _s, _a=answer: _a)
        assert gca.gather_repo_facts("o/r").pr_review_expected is answer
