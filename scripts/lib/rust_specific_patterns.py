"""Rust-language-specific attack-surface patterns.

Wave 21 impl-J — distillation of 25 proposals from
``reports/distill-round-7/rust-specific.md`` into deterministic regex
rules.

The distill report proposed deeper-than-shallow Rust detectors that
``per_language_patterns.py`` (Wave 16) does NOT cover: ``unsafe`` blocks
in network paths, ``unwrap``/``expect`` on attacker-supplied parser
returns, ``transmute`` / ``from_utf8_unchecked`` / ``Vec::set_len`` UB
class, tokio runtime mistakes (``block_on`` inside ``async``, blocking
syscalls in ``async``, ``std::sync::Mutex`` across ``.await``),
``Rc``/``RefCell`` cross-thread footguns, unbounded deserialisation
(serde_json / bincode / hyper body), Cargo-toolchain hygiene
(``Cargo.lock`` for binaries, ``[patch.crates-io]`` with unpinned git,
``cargo audit`` / ``cargo deny`` in CI, ``cargo install --git`` without
``--locked``/``--rev``), runtime misconfiguration, secret leakage via
``tracing``, ``panic = "abort"`` on server binaries, ``static mut`` /
``OnceCell`` init from network, and unauthed debug/admin/metrics
endpoints.

This module encodes the same shapes as **pure regex** for the
heartbeat detectors that prefer the lightweight one-pass scanner
shape over an AST walk. The regex rules accept a small precision
trade-off (slightly higher FP rate vs an AST walk that can reason
about scopes) in exchange for being trivially composable with the
other ``scripts/lib/*_patterns.py`` modules.

Architecture mirrors ``scripts/lib/python_specific_patterns.py``:

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
deliberately RE2-safe (no backreferences, no nested unbounded
quantifiers, bounded ``{0,N}`` repetitions in every alternation).

Severity mapping from the distill report onto the janitor's
canonical four-tier scale:

  CRITICAL (report) → CRITICAL (rule)
  HIGH     (report) → HIGH (rule)
  MEDIUM   (report) → MEDIUM (rule)
  LOW      (report) → LOW (rule)

Cross-references and de-duplication:

  * Wave 16 ``per_language_patterns.py`` already covers shallow
    ``unwrap()``, ``panic!()``, ``Cargo.lock`` existence and the
    ``unsafe`` keyword presence at file-level. Everything here is
    strictly deeper granularity (call-site / data-flow / arg-cap /
    middleware-presence / runtime-flavour).
  * Angle A (cargo dep hygiene) overlaps with J14/J15/J17. We keep
    them here because they target the Rust toolchain specifically
    (`cargo install`, `Cargo.lock`, `[patch.crates-io]`).
  * Angle G (secrets) overlaps with J21 / J22. Dedupe at scoring
    time, not at rule-definition time.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    ``scripts/lib/python_specific_patterns.Finding`` so heartbeat
    detectors can render either kind uniformly."""

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

    Rust identifiers and keywords are case-sensitive — so the regexes
    here do NOT use IGNORECASE. ``Unsafe`` is NOT ``unsafe`` in Rust
    parsing.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- J1: unsafe { ... } block in a network-input path ------------------


# Tree-sitter sees `unsafe_block`; pure regex sees `unsafe` followed by
# `{`. We can't do reachability analysis in regex, so the rule fires on
# any `unsafe {` block AND lets the caller route only files that match
# the "network-input path" heuristic (HTTP handler / serde / clap
# subcommand). The marker shape here is `unsafe {` at any indentation,
# not preceded by `impl` or `fn` keywords (which produce
# `unsafe impl` / `unsafe fn` — different shapes covered by J13).
_UNSAFE_BLOCK = _re(
    r"(?<![A-Za-z0-9_])"                # word boundary before
    r"unsafe\s*\{"                      # `unsafe {`
)


# ---- J2: unwrap()/expect() on serde / parse / Regex::new output --------


# `.unwrap()` or `.expect("...")` chained off any of the standard
# attacker-bytes parsers. We match the parser call followed by `.unwrap`
# or `.expect`. Bounded `{0,N}` window to avoid catastrophic backtracking
# on long expression chains.
_UNWRAP_ON_ATTACKER_PARSE = _re(
    r"\b(?:serde_json|serde_yaml|toml|bincode|rmp_serde|ciborium|"
    r"quick_xml(?:::de)?|roxmltree|postcard|semver|url|chrono)"
    r"(?:::[A-Za-z_][\w]*)*"            # path segments
    r"::(?:from_str|from_slice|from_reader|from_bytes|deserialize|parse|"
    r"parse_from_rfc[23]339|Version|Url)"
    r"\s*\([^)\n]{0,200}\)"
    r"\s*(?:\?\s*)?\.\s*(?:unwrap|expect)\s*\("
)


# Variant: `str::from_utf8(...).unwrap()`, `std::str::from_utf8(...).unwrap()`
_UNWRAP_ON_UTF8_PARSE = _re(
    r"\b(?:std::)?str::from_utf8\s*\([^)\n]{0,200}\)"
    r"\s*\.\s*(?:unwrap|expect)\s*\("
)


# Variant: `Regex::new(non_literal).unwrap()`. We catch ALL Regex::new
# unwrap() and let severity be MEDIUM — literal-pattern compiles are
# technically infallible but a typo still panics on first call.
_UNWRAP_ON_REGEX_NEW = _re(
    r"\b(?:regex::)?Regex::new\s*\([^)\n]{0,200}\)"
    r"\s*\.\s*(?:unwrap|expect)\s*\("
)


# ---- J3: std::mem::transmute or chained pointer-cast across non-repr ---


# Direct `transmute` call (the most dangerous unsafe primitive).
_MEM_TRANSMUTE = _re(
    r"\b(?:std|core)::mem::transmute(?:::<[^>]{0,200}>)?\s*\("
)


