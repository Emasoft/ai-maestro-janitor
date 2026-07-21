#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""wikimem-syntax — surface memory pages memgrep can no longer PARSE (TRDD-VPTQ4067).

The 3 memory-authoring skills disagreed on the lesson schema and the corpus drifted; the
`wikimem_syntax_lint.py` rules (ported 1:1 from memgrep's `memory.rs` parser) catch the
CRITICAL breakages — an atom whose `⟦`-bracket makes it invisible to recall, an atom with no
`keywords:` (un-findable → "the memory does not exist"), a page with no `description:`, and
corpus-wide DUPLICATE atom ids (which make a cross-scope `recall` on that id ambiguous). Until
now that linter was wired into NOTHING; this detector is the wiring — the heartbeat surfaces a
CRITICAL the moment any page goes malformed, and goes silent again the moment it is fixed.

Only CRITICAL is surfaced (a broken/invisible element). The ~hundreds of WARN-level advisories
(lean lessons, missing ocd/lmd, orphan sections) stay for the on-demand
`uv run scripts/wikimem_syntax_lint.py`, so the heartbeat line is never noise.

Scope: the SAME three memory roots recall reads — LOCAL (this project's), PROJECT (this repo's),
USER (the user's own global). These are all the USER's own memory; no other project's data is
touched, so the per-project channeling invariant holds. READ-ONLY: it never mutates a page (RULE
0 + separation of powers — the janitor surfaces, an agent fixes via /janitor-memory-update).
Fail-open: any error → silent exit 0, never breaks the heartbeat. Per-set content-hash dedupe:
re-emits only when the set of CRITICALs CHANGES (bounded — fix the corpus and it converges to
silence).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS / "lib"))
sys.path.insert(0, str(_SCRIPTS))  # for the top-level linter module

import dedupe  # noqa: E402
import memory_scopes  # noqa: E402
import state  # noqa: E402
import wikimem_syntax_lint as lint  # noqa: E402


def _critical_signatures() -> list[str]:
    """Every CRITICAL finding across the 3 memory scopes, as short stable signatures.

    A signature is `<code>@<relpath>:<line>` — stable across runs so the dedupe hash only
    changes when the actual defect set changes. Cross-scope duplicate atom ids are appended as
    one signature per colliding id.
    """
    sigs: list[str] = []
    pages: dict[Path, str] = {}
    for _label, root in memory_scopes.resolve_scope_dirs():
        for note in memory_scopes.iter_note_files(root):
            try:
                text = note.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            pages[note] = text
            for fd in lint.lint_page(note, text):
                if fd.sev == "CRITICAL":
                    sigs.append(f"{fd.code}@{note.name}:{fd.line}")
    for aid in lint.find_duplicate_atom_ids(pages):
        sigs.append(f"atom-dup-id@{aid}")
    return sorted(set(sigs))


def main() -> int:
    try:
        state.init_state()
        sigs = _critical_signatures()
        if not sigs:
            return 0
        example = state.sanitize_for_drift_line(sigs[0])
        n = len(sigs)
        msg = (
            f"[wikimem-syntax] {n} memory element(s) memgrep CANNOT parse (CRITICAL — "
            f"recall-invisible or ambiguous). e.g. {example}. Run "
            f"`uv run scripts/wikimem_syntax_lint.py` for the full list; fix via "
            f"/janitor-memory-update (never hand-edit the .md)."
        )
        # Per-SET dedupe: the key is a hash of the whole critical set, so the line re-emits
        # ONLY when the set changes (a new break, or one fixed) — never on an unchanged corpus.
        key = "critset-" + hashlib.sha1("\n".join(sigs).encode("utf-8")).hexdigest()[:16]
        seen = state.state_dir() / "wikimem-syntax-seen.txt"
        line = dedupe.emit_once(seen, key, msg)
        if line is not None:
            print(line)
    except Exception:  # noqa: BLE001 -- a validator must never break the heartbeat
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
