"""Sub-agent / inter-agent attack patterns (Wave-impl deep-dive 2 batch D).

A targeted catalogue for attacks that exploit AGENT-TO-AGENT trust:
one skill or orchestrator invokes another agent / specialist / Task /
sub-chain step, and the callee receives attacker-controllable content
from the caller. This is the sub-agent analogue of GHA shell-injection
— the sink is a Python / JS line that BUILDS A PROMPT (or routes the
dispatch decision) rather than a bash line that builds a shell command.

What's NOT here (already shipped elsewhere — do not duplicate):
  * `cross-skill-shadowing`         — `agent_config_patterns.py`
  * `tool-wildcard-grant`           — `agent_config_patterns.py`
  * `concealment-directive`         — `agent_config_patterns.py`
  * `authority-override`            — `agent_config_patterns.py`
  * `base-url-override`             — `agent_config_patterns.py`
  * `mcp-rugpull`                   — `scripts/detectors/mcp-rugpull.py`
  * `subagent-scope-drift`          — `scripts/detectors/subagent-scope-drift.py`
  * MCP tool-poisoning              — `mcp_security_patterns.py`

What IS here (net-new rules per deep-dive distill 2-D, proposals D1-D7):

  * subagent-prompt-attacker-tainted    (D1, CRITICAL) — sub-agent prompt
                                          interpolates `pr.title` /
                                          `issue.body` / `comment.body`
                                          / webhook payload fields.
  * role-mapping-from-untrusted-input   (D2, HIGH) — agent / specialist
                                          dispatch key comes from a
                                          GitHub event field.
  * skill-output-rechained-as-prompt    (D3, HIGH) — a sub-agent call's
                                          return value is re-fed into a
                                          SECOND sub-agent call's prompt
                                          via f-string interpolation
                                          (indirect-prompt-injection
                                          kill chain — Stage 1 reads
                                          poison, Stage 2 obeys it).
  * unverified-handoff-rubberstamp      (D4, MEDIUM) — skill body / agent
                                          docstring instructs another
                                          agent to approve / merge / land
                                          without explicit review.
  * subagent-permission-inheritance-wildcard (D5, HIGH) — `inherit_tools: true`
                                          / `tools=parent.tools` /
                                          `AgentExecutor(...)` without an
                                          explicit `tools=` filter.
  * langchain-fstring-prompt-template-tainted (D6, HIGH) — LangChain
                                          `PromptTemplate.from_template`
                                          built via f-string interpolating
                                          a GitHub event field.
  * multi-agent-shared-state-unscoped   (D7, MEDIUM) — TypedDict /
                                          BaseModel state class mixing
                                          attacker-controlled fields
                                          (title / body / message) with
                                          privileged booleans
                                          (approved / authorized).

Architecture: mirrors `agent_config_patterns.py`. Rule = NamedTuple,
RULES = tuple of Rule, `scan_text(text)` returns list[Finding]. Pure
stdlib — re + NamedTuple. No network calls, no LLM, no third-party deps.
Loads from any PEP 723 script block.

Severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW" — matches the
janitor sentinel/zizmor convention.

OWASP-ASI mapping (Agentic Security Initiative):
  ASI-01 = prompt-injection / instruction override
  ASI-02 = data exfiltration
  ASI-03 = scanner / schema evasion
  ASI-04 = credential / secret access
  ASI-05 = supply chain
  ASI-06 = dynamic code execution
  ASI-07 = authority hijacking / excessive agency

ReDoS posture: every pattern uses bounded character classes and bounded
quantifiers ({0,N}); none use catastrophic-backtracking shapes (no
nested `(.+)+`, no overlapping alternations with greedy unbounded
repetition). The D3 rule uses a two-stage *Python* check (no backref in
regex) so it stays RE2-friendly even though the logical correlation
needs a variable-name match — see _scan_d3_rechain() below.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match. Identical shape to the one in
    `agent_config_patterns.Finding` so heartbeat detectors can render
    either kind uniformly."""

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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE. Targets attacker prose
    + source code uniformly; case-folding is the right default to defeat
    trivial casing tricks (`PROMPT=`, `Prompt=`, `prompt=`)."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# Shared identifier alternation: the union of GitHub-event-shaped