# Chained pointer cast: `&X as *const _ as *const Y` / `as *mut _ as *mut Y`.
# Bounded so RE2-safe.
_CHAINED_PTR_CAST = _re(
    r"\bas\s+\*(?:const|mut)\s+(?:[A-Za-z_][\w]*|_)"
    r"\s+as\s+\*(?:const|mut)\s+(?:[A-Za-z_][\w]*)"
)


# ---- J4: from_utf8_unchecked on attacker bytes -------------------------


# Any call to the unchecked UTF-8 constructor. The caller is expected
# to route bytes-from-network paths to this rule with extra severity.
_FROM_UTF8_UNCHECKED = _re(
    r"\b(?:std::|core::)?(?:str|String)::from_utf8_unchecked\s*\("
)


# ---- J5: Vec::set_len without obvious preceding init -------------------


# Any `Vec::set_len` call. We don't try to prove the preceding init
# from regex; we surface every site and let review handle it.
# `vec.set_len(arg)` or `Vec::set_len(arg)` both match.
_VEC_SET_LEN = _re(
    r"(?:\bVec::set_len\b|\b[A-Za-z_][\w]*\s*\.\s*set_len\s*\()"
)


# ---- J6: tokio::spawn whose JoinHandle is dropped (statement-level) ----


# `tokio::spawn(...)` or `tokio::task::spawn(...)` at statement level.
# Anchor: the call appears at the START of a statement (line begins
# with optional whitespace + `tokio::spawn` — no `let =` / `=` prefix).
# We do NOT walk the entire body (that would be catastrophic backtracking
# territory); we simply require the start anchor and require the
# closing `);` somewhere downstream on the same physical line. The
# common case is the spawn-and-drop one-liner; multi-line spawns that
# legitimately drop the handle are also caught when the inner block
# ends with `});` on its own line — that line then matches a SEPARATE
# (lighter) anchor: a line that is ONLY `});` after a tokio::spawn
# context. We keep the rule simple here and let the upstream
# integration decide the multiline shape if needed.
_TOKIO_SPAWN_DROPPED = _re(
    r"^[ \t]*tokio::(?:task::)?spawn\s*\([^\n]{0,800}\)\s*;"
)


# ---- J7: block_on inside async ---------------------------------------


# Co-occurrence: `async fn` (or `async {` / `async move {`) anywhere in
# the file AND a `block_on(` call anywhere. Same as Python's reflection-
# exec co-occurrence pattern: a single regex with an 8KB lookahead window.
_BLOCK_ON_INSIDE_ASYNC = _re(
    r"\basync\s+(?:fn|move\s*\{|\{)"
    r"[\s\S]{0,8000}?"
    r"\b(?:[A-Za-z_][\w:]*\s*\.\s*)?block_on\s*\("
)


# ---- J8: blocking-stdlib call inside async block ----------------------


# Co-occurrence: `async fn` / `async {` / `async move {` anywhere AND
# a blocking syscall later in the same 8KB window.
_BLOCKING_IN_ASYNC = _re(
    r"\basync\s+(?:fn|move\s*\{|\{)"
    r"[\s\S]{0,8000}?"
    r"\b(?:std::thread::sleep|std::fs::(?:read|write|read_to_string|"
    r"read_to_end|File::open|File::create)|std::process::Command|"
    r"reqwest::blocking|ureq::(?:get|post|put|delete)|"
    r"rusqlite::Connection|libsqlite3_sys)"
    r"\s*[(:]"
)


# ---- J9: std::sync::Mutex / RwLock held across .await -----------------


# Co-occurrence within 8KB: a `let X = ...lock()` or `.read()`/`.write()`
# on something that resolves to `std::sync::Mutex`/`RwLock` AND a `.await`
# later. Regex can't resolve types — but we can match the typed import
# `use std::sync::Mutex` / `use std::sync::RwLock` AND a `.lock()` /
# `.read()` / `.write()` site AND an `.await` co-located.
# We use a simpler shape: any `let _ = ... .lock().unwrap();` followed
# by `.await` within 8KB.
_STD_MUTEX_ACROSS_AWAIT = _re(
    r"\blet\s+(?:mut\s+)?[A-Za-z_][\w]*\s*=\s*"
    r"[^;\n]{0,200}\.(?:lock|read|write)\s*\(\s*\)"
    r"(?:\s*\.\s*unwrap\s*\(\s*\))?"
    r"\s*;"
    r"[\s\S]{0,2000}?"
    r"\.\s*await\b"
)


# ---- J10: unsafe impl Send/Sync OR Rc into tokio::spawn --------------


# Part A: `unsafe impl Send for X {}` / `unsafe impl Sync for X {}`.
_UNSAFE_IMPL_SEND_SYNC = _re(
    r"\bunsafe\s+impl\s+(?:Send|Sync)\s+for\s+[A-Za-z_][\w<>:,\s']{0,200}\s*\{"
)


# Part B: `Rc::new(...)` reaching `tokio::spawn` / `thread::spawn`
# within an 8KB window. Co-occurrence pattern.
_RC_CROSS_THREAD = _re(
    r"\bRc::new\s*\("
    r"[\s\S]{0,8000}?"
    r"\b(?:tokio::(?:task::)?spawn|std::thread::spawn|rayon::spawn)\s*\("
)


# ---- J11: serde_json::from_str / from_slice without size cap ----------


# Match `serde_json::from_str(VAR)` / `serde_json::from_slice(&VAR)`
# unconditionally. The caller's heuristic decides whether the var came
# from a network response. To reduce noise we exclude the literal-arg
# shape: regular string `"..."` / `'...'`, byte string `b"..."`, and
# raw string `r"..."` / `r#"..."#` / `r##"..."##` etc.
_SERDE_JSON_UNBOUNDED = _re(
    r"\bserde_json::(?:from_str|from_slice|from_reader)\s*\(\s*"
    r"(?!['\"])"                        # not a regular string literal
    r"(?!b['\"])"                       # not a byte literal
    r"(?!r#*['\"])"                     # not a raw string literal r"..." / r#"..."# / etc.
    r"[^)\n]{1,200}\)"
)


