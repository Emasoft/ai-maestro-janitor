# Shadow decision-log wiring for jev_compact.py (TRDD-N9LDHF7N card 7).
#
# jevctx.shadow.ShadowLog (vendored, scripts/lib/jevctx/shadow.py -- do not edit it, another
# worker owns jev_compaction.py/test_jev_compaction.py and this card must not touch either)
# is the generic append-only decision/outcome log. This module is the project-specific glue
# that turns jev_compaction.py's own scored items into ShadowLog calls, and answers the three
# things the vendored module deliberately leaves to its caller: where the file lives, how big
# it is allowed to get, and what a write failure means for the caller it is observing (never
# fail the compaction -- see log_decisions/log_expand_outcome).
#
# Two ShadowLog rows per fully-scored item, matching the two Noul questions
# jev_compaction.py's own score_items() actually asks (see its `_score_batch` docstring):
#   - "relevance" (jevctx's RETRIEVE_QUESTION -- `Scores.relevance` vs `relevance_threshold`)
#     -> ShadowLog kind="admit", action mirrors the item's REAL kept/elided outcome
#     (`Scores.kept`, the union of both gates) -- logged for every scored item, since every
#     item is asked this question.
#   - "decision" (DECISION_QUESTION -- `Scores.decision` vs `decision_threshold`) ->
#     ShadowLog kind="retrieve" (this project's own reading of that generic label as "a
#     signal that decides whether an item earns extra protection/retrievability" -- shadow.py
#     itself only defines the generic injected/skipped action pair, it does not prescribe
#     this mapping), action mirrors `Scores.decision_passed` -- logged ONLY for "user" items,
#     because jev_compaction.py
#     never sends a `:dec` question for any other kind (`_score_batch`: "a non-'user' item
#     still never gets a :dec question sent for it"). Logging a spurious decision=0.0 row for
#     every other item would be noise no threshold change could ever move.
#
# `replay_stats`'s own `--question relevance|decision` (the card's CLI surface) maps back onto
# exactly these two kinds (_QUESTION_TO_KIND), so a caller can retune ONE threshold without the
# OTHER question's rows (a different score/threshold pair entirely) skewing the counterfactual.
#
# A blocked or oversized item (`Scores.blocked`/`Scores.oversized`) was never actually sent to
# Jev -- jev_compaction.py fills in a sentinel Scores for it precisely so `compose()` always
# treats it as a pointer. Logging that sentinel as a real scored decision would corrupt replay,
# so both are skipped in `log_decisions`.

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any, Protocol

import state
from jevctx.shadow import PREVIEW_CHARS, ShadowLog, ShadowStats
from jevctx.types import Origin

# Card 7 follow-up (TRDD-N9LDHF7N, review defect 1 -- "run every preview through the
# janitor's existing secret redaction"): reuse the vendor-prefix secret-value regex already
# compiled for the Lambda/serverless secret-shape rule (AWS AKIA/ASIA, GitHub/GitLab/Slack
# tokens, OpenAI/Anthropic sk- keys) -- this is the one existing pattern lib in scripts/lib/
# that matches a literal secret VALUE in arbitrary text (the cloud/CI-CD leak libs scan for
# risky *commands*, not pasted credential shapes). Reused as-is, not copied: this module stays
# a thin project-specific wrapper around the vendored shadow log, never its own secret scanner.
from serverless_function_patterns import _KNOWN_SECRET_RE as _SECRET_VALUE_RE

