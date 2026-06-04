"""Tests for scripts/lib/pnpm_yarn_workspace_patterns.py.

2 positive + 2 negative (or 2 positive + 1 negative where the rule is
structural) per rule — 16 coverage tests plus 4 data-model sanity checks.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import pnpm_yarn_workspace_patterns as pyw  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_eight_rule_ids() -> None:
    """RULES must expose exactly 8 pyw-prefixed rule IDs."""
    assert isinstance(pyw.RULES, tuple)
    ids = {r.id for r in pyw.RULES}
    expected = {
        "pyw-pnpm-glob-too-broad",
        "pyw-yarn-nodelinker-node-modules",
        "pyw-lerna-npmclientargs-injection",
        "pyw-pnpm-manage-pkg-manager-off",
        "pyw-yarn-nohoist-missing-sensitive",
        "pyw-internal-star-semver-override",
        "pyw-lerna-independent-no-exact-cross-dep",
        "pyw-pnpm-shamefully-hoist",
    }
    assert ids == expected
    assert len(pyw.RULES) == 8


def test_every_rule_has_pyw_prefix_and_valid_severity() -> None:
    """All rule IDs start with pyw- and severity is one of the four canonical values."""
    for rule in pyw.RULES:
        assert rule.id.startswith("pyw-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding has the 7 fields expected by the shared contract."""
    f = pyw.Finding(
        rule_id="pyw-test",
        line=3,
        column=5,
        matched_text="foo",
        severity="HIGH",
        description="desc",
        owasp_asi="ASI-05",
    )
    assert f.rule_id == "pyw-test"
    assert f.line == 3
    assert f.column == 5
    assert f.matched_text == "foo"
    assert f.severity == "HIGH"
    assert f.description == "desc"
    assert f.owasp_asi == "ASI-05"


def test_empty_text_returns_empty_list() -> None:
    """scan_text('') must return [] without raising."""
    assert pyw.scan_text("") == []


# ---------- Rule: pyw-pnpm-glob-too-broad --------------------------------


def test_pnpm_glob_too_broad_fires_on_bare_star() -> None:
    """pnpm-workspace.yaml bare * in packages list triggers the rule."""
    text = "packages:\n  - '*'\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-pnpm-glob-too-broad"]
    assert findings, "Expected finding for bare '*' glob"


def test_pnpm_glob_too_broad_fires_on_double_star() -> None:
    """pnpm-workspace.yaml bare ** in packages list triggers the rule."""
    text = 'packages:\n  - "**"\n'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-pnpm-glob-too-broad"]
    assert findings, "Expected finding for bare '**' glob"


def test_pnpm_glob_too_broad_no_fire_for_scoped_glob() -> None:
    """packages/* or apps/* should NOT trigger the rule."""
    text = "packages:\n  - 'packages/*'\n  - 'apps/*'\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-pnpm-glob-too-broad"]
    assert not findings, "Should not fire for scoped subdirectory globs"


def test_pnpm_glob_too_broad_no_fire_for_named_package() -> None:
    """An explicit package name in the packages list must not trigger."""
    text = "packages:\n  - 'packages/my-lib'\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-pnpm-glob-too-broad"]
    assert not findings, "Should not fire for explicit named package"


# ---------- Rule: pyw-yarn-nodelinker-node-modules -----------------------


def test_yarn_nodelinker_fires_on_node_modules() -> None:
    """nodeLinker: node-modules in .yarnrc.yml triggers the rule."""
    text = "nodeLinker: node-modules\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-yarn-nodelinker-node-modules"]
    assert findings, "Expected finding for nodeLinker: node-modules"


def test_yarn_nodelinker_fires_with_leading_whitespace() -> None:
    """nodeLinker with leading spaces still triggers the rule."""
    text = "  nodeLinker: node-modules\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-yarn-nodelinker-node-modules"]
    assert findings, "Expected finding even with leading whitespace"


def test_yarn_nodelinker_no_fire_for_pnp() -> None:
    """nodeLinker: pnp is the safe setting and must not trigger."""
    text = "nodeLinker: pnp\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-yarn-nodelinker-node-modules"]
    assert not findings, "pnp linker is safe — should not fire"