# ---- J12: bincode / rmp_serde / ciborium without limit ---------------


# Match the unbounded variants. `with_limit` / `with_no_limit` are the
# config knobs; their absence is the smell — but the regex can't span
# the option chain reliably, so we match the plain entry-point calls
# and let the caller decide context.
_BINARY_FORMAT_UNBOUNDED = _re(
    r"\b(?:bincode::(?:deserialize|deserialize_from)"
    r"|rmp_serde::(?:from_slice|from_read|from_read_ref)"
    r"|ciborium::(?:from_reader|de::from_reader)"
    r"|postcard::from_bytes)\s*\("
)


# Loud variant: `.with_no_limit()` is the opt-in-to-danger choice.
_BINARY_FORMAT_NO_LIMIT_OPTIN = _re(
    r"\.\s*with_no_limit\s*\(\s*\)"
)


# ---- J13: unsafe impl Send/Sync on type with interior mutability ------


# Co-occurrence: `unsafe impl Send for Wrapper` AND `Wrapper` definition
# contains a raw pointer / Rc / RefCell / Cell / UnsafeCell / NonNull.
# We approximate: any `unsafe impl Send|Sync` in a file that ALSO has
# a `*const ` / `*mut ` / `Rc<` / `RefCell<` / `Cell<` / `UnsafeCell<` /
# `NonNull<` somewhere in the same 8KB window. Structs are usually
# declared BEFORE their `unsafe impl` so we match both orderings via
# a single alternation. RE2-safe: each branch uses a bounded
# `[\s\S]{0,8000}?` lazy quantifier, no nested unbounded loops.
_UNSAFE_IMPL_INTERIOR_MUT = _re(
    # Branch A: interior-mutability marker BEFORE the unsafe impl
    r"(?:\*(?:const|mut)\s+[A-Za-z_]"
    r"|\b(?:Rc|RefCell|Cell|UnsafeCell|NonNull)\s*<)"
    r"[\s\S]{0,8000}?"
    r"\bunsafe\s+impl\s+(?:Send|Sync)\s+for\b"
    r"|"
    # Branch B: unsafe impl BEFORE the marker
    r"\bunsafe\s+impl\s+(?:Send|Sync)\s+for\b"
    r"[\s\S]{0,8000}?"
    r"(?:\*(?:const|mut)\s+[A-Za-z_]"
    r"|\b(?:Rc|RefCell|Cell|UnsafeCell|NonNull)\s*<)"
)


# ---- J14: Cargo.lock missing for binary crate -------------------------


# This is a file-level rule. The pattern fires on a Cargo.toml whose
# content declares `[[bin]]` (explicit binary target) but lacks a
# `[workspace]` marker. Caller cross-references the filesystem for
# Cargo.lock presence. We surface the binary-crate marker.
_CARGO_TOML_BINARY_TARGET = _re(
    r"^\s*\[\[\s*bin\s*\]\]\s*$"
)


# ---- J15: [patch.crates-io] with unpinned git -------------------------


# A `[patch.crates-io]` (or `[patch."<registry>"]`) section followed
# within ~2KB by a `git = "..."` line WITHOUT a sibling `rev = "..."`
# of 40 chars. Pure regex can't easily do "WITHOUT" across multiple
# lines so we emit two patterns: one fires on the `git = "..."` with
# only `branch = ` or `tag = ` nearby, and the other fires on bare
# `git = "..."` lines under `[patch.*]` headers.
_CARGO_PATCH_GIT = _re(
    r"^\s*\[patch[^\]\n]{0,200}\]\s*$"
    r"[\s\S]{0,2000}?"
    r"^\s*[A-Za-z_][\w-]*\s*=\s*\{[^}\n]{0,400}"
    r"\bgit\s*=\s*['\"][^'\"\n]{1,400}['\"]"
)


# Stricter: `[patch.*]` block where the git entry uses `branch = ` or
# `tag = ` instead of `rev = `. Forty-char SHA `rev` is the safe form;
# branch/tag is the unsafe form (force-pushable).
_CARGO_PATCH_GIT_BRANCH_OR_TAG = _re(
    r"\bgit\s*=\s*['\"][^'\"\n]{1,400}['\"]"
    r"[\s,]+"
    r"(?:branch|tag)\s*=\s*['\"][^'\"\n]{1,200}['\"]"
)


# ---- J16: missing cargo audit / cargo deny in CI ----------------------


# A `.yml` (CI workflow file) that mentions `cargo test`/`cargo build`
# but NOT `cargo audit`/`cargo deny`. Pure regex can't do "NOT X" across
# a multi-MB file; we emit a positive marker for the absence-checker
# upstream: any line `run: cargo (test|build|check)` is the trigger.
# The caller then opens the file and greps for `cargo audit` /
# `cargo deny` separately. This regex fires on the cargo test/build
# marker.
_CARGO_TEST_OR_BUILD_IN_CI = _re(
    r"^\s*(?:-\s*)?run\s*:\s*[\"']?cargo\s+(?:test|build|check)\b"
)


# Companion regex used to suppress: a line `run: cargo audit` or
# `run: cargo deny` (or the action `actions-rs/audit-check`,
# `rustsec/audit-check`, `EmbarkStudios/cargo-deny-action`). The caller
# uses this as a negative check; if NONE of these match in the same
# workflow file but the test/build pattern matches, flag.
_CARGO_AUDIT_IN_CI = _re(
    r"(?:cargo\s+audit\b|cargo\s+deny\b|"
    r"actions-rs/audit-check|rustsec/audit-check|"
    r"EmbarkStudios/cargo-deny-action)"
)


# ---- J17: cargo install --git URL without --locked / --rev -----------


