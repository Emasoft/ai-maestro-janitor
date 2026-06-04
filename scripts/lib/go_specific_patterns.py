"""Go-language-specific attack-surface patterns.

Wave 21 impl-I — distillation of 15 Go-specific runtime/stdlib
pathology detectors from ``reports/distill-round-7/go-specific.md``
into deterministic regex rules.

The distill report proposed AST-level detectors (`go/ast` + `go/types`)
for shapes that the janitor's existing Go coverage does NOT touch:
``http.Server`` zero-value (slowloris), ``http.DefaultClient`` no-
timeout, ``DefaultServeMux`` global-mux registration, ``unsafe.Pointer``
slice walking and ``reflect.SliceHeader`` direct construction,
``sync.Mutex`` value-copy, unprotected map concurrent access,
missing ``defer mu.Unlock()`` on early return, goroutine leaks via
``<-ch`` without ``ctx.Done()``, ``time.After`` in select-in-loop,
unrecovered goroutine panics, ``context.Background()`` inside HTTP
handlers, ``template.HTML(userInput)`` type-conversion XSS, ``math/rand``
for security tokens, ignored ``crypto/rand.Read`` errors, ``init()``
network I/O at import time, and ``os.Setenv`` race on Go <1.21.

This module encodes the same shapes as **pure regex** for the
heartbeat detectors that prefer the lightweight one-pass scanner
over an AST walk. The regex rules accept a small precision
trade-off (slightly higher FP rate vs an AST walk that can reason
about scopes and types) in exchange for being trivially composable
with the other ``scripts/lib/*_patterns.py`` modules.

Architecture mirrors ``scripts/lib/python_specific_patterns.py`` and
``scripts/lib/agent_config_patterns.py``:

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
PEP 723 script block without third-party deps.

Severity mapping from the distill report onto the janitor's
canonical four-tier scale (CRITICAL / HIGH / MEDIUM / LOW). The
report explicitly classifies G6 (concurrent map) and G14 (init
network I/O) as CRITICAL because both are uncoverable: G6 is a
``fatal`` runtime panic that ``recover()`` cannot intercept, and
G14 runs at every ``go test`` of a downstream package as the build
user.

NON-DUPLICATION: ``scripts/lib/per_language_patterns.py`` already
covers Go ``go.mod replace`` directive hijack — NOT duplicated here.
Round 6 D5 / E covers ``database/sql`` SQL injection — NOT duplicated
here. Round 5 / ``crypto-misuse.md`` covers generic low-entropy
``crypto/rand`` seeding — G13 here narrows to the Go-specific
``math/rand`` vs. ``crypto/rand`` distinction.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    ``scripts/lib/agent_config_patterns.Finding`` so heartbeat
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
    """Compile a pattern with MULTILINE+UNICODE+DOTALL.

    Go identifiers and keywords are case-sensitive — so the regexes
    here do NOT use IGNORECASE (unlike the prose/config-file
    scanners). DOTALL is enabled because several detectors need to
    match across newlines inside struct literals or function bodies.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE | re.DOTALL)


# ---- G1: http.Server with no timeouts (slowloris) ----------------------


# ``&http.Server{...}`` composite literal that does NOT set ALL of
# ReadTimeout / WriteTimeout / IdleTimeout. We match the literal head
# and inspect the body. If any of the three timeout fields is absent,
# fire. We also catch the SHORT shape ``http.ListenAndServe(addr, h)``
# which uses the zero-value default Server.
#
# Pattern strategy: TWO alternatives.
# Branch A — ``http.ListenAndServe("addr", handler)`` direct shape:
#            always uses the default Server with zero timeouts.
# Branch B — ``&http.Server{...body...}`` where body is missing ANY
#            of ReadTimeout/WriteTimeout/IdleTimeout. We invert this:
#            we match ``&http.Server{`` then a body of bounded length
#            with NEGATIVE lookahead for all three field names. If
#            any field is missing the lookahead succeeds and we fire.
#
# RE2-safe: bounded {0,800} character body, no backreferences.
_GO_HTTP_SERVER_NO_TIMEOUTS = _re(
    # Branch A — direct http.ListenAndServe (uses default Server)
    r"\bhttp\.ListenAndServe(?:TLS)?\s*\("
    r"|"
    # Branch B — &http.Server{...} or http.Server{...} composite literal
    # whose body lacks ANY of the three timeout fields.
    r"(?:&)?\bhttp\.Server\s*\{"
    r"(?="
    # ANY body that is missing at least one of the three timeout fields:
    # the negative lookahead inside requires ALL THREE; we negate it.
    r"(?:"
    # 800-char body without the three timeout-field markers all present
    r"(?![^}]*\bReadTimeout\b)"
    r"|(?![^}]*\bWriteTimeout\b)"
    r"|(?![^}]*\bIdleTimeout\b)"
    r")"
    r")"
    r"[^}]{0,800}\}"
)


