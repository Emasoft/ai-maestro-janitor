"""Tests for scripts/lib/mime_mail_patterns.py.

Pattern-coverage tests for the Wave-24 distill-round-10 MIME / mail
deeper parsing & content attack catalogue (8 anti-patterns covering
MIME boundary smuggling, attachment-disguise RCE, S/MIME signature trust
failures, calendar-invite injection, parser policy gaps, custom-header
injection, and email-attachment insecure-deserialization).

Each rule has at least one positive test exercising the canary AND at
least one negative test exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import mime_mail_patterns as mmp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 8 documented rule IDs."""
    assert isinstance(mmp.RULES, tuple)
    rule_ids = {r.id for r in mmp.RULES}
    expected = {
        "mime-boundary-attacker-controlled",
        "mime-attachment-double-extension-rce",
        "mime-smime-chain-only-no-signature-verify",
        "mime-parser-no-strict-policy",
        "mime-attachment-filename-rtlo-bidi",
        "mime-ics-method-request-no-sender-verify",
        "mime-custom-header-crlf-injection",
        "mime-attachment-payload-insecure-deserialize",
    }
    assert expected == rule_ids
    assert len(mmp.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in mmp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = mmp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert mmp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — boundary from req.body
        "msg.set_boundary(request.json['boundary'])\n"
        # Line 2 — double-extension literal
        'attachment = {"filename": "report.pdf.exe", "data": buf}\n'
        # Line 3 — bidi RTLO in filename literal
        'header = "Content-Disposition: attachment; filename=\\"invoice‮fdp.exe\\""\n'
    )
    findings = mmp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[mmp.Finding]:
    return [f for f in mmp.scan_text(text) if f.rule_id == rule_id]


# ---------- M1 : mime-boundary-attacker-controlled -----------------------


def test_m1_positive_python_set_boundary_from_request() -> None:
    """Python set_boundary called on attacker-controlled value flags."""
    src = (
        "from email.mime.multipart import MIMEMultipart\n"
        "msg = MIMEMultipart()\n"
        "msg.set_boundary(request.json['boundary'])\n"
    )
    hits = _hits("mime-boundary-attacker-controlled", src)
    assert len(hits) >= 1


def test_m1_negative_hardcoded_boundary_constant() -> None:
    """Hardcoded boundary string from a module constant must NOT flag."""
    src = (
        "BOUNDARY = '----=_TestFixture-1234'\n"
        "msg = MIMEMultipart()\n"
        "msg.set_boundary(BOUNDARY)\n"
    )
    assert _hits("mime-boundary-attacker-controlled", src) == []


def test_m1_positive_node_boundary_field_from_req_body() -> None:
    """Node nodemailer sendMail({ boundary: req.body.boundary }) flags."""
    src = (
        "transporter.sendMail({\n"
        "  boundary: req.body.boundary,\n"
        "  html: userHtml,\n"
        "});\n"
    )
    hits = _hits("mime-boundary-attacker-controlled", src)
    assert len(hits) >= 1


# ---------- M2 : mime-attachment-double-extension-rce --------------------


def test_m2_positive_double_extension_literal_pdf_exe() -> None:
    """A filename literal `something.pdf.exe` flags as double-extension."""
    src = 'attachments: [{filename: "Q3-report.pdf.exe", data: buf}]\n'
    hits = _hits("mime-attachment-double-extension-rce", src)
    assert len(hits) >= 1


def test_m2_negative_single_extension_pdf() -> None:
    """A plain `.pdf` filename literal must NOT flag."""
    src = 'attachments: [{filename: "Q3-report.pdf", data: buf}]\n'
    assert _hits("mime-attachment-double-extension-rce", src) == []


def test_m2_positive_get_filename_paired_with_write() -> None:
    """get_filename() output piped into open().write() flags."""
    src = (
        "for part in msg.iter_attachments():\n"
        "    fname = part.get_filename()\n"
        "    with open(os.path.join(SPOOL, fname), 'wb') as f:\n"
        "        f.write(part.get_payload(decode=True))\n"
    )
    hits = _hits("mime-attachment-double-extension-rce", src)
    assert len(hits) >= 1


# ---------- M3 : mime-smime-chain-only-no-signature-verify ---------------


def test_m3_positive_chain_only_no_signed_data() -> None:
    """verify_chain WITHOUT verify_signed_data nearby flags."""
    src = (
        "certs = pkcs7.load_der_pkcs7_certificates(sig_blob)\n"
        "for cert in certs:\n"
        "    verify_chain(cert, trust_store)\n"
        "accept_message(body)\n"
    )
    hits = _hits("mime-smime-chain-only-no-signature-verify", src)
    assert len(hits) >= 1


def test_m3_negative_chain_and_signed_data_both_verified() -> None:
    """Chain verify accompanied by signed-data verify must NOT flag."""
    src = (
        "verify_chain(cert, trust_store)\n"
        "verify_signed_data(sig, body, cert.public_key())\n"
        "accept_message(body)\n"
    )
    assert _hits("mime-smime-chain-only-no-signature-verify", src) == []


# ---------- M4 : mime-parser-no-strict-policy ----------------------------


