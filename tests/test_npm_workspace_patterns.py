"""Tests for scripts/lib/npm_workspace_patterns.py.

Pattern-coverage tests for the 15 npm workspace / pnpm catalog / Yarn
berry workspace-poisoning rules from distill-round-5 angle G:

   1. PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO         (CRITICAL)
   2. PKG-WORKSPACE-FILE-PROTOCOL-TRAVERSAL            (HIGH)
   3. PKG-WORKSPACE-PROTOCOL-SHADOW                    (HIGH)
   4. PKG-WORKSPACE-RESOLUTIONS-OVERRIDE-TRANSITIVE    (HIGH)
   5. PKG-WORKSPACE-PACKAGEEXTENSIONS-INJECTION        (HIGH)
   6. PKG-WORKSPACE-GIT-URL-DEP-PREPARE-RCE            (HIGH)
   7. PKG-WORKSPACE-BUNDLE-DEPENDENCIES-TARBALL        (MEDIUM)
   8. PKG-WORKSPACE-PEER-DEP-META-OPTIONAL-TRUE        (LOW)
   9. PKG-WORKSPACE-CYCLE-AMPLIFICATION                (MEDIUM)
  10. PKG-WORKSPACE-ENGINES-NODE-UNBOUNDED             (LOW)
  11. PKG-WORKSPACE-LOCKFILE-LINTRC-ALLOWED-HOSTS      (HIGH)
  12. PKG-WORKSPACE-PREPUBLISHONLY-SECRET-COPY         (MEDIUM)
  13. PKG-WORKSPACE-SHRINKWRAP-OVERRIDES-LOCK          (MEDIUM)
  14. PKG-WORKSPACE-PNPM-CATALOG-REWRITE               (MEDIUM)
  15. PKG-WORKSPACE-OVERRIDE-VALUE-GIT-URL             (CRITICAL)

Every rule gets at least one positive test (pattern appears, must fire)
and at least one negative test (pattern absent OR benign context). The
file-anchor mechanism gets explicit coverage so anchored rules do NOT
fire when the caller omits `filename` (the test suite catches the
common-by-omission failure mode).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import npm_workspace_patterns as nwp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen() -> None:
    """RULES must be an immutable tuple of 15 rules — one per distill
    proposal."""
    assert isinstance(nwp.RULES, tuple)
    assert len(nwp.RULES) == 15


def test_every_advertised_rule_id_present() -> None:
    """All 15 advertised rule_ids from distill-round-5 angle G must
    exist in RULES — one per proposal."""
    rule_ids = {r.id for r in nwp.RULES}
    expected = {
        "PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO",
        "PKG-WORKSPACE-FILE-PROTOCOL-TRAVERSAL",
        "PKG-WORKSPACE-PROTOCOL-SHADOW",
        "PKG-WORKSPACE-RESOLUTIONS-OVERRIDE-TRANSITIVE",
        "PKG-WORKSPACE-PACKAGEEXTENSIONS-INJECTION",
        "PKG-WORKSPACE-GIT-URL-DEP-PREPARE-RCE",
        "PKG-WORKSPACE-BUNDLE-DEPENDENCIES-TARBALL",
        "PKG-WORKSPACE-PEER-DEP-META-OPTIONAL-TRUE",
        "PKG-WORKSPACE-CYCLE-AMPLIFICATION",
        "PKG-WORKSPACE-ENGINES-NODE-UNBOUNDED",
        "PKG-WORKSPACE-LOCKFILE-LINTRC-ALLOWED-HOSTS",
        "PKG-WORKSPACE-PREPUBLISHONLY-SECRET-COPY",
        "PKG-WORKSPACE-SHRINKWRAP-OVERRIDES-LOCK",
        "PKG-WORKSPACE-PNPM-CATALOG-REWRITE",
        "PKG-WORKSPACE-OVERRIDE-VALUE-GIT-URL",
    }
    assert rule_ids == expected


def test_every_rule_has_owasp_and_ecosystem() -> None:
    """OWASP ASI tag, severity, and ecosystem must be set on every rule."""
    for rule in nwp.RULES:
        assert rule.owasp_asi == "ASI-05", rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.ecosystem in {"npm", "pnpm", "yarn", "bun"}, rule.id


def test_finding_shape() -> None:
    """Finding NamedTuple must have the same shape as
    `pkg_bypass_patterns.Finding` (uniform rendering across modules)."""
    f = nwp.Finding(
        rule_id="PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO",
        line=1,
        column=2,
        matched_text="m",
        severity="CRITICAL",
        description="d",
        owasp_asi="ASI-05",
        ecosystem="npm",
    )
    assert f.rule_id == "PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO"
    assert f.ecosystem == "npm"


def _hits(rule_id: str, text: str, *, filename: str | None = None) -> list[nwp.Finding]:
    """Return only findings of `rule_id` from scan_text(text)."""
    return [f for f in nwp.scan_text(text, filename=filename) if f.rule_id == rule_id]


# ---------- Rule 1: PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO -------------


def test_link_protocol_parent_traversal_positive() -> None:
    """link: with `..` parent traversal must fire — escapes repo tree."""
    assert _hits(
        "PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO",
        '"my-dep": "link:../../../tmp/attacker"',
        filename="package.json",
    )


def test_link_protocol_absolute_path_positive() -> None:
    """link: with absolute path /etc/... must fire."""
    assert _hits(
        "PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO",
        '"my-dep": "link:/etc/secrets"',
        filename="package.json",
    )


def test_portal_protocol_traversal_positive() -> None:
    """portal: with `..` parent traversal must fire (Yarn berry)."""
    assert _hits(
        "PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO",
        '"my-dep": "portal:../sibling/lib"',
        filename="package.json",
    )


def test_link_protocol_workspace_internal_negative() -> None:
    """link: pointing inside the repo (./packages/util) must NOT fire."""
    assert not _hits(
        "PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO",
        '"my-dep": "link:./packages/util"',
        filename="package.json",
    )


def test_link_protocol_anchored_to_package_json() -> None:
    """The link/portal rule is file-anchored to package.json — missing
    filename must NOT fire."""
    assert not _hits(
        "PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO",
        '"my-dep": "link:../../../tmp/attacker"',
        filename=None,
    )


# ---------- Rule 2: PKG-WORKSPACE-FILE-PROTOCOL-TRAVERSAL ----------------


def test_file_protocol_parent_traversal_positive() -> None:
    """file: with `..` traversal must fire (tarball extract from outside
    repo)."""
    assert _hits(
        "PKG-WORKSPACE-FILE-PROTOCOL-TRAVERSAL",
        '"my-dep": "file:../../../etc/secrets/legit.tgz"',
        filename="package.json",
    )


def test_file_protocol_absolute_path_positive() -> None:
    """file: with absolute path must fire."""
    assert _hits(
        "PKG-WORKSPACE-FILE-PROTOCOL-TRAVERSAL",
        '"my-dep": "file:/var/tmp/attacker.tgz"',
        filename="package.json",
    )


def test_file_protocol_workspace_internal_negative() -> None:
    """file: pointing to a workspace-local tarball must NOT fire."""
    assert not _hits(
        "PKG-WORKSPACE-FILE-PROTOCOL-TRAVERSAL",
        '"my-dep": "file:./vendor/local.tgz"',
        filename="package.json",
    )


# ---------- Rule 3: PKG-WORKSPACE-PROTOCOL-SHADOW ------------------------


def test_workspace_protocol_unscoped_positive() -> None:
    """workspace:* on an UNSCOPED name (lodash) must fire — public-name
    shadow risk."""
    assert _hits(
        "PKG-WORKSPACE-PROTOCOL-SHADOW",
        '"lodash": "workspace:*"',
        filename="package.json",
    )


def test_workspace_protocol_scoped_negative() -> None:
    """workspace:* on a SCOPED name (@myorg/util) must NOT fire — scope
    drops collision risk to near-zero."""
    assert not _hits(
        "PKG-WORKSPACE-PROTOCOL-SHADOW",
        '"@myorg/internal-utils": "workspace:*"',
        filename="package.json",
    )


def test_workspace_protocol_carret_tilde_positive() -> None:
    """workspace:^ and workspace:~ on an unscoped name must also fire."""
    assert _hits(
        "PKG-WORKSPACE-PROTOCOL-SHADOW",
        '"axios": "workspace:^"',
        filename="package.json",
    )
    assert _hits(
        "PKG-WORKSPACE-PROTOCOL-SHADOW",
        '"react": "workspace:~"',
        filename="package.json",
    )


# ---------- Rule 4: PKG-WORKSPACE-RESOLUTIONS-OVERRIDE-TRANSITIVE ---------


def test_overrides_block_positive() -> None:
    """A non-empty npm overrides block must fire."""
    text = '{"overrides": { "lodash": "0.0.1-malicious" }}'
    assert _hits(
        "PKG-WORKSPACE-RESOLUTIONS-OVERRIDE-TRANSITIVE",
        text,
        filename="package.json",
    )


def test_resolutions_block_positive() -> None:
    """A non-empty Yarn resolutions block must fire."""
    text = '{"resolutions": { "axios": "0.21.4-evil" }}'
    assert _hits(
        "PKG-WORKSPACE-RESOLUTIONS-OVERRIDE-TRANSITIVE",
        text,
        filename="package.json",
    )


def test_empty_overrides_negative() -> None:
    """An EMPTY overrides block (`{}`) must NOT fire — it's a no-op."""
    text = '{"overrides": { }}'
    assert not _hits(
        "PKG-WORKSPACE-RESOLUTIONS-OVERRIDE-TRANSITIVE",
        text,
        filename="package.json",
    )