# ---- G2: http.DefaultClient / zero-value http.Client no timeout --------


# ``http.Get(``, ``http.Post(``, ``http.PostForm(``, ``http.Head(``
# all use ``http.DefaultClient`` internally — which has Timeout: 0.
# Also ``http.DefaultClient.Do(`` directly. Also ``http.Client{}``
# zero-value literal used as a client.
#
# RE2-safe: simple alternation.
_GO_HTTP_DEFAULT_CLIENT = _re(
    r"\bhttp\.(?:Get|Post|PostForm|Head)\s*\("
    r"|\bhttp\.DefaultClient\.(?:Do|Get|Post|Head)\s*\("
    r"|(?:&)?http\.Client\s*\{\s*\}"
)


# ---- G3: DefaultServeMux package-global registration -------------------


# ``http.HandleFunc("/path", h)`` or ``http.Handle("/path", h)`` at
# package level — registers to the module-global DefaultServeMux.
# The legitimate shape is ``mux.HandleFunc(...)`` (instance method
# on a *ServeMux) — we exclude that with a negative lookbehind on
# a dot+identifier prefix.
#
# RE2-safe: negative lookbehind is fixed-width so re module accepts it.
_GO_DEFAULT_SERVEMUX = _re(
    r"(?<![.\w])"
    r"\bhttp\.(?:HandleFunc|Handle)\s*\("
)


# ---- G4: unsafe.Pointer + uintptr arithmetic / reflect.SliceHeader -----


# Three shapes:
# A — ``unsafe.Pointer(uintptr(unsafe.Pointer(...)) + ...)`` arithmetic
# B — ``reflect.SliceHeader`` / ``reflect.StringHeader`` directly
#     constructed (deprecated in Go 1.17; GC cannot follow)
# C — ``unsafe.Slice((*T)(...), n)`` where n is NOT a const-looking token
#
# RE2-safe: bounded windows, no backreferences.
_GO_UNSAFE_POINTER_DANGER = _re(
    # A — unsafe.Pointer(uintptr( ... ) + ... ) arithmetic
    r"\bunsafe\.Pointer\s*\(\s*uintptr\s*\(\s*unsafe\.Pointer"
    # B — reflect.SliceHeader / reflect.StringHeader direct construction
    r"|\breflect\.(?:Slice|String)Header\s*\{"
    # B2 — *(*[]byte)(unsafe.Pointer(&sh)) reinterpret cast on a header
    r"|\*\s*\(\s*\*\s*\[\][A-Za-z_]\w*\s*\)\s*\(\s*unsafe\.Pointer"
    # C — unsafe.Slice( (*T)(p), n )
    r"|\bunsafe\.Slice\s*\("
)


# ---- G5: sync.Mutex / RWMutex / WaitGroup passed by value --------------


# Function-signature or method-receiver shape that takes a sync.* type
# by VALUE (not pointer). The presence of ``*`` immediately before the
# type means pointer (good); absence means value-copy (bad).
#
# Matches:
#   func process(m sync.Mutex)        — BAD
#   func (c Cache) Get() string { }   — caller cross-references Cache struct
#   func go-vet-flagged(wg sync.WaitGroup) — BAD
#
# Does NOT match:
#   func process(m *sync.Mutex)       — pointer is fine
#   func (c *Cache) Get() string { }  — pointer receiver is fine
#
# RE2-safe.
_GO_MUTEX_BY_VALUE = _re(
    r"\b(?:func\s*\(\s*[A-Za-z_]\w*\s+|[A-Za-z_]\w*\s+)"
    # Negative lookahead — NOT a pointer (no `*` before the type)
    r"(?!\*)"
    r"sync\.(?:Mutex|RWMutex|WaitGroup|Once|Map|Cond|Pool)\b"
)


