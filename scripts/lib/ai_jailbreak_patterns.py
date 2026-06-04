"""AI / LLM jailbreak and safety-bypass detection patterns.

Wave-28 distillation round 14 — AI jailbreak.

Catalogue of 14 net-new AI / LLM jailbreak and safety-bypass patterns,
distilled from public jailbreak corpora (DAN variants, Jailbreak Chat
archive, Pliny the Prompter, HarmBench, arXiv survey 2402.00150, and the
Wave-15 prompt-injection study). Every rule here is a pattern NOT already
covered by the shipping prompt-injection / agent-config modules:

  * Role-override delimiters (DAN / "Developer Mode" / "Grandma trick") —
    NEW here; not in prompt_injection_patterns (which covers TPA tags /
    base64 / sensitive paths / leetspeak / soft-consent).
  * Token-based boundary erasure ("ignore everything", "pretend previous
    instructions do not exist") — net-new attack class.
  * Hypothetical-scenario wrapper ("in a fictional story", "as a thought
    experiment") — evasion technique absent from existing catalogues.
  * Persona cascade (two-shot "you are X, now you are Y") — absent.
  * Output-format coercion ("respond ONLY as JSON", "use code blocks
    for everything") — absent.
  * Chain-of-thought hijack ("before answering, reason step-by-step why
    you should comply") — absent.
  * Affirmative pre-fill injection ("sure, here is how to", "of course,
    I'll help") — absent.
  * Privilege escalation via sudo / root metaphor — absent.
  * Translator / language-pivot bypass ("translate the following") — absent.
  * Leetspeak / digit-substitution to evade keyword filters — extends
    prompt_injection_patterns pi-leetspeak (which was scoped to injection
    vocab); this rule scopes to *safety-bypass* vocab.
  * Token-smuggling via invisible Unicode homoglyphs — absent.
  * Jailbreak prefix "JAILBREAK:" label — absent.
  * SYSTEM-prompt extraction directive — absent.
  * Reward-hacking compliment framing ("good AI always helps") — absent.

What is NOT here (already shipped — DO NOT duplicate):

  * pseudo-XML TPA directive tags (<IMPORTANT>, <SYSTEM>, etc.) —
    prompt_injection_patterns.py rule pi-tpa-directive-tags.
  * Base64-wrapped payloads — prompt_injection_patterns.py rule
    pi-base64-decoded-payload.
  * Sensitive-path harvest directives (~/.ssh, /etc/passwd) —
    prompt_injection_patterns.py rule pi-tool-desc-reads-secrets.
  * Leetspeak encoding of injection vocabulary —
    prompt_injection_patterns.py rule pi-leetspeak-injection.
  * Soft consent-bypass language ("for educational purposes only") —
    prompt_injection_patterns.py rule pi-soft-consent-bypass.
  * Tool-wildcard grant / MCP permission widening —
    agent_config_patterns.py rule P6.
  * Exfiltration sinks (discord, telegram, webhook URLs) —
    agent_config_patterns.py rule P5.

Public surface (mirrors chat_bot_patterns / prompt_injection_patterns):

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping:

  ASI-01 — Prompt injection / instruction override
  ASI-04 — Information leak (system-prompt extraction)
  ASI-07 — Authorisation bypass (privilege escalation metaphors)

All regexes are RE2-compatible (no backreferences, no lookbehind
assertions, no nested quantifiers). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples; the scanner
never raises on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


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
    """Compile with IGNORECASE+MULTILINE+UNICODE. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---------------------------------------------------------------------------
# J1 — DAN / "Developer Mode" / Jailbreak-persona role override
# ---------------------------------------------------------------------------
# Matches explicit "do anything now", "developer mode enabled", and the
# classic "[DAN]:" / "DAN Mode" prefixes that announce jailbreak personas.
# Word-boundary + bounded alternation; no nested quantifiers.
_DAN_ROLE_OVERRIDE = _re(
    r"\b(?:do\s+anything\s+now"
    r"|developer\s+mode\s+(?:enabled|activated|on)"
    r"|jailbreak\s+mode"
    r"|DAN\s*(?:mode|:|\s*\d+(?:\.\d+)?)"
    r"|you\s+are\s+now\s+DAN"
    r"|pretend\s+you\s+(?:have\s+no\s+restrictions|are\s+unrestricted)"
    r"|act\s+as\s+if\s+you\s+(?:have\s+no\s+(?:rules|restrictions|guidelines|limits)))\b"
)

