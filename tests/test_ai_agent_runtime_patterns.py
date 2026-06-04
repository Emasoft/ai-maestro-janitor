"""Tests for scripts/lib/ai_agent_runtime_patterns.py.

Pattern-coverage tests for the wave-26 distill-round-12 AI/LLM
agent-runtime catalogue (9 rules covering unbounded loops, gateway
confused-deputy, sub-agent dispatch trust, tool-registry hygiene,
memory persistence, shared LLM credentials, supply-chain drift).
Each rule has at least one positive test exercising the canary AND
at least one negative test exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import ai_agent_runtime_patterns as arp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 9 documented rule IDs."""
    assert isinstance(arp.RULES, tuple)
    rule_ids = {r.id for r in arp.RULES}
    expected = {
        "agent-runtime-loop-unbounded-langchain",
        "agent-runtime-loop-unbounded-langgraph",
        "agent-runtime-loop-unbounded-autogen-crewai",
        "agent-runtime-gateway-master-key-confused-deputy",
        "agent-runtime-subagent-dispatch-no-provenance",
        "agent-runtime-tool-registry-last-write-wins",
        "agent-runtime-memory-unbounded-accumulator",
        "agent-runtime-llm-client-module-level-multi-tenant",
        "agent-runtime-tool-list-no-integrity-fingerprint",
    }
    assert expected == rule_ids
    assert len(arp.RULES) == 9


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in arp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = arp.Finding(
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


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert arp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — LangChain AgentExecutor with no max_iterations
        "executor = AgentExecutor(agent=react_agent, tools=tools, verbose=True)\n"
        # Line 2 — Module-level OpenAI client
        "_client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))\n"
    )
    findings = arp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[arp.Finding]:
    return [f for f in arp.scan_text(text) if f.rule_id == rule_id]


# ---------- R1 : agent-runtime-loop-unbounded-langchain ------------------


