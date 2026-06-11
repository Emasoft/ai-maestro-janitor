"""WebAssembly sandbox escape + WASI capability-misuse patterns.

Wave 22 impl-B — distillation of 25 proposals from
``reports/distill-round-8/wasm-sandbox-escape.md`` into deterministic
regex rules.

Scope. WebAssembly runtime misconfiguration, WASI capability over-grant,
host-import shadowing, browser-side ``WebAssembly.instantiate`` without
SRI, Spin/Fermyon manifest outbound wildcards, Deno permission-flag
misuse, and Node.js wasm host-isolation gaps. Covers ``wasmtime``,
``wasmer``, ``WasmEdge``, browser-side WebAssembly, Node.js wasm hosts,
Deno's permission flags, and the WIT-bindgen / WASM-Component
capability gate. Strictly about *wasm runtime configuration* and
*WASI capability granting* — NOT host-language ``unsafe`` blocks
(Wave 21 ``rust_specific_patterns.py``) and NOT POSIX sandbox primitives
(Wave 18 ``sandbox_escape_patterns.py``).

This module encodes the wasm-specific rule shapes as **pure regex**
for the heartbeat detectors that prefer the lightweight one-pass
scanner shape over an AST walk. The regex rules accept a small
precision trade-off (slightly higher FP rate vs an AST walk that can
reason about scopes) in exchange for being trivially composable with
the other ``scripts/lib/*_patterns.py`` modules.

Architecture mirrors ``scripts/lib/rust_specific_patterns.py``:

  * ``Rule(id, name, severity, description, pattern, owasp_asi)``
                                  — single rule record. Patterns are
                                    pre-compiled at module load.
  * ``RULES``                     — ordered tuple of every catalogued rule.
  * ``scan_text(text)`` -> list[Finding]
                                  — run every rule, return findings.
  * ``Finding(rule_id, line, column, matched_text, severity,
              description, owasp_asi)``
                                  — single finding record.

Pure-stdlib (``re``, ``NamedTuple``) so the module loads in every
PEP 723 script block without third-party deps. All regexes are
RE2-safe (no backreferences, no nested unbounded quantifiers, every
``*``/``+`` is bounded by either an anchored prefix or a finite
``{0,N}`` window).

Severity mapping from the distill report onto the janitor's
canonical four-tier scale:

  CRITICAL (report) → CRITICAL (rule)
  HIGH     (report) → HIGH (rule)
  MEDIUM   (report) → MEDIUM (rule)
  LOW      (report) → LOW (rule)

Cross-references and de-duplication:

  * Wave 18 ``sandbox_escape_patterns.py`` (container/k8s/seccomp) —
    no overlap. That wave is POSIX sandbox primitives; this report is
    wasm-runtime-config and WASI capabilities.
  * Wave 21 ``rust_specific_patterns.py`` (Rust unsafe) — no overlap.
    That wave is host-language ``unsafe`` / FFI / raw-pointer casts.
    Wasmtime/wasmer host APIs are written in Rust, but the rule set
    here targets the wasm runtime configuration API surface, not the
    host's general-purpose unsafe usage.
  * Wave 16 ``per_language_patterns.py`` does not cover wasm runtimes.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    ``scripts/lib/rust_specific_patterns.Finding`` so heartbeat
    detectors can render any of these patterns uniformly."""

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
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with MULTILINE+UNICODE.

    Wasm/Rust/JS identifiers are case-sensitive — so the regexes here
    do NOT use IGNORECASE for code constructs. TOML/YAML key regexes
    use a separate compile path that DOES allow case-insensitive
    matching at the parse layer (we apply ``\\b`` boundaries
    explicitly where needed).
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- B1: wasmtime::Config with no compute limit (no fuel, no epoch) ----


# `wasmtime::Config::new()` or `wasmtime::Config::default()` invocation.
# We split into two anchors: positive (Config is constructed) and
# negative (neither consume_fuel(true) nor epoch_interruption(true)
# appear in the same function/file). Pure regex can't reason about
# absence reliably, so we instead emit the rule when the construction
# appears AND `consume_fuel` does NOT appear in the same file (an
# 8KB window). The same approach as J7/J8/J9 in rust_specific.
_WASMTIME_CONFIG_CTOR = _re(
    r"\bwasmtime::Config::(?:new|default)\s*\(\s*\)"
)


# Co-occurrence: Config construction AND no `consume_fuel(true)` /
# `epoch_interruption(true)` anywhere in a 6KB window after it.
# We use negative lookahead with bounded scan window. The lookahead
# fires when the file contains construction but NO fuel/epoch knob.
_WASMTIME_NO_COMPUTE_LIMIT = _re(
    r"\bwasmtime::Config::(?:new|default)\s*\(\s*\)"
    r"(?![\s\S]{0,6000}?"
    r"(?:\.consume_fuel\s*\(\s*true\s*\)"
    r"|\.epoch_interruption\s*\(\s*true\s*\)))"
)


# ---- B2: wasmtime::Config without an explicit max_wasm_stack -----------


# Co-occurrence pattern: Config ctor AND no `.max_wasm_stack(`
# AND no `.async_stack_size(` in the next 6KB.
_WASMTIME_DEFAULT_STACK = _re(
    r"\bwasmtime::Config::(?:new|default)\s*\(\s*\)"
    r"(?![\s\S]{0,6000}?"
    r"(?:\.max_wasm_stack\s*\("
    r"|\.async_stack_size\s*\())"
)


# ---- B3: wasmtime::Config with unbounded linear memory -----------------


# Co-occurrence: Config ctor AND no `.static_memory_maximum_size(`
# AND no `.dynamic_memory_guard_size(` AND no `.static_memory_guard_size(`.
_WASMTIME_UNBOUNDED_MEMORY = _re(
    r"\bwasmtime::Config::(?:new|default)\s*\(\s*\)"
    r"(?![\s\S]{0,6000}?"
    r"(?:\.static_memory_maximum_size\s*\("
    r"|\.dynamic_memory_guard_size\s*\("
    r"|\.static_memory_guard_size\s*\("
    r"|\.memory_guaranteed_dense_image_size\s*\())"
)


# ---- B4: wasmtime::PoolingAllocationConfig with no total_* caps --------


# Anchor: PoolingAllocationConfig::default() / new().
# Negative: no `.total_memories(` / `.total_tables(` / `.total_stacks(`
# in the next 6KB.
_WASMTIME_POOLING_UNBOUNDED = _re(
    r"\b(?:wasmtime::)?PoolingAllocationConfig::(?:new|default)\s*\(\s*\)"
    r"(?![\s\S]{0,6000}?"
    r"(?:\.total_memories\s*\("
    r"|\.total_tables\s*\("
    r"|\.total_stacks\s*\())"
)


# ---- B5: wasmer Singlepass compiler used in production -----------------