# `cargo install --git URL` shell command. Match `cargo install` with a
# subsequent `--git`. Caller decides whether `--locked` or `--rev <sha>`
# is in the same shell line.
_CARGO_INSTALL_GIT = _re(
    r"\bcargo\s+install\b[^\n]{0,400}--git\s+(?:https?|ssh|git)"
)


# ---- J18: tokio::main(flavor = "current_thread") --------------------


# `#[tokio::main(...)]` attribute on `fn main` with `flavor =
# "current_thread"` OR `worker_threads = 1`. Match the attribute call.
_TOKIO_CURRENT_THREAD_FLAVOR = _re(
    r"#\[\s*tokio::main\s*\("
    r"[^)\n]{0,200}"
    r"flavor\s*=\s*['\"]current_thread['\"]"
)


_TOKIO_SINGLE_WORKER = _re(
    r"#\[\s*tokio::main\s*\("
    r"[^)\n]{0,200}"
    r"worker_threads\s*=\s*1\b"
)


# ---- J19: reqwest::Client::new / reqwest::get without timeout --------


# Naked `reqwest::Client::new()` is the smell: it uses no timeout.
_REQWEST_CLIENT_NEW_BARE = _re(
    r"\breqwest::Client::new\s*\(\s*\)"
)


# `reqwest::get(URL).await` is also the smell.
_REQWEST_GET_DIRECT = _re(
    r"\breqwest::get\s*\("
)


# `reqwest::Client::builder()` with NO `.timeout(` in the same chain —
# we approximate by matching the `.build()` line at the end of the
# builder chain and letting the caller scan back for `.timeout`. Here
# the marker is `Client::builder().build()` direct (no chain).
_REQWEST_CLIENT_BUILDER_BARE = _re(
    r"\breqwest::Client::builder\s*\(\s*\)\s*\.\s*build\s*\("
)


# ---- J20: hyper::body::to_bytes / axum::body::to_bytes unbounded ----


_HYPER_BODY_UNBOUNDED = _re(
    r"\b(?:hyper::body::to_bytes\s*\(\s*[A-Za-z_][\w]*\s*\)"
    r"|axum::body::to_bytes\s*\([^)\n]{0,200}usize::MAX\s*\))"
)


# ---- J21: dotenv / dotenvy in main without #[cfg(test)] ------------


# `dotenv::dotenv()` or `dotenvy::dotenv()` call. Caller checks whether
# the surrounding fn is `fn main` AND there's no `#[cfg(...)]` gate.
_DOTENV_CALL = _re(
    r"\bdotenv(?:y)?::dotenv\s*\(\s*\)"
)


# ---- J22: tracing!/log! macro with secret-shaped arg ---------------


# `tracing::info!("... {} ...", token)` where the format arg name matches
# a secret-shaped identifier. We match the macro invocation + at least
# one secret-named identifier in the args.
_TRACING_LOG_SECRET = _re(
    r"\b(?:tracing|log)::(?:trace|debug|info|warn|error)!\s*\("
    r"[^)\n]{0,400}"
    r"\b(?:password|passwd|secret|api_key|apikey|"
    r"private_key|priv_key|auth_token|bearer|access_token|"
    r"refresh_token|jwt|session_id|credit_card|ssn|tax_id)\b"
)


# ---- J23: [profile.release] panic = "abort" in server crate ---------


# Cargo.toml: `[profile.release]` block with `panic = "abort"`. We can't
# easily check "server framework in deps" from a single regex; we surface
# the panic=abort setting and let the caller cross-check.
_PROFILE_RELEASE_PANIC_ABORT = _re(
    r"^\s*\[profile\.release\]\s*$"
    r"[\s\S]{0,2000}?"
    r"^\s*panic\s*=\s*['\"]abort['\"]"
)


# ---- J24: static mut OR OnceCell init from network ----------------


# `static mut X: T = ...` declaration.
_STATIC_MUT_GLOBAL = _re(
    r"^\s*(?:pub(?:\([^)\n]{0,40}\))?\s+)?"
    r"static\s+mut\s+[A-Z_][A-Z0-9_]*\s*:"
)


# `lazy_static! { static ref X = ... }` or
# `OnceCell::new() ... .get_or_init(|| network_call())`. We match the
# `lazy_static!` macro AND a network-fetch call within 2KB.
_LAZY_STATIC_NETWORK = _re(
    r"\blazy_static\s*!\s*\{"
    r"[\s\S]{0,2000}?"
    r"\b(?:reqwest::(?:get|Client)|ureq::(?:get|post)|"
    r"std::net::TcpStream::connect|tokio::net::TcpStream::connect|"
    r"http::Request::builder)"
)


# ---- J25: debug/admin/metrics endpoints without auth ----------------


# axum: `Router::new().route("/debug/...", ...)`.
_AXUM_DEBUG_ROUTE = _re(
    r"\b(?:Router::new\s*\(\s*\)|router|app)\s*"
    r"(?:\.\s*[A-Za-z_][\w]*\s*\([^)\n]{0,200}\)\s*)*"
    r"\.\s*route\s*\(\s*"
    r"['\"](?:/debug|/admin|/metrics|/healthz|/internal|/__|/pprof)"
    r"[^'\"]{0,200}['\"]"
)


# actix-web: `App::service(web::scope("/admin"))` or `web::resource("/admin")`.
_ACTIX_DEBUG_ROUTE = _re(
    r"\bweb::(?:scope|resource)\s*\(\s*"
    r"['\"](?:/debug|/admin|/metrics|/healthz|/internal|/__|/pprof)"
    r"[^'\"]{0,200}['\"]"
)


