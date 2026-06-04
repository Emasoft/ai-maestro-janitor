"""Tests for scripts/lib/api_gateway_patterns.py.

Pattern-coverage tests for the Wave-28 distill-round-14 api-gateway
catalogue (7 API-gateway-specific anti-patterns covering Kong, Tyk,
Apigee, AWS API Gateway, KrakenD, Express Gateway / Express.js,
MCP Shield, and LiteLLM proxy). Each rule has at least two tests:
one positive (canary triggers) and one negative (safe pattern suppressed).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import api_gateway_patterns as agp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(agp.RULES, tuple)
    rule_ids = {r.id for r in agp.RULES}
    expected = {
        "agw-proxy-no-caller-auth",
        "agw-wildcard-cors",
        "agw-rate-limit-gap-auth-routes",
        "agw-security-empty-override",
        "agw-default-allow-policy",
        "agw-authorizer-ttl-no-invalidate",
        "agw-rate-limit-absent-default",
    }
    assert expected == rule_ids
    assert len(agp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid API- prefix and a known severity."""
    for rule in agp.RULES:
        assert rule.owasp_api.startswith("API"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding NamedTuple must carry the correct fields."""
    f = agp.Finding(
        rule_id="agw-test",
        line=1,
        column=5,
        matched_text="app.use(cors())",
        severity="HIGH",
        description="test",
        owasp_api="API7:2023",
    )
    assert f.rule_id == "agw-test"
    assert f.line == 1
    assert f.column == 5
    assert f.matched_text == "app.use(cors())"
    assert f.severity == "HIGH"
    assert f.owasp_api == "API7:2023"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert agp.scan_text("") == []


def test_scan_returns_list_of_finding_instances() -> None:
    """scan_text return value must be a list of Finding instances."""
    src = "app.use(cors())\n"
    results = agp.scan_text(src)
    assert isinstance(results, list)
    for f in results:
        assert isinstance(f, agp.Finding)


# ---------- AGW-001 : proxy-no-caller-auth -------------------------------


def test_agw001_proxy_no_caller_auth_triggers() -> None:
    """Catch-all proxy route with no auth dependency fires AGW-001."""
    src = (
        "@app.api_route('/{provider}/{path:path}', methods=['GET', 'POST'])\n"
        "async def forward(provider: str, path: str, request: Request):\n"
        "    real_key = get_real_api_key(provider)\n"
        "    headers['x-api-key'] = real_key\n"
    )
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-proxy-no-caller-auth" in ids


def test_agw001_proxy_with_auth_dependency_suppressed() -> None:
    """Catch-all route with Depends(get_current_user) must not fire."""
    src = (
        "@app.api_route('/{provider}/{path:path}', methods=['GET', 'POST'])\n"
        "async def forward(provider: str, path: str, request: Request,\n"
        "                  user=Depends(get_current_user)):\n"
        "    real_key = get_real_api_key(provider)\n"
        "    headers['x-api-key'] = real_key\n"
    )
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-proxy-no-caller-auth" not in ids


# ---------- AGW-002 : wildcard-cors --------------------------------------


def test_agw002_wildcard_cors_triggers() -> None:
    """app.use(cors()) with no arguments fires AGW-002."""
    src = "const app = express();\napp.use(cors());\n"
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-wildcard-cors" in ids


def test_agw002_cors_with_origin_list_suppressed() -> None:
    """app.use(cors({ origin: [...] })) must not fire AGW-002."""
    src = (
        "app.use(cors({\n"
        "  origin: ['https://app.example.com'],\n"
        "  credentials: true,\n"
        "}));\n"
    )
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-wildcard-cors" not in ids


# ---------- AGW-003 : rate-limit-gap-auth-routes -------------------------


def test_agw003_auth_route_no_limiter_triggers() -> None:
    """Auth route mounted without a rate-limiter fires AGW-003."""
    src = (
        "app.use('/api', apiLimiter);\n"
        "app.use('/auth', authRoutes);\n"
    )
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-rate-limit-gap-auth-routes" in ids


def test_agw003_auth_route_with_limiter_suppressed() -> None:
    """Auth route with an explicit authLimiter must not fire AGW-003."""
    src = (
        "const authLimiter = rateLimit({ windowMs: 60_000, limit: 10 });\n"
        "app.use('/auth', authLimiter, authRoutes);\n"
    )
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-rate-limit-gap-auth-routes" not in ids


def test_agw003_login_route_no_limiter_triggers() -> None:
    """Login route mounted without a rate-limiter fires AGW-003."""
    src = "app.use('/login', loginHandler);\n"
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-rate-limit-gap-auth-routes" in ids


def test_agw003_forgot_route_with_throttle_suppressed() -> None:
    """Forgot-password route with slowDown middleware must not fire."""
    src = "app.use('/forgot', slowDown({ windowMs: 60000, delayAfter: 5 }), forgotRoutes);\n"
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-rate-limit-gap-auth-routes" not in ids


# ---------- AGW-004 : security-empty-override ----------------------------


def test_agw004_security_empty_list_triggers() -> None:
    """security: [] in OpenAPI YAML fires AGW-004."""
    src = (
        "paths:\n"
        "  /health:\n"
        "    get:\n"
        "      security: []\n"
    )
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-security-empty-override" in ids


def test_agw004_security_with_scheme_suppressed() -> None:
    """security: [bearerAuth: []] must not fire AGW-004."""
    src = (
        "paths:\n"
        "  /items:\n"
        "    get:\n"
        "      security:\n"
        "        - bearerAuth: []\n"
    )
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-security-empty-override" not in ids


# ---------- AGW-005 : default-allow-policy -------------------------------


def test_agw005_default_action_allow_triggers() -> None:
    """default_action: ALLOW in a policy YAML fires AGW-005."""
    src = (
        'policy = {\n'
        '    "version": "1.0",\n'
        '    "default_action": "ALLOW",\n'
        '    "ingress_rules": [],\n'
        '}\n'
    )
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-default-allow-policy" in ids


def test_agw005_default_allow_true_triggers() -> None:
    """default_allow: true fires AGW-005."""
    src = "default_allow: true\n"
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-default-allow-policy" in ids


def test_agw005_default_action_deny_suppressed() -> None:
    """default_action: DENY must not fire AGW-005."""
    src = 'default_action: "DENY"\n'
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-default-allow-policy" not in ids


# ---------- AGW-006 : authorizer-ttl-no-invalidate -----------------------


def test_agw006_long_ttl_no_invalidation_triggers() -> None:
    """TokenAuthorizer with TTL=900 and no cache flush fires AGW-006."""
    src = (
        "authorizer = apigw.TokenAuthorizer(self, 'MyAuthorizer',\n"
        "    handler=authorizer_fn,\n"
        "    results_cache_ttl=Duration.seconds(900),\n"
        ")\n"
    )
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-authorizer-ttl-no-invalidate" in ids


def test_agw006_long_ttl_with_flush_suppressed() -> None:
    """TokenAuthorizer with TTL=900 but flush_stage_authorizers_cache present must not fire."""
    src = (
        "authorizer = apigw.TokenAuthorizer(self, 'MyAuthorizer',\n"
        "    handler=authorizer_fn,\n"
        "    results_cache_ttl=Duration.seconds(900),\n"
        ")\n"
        "# On revoke:\n"
        "gw.flush_stage_authorizers_cache(restApiId=REST_API_ID, stageName='prod')\n"
    )
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-authorizer-ttl-no-invalidate" not in ids


def test_agw006_short_ttl_suppressed() -> None:
    """TTL of 0 seconds (single digit) must not fire AGW-006."""
    src = "results_cache_ttl=Duration.seconds(0),\n"
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-authorizer-ttl-no-invalidate" not in ids


# ---------- AGW-007 : rate-limit-absent-default --------------------------


def test_agw007_invocation_block_no_rate_limit_triggers() -> None:
    """invocation: block with keys but no rate_limit fires AGW-007."""
    src = (
        "invocation:\n"
        "  block_shell_injection: true\n"
        "  block_path_traversal: true\n"
        "  block_credential_patterns: true\n"
        "\n"
        "policies:\n"
        "  default:\n"
        "    action: ask\n"
    )
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-rate-limit-absent-default" in ids


def test_agw007_invocation_block_with_rate_limit_suppressed() -> None:
    """invocation: block that includes rate_limit must not fire AGW-007."""
    src = (
        "invocation:\n"
        "  block_shell_injection: true\n"
        "  block_path_traversal: true\n"
        "  rate_limit:\n"
        "    max_calls_per_minute: 10\n"
        "    max_calls_per_tool_per_minute: 5\n"
    )
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-rate-limit-absent-default" not in ids


# ---------- Deduplication and multi-match --------------------------------


def test_deduplication_same_match_emitted_once() -> None:
    """Identical matches at the same offset must not produce duplicate findings."""
    src = "app.use(cors());\n"
    results = agp.scan_text(src)
    cors_findings = [f for f in results if f.rule_id == "agw-wildcard-cors"]
    assert len(cors_findings) == 1


def test_multiple_rules_can_fire_from_same_source() -> None:
    """A snippet triggering multiple rules produces findings for each."""
    src = (
        # AGW-002: wildcard CORS
        "app.use(cors());\n"
        # AGW-003: auth route without limiter
        "app.use('/auth', authRoutes);\n"
    )
    ids = {f.rule_id for f in agp.scan_text(src)}
    assert "agw-wildcard-cors" in ids
    assert "agw-rate-limit-gap-auth-routes" in ids


def test_finding_line_numbers_are_positive() -> None:
    """All findings must report line >= 1 and column >= 1."""
    src = (
        "app.use(cors());\n"
        "app.use('/login', loginRoutes);\n"
        "default_action: ALLOW\n"
    )
    for f in agp.scan_text(src):
        assert f.line >= 1, f"line={f.line} for {f.rule_id}"
        assert f.column >= 1, f"col={f.column} for {f.rule_id}"
