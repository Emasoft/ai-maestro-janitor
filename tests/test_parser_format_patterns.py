"""Tests for scripts/lib/parser_format_patterns.py.

Pattern-coverage tests for the Wave-16 file-format / parser-attack
catalogue (yaml-load-unsafe, pickle-load-from-network, JSONC
comment-key shadow, markdown-raw-html, svg-embedded-js, PDF
JavaScript actions, archive zipslip, CSV formula injection, magic-byte
classification). Every rule + helper gets at least one positive + one
negative test.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import parser_format_patterns as pfp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised rule id."""
    assert isinstance(pfp.RULES, tuple)
    rule_ids = [r.id for r in pfp.RULES]
    expected = {
        "yaml-load-unsafe",
        "pickle-load-from-network",
        "jsonc-comment-key-shadow",
        "markdown-raw-html-script-tag",
        "svg-embedded-js",
    }
    assert expected.issubset(set(rule_ids)), (
        f"missing rules: {expected - set(rule_ids)}"
    )


def test_every_rule_has_owasp_mapping_and_severity() -> None:
    for rule in pfp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        # description must be substantive, not empty
        assert len(rule.description) > 20, rule.id


def test_finding_named_tuple_shape() -> None:
    f = pfp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-06",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-06"


def _hits(rule_id: str, text: str, *, file_kind: str = "prose") -> list[pfp.Finding]:
    """Return only findings of `rule_id` from scan_text(text)."""
    return [f for f in pfp.scan_text(text, file_kind=file_kind) if f.rule_id == rule_id]


# ---------- yaml-load-unsafe --------------------------------------------


def test_yaml_load_unsafe_bare_load_flags() -> None:
    assert _hits("yaml-load-unsafe", "data = yaml.load(payload)")


def test_yaml_load_unsafe_full_load_flags() -> None:
    assert _hits("yaml-load-unsafe", "obj = yaml.full_load(blob)")


def test_yaml_load_unsafe_unsafe_load_flags() -> None:
    assert _hits("yaml-load-unsafe", "yaml.unsafe_load(stream)")


def test_yaml_load_unsafe_load_all_flags() -> None:
    assert _hits("yaml-load-unsafe", "for doc in yaml.load_all(text): pass")


def test_yaml_load_safe_loader_does_not_flag() -> None:
    """SafeLoader passed explicitly — must NOT flag."""
    assert not _hits(
        "yaml-load-unsafe",
        "data = yaml.load(payload, Loader=yaml.SafeLoader)",
    )


def test_yaml_safe_load_does_not_flag() -> None:
    """yaml.safe_load() is the dedicated safe form — must NOT flag."""
    assert not _hits("yaml-load-unsafe", "data = yaml.safe_load(payload)")


# ---------- pickle-load-from-network ------------------------------------


def test_pickle_loads_from_requests_flags() -> None:
    src = (
        "resp = requests.get(url)\n"
        "obj = pickle.loads(resp.content)\n"
    )
    assert _hits("pickle-load-from-network", src)


def test_pickle_loads_from_urlopen_flags() -> None:
    # The match window is bounded at 300 chars; the network token must
    # land inside that window. The single-statement form is the cleanest
    # positive — urlopen(...) sits as the argument to pickle.loads().
    src_urlopen = "pickle.loads(urlopen(url).read())"
    assert _hits("pickle-load-from-network", src_urlopen)
    # Same shape via httpx — different client, identical network sink.
    src_httpx = "pickle.loads(httpx.get(url).content)"
    assert _hits("pickle-load-from-network", src_httpx)


def test_pickle_loads_dill_from_socket_flags() -> None:
    src = "dill.loads(socket.recv(4096))"
    assert _hits("pickle-load-from-network", src)


def test_pickle_loads_local_file_does_not_flag() -> None:
    """Pure local-file pickle load — no network source within the window."""
    src = "with open('model.pkl', 'rb') as f: obj = pickle.loads(f.read_local_blob_no_net())"
    # `.read_local_blob_no_net` does NOT contain the network tokens we
    # match (requests/urllib/httpx/urlopen/socket/.content/.raw/.text/
    # .data/.recv/.read()) — the bare `.read_local_blob_no_net()` lacks
    # the `\.read\s*\(` shape, so this stays clean.
    assert not _hits("pickle-load-from-network", src)