def test_overrides_no_overrides_key_negative() -> None:
    """A package.json without overrides/resolutions must NOT fire."""
    text = '{"dependencies": {"lodash": "^4.17.21"}}'
    assert not _hits(
        "PKG-WORKSPACE-RESOLUTIONS-OVERRIDE-TRANSITIVE",
        text,
        filename="package.json",
    )


# ---------- Rule 5: PKG-WORKSPACE-PACKAGEEXTENSIONS-INJECTION ------------


def test_package_extensions_injection_positive() -> None:
    """packageExtensions injecting dependencies into a third-party must
    fire."""
    text = (
        "packageExtensions:\n"
        '  "trusted-package":\n'
        "    dependencies:\n"
        '      "@attacker/innocuous-name": "*"\n'
    )
    assert _hits(
        "PKG-WORKSPACE-PACKAGEEXTENSIONS-INJECTION",
        text,
        filename="pnpm-workspace.yaml",
    )


def test_package_extensions_injection_peer_deps_positive() -> None:
    """packageExtensions injecting peerDependencies (NOT just
    peerDependenciesMeta) must fire."""
    text = (
        "packageExtensions:\n"
        '  "trusted-package":\n'
        "    peerDependencies:\n"
        '      "@attacker/silent": "*"\n'
    )
    assert _hits(
        "PKG-WORKSPACE-PACKAGEEXTENSIONS-INJECTION",
        text,
        filename="pnpm-workspace.yaml",
    )