# Post-write review, second follow-up (coordinator, verified against commit e904477d): the
# prefixed-token regex above misses generic, unprefixed secret shapes -- checked
# scripts/hooks/post-edit-safety.py and scripts/hooks/pre-bash-safety.py (the coordinator's
# own named candidates) AND everything they import: both are stdlib-only (json/os/re/sys, no
# `scripts/lib` import), and their own "secret"/"credential" hits are sensitive FILE PATHS
# (~/.aws/credentials, ~/.git-credentials, /etc/shadow), not a value-shape matcher -- there is
# nothing further to reuse from those two files. These four are therefore NEW, added next to
# the reuse above per the coordinator's own fallback ("if it still misses the common generic
# shapes... add those"), not a duplicate of something already shared elsewhere.
#
# Review fork (third pass) caught a real gap in the first draft's value class
# (`[A-Za-z0-9_\-+/=]{6,}`, unquoted-only): a human-pasted password containing a space or
# punctuation before 6 alnum characters -- `password: "hi there!"` -- matched nothing and
# escaped redaction entirely, exactly this log's own threat model (transcript text, not a
# config file). Fixed by matching a QUOTED value (any run inside matching quotes, punctuation
# and spaces included) as its own alternative, ahead of the unquoted fallback.
_GENERIC_KV_SECRET_RE = re.compile(
    r"(?i:\b(?:password|passwd|secret|token)\s*[:=]\s*)"
    r"(?:\"[^\"\n]{3,}\"|'[^'\n]{3,}'|[A-Za-z0-9_\-+/=]{6,})"
)
_BEARER_TOKEN_RE = re.compile(r"(?i:\bauthorization\s*:\s*bearer\s+)[A-Za-z0-9\-._~+/=]{8,}")
_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
    r".*?"
    r"-----END (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
    re.DOTALL,  # a real PEM block spans many lines -- `.` must cross them to match the whole thing
)
# Known, undocumented-until-now limitation (review fork, third pass): this pattern requires
# BOTH the BEGIN and END markers inside the SAME item's text. jev_compaction.py's own large
# tool-result segmentation (`_segment_tool_result`) can split one big result across multiple
# items/records, and a PEM key split across that boundary -- BEGIN in one item, base64 body and
# END in the next -- leaves bare key material in one or both fragments with no marker for any
# pattern here to anchor on. No per-item redaction pass can close this without carrying state
# across the whole batch, which none of these patterns attempt; flagged, not fixed, since it is
# a different (cross-item) problem than the one this follow-up was scoped to.
_GENERIC_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    _PRIVATE_KEY_BLOCK_RE,  # multi-line, run first so a narrower pattern can't split it apart
    _BEARER_TOKEN_RE,
    _GENERIC_KV_SECRET_RE,
)

__all__ = [
    "SHADOW_LOG_NAME",
    "MAX_SHADOW_LOG_BYTES",
    "ScoredItem",
    "ItemScore",
    "shadow_log_path",
    "log_decisions",
    "log_expand_outcome",
    "replay_stats",
]

SHADOW_LOG_NAME = "jev-shadow.jsonl"

# Card 7 follow-up (TRDD-N9LDHF7N, review defect 4 -- "the 10MB single-backup cap is smaller
# than one large compaction, so a week of history never accumulates"). The arithmetic (full
# numbers in reports/compaction-replacement/, this follow-up's own report):
#   - Measured on a synthetic 45,000-item run (realistic score spread, not a constant score),
#     AFTER fix 2's batching, fix 1's redaction, and this fix's far-from-threshold preview
#     drop: ~460.7 bytes/record, 58,500 records (45,000 admit + ~13,500 retrieve) for one
#     full-transcript compaction -> ~27MB for that ONE session.
#   - IMPORTANT (post-write review, TRDD-N9LDHF7N card 7 follow-up): `jev_compaction.
#     extract_items` walks the WHOLE transcript "one pass, top to bottom" on every `compact`
#     call, and `score_items` has no already-scored cache -- there is no incremental,
#     since-last-run scoring to lean on here. So "9 small + 1 big compactions/day" describes
#     ten compactions whose TARGET SESSIONS happen to differ in size (nine on transcripts that
#     simply haven't grown large yet), not nine cheap incremental deltas on one session.
#   - The task's own worst-case assumption -- a 45,000-item FULL compaction recurring every
#     single day, 7 days straight -- is therefore ~189MB even with the preview drop applied:
#     NOT achievable under a 60MB ceiling, and no further shrinking of a single JSONL record
#     (short of dropping the hash and every other field too, which would make the log useless
#     for its own purpose) closes a 3x gap. Per the review's own instruction ("if that's
#     impossible... record that choice"): this cap instead guarantees a FIRM 60MB total ceiling
#     (never unbounded growth), which comfortably covers >= 7 days when large-transcript
#     compactions stay occasional (the common case in practice), and covers roughly its two
#     most recent occurrences (2 x 27MB ~= 54MB) when they don't -- an honest bound for a
#     side-observability channel that is explicitly allowed to lose old history, not a
#     data-loss risk in itself (see log_decisions'/log_expand_outcome's own OSError handling).
#   - 30MB for this file, one rotated backup of the same size (jev-shadow.jsonl.1, same shape
#     as dispatch.py's own log rotation) = 60MB, the stated ceiling exactly. A second backup
#     would only ever widen the worst-case-vs-60MB gap above, not close it.
MAX_SHADOW_LOG_BYTES = 30 * 1024 * 1024

