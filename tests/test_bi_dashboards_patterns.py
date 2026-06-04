"""Tests for scripts/lib/bi_dashboards_patterns.py.

Pattern-coverage tests for the Wave-28 distill-round-14 BI dashboards
catalogue (7 BI-platform-specific anti-patterns covering Tableau /
PowerBI / Metabase / Superset / Looker). Each rule has at least two
tests: one positive (canary that MUST fire) and one negative (carve-out
or context filter that MUST NOT fire).
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import bi_dashboards_patterns as bdp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62  # noqa: E402

_PBI_BLOB = base64.b64encode(b62("pbi-conn", 42).encode()).decode()

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(bdp.RULES, tuple)
    rule_ids = {r.id for r in bdp.RULES}
    expected = {
        "bi-tableau-workbook-embedded-password",
        "bi-powerbi-encoded-connection-string",
        "bi-metabase-encryption-key-hardcoded",
        "bi-superset-secret-key-hardcoded",
        "bi-metabase-session-token-in-source",
        "bi-looker-client-secret-hardcoded",
        "bi-tableau-pat-hardcoded",
    }
    assert expected == rule_ids
    assert len(bdp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in bdp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = bdp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert bdp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Findings must be ordered by (line, col) ascending."""
    src = (
        "password=\"P@ssw0rd_Tableau2024!\"\n"
        "MB_ENCRYPTION_SECRET_KEY=t0pS3cret_M3tab4se_k3y!\n"
    )
    findings = bdp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[bdp.Finding]:
    return [f for f in bdp.scan_text(text) if f.rule_id == rule_id]


# ---------- B1 : bi-tableau-workbook-embedded-password -------------------


def test_b1_tableau_password_attribute_flags() -> None:
    """Tableau .twb XML with real embedded password → CRITICAL hit."""
    src = (
        '<connection authentication="sqlserver"\n'
        '            class="sqlserver"\n'
        '            server="db.corp.example.com"\n'
        '            username="svc_tableau"\n'
        '            password="P@ssw0rd_Tableau2024!"\n'
        '            port="1433" />\n'
    )
    hits = _hits("bi-tableau-workbook-embedded-password", src)
    assert hits, "Expected a finding for embedded Tableau password"
    assert hits[0].severity == "CRITICAL"


def test_b1_tableau_password_in_single_quotes_flags() -> None:
    """Tableau password in single-quoted attribute → hit."""
    src = "password='SuperSecret123'\n"
    hits = _hits("bi-tableau-workbook-embedded-password", src)
    assert hits


def test_b1_tableau_placeholder_required_skipped() -> None:
    """Tableau placeholder '(Required)' must NOT fire."""
    src = 'password="(Required)"\n'
    assert not _hits("bi-tableau-workbook-embedded-password", src)


def test_b1_tableau_empty_password_skipped() -> None:
    """Empty password attribute must NOT fire."""
    src = 'password=""\n'
    assert not _hits("bi-tableau-workbook-embedded-password", src)


# ---------- B2 : bi-powerbi-encoded-connection-string --------------------


