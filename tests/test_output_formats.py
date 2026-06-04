"""Tests for scripts/lib/output_formats.py.

Coverage targets:

- make_badge / verify_badge wire shape + signature + expiry
- Tamper resistance (every field swap → "bad signature", not "OK")
- Timing-safe comparator is actually wired (not `==`)
- Malformed inputs degrade to (False, "malformed") — never raise
- format_security_triggered byte-exact layout
- parse_approval_response strict literal contract
- apply_fp_filters substring semantics + empty-list / empty-filter edges
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import output_formats  # type: ignore[import-not-found]  # noqa: E402

_KEY = b"unit-test-hmac-key-do-not-reuse-in-prod"


# ---------- make_badge / verify_badge happy path ------------------------


def test_make_badge_wire_shape() -> None:
    """make_badge returns exactly five `|`-joined fields."""
    badge = output_formats.make_badge("rid-1", "safe", 1_700_000_000, _KEY)
    parts = badge.split("|")
    assert len(parts) == 5
    rid, verdict, scanned_at, expires_at, sig = parts
    assert rid == "rid-1"
    assert verdict == "safe"
    assert int(scanned_at) == 1_700_000_000
    # Default expiry = 30 days = 30 * 86400 seconds
    assert int(expires_at) == 1_700_000_000 + 30 * 86_400
    # Signature is non-empty base64
    assert sig
    assert all(c.isalnum() or c in "+/=" for c in sig)


def test_make_badge_custom_expiry() -> None:
    """expiry_days propagates into expires_at."""
    badge = output_formats.make_badge("rid-2", "drift", 1_000, _KEY, expiry_days=7)
    expires_at = int(badge.split("|")[3])
    assert expires_at == 1_000 + 7 * 86_400


def test_verify_badge_roundtrip_ok() -> None:
    """A freshly-minted badge verifies OK well before its expiry."""
    badge = output_formats.make_badge("rid-3", "safe", 2_000_000_000, _KEY)
    valid, reason = output_formats.verify_badge(badge, _KEY, now=2_000_000_000 + 1)
    assert valid is True
    assert reason == "OK"


def test_verify_badge_blocked_verdict_ok() -> None:
    """Verdict literal is not constrained (caller's contract); 'blocked' is fine."""
    badge = output_formats.make_badge("rid-4", "blocked", 100, _KEY)
    valid, reason = output_formats.verify_badge(badge, _KEY, now=101)
    assert valid is True
    assert reason == "OK"


# ---------- Expiry behaviour --------------------------------------------


def test_verify_badge_expired_at_boundary() -> None:
    """expires_at == now is treated as expired (strict <= comparison)."""
    badge = output_formats.make_badge("rid-5", "safe", 100, _KEY, expiry_days=1)
    expires_at = 100 + 86_400
    valid, reason = output_formats.verify_badge(badge, _KEY, now=expires_at)
    assert valid is False
    assert reason == "expired"


def test_verify_badge_expired_well_past() -> None:
    """A clearly stale badge returns ("expired"), not OK."""
    badge = output_formats.make_badge("rid-6", "safe", 100, _KEY, expiry_days=1)
    valid, reason = output_formats.verify_badge(badge, _KEY, now=100 + 999_999)
    assert valid is False
    assert reason == "expired"


def test_make_badge_rejects_zero_expiry() -> None:
    """Zero / negative expiry would mint a pre-expired badge — fail-fast."""
    import pytest

    with pytest.raises(ValueError):
        output_formats.make_badge("rid-7", "safe", 100, _KEY, expiry_days=0)
    with pytest.raises(ValueError):
        output_formats.make_badge("rid-8", "safe", 100, _KEY, expiry_days=-1)


def test_make_badge_rejects_separator_in_fields() -> None:
    """Embedded `|` in report_id or verdict would let an attacker re-shape the payload."""
    import pytest

    with pytest.raises(ValueError):
        output_formats.make_badge("ri|d", "safe", 100, _KEY)
    with pytest.raises(ValueError):
        output_formats.make_badge("rid", "sa|fe", 100, _KEY)


# ---------- Tamper resistance — every field must be signed --------------


def test_verify_badge_detects_verdict_tampering() -> None:
    """Flipping verdict from safe→blocked invalidates the signature."""
    badge = output_formats.make_badge("rid-9", "safe", 100, _KEY, expiry_days=365)
    parts = badge.split("|")
    parts[1] = "blocked"
    tampered = "|".join(parts)
    valid, reason = output_formats.verify_badge(tampered, _KEY, now=101)
    assert valid is False
    assert reason == "bad signature"


def test_verify_badge_detects_report_id_tampering() -> None:
    """Swapping report_id invalidates the signature."""
    badge = output_formats.make_badge("rid-10", "safe", 100, _KEY, expiry_days=365)
    parts = badge.split("|")
    parts[0] = "rid-other"
    tampered = "|".join(parts)
    valid, reason = output_formats.verify_badge(tampered, _KEY, now=101)
    assert valid is False
    assert reason == "bad signature"


def test_verify_badge_detects_scanned_at_tampering() -> None:
    """Pushing scanned_at forward without resigning fails."""
    badge = output_formats.make_badge("rid-11", "safe", 100, _KEY, expiry_days=365)
    parts = badge.split("|")
    parts[2] = "200"
    tampered = "|".join(parts)
    valid, reason = output_formats.verify_badge(tampered, _KEY, now=300)
    assert valid is False
    assert reason == "bad signature"


def test_verify_badge_detects_expires_at_tampering() -> None:
    """Extending expires_at without resigning fails — the most attractive forgery."""
    badge = output_formats.make_badge("rid-12", "safe", 100, _KEY, expiry_days=1)
    parts = badge.split("|")
    parts[3] = str(int(parts[3]) + 86_400 * 365)
    tampered = "|".join(parts)
    valid, reason = output_formats.verify_badge(tampered, _KEY, now=300)
    assert valid is False
    assert reason == "bad signature"


def test_verify_badge_detects_signature_tampering() -> None:
    """Mangling the signature directly fails."""
    badge = output_formats.make_badge("rid-13", "safe", 100, _KEY, expiry_days=365)
    parts = badge.split("|")
    parts[4] = "AAAA" + parts[4][4:]
    tampered = "|".join(parts)
    valid, reason = output_formats.verify_badge(tampered, _KEY, now=101)
    assert valid is False
    assert reason == "bad signature"


def test_verify_badge_wrong_key() -> None:
    """A badge signed with KEY-A does NOT verify under KEY-B."""
    badge = output_formats.make_badge("rid-14", "safe", 100, _KEY, expiry_days=365)
    valid, reason = output_formats.verify_badge(badge, b"different-key", now=101)
    assert valid is False
    assert reason == "bad signature"


# ---------- Malformed badge inputs --------------------------------------


def test_verify_badge_empty_string() -> None:
    valid, reason = output_formats.verify_badge("", _KEY, now=1)
    assert valid is False
    assert reason == "malformed"


def test_verify_badge_wrong_field_count() -> None:
    valid, reason = output_formats.verify_badge("only|three|fields", _KEY, now=1)
    assert valid is False
    assert reason == "malformed"


def test_verify_badge_six_fields_too_many() -> None:
    valid, reason = output_formats.verify_badge("a|b|1|2|sig|extra", _KEY, now=1)
    assert valid is False
    assert reason == "malformed"


def test_verify_badge_non_integer_timestamps() -> None:
    """Junk in the timestamp slots returns 'malformed', not a stack trace."""
    valid, reason = output_formats.verify_badge("rid|safe|notanint|200|sig", _KEY, now=1)
    assert valid is False
    assert reason == "malformed"


def test_verify_badge_empty_report_id() -> None:
    """An empty report_id is malformed — caller never had a stable identifier."""
    valid, reason = output_formats.verify_badge("|safe|100|200|sig", _KEY, now=1)
    assert valid is False
    assert reason == "malformed"


def test_verify_badge_empty_verdict() -> None:
    valid, reason = output_formats.verify_badge("rid||100|200|sig", _KEY, now=1)
    assert valid is False
    assert reason == "malformed"


# ---------- Timing-safe comparator is wired -----------------------------


def test_verify_badge_uses_compare_digest(monkeypatch) -> None:
    """If we remove hmac.compare_digest, the test should fail — proves it's wired."""
    import hmac as real_hmac

    calls: list[tuple[bytes, bytes]] = []
    original = real_hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return original(a, b)

    monkeypatch.setattr(output_formats.hmac, "compare_digest", spy)
    badge = output_formats.make_badge("rid-15", "safe", 100, _KEY, expiry_days=365)
    output_formats.verify_badge(badge, _KEY, now=101)
    assert calls, "verify_badge must use hmac.compare_digest, not =="


# ---------- format_security_triggered byte-exact layout -----------------


def test_format_security_triggered_layout() -> None:
    """The block's wire format is byte-exact — no trailing whitespace, no extra blanks."""
    block = output_formats.format_security_triggered(
        action="Edit .claude/settings.json",
        normalized_diff="+ key: value",
    )
    expected = (
        "SECURITY TRIGGERED:\n"
        "Edit .claude/settings.json\n"
        "+ key: value\n"
        "\n"
        "Reply APPROVED to proceed."
    )
    assert block == expected


def test_format_security_triggered_passes_normalized_diff_through() -> None:
    """The diff field is preserved verbatim — caller hands in the rule-normalized text."""
    diff = "- old\n+ new\n# normalized: pin ^1.0.0 -> 1.0.0\n# scripts stripped: postinstall"
    block = output_formats.format_security_triggered("Add npm dep", diff)
    assert diff in block
    # The instruction line MUST appear AFTER the diff, after a blank line.
    assert block.endswith("\n\nReply APPROVED to proceed.")


def test_format_security_triggered_empty_diff() -> None:
    """Empty diff is allowed (informational gate); structure still holds."""
    block = output_formats.format_security_triggered("Touch lockfile", "")
    assert block.startswith("SECURITY TRIGGERED:\nTouch lockfile\n")
    assert block.endswith("Reply APPROVED to proceed.")


# ---------- parse_approval_response strict literal ----------------------


def test_parse_approval_response_exact_token() -> None:
    assert output_formats.parse_approval_response("APPROVED") is True


def test_parse_approval_response_strips_whitespace() -> None:
    """Surrounding whitespace from copy-paste is tolerated."""
    assert output_formats.parse_approval_response("  APPROVED\n") is True
    assert output_formats.parse_approval_response("\tAPPROVED  ") is True


def test_parse_approval_response_rejects_lowercase() -> None:
    """Case-sensitive — 'approved' is NOT enough."""
    assert output_formats.parse_approval_response("approved") is False


def test_parse_approval_response_rejects_synonyms() -> None:
    """Synonym tolerance is exactly the surface attackers exploit — strict literal only."""
    for syn in ("yes", "y", "ok", "OK", "sure", "lgtm", "APPROVE", "Approved", "APPROVED!"):
        assert output_formats.parse_approval_response(syn) is False, syn


def test_parse_approval_response_rejects_embedded_whitespace() -> None:
    """Internal whitespace breaks the literal — 'APP ROVED' is not 'APPROVED'."""
    assert output_formats.parse_approval_response("APP ROVED") is False
    assert output_formats.parse_approval_response("APPRO VED") is False


def test_parse_approval_response_rejects_extra_text() -> None:
    """Approval cannot be smuggled inside a longer phrase."""
    assert output_formats.parse_approval_response("yes, APPROVED") is False
    assert output_formats.parse_approval_response("APPROVED for the next 5 turns") is False


def test_parse_approval_response_empty() -> None:
    assert output_formats.parse_approval_response("") is False
    assert output_formats.parse_approval_response("   ") is False


# ---------- apply_fp_filters substring DSL ------------------------------


def test_apply_fp_filters_match() -> None:
    """Any matching substring → True (rule should suppress the finding)."""
    assert output_formats.apply_fp_filters("tests/fixtures/setup.sh", ["tests/", "examples/"]) is True


def test_apply_fp_filters_no_match() -> None:
    """No filter matches → False (rule emits the finding normally)."""
    assert output_formats.apply_fp_filters("src/lib/real.py", ["tests/", "examples/"]) is False


def test_apply_fp_filters_empty_list_returns_false() -> None:
    """Empty filter list means 'no allowlist', not 'allow everything'."""
    assert output_formats.apply_fp_filters("any text at all", []) is False


def test_apply_fp_filters_empty_filter_string_skipped() -> None:
    """An empty filter substring would match everything — must be skipped."""
    assert output_formats.apply_fp_filters("nothing matches here", ["", ""]) is False


def test_apply_fp_filters_mixed_empty_and_real() -> None:
    """A real filter alongside empties still matches on the real one."""
    assert output_formats.apply_fp_filters("path/with/tests/in/it", ["", "tests/"]) is True


def test_apply_fp_filters_case_sensitive() -> None:
    """Plain substring is case-sensitive — caller normalises for case-insensitive matching."""
    assert output_formats.apply_fp_filters("TESTS/foo", ["tests/"]) is False
    assert output_formats.apply_fp_filters("tests/foo", ["tests/"]) is True


def test_apply_fp_filters_first_filter_short_circuits() -> None:
    """Substring contained anywhere in text matches — order does not matter."""
    assert output_formats.apply_fp_filters("readme.md", ["nope", "readme", "still-nope"]) is True


def test_apply_fp_filters_empty_text() -> None:
    """Empty text + non-empty filters → no match (filter substring is non-empty)."""
    assert output_formats.apply_fp_filters("", ["tests/"]) is False