# Card 7: "replay --threshold T [--question relevance|decision]" -- maps the CLI's question
# name onto the ShadowLog `kind` literal that carries that question's rows (see module header).
_QUESTION_TO_KIND: Mapping[str, str] = {"relevance": "admit", "decision": "retrieve"}

# Review fork finding (post-write review, TRDD-N9LDHF7N card 7): ShadowLog.stats()/.replay()
# build their internal per-item action map as `{e.item_id: e.action ...}` -- a PLAIN dict
# keyed only by item_id, with no `kind` in the key (shadow.py's own `stats`/`replay`). Logging
# the admit AND retrieve rows for a "user" item under the SAME item_id therefore collapses to
# ONE slot (last write wins -- the retrieve row, appended second), so the admit row's real
# "kept"/"elided" action is silently discarded whenever the raw file is read through the
# vendored module's own public `.stats()`/`.replay()` (not just through this module's own
# kind-filtered `replay_stats`, which was already immune). Concretely: an elided "user" item
# would stop counting as a false negative in `ShadowLog.load(path).stats()` the moment it also
# got a retrieve row. Suffixing the retrieve row's item_id makes the two rows collision-proof
# in ANY reader, not just this module's own filtered path -- `log_expand_outcome` never needs
# to know about the suffix, since it always logs the bare id, which only the admit row (the
# one "was this elided" is actually about) can ever match.
_RETRIEVE_ROW_ID_SUFFIX = "#decision"