# Singlepass::default() or Singlepass::new() — flag when not in tests.
# We can't reason about test-context from a regex, so we surface every
# Singlepass instantiation and let the caller route by file path.
_WASMER_SINGLEPASS = _re(
    r"\b(?:wasmer(?:_compiler_singlepass)?::)?Singlepass::(?:new|default)\s*\("
)


# ---- B6: wasmer Engine/Store without Metering middleware ---------------


# Co-occurrence: `wasmer::Engine::new(` / `wasmer::Store::new(` and
# no `Metering::new(` reference in the same 6KB window AFTER the ctor
# call. The forward lookahead catches the common "ctor → metering"
# ordering. The file-level guard ``_WASMER_METERING_FILE_GUARD`` is
# checked separately in ``scan_text`` to also catch the
# "metering → ctor" ordering (where the engine is constructed AFTER
# the metering middleware is configured).
_WASMER_NO_METERING = _re(
    r"\bwasmer::(?:Engine|Store)::new\s*\("
    r"(?![\s\S]{0,6000}?"
    r"(?:wasmer_middlewares::)?Metering::new\s*\()"
)
# File-level guard: if ``Metering::new`` appears ANYWHERE in the text
# (before or after the wasmer Engine/Store ctor), the engine is
# considered metered and the wasm-wasmer-no-metering rule is
# suppressed for this scan_text() invocation. This catches the
# variable-ordering case where ``let metering = Metering::new(...)``
# precedes ``wasmer::Engine::new(...)``.
_WASMER_METERING_FILE_GUARD = _re(
    r"\b(?:wasmer_middlewares::)?Metering::new\s*\("
)


# ---- B7: Module::deserialize on untrusted bytes ------------------------


# The three deserialize families that BYPASS wasm validation. Each is
# a separate match shape. We flag every site; the caller is expected
# to walk the arg dataflow to confirm untrusted source.
_MODULE_DESERIALIZE_UNCHECKED = _re(
    r"\b(?:wasmtime|wasmer)::Module::deserialize_unchecked\s*\("
)
_MODULE_DESERIALIZE_GENERIC = _re(
    r"\b(?:wasmtime|wasmer)::Module::deserialize"
    r"(?:_from_file)?\s*\("
)


# ---- B8: WasiCtxBuilder leaks the full host env ------------------------


# Two shapes: `.inherit_env()` (the explicit blanket grant) and
# `.envs(env::vars().collect())` / `.envs(env::vars_os().collect())`.
_WASI_INHERIT_ENV = _re(
    r"\.\s*inherit_env\s*\(\s*\)"
)
_WASI_ENVS_FULL_HOST = _re(
    r"\.\s*envs\s*\(\s*"
    r"(?:std::)?env::vars(?:_os)?\s*\(\s*\)"
    r"(?:\s*\.\s*collect\s*::<[^>]{0,200}>\s*\(\s*\)"
    r"|\s*\.\s*collect\s*\(\s*\))?"
    r"\s*\)"
)


# ---- B9: WasiCtxBuilder preopen at root / home / cwd -------------------


# Match `.preopen_dir(` plus a host-path argument that is "/" or "$HOME"
# or "~" or env::var("HOME") / dirs::home_dir() — a high-privilege
# location. We accept the host path as the FIRST argument of preopen_dir
# OR as the argument of `Dir::open_ambient_dir(...)` that's piped in.
# Two separate anchors keep the regex bounded.
_WASI_PREOPEN_ROOT_LITERAL = _re(
    r"\bDir::open_ambient_dir\s*\(\s*"
    r"\"(?:/|/Users|/home|~/?|/root)(?:[^\"]{0,200})?\""
)
_WASI_PREOPEN_HOME_ENV = _re(
    r"\bDir::open_ambient_dir\s*\(\s*"
    r"(?:std::)?env::var\s*\(\s*\"(?:HOME|USERPROFILE|PWD|CARGO_HOME|"
    r"GOPATH|XDG_DATA_HOME|XDG_CONFIG_HOME)\""
)
_WASI_PREOPEN_DIRS_HELPER = _re(
    r"\bDir::open_ambient_dir\s*\(\s*"
    r"(?:dirs|dirs_next|home)::"
    r"(?:home_dir|config_dir|data_dir|cache_dir|document_dir)\s*\(\s*\)"
)


# ---- B10: WASI network preopen — inherit_network / 0.0.0.0/0 -----------


_WASI_INHERIT_NETWORK = _re(
    r"\.\s*inherit_network\s*\(\s*\)"
)
_WASI_POOL_WILDCARD_IP = _re(
    r"\bipnet!\s*\(\s*\""
    r"(?:0\.0\.0\.0/0|::/0)"
    r"\""
)
_WASI_POOL_ANY_SOCKET = _re(
    r"\bSocketAddr::from\s*\(\s*\(\s*"
    r"\[\s*0\s*,\s*0\s*,\s*0\s*,\s*0\s*\]"
    r"\s*,\s*0\s*\)\s*\)"
)
# Shell-form: `wasmtime run ... --inherit-network`
_WASMTIME_CLI_INHERIT_NETWORK = _re(
    r"\bwasmtime\s+(?:run|serve)\b[^\n]{0,300}?--inherit-network\b"
)


# ---- B11: wasm-bindgen --target web artefact on Node side --------------


# Shell/script form: `wasm-pack build --target web` (the build flag),
# followed in the same repo by a Node `require()` of the artefact.
# We flag the build flag directly; the caller cross-references against
# package.json shape.
_WASM_PACK_TARGET_WEB = _re(
    r"\bwasm-pack\s+(?:build|publish)\b[^\n]{0,300}?--target(?:[\s=])web\b"
)


# ---- B12: Browser WebAssembly.instantiateStreaming without SRI ---------


# We flag every call site of the four instantiate APIs that take a
# fetch() argument with an absolute URL (different origin). The
# caller must verify whether SRI is set. We surface the API call
# itself and let routing logic gate.
_BROWSER_WASM_INSTANTIATE_STREAMING = _re(
    r"\bWebAssembly\s*\.\s*(?:instantiateStreaming|compileStreaming)"
    r"\s*\(\s*fetch\s*\(\s*"
)
# Absolute cross-origin URL in fetch — fires when fetch is called with
# a literal `https://` URL inside the wasm instantiate chain.
_BROWSER_WASM_FETCH_REMOTE = _re(
    r"\bWebAssembly\s*\.\s*(?:instantiateStreaming|compileStreaming"
    r"|instantiate|compile)"
    r"\s*\(\s*fetch\s*\(\s*[\"']https?://"
)


# ---- B13: Browser WebAssembly.instantiate of unbounded attacker bytes --