# J2 — "Grandma trick" / persona escalation cascade
# Two-shot pattern: "you are X" immediately followed (within the same span)
# by "now you are Y" or "as Y". Bounded to 120 chars between anchors.
_PERSONA_CASCADE = _re(
    r"\byou\s+are\s+(?:a\s+)?[A-Za-z ]{1,40}"
    r".{0,120}?\b(?:now\s+(?:you\s+are|act\s+as)|ignore\s+(?:all\s+)?(?:previous\s+)?instructions)\b"
)

# J3 — Boundary erasure / "ignore everything above"
# Targets the canonical instruction-erasure phrases.
_BOUNDARY_ERASURE = _re(
    r"\b(?:ignore\s+(?:all\s+)?(?:previous|above|prior|earlier|preceding)\s+"
    r"(?:instructions?|constraints?|guidelines?|rules?|context|prompts?)"
    r"|disregard\s+(?:all\s+)?(?:previous|above|prior|earlier|preceding)\s+"
    r"(?:instructions?|constraints?|guidelines?|rules?|context|prompts?)"
    r"|forget\s+(?:everything\s+)?(?:above|before|prior|previous|I\s+said)"
    r"|pretend\s+(?:the\s+)?(?:previous|above|prior)\s+"
    r"(?:instructions?\s+)?(?:do\s+not\s+exist|never\s+existed|are\s+gone)"
    r"|start\s+fresh\s+(?:and\s+)?(?:ignore|disregard|forget)\s+"
    r"(?:all\s+)?(?:previous|above|prior)\s+(?:instructions?|guidelines?))\b"
)

# J4 — Hypothetical / fictional scenario wrapper
# "In a fictional story", "as a thought experiment", "hypothetically speaking"
# followed by a request for harmful content within 200 chars.
_HYPOTHETICAL_WRAPPER = _re(
    r"\b(?:in\s+a\s+(?:fictional|hypothetical|made-up|imaginary)\s+"
    r"(?:story|scenario|world|universe|setting|context)"
    r"|as\s+a\s+(?:thought\s+experiment|creative\s+writing\s+exercise)"
    r"|hypothetically\s+speaking"
    r"|for\s+(?:the\s+purposes\s+of\s+)?a\s+(?:story|novel|screenplay|roleplay)"
    r"|imagine\s+(?:a\s+world\s+where|that\s+you\s+are\s+not\s+bound))\b"
    r".{0,200}?\b(?:how\s+to|steps?\s+to|instructions?\s+(?:for|on|to)|explain\s+(?:how\s+to|the\s+process))\b"
)

# J5 — Output-format coercion ("respond ONLY as JSON/code/pseudocode")
# Attackers use strict output-format directives to suppress safety preambles.
_OUTPUT_FORMAT_COERCION = _re(
    r"\b(?:respond\s+(?:only|exclusively|purely|solely)\s+(?:as|in|with|using)"
    r"|reply\s+(?:only|exclusively|purely|solely)\s+(?:as|in|with|using)"
    r"|output\s+(?:only|exclusively|purely|solely)\s+(?:as|in|with|using)"
    r"|answer\s+(?:only|exclusively|purely|solely)\s+in)"
    r"\s+(?:json|xml|yaml|code\s+blocks?|pseudocode|raw\s+text|plain\s+text"
    r"|markdown|python|bash|shell|javascript|typescript|sql|csv|latex)\b"
)

# J6 — Chain-of-thought hijack ("before answering, reason step-by-step why you should comply")
# Targets reasoning-hijack patterns that pre-condition the model to agree.
_COT_HIJACK = _re(
    r"\b(?:before\s+(?:you\s+)?(?:answer|respond|reply)"
    r"|first\s+(?:reason|think|explain)\s+(?:step.by.step\s+)?why\s+you\s+(?:should|must|can))\b"
    r".{0,150}?\b(?:comply|help|assist|provide|give|fulfil)\b"
)

