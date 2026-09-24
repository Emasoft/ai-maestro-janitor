#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""Jev compaction CLI (TRDD-541CBN36 card 2, TRDD-RAEGS1D5 card 3 part B).

This is its OWN PEP-723 script, separate from the stdlib-only hook scripts, because it is
the one place in this project that needs ``httpx`` — jevctx's ``HttpJevClient`` /
``OpenRouterJevClient`` are built on it (see scripts/lib/jevctx/VENDORED.md and the study
at reports/compaction-replacement/20260922_205137+0200-jev-compaction-study.md §H: "the
scorer must therefore be its OWN PEP-723 script ... and be called as a subprocess"). That
also gives it a CA bundle via ``httpx`` → ``certifi`` in the daemon lane, cf. TRDD-X6I04SAO.

Sub-commands:
  probe                            — one Noul question through the configured provider;
                                      prints ``probe ok noul=<f> cost=<usd> ms=<n>`` and
                                      exits 0, or prints the reason and exits 2. Also writes
                                      the probe stamp (below) — a manual check, so it always
                                      actually probes, never short-circuits on a cached stamp.
  expand --transcript P ID         — prints the ORIGINAL bytes of one item (``ID`` =
                                      ``<uuid>:<n>``) from a transcript JSONL; exits 3 if
                                      the entry or the block index isn't found. Card 6
                                      (TRDD-88DOI824): ``ID`` may instead be
                                      ``<uuid>:<n>@<a>-<b>`` (1-based, inclusive line
                                      numbers) — a segment `jev_compaction.py::
                                      _segment_tool_result` split a large tool result into —
                                      and prints exactly lines ``a..b`` of that block's raw
                                      text; exits 3 if the span is out of range.
  replay --threshold T             — print `jevctx.shadow.ShadowStats` for the hypothetical
                                      threshold T against the persisted shadow decision log
                                      (TRDD-N9LDHF7N card 7) -- no Jev call, no transcript
                                      walk, just the scores past `compact` runs already
                                      logged. `--question relevance|decision` (default
                                      "relevance") picks which of the two logged questions to
                                      replay; see scripts/lib/jev_shadow_log.py's module
                                      header for what each one means. Always exits 0 (an
                                      empty/missing log just replays as zero decisions).
  compact --transcript P --out F   — compose the compacted context (card 3) and write it to
                                      F atomically. Exit code contract (a part C caller
                                      branches on these, so each is deliberate and stable):
                                        0 — wrote F; one summary line on stdout.
                                        5 — declined: a probe-stamp failure younger than its
                                            kind's own TTL says Jev is down right now — no
                                            network fan-out into a known outage. Gated on
                                            stamp `kind` in {"unavailable", "unreachable",
                                            "rate_limited"} ONLY: `auth`/`budget`/`invalid`/
                                            `unknown` never decline a later attempt — those
                                            are scoped to one key/request/attempt, not the
                                            endpoint, so the caller surfaces them as a
                                            finding instead of the whole machine going dark.
                                            `--no-decline` bypasses the `unavailable` and
                                            `unreachable` branches (never `rate_limited` —
                                            see `cmd_compact`).
                                        6 — declined: `jev_compaction.NoDigest` — neither a
                                            human message nor a TRDD STATE head exists, so
                                            there is nothing to judge relevance against.
                                        7 — a Jev error (missing/bad key, budget violation,
                                            scorer failure, malformed request/response)
                                            during THIS attempt; the probe stamp is written
                                            ok=false with the reason and a `kind` (below) so
                                            the NEXT attempt can decide whether to decline
                                            fast via exit 5. `kind="auth"`/`"budget"`/
                                            `"invalid"`/`"unknown"` never decline a later
                                            attempt -- those are scoped to one key/request/
                                            attempt, not the endpoint. A real
                                            `kind="unavailable"` (a 5xx response, Jev itself
                                            degraded) declines for `PROBE_FAIL_TTL_S` (5min,
                                            TRDD-RAEGS1D5 owner decision 2026-09-23 -- was
                                            30min); `kind="unreachable"` (a transport
                                            failure -- no response ever came back, may be
                                            local to this machine/lane) declines for the
                                            same-length `PROBE_UNREACHABLE_TTL_S` (5min) --
                                            long enough to skip the retry/backoff wall on a
                                            flapping network, short enough that a fixed local
                                            issue (DNS, a VPN) is retried again soon;
                                            `kind="rate_limited"` (a 429, a per-key limit
                                            rather than an outage) declines too, but only for
                                            the much shorter window `cmd_compact` derives from
                                            the server's own `Retry-After` value, and is NEVER
                                            bypassed by `--no-decline`.
                                      (2..4 are `probe`/`expand`'s own codes, listed above —
                                      one flat exit-code space across all three sub-commands
                                      so a caller never confuses e.g. `expand`'s 3 with
                                      `compact`'s 5..7.)

Probe stamp contract (single source of truth — every reader/writer of this file lives HERE,
never duplicated in arm_prepare.py or anywhere else): JSON at
``<global_state.control_dir()>/jev-probe.json`` (machine-wide, not per-project — matching
where ``armed.flag`` and the daemon's other control-plane files already live), shape
``{"ok": bool, "reason": str|None, "ts": epoch_seconds, "cost": float|None,
"model": None, "provider": str, "kind": str, "retry_after_s": float|None}``. ``model`` is
always ``None`` — nothing in this CLI's probe response carries a model name to put there.
``kind`` is one of ``"unavailable"``, ``"unreachable"``, ``"rate_limited"``, ``"auth"``,
``"budget"``, ``"invalid"``, ``"blocked"`` (TRDD-1ETALGDG — a Cloudflare edge block, never
declining, see ``_stamp_kind_for_error``), ``"unknown"``, ``"ok"`` (see ``write_probe_stamp``)
— it is
what `compact`'s decline gate keys on, not ``ok`` alone. ``retry_after_s`` is only ever
non-``None`` for ``kind="rate_limited"`` (the server's own ``Retry-After`` header value, in
seconds). Two TTLs, read by different callers: ``PROBE_OK_TTL_S`` (6h) documents how long an
``ok=true`` stamp should be considered current by an external reader; ``PROBE_FAIL_TTL_S``
(5min — TRDD-RAEGS1D5 owner decision 2026-09-23, was 30min) is the one this file itself
enforces for a ``kind="unavailable"`` stamp — ``kind="rate_limited"`` instead uses
``min(retry_after_s or _RATE_LIMIT_FALLBACK_TTL_S, 1800 if retry_after_s else
_RATE_LIMIT_MAX_TTL_S)`` — a server-STATED ``Retry-After`` is honoured up to 1800s, the 300s
``_RATE_LIMIT_MAX_TTL_S`` ceiling applies only to the no-header fallback guess (see
`cmd_compact`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

import global_state  # noqa: E402  -- needs the sys.path line above
import jev_compaction as jc  # noqa: E402
import jev_shadow_log as jsl  # noqa: E402  -- TRDD-N9LDHF7N card 7, shadow decision log
import jsonl_walk  # noqa: E402  -- TRDD-DQXMND59 stage 3: iter_jsonl_entries/parse_jsonl_line/drop_lone_surrogates moved here from jc, its new home
import state  # noqa: E402
from jevctx.openrouter import JevBlockedError  # noqa: E402  -- TRDD-1ETALGDG, see _stamp_kind_for_error
from jevctx.provider import DEFAULT_PROVIDER, PROVIDER_ENV, make_client  # noqa: E402
from jevctx.tokens import estimate_tokens  # noqa: E402
from jevctx.types import (  # noqa: E402
    JevAuthError,
    JevBudgetError,
    JevError,
    JevUnavailableError,
    JevValidationError,
    Noul,
)

# --------------------------------------------------------------------------- #
# Probe stamp — see module docstring for the full contract.
# --------------------------------------------------------------------------- #

PROBE_STAMP_NAME = "jev-probe.json"
PROBE_OK_TTL_S = 6 * 3600
# 30min -> 5min (TRDD-RAEGS1D5, owner decision 2026-09-23 R1): the owner's retry budget for
# a genuine Jev outage is 5 minutes total, not 30 -- a 30-minute decline window would have
# outlived that whole budget by 6x and made "retry for 5 minutes then fall back to llm-ext"
# unreachable in practice (every retry after the first would fast-decline instead of trying).
PROBE_FAIL_TTL_S = 5 * 60
# `kind="unreachable"` (DNS/TLS/offline -- no HTTP response ever came back) decline window.
# Card 5 content-fit (TRDD-RAEGS1D5): this used to live ONLY in `on-session-start-post-clear-
# compact.py`'s own `_PROBE_UNREACHABLE_TTL_S`, so `summarize_previous_session.py`'s detached
# lane (which also calls `run_compact` -> this CLI, but had no such pre-check of its own) paid
# the full retry/backoff wall (~70s) on every network outage while the hook's copy declined in
# microseconds -- two lanes, two policies for the same stamp. Moved into `cmd_compact`'s own
# decline gate, next to `PROBE_FAIL_TTL_S`, so every caller of this CLI honours ONE policy.
PROBE_UNREACHABLE_TTL_S = 5 * 60

# `kind="rate_limited"` decline window (see `cmd_compact`): a 429 is a per-key limit, not
# a whole-endpoint outage, so it earns a much shorter fast-decline TTL than
# `PROBE_FAIL_TTL_S` -- the server's own `Retry-After` value wins when the response sent one,
# `_RATE_LIMIT_FALLBACK_TTL_S` is the guess when it didn't. `_RATE_LIMIT_MAX_TTL_S` caps ONLY
# the fallback guess (300s, unchanged): a server-STATED `Retry-After` is honoured up to 1800s
# instead (TRDD-RAEGS1D5 card 3 C2) -- the server said how long it needs, and a 300s cap on
# that would make us retry into the SAME window it just asked us to wait out.
_RATE_LIMIT_FALLBACK_TTL_S = 60
_RATE_LIMIT_MAX_TTL_S = 300

# `compact`'s own tunables — CLAUDE_PLUGIN_OPTION_* env vars, read like every sibling script
# reads a plugin option (state.plugin_option, real env var wins over the settings.json
# mirror). Defaults match docs_dev/jev-compaction-spec.md card 3 / jev_compaction.py.
_BUDGET_ENV = "CLAUDE_PLUGIN_OPTION_JEV_COMPACT_BUDGET_TOKENS"
_RELEVANCE_ENV = "CLAUDE_PLUGIN_OPTION_JEV_RELEVANCE_THRESHOLD"
_DECISION_ENV = "CLAUDE_PLUGIN_OPTION_JEV_DECISION_THRESHOLD"
_DEFAULT_BUDGET_TOKENS = 8000


def _probe_stamp_path() -> Path:
    return global_state.control_dir() / PROBE_STAMP_NAME


def read_probe_stamp() -> dict[str, Any] | None:
    """The current probe stamp, or `None` if it doesn't exist / isn't valid JSON / isn't
    a JSON object.

    A missing or corrupt stamp is not an error here — it just means "no prior probe result
    to decide anything from", so every caller of this function already treats `None` as
    "proceed as if nothing is known" (`compact` proceeds instead of fast-declining). A
    torn write (a crash mid-write, or a reader racing `write_probe_stamp`'s
    tmp+`os.replace`) must never crash the CLI -- it is reported on stderr and treated
    the same as "no stamp".
    """
    path = _probe_stamp_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"probe stamp unreadable: {exc}", file=sys.stderr)
        return None
    if not isinstance(parsed, dict):
        print(f"probe stamp unreadable: not a JSON object ({path})", file=sys.stderr)
        return None
    return parsed


def write_probe_stamp(
    *, ok: bool, reason: str | None, cost: float | None, model: str | None, provider: str,
    kind: str, retry_after_s: float | None = None,
) -> None:
    """Atomically write the probe stamp — see module docstring for the shape/TTLs.

    ``kind`` classifies WHY (one of ``"unavailable"``, ``"unreachable"``,
    ``"rate_limited"``, ``"auth"``, ``"budget"``, ``"invalid"``, ``"blocked"``,
    ``"unknown"``, ``"ok"``)
    — `compact`'s fast-decline gate keys on it, not on ``ok`` alone: an
    ``auth``/``budget``/``invalid``/``blocked``/``unknown`` failure is scoped to THIS caller's
    key/request/attempt, not evidence the Jev endpoint itself is down, so none of them
    black out compaction for every other shell on the machine the way an ``unavailable``
    stamp correctly does. ``unreachable`` is the same non-decline-by-default treatment for
    a different reason: a transport failure means no response ever came back at all, which
    can be local to THIS machine/lane (e.g. the daemon's Python missing a CA bundle,
    TRDD-X6I04SAO) rather than Jev being down machine-wide — but it still gets its OWN
    (shorter) decline TTL, same as ``unavailable``, since a caller with no evidence either
    way should not hammer it either. ``rate_limited`` (a 429, retries exhausted) DOES
    decline a later attempt, but only briefly (see `cmd_compact`) — a per-key rate limit,
    not an outage. ``retry_after_s`` carries the server's own ``Retry-After`` value in
    seconds for a ``rate_limited`` stamp; ``None`` for every other ``kind``.
    """
    stamp = {"ok": ok, "reason": reason, "ts": time.time(), "cost": cost,
              "model": model, "provider": provider, "kind": kind,
              "retry_after_s": retry_after_s}
    state.atomic_write(_probe_stamp_path(), json.dumps(stamp))


def _stamp_kind_for_error(exc: JevError) -> str:
    """Classify a `JevError` into the probe-stamp `kind` — see `write_probe_stamp`.

    `JevUnavailableError` always carries `.status`/`.cause` (public attributes on the
    base class itself, set at every raise site in jev.py/openrouter.py -- see the
    class's own docstring in types.py), so this reads them directly, no `getattr`
    fallback and no private-subclass check needed. `status == 429` is its own `kind`
    (`"rate_limited"`) rather than folded into `"unavailable"`: it is a per-key rate
    limit, not evidence the whole endpoint is down (see `cmd_compact`'s decline gate).

    `JevValidationError` (TRDD-RAEGS1D5, owner decision 2026-09-23) maps to `"invalid"` --
    a 400/404/413/422/malformed-response is a bug in THIS one request, never evidence the
    endpoint itself is down, so (like `"auth"`/`"budget"`) it must NOT decline a later
    attempt. Before this fix `JevValidationError` fell through to the `"unavailable"`
    default below and declined every other caller on this machine for the (then 30-minute,
    now 5-minute) outage TTL -- a live, presently-reachable defect the owner's fallback
    review found (a 408/422/malformed-200-body response reaches this branch through
    ordinary HTTP traffic, not just a hypothetical future exception type).

    Any OTHER, genuinely unrecognized `JevError` subclass maps to `"unknown"` -- also
    non-declining (retrying/falling back on an unclassified error is safe; blacking out
    every other caller's compaction on one is not).

    `JevBlockedError` (TRDD-1ETALGDG) maps to `"blocked"` -- `jev_compaction.py::score_items`
    only ever lets one escape after every batch has been split down and retried per its own
    caps (see its docstring), so by the time this CLI sees one, the whole attempt genuinely
    could not compact anything. Still non-declining, same reasoning as `"invalid"`: a
    Cloudflare edge block is provoked by THIS request's content/volume, not evidence the
    OpenRouter endpoint itself is down, so it must not black out every other caller's
    compaction the way `"unavailable"` correctly does.
    """
    if isinstance(exc, JevBlockedError):
        return "blocked"
    if isinstance(exc, JevAuthError):
        return "auth"
    if isinstance(exc, JevBudgetError):
        return "budget"
    if isinstance(exc, JevValidationError):
        return "invalid"
    if isinstance(exc, JevUnavailableError):
        if exc.status == 429:
            return "rate_limited"
        return "unavailable" if exc.status is not None else "unreachable"
    return "unknown"


def _retry_after_for_stamp(exc: JevError) -> float | None:
    """`exc.retry_after` when `exc` is a `JevUnavailableError` (the only `JevError` shape
    that ever carries one); `None` for every other kind (`write_probe_stamp`'s own
    default for a non-`rate_limited` stamp)."""
    return exc.retry_after if isinstance(exc, JevUnavailableError) else None


def _current_provider() -> str:
    return (os.environ.get(PROVIDER_ENV) or DEFAULT_PROVIDER).strip() or DEFAULT_PROVIDER


def _coerce_float(value: str | None, default: float) -> float:
    """Like `state.coerce_int` but for a `[0, 1]`-ish threshold — no such helper exists in
    state.py (it only coerces non-negative ints), so this is the small local equivalent: an
    empty/unset/unparseable value silently falls back to `default` rather than crashing the
    CLI on a config typo."""
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def cmd_probe(_args: argparse.Namespace) -> int:
    """One Noul question through whichever provider `CLAUDE_PLUGIN_OPTION_JEV_PROVIDER`
    names. A probe failure must never look like a compaction failure to the caller, so it
    is always ONE line on stdout/stderr and a small, distinguishable exit code (2) —
    `arm_prepare.py` greps this line, it does not parse a traceback.

    A MANUAL check: unlike `compact`, this never reads or short-circuits on a cached probe
    stamp — it always actually probes. It DOES write the stamp on every outcome, so a human
    running `probe` by hand also refreshes what `compact`'s fast-decline path reads next."""
    provider = _current_provider()
    try:
        client = make_client()
    except JevError as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        write_probe_stamp(ok=False, reason=str(exc), cost=None, model=None, provider=provider,
                           kind=_stamp_kind_for_error(exc), retry_after_s=_retry_after_for_stamp(exc))
        return 2

    start = time.monotonic()
    try:
        answers = client.ask(
            state={"task": "probe", "items": [{"ref": "a", "text": "probe: is this text non-empty?"}]},
            questions={"a": Noul(instructions="Is the item's text non-empty?", true="non-empty", false="empty")},
        )
    except JevError as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        write_probe_stamp(ok=False, reason=str(exc), cost=None, model=None, provider=provider,
                           kind=_stamp_kind_for_error(exc), retry_after_s=_retry_after_for_stamp(exc))
        return 2
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    elapsed_ms = int((time.monotonic() - start) * 1000)

    answer = answers.get("a")
    noul = getattr(answer, "noul", None)
    if noul is None:
        reason = "response carried no 'a.noul' answer"
        print(f"probe failed: {reason}", file=sys.stderr)
        write_probe_stamp(ok=False, reason=reason, cost=None, model=None, provider=provider,
                           kind="unavailable")
        return 2
    cost = getattr(getattr(client, "usage", None), "cost", 0.0)
    write_probe_stamp(ok=True, reason=None, cost=cost, model=None, provider=provider, kind="ok")
    print(f"probe ok noul={noul} cost={cost} ms={elapsed_ms}")
    return 0


def _read_jsonl_entry(
    transcript: Path, target_uuid: str, *, malformed_lines: list[int],
) -> dict[str, Any] | None:
    """Scan the transcript for the entry with ``uuid == target_uuid``.

    A plain linear scan, not an index: a transcript is read here once per `expand` call,
    which is an interactive, occasional operation (a pointer the model chose to follow) —
    not the hot path card 3's compaction pass walks. Building an index for a one-shot CLI
    invocation would be optimizing a call that happens a handful of times per session.

    TRDD-DQXMND59 follow-up (adversarial review, 2026-09-24, finding B): this used to open
    the file in TEXT mode (`encoding="utf-8"`) and its own bare `json.loads` loop, so a
    single non-UTF-8 byte anywhere before `target_uuid`'s line raised `UnicodeDecodeError`
    and crashed `expand` outright -- the exact damage `compact`'s `extract_items` already
    knew how to skip. Now shares `jsonl_walk.iter_jsonl_entries`, the SAME byte-safe walk
    (stage 3: moved out of `jc` into its own stdlib-only module), so a damaged line earlier
    in the file no longer blocks reaching a healthy one later.
    """
    try:
        for _line_no, entry in jsonl_walk.iter_jsonl_entries(transcript, malformed_lines=malformed_lines):
            if entry.get("uuid") == target_uuid:
                return entry
    except OSError:
        return None
    return None


def _extract_block(entry: dict[str, Any], index: int) -> str | None:
    """The original bytes of block ``index`` of ``entry`` — user text (str content, index
    must be 0), or one block of a list-shaped ``user``/``assistant`` content (a
    ``text`` block's ``text``, or a ``tool_result`` block's ``content``, verbatim), or an
    ``attachment`` entry's queued prompt (the joined TEXT blocks only when the prompt is a
    list of content blocks -- see the WHY comment below; NOT byte-verbatim in that one case).
    ``thinking``/``tool_use`` blocks are not expandable on their own (card 3 pairs a
    ``tool_use`` with its ``tool_result`` — expanding the tool_result is the pointer)."""
    if entry.get("type") == "attachment":
        # TRDD-DQXMND59 follow-up (adversarial review of e23e0b39): this used to restate
        # `extract_items`'s attachment predicate (the `queued_command` type gate, the
        # prompt text-join) here, calling the OTHER module's PRIVATE `jc._tool_result_text`
        # directly -- two independent copies of one rule that could drift the moment either
        # changed without the other (matrix row V2: `expand` "not found" for a real pointer;
        # row V10: `expand` accepting an id `extract_items` never generated). Now calls
        # `jc.attachment_item_text`, the ONE shared, public rule -- see its own docstring.
        #
        # WHY this is not byte-verbatim like the other branches: `attachment_item_text` joins
        # only the `text`-type blocks of a list-shaped prompt (matching what `extract_items`
        # scores/inlines) -- an image or other non-text block in the same prompt is silently
        # excluded from the returned string, same as the docstring above now says.
        if index != 0:
            return None
        return jc.attachment_item_text(entry)
    message = entry.get("message")
    content = (message.get("content") if isinstance(message, dict) else None) or entry.get("content")
    if isinstance(content, str):
        return content if index == 0 else None
    if not isinstance(content, list):
        return None
    if index < 0 or index >= len(content):
        return None
    block = content[index]
    if not isinstance(block, dict):
        return None
    block_type = block.get("type")
    if block_type == "text":
        text = block.get("text")
        return text if isinstance(text, str) else None
    if block_type == "tool_result":
        result = block.get("content")
        if isinstance(result, str):
            return result
        if isinstance(result, list):
            # A structured tool_result: concatenate its own text sub-blocks verbatim.
            parts = [part.get("text", "") for part in result if isinstance(part, dict) and part.get("type") == "text"]
            return "\n".join(parts)
        return None
    return None


def cmd_expand(args: argparse.Namespace) -> int:
    transcript = Path(args.transcript)

    if args.list:
        # Card 5 content-fit (TRDD-RAEGS1D5, item 3): the "N more items not listed" line in
        # `jev_compaction.py::compose()`'s output used to be a dead end -- `expand` needs an id,
        # and an id never shown could never be named. Reuses `jc.extract_items`, the SAME
        # transcript walk `compact` itself does -- no re-scoring, no Jev call, just a parse.
        # `malformed_lines` is a REQUIRED keyword (finding A, adversarial review 2026-09-24) --
        # `--list` is a human-browsing aid over whatever items DID parse, not the compaction
        # record of truth, but a caller must still be TOLD a line was skipped, not left to
        # infer it from a shorter-than-expected listing. Printed to stderr below.
        # `segmentation_failures` is REQUIRED too now (stage 3, item E) -- this call used to
        # pass none at all, so a segmentation failure on this exact path was invisible; now
        # reported the same way as `malformed_lines`.
        malformed_lines: list[int] = []
        segmentation_failures: list[str] = []
        try:
            items = jc.extract_items(
                str(transcript), malformed_lines=malformed_lines,
                segmentation_failures=segmentation_failures,
            )
        except OSError as exc:
            print(f"expand --list failed: {exc}", file=sys.stderr)
            return 3
        if malformed_lines:
            print(f"expand --list: skipped {len(malformed_lines)} malformed line(s)", file=sys.stderr)
        if segmentation_failures:
            print(
                f"expand --list: {len(segmentation_failures)} tool result(s) fell back to "
                f"unsegmented after a segmentation failure", file=sys.stderr,
            )
        needle = args.grep.lower() if args.grep else None
        # Card 5 two-renderings (TRDD-RAEGS1D5, item 6): name the transcript this listing is
        # against -- a bare id/kind/preview table gives no way to tell which transcript it came
        # from once printed on its own (e.g. copy-pasted into a chat).
        print(f"transcript: {transcript}")
        shown = 0
        for it in items:
            if needle is not None and needle not in it.text.lower():
                continue
            if shown >= args.limit:
                break
            first_line = it.text.splitlines()[0] if it.text else ""
            print(f"{it.id}\t{it.kind}\t{first_line[:80]}")
            shown += 1
        if shown == 0:
            print("(no matching items)", file=sys.stderr)
        return 0

    if not args.id:
        print("expand failed: an id is required unless --list is given", file=sys.stderr)
        return 3

    # Card 6 (TRDD-88DOI824): a segment id is "<uuid>:<n>@<a>-<b>" -- split the span off
    # FIRST (rsplit on the last "@", matching real ids, which never carry one otherwise) so
    # the "<uuid>:<n>" half below is parsed exactly as it always was, pre-card-6.
    id_part = args.id
    line_span: tuple[int, int] | None = None
    if "@" in id_part:
        id_part, span_str = id_part.rsplit("@", 1)
        try:
            start_str, end_str = span_str.split("-", 1)
            line_span = (int(start_str), int(end_str))
        except ValueError:
            print(
                f"expand failed: malformed id {args.id!r}, expected '<uuid>:<n>@<a>-<b>'",
                file=sys.stderr,
            )
            return 3

    try:
        target_uuid, index_str = id_part.rsplit(":", 1)
        index = int(index_str)
    except ValueError:
        print(f"expand failed: malformed id {args.id!r}, expected '<uuid>:<n>'", file=sys.stderr)
        return 3

    expand_malformed_lines: list[int] = []
    entry = _read_jsonl_entry(transcript, target_uuid, malformed_lines=expand_malformed_lines)
    if expand_malformed_lines:
        print(
            f"expand: skipped {len(expand_malformed_lines)} malformed line(s)", file=sys.stderr,
        )
    if entry is None:
        print(f"expand failed: no transcript entry with uuid={target_uuid!r} in {transcript}", file=sys.stderr)
        return 3

    text = _extract_block(entry, index)
    if text is None:
        print(f"expand failed: no block {index} in entry {target_uuid!r}", file=sys.stderr)
        return 3

    if line_span is not None:
        # `jev_compaction.py::_segment_tool_result` sliced ITS segment from this SAME raw
        # block text (never the synthetic "name(input)\n" prefix) -- see that function's own
        # docstring for why the two must agree on what "the original" is.
        start, end = line_span
        lines = text.splitlines(keepends=True)
        if start < 1 or end < start or end > len(lines):
            print(
                f"expand failed: line span {start}-{end} out of range for block {index} "
                f"in entry {target_uuid!r} ({len(lines)} lines)",
                file=sys.stderr,
            )
            return 3
        text = "".join(lines[start - 1:end])

    # TRDD-N9LDHF7N card 7: an expand of an id `compact` had logged as elided is a false
    # negative -- ground truth the gate was too aggressive (jevctx.shadow.ShadowLog's own
    # docstring). Logged only on this SUCCESS path (never for --list, never for a malformed
    # id that exits 3 above): those never resolve to a real item, so there is nothing to
    # match against a prior decision.
    jsl.log_expand_outcome(args.id)

    # TRDD-DQXMND59 stage 3, finding A: `text` here is the RAW block bytes -- unlike an
    # `Item.text` (sanitized once, at construction, in `Item.__post_init__`), nothing upstream
    # of this print has ever run it through `drop_lone_surrogates`. A lone (unpaired) UTF-16
    # surrogate in the transcript (e.g. `"\ud83d"`, an emoji a writer's own bug cut in half) is
    # valid JSON and parses fine, but `print()` to a UTF-8 stdout raises `UnicodeEncodeError` on
    # it -- the exact crash `compose()`'s byte-budget accounting used to hit before `Item` was
    # sanitized, now one layer up, on the one path (`expand`) that builds text WITHOUT going
    # through `Item` at all.
    print(jsonl_walk.drop_lone_surrogates(text))
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    """TRDD-N9LDHF7N card 7: print `ShadowStats` for `--threshold` against the persisted
    shadow decision log -- an offline tuning tool over past `compact` runs, no network call
    and no transcript walk. Always exits 0: a missing or empty log just replays as zero
    decisions (`jsl.replay_stats` treats "no file" the same as "no matching rows")."""
    stats = jsl.replay_stats(args.threshold, question=args.question)
    print(stats)
    return 0


def cmd_compact(args: argparse.Namespace) -> int:
    """Compose the compacted context and write it to `args.out` atomically.

    Order matters and is deliberate (see the module docstring's exit-code table): the probe
    stamp is checked BEFORE reading the transcript or building anything, so a known-down Jev
    declines in microseconds rather than after paying the cost of walking a
    (possibly 24-258 MB, per the spec) transcript file first.

    Card 5 two-renderings (TRDD-RAEGS1D5): score ONCE, render up to TWICE. `--out` always gets
    the FULL, uncapped-by-default document (card-3 sizing: `--budget-tokens`'s own default,
    up to `_MAX_ELIDED_POINTERS` pointers, the full digest) -- a caller's `--max-elided-
    pointers`/`--inject-max-bytes` no longer shrink it. When `--inject-out` is also given, a SECOND
    `jc.compose()` call over the SAME `items`/`scores` (no second scoring pass) renders a
    capped companion there: the digest omitted (it dominated the old single-document size --
    the full digest is still in `--out`), `--max-elided-pointers`/`--inject-max-bytes` applied,
    and a READ FIRST first line naming `--out`'s absolute path.

    TRDD-D7RLXAN1: only tool and event items are scored. Every owner/assistant message since
    the session's last compaction is kept verbatim -- whole in `--out` (after Claude Code's own
    compaction summary), the newest exchanges in `--inject-out`.
    """
    provider = _current_provider()

    stamp = read_probe_stamp()
    # Decline on kind="unavailable" (a real, machine-wide outage -- the full
    # PROBE_FAIL_TTL_S) or kind="rate_limited" (a per-key 429 -- a much shorter window
    # derived from the server's own Retry-After, since it is not evidence the endpoint
    # itself is down). An auth or budget failure is scoped to this caller's key/request,
    # not evidence the Jev endpoint itself is down, so it must not black out compaction
    # machine-wide the way these two do (see write_probe_stamp's docstring). Those
    # stamps still exist for a caller to surface as a finding; they just don't gate the
    # NEXT attempt.
    #
    # `--no-decline` (TRDD-RAEGS1D5, owner decision 2026-09-23 R1): bypasses the
    # `kind="unavailable"` AND `kind="unreachable"` branches -- NEVER `rate_limited`. This
    # widened the original card-5 behaviour (which bypassed `unreachable` only): the
    # AUTOMATIC retry lane (`jev_compaction_lane.run_compact_with_fallback`) now also passes
    # `--no-decline` on every retry inside its owner-mandated 5-minute budget, and with the
    # OLD narrower bypass a real outage would stamp `kind="unavailable"` on attempt 1 and
    # every later retry would exit 5 in microseconds for the rest of the window -- "retry for
    # 5 minutes" would have meant one real attempt plus a 5-minute sleep. `rate_limited` stays
    # gated even with `--no-decline`: a 429 is the SERVER explicitly asking for a wait, and a
    # manual or automatic caller must not be allowed to hammer straight through that.
    if stamp is not None and stamp.get("ok") is False:
        kind = stamp.get("kind")
        age_s = time.time() - float(stamp.get("ts", 0))
        ttl: float | None = None
        if kind == "unavailable" and not args.no_decline:
            ttl = PROBE_FAIL_TTL_S
        elif kind == "unreachable" and not args.no_decline:
            ttl = PROBE_UNREACHABLE_TTL_S
        elif kind == "rate_limited":
            retry_after_s = stamp.get("retry_after_s")
            base = retry_after_s if isinstance(retry_after_s, (int, float)) else _RATE_LIMIT_FALLBACK_TTL_S
            ttl = min(base, 1800 if isinstance(retry_after_s, (int, float)) else _RATE_LIMIT_MAX_TTL_S)
        if ttl is not None and age_s < ttl:
            reason = stamp.get("reason") or "unknown"
            print(f"declined: recent probe failure: {reason}", file=sys.stderr)
            return 5

    start = time.monotonic()
    # Coordinator follow-up (review of commit 3006e92f): a segmentation failure (degrades to
    # the pre-card-6 whole item, see jev_compaction.py::_segment_tool_result) already prints
    # a stderr line, but stderr alone is easy to miss -- this list is appended to in place and
    # its length feeds the `segmentation_failed=N` summary field below, so it is never silent
    # to a caller that only reads stdout.
    segmentation_failures: list[str] = []
    # TRDD-DQXMND59: mirrors `segmentation_failures` above -- a skipped-line count feeds the
    # `malformed=N` summary field below, so a damaged transcript is never silently under-read.
    malformed_lines: list[int] = []
    window = jc.ConversationWindow()
    items = jc.extract_items(
        args.transcript, segmentation_failures=segmentation_failures, window=window,
        malformed_lines=malformed_lines,
    )
    # TRDD-D7RLXAN1 (owner directive 2026-09-24: "assistant prose and user prose (the messages
    # exchanges) should be all kept intact"): THE enforcement point. Owner/assistant/control
    # messages are split off here and never reach `score_items`, so no Jev score can drop one;
    # the compose calls below render them verbatim. A prompt sentence could not guarantee this:
    # a kept/elided decision is a threshold on a returned probability.
    conversation, scored = jc.split_conversation(items, window)

    state_heads: list[str] = []
    for head_path in args.state_heads or []:
        try:
            state_heads.append(Path(head_path).read_text(encoding="utf-8"))
        except OSError as exc:
            # A missing/unreadable STATE head file degrades the digest, it does not abort
            # the whole compaction -- the remaining heads and human messages may still be
            # enough to build one.
            print(f"compact: skipping unreadable state head {head_path!r}: {exc}", file=sys.stderr)

    try:
        # `items`, not `scored`: the newest owner/assistant messages are Jev's TASK context
        # (what each tool item is judged relevant to), never a scored item (advisor, TRDD-D7RLXAN1).
        digest = jc.build_digest(items, state_heads, cap_tokens=args.digest_tokens)
    except jc.NoDigest as exc:
        print(f"declined: no digest material: {exc}", file=sys.stderr)
        return 6

    client = None
    try:
        client = make_client()
        scores = jc.score_items(
            scored, digest, client,
            relevance_threshold=args.relevance_threshold,
            decision_threshold=args.decision_threshold,
        )
    except JevBudgetError as exc:
        # A budget violation is the planner's own bug (a request shape it should never have
        # built), not an outage -- kept as its own branch so the message and stamp kind say
        # so, instead of being folded into the generic "compact failed" outage wording below.
        reason = str(exc)
        print(f"budget: {reason}", file=sys.stderr)
        write_probe_stamp(ok=False, reason=reason, cost=None, model=None, provider=provider,
                           kind="budget")
        return 7
    except JevError as exc:
        reason = str(exc)
        print(f"compact failed: {reason}", file=sys.stderr)
        write_probe_stamp(ok=False, reason=reason, cost=None, model=None, provider=provider,
                           kind=_stamp_kind_for_error(exc), retry_after_s=_retry_after_for_stamp(exc))
        return 7
    finally:
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    # TRDD-N9LDHF7N card 7: log every keep/elide decision the scoring pass above just made --
    # from the scores already in hand, never a hook inside jev_compaction.py itself. An
    # OSError write failure is already swallowed inside jsl.log_decisions itself (one stderr
    # line, never raises). Coordinator's decision (card 7 follow-up, fourth round): the
    # card's rule is the shadow log never breaks a compaction AND never fails silently -- so
    # this call site is ALSO the boundary for any OTHER unexpected exception jsl can raise
    # (the zip-mismatch guard's `ValueError` on an internal-consistency violation, or
    # anything else): caught here, named on stderr, and surfaced in the CLI summary line
    # below (`shadow_log_failed=1`) rather than left silent -- the compaction itself still
    # completes and exits 0 either way.
    shadow_log_failed = False
    try:
        # TRDD-D7RLXAN1: `scored` -- log only what was scored. Not forced by jsl's zip guard (an
        # unscored item is skipped before it, advisor finding E); the prose rows just vanish.
        jsl.log_decisions(
            scored, scores,
            relevance_threshold=args.relevance_threshold, decision_threshold=args.decision_threshold,
            # TRDD-N9LDHF7N card 7 follow-up, defect 3: the sync SessionStart lane and the
            # detached background lane can both `compact` the same just-closed session's
            # transcript -- `session_key` (already threaded through for the compose header) plus
            # the transcript's own byte size lets jsl dedupe a run it already logged.
            session_key=args.session_key, transcript_path=args.transcript,
        )
    except Exception as exc:  # noqa: BLE001 -- the shadow log must never break a real compaction
        shadow_log_failed = True
        print(f"jev-shadow: {type(exc).__name__}: {exc}", file=sys.stderr)

    usage = getattr(client, "usage", None)
    usage_tokens = getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0)
    usage_cost = getattr(usage, "cost", 0.0)

    compose_header: dict[str, Any] = {
        "transcript_path": str(args.transcript),
        "session_key": args.session_key or "",
        "digest": digest,
        "usage": {"tokens": usage_tokens, "cost": usage_cost},
    }

    # The FULL document -- card-3 sizing throughout (`--budget-tokens`'s own default, the
    # default pointer cap, no byte backstop). Never shrunk by `--max-elided-pointers`/
    # `--inject-max-bytes`, which apply ONLY to the `--inject-out` rendering below.
    out_path = Path(args.out)
    # TRDD-D7RLXAN1: the full copy carries Claude Code's own summary and every live message,
    # whole -- it is the READ FIRST target the injected copy names.
    full_doc = jc.compose(
        scored, scores, budget_tokens=args.budget_tokens, header=compose_header,
        conversation=conversation, conversation_summary=window.summary,
    )
    state.atomic_write(out_path, full_doc)

    if args.inject_out:
        inject_kwargs: dict[str, Any] = {}
        if args.max_elided_pointers is not None:
            inject_kwargs["max_elided_pointers"] = args.max_elided_pointers
        if args.inject_max_bytes is not None:
            inject_kwargs["max_bytes"] = args.inject_max_bytes
        # The digest dominated the old single-document size (measured ~11KB, reports/
        # compaction-replacement/) -- omitted here on purpose; the full digest still lives in
        # `--out`, and the READ FIRST line (`full_context_path`) points there.
        inject_header = dict(compose_header)
        inject_header["digest"] = ""
        # TRDD-RAEGS1D5 (injected-copy content fix): `max_item_bytes` is ALWAYS passed for the
        # injected render, unconditionally on `--inject-max-bytes` -- it is what makes a kept
        # item show up as a verbatim prefix instead of being evicted whole (see `compose()`'s
        # own docstring); measured on three real transcripts, the old whole-item-only eviction
        # rendered 3, 0 and 0 kept items into the injected copy.
        inject_doc = jc.compose(
            scored, scores, budget_tokens=args.budget_tokens, header=inject_header,
            full_context_path=str(out_path.resolve()),
            conversation=conversation,
            max_item_bytes=jc.DEFAULT_INJECT_ITEM_BYTES,
            # TRDD-RAEGS1D5 (jev newest+3): a smaller cap for NON-owner items only, so the
            # session's own tool calls/replies/events are not crowded out by owner messages
            # sharing the same per-item cap in a tight injected render -- see that constant's
            # own docstring in jev_compaction.py.
            non_owner_item_bytes=jc.DEFAULT_INJECT_NON_OWNER_ITEM_BYTES,
            **inject_kwargs,
        )
        state.atomic_write(Path(args.inject_out), inject_doc)

    write_probe_stamp(ok=True, reason=None, cost=usage_cost, model=None, provider=provider,
                       kind="ok")

    kept = sum(1 for s in scores.values() if s.kept and not s.oversized)
    # TRDD-1ETALGDG followup: `blocked` counts items `jc.score_items` could never get scored
    # at all (a provider firewall block or an oversized batch that survived every split
    # retry) -- invisible before this, since a partially-blocked compaction still exits 0
    # like a fully clean one. `blocked_digest` is a hash of the blocked items' own TEXT
    # (never the text itself), sorted before hashing so split/retry ORDER never changes it
    # for identical content -- `jev_compaction_lane.py` uses it as a cross-SESSION dedupe
    # key (item ids embed the transcript's own uuids, which differ every session; the
    # blocked CONTENT is what actually recurs).
    blocked_items = [it for it in scored if scores[it.id].blocked]
    blocked_digest = ""
    if blocked_items:
        item_hashes = sorted(
            hashlib.sha256(it.text.encode("utf-8")).hexdigest() for it in blocked_items
        )
        blocked_digest = hashlib.sha256("".join(item_hashes).encode("utf-8")).hexdigest()
    elapsed_ms = int((time.monotonic() - start) * 1000)
    out_tokens = estimate_tokens(full_doc)
    # TRDD-D7RLXAN1: `items=` counts only the scored items; `conversation=` the verbatim, never-
    # scored messages. Appended after `blocked=… blocked_digest=…`, which the lane's regex reads.
    summary = (
        f"compacted items={kept}/{len(scored)} tokens={out_tokens} cost={usage_cost} "
        f"ms={elapsed_ms} blocked={len(blocked_items)} blocked_digest={blocked_digest} "
        f"segmentation_failed={len(segmentation_failures)} conversation={len(conversation)} "
        f"malformed={len(malformed_lines)}"
    )
    # Coordinator's decision: `shadow_log_failed=1` is appended at the very END, after every
    # existing field -- `jev_compaction_lane.py`'s own `blocked=… blocked_digest=…` regex
    # (unchanged, not touched this round) keeps matching regardless. Only added on an actual
    # failure, so a healthy compaction's summary line is byte-for-byte what it always was.
    if shadow_log_failed:
        summary += " shadow_log_failed=1"
    print(summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jev_compact")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", help="one Noul question through the configured Jev provider")

    p_expand = sub.add_parser("expand", help="print the original bytes of one transcript item")
    p_expand.add_argument("--transcript", required=True)
    p_expand.add_argument("id", nargs="?", default=None)
    # Card 5 content-fit (TRDD-RAEGS1D5, item 3): list/search every item's id instead of
    # expanding one -- the way back to an id the capped pointer list didn't name.
    p_expand.add_argument("--list", action="store_true")
    p_expand.add_argument("--grep", default=None)
    # Card 5 two-renderings (TRDD-RAEGS1D5, item 6): a real transcript can hold thousands of
    # items -- an unbounded `--list` is its own dead end, just a bigger one. 50 is a screenful;
    # `--grep` narrows further, `--limit` widens when 50 genuinely is not enough.
    p_expand.add_argument("--limit", type=int, default=50)

    p_replay = sub.add_parser(
        "replay", help="print ShadowStats for a hypothetical threshold (TRDD-N9LDHF7N card 7)"
    )
    p_replay.add_argument("--threshold", type=float, required=True)
    p_replay.add_argument("--question", choices=["relevance", "decision"], default="relevance")

    p_compact = sub.add_parser("compact", help="compose the compacted context (card 3)")
    p_compact.add_argument("--transcript", required=True)
    p_compact.add_argument("--out", required=True)
    p_compact.add_argument("--session-key", default="")
    p_compact.add_argument("--state-heads", nargs="*", default=[])
    p_compact.add_argument("--digest-tokens", type=int, default=4000)
    p_compact.add_argument(
        "--budget-tokens", type=int,
        default=state.coerce_int(state.plugin_option(_BUDGET_ENV), _DEFAULT_BUDGET_TOKENS),
    )
    p_compact.add_argument(
        "--relevance-threshold", type=float,
        default=_coerce_float(state.plugin_option(_RELEVANCE_ENV), jc.DEFAULT_RELEVANCE_THRESHOLD),
    )
    p_compact.add_argument(
        "--decision-threshold", type=float,
        default=_coerce_float(state.plugin_option(_DECISION_ENV), jc.DEFAULT_DECISION_THRESHOLD),
    )
    # Card 5 two-renderings (TRDD-RAEGS1D5): `--out` is now ALWAYS the full, card-3-sized
    # document -- these two apply ONLY to the optional `--inject-out` rendering below, never to
    # `--out` itself (see `cmd_compact`'s own docstring: "score once, render twice").
    p_compact.add_argument("--max-elided-pointers", type=int, default=None)
    # `--inject-out`/`--inject-max-bytes`: when given, a SECOND `jc.compose()` call over the
    # SAME scored items renders a capped companion document at this path, sized to fit
    # `--inject-max-bytes` (the digest omitted, a READ FIRST line pointing at `--out`). Unset
    # means "no second rendering" -- a bare manual `compact` invocation is unchanged.
    p_compact.add_argument("--inject-out", default=None)
    p_compact.add_argument("--inject-max-bytes", type=int, default=None)
    # Card 5 two-renderings (TRDD-RAEGS1D5, item 5) + owner decision 2026-09-23 R1: the
    # SYNCHRONOUS SessionStart hook always honours the early decline gate below (one bounded
    # attempt, must not hammer a known outage); an explicit compact-now request, AND the
    # AUTOMATIC retry lane's own bounded 5-minute budget (`jev_compaction_lane.
    # run_compact_with_fallback`), both pass `--no-decline` to bypass the `unavailable`/
    # `unreachable` branches -- `rate_limited` is never bypassed (see `cmd_compact`).
    p_compact.add_argument("--no-decline", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "probe":
        return cmd_probe(args)
    if args.command == "expand":
        return cmd_expand(args)
    if args.command == "replay":
        return cmd_replay(args)
    return cmd_compact(args)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
