"""Polyglot file detection / Content-Type confusion patterns.

Wave-29 distillation round 15, angle: polyglot files.

Catalogue of 6 polyglot-file-specific anti-patterns distilled in
`reports/distill-round-15/20260528_080658+0200-polyglot-files.md`.
Targets file-upload handlers, archive readers, and proxy mirrors that
accept file bytes based on Content-Type header or filename extension
alone, without verifying magic bytes.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * poly-extension-only-archive-dispatch          (HIGH)
  * poly-client-filename-written-verbatim          (HIGH)
  * poly-upstream-content-type-passthrough         (MEDIUM)
  * poly-attachment-missing-nosniff                (MEDIUM)
  * poly-archive-member-extension-only-decode      (MEDIUM)
  * poly-json-unsafe-cast-no-schema                (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-03 — Injection (CRLF, header injection, prompt injection via
                       malformed member content)
  ASI-05 — Security Misconfiguration (Content-Type not validated,
                                       nosniff absent, schema absent)
  ASI-06 — Vulnerable and Outdated Components (supply-chain mirror
                                               context)
  ASI-08 — Software and Data Integrity Failures (archive/package
                                                  content not verified)
  ASI-10 — Server-Side Request Forgery (unvalidated tarball URL from
                                         upstream JSON)

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
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- P1 : poly-extension-only-archive-dispatch --------------------------


# Trigger: archive format dispatched by filename extension only.
# Matches .whl / .zip / .tar.gz / .tar.bz2 / .tar.xz endswith checks
# WITHOUT a nearby magic-byte verification pattern on the same line
# or the immediately surrounding context.  Because RE2 has no lookbehind
# we match the extension check itself and rely on the scanner to apply
# the context filter.
_EXTENSION_ONLY_DISPATCH = _re(
    r'\.endswith\(\s*["\']\.(?:whl|zip|tar\.gz|tar\.bz2|tar\.xz)["\']'
    r'|\.endswith\(\s*\([^)]*(?:\.whl|\.zip|\.tar\.gz|\.tar\.bz2)[^)]*\)'
)

# Presence of a magic-byte verification pattern nearby negates the flag.
# NOTE: the word "magic" alone is intentionally excluded — it appears in
# comments like "# no magic check" and would produce false negatives.
# Only concrete code-level magic-byte markers negate the flag.
_MAGIC_BYTE_CHECK = _re(
    r"\bMAGIC_(?:ZIP|GZ|TAR|BZ2|XZ|BYTES?)\b"
    r"|"
    r"\bread_bytes\(\)\s*\[:"
    r"|"
    r"\bfrom_buffer\b"
    r"|"
    r"\\x(?:1f|50)\\x(?:8b|4b)"
    r"|"
    r'b["\']PK'
)


# ---- P2 : poly-client-filename-written-verbatim -------------------------


# Trigger: Werkzeug FileStorage .filename attribute used to build the
# destination path, with bytes written verbatim shortly after.
# We match file_obj.filename followed within 10 lines by .write_bytes(.
_FILE_OBJ_FILENAME = _re(r"\bfile_obj\.filename\b")

# Proximity marker: bytes written after filename was consumed.
_WRITE_BYTES_CALL = _re(r"\.write_bytes\(")

# Negation marker: magic-byte check or MIME validation before the write.
_MIME_OR_MAGIC_VALIDATE = _re(
    r"\bMAGIC\b"
    r"|"
    r"\bmagic\b"
    r"|"
    r"\bfrom_buffer\b"
    r"|"
    r"\bsecure_filename\b"
    r"|"
    r"\bMIME_WHITELIST\b"
    r"|"
    r"\bALLOWED_MAGIC\b"
)


# ---- P3 : poly-upstream-content-type-passthrough ------------------------


# Trigger: upstream response Content-Type header forwarded verbatim.
# Covers the Cloudflare Workers / Fetch API shape and the Express/axios
# shape.
_UPSTREAM_CT_PASSTHROUGH = _re(
    r'upstream(?:Resp|Response)\s*\.\s*headers\s*\.\s*get\s*\(\s*["\']content-type["\']'
    r"|"
    r'headers\.get\s*\(\s*["\']content-type["\'].*upstream'
)

# Negation: a magic-byte probe or explicit content-type override nearby.
_CT_VERIFICATION = _re(
    r"\bmagic\b"
    r"|"
    r"\bfrom_buffer\b"
    r"|"
    r"\\x1f\\x8b"
    r"|"
    r"\\x50\\x4b"
    r"|"
    r'safeHeaders\.set\s*\(\s*["\']content-type["\']'
    r"|"
    r"application/octet-stream"
)


# ---- P4 : poly-attachment-missing-nosniff -------------------------------


# Trigger: Content-Disposition: attachment set without a following
# X-Content-Type-Options: nosniff header in the same response.
_CONTENT_DISPOSITION_ATTACHMENT = _re(
    r'setHeader\s*\(\s*["\']Content-Disposition["\']'
    r'\s*,\s*["\']attachment'
)

# Negation: nosniff present nearby (within the same handler).
_NOSNIFF_HEADER = _re(r"X-Content-Type-Options[^=]*nosniff|nosniff")

# Also negation: global helmet() middleware usage (sets nosniff globally).
_HELMET_GLOBAL = _re(r"\bhelmet\s*\(")


# ---- P5 : poly-archive-member-extension-only-decode ---------------------


# Trigger: archive member treated as Python source solely by .py suffix.
_MEMBER_ENDSWITH_PY = _re(
    r"member\.name\.endswith\s*\(\s*['\"]\.py['\"]"
    r"|"
    r"requestedName\.endsWith\s*\(\s*['\"]\.metadata['\"]"
)

# Negation: magic-byte gate, ast.parse, or strict decode error handling.
# NOTE: decode(..., errors="replace") is itself the vulnerable pattern
# (silently accepts non-UTF-8 binary); only errors="strict" or errors="ignore"
# combined with ast.parse counts as verification. We match ast.parse or
# from_buffer as clear verification markers.
_MEMBER_CONTENT_VERIFY = _re(
    r"\bast\.parse\b"
    r"|"
    r"\bfrom_buffer\b"
    r"|"
    r'\.decode\s*\([^)]*errors\s*=\s*["\']strict["\']'
)


# ---- P6 : poly-json-unsafe-cast-no-schema -------------------------------


# Trigger: upstream JSON response cast without schema validation.
# Matches both forms:
#   `await X.json() as Type`               — direct await cast
#   `(await X.json()) as Type`             — parenthesised await cast
# without a zod/ajv/.parse()/.safeParse()/schema check nearby.
_JSON_UNSAFE_CAST = _re(
    r"\(\s*await\s+\w+\.json\(\)\s*\)\s+as\s+\w+"
    r"|"
    r"await\s+\w+\.json\(\)\s+as\s+\w+"
)

# Negation: schema validation present within the same file or handler.
_SCHEMA_VALIDATION = _re(
    r"\.parse\s*\("
    r"|"
    r"\.safeParse\s*\("
    r"|"
    r"\bschema\."
    r"|"
    r"\bz\.object\s*\("
    r"|"
    r"\bajv\b"
)


# ---- RULES tuple (canonical ordered list) -------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="poly-extension-only-archive-dispatch",
        name="Archive format dispatched by filename extension without magic-byte verification",
        severity="HIGH",
        description=(
            "Archive format is determined exclusively by filename extension "
            "(.whl, .tar.gz, .zip). No magic-byte check is performed on the "
            "file's actual bytes before dispatching to the archive reader. "
            "A polyglot payload ending in .whl but containing a PE binary "
            "or script bypasses extension-based allowlists. "
            "Fix: verify leading bytes (PK\\x03\\x04 for ZIP/wheel, "
            "\\x1f\\x8b for gzip) before dispatching."
        ),
        pattern=_EXTENSION_ONLY_DISPATCH,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="poly-client-filename-written-verbatim",
        name="Client-controlled filename used as disk path without MIME or magic-byte check",
        severity="HIGH",
        description=(
            "The Werkzeug FileStorage .filename attribute (fully controlled "
            "by the HTTP client) is used to construct the destination path "
            "and bytes are written without validating Content-Type or magic "
            "bytes. An attacker uploads evil.py named legit-1.0.0.whl; the "
            "file is stored under the attacker-supplied name, bypassing any "
            "downstream extension-based security gate. "
            "Fix: verify magic bytes before persisting; sanitise the filename "
            "with werkzeug.utils.secure_filename."
        ),
        pattern=_FILE_OBJ_FILENAME,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="poly-upstream-content-type-passthrough",
        name="Upstream Content-Type header forwarded verbatim without magic-byte probe",
        severity="MEDIUM",
        description=(
            "A proxy or mirror copies the Content-Type header from an upstream "
            "server response into its own response without independently "
            "verifying the header against the file's actual bytes. If the "
            "upstream server is compromised or misconfigured, the client will "
            "trust the incorrect content type. "
            "Fix: probe the leading bytes of the response body and set a safe "
            "Content-Type (application/octet-stream) regardless of upstream."
        ),
        pattern=_UPSTREAM_CT_PASSTHROUGH,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="poly-attachment-missing-nosniff",
        name="File download response missing X-Content-Type-Options: nosniff",
        severity="MEDIUM",
        description=(
            "A generated script or user-uploaded file is served with "
            "Content-Disposition: attachment but without the "
            "X-Content-Type-Options: nosniff header. Old browser engines "
            "or absent global helmet() middleware may sniff the content "
            "and render executable types (SVG, HTML, JS). If the disposition "
            "is later changed to inline, or if user data flows into the "
            "attachment content, this becomes an XSS vector. "
            "Fix: add res.setHeader('X-Content-Type-Options', 'nosniff') "
            "or apply helmet() globally."
        ),
        pattern=_CONTENT_DISPOSITION_ATTACHMENT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="poly-archive-member-extension-only-decode",
        name="Archive member treated as Python source based solely on .py suffix",
        severity="MEDIUM",
        description=(
            "When iterating archive members inside a .whl or .tar.gz, "
            "member filenames ending in .py are decoded as UTF-8 Python "
            "source without verifying that the bytes are valid UTF-8 text "
            "or valid Python syntax. A polyglot binary blob with .py "
            "appended to its name passes the filter and is submitted "
            "verbatim to the LLM or rule engine (prompt injection risk). "
            "Fix: decode with errors='strict', attempt ast.parse(), "
            "and skip members that fail either check."
        ),
        pattern=_MEMBER_ENDSWITH_PY,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="poly-json-unsafe-cast-no-schema",
        name="Upstream JSON response cast to type without schema validation",
        severity="MEDIUM",
        description=(
            "An npm or PyPI proxy casts the upstream JSON response to a "
            "TypeScript type (await X.json() as Type) without running a "
            "schema validation step (zod, ajv, etc.). If the upstream "
            "registry returns a crafted payload, the proxy faithfully relays "
            "unvalidated tarball URLs to clients (SSRF pivot) or relays "
            "XSS payloads in description fields to browser UIs. "
            "Fix: validate with zod .parse() or .safeParse() before "
            "consuming any upstream JSON field."
        ),
        pattern=_JSON_UNSAFE_CAST,
        owasp_asi="ASI-05",
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

      * P1 (extension-only-archive-dispatch) — anchor on the endswith()
        extension check; require NO magic-byte verification pattern in a
        10-line symmetric window around the match.
      * P2 (client-filename-written-verbatim) — anchor on file_obj.filename
        and require BOTH: a .write_bytes( call within 10 forward lines
        AND NO MIME / magic validation in the same window.
      * P3 (upstream-content-type-passthrough) — anchor on the
        upstream headers.get('content-type') call; require NO
        magic-byte probe or content-type override in a 15-line window.
      * P4 (attachment-missing-nosniff) — anchor on
        Content-Disposition: attachment; require NO X-Content-Type-Options
        nosniff in a 20-line forward window AND NO global helmet() call
        anywhere in the file.
      * P5 (archive-member-extension-only-decode) — anchor on
        member.name.endswith('.py'); require NO ast.parse, magic, or
        decode-with-errors in a 15-line forward window.
      * P6 (json-unsafe-cast-no-schema) — require NO schema validation
        pattern (zod / ajv / .parse) anywhere in the file.

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

    # ---- P1 : poly-extension-only-archive-dispatch ----
    rule_p1 = rule_by_id["poly-extension-only-archive-dispatch"]
    for m in _EXTENSION_ONLY_DISPATCH.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 10)
        if _MAGIC_BYTE_CHECK.search(window) is not None:
            continue
        _emit(rule_p1, m.start(), m.group(0))

    # ---- P2 : poly-client-filename-written-verbatim ----
    rule_p2 = rule_by_id["poly-client-filename-written-verbatim"]
    for m in _FILE_OBJ_FILENAME.finditer(text):
        line, _ = _line_col(text, m.start())
        window_fwd = _slice_forward(text, line, 10)
        if _WRITE_BYTES_CALL.search(window_fwd) is None:
            continue
        window_full = _slice_window(text, line, 3, 10)
        if _MIME_OR_MAGIC_VALIDATE.search(window_full) is not None:
            continue
        _emit(rule_p2, m.start(), m.group(0))

    # ---- P3 : poly-upstream-content-type-passthrough ----
    rule_p3 = rule_by_id["poly-upstream-content-type-passthrough"]
    for m in _UPSTREAM_CT_PASSTHROUGH.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 15)
        if _CT_VERIFICATION.search(window) is not None:
            continue
        _emit(rule_p3, m.start(), m.group(0))

    # ---- P4 : poly-attachment-missing-nosniff ----
    rule_p4 = rule_by_id["poly-attachment-missing-nosniff"]
    has_helmet = _file_contains(text, _HELMET_GLOBAL)
    if not has_helmet:
        for m in _CONTENT_DISPOSITION_ATTACHMENT.finditer(text):
            line, _ = _line_col(text, m.start())
            window_fwd = _slice_forward(text, line, 20)
            if _NOSNIFF_HEADER.search(window_fwd) is not None:
                continue
            _emit(rule_p4, m.start(), m.group(0))

    # ---- P5 : poly-archive-member-extension-only-decode ----
    rule_p5 = rule_by_id["poly-archive-member-extension-only-decode"]
    for m in _MEMBER_ENDSWITH_PY.finditer(text):
        line, _ = _line_col(text, m.start())
        window_fwd = _slice_forward(text, line, 15)
        if _MEMBER_CONTENT_VERIFY.search(window_fwd) is not None:
            continue
        _emit(rule_p5, m.start(), m.group(0))

    # ---- P6 : poly-json-unsafe-cast-no-schema ----
    rule_p6 = rule_by_id["poly-json-unsafe-cast-no-schema"]
    has_schema = _file_contains(text, _SCHEMA_VALIDATION)
    if not has_schema:
        for m in _JSON_UNSAFE_CAST.finditer(text):
            _emit(rule_p6, m.start(), m.group(0))

    return findings
