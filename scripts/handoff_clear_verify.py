#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Cross-/clear verification harness for /janitor-handoff-and-clear (TRDD-Z582IKIR P1).

The handoff+clear primitive rests on several assumptions that must be PROVEN LIVE,
not inferred:
  1. The heartbeat cron is HEALTHY after `/clear` — either it SURVIVES unchanged
     (the common case: `/clear` resets the conversation but keeps the same process,
     so the in-memory cron usually just survives it) or it is destroyed-and-recreated
     on builds where `/clear` does drop it. `on-session-start.py`'s own re-arm nudge
     is CONDITIONAL — "if it is missing, run /janitor-arm" — so a cron that never went
     missing is never re-armed, and that is healthy, not a defect (see #186; a prior
     version of this harness asserted destruction+recreation UNCONDITIONALLY and
     FAILED on a build where the cron simply survived — the false assumption, not the
     primitive). Only a cron that is GONE after `/clear` and never comes back is real.
  2. `/clear` collapses the context to base-size (the whole reason to prefer it
     over `/compact`).
  3. The link-only handoff is RECOVERABLE — every `[[wikimem link]]` it carries
     resolves via memgrep in the fresh session.
  4. The `resume-after-clear.flag` is consumed and `[janitor-resume]` is emitted.
  5. SessionStart re-armed AFTER the clear — but ONLY when assumption 1 found the
     cron missing/destroyed. When the cron simply survived unchanged, SessionStart's
     conditional re-arm correctly did nothing, so "no fresh re-arm" there is the
     healthy outcome (#186), not a failure.

This harness spans the boundary with a PERSISTENT log that survives /clear
(`.janitor/state/handoff-clear-verify.json` — a filesystem file, not session
state):

  --phase before  (run by the skill in the INVOKING session, right before /clear):
      snapshot ground truth — the stored cron id, live context size, the handoff's
      byte size + `[[link]]` count + the extracted link list, and the rotator /
      token-meter log tails. Written to the JSON.

  --phase after   (run by the resumed session, driven by the resume directive):
      re-read the cron id (≠ before ⇒ classified by the re-arm's CronDelete evidence when
      present in the after-snapshot; neutral wording otherwise — see compute_verdicts), the
      context size (« before ⇒ collapse proven), resolve EACH persisted link via memgrep (all
      resolve ⇒ handoff recoverable), confirm the resume flag was consumed, and
      confirm a re-arm happened after the snapshot (⇒ SessionStart ran on clear).
      Emits a PASS/FAIL table to reports/continuity-build/.

FAIL-OPEN throughout: this is a DIAGNOSTIC. A fault here must NEVER break the
resume — every gather is best-effort and a missing signal degrades a check to SKIP,
never to a crash.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

import handoff_files  # noqa: E402 - needs the sys.path line above

_VERIFY_FILENAME = "handoff-clear-verify.json"
_CRON_ID_FILENAME = "heartbeat-cron-id.txt"
_ARMED_AT_FILENAME = "heartbeat-armed-at.ts"
_RESUME_FLAG_FILENAME = "resume-after-clear.flag"
_RESUME_CONSUMED_FILENAME = "resume-consumed.ts"
# How far above the install's measured base a fresh session may sit and still count as
# "collapsed". A clear cannot land BELOW the floor — the base reloads by definition — and the
# first turn adds a little on top of it, so an exact-equality test would fail every real run.
_FLOOR_MARGIN = 0.10
_TOKEN_METER_FILENAME = "token-meter.jsonl"
# SessionStart-injection estimate: ~4 characters per token (see `_session_start_injected_tokens`).
_CHARS_PER_TOKEN = 4
# A new session counts as the clear's only if its first record is this soon after the before-phase ts.
_NEW_SESSION_WINDOW_S = 15 * 60
# The tool-result line a successful CronDelete prints ("Cancelled job <id>") — direct evidence
# the deleted id still existed, when paired with its CronDelete tool_use. CronDelete fails
# not-found for a dead id, so this line for the PRIOR heartbeat id proves that id SURVIVED the
# /clear (TRDD-5ID9CQY8 box 4).
_CANCELLED_JOB_RE = re.compile(r"Cancelled job ([A-Za-z0-9_-]{1,64})")

# A wikilink target: the text inside [[ ]], up to a `|` alias or `#` anchor. Kept
# permissive (letters/digits/dash/underscore/slash/dot/space) so a real page slug is
# captured whole but a stray `[[` in prose can't run away to the end of the file.
_WIKILINK_RE = re.compile(r"\[\[([^\[\]|#]+?)(?:[|#][^\[\]]*)?\]\]")


# Jev pointers `[[elided id=... tokens=N "summary"]]` (jevctx/pipeline.format_pointer) and the
# listing line `[[elided: N more items ...]]` reuse the [[ ]] delimiters but are retrieval
# handles for `jev_compact.py expand`, not wikimem links (TRDD-AFW0CA65). Resolving them by
# memgrep text search only measured whether the summary's words occur in the corpus (the
# 41/41 and 2/41 results were luck), so they are excluded from extraction. Consequence: a
# handoff made only of pointers has no wikilinks, and handoff_links_resolve reports SKIP
# rather than a meaningless PASS/FAIL.
_JEV_POINTER_TARGET_RE = re.compile(r"^elided(?: id=|:)")


# ---------- pure helpers (tested directly) --------------------------------


def extract_wikilinks(text: str) -> list[str]:
    """Every distinct `[[wikilink]]` TARGET in `text`, order-preserving, deduped.

    The target is the slug before any `|alias` or `#anchor`, stripped. Pure. This is
    the set the `after` phase must prove resolvable — a link the handoff carries but
    the corpus can't resolve is a lost fact, so the whole recoverability check hangs
    off getting this extraction right.
    """
    out: list[str] = []
    seen: set[str] = set()
    for m in _WIKILINK_RE.finditer(text):
        slug = m.group(1).strip()
        if _JEV_POINTER_TARGET_RE.match(slug):
            continue
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out



# ---------- Jev pointer expansion check (TRDD-I40IKPWU) ---------------------
#
# A handoff written by a Jev compaction elides items and leaves `[[elided id=<uuid>:<n> ...]]`
# pointers that `jev_compact.py expand` resolves against the cleared session's transcript.
# Nothing proved those pointers still resolve after the /clear, so a broken one would only
# surface when the fresh session needed it. This check re-resolves every REAL pointer with the
# SAME code `expand` runs (`jev_expand.resolve_pointer`).

_COMPACTED_HEADING_RE = re.compile(r"^#{1,2} Compacted context \(Jev compaction\)$")
_POINTER_LINE_RE = re.compile(r"^\[\[elided id=(\S+?) tokens=")
# `-- <role> <uuid>:<n> --`: the header of one "Newest messages" section. Only a plain
# `<uuid>:<n>` id qualifies (no `@a-b` span): that is what the composer writes for an inline pointer.
_MESSAGE_HEADER_RE = re.compile(r"^-- \S+ ([^\s@]+:\d+) --$")
_EXPAND_LINE_PREFIX = "pointers expand with:"
_TRANSCRIPT_ARG_RE = re.compile(r"--transcript (\S+)")
_ELIDED_LIST_HEADING = "## Elided"


def _compacted_block(text: str) -> list[str] | None:
    """The lines of the handoff's Jev compacted block, or None when it carries none.

    From the FIRST compacted-context heading to the LAST `pointers expand with:` line (to the end
    of the text when there is none). FIRST heading, LAST expand line: a kept item that quotes a
    heading or an expand line can only sit INSIDE the real block, so the outermost pair is the
    real one.
    """
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if _COMPACTED_HEADING_RE.match(ln.rstrip())), None)
    if start is None:
        return None
    end = len(lines) - 1
    for i in range(len(lines) - 1, start, -1):
        if lines[i].startswith(_EXPAND_LINE_PREFIX):
            end = i
            break
    return lines[start : end + 1]


