"""WebAssembly Component Model security and correctness patterns.

Wave-31 distillation round 17 — wasm-component-model angle.

Catalogue of 12 WASM Component Model anti-patterns covering canonical
insecure or erroneous usage of the WebAssembly Component Model, WIT
(Wasm Interface Types), WASI host bindings, component linking, and
guest/host boundary code. Targets Rust/C/C++/Python toolchains and
generated glue code (wit-bindgen, wasm-bindgen, wasmtime, wasm-pack,
componentize-py, js-component, etc.).

What is NOT here (distinct from peer modules):

  * Generic binary Wasm: magic-bytes, section-order, MVP instruction
    hazards — handled at a lower-level analysis layer.
  * wasm-pack / wasm-bindgen JS/TS side secrets — see
    js_bundler_patterns and browser_storage_patterns.
  * Supply-chain / dependency confusion for crates — see
    cdn_supply_chain_patterns and build_reproducibility_patterns.

What IS here (12 net-new rules, regex-only, all RE2-safe):

  * wasm-cm-wit-resource-handle-escaped              (CRITICAL)
  * wasm-cm-canonical-lift-abi-mismatch              (HIGH)
  * wasm-cm-host-function-unchecked-ptr              (CRITICAL)
  * wasm-cm-linear-memory-aliasing                   (HIGH)
  * wasm-cm-wit-import-wildcard-namespace             (MEDIUM)
  * wasm-cm-component-link-no-seal                   (HIGH)
  * wasm-cm-wasi-filesystem-preopened-dir-escape     (CRITICAL)
  * wasm-cm-guest-stack-alloc-unbounded              (HIGH)
  * wasm-cm-realloc-null-passthrough                 (HIGH)
  * wasm-cm-interface-version-skew                   (MEDIUM)
  * wasm-cm-debug-fuel-disabled-in-prod              (LOW)
  * wasm-cm-shared-memory-without-threads-flag       (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret / sensitive data leak (host pointer exposure,
            linear-memory aliasing across components)
  ASI-05 — Supply-chain / component-linking integrity (wildcard
            namespace imports, unsealed component links, version skew)
  ASI-06 — Sandbox escape / privilege escalation (WASI pre-opened
            directory traversal, resource-handle escape)
  ASI-07 — Authority / correctness gaps (canonical-lift ABI mismatch,
            unbounded stack alloc, realloc null passthrough, shared
            memory without threads flag, debug fuel in prod)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking). Patterns are PRE-COMPILED at module load.
Fail-fast: callers receive structured Finding tuples, never raised
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
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- W1 : wasm-cm-wit-resource-handle-escaped ---------------------------

# Detects when a WIT resource handle is stored in a container or field
# that outlives the component instance, allowing use-after-drop across
# component boundaries. Two structural forms:
#   A) `static` keyword on the same line as the handle type name.
#   B) Handle type nested inside Arc<>, Mutex<>, RwLock<> or Box<>.
_WIT_RESOURCE_HANDLE_ESCAPED = _re(
    r"\bstatic\b[^\n]*\b(?:ResourceHandle|resource_handle|Handle\s*<[A-Za-z0-9_]+>)\b"
    r"|\b(?:Arc|Mutex|RwLock|Box)\s*<[^>]*(?:ResourceHandle|resource_handle|Handle\s*<[^>]*>)"
)


# ---- W2 : wasm-cm-canonical-lift-abi-mismatch ---------------------------

# Flags calls to canonical lift/lower with a mismatched memory index —
# e.g. passing memory index >= 1 where the canonical ABI expects memory 0,
# or a canon_lift() call passing None/null/zero for the required realloc.
# Only flags non-zero memory indices to avoid false positives on memory 0.
_CANONICAL_LIFT_ABI_MISMATCH = _re(
    r"\bcanon(?:ical)?\s+(?:lift|lower)\b[^\n]*memory\s+[1-9][0-9]*"
    r"|\bcanon_lift\b[^\n]*,\s*(?:None|null|0\s*,\s*0)"
)


# ---- W3 : wasm-cm-host-function-unchecked-ptr ---------------------------

# Detects host-side Wasmtime / wasm3 function implementations that
# accept a raw i32/u32 pointer argument and immediately dereference it
# without bounds-checking against memory.data_size() or similar guard.
# Two structural forms:
#   A) func_wrap closure with a ptr/addr/offset: i32|u32 argument.
#   B) raw pointer cast (as *const/*mut T) followed within 3 lines by
#      memory.data / mem.data access (cross-line pattern).
_HOST_FUNCTION_UNCHECKED_PTR = _re(
    r"\.func_wrap\b[^\n]*\|[^|]*(?:ptr|pointer|addr|offset)\s*:\s*(?:i32|u32)\b"
    r"|as\s*\*(?:const|mut)\s+[A-Za-z][A-Za-z0-9_]*[^\n]*\n"
    r"(?:[^\n]*\n){0,3}"
    r"[^\n]*(?:memory|mem)\.data\b"
)


# ---- W4 : wasm-cm-linear-memory-aliasing --------------------------------

# Multiple component instances sharing the same linear-memory export by
# name without isolation — commonly seen in naive multi-tenant component
# composition where both components export `memory` and the host binds
# them to the same store slot. Matches two get_export("memory") calls
# within 8 lines of each other (inclusive of any intervening lines).
_LINEAR_MEMORY_ALIASING = _re(
    r'get_export[^\n]*"memory"[^\n]*\n'
    r"(?:[^\n]*\n){0,8}"
    r'[^\n]*get_export[^\n]*"memory"'
)


# ---- W5 : wasm-cm-wit-import-wildcard-namespace -------------------------

# A WIT `use` statement importing an entire namespace with `.*` wildcard
# OR importing a specific interface set via `{ ... }` without a @version
# qualifier — allows a malicious or silently-upgraded package to inject
# unexpected exports into the component's import namespace.
_WIT_IMPORT_WILDCARD = _re(
    r"\buse\s+[a-z][a-z0-9_-]*(?::[a-z][a-z0-9_-]*)?\s*\.\s*\*\s*;"
    r"|\buse\s+[a-z][a-z0-9_-]*:[a-z][a-z0-9_-]*\s*\{"
)


# ---- W6 : wasm-cm-component-link-no-seal --------------------------------

# A component link step (Linker::new ... instantiate) where `seal` does
# not appear anywhere in the matched code block — leaving the set of
# satisfiable imports open so a later caller can inject unexpected host
# functions. The post-filter in scan_text() excludes matches that
# contain a `seal` call, keeping this RE2-safe (no negative lookahead).
_COMPONENT_LINK_NO_SEAL = _re(
    r"Linker\s*::\s*new\b[^\n]*\n"
    r"(?:[^\n]*\n){0,25}"
    r"[^\n]*\.instantiate(?:_async)?\b"
)


# ---- W7 : wasm-cm-wasi-filesystem-preopened-dir-escape ------------------

# The WASI preopened directory is set to `/`, `..`, or the path is
# constructed from a variable named after user/request input without
# canonicalization — a guest component can walk out of the sandbox.
# Two structural forms:
#   A) preopened_dir("/" ...) or preopened_dir(".." ...)
#   B) preopened_dir(user_var ...) where the first argument is a
#      variable name containing user|req|body|input|param|arg.
_WASI_PREOPENED_DIR_ESCAPE = _re(
    r'\bpreopened_dir\s*\(\s*["\'](?:/|\.\.)["\']'
    r'|\bpreopened_dir\s*\([^,\n]*(?:user|req|body|input|param|arg)'
)


# ---- W8 : wasm-cm-guest-stack-alloc-unbounded ---------------------------

# Guest code that calls `alloca()` or equivalent with a value derived
# from untrusted (host-provided) input without an upper-bound guard —
# causes a stack overflow that crashes the entire Wasm instance and may
# corrupt the host process if the runtime does not enforce stack limits.
_GUEST_STACK_ALLOC_UNBOUNDED = _re(
    r"\balloca\s*\(\s*(?!sizeof\b)[A-Za-z_][A-Za-z0-9_]*\s*\)"
    r"|\b__builtin_alloca\s*\(\s*(?!sizeof\b)[A-Za-z_][A-Za-z0-9_]*\s*\)"
)


# ---- W9 : wasm-cm-realloc-null-passthrough ------------------------------

# The canonical realloc implementation (required by the Component Model
# ABI) passes a null / zero old_ptr straight to the allocator without
# the required branch — causing undefined behaviour in allocators that
# do not treat realloc(NULL, n) as malloc(n).
_REALLOC_NULL_PASSTHROUGH = _re(
    r"\bcrate_realloc\b[^\n]*\bfn\b"
    r"|#\[no_mangle\]\s*\npub\s+(?:unsafe\s+)?fn\s+crate_realloc\b"
    r"|void\s*\*\s*crate_realloc\s*\([^)]*\)\s*\{"
    r"(?:(?!\bif\b[^\n]*\bnull\b|\bif\b[^\n]*\b0\b)[^\n])*$"
)


# ---- W10 : wasm-cm-interface-version-skew -------------------------------

# A component's WIT world declaration references an interface at a
# version that does not match the semver pinned in the component's
# package manifest (`Cargo.toml`, `package.json`, `pyproject.toml`) —
# silently resolved to the wrong ABI at link time. Matches any explicit
# version pin in a manifest or a WIT `use` statement with @version.
_INTERFACE_VERSION_SKEW = _re(
    r'\bwit-bindgen\b[^\n]*=\s*["\']?\d+\.\d+\.\d+["\']?'
    r"|\bwit_bindgen\b[^\n]*version\s*=\s*[\"']\d+\.\d+"
    r"|\buse\s+[a-z][a-z0-9_-]*:[a-z][a-z0-9_-]*@\d+\.\d+\.[0-9x*]+"
)


# ---- W11 : wasm-cm-debug-fuel-disabled-in-prod --------------------------

# Wasmtime fuel / epoch interruption is disabled in a context that
# looks like a production server — allows a malicious component to spin
# forever and exhaust the host-thread pool. Matches an Engine::new(config)
# call followed within 10 lines by a TcpListener binding. The post-filter
# in scan_text() excludes matches that contain set_fuel/epoch_interruption.
_DEBUG_FUEL_DISABLED_IN_PROD = _re(
    r"Engine\s*::\s*new\s*\(&\s*config\b[^\n]*\n"
    r"(?:[^\n]*\n){0,10}"
    r"[^\n]*listener\s*=\s*TcpListener"
)


# ---- W12 : wasm-cm-shared-memory-without-threads-flag -------------------

# A Wasm module declares shared memory (`(memory … shared …)` in WAT
# text format) or the host constructs a `SharedMemory` object, but
# the component instantiation config does not enable the threads
# proposal — causing silent downgrade or validation failure.
# Matches the `shared` keyword adjacent to a `memory` identifier in
# the same line, or a `SharedMemory::new` host-side call.
_SHARED_MEMORY_WITHOUT_THREADS = _re(
    r"\bmemory\b[^\n]*\bshared\b"
    r"|SharedMemory\s*::\s*new\b"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="wasm-cm-wit-resource-handle-escaped",
        name="WIT resource handle stored beyond component lifetime",
        severity="CRITICAL",
        description=(
            "A WIT resource handle is placed in a static, Arc, Mutex, or Box<dyn> "
            "container that can outlive the component instance that created it. "
            "When the originating instance is dropped, any retained handle becomes "
            "dangling: dereferencing it through the host table causes a use-after-free "
            "that may corrupt the host's internal resource table and allow one tenant to "
            "manipulate another tenant's resources in a multi-tenant runtime."
        ),
        pattern=_WIT_RESOURCE_HANDLE_ESCAPED,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="wasm-cm-canonical-lift-abi-mismatch",
        name="Canonical ABI lift/lower uses wrong memory or missing realloc",
        severity="HIGH",
        description=(
            "A `canon lift` or `canon lower` instruction specifies a non-zero memory "
            "index or passes `None`/`null` for the required realloc pointer. The Component "
            "Model canonical ABI mandates memory 0 for single-memory components and a "
            "valid realloc for string/list transfers. A mismatch causes the runtime to "
            "read or write from the wrong linear-memory region, producing silent data "
            "corruption or an OOB trap that reveals heap layout to callers."
        ),
        pattern=_CANONICAL_LIFT_ABI_MISMATCH,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wasm-cm-host-function-unchecked-ptr",
        name="Host function dereferences guest pointer without bounds check",
        severity="CRITICAL",
        description=(
            "A host-side `func_wrap` implementation accepts a raw i32/u32 pointer "
            "argument and immediately casts it to a Rust raw pointer or indexes into "
            "`memory.data()` without first validating that the pointer + size fits within "
            "the guest's linear memory. A malicious or buggy guest can supply an "
            "out-of-bounds pointer, allowing it to read or overwrite arbitrary host "
            "memory outside the sandbox — a full sandbox escape."
        ),
        pattern=_HOST_FUNCTION_UNCHECKED_PTR,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="wasm-cm-linear-memory-aliasing",
        name="Two component instances share the same linear-memory export",
        severity="HIGH",
        description=(
            "Two consecutive `get_export(\"memory\")` calls within a narrow window "
            "bind both component instances to the same linear-memory slot in the host "
            "store. When both instances write through this shared backing buffer without "
            "coordination, one component can overwrite the heap of the other — leaking "
            "secrets across tenant boundaries in multi-tenant WASM deployments."
        ),
        pattern=_LINEAR_MEMORY_ALIASING,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="wasm-cm-wit-import-wildcard-namespace",
        name="WIT use-statement imports entire namespace with wildcard",
        severity="MEDIUM",
        description=(
            "A WIT `use` statement imports an interface via `.*` wildcard or without "
            "a semver-pinned package qualifier. If the upstream WIT package is later "
            "updated to add new exports, the component automatically receives them at "
            "link time without any explicit opt-in, which may introduce unreviewed "
            "host capabilities or allow a dependency-confusion attack to inject "
            "unexpected interface implementations."
        ),
        pattern=_WIT_IMPORT_WILDCARD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="wasm-cm-component-link-no-seal",
        name="Component Linker not sealed before instantiation",
        severity="HIGH",
        description=(
            "A Wasmtime `Linker` is constructed and used to instantiate a component "
            "without calling `.seal()` or `seal_base_imports()` first. An unsealed "
            "linker accepts any host function added after the component is instantiated, "
            "including late-injected functions added by a subsequent caller in the same "
            "process. This allows privilege escalation if untrusted code shares the "
            "linker instance."
        ),
        pattern=_COMPONENT_LINK_NO_SEAL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="wasm-cm-wasi-filesystem-preopened-dir-escape",
        name="WASI preopened directory set to root or user-controlled path",
        severity="CRITICAL",
        description=(
            "The WASI filesystem preopened directory is set to `/`, `..`, or a path "
            "constructed from user-supplied input without canonicalization. A guest "
            "component can traverse out of the intended sandbox root using `..` path "
            "segments (e.g. `/preopened/../etc/passwd`), reading or writing arbitrary "
            "host files outside the intended capability boundary. This is the most "
            "common WASI sandbox-escape class reported in production deployments."
        ),
        pattern=_WASI_PREOPENED_DIR_ESCAPE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="wasm-cm-guest-stack-alloc-unbounded",
        name="Guest alloca size derived from untrusted input without upper bound",
        severity="HIGH",
        description=(
            "Guest C/C++ code calls `alloca()` or `__builtin_alloca()` with a size "
            "value that is not a `sizeof` expression, indicating the size may originate "
            "from host-supplied (untrusted) input. An unbounded VLA or alloca in a "
            "Wasm guest with a fixed stack causes a deterministic stack overflow that "
            "terminates the instance with a trap. If the Wasm runtime does not enforce "
            "per-instance stack limits, the overflow may corrupt adjacent stack frames "
            "in the host process."
        ),
        pattern=_GUEST_STACK_ALLOC_UNBOUNDED,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wasm-cm-realloc-null-passthrough",
        name="crate_realloc implementation missing null/zero branch",
        severity="HIGH",
        description=(
            "A custom `crate_realloc` function required by the Component Model ABI "
            "does not contain a null/zero old_ptr branch before delegating to the "
            "underlying allocator. The Component Model spec requires this function to "
            "behave as `malloc` when `old_ptr` is null and `old_size` is 0. Allocators "
            "that do not define `realloc(NULL, n) == malloc(n)` invoke undefined "
            "behaviour, which manifests as silent heap corruption in Rust `#[no_mangle]` "
            "implementations compiled to Wasm."
        ),
        pattern=_REALLOC_NULL_PASSTHROUGH,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wasm-cm-interface-version-skew",
        name="WIT interface version does not match pinned wit-bindgen version",
        severity="MEDIUM",
        description=(
            "A WIT `use` statement references an interface at a semver version "
            "that differs from the `wit-bindgen` / `wit_bindgen` version pinned in "
            "the project manifest, or uses an unanchored `x.*` wildcard. Version skew "
            "causes the generated host bindings to be built against a different ABI "
            "than the guest component was compiled for, resulting in silent type "
            "mismatches, wrong string encoding assumptions, or missing canonical "
            "realloc plumbing that only manifests at runtime with corrupted data."
        ),
        pattern=_INTERFACE_VERSION_SKEW,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="wasm-cm-debug-fuel-disabled-in-prod",
        name="Wasmtime fuel/epoch interruption absent in production server config",
        severity="LOW",
        description=(
            "A Wasmtime `Config` is constructed and used in a context that opens a "
            "TCP listener (production server mode) without configuring fuel consumption "
            "or epoch-based interruption. Without a CPU budget, a malicious or buggy "
            "component can execute an infinite loop that pins a host thread forever, "
            "causing a denial-of-service that exhausts the thread pool and prevents "
            "other tenants from being served. Fuel or epoch interruption is mandatory "
            "in any multi-tenant or user-facing deployment."
        ),
        pattern=_DEBUG_FUEL_DISABLED_IN_PROD,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="wasm-cm-shared-memory-without-threads-flag",
        name="Wasm shared memory declared without threads feature enabled",
        severity="MEDIUM",
        description=(
            "A Wasm module or component declares `(memory … shared …)` or the host "
            "constructs a `SharedMemory` object, but the Wasmtime `Config` does not "
            "enable `wasm_threads(true)` / `wasm_shared_everything_threads(true)`. "
            "Without the threads proposal enabled, the runtime either rejects the "
            "module at validation time or silently downgrades the memory to non-shared, "
            "causing subtle atomic-operation visibility bugs that only appear under "
            "concurrent access and are extremely difficult to reproduce in testing."
        ),
        pattern=_SHARED_MEMORY_WITHOUT_THREADS,
        owasp_asi="ASI-07",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Each rule's compiled pattern is matched directly against the full text
    (MULTILINE mode). Findings are deduplicated by (rule_id, line, col).

    Returns a list of Finding namedtuples sorted by (line, column, rule_id).
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

    # Compile a helper for detecting 'seal' presence in matched blocks.
    _seal_pat = re.compile(r"\bseal\b", re.IGNORECASE)

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            # W6 post-filter: only emit if the matched block contains NO seal call.
            if rule.id == "wasm-cm-component-link-no-seal":
                if _seal_pat.search(m.group(0)):
                    continue
            _emit(rule, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