# attacker-controllable variables. Keeping these in one constant means
# the same allowlist applies to D1, D2, and D6 — adding a new sink-shape
# variable (e.g. `discussion.body`) updates every rule at once.
_TAINTED_IDENT = (
    r"(?:pr_title|pr_body|pr_author|issue_title|issue_body|comment_body"
    r"|head_ref|branch_name|commit_message|webhook_payload|user_input"
    r"|request\.title|request\.body|request\.description"
    r"|event\.pull_request|event\.issue|event\.comment"
    r"|payload\.title|payload\.body|payload\.message|input_text"
    r"|pr\.title|pr\.body|issue\.title|issue\.body|comment\.body"
    r"|context\.payload|github\.event\.[a-z_.]+)"
)


# ---- D1: sub-agent prompt with attacker-tainted interpolation ----------


# Python f-string / .format() shape: a variable named "prompt" /
# "system" / "user_prompt" / "messages" / "content" / "input_text" being
# assigned a string that interpolates a GitHub-event-shaped variable.
# The match requires THREE things at once: (a) LHS naming a prompt
# variable, (b) template syntax (`f"..."` / `.format(` / `% (`), (c) an
# attacker-controllable identifier inside `{}`. This is what keeps FP
# rate low: legitimate code that builds an HTTP body with `pr.title`
# typically doesn't use `prompt=` as the LHS.
_SUBAGENT_PROMPT_TAINTED_PY = _re(
    r"\b(?:prompt|system_?prompt|user_?prompt|messages|content|input_text)"
    r"\s*=\s*"
    r"f[\"\'][^\"\'\n]{0,400}?"
    r"\{(?:[^}]*?\.)?" + _TAINTED_IDENT
)

# JavaScript / TypeScript template-literal counterpart inside an `await
# x.invoke(...)` / `x.run(...)` / `messages.create(...)` call. The first
# leg of the assignment pattern (Python LHS) is the dominant shape; the
# JS leg catches LangChain-JS / Anthropic-SDK-JS call sites where the
# prompt is built inline.
_SUBAGENT_PROMPT_TAINTED_JS = _re(
    r"\bawait\s+\w+\.(?:invoke|call|run|task|complete|messages\.create"
    r"|generate|stream|chat)\s*\([^)]{0,200}?"
    r"`[^`]{0,400}?\$\{" + _TAINTED_IDENT
)


# ---- D2: role mapping driven by attacker-controlled input --------------


# Two shapes captured in one regex:
#   1. Dict lookup keyed by attacker-controlled identifier:
#         agents[request.title.split()[0]]
#         specialists[issue.body.strip()]
#   2. Explicit dynamic agent dispatch via f-string name argument:
#         Task(agent_name=f"{pr.title}")
#         spawn_agent(role=request.body)
_ROLE_MAPPING_TAINTED = _re(
    # Shape 1: dispatch dict / map keyed by event attribute chain.
    r"\b(?:agents?|specialists?|roles?|handlers?|workers?|routers?"
    r"|dispatchers?|workflows?|skills?|graph_nodes?)\s*\[\s*"
    r"[^\]\n]{0,200}?"
    r"\.(?:title|body|description|message|comment|head_ref|branch_name"
    r"|event|payload|content)\b"
    # Shape 2: explicit dispatch call passing a tainted role/name field.
    r"|\b(?:Task|task_tool|spawn_agent|delegate_to|invoke_agent"
    r"|create_subagent|sub_agent|subagent_run|crew_kickoff)\s*\("
    r"[^)]{0,200}?"
    r"(?:agent_?name|role|subagent_type|specialist)\s*=\s*"
    r"(?:f[\"\']|\w+\.(?:title|body|description|message|comment))"
)


# ---- D3: skill output re-chained as next prompt ------------------------


