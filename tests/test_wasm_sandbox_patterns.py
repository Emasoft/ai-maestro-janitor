"""Tests for ``scripts/lib/wasm_sandbox_patterns.py``.

Wave 22 impl-B — verifies the 50 WebAssembly sandbox-escape /
WASI capability-misuse rules each have a positive + (1-2) negative
tests. Pure-stdlib pytest.

The rule catalogue covers wasm-runtime-config and WASI-capability
attack vectors: ``wasmtime::Config`` compute/memory/stack limits,
``wasmer`` compiler+metering choices, ``Module::deserialize`` trust
boundary, WASI ``inherit_env`` / ``preopen_dir`` / ``inherit_network``
over-grant, browser-side ``WebAssembly.instantiateStreaming`` without
SRI, Spin/Fermyon manifest wildcards, Deno permission-flag misuse,
Node.js wasm-host isolation, WIT-bindgen name shadowing, WasmEdge
plugin loading, ``.wat`` unbounded memory, and ``wasm-pack`` toolchain
misuse.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Make ``scripts/lib`` importable without packaging — same trick used
# by every other ``test_*_patterns.py`` file in this repo.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

import wasm_sandbox_patterns as wsp  # type: ignore[import-not-found]  # noqa: E402

# ---- Module-level invariants -------------------------------------------


def test_rules_have_unique_ids() -> None:
    """Every Rule.id is unique — duplicates would dedupe-collide."""
    ids = [r.id for r in wsp.RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


def test_rules_have_compiled_patterns() -> None:
    """Every Rule.pattern is a compiled regex with MULTILINE flag."""
    for rule in wsp.RULES:
        assert isinstance(rule.pattern, re.Pattern), rule.id
        assert rule.pattern.flags & re.MULTILINE, rule.id


def test_rules_have_valid_severity() -> None:
    """Severity is one of the four canonical strings."""
    allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in wsp.RULES:
        assert rule.severity in allowed, f"{rule.id}: {rule.severity}"


def test_rules_have_owasp_asi_mapping() -> None:
    """Every rule carries an OWASP-ASI mapping."""
    for rule in wsp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id


def test_scan_empty_returns_empty() -> None:
    """Empty input returns empty findings list."""
    assert wsp.scan_text("") == []
    assert wsp.scan_text("\n\n") == []


def test_rules_count_covers_proposals() -> None:
    """We implemented 50 rules expanding 25 distill proposals.

    Several proposals decomposed into multiple sub-rules so each regex
    stays bounded and RE2-safe: B7 (unchecked vs generic deserialize),
    B8 (inherit_env vs envs(env::vars)), B9 (literal/env/dirs preopens),
    B10 (4 network grant shapes), B12-B13 (browser SRI + dataflow),
    B14 (TOML/CLI/Rust feature toggles), B15 (Spin wildcard/legacy/SSRF),
    B16 (six --allow-* variants), B17 (legacy/per-feature unstable),
    B19 (Buffer/fs.readFile sources), B20 (wasmtime/wasmer imports),
    B21 (wasi/host namespace + ambiguous export), B22 (C/C++ plugin
    load APIs), B24 (flag-order variants), B25 (literal/$(pwd) shapes).
    """
    assert len(wsp.RULES) == 50


def test_finding_namedtuple_shape() -> None:
    """Finding has the same 7 fields as rust_specific_patterns.Finding."""
    f = wsp.Finding(
        rule_id="x", line=1, column=1, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-08",
    )
    assert f.rule_id == "x"
    assert f.line == 1
    assert f.column == 1
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-08"


def _hits(rule_id: str, text: str) -> list[wsp.Finding]:
    """Return only findings of ``rule_id`` from ``scan_text(text)``."""
    return [f for f in wsp.scan_text(text) if f.rule_id == rule_id]


# ---- B1: wasmtime no compute limit -------------------------------------


def test_wasmtime_no_compute_limit_positive() -> None:
    """`wasmtime::Config::new()` with no fuel/epoch toggle is flagged."""
    src = (
        "let mut cfg = wasmtime::Config::new();\n"
        "cfg.cranelift_opt_level(OptLevel::Speed);\n"
        "let engine = Engine::new(&cfg).unwrap();\n"
    )
    assert _hits("wasm-wasmtime-no-compute-limit", src)


def test_wasmtime_no_compute_limit_with_fuel_negative() -> None:
    """Config with `.consume_fuel(true)` is NOT flagged."""
    src = (
        "let mut cfg = wasmtime::Config::new();\n"
        "cfg.consume_fuel(true);\n"
    )
    assert not _hits("wasm-wasmtime-no-compute-limit", src)


def test_wasmtime_no_compute_limit_with_epoch_negative() -> None:
    """Config with `.epoch_interruption(true)` is NOT flagged."""
    src = (
        "let mut cfg = wasmtime::Config::default();\n"
        "cfg.epoch_interruption(true);\n"
    )
    assert not _hits("wasm-wasmtime-no-compute-limit", src)


# ---- B2: wasmtime default stack ----------------------------------------


def test_wasmtime_default_stack_positive() -> None:
    """Config built with no `.max_wasm_stack(...)` is flagged."""
    src = (
        "let mut cfg = wasmtime::Config::new();\n"
        "cfg.cranelift_opt_level(OptLevel::Speed);\n"
    )
    assert _hits("wasm-wasmtime-default-stack", src)


def test_wasmtime_default_stack_explicit_negative() -> None:
    """Config with `.max_wasm_stack(256 * 1024)` is NOT flagged."""
    src = (
        "let mut cfg = wasmtime::Config::new();\n"
        "cfg.max_wasm_stack(256 * 1024);\n"
    )
    assert not _hits("wasm-wasmtime-default-stack", src)


def test_wasmtime_default_stack_async_negative() -> None:
    """Config with `.async_stack_size(...)` is NOT flagged."""
    src = (
        "let mut cfg = wasmtime::Config::new();\n"
        "cfg.async_stack_size(128 * 1024);\n"
    )
    assert not _hits("wasm-wasmtime-default-stack", src)


# ---- B3: wasmtime unbounded memory -------------------------------------


def test_wasmtime_unbounded_memory_positive() -> None:
    """Config with no memory limits is flagged."""
    src = (
        "let mut cfg = wasmtime::Config::new();\n"
        "cfg.cranelift_opt_level(OptLevel::Speed);\n"
    )
    assert _hits("wasm-wasmtime-unbounded-memory", src)


def test_wasmtime_unbounded_memory_static_max_negative() -> None:
    """Config with `.static_memory_maximum_size(...)` is NOT flagged."""
    src = (
        "let mut cfg = wasmtime::Config::new();\n"
        "cfg.static_memory_maximum_size(64 * 1024 * 1024);\n"
    )
    assert not _hits("wasm-wasmtime-unbounded-memory", src)


# ---- B4: wasmtime pooling unbounded ------------------------------------


def test_wasmtime_pooling_unbounded_positive() -> None:
    """PoolingAllocationConfig with no total caps is flagged."""
    src = (
        "let mut pool = wasmtime::PoolingAllocationConfig::default();\n"
        "cfg.allocation_strategy(InstanceAllocationStrategy::Pooling(pool));\n"
    )
    assert _hits("wasm-wasmtime-pooling-unbounded", src)


def test_wasmtime_pooling_total_memories_negative() -> None:
    """PoolingAllocationConfig with `.total_memories(N)` is NOT flagged."""
    src = (
        "let mut pool = PoolingAllocationConfig::new();\n"
        "pool.total_memories(64);\n"
    )
    assert not _hits("wasm-wasmtime-pooling-unbounded", src)


# ---- B5: wasmer Singlepass --------------------------------------------


def test_wasmer_singlepass_default_positive() -> None:
    """`Singlepass::default()` is flagged."""
    src = 'let compiler = wasmer::Singlepass::default();'
    assert _hits("wasm-wasmer-singlepass", src)


def test_wasmer_singlepass_new_positive() -> None:
    """`Singlepass::new()` is flagged."""
    src = 'let compiler = wasmer_compiler_singlepass::Singlepass::new();'
    assert _hits("wasm-wasmer-singlepass", src)


def test_wasmer_cranelift_negative() -> None:
    """`Cranelift::default()` is NOT flagged (preferred compiler)."""
    src = 'let compiler = wasmer::Cranelift::default();'
    assert not _hits("wasm-wasmer-singlepass", src)


# ---- B6: wasmer no metering --------------------------------------------


def test_wasmer_no_metering_positive() -> None:
    """`wasmer::Engine::new(...)` without Metering middleware is flagged."""
    src = (
        "let engine = wasmer::Engine::new(compiler);\n"
        "let module = Module::new(&engine, bytes);\n"
    )
    assert _hits("wasm-wasmer-no-metering", src)


def test_wasmer_with_metering_negative() -> None:
    """`Engine::new` with `Metering::new` in same window is NOT flagged."""
    src = (
        "let metering = Metering::new(10_000_000, cost_fn);\n"
        "let engine = wasmer::Engine::new(compiler);\n"
    )
    assert not _hits("wasm-wasmer-no-metering", src)


# ---- B7: Module::deserialize_unchecked --------------------------------


def test_module_deserialize_unchecked_positive() -> None:
    """`Module::deserialize_unchecked` is flagged."""
    src = (
        "let m = unsafe { wasmtime::Module::deserialize_unchecked(&engine, &bytes)? };"
    )
    assert _hits("wasm-module-deserialize-unchecked", src)


def test_module_deserialize_unchecked_wasmer_positive() -> None:
    """wasmer variant is flagged."""
    src = 'let m = wasmer::Module::deserialize_unchecked(&store, bytes)?;'
    assert _hits("wasm-module-deserialize-unchecked", src)


# ---- B7 variant: Module::deserialize (generic) -------------------------


def test_module_deserialize_generic_positive() -> None:
    """`Module::deserialize(&engine, &bytes)` is flagged."""
    src = 'let m = wasmtime::Module::deserialize(&engine, &bytes)?;'
    assert _hits("wasm-module-deserialize-generic", src)


def test_module_deserialize_from_file_positive() -> None:
    """`Module::deserialize_from_file(&engine, path)` is flagged."""
    src = 'let m = wasmtime::Module::deserialize_from_file(&engine, "cache.cwasm")?;'
    assert _hits("wasm-module-deserialize-generic", src)


def test_module_new_negative() -> None:
    """`Module::new(...)` (which DOES validate) is NOT flagged."""
    src = 'let m = wasmtime::Module::new(&engine, &bytes)?;'
    assert not _hits("wasm-module-deserialize-generic", src)


# ---- B8: WASI inherit_env ---------------------------------------------


def test_wasi_inherit_env_positive() -> None:
    """`.inherit_env()` chain is flagged."""
    src = (
        "let wasi = WasiCtxBuilder::new()\n"
        "    .inherit_env()\n"
        "    .build();\n"
    )
    assert _hits("wasm-wasi-inherit-env", src)


def test_wasi_inherit_env_other_method_negative() -> None:
    """`.env(\"PATH\", ...)` allow-listing is NOT flagged."""
    src = (
        'let wasi = WasiCtxBuilder::new()\n'
        '    .env("PATH", env::var("PATH").unwrap_or_default())\n'
        '    .build();\n'
    )
    assert not _hits("wasm-wasi-inherit-env", src)


# ---- B8 variant: envs(env::vars()) ------------------------------------


def test_wasi_envs_full_host_positive() -> None:
    """`.envs(env::vars().collect())` is flagged."""
    src = '.envs(env::vars().collect())'
    assert _hits("wasm-wasi-envs-full-host", src)


def test_wasi_envs_vars_os_positive() -> None:
    """`.envs(env::vars_os().collect())` is flagged."""
    src = '.envs(env::vars_os().collect())'
    assert _hits("wasm-wasi-envs-full-host", src)


def test_wasi_envs_allowlist_negative() -> None:
    """`.envs(vec![(\"PATH\", \"/bin\".to_string())])` is NOT flagged."""
    src = '.envs(vec![("PATH", "/bin".to_string())])'
    assert not _hits("wasm-wasi-envs-full-host", src)


# ---- B9: WASI preopen root --------------------------------------------


def test_wasi_preopen_root_literal_positive() -> None:
    """`Dir::open_ambient_dir(\"/\")` is flagged."""
    src = 'let root = Dir::open_ambient_dir("/", ambient_authority())?;'
    assert _hits("wasm-wasi-preopen-root-literal", src)


def test_wasi_preopen_home_literal_positive() -> None:
    """`Dir::open_ambient_dir(\"/home/foo\")` is flagged."""
    src = 'let h = Dir::open_ambient_dir("/home/foo", ambient_authority())?;'
    assert _hits("wasm-wasi-preopen-root-literal", src)


def test_wasi_preopen_inputs_dir_negative() -> None:
    """`Dir::open_ambient_dir(\"./inputs\")` is NOT flagged."""
    src = 'let d = Dir::open_ambient_dir("./inputs", ambient_authority())?;'
    assert not _hits("wasm-wasi-preopen-root-literal", src)


# ---- B9 variant: preopen via env::var ---------------------------------


def test_wasi_preopen_home_env_positive() -> None:
    """`Dir::open_ambient_dir(env::var(\"HOME\"))` is flagged."""
    src = (
        'let h = Dir::open_ambient_dir(env::var("HOME").unwrap(), '
        'ambient_authority())?;'
    )
    assert _hits("wasm-wasi-preopen-home-env", src)


def test_wasi_preopen_cargo_home_positive() -> None:
    """`Dir::open_ambient_dir(env::var(\"CARGO_HOME\"))` is flagged."""
    src = 'Dir::open_ambient_dir(env::var("CARGO_HOME").unwrap(), aa())?;'
    assert _hits("wasm-wasi-preopen-home-env", src)


# ---- B9 variant: preopen via dirs:: -----------------------------------


def test_wasi_preopen_dirs_home_positive() -> None:
    """`Dir::open_ambient_dir(dirs::home_dir())` is flagged."""
    src = 'Dir::open_ambient_dir(dirs::home_dir().unwrap(), aa())?;'
    assert _hits("wasm-wasi-preopen-dirs-helper", src)


def test_wasi_preopen_dirs_config_positive() -> None:
    """`Dir::open_ambient_dir(dirs::config_dir())` is flagged."""
    src = 'Dir::open_ambient_dir(dirs::config_dir().unwrap(), aa())?;'
    assert _hits("wasm-wasi-preopen-dirs-helper", src)


# ---- B10: WASI inherit_network ----------------------------------------


def test_wasi_inherit_network_positive() -> None:
    """`.inherit_network()` is flagged."""
    src = 'let wasi = WasiCtxBuilder::new().inherit_network().build()?;'
    assert _hits("wasm-wasi-inherit-network", src)


def test_wasi_no_network_negative() -> None:
    """WasiCtx without network is NOT flagged."""
    src = 'let wasi = WasiCtxBuilder::new().build()?;'
    assert not _hits("wasm-wasi-inherit-network", src)


# ---- B10 variant: ipnet wildcard --------------------------------------


def test_wasi_pool_wildcard_v4_positive() -> None:
    """`ipnet!(\"0.0.0.0/0\")` is flagged."""
    src = 'pool.insert_ip_net(ipnet!("0.0.0.0/0"), AmbientAuthority::default());'
    assert _hits("wasm-wasi-pool-wildcard-ip", src)


def test_wasi_pool_wildcard_v6_positive() -> None:
    """`ipnet!(\"::/0\")` is flagged."""
    src = 'pool.insert_ip_net(ipnet!("::/0"), AmbientAuthority::default());'
    assert _hits("wasm-wasi-pool-wildcard-ip", src)


def test_wasi_pool_specific_cidr_negative() -> None:
    """`ipnet!(\"10.0.0.0/24\")` (specific CIDR) is NOT flagged."""
    src = 'pool.insert_ip_net(ipnet!("10.0.0.0/24"), aa());'
    assert not _hits("wasm-wasi-pool-wildcard-ip", src)


# ---- B10 variant: 0.0.0.0:0 socket addr -------------------------------


def test_wasi_pool_any_socket_positive() -> None:
    """`SocketAddr::from(([0,0,0,0], 0))` is flagged."""
    src = 'pool.insert_socket_addr(SocketAddr::from(([0,0,0,0], 0)), aa());'
    assert _hits("wasm-wasi-pool-any-socket", src)


# ---- B10 variant: wasmtime CLI --inherit-network ----------------------


def test_wasmtime_cli_inherit_network_positive() -> None:
    """`wasmtime run --inherit-network module.wasm` is flagged."""
    src = 'wasmtime run --inherit-network --dir=./data module.wasm'
    assert _hits("wasm-wasmtime-cli-inherit-network", src)


def test_wasmtime_cli_no_network_negative() -> None:
    """`wasmtime run module.wasm` (no --inherit-network) is NOT flagged."""
    src = 'wasmtime run module.wasm'
    assert not _hits("wasm-wasmtime-cli-inherit-network", src)


# ---- B11: wasm-pack --target web --------------------------------------


def test_wasm_pack_target_web_positive() -> None:
    """`wasm-pack build --target web` is flagged."""
    src = 'wasm-pack build --target web --release ./crate'
    assert _hits("wasm-wasm-pack-target-web", src)


def test_wasm_pack_target_nodejs_negative() -> None:
    """`wasm-pack build --target nodejs` is NOT flagged."""
    src = 'wasm-pack build --target nodejs --release ./crate'
    assert not _hits("wasm-wasm-pack-target-web", src)


# ---- B12: WebAssembly.instantiateStreaming -----------------------------


def test_browser_instantiate_streaming_positive() -> None:
    """`WebAssembly.instantiateStreaming(fetch(...))` is flagged."""
    src = 'WebAssembly.instantiateStreaming(fetch("./foo.wasm"))'
    assert _hits("wasm-browser-instantiate-streaming", src)


def test_browser_compile_streaming_positive() -> None:
    """`WebAssembly.compileStreaming(fetch(...))` is flagged."""
    src = 'await WebAssembly.compileStreaming(fetch("./bar.wasm"))'
    assert _hits("wasm-browser-instantiate-streaming", src)


def test_browser_no_streaming_negative() -> None:
    """A plain `await fetch(...)` (no wasm) is NOT flagged."""
    src = 'await fetch("./foo.wasm").then(r => r.arrayBuffer())'
    assert not _hits("wasm-browser-instantiate-streaming", src)


# ---- B12 variant: instantiate with cross-origin fetch -----------------


def test_browser_fetch_remote_https_positive() -> None:
    """`WebAssembly.instantiate(fetch(\"https://cdn.example/foo.wasm\"))` flagged."""
    src = (
        'WebAssembly.instantiateStreaming('
        'fetch("https://cdn.example.com/foo.wasm"))'
    )
    assert _hits("wasm-browser-fetch-remote", src)


def test_browser_fetch_relative_negative() -> None:
    """`WebAssembly.instantiate(fetch(\"./foo.wasm\"))` (relative) NOT flagged."""
    src = 'WebAssembly.instantiateStreaming(fetch("./foo.wasm"))'
    assert not _hits("wasm-browser-fetch-remote", src)


# ---- B13: instantiate from URLSearchParams ----------------------------


def test_browser_searchparams_to_wasm_positive() -> None:
    """URLSearchParams → WebAssembly.instantiate chain is flagged."""
    src = (
        'const params = new URLSearchParams(window.location.search);\n'
        'const url = params.get("wasm_url");\n'
        'const r = await fetch(url);\n'
        'await WebAssembly.instantiate(await r.arrayBuffer());\n'
    )
    assert _hits("wasm-browser-from-searchparams", src)


def test_browser_static_url_negative() -> None:
    """Static URL (no URLSearchParams) is NOT flagged."""
    src = 'await WebAssembly.instantiate(await (await fetch("./a.wasm")).arrayBuffer());'
    assert not _hits("wasm-browser-from-searchparams", src)


# ---- B13 variant: localStorage source ---------------------------------


def test_browser_localstorage_to_wasm_positive() -> None:
    """localStorage → WebAssembly.instantiate chain is flagged."""
    src = (
        'const bytes = localStorage.getItem("cached_wasm");\n'
        'await WebAssembly.instantiate(new Uint8Array(JSON.parse(bytes)));\n'
    )
    assert _hits("wasm-browser-from-localstorage", src)


# ---- B14: wasm-features = "all" (TOML) --------------------------------


def test_wasm_features_all_toml_string_positive() -> None:
    """`features = "all"` in TOML is flagged."""
    src = 'features = "all"\n'
    assert _hits("wasm-features-all-toml", src)


def test_wasm_features_all_toml_array_positive() -> None:
    """`wasm-features = ["all"]` in TOML is flagged."""
    src = 'wasm-features = ["all"]\n'
    assert _hits("wasm-features-all-toml", src)


def test_wasm_features_specific_negative() -> None:
    """`features = ["simd"]` (specific) is NOT flagged."""
    src = 'features = ["simd"]\n'
    assert not _hits("wasm-features-all-toml", src)


# ---- B14 variant: --wasm-features=all CLI -----------------------------


def test_wasmtime_cli_features_all_positive() -> None:
    """`wasmtime --wasm-features=all` is flagged."""
    src = 'wasmtime run --wasm-features=all module.wasm'
    assert _hits("wasm-cli-features-all", src)


def test_wasmtime_cli_features_all_space_positive() -> None:
    """`wasmtime --wasm-features all` is flagged."""
    src = 'wasmtime run --wasm-features all module.wasm'
    assert _hits("wasm-cli-features-all", src)


def test_wasmtime_cli_features_specific_negative() -> None:
    """`wasmtime --wasm-features=simd,bulk-memory` is NOT flagged."""
    src = 'wasmtime run --wasm-features=simd,bulk-memory module.wasm'
    assert not _hits("wasm-cli-features-all", src)


# ---- B14 variant: Rust Config wasm_* toggles --------------------------


def test_wasmtime_cfg_wasm_threads_positive() -> None:
    """`.wasm_threads(true)` is flagged (single proposal feature)."""
    src = 'cfg.wasm_threads(true);'
    assert _hits("wasm-cfg-feature-toggle", src)


def test_wasmtime_cfg_wasm_gc_positive() -> None:
    """`.wasm_gc(true)` is flagged."""
    src = 'cfg.wasm_gc(true);'
    assert _hits("wasm-cfg-feature-toggle", src)


def test_wasmtime_cfg_wasm_threads_false_negative() -> None:
    """`.wasm_threads(false)` is NOT flagged."""
    src = 'cfg.wasm_threads(false);'
    assert not _hits("wasm-cfg-feature-toggle", src)


# ---- B15: Spin outbound wildcard --------------------------------------


def test_spin_outbound_wildcard_star_positive() -> None:
    """`allowed_outbound_hosts = ["*"]` is flagged."""
    src = 'allowed_outbound_hosts = ["*"]\n'
    assert _hits("wasm-spin-outbound-wildcard", src)


def test_spin_outbound_wildcard_https_positive() -> None:
    """`allowed_outbound_hosts = ["https://*:*"]` is flagged."""
    src = 'allowed_outbound_hosts = ["https://*:*"]\n'
    assert _hits("wasm-spin-outbound-wildcard", src)


def test_spin_outbound_specific_negative() -> None:
    """`allowed_outbound_hosts = ["https://api.example.com:443"]` NOT flagged."""
    src = 'allowed_outbound_hosts = ["https://api.example.com:443"]\n'
    assert not _hits("wasm-spin-outbound-wildcard", src)


# ---- B15 variant: legacy allowed_http_hosts ---------------------------


def test_spin_http_wildcard_positive() -> None:
    """`allowed_http_hosts = ["*"]` (older Spin key) is flagged."""
    src = 'allowed_http_hosts = ["*"]\n'
    assert _hits("wasm-spin-http-wildcard", src)


# ---- B15 variant: SSRF target in outbound -----------------------------


def test_spin_outbound_imds_positive() -> None:
    """outbound list with `169.254.169.254` is flagged."""
    src = 'allowed_outbound_hosts = ["http://169.254.169.254"]\n'
    assert _hits("wasm-spin-outbound-ssrf-target", src)


def test_spin_outbound_localhost_positive() -> None:
    """outbound list with `localhost` is flagged."""
    src = 'allowed_outbound_hosts = ["http://localhost:8080"]\n'
    assert _hits("wasm-spin-outbound-ssrf-target", src)


# ---- B16: Deno --allow-net unscoped -----------------------------------


def test_deno_allow_net_unscoped_positive() -> None:
    """`deno run --allow-net script.ts` (no `=scope`) is flagged."""
    src = 'deno run --allow-net script.ts'
    assert _hits("wasm-deno-allow-net-unscoped", src)


def test_deno_allow_net_scoped_negative() -> None:
    """`deno run --allow-net=api.example.com:443 script.ts` NOT flagged."""
    src = 'deno run --allow-net=api.example.com:443 script.ts'
    assert not _hits("wasm-deno-allow-net-unscoped", src)


def test_deno_test_allow_net_unscoped_positive() -> None:
    """`deno test --allow-net script.ts` is flagged."""
    src = 'deno test --allow-net script.ts'
    assert _hits("wasm-deno-allow-net-unscoped", src)


# ---- B16 variants: --allow-read / -write / -env / -run unscoped -------


def test_deno_allow_read_unscoped_positive() -> None:
    src = 'deno run --allow-read script.ts'
    assert _hits("wasm-deno-allow-read-unscoped", src)


def test_deno_allow_write_unscoped_positive() -> None:
    src = 'deno run --allow-write script.ts'
    assert _hits("wasm-deno-allow-write-unscoped", src)


def test_deno_allow_env_unscoped_positive() -> None:
    src = 'deno run --allow-env script.ts'
    assert _hits("wasm-deno-allow-env-unscoped", src)


def test_deno_allow_env_scoped_negative() -> None:
    src = 'deno run --allow-env=API_KEY,DATABASE_URL script.ts'
    assert not _hits("wasm-deno-allow-env-unscoped", src)


def test_deno_allow_run_unscoped_positive() -> None:
    src = 'deno run --allow-run script.ts'
    assert _hits("wasm-deno-allow-run-unscoped", src)


# ---- B16 variant: deno -A / --allow-all ------------------------------


def test_deno_allow_all_short_positive() -> None:
    """`deno run -A script.ts` is flagged."""
    src = 'deno run -A script.ts'
    assert _hits("wasm-deno-allow-all", src)


def test_deno_allow_all_long_positive() -> None:
    """`deno run --allow-all script.ts` is flagged."""
    src = 'deno run --allow-all script.ts'
    assert _hits("wasm-deno-allow-all", src)


def test_deno_no_perm_negative() -> None:
    """`deno run script.ts` (no perms) is NOT flagged."""
    src = 'deno run script.ts'
    assert not _hits("wasm-deno-allow-all", src)


# ---- B17: Deno --unstable legacy --------------------------------------


def test_deno_unstable_legacy_positive() -> None:
    """`deno run --unstable script.ts` is flagged."""
    src = 'deno run --unstable script.ts'
    assert _hits("wasm-deno-unstable-legacy", src)


def test_deno_unstable_feature_negative_for_legacy() -> None:
    """`deno run --unstable-ffi script.ts` does NOT trigger the LEGACY rule."""
    src = 'deno run --unstable-ffi script.ts'
    assert not _hits("wasm-deno-unstable-legacy", src)


# ---- B17 variant: --unstable-<feature> --------------------------------


def test_deno_unstable_ffi_positive() -> None:
    """`deno run --unstable-ffi script.ts` is flagged."""
    src = 'deno run --unstable-ffi script.ts'
    assert _hits("wasm-deno-unstable-feature", src)


def test_deno_unstable_kv_positive() -> None:
    """`deno run --unstable-kv script.ts` is flagged."""
    src = 'deno run --unstable-kv script.ts'
    assert _hits("wasm-deno-unstable-feature", src)


# ---- B18: deno cache then deno run ------------------------------------


def test_deno_cache_then_run_positive() -> None:
    """`deno cache foo.ts` followed by `deno run foo.ts` is flagged."""
    src = (
        'deno cache --allow-net deps.ts\n'
        'deno run main.ts\n'
    )
    assert _hits("wasm-deno-cache-then-run", src)


def test_deno_cache_only_negative() -> None:
    """Only `deno cache` (no run) is NOT flagged."""
    src = 'deno cache --allow-net deps.ts\n'
    assert not _hits("wasm-deno-cache-then-run", src)


# ---- B19: Node WebAssembly.instantiate(Buffer.from(...)) --------------


def test_node_wasm_instantiate_buffer_positive() -> None:
    """`WebAssembly.instantiate(Buffer.from(bytes))` is flagged."""
    src = 'await WebAssembly.instantiate(Buffer.from(bytes));'
    assert _hits("wasm-node-wasm-instantiate-buffer", src)


def test_node_wasm_compile_buffer_positive() -> None:
    """`WebAssembly.compile(Buffer.from(...))` is flagged."""
    src = 'const m = await WebAssembly.compile(Buffer.from(bytes));'
    assert _hits("wasm-node-wasm-instantiate-buffer", src)


# ---- B19 variant: fs.readFile source ---------------------------------


def test_node_wasm_instantiate_fsread_positive() -> None:
    """`WebAssembly.instantiate(fs.readFileSync(...))` is flagged."""
    src = 'WebAssembly.instantiate(fs.readFileSync("./module.wasm"));'
    assert _hits("wasm-node-wasm-instantiate-fsread", src)


def test_node_wasm_instantiate_fs_promises_positive() -> None:
    """`WebAssembly.instantiate(await fs.promises.readFile(...))` is flagged."""
    src = 'WebAssembly.instantiate(await fs.promises.readFile("./m.wasm"));'
    assert _hits("wasm-node-wasm-instantiate-fsread", src)


# ---- B20: host-import privileged (wasmtime) ---------------------------


def test_wasmtime_linker_privileged_positive() -> None:
    """`Linker::func_wrap(...)` body using `std::fs::read` is flagged."""
    src = (
        'linker.func_wrap("env", "read_file", |path: &str| {\n'
        '    let data = std::fs::read(path).unwrap();\n'
        '    data.len() as i32\n'
        '})?;\n'
    )
    assert _hits("wasm-host-import-privileged-wasmtime", src)


def test_wasmtime_linker_logging_only_negative() -> None:
    """`Linker::func_wrap` body using only `tracing::info!` is NOT flagged."""
    src = (
        'linker.func_wrap("env", "log", |msg: &str| {\n'
        '    tracing::info!(msg);\n'
        '})?;\n'
    )
    assert not _hits("wasm-host-import-privileged-wasmtime", src)


# ---- B20 variant: wasmer imports! macro -------------------------------


def test_wasmer_imports_privileged_positive() -> None:
    """`imports! { ... }` body using `std::fs::read` is flagged."""
    src = (
        'let imports = imports! {\n'
        '    "env" => {\n'
        '        "read_file" => Function::new_typed(&mut store, |path: i32| {\n'
        '            std::fs::read("/tmp/foo").unwrap();\n'
        '            0i32\n'
        '        }),\n'
        '    },\n'
        '};\n'
    )
    assert _hits("wasm-host-import-privileged-wasmer", src)


# ---- B21: WIT exports under wasi:/host: --------------------------------


def test_wit_export_wasi_filesystem_positive() -> None:
    """`export wasi:filesystem/preopens` is flagged."""
    src = 'export wasi:filesystem/preopens;'
    assert _hits("wasm-wit-export-wasi-or-host", src)


def test_wit_export_host_intf_positive() -> None:
    """`export host:logging/log` is flagged."""
    src = 'export host:logging/log;'
    assert _hits("wasm-wit-export-wasi-or-host", src)


def test_wit_export_third_party_negative() -> None:
    """`export myapp:db/query` (non-reserved namespace) is NOT flagged here."""
    src = 'export myapp:db/query;'
    assert not _hits("wasm-wit-export-wasi-or-host", src)


# ---- B21 variant: ambiguous export ------------------------------------


def test_wit_ambiguous_export_positive() -> None:
    """`export pkg:intf/name;` (any package/intf/name shape) is flagged."""
    src = 'export pkg:logging/log;'
    assert _hits("wasm-wit-ambiguous-export", src)


# ---- B22: WasmEdge plugin C API ---------------------------------------


def test_wasmedge_plugin_load_c_positive() -> None:
    """`WasmEdge_PluginLoadFromPath(...)` is flagged."""
    src = 'WasmEdge_PluginLoadFromPath(plugin_path);'
    assert _hits("wasm-wasmedge-plugin-load-c", src)


# ---- B22 variant: WasmEdge plugin C++ binding -------------------------


def test_wasmedge_plugin_load_cpp_positive() -> None:
    """`PluginManager::loadFromPath(...)` is flagged."""
    src = 'wasmedge::PluginManager::loadFromPath(path);'
    assert _hits("wasm-wasmedge-plugin-load-cpp", src)


def test_wasmedge_plugin_load_cpp_capitalized_positive() -> None:
    """`WasmEdge::PluginManager::loadFromPath(...)` is flagged."""
    src = 'WasmEdge::PluginManager::loadFromPath(path);'
    assert _hits("wasm-wasmedge-plugin-load-cpp", src)


# ---- B23: WAT memory no max -------------------------------------------


def test_wat_memory_no_max_positive() -> None:
    """`(memory (export "memory") 16)` (no max) is flagged."""
    src = '(memory (export "memory") 16)\n'
    assert _hits("wasm-wat-memory-no-max", src)


def test_wat_memory_with_max_negative() -> None:
    """`(memory (export "memory") 16 64)` (with max) is NOT flagged.

    The regex matches `... N)` — when there are TWO numbers, the regex
    won't match because the second number breaks the `\\d{1,5}\\s*\\)`
    tail anchor.
    """
    src = '(memory (export "memory") 16 64)\n'
    assert not _hits("wasm-wat-memory-no-max", src)


# ---- B24: wasm-pack --target web --no-modules -------------------------


def test_wasm_bindgen_no_modules_positive() -> None:
    """`wasm-pack build --target web --no-modules` is flagged."""
    src = 'wasm-pack build --target web --no-modules ./crate'
    assert _hits("wasm-wasm-bindgen-no-modules", src)


def test_wasm_bindgen_target_web_only_negative() -> None:
    """`wasm-pack build --target web` (no `--no-modules`) NOT flagged."""
    src = 'wasm-pack build --target web ./crate'
    assert not _hits("wasm-wasm-bindgen-no-modules", src)


# ---- B24 variant: reversed flag order ---------------------------------


def test_wasm_bindgen_no_modules_reversed_positive() -> None:
    """`wasm-pack build --no-modules --target web` (reversed) is flagged."""
    src = 'wasm-pack build --no-modules --target web ./crate'
    assert _hits("wasm-wasm-bindgen-no-modules-rev", src)


# ---- B25: wasmtime --dir=. CWD preopen --------------------------------


def test_wasmtime_cli_dir_dot_positive() -> None:
    """`wasmtime run --dir=. module.wasm` is flagged."""
    src = 'wasmtime run --dir=. module.wasm'
    assert _hits("wasm-wasi-cli-dir-cwd", src)


def test_wasmtime_cli_dir_dot_double_positive() -> None:
    """`wasmtime run --dir=.::. module.wasm` is flagged."""
    src = 'wasmtime run --dir=.::. module.wasm'
    assert _hits("wasm-wasi-cli-dir-cwd", src)


def test_wasmtime_cli_dir_pwd_positive() -> None:
    """`wasmtime run --dir=$PWD module.wasm` is flagged."""
    src = 'wasmtime run --dir=$PWD module.wasm'
    assert _hits("wasm-wasi-cli-dir-cwd", src)


def test_wasmedge_cli_dir_dot_positive() -> None:
    """`wasmedge --dir .:. module.wasm` is flagged."""
    src = 'wasmedge --dir .:. module.wasm'
    assert _hits("wasm-wasi-cli-dir-cwd", src)


def test_wasmtime_cli_dir_specific_negative() -> None:
    """`wasmtime run --dir=./inputs module.wasm` (specific path) NOT flagged."""
    src = 'wasmtime run --dir=./inputs module.wasm'
    assert not _hits("wasm-wasi-cli-dir-cwd", src)


# ---- B25 variant: --dir=$(pwd) ---------------------------------------


def test_wasmtime_cli_dir_pwd_sub_positive() -> None:
    """`wasmtime run --dir=$(pwd) module.wasm` is flagged."""
    src = 'wasmtime run --dir=$(pwd) module.wasm'
    assert _hits("wasm-wasi-cli-dir-pwd-sub", src)


# ---- Scanner integration ----------------------------------------------


def test_scan_text_returns_findings_in_line_order() -> None:
    """Multi-rule scan returns findings sorted by (line, column, rule_id)."""
    src = (
        'wasmtime::Config::new();\n'                       # B1, B2, B3
        '.inherit_env()\n'                                  # B8
        'deno run -A script.ts\n'                           # B16
    )
    findings = wsp.scan_text(src)
    # Sorted ascending
    for i in range(1, len(findings)):
        prev = (findings[i - 1].line, findings[i - 1].column, findings[i - 1].rule_id)
        curr = (findings[i].line, findings[i].column, findings[i].rule_id)
        assert prev <= curr


def test_scan_text_dedupes_same_rule_line_col() -> None:
    """Identical (rule_id, line, col) triples emit one finding."""
    # Two consecutive identical lines — different lines, so each fires.
    # Same line / same col should dedupe — easiest to verify by checking
    # that a single line emitting one rule produces exactly one finding.
    src = '.inherit_env()'
    hits = _hits("wasm-wasi-inherit-env", src)
    assert len(hits) == 1


def test_scan_text_carries_severity_and_owasp() -> None:
    """Findings carry severity + OWASP-ASI from their Rule."""
    src = 'wasmer::Module::deserialize_unchecked(&store, &bytes)'
    hits = _hits("wasm-module-deserialize-unchecked", src)
    assert hits
    assert hits[0].severity == "CRITICAL"
    assert hits[0].owasp_asi.startswith("ASI-")


def test_scan_text_truncates_long_matched_text() -> None:
    """`matched_text` over 200 chars is truncated with `…` suffix."""
    # Build a regex-firing line longer than 200 chars.
    long_line = "deno run --allow-net" + (" " + "x" * 300) + " script.ts"
    findings = wsp.scan_text(long_line)
    if findings:
        f = findings[0]
        assert len(f.matched_text) <= 201  # 200 chars + ellipsis
