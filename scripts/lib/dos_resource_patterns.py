"""DoS / resource-exhaustion attack patterns.

Wave 17 (distill round 3, agent H) of the github-monitoring distillation.
Patterns convergent across: bheeshma (rule-linter catastrophic-regex
trio), tocsin (shell-pattern fork-bomb scanner), defusedxml
(tests/test_xmlrpc.py billion-laughs golden corpus + sister
`defusedyaml` recursive-alias documentation), mcp-shield (psutil
fd/process/CPU delta watchers reformulated as static source patterns),
and supply-chain-guardian's `runtime_monitor.py` thresholds.

This module is the RULE-PATTERN catalogue for static DoS detectors. Pure
regex / pure-stdlib so it loads in every PEP 723 script block without
third-party deps. The patterns deliberately favour FP-tolerance over
precision — the caller does the contextual triage (file kind, severity,
posture mode).

Detectors implemented (full distill list ports 1..8 — the inotify and
ulimit candidates from the same agent were explicitly demoted to
out-of-scope by the distill itself because their blast radius is
runtime-only):

  1. regex-catastrophic-backtrack          — HIGH      ReDoS shapes A/B/C
  2. fork-bomb-shell                       — CRITICAL  `:(){:|:&};:` + Py
  3. xml-billion-laughs                    — CRITICAL  ENTITY fan-out
  4. yaml-recursive-alias                  — HIGH      `&a` + `<<: *a` fallback
  5. json-bomb-deep-nested-gzipped         — HIGH      gzip→json.loads sequence
  6. busy-spin-loop-no-upper-bound         — MEDIUM    `while True: pass`
  7. subprocess-popen-in-loop-no-wait      — CRITICAL  Popen in loop, no wait
  8. fd-leak-open-in-loop                  — HIGH      open() in loop, no close

Severity strings match the existing janitor convention
("CRITICAL"/"HIGH"/"MEDIUM"/"LOW") so downstream renderers
(sentinel/zizmor/heartbeat) handle them uniformly.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
                                  — single rule record (same shape as
                                    agent_config_patterns.Rule).
  * RULES                         — ordered tuple of every catalogued rule.
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)            — single finding (mirrors
                                    agent_config_patterns.Finding).
  * scan_text(text)               — run every rule, return findings sorted
                                    by (line, column, rule_id).

OWASP mapping: every DoS finding maps to ASI-08 "Resource Exhaustion /
Denial of Service" in the OWASP ASI catalogue. The mapping is fixed at
ASI-08 across all eight rules — the differentiator is the severity, not
the category.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/agent_config_patterns.Finding
    so heartbeat / sentinel detectors render DoS findings uniformly with
    the existing prompt-injection findings."""

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


def _re(pattern: str, *, flags: int = 0) -> re.Pattern:
    """Compile a pattern with MULTILINE+DOTALL by default. DoS shapes
    often span newlines (loop-body matches), so MULTILINE makes ``^`` /
    ``$`` line-anchored and DOTALL lets ``.`` cross newlines for the
    Popen-in-loop and open-in-loop cases. Individual patterns can pass
    extra flags via `flags=`."""
    return re.compile(pattern, re.MULTILINE | re.DOTALL | flags)


# ---- 1. Catastrophic-backtracking ReDoS shapes (bheeshma rules-linter) --


# Shape A — nested quantifier on a group that itself repeats: "(a+)+".
# The inner [+*] greedily matches; the outer [+*] then backtracks across
# every permutation when the tail doesn't match. Classic exponential
# blowup. Tighter than "(...)+" alone to avoid matching `(?P<x>a)+`.
_REDOS_NESTED_QUANT = _re(
    r"\([^)(]{0,80}?[+*]\s*\)\s*[+*]"
    # match: "(.+)+", "(\w*)*", "( [a-z]+ )+", "([a-z0-9_]+)+"
)


# Shape B — alternation with overlapping alternatives under +/*:
# "(a|a)+". The NFA explodes when input doesn't match the tail anchor
# because every position can pick either branch. The detector uses a
# backreference \1 to require the SAME token on both sides of `|`.
_REDOS_ALTERNATION_OVERLAP = _re(
    r"\(\s*([^)|]{1,40}?)\s*\|\s*\1\s*\)\s*[+*]"
    # match: "(a|a)+", "(\d|\d)*", "(abc|abc)+"
)