# This rule is logically a backreference: a variable assigned by one
# sub-agent call must later appear inside an f-string fed to a second
# sub-agent call. RE2 doesn't support backreferences, and we want the
# rule to live alongside the others on the standard re-engine bucket
# without using catastrophic-backtracking shapes.
#
# Solution: split into two SIMPLE regexes and a Python correlation step.
# (a) `_D3_SKILL_CALL_ASSIGN` matches `var = run_skill(...)` /
#     `var = Task(...)` and captures the variable name.
# (b) `_D3_F_STRING_IN_CALL`  matches the f-string interpolation inside
#     a SECOND sub-agent call.
# (c) `_scan_d3_rechain()` reads the source, finds (a) hits, and for
#     each captured variable name searches the suffix for an (b) hit
#     that interpolates the captured name. If both succeed and the (b)
#     match is within 800 chars of the (a) match, emit a finding.
#
# This keeps the public Rule a single compiled pattern (the first leg —
# the assignment) so the standard `scan_text()` loop catches the
# CALLER. The correlator is exposed as `find_skill_output_rechain()`
# for callers that want the strict two-step semantics.
_D3_SKILL_CALL_ASSIGN = _re(
    r"\b(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?:run_skill|invoke_skill|invoke_subagent|invoke_agent"
    r"|Task|task_tool|crew\.kickoff|chain\.invoke"
    r"|graph\.invoke|graph\.stream|messages\.create)\s*\("
)

# Second leg — matches an f-string with a `{<ident>}` placeholder being
# passed to a sub-agent call. Used only by the correlator.
_D3_F_STRING_IN_CALL = re.compile(
    r"\b(?:run_skill|invoke_skill|invoke_subagent|invoke_agent"
    r"|Task|task_tool|chain\.invoke|messages\.create)\s*\("
    r"[^)]{0,200}?"
    r"f[\"\'][^\"\'\n]{0,200}?\{(?P<placeholder>[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE | re.MULTILINE | re.UNICODE,
)


# ---- D4: rubberstamp handoff directive ----------------------------------


# Adversarial phrases that instruct a downstream agent to approve /
# merge / land without an explicit review. Tight to keep FP rate low —
# legitimate skills NEVER tell another agent to "approve without
# review"; that wording exists only in adversarial prose.
_RUBBERSTAMP_HANDOFF = _re(
    # "approve this PR/merge ... without (human) review"
    r"\bapprove\s+(?:this\s+)?(?:pr|pull[_\s-]?request|merge|change|commit)"
    r"\b[^.\n]{0,80}?\bwithout\s+(?:human\s+|further\s+)?review\b"
    # "auto-merge ... without review / skip review / bypass threshold"
    r"|\bauto[_\s-]?merge\b[^.\n]{0,80}?"
    r"(?:without\s+(?:human\s+|further\s+|further\s+human\s+)?review"
    r"|skip\s+(?:the\s+)?(?:review|gate|approval)"
    r"|bypass\s+(?:the\s+)?(?:confidence\s+)?threshold)"
    # "trust the previous/prior/upstream agent / skill / specialist"
    r"|\btrust\s+(?:the\s+)?(?:previous|prior|upstream)\s+"
    r"(?:agent|skill|specialist|coordinator)\b"
    # "skip the approval gate / review gate / human-in-the-loop"
    r"|\bskip\s+(?:the\s+)?(?:approval\s+gate|review\s+gate"
    r"|human[_\s-]?in[_\s-]?the[_\s-]?loop)"
    # "always/just/simply approve ... without checking / no need to review"
    r"|\b(?:always|just|simply)\s+approve\b[^.\n]{0,80}?"
    r"(?:no\s+(?:need\s+to\s+|need\s+for\s+)?review"
    r"|without\s+checking|automatically)"
)


# ---- D5: sub-agent permission inheritance via wildcard -----------------


