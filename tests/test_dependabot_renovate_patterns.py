"""Tests for scripts/lib/dependabot_renovate_patterns.py.

Pattern-coverage tests for the Wave-22 distill-round-8 angle F
catalogue (18 rule IDs covering Dependabot / Renovate config gaming
plus auto-merge / pull_request_target workflow primitives). Each
rule has at least one positive test exercising the canary AND at
least one negative test exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import dependabot_renovate_patterns as drp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 18 documented rule IDs."""
    assert isinstance(drp.RULES, tuple)
    rule_ids = {r.id for r in drp.RULES}
    expected = {
        "DR-P1",
        "DR-P2",
        "DR-P3",
        "DR-P4",
        "DR-P5",
        "DR-P6",
        "DR-P7-CATCHALL",
        "DR-P7-BROAD",
        "DR-P7-BRANCH-MODE",
        "DR-P8",
        "DR-P9",
        "DR-P10",
        "DR-P11-TLD",
        "DR-P11-IP",
        "DR-P11-HOSTRULES",
        "DR-P12",
        "DR-P13-EXPR",
        "DR-P13-PUSH",
    }
    assert expected == rule_ids
    assert len(drp.RULES) == 18


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI prefix and a known severity."""
    for rule in drp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding carries the eight documented fields in stable order."""
    f = drp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-05",
        file_anchor="dependabot.yml",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-05"
    assert f.file_anchor == "dependabot.yml"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert drp.scan_text("") == []
    assert drp.scan_text("", filename="dependabot.yml") == []


def _hits(rule_id: str, src: str, *, filename: str = "") -> list[drp.Finding]:
    return [
        f for f in drp.scan_text(src, filename=filename or None)
        if f.rule_id == rule_id
    ]


# ---------- DR-P1 : dependabot-cooldown-missing-high-risk-ecosystem ------


def test_dr_p1_npm_package_ecosystem_flags() -> None:
    """Dependabot config declaring HIGH-RISK npm ecosystem fires DR-P1."""
    src = (
        "version: 2\n"
        "updates:\n"
        "  -\n"
        '    package-ecosystem: "npm"\n'
        '    directory: "/"\n'
        "    schedule:\n"
        '      interval: "weekly"\n'
    )
    hits = _hits("DR-P1", src, filename="dependabot.yml")
    assert hits
    assert hits[0].severity == "HIGH"


def test_dr_p1_github_actions_ecosystem_silent() -> None:
    """github-actions ecosystem is NOT in HIGH_RISK_ECOSYSTEMS — no hit."""
    src = (
        "version: 2\n"
        "updates:\n"
        "  -\n"
        '    package-ecosystem: "github-actions"\n'
        '    directory: "/"\n'
    )
    assert not _hits("DR-P1", src, filename="dependabot.yml")


# ---------- DR-P2 : dependabot-insecure-external-code-execution ----------


def test_dr_p2_insecure_exec_allow_flags() -> None:
    """`insecure-external-code-execution: allow` is the CRITICAL canary."""
    src = (
        "version: 2\n"
        "updates:\n"
        "  -\n"
        '    package-ecosystem: "npm"\n'
        "    insecure-external-code-execution: allow\n"
    )
    hits = _hits("DR-P2", src, filename="dependabot.yml")
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_dr_p2_insecure_exec_deny_silent() -> None:
    """Explicit `deny` is the hardened value — no hit."""
    src = (
        "version: 2\n"
        "updates:\n"
        "  -\n"
        '    package-ecosystem: "npm"\n'
        "    insecure-external-code-execution: deny\n"
    )
    assert not _hits("DR-P2", src, filename="dependabot.yml")


# ---------- DR-P3 : dependabot-versioning-strategy-increase --------------


def test_dr_p3_versioning_strategy_increase_flags() -> None:
    """`versioning-strategy: increase` rewrites the manifest — HIGH."""
    src = (
        "version: 2\n"
        "updates:\n"
        "  -\n"
        '    package-ecosystem: "npm"\n'
        "    versioning-strategy: increase\n"
    )
    hits = _hits("DR-P3", src, filename="dependabot.yml")
    assert hits
    assert hits[0].severity == "HIGH"


def test_dr_p3_versioning_strategy_lockfile_only_silent() -> None:
    """`lockfile-only` is in DEPENDABOT_VERSIONING_STRATEGIES_SAFE."""
    src = (
        "version: 2\n"
        "updates:\n"
        "  -\n"
        '    package-ecosystem: "npm"\n'
        "    versioning-strategy: lockfile-only\n"
    )
    assert not _hits("DR-P3", src, filename="dependabot.yml")


