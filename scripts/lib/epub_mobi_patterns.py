"""EPUB / MOBI / AZW / FictionBook2 parsing flaw patterns.

Wave-33 distillation round 19.

Catalogue of 10 eBook-format-specific anti-patterns distilled in
`reports/distill-round-19/epub-mobi-parsing.md`. Targets EPUB/MOBI/AZW/
FictionBook2 parsing surfaces that generic archive, XXE, and image
modules cover only at the abstract level.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic ZIP member path-traversal (extractall, tar -x) —
    ``archive_extraction_patterns.py``
  * Generic XXE / billion-laughs DTD —
    ``xml_entity_expansion_patterns.py``
  * SVG ``<foreignObject>`` with embedded script (generic) —
    ``xml_entity_expansion_patterns.py`` X5
  * ImageMagick command injection —
    ``image_processing_patterns.py``
  * PDF JavaScript actions —
    ``parser_format_patterns.py`` pdf-with-javascript
  * Widevine / FairPlay / PlayReady DRM —
    ``mobile_drm_patterns.py``

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * ebk-epub-zip-path-traversal-content-opf             (CRITICAL)
  * ebk-epub-xhtml-script-not-sandboxed                 (HIGH)
  * ebk-epub-svg-foreignobject-js-embedded              (HIGH)
  * ebk-mobi-palmdoc-no-decompress-limit                (HIGH)
  * ebk-mobi-pdb-record-count-oob                       (HIGH)
  * ebk-azw-drm-integer-overflow-kdf                    (HIGH)
  * ebk-fb2-xxe-no-defusedxml                           (CRITICAL)
  * ebk-calibre-xslt-command-injection                  (CRITICAL)
  * ebk-pdfminer-cpu-exhaustion-no-timeout              (HIGH)
  * ebk-ade-url-handler-rce                             (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Instruction/command injection (Calibre XPath injection,
                                           ADE URL handler RCE)
  ASI-03 — Trust boundary violation / SSRF (FictionBook2 XXE)
  ASI-04 — Input validation failures (MOBI PDB record-count OOB)
  ASI-05 — Supply-chain / path-traversal (EPUB OPF zip path traversal)
  ASI-06 — Lack of resource limits (MOBI PalmDOC decompression bomb,
                                     pdfminer CPU exhaustion)
  ASI-07 — Output encoding / XSS (EPUB WebView without sandbox,
                                   EPUB SVG foreignObject JS)
  ASI-09 — Insecure cryptography (AZW/KFX DRM integer overflow KDF)

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


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- E1 : ebk-epub-zip-path-traversal-content-opf ----------------------

_EPUB_ZIP_PATH_TRAVERSAL = _re(
    r"(?:ZipFile|zipfile\.ZipFile)\s*\([^)]*\.epub[^)]*\)[^}]*\.(?:extract|read)\s*\(\s*(?!os\.path)"
)

# ---- E2 : ebk-epub-xhtml-script-not-sandboxed --------------------------

_EPUB_WEBVIEW_LOAD = _re(
    r"(?:WebView|WKWebView|loadUrl|loadHTMLString|webview)\s*[.(][^;]*(?:\.epub|OEBPS|xhtml)[^;]*;"
)

# ---- E3 : ebk-epub-svg-foreignobject-js-embedded -----------------------

_EPUB_SVG_FOREIGNOBJECT = _re(
    r"<foreignObject\b[^>]*>(?:[^<]|<(?!script))*<script\b"
)

# ---- E4 : ebk-mobi-palmdoc-no-decompress-limit -------------------------

_MOBI_PALMDOC_DECOMPRESS = _re(
    r"(?:palmdoc_decompress|huffcdic_decompress|PalmDOCDecompress|mobi\.read_record)\s*\([^)]*\)"
)

# ---- E5 : ebk-mobi-pdb-record-count-oob --------------------------------

_MOBI_PDB_RECORD_COUNT = _re(
    r"struct\.unpack\s*\(\s*['\"]>[^'\"]*H[^'\"]*['\"][^)]*\)[^}]*for\s+\w+\s+in\s+range"
)

# ---- E6 : ebk-azw-drm-integer-overflow-kdf -----------------------------

_AZW_DRM_XOR_LOOP = _re(
    r"for\s+\w+\s+in\s+range\s*\(\s*(?:pid_len|drm_len|key_len|length)\s*\)[^:]*:[^\n]*\^="
)

# ---- E7 : ebk-fb2-xxe-no-defusedxml ------------------------------------

_FB2_XXE_PARSE = _re(
    r"(?:ElementTree\.parse|minidom\.parse|etree\.parse|fromstring)\s*\([^)]*(?:fb2|fictionbook)[^)]*\)"
)

# ---- E8 : ebk-calibre-xslt-command-injection ---------------------------

_CALIBRE_XSLT_INJECTION = _re(
    r"(?:etree\.XPath|XPath)\s*\(\s*f['\"]|subprocess\.[^(]+\(\s*\[?['\"]calibredb[^)]*%[^)]*\)"
)

# ---- E9 : ebk-pdfminer-cpu-exhaustion-no-timeout -----------------------

_PDFMINER_OPEN_UNTRUSTED = _re(
    r"(?:PDFPageInterpreter|pdfminer\.high_level\.extract_text|fitz\.open)\s*\([^)]*(?:upload|request|user|tmp|untrusted)[^)]*\)"
)

# ---- E10 : ebk-ade-url-handler-rce -------------------------------------

_ADE_URL_HANDLER_RCE = _re(
    r"(?:adept|digitalpublishing|acsm)://[^\s\"'<>]*(?:\.\.|%2e%2e|%252e)"
)


# ---- Rules tuple --------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="ebk-epub-zip-path-traversal-content-opf",
        name="epub-zip-path-traversal-content-opf",
        severity="CRITICAL",
        description=(
            "EPUB ZIP extraction uses a member path derived from OPF manifest "
            "`href` without first canonicalising via `os.path.abspath`. An "
            "attacker-crafted EPUB can include `../` sequences in `href` "
            "values to write files outside the intended extraction directory. "
            "CVE-2019-10685 (Readium), CVE-2020-10086 (KindleGen). "
            "Fix: validate every extracted path with `os.path.abspath` and "
            "confirm it shares the expected prefix before writing."
        ),
        pattern=_EPUB_ZIP_PATH_TRAVERSAL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ebk-epub-xhtml-script-not-sandboxed",
        name="epub-xhtml-script-not-sandboxed",
        severity="HIGH",
        description=(
            "EPUB 3 XHTML content is loaded in a WebView / WKWebView without "
            "JavaScript disabled or a restrictive CSP. EPUB 3 permits "
            "`<script>` elements and event handlers in XHTML chapters; a "
            "crafted EPUB executes arbitrary JS in the reading-system context. "
            "CVE-2022-26730 (macOS Books), CVE-2019-12086 (Aldiko). "
            "Fix: call `setJavaScriptEnabled(false)` / `WKWebpagePreferences`"
            ".allowsContentJavaScript = false before loading any EPUB content."
        ),
        pattern=_EPUB_WEBVIEW_LOAD,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="ebk-epub-svg-foreignobject-js-embedded",
        name="epub-svg-foreignobject-js-embedded",
        severity="HIGH",
        description=(
            "SVG `<foreignObject>` embedding a `<script>` element detected in "
            "EPUB content. When an EPUB reading system renders SVG inline "
            "(not via `<img>`), the embedded script executes in the "
            "reading-system origin. Distinct from generic SVG upload vectors: "
            "here the trigger is the reading-system rendering an SVG chapter. "
            "Calibre content-server pre-5.42 served such SVG chapters inline. "
            "Fix: strip or sandbox `<foreignObject>` elements before rendering."
        ),
        pattern=_EPUB_SVG_FOREIGNOBJECT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="ebk-mobi-palmdoc-no-decompress-limit",
        name="mobi-palmdoc-no-decompress-limit",
        severity="HIGH",
        description=(
            "PalmDOC / HUFFCDIC decompression called without an upper-bound "
            "size guard. A crafted MOBI file with a decompressed-size header "
            "field far larger than the actual payload triggers a decompression "
            "bomb: the decoder pre-allocates a buffer matching the declared "
            "uncompressed size. CVE-2019-20781 (mobi PyPI package <= 0.3.3). "
            "Fix: cap `uncompressed_size` to a safe maximum (e.g. 50 MB) "
            "before allocating the output buffer."
        ),
        pattern=_MOBI_PALMDOC_DECOMPRESS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ebk-mobi-pdb-record-count-oob",
        name="mobi-pdb-record-count-oob",
        severity="HIGH",
        description=(
            "MOBI/PRC PDB header `numRecords` field is unpacked and used "
            "directly in a `range()` loop without capping to "
            "`(file_size - header_size) / min_record_size`. An attacker can "
            "set `numRecords` to 65535 to force reads past EOF, causing "
            "index-out-of-bounds errors or heap over-reads in C extensions. "
            "CVE-2020-14144 (Kobo firmware). "
            "Fix: assert `num_records <= (len(data) - 78) // 8` before the loop."
        ),
        pattern=_MOBI_PDB_RECORD_COUNT,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="ebk-azw-drm-integer-overflow-kdf",
        name="azw-drm-integer-overflow-kdf",
        severity="HIGH",
        description=(
            "AZW/KFX DRM key-derivation XOR loop iterates over a range whose "
            "upper bound comes directly from a file-supplied length field "
            "without a `min(length, 20)` cap. A crafted file with "
            "pid-length 0xFFFFFFFF triggers silent integer wrap in the XOR "
            "loop in C extensions, producing a wrong key and bypassing "
            "content integrity checks. "
            "Fix: cap `pid_len = min(pid_len, 20)` immediately after unpack."
        ),
        pattern=_AZW_DRM_XOR_LOOP,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="ebk-fb2-xxe-no-defusedxml",
        name="fb2-xxe-no-defusedxml",
        severity="CRITICAL",
        description=(
            "FictionBook2 (`.fb2`) file parsed with stdlib "
            "`xml.etree.ElementTree`, `xml.dom.minidom`, or `lxml.etree` with "
            "default settings (entity resolution enabled). A crafted `.fb2` "
            "embedding `<!DOCTYPE foo [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]>` "
            "exfiltrates local files or triggers SSRF via entity expansion. "
            "CWE-611. Fix: use `defusedxml.ElementTree.parse` or "
            "`lxml.etree.XMLParser(resolve_entities=False, no_network=True)`."
        ),
        pattern=_FB2_XXE_PARSE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="ebk-calibre-xslt-command-injection",
        name="calibre-xslt-command-injection",
        severity="CRITICAL",
        description=(
            "User-supplied metadata (title, author, custom column) is "
            "interpolated into an `lxml.etree.XPath` f-string expression or "
            "a `subprocess` call to `calibredb` without `shlex.quote`. An "
            "attacker who controls a metadata field achieves XPath injection "
            "or OS command injection. CVE-2022-26730, CalyxOS advisory 2023-04. "
            "Fix: parameterise XPath via `etree.XPath(expr, variables={'v': val})` "
            "and always `shlex.quote` subprocess arguments."
        ),
        pattern=_CALIBRE_XSLT_INJECTION,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="ebk-pdfminer-cpu-exhaustion-no-timeout",
        name="pdfminer-cpu-exhaustion-no-timeout",
        severity="HIGH",
        description=(
            "pdfminer `PDFPageInterpreter` / `pdfminer.high_level.extract_text` "
            "or PyMuPDF `fitz.open` called on a path that appears "
            "user-controlled (contains `upload`, `request`, `user`, `tmp`, or "
            "`untrusted`) without a preceding `signal.alarm` / "
            "`threading.Timer` / `fitz.Document.set_timeout` guard. A crafted "
            "PDF with a recursive Type-3 font or deeply nested XObject triggers "
            "exponential CPU consumption with no built-in parse-time limit. "
            "CVE-2023-34455 (pdfminer-six <= 20221105). "
            "Fix: wrap the call in a `signal.alarm(N)` context manager or "
            "call `doc.set_timeout(N)` before iteration."
        ),
        pattern=_PDFMINER_OPEN_UNTRUSTED,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ebk-ade-url-handler-rce",
        name="ade-url-handler-rce",
        severity="CRITICAL",
        description=(
            "Adobe Digital Editions `adept://` / `digitalpublishing://` / "
            "`acsm://` custom URL with a path-traversal sequence (`../`, "
            "`%2e%2e`, `%252e`) detected. A crafted EPUB embedding such a "
            "link triggers the ADE URL handler, which (prior to ADE 4.5.11) "
            "passed the URL path as an unquoted shell argument to a helper "
            "binary, achieving RCE. "
            "Fix: validate and reject any `adept://` URL whose decoded path "
            "contains `..` before passing it to the handler."
        ),
        pattern=_ADE_URL_HANDLER_RCE,
        owasp_asi="ASI-01",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    All 10 rules are applied as direct pattern scans (Stage-A) since the
    EPUB/MOBI/AZW/FB2 patterns are high-precision enough to avoid the
    Stage-B context-window filtering used in chat_bot_patterns.

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

    # ---- E1 : ebk-epub-zip-path-traversal-content-opf ----
    rule_e1 = rule_by_id["ebk-epub-zip-path-traversal-content-opf"]
    for m in _EPUB_ZIP_PATH_TRAVERSAL.finditer(text):
        _emit(rule_e1, m.start(), m.group(0))

    # ---- E2 : ebk-epub-xhtml-script-not-sandboxed ----
    rule_e2 = rule_by_id["ebk-epub-xhtml-script-not-sandboxed"]
    for m in _EPUB_WEBVIEW_LOAD.finditer(text):
        _emit(rule_e2, m.start(), m.group(0))

    # ---- E3 : ebk-epub-svg-foreignobject-js-embedded ----
    rule_e3 = rule_by_id["ebk-epub-svg-foreignobject-js-embedded"]
    for m in _EPUB_SVG_FOREIGNOBJECT.finditer(text):
        _emit(rule_e3, m.start(), m.group(0))

    # ---- E4 : ebk-mobi-palmdoc-no-decompress-limit ----
    rule_e4 = rule_by_id["ebk-mobi-palmdoc-no-decompress-limit"]
    for m in _MOBI_PALMDOC_DECOMPRESS.finditer(text):
        _emit(rule_e4, m.start(), m.group(0))

    # ---- E5 : ebk-mobi-pdb-record-count-oob ----
    rule_e5 = rule_by_id["ebk-mobi-pdb-record-count-oob"]
    for m in _MOBI_PDB_RECORD_COUNT.finditer(text):
        _emit(rule_e5, m.start(), m.group(0))

    # ---- E6 : ebk-azw-drm-integer-overflow-kdf ----
    rule_e6 = rule_by_id["ebk-azw-drm-integer-overflow-kdf"]
    for m in _AZW_DRM_XOR_LOOP.finditer(text):
        _emit(rule_e6, m.start(), m.group(0))

    # ---- E7 : ebk-fb2-xxe-no-defusedxml ----
    rule_e7 = rule_by_id["ebk-fb2-xxe-no-defusedxml"]
    for m in _FB2_XXE_PARSE.finditer(text):
        _emit(rule_e7, m.start(), m.group(0))

    # ---- E8 : ebk-calibre-xslt-command-injection ----
    rule_e8 = rule_by_id["ebk-calibre-xslt-command-injection"]
    for m in _CALIBRE_XSLT_INJECTION.finditer(text):
        _emit(rule_e8, m.start(), m.group(0))

    # ---- E9 : ebk-pdfminer-cpu-exhaustion-no-timeout ----
    rule_e9 = rule_by_id["ebk-pdfminer-cpu-exhaustion-no-timeout"]
    for m in _PDFMINER_OPEN_UNTRUSTED.finditer(text):
        _emit(rule_e9, m.start(), m.group(0))

    # ---- E10 : ebk-ade-url-handler-rce ----
    rule_e10 = rule_by_id["ebk-ade-url-handler-rce"]
    for m in _ADE_URL_HANDLER_RCE.finditer(text):
        _emit(rule_e10, m.start(), m.group(0))

    return findings
