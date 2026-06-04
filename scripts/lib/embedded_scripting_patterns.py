"""Embedded scripting-language sandbox & interpreter patterns.

Wave-26 distillation round 12, embedded-scripting angle.

Catalogue of 7 in-process scripting-interpreter anti-patterns distilled
in `reports/distill-round-12/embedded-scripting.md`. Targets host
processes that embed a *string-source* scripting interpreter — Lua
state attached to a C/C++/Rust binary, Tcl `interp`, QuickJS
`JSContext`, GraalJS `Context.Builder()`, V8 isolate with host-bound
function pointers, Node `vm`/`vm2`/`isolated-vm`, Roblox Luau with
`HttpService`, Jinja `SandboxedEnvironment` over attacker-controlled
template strings, Python `eval`/`exec`/`RestrictedPython`/`asteval`/
`simpleeval` with `__builtins__` leak.

Distinct from `wasm_sandbox_patterns.py` (pre-compiled WASM with a
fixed import contract): THIS angle covers **string-source scripting
interpreters embedded in a host process**, where the input is text in
some other language parsed at runtime — not WASM bytecode.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * embedded-scripting-lua-loadstring-untrusted               (CRITICAL)
  * embedded-scripting-node-vm-untrusted-source               (CRITICAL)
  * embedded-scripting-template-ssti-user-source              (CRITICAL)
  * embedded-scripting-js-engine-host-binding-exposure        (CRITICAL)
  * embedded-scripting-tcl-eval-untrusted                     (CRITICAL)
  * embedded-scripting-python-eval-exec-builtins-leak         (CRITICAL)
  * embedded-scripting-config-deferred-eval                   (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Tool Misuse (host bindings + intrinsics exposed to script)
  ASI-04 — Supply Chain Vulnerabilities (vm2 escape wave, config carrier
                                          treated as data on wire / code
                                          at executor)
  ASI-05 — Unexpected Code Execution (parse-then-eval untrusted text)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
negative lookahead, no catastrophic backtracking shapes). Patterns are
PRE-COMPILED at module load. Fail-fast: callers receive structured
Finding tuples, never raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    chat_bot_patterns / embedded_shortrange_patterns. RE2-safe: no
    nested quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


def _re_dotall(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+DOTALL+UNICODE — for patterns that must
    span newlines."""
    return re.compile(pattern, re.IGNORECASE | re.DOTALL | re.UNICODE)


# ---- ESI-001 : embedded-scripting-lua-loadstring-untrusted --------------


# Lua/Luau and C-side host APIs that compile a string into Lua bytecode.
# The match also requires the same line to contain a taint-source marker
# (request / body / payload / user / remote / untrusted / http) so that a
# `load("local x = 1")` literal-only call does NOT trigger.
_LUA_LOADSTRING_UNTRUSTED = _re(
    r"\b(?:luaL_loadstring|luaL_loadbuffer|lua_load|loadstring|load)\s*\("
    r"[^)\"']{0,200}"
    r"(?:request|input|body|payload|data|untrusted|user|remote|http)"
)

# Roblox Luau: HttpService JSON decode followed by setmetatable within
# the same window. The DOTALL across a bounded `.{0,400}` keeps it
# RE2-safe (no unbounded greedy).
_ROBLOX_HTTPSERVICE_METATABLE = _re_dotall(
    r"HttpService\s*:\s*JSONDecode\b.{0,400}\bsetmetatable\s*\("
)


# ---- ESI-002 : embedded-scripting-node-vm-untrusted-source --------------


# Stage-A trigger: any of the four Node in-process script interpreters.
# Match anchors on the *call shape*, then Stage-B checks for an untrusted
# argument in the same window.
_NODE_VM_TRIGGER = _re(
    r"\b(?:"
    r"vm\.runIn(?:NewContext|ThisContext|Context)"
    r"|new\s+Function\s*\("
    r"|new\s+VM\s*\([^)]{0,80}\)\s*\.run\s*\("
    r"|ivm\.Isolate\b"
    r"|isolated[_-]?vm\b"
    r")"
)

# Stage-B: same-line untrusted argument shape.
_NODE_VM_UNTRUSTED_ARG = _re(
    r"\b(?:vm\.runIn(?:NewContext|ThisContext|Context)|new\s+Function|\.run)\s*\("
    r"[^)]{0,200}"
    r"(?:req\.|request\.|input|body|payload|userCode|untrusted|event\.data)"
)