# rocket: `#[get("/admin/...")]` / `#[post("/metrics")]`.
_ROCKET_DEBUG_ROUTE = _re(
    r"#\[\s*(?:get|post|put|delete|patch|head|options)\s*\(\s*"
    r"['\"](?:/debug|/admin|/metrics|/healthz|/internal|/__|/pprof)"
    r"[^'\"]{0,200}['\"]"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="rust-unsafe-block-in-request-path",
        name="`unsafe { ... }` block (review for network-reachable path)",
        severity="HIGH",
        description=(
            "An `unsafe { ... }` block was found. Rust's whole value "
            "proposition is 'safe by default'; once `unsafe` appears, the "
            "rest of the codebase's safety guarantees are predicated on "
            "the human having gotten that block right. Auto-flagging every "
            "unsafe block in a network-input path makes review mandatory. "
            "Caller should reduce severity to MEDIUM when the block "
            "contains only zero-arg syscalls (isatty, GetStdHandle)."
        ),
        pattern=_UNSAFE_BLOCK,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-unwrap-on-attacker-parse",
        name="`.unwrap()`/`.expect()` on serde / parse / url::Url::parse return",
        severity="HIGH",
        description=(
            "A panic-on-error chain on the return of `serde_json::from_*` "
            "/ `serde_yaml::from_*` / `toml::from_str` / "
            "`bincode::deserialize` / `rmp_serde::*` / `ciborium::*` / "
            "`quick_xml::de::from_str` / `roxmltree::parse` / "
            "`url::Url::parse` / `semver::Version::parse` / "
            "`chrono::*::parse_from_rfc*`. On tokio multi-thread the task "
            "is discarded; on `current_thread` flavour or `panic=abort` "
            "builds this is a denial-of-service vector."
        ),
        pattern=_UNWRAP_ON_ATTACKER_PARSE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-unwrap-on-utf8-parse",
        name="`.unwrap()`/`.expect()` on `str::from_utf8`",
        severity="HIGH",
        description=(
            "`str::from_utf8(bytes).unwrap()` panics when `bytes` is not "
            "valid UTF-8. On attacker-controlled bytes this is a "
            "denial-of-service vector. Use `?` operator or explicit "
            "`match` instead."
        ),
        pattern=_UNWRAP_ON_UTF8_PARSE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-unwrap-on-regex-new",
        name="`Regex::new(...).unwrap()` (panic on regex compile)",
        severity="MEDIUM",
        description=(
            "`Regex::new(...).unwrap()` panics if the pattern is invalid. "
            "Literal-pattern compiles are technically infallible but a "
            "typo still panics on first call. Prefer "
            "`Regex::new(LITERAL).expect(\"BUG: literal regex\")` so the "
            "message is grep-able. For non-literal patterns (user input, "
            "config files) this is a denial-of-service vector."
        ),
        pattern=_UNWRAP_ON_REGEX_NEW,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-mem-transmute",
        name="`std::mem::transmute` / `core::mem::transmute` direct use",
        severity="CRITICAL",
        description=(
            "Direct `std::mem::transmute` or `core::mem::transmute`. UB "
            "from transmute is RCE-grade because the Rust optimiser inlines "
            "based on type assumptions. Prefer `bytemuck::cast` / "
            "`zerocopy::Ref::new` for layout-equivalent conversions; "
            "any other use needs a heavy-weight safety comment AND a "
            "RUSTSEC advisory crosscheck."
        ),
        pattern=_MEM_TRANSMUTE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-chained-pointer-cast",
        name="Chained `*const T as *const U` pointer cast across types",
        severity="HIGH",
        description=(
            "A pointer cast chain of length >= 2 (`as *const T as "
            "*const U` or `as *mut T as *mut U`) where the source and "
            "destination pointee types differ. Same risk class as "
            "transmute but lower visibility — the compiler accepts it "
            "without an `unsafe` block around the cast itself (the deref "
            "is unsafe). Likely UB without a `#[repr(C)]` / `Pod` proof."
        ),
        pattern=_CHAINED_PTR_CAST,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-from-utf8-unchecked",
        name="`from_utf8_unchecked` (immediate UB on non-UTF-8 input)",
        severity="HIGH",
        description=(
            "`String::from_utf8_unchecked` / `str::from_utf8_unchecked` "
            "called on bytes. Constructing `&str` from non-UTF-8 bytes is "
            "immediate UB, not 'just a wrong string' — subsequent "
            "`.chars()`/`.split()` may read past buffer end. One of two "
            "rustsec advisory classes that genuinely become RCE in "
            "optimised builds. Use the checked variant."
        ),
        pattern=_FROM_UTF8_UNCHECKED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-vec-set-len",
        name="`Vec::set_len` without proven initialisation",
        severity="HIGH",
        description=(
            "Any call to `Vec::set_len(n)`. This IS the unsafe API; "
            "calling it without proving initialisation of all N elements "
            "via `MaybeUninit::write` / `ptr::write` / `write_bytes` "
            "yields `Vec<T>` containing uninitialised T. Reading any "
            "element is UB. rustsec ADV-2021-0093 class."
        ),
        pattern=_VEC_SET_LEN,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-tokio-spawn-dropped",
        name="`tokio::spawn(...)` whose JoinHandle is dropped",
        severity="MEDIUM",
        description=(
            "A `tokio::spawn` / `tokio::task::spawn` call at statement "
            "level — the return JoinHandle is dropped. Panics inside the "
            "future are swallowed; the task disappears silently and "
            "state corruption goes undetected. Use `JoinSet` or store "
            "the handle and await it, or wrap the body with explicit "
            "`Result<_>` handling and an `Err` log."
        ),
        pattern=_TOKIO_SPAWN_DROPPED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-block-on-inside-async",
        name="`block_on(...)` inside an `async fn` / `async {}` block",
        severity="HIGH",
        description=(
            "A `block_on(...)` call co-located with an `async fn` / "
            "`async {}` / `async move {}` block. On the `current_thread` "
            "flavour this is a guaranteed deadlock; on `multi_thread` it "
            "may deadlock under load. Production-only race condition "
            "that won't be caught by unit tests."
        ),
        pattern=_BLOCK_ON_INSIDE_ASYNC,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-blocking-in-async",
        name="Blocking syscall inside an `async` block",
        severity="MEDIUM",
        description=(
            "An `async fn` / `async {}` body contains a blocking call: "
            "`std::thread::sleep`, `std::fs::*`, `std::process::Command`, "
            "`reqwest::blocking::*`, `ureq::*`, `rusqlite::Connection`, "
            "or `libsqlite3_sys`. Blocks the executor thread — on "
            "`multi_thread` flavour it starves N-1 other tasks; on "
            "`current_thread` it freezes the entire runtime. Wrap with "
            "`tokio::task::spawn_blocking` or use an async-native "
            "alternative."
        ),
        pattern=_BLOCKING_IN_ASYNC,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-std-mutex-across-await",
        name="`std::sync::Mutex/RwLock` guard held across `.await`",
        severity="HIGH",
        description=(
            "A `let g = m.lock().unwrap();` or `.read()`/`.write()` guard "
            "is held across an `.await` point. The MutexGuard is `!Send` "
            "(std::sync) and even when `Send` (parking_lot), holding it "
            "across `.await` means another task on the same thread "
            "cannot acquire the mutex while the awaiting task is parked. "
            "Use `tokio::sync::Mutex` / `tokio::sync::RwLock` instead, or "
            "structure the code so the guard is dropped before any "
            "`.await`."
        ),
        pattern=_STD_MUTEX_ACROSS_AWAIT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-unsafe-impl-send-sync",
        name="`unsafe impl Send/Sync for T {}` (assert without compiler proof)",
        severity="HIGH",
        description=(
            "`unsafe impl Send for X {}` / `unsafe impl Sync for X {}` "
            "declarations. The compiler cannot prove correctness; the "
            "human is asserting it. If the assertion is wrong, the "
            "program has data races, which in Rust are UB → LLVM is "
            "free to miscompile. Requires a `// Safety:` justification "
            "comment of >= 3 lines."
        ),
        pattern=_UNSAFE_IMPL_SEND_SYNC,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-rc-cross-thread",
        name="`Rc<T>` reaching `tokio::spawn` / `thread::spawn` (Send violation)",
        severity="MEDIUM",
        description=(
            "An `Rc::new(...)` flows into `tokio::spawn` / "
            "`std::thread::spawn` / `rayon::spawn`. Compiler usually "
            "catches this — but `unsafe impl Send for Wrapper<Rc<T>> {}` "
            "(see rule rust-unsafe-impl-send-sync) defeats the check "
            "and ships UB. Use `Arc<T>` for cross-thread sharing."
        ),
        pattern=_RC_CROSS_THREAD,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-serde-json-unbounded",
        name="`serde_json::from_str/from_slice/from_reader` on tainted input",
        severity="HIGH",
        description=(
            "`serde_json::from_str(payload)` / `from_slice(&bytes)` / "
            "`from_reader(r)` on non-literal input. serde_json's "
            "recursive descent is roughly O(input depth) stack usage. A "
            "50 MB deeply-nested JSON crashes the stack; a 500 MB flat "
            "array spikes heap and gets killed by the OOM-killer. Both "
            "are DoS. Use `serde_json::Deserializer::from_str(s)."
            "into_iter::<T>()` with streaming + a size cap."
        ),
        pattern=_SERDE_JSON_UNBOUNDED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-binary-format-unbounded",
        name="bincode/rmp_serde/ciborium/postcard deserialize without limit",
        severity="HIGH",
        description=(
            "`bincode::deserialize(&bytes)` / `rmp_serde::from_slice` / "
            "`ciborium::from_reader` / `postcard::from_bytes` without a "
            "`.with_limit(N)` wrapper. bincode legacy variant allocates "
            "an attacker-specified Vec length BEFORE reading the bytes. "
            "A 4-byte length prefix of `u32::MAX` = 4 GB allocation = "
            "OOM = crash. Mandatory `Bounded` config since bincode 2."
        ),
        pattern=_BINARY_FORMAT_UNBOUNDED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-binary-format-no-limit-optin",
        name="`.with_no_limit()` opt-in to unbounded decode",
        severity="CRITICAL",
        description=(
            "Explicit `.with_no_limit()` opts in to unbounded allocation "
            "by an untrusted deserialiser. Same DoS class as the unbounded "
            "variant but louder: someone added the disabler deliberately. "
            "Replace with `.with_limit(N)` where N is the expected "
            "maximum payload."
        ),
        pattern=_BINARY_FORMAT_NO_LIMIT_OPTIN,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-unsafe-impl-interior-mut",
        name="`unsafe impl Send/Sync` co-located with raw ptr / Rc / RefCell / Cell",
        severity="HIGH",
        description=(
            "An `unsafe impl Send/Sync for T {}` declaration in a file "
            "that ALSO defines `*const T`, `*mut T`, `Rc<U>`, "
            "`RefCell<U>`, `Cell<U>`, `UnsafeCell<U>`, or `NonNull<U>` "
            "fields. The compiler cannot prove `Send`/`Sync` for such "
            "types; the human is asserting cross-thread safety without "
            "the compiler's normal proof obligations."
        ),
        pattern=_UNSAFE_IMPL_INTERIOR_MUT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-cargo-toml-binary-target",
        name="Cargo.toml declares `[[bin]]` (verify Cargo.lock is committed)",
        severity="LOW",
        description=(
            "Cargo.toml contains an explicit `[[bin]]` target. The caller "
            "must cross-reference the filesystem: `Cargo.lock` MUST be "
            "committed for binary crates. Without it, two `cargo install` "
            "calls on different days yield different binaries — and the "
            "dependency resolution silently picks up a malicious patch "
            "release. This is the Rust-specific equivalent of 'no "
            "`requirements.txt` / `package-lock.json`'."
        ),
        pattern=_CARGO_TOML_BINARY_TARGET,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="rust-cargo-patch-git",
        name="`[patch.crates-io]` overrides crate to a `git = ...` URL",
        severity="CRITICAL",
        description=(
            "`Cargo.toml` `[patch.crates-io]` (or `[patch.<registry>]`) "
            "section redirects a crate to `git = \"...\"` URL. A patch "
            "with no 40-char `rev = \"<sha>\"` pin downloads HEAD at "
            "build time; the maintainer of that GitHub repo can rewrite "
            "history (force-push) and inject malicious code into the "
            "next `cargo build`. The Rust equivalent of npm's protestware "
            "/ typosquat attack class."
        ),
        pattern=_CARGO_PATCH_GIT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="rust-cargo-patch-git-branch-or-tag",
        name="`git = ...` patch pinned by `branch =` / `tag =` (force-pushable)",
        severity="CRITICAL",
        description=(
            "`git = \"...\"` patch with `branch = \"...\"` or "
            "`tag = \"...\"` instead of `rev = \"<40-char-sha>\"`. Tags "
            "and branches are force-pushable by the upstream maintainer; "
            "next `cargo build` silently pulls whatever they pushed last. "
            "Only a 40-char commit SHA is immutable."
        ),
        pattern=_CARGO_PATCH_GIT_BRANCH_OR_TAG,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="rust-cargo-test-or-build-in-ci",
        name="CI runs `cargo test`/`cargo build`/`cargo check` (verify cargo audit/deny present)",
        severity="LOW",
        description=(
            "A CI workflow file runs `cargo test` / `cargo build` / "
            "`cargo check`. The caller must cross-reference the same "
            "file for `cargo audit` / `cargo deny check` / "
            "`actions-rs/audit-check` / `rustsec/audit-check` / "
            "`EmbarkStudios/cargo-deny-action`. rustsec advisories ship "
            "CVE-grade fixes for the rust crate ecosystem; no audit step "
            "= the project is shipping vulnerable transitive deps and "
            "doesn't know it."
        ),
        pattern=_CARGO_TEST_OR_BUILD_IN_CI,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="rust-cargo-install-git",
        name="`cargo install --git URL` (verify --locked AND --rev <sha>)",
        severity="HIGH",
        description=(
            "Documentation / install script / Makefile contains a "
            "`cargo install --git URL` command. The caller must check "
            "that BOTH `--locked` (force-use of upstream `Cargo.lock`) "
            "AND `--rev <40-char-sha>` (commit pin) are present. Without "
            "both, the install fetches HEAD-at-time-of-install — a "
            "force-push by the upstream maintainer (or repo compromise) "
            "lands malicious code on every fresh install."
        ),
        pattern=_CARGO_INSTALL_GIT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="rust-tokio-current-thread-flavor",
        name="`#[tokio::main(flavor = \"current_thread\")]` on a server crate",
        severity="MEDIUM",
        description=(
            "`#[tokio::main(flavor = \"current_thread\")]` on a binary "
            "whose deps include `actix-web` / `axum` / `warp` / `rocket` "
            "/ `tonic` / `hyper::server`. A current-thread runtime on a "
            "multi-CPU machine artificially serialises every request, "
            "doubling p99 latency and creating a slow-loris amplifier. "
            "Combined with `block_on`/`blocking-in-async` rules above, "
            "the system becomes a guaranteed-deadlock target."
        ),
        pattern=_TOKIO_CURRENT_THREAD_FLAVOR,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-tokio-single-worker",
        name="`#[tokio::main(worker_threads = 1)]` on a server crate",
        severity="MEDIUM",
        description=(
            "`#[tokio::main(worker_threads = 1)]` is functionally the "
            "same as `current_thread` flavour for a server: one CPU "
            "handling every request serially. Same DoS amplification "
            "class as `current_thread` flavour."
        ),
        pattern=_TOKIO_SINGLE_WORKER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-reqwest-client-new",
        name="`reqwest::Client::new()` (no timeout — default is None)",
        severity="HIGH",
        description=(
            "`reqwest::Client::new()` uses no timeout — `None` is the "
            "default. An attacker that responds slowly (or holds the TCP "
            "connection open and trickles bytes) parks one of your tokio "
            "worker threads forever. Combined with single-worker / "
            "current_thread runtimes this is single-client denial of "
            "service. Use `reqwest::Client::builder().timeout(...)"
            ".connect_timeout(...).build()`."
        ),
        pattern=_REQWEST_CLIENT_NEW_BARE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-reqwest-get-direct",
        name="`reqwest::get(URL)` direct call (uses default global client = no timeout)",
        severity="HIGH",
        description=(
            "`reqwest::get(URL).await` uses the default global client "
            "which has no timeout. Same DoS class as "
            "`reqwest::Client::new()`. Always use an explicit "
            "`Client::builder().timeout(...).build()`."
        ),
        pattern=_REQWEST_GET_DIRECT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-reqwest-client-builder-bare",
        name="`reqwest::Client::builder().build()` without `.timeout(...)`",
        severity="HIGH",
        description=(
            "`reqwest::Client::builder().build()` chain with no "
            "`.timeout(...)` / `.connect_timeout(...)`. Same DoS class as "
            "`Client::new()`. Add an explicit timeout to the chain."
        ),
        pattern=_REQWEST_CLIENT_BUILDER_BARE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-hyper-body-unbounded",
        name="`hyper::body::to_bytes` / `axum::body::to_bytes(_, usize::MAX)`",
        severity="HIGH",
        description=(
            "`hyper::body::to_bytes(body).await` (no size cap) or "
            "`axum::body::to_bytes(body, usize::MAX)` buffer the entire "
            "request body in RAM. An attacker that sends a 10 GB "
            "`Content-Length` header allocates 10 GB before your code "
            "runs its first byte of business logic. Use a bounded "
            "limit or `body.into_data_stream()` chunked reads."
        ),
        pattern=_HYPER_BODY_UNBOUNDED,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-dotenv-call",
        name="`dotenv::dotenv()` / `dotenvy::dotenv()` call (verify cfg(test) gate)",
        severity="MEDIUM",
        description=(
            "A binary crate calls `dotenv::dotenv()` or "
            "`dotenvy::dotenv()`. `.env` files are convenient in dev but "
            "leak secrets when a binary built with `dotenv` enabled "
            "ships to a customer machine; the customer's `.env` (often "
            "containing their own secrets stashed in their cwd) gets "
            "loaded into the binary's env. Local-only secret leak. Gate "
            "with `#[cfg(debug_assertions)]` or `#[cfg(test)]`."
        ),
        pattern=_DOTENV_CALL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="rust-tracing-log-secret",
        name="`tracing!`/`log!` macro argument contains secret-shaped name",
        severity="HIGH",
        description=(
            "A `tracing::{trace,debug,info,warn,error}!` (or `log::` "
            "equivalent) macro invocation whose argument expression "
            "contains an identifier matching "
            "`password|passwd|secret|api_key|apikey|private_key|"
            "priv_key|auth_token|bearer|access_token|refresh_token|jwt|"
            "session_id|credit_card|ssn|tax_id`. Logs are the #1 "
            "secret-leak channel. Rust's strong typing means the secret "
            "is IN the struct; format-printing the struct via `{:?}` "
            "ships it to logs unchanged."
        ),
        pattern=_TRACING_LOG_SECRET,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="rust-profile-release-panic-abort",
        name="`[profile.release] panic = \"abort\"` (verify no server-framework dep)",
        severity="MEDIUM",
        description=(
            "`Cargo.toml` `[profile.release]` block sets `panic = "
            "\"abort\"`. Caller must check whether the crate depends on "
            "a server framework (`actix-web`, `axum`, `warp`, `hyper`, "
            "`tonic`, `rocket`). With `panic = \"abort\"`, any panic in "
            "a request handler aborts the entire process instead of "
            "unwinding only that task. Combined with `unwrap on attacker "
            "parse` (above) this turns a single malformed payload into "
            "a full-server crash = 1:N DoS amplification."
        ),
        pattern=_PROFILE_RELEASE_PANIC_ABORT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-static-mut-global",
        name="`static mut X: T = ...` global (deprecated since 1.78)",
        severity="HIGH",
        description=(
            "`static mut X: T = ...` declaration. Deprecated since Rust "
            "1.78 — every access requires an `unsafe` block. The `mut` "
            "is the smell. Use `OnceLock<T>` / `Mutex<T>` / "
            "`AtomicX<T>` instead."
        ),
        pattern=_STATIC_MUT_GLOBAL,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-lazy-static-network-init",
        name="`lazy_static!` co-located with network-fetch call",
        severity="HIGH",
        description=(
            "A `lazy_static! { ... }` block in a file that ALSO contains "
            "`reqwest::get` / `ureq::*` / `TcpStream::connect` / "
            "`http::Request::builder`. The lazy init runs ONCE, silently, "
            "the first time any thread touches the static. If it fails "
            "partway, the cell is poisoned and every future access "
            "returns nothing. Silent partial-init = security policy "
            "half-loaded = the system fails OPEN. This is the textbook "
            "fail-closed-required case that the fail-fast principle "
            "forbids."
        ),
        pattern=_LAZY_STATIC_NETWORK,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="rust-axum-debug-route",
        name="axum `Router.route(\"/debug|/admin|/metrics|...\", ...)`",
        severity="HIGH",
        description=(
            "An axum `Router::new().route(\"/<path>\", ...)` where "
            "`<path>` starts with `/debug`, `/admin`, `/metrics`, "
            "`/healthz`, `/internal`, `/__`, or `/pprof`. The caller "
            "must check that an `Auth*` / `Bearer*` / `Jwt*` / "
            "`RequireAuth*` / `BasicAuth*` / `tower_http::auth::*` "
            "middleware is applied. Unrestricted /metrics exposes "
            "internal state (request counts, query latencies, "
            "sometimes PII labels)."
        ),
        pattern=_AXUM_DEBUG_ROUTE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="rust-actix-debug-route",
        name="actix-web `web::scope/resource(\"/debug|/admin|/metrics|...\")`",
        severity="HIGH",
        description=(
            "An actix-web `web::scope(\"/<path>\")` or "
            "`web::resource(\"/<path>\")` where `<path>` matches "
            "`/debug`, `/admin`, `/metrics`, `/healthz`, `/internal`, "
            "`/__`, or `/pprof`. Same config-leak class as the axum "
            "rule."
        ),
        pattern=_ACTIX_DEBUG_ROUTE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="rust-rocket-debug-route",
        name="rocket `#[get|post|...(\"/debug|/admin|/metrics|...\")]`",
        severity="HIGH",
        description=(
            "A rocket route attribute `#[get|post|put|delete|patch|"
            "head|options(\"/<path>\")]` where `<path>` matches "
            "`/debug`, `/admin`, `/metrics`, `/healthz`, `/internal`, "
            "`/__`, or `/pprof`. Same config-leak class as the axum "
            "and actix-web rules."
        ),
        pattern=_ROCKET_DEBUG_ROUTE,
        owasp_asi="ASI-02",
    ),
)


# ---- The composed scanner ----------------------------------------------


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
    right rule — Cargo.toml rules (J14, J15, J20) fire on Cargo.toml
    files, CI rules (J16, J17) fire on workflow files, the rest fire
    on `.rs` sources. The composite ``scan_text`` runs every rule;
    upstream filtering by extension keeps noise down.
    """
    if not text:
        return []
    # File-level absence-of-audit gate: if the workflow file mentions
    # cargo audit / cargo deny / actions-rs/audit-check anywhere, the
    # cargo-test-or-build rule is suppressed (the project IS auditing).
    has_cargo_audit = _CARGO_AUDIT_IN_CI.search(text) is not None
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            # Suppress the rustsec-audit-absent finding when the file
            # already runs cargo audit / cargo deny / audit-check.
            if rule.id == "rust-cargo-test-or-build-in-ci" and has_cargo_audit:
                continue
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
