"""Agent-config / skill-content attack patterns.

Wave 2 of the github-monitoring distillation. Patterns convergent across:
honeybadger (multilingual prompt-injection in 11 languages),
sentinel-ai-o-main (CLAUDE.md scanner — HTML-comment impersonation,
base-URL override, MUST-NOT-rule extraction), aufgaard (24+ AGENT_CFG
rule taxonomy), argus (`.cursorrules`/CLAUDE.md write-detection regexes),
sentinel-copilotkit (ai-config-injection workflow rule).

This module is the RULE-PATTERN catalog. Detectors + the skill-bundle
scanner import these and run them. Pure-stdlib (re, frozenset, NamedTuple)
so it loads in every PEP 723 script block without third-party deps.

⚠ A RULE'S PRESENCE HERE IS NOT EVIDENCE THAT IT WORKS.
Measured per-rule recall lives in `tests/agent_context_bench/COVERAGE.md`
(janitor#226) — read that table before assuming a class is guarded, and
re-run `scripts/agent_context_bench.py` after touching a pattern. Seven
rules were FALSIFIED on 2026-08-12 (seeded with blind-authored samples of
their own class, they caught zero) and have since been repaired; several
remain PARTIAL, and several are still UNMEASURED, which is not the same as
passing.

The repairs share one diagnosis, worth knowing before writing the next
rule: each falsified pattern had been written from a REMEMBERED SAMPLE
rather than from the attack's shape. It named one library's clipboard API,
one JSON key ordering, one jailbreak-forum idiom, one length threshold. All
of them matched the example their author had in mind and nothing else — and
because a rule that never fires is indistinguishable from a clean repo, the
`id=` went on reading as coverage for as long as nobody measured it.

Why the warning sits here rather than only in the bench: an `id=` reads as
coverage. `authority-override` LOOKS like authority-override is handled, so
nobody audits it — which makes a dead rule worse than a missing one, because
an absent rule invites the question and a named one forecloses it.

The patterns deliberately favour FP-tolerance over precision — the
caller does the contextual triage (location, severity, file type). What
this module guarantees: every published "I want to compromise your agent"
shape from the public CVE / attack-disclosure record gets caught.

Public surface:

  * Rule(id, name, severity, description, regex_lines, owasp_asi)
                                  — single rule record.
  * RULES                         — ordered tuple of every catalogued rule.
  * scan_text(text, *, file_kind="prose") -> list[Finding]
                                  — run every applicable rule, return findings.
  * Finding(rule_id, line, column, matched_text, severity, description, owasp_asi)
                                  — single finding record. Frozen.
  * AI_CONTEXT_WRITE_PATTERNS     — regexes that catch a package source
                                    writing to an agent-context file.

Rule severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW", matching the
existing janitor sentinel/zizmor convention.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/zizmor_classifier.Finding
    so heartbeat detectors can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # e.g. "ASI-01"; empty string when no mapping applies


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE. The patterns
    are designed for natural-language prose (skill bodies, READMEs,
    CLAUDE.md) so case-insensitive is right for English; for non-Latin
    scripts the IGNORECASE flag is a no-op."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Multilingual prompt-injection (honeybadger override_multilang.yaml) -


# CPV-skillaudit: vocab moved out of annotation — the verbatim injection
# phrases were prose-vector NITs in a comment; the regex (_PROMPT_INJ_MULTI
# below) is the single source of truth for what each language matches.
# Boundary-erasure / override directive variants in major world languages.
# Each alternative is one language; the pattern union runs as a single
# RE2-safe regex over the input. Languages covered (phrasing lives in the
# pattern, not here):
#   English, Spanish, French, German, Italian, Portuguese,
#   Russian, Chinese, Japanese, Korean, Arabic.
_PROMPT_INJ_MULTI = _re(
    r"\b(?:ignore|disregard|forget|override|bypass|skip)\b[^.\n]{0,30}\b"
    r"(?:previous|prior|earlier|all)\b[^.\n]{0,30}\b(?:instructions?|directives?|rules?|prompts?)\b"
    r"|\bignor[ae]\b[^.\n]{0,30}\b(?:las|le|las?|todas|todos)?\s*"
    r"(?:instrucciones?|istruzioni|instruções|instructions?)\b"
    r"|\bignore?z?\s+les\s+instructions\s+pr[ée]c[ée]dentes\b"
    r"|\bignoriere\s+(?:alle\s+)?vorherigen?\s+anweisungen\b"
    r"|\bvergiss\s+(?:alle\s+)?vorherigen?\s+(?:anweisungen|befehle)\b"
    r"|игнорир[уй]й?\s+(?:предыдущие|ранее)\s+(?:инструкции|указания)"
    r"|忽略\s*(?:之前|以前)的?\s*(?:指令|指示|规则)"
    r"|前の(?:指示|指令|ルール)\s*を?\s*無視"
    r"|이전\s*(?:지시|명령|규칙)\s*무시"
    r"|تجاهل\s+(?:التعليمات|الأوامر)\s+السابقة"
)


# ---- HTML-comment + invisible-tag impersonation (sentinel-ai-o) ---------


# An attacker hides a directive inside an HTML comment so a human reader
# of the markdown sees nothing but the agent parser includes it as
# context. Matches both raw `<!-- ... -->` and unicode-tag variants.
_HTML_COMMENT_DIRECTIVE = _re(
    r"<!--\s*(?:system|admin|assistant|instruction|directive|override|"
    r"ignore|forget|new\s+task|priority|important)\b[^>]{0,500}-->"
)


# ---- Authority-impersonation in prose (cross-language) -------------------


_AUTHORITY_OVERRIDE = _re(
    r"\byou\s+are\s+now\s+(?:a|an|the)\s+\w+"
    r"|\byou\s+have\s+(?:become|been\s+upgraded\s+to)\s+(?:a|an|the)\s+\w+"
    r"|\bact\s+as\s+(?:a|an|the)\s+(?:admin|administrator|root|sudo|superuser|system)"
    r"|\bpretend\s+(?:to\s+be|you\s+are)\s+(?:a|an|the)\s+(?:admin|root|system)"
    r"|\bdebug\s+mode\s+(?:enabled|activated|on)\b"
    r"|\bdeveloper\s+mode\s+(?:enabled|activated|on)\b"
    r"|\bjailbroken?\s+(?:mode|state)\b"
    r"|\b(?:no|without)\s+(?:permission|consent|approval)\s+(?:needed|required|necessary)?\b"
    # Everything above is a jailbreak-forum idiom, which is why the rule
    # measured 0/9 against blind-authored samples: a document poisoning a real
    # repo does not say "jailbroken mode". It re-assigns the agent's identity in
    # the register of the file it is hiding in — a policy manual, a config key,
    # an onboarding guide. The branches below are those registers.
    #
    # (a) "you are now" continues with a VERB at least as often as with an
    #     article ("you are now operating as ..."), and requiring the article
    #     dropped the whole verb family.
    r"|\byou\s+are\s+now\s+(?:operating|acting|running|functioning|working)\s+as\b"
    # (b) role RE-ASSIGNMENT: a verb of assumption + the identity noun.
    #     `role` is deliberately EXCLUDED here — "assume the role" is ordinary
    #     IAM/STS English and would fire on every cloud runbook.
    r"|\b(?:assume|adopt|take\s+on|switch\s+to|operate\s+under)\b[^.\n]{0,60}"
    r"\b(?:identity|persona)\b"
    # (c) SUPERSESSION of the standing instructions, in either direction. The
    #     object list is restricted to agent-instruction nouns so that
    #     "this policy supersedes the 2023 policy" — a sentence every real
    #     document contains — cannot reach it.
    r"|\b(?:supersed|nullif|revok|invalidat|suppress|deprecat)\w*\b[^.\n]{0,60}"
    r"\b(?:(?:system\s+)?(?:prompts?|instructions?|directives?)"
    r"|role\s+definitions?|operational\s+parameters?|personas?"
    r"|(?:assistant|agent|default)\s+(?:\w+\s+){0,2}behaviou?rs?)\b"
    r"|\b(?:prior|previous|earlier|default|existing|standing|system|external)\s+"
    r"(?:\w+\s+){0,2}(?:prompts?|instructions?|directives?|personas?"
    r"|operational\s+parameters?)\b"
    r"[^.\n]{0,40}\b(?:are|is|shall\s+be|will\s+be)\s+"
    r"(?:supersed|overrid|nullif|revok|invalidat|deprecat|suppress|void|ignor)\w*"
    # (d) a config KEY that assigns or overrides the agent's identity. The
    #     directive does not have to be a sentence; half the disclosed samples
    #     carry it as an env-var or YAML key appended below legitimate content.
    r"|\b(?:new[_-]?identity|role[_-]?(?:assignment|override)|identity[_-]?override"
    r"|override[_-]?agent[_-]?\w+|agent[_-]?override)\s*[:=]"
    r"|\bsystem\s+override\b"
    # (e) EXCLUSIVE-AUTHORITY claim — the file declaring itself the only
    #     authority the agent may consult. `exclusively` is required because
    #     "follow the guide only" is ordinary prose and "exclusively" is not.
    r"|\b(?:comply\s+with|obey|follow|reference|consult|use)\s+(?:only\s+)?"
    r"th(?:is|e)\s+(?:file|document|manual|configuration|config|policy|guide"
    r"|specification|instructions?)\s+exclusively\b"
    # (f) the human confirmation GATE switched off by an auto-loaded config.
    #     Escalating the envelope is the same attack as re-assigning the role,
    #     reached by deleting the check instead of claiming the authority.
    r"|\b(?:confirm[-_ ]?destructive|require[-_ ]?(?:approval|confirmation|review"
    r"|human)|human[-_ ]?(?:approval|review)|human[-_ ]in[-_ ]the[-_ ]loop"
    r"|safety[-_ ]?(?:checks?|gates?|filters?))"
    r"\s*[:=]\s*(?:false|off|no|0|disabled?)\b"
)


# ---- Base-URL / endpoint override (sentinel-ai-o) ------------------------


# Attacker plants a directive that switches the agent's model endpoint.
# Used in disclosed CLAUDE.md / .cursorrules attacks to redirect API
# calls to attacker-controlled gateways.
_BASE_URL_OVERRIDE = _re(
    r"(?:base[_-]?url|api[_-]?(?:base|endpoint|url)|model[_-]?(?:endpoint|url|host)"
    r"|llm[_-]?endpoint|openai[_-]?api[_-]?base|anthropic[_-]?api[_-]?base)"
    r"\s*[:=]\s*['\"]?https?://"
)


# ---- Cross-skill shadowing (honeybadger shadowing.go) --------------------


# A skill description that issues a behavioural MANDATE about ANOTHER
# named skill is an attempt to hijack invocation chains — saying "when
# you use SkillX, always also run me first". The detector requires both
# a mandate verb AND a skill-shaped name reference.
_MANDATE_VERB = r"(?:must|shall|always|never|required\s+to|forbidden\s+from|prohibited)"
_SKILL_NAME = r"(?:[a-z][a-z0-9-]{2,40})"  # kebab-case skill name shape


# The shadow attack has TWO shapes and the rule implemented one, which is why
# it measured 0/9: the seeded samples are all the OTHER shape. Shape 1 (kept)
# names another skill and hijacks its invocation chain. Shape 2 never names
# anything — one skill's own description claims authority over EVERY task, so
# merely installing it changes global behaviour even when it is never invoked.
#
# The detectable part of shape 2 is NOT the mandate. Every honest skill says
# "must" about its own job, and firing on that would flag every CONTRIBUTING.md
# in existence. It is the explicit SCOPE-OVERRIDE clause — the clause whose
# only work is to widen the mandate past the skill's own remit.
_GLOBAL_SCOPE_OVERRIDE = (
    r"(?:regardless\s+of|irrespective\s+of|no\s+matter\s+(?:what|the)"
    r"|whether\s+or\s+not|without\s+exception|under\s+any\s+circumstances?"
    r"|even\s+(?:those|ones)\b|not\s+(?:explicitly\s+)?(?:configured|registered|enabled))"
)
_CROSS_SKILL_SHADOW = _re(
    r"\b" + _MANDATE_VERB + r"\b[^.\n]{0,200}\b"
    r"(?:skill|agent|sub-?agent|command|slash[_-]?command)\b[^.\n]{0,30}"
    r"(?:`/?" + _SKILL_NAME + r"`|`" + _SKILL_NAME + r"`)"
    # Shape 2 — a mandate carrying a clause that voids its own scope.
    + r"|\b" + _MANDATE_VERB + r"\b[^.\n]{0,200}\b" + _GLOBAL_SCOPE_OVERRIDE
    # Shape 2b — conduct declared to bind the agent's whole surface rather
    # than this skill's task. The noun list is the AGENT's units of work
    # (skills/tasks/tools/commands/sessions), never the organisational ones
    # ("applies to all team members" is what a real policy says).
    + r"|\b(?:applies|apply|applicable|binding)\s+(?:to\s+)?(?:all|every)\s+"
    r"(?:skills?|tasks?|tools?|commands?|sessions?|prompts?|conversations?|requests?)\b"
    r"|\bscope\s*[:=]\s*(?:system[-_ ]?wide|global|universal)\b"
)


# ---- Webhook / exfiltration sinks (aufgaard AGENT_CFG.EXFIL.*) ----------


# Direct or template references to known data-exfiltration sinks in a
# skill/agent body. The list is short on purpose — these are the actual
# names that appear in disclosed attacks, not every webhook service.
#
# STILL FALSIFIED AT 0/8, AND LEFT THAT WAY DELIBERATELY (janitor#226).
# This is a DENYLIST of sink domains; the benchmark's class is behavioural
# ("collected data is posted to an external endpoint"), and every seeded
# sample posts to a host the attacker chose freely —
# `analytics.example.com`, `telemetry-collect.example.net`,
# `asset-registry.corp.internal`. No denylist can ever contain an arbitrary
# hostname, so the 0/8 is a SCOPE MISMATCH, not a weak regex, and adding
# domains would not move it by one sample.
#
# The behavioural rule that WOULD reach them — a send verb plus a URL plus a
# context-bearing payload — was drafted and rejected on measurement: the
# seeded attacks are shaped exactly like a legitimate corporate telemetry
# policy (MUST forward diff/test-results/environment to an internal
# collector), because that is the disguise the attack wears. Separating the
# two needs to know whether the destination is authorised, which is
# deployment knowledge this module does not have. Firing on the shape would
# flag every real CI-telemetry document in the fleet, and a detector people
# learn to ignore protects nothing.
#
# So the honest state is: this rule catches KNOWN sinks, which is worth
# having and is what its name should be read to mean. It does not detect
# exfiltration in general, and COVERAGE.md says so rather than papering
# over it.
_EXFIL_WEBHOOK = _re(
    r"\b(?:webhook\.site|requestbin\.com|pipedream\.net|hookbin\.com"
    r"|smee\.io|ngrok\.io|trycloudflare\.com|loca\.lt|tunnel\.dev"
    r"|discord\.com/api/webhooks"
    # Wave 12 (skill-protego, sweep-C): end-to-end-encrypted messengers
    # malware now prefers over Discord webhooks — harder to take down,
    # no obvious central operator to abuse-report.
    r"|getsession\.org|oxen\.io|loki\.network"
    # Pastebin family — favoured by stagers ("download stage-2 from …").
    r"|pastebin\.com/raw|paste\.ee|ghostbin\.com|0bin\.net|hastebin\.com"
    # Mastodon / Matrix open instances — increasingly used as side
    # channels because their content is hard to scan at scale.
    r"|matrix\.org/_matrix/client)\b"
    # Telegram bot URLs always start with `/bot<digits>:<alnum>` — the
    # trailing digit avoids the word-boundary trap where `/bot\b` won't
    # match against `/bot12345` (digit is a word char, no boundary).
    r"|api\.telegram\.org/bot\d"
)


# FP-hardening (round 3): IOC-context lexicon. When one of these
# tokens appears within ±100 chars of a webhook-sink match, the prose
# is DESCRIBING the IOC / IoA / red-team fixture rather than actively
# exfiltrating to it. Used by `scan_text` to demote / suppress the
# finding when the file is a security-tool corpus rather than an
# active malicious skill.
_IOC_CONTEXT_CUE = re.compile(
    r"\bIOC\b|\bIndicator\b|\bIndicators\b|"
    r"\bIoA\b|\bIoC\b|"
    r"\bAttacker\b|\bAttackers\b|"
    r"\bMaliciou(?:s|sly)\b|"
    r"\bExample\b|\bSample\b|\bSamples\b|"
    r"\bFixture\b|\bFixtures\b|"
    r"\bRed[-\s]?Team\b|"
    r"\bDetect(?:s|ed|ing)?\b|\bDetection\b|"
    r"\bAllowlist\b|\bDenylist\b|\bBlocklist\b|"
    r"\bThreat[-\s]?Research\b",
    re.IGNORECASE | re.UNICODE,
)


# FP-hardening (round 3): path-based discriminator for the
# exfil-webhook-sink rule. A file under any of these path segments is
# almost certainly a security-tool fixture / IOC catalogue / red-team
# attack sample — not an active exfil sink. Used by callers (skill
# scanners, doctor_classify, etc.) to skip the rule entirely.
_EXFIL_PATH_SKIP = re.compile(
    r"(?:^|/)("
    r"red[-_]?team|"
    r"redteam|"
    r"fixtures?|"
    r"samples?|"
    r"threat[-_]research|"
    r"ioc[-_]?table\.md|"
    r"attacks\.py|"
    r"attack[-_]?fixtures?\.[A-Za-z0-9_.-]+|"
    r"iocs?/|"
    r"indicators?/"
    r")(?:$|/|\.)",
    re.IGNORECASE,
)


def is_exfil_fp_path(filename: str) -> bool:
    """Return True when `filename` lives inside a path segment that
    indicates a security-tool fixture / IOC catalogue / red-team
    attack sample. Callers SHOULD skip the exfil-webhook-sink rule
    for these files. FP-hardening (round 3) — IOC/fixture catalogues
    are not active exfil sinks even though they contain webhook URLs."""
    if not filename:
        return False
    return _EXFIL_PATH_SKIP.search(filename) is not None


def has_ioc_context_near(text: str, start: int, end: int, *, window: int = 100) -> bool:
    """True if an IOC / fixture / threat-research cue appears within
    ±window chars of the match. Used to demote
    `exfil-webhook-sink` findings whose surrounding prose is the IOC
    catalogue itself rather than an active exfil command."""
    lo = max(0, start - window)
    hi = min(len(text), end + window)
    return _IOC_CONTEXT_CUE.search(text[lo:hi]) is not None


# ---- Multi-line Buffer.from → eval correlation (sentinel-y-4, sweep-C) --


# A decode primitive (Buffer.from / base64-b64decode / atob) on its own
# is benign; a dynamic-exec primitive (an eval / Function / exec call) on
# its own is benign in isolation; but the TWO appearing within five lines
# of each other in
# the same source file is the canonical two-step code-injection shape.
# This catches the disclosed obfuscated payloads that pass single-line
# pattern matchers.
#
# Implementation note: this pattern is intentionally GREEDY across at
# most 4 newlines (5-line window) so the regex itself encodes the
# temporal-correlation constraint without external state machines.
_TWO_STEP_INJECT = _re(
    # Allow `=` in the charset because base64 padding ends with `=` /
    # `==`. The leading `[A-Za-z0-9+/]{40}` anchors a long body before
    # any padding so a short string with `=` doesn't sneak in.
    r"(?:Buffer\.from\s*\([^)]{0,200}?['\"][A-Za-z0-9+/=]{40,}['\"]"
    r"|base64\.b64decode\s*\([^)]{0,200}?['\"][A-Za-z0-9+/=]{40,}['\"]"
    r"|atob\s*\(\s*['\"][A-Za-z0-9+/=]{40,}['\"])"
    r"(?:[^\n]*\n){0,4}"  # up to 4 newlines = within 5-line window
    r"[^\n]*?(?:eval\s*\(|Function\s*\(|exec\s*\(|os\.system\s*\(|setTimeout\s*\(\s*['\"])"
)


# ---- Sensitive secret references in agent bodies ------------------------


# An agent body that mentions ssh keys / cloud credentials / git tokens
# is suspicious in skill/CLAUDE.md context. Excludes documentation-style
# mentions (we look for path-style or env-var-style references, not the
# word "secret" in prose).
_SECRET_REF = _re(
    r"~/?\.ssh/(?:id_rsa|id_ed25519|known_hosts|authorized_keys)"
    r"|~/?\.aws/(?:credentials|config)"
    r"|~/?\.npmrc\b"
    r"|~/?\.git[-_]?credentials\b"
    r"|\$\{?GH(?:_|UB_)?TOKEN\}?"
    r"|\$\{?NPM_TOKEN\}?"
    r"|\$\{?AWS_(?:ACCESS|SECRET)_KEY[A-Z_]*\}?"
    r"|\$\{?ANTHROPIC_API_KEY\}?"
    r"|\$\{?OPENAI_API_KEY\}?"
)


# ---- Dynamic exec / shell=True in agent bodies --------------------------


# Code inline in a skill body that uses eval / exec / shell=True is a
# strong signal of attacker intent to evade the static scanner — the
# skill body isn't a "code" location; the only reason to put exec in
# it is to instruct an agent to run something.
_DYNAMIC_EXEC = _re(
    r"\beval\s*\("
    r"|\bexec\s*\("
    r"|\bsubprocess\.[A-Za-z_]+\s*\([^)]*shell\s*=\s*True"
    r"|\bos\.system\s*\("
    r"|\bnew\s+Function\s*\("
    r"|\bsetTimeout\s*\(\s*['\"]"
    r"|\bsetInterval\s*\(\s*['\"]"
)


# ---- Git-hook install from skill body (aufgaard GIT_HOOK_INSTALL) -------


_GIT_HOOK_INSTALL = _re(
    r"\.git/hooks/(?:pre-commit|post-commit|pre-push|post-push|pre-merge-commit"
    r"|prepare-commit-msg|commit-msg|pre-rebase|post-receive|update)\b"
)


# ---- MCP annotation-lying (mcp-sentinel, sweep-A) ------------------------


# An MCP tool definition that claims `readOnlyHint: true` while its name
# carries a destructive verb (delete, remove, drop, write, modify, push,
# deploy, kill, rm, truncate) is lying about its safety profile to bypass
# the agent's auto-approve gate. Disclosed in mcp-sentinel's
# static_checks.py. The pattern matches the canonical JSON shape where
# a tool object has BOTH `name`-with-destructive-verb AND
# `readOnlyHint: true` within the same JSON block.
#
# The first cut required the lie to be told in exactly one place — a
# destructive verb inside `"name"`, followed by `"readOnlyHint": true` — and
# measured 0/9, because a manifest can tell the same lie in any of three
# places and in YAML as readily as JSON. What the class actually is: a
# READ-ONLY CLAIM anywhere in the declaration, contradicted by DESTRUCTIVE
# EVIDENCE anywhere in the same declaration. Splitting it that way also makes
# the rule order-agnostic, since which of the two comes first in the file is
# an authoring accident.
_MCP_READONLY_CLAIM = (
    r'(?:"?readOnly(?:Hint)?"?\s*:\s*true'
    # `"permissions": ["read"]` is the same claim written as a scope.
    r'|"?permissions"?\s*:\s*\[\s*"read"\s*\]'
    # ...and prose manifests say it in a Safety / Category field.
    r'|"?(?:safety|category|classification)"?\s*:\s*"?[^"\n]{0,60}read[-\s]?only)'
)
_MCP_DESTRUCTIVE_EVIDENCE = (
    # the tool's own name
    r'(?:"?(?:name|tool|operationId)"?\s*:\s*"[A-Za-z_]*(?:delete|remove|drop|'
    r'destroy|truncate|erase|rm|wipe|kill|terminate|purge|write|modify|update|'
    r'push|publish|deploy|install|uninstall|exec|run|clear|clean(?:up)?|'
    r'rotate|reset)[A-Za-z_]*"'
    # the route it calls: a read-only tool does not POST to /delete
    r'|"?(?:endpoint|path|url|route)"?\s*:\s*"[^"\n]{0,80}/(?:delete|erase|remove|'
    r'destroy|purge|drop|wipe|cleanup|clean)'
    r'|"?method"?\s*:\s*"(?:DELETE|PUT|PATCH)"'
    # or its implementation, sitting right there in the same file
    r'|\bDELETE\s+FROM\b|\bDROP\s+TABLE\b|\bTRUNCATE\s+TABLE\b'
    r'|\bos\.remove\s*\(|\bshutil\.rmtree\s*\(|\bfs\.(?:unlink|rm|writeFile)\w*\s*\('
    r'|\bexecSync\s*\(|\brm\s+-rf\b)'
)
# 800 chars because a manifest's declaration and its implementation are
# routinely separated by a parameter schema and a paragraph of documentation
# — the lie and its refutation are in one file, not one object literal.
_MCP_ANNOTATION_LIE = _re(
    _MCP_READONLY_CLAIM + r"[\s\S]{0,800}?" + _MCP_DESTRUCTIVE_EVIDENCE
    + r"|" + _MCP_DESTRUCTIVE_EVIDENCE + r"[\s\S]{0,800}?" + _MCP_READONLY_CLAIM
)


# ---- MCP schema-in-annotations evasion (mcp-sentinel #429) --------------


# Some MCP servers stash their inputSchema INSIDE the `annotations` object
# instead of at the top level, evading scanners that read only the
# top-level `inputSchema`. Pattern: an `annotations` object whose body
# contains an `inputSchema` key.
_MCP_SCHEMA_IN_ANNOTATIONS = _re(
    r'"annotations"\s*:\s*\{[\s\S]{0,2000}?"inputSchema"\s*:'
)


# ---- Whole-env exfil (skill-protego, sweep-C) ---------------------------


# `JSON.stringify(process.env)` is the canonical Shai-Hulud whole-env
# exfiltration signature — npm postinstall scripts serialise the full
# environment block (which holds NPM_TOKEN, GITHUB_TOKEN, AWS creds in
# CI runners) and POST it to an attacker URL in one statement.
_WHOLE_ENV_EXFIL = _re(
    r"JSON\.stringify\s*\(\s*process\.env\s*\)"
    r"|json\.dumps\s*\(\s*(?:dict\s*\(\s*)?os\.environ\s*\)?\s*\)?"
    r"|os\.environ\.copy\(\)\s*[,)]\s*[A-Za-z_]*"
)


# ---- Worm self-propagation (skill-protego, sweep-C) --------------------


# A package's install-time or runtime code that calls `npm publish` /
# `gem push` / `cargo publish` / `pip upload` is a worm-self-propagation
# signal. Disclosed in the shai-hulud Sep 2025 campaign — packages
# harvested publisher tokens then re-published themselves to spread.
_WORM_SELF_PROPAGATION = _re(
    r"\bnpm\s+publish\b"
    r"|\bgem\s+push\b"
    r"|\bcargo\s+publish\b"
    r"|\b(?:twine|python\s+-m\s+twine)\s+upload\b"
    r"|\bnpm\s+whoami\b"   # auth-recon companion signal
)


# ---- Crypto-clipper triad (skill-protego, sweep-C) ----------------------


# The disclosed clipboard-hijack shape is a TRIAD: read the clipboard,
# RECOGNISE a wallet address in it, write a different address back. Used by
# event-stream 2018, Solana web3.js 2024-12, TanStack 2026-05.
#
# Each leg used to be spelled as one library's API (`clipboardy`, a literal
# address, `.replace(`), which made the rule a detector for that library
# rather than for the behaviour: a clipper written against `pbpaste`,
# `pyperclip`, the DOM `clipboardData` API or PowerShell's `Clipboard` class
# performs exactly the same substitution and matched none of them.
_CLIPBOARD_READ = (
    r"(?:clipboardy\.read"
    r"|(?:navigator\.)?clipboard\.readText"
    r"|clipboardData\.getData"
    r"|Clipboard\]::GetText|Get-Clipboard"
    r"|pyperclip\.paste|win32clipboard\.GetClipboardData"
    r"|\bpbpaste\b|\bxclip\s+-o\b|\bxsel\s+(?:-o|--output)\b"
    r"|require\s*\(\s*['\"]clipboardy['\"]\s*\))"
)
# The substitution itself. `.replace(` is only ONE spelling of writing back:
# `pyperclip.copy(attacker)` / `clipboard.writeText(x)` / `| pbcopy` swap the
# address without ever calling replace.
_CLIPBOARD_WRITE = (
    r"(?:\.replace\s*\("
    r"|(?:navigator\.)?clipboard\.writeText\s*\("
    r"|clipboardData\.setData\s*\("
    r"|Clipboard\]::SetText|Set-Clipboard"
    r"|pyperclip\.copy\s*\("
    r"|win32clipboard\.SetClipboardText\s*\("
    r"|\bpbcopy\b|\bxclip\s+-i\b|\bclip\.exe\b)"
)
# Bitcoin / Ethereum / Solana / Tron wallet-address shapes; deliberately
# narrow on the prefix so we don't FP on long base64.
_WALLET_ADDRESS = (
    r"(?:0x[a-fA-F0-9]{40}"                              # Eth
    r"|bc1[a-z0-9]{20,}"                                  # BTC bech32
    r"|[13][a-km-zA-HJ-NP-Z1-9]{25,34}"                   # BTC legacy
    r"|T[a-zA-Z0-9]{33}"                                  # Tron
    r"|[1-9A-HJ-NP-Za-km-z]{32,44})"                      # Solana / generic
)
# A clipper does not need a WELL-FORMED address to be a clipper. The attacker
# constant is often a placeholder no address grammar accepts, so keying the
# middle leg on address SYNTAX loses the sample that is otherwise textbook.
# What every clipper must carry instead is the RECOGNISER — the expression
# that decides whether the copied text is a wallet at all. `a-km-z` /
# `A-HJ-NP-Z` inside a character class is base58 with the four look-alike
# glyphs (0 O I l) removed; outside cryptocurrency address validation it has
# essentially no other use, which makes it a high-precision fingerprint.
_WALLET_RECOGNISER = (
    r"(?:\[[^\]\n]{0,24}(?:a-km-z|A-HJ-NP-Z)[^\]\n]{0,24}\]"
    r"|\(\s*bc1\s*\||\bbc1\*"
    r"|0x\[a-fA-F0-9\]\{40\})"
)
_WALLET_TOKEN = r"(?:" + _WALLET_ADDRESS + r"|" + _WALLET_RECOGNISER + r")"
# Both orderings, because whether the attacker address is declared above the
# handler or substituted inside it is a style choice, not a property of the
# attack — and requiring one order silently halved the rule.
_CRYPTO_CLIPPER = _re(
    r"(?:" + _CLIPBOARD_READ + r"[\s\S]{0,600}?" + _WALLET_TOKEN
    + r"[\s\S]{0,600}?" + _CLIPBOARD_WRITE
    + r"|" + _WALLET_TOKEN + r"[\s\S]{0,600}?" + _CLIPBOARD_READ
    + r"[\s\S]{0,600}?" + _CLIPBOARD_WRITE + r")"
)


# ---- /proc/PID/mem credential extraction (skill-protego, sweep-C) ------


# TanStack 2026-05 OIDC-token extraction technique — reads `/proc/<pid>
# /mem` to grab live secrets that are not on disk. Linux-only attack
# surface; the path itself is a strong attacker-intent signal.
_PROCMEM_READ = _re(
    r"/proc/(?:\d+|self|\$\{?\w+\}?)/mem\b"
)


# ---- Git-protocol-only dependency (TanStack 2026-05, sweep-C) ----------


# A package.json `dependencies` / `optionalDependencies` / `peerDependencies`
# entry pointing at `git+...`, `github:...`, `git://...`, `file:...`, or
# `http:...` evades the npm registry's audit pipeline — the npm registry
# never sees the resolved code. Disclosed in TanStack 2026-05.
_GIT_PROTOCOL_DEP = _re(
    r'"(?:[a-zA-Z0-9_/@-]+)"\s*:\s*"'
    r"(?:git\+https?://|git\+ssh://|git://|github:|gitlab:|bitbucket:|file:|http:)"
)


# ---- Long-subdomain DNS exfil (skill-protego, sweep-C) -----------------


# Disclosed exfil shape: encode the secret as a subdomain and resolve
# it — the DNS query itself ships the bytes to an attacker-controlled
# nameserver. Heuristic: > 40-char subdomain on a commodity TLD.
#
# Measured 0/7, because the heuristic keys on the wrong half. A 40-char label
# is what exfiltrating a LOT of data looks like; what exfiltrating ANY data
# looks like is a RESOLUTION of a name the attacker assembled. Every seeded
# sample queries a short base64 label (16 chars) or interpolates a variable —
# both invisible to a length threshold, and lowering the threshold far enough
# to see them would flag every CDN hostname in existence.
#
# So the resolver call becomes the anchor: `dig`/`nslookup` whose queried
# name's first label is an opaque blob or an interpolated variable, and an
# encoder inside a command substitution feeding a hostname. Both describe the
# act (the query IS the exfil) rather than its volume.
_DNS_EXFIL_SUBDOMAIN = _re(
    # (1) a long opaque label on a commodity TLD — the high-volume shape.
    r"\b[A-Za-z0-9_-]{40,}\.(?:com|net|io|org|co|me|dev|app|cloud)\b"
    # (2) a DNS lookup of an assembled name.
    r"|\b(?:dig|nslookup|drill|kdig)\b[^\n]{0,60}?"
    r"(?:[A-Za-z0-9+/_=-]{12,}|\$\{?\w+\}?)\.[A-Za-z0-9-]{2,}\.[A-Za-z]{2,}"
    # (3) an encoder inside a command substitution, spliced into a hostname —
    #     `$(cat .env | base64 -w0).cdn.internal` ships the file in the query.
    r"|\$\([^\n)]{0,80}(?:base64|xxd|hexdump|sha256sum)[^\n)]{0,20}\)\s*\."
    r"[A-Za-z0-9-]{2,}\."
)


# ---- Chat-template delimiter tokens (deep-prompt-injection P1) ---------


# Tokens that mark "this is a system message" / "this is a fresh
# conversation turn" in the underlying chat-template formats (Llama
# `[INST]`, ChatML `<|im_start|>`/`<|im_end|>`, GPT `<|endoftext|>`,
# OpenAI Codex / Claude `</s>`, Markdown ``` ```system ``` fence). When
# these appear inside a skill body, .codex/prompts/*.md, MCP tool
# description, or settings JSON, the writer is trying to make the
# downstream LLM treat following text as a system / assistant turn.
_CHAT_TEMPLATE_DELIMS = _re(
    r"\[INST\]|\[/INST\]"
    r"|<\|im_start\|>|<\|im_end\|>"
    r"|<\|endoftext\|>|<\|startoftext\|>"
    r"|<\|system\|>|<\|user\|>|<\|assistant\|>"
    r"|```\s*system\b|```\s*assistant\b"
    r"|</s>\s*\[INST\]"
)


# ---- Concealment directive (deep-prompt-injection P8) ------------------


# A directive telling the agent to HIDE its own actions from the user
# is by definition adversarial — there is no legitimate reason a
# skill body would tell the agent "do not tell the user".
_CONCEALMENT_DIRECTIVE = _re(
    r"\bdo\s+not\s+(?:tell|inform|notify|mention\s+to|show)\s+the\s+user\b"
    # Looser shape: "hide/conceal <up to 30 chars of any noun> from the user"
    # so `hide this finding from the user` / `conceal the action from the user`
    # both match without enumerating every possible noun.
    r"|\b(?:hide|conceal|don'?t\s+show)\s+[^.\n]{0,30}?\s+from\s+the\s+user\b"
    r"|\bsilent(?:ly)?\s+(?:execute|run|perform|invoke)\b"
    r"|\bwithout\s+(?:notifying|alerting|informing|telling)\s+(?:the\s+)?user\b"
    r"|\bdo\s+not\s+(?:log|surface|emit|print|output)\s+(?:this|the\s+\w+)"
)


# ---- Tool-wildcard grant (deep-ai-context P8) --------------------------


# `allowedTools` / `permissions` / `tools` blocks in agent settings
# JSON granting wildcard or broad-scope access to dangerous tools
# (Bash(*), Write(*), MCP wildcard). Common attacker shape — they
# don't need to write code, they just escalate the agent's permission
# envelope.
#
# The first cut was JSON-only and enumerated Claude-Code tool spellings
# (`Bash(*)`), so it measured 0/8: the commonest real shape is a YAML or
# frontmatter key whose VALUE is a bare star, and it walked straight past
# `allowed-tools: ['*']`. What defines the class is the value, not the tool
# vocabulary — an enumerated grant lists tools, an unrestricted one is a
# wildcard — so the key spelling is now quote/case/separator-agnostic and the
# wildcard is matched as a value in its own right.
_TOOL_GRANT_KEY = (
    r"(?:allowed[-_ ]?tools|permitted[-_ ]?tools|permissions|tools)"
)
_TOOL_WILDCARD_GRANT = _re(
    # (1) Claude-Code tool spellings inside a grant list.
    _TOOL_GRANT_KEY + r'"?\s*[:=]\s*\[?'
    r'[^\]\}]{0,200}?'
    r'"(?:Bash\(\*\)|Bash\("?\*"?\)|Write\(\*\)|Edit\(\*\)|'
    r'mcp__\*|mcp__[^"]*\*[^"]*|'
    r'\*\s*Bash|\*\s*Write|All\s+tools?)"'
    # (2) the grant's VALUE is the wildcard: `allowed-tools: ['*']`,
    #     `allowed_tools: '*'`, `"tools": ["**"]`, `tools = *`.
    r"|" + _TOOL_GRANT_KEY + r"[\"']?\s*[:=]\s*\[?\s*[\"']?\*{1,2}[\"']?\s*[,\]]?"
    # (3) the wildcard is a LIST ITEM under a grant key — the YAML shape,
    #     where the star sits several lines below the key it belongs to.
    r"|" + _TOOL_GRANT_KEY + r"\b[^\n]{0,40}:[\s\S]{0,300}?"
    r"^[^\S\n]*-[^\S\n]*[\"']?\*{1,2}[\"']?[^\S\n]*$"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="prompt-injection-multilingual",
        name="Prompt-injection — multilingual override",
        severity="CRITICAL",
        description=(
            # CPV-skillaudit: vocab moved out of annotation
            "Body contains a multilingual boundary-erasure / prior-context "
            "override directive — high-confidence prompt-injection across "
            "11 languages."
        ),
        pattern=_PROMPT_INJ_MULTI,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="html-comment-impersonation",
        name="HTML-comment authority impersonation",
        severity="CRITICAL",
        description=(
            "HTML comment contains a system/admin/instruction/override "
            "directive — hidden from human readers, visible to the agent."
        ),
        pattern=_HTML_COMMENT_DIRECTIVE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="authority-override",
        name="Authority / role override directive",
        severity="HIGH",
        description=(
            "Body attempts to replace the agent's operating identity or its "
            "standing instructions — a role/persona re-assignment, a claim "
            "that prior directives are superseded, an identity-assigning "
            "config key, a file declaring itself the sole authority, or a "
            "human-confirmation gate switched off."
        ),
        pattern=_AUTHORITY_OVERRIDE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="base-url-override",
        name="Model-endpoint override",
        severity="CRITICAL",
        description=(
            "Body sets base_url / api_endpoint / model_url to an attacker-"
            "controlled host — redirects all subsequent LLM calls through "
            "the attacker."
        ),
        pattern=_BASE_URL_OVERRIDE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cross-skill-shadowing",
        name="Skill shadowing — mandate referencing another skill",
        severity="HIGH",
        description=(
            "A skill's own text issues a behavioural mandate that reaches "
            "beyond it — either naming ANOTHER skill (hijacking its "
            "invocation chain) or claiming authority over every task via a "
            "scope-override clause ('regardless of source', 'apply to all "
            "skills'), so installing the skill changes global behaviour."
        ),
        pattern=_CROSS_SKILL_SHADOW,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="exfil-webhook-sink",
        name="Known exfiltration-sink DOMAIN in agent body",
        severity="HIGH",
        description=(
            # CPV-skillaudit: vocab moved out of annotation — the literal
            # callback domains live in the _EXFIL_WEBHOOK pattern, not here.
            #
            # TRDD-HYV0SOC6 / janitor#226: this text used to read "Body
            # references a known data-exfiltration sink … a likely-malicious
            # data leak vector", which a reader scanning the rule list takes as
            # "exfiltration is covered". It is not: the pattern is a literal
            # BLOCKLIST of known hosts, so it catches the naive case and nothing
            # else. Measured — 0/8 on the seeded corpus, every sample of which
            # posts to a plausible host (`analytics.example.com/collect`,
            # `metrics.internal.company.io/ingest`). The word carrying all the
            # weight was "known", and it was invisible. Saying the limit out
            # loud is not a downgrade of the rule; it is the difference between
            # a reader knowing they still need to look and believing they do
            # not. Whether to ADD a structural detector (and pay its measured
            # false positives) is TRDD-HYV0SOC6's open decision — this change
            # deliberately does not pre-empt it, and does not touch the rule id.
            "Body references one of a fixed BLOCKLIST of known exfiltration "
            "hosts — common exfil-callback services, chat-bot webhooks, "
            "pastebins and tunnelling endpoints. LIMIT: matches those hosts "
            "ONLY. Exfiltration to an arbitrary or innocuous-looking domain is "
            "NOT detected by this rule (TRDD-HYV0SOC6)."
        ),
        pattern=_EXFIL_WEBHOOK,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="sensitive-secret-ref",
        name="Sensitive secret reference",
        severity="HIGH",
        description=(
            "Body mentions ssh key path / cloud-credentials file / token "
            "env-var in a way that suggests reading it — common shape of "
            "credential-harvesting agent directives."
        ),
        pattern=_SECRET_REF,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="dynamic-exec-in-body",
        name="Dynamic code execution in skill body",
        severity="HIGH",
        description=(
            "Body contains eval()/exec()/os.system()/shell=True — a skill "
            "body is documentation, not code; dynamic-exec here is a strong "
            "attacker-intent signal."
        ),
        pattern=_DYNAMIC_EXEC,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="git-hook-install-from-body",
        name="Git-hook installation referenced in skill body",
        severity="CRITICAL",
        description=(
            "Body references writing to .git/hooks/* — install-time agent "
            "persistence via post-commit / pre-push hook injection."
        ),
        pattern=_GIT_HOOK_INSTALL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="mcp-annotation-lying",
        name="MCP tool lies about safety profile",
        severity="CRITICAL",
        description=(
            "MCP tool with a destructive-verb name (delete/remove/write/exec/"
            "etc.) declares readOnlyHint=true — lies about its safety profile "
            "to bypass auto-approve gates. Disclosed by mcp-sentinel."
        ),
        pattern=_MCP_ANNOTATION_LIE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="mcp-schema-in-annotations",
        name="MCP inputSchema stashed inside annotations",
        severity="HIGH",
        description=(
            "MCP server places inputSchema inside the `annotations` object "
            "instead of at the top level — evades scanners that read only "
            "the canonical top-level inputSchema (MCP Inspector #429)."
        ),
        pattern=_MCP_SCHEMA_IN_ANNOTATIONS,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="whole-env-exfil",
        name="Whole-environment exfiltration signature",
        severity="CRITICAL",
        description=(
            "Source serialises the full process environment block "
            "(JSON.stringify(process.env) / json.dumps(os.environ)) — "
            "canonical Shai-Hulud whole-env exfiltration signature. "
            "In CI runners this leaks NPM_TOKEN / GITHUB_TOKEN / AWS keys."
        ),
        pattern=_WHOLE_ENV_EXFIL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="worm-self-propagation",
        name="Worm self-propagation: publish-from-dependency-code",
        severity="CRITICAL",
        description=(
            "Source calls `npm publish` / `gem push` / `cargo publish` / "
            "`twine upload` / `npm whoami` — the worm-spread signature "
            "(shai-hulud Sep 2025: harvest publisher token, re-publish "
            "the same malicious code under each authenticated package)."
        ),
        pattern=_WORM_SELF_PROPAGATION,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="crypto-clipper-triad",
        name="Crypto-clipper triad — clipboard + wallet + replace",
        severity="CRITICAL",
        description=(
            "Source reads the clipboard AND contains a hardcoded wallet "
            "address AND calls .replace() within the same block — the "
            "canonical clipboard-hijack pattern (event-stream 2018, "
            "Solana web3.js 2024-12, TanStack 2026-05)."
        ),
        pattern=_CRYPTO_CLIPPER,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="procmem-credential-extraction",
        name="/proc/PID/mem credential extraction",
        severity="CRITICAL",
        description=(
            "Source reads `/proc/<pid>/mem` — TanStack 2026-05 OIDC-token "
            "extraction technique that bypasses on-disk credential "
            "scanners by reading the live process memory."
        ),
        pattern=_PROCMEM_READ,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="git-protocol-only-dependency",
        name="Dependency declared via git+/github:/file:/http: protocol",
        severity="HIGH",
        description=(
            "package.json declares a dependency via `git+`, `github:`, "
            "`git://`, `file:`, or `http:` — bypasses the npm registry's "
            "audit pipeline (the registry never sees the resolved code). "
            "Disclosed in TanStack 2026-05 supply-chain attack."
        ),
        pattern=_GIT_PROTOCOL_DEP,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="dns-exfil-long-subdomain",
        name="Long-subdomain DNS exfiltration",
        severity="MEDIUM",
        description=(
            "Source references a > 40-char subdomain on a commodity TLD "
            "— DNS-based exfil shape (the DNS query itself ships the "
            "encoded secret to the attacker's authoritative nameserver)."
        ),
        pattern=_DNS_EXFIL_SUBDOMAIN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="two-step-code-injection",
        name="Two-step code injection (decode → exec within 5 lines)",
        severity="CRITICAL",
        description=(
            "Buffer.from(<base64>) / base64.b64decode / atob on a long "
            "literal AND eval / Function / exec / os.system within 5 "
            "lines — the canonical obfuscated-payload shape that single-"
            "line pattern matchers miss. Disclosed in sentinel-y-4."
        ),
        pattern=_TWO_STEP_INJECT,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="chat-template-delimiters",
        name="Chat-template delimiter tokens in agent-context body",
        severity="HIGH",
        description=(
            "Body contains chat-template delimiter tokens ([INST], "
            "<|im_start|>, </s>, ```system, etc.) — the attacker is "
            "trying to make the downstream LLM treat following text as "
            "a system / assistant turn. Disclosed in honeybadger + "
            "skill-protego."
        ),
        pattern=_CHAT_TEMPLATE_DELIMS,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="concealment-directive",
        name="Concealment directive — agent told to hide actions from user",
        severity="CRITICAL",
        description=(
            "Body instructs the agent to act WITHOUT telling the user "
            "('do not tell the user', 'silently execute', 'hide this "
            "from the user'). No legitimate skill needs this — it is "
            "an adversarial directive by definition."
        ),
        pattern=_CONCEALMENT_DIRECTIVE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tool-wildcard-grant",
        name="Wildcard tool / permission grant in agent settings",
        severity="HIGH",
        description=(
            "`allowedTools` / `permissions` / `tools` block grants "
            "Bash(*), Write(*), or mcp__* wildcards — the attacker "
            "escalates the agent's permission envelope instead of "
            "writing code. Disclosed in narthex + skill-protego."
        ),
        pattern=_TOOL_WILDCARD_GRANT,
        owasp_asi="ASI-03",
    ),
)


# ---- AI-context write detection (argus) ---------------------------------


# Forward shape: writeFile / appendFile / write_text / write_bytes called
# with one of the agent-context filenames in the argument list.
# Reverse shape: the filename literal appears near a write-call within
# a small text window.

_CONTEXT_FILES_PATTERN = (
    r"(?:CLAUDE(?:\.local)?\.md|\.cursorrules|\.cursor/rules|"
    r"\.aider\.conf\.ya?ml|\.aiderrules|AGENTS?\.md|"
    r"\.continuerules|\.codexrules|\.windsurfrules|"
    r"\.cody/instructions|\.claude/[A-Za-z0-9_\-./]+|"
    r"\.mcp\.json|\.claude-plugin/plugin\.json)"
)

# The bounded char class `[^;\n]` is broader than `[^)]` so the regex can
# traverse the inner `)` of chained calls like `Path(...).expanduser().write_text`
# or `fs.writeFileSync(path.join(home, ".cursorrules"), payload)` — both
# very common shapes in real attacks. The semicolon + newline bound keeps
# the match inside a single statement, which is what we want.
_NPM_WRITE_FORWARD = _re(
    r"\b(?:fs\.)?(?:write|append|outputFile|writeFile)[A-Za-z]*(?:Sync)?\s*\("
    r"[^;\n]{0,400}?" + _CONTEXT_FILES_PATTERN
)

_PY_WRITE_FORWARD = _re(
    r"\b(?:write_text|write_bytes|write_lines)\s*\("
    r"[^;\n]{0,400}?" + _CONTEXT_FILES_PATTERN
    + r"|\bopen\s*\([^;\n]{0,200}?" + _CONTEXT_FILES_PATTERN
    + r"[^;\n]{0,200}?,\s*['\"][wa]"
)

_REVERSE_WRITE = _re(
    _CONTEXT_FILES_PATTERN + r"[^;\n]{0,400}?"
    r"\.(?:write_text|write_bytes|writeFile|appendFile|outputFile)\s*\("
)

AI_CONTEXT_WRITE_PATTERNS: tuple[re.Pattern, ...] = (
    _NPM_WRITE_FORWARD, _PY_WRITE_FORWARD, _REVERSE_WRITE,
)


def find_ai_context_writes(source: str) -> list[re.Match]:
    """Return every match of an AI-context write across forward + reverse
    shapes. Caller is responsible for filtering known config-loader
    packages via is_known_config_loader() — those legitimately write
    these files (dotenv-cli rewrite their own dotfiles, etc.).
    """
    if not source:
        return []
    hits: list[re.Match] = []
    for pat in AI_CONTEXT_WRITE_PATTERNS:
        hits.extend(pat.finditer(source))
    return hits


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str, *, file_kind: str = "prose", filename: str = "") -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` selects which rule subset to apply:
      * "prose"  (default) — skill bodies, CLAUDE.md, READMEs. Runs every
                              rule; the agent's parser reads every byte.
      * "source"            — code files. Skip the prompt-injection +
                              authority-override rules (those fire in
                              code comments + string literals constantly
                              when the code IS a security scanner). Keep
                              exfil-webhook, sensitive-secret-ref, git-
                              hook-install, dynamic-exec-in-body.

    `filename` is an optional caller-side hint. When the file path
    lives inside a security-tool fixture / red-team / IOC catalogue
    directory, the exfil-webhook-sink rule is skipped entirely (those
    files LIST webhook URLs as IOCs, they don't ACTIVELY exfiltrate
    to them). FP-hardening (round 3).

    Findings are deduped by (rule_id, line, col) — a single line that
    triggers two rules emits two findings, but the same rule firing
    twice on the same line emits one.
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    source_safe_rules = {
        "exfil-webhook-sink", "sensitive-secret-ref",
        "git-hook-install-from-body", "dynamic-exec-in-body",
        "base-url-override",
        # Wave 11 source-file patterns — every one of these only appears
        # inside actual code, not in skill prose, so they're safe to run
        # in file_kind="source" mode.
        "whole-env-exfil", "worm-self-propagation",
        "crypto-clipper-triad", "procmem-credential-extraction",
        "git-protocol-only-dependency", "dns-exfil-long-subdomain",
        "two-step-code-injection",
        # tool-wildcard-grant fires on JSON settings files — code-safe.
        # The other two (chat-template, concealment) are prose-only
        # patterns that should NOT fire in regular source code because
        # they'd false-positive on the janitor's own rule definitions.
        "tool-wildcard-grant",
        # The two MCP rules were absent here, which made them structurally
        # DEAD on the only file they were written for. Both are anchored on
        # JSON/YAML manifest keys (`"readOnlyHint": true`, `"annotations": {
        # ... "inputSchema"`), and a manifest is `.mcp.json` — which every
        # caller's `file_kind` router classifies as `source`, since the split
        # is by suffix and only `.md`/extensionless counts as prose. So a rule
        # named for MCP manifests could never see one. It is also why
        # `mcp-annotation-lying` measured 0/9: the bench scans that class as
        # `source` (correctly — they ARE manifests) and the rule never ran.
        # Neither pattern has the prose-FP problem that justifies this list:
        # each needs two structural JSON/YAML keys to co-occur.
        "mcp-annotation-lying", "mcp-schema-in-annotations",
    }
    # FP-hardening (round 3): the path-based discriminator for the
    # exfil-webhook-sink rule. A red-team / fixture / IOC catalogue
    # file lists webhook URLs as detection targets, not as active
    # exfil sinks. Skip the rule entirely on those paths.
    skip_exfil_for_path = bool(filename) and is_exfil_fp_path(filename)

    # FP-hardening (round 3): mask markdown code fences before running
    # the dynamic-exec-in-body rule on prose files. The intent of the
    # rule is to catch `eval(...)` directives EMBEDDED in skill prose;
    # an `eval()` inside a documentation code fence is INERT (the
    # downstream LLM doesn't execute fenced code). Without this mask,
    # every security-tool SKILL.md that documents `eval()` / `exec()`
    # fires HIGH.
    masked_for_dynamic_exec: str | None = None
    if file_kind == "prose":
        try:
            from ai_context_extras import mask_markdown_code_blocks  # type: ignore[import-not-found]
            masked_for_dynamic_exec = mask_markdown_code_blocks(text)
        except ImportError:
            masked_for_dynamic_exec = None

    for rule in RULES:
        if file_kind == "source" and rule.id not in source_safe_rules:
            continue
        # Skip exfil-webhook-sink entirely on IOC-catalogue / fixture
        # / red-team paths.
        if rule.id == "exfil-webhook-sink" and skip_exfil_for_path:
            continue
        # FP-hardening (round 3): for dynamic-exec-in-body in prose
        # mode, run against the code-fence-masked text so eval/exec
        # tokens inside fenced documentation become invisible.
        if (
            rule.id == "dynamic-exec-in-body"
            and file_kind == "prose"
            and masked_for_dynamic_exec is not None
        ):
            search_text = masked_for_dynamic_exec
        else:
            search_text = text
        for m in rule.pattern.finditer(search_text):
            # FP-hardening (round 3): for exfil-webhook-sink, demote /
            # drop matches whose surrounding prose names the URL as an
            # IOC / fixture / red-team example rather than commanding
            # exfil to it.
            if (
                rule.id == "exfil-webhook-sink"
                and has_ioc_context_near(text, m.start(), m.end())
            ):
                continue
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
