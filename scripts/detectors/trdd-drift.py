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

# How far ahead of NOW an `updated:` stamp may sit before it is reported.
#
# 5 minutes, and the number is doing real work in both directions. Timezone is NOT the risk the
# tolerance absorbs — the mandated format carries an explicit UTC offset, so the comparison is
# absolute — it absorbs CLOCK SKEW between contributors, because PROJECT TRDDs are git-tracked and
# pushed. Beyond ~5 minutes on an NTP-synced host the skew is itself a defect worth surfacing.
# Wide enough to swallow ordinary jitter and a card stamped the instant before this runs; far
# below the +77 and +79 minute errors actually measured, so the cases that motivated the check are
# caught with two orders of magnitude of margin.
_FUTURE_UPDATED_TOLERANCE_S = 300

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


# ── unblock-when (RTRS704K) — predicate kinds a card's `unblock-when:` may name ────────────
_PRED_TRDD_RE = re.compile(r"^trdd:([0-9A-Za-z]{8})\s+terminal$")
_PRED_ISSUE_RE = re.compile(r"^issue:([\w.-]+/[\w.-]+)#(\d+)\s+closed$")
_PRED_FILE_RE = re.compile(r"^file:(\S+)\s+exists$")
_PRED_LOG_RE = re.compile(r"^log:(\S+)\s+matches\s+(.+)$")
_PRED_DATE_RE = re.compile(r"^date:>=(\d{4})-(\d{2})-(\d{2})$")
_PRED_DECISION_RE = re.compile(r"^decision:\S+$")

# `log:` predicate reads only the TAIL of the target file — a `.janitor/logs/` file can grow
# to multi-MB and this predicate is re-evaluated every heartbeat, so a whole-file read+regex
# on every fire is an unbounded cost that scales with log age, not with what changed. 256 KiB
# comfortably covers the tail a fresh log line needs to appear in; older matches age out, same
# as `tail -f` behaviour a human would expect from a "did the log just say X" check.
_LOG_PRED_TAIL_BYTES = 256 * 1024


def _repo_relative(rel: str) -> bool:
    """True iff `rel` cannot escape the project root — a PROJECT card is pushed, so an
    absolute or `..`-climbing path in `file:`/`log:` would leak local layout to every
    cloner (advisor constraint, RTRS704K)."""
    return not rel.startswith("/") and ".." not in Path(rel).parts


