#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""TRDD drift detector — Python port of trdd-drift.sh.

One-shot scan for stale active TRDDs — frontmatter `status:`
`not-started`/`in-progress` (v1) or a v2 `column:` in the
actively-in-flight set — that have not been touched for too long.
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402
import trdd_common  # noqa: E402

# The TRDD filename / frontmatter parsing is shared across the TRDD detectors —
# it lives in trdd_common now (TRDD-15ECPBSA). `extract_uid` is the SINGLE id
# matcher (base36 UPPERCASE id + legacy lowercase-hex/UUID, case preserved): it
# catches the modern uppercase-base36 ids that the old `[0-9a-f]{8}` matcher
# silently DROPPED, so a stale v2 TRDD is no longer invisible to this detector.
_parse_trdd_state = trdd_common.parse_trdd_state
_ACTIVE_COLUMNS = trdd_common.ACTIVE_COLUMNS

# Status values (v1 frontmatter / legacy body) that warrant a drift nudge.
_DRIFT_ACTIVE_STATUSES = frozenset({"not-started", "in-progress"})

# `review-after: YYYY-MM-DD` — a DELIBERATE park, honoured until that date.
_REVIEW_AFTER_RE = re.compile(r"^review-after:\s*(\d{4})-(\d{2})-(\d{2})\s*$", re.MULTILINE)


def review_after_epoch(head: str) -> int | None:
    """The epoch of a TRDD's `review-after:` date, or None when it declares none. PURE.

    A `backburner` TRDD is drift-eligible on purpose — most of them ARE forgotten work. But
    some are parked for a stated reason (TRDD-de731408 is shelved pending an upstream Claude
    Code change), and nagging those every sweep is a false positive that trains a reader to
    ignore the detector. The alternative — bumping `updated:` to quiet it — is worse: it
    would assert the file changed when nothing did.

    This is a SNOOZE, not a mute, and the distinction is the whole design. A bare
    "shelved" label would silence the TRDD forever, which is exactly the failure the
    janitor already learned the hard way: a temporary global disarm went unnoticed for ~33h
    because nothing carried its duration or reason. A DATE expires by itself, so a park a
    human forgets re-surfaces on its own.

    Parses only a well-formed date at column 0. Anything else returns None and the TRDD is
    checked normally — a malformed snooze must never silence a TRDD by accident.
    """
    m = _REVIEW_AFTER_RE.search(head or "")
    if m is None:
        return None
    try:
        return int(
            datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            .astimezone()
            .timestamp()
        )
    except ValueError:
        return None  # e.g. 2026-02-31 — a nonsense date is not a valid snooze


def _last_touched_epoch(path: Path, project_root: Path) -> int:
    """Prefer git last-commit timestamp, fall back to mtime for uncommitted files.

    Bounded by a 5s timeout — `git log -1` is normally instant but a
    corrupted refs pack would otherwise hang the whole heartbeat.
    """
    proc = state.run_subprocess(
        ["git", "-C", str(project_root), "log", "-1", "--format=%ct", "--", str(path)],
        timeout=5,
        detector_name="trdd-drift",
    )
    if proc is not None and proc.returncode == 0:
        out = proc.stdout.strip()
        if out.isdigit():
            return int(out)
    return state.file_mtime(path)