def test_b2_powerbi_encoded_connection_flags() -> None:
    """PowerBI DataMashup EncodedConnectionString → CRITICAL hit."""
    # Simulated base64 blob >= 30 chars
    src = (
        "<EncodedConnectionString>"
        + _PBI_BLOB
        + "</EncodedConnectionString>\n"
    )
    hits = _hits("bi-powerbi-encoded-connection-string", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_b2_powerbi_multiline_blob_flags() -> None:
    """Multi-line base64 blob inside EncodedConnectionString → hit."""
    src = (
        "<EncodedConnectionString>\n"
        "  "
        + _PBI_BLOB
        + "\n</EncodedConnectionString>\n"
    )
    hits = _hits("bi-powerbi-encoded-connection-string", src)
    assert hits


def test_b2_powerbi_short_blob_skipped() -> None:
    """EncodedConnectionString with fewer than 30 base64 chars → no hit."""
    src = "<EncodedConnectionString>abc123</EncodedConnectionString>\n"
    assert not _hits("bi-powerbi-encoded-connection-string", src)


def test_b2_no_tag_no_hit() -> None:
    """Bare base64 without the XML tag → no hit for this rule."""
    src = _PBI_BLOB + "\n"
    assert not _hits("bi-powerbi-encoded-connection-string", src)


# ---------- B3 : bi-metabase-encryption-key-hardcoded -------------------


def test_b3_metabase_key_in_dotenv_flags() -> None:
    """MB_ENCRYPTION_SECRET_KEY in .env with real key → HIGH hit."""
    src = "MB_ENCRYPTION_SECRET_KEY=t0pS3cret_M3tab4se_k3y!\n"
    hits = _hits("bi-metabase-encryption-key-hardcoded", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_b3_metabase_key_in_compose_yaml_flags() -> None:
    """MB_ENCRYPTION_SECRET_KEY in docker-compose YAML → hit."""
    src = "      MB_ENCRYPTION_SECRET_KEY: 'strongK3y_20chars_here'\n"
    hits = _hits("bi-metabase-encryption-key-hardcoded", src)
    assert hits


def test_b3_metabase_placeholder_key_skipped() -> None:
    """Placeholder value containing 'your' must NOT fire."""
    src = "MB_ENCRYPTION_SECRET_KEY=your-32-character-secret-key-here\n"
    assert not _hits("bi-metabase-encryption-key-hardcoded", src)


def test_b3_metabase_too_short_key_skipped() -> None:
    """Key value shorter than 10 chars (threshold) → no hit."""
    src = "MB_ENCRYPTION_SECRET_KEY=short\n"
    assert not _hits("bi-metabase-encryption-key-hardcoded", src)


# ---------- B4 : bi-superset-secret-key-hardcoded -----------------------


def test_b4_superset_known_default_key_flags() -> None:
    """Known Superset default 'thisismyscretkey' → CRITICAL hit."""
    src = "SECRET_KEY = 'thisismyscretkey'\n"
    hits = _hits("bi-superset-secret-key-hardcoded", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_b4_superset_default_substring_flags() -> None:
    """The default key inside the hex-escape form → hit."""
    src = r"SECRET_KEY = '\x02\x01thisismyscretkey\x01\x02\xe1\xe1\x00\x00'" + "\n"
    hits = _hits("bi-superset-secret-key-hardcoded", src)
    assert hits


def test_b4_superset_arbitrary_hardcoded_key_flags() -> None:
    """Arbitrary >=8 char SECRET_KEY value in Python config → hit."""
    src = "SECRET_KEY = 'Sup3rS3cr3tK3y!'\n"
    hits = _hits("bi-superset-secret-key-hardcoded", src)
    assert hits


def test_b4_superset_commented_line_skipped() -> None:
    """SECRET_KEY assignment in a comment line must not fire from the assignment rule."""
    # The known-default literal fires everywhere (raw substring), so use a
    # non-default key to isolate the assignment sub-rule's comment guard.
    src = "# SECRET_KEY = 'SomeArbitraryKey123'\n"
    assert not _hits("bi-superset-secret-key-hardcoded", src)


def test_b4_superset_placeholder_key_skipped() -> None:
    """Placeholder value 'your-secret-key-here' → no hit from assignment rule."""
    src = "SECRET_KEY = 'your-secret-key-here'\n"
    assert not _hits("bi-superset-secret-key-hardcoded", src)


# ---------- B5 : bi-metabase-session-token-in-source --------------------


def test_b5_metabase_session_header_token_flags() -> None:
    """X-Metabase-Session header with UUID → HIGH hit."""
    src = 'headers = {"X-Metabase-Session": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"}\n'
    hits = _hits("bi-metabase-session-token-in-source", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_b5_metabase_session_in_log_output_flags() -> None:
    """Metabase session token in CI log output → hit."""
    src = "metabase-session: a1b2c3d4-e5f6-7890-abcd-ef1234567890\n"
    hits = _hits("bi-metabase-session-token-in-source", src)
    assert hits


def test_b5_all_zero_uuid_skipped() -> None:
    """All-zeros UUID (synthetic / test token) → no hit."""
    src = 'headers = {"X-Metabase-Session": "00000000-0000-0000-0000-000000000000"}\n'
    assert not _hits("bi-metabase-session-token-in-source", src)


def test_b5_no_metabase_context_no_hit() -> None:
    """Bare UUID without Metabase session context → no hit from this rule."""
    src = "id = a1b2c3d4-e5f6-7890-abcd-ef1234567890\n"
    assert not _hits("bi-metabase-session-token-in-source", src)


# ---------- B6 : bi-looker-client-secret-hardcoded ----------------------


def test_b6_looker_client_secret_in_ini_flags() -> None:
    """looker.ini client_secret with real value → HIGH hit."""
    src = f"client_secret={b62('b6-looker-cs-ini', 27)}\n"
    hits = _hits("bi-looker-client-secret-hardcoded", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_b6_looker_client_secret_in_python_flags() -> None:
    """LOOKER_CLIENT_SECRET variable assignment → hit."""
    src = f'LOOKER_CLIENT_SECRET = "{b62("b6-looker-cs-py", 35)}"\n'
    hits = _hits("bi-looker-client-secret-hardcoded", src)
    assert hits


def test_b6_env_var_expansion_skipped() -> None:
    """client_secret with env-var expansion → no hit."""
    src = "client_secret=${LOOKER_CLIENT_SECRET}\n"
    assert not _hits("bi-looker-client-secret-hardcoded", src)


def test_b6_placeholder_secret_skipped() -> None:
    """Placeholder value 'your_client_secret' → no hit."""
    src = "looker_client_secret = your_client_secret_here\n"
    assert not _hits("bi-looker-client-secret-hardcoded", src)


# ---------- B7 : bi-tableau-pat-hardcoded --------------------------------


def test_b7_tableau_pat_variable_flags() -> None:
    """TABLEAU_PAT_SECRET variable with token → HIGH hit."""
    src = f'TABLEAU_PAT_SECRET = "{b62("b7-tableau-pat", 45)}"\n'
    hits = _hits("bi-tableau-pat-hardcoded", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_b7_tableau_token_in_xml_flags() -> None:
    """Tableau REST API XML response with <token> element → hit."""
    _tok = b62("bi-tab-xml-tok", 42)
    src = (
        '<tsResponse>\n'
        f'  <credentials token="{_tok}==" />\n'
        "</tsResponse>\n"
        f"<token>{_tok}==</token>\n"
    )
    hits = _hits("bi-tableau-pat-hardcoded", src)
    assert hits


def test_b7_tableau_personal_access_token_kwarg_flags() -> None:
    """tableauserverclient personal_access_token= keyword arg → hit."""
    src = (
        "tableau_auth = TSC.PersonalAccessTokenAuth(\n"
        '    token_name="ci-pat",\n'
        '    personal_access_token=AbCdEfGhIjKlMnOpQrStUvWxYz0123456789,\n'
        '    site_id="corp",\n'
        ")\n"
    )
    hits = _hits("bi-tableau-pat-hardcoded", src)
    assert hits


def test_b7_placeholder_token_skipped() -> None:
    """Placeholder 'YOUR_TOKEN' value → no hit."""
    src = 'TABLEAU_TOKEN = "your_token_here"\n'
    assert not _hits("bi-tableau-pat-hardcoded", src)


def test_b7_short_xml_token_skipped() -> None:
    """<token> element with fewer than 20 chars → no hit."""
    src = "<token>shorttoken</token>\n"
    assert not _hits("bi-tableau-pat-hardcoded", src)