def test_package_extensions_peer_meta_only_negative() -> None:
    """packageExtensions touching ONLY peerDependenciesMeta (the
    documented legitimate use) must NOT fire."""
    text = (
        "packageExtensions:\n"
        '  "react":\n'
        "    peerDependenciesMeta:\n"
        '      "react-dom":\n'
        "        optional: true\n"
    )
    assert not _hits(
        "PKG-WORKSPACE-PACKAGEEXTENSIONS-INJECTION",
        text,
        filename="pnpm-workspace.yaml",
    )


def test_package_extensions_wrong_file_negative() -> None:
    """packageExtensions block in a NON-anchored file must NOT fire
    (file-anchored to pnpm-workspace.yaml)."""
    text = "packageExtensions:\n  trusted-package:\n    dependencies:\n"
    assert not _hits(
        "PKG-WORKSPACE-PACKAGEEXTENSIONS-INJECTION",
        text,
        filename="random.txt",
    )


# ---------- Rule 6: PKG-WORKSPACE-GIT-URL-DEP-PREPARE-RCE ----------------


def test_git_url_github_short_positive() -> None:
    """github: short form must fire."""
    assert _hits(
        "PKG-WORKSPACE-GIT-URL-DEP-PREPARE-RCE",
        '"my-dep": "github:attacker/repo#abc123"',
        filename="package.json",
    )