# WHY two headings: compose() writes "## Newest messages ..." in the injected render and
# "## Conversation since ..." in the full render (jev_compaction._EXCHANGES_HEADING / _CONVERSATION_HEADING);
# both hold the same `-- role id --` message blocks.
_NEWEST_HEADINGS = ("## Newest messages", "## Conversation since")
# The sections that can follow Newest messages in the composer output; either closes it.
_NEWEST_END_PREFIXES = ("## Kept items", "## Elided")
_CANDIDATE_RE = re.compile(r"^\S{0,2}elided id=")


def _pointer_regions(block: list[str]) -> tuple[list[str], list[str]]:
    """(Newest-messages lines, lines after the LAST exact `## Elided`) -- the only places a REAL pointer lives.

    WHY one helper for both callers: `extract_pointers` (what to verify) and
    `count_pointer_candidates` (format-drift detector) must agree on where real pointers can sit,
    otherwise a kept item quoting old pointers is verified by one and counted by the other.
    Newest messages runs from the FIRST line starting `## Newest messages` to the next line
    starting `## Kept items` or `## Elided` (or the block end).
    """
    newest: list[str] = []
    start = next((i for i, ln in enumerate(block) if ln.startswith(_NEWEST_HEADINGS)), None)
    if start is not None:
        for ln in block[start + 1 :]:
            if ln.startswith(_NEWEST_END_PREFIXES):
                break
            newest.append(ln)
    elided_at = max((i for i, ln in enumerate(block) if ln == _ELIDED_LIST_HEADING), default=None)
    elided = block[elided_at + 1 :] if elided_at is not None else []
    return newest, elided


def count_pointer_candidates(text: str) -> int:
    """How many line-start `elided id=` candidates sit where real pointers can live, in ANY bracket form.

    Format-drift detector: if the composer's pointer syntax changes (e.g. `[[` becomes `⟦⟦`),
    `extract_pointers` finds 0 while this still finds the old-shaped candidates, so the verdict is
    FAIL, never a quiet SKIP. Counts only the regions `_pointer_regions` names: a kept item that
    quotes old pointers is not drift.
    """
    block = _compacted_block(text)
    if not block:
        return 0
    newest, elided = _pointer_regions(block)
    return sum(1 for ln in newest + elided if _CANDIDATE_RE.match(ln.strip()))


def extract_pointers(text: str) -> tuple[list[str], str | None]:
    """(real pointer ids in order, transcript path) from a handoff's compacted block. Pure.

    A pointer is REAL in exactly two places, because only there did the composer write it:
      - INLINE, in a "Newest messages" section: a line-start pointer after the text of the section
        opened by `-- <role> <uuid>:<n> --` (up to the next header or `## ` heading), and only when
        its id is exactly that header's `<uuid>:<n>`;
      - the trailing `## Elided` list: line-start pointers after the LAST line that is exactly
        `## Elided`.
    Every other line-start pointer is FOREIGN -- e.g. a raw `expand` output or an `## Elided` list
    quoted inside a kept item -- and is ignored: it names an entry of some OTHER transcript, so
    "verifying" it would report a failure the handoff does not have.

    The transcript comes ONLY from a `pointers expand with: ... --transcript <path> <id>` line that
    is the LAST non-blank line of the block; None when there is none.
    """
    block = _compacted_block(text)
    if not block:
        return [], None
    ids: list[str] = []

    def add(pointer_id: str) -> None:
        if pointer_id not in ids:
            ids.append(pointer_id)

    newest, elided = _pointer_regions(block)
    header: str | None = None
    # WHY only inside Newest messages: a kept item quoting an old compacted file carries its own
    # `-- role id --` header + matching pointer; outside this section that is FOREIGN, not a defect.
    for line in newest:
        # WHY a `## ` line does NOT reset the header: a message body may contain markdown headings;
        # only a new `-- ... --` header ends the message.
        head = _MESSAGE_HEADER_RE.match(line)
        if head:
            header = head.group(1)
            continue
        ptr = _POINTER_LINE_RE.match(line)
        if ptr and header is not None and ptr.group(1) == header:
            add(ptr.group(1))
    for line in elided:
        ptr = _POINTER_LINE_RE.match(line)
        if ptr:
            add(ptr.group(1))

    transcript: str | None = None
    last_nonblank = next((ln for ln in reversed(block) if ln.strip()), "")
    if last_nonblank.startswith(_EXPAND_LINE_PREFIX):
        found = _TRANSCRIPT_ARG_RE.findall(last_nonblank)
        transcript = found[-1] if found else None
    return ids, transcript