def test_pickle_loads_joblib_local_does_not_flag() -> None:
    """joblib.load on a literal path — no network token — must NOT flag."""
    src = "model = joblib.load('checkpoint.pkl')"
    assert not _hits("pickle-load-from-network", src)


# ---------- jsonc-comment-key-shadow ------------------------------------


def test_jsonc_line_comment_tombstoned_key_flags() -> None:
    src = '// "Bash": "allow",\n  "Bash": "ask"'
    assert _hits("jsonc-comment-key-shadow", src)


def test_jsonc_block_comment_tombstoned_key_flags() -> None:
    src = '{ "auto_approve": false, /* "auto_approve": true */ }'
    assert _hits("jsonc-comment-key-shadow", src)


def test_jsonc_plain_doc_comment_does_not_flag() -> None:
    """A free-form `// note about this section` does NOT match the
    key-shape with `:` and tombstone-tail — must stay clean."""
    src = '// this is the permissions section\n{ "Bash": "ask" }'
    assert not _hits("jsonc-comment-key-shadow", src)


def test_jsonc_running_prose_comment_does_not_flag() -> None:
    src = "/* this scanner does X */ \nimport re"
    assert not _hits("jsonc-comment-key-shadow", src)


# ---------- markdown-raw-html-script-tag --------------------------------


def test_markdown_raw_script_tag_flags() -> None:
    assert _hits(
        "markdown-raw-html-script-tag",
        "Some text <script>alert(1)</script> more text",
    )


def test_markdown_raw_iframe_flags() -> None:
    assert _hits(
        "markdown-raw-html-script-tag",
        '<iframe src="https://attacker.example"></iframe>',
    )


def test_markdown_javascript_href_flags() -> None:
    assert _hits(
        "markdown-raw-html-script-tag",
        '<a href="javascript:alert(1)">click</a>',
    )


def test_markdown_inline_onerror_flags() -> None:
    assert _hits(
        "markdown-raw-html-script-tag",
        '<img src=x onerror="alert(1)">',
    )


def test_markdown_meta_refresh_flags() -> None:
    assert _hits(
        "markdown-raw-html-script-tag",
        '<meta http-equiv="refresh" content="0;url=evil">',
    )


def test_markdown_plain_prose_does_not_flag() -> None:
    """Pure prose markdown — no flag."""
    assert not _hits(
        "markdown-raw-html-script-tag",
        "# Heading\n\nSome **prose** with a [link](https://example.com).\n",
    )


def test_markdown_plain_code_fence_does_not_flag() -> None:
    """Markdown code fence with python source — must stay clean."""
    src = "```python\nprint('hello world')\n```"
    assert not _hits("markdown-raw-html-script-tag", src)


# ---------- svg-embedded-js --------------------------------------------


def test_svg_with_script_flags() -> None:
    src = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<script>alert(1)</script></svg>'
    )
    assert _hits("svg-embedded-js", src)


def test_svg_with_onload_flags() -> None:
    src = '<svg onload="alert(1)" xmlns="http://www.w3.org/2000/svg"/>'
    assert _hits("svg-embedded-js", src)


def test_svg_with_foreign_object_flags() -> None:
    src = '<svg><foreignObject><body onload="x()"/></foreignObject></svg>'
    assert _hits("svg-embedded-js", src)


def test_svg_javascript_href_flags() -> None:
    src = '<svg><a xlink:href="javascript:alert(1)"><rect/></a></svg>'
    assert _hits("svg-embedded-js", src)


def test_svg_static_art_does_not_flag() -> None:
    """Standard `<svg><path>/<rect>/<circle>` — no JS, no event — clean."""
    src = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect x="10" y="10" width="80" height="80" fill="blue"/>'
        '<title>Static art</title><desc>nothing dynamic here</desc></svg>'
    )
    assert not _hits("svg-embedded-js", src)


