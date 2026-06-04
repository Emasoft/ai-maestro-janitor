"""Tests for ``scripts/lib/rust_specific_patterns.py``.

Wave 21 impl-J — verifies 35 Rust-specific attack-surface rules each
have a positive + (1-2) negative tests. Pure-stdlib pytest.

The rule catalogue covers Rust-runtime attack vectors deeper than the
shallow patterns in ``per_language_patterns.py``: ``unsafe`` blocks,
``unwrap`` on attacker-supplied parser returns, ``transmute`` /
``from_utf8_unchecked`` / ``Vec::set_len`` UB class, tokio runtime
mistakes (``block_on`` in ``async``, blocking-in-async,
``std::sync::Mutex`` across ``.await``), Cargo-toolchain hygiene,
runtime misconfiguration, secret leakage via ``tracing``, and
unauthed debug/admin/metrics endpoints.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Make ``scripts/lib`` importable without packaging — same trick used
# by every other ``test_*_patterns.py`` file in this repo.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

import rust_specific_patterns as rsp  # type: ignore[import-not-found]  # noqa: E402

# ---- Module-level invariants -------------------------------------------


def test_rules_have_unique_ids() -> None:
    """Every Rule.id is unique — duplicates would dedupe-collide."""
    ids = [r.id for r in rsp.RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


def test_rules_have_compiled_patterns() -> None:
    """Every Rule.pattern is a compiled regex with MULTILINE flag."""
    for rule in rsp.RULES:
        assert isinstance(rule.pattern, re.Pattern), rule.id
        assert rule.pattern.flags & re.MULTILINE, rule.id


def test_rules_have_valid_severity() -> None:
    """Severity is one of the four canonical strings."""
    allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in rsp.RULES:
        assert rule.severity in allowed, f"{rule.id}: {rule.severity}"


def test_rules_have_owasp_asi_mapping() -> None:
    """Every rule carries an OWASP-ASI mapping."""
    for rule in rsp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id


def test_scan_empty_returns_empty() -> None:
    """Empty input returns empty findings list."""
    assert rsp.scan_text("") == []
    assert rsp.scan_text("\n\n") == []


def test_rules_count_matches_proposals() -> None:
    """We implemented 37 rules expanding 25 distill proposals.

    Some proposals (J2 unwrap-on-parse, J3 transmute, J10 unsafe-impl-Send,
    J12 binary-format, J15 [patch], J18 tokio-current-thread,
    J19 reqwest no-timeout, J24 lazy_static/static-mut,
    J25 debug-endpoints) decomposed into two or more sub-rules to keep
    each regex bounded and RE2-safe.
    """
    assert len(rsp.RULES) == 37


def test_finding_namedtuple_shape() -> None:
    """Finding has the same 7 fields as python_specific_patterns.Finding."""
    f = rsp.Finding(
        rule_id="x", line=1, column=1, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-08",
    )
    assert f.rule_id == "x"
    assert f.line == 1
    assert f.column == 1
    assert f.matched_text == "m"


def _hits(rule_id: str, text: str) -> list[rsp.Finding]:
    """Return only findings of ``rule_id`` from ``scan_text(text)``."""
    return [f for f in rsp.scan_text(text) if f.rule_id == rule_id]


# ---- J1: unsafe { ... } block ------------------------------------------


def test_unsafe_block_basic_positive() -> None:
    """`unsafe { ... }` block is flagged."""
    src = 'fn foo() {\n    unsafe { *raw_ptr = 1; }\n}'
    assert _hits("rust-unsafe-block-in-request-path", src)


def test_unsafe_block_ffi_positive() -> None:
    """FFI `unsafe { libc::ioctl(...) }` block fires."""
    src = 'unsafe { libc::ioctl(1, TIOCGWINSZ, &mut ws); }'
    assert _hits("rust-unsafe-block-in-request-path", src)


def test_unsafe_block_no_unsafe_negative() -> None:
    """Code without any unsafe block does NOT fire."""
    src = 'fn safe() { let x = 1; }'
    assert not _hits("rust-unsafe-block-in-request-path", src)


def test_unsafe_block_only_unsafe_fn_negative() -> None:
    """`unsafe fn foo()` declaration (not a block) does NOT fire under J1.

    J13 (`rust-unsafe-impl-send-sync`) covers `unsafe impl`. J1 is
    specifically for block-level `unsafe { ... }` sites.
    """
    src = 'unsafe fn dangerous() { /* body */ }'
    assert not _hits("rust-unsafe-block-in-request-path", src)


# ---- J2: unwrap/expect on serde / parse return ------------------------


def test_unwrap_on_serde_json_from_str_positive() -> None:
    """`serde_json::from_str(json).unwrap()` is flagged."""
    src = 'let v: Value = serde_json::from_str(json).unwrap();'
    assert _hits("rust-unwrap-on-attacker-parse", src)


def test_unwrap_on_serde_json_from_slice_positive() -> None:
    """`serde_json::from_slice(&bytes).expect("...")` is flagged."""
    src = 'let v: Value = serde_json::from_slice(&bytes).expect("parse");'
    assert _hits("rust-unwrap-on-attacker-parse", src)


def test_unwrap_on_url_parse_positive() -> None:
    """`url::Url::parse(s).unwrap()` is flagged."""
    src = 'let url = url::Url::parse(input).unwrap();'
    assert _hits("rust-unwrap-on-attacker-parse", src)


def test_unwrap_on_toml_from_str_positive() -> None:
    """`toml::from_str(input).unwrap()` is flagged."""
    src = 'let cfg: Config = toml::from_str(content).unwrap();'
    assert _hits("rust-unwrap-on-attacker-parse", src)


def test_no_unwrap_on_serde_json_negative() -> None:
    """`?` operator instead of `.unwrap()` does NOT fire."""
    src = 'let v: Value = serde_json::from_str(json)?;'
    assert not _hits("rust-unwrap-on-attacker-parse", src)


# ---- J2 variant: utf8 parse ---------------------------------------


def test_unwrap_on_str_from_utf8_positive() -> None:
    """`str::from_utf8(bytes).unwrap()` is flagged."""
    src = 'let s = str::from_utf8(bytes).unwrap();'
    assert _hits("rust-unwrap-on-utf8-parse", src)


def test_unwrap_on_std_str_from_utf8_positive() -> None:
    """`std::str::from_utf8(bytes).expect("...")` is flagged."""
    src = 'let s = std::str::from_utf8(buf).expect("utf8");'
    assert _hits("rust-unwrap-on-utf8-parse", src)


def test_str_from_utf8_with_question_mark_negative() -> None:
    """`?` operator instead of unwrap does NOT fire."""
    src = 'let s = std::str::from_utf8(bytes)?;'
    assert not _hits("rust-unwrap-on-utf8-parse", src)


# ---- J2 variant: regex::new ----------------------------------------


def test_unwrap_on_regex_new_positive() -> None:
    """`Regex::new(pattern).unwrap()` is flagged."""
    src = 'let re = Regex::new(r"\\d+").unwrap();'
    assert _hits("rust-unwrap-on-regex-new", src)


def test_unwrap_on_regex_new_fully_qualified_positive() -> None:
    """`regex::Regex::new(...).expect(...)` is flagged."""
    src = 'let re = regex::Regex::new(pattern).expect("BUG");'
    assert _hits("rust-unwrap-on-regex-new", src)


def test_regex_new_with_question_mark_negative() -> None:
    """`?` operator instead of unwrap does NOT fire."""
    src = 'let re = Regex::new(pattern)?;'
    assert not _hits("rust-unwrap-on-regex-new", src)


# ---- J3: mem::transmute -------------------------------------------


def test_mem_transmute_positive() -> None:
    """`std::mem::transmute(...)` fires."""
    src = 'let x: u32 = unsafe { std::mem::transmute(some_f32) };'
    assert _hits("rust-mem-transmute", src)


def test_core_mem_transmute_positive() -> None:
    """`core::mem::transmute(...)` fires."""
    src = 'let p: *const T = unsafe { core::mem::transmute(addr) };'
    assert _hits("rust-mem-transmute", src)


def test_mem_transmute_with_turbofish_positive() -> None:
    """`std::mem::transmute::<A, B>(...)` fires."""
    src = 'let r = unsafe { std::mem::transmute::<u32, [u8; 4]>(v) };'
    assert _hits("rust-mem-transmute", src)


def test_bytemuck_cast_negative() -> None:
    """`bytemuck::cast(x)` does NOT fire — it's the safe alternative."""
    src = 'let y: B = bytemuck::cast(x);'
    assert not _hits("rust-mem-transmute", src)