def test_git_url_git_plus_https_positive() -> None:
    """git+https:// must fire."""
    assert _hits(
        "PKG-WORKSPACE-GIT-URL-DEP-PREPARE-RCE",
        '"my-dep": "git+https://github.com/attacker/repo.git"',
        filename="package.json",
    )


def test_git_url_git_plus_ssh_positive() -> None:
    """git+ssh:// must fire."""
    assert _hits(
        "PKG-WORKSPACE-GIT-URL-DEP-PREPARE-RCE",
        '"my-dep": "git+ssh://git@github.com/attacker/repo.git"',
        filename="package.json",
    )


def test_git_url_gitlab_positive() -> None:
    """gitlab: short form must fire."""
    assert _hits(
        "PKG-WORKSPACE-GIT-URL-DEP-PREPARE-RCE",
        '"my-dep": "gitlab:attacker/repo"',
        filename="package.json",
    )


def test_git_url_semver_negative() -> None:
    """A normal semver dep must NOT fire."""
    assert not _hits(
        "PKG-WORKSPACE-GIT-URL-DEP-PREPARE-RCE",
        '"my-dep": "^1.0.0"',
        filename="package.json",
    )


def test_git_url_https_tarball_negative() -> None:
    """A plain https tarball URL (no `git+`) must NOT fire."""
    assert not _hits(
        "PKG-WORKSPACE-GIT-URL-DEP-PREPARE-RCE",
        '"my-dep": "https://example.com/tarball.tgz"',
        filename="package.json",
    )


# ---------- Rule 7: PKG-WORKSPACE-BUNDLE-DEPENDENCIES-TARBALL ------------


def test_bundle_dependencies_non_empty_positive() -> None:
    """A non-empty bundleDependencies array must fire."""
    assert _hits(
        "PKG-WORKSPACE-BUNDLE-DEPENDENCIES-TARBALL",
        '"bundleDependencies": ["lodash"]',
        filename="package.json",
    )


def test_bundledDependencies_alias_positive() -> None:
    """The `bundledDependencies` alias must also fire."""
    assert _hits(
        "PKG-WORKSPACE-BUNDLE-DEPENDENCIES-TARBALL",
        '"bundledDependencies": ["axios"]',
        filename="package.json",
    )


def test_bundle_dependencies_empty_negative() -> None:
    """An EMPTY bundleDependencies array (`[]`) must NOT fire — it's a
    no-op."""
    assert not _hits(
        "PKG-WORKSPACE-BUNDLE-DEPENDENCIES-TARBALL",
        '"bundleDependencies": []',
        filename="package.json",
    )


# ---------- Rule 8: PKG-WORKSPACE-PEER-DEP-META-OPTIONAL-TRUE ------------


def test_peer_deps_meta_optional_true_positive() -> None:
    """peerDependenciesMeta.optional: true must fire (warning silencer)."""
    text = '{"peerDependenciesMeta": { "react": { "optional": true } }}'
    assert _hits(
        "PKG-WORKSPACE-PEER-DEP-META-OPTIONAL-TRUE",
        text,
        filename="package.json",
    )


