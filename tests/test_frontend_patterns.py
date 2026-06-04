"""Tests for ``scripts/lib/frontend_patterns.py``.

Wave 17 impl-z — verifies the 11 TS/TSX/JSX/Vue/Svelte attack-pattern
rules each have a positive + (1–2) negative tests. Pure-stdlib pytest;
no third-party fixtures. Mirrors the conventions used by
``tests/test_per_language_patterns.py`` and
``tests/test_agent_config_patterns.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make ``scripts/lib`` importable without packaging — same trick used by
# every other ``test_*_patterns.py`` in this repo.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

import frontend_patterns as fp  # noqa: E402

# ---- Helper -------------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[fp.Finding]:
    """Return only findings of ``rule_id`` from ``scan_text(text)``."""
    return [f for f in fp.scan_text(text) if f.rule_id == rule_id]


# ---- Module-level invariants -------------------------------------------


def test_rules_have_unique_ids() -> None:
    """Every Rule.id is unique — duplicates would dedupe-collide."""
    ids = [r.id for r in fp.RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


def test_rules_have_compiled_patterns() -> None:
    """Every Rule.pattern is a compiled regex with IGNORECASE+MULTILINE."""
    import re
    for rule in fp.RULES:
        assert isinstance(rule.pattern, re.Pattern), rule.id
        assert rule.pattern.flags & re.IGNORECASE, rule.id
        assert rule.pattern.flags & re.MULTILINE, rule.id


def test_rules_have_valid_severity() -> None:
    """Severity is one of the four canonical strings."""
    allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in fp.RULES:
        assert rule.severity in allowed, f"{rule.id}: {rule.severity}"


def test_rules_have_owasp_mapping() -> None:
    """Every rule maps to an OWASP-ASI identifier."""
    for rule in fp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id


def test_scan_empty_returns_empty() -> None:
    """Empty input returns empty findings list."""
    assert fp.scan_text("") == []
    assert fp.scan_text("\n\n") == []


def test_rules_count_matches_proposals() -> None:
    """We implemented 11 rules covering the 10 distill3-f proposals
    (the Angular proposal is split into bypass-call + template-binding,
    yielding 11 total)."""
    assert len(fp.RULES) == 11


def test_finding_namedtuple_shape() -> None:
    """Finding has the same 7 fields as agent_config_patterns.Finding."""
    f = fp.Finding(
        rule_id="x", line=1, column=1, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-06",
    )
    assert f.rule_id == "x"
    assert f.line == 1
    assert f.column == 1
    assert f.severity == "HIGH"


# ---- Rule 1: React dangerouslySetInnerHTML -----------------------------


def test_react_danger_html_identifier_positive() -> None:
    """dangerouslySetInnerHTML with a bare identifier RHS is flagged."""
    src = """
    function Post({ content }) {
      return <div dangerouslySetInnerHTML={{ __html: content }} />;
    }
    """
    assert _hits("react-dangerously-set-inner-html-untrusted", src)


def test_react_danger_html_member_access_positive() -> None:
    """dangerouslySetInnerHTML with member-access RHS (post.body) is flagged."""
    src = """
    <article dangerouslySetInnerHTML={{ __html: post.body }} />
    """
    assert _hits("react-dangerously-set-inner-html-untrusted", src)


def test_react_danger_html_dompurify_negative() -> None:
    """DOMPurify.sanitize(content) inline → NOT flagged."""
    src = """
    <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(content) }} />
    """
    assert not _hits("react-dangerously-set-inner-html-untrusted", src)


def test_react_danger_html_string_literal_negative() -> None:
    """A string-literal RHS is static-html and not flagged."""
    src = """
    <div dangerouslySetInnerHTML={{ __html: "<b>static</b>" }} />
    """
    assert not _hits("react-dangerously-set-inner-html-untrusted", src)


def test_react_danger_html_multi_space_literal_negative() -> None:
    """Multi-space ``__html:   "static"`` must not bypass the literal
    gate via ``\\s*`` backtracking — defensive test for the lookahead
    anchor documented in the source-module docstring."""
    src = """
    <div dangerouslySetInnerHTML={{ __html:   "<b>static</b>" }} />
    """
    assert not _hits("react-dangerously-set-inner-html-untrusted", src)


# ---- Rule 2: Vue v-html ------------------------------------------------


def test_vue_v_html_identifier_positive() -> None:
    """<p v-html="message"> with identifier RHS is flagged."""
    src = """
    <template>
      <p v-html="message"></p>
    </template>
    """
    assert _hits("vue-v-html-untrusted", src)


def test_vue_v_html_store_state_positive() -> None:
    """v-html bound to $store.state.x is flagged."""
    src = """
    <div v-html="$store.state.userBio"></div>
    """
    assert _hits("vue-v-html-untrusted", src)


def test_vue_domprops_innerhtml_positive() -> None:
    """Vue 2 render-function domProps: { innerHTML: ident } is flagged."""
    src = """
    return h('div', { domProps: { innerHTML: rawHtml } }, []);
    """
    assert _hits("vue-v-html-untrusted", src)


def test_vue_v_html_static_html_negative() -> None:
    """v-html="<b>static</b>" (leading '<') is NOT flagged."""
    src = """
    <div v-html="<b>static</b>"></div>
    """
    assert not _hits("vue-v-html-untrusted", src)


# ---- Rule 3: Angular bypassSecurityTrust* ------------------------------


def test_angular_bypass_html_positive() -> None:
    """bypassSecurityTrustHtml call is flagged."""
    src = """
    constructor(private sanitizer: DomSanitizer) {}
    safe() { return this.sanitizer.bypassSecurityTrustHtml(this.rawInput); }
    """
    assert _hits("angular-bypass-security-trust-html", src)


def test_angular_bypass_script_positive() -> None:
    """bypassSecurityTrustScript (RCE-class) is flagged."""
    src = """
    this.sanitizer.bypassSecurityTrustScript(userScript);
    """
    assert _hits("angular-bypass-security-trust-html", src)


def test_angular_bypass_resource_url_positive() -> None:
    """bypassSecurityTrustResourceUrl (RCE-class via iframe src) is flagged."""
    src = """
    this.sanitizer.bypassSecurityTrustResourceUrl(externalUrl);
    """
    assert _hits("angular-bypass-security-trust-html", src)


def test_angular_no_bypass_call_negative() -> None:
    """A regular sanitize call is NOT flagged."""
    src = """
    this.sanitizer.sanitize(SecurityContext.HTML, content);
    """
    assert not _hits("angular-bypass-security-trust-html", src)


# ---- Rule 4: Angular [innerHTML] binding -------------------------------


def test_angular_inner_html_binding_positive() -> None:
    """[innerHTML]="someVar" (identifier RHS) is flagged."""
    src = """
    <div [innerHTML]="content"></div>
    """
    assert _hits("angular-inner-html-binding-untrusted", src)


def test_angular_inner_html_binding_static_negative() -> None:
    """[innerHTML]="<b>x</b>" (leading '<') is NOT flagged."""
    src = """
    <div [innerHTML]="<b>x</b>"></div>
    """
    assert not _hits("angular-inner-html-binding-untrusted", src)


# ---- Rule 5: Svelte {@html ...} -----------------------------------------


def test_svelte_at_html_identifier_positive() -> None:
    """{@html post.body} with identifier RHS is flagged."""
    src = """
    <article>
      {@html post.body}
    </article>
    """
    assert _hits("svelte-at-html-untrusted", src)


def test_svelte_at_html_function_call_positive() -> None:
    """{@html getMarkdown(user)} (function call) is flagged."""
    src = """
    {@html getMarkdown(user.about)}
    """
    assert _hits("svelte-at-html-untrusted", src)


def test_svelte_at_html_string_literal_negative() -> None:
    """{@html "static html"} (pure string-literal) is NOT flagged."""
    src = """
    {@html "<b>static</b>"}
    """
    assert not _hits("svelte-at-html-untrusted", src)


def test_svelte_at_html_multi_space_literal_negative() -> None:
    """Multi-space `{@html  "static"}` must not bypass the literal gate
    via ``\\s+`` backtracking — defensive test for the lookahead anchor
    documented in the source-module docstring."""
    src = """
    {@html  "still static"}
    """
    assert not _hits("svelte-at-html-untrusted", src)


# ---- Rule 6: Next.js Server Action -------------------------------------


def test_nextjs_use_server_double_quote_positive() -> None:
    """A file starting with the 'use server' directive is flagged."""
    src = '"use server"\n\nexport async function createPost(formData) { … }'
    assert _hits("nextjs-server-action-no-csrf", src)


def test_nextjs_use_server_single_quote_positive() -> None:
    """A file starting with 'use server' (single quotes) is flagged."""
    src = "'use server';\n\nexport async function deletePost(id) { … }"
    assert _hits("nextjs-server-action-no-csrf", src)


def test_nextjs_no_use_server_negative() -> None:
    """A regular client component is NOT flagged."""
    src = """
    export default function Page() {
      return <div>hello</div>;
    }
    """
    assert not _hits("nextjs-server-action-no-csrf", src)


def test_nextjs_use_client_negative() -> None:
    """The 'use client' directive is the OPPOSITE of 'use server' and NOT flagged."""
    src = "'use client';\n\nexport default function Page() { … }"
    assert not _hits("nextjs-server-action-no-csrf", src)


# ---- Rule 7: Prototype-pollution carriers ------------------------------


def test_proto_pollution_object_assign_json_parse_positive() -> None:
    """Object.assign(target, JSON.parse(input)) is flagged."""
    src = """
    const target = {};
    Object.assign(target, JSON.parse(req.body.payload));
    """
    assert _hits("prototype-pollution-object-assign-json-parse", src)


def test_proto_pollution_object_assign_req_body_positive() -> None:
    """Object.assign(target, req.body) is flagged."""
    src = """
    app.post('/u', (req, res) => {
      Object.assign(target, req.body);
    });
    """
    assert _hits("prototype-pollution-object-assign-json-parse", src)


def test_proto_pollution_reflective_json_positive() -> None:
    """obj[userKey] = JSON.parse(input) generic reflective write is flagged."""
    src = """
    cache[req.query.key] = JSON.parse(req.body.value);
    """
    assert _hits("prototype-pollution-object-assign-json-parse", src)


def test_proto_pollution_object_create_null_negative() -> None:
    """Object.assign(Object.create(null), JSON.parse(x)) — null prototype target — NOT flagged."""
    src = """
    const target = Object.create(null);
    Object.assign(Object.create(null), JSON.parse(input));
    """
    assert not _hits("prototype-pollution-object-assign-json-parse", src)


# ---- Rule 8: eval / new Function / setTimeout with template literal ----


def test_eval_template_literal_positive() -> None:
    """eval(`doX(${user.input})`) is flagged."""
    src = """
    const action = eval(`doX(${user.input})`);
    """
    assert _hits("js-eval-or-function-with-template-literal", src)


def test_new_function_template_positive() -> None:
    """new Function('args', `return ${userExpr}`) is flagged."""
    src = """
    const fn = new Function('a', `return ${userExpr};`);
    """
    assert _hits("js-eval-or-function-with-template-literal", src)


def test_settimeout_string_template_positive() -> None:
    """setTimeout(`runAction(${user})`, 0) is flagged."""
    src = """
    setTimeout(`runAction(${user})`, 0);
    """
    assert _hits("js-eval-or-function-with-template-literal", src)


def test_eval_regular_string_negative() -> None:
    """new Function('module', 'return import(module)') (regular literal) is NOT flagged."""
    src = """
    const fn = new Function('module', 'return import(module)');
    """
    assert not _hits("js-eval-or-function-with-template-literal", src)


def test_settimeout_callback_negative() -> None:
    """setTimeout(() => doX(user), 0) (callback form) is NOT flagged."""
    src = """
    setTimeout(() => doX(user), 0);
    """
    assert not _hits("js-eval-or-function-with-template-literal", src)


# ---- Rule 9: TypeScript `as any` reflective write ----------------------


def test_ts_as_any_reflective_write_positive() -> None:
    """(obj as any)[userKey] = value is flagged."""
    src = """
    (target as any)[req.body.key] = req.body.value;
    """
    assert _hits("ts-as-any-reflective-write", src)


def test_ts_old_style_any_cast_positive() -> None:
    """(<any>obj)[userKey] = value (legacy cast) is flagged."""
    src = """
    (<any>target)[userKey] = value;
    """
    assert _hits("ts-as-any-reflective-write", src)


def test_ts_as_any_string_literal_key_negative() -> None:
    """(obj as any)['knownKey'] = value (string-literal key) is NOT flagged."""
    src = """
    (target as any)['knownKey'] = value;
    """
    assert not _hits("ts-as-any-reflective-write", src)


# ---- Rule 10: JSON.parse reviver with eval -----------------------------


def test_json_parse_reviver_with_eval_positive() -> None:
    """JSON.parse(input, function(k,v) { eval(v) }) is flagged."""
    src = """
    const obj = JSON.parse(payload, function (k, v) {
      return eval(v);
    });
    """
    assert _hits("json-parse-reviver-with-eval", src)


def test_json_parse_reviver_with_new_function_positive() -> None:
    """JSON.parse(input, (k,v) => { new Function(v)() }) is flagged."""
    src = """
    const obj = JSON.parse(payload, (k, v) => {
      const fn = new Function(v);
      return fn();
    });
    """
    assert _hits("json-parse-reviver-with-eval", src)


def test_json_parse_no_reviver_negative() -> None:
    """JSON.parse(input) without a reviver is NOT flagged."""
    src = """
    const obj = JSON.parse(payload);
    """
    assert not _hits("json-parse-reviver-with-eval", src)


def test_json_parse_safe_reviver_negative() -> None:
    """A reviver that only does identity transforms is NOT flagged."""
    src = """
    const obj = JSON.parse(payload, function (k, v) {
      if (k === 'date') return new Date(v);
      return v;
    });
    """
    assert not _hits("json-parse-reviver-with-eval", src)


# ---- Rule 11: Object.defineProperty untrusted key ----------------------


def test_object_defineproperty_identifier_key_positive() -> None:
    """Object.defineProperty(obj, userKey, desc) (identifier key) is flagged."""
    src = """
    Object.defineProperty(target, userInput, { value: 1 });
    """
    assert _hits("js-object-defineproperty-untrusted-key", src)


def test_reflect_defineproperty_identifier_positive() -> None:
    """Reflect.defineProperty(obj, userKey, desc) is flagged."""
    src = """
    Reflect.defineProperty(target, req.body.key, { value: payload });
    """
    assert _hits("js-object-defineproperty-untrusted-key", src)


def test_object_defineproperty_string_key_negative() -> None:
    """Object.defineProperty(obj, 'safe', desc) (string-literal key) is NOT flagged."""
    src = """
    Object.defineProperty(target, 'safe', { value: 1 });
    """
    assert not _hits("js-object-defineproperty-untrusted-key", src)


# ---- scan_text dedup + sort properties ---------------------------------


def test_scan_text_dedup_same_rule_same_position() -> None:
    """Findings deduped by (rule_id, line, col) — the regex fires once."""
    src = "<div dangerouslySetInnerHTML={{ __html: content }} />"
    findings = fp.scan_text(src)
    rule_id = "react-dangerously-set-inner-html-untrusted"
    matches_here = [f for f in findings if f.rule_id == rule_id]
    # Single occurrence at line 1 → exactly one Finding.
    assert len(matches_here) == 1


def test_scan_text_sorted_by_line_col() -> None:
    """Findings are sorted by (line, column, rule_id) for reproducibility."""
    src = """
    Object.assign(target, JSON.parse(req.body.x));
    (target as any)[userKey] = 1;
    """
    findings = fp.scan_text(src)
    for prev, nxt in zip(findings, findings[1:]):
        assert (prev.line, prev.column, prev.rule_id) <= (nxt.line, nxt.column, nxt.rule_id)


def test_scan_text_truncates_long_match() -> None:
    """A long match is truncated to ≤201 chars with the ellipsis marker."""
    long_body = "x" * 300
    src = f"<div dangerouslySetInnerHTML={{{{ __html: {long_body} }}}} />"
    findings = fp.scan_text(src)
    rule_id = "react-dangerously-set-inner-html-untrusted"
    matches_here = [f for f in findings if f.rule_id == rule_id]
    # The match should fire — but the matched_text payload is capped.
    assert matches_here
    assert len(matches_here[0].matched_text) <= 201
    assert matches_here[0].matched_text.endswith("…")
