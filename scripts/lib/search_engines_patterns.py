"""Search-engine server-side scripting and API-key exposure patterns.

Wave-27 distillation round 13, angle "search-engines".

Catalogue of 8 search-engine-specific anti-patterns distilled in
`reports/distill-round-13/search-engines.md`. Targets the
**search-engine HTTP DSL surface** — Elasticsearch / OpenSearch inline
Painless / Lucene-expression scripts, Apache Solr VelocityResponseWriter
SSTI (CVE-2019-17558 family), Meilisearch / Typesense / Algolia
master/admin keys shipped in client bundles, search-engine API keys
sent over cleartext HTTP, stored-script aliasing, and search-DSL JSON
splicing (DSL injection).

What is NOT here (already shipped or out-of-scope — DO NOT duplicate):

  * GraphQL introspection / federation —
    `graphql_patterns.py` / `graphql_federation_patterns.py`.
  * PostgreSQL `CREATE EXTENSION`, MySQL UDF `.so` load, SQLite
    `load_extension`, MongoDB `$where`, Redis `MODULE LOAD` —
    `db_extensions_patterns.py`.
  * Generic SSTI in Jinja / Twig / Velocity-outside-Solr — generic
    SSTI distillations elsewhere.
  * Generic JWT-bearer key in a frontend bundle (non-search) —
    `auth_flow_patterns.py` and credential-lifecycle distillations.

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * search-engine-painless-inline-script-injection             (CRITICAL)
  * search-engine-get-with-script-source-bypass                (HIGH)
  * search-engine-stored-script-aliasing                       (HIGH)
  * search-engine-solr-velocity-response-writer                (CRITICAL)
  * search-engine-master-key-in-client-bundle                  (CRITICAL)
  * search-engine-api-key-over-cleartext-http                  (HIGH)
  * search-engine-dsl-json-splicing                            (HIGH)
  * search-engine-lucene-expression-injection                  (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (admin key in client bundle, key over HTTP)
  ASI-03 — Injection (Painless / Lucene-expression / DSL / SSTI)
  ASI-05 — Supply-chain / misconfiguration (Solr config, stored-script
                                            aliasing, cleartext HTTP)
  ASI-07 — Authority / authorisation gaps (script-id selection from
                                            user input)

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
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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


# ---- SE-001 : search-engine-painless-inline-script-injection ------------


# "source" JSON key whose value contains an interpolation token:
#   - ${var}  (template literal / JS, also Bash)
#   - %s / %d (printf-style)
#   - {var}   (Python f-string / str.format)
#   - + var   (concatenation builder)
# Bounded character classes; no nested quantifiers.
_PAINLESS_SOURCE_INTERPOLATED = _re(
    r'"source"\s*:\s*f?["\'`]'
    r"[^\n]{0,200}?"
    r"(?:"
    r"\$\{[^}]{1,80}\}"
    r"|%[sd]"
    r"|\{[A-Za-z_][A-Za-z0-9_]{0,40}\}"
    r"|['\"`]\s*\+\s*[A-Za-z_]"
    r")"
)

_PAINLESS_LANG_TAG = _re(
    r'"lang"\s*:\s*["\']painless["\']'
)


# ---- SE-002 : search-engine-get-with-script-source-bypass ---------------


# Pattern A: complete URL with ?source=...&source_content_type=application/json
_GET_SOURCE_PARAM_FULL = _re(
    r"[?&]source=[^&\"'\s\r\n\t]{1,2000}"
    r"&source_content_type=application(?:%2F|/)json"
)

# Pattern B: source_content_type=application/json appears as a key/value
# anywhere — looser companion when builder composes the params over multiple
# lines.
_GET_SOURCE_CONTENT_TYPE = _re(
    r"source_content_type[\"'`]?\s*[:=]\s*[\"'`]application/json[\"'`]"
)


# ---- SE-003 : search-engine-stored-script-aliasing ----------------------


# Stage-A: any reference to the stored-scripts API (write side).
_STORED_SCRIPT_WRITE = _re(
    r"\b(?:put_script|putScript)\b"
    r"|"
    r"\b_scripts/[A-Za-z_][A-Za-z0-9_]{0,40}\b"
)

# Stage-B: read-side that pulls a script id from a user-controllable value
# instead of a constant string literal.
_STORED_SCRIPT_ID_FROM_INPUT = _re(
    r'"script"\s*:\s*\{\s*"id"\s*:\s*'
    r"(?:"
    # JS / TS: `${var}` / req.query.X / req.body.X / req.params.X
    r"f?[\"'`][^\"'`]{0,80}\$\{[^}]{1,80}\}"
    r"|req\.(?:query|body|params|args)\."
    r"|request\.(?:args|form|json|values|params)"
    # Python f-string / str.format
    r"|f[\"'][^\"']{0,80}\{[A-Za-z_][A-Za-z0-9_]{0,40}\}"
    r"|str\.format"
    # Bare variable identifier (no quotes — i.e. NOT a literal string)
    r"|[A-Za-z_$][A-Za-z0-9_$.\[\]]{0,40}[,\s\}]"
    r")"
)


# ---- SE-004 : search-engine-solr-velocity-response-writer ---------------


# Solr `class="solr.VelocityResponseWriter"` declaration (XML attribute).
_SOLR_VELOCITY_CLASS_DECL = _re(
    r"class\s*=\s*[\"']solr\.VelocityResponseWriter[\"']"
)

# `params.resource.loader.enabled` set to true / 1.
_SOLR_PARAMS_RESOURCE_LOADER_TRUE = _re(
    r"\bparams\.resource\.loader\.enabled[\"']?"
    r"\s*[=>:]\s*"
    r"(?:[\"']?true[\"']?|1\b)"
)

# `wt=velocity` URL invocation (Solr SSTI exploitation surface).
_SOLR_WT_VELOCITY = _re(
    r"[?&]wt=velocity(?:&|[\"'\s]|$)"
)


# ---- SE-005 : search-engine-master-key-in-client-bundle -----------------


# Stage-A: env-var NAME pattern — NEXT_PUBLIC_* / VITE_* / REACT_APP_* /
# PUBLIC_* / EXPO_PUBLIC_* + contains MEILI|TYPESENSE|ALGOLIA + suffix
# MASTER|ADMIN.
_FE_BUNDLED_SEARCH_ADMIN_ENV = _re(
    r"\b(?:NEXT_PUBLIC|VITE|REACT_APP|PUBLIC|EXPO_PUBLIC)"
    r"_(?:[A-Z0-9_]{0,40}_)?"
    r"(?:MEILI[_A-Z0-9]*MASTER"
    r"|TYPESENSE[_A-Z0-9]*ADMIN"
    r"|ALGOLIA[_A-Z0-9]*ADMIN)"
    r"[_A-Z0-9]{0,40}\b"
)

# Stage-B: call-site shape — a constructor for MeiliSearch / TypesenseClient
# / algoliasearch with masterKey / admin(API)?Key / adminKey property.
_FE_BUNDLED_SEARCH_ADMIN_CONSTRUCTOR = _re(
    r"\b(?:MeiliSearch|TypesenseClient|algoliasearch)\s*\(\s*"
    r"[^)]{0,500}"
    r"(?:masterKey|admin(?:API)?Key|adminKey)\s*[:=]"
)


# ---- SE-006 : search-engine-api-key-over-cleartext-http -----------------


# Bounded host: NO loopback, NO RFC2606 reserved TLDs. We intentionally
# match any http:// URL with a hostname and let the FP suppression list
# strip the loopback / test / example cases.
_CLEARTEXT_HTTP_URL = _re(
    r"\bhttp://[A-Za-z0-9_.-]{1,200}"
    r"(?::[0-9]{1,5})?"
    r"/?[A-Za-z0-9_./%\-]{0,200}"
)

# Loopback / reserved hosts — these are NOT real cleartext leaks.
# The suffix (?:[:/\s"'`]|$) ensures the reserved TLD is the last label
# (e.g. "meili.example.com" is NOT filtered because ".example" is not the TLD).
_LOOPBACK_OR_RESERVED_HOST = _re(
    r"\bhttp://"
    r"(?:localhost"
    r"|127\.0\.0\.1"
    r"|0\.0\.0\.0"
    r"|\[::1\]"
    r"|[A-Za-z0-9_.-]{1,200}\.(?:test|example|local|invalid|localhost)(?:[:/\s\"'`]|$)"
    r")"
    r"(?::[0-9]{1,5})?\b"
)

# Search-engine key markers — header names + common SDK property names.
_SEARCH_ENGINE_KEY_MARKER = _re(
    r"\b(?:X-Meili-API-Key"
    r"|X-TYPESENSE-API-KEY"
    r"|X-Algolia-API-Key"
    r"|api[_-]?key"
    r"|http_auth"
    r"|masterKey"
    r"|MEILI_(?:MASTER_)?KEY"
    r"|TYPESENSE_API_KEY"
    r"|ALGOLIA_(?:ADMIN_)?KEY)\b"
)


# ---- SE-007 : search-engine-dsl-json-splicing ---------------------------


# String / template-literal / f-string that embeds a DSL-key followed by
# an interpolation site (${var} or {var}). Bounded; alternation kept linear.
# Uses [\s\S]{N}? (lazy any-char) so that single/double quotes and newlines
# inside multiline f-strings (f'''...''') do not break the match.
# The interpolation anchor \{[A-Za-z_$][^}\n]{0,80}\} requires the expression
# to START with an identifier character, preventing false matches on plain
# JSON object literals like {"name": q} (which start with ").
_DSL_JSON_SPLICE_INTERP = _re(
    r"f?[\"'`][\s\S]{0,300}?"
    r'"(?:match|term|range|query|bool|script|aggs|_source|fields|size|from)"\s*:'
    r"[\s\S]{0,200}?"
    r"(?:\$\{[^}]{1,80}\}|\{[A-Za-z_$][^}\n]{0,80}\})"
)

# Same DSL-key followed by `.format(`, `%`, or `+ <ident>` concat.
_DSL_JSON_SPLICE_CONCAT = _re(
    r"[\"'`]"
    r'"(?:match|term|range|script|bool|aggs|_source|size|from)"\s*:'
    r"[^\"'`]{0,200}"
    r"[\"'`]\s*"
    r"(?:\.format\("
    r"|%\s*[(\[]?[A-Za-z_]"
    r"|\+\s*[A-Za-z_])"
)


# ---- SE-008 : search-engine-lucene-expression-injection -----------------


_LUCENE_EXPR_LANG_TAG = _re(
    r'"lang"\s*:\s*["\']expression["\']'
)

# Same `source` interpolation shape as SE-001 — reused at scan time.
# We reference _PAINLESS_SOURCE_INTERPOLATED in scan_text.


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="search-engine-painless-inline-script-injection",
        name="Elasticsearch / OpenSearch inline Painless script source built from interpolation",
        severity="CRITICAL",
        description=(
            "An Elasticsearch / OpenSearch query body contains a "
            "`\"script\"` object whose `\"lang\": \"painless\"` is set "
            "AND whose `\"source\"` field is built from string "
            "interpolation (f-string, template literal, `%s`, "
            "`format()`, `+`-concat). Painless is Turing-equivalent "
            "and runs inside the cluster JVM — every untrusted byte "
            "reaching `source:` lands in a function body executed "
            "server-side. With `script.allowed_types: inline` (the "
            "default for ES ≥ 6.0) and known allow-list bypass "
            "families, this is RCE-on-the-search-node. Distinct from "
            "generic SQL/Mongo injection: the script body is part of "
            "the search query, not a side channel."
        ),
        pattern=_PAINLESS_SOURCE_INTERPOLATED,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="search-engine-get-with-script-source-bypass",
        name="Elasticsearch _search invoked as GET with ?source=... and source_content_type=application/json",
        severity="HIGH",
        description=(
            "Code issues an Elasticsearch / OpenSearch search via a "
            "**GET** with the query body URL-encoded into the "
            "`source` query-string parameter and "
            "`source_content_type=application/json`. Two security "
            "side-effects: (a) the script body is now in a GET URL "
            "(logged by proxies, CDN caches, browser history, "
            "`Referer` headers); (b) some WAF rules and "
            "`if request.method == 'POST'` checks treat GETs as "
            "read-only and skip body inspection, so a Painless script "
            "smuggled via `?source=` evades body-inspection rules. "
            "Particularly dangerous when combined with a leaky "
            "`Referer`."
        ),
        pattern=_GET_SOURCE_PARAM_FULL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="search-engine-stored-script-aliasing",
        name="Elasticsearch stored-script aliasing — script id sourced from user input",
        severity="HIGH",
        description=(
            "Code calls `PUT _scripts/<id>` (or `put_script`) with a "
            "script body, AND a later query references a stored script "
            "by `\"id\": \"<id>\"` where the id comes from user input "
            "(request body / query / template variable). The danger: "
            "(a) the write call ran with elevated credentials but "
            "the stored script inherits the write-time identity at "
            "execution; (b) the script id is now an attacker-selected "
            "*which-script-to-fire* sink — a script-selection injection "
            "channel on top of the script-execution sink."
        ),
        pattern=_STORED_SCRIPT_ID_FROM_INPUT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="search-engine-solr-velocity-response-writer",
        name="Apache Solr VelocityResponseWriter / params.resource.loader.enabled=true (CVE-2019-17558)",
        severity="CRITICAL",
        description=(
            "Solr `solrconfig.xml` (or equivalent server-side "
            "config-loader) enables `solr.VelocityResponseWriter` and "
            "sets `params.resource.loader.enabled=true` — the "
            "CVE-2019-17558 configuration that allows Velocity Server-"
            "Side Template Injection via `wt=velocity` and a template "
            "body in `v.template=...`. The CVE is widely exploited and "
            "yields RCE-equivalent execution inside the Solr JVM. "
            "Equivalently dangerous: a deployment whose `<dataDir>` is "
            "writable AND inside the core config tree, letting an "
            "authenticated attacker plant a `velocity/*.vm` template."
        ),
        pattern=_SOLR_VELOCITY_CLASS_DECL,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="search-engine-master-key-in-client-bundle",
        name="Meilisearch / Typesense / Algolia master/admin key shipped in client bundle",
        severity="CRITICAL",
        description=(
            "The application ships a master/admin API key "
            "(Meilisearch `MEILI_MASTER_KEY`, Typesense admin "
            "`api_key`, Algolia `adminAPIKey`) in a front-end build "
            "artifact (via `NEXT_PUBLIC_*` / `VITE_*` / "
            "`REACT_APP_*` / `PUBLIC_*` / `EXPO_PUBLIC_*` env-var, a "
            "`window.__CONFIG__`, or a `<meta>` tag). The browser "
            "transmits that key on every search request, exposing it "
            "to the user's network stack, browser extensions, "
            "devtools, page-source dumps, and any XSS on the page. "
            "The correct construct is a *scoped tenant key* generated "
            "server-side per session (Algolia secured API key, "
            "Meilisearch tenant token, Typesense scoped search key). "
            "Master key = drop the index / write any document / read "
            "every document — full cluster ownership."
        ),
        pattern=_FE_BUNDLED_SEARCH_ADMIN_ENV,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="search-engine-api-key-over-cleartext-http",
        name="Search-engine API key sent over cleartext http:// URL",
        severity="HIGH",
        description=(
            "Client / server code constructs a search-engine endpoint "
            "with the `http://` scheme (not `https://`) AND sends a "
            "bearer / `X-Meili-API-Key` / `X-TYPESENSE-API-KEY` / "
            "Algolia `X-Algolia-API-Key` header (or equivalent SDK "
            "property — `masterKey`, `apiKey`, `http_auth`). The key "
            "is then visible to every router, IDS, NAC appliance, and "
            "shared-WiFi listener on the path. Common in dev configs "
            "that accidentally land in production "
            "(`MEILI_HOST=http://...`), container fixtures "
            "(`http://elasticsearch:9200` + basic-auth header), and "
            "poorly-typed Helm `values.yaml` charts. Loopback / "
            "RFC-2606 reserved hosts (`localhost`, `*.example`, "
            "`*.test`, `*.local`) are excluded from the host match."
        ),
        pattern=_CLEARTEXT_HTTP_URL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="search-engine-dsl-json-splicing",
        name="Search-DSL JSON query body built by string-concatenating untrusted input",
        severity="HIGH",
        description=(
            "Code builds an Elasticsearch / OpenSearch / Solr / "
            "Meilisearch DSL query body by string-concatenating an "
            "untrusted value into a JSON template — instead of using "
            "the client library's parameter binder (`Q()`, "
            "`helpers.bulk()`, the typed query-builder DSL). The "
            "attacker controls JSON structure — they can break out of "
            "the `value` field with `\",\"script\":{...}` and append "
            "a new DSL clause (composes with the inline-Painless "
            "rule), aggregations that fan out the entire index, or "
            "`_source` field-selection that returns documents the "
            "user shouldn't see (mass-extraction). On Solr the same "
            "class allows `qt=` / `shards.qt=` overrides."
        ),
        pattern=_DSL_JSON_SPLICE_INTERP,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="search-engine-lucene-expression-injection",
        name="Elasticsearch Lucene-expression script source built from interpolation",
        severity="MEDIUM",
        description=(
            "Elasticsearch / OpenSearch supports a separate, "
            "restricted scripting language called `expression` "
            "(Lucene expressions) — intended for safe numeric "
            "scoring. It does NOT permit arbitrary class loading "
            "like Painless, but it does evaluate arbitrary "
            "arithmetic / boolean / field-access expressions. When "
            "`\"lang\": \"expression\"`'s `\"source\"` is built from "
            "untrusted input the attacker can (a) crash the search "
            "node with a deeply-nested expression, (b) build "
            "expressions whose execution time scales polynomially "
            "with index size (algorithmic DoS), and (c) read fields "
            "via dotted field-access that bypasses the `_source` "
            "filter. Severity is MEDIUM (no RCE) rather than CRITICAL "
            "but the regex skeleton is the same shape as the Painless "
            "sibling."
        ),
        pattern=_LUCENE_EXPR_LANG_TAG,
        owasp_asi="ASI-03",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no itself
    plus the next `forward` lines."""
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

      * SE-001 (painless-inline-script-injection) — `source:` with
        interpolation token AND a `lang: painless` marker within
        200 chars (5-line window).
      * SE-002 (get-with-script-source-bypass) — single regex matches
        the full URL shape (`?source=...&source_content_type=`).
      * SE-003 (stored-script-aliasing) — script-id field with
        interpolation / user-input marker. Suppressed if the read
        side is a constant string literal.
      * SE-004 (solr-velocity-response-writer) — Velocity class
        declaration. The `params.resource.loader.enabled=true`
        companion is a secondary signal (also flagged).
      * SE-005 (master-key-in-client-bundle) — env-var NAME match is
        Stage-A (always flagged). Constructor call site with
        `masterKey:` / `adminAPIKey:` is Stage-B (also flagged).
      * SE-006 (api-key-over-cleartext-http) — `http://` URL with a
        non-loopback / non-reserved host AND a search-engine key
        marker within 30 lines.
      * SE-007 (dsl-json-splicing) — DSL-key + interpolation match
        OR concat-builder match. Both emit the same rule id.
      * SE-008 (lucene-expression-injection) — `lang: expression`
        marker AND a `source:` interpolation site within a 5-line
        window of the lang marker.

    Findings are deduped by (rule_id, line, col).
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

    # ---- SE-001 : painless-inline-script-injection ----
    rule_se1 = rule_by_id["search-engine-painless-inline-script-injection"]
    for m in _PAINLESS_SOURCE_INTERPOLATED.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 5)
        if _PAINLESS_LANG_TAG.search(window) is not None:
            _emit(rule_se1, m.start(), m.group(0))

    # ---- SE-002 : get-with-script-source-bypass ----
    rule_se2 = rule_by_id["search-engine-get-with-script-source-bypass"]
    for m in _GET_SOURCE_PARAM_FULL.finditer(text):
        _emit(rule_se2, m.start(), m.group(0))
    # Pattern B: looser companion when the builder composes params over
    # multiple lines (e.g. source_content_type is set as a separate key).
    for m in _GET_SOURCE_CONTENT_TYPE.finditer(text):
        _emit(rule_se2, m.start(), m.group(0))

    # ---- SE-003 : stored-script-aliasing ----
    rule_se3 = rule_by_id["search-engine-stored-script-aliasing"]
    has_write = _file_contains(text, _STORED_SCRIPT_WRITE)
    if has_write:
        for m in _STORED_SCRIPT_ID_FROM_INPUT.finditer(text):
            _emit(rule_se3, m.start(), m.group(0))

    # ---- SE-004 : solr-velocity-response-writer ----
    rule_se4 = rule_by_id["search-engine-solr-velocity-response-writer"]
    for m in _SOLR_VELOCITY_CLASS_DECL.finditer(text):
        _emit(rule_se4, m.start(), m.group(0))
    # `wt=velocity` URL exploitation surface — also emit (same rule id).
    for m in _SOLR_WT_VELOCITY.finditer(text):
        _emit(rule_se4, m.start(), m.group(0))
    # `params.resource.loader.enabled=true` companion — also emit.
    for m in _SOLR_PARAMS_RESOURCE_LOADER_TRUE.finditer(text):
        _emit(rule_se4, m.start(), m.group(0))

    # ---- SE-005 : master-key-in-client-bundle ----
    rule_se5 = rule_by_id["search-engine-master-key-in-client-bundle"]
    for m in _FE_BUNDLED_SEARCH_ADMIN_ENV.finditer(text):
        _emit(rule_se5, m.start(), m.group(0))
    # Call-site shape — `MeiliSearch(... masterKey: ...)`.
    for m in _FE_BUNDLED_SEARCH_ADMIN_CONSTRUCTOR.finditer(text):
        _emit(rule_se5, m.start(), m.group(0))

    # ---- SE-006 : api-key-over-cleartext-http ----
    rule_se6 = rule_by_id["search-engine-api-key-over-cleartext-http"]
    has_key_marker = _file_contains(text, _SEARCH_ENGINE_KEY_MARKER)
    if has_key_marker:
        for m in _CLEARTEXT_HTTP_URL.finditer(text):
            url = m.group(0)
            # FP suppression: loopback / RFC-2606 reserved hosts.
            if _LOOPBACK_OR_RESERVED_HOST.match(url) is not None:
                continue
            # Within 30 lines of a search-engine key marker.
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 15, 15)
            if _SEARCH_ENGINE_KEY_MARKER.search(window) is None:
                continue
            _emit(rule_se6, m.start(), url)

    # ---- SE-007 : dsl-json-splicing ----
    rule_se7 = rule_by_id["search-engine-dsl-json-splicing"]
    for m in _DSL_JSON_SPLICE_INTERP.finditer(text):
        _emit(rule_se7, m.start(), m.group(0))
    for m in _DSL_JSON_SPLICE_CONCAT.finditer(text):
        _emit(rule_se7, m.start(), m.group(0))

    # ---- SE-008 : lucene-expression-injection ----
    rule_se8 = rule_by_id["search-engine-lucene-expression-injection"]
    for m in _LUCENE_EXPR_LANG_TAG.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 5)
        if _PAINLESS_SOURCE_INTERPOLATED.search(window) is not None:
            _emit(rule_se8, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
