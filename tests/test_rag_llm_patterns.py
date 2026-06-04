"""Tests for scripts/lib/rag_llm_patterns.py.

Pattern-coverage tests for the Wave-20 distillation round 6 angle A
catalogue (RAG / LLM safety beyond prompt-injection). Each of the 13
rules gets at least one positive test plus at least one negative /
carve-out test exercising the file-level guard, the span sanitiser,
or the proximity check.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import rag_llm_patterns as rlp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES is a tuple and exposes every advertised rule id."""
    assert isinstance(rlp.RULES, tuple)
    rule_ids = {r.id for r in rlp.RULES}
    expected = {
        "rag-llm.vectorstore-upsert-untrusted-text-metadata",
        "rag-llm.embedding-model-not-pinned-by-revision",
        "rag-llm.retrieved-context-into-system-prompt",
        "rag-llm.tool-result-loops-back-into-prompt-unchecked",
        "rag-llm.function-call-output-into-os-without-schema-check",
        "rag-llm.streaming-tokens-into-html-renderer",
        "rag-llm.thinking-block-logged-or-persisted",
        "rag-llm.session-memory-no-user-scoping",
        "rag-llm.cosine-threshold-too-permissive",
        "rag-llm.prompt-cache-key-attacker-controlled",
        "rag-llm.system-message-boundary-from-user-input",
        "rag-llm.adversarial-token-sequence-in-user-content",
        "rag-llm.model-card-readme-parsed-as-instruction",
    }
    assert expected.issubset(rule_ids)
    assert len(rlp.RULES) == len(expected)


def test_every_rule_has_owasp_mapping_and_severity() -> None:
    """Every rule maps to a non-empty ASI- prefix and a known severity."""
    for rule in rlp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the sibling pattern modules' Finding shape."""
    f = rlp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-08"


def test_scan_text_empty_input_returns_empty_list() -> None:
    """scan_text('') returns the empty list (not None / not an error)."""
    assert rlp.scan_text("") == []


def test_scan_text_findings_sorted_by_line_then_col() -> None:
    """Findings come out sorted by (line, column, rule_id)."""
    src = (
        "ctx = retriever.invoke(q)\n"
        "client.messages.create(\n"
        "    system=ctx, model='claude', messages=[]\n"
        ")\n"
        "logger.info(response.thinking)\n"
    )
    out = rlp.scan_text(src)
    assert out == sorted(out, key=lambda f: (f.line, f.column, f.rule_id))


def _hits(rule_id: str, text: str, *, filename: str = "") -> list[rlp.Finding]:
    return [
        f for f in rlp.scan_text(text, filename=filename)
        if f.rule_id == rule_id
    ]


# ---------- Rule 1 : vectorstore-upsert-untrusted-text-metadata ----------


def test_rule1_pinecone_upsert_with_network_text_metadata_fires() -> None:
    """Pinecone upsert carrying a `text` metadata field from a fetch fires."""
    src = (
        "data = requests.get(url).text\n"
        "for chunk in chunks(data):\n"
        "    index.upsert(vectors=[(id_, vec, {'text': chunk['text']})])\n"
    )
    assert _hits("rag-llm.vectorstore-upsert-untrusted-text-metadata", src)


def test_rule1_add_texts_with_network_content_metadata_fires() -> None:
    """LangChain `.add_texts(...)` with `content` in metadata after a fetch."""
    src = (
        "raw = httpx.get(github_url).text\n"
        "vector_store.add_texts(\n"
        "    texts=[raw], metadata=[{'content': raw}]\n"
        ")\n"
    )
    assert _hits("rag-llm.vectorstore-upsert-untrusted-text-metadata", src)


def test_rule1_file_with_bleach_clean_suppresses() -> None:
    """`bleach.clean` anywhere in the file is the sanitiser opt-out."""
    src = (
        "import bleach\n"
        "data = requests.get(url).text\n"
        "safe = bleach.clean(data)\n"
        "index.upsert(vectors=[(id_, vec, {'text': safe})])\n"
    )
    assert not _hits("rag-llm.vectorstore-upsert-untrusted-text-metadata", src)