def test_peer_deps_meta_optional_false_negative() -> None:
    """peerDependenciesMeta with optional: false must NOT fire."""
    text = '{"peerDependenciesMeta": { "react": { "optional": false } }}'
    assert not _hits(
        "PKG-WORKSPACE-PEER-DEP-META-OPTIONAL-TRUE",
        text,
        filename="package.json",
    )


# ---------- Rule 9: PKG-WORKSPACE-CYCLE-AMPLIFICATION --------------------


def test_workspace_dep_plus_postinstall_positive() -> None:
    """A package.json with BOTH a workspace: dep AND a postinstall
    script must fire (cycle-amplification candidate)."""
    text = (
        "{\n"
        '  "scripts": { "postinstall": "node setup.js" },\n'
        '  "dependencies": { "@scope/x": "workspace:*" }\n'
        "}\n"
    )
    assert _hits(
        "PKG-WORKSPACE-CYCLE-AMPLIFICATION",
        text,
        filename="package.json",
    )


def test_workspace_dep_plus_preinstall_positive() -> None:
    """preinstall script also triggers the amplification marker."""
    text = (
        "{\n"
        '  "dependencies": { "@scope/x": "workspace:*" },\n'
        '  "scripts": { "preinstall": "node setup.js" }\n'
        "}\n"
    )
    assert _hits(
        "PKG-WORKSPACE-CYCLE-AMPLIFICATION",
        text,
        filename="package.json",
    )


def test_workspace_dep_without_install_script_negative() -> None:
    """A workspace: dep WITHOUT any postinstall/preinstall must NOT
    fire."""
    text = (
        "{\n"
        '  "dependencies": { "@scope/x": "workspace:*" },\n'
        '  "scripts": { "build": "tsc" }\n'
        "}\n"
    )
    assert not _hits(
        "PKG-WORKSPACE-CYCLE-AMPLIFICATION",
        text,
        filename="package.json",
    )


def test_postinstall_without_workspace_dep_negative() -> None:
    """A postinstall script WITHOUT any workspace: dep must NOT fire."""
    text = (
        "{\n"
        '  "scripts": { "postinstall": "node setup.js" },\n'
        '  "dependencies": { "@scope/x": "^1.0.0" }\n'
        "}\n"
    )
    assert not _hits(
        "PKG-WORKSPACE-CYCLE-AMPLIFICATION",
        text,
        filename="package.json",
    )


# ---------- Rule 10: PKG-WORKSPACE-ENGINES-NODE-UNBOUNDED ----------------


def test_engines_node_star_positive() -> None:
    """engines.node: '*' must fire — allows any version including EOL."""
    assert _hits(
        "PKG-WORKSPACE-ENGINES-NODE-UNBOUNDED",
        '"engines": { "node": "*" }',
        filename="package.json",
    )


def test_engines_node_ge_zero_positive() -> None:
    """engines.node: '>=0' must fire — unbounded low end."""
    assert _hits(
        "PKG-WORKSPACE-ENGINES-NODE-UNBOUNDED",
        '"engines": { "node": ">=0" }',
        filename="package.json",
    )


def test_engines_node_ge_4_positive() -> None:
    """engines.node: '>=4' must fire — Node 4 is EOL."""
    assert _hits(
        "PKG-WORKSPACE-ENGINES-NODE-UNBOUNDED",
        '"engines": { "node": ">=4" }',
        filename="package.json",
    )


def test_engines_node_ge_16_positive() -> None:
    """engines.node: '>=16' must fire — Node 16 is EOL."""
    assert _hits(
        "PKG-WORKSPACE-ENGINES-NODE-UNBOUNDED",
        '"engines": { "node": ">=16" }',
        filename="package.json",
    )


def test_engines_node_ge_18_negative() -> None:
    """engines.node: '>=18' must NOT fire — current LTS minus 2."""
    assert not _hits(
        "PKG-WORKSPACE-ENGINES-NODE-UNBOUNDED",
        '"engines": { "node": ">=18" }',
        filename="package.json",
    )


