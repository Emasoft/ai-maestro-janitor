"""Tests for scripts/lib/sca_lockfile_patterns.py.

Pattern-coverage tests for the Wave-25 distill-round-11 SCA / lockfile-
bypass catalogue (8 install-time integrity-control evasions across npm /
PyPI / Cargo / Go / NuGet). Each rule has at least one positive test
exercising the canary AND at least one negative test exercising the
carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import sca_lockfile_patterns as slp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 8 documented rule IDs."""
    assert isinstance(slp.RULES, tuple)
    rule_ids = {r.id for r in slp.RULES}
    expected = {
        "sca-lockfile-plain-http-registry",
        "sca-lockfile-missing-or-fake-integrity",
        "sca-lockfile-pip-no-deps-target-no-hashes",
        "sca-lockfile-extra-index-url-dependency-confusion",
        "sca-lockfile-cargo-install-git-no-rev-no-locked",
        "sca-lockfile-replace-override-local-path",
        "sca-lockfile-wildcard-checksum-bypass-env",
        "sca-lockfile-goproxy-direct-fallback",
    }
    assert expected == rule_ids
    assert len(slp.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in slp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = slp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-08"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert slp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — plain HTTP registry (SCA-LB-001)
        "registry=http://internal-mirror.corp.example/api/\n"
        # Line 2 — fake integrity (SCA-LB-002)
        '    "integrity": "sha512-fake",\n'
    )
    findings = slp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[slp.Finding]:
    return [f for f in slp.scan_text(text) if f.rule_id == rule_id]


# ---------- SCA-LB-001 : plain-HTTP registry / mirror --------------------


