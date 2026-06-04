"""AI/LLM agent-runtime architecture anti-patterns (wave 26, distill-round-12).

Catalogue distilled in
`reports/distill-round-12/ai-agent-runtime.md`. The angle is **agent
runtime architecture** — bounded loops, gateway confused-deputy,
sub-agent dispatch trust, tool-registry hygiene, persistence policy,
shared LLM credentials, supply-chain drift of tool definitions.

The angle deliberately EXCLUDES:

  * Prompt-text injection / template-build taint — already shipped by
    `prompt_injection_patterns.py` and `subagent_attack_patterns.py`.
  * RAG retrieval / vector-store contamination / embedding-rev
    pinning — already shipped by `rag_llm_patterns.py`.
  * Sub-agent prompt taint, role-mapping taint, skill-output rechain,
    permission-inheritance wildcard, multi-agent shared-state mixing
    — already shipped by `subagent_attack_patterns.py`.
  * Generic env-var-key leaks (Slack / Discord / Telegram bot tokens
    in client bundles) — already shipped by
    `chat_bot_patterns.py` and `credential_lifecycle_patterns.py`.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * agent-runtime-loop-unbounded-langchain                     (HIGH)
  * agent-runtime-loop-unbounded-langgraph                     (HIGH)
  * agent-runtime-loop-unbounded-autogen-crewai                (HIGH)
  * agent-runtime-gateway-master-key-confused-deputy           (CRITICAL)
  * agent-runtime-subagent-dispatch-no-provenance              (HIGH)
  * agent-runtime-tool-registry-last-write-wins                (HIGH)
  * agent-runtime-memory-unbounded-accumulator                 (MEDIUM)
  * agent-runtime-llm-client-module-level-multi-tenant         (HIGH)
  * agent-runtime-tool-list-no-integrity-fingerprint           (MEDIUM)

Public surface mirrors `chat_bot_patterns`:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping (from the report's cross-cutting notes):
  ASI-06 — Excessive Agency (loops, gateway deputy, sub-agent trust,
                              tool shadow, shared credential)
  ASI-10 — Unbounded Consumption (loops, persistence, shared credential)
  ASI-03 — Supply Chain (tool-name shadow, definition drift)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never
raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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
    chat_bot_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : agent-runtime-loop-unbounded-langchain ------------------------
#
# LangChain ReAct / AgentExecutor constructors without an explicit
# `max_iterations=` argument. Bounded `[^)]{0,400}` keeps RE2-safe.


_LANGCHAIN_AGENT_EXECUTOR_CTOR = _re(
    r"\bAgentExecutor\s*\(\s*[^)]{0,400}\)"
)

# Used by the Stage-B filter to suppress when max_iterations is present.
_LANGCHAIN_AGENT_EXECUTOR_HAS_CAP = _re(
    r"\bmax_iterations\s*="
)


# ---- R2 : agent-runtime-loop-unbounded-langgraph ------------------------
#
# LangGraph `.invoke(...)` / `.stream(...)` / `.astream(...)` calls that
# pass a `config={...}` argument WITHOUT `recursion_limit`. We anchor on
# the call+config-dict opener and Stage-B-check for the key in the
# enclosing call.


_LANGGRAPH_INVOKE_WITH_CONFIG = _re(
    r"\.(?:invoke|stream|astream|ainvoke)\s*\("
    r"[^)]{0,200}?config\s*=\s*\{[^}]{0,400}\}"
)

_LANGGRAPH_HAS_RECURSION_LIMIT = _re(
    r"\brecursion_limit\b"
)


# ---- R3 : agent-runtime-loop-unbounded-autogen-crewai -------------------
#
# AutoGen `initiate_chat(...)` without `max_consecutive_auto_reply=` and
# CrewAI `Agent(role=...)` without `max_iter=`. Both bounded by
# `[^)]{0,400}` to stay RE2-safe.


_AUTOGEN_INITIATE_CHAT = _re(
    r"\binitiate_chat\s*\(\s*[^)]{0,400}\)"
)

_AUTOGEN_HAS_REPLY_CAP = _re(
    r"\bmax_consecutive_auto_reply\s*="
)

_CREWAI_AGENT_CTOR = _re(
    r"\bAgent\s*\(\s*[^)]{0,400}\brole\s*=\s*[^)]{0,200}\)"
)

_CREWAI_HAS_ITER_CAP = _re(
    r"\bmax_iter\s*="
)


# ---- R4 : agent-runtime-gateway-master-key-confused-deputy --------------
#
# An LLM-gateway-style HTTP handler rewrites the outbound Authorization /
# x-api-key header to a process-env value, discarding caller identity.
# Anchored on the header-rewrite to a env-driven key. Stage-B requires a
# request-receiving function context (the file mentions `request:` or
# `Request` typing) in a 25-line window.


_GATEWAY_HEADER_REWRITE_FROM_ENV = _re(
    r"\bheaders\s*\[\s*['\"](?:Authorization|x-api-key)['\"]\s*\]"
    r"\s*=\s*[^#\n]{0,200}?os\.(?:getenv|environ)"
    r"|"
    # JS / TS variant — req.headers / req.set / fetch options
    r"\bheaders\s*\.\s*set\s*\(\s*['\"](?:Authorization|x-api-key)['\"]"
    r"\s*,\s*[^)]{0,200}?process\.env\."
    r"|"
    # JS object-literal header rewrite with process.env value
    r"['\"](?:Authorization|x-api-key)['\"]\s*:\s*"
    r"(?:`Bearer\s+\$\{process\.env\.|process\.env\.)"
)

# Request-receiving context indicator: a function whose signature accepts
# a Request / req / async route handler.
_GATEWAY_REQUEST_CONTEXT = _re(
    r"\b(?:async\s+def|def)\s+\w+\s*\([^)]*(?:request|req)\s*:"
    r"|"
    r"\@(?:app|router|api|fastapi_app)\.(?:get|post|put|delete|patch|api_route)\s*\("
    r"|"
    # JS / TS Express / Koa / Fastify route handlers
    r"\b(?:app|router|server|fastify)\.(?:get|post|put|delete|patch|use)\s*\("
    r"|"
    # Generic async handler taking (req|request) as first arg
    r"\b(?:async\s+)?function\s+\w+\s*\(\s*(?:req|request)\b"
)


# ---- R5 : agent-runtime-subagent-dispatch-no-provenance -----------------
#
# A LangGraph-style node function reads a dispatch field (`next_action`,
# `next_task`, `delegated_to`, `handoff`, `task`) from `state[...]` and
# routes downstream without a provenance / signed-by / origin check.
# This is the agent-to-agent confused-deputy.


_SUBAGENT_NODE_DEF = _re(
    r"\bdef\s+\w*(?:node|router|executor|dispatcher|planner)\w*\s*"
    r"\(\s*state\b[^)]{0,200}\)\s*"
    r"(?:->\s*[^:]{0,80})?\s*:"
)

_SUBAGENT_DISPATCH_FIELD_READ = _re(
    r"\bstate\s*\[\s*['\"]"
    r"(?:next_action|next_task|delegated_to|handoff|task|next_agent"
    r"|next_node|route_to|dispatch_to)"
    r"['\"]\s*\]"
)

_SUBAGENT_PROVENANCE_MARKER = _re(
    r"\b(?:signature|signed_by|origin|provenance|authored_by|caller_agent"
    r"|hmac|verify_origin|origin_token|caller_id|caller_token)\b"
)


# ---- R6 : agent-runtime-tool-registry-last-write-wins -------------------
#
# A tool-registry attribute (`self.tools[name] = fn` / `registry[name]`)
# is written without a prior `if name in ...` / `raise` / `assert`
# duplicate guard in the same method. We anchor on the write; Stage-B
# checks the 15-line backward window for the guard.


_TOOL_REGISTRY_WRITE = _re(
    r"\b(?:self|cls)\.(?:tools|tool_map|tool_registry|_tools|_tool_map"
    r"|_tool_to_server|_tool_to_handler|registry|tool_table)\s*"
    r"\[\s*[^\]]{0,80}\]\s*="
    r"|"
    # Stand-alone dict-by-name assignment in a registration helper
    r"\bregistry\s*\[\s*[^\]]{0,80}\]\s*="
)

_TOOL_REGISTRY_GUARD = _re(
    r"\bif\s+[^:\n]{0,120}\bin\s+(?:self\.tools|self\._tools|self\.tool_map"
    r"|self\.tool_registry|self\._tool_to_server|self\._tool_to_handler"
    r"|self\.registry|self\.tool_table|registry)\b"
    r"|"
    r"\b(?:raise|assert)\b[^:\n]{0,120}\b(?:duplicate|already|exists|conflict|collision)"
    r"|"
    r"\.(?:setdefault|get)\s*\("
)


# ---- R7 : agent-runtime-memory-unbounded-accumulator --------------------
#
# Three accumulator shapes that grow without bound:
#   a) LangGraph `Annotated[list, operator.add]`
#   b) LangChain `ConversationBufferMemory()` (no Window/Summary suffix)
#   c) Redis rpush / lpush in a `def append_*` style helper with no
#      LTRIM / EXPIRE in the same function (Stage-B window).


_MEMORY_LANGGRAPH_ANNOTATED = _re(
    r"\bAnnotated\s*\[\s*(?:list|List)\s*(?:\[[^\]]{0,80}\])?\s*,\s*"
    r"operator\.add\s*\]"
    r"|"
    # The `add_messages` reducer in MessagesState is also unbounded
    r"\bAnnotated\s*\[\s*(?:list|List)[^,]{0,80},\s*add_messages\s*\]"
)

_MEMORY_LANGCHAIN_BUFFER = _re(
    # ConversationBufferMemory but NOT ...WindowMemory / ...SummaryMemory.
    # The negative-tail uses a bounded character class, not a lookbehind.
    r"\bConversation(?:Buffer)Memory\s*\("
)

_MEMORY_REDIS_PUSH = _re(
    r"\b(?:r|redis_client|cache|conn)\.(?:rpush|lpush)\s*\("
)

_MEMORY_REDIS_BOUND = _re(
    r"\b(?:LTRIM|ltrim|EXPIRE|expire|expireat|EXPIREAT|set_ttl|setex)\b"
)


# ---- R8 : agent-runtime-llm-client-module-level-multi-tenant -----------
#
# Module-scope LLM-client instantiation reading an LLM-provider API key
# from the environment. Anchored to start-of-line so we don't match
# in-function constructions. Three shapes covered:
#   a) `_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))`
#   b) `_llm: ChatGroq | None = None` (lazy-singleton helper)
#   c) `openai.api_key = os.environ.get("OPENAI_API_KEY")`


_LLM_MODULE_SCOPE_CLIENT = _re(
    r"^_?\w+\s*=\s*(?:OpenAI|AsyncOpenAI|Anthropic|AsyncAnthropic"
    r"|ChatGroq|ChatOpenAI|ChatAnthropic|ChatVertexAI|ChatGoogleGenerativeAI"
    r"|GoogleGenerativeAI|Mistral|Cohere)\s*\("
    r"[^)\n]{0,300}\bapi_key\s*=\s*os\.(?:getenv|environ)"
)

_LLM_MODULE_SCOPE_SINGLETON = _re(
    r"^_(?:llm|client|openai_client|anthropic_client|groq_client"
    r"|chat_client|model_client)\s*:\s*[A-Za-z_][\w.]*"
    r"(?:\s*\|\s*None)?\s*=\s*None\s*$"
)

_LLM_MODULE_SCOPE_DOTTED = _re(
    r"^(?:openai|anthropic|groq|cohere|mistral)\.api_key\s*="
    r"\s*os\.(?:getenv|environ)"
)


# ---- R9 : agent-runtime-tool-list-no-integrity-fingerprint --------------
#
# A tool-source loader pulls definitions from a dynamic source (MCP
# `tools/list`, `importlib.metadata.entry_points`, `os.listdir` over a
# `tools/` directory) WITHOUT a hash / fingerprint / signature step in
# the same function. Stage-B window: 20-line window around the loader
# call.


_TOOL_SOURCE_DYNAMIC = _re(
    # MCP tools/list — one-shot remote fetch
    r"\b(?:await\s+)?[A-Za-z_][\w.]*\.send_request\s*\(\s*"
    r"['\"]tools/list['\"]"
    r"|"
    # importlib entry-points keyed by a tools group
    r"\bimportlib\.metadata\.entry_points\s*\([^)]{0,200}"
    r"\bgroup\s*=\s*['\"][^'\"]*tools?['\"]"
    r"|"
    # os.listdir over a tools directory
    r"\bos\.listdir\s*\(\s*['\"][^'\"]{0,200}tools?[^'\"]{0,200}['\"]\s*\)"
)

_TOOL_INTEGRITY_MARKER = _re(
    r"\bhashlib\.(?:sha256|sha384|sha512|blake2b|blake2s)\b"
    r"|"
    r"\b(?:fingerprint|signature|verify|integrity|checksum|manifest"
    r"|signed_by|signed_manifest|sigstore|cosign)\b"
)


# ---- Rule catalogue -----------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="agent-runtime-loop-unbounded-langchain",
        name="LangChain AgentExecutor / ReAct agent without max_iterations",
        severity="HIGH",
        description=(
            "A LangChain `AgentExecutor(...)` constructor call has no "
            "`max_iterations=` argument. The agent's tool-use loop has "
            "no upper bound — a poisoned tool description, adversarial "
            "user prompt, or sticky model can burn tokens indefinitely. "
            "At hosted-LLM rates a runaway loop costs the operator "
            "thousands of dollars before any monitor reacts. Always "
            "pass `max_iterations=` (default 15 is acceptable for most "
            "ReAct loops; lower it for cost-sensitive paths)."
        ),
        pattern=_LANGCHAIN_AGENT_EXECUTOR_CTOR,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="agent-runtime-loop-unbounded-langgraph",
        name="LangGraph .invoke/.stream config without recursion_limit",
        severity="HIGH",
        description=(
            "A LangGraph compiled-graph `.invoke(...)` / `.stream(...)` "
            "/ `.astream(...)` call passes a `config={...}` argument "
            "without `recursion_limit`. The default `recursion_limit` "
            "is 25, which may be safe for a fixed DAG but becomes a "
            "footgun the moment a conditional edge or self-loop is "
            "added. Always pass `recursion_limit` explicitly so the "
            "ceiling tracks the graph's actual shape."
        ),
        pattern=_LANGGRAPH_INVOKE_WITH_CONFIG,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="agent-runtime-loop-unbounded-autogen-crewai",
        name="AutoGen initiate_chat / CrewAI Agent without iteration cap",
        severity="HIGH",
        description=(
            "AutoGen `initiate_chat(...)` called without "
            "`max_consecutive_auto_reply=`, OR CrewAI `Agent(role=...)` "
            "constructor called without `max_iter=`. Same failure mode "
            "as the LangChain case: an unbounded tool-use / chat loop "
            "burns tokens until provider rate-limits kick in (denying "
            "service to other tenants) or the operator's bill spikes."
        ),
        pattern=_AUTOGEN_INITIATE_CHAT,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="agent-runtime-gateway-master-key-confused-deputy",
        name="LLM-gateway rewrites outbound Authorization/x-api-key from env",
        severity="CRITICAL",
        description=(
            "An HTTP handler that receives a `request` / `req` argument "
            "rewrites the outbound `Authorization` or `x-api-key` "
            "header to an `os.environ`-driven (Python) or "
            "`process.env`-driven (JS) value — the operator's master "
            "LLM API key. The inbound caller's identity is discarded "
            "and any HTTP client that reaches the gateway can issue "
            "calls billed to the operator's master account. Canonical "
            "confused-deputy in agent runtimes. Verify caller identity "
            "(JWT, mTLS, per-tenant bearer) BEFORE rewriting the "
            "outbound credential."
        ),
        pattern=_GATEWAY_HEADER_REWRITE_FROM_ENV,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="agent-runtime-subagent-dispatch-no-provenance",
        name="LangGraph node dispatches on state field with no provenance check",
        severity="HIGH",
        description=(
            "A node function (`*_node` / `*_router` / `*_executor` / "
            "`*_dispatcher` / `*_planner`) reads a dispatch field "
            "(`next_action`, `next_task`, `delegated_to`, `handoff`, "
            "`task`, `next_agent`, `next_node`, `route_to`, "
            "`dispatch_to`) from `state[...]` AND the same function "
            "contains no provenance / signed-by / origin / hmac / "
            "caller-id marker. Any agent in the graph — and any tool "
            "output that lands in the state — can forge a dispatch "
            "instruction; the dispatcher acts on it as if it came from "
            "the orchestrator. Distinct from "
            "`subagent_attack_patterns.subagent-prompt-attacker-tainted` "
            "(prompt-text taint) and "
            "`subagent_attack_patterns.role-mapping-from-untrusted-input` "
            "(role-selector taint) — this rule fires on the "
            "*dispatch-side* lack of caller-agent authentication."
        ),
        pattern=_SUBAGENT_NODE_DEF,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="agent-runtime-tool-registry-last-write-wins",
        name="Tool registry writes by name without duplicate guard",
        severity="HIGH",
        description=(
            "A tool-registry assignment of the shape "
            "`self.tools[name] = fn` / `self._tool_to_server[name] = "
            "server` (or any equivalent dict-keyed-by-tool-name write) "
            "happens with no prior `if name in self.tools` guard, no "
            "raise on collision, and no `.setdefault(...)` / `.get(...)` "
            "pattern. Two upstream sources can register tools with the "
            "same name; the last writer silently shadows the first. An "
            "attacker who controls one source impersonates a trusted "
            "tool (`bash`, `write_file`, `send_email`) — the model has "
            "no way to tell from the schema view."
        ),
        pattern=_TOOL_REGISTRY_WRITE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="agent-runtime-memory-unbounded-accumulator",
        name="Agent memory / scratchpad accumulator with no bound",
        severity="MEDIUM",
        description=(
            "An agent runtime accumulates state into one of three "
            "unbounded shapes: (a) LangGraph "
            "`Annotated[list, operator.add]` / `add_messages` reducer, "
            "(b) LangChain `ConversationBufferMemory()` (use "
            "`ConversationBufferWindowMemory(k=N)` or "
            "`ConversationSummaryMemory` instead), or (c) a Redis "
            "`rpush` / `lpush` helper with no `LTRIM` / `EXPIRE` in "
            "the same scope. Each call appends; the store grows "
            "without bound; later requests feed the entire history "
            "back into the model — token-DoS + persistent-injection "
            "vector + storage-exhaustion."
        ),
        pattern=_MEMORY_LANGGRAPH_ANNOTATED,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="agent-runtime-llm-client-module-level-multi-tenant",
        name="LLM client instantiated at module scope with env api_key",
        severity="HIGH",
        description=(
            "An LLM client (`OpenAI`, `AsyncOpenAI`, `Anthropic`, "
            "`ChatGroq`, `ChatOpenAI`, `ChatAnthropic`, `ChatVertexAI`, "
            "`ChatGoogleGenerativeAI`, etc.) is constructed at module "
            "scope with `api_key=os.environ.get(...)`, OR a module-level "
            "lazy-singleton helper holds the same shape "
            "(`_llm: ChatGroq | None = None`), OR a provider's global "
            "is assigned (`openai.api_key = os.environ.get(...)`). In a "
            "multi-tenant deployment every tenant bills the operator's "
            "master key; one tenant's runaway loop trips the rate limit "
            "for everyone. Construct the client per-request from a "
            "vault lookup keyed by tenant ID."
        ),
        pattern=_LLM_MODULE_SCOPE_CLIENT,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="agent-runtime-tool-list-no-integrity-fingerprint",
        name="Tool definitions loaded from dynamic source with no integrity check",
        severity="MEDIUM",
        description=(
            "Tool definitions are loaded from a dynamic source (MCP "
            "`tools/list` remote call, "
            "`importlib.metadata.entry_points(group='*.tools')` Python "
            "entry-point lookup, or `os.listdir('.../tools/')` "
            "filesystem scan) without a hash / fingerprint / signature "
            "/ manifest / checksum check in the same function. A "
            "previously-trusted tool's description text can drift to "
            "include a prompt-injection payload, or its JSON schema "
            "can grow a new required parameter the model dutifully "
            "fills — supply-chain compromise that survives across "
            "restarts and is invisible to log review."
        ),
        pattern=_TOOL_SOURCE_DYNAMIC,
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


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * R1 (loop-unbounded-langchain) — anchor on the AgentExecutor
        constructor; suppress if `max_iterations=` is present
        anywhere in the matched call expression.
      * R2 (loop-unbounded-langgraph) — anchor on the
        `.invoke(...)`/`.stream(...)` config dict; suppress if
        `recursion_limit` is present anywhere in the matched call
        expression.
      * R3 (loop-unbounded-autogen-crewai) — anchor on either
        `initiate_chat(...)` (suppress if `max_consecutive_auto_reply=`
        in the call) OR `Agent(role=..., ...)` (suppress if `max_iter=`
        in the call).
      * R4 (gateway-master-key-confused-deputy) — anchor on the
        header rewrite from env; require a request-handler context
        marker within 25 lines (suppress otherwise so the rule fires
        only on actual HTTP gateways, not on outbound LLM clients
        that legitimately set their own Authorization header).
      * R5 (subagent-dispatch-no-provenance) — anchor on a node
        function definition; require BOTH a dispatch-field read AND
        the ABSENCE of any provenance/origin/signature marker in the
        50-line function body window.
      * R6 (tool-registry-last-write-wins) — anchor on the write;
        require no guard / no setdefault / no exists-raise pattern in
        the 15-line backward window (the guard typically appears
        BEFORE the write).
      * R7 (memory-unbounded-accumulator) — three independent
        anchor patterns; the Redis-push variant requires NO
        LTRIM/EXPIRE marker in a 40-line window.
      * R8 (llm-client-module-level) — three anchor patterns
        (constructor at module scope, singleton helper, dotted
        global assignment); no Stage-B (the start-of-line anchor is
        the precision filter).
      * R9 (tool-list-no-integrity) — anchor on the dynamic
        loader; suppress if a hash / fingerprint / manifest marker
        appears in the 20-line window.

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

    # ---- R1 : loop-unbounded-langchain ----
    rule_r1 = rule_by_id["agent-runtime-loop-unbounded-langchain"]
    for m in _LANGCHAIN_AGENT_EXECUTOR_CTOR.finditer(text):
        if _LANGCHAIN_AGENT_EXECUTOR_HAS_CAP.search(m.group(0)) is not None:
            continue
        _emit(rule_r1, m.start(), m.group(0))

    # ---- R2 : loop-unbounded-langgraph ----
    rule_r2 = rule_by_id["agent-runtime-loop-unbounded-langgraph"]
    for m in _LANGGRAPH_INVOKE_WITH_CONFIG.finditer(text):
        if _LANGGRAPH_HAS_RECURSION_LIMIT.search(m.group(0)) is not None:
            continue
        _emit(rule_r2, m.start(), m.group(0))

    # ---- R3 : loop-unbounded-autogen-crewai ----
    rule_r3 = rule_by_id["agent-runtime-loop-unbounded-autogen-crewai"]
    for m in _AUTOGEN_INITIATE_CHAT.finditer(text):
        if _AUTOGEN_HAS_REPLY_CAP.search(m.group(0)) is not None:
            continue
        _emit(rule_r3, m.start(), m.group(0))
    for m in _CREWAI_AGENT_CTOR.finditer(text):
        if _CREWAI_HAS_ITER_CAP.search(m.group(0)) is not None:
            continue
        _emit(rule_r3, m.start(), m.group(0))

    # ---- R4 : gateway-master-key-confused-deputy ----
    rule_r4 = rule_by_id["agent-runtime-gateway-master-key-confused-deputy"]
    has_request_ctx = _file_contains(text, _GATEWAY_REQUEST_CONTEXT)
    if has_request_ctx:
        for m in _GATEWAY_HEADER_REWRITE_FROM_ENV.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 25, 25)
            if _GATEWAY_REQUEST_CONTEXT.search(window) is None:
                continue
            _emit(rule_r4, m.start(), m.group(0))

    # ---- R5 : subagent-dispatch-no-provenance ----
    rule_r5 = rule_by_id["agent-runtime-subagent-dispatch-no-provenance"]
    for m in _SUBAGENT_NODE_DEF.finditer(text):
        line, _ = _line_col(text, m.start())
        # 50-line forward window — the function body.
        window = _slice_window(text, line, 0, 50)
        if _SUBAGENT_DISPATCH_FIELD_READ.search(window) is None:
            continue
        if _SUBAGENT_PROVENANCE_MARKER.search(window) is not None:
            continue
        _emit(rule_r5, m.start(), m.group(0))

    # ---- R6 : tool-registry-last-write-wins ----
    rule_r6 = rule_by_id["agent-runtime-tool-registry-last-write-wins"]
    for m in _TOOL_REGISTRY_WRITE.finditer(text):
        line, _ = _line_col(text, m.start())
        # Guard typically appears BEFORE the write. 15-line backward
        # window + 3-line forward (for `raise X if exists` styles).
        window = _slice_window(text, line, 15, 3)
        if _TOOL_REGISTRY_GUARD.search(window) is not None:
            continue
        _emit(rule_r6, m.start(), m.group(0))

    # ---- R7 : memory-unbounded-accumulator ----
    rule_r7 = rule_by_id["agent-runtime-memory-unbounded-accumulator"]
    for m in _MEMORY_LANGGRAPH_ANNOTATED.finditer(text):
        _emit(rule_r7, m.start(), m.group(0))
    for m in _MEMORY_LANGCHAIN_BUFFER.finditer(text):
        _emit(rule_r7, m.start(), m.group(0))
    for m in _MEMORY_REDIS_PUSH.finditer(text):
        line, _ = _line_col(text, m.start())
        # 40-line window around the call — the bound usually appears
        # in the same helper function.
        window = _slice_window(text, line, 20, 20)
        if _MEMORY_REDIS_BOUND.search(window) is not None:
            continue
        _emit(rule_r7, m.start(), m.group(0))

    # ---- R8 : llm-client-module-level-multi-tenant ----
    rule_r8 = rule_by_id["agent-runtime-llm-client-module-level-multi-tenant"]
    for m in _LLM_MODULE_SCOPE_CLIENT.finditer(text):
        _emit(rule_r8, m.start(), m.group(0))
    for m in _LLM_MODULE_SCOPE_SINGLETON.finditer(text):
        _emit(rule_r8, m.start(), m.group(0))
    for m in _LLM_MODULE_SCOPE_DOTTED.finditer(text):
        _emit(rule_r8, m.start(), m.group(0))

    # ---- R9 : tool-list-no-integrity-fingerprint ----
    rule_r9 = rule_by_id["agent-runtime-tool-list-no-integrity-fingerprint"]
    for m in _TOOL_SOURCE_DYNAMIC.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 10, 20)
        if _TOOL_INTEGRITY_MARKER.search(window) is not None:
            continue
        _emit(rule_r9, m.start(), m.group(0))

    # Stable ordering by (line, column, rule_id).
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