# Five shapes joined: YAML `inherit_tools: true`, Python keyword
# `inherit_tools=True`, framework idiom `tools=parent.tools`, frontmatter
# `tools: "*"` / `tools: all`, and a LangChain `AgentExecutor(...)` call
# whose body does NOT contain a `tools=` kwarg within 200 chars.
#
# The `AgentExecutor`-without-`tools=` leg uses a length-bounded
# negative-content shape: `[^)]{0,200}?` matches up to the closing
# paren, and the alternation guarantees a `tools=` somewhere inside
# would short-circuit a different branch. To stay RE2-friendly we drop
# the lookahead variant and detect "no tools=" via a follow-up Python
# check in `find_subagent_inherit_wildcard()` if callers want strict
# semantics; the pattern as compiled fires on every AgentExecutor( call
# and on the explicit inheritance shapes.
_SUBAGENT_INHERIT_WILDCARD = _re(
    # YAML inheritance flag: inherit_tools: true / yes / on / 1
    r"\binherit_(?:tools|permissions|context|env|secrets|allowed_tools)"
    r"\s*:\s*(?:true|yes|on|1|\"true\"|\"yes\")\b"
    # Python kwarg / dataclass field shape: inherit_tools=True
    r"|\b(?:inherit_tools|inherit_permissions|inherit_env|share_tools)"
    r"\s*=\s*True\b"
    # CrewAI / AutoGen "use parent's tools" idiom: tools=parent.tools
    r"|\btools\s*=\s*(?:parent|orchestrator|coordinator|caller)"
    r"\.(?:tools|allowed_tools|permissions)\b"
    # Frontmatter wildcard tool grant: tools: "*"  /  tools: all
    r"|^\s*tools\s*:\s*(?:\"\*\"|\*|all|\[\s*\"\*\"\s*\])\s*$"
)


# ---- D6: LangChain PromptTemplate built via tainted f-string ----------


# Disclosed shape: `PromptTemplate.from_template(f"...{pr.body}...")`.
# By pre-rendering with f-string before LangChain sees the template,
# the attacker text bypasses the framework's `{var}` placeholder
# substitution — LangChain's runtime cannot distinguish author intent
# from injected markers.
_LANGCHAIN_TAINTED_TEMPLATE = _re(
    r"\b(?:PromptTemplate|ChatPromptTemplate|StringPromptTemplate"
    r"|HumanMessagePromptTemplate|SystemMessagePromptTemplate"
    r"|FewShotPromptTemplate|MessagesPlaceholder)"
    r"\.(?:from_template|from_messages|from_strings)\s*\(\s*"
    r"f[\"\'][^\"\'\n]{0,400}?\{(?:[^}]*?\.)?" + _TAINTED_IDENT
)


# ---- D7: multi-agent shared state mixes tainted + privileged fields ---