def test_m4_positive_bytesparser_without_policy() -> None:
    """BytesParser() instantiated without policy= flags."""
    src = (
        "from email.parser import BytesParser\n"
        "msg = BytesParser().parsebytes(raw)\n"
        "subj = msg['Subject']\n"
    )
    hits = _hits("mime-parser-no-strict-policy", src)
    assert len(hits) >= 1


def test_m4_negative_bytesparser_with_default_policy() -> None:
    """BytesParser(policy=policy.default) must NOT flag (same-file marker)."""
    src = (
        "from email.parser import BytesParser\n"
        "from email import policy\n"
        "msg = BytesParser(policy=policy.default).parsebytes(raw)\n"
    )
    assert _hits("mime-parser-no-strict-policy", src) == []


# ---------- M5 : mime-attachment-filename-rtlo-bidi ----------------------


def test_m5_positive_filename_with_rtlo_codepoint() -> None:
    """Filename literal containing U+202E (RTLO) flags."""
    # The U+202E (RTLO) character makes "invoiceexe.pdf" appear in UI
    # but the on-disk file is "invoice<RTLO>fdp.exe".
    src = 'attach = {"filename": "invoice‮fdp.exe", "data": buf}\n'
    hits = _hits("mime-attachment-filename-rtlo-bidi", src)
    assert len(hits) >= 1


def test_m5_negative_plain_ascii_filename() -> None:
    """A plain ASCII filename without bidi codepoints must NOT flag."""
    src = 'attach = {"filename": "regular-document.pdf", "data": buf}\n'
    assert _hits("mime-attachment-filename-rtlo-bidi", src) == []


# ---------- M6 : mime-ics-method-request-no-sender-verify ----------------


def test_m6_positive_from_ical_no_sender_check() -> None:
    """Calendar.from_ical with no sender-trust marker nearby flags."""
    src = (
        "from icalendar import Calendar\n"
        "cal = Calendar.from_ical(request.body)\n"
        "for event in cal.walk('VEVENT'):\n"
        "    if cal['method'] == 'REQUEST':\n"
        "        calendar_api.create_event(event)\n"
    )
    hits = _hits("mime-ics-method-request-no-sender-verify", src)
    assert len(hits) >= 1


def test_m6_negative_from_ical_with_sender_allowlist() -> None:
    """Calendar.from_ical with sender allowlist nearby must NOT flag."""
    src = (
        "from icalendar import Calendar\n"
        "cal = Calendar.from_ical(request.body)\n"
        "if sender not in ALLOWED_SENDERS:\n"
        "    abort(403)\n"
        "for event in cal.walk('VEVENT'):\n"
        "    calendar_api.create_event(event)\n"
    )
    assert _hits("mime-ics-method-request-no-sender-verify", src) == []


# ---------- M7 : mime-custom-header-crlf-injection -----------------------


def test_m7_positive_node_x_header_from_req_body() -> None:
    """nodemailer custom X-header from req.body flags."""
    src = (
        "await transporter.sendMail({\n"
        "  to: recipient,\n"
        "  headers: {\n"
        "    'X-Original-Subject': req.body.subj,\n"
        "  },\n"
        "  text: '...'\n"
        "});\n"
    )
    hits = _hits("mime-custom-header-crlf-injection", src)
    assert len(hits) >= 1


def test_m7_negative_node_x_header_static_literal() -> None:
    """nodemailer custom X-header with static value must NOT flag."""
    src = (
        "await transporter.sendMail({\n"
        "  headers: {\n"
        "    'X-Mailer': 'production-bot-v1.2',\n"
        "  },\n"
        "  text: '...'\n"
        "});\n"
    )
    assert _hits("mime-custom-header-crlf-injection", src) == []


def test_m7_positive_python_msg_x_header_from_form() -> None:
    """Python msg['X-...'] = request.form[...] flags."""
    src = (
        "msg = MIMEText(body)\n"
        "msg['X-Original-Subject'] = request.form['subj']\n"
    )
    hits = _hits("mime-custom-header-crlf-injection", src)
    assert len(hits) >= 1


# ---------- M8 : mime-attachment-payload-insecure-deserialize -----------


def test_m8_positive_pickle_loads_on_part_payload() -> None:
    """pickle.loads on part.get_payload() flags."""
    src = (
        "msg = email.message_from_bytes(raw)\n"
        "for part in msg.iter_attachments():\n"
        "    payload = pickle.loads(part.get_payload(decode=True))\n"
    )
    hits = _hits("mime-attachment-payload-insecure-deserialize", src)
    assert len(hits) >= 1


def test_m8_negative_pickle_loads_on_local_bytes() -> None:
    """pickle.loads on a non-email local variable must NOT flag."""
    src = (
        "with open('/etc/cache/state.pkl', 'rb') as f:\n"
        "    state_bytes = f.read()\n"
        "config = pickle.loads(state_bytes)\n"
    )
    assert _hits("mime-attachment-payload-insecure-deserialize", src) == []


def test_m8_positive_msgpack_unpackb_on_attachment() -> None:
    """msgpack.unpackb on attachment payload flags."""
    src = (
        "for part in msg.iter_attachments():\n"
        "    if part.get_content_type() == 'application/x-msgpack':\n"
        "        payload = msgpack.unpackb(part.get_payload(decode=True))\n"
    )
    hits = _hits("mime-attachment-payload-insecure-deserialize", src)
    assert len(hits) >= 1