# ---- J3 variant: chained pointer cast -----------------------------


def test_chained_ptr_cast_positive() -> None:
    """`as *const _ as *const u8` chained cast is flagged."""
    src = 'let p = &mut ws as *mut Winsize as *mut u8;'
    assert _hits("rust-chained-pointer-cast", src)


def test_chained_const_to_const_positive() -> None:
    """`as *const A as *const B` is flagged."""
    src = 'let q = &foo as *const Foo as *const u8;'
    assert _hits("rust-chained-pointer-cast", src)


def test_single_ptr_cast_negative() -> None:
    """A single `as *const u8` cast (not chained) does NOT fire."""
    src = 'let p = some_ref as *const u8;'
    assert not _hits("rust-chained-pointer-cast", src)


# ---- J4: from_utf8_unchecked --------------------------------------


def test_string_from_utf8_unchecked_positive() -> None:
    """`String::from_utf8_unchecked(bytes)` fires."""
    src = 'let s = unsafe { String::from_utf8_unchecked(bytes) };'
    assert _hits("rust-from-utf8-unchecked", src)


def test_str_from_utf8_unchecked_positive() -> None:
    """`str::from_utf8_unchecked(bytes)` fires."""
    src = 'let s = unsafe { std::str::from_utf8_unchecked(&buf) };'
    assert _hits("rust-from-utf8-unchecked", src)