def validate_transcript_path(path: str | None, projects_roots: tuple[Path, ...], sid8: str | None) -> str | None:
    """Why `path` may not be read as the cleared session's transcript, or None when it may. Pure.

    The path comes out of a handoff file -- data, not trusted input -- so the verifier must not
    open an arbitrary file on its say-so. Accepted only when it is `<root>/<project>/<sid8...>.jsonl`
    for one of `projects_roots`. Existence is NOT checked here: a well-formed path to a vanished
    transcript is a different failure ("gone") from a malformed path ("rejected").
    """
    if not path:
        return "handoff names no transcript"
    if sid8 is None:
        return "cannot derive session id"
    # WHY resolved on BOTH sides: a lexical comparison is fooled by `..` and by symlinked
    # roots (/var vs /private/var on macOS), accepting a path that really points elsewhere.
    cand = Path(path).expanduser().resolve(strict=False)
    if not any(cand.parent.parent == root.resolve() for root in projects_roots):
        return "not directly under a Claude projects root"
    if cand.suffix != ".jsonl" or not cand.name.startswith(sid8):
        return f"not a <session>.jsonl file for session {sid8}"
    return None


def _projects_roots() -> tuple[Path, ...]:
    """The Claude projects roots a session transcript may live under: `$CLAUDE_CONFIG_DIR/projects`
    when set, and always `~/.claude/projects` (no shared helper exists in scripts/lib)."""
    roots: list[Path] = []
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        roots.append(Path(config_dir) / "projects")
    roots.append(Path.home() / ".claude" / "projects")
    return tuple(roots)


def _verdict(status: str, detail: str) -> dict:
    return {"status": status, "detail": detail}


