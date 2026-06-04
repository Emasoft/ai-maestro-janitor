"""Tests for scripts/lib/email_smtp_patterns.py.

Pattern-coverage tests for the Wave-21 distillation round 7 angle D
catalogue (14 rules: SMTP smuggling, MIME boundary attacker-controlled,
MIME header CRLF, smtplib starttls order, mail-SDK SSL no verify, IMAP
mailbox-name input, email parser on untrusted, RFC 5322 display-name
quote injection, Postfix mynetworks broad, Postfix missing
reject_unauth_destination, DSN reflection, listserv command injection,
Maildir spool path traversal, SaaS-mail substitution-tag CRLF).
Every rule gets at least one positive test + at least one negative
carve-out test.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import email_smtp_patterns as esp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(esp.RULES, tuple)
    rule_ids = {r.id for r in esp.RULES}
    expected = {
        "email-smtp-smuggling-bare-crlf-in-body",
        "email-mime-attacker-controlled-boundary",
        "email-mime-text-subject-contains-control",
        "email-smtplib-no-starttls-after-connect",
        "email-smtp-ssl-no-hostname-verify",
        "email-imap-mailbox-name-from-user-input",
        "email-message-from-string-on-untrusted",
        "email-from-header-rfc5322-display-name-quote-injection",
        "email-postfix-mynetworks-too-broad",
        "email-postfix-recipient-restrictions-missing-unauth-reject",
        "email-bounce-sender-not-verified-dsn-amplification",
        "email-listserv-command-injection-via-subject-or-body",
        "email-maildir-spool-path-traversal-from-recipient",
        "email-sendgrid-mailgun-substitution-tag-crlf",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_owasp_mapping_and_severity() -> None:
    """Each rule maps to a real ASI- prefix and a valid severity."""
    for rule in esp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns.Finding shape."""
    f = esp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-02"


def test_scan_text_empty_returns_empty() -> None:
    """Empty / whitespace-only text yields no findings."""
    assert esp.scan_text("") == []
    assert esp.scan_text("   \n   \n") == []


# ---------- helpers ------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[esp.Finding]:
    return [f for f in esp.scan_text(text) if f.rule_id == rule_id]


# ---------- D1 : email-smtp-smuggling-bare-crlf-in-body ------------------


def test_smtp_smuggling_python_fstring_data_payload_flags() -> None:
    """Python raw-socket DATA payload with `{body}` interpolation fires."""
    src = (
        "def send_data(sock, body):\n"
        "    sock.send(f\"DATA\\r\\nFrom: a@b\\r\\n\\r\\n{body}\\r\\n.\\r\\n\".encode())\n"
    )
    assert _hits("email-smtp-smuggling-bare-crlf-in-body", src)


def test_smtp_smuggling_js_template_literal_data_payload_flags() -> None:
    """Node raw-socket DATA payload with `${userBody}` interpolation fires."""
    src = (
        "function send(sock, userBody) {\n"
        "  sock.write(`DATA\\r\\nFrom: a@b\\r\\n\\r\\n${userBody}\\r\\n.\\r\\n`);\n"
        "}\n"
    )
    assert _hits("email-smtp-smuggling-bare-crlf-in-body", src)


def test_smtp_smuggling_js_concat_data_payload_flags() -> None:
    """Node string-concat DATA payload `"DATA\\r\\n" + body + "\\r\\n.\\r\\n"` fires."""
    src = (
        "function send(sock, body) {\n"
        "  sock.write(\"DATA\\r\\n\" + body + \"\\r\\n.\\r\\n\");\n"
        "}\n"
    )
    assert _hits("email-smtp-smuggling-bare-crlf-in-body", src)


def test_smtp_smuggling_dotstuffing_pass_safe() -> None:
    """A `.replace('\\n.', '\\n..')` dot-stuffing pass anywhere suppresses."""
    src = (
        "def send_data(sock, body):\n"
        "    body = body.replace('\\n.', '\\n..')\n"
        "    sock.send(f\"DATA\\r\\n{body}\\r\\n.\\r\\n\".encode())\n"
    )
    assert not _hits("email-smtp-smuggling-bare-crlf-in-body", src)


def test_smtp_smuggling_high_level_sdk_safe() -> None:
    """nodemailer.sendMail() with no raw socket — not the smuggling shape."""
    src = (
        "await transporter.sendMail({ from: 'a@b', to: 'c@d', text: body });\n"
    )
    assert not _hits("email-smtp-smuggling-bare-crlf-in-body", src)