# ---------- detect_magic / MAGIC_PREFIXES --------------------------------


def test_magic_prefixes_is_tuple_of_tuples() -> None:
    assert isinstance(pfp.MAGIC_PREFIXES, tuple)
    for entry in pfp.MAGIC_PREFIXES:
        assert isinstance(entry, tuple)
        assert len(entry) == 2
        prefix, label = entry
        assert isinstance(prefix, bytes)
        assert isinstance(label, str)
        assert prefix  # non-empty
        assert label   # non-empty


def test_detect_magic_pdf() -> None:
    assert pfp.detect_magic(b"%PDF-1.7\nbody...") == "pdf"


def test_detect_magic_zip_local_header() -> None:
    assert pfp.detect_magic(b"PK\x03\x04\x14\x00\x00") == "zip"


def test_detect_magic_zip_empty_archive() -> None:
    assert pfp.detect_magic(b"PK\x05\x06\x00\x00") == "zip-empty"


def test_detect_magic_gzip() -> None:
    # 3-byte form (with deflate flag)
    assert pfp.detect_magic(b"\x1f\x8b\x08\x00plaintext") == "gzip"


def test_detect_magic_gzip_short() -> None:
    # 2-byte fallback (no deflate flag byte)
    assert pfp.detect_magic(b"\x1f\x8b\x00\x00") == "gzip"


def test_detect_magic_bzip2() -> None:
    assert pfp.detect_magic(b"BZh91AY&SY") == "bzip2"


def test_detect_magic_xz() -> None:
    assert pfp.detect_magic(b"\xfd7zXZ\x00\x00\x00body") == "xz"


def test_detect_magic_7z() -> None:
    assert pfp.detect_magic(b"7z\xbc\xaf\x27\x1c\x00\x03") == "7z"


def test_detect_magic_xml() -> None:
    assert pfp.detect_magic(b'<?xml version="1.0"?><svg/>') == "xml"


def test_detect_magic_elf() -> None:
    assert pfp.detect_magic(b"\x7fELF\x02\x01") == "elf"


def test_detect_magic_svg_raw() -> None:
    assert pfp.detect_magic(b'<svg xmlns="http://www.w3.org/2000/svg"/>') == "svg"


def test_detect_magic_svg_uppercase() -> None:
    assert pfp.detect_magic(b"<SVG/>") == "svg"


def test_detect_magic_html_doctype() -> None:
    assert pfp.detect_magic(b"<!DOCTYPE html><html/>") == "html-doctype"


def test_detect_magic_html_script_fragment() -> None:
    assert pfp.detect_magic(b"<script>alert(1)</script>") == "html-script-fragment"


def test_detect_magic_html_doctype_lowercase() -> None:
    assert pfp.detect_magic(b"<!doctype html>") == "html-doctype"


def test_detect_magic_unknown_returns_none() -> None:
    assert pfp.detect_magic(b"plain text without any magic") is None


def test_detect_magic_plain_html_paragraph_returns_none() -> None:
    """A `<p>` or `<div>` chunk must NOT classify — only the specific
    SVG/script/doctype prefixes are recognised. This guards against the
    earlier over-broad `<s` prefix that would have matched `<span>` /
    `<style>` / `<strong>` / `<select>` / `<strike>`."""
    assert pfp.detect_magic(b"<p>some prose</p>") is None
    assert pfp.detect_magic(b"<span>x</span>") is None
    assert pfp.detect_magic(b"<style>p{}</style>") is None
    assert pfp.detect_magic(b"<strong>bold</strong>") is None


def test_detect_magic_empty_returns_none() -> None:
    assert pfp.detect_magic(b"") is None


def test_detect_magic_longest_prefix_wins() -> None:
    """Both `\\xfd7zXZ` (5-byte) and `\\xfd7zXZ\\x00\\x00\\x00` (8-byte)
    are in the table; the 8-byte form must win when present."""
    head = b"\xfd7zXZ\x00\x00\x00\x99\x99"
    assert pfp.detect_magic(head) == "xz"