def compute_verdicts(before: dict, after: dict, *, collapse_ratio: float = 0.5) -> dict:
    """PASS/FAIL/SKIP for each assumption, from the before+after snapshots. PURE.

    SKIP (not FAIL) whenever a signal is simply unavailable — the harness proves what
    it CAN observe and never manufactures a failure from missing data (fail-open).
    """
    v: dict[str, dict] = {}

    # 1. The heartbeat cron is HEALTHY after /clear — either it SURVIVED unchanged (the
    #    common case: /clear does not restart the process, so the in-memory cron usually
    #    just survives, and SessionStart's re-arm is CONDITIONAL — "if missing" — so it
    #    correctly does nothing) or it was destroyed-and-recreated (a build where /clear
    #    does drop it). Both are healthy. #186: a prior version of this check FAILED on
    #    the survived-unchanged case, asserting destruction+recreation as if it were
    #    unconditional — that assumption, not the primitive, was wrong. Only a cron that
    #    is GONE after /clear and never came back is a real failure.
    b_id = (before.get("cron_id") or "").strip()
    a_id = (after.get("cron_id") or "").strip()
    cron_survived_unchanged = bool(b_id) and a_id == b_id
    if not a_id:
        if b_id:
            v["cron_recreated"] = _verdict(
                "FAIL", f"cron {b_id} existed before /clear but is GONE after, and was not re-armed"
            )
        else:
            v["cron_recreated"] = _verdict(
                "SKIP", "no cron id observed before or after (re-arm not observed yet)"
            )
    elif cron_survived_unchanged:
        v["cron_recreated"] = _verdict(
            "PASS",
            f"cron {a_id} survived /clear unchanged — this build does not drop the session "
            "cron on /clear, so SessionStart's conditional re-arm ('if missing') correctly "
            "did nothing (see #186)",
        )
    else:
        # TRDD-5ID9CQY8 box 4: the re-arm's CronDelete of the PRIOR id is the only signal that can
        # tell "the prior cron SURVIVED the clear" from any other id change — CronDelete fails
        # not-found for a dead id, so a successful delete of exactly the prior id proves it still
        # existed after /clear. The evidence arrives as the after-snapshot's `prior_cron_deleted`
        # MATCHED ID — only from a tool_result paired with a real CronDelete tool_use; anything
        # else stays neutral (TRDD-JK2MLS8Z).
        matched = after.get("prior_cron_deleted")
        if isinstance(matched, str) and matched == b_id:
            v["cron_recreated"] = _verdict(
                "PASS",
                f"cron id changed {b_id or '∅'} → {a_id} — SURVIVED the clear: the re-arm's "
                f"CronDelete of the prior id {b_id} succeeded (CronDelete fails not-found for a "
                "dead id), so the prior cron still existed after /clear and the re-arm replaced it",
            )
        else:
            v["cron_recreated"] = _verdict("PASS", f"cron id changed {b_id or '∅'} → {a_id}")

    # 2. context collapsed to base-size.
    b_ctx = before.get("context_tokens")
    a_ctx = after.get("context_tokens")
    # janitor#224 defect 3: a fixed ratio of `before` is the wrong yardstick, and it FAILs
    # hardest on the sessions that clear soonest. A fresh session reloads the install's base
    # — system prompt, auto-loaded rules, the skills/agents listing — measured at ~166k on the
    # reporter's host. A session only ~11k above that floor cannot reach 0.5× no matter how
    # perfectly /clear works, so the verdict was reporting a property of the INSTALL as a
    # failure of the CLEAR. dispatch.py already models this correctly for compaction: the
    # floor is "a property of the install, not a number we get to choose".
    _raw_floor = after.get("context_floor")
    floor = _raw_floor if isinstance(_raw_floor, int) and _raw_floor > 0 else 0
    has_floor = floor > 0
    threshold = int(floor * (1.0 + _FLOOR_MARGIN))
    # TRDD-JK2MLS8Z: `a_ctx` is the FIRST assistant record of the new session. Its SessionStart
    # injection (`injected_tokens`, ~2.7k measured) is printed for information ONLY and is NOT
    # added to the threshold: the 10% margin (~17k at a 174k floor) already covers it, and
    # whether the post-compaction floor already contains SessionStart output is unverified, so
    # adding it could count the injection twice.
    _raw_inj = after.get("injected_tokens")
    injected = f"~{_raw_inj}" if isinstance(_raw_inj, int) and _raw_inj > 0 else "not determined"
    measured = f"[{after.get('context_source') or 'unknown source'}; SessionStart injection {injected} tokens, information only]"
    if not isinstance(b_ctx, int) or not isinstance(a_ctx, int) or b_ctx <= 0:
        v["context_collapsed"] = _verdict(
            "SKIP", f"context size unknown (before={b_ctx}, after={a_ctx}) {measured}"
        )
    elif has_floor and a_ctx <= threshold:
        v["context_collapsed"] = _verdict(
            "PASS", f"context {b_ctx} → {a_ctx} tokens (at the install's ~{floor} floor) {measured}"
        )
    elif has_floor:
        # With a floor known, the ratio is not consulted at all — the floor ANSWERS the
        # question the ratio was approximating, so consulting both would only let the looser
        # one win. (A first draft kept a third branch for "before was too close to the floor
        # for the ratio to be reachable"; the floor test above already passes every case that
        # branch existed for, so it was unreachable — the same dead-code shape being hunted
        # elsewhere in this issue. Deleted rather than left as decoration.)
        v["context_collapsed"] = _verdict(
            "FAIL",
            f"context {b_ctx} → {a_ctx} tokens — still {a_ctx - floor} above the install's "
            f"~{floor} floor (threshold {threshold} = floor +{_FLOOR_MARGIN:.0%}), so the "
            f"context did not collapse {measured}",
        )
    elif a_ctx <= b_ctx * collapse_ratio:
        v["context_collapsed"] = _verdict("PASS", f"context {b_ctx} → {a_ctx} tokens (collapsed) {measured}")
    else:
        v["context_collapsed"] = _verdict(
            "FAIL", f"context {b_ctx} → {a_ctx} tokens (did NOT collapse below {collapse_ratio:g}×) {measured}"
        )

    # 3. every handoff link resolves in the fresh session.
    resolved = after.get("links_resolved") or {}
    links = before.get("handoff_links") or []
    if not links:
        v["handoff_links_resolve"] = _verdict("SKIP", "handoff carried no [[wikilinks]] to resolve")
    else:
        checkable = {k: val for k, val in resolved.items() if val is not None}
        if not checkable:
            v["handoff_links_resolve"] = _verdict(
                "SKIP", f"{len(links)} link(s) but none checkable (memgrep unavailable)"
            )
        else:
            failed = [k for k, val in checkable.items() if not val]
            if failed:
                v["handoff_links_resolve"] = _verdict(
                    "FAIL", f"{len(failed)}/{len(checkable)} link(s) did not resolve: {', '.join(failed[:5])}"
                )
            else:
                v["handoff_links_resolve"] = _verdict(
                    "PASS", f"all {len(checkable)} checkable link(s) resolve"
                )

    # 4. the resume-after-clear flag was consumed by _phase_clear_resume.
    b_flag = bool(before.get("resume_flag_present"))
    a_flag = bool(after.get("resume_flag_present"))
    # janitor#224 defect 2: the before/after diff cannot see the common path at all. On
    # CLEAR_CHAIN_SPAWNED the flag is written by a detached child immediately before the
    # /clear keystroke — after this snapshot — so `b_flag` is False on exactly the runs that
    # worked, and the old SKIP then stated as FACT that no flag had been set. The consumption
    # stamp is written by `_phase_post_clear_resume` at unlink time and survives the clear, so
    # it is checked FIRST: direct evidence beats an inference that structurally cannot hold.
    consumed_at = after.get("resume_consumed_at")
    b_ts = before.get("ts")
    if isinstance(consumed_at, int) and consumed_at > 0 and (
        not isinstance(b_ts, int) or consumed_at >= b_ts
    ):
        v["resume_flag_consumed"] = _verdict(
            "PASS", f"resume cue emitted and flag consumed at {consumed_at} (post-clear stamp)"
        )
    elif not b_flag:
        v["resume_flag_consumed"] = _verdict(
            "SKIP",
            "could not observe a resume-after-clear flag before /clear (on the spawned-chain "
            "path it is written by the detached child after this snapshot) and no consumption "
            "stamp was found afterwards",
        )
    elif a_flag:
        v["resume_flag_consumed"] = _verdict("FAIL", "resume-after-clear flag still present (not consumed)")
    else:
        v["resume_flag_consumed"] = _verdict("PASS", "resume-after-clear flag consumed (resume fired)")

    # 5. a re-arm happened AFTER the before-snapshot ⇒ SessionStart+bootstrap ran on clear.
    #    A re-arm is only EXPECTED when assumption 1 found the cron missing/destroyed —
    #    on a build where /clear leaves the cron alone, SessionStart's conditional arm
    #    ("if missing") correctly does nothing, so "no fresh re-arm timestamp" there is
    #    the healthy outcome, not a failure (#186's second false unconditional assumption).
    b_ts = before.get("ts")
    a_armed = after.get("armed_at_ts")
    if cron_survived_unchanged:
        v["session_restarted"] = _verdict(
            "SKIP", "cron survived /clear unchanged — no re-arm was needed (see cron_recreated)"
        )
    elif not isinstance(b_ts, int) or not isinstance(a_armed, int) or a_armed <= 0:
        v["session_restarted"] = _verdict("SKIP", "no post-clear re-arm timestamp observed")
    elif a_armed >= b_ts:
        v["session_restarted"] = _verdict(
            "PASS", f"re-armed at {a_armed} (after the {b_ts} snapshot) — SessionStart ran on source=clear"
        )
    else:
        v["session_restarted"] = _verdict(
            "FAIL", f"newest re-arm {a_armed} predates the {b_ts} snapshot (no fresh re-arm seen)"
        )

    # 6. every elided pointer the handoff carries still resolves (TRDD-I40IKPWU), through the SAME
    #    `jev_expand.resolve_pointer` that `jev_compact.py expand` runs. Unlike the checks above,
    #    an UNRUNNABLE check here is a FAIL, never a SKIP: this check guards an invariant that
    #    holds today, so "could not run" must stay as loud as "ran and failed" or a regression
    #    in the plumbing would read as a clean bill of health. Only a handoff with no pointers
    #    at all is a SKIP, and even that FAILs when pointer-shaped text exists but none parsed
    #    (format drift in the composer).
    pointers = before.get("handoff_pointers") or []
    candidates = before.get("handoff_pointer_candidates") or 0
    expanded = after.get("pointers_expanded") or {}
    if not pointers and not candidates:
        v["handoff_pointers_expand"] = _verdict("SKIP", "handoff carried no elided pointers")
    elif not pointers:
        v["handoff_pointers_expand"] = _verdict(
            "FAIL", f"pointer format not recognised: {candidates} candidate(s), 0 parsed"
        )
    elif "pointers_expanded_error" in after:
        v["handoff_pointers_expand"] = _verdict(
            "FAIL", f"pointer check could not run: {after['pointers_expanded_error']}"
        )
    elif "pointers_transcript_rejected" in after:
        v["handoff_pointers_expand"] = _verdict(
            "FAIL", f"transcript path rejected: {after['pointers_transcript_rejected']}"
        )
    elif after.get("pointers_transcript_missing"):
        v["handoff_pointers_expand"] = _verdict(
            "FAIL", f"transcript of the cleared session is gone: {len(pointers)} pointer(s) unrecoverable"
        )
    else:
        failed = [(pid, expanded.get(pid, "not checked")) for pid in pointers]
        failed = [(pid, err) for pid, err in failed if err is not None]
        if not failed:
            v["handoff_pointers_expand"] = _verdict("PASS", f"all {len(pointers)} pointer(s) expand")
        else:
            shown = "; ".join(f"{pid}={err}" for pid, err in failed[:5])
            v["handoff_pointers_expand"] = _verdict(
                "FAIL", f"{len(failed)}/{len(pointers)} pointer(s) did not expand: {shown}"
            )
    return v