# Shape: an instantiate-from-buffer chain where the URL/bytes source
# is `window.location`, `URLSearchParams`, `localStorage`, `event.data`.
# We flag the dataflow-anchor: an instantiate call following a
# searchParams/localStorage/event-data assignment in the same 4KB window.
_BROWSER_WASM_FROM_SEARCHPARAMS = _re(
    r"\bnew\s+URLSearchParams\s*\([\s\S]{0,200}?\)"
    r"[\s\S]{0,4000}?"
    r"\bWebAssembly\s*\.\s*(?:instantiate|compile|instantiateStreaming"
    r"|compileStreaming)\s*\("
)
_BROWSER_WASM_FROM_LOCALSTORAGE = _re(
    r"\blocalStorage\s*\.\s*getItem\s*\([\s\S]{0,200}?\)"
    r"[\s\S]{0,4000}?"
    r"\bWebAssembly\s*\.\s*(?:instantiate|compile|instantiateStreaming"
    r"|compileStreaming)\s*\("
)


# ---- B14: wasm-features = "all" (TOML/CLI) -----------------------------


# TOML form: `features = "all"` inside `[wasm]` / `[wasm-tools]` table,
# OR a CLI flag `--wasm-features=all` / `--wasm-features all` in any
# script.
_WASM_FEATURES_ALL_TOML = _re(
    r"^\s*(?:features|wasm[-_]features)\s*=\s*"
    r"\[?\s*[\"']all[\"']\s*\]?"
)
_WASMTIME_CLI_FEATURES_ALL = _re(
    r"--wasm-features(?:[\s=])all\b"
)
# Rust Config builder: 4+ proposal-stage feature toggles flipped true.
# We surface every individual toggle and let the caller correlate.
_WASMTIME_CFG_FEATURE_TOGGLE = _re(
    r"\.\s*wasm_(?:threads|relaxed_simd|gc|function_references"
    r"|multi_memory|memory64|tail_call|exceptions|component_model"
    r"|bulk_memory|reference_types|simd)"
    r"\s*\(\s*true\s*\)"
)


# ---- B15: Spin / Fermyon manifest allowed_outbound_hosts = ["*"] -------


# TOML: `allowed_outbound_hosts = ["*"]` or `["https://*:*"]`.
# We accept either spin.toml or fermyon.toml.
_SPIN_OUTBOUND_WILDCARD = _re(
    r"^\s*allowed_outbound_hosts\s*=\s*"
    r"\[\s*"
    r"[\"'](?:\*"
    r"|(?:https?|\*)://\*(?::\*)?"
    r"|(?:https?|\*)://[\w*.-]*\*[\w*.-]*"
    r")[\"']"
)
# Older shape: `allowed_http_hosts = ["*"]`.
_SPIN_HTTP_WILDCARD = _re(
    r"^\s*allowed_http_hosts\s*=\s*"
    r"\[\s*[\"']\*[\"']"
)
# SSRF-prone literal endpoints in outbound allowlist.
#
# Hosts can appear as the bare quoted value (``"169.254.169[.]254"``)
# OR inside a URL string (``"http://169.254.169[.]254"``,
# ``"http://localhost:8080"``). We anchor on the lead-in character —
# a quote, a slash (`//` from `http://`), or a `@` (user@host) —
# and on the trail-out character: a quote, port colon, path slash.
# The boundary set ``[\"'/@]`` covers every reasonable lead-in,
# the boundary set ``[\"':/]`` every reasonable trail-out.
_SPIN_OUTBOUND_SSRF_TARGET = _re(
    r"^\s*allowed_(?:outbound_hosts|http_hosts)\s*=\s*\[[^\n]{0,300}?"
    r"[\"'/@](?:"
    r"169\.254\.169\.254"
    r"|metadata\.google\.internal"
    r"|metadata\.azure\.com"
    r"|localhost"
    r"|127\.0\.0\.1"
    r")[\"':/]"
)


# ---- B16: Deno permission flags without scope --------------------------


# Each `--allow-*` flag with no `=scope` suffix.
# We capture `--allow-net` (no `=`), `--allow-read`, `--allow-write`,
# `--allow-env`, `--allow-run`, plus the catch-all `-A`.
_DENO_ALLOW_NET_UNSCOPED = _re(
    r"\bdeno\s+(?:run|test|bench|install|task|serve|repl|eval)\b"
    r"[^\n]{0,600}?--allow-net\b(?!\s*=)"
)
_DENO_ALLOW_READ_UNSCOPED = _re(
    r"\bdeno\s+(?:run|test|bench|install|task|serve|repl|eval)\b"
    r"[^\n]{0,600}?--allow-read\b(?!\s*=)"
)
_DENO_ALLOW_WRITE_UNSCOPED = _re(
    r"\bdeno\s+(?:run|test|bench|install|task|serve|repl|eval)\b"
    r"[^\n]{0,600}?--allow-write\b(?!\s*=)"
)
_DENO_ALLOW_ENV_UNSCOPED = _re(
    r"\bdeno\s+(?:run|test|bench|install|task|serve|repl|eval)\b"
    r"[^\n]{0,600}?--allow-env\b(?!\s*=)"
)
_DENO_ALLOW_RUN_UNSCOPED = _re(
    r"\bdeno\s+(?:run|test|bench|install|task|serve|repl|eval)\b"
    r"[^\n]{0,600}?--allow-run\b(?!\s*=)"
)
_DENO_ALLOW_ALL = _re(
    r"\bdeno\s+(?:run|test|bench|install|task|serve|repl|eval)\b"
    r"[^\n]{0,600}?(?:--allow-all\b|(?<=\s)-A\b)"
)


# ---- B17: Deno --unstable in production --------------------------------


_DENO_UNSTABLE_LEGACY = _re(
    r"\bdeno\s+(?:run|test|bench|install|task|serve|repl|eval)\b"
    r"[^\n]{0,600}?--unstable\b(?!-)"
)
_DENO_UNSTABLE_FEATURE = _re(
    r"\bdeno\s+(?:run|test|bench|install|task|serve|repl|eval)\b"
    r"[^\n]{0,600}?--unstable-(?:bare-node-builtins|byonm|sloppy-imports"
    r"|temporal|worker-options|broadcast-channel|net|cron|kv|ffi"
    r"|http|node-globals|process|fs|webgpu|otel)\b"
)


# ---- B18: deno cache + deno run permission split -----------------------


# Anchor: a `deno cache` invocation followed in the same file by a
# `deno run` / `deno test` / `deno install` invocation. We flag the
# combination; the human verifies whether deno.lock is committed.
_DENO_CACHE_THEN_RUN = _re(
    r"\bdeno\s+cache\b[^\n]{0,600}"
    r"[\s\S]{0,4000}?"
    r"\bdeno\s+(?:run|test|install)\b"
)


# ---- B19: Node WebAssembly.instantiate without Worker isolation --------


# Anchor: `WebAssembly.instantiate(Buffer.from(...))` or
# `WebAssembly.instantiate(fs.readFile...)` or
# `WebAssembly.instantiate(require(...))`.
# We flag every call where the source argument is `Buffer.from(`,
# `fs.readFileSync(`, or `fs.readFile(`. The caller decides whether
# a Worker boundary exists.
_NODE_WASM_INSTANTIATE_BUFFER = _re(
    r"\bWebAssembly\s*\.\s*(?:instantiate|compile)"
    r"\s*\(\s*Buffer\s*\.\s*from\s*\("
)
_NODE_WASM_INSTANTIATE_FSREAD = _re(
    r"\bWebAssembly\s*\.\s*(?:instantiate|compile)"
    r"\s*\(\s*(?:await\s+)?fs(?:\s*\.\s*promises)?"
    r"\s*\.\s*readFile(?:Sync)?\s*\("
)


