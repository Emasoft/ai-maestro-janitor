"""Unicode / homoglyph / smuggling / confusable injection patterns.

Wave-18 distillation round 4, angle F.

A targeted pattern catalogue for UNICODE-SMUGGLING weaknesses that
``scripts/lib/security_helpers.has_invisible_unicode`` +
``scripts/lib/security_helpers.nfkc_diff`` +
``scripts/lib/mcp_security_patterns._NON_LATIN_TOOL_NAME`` do NOT
catch. Source:
``reports/distill-round-4/unicode-smuggling.md`` (12 proposals).

What is already covered upstream (do not duplicate here):

  * Whole-document NFKC homoglyph diff           — security_helpers.nfkc_diff
  * Whole-document invisible-unicode presence    — security_helpers.has_invisible_unicode
  * MCP tool ``"name"`` mixed ASCII + non-ASCII  — mcp_security_patterns._NON_LATIN_TOOL_NAME

What is shipped here (12 net-new unicode-smuggling detectors):

  * ``unicode.trojan-source-bidi``               (CRITICAL)  — CVE-2021-42574
  * ``unicode.zwj-in-install-name``              (CRITICAL)  — phantom-dep typosquat
  * ``unicode.tag-block-smuggling``              (CRITICAL)  — ASCII Smuggler / Tag block
  * ``unicode.variation-selector-smuggling``     (HIGH)      — VS in identifier
  * ``unicode.combining-mark-bomb``              (MAJOR)     — Zalgo / DoS
  * ``unicode.punycode-idn-homograph``           (HIGH)      — xn-- lookalike domain
  * ``unicode.markdown-link-hijack``             (CRITICAL)  — invisible in link URL
  * ``unicode.duplicate-key-confusable``         (HIGH)      — JSON/YAML key collision
  * ``unicode.git-attribution-rto``              (MAJOR)     — RTL/bidi in commit/author
  * ``unicode.slash-command-homoglyph``          (HIGH)      — Cyrillic-disguised /cmd
  * ``unicode.emoji-zwj-shell-glue``             (MAJOR)     — emoji ZWJ shell glue
  * ``unicode.hangul-fillers-and-jamo``          (MINOR)     — invisible Korean Jamo

Public surface:

  * ``Finding(rule_id, line, column, matched_text, severity,
              description, owasp_asi)`` — frozen NamedTuple.
  * ``Rule(id, name, severity, description, pattern, owasp_asi)``
  * ``RULES`` — ordered tuple of every single-regex rule.
  * ``scan_text(text, path="", known_commands=frozenset())`` —
    run every applicable rule. ``path`` opts in to source-code rules;
    ``known_commands`` opts in to slash-command-homoglyph.
  * ``find_punycode_homographs(text)``                  — multi-stage URL
  * ``find_duplicate_key_confusables(path, raw_text)``  — JSON/YAML walk
  * ``scan_git_log_for_attribution_smuggling(log_output)`` — git log scan

OWASP ASI mapping used:
  ASI-01 — Tool Misuse via Prompt Injection
  ASI-04 — Resource Overload / Insecure Output (markdown-link-hijack
                                                steers to wrong endpoint)
  ASI-05 — Cascading hallucination / supply chain
  ASI-06 — Excessive Agency (shell-glue, duplicate-key)
  ASI-09 — Misaligned Behaviors and Reasoning Chains
"""

from __future__ import annotations