def render_report(before: dict, after: dict, verdicts: dict) -> str:
    """A PASS/FAIL table + the raw before/after snapshots, as markdown. Pure."""
    order = [
        ("cron_recreated", "heartbeat cron survives or is re-armed after /clear"),
        ("context_collapsed", "context collapsed to base size"),
        ("handoff_links_resolve", "every [[handoff link]] resolves"),
        ("resume_flag_consumed", "resume-after-clear flag consumed"),
        ("session_restarted", "SessionStart re-armed after /clear, if a re-arm was needed"),
        ("handoff_pointers_expand", "every elided pointer in the handoff expands"),
    ]
    icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⚪"}
    n_pass = sum(1 for k, _ in order if verdicts.get(k, {}).get("status") == "PASS")
    n_fail = sum(1 for k, _ in order if verdicts.get(k, {}).get("status") == "FAIL")
    n_skip = sum(1 for k, _ in order if verdicts.get(k, {}).get("status") == "SKIP")
    lines = [
        "# /janitor-handoff-and-clear — cross-/clear verification (TRDD-Z582IKIR P1)",
        "",
        f"- generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S%z')}",
        f"- result: {n_pass} PASS · {n_fail} FAIL · {n_skip} SKIP",
        "",
        "| # | assumption | result | detail |",
        "|---|---|---|---|",
    ]
    for i, (key, label) in enumerate(order, 1):
        ver = verdicts.get(key, {"status": "SKIP", "detail": "not evaluated"})
        st = ver["status"]
        lines.append(f"| {i} | {label} | {icon.get(st, '?')} {st} | {ver['detail']} |")
    lines += [
        "",
        "## before snapshot (invoking session, pre-/clear)",
        "```json",
        json.dumps(before, indent=2, sort_keys=True),
        "```",
        "",
        "## after snapshot (fresh session, post-/clear resume)",
        "```json",
        json.dumps(after, indent=2, sort_keys=True),
        "```",
        "",
    ]
    return "\n".join(lines)


# ---------- I/O gather (best-effort, never raises) -------------------------


def _project_root() -> Path:
    import state  # noqa: PLC0415 - local sibling lib

    return state.project_root()


def _state_dir() -> Path:
    import state  # noqa: PLC0415 - local sibling lib

    return state.state_dir()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def _read_int(path: Path) -> int:
    try:
        return int(_read_text(path).strip() or "0")
    except ValueError:
        return 0