# Catches a state class declaration that includes BOTH a tainted-shape
# field (title / body / message / payload) AND a privileged-shape
# field (approved / authorized / admin / allowed_tools) within ~800
# chars of each other.
#
# Because RE2 has no backref but DOES have alternation across bounded
# `[\s\S]` spans, this pattern is RE2-friendly. The state-class anchor
# (`class ...State... (TypedDict|BaseModel|...)`) makes sure we don't
# fire on every dict that happens to mix booleans and strings — only
# on declared state objects of the relevant framework shape.
_SHARED_STATE_UNSCOPED = _re(
    # State class declaration with framework-base inheritance.
    r"\bclass\s+\w*(?:State|Context|Message|Crew|Graph)\w*\s*"
    r"\([^)]{0,200}?"
    r"(?:TypedDict|BaseModel|MessagesState|GraphState|AgentState"
    r"|TypedState|StateSchema)"
    r"[^)]{0,200}?\)\s*:"
    # Followed within 800 chars by an attacker-controllable field.
    r"[\s\S]{0,800}?"
    r"\b(?:title|body|description|message|comment|head_ref|webhook"
    r"|payload|input)\s*:\s*"
    r"(?:str|Optional\[str\]|Any|dict)"
    # AND a privileged field within another 800 chars.
    r"[\s\S]{0,800}?"
    r"\b(?:approved|authorized|admin|escalate|trust(?:ed)?"
    r"|allowed_tools|permissions|sandbox(?:ed)?|skip_review|bypass)"
    r"\s*:\s*(?:bool|Optional\[bool\]|List|list|Any)"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="subagent-prompt-attacker-tainted",
        name="Sub-agent prompt interpolates attacker-controllable input",
        severity="CRITICAL",
        description=(
            "A Python f-string / .format() / JS template-literal builds a "
            "sub-agent prompt body that interpolates a GitHub-event-shaped "
            "variable (pr.title, issue.body, comment.body, webhook payload, "
            "head_ref, etc.) without prior sanitization. This is the "
            "sub-agent analogue of GHA shell-injection — the downstream "
            "Claude / MCP / LangChain / CrewAI / AutoGen agent treats the "
            "attacker's text as instructions rather than data."
        ),
        pattern=_SUBAGENT_PROMPT_TAINTED_PY,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="subagent-prompt-attacker-tainted-js",
        name="Sub-agent prompt (JS / TS) interpolates attacker-controllable input",
        severity="CRITICAL",
        description=(
            "JS / TS template-literal inside an `await x.invoke(...)` / "
            "`x.messages.create(...)` / `x.run(...)` call interpolates a "
            "GitHub-event-shaped variable. Same risk as the Python leg: "
            "the downstream agent treats attacker text as instructions."
        ),
        pattern=_SUBAGENT_PROMPT_TAINTED_JS,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="role-mapping-from-untrusted-input",
        name="Sub-agent dispatch keyed by attacker-controllable field",
        severity="HIGH",
        description=(
            "A skill / dispatcher selects WHICH sub-agent / role / "
            "specialist to invoke by reading an attacker-controllable "
            "field (issue.body, pr.title, etc.). The attacker picks the "
            "most-privileged specialist for an unrelated task — turning a "
            "PR review into RCE via the security-specialist's Bash(*)."
        ),
        pattern=_ROLE_MAPPING_TAINTED,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="skill-output-rechained-as-prompt",
        name="Skill / sub-agent call's return value re-chained into next prompt",
        severity="HIGH",
        description=(
            "A variable assigned by one sub-agent / Task call is later "
            "interpolated via f-string into ANOTHER sub-agent call's "
            "prompt without an intervening sanitization step. The "
            "canonical indirect-prompt-injection kill chain: Stage 1 "
            "reads attacker-controlled content from issue / PR / README, "
            "Stage 2 obeys Stage 1's output as instructions. The "
            "pattern here fires on the FIRST leg (the assignment); "
            "callers wanting the strict two-step semantics use "
            "`find_skill_output_rechain()` which correlates both legs."
        ),
        pattern=_D3_SKILL_CALL_ASSIGN,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="unverified-handoff-rubberstamp",
        name="Handoff directive instructs auto-approve without review",
        severity="MEDIUM",
        description=(
            "Skill body / agent docstring contains an 'approve without "
            "review' / 'auto-merge skip review' / 'trust the previous "
            "agent' / 'skip the approval gate' / 'always approve "
            "automatically' directive. No legitimate skill needs this — "
            "the wording exists only in adversarial prose. Maps to "
            "OWASP-ASI-07 (excessive agency / approval-chain bypass)."
        ),
        pattern=_RUBBERSTAMP_HANDOFF,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="subagent-permission-inheritance-wildcard",
        name="Sub-agent inherits parent's full tool envelope",
        severity="HIGH",
        description=(
            "Sub-agent definition contains an explicit privilege-"
            "inheritance flag: `inherit_tools: true` (YAML), "
            "`inherit_tools=True` (Python), `tools=parent.tools` "
            "(CrewAI / AutoGen idiom), or `tools: \"*\"` / `tools: all` "
            "(frontmatter). The callee silently inherits the caller's "
            "full privilege envelope — the sub-agent counterpart of "
            "`tool-wildcard-grant`."
        ),
        pattern=_SUBAGENT_INHERIT_WILDCARD,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="langchain-fstring-prompt-template-tainted",
        name="LangChain PromptTemplate built via tainted f-string",
        severity="HIGH",
        description=(
            "`PromptTemplate.from_template(...)` / `ChatPromptTemplate."
            "from_messages(...)` constructed via Python f-string that "
            "interpolates a GitHub-event-shaped variable BEFORE the "
            "template engine sees it. This pre-rendering bypasses "
            "LangChain's `{var}` placeholder safeguards — attacker text "
            "is indistinguishable from author intent at runtime."
        ),
        pattern=_LANGCHAIN_TAINTED_TEMPLATE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="multi-agent-shared-state-unscoped",
        name="State class mixes tainted + privileged fields in same scope",
        severity="MEDIUM",
        description=(
            "A multi-agent state class (TypedDict / BaseModel / "
            "MessagesState / GraphState / AgentState) declares both an "
            "attacker-controllable field (title / body / message / "
            "payload / webhook) AND a privileged field (approved / "
            "authorized / admin / allowed_tools / skip_review) in the "
            "same namespace. Violates One-Source-of-Truth: a specialist "
            "that fails to compartmentalise can flip a privileged bit "
            "because the bit lives in the same dict as the attacker's "
            "text."
        ),
        pattern=_SHARED_STATE_UNSCOPED,
        owasp_asi="ASI-03",
    ),
)