# Shape C — adjacent quantified atoms with no separator: "a*a*", "\w+\w+".
# Engine backtracks across both quantifiers on a non-match. The atom is
# any single regex token: a word char, an escape, or a character class.
_REDOS_ADJACENT_QUANT = _re(
    r"(?:\w|\\.|\[[^\]]{1,40}\])[+*](?:\w|\\.|\[[^\]]{1,40}\])[+*]"
    # match: "\w+\w+", "[a-z]*[A-Z]*", "a+a+", "\d+\d*"
)


_REDOS_ANY = _re(
    # Combined union of all three shapes — emit on any match.
    # The alternation tries A, then B, then C; the first to fire wins.
    _REDOS_NESTED_QUANT.pattern
    + r"|"
    + _REDOS_ALTERNATION_OVERLAP.pattern
    + r"|"
    + _REDOS_ADJACENT_QUANT.pattern
)


# ---- 2. Fork-bomb shapes (tocsin shell-scanner) -------------------------


# The canonical bash fork-bomb `:(){:|:&};:` — whitespace-tolerant.
# Every legitimate shell script avoids this shape entirely; FP-rate ~0.
_FORK_BOMB_CLASSIC = _re(
    r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"
)


# Renamed-function variant — same shape with a non-`:` function name.
# `\1` backreferences the captured name so it's the SAME name on every
# usage in the bomb (function definition + 3 invocations).
_FORK_BOMB_NAMED = _re(
    r"(\b[a-zA-Z_]\w{0,30})\s*\(\s*\)\s*\{\s*"
    r"\1\s*\|\s*\1\s*&\s*\}\s*;\s*\1"
)


# Python equivalent: `while True: os.fork()` — never legitimate as a
# top-level production pattern.
_FORK_BOMB_PYTHON = _re(
    r"\bwhile\s+(?:True|1)\s*:\s*(?:#[^\n]*\n)?\s*os\.fork\s*\(\s*\)"
)


_FORK_BOMB_ANY = _re(
    _FORK_BOMB_CLASSIC.pattern
    + r"|"
    + _FORK_BOMB_NAMED.pattern
    + r"|"
    + _FORK_BOMB_PYTHON.pattern
)


# ---- 3. XML billion-laughs (defusedxml tests/test_xmlrpc.py) ------------


# A billion-laughs payload declares an entity whose body references 2+
# OTHER entities. The static regex matches an `<!ENTITY name "...">`
# declaration whose value contains 2+ `&otherName;` references — the
# exponential-fan-out signature. A single-entity declaration (the benign
# `<!ENTITY copyright "© 2026">` shape) has no entity refs in its body
# and never matches.
#
# We require the entity body to contain 2+ entity references (`&xxx;`)
# AND the document to declare at least 2 entities (the `<!ENTITY ...>`
# count, enforced by the alternation below). A simple regex captures
# both via a non-greedy quantifier and a forward look that confirms a
# second `<!ENTITY` definition follows.
_XML_BILLION_LAUGHS = _re(
    # Match: <!ENTITY name "body-with-2+-refs"> with body containing 2 or
    # more `&otherEntity;` references. The `[^"]{0,2000}?` is bounded so
    # the regex remains linear on giant payloads.
    r"<!ENTITY\s+\w{1,40}\s+\""
    r"[^\"]{0,2000}?&\w{1,40};[^\"]{0,2000}?&\w{1,40};"
    r"[^\"]{0,2000}?\""
)


# ---- 4. Recursive YAML alias (defusedyaml + PyYAML #420) ----------------


# Common shape from defusedyaml: an anchor `&foo` is declared AND a merge
# reference `<<: *foo` appears later in the same document. PyYAML 1.x
# resolves the merge by expanding the anchor's subtree — if the subtree
# itself contains `*foo` (direct self-reference) or another anchor that
# back-references it, expansion is infinite.
#
# Detector shape: an anchor `&NAME` immediately followed (within 2000
# chars, same document) by `<<: *NAME` — the merge-into-self shape that
# defusedyaml's tests/test_recursion.yml uses as the golden malicious
# fixture. Backreference \1 ensures it's the SAME name.
_YAML_RECURSIVE_ALIAS = _re(
    r"&([A-Za-z_][\w-]{0,40})\b"
    r"[\s\S]{0,2000}?"
    r"<<:\s*\*\1\b"
)


# ---- 5. JSON-bomb behind gzip (GHSA-4j5g-8r4p-xq3w) ---------------------