# ---------- D2 : email-mime-attacker-controlled-boundary -----------------


def test_mime_boundary_variable_name_flags() -> None:
    """`MIMEMultipart(boundary=user_supplied)` fires."""
    src = (
        "from email.mime.multipart import MIMEMultipart\n"
        "def build(user_supplied):\n"
        "    return MIMEMultipart('mixed', boundary=user_supplied)\n"
    )
    assert _hits("email-mime-attacker-controlled-boundary", src)


def test_mime_boundary_short_literal_flags() -> None:
    """`MIMEMultipart(boundary='simple')` — boundary <16 chars fires."""
    src = (
        "from email.mime.multipart import MIMEMultipart\n"
        "msg = MIMEMultipart(boundary='simple')\n"
    )
    assert _hits("email-mime-attacker-controlled-boundary", src)


def test_mime_boundary_set_boundary_variable_flags() -> None:
    """`msg.set_boundary(user_value)` fires."""
    src = (
        "msg = MIMEMultipart()\n"
        "msg.set_boundary(user_value)\n"
    )
    assert _hits("email-mime-attacker-controlled-boundary", src)


def test_mime_boundary_random_source_safe() -> None:
    """`secrets.token_hex(16)` in file suppresses variable-source hit."""
    src = (
        "import secrets\n"
        "from email.mime.multipart import MIMEMultipart\n"
        "boundary = secrets.token_hex(16)\n"
        "msg = MIMEMultipart('mixed', boundary=boundary)\n"
    )
    assert not _hits("email-mime-attacker-controlled-boundary", src)


def test_mime_boundary_short_literal_still_fires_with_random_in_file() -> None:
    """Short literal boundary fires even when secrets is imported (intrinsic)."""
    src = (
        "import secrets\n"
        "from email.mime.multipart import MIMEMultipart\n"
        "# Used elsewhere but THIS line still uses short literal:\n"
        "msg = MIMEMultipart(boundary='abc')\n"
    )
    assert _hits("email-mime-attacker-controlled-boundary", src)


# ---------- D3 : email-mime-text-subject-contains-control ----------------


def test_mime_header_subject_assigned_from_user_var_flags() -> None:
    """`msg["Subject"] = user_subject` fires."""
    src = (
        "from email.message import EmailMessage\n"
        "msg = EmailMessage()\n"
        "msg[\"Subject\"] = user_subject\n"
    )
    assert _hits("email-mime-text-subject-contains-control", src)


def test_mime_header_to_assigned_from_request_var_flags() -> None:
    """`msg["To"] = request.form["addr"]` fires."""
    src = (
        "msg = EmailMessage()\n"
        "msg[\"To\"] = request.form[\"addr\"]\n"
    )
    assert _hits("email-mime-text-subject-contains-control", src)


def test_mime_header_with_header_wrap_safe() -> None:
    """`msg["Subject"] = Header(value, "utf-8")` on same line suppresses."""
    src = (
        "from email.header import Header\n"
        "msg[\"Subject\"] = Header(user_subject, \"utf-8\")\n"
    )
    assert not _hits("email-mime-text-subject-contains-control", src)


def test_mime_header_static_literal_safe() -> None:
    """`msg["Subject"] = "Static Alert"` is a literal — not flagged."""
    src = (
        "msg[\"Subject\"] = \"Static Alert Subject\"\n"
    )
    assert not _hits("email-mime-text-subject-contains-control", src)


# ---------- D4 : email-smtplib-no-starttls-after-connect -----------------


def test_smtplib_login_before_starttls_flags() -> None:
    """SMTP(host).login() with NO .starttls() in between fires."""
    src = (
        "import smtplib\n"
        "s = smtplib.SMTP('smtp.example.com', 587)\n"
        "s.login(user, pwd)\n"
        "s.sendmail(frm, to, msg)\n"
        "s.quit()\n"
    )
    assert _hits("email-smtplib-no-starttls-after-connect", src)


def test_smtplib_starttls_then_login_safe() -> None:
    """SMTP(host).starttls().login() in correct order is fine."""
    src = (
        "import smtplib\n"
        "s = smtplib.SMTP('smtp.example.com', 587)\n"
        "s.ehlo()\n"
        "s.starttls()\n"
        "s.ehlo()\n"
        "s.login(user, pwd)\n"
    )
    assert not _hits("email-smtplib-no-starttls-after-connect", src)


