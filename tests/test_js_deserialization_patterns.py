"""Tests for scripts/lib/js_deserialization_patterns.py.

Pattern-coverage tests for the Wave-25 distill-round-11 angle (browser/JS
deserialization & message-event-trust). Each of the 6 rules has at
least two tests: a positive canary exercising the vulnerability and a
negative test exercising the FP-suppression carve-out (schema validator
present, origin check present, __proto__ stripped, etc.).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import js_deserialization_patterns as jdp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(jdp.RULES, tuple)
    rule_ids = {r.id for r in jdp.RULES}
    expected = {
        "jsdes-ws-event-data-json-parse-no-schema",
        "jsdes-storage-parse-into-state-spread",
        "jsdes-window-message-listener-no-origin-check",
        "jsdes-postmessage-wildcard-target-origin",
        "jsdes-structured-clone-untrusted-into-object-assign",
        "jsdes-json-parse-reviver-captured-state-write",
    }
    assert expected == rule_ids
    assert len(jdp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in jdp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = jdp.Finding(
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
    assert jdp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — postMessage wildcard (high-precision rule)
        "popup.postMessage({ token }, '*');\n"
        # Line 2 — another wildcard
        "iframe.contentWindow.postMessage(payload, '*');\n"
    )
    findings = jdp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[jdp.Finding]:
    return [f for f in jdp.scan_text(text) if f.rule_id == rule_id]


# ---------- J1 : jsdes-ws-event-data-json-parse-no-schema ----------------


def test_j1_websocket_json_parse_no_schema_flags() -> None:
    """WebSocket onmessage with raw JSON.parse and no schema → HIGH hit."""
    src = (
        "ws.onmessage = (e) => {\n"
        "  try {\n"
        "    const data = JSON.parse(e.data);\n"
        "    onMessageRef.current(data);\n"
        "  } catch { /* ignore */ }\n"
        "};\n"
    )
    hits = _hits("jsdes-ws-event-data-json-parse-no-schema", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_j1_eventsource_json_parse_no_schema_flags() -> None:
    """EventSource onmessage with raw JSON.parse and no schema → flagged."""
    src = (
        "es.onmessage = (e) => {\n"
        "  const evt = JSON.parse(e.data);\n"
        "  setEvents(prev => [...prev, evt]);\n"
        "  if (evt.type === 'complete') stop();\n"
        "};\n"
    )
    assert _hits("jsdes-ws-event-data-json-parse-no-schema", src)


def test_j1_addeventlistener_message_no_schema_flags() -> None:
    """worker.addEventListener('message', handler) without schema → flagged."""
    src = (
        "worker.addEventListener('message', (event) => {\n"
        "  const data = JSON.parse(event.data);\n"
        "  dispatch(data);\n"
        "});\n"
    )
    assert _hits("jsdes-ws-event-data-json-parse-no-schema", src)


def test_j1_zod_schema_suppresses() -> None:
    """Same shape with a zod safeParse validator within window → no hit."""
    src = (
        "ws.onmessage = (e) => {\n"
        "  const parsed = JSON.parse(e.data);\n"
        "  const result = MessageSchema.safeParse(parsed);\n"
        "  if (result.success) dispatch(result.data);\n"
        "};\n"
    )
    assert not _hits("jsdes-ws-event-data-json-parse-no-schema", src)


def test_j1_no_parse_idiom_silent() -> None:
    """Listener without JSON.parse(e.data) → no hit (no untrusted parse)."""
    src = (
        "ws.onmessage = (e) => {\n"
        "  console.log('got message of size', e.data.length);\n"
        "};\n"
    )
    assert not _hits("jsdes-ws-event-data-json-parse-no-schema", src)


# ---------- J2 : jsdes-storage-parse-into-state-spread -------------------


def test_j2_localstorage_parse_spread_into_state_flags() -> None:
    """JSON.parse(localStorage.getItem(...)) spread into state → MEDIUM hit."""
    src = (
        "useEffect(() => {\n"
        "  const stored = window.localStorage.getItem('app-state');\n"
        "  if (stored) {\n"
        "    const parsed = JSON.parse(window.localStorage.getItem('app'));\n"
        "    setProgress((prev) => ({ ...prev, ...parsed }));\n"
        "  }\n"
        "}, []);\n"
    )
    hits = _hits("jsdes-storage-parse-into-state-spread", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_j2_sessionstorage_object_assign_flags() -> None:
    """JSON.parse(sessionStorage[...]) followed by Object.assign → flagged."""
    src = (
        "const parsed = JSON.parse(sessionStorage['app']);\n"
        "Object.assign(state, parsed);\n"
    )
    assert _hits("jsdes-storage-parse-into-state-spread", src)


def test_j2_cookie_parse_lodash_merge_flags() -> None:
    """JSON.parse(document.cookie) into lodash merge → flagged."""
    src = (
        "const cached = JSON.parse(document.cookie);\n"
        "_.merge(config, cached);\n"
    )
    assert _hits("jsdes-storage-parse-into-state-spread", src)


def test_j2_schema_validator_suppresses() -> None:
    """JSON.parse(localStorage) → schema.safeParse → no hit."""
    src = (
        "const stored = JSON.parse(localStorage.getItem('user'));\n"
        "const result = UserSchema.safeParse(stored);\n"
        "if (result.success) setUser(result.data);\n"
    )
    assert not _hits("jsdes-storage-parse-into-state-spread", src)


def test_j2_proto_strip_suppresses() -> None:
    """JSON.parse(localStorage) → delete __proto__ → no hit."""
    src = (
        "const parsed = JSON.parse(localStorage.getItem('cfg'));\n"
        "delete parsed.__proto__;\n"
        "Object.assign(state, parsed);\n"
    )
    assert not _hits("jsdes-storage-parse-into-state-spread", src)


def test_j2_parse_without_spread_silent() -> None:
    """JSON.parse(localStorage) but no spread/merge sink → no hit."""
    src = (
        "const token = JSON.parse(localStorage.getItem('token'));\n"
        "console.log('token length:', token.value.length);\n"
    )
    assert not _hits("jsdes-storage-parse-into-state-spread", src)


# ---------- J3 : jsdes-window-message-listener-no-origin-check -----------


def test_j3_window_listener_no_origin_check_flags() -> None:
    """window.addEventListener('message') without origin check → CRITICAL hit."""
    src = (
        "window.addEventListener('message', (event) => {\n"
        "  const data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;\n"
        "  if (data.action === 'updateProfile') {\n"
        "    document.querySelector('#name').innerHTML = data.html;\n"
        "  }\n"
        "});\n"
    )
    hits = _hits("jsdes-window-message-listener-no-origin-check", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_j3_globalthis_listener_no_origin_flags() -> None:
    """globalThis.addEventListener('message') without origin check → flagged."""
    src = (
        "globalThis.addEventListener('message', (ev) => {\n"
        "  location.href = ev.data.url;\n"
        "});\n"
    )
    assert _hits("jsdes-window-message-listener-no-origin-check", src)


def test_j3_origin_check_suppresses() -> None:
    """Listener with event.origin !== EXPECTED guard → no hit."""
    src = (
        "window.addEventListener('message', (event) => {\n"
        "  if (event.origin !== 'https://app.example.com') return;\n"
        "  doStuff(event.data);\n"
        "});\n"
    )
    assert not _hits("jsdes-window-message-listener-no-origin-check", src)


def test_j3_allowed_origins_set_suppresses() -> None:
    """Listener that checks against ALLOWED_ORIGINS → no hit."""
    src = (
        "const ALLOWED_ORIGINS = new Set(['https://app.example.com']);\n"
        "window.addEventListener('message', (event) => {\n"
        "  if (!ALLOWED_ORIGINS.has(event.origin)) return;\n"
        "  handle(event.data);\n"
        "});\n"
    )
    assert not _hits("jsdes-window-message-listener-no-origin-check", src)


# ---------- J4 : jsdes-postmessage-wildcard-target-origin ----------------


def test_j4_postmessage_wildcard_flags() -> None:
    """popup.postMessage(payload, '*') → HIGH hit."""
    src = (
        "popup.postMessage({ token: localStorage.getItem('access_token') }, '*');\n"
    )
    hits = _hits("jsdes-postmessage-wildcard-target-origin", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_j4_postmessage_wildcard_identifier_flags() -> None:
    """iframe.contentWindow.postMessage(payload, '*') → flagged."""
    src = "iframe.contentWindow.postMessage(payload, '*');\n"
    assert _hits("jsdes-postmessage-wildcard-target-origin", src)


def test_j4_postmessage_explicit_origin_no_hit() -> None:
    """postMessage with a real origin → no hit."""
    src = (
        "popup.postMessage(payload, 'https://app.example.com');\n"
    )
    assert not _hits("jsdes-postmessage-wildcard-target-origin", src)


def test_j4_postmessage_no_target_origin_no_hit() -> None:
    """postMessage with only one argument → no hit (rare but well-formed call)."""
    # Single-arg postMessage in MessagePort/Worker context — different shape.
    src = "port.postMessage(payload);\n"
    assert not _hits("jsdes-postmessage-wildcard-target-origin", src)


# ---------- J5 : jsdes-structured-clone-untrusted-into-object-assign -----


def test_j5_structured_clone_json_parse_then_assign_flags() -> None:
    """structuredClone(JSON.parse(raw)) + Object.assign(target, ...) → HIGH hit."""
    src = (
        "function applyServerState(raw) {\n"
        "  const parsed = JSON.parse(raw);\n"
        "  const snapshot = structuredClone(parsed);\n"
        "  Object.assign(state, snapshot);\n"
        "}\n"
    )
    hits = _hits("jsdes-structured-clone-untrusted-into-object-assign", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_j5_object_assign_of_structured_clone_inline_flags() -> None:
    """Object.assign(target, structuredClone(...)) direct form → flagged."""
    src = (
        "Object.assign(state, structuredClone(JSON.parse(input)));\n"
    )
    assert _hits("jsdes-structured-clone-untrusted-into-object-assign", src)


def test_j5_websocket_clone_then_assign_flags() -> None:
    """structuredClone(incoming) wash + Object.assign(target, clone) → flagged.

    Canonical anti-pattern from the report: the developer believes
    structuredClone is a prototype-pollution safety net, but the
    resulting clone is still passed into Object.assign.
    """
    src = (
        "ws.onmessage = (e) => {\n"
        "  const incoming = JSON.parse(e.data);\n"
        "  const clone = structuredClone(incoming);\n"
        "  Object.assign(state, clone);\n"
        "};\n"
    )
    assert _hits("jsdes-structured-clone-untrusted-into-object-assign", src)


def test_j5_structured_clone_no_sink_silent() -> None:
    """structuredClone but no Object.assign / merge sink → no hit."""
    src = (
        "const snapshot = structuredClone(JSON.parse(raw));\n"
        "console.log('snapshot keys:', Object.keys(snapshot).length);\n"
    )
    assert not _hits("jsdes-structured-clone-untrusted-into-object-assign", src)


def test_j5_structured_clone_safe_input_silent() -> None:
    """structuredClone over a non-untrusted identifier → no hit."""
    # The trigger only matches structuredClone over a known-untrusted source
    # (JSON.parse(...) or event-shaped identifier). A trusted source identifier
    # such as `userConfig` does not match.
    src = (
        "const cloned = structuredClone(userConfig);\n"
        "Object.assign(state, cloned);\n"
    )
    assert not _hits("jsdes-structured-clone-untrusted-into-object-assign", src)


# ---------- J6 : jsdes-json-parse-reviver-captured-state-write -----------


def test_j6_reviver_captured_write_flags() -> None:
    """JSON.parse(raw, (k, v) => { state.role = v; ... }) → HIGH hit."""
    src = (
        "function loadState(raw) {\n"
        "  return JSON.parse(raw, (k, v) => {\n"
        "    if (k === 'role') state.role = v;\n"
        "    return v;\n"
        "  });\n"
        "}\n"
    )
    hits = _hits("jsdes-json-parse-reviver-captured-state-write", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_j6_reviver_function_expression_flags() -> None:
    """JSON.parse with `function(k, v) { ... target.role = v; }` → flagged."""
    src = (
        "const cfg = JSON.parse(remote, function (k, v) {\n"
        "  if (k === 'role') user.role = v;\n"
        "  return v;\n"
        "});\n"
    )
    assert _hits("jsdes-json-parse-reviver-captured-state-write", src)


def test_j6_reviver_pure_transform_silent() -> None:
    """Reviver that only transforms (Date revival) → no captured write → no hit."""
    src = (
        "const obj = JSON.parse(raw, (k, v) => "
        "k === 'createdAt' ? new Date(v) : v);\n"
    )
    assert not _hits("jsdes-json-parse-reviver-captured-state-write", src)


def test_j6_reviver_returns_v_unchanged_silent() -> None:
    """Reviver body that just logs and returns v → no hit."""
    src = (
        "JSON.parse(raw, (k, v) => {\n"
        "  console.log('key:', k);\n"
        "  return v;\n"
        "});\n"
    )
    assert not _hits("jsdes-json-parse-reviver-captured-state-write", src)


def test_j6_json_parse_no_reviver_silent() -> None:
    """JSON.parse without a reviver → no hit."""
    src = "const data = JSON.parse(raw);\n"
    assert not _hits("jsdes-json-parse-reviver-captured-state-write", src)


# ---------- Cross-cutting: scan_text returns Findings (not raise) ---------


def test_scan_text_returns_list_on_binary_garbage() -> None:
    """scan_text must never raise — even on unusual input."""
    src = "\x00\xff\x01\x02 random binary garbage\nno match here\n"
    findings = jdp.scan_text(src)
    assert isinstance(findings, list)


def test_scan_text_all_rules_produce_a_hit_in_a_combined_fixture() -> None:
    """Compound fixture exercises every rule once."""
    src = (
        # J1
        "ws.onmessage = (e) => { const d = JSON.parse(e.data); use(d); };\n"
        # J2
        "const stored = JSON.parse(localStorage.getItem('x'));\n"
        "setState((prev) => ({ ...prev, ...stored }));\n"
        # J3
        "window.addEventListener('message', (event) => { run(event.data); });\n"
        # J4
        "popup.postMessage(token, '*');\n"
        # J5
        "const snap = structuredClone(JSON.parse(raw));\n"
        "Object.assign(state, snap);\n"
        # J6
        "JSON.parse(payload, (k, v) => { if (k==='r') user.r = v; return v; });\n"
    )
    findings = jdp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    expected = {
        "jsdes-ws-event-data-json-parse-no-schema",
        "jsdes-storage-parse-into-state-spread",
        "jsdes-window-message-listener-no-origin-check",
        "jsdes-postmessage-wildcard-target-origin",
        "jsdes-structured-clone-untrusted-into-object-assign",
        "jsdes-json-parse-reviver-captured-state-write",
    }
    missing = expected - rule_ids
    assert not missing, f"missing hits for: {missing}"