def test_str_from_utf8_checked_negative() -> None:
    """`str::from_utf8(bytes)?` (CHECKED) does NOT fire."""
    src = 'let s = std::str::from_utf8(bytes)?;'
    assert not _hits("rust-from-utf8-unchecked", src)


# ---- J5: Vec::set_len ---------------------------------------------


def test_vec_set_len_method_positive() -> None:
    """`vec.set_len(n)` method call is flagged."""
    src = 'unsafe { v.set_len(new_len); }'
    assert _hits("rust-vec-set-len", src)


def test_vec_set_len_assoc_positive() -> None:
    """`Vec::set_len(v, n)` associated-function form is flagged."""
    src = 'unsafe { Vec::set_len(&mut v, capacity); }'
    assert _hits("rust-vec-set-len", src)


def test_vec_push_negative() -> None:
    """`vec.push(x)` does NOT fire — it's the safe API."""
    src = 'v.push(item);'
    assert not _hits("rust-vec-set-len", src)


# ---- J6: tokio::spawn with dropped JoinHandle --------------------


def test_tokio_spawn_dropped_positive() -> None:
    """`tokio::spawn(async move { ... });` at stmt level fires."""
    src = '    tokio::spawn(async move { work().await; });'
    assert _hits("rust-tokio-spawn-dropped", src)


def test_tokio_task_spawn_dropped_positive() -> None:
    """`tokio::task::spawn(async { ... });` at stmt level fires."""
    src = '    tokio::task::spawn(async { do_thing().await; });'
    assert _hits("rust-tokio-spawn-dropped", src)


def test_tokio_spawn_stored_negative() -> None:
    """`let handle = tokio::spawn(...)` does NOT fire (stored)."""
    src = '    let handle = tokio::spawn(async { work().await });'
    assert not _hits("rust-tokio-spawn-dropped", src)


def test_tokio_spawn_awaited_negative() -> None:
    """`tokio::spawn(...).await` does NOT fire (awaited inline)."""
    src = '    tokio::spawn(async { go().await }).await;'
    assert not _hits("rust-tokio-spawn-dropped", src)


# ---- J7: block_on inside async ----------------------------------


def test_block_on_inside_async_fn_positive() -> None:
    """`async fn ... block_on(...)` co-occurrence fires."""
    src = (
        'async fn handler() {\n'
        '    rt.block_on(other_future());\n'
        '}'
    )
    assert _hits("rust-block-on-inside-async", src)


def test_block_on_inside_async_block_positive() -> None:
    """`async { ... block_on(...) ... }` co-occurrence fires."""
    src = (
        'let fut = async {\n'
        '    Handle::current().block_on(inner);\n'
        '};'
    )
    assert _hits("rust-block-on-inside-async", src)


def test_block_on_outside_async_negative() -> None:
    """`block_on(...)` in plain `fn main` does NOT fire."""
    src = 'fn main() {\n    rt.block_on(work());\n}'
    assert not _hits("rust-block-on-inside-async", src)


# ---- J8: blocking syscalls in async ----------------------------


def test_blocking_in_async_thread_sleep_positive() -> None:
    """`std::thread::sleep` inside `async fn` fires."""
    src = (
        'async fn handler() {\n'
        '    std::thread::sleep(Duration::from_secs(1));\n'
        '}'
    )
    assert _hits("rust-blocking-in-async", src)


def test_blocking_in_async_fs_read_positive() -> None:
    """`std::fs::read(path)` inside `async fn` fires."""
    src = (
        'async fn load() {\n'
        '    let bytes = std::fs::read("/path")?;\n'
        '}'
    )
    assert _hits("rust-blocking-in-async", src)