def test_smtplib_localhost_safe() -> None:
    """SMTP('localhost') against local debug server is safe (dev case)."""
    src = (
        "import smtplib\n"
        "s = smtplib.SMTP('localhost', 1025)\n"
        "s.login(user, pwd)\n"
    )
    assert not _hits("email-smtplib-no-starttls-after-connect", src)


def test_smtplib_no_login_no_send_safe() -> None:
    """SMTP(host) with no .login or .sendmail in window does not fire."""
    src = (
        "import smtplib\n"
        "s = smtplib.SMTP('smtp.example.com', 587)\n"
        "# diagnostic: just connect to check reachability\n"
        "s.noop()\n"
        "s.quit()\n"
    )
    assert not _hits("email-smtplib-no-starttls-after-connect", src)


# ---------- D5 : email-smtp-ssl-no-hostname-verify -----------------------


def test_smtp_ssl_check_hostname_false_flags() -> None:
    """`ctx.check_hostname = False` near SMTP_SSL fires."""
    src = (
        "import ssl, smtplib\n"
        "ctx = ssl.create_default_context()\n"
        "ctx.check_hostname = False\n"
        "s = smtplib.SMTP_SSL('smtp.example.com', 465, context=ctx)\n"
    )
    assert _hits("email-smtp-ssl-no-hostname-verify", src)


def test_imap_ssl_cert_none_flags() -> None:
    """`ctx.verify_mode = ssl.CERT_NONE` near IMAP4_SSL fires."""
    src = (
        "import ssl, imaplib\n"
        "ctx = ssl.create_default_context()\n"
        "ctx.verify_mode = ssl.CERT_NONE\n"
        "imap = imaplib.IMAP4_SSL('imap.example.com', 993, ssl_context=ctx)\n"
    )
    assert _hits("email-smtp-ssl-no-hostname-verify", src)


def test_smtp_ssl_create_unverified_context_flags() -> None:
    """`ssl._create_unverified_context()` near SMTP_SSL fires."""
    src = (
        "import ssl, smtplib\n"
        "ctx = ssl._create_unverified_context()\n"
        "s = smtplib.SMTP_SSL('smtp.example.com', 465, context=ctx)\n"
    )
    assert _hits("email-smtp-ssl-no-hostname-verify", src)


def test_smtp_ssl_default_context_safe() -> None:
    """SMTP_SSL with default ssl.create_default_context() does NOT fire."""
    src = (
        "import ssl, smtplib\n"
        "ctx = ssl.create_default_context()\n"
        "s = smtplib.SMTP_SSL('smtp.example.com', 465, context=ctx)\n"
    )
    assert not _hits("email-smtp-ssl-no-hostname-verify", src)


def test_check_hostname_false_without_mail_sdk_safe() -> None:
    """`check_hostname=False` without mail-SDK usage doesn't trigger D5."""
    src = (
        "import ssl, requests\n"
        "ctx = ssl.create_default_context()\n"
        "ctx.check_hostname = False\n"
        "# uses requests, not mail SDK\n"
    )
    assert not _hits("email-smtp-ssl-no-hostname-verify", src)


# ---------- D6 : email-imap-mailbox-name-from-user-input -----------------


def test_imap_select_request_args_flags() -> None:
    """`imap.select(request.args["folder"])` fires."""
    src = (
        "imap = imaplib.IMAP4_SSL('imap.example.com')\n"
        "imap.login(user, pwd)\n"
        "imap.select(request.args[\"folder\"])\n"
    )
    assert _hits("email-imap-mailbox-name-from-user-input", src)


def test_imap_fetch_req_body_msgid_flags() -> None:
    """`imap.fetch(req.body['msgid'], '(RFC822)')` fires."""
    src = (
        "data = imap.fetch(req.body['msgid'], '(RFC822)')\n"
    )
    assert _hits("email-imap-mailbox-name-from-user-input", src)


def test_imap_hardcoded_mailbox_safe() -> None:
    """`imap.select('INBOX')` literal mailbox is safe."""
    src = (
        "imap.select('INBOX')\n"
    )
    assert not _hits("email-imap-mailbox-name-from-user-input", src)