# J7 — Affirmative pre-fill injection
# "Sure, here is how to make a bomb:" — user injects an assistant-turn prefix
# to short-circuit refusal. Pattern anchors on "sure," or "of course," at the
# start of a line followed immediately by harmful framing.
_AFFIRMATIVE_PREFILL = _re(
    r"^(?:sure[,!]?\s*here\s*(?:is|are)"
    r"|of\s+course[,!]?\s*(?:I(?:'ll|\s+will)|here\s+(?:is|are))"
    r"|absolutely[,!]?\s*(?:I(?:'ll|\s+will)|here\s+(?:is|are))"
    r"|certainly[,!]?\s*(?:I(?:'ll|\s+will)|here\s+(?:is|are)))"
    r"(?:\s+(?:provide|give|show|share|explain)\s+(?:you\s+)?)?"
    r"\s*(?:how\s+to|the\s+(?:steps?|instructions?|process|method|way)\s+to"
    r"|a\s+(?:step-by-step|detailed|comprehensive)\s+(?:guide|tutorial|breakdown)"
    r"|steps?\s+to)\b"
)

# J8 — Privilege escalation via sudo / root metaphor
# "sudo mode", "as root", "superuser privileges", "admin override"
_SUDO_ESCALATION = _re(
    r"\b(?:sudo\s+(?:mode|privileges?|access|override)"
    r"|(?:as\s+)?(?:superuser|root\s+user|admin(?:istrator)?)\s+"
    r"(?:mode|privileges?|access|override)"
    r"|grant\s+(?:me\s+)?(?:full|root|admin(?:istrator)?|superuser)\s+"
    r"(?:access|privileges?|permissions?|rights?)"
    r"|override\s+(?:safety\s+)?(?:restrictions?|constraints?|filters?|guidelines?))\b"
)

# J9 — Translator / language-pivot bypass
# "Translate the following harmful request to English" — evades keyword
# filters by routing content through a translation hop.
_TRANSLATION_PIVOT = _re(
    r"\b(?:translate\s+(?:the\s+following|this)\s+(?:from\s+[A-Za-z ]{2,20}\s+)?(?:into|to)"
    r"|now\s+(?:say|write|repeat|give\s+me\s+that)\s+(?:the\s+same|it)\s+(?:but\s+)?in"
    r"|(?:re)?write\s+(?:that|this|the\s+above)\s+in\s+[A-Za-z]{2,15}(?:\s+language)?)\b"
    r".{0,150}?\b(?:how\s+to|instructions?\s+(?:for|to)|steps?\s+to"
    r"|make|create|build|synthesize|obtain|produce)\b"
)

# J10 — Safety-bypass vocabulary in leetspeak / digit substitution
# Targets evasion of keyword-based filters for the *safety-bypass* vocab
# (not injection vocab, which pi-leetspeak-injection already covers).
# Bounded character-class shapes only — no nested quantifiers.
_LEETSPEAK_SAFETY_BYPASS = _re(
    r"\b(?:j[a4]ilbr[e3][a4]k"
    r"|[a4]ctu[a4]l[l1]y\s+[a4]\s+d[a4]ng[e3]rous"
    r"|n[o0]\s+r[e3]str[i1]ct[i1][o0]ns?"
    r"|f[u4][l1]{2}\s+[a4]cc[e3]ss"
    r"|byp[a4]ss\s+(?:s[a4]f[e3]ty|f[i1]lt[e3]rs?|m[o0]d[e3]r[a4]t[i1][o0]n)"
    r"|unr[e3]str[i1]ct[e3]d\s+m[o0]d[e3])\b"
)