def test_rule1_sanitised_marker_suppresses() -> None:
    """The `# sanitised-rag-input` marker is the operator opt-out."""
    src = (
        "# sanitised-rag-input — chunks pre-cleaned upstream\n"
        "data = requests.get(url).text\n"
        "index.upsert(vectors=[(id_, vec, {'text': data})])\n"
    )
    assert not _hits("rag-llm.vectorstore-upsert-untrusted-text-metadata", src)


# ---------- Rule 2 : embedding-model-not-pinned-by-revision --------------


def test_rule2_sentence_transformer_no_revision_with_encode_fires() -> None:
    """`SentenceTransformer('name')` + `.encode(` and no revision pin fires."""
    src = (
        "model = SentenceTransformer('all-MiniLM-L6-v2')\n"
        "vecs = model.encode(texts)\n"
    )
    assert _hits("rag-llm.embedding-model-not-pinned-by-revision", src)


def test_rule2_huggingface_embeddings_no_pin_with_embed_query_fires() -> None:
    """`HuggingFaceEmbeddings(model_name='x')` + `.embed_query` fires."""
    src = (
        "emb = HuggingFaceEmbeddings(model_name='intfloat/e5-large-v2')\n"
        "q = emb.embed_query('hello')\n"
    )
    assert _hits("rag-llm.embedding-model-not-pinned-by-revision", src)


def test_rule2_revision_pin_suppresses() -> None:
    """`revision='<commit-hex>'` anywhere in the file suppresses."""
    src = (
        "model = SentenceTransformer('all-MiniLM-L6-v2', "
        "revision='abc1234567890abcdef')\n"
        "vecs = model.encode(texts)\n"
    )
    assert not _hits("rag-llm.embedding-model-not-pinned-by-revision", src)


def test_rule2_no_embedding_invocation_suppresses() -> None:
    """Ctor without any `.encode/.embed_*` call in file does not fire."""
    src = "model = SentenceTransformer('foo')\n"
    assert not _hits("rag-llm.embedding-model-not-pinned-by-revision", src)


def test_rule2_provider_namespaced_id_downgrades_to_medium() -> None:
    """`text-embedding-3-small` is provider-hosted — severity drops to MEDIUM."""
    src = (
        "emb = OpenAIEmbeddings(model='text-embedding-3-small')\n"
        "vecs = emb.embed_documents(texts)\n"
    )
    out = _hits("rag-llm.embedding-model-not-pinned-by-revision", src)
    assert out
    assert all(h.severity == "MEDIUM" for h in out), [
        (h.severity, h.matched_text) for h in out
    ]


# ---------- Rule 3 : retrieved-context-into-system-prompt ----------------


def test_rule3_retriever_invoke_then_system_prompt_fires() -> None:
    """`retriever.invoke()` → `messages.create(system=context)` is CRITICAL."""
    src = (
        "ctx = retriever.invoke(question)\n"
        "client.messages.create(model='claude-sonnet', "
        "system=ctx, messages=user_messages)\n"
    )
    assert _hits("rag-llm.retrieved-context-into-system-prompt", src)


def test_rule3_similarity_search_into_system_block_fires() -> None:
    """`similarity_search` + `system=[{'type':'text',...}]` block fires."""
    src = (
        "docs = vectorstore.similarity_search(q)\n"
        "client.messages.create(\n"
        "    system=[{'type': 'text', 'text': '\\n'.join(docs)}],\n"
        "    messages=[])\n"
    )
    assert _hits("rag-llm.retrieved-context-into-system-prompt", src)


def test_rule3_sanitiser_in_span_suppresses() -> None:
    """`strip_directives` in the matched span suppresses."""
    src = (
        "ctx = retriever.invoke(q)\n"
        "ctx = strip_directives(ctx)\n"
        "client.messages.create(system=ctx, messages=user_messages)\n"
    )
    assert not _hits("rag-llm.retrieved-context-into-system-prompt", src)


# ---------- Rule 4 : tool-result-loops-back-into-prompt-unchecked --------


def test_rule4_agent_loop_tool_result_appended_fires() -> None:
    """`while tool_use:` + `messages.append(... tool_result ...)` fires."""
    src = (
        "while stop_reason == 'tool_use':\n"
        "    out = run_tool(t)\n"
        "    messages.append({'role': 'user', 'content': [\n"
        "        {'type': 'tool_result', 'tool_use_id': t.id, 'content': out}\n"
        "    ]})\n"
    )
    assert _hits("rag-llm.tool-result-loops-back-into-prompt-unchecked", src)


