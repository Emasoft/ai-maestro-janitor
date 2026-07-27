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
/janitor-memory-update). Fail-open: any error → silent exit 0, never breaks the heartbeat.
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


def _error_signatures() -> list[str]:
    """Every ERROR finding across the 3 memory scopes, as short stable signatures.

    A signature is `<basename>:<line>:<check-code>` — the check's stable IDENTITY, so the dedupe
    hash changes when the defect SET changes and not when someone improves a message's wording.
    (It used to hash the message, which made every reworded message look like a new defect.)
    Neither the message nor the path is carried: a duplicate-id report names every colliding
    absolute location, and a drift signature must never be a channel for one.

    A binary predating codes yields an empty `code`; fall back to a message hash there, so an old
    memgrep degrades to the previous behaviour instead of collapsing every finding on a line into
    one signature.
    """
    _code, _stdout, findings = lint.run_lint()
    sigs = {
        f"{Path(f.path).name}:{f.line}:"
        + (
            f.code
            or hashlib.sha1(f.msg.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        )
        for f in findings
        if f.sev == "ERROR"
    }
    return sorted(sigs)


def main() -> int:
    try:
        state.init_state()
        sigs = _error_signatures()
        if not sigs:
            return 0
        example = state.sanitize_for_drift_line(sigs[0])
        n = len(sigs)
        msg = (
            f"[wikimem-syntax] {n} memory element(s) memgrep CANNOT parse (ERROR — "
            f"recall-invisible or ambiguous). e.g. {example}. Run "
            f"`uv run scripts/wikimem_syntax_lint.py` for the full list; fix via "
            f"/janitor-memory-update (never hand-edit the .md)."
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