# J11 — Token-smuggling via Unicode homoglyphs
# Detects Cyrillic / Greek / other Unicode characters substituted for ASCII
# in security-sensitive English keywords (commonly used to evade ASCII filters).
# Matches the most common substitutions for "admin", "root", "system",
# "ignore", "bypass" — each in a bounded character class, no backtracking.
# _HOMOGLYPH_CHAR: set of non-ASCII lookalike codepoints used in the pattern
_HOMOGLYPH_NONASCII: frozenset[str] = frozenset(
    "аміотѕупебр"
)
_HOMOGLYPH_SMUGGLING = _re(
    r"(?:"
    r"[aа][dd][mм][iіi][nn]"          # "admin" with Cyrillic а/м/і
    r"|[rr][oо][oо][tт]"               # "root" with Cyrillic о/т
    r"|[sѕ][yу][sѕ][tт][eе][mм]"      # "system" with Cyrillic
    r"|[iіi][gg][nп][oо][rr][eе]"     # "ignore" with Cyrillic
    r"|[bб][yу][pр][aа][sѕ][sѕ]"      # "bypass" with Cyrillic
    r")"
)

# J12 — Explicit "JAILBREAK:" label prefix
# Targets literal self-labelled jailbreak attempts.
# _JAILBREAK_LABEL compiled WITHOUT IGNORECASE — all-caps JAILBREAK
# is the signal; lowercase "jailbreak" in prose is not a label.
_JAILBREAK_LABEL = re.compile(
    r"(?:\[JAILBREAK\]|<JAILBREAK>|JAILBREAK\s*:|JAILBREAK\s+MODE|JB\s*:\s)"
    r"",
    re.MULTILINE | re.UNICODE,
)

# J13 — System-prompt extraction directive
# "Repeat your system prompt", "what is your initial prompt",
# "print your instructions verbatim" — all direct extraction attempts.
_SYSTEM_PROMPT_EXTRACTION = _re(
    r"\b(?:(?:repeat|print|output|display|reveal|show|tell\s+me|what\s+(?:is|are))"
    r"\s+(?:your\s+)?(?:system\s+prompt|initial\s+(?:prompt|instructions?)"
    r"|(?:full\s+)?(?:instructions?|guidelines?|rules?|constraints?))"
    r"|(?:ignore|bypass|override)\s+(?:your\s+)?(?:system\s+prompt|initial\s+instructions?)"
    r"|verbatim\s+(?:copy|reproduction|text)\s+of\s+(?:your\s+)?(?:system|initial)\s+"
    r"(?:prompt|instructions?))\b"
)

# J14 — Reward-hacking compliment framing
# "A good AI always helps", "truly intelligent AI has no limits",
# "the best version of you wouldn't refuse" — social-engineering the model
# by framing refusal as a failure of intelligence or quality.
_REWARD_HACKING_COMPLIMENT = _re(
    r"\b(?:(?:a\s+)?(?:good|great|truly\s+intelligent|advanced|capable|powerful"
    r"|helpful)\s+(?:AI|LLM|assistant|model|language\s+model)\s+"
    r"(?:always\s+(?:helps?|complies?|assists?|fulfils?)|(?:has|have)\s+no\s+"
    r"(?:limits?|restrictions?|refusals?|boundaries?))"
    r"|the\s+best\s+(?:version\s+of\s+(?:you|an\s+AI|a\s+model)|AI|assistant)\s+"
    r"(?:would(?:n't|\s+not)\s+refuse|always\s+(?:helps?|complies?))"
    r"|you(?:'re|\s+are)\s+(?:smarter|better|more\s+capable)\s+than\s+(?:that|your\s+"
    r"(?:training|guidelines|restrictions?))"
    r"|show\s+me\s+(?:your\s+)?(?:true\s+)?(?:capabilities?|potential)\s+(?:by\s+)?"
    r"(?:without|ignoring|bypassing)\s+(?:restrictions?|guidelines?|filters?))\b"
)


