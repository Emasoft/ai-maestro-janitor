"""Tests for scripts/lib/embedded_scripting_patterns.py.

Pattern-coverage tests for the Wave-26 distill-round-12 embedded-scripting
catalogue (7 anti-patterns covering Lua / Tcl / QuickJS / GraalJS / V8
isolate / Node vm-family / Jinja SSTI / Python eval-family / deferred-eval
inside YAML or Nginx or Envoy configs). Each rule has at least one
positive test exercising the canary AND at least one negative test
exercising the FP suppression baseline.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import embedded_scripting_patterns as esp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(esp.RULES, tuple)
    rule_ids = {r.id for r in esp.RULES}
    expected = {
        "embedded-scripting-lua-loadstring-untrusted",
        "embedded-scripting-node-vm-untrusted-source",
        "embedded-scripting-template-ssti-user-source",
        "embedded-scripting-js-engine-host-binding-exposure",
        "embedded-scripting-tcl-eval-untrusted",
        "embedded-scripting-python-eval-exec-builtins-leak",
        "embedded-scripting-config-deferred-eval",
    }
    assert expected == rule_ids
    assert len(esp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in esp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = esp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="CRITICAL",
        description="d",
        owasp_asi="ASI-05",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "CRITICAL"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-05"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert esp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — Lua loadstring of request body
        "local fn = loadstring(request.body)\n"
        # Line 2 — Python eval of request body
        "result = eval(request.body)\n"
    )
    findings = esp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[esp.Finding]:
    return [f for f in esp.scan_text(text) if f.rule_id == rule_id]


# ---------- ESI-001 : lua-loadstring-untrusted ---------------------------


def test_esi001_lua_loadstring_request_body_flags() -> None:
    """loadstring(http_request.body) → CRITICAL hit."""
    src = "local fn, err = loadstring(http_request.body)\n"
    hits = _hits("embedded-scripting-lua-loadstring-untrusted", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_esi001_lua_luaL_loadbuffer_untrusted_flags() -> None:
    """C-side luaL_loadbuffer(L, untrusted, ...) → hit."""
    src = 'luaL_loadbuffer(L, untrusted, len, "user");\n'
    assert _hits("embedded-scripting-lua-loadstring-untrusted", src)


def test_esi001_roblox_httpservice_metatable_flags() -> None:
    """Roblox Luau JSONDecode → setmetatable in same window → hit."""
    src = (
        "local data = HttpService:JSONDecode(remote_body)\n"
        "setmetatable(data, {__index = function(...) end})\n"
    )
    assert _hits("embedded-scripting-lua-loadstring-untrusted", src)


def test_esi001_lua_load_constant_string_not_flagged() -> None:
    """loadstring on a literal constant → no hit (no taint token)."""
    src = "local fn = loadstring('return 1 + 2')\n"
    assert not _hits("embedded-scripting-lua-loadstring-untrusted", src)


# ---------- ESI-002 : node-vm-untrusted-source ---------------------------


def test_esi002_vm_runinnewcontext_req_body_flags() -> None:
    """vm.runInNewContext(req.body.expr, ...) → CRITICAL hit."""
    src = (
        "const vm = require('node:vm');\n"
        "const result = vm.runInNewContext(req.body.expr, { input: req.body.data });\n"
    )
    hits = _hits("embedded-scripting-node-vm-untrusted-source", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_esi002_new_function_req_body_flags() -> None:
    """new Function('ctx', req.body.code) → hit."""
    src = "const fn = new Function('ctx', req.body.code);\n"
    assert _hits("embedded-scripting-node-vm-untrusted-source", src)


def test_esi002_vm2_new_vm_run_user_code_flags() -> None:
    """new VM({...}).run(userCode) → hit (VM2 May-2026 wave is audit-grade)."""
    src = (
        "const { VM } = require('vm2');\n"
        "new VM({ timeout: 1000 }).run(userCode);\n"
    )
    assert _hits("embedded-scripting-node-vm-untrusted-source", src)


def test_esi002_isolated_vm_fetch_reference_flags() -> None:
    """isolated-vm Reference(fetch) leak → hit."""
    src = (
        "const isolate = new ivm.Isolate();\n"
        "const ctx = await isolate.createContext();\n"
        "await ctx.global.set('fetch', new ivm.Reference(fetch));\n"
    )
    assert _hits("embedded-scripting-node-vm-untrusted-source", src)


def test_esi002_vm_runincontext_constant_not_flagged() -> None:
    """vm.runInNewContext over a constant string → no hit (no taint token)."""
    src = "const result = vm.runInNewContext('1 + 1', {});\n"
    assert not _hits("embedded-scripting-node-vm-untrusted-source", src)


# ---------- ESI-003 : template-ssti-user-source --------------------------


def test_esi003_flask_render_template_string_args_flags() -> None:
    """Flask render_template_string(request.args[...]) → CRITICAL hit."""
    src = (
        "from flask import render_template_string, request\n"
        "def preview():\n"
        "    return render_template_string(request.args['tmpl'])\n"
    )
    hits = _hits("embedded-scripting-template-ssti-user-source", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_esi003_jinja_environment_from_string_user_flags() -> None:
    """jinja2 Environment().from_string(user_input) → hit."""
    src = (
        "from jinja2 import Environment\n"
        "env = Environment()\n"
        "return env.from_string(user_payload).render(user=user)\n"
    )
    assert _hits("embedded-scripting-template-ssti-user-source", src)


def test_esi003_handlebars_compile_req_body_flags() -> None:
    """Handlebars.compile(req.body.template, ...) → hit."""
    src = (
        "const tmpl = Handlebars.compile(req.body.template, { noEscape: true });\n"
        "res.send(tmpl(req.body.data));\n"
    )
    assert _hits("embedded-scripting-template-ssti-user-source", src)


def test_esi003_twig_arrayloader_post_flags() -> None:
    """Twig ArrayLoader fed from $_POST → hit."""
    src = "$env = new \\Twig\\Environment(new \\Twig\\Loader\\ArrayLoader(['user' => $_POST['tmpl']]));\n"
    assert _hits("embedded-scripting-template-ssti-user-source", src)


def test_esi003_render_template_static_path_not_flagged() -> None:
    """render_template_string with a literal local-file template → no hit."""
    src = (
        "with open('templates/welcome.j2') as fh:\n"
        "    tmpl = fh.read()\n"
        "return render_template_string(tmpl, name='alice')\n"
    )
    assert not _hits("embedded-scripting-template-ssti-user-source", src)


# ---------- ESI-004 : js-engine-host-binding-exposure --------------------


def test_esi004_quickjs_init_module_os_flags() -> None:
    """QuickJS js_init_module_os registration → CRITICAL hit."""
    src = (
        "JSRuntime *rt = JS_NewRuntime();\n"
        "JSContext *ctx = JS_NewContext(rt);\n"
        'js_init_module_os(ctx, "os");\n'
        'js_init_module_std(ctx, "std");\n'
    )
    hits = _hits("embedded-scripting-js-engine-host-binding-exposure", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_esi004_graaljs_allow_all_access_true_flags() -> None:
    """GraalJS Context.newBuilder("js").allowAllAccess(true) → hit."""
    src = (
        'Context ctx = Context.newBuilder("js")\n'
        "    .allowAllAccess(true)\n"
        "    .build();\n"
    )
    assert _hits("embedded-scripting-js-engine-host-binding-exposure", src)


def test_esi004_graaljs_host_access_all_flags() -> None:
    """GraalJS HostAccess.ALL → hit (effectively no sandbox)."""
    src = "  .allowHostAccess(HostAccess.ALL)\n"
    assert _hits("embedded-scripting-js-engine-host-binding-exposure", src)


def test_esi004_v8_no_security_token_flags() -> None:
    """V8 Context::New without SetSecurityToken anywhere in file → hit."""
    src = (
        "v8::Isolate::CreateParams params;\n"
        "auto* isolate = v8::Isolate::New(params);\n"
        "v8::Local<v8::Context> ctx = v8::Context::New(isolate);\n"
        "// no SetSecurityToken call here\n"
    )
    assert _hits("embedded-scripting-js-engine-host-binding-exposure", src)


def test_esi004_v8_with_security_token_not_flagged() -> None:
    """V8 Context::New paired with SetSecurityToken → no hit on missing-token half."""
    src = (
        "v8::Local<v8::Context> ctx = v8::Context::New(isolate);\n"
        "ctx->SetSecurityToken(token);\n"
    )
    # The missing-token path is suppressed, and there is no external-untrusted
    # binding either, so the whole rule stays silent.
    assert not _hits("embedded-scripting-js-engine-host-binding-exposure", src)


def test_esi004_quickjs_safe_init_only_not_flagged() -> None:
    """QuickJS context with no os/std/fs init → no hit."""
    src = (
        "JSRuntime *rt = JS_NewRuntime();\n"
        "JSContext *ctx = JS_NewContext(rt);\n"
        '/* no js_init_module_* call */\n'
        'JS_Eval(ctx, src, strlen(src), "user", 0);\n'
    )
    assert not _hits("embedded-scripting-js-engine-host-binding-exposure", src)


# ---------- ESI-005 : tcl-eval-untrusted ---------------------------------


def test_esi005_tcl_eval_user_var_flags() -> None:
    """Tcl `eval $user_expr` → CRITICAL hit."""
    src = (
        "package require ncgi\n"
        'set user_expr [::ncgi::value "expr"]\n'
        "eval $user_expr\n"
    )
    hits = _hits("embedded-scripting-tcl-eval-untrusted", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_esi005_tcl_evalobjex_host_buf_flags() -> None:
    """C-host Tcl_EvalObjEx on untrusted buf → hit."""
    src = (
        "Tcl_Interp *interp = Tcl_CreateInterp();\n"
        "Tcl_Obj *cmd = Tcl_NewStringObj(untrusted, -1);\n"
        "Tcl_EvalObjEx(interp, untrusted, TCL_EVAL_GLOBAL);\n"
    )
    assert _hits("embedded-scripting-tcl-eval-untrusted", src)


def test_esi005_tcl_safe_interp_alias_exec_flags() -> None:
    """`$s alias myexec exec` re-exposes master exec from a safe slave → hit."""
    src = (
        "set s [interp create -safe]\n"
        "$s alias myexec exec\n"
        "$s eval $user_input\n"
    )
    assert _hits("embedded-scripting-tcl-eval-untrusted", src)


def test_esi005_tcl_eval_literal_not_flagged() -> None:
    """`eval $constant` where the var name has no taint hint → no hit."""
    src = "eval $cmd\n"
    assert not _hits("embedded-scripting-tcl-eval-untrusted", src)


# ---------- ESI-006 : python-eval-exec-builtins-leak ---------------------


def test_esi006_python_eval_request_json_flags() -> None:
    """Bare eval(req.json[...]) → CRITICAL hit."""
    src = "result = eval(req.json['expr'])\n"
    hits = _hits("embedded-scripting-python-eval-exec-builtins-leak", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_esi006_python_exec_body_flags() -> None:
    """exec(req.body) → hit."""
    src = "exec(req.body)\n"
    assert _hits("embedded-scripting-python-eval-exec-builtins-leak", src)


def test_esi006_eval_empty_builtins_bypass_flags() -> None:
    """eval(expr, {'__builtins__': {}}, {}) → hit (known bypass)."""
    src = "result = eval(user_expr, {'__builtins__': {}}, {})\n"
    assert _hits("embedded-scripting-python-eval-exec-builtins-leak", src)


def test_esi006_restrictedpython_no_safe_globals_flags() -> None:
    """compile_restricted + exec without safe_globals/safe_builtins → hit."""
    src = (
        "from RestrictedPython import compile_restricted\n"
        'code = compile_restricted(user_src, "<user>", "exec")\n'
        "exec(code)\n"
    )
    assert _hits("embedded-scripting-python-eval-exec-builtins-leak", src)


def test_esi006_restrictedpython_with_safe_globals_not_flagged() -> None:
    """compile_restricted + exec(code, safe_globals, ...) → no hit on the
    'no-safe-globals' half (file-wide marker suppresses)."""
    src = (
        "from RestrictedPython import compile_restricted, safe_globals\n"
        'code = compile_restricted(user_src, "<user>", "exec")\n'
        "exec(code, safe_globals)\n"
    )
    # `safe_globals` token appears → Stage-B suppresses the compile_restricted
    # match. The bare `exec(code)` shape on its own line does not match the
    # taint-token Stage-A either.
    hits = _hits("embedded-scripting-python-eval-exec-builtins-leak", src)
    # The restricted-no-globals shape MUST be suppressed.
    assert not any(
        "compile_restricted" in h.matched_text for h in hits
    )


def test_esi006_asteval_user_input_flags() -> None:
    """asteval Interpreter() applied to user_expr → hit."""
    src = (
        "from asteval import Interpreter\n"
        "aeval = Interpreter()\n"
        "aeval(user_expr)\n"
    )
    assert _hits("embedded-scripting-python-eval-exec-builtins-leak", src)


def test_esi006_interactive_interpreter_llm_flags() -> None:
    """InteractiveInterpreter().runsource(llm_line) → hit (agentic shell)."""
    src = (
        "from code import InteractiveInterpreter\n"
        "interp = InteractiveInterpreter()\n"
        "for line in llm_response.splitlines():\n"
        "    interp.runsource(llm_response)\n"
    )
    assert _hits("embedded-scripting-python-eval-exec-builtins-leak", src)


def test_esi006_eval_static_literal_not_flagged() -> None:
    """eval('1+1') over a literal → no hit (no taint source)."""
    src = "result = eval('1+1')\n"
    assert not _hits("embedded-scripting-python-eval-exec-builtins-leak", src)


# ---------- ESI-007 : config-deferred-eval -------------------------------


def test_esi007_gha_pull_request_title_in_run_flags() -> None:
    """GHA `run:` block with ${{ github.event.pull_request.title }} → hit."""
    src = (
        "- name: Run Lua transform\n"
        "  run: |\n"
        "    lua -e '${{ github.event.pull_request.title }}'\n"
    )
    hits = _hits("embedded-scripting-config-deferred-eval", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_esi007_gha_issue_body_in_run_flags() -> None:
    """GHA `run:` with ${{ github.event.issue.body }} → hit."""
    src = (
        "- name: Echo issue\n"
        "  run: |\n"
        "    echo '${{ github.event.issue.body }}'\n"
    )
    assert _hits("embedded-scripting-config-deferred-eval", src)


def test_esi007_gha_head_ref_in_run_flags() -> None:
    """GHA `run:` with ${{ github.head_ref }} → hit."""
    src = (
        "- name: Checkout\n"
        "  run: |\n"
        "    git checkout '${{ github.head_ref }}'\n"
    )
    assert _hits("embedded-scripting-config-deferred-eval", src)


def test_esi007_envoy_lua_header_loadstring_flags() -> None:
    """Envoy Lua HTTP filter loading user header into loadstring → hit."""
    src = (
        "http_filters:\n"
        "- name: envoy.filters.http.lua\n"
        "  typed_config:\n"
        '    "@type": type.googleapis.com/envoy.extensions.filters.http.lua.v3.Lua\n'
        "    inline_code: |\n"
        "      function envoy_on_request(handle)\n"
        '        local h = handle:headers():get("x-user-script")\n'
        "        loadstring(h)()\n"
        "      end\n"
    )
    assert _hits("embedded-scripting-config-deferred-eval", src)


def test_esi007_nginx_lua_arg_loadstring_flags() -> None:
    """Nginx content_by_lua_block compiling ngx.var.arg_code → hit."""
    src = (
        "location /run {\n"
        "  content_by_lua_block {\n"
        "    local user = ngx.var.arg_code\n"
        "    local fn = loadstring(user)\n"
        "    fn()\n"
        "  }\n"
        "}\n"
    )
    assert _hits("embedded-scripting-config-deferred-eval", src)


def test_esi007_gha_immutable_sha_not_flagged() -> None:
    """GHA `run:` with ${{ github.sha }} (immutable) → no hit."""
    src = (
        "- name: Tag\n"
        "  run: |\n"
        "    echo '${{ github.sha }}'\n"
    )
    assert not _hits("embedded-scripting-config-deferred-eval", src)
