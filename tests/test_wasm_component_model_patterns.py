"""Tests for scripts/lib/wasm_component_model_patterns.py.

Wave-31 distillation round 17 — wasm-component-model angle.
Each of the 12 rules has at least 2 tests (one positive, one negative or
structural). Data-model sanity tests verify Finding/Rule shapes and the
public surface contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import wasm_component_model_patterns as wmp  # type: ignore[import-not-found]  # noqa: E402

# ---- Data-model sanity --------------------------------------------------


def test_rules_tuple_contains_all_advertised_rules() -> None:
    """RULES must cover all 12 documented rule IDs."""
    assert isinstance(wmp.RULES, tuple)
    rule_ids = {r.id for r in wmp.RULES}
    expected = {
        "wasm-cm-wit-resource-handle-escaped",
        "wasm-cm-canonical-lift-abi-mismatch",
        "wasm-cm-host-function-unchecked-ptr",
        "wasm-cm-linear-memory-aliasing",
        "wasm-cm-wit-import-wildcard-namespace",
        "wasm-cm-component-link-no-seal",
        "wasm-cm-wasi-filesystem-preopened-dir-escape",
        "wasm-cm-guest-stack-alloc-unbounded",
        "wasm-cm-realloc-null-passthrough",
        "wasm-cm-interface-version-skew",
        "wasm-cm-debug-fuel-disabled-in-prod",
        "wasm-cm-shared-memory-without-threads-flag",
    }
    assert expected == rule_ids
    assert len(wmp.RULES) == 12


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule must have a valid ASI- prefix and known severity level."""
    for rule in wmp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding must mirror webhook_signature_patterns.Finding shape exactly."""
    f = wmp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-06",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-06"


def test_empty_text_returns_no_findings() -> None:
    """Empty input must short-circuit to empty list."""
    assert wmp.scan_text("") == []


def test_scan_text_returns_list_of_findings() -> None:
    """scan_text must return a list (possibly empty) for arbitrary input."""
    result = wmp.scan_text("// harmless comment\nlet x = 1;\n")
    assert isinstance(result, list)
    for f in result:
        assert isinstance(f, wmp.Finding)


def test_findings_sorted_by_line_then_column() -> None:
    """scan_text results must be ordered (line, column, rule_id)."""
    # Trigger W5 (wildcard import) twice on separate lines
    src = (
        "use foo:bar.*;\n"
        "// some code\n"
        "use baz:qux.*;\n"
    )
    results = wmp.scan_text(src)
    if len(results) >= 2:
        for i in range(len(results) - 1):
            a, b = results[i], results[i + 1]
            assert (a.line, a.column, a.rule_id) <= (b.line, b.column, b.rule_id)


def test_no_duplicate_findings_for_same_position() -> None:
    """Deduplication must prevent two identical (rule_id, line, col) findings."""
    src = "use foo:bar.*;\n" * 1
    results = wmp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in results]
    assert len(keys) == len(set(keys))


# ---- W1 : wasm-cm-wit-resource-handle-escaped ---------------------------


def test_w1_positive_resource_handle_in_static() -> None:
    """ResourceHandle stored in a static variable must trigger W1."""
    src = "static HANDLE: ResourceHandle = ResourceHandle::new();\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-wit-resource-handle-escaped" in ids


def test_w1_positive_handle_in_arc() -> None:
    """Handle<T> wrapped in Arc must trigger W1."""
    src = "let h: Arc<Handle<MyResource>> = Arc::new(handle);\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-wit-resource-handle-escaped" in ids


def test_w1_negative_local_handle() -> None:
    """A local (non-static, non-Arc) resource_handle must not trigger W1."""
    src = "let h: resource_handle = get_handle();\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-wit-resource-handle-escaped" not in ids


# ---- W2 : wasm-cm-canonical-lift-abi-mismatch ---------------------------


def test_w2_positive_canon_lift_memory_1() -> None:
    """canon lift referencing memory 1 must trigger W2."""
    src = "canon lift $func (memory 1) (realloc 0) string-encoding=utf8\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-canonical-lift-abi-mismatch" in ids


def test_w2_positive_canon_lift_none_realloc() -> None:
    """canon_lift passing None for realloc must trigger W2."""
    src = "canon_lift(func, None, 0, encoding)\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-canonical-lift-abi-mismatch" in ids


def test_w2_negative_correct_canon_lower() -> None:
    """A canonical lower with memory 0 and valid realloc is benign."""
    src = "canon lower $func (memory 0) (realloc $my_realloc) string-encoding=utf8\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-canonical-lift-abi-mismatch" not in ids


# ---- W3 : wasm-cm-host-function-unchecked-ptr ---------------------------


def test_w3_positive_func_wrap_with_ptr_arg() -> None:
    """func_wrap accepting a raw ptr: i32 must trigger W3."""
    src = (
        'linker.func_wrap("env", "read", |mut caller: Caller<_>, ptr: i32| {\n'
        "    // use ptr\n"
        "});\n"
    )
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-host-function-unchecked-ptr" in ids


def test_w3_positive_raw_ptr_cast_with_memory_data() -> None:
    """Raw pointer cast followed by memory.data must trigger W3."""
    src = (
        "let p = offset as *const u8;\n"
        "let mem = memory.data(&caller);\n"
    )
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-host-function-unchecked-ptr" in ids


def test_w3_negative_func_wrap_no_ptr() -> None:
    """func_wrap with only a string argument must not trigger W3."""
    src = (
        'linker.func_wrap("env", "log", |mut caller: Caller<_>, msg: i64| {\n'
        "});\n"
    )
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-host-function-unchecked-ptr" not in ids


# ---- W4 : wasm-cm-linear-memory-aliasing --------------------------------


def test_w4_positive_two_get_export_memory_close() -> None:
    """Two get_export(\"memory\") within a few lines must trigger W4."""
    src = (
        'let mem_a = instance_a.get_export(&mut store, "memory").unwrap();\n'
        'let mem_b = instance_b.get_export(&mut store, "memory").unwrap();\n'
    )
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-linear-memory-aliasing" in ids


def test_w4_negative_get_export_other_names() -> None:
    """get_export for non-memory exports must not trigger W4."""
    src = (
        'let func_a = instance_a.get_export(&mut store, "run").unwrap();\n'
        'let func_b = instance_b.get_export(&mut store, "init").unwrap();\n'
    )
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-linear-memory-aliasing" not in ids


# ---- W5 : wasm-cm-wit-import-wildcard-namespace -------------------------


def test_w5_positive_wildcard_import() -> None:
    """WIT use with .* wildcard must trigger W5."""
    src = "use wasi:filesystem.*;\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-wit-import-wildcard-namespace" in ids


def test_w5_positive_bare_interface_import() -> None:
    """WIT use with a bare interface block (no version) must trigger W5."""
    src = "use wasi:io {input-stream, output-stream};\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-wit-import-wildcard-namespace" in ids


def test_w5_negative_plain_code_no_use() -> None:
    """Rust source with no WIT use statements must not trigger W5."""
    src = "fn main() { println!(\"hello\"); }\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-wit-import-wildcard-namespace" not in ids


# ---- W6 : wasm-cm-component-link-no-seal --------------------------------


def test_w6_positive_linker_new_instantiate_no_seal() -> None:
    """Linker::new followed by instantiate without seal must trigger W6."""
    src = (
        "let mut linker = Linker::new(&engine);\n"
        "wasi::add_to_linker(&mut linker, |s| s)?;\n"
        "let instance = linker.instantiate(&mut store, &component)?;\n"
    )
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-component-link-no-seal" in ids


def test_w6_negative_empty_source() -> None:
    """Source with no Linker::new must not trigger W6."""
    src = "// Just a comment about linking\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-component-link-no-seal" not in ids


# ---- W7 : wasm-cm-wasi-filesystem-preopened-dir-escape ------------------


def test_w7_positive_preopened_dir_root() -> None:
    """preopened_dir(\"/\") must trigger W7."""
    src = (
        "let wasi = WasiCtxBuilder::new()\n"
        '    .preopened_dir("/", "/")\n'
        "    .build();\n"
    )
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-wasi-filesystem-preopened-dir-escape" in ids


def test_w7_positive_preopened_dir_dotdot() -> None:
    """preopened_dir(\"..\") must trigger W7."""
    src = (
        "ctx.preopened_dir(\"..\", \"parent\")?;\n"
    )
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-wasi-filesystem-preopened-dir-escape" in ids


def test_w7_negative_preopened_specific_dir() -> None:
    """preopened_dir with a safe literal path must not trigger W7."""
    src = (
        'ctx.preopened_dir("/tmp/sandbox", "/data")?;\n'
    )
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-wasi-filesystem-preopened-dir-escape" not in ids


# ---- W8 : wasm-cm-guest-stack-alloc-unbounded ---------------------------


def test_w8_positive_alloca_with_variable() -> None:
    """alloca(n) where n is a variable must trigger W8."""
    src = "char *buf = alloca(n);\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-guest-stack-alloc-unbounded" in ids


def test_w8_positive_builtin_alloca_variable() -> None:
    """__builtin_alloca(len) must trigger W8."""
    src = "void *p = __builtin_alloca(len);\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-guest-stack-alloc-unbounded" in ids


def test_w8_negative_alloca_sizeof() -> None:
    """alloca(sizeof(T)) is a safe known-size alloca and must not trigger W8."""
    src = "char *buf = alloca(sizeof(MyStruct));\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-guest-stack-alloc-unbounded" not in ids


# ---- W9 : wasm-cm-realloc-null-passthrough ------------------------------


def test_w9_positive_crate_realloc_no_mangle() -> None:
    """#[no_mangle] pub fn crate_realloc must trigger W9."""
    src = (
        "#[no_mangle]\n"
        "pub unsafe fn crate_realloc(old_ptr: *mut u8, old_size: usize,\n"
        "                             _align: usize, new_size: usize) -> *mut u8 {\n"
        "    std::alloc::realloc(old_ptr, layout, new_size)\n"
        "}\n"
    )
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-realloc-null-passthrough" in ids


def test_w9_positive_c_crate_realloc_definition() -> None:
    """C-style void *crate_realloc(...) definition must trigger W9."""
    src = "void *crate_realloc(void *old_ptr, size_t old_size, size_t align, size_t new_size) {\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-realloc-null-passthrough" in ids


def test_w9_negative_unrelated_realloc() -> None:
    """A plain stdlib realloc call must not trigger W9."""
    src = "ptr = realloc(ptr, new_size);\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-realloc-null-passthrough" not in ids


# ---- W10 : wasm-cm-interface-version-skew -------------------------------


def test_w10_positive_wit_bindgen_version_line() -> None:
    """wit-bindgen = \"0.24.0\" in a manifest must trigger W10."""
    src = 'wit-bindgen = "0.24.0"\n'
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-interface-version-skew" in ids


def test_w10_positive_use_interface_at_version() -> None:
    """WIT use statement with @version must trigger W10."""
    src = "use wasi:filesystem@0.2.0;\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-interface-version-skew" in ids


def test_w10_negative_no_wit_version_reference() -> None:
    """Source without wit-bindgen or @version references must not trigger W10."""
    src = "fn greet(name: &str) -> String { format!(\"Hello, {name}!\") }\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-interface-version-skew" not in ids


# ---- W11 : wasm-cm-debug-fuel-disabled-in-prod --------------------------


def test_w11_positive_config_new_with_listener_no_fuel() -> None:
    """Config::new with TcpListener but no fuel config must trigger W11."""
    src = (
        "let engine = Engine::new(&config);\n"
        "let listener = TcpListener::bind(addr)?;\n"
    )
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-debug-fuel-disabled-in-prod" in ids


def test_w11_negative_no_server_context() -> None:
    """Config::new without any listener context must not trigger W11."""
    src = "let mut config = Config::new();\nconfig.debug_info(true);\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-debug-fuel-disabled-in-prod" not in ids


# ---- W12 : wasm-cm-shared-memory-without-threads-flag -------------------


def test_w12_positive_wasm_text_shared_memory() -> None:
    """Wasm text format (memory shared) declaration must trigger W12."""
    src = "(module (memory (export \"memory\") 1 1 shared))\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-shared-memory-without-threads-flag" in ids


def test_w12_positive_shared_memory_api() -> None:
    """SharedMemory::new call must trigger W12."""
    src = "let shared_mem = SharedMemory::new(&engine, ty)?;\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-shared-memory-without-threads-flag" in ids


def test_w12_negative_plain_memory_no_shared() -> None:
    """A Wasm text memory without `shared` must not trigger W12."""
    src = "(module (memory (export \"memory\") 1))\n"
    ids = {f.rule_id for f in wmp.scan_text(src)}
    assert "wasm-cm-shared-memory-without-threads-flag" not in ids