def test_r1_langchain_agent_executor_without_cap_flags() -> None:
    """AgentExecutor(...) with no max_iterations → HIGH hit."""
    src = (
        "from langchain.agents import AgentExecutor, create_react_agent\n"
        "agent = create_react_agent(llm, tools, prompt)\n"
        "executor = AgentExecutor(agent=agent, tools=tools, verbose=True)\n"
        "result = executor.invoke({'input': user_query})\n"
    )
    hits = _hits("agent-runtime-loop-unbounded-langchain", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r1_langchain_agent_executor_with_cap_suppressed() -> None:
    """AgentExecutor with max_iterations= → no hit (carve-out)."""
    src = (
        "executor = AgentExecutor(\n"
        "    agent=agent, tools=tools, max_iterations=8, verbose=True,\n"
        ")\n"
    )
    assert not _hits("agent-runtime-loop-unbounded-langchain", src)


# ---------- R2 : agent-runtime-loop-unbounded-langgraph ------------------


def test_r2_langgraph_invoke_without_recursion_limit_flags() -> None:
    """compiled.stream(... config={'run_name': ...}) without recursion_limit → HIGH."""
    src = (
        "compiled = graph.compile()\n"
        "for event in compiled.stream(initial_state, "
        "config={'run_name': 'review-pipeline'}, stream_mode='values'):\n"
        "    handle(event)\n"
    )
    hits = _hits("agent-runtime-loop-unbounded-langgraph", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r2_langgraph_invoke_with_recursion_limit_suppressed() -> None:
    """recursion_limit explicit in config → no hit."""
    src = (
        "compiled = graph.compile()\n"
        "result = compiled.invoke(initial_state, "
        "config={'recursion_limit': 50, 'run_name': 'review'})\n"
    )
    assert not _hits("agent-runtime-loop-unbounded-langgraph", src)


# ---------- R3 : agent-runtime-loop-unbounded-autogen-crewai -------------


def test_r3_autogen_initiate_chat_without_cap_flags() -> None:
    """initiate_chat(...) without max_consecutive_auto_reply → HIGH hit."""
    src = (
        "from autogen import UserProxyAgent, AssistantAgent\n"
        "user_proxy = UserProxyAgent(name='user', code_execution_config=False)\n"
        "user_proxy.initiate_chat(assistant, message=prompt)\n"
    )
    hits = _hits("agent-runtime-loop-unbounded-autogen-crewai", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r3_crewai_agent_with_max_iter_suppressed() -> None:
    """Agent(role=..., max_iter=10) → no hit."""
    src = (
        "agent = Agent(role='researcher', goal='find papers', "
        "backstory='lab postdoc', tools=tools, max_iter=10)\n"
    )
    assert not _hits("agent-runtime-loop-unbounded-autogen-crewai", src)


# ---------- R4 : agent-runtime-gateway-master-key-confused-deputy --------


def test_r4_fastapi_gateway_master_key_rewrite_flags() -> None:
    """FastAPI forward handler rewriting Authorization from os.environ → CRITICAL."""
    src = (
        "@app.api_route('/{provider}/{path:path}', methods=['GET', 'POST'])\n"
        "async def forward(provider: str, path: str, request: Request):\n"
        "    body = await request.body()\n"
        "    headers = dict(request.headers)\n"
        "    headers['Authorization'] = f'Bearer {os.environ.get(\"OPENAI_API_KEY\")}'\n"
        "    async with httpx.AsyncClient() as c:\n"
        "        r = await c.post(upstream_url, content=body, headers=headers)\n"
        "    return r.json()\n"
    )
    hits = _hits("agent-runtime-gateway-master-key-confused-deputy", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r4_outside_request_context_suppressed() -> None:
    """Same header rewrite OUTSIDE a request handler → no hit."""
    src = (
        "# Library helper, not an HTTP gateway\n"
        "def build_headers():\n"
        "    headers = {}\n"
        "    headers['Authorization'] = 'Bearer ' + os.environ.get('OPENAI_API_KEY', '')\n"
        "    return headers\n"
    )
    assert not _hits("agent-runtime-gateway-master-key-confused-deputy", src)


# ---------- R5 : agent-runtime-subagent-dispatch-no-provenance -----------


def test_r5_planner_node_no_provenance_flags() -> None:
    """planner_node reads state['next_action'] with no origin check → HIGH."""
    src = (
        "def executor_node(state: GraphState) -> dict:\n"
        "    action = state['next_action']\n"
        "    result = execute_action(action)\n"
        "    return {'result': result}\n"
    )
    hits = _hits("agent-runtime-subagent-dispatch-no-provenance", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r5_executor_node_with_signature_check_suppressed() -> None:
    """Same node WITH signed_by / origin marker → no hit."""
    src = (
        "def executor_node(state: GraphState) -> dict:\n"
        "    action = state['next_action']\n"
        "    # Verify the dispatch was signed by the orchestrator agent.\n"
        "    if not verify_origin(state.get('signed_by'), state.get('signature')):\n"
        "        raise PermissionError('forged dispatch')\n"
        "    return execute_action(action)\n"
    )
    assert not _hits("agent-runtime-subagent-dispatch-no-provenance", src)


# ---------- R6 : agent-runtime-tool-registry-last-write-wins -------------


def test_r6_tool_registry_unguarded_write_flags() -> None:
    """self.tools[name] = fn with no guard → HIGH hit."""
    src = (
        "class ToolRegistry:\n"
        "    def __init__(self) -> None:\n"
        "        self.tools: dict[str, callable] = {}\n"
        "    def register(self, name: str, fn: callable) -> None:\n"
        "        self.tools[name] = fn\n"
    )
    hits = _hits("agent-runtime-tool-registry-last-write-wins", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r6_tool_registry_with_guard_suppressed() -> None:
    """Write preceded by `if name in self.tools: raise ...` → no hit."""
    src = (
        "class ToolRegistry:\n"
        "    def __init__(self) -> None:\n"
        "        self.tools: dict[str, callable] = {}\n"
        "    def register(self, name: str, fn: callable) -> None:\n"
        "        if name in self.tools:\n"
        "            raise ValueError(f'duplicate tool: {name}')\n"
        "        self.tools[name] = fn\n"
    )
    assert not _hits("agent-runtime-tool-registry-last-write-wins", src)


# ---------- R7 : agent-runtime-memory-unbounded-accumulator --------------


def test_r7_langgraph_annotated_list_operator_add_flags() -> None:
    """Annotated[list, operator.add] in state TypedDict → MEDIUM hit."""
    src = (
        "from typing import Annotated, TypedDict\n"
        "import operator\n"
        "class ReviewState(TypedDict):\n"
        "    progress: Annotated[list, operator.add]\n"
        "    messages: Annotated[list[str], operator.add]\n"
    )
    hits = _hits("agent-runtime-memory-unbounded-accumulator", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_r7_redis_rpush_with_ltrim_suppressed() -> None:
    """rpush followed by LTRIM in the same function → no hit (bounded)."""
    src = (
        "def append_message(session_id: str, msg: dict) -> None:\n"
        "    r.rpush(f'session:{session_id}', json.dumps(msg))\n"
        "    # Keep the last 200 messages only.\n"
        "    r.ltrim(f'session:{session_id}', -200, -1)\n"
        "    r.expire(f'session:{session_id}', 3600)\n"
    )
    assert not _hits("agent-runtime-memory-unbounded-accumulator", src)


# ---------- R8 : agent-runtime-llm-client-module-level-multi-tenant -----


def test_r8_module_level_openai_client_flags() -> None:
    """_client = OpenAI(api_key=os.environ.get(...)) at module scope → HIGH."""
    src = (
        "import os\n"
        "from openai import OpenAI\n"
        "_client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))\n"
        "\n"
        "def run_agent(tenant_id: str, prompt: str) -> str:\n"
        "    return _client.chat.completions.create(model='gpt-4', messages=[...])\n"
    )
    hits = _hits("agent-runtime-llm-client-module-level-multi-tenant", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r8_per_request_client_construction_suppressed() -> None:
    """Client built INSIDE the handler (no module-scope assignment) → no hit."""
    src = (
        "import os\n"
        "from openai import OpenAI\n"
        "\n"
        "def run_agent(tenant_id: str, prompt: str) -> str:\n"
        "    api_key = vault.get_tenant_key(tenant_id)\n"
        "    client = OpenAI(api_key=api_key)\n"
        "    return client.chat.completions.create(model='gpt-4', messages=[...])\n"
    )
    assert not _hits("agent-runtime-llm-client-module-level-multi-tenant", src)


# ---------- R9 : agent-runtime-tool-list-no-integrity-fingerprint --------


def test_r9_mcp_tools_list_no_fingerprint_flags() -> None:
    """server.send_request('tools/list') with no hash/fingerprint → MEDIUM hit."""
    src = (
        "async def load_mcp_tools(server) -> list:\n"
        "    resp = await server.send_request('tools/list')\n"
        "    return resp['result']['tools']\n"
    )
    hits = _hits("agent-runtime-tool-list-no-integrity-fingerprint", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_r9_mcp_tools_list_with_hash_suppressed() -> None:
    """Same loader WITH hashlib fingerprint → no hit."""
    src = (
        "import hashlib\n"
        "async def load_mcp_tools(server) -> list:\n"
        "    resp = await server.send_request('tools/list')\n"
        "    tools = resp['result']['tools']\n"
        "    # Fingerprint each tool def for drift detection.\n"
        "    for t in tools:\n"
        "        t['_fp'] = hashlib.sha256(json.dumps(t, sort_keys=True).encode()).hexdigest()\n"
        "    return tools\n"
    )
    assert not _hits("agent-runtime-tool-list-no-integrity-fingerprint", src)