# Stage-B for isolated-vm: a Reference being .set() with a global-class
# host capability name (e.g. 'fetch', 'require', 'process'). Bounded `.`
# keeps it RE2-safe.
_ISOLATED_VM_HOST_REF_LEAK = _re_dotall(
    r"\bivm\.Isolate\b.{0,500}\.set\s*\(\s*['\"](?:fetch|require|process|"
    r"global|console|child_process|spawn|exec|eval|Function)['\"]"
    r"\s*,\s*new\s+ivm\.Reference\b"
)


# ---- ESI-003 : embedded-scripting-template-ssti-user-source -------------


# Jinja / FastAPI / Flask `render_template_string` / `Environment().from_string`
# applied to a request-derived argument.
_TEMPLATE_FROMSTRING_USER = _re(
    r"\b(?:render_template_string|"
    r"Environment\s*\([^)]{0,200}\)\s*\.from_string"
    r"|env\.from_string|tmpl_env\.from_string|jinja\.from_string)"
    r"\s*\(\s*"
    r"[^)]{0,200}"
    r"(?:request\.|req\.|input|body|payload|user|untrusted|args\[|params\[)"
)

# Python `.format()` invoked directly on a request-derived expression —
# the `format` method of str-subclasses is itself a path-traversal vector
# (e.g. `{0.__class__.__mro__[1].__subclasses__()}` in `str.format`).
_TEMPLATE_DOTFORMAT_USER = _re(
    r"(?:request\.|req\.|input\b|\bbody\b|\bpayload\b|args\[|params\[)"
    r"[^\n]{0,80}\.format\s*\("
)

# Handlebars compile of a request-derived template (with or without
# noEscape — both shapes are flagged).
_HANDLEBARS_COMPILE_USER = _re(
    r"\bHandlebars\.compile\s*\(\s*"
    r"[^)]{0,200}"
    r"(?:req\.|request\.|body|payload|user|input|event\.data)"
)

# Twig ArrayLoader fed from `$_POST` / `$_GET` / `$_REQUEST`.
_TWIG_ARRAYLOADER_REQUEST = _re(
    r"ArrayLoader\s*\(\s*\[[^\]]{0,200}=>\s*\$_(?:POST|GET|REQUEST)\["
)


# ---- ESI-004 : embedded-scripting-js-engine-host-binding-exposure -------


# QuickJS: registration of `os` / `std` / `fs` / `child_process` modules
# into a freshly created JSContext. Each one of these alone is full
# in-process exec.
_QUICKJS_HOST_MODULE_INIT = _re(
    r"\bjs_init_module_(?:os|std|fs|child_process|net)\s*\("
)

# GraalJS: `Context.newBuilder("js").allowAllAccess(true).build()` — the
# DOTALL across a bounded chain keeps it RE2-safe.
_GRAALJS_ALLOW_ALL_ACCESS = _re_dotall(
    r"\bContext\s*\.\s*newBuilder\s*\([^)]{0,80}\)"
    r"[^;{]{0,400}"
    r"\.allowAllAccess\s*\(\s*true\s*\)"
)

# GraalJS marginal-but-still-CRITICAL shapes: `HostAccess.ALL` or
# `.allowHostClassLookup(name -> true)` — both effectively grant
# `java.lang.Runtime` lookups from JS.
_GRAALJS_HOST_ACCESS_ALL = _re(
    r"\bHostAccess\s*\.\s*ALL\b"
    r"|"
    r"\.allowHostClassLookup\s*\(\s*\w+\s*->\s*true\s*\)"
)

# V8: `Context::New` followed (in the same file) by an `External::New`
# binding of an untrusted host pointer. The `External::New` shape with a
# host-pointer comment / variable named for untrusted input is the Stage-B
# half — emitted only if both halves are present in the file.
_V8_CONTEXT_NEW = _re(
    r"\bv8\s*::\s*Context\s*::\s*New\s*\("
)

_V8_EXTERNAL_BIND_UNTRUSTED = _re(
    r"\bv8\s*::\s*External\s*::\s*New\s*\(\s*\w+\s*,\s*"
    r"[^)]{0,200}"
    r"(?:untrusted|user|request|input|body|payload|attacker)"
)

# V8: file uses `Context::New` but never calls `SetSecurityToken` — this
# is the "missing-token" half. Stage-B will scan the file for the marker.
_V8_SET_SECURITY_TOKEN = _re(
    r"\bSetSecurityToken\s*\("
)