class ScoredItem(Protocol):
    """The `jev_compaction.Item` fields this module reads -- a structural Protocol instead
    of importing `jev_compaction` directly, so this module carries no dependency on that
    module's own httpx-requiring import chain, and no coupling to its in-flight changes.

    Declared as read-only `@property` members, not plain mutable annotations: `Item` is a
    frozen dataclass, and a plain `id: str`-style Protocol attribute requires a SETTER too
    (pyright: "id is not read-only in protocol") -- a frozen dataclass instance would then
    never structurally satisfy it.
    """

    @property
    def id(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def text(self) -> str: ...
    @property
    def tokens(self) -> int: ...
    @property
    def turn(self) -> int: ...


class ItemScore(Protocol):
    """The `jev_compaction.Scores` fields this module reads -- read-only for the same reason
    as `ScoredItem` above (`Scores` is also a frozen dataclass)."""

    @property
    def relevance(self) -> float: ...
    @property
    def decision(self) -> float: ...
    @property
    def oversized(self) -> bool: ...
    @property
    def kept(self) -> bool: ...
    @property
    def decision_passed(self) -> bool: ...
    @property
    def blocked(self) -> bool: ...


def shadow_log_path() -> Path:
    """`<project>/.janitor/state/jev-shadow.jsonl` -- `.janitor/` is gitignored project-wide
    (see the repo's own .gitignore), so this never lands in the repo tree, per the card."""
    return state.state_dir() / SHADOW_LOG_NAME


def _rotate_if_oversized(path: Path) -> None:
    """Single-backup rotation: `path` -> `path.1` (overwriting any older one) once `path`
    crosses `MAX_SHADOW_LOG_BYTES`. Never raises: a rotation failure degrades to "keep
    appending to the oversized file" rather than aborting the log entirely -- write failures
    are the caller's own concern (log_decisions/log_expand_outcome), this is just growth
    control and must not itself become a NEW way for shadow logging to break a compaction.

    Checked once per `log_decisions`/`log_expand_outcome` call, not once per line: a single
    `compact` run over a transcript with thousands of items can therefore push the file past
    `MAX_SHADOW_LOG_BYTES` by that call's own size before the NEXT call rotates it -- an
    acceptable, deliberate looseness for an observability side channel (the cap bounds
    long-run growth across many `compact` runs, not the peak size of any one run)."""
    try:
        if not path.exists() or path.stat().st_size <= MAX_SHADOW_LOG_BYTES:
            return
        backup = path.with_name(path.name + ".1")
        path.replace(backup)
        # Defect 1 (review): keep the rotated backup as locked-down as the live file --
        # `Path.replace` preserves the source's mode, so this is belt-and-suspenders for a
        # backup left over from before this fix shipped (created with default permissions).
        backup.chmod(0o600)
    except OSError as exc:
        print(f"jev-shadow: rotation failed, appending to the oversized file: {exc}", file=sys.stderr)


def _redact_text(text: str) -> str:
    """Defect 1 (review): a decision record's preview is raw transcript/tool-output text -- an
    API key or AWS credential pasted into a tool result would land in this file verbatim
    otherwise. Runs `_SECRET_VALUE_RE` (the vendor-prefix reuse) plus the four generic shapes
    above (see their own comment). `text_sha256` is left hashing the REAL text throughout. A
    hash is not the same exposure as a plaintext preview -- it can't be read back -- but it is
    not a zero-risk residual either: post-write review noted that anyone who already SUSPECTS
    a specific literal secret can confirm the guess by hashing it and comparing. That is a
    narrow threat (it requires already having the candidate string), the task scoped this fix
    to the preview specifically, and the hash's own job (letting a caller correlate identical
    content across records) needs the real text regardless of redaction -- so it is left
    alone, not silently treated as risk-free.

    Takes the FULL item text, not an already-truncated preview (coordinator, second
    follow-up): redacting after truncation misses a secret cut at the 200-char boundary --
    its surviving prefix no longer completes the "known prefix + minimum length" shape any of
    these patterns require, so it leaked. `_safe_preview` (below) is the only caller and is
    the one that truncates, always AFTER this runs."""
    redacted = _SECRET_VALUE_RE.sub("[REDACTED]", text)
    for pattern in _GENERIC_SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


# Coordinator, second follow-up: even redacting the full text first, the TRUNCATION itself can
# still slice a real, otherwise-unredacted secret in half (one that starts too close to the
# 200-char cut for its own pattern to have matched at all -- e.g. a bare high-entropy token
# with no recognized prefix, which none of the patterns above catch by design). The trailing
# fragment is `_PARTIAL_TOKEN_TAIL_MIN_LEN`+ alnum/underscore/dash characters that run straight
# to the cut with nothing after them -- exactly what an in-progress token cut mid-string looks
# like -- and is masked outright rather than left as a shortened-but-still-readable prefix.
_PARTIAL_TOKEN_TAIL_MIN_LEN = 12
_TRUNC_TAIL_WINDOW = 40  # coordinator's own spec: inspect the last 40 characters for the cut
_PARTIAL_TOKEN_TAIL_RE = re.compile(rf"[A-Za-z0-9_\-]{{{_PARTIAL_TOKEN_TAIL_MIN_LEN},}}$")


def _safe_preview(text: str) -> str:
    """Redact the full text, THEN truncate to `PREVIEW_CHARS`, THEN mask a trailing partial
    token the truncation itself created -- see `_redact_text`'s and the module constants'
    docstrings/comments above for why each step has to happen in this order.

    Disclosed trade-off (review fork, third pass): redacting before truncating means a long
    early match (e.g. a multi-KB PEM block collapsing to one `[REDACTED]`) shrinks the text,
    which can pull originally-later bytes -- ones a truncate-FIRST preview could never have
    reached at all -- into the 200-char window. That is not a leak of the matched secret
    itself, but it does mean the preview is no longer a stable prefix of the raw text, so any
    pattern-coverage gap elsewhere (an unquoted value with unusual punctuation, a secret shape
    none of these patterns recognize) has more raw bytes to potentially appear through. This
    is accepted as the necessary cost of fixing the truncation-order bug correctly, not
    something this function tries to further mitigate."""
    redacted = _redact_text(text)
    was_truncated = len(redacted) > PREVIEW_CHARS
    preview = redacted[:PREVIEW_CHARS]
    if was_truncated:
        m = _PARTIAL_TOKEN_TAIL_RE.search(preview[-_TRUNC_TAIL_WINDOW:])
        if m:
            preview = preview[: len(preview) - len(m.group(0))] + "[TRUNC]"
    return preview


_FAR_FROM_THRESHOLD_MARGIN = 0.3
# Defect 4 (review): the preview is the dominant cost per record (~200 of the measured ~525
# bytes -- see the report), and the daily-45,000-item session alone already exceeds the 60MB/
# 7-day budget if every one of its records keeps a preview (the arithmetic is in the report and
# in MAX_SHADOW_LOG_BYTES's own comment above). The review's own fallback: a record whose score
# sits more than `_FAR_FROM_THRESHOLD_MARGIN` away from the threshold it was logged against is
# safe to shrink for the REALISTIC calibration use case this log exists for -- nudging a
# threshold by tenths, not retargeting it entirely. Post-write review flagged the earlier
# wording here ("can't change action under ANY replay threshold") as an overclaim:
# `replay_stats`/`ShadowLog.replay` accept an arbitrary threshold, so a record logged at 0.5
# with score 0.95 (dropped, diff 0.45) CAN still flip kept->elided under `replay --threshold
# 0.99` -- `_counterfactual` reads only `score`/`threshold`, never `text_preview`, so that
# flip's ACTION and every ShadowStats number are still exactly correct either way; what is
# lost for a far-from-threshold, far-from-original-threshold replay is only a human's ability
# to manually eyeball that one outlier's raw text next to the number.


def _drop_preview_if_far_from_threshold(record: dict[str, Any]) -> None:
    """Mutates `record["text_preview"]` to "" when this row's own logged score/threshold pair
    (both already on the record -- `admit` rows carry `relevance_threshold`, `retrieve` rows
    carry `decision_threshold`, whichever `log_decisions` passed to `.decision()`) are far
    apart. `text_sha256` is left alone -- it is 64 bytes vs the preview's ~200, and a caller
    correlating identical content across records needs it regardless of how "close" a score
    is. Outcome rows have no `score`/`threshold` at all (see `ShadowLog.outcome`'s call
    signature) and are never passed here -- only `log_decisions`' decision records are."""
    if abs(record["score"] - record["threshold"]) > _FAR_FROM_THRESHOLD_MARGIN:
        record["text_preview"] = ""


def _write_records(path: Path, records: list[dict[str, Any]]) -> None:
    """Append every record in `records` to `path` in ONE open/write/close (defect 2: the
    vendored `ShadowLog.decision()`/`.outcome()` each open the file for append on every call
    -- about 45,000 opens scoring a full transcript in the latency-limited sync lane).
    `log_decisions`/`log_expand_outcome` build their records through an in-memory
    `ShadowLog(path=None)` (the vendored helpers, so the JSONL shape stays exactly what
    `ShadowLog.load` expects -- see the round-trip test), then hand the resulting
    `.entries()` dicts here for the actual disk write.

    Never called with an empty `records`: `log_decisions` must not create an empty log file
    just because every item in this batch was blocked/oversized (see its own callers' tests).

    Mode 0600 (defect 1): a record carries a (now-redacted) preview and a sha256 of real
    transcript content -- the file must not be group/world-readable. Set on every call, not
    just first creation, so a log file left over from before this fix also gets locked down.

    Durability trade-off (post-write review, disclosed rather than fixed -- this module's own
    contract is "shadow logging must never fail the caller it observes", so losing the SIDE
    log on a real I/O failure is already accepted, see log_decisions'/log_expand_outcome's
    OSError handling): batching means a disk-full or similar failure partway through a large
    batch can lose the WHOLE call's records, where the old per-record-open design would have
    already durably written everything up to the failing record. Fewer opens in exchange for
    coarser-grained loss on the rare write-failure path -- consistent with the existing
    contract, but a real shift this batching introduces, not merely a wash.
    """
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    # fchmod on the already-open fd, not chmod(path, ...): O_CREAT's mode arg is ignored for a
    # file that already existed (needed to lock down a log left over from before this fix), and
    # operating on the fd -- not the path -- avoids re-resolving the name for that second call.
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in records)