def test_yarn_nodelinker_no_fire_for_pnpm_linker() -> None:
    """nodeLinker: pnpm should not trigger the node-modules rule."""
    text = "nodeLinker: pnpm\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-yarn-nodelinker-node-modules"]
    assert not findings, "pnpm linker is not node-modules — should not fire"


# ---------- Rule: pyw-lerna-npmclientargs-injection ----------------------


def test_lerna_npmclientargs_fires_on_injection() -> None:
    """lerna.json with npmClientArgs array triggers the rule."""
    text = '{\n  "npmClientArgs": ["--ignore-scripts=false"]\n}\n'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-lerna-npmclientargs-injection"]
    assert findings, "Expected finding for npmClientArgs"


def test_lerna_npmclientargs_fires_with_registry_redirect() -> None:
    """npmClientArgs with a --registry flag also triggers."""
    text = '{"npmClientArgs": ["--registry", "https://attacker.example/"]}'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-lerna-npmclientargs-injection"]
    assert findings, "Expected finding for --registry injection"


def test_lerna_npmclientargs_no_fire_for_clean_config() -> None:
    """Clean lerna.json without npmClientArgs must not trigger."""
    text = '{\n  "version": "independent",\n  "npmClient": "pnpm"\n}\n'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-lerna-npmclientargs-injection"]
    assert not findings, "Clean lerna.json should not fire"


def test_lerna_npmclientargs_no_fire_for_npmclient_string() -> None:
    """npmClient (string, not array) must not trigger the array pattern."""
    text = '{"npmClient": "yarn"}'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-lerna-npmclientargs-injection"]
    assert not findings, "npmClient string key should not fire"


# ---------- Rule: pyw-pnpm-manage-pkg-manager-off ------------------------


def test_manage_pkg_manager_off_fires_on_false() -> None:
    """manage-package-manager-versions=false triggers the rule."""
    text = "manage-package-manager-versions=false\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-pnpm-manage-pkg-manager-off"]
    assert findings, "Expected finding for =false"


def test_manage_pkg_manager_off_fires_on_yaml_no() -> None:
    """manage-package-manager-versions: no in YAML form triggers the rule."""
    text = "manage-package-manager-versions: no\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-pnpm-manage-pkg-manager-off"]
    assert findings, "Expected finding for yaml 'no'"


def test_manage_pkg_manager_off_no_fire_when_true() -> None:
    """manage-package-manager-versions=true is the safe setting."""
    text = "manage-package-manager-versions=true\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-pnpm-manage-pkg-manager-off"]
    assert not findings, "true is safe — should not fire"


def test_manage_pkg_manager_off_no_fire_for_unrelated_key() -> None:
    """Unrelated .npmrc keys must not trigger the rule."""
    text = "save-exact=true\nauto-install-peers=true\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-pnpm-manage-pkg-manager-off"]
    assert not findings, "Unrelated keys should not fire"


# ---------- Rule: pyw-yarn-nohoist-missing-sensitive ---------------------


def test_yarn_nohoist_fires_on_workspaces_packages_block() -> None:
    """Yarn v1 workspaces with packages block triggers the rule."""
    text = '{\n  "workspaces": {"packages": ["packages/*"]}\n}\n'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-yarn-nohoist-missing-sensitive"]
    assert findings, "Expected finding for workspaces.packages block"


def test_yarn_nohoist_fires_on_inline_packages_compact() -> None:
    """Compact inline form also triggers the rule."""
    text = '{"workspaces":{"packages":["apps/*"]}}'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-yarn-nohoist-missing-sensitive"]
    assert findings, "Expected finding for compact inline form"


def test_yarn_nohoist_no_fire_for_workspaces_array_form() -> None:
    """Yarn v1 shorthand array workspaces (no inner packages key) does not match."""
    text = '{"workspaces": ["packages/*", "apps/*"]}'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-yarn-nohoist-missing-sensitive"]
    assert not findings, "Array shorthand form should not fire"