# ---- G6: struct with map field + goroutine touching it ------------------


# We can't run a full data-flow walk in regex. Instead we fire on
# the SHAPE: a struct type declaration containing a ``map[K]V`` field
# WITHOUT a sibling ``sync.Mutex`` / ``sync.RWMutex`` / ``sync.Map``
# field. We use a bounded {0,400} window after the map-field line to
# scan for a lock field before the closing brace.
#
# RE2-safe: negative lookahead with bounded body.
_GO_UNPROTECTED_MAP_FIELD = _re(
    r"\btype\s+[A-Z]\w*\s+struct\s*\{"
    r"(?="
    # body contains a map field
    r"[^}]*\bmap\s*\[[^\]]+\]"
    r")"
    r"(?!"
    # body does NOT contain a lock field
    r"[^}]*\b(?:sync\.(?:Mutex|RWMutex|Map)|sync/atomic)\b"
    r")"
    r"[^}]{0,800}\}"
)


# ---- G7: mu.Lock() followed by early-return without defer Unlock --------


# Shape: ``mu.Lock()`` (or ``c.mu.Lock()``) NOT immediately followed
# by ``defer mu.Unlock()`` on the very next line. The 'defer Unlock
# immediately after Lock' idiom is the only safe pattern; anything
# else is a bug candidate.
#
# We fire on:
#   c.mu.Lock()
#   if err := validate(); err != nil { return err }   ← early return
#
# Pattern: ``.Lock()\n`` followed by a NON-defer line within 200 chars.
# Then a ``return`` keyword. If a ``defer`` for Unlock appears first
# we don't fire.
#
# RE2-safe: bounded 600-char window between Lock and return.
# We use [\s\S] (any char) rather than [^{}] because legitimate early-
# return patterns include `if err := ...; err != nil { return err }`
# which has braces between Lock and the return token.
_GO_LOCK_NO_DEFER_UNLOCK = _re(
    r"[\w.]+\.(?:Lock|RLock)\s*\(\s*\)"
    # Next thing on the next non-blank line MUST NOT be defer Unlock
    r"\s*(?:\n|;)"
    r"(?!\s*defer\s+[\w.]+\.(?:Unlock|RUnlock)\s*\()"
    # Within 600 chars, find a `return` keyword
    r"[\s\S]{0,600}?\breturn\b"
)


# ---- G8: goroutine receiving from channel without ctx.Done() -----------


# ``go func() { ... v := <-ch ... }()`` where the goroutine body
# does NOT contain ``case <-ctx.Done()`` or a ``context.Context``
# parameter. The goroutine parks on the receive forever if the sender
# never closes ``ch``.
#
# Pattern: ``go func(`` followed by body of bounded length containing
# ``<-`` (channel receive) but NOT containing ``ctx.Done`` or the
# word ``context`` within that window.
#
# RE2-safe: bounded 1200-char body, no backreferences. Uses negative
# lookahead with a bounded body window. We use [\s\S] (any char) rather
# than [^}] because a goroutine body can contain nested braces (inner
# select / for / closure), so excluding } truncates the lookahead too
# early.
_GO_GOROUTINE_CHANNEL_LEAK = _re(
    r"\bgo\s+func\s*\([^)]*\)\s*\{"
    r"(?="
    # Body contains a channel-receive `<-`
    r"[\s\S]{0,1200}<-"
    r")"
    r"(?!"
    # Body does NOT contain a ctx.Done bridge
    r"[\s\S]{0,1200}\bctx\.Done\s*\("
    r")"
    r"(?!"
    # Body does NOT contain a `context.Context` reference
    r"[\s\S]{0,1200}\bcontext\.(?:Context|Done)\b"
    r")"
)


