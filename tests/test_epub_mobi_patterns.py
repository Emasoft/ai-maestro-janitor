"""Tests for scripts/lib/epub_mobi_patterns.py.

Pattern-coverage tests for the Wave-33 distill-round-19 catalogue
(10 EPUB/MOBI/AZW/FictionBook2 parsing flaw patterns). Each rule has
exactly two tests: one positive (vulnerable snippet fires the rule) and
one negative (safe or non-matching snippet is silent).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))  # noqa: E402

import epub_mobi_patterns as emp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(emp.RULES, tuple)
    rule_ids = {r.id for r in emp.RULES}
    expected = {
        "ebk-epub-zip-path-traversal-content-opf",
        "ebk-epub-xhtml-script-not-sandboxed",
        "ebk-epub-svg-foreignobject-js-embedded",
        "ebk-mobi-palmdoc-no-decompress-limit",
        "ebk-mobi-pdb-record-count-oob",
        "ebk-azw-drm-integer-overflow-kdf",
        "ebk-fb2-xxe-no-defusedxml",
        "ebk-calibre-xslt-command-injection",
        "ebk-pdfminer-cpu-exhaustion-no-timeout",
        "ebk-ade-url-handler-rce",
    }
    assert expected == rule_ids
    assert len(emp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in emp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = emp.Finding(
        rule_id="ebk-test",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-05",
    )
    assert f.rule_id == "ebk-test"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-05"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert emp.scan_text("") == []


# ---------- E1 : ebk-epub-zip-path-traversal-content-opf ----------------


def test_e1_positive_zipfile_epub_read_no_abspath() -> None:
    """ZipFile opened on .epub with .read() and no os.path guard fires E1."""
    src = (
        'with zipfile.ZipFile("book.epub") as zf:\n'
        '    data = zf.read(f"OEBPS/{href}")\n'
    )
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-epub-zip-path-traversal-content-opf" in ids


def test_e1_negative_zipfile_epub_read_with_abspath() -> None:
    """ZipFile on .epub with os.path guard does NOT fire E1."""
    src = (
        'with zipfile.ZipFile("book.epub") as zf:\n'
        '    safe = zf.read(os.path.join("OEBPS", href))\n'
    )
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-epub-zip-path-traversal-content-opf" not in ids


# ---------- E2 : ebk-epub-xhtml-script-not-sandboxed --------------------


def test_e2_positive_webview_loadurl_epub_xhtml() -> None:
    """WebView.loadUrl with .epub path fires E2."""
    src = 'wv.loadUrl("file:///sdcard/books/untrusted.epub!/OEBPS/chapter1.xhtml");\n'
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-epub-xhtml-script-not-sandboxed" in ids


def test_e2_negative_webview_plain_https_url() -> None:
    """WebView.loadUrl with a plain https URL does NOT fire E2."""
    src = 'wv.loadUrl("https://example.com/page.html");\n'
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-epub-xhtml-script-not-sandboxed" not in ids


# ---------- E3 : ebk-epub-svg-foreignobject-js-embedded -----------------


def test_e3_positive_svg_foreignobject_script() -> None:
    """SVG <foreignObject> containing <script> fires E3."""
    src = (
        '<svg xmlns="http://www.w3.org/2000/svg">\n'
        '  <foreignObject width="100%" height="100%">\n'
        "    <html><script>alert(1)</script></html>\n"
        "  </foreignObject>\n"
        "</svg>\n"
    )
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-epub-svg-foreignobject-js-embedded" in ids


def test_e3_negative_svg_foreignobject_no_script() -> None:
    """SVG <foreignObject> with only inline text does NOT fire E3."""
    src = (
        '<svg xmlns="http://www.w3.org/2000/svg">\n'
        '  <foreignObject width="100%" height="100%">\n'
        "    <html><p>safe text</p></html>\n"
        "  </foreignObject>\n"
        "</svg>\n"
    )
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-epub-svg-foreignobject-js-embedded" not in ids


# ---------- E4 : ebk-mobi-palmdoc-no-decompress-limit -------------------


def test_e4_positive_palmdoc_decompress_call() -> None:
    """palmdoc_decompress() without a size guard fires E4."""
    src = "output = palmdoc_decompress(record_data)\n"
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-mobi-palmdoc-no-decompress-limit" in ids


def test_e4_negative_unrelated_decompress_call() -> None:
    """zlib.decompress() does NOT fire E4 (different function name)."""
    src = "output = zlib.decompress(data)\n"
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-mobi-palmdoc-no-decompress-limit" not in ids


# ---------- E5 : ebk-mobi-pdb-record-count-oob --------------------------


def test_e5_positive_struct_unpack_big_endian_H_range() -> None:
    """struct.unpack with big-endian H followed by range() iteration fires E5."""
    src = (
        'num_records, = struct.unpack(">H", data[76:78])\n'
        "offsets = [data[i] for i in range(num_records)]\n"
    )
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-mobi-pdb-record-count-oob" in ids


def test_e5_negative_struct_unpack_no_range() -> None:
    """struct.unpack without a subsequent range() loop does NOT fire E5."""
    src = 'num_records, = struct.unpack(">H", data[76:78])\n'
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-mobi-pdb-record-count-oob" not in ids


# ---------- E6 : ebk-azw-drm-integer-overflow-kdf -----------------------


def test_e6_positive_xor_loop_pid_len() -> None:
    """for i in range(pid_len): result[i] ^= on same line fires E6."""
    src = "for i in range(pid_len): result[i] ^= pid[i % len(pid)]\n"
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-azw-drm-integer-overflow-kdf" in ids


def test_e6_negative_xor_loop_safe_name() -> None:
    """for i in range(block_count): buf[i] ^= does NOT fire E6."""
    src = (
        "for i in range(block_count):\n"
        "    buf[i] ^= mask[i]\n"
    )
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-azw-drm-integer-overflow-kdf" not in ids


# ---------- E7 : ebk-fb2-xxe-no-defusedxml ------------------------------


def test_e7_positive_elementtree_parse_fb2() -> None:
    """ET.parse('user.fb2') fires E7."""
    src = 'tree = ElementTree.parse("user-uploaded.fb2")\n'
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-fb2-xxe-no-defusedxml" in ids


def test_e7_negative_elementtree_parse_xml_no_fb2() -> None:
    """ET.parse('config.xml') does NOT fire E7 (no fb2 context)."""
    src = 'tree = ElementTree.parse("config.xml")\n'
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-fb2-xxe-no-defusedxml" not in ids


# ---------- E8 : ebk-calibre-xslt-command-injection ---------------------


def test_e8_positive_xpath_fstring() -> None:
    """etree.XPath(f\"...{author}...\") fires E8."""
    src = "results = tree.xpath(etree.XPath(f\"//book[author='{author}']\"))\n"
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-calibre-xslt-command-injection" in ids


def test_e8_negative_xpath_static_string() -> None:
    """etree.XPath with a plain string literal does NOT fire E8."""
    src = 'results = tree.xpath(etree.XPath("//book[@id=\'1\']"))\n'
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-calibre-xslt-command-injection" not in ids


# ---------- E9 : ebk-pdfminer-cpu-exhaustion-no-timeout -----------------


def test_e9_positive_fitz_open_user_upload() -> None:
    """fitz.open(user_uploaded_path) fires E9."""
    src = "doc = fitz.open(user_uploaded_path)\n"
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-pdfminer-cpu-exhaustion-no-timeout" in ids


def test_e9_negative_fitz_open_static_path() -> None:
    """fitz.open('sample.pdf') does NOT fire E9 (no user-controlled signal)."""
    src = 'doc = fitz.open("sample.pdf")\n'
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-pdfminer-cpu-exhaustion-no-timeout" not in ids


# ---------- E10 : ebk-ade-url-handler-rce --------------------------------


def test_e10_positive_adept_url_path_traversal() -> None:
    """adept:// URL with ../ sequence fires E10."""
    src = '<a href="adept://../../../../../../tmp/evil.sh">Click</a>\n'
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-ade-url-handler-rce" in ids


def test_e10_negative_adept_url_no_traversal() -> None:
    """adept:// URL without path traversal does NOT fire E10."""
    src = '<a href="adept://activate/device">Activate</a>\n'
    ids = {f.rule_id for f in emp.scan_text(src)}
    assert "ebk-ade-url-handler-rce" not in ids
