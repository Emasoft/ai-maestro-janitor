#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""wikimem-syntax — surface memory pages memgrep can no longer PARSE (TRDD-VPTQ4067).

The 3 memory-authoring skills disagreed on the lesson schema and the corpus drifted; `memgrep
lint` catches the ERROR-class breakages — an atom whose `⟦`-bracket makes it invisible to
recall, an atom with no `keywords:` (un-findable → "the memory does not exist"), props segments
the parser silently DISCARDS, a page with no `description:`, and corpus-wide DUPLICATE atom ids
(which make a `recall` on that id ambiguous). Until now that linter was wired into NOTHING; this
detector is the wiring — the heartbeat surfaces an ERROR the moment any page goes malformed, and
goes silent again the moment it is fixed.

The checks live in memgrep, not here (plan Phase 1b): the write gate and this heartbeat MUST
enforce the same rule set, and two implementations of one grammar drift apart — they already had.

Only ERROR is surfaced (a broken or invisible element). The hundreds of WARN/INFO advisories
(lean lessons, missing ocd/lmd, one-sided links) stay for the on-demand
`uv run scripts/wikimem_syntax_lint.py`, so the heartbeat line is never noise.

Scope: the SAME three memory roots recall reads — LOCAL (this project's), PROJECT (this repo's),
USER (the user's own global) — in ONE invocation, because atom-id uniqueness is corpus-wide and a
per-scope run cannot see a cross-scope collision. These are all the USER's own memory; no other
project's data is touched, so the per-project channeling invariant holds. READ-ONLY: it never
mutates a page (RULE 0 + separation of powers — the janitor surfaces, an agent fixes via
/janitor-memory-update, EXCEPT `link-downward-cross-scope`: no editor chore re-homes a page
across scopes, so that rule's remedy is a scope decision the agent makes itself — janitor#138).
Fail-open: any error → silent exit 0, never breaks the heartbeat.
Per-set content-hash dedupe: re-emits only when the set of ERRORs CHANGES (bounded — fix the
corpus and it converges to silence).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS / "lib"))
sys.path.insert(0, str(_SCRIPTS))  # for the top-level linter module

import dedupe  # noqa: E402
import state  # noqa: E402
import wikimem_syntax_lint as lint  # noqa: E402

# The one rule (janitor#138) whose remedy the blanket "/janitor-memory-update" line
# CANNOT satisfy: a page linking DOWN across scopes (LOCAL from PROJECT/USER, or
# PROJECT from USER) has no editor chore that can fix it — no chore re-homes a page
# across scopes (janitor-memory-repair §8: "cross-scope re-homing is SURFACED, not
# done"; janitor-memory-consolidate: "promotion is a deliberate human act"). The scope
# decision is the agent's own: promote the target deliberately, or remove the downward
# reference. Every other code keeps pointing at /janitor-memory-update.
_CROSS_SCOPE_CODE = "link-downward-cross-scope"


def _error_findings() -> list[lint.Finding]:
    """Every ERROR finding across the 3 memory scopes."""
    _code, _stdout, findings = lint.run_lint()
    return [f for f in findings if f.sev == "ERROR"]


def _signatures(findings: list[lint.Finding]) -> list[str]:
    """Findings as short stable signatures, sorted.

    A signature is `<basename>:<line>:<check-code>` — the check's stable IDENTITY, so the dedupe
    hash changes when the defect SET changes and not when someone improves a message's wording.
    (It used to hash the message, which made every reworded message look like a new defect.)
    Neither the message nor the path is carried: a duplicate-id report names every colliding
    absolute location, and a drift signature must never be a channel for one.

    A binary predating codes yields an empty `code`; fall back to a message hash there, so an old
    memgrep degrades to the previous behaviour instead of collapsing every finding on a line into
    one signature.
    """
    sigs = {
        f"{Path(f.path).name}:{f.line}:"
        + (
            f.code
            or hashlib.sha1(f.msg.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        )
        for f in findings
    }
    return sorted(sigs)


def _error_signatures() -> list[str]:
    """Every ERROR finding's signature, sorted — `_signatures(_error_findings())`.

    A standalone zero-arg entry point (distinct from `main`'s own call sequence,
    which needs the findings themselves too — for the per-rule remedy — and must
    not run `lint.run_lint()` a second time to get them).
    """
    return _signatures(_error_findings())


def _remedy_for(codes: set[str]) -> str:
    """The remedy clause for the drift line, PER-RULE rather than blanket (janitor#138).

    A `link-downward-cross-scope` ERROR cannot be fixed via `/janitor-memory-update` —
    that instrument delegates COMPLEX re-editing to the six editor chores
    (split/consolidate/conflict/repair/atomize/harvest), and NONE of them re-homes a
    page across scopes. Naming the blanket remedy for this rule reads as "a chore owns
    this, wait for it" when no chore does, so it must say the scope decision is the
    agent's own instead. Every other code keeps the generic remedy.
    """
    cross_scope_clause = (
        f"for `{_CROSS_SCOPE_CODE}`: the scope decision is yours — no editor chore "
        "re-homes a page across scopes (see janitor-memory-repair §8); either promote "
        "the target deliberately or remove the downward reference"
    )
    generic_clause = "fix via /janitor-memory-update (never hand-edit the .md)"
    has_cross_scope = _CROSS_SCOPE_CODE in codes
    has_other = bool(codes - {_CROSS_SCOPE_CODE})
    if has_cross_scope and has_other:
        return f"{cross_scope_clause}; everything else: {generic_clause}."
    if has_cross_scope:
        return f"{cross_scope_clause}."
    return f"{generic_clause}."


def main() -> int:
    try:
        state.init_state()
        findings = _error_findings()
        if not findings:
            return 0
        sigs = _signatures(findings)
        example = state.sanitize_for_drift_line(sigs[0])
        n = len(sigs)
        codes = {f.code for f in findings if f.code}
        remedy = _remedy_for(codes)
        msg = (
            f"[wikimem-syntax] {n} memory element(s) memgrep CANNOT parse (ERROR — "
            f"recall-invisible or ambiguous). e.g. {example}. Run "
            f"`uv run scripts/wikimem_syntax_lint.py` for the full list; {remedy}"
        )
        # Per-SET dedupe: the key is a hash of the whole ERROR set, so the line re-emits
        # ONLY when the set changes (a new break, or one fixed) — never on an unchanged corpus.
        key = "critset-" + hashlib.sha1("\n".join(sigs).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
        seen = state.state_dir() / "wikimem-syntax-seen.txt"
        line = dedupe.emit_once(seen, key, msg)
        if line is not None:
            print(line)
    except Exception:  # noqa: BLE001 -- a validator must never break the heartbeat
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