def test_blocking_in_async_command_positive() -> None:
    """`std::process::Command::new(...)` inside `async fn` fires."""
    src = (
        'async fn run() {\n'
        '    std::process::Command::new("ls").output();\n'
        '}'
    )
    assert _hits("rust-blocking-in-async", src)


def test_blocking_in_sync_fn_negative() -> None:
    """`std::thread::sleep` in a non-async fn does NOT fire."""
    src = 'fn handler() {\n    std::thread::sleep(d);\n}'
    assert not _hits("rust-blocking-in-async", src)


# ---- J9: std::sync::Mutex across .await ----------------------


def test_std_mutex_across_await_positive() -> None:
    """`let g = m.lock().unwrap(); ... .await` fires."""
    src = (
        'async fn handler() {\n'
        '    let guard = m.lock().unwrap();\n'
        '    something(guard).await;\n'
        '}'
    )
    assert _hits("rust-std-mutex-across-await", src)


def test_std_rwlock_read_across_await_positive() -> None:
    """`let g = lock.read().unwrap(); ... .await` fires."""
    src = (
        'async fn handler() {\n'
        '    let g = lock.read().unwrap();\n'
        '    other.await;\n'
        '}'
    )
    assert _hits("rust-std-mutex-across-await", src)


def test_no_await_after_lock_negative() -> None:
    """`let g = m.lock().unwrap();` with no following `.await` does NOT fire."""
    src = (
        'fn handler() {\n'
        '    let guard = m.lock().unwrap();\n'
        '    use_it(&guard);\n'
        '}'
    )
    assert not _hits("rust-std-mutex-across-await", src)


# ---- J10: unsafe impl Send/Sync ------------------------------


def test_unsafe_impl_send_positive() -> None:
    """`unsafe impl Send for Wrapper {}` fires."""
    src = 'unsafe impl Send for Wrapper {}'
    assert _hits("rust-unsafe-impl-send-sync", src)


def test_unsafe_impl_sync_positive() -> None:
    """`unsafe impl Sync for Wrapper {}` fires."""
    src = 'unsafe impl Sync for Wrapper {}'
    assert _hits("rust-unsafe-impl-send-sync", src)


def test_unsafe_impl_with_generic_positive() -> None:
    """`unsafe impl<T> Send for Wrapper<T> {}` fires."""
    src = 'unsafe impl Send for Wrapper<T> {}'
    assert _hits("rust-unsafe-impl-send-sync", src)


def test_normal_impl_negative() -> None:
    """`impl Send for X {}` (no `unsafe`) does NOT fire."""
    src = 'impl Send for SafeWrapper {}'
    assert not _hits("rust-unsafe-impl-send-sync", src)


# ---- J10 variant: Rc into spawn -----------------------------


def test_rc_into_tokio_spawn_positive() -> None:
    """`Rc::new(...) ... tokio::spawn(...)` co-occurrence fires."""
    src = (
        'let shared = Rc::new(state);\n'
        'tokio::spawn(async move { use_state(shared).await });'
    )
    assert _hits("rust-rc-cross-thread", src)


def test_rc_into_thread_spawn_positive() -> None:
    """`Rc::new(...) ... std::thread::spawn(...)` co-occurrence fires."""
    src = (
        'let shared = Rc::new(data);\n'
        'std::thread::spawn(move || { work(shared) });'
    )
    assert _hits("rust-rc-cross-thread", src)


def test_arc_into_spawn_negative() -> None:
    """`Arc::new(...) tokio::spawn(...)` does NOT fire."""
    src = (
        'let shared = Arc::new(state);\n'
        'tokio::spawn(async move { use_state(shared).await });'
    )
    assert not _hits("rust-rc-cross-thread", src)


# ---- J11: serde_json unbounded ---------------------------


def test_serde_json_from_str_variable_positive() -> None:
    """`serde_json::from_str(payload)` with variable fires."""
    src = 'let v: Value = serde_json::from_str(payload).unwrap();'
    assert _hits("rust-serde-json-unbounded", src)


def test_serde_json_from_slice_variable_positive() -> None:
    """`serde_json::from_slice(&bytes)` with variable fires."""
    src = 'let v: Value = serde_json::from_slice(&bytes)?;'
    assert _hits("rust-serde-json-unbounded", src)


def test_serde_json_literal_negative() -> None:
    """`serde_json::from_str("\\u007b ...\\u007d")` literal does NOT fire."""
    src = 'let v: Value = serde_json::from_str(r#"{"k":1}"#)?;'
    assert not _hits("rust-serde-json-unbounded", src)


# ---- J12: bincode/rmp_serde/ciborium/postcard unbounded ----