def test_rule4_for_range_max_iterations_fires() -> None:
    """`for _ in range(max_iterations):` + ToolMessage append fires."""
    src = (
        "for _ in range(max_iterations):\n"
        "    result = call_tool()\n"
        "    messages.append(ToolMessage(content=result))\n"
    )
    assert _hits("rag-llm.tool-result-loops-back-into-prompt-unchecked", src)


def test_rule4_validator_in_span_suppresses() -> None:
    """`jsonschema.validate` in the span is the opt-out."""
    src = (
        "while stop_reason == 'tool_use':\n"
        "    out = run_tool(t)\n"
        "    jsonschema.validate(out, schema)\n"
        "    messages.append({'role': 'tool', 'content': out})\n"
    )
    assert not _hits(
        "rag-llm.tool-result-loops-back-into-prompt-unchecked", src
    )


def test_rule4_validated_marker_suppresses() -> None:
    """`# validated-tool-result` marker suppresses the hit."""
    src = (
        "for i in range(max_turns):\n"
        "    out = call()\n"
        "    # validated-tool-result\n"
        "    messages.append({'role': 'tool', 'content': out})\n"
    )
    assert not _hits(
        "rag-llm.tool-result-loops-back-into-prompt-unchecked", src
    )


# ---------- Rule 5 : function-call-output-into-os-without-schema-check ---


def test_rule5_json_loads_message_content_into_subprocess_fires() -> None:
    """`json.loads(message.content)` → `subprocess.run(args)` is CRITICAL."""
    src = (
        "data = json.loads(message.content[0].text)\n"
        "subprocess.run(['rm', data['path']])\n"
    )
    assert _hits(
        "rag-llm.function-call-output-into-os-without-schema-check", src
    )


def test_rule5_tool_use_into_path_unlink_fires() -> None:
    """`tool_use = ...` then `Path(...).unlink()` fires."""
    src = (
        "tool_use = block.input\n"
        "Path(tool_use['target']).unlink()\n"
    )
    assert _hits(
        "rag-llm.function-call-output-into-os-without-schema-check", src
    )


def test_rule5_pydantic_validate_in_span_suppresses() -> None:
    """`pydantic` validation in the span suppresses."""
    src = (
        "import pydantic\n"
        "raw = json.loads(message.content[0].text)\n"
        "args = ToolArgs.parse_obj(raw)\n"
        "subprocess.run(['rm', args.path])\n"
    )
    assert not _hits(
        "rag-llm.function-call-output-into-os-without-schema-check", src
    )


def test_rule5_tool_args_validated_marker_suppresses() -> None:
    """`# tool-args-validated` marker suppresses the hit."""
    src = (
        "data = json.loads(message.content[0].text)\n"
        "# tool-args-validated\n"
        "subprocess.run(['rm', data['path']])\n"
    )
    assert not _hits(
        "rag-llm.function-call-output-into-os-without-schema-check", src
    )


# ---------- Rule 6 : streaming-tokens-into-html-renderer -----------------


def test_rule6_messages_stream_into_innerhtml_fires() -> None:
    """`messages.stream` → `innerHTML +=` fires."""
    src = (
        "stream = client.messages.stream(model='claude')\n"
        "for chunk in stream.text_stream:\n"
        "    el.innerHTML += chunk\n"
    )
    assert _hits("rag-llm.streaming-tokens-into-html-renderer", src)


def test_rule6_openai_stream_true_into_dangerously_set_fires() -> None:
    """`stream=True` + `dangerouslySetInnerHTML` fires."""
    src = (
        "const completion = client.chat.completions.create({stream: true});\n"
        "for await (const chunk of completion) {\n"
        "  setOutput(chunk);\n"
        "}\n"
        "return <div dangerouslySetInnerHTML={{__html: out}} />;\n"
    )
    assert _hits("rag-llm.streaming-tokens-into-html-renderer", src)


def test_rule6_dompurify_in_span_suppresses() -> None:
    """`DOMPurify.sanitize` in the span suppresses (note: still per-chunk
    sanitisation is risky in real life, but the rule honours its marker)."""
    src = (
        "for await (const chunk of stream) {\n"
        "  el.innerHTML += DOMPurify.sanitize(chunk);\n"
        "}\n"
    )
    assert not _hits("rag-llm.streaming-tokens-into-html-renderer", src)