# Defect 3 (review): the synchronous SessionStart lane and the detached background lane can
# both run `compact` on the same just-closed session's transcript (one already wrote the
# compacted output, the other raced it) -- each call to `log_decisions` logs its own full set
# of admit/retrieve rows, so the same session's decisions land twice. A tiny seen-set file next
# to the log (not the log itself, so replay never has to filter it out) remembers which runs
# were already logged; `session_key` (the same value `--session-key` already threads through
# `cmd_compact`) plus the transcript's byte size at call time is specific enough that two
# genuinely different compactions of a GROWING transcript (mid-session, before it closes) are
# never conflated with each other.
_SEEN_SET_MAX_ENTRIES = 2000  # generous headroom over ~10 compactions/day * 7 days = 70


def _seen_set_path(log_path: Path) -> Path:
    return log_path.with_suffix(".seen")


def _run_key(session_key: str, transcript_path: str | Path | None) -> str | None:
    """`None` means "cannot dedupe this call" (no session_key, no transcript, or the
    transcript vanished under us) -- `log_decisions` then always logs, exactly its old
    behaviour, so every existing caller that doesn't pass these two stays unaffected."""
    if not session_key or transcript_path is None:
        return None
    try:
        size = Path(transcript_path).stat().st_size
    except OSError:
        return None
    return f"{session_key}:{size}"