# The decoded shape: gzip.decompress(...) → json.loads(...) within ~200
# chars. requests/httpx auto-decompress gzip then call `.json()`; the
# safe variants (orjson with depth limit / json_stream / explicit size
# guard) suppress externally — the rule scanner reads them out in its
# post-filter, not in this regex.
_JSON_BOMB_DECOMPRESS = _re(
    r"(?:gzip|zlib)\s*\.\s*decompress\s*\([^)]{0,200}\)"
    r"[\s\S]{0,200}?"
    r"\bjson\.loads?\s*\("
)


_JSON_BOMB_HTTPX_REQUESTS = _re(
    # requests / httpx auto-decompresses gzip; .json() is then called
    # without a depth limit. The cue is no `stream=True` (full-body
    # buffering) and no iter_content() guard.
    r"\b(?:requests|httpx)\s*\.\s*(?:get|post|put|patch|delete)\s*\("
    r"[^)]{0,400}\)\s*\.\s*json\s*\(\s*\)"
)


_JSON_BOMB_ANY = _re(
    _JSON_BOMB_DECOMPRESS.pattern
    + r"|"
    + _JSON_BOMB_HTTPX_REQUESTS.pattern
)


# ---- 6. Busy-spin loop with no upper bound (mcp-shield CPU watcher) -----


# `while True: pass` (or `while 1:`, `while not False:`) followed by a
# no-yield body — only `pass`, `continue`, or `time.sleep(0)` /
# `asyncio.sleep(0)`. Any non-zero sleep, any blocking syscall, any
# `break` / `return` / `raise` legitimises the loop.
_BUSY_SPIN_LOOP = _re(
    r"while\s+(?:True|1|not\s+False)\s*:\s*\n"
    r"(?:[ \t]*#[^\n]*\n)*"
    r"[ \t]+(?:pass|continue|"
    r"time\.sleep\s*\(\s*0(?:\.0+)?\s*\)|"
    r"asyncio\.sleep\s*\(\s*0(?:\.0+)?\s*\)|"
    r"await\s+asyncio\.sleep\s*\(\s*0(?:\.0+)?\s*\))\s*\n"
)


# ---- 7. Process-bomb: subprocess.Popen in loop, no wait (mcp-shield) ----


# `for`/`while` loop whose body contains a `subprocess.Popen(...)` /
# `os.spawn*(...)` / `multiprocessing.Process(...).start()` AND the
# next ~6 lines contain NO `.wait()` / `.communicate()` / `.poll()` /
# `.terminate()` / `.kill()` AND NO surrounding `with` context.
#
# Implementation: regex matches the loop-with-spawn shape; the
# negative-lookahead block excludes lines that wait. The bounded
# `{0,6}` line window is intentionally short — a real spawn-and-wait
# pattern keeps the wait close to the spawn for readability.
_PROCESS_BOMB = _re(
    # The `with ` / `await ` lookahead-blockers go BEFORE the bare-spawn
    # alternation so the inner alternation only catches naked, unwaited
    # spawns. The negative-lookahead block after the spawn looks 8
    # lines ahead for a wait-/communicate-/terminate-/poll-/kill-call.
    r"(?:for|while)\s+[^\n:]*:\s*\n"
    r"(?:[ \t]*(?:#[^\n]*)?\n){0,3}"
    r"[ \t]+(?!with\s+)"
    r"(?:[A-Za-z_][\w.]*\s*=\s*)?"
    r"(?:subprocess\.Popen|os\.spawn\w+|multiprocessing\.Process\s*\([^)]*\)\s*\.\s*start)\s*\("
    r"(?![\s\S]{0,400}?\.(?:wait|communicate|poll|terminate|kill)\s*\()"
)


# ---- 8. fd-leak: open() in loop, no close, no `with` (mcp-shield) -------


# `for`/`while` loop whose body calls `open(...)` (or `io.open`,
# `pathlib.Path.open`, `os.open`, `socket.socket`) where the result is
# NEITHER captured by a `with`/`async with` context NOR followed by a
# `.close()` call within ~8 lines.
#
# Implementation: regex matches the loop with a naked `open(...)`
# call (not preceded by `with ` / `async with `), and the
# negative-lookahead block scans the next ~400 chars for a `.close()`
# or `with` / `async with` introducer that would legitimise it.
_FD_LEAK_OPEN_IN_LOOP = _re(
    r"(?:for|while)\s+[^\n:]*:\s*\n"
    r"(?:[ \t]*(?:#[^\n]*)?\n){0,3}"
    r"[ \t]+(?!with\s+|async\s+with\s+)"
    r"(?:[A-Za-z_][\w.]*\s*=\s*)?"
    r"(?:io\.open|pathlib\.Path\s*\([^)]*\)\s*\.\s*open|"
    r"[A-Za-z_][\w.]*\.open|open|os\.open|socket\.socket)\s*\("
    r"(?![\s\S]{0,400}?\.close\s*\()"
)