def test_001_plain_http_pip_index_url_flags() -> None:
    """Plain HTTP index-url in pip.conf → HIGH hit."""
    src = (
        "[global]\n"
        "index-url = http://artifactory.corp.example/api/pypi/pypi-virtual/simple/\n"
    )
    hits = _hits("sca-lockfile-plain-http-registry", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_001_plain_http_npm_registry_flags() -> None:
    """Plain HTTP registry in .npmrc → flagged."""
    src = "registry=http://internal-mirror.corp.example/\n"
    assert _hits("sca-lockfile-plain-http-registry", src)


def test_001_cargo_sparse_http_index_flags() -> None:
    """sparse+http:// Cargo index → flagged."""
    src = (
        "[registries.internal]\n"
        'index = "sparse+http://cargo-mirror.corp.example/index/"\n'
    )
    assert _hits("sca-lockfile-plain-http-registry", src)


def test_001_nuget_allow_insecure_flags() -> None:
    """NuGet allowInsecureConnections=true → flagged."""
    src = '<add key="internal" value="http://nuget.corp.example/" allowInsecureConnections="true" />\n'
    assert _hits("sca-lockfile-plain-http-registry", src)


def test_001_localhost_registry_suppressed() -> None:
    """http://localhost devpi/Verdaccio mirror → no hit (FP suppression)."""
    src = "registry=http://localhost:4873/\n"
    assert not _hits("sca-lockfile-plain-http-registry", src)


def test_001_https_registry_silent() -> None:
    """HTTPS index-url → silent (the safe form)."""
    src = (
        "[global]\n"
        "index-url = https://pypi.corp.example/simple/\n"
    )
    assert not _hits("sca-lockfile-plain-http-registry", src)


# ---------- SCA-LB-002 : missing or fake `integrity:` --------------------


def test_002_fake_sha512_value_flags() -> None:
    """`"integrity": "sha512-fake"` → CRITICAL hit."""
    src = (
        '    "node_modules/axios": {\n'
        '      "version": "1.14.1",\n'
        '      "integrity": "sha512-fake"\n'
        "    }\n"
    )
    hits = _hits("sca-lockfile-missing-or-fake-integrity", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_002_deadbeef_short_hash_flags() -> None:
    """`"integrity": "sha1-deadbeef"` → flagged."""
    src = '"integrity": "sha1-deadbeef"\n'
    assert _hits("sca-lockfile-missing-or-fake-integrity", src)


def test_002_empty_integrity_string_flags() -> None:
    """`"integrity": ""` → flagged."""
    src = '    "integrity": ""\n'
    assert _hits("sca-lockfile-missing-or-fake-integrity", src)


def test_002_real_sri_hash_silent() -> None:
    """Real-looking SRI hash (long base64) → no hit."""
    src = (
        '    "integrity": "sha512-EwBzVtFTsKZGZGqXgrA9NCJg1H3yMjFKqcuD9R'
        'O6jKkOIK5RfA1U8eYKQ/H4ZIeAcdC7y1l1z+1mYR8AdHkUyA=="\n'
    )
    assert not _hits("sca-lockfile-missing-or-fake-integrity", src)


# ---------- SCA-LB-003 : pip install --no-deps --target no-hash-gate ----


def test_003_pip_no_deps_target_flags() -> None:
    """`pip install --no-deps --target ./python/lib boto3` → HIGH hit."""
    src = "pip install --no-deps --target ./python/lib boto3 requests pyyaml\n"
    hits = _hits("sca-lockfile-pip-no-deps-target-no-hashes", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_003_pip3_no_deps_target_flags() -> None:
    """`pip3 install --no-deps --target /opt/vendor pkg` → flagged."""
    src = "pip3 install --no-deps --target /opt/app/vendor some-package\n"
    assert _hits("sca-lockfile-pip-no-deps-target-no-hashes", src)


def test_003_pip_with_require_hashes_suppressed() -> None:
    """Same shape but with `--require-hashes` → no hit."""
    src = (
        "pip install --require-hashes --no-deps --target build/site-packages "
        "-r requirements.txt\n"
    )
    assert not _hits("sca-lockfile-pip-no-deps-target-no-hashes", src)


def test_003_editable_local_install_silent() -> None:
    """`pip install --no-deps -e .` → silent (editable local install)."""
    src = "pip install --no-deps -e .\n"
    assert not _hits("sca-lockfile-pip-no-deps-target-no-hashes", src)


def test_003_pip_install_simple_silent() -> None:
    """Plain `pip install requests` → silent (no risky flags)."""
    src = "pip install requests pyyaml\n"
    assert not _hits("sca-lockfile-pip-no-deps-target-no-hashes", src)


# ---------- SCA-LB-004 : --extra-index-url dependency confusion ---------


def test_004_extra_index_url_cli_flag_flags() -> None:
    """`pip install --extra-index-url https://pypi.org/simple/` → HIGH hit."""
    src = "pip install --extra-index-url https://pypi.org/simple/ -r requirements.txt\n"
    hits = _hits("sca-lockfile-extra-index-url-dependency-confusion", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_004_pip_extra_index_url_env_var_flags() -> None:
    """`PIP_EXTRA_INDEX_URL=https://pypi.org/simple/` → flagged."""
    src = "PIP_EXTRA_INDEX_URL=https://pypi.org/simple/ uv sync\n"
    assert _hits("sca-lockfile-extra-index-url-dependency-confusion", src)


def test_004_pip_conf_extra_index_url_flags() -> None:
    """pip.conf `extra-index-url = …` → flagged."""
    src = (
        "[global]\n"
        "extra-index-url = https://pypi.org/simple/\n"
    )
    assert _hits("sca-lockfile-extra-index-url-dependency-confusion", src)


def test_004_single_index_url_silent() -> None:
    """Plain `index-url = …` without extra-index → silent."""
    src = (
        "[global]\n"
        "index-url = https://pypi.corp.example/simple/\n"
    )
    assert not _hits("sca-lockfile-extra-index-url-dependency-confusion", src)


# ---------- SCA-LB-005 : cargo install --git no --rev no --locked -------


def test_005_cargo_install_git_no_rev_flags() -> None:
    """`cargo install --git https://github.com/x/y` → HIGH hit."""
    src = "cargo install --git https://github.com/some-org/some-tool\n"
    hits = _hits("sca-lockfile-cargo-install-git-no-rev-no-locked", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_005_cargo_install_git_branch_main_flags() -> None:
    """`cargo install --git … --branch main` → flagged."""
    src = (
        "RUN cargo install --git https://github.com/contrib/cargo-helper "
        "--branch main\n"
    )
    assert _hits("sca-lockfile-cargo-install-git-no-rev-no-locked", src)


def test_005_cargo_install_git_locked_safe() -> None:
    """`cargo install --git … --locked` → no hit (safe form)."""
    src = (
        "cargo install --git https://github.com/some-org/some-tool "
        "--locked\n"
    )
    assert not _hits("sca-lockfile-cargo-install-git-no-rev-no-locked", src)


def test_005_cargo_install_git_with_rev_safe() -> None:
    """`cargo install --git … --rev <40-hex>` → no hit (rev pinned)."""
    src = (
        "cargo install --git https://github.com/x/y "
        "--rev abc1234def5678901234567890abcdef12345678\n"
    )
    assert not _hits("sca-lockfile-cargo-install-git-no-rev-no-locked", src)


# ---------- SCA-LB-006 : replace / overrides → local path ----------------


def test_006_go_replace_relative_path_flags() -> None:
    """`replace x => ../local-fork` in go.mod → HIGH hit."""
    src = "replace golang.org/x/crypto => ../my-local-crypto-fork\n"
    hits = _hits("sca-lockfile-replace-override-local-path", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_006_go_replace_fork_v000_flags() -> None:
    """`replace x v1.2.3 => github.com/attacker/pq v0.0.1` → flagged."""
    src = "replace github.com/lib/pq v1.10.7 => github.com/attacker/pq v0.0.0\n"
    assert _hits("sca-lockfile-replace-override-local-path", src)


def test_006_npm_overrides_file_protocol_flags() -> None:
    """`"overrides": { "lodash": "file:./vendor/…" }` → flagged."""
    src = (
        '{\n'
        '  "overrides": {\n'
        '    "lodash": "file:./vendor/lodash-patched"\n'
        '  }\n'
        '}\n'
    )
    assert _hits("sca-lockfile-replace-override-local-path", src)


def test_006_cargo_patch_crates_io_path_flags() -> None:
    """`[patch.crates-io] serde = { path = "../local-serde-fork" }` → flagged."""
    src = (
        "[patch.crates-io]\n"
        'serde = { path = "../local-serde-fork" }\n'
    )
    assert _hits("sca-lockfile-replace-override-local-path", src)


def test_006_normal_require_silent() -> None:
    """Normal `require` directive with registry version → no hit."""
    src = (
        "require (\n"
        "    github.com/stretchr/testify v1.8.4\n"
        "    golang.org/x/crypto v0.17.0\n"
        ")\n"
    )
    assert not _hits("sca-lockfile-replace-override-local-path", src)


# ---------- SCA-LB-007 : wildcard checksum-bypass envs / exclusions -----


def test_007_goprivate_wildcard_flags() -> None:
    """`export GOPRIVATE=*` → HIGH hit."""
    src = "export GOPRIVATE=*\n"
    hits = _hits("sca-lockfile-wildcard-checksum-bypass-env", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_007_gonosumcheck_wildcard_flags() -> None:
    """`GONOSUMCHECK=*` (env or shell) → flagged."""
    src = 'ENV GONOSUMCHECK="*"\n'
    assert _hits("sca-lockfile-wildcard-checksum-bypass-env", src)


def test_007_yarn_npm_preapproved_wildcard_block_flags() -> None:
    """YAML block `npmPreapprovedPackages:\\n  - "*"` → flagged."""
    src = (
        "npmPreapprovedPackages:\n"
        '  - "*"\n'
    )
    assert _hits("sca-lockfile-wildcard-checksum-bypass-env", src)


def test_007_pnpm_minimum_release_age_inline_flags() -> None:
    """Inline `minimumReleaseAgeExclude: ["*"]` → flagged."""
    src = 'minimumReleaseAgeExclude: ["*"]\n'
    assert _hits("sca-lockfile-wildcard-checksum-bypass-env", src)


def test_007_goprivate_narrow_prefix_silent() -> None:
    """`GOPRIVATE=github.com/myorg/*` (narrow prefix) → no hit."""
    src = "export GOPRIVATE=github.com/myorg/*\n"
    assert not _hits("sca-lockfile-wildcard-checksum-bypass-env", src)


# ---------- SCA-LB-008 : GOPROXY=...,direct silent VCS fallback ---------


def test_008_goproxy_direct_terminal_flags() -> None:
    """`GOPROXY=https://proxy.golang.org,direct` → MEDIUM hit."""
    src = 'export GOPROXY="https://proxy.golang.org,direct"\n'
    hits = _hits("sca-lockfile-goproxy-direct-fallback", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_008_goproxy_dockerfile_direct_flags() -> None:
    """`ENV GOPROXY=https://proxy.corp.example,direct` → flagged."""
    src = "ENV GOPROXY=https://proxy.corp.example,direct\n"
    assert _hits("sca-lockfile-goproxy-direct-fallback", src)


def test_008_goproxy_off_terminal_silent() -> None:
    """`GOPROXY=https://proxy.golang.org,off` (safe form) → no hit."""
    src = 'export GOPROXY="https://proxy.golang.org,off"\n'
    assert not _hits("sca-lockfile-goproxy-direct-fallback", src)


def test_008_goproxy_single_proxy_silent() -> None:
    """`GOPROXY=https://proxy.golang.org` alone → no hit."""
    src = "export GOPROXY=https://proxy.golang.org\n"
    assert not _hits("sca-lockfile-goproxy-direct-fallback", src)


# ---------- Integration sanity -------------------------------------------


def test_scan_text_returns_findings_list() -> None:
    """scan_text returns a list (mutable) — same as sibling modules."""
    out = slp.scan_text("nothing to see here")
    assert isinstance(out, list)


def test_multiple_rules_co_fire_on_combo_src() -> None:
    """Combined source triggers multiple rules independently."""
    src = (
        # SCA-LB-001 hit
        "registry=http://internal-mirror.corp.example/\n"
        # SCA-LB-002 hit
        '    "integrity": "sha512-fake"\n'
        # SCA-LB-008 hit
        'export GOPROXY="https://proxy.golang.org,direct"\n'
    )
    findings = slp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "sca-lockfile-plain-http-registry" in rule_ids
    assert "sca-lockfile-missing-or-fake-integrity" in rule_ids
    assert "sca-lockfile-goproxy-direct-fallback" in rule_ids


def test_no_findings_on_benign_text() -> None:
    """Benign English prose → 0 findings."""
    src = (
        "This module documents lockfile-bypass detection patterns. It\n"
        "does not contain any live config or hash. The author writes\n"
        "about supply-chain security in prose only, not in config form.\n"
    )
    assert slp.scan_text(src) == []


def test_dedup_prevents_double_emission() -> None:
    """Same line / column / rule_id is only emitted once."""
    src = "registry=http://mirror.corp.example/\n"
    findings = slp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))