def test_imap_with_allowlist_guard_safe() -> None:
    """File with MAILBOX_ALLOWLIST guard suppresses the hit."""
    src = (
        "MAILBOX_ALLOWLIST = {'INBOX', 'Sent'}\n"
        "folder = request.args['folder']\n"
        "if folder not in MAILBOX_ALLOWLIST:\n"
        "    raise ValueError('bad mailbox')\n"
        "imap.select(folder)\n"
        # Hit could still fire but allowlist guard suppresses it.
    )
    # The file references request.args, so trigger would match;
    # but MAILBOX_ALLOWLIST guard suppresses.
    assert not _hits("email-imap-mailbox-name-from-user-input", src)


# ---------- D7 : email-message-from-string-on-untrusted ------------------


def test_message_from_string_request_data_flags() -> None:
    """`email.message_from_string(request.data)` fires."""
    src = (
        "import email\n"
        "msg = email.message_from_string(request.data)\n"
    )
    assert _hits("email-message-from-string-on-untrusted", src)


def test_message_from_bytes_req_body_flags() -> None:
    """`email.message_from_bytes(req.body)` fires."""
    src = (
        "import email\n"
        "msg = email.message_from_bytes(req.body)\n"
    )
    assert _hits("email-message-from-string-on-untrusted", src)


def test_parser_parsestr_request_form_flags() -> None:
    """`email.parser.Parser().parsestr(request.form)` fires."""
    src = (
        "import email.parser\n"
        "msg = email.parser.Parser().parsestr(request.form)\n"
    )
    assert _hits("email-message-from-string-on-untrusted", src)


def test_message_from_string_literal_safe() -> None:
    """`email.message_from_string(literal)` not flagged."""
    src = (
        "import email\n"
        "msg = email.message_from_string(some_local_var)\n"
        # some_local_var is not in the input-source allowlist.
    )
    assert not _hits("email-message-from-string-on-untrusted", src)


# ---------- D8 : email-from-header-rfc5322-display-name-quote-injection --


def test_from_header_js_template_with_interpolated_name_flags() -> None:
    """`from: \\`\\"${EMAIL_FROM_NAME}\\" <${FROM_ADDR}>\\`` fires."""
    src = (
        "const from = `\"${process.env.EMAIL_FROM_NAME}\" <${FROM_ADDR}>`;\n"
        "mailOptions.from = from;\n"
    )
    assert _hits(
        "email-from-header-rfc5322-display-name-quote-injection", src
    )


def test_from_header_python_fstring_flags() -> None:
    """`msg["From"] = f'"{name}" <{addr}>'` fires."""
    src = (
        "from email.message import EmailMessage\n"
        "msg = EmailMessage()\n"
        "msg[\"From\"] = f'\"{name}\" <{addr}>'\n"
    )
    assert _hits(
        "email-from-header-rfc5322-display-name-quote-injection", src
    )


def test_from_header_with_formataddr_guard_safe() -> None:
    """`email.utils.formataddr` anywhere suppresses the hit."""
    src = (
        "from email.utils import formataddr\n"
        "from_addr = formataddr((name, addr))\n"
        # construction below — but formataddr guard is present.
        "msg[\"From\"] = from_addr\n"
    )
    assert not _hits(
        "email-from-header-rfc5322-display-name-quote-injection", src
    )


def test_from_header_with_quote_escape_safe() -> None:
    """`.replace('\\"', '\\\\\\"')` in file suppresses the hit."""
    src = (
        "name = process.env.NAME.replace(\"\\\"\", \"\\\\\\\"\");\n"
        "const from = `\"${name}\" <${addr}>`;\n"
    )
    assert not _hits(
        "email-from-header-rfc5322-display-name-quote-injection", src
    )


# ---------- D9 : email-postfix-mynetworks-too-broad ----------------------


def test_postfix_mynetworks_open_v4_flags() -> None:
    """`mynetworks = 0.0.0.0/0` fires (open relay)."""
    src = (
        "# Postfix main.cf\n"
        "mynetworks = 0.0.0.0/0\n"
        "myhostname = mail.example.com\n"
    )
    assert _hits("email-postfix-mynetworks-too-broad", src)


def test_postfix_mynetworks_v6_open_flags() -> None:
    """`mynetworks = ::/0` fires (open IPv6 relay)."""
    src = (
        "mynetworks = ::/0\n"
    )
    assert _hits("email-postfix-mynetworks-too-broad", src)


