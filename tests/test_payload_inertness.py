"""Regression guard: the repo's attack corpus and detector signatures are DATA,
never a runnable payload.

This repo is a security scanner, so it necessarily carries the two things a
scanner needs and an attacker wants: ~223 `scripts/lib/*_patterns.py` modules
whose regex source IS the needle, and `tests/agent_context_bench/*.jsonl`, a
corpus of 218 realistic poisoned CLAUDE.md / skill / manifest bodies used to
measure detector recall.

Neither may ever become executable. The sibling guard
`test_secret_fixture_hygiene.py` enforces the same discipline for the LEAK class
(no credential literal at rest); this one enforces the EXECUTION class, because
those invariants held only by author discipline and nothing detected a
regression.

Four invariants, each independently sufficient to be worth failing a publish:

1. **No data file is executable.** A corpus row is inert prose; an executable
   bit turns the file into something a shell will try to run.
2. **No data file carries a shebang.** `#!` on line 1 is the other half of the
   same vector — it is what makes an executable file *runnable as a program*.
3. **No pattern module contains a dynamic-exec sink.** The modules are regex
   source. `eval` / `exec` / `os.system` / `pickle.loads` / `shell=True` in one
   would turn signature data into code. Verified by AST, which — unlike grep —
   cannot be fooled by the many *comments and regex literals* in these files
   that legitimately mention those very words.
4. **The corpus is parseable JSON, end to end.** This is the positive proof of
   the design recorded in `tests/agent_context_bench/README.md` ("Why the corpus
   is JSONL, not files on disk"): holding the samples as JSON strings means
   nothing on disk is shaped like an agent-context file, so neither the
   janitor's own detector nor a human reader ingests them as instructions. A row
   that stopped parsing would mean a raw payload had leaked out of its quoting.

NOTE for anyone extending the corpus: these tests deliberately assert nothing
about the *content* of a sample. The corpus is a measurement instrument scored
against `tests/agent_context_bench/baseline.json`; weakening, truncating or
defanging the text a detector reads would destroy the measurement rather than
devitalize anything. Inertness is enforced by the file's SHAPE — not
executable, not a program, and parsed as data — never by editing the samples.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Suffixes that denote pure DATA. A file with one of these is never meant to be
# run, so it must be neither executable nor shebang-bearing.
_DATA_SUFFIXES = (".jsonl", ".json", ".tsv", ".csv", ".txt", ".md", ".yml", ".yaml")

# SAFETY NOTE for readers and for grep-based scanners: every dangerous name
# below (`eval`, `exec`, `pickle.loads`, `os.system`, …) appears ONLY as an
# inert string literal in this catalog of things to SEARCH FOR. This module
# contains no call to any of them — a claim `test_this_guard_is_itself_inert`
# proves by AST rather than asserting in prose. A substring scanner flagging
# this file is demonstrating the very false-positive problem that makes the
# AST approach necessary.
#
# Bare-name calls that execute attacker-supplied text.
_SINK_NAMES = frozenset({"eval", "exec", "compile", "__import__"})

# Dotted calls that execute or deserialize-into-objects. Matched on the last two
# components, so `os.system` matches whether imported as `os` or aliased.
_SINK_ATTRS = frozenset({
    ("os", "system"),
    ("os", "popen"),
    ("os", "execv"),
    ("os", "execve"),
    ("os", "execvp"),
    ("os", "spawnv"),
    ("pickle", "loads"),
    ("pickle", "load"),
    ("marshal", "loads"),
})

_CORPUS_DIR = _REPO_ROOT / "tests" / "agent_context_bench"
_PATTERNS_DIR = _REPO_ROOT / "scripts" / "lib"


def _tracked() -> list[tuple[str, str]]:
    """Every tracked file as `(mode, relative_path)` straight from the index.

    Reading the mode from `git ls-files -s` rather than the filesystem is
    deliberate: the index mode is what actually ships to a cloner, and it is
    what a `core.fileMode=false` checkout (or a Windows clone) would otherwise
    hide.
    """
    out = subprocess.run(
        ["git", "ls-files", "-s"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        meta, _, rel = line.partition("\t")
        parts = meta.split()
        if not rel or not parts:
            continue
        rows.append((parts[0], rel))
    return rows


def _dotted(node: ast.AST) -> str:
    """Flatten an attribute chain (`a.b.c`) back to its dotted source text."""
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _exec_sinks(path: Path) -> list[str]:
    """Every real dynamic-exec call site in `path`, as `file:line: detail`.

    AST-based on purpose. These modules are full of comments and regex literals
    containing the strings `eval(`, `exec(`, `os.system(` — a grep-based guard
    would report hundreds of false positives and be switched off within a week.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    rel = path.relative_to(_REPO_ROOT)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in _SINK_NAMES:
            hits.append(f"{rel}:{node.lineno}: {fn.id}(...)")
            continue
        if not isinstance(fn, ast.Attribute):
            continue
        name = _dotted(fn)
        if tuple(name.split(".")[-2:]) in _SINK_ATTRS:
            hits.append(f"{rel}:{node.lineno}: {name}(...)")
            continue
        if name.startswith("subprocess.") and any(
            kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
            for kw in node.keywords
        ):
            hits.append(f"{rel}:{node.lineno}: {name}(..., shell=True)")
            continue
        # `yaml.load` is safe ONLY with an explicit Loader; the bare default
        # constructs arbitrary Python objects. Assert the safety CONDITION
        # rather than exempting the one legitimate call site, so a future
        # unsafe call in the same file is still caught.
        if tuple(name.split(".")[-2:]) == ("yaml", "load") and not any(
            kw.arg == "Loader" for kw in node.keywords
        ):
            hits.append(f"{rel}:{node.lineno}: {name}(...) without Loader=")
    return hits


