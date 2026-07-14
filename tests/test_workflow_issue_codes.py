"""Workflow rule id → issue code: the map must be TOTAL (TRDD-CGYMUKO6, Phase 3).

The acceptance criterion for the issue catalog is that every finding every scanner can emit has a
code. For the workflow auditor that is 54 rule ids across two tiers, and a claim that size is worth
exactly as much as the test that checks it — so this file enumerates the rule set from the SCANNERS
THEMSELVES (never a copy of the list) and fails if any rule has no mapping.

That indirection is the point: a copied list agrees with itself forever. Adding a rule to
zizmor_patterns or a Sentinel module and forgetting the code should BREAK the build, because the
alternative is a security finding that silently lands in a bucket labelled "other".
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import issue_catalog  # noqa: E402
import workflow_issue_codes as wfcodes  # noqa: E402
from lib.sentinel.rules_absence import RULES as ABSENCE  # noqa: E402
from lib.sentinel.rules_context import RULES as CONTEXT  # noqa: E402
from lib.sentinel.rules_extra import RULES as EXTRA  # noqa: E402
from lib.sentinel.rules_injection import RULES as INJECTION  # noqa: E402
from lib.zizmor_patterns import PATTERNS  # noqa: E402
from lib.zizmor_patterns_extra import PATTERNS_EXTRA  # noqa: E402


def emittable_rule_ids() -> set[str]:
    """Every rule id the workflow auditor can actually emit — read from the scanners, not a list."""
    ids = set(PATTERNS) | set(PATTERNS_EXTRA)
    ids |= {r.name for r in (*ABSENCE, *CONTEXT, *INJECTION, *EXTRA)}
    return ids


def test_every_emittable_rule_has_a_code() -> None:
    """THE coverage criterion. A rule with no code is a finding that cannot become a ticket."""
    missing = sorted(emittable_rule_ids() - set(wfcodes.CODE_FOR_RULE))
    assert not missing, (
        f"{len(missing)} workflow rule(s) have no issue code: {missing}\n"
        "Add each to the right class in scripts/lib/workflow_issue_codes.py — group by THE FIX "
        "(which repair answers it), not by the rule's name."
    )


def test_the_map_has_no_rules_that_do_not_exist() -> None:
    """The other direction: a mapping for a rule the scanners no longer emit is dead weight, and a
    dead entry is how a map starts lying about what it covers."""
    stale = sorted(set(wfcodes.CODE_FOR_RULE) - emittable_rule_ids())
    assert not stale, f"the map names rule(s) no scanner emits: {stale}"


def test_every_code_the_map_names_exists_in_the_catalog() -> None:
    """A map pointing at a code the catalog does not know would make `raise_issue` return
    `unknown issue code` and DROP a real security finding at detection time."""
    for rule, code in sorted(wfcodes.CODE_FOR_RULE.items()):
        assert code in issue_catalog.ISSUE_CATALOG, f"{rule} → {code}, which is not in the catalog"
    assert wfcodes.FALLBACK_CODE in issue_catalog.ISSUE_CATALOG


def test_every_WFSEC_code_is_actually_reachable() -> None:
    """A code no rule maps to is a documented incident the janitor can never raise — the catalog would
    be advertising a capability that does not exist."""
    reachable = set(wfcodes.CODE_FOR_RULE.values())
    documented = {c for c in issue_catalog.ISSUE_CATALOG if c.startswith("WFSEC-")}
    assert documented == reachable, f"unreachable: {sorted(documented - reachable)}"


def test_the_fallback_never_silently_loses_a_finding() -> None:
    """The runtime safety net. An unmapped rule (a scanner rule added after this build) must still
    produce a code — a heartbeat is the wrong place to discover a mapping gap by dropping a CRITICAL
    finding on the floor. The test above is what stops the net from becoming the design."""
    assert wfcodes.code_for("a-rule-that-does-not-exist-yet") == wfcodes.FALLBACK_CODE
    assert wfcodes.code_for("") == wfcodes.FALLBACK_CODE
