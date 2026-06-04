"""Tests for scripts/lib/pci_dss_patterns.py.

Pattern-coverage tests for the Wave-27 distill-round-13 angle "pci-dss"
catalogue (8 PCI-DSS Req 3 / Req 4 cardholder-data violations). Each
rule has at least one positive test exercising the canary AND at least
one negative test exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pci_dss_patterns as pdp  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import secret  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 8 documented rule IDs."""
    assert isinstance(pdp.RULES, tuple)
    rule_ids = {r.id for r in pdp.RULES}
    expected = {
        "pci-dss-cvv-stored-in-db",
        "pci-dss-pan-logged-plaintext",
        "pci-dss-track-data-persisted",
        "pci-dss-pan-unmasked-in-response",
        "pci-dss-payment-secret-in-client-bundle",
        "pci-dss-pan-in-url-query",
        "pci-dss-pan-leaked-via-repr-str",
        "pci-dss-bin-lookup-third-party",
    }
    assert expected == rule_ids
    assert len(pdp.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in pdp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = pdp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-04",
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
    assert pdp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — track-2 magstripe literal (P3)
        "const track = ';4111111111111111=2512123456789';\n"
        # Line 2 — Stripe sk_live secret literal (P5)
        f"const k = '{secret('sk_' + 'live_', 'pci-sort-check', 30)}';\n"
    )
    findings = pdp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[pdp.Finding]:
    return [f for f in pdp.scan_text(text) if f.rule_id == rule_id]


# ---------- P1 : pci-dss-cvv-stored-in-db --------------------------------


def test_p1_orm_model_with_cvv_field_flags() -> None:
    """Django/SQLAlchemy ORM model declares a `cvv` column → CRITICAL hit."""
    src = (
        "class Payment(models.Model):\n"
        "    __tablename__ = 'payments'\n"
        "    card_number = models.CharField(max_length=19)\n"
        "    cvv = models.CharField(max_length=4)\n"
        "    expiry = models.DateField()\n"
    )
    hits = _hits("pci-dss-cvv-stored-in-db", src)
    assert hits
    assert hits[0].severity == "CRITICAL"
    assert hits[0].owasp_asi == "ASI-04"


def test_p1_dto_dataclass_without_persistence_does_not_flag() -> None:
    """A pure DTO @dataclass with a `cvv` field — no persistence context — must NOT flag."""
    src = (
        "@dataclass\n"
        "class PaymentRequest:\n"
        "    card_number: str\n"
        "    cvv: str\n"
        "    expiry: str\n"
        # No CREATE TABLE / models.Model / Base / Schema in the file.
    )
    assert not _hits("pci-dss-cvv-stored-in-db", src)


# ---------- P2 : pci-dss-pan-logged-plaintext ----------------------------


def test_p2_logger_info_with_card_number_flags() -> None:
    """`logger.info(f"... {card_number} ...")` → CRITICAL hit."""
    src = (
        'logger.info(f"Charged card {card_number} for {amount}")\n'
    )
    hits = _hits("pci-dss-pan-logged-plaintext", src)
    assert hits
    assert hits[0].severity == "CRITICAL"
    assert hits[0].owasp_asi == "ASI-09"


def test_p2_console_log_without_card_name_does_not_flag() -> None:
    """`console.log` of an unrelated variable must NOT flag."""
    src = 'console.log(`processed order ${orderId}`);\n'
    assert not _hits("pci-dss-pan-logged-plaintext", src)


def test_p2_console_log_with_cardnumber_flags() -> None:
    """`console.log(\\`... ${cardNumber} ...\\`)` → CRITICAL hit."""
    src = 'console.log(`payment with card ${cardNumber} authorised`);\n'
    hits = _hits("pci-dss-pan-logged-plaintext", src)
    assert hits


# ---------- P3 : pci-dss-track-data-persisted ----------------------------