def _read_seen(seen_path: Path) -> list[str]:
    try:
        return seen_path.read_text(encoding="utf-8").splitlines() if seen_path.exists() else []
    except OSError:
        return []  # fail OPEN -- never let a seen-set read error block a real decision log


def _mark_seen(seen_path: Path, run_key: str, already: list[str]) -> None:
    updated = already[-(_SEEN_SET_MAX_ENTRIES - 1):] + [run_key]
    seen_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    try:
        seen_path.chmod(0o600)  # session_key can itself be an identifying string
    except OSError:
        pass  # the write above already succeeded -- a chmod failure is not worth raising over


@contextlib.contextmanager
def _seen_lock(seen_path: Path) -> Iterator[None]:
    """Post-write review (defect 3 follow-up): a plain read-then-write on the seen-set file is
    racy if the sync SessionStart lane and the detached background lane genuinely overlap
    (both start near session end, before either has called `_mark_seen`) -- both would read an
    empty/stale seen-set and both would then log a full duplicate set of records, exactly what
    the seen-set exists to prevent. An exclusive `flock` on a sibling `.lock` file (never the
    seen-set file itself, so nothing has to special-case "does the seen-set exist yet")
    serializes the whole check-then-write critical section across processes; POSIX-only
    (flock), matching this module's existing chmod/fchmod-only (macOS/Linux) posture. A flock
    is held per open file description and released by the kernel the instant this process
    closes the fd or exits (including a crash) -- no stale-lock cleanup is possible or needed,
    unlike a PID-file lock. Only engaged when `log_decisions` actually has a `run_key` to
    dedupe (see its own call site) -- a caller that never passes session_key/transcript_path
    never pays for or waits on this lock."""
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = seen_path.with_suffix(".lock")
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def log_decisions(
    items: Iterable[ScoredItem],
    scores: Mapping[str, ItemScore],
    *,
    relevance_threshold: float,
    decision_threshold: float,
    session_key: str = "",
    transcript_path: str | Path | None = None,
) -> None:
    """Append one "admit" row per scored item, plus one "retrieve" row for each item that was
    actually asked the decision question -- see the module header for which is which. Called
    once per real `compact` run, right after `jc.score_items` returns: this logs from the
    scores jev_compact.py already has, never from a hook inside jev_compaction.py itself.

    `session_key`/`transcript_path` (defect 3): when both are given, a run already logged for
    this exact (session, transcript size) is skipped entirely -- see the module-level comment
    above `_run_key`. Omit either (the default) to always log, unchanged from before this fix.

    A write failure (a read-only `.janitor/`, a full disk, a permissions error) is reported on
    stderr and swallowed: shadow logging is an observability side channel, and a compaction
    that already scored and is about to write its real output must never fail because the
    SIDE log couldn't be written (card 7's own requirement).
    """
    try:
        path = shadow_log_path()
        run_key = _run_key(session_key, transcript_path)
        seen_path = _seen_set_path(path)
        # `_seen_lock` (post-write review, defect 3 follow-up): without it, the sync lane and
        # the detached lane could both pass the "not already seen" check before either called
        # `_mark_seen`, defeating the dedup this whole block exists for. `nullcontext()` when
        # there is nothing to dedupe (`run_key is None`) -- a caller that never passes
        # session_key/transcript_path never waits on a lock it has no use for.
        lock = _seen_lock(seen_path) if run_key is not None else contextlib.nullcontext()
        with lock:
            already = _read_seen(seen_path) if run_key is not None else []
            if run_key is not None and run_key in already:
                return  # defect 3: the other lane already logged this exact run

            _rotate_if_oversized(path)

            # In-memory only (`path=None`) -- defect 2: building every record through the
            # vendored `.decision()` without a disk-backed ShadowLog means zero opens per
            # item; `_write_records` below does the one real open for the whole batch.
            # `raw_texts` runs parallel to the records `log.entries()` returns below (same
            # append order) -- `_safe_preview` (coordinator, second follow-up) needs the FULL
            # original text of each row, not the already-truncated `text_preview` the vendored
            # `.decision()` computed from it, to redact before truncating rather than after.
            log = ShadowLog(path=None)
            raw_texts: list[str] = []
            for it in items:
                sc = scores.get(it.id)
                if sc is None or sc.oversized or sc.blocked:
                    continue  # never actually scored -- see module header
                origin = Origin(source=f"item:{it.kind}", ref=it.id, turn=it.turn)
                log.decision(
                    kind="admit", item_id=it.id, score=sc.relevance,
                    threshold=relevance_threshold, action="kept" if sc.kept else "elided",
                    tokens=it.tokens, origin=origin, text=it.text, turn=it.turn,
                )
                raw_texts.append(it.text)
                if it.kind == "user":
                    # `_RETRIEVE_ROW_ID_SUFFIX`: keeps this row's item_id distinct from the
                    # admit row just logged above -- see that constant's own comment for why
                    # sharing `it.id` between the two corrupts the vendored
                    # ShadowLog.stats()/.replay().
                    log.decision(
                        kind="retrieve", item_id=f"{it.id}{_RETRIEVE_ROW_ID_SUFFIX}",
                        score=sc.decision, threshold=decision_threshold,
                        action="injected" if sc.decision_passed else "skipped",
                        tokens=it.tokens, origin=origin, text=it.text, turn=it.turn,
                    )
                    raw_texts.append(it.text)

            records = log.entries()
            # Review fork (third pass): `zip(strict=True)` below is the right tool to catch a
            # future maintenance slip (a `.decision()` call added without its matching
            # `raw_texts.append`) LOUDLY in dev/CI -- but the `ValueError` it raises is not an
            # `OSError`, so left unguarded it would propagate out of this function's own
            # `except OSError` and break the CALLER's compaction, contradicting this module's
            # one stated contract. This explicit length check degrades the SAME way an OSError
            # write failure already does (log to stderr, write nothing for this batch) instead
            # of writing UNREDACTED vendor previews (the only other "safe" option here would
            # be worse than failing) or letting the exception through.
            if len(records) != len(raw_texts):
                print(
                    f"jev-shadow: internal record/text-count mismatch ({len(records)} vs "
                    f"{len(raw_texts)}), skipping this batch rather than risk an unredacted "
                    "preview", file=sys.stderr,
                )
                return
            for record, raw_text in zip(records, raw_texts, strict=True):
                _drop_preview_if_far_from_threshold(record)  # defect 4 -- see its own docstring
                if record["text_preview"]:
                    record["text_preview"] = _safe_preview(raw_text)  # defect 1, from the FULL text
            _write_records(path, records)

            if run_key is not None:
                _mark_seen(seen_path, run_key, already)
    except OSError as exc:
        print(f"jev-shadow: decision log write failed, compaction continues: {exc}", file=sys.stderr)