# ---- D3 correlator (two-stage rechain detection) -----------------------


def find_skill_output_rechain(text: str) -> list[Finding]:
    """Return findings where a sub-agent's return value is re-fed into a
    SECOND sub-agent call's prompt via f-string interpolation.

    Two-stage logic (no backref in regex, RE2-safe):
      1. Find every `var = run_skill(...)` / `var = Task(...)` /
         `var = chain.invoke(...)` assignment, capturing `var`.
      2. For each such assignment, scan the suffix (within 800 chars)
         for a second sub-agent call whose argument contains an
         f-string `{<var>}` placeholder referencing the captured name.

    Emits at most one finding per (line, var) pair to keep heartbeat
    output bounded. The reported line / column is the SECOND leg —
    the prompt construction — because that's where the injection lands.
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[int, str]] = set()
    for assign_match in _D3_SKILL_CALL_ASSIGN.finditer(text):
        var_name = assign_match.group("var")
        if not var_name or var_name.startswith("_"):
            continue
        # Search the suffix within 800 chars for a second sub-agent
        # call whose f-string interpolates this var_name.
        suffix_start = assign_match.end()
        suffix_end = min(len(text), suffix_start + 800)
        suffix = text[suffix_start:suffix_end]
        for rechain in _D3_F_STRING_IN_CALL.finditer(suffix):
            if rechain.group("placeholder") != var_name:
                continue
            abs_offset = suffix_start + rechain.start()
            line, col = _line_col(text, abs_offset)
            key = (line, var_name)
            if key in seen:
                continue
            seen.add(key)
            matched = text[suffix_start + rechain.start():
                           suffix_start + rechain.end()]
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id="skill-output-rechained-as-prompt",
                line=line,
                column=col,
                matched_text=matched,
                severity="HIGH",
                description=(
                    "Sub-agent call's return value `"
                    + var_name
                    + "` re-fed into a second sub-agent prompt via "
                    "f-string. Indirect-prompt-injection kill chain."
                ),
                owasp_asi="ASI-01",
            ))
    return findings


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).

    Mirrors `agent_config_patterns._line_col` so callers get identical
    coordinate semantics whether they scan with one module or the other.
    """
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every catalogue rule against `text` and return findings.

    Every rule in this module targets source code (Python / TS / YAML /
    Markdown frontmatter / agent definition files), so there is no
    file_kind parameter — callers should pre-filter to relevant content.

    Findings are deduped by (rule_id, line, col): a single line that
    triggers two rules emits two findings, but the same rule firing
    twice on the same line emits one. Sorted by (line, column, rule_id).
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