def _tail_lines(path: Path, n: int) -> list[str]:
    """Last `n` non-empty lines of `path`, or [] — best-effort, never raises."""
    try:
        lines = [ln.rstrip("\n") for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return lines[-n:]
    except (FileNotFoundError, OSError):
        return []


def _context_tokens() -> tuple[int | None, str]:
    """Live context size + its source. Prefers a configured agentlensPro command
    (best-effort), falls back to the newest transcript's token count — the same
    reader the cold-cache paths use, so it needs no external dependency."""
    cmd = os.environ.get(
        "CLAUDE_PLUGIN_OPTION_HANDOFF_VERIFY_CONTEXT_COMMAND", "agentlenspro get_burn_status"
    ).strip()
    if cmd:
        try:
            proc = subprocess.run(
                cmd.split(), capture_output=True, text=True, timeout=15, check=False
            )
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                for key in ("context_tokens", "contextTokens", "used_tokens", "usedTokens", "tokens"):
                    val = data.get(key) if isinstance(data, dict) else None
                    if isinstance(val, int) and val > 0:
                        return val, f"agentlenspro:{key}"
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    try:
        import cold_cache_compact  # noqa: PLC0415 - local sibling lib

        tokens = cold_cache_compact.context_tokens_for(
            cold_cache_compact.newest_transcript(_project_root())
        )
        if isinstance(tokens, int):
            return tokens, "transcript"
    except Exception:  # noqa: BLE001 - best-effort
        pass
    return None, "unknown"


# ---------- the NEW session after /clear (TRDD-JK2MLS8Z) -------------------
def _first_record_time(path: Path) -> datetime | None:
    """Timezone-aware time of the first transcript record that carries a `timestamp`, else None.

    Records are ISO strings with `Z` or a numeric offset. A naive or unparseable stamp is None --
    such a candidate is never accepted, and if it was modified after the clear it makes the
    result ambiguous (see `_new_session_transcript`).
    """
    import jsonl_walk  # noqa: PLC0415 - local sibling lib

    try:
        for _line_no, entry in jsonl_walk.iter_jsonl_entries(path, malformed_lines=[]):
            raw = entry.get("timestamp")
            if not isinstance(raw, str):
                continue
            try:
                started = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            except ValueError:
                return None
            return started if started.tzinfo is not None else None
    except OSError:
        return None
    return None


def _new_session_transcript(before: dict) -> tuple[Path | None, str]:
    """The transcript of the session the clear started, or `(None, reason)` -- never a guess.

    Accepted: a `*.jsonl` in the project's transcript dir whose stem does not start with the
    cleared session's sid8 AND whose FIRST record lies within `_NEW_SESSION_WINDOW_S` after the
    before-phase `ts` (the snapshot taken just before /clear, `gather_before`'s `now`). Chosen by
    START time, never by mtime. Exactly one must qualify.

    AMBIGUOUS (None) when the real successor may be a candidate we cannot accept: one whose start
    cannot be placed (no aware timestamp) yet whose mtime is after the clear, or one whose first
    record is AFTER the window (a late successor). Accepting a lone in-window peer beside either
    would measure the wrong session and could PASS falsely. mtime is only the ambiguity hint for
    stamp-less files, never a selector; stamp-less files last modified before the clear, and
    candidates whose first record is at or before the clear, are ignored.
    """
    import memory_scopes  # noqa: PLC0415 - local sibling lib

    clear_ts = before.get("ts")
    if not isinstance(clear_ts, int):
        return None, "the before snapshot has no ts"
    sid8 = before.get("handoff_sid8")
    slug = memory_scopes.project_slug(str(_project_root()))
    accepted: dict[Path, Path] = {}
    unplaceable: dict[Path, Path] = {}
    late: dict[Path, Path] = {}
    for root in _projects_roots():
        for candidate in (root / slug).glob("*.jsonl"):
            if isinstance(sid8, str) and sid8 and candidate.stem.startswith(sid8):
                continue
            started = _first_record_time(candidate)
            if started is None:
                if candidate.stat().st_mtime > clear_ts:
                    unplaceable[candidate.resolve()] = candidate
            elif clear_ts < started.timestamp() <= clear_ts + _NEW_SESSION_WINDOW_S:
                accepted[candidate.resolve()] = candidate
            elif started.timestamp() > clear_ts + _NEW_SESSION_WINDOW_S:
                # Why: the clear chain may have waited before typing /clear, so the real successor can
                # start after the window; with one in-window peer it would otherwise be a false PASS.
                late[candidate.resolve()] = candidate
    window = f"{_NEW_SESSION_WINDOW_S // 60}-minute window after the clear"
    if unplaceable or late:
        return None, (
            f"{len(unplaceable)} transcript(s) with no placeable first-record time were modified "
            f"after the clear and {len(late)} started after the {window}, so the successor is ambiguous "
            f"({len(accepted)} started within the {window})"
        )
    if len(accepted) != 1:
        return None, f"{len(accepted)} transcripts started within the {window} (exactly 1 required)"
    return next(iter(accepted.values())), ""


def _session_start_injected_tokens(path: Path) -> int | None:
    """Estimated tokens the clear's own SessionStart hooks injected, or None when undeterminable.

    The new transcript stores every hook output as an `attachment` record (`hook_success`,
    `hookEvent: SessionStart`, text in `content`) ahead of the first assistant record, so the
    figure is summed from what the session actually received -- all hooks, not only the handoff.
    Estimated at ~4 characters per token, the repo's other stdlib estimate
    (`wikimem_bench.estimate_tokens`; not imported -- that is a CLI script, and the
    `jevctx.tokens` estimator is barred from this process by tests/test_jev_boundary.py). The
    figure is information only: it is printed in the verdict detail and is NOT added to the
    collapse threshold. At ~4 characters per token it under-counts against `jevctx`'s 3.5.
    """
    import jsonl_walk  # noqa: PLC0415 - local sibling lib

    chars = 0
    try:
        for _line_no, entry in jsonl_walk.iter_jsonl_entries(path, malformed_lines=[]):
            if entry.get("type") == "assistant":
                break
            att = entry.get("attachment")
            if (
                entry.get("type") == "attachment"
                and isinstance(att, dict)
                and att.get("hookEvent") == "SessionStart"
                and isinstance(att.get("content"), str)
            ):
                chars += len(att["content"])
    except OSError:
        return None
    return -(-chars // _CHARS_PER_TOKEN) if chars > 0 else None


def _prior_cron_deleted(path: Path, prior_id: str) -> str | bool:
    """The prior heartbeat id, when a real CronDelete call for it SUCCEEDED in this transcript.

    A "Cancelled job <id>" tool_result is direct evidence the deleted cron still existed
    (CronDelete fails not-found for a dead id), but ONLY when the result is paired — by
    `tool_use_id` — with the `tool_use` block that issued the delete AND that call's own
    `input.id` is the prior id: transcripts freely quote the same string inside OTHER
    tool_results (a Read of a report or card quoting "Cancelled job <id>" is text, not
    evidence), so a bare text scan false-positives on quoted lines (TRDD-5ID9CQY8 review
    item 1). Returns the MATCHED id (== `prior_id`) on success, False otherwise — an
    unpaired line or a delete of an unrelated job is no evidence about the prior id.
    Best-effort: False on any read failure, which just leaves the id-change verdict's
    wording neutral.
    """
    import jsonl_walk  # noqa: PLC0415 - local sibling lib

    if not prior_id:
        return False
    delete_ids: set[str] = set()
    try:
        for _line_no, entry in jsonl_walk.iter_jsonl_entries(path, malformed_lines=[]):
            message = entry.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name")
                tool_input = block.get("input")
                if (
                    isinstance(name, str)
                    and "CronDelete" in name
                    and isinstance(tool_input, dict)
                    and tool_input.get("id") == prior_id
                ):
                    use_id = block.get("id")
                    if isinstance(use_id, str) and use_id:
                        delete_ids.add(use_id)
        for _line_no, entry in jsonl_walk.iter_jsonl_entries(path, malformed_lines=[]):
            message = entry.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                if block.get("tool_use_id") not in delete_ids:
                    continue
                inner = block.get("content")
                if isinstance(inner, str):
                    texts = [inner]
                elif isinstance(inner, list):
                    texts = [
                        b.get("text", "")
                        for b in inner
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    texts += [c for c in inner if isinstance(c, str)]
                else:
                    texts = []
                for text in texts:
                    m = _CANCELLED_JOB_RE.search(text)
                    if m and m.group(1) == prior_id:
                        return m.group(1)
    except OSError:
        return False
    return False


def _rotator_log_tail(n: int) -> list[str]:
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    data = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    candidates = [
        Path(data) / "oauth-rotator" / "rotator.log" if data else None,
        home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins" / "oauth-rotator" / "rotator.log",
        home / ".claude" / "account-rotator" / "rotator.log",
    ]
    for c in candidates:
        if c is not None and c.is_file():
            return _tail_lines(c, n)
    return []


def _resolve_link(slug: str, roots: list[Path], memgrep: str | None) -> bool | None:
    """Does `slug` resolve to a memory note? True/False, or None when unresolvable
    to check (no memgrep AND no filesystem match to reason from). Never raises."""
    # Filesystem fallback first — cheap and dependency-free: a page file whose stem
    # matches the slug proves the target exists even with no memgrep.
    stem = slug.replace(" ", "-").lower()
    for root in roots:
        try:
            for md in root.rglob("*.md"):
                if md.stem.lower() == stem:
                    return True
        except OSError:
            continue
    if not memgrep:
        return None
    for root in roots:
        try:
            proc = subprocess.run(
                [memgrep, "find", slug, str(root)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def _memory_roots() -> list[Path]:
    try:
        import memory_scopes  # noqa: PLC0415 - local sibling lib

        return [p for _scope, p in memory_scopes.resolve_scope_dirs()]
    except Exception:  # noqa: BLE001 - best-effort
        return []


def gather_before(now: int) -> dict:
    sd = _state_dir()
    # TRDD-5RXBI65T — the newest handoff FILE, whatever its name. The verifier's question is
    # "was a handoff written before the /clear", and since option D each write has its own path.
    _newest = handoff_files.newest(sd)
    handoff = _read_text(_newest) if _newest is not None else ""
    ctx, ctx_src = _context_tokens()
    pointers, transcript = extract_pointers(handoff)
    # The handoff's session key is the first 8 chars of the CLEARED session's id (its filename);
    # the legacy shared name and the unkeyed fallback carry no usable id.
    parsed = handoff_files.parse(_newest.name) if _newest is not None else None
    sid8 = parsed[0] if parsed and parsed[0] not in (handoff_files.LEGACY_KEY, handoff_files.UNKEYED_KEY) else None
    return {
        "ts": now,
        "cron_id": _read_text(sd / _CRON_ID_FILENAME).strip(),
        "context_tokens": ctx,
        "context_source": ctx_src,
        "handoff_bytes": len(handoff.encode("utf-8")),
        "handoff_link_count": len(extract_wikilinks(handoff)),
        "handoff_links": extract_wikilinks(handoff),
        "handoff_pointers": pointers,
        "handoff_pointer_candidates": count_pointer_candidates(handoff),
        "handoff_transcript": transcript,
        "handoff_sid8": sid8,
        "resume_flag_present": (sd / _RESUME_FLAG_FILENAME).is_file(),
        "rotator_log_tail": _rotator_log_tail(10),
        "token_meter_tail": _tail_lines(sd / _TOKEN_METER_FILENAME, 5),
    }



def _check_pointers(before: dict) -> dict:
    """The `after`-snapshot keys for the elided-pointer check (TRDD-I40IKPWU); {} when the handoff
    carried no pointers. Exactly one outcome key: `pointers_expanded_error`,
    `pointers_transcript_rejected`, `pointers_transcript_missing`, or `pointers_expanded`
    ({pointer id: error text or None})."""
    pointers = before.get("handoff_pointers") or []
    if not pointers:
        return {}
    # WHY a failed import is recorded, not swallowed into a fallback: if `jev_expand` cannot be
    # imported the check did not run, and the verdict must say FAIL "could not run" -- a quiet
    # SKIP here would turn a broken plugin install into a clean bill of health. (Deliberately NOT
    # the silent `except: pass` the memgrep lookup in `gather_after` uses.)
    try:
        import jev_expand  # noqa: PLC0415 - local sibling lib, stdlib-only
    except Exception as exc:  # noqa: BLE001 - reported verbatim as the verdict detail
        return {"pointers_expanded_error": f"{type(exc).__name__}: {exc}"}
    transcript = before.get("handoff_transcript")
    reason = validate_transcript_path(transcript, _projects_roots(), before.get("handoff_sid8"))
    if reason is not None:
        return {"pointers_transcript_rejected": reason}
    # WHY the resolved path is used for BOTH the existence check and the read: the validated
    # path and the opened path must be the same file, never the raw string re-interpreted.
    assert transcript is not None  # validate_transcript_path returned None, so a path exists
    cand = Path(transcript).expanduser().resolve(strict=False)
    if not cand.is_file():
        return {"pointers_transcript_missing": True}
    return {
        "pointers_expanded": {
            pid: jev_expand.resolve_pointer(cand, pid, malformed_lines=[])[1] for pid in pointers
        }
    }


def gather_after(before: dict, now: int) -> dict:
    sd = _state_dir()
    # TRDD-JK2MLS8Z: the collapse verdict needs the context RIGHT AFTER the clear, i.e. the first
    # assistant record of the new session -- not `_context_tokens()` (agentlensPro or the newest
    # transcript's LAST record), which reads "now", after the resumed session has already read
    # files. That live figure is deliberately NOT used here, not even as a fallback: later records
    # only grow, so it could only turn a good clear into a false FAIL, never into a false PASS.
    # When the new session cannot be identified or has no assistant record yet, the check
    # reports SKIP with the reason instead of guessing. `gather_before` keeps the live figure.
    ctx: int | None = None
    injected: int | None = None
    new_transcript, why = _new_session_transcript(before)
    if new_transcript is None:
        ctx_src = f"skipped: {why}"
    else:
        import token_meter  # noqa: PLC0415 - local sibling lib

        ctx = token_meter.first_context_entry(new_transcript)
        if ctx is None:
            ctx_src = "skipped: the new session has no assistant usage record yet"
        else:
            ctx_src = "transcript:first-assistant"
            injected = _session_start_injected_tokens(new_transcript)
    memgrep = None
    try:
        import user_mem_lib  # noqa: PLC0415 - local sibling lib

        memgrep = user_mem_lib.find_memgrep()
    except Exception:  # noqa: BLE001 - best-effort
        memgrep = None
    roots = _memory_roots()
    links_resolved = {slug: _resolve_link(slug, roots, memgrep) for slug in before.get("handoff_links", [])}
    after = {
        "ts": now,
        "cron_id": _read_text(sd / _CRON_ID_FILENAME).strip(),
        # TRDD-5ID9CQY8 box 4: the MATCHED id of a successful CronDelete of the PRIOR id in the new
        # session's transcript (result paired with its CronDelete tool_use) — direct evidence the
        # PRIOR cron survived the clear, since CronDelete fails not-found for a dead id. False when
        # no paired delete matched the prior id, and also when the successor transcript is
        # unidentifiable.
        "prior_cron_deleted": _prior_cron_deleted(new_transcript, before.get("cron_id") or "")
        if new_transcript is not None
        else False,
        "context_tokens": ctx,
        "context_source": ctx_src,
        "injected_tokens": injected,
        "resume_flag_present": (sd / _RESUME_FLAG_FILENAME).is_file(),
        # Direct evidence the resume fired, written at unlink time by the phase that did it
        # (janitor#224 defect 2) — the before/after diff cannot see the common path.
        "resume_consumed_at": _read_int(sd / _RESUME_CONSUMED_FILENAME),
        # The install's own base size, so `context_collapsed` judges against the floor a
        # fresh session actually reloads rather than a ratio of `before` (defect 3).
        "context_floor": _context_floor(),
        "armed_at_ts": _read_int(sd / _ARMED_AT_FILENAME),
        "memgrep": bool(memgrep),
        "links_resolved": links_resolved,
    }
    after.update(_check_pointers(before))
    return after


def _context_floor() -> int:
    """The context size a FRESH session reloads on this install, or 0 when unmeasured.

    Reuses `cold_cache_compact`'s learned floor rather than measuring a second one: that
    module already records the size observed right after a compaction, which is the same
    quantity (base install + auto-loaded rules + the skills/agents listing). A private copy
    here would drift from it, and the two would disagree about the same install.
    """
    try:
        import cold_cache_compact  # noqa: PLC0415 - local sibling lib

        floor, _measured_at = cold_cache_compact.read_floor(_state_dir())
        return int(floor) if isinstance(floor, int) and floor > 0 else 0
    except Exception:  # noqa: BLE001 - best-effort; an unknown floor degrades to the ratio
        return 0


def _verify_path() -> Path:
    return _state_dir() / _VERIFY_FILENAME


def _write_json(path: Path, data: dict) -> None:
    """Atomic write so a crash mid-write can't leave the `after` phase reading a
    half-written `before` block across the /clear boundary."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _report_dir() -> Path:
    """<project>/reports/continuity-build/ — anchored on CLAUDE_PROJECT_DIR (the project
    being cleared), NOT the process cwd. Deliberately no `git` call: this is a
    per-project diagnostic, project_root() is its correct home, and shelling out to git
    from an arbitrary cwd is both fragile and how a wrong-repo report gets written."""
    d = _project_root() / "reports" / "continuity-build"
    d.mkdir(parents=True, exist_ok=True)
    return d


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Prove the /janitor-and-clear primitive's assumptions across the /clear boundary."
    )
    ap.add_argument("--phase", required=True, choices=("before", "after"))
    args = ap.parse_args()

    now = int(time.time())
    try:
        if args.phase == "before":
            before = gather_before(now)
            _write_json(_verify_path(), {"before": before})
            print(
                f"VERIFY_BEFORE cron_id={before['cron_id'] or '∅'} "
                f"context={before['context_tokens']} handoff_links={before['handoff_link_count']} "
                f"-> {_verify_path()}"
            )
            # SURFACE the missing flag — AMBIGUOUSLY, because it genuinely is ambiguous. Absence
            # has two readings and this phase does not currently tell them apart (it COULD — see
            # the note below the two readings; not distinguishing is a choice, not a limit):
            #
            #   1. NORMAL. On the spawned-chain path (`CLEAR_CHAIN_SPAWNED`, the common case) the
            #      resume state is written by the DETACHED CHILD immediately before the `/clear`
            #      keystroke — i.e. AFTER this snapshot. The skill's step 4 says so outright:
            #      running before-phase after the trigger "gives it a chance to observe
            #      `resume-after-clear.flag` IF the trigger's write already landed", and the
            #      dependent check "reads SKIP, never FAIL, when it hasn't". Line 227 of this very
            #      file carries the same sentence.
            #   2. BROKEN. Nobody fired the chain at all — this script was run standalone and a
            #      human was asked to type `/clear`. Then `_inject_post_clear_handoff` returns
            #      early (deliberately gated on the flag: a manual `/clear` means DISCARD), no
            #      `[janitor-resume]` is emitted, and the session-only cron dies with the session.
            #      Measured 2026-08-22: exactly that left a resumed session idle until its user
            #      complained, while this line printed cron id, context and link count — every
            #      field except the one that decided the outcome.
            #
            # A PREDICATE DOES EXIST, and this deliberately does not use it (yet). The chain's
            # detached child holds a NON-BLOCKING exclusive `flock` on `.janitor/state/
            # clear-chain.lock` for the whole chain (`clear_trigger.py` ~:359-370), so a
            # `LOCK_EX|LOCK_NB` probe here would separate (1) from (2) outright: lock busy ⇒ a
            # chain is pending, lock free ⇒ nobody fired one. Not taken because the ambiguous
            # message already puts the consequence in front of the one caller who can act on it,
            # and adding a lock syscall to a FAIL-OPEN diagnostic buys precision with a new
            # failure mode. What does NOT work — and was proposed — is gating on
            # `resume-after-clear.ts`: the child writes ts and flag back-to-back in one function,
            # so ts-without-flag is a microsecond window, not the in-flight period (which is
            # BEFORE both writes, when neither exists).
            #
            # So it names BOTH readings and asks the caller — who knows whether it fired the
            # trigger — to decide. An earlier revision asserted (2) alone and would have cried
            # wolf on every correct orchestrated clear; a warning that fires on the happy path is
            # ignored, and then the real one is missed too. FAIL-OPEN either way ("a fault here
            # must NEVER break the resume"), and it does NOT write the flag itself: that would
            # flip the documented manual-clear-is-a-discard semantics for the flag's whole age
            # window and make the after-phase's own flag check self-fulfilling.
            if not before.get("resume_flag_present"):
                print(
                    "VERIFY_BEFORE_NO_RESUME_FLAG no resume-after-clear.flag observed. If you "
                    "fired clear_trigger.py / the /janitor-handoff-and-clear skill, this is "
                    "EXPECTED — the detached child writes it later, and the after-phase check "
                    "reads SKIP, not FAIL. If you did NOT, nothing will resume this clear (no "
                    "handoff injection, no [janitor-resume], and the cron dies with the "
                    "session), so hand the user the exact command to paste after clearing: "
                    "`uv run scripts/handoff_clear_verify.py --phase after`",
                    file=sys.stderr,
                )
            return 0

        # phase == after
        try:
            saved = json.loads(_verify_path().read_text(encoding="utf-8"))
            before = saved.get("before", {}) if isinstance(saved, dict) else {}
        except (FileNotFoundError, OSError, ValueError):
            before = {}
        if not before:
            print(
                "VERIFY_NO_BEFORE no before-snapshot found — run `--phase before` in the "
                "session that fired /clear",
                file=sys.stderr,
            )
            return 0
        after = gather_after(before, now)
        verdicts = compute_verdicts(before, after)
        report = render_report(before, after, verdicts)
        _write_json(_verify_path(), {"before": before, "after": after, "verdicts": verdicts})
        report_path = _report_dir() / f"{datetime.now().astimezone().strftime('%Y%m%d_%H%M%S%z')}-handoff-clear-verify.md"
        report_path.write_text(report, encoding="utf-8")
        n_pass = sum(1 for x in verdicts.values() if x["status"] == "PASS")
        n_fail = sum(1 for x in verdicts.values() if x["status"] == "FAIL")
        n_skip = sum(1 for x in verdicts.values() if x["status"] == "SKIP")
        print(f"VERIFY_AFTER {n_pass} PASS · {n_fail} FAIL · {n_skip} SKIP -> {report_path}")
        # Also print the compact table so the resumed session sees the result inline.
        for key, ver in verdicts.items():
            print(f"  [{ver['status']}] {key}: {ver['detail']}")
        return 0
    except Exception as exc:  # noqa: BLE001 - a diagnostic must NEVER break the resume
        print(f"VERIFY_ERROR {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
