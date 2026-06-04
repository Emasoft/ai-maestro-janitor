"""Tests for scripts/lib/cloudflare_workers_patterns.py.

Pattern-coverage tests for the Wave-35 distill-round-21 catalogue
(10 Cloudflare Workers + D1 / R2 / KV / Durable Objects anti-patterns).
Each rule has at least two tests: one positive (canary fires) and one
negative (carve-out / benign case does NOT fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import cloudflare_workers_patterns as cfw  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import secret  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs with cfw- prefix."""
    assert isinstance(cfw.RULES, tuple)
    rule_ids = {r.id for r in cfw.RULES}
    expected = {
        "cfw-wildcard-route-hijack",
        "cfw-r2-bucket-public-read",
        "cfw-kv-namespace-id-committed",
        "cfw-d1-exec-injection",
        "cfw-durable-object-alarm-no-auth",
        "cfw-vars-plaintext-secret",
        "cfw-subrequest-loop-exhaustion",
        "cfw-ai-binding-response-leak",
        "cfw-cron-trigger-with-var-secret",
        "cfw-kv-get-no-cache-ttl",
    }
    assert expected == rule_ids
    assert len(cfw.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in cfw.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = cfw.Finding(
        rule_id="cfw-test", line=1, column=2, matched_text="x",
        severity="HIGH", description="desc", owasp_asi="ASI-02",
    )
    assert f.rule_id == "cfw-test"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "x"
    assert f.severity == "HIGH"
    assert f.description == "desc"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert cfw.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Findings are sorted by (line, column, rule_id)."""
    # Trigger two rules in known order: KV id on line 1, cron on line 5.
    src = (
        '[[kv_namespaces]]\nid = "abcdef1234567890abcdef1234567890"\n'
        "\n\n"
        "[triggers]\ncrons = [\"0 * * * *\"]\n"
    )
    findings = cfw.scan_text(src)
    lines = [f.line for f in findings]
    assert lines == sorted(lines), "findings must be sorted by line"


# ---------- P1: cfw-wildcard-route-hijack --------------------------------


def test_wildcard_route_fires_on_star_slash_star() -> None:
    """routes = ['*/*'] must trigger cfw-wildcard-route-hijack."""
    src = 'routes = ["*/*"]\n'
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-wildcard-route-hijack" in ids


def test_wildcard_route_negative_specific_path() -> None:
    """routes = ['/api/widget'] must NOT trigger cfw-wildcard-route-hijack."""
    src = 'routes = ["/api/widget"]\n'
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-wildcard-route-hijack" not in ids


# ---------- P2: cfw-r2-bucket-public-read --------------------------------


def test_r2_bucket_fires_when_get_also_present() -> None:
    """[[r2_buckets]] + env.BUCKET.get() fires cfw-r2-bucket-public-read."""
    src = (
        "[[r2_buckets]]\n"
        'binding = "ASSETS"\n'
        "\n"
        "// worker.ts\n"
        "const obj = await env.ASSETS.get(request.url);\n"
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-r2-bucket-public-read" in ids


def test_r2_bucket_negative_no_get_call() -> None:
    """[[r2_buckets]] alone without any .get() must NOT fire."""
    src = (
        "[[r2_buckets]]\n"
        'binding = "ASSETS"\n'
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-r2-bucket-public-read" not in ids


# ---------- P3: cfw-kv-namespace-id-committed ----------------------------


def test_kv_ns_id_fires_on_32hex_id() -> None:
    """[[kv_namespaces]] with id = '<32 hex>' fires cfw-kv-namespace-id-committed."""
    src = (
        "[[kv_namespaces]]\n"
        'binding = "SESSION"\n'
        'id = "deadbeef01234567deadbeef01234567"\n'
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-kv-namespace-id-committed" in ids


def test_kv_ns_id_negative_placeholder_value() -> None:
    """[[kv_namespaces]] with id = 'YOUR_KV_ID' (non-hex) must NOT fire."""
    src = (
        "[[kv_namespaces]]\n"
        'binding = "SESSION"\n'
        'id = "YOUR_KV_ID_HERE"\n'
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-kv-namespace-id-committed" not in ids


def test_account_id_committed_fires() -> None:
    """account_id = '<32 hex>' at root fires cfw-kv-namespace-id-committed."""
    src = 'account_id = "abcdef1234567890abcdef1234567890"\n'
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-kv-namespace-id-committed" in ids


def test_account_id_negative_non_hex() -> None:
    """account_id = 'not-a-real-id' must NOT fire cfw-kv-namespace-id-committed."""
    src = 'account_id = "not-a-real-id"\n'
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-kv-namespace-id-committed" not in ids


# ---------- P4: cfw-d1-exec-injection ------------------------------------


def test_d1_exec_variable_fires() -> None:
    """db.exec(sqlVar) with a variable argument fires cfw-d1-exec-injection."""
    src = "const result = await db.exec(sqlQuery);\n"
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-d1-exec-injection" in ids


def test_d1_exec_negative_literal_string() -> None:
    """db.exec('SELECT 1') with a literal string must NOT fire."""
    src = "await db.exec('SELECT 1');\n"
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-d1-exec-injection" not in ids


def test_d1_prepare_template_fires() -> None:
    """db.prepare(`SELECT * FROM t WHERE id = ${id}`) fires cfw-d1-exec-injection."""
    src = "const stmt = db.prepare(`SELECT * FROM users WHERE id = ${userId}`);\n"
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-d1-exec-injection" in ids


def test_d1_prepare_negative_no_interpolation() -> None:
    """db.prepare('SELECT * FROM t WHERE id = ?') must NOT fire."""
    src = "const stmt = db.prepare('SELECT * FROM users WHERE id = ?');\n"
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-d1-exec-injection" not in ids


# ---------- P5: cfw-durable-object-alarm-no-auth -------------------------


def test_do_alarm_privileged_fires() -> None:
    """async alarm() calling delete() fires cfw-durable-object-alarm-no-auth."""
    src = (
        "class MyDO {\n"
        "  async alarm() {\n"
        "    await this.storage.delete('session');\n"
        "  }\n"
        "}\n"
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-durable-object-alarm-no-auth" in ids


def test_do_alarm_negative_benign_alarm() -> None:
    """async alarm() that only reads data must NOT fire."""
    src = (
        "class MyDO {\n"
        "  async alarm() {\n"
        "    const val = await this.storage.get('counter');\n"
        "    console.log(val);\n"
        "  }\n"
        "}\n"
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-durable-object-alarm-no-auth" not in ids


# ---------- P6: cfw-vars-plaintext-secret --------------------------------


def test_vars_plaintext_secret_fires_on_token() -> None:
    """[vars] with API_TOKEN key fires cfw-vars-plaintext-secret."""
    src = (
        "[vars]\n"
        f'API_TOKEN = "{secret("sk-" + "live-", "cfw-vars-sk1", 16)}"\n'
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-vars-plaintext-secret" in ids


def test_vars_plaintext_secret_negative_non_secret_key() -> None:
    """[vars] with UPSTREAM_URL key must NOT fire cfw-vars-plaintext-secret."""
    src = (
        "[vars]\n"
        'UPSTREAM_URL = "https://registry.npmjs.org"\n'
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-vars-plaintext-secret" not in ids


def test_vars_plaintext_secret_negative_short_value() -> None:
    """[vars] with a SECRET_ key but a short value (<8 chars) must NOT fire."""
    src = (
        "[vars]\n"
        'SECRET_X = "abc"\n'
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-vars-plaintext-secret" not in ids


# ---------- P7: cfw-subrequest-loop-exhaustion ---------------------------


def test_subreq_for_loop_fires() -> None:
    """for loop with await fetch() fires cfw-subrequest-loop-exhaustion."""
    src = (
        "for (const url of urlList) {\n"
        "  const resp = await fetch(url);\n"
        "}\n"
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-subrequest-loop-exhaustion" in ids


def test_subreq_promise_all_fires() -> None:
    """Promise.all with fetch() fires cfw-subrequest-loop-exhaustion."""
    src = "const results = await Promise.all(urls.map(u => fetch(u)));\n"
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-subrequest-loop-exhaustion" in ids


def test_subreq_negative_single_fetch() -> None:
    """A single fetch() outside any loop must NOT fire."""
    src = "const resp = await fetch('https://example.com/api');\n"
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-subrequest-loop-exhaustion" not in ids


# ---------- P8: cfw-ai-binding-response-leak -----------------------------


def test_ai_run_stringify_fires() -> None:
    """env.AI.run() result forwarded to Response(JSON.stringify(result)) fires."""
    src = (
        "const result = await env.AI.run('@cf/meta/llama-2-7b-chat-int8', inputs);\n"
        "return new Response(JSON.stringify(result), { headers: ct });\n"
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-ai-binding-response-leak" in ids


def test_ai_run_stringify_negative_field_filtered() -> None:
    """env.AI.run() result with field filtering must NOT fire the stringify rule."""
    src = (
        "const result = await env.AI.run('@cf/meta/llama-2-7b-chat-int8', inputs);\n"
        "return new Response(JSON.stringify({ text: result.response }), { headers: ct });\n"
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    # result.response — not bare variable name — should not match
    assert "cfw-ai-binding-response-leak" not in ids


def test_env_log_stringify_fires() -> None:
    """console.log(JSON.stringify(env)) fires cfw-ai-binding-response-leak."""
    src = "console.log(JSON.stringify(env));\n"
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-ai-binding-response-leak" in ids


def test_env_log_stringify_negative_other_obj() -> None:
    """console.log(JSON.stringify(request)) must NOT fire."""
    src = "console.log(JSON.stringify(request));\n"
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-ai-binding-response-leak" not in ids


# ---------- P9: cfw-cron-trigger-with-var-secret -------------------------


def test_cron_trigger_fires() -> None:
    """[triggers] with crons array fires cfw-cron-trigger-with-var-secret."""
    src = (
        "[triggers]\n"
        'crons = ["0 * * * *"]\n'
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-cron-trigger-with-var-secret" in ids


def test_cron_trigger_negative_no_crons_key() -> None:
    """[triggers] section without crons key must NOT fire."""
    src = (
        "[triggers]\n"
        'schedule = "0 * * * *"\n'
    )
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-cron-trigger-with-var-secret" not in ids


# ---------- P10: cfw-kv-get-no-cache-ttl ---------------------------------


def test_kv_get_no_ttl_fires() -> None:
    """env.KV.get(key) without cacheTtl fires cfw-kv-get-no-cache-ttl."""
    src = "const token = await env.SESSION_KV.get(sessionId);\n"
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-kv-get-no-cache-ttl" in ids


def test_kv_get_negative_with_cache_ttl() -> None:
    """env.KV.get(key, { cacheTtl: 0 }) must NOT fire cfw-kv-get-no-cache-ttl."""
    src = "const token = await env.SESSION_KV.get(sessionId, { cacheTtl: 0 });\n"
    findings = cfw.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "cfw-kv-get-no-cache-ttl" not in ids