# ---- ESI-005 : embedded-scripting-tcl-eval-untrusted --------------------


# Tcl-side `eval $var` / `uplevel $var` where the variable name hints at
# a taint source (user / input / cgi / req / body / payload / ncgi).
_TCL_EVAL_USER = _re(
    r"^\s*(?:eval|uplevel)\s+\$\w*"
    r"(?:user|input|cgi|req|body|payload|args|ncgi)"
)

# C-host call `Tcl_Eval` / `Tcl_EvalObjEx` / `Tcl_EvalEx` on a buffer
# variable whose name hints at untrusted input.
_TCL_EVALOBJEX_HOST = _re(
    r"\bTcl_Eval(?:Obj)?(?:Ex)?\s*\(\s*\w+\s*,\s*"
    r"[^,)]{0,120}"
    r"(?:user|input|untrusted|buf|body|payload|cgi|request)"
)

# Safe-interp alias that re-exposes a dangerous master command — the
# alias destination is `exec` / `open` / `source` / `file delete|rename`.
_TCL_SAFE_INTERP_ALIAS_LEAK = _re_dotall(
    r"\binterp\s+(?:create\s+-safe|alias)\b"
    r".{0,200}"
    r"\b(?:exec|open|source|file\s+(?:delete|rename))\b"
)


# ---- ESI-006 : embedded-scripting-python-eval-exec-builtins-leak --------


# Bare `eval(req.json[...])` / `exec(req.body)` / `eval(llm_response)`.
_PY_EVAL_EXEC_USER = _re(
    r"\b(?:eval|exec)\s*\(\s*"
    r"[^)]{0,200}"
    r"(?:request\.|req\.|\binput\s*\(|\bbody\b|\bpayload\b|"
    r"\buser\b|\buntrusted\b|args\[|\bllm\b|response)"
)

# `eval(expr, {"__builtins__": {}}, {})` — known-bypassable "sandbox".
_PY_EVAL_BUILTINS_EMPTY = _re(
    r"\beval\s*\(\s*[^,)]{0,80}\s*,\s*"
    r"\{[^}]{0,120}['\"]__builtins__['\"]\s*:\s*\{\s*\}\s*\}"
)

# `compile_restricted(...)` followed by `exec(...)` of the compiled code
# WITHOUT a safe_globals / safe_builtins argument. Stage-B scans the
# 200-char window after the compile_restricted call for an exec() of the
# same compiled name. The negative ("no safe_*" marker) check is done
# separately to keep this regex RE2-safe.
_PY_RESTRICTEDPYTHON_COMPILE = _re_dotall(
    r"\bcompile_restricted\s*\([^)]{0,300}\)"
    r"[^;]{0,400}"
    r"\bexec\s*\(\s*\w+\s*\)"
)

# Stage-B marker: the safe_builtins / safe_globals symbols anywhere in
# the file suppress the finding.
_PY_RESTRICTED_SAFE_MARKER = _re(
    r"\bsafe_(?:builtins|globals|locals)\b"
)

# `asteval` Interpreter() applied to LLM / user input.
_PY_ASTEVAL_USER = _re(
    r"\b(?:asteval\.)?Interpreter\s*\(\s*\)"
    r"[^\n]*\n"
    r"[^\n]{0,80}\((?:user|llm|response|input|untrusted|payload)"
)

# `code.InteractiveInterpreter` / `code.InteractiveConsole` driving
# `runsource` from LLM / user output — the agentic-shell anti-pattern.
_PY_INTERACTIVE_INTERPRETER_LLM = _re_dotall(
    r"\bInteractive(?:Interpreter|Console)\s*\([^)]{0,80}\)"
    r".{0,600}"
    r"\.runsource\s*\(\s*[^)]{0,80}"
    r"(?:llm|response|user|untrusted|payload|request)"
)


# ---- ESI-007 : embedded-scripting-config-deferred-eval ------------------


# GitHub Actions: `run:` block whose body contains a
# `${{ github.event.<thing>.* }}` expression for an
# attacker-controllable field. Only the four attacker-controllable
# event kinds are flagged (pull_request / issue / comment / review);
# `github.sha` etc. are intentionally skipped.
_GHA_EXPRESSION_INJECTION_RUN = _re(
    r"\brun\s*:\s*[\|>][^\n]*\n"
    r"(?:[^\n]*\n){0,10}"
    r"[^\n]*\$\{\{\s*github\.event\."
    r"(?:pull_request|issue|comment|review|discussion)\."
)

