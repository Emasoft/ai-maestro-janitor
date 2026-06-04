"""Font Parsing Flaws — attack-pattern library.

Wave-32 distillation round 18, angle: font parsing flaws.

Catalogue of 10 font-parsing-specific anti-patterns distilled in
`reports/distill-round-18/font-parsing-flaws.md`. Targets FreeType,
HarfBuzz, WOFF/WOFF2, TrueType bytecode interpreter, variable fonts,
CSS @font-face SSRF, ImageMagick font injection, font upload without
magic-byte validation, Pillow ImageFont SBIX, and fontconfig user-path
vectors.

What is NOT here (already shipped — DO NOT duplicate):

  * ImageMagick shell-sink patterns — `image_processing_patterns.py`.
  * CSS property injection — `css_injection_patterns.py`.
  * PDF-specific font handling — `pdf_generation_patterns.py`.
  * XXE in XML font metadata — `xxe_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * fpf-freetype-face-open-unguarded                  (CRITICAL)
  * fpf-harfbuzz-shape-untrusted-font                 (HIGH)
  * fpf-woff2-brotli-decompress-untrusted             (HIGH)
  * fpf-truetype-bytecode-interpreter-on-upload       (HIGH)
  * fpf-variable-font-instancing-no-axis-bound        (HIGH)
  * fpf-css-font-face-ssrf                            (HIGH)
  * fpf-imagemagick-font-arg-injection                (HIGH)
  * fpf-font-upload-no-magic-check                    (HIGH)
  * fpf-pillow-truetype-user-path                     (HIGH)
  * fpf-fontconfig-scan-user-path                     (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

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


# ---- FP-01 : fpf-freetype-face-open-unguarded --------------------------


# FreeType face-initialisation family — the primary attack surface for
# CVE-2020-15999, CVE-2025-27363, CVE-2022-27405/6. Any call to FT_New_*Face
# on attacker-controlled font bytes belongs here.
_FREETYPE_FACE_OPEN = _re(
    r"FT_New_(?:Face|Memory_Face|Face_From_Stream)\s*\("
)


# ---- FP-02 : fpf-harfbuzz-shape-untrusted-font -------------------------


# HarfBuzz shaping entry-point. CVE-2023-25193 fires when hb_shape() is
# called on a font with a malformed GSUB/GPOS table. Matches both C and
# Python (uharfbuzz) call forms.
_HARFBUZZ_SHAPE = _re(
    r"hb_shape\s*\(|hb\.shape\s*\("
)


# ---- FP-03 : fpf-woff2-brotli-decompress-untrusted ---------------------


# Two sub-surfaces:
#   (a) fonttools TTFont() on a path that is user-derived (variable/upload/…)
#   (b) brotli.decompress() — decompressing WOFF2 table streams without an
#       orig_size sanity check. The crafted-origLength class of bugs is
#       triggered by either entry point.
_WOFF2_BROTLI_DECOMPRESS = _re(
    r"TTFont\s*\(\s*[^)]*(?:upload|request|user|tmp|path|file)[^)]*\)"
    r"|"
    r"brotli\.decompress\s*\("
)


# ---- FP-04 : fpf-truetype-bytecode-interpreter-on-upload ---------------


# FT_Load_Glyph / FT_Load_Char called with FT_LOAD_DEFAULT,
# FT_LOAD_TARGET_NORMAL, or FT_LOAD_TARGET_LIGHT — all of which enable the
# TrueType bytecode interpreter. CVE-2010-2498/2499 class.
_TTBI_LOAD = _re(
    r"FT_Load_(?:Glyph|Char)\s*\([^)]*FT_LOAD_(?:DEFAULT|TARGET_NORMAL|TARGET_LIGHT)[^)]*\)"
)


# ---- FP-05 : fpf-variable-font-instancing-no-axis-bound ----------------


# Variable-font instancing functions that enumerate fvar axis records.
# Integer overflow on axisCount * sizeof(FT_Fixed) is the vulnerability.
_VARFONT_INSTANCING = _re(
    r"instantiateVariableFont\s*\("
    r"|"
    r"FT_Set_Named_Instance\s*\("
    r"|"
    r"FT_Set_MM_Blend_Coordinates\s*\("
)


# ---- FP-06 : fpf-css-font-face-ssrf ------------------------------------


# @font-face src: url() in user-submitted CSS processed server-side
# (WeasyPrint, Puppeteer, wkhtmltopdf). The URL may point to internal
# metadata endpoints or local file paths.
_CSS_FONT_FACE_SSRF = _re(
    r"@font-face[^}]*src\s*:\s*url\s*\("
    r"|"
    r"font-face.*src.*url\("
)


# ---- FP-07 : fpf-imagemagick-font-arg-injection ------------------------


# ImageMagick convert command with a user-controlled -font argument.
# The font path is forwarded to FreeType/Pango, enabling exploitation
# of FreeType CVEs via a shell command.
_IMAGEMAGICK_FONT_ARG = _re(
    r"convert[^\"'\n]*-font[^\"'\n]*(?:\$|%|\{|format|user|request|param|upload|input)"
)


# ---- FP-08 : fpf-font-upload-no-magic-check ----------------------------


# Font file upload endpoints that check only the file extension
# (ttf/otf/woff/woff2) without reading the magic bytes. Enables all
# memory-safety CVEs above by forwarding arbitrary binary content to the
# font parser.
_FONT_UPLOAD_EXT_ONLY = _re(
    r"(?:ttf|otf|woff2?)['\"](?:\s*\)|\s*,)"
    r"|"
    r"['\"](?:ttf|otf|woff2?)['\"].*(?:save|write|copy|upload|store)"
)


# ---- FP-09 : fpf-pillow-truetype-user-path -----------------------------


# Pillow ImageFont.truetype() on a path derived from user input.
# Triggers FreeType's sbix-table parser (SBIX/color-emoji OOB class,
# CVE-2021-30727 family).
_PILLOW_TRUETYPE_USER = _re(
    r"ImageFont\.truetype\s*\([^)]*(?:upload|request|user|tmp|path|var)[^)]*\)"
)


# ---- FP-10 : fpf-fontconfig-scan-user-path -----------------------------


# fontconfig CLI tools (fc-scan, fc-query, fc-cache) or library calls
# (FcConfigAppFontAddFile / FcConfigAppFontAddDir) on user-controlled
# paths. Triggers FreeType parse; also a DoS / path-traversal vector
# via symlinks.
_FONTCONFIG_USER_PATH = _re(
    r"fc-(?:scan|query|cache)[^\"'\n]*(?:\$|%|\{|format|user|request|param|upload|input)"
    r"|"
    r"FcConfigAppFont(?:AddFile|AddDir)\s*\("
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="fpf-freetype-face-open-unguarded",
        name="FreeType FT_New_*Face called on attacker-controlled font bytes",
        severity="CRITICAL",
        description=(
            "A call to FT_New_Face(), FT_Open_Face(), or "
            "FT_New_Memory_Face() on externally supplied font bytes is "
            "the primary FreeType attack surface. CVE-2020-15999 "
            "(0-day in Chrome, exploited in the wild) was triggered by "
            "FT_Bitmap_Convert()/FT_Bitmap_Copy() on an embedded-PNG "
            "glyph when FT_LOAD_NO_BITMAP was absent. CVE-2025-27363 "
            "is a heap OOB write in SFnt_init_face() exploited on "
            "Android/Chrome (CVSS 8.1). Pin to FreeType >= 2.10.4 and "
            "set FT_LOAD_NO_BITMAP when processing untrusted input."
        ),
        pattern=_FREETYPE_FACE_OPEN,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="fpf-harfbuzz-shape-untrusted-font",
        name="HarfBuzz hb_shape() on untrusted font and text pair",
        severity="HIGH",
        description=(
            "HarfBuzz CVE-2023-25193 is a heap buffer overflow in "
            "hb_ot_shape_glyphs_closure() triggered by a malformed "
            "GSUB/GPOS table when hb_shape() is called. The attack "
            "requires both the font and the input text to be "
            "attacker-influenced (server-side thumbnail generators, "
            "PDF exporters, LaTeX renderers). Matches C (hb_shape) "
            "and Python/uharfbuzz (hb.shape)."
        ),
        pattern=_HARFBUZZ_SHAPE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="fpf-woff2-brotli-decompress-untrusted",
        name="WOFF2 brotli decompress or TTFont() on user-supplied font",
        severity="HIGH",
        description=(
            "The WOFF2 format embeds brotli-compressed table streams "
            "with an origLength header field. A crafted font sets "
            "origLength to INT_MAX; the decoder allocates an undersized "
            "buffer and the brotli decompressor writes OOB. Python "
            "vectors: fonttools TTFont() on a user-derived path, or "
            "brotli.decompress() called without orig_size sanity check. "
            "Affects the reference woff2 library used by Chrome, "
            "Firefox, and fonttools."
        ),
        pattern=_WOFF2_BROTLI_DECOMPRESS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="fpf-truetype-bytecode-interpreter-on-upload",
        name="TrueType bytecode interpreter enabled on untrusted font",
        severity="HIGH",
        description=(
            "FT_Load_Glyph/FT_Load_Char with FT_LOAD_DEFAULT, "
            "FT_LOAD_TARGET_NORMAL, or FT_LOAD_TARGET_LIGHT enables "
            "the TrueType bytecode interpreter (TTBI) — a Turing-"
            "complete stack machine with 256 opcodes. CVE-2010-2498 "
            "and CVE-2010-2499 allowed arbitrary code execution via "
            "crafted bytecode programs. Modern FreeType mitigates most "
            "of these but the interpreter remains a large attack surface "
            "with new findings per major version."
        ),
        pattern=_TTBI_LOAD,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="fpf-variable-font-instancing-no-axis-bound",
        name="Variable-font fvar axis instancing without axis-count bound check",
        severity="HIGH",
        description=(
            "OpenType variable fonts embed an fvar table with a 16-bit "
            "axisCount field. Multiplying axisCount by sizeof(FT_Fixed) "
            "without overflow checks produces an undersized allocation; "
            "subsequent axis-record parsing writes OOB. Python vector: "
            "fonttools.varLib.instancer.instantiateVariableFont() on a "
            "user-supplied variable font. C vector: FT_Set_Named_Instance "
            "or FT_Set_MM_Blend_Coordinates on a face opened from "
            "user-controlled bytes."
        ),
        pattern=_VARFONT_INSTANCING,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="fpf-css-font-face-ssrf",
        name="@font-face src: url() in user-submitted CSS — SSRF / file:// read",
        severity="HIGH",
        description=(
            "When user-submitted CSS is rendered server-side (headless "
            "Chrome, WeasyPrint, wkhtmltopdf, Playwright screenshot), a "
            "crafted @font-face rule with src: url('http://internal-host/') "
            "triggers an outbound HTTP request — leaking internal network "
            "topology via DNS resolution and timing. The file:// variant "
            "reads arbitrary local files. This is a class-B SSRF: the "
            "font-load response is not returned to the attacker but the "
            "fact of the request is observable."
        ),
        pattern=_CSS_FONT_FACE_SSRF,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="fpf-imagemagick-font-arg-injection",
        name="ImageMagick convert -font with user-controlled font path",
        severity="HIGH",
        description=(
            "ImageMagick's -annotate/-draw/convert text primitives load "
            "fonts via FreeType/Pango. When the font name or path is "
            "user-controlled, an attacker can supply an absolute path to "
            "a crafted font (-font /tmp/evil.ttf) that exploits FreeType "
            "CVEs. The vector is a shell command but the exploit payload "
            "is a font file. Ghostscript has the same issue via "
            "-sFONTPATH on user-controlled input."
        ),
        pattern=_IMAGEMAGICK_FONT_ARG,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="fpf-font-upload-no-magic-check",
        name="Font file upload accepted on extension check alone, no magic-byte validation",
        severity="HIGH",
        description=(
            "Services that accept font-file uploads (TTF/OTF/WOFF/WOFF2) "
            "for document generation or custom-branding rarely validate "
            "that the uploaded bytes are actually a valid font. An "
            "attacker uploads a crafted file with a .ttf extension but "
            "malicious binary content that exploits the parser. TTF magic: "
            "\\x00\\x01\\x00\\x00 or 'true'. OTF magic: 'OTTO'. WOFF: "
            "'wOFF'. WOFF2: 'wOF2'. Absence of magic-byte validation "
            "enables all FreeType/HarfBuzz memory-safety CVEs above."
        ),
        pattern=_FONT_UPLOAD_EXT_ONLY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="fpf-pillow-truetype-user-path",
        name="Pillow ImageFont.truetype() on user-supplied path — SBIX / OOB",
        severity="HIGH",
        description=(
            "Pillow's ImageFont.truetype() on a path derived from user "
            "input triggers FreeType's sbix-table parser. The sbix "
            "(Standard Bitmap Graphics) table stores color emoji bitmaps; "
            "its numStrikes field is parsed without count capping in "
            "vulnerable FreeType versions, walking off the end of the "
            "table. CVE-2021-30727 (macOS CoreText variant) was 0-click "
            "exploitable. Server-side thumbnail services accepting user "
            "fonts for emoji rendering are the primary attack surface."
        ),
        pattern=_PILLOW_TRUETYPE_USER,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="fpf-fontconfig-scan-user-path",
        name="fontconfig fc-scan / FcConfigAppFontAddFile on user-controlled path",
        severity="HIGH",
        description=(
            "fontconfig's fc-scan, fc-query CLI tools and the C library's "
            "FcConfigAppFontAddFile()/FcConfigAppFontAddDir() parse font "
            "files to build a font cache. When the path argument is "
            "user-controlled, an attacker can supply a crafted font to "
            "any fontconfig version with an unfixed FreeType dependency. "
            "FcConfigAppFontAddDir() follows symlinks and directory "
            "traversal if the path is not sanitised, allowing filesystem "
            "enumeration via timing side-channels even without a "
            "memory-safety CVE in FreeType."
        ),
        pattern=_FONTCONFIG_USER_PATH,
        owasp_asi="ASI-06",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - before.rfind("\n")
    return line, col


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    All 10 rules use single-pass regex scanning (no windowed multi-pass
    needed for this rule set — each pattern is self-contained and
    high-precision enough without context gating).

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

    # ---- FP-01 : fpf-freetype-face-open-unguarded ----
    rule_fp01 = rule_by_id["fpf-freetype-face-open-unguarded"]
    for m in _FREETYPE_FACE_OPEN.finditer(text):
        _emit(rule_fp01, m.start(), m.group(0))

    # ---- FP-02 : fpf-harfbuzz-shape-untrusted-font ----
    rule_fp02 = rule_by_id["fpf-harfbuzz-shape-untrusted-font"]
    for m in _HARFBUZZ_SHAPE.finditer(text):
        _emit(rule_fp02, m.start(), m.group(0))

    # ---- FP-03 : fpf-woff2-brotli-decompress-untrusted ----
    rule_fp03 = rule_by_id["fpf-woff2-brotli-decompress-untrusted"]
    for m in _WOFF2_BROTLI_DECOMPRESS.finditer(text):
        _emit(rule_fp03, m.start(), m.group(0))

    # ---- FP-04 : fpf-truetype-bytecode-interpreter-on-upload ----
    rule_fp04 = rule_by_id["fpf-truetype-bytecode-interpreter-on-upload"]
    for m in _TTBI_LOAD.finditer(text):
        _emit(rule_fp04, m.start(), m.group(0))

    # ---- FP-05 : fpf-variable-font-instancing-no-axis-bound ----
    rule_fp05 = rule_by_id["fpf-variable-font-instancing-no-axis-bound"]
    for m in _VARFONT_INSTANCING.finditer(text):
        _emit(rule_fp05, m.start(), m.group(0))

    # ---- FP-06 : fpf-css-font-face-ssrf ----
    rule_fp06 = rule_by_id["fpf-css-font-face-ssrf"]
    for m in _CSS_FONT_FACE_SSRF.finditer(text):
        _emit(rule_fp06, m.start(), m.group(0))

    # ---- FP-07 : fpf-imagemagick-font-arg-injection ----
    rule_fp07 = rule_by_id["fpf-imagemagick-font-arg-injection"]
    for m in _IMAGEMAGICK_FONT_ARG.finditer(text):
        _emit(rule_fp07, m.start(), m.group(0))

    # ---- FP-08 : fpf-font-upload-no-magic-check ----
    rule_fp08 = rule_by_id["fpf-font-upload-no-magic-check"]
    for m in _FONT_UPLOAD_EXT_ONLY.finditer(text):
        _emit(rule_fp08, m.start(), m.group(0))

    # ---- FP-09 : fpf-pillow-truetype-user-path ----
    rule_fp09 = rule_by_id["fpf-pillow-truetype-user-path"]
    for m in _PILLOW_TRUETYPE_USER.finditer(text):
        _emit(rule_fp09, m.start(), m.group(0))

    # ---- FP-10 : fpf-fontconfig-scan-user-path ----
    rule_fp10 = rule_by_id["fpf-fontconfig-scan-user-path"]
    for m in _FONTCONFIG_USER_PATH.finditer(text):
        _emit(rule_fp10, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
