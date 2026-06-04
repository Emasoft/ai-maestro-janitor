"""Tests for scripts/lib/dos_resource_patterns.py.

Pattern-coverage tests for the Wave-17 DoS / resource-exhaustion
catalogue (catastrophic-backtracking regexes, shell + Python fork
bombs, XML billion-laughs, recursive YAML aliases, JSON-bombs behind
gzip, busy-spin loops, subprocess.Popen-in-loop process bombs, fd-leak
open-in-loop). Every rule gets at least one positive + 1-2 negative
tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import dos_resource_patterns as drp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_eight_detectors() -> None:
    """RULES must be a tuple and contain every advertised rule id from
    the distill-pass-3 / agent-H proposal."""
    assert isinstance(drp.RULES, tuple)
    rule_ids = {r.id for r in drp.RULES}
    expected = {
        "regex-catastrophic-backtrack",
        "fork-bomb-shell",
        "xml-billion-laughs",
        "yaml-recursive-alias",
        "json-bomb-deep-nested-gzipped",
        "busy-spin-loop-no-upper-bound",
        "subprocess-popen-in-loop-no-wait",
        "fd-leak-open-in-loop",
    }
    assert expected == rule_ids, (
        f"missing: {expected - rule_ids}, extra: {rule_ids - expected}"
    )


def test_every_rule_has_owasp_mapping_and_valid_severity() -> None:
    """All DoS rules map to ASI-08 (Resource Exhaustion / DoS); severity
    must be one of CRITICAL/HIGH/MEDIUM/LOW."""
    for rule in drp.RULES:
        assert rule.owasp_asi == "ASI-08", rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors agent_config_patterns.Finding so downstream
    renderers handle DoS + prompt-injection findings uniformly."""
    f = drp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-08"


def _hits(rule_id: str, text: str) -> list[drp.Finding]:
    """Return only findings of `rule_id` from scan_text(text)."""
    return [f for f in drp.scan_text(text) if f.rule_id == rule_id]


# ---------- 1. Catastrophic-backtracking ReDoS ---------------------------


def test_redos_nested_quantifier_positive() -> None:
    """Shape A — `(a+)+` (nested quantifier on a repeating group)."""
    assert _hits(
        "regex-catastrophic-backtrack",
        r're.compile(r"(.+)+abc")',
    )


def test_redos_word_class_nested_positive() -> None:
    """Shape A variant — `(\\w*)*`."""
    assert _hits(
        "regex-catastrophic-backtrack",
        r'pat = re.compile(r"(\w*)*$")',
    )


def test_redos_alternation_overlap_positive() -> None:
    """Shape B — `(a|a)+` (same alternative on both sides of `|`)."""
    assert _hits(
        "regex-catastrophic-backtrack",
        r'rx = re.compile(r"(abc|abc)+")',
    )


def test_redos_adjacent_quantifier_positive() -> None:
    """Shape C — `\\w+\\w+` (adjacent quantified atoms)."""
    assert _hits(
        "regex-catastrophic-backtrack",
        r'p = re.compile(r"\w+\w+@example.com")',
    )


def test_redos_safe_quantifier_no_match() -> None:
    """Non-nested quantifier on a non-repeating group must NOT match."""
    assert not _hits(
        "regex-catastrophic-backtrack",
        r'pat = re.compile(r"[a-z]+@example.com")',
    )


def test_redos_simple_class_no_match() -> None:
    """A simple character class with one quantifier is safe."""
    assert not _hits(
        "regex-catastrophic-backtrack",
        r're.compile(r"^[a-zA-Z0-9_-]+$")',
    )


# ---------- 2. Fork-bomb shapes ------------------------------------------


def test_fork_bomb_classic_bash_positive() -> None:
    """The canonical `:(){:|:&};:` shape — must trigger CRITICAL."""
    findings = _hits("fork-bomb-shell", ":(){:|:&};:")
    assert findings
    assert findings[0].severity == "CRITICAL"


def test_fork_bomb_classic_whitespaced_positive() -> None:
    """Whitespace-padded variant `: ( ) { : | : & } ; :`."""
    assert _hits("fork-bomb-shell", ": () { : | : & } ; :")


def test_fork_bomb_renamed_function_positive() -> None:
    """Named-function variant `bomb(){bomb|bomb&};bomb`."""
    assert _hits("fork-bomb-shell", "bomb(){bomb|bomb&};bomb")


def test_fork_bomb_python_positive() -> None:
    """Python `while True: os.fork()` — never a legitimate prod pattern."""
    src = (
        "import os\n"
        "while True:\n"
        "    os.fork()\n"
    )
    assert _hits("fork-bomb-shell", src)


def test_fork_bomb_normal_function_no_match() -> None:
    """A normal Python `while True: do_work()` loop must NOT match."""
    src = (
        "while True:\n"
        "    do_work()\n"
        "    if done: break\n"
    )
    assert not _hits("fork-bomb-shell", src)


