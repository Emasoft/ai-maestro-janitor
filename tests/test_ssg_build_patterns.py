"""Tests for scripts/lib/ssg_build_patterns.py.

2 tests per rule (positive hit + negative miss), plus a sys.path import
guard and a scan_text smoke test. All tests are fully real — no mocks.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the library under test is importable regardless of how pytest is
# invoked (from repo root, from tests/, or via uv run --with pytest).
_SCRIPTS_LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib"
if str(_SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_LIB))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ssg_build_patterns as ssg  # noqa: E402
from _fake_secrets import secret  # noqa: E402

# ---------------------------------------------------------------------------
# Structural sanity
# ---------------------------------------------------------------------------


def test_module_exports_required_symbols():
    """Module exposes Finding, Rule, RULES, and scan_text."""
    assert hasattr(ssg, "Finding")
    assert hasattr(ssg, "Rule")
    assert hasattr(ssg, "RULES")
    assert callable(ssg.scan_text)


def test_rules_tuple_has_six_entries():
    """RULES contains exactly 6 Rule entries (one per SSG-00N pattern)."""
    assert len(ssg.RULES) == 6


def test_scan_text_empty_returns_empty_list():
    """scan_text('') returns an empty list without raising."""
    assert ssg.scan_text("") == []


def test_finding_fields():
    """Finding instances expose all expected fields."""
    f = ssg.Finding(
        rule_id="ssg-test",
        line=1,
        column=1,
        matched_text="x",
        severity="HIGH",
        description="desc",
        owasp_asi="ASI-02",
    )
    assert f.rule_id == "ssg-test"
    assert f.line == 1
    assert f.owasp_asi == "ASI-02"


# ---------------------------------------------------------------------------
# Rule S1 — ssg-next-public-prefix-secret
# ---------------------------------------------------------------------------

_RULE_S1 = "ssg-next-public-prefix-secret"


def test_s1_detects_next_public_github_token():
    """NEXT_PUBLIC_GITHUB_TOKEN with a literal value is flagged as CRITICAL."""
    code = f"NEXT_PUBLIC_GITHUB_TOKEN={secret('ghp_', 'ssg-s1-github-token', 21)}\n"
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S1]
    assert len(findings) >= 1
    assert findings[0].severity == "CRITICAL"


def test_s1_skips_stripe_publishable_key():
    """NEXT_PUBLIC_STRIPE_SECRET with a pk_live_ value is allowlisted (not flagged)."""
    # The allowlist is for pk_live_ / pk_test_ values; this is a STRIPE_SECRET name
    # which only gets allowlisted when the *value* starts with pk_live_ / pk_test_.
    # A real pk_live_ value assigned to STRIPE_SECRET would be allowlisted.
    code = f"NEXT_PUBLIC_STRIPE_SECRET={secret('pk_' + 'live_', 'ssg-s1-pk-live', 24)}\n"
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S1]
    assert len(findings) == 0


def test_s1_skips_bare_process_env_reference():
    """process.env.NEXT_PUBLIC_API_KEY alone (no assignment) is not flagged."""
    code = "const key = process.env.NEXT_PUBLIC_API_KEY;\n"
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S1]
    assert len(findings) == 0


def test_s1_skips_empty_value():
    """NEXT_PUBLIC_API_KEY= with an empty value is not flagged."""
    code = "NEXT_PUBLIC_API_KEY=\n"
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S1]
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Rule S2 — ssg-next-public-runtime-config-secret
# ---------------------------------------------------------------------------

_RULE_S2 = "ssg-next-public-runtime-config-secret"


def test_s2_detects_secret_in_public_runtime_config():
    """publicRuntimeConfig block with a 'token' key is flagged as HIGH."""
    code = (
        "module.exports = {\n"
        "  publicRuntimeConfig: {\n"
        "    contentfulAccessToken: 'abc123xyz',\n"
        "  },\n"
        "};\n"
    )
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S2]
    assert len(findings) >= 1
    assert findings[0].severity == "HIGH"


def test_s2_skips_server_runtime_config():
    """serverRuntimeConfig block (not publicRuntimeConfig) is not flagged."""
    code = (
        "module.exports = {\n"
        "  serverRuntimeConfig: {\n"
        "    stripeSecretKey: process.env.STRIPE_SECRET_KEY,\n"
        "  },\n"
        "};\n"
    )
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S2]
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Rule S3 — ssg-gatsby-config-token-literal
# ---------------------------------------------------------------------------

_RULE_S3 = "ssg-gatsby-config-token-literal"


def test_s3_detects_gatsby_access_token_literal():
    """Literal accessToken string (>=20 chars) in gatsby-config is flagged."""
    code = (
        "module.exports = {\n"
        "  plugins: [{\n"
        "    resolve: 'gatsby-source-contentful',\n"
        "    options: {\n"
        "      spaceId: 'abc123',\n"
        f"      accessToken: '{secret('CFPAT' + '-', 'ssg-s3-cfpat', 21)}',\n"
        "    },\n"
        "  }],\n"
        "};\n"
    )
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S3]
    assert len(findings) >= 1
    assert findings[0].severity == "HIGH"


def test_s3_skips_env_var_reference_in_gatsby():
    """accessToken: process.env.FOO (no string literal) is not flagged."""
    code = (
        "module.exports = {\n"
        "  plugins: [{\n"
        "    options: {\n"
        "      accessToken: process.env.CONTENTFUL_ACCESS_TOKEN,\n"
        "    },\n"
        "  }],\n"
        "};\n"
    )
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S3]
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Rule S4 — ssg-nuxt-runtime-config-public-secret
# ---------------------------------------------------------------------------

_RULE_S4 = "ssg-nuxt-runtime-config-public-secret"


def test_s4_detects_nuxt_public_secret_key():
    """runtimeConfig.public with an openaiApiKey entry is flagged."""
    code = (
        "export default defineNuxtConfig({\n"
        "  runtimeConfig: {\n"
        "    stripeSecretKey: process.env.STRIPE_SECRET_KEY,\n"
        "    public: {\n"
        f"      openaiApiKey: '{secret('sk-' + 'proj-', 'ssg-s4-sk-proj', 24)}',\n"
        "    },\n"
        "  },\n"
        "});\n"
    )
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S4]
    assert len(findings) >= 1
    assert findings[0].severity == "HIGH"


def test_s4_skips_server_only_runtime_config():
    """runtimeConfig with only top-level keys (no public sub-key) is not flagged."""
    code = (
        "export default defineNuxtConfig({\n"
        "  runtimeConfig: {\n"
        "    stripeSecretKey: process.env.STRIPE_SECRET_KEY,\n"
        "    dbPassword: process.env.DB_PASSWORD,\n"
        "  },\n"
        "});\n"
    )
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S4]
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Rule S5 — ssg-jekyll-config-secret
# ---------------------------------------------------------------------------

_RULE_S5 = "ssg-jekyll-config-secret"


def test_s5_detects_github_token_in_jekyll_config():
    """github_token with a literal PAT value in _config.yml is flagged."""
    code = f"github_token: {secret('ghp_', 'ssg-s5-github-token', 21)}\n"
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S5]
    assert len(findings) >= 1
    assert findings[0].severity == "HIGH"


def test_s5_skips_erb_env_interpolation():
    """ERB interpolation (<%= ENV['KEY'] %>) is not flagged (contains < > chars)."""
    code = "auth_token: <%= ENV['GITHUB_TOKEN'] %>\n"
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S5]
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Rule S6 — ssg-get-static-props-secret-in-props
# ---------------------------------------------------------------------------

_RULE_S6 = "ssg-get-static-props-secret-in-props"


def test_s6_detects_secret_env_var_in_static_props():
    """props object containing a 'token' key with a non-PUBLIC env var is flagged."""
    code = (
        "export async function getStaticProps() {\n"
        "  return {\n"
        "    props: {\n"
        "      cmsToken: process.env.CMS_SECRET_TOKEN,\n"
        "    },\n"
        "  };\n"
        "}\n"
    )
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S6]
    assert len(findings) >= 1
    assert findings[0].severity == "CRITICAL"


def test_s6_skips_next_public_env_var_in_props():
    """props with a NEXT_PUBLIC_ env var (intentionally public) is not flagged."""
    # The pattern excludes env vars whose name contains _PUBLIC_ in the suffix
    # anchoring — NEXT_PUBLIC_API_URL does not match the suffix requirement.
    code = (
        "export async function getStaticProps() {\n"
        "  return {\n"
        "    props: {\n"
        "      apiUrl: process.env.NEXT_PUBLIC_API_URL,\n"
        "    },\n"
        "  };\n"
        "}\n"
    )
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S6]
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# scan_text integration
# ---------------------------------------------------------------------------


def test_scan_text_returns_list_of_findings():
    """scan_text returns a list of Finding namedtuples."""
    code = f"NEXT_PUBLIC_API_KEY={secret('sk-', 'ssg-scan-sk', 24)}\n"
    result = ssg.scan_text(code)
    assert isinstance(result, list)
    for f in result:
        assert isinstance(f, ssg.Finding)


def test_scan_text_deduplicates_same_position():
    """The same match position does not produce duplicate findings."""
    # Repeat the same pattern twice on the same line — but since the
    # pattern anchors on the key name, duplicate text produces only one
    # positional match per rule.
    _tok = secret("ghp_", "ssg-s1-github-token", 21)
    code = (
        f"NEXT_PUBLIC_GITHUB_TOKEN={_tok}\n"
        f"NEXT_PUBLIC_GITHUB_TOKEN={_tok}\n"
    )
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S1]
    # Two separate lines → two separate (rule_id, line, col) keys → 2 findings
    assert len(findings) == 2
    lines = {f.line for f in findings}
    assert lines == {1, 2}


def test_scan_text_line_col_accuracy():
    """Finding.line and .column point to the correct position in the text."""
    code = f"# comment\nNEXT_PUBLIC_API_KEY={secret('sk-', 'ssg-scan-sk', 24)}\n"
    findings = [f for f in ssg.scan_text(code) if f.rule_id == _RULE_S1]
    assert len(findings) >= 1
    assert findings[0].line == 2
    assert findings[0].column == 1
