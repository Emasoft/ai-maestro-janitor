#!/usr/bin/env python3
"""Pre-commit stage 3 gate: allow ONE tracked ubs partial scan, fail closed on everything else (TRDD-H7884ERZ).

WHY THIS EXISTS: ubs exits 2 with status "partial" when a detector gives up on a file ("detector
sql_injection: SQLFlowLimit: ... analysis is incomplete"). The hook used to block every such commit.
OWNER RULING 2026-11-19: allow exit 2 only when the unfinished part matches ONE tracked entry
(git-hooks/ubs-partial-allow.tsv: path, detector, anchor text, reason) and the staged diff changes no
line at or after the anchor line. The anchor marks the limit site, so code below it is the code the
detector did not analyse; editing only above it keeps the unscanned region byte-identical.

FAIL CLOSED: every error, missing entry, other detector, HEAD blob not partial, ambiguous or missing
anchor, unparseable diff, or touched line at or after the anchor makes the gate return 1 (block).
There is no fallback and no skip. Pure decision logic lives in decide(); main() only gathers inputs.

Usage (from the repo top level): ubs_partial_gate.py --allow ALLOW_TSV --report UBS_STAGED_REPORT_JSON
Exit 0: every partial staged .py file is allowed. Exit 1: block. Stdlib only (the hook runs plain python3).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

UBS_TIMEOUT_S = 600
GIT_TIMEOUT_S = 60
DETECTOR_RE = re.compile(r"detector (\w+):")
NAME_RE = re.compile(r"\w+")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", re.MULTILINE)


class GateError(Exception):
    """Anything the gate cannot prove safe; the caller turns it into a block."""


@dataclass(frozen=True)
class Entry:
    """One allow-file line: the file, the one detector allowed to stay unfinished, the limit-site text, why."""

    path: str
    detector: str
    anchor: str
    reason: str


@dataclass(frozen=True)
class Decision:
    """Outcome for one staged file; message names the file and the detector."""

    ok: bool
    message: str


def parse_allow(text: str) -> dict[str, Entry]:
    """Parse the tab-separated allow file; any malformed line raises GateError (never skipped)."""
    entries: dict[str, Entry] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 4 or not all(f.strip() for f in fields):
            raise GateError(f"allow file line {number}: expected 4 non-empty tab-separated fields (path, detector, anchor, reason)")
        path, detector, anchor, reason = (f.strip() for f in fields)
        if not NAME_RE.fullmatch(detector):
            raise GateError(f"allow file line {number}: detector name {detector!r} is not a plain identifier")
        if path in entries:
            raise GateError(f"allow file line {number}: duplicate entry for {path}")
        entries[path] = Entry(path, detector, anchor, reason)
    return entries


def parse_report(raw: str) -> dict[str, Any]:
    """Parse a ubs JSON report; ubs prints a banner before the JSON, so parse from the first brace."""
    start = raw.find("{")
    if start < 0:
        raise GateError("ubs report holds no JSON object")
    try:
        data = json.loads(raw[start:])
    except json.JSONDecodeError as exc:
        raise GateError(f"ubs report is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise GateError("ubs report is not a JSON object")
    return data


def classify_report(report: dict[str, Any]) -> frozenset[str]:
    """Return the detectors a ubs report says did not finish: empty for a clean scan, GateError for anything else."""
    modules = report.get("failed_modules")
    status = report.get("status")
    if not isinstance(modules, list):
        raise GateError("ubs report has no failed_modules list")
    if status == "ok" and not modules:
        return frozenset()
    if status != "partial" or not modules:
        raise GateError(f"ubs report status {status!r} is not a recognised clean or partial scan")
    detectors: set[str] = set()
    for module in modules:
        if not isinstance(module, dict) or module.get("language") != "python" or module.get("status") != "partial":
            raise GateError("ubs report has a failed module that is not a partial python scan")
        named = DETECTOR_RE.findall(str(module.get("message", "")))
        if not named:
            raise GateError("ubs partial scan names no detector")
        detectors.update(named)
    return frozenset(detectors)


def anchor_line(head_text: str, anchor: str) -> int:
    """1-based line of the single HEAD line containing the anchor; zero or several matches raise GateError."""
    found = [number for number, line in enumerate(head_text.splitlines(), 1) if anchor in line]
    if len(found) != 1:
        raise GateError(f"anchor text matches {len(found)} lines in the HEAD blob, expected exactly 1")
    return found[0]


def diff_touches_at_or_after(diff_text: str, line: int) -> bool:
    """True when a -U0 diff changes any HEAD line numbered >= line; a diff with no parsable hunk raises GateError."""
    if not diff_text.strip():
        return False
    hunks = HUNK_RE.findall(diff_text)
    if not hunks:
        raise GateError("the staged diff has no parsable hunk (mode change or binary), cannot prove it stays above the anchor")
    for start_s, count_s in hunks:
        start = int(start_s)
        count = 1 if count_s == "" else int(count_s)
        # count 0 is a pure insertion AFTER old line `start`; it is below the anchor only when start >= line.
        last_old = start if count == 0 else start + count - 1
        if last_old >= line:
            return True
    return False


def decide(path: str, entry: Entry | None, staged_report: dict[str, Any], head_report: dict[str, Any] | None, head_text: str | None, diff_text: str) -> Decision:
    """Decide one staged file whose scan was partial. Pure: no I/O, so it is tested with fixture reports and diffs."""
    try:
        staged = classify_report(staged_report)
        if not staged:
            return Decision(True, f"{path}: fully scanned by ubs")
        names = ", ".join(sorted(staged))
        if entry is None:
            return Decision(False, f"{path}: ubs did not scan detector(s) {names}, and the allow file has no entry for this file")
        if staged != frozenset({entry.detector}):
            return Decision(False, f"{path}: ubs did not scan detector(s) {names}, but the allow entry covers only {entry.detector}")
        if head_report is None or head_text is None:
            return Decision(False, f"{path}: detector {entry.detector} is unscanned, and no partial HEAD scan exists to show it is pre-existing")
        if classify_report(head_report) != frozenset({entry.detector}):
            return Decision(False, f"{path}: the HEAD blob is not partial with exactly detector {entry.detector}")
        line = anchor_line(head_text, entry.anchor)
        if diff_touches_at_or_after(diff_text, line):
            return Decision(False, f"{path}: detector {entry.detector} is unscanned at and after line {line} (HEAD numbering), and the staged diff changes a line there")
    except GateError as exc:
        return Decision(False, f"{path}: {exc}")
    return Decision(True, f"{path}: unscanned by detector {entry.detector} at and after line {line} (anchor), allowed by the tracked entry: {entry.reason}")


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    git = shutil.which("git")
    if git is None:
        raise GateError("git not found on PATH")
    try:
        return subprocess.run([git, *args], capture_output=True, check=False, timeout=GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise GateError(f"git {args[0]} timed out") from exc


def run_ubs(tmp: Path, name: str, rel: str, content: bytes) -> tuple[int, dict[str, Any] | None]:
    """Scan one blob at its repo-relative path under tmp/name; returns (exit code, report or None when exit is 0 or 1)."""
    ubs = shutil.which("ubs")
    if ubs is None:
        raise GateError("ubs not found on PATH")
    root = tmp / name
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    report_path = tmp / f"{name}.json"
    try:
        proc = subprocess.run([ubs, "--format=json", f"--report-json={report_path}", str(root)], capture_output=True, check=False, timeout=UBS_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise GateError(f"ubs timed out on {rel}") from exc
    if proc.returncode in (0, 1):
        return proc.returncode, None
    if proc.returncode != 2:
        raise GateError(f"ubs exit {proc.returncode} on {rel} is not a scan result")
    if not report_path.is_file():
        raise GateError(f"ubs exit 2 on {rel} wrote no report")
    return 2, parse_report(report_path.read_text(encoding="utf-8", errors="replace"))


def staged_python_files() -> list[str]:
    """Repo-relative staged added/copied/modified .py files (renames split into add + delete)."""
    proc = _git("diff", "--cached", "--no-renames", "--name-only", "--diff-filter=ACM", "-z")
    if proc.returncode != 0:
        raise GateError("git diff --cached --name-only failed")
    names = [n.decode("utf-8", errors="replace") for n in proc.stdout.split(b"\0") if n]
    return [n for n in names if n.endswith(".py")]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--allow", required=True, help="tracked allow file (tab separated: path, detector, anchor, reason)")
    parser.add_argument("--report", required=True, help="the JSON report written by ubs --staged")
    args = parser.parse_args(argv)
    blocked = False
    partial_seen = 0
    try:
        entries = parse_allow(Path(args.allow).read_text(encoding="utf-8"))
        overall = parse_report(Path(args.report).read_text(encoding="utf-8", errors="replace"))
        if not classify_report(overall):
            raise GateError("ubs exited 2 but its staged report is not a partial scan")
        with tempfile.TemporaryDirectory(prefix="ubs-partial-") as tmp_name:
            tmp = Path(tmp_name)
            for index, rel in enumerate(staged_python_files()):
                staged_blob = _git("show", f":{rel}")
                if staged_blob.returncode != 0:
                    raise GateError(f"cannot read the staged blob of {rel}")
                rc, staged_report = run_ubs(tmp, f"staged-{index}", rel, staged_blob.stdout)
                if rc != 2 or staged_report is None:
                    continue
                partial_seen += 1
                entry = entries.get(rel)
                head_report: dict[str, Any] | None = None
                head_text: str | None = None
                if entry is not None:
                    head_blob = _git("cat-file", "-p", f"HEAD:{rel}")
                    if head_blob.returncode == 0:
                        head_text = head_blob.stdout.decode("utf-8", errors="replace")
                        head_rc, head_report = run_ubs(tmp, f"head-{index}", rel, head_blob.stdout)
                        if head_rc != 2:
                            head_report = None
                diff = _git("diff", "--cached", "--no-renames", "-U0", "--", rel)
                if diff.returncode != 0:
                    raise GateError(f"cannot diff the staged change of {rel}")
                decision = decide(rel, entry, staged_report, head_report, head_text, diff.stdout.decode("utf-8", errors="replace"))
                print(f"pre-commit: ubs partial scan — {decision.message}")
                blocked = blocked or not decision.ok
        if partial_seen == 0:
            raise GateError("ubs exited 2 but no staged .py file reproduced a partial scan")
    except (GateError, OSError) as exc:
        print(f"pre-commit: ubs partial-scan gate — {exc}")
        return 1
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