# ---- G9: time.After inside a select inside a for-loop ------------------


# ``time.After(d)`` as a case arm in a ``select`` that runs in a
# loop. On Go <1.23 every iteration allocates a timer that runs to
# completion even if the select returns early.
#
# Pattern: a ``for`` keyword followed by ``select`` followed by a
# ``case <-time.After(`` within a bounded window. We require the
# specific ``case <-time.After(`` shape inside a select-in-for
# context.
#
# RE2-safe: bounded {0,400} window between for/select/time.After.
_GO_TIME_AFTER_IN_SELECT = _re(
    r"\bfor\s*(?:[A-Za-z_][^{]{0,80})?\{"
    r"[^{}]{0,400}?"
    r"\bselect\s*\{"
    r"[^{}]{0,400}?"
    r"\bcase\s+<-\s*time\.After\s*\("
)


# ---- G10: goroutine without recover() ----------------------------------


# ``go func() { ... }()`` whose body does NOT start with the recover
# idiom: ``defer func() { if r := recover(); r != nil { ... } }()``.
#
# Pattern: ``go func(`` followed by ``{`` followed by content of
# bounded length that does NOT contain ``recover()`` within the
# first 200 chars of the body. We use negative lookahead.
#
# RE2-safe: bounded windows, no backreferences.
_GO_GOROUTINE_NO_RECOVER = _re(
    r"\bgo\s+func\s*\([^)]{0,200}\)\s*"
    # No return type since this is a goroutine call
    r"\{"
    # Negative lookahead: first 400 chars of body must contain
    # `defer` + `recover` near the start
    r"(?!"
    r"\s*defer\s+(?:func\s*\(\s*\)\s*\{[^{}]{0,200}recover\s*\(|[^{}]{0,80}recover)"
    r")"
    # Body must be at least minimally non-trivial (10+ chars)
    r"[^{}]{10,800}"
    r"\}\s*\(\s*\)"
)


# ---- G11: context.Background() / TODO() inside HTTP handler ------------


# ``context.Background()`` or ``context.TODO()`` appearing inside the
# body of a ``func(w http.ResponseWriter, r *http.Request)`` handler.
# The detector matches the handler signature, then within a bounded
# window finds either Background/TODO.
#
# Pattern: handler signature followed by Background/TODO within a
# {0,1600}-char window inside the function body.
#
# RE2-safe: bounded windows.
_GO_CONTEXT_BACKGROUND_IN_HANDLER = _re(
    r"\bfunc\s+\w*\s*\([^)]{0,200}"
    r"http\.ResponseWriter[^)]{0,200}"
    r"\*\s*http\.Request[^)]{0,200}\)\s*\{"
    r"[^{}]{0,1600}?"
    r"\bcontext\.(?:Background|TODO)\s*\(\s*\)"
)


# ---- G12: template.HTML / template.JS / template.CSS type conversion ---


# ``template.HTML(varname)``, ``template.JS(...)``, ``template.CSS(...)``,
# ``template.URL(...)``, ``template.HTMLAttr(...)``, ``template.JSStr(...)``
# where the argument is NOT a string literal. These type conversions
# explicitly opt out of html/template's context-aware escaping → XSS.
#
# Pattern: match the call shape and require the first non-whitespace
# inside the parens to NOT be a quote. This is the same negative-
# lookahead trick used by ``py-dunder-import-nonliteral``.
#
# RE2-safe: bounded {1,200} character argument window.
_GO_TEMPLATE_HTML_TYPE_XSS = _re(
    r"\btemplate\.(?:HTML|JS|CSS|URL|HTMLAttr|JSStr|Srcset)\s*\(\s*"
    r"(?!['\"`])"
    r"(?![\)\n])"
    r"[A-Za-z_][\w.\[\]\(\) ]{0,200}\)"
)


# ---- G13: math/rand for security tokens --------------------------------