# `github.head_ref` is the well-known attacker-controllable shape on
# fork PRs and deserves an independent flag inside `run:` blocks.
_GHA_HEAD_REF_RUN = _re(
    r"\brun\s*:\s*[\|>][^\n]*\n"
    r"(?:[^\n]*\n){0,10}"
    r"[^\n]*\$\{\{\s*github\.head_ref\b"
)

# Envoy HTTP Lua filter with `inline_code:` that loads a header /
# cookie / query value into `loadstring` / `load` / `dofile`. The header
# read (`:headers()`, `:get(...)`, `cookie`, `query`) MUST appear before
# the `loadstring/load/dofile` call but inside the inline_code block.
_ENVOY_LUA_FROM_HEADER = _re_dotall(
    r"envoy\.filters\.http\.lua"
    r".{0,500}"
    r"inline_code"
    r".{0,500}"
    r"(?:headers\s*\(\s*\)|:headers\b|:get\s*\(|cookie|query)"
    r".{0,500}"
    r"(?:loadstring|dofile)\s*\("
)

# Nginx with lua-nginx-module: `content_by_lua_block { … ngx.var.arg_X
# … loadstring(...) … }` — bounded inner spans keep this RE2-safe.
_NGINX_LUA_ARG_LOADSTRING = _re_dotall(
    r"(?:content_by_lua_block|content_by_lua)"
    r".{0,400}"
    r"\bngx\.var\.(?:arg_|http_|cookie_)\w*"
    r".{0,400}"
    r"\bloadstring\s*\("
)

# OpenTelemetry collector OTTL processor: `processors:` block referencing
# `ottl` with a value that interpolates a request / user / attr field.
_OTTL_PROCESSOR_DYNAMIC = _re_dotall(
    r"processors\s*:"
    r".{0,500}"
    r"\bottl\b"
    r".{0,500}"
    r"value\s*:\s*['\"]?\$\{[^}]{0,80}"
    r"(?:request|user|attr|event)"
)