def test_p3_track2_persisted_to_disk_flags() -> None:
    """A `track_data` variable written to disk → CRITICAL hit."""
    src = (
        'def store_swipe(track_data):\n'
        '    with open("/tmp/swipe.txt", "a") as f:\n'
        '        f.write(track_data)\n'
    )
    hits = _hits("pci-dss-track-data-persisted", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p3_track2_parsed_only_does_not_flag() -> None:
    """`parsed = parse_track2(track)` — no persistence verb — must NOT flag."""
    src = (
        'def validate_swipe(track):\n'
        '    parsed = parse_track2(track)\n'
        '    return parsed.is_valid()\n'
    )
    # `track` alone (not the suffixed `track1/track2/track_data`) isn't
    # in the name list — this is a sanity / pure-parser negative.
    assert not _hits("pci-dss-track-data-persisted", src)


def test_p3_raw_track2_literal_flags() -> None:
    """A raw Track-2 magstripe literal `;…=…` in source → CRITICAL hit."""
    src = "const SAMPLE = ';4111111111111111=2512123456789';\n"
    hits = _hits("pci-dss-track-data-persisted", src)
    assert hits


# ---------- P4 : pci-dss-pan-unmasked-in-response ------------------------


def test_p4_express_response_with_cardnumber_flags() -> None:
    """Express `res.json({ cardNumber: p.card_number })` → HIGH hit."""
    src = (
        "app.get('/api/payments/:id', async (req, res) => {\n"
        "  const p = await db.payments.findById(req.params.id);\n"
        "  res.json({ amount: p.amount, cardNumber: p.card_number, expiry: p.expiry });\n"
        "});\n"
    )
    hits = _hits("pci-dss-pan-unmasked-in-response", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p4_response_with_last4_masking_does_not_flag() -> None:
    """`res.json({ cardLast4: p.card_number.slice(-4) })` → suppressed."""
    src = (
        "app.get('/api/payments/:id', async (req, res) => {\n"
        "  const p = await db.payments.findById(req.params.id);\n"
        "  res.json({ amount: p.amount, cardLast4: p.card_number.slice(-4) });\n"
        "});\n"
    )
    assert not _hits("pci-dss-pan-unmasked-in-response", src)


# ---------- P5 : pci-dss-payment-secret-in-client-bundle ----------------


def test_p5_stripe_sk_live_literal_flags() -> None:
    """A live Stripe `sk_live_*` secret-key literal → CRITICAL hit."""
    src = (
        f"const stripe = require('stripe')('{secret('sk_' + 'live_', 'pci-p5-live', 30)}');\n"
    )
    hits = _hits("pci-dss-payment-secret-in-client-bundle", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p5_redacted_placeholder_does_not_flag() -> None:
    """A `.env.example` placeholder value (`xxxxx` / `REDACTED`) → suppressed."""
    src = (
        "# .env.example\n"
        "STRIPE_SECRET_KEY=sk_" + "live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
    )
    assert not _hits("pci-dss-payment-secret-in-client-bundle", src)


def test_p5_next_public_prefixed_secret_flags() -> None:
    """A `NEXT_PUBLIC_STRIPE_SECRET_KEY` env-var name → CRITICAL hit."""
    src = (
        "// next.config.js — NEXT_PUBLIC_* ships to the browser:\n"
        "const KEY = process.env.NEXT_PUBLIC_STRIPE_SECRET_KEY;\n"
    )
    hits = _hits("pci-dss-payment-secret-in-client-bundle", src)
    assert hits


# ---------- P6 : pci-dss-pan-in-url-query --------------------------------


def test_p6_fetch_with_pan_in_query_flags() -> None:
    """`fetch('/charge?pan=${pan}')` → HIGH hit."""
    src = (
        "fetch(`https://api.example.com/charge?pan=${cardNumber}&amount=${amt}`);\n"
    )
    hits = _hits("pci-dss-pan-in-url-query", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p6_unrelated_pan_query_without_payment_path_does_not_flag() -> None:
    """A `?pan=` query in a graphics-widget URL (Panorama Pan zoom) → suppressed."""
    src = (
        "// Panorama view zoom widget — `pan` here is the pan-zoom factor.\n"
        "fetch(`/widget/render?pan=${panFactor}&zoom=${zoomLevel}`);\n"
    )
    # No payment-themed URL path → no hit.
    assert not _hits("pci-dss-pan-in-url-query", src)


# ---------- P7 : pci-dss-pan-leaked-via-repr-str -------------------------


def test_p7_card_class_with_repr_flags() -> None:
    """A `Card` class with a `__repr__` AND payment-domain markers → HIGH hit."""
    src = (
        "@dataclass\n"
        "class Card:\n"
        "    number: str\n"
        "    cvv: str\n"
        "    expiry: str\n"
        "    amount: float\n"
        "    def __repr__(self) -> str:\n"
        "        return f'Card(number={self.number}, expiry={self.expiry})'\n"
    )
    hits = _hits("pci-dss-pan-leaked-via-repr-str", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_p7_business_card_class_without_payment_domain_does_not_flag() -> None:
    """A `BusinessCard` class with `__repr__` and NO payment markers → suppressed."""
    src = (
        "class BusinessCard:\n"
        "    name: str\n"
        "    title: str\n"
        "    company: str\n"
        "    phone: str\n"
        "    def __repr__(self) -> str:\n"
        "        return f'BusinessCard(name={self.name}, company={self.company})'\n"
    )
    # No `expiry`/`cvv`/`merchant`/`stripe`/etc. anywhere in file.
    assert not _hits("pci-dss-pan-leaked-via-repr-str", src)


def test_p7_pydantic_pan_plain_str_flags() -> None:
    """A pydantic `BaseModel` with `card_number: str` (should be SecretStr) → HIGH hit."""
    src = (
        "class Payment(BaseModel):\n"
        "    card_number: str\n"
        "    amount: float\n"
    )
    hits = _hits("pci-dss-pan-leaked-via-repr-str", src)
    assert hits


# ---------- P8 : pci-dss-bin-lookup-third-party --------------------------


def test_p8_fetch_to_binlist_net_flags() -> None:
    """`fetch('https://lookup.binlist.net/...')` → MEDIUM hit."""
    src = (
        "const bin = await fetch(`https://lookup.binlist.net/${cardNumber}`);\n"
    )
    hits = _hits("pci-dss-bin-lookup-third-party", src)
    assert hits
    assert hits[0].severity == "MEDIUM"
    assert hits[0].owasp_asi == "ASI-08"


def test_p8_internal_bin_endpoint_does_not_flag() -> None:
    """A BIN-lookup hitting an internal `localhost` / `10.x` host → suppressed."""
    src = (
        "const bin = await fetch(`https://localhost:9000/bin/${cardNumber.substr(0,6)}`);\n"
        "const bin2 = await fetch(`https://10.0.0.5/bin/${pan}`);\n"
    )
    # `localhost` / `10.x` markers in the URL → suppression. And the URL
    # host isn't in `_THIRD_PARTY_BIN_HOST` either.
    assert not _hits("pci-dss-bin-lookup-third-party", src)


def test_p8_binlist_with_localhost_marker_suppressed() -> None:
    """`apilayer.com/bin` with a `// localhost-tunnel` comment marker → suppressed."""
    src = (
        "// localhost-tunneled to apilayer.com/bin for local dev only.\n"
        "fetch('https://apilayer.com/bin/v1/check');\n"
    )
    # 200-char span around the host match contains `localhost` → drop.
    assert not _hits("pci-dss-bin-lookup-third-party", src)