def test_fork_bomb_non_recursive_named_function_no_match() -> None:
    """`func(){other|other&};other` (no self-recursion) must NOT match —
    the backreference requires the SAME name across all four uses."""
    assert not _hits("fork-bomb-shell", "alpha(){beta|gamma&};delta")


# ---------- 3. XML billion-laughs ----------------------------------------


def test_xml_billion_laughs_positive() -> None:
    """ENTITY whose body has 2+ refs to other entities — fan-out blow-up."""
    xml = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE lolz [\n'
        '  <!ENTITY lol "lol">\n'
        '  <!ENTITY lol2 "&lol;&lol;&lol;&lol;">\n'
        '  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;">\n'
        ']>\n'
        '<lolz>&lol3;</lolz>\n'
    )
    assert _hits("xml-billion-laughs", xml)


def test_xml_single_entity_safe_no_match() -> None:
    """A benign single-level `<!ENTITY copyright "© 2026">` must NOT match
    — its body contains no entity references."""
    xml = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE doc [\n'
        '  <!ENTITY copyright "© 2026 ACME">\n'
        ']>\n'
        '<doc>&copyright;</doc>\n'
    )
    assert not _hits("xml-billion-laughs", xml)


def test_xml_plain_document_no_match() -> None:
    """An XML document with no DOCTYPE at all must NOT match."""
    xml = '<?xml version="1.0"?>\n<root><a>1</a><b>2</b></root>'
    assert not _hits("xml-billion-laughs", xml)


# ---------- 4. Recursive YAML alias --------------------------------------


def test_yaml_recursive_alias_positive() -> None:
    """`&foo` declared, then `<<: *foo` merge-into-self further down."""
    yaml_text = (
        "base: &foo\n"
        "  a: 1\n"
        "  b: 2\n"
        "derived:\n"
        "  <<: *foo\n"
        "  c: 3\n"
    )
    assert _hits("yaml-recursive-alias", yaml_text)


def test_yaml_plain_anchor_no_self_merge_no_match() -> None:
    """An anchor + a plain `*foo` reference (not via `<<:`) is the normal
    YAML reuse shape and must NOT match — it's not recursive."""
    yaml_text = (
        "defaults: &foo {a: 1, b: 2}\n"
        "target: *foo\n"
    )
    assert not _hits("yaml-recursive-alias", yaml_text)


def test_yaml_no_anchors_no_match() -> None:
    """A YAML document with no anchors / no aliases at all is safe."""
    yaml_text = "a: 1\nb: 2\nc: [3, 4, 5]\n"
    assert not _hits("yaml-recursive-alias", yaml_text)


# ---------- 5. JSON-bomb behind gzip -------------------------------------


def test_json_bomb_gzip_decompress_loads_positive() -> None:
    """`gzip.decompress(...)` followed shortly by `json.loads(...)`."""
    src = (
        "raw = gzip.decompress(payload)\n"
        "data = json.loads(raw)\n"
    )
    assert _hits("json-bomb-deep-nested-gzipped", src)


def test_json_bomb_zlib_decompress_load_positive() -> None:
    """`zlib.decompress(...)` followed by `json.load(...)` is the same
    attack surface — both fully buffer the decompressed JSON."""
    src = (
        "decoded = zlib.decompress(buf)\n"
        "json.load(io.StringIO(decoded))\n"
    )
    assert _hits("json-bomb-deep-nested-gzipped", src)


def test_json_bomb_requests_get_json_positive() -> None:
    """`requests.get(url).json()` without stream=True is the canonical
    full-body-buffer shape that auto-decompresses gzip."""
    src = 'data = requests.get("https://example.org/api").json()'
    assert _hits("json-bomb-deep-nested-gzipped", src)


def test_json_bomb_httpx_post_json_positive() -> None:
    """`httpx.post(url, json=...).json()` shape from the httpx ecosystem."""
    src = 'response = httpx.post(url, json=payload).json()'
    assert _hits("json-bomb-deep-nested-gzipped", src)


def test_json_bomb_plain_json_load_no_match() -> None:
    """Plain `json.load(open(path))` on a local file is safe — no
    gzip/zlib decompress in the chain, no HTTP fetch."""
    src = 'data = json.load(open("config.json"))'
    assert not _hits("json-bomb-deep-nested-gzipped", src)


def test_json_bomb_unrelated_decompress_no_match() -> None:
    """`gzip.decompress` followed by anything other than `json.loads`
    (e.g. writing to disk) must NOT match."""
    src = (
        "raw = gzip.decompress(payload)\n"
        'Path("out.bin").write_bytes(raw)\n'
    )
    assert not _hits("json-bomb-deep-nested-gzipped", src)


# ---------- 6. Busy-spin loop --------------------------------------------


def test_busy_spin_while_true_pass_positive() -> None:
    """`while True: pass` — burns a CPU core forever."""
    src = "while True:\n    pass\n"
    assert _hits("busy-spin-loop-no-upper-bound", src)


def test_busy_spin_while_1_continue_positive() -> None:
    """`while 1: continue` shape — equivalent attack."""
    src = "while 1:\n    continue\n"
    assert _hits("busy-spin-loop-no-upper-bound", src)