def test_yarn_nohoist_no_fire_for_unrelated_json() -> None:
    """JSON without a workspaces key must not trigger."""
    text = '{"name": "my-app", "version": "1.0.0"}'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-yarn-nohoist-missing-sensitive"]
    assert not findings, "No workspaces key — should not fire"


# ---------- Rule: pyw-internal-star-semver-override ----------------------


def test_star_semver_fires_on_bare_star_dep() -> None:
    """dependencies with bare '*' semver triggers the rule."""
    text = '{\n  "dependencies": {\n    "@myco/shared": "*"\n  }\n}\n'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-internal-star-semver-override"]
    assert findings, "Expected finding for bare '*' in dependencies"


def test_star_semver_fires_on_dev_dep_star() -> None:
    """devDependencies with bare '*' semver triggers the rule."""
    text = '{"devDependencies": {"@myco/utils": "*"}}'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-internal-star-semver-override"]
    assert findings, "Expected finding for bare '*' in devDependencies"


def test_star_semver_no_fire_for_workspace_star() -> None:
    """workspace:* is the safe protocol and must not trigger."""
    text = '{"dependencies": {"@myco/shared": "workspace:*"}}'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-internal-star-semver-override"]
    assert not findings, "workspace:* is safe — should not fire"


def test_star_semver_no_fire_for_exact_version() -> None:
    """Exact version string must not trigger the rule."""
    text = '{"dependencies": {"lodash": "4.17.21"}}'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-internal-star-semver-override"]
    assert not findings, "Exact semver should not fire"


# ---------- Rule: pyw-lerna-independent-no-exact-cross-dep ---------------


def test_lerna_independent_fires_on_independent_version() -> None:
    """lerna.json with 'independent' version string triggers the rule."""
    text = '{\n  "version": "independent"\n}\n'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-lerna-independent-no-exact-cross-dep"]
    assert findings, "Expected finding for 'independent' version"


def test_lerna_independent_fires_with_surrounding_config() -> None:
    """Independent mode embedded in a fuller lerna.json also fires."""
    text = '{"npmClient":"pnpm","version":"independent","packages":["packages/*"]}'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-lerna-independent-no-exact-cross-dep"]
    assert findings, "Expected finding in full config"


def test_lerna_independent_no_fire_for_fixed_version() -> None:
    """Fixed (semver) version in lerna.json must not trigger."""
    text = '{\n  "version": "1.2.3"\n}\n'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-lerna-independent-no-exact-cross-dep"]
    assert not findings, "Fixed version should not fire"


def test_lerna_independent_no_fire_for_unrelated_json() -> None:
    """package.json-style version field must not trigger the rule."""
    text = '{"name": "my-app", "version": "0.1.0"}'
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-lerna-independent-no-exact-cross-dep"]
    assert not findings, "Semver version string should not fire"


# ---------- Rule: pyw-pnpm-shamefully-hoist ------------------------------


def test_shamefully_hoist_fires_on_true() -> None:
    """shamefully-hoist=true triggers the rule."""
    text = "shamefully-hoist=true\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-pnpm-shamefully-hoist"]
    assert findings, "Expected finding for shamefully-hoist=true"


def test_shamefully_hoist_fires_on_yaml_yes() -> None:
    """shamefully-hoist: yes in YAML form also triggers the rule."""
    text = "shamefully-hoist: yes\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-pnpm-shamefully-hoist"]
    assert findings, "Expected finding for yaml 'yes'"


def test_shamefully_hoist_no_fire_when_false() -> None:
    """shamefully-hoist=false is the safe setting."""
    text = "shamefully-hoist=false\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-pnpm-shamefully-hoist"]
    assert not findings, "false is safe — should not fire"


def test_shamefully_hoist_no_fire_for_unrelated_npmrc_key() -> None:
    """Other .npmrc keys must not trigger the shamefully-hoist rule."""
    text = "strict-peer-dependencies=true\nhoist=true\n"
    findings = [f for f in pyw.scan_text(text) if f.rule_id == "pyw-pnpm-shamefully-hoist"]
    assert not findings, "Unrelated keys should not fire"