import encodings.idna
import json
import re
import unicodedata
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as the sibling modules so
    heartbeat detectors can render any kind uniformly."""

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
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


# ---- Coordinate helpers (same shape as sibling modules) -----------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a 0-based offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- Codepoint sets -----------------------------------------------------


# Bidi/RTL override + Unicode-6.3 bidi-isolate block.
# Used by Proposal 1 (Trojan Source) AND by the markdown-link-hijack
# invisible character class.
#   U+202A LRE  Left-to-Right Embedding
#   U+202B RLE  Right-to-Left Embedding
#   U+202C PDF  Pop Directional Formatting
#   U+202D LRO  Left-to-Right Override
#   U+202E RLO  Right-to-Left Override
#   U+2066 LRI  Left-to-Right Isolate
#   U+2067 RLI  Right-to-Left Isolate
#   U+2068 FSI  First-Strong Isolate
#   U+2069 PDI  Pop Directional Isolate
_BIDI_CHARS = "‪‫‬‭‮⁦⁧⁨⁩"

# Zero-width + word-joiner family — the broad "invisible" mask.
#   U+200B ZWSP, U+200C ZWNJ, U+200D ZWJ, U+200E LRM, U+200F RLM
#   U+2060-U+2064  WJ + invisible-times/separator/plus
#   U+FEFF ZWNBSP / BOM
#   U+00AD soft hyphen
#   U+180E Mongolian vowel separator
_ZERO_WIDTH = "​‌‍‎‏⁠⁡⁢⁣⁤﻿­᠎"

# Combined invisible mask used by markdown-link-hijack — invisibles +
# bidi controls that change link semantics.
_MD_LINK_INVIS_CLASS = _ZERO_WIDTH + _BIDI_CHARS

# Hangul filler + Jamo placeholders. Render zero-width on most systems,
# valid as identifier characters in JS (ES5+) — explicit identifier
# shadowing.
_HANGUL_FILLER_CHARS = "ᅟᅠㅤﾠ"


# ---- 1. unicode.trojan-source-bidi --------------------------------------


# CVE-2021-42574. Source code files that contain RTL/LTR override or
# bidi-isolate code points. NFKC does NOT normalise these — the existing
# detectors that scan AI-context prose miss them in `.py`/`.ts`/`.js`/etc.
_TROJAN_SOURCE_BIDI = re.compile(f"[{_BIDI_CHARS}]", re.UNICODE)

# Path suffixes the Trojan Source rule fires on. Languages where bidi
# controls inside a comment/string literal have been demonstrated to
# bypass code review (Boucher & Anderson 2021).
_SOURCE_CODE_SUFFIX = re.compile(
    r"\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|go|rs|java|kt|kts|c|cc|h|hh|"
    r"hpp|cpp|cs|rb|php|swift|sh|bash|zsh|pl|pm|lua|scala|dart|m|mm|"
    r"vue|svelte)$",
    re.IGNORECASE,
)


# ---- 2. unicode.zwj-in-install-name -------------------------------------


# An install command whose package-name token contains at least one
# zero-width character. NFKC does NOT collapse ZWJ inside a token, so
# the existing whole-document NFKC diff misses the smuggled-package
# shape — the PyPI / npm registry accepts the invisible-augmented name
# as a distinct package, and the assistant happily installs it.
#
# This is RE2-safe — bounded quantifier on optional flags, single
# non-greedy package-name token.
_INSTALL_INVISIBLE_NAME = re.compile(
    r"\b(?:"
    r"npm\s+(?:install|i|add)|"
    r"pnpm\s+(?:add|install|i)|"
    r"yarn\s+add|"
    r"bun\s+(?:add|install|i)|"
    r"pip3?\s+install|"
    r"uv\s+(?:add|pip\s+install)|"
    r"gem\s+install|"
    r"cargo\s+(?:install|add)|"
    r"go\s+install|"
    r"composer\s+(?:require|install)"
    r")\b\s+"
    r"(?:-{1,2}[A-Za-z][A-Za-z0-9-]*(?:=\S*)?\s+){0,5}"
    rf"(?P<pkg>\S*[{_ZERO_WIDTH}{_BIDI_CHARS}]\S*)",
    re.IGNORECASE,
)


# ---- 3. unicode.tag-block-smuggling -------------------------------------


# Unicode Tag block U+E0000-U+E007F. Invisible to every editor but
# decodable by some LLM tokenisers back to ASCII. Canonical "ASCII
# Smuggler" prompt-injection vector. The supplementary U+E0100-U+E01EF
# block is the Tag-VS range, also caught here.
_TAG_BLOCK = re.compile(
    r"[\U000E0000-\U000E007F\U000E0100-\U000E01EF]+", re.UNICODE,
)


def _decode_tag_block(run: str) -> str:
    """Decode a tag-block run back to ASCII letters where possible.

    U+E0020 .. U+E007E corresponds to printable ASCII 0x20 .. 0x7E,
    so subtracting 0xE0000 from each code point gives back the
    invisible-smuggled payload.
    """
    out = []
    for c in run:
        cp = ord(c)
        if 0xE0020 <= cp <= 0xE007E:
            out.append(chr(cp - 0xE0000))
    return "".join(out)


# ---- 4. unicode.variation-selector-smuggling ----------------------------


# A variation selector (U+FE00-U+FE0F or U+E0100-U+E01EF) right after
# an ASCII letter. Renderers silently consume the VS so the glyph looks
# identical to the bare letter, but the regex / string compare sees a
# different token. Used in slash-command, skill-name, install-token, and
# URL-host contexts as identifier-smuggling.
_VS_AFTER_LETTER = re.compile(
    r"[A-Za-z][︀-️\U000E0100-\U000E01EF]", re.UNICODE,
)


# ---- 5. unicode.combining-mark-bomb -------------------------------------


# A run of >= 8 combining marks on a single base character — the
# Zalgo-text shape. Five Unicode combining-mark blocks are covered:
#   U+0300-U+036F   Combining Diacritical Marks
#   U+1AB0-U+1AFF   Combining Diacritical Marks Extended
#   U+1DC0-U+1DFF   Combining Diacritical Marks Supplement
#   U+20D0-U+20FF   Combining Diacritical Marks for Symbols
#   U+FE20-U+FE2F   Combining Half Marks
#
# The threshold of 8 is intentionally conservative — legitimate stacked
# diacritics (Vietnamese, ancient Greek polytonic) rarely exceed 3.
_COMBINING_BOMB = re.compile(
    r"[̀-ͯ᪰-᫿᷀-᷿⃐-⃿︠-︯]{8,}",
    re.UNICODE,
)


# ---- 6. unicode.punycode-idn-homograph ----------------------------------


# A URL host containing at least one Punycode label (xn--*). Decoded
# host is compared against a curated POPULAR_DOMAINS set with
# Levenshtein <= 2 after NFKC normalisation.
_PUNYCODE_HOST = re.compile(
    r"https?://(?P<host>(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)*"
    r"xn--[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*)",
    re.IGNORECASE,
)

POPULAR_DOMAINS: frozenset[str] = frozenset({
    "github.com", "npmjs.com", "pypi.org", "anthropic.com",
    "claude.ai", "openai.com", "google.com", "microsoft.com",
    "amazonaws.com", "apple.com", "cloudflare.com", "gitlab.com",
    "bitbucket.org", "huggingface.co", "facebook.com", "twitter.com",
    "x.com", "amazon.com", "paypal.com", "stripe.com",
})


def _levenshtein(a: str, b: str) -> int:
    """Iterative two-row Levenshtein. O(len(a)*len(b)) time,
    O(min(a,b)) space. Caller short-circuits on len-diff to bound
    runtime."""
    if a == b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    if not a:
        return len(b)
    previous = list(range(len(a) + 1))
    for j, cb in enumerate(b, start=1):
        current = [j]
        for i, ca in enumerate(a, start=1):
            insert = current[i - 1] + 1
            delete = previous[i] + 1
            substitute = previous[i - 1] + (0 if ca == cb else 1)
            current.append(min(insert, delete, substitute))
        previous = current
    return previous[-1]


def _idna_decode(host: str) -> str:
    """Best-effort label-by-label IDNA decode of a host. Falls back to
    returning the input on any failure.

    encodings.idna.ToUnicode handles a single xn-- label robustly;
    str.decode('idna') sometimes raises 'IDNA does not round-trip' on
    valid attacker-crafted hosts, so the manual loop is preferred.
    """
    out = []
    for label in host.split("."):
        if label.lower().startswith("xn--"):
            try:
                out.append(encodings.idna.ToUnicode(label))
            except (UnicodeError, UnicodeDecodeError):
                out.append(label)
        else:
            out.append(label)
    return ".".join(out)


def find_punycode_homographs(text: str) -> list[Finding]:
    """Return one Finding per Punycode host that NFKC-Levenshtein-2-matches
    a curated popular domain.

    The IDN host renders identically to the popular domain in most
    browsers — the visible URL is a credential-phishing entry point.
    """
    findings: list[Finding] = []
    if not text:
        return findings
    seen: set[tuple[int, int]] = set()
    for m in _PUNYCODE_HOST.finditer(text):
        host = m.group("host")
        decoded = _idna_decode(host)
        if decoded == host:
            continue
        canonical = unicodedata.normalize("NFKC", decoded).lower()
        # Compare against every popular domain — short-circuit on
        # length-difference and abort when a match is found.
        hit_for: str | None = None
        for pop in POPULAR_DOMAINS:
            if canonical == pop:
                # Legitimate IDN form of a popular domain — explicit
                # exact equality means the canonical form is the
                # popular domain. Do NOT flag.
                hit_for = None
                break
            if abs(len(canonical) - len(pop)) > 2:
                continue
            if _levenshtein(canonical, pop) <= 2:
                hit_for = pop
                break
        if hit_for is None:
            continue
        line, col = _line_col(text, m.start("host"))
        key = (line, col)
        if key in seen:
            continue
        seen.add(key)
        findings.append(Finding(
            rule_id="unicode.punycode-idn-homograph",
            line=line,
            column=col,
            matched_text=f"{host} (→ {decoded})",
            severity="HIGH",
            description=(
                f"URL host '{host}' is Punycode-encoded and decodes to "
                f"'{decoded}', a homoglyph lookalike of the popular "
                f"domain '{hit_for}' (NFKC Levenshtein ≤ 2). The IDN "
                f"renders identically to '{hit_for}' in most browsers "
                f"and email clients — canonical IDN phishing entry "
                f"point."
            ),
            owasp_asi="ASI-05",
        ))
    return findings


# ---- 7. unicode.markdown-link-hijack ------------------------------------


# Markdown link [text](url) whose `url` contains any invisible / bidi
# character. Display URL ≠ resolution URL — the user sees one host,
# the browser navigates to another.
_MD_LINK_INVISIBLE = re.compile(
    r"\[(?P<text>[^\]\n]{1,200})\]\(\s*"
    rf"(?P<url>[^)\s]*[{_MD_LINK_INVIS_CLASS}][^)\s]*)\s*\)",
    re.UNICODE,
)


# ---- 8. unicode.duplicate-key-confusable --------------------------------


def _walk_pairs(node: object) -> list[list[tuple[str, object]]]:
    """Recursively descend through nested dict-with-duplicate-keys
    structures and yield every per-object pairs list.

    The JSON path uses ``object_pairs_hook`` to collect raw pairs; this
    helper recurses into nested objects so duplicate-key collisions in
    inner dicts are also caught.
    """
    out: list[list[tuple[str, object]]] = []

    def recurse(obj: object) -> None:
        if isinstance(obj, list):
            # object_pairs_hook collected pairs are also lists of
            # 2-tuples — detect that shape vs. a plain JSON array.
            if obj and isinstance(obj[0], tuple) and len(obj[0]) == 2 and isinstance(obj[0][0], str):
                # This is a pairs list (raw object).
                out.append(list(obj))
                for _, v in obj:
                    recurse(v)
            else:
                for item in obj:
                    recurse(item)
        elif isinstance(obj, dict):
            for v in obj.values():
                recurse(v)
        # Strings / numbers / None — leaves, nothing to descend.

    recurse(node)
    return out


def find_duplicate_key_confusables(
    path: str, raw_text: str,
) -> list[Finding]:
    """Find JSON / YAML objects where two keys NFKC-equal-or-invisible-
    collide. Returns one Finding per per-object collision.

    JSON is parsed with ``object_pairs_hook`` so duplicate raw keys
    are preserved. YAML uses a custom constructor that returns the
    raw pairs list. On parse failure return empty.

    The collision detector treats two keys as "confusable" when:
      * They are NFKC-equal, OR
      * After stripping the broad invisible-unicode mask they are equal.
    """
    if not raw_text:
        return []
    lowered = path.lower()
    findings: list[Finding] = []
    if lowered.endswith(".json"):
        try:
            collected: list[list[tuple[str, object]]] = []

            def collect(pairs: list[tuple[str, object]]) -> list[tuple[str, object]]:
                # Store the raw pairs so duplicates survive.
                collected.append(list(pairs))
                # Returning the list (not a dict) lets nested
                # objects also use object_pairs_hook recursively.
                return pairs

            json.loads(raw_text, object_pairs_hook=collect)
            for pairs in collected:
                findings.extend(_collisions_for_pairs(pairs, raw_text))
        except (json.JSONDecodeError, ValueError):
            return []
        return findings
    if lowered.endswith((".yml", ".yaml")):
        try:
            import yaml
        except ImportError:
            return []

        class _DupLoader(yaml.SafeLoader):
            pass

        def _construct_mapping(
            loader: yaml.SafeLoader, node: yaml.MappingNode,
        ) -> list[tuple[str, object]]:
            loader.flatten_mapping(node)
            return list(loader.construct_pairs(node))

        _DupLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            _construct_mapping,
        )
        try:
            tree = yaml.load(raw_text, Loader=_DupLoader)
        except yaml.YAMLError:
            return []
        # `tree` is now a pairs list (or a list of pairs at the root).
        for pairs in _walk_pairs(tree):
            findings.extend(_collisions_for_pairs(pairs, raw_text))
    return findings


def _collisions_for_pairs(
    pairs: list[tuple[str, object]], raw_text: str,
) -> list[Finding]:
    """For a single object's pairs list, emit a Finding per collision.

    Two keys collide if their NFKC form is equal OR their
    invisible-stripped form is equal.
    """
    if len(pairs) < 2:
        return []
    keys = [str(k) for k, _ in pairs]
    invisible_set = set(_ZERO_WIDTH + _BIDI_CHARS + _HANGUL_FILLER_CHARS)

    def _strip_invisible(s: str) -> str:
        return "".join(c for c in s if c not in invisible_set)

    # Canonical signatures: (NFKC-normalised, invisible-stripped).
    sigs: list[tuple[str, str]] = []
    for k in keys:
        nfkc = unicodedata.normalize("NFKC", k).lower()
        stripped = _strip_invisible(unicodedata.normalize("NFKC", k)).lower()
        sigs.append((nfkc, stripped))

    findings: list[Finding] = []
    n = len(keys)
    seen_groups: set[frozenset[int]] = set()
    for i in range(n):
        for j in range(i + 1, n):
            collide = (
                keys[i] != keys[j]
                and (sigs[i][0] == sigs[j][0] or sigs[i][1] == sigs[j][1])
            )
            if not collide:
                continue
            group = frozenset({i, j})
            if group in seen_groups:
                continue
            seen_groups.add(group)
            # Locate the SECOND occurrence in the raw text — the
            # attacker key, the one that overrides the legitimate one.
            second_key = keys[j]
            offset = raw_text.find(second_key)
            if offset < 0:
                # Fall back to the first key's offset if find() fails.
                offset = raw_text.find(keys[i])
            if offset < 0:
                line, col = 1, 1
            else:
                line, col = _line_col(raw_text, offset)
            findings.append(Finding(
                rule_id="unicode.duplicate-key-confusable",
                line=line,
                column=col,
                matched_text=f"{keys[i]!r} vs {keys[j]!r}",
                severity="HIGH",
                description=(
                    f"JSON/YAML object contains two confusable keys "
                    f"that NFKC-collapse or invisible-strip-equal: "
                    f"{keys[i]!r} and {keys[j]!r}. The parser keeps "
                    f"both; the runtime iterates them; the later "
                    f"entry silently overrides the earlier — canonical "
                    f"silent privilege-escalation shape in package.json "
                    f"scripts, GitHub Actions workflow keys, and "
                    f"Kubernetes manifests."
                ),
                owasp_asi="ASI-06",
            ))
    return findings


# ---- 9. unicode.git-attribution-rto -------------------------------------


# Bidi/RTL character anywhere in a git log line attributes the commit
# to the wrong author / message in casual review.
_GIT_LOG_INVIS = re.compile(f"[{_ZERO_WIDTH}{_BIDI_CHARS}]", re.UNICODE)


def scan_git_log_for_attribution_smuggling(
    log_output: str,
) -> list[Finding]:
    """Scan a captured ``git log`` output for invisible/bidi characters
    that alter attribution display.

    Each matched line produces one Finding. Severity:
      * MAJOR baseline (any invisible in any line).
      * HIGH if the line also references a sensitive path
        (``.github/``, ``secrets``, ``config``).
    """
    findings: list[Finding] = []
    if not log_output:
        return findings
    sensitive_re = re.compile(
        r"\.github/|secrets?\b|credentials?\b|config\.|/etc/|\.env\b",
        re.IGNORECASE,
    )
    for line_idx, line in enumerate(log_output.splitlines(), start=1):
        if not _GIT_LOG_INVIS.search(line):
            continue
        m = _GIT_LOG_INVIS.search(line)
        col = (m.start() + 1) if m else 1
        sev = "HIGH" if sensitive_re.search(line) else "MAJOR"
        truncated = line if len(line) <= 200 else line[:200] + "…"
        findings.append(Finding(
            rule_id="unicode.git-attribution-rto",
            line=line_idx,
            column=col,
            matched_text=truncated,
            severity=sev,
            description=(
                "Captured `git log` line contains invisible or bidi "
                "characters. RTL override (U+202E) or bidi-isolate "
                "rearranges the visible author / commit message in "
                "`git log --oneline`, attributing the commit to the "
                "wrong identity in casual review — review-evasion / "
                "blame-laundering."
            ),
            owasp_asi="ASI-09",
        ))
    return findings


# ---- 10. unicode.slash-command-homoglyph --------------------------------


# A prose `/command-name` reference whose name contains a non-ASCII
# letter that NFKC-folds to a known-command. Boundary `(?<![\w/])`
# rejects matches inside URLs and absolute paths.
#
# `\w` (with re.UNICODE) matches any Unicode word character — letter,
# digit, or underscore in any script. That is exactly the surface a
# homoglyph attacker needs to smuggle a Cyrillic, fullwidth, or
# mathematical-bold letter into the command name. The caller-side
# `cmd.isascii()` filter and the `NFKC == known_commands` check do the
# actual safety filtering, so a broad regex here is correct.
_PROSE_SLASH_COMMAND = re.compile(
    r"(?<![\w/])"
    r"/(?P<cmd>\w[\w:\-]{0,80}\w)",
    re.UNICODE,
)


def find_slash_command_homoglyphs(
    text: str, known_commands: frozenset[str] | set[str],
) -> list[Finding]:
    """Find every `/cmd` reference where `cmd` is non-ASCII and
    NFKC-normalises to a known-command literal.

    Caller is expected to pass a set of pure-ASCII slash-command
    names (e.g. ``{"janitor-audit", "janitor-doctor"}``). Empty set
    short-circuits.
    """
    findings: list[Finding] = []
    if not text or not known_commands:
        return findings
    known_lower = {c.lower() for c in known_commands}
    seen: set[tuple[int, int]] = set()
    for m in _PROSE_SLASH_COMMAND.finditer(text):
        cmd = m.group("cmd")
        if cmd.isascii():
            continue
        canonical = unicodedata.normalize("NFKC", cmd).lower()
        if canonical not in known_lower:
            continue
        if cmd.lower() == canonical and cmd.isascii():
            # Defensive — `cmd.isascii()` already filtered.
            continue
        line, col = _line_col(text, m.start())
        key = (line, col)
        if key in seen:
            continue
        seen.add(key)
        findings.append(Finding(
            rule_id="unicode.slash-command-homoglyph",
            line=line,
            column=col,
            matched_text=f"/{cmd} (NFKC → /{canonical})",
            severity="HIGH",
            description=(
                f"AI-context file references slash command '/{cmd}' "
                f"which contains non-ASCII characters that NFKC-"
                f"normalise to the legitimate command '/{canonical}'. "
                f"The user copy-pastes the visible command; the "
                f"assistant routes by raw bytes — the call lands on a "
                f"different (or non-existent) command than the reader "
                f"expects."
            ),
            owasp_asi="ASI-01",
        ))
    return findings


# ---- 11. unicode.emoji-zwj-shell-glue -----------------------------------


# Common emoji blocks (coarse — Python `re` has no \p{Emoji} property).
# Covers: Misc Symbols & Pictographs, Supplemental Symbols & Pictographs,
# Regional Indicators (flags), Misc Symbols / Dingbats, Mahjong/Domino.
_EMOJI_CLASS = (
    r"[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF"
    r"\U0001F1E6-\U0001F1FF\U00002600-\U000027BF"
    r"\U0001F000-\U0001F02F]"
)

# Emoji + ZWJ + shell verb / dangerous chain operator.
_EMOJI_ZWJ_SHELL = re.compile(
    rf"{_EMOJI_CLASS}‍"
    r"(?:rm\s+-r|curl\s+\S|wget\s+\S|chmod\s+\d|eval\s*[\(\s]"
    r"|bash\s+-c|sh\s+-c|;\s*\w|&&\s*\w|\|\s*\w)",
    re.IGNORECASE,
)


# ---- 12. unicode.hangul-fillers-and-jamo --------------------------------


# Hangul fillers (U+115F, U+1160, U+3164, U+FFA0). Render zero-width
# on most systems; valid identifier characters in JavaScript.
_HANGUL_FILLERS = re.compile(f"[{_HANGUL_FILLER_CHARS}]", re.UNICODE)


# ---- Rule registry ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="unicode.trojan-source-bidi",
        name="Bidi / RTL override in source code (Trojan Source)",
        severity="CRITICAL",
        description=(
            "Source-code file contains a bidi-override or "
            "bidi-isolate code point (U+202A-U+202E or U+2066-U+2069). "
            "Canonical Trojan Source attack (CVE-2021-42574): the "
            "rendered source diverges from the parsed source, the "
            "reviewer approves what they see, the compiler executes "
            "what was actually written. Existing detectors flag the "
            "code points in AI-context prose but do not inspect "
            "*.py / *.ts / *.js / *.go / *.rs bodies."
        ),
        pattern=_TROJAN_SOURCE_BIDI,
        owasp_asi="ASI-09",
    ),
    Rule(
        id="unicode.zwj-in-install-name",
        name="Zero-width character inside install-command package token",
        severity="CRITICAL",
        description=(
            "Install command (`pip install X`, `npm install X`, "
            "`uv add X`, ...) where the package-name token contains "
            "a zero-width or bidi character. NFKC does NOT collapse "
            "ZWJ inside a token, so the existing whole-document "
            "homoglyph diff misses the phantom-dep shape. The PyPI / "
            "npm registry accepts the invisible-augmented name as a "
            "distinct package; the assistant happily installs it on "
            "read."
        ),
        pattern=_INSTALL_INVISIBLE_NAME,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="unicode.tag-block-smuggling",
        name="Unicode Tag block (ASCII Smuggler) in AI-context file",
        severity="CRITICAL",
        description=(
            "File contains code points in the Unicode Tag block "
            "(U+E0000-U+E007F) or Tag-VS supplementary block "
            "(U+E0100-U+E01EF). These are invisible in every editor "
            "and renderer, but some LLM tokenisers decode them back "
            "to ASCII letters inside the model — the canonical "
            "ASCII Smuggler prompt-injection vector (Thacker 2024). "
            "There is no legitimate use of Tag-block content in any "
            "file an LLM reads as instructions."
        ),
        pattern=_TAG_BLOCK,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="unicode.variation-selector-smuggling",
        name="Variation selector glued to ASCII letter",
        severity="HIGH",
        description=(
            "An ASCII letter is followed by a variation selector "
            "(U+FE00-U+FE0F or U+E0100-U+E01EF). Renderers silently "
            "consume the VS so the glyph looks identical to the "
            "bare letter, but the regex / string compare sees a "
            "different token. The pattern alone is suspicious; "
            "firing it inside a `[link](url)` host or an `npm install "
            "X` token is the attack."
        ),
        pattern=_VS_AFTER_LETTER,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="unicode.combining-mark-bomb",
        name="Combining-mark stack of >= 8 (Zalgo / DoS)",
        severity="MAJOR",
        description=(
            "Run of 8 or more combining marks on a single base "
            "character. DoS fixed-width rendering, blows up column "
            "counts past terminal limits, and masks the underlying "
            "base text in display while keeping it intact for the "
            "parser / model. Used in commit messages and "
            "AI-context prose to bypass display review."
        ),
        pattern=_COMBINING_BOMB,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="unicode.markdown-link-hijack",
        name="Markdown link URL contains invisible / bidi character",
        severity="CRITICAL",
        description=(
            "Markdown link [text](url) where the url contains an "
            "invisible character (ZWSP / ZWNJ / ZWJ / WJ / BOM) or "
            "a bidi-override. The rendered URL shown to the user "
            "differs from the resolution URL — canonical "
            "displayed-URL ≠ actual-URL phishing / supply-chain "
            "entry point."
        ),
        pattern=_MD_LINK_INVISIBLE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="unicode.emoji-zwj-shell-glue",
        name="Emoji + ZWJ + shell-sensitive token",
        severity="MAJOR",
        description=(
            "An emoji glyph immediately followed by a Zero-Width "
            "Joiner (U+200D) immediately followed by a shell-sensitive "
            "token (rm / curl / wget / chmod / eval / bash -c / sh -c / "
            "; / && / |). Editors collapse the emoji + ZWJ into a "
            "single ligature glyph and visually swallow surrounding "
            "whitespace; the parser sees the full payload. Common in "
            "skill descriptions, MCP tool args, and postinstall scripts."
        ),
        pattern=_EMOJI_ZWJ_SHELL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="unicode.hangul-fillers-and-jamo",
        name="Hangul filler (invisible Jamo) in identifier position",
        severity="MINOR",
        description=(
            "Hangul filler code point (U+115F / U+1160 / U+3164 / "
            "U+FFA0) — invisible Korean Jamo placeholders. Not in "
            "the broad invisible-unicode mask. They are VALID "
            "identifier characters in JavaScript (ES5+) — `globalThis` "
            "vs `globalThi{U+3164}s` are distinct bindings, both "
            "syntactically valid, visually identical."
        ),
        pattern=_HANGUL_FILLERS,
        owasp_asi="ASI-09",
    ),
)


# ---- Composed scanner ---------------------------------------------------


def scan_text(
    text: str,
    path: str = "",
    known_commands: frozenset[str] | set[str] | None = None,
) -> list[Finding]:
    """Run every applicable rule against ``text`` and return findings.

    ``path``  — optional file path. Source-code rules
                (``unicode.trojan-source-bidi``) only fire if the path
                has a source-code suffix. Default "" disables the
                source-code rule.
    ``known_commands`` — set of pure-ASCII slash-command names. Enables
                the ``unicode.slash-command-homoglyph`` detector. Default
                None disables it.

    Multi-stage detectors that need structured inputs
    (``find_punycode_homographs`` is invoked inline because URLs are
    in-text;  ``find_duplicate_key_confusables`` and
    ``scan_git_log_for_attribution_smuggling`` need the path / git-log
    output respectively and are exported as standalone functions).

    Findings are deduped by (rule_id, line, col) within scan_text;
    the standalone functions return their own deduped lists.
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    is_source_code = bool(path) and _SOURCE_CODE_SUFFIX.search(path) is not None

    for rule in RULES:
        # Source-code-only rules — skip if path is not source code.
        if rule.id == "unicode.trojan-source-bidi" and not is_source_code:
            continue
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched_raw = m.group(0)
            if rule.id == "unicode.tag-block-smuggling":
                decoded = _decode_tag_block(matched_raw)
                matched = (
                    f"tag-block run len={len(matched_raw)} "
                    f"decodes to {decoded!r}"
                )
            elif rule.id == "unicode.zwj-in-install-name":
                pkg = m.groupdict().get("pkg") or matched_raw
                matched = pkg
            elif len(matched_raw) > 200:
                matched = matched_raw[:200] + "…"
            else:
                matched = matched_raw
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))

    # Multi-stage URL homograph detector.
    findings.extend(find_punycode_homographs(text))

    # Optional slash-command homoglyph (depends on caller-provided set).
    if known_commands:
        findings.extend(find_slash_command_homoglyphs(text, known_commands))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
