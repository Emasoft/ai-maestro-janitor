"""Lua sandbox escape patterns.

Wave-32 distillation round-18, Lua sandbox escape angle.

Catalogue of 9 patterns covering sandbox breakout techniques in Lua 5.x
and LuaJIT 2.1 environments: debug library introspection, metatable
bootstraps, bytecode round-trips, coroutine upvalue leaks, FFI native
gateways, pcall/xpcall handler injection, Redis EVAL script injection,
package.loadlib path injection, and _G/_ENV global-table access.

What is NOT here (already shipped — DO NOT duplicate):

  * `luaL_loadstring` / `luaL_loadbuffer` / `lua_load` / `loadstring` /
    `load` with an untrusted taint-source marker on the same line —
    `embedded_scripting_patterns.py` rule `embedded-scripting-lua-loadstring-untrusted`.
  * Roblox Luau `HttpService:JSONDecode` + `setmetatable` within 400 chars —
    `embedded_scripting_patterns.py` rule `_ROBLOX_HTTPSERVICE_METATABLE`.
  * Nginx `content_by_lua_block` / `content_by_lua` with `ngx.var.arg_*`
    injection — `embedded_scripting_patterns.py`.
  * Container / k8s sandbox escape — `sandbox_escape_patterns.py` (round-4).

What IS here (9 net-new rules, all RE2-safe):

  * lse-debug-introspection              (CRITICAL)
  * lse-getmetatable-string-bootstrap    (CRITICAL)
  * lse-string-dump-load-roundtrip       (HIGH)
  * lse-coroutine-upvalue-escape         (MEDIUM)
  * lse-coroutine-resume-inject          (HIGH)
  * lse-luajit-ffi-escape                (CRITICAL)
  * lse-require-ffi                      (HIGH)
  * lse-pcall-xpcall-handler-injection   (HIGH)
  * lse-redis-eval-os-fs-access          (CRITICAL)
  * lse-redis-eval-config-restore        (HIGH)
  * lse-package-loadlib-path-injection   (CRITICAL)
  * lse-package-cpath-overwrite          (HIGH)
  * lse-package-preload-hijack           (MEDIUM)
  * lse-global-env-access                (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, same shape as
            webhook_signature_patterns.Finding.

OWASP ASI mapping used:
  ASI-02 — Tool misuse (debug library left enabled, FFI gateway)
  ASI-04 — Supply chain (package.loadlib path injection)
  ASI-05 — Unexpected code execution (all sandbox escape sinks)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
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
    chat_bot_patterns / auth_flow_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- LSE-01 : debug library introspection left enabled in sandbox -------

# Matches any call to the five classic introspection methods on the Lua
# debug library. Whitespace-flexible dot handles minified/obfuscated payloads.
_DEBUG_INTROSPECTION = _re(
    r"\bdebug\s*\.\s*(?:getlocal|getupvalue|sethook|getregistry|getinfo)\s*\("
)

# ---- LSE-02 : getmetatable string-library bootstrap (global table leak) -

# Matches getmetatable applied to a literal primitive — the canonical
# bootstrap targets: "", '', 0, nil, false, true.
_GETMETATABLE_STRING_BOOTSTRAP = _re(
    r"getmetatable\s*\(\s*(?:\"\"|''|0|nil|false|true)\s*\)\s*\.__index"
)

# ---- LSE-03 : string.dump + load bytecode round-trip --------------------

# The window [^)]{0,200} captures the argument; [^;,\n]{0,50} allows
# for an intermediate variable assignment before load(.
_STRING_DUMP_LOAD_ROUNDTRIP = _re(
    r"\bstring\s*\.\s*dump\s*\([^)]{0,200}\)[^;,\n]{0,50}\bload\s*\("
)

# ---- LSE-04a : coroutine.wrap/create with upvalue in same expression ----

# Primary — coroutine wrap/create with explicit "upvalue" name nearby.
# Uses [\s\S]{0,500} to span multi-line function bodies (e.g. the closing
# paren of yield() inside a wrap argument would stop [^)]{0,300}).
# "upvalue" without a trailing word boundary also matches f_with_upvalue.
# Used as MEDIUM advisory; FP rate is higher without secondary taint signal.
_COROUTINE_UPVALUE_ESCAPE = _re(
    r"\bcoroutine\s*\.\s*(?:wrap|create)\s*\([\s\S]{0,500}upvalue"
)

# ---- LSE-04b : coroutine.resume injection with dangerous args -----------

# Secondary shape: resume called with dangerous capability in argument list.
_COROUTINE_RESUME_INJECT = _re(
    r"\bcoroutine\s*\.\s*resume\s*\([^,)]{0,100},[^)]{0,300}(?:io|os|debug|_G|load)\b"
)

# ---- LSE-05a : LuaJIT FFI native code gateway --------------------------

# ffi.cdef / ffi.load / ffi.cast followed by opening bracket/quote.
# ffi.C.<funcname>( catches the default-namespace call shape (e.g. ffi.C.system("id"))
# which is different from ffi.cdef/load/cast — those are followed by [[ or quote/paren,
# but ffi.C.something( is followed by an identifier.
_LUAJIT_FFI_ESCAPE = _re(
    r"\bffi\s*\.\s*(?:cdef|load|cast)\s*(?:\[\[|['\"\(])"
    r"|\bffi\s*\.\s*C\s*\.\s*[a-zA-Z_]\w*\s*\("
)

# ---- LSE-05b : require("ffi") in sandboxed Lua code --------------------

# A sandboxed chunk should never be able to require the FFI library.
_REQUIRE_FFI = _re(
    r'\brequire\s*\(\s*[\'"]ffi[\'"]\s*\)'
)

# ---- LSE-06 : pcall/xpcall error-handler injection from tainted source --

# Matches xpcall where the second argument (handler) derives from a
# recognisably tainted source name.  Uses [\s\S]{0,300}? (lazy) to span
# multi-line first-argument shapes (e.g. function() ... end).
# Taint keywords match with (?:_|\b) so they also catch user_handler,
# input_callback, arg_fn etc.
_PCALL_XPCALL_HANDLER_INJECTION = _re(
    r"\bxpcall\s*\([\s\S]{0,300}?(?:request|user|input|body|payload|arg)(?:_|\b)"
)

# ---- LSE-07a : Redis EVAL with user-interpolated f-string script --------

# Python redis-py r.eval(f"...", ...) or redis.eval(f"...", ...) with f-string.
# Allows both the shorthand variable (r.eval) and the full object (redis.eval).
_REDIS_EVAL_OS_FS_ACCESS = _re(
    r'\b(?:redis|r)\.eval\s*\(\s*f["\']'
)

# ---- LSE-07b : CONFIG SET restoring protected capabilities inside EVAL --

# Post-auth privilege escalation restoring debug command or clearing auth.
_REDIS_EVAL_CONFIG_RESTORE = _re(
    r'redis\.call\s*\(\s*[\'"]CONFIG[\'"][^)]{0,200}'
    r'(?:enable-(?:protected-configs|debug-command)|requirepass)\b'
)

# ---- LSE-08a : package.loadlib with attacker-controlled path -----------

# loadlib with a path argument pointing to world-writable or user-controlled
# locations.  No trailing \b so that user_path / input_file / arg_dir
# also match (the taint keyword appears as a prefix of a longer identifier).
_PACKAGE_LOADLIB_PATH_INJECTION = _re(
    r"\bpackage\s*\.\s*loadlib\s*\(\s*[^,)]{0,300}"
    r"(?:/tmp|/var/tmp|user|input|arg|request)"
)

# ---- LSE-08b : package.cpath / package.path overwrite ------------------

# Overwriting the search path to include attacker-controlled directories.
_PACKAGE_CPATH_OVERWRITE = _re(
    r"\bpackage\s*\.\s*(?:cpath|path)\s*=\s*[^;,\n]{0,100}"
    r"(?:/tmp|/var/tmp|user_|input_|arg_)"
)

# ---- LSE-08c : package.preload hijack ----------------------------------

# Assignment to a preload slot redirects future require() calls.
_PACKAGE_PRELOAD_HIJACK = _re(
    r"\bpackage\s*\.\s*preload\s*\[\s*['\"][^'\"]{1,50}['\"]\s*\]\s*="
)

# ---- LSE-09 : _G / _ENV direct global-table access in sandboxed chunk --

# Covers three sub-shapes:
#   _G["dangerous-symbol"]  — direct key access
#   rawget(_G, ...)         — rawget bypass of __newindex guard
#   _ENV = _G               — Lua 5.2+ full-reset of environment
_GLOBAL_ENV_ACCESS = _re(
    r"\b(?:"
    r"_G\s*\[\s*['\"](?:io|os|debug|require|load|rawget|rawset|getmetatable|setmetatable)['\"]\s*\]"
    r"|rawget\s*\(\s*_G\s*,"
    r"|_ENV\s*=\s*_G\b"
    r")"
)


# ---- RULES tuple --------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="lse-debug-introspection",
        name="Lua debug library introspection left enabled in sandboxed environment",
        severity="CRITICAL",
        description=(
            "A call to `debug.getlocal`, `debug.getupvalue`, "
            "`debug.sethook`, `debug.getregistry`, or `debug.getinfo` "
            "inside a Lua sandbox indicates the `debug` library was not "
            "nil-ed out. An attacker can walk the call stack to extract "
            "local variables, upvalues, privileged function references, "
            "and the full Lua registry. `debug.sethook` can execute "
            "arbitrary code on every instruction step even in protected "
            "mode. Sandbox setup MUST include `debug = nil` or "
            "`rawset(env, 'debug', nil)` before arming the environment."
        ),
        pattern=_DEBUG_INTROSPECTION,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="lse-getmetatable-string-bootstrap",
        name="getmetatable on literal primitive to bootstrap string library / global table",
        severity="CRITICAL",
        description=(
            "All Lua strings share a single metatable whose `__index` "
            "points at the `string` library. `getmetatable('').__index` "
            "recovers the full string table even if the sandbox "
            "restricts `string` directly. An attacker can then "
            "reconstruct arbitrary function names with `string.char` "
            "and call them through `_G`. The same technique applies to "
            "other literal primitives (0, nil, false, true) whose "
            "metatables may be hijacked. Sandbox setup MUST replace or "
            "remove the string metatable."
        ),
        pattern=_GETMETATABLE_STRING_BOOTSTRAP,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="lse-string-dump-load-roundtrip",
        name="string.dump serialises function then load deserialises bytecode",
        severity="HIGH",
        description=(
            "`string.dump(f)` serialises the bytecode of function `f`; "
            "`load(blob)` deserialises it. In a sandbox that blocks "
            "`loadstring`/`load` at source level but still exposes "
            "`string.dump`, a pre-compiled bytecode blob can bypass "
            "source-level restrictions. Crafted bytecode may also "
            "corrupt the VM state (CVE-2021-44647, CVE-2022-33099) "
            "before the payload executes. The sandbox MUST remove both "
            "`string.dump` and `load`."
        ),
        pattern=_STRING_DUMP_LOAD_ROUNDTRIP,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="lse-coroutine-upvalue-escape",
        name="coroutine.wrap/create used to leak host upvalue via debug introspection",
        severity="MEDIUM",
        description=(
            "A coroutine created with `coroutine.wrap` or "
            "`coroutine.create` shares upvalues with its creator. When "
            "the `debug` library is also available (LSE-01), sandboxed "
            "code can use `debug.getupvalue` to walk the host closure "
            "and recover privileged function references. This advisory "
            "fires on the coroutine + explicit `upvalue` name proximity; "
            "escalate to HIGH when LSE-01 is also present."
        ),
        pattern=_COROUTINE_UPVALUE_ESCAPE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="lse-coroutine-resume-inject",
        name="coroutine.resume with dangerous capability injected as argument",
        severity="HIGH",
        description=(
            "`coroutine.resume` called with a second argument that "
            "references a privileged capability (`io`, `os`, `debug`, "
            "`_G`, `load`). After a coroutine `yield`s, the resumed "
            "function receives the resume arguments as return values of "
            "`yield`; if the coroutine body treats these as callbacks "
            "or function tables it will invoke attacker-supplied code "
            "with the coroutine's privilege level."
        ),
        pattern=_COROUTINE_RESUME_INJECT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="lse-luajit-ffi-escape",
        name="LuaJIT ffi.cdef / ffi.load / ffi.cast native code gateway",
        severity="CRITICAL",
        description=(
            "LuaJIT's FFI library (`ffi.cdef`, `ffi.load`, `ffi.cast`, "
            "`ffi.C.*`) gives Lua code direct access to native C "
            "functions. An attacker can declare `system` via `ffi.cdef` "
            "and then call `libc.system('id')` for full shell execution. "
            "`ffi.C` (default namespace) on Linux already exposes "
            "`open`, `write`, `exec*` without any `ffi.load` step. "
            "The sandbox MUST remove `package.preload['ffi']` and nil "
            "the `ffi` global before arming the environment."
        ),
        pattern=_LUAJIT_FFI_ESCAPE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="lse-require-ffi",
        name="require('ffi') in sandboxed Lua chunk",
        severity="HIGH",
        description=(
            "`require('ffi')` in a sandboxed Lua chunk means either "
            "the sandbox forgot to remove `package.preload['ffi']` or "
            "the sandbox re-exposes `require` without restricting the "
            "preload table. The FFI library provides full native code "
            "access; its presence in a sandbox is a CRITICAL precursor "
            "to the attack in lse-luajit-ffi-escape."
        ),
        pattern=_REQUIRE_FFI,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="lse-pcall-xpcall-handler-injection",
        name="xpcall error-handler supplied from tainted / user-controlled source",
        severity="HIGH",
        description=(
            "`xpcall(f, handler)` runs `handler` outside the strict "
            "sandbox environment at the privilege level of the call "
            "site. When the handler argument is derived from a "
            "user-supplied variable (`request`, `user`, `input`, "
            "`body`, `payload`, `arg`), an attacker can inject a "
            "handler that reads debug info about the call site and "
            "invokes privileged functions. Combined with LSE-01 this "
            "becomes a full sandbox escape."
        ),
        pattern=_PCALL_XPCALL_HANDLER_INJECTION,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="lse-redis-eval-os-fs-access",
        name="Redis EVAL script constructed from user-controlled f-string (script injection)",
        severity="CRITICAL",
        description=(
            "`redis.eval(f'...', ...)` with an f-string that "
            "interpolates a variable allows a classic Lua script "
            "injection: the attacker closes the embedded Lua string "
            "early and appends arbitrary Lua code. Redis 7.x "
            "`enable-protected-configs yes` may also restore the "
            "restricted `os`/`debug` libraries. NEVER build an EVAL "
            "script string from user-supplied values; use KEYS/ARGV "
            "parameters instead."
        ),
        pattern=_REDIS_EVAL_OS_FS_ACCESS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="lse-redis-eval-config-restore",
        name="Redis CONFIG SET inside EVAL restores protected capabilities or clears auth",
        severity="HIGH",
        description=(
            "A Redis Lua script that calls "
            "`redis.call('CONFIG', 'SET', 'enable-debug-command', 'yes')` "
            "or `redis.call('CONFIG', 'SET', 'requirepass', '')` "
            "escalates privilege from the Lua sandbox to full Redis "
            "admin control: the first restores the `debug` library "
            "(allowing further Lua sandbox escape), the second removes "
            "authentication entirely. Both are post-auth sandbox "
            "escapes documented in Redis 7.x security advisories."
        ),
        pattern=_REDIS_EVAL_CONFIG_RESTORE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="lse-package-loadlib-path-injection",
        name="package.loadlib called with attacker-controllable or world-writable path",
        severity="CRITICAL",
        description=(
            "`package.loadlib(path, funcname)` loads a shared library "
            "from an arbitrary filesystem path and calls `funcname` in "
            "it — equivalent to `dlopen` + `dlsym`. An attacker who "
            "can write a `.so`/`.dll` to `/tmp` or another "
            "world-writable location gains full native code execution. "
            "The sandbox MUST remove `package.loadlib` before arming "
            "the environment."
        ),
        pattern=_PACKAGE_LOADLIB_PATH_INJECTION,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="lse-package-cpath-overwrite",
        name="package.cpath or package.path overwritten to include attacker-controlled directory",
        severity="HIGH",
        description=(
            "Overwriting `package.cpath` or `package.path` to include "
            "`/tmp` or another user-controlled directory allows a "
            "subsequent `require()` call to silently load an "
            "attacker-supplied `.so`/`.lua` extension. The sandbox "
            "MUST nil `package` entirely or freeze both path fields "
            "before arming the environment."
        ),
        pattern=_PACKAGE_CPATH_OVERWRITE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="lse-package-preload-hijack",
        name="package.preload slot overwritten to redirect future require() calls",
        severity="MEDIUM",
        description=(
            "Assigning to `package.preload['modulename']` redirects "
            "every future `require('modulename')` call in the same Lua "
            "state to the attacker-supplied loader function. This "
            "silently replaces trusted module implementations (e.g. "
            "`json`, `cjson`, `socket`) with attacker-controlled ones. "
            "Escalates to HIGH when the assigned function body contains "
            "`os.execute` or `io.open`. Sandbox MUST freeze or nil "
            "`package.preload` before arming."
        ),
        pattern=_PACKAGE_PRELOAD_HIJACK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="lse-global-env-access",
        name="_G / _ENV direct global-table access bypasses sandbox restrictions",
        severity="HIGH",
        description=(
            "Sandboxed Lua code accessing `_G['io']`, `_G['os']`, "
            "`_G['debug']`, `rawget(_G, ...)`, or replacing `_ENV = _G` "
            "bypasses the restricted environment table and recovers "
            "full access to the Lua standard library. `rawget`/`rawset` "
            "bypass `__index`/`__newindex` metamethod guards that many "
            "sandboxes rely on. Sandbox MUST rebind `_ENV` to a "
            "restricted table and ensure `_G` is not reachable as an "
            "upvalue from sandboxed code."
        ),
        pattern=_GLOBAL_ENV_ACCESS,
        owasp_asi="ASI-05",
    ),
)


# ---- Scanner-level helpers ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Each rule's compiled pattern is applied once to the full input. Findings
    are deduplicated by (rule_id, line, column).
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
            _emit(rule, m.start(), m.group(0))

    return findings
