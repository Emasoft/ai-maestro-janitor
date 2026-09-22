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
                                      the entry or the block index isn't found.
  compact --transcript P --out F   — compose the compacted context (card 3) and write it to
                                      F atomically. Exit code contract (a part C caller
                                      branches on these, so each is deliberate and stable):
                                        0 — wrote F; one summary line on stdout.
                                        5 — declined: a probe-stamp failure younger than
                                            PROBE_FAIL_TTL_S says Jev is down right now — no
                                            network fan-out into a known outage. Gated on
                                            stamp `kind == "unavailable"` ONLY: an `auth` or
                                            `budget` stamp never declines a later attempt —
                                            those are scoped to one key/request, not the
                                            endpoint, so the caller surfaces them as a
                                            finding instead of the whole machine going dark.
                                        6 — declined: `jev_compaction.NoDigest` — neither a
                                            human message nor a TRDD STATE head exists, so
                                            there is nothing to judge relevance against.
                                        7 — a Jev error (missing/bad key, budget violation,
                                            scorer failure) during THIS attempt; the probe
                                            stamp is written ok=false with the reason and a
                                            `kind` (below) so the NEXT attempt can decide
                                            whether to decline fast via exit 5. `kind=
                                            "unreachable"` (a transport failure -- no
                                            response ever came back, may be local to this
                                            machine/lane) never declines a later attempt
                                            either, same as `auth`/`budget` -- a real
                                            `kind="unavailable"` (a 5xx response, Jev
                                            itself degraded) declines for the full
                                            `PROBE_FAIL_TTL_S`; `kind="rate_limited"` (a
                                            429, a per-key limit rather than an outage)
                                            declines too, but only for the much shorter
                                            window `cmd_compact` derives from the
                                            server's own `Retry-After` value.
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
``"budget"``, ``"ok"`` (see ``write_probe_stamp``) — it is
what `compact`'s decline gate keys on, not ``ok`` alone. ``retry_after_s`` is only ever
non-``None`` for ``kind="rate_limited"`` (the server's own ``Retry-After`` header value, in
seconds). Two TTLs, read by different callers: ``PROBE_OK_TTL_S`` (6h) documents how long an
``ok=true`` stamp should be considered current by an external reader; ``PROBE_FAIL_TTL_S``
(30min) is the one this file itself enforces for a ``kind="unavailable"`` stamp —
``kind="rate_limited"`` instead uses ``min(retry_after_s or _RATE_LIMIT_FALLBACK_TTL_S, 1800
if retry_after_s else _RATE_LIMIT_MAX_TTL_S)`` — a server-STATED ``Retry-After`` is honoured
up to 1800s, the 300s ``_RATE_LIMIT_MAX_TTL_S`` ceiling applies only to the no-header fallback
guess (see `cmd_compact`).
"""

from __future__ import annotations

import argparse
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
import state  # noqa: E402
from jevctx.provider import DEFAULT_PROVIDER, PROVIDER_ENV, make_client  # noqa: E402
from jevctx.tokens import estimate_tokens  # noqa: E402
from jevctx.types import (  # noqa: E402
    JevAuthError,
    JevBudgetError,
    JevError,
    JevUnavailableError,
    Noul,
)

# --------------------------------------------------------------------------- #
# Probe stamp — see module docstring for the full contract.
# --------------------------------------------------------------------------- #

PROBE_STAMP_NAME = "jev-probe.json"
PROBE_OK_TTL_S = 6 * 3600
PROBE_FAIL_TTL_S = 30 * 60

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
    ``"rate_limited"``, ``"auth"``, ``"budget"``, ``"ok"``) — `compact`'s fast-decline
    gate keys on it, not on ``ok`` alone: an ``auth``/``budget`` failure is a
    config/planner bug specific to THIS caller's key or request shape, not evidence the
    Jev endpoint itself is down, so it must not black out compaction for every other
    shell on the machine the way an ``unavailable`` stamp correctly does. ``unreachable``
    is the same non-decline treatment for a different reason: a transport failure means
    no response ever came back at all, which can be local to THIS machine/lane (e.g. the
    daemon's Python missing a CA bundle, TRDD-X6I04SAO) rather than Jev being down
    machine-wide. ``rate_limited`` (a 429, retries exhausted) DOES decline a later
    attempt, but only briefly (see `cmd_compact`) — a per-key rate limit, not an outage.
    ``retry_after_s`` carries the server's own ``Retry-After`` value in seconds for a
    ``rate_limited`` stamp; ``None`` for every other ``kind``.
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
    Any OTHER `JevError` subclass this CLI itself might raise maps to `"unavailable"`,
    the conservative default.
    """
    if isinstance(exc, JevAuthError):
        return "auth"
    if isinstance(exc, JevBudgetError):
        return "budget"
    if isinstance(exc, JevUnavailableError):
        if exc.status == 429:
            return "rate_limited"
        return "unavailable" if exc.status is not None else "unreachable"
    return "unavailable"


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


