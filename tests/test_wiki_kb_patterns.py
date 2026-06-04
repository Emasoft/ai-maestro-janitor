"""Tests for scripts/lib/wiki_kb_patterns.py.

Pattern-coverage tests for the Wave-28 distill-round-14 wiki/KB API
catalogue (6 rules covering Notion, Confluence, MediaWiki, Bookstack,
Notion search BOLA, and Wiki.js). Each rule has at least two tests:
one positive (canary triggers) and one negative (carve-out / benign
variant does NOT trigger).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import wiki_kb_patterns as wkb  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62, secret  # noqa: E402

# ---------- Synthetic secret-shaped fixtures -----------------------------
# Prefixes are split at runtime so no contiguous, real-format secret
# literal exists at rest in this file. The detector still receives the fully-
# assembled string at runtime (byte-identical), so coverage is unchanged.
_ATATT = "ATAT" + "T"

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must expose all 6 documented rule IDs as an ordered tuple."""
    assert isinstance(wkb.RULES, tuple)
    rule_ids = {r.id for r in wkb.RULES}
    expected = {
        "wiki-kb-notion-token-literal",
        "wiki-kb-atlassian-atatt-token",
        "wiki-kb-mediawiki-secretkey",
        "wiki-kb-bookstack-app-key",
        "wiki-kb-notion-unfiltered-search",
        "wiki-kb-wikijs-db-pass-config",
    }
    assert expected == rule_ids
    assert len(wkb.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to an ASI- prefix and a known severity enum value."""
    for rule in wkb.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding NamedTuple must expose all expected fields with correct types."""
    f = wkb.Finding(
        rule_id="wiki-kb-test",
        line=3,
        column=7,
        matched_text="secret_abc123",
        severity="HIGH",
        description="test finding",
        owasp_asi="ASI-02",
    )
    assert f.rule_id == "wiki-kb-test"
    assert f.line == 3
    assert f.column == 7
    assert f.matched_text == "secret_abc123"
    assert f.severity == "HIGH"
    assert f.description == "test finding"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_list() -> None:
    """Empty input must short-circuit immediately to an empty list."""
    assert wkb.scan_text("") == []


def test_scan_text_returns_list_of_findings() -> None:
    """scan_text always returns a list; benign input returns empty list."""
    result = wkb.scan_text("hello world, no secrets here")
    assert isinstance(result, list)
    assert result == []


def test_findings_are_deduplicated_by_rule_line_col() -> None:
    """Duplicate matches at the same (rule_id, line, col) produce one Finding."""
    src = f"NOTION_TOKEN = 'secret_{b62('notion-w1-dedup', 43)}'\n"
    results = wkb.scan_text(src)
    notion_findings = [f for f in results if f.rule_id == "wiki-kb-notion-token-literal"]
    lines_seen = [(f.line, f.column) for f in notion_findings]
    assert len(lines_seen) == len(set(lines_seen)), "Duplicate findings at same position"


# ---------- W1 : wiki-kb-notion-token-literal ----------------------------


def test_w1_notion_token_literal_detected() -> None:
    """Hardcoded Notion 'secret_' token in variable assignment must trigger W1."""
    src = f"NOTION_TOKEN = 'secret_{b62('notion-w1-detect', 43)}'\n"
    results = wkb.scan_text(src)
    rule_ids = [f.rule_id for f in results]
    assert "wiki-kb-notion-token-literal" in rule_ids


def test_w1_notion_token_placeholder_not_detected() -> None:
    """Placeholder string 'secret_REPLACE_WITH_REAL_TOKEN' must NOT trigger W1."""
    src = "NOTION_TOKEN = 'secret_REPLACE_WITH_REAL_TOKEN'\n"
    results = wkb.scan_text(src)
    # Placeholder has non-alphanumeric chars (underscores in value are ok but
    # 'REPLACE_WITH_REAL_TOKEN' is only 22 chars after 'secret_' — below minimum 40)
    rule_ids = [f.rule_id for f in results]
    assert "wiki-kb-notion-token-literal" not in rule_ids


def test_w1_notion_api_key_variable_name_triggers() -> None:
    """NOTION_API_KEY assignment with real-length secret_ prefix triggers W1."""
    src = f'NOTION_API_KEY = "secret_{b62("notion-w1-fire", 40)}"\n'
    results = wkb.scan_text(src)
    assert any(f.rule_id == "wiki-kb-notion-token-literal" for f in results)


def test_w1_notion_token_wrong_prefix_not_detected() -> None:
    """A Notion variable assignment with a non-'secret_' value must NOT trigger W1."""
    _tok = secret("ghp" + "_", "wiki-w1-nofire", 35)
    src = f"NOTION_TOKEN = '{_tok}'\n"
    results = wkb.scan_text(src)
    rule_ids = [f.rule_id for f in results]
    assert "wiki-kb-notion-token-literal" not in rule_ids


# ---------- W2 : wiki-kb-atlassian-atatt-token ---------------------------


def test_w2_atatt_prefix_token_detected() -> None:
    """Atlassian Cloud token with ATATT prefix must trigger W2."""
    src = f"api_token = '{_ATATT}xmNpQ3KrLvHwEoYsAbUdGiJfZcXtRePmOkNbVaSdFgHjKl'\n"
    results = wkb.scan_text(src)
    assert any(f.rule_id == "wiki-kb-atlassian-atatt-token" for f in results)


def test_w2_confluence_variable_name_detected() -> None:
    """CONFLUENCE_API_TOKEN assignment with long value must trigger W2."""
    src = f"CONFLUENCE_API_TOKEN = '{b62('wiki-w2-confluence', 40)}'\n"
    results = wkb.scan_text(src)
    assert any(f.rule_id == "wiki-kb-atlassian-atatt-token" for f in results)


def test_w2_short_value_not_detected() -> None:
    """A Confluence variable with a value shorter than 24 chars must NOT trigger W2."""
    src = "CONFLUENCE_API_TOKEN = 'shortval'\n"
    results = wkb.scan_text(src)
    rule_ids = [f.rule_id for f in results]
    assert "wiki-kb-atlassian-atatt-token" not in rule_ids


def test_w2_atatt_prefix_in_comment_detected() -> None:
    """ATATT prefix token anywhere in text (even in comments) triggers W2 (no FP carve-out for context)."""
    src = f"# token: {_ATATT}xmNpQ3KrLvHwEoYsAbUdGiJfZcXtRePmOkNbVaSdFgHjKl\n"
    results = wkb.scan_text(src)
    assert any(f.rule_id == "wiki-kb-atlassian-atatt-token" for f in results)


# ---------- W3 : wiki-kb-mediawiki-secretkey -----------------------------


def test_w3_wgsecretkey_64_hex_detected() -> None:
    """$wgSecretKey with 64-char hex string must trigger W3."""
    src = (
        "$wgSecretKey = '3a7b8c2e4f1d9a6b5c8e2f7a4d1b3c9e"  # gitleaks:allow  pragma: allowlist secret
        "6f2a8d5b7c4e1f3a9d6b2c5e8f1a4d7b';\n"
    )
    results = wkb.scan_text(src)
    assert any(f.rule_id == "wiki-kb-mediawiki-secretkey" for f in results)


def test_w3_wgdbpassword_detected() -> None:
    """$wgDBpassword with a value must trigger W3."""
    src = f"$wgDBpassword = '{b62('wiki-w3-dbpass', 22)}';\n"
    results = wkb.scan_text(src)
    assert any(f.rule_id == "wiki-kb-mediawiki-secretkey" for f in results)


def test_w3_placeholder_short_value_not_detected() -> None:
    """$wgSecretKey with a very short placeholder (< 16 hex chars) must NOT trigger W3."""
    src = "$wgSecretKey = 'changeme';\n"
    results = wkb.scan_text(src)
    rule_ids = [f.rule_id for f in results]
    assert "wiki-kb-mediawiki-secretkey" not in rule_ids


def test_w3_non_mediawiki_variable_not_detected() -> None:
    """An unrelated PHP variable assignment must NOT trigger W3."""
    src = f"$appSecret = '{b62('wiki-w3-nofire-app', 20)}';\n"
    results = wkb.scan_text(src)
    rule_ids = [f.rule_id for f in results]
    assert "wiki-kb-mediawiki-secretkey" not in rule_ids


# ---------- W4 : wiki-kb-bookstack-app-key -------------------------------


def test_w4_app_key_base64_dotenv_detected() -> None:
    """APP_KEY=base64:... in a dotenv block must trigger W4."""
    src = "APP_KEY=base64:kQpR3mXvTnLwEoYsAbUdGiJfZcXtRePmOkNbVaSdFg=\n"
    results = wkb.scan_text(src)
    assert any(f.rule_id == "wiki-kb-bookstack-app-key" for f in results)


def test_w4_app_key_in_docker_compose_detected() -> None:
    """APP_KEY: base64:... in YAML environment block must trigger W4."""
    src = "      APP_KEY: base64:kQpR3mXvTnLwEoYsAbUdGiJfZcXtRePmOkNbVaSdFg=\n"
    results = wkb.scan_text(src)
    assert any(f.rule_id == "wiki-kb-bookstack-app-key" for f in results)


def test_w4_short_base64_not_detected() -> None:
    """APP_KEY=base64: with fewer than 40 base64 chars must NOT trigger W4."""
    src = "APP_KEY=base64:shortval==\n"
    results = wkb.scan_text(src)
    rule_ids = [f.rule_id for f in results]
    assert "wiki-kb-bookstack-app-key" not in rule_ids


def test_w4_env_var_reference_not_detected() -> None:
    """APP_KEY referencing an environment variable placeholder must NOT trigger W4."""
    src = "APP_KEY=${LARAVEL_APP_KEY}\n"
    results = wkb.scan_text(src)
    rule_ids = [f.rule_id for f in results]
    assert "wiki-kb-bookstack-app-key" not in rule_ids


# ---------- W5 : wiki-kb-notion-unfiltered-search ------------------------


def test_w5_notion_search_req_body_detected() -> None:
    """notion.search({ query: req.body.q }) must trigger W5."""
    src = "const res = await notion.search({ query: req.body.q, filter: { value: 'page' } });\n"
    results = wkb.scan_text(src)
    assert any(f.rule_id == "wiki-kb-notion-unfiltered-search" for f in results)


def test_w5_notion_search_request_args_detected() -> None:
    """notion.search with request.args.get() passing detected via Python form."""
    src = (
        "results = notion.search(query=request.args.get('q'),\n"
        "                        filter={'value': 'page', 'property': 'object'})\n"
    )
    results = wkb.scan_text(src)
    assert any(f.rule_id == "wiki-kb-notion-unfiltered-search" for f in results)


def test_w5_notion_search_static_query_not_detected() -> None:
    """notion.search with a hardcoded static string must NOT trigger W5."""
    src = "const r = await notion.search({ query: 'security incident' });\n"
    results = wkb.scan_text(src)
    rule_ids = [f.rule_id for f in results]
    assert "wiki-kb-notion-unfiltered-search" not in rule_ids


def test_w5_notion_search_no_query_key_not_detected() -> None:
    """notion.search() call without a query: key must NOT trigger W5."""
    src = "const r = await notion.search({ filter: { value: 'page' } });\n"
    results = wkb.scan_text(src)
    rule_ids = [f.rule_id for f in results]
    assert "wiki-kb-notion-unfiltered-search" not in rule_ids


# ---------- W6 : wiki-kb-wikijs-db-pass-config ---------------------------


def test_w6_wikijs_db_pass_config_detected() -> None:
    """Wiki.js config.yml db.pass with plaintext password must trigger W6."""
    src = (
        "# wikijs config\n"
        "db:\n"
        "  type: postgres\n"
        "  host: localhost\n"
        "  port: 5432\n"
        "  user: wikijs\n"
        "  pass: wikijs_prod_P4ssw0rd2024\n"
        "  db: wiki\n"
    )
    results = wkb.scan_text(src)
    assert any(f.rule_id == "wiki-kb-wikijs-db-pass-config" for f in results)


def test_w6_password_yaml_key_detected() -> None:
    """A YAML 'password:' key with a real value must trigger W6."""
    src = "  password: mySuperSecretWikiPassword\n"
    results = wkb.scan_text(src)
    assert any(f.rule_id == "wiki-kb-wikijs-db-pass-config" for f in results)


def test_w6_placeholder_null_not_detected() -> None:
    """'pass: null' must NOT trigger W6 (null is an allowed placeholder)."""
    src = "  pass: null\n"
    results = wkb.scan_text(src)
    rule_ids = [f.rule_id for f in results]
    assert "wiki-kb-wikijs-db-pass-config" not in rule_ids


def test_w6_env_var_substitution_not_detected() -> None:
    """'pass: ${DB_PASS}' (env var reference) must NOT trigger W6."""
    src = "  pass: ${DB_PASS}\n"
    results = wkb.scan_text(src)
    # ${DB_PASS} starts with '$' which is not in [^\n#"'] set properly handled
    # by the pattern anchoring; it should NOT produce a finding.
    rule_ids = [f.rule_id for f in results]
    assert "wiki-kb-wikijs-db-pass-config" not in rule_ids


def test_w6_short_value_not_detected() -> None:
    """'password: abc' (fewer than 8 chars) must NOT trigger W6."""
    src = "  password: abc\n"
    results = wkb.scan_text(src)
    rule_ids = [f.rule_id for f in results]
    assert "wiki-kb-wikijs-db-pass-config" not in rule_ids
