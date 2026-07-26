#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""wikimem_syntax_lint — the wikimem page linter, as a thin shell-out to `memgrep lint`.

WHY this is a SHELL-OUT and no longer an implementation (plan Phase 1b): this file used to
carry its own port of memgrep's parser rules, "ported 1:1 from memory.rs". Two copies of one
grammar cannot stay in step — and they did not: the Python side grew `atom-bad-bracket`,
`atom-no-keywords`, `atom-dup-id`, the date checks and the lesson-metadata checks that Rust
never had, while Rust grew the severity model, the link law and the cross-scope rule that
Python never had. So the heartbeat detector and the write gate enforced DIFFERENT rule sets,
and which defects you saw depended on which tool happened to run. Every check now lives in
`scripts/memgrep/src/memory.rs::lint_paths` — the same code the write gate calls — and this
file only chooses the default roots, runs it, and parses its output.

The lint is READ-ONLY: it surfaces, an agent fixes (RULE 0 / separation of powers).

Exit status mirrors `memgrep lint`: 0 when nothing is at or above the gating severity (default
ERROR), 1 when something is. A MISSING binary exits 2 — never 0: a gate that passes because the
checker could not run is worse than no gate at all.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS / "lib"))

import memory_scopes  # noqa: E402

# `SEVERITY path:line — message` — the output contract memgrep's lint prints (WM-LINT-06: the
# severity LEADS the line so `| grep '^ERROR'` is exact). The em-dash separator is memgrep's.
_LINE_RE = re.compile(r"^(?P<sev>ERROR|WARN|INFO)\s+(?P<path>.+?):(?P<line>\d+)\s+—\s+(?P<msg>.*)$")

SEVERITIES = ("ERROR", "WARN", "INFO")


@dataclass(frozen=True)
class Finding:
    sev: str
    path: str
    line: int
    msg: str


class MemgrepMissing(RuntimeError):
    """No `memgrep` binary could be resolved, so nothing was checked."""


def find_memgrep() -> str | None:
    """Resolve the memgrep binary: `MEMGREP_BIN` → PATH → the cargo bin dir.

    `MEMGREP_BIN` is first because a test (or a bisect) MUST be able to pin the binary under
    test; without it the check silently scores whatever `cargo install` last left on PATH.
    """
    override = os.environ.get("MEMGREP_BIN")
    if override and Path(override).is_file():
        return override
    found = shutil.which("memgrep")
    if found:
        return found
    cargo_bin = Path(os.path.expanduser("~")) / ".cargo" / "bin" / "memgrep"
    return str(cargo_bin) if cargo_bin.is_file() else None


def default_roots() -> list[Path]:
    """The three memory scopes recall reads — LOCAL, PROJECT, USER — in that order.

    Passed to ONE memgrep invocation rather than three, because atom-id uniqueness is
    corpus-wide: a collision between a LOCAL and a USER page is invisible to a per-scope run.
    """
    return [root for _label, root in memory_scopes.resolve_scope_dirs()]


def parse_findings(stdout: str) -> list[Finding]:
    """Parse `memgrep lint` stdout into findings, ignoring anything that is not a finding line."""
    out: list[Finding] = []
    for raw in stdout.splitlines():
        m = _LINE_RE.match(raw)
        if m:
            out.append(Finding(m["sev"], m["path"], int(m["line"]), m["msg"]))
    return out


def run_lint(paths: list[Path] | None = None, *, extra_args: list[str] | None = None) -> tuple[int, str, list[Finding]]:
    """Run `memgrep lint` over `paths` (default: the three scopes) → (exit code, stdout, findings).

    Raises `MemgrepMissing` when the binary cannot be resolved — callers decide whether that is
    fatal (the CLI) or fail-open (the heartbeat detector).
    """
    binary = find_memgrep()
    if binary is None:
        raise MemgrepMissing("memgrep not found (set MEMGREP_BIN, or `cargo install --path scripts/memgrep`)")
    targets = [str(p) for p in (paths if paths is not None else default_roots())]
    cmd = [binary, "lint", *(extra_args or []), *targets]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode, proc.stdout, parse_findings(proc.stdout)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Lint wikimem pages (thin wrapper around `memgrep lint` — the one linter).",
    )
    ap.add_argument("paths", nargs="*", help="Pages or dirs to lint (default: the 3 memory scopes).")
    ap.add_argument(
        "--min-severity",
        choices=[s.lower() for s in SEVERITIES],
        help="Exit non-zero only at or above this severity (memgrep's default: error).",
    )
    args = ap.parse_args()

    extra = ["--min-severity", args.min_severity] if args.min_severity else []
    try:
        code, stdout, findings = run_lint([Path(p) for p in args.paths] or None, extra_args=extra)
    except MemgrepMissing as e:
        print(f"wikimem-lint: {e}", file=sys.stderr)
        return 2
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"wikimem-lint: memgrep failed to run ({e})", file=sys.stderr)
        return 2

    print(stdout, end="")
    counts = {s: sum(1 for f in findings if f.sev == s) for s in SEVERITIES}
    print(
        f"wikimem-lint: {counts['ERROR']} ERROR, {counts['WARN']} WARN, {counts['INFO']} INFO",
        file=sys.stderr,
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