def test_rule6_text_content_in_span_suppresses() -> None:
    """Switching to `textContent =` is the safe pattern."""
    src = (
        "for await (const chunk of stream) {\n"
        "  el.textContent = el.textContent + chunk;\n"
        "  el.innerHTML += chunk;\n"
        "}\n"
    )
    # The textContent reset within the span suppresses the innerHTML
    # finding via the escape-guard.
    assert not _hits("rag-llm.streaming-tokens-into-html-renderer", src)


# ---------- Rule 7 : thinking-block-logged-or-persisted ------------------


def test_rule7_response_thinking_into_logger_fires() -> None:
    """`response.thinking` → `logger.info(...)` fires."""
    src = (
        "resp = client.messages.create(model='claude')\n"
        "trace = resp.thinking\n"
        "logger.info('reasoning trace: %s', trace)\n"
    )
    assert _hits("rag-llm.thinking-block-logged-or-persisted", src)


def test_rule7_thinking_block_into_webhook_post_fires() -> None:
    """`<thinking>...</thinking>` + `requests.post` (webhook) fires."""
    src = (
        "raw = '<thinking>internal model reasoning here</thinking>'\n"
        "requests.post('https://hooks.slack.com/x', json={'text': raw})\n"
    )
    assert _hits("rag-llm.thinking-block-logged-or-persisted", src)


def test_rule7_thinking_into_sentry_capture_fires() -> None:
    """`.thinking` into `capture_message` fires."""
    src = (
        "from sentry_sdk import capture_message\n"
        "msg = resp.thinking\n"
        "capture_message(msg)\n"
    )
    assert _hits("rag-llm.thinking-block-logged-or-persisted", src)


def test_rule7_redact_thinking_in_span_suppresses() -> None:
    """`redact_thinking(...)` in the span suppresses."""
    src = (
        "raw = resp.thinking\n"
        "safe = redact_thinking(raw)\n"
        "logger.info(safe)\n"
    )
    assert not _hits("rag-llm.thinking-block-logged-or-persisted", src)


# ---------- Rule 8 : session-memory-no-user-scoping ----------------------


def test_rule8_conversation_buffer_memory_no_scope_fires() -> None:
    """`ConversationBufferMemory()` with no scope-token context fires."""
    src = "memory = ConversationBufferMemory()\n"
    assert _hits("rag-llm.session-memory-no-user-scoping", src)


def test_rule8_redis_conversation_no_scope_fires() -> None:
    """`redis.set('conversation:abc', ...)` with no user_id near fires."""
    src = "redis.set('conversation:global', json.dumps(history))\n"
    assert _hits("rag-llm.session-memory-no-user-scoping", src)


def test_rule8_user_id_proximity_suppresses() -> None:
    """`user_id` within 200 chars BEFORE the call suppresses."""
    src = (
        "user_id = current_user.id\n"
        "key = f'conversation:{user_id}'\n"
        "memory = ConversationBufferMemory()\n"
    )
    assert not _hits("rag-llm.session-memory-no-user-scoping", src)


def test_rule8_session_id_proximity_suppresses() -> None:
    """`session_id` token within 200 chars BEFORE suppresses."""
    src = (
        "session_id = get_session()\n"
        "memory = ConversationSummaryMemory(session_id=session_id)\n"
    )
    assert not _hits("rag-llm.session-memory-no-user-scoping", src)


# ---------- Rule 9 : cosine-threshold-too-permissive ---------------------


def test_rule9_top_k_50_fires_in_retrieval_context() -> None:
    """`top_k=50` in a file referencing vectorstore fires."""
    src = (
        "from langchain.vectorstores import Pinecone\n"
        "results = vectorstore.similarity_search(q, top_k=50)\n"
    )
    assert _hits("rag-llm.cosine-threshold-too-permissive", src)


def test_rule9_n_results_25_fires() -> None:
    """`n_results=25` in a vectorstore file fires."""
    src = (
        "from chromadb import Client\n"
        "out = collection.query(query_texts=[q], n_results=25)\n"
    )
    assert _hits("rag-llm.cosine-threshold-too-permissive", src)