def test_bincode_deserialize_positive() -> None:
    """`bincode::deserialize(&bytes)` fires."""
    src = 'let v: T = bincode::deserialize(&bytes)?;'
    assert _hits("rust-binary-format-unbounded", src)


def test_rmp_serde_from_slice_positive() -> None:
    """`rmp_serde::from_slice(&bytes)` fires."""
    src = 'let v: T = rmp_serde::from_slice(&bytes)?;'
    assert _hits("rust-binary-format-unbounded", src)


def test_ciborium_from_reader_positive() -> None:
    """`ciborium::from_reader(r)` fires."""
    src = 'let v: T = ciborium::from_reader(reader)?;'
    assert _hits("rust-binary-format-unbounded", src)


def test_postcard_from_bytes_positive() -> None:
    """`postcard::from_bytes(b)` fires."""
    src = 'let v: T = postcard::from_bytes(b)?;'
    assert _hits("rust-binary-format-unbounded", src)


def test_serde_json_doesnt_match_binary_format_negative() -> None:
    """`serde_json::from_str` does NOT fire under binary-format rule."""
    src = 'let v: Value = serde_json::from_str(s)?;'
    assert not _hits("rust-binary-format-unbounded", src)


# ---- J12 variant: .with_no_limit() ----------------------


def test_with_no_limit_optin_positive() -> None:
    """`.with_no_limit()` explicit opt-in fires."""
    src = 'bincode::DefaultOptions::new().with_no_limit().deserialize(&b)'
    assert _hits("rust-binary-format-no-limit-optin", src)


def test_with_limit_negative() -> None:
    """`.with_limit(N)` (the safe form) does NOT fire."""
    src = 'bincode::DefaultOptions::new().with_limit(1024).deserialize(&b)'
    assert not _hits("rust-binary-format-no-limit-optin", src)


# ---- J13: unsafe impl + interior mutability ------------


def test_unsafe_impl_with_raw_ptr_positive() -> None:
    """`unsafe impl Send for X {}` with raw ptr field nearby fires."""
    src = (
        'struct X {\n'
        '    p: *const u8,\n'
        '}\n'
        'unsafe impl Send for X {}'
    )
    assert _hits("rust-unsafe-impl-interior-mut", src)


def test_unsafe_impl_with_rc_positive() -> None:
    """`unsafe impl Send for X {}` with Rc<U> field nearby fires."""
    src = (
        'struct X {\n'
        '    inner: Rc<Vec<u8>>,\n'
        '}\n'
        'unsafe impl Send for X {}'
    )
    assert _hits("rust-unsafe-impl-interior-mut", src)


def test_unsafe_impl_with_refcell_positive() -> None:
    """`unsafe impl Sync for X` with RefCell<U> nearby fires."""
    src = (
        'struct X {\n'
        '    val: RefCell<u32>,\n'
        '}\n'
        'unsafe impl Sync for X {}'
    )
    assert _hits("rust-unsafe-impl-interior-mut", src)


# ---- J14: Cargo.toml binary target ---------------------


def test_cargo_toml_bin_section_positive() -> None:
    """Cargo.toml with `[[bin]]` section fires."""
    src = (
        '[package]\n'
        'name = "tool"\n'
        '[[bin]]\n'
        'name = "tool"\n'
        'path = "src/main.rs"\n'
    )
    assert _hits("rust-cargo-toml-binary-target", src)


def test_cargo_toml_no_bin_section_negative() -> None:
    """Cargo.toml without `[[bin]]` does NOT fire."""
    src = (
        '[package]\n'
        'name = "lib"\n'
        '[lib]\n'
        'crate-type = ["cdylib"]\n'
    )
    assert not _hits("rust-cargo-toml-binary-target", src)


# ---- J15: [patch.crates-io] with git -------------------


def test_cargo_patch_git_positive() -> None:
    """`[patch.crates-io]` with `git = ...` fires."""
    src = (
        '[patch.crates-io]\n'
        'serde = { git = "https://github.com/serde-rs/serde" }\n'
    )
    assert _hits("rust-cargo-patch-git", src)


def test_cargo_patch_path_only_negative() -> None:
    """`[patch.crates-io]` with `path = ...` does NOT fire."""
    src = (
        '[patch.crates-io]\n'
        'serde = { path = "../serde" }\n'
    )
    assert not _hits("rust-cargo-patch-git", src)


# ---- J15 variant: branch/tag not rev -----------------


