"""CSV / spreadsheet formula injection patterns (CWE-1236).

Wave-28 distillation round 14, angle csv-formula-injection.

Catalogue of 7 patterns distilled in
`reports/distill-round-14/csv-formula-injection.md`. Targets Python
csv.writer / csv.DictWriter / pandas.to_csv, TypeScript Blob-join CSV
export, bare f-string CSV construction, and gspread USER_ENTERED upload.

What is NOT here (handled elsewhere):

  * Generic SQL injection — `db_injection_patterns.py`.
  * Generic server-side template injection — `parser_format_patterns.py`.
  * HTML injection in output formats — `output_formats.py`.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * csv-formula-writer-quote-minimal          (HIGH)
  * csv-formula-dictwriter-quote-minimal      (HIGH)
  * csv-formula-escape-no-prefix-guard        (HIGH)
  * csv-formula-quote-all-newline-only-strip  (MEDIUM)
  * csv-formula-pandas-to-csv-default         (HIGH)
  * csv-formula-fstring-bare-csv              (MEDIUM)
  * csv-formula-gspread-user-entered          (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-03 — Injection (CSV formula injection / formula execution)

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


# ---- CSVFI-001 : csv.writer with QUOTE_MINIMAL --------------------------

# Match the csv.writer( call anchor.  We then require that the SAME
# parenthesised argument span does NOT contain a safe quoting override.
# Strategy: match the token, then separately reject via a negative scan
# done in scan_text (see _CSV_WRITER_SAFE_QUOTING below).
_CSV_WRITER_CALL = _re(r"\bcsv\.writer\s*\(")

# RE2-safe guard: a quoting= keyword argument set to QUOTE_ALL or
# QUOTE_NONNUMERIC anywhere within 200 chars of the opening paren.
_CSV_WRITER_SAFE_QUOTING = _re(
    r"\bquoting\s*=\s*csv\.QUOTE_(?:ALL|NONNUMERIC)\b"
)


# ---- CSVFI-002 : csv.DictWriter with QUOTE_MINIMAL ----------------------

# Same two-pattern approach as CSVFI-001.
_CSV_DICTWRITER_CALL = _re(r"\bcsv\.DictWriter\s*\(")
_CSV_DICTWRITER_SAFE_QUOTING = _CSV_WRITER_SAFE_QUOTING


# ---- CSVFI-003 : escapeCSV / escapeCSVField without formula-prefix guard

# Matches an escape*CSV* function that contains includes(",") or includes('"')
# (the comma/quote guard) but lacks a startsWith("=") formula-prefix check.
# Two separate patterns; scan_text combines them with AND logic.
_ESCAPE_CSV_FUNC_DECL = _re(
    r"function\s+\w*[Ee]scape[Cc][Ss][Vv]\w*\s*\([^)]{0,80}\)"
)

# Present in vulnerable functions: guards quotes/commas but not formula prefix.
_ESCAPE_CSV_COMMA_GUARD = _re(r'\.includes\s*\(\s*["\'],["\']\s*\)')

# Absent in vulnerable functions: formula-prefix startsWith guard.
_ESCAPE_CSV_PREFIX_GUARD = _re(
    r'\.startsWith\s*\(\s*["\'][=+\-@]["\']'
)


# ---- CSVFI-004 : QUOTE_ALL + newline-strip but no formula-prefix strip ---

# Matches the .replace("\n", ...) sanitisation pattern (with an optional
# chained .replace("\r", ...)) that strips newlines but does NOT follow up
# with a formula-prefix strip (lstrip("=+-@") or equivalent).
_QUOTE_ALL_NEWLINE_ONLY_STRIP = _re(
    r'\.replace\s*\(\s*["\']\\n["\']\s*,\s*["\'][^"\']{0,4}["\']\s*\)'
    r'(?:\s*\.replace\s*\(\s*["\']\\r["\']\s*,\s*["\'][^"\']{0,4}["\']\s*\))?'
)


# ---- CSVFI-005 : pandas DataFrame.to_csv() default quoting --------------

# Matches df.to_csv( / DataFrame.to_csv( calls without an explicit
# quoting= override to QUOTE_ALL or QUOTE_NONNUMERIC.
_PANDAS_TO_CSV_DEFAULT = _re(
    r"\bdf\.to_csv\s*\(\s*[^)]{0,200}\)"
    r"|"
    r"\bDataFrame\.to_csv\s*\(\s*[^)]{0,200}\)"
)


# ---- CSVFI-006 : bare f-string / template-literal CSV construction ------

# Matches Python f-strings (two+ {var} placeholders separated by a comma)
# OR TypeScript/JS template literals (two+ ${} separated by a comma).
# RE2-safe: no nested quantifiers, no backreferences.
_FSTRING_BARE_CSV_COMBINED = _re(
    r'(?:f["\'].*\{[^}]+\},[^"\']*\{[^}]+\}.*["\']'
    r"|"
    r"`[^`]*\$\{[^}]+\},[^`]*\$\{[^}]+\}[^`]*`)"
)


# ---- CSVFI-007 : gspread / Sheets API with USER_ENTERED -----------------

# Matches value_input_option / valueInputOption set to USER_ENTERED —
# the mode that causes Google Sheets to evaluate injected formulas.
_GSPREAD_USER_ENTERED = _re(
    r'\bvalue_?[Ii]nput_?[Oo]ption\s*[=:]\s*["\']?USER_ENTERED["\']?'
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="csv-formula-writer-quote-minimal",
        name="csv.writer without QUOTE_ALL/QUOTE_NONNUMERIC emits formula-prefix strings",
        severity="HIGH",
        description=(
            "csv.writer defaults to QUOTE_MINIMAL, which does not quote "
            "fields that start with formula-trigger characters (=, +, -, @). "
            "Attacker-controlled values such as file paths or commit messages "
            "written as CSV rows can be executed as formulas when the output "
            "is opened in Excel or LibreOffice Calc. Use "
            "quoting=csv.QUOTE_ALL or strip formula prefixes before writing. "
            "CWE-1236."
        ),
        pattern=_CSV_WRITER_CALL,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="csv-formula-dictwriter-quote-minimal",
        name="csv.DictWriter without QUOTE_ALL/QUOTE_NONNUMERIC emits formula-prefix strings",
        severity="HIGH",
        description=(
            "csv.DictWriter defaults to QUOTE_MINIMAL. Security audit scripts "
            "that write package names (PyPI/npm) or vulnerability metadata "
            "into CSV rows via DictWriter expose formula-injection: a "
            "malicious package named =cmd|' /C calc'!A0 is written verbatim "
            "and executed when the CSV is opened. Use quoting=csv.QUOTE_ALL "
            "or sanitise values before writerows(). CWE-1236."
        ),
        pattern=_CSV_DICTWRITER_CALL,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="csv-formula-escape-no-prefix-guard",
        name="escapeCSVField function guards quotes/commas but not formula prefixes",
        severity="HIGH",
        description=(
            "A TypeScript/JavaScript escapeCSV* function that wraps fields "
            "containing commas or double-quotes in quotes but does not "
            "prepend a leading apostrophe (') to values starting with "
            "=, +, -, or @ leaves formula execution possible. The function "
            "returns the raw stringValue unchanged for formula-prefixed "
            "strings, which Excel/LibreOffice interpret as live formulas. "
            "CWE-1236."
        ),
        pattern=_ESCAPE_CSV_FUNC_DECL,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="csv-formula-quote-all-newline-only-strip",
        name="csv.writer QUOTE_ALL: newline-stripped excerpt still carries formula prefix",
        severity="MEDIUM",
        description=(
            "Using QUOTE_ALL prevents most formula injection in Excel, but "
            "OpenDocument Calc and Google Sheets evaluate formula-prefix "
            "strings even inside quoted cells on import. A sanitiser that "
            "only strips newlines (replace('\\n', ' ')) but not formula "
            "prefixes (=, +, -, @) in masked_excerpt / code snippet fields "
            "leaves a partial bypass. Add lstrip('=+-@') or a formula-prefix "
            "guard after the newline replacement. CWE-1236."
        ),
        pattern=_QUOTE_ALL_NEWLINE_ONLY_STRIP,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="csv-formula-pandas-to-csv-default",
        name="pandas DataFrame.to_csv() default quoting emits formula-prefix values",
        severity="HIGH",
        description=(
            "pandas.DataFrame.to_csv() uses csv.QUOTE_MINIMAL by default. "
            "Any DataFrame column sourced from external data (package names, "
            "CVE summaries, attack-vector labels from an OSV or PyPI API) "
            "is written without formula-prefix sanitisation. Pass "
            "quoting=csv.QUOTE_ALL or sanitise string columns before export. "
            "CWE-1236."
        ),
        pattern=_PANDAS_TO_CSV_DEFAULT,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="csv-formula-fstring-bare-csv",
        name="Bare f-string or template-literal CSV construction without quoting",
        severity="MEDIUM",
        description=(
            "CSV files constructed via Python f-strings or TypeScript/JS "
            "template literals (f'{a},{b}\\n' / `${a},${b}`) bypass the "
            "csv module entirely and receive no quoting protection. "
            "If any interpolated variable originates from external input "
            "(user data, market-data feeds, package metadata), a formula "
            "prefix in that value is written verbatim. Use the csv module "
            "with QUOTE_ALL or validate that all interpolated values are "
            "purely numeric. CWE-1236."
        ),
        pattern=_FSTRING_BARE_CSV_COMBINED,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="csv-formula-gspread-user-entered",
        name="gspread / Sheets API upload with USER_ENTERED triggers formula evaluation",
        severity="HIGH",
        description=(
            "Uploading CSV report rows to Google Sheets with "
            "value_input_option='USER_ENTERED' (or valueInputOption: "
            "'USER_ENTERED') instructs Sheets to evaluate cell values as "
            "formulas. If the uploaded data contains formula-prefix strings "
            "from scanner output (file paths, package names, code excerpts), "
            "Sheets executes them — enabling IMPORTXML/WEBSERVICE exfiltration. "
            "Use RAW input option unless the upload intentionally contains "
            "user-authored formulas. CWE-1236."
        ),
        pattern=_GSPREAD_USER_ENTERED,
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


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    Three rules use multi-pattern AND/NOT logic evaluated in scan_text:

      * csv-formula-writer-quote-minimal (CSVFI-001) — fire on csv.writer(
        calls ONLY when no quoting=csv.QUOTE_ALL/NONNUMERIC exists within
        200 chars following the opening paren.
      * csv-formula-dictwriter-quote-minimal (CSVFI-002) — same guard for
        csv.DictWriter(.
      * csv-formula-escape-no-prefix-guard (CSVFI-003) — fire on
        escape*CSV* function declarations ONLY when a comma/quote guard
        (.includes(",")) is present but a formula-prefix startsWith guard
        is absent within the function body (next 600 chars).

    All other rules use a simple single-pattern scan.

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

    # ---- CSVFI-001 : csv.writer without safe quoting --------------------
    rule_001 = rule_by_id["csv-formula-writer-quote-minimal"]
    for m in _CSV_WRITER_CALL.finditer(text):
        window = text[m.start(): m.start() + 200]
        if not _CSV_WRITER_SAFE_QUOTING.search(window):
            _emit(rule_001, m.start(), m.group())

    # ---- CSVFI-002 : csv.DictWriter without safe quoting ----------------
    rule_002 = rule_by_id["csv-formula-dictwriter-quote-minimal"]
    for m in _CSV_DICTWRITER_CALL.finditer(text):
        window = text[m.start(): m.start() + 200]
        if not _CSV_DICTWRITER_SAFE_QUOTING.search(window):
            _emit(rule_002, m.start(), m.group())

    # ---- CSVFI-003 : escapeCSV with comma guard but no prefix guard -----
    rule_003 = rule_by_id["csv-formula-escape-no-prefix-guard"]
    for m in _ESCAPE_CSV_FUNC_DECL.finditer(text):
        window = text[m.start(): m.start() + 600]
        if _ESCAPE_CSV_COMMA_GUARD.search(window) and not _ESCAPE_CSV_PREFIX_GUARD.search(window):
            _emit(rule_003, m.start(), m.group())

    # ---- CSVFI-004 through CSVFI-007 : simple single-pattern scan -------
    _simple_rule_ids = {
        "csv-formula-quote-all-newline-only-strip",
        "csv-formula-pandas-to-csv-default",
        "csv-formula-fstring-bare-csv",
        "csv-formula-gspread-user-entered",
    }
    for rule in RULES:
        if rule.id not in _simple_rule_ids:
            continue
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group())

    return findings