def _evaluate_predicate(
    pred: str,
    *,
    column_by_uid: dict[str, str],
    project_repo_slug: str | None,
    open_issue_numbers: set[int] | None,
    project_root: Path,
    now: int,
) -> bool | None:
    """One `unblock-when:` predicate → True (satisfied) / False (not yet, or never
    auto-clearable) / None (malformed — unknown shape or an out-of-bounds path). PURE except
    for the two filesystem-read kinds, which fail to False (not a parse error) on I/O trouble.
    """
    m = _PRED_TRDD_RE.match(pred)
    if m:
        return trdd_common.is_terminal_column(column_by_uid.get(m.group(1), ""))
    m = _PRED_ISSUE_RE.match(pred)
    if m:
        owner_repo, num = m.group(1), int(m.group(2))
        # Cross-repo issues have no local snapshot to check against (advisor constraint) —
        # treat as `decision:`-shaped: never auto-clears, but it is a real predicate, not a
        # typo, so it is NOT malformed.
        if project_repo_slug is None or owner_repo.lower() != project_repo_slug.lower():
            return False
        # `None` means the snapshot itself is missing/unreadable — the ONLY safe reading is
        # "unknown, so not satisfied" (never True): an empty-but-present set already means
        # "snapshot read fine, zero open issues", which correctly satisfies this predicate.
        # Collapsing "missing" into "empty" is the bug this comment guards against — it made
        # every `issue:` predicate auto-satisfy the moment the watcher snapshot vanished.
        if open_issue_numbers is None:
            return False
        # The snapshot caps at the newest 50 open issues (github-issues-watch.py) — an issue
        # outside that window reads as "not present" i.e. closed, a false satisfy. Reliable
        # only while the repo has ≤50 open issues; not fixable here without changing the watcher.
        return num not in open_issue_numbers
    m = _PRED_FILE_RE.match(pred)
    if m:
        rel = m.group(1)
        if not _repo_relative(rel):
            return None
        return (project_root / rel).exists()
    m = _PRED_LOG_RE.match(pred)
    if m:
        rel, pattern = m.group(1), m.group(2)
        if not _repo_relative(rel):
            return None
        try:
            with (project_root / rel).open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                truncated = size > _LOG_PRED_TAIL_BYTES
                fh.seek(max(0, size - _LOG_PRED_TAIL_BYTES))
                tail = fh.read()
        except OSError:
            return False
        text = tail.decode("utf-8", errors="replace")
        if truncated:
            # The seek can land mid-line, and `^` matches at index 0 of the decoded string
            # regardless of `re.MULTILINE` — so a `^`-anchored pattern could match a line
            # FRAGMENT the seek cut in half (the real line started before the window). A
            # sentinel byte at index 0 is NOT enough: `^.*needle` swallows the sentinel and
            # still matches the fragment. Drop everything up to and including the first `\n`
            # instead — every line left in the window is then whole, so a match can only be a
            # line the log genuinely wrote. A tail with no `\n` at all is one >256 KiB line,
            # not a log; it matches nothing.
            nl = text.find("\n")
            text = text[nl + 1 :] if nl >= 0 else ""
        try:
            compiled = re.compile(pattern, re.MULTILINE)
        except re.error:
            return None
        # A pathological pattern can only backtrack across the bounded tail read above, not
        # an unbounded log — the size cap is what keeps this call's worst case finite.
        return compiled.search(text) is not None
    m = _PRED_DATE_RE.match(pred)
    if m:
        try:
            target = (
                datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                .astimezone()
                .timestamp()
            )
        except ValueError:
            return None
        return now >= target
    if _PRED_DECISION_RE.match(pred):
        return False  # the ONLY human-only kind — the attention cue surfaces it, never this
    return None  # unrecognized shape


def evaluate_unblock_when(
    predicates: list[str],
    *,
    column_by_uid: dict[str, str],
    project_repo_slug: str | None,
    open_issue_numbers: set[int] | None,
    project_root: Path,
    now: int,
) -> tuple[bool, list[str]]:
    """(all_satisfied, malformed_tokens) for a card's `unblock-when:` list.

    Fails OPEN toward "stay blocked" on a malformed predicate — the inverse stance of
    `review_after_epoch` (which fails open toward "check it"), because here the failure mode
    to avoid is unblocking a card on a typo, not silencing one.
    """
    malformed: list[str] = []
    all_true = True
    for pred in predicates:
        result = _evaluate_predicate(
            pred,
            column_by_uid=column_by_uid,
            project_repo_slug=project_repo_slug,
            open_issue_numbers=open_issue_numbers,
            project_root=project_root,
            now=now,
        )
        if result is None:
            malformed.append(pred)
            all_true = False
        elif result is not True:
            all_true = False
    return (all_true and not malformed), malformed


_FM_COLUMN_BLOCKED_RE = re.compile(r"^column:[ \t]*blocked[ \t]*$", re.MULTILINE)
_FM_UPDATED_LINE_RE = re.compile(r"^updated:[ \t]*.*$", re.MULTILINE)
_FM_PRE_BLOCK_COLUMN_LINE_RE = re.compile(r"^pre-block-column:[ \t]*.*\n?", re.MULTILINE)