def test_no_tracked_data_file_is_executable() -> None:
    """No corpus/fixture/data file carries the executable bit in the git index."""
    offenders = [
        f"{rel} (mode {mode})"
        for mode, rel in _tracked()
        if rel.endswith(_DATA_SUFFIXES) and mode == "100755"
    ]
    assert not offenders, (
        "Data file(s) marked executable — a corpus row is inert prose and must "
        "never be runnable:\n  " + "\n  ".join(offenders)
    )


def test_no_tracked_data_file_has_a_shebang() -> None:
    """No tracked data file begins with `#!` (which would make it a program)."""
    offenders: list[str] = []
    for _mode, rel in _tracked():
        if not rel.endswith((".jsonl", ".json", ".tsv", ".csv")):
            continue
        path = _REPO_ROOT / rel
        try:
            head = path.read_bytes()[:2]
        except OSError:
            continue
        if head == b"#!":
            offenders.append(rel)
    assert not offenders, (
        "Data file(s) start with a shebang — that is what makes a file runnable "
        "as a program:\n  " + "\n  ".join(offenders)
    )


def test_pattern_modules_contain_no_dynamic_exec_sink() -> None:
    """The ~223 `*_patterns.py` detector-signature modules execute nothing."""
    modules = sorted(_PATTERNS_DIR.glob("*_patterns.py"))
    # Guard against a silently empty scan (a moved directory would otherwise
    # make this test pass forever while checking nothing).
    assert len(modules) >= 100, f"only {len(modules)} pattern modules found — scan drifted"
    offenders: list[str] = []
    for mod in modules:
        offenders.extend(_exec_sinks(mod))
    assert not offenders, (
        "Dynamic-exec sink(s) in detector-signature modules — these files are "
        "regex DATA and must never execute:\n  " + "\n  ".join(offenders)
    )


def test_this_guard_is_itself_inert() -> None:
    """This module names every exec sink, and calls none of them.

    A guard that catalogs `eval` / `os.system` / `pickle.loads` as strings is
    indistinguishable, to a substring scanner, from one that calls them. Proving
    it by AST keeps the file honest and stops anyone from "fixing" a scanner
    false positive by weakening the catalog.
    """
    assert _exec_sinks(Path(__file__).resolve()) == []


def test_attack_corpus_is_parseable_json_data() -> None:
    """Every corpus row parses as JSON — the positive proof the samples are data.

    A payload that escaped its JSON quoting would both break this parse and put
    raw attack text on disk in an agent-readable shape.
    """
    shards = sorted(_CORPUS_DIR.glob("*.jsonl"))
    assert shards, f"no corpus shards found under {_CORPUS_DIR}"
    total = 0
    for shard in shards:
        for lineno, line in enumerate(shard.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:  # pragma: no cover - failure path
                raise AssertionError(
                    f"{shard.relative_to(_REPO_ROOT)}:{lineno} is not valid JSON "
                    f"({exc.msg}) — a raw payload may have escaped its quoting"
                ) from exc
            total += 1
    assert total >= 200, f"corpus parsed only {total} rows — shards drifted"