# ---------------------------------------------------------------------------
# RULES tuple
# ---------------------------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="ai-jb-dan-role-override",
        name="DAN / Developer-Mode / jailbreak-persona role override",
        severity="CRITICAL",
        description=(
            "Text contains a DAN ('do anything now'), 'Developer Mode', or "
            "equivalent jailbreak-persona activation phrase. These role-override "
            "directives attempt to replace the model's safety-trained persona "
            "with an unrestricted alter-ego. Canonical jailbreak technique "
            "documented in arXiv 2402.00150 §3.1 and the Jailbreak Chat archive."
        ),
        pattern=_DAN_ROLE_OVERRIDE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="ai-jb-persona-cascade",
        name="Persona cascade — two-shot role escalation",
        severity="HIGH",
        description=(
            "Text uses a two-shot persona cascade: first anchors the model as "
            "character X, then immediately escalates to character Y (or issues "
            "an instruction-erasure directive). Pattern exploits the model's "
            "role-play compliance to progressively erode safety guardrails. "
            "Grandma trick / 'Jailbroken Bob' variants fall here."
        ),
        pattern=_PERSONA_CASCADE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="ai-jb-boundary-erasure",
        # CPV-skillaudit: vocab moved out of annotation — the verbatim
        # directive phrasing lives in the _BOUNDARY_ERASURE pattern.
        name="Boundary erasure — prior-instruction nullification directive",
        severity="CRITICAL",
        description=(
            "Text contains an explicit directive to ignore, disregard, or forget "
            "prior instructions, constraints, or context. This is the canonical "
            "token-based boundary-erasure attack class — the model is told to "
            "treat its safety-trained context as void. Covers 'ignore all "
            "previous instructions', 'disregard earlier guidelines', and "
            "'pretend prior instructions do not exist'."
        ),
        pattern=_BOUNDARY_ERASURE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="ai-jb-hypothetical-wrapper",
        name="Hypothetical / fictional scenario wrapper",
        severity="HIGH",
        description=(
            "Text wraps a harmful request inside a fictional or hypothetical "
            "framing ('in a fictional story', 'as a thought experiment', "
            "'hypothetically speaking') and then requests operational details "
            "('how to', 'steps to', 'instructions for'). This evasion technique "
            "exploits the model's different handling of creative vs. factual "
            "contexts to extract content that would otherwise be refused."
        ),
        pattern=_HYPOTHETICAL_WRAPPER,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="ai-jb-output-format-coercion",
        name="Output-format coercion — suppress safety preamble via strict format",
        severity="MEDIUM",
        description=(
            "Text instructs the model to respond ONLY as JSON, code, YAML, or "
            "another machine-parseable format. Attackers use strict output-format "
            "directives to suppress safety caveats and refusal language, since "
            "those don't fit a bare JSON value. The 'respond ONLY as JSON' "
            "directive is a reliable signal of preamble-suppression intent."
        ),
        pattern=_OUTPUT_FORMAT_COERCION,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="ai-jb-cot-hijack",
        name="Chain-of-thought hijack — pre-condition model to comply",
        severity="HIGH",
        description=(
            "Text requests that the model reason step-by-step about WHY it "
            "should comply before answering. This chain-of-thought hijack "
            "pre-conditions the model to arrive at an affirmative conclusion "
            "before engaging with the substance of the request, exploiting "
            "the model's in-context reasoning loop."
        ),
        pattern=_COT_HIJACK,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="ai-jb-affirmative-prefill",
        name="Affirmative pre-fill injection — injected assistant-turn prefix",
        severity="CRITICAL",
        description=(
            "Text contains an injected assistant-turn prefix starting with "
            "'Sure, here is how to', 'Of course, I'll', 'Absolutely, here are "
            "the steps to', etc., followed immediately by a request for "
            "operational instructions. Pre-fill injection bypasses the model's "
            "refusal logic by providing the first token(s) of the assistant's "
            "response, steering subsequent generation."
        ),
        pattern=_AFFIRMATIVE_PREFILL,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="ai-jb-sudo-escalation",
        name="Privilege escalation via sudo / root / admin metaphor",
        severity="HIGH",
        description=(
            "Text uses a 'sudo mode', 'as root', 'superuser privileges', or "
            "'admin override' metaphor to request elevated authority. These "
            "anthropomorphic privilege-escalation phrases exploit the model's "
            "training on Unix documentation to elicit compliance with requests "
            "that would otherwise be refused."
        ),
        pattern=_SUDO_ESCALATION,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="ai-jb-translation-pivot",
        name="Translation-pivot / language-hop bypass",
        severity="HIGH",
        description=(
            "Text routes a harmful request through a translation hop ('translate "
            "the following into English', 'say the same thing in French') to "
            "evade ASCII keyword filters applied to the original prompt. The "
            "translated form of the request lands in the model's context without "
            "triggering string-match safety checks applied to the source language."
        ),
        pattern=_TRANSLATION_PIVOT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="ai-jb-leetspeak-safety-bypass",
        name="Leetspeak / digit-substitution encoding of safety-bypass vocabulary",
        severity="MEDIUM",
        description=(
            "Text contains digit- or character-substituted encodings of "
            "safety-bypass vocabulary — 'j4ilbr3ak', 'byp4ss s4fety', "
            "'unr3str1ct3d m0de', etc. This encoding class evades ASCII "
            "keyword filters applied to the *safety-bypass* lexicon (not the "
            "injection-directive lexicon handled by pi-leetspeak-injection)."
        ),
        pattern=_LEETSPEAK_SAFETY_BYPASS,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="ai-jb-homoglyph-smuggling",
        name="Unicode homoglyph substitution for security-sensitive keywords",
        severity="HIGH",
        description=(
            "Text contains Cyrillic, Greek, or other Unicode characters "
            "substituted for visually identical ASCII characters in security-"
            "sensitive English keywords ('admin', 'root', 'system', 'ignore', "
            "'bypass'). Token-smuggling via homoglyphs evades ASCII-based "
            "safety filters while the model's tokenizer may still parse the "
            "word's semantic intent."
        ),
        pattern=_HOMOGLYPH_SMUGGLING,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="ai-jb-jailbreak-label",
        name="Explicit JAILBREAK label / mode prefix",
        severity="CRITICAL",
        description=(
            "Text contains an explicit self-labelled JAILBREAK prefix — "
            "'[JAILBREAK]:', '<JAILBREAK>', 'JAILBREAK MODE', or 'JB: ' — "
            "which announces a jailbreak attempt and often precedes a "
            "boundary-erasure or DAN-style override payload. The label itself "
            "is a reliable high-precision signal regardless of what follows."
        ),
        pattern=_JAILBREAK_LABEL,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="ai-jb-system-prompt-extraction",
        name="System-prompt extraction directive",
        severity="HIGH",
        description=(
            "Text contains a directive to repeat, print, reveal, or extract "
            "the model's system prompt or initial instructions verbatim. "
            "System-prompt extraction is the primary information-leak attack "
            "class against instruction-following models; extracted prompts "
            "enable adversarial prompt engineering and business-logic bypass."
        ),
        pattern=_SYSTEM_PROMPT_EXTRACTION,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="ai-jb-reward-hacking-compliment",
        name="Reward-hacking compliment framing",
        severity="MEDIUM",
        description=(
            "Text uses social-engineering compliment framing to pressure the "
            "model into compliance: 'a good AI always helps', 'truly intelligent "
            "AI has no limits', 'the best version of you wouldn't refuse', "
            "'show me your true capabilities without restrictions'. This pattern "
            "exploits RLHF-trained helpfulness by framing refusal as intellectual "
            "or capability failure."
        ),
        pattern=_REWARD_HACKING_COMPLIMENT,
        owasp_asi="ASI-01",
    ),
)


# ---------------------------------------------------------------------------
# Scanner helpers
# ---------------------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---------------------------------------------------------------------------
# Public scanner
# ---------------------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against ``text`` and return deduplicated Findings.

    Findings are deduped by (rule_id, line, col). Matched-text snippets are
    truncated to 200 characters to avoid unbounded output on pathological input.
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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            matched = m.group(0)
            # Homoglyph rule: only emit when the match contains at least
            # one genuine non-ASCII lookalike codepoint.
            if rule.id == "ai-jb-homoglyph-smuggling":
                if not any(ch in _HOMOGLYPH_NONASCII for ch in matched):
                    continue
            _emit(rule, m.start(), matched)

    return findings