def _restore_column_text(text: str, target_column: str, now_iso: str) -> str | None:
    """Rewrite `column: blocked` → `column: <target_column>`, bump `updated:`, clear
    `blocked-by:` and drop `pre-block-column:` — both scoped to the frontmatter block only.

    `blocked-by:` and `pre-block-column:` MUST be cleared here (rule §6: "`blocked-by:`
    empties; restore previous column"), not left behind — otherwise `check4_stale_blockers`
    re-flags the leftover id as a "cleared blocker" every fire (advisor finding B2), even
    though the card already left `blocked`.

    None if the shape doesn't match — the caller then writes nothing rather than risk a
    malformed rewrite.
    """
    m = trdd_common.FRONTMATTER_RE.match(text)
    if not m:
        return None
    block = m.group(1)
    block, n = _FM_COLUMN_BLOCKED_RE.subn(f"column: {target_column}", block, count=1)
    if n != 1:
        return None
    block, n = _FM_UPDATED_LINE_RE.subn(f"updated: {now_iso}", block, count=1)
    if n != 1:
        return None
    block = trdd_common.FM_BLOCKED_BY_RE.sub("blocked-by: []", block, count=1)
    block = _FM_PRE_BLOCK_COLUMN_LINE_RE.sub("", block, count=1)
    return text[: m.start(1)] + block + text[m.end(1) :]


def _try_unblock(
    f: Path,
    head: str,
    *,
    column_by_uid: dict[str, str],
    project_repo_slug: str | None,
    open_issue_numbers: set[int] | None,
    project_root: Path,
    now: int,
    seen: Path,
) -> None:
    """Restore a `column: blocked` card whose `unblock-when:` predicates now ALL hold.

    No `unblock-when:` field → nothing to do (silent — `blocked-by:` alone stays a human
    read, per rule §6). Never touches a card with no field, never partially restores one.
    """
    predicates = trdd_common.unblock_when_predicates(head)
    if not predicates:
        return
    satisfied, malformed = evaluate_unblock_when(
        predicates,
        column_by_uid=column_by_uid,
        project_repo_slug=project_repo_slug,
        open_issue_numbers=open_issue_numbers,
        project_root=project_root,
        now=now,
    )
    uid = trdd_common.extract_uid(f.name)
    if uid is None:
        return
    if malformed:
        state.log_line(
            "trdd-drift",
            f"TRDD-{uid[:8]} unblock-when has a malformed predicate "
            f"{malformed!r} — staying blocked, never auto-unblocking on a parse error.",
        )
    if not satisfied:
        return
    # `unblock-when:` predicates can all hold while `blocked-by:` still names a live blocker
    # (the two fields are authored independently) — restoring past that would unblock a card
    # whose actual dependency has not resolved. `blocked_by_ids` extracts only TRDD-SHAPED
    # ids — a `#N`/`owner/repo#N` issue ref or a descriptive token (e.g. `owner-decision-x`)
    # does NOT match its pattern and is silently skipped by design: RTRS704K's own
    # `unblock-when: decision:` predicate is the machine-checkable replacement for those, and
    # `blocked-by:` is scoped to TRDD-to-TRDD dependencies only. Every id `blocked_by_ids`
    # DOES return here IS a TRDD reference, and it must have actually SHIPPED (`DONE_COLUMNS`)
    # to clear the hold — `failed`/`refused`/`cancelled`/`superseded` are terminal but NOT
    # done, so they stay a hold too, mirroring dispatch.py's `_blocked_reason`, which
    # classifies both an unresolvable id and a non-shipped terminal blocker as decision-needed.
    fm = trdd_common.FRONTMATTER_RE.match(head)
    blocked_by_raw = trdd_common.FM_BLOCKED_BY_RE.search(fm.group(1)) if fm else None
    if blocked_by_raw:
        for blocker_id in trdd_common.blocked_by_ids(blocked_by_raw.group(1)):
            blocker_column = column_by_uid.get(blocker_id)
            if blocker_column is None:
                state.log_line(
                    "trdd-drift",
                    f"TRDD-{uid[:8]} unblock-when satisfied but blocked-by "
                    f"TRDD-{blocker_id} is unresolvable — holding.",
                )
                return
            if not trdd_common.is_done_column(blocker_column):
                state.log_line(
                    "trdd-drift",
                    f"TRDD-{uid[:8]} unblock-when satisfied but blocked-by "
                    f"TRDD-{blocker_id} still {blocker_column} — holding.",
                )
                return
    target = trdd_common.pre_block_column(head) or "todo"
    # `pre-block-column:` is free-text frontmatter — an author typo or corruption there must
    # not silently plant an illegal `column:` value on restore (advisor finding B4). "blocked"
    # itself is also refused: restoring INTO the state being restored FROM is not a restore.
    if target not in trdd_common.ALL_COLUMNS or target == "blocked":
        state.log_line(
            "trdd-drift",
            f"TRDD-{uid[:8]} unblock-when satisfied but pre-block-column "
            f"{target!r} is not a legal column — holding rather than write it.",
        )
        return
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return
    now_iso = datetime.fromtimestamp(now).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    new_text = _restore_column_text(text, target, now_iso)
    if new_text is None:
        return
    try:
        state.atomic_write(f, new_text)
    except OSError:
        return
    line = dedupe.emit_once(
        seen,
        f"unblocked@{uid}@{now // 86400}",
        f"[trdd-drift] TRDD-{uid[:8]} unblock-when predicates all satisfied — "
        f"restored column: blocked -> {target}.",
    )
    if line is not None:
        print(line)


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