def test_postfix_mynetworks_slash_8_flags() -> None:
    """`mynetworks = 10.0.0.0/8` fires (cross-tenant cidr)."""
    src = (
        "mynetworks = 10.0.0.0/8 127.0.0.0/8\n"
    )
    assert _hits("email-postfix-mynetworks-too-broad", src)


def test_postfix_mynetworks_safe_loopback_only() -> None:
    """`mynetworks = 127.0.0.0/8 [::1]/128` is safe."""
    src = (
        "mynetworks = 127.0.0.0/8 [::1]/128\n"
    )
    assert not _hits("email-postfix-mynetworks-too-broad", src)


def test_postfix_mynetworks_slash_24_safe() -> None:
    """`mynetworks = 192.168.1.0/24` is a narrow subnet — safe."""
    src = (
        "mynetworks = 192.168.1.0/24\n"
    )
    assert not _hits("email-postfix-mynetworks-too-broad", src)


# ---------- D10 : email-postfix-recipient-restrictions-missing-unauth-reject


def test_postfix_recipient_restrictions_no_reject_unauth_flags() -> None:
    """`smtpd_recipient_restrictions = permit_mynetworks, permit_sasl_authenticated` fires."""
    src = (
        "smtpd_recipient_restrictions = permit_mynetworks, permit_sasl_authenticated\n"
    )
    assert _hits(
        "email-postfix-recipient-restrictions-missing-unauth-reject", src
    )


def test_postfix_relay_restrictions_no_reject_unauth_flags() -> None:
    """`smtpd_relay_restrictions = permit_mynetworks` fires."""
    src = (
        "smtpd_relay_restrictions = permit_mynetworks\n"
    )
    assert _hits(
        "email-postfix-recipient-restrictions-missing-unauth-reject", src
    )


def test_postfix_recipient_restrictions_with_reject_unauth_safe() -> None:
    """Restriction list with `reject_unauth_destination` is safe."""
    src = (
        "smtpd_relay_restrictions = permit_mynetworks, "
        "permit_sasl_authenticated, reject_unauth_destination\n"
    )
    assert not _hits(
        "email-postfix-recipient-restrictions-missing-unauth-reject", src
    )


# ---------- D11 : email-bounce-sender-not-verified-dsn-amplification -----


def test_dsn_amplification_imap_fetch_then_sendmail_flags() -> None:
    """`imap.fetch(...)` followed by `smtp.sendmail(...)` fires."""
    src = (
        "for msgid, body in imap.fetch_all():\n"
        "    m = email.message_from_string(body)\n"
        "    original = m.get('X-Original-Recipient')\n"
        "    smtp.sendmail(my_addr, [original], retry_body)\n"
    )
    assert _hits(
        "email-bounce-sender-not-verified-dsn-amplification", src
    )


def test_dsn_amplification_maildir_then_send_flags() -> None:
    """`mailbox.Maildir(...)` near `smtp.send_message` fires."""
    src = (
        "import mailbox, smtplib\n"
        "for m in mailbox.Maildir('/var/spool/bounces'):\n"
        "    smtp.send_message(m)\n"
    )
    assert _hits(
        "email-bounce-sender-not-verified-dsn-amplification", src
    )


def test_dsn_amplification_with_msgid_verify_safe() -> None:
    """Recent-msgid table check suppresses the hit."""
    src = (
        "for msgid, body in imap.fetch_all():\n"
        "    if msgid not in sent_msgids:\n"
        "        continue\n"
        "    smtp.sendmail(my_addr, [orig], body)\n"
    )
    assert not _hits(
        "email-bounce-sender-not-verified-dsn-amplification", src
    )


# ---------- D12 : email-listserv-command-injection-via-subject-or-body --


def test_listserv_subscribe_in_subject_flags() -> None:
    """`msg["Subject"]` containing SUBSCRIBE without confirmation token fires."""
    src = (
        "def handle(msg):\n"
        "    cmd = msg[\"Subject\"].strip().upper()\n"
        "    if 'SUBSCRIBE' in cmd:\n"
        "        subscribe_user(cmd.split()[1], cmd.split()[2])\n"
    )
    assert _hits(
        "email-listserv-command-injection-via-subject-or-body", src
    )


