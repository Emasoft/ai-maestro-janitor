#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""report-to-trdd-drift — nudge when a DECISION report has no TRDD.

Enforces the "reports are evidence; decisions become TRDDs" rule
(`~/.claude/rules/trdd-design-tasks.md`). A report under `reports/` is gitignored
and ephemeral; a DECISION that lives only in a report is invisible to the next
session (this is exactly how a recommended STACK in a consolidated audit report
got re-derived from scratch). This detector scans `reports/` for decision/synthesis
-class reports that NO TRDD references and reminds the agent to convert each into
a TRDD (new, or by extending an existing one's STATE block).

WHY a heartbeat detector and NOT a Write/Stop hook: reports are frequently written
by SUBAGENTS, whose tool calls a main-session PostToolUse/Stop hook does not
reliably observe; and a report is born ON DISK regardless of who wrote it. Scanning
the folder catches every report. It is a REMINDER (not a hard block) because not
every report is a decision — a Stop-block would false-positive on data-only reports.
Per-report-set tick-bucket dedupe keeps it to once per interval until converted.

Silent when the project has no `design/tasks/` (it doesn't use TRDDs) or no
unconverted decision report. Project-scoped; never touches user/global scope.
"""

from __future__ import annotations

import hashlib
import os
import re
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402
import trdd_common  # noqa: E402

# Filenames that signal a DECISION / synthesis worth a TRDD (vs raw data dumps,
# lint captures, screenshots — those legitimately stay as evidence-only reports).
_DECISION_RE = re.compile(
    r"(consolidat|synthes|verdict|recommendation|proposal|decision|roadmap|[-_]plan)",
    re.IGNORECASE,
)
# The janitor-memory-subconscious-agent writes a report for EVERY editorial pass
# under this exact dir — including ABSTAIN / no-op passes (nothing due, no qualifying
# candidate, 0 mutations). Those reports carry no decision to convert, yet their
# filenames trip `_DECISION_RE` (e.g. "…-consolidat-e-abstain…"), so they were nagged
# every cadence and buried the real signal (issue #63). We scope the no-op skip to
# THIS dir only, then key off the curator's own outcome marker in the body — a genuine
# decision report (one that actually merged/split and recommends follow-up) lacks that
# marker and is STILL flagged.
_MEMORY_CURATOR_DIR = "memory-subconscious-agent"
# MEASURED CORRECTION 2026-07-29. The previous pattern matched ONLY an inline
# `**Outcome:** ABSTAINED …` label, and its comment claimed that was "verified across
# every real abstain/nothing-due report". It was not: across the 51 curator reports on
# disk, **zero** carry that spelling, so this exclusion had never once fired since issue
# #63 shipped. Every abstain was nagged forever and the list grew without bound — the
# exact false positive the exclusion was written to end.
#
# What the curator ACTUALLY writes is a `## Outcome` SECTION HEADING with the verb on the
# next non-empty line (`ABSTAINED — …`, `NOTHING DUE — …`, or `REPAIRED`/`SPLIT`/
# `ATOMIZED` for a real pass), and on some passes only an H1 title carrying the word.
#
# All three anchored forms are accepted below. Anchoring is the whole safety argument and
# is preserved from the original: a heading or a labelled line cannot be a passing
# *mention* of an abstained sub-candidate buried in a decision report's prose, so a real
# merge/split report is still flagged. Verified on the full 51-report corpus: 7 excluded,
# 44 kept, and ZERO reports whose outcome verb is a mutation were silenced.
#
# Lesson, and it is why this comment is long: the dead guard was invisible precisely
# because it FAILED OPEN — an exclusion that never matches just means more nagging, which
# reads as a noisy detector rather than a broken one. Assert the producer's format against
# real artifacts, never against the format you expect it to have.
_MEMORY_NOOP_RE = re.compile(
    # 1. inline label: `**Outcome:** ABSTAINED …`  (the original form; kept for tolerance)
    r"(?:^[\s\-\*>|]*\*\*outcome:\*\*[^\n]*?\b(?:abstain(?:ed)?|nothing\s+due)\b"
    # 2. section heading `## Outcome`, verb on the next non-empty line (the REAL form)
    r"|^#{1,4}[ \t]*outcome[ \t]*$\s*\n\s*[\s\-\*>|]*(?:abstain(?:ed)?|nothing\s+due)\b"
    # 3. H1 title carrying the word: `# CONSOLIDATE pass — LOCAL scope — abstained`
    r"|^#[ \t]+[^\n]*\b(?:abstain(?:ed)?|nothing\s+due)\b[^\n]*$)",
    re.IGNORECASE | re.MULTILINE,
)
_NOOP_SCAN_BYTES = 4096  # the outcome marker is always in the report's opening lines
_FRESH_GRACE_S = 90  # skip reports written in the last 90s (may be mid-write)
_MAX_LISTED = 6      # cap how many unconverted reports we name in one line


def _session_key() -> str:
    """Session-scoped dedupe key (mirrors trdd-reminder: no PPID — it rotates)."""
    sid = os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        return sid
    host = socket.gethostname().split(".")[0]
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    return hashlib.sha1(f"{host}@{today}".encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def _contained(child: Path, root: Path) -> bool:
    """True iff `child` resolves inside `root` (refuse to scan escapes)."""
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _is_memory_noop_report(rep: Path, reports_dir: Path) -> bool:
    """True iff `rep` is a janitor-memory-subconscious-agent ABSTAIN / no-op report.

    Scoped to `reports/memory-subconscious-agent/` so it can never silence a decision
    report living elsewhere; then keyed off the curator's own `**Outcome:**
    ABSTAINED|NOTHING DUE` opening marker (issue #63). A pass that actually mutated the
    corpus and recommends follow-up lacks that marker → still flagged for conversion.
    """
    if (reports_dir / _MEMORY_CURATOR_DIR) not in rep.parents:
        return False
    try:
        head = rep.read_text(encoding="utf-8", errors="replace")[:_NOOP_SCAN_BYTES]
    except OSError:
        return False
    return _MEMORY_NOOP_RE.search(head) is not None


def _trdd_corpus(trdd_paths: list[Path]) -> str:
    """Concatenate all TRDD bodies so a one-shot substring test answers
    'is this report referenced by any TRDD?' (TRDDs cite the report path).

    Takes the already-resolved paths rather than a directory: the board spans BOTH design
    scopes, and a report converted into a LOCAL TRDD is just as converted as one converted
    into a PROJECT TRDD. Reading only the project dir would leave this detector nagging
    forever about a decision the user already captured locally — the exact false positive
    that teaches people to ignore the nag.
    """
    parts: list[str] = []
    for p in trdd_paths:
        try:
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


def main() -> int:
    state.init_state()
    # Context gate (TRDD-db169d9e R1): the "decisions become TRDDs" rule is an
    # ai-maestro/Emasoft framework convention, and this is the one TRDD detector
    # that triggers on a GENERIC artifact (reports/) — so without this gate it
    # would nag in vanilla projects that have a reports/ dir but no TRDDs. Stay
    # silent outside ai-maestro. (Override with JANITOR_FORCE_AI_MAESTRO=1.)
    if not state.project_is_ai_maestro():
        return 0
    interval = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_REPORT_TO_TRDD_INTERVAL"), 21600
    )

    root = state.project_root()
    reports_dir = root / "reports"

    # Gate: only projects that USE TRDDs (in EITHER design scope) and HAVE a reports/ tree.
    # `trdd_common` owns the board resolution and the containment check that used to be a
    # private copy here; `_contained` still guards reports/, which is ours alone.
    trdds = trdd_common.trdd_files("tasks", str(root))
    if not trdds:
        return 0
    if not (reports_dir.is_dir() and _contained(reports_dir, root)):
        return 0

    corpus = _trdd_corpus([p for _scope, p in trdds])
    now = int(time.time())

    unconverted: list[str] = []
    for rep in sorted(reports_dir.rglob("*.md")):
        if not _DECISION_RE.search(rep.name):
            continue
        mtime = state.file_mtime(rep)
        if mtime > 0 and (now - mtime) < _FRESH_GRACE_S:
            continue  # too fresh — may still be writing
        # Memory-curator ABSTAIN / no-op pass report → no decision to convert (issue #63).
        if _is_memory_noop_report(rep, reports_dir):
            continue
        # Referenced by any TRDD (cited by basename) → already converted.
        if rep.name in corpus:
            continue
        try:
            rel = str(rep.relative_to(root))
        except ValueError:
            rel = rep.name
        unconverted.append(rel)

    if not unconverted:
        return 0

    listed = unconverted[:_MAX_LISTED]
    more = "" if len(unconverted) <= _MAX_LISTED else f" (+{len(unconverted) - _MAX_LISTED} more)"

    # Tick-bucket dedupe keyed by the SET of unconverted reports — a NEW
    # decision report produces a fresh key (fresh reminder); an unchanged set
    # reminds at most once per interval. Sort so directory order is irrelevant.
    sig = hashlib.sha1(",".join(sorted(unconverted)).encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    # max(1, …): interval=0 is a legal knob value (coerce_int only clamps negatives) and
    # must mean "every fire", never ZeroDivisionError — same guard as memorize-nudge.
    tick_key = f"tick-{now // max(1, interval)}-{sig}"

    seen = state.state_dir() / f"report-to-trdd-session-{_session_key()}.txt"
    msg = (
        f"[report-to-trdd] {len(unconverted)} decision/synthesis report(s) not yet "
        f"converted to a TRDD: {', '.join(listed)}{more}. Reports are gitignored/ephemeral "
        f"— write each decision into a TRDD (new, or extend an existing STATE block) and "
        f"cite the report, so the plan survives the next resume."
    )
    line = dedupe.emit_once(seen, tick_key, msg)
    if line is not None:
        print(line)

    state.rotate_log_if_big("report-to-trdd-drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
