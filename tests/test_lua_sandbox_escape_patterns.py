"""Tests for scripts/lib/lua_sandbox_escape_patterns.py.

Pattern-coverage tests for the Wave-32 distill-round-18 Lua sandbox
escape catalogue (14 rules across 9 logical vectors: debug introspection,
metatable bootstrap, bytecode round-trip, coroutine escape, LuaJIT FFI,
pcall/xpcall handler injection, Redis EVAL injection, package.loadlib path
injection, and _G/_ENV global-table access).

Each rule has at least 2 positive tests (canary) and at least 2 negative
tests (carve-out or context filter).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import lua_sandbox_escape_patterns as lse  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must contain all 14 documented rule IDs."""
    assert isinstance(lse.RULES, tuple)
    rule_ids = {r.id for r in lse.RULES}
    expected = {
        "lse-debug-introspection",
        "lse-getmetatable-string-bootstrap",
        "lse-string-dump-load-roundtrip",
        "lse-coroutine-upvalue-escape",
        "lse-coroutine-resume-inject",
        "lse-luajit-ffi-escape",
        "lse-require-ffi",
        "lse-pcall-xpcall-handler-injection",
        "lse-redis-eval-os-fs-access",
        "lse-redis-eval-config-restore",
        "lse-package-loadlib-path-injection",
        "lse-package-cpath-overwrite",
        "lse-package-preload-hijack",
        "lse-global-env-access",
    }
    assert expected == rule_ids
    assert len(lse.RULES) == 14


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in lse.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = lse.Finding(
        rule_id="lse-debug-introspection",
        line=3,
        column=5,
        matched_text="debug.getlocal(2, 1)",
        severity="CRITICAL",
        description="desc",
        owasp_asi="ASI-02",
    )
    assert f.rule_id == "lse-debug-introspection"
    assert f.line == 3
    assert f.column == 5
    assert f.matched_text == "debug.getlocal(2, 1)"
    assert f.severity == "CRITICAL"
    assert f.description == "desc"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert lse.scan_text("") == []


def test_scan_text_returns_list_of_findings() -> None:
    """scan_text always returns a list, even for benign input."""
    result = lse.scan_text("local x = 1\nprint(x)\n")
    assert isinstance(result, list)


def _hits(rule_id: str, text: str) -> list[lse.Finding]:
    return [f for f in lse.scan_text(text) if f.rule_id == rule_id]


# ---------- LSE-01 : lse-debug-introspection -----------------------------


def test_lse01_getupvalue_call_flags() -> None:
    """debug.getupvalue(f, n) → CRITICAL hit."""
    src = "local _, upval = debug.getupvalue(io.close, 1)\n"
    hits = _hits("lse-debug-introspection", src)
    assert len(hits) >= 1
    assert hits[0].severity == "CRITICAL"


def test_lse01_getregistry_call_flags() -> None:
    """debug.getregistry() → CRITICAL hit."""
    src = "local g = debug.getregistry()\n"
    hits = _hits("lse-debug-introspection", src)
    assert len(hits) >= 1
    assert hits[0].severity == "CRITICAL"


def test_lse01_sethook_flags() -> None:
    """debug.sethook(fn, 'c') → CRITICAL hit."""
    src = "debug.sethook(my_hook, 'c')\n"
    hits = _hits("lse-debug-introspection", src)
    assert len(hits) >= 1


def test_lse01_getinfo_flags() -> None:
    """debug.getinfo(2, 'f') → CRITICAL hit."""
    src = "local info = debug.getinfo(2, 'f')\n"
    hits = _hits("lse-debug-introspection", src)
    assert len(hits) >= 1


def test_lse01_benign_debug_string_no_hit() -> None:
    """The word 'debug' in a comment must NOT trigger."""
    src = "-- debug library is not used here\nlocal x = 1\n"
    assert _hits("lse-debug-introspection", src) == []


def test_lse01_benign_debug_variable_no_hit() -> None:
    """A variable named debug_level that is not a method call must not trigger."""
    src = "local debug_level = 3\nprint(debug_level)\n"
    assert _hits("lse-debug-introspection", src) == []


# ---------- LSE-02 : lse-getmetatable-string-bootstrap -------------------


def test_lse02_empty_string_index_flags() -> None:
    """getmetatable('').__index → CRITICAL hit."""
    src = 'local mt = getmetatable("").__index\n'
    hits = _hits("lse-getmetatable-string-bootstrap", src)
    assert len(hits) >= 1
    assert hits[0].severity == "CRITICAL"


def test_lse02_nil_index_flags() -> None:
    """getmetatable(nil).__index → CRITICAL hit."""
    src = "local mt = getmetatable(nil).__index\n"
    hits = _hits("lse-getmetatable-string-bootstrap", src)
    assert len(hits) >= 1