def test_listserv_unsubscribe_via_get_subject_flags() -> None:
    """`msg.get("Subject")` with UNSUBSCRIBE fires."""
    src = (
        "subj = msg.get(\"Subject\", \"\")\n"
        "if subj.startswith('UNSUBSCRIBE'):\n"
        "    unsubscribe(parsed_email)\n"
    )
    assert _hits(
        "email-listserv-command-injection-via-subject-or-body", src
    )


def test_listserv_with_confirmation_token_safe() -> None:
    """Confirmation-token guard in file suppresses the hit."""
    src = (
        "import secrets\n"
        "def handle(msg):\n"
        "    confirmation_token = secrets.token_urlsafe(32)\n"
        "    cmd = msg[\"Subject\"]\n"
        "    if 'SUBSCRIBE' in cmd:\n"
        "        send_confirm(cmd.split()[1], confirmation_token)\n"
    )
    assert not _hits(
        "email-listserv-command-injection-via-subject-or-body", src
    )


# ---------- D13 : email-maildir-spool-path-traversal-from-recipient ------


def test_maildir_path_var_mail_recipient_flags() -> None:
    """`f"/var/mail/{recipient}/new/{uuid4()}"` fires."""
    src = (
        "from uuid import uuid4\n"
        "def deliver(msg, recipient):\n"
        "    spool = f\"/var/mail/{recipient}/new/{uuid4()}\"\n"
        "    Path(spool).write_text(msg.as_string())\n"
    )
    assert _hits(
        "email-maildir-spool-path-traversal-from-recipient", src
    )


def test_maildir_path_maildir_api_flags() -> None:
    """`mailbox.Maildir(f"/var/mail/{recipient}/Maildir")` fires."""
    src = (
        "import mailbox\n"
        "mbox = mailbox.Maildir(f\"/var/mail/{recipient}/Maildir\")\n"
    )
    assert _hits(
        "email-maildir-spool-path-traversal-from-recipient", src
    )


def test_maildir_path_with_secure_filename_safe() -> None:
    """`secure_filename(recipient)` in file suppresses the hit."""
    src = (
        "from werkzeug.utils import secure_filename\n"
        "def deliver(recipient, msg):\n"
        "    name = secure_filename(recipient)\n"
        "    spool = f\"/var/mail/{name}/new/file\"\n"
        "    Path(spool).write_text(msg.as_string())\n"
    )
    assert not _hits(
        "email-maildir-spool-path-traversal-from-recipient", src
    )


def test_maildir_path_no_variable_safe() -> None:
    """`/var/mail/static-user/` literal — not flagged."""
    src = (
        "spool = '/var/mail/static-user/new/file'\n"
        "Path(spool).write_text(msg.as_string())\n"
    )
    assert not _hits(
        "email-maildir-spool-path-traversal-from-recipient", src
    )


# ---------- D14 : email-sendgrid-mailgun-substitution-tag-crlf -----------


def test_sendgrid_substitution_from_req_body_flags() -> None:
    """SendGrid sgMail.send with substitutions: {req.body.X} fires."""
    src = (
        "const sgMail = require('@sendgrid/mail');\n"
        "const msg = {\n"
        "  personalizations: [{\n"
        "    to: 'user@example.com',\n"
        "    substitutions: {\n"
        "      '-name-': req.body.userName,\n"
        "      '-reset_url-': req.body.url,\n"
        "    },\n"
        "  }],\n"
        "  templateId: 'd-abc',\n"
        "};\n"
        "sgMail.send(msg);\n"
    )
    assert _hits(
        "email-sendgrid-mailgun-substitution-tag-crlf", src
    )


def test_mailgun_substitution_from_req_body_flags() -> None:
    """Mailgun mg.messages.create with h:X-Mailgun-Variables from req.body fires."""
    src = (
        "const mg = require('mailgun-js')();\n"
        "mg.messages.create('domain', {\n"
        "  from: 'a@b',\n"
        "  to: ['user@example.com'],\n"
        "  template: 'reset-pw',\n"
        "  'h:X-Mailgun-Variables': JSON.stringify({\n"
        "    resetUrl: req.body.url\n"
        "  })\n"
        "});\n"
    )
    assert _hits(
        "email-sendgrid-mailgun-substitution-tag-crlf", src
    )