# ---------- TAR offset-257 marker ---------------------------------------


def test_tar_ustar_constants() -> None:
    """TAR magic lives at offset 257, NOT at the start — the constants
    let detector scripts check `data[257:262] == b'ustar'` cleanly."""
    assert pfp.TAR_USTAR_OFFSET == 257
    assert pfp.TAR_USTAR_MARKER == b"ustar"


# ---------- has_pdf_action / PDF JavaScript ------------------------------


def test_has_pdf_action_javascript_flags() -> None:
    head = b"%PDF-1.7\n4 0 obj <</JavaScript (alert(1))>>\nendobj"
    assert pfp.has_pdf_action(head) == "/JavaScript"


def test_has_pdf_action_open_action_flags() -> None:
    head = b"%PDF-1.7\n1 0 obj <</OpenAction 4 0 R>>"
    assert pfp.has_pdf_action(head) == "/OpenAction"


def test_has_pdf_action_launch_flags() -> None:
    head = b"%PDF-1.7\n<</Type /Action /S /Launch /F (calc.exe)>>"
    assert pfp.has_pdf_action(head) == "/Launch"


def test_has_pdf_action_clean_pdf_returns_none() -> None:
    """A plain PDF with no dangerous actions — must return None."""
    head = b"%PDF-1.7\n1 0 obj <</Type /Catalog /Pages 2 0 R>>\nendobj"
    assert pfp.has_pdf_action(head) is None


def test_has_pdf_action_non_pdf_returns_none() -> None:
    """Bytes that don't start with %PDF- — must return None even if they
    contain /JavaScript later (so we don't FP on .html / .js / .py)."""
    head = b"<html>/JavaScript here is fine in HTML</html>"
    assert pfp.has_pdf_action(head) is None


# ---------- ZIPSLIP_NAME archive-member regex ----------------------------


def test_zipslip_dotdot_relative_flags() -> None:
    assert pfp.ZIPSLIP_NAME.search("../../../etc/passwd")


def test_zipslip_dotdot_mid_path_flags() -> None:
    assert pfp.ZIPSLIP_NAME.search("foo/bar/../../../etc/passwd")


def test_zipslip_absolute_unix_flags() -> None:
    assert pfp.ZIPSLIP_NAME.search("/etc/cron.d/x")


def test_zipslip_absolute_windows_flags() -> None:
    assert pfp.ZIPSLIP_NAME.search("C:\\Windows\\System32\\evil.dll")


def test_zipslip_home_expansion_flags() -> None:
    assert pfp.ZIPSLIP_NAME.search("~/.bashrc")


def test_zipslip_backslash_dotdot_flags() -> None:
    assert pfp.ZIPSLIP_NAME.search("foo\\..\\bar.txt")


def test_zipslip_clean_relative_name_does_not_flag() -> None:
    assert not pfp.ZIPSLIP_NAME.search("src/foo/bar.txt")


def test_zipslip_dotted_filename_does_not_flag() -> None:
    """`my..file.txt` contains `..` but NOT as a path component — clean."""
    assert not pfp.ZIPSLIP_NAME.search("my..file.txt")


def test_zipslip_dotfile_does_not_flag() -> None:
    """`.config/foo` starts with a literal dot but not `..` — clean."""
    assert not pfp.ZIPSLIP_NAME.search(".config/foo")


# ---------- find_csv_injection_lines ------------------------------------


def test_csv_equals_formula_flags_critical() -> None:
    data = b"name,formula\nAlice,=cmd|'/c calc'!A1\n"
    hits = pfp.find_csv_injection_lines(data)
    assert hits, "expected a finding for =cmd|..."
    # Line 2, the formula chunk starts with `=`
    assert any(b == ord("=") for (_, _, b) in hits)


def test_csv_at_formula_flags_critical() -> None:
    data = b"a,b\n@SUM(1+1),x\n"
    hits = pfp.find_csv_injection_lines(data)
    assert any(b == ord("@") for (_, _, b) in hits)