# ---------- DR-P4 : dependabot-target-branch-default ---------------------


def test_dr_p4_target_branch_main_flags() -> None:
    """`target-branch: main` (or master) skips the integration branch."""
    src = (
        "version: 2\n"
        "updates:\n"
        "  -\n"
        '    package-ecosystem: "npm"\n'
        "    target-branch: main\n"
    )
    hits = _hits("DR-P4", src, filename="dependabot.yml")
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_dr_p4_target_branch_develop_silent() -> None:
    """A separate integration branch (`develop`) is the hardened pattern."""
    src = (
        "version: 2\n"
        "updates:\n"
        "  -\n"
        '    package-ecosystem: "npm"\n'
        "    target-branch: develop\n"
    )
    assert not _hits("DR-P4", src, filename="dependabot.yml")


# ---------- DR-P5 : renovate-automerge-broad -----------------------------


def test_dr_p5_top_level_automerge_true_flags() -> None:
    """Renovate top-level `automerge: true` is the HIGH canary."""
    src = '{"automerge": true, "extends": ["config:base"]}\n'
    hits = _hits("DR-P5", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_dr_p5_automerge_false_silent() -> None:
    """Explicit `automerge: false` is the hardened value — no hit."""
    src = '{"automerge": false, "extends": ["config:base"]}\n'
    assert not _hits("DR-P5", src)


# ---------- DR-P6 : renovate-dangerous-always-write-default --------------


def test_dr_p6_dangerous_direct_push_flags() -> None:
    """`dangerousAlwaysWriteToDefaultBranch: true` is the HIGH canary."""
    src = '{"dangerousAlwaysWriteToDefaultBranch": true}\n'
    hits = _hits("DR-P6", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_dr_p6_dangerous_direct_push_false_silent() -> None:
    """`dangerousAlwaysWriteToDefaultBranch: false` is hardened."""
    src = '{"dangerousAlwaysWriteToDefaultBranch": false}\n'
    assert not _hits("DR-P6", src)


# ---------- DR-P7-CATCHALL : renovate-allowed-postupgrade-commands -------


def test_dr_p7_catchall_dotstar_flags() -> None:
    """`allowedPostUpgradeCommands: [".*"]` is the CRITICAL canary."""
    src = '{"allowedPostUpgradeCommands": [".*"]}\n'
    hits = _hits("DR-P7-CATCHALL", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_dr_p7_catchall_specific_command_silent() -> None:
    """A specific allowlisted command (no catch-all glob) → no hit."""
    src = '{"allowedPostUpgradeCommands": ["npm run build"]}\n'
    assert not _hits("DR-P7-CATCHALL", src)


# ---------- DR-P7-BROAD : renovate-allowed-postupgrade-broad-prefix ------


def test_dr_p7_broad_npm_prefix_flags() -> None:
    """`allowedPostUpgradeCommands: ["npm .*"]` is the broad HIGH canary."""
    src = '{"allowedPostUpgradeCommands": ["npm .*"]}\n'
    hits = _hits("DR-P7-BROAD", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_dr_p7_broad_specific_npm_command_silent() -> None:
    """`npm run build` is specific, not a broad shell prefix."""
    src = '{"allowedPostUpgradeCommands": ["npm run build"]}\n'
    assert not _hits("DR-P7-BROAD", src)


# ---------- DR-P7-BRANCH-MODE : renovate-postupgrade-branch-mode ---------


def test_dr_p7_branch_mode_flags() -> None:
    """`postUpgradeTasks.executionMode: "branch"` is the HIGH canary."""
    src = '{"postUpgradeTasks": {"executionMode": "branch"}}\n'
    hits = _hits("DR-P7-BRANCH-MODE", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_dr_p7_branch_mode_update_silent() -> None:
    """`executionMode: "update"` is the hardened mode — no hit."""
    src = '{"postUpgradeTasks": {"executionMode": "update"}}\n'
    assert not _hits("DR-P7-BRANCH-MODE", src)


# ---------- DR-P8 : renovate-dashboard-disabled-with-automerge -----------


def test_dr_p8_disable_dashboard_extends_flags() -> None:
    """`:disableDependencyDashboard` in extends is the HIGH canary."""
    src = '{"extends": [":disableDependencyDashboard"]}\n'
    hits = _hits("DR-P8", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_dr_p8_dashboard_default_silent() -> None:
    """Default dashboard config (no disable, no false) → no hit."""
    src = '{"extends": ["config:base"]}\n'
    assert not _hits("DR-P8", src)


# ---------- DR-P9 : renovate-cooldown-scoped-narrower-than-managers ------


def test_dr_p9_match_managers_custom_regex_flags() -> None:
    """`matchManagers: ["custom.regex"]` is the narrow-scope MEDIUM canary."""
    src = (
        '{"packageRules": [{"matchManagers": ["custom.regex"], '
        '"minimumReleaseAge": "7 days"}]}\n'
    )
    hits = _hits("DR-P9", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_dr_p9_match_managers_npm_silent() -> None:
    """`matchManagers: ["npm"]` is a real manager, not custom.regex — no hit."""
    src = (
        '{"packageRules": [{"matchManagers": ["npm"], '
        '"minimumReleaseAge": "7 days"}]}\n'
    )
    assert not _hits("DR-P9", src)


# ---------- DR-P10 : renovate-range-strategy-bump-high-risk --------------


def test_dr_p10_range_strategy_bump_flags() -> None:
    """`"rangeStrategy": "bump"` moves the manifest range — MEDIUM canary."""
    src = '{"rangeStrategy": "bump"}\n'
    hits = _hits("DR-P10", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_dr_p10_range_strategy_pin_silent() -> None:
    """`"rangeStrategy": "pin"` pins exact versions — hardened, no hit."""
    src = '{"rangeStrategy": "pin"}\n'
    assert not _hits("DR-P10", src)


# ---------- DR-P11-TLD : renovate-non-canonical-registry-tld -------------


def test_dr_p11_tld_dot_tk_registry_flags() -> None:
    """A `.tk` TLD in `registryUrls` is the HIGH attacker-mirror canary."""
    src = '{"registryUrls": ["https://attacker.tk/registry"]}\n'
    hits = _hits("DR-P11-TLD", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_dr_p11_tld_canonical_npmjs_silent() -> None:
    """`https://registry.npmjs.org` is in CANONICAL_REGISTRY_URLS — no hit."""
    src = '{"registryUrls": ["https://registry.npmjs.org"]}\n'
    assert not _hits("DR-P11-TLD", src)


# ---------- DR-P11-IP : renovate-registry-url-raw-ipv4 -------------------


def test_dr_p11_ip_raw_ipv4_registry_flags() -> None:
    """A raw IPv4 in `registryUrls` is the HIGH attacker-mirror canary."""
    src = '{"registryUrls": ["https://192.168.1.1/registry"]}\n'
    hits = _hits("DR-P11-IP", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_dr_p11_ip_canonical_dns_silent() -> None:
    """DNS-named canonical registry → no IP hit."""
    src = '{"registryUrls": ["https://registry.npmjs.org/"]}\n'
    assert not _hits("DR-P11-IP", src)


# ---------- DR-P11-HOSTRULES : renovate-hostrules-suspicious-tld ---------


def test_dr_p11_hostrules_dot_tk_flags() -> None:
    """`hostRules.matchHost: "evil.tk"` is the HIGH canary."""
    src = '{"hostRules": [{"matchHost": "evil.tk"}]}\n'
    hits = _hits("DR-P11-HOSTRULES", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_dr_p11_hostrules_github_com_silent() -> None:
    """`hostRules.matchHost: "github.com"` is a legitimate org host — no hit."""
    src = '{"hostRules": [{"matchHost": "github.com"}]}\n'
    assert not _hits("DR-P11-HOSTRULES", src)


# ---------- DR-P12 : workflow-pull-request-target-dependabot-pr ----------


def test_dr_p12_pull_request_target_with_head_ref_flags() -> None:
    """`on: pull_request_target` + checkout head.sha → CRITICAL canary."""
    src = (
        "on:\n"
        "  pull_request_target:\n"
        "    types: [opened]\n"
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          ref: ${{ github.event.pull_request.head.sha }}\n"
    )
    hits = _hits("DR-P12", src)
    assert hits
    # With head-ref checkout present the severity stays CRITICAL.
    assert hits[0].severity == "CRITICAL"


def test_dr_p12_pull_request_no_target_silent() -> None:
    """Standard `on: pull_request` (no `_target`) trigger → no hit."""
    src = (
        "on:\n"
        "  pull_request:\n"
        "    types: [opened]\n"
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
    )
    assert not _hits("DR-P12", src)


# ---------- DR-P13-EXPR : workflow-branch-name-gate-expr -----------------


def test_dr_p13_expr_startswith_dependabot_flags() -> None:
    """`startsWith(github.head_ref, 'dependabot/')` is the HIGH canary."""
    src = "if: startsWith(github.head_ref, 'dependabot/')\n"
    hits = _hits("DR-P13-EXPR", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_dr_p13_expr_actor_gate_silent() -> None:
    """Actor-equality (`github.actor == 'dependabot[bot]'`) is a different
    rule (Wave-16 dependabot-actor-spoofable); this rule does NOT fire."""
    src = "if: github.actor == 'dependabot[bot]'\n"
    assert not _hits("DR-P13-EXPR", src)


# ---------- DR-P13-PUSH : workflow-on-push-branches-dependabot -----------


def test_dr_p13_push_branches_dependabot_star_flags() -> None:
    """`on.push.branches: ['dependabot/*']` is the HIGH canary."""
    src = (
        "on:\n"
        "  push:\n"
        "    branches:\n"
        "      - 'dependabot/*'\n"
    )
    hits = _hits("DR-P13-PUSH", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_dr_p13_push_branches_main_only_silent() -> None:
    """`on.push.branches: [main]` is a normal default-branch CI — no hit."""
    src = (
        "on:\n"
        "  push:\n"
        "    branches:\n"
        "      - main\n"
    )
    assert not _hits("DR-P13-PUSH", src)


# ---------- Structural helper sanity (scan_dependabot_yaml) --------------


def test_scan_dependabot_yaml_per_ecosystem_cooldown_audit() -> None:
    """scan_dependabot_yaml: npm entry without cooldown → DR-P1 HIGH."""
    yml = (
        "version: 2\n"
        "updates:\n"
        "  - package-ecosystem: npm\n"
        "    directory: /\n"
        "    schedule:\n"
        "      interval: weekly\n"
    )
    findings = drp.scan_dependabot_yaml(yml)
    p1 = [f for f in findings if f.rule_id == "DR-P1"]
    assert p1
    assert p1[0].severity == "HIGH"


def test_scan_dependabot_yaml_with_cooldown_passes() -> None:
    """scan_dependabot_yaml: npm + cooldown default-days >= 7 → no DR-P1."""
    yml = (
        "version: 2\n"
        "updates:\n"
        "  - package-ecosystem: npm\n"
        "    directory: /\n"
        "    cooldown:\n"
        "      default-days: 7\n"
        "    schedule:\n"
        "      interval: weekly\n"
    )
    findings = drp.scan_dependabot_yaml(yml)
    assert not [f for f in findings if f.rule_id == "DR-P1"]


# ---------- Structural helper sanity (scan_renovate_json) ----------------


def test_scan_renovate_json_automerge_emits_p5() -> None:
    """scan_renovate_json: top-level automerge true → DR-P5."""
    src = '{"automerge": true}\n'
    findings = drp.scan_renovate_json(src)
    assert [f for f in findings if f.rule_id == "DR-P5"]


def test_scan_renovate_json_clean_config_silent() -> None:
    """A minimal hardened renovate.json should not fire any DR-P rules."""
    src = (
        '{"extends": ["config:base"], "rangeStrategy": "pin", '
        '"automerge": false}\n'
    )
    findings = drp.scan_renovate_json(src)
    # No DR-P5/P6/P10 should fire on this hardened shape.
    rule_ids = {f.rule_id for f in findings}
    assert "DR-P5" not in rule_ids
    assert "DR-P6" not in rule_ids
    assert "DR-P10" not in rule_ids


# ---------- File-anchor enforcement --------------------------------------


def test_dependabot_anchored_rules_respect_filename() -> None:
    """DR-P1..P4 only fire when filename matches dependabot.yml basename."""
    src = (
        "version: 2\n"
        "updates:\n"
        "  -\n"
        '    package-ecosystem: "npm"\n'
        "    target-branch: main\n"
    )
    # Wrong filename — anchored rules must NOT fire.
    assert not _hits("DR-P1", src, filename="some-other.yml")
    assert not _hits("DR-P4", src, filename="some-other.yml")
    # Correct filename — anchored rules fire.
    assert _hits("DR-P1", src, filename="dependabot.yml")
    assert _hits("DR-P4", src, filename="dependabot.yml")


def test_findings_sorted_deterministically() -> None:
    """Findings must be sorted by (line, column, rule_id)."""
    src = (
        '{"automerge": true, '
        '"dangerousAlwaysWriteToDefaultBranch": true, '
        '"rangeStrategy": "bump"}\n'
    )
    findings = drp.scan_text(src)
    assert len(findings) >= 3
    for i in range(len(findings) - 1):
        a = (findings[i].line, findings[i].column, findings[i].rule_id)
        b = (findings[i + 1].line, findings[i + 1].column, findings[i + 1].rule_id)
        assert a <= b