def _read_jsonl_entry(transcript: Path, target_uuid: str) -> dict[str, Any] | None:
    """Scan the transcript for the entry with ``uuid == target_uuid``.

    A plain linear scan, not an index: a transcript is read here once per `expand` call,
    which is an interactive, occasional operation (a pointer the model chose to follow) —
    not the hot path card 3's compaction pass walks. Building an index for a one-shot CLI
    invocation would be optimizing a call that happens a handful of times per session.
    """
    try:
        with transcript.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("uuid") == target_uuid:
                    return entry
    except OSError:
        return None
    return None


def _extract_block(entry: dict[str, Any], index: int) -> str | None:
    """The original bytes of block ``index`` of ``entry`` — user text (str content, index
    must be 0), or one block of a list-shaped ``user``/``assistant`` content (a
    ``text`` block's ``text``, or a ``tool_result`` block's ``content``, verbatim).
    ``thinking``/``tool_use`` blocks are not expandable on their own (card 3 pairs a
    ``tool_use`` with its ``tool_result`` — expanding the tool_result is the pointer)."""
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
    try:
        target_uuid, index_str = args.id.rsplit(":", 1)
        index = int(index_str)
    except ValueError:
        print(f"expand failed: malformed id {args.id!r}, expected '<uuid>:<n>'", file=sys.stderr)
        return 3

    entry = _read_jsonl_entry(transcript, target_uuid)
    if entry is None:
        print(f"expand failed: no transcript entry with uuid={target_uuid!r} in {transcript}", file=sys.stderr)
        return 3

    text = _extract_block(entry, index)
    if text is None:
        print(f"expand failed: no block {index} in entry {target_uuid!r}", file=sys.stderr)
        return 3

    print(text)
    return 0


def cmd_compact(args: argparse.Namespace) -> int:
    """Compose the compacted context and write it to `args.out` atomically.

    Order matters and is deliberate (see the module docstring's exit-code table): the probe
    stamp is checked BEFORE reading the transcript or building anything, so a known-down Jev
    declines in microseconds rather than after paying the cost of walking a
    (possibly 24-258 MB, per the spec) transcript file first.
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
    if stamp is not None and stamp.get("ok") is False:
        kind = stamp.get("kind")
        age_s = time.time() - float(stamp.get("ts", 0))
        ttl: float | None = None
        if kind == "unavailable":
            ttl = PROBE_FAIL_TTL_S
        elif kind == "rate_limited":
            retry_after_s = stamp.get("retry_after_s")
            base = retry_after_s if isinstance(retry_after_s, (int, float)) else _RATE_LIMIT_FALLBACK_TTL_S
            ttl = min(base, 1800 if isinstance(retry_after_s, (int, float)) else _RATE_LIMIT_MAX_TTL_S)
        if ttl is not None and age_s < ttl:
            reason = stamp.get("reason") or "unknown"
            print(f"declined: recent probe failure: {reason}", file=sys.stderr)
            return 5

    start = time.monotonic()
    items = jc.extract_items(args.transcript)

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
        digest = jc.build_digest(items, state_heads, cap_tokens=args.digest_tokens)
    except jc.NoDigest as exc:
        print(f"declined: no digest material: {exc}", file=sys.stderr)
        return 6

    client = None
    try:
        client = make_client()
        scores = jc.score_items(
            items, digest, client,
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

    usage = getattr(client, "usage", None)
    usage_tokens = getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0)
    usage_cost = getattr(usage, "cost", 0.0)

    doc = jc.compose(
        items, scores, budget_tokens=args.budget_tokens,
        header={
            "transcript_path": str(args.transcript),
            "session_key": args.session_key or "",
            "digest": digest,
            "usage": {"tokens": usage_tokens, "cost": usage_cost},
        },
    )
    state.atomic_write(Path(args.out), doc)
    write_probe_stamp(ok=True, reason=None, cost=usage_cost, model=None, provider=provider,
                       kind="ok")

    kept = sum(1 for s in scores.values() if s.kept and not s.oversized)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    out_tokens = estimate_tokens(doc)
    print(f"compacted items={kept}/{len(items)} tokens={out_tokens} cost={usage_cost} ms={elapsed_ms}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jev_compact")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", help="one Noul question through the configured Jev provider")

    p_expand = sub.add_parser("expand", help="print the original bytes of one transcript item")
    p_expand.add_argument("--transcript", required=True)
    p_expand.add_argument("id")

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

    args = parser.parse_args(argv)
    if args.command == "probe":
        return cmd_probe(args)
    if args.command == "expand":
        return cmd_expand(args)
    return cmd_compact(args)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