# ---- RULES catalogue ---------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="regex-catastrophic-backtrack",
        name="Catastrophic-backtracking regex (ReDoS)",
        severity="HIGH",
        description=(
            "Regex literal contains a catastrophic-backtracking shape — "
            "nested quantifier '(a+)+', overlapping-alternation '(a|a)+', "
            "or adjacent-quantifier '\\w+\\w+'. Crafted input pins a CPU "
            "core at 100% for seconds-to-hours."
        ),
        pattern=_REDOS_ANY,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="fork-bomb-shell",
        name="Fork-bomb shape (shell or Python)",
        severity="CRITICAL",
        description=(
            "Body contains a canonical fork-bomb shape — ':(){:|:&};:' "
            "(any whitespace), a renamed-function variant of the same "
            "self-recursive pipeline, or 'while True: os.fork()' in "
            "Python. Exhausts the pid table in milliseconds."
        ),
        pattern=_FORK_BOMB_ANY,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="xml-billion-laughs",
        name="Billion-laughs XML entity-expansion bomb",
        severity="CRITICAL",
        description=(
            "XML DOCTYPE declares an `<!ENTITY ...>` whose body contains "
            "2+ references to OTHER entities — exponential fan-out "
            "expansion at parse time. Standard 1 KB → multi-GB blow-up."
        ),
        pattern=_XML_BILLION_LAUGHS,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="yaml-recursive-alias",
        name="Recursive YAML alias (anchor + self-merge)",
        severity="HIGH",
        description=(
            "YAML declares an anchor `&foo` and later merges its own "
            "subtree via `<<: *foo` — infinite-tree expansion at load "
            "time. PyYAML 1.x eats all RAM (upstream issue #420)."
        ),
        pattern=_YAML_RECURSIVE_ALIAS,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="json-bomb-deep-nested-gzipped",
        name="JSON-bomb after gzip decompression",
        severity="HIGH",
        description=(
            "Source decompresses gzip/zlib content and feeds the result "
            "to json.loads() within a few lines (or calls "
            "requests/httpx + .json() without stream=True / size guard) — "
            "an attacker-supplied 1 KB gzipped JSON can expand to GBs."
        ),
        pattern=_JSON_BOMB_ANY,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="busy-spin-loop-no-upper-bound",
        name="Busy-spin loop with no upper bound",
        severity="MEDIUM",
        description=(
            "`while True:` (or `while 1:`) whose body is only `pass` / "
            "`continue` / zero-sleep — burns a full CPU core forever. "
            "On shared CI runners starves co-tenants; on workflows wastes "
            "runtime minutes for nothing."
        ),
        pattern=_BUSY_SPIN_LOOP,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="subprocess-popen-in-loop-no-wait",
        name="subprocess.Popen in loop without wait/terminate",
        severity="CRITICAL",
        description=(
            "Loop body spawns a subprocess (Popen / os.spawn* / "
            "multiprocessing.Process.start) without `.wait()`, "
            "`.communicate()`, `.poll()`, `.terminate()`, or `.kill()` "
            "in the next ~8 lines, and without a `with` context manager "
            "— canonical process-bomb shape."
        ),
        pattern=_PROCESS_BOMB,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="fd-leak-open-in-loop",
        name="File-descriptor leak: open() in loop without close",
        severity="HIGH",
        description=(
            "Loop body calls `open(...)` (or `io.open`, `Path.open`, "
            "`os.open`, `socket.socket`) without a surrounding `with` "
            "context and without a `.close()` in the next ~8 lines — "
            "Linux default soft limit is 1024 fds, exhausts in one "
            "iteration loop."
        ),
        pattern=_FD_LEAK_OPEN_IN_LOOP,
        owasp_asi="ASI-08",
    ),
)


# ---- scan_text ---------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).

    Identical helper to scripts/lib/agent_config_patterns._line_col — kept
    local so this module can be imported independently in a PEP 723
    script without dragging in the larger agent_config_patterns module."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    Findings are deduped by (rule_id, line, col) — a single line that
    triggers two rules emits two findings, but the same rule firing
    twice at the same offset emits one. Matched text is truncated to
    200 chars + ellipsis to keep findings small for downstream
    renderers.

    The function never raises — every regex is pre-compiled and applied
    to a plain string. Caller-side input validation (file kind, encoding,
    suppression comments) is performed by the dispatcher that wraps
    scan_text, not by this module.
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
