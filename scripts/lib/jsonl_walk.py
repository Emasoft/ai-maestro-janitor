"""Byte-safe JSONL transcript walk, intended for every transcript reader (TRDD-A8DRRW0I); used
today by `extract_items` and `expand` (stage 3b item G: corrected from "shared by every reader"
-- TRDD-A8DRRW0I's own follow-up, moving the OTHER readers onto this module, had not landed at
the time this was last touched).

TRDD-DQXMND59 stage 3: extracted out of ``scripts/lib/jev_compaction.py``, where
``iter_jsonl_entries`` first landed (73df900b, 2729b1cb) as Jev's own fix for a transcript that
can carry a non-UTF-8 byte or a half-written last line. TRDD-A8DRRW0I is the follow-up that
moves the OTHER transcript readers in this project (hooks, the fleet scanner, the lane's own
mention scan, ...) onto this same walk -- deliberately in a NEW module rather than importing
``jev_compaction`` from those callers.

Deliberately STDLIB-ONLY (``json``, ``pathlib``, ``typing`` -- nothing from the vendored
``jevctx`` package, nothing that needs a PEP-723 ``uv run --script`` dependency declaration):
TRDD-A8DRRW0I's hooks import THIS module, never ``jev_compaction.py`` -- that module pulls in
``jevctx``/``httpx``, an ImportError risk under a hook's own PEP-723 header (which does not
declare those third-party deps), and adds avoidable import time to hooks that already run close
to their timeout budget under load (the measured root cause of the project's 2 s hook timeouts
was CPU run-queue wait plus synchronized heartbeats, commit 7ed4cdeb -- NOT import cost -- but a
thin startup budget is still the wrong place to add a dependency nothing in the hook needs).

WHAT'S HERE, and what's deliberately NOT here (YAGNI, TRDD-DQXMND59 stage 3 item M):
``parse_jsonl_line`` and ``iter_jsonl_entries`` (a from-byte-0, whole-file walk), plus
``drop_lone_surrogates``, plus (TRDD-A8DRRW0I stage A) ``iter_jsonl_tail``. TRDD-A8DRRW0I's own
survey found that most transcript readers OUTSIDE Jev only need a TAIL read (seek N bytes before
EOF, not a full 258 MB transcript read from the front), hence the tail variant. Its constraint:
the first line after a tail seek is, by construction, a PARTIAL line the seek cut mid-record.
That deliberately-cut line is NEVER counted in the tail walk's own ``malformed_lines`` --
counting it would make every single tail read report one false-positive malformed line before it
has even started reading real content.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# Stage 3b item H: the slow path used to rebuild the string one Python-level `for c in text`
# character at a time -- `re.sub` runs the scan+replace in C, and a lone-surrogate string is
# rare enough (the whole point of the fast `encode` check below) that this only matters on the
# path that already pays for a full re-copy anyway.
_LONE_SURROGATE_RE = re.compile("[\ud800-\udfff]")


def drop_lone_surrogates(text: str) -> str:
    """`text`, or a copy with every lone (unpaired) UTF-16 surrogate codepoint replaced by
    U+FFFD. Cheap on the common case: a string that already encodes cleanly returns itself
    unchanged (identity, not a copy).

    TRDD-DQXMND59: `json.loads` accepts a lone surrogate escape (e.g. an emoji a writer's own
    bug cut in half, `"\\ud83d"` with no paired low surrogate) and hands back a `str` that looks
    fine but raises `UnicodeEncodeError` on the first later `.encode("utf-8")` -- every caller
    that renders transcript text (`Item.__post_init__`, `expand`'s own stdout write) must run
    text through this function before treating it as safe to encode.
    """
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return _LONE_SURROGATE_RE.sub("�", text)
    return text


def parse_jsonl_line(
    raw_line: bytes, line_no: int, malformed_lines: list[int],
) -> dict[str, Any] | None:
    """Decode and parse one JSONL line; ``None`` for a blank line (not malformed -- just
    whitespace between real lines) or for one that is malformed, in which case `line_no` is
    also appended to `malformed_lines`. Shared by `iter_jsonl_entries` below and by
    `jev_compaction.py::extract_items`'s own walk (kept as a separate loop there rather than
    switching to the iterator, so its per-entry state -- `pending_tool_uses`,
    `quiet_tool_use_ids`, `window` -- stays at its existing indentation instead of a large,
    error-prone re-indent).

    Read as BYTES and decoded per line, not `open(encoding="utf-8")` on the whole file: a live
    session's transcript is written by another process, so one line's non-UTF-8 bytes (a
    subprocess's raw stdout) must not poison every line after it, and a mid-append last line
    decodes as garbage-then-EOF rather than raising and aborting the whole walk on the line most
    likely to be incomplete. `errors="replace"` does not by itself guarantee a bad line fails to
    parse (a bad byte that decodes to U+FFFD inside a JSON string is still valid JSON, and the
    line still parses -- see `drop_lone_surrogates` for the SEPARATE anomaly this causes later)
    -- what is actually caught here is a line that is structurally broken: not valid JSON at
    all, or JSON whose top level is not an object (a bare number/string/list/null line would
    otherwise make a caller's `entry.get(...)` raise `AttributeError`).

    `except ValueError`, not `except json.JSONDecodeError` (TRDD-DQXMND59 stage 3, finding F;
    citation corrected stage 3b item D -- there is no "PEP 3.11"): CPython's integer-string-
    conversion length limit (`sys.set_int_max_str_digits`, CVE-2020-10735, landed in 3.11 and
    backported to 3.7.14/3.8.14/3.9.14/3.10.7) makes `json.loads` raise a plain `ValueError` --
    not the `JSONDecodeError` subclass -- for an integer literal longer than 4300 digits.
    `json.JSONDecodeError` IS a `ValueError` subclass, so this widening loses no precision on the
    case it already covered; it closes the gap on the one `json.loads` failure mode that was
    never a `JSONDecodeError` at all.
    """
    line = raw_line.decode("utf-8", errors="replace").strip()
    if not line:
        return None
    try:
        entry = json.loads(line)
    except ValueError:
        malformed_lines.append(line_no)
        return None
    if not isinstance(entry, dict):
        malformed_lines.append(line_no)
        return None
    return entry


def iter_jsonl_entries(path: Path, *, malformed_lines: list[int]) -> Iterator[tuple[int, dict[str, Any]]]:
    """Walk one transcript JSONL, from byte 0, yielding ``(1-based line number, parsed dict)``
    for every line that parses to a JSON OBJECT -- the one entry shape every reader in this
    codebase actually consumes.

    TRDD-DQXMND59 follow-up (adversarial review, 2026-09-24, finding B): `extract_items` had its
    own byte-read-and-decode loop and `_read_jsonl_entry` (`scripts/jev_compact.py`) had a
    SECOND, older one that still opened the file in text mode -- so `expand` crashed with
    `UnicodeDecodeError` on the exact same damaged byte `compact` already knew how to skip, for
    every id located after it. Sharing `parse_jsonl_line` (not just its logic, copy-pasted)
    means one fix covers both callers forever -- and, per this module's own docstring, every
    future caller under TRDD-A8DRRW0I too.
    """
    with path.open("rb") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            entry = parse_jsonl_line(raw_line, line_no, malformed_lines)
            if entry is not None:
                yield line_no, entry


def iter_jsonl_tail(path: Path, tail_bytes: int, *, malformed_lines: list[int]) -> Iterator[dict[str, Any]]:
    """Walk the LAST ``tail_bytes`` bytes of one transcript JSONL, yielding every line that parses
    to a JSON OBJECT, in file order (TRDD-A8DRRW0I stage A).

    The read starts ``tail_bytes`` before EOF (or at byte 0 when the file is shorter). When it did
    not start at byte 0 the seek may have cut a record in half: the byte just BEFORE the start is
    read too, and if it is not a newline the first line is that partial fragment and is dropped
    WITHOUT being recorded in ``malformed_lines`` (a seek that lands exactly on a line boundary
    drops nothing). Every remaining line goes through ``parse_jsonl_line``, so a non-UTF-8 byte,
    a non-object line or a half-written last line never raises.

    ``malformed_lines`` receives 1-based positions WITHIN THE TAIL READ (after the dropped
    fragment), not file line numbers -- a tail read cannot know how many lines precede it.

    A missing or unreadable file raises ``OSError`` to the caller (fail fast; each caller decides
    whether that means "skip" or "abort"). It surfaces on the first ``next()``, not at call time.
    """
    if tail_bytes < 1:
        raise ValueError(f"tail_bytes must be >= 1, got {tail_bytes}")
    with path.open("rb") as fh:
        size = fh.seek(0, 2)
        start = max(0, size - tail_bytes)
        # start - 1: the one byte of look-behind that tells a clean boundary from a mid-record cut.
        fh.seek(max(0, start - 1))
        data = fh.read()
    if start > 0:
        if data[:1] == b"\n":
            data = data[1:]
        else:
            nl = data.find(b"\n")
            data = data[nl + 1:] if nl != -1 else b""
    for line_no, raw_line in enumerate(data.split(b"\n"), start=1):
        entry = parse_jsonl_line(raw_line, line_no, malformed_lines)
        if entry is not None:
            yield entry