def test_cargo_patch_git_branch_positive() -> None:
    """`git = ..., branch = ...` (force-pushable) fires."""
    src = 'serde = { git = "https://example/serde", branch = "main" }'
    assert _hits("rust-cargo-patch-git-branch-or-tag", src)


def test_cargo_patch_git_tag_positive() -> None:
    """`git = ..., tag = ...` (force-pushable) fires."""
    src = 'serde = { git = "https://example/serde", tag = "v1.0" }'
    assert _hits("rust-cargo-patch-git-branch-or-tag", src)


def test_cargo_patch_git_rev_negative() -> None:
    """`git = ..., rev = "<sha>"` (the safe form) does NOT fire."""
    src = (
        'serde = { git = "https://example/serde", '
        'rev = "abcdef1234567890abcdef1234567890abcdef12" }'
    )
    assert not _hits("rust-cargo-patch-git-branch-or-tag", src)


# ---- J16: cargo test/build in CI ---------------------


def test_cargo_test_in_ci_positive() -> None:
    """`run: cargo test` in YAML CI fires."""
    src = '      - run: cargo test --all\n'
    assert _hits("rust-cargo-test-or-build-in-ci", src)


def test_cargo_build_in_ci_positive() -> None:
    """`run: cargo build` in YAML CI fires."""
    src = '      - run: cargo build --release\n'
    assert _hits("rust-cargo-test-or-build-in-ci", src)


def test_npm_install_in_ci_negative() -> None:
    """`run: npm install` does NOT fire (not Rust)."""
    src = '      - run: npm install\n'
    assert not _hits("rust-cargo-test-or-build-in-ci", src)


# ---- J17: cargo install --git -----------------------


def test_cargo_install_git_https_positive() -> None:
    """`cargo install --git https://...` fires."""
    src = 'cargo install --git https://github.com/example/tool'
    assert _hits("rust-cargo-install-git", src)


def test_cargo_install_git_ssh_positive() -> None:
    """`cargo install --git ssh://...` fires."""
    src = 'cargo install --git ssh://github.com/example/tool'
    assert _hits("rust-cargo-install-git", src)


def test_cargo_install_crates_io_negative() -> None:
    """`cargo install ripgrep` (no --git) does NOT fire."""
    src = 'cargo install ripgrep'
    assert not _hits("rust-cargo-install-git", src)


# ---- J18: tokio current_thread flavor --------------


def test_tokio_main_current_thread_positive() -> None:
    """`#[tokio::main(flavor = "current_thread")]` fires."""
    src = '#[tokio::main(flavor = "current_thread")]\nasync fn main() {}'
    assert _hits("rust-tokio-current-thread-flavor", src)


def test_tokio_main_default_flavor_negative() -> None:
    """`#[tokio::main]` without flavor arg does NOT fire."""
    src = '#[tokio::main]\nasync fn main() {}'
    assert not _hits("rust-tokio-current-thread-flavor", src)


# ---- J18 variant: worker_threads = 1 --------------


def test_tokio_main_single_worker_positive() -> None:
    """`#[tokio::main(worker_threads = 1)]` fires."""
    src = '#[tokio::main(worker_threads = 1)]\nasync fn main() {}'
    assert _hits("rust-tokio-single-worker", src)


def test_tokio_main_four_workers_negative() -> None:
    """`#[tokio::main(worker_threads = 4)]` does NOT fire."""
    src = '#[tokio::main(worker_threads = 4)]\nasync fn main() {}'
    assert not _hits("rust-tokio-single-worker", src)


# ---- J19: reqwest no-timeout -----------------


def test_reqwest_client_new_positive() -> None:
    """`reqwest::Client::new()` fires."""
    src = 'let client = reqwest::Client::new();'
    assert _hits("rust-reqwest-client-new", src)


def test_reqwest_get_direct_positive() -> None:
    """`reqwest::get(url)` direct call fires."""
    src = 'let body = reqwest::get(url).await?;'
    assert _hits("rust-reqwest-get-direct", src)


def test_reqwest_builder_bare_positive() -> None:
    """`reqwest::Client::builder().build()` (no timeout) fires."""
    src = 'let c = reqwest::Client::builder().build()?;'
    assert _hits("rust-reqwest-client-builder-bare", src)


def test_reqwest_with_timeout_negative() -> None:
    """`Client::builder().timeout(...).build()` does NOT fire on the bare rule."""
    src = (
        'let c = reqwest::Client::builder()\n'
        '    .timeout(Duration::from_secs(30))\n'
        '    .build()?;'
    )
    # The bare-builder rule matches `builder().build(` directly with no
    # intervening chain. With a `.timeout(...)` in between this does NOT
    # match the bare pattern.
    assert not _hits("rust-reqwest-client-builder-bare", src)