def log_expand_outcome(item_id: str, *, turn: int = 0) -> None:
    """Append an "expand" outcome row. An expand of an id `compact` had logged as elided is a
    false negative (see `ShadowLog.false_negative_rate`'s own docstring) -- this is the only
    hook `expand` needs; the matching against a prior decision happens later, by item_id, when
    the log is read (`ShadowLog.stats`/`.replay`). `item_id` is always the BARE id (never
    `_RETRIEVE_ROW_ID_SUFFIX`-suffixed): that matches only the admit row, which is the one
    "was this elided" is actually about -- an item's retrieve row, if any, is a separate
    question entirely (see `log_decisions`).

    `turn` defaults to 0: a one-shot `expand` invocation has no live turn counter the way
    `compact` has each item's own `.turn` -- harmless, since no stats computation in ShadowLog
    reads `turn` at all (its `_summarise` keys only on item_id/score/action/tokens).
    """
    try:
        path = shadow_log_path()
        _rotate_if_oversized(path)
        log = ShadowLog(path=None)  # defect 2: same in-memory-then-batch-write path
        log.outcome(kind="expand", item_id=item_id, turn=turn)
        _write_records(path, log.entries())
    except OSError as exc:
        print(f"jev-shadow: outcome log write failed: {exc}", file=sys.stderr)