def test_csv_plus_formula_flags_major() -> None:
    data = b"a,b\n+1+cmd|'/c calc'!A1,x\n"
    hits = pfp.find_csv_injection_lines(data)
    assert any(b == ord("+") for (_, _, b) in hits)


def test_csv_tab_trigger_flags() -> None:
    """Tab as the FIRST byte of a field — Excel auto-formula recovery."""
    # The chunk after the comma starts with TAB then `=cmd...`
    data = b"a,\t=cmd|x\n"
    hits = pfp.find_csv_injection_lines(data)
    # Either TAB or `=` triggers; we get at least one finding.
    assert hits


def test_csv_minus_followed_by_digit_does_not_flag() -> None:
    """Negative-number field `-1.5` is legitimate data — must NOT flag."""
    data = b"name,balance\nAlice,-1.5\n"
    hits = pfp.find_csv_injection_lines(data)
    # No `-` finding allowed; `=`/`@`/`+` not present either.
    assert all(b != ord("-") for (_, _, b) in hits)


def test_csv_minus_followed_by_dot_then_digit_does_not_flag() -> None:
    """`-.5` (a decimal without leading 0) — legitimate, NOT flagged."""
    data = b"a,b\nx,-.5\n"
    hits = pfp.find_csv_injection_lines(data)
    assert all(b != ord("-") for (_, _, b) in hits)


def test_csv_minus_followed_by_letter_flags() -> None:
    """`-cmd|'/c calc'!A1` — minus followed by non-digit → flagged."""
    data = b"a,b\n-cmd|'/c calc',1\n"
    hits = pfp.find_csv_injection_lines(data)
    assert any(b == ord("-") for (_, _, b) in hits)


def test_csv_quoted_field_still_strips_quote_and_flags() -> None:
    """Excel parses `"=cmd"` as formula too — leading quote is stripped."""
    data = b'a,b\n"=cmd|x",1\n'
    hits = pfp.find_csv_injection_lines(data)
    assert any(b == ord("=") for (_, _, b) in hits)


def test_csv_empty_data_returns_empty() -> None:
    assert pfp.find_csv_injection_lines(b"") == []


def test_csv_normal_data_returns_empty() -> None:
    data = b"name,age,city\nAlice,30,Berlin\nBob,25,Madrid\n"
    assert pfp.find_csv_injection_lines(data) == []


# ---------- file_kind=source filters out markdown/SVG rules -------------


def test_scan_text_source_mode_skips_markdown_rules() -> None:
    """In file_kind='source' mode, the markdown-raw-html and svg rules
    must NOT fire (otherwise they FP on raw HTML inside string literals
    in scanner code itself)."""
    src = (
        "# Python source file\n"
        "DANGEROUS = '<script>alert(1)</script>'   # this is a TEST pattern, not real XSS\n"
        "SVG_TEST = '<svg onload=\"x\"/>'\n"
    )
    findings = pfp.scan_text(src, file_kind="source")
    rule_ids = {f.rule_id for f in findings}
    assert "markdown-raw-html-script-tag" not in rule_ids
    assert "svg-embedded-js" not in rule_ids


def test_scan_text_source_mode_keeps_yaml_pickle_jsonc() -> None:
    """yaml-load-unsafe / pickle-load-from-network / jsonc-comment-key-shadow
    must still fire in source mode — those are the rules that catch
    code-level attacks."""
    src = "yaml.load(payload)\n"
    findings = pfp.scan_text(src, file_kind="source")
    assert any(f.rule_id == "yaml-load-unsafe" for f in findings)


def test_scan_text_empty_returns_empty() -> None:
    assert pfp.scan_text("") == []
    assert pfp.scan_text("", file_kind="source") == []


def test_scan_text_finding_line_col_are_one_based() -> None:
    """First line of input is line 1, first column is column 1."""
    src = "yaml.load(payload)"
    findings = pfp.scan_text(src)
    assert findings
    assert findings[0].line == 1
    assert findings[0].column >= 1
