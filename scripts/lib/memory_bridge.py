# MEMORY.md ↔ wikimem bridge line (owner directive 2026-07-25).
#
# THE WHOLE CONTRACT, and the reason this module is deliberately tiny:
#
#   `MEMORY.md` belongs to the Claude Code HARNESS. It is NOT deprecated and it is
#   NOT the janitor's to curate. The harness's own `# Memory` directive maintains
#   its content. The two memory systems — the harness's MEMORY.md and the janitor's
#   wikimem corpus — COEXIST.
#
#   The janitor maintains EXACTLY ONE LINE in that file: a link to the project's
#   main wikimem page (`<project>-overview.md`). That single line is the BRIDGE, so
#   an agent arriving through either system can find the other. We VERIFY it is
#   present and RE-ADD it if deleted. We interfere with nothing else.
#
# Why this is append-only and never a rewrite: an earlier model treated MEMORY.md as
# a janitor-owned index and "stubbed" it, which DESTROYED harness-written pointer
# lines. That is the failure this module exists to make structurally impossible —
# every write here is a single appended line, and any file we cannot parse or that
# already carries the link is left byte-identical.
#
# Imported (not run as a script) so no PEP 723 metadata block. Stdlib-only.

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import state  # noqa: E402  -- sibling lib

# The harness's file. We never create it — creation is the harness's business; a
# janitor-created MEMORY.md would be a second system claiming the same filename.
MEMORY_MD = "MEMORY.md"

# memgrep's own rule for the entry page (`find_overview_page`, memory.rs): the single
# note whose basename ends with `-overview.md`, case-insensitively. Kept identical so
# the bridge always points at exactly what `memgrep overview` resolves.
_OVERVIEW_SUFFIX = "-overview.md"

# Outcome vocabulary — returned, logged, and asserted on by tests.
OUTCOME_NO_MEMORY_MD = "no-memory-md"   # harness file absent → nothing to bridge INTO (never create it)
OUTCOME_NO_OVERVIEW = "no-overview"     # no wiki entry page → nothing to bridge TO (bootstrap first)
OUTCOME_PRESENT = "present"             # the link is already there → file untouched
OUTCOME_ADDED = "added"                 # the line was missing/deleted → one line appended
OUTCOME_ERROR = "error"                 # unreadable/unwritable → fail OPEN, never raise


def find_overview_page(scope_root: Path | str) -> Path | None:
    """The scope's single `*-overview.md` wiki entry page, or None.

    Mirrors memgrep's `find_overview_page` (suffix match, case-insensitive) so the
    bridge and `memgrep overview` can never disagree about the target. Searched
    recursively because a curated corpus keeps its pages under `wiki/`, while an
    older/flat corpus keeps them at the scope root.

    Deterministic on a corpus that (incorrectly) has more than one: the shortest
    path wins, then lexicographic — so the bridge does not flap between candidates
    from one run to the next.
    """
    try:
        hits = [
            p
            for p in Path(scope_root).rglob("*.md")
            if p.is_file() and p.name.lower().endswith(_OVERVIEW_SUFFIX)
        ]
    except OSError:
        return None
    if not hits:
        return None
    return sorted(hits, key=lambda p: (len(p.parts), str(p)))[0]


def bridge_line(scope_root: Path, overview: Path) -> str:
    """The canonical one-line bridge, as it is written into MEMORY.md.

    The link is RELATIVE to MEMORY.md (which lives at the scope root), so the file
    stays portable — a PROJECT-scope MEMORY.md is pushed to every contributor, and
    an absolute path would be one machine's private layout leaking into the repo.
    """
    try:
        rel = overview.relative_to(scope_root).as_posix()
    except ValueError:
        rel = overview.name
    return (
        f"- [wikimem — project overview]({rel}) — the curated wiki that coexists with "
        f'this file; recall by symptom: `memgrep recall "<symptom>" <memdir>`'
    )


def has_bridge(text: str, overview: Path) -> bool:
    """True iff `text` already links to the overview page. PURE.

    Keyed on the FILENAME rather than on our exact sentence, so a human (or the
    harness) who rewords the line, moves it, or writes their own link to the same
    page still counts as "present" — re-adding ours would then be a duplicate, which
    is precisely the interference this contract forbids.
    """
    return overview.name in text


def ensure_bridge_line(scope_root: Path | str) -> str:
    """VERIFY the bridge line is present in this scope's MEMORY.md; RE-ADD if absent.

    Returns one of the OUTCOME_* constants. Never raises: this runs on the
    SessionStart path, where an exception would cost the user their session for a
    cosmetic index line.

    The ONLY mutation possible here is appending a single line to an existing
    MEMORY.md. Nothing else in the file is read for meaning, rewritten, reordered,
    or removed.
    """
    # Coerce: the documented shell one-liner (and the bootstrap skill) pass a plain
    # string, and a TypeError there would be a crash in the middle of a chore.
    scope_root = Path(scope_root)
    memory_md = scope_root / MEMORY_MD
    if not memory_md.is_file():
        return OUTCOME_NO_MEMORY_MD  # the harness owns creation — never do it for it

    overview = find_overview_page(scope_root)
    if overview is None:
        return OUTCOME_NO_OVERVIEW  # nothing to point at; /janitor-memory-bootstrap seeds it

    try:
        text = memory_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return OUTCOME_ERROR

    if has_bridge(text, overview):
        return OUTCOME_PRESENT

    # Append-only. Preserve the file's exact existing bytes; add a separating newline
    # only when the file does not already end with one (never collapse or reflow).
    sep = "" if text.endswith("\n") or not text else "\n"
    try:
        state.atomic_write(memory_md, f"{text}{sep}{bridge_line(scope_root, overview)}\n")
    except OSError:
        return OUTCOME_ERROR
    return OUTCOME_ADDED
