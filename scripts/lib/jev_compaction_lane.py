"""Jev-compaction lane library (TRDD-RAEGS1D5 card 3 C2).

Extracted out of `scripts/summarize_previous_session.py` once that entry point grew from 137 to
~530 lines wiring `jev_compact.py compact` in (card 3 C1): the trddgrep board/STATE-heads
discovery, the `jev_compact.py compact` subprocess runner, the exit-code -> findings-ledger
mapper, and their supporting constants all live here now, so the entry script goes back to being
a thin ~140-line orchestrator.

STDLIB ONLY. This module is imported IN-PROCESS by `summarize_previous_session.py`, which must
itself stay PEP-723 stdlib-only (see its own module docstring: `jev_compact.py` is the ONE place
`httpx`/`jevctx`/`jev_compaction` may be imported, always reached through a subprocess). Never add
a `jevctx`/`httpx`/`jev_compaction` import here -- `tests/test_jev_boundary.py` pins this file
into the same forbidden-import list as `scripts/lib/external_clear.py` and
`scripts/summarize_previous_session.py` for exactly that reason.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Callable

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

# `external_clear` (TRDD-RAEGS1D5 room-floor follow-up): the floor helper below composes
# `external_clear.HandoffInputs`/`compose_handoff_room` directly -- no cycle (external_clear never
# imports this module, grep-verified), and `test_jev_boundary.py` only forbids
# jevctx/httpx/jev_compaction/llm_ext_summary here, not `external_clear` (both are already treated
# as peer "import-light" modules there).
import dedupe  # noqa: E402
import external_clear  # noqa: E402
import findings_ledger  # noqa: E402
import global_state  # noqa: E402
import state  # noqa: E402
import transcript_roles  # noqa: E402  -- stdlib-only, shared classifier (used by _scan_transcript_mentions)
import trdd_common  # noqa: E402  -- stdlib-only (TERMINAL_COLUMNS), shared with the drift detectors

_LOG = "session-summary"

# `jev_compact.py compact`'s exit-code contract (its own module docstring is the source of
# truth; TRDD-RAEGS1D5 card 3 part B). `run_compact` ITSELF never retries -- one call, one
# subprocess, a `TimeoutExpired` is a bug exit here, same as any other non-zero/non-{5,6}
# code. `run_compact_with_fallback` (below), added by owner decision 2026-09-23, is the one
# place that calls `run_compact` more than once for the SAME compaction, on a bounded budget.
EXIT_OK = 0
EXIT_DECLINED_UNAVAILABLE = 5
EXIT_DECLINED_NO_DIGEST = 6
EXIT_JEV_ERROR = 7
# Not one of jev_compact.py's own contract codes -- the shell's own "command not found", which
# the exec-by-path call in `run_compact` can hit when a launchd/cron-started session inherits a
# bare PATH with no `uv` on it (coordinator amendment, card 3 C2).
EXIT_COMMAND_NOT_FOUND = 127

# jev_compact.py's own probe-stamp filename/location (its module docstring is the single
# source of truth for the SHAPE; duplicated here only as a bare string, never as a schema,
# because nothing in this lane may `import jev_compact` in-process -- that would pull in
# `jevctx`/`httpx`, exactly what `test_jev_boundary.py` forbids for every stdlib-only module).
PROBE_STAMP_NAME = "jev-probe.json"

# Which board columns count as "in-flight" for STATE-head selection (brief: docs_dev/
# jev-card3c-brief.md, C1). TRDD-O2FNJ4KW: no longer the sole candidate set for the top-6 cards
# a resumed session is shown -- ALL non-terminal columns are candidates now (see
# `_select_and_rank_cards`), a card the transcript actually mentions in `todo`/`live_auditing`/
# etc. ranks ahead of a stale card sitting in one of these columns. This set is now only the
# deterministic FILL-IN pool used when fewer than `TOP_CARD_COUNT` cards were mentioned at all.
# A `frozenset` here was measured to iterate in a different order across three separate Python
# processes (hash-randomized `PYTHONHASHSEED`), which made both the STATE-head list AND their
# `build_digest` eviction order non-reproducible run to run -- a plain `tuple` fixes that (the
# fill-in path below also re-sorts by `(column, id)` before use, so this tuple's own order is
# belt-and-suspenders, not load-bearing on its own).
STATE_HEAD_COLUMNS = ("dev", "testing", "ai_review", "verify_assumptions", "plan", "dispatch")

# `trddgrep`'s bare board dump is ANSI-colored, human prose -- there is no machine-readable
# board listing in the installed CLI (its own --help says `--porcelain` covers `show`/search
# only, and testing confirmed the board view ignores it). Rather than read a TRDD file
# ourselves (forbidden -- PRRD G12.1, only trddgrep touches a TRDD), this parses the SAME
# board dump a human would see: strip ANSI, track the `═══ <COLUMN> (` section headers, and
# pull the 8-char id token off each entry line.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_HEADER_RE = re.compile(r"^═+\s*(\S+)\s*\(")
_ID_RE = re.compile(r"^\s*([A-Z0-9]{8})\s+\S+\s+\S+\s+(.*)$")

# The env marker a future non-SessionStart spawn point (e.g. a daemon lane) would set before
# invoking this lane, so the "scorer unreachable" finding can name which lane hit it
# (coordinator amendment to TRDD-RAEGS1D5 card 3 part C). TODAY only the SessionStart hook
# spawns `summarize_previous_session.py` (`scripts/hooks/on-session-start.py`, confirmed by
# grep -- no daemon spawn site exists yet), so the default is correct as shipped; this is only a
# hook for later.
LANE = os.environ.get("JANITOR_JEV_LANE") or "session-start"

# `kind=auth` findings are deduped (coordinator amendment): a rejected provider key does not
# change on every retry, so re-surfacing it every SessionStart is noise, not new information.
# Every other kind is re-surfaced on each occurrence -- an outage or a bug is worth repeating
# until it's fixed. One seen-file, keyed by a hash of the reason text (unbounded length).
AUTH_SEEN_FILE = "jev-auth-finding-seen"

# Every `trddgrep` subprocess call is capped at 10s (TRDD-RAEGS1D5 card 3 C2, amended down from
# C1's 15-20s): a SQLite index locked by a concurrent `trddgrep move` must not stall the
# composer -- TimeoutExpired or a non-zero exit both degrade to "no heads", never a hang.
_TRDDGREP_TIMEOUT_S = 10


def previous_transcript(root: Path, current_session_id: str) -> Path | None:
    """The newest transcript that is NOT this session's.

    `current_session_id` is excluded by STEM, not by mtime: at SessionStart the new transcript may
    already exist and may already be the newest, so "newest" alone would summarize the blank
    session that just started — the same empty-source trap the post-clear path guards against,
    arriving by a different route.
    """
    try:
        import cold_cache_compact  # noqa: PLC0415

        newest = cold_cache_compact.newest_transcript(root)
        if newest is None:
            return None
        parent = newest.parent
        candidates = [
            p for p in parent.glob("*.jsonl")
            if p.is_file() and p.stat().st_size > 0 and current_session_id not in p.stem
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)
    except (OSError, ValueError, ImportError):
        return None


def _board_ids_by_column(root: Path) -> dict[str, list[tuple[str, str]]] | None:
    """`{column: [(id, title), ...]}` off `trddgrep`'s plain board dump, or `None` when
    trddgrep is absent or the call failed -- the caller's signal to note "heads unavailable"
    rather than silently inject zero heads/cards as if that were simply this session's true
    state. `title` is carried alongside `id` (not just the id) so callers can build real
    `HandoffInputs.cards` entries from the SAME call, instead of shipping an always-empty
    facts section whose "read the first in-flight card" NEXT ACTION text would otherwise lie
    (review finding on TRDD-RAEGS1D5 C1: an empty `cards=[]` makes compose_template_handoff's
    fixed NEXT-ACTION prose point at nothing)."""
    exe = shutil.which("trddgrep")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "--design-dir", str(root / "design")],
            cwd=str(root), capture_output=True, text=True, timeout=_TRDDGREP_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1):  # 1 == "no cards match" -- still a clean run
        return None
    by_col: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    for raw_line in proc.stdout.splitlines():
        line = _ANSI_RE.sub("", raw_line)
        header = _HEADER_RE.match(line)
        if header:
            current = header.group(1).lower()
            continue
        m = _ID_RE.match(line)
        if m and current:
            title = m.group(2).strip()
            by_col.setdefault(current, []).append((m.group(1), title))
    return by_col


def _extract_state_section(show_output: str) -> str | None:
    """The `⏵ STATE` section of a `trddgrep show <id>` transcript, or `None` when the card
    carries none (its output then reads literally "(no STATE block — read the file)" — noise,
    not a head worth passing on)."""
    cleaned = _ANSI_RE.sub("", show_output)
    idx = cleaned.find("⏵ STATE")
    if idx == -1:
        return None
    return cleaned[idx:].strip()


# TRDD-O2FNJ4KW follow-up (review corrections 1-2): the id union built below replaces this fixed
# `TRDD-<id>`-only pattern. A mention must now (a) be one of the OPEN cards the board already
# named -- so a random 8-char uppercase word can never false-positive -- and (b) may be spelled
# `TRDD-<id>`, `#<id>`, or bare `<id>`, since real transcript prose overwhelmingly drops the
# `TRDD-` prefix ("EFA4P42B is committed").
#: How many DISTINCT open-card ids a single ASSISTANT-authored block (`tool_use` input, or an
#: assistant `text` block) may name before the whole block is dropped from the scan (review
#: correction 1): a worker prompt, a card batch, or a `grep -E 'A|B|C'` argument that happens to
#: enumerate several ids is the TOOL CALL's business, not evidence that the assistant was
#: actually WORKING all of them -- letting it count would put every named id at the same "most
#: recent" rank, which is exactly the skew the review flagged. Commit 6471f448's own review found
#: the cap had been applied to `tool_use` only: an assistant TEXT block (a status update naming
#: nine new cards) still counted every id at one position, the identical skew in prose form -- so
#: the cap now covers both assistant block kinds. Owner (human) prose is still exempt: a human
#: actually writing "TRDD-A, TRDD-B, TRDD-C are all done" is a real, if unusual, multi-card
#: mention, and there is no tool call standing in for the human's own words to misattribute.
_TOOL_USE_MENTION_CAP = 3


# A MAXIMAL run of uppercase-base36 characters, length 8 or more -- the candidate extractor for
# a mention, in ANY spelling (`TRDD-<id>`, `#<id>`, or bare `<id>`, review correction 2).
#
# No lookaround, no per-id alternation, and no capturing of `TRDD-`/`#` at all: `-` and `#` are
# themselves non-alnum, so they already break the run on their own -- "TRDD-ABCD1234" tokenizes
# as two runs, "TRDD" (4 chars, discarded below) and "ABCD1234" (8 chars, the candidate), with no
# regex machinery needed to strip the prefix. A run's own greediness gives the boundary check for
# free too: `finditer` always starts a match at the FIRST alnum position it can, so a matched
# run's neighbours (if any) are guaranteed non-alnum -- "XABCD1234" and "ABCD12345" both tokenize
# as ONE 9-char run, which the `len(...) == 8` filter below rejects outright, precisely the
# "can't be a substring of a longer token" contract the old `(?<!...)...(?!...)` lookaround pair
# enforced explicitly. This is also why this is FAST: an earlier version built the alternation of
# every open id straight into the regex (`(?:id1|id2|...|id228)`) plus a lookaround pair, correct
# but not fast -- Python's `re` engine tries alternatives in order with no shared-prefix
# optimization, and lookaround adds its own per-position cost on top. MEASURED on the 258MB/138k-
# line perf transcript this follow-up's own review demanded: the alternation+lookaround version
# took 23.6s against a real 78-open-card board (~8x the 3s budget); the lookaround-only version
# (id-set-independent shape, no alternation) still took 3.8s; this plain run scan measures 2.8s.
# Board size never changes this regex's own cost -- only the SET LOOKUP below (`in open_ids`,
# O(1) average) scales with it, and that lookup only runs for the rare EXACT-8 runs.
#
# UPPERCASE-ONLY IS LOAD-BEARING, not a display convention: `trdd-design-tasks.md`'s id grammar
# is 8-char UPPERCASE base36, and `[A-Z0-9]` matches nothing else -- an id that ever reached this
# scan lowercase or mixed-case (a board loader bug, a hand-edited test fixture) would silently
# never match here, with no error, because the SHAPE check runs and fails BEFORE the `open_ids`
# membership check ever gets a chance to see it (review finding, TRDD-O2FNJ4KW follow-up).
_MENTION_RUN_STR_RE = re.compile(r"[A-Z0-9]{8,}")
_MENTION_RUN_BYTES_RE = re.compile(rb"[A-Z0-9]{8,}")


def _line_mentions_any_open_id(raw: bytes, open_ids: frozenset[str]) -> bool:
    """Cheap first-pass check straight on the RAW transcript line: does it contain an exactly-8
    uppercase-base36 run that is actually one of `open_ids`? Skips `json.loads` + role
    classification for the overwhelming majority of lines (tool_result payloads, board dumps,
    file reads) that carry no such run at all -- replaces the old fixed `b"TRDD-" not in raw`
    prefilter, now also catching the bare-id and `#id` spellings it missed (review correction 2)."""
    for m in _MENTION_RUN_BYTES_RE.finditer(raw):
        token = m.group(0)
        if len(token) != 8:
            continue  # a longer run can never be a bounded id -- see the constant's own comment
        try:
            card_id = token.decode("ascii")
        except UnicodeDecodeError:
            continue
        if card_id in open_ids:
            return True
    return False


def _text_mentions(text: str, open_ids: frozenset[str]) -> set[str]:
    """Every id in `open_ids` mentioned in `text`, spelled `TRDD-<id>`, `#<id>`, or bare `<id>`
    (review correction 2) -- ids not on the board never match, since membership is checked
    against the SET loaded from it, not inferred from shape alone."""
    return {
        m.group(0) for m in _MENTION_RUN_STR_RE.finditer(text)
        if len(m.group(0)) == 8 and m.group(0) in open_ids
    }

# How many of the mentioned/in-flight cards get a title + a STATE head in the facts section.
# TRDD-O2FNJ4KW: a real run measured 19 cards listed (17 stale) with no cap and no relevance --
# 6 is enough to name every card a typical session actually touches without the list itself
# becoming the thing that needs summarizing.
TOP_CARD_COUNT = 6

# Byte cap for the "every other open card" line `_format_other_ids_line` builds (TRDD-O2FNJ4KW,
# review corrections bullet 4). Sized as a small, fixed fraction of `LANE_INJECTION_MAX_BYTES`
# (8192) -- this line names ids only (no titles, no STATE heads), so it never competes with the
# summary body for room; ~300B holds roughly 20 bare 8-char ids before falling back to the
# "and N more" form, comfortably above what any single session's own board churn produces.
_OTHER_IDS_LINE_MAX_BYTES = 300
_OTHER_IDS_LINE_TOOL_HINT = "trddgrep"


def _record_scan_blocks(entry: dict) -> list[tuple[str, str]]:
    """`[(block_kind, text), ...]` worth regex-scanning for a mention out of ONE transcript
    record's `message.content` -- a plain string (kind `"text"`), or the `text`/`tool_use`
    blocks of a content list (kind `"text"` / `"tool_use"` respectively). Returning the kind
    alongside the text (TRDD-O2FNJ4KW follow-up, review correction 1; extended to assistant
    `text` blocks by the 6471f448 review) is what lets the caller cap a single assistant-authored
    block's distinct-id count without also capping OWNER prose -- collapsing every block into one
    joined string, as this used to do, throws that distinction away before the caller ever sees
    it.

    `tool_result` (and any other block kind) is deliberately skipped: it is a board dump, a file
    read, or another tool's own output landing back in the transcript, not something this
    session's owner or assistant WROTE (TRDD-O2FNJ4KW review corrections bullet, `state_head_
    paths` docstring)."""
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return [("text", content)]
    if not isinstance(content, list):
        return []
    blocks: list[tuple[str, str]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            blocks.append(("text", block.get("text", "")))
        elif btype == "tool_use":
            # The assistant's OWN tool call (e.g. a `move <id>` or `edit <id>` argument) is the
            # assistant's own work, unlike the `tool_result` that comes back from running it --
            # `json.dumps` on the raw input is enough to regex-match an id embedded in any
            # argument, string or not.
            blocks.append(("tool_use", json.dumps(block.get("input", ""))))
    return blocks


def _scan_transcript_mentions(transcript_path: str, open_ids: frozenset[str]) -> dict[str, int]:
    """`{card_id: last_line_number_mentioned}` over the WHOLE transcript, one single streamed
    pass (TRDD-O2FNJ4KW) -- never loads the file into memory (measured up to 258MB on this
    project) and never re-parses a line whose raw bytes don't contain any `open_ids` id at all
    (`_line_mentions_any_open_id`), which skips the `json.loads`+`transcript_roles.classify_
    record` cost for the overwhelming majority of lines (tool_result payloads, board dumps, file
    reads) before it's paid. `open_ids` empty (no board, or trddgrep unavailable) short-circuits
    to an empty result without opening the file at all -- there is nothing any mention could
    rank.

    Counts ONLY text that reflects the session's OWN work, per the review corrections on
    TRDD-O2FNJ4KW: the owner's own messages (`transcript_roles.classify_record(entry) ==
    "human"`) and the assistant's own text/tool_use (any assistant record `classify_record`
    doesn't call `"skip"` -- a sidechain subagent turn or hook-injected hidden context). A
    `tool_result` block (a board dump, a file read) never counts even inside an otherwise-human
    or otherwise-assistant record -- `_record_scan_blocks` already drops that block kind -- and
    neither does a `notification`/`system`/`peer`-classified `user`-type record (a task
    notification, a heartbeat fire, a hook's own typed command): those are NOT the session's own
    words either, they are the harness/janitor talking to itself.

    A single ASSISTANT-authored block (`tool_use`, or an assistant `text` block) naming more than
    `_TOOL_USE_MENTION_CAP` DISTINCT open-card ids contributes NONE of them (TRDD-O2FNJ4KW
    follow-up, review correction 1; the text-block half added by the 6471f448 review, which found
    a status update naming nine new cards in prose still counted every one of them at a single
    position) -- a worker prompt, a card batch, or a status update enumerating many ids is not
    evidence the assistant worked all of them just now, and letting it count put every named id
    at the same "most recent" rank. Owner (human) messages are the only thing never capped.

    A malformed line (partial write, non-UTF8) is skipped, not fatal -- one bad line in a
    multi-gigabyte transcript must never abort the whole scan."""
    mentions: dict[str, int] = {}
    if not open_ids:
        return mentions
    try:
        fh = open(transcript_path, "rb")  # noqa: SIM115 -- explicit close below, streamed read
    except OSError:
        return mentions
    with fh:
        for lineno, raw in enumerate(fh):
            if not _line_mentions_any_open_id(raw, open_ids):
                continue
            try:
                entry = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(entry, dict):
                continue
            # Same `type` **or** `message.role` fallback `external_clear._record_text`'s own
            # caller uses -- real transcripts always carry a top-level `type`, but fixtures (and
            # this module's own tests) commonly omit it and set only `message.role`.
            etype = entry.get("type") or (entry.get("message") or {}).get("role") or ""
            if etype not in ("user", "assistant"):
                continue
            role = transcript_roles.classify_record(entry)
            if etype == "user" and role != "human":
                continue
            if etype == "assistant" and role == "skip":
                continue
            for kind, text in _record_scan_blocks(entry):
                ids = _text_mentions(text, open_ids)
                # Cap applies to any ASSISTANT-authored block -- `tool_use` is always the
                # assistant's own call, and a `text` block is capped too when `etype ==
                # "assistant"` (6471f448 review: an assistant status update naming many ids in
                # prose is the same bulk-listing skew as a tool_use argument doing it). A `text`
                # block from an `etype == "user"` (owner) record is never capped.
                if (kind == "tool_use" or etype == "assistant") and len(ids) > _TOOL_USE_MENTION_CAP:
                    continue  # bulk mention -- contributes nothing (review correction 1)
                for card_id in ids:
                    mentions[card_id] = lineno  # last position wins -- later lines overwrite
    return mentions