def replay_stats(threshold: float, *, question: str, path: Path | None = None) -> ShadowStats:
    """What `threshold` would have produced for just `question`'s own rows -- card 7's
    `replay --threshold T --question relevance|decision`.

    `ShadowLog.replay()` applies ONE threshold to every decision it holds regardless of
    `kind` -- correct when a log only ever carries one question's rows, wrong here since
    `log_decisions` logs two per item. So this filters the persisted JSONL down to the rows
    for the requested question's `kind` (plus every outcome row, which carries no `kind` and
    is always relevant to the false-negative count) into a scratch file, then delegates the
    actual counterfactual math to the vendored `ShadowLog.load`/`.replay` -- no
    reimplementation of its private `_counterfactual`.
    """
    if question not in _QUESTION_TO_KIND:
        raise ValueError(f"unknown question {question!r}, expected one of {sorted(_QUESTION_TO_KIND)}")
    kind = _QUESTION_TO_KIND[question]
    source = path if path is not None else shadow_log_path()

    kept_lines: list[str] = []
    if source.exists():
        try:
            with source.open("r", encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        obj = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue  # a torn final write -- ShadowLog.load skips these too
                    if obj.get("type") == "decision" and obj.get("kind") != kind:
                        continue  # the OTHER question's row
                    kept_lines.append(stripped)
        except OSError as exc:
            print(f"jev-shadow: replay read failed, treating as empty: {exc}", file=sys.stderr)
            kept_lines = []

    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as tmp:
        for line in kept_lines:
            tmp.write(line + "\n")
        tmp_path = Path(tmp.name)
    try:
        return ShadowLog.load(tmp_path).replay(threshold)
    finally:
        tmp_path.unlink(missing_ok=True)