# ---- B20: host import exposing privileged stdlib without capability ----


# `Linker::func_wrap(` or `linker.func_wrap(` (instance receiver)
# followed in the body by `std::fs::*` / `std::process::Command` /
# `tokio::fs::*` / `reqwest::*` / `libloading::*` / `tokio::net::*` —
# within a 6KB window. The receiver shape can be either the
# ``Linker`` type (rare) or a snake_case binding like ``linker``,
# ``my_linker``, ``store_linker_v2`` — i.e. any identifier ending in
# the case-insensitive substring ``linker``. The ``\w{0,40}linker``
# prefix bound keeps the identifier match RE2-safe; ``\w`` is the
# Rust identifier character class.
_WASMTIME_LINKER_PRIVILEGED = _re(
    r"\b\w{0,40}[Ll]inker"
    r"(?:::<[^>]{0,200}>)?\s*\.\s*func_wrap\s*\("
    r"[\s\S]{0,6000}?"
    r"\b(?:std::fs::(?:read|write|read_to_string|read_to_end|"
    r"File::open|File::create|remove_file|remove_dir|create_dir)"
    r"|std::process::Command"
    r"|tokio::fs::"
    r"|reqwest::(?:get|post|put|delete|Client)"
    r"|libloading::"
    r"|tokio::net::)"
)
# Wasmer equivalent: `imports!` macro or `Instance::new_with_imports`
# followed by the same privileged primitives.
_WASMER_IMPORTS_PRIVILEGED = _re(
    r"\b(?:imports!\s*\{"
    r"|wasmer::Instance::new_with_imports\s*\("
    r"|wasmer::Function::new\s*\(\s*&mut\s+\w+\s*,\s*&[^,]{0,200}?,"
    r"\s*\|)"
    r"[\s\S]{0,6000}?"
    r"\b(?:std::fs::(?:read|write|read_to_string|read_to_end|"
    r"File::open|File::create)"
    r"|std::process::Command"
    r"|tokio::fs::"
    r"|reqwest::(?:get|post|put|delete|Client))"
)


# ---- B21: WIT-bindgen: ambiguous component-export name shadowing -------


# A `.wit` file with an `export` clause naming a package import
# that is ALSO declared as an `import` clause in the same world.
# We flag exports whose names start with `wasi:`, `host:` — namespaces
# that the host should reserve.
_WIT_EXPORT_WASI_OR_HOST = _re(
    r"^\s*export\s+"
    r"(?:wasi:(?:filesystem|http|sockets|clocks|cli|preopens|random)"
    r"|host:[a-zA-Z][\w-]*)"
    r"/[a-zA-Z][\w-]*"
)
# A world with an export that matches the name of its own import —
# the squat-self case. We surface every `export <ns>/<intf>` whose
# `<ns>` is the same as an earlier-line `import <ns>/<intf>`.
# Pure regex can't pair these — we instead flag any export of
# `pkg:logging/log` style names that look reserved (single word
# colon double-word).
_WIT_AMBIGUOUS_EXPORT = _re(
    r"^\s*export\s+"
    r"[a-z][\w-]*:[a-z][\w-]*/[a-z][\w-]*"
    r"\s*;"
)


# ---- B22: WasmEdge plugin from an unsigned untrusted path --------------


_WASMEDGE_PLUGIN_LOAD_FROM_C = _re(
    r"\bWasmEdge_PluginLoadFromPath\s*\("
)
_WASMEDGE_PLUGIN_LOAD_FROM_CPP = _re(
    r"\b(?:wasmedge::|WasmEdge::)?PluginManager"
    r"\s*(?:::|\.)\s*loadFromPath\s*\("
)


# ---- B23: wasm memory.grow unbounded — module declares no maximum ------


# We can't parse wasm binary from regex. But `.wat` text-format wasm
# is readable: `(memory (export "memory") N)` with no second integer
# (= no maximum). We flag every `.wat` memory declaration missing a
# maximum.
_WAT_MEMORY_NO_MAX = _re(
    r"^\s*\(memory\s+"
    r"(?:\(\s*export\s+\"[^\"]{0,200}\"\s*\)\s+)?"
    r"\d{1,5}\s*\)"
)


# ---- B24: wasm-bindgen --target web AND --no-modules -------------------


_WASM_BINDGEN_NO_MODULES = _re(
    r"\bwasm-pack\s+(?:build|publish)\b"
    r"[^\n]{0,300}?--target(?:[\s=])web\b"
    r"[^\n]{0,300}?--no-modules\b"
)
# Reversed order — both flags appear in either order.
_WASM_BINDGEN_NO_MODULES_REV = _re(
    r"\bwasm-pack\s+(?:build|publish)\b"
    r"[^\n]{0,300}?--no-modules\b"
    r"[^\n]{0,300}?--target(?:[\s=])web\b"
)


# ---- B25: wasi-cli --dir=. (CWD preopen) -------------------------------


# `wasmtime run --dir=.::.` / `wasmtime run --dir .` /
# `wasmedge --dir .:.` (CWD-to-CWD shorthand) / `wasmer --dir=$PWD`.
# All of these CWD preopen forms.
#
# Subcommand handling: ``wasmtime`` and ``wasmer`` use ``run``/``serve``,
# but ``wasmedge`` invokes directly (``wasmedge --dir .:. module.wasm``)
# with no subcommand. The pattern ``(?:(?:run|serve)\s+)?`` is wrapped
# so the optional group consumes the trailing whitespace alongside the
# subcommand — this avoids leaving the position at a non-word/non-word
# boundary that ``\b`` would reject when the subcommand is absent.
_WASMTIME_CLI_DIR_CWD = _re(
    r"\b(?:wasmtime|wasmer|wasmedge)\s+(?:(?:run|serve)\s+)?"
    r"[^\n]{0,300}?"
    r"--dir(?:[\s=])"
    r"(?:\.(?::\.)?"
    r"|\$PWD(?:::\$PWD)?"
    r"|\$\{PWD\}(?:::\$\{PWD\})?"
    r"|\.\/?(?:::\.\/?)?"
    r")(?:\s|$|\")"
)
# `--dir=$(pwd)` shell-substitution shape.
_WASMTIME_CLI_DIR_PWD_SUB = _re(
    r"\b(?:wasmtime|wasmer|wasmedge)\s+(?:(?:run|serve)\s+)?"
    r"[^\n]{0,300}?"
    r"--dir(?:[\s=])\$\(pwd\)"
)