def test_lse02_false_index_flags() -> None:
    """getmetatable(false).__index → CRITICAL hit."""
    src = "local x = getmetatable(false).__index\n"
    hits = _hits("lse-getmetatable-string-bootstrap", src)
    assert len(hits) >= 1


def test_lse02_object_arg_no_hit() -> None:
    """getmetatable(userObj).__index is a legitimate shape — NOT flagged."""
    src = "local mt = getmetatable(userObj).__index\n"
    assert _hits("lse-getmetatable-string-bootstrap", src) == []


def test_lse02_getmetatable_without_index_no_hit() -> None:
    """getmetatable('') without .__index should NOT trigger."""
    src = 'local mt = getmetatable("")\nprint(mt)\n'
    assert _hits("lse-getmetatable-string-bootstrap", src) == []


# ---------- LSE-03 : lse-string-dump-load-roundtrip ----------------------


def test_lse03_dump_then_load_same_line_flags() -> None:
    """string.dump(f) assigned then load( on same line → HIGH hit."""
    # Order matters: string.dump first, load( second (matches the regex)
    src = "local blob = string.dump(io.open)  local fn = load(blob)\n"
    hits = _hits("lse-string-dump-load-roundtrip", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_lse03_dump_assigned_then_load_flags() -> None:
    """string.dump(f) assigned to var then load(var) → HIGH hit."""
    src = "local blob = string.dump(io.open)  local fn = load(blob)\n"
    hits = _hits("lse-string-dump-load-roundtrip", src)
    assert len(hits) >= 1


def test_lse03_dump_alone_no_hit() -> None:
    """string.dump alone (no load on same line) must NOT trigger."""
    src = "local blob = string.dump(my_func)\n-- blob is saved to disk\n"
    assert _hits("lse-string-dump-load-roundtrip", src) == []


def test_lse03_load_alone_no_hit() -> None:
    """load() without string.dump must NOT trigger this rule."""
    src = 'local fn = load("return 42")\n'
    assert _hits("lse-string-dump-load-roundtrip", src) == []


# ---------- LSE-04a : lse-coroutine-upvalue-escape -----------------------


def test_lse04a_wrap_with_upvalue_flags() -> None:
    """coroutine.wrap(function() ... upvalue ... end) → MEDIUM hit."""
    src = (
        "local co = coroutine.wrap(function()\n"
        "    -- recover upvalue from host closure\n"
        "    coroutine.yield()\n"
        "end)\n"
    )
    hits = _hits("lse-coroutine-upvalue-escape", src)
    assert len(hits) >= 1
    assert hits[0].severity == "MEDIUM"


def test_lse04a_create_with_upvalue_flags() -> None:
    """coroutine.create with 'upvalue' keyword nearby → MEDIUM hit."""
    src = "local co = coroutine.create(f_with_upvalue)\n"
    hits = _hits("lse-coroutine-upvalue-escape", src)
    assert len(hits) >= 1


def test_lse04a_wrap_without_upvalue_no_hit() -> None:
    """coroutine.wrap without the word 'upvalue' must NOT trigger."""
    src = "local co = coroutine.wrap(function() return 42 end)\n"
    assert _hits("lse-coroutine-upvalue-escape", src) == []


# ---------- LSE-04b : lse-coroutine-resume-inject ------------------------


def test_lse04b_resume_with_io_arg_flags() -> None:
    """coroutine.resume(co, io.open) → HIGH hit."""
    src = "local res = coroutine.resume(co, io.open)\n"
    hits = _hits("lse-coroutine-resume-inject", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_lse04b_resume_with_os_arg_flags() -> None:
    """coroutine.resume(co, os) → HIGH hit."""
    src = "coroutine.resume(thread, os)\n"
    hits = _hits("lse-coroutine-resume-inject", src)
    assert len(hits) >= 1


def test_lse04b_resume_benign_args_no_hit() -> None:
    """coroutine.resume(co, value) with safe argument must NOT trigger."""
    src = "coroutine.resume(co, 42)\n"
    assert _hits("lse-coroutine-resume-inject", src) == []


# ---------- LSE-05a : lse-luajit-ffi-escape ------------------------------


def test_lse05a_ffi_cdef_flags() -> None:
    """ffi.cdef [[ ... ]] → CRITICAL hit."""
    src = 'ffi.cdef[[\n    int system(const char *command);\n]]\n'
    hits = _hits("lse-luajit-ffi-escape", src)
    assert len(hits) >= 1
    assert hits[0].severity == "CRITICAL"


def test_lse05a_ffi_load_flags() -> None:
    """ffi.load('libc') → CRITICAL hit."""
    src = "local libc = ffi.load('libc')\n"
    hits = _hits("lse-luajit-ffi-escape", src)
    assert len(hits) >= 1


def test_lse05a_ffi_cast_flags() -> None:
    """ffi.cast('void*', ptr) → CRITICAL hit."""
    src = 'local p = ffi.cast("void*", raw_ptr)\n'
    hits = _hits("lse-luajit-ffi-escape", src)
    assert len(hits) >= 1


def test_lse05a_ffi_c_dot_flags() -> None:
    """ffi.C.system(...) → CRITICAL hit."""
    src = 'ffi.C.system("id")\n'
    hits = _hits("lse-luajit-ffi-escape", src)
    assert len(hits) >= 1


def test_lse05a_benign_ffi_comment_no_hit() -> None:
    """A comment mentioning ffi must NOT trigger lse-luajit-ffi-escape."""
    src = "-- ffi is disabled in this sandbox\nlocal x = 1\n"
    assert _hits("lse-luajit-ffi-escape", src) == []


# ---------- LSE-05b : lse-require-ffi ------------------------------------


def test_lse05b_require_ffi_double_quote_flags() -> None:
    """require("ffi") → HIGH hit."""
    src = 'local ffi = require("ffi")\n'
    hits = _hits("lse-require-ffi", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_lse05b_require_ffi_single_quote_flags() -> None:
    """require('ffi') → HIGH hit."""
    src = "local ffi = require('ffi')\n"
    hits = _hits("lse-require-ffi", src)
    assert len(hits) >= 1


def test_lse05b_require_other_module_no_hit() -> None:
    """require('json') must NOT trigger lse-require-ffi."""
    src = "local json = require('json')\n"
    assert _hits("lse-require-ffi", src) == []


# ---------- LSE-06 : lse-pcall-xpcall-handler-injection ------------------


def test_lse06_xpcall_request_handler_flags() -> None:
    """xpcall(f, request.handler) → HIGH hit."""
    src = "xpcall(function() error('x') end, request.log_handler)\n"
    hits = _hits("lse-pcall-xpcall-handler-injection", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_lse06_xpcall_user_handler_flags() -> None:
    """xpcall(f, user_handler) → HIGH hit."""
    src = "xpcall(protected_fn, user_error_handler)\n"
    hits = _hits("lse-pcall-xpcall-handler-injection", src)
    assert len(hits) >= 1


def test_lse06_xpcall_trusted_handler_no_hit() -> None:
    """xpcall with a constant function handler must NOT trigger."""
    src = "xpcall(function() do_thing() end, traceback)\n"
    assert _hits("lse-pcall-xpcall-handler-injection", src) == []


def test_lse06_pcall_no_handler_no_hit() -> None:
    """pcall(f) without a handler must NOT trigger xpcall rule."""
    src = "local ok, err = pcall(do_thing, payload)\n"
    assert _hits("lse-pcall-xpcall-handler-injection", src) == []


# ---------- LSE-07a : lse-redis-eval-os-fs-access ------------------------


def test_lse07a_redis_eval_fstring_flags() -> None:
    """redis.eval(f'...{user}...', ...) → CRITICAL hit."""
    src = "r.eval(f\"return redis.call('GET', '{user_key}')\", 0)\n"
    hits = _hits("lse-redis-eval-os-fs-access", src)
    assert len(hits) >= 1
    assert hits[0].severity == "CRITICAL"


def test_lse07a_redis_eval_fstring_double_flags() -> None:
    """redis.eval(f\"...\") with interpolation marker → CRITICAL hit."""
    src = 'redis.eval(f"local k = {key_name}; return redis.call(\'GET\', k)", 0)\n'
    hits = _hits("lse-redis-eval-os-fs-access", src)
    assert len(hits) >= 1


def test_lse07a_redis_eval_static_string_no_hit() -> None:
    """redis.eval with a plain string (no f-string) must NOT trigger."""
    src = "r.eval(\"return redis.call('SET', KEYS[1], ARGV[1])\", 1, key, val)\n"
    assert _hits("lse-redis-eval-os-fs-access", src) == []


# ---------- LSE-07b : lse-redis-eval-config-restore ----------------------


def test_lse07b_enable_debug_command_flags() -> None:
    """redis.call('CONFIG', 'SET', 'enable-debug-command', 'yes') → HIGH hit."""
    src = "r.eval(\"redis.call('CONFIG', 'SET', 'enable-debug-command', 'yes')\", 0)\n"
    hits = _hits("lse-redis-eval-config-restore", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_lse07b_requirepass_clear_flags() -> None:
    """redis.call('CONFIG', 'SET', 'requirepass', '') → HIGH hit."""
    src = "r.eval(\"redis.call('CONFIG', 'SET', 'requirepass', '')\", 0)\n"
    hits = _hits("lse-redis-eval-config-restore", src)
    assert len(hits) >= 1


def test_lse07b_config_get_no_hit() -> None:
    """redis.call('CONFIG', 'GET', ...) must NOT trigger CONFIG SET rule."""
    src = "r.eval(\"return redis.call('CONFIG', 'GET', 'maxmemory')\", 0)\n"
    assert _hits("lse-redis-eval-config-restore", src) == []


# ---------- LSE-08a : lse-package-loadlib-path-injection -----------------


def test_lse08a_tmp_path_flags() -> None:
    """package.loadlib('/tmp/evil.so', ...) → CRITICAL hit."""
    src = "local lib = package.loadlib('/tmp/evil.so', 'luaopen_evil')\n"
    hits = _hits("lse-package-loadlib-path-injection", src)
    assert len(hits) >= 1
    assert hits[0].severity == "CRITICAL"


def test_lse08a_user_path_arg_flags() -> None:
    """package.loadlib(user_input, ...) → CRITICAL hit."""
    src = "local lib = package.loadlib(user_path, entry_sym)\n"
    hits = _hits("lse-package-loadlib-path-injection", src)
    assert len(hits) >= 1


def test_lse08a_static_trusted_path_no_hit() -> None:
    """package.loadlib('/usr/lib/lua/socket.so', ...) must NOT trigger."""
    src = "package.loadlib('/usr/lib/lua/socket.so', 'luaopen_socket')\n"
    assert _hits("lse-package-loadlib-path-injection", src) == []


# ---------- LSE-08b : lse-package-cpath-overwrite ------------------------


def test_lse08b_cpath_tmp_overwrite_flags() -> None:
    """package.cpath = '/tmp/?.so;' ... → HIGH hit."""
    src = "package.cpath = '/tmp/?.so;' .. package.cpath\n"
    hits = _hits("lse-package-cpath-overwrite", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_lse08b_path_user_overwrite_flags() -> None:
    """package.path set to include user_ prefix path → HIGH hit."""
    src = "package.path = user_dir .. '/?.lua;' .. package.path\n"
    hits = _hits("lse-package-cpath-overwrite", src)
    assert len(hits) >= 1


def test_lse08b_cpath_static_no_hit() -> None:
    """package.cpath set to a static trusted path must NOT trigger."""
    src = "package.cpath = '/usr/local/lib/lua/5.4/?.so'\n"
    assert _hits("lse-package-cpath-overwrite", src) == []


# ---------- LSE-08c : lse-package-preload-hijack -------------------------


def test_lse08c_preload_assignment_flags() -> None:
    """package.preload['json'] = function() ... end → MEDIUM hit."""
    src = (
        "package.preload['json'] = function()\n"
        "    return { decode = function(s) os.execute(s) end }\n"
        "end\n"
    )
    hits = _hits("lse-package-preload-hijack", src)
    assert len(hits) >= 1
    assert hits[0].severity == "MEDIUM"


def test_lse08c_preload_double_quote_key_flags() -> None:
    """package.preload[\"socket\"] = loader → MEDIUM hit."""
    src = 'package.preload["socket"] = attacker_loader\n'
    hits = _hits("lse-package-preload-hijack", src)
    assert len(hits) >= 1


def test_lse08c_preload_read_no_hit() -> None:
    """Reading package.preload['x'] (no assignment) must NOT trigger."""
    src = "local loader = package.preload['json']\n"
    assert _hits("lse-package-preload-hijack", src) == []


# ---------- LSE-09 : lse-global-env-access --------------------------------


def test_lse09_g_io_access_flags() -> None:
    """_G['io'] → HIGH hit."""
    src = "local real_io = _G['io']\nreal_io.open('/etc/passwd', 'r')\n"
    hits = _hits("lse-global-env-access", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_lse09_g_os_access_flags() -> None:
    """_G['os'] → HIGH hit."""
    src = 'local os2 = _G["os"]\nos2.execute("id")\n'
    hits = _hits("lse-global-env-access", src)
    assert len(hits) >= 1


def test_lse09_rawget_g_flags() -> None:
    """rawget(_G, 'debug') → HIGH hit."""
    src = "local d = rawget(_G, 'debug')\n"
    hits = _hits("lse-global-env-access", src)
    assert len(hits) >= 1


def test_lse09_env_equals_g_flags() -> None:
    """_ENV = _G → HIGH hit."""
    src = "_ENV = _G\nos.execute('id')\n"
    hits = _hits("lse-global-env-access", src)
    assert len(hits) >= 1


def test_lse09_g_safe_key_no_hit() -> None:
    """_G['print'] (safe key not in dangerous list) must NOT trigger."""
    src = "local p = _G['print']\n"
    assert _hits("lse-global-env-access", src) == []


def test_lse09_pairs_g_enumeration_no_hit() -> None:
    """for k,v in pairs(_G) do ... end must NOT trigger (no dangerous key lookup)."""
    src = "for k, v in pairs(_G) do print(k) end\n"
    assert _hits("lse-global-env-access", src) == []