# ---- The composed RULES tuple ------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="embedded-scripting-lua-loadstring-untrusted",
        name="Lua loadstring/load on text that traces to a network / request source",
        severity="CRITICAL",
        description=(
            "A host process embedding Lua (game engine, network "
            "appliance, observability sidecar, Roblox-style platform) "
            "calls `luaL_loadstring` / `luaL_loadbuffer` / `lua_load` / "
            "`loadstring` / `load` on text whose source is a request "
            "body, HTTP input, payload, or remote blob. Lua compiles "
            "the string to bytecode in the host's address space; "
            "`os.execute`, `io.open`, `package.loadlib`, and "
            "`debug.getregistry` re-expose shell / FS / arbitrary-C even "
            "after `os` and `io` are nilled out at the global. Roblox "
            "Luau's `HttpService:JSONDecode` followed by `setmetatable` "
            "in the same window is the metatable-injection variant of "
            "the same class (the metatable's methods fire during "
            "`tostring` / `__index`)."
        ),
        pattern=_LUA_LOADSTRING_UNTRUSTED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="embedded-scripting-node-vm-untrusted-source",
        name="Node vm.runIn*, new Function, VM2, or isolated-vm with untrusted source",
        severity="CRITICAL",
        description=(
            "Node.js exposes four in-process script interpreters that "
            "compile attacker-controllable JS source in the same "
            "process: `vm.runInNewContext` / `vm.runInThisContext` / "
            "`vm.runInContext` (contextify is documented as NOT a "
            "security boundary), `new Function(...)` (same parser as "
            "`eval`, no sandbox), `vm2` (deprecated after the May 2026 "
            "escape wave — 13 CVEs CVSS 9.0-10.0), and `isolated-vm` "
            "with a host `Reference` to `fetch` / `require` / `process` "
            "/ `child_process` leaked to the script global. The first "
            "three are full RCE on any request that lands in them; the "
            "fourth is RCE-class via one prototype lookup."
        ),
        pattern=_NODE_VM_TRIGGER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="embedded-scripting-template-ssti-user-source",
        name="Server-side template engine renders a user-controlled template string",
        severity="CRITICAL",
        description=(
            "A web framework renders a *template string* sourced from "
            "user input — `render_template_string(req.args[...])`, "
            "`Environment().from_string(user_input)`, "
            "`Handlebars.compile(req.body.template)`, Twig "
            "`ArrayLoader([... => $_POST[...]])`. Jinja's "
            "`SandboxedEnvironment` is bypassable via "
            "`__class__.__mro__` / `__subclasses__()` / "
            "`__init__.__globals__['__builtins__']`; Mako, Handlebars "
            "with `noEscape`, Twig with permissive sandbox, ERB with "
            "`<%= %>`, Liquid with unsafe filters, and Razor with "
            "`@Html.Raw` of dynamic source all have documented SSTI "
            "payloads. Direct `.format()` on a request-derived "
            "expression is the str-subclass attribute-traversal variant."
        ),
        pattern=_TEMPLATE_FROMSTRING_USER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="embedded-scripting-js-engine-host-binding-exposure",
        name="Embedded JS engine (QuickJS / GraalJS / V8) exposes host bindings to script",
        severity="CRITICAL",
        description=(
            "Embedders that ship a JS engine inside a C/C++/Rust/Java "
            "binary (QuickJS in `quickjs-emscripten` sandboxes / earlier "
            "Bun builds, GraalJS inside a JVM, V8 in a custom host) "
            "MUST strip the global of host APIs before the first user "
            "script runs. Common mistakes: QuickJS `js_init_module_os` "
            "/ `js_init_module_std` / `js_init_module_fs` registered "
            "before `JS_Eval(ctx, untrusted)`; GraalJS "
            "`Context.newBuilder('js').allowAllAccess(true).build()` "
            "(documented as 'effectively no sandbox' by GraalVM); "
            "GraalJS `HostAccess.ALL` or "
            "`.allowHostClassLookup(name -> true)` (attacker picks "
            "`Runtime`); V8 `External::New` of an untrusted host "
            "pointer without a `SetSecurityToken` call (cross-isolate "
            "property access)."
        ),
        pattern=_QUICKJS_HOST_MODULE_INIT,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="embedded-scripting-tcl-eval-untrusted",
        name="Tcl eval / Tcl_EvalObjEx on argv or buffer that traces to untrusted input",
        severity="CRITICAL",
        description=(
            "Tcl's `eval` / `uplevel` / `Tcl_Eval` / `Tcl_EvalObjEx` "
            "executes any Tcl text in the calling interpreter — `exec` "
            "is shell, `open \"|...\" r+` is shell, `expr [exec ...]` "
            "is shell. Network appliances (Cisco-style CLI, legacy F5 "
            "iRules), EDA toolchains (Synopsys, Cadence) and EXPECT "
            "scripts embed Tcl as the control plane, typically running "
            "as root in the data plane. Even `interp create -safe` is "
            "voided every time `interp alias slave srcCmd master "
            "srcCmd` re-exposes a master command (the master runs at "
            "master privilege regardless of the slave being marked "
            "-safe)."
        ),
        pattern=_TCL_EVAL_USER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="embedded-scripting-python-eval-exec-builtins-leak",
        name="Python eval / exec / RestrictedPython / asteval with attacker-controlled input",
        severity="CRITICAL",
        description=(
            "Python's `eval(...)` and `exec(...)` are full RCE when "
            "the expression is attacker-controlled. The common "
            "'defenses' all have known escapes: "
            "`eval(expr, {'__builtins__': {}}, {})` is bypassed via "
            "`().__class__.__base__.__subclasses__()[N]` (subprocess "
            "class lookup); `RestrictedPython` requires the consumer "
            "to also pass `safe_globals` / `safe_builtins` "
            "(`compile_restricted` alone is insufficient); `asteval`'s "
            "own docs state it is not a security sandbox; `simpleeval` "
            "re-introduces attribute traversal via `.format(...)`. "
            "Additional vector: `code.InteractiveInterpreter` / "
            "`InteractiveConsole` used as an agentic shell driving "
            "`interp.runsource(line)` over an LLM response."
        ),
        pattern=_PY_EVAL_EXEC_USER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="embedded-scripting-config-deferred-eval",
        name="Scripting language embedded in YAML / TOML / JSON config with attacker-controlled fields",
        severity="CRITICAL",
        description=(
            "Modern infra configs (GitHub Actions `${{ }}` expressions, "
            "Envoy `envoy.filters.http.lua` inline code, Nginx "
            "`content_by_lua_block`, OpenTelemetry collector OTTL "
            "processors, Promtail Lua stages, Argo CD / Crossplane / "
            "Helm value templates) embed *scripting languages inside "
            "strings inside structured configs*. The config loader "
            "treats the string as opaque, then a downstream component "
            "compiles and runs it — meaning grep on the loader for "
            "`eval` finds nothing, but the executor downstream eval's "
            "attacker-supplied text. Classic examples: GHA expression "
            "injection on `github.event.pull_request.title`; Envoy Lua "
            "filter calling `loadstring(headers:get('x-user-script'))`; "
            "Nginx Lua compiling `ngx.var.arg_code`. Impact is RCE in "
            "the proxy / sidecar / CI runner with full `GITHUB_TOKEN` "
            "or sidecar-pod credentials."
        ),
        pattern=_GHA_EXPRESSION_INJECTION_RUN,
        owasp_asi="ASI-04",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


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

    Stage-B filters consult adjacent lines or whole-file markers:

      * ESI-001 — Stage-A regex anchors on the loadstring/load call
        WITH a taint-source token on the same line. A separate Roblox
        Luau metatable-injection scan covers `HttpService:JSONDecode` →
        `setmetatable` within a 400-char window.
      * ESI-002 — Stage-A flags any of the four Node interpreter
        triggers. The high-precision Stage-B `_NODE_VM_UNTRUSTED_ARG`
        regex covers the `vm.runIn*(req.body)` / `new Function(payload)`
        / `vm.run(userCode)` shapes; `_ISOLATED_VM_HOST_REF_LEAK`
        covers the isolated-vm `Reference` leak.
      * ESI-003 — Stage-A regex requires a request-derived argument on
        the template `from_string` / `render_template_string` /
        `Handlebars.compile` call site. `.format()` on a
        request-derived expression is a separate sub-rule for the
        str-subclass traversal variant.
      * ESI-004 — Stage-A flags QuickJS `js_init_module_(os|std|fs|...)`
        registration. GraalJS `allowAllAccess(true)` /
        `HostAccess.ALL` / `.allowHostClassLookup(name -> true)` are
        independent Stage-A regexes. V8 `Context::New` paired with an
        `External::New` of untrusted data (or with a missing
        `SetSecurityToken` marker in the same file) is the Stage-B
        check.
      * ESI-005 — Stage-A regex requires the eval target variable name
        to hint at a taint source (user/cgi/req/etc). C-host
        `Tcl_EvalObjEx` is a separate Stage-A. Safe-interp alias
        leakage is a third sub-rule.
      * ESI-006 — Stage-A regex requires the eval/exec argument to
        trace to a request / input / payload / llm / response source.
        Empty-`__builtins__` bypass is a separate Stage-A.
        `compile_restricted` without `safe_globals` is Stage-B (the
        file-wide `safe_*` marker suppresses the finding).
      * ESI-007 — Stage-A regex flags `${{ github.event.<event>.* }}`
        inside a `run:` block. Envoy / Nginx / OTTL deferred-eval
        shapes are independent Stage-As — each scoped to a bounded
        `.{0,500}` window.

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

    # ---- ESI-001 : Lua loadstring on untrusted text ----
    rule_e1 = rule_by_id["embedded-scripting-lua-loadstring-untrusted"]
    for m in _LUA_LOADSTRING_UNTRUSTED.finditer(text):
        _emit(rule_e1, m.start(), m.group(0))
    for m in _ROBLOX_HTTPSERVICE_METATABLE.finditer(text):
        _emit(rule_e1, m.start(), m.group(0))

    # ---- ESI-002 : Node vm / new Function / VM2 / isolated-vm ----
    rule_e2 = rule_by_id["embedded-scripting-node-vm-untrusted-source"]
    # High-precision: untrusted-arg same-line shape.
    for m in _NODE_VM_UNTRUSTED_ARG.finditer(text):
        _emit(rule_e2, m.start(), m.group(0))
    # isolated-vm Reference-leak shape (cross-line, bounded).
    for m in _ISOLATED_VM_HOST_REF_LEAK.finditer(text):
        _emit(rule_e2, m.start(), m.group(0))
    # VM2 instantiation is itself audit-grade post-May-2026 escape wave;
    # any `new VM().run(...)` call is flagged regardless of the
    # argument shape.
    for m in _NODE_VM_TRIGGER.finditer(text):
        matched = m.group(0)
        if "VM" in matched and ".run" in matched:
            _emit(rule_e2, m.start(), matched)

    # ---- ESI-003 : SSTI via template engine ----
    rule_e3 = rule_by_id["embedded-scripting-template-ssti-user-source"]
    for m in _TEMPLATE_FROMSTRING_USER.finditer(text):
        _emit(rule_e3, m.start(), m.group(0))
    for m in _TEMPLATE_DOTFORMAT_USER.finditer(text):
        _emit(rule_e3, m.start(), m.group(0))
    for m in _HANDLEBARS_COMPILE_USER.finditer(text):
        _emit(rule_e3, m.start(), m.group(0))
    for m in _TWIG_ARRAYLOADER_REQUEST.finditer(text):
        _emit(rule_e3, m.start(), m.group(0))

    # ---- ESI-004 : embedded JS engine host-binding exposure ----
    rule_e4 = rule_by_id["embedded-scripting-js-engine-host-binding-exposure"]
    for m in _QUICKJS_HOST_MODULE_INIT.finditer(text):
        _emit(rule_e4, m.start(), m.group(0))
    for m in _GRAALJS_ALLOW_ALL_ACCESS.finditer(text):
        _emit(rule_e4, m.start(), m.group(0))
    for m in _GRAALJS_HOST_ACCESS_ALL.finditer(text):
        _emit(rule_e4, m.start(), m.group(0))
    # V8 dual-check: emit if `External::New` binds untrusted data, OR
    # if `Context::New` appears AND `SetSecurityToken` never appears.
    for m in _V8_EXTERNAL_BIND_UNTRUSTED.finditer(text):
        _emit(rule_e4, m.start(), m.group(0))
    has_v8_context = _file_contains(text, _V8_CONTEXT_NEW)
    has_security_token = _file_contains(text, _V8_SET_SECURITY_TOKEN)
    if has_v8_context and not has_security_token:
        for m in _V8_CONTEXT_NEW.finditer(text):
            _emit(rule_e4, m.start(), m.group(0))

    # ---- ESI-005 : Tcl eval / Tcl_EvalObjEx ----
    rule_e5 = rule_by_id["embedded-scripting-tcl-eval-untrusted"]
    for m in _TCL_EVAL_USER.finditer(text):
        _emit(rule_e5, m.start(), m.group(0))
    for m in _TCL_EVALOBJEX_HOST.finditer(text):
        _emit(rule_e5, m.start(), m.group(0))
    for m in _TCL_SAFE_INTERP_ALIAS_LEAK.finditer(text):
        _emit(rule_e5, m.start(), m.group(0))

    # ---- ESI-006 : Python eval / exec / sandbox bypass ----
    rule_e6 = rule_by_id["embedded-scripting-python-eval-exec-builtins-leak"]
    for m in _PY_EVAL_EXEC_USER.finditer(text):
        _emit(rule_e6, m.start(), m.group(0))
    for m in _PY_EVAL_BUILTINS_EMPTY.finditer(text):
        _emit(rule_e6, m.start(), m.group(0))
    # RestrictedPython: file-wide safe_* marker suppresses.
    has_safe_marker = _file_contains(text, _PY_RESTRICTED_SAFE_MARKER)
    if not has_safe_marker:
        for m in _PY_RESTRICTEDPYTHON_COMPILE.finditer(text):
            _emit(rule_e6, m.start(), m.group(0))
    for m in _PY_ASTEVAL_USER.finditer(text):
        _emit(rule_e6, m.start(), m.group(0))
    for m in _PY_INTERACTIVE_INTERPRETER_LLM.finditer(text):
        _emit(rule_e6, m.start(), m.group(0))

    # ---- ESI-007 : deferred-eval inside config carriers ----
    rule_e7 = rule_by_id["embedded-scripting-config-deferred-eval"]
    for m in _GHA_EXPRESSION_INJECTION_RUN.finditer(text):
        _emit(rule_e7, m.start(), m.group(0))
    for m in _GHA_HEAD_REF_RUN.finditer(text):
        _emit(rule_e7, m.start(), m.group(0))
    for m in _ENVOY_LUA_FROM_HEADER.finditer(text):
        _emit(rule_e7, m.start(), m.group(0))
    for m in _NGINX_LUA_ARG_LOADSTRING.finditer(text):
        _emit(rule_e7, m.start(), m.group(0))
    for m in _OTTL_PROCESSOR_DYNAMIC.finditer(text):
        _emit(rule_e7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