# Two-part shape:
# Part A — ``import "math/rand"`` or ``import _ "math/rand"`` appears
#          in the file. We use just the explicit math/rand string
#          since that's the trigger.
# Part B — On the same file, a security-keyword string appears.
#
# Pattern strategy: a single regex that matches ``math/rand`` and
# then within an 8KB window finds one of the security keywords. Plus
# a stricter pattern that matches direct ``rand.Read(`` / ``rand.Int(``
# usage within a function whose name contains a security keyword.
#
# RE2-safe: bounded {0,8000} window between the two markers.
_GO_MATH_RAND_FOR_SECURITY = _re(
    # Branch A — math/rand import co-located with security keywords
    r'"math/rand"'
    r"[\s\S]{0,8000}?"
    r"\b(?:token|session|csrf|apikey|api_key|secret|nonce|salt|"
    r"password|passphrase|seed|generateUUID|generateID)\b"
    # Branch B — explicit rand.Seed(time.Now().UnixNano()) pattern
    r"|\brand\.Seed\s*\(\s*time\.Now\s*\(\s*\)\.UnixNano\s*\(\s*\)"
    # Branch C — function name with security keyword USING math/rand
    r"|\bfunc\s+\w*(?:[Tt]oken|[Ss]ession|[Ss]ecret|[Nn]once|[Ss]alt|[Pp]assword|[Cc]srf|[Aa]piKey)\w*"
    r"\s*\([^{]{0,200}\{[^{}]{0,400}\brand\.(?:Read|Int|Intn|Int31|Int63|Float)"
)


# ---- G13a: crypto/rand error ignored -----------------------------------


# ``rand.Read(b)`` from ``crypto/rand`` where the returned error is
# discarded with ``_`` or the call result is ignored entirely. On
# non-Linux platforms ``crypto/rand`` can fail (Windows BCryptGenRandom
# refusal, BSD getrandom unavailable on old kernel) — silent fallback
# to zero bytes is catastrophic.
#
# Pattern: assignment shape ``_, _ := rand.Read(`` or unhandled bare
# call ``rand.Read(`` not in a context where the error is captured.
#
# RE2-safe: simple alternation.
_GO_CRYPTORAND_ERR_IGNORED = _re(
    # `_, _ = rand.Read(b)` or `_, _ := rand.Read(b)` — explicit discard
    r"\b_\s*,\s*_\s*:?=\s*rand\.Read\s*\("
    # Bare call as a statement: `rand.Read(b)` with no LHS
    r"|^\s*rand\.Read\s*\("
)


# ---- G14: init() doing network I/O -------------------------------------


# ``func init() { ... }`` body containing ``net.Dial(``, ``http.Get(``,
# ``http.Post(``, ``exec.Command(`` of a network tool, or any
# ``Open*`` of a remote DSN. Also a package-level var that calls a
# network function: ``var X = fetchURL(...)``.
#
# Pattern: ``func init`` followed by a body window containing one of
# the network primitives.
#
# RE2-safe: bounded {0,2000} body window.
_GO_INIT_NETWORK_IO = _re(
    # Branch A — func init() body with network primitive
    r"\bfunc\s+init\s*\(\s*\)\s*\{"
    r"[^{}]{0,2000}?"
    r"(?:"
    r"\bnet\.Dial\b"
    r"|\bnet\.Listen\b"
    r"|\bhttp\.(?:Get|Post|PostForm|Head|NewRequest)\b"
    r"|\bexec\.Command\b"
    r"|\bos/exec\b"
    r"|\bsql\.Open\b"
    r"|\burl\.Parse\b[^{}]{0,200}\bhttp"
    r")"
    # Branch B — package-level var with network-call shape
    r"|^var\s+\w+\s*=\s*"
    r"(?:"
    r"\bhttp\.(?:Get|Post|Head)\b"
    r"|\bmust\w*[Ff]etch\w*\s*\("
    r"|\bnet\.Dial\b"
    r")"
)


# ---- G15: os.Setenv in a goroutine or post-main code -------------------