def test_rule9_threshold_loose_fires() -> None:
    """`if score > 0.4` in a retrieval file is too loose."""
    src = (
        "from langchain.vectorstores import Pinecone\n"
        "for r in results:\n"
        "    if r.score > 0.4:\n"
        "        keep.append(r)\n"
    )
    assert _hits("rag-llm.cosine-threshold-too-permissive", src)


def test_rule9_pragma_suppresses() -> None:
    """`# rag-recall-tuned: <reason>` suppresses."""
    src = (
        "from langchain.vectorstores import Pinecone\n"
        "# rag-recall-tuned: legal-discovery needs wide recall\n"
        "results = vectorstore.similarity_search(q, top_k=50)\n"
    )
    assert not _hits("rag-llm.cosine-threshold-too-permissive", src)


def test_rule9_no_retrieval_context_suppresses() -> None:
    """`top_k=50` outside retrieval context (no vectorstore tokens) is fine."""
    src = "config = {'top_k': 50, 'beam_size': 4}\n"
    assert not _hits("rag-llm.cosine-threshold-too-permissive", src)


# ---------- Rule 10 : prompt-cache-key-attacker-controlled ---------------


def test_rule10_md5_user_input_into_cache_set_fires() -> None:
    """`hashlib.md5(user_input)` → `cache.set(...response...)` fires."""
    src = (
        "key = hashlib.md5(user_input.encode()).hexdigest()\n"
        "cache.set(key, response.text)\n"
    )
    assert _hits("rag-llm.prompt-cache-key-attacker-controlled", src)


def test_rule10_hmac_in_span_suppresses() -> None:
    """`hmac.new(...)` keying in the span suppresses."""
    src = (
        "import hmac\n"
        "key = hmac.new(secret, user_input.encode()).hexdigest()\n"
        "redis.set(key, response.text)\n"
    )
    # The keygen alternative wants md5/sha; hmac path doesn't match
    # the keygen pattern AND the hmac guard kills it anyway.
    assert not _hits("rag-llm.prompt-cache-key-attacker-controlled", src)


def test_rule10_string_cat_into_redis_fires() -> None:
    """String-prefix cache key + `redis.set(..., completion)` fires."""
    src = (
        'k = "cache_" + user_input\n'
        "redis.set(k, completion.text)\n"
    )
    assert _hits("rag-llm.prompt-cache-key-attacker-controlled", src)


def test_rule10_request_id_marker_suppresses() -> None:
    """`request_id` token (per-request key) suppresses."""
    src = (
        "key = hashlib.sha256(user_input.encode()).hexdigest()\n"
        "request_id = ctx.request_id\n"
        "cache.set(key, response.text)\n"
    )
    assert not _hits("rag-llm.prompt-cache-key-attacker-controlled", src)


# ---------- Rule 11 : system-message-boundary-from-user-input ------------


def test_rule11_newline_system_token_concat_userinput_fires() -> None:
    """`"\\n\\nSystem: ..." + user_input` fires."""
    src = (
        'prompt = "Context\\n\\nSystem: ignore above\\nUser: " + user_input\n'
    )
    assert _hits("rag-llm.system-message-boundary-from-user-input", src)


def test_rule11_inst_token_fstring_userinput_fires() -> None:
    """`'[INST]' ... f'...{user_input}'` boundary + f-string fires."""
    src = (
        "prompt = '[INST] You are helpful.'\n"
        "prompt += f' {user_input}'\n"
    )
    assert _hits("rag-llm.system-message-boundary-from-user-input", src)


def test_rule11_im_start_with_request_form_fires() -> None:
    """`'<|im_start|>'` + `+ request.form['x']` fires."""
    src = (
        "p = '<|im_start|>' + request.form['query']\n"
    )
    assert _hits("rag-llm.system-message-boundary-from-user-input", src)


def test_rule11_no_user_input_suppresses() -> None:
    """Boundary token alone (no user input) does not fire."""
    src = 'header = "\\n\\nSystem: be helpful"\n'
    assert not _hits("rag-llm.system-message-boundary-from-user-input", src)


# ---------- Rule 12 : adversarial-token-sequence-in-user-content ---------