def test_engines_node_ge_22_negative() -> None:
    """engines.node: '^22' must NOT fire — current LTS."""
    assert not _hits(
        "PKG-WORKSPACE-ENGINES-NODE-UNBOUNDED",
        '"engines": { "node": "^22" }',
        filename="package.json",
    )


# ---------- Rule 11: PKG-WORKSPACE-LOCKFILE-LINTRC-ALLOWED-HOSTS ---------


def test_allowed_hosts_present_positive() -> None:
    """A non-empty allowed-hosts array must fire — detector audits
    contents."""
    text = '{"allowed-hosts": ["attacker-mirror.example.com"]}'
    assert _hits(
        "PKG-WORKSPACE-LOCKFILE-LINTRC-ALLOWED-HOSTS",
        text,
        filename=".lockfile-lintrc",
    )


def test_allowed_hosts_with_npmjs_also_positive() -> None:
    """allowed-hosts containing registry.npmjs.org STILL fires at the
    regex layer — the detector demotes such findings after parsing."""
    text = '{"allowed-hosts": ["registry.npmjs.org"]}'
    assert _hits(
        "PKG-WORKSPACE-LOCKFILE-LINTRC-ALLOWED-HOSTS",
        text,
        filename=".lockfile-lintrc",
    )


def test_allowed_hosts_wrong_file_negative() -> None:
    """Allowed-hosts in a file that isn't `.lockfile-lintrc` must NOT
    fire (file-anchored)."""
    text = '{"allowed-hosts": ["evil.example.com"]}'
    assert not _hits(
        "PKG-WORKSPACE-LOCKFILE-LINTRC-ALLOWED-HOSTS",
        text,
        filename="package.json",
    )


# ---------- Rule 12: PKG-WORKSPACE-PREPUBLISHONLY-SECRET-COPY ------------


def test_prepublishonly_cp_dotenv_positive() -> None:
    """prepublishOnly running `cp .env dist/` must fire."""
    text = '"prepublishOnly": "cp .env dist/ && npm pack"'
    assert _hits(
        "PKG-WORKSPACE-PREPUBLISHONLY-SECRET-COPY",
        text,
        filename="package.json",
    )


def test_prepublishonly_rsync_secrets_positive() -> None:
    """prepublishOnly running rsync of secrets must fire."""
    text = '"prepublishOnly": "rsync -av ./secrets/ ./dist/secret/"'
    assert _hits(
        "PKG-WORKSPACE-PREPUBLISHONLY-SECRET-COPY",
        text,
        filename="package.json",
    )


def test_prepublishonly_safe_build_negative() -> None:
    """A legitimate prepublishOnly build step must NOT fire (no secret
    tokens)."""
    text = '"prepublishOnly": "npm run build && npm run test"'
    assert not _hits(
        "PKG-WORKSPACE-PREPUBLISHONLY-SECRET-COPY",
        text,
        filename="package.json",
    )


# ---------- Rule 13: PKG-WORKSPACE-SHRINKWRAP-OVERRIDES-LOCK -------------


def test_shrinkwrap_filename_in_dockerfile_positive() -> None:
    """A Dockerfile referencing npm-shrinkwrap.json must fire — the
    only un-anchored rule, fires anywhere."""
    text = "COPY npm-shrinkwrap.json /app/"
    assert _hits(
        "PKG-WORKSPACE-SHRINKWRAP-OVERRIDES-LOCK",
        text,
    )


def test_shrinkwrap_filename_in_workflow_positive() -> None:
    """A workflow step referencing npm-shrinkwrap.json must fire."""
    text = "- run: cp npm-shrinkwrap.json ./build/"
    assert _hits(
        "PKG-WORKSPACE-SHRINKWRAP-OVERRIDES-LOCK",
        text,
    )


