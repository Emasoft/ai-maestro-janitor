# Shared parser for the janitor-memory-subconscious-agent's closing outcome marker.
#
# Two detectors (memory-maintenance.py, report-to-trdd-drift.py) each carried their own
# copy of `<!-- janitor-outcome: noop|mutation [reason=<token>] -->` regex, and the two
# copies diverged: memory-maintenance.py pinned the reason to `[a-z-]+`, so a marker like
# `reason=no_work` (underscore) or a quoted `reason="no-work"` failed the WHOLE regex —
# not just the reason group — silently demoting a present marker to "no marker found" and
# defeating that file's own fail-open contract. report-to-trdd-drift.py separately widened
# its copy to `\S+` for exactly this reason (see its comment, 2026-09-15 review). One
# pattern here, used by both; each caller validates the reason value in code instead of in
# the regex, so an unrecognized token degrades gracefully instead of hiding the marker.
from __future__ import annotations

import re

MEMORY_OUTCOME_RE = re.compile(
    r"<!--\s*janitor-outcome:\s*(noop|mutation)(?:\s+reason=(\S+))?\s*-->",
    re.IGNORECASE,
)

REASON_NO_WORK = "no-work"
REASON_FAILED = "failed"


def parse_outcome(text: str) -> tuple[str, str | None] | None:
    """Return (outcome, reason) from the LAST marker in `text`, or None if absent.

    `outcome` is "noop" or "mutation" (lowercased). `reason` is the raw token after
    `reason=`, stripped of surrounding quotes if present, lowercased, or None when the
    marker carries no reason suffix. Validating the reason against known values
    (REASON_NO_WORK / REASON_FAILED) is the caller's job — an unlisted token is still a
    present marker, just not one that means "no-work".

    Last-occurrence, not first: a report may QUOTE the marker syntax in prose before the
    real, appended verdict — anchoring on the last match keeps the quoted example from
    overriding the actual outcome.
    """
    matches = list(MEMORY_OUTCOME_RE.finditer(text))
    if not matches:
        return None
    m = matches[-1]
    outcome = m.group(1).lower()
    reason = m.group(2)
    if reason is not None:
        reason = reason.strip("'\"").lower()
    return outcome, reason
