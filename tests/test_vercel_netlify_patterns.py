"""Tests for scripts/lib/vercel_netlify_patterns.py.

Pattern-coverage tests for the Wave-35 distill-round-21 angle
vercel-netlify-edge catalogue (12 edge-function security anti-patterns
covering Vercel / Netlify / Deno Deploy / Fly.io). Each rule has exactly
two tests: one positive (must fire) and one negative (must not fire on
the safe / carve-out input).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import vercel_netlify_patterns as vnp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62, secret  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 12 documented rule IDs."""
    assert isinstance(vnp.RULES, tuple)
    rule_ids = {r.id for r in vnp.RULES}
    expected = {
        "vne-vercel-json-env-secret-literal",
        "vne-netlify-toml-env-secret-literal",
        "vne-fly-toml-env-secret-literal",
        "vne-edge-function-no-auth-header-check",
        "vne-cors-wildcard-on-mutation-route",
        "vne-netlify-identity-jwt-not-verified",
        "vne-deno-deploy-dynamic-import-url",
        "vne-vercel-oidc-token-logged",
        "vne-edge-runtime-secret-in-response-body",
        "vne-netlify-function-ssrf-url-param",
        "vne-fly-machine-api-token-literal",
        "vne-vercel-bypass-protection-secret-weak",
    }
    assert expected == rule_ids
    assert len(vnp.RULES) == 12


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in vnp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = vnp.Finding(
        rule_id="vne-test",
        line=3,
        column=5,
        matched_text="SOMETOKEN",
        severity="HIGH",
        description="test",
        owasp_asi="ASI-02",
    )
    assert f.rule_id == "vne-test"
    assert f.line == 3
    assert f.column == 5
    assert f.matched_text == "SOMETOKEN"
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert vnp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Multiple findings must be returned in (line, col, rule_id) order."""
    src = (
        'VERCEL_AUTOMATION_BYPASS_SECRET = "tooshort"\n'
        'fm2_aaaabbbbccccddddeeeeffffgggghhhhiiiijjjjkkkk\n'
    )
    results = vnp.scan_text(src)
    assert results == sorted(results, key=lambda f: (f.line, f.column, f.rule_id))


# ---------- E1 : vne-vercel-json-env-secret-literal ----------------------


def test_e1_vercel_json_env_secret_positive() -> None:
    """vercel.json env block with hardcoded SECRET value must fire."""
    src = '''
{
  "env": {
    "DATABASE_SECRET": "s3cr3t-live-value-abc123xyz"
  }
}
'''
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-vercel-json-env-secret-literal" in ids


def test_e1_vercel_json_env_secret_negative_placeholder() -> None:
    """vercel.json env block with @vercel reference must NOT fire."""
    src = '''
{
  "env": {
    "DATABASE_SECRET": "@my-database-secret"
  }
}
'''
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-vercel-json-env-secret-literal" not in ids


# ---------- E2 : vne-netlify-toml-env-secret-literal ---------------------


def test_e2_netlify_toml_env_secret_positive() -> None:
    """netlify.toml environment block with hardcoded TOKEN must fire."""
    src = (
        '[build.environment]\n'
        f'  API_TOKEN = "{secret("live" + "-tok-", "netlify-e2-api-tok", 16)}"\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-netlify-toml-env-secret-literal" in ids


def test_e2_netlify_toml_env_secret_negative_nonmatching_key() -> None:
    """netlify.toml env var with a non-secret name must NOT fire."""
    src = (
        '[build.environment]\n'
        '  NODE_VERSION = "18"\n'
        '  SITE_URL = "https://example.com"\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-netlify-toml-env-secret-literal" not in ids


# ---------- E3 : vne-fly-toml-env-secret-literal -------------------------


def test_e3_fly_toml_env_secret_positive() -> None:
    """fly.toml [env] section with hardcoded PASSWORD must fire."""
    src = (
        '[env]\n'
        '  DB_PASSWORD = "MyS3cr3tPwd!@#abc12345"\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-fly-toml-env-secret-literal" in ids


def test_e3_fly_toml_env_secret_negative_numeric_value() -> None:
    """fly.toml env var with a numeric value must NOT fire."""
    src = (
        '[env]\n'
        '  PORT = 8080\n'
        '  MAX_CONNECTIONS = 100\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-fly-toml-env-secret-literal" not in ids


# ---------- E4 : vne-edge-function-no-auth-header-check ------------------


def test_e4_edge_no_auth_positive() -> None:
    """Edge handler export without any auth header check must fire."""
    src = (
        'export default async function handler(req, res) {\n'
        '  const data = await fetchData();\n'
        '  res.json(data);\n'
        '}\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-edge-function-no-auth-header-check" in ids


def test_e4_edge_no_auth_negative_has_auth() -> None:
    """Edge handler that checks Authorization header must NOT fire."""
    src = (
        'export default async function handler(req, res) {\n'
        '  const authHeader = req.headers["authorization"];\n'
        '  if (!authHeader) return res.status(401).end();\n'
        '  res.json({ok: true});\n'
        '}\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-edge-function-no-auth-header-check" not in ids


# ---------- E5 : vne-cors-wildcard-on-mutation-route ---------------------


def test_e5_cors_wildcard_mutation_positive() -> None:
    """CORS wildcard with adjacent POST method check must fire."""
    src = (
        'res.setHeader("Access-Control-Allow-Origin", "*");\n'
        'if (req.method === "POST") {\n'
        '  await saveData(req.body);\n'
        '}\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-cors-wildcard-on-mutation-route" in ids


def test_e5_cors_wildcard_mutation_negative_readonly() -> None:
    """CORS wildcard with only GET method nearby must NOT fire."""
    src = (
        'res.setHeader("Access-Control-Allow-Origin", "*");\n'
        'if (req.method === "GET") {\n'
        '  return res.json(publicData);\n'
        '}\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-cors-wildcard-on-mutation-route" not in ids


# ---------- E6 : vne-netlify-identity-jwt-not-verified -------------------


def test_e6_netlify_identity_no_verify_positive() -> None:
    """Reading clientContext.user without verify() must fire."""
    src = (
        'exports.handler = async (event, context) => {\n'
        '  const user = context.clientContext.user;\n'
        '  return { statusCode: 200, body: JSON.stringify(user) };\n'
        '};\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-netlify-identity-jwt-not-verified" in ids


def test_e6_netlify_identity_no_verify_negative_with_verify() -> None:
    """Reading clientContext.user WITH verify() call must NOT fire."""
    src = (
        'exports.handler = async (event, context) => {\n'
        '  const verified = await jwtVerify(context.clientContext.user.token, key);\n'
        '  return { statusCode: 200, body: JSON.stringify(verified) };\n'
        '};\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-netlify-identity-jwt-not-verified" not in ids


# ---------- E7 : vne-deno-deploy-dynamic-import-url ----------------------


def test_e7_deno_dynamic_import_positive() -> None:
    """Dynamic import() with string concatenation must fire."""
    src = (
        'const mod = await import("https://deno.land/x/" + moduleName + "/mod.ts");\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-deno-deploy-dynamic-import-url" in ids


def test_e7_deno_dynamic_import_negative_static_string() -> None:
    """Static string import() must NOT fire."""
    src = (
        'const mod = await import("https://deno.land/x/oak/mod.ts");\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-deno-deploy-dynamic-import-url" not in ids


# ---------- E8 : vne-vercel-oidc-token-logged ----------------------------


def test_e8_oidc_token_logged_positive() -> None:
    """OIDC token source followed by console.log must fire."""
    src = (
        'const token = await getVercelOidcToken();\n'
        'console.log("token", token);\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-vercel-oidc-token-logged" in ids


def test_e8_oidc_token_logged_negative_no_log() -> None:
    """OIDC token used in fetch header without logging must NOT fire."""
    src = (
        'const token = await getVercelOidcToken();\n'
        'const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-vercel-oidc-token-logged" not in ids


# ---------- E9 : vne-edge-runtime-secret-in-response-body ----------------


def test_e9_secret_in_response_positive() -> None:
    """process.env secret fed directly into new Response() must fire."""
    src = (
        'const secret = process.env("DATABASE_SECRET");\n'
        'return new Response(secret);\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-edge-runtime-secret-in-response-body" in ids


def test_e9_secret_in_response_negative_non_secret_env() -> None:
    """process.env for a non-secret variable in a response must NOT fire."""
    src = (
        'const version = process.env("APP_VERSION");\n'
        'return new Response(version);\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-edge-runtime-secret-in-response-body" not in ids


# ---------- E10 : vne-netlify-function-ssrf-url-param --------------------


def test_e10_ssrf_url_param_positive() -> None:
    """fetch() with event.queryStringParameters as URL must fire."""
    src = (
        'exports.handler = async (event) => {\n'
        '  const data = await fetch(event.queryStringParameters.url);\n'
        '  return { statusCode: 200, body: await data.text() };\n'
        '};\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-netlify-function-ssrf-url-param" in ids


def test_e10_ssrf_url_param_negative_host_allowlist() -> None:
    """fetch with event params but ALLOWED_HOSTS check must NOT fire."""
    src = (
        'exports.handler = async (event) => {\n'
        '  const url = event.queryStringParameters.url;\n'
        '  const parsed = new URL(url);\n'
        '  if (!ALLOWED_HOSTS.includes(parsed.hostname)) throw new Error("Forbidden");\n'
        '  const data = await fetch(url);\n'
        '  return { statusCode: 200, body: await data.text() };\n'
        '};\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-netlify-function-ssrf-url-param" not in ids


# ---------- E11 : vne-fly-machine-api-token-literal ----------------------


def test_e11_fly_token_positive_fm2_prefix() -> None:
    """fm2_ prefixed token literal in source must fire."""
    src = (
        f'const flyToken = "{secret("fm2" + "_", "fly-e11-tok", 44)}";\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-fly-machine-api-token-literal" in ids


def test_e11_fly_token_negative_env_reference() -> None:
    """Fly token read from environment variable must NOT fire."""
    src = (
        'const flyToken = process.env.FLY_API_TOKEN;\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-fly-machine-api-token-literal" not in ids


# ---------- E12 : vne-vercel-bypass-protection-secret-weak ---------------


def test_e12_bypass_secret_weak_positive() -> None:
    """Short bypass secret (< 32 chars) must fire."""
    src = (
        'VERCEL_AUTOMATION_BYPASS_SECRET = "tooshort"\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-vercel-bypass-protection-secret-weak" in ids


def test_e12_bypass_secret_weak_negative_long_random() -> None:
    """Bypass secret >= 32 chars with no weak keyword must NOT fire."""
    # Value is exactly 32 alphanumeric chars — exceeds the {1,31} threshold.
    src = (
        f'VERCEL_AUTOMATION_BYPASS_SECRET = "{b62("vercel-bypass-neg", 32)}"\n'
    )
    ids = {f.rule_id for f in vnp.scan_text(src)}
    assert "vne-vercel-bypass-protection-secret-weak" not in ids
