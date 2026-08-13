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
# EVERY dir the memory curator writes under — not one literal (janitor#121).
#
# This was a single name, `memory-subconscious-agent`, and the agent has since been
# renamed `janitor-memory-subconscious-agent`, with per-chore dirs alongside it.
# Measured on this repo when the issue was worked: 53 reports in the covered legacy
# dir, and 6 in dirs the gate did not cover at all — so every abstain written since
# the rename was nagged again, which is precisely the unsatisfiable loop #121 reports.
#
# It is the SAME failure the long comment below dissects, one field over: that one
# asserted the producer's FORMAT from expectation instead of from artifacts; this one
# asserted its PATH. Both fail OPEN, which is why neither was noticed — an exclusion
# that never matches just looks like a noisy detector, never a broken one.
#
# Enumerated, not prefix-matched. `reports/memory-docs/` and
# `reports/memory-edit-verify/` are human work that SHOULD be flagged when it records
# a decision, and a `memory-*` prefix would silence both.
#
# Widening WHERE cannot silence a decision: `_is_memory_noop_report` still requires the
# curator's own no-op marker in the body, so a pass that actually merged or split is
# flagged in these dirs exactly as before. The dir set only bounds where a body marker
# is allowed to speak.
_MEMORY_CURATOR_DIRS: frozenset[str] = frozenset(
    {
        "memory-subconscious-agent",  # legacy name; 53 reports still on disk
        "janitor-memory-subconscious-agent",  # the agent's current name
    }
    | {
        # the per-chore dirs, one per marker the heartbeat can dispatch
        f"janitor-memory-{chore}"
        for chore in ("consolidate", "split", "atomize", "conflict", "repair", "harvest")
    }
)
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
    # 1. inline label: `**Outcome:** ABSTAINED …` OR `- Outcome: **ABSTAINED — …**`.
    #    MEASURED CORRECTION 2026-08-05 (#121 fired again): the previous form hard-coded the
    #    bold around the LABEL, but the curator bolds the VALUE — the live report reads
    #    `- Outcome: **ABSTAINED — no new merge candidate found**`, which never matched. The
    #    `**` are now optional on both sides, so all three real spellings are accepted.
    #    Same failure mode as the 2026-07-29 correction below, one field over: the guard was
    #    asserted against the format we expected rather than the bytes the producer writes,
    #    and it FAILED OPEN, so the only symptom was more nagging.
    r"(?:^[\s\-\*>|]*(?:\*\*)?outcome:?(?:\*\*)?[^\n]*?\b(?:abstain(?:ed)?|nothing\s+due)\b"
    # 2. section heading `## Outcome`, verb on the next non-empty line (the REAL form)
    r"|^#{1,4}[ \t]*outcome[ \t]*$\s*\n\s*[\s\-\*>|]*(?:abstain(?:ed)?|nothing\s+due)\b"
    # 3. H1 title carrying the word: `# CONSOLIDATE pass — LOCAL scope — abstained`
    r"|^#[ \t]+[^\n]*\b(?:abstain(?:ed)?|nothing\s+due)\b[^\n]*$)",
    re.IGNORECASE | re.MULTILINE,
)
# THE FIX THAT ENDS THE SERIES (janitor#259). The three corrections above — punctuation
# (2026-07-29), label placement (2026-08-05, #121), vocabulary (2026-08-13, #259: the curator
# wrote "Nothing merged this pass", and `nothing\s+due` does not match `nothing merged`) —
# are one failure repeated, and widening the pattern a fourth time would only postpone it.
#
# A regex over free prose cannot converge here because the producer is a LANGUAGE MODEL writing
# English: "nothing merged", "no candidates", "0 mutations", "skipped" and "abstained" all mean
# the same thing to it, and only some of them are in any pattern. Each fix matched the spellings
# in the corpus at the time; the next unobserved spelling was already being written.
#
# The proof that the mechanism (not the pattern) is at fault is in the same reports: the ONE
# machine-written line, `<!-- generated: ... -->`, has NEVER drifted — because a shell `printf`
# with a fixed literal emits it, not the model. That line exists because of janitor#248, whose
# lesson the curator's own doc states exactly: "a built string gets a plausible offset recalled
# instead of a real one read". A composed value drifts; an emitted literal does not.
#
# So the curator now closes every pass with a second mechanical line carrying its OWN verdict in
# a two-value vocabulary, and this detector reads THAT exactly. The prose forms below remain as a
# FALLBACK for the ~59 legacy reports already on disk, and are deliberately NOT widened again.
#
# Read authority, in order: an explicit marker WINS outright — `mutation` means NOT exempt even
# if the prose says "abstained", because the producer's own machine verdict beats an inference
# drawn from its narration. Only an ABSENT marker falls through to the prose.
#
# KNOWN AND ACCEPTED: legacy reports whose prose uses an unlisted spelling still nag. That is the
# cost of refusing the fourth patch, it is bounded (`_MAX_LISTED`), and it decays as the old
# reports age out — whereas another regex widening would have re-armed the same trap.
_MEMORY_OUTCOME_RE = re.compile(
    r"<!--\s*janitor-outcome:\s*(noop|mutation)\s*-->",
    re.IGNORECASE,
)
_MARKER_SCAN_BYTES = 64 * 1024  # the marker is APPENDED at pass end, so scan the whole report
_NOOP_SCAN_BYTES = 4096  # prose fallback only: the legacy outcome wording is in the opening lines
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

    Scoped to the curator's own report dirs (`_MEMORY_CURATOR_DIRS`) so it can never
    silence a decision report living elsewhere; then keyed off the curator's own
    `**Outcome:** ABSTAINED|NOTHING DUE` opening marker (issue #63). A pass that actually
    mutated the corpus and recommends follow-up lacks that marker → still flagged for
    conversion.

    Matches on the report's dir NAME rather than a built path, so a nested layout
    (`reports/<curator-dir>/<sub>/x.md`) is covered too — the previous
    `reports_dir / NAME in rep.parents` form only ever matched one exact depth.
    """
    if not any(p.name in _MEMORY_CURATOR_DIRS for p in rep.parents):
        return False
    if not _contained(rep, reports_dir):
        return False
    try:
        text = rep.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    # The curator's own machine verdict, when present, is authoritative in BOTH directions
    # (janitor#259). It is APPENDED when the pass ends, so it lives in the report's TAIL —
    # a head-only slice of `_MARKER_SCAN_BYTES` therefore misses it on exactly the long
    # decision reports, and silently reverts them to the fragile prose path this marker
    # exists to retire. Scan the head AND the tail, each bounded, never the head alone.
    window = (
        text if len(text) <= 2 * _MARKER_SCAN_BYTES
        else text[:_MARKER_SCAN_BYTES] + "\n" + text[-_MARKER_SCAN_BYTES:]
    )
    marker = _MEMORY_OUTCOME_RE.search(window)
    if marker is not None:
        return marker.group(1).lower() == "noop"
    # No marker: a legacy report (or a curator that skipped the closing block). Fall back to the
    # prose forms, over the SAME opening window as before so this path's behaviour is unchanged —
    # widening the window here would let form 3 (a bare `# … abstained` H1) match a heading deep
    # in a long decision report and silence it.
    return _MEMORY_NOOP_RE.search(text[:_NOOP_SCAN_BYTES]) is not None


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