def test_busy_spin_while_true_zero_sleep_positive() -> None:
    """`while True: time.sleep(0)` — does NOT yield to other tasks."""
    src = "while True:\n    time.sleep(0)\n"
    assert _hits("busy-spin-loop-no-upper-bound", src)


def test_busy_spin_legitimate_loop_no_match() -> None:
    """`while True:` that does real work (or sleeps non-zero) must NOT
    match — that's a normal event loop."""
    src = (
        "while True:\n"
        "    result = queue.get()\n"
        "    process(result)\n"
    )
    assert not _hits("busy-spin-loop-no-upper-bound", src)


def test_busy_spin_sleep_one_second_no_match() -> None:
    """`while True: time.sleep(1)` yields the CPU and is safe."""
    src = "while True:\n    time.sleep(1)\n"
    assert not _hits("busy-spin-loop-no-upper-bound", src)


# ---------- 7. subprocess.Popen-in-loop process bomb ---------------------


def test_process_bomb_popen_for_loop_positive() -> None:
    """`for ...: subprocess.Popen(...)` with no wait/communicate."""
    src = (
        "for cmd in commands:\n"
        "    subprocess.Popen(cmd)\n"
        "    log_started(cmd)\n"
    )
    assert _hits("subprocess-popen-in-loop-no-wait", src)


def test_process_bomb_popen_while_loop_positive() -> None:
    """`while ...: subprocess.Popen(...)` no-wait shape."""
    src = (
        "while pending:\n"
        "    subprocess.Popen(spawn_cmd)\n"
        "    pending = next_batch()\n"
    )
    assert _hits("subprocess-popen-in-loop-no-wait", src)


def test_process_bomb_with_wait_no_match() -> None:
    """Popen in loop WITH `.wait()` in the same iteration is legitimate
    — the parent reaps each child before the next spawn."""
    src = (
        "for cmd in commands:\n"
        "    proc = subprocess.Popen(cmd)\n"
        "    proc.wait()\n"
    )
    assert not _hits("subprocess-popen-in-loop-no-wait", src)


def test_process_bomb_communicate_no_match() -> None:
    """Popen + `.communicate()` is the canonical safe shape."""
    src = (
        "for cmd in commands:\n"
        "    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)\n"
        "    out, err = proc.communicate()\n"
    )
    assert not _hits("subprocess-popen-in-loop-no-wait", src)


# ---------- 8. fd-leak open()-in-loop ------------------------------------


def test_fd_leak_open_in_for_loop_positive() -> None:
    """`for ...: open(...)` with no close, no `with`."""
    src = (
        "for path in paths:\n"
        "    open(path)\n"
        "    log_seen(path)\n"
    )
    assert _hits("fd-leak-open-in-loop", src)


def test_fd_leak_io_open_in_while_loop_positive() -> None:
    """`while ...: io.open(...)` — same fd-exhaustion shape."""
    src = (
        "while paths:\n"
        "    io.open(paths.pop())\n"
        "    counter += 1\n"
    )
    assert _hits("fd-leak-open-in-loop", src)


def test_fd_leak_with_open_no_match() -> None:
    """`with open(...) as f:` is the safe Python idiom — must NOT match."""
    src = (
        "for path in paths:\n"
        "    with open(path) as f:\n"
        "        data = f.read()\n"
    )
    assert not _hits("fd-leak-open-in-loop", src)


def test_fd_leak_open_then_close_no_match() -> None:
    """Explicit `.close()` within a few lines of `open()` is also safe."""
    src = (
        "for path in paths:\n"
        "    f = open(path)\n"
        "    data = f.read()\n"
        "    f.close()\n"
    )
    assert not _hits("fd-leak-open-in-loop", src)


# ---------- Composed scan_text behaviour ---------------------------------


def test_scan_text_empty_returns_empty_list() -> None:
    """Empty input is a no-op — must not raise."""
    assert drp.scan_text("") == []


def test_scan_text_findings_are_sorted_by_position() -> None:
    """Findings sorted by (line, column, rule_id) for stable output."""
    text = (
        "while True:\n"
        "    pass\n"
        ":(){:|:&};:\n"
    )
    findings = drp.scan_text(text)
    assert len(findings) >= 2
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_scan_text_long_match_is_truncated() -> None:
    """matched_text capped at 200 chars + ellipsis."""
    long_yaml = (
        "x: &foo\n"
        + "  noise: " + ("X" * 1000) + "\n"
        + "y:\n"
        + "  <<: *foo\n"
    )
    findings = _hits("yaml-recursive-alias", long_yaml)
    assert findings
    assert len(findings[0].matched_text) <= 201  # 200 + ellipsis


def test_scan_text_line_column_one_based() -> None:
    """Lines + columns 1-based (matches human traceback convention)."""
    text = (
        "harmless: 1\n"
        ":(){:|:&};:\n"
    )
    findings = _hits("fork-bomb-shell", text)
    assert findings
    assert findings[0].line == 2
    assert findings[0].column == 1