# ``os.Setenv(`` or ``os.Unsetenv(`` called from any function that is
# reachable from a goroutine. Pre-Go 1.21, these calls were not safe
# for concurrent use. The file-level heuristic: any ``os.Setenv(`` in
# a file that ALSO has ``go `` keyword (goroutine launch), where the
# Setenv is NOT inside an obvious main() pre-goroutine block.
#
# Pattern: file-level shape — ``go func`` or ``go <Identifier>(`` AND
# ``os.Setenv(`` co-located in the same file within an 8KB window.
#
# RE2-safe: bounded {0,8000} window.
_GO_OS_SETENV_RACE = _re(
    # Branch A — `go ` goroutine launch AND `os.Setenv(` within 8KB
    r"\bgo\s+(?:func\s*\(|[A-Za-z_]\w*\s*\()"
    r"[\s\S]{0,8000}?"
    r"\bos\.(?:Setenv|Unsetenv)\s*\("
    # Branch B — `os.Setenv(` first, then `go ` later
    r"|\bos\.(?:Setenv|Unsetenv)\s*\("
    r"[\s\S]{0,8000}?"
    r"\bgo\s+(?:func\s*\(|[A-Za-z_]\w*\s*\()"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="go-http-server-no-timeouts",
        name="http.Server without ReadTimeout/WriteTimeout/IdleTimeout (slowloris)",
        severity="HIGH",
        description=(
            "&http.Server{...} composite literal missing one or more of "
            "ReadTimeout / WriteTimeout / IdleTimeout, OR direct "
            "http.ListenAndServe(addr, h) call. The zero-value Server "
            "has all timeouts at 0 (infinite), so a slowloris attacker "
            "can hold thousands of TCP sockets open by sending one byte "
            "every 30 seconds. CVE-2016-2849-class. Anchor: P1, "
            "pkg.go.dev/net/http#Server."
        ),
        pattern=_GO_HTTP_SERVER_NO_TIMEOUTS,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="go-http-default-client",
        name="http.DefaultClient or zero-value http.Client has no timeout",
        severity="HIGH",
        description=(
            "http.Get / http.Post / http.PostForm / http.Head — all use "
            "http.DefaultClient whose Timeout is 0 (no timeout). Also "
            "&http.Client{} zero-value literal used to make outbound "
            "calls. A hung upstream pins the goroutine forever and "
            "exhausts file descriptors. gosec G107. Anchor: P2, "
            "pkg.go.dev/net/http#Client.Timeout."
        ),
        pattern=_GO_HTTP_DEFAULT_CLIENT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="go-default-servemux-handlefunc",
        name="http.HandleFunc / http.Handle registers on global DefaultServeMux",
        severity="HIGH",
        description=(
            "Package-level http.HandleFunc(\"/path\", h) or http.Handle(...) "
            "registers on the module-global http.DefaultServeMux. Any "
            "imported package can do the same — including transitive "
            "deps. Classic exploit: `import _ \"net/http/pprof\"` "
            "registers /debug/pprof/ on DefaultServeMux, letting any "
            "client dump heap profiles and goroutine stacks. gosec G114. "
            "Anchor: P3, pkg.go.dev/net/http#ServeMux."
        ),
        pattern=_GO_DEFAULT_SERVEMUX,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="go-unsafe-pointer-slice-walk",
        name="unsafe.Pointer arithmetic / reflect.SliceHeader direct construction",
        severity="HIGH",
        description=(
            "unsafe.Pointer(uintptr(unsafe.Pointer(...)) + offset) "
            "arithmetic across slice boundaries, OR reflect.SliceHeader "
            "/ reflect.StringHeader constructed by hand (the GC cannot "
            "follow these headers — they are documented Unsafe since "
            "Go 1.17), OR unsafe.Slice((*T)(p), n) with un-validated n. "
            "Type confusion, OOB read/write, heap corruption. CWE-787. "
            "Anchor: P4, golang.org/issue/19367."
        ),
        pattern=_GO_UNSAFE_POINTER_DANGER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="go-mutex-by-value",
        name="sync.Mutex / WaitGroup / Once passed by value (lock copy)",
        severity="HIGH",
        description=(
            "Function signature, method receiver, or struct field "
            "passes sync.Mutex / sync.RWMutex / sync.WaitGroup / "
            "sync.Once / sync.Map by VALUE (no `*`). The copy protects "
            "a different memory location than the original; concurrent "
            "writes to the supposedly-protected state race silently. "
            "go vet -copylocks ships with the stdlib and catches this "
            "since 2017. CWE-820. Anchor: P5."
        ),
        pattern=_GO_MUTEX_BY_VALUE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="go-map-concurrent-access-no-lock",
        name="struct has map[K]V field but no sibling sync.Mutex / sync.Map",
        severity="CRITICAL",
        description=(
            "Type declaration `type X struct { ... map[K]V ... }` whose "
            "body does NOT also contain a sync.Mutex / sync.RWMutex / "
            "sync.Map field. Concurrent read/write of a built-in map "
            "produces `fatal error: concurrent map read and map write` "
            "— a FATAL panic from runtime/map.go that `recover()` "
            "cannot intercept. The process dies. CWE-664. Anchor: P6."
        ),
        pattern=_GO_UNPROTECTED_MAP_FIELD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="go-defer-unlock-missing-early-return",
        name=".Lock() not immediately followed by defer .Unlock() with early return",
        severity="HIGH",
        description=(
            "A `.Lock()` call NOT immediately followed by a `defer "
            "...Unlock()` on the next line, where the same function "
            "contains a `return` keyword. Early-exit paths leave the "
            "mutex held forever; subsequent callers block indefinitely. "
            "Hard to diagnose because the symptom is silent: no error, "
            "no log, just freeze. CWE-667. Anchor: P14."
        ),
        pattern=_GO_LOCK_NO_DEFER_UNLOCK,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="go-goroutine-leak-unbounded-channel-recv",
        name="goroutine receives from channel without ctx.Done bridge",
        severity="MEDIUM",
        description=(
            "`go func() { ... <-ch ... }()` whose body does NOT contain "
            "`case <-ctx.Done()` or a `context.Context` reference. If "
            "the sender never closes the channel, the goroutine parks "
            "forever; under load the leak is unbounded and eventually "
            "OOMs the process. CWE-401. Anchor: P7, "
            "pkg.go.dev/runtime#NumGoroutine."
        ),
        pattern=_GO_GOROUTINE_CHANNEL_LEAK,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="go-time-after-in-select-in-loop",
        name="time.After in a select inside a for-loop (timer leak pre-Go-1.23)",
        severity="MEDIUM",
        description=(
            "`case <-time.After(d):` inside a `select` inside a `for` "
            "loop. On Go <1.23 (still production for many), every "
            "iteration allocates a timer that runs to completion even "
            "when the other arm wins; under load this accumulates "
            "thousands of dangling timers. Go 1.23 fixes the allocation, "
            "but older toolchains still ship. CWE-401. Anchor: P8, "
            "golang.org/issue/27169."
        ),
        pattern=_GO_TIME_AFTER_IN_SELECT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="go-goroutine-panic-no-recover",
        name="goroutine body lacks defer/recover guard",
        severity="HIGH",
        description=(
            "`go func() { ... }()` whose body does NOT start with the "
            "recover idiom `defer func() { if r := recover(); r != nil "
            "{ ... } }()`. A panic in goroutine A crashes the ENTIRE "
            "process — there is no per-goroutine uncaught-exception "
            "handler. One unguarded type assertion / nil pointer / "
            "out-of-bounds index takes down the whole daemon. "
            "CWE-755. Anchor: P9, pkg.go.dev/builtin#recover."
        ),
        pattern=_GO_GOROUTINE_NO_RECOVER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="go-context-background-in-handler",
        name="context.Background / TODO used inside HTTP handler",
        severity="MEDIUM",
        description=(
            "`context.Background()` or `context.TODO()` appearing inside "
            "the body of a `func(w http.ResponseWriter, r *http.Request)` "
            "handler. The correct context is `r.Context()` — which is "
            "cancelled when the client disconnects or WriteTimeout "
            "fires. Using Background means outbound DB/RPC calls keep "
            "running after the client gave up, wasting CPU, DB conns, "
            "and goroutines. CWE-400. Anchor: P12."
        ),
        pattern=_GO_CONTEXT_BACKGROUND_IN_HANDLER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="go-template-html-js-type-conversion-xss",
        name="template.HTML / template.JS type conversion with non-literal arg",
        severity="HIGH",
        description=(
            "`template.HTML(x)`, `template.JS(x)`, `template.CSS(x)`, "
            "`template.URL(x)`, `template.HTMLAttr(x)`, "
            "`template.JSStr(x)` where x is NOT a string literal. These "
            "type conversions explicitly OPT OUT of html/template's "
            "context-aware escaping — they exist so trusted markup can "
            "pass through, but accepting user input through them is XSS "
            "by construction. CWE-79. Anchor: P11, "
            "pkg.go.dev/html/template#HTML."
        ),
        pattern=_GO_TEMPLATE_HTML_TYPE_XSS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="go-math-rand-for-security",
        name="math/rand used for token / session / nonce generation",
        severity="HIGH",
        description=(
            "Import of `math/rand` co-located with security-keyword "
            "strings (token, session, csrf, apikey, secret, nonce, "
            "salt, password), OR direct rand.Seed(time.Now().UnixNano()) "
            "pattern, OR a function named with a security keyword that "
            "calls rand.Read / rand.Int / rand.Intn. math/rand is a "
            "Mersenne Twister — a handful of outputs reveal the seed and "
            "all future outputs become predictable. gosec G404. CWE-338. "
            "Anchor: P10."
        ),
        pattern=_GO_MATH_RAND_FOR_SECURITY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="go-cryptorand-error-ignored",
        name="crypto/rand.Read error discarded (silent zero-bytes fallback)",
        severity="HIGH",
        description=(
            "`_, _ = rand.Read(b)` or bare `rand.Read(b)` statement "
            "without capturing the returned error. On Linux this is "
            "rare; on Windows (BCryptGenRandom can refuse) and BSD "
            "(getrandom missing on old kernels) it can fail and the "
            "buffer remains all-zeros. Silent zero-bytes for a session "
            "token or nonce is catastrophic. Sub-rule of G13. Anchor: P10."
        ),
        pattern=_GO_CRYPTORAND_ERR_IGNORED,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="go-init-network-io",
        name="func init() performs net.Dial / http.Get / exec.Command (supply-chain beacon)",
        severity="CRITICAL",
        description=(
            "`func init() { ... }` body performs network I/O — net.Dial, "
            "http.Get, http.Post, exec.Command of a network tool, "
            "sql.Open of a remote DSN. Also a package-level var "
            "(`var X = mustFetch(...)`) that triggers the same path. "
            "init() runs at import time, BEFORE main, BEFORE logging "
            "config, BEFORE flag.Parse — and runs in `go test ./...` of "
            "any downstream consumer, on a privileged CI build node. "
            "Classic Go-flavor of the event-stream npm attack. CWE-829. "
            "Anchor: P15."
        ),
        pattern=_GO_INIT_NETWORK_IO,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="go-os-setenv-race-pre-1.21",
        name="os.Setenv reachable from goroutines (race on Go <1.21)",
        severity="MEDIUM",
        description=(
            "File contains both `os.Setenv` / `os.Unsetenv` and a `go` "
            "statement launching a goroutine. Pre-Go-1.21 these calls "
            "were NOT safe for concurrent use due to a race in the C "
            "`environ` glibc backing (golang.org/issue/15050). Go 1.21+ "
            "made them atomic but does not back-port; every binary "
            "built with an older toolchain still ships the bug. CWE-362. "
            "Anchor: P13."
        ),
        pattern=_GO_OS_SETENV_RACE,
        owasp_asi="ASI-05",
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

    Unlike ``agent_config_patterns.scan_text`` this scanner does not
    differentiate prose vs source — every rule here targets a specific
    Go source-file shape and the caller routes only ``*.go`` files
    through it. The caller may further restrict by file basename
    (e.g. exclude ``*_test.go`` for the math/rand rule since test
    fixtures commonly use deterministic RNG).

    Findings are deduped by ``(rule_id, line, col)`` — a single line
    that triggers two rules emits two findings, but the same rule
    firing twice on the same line emits one.
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
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