def main() -> int:
    state.init_state()
    # Context gate (TRDD-db169d9e R1): TRDD enforcement is an ai-maestro/Emasoft
    # framework convention. The janitor runs at USER scope in EVERY project, so
    # stay silent in projects that aren't ai-maestro-plugins members. (Override
    # with JANITOR_FORCE_AI_MAESTRO=1 to use TRDDs in a non-ai-maestro project.)
    if not state.project_is_ai_maestro():
        return 0

    stale_days = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_TRDD_STALENESS_DAYS"), 14)
    seen = state.state_dir() / "trdd-drift-seen.txt"

    root = state.project_root()

    # BOTH design scopes — PROJECT (`<repo>/design/tasks`, honoring
    # CLAUDE_PLUGIN_OPTION_TRDD_PATH) and LOCAL (`~/.claude/projects/<slug>/design/tasks`).
    # `trdd_common` owns the resolution AND the containment check that refuses a TRDD_PATH
    # escaping the project root — that check lived here as a private copy, which is exactly
    # how a second root gets missed by one consumer and its tasks go invisible.
    trdds = trdd_common.trdd_files("tasks", str(root))
    if not trdds:
        state.log_line("trdd-drift", "no TRDDs in any design scope — skipping")
        return 0

    now = int(time.time())

    for scope, f in trdds:
        status, column = _parse_trdd_state(f)

        # A TRDD that parsed to NOTHING is invisible to every column query while
        # `grep '^column:'` still shows its line — so ask WHY before the filter
        # below silently drops the file most in need of a nudge (TRDD-WEBA1RMF
        # fell off the board and blocked a release exactly this way).
        #
        # Gated on `not status and not column`, NOT on "has no frontmatter": the
        # LEGACY body-only `**Status:** In progress` form carries no frontmatter
        # BY DESIGN and still parses via parse_state_text's fallback. Asking the
        # defect question first suppressed that form's real drift line — caught
        # by test_drift_legacy_status_body_flagged. Parse first, diagnose second.
        if not status and not column:
            defect = trdd_common.frontmatter_defect_for(f)
            uid = trdd_common.extract_uid(f.name)
            if defect is not None and uid is not None:
                tag = " (local)" if scope == trdd_common.LOCAL else ""
                # `defect` embeds a slice of line 1 — author-controlled text.
                line = dedupe.emit_once(
                    seen,
                    f"frontmatter@{uid}",
                    f"[trdd-drift] TRDD-{uid[:8]}{tag} unreadable frontmatter: "
                    f"{state.sanitize_for_drift_line(defect)} — its column:/status: are "
                    f"invisible to the board. Move the YAML block to line 1.",
                )
                if line is not None:
                    print(line)
            continue
        # `column:` WINS whenever present (issue #135). A v2 card's column is its state, so
        # a v1 `status:` alongside one is legacy residue, not a second opinion — and the OR
        # this replaced let that residue override a TERMINAL column, reporting a frozen
        # `complete` TRDD as drifting. That finding was unclearable by construction: §12
        # forbids editing a terminal TRDD, so there was no action that could satisfy it.
        #
        # Only a card with NO column at all is judged by v1 status. The column set is broader
        # than the v1 statuses on purpose — a `backburner`/`todo` TRDD that hasn't moved in
        # weeks is exactly the staleness worth surfacing.
        if column:
            if column not in _ACTIVE_COLUMNS:
                continue
        elif status not in _DRIFT_ACTIVE_STATUSES:
            continue

        # A stated park is honoured until its own date, then expires on its own.
        try:
            head = f.read_text(encoding="utf-8")[:4096]
        except OSError:
            head = ""
        review_after = review_after_epoch(head)
        if review_after is not None and now < review_after:
            continue

        # A `backburner` card whose staleness is EXPLAINED — `blocked-by:` or `npt:`
        # populated — is not "forgotten": it is correctly parked pending that stated
        # condition (janitor#189: 31/32 flagged cards were already correct, and this was
        # the actionable shape among them — a card with a real precondition on file).
        # Narrower than exempting the whole column: a `backburner` card with NEITHER
        # field set still fires, so genuinely forgotten work keeps surfacing.
        if column == "backburner" and trdd_common.has_stated_precondition(head):
            continue
        # Label from the field that DECIDED eligibility above, so the line can never assert a
        # state the card does not hold. The old `status or column` preferred v1 status even on
        # a v2 card, which is how `status='not-started'` was printed for a `column: complete`
        # TRDD whose frontmatter contains no `status:` at all (issue #135).
        active_label = column or status
        # …and NAME that field, rather than hardcoding "status=". Printing `status='dev'` for
        # a card whose frontmatter says `column: dev` is the same defect #135 was about in
        # miniature: the line asserts a field the file does not carry, and a reader who greps
        # `^status:` to check finds nothing and distrusts the detector.
        active_field = "column" if column else "status"

        # PROJECT TRDDs are git-tracked, so their last-commit time is the honest "last
        # touched" (an mtime is churned by any checkout). A LOCAL TRDD lives OUTSIDE the
        # repo and is in no git at all — asking git about it is meaningless, so use its
        # mtime directly rather than relying on `git log` to fail quietly on a foreign path.
        touched = (
            _last_touched_epoch(f, root)
            if scope == trdd_common.PROJECT
            else state.file_mtime(f)
        )
        if touched == 0:
            continue

        age_days = (now - touched) // 86400
        if age_days < stale_days:
            continue

        # The SINGLE id matcher: base36 UPPERCASE id or legacy UUID, case
        # preserved; None for a non-TRDD filename. Feeds the dedupe key (unique)
        # and the `[:8]` display ref.
        uuid = trdd_common.extract_uid(f.name)
        if uuid is None:
            continue
        bucket = age_days // 7

        # `active_label` is whatever the human author wrote in the
        # status:/column: frontmatter — fully untrusted text. The narrowing
        # membership check above limits the value to a known set in normal
        # operation, but a future format change could widen it — defang here.
        display_status = state.sanitize_for_drift_line(active_label)
        # Name the scope only when it is LOCAL — PROJECT is the default board, and tagging
        # every line with it would be noise. TRDD ids are globally unique, so the dedupe key
        # needs no scope qualifier.
        tag = " (local)" if scope == trdd_common.LOCAL else ""
        line = dedupe.emit_once(
            seen,
            f"drift@{uuid}@bucket-{bucket}",
            f"[trdd-drift] TRDD-{uuid[:8]}{tag} {active_field}='{display_status}' "
            f"but file untouched for {age_days}d.",
        )
        if line is not None:
            print(line)

    state.rotate_log_if_big("trdd-drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