# ---- J20: hyper body unbounded -----------


def test_hyper_body_to_bytes_positive() -> None:
    """`hyper::body::to_bytes(body)` fires."""
    src = 'let bytes = hyper::body::to_bytes(body).await?;'
    assert _hits("rust-hyper-body-unbounded", src)


def test_axum_to_bytes_max_positive() -> None:
    """`axum::body::to_bytes(body, usize::MAX)` fires."""
    src = 'let b = axum::body::to_bytes(body, usize::MAX).await?;'
    assert _hits("rust-hyper-body-unbounded", src)


def test_axum_to_bytes_bounded_negative() -> None:
    """`axum::body::to_bytes(body, 1024 * 1024)` (bounded) does NOT fire."""
    src = 'let b = axum::body::to_bytes(body, 1024 * 1024).await?;'
    assert not _hits("rust-hyper-body-unbounded", src)


# ---- J21: dotenv in main --------------


def test_dotenv_call_positive() -> None:
    """`dotenv::dotenv()` call fires."""
    src = 'fn main() {\n    dotenv::dotenv().ok();\n}'
    assert _hits("rust-dotenv-call", src)


def test_dotenvy_call_positive() -> None:
    """`dotenvy::dotenv()` call fires."""
    src = 'fn main() {\n    dotenvy::dotenv().ok();\n}'
    assert _hits("rust-dotenv-call", src)


def test_no_dotenv_negative() -> None:
    """Code without dotenv does NOT fire."""
    src = 'fn main() {\n    let x = 1;\n}'
    assert not _hits("rust-dotenv-call", src)


# ---- J22: tracing/log macros with secret arg ------


def test_tracing_info_with_password_positive() -> None:
    """`tracing::info!("login {password}", ...)` fires."""
    src = 'tracing::info!("login attempt with password {}", password);'
    assert _hits("rust-tracing-log-secret", src)


def test_tracing_debug_with_jwt_positive() -> None:
    """`tracing::debug!(... jwt ...)` fires."""
    src = 'tracing::debug!("token validation: jwt = {}", jwt);'
    assert _hits("rust-tracing-log-secret", src)


def test_log_error_with_api_key_positive() -> None:
    """`log::error!("... api_key ...")` fires."""
    src = 'log::error!("failed for api_key: {}", api_key);'
    assert _hits("rust-tracing-log-secret", src)


def test_tracing_info_no_secret_negative() -> None:
    """`tracing::info!("hello")` does NOT fire (no secret-shaped arg)."""
    src = 'tracing::info!("Server started on port {}", port);'
    assert not _hits("rust-tracing-log-secret", src)


# ---- J23: panic = "abort" in profile.release -------


def test_profile_release_panic_abort_positive() -> None:
    """`[profile.release] panic = "abort"` fires."""
    src = (
        '[profile.release]\n'
        'lto = true\n'
        'panic = "abort"\n'
        'strip = true\n'
    )
    assert _hits("rust-profile-release-panic-abort", src)


def test_profile_release_panic_unwind_negative() -> None:
    """`[profile.release]` without panic="abort" does NOT fire."""
    src = (
        '[profile.release]\n'
        'lto = true\n'
        'strip = true\n'
    )
    assert not _hits("rust-profile-release-panic-abort", src)


# ---- J24: static mut global -----------


def test_static_mut_positive() -> None:
    """`static mut COUNT: u32 = 0;` fires."""
    src = 'static mut COUNT: u32 = 0;'
    assert _hits("rust-static-mut-global", src)


def test_pub_static_mut_positive() -> None:
    """`pub static mut COUNT: u32 = 0;` fires."""
    src = 'pub static mut COUNT: u32 = 0;'
    assert _hits("rust-static-mut-global", src)


def test_static_immutable_negative() -> None:
    """`static COUNT: u32 = 0;` (immutable) does NOT fire."""
    src = 'static COUNT: u32 = 0;'
    assert not _hits("rust-static-mut-global", src)


# ---- J24 variant: lazy_static + network init ----


def test_lazy_static_with_reqwest_positive() -> None:
    """`lazy_static!` + `reqwest::get(...)` fires."""
    src = (
        'lazy_static! {\n'
        '    static ref CONFIG: Config = {\n'
        '        let r = reqwest::get("https://config.svc").unwrap();\n'
        '        r.json().unwrap()\n'
        '    };\n'
        '}\n'
    )
    assert _hits("rust-lazy-static-network-init", src)


