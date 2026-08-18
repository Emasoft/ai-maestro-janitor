"""Baseline CONTENT comparison (TRDD-DD0M4QL7) — present-by-name must not mask stale-by-content.

Gate 6 of the guard applier used to short-circuit on ruleset NAMES alone
(`baselines_present`), so a hand-loosened or older-parameter ruleset stayed
"converged" forever — the baseline could be created but never MAINTAINED
(hub-verified P1; explains the fleet's 8-of-9 staleness better than drift).
These tests pin the PURE comparison layer: a live ruleset that matches the
ratified payload passes even with server-added response fields; every
loosening the baseline pins must produce a named drift reason.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import branch_protection_lib as bpl  # noqa: E402


def _expected() -> list[dict]:
    return bpl.baseline_ruleset_payloads(
        "main", [{"context": "ci"}], require_pull_request=True
    )


def _as_live(payload: dict) -> dict:
    """A GitHub GET echo of the payload: same content + server-added fields."""
    live = copy.deepcopy(payload)
    live["id"] = 12345
    live["source_type"] = "Repository"
    live["source"] = "Emasoft/example"
    live["created_at"] = "2026-08-01T00:00:00Z"
    live["updated_at"] = "2026-08-01T00:00:00Z"
    # Servers also decorate individual rules with extra keys.
    for rule in live.get("rules", []):
        rule["ruleset_id"] = 12345
    return live


def test_faithful_server_echo_has_no_drift() -> None:
    """A live ruleset identical in pinned content passes despite server-added fields."""
    for payload in _expected():
        assert bpl.ruleset_content_drift(payload, _as_live(payload)) == []


def test_loosened_parameter_is_named_drift() -> None:
    """The exact hub scenario: present by name, loosened by content — must redden."""
    exp = next(p for p in _expected() if p["name"] == bpl.PR_CHECKS_RULESET_NAME)
    live = _as_live(exp)
    for rule in live["rules"]:
        if rule["type"] == "pull_request":
            rule["parameters"]["required_review_thread_resolution"] = False
    drift = bpl.ruleset_content_drift(exp, live)
    assert any("pull_request" in d for d in drift), drift


def test_missing_rule_is_drift() -> None:
    exp = next(p for p in _expected() if p["name"] == bpl.HISTORY_RULESET_NAME)
    live = _as_live(exp)
    live["rules"] = [r for r in live["rules"] if r["type"] != "non_fast_forward"]
    drift = bpl.ruleset_content_drift(exp, live)
    assert any("non_fast_forward" in d for d in drift), drift


def test_disabled_enforcement_is_drift() -> None:
    exp = _expected()[0]
    live = _as_live(exp)
    live["enforcement"] = "evaluate"
    assert any("enforcement" in d for d in bpl.ruleset_content_drift(exp, live))


def test_added_bypass_actor_is_drift() -> None:
    exp = _expected()[0]
    live = _as_live(exp)
    live["bypass_actors"].append(
        {"actor_id": 1, "actor_type": "Integration", "bypass_mode": "always"}
    )
    assert any("bypass" in d for d in bpl.ruleset_content_drift(exp, live))


def test_live_checks_rule_is_not_drift_when_expected_omits_it() -> None:
    """The documented cwd-dependence: a foreign checkout cannot detect CI contexts, so
    the expected payload omits required_status_checks — a live repo that HAS the rule
    (applied earlier from its own checkout) is stricter, never stale."""
    exp = next(
        p
        for p in bpl.baseline_ruleset_payloads("main", [], require_pull_request=True)
        if p["name"] == bpl.PR_CHECKS_RULESET_NAME
    )
    full = next(p for p in _expected() if p["name"] == bpl.PR_CHECKS_RULESET_NAME)
    live = _as_live(full)  # live carries the checks rule
    assert bpl.ruleset_content_drift(exp, live) == []


def test_narrowing_exclude_is_drift() -> None:
    exp = _expected()[0]
    live = _as_live(exp)
    live["conditions"]["ref_name"]["exclude"] = ["refs/heads/main"]
    assert any("conditions" in d for d in bpl.ruleset_content_drift(exp, live))