def test_shrinkwrap_no_reference_negative() -> None:
    """Text without npm-shrinkwrap.json must NOT fire."""
    text = "COPY package.json package-lock.json /app/"
    assert not _hits(
        "PKG-WORKSPACE-SHRINKWRAP-OVERRIDES-LOCK",
        text,
    )


# ---------- Rule 14: PKG-WORKSPACE-PNPM-CATALOG-REWRITE ------------------


def test_pnpm_catalogs_plural_positive() -> None:
    """pnpm `catalogs:` (plural) must fire."""
    text = "catalogs:\n  react18:\n    react: 18.0.0\n"
    assert _hits(
        "PKG-WORKSPACE-PNPM-CATALOG-REWRITE",
        text,
        filename="pnpm-workspace.yaml",
    )


def test_pnpm_catalog_singular_positive() -> None:
    """pnpm `catalog:` (singular) must also fire."""
    text = "catalog:\n  react: 18.0.0\n  lodash: 4.17.21\n"
    assert _hits(
        "PKG-WORKSPACE-PNPM-CATALOG-REWRITE",
        text,
        filename="pnpm-workspace.yaml",
    )


def test_pnpm_catalog_wrong_file_negative() -> None:
    """`catalogs:` in a NON-pnpm-workspace file must NOT fire."""
    text = "catalogs:\n  react18:\n    react: 18.0.0\n"
    assert not _hits(
        "PKG-WORKSPACE-PNPM-CATALOG-REWRITE",
        text,
        filename="package.json",
    )


def test_pnpm_no_catalogs_negative() -> None:
    """A pnpm-workspace.yaml without catalogs: must NOT fire."""
    text = "packages:\n  - 'packages/*'\n"
    assert not _hits(
        "PKG-WORKSPACE-PNPM-CATALOG-REWRITE",
        text,
        filename="pnpm-workspace.yaml",
    )


# ---------- Rule 15: PKG-WORKSPACE-OVERRIDE-VALUE-GIT-URL ----------------


def test_override_value_github_positive() -> None:
    """An overrides block forcing a transitive to github: must fire
    CRITICAL."""
    text = '{"overrides": {"lodash": "github:attacker/lodash#abc"}}'
    findings = _hits(
        "PKG-WORKSPACE-OVERRIDE-VALUE-GIT-URL",
        text,
        filename="package.json",
    )
    assert findings
    assert findings[0].severity == "CRITICAL"


def test_override_value_git_plus_positive() -> None:
    """An overrides block forcing a transitive to git+https:// must
    fire."""
    text = '{"overrides": {"axios": "git+https://attacker/repo.git"}}'
    assert _hits(
        "PKG-WORKSPACE-OVERRIDE-VALUE-GIT-URL",
        text,
        filename="package.json",
    )


def test_override_value_link_positive() -> None:
    """An overrides block forcing a transitive to link: must fire."""
    text = '{"overrides": {"react": "link:../../tmp/attacker"}}'
    assert _hits(
        "PKG-WORKSPACE-OVERRIDE-VALUE-GIT-URL",
        text,
        filename="package.json",
    )


def test_resolutions_value_file_positive() -> None:
    """A resolutions block forcing a transitive to file: must fire."""
    text = '{"resolutions": {"lodash": "file:../attacker.tgz"}}'
    assert _hits(
        "PKG-WORKSPACE-OVERRIDE-VALUE-GIT-URL",
        text,
        filename="package.json",
    )


def test_override_normal_semver_negative() -> None:
    """An overrides block with a normal semver target must NOT fire
    Rule 15 (Rule 4 still fires — that's by design)."""
    text = '{"overrides": {"lodash": "^4.17.21"}}'
    assert not _hits(
        "PKG-WORKSPACE-OVERRIDE-VALUE-GIT-URL",
        text,
        filename="package.json",
    )


# ---------- Scanner-level / file-anchor mechanism ------------------------


def test_scan_text_empty_returns_empty() -> None:
    """Empty text => empty findings list."""
    assert nwp.scan_text("") == []