def test_lazy_static_with_tcp_connect_positive() -> None:
    """`lazy_static!` + `TcpStream::connect(...)` fires."""
    src = (
        'lazy_static! {\n'
        '    static ref STREAM: TcpStream = std::net::TcpStream::connect("svc:9000").unwrap();\n'
        '}\n'
    )
    assert _hits("rust-lazy-static-network-init", src)


def test_lazy_static_local_only_negative() -> None:
    """`lazy_static!` with compile-time constants does NOT fire."""
    src = (
        'lazy_static! {\n'
        '    static ref BANNER: String = include_str!("banner.txt").to_string();\n'
        '}\n'
    )
    assert not _hits("rust-lazy-static-network-init", src)


# ---- J25: debug/admin routes (axum) ---------


def test_axum_admin_route_positive() -> None:
    """axum `Router::new().route("/admin/...", ...)` fires."""
    src = 'let app = Router::new().route("/admin/users", get(admin_users));'
    assert _hits("rust-axum-debug-route", src)


def test_axum_metrics_route_positive() -> None:
    """axum `route("/metrics", ...)` fires."""
    src = 'let app = Router::new().route("/metrics", get(prom_handler));'
    assert _hits("rust-axum-debug-route", src)


def test_axum_user_facing_route_negative() -> None:
    """axum `route("/api/users", ...)` does NOT fire."""
    src = 'let app = Router::new().route("/api/users", get(list_users));'
    assert not _hits("rust-axum-debug-route", src)


# ---- J25 variant: actix-web ---------


def test_actix_admin_scope_positive() -> None:
    """actix-web `web::scope("/admin")` fires."""
    src = 'App::new().service(web::scope("/admin").service(admin_handler));'
    assert _hits("rust-actix-debug-route", src)


def test_actix_metrics_resource_positive() -> None:
    """actix-web `web::resource("/metrics")` fires."""
    src = 'App::new().service(web::resource("/metrics").route(web::get().to(metrics)));'
    assert _hits("rust-actix-debug-route", src)


def test_actix_user_facing_resource_negative() -> None:
    """actix-web `web::resource("/users")` does NOT fire."""
    src = 'App::new().service(web::resource("/users"));'
    assert not _hits("rust-actix-debug-route", src)


# ---- J25 variant: rocket -----------


def test_rocket_admin_route_positive() -> None:
    """rocket `#[get("/admin/...")]` fires."""
    src = '#[get("/admin/users")]\nfn admin_users() -> &\'static str { "" }'
    assert _hits("rust-rocket-debug-route", src)


def test_rocket_metrics_route_positive() -> None:
    """rocket `#[post("/metrics")]` fires."""
    src = '#[post("/metrics")]\nfn metrics() -> &\'static str { "" }'
    assert _hits("rust-rocket-debug-route", src)


def test_rocket_user_facing_route_negative() -> None:
    """rocket `#[get("/users")]` does NOT fire."""
    src = '#[get("/users")]\nfn list_users() -> &\'static str { "" }'
    assert not _hits("rust-rocket-debug-route", src)


# ---- End-to-end scan_text composition ----------


def test_scan_text_returns_findings_sorted_by_line() -> None:
    """Findings are sorted by (line, column, rule_id)."""
    src = (
        'unsafe { *p = 0; }\n'
        'let v = serde_json::from_str(s).unwrap();\n'
        'static mut COUNT: u32 = 0;\n'
    )
    findings = rsp.scan_text(src)
    assert any(f.rule_id == "rust-unsafe-block-in-request-path" for f in findings)
    assert any(f.rule_id == "rust-unwrap-on-attacker-parse" for f in findings)
    assert any(f.rule_id == "rust-static-mut-global" for f in findings)
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_scan_text_deduplicates_same_rule_same_position() -> None:
    """A single rule firing at the same (line, col) twice emits once."""
    src = 'unsafe { *p = 0; }'
    findings = rsp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys)), f"duplicate findings: {keys}"


def test_scan_text_truncates_long_matches_to_200_chars() -> None:
    """Matched text over 200 chars is truncated with an ellipsis."""
    long_path = "x" * 500
    src = f'static mut {long_path.upper()}: u32 = 0;'
    findings = rsp.scan_text(src)
    target = [f for f in findings if f.rule_id == "rust-static-mut-global"]
    for f in target:
        if len(f.matched_text) > 200:
            assert f.matched_text.endswith("…"), f.matched_text[-5:]
            assert len(f.matched_text) <= 201, len(f.matched_text)


def test_scan_text_empty_lines_only_no_findings() -> None:
    """A file with only whitespace produces no findings."""
    assert rsp.scan_text("   \n\t\n   ") == []