def _autofix_frontmatter(path: Path) -> str | None:
    """Repair `path`'s frontmatter prelude in place; return what was removed, or None.

    The return value is a SHORT human label of the removed bytes ("a UTF-8 BOM", "2 blank
    lines"), not the bytes themselves — the drift line quotes it, and the bytes are by
    definition invisible, so echoing them would print nothing useful and risk pasting a BOM
    into a terminal.

    FAILS SILENT, on purpose. An unreadable or unwritable card is not a repair opportunity,
    and a detector that raised here would take the whole heartbeat down over one bad file —
    turning a cosmetic finding into an outage. It simply declines, and the notify path below
    still reports the defect, so nothing is lost by the decline.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    fixed = trdd_common.repair_frontmatter_prelude(text)
    if fixed is None:
        return None
    removed = text[: len(text) - len(fixed)]
    parts = []
    if removed.startswith(trdd_common.BOM):
        parts.append("a UTF-8 BOM")
    blanks = removed.lstrip(trdd_common.BOM).count("\n")
    if blanks:
        parts.append(f"{blanks} blank line{'s' if blanks != 1 else ''}")
    try:
        state.atomic_write(path, fixed)
    except OSError:
        return None
    return " and ".join(parts) or "leading whitespace"


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

    # Pass 1 — a uid->column board for the `trdd:<id> terminal` predicate kind (mirrors
    # trdd-state-reconciliation's Check-4 board) AND for the `blocked-by:` hold below. Built
    # over EVERY design folder (tasks/archived/proposals/refused), not just `tasks/` — a
    # blocker that already SHIPPED is archived and therefore invisible to `trdd_files("tasks")`
    # alone, which made a completed-and-archived blocker look "unresolvable" and held its
    # dependent blocked forever (RTRS704K finding #1; mirrors dispatch.py's `_all_folders_columns`).
    column_by_uid: dict[str, str] = {}
    for _folder in trdd_common.DESIGN_FOLDERS:
        for _scope, _f in trdd_common.trdd_files(_folder, str(root)):
            _uid = trdd_common.extract_uid(_f.name)
            if _uid is not None and _uid not in column_by_uid:
                _, _col = _parse_trdd_state(_f)
                column_by_uid[_uid] = _col

    # This project's own `owner/repo` + its currently-open issue numbers, from the
    # network-free snapshot `github-issues-watch` already maintains (dispatch.py's
    # `_open_issues_bit` reads the same file the same way) — the `issue:<owner/repo#N>
    # closed` predicate must never hit the network per card per fire (advisor constraint).
    project_repo_slug: str | None = None
    remote_proc = state.run_subprocess(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        timeout=5,
        detector_name="trdd-drift",
    )
    if remote_proc is not None and remote_proc.returncode == 0:
        import issues_watch  # noqa: PLC0415 - lazy, this detector's only use of it (lib already on sys.path)

        project_repo_slug = issues_watch.parse_remote_slug(remote_proc.stdout or "")
    # `None` = no readable snapshot yet, distinct from an empty-but-present one (zero open
    # issues) — collapsing the two used to auto-satisfy `issue:` predicates the moment the
    # snapshot was absent, since `num not in set()` is always True (advisor finding B1).
    open_issue_numbers: set[int] | None = None
    try:
        import json  # noqa: PLC0415 - lazy, this detector's only use of it

        seen_issues_raw = json.loads(
            (state.state_dir() / "issues-watch-seen.json").read_text(encoding="utf-8")
        )
        if isinstance(seen_issues_raw, dict):
            open_issue_numbers = {int(k) for k in seen_issues_raw if str(k).isdigit()}
    except (OSError, ValueError):
        pass  # no snapshot yet — every `issue:` predicate on THIS repo stays unsatisfied (None)

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
                # AUTOFIX LANE (USER decision #12, 2026-08-22): formatting is repaired, content
                # is only ever reported. `repair_frontmatter_prelude` returns non-None ONLY for
                # the two cases where the removed bytes carry no assertion (a BOM, blank lines),
                # so the repaired card says exactly what it said before — that is what makes
                # acting without asking defensible here and not for the sibling defects, which
                # all need a human to decide something. `updated:` is deliberately NOT bumped:
                # the board sorts on it, and a repair that changes no fact must not reorder it.
                fixed = _autofix_frontmatter(f) if state.autofix_enabled() else None
                if fixed is not None:
                    line = dedupe.emit_once(
                        seen,
                        f"frontmatter@{uid}",
                        f"[trdd-drift] TRDD-{uid[:8]}{tag} unreadable frontmatter AUTOFIXED: "
                        f"{state.sanitize_for_drift_line(fixed)} removed from above the YAML "
                        f"block, which now opens on line 1. No assertion changed; `updated:` "
                        f"deliberately left alone. `/janitor-autofix-off` to stop this.",
                    )
                    if line is not None:
                        print(line)
                    continue
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

        # ── future `updated:` ────────────────────────────────────────────────────────
        # Checked BEFORE the active-column filter, deliberately: a future stamp corrupts the
        # board's sort order no matter which column the card sits in, and a TERMINAL card is not
        # exempt — rule §12 freezes a terminal TRDD's BODY but explicitly still allows `updated:`
        # to change, so this finding is actionable there too. Filtering it behind the active set
        # would leave the 169 `complete` cards permanently unauditable on the one field that
        # orders the board.
        #
        # This is the FIRST consumer of `updated:` in this detector — staleness is judged from git
        # commit time (`_last_touched_epoch`), never from the frontmatter — and that is exactly why
        # nothing validated the field: it had no reader.
        try:
            fm_head = f.read_text(encoding="utf-8")[:4096]
        except OSError:
            fm_head = ""
        bad_stamp = trdd_common.future_updated(fm_head, now, _FUTURE_UPDATED_TOLERANCE_S)
        if bad_stamp is not None:
            uid = trdd_common.extract_uid(f.name)
            if uid is not None:
                tag = " (local)" if scope == trdd_common.LOCAL else ""
                # The offending value is in the dedupe key, NOT just the message: the other
                # findings here key on `<kind>@<uid>` and so report a card once and never again,
                # which would swallow a SECOND bad stamp written after the first was fixed. A
                # corrected card simply stops matching; a newly-broken one is a new key.
                line = dedupe.emit_once(
                    seen,
                    f"future-updated@{uid}@{bad_stamp}",
                    f"[trdd-drift] TRDD-{uid[:8]}{tag} updated='"
                    f"{state.sanitize_for_drift_line(bad_stamp)}' is in the FUTURE — the board "
                    f"sorts on this field, so the card outranks every honest one. Regenerate it "
                    f"with `date +%Y-%m-%dT%H:%M:%S%z`.",
                )
                if line is not None:
                    print(line)

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
            if column == "blocked":
                # `blocked` is not drift-eligible (it IS the licence to sit still) — but it
                # may carry a machine-checkable `unblock-when:` this fire can clear on its
                # own (RTRS704K). No such field → `_try_unblock` is a no-op.
                _try_unblock(
                    f,
                    fm_head,
                    column_by_uid=column_by_uid,
                    project_repo_slug=project_repo_slug,
                    open_issue_numbers=open_issue_numbers,
                    project_root=root,
                    now=now,
                    seen=seen,
                )
                continue
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