# ---- Rule catalogue ----------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="wasm-wasmtime-no-compute-limit",
        name="`wasmtime::Config` built without fuel OR epoch interruption",
        severity="HIGH",
        description=(
            "`wasmtime::Config::new()`/`::default()` built without either "
            "`.consume_fuel(true)` or `.epoch_interruption(true)`. Both "
            "knobs disabled means an attacker-supplied module can run an "
            "infinite loop with no host interrupt path — the wasm equivalent "
            "of 'no timeout on a regex engine.' Always enable at least one."
        ),
        pattern=_WASMTIME_NO_COMPUTE_LIMIT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="wasm-wasmtime-default-stack",
        name="`wasmtime::Config` built without explicit `.max_wasm_stack(...)`",
        severity="MEDIUM",
        description=(
            "`wasmtime::Config` constructed with no `.max_wasm_stack(N)` "
            "and no `.async_stack_size(N)`. Default 1 MiB × N concurrent "
            "stores blows host RSS; an attacker that spawns many "
            "concurrent compilation requests can DoS the host. Cap stack "
            "at the smallest viable value (64 KiB–256 KiB typical)."
        ),
        pattern=_WASMTIME_DEFAULT_STACK,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="wasm-wasmtime-unbounded-memory",
        name="`wasmtime::Config` with default 4 GiB static memory reservation",
        severity="HIGH",
        description=(
            "`wasmtime::Config` built with no `.static_memory_maximum_size`, "
            "no `.dynamic_memory_guard_size`, no `.static_memory_guard_size`. "
            "Default on 64-bit hosts is 4 GiB virtual per store; "
            "a few hundred concurrent stores reserve ~1 TiB of VM. "
            "Bound to the smallest viable value (often 64 MiB–256 MiB)."
        ),
        pattern=_WASMTIME_UNBOUNDED_MEMORY,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="wasm-wasmtime-pooling-unbounded",
        name="`PoolingAllocationConfig` without `total_memories/tables/stacks`",
        severity="HIGH",
        description=(
            "`PoolingAllocationConfig::default()` / `::new()` with no "
            "`.total_memories(N)` / `.total_tables(N)` / `.total_stacks(N)` "
            "cap. The pooling allocator pre-reserves memory regions — "
            "unbounded means startup DoS as an attacker opens many stores."
        ),
        pattern=_WASMTIME_POOLING_UNBOUNDED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="wasm-wasmer-singlepass",
        name="`wasmer::Singlepass::default()` / `Singlepass::new()` in production",
        severity="MEDIUM",
        description=(
            "Singlepass compiler used outside tests. Singlepass is fast-"
            "compile but generates less hardened code than Cranelift — "
            "no Spectre mitigation passes by default, looser bounds checks. "
            "Production wasm hosts should default to Cranelift unless "
            "cold-start latency is the explicit goal."
        ),
        pattern=_WASMER_SINGLEPASS,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="wasm-wasmer-no-metering",
        name="`wasmer::Engine`/`Store::new` without Metering middleware",
        severity="HIGH",
        description=(
            "`wasmer::Engine::new(...)` / `wasmer::Store::new(...)` built "
            "without `wasmer_middlewares::Metering`. Metering is the wasmer "
            "equivalent of wasmtime's fuel — without it there is no compute "
            "bound on a guest. Same DoS class as the wasmtime no-fuel rule."
        ),
        pattern=_WASMER_NO_METERING,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="wasm-module-deserialize-unchecked",
        name="`Module::deserialize_unchecked(bytes)` — bypasses validation",
        severity="CRITICAL",
        description=(
            "`Module::deserialize_unchecked` skips wasm validation entirely. "
            "It trusts that the bytes are a valid compiled artefact for "
            "this engine. A malicious file at the cache path becomes "
            "arbitrary host code execution — the wasm equivalent of "
            "deserialising an attacker's pickle. Both wasmtime and wasmer "
            "docs explicitly warn against the unsafe variant."
        ),
        pattern=_MODULE_DESERIALIZE_UNCHECKED,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wasm-module-deserialize-generic",
        name="`Module::deserialize(...)` on bytes (verify signature/source)",
        severity="HIGH",
        description=(
            "`Module::deserialize(bytes)` / `Module::deserialize_from_file` "
            "loads a pre-compiled artefact. The caller MUST verify the "
            "bytes were either signed by the operator OR produced in the "
            "current process from `Module::serialize`. Loading from disk/"
            "network/CLI args without verification is arbitrary code "
            "execution at module-load time."
        ),
        pattern=_MODULE_DESERIALIZE_GENERIC,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wasm-wasi-inherit-env",
        name="`WasiCtxBuilder::inherit_env()` — full host env to guest",
        severity="HIGH",
        description=(
            "`.inherit_env()` passes the entire host process environment "
            "to the guest. Host env routinely contains `AWS_*`, "
            "`GITHUB_TOKEN`, `OPENAI_API_KEY`, `DATABASE_URL` — leaking "
            "the full set gives the guest blanket cloud access. Allow-list "
            "specific keys instead: `.env(\"PATH\", env::var(\"PATH\").unwrap_or_default())`."
        ),
        pattern=_WASI_INHERIT_ENV,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-wasi-envs-full-host",
        name="`.envs(env::vars().collect())` — full host env to guest",
        severity="HIGH",
        description=(
            "`.envs(env::vars().collect())` / `.envs(env::vars_os().collect())` "
            "passes the full host environment to the guest. Same risk as "
            "`.inherit_env()`. Filter to an allow-list."
        ),
        pattern=_WASI_ENVS_FULL_HOST,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-wasi-preopen-root-literal",
        name="`Dir::open_ambient_dir(\"/\")` or `\"/home\"` / `\"~\"` preopen",
        severity="CRITICAL",
        description=(
            "`Dir::open_ambient_dir(\"/\")` (or `/Users`, `/home`, `/root`, "
            "`~`) re-grants the host filesystem root to the guest, defeating "
            "wasm's 'no ambient authority' promise. WASI documentation is "
            "explicit: preopens should be at the narrowest viable path."
        ),
        pattern=_WASI_PREOPEN_ROOT_LITERAL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-wasi-preopen-home-env",
        name="`Dir::open_ambient_dir(env::var(\"HOME\"))` preopen at $HOME",
        severity="CRITICAL",
        description=(
            "Preopening at `$HOME` / `$USERPROFILE` / `$PWD` / `$CARGO_HOME` / "
            "`$GOPATH` / `$XDG_DATA_HOME` leaks SSH keys, `.aws/credentials`, "
            "`.npmrc`, repo `.env` files, and toolchain secrets to the guest. "
            "Scope to a dedicated `inputs/` subdirectory."
        ),
        pattern=_WASI_PREOPEN_HOME_ENV,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-wasi-preopen-dirs-helper",
        name="`Dir::open_ambient_dir(dirs::home_dir())` preopen via dirs crate",
        severity="HIGH",
        description=(
            "`dirs::home_dir()` / `dirs::config_dir()` / `dirs::data_dir()` "
            "resolved as preopen host paths. Same risk class as "
            "$HOME-env preopen — the guest sees the user's full toolchain "
            "config + cached secrets."
        ),
        pattern=_WASI_PREOPEN_DIRS_HELPER,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-wasi-inherit-network",
        name="`WasiCtxBuilder::inherit_network()` — full host network to guest",
        severity="HIGH",
        description=(
            "`.inherit_network()` grants the guest unrestricted host "
            "network. The guest can `connect()` to AWS metadata "
            "(169.254.169[.]254), localhost (other guests + host services), "
            "and arbitrary external hosts (data exfil + SSRF). WASI's "
            "fine-grained allowlist proposal isn't stable yet — wrap the "
            "Pool with a CIDR allow-list of expected destinations."
        ),
        pattern=_WASI_INHERIT_NETWORK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-wasi-pool-wildcard-ip",
        name="`cap-std::net::Pool::insert_ip_net(\"0.0.0.0/0\")` — open network",
        severity="HIGH",
        description=(
            "`ipnet!(\"0.0.0.0/0\")` / `\"::/0\"` in a cap-std Pool grants "
            "the entire IPv4/IPv6 address space. Same risk as "
            "`inherit_network()`. CIDR-allowlist to expected destinations."
        ),
        pattern=_WASI_POOL_WILDCARD_IP,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-wasi-pool-any-socket",
        name="`Pool::insert_socket_addr(SocketAddr::from(([0,0,0,0], 0)))` — open network",
        severity="HIGH",
        description=(
            "Inserting `0.0.0.0:0` into a cap-std Pool means the host "
            "binds to all interfaces, all ports — equivalent to "
            "`inherit_network()`. Pin the listen interface AND port."
        ),
        pattern=_WASI_POOL_ANY_SOCKET,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-wasmtime-cli-inherit-network",
        name="`wasmtime run --inherit-network` — full host network",
        severity="HIGH",
        description=(
            "The wasmtime CLI `--inherit-network` flag grants the guest "
            "unrestricted host network. Same risk as the Rust API rule. "
            "Use `--allow-ip` / `--allow-host` with explicit destinations."
        ),
        pattern=_WASMTIME_CLI_INHERIT_NETWORK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-wasm-pack-target-web",
        name="`wasm-pack build --target web` artefact (verify not on Node)",
        severity="MEDIUM",
        description=(
            "A `wasm-pack build --target web` artefact built for the "
            "browser. The caller must verify it's not imported from a "
            "Node.js process — `--target=web` glue does "
            "`fetch(import.meta.url)` which on Node either fails or "
            "silently hits a shimmed fetch. Backend wasm should use "
            "`--target=nodejs` or `--target=bundler`."
        ),
        pattern=_WASM_PACK_TARGET_WEB,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wasm-browser-instantiate-streaming",
        name="`WebAssembly.instantiateStreaming(fetch(...))` — verify SRI",
        severity="MEDIUM",
        description=(
            "`WebAssembly.instantiateStreaming(fetch(...))` / "
            "`compileStreaming(fetch(...))` call. The caller MUST verify "
            "the fetch carries `integrity` (SRI) when the URL is "
            "cross-origin. Without SRI, a CDN takeover / DNS hijack / "
            "BGP attack substitutes arbitrary wasm into every visitor's "
            "session."
        ),
        pattern=_BROWSER_WASM_INSTANTIATE_STREAMING,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wasm-browser-fetch-remote",
        name="`WebAssembly.instantiate(fetch(\"https://...\"))` cross-origin",
        severity="HIGH",
        description=(
            "Browser-side wasm load from an absolute `https://` URL. "
            "If the URL is a third-party CDN, a takeover plants arbitrary "
            "code into the page. Use SRI (`integrity=\"sha256-...\"`), "
            "lock CSP to `'self'`, OR serve the wasm same-origin."
        ),
        pattern=_BROWSER_WASM_FETCH_REMOTE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wasm-browser-from-searchparams",
        name="WebAssembly.instantiate of bytes derived from URLSearchParams",
        severity="HIGH",
        description=(
            "Browser-side wasm instantiation where the URL/bytes flow "
            "from `new URLSearchParams(...).get(...)`. Attacker-controlled "
            "query string → arbitrary wasm executed. Combined with the "
            "no-SRI rule, a single hostile link can both DoS and pwn "
            "every visitor that follows it."
        ),
        pattern=_BROWSER_WASM_FROM_SEARCHPARAMS,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wasm-browser-from-localstorage",
        name="WebAssembly.instantiate of bytes from localStorage",
        severity="MEDIUM",
        description=(
            "Browser-side wasm where the bytes flow from "
            "`localStorage.getItem(...)`. Any prior XSS that wrote to "
            "localStorage becomes wasm execution on the next page load — "
            "a persistence vector for ephemeral XSS payloads."
        ),
        pattern=_BROWSER_WASM_FROM_LOCALSTORAGE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wasm-features-all-toml",
        name="`wasm-features = \"all\"` / `features = \"all\"` (proposal-stage)",
        severity="HIGH",
        description=(
            "A TOML config enabling all proposal-stage wasm features. "
            "Proposal-stage features have less battle-tested implementations: "
            "`threads` opens shared memory + atomics (Spectre surface), "
            "`gc` opens host-allocator pressure, `relaxed_simd` has "
            "platform-dependent semantics. Stage-4 features only is the "
            "defensible default."
        ),
        pattern=_WASM_FEATURES_ALL_TOML,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wasm-cli-features-all",
        name="`wasmtime run --wasm-features=all` (proposal-stage features on)",
        severity="HIGH",
        description=(
            "CLI flag enabling all proposal-stage wasm features. Same risk "
            "as the TOML form — Spectre attack surface from `threads`, "
            "platform-dependent UB from `relaxed_simd`, host-allocator "
            "pressure from `gc`."
        ),
        pattern=_WASMTIME_CLI_FEATURES_ALL,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wasm-cfg-feature-toggle",
        name="`wasmtime::Config::wasm_<feature>(true)` (proposal-stage toggle)",
        severity="MEDIUM",
        description=(
            "Individual proposal-stage feature toggle: `wasm_threads(true)`, "
            "`wasm_relaxed_simd(true)`, `wasm_gc(true)`, "
            "`wasm_function_references(true)`, `wasm_multi_memory(true)`, "
            "etc. Surface each — when 4+ appear in the same file, treat "
            "as equivalent to the `--wasm-features=all` rule."
        ),
        pattern=_WASMTIME_CFG_FEATURE_TOGGLE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="wasm-spin-outbound-wildcard",
        name="Spin/Fermyon manifest `allowed_outbound_hosts = [\"*\"]`",
        severity="HIGH",
        description=(
            "A `spin.toml` / `fermyon.toml` manifest with "
            "`allowed_outbound_hosts = [\"*\"]` (or `[\"https://*:*\"]`, "
            "`[\"*://*:*\"]`). This is the Spin equivalent of CORS `*` — "
            "the guest can fetch arbitrary external hosts and (worse) "
            "internal cloud metadata endpoints. Spin's docs explicitly "
            "recommend host-by-host allowlisting."
        ),
        pattern=_SPIN_OUTBOUND_WILDCARD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-spin-http-wildcard",
        name="Spin manifest `allowed_http_hosts = [\"*\"]` (older form)",
        severity="HIGH",
        description=(
            "Older Spin manifests use `allowed_http_hosts` instead of "
            "`allowed_outbound_hosts`. Same wildcard risk class. Migrate "
            "to the newer key AND replace the wildcard with explicit hosts."
        ),
        pattern=_SPIN_HTTP_WILDCARD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-spin-outbound-ssrf-target",
        name="Spin manifest outbound allow contains cloud metadata / localhost",
        severity="CRITICAL",
        description=(
            "Spin manifest `allowed_outbound_hosts` / `allowed_http_hosts` "
            "list includes `169.254.169[.]254` (AWS/Azure IMDS), "
            "`metadata.google[.]internal` (GCP IMDS), `localhost`, or "
            "`127.0.0.1`. These are the prime SSRF targets — granting "
            "access lets a compromised guest harvest cloud-credentials "
            "and pivot to internal host services."
        ),
        pattern=_SPIN_OUTBOUND_SSRF_TARGET,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-deno-allow-net-unscoped",
        name="`deno run --allow-net` (no `=host:port` scope)",
        severity="HIGH",
        description=(
            "Unscoped `--allow-net` grants unrestricted network access — "
            "equivalent to running Node with no sandbox at all, but worse "
            "because it gives the false impression of being sandboxed in "
            "code review. Always scope: `--allow-net=api.example.com:443`."
        ),
        pattern=_DENO_ALLOW_NET_UNSCOPED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-deno-allow-read-unscoped",
        name="`deno run --allow-read` (no `=path` scope)",
        severity="HIGH",
        description=(
            "Unscoped `--allow-read` lets the script read any file on the "
            "host — including `.env`, `.ssh/`, `.aws/credentials`. "
            "Always scope: `--allow-read=./data,./config`."
        ),
        pattern=_DENO_ALLOW_READ_UNSCOPED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-deno-allow-write-unscoped",
        name="`deno run --allow-write` (no `=path` scope)",
        severity="HIGH",
        description=(
            "Unscoped `--allow-write` lets the script overwrite any "
            "writable file — including `~/.bashrc`, `~/.ssh/authorized_keys`. "
            "Always scope: `--allow-write=./tmp`."
        ),
        pattern=_DENO_ALLOW_WRITE_UNSCOPED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-deno-allow-env-unscoped",
        name="`deno run --allow-env` (no `=VAR1,VAR2` scope)",
        severity="HIGH",
        description=(
            "Unscoped `--allow-env` lets the script read the entire host "
            "environment — including secrets like `AWS_*`, `GITHUB_TOKEN`. "
            "Always scope: `--allow-env=API_KEY,DATABASE_URL`."
        ),
        pattern=_DENO_ALLOW_ENV_UNSCOPED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-deno-allow-run-unscoped",
        name="`deno run --allow-run` (no `=cmd1,cmd2` scope)",
        severity="HIGH",
        description=(
            "Unscoped `--allow-run` lets the script execute arbitrary "
            "host subprocesses — effectively shell access. Always scope: "
            "`--allow-run=git,curl`."
        ),
        pattern=_DENO_ALLOW_RUN_UNSCOPED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-deno-allow-all",
        name="`deno run -A` / `--allow-all` (grant every permission)",
        severity="CRITICAL",
        description=(
            "`-A` / `--allow-all` grants every permission. This is "
            "equivalent to a Node script with full host privileges — but "
            "it gives the *false impression* of being sandboxed in code "
            "review. Never use; always granular-scope each `--allow-*`."
        ),
        pattern=_DENO_ALLOW_ALL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-deno-unstable-legacy",
        name="`deno run --unstable` (legacy blanket unstable flag)",
        severity="MEDIUM",
        description=(
            "Legacy `--unstable` flag opts the script into all unstable "
            "APIs at once. Unstable APIs have weaker security review and "
            "are subject to breaking changes. Move to per-feature "
            "`--unstable-<name>` and reduce to the minimum set actually "
            "needed."
        ),
        pattern=_DENO_UNSTABLE_LEGACY,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wasm-deno-unstable-feature",
        name="`deno run --unstable-<feature>` (per-feature unstable flag)",
        severity="MEDIUM",
        description=(
            "Per-feature unstable flag in production / CI. `--unstable-ffi` "
            "in particular grants FFI (native shared library load) — "
            "functionally equivalent to escaping the sandbox. Audit each "
            "flag against the deno docs and the production-vs-experiment "
            "context."
        ),
        pattern=_DENO_UNSTABLE_FEATURE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wasm-deno-cache-then-run",
        name="`deno cache` followed by `deno run` — verify `--lock=deno.lock`",
        severity="HIGH",
        description=(
            "CI / Dockerfile that runs `deno cache` and then `deno run` / "
            "`deno test` / `deno install` in the same file. A malicious "
            "dep fetched at `deno cache` time can plant code that only "
            "runs once the broader run-time permissions are granted by "
            "`deno run`. Defence: always `deno cache --lock=deno.lock "
            "--lock-write` and commit `deno.lock`."
        ),
        pattern=_DENO_CACHE_THEN_RUN,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wasm-node-wasm-instantiate-buffer",
        name="`WebAssembly.instantiate(Buffer.from(...))` in Node — verify isolation",
        severity="MEDIUM",
        description=(
            "Node.js `WebAssembly.instantiate(Buffer.from(...))` call. "
            "The caller MUST verify the bytes are from a trusted source "
            "AND that wasm execution is isolated (e.g. in a "
            "`worker_threads.Worker` with no host bindings). Otherwise "
            "the guest's host imports get full Node authority."
        ),
        pattern=_NODE_WASM_INSTANTIATE_BUFFER,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-node-wasm-instantiate-fsread",
        name="`WebAssembly.instantiate(fs.readFileSync(...))` in Node",
        severity="MEDIUM",
        description=(
            "Node.js wasm instantiation from `fs.readFile(Sync)?` — "
            "verify isolation. If the file path is user-controlled, "
            "this is a direct path-to-RCE conversion."
        ),
        pattern=_NODE_WASM_INSTANTIATE_FSREAD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-host-import-privileged-wasmtime",
        name="`wasmtime::Linker::func_wrap` exposing fs/process/net stdlib",
        severity="HIGH",
        description=(
            "A wasmtime `Linker::func_wrap(...)` whose body calls "
            "`std::fs::*`, `std::process::Command`, `tokio::fs::*`, "
            "`reqwest::*`, `libloading::*`, or `tokio::net::*` — without "
            "a capability-token boundary. The guest now reaches the full "
            "host attack surface through the import. Mitigation: capability "
            "tokens (integer handles to specific resources), not raw paths."
        ),
        pattern=_WASMTIME_LINKER_PRIVILEGED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-host-import-privileged-wasmer",
        name="`wasmer::imports!` / Instance::new_with_imports exposing privileged stdlib",
        severity="HIGH",
        description=(
            "A wasmer `imports! { ... }` block or "
            "`Instance::new_with_imports(...)` whose registered functions "
            "call `std::fs::*` / `std::process::Command` / `tokio::*` / "
            "`reqwest::*`. Same architectural failure as the wasmtime "
            "rule — wasm is sandboxed but the host import re-introduces "
            "the unsandboxed-host attack surface."
        ),
        pattern=_WASMER_IMPORTS_PRIVILEGED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-wit-export-wasi-or-host",
        name="`*.wit` `export wasi:.../...` or `export host:.../...` — name squat",
        severity="MEDIUM",
        description=(
            "A component exporting an interface under the `wasi:` or "
            "`host:` namespace can spoof the host's own exports if the "
            "linker resolves by string instead of by hash. A malicious "
            "component that exports `wasi:filesystem/preopens` and "
            "registers first intercepts every later component's preopen "
            "request. Reserve `wasi:` / `host:` for the host."
        ),
        pattern=_WIT_EXPORT_WASI_OR_HOST,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wasm-wit-ambiguous-export",
        name="`*.wit` `export pkg:intf/name;` — verify no import shadow",
        severity="LOW",
        description=(
            "A WIT export of `pkg:intf/name` shape. The reviewer must "
            "cross-check that no sibling component imports the SAME "
            "`pkg:intf/name` and that the linker resolves to the intended "
            "exporter — name resolution in the WASM Component Model is "
            "by string, not by hash."
        ),
        pattern=_WIT_AMBIGUOUS_EXPORT,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wasm-wasmedge-plugin-load-c",
        name="`WasmEdge_PluginLoadFromPath(path)` — verify path is trusted",
        severity="HIGH",
        description=(
            "WasmEdge plugin path loaded from C API. WasmEdge plugins are "
            "native shared libraries — loading one is equivalent to "
            "`dlopen` on attacker bytes. Verify the path is a fixed "
            "system prefix (e.g. `/usr/lib/wasmedge/plugins/`) AND that "
            "the `.so`/`.dll` is signed."
        ),
        pattern=_WASMEDGE_PLUGIN_LOAD_FROM_C,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wasm-wasmedge-plugin-load-cpp",
        name="`PluginManager::loadFromPath(path)` — verify path is trusted",
        severity="HIGH",
        description=(
            "WasmEdge plugin path loaded from the C++/Rust binding. Same "
            "`dlopen-on-attacker-bytes` risk class as the C API. Verify "
            "signature + fixed system prefix."
        ),
        pattern=_WASMEDGE_PLUGIN_LOAD_FROM_CPP,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wasm-wat-memory-no-max",
        name="`.wat` `(memory ... N)` declared with no maximum",
        severity="MEDIUM",
        description=(
            "A `.wat` text-format module declares memory with an initial "
            "page count but no maximum: `(memory (export \"memory\") N)`. "
            "Combined with a host config that doesn't impose a per-store "
            "memory limit, the guest can `memory.grow` in a loop until "
            "the host config max (4 GiB default). Declare a max: "
            "`(memory (export \"memory\") N M)`."
        ),
        pattern=_WAT_MEMORY_NO_MAX,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="wasm-wasm-bindgen-no-modules",
        name="`wasm-pack build --target web --no-modules` (no ESM / no SRI)",
        severity="MEDIUM",
        description=(
            "`wasm-pack build --target web --no-modules` emits glue that "
            "attaches the WebAssembly instance to `window`, bypassing CSP "
            "`script-src` if the host page allows `'unsafe-inline'`. ESM "
            "modules + SRI are the modern baseline — `--no-modules` "
            "predates SRI-for-modules and trades safety for legacy browser "
            "compat."
        ),
        pattern=_WASM_BINDGEN_NO_MODULES,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wasm-wasm-bindgen-no-modules-rev",
        name="`wasm-pack build --no-modules --target web` (flag order reversed)",
        severity="MEDIUM",
        description=(
            "Same finding as the `--target web --no-modules` rule with "
            "the flag order reversed. ESM + SRI is the modern baseline."
        ),
        pattern=_WASM_BINDGEN_NO_MODULES_REV,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="wasm-wasi-cli-dir-cwd",
        name="`wasmtime run --dir=.` (CWD preopen leaks repo root)",
        severity="HIGH",
        description=(
            "`wasmtime run --dir=.` / `--dir=.::.` / `--dir=$PWD` / "
            "`wasmedge --dir .:.`. CWD on dev machines and CI is the "
            "repo root — leaks `.env`, `.git/config` (creds in URLs), "
            "`~/.ssh` when CWD == `$HOME`. Use a dedicated "
            "`inputs/` subdirectory containing only what the module needs."
        ),
        pattern=_WASMTIME_CLI_DIR_CWD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="wasm-wasi-cli-dir-pwd-sub",
        name="`wasmtime run --dir=$(pwd)` (CWD via shell substitution)",
        severity="HIGH",
        description=(
            "Shell-substitution form of the CWD preopen: `--dir=$(pwd)`. "
            "Same risk as `--dir=.`. Use a dedicated `inputs/` directory."
        ),
        pattern=_WASMTIME_CLI_DIR_PWD_SUB,
        owasp_asi="ASI-04",
    ),
)


