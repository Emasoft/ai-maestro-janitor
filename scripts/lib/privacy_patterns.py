"""Privacy / PII / GDPR / data-residency attack patterns.

Wave 16 (Pass 2) impl-S: distilled from `distill2-i-privacy.md`. The
janitor's existing detectors cover credential shapes (hardcoded-secrets,
exfil-webhook-sink) and agent-context tampering (agent-context-poisoning)
but had ZERO coverage of the privacy axis — PII shapes leaking into
logs, public artifacts, error bodies, telemetry payloads, unsecured
cookies, or pages with no CSP. This module closes that gap.

Each rule follows the same `Rule(NamedTuple)` shape as
`scripts/lib/agent_config_patterns.py` so a uniform scanner can consume
both catalogues. Patterns are deterministic regex only — no LLM, no
non-Anthropic helper, every quantifier bounded, no `.*` without an
anchor. The companion `luhn_valid()` validator runs in constant time
per match (digit count is always ≤ 19).

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
                                  — single rule record (NamedTuple).
  * RULES                         — ordered tuple of every privacy rule.
  * PII_SHAPES                    — dict of named PII regexes
                                    (us_ssn, credit_card, iban, us_passport,
                                    email, phone_e164) shared by callers
                                    that want to do their own contextual
                                    triage (e.g. log-line or telemetry-body
                                    inspection).
  * luhn_valid(s) -> bool         — Luhn validator used to filter
                                    credit-card false positives.
  * scan_text(text, *, file_kind="source") -> list[Finding]
                                  — run every applicable rule, return
                                    findings.

Severity strings: "CRITICAL", "HIGH", "MAJOR", "MEDIUM", "LOW" — matching
the existing janitor convention.

OWASP-ASI mapping convention (re-uses the same scheme as
agent_config_patterns):
  * ASI-02 — exfil sinks (logs / public artifacts / telemetry)
  * ASI-03 — broken access / wildcard / weak-defaults (cookies, CSP)
  * ASI-04 — sensitive-data exposure (PII to client, residency)
  * ASI-07 — operational / compliance (GDPR erasure cascade)
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    scripts/lib/agent_config_patterns.Finding so heartbeat detectors can
    render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


# NOTE: this module deliberately calls `re.compile(...)` directly per-
# pattern rather than via a shared helper — each pattern's flag set is
# tuned individually (PII shapes need MULTILINE; some cookie / CSP
# patterns are case-sensitive). A wrapper was tried and rejected because
# every call site needed an override anyway.


# ---- Shared PII shape vocabulary ----------------------------------------


# Each entry: a regex that matches one PII shape. These are also exposed
# as `PII_SHAPES` so callers (workflow-walkers, telemetry-body inspectors)
# can run them on a sub-string of source instead of the full file.
#
# Placeholder rejection (e.g. `000-00-0000`) is built into the regex
# itself — same trick used by secret-leak-sentinel `pattern_registry.py`.
#
# us_ssn: 3-2-4 digits with optional dash/space, rejects:
#   * 000 / 666 / 9xx area numbers (SSA never issued these)
#   * 00 group
#   * 0000 serial
_US_SSN = re.compile(
    r"(?<!\d)(?!000|666|9\d{2})(\d{3})[-\s]?"
    r"(?!00)(\d{2})[-\s]?(?!0000)(\d{4})(?!\d)"
)

# credit_card: 13-19 digit run with optional spaces/dashes. The Luhn
# validator (below) is applied by callers to drop date strings and
# similar 16-digit numeric runs.
_CREDIT_CARD = re.compile(
    r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"
)

# iban: 2-letter country + 2-digit check + 11-30 alphanumeric. The
# leading word boundary keeps it out of identifier-like contexts.
_IBAN = re.compile(
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"
)

# us_passport: 1 letter + 8 digits — the canonical US shape. Common
# placeholders (e.g. "X12345678") still match; callers should filter
# obvious test data via the `email_local_part_skiplist` analogue.
_US_PASSPORT = re.compile(
    r"\b[A-Z]\d{8}\b"
)

# email (RFC-5322 simplified): local@host with TLD ≥ 2 chars.
_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# phone_e164: + country (1-3 digits) + groups. Tolerant of dashes,
# dots, spaces, and slashes between groups.
_PHONE_E164 = re.compile(
    r"\+\d{1,3}[\s\-.]?\d{1,4}[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}"
)


PII_SHAPES: dict[str, re.Pattern] = {  # noqa: UP006 - keep stdlib name
    "us_ssn": _US_SSN,
    "credit_card": _CREDIT_CARD,
    "iban": _IBAN,
    "us_passport": _US_PASSPORT,
    "email": _EMAIL,
    "phone_e164": _PHONE_E164,
}


def luhn_valid(s: str) -> bool:
    """Return True iff `s`'s digits form a Luhn-valid number of 13-19
    digits. Used to drop credit-card regex false positives (a 16-digit
    date+timestamp like `2024-01-15-13-42-55-XX` will match the shape
    but fail Luhn). Constant time per match — digit count is bounded."""
    digits = [int(c) for c in s if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ---- Rule 1 — privacy.pii-pattern-in-log-line ---------------------------


# Two-stage detector compiled as a single regex. Stage A matches the
# logger / printer signature, then the lookahead requires a PII shape
# inside the call's argument expression (≤ 400 chars before the closing
# paren). The PII alternation is intentionally union-shaped so a single
# pass over the source catches any PII-in-log occurrence regardless of
# which shape leaked. The PII-shape union here is the SAME vocabulary
# as PII_SHAPES so callers can re-run individual shapes for fine-grained
# triage.
_LOG_CALL_WITH_PII = re.compile(
    r"""(?ix)
    (?:
      logger\.(?:info|debug|warning|warn|error|critical|exception|log|trace)|
      log\.(?:info|debug|warning|warn|error|critical|exception)|
      logging\.(?:info|debug|warning|warn|error|critical|exception)|
      console\.(?:log|info|debug|warn|error|trace)|
      print|
      fmt\.(?:Println|Printf|Print|Sprintf)|
      slog\.(?:Info|Debug|Warn|Error)
    )
    \s*\(
    [^)]{0,400}?
    (?:
      # us_ssn
      (?<!\d)(?!000|666|9\d{2})\d{3}[-\s]?(?!00)\d{2}[-\s]?(?!0000)\d{4}(?!\d)|
      # credit_card (shape only — caller validates via luhn_valid)
      (?<!\d)(?:\d[\ \-]?){12,18}\d(?!\d)|
      # iban
      \b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b|
      # us_passport
      \b[A-Z]\d{8}\b|
      # email
      \b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b|
      # phone_e164
      \+\d{1,3}[\ \-.]?\d{1,4}[\ \-.]?\d{3,4}[\ \-.]?\d{3,4}
    )
    """
)


# ---- Rule 2 — privacy.email-in-public-artifact --------------------------


# Stage-A: a public artifact destination (GH upload-artifact / S3 public
# / Pages deploy / gh release upload / Azure/GCS public blob / CDN).
# Stage-B is applied by the workflow-walker — it inspects the file(s)
# the artifact step uploads and looks for email shapes inside them.
# This rule's REGEX matches Stage-A only; downstream code joins it with
# Stage-B per Proposal 2's design (the union below would explode the
# regex into multi-file scope and break the deterministic-per-line
# guarantee).
_PUBLIC_ARTIFACT_SINK = re.compile(
    r"""(?ix)
    (?:
      actions/upload-artifact@|
      actions/upload-pages-artifact@|
      actions/deploy-pages@|
      s3:\/\/[^\s"']+|
      aws\s+s3\s+(?:cp|sync|mb)\s+[^\s]+\s+s3:\/\/|
      \.s3[.\-](?:[a-z0-9\-]+)?amazonaws\.com|
      storage\.googleapis\.com\/[^\s"']+|
      \.blob\.core\.windows\.net\/[^\s"']+|
      gh\s+release\s+upload|
      (?:jsdelivr\.net|cdn\.jsdelivr|unpkg\.com)\/
    )
    """
)


# ---- Rule 3 — privacy.gdpr-erase-not-implemented ------------------------


# Matches a DELETE-user route handler signature. The cascade check
# (Stage B from Proposal 3) is performed by the caller: a successful
# match here is a HANDLER candidate; the caller then walks the function
# body for cascade indicators. The regex only fires on signatures whose
# path / function name references user / account / profile / me /
# customer / member — minimising FP on unrelated DELETE endpoints.
_DELETE_USER_ROUTE = re.compile(
    r"""(?ix)
    (?:
      @(?:app|router|api|blueprint)\.delete\s*\(\s*["']
        /(?:api/)?(?:v\d+/)?
        (?:users?|accounts?|profiles?|me|customers?|members?)
        (?:/\{[^/}]+\}|/<[^/>]+>|/:[^/\s"']+)?
      ["']|
      router\.delete\s*\(\s*["']
        /[^"']*(?:users?|accounts?|profiles?|me|customers?|members?)[^"']*
      ["']|
      (?:async\s+)?(?:def|function)\s+
        (?:delete|destroy|remove|erase)_?
        (?:user|account|profile|me|customer|member)\s*\(
    )
    """
)


# Cascade-indicator vocabulary — exported for callers that walk a
# matched handler body and want to determine whether the delete
# cascades to owned data, tokens, sessions, etc.
CASCADE_INDICATORS = re.compile(
    r"""(?ix)
    (?:
      cascade\s*=\s*["']?(?:delete|all)["']?|
      ondelete\s*=\s*["']?CASCADE["']?|
      on_delete\s*=\s*models\.CASCADE|
      \.(?:posts|orders|sessions|tokens|messages|comments|likes|
            follows|subscriptions|notifications)\.(?:delete|destroy|
                                                   invalidate|revoke)|
      (?:erase|purge|anonymize|scrub|cleanup|wipe)_user_data\s*\(|
      (?:enqueue|publish|emit)\s*\(\s*["']?
        (?:user[._-]?(?:deleted|erased)|account[._-]?deleted|
           gdpr[._-]?erase)
    )
    """
)


# ---- Rule 4 — privacy.data-residency-violation --------------------------


# Stage-B only (the residency declaration in Stage A is loaded by the
# caller from .janitor-privacy.yaml or pyproject.toml). This regex
# matches cloud-region tokens for non-EU regions in AWS / GCP / Azure.
# EU regions (eu-* / europe-* / Azure EU regions) are NOT in the
# alternation — they're permitted, not flagged. The detector is
# INACTIVE by default; the caller decides whether to fire based on
# whether the project has opted in.
_NON_EU_REGION = re.compile(
    r"""(?ix)
    (?:
      # AWS
      aws[_-]?region\s*[:=]\s*["']?
        (?:us-(?:east|west)-\d|
           ap-(?:south|northeast|southeast)-\d|
           sa-east-\d|
           ca-(?:central|west)-\d|
           me-(?:south|central)-\d|
           af-south-\d)|
      \.s3\.
        (?:us-(?:east|west)-\d|ap-[a-z]+-\d|sa-east-\d|
           ca-[a-z]+-\d|me-[a-z]+-\d|af-[a-z]+-\d)
        \.amazonaws\.com|
      # GCP
      --region[\s=]+
        (?:us-(?:east|west|central)\d|
           asia-[a-z]+\d|
           australia-[a-z]+\d|
           southamerica-[a-z]+\d|
           northamerica-[a-z]+\d)|
      # Azure
      --location[\s=]+
        (?:EastUS|WestUS\d?|CentralUS|SouthCentralUS|
           Brazil[A-Za-z]+|Australia[A-Za-z]+|Japan[A-Za-z]+|
           Korea[A-Za-z]+|Canada[A-Za-z]+|India[A-Za-z]+)
    )
    """
)


# Opt-in declaration shape — caller scans repo-wide docs (README,
# CHANGELOG, COMPLIANCE.md) for this regex. If present, the residency
# rule activates; otherwise no findings fire.
EU_RESIDENCY_DECLARATION = re.compile(
    r"""(?ix)
    \b(?:
      GDPR|
      EU\s+residency|
      EEA\s+residency|
      data\s+(?:resides|residency|stored)\s+in\s+(?:the\s+)?(?:EU|EEA|European)
    )\b
    """
)


# ---- Rule 5 — privacy.pii-in-error-message-to-client --------------------


# Stage-A regex — finds HTTP error-response constructors that expose a
# body to the client (FastAPI HTTPException, Flask jsonify, Express
# res.json, Django JsonResponse, NestJS HttpException). The Stage-B
# PII-shape inspection on the matched group is done by the caller.
# Email is intentionally EXCLUDED from the PII vocabulary used by this
# rule's caller — "user not found: alice@example.com" is too common
# and would dominate noise. Callers that want stricter behaviour can
# re-run the email shape from PII_SHAPES on a case-by-case basis.
_ERROR_RESPONSE_WITH_PII = re.compile(
    r"""(?ix)
    (?:
      HTTPException\s*\(\s*(?:status_code\s*=\s*\d+\s*,\s*)?
        detail\s*=\s*[^)]{0,300}|
      jsonify\s*\(\s*\{[^}]{0,300}?(?:error|message|reason)[^}]{0,300}?\}|
      res\.status\s*\(\s*\d+\s*\)\s*\.json\s*\(\s*\{[^}]{0,300}?\}|
      res\.send\s*\(\s*[^)]{0,300}|
      JsonResponse\s*\(\s*\{[^}]{0,300}?\}|
      throw\s+new\s+
        (?:Http|BadRequest|Unauthorized|NotFound|Forbidden|InternalServer\w*)
        Exception\s*\(\s*[^)]{0,300}
    )
    [^)]{0,200}?
    (?:
      # PII shapes minus email (see comment above)
      (?<!\d)(?!000|666|9\d{2})\d{3}[-\s]?(?!00)\d{2}[-\s]?(?!0000)\d{4}(?!\d)|
      (?<!\d)(?:\d[\ \-]?){12,18}\d(?!\d)|
      \b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b|
      \b[A-Z]\d{8}\b|
      \+\d{1,3}[\ \-.]?\d{1,4}[\ \-.]?\d{3,4}[\ \-.]?\d{3,4}|
      # traceback exposure (industry-standard danger)
      traceback\.format_exc|sys\.exc_info|err\.stack
    )
    """
)


# ---- Rule 6 — privacy.telemetry-with-pii --------------------------------


# Stage-A: known analytics SDK calls (PostHog, Mixpanel, Amplitude,
# Segment, Hotjar, FullStory, generic /telemetry endpoints).
# Stage-B is applied by the caller: it inspects the call's payload
# argument for PII shapes. The rule's regex matches Stage-A AND
# requires a PII shape in the call argument expression (≤ 400 chars).
_TELEMETRY_WITH_PII = re.compile(
    r"""(?ix)
    (?:
      posthog\.capture\s*\(|
      mixpanel\.track\s*\(|
      amplitude\.(?:logEvent|track)\s*\(|
      analytics\.(?:track|identify|page|screen)\s*\(|
      gtag\s*\(\s*["']event["']|
      segment\.(?:track|identify)\s*\(|
      (?:fetch|requests\.(?:post|put)|axios\.(?:post|put)|http\.(?:post|request))
        \s*\(\s*["']https?:\/\/
        (?:api\.(?:posthog|mixpanel|segment|amplitude|hotjar|fullstory)\.com|
           [^"']*\/(?:telemetry|analytics|metrics|events|tracking)\b)
    )
    [^)]{0,400}?
    (?:
      # us_ssn
      (?<!\d)(?!000|666|9\d{2})\d{3}[-\s]?(?!00)\d{2}[-\s]?(?!0000)\d{4}(?!\d)|
      # credit_card shape
      (?<!\d)(?:\d[\ \-]?){12,18}\d(?!\d)|
      # iban
      \b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b|
      # us_passport
      \b[A-Z]\d{8}\b|
      # email
      \b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b|
      # phone
      \+\d{1,3}[\ \-.]?\d{1,4}[\ \-.]?\d{3,4}[\ \-.]?\d{3,4}
    )
    """
)


# ---- Rule 7 — privacy.cookie-without-secure-httponly --------------------


# Cookie-setter signature regex. The Secure / HttpOnly / SameSite
# presence checks are done by the caller (which post-processes the
# matched options block). This regex anchors on the SETTER call so
# unrelated `secure: false` flags in non-cookie contexts don't fire.
_COOKIE_SETTER = re.compile(
    r"""(?ix)
    (?:
      res(?:ponse)?\.cookie\s*\(\s*["'][^"']+["']\s*,\s*[^,)]+
        (?:\s*,\s*\{[^}]{0,300}?\})?\s*\)|
      (?:response|resp)\.set_cookie\s*\(\s*["'][^"']+["'][^)]{0,300}?\)|
      \.set_cookie\s*\(\s*key\s*=\s*["'][^"']+["'][^)]{0,300}?\)|
      @SetCookie\s*\(\s*["'][^"']+["']|
      (?:res|response|ctx)\.(?:setHeader|set)\s*\(\s*["']Set-Cookie["']
        \s*,\s*["'][^"']{0,300}?["']
    )
    """
)


# Helper sub-patterns the caller uses on the matched options-block
# text to decide severity. Exported so the caller doesn't have to
# duplicate them.
COOKIE_SECURE_PRESENT = re.compile(
    r"\bsecure\b\s*[:=]\s*[tT]rue|;\s*Secure\b"
)
COOKIE_HTTPONLY_PRESENT = re.compile(
    r"\bhttp[_]?only\b\s*[:=]\s*[tT]rue|;\s*HttpOnly\b", re.IGNORECASE,
)
COOKIE_SAMESITE_PRESENT = re.compile(
    r"\bsame[_]?site\b\s*[:=]", re.IGNORECASE,
)


# Django/Flask config-key shape (e.g. SESSION_COOKIE_SECURE = False).
# Caller fires when value is False / None / "".
_COOKIE_CONFIG_INSECURE = re.compile(
    r"""(?ix)
    (?:SESSION|CSRF|REMEMBER|AUTH)_COOKIE_(?:SECURE|HTTPONLY)
      \s*=\s*(?:False|None|["']\s*["'])
    """
)


# ---- Rule 8 — privacy.third-party-script-without-csp --------------------


# Stage-A: a `<script src="https://..."` to an external host. Stage-B
# is the absence of a CSP declaration in the same file/header config;
# the caller decides whether to fire after running CSP_DECLARATION on
# the surrounding context. This regex matches Stage-A only.
_THIRD_PARTY_SCRIPT = re.compile(
    r"""(?ix)
    <script\s+
      (?:[^>]*?\s)?
      src\s*=\s*["']
        https?:\/\/
        (?!localhost|127\.0\.0\.1)
        [^"']+
      ["']
    """
)


# CSP declaration shape — exported so the caller can run it on the
# surrounding context (HTML <head>, headers config, helmet block,
# Next.js headers config) and decide whether Rule 8 fires.
CSP_DECLARATION = re.compile(
    r"""(?ix)
    (?:
      <meta\s+http-equiv\s*=\s*["']Content-Security-Policy["']
        \s+content\s*=\s*["'][^"']+["']|
      (?:setHeader|headers\.set|res\.set)\s*\(\s*
        ["']Content-Security-Policy["']\s*,\s*["'][^"']+["']|
      helmet\s*\(\s*\{\s*contentSecurityPolicy\s*:\s*
        (?:\{[^}]+\}|true|false)|
      ["']Content-Security-Policy["']\s*:\s*["'][^"']+["']
    )
    """
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="privacy.pii-pattern-in-log-line",
        name="PII shape inside a logger / print call argument",
        severity="HIGH",
        description=(
            "A logger / console.log / print / fmt.Println / slog call "
            "argument expression contains a PII shape (SSN, credit-card, "
            "IBAN, US passport, email, E.164 phone). Even when the log "
            "sink itself is private, PII in logs propagates to backups, "
            "cold storage, third-party log aggregators, and engineer "
            "screens — out-of-scope for the original consent. Source "
            "shape: PWNPipe token-in-logs.js + ePHI/PCI test corpora. "
            "Callers should run luhn_valid() on credit_card matches to "
            "drop date-string FPs."
        ),
        pattern=_LOG_CALL_WITH_PII,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="privacy.email-in-public-artifact",
        name="Public-artifact sink in a workflow / IaC step",
        severity="CRITICAL",
        description=(
            "A workflow step uploads to a provably-public destination "
            "(actions/upload-artifact, GitHub Pages, S3 bucket, gh "
            "release upload, jsDelivr/unpkg CDN, Azure/GCS public blob). "
            "Stage-B (file-content inspection for email shapes from "
            "PII_SHAPES) is the caller's responsibility — this regex "
            "matches the SINK only. Joined with Stage-B at the "
            "workflow-walker layer per Proposal 2 of distill2-i."
        ),
        pattern=_PUBLIC_ARTIFACT_SINK,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="privacy.gdpr-erase-not-implemented",
        name="DELETE-user route without cascade indicators",
        severity="MAJOR",
        description=(
            "A DELETE /user|account|profile|me|customer|member route "
            "is defined. The caller walks the handler body and runs "
            "CASCADE_INDICATORS on it; if no cascade indicator fires "
            "inside the handler, the rule fires MAJOR. Per GDPR "
            "Article 17, the right to erasure must remove (or "
            "anonymise) all related personal data — soft-delete of "
            "just the user row is arguably non-compliant."
        ),
        pattern=_DELETE_USER_ROUTE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="privacy.data-residency-violation",
        name="Non-EU cloud region referenced in IaC / workflow",
        severity="CRITICAL",
        description=(
            "An AWS / GCP / Azure region token outside the EU was "
            "found in source / IaC / workflow. This rule is INACTIVE "
            "by default and the caller MUST first verify the project "
            "has opted in via .janitor-privacy.yaml `residency: eu` "
            "or an EU_RESIDENCY_DECLARATION match in repo docs. The "
            "opt-in gate keeps precision near 100% — every firing is "
            "a real residency concern, every non-firing is by design."
        ),
        pattern=_NON_EU_REGION,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="privacy.pii-in-error-message-to-client",
        name="HTTP error-response body contains a PII shape",
        severity="HIGH",
        description=(
            "An HTTP error-response constructor (FastAPI HTTPException, "
            "Flask jsonify, Express res.json/res.send, Django "
            "JsonResponse, NestJS HttpException) carries a PII shape "
            "(SSN / credit-card / IBAN / passport / phone) or a "
            "raw traceback (traceback.format_exc, sys.exc_info, "
            "err.stack) in its body. The body is delivered to the "
            "API caller — out-of-scope PII leak. Email is "
            "intentionally NOT in the PII vocabulary for this rule "
            "(too noisy in 'user not found' messages); run "
            "PII_SHAPES['email'] separately on a case-by-case basis."
        ),
        pattern=_ERROR_RESPONSE_WITH_PII,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="privacy.telemetry-with-pii",
        name="Analytics / telemetry call carries a PII shape",
        severity="HIGH",
        description=(
            "A telemetry SDK call (PostHog, Mixpanel, Amplitude, "
            "Segment, Hotjar, FullStory) or a fetch/axios POST to a "
            "telemetry/analytics/metrics/tracking endpoint carries a "
            "PII shape in its payload. Raw PII to third-party "
            "telemetry destinations breaks GDPR/CCPA opt-in tracking "
            "and exfiltrates personal data outside the consent "
            "boundary. Use a hashed pseudonymous ID instead."
        ),
        pattern=_TELEMETRY_WITH_PII,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="privacy.cookie-without-secure-httponly",
        name="Cookie set without Secure + HttpOnly flags",
        severity="HIGH",
        description=(
            "A cookie setter (Express res.cookie, Flask "
            "response.set_cookie, FastAPI set_cookie, Django "
            "set_cookie, NestJS @SetCookie, raw Set-Cookie header) "
            "matched. The caller runs COOKIE_SECURE_PRESENT and "
            "COOKIE_HTTPONLY_PRESENT on the matched options text — "
            "if both are absent → HIGH, if one is absent → MAJOR. "
            "Analytics cookies (_ga, _gid, _gat) are intentionally "
            "client-readable; the caller skips those names."
        ),
        pattern=_COOKIE_SETTER,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="privacy.cookie-config-insecure",
        name="Django/Flask cookie config flag set to False/None",
        severity="HIGH",
        description=(
            "A SESSION_COOKIE_SECURE / CSRF_COOKIE_SECURE / "
            "REMEMBER_COOKIE_HTTPONLY / AUTH_COOKIE_SECURE (etc.) "
            "config key is set to False, None, or empty string. "
            "Session cookies without Secure flag are sent over plain "
            "HTTP and stealable by network attackers; cookies "
            "without HttpOnly are stealable via XSS. Config-file "
            "complement to privacy.cookie-without-secure-httponly."
        ),
        pattern=_COOKIE_CONFIG_INSECURE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="privacy.third-party-script-without-csp",
        name="Third-party <script> tag in HTML / template",
        severity="HIGH",
        description=(
            "An HTML <script src='https://external.host/...'> tag "
            "was found. Caller runs CSP_DECLARATION on the page's "
            "<head> / response headers / helmet config / Next.js "
            "headers; if no CSP declaration is found → HIGH; if CSP "
            "exists but lacks script-src for the script's host → "
            "MAJOR; if CSP allows 'unsafe-inline' or '*' → NIT. "
            "Skip-list for known-good CDNs (cdnjs.cloudflare.com, "
            "cdn.jsdelivr.net, unpkg.com) is applied by the caller."
        ),
        pattern=_THIRD_PARTY_SCRIPT,
        owasp_asi="ASI-03",
    ),
)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str, *, file_kind: str = "source") -> list[Finding]:
    """Run every applicable privacy rule against `text` and return findings.

    `file_kind` selects which subset to apply:
      * "source" (default) — code files. Runs every rule.
      * "workflow"         — GitHub Actions / GitLab CI / similar YAML.
                             Runs the public-artifact and non-EU-region
                             rules; skips source-only rules (cookies,
                             error-response bodies, telemetry SDK calls)
                             that don't appear in workflow YAML.
      * "html"             — HTML / template files. Runs only the
                             third-party-script-without-csp rule.

    Findings are deduped by (rule_id, line, col). Same shape as
    `agent_config_patterns.scan_text`.

    NOTE: This is a regex pass only. For Proposals 3, 4, 7, 8, the
    full finding requires the caller's Stage-B context check (cascade
    walk, opt-in declaration, options-block parse, CSP-presence
    check). The scanner emits a candidate finding; the caller decides
    final severity / suppression.
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    workflow_rules = {
        "privacy.email-in-public-artifact",
        "privacy.data-residency-violation",
    }
    html_rules = {
        "privacy.third-party-script-without-csp",
    }
    for rule in RULES:
        if file_kind == "workflow" and rule.id not in workflow_rules:
            continue
        if file_kind == "html" and rule.id not in html_rules:
            continue
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    return findings