def _select_and_rank_cards(
    by_col: dict[str, list[tuple[str, str]]], mentions: dict[str, int],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """(top `TOP_CARD_COUNT` cards, every OTHER open card id) -- TRDD-O2FNJ4KW.

    Candidates are every card in a NON-TERMINAL column (`trdd_common.TERMINAL_COLUMNS`), not
    just `STATE_HEAD_COLUMNS` -- the bug this fixes is exactly that a `todo`/`live_auditing`
    card the session actually worked sat outside that narrower set and was never shown. Cards
    the transcript mentions rank first, most-recent mention first; when fewer than
    `TOP_CARD_COUNT` were mentioned at all, the remainder is filled from `STATE_HEAD_COLUMNS`
    (the in-flight work columns) in a fixed `(column, id)` order -- deterministic, so two runs
    over the identical board+transcript always pick the identical top set."""
    open_cards = [
        (card_id, col, title)
        for col, items in by_col.items()
        if col not in trdd_common.TERMINAL_COLUMNS
        for card_id, title in items
    ]
    # Explicit `(column, id)` tiebreak for two cards mentioned at the SAME line (review finding,
    # TRDD-O2FNJ4KW): without it, Python's stable sort falls back to `open_cards`'s own order,
    # which is `by_col.items()` insertion order -- itself a silent dependency on trddgrep's own
    # column-dump rendering order. Naming the tiebreak here means a future trddgrep output-order
    # change cannot silently reorder same-mention-position cards.
    mentioned = sorted(
        (c for c in open_cards if c[0] in mentions),
        key=lambda c: (-mentions[c[0]], c[1], c[0]),
    )
    mentioned_ids = {c[0] for c in mentioned}
    fill = sorted(
        (c for c in open_cards if c[0] not in mentioned_ids and c[1] in STATE_HEAD_COLUMNS),
        key=lambda c: (c[1], c[0]),
    )
    top = (mentioned + fill)[:TOP_CARD_COUNT]
    top_ids = {c[0] for c in top}
    other_ids = sorted(card_id for card_id, _col, _title in open_cards if card_id not in top_ids)
    return top, other_ids


def _format_other_ids_line(
    other_ids: Sequence[str], cap: int = _OTHER_IDS_LINE_MAX_BYTES,
) -> str:
    """One line naming every OTHER open card id, comma-separated, bare (no titles) -- `""` when
    there are none. Past `cap` bytes it stops and ends `and N more (trddgrep)` instead of
    growing without bound (TRDD-O2FNJ4KW review corrections bullet 4): a card the session never
    mentioned is the BOARD's business, not this handoff's, so naming it once on a bounded line
    is enough for a resuming session to run `trddgrep` itself -- every id is still SURFACED,
    never dropped without a trace, only NOT individually titled/state-headed."""
    if not other_ids:
        return ""
    prefix = "other open cards: "
    ids_str = ""
    for i, card_id in enumerate(other_ids):
        candidate = card_id if not ids_str else f"{ids_str}, {card_id}"
        if len(candidate.encode("utf-8")) > cap:
            remaining = len(other_ids) - i
            tail = f"and {remaining} more ({_OTHER_IDS_LINE_TOOL_HINT})"
            return f"{prefix}{ids_str}, {tail}" if ids_str else f"{prefix}{tail}"
        ids_str = candidate
    return f"{prefix}{ids_str}"


def state_head_paths(
    root: Path, sd: Path, transcript: str = "",
) -> tuple[list[str], bool, list[tuple[str, str, str]], str]:
    """Paths of `<state_dir>/jev-heads/<id>.txt`, one per TOP card's STATE block; whether
    trddgrep was unavailable/failing (the caller's cue to note that in the injected header); the
    top `TOP_CARD_COUNT` cards as `(id, column, title)` tuples for `HandoffInputs.cards`, most-
    recently-mentioned first; and one capped line naming every OTHER open card id
    (`_format_other_ids_line`) -- TRDD-O2FNJ4KW superseded the old flat `STATE_HEAD_COLUMNS`
    listing (see that constant's own comment): candidates are now every non-terminal-column
    card, ranked by the session's OWN transcript mentions (`_scan_transcript_mentions`), not by
    which column they happen to sit in. `transcript` defaults to `""` (no scan, mention-based
    ranking degrades to the old in-flight-columns fill order) so a caller that hasn't got one
    yet still gets a deterministic answer. Never reads a TRDD file directly — every touch goes
    through `trddgrep`."""
    exe = shutil.which("trddgrep")
    if not exe:
        return [], True, [], ""
    by_col = _board_ids_by_column(root)
    if by_col is None:
        return [], True, [], ""
    # The mention scan only ever needs to recognize an OPEN card's own id (TRDD-O2FNJ4KW
    # follow-up, review correction 2) -- computed once here and threaded through both the scan
    # (which builds its match/prefilter patterns from it) and the ranking below (which already
    # recomputes the same non-terminal-column filter for its own `(id, column, title)` tuples).
    open_ids = frozenset(
        card_id
        for col, items in by_col.items()
        if col not in trdd_common.TERMINAL_COLUMNS
        for card_id, _title in items
    )
    mentions = _scan_transcript_mentions(transcript, open_ids) if transcript else {}
    top, other_ids = _select_and_rank_cards(by_col, mentions)
    other_line = _format_other_ids_line(other_ids)
    heads_dir = sd / "jev-heads"
    paths: list[str] = []
    # Least-relevant-first (TRDD-O2FNJ4KW review corrections bullet 5): `jev_compaction.py::
    # build_digest` drops STATE heads from the FRONT of the list once the digest overruns its
    # budget, so the MOST relevant top card must be LAST here to be the LAST one dropped.
    for card_id, _col, _title in reversed(top):
        try:
            proc = subprocess.run(
                [exe, "--design-dir", str(root / "design"), "show", card_id],
                cwd=str(root), capture_output=True, text=True, timeout=_TRDDGREP_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        head_text = _extract_state_section(proc.stdout)
        if not head_text:
            continue
        try:
            heads_dir.mkdir(parents=True, exist_ok=True)
            head_path = heads_dir / f"{card_id}.txt"
            state.atomic_write(head_path, head_text)
        except OSError:
            continue
        paths.append(str(head_path))
    return paths, False, top, other_line


def fmt_age(seconds: float) -> str:
    """A short human age phrase — `12m ago`-style, matching the wording the brief's findings
    text expects (e.g. `declined: endpoint unavailable <age> ago`)."""
    seconds = max(0.0, seconds)
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def read_probe_stamp() -> dict | None:
    """The current Jev probe stamp (`jev_compact.py`'s own contract — see its module
    docstring), or `None` if it doesn't exist / isn't valid JSON. Read-only: this lane never
    writes the stamp, only `jev_compact.py` itself does.

    TRDD-RAEGS1D5 owner review finding #7: the stamp lives under `global_state.control_dir()`
    -- MACHINE-WIDE, not per-project (same file every janitor-armed session on this box
    reads/writes). Between one caller's `jev_compact.py compact` failing (which writes this
    stamp) and that SAME caller reading it back a moment later (here), a DIFFERENT session's
    own compaction attempt can legitimately land in between and overwrite it with its own
    kind/reason -- the finding this lane then records could describe the other session's
    failure, not the one that triggered this read. Accepted at LOW severity: the stamp is a
    best-effort diagnostic (which kind of outage, how old), never a correctness input (the
    decline gate re-reads it fresh on its own next call, so a stale/foreign read here cannot
    cause a wrong compact/decline decision, only a momentarily misattributed finding message).
    """
    path = global_state.control_dir() / PROBE_STAMP_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


# TRDD-RAEGS1D5 card 5 measured facts (reports/compaction-replacement/20260923_064108+0200-
# hook-output-experiments.md, 20260923_072806+0200-card5-core.md): the SessionStart hook can
# only inject ~9,000 bytes of stdout before Claude Code truncates it to a 2KB preview, and the
# manual `compose_handoff` default (`external_clear.HANDOFF_MAX_BYTES`, 4096) is deliberately
# unchanged for the manual `/clear` paths -- the AUTOMATIC lane (this hook +
# `summarize_previous_session.py`) instead gets its OWN, larger budget, shared here so both
# callers pass the identical numbers instead of hand-copied magic constants.
LANE_INJECTION_MAX_BYTES = 8192
# Card 5 two-renderings (TRDD-RAEGS1D5): `LANE_BUDGET_TOKENS`/`LANE_DIGEST_TOKENS` are RETIRED
# -- score once, render twice (`jev_compact.py compact`'s own docstring). `--out` (the keyed
# handoff file on disk) now always gets the FULL card-3 budget and the FULL digest; shrinking
# them here used to shrink `--out` too (the card 5 content-fit defect: "the keyed handoff FILE
# on disk is the capped ~4.3 KB document"). Only the SEPARATE `--inject-out` rendering below is
# capped, and its own kept-item budget "aims at the ceiling" -- the byte backstop
# (`LANE_COMPACTED_MAX_BYTES`) is the guarantee, so no separate small token budget is needed for
# it either.
# `jev_compaction.py::compose`'s `max_elided_pointers` (default 40) was the single largest
# line-count contributor once the digest was capped. 12 pointers measured at ~1,732 bytes --
# still enough to name the highest-scoring elided items, far short of showing all 40. Applies
# ONLY to the `--inject-out` rendering, never to `--out`.
#
# 0c607b36 (TRDD-BLGZTHQ9) replaced the tiered injected-selection with `_select_injected`'s one
# priority fill: this cap now bounds ONLY step 7's ORDINARY pointers (`_InjectSelection.pointers`
# -- items that were never a decision/constraint/correction/instruction). A pointer to an
# excluded DECISION item is a separate, capped-by-bytes-not-count reserve held BEFORE this tier
# (`_InjectSelection.decision_pointers`, step 3: up to `_MAX_DECISION_POINTERS` of the newest
# excluded decision items, within `_INJECT_DECISION_POINTER_SHARE` -- 25% -- of the room) and is
# added ON TOP of the `LANE_MAX_ELIDED_POINTERS` ordinary pointers, not counted against it.
LANE_MAX_ELIDED_POINTERS = 12
# The backstop forwarded to `jev_compact.py compact --inject-max-bytes` (via `run_compact`) --
# see `jev_compaction.py::compose`'s own docstring for the drop-oldest-kept-first / drop-lowest-
# score-pointer-first / truncate-digest-last degrade order it applies once this is exceeded.
# Well under `LANE_INJECTION_MAX_BYTES` so `external_clear.compose_handoff` (facts + this + the
# recent-turns tail) still has room for the other two parts of its own single budget.
#
# TRDD-RAEGS1D5 (retune, owner per-item token cap follow-up): raised from 5000 -- measured
# directly (reports/compaction-replacement/): with an empty facts/cards section (the common
# case), `external_clear.compose_handoff`'s OWN room for this summary (its `max_bytes`
# LANE_INJECTION_MAX_BYTES=8192, minus the facts+recent-turns-tail it always reserves first)
# came to ~5250-6442 bytes across the three real transcripts this project keeps for
# acceptance testing (d30bf250 49MB, 4eb7bf5d 258MB, 06f2b2be 4.7MB) -- 5000 left real,
# measured slack unused on all three, which is exactly why the injected copy kept only 2 of
# the ~3+ non-owner items real data showed should fit.
#
# TRDD-RAEGS1D5 (retune follow-up, owner per-item token cap review): a FLAT 6500 was itself the
# wrong fix -- it is bigger than the REAL room on all three transcripts once in-flight cards
# join the facts section, and bigger than 5250/5286 even with an EMPTY one. Any time the flat
# constant overran the real room, `external_clear.compose_handoff`'s own raw byte-slice
# (`raw[:room]`) cut the TAIL of the Jev summary -- the newest kept items and the trailing
# "pointers expand with:" pointer line -- instead of Jev's own priority-aware trim ever
# deciding what to drop. This constant is now the UPPER BOUND ONLY: the real per-call budget is
# `external_clear.compose_handoff_room(...)`, computed BEFORE `jev_compact.py` runs from the
# SAME facts+tail inputs `compose_handoff` itself uses (see that function's own docstring), and
# `inject_max_bytes_for` (below) clamps to whichever of the two is smaller. Kept as a ceiling,
# not deleted, because a session with no cards/findings and a short tail could otherwise hand
# Jev an unbounded budget -- `LANE_INJECTION_MAX_BYTES` (8192) is the true hard cap
# `compose_handoff` enforces regardless, but a companion render that large would be wasted work
# for `compose_handoff` to then still have to trim.
LANE_COMPACTED_MAX_BYTES = 6500

# The FIXED portion (everything except the transcript path itself) of the bytes
# `compose_handoff_room` cannot see yet (no summary exists at the point a lane must call it,
# before `jev_compact.py` has run): a REAL summary's own trailing "pointers expand with: uv run
# --script ... expand --transcript <path> <id>" line, which `jev_compaction.py::compose` always
# emits (see its own source). Measured directly (the exact literal, minus the path): 110 bytes.
# 150 adds a small rounding cushion -- this is what "minus a small safety margin" means, not a
# second guess at the room itself. NOT the whole margin: `inject_max_bytes_for` below adds the
# ACTUAL transcript path's own byte length on top -- a flat margin sized only for this project's
# own (short) state-dir paths would silently under-cover a long one elsewhere (a deep project
# dir, a synced/mirrored home directory) and let `compose_handoff`'s byte-slice fire again,
# invisibly, on exactly the machines least likely to be caught by a test fixture (adversarial
# review finding, TRDD-RAEGS1D5 retune follow-up).
LANE_ROOM_SAFETY_MARGIN_BYTES = 150


def inject_max_bytes_for(room: int, transcript_path: str) -> int:
    """`--inject-max-bytes` for a `jev_compact.py compact` call, from the `room`
    `external_clear.compose_handoff_room` computed for THIS invocation's own facts+tail, minus a
    margin sized to THIS call's own `transcript_path` (the fixed trailer-line overhead plus the
    path's own byte length -- see `LANE_ROOM_SAFETY_MARGIN_BYTES`'s own commentary for why a
    flat margin is not enough). `LANE_COMPACTED_MAX_BYTES` is the upper bound only -- never
    handed to Jev directly, because the real room can be smaller (in-flight cards, findings, a
    long recent-turns tail) than that flat constant, and handing Jev more than `compose_handoff`
    will actually have room for only guarantees its own byte-slice backstop cuts the summary's
    tail again, the exact defect this exists to avoid. `room` may be negative (a facts section
    big enough to consume the whole budget on its own) -- clamped at 0 rather than passed
    through, since a negative `--inject-max-bytes` is not a value `jev_compact.py`'s CLI
    contract defines.

    One copy of this clamp, shared by both lanes that call it (the synchronous SessionStart hook
    and the detached `summarize_previous_session.py`), so neither hand-rolls its own.
    """
    margin = LANE_ROOM_SAFETY_MARGIN_BYTES + len(transcript_path.encode("utf-8"))
    return max(0, min(room - margin, LANE_COMPACTED_MAX_BYTES))


# TRDD-RAEGS1D5 room-floor follow-up. `inject_max_bytes_for` above was measured against an
# EMPTY facts section -- with in-flight TRDD cards (long titles), `external_clear.
# compose_template_handoff` can spend nearly the whole `max_bytes` budget on the facts section
# alone (it only ever stops trimming at ONE remaining card, never zero -- see its own docstring),
# so `room` can reach zero or go negative and `inject_max_bytes_for`'s own `max(0, ...)` silently
# hands `jev_compact.py` `--inject-max-bytes 0`.
#
# That is NOT harmless. Read `jev_compact.py::cmd_compact`'s `--inject-out` render and
# `jev_compaction.py::compose`'s injected branch, which hands off to `_select_injected`. (Cited
# by symbol, never by line number: these files move under every Jev fix, and two line citations
# here were already wrong one commit after they were written.) With `max_bytes=0`, compose's
# `available = ... max(0, max_bytes - baseline)` line yields 0, and `_select_injected`'s own
# `fits()` helper only admits a candidate whose cost is 0 against a
# 0-byte `available` -- so no kept item and no pointer (ordinary or decision) survives admission.
# The digest is already forced
# to `""` for every `--inject-out` render regardless of `--inject-max-bytes` (`cmd_compact`'s
# unconditional `inject_header["digest"] = ""`), so compose's digest-truncation backstop never has
# material to trim either. The `evict_order` eviction loop that follows then has
# nothing left to evict (`kept_order_list`/`shown_elided` are already empty), so it exits
# immediately -- `compose()` returns its bare fixed skeleton (header + "N more items" line +
# trailer) UNBOUNDED by `max_bytes` (there is no assertion or further slice enforcing the 0-byte
# request). NOT a fixed "few hundred bytes" (round-1 wording, corrected here -- round-2 adversarial
# review, TRDD-EFA4P42B correction): the skeleton used to embed `transcript_path` up to FOUR
# times (the header, the "N more items" line, the "Full compacted context" line, and the
# trailer) plus `full_context_path` once more for an inject-mode render, which always sets it.
# TRDD-EFA4P42B cut the header/elided-line/full-context-line copies -- `render()` now embeds
# `transcript_path` ONCE (the trailer) and `full_context_path` once, so the skeleton still
# SCALES with how long these paths are, just by far less (measured 927B skeleton -> 538B, a
# 389B drop, on this project's own ~148-char real paths; a deeply nested project dir or a
# synced/mirrored home directory elsewhere could still push it into the KB range). A tiny
# positive value (1-399)
# degrades the same way: `available` and `_select_injected`'s per-tier caps (`fits()`'s limits,
# all derived from `available`) are still ~0 once the baseline skeleton is subtracted, so the
# injected companion is still just that same (path-scaled) skeleton
# -- a REAL Jev API call was paid for a document containing no actual summary content. A negative
# value is never possible from `inject_max_bytes_for` itself (its own `max(0, ...)` already floors
# it) -- there is no separate handling for it in `jev_compaction.py::compose` either (`available =
# max(0, max_bytes - baseline)` at line 1619 already floors ANY sub-baseline value, negative
# included, to the same 0), so a negative would degrade identically to 0 -- this module never
# sends one either way.
#
# Downstream, `external_clear.compose_handoff` (scripts/lib/external_clear.py:939-959) computes
# ITS OWN room independently from the same facts+tail and, whenever that room is <=400, drops the
# whole compacted-context section rather than slicing it (the `elif trailer:` branch, `external_
# clear.py:946-959) -- so a 0-byte-skeleton companion never gets SLICED, it gets discarded
# whole, silently: the reader sees no summary and no notice that one was ever computed, and the
# API spend that produced it was wasted. RESIDUAL, DISCLOSED, NOT FIXED HERE (round-2 adversarial
# review): the path-scaled skeleton above is `jev_compaction.py::compose`'s own behaviour, a file
# out of this task's scope -- on an unusually long transcript/out-file path, a skeleton bigger than
# `compose_handoff`'s real room (rather than smaller than it) could in principle get SLICED instead
# of discarded whole. This module's own margin (`LANE_ROOM_SAFETY_MARGIN_BYTES`, scaled 1x by
# `transcript_path`'s length) cannot fix this: it bounds what THIS module REQUESTS, not what
# `jev_compaction.py::compose` actually RENDERS when the request is too small to admit real
# content. Flagged for whichever worker owns `jev_compaction.py` next; not reproduced in this
# module's own tests, which use short, fixed-literal paths throughout.
#
# ROUND 2 (coordinator review of commit 44fdec8c -- two corrections to round 1's design above):
#
# (1) THE CARD LIST IS NEVER DROPPED, ONLY THE TITLES. Round 1 dropped whole cards
# (`inputs.cards[:-1]`, one at a time) to reclaim room -- but the card LIST is how a resumed
# session finds its in-flight TRDDs, and a card-heavy facts section is exactly the situation a
# BUSY session is in: dropping ids to save space is throwing away the one thing a resuming session
# cannot cheaply regenerate, to save a few dozen bytes a bare id line barely needs (`TRDD-
# XXXXXXXX` is ~14 bytes on its own; the id+column together render in well under 40). `_cards_
# with_title_cap` below truncates every card's TITLE (never its id or column) toward "" instead --
# the least load-bearing part of the line -- so every id survives no matter how much trimming is
# needed.
#
# TRDD-O2FNJ4KW (2026-09-24) partially SUPERSEDES this ruling's SCOPE, not its substance: the
# flat, unranked, uncapped `STATE_HEAD_COLUMNS` card list this ruling used to protect no longer
# reaches this function at all -- `state_head_paths` now hands `trim_cards_for_room` only the
# top `TOP_CARD_COUNT` (6) cards, ranked by the session's OWN transcript mentions, with every
# OTHER open card named once on a separate, independently-capped one-line list
# (`_format_other_ids_line`) instead. "Never drop a card, only shrink its title" still holds,
# unchanged, for that top-6 set -- this function's own behaviour below is not touched by
# TRDD-O2FNJ4KW at all. What changed is upstream: which cards are relevant enough to EARN a
# title and a slot in `inputs.cards` in the first place, and the fact that a card that doesn't
# earn one is still named (a bare id), never silently absent.
#
# (2) THE RETURNED VALUE IS NEVER FORCED ABOVE THE NATURALLY-COMPUTED ONE. Round 1's final
# `return inputs, max(LANE_MIN_INJECT_BYTES, inject_max_bytes)` was itself unsafe: `inject_max_
# bytes_for`'s own margin subtraction is what makes its return value provably <= `external_clear.
# compose_handoff`'s REAL room for this exact `inputs`/`tail`/`max_bytes` (that margin is the
# whole point of `LANE_ROOM_SAFETY_MARGIN_BYTES` -- see `inject_max_bytes_for`'s own docstring).
# Forcing that value UP to a flat 800 whenever it fell short -- even when the natural value was
# already a SAFE, smaller positive number -- handed `jev_compact.py` a budget bigger than
# `compose_handoff` actually has room for. A well-behaved Jev render fills close to whatever
# budget it is given; a companion sized toward 800 bytes arriving at a `compose_handoff` call
# whose real room is smaller (say, 656) is EXACTLY what `compose_handoff`'s own `raw[:room]` slice
# (external_clear.py:941-944, gated on `room > 400`) exists to cut -- the identical defect this
# whole TRDD chain exists to eliminate, just moved one level down. There is no flat floor that is
# always safe, because safety depends on how far below `LANE_MIN_INJECT_BYTES` the natural value
# already is -- proven below by a fixture (225 cards, empty titles after trimming) whose natural
# room lands at 656 bytes: a companion sized to round 1's flat 800 DOES get sliced against it; one
# sized to the natural, unforced value does not.
#
# THE CORRECTED CONTRACT: `LANE_MIN_INJECT_BYTES` is a TARGET the title-shortening loop tries to
# reach, never a value the return is forced UP to. The only value ever added on top of the
# naturally-computed (and therefore margin-safe) `inject_max_bytes_for` result is `max(1, ...)` --
# bumping an exact `0` up to `1` changes NOTHING about what `jev_compact.py` actually renders
# (both are below any real transcript's own skeleton `baseline`, so `compose()` renders the
# identical bare skeleton either way -- see the round-1 trace above), it only satisfies "never
# pass 0 or negative" literally, without inflating the requested budget past what `compose_handoff`
# can actually use. Whenever every title is already empty (every id kept) and the natural value is
# STILL below `LANE_MIN_INJECT_BYTES`, that smaller value is returned AS-IS, not overridden -- the
# residual "summary may come out short or empty" outcome from round 1's disclosed finding #1 still
# applies in that case -- MORE OFTEN than round 1's own code would have hit it, in fact (round 1's
# inflated-but-unsafe 800 sometimes accidentally produced a usable body where the true room was,
# say, 750; round 2 requests the true, smaller room instead, which degrades to the empty skeleton
# more readily -- adversarial review, round 2 self-review) -- but the summary is never sliced by
# this module handing out a number bigger than `compose_handoff` can actually use, which is the
# one guarantee this module owns.
LANE_MIN_INJECT_BYTES = 800


def _cards_with_title_cap(
    cards: Sequence[tuple[str, str, str]], cap: int,
) -> tuple[tuple[str, str, str], ...]:
    """Every card's id/column kept verbatim; its title truncated to at most `cap` characters
    (`cap=0` empties it, never removes the card). The title is decoration; the id (and the STATE
    block it points at, via `trddgrep show <id>`) is the one thing a resuming session cannot
    regenerate for free -- see the round-2 module comment above `LANE_MIN_INJECT_BYTES`.

    A `cap=0` line renders (via `external_clear.compose_template_handoff`, untouched by this fix)
    as `"- TRDD-<id> (`<col>`) -- "` -- a dangling em dash with nothing after it. Cosmetically odd
    (adversarial review, round 2 self-review), but harmless: the id is fully intact and resolvable
    (`trddgrep show <id>`), which is the only thing this function promises to preserve."""
    return tuple((cid, col, title[:cap]) for cid, col, title in cards)


def trim_cards_for_room(
    inputs: external_clear.HandoffInputs,
    *,
    now_iso: str,
    tail: Sequence[str],
    transcript_path: str,
    max_bytes: int = LANE_INJECTION_MAX_BYTES,
    source: str,
) -> tuple[external_clear.HandoffInputs, int]:
    """(possibly title-shortened `inputs`, the `--inject-max-bytes` to pass) for THIS call's own
    facts+tail -- the one place both lanes enforce the room floor, so neither hand-rolls its own
    (same reason `inject_max_bytes_for` above is shared). See `LANE_MIN_INJECT_BYTES`'s own
    (round 2) comment for why title-shortening -- never card-dropping -- and a never-inflating
    return are the chosen fix.

    Every card's id SURVIVES, always: only titles shrink, by halving a shared length cap (applied
    to every card at once) until room reaches the `LANE_MIN_INJECT_BYTES` target or every title is
    empty. The returned `inject_max_bytes` is never forced above the naturally-computed, margin-
    safe value from `inject_max_bytes_for` -- only an exact `0` is bumped to `1` (see the module
    comment above for why that specific, and only that, substitution cannot enlarge what
    `jev_compact.py` actually renders).

    The caller composes its OWN final `HandoffInputs` (a different `trigger` per branch) for the
    template/failure path -- pass this call's returned `inputs` (not the original) to whatever
    `compose_handoff` call actually injects the summary, so the room this function measured stays
    the room `compose_handoff` itself later computes; a template-only failure path that never
    calls `compose_handoff` should keep using the ORIGINAL, untouched inputs instead -- shortening
    titles buys it nothing there (no summary is being sized) and would only degrade the template's
    own card list for no reason.
    """
    def _room_and_inject(candidate: external_clear.HandoffInputs) -> int:
        room = external_clear.compose_handoff_room(
            candidate, now_iso=now_iso, tail=tail, max_bytes=max_bytes, source=source,
        )
        return inject_max_bytes_for(room, transcript_path)

    inject_max_bytes = _room_and_inject(inputs)
    if inject_max_bytes < LANE_MIN_INJECT_BYTES and inputs.cards:
        # `original_cards` -- NEVER `inputs.cards` once the loop has run once -- is what every
        # iteration re-caps. `cap` only ever decreases (`cap //= 2`), so re-slicing the ORIGINAL
        # titles each time is not merely equivalent to re-slicing the PREVIOUS iteration's
        # already-capped titles (`s[:a][:b] == s[:b]` whenever `b <= a`, which a monotonically
        # shrinking `cap` guarantees) -- it makes that guarantee true BY CONSTRUCTION rather than
        # by an invariant a future edit could break without this function visibly changing shape
        # (adversarial review finding, round 2 self-review).
        original_cards = inputs.cards
        cap = max((len(title) for _cid, _col, title in original_cards), default=0)
        while inject_max_bytes < LANE_MIN_INJECT_BYTES and cap > 0:
            cap //= 2
            candidate = dataclasses.replace(
                inputs, cards=_cards_with_title_cap(original_cards, cap),
            )
            candidate_inject = _room_and_inject(candidate)
            inputs, inject_max_bytes = candidate, candidate_inject

    # Never inflated above the naturally-computed value -- see the round-2 module comment above
    # for why doing so would hand `jev_compact.py` a budget `compose_handoff`'s own room cannot
    # actually fit, re-enabling the exact slicing this fix exists to prevent. `0` alone is bumped
    # to `1`, which changes nothing about what `jev_compact.py` renders either way.
    return inputs, max(1, inject_max_bytes)


def record_finding(*, sev: str, code: str, msg: str) -> None:
    """The choke point for every non-zero-exit finding below: record it and, if this project
    is the one it happened in, print the drift line so the heartbeat's quiet-filter can surface
    it. A ledger failure must never break the caller (`findings_ledger.record` never raises,
    but the print/log around it is still guarded for the same reason every other caller in
    this codebase guards it)."""
    try:
        line = findings_ledger.record(sev=sev, code=code, src="jev-compaction", msg=msg, ref="")
        if line:
            print(line)
    except Exception as exc:  # noqa: BLE001 - a ledger failure must never break the caller
        state.log_line(_LOG, f"could not record finding {code!r}: {exc!r}")


def handle_nonzero_exit(
    proc: subprocess.CompletedProcess[str] | None, *, timed_out: bool, sd: Path,
) -> None:
    """Map `jev_compact.py compact`'s exit code (or a `TimeoutExpired`) to a finding, per
    docs_dev/jev-card3c-brief.md's C1 exit-code table plus coordinator amendments: a
    `kind=unreachable` stamp (a transport failure with no HTTP response at all -- offline,
    DNS, TLS) is HIGH and names the LANE; a `kind=rate_limited` stamp (HTTP 429) is MEDIUM and
    names the provider's own retry window; exit 127 (the shell's "command not found") is HIGH
    and names the likely cause -- a launchd/cron-started session inheriting a bare PATH with no
    `uv` on it (card 3 C2 amendment). Never writes/releases the hold — the fact-only template
    injection on TTL expiry is today's (unchanged) fallback behaviour; this function only
    records WHY.

    BOTH `kind` and `retry_after_s` are read DEFENSIVELY off the stamp (coordinator amendment):
    a stamp with no `kind` at all (or `rate_limited` with no `retry_after_s`) degrades to the
    `unavailable` wording rather than crashing or guessing a number — the generic outage
    text is always a safe fallback, never a more alarming one.
    """
    if timed_out or proc is None:
        # TRDD-RAEGS1D5 R5: this used to hardcode "within 120s" -- true only for the old
        # single fixed-timeout callers. `run_compact_with_fallback`'s retry loop calls
        # `run_compact` with a VARIABLE `timeout=min(120, remaining)` on each attempt, so a
        # fixed number here would misreport the actual bound of the attempt that timed out.
        record_finding(
            sev="HIGH", code="JEV-COMPACT-FAILED",
            msg="[jev-compaction] jev_compact failed (timeout): no response within the "
            "attempt's own timeout — fact-only context injected",
        )
        return

    stderr_tail = (proc.stderr or "").strip()[-200:]

    if proc.returncode == EXIT_COMMAND_NOT_FOUND:
        # exec-by-path resolves `#!/usr/bin/env -S uv run ...` through the SPAWNING process's
        # own PATH, not this repo's -- a launchd/cron-started session can legitimately inherit
        # one with no `uv` on it, which is a config problem to fix, not a jev outage to wait out.
        record_finding(
            sev="HIGH", code="JEV-COMPACT-FAILED",
            msg="[jev-compaction] jev_compact failed (exit 127): uv not on PATH for this "
            "session (a launchd/cron-started session may inherit a bare PATH) — fact-only "
            "context injected",
        )
        return

    if proc.returncode == EXIT_DECLINED_UNAVAILABLE:
        stamp = read_probe_stamp() or {}
        reason = stamp.get("reason") or "unknown"
        age_s = time.time() - float(stamp.get("ts", time.time()))
        stamp_kind = stamp.get("kind")
        retry_after = stamp.get("retry_after_s") if stamp_kind == "rate_limited" else None
        if retry_after is not None:
            record_finding(
                sev="MEDIUM", code="JEV-RATE-LIMITED",
                msg=f"[jev-compaction] provider rate limit — compactions retry after "
                f"{retry_after}s — fact-only context injected",
            )
            return
        # Card 5 two-renderings (TRDD-RAEGS1D5, item 5): a `kind="unreachable"` decline (no HTTP
        # response ever came back -- offline, DNS, TLS) is a DIFFERENT fact than a real
        # `kind="unavailable"` outage (a 5xx response) -- saying "unavailable" for both erased
        # that distinction right where a reader would look for it. Any other/missing kind still
        # reads as the generic "unavailable" wording (defensive, per the stamp docstring above).
        word = "unreachable" if stamp_kind == "unreachable" else "unavailable"
        record_finding(
            sev="LOW", code="JEV-COMPACT-DECLINED",
            msg=f"[jev-compaction] declined: endpoint {word} {fmt_age(age_s)} ago "
            f"({reason}) — fact-only context injected",
        )
        return

    if proc.returncode == EXIT_DECLINED_NO_DIGEST:
        record_finding(
            sev="LOW", code="JEV-COMPACT-NO-DIGEST",
            msg="[jev-compaction] declined: nothing to digest — fact-only context injected",
        )
        return

    if proc.returncode == EXIT_JEV_ERROR:
        stamp = read_probe_stamp() or {}
        reason = stamp.get("reason") or stderr_tail or "unknown"
        # A stamp with no `kind` field at all reads as the generic outage shape -- defensive,
        # per the amendment, never an escalation to a more alarming wording it never claimed.
        kind = stamp.get("kind") or "unavailable"

        if kind == "rate_limited":
            retry_after = stamp.get("retry_after_s")
            if retry_after is not None:
                record_finding(
                    sev="MEDIUM", code="JEV-RATE-LIMITED",
                    msg=f"[jev-compaction] provider rate limit — compactions retry after "
                    f"{retry_after}s — fact-only context injected",
                )
                return
            kind = "unavailable"  # no retry_after_s -- fall back to unavailable's own text

        if kind == "unavailable":
            # TRDD-RAEGS1D5 R5: "30 min" was the pre-owner-decision TTL; PROBE_FAIL_TTL_S is
            # now 5 min (jev_compact.py), so this wording would otherwise mislead a reader
            # about how long the next automatic attempt is actually held back.
            record_finding(
                sev="MEDIUM", code="JEV-SCORER-UNAVAILABLE",
                msg=f"[jev-compaction] scorer unavailable: {reason} — fact-only context "
                "injected; compactions decline for 5 min",
            )
            return
        if kind == "auth":
            key = hashlib.sha256(reason.encode("utf-8")).hexdigest()[:16]
            msg = record_once_per_reason(sd, key, reason)
            if msg:
                record_finding(sev="HIGH", code="JEV-AUTH-REJECTED", msg=msg)
            return
        if kind == "unreachable":
            record_finding(
                sev="HIGH", code="JEV-SCORER-UNREACHABLE",
                msg=f"[jev-compaction] scorer unreachable from this lane ({LANE}): {reason} "
                "— fact-only context injected",
            )
            return
        # kind == "budget" or "blocked" (TRDD-1ETALGDG -- a Cloudflare edge block that
        # persisted past every split-retry `score_items` tried), or any other unrecognized
        # string — scoped to THIS attempt, not a known whole-endpoint outage shape; never
        # decline the next one on it. No dedicated branch needed: `reason` already carries
        # the specific "blocked"/"budget" detail, and this generic wording is accurate for
        # both.
        record_finding(
            sev="HIGH", code="JEV-COMPACT-FAILED",
            msg=f"[jev-compaction] jev_compact failed (exit {proc.returncode}): {reason}",
        )
        return

    # Any other exit code is a bug per the CLI's own contract — one flat space, nothing else
    # is meant to happen.
    record_finding(
        sev="HIGH", code="JEV-COMPACT-FAILED",
        msg=f"[jev-compaction] jev_compact failed (exit {proc.returncode}): {stderr_tail}",
    )


def record_once_per_reason(sd: Path, key: str, reason: str) -> str | None:
    """The `kind=auth` finding text, or `None` when this exact reason was already surfaced
    (coordinator amendment: dedupe auth-rejection findings, not every other kind — an auth
    failure is a standing config problem, not a fresh event each SessionStart)."""
    msg = (
        f"[jev-compaction] provider key rejected: {reason} — set OPENROUTER_API_KEY / "
        "CLAUDE_PLUGIN_OPTION_JEV_PROVIDER"
    )
    seen_file = sd / AUTH_SEEN_FILE
    return dedupe.emit_once(seen_file, key, msg)


def run_compact(
    plugin_root: Path, *, transcript: str, out_path: Path, session_key: str,
    heads_args: list[str], sd: Path, timeout: int = 120, budget_tokens: int | None = None,
    digest_tokens: int | None = None, max_elided_pointers: int | None = None,
    inject_out_path: Path | None = None, inject_max_bytes: int | None = None,
    no_decline: bool = False,
) -> tuple[subprocess.CompletedProcess[str] | None, bool]:
    """Exec `jev_compact.py compact` BY PATH (it is git-tracked 100755, own shebang runs it) and
    return `(proc, timed_out)`. On a real exit-0 success, ALSO parses and records the
    `blocked=`/`malformed=` counts off the summary line (`parse_blocked_summary`,
    `parse_malformed_summary`, `record_blocked_finding`) -- this is now the ONE place both
    real-world callers (`on-session-start-post-clear-compact.py`'s hook and
    `run_compact_with_fallback` below) get this, since TRDD-DQXMND59 stage 3b found the hook
    calls `run_compact` directly and never reads `proc.stdout` itself, so both findings were
    silently lost on the production post-clear path even though `jev_compact.py` had already
    printed them. `sd` (the project state dir) is required for exactly this -- it is what
    `record_blocked_finding` writes its dedupe/day-cap files under, and every real caller
    already has one on hand (`state.state_dir()`), so there is no good default to fall back to.
    `timeout` defaults to 120s (jev's own client retries 3x with
    <=8s backoff on a 15s request timeout; six parallel batches bound the worst case near 70s)
    for a bare caller that passes none -- the sync hook passes its own smaller
    `_RUN_COMPACT_TIMEOUT_S` (60s) explicitly, and `run_compact_with_fallback` (below) passes
    the WHOLE remaining retry budget explicitly (orchestrator correction 2026-09-23, measured:
    a 49MB transcript took 168s for one real run, well past this 120s default), so neither of
    the two real production callers actually relies on this default. A `TimeoutExpired` is a
    bug exit here -- THIS FUNCTION itself never retries on it, so a caller that wants to (only
    `run_compact_with_fallback`, per owner decision 2026-09-23 -- and it deliberately never
    retries a timeout either, only the FAST transient failure kinds) makes the SAME bounded-
    budget decision explicitly, one call at a time, rather than this function silently looping
    and risking landing past the hold's own deadline on its own.

    `budget_tokens`/`digest_tokens`, when given, are forwarded as `--budget-tokens`/`--digest-
    tokens` -- unset (the automatic lane's own default now, card 5 two-renderings) keeps
    `jev_compact.py`'s own card-3 defaults, so `--out` (the keyed handoff file) always gets the
    FULL document and digest, never shrunk by an injection budget.

    `inject_out_path`/`max_elided_pointers`/`inject_max_bytes`, when given, are forwarded as
    `--inject-out`/`--max-elided-pointers`/`--inject-max-bytes` -- a SECOND, capped rendering of
    the SAME scored items, written alongside `--out` for a caller that needs to inject a
    size-bounded companion document (the SessionStart hook) rather than the full one.

    `no_decline`, when true, forwards `--no-decline` -- bypasses `jev_compact.py compact`'s own
    early decline gate for `kind="unavailable"`/`"unreachable"`, NEVER `"rate_limited"` (owner
    decision 2026-09-23 R1; card 5 two-renderings, item 5, originally bypassed `"unreachable"`
    only). Set by an explicit compact-now request, AND by `run_compact_with_fallback` (below)
    on every retry inside its own bounded 5-minute budget -- without it, the first real
    failure would stamp a decline that fast-declines every later retry in this same window."""
    cmd = [
        str(plugin_root / "scripts" / "jev_compact.py"), "compact",
        "--transcript", transcript, "--out", str(out_path),
        "--session-key", session_key, *heads_args,
    ]
    if budget_tokens is not None:
        cmd += ["--budget-tokens", str(budget_tokens)]
    if digest_tokens is not None:
        cmd += ["--digest-tokens", str(digest_tokens)]
    if max_elided_pointers is not None:
        cmd += ["--max-elided-pointers", str(max_elided_pointers)]
    if inject_out_path is not None:
        cmd += ["--inject-out", str(inject_out_path)]
    if inject_max_bytes is not None:
        cmd += ["--inject-max-bytes", str(inject_max_bytes)]
    if no_decline:
        cmd += ["--no-decline"]
    try:
        proc = subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return None, True
    if proc.returncode == EXIT_OK:
        # TRDD-DQXMND59 stage 3b item A: moved here from `run_compact_with_fallback`'s own
        # success branch (the ONE function both real callers share) -- see this function's own
        # docstring for why the hook losing both records was the bug.
        blocked, blocked_digest = parse_blocked_summary(proc.stdout or "")
        record_blocked_finding(sd, blocked=blocked, blocked_digest=blocked_digest)
        malformed = parse_malformed_summary(proc.stdout or "")
        if malformed:
            state.log_line(
                _LOG, f"jev compact skipped {malformed} malformed transcript line(s)",
            )
    return proc, False


# --------------------------------------------------------------------------------------- #
# Retry-then-llm-ext fallback (TRDD-RAEGS1D5, owner decision 3 of 2026-09-23 + advisor
# review 20260923_191616+0200-jev-fallback-advisor.md, R1-R5 + recommendations).
#
# Owner's own words: "if jev is not working after 5 minutes retries, the llm-ext compaction
# function must be called as a fallback ... but llm-ext must be used if jev is unavailable
# after 5 minutes." Also: no failure may pause compaction for 30 minutes.
#
# LIVES HERE, NOT IN summarize_previous_session.py, so the entry point stays a thin
# orchestrator (its own docstring: "THIN ON PURPOSE") and BOTH callers of `run_compact` --
# the pane-keyed detached lane AND the no-pane-key path -- get the identical retry+fallback
# behaviour by calling this one function instead of duplicating the loop.
# --------------------------------------------------------------------------------------- #

# Skip a Jev attempt entirely once less than this remains of the retry budget: a real compact
# is ~13s on a 4.6MB transcript, up to ~70s worst case (measure report) -- a 5-30s remainder
# cannot possibly complete one, so spend it on the llm-ext fallback instead (advisor §4).
_MIN_JEV_ATTEMPT_S = 30.0
# Sleep between retries after a FAST transient (non-rate-limited) failure -- kind unavailable/
# unreachable/unknown, which `jev_compact.py` returns in seconds, never a `run_compact`
# subprocess TIMEOUT (that one never retries at all -- see `run_compact_with_fallback`'s own
# docstring, orchestrator correction 2026-09-23: measured 168s for a 49MB transcript, so a
# single attempt can legitimately span the WHOLE remaining budget, and re-running identical
# deterministic work after it times out would only burn what budget is left proving the same
# thing again). Arbitrary but harmless (advisor §5).
_TRANSIENT_RETRY_SLEEP_S = 15.0
# The outer bound added around the llm-ext fallback subprocess (advisor §4 "minor"): its own
# internal timeout is `llm_ext_timeout_s`, but a `uv`/launcher hang BEFORE that timer even
# starts could otherwise outlive the 15-minute hold entirely.
_LLM_EXT_OUTER_SLACK_S = 15.0

# Sources `run_compact_with_fallback` can report success from.
SOURCE_JEV = "jev"
SOURCE_LLM_EXT = "llm-ext"
SOURCE_FAILED = "failed"

# `kind`s (from the probe stamp) that mean "retrying THIS attempt again cannot help" --
# stop the loop and fall back at once rather than spending more of the 5-minute budget.
_NON_RETRYABLE_KINDS = frozenset({"auth", "budget", "invalid"})


# --------------------------------------------------------------------------------------- #
# `blocked=N` visibility (TRDD-1ETALGDG followup): a compaction that succeeds (exit 0) but
# had to pointer some items -- a provider firewall block or an oversized batch that
# survived every split retry `jev_compaction.py::score_items` tried -- is otherwise
# invisible to this lane's own findings: `handle_nonzero_exit` above only ever fires on a
# NON-zero exit. `jev_compact.py`'s own `compacted items=...` success line now carries
# `blocked=N blocked_digest=<hex>` (jev_compact.py::cmd_compact); this parses it and records
# ONE LOW `JEV-COMPACT-BLOCKED` finding, reusing `record_finding` the same way every other
# finding in this module does.
# --------------------------------------------------------------------------------------- #

_BLOCKED_LINE_RE = re.compile(r"\bblocked=(\d+)\s+blocked_digest=([0-9a-f]*)")

# Dedup is CONTENT-based, not session-based (coordinator amendment, 2026-09-23): the SAME
# poisoning content (e.g. one recurring transcript entry a provider firewall always blocks)
# recurs in EVERY new session of this repo, each with a DIFFERENT set of item ids (ids embed
# the transcript's own uuids, which differ per session) -- a session-keyed dedupe would never
# suppress the repeat. `blocked_digest` is a hash of the blocked items' own TEXT (never the
# text itself, matching the codebase's existing cf_ray/body_sha256 pattern -- see
# jevctx.openrouter.JevBlockedError), sorted before hashing so batch-split ORDER (which
# varies run to run) never changes the digest for identical content. `emit_once` against a
# seen-file under the PROJECT state dir (`sd`, never per-session) then suppresses the exact
# same content forever -- the same mechanism `record_once_per_reason` already uses for
# `kind=auth`.
#
# On top of the content dedupe, a separate one-per-day cap on the CODE itself (regardless of
# digest) bounds how often this fires even when the blocked content keeps changing -- a LOW-
# severity visibility finding is not worth repeating more than once a day no matter how many
# distinct poison items a flaky firewall produces on a given day.
BLOCKED_SEEN_FILE = "jev-blocked-finding-seen"
_BLOCKED_LAST_EMIT_FILE = "jev-blocked-finding-last-emit.ts"
_BLOCKED_DAY_CAP_S = 86400.0


# TRDD-DQXMND59 stage 3, item B: `jev_compact.py compact`'s summary line also carries
# `malformed=N` (transcript lines the walk had to skip -- a half-written last line, a
# non-UTF-8 byte, a line that parsed to non-object JSON) since 2729b1cb, but nothing in this
# lane ever read it: `_BLOCKED_LINE_RE` above only captures `blocked=`/`blocked_digest=`, so a
# nonzero `malformed` count reached this process's stdout and was then simply discarded --
# production silence identical in shape to the CLI-only silence 2729b1cb itself fixed. A
# SEPARATE regex/function, not a widened `_BLOCKED_LINE_RE`, so `parse_blocked_summary`'s own
# existing `(count, digest)` contract (and its tests) stay untouched.
_MALFORMED_LINE_RE = re.compile(r"\bmalformed=(\d+)")


def parse_malformed_summary(stdout: str) -> int:
    """The `malformed=N` count off `jev_compact.py compact`'s own `compacted items=...` stdout
    summary line, or `0` when the line is missing/malformed -- same best-effort contract as
    `parse_blocked_summary` (a parse miss means "nothing to report", never an error)."""
    m = _MALFORMED_LINE_RE.search(stdout)
    if not m:
        return 0
    return int(m.group(1))


def parse_blocked_summary(stdout: str) -> tuple[int, str]:
    """`(blocked_count, blocked_digest)` off `jev_compact.py compact`'s own `compacted
    items=...` stdout summary line, or `(0, "")` when the line is missing/malformed (an
    older `jev_compact.py` without this field, or stdout captured mid-write) -- a best-
    effort visibility signal, never a correctness input, so a parse miss just means "nothing
    to report", not an error."""
    m = _BLOCKED_LINE_RE.search(stdout)
    if not m:
        return 0, ""
    return int(m.group(1)), m.group(2)


def _blocked_day_cap_spent(sd: Path, *, now_fn: Callable[[], float] = time.time) -> bool:
    """True iff a `JEV-COMPACT-BLOCKED` finding already fired within the last
    `_BLOCKED_DAY_CAP_S` -- read-only, never mutates (the caller stamps
    `_mark_blocked_day_spent` only right after it actually emits one)."""
    try:
        last = float((sd / _BLOCKED_LAST_EMIT_FILE).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return now_fn() - last < _BLOCKED_DAY_CAP_S


def _mark_blocked_day_spent(sd: Path, *, now_fn: Callable[[], float] = time.time) -> None:
    try:
        sd.mkdir(parents=True, exist_ok=True)
        state.atomic_write(sd / _BLOCKED_LAST_EMIT_FILE, str(now_fn()))
    except OSError:
        pass  # best-effort -- see record_finding's own guard rationale


def record_blocked_finding(
    sd: Path, *, blocked: int, blocked_digest: str, now_fn: Callable[[], float] = time.time,
) -> None:
    """Record ONE LOW `JEV-COMPACT-BLOCKED` finding for a compaction that succeeded (exit 0)
    but had to pointer some items -- see the module-level comment above for the two dedupe
    layers this applies (content digest, forever; the code itself, once a day). A no-op when
    `blocked <= 0` -- nothing to report."""
    if blocked <= 0:
        return
    if _blocked_day_cap_spent(sd, now_fn=now_fn):
        return
    key = f"JEV-COMPACT-BLOCKED:{blocked_digest}"
    msg = (
        f"[jev-compaction] {blocked} item(s) could not be scored (provider firewall or "
        "oversize) and were rendered as pointers instead -- verbatim guarantee held, "
        "nothing was inlined or altered"
    )
    emitted = dedupe.emit_once(sd / BLOCKED_SEEN_FILE, key, msg)
    if emitted:
        record_finding(sev="LOW", code="JEV-COMPACT-BLOCKED", msg=emitted)
        _mark_blocked_day_spent(sd, now_fn=now_fn)


def _sleep_for_kind_or_break(
    stamp: dict, *, deadline: float, now_fn: Callable[[], float], sleep_fn: Callable[[float], None],
) -> bool:
    """For a `kind="rate_limited"` stamp: sleep out the server's own `Retry-After` (floor 5s)
    when it fits inside the remaining budget, or signal "stop, fall back now" when it does not
    (R3: falling back immediately is strictly better than sleeping to the deadline only to
    learn what the stamp's own `retry_after_s` already told us). Returns True to keep
    retrying, False to break out of the loop."""
    remaining = deadline - float(now_fn())
    if remaining <= 0:
        return False
    retry_after = stamp.get("retry_after_s")
    wait = max(float(retry_after), 5.0) if isinstance(retry_after, (int, float)) else 5.0
    if wait > remaining:
        return False  # R3: the decline window outlasts the retry budget -- fall back now
    sleep_fn(min(wait, remaining))
    return True


def _run_llm_ext_fallback(
    plugin_root: Path, *, transcript: str, timeout_s: float,
) -> tuple[bool, str]:
    """EXEC (never import) `scripts/llm_ext_compact.py` -- the llm-ext equivalent of how this
    lane execs `jev_compact.py` BY PATH, for the same reason: `tests/test_jev_boundary.py`
    forbids this stdlib-only module from importing `llm_ext_summary` in-process (owner
    decision 2026-09-23: the automatic lane may EXEC llm-ext, never import it).

    `timeout_s + _LLM_EXT_OUTER_SLACK_S` bounds the whole subprocess -- `llm_ext_compact.py`
    already bounds its OWN internal attempt at `timeout_s`; the slack only guards against a
    `uv`/launcher hang before that internal timer starts (advisor §4).

    Runs in ITS OWN process group (`start_new_session=True`) and, on the outer timeout, kills
    the WHOLE group (`os.killpg`), not just this one child (owner review finding #4,
    TRDD-RAEGS1D5). `llm_ext_compact.py`'s own shebang is `uv run --script`, which execs `uv`,
    which in turn launches the real llm-ext binary as ITS OWN child -- two more generations of
    process below the one `subprocess.run(cmd, timeout=...)` used to reach. A plain
    `Popen.kill()` (or `subprocess.run`'s own timeout handling, which only signals the direct
    child) leaves those grandchildren running past the hold's own deadline with nothing left
    to reap them. `start_new_session=True` makes this process (and everything IT spawns,
    unless one of them calls `setsid` itself) share one process group whose id equals this
    child's own pid, so `os.killpg(proc.pid, ...)` reaches the whole tree in one signal.
    """
    if timeout_s < _MIN_JEV_ATTEMPT_S:
        # Not enough of the hold left to plausibly get a real llm-ext summary back --
        # degrade straight to the mechanical template rather than spend the remainder on a
        # call almost certain to be killed mid-flight.
        return False, f"llm-ext fallback skipped: only {timeout_s:.0f}s left in the hold"
    script = plugin_root / "scripts" / "llm_ext_compact.py"
    cmd = [str(script), "--transcript", transcript, "--timeout-s", str(int(timeout_s))]
    try:
        proc = subprocess.Popen(  # noqa: S603 - explicit args, no shell
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
    except OSError as exc:
        return False, f"llm-ext fallback spawn failed: {exc!r}"
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s + _LLM_EXT_OUTER_SLACK_S)
    except subprocess.TimeoutExpired:
        try:
            if sys.platform == "win32":
                # os.killpg/SIGKILL don't exist on Windows (no POSIX process groups) --
                # start_new_session=True above is a no-op there too, so there is no group to
                # reach anyway; Popen.kill() (TerminateProcess) at least stops the direct
                # child. Grandchildren (uv's own children) going unreaped on this platform is
                # a pre-existing gap this fix does not attempt to close.
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass  # already gone, or this platform/sandbox denies killpg -- nothing more to do
        try:
            proc.communicate(timeout=5)  # reap the now-dead group leader
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
        return False, "llm-ext fallback timed out (outer bound)"
    if proc.returncode == 0:
        text = (stdout or "").strip()
        if text:
            return True, text
        return False, "llm-ext fallback produced no output"
    return False, (stderr or "").strip()[-400:] or f"llm-ext fallback exited {proc.returncode}"


def run_compact_with_fallback(
    plugin_root: Path, *, transcript: str, out_path: Path, session_key: str,
    heads_args: list[str], sd: Path, deadline: float, llm_ext_timeout_s: float,
    budget_tokens: int | None = None, digest_tokens: int | None = None,
    inject_out_path: Path | None = None, inject_max_bytes: int | None = None,
    max_elided_pointers: int | None = None,
    now_fn: Callable[[], float] = time.time, sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[str, str | None, str]:
    """Retry `jev_compact.py compact` (with `--no-decline`) until `deadline`, then fall back to
    `llm_ext_compact.py` once. Returns `(source, text, detail)`:
      * `(SOURCE_JEV, <compacted text>, "")` — a real Jev compose succeeded; `out_path` is
        already written (by `run_compact`/`jev_compact.py` itself). `text` is read from
        `inject_out_path` instead, when given and readable -- the size-bounded, priority-aware
        companion rendering (TRDD-RAEGS1D5 retune follow-up), same two-renderings shape
        `on-session-start-post-clear-compact.py` already uses. Falls back to `out_path`'s full
        text when `inject_out_path` is unset OR the companion is missing (the two files are
        separate `atomic_write`s, not one atomic pair -- a crash between them must degrade to
        the full document, never lose the compose entirely).
      * `(SOURCE_LLM_EXT, <summary text>, "")` — Jev was exhausted, the llm-ext fallback
        produced a real summary.
      * `(SOURCE_FAILED, None, <why>)` — both Jev and the llm-ext fallback failed; the
        caller degrades to the mechanical template (per the owner's recommendation: ensure a
        template handoff exists for the key, then RELEASE the hold rather than leave it to
        expire — see `summarize_previous_session.py`).

    THIS RETRY LOOP LIVES INSIDE ONE COMPACTION (TRDD-RAEGS1D5, advisor §1): it never stamps
    the clear cooldown, never types `/clear`, and never re-enters the trigger path -- it only
    calls `jev_compact.py compact` and (on exhaustion) `llm_ext_compact.py`, both read-only
    with respect to the clear machinery. That is what keeps it compatible with card 1's loop
    guard ("a failed attempt records evaluated, not fired; no hot retry").

    `--no-decline` is passed on every Jev attempt (R1): without it, the FIRST real failure
    stamps `kind="unavailable"`/`"unreachable"` and every later iteration inside this same
    5-minute budget would fast-decline in microseconds instead of actually retrying.
    `kind="rate_limited"` is deliberately never bypassed (the server's own `Retry-After` is
    honoured via `_sleep_for_kind_or_break`, not raced past).

    ONE ATTEMPT MAY SPAN THE WHOLE REMAINING BUDGET (orchestrator correction, 2026-09-23,
    from a real measurement: a 49MB transcript took 168s for ONE `jev_compact.py compact` run,
    4.7MB took 10s). So `timeout=remaining` here, not a fixed sub-budget -- and a TIMEOUT is
    NEVER retried: it is deterministic work (same transcript, same digest, same items), so a
    re-run would reproduce the identical slowness and just spend more of an already-exhausted
    budget learning nothing new. On timeout the loop goes straight to the llm-ext fallback.
    Retries stay reserved for the FAST transient failures (`kind` unavailable/unreachable/
    unknown/rate_limited), which `jev_compact.py` returns in seconds, not minutes.
    """
    last_proc: subprocess.CompletedProcess[str] | None = None
    last_timed_out = False

    while True:
        remaining = deadline - float(now_fn())
        if remaining < _MIN_JEV_ATTEMPT_S:
            break  # not enough budget left for one more attempt to plausibly finish

        proc, timed_out = run_compact(
            plugin_root, transcript=transcript, out_path=out_path, session_key=session_key,
            heads_args=heads_args, sd=sd, timeout=int(remaining), budget_tokens=budget_tokens,
            digest_tokens=digest_tokens, no_decline=True,
            inject_out_path=inject_out_path, inject_max_bytes=inject_max_bytes,
            max_elided_pointers=max_elided_pointers,
        )
        last_proc, last_timed_out = proc, timed_out

        if not timed_out and proc is not None and proc.returncode == EXIT_OK:
            try:
                text = out_path.read_text(encoding="utf-8")
            except OSError:
                pass  # written but unreadable -- treat exactly like any other failed attempt
            else:
                # TRDD-DQXMND59 stage 3b item A: the `blocked=`/`malformed=` parse+record used
                # to live here (TRDD-1ETALGDG followup, then stage 3 item B) -- moved into
                # `run_compact` itself, the one function both this loop and the post-clear
                # hook share, so the hook (which never reads `proc.stdout`) stops losing both
                # records on its own success path. See `run_compact`'s own docstring.
                if inject_out_path is not None:
                    # TRDD-RAEGS1D5 retune follow-up: prefer the size-bounded companion Jev's
                    # own priority-aware trim produced over the FULL document just read above --
                    # `out_path` stays the fallback (its `text` above), never discarded, for
                    # exactly the crash-between-two-atomic-writes case its docstring describes.
                    try:
                        text = inject_out_path.read_text(encoding="utf-8")
                    except OSError:
                        pass
                return SOURCE_JEV, text, ""

        if timed_out or proc is None:
            # Orchestrator correction 2026-09-23: NEVER retried. The attempt just spent (up
            # to) the WHOLE remaining budget on deterministic work that did not finish in
            # time -- a re-run of the SAME transcript/digest/items would time out again,
            # identically, for the same reason. Go straight to the llm-ext fallback.
            break

        if proc.returncode == EXIT_DECLINED_UNAVAILABLE:
            # With `--no-decline` set, `unavailable`/`unreachable` are bypassed by
            # jev_compact.py itself (R1) -- this exit is reachable, with a REAL binary, ONLY
            # for a `kind="rate_limited"` decline (never bypassed). Defensively still guard
            # on the actual stamp kind (never assume) -- an unexpected kind here (a stub in a
            # test, a future stamp shape) stops the loop rather than sleeping on a guess.
            stamp = read_probe_stamp() or {}
            if stamp.get("kind") == "rate_limited" and _sleep_for_kind_or_break(
                stamp, deadline=deadline, now_fn=now_fn, sleep_fn=sleep_fn
            ):
                continue
            break

        if proc.returncode == EXIT_JEV_ERROR:
            stamp = read_probe_stamp() or {}
            kind = stamp.get("kind")
            if kind in _NON_RETRYABLE_KINDS:
                break  # auth/budget/invalid -- retrying cannot help, fall back now
            if kind == "rate_limited":
                if _sleep_for_kind_or_break(
                    stamp, deadline=deadline, now_fn=now_fn, sleep_fn=sleep_fn
                ):
                    continue
                break
            # unavailable / unreachable / unknown / a missing kind -- transient, short sleep
            remaining = deadline - float(now_fn())
            if remaining <= 0:
                break
            sleep_fn(min(_TRANSIENT_RETRY_SLEEP_S, remaining))
            continue

        # EXIT_DECLINED_NO_DIGEST, EXIT_COMMAND_NOT_FOUND, or any other code -- deterministic
        # for this same transcript/environment; retrying cannot change the outcome.
        break

    # Jev exhausted (deadline reached, or a non-retryable stop). Record WHY, per the existing
    # exit-code -> findings-ledger mapping, then try the fallback exactly once -- EXCEPT for
    # two exit codes where trying it is certain to be pointless (owner review finding #2,
    # TRDD-RAEGS1D5): EXIT_COMMAND_NOT_FOUND (127) means `uv` is missing from this session's
    # PATH, and `llm_ext_compact.py` is exec'd BY PATH with the IDENTICAL `uv run --script`
    # shebang -- it would fail the same way, for the same reason, wasting the rest of the hold
    # to learn nothing new. EXIT_DECLINED_NO_DIGEST (6) means the transcript itself carries no
    # digest material (no human message, no TRDD STATE head) -- there is nothing in it for
    # llm-ext to summarize either, so the fallback can only reach the same "nothing to
    # summarize" conclusion the mechanical template already states directly.
    handle_nonzero_exit(last_proc, timed_out=last_timed_out, sd=sd)

    if last_proc is not None and last_proc.returncode == EXIT_COMMAND_NOT_FOUND:
        return SOURCE_FAILED, None, "uv not on PATH -- llm-ext would fail identically"
    if last_proc is not None and last_proc.returncode == EXIT_DECLINED_NO_DIGEST:
        return SOURCE_FAILED, None, "no digest material -- nothing for llm-ext to summarize either"

    ok, payload = _run_llm_ext_fallback(
        plugin_root, transcript=transcript, timeout_s=llm_ext_timeout_s,
    )
    if ok:
        return SOURCE_LLM_EXT, payload, ""

    record_finding(
        sev="HIGH", code="JEV-COMPACT-FAILED",
        msg=f"[jev-compaction] llm-ext fallback also failed: {payload} — degrading to the "
        "mechanical handoff",
    )
    return SOURCE_FAILED, None, payload