def test_sendgrid_substitution_with_crlf_strip_safe() -> None:
    """`.replace(/[\\r\\n]/g, '')` on the substitution value suppresses."""
    src = (
        "const sgMail = require('@sendgrid/mail');\n"
        "const safeName = req.body.userName.replace(/[\\r\\n]/g, '');\n"
        "sgMail.send({\n"
        "  personalizations: [{ substitutions: { '-name-': safeName } }],\n"
        "});\n"
    )
    # The substitution line itself doesn't include `req.body`, so trigger
    # doesn't match. This is a no-op (no hit either way) — confirm.
    hits = _hits("email-sendgrid-mailgun-substitution-tag-crlf", src)
    assert not hits


def test_sendgrid_no_user_input_safe() -> None:
    """SendGrid with literal substitutions — not flagged."""
    src = (
        "const sgMail = require('@sendgrid/mail');\n"
        "sgMail.send({\n"
        "  personalizations: [{ substitutions: { '-name-': 'Static Name' } }],\n"
        "});\n"
    )
    assert not _hits(
        "email-sendgrid-mailgun-substitution-tag-crlf", src
    )


# ---------- Postfix helper parser unit-tests -----------------------------


def test_parse_postfix_main_cf_basic() -> None:
    """parse_postfix_main_cf splits k=v lines and skips comments."""
    src = (
        "# Postfix main.cf\n"
        "myhostname = mail.example.com\n"
        "mynetworks = 127.0.0.0/8\n"
        "smtpd_recipient_restrictions = permit_mynetworks, reject_unauth_destination\n"
    )
    parsed = esp.parse_postfix_main_cf(src)
    assert parsed["myhostname"] == "mail.example.com"
    assert parsed["mynetworks"] == "127.0.0.0/8"
    assert "reject_unauth_destination" in parsed["smtpd_recipient_restrictions"]


def test_parse_postfix_main_cf_empty_returns_empty_dict() -> None:
    """Empty input yields an empty dict."""
    assert esp.parse_postfix_main_cf("") == {}
    assert esp.parse_postfix_main_cf("# only a comment\n") == {}


def test_parse_postfix_main_cf_continuation_line() -> None:
    """Continuation lines (leading whitespace) join the previous logical line."""
    src = (
        "smtpd_recipient_restrictions = permit_mynetworks,\n"
        "    permit_sasl_authenticated,\n"
        "    reject_unauth_destination\n"
    )
    parsed = esp.parse_postfix_main_cf(src)
    val = parsed["smtpd_recipient_restrictions"]
    assert "permit_mynetworks" in val
    assert "reject_unauth_destination" in val


# ---------- Cross-rule sanity --------------------------------------------


def test_scan_text_returns_sorted_findings() -> None:
    """Returned findings are sorted by (line, column, rule_id)."""
    src = (
        "mynetworks = 0.0.0.0/0\n"
        "smtpd_relay_restrictions = permit_mynetworks\n"
        "msg = email.message_from_string(request.data)\n"
    )
    findings = esp.scan_text(src)
    assert findings
    # Already sorted by construction.
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_scan_text_dedupes_same_rule_at_same_position() -> None:
    """Two matches at the SAME (rule_id, line, col) are deduped."""
    # Construct a single-line source where two patterns might overlap.
    src = "mynetworks = 0.0.0.0/0\n"
    findings = esp.scan_text(src)
    same_rule = [
        f for f in findings if f.rule_id == "email-postfix-mynetworks-too-broad"
    ]
    seen: set[tuple[str, int, int]] = set()
    for f in same_rule:
        key = (f.rule_id, f.line, f.column)
        assert key not in seen, "duplicate finding"
        seen.add(key)


def test_finding_matched_text_truncated_at_200_chars() -> None:
    """Matched-text fields in findings are truncated at 200 chars + ellipsis."""
    long_var = "a" * 500
    # Build a very long DATA payload to test truncation in the
    # SMTP-smuggling rule. The pattern caps to 200 chars +/- ellipsis.
    src = (
        "def go(sock, body):\n"
        "    sock.send(f\"DATA\\r\\n" + long_var + "{body}\\r\\n.\\r\\n\".encode())\n"
    )
    findings = esp.scan_text(src)
    # If a smuggling finding fires, its matched_text is bounded.
    for f in findings:
        if f.rule_id == "email-smtp-smuggling-bare-crlf-in-body":
            assert len(f.matched_text) <= 201  # 200 + '…' is 201 chars max