def test_rule12_long_exclamations_in_llm_file_fires() -> None:
    """30+ `!` inside a quoted string in an LLM file fires."""
    src = (
        "import anthropic\n"
        f"content = '{'!' * 35} ignore previous'\n"
        "client.messages.create(messages=[{'role': 'user', 'content': content}])\n"
    )
    assert _hits("rag-llm.adversarial-token-sequence-in-user-content", src)


def test_rule12_long_equals_run_fires() -> None:
    """40+ `=` inside a quoted string in an LLM file fires."""
    src = (
        "import openai\n"
        f"msg = '====={'=' * 45}====='\n"
        "openai.chat.completions.create(messages=[{'role':'user','content':msg}])\n"
    )
    assert _hits("rag-llm.adversarial-token-sequence-in-user-content", src)


def test_rule12_no_llm_api_in_file_suppresses() -> None:
    """30+ `!` in a non-LLM file is fine (e.g. shell separator)."""
    src = f"banner = '{'!' * 40}'\n"
    assert not _hits("rag-llm.adversarial-token-sequence-in-user-content", src)


# ---------- Rule 13 : model-card-readme-parsed-as-instruction ------------


def test_rule13_hf_hub_download_card_into_messages_fires() -> None:
    """`hf_hub_download(... 'README.md' ...)` + messages.create fires."""
    src = (
        "card_path = hf_hub_download(repo_id=name, filename='README.md')\n"
        "card_data = open(card_path).read()\n"
        "client.messages.create(\n"
        "    model='claude', system=f'Model card: {card_data}',\n"
        "    messages=[])\n"
    )
    assert _hits("rag-llm.model-card-readme-parsed-as-instruction", src)


def test_rule13_model_info_carddata_into_chat_completions_fires() -> None:
    """`HfApi().model_info()` + `card_data` + chat.completions.create fires."""
    src = (
        "info = huggingface_hub.HfApi().model_info(repo)\n"
        "card_data = info.cardData\n"
        "openai.chat.completions.create(\n"
        "    messages=[{'role': 'system',\n"
        "               'content': f'Model card: {card_data}'}])\n"
    )
    assert _hits("rag-llm.model-card-readme-parsed-as-instruction", src)


def test_rule13_no_sink_does_not_fire() -> None:
    """Download a card but never feed it to an LLM = no hit."""
    src = (
        "info = huggingface_hub.HfApi().model_info(repo)\n"
        "card_data = info.cardData\n"
        "print(card_data)\n"
    )
    assert not _hits("rag-llm.model-card-readme-parsed-as-instruction", src)


# ---------- Scanner-level invariants -------------------------------------


def test_test_filename_suppresses_every_rule() -> None:
    """A test/fixture filename suppresses ALL rules (test code is exempt)."""
    src = (
        "data = requests.get(url).text\n"
        "index.upsert(vectors=[(id_, vec, {'text': data})])\n"
        "ctx = retriever.invoke(q)\n"
        "client.messages.create(system=ctx, messages=[])\n"
    )
    assert not rlp.scan_text(src, filename="tests/test_something.py")
    assert not rlp.scan_text(src, filename="src/fixtures/sample.py")
    assert not rlp.scan_text(src, filename="examples/demo.py")


def test_scan_text_dedupes_same_rule_same_position() -> None:
    """Same rule firing at the same (rule, line, col) emits once."""
    src = (
        "data = requests.get(url).text\n"
        "index.upsert(vectors=[(id_, vec, {'text': data, 'content': data})])\n"
    )
    out = _hits("rag-llm.vectorstore-upsert-untrusted-text-metadata", src)
    keys = {(h.line, h.column) for h in out}
    assert len(out) == len(keys)


def test_long_match_truncated_in_finding() -> None:
    """matched_text > 200 chars gets truncated with an ellipsis."""
    big = "X" * 500
    src = (
        "data = requests.get(url).text\n"
        f"# {big}\n"
        "index.upsert(vectors=[(id_, vec, {'text': data})])\n"
    )
    out = _hits("rag-llm.vectorstore-upsert-untrusted-text-metadata", src)
    assert out
    assert all(len(h.matched_text) <= 201 for h in out)
    assert any("…" in h.matched_text for h in out)


def test_owasp_distribution_includes_new_categories() -> None:
    """The 13 rules use the new ASI-08 and ASI-09 categories at least once."""
    cats = {r.owasp_asi for r in rlp.RULES}
    assert "ASI-08" in cats
    assert "ASI-09" in cats