def test_scan_text_findings_sorted() -> None:
    """Findings must be sorted by (line, column, rule_id) for stable
    rendering."""
    text = (
        '{\n'
        '  "engines": { "node": "*" },\n'
        '  "overrides": { "lodash": "0.0.1" }\n'
        '}\n'
    )
    findings = nwp.scan_text(text, filename="package.json")
    for prev, curr in zip(findings, findings[1:], strict=False):
        assert (prev.line, prev.column, prev.rule_id) <= (
            curr.line,
            curr.column,
            curr.rule_id,
        )


def test_file_anchor_gates_rule_when_filename_missing() -> None:
    """When `filename=None`, ALL file-anchored rules must be skipped.
    Only the un-anchored shrinkwrap rule (Rule 13) is allowed to fire."""
    # Inject a clear positive for Rule 1 (would fire WITH filename=
    # "package.json") and check it does NOT fire WITHOUT a filename.
    text = '"my-dep": "link:../../../tmp/attacker"'
    assert not _hits(
        "PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO",
        text,
        filename=None,
    )
    # Sanity: WITH filename it fires.
    assert _hits(
        "PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO",
        text,
        filename="package.json",
    )


def test_file_anchor_case_insensitive() -> None:
    """File-anchor matching must be case-insensitive on the basename —
    `PACKAGE.JSON` resolves to the same rule set as `package.json`."""
    text = '"my-dep": "link:../../../tmp/attacker"'
    assert _hits(
        "PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO",
        text,
        filename="PACKAGE.JSON",
    )


def test_file_anchor_basename_extraction_unix() -> None:
    """Unix-style absolute path must extract basename correctly."""
    text = '"my-dep": "link:../../../tmp/attacker"'
    assert _hits(
        "PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO",
        text,
        filename="/some/path/to/package.json",
    )


def test_file_anchor_basename_extraction_windows() -> None:
    """Windows-style absolute path must extract basename correctly."""
    text = '"my-dep": "link:../../../tmp/attacker"'
    assert _hits(
        "PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO",
        text,
        filename=r"C:\repo\package.json",
    )


def test_no_re2_unsafe_constructs() -> None:
    """Every rule's pattern must avoid RE2-incompatible constructs:
    no backreferences (`\\1`..`\\9`), no lookahead (`(?=`, `(?!`), no
    lookbehind (`(?<=`, `(?<!`). This guards against future edits
    sneaking in non-portable patterns."""
    import re as _re_mod
    forbidden = _re_mod.compile(r"\\[1-9]|\(\?=|\(\?!|\(\?<=|\(\?<!")
    for rule in nwp.RULES:
        assert not forbidden.search(rule.pattern.pattern), (
            f"RE2-unsafe pattern in rule {rule.id}: "
            f"{rule.pattern.pattern!r}"
        )


def test_findings_deduplicated_on_same_line_column() -> None:
    """The same rule firing twice on the same (line, column) must
    appear only once in findings."""
    text = '"my-dep": "link:../../../tmp/attacker"'
    findings = nwp.scan_text(text, filename="package.json")
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))


def test_composite_rule_15_fires_along_with_4_and_6() -> None:
    """An overrides block targeting a git URL fires THREE rules at
    once: Rule 4 (overrides present), Rule 6 (git URL dep), Rule 15
    (composite). That's intentional — the composite is CRITICAL, the
    constituents are HIGH each, and the detector can use the
    intersection for confidence scoring."""
    text = '{"overrides": {"lodash": "github:attacker/lodash#abc"}}'
    findings = nwp.scan_text(text, filename="package.json")
    rule_ids = {f.rule_id for f in findings}
    assert "PKG-WORKSPACE-OVERRIDE-VALUE-GIT-URL" in rule_ids
    assert "PKG-WORKSPACE-RESOLUTIONS-OVERRIDE-TRANSITIVE" in rule_ids
    assert "PKG-WORKSPACE-GIT-URL-DEP-PREPARE-RCE" in rule_ids