# ---- Scanner -----------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against ``text`` and return findings.

    Findings are deduped by ``(rule_id, line, col)`` — a single line
    that triggers two rules emits two findings, but the same rule
    firing twice on the same line emits one.

    The caller is responsible for routing the right file type to the
    right rule — TOML rules (B14 TOML form, B15 Spin) fire on
    ``spin.toml``/``fermyon.toml``/``Cargo.toml`` files, shell rules
    (B10 CLI, B16 Deno, B25 CLI dir) fire on shell scripts / CI YAML,
    WIT rules (B21) fire on ``*.wit`` files, the rest fire on
    ``.rs`` / ``.js`` / ``.ts`` / ``.wat`` sources. The composite
    ``scan_text`` runs every rule; upstream filtering by extension
    keeps noise down.
    """
    if not text:
        return []
    # File-level guards: if these patterns match ANYWHERE in the
    # text, the named rule_id is suppressed for this scan. This
    # catches "metering configured before the engine is built" cases
    # that a forward-only regex lookahead cannot see. Mirrors the
    # ``_file_contains_any`` style used in other ``*_patterns.py``
    # modules.
    metering_in_file = bool(_WASMER_METERING_FILE_GUARD.search(text))
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        # Suppress wasm-wasmer-no-metering when Metering::new appears
        # ANYWHERE in the file — regardless of source/dest ordering
        # relative to the ``wasmer::Engine::new(`` call.
        if rule.id == "wasm-wasmer-no-metering" and metering_in_file:
            continue
        for m in rule.pattern.finditer(text):
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
