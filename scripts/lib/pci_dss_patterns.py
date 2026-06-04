"""PCI-DSS payment-card data leak patterns.

Wave-27 distillation round 13, angle "pci-dss".

Catalogue of 8 PCI-DSS Req 3 / Req 4 cardholder-data (CHD)
anti-patterns distilled in `reports/distill-round-13/pci-dss.md`.
Targets the *payload* — PAN/CVV/Track-1/Track-2/etc. — flowing through
application code in ways PCI-DSS v4.0 explicitly forbids. Orthogonal
to:

  * `crypto_misuse_patterns` (algorithm choices, not data-persistence sites).
  * `gdpr_privacy_patterns` (PII retention; not card-data-specific).
  * `secret_rotation_patterns` (Stripe/Braintree *API* secrets, not CHD).
  * `log_telemetry_patterns` (log destinations; we look for the SHAPE
    of card data in log/response strings).

What IS here (8 rules, regex-only, all RE2-safe):

  * pci-dss-cvv-stored-in-db                                  (CRITICAL)
  * pci-dss-pan-logged-plaintext                              (CRITICAL)
  * pci-dss-track-data-persisted                              (CRITICAL)
  * pci-dss-pan-unmasked-in-response                          (HIGH)
  * pci-dss-payment-secret-in-client-bundle                   (CRITICAL)
  * pci-dss-pan-in-url-query                                  (HIGH)
  * pci-dss-pan-leaked-via-repr-str                           (HIGH)
  * pci-dss-bin-lookup-third-party                            (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used (PCI-DSS report maps these to A0X:2021 codes;
we keep the janitor-local "ASI-NN" shorthand):

  ASI-01 — Broken Access Control (unmasked PAN on response surface)
  ASI-02 — Cryptographic Failures / Secret leak (CHD or secret key
                                                 in logs / responses /
                                                 client bundles)
  ASI-04 — Insecure Design (storage / transmission patterns that
                            cannot be made compliant via patching —
                            architectural)
  ASI-05 — Security Misconfiguration (client-side env-var prefix
                                       ships secrets to browser;
                                       third-party endpoints w/o
                                       contract)
  ASI-07 — Authentication / Identification Failures (secret-key
                                                      compromise =
                                                      merchant account
                                                      takeover)
  ASI-08 — Software & Data Integrity Failures (ungoverned third-party
                                                BIN lookups)
  ASI-09 — Security Logging & Monitoring Failures (CHD in logs / stack
                                                    traces / Sentry
                                                    captures)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

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
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    chat_bot_patterns / auth_flow_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# Card-name atom used by several rules. PCI scope names: PAN aliases
# (`card_number`, `pan`, `cc_number`, `cardNumber`, `primary_account_number`)
# and CVV aliases (`cvv`, `cvc`, `cvv2`, `cvc2`).
_PAN_NAMES = (
    r"(?:card_?number|cc_?num(?:ber)?|pan|primary_account_number)"
)
_CVV_NAMES = (
    r"(?:cvv2?|cvc2?|card_verification_value|security_code)"
)


# ---- P1 : pci-dss-cvv-stored-in-db --------------------------------------


# SQL/ORM column declaration with a CVV-aliased name. We anchor on the
# CVV name followed by a type/column keyword on the same line.
_CVV_COLUMN_DECL = _re(
    r"\b" + _CVV_NAMES + r"\b"
    r"\s*(?:varchar|char|text|string|integer|number|smallint|tinyint"
    r"|=\s*Column|=\s*models\.|=\s*db\.Column|=\s*Field\s*\(|"
    r":\s*str\b|:\s*int\b)"
)

# Pydantic / Mongoose / OpenAPI schema variant: the CVV key sits in a
# schema-object literal with a `type` / `dataType` property.
_CVV_SCHEMA_DECL = _re(
    r"['\"]?" + _CVV_NAMES + r"['\"]?\s*:\s*\{"
    r"[^}]{0,200}\b(?:type|columnType|dataType)\b"
)

# Stage-B context: the file must contain a persistence-site keyword
# (CREATE TABLE / models.Model / Base / pydantic-with-table / Mongoose
# `Schema(...)`). Pure DTO/dataclass declarations with no persistence
# context are dropped per the report's FP filter.
_PERSISTENCE_CONTEXT = _re(
    r"\bCREATE\s+TABLE\b"
    r"|"
    r"\bclass\s+\w+\s*\(\s*(?:[\w.]*\.)?(?:Model|Base|TableBase|DeclarativeBase"
    r"|db\.Model)\b"
    r"|"
    r"\bnew\s+(?:mongoose\.)?Schema\s*\("
    r"|"
    r"\bsequelize\.define\s*\("
    r"|"
    r"\bSequelize\.Model\b"
    r"|"
    r"\b__tablename__\s*="
    r"|"
    r"\bORM\b"
)


# ---- P2 : pci-dss-pan-logged-plaintext ----------------------------------


# Part A — log/print call atom across Python, JS/TS, Go.
_LOG_CALL_ATOM = _re(
    r"\b(?:"
    r"logger?\.(?:debug|info|warn|warning|error|critical|fatal|trace)"
    r"|print"
    r"|console\.(?:log|info|warn|error|debug|trace)"
    r"|fmt\.(?:Print|Printf|Println|Sprintf|Sprintln|Errorf)"
    r"|log\.(?:Print|Printf|Println|Fatal|Fatalf|Panic|Panicf|Debug|Info)"
    r"|sys\.(?:stdout|stderr)\.write"
    r"|System\.(?:out|err)\.println"
    r")\b"
)

# Part B — same-line interpolation of a card-aliased identifier. We
# bound the gap between the log call and the card name to 200 chars
# (single-line log statements rarely exceed that).
_PAN_INTERPOLATION = _re(
    # Template / f-string: ${cardNumber} or {card_number} or %s ... pan
    r"(?:\$\{?|\{|%[sdv])[^\n]{0,40}\b" + _PAN_NAMES + r"\b"
    r"|"
    # Positional arg: logger.info(msg, card_number) — bare identifier
    # immediately after a comma in the args list.
    r",\s*(?:[A-Za-z_$][\w.]*\.)?" + _PAN_NAMES + r"\b"
)


# ---- P3 : pci-dss-track-data-persisted ----------------------------------


# Part A — track-data variable / column / key name.
_TRACK_NAME = _re(
    r"\b(?:track1|track2|track_1|track_2|track_data|magstripe|mag_stripe"
    r"|emv_track|magnetic_stripe)\b"
)

# Part B — persistence verb (INSERT / save / write / disk). Each
# alternative is anchored with its own `\b` only where the trailing
# character is word-class (some alternatives end at a quote, where `\b`
# would be a non-word boundary mismatch).
_PERSIST_VERB = _re(
    r"\b(?:INSERT|UPDATE|insert_one|insertOne|insertMany|persist"
    r"|flush|fwrite|writeFile|writeFileSync"
    r"|\.save|\.create|\.put|\.push|\.append|\.write)\b"
    r"|"
    # open() with append / write mode → disk-write site
    r"\bopen\s*\([^)]{0,200}['\"](?:a|w|wb|ab)\+?['\"]"
    r"|"
    r"\b(?:os\.write|fs\.write|file\.write)\b"
    r"|"
    # bare `.write(` call (e.g. `f.write(track_data)`)
    r"\.write\s*\("
)

# Part C — raw magstripe Track-1 literal (`%B…^...^…`).
_TRACK1_LITERAL = _re(
    r"%B\d{13,19}\^[A-Z\s./]+\^\d{4}"
)

# Part D — raw magstripe Track-2 literal (`;…=…`). Anchor with a
# semicolon, PAN-shape digits, `=`, then expiry+service-code/discretionary.
_TRACK2_LITERAL = _re(
    r";\d{13,19}=\d{4}\d{3,4}"
)


# ---- P4 : pci-dss-pan-unmasked-in-response ------------------------------


# Part A — response-construction site.
_RESPONSE_BUILDER = _re(
    r"\bres\.json\s*\("
    r"|"
    r"\bres\.send\s*\("
    r"|"
    r"\bres\.status\s*\(\s*\d+\s*\)\s*\.\s*json\s*\("
    r"|"
    r"\breturn\s+jsonify\s*\("
    r"|"
    r"\breturn\s+JsonResponse\s*\("
    r"|"
    r"\breturn\s+Response\s*\("
    r"|"
    r"\breturn\s+json\s*\("
    r"|"
    r"\bc\.JSON\s*\("
    r"|"
    r"\bctx\.body\s*="
)

# Part B — card-name key in JSON-object position. The value side is an
# identifier (NOT a string literal containing a constant test PAN).
_PAN_KEY_IN_OBJECT = _re(
    r"['\"]?" + _PAN_NAMES + r"['\"]?"
    r"\s*[:=]\s*[A-Za-z_$][\w.$]{0,80}"
)

# Part C — schema-style declaration (GraphQL, OpenAPI, TypeScript
# interface, pydantic field declaration). Distinct from P1 because
# this looks for the *response shape*, not a persistence column.
_PAN_SCHEMA_FIELD = _re(
    r"\b" + _PAN_NAMES + r"\s*:\s*"
    r"(?:String|VARCHAR|str|number|Int|Float|String!|Int!)"
    r"\b"
)

# Part D — masking marker that suppresses the finding when present in
# the surrounding window. `last4`, `masked`, `redact`, etc.
_MASKING_MARKER = _re(
    r"\b(?:mask(?:ed)?\s*\(|last\s*[_-]?\s*4|redact"
    r"|slice\s*\(\s*-\s*4|substr\s*\(\s*-?\s*4"
    r"|substring\s*\(\s*\w+\s*\.\s*length\s*-\s*4"
    r"|cardLast4|card_last4|truncate)\b"
)


# ---- P5 : pci-dss-payment-secret-in-client-bundle -----------------------


# Part A — server-side secret-key literal for Stripe / Braintree / Adyen.
_PAYMENT_SECRET_LITERAL = _re(
    # Stripe live/secret/restricted-key
    r"\bsk_live_[A-Za-z0-9]{20,}"
    r"|"
    r"\brk_live_[A-Za-z0-9]{20,}"
    r"|"
    # Braintree access token (production)
    r"\baccess_token\$production\$[A-Za-z0-9_$]{8,}"
    r"|"
    # Adyen API key shape (`AQEx…`)
    r"\bAQE[A-Za-z0-9_\-]{50,}"
)

# Part B — client-side env-var prefix that ships to the browser. Each
# bundler / framework has a well-known public-env prefix; values under
# these names ARE inlined into the client bundle by the bundler.
_CLIENT_ENV_PREFIXED_SECRET = _re(
    r"\b(?:NEXT_PUBLIC_|REACT_APP_|VITE_|GATSBY_|NUXT_PUBLIC_"
    r"|VUE_APP_|EXPO_PUBLIC_)"
    r"[A-Z0-9_]*"
    r"(?:STRIPE|BRAINTREE|ADYEN|CHECKOUT|PAYMENT)"
    r"[A-Z0-9_]*"
    r"(?:_SECRET|_PRIVATE|_KEY|_TOKEN|_SK)\b"
)

# Part C — placeholder / fixture marker that suppresses literal hits
# (per the report's FP filter).
_PLACEHOLDER_MARKER = _re(
    r"x{5,}"
    r"|"
    r"0{5,}"
    r"|"
    r"\bREDACTED\b"
    r"|"
    r"<your[-_]?key>"
    r"|"
    r"<example>"
    r"|"
    r"placeholder"
)


# ---- P6 : pci-dss-pan-in-url-query --------------------------------------


# PAN / CVV name inside a URL query parameter, with the value side
# being an interpolation (`${...}`, `{...}`, `+ var`) — NOT a static
# literal. Cover JS template-strings, Python f-strings, raw concat.
_PAN_IN_QUERY = _re(
    r"[?&]" + _PAN_NAMES + r"\s*=\s*"
    r"(?:\$\{[^}\s\"']{1,80}\}"
    r"|\{[^}\s\"']{1,80}\}"
    r"|[A-Za-z_$][\w.$]{0,60})"
    r"|"
    r"[?&]" + _CVV_NAMES + r"\s*=\s*"
    r"(?:\$\{[^}\s\"']{1,80}\}"
    r"|\{[^}\s\"']{1,80}\}"
    r"|[A-Za-z_$][\w.$]{0,60})"
)

# Stage-B context: the URL path must be in a payment-themed segment.
_PAYMENT_URL_PATH = _re(
    r"\b/(?:charge|payment|pay|checkout|order|billing|subscription"
    r"|refund|capture|authorize|authorise|confirm|3ds|threeds)\b"
)


# ---- P7 : pci-dss-pan-leaked-via-repr-str -------------------------------


# Part A — class with a card-y name AND a stringify hook. RE2-safe: the
# `[^{]{0,500}` body window has a bounded upper limit, no nested
# quantifier.
_CARD_CLASS_STRINGIFY = _re(
    r"\bclass\s+\w*(?:Card|Payment|PaymentMethod|CreditCard)\w*"
    r"[^{]{0,500}"
    r"(?:def\s+__repr__|def\s+__str__|toString\s*\(\s*\)"
    r"|String\s*\(\s*\)\s*string|fmt\.Stringer|Display\s*\(\s*\))"
)

# Part B — pydantic model with un-wrapped PAN field (should be SecretStr).
_PYDANTIC_PAN_PLAIN_STR = _re(
    r"\bclass\s+\w+\s*\(\s*(?:[\w.]*\.)?BaseModel\s*\)"
    r"[^{]{0,500}"
    r"\b" + _PAN_NAMES + r"\s*:\s*str\b"
)

# Part C — string-template raise/throw/panic that interpolates `card`.
_RAISE_WITH_CARD = _re(
    r"\b(?:raise|throw\s+new\s+Error|panic)\s*\(\s*"
    r"[fr]?[\"'`][^\"'`]*\{[^}]*\bcard\b[^}]*\}"
)

# Stage-B suppressor: the surrounding window must contain a
# payment-domain marker. Tarot/library/business-card classes don't have
# `expiry`, `cvv`, `merchant`, `stripe`, etc.
_PAYMENT_DOMAIN_MARKER = _re(
    r"\b(?:expiry|exp_month|exp_year|cvv|cvc|pan|amount|merchant"
    r"|stripe|braintree|adyen|payment|charge|authoris|authori[sz]e"
    r"|card_?number|primary_account_number)\b"
)


# ---- P8 : pci-dss-bin-lookup-third-party --------------------------------


# Part A — well-known free / public BIN-lookup hostname.
_THIRD_PARTY_BIN_HOST = _re(
    r"\b(?:"
    r"lookup\.binlist\.net"
    r"|binlist\.net"
    r"|bin-checker\.net"
    r"|freebinchecker\.com"
    r"|neutrinoapi\.com/bin-lookup"
    r"|apilayer\.com/bin"
    r"|binlist\.io"
    r"|binbase\.com"
    r"|bincodes\.com"
    r")\b"
)

# Part B — HTTP-client call atom.
_HTTP_CLIENT_CALL = _re(
    r"\b(?:fetch\s*\("
    r"|axios\.(?:get|post|put|patch|delete|request)\s*\("
    r"|requests\.(?:get|post|put|patch|delete|request)\s*\("
    r"|http\.(?:get|post|request)"
    r"|urllib\.request"
    r"|httpx\.(?:get|post|put|patch|delete)\s*\("
    r"|got\s*\("
    r"|superagent\.(?:get|post)"
    r"|ky\.(?:get|post))"
)

# Part C — internal-host suppressor (per report FP filter).
_INTERNAL_HOST_MARKER = _re(
    r"\blocalhost\b"
    r"|"
    r"\b127\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
    r"|"
    r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
    r"|"
    r"\b192\.168\.\d{1,3}\.\d{1,3}\b"
    r"|"
    r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"
    r"|"
    r"\.local\b"
    r"|"
    r"\binternal\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="pci-dss-cvv-stored-in-db",
        name="CVV/CVC field declared in DB schema or ORM model",
        severity="CRITICAL",
        description=(
            "A column / model field named cvv / cvc / cvv2 / cvc2 / "
            "card_verification_value / security_code is declared in a "
            "SQL CREATE TABLE, an ORM model class, or a Mongoose / "
            "Pydantic-with-table schema. PCI-DSS Req 3.2.1 prohibits "
            "storing the CVV at all — not encrypted, not hashed, not "
            "tokenised. Storage post-authorization is an automatic-"
            "failure finding regardless of crypto envelope."
        ),
        pattern=_CVV_COLUMN_DECL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="pci-dss-pan-logged-plaintext",
        name="PAN interpolated into a log / print / console call",
        severity="CRITICAL",
        description=(
            "A logger / print / console.log / fmt.Printf / "
            "log.Printf call interpolates a variable named "
            "card_number / cardNumber / pan / cc_number / "
            "primary_account_number on the same line. PCI-DSS Req "
            "3.3.1 + Req 10 require masking to first6 + last4 on every "
            "display surface, and logs are routinely shipped to "
            "SIEM / Splunk / Datadog which multiplies the exposure "
            "footprint. Mask before logging — e.g. pan[-4:] only."
        ),
        pattern=_PAN_INTERPOLATION,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="pci-dss-track-data-persisted",
        name="Track-1 / Track-2 magnetic-stripe data persisted to disk / DB",
        severity="CRITICAL",
        description=(
            "Variable / column / key named track1 / track2 / "
            "track_data / magstripe / emv_track is written to a file, "
            "DB row, or log — OR a raw magstripe Track-1 (`%B…^…^…`) "
            "or Track-2 (`;…=…`) literal appears in source. PCI-DSS "
            "Req 3.2 PROHIBITS storage of full track data post-"
            "authorization, period. This is the most severe CHD "
            "violation: a single stored track-2 record gives the "
            "attacker every datum needed to clone a magstripe card."
        ),
        pattern=_TRACK_NAME,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="pci-dss-pan-unmasked-in-response",
        name="PAN returned unmasked in API JSON / GraphQL response",
        severity="HIGH",
        description=(
            "An HTTP handler / resolver / serializer responds with a "
            "JSON object whose `card_number` / `cardNumber` / `pan` / "
            "`cc_number` / `primary_account_number` key carries the "
            "full PAN — no `mask()`, `last4`, `redact`, or `slice(-4)` "
            "applied. PCI-DSS Req 3.3.1 / Req 4.2 require masking on "
            "every display surface; the API response is a display "
            "surface when the consumer is a browser, mobile app, or "
            "partner system (each of which retains the response in "
            "caches / memory / logs)."
        ),
        pattern=_RESPONSE_BUILDER,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="pci-dss-payment-secret-in-client-bundle",
        name="Stripe / Braintree / Adyen secret key in client-shipped code or env",
        severity="CRITICAL",
        description=(
            "A server-side payment-API SECRET key (`sk_live_*`, "
            "`rk_live_*`, `access_token$production$…`, Adyen `AQE…`) "
            "is present in code or env-var name that ships to the "
            "browser — either as a literal string OR as a "
            "client-public env-var prefix (`NEXT_PUBLIC_`, "
            "`REACT_APP_`, `VITE_`, `GATSBY_`, `NUXT_PUBLIC_`, "
            "`VUE_APP_`, `EXPO_PUBLIC_`) ending in `_SECRET` / "
            "`_PRIVATE` / `_KEY`. The secret key grants full account "
            "control — leaking one to the browser equals an "
            "unauthenticated takeover of the merchant's payment-"
            "processor account."
        ),
        pattern=_PAYMENT_SECRET_LITERAL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="pci-dss-pan-in-url-query",
        name="PAN / CVV passed as a URL query parameter",
        severity="HIGH",
        description=(
            "A URL is constructed with the PAN or CVV as a query "
            "parameter (`?card_number=…` / `?pan=…` / `?cvv=…`). "
            "Query strings persist in browser history, server access "
            "logs, proxy logs, Referer headers, and CDN caches — "
            "every one of which is an immutable surface outside the "
            "merchant's control. PCI-DSS Req 4.2.1 forbids "
            "transmitting PAN via end-user messaging tech; the same "
            "principle applies to URL query strings because the "
            "downstream log surface is just as durable."
        ),
        pattern=_PAN_IN_QUERY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="pci-dss-pan-leaked-via-repr-str",
        name="Card class __repr__ / toString / pydantic str field leaks full PAN",
        severity="HIGH",
        description=(
            "A `Card` / `Payment` / `PaymentMethod` / `CreditCard` "
            "class overrides `__repr__` / `__str__` / `toString` / "
            "`String()` / `Display()` to return the full PAN — OR a "
            "pydantic `BaseModel` declares `card_number: str` "
            "(should be `SecretStr`). Any stack trace, Sentry "
            "capture, unhandled-exception serializer, or `JSON."
            "stringify(error)` then dumps the CHD into the log "
            "surface. PCI-DSS Req 6.5.5 (improper error handling) + "
            "Req 10 (audit-log content) — both fail."
        ),
        pattern=_CARD_CLASS_STRINGIFY,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="pci-dss-bin-lookup-third-party",
        name="BIN / PAN-prefix lookup sent to ungoverned third-party endpoint",
        severity="MEDIUM",
        description=(
            "Code calls a public BIN-lookup endpoint "
            "(`binlist.net`, `bin-checker.net`, `neutrinoapi.com/"
            "bin-lookup`, `apilayer.com/bin`, etc.) with the PAN "
            "prefix — or, worse, the full PAN — in the URL path or "
            "body. Even though the BIN itself is not formally "
            "'sensitive' under PCI-DSS, sending it to an "
            "uncontracted third-party is a Req 12.8 service-provider "
            "compliance gap; several free endpoints log the request "
            "body which often contains the full PAN because the dev "
            "pasted `card_number` instead of `card_number[:6]`. "
            "Use a contracted BIN provider with a DPA in place."
        ),
        pattern=_THIRD_PARTY_BIN_HOST,
        owasp_asi="ASI-08",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * P1 (cvv-stored-in-db) — anchor on the CVV column declaration
        AND require a persistence-context marker (CREATE TABLE / ORM
        base class / Mongoose Schema) anywhere in the file. Pure DTO /
        @dataclass declarations are dropped.
      * P2 (pan-logged-plaintext) — anchor on the log-call atom AND
        require a PAN-name interpolation on the same line (200-char
        window). Findings emit at the log call's offset.
      * P3 (track-data-persisted) — anchor on the track-name AND
        require a persistence verb in the same 300-char span. The
        raw `%B…` / `;…=…` magstripe literal is high-precision on
        its own.
      * P4 (pan-unmasked-in-response) — anchor on the response builder
        AND require a PAN-key in the next 300-char span AND NO
        masking marker (`mask`, `last4`, `redact`, `slice(-4)`) in a
        5-line backward window.
      * P5 (payment-secret-in-client-bundle) — Stage-A literal-shape
        match is high-precision (drop if a placeholder marker like
        `xxxxx` / `REDACTED` is present on the same line). Stage-B
        env-prefix variant flags on the bare prefixed-name match.
      * P6 (pan-in-url-query) — anchor on the query-string match AND
        require a payment-themed URL path segment in the same 200-
        char window.
      * P7 (pan-leaked-via-repr-str) — anchor on the card-class
        stringify hook AND require a payment-domain marker
        (`expiry`/`cvv`/`merchant`/`stripe`/etc.) anywhere in the
        file. Pydantic-PAN-plain-str variant emits standalone.
      * P8 (bin-lookup-third-party) — anchor on the third-party host
        AND require an HTTP-client call in the same 200-char window
        AND NO internal-host marker in that window.

    Findings are deduped by (rule_id, line, column).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    has_persistence = _file_contains(text, _PERSISTENCE_CONTEXT)

    # ---- P1 : pci-dss-cvv-stored-in-db ----
    rule_p1 = rule_by_id["pci-dss-cvv-stored-in-db"]
    if has_persistence:
        for m in _CVV_COLUMN_DECL.finditer(text):
            _emit(rule_p1, m.start(), m.group(0))
        for m in _CVV_SCHEMA_DECL.finditer(text):
            _emit(rule_p1, m.start(), m.group(0))

    # ---- P2 : pci-dss-pan-logged-plaintext ----
    rule_p2 = rule_by_id["pci-dss-pan-logged-plaintext"]
    # Per-line scan: the log call and the PAN-name must appear on the
    # SAME line (or within a 200-char tail window). Using a line-by-line
    # split here is the RE2-safe substitute for the report's two-part
    # AND-able regex.
    line_offset = 0
    for raw_line in text.split("\n"):
        if _LOG_CALL_ATOM.search(raw_line) and _PAN_INTERPOLATION.search(raw_line):
            log_match = _LOG_CALL_ATOM.search(raw_line)
            if log_match is not None:
                _emit(rule_p2, line_offset + log_match.start(), log_match.group(0))
        line_offset += len(raw_line) + 1  # +1 for the newline

    # ---- P3 : pci-dss-track-data-persisted ----
    rule_p3 = rule_by_id["pci-dss-track-data-persisted"]
    # Variable-name + persistence-verb co-occurrence in a 300-char span.
    for m in _TRACK_NAME.finditer(text):
        start = m.start()
        # 300-char span centred on the match.
        span_lo = max(0, start - 150)
        span_hi = min(len(text), start + 150)
        span = text[span_lo:span_hi]
        if _PERSIST_VERB.search(span) is not None:
            _emit(rule_p3, start, m.group(0))
    # Raw magstripe literal on its own is enough.
    for m in _TRACK1_LITERAL.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))
    for m in _TRACK2_LITERAL.finditer(text):
        _emit(rule_p3, m.start(), m.group(0))

    # ---- P4 : pci-dss-pan-unmasked-in-response ----
    rule_p4 = rule_by_id["pci-dss-pan-unmasked-in-response"]
    for m in _RESPONSE_BUILDER.finditer(text):
        start = m.start()
        line, _ = _line_col(text, start)
        # 300-char forward window for the PAN-key in the response body.
        forward_lo = start
        forward_hi = min(len(text), start + 300)
        forward = text[forward_lo:forward_hi]
        key_match = _PAN_KEY_IN_OBJECT.search(forward)
        if key_match is None:
            continue
        # 5-line backward window: if a masking marker is present, drop.
        back_window = _slice_window(text, line, 5, 1)
        if _MASKING_MARKER.search(back_window) is not None:
            continue
        # Anchor the finding at the PAN-key match itself so the test
        # can see the column of the leak, not the column of `res.json(`.
        key_abs = forward_lo + key_match.start()
        _emit(rule_p4, key_abs, key_match.group(0))
    # Standalone schema-field declaration (GraphQL / pydantic-response /
    # TypeScript interface).
    for m in _PAN_SCHEMA_FIELD.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 5)
        if _MASKING_MARKER.search(window) is not None:
            continue
        _emit(rule_p4, m.start(), m.group(0))

    # ---- P5 : pci-dss-payment-secret-in-client-bundle ----
    rule_p5 = rule_by_id["pci-dss-payment-secret-in-client-bundle"]
    for m in _PAYMENT_SECRET_LITERAL.finditer(text):
        line, _ = _line_col(text, m.start())
        # Same-line placeholder suppression — _slice_forward returns exactly
        # the one line at `line`, so the bounds check is handled internally.
        line_text = _slice_forward(text, line, 1)
        if _PLACEHOLDER_MARKER.search(line_text) is not None:
            continue
        _emit(rule_p5, m.start(), m.group(0))
    for m in _CLIENT_ENV_PREFIXED_SECRET.finditer(text):
        _emit(rule_p5, m.start(), m.group(0))

    # ---- P6 : pci-dss-pan-in-url-query ----
    rule_p6 = rule_by_id["pci-dss-pan-in-url-query"]
    for m in _PAN_IN_QUERY.finditer(text):
        start = m.start()
        # 200-char span centred on the match for the payment-path filter.
        span_lo = max(0, start - 100)
        span_hi = min(len(text), start + 100)
        span = text[span_lo:span_hi]
        if _PAYMENT_URL_PATH.search(span) is None:
            continue
        _emit(rule_p6, start, m.group(0))

    # ---- P7 : pci-dss-pan-leaked-via-repr-str ----
    rule_p7 = rule_by_id["pci-dss-pan-leaked-via-repr-str"]
    has_payment_domain = _file_contains(text, _PAYMENT_DOMAIN_MARKER)
    if has_payment_domain:
        for m in _CARD_CLASS_STRINGIFY.finditer(text):
            _emit(rule_p7, m.start(), m.group(0))
        for m in _RAISE_WITH_CARD.finditer(text):
            _emit(rule_p7, m.start(), m.group(0))
    # Pydantic-pan-plain-str is precise enough to fire standalone — the
    # pydantic BaseModel class signature already constrains the match.
    for m in _PYDANTIC_PAN_PLAIN_STR.finditer(text):
        _emit(rule_p7, m.start(), m.group(0))

    # ---- P8 : pci-dss-bin-lookup-third-party ----
    rule_p8 = rule_by_id["pci-dss-bin-lookup-third-party"]
    for m in _THIRD_PARTY_BIN_HOST.finditer(text):
        start = m.start()
        # 200-char span centred on the match.
        span_lo = max(0, start - 100)
        span_hi = min(len(text), start + 100)
        span = text[span_lo:span_hi]
        # Must co-occur with an HTTP-client call atom.
        if _HTTP_CLIENT_CALL.search(span) is None:
            continue
        # Internal-host marker suppresses (in-house / on-prem endpoint).
        if _INTERNAL_HOST_MARKER.search(span) is not None:
            continue
        _emit(rule_p8, start, m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
