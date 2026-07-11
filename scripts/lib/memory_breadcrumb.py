"""SessionStart memory breadcrumb (TRDD-98ISATJZ, surface S2 — janitor#62).

The 3-scope wikimem is only useful if a fresh session KNOWS it exists. Recall is
already PUSHED by the autorecall hook, but a note surfaces only when a prompt
happens to match it — there is no "what do I have?" entry point, so a corpus the
agent never queries stays invisible. That is janitor#62's gap 2 (no one-shot
overview) and gap 3 (USER/cross-project notes invisible until queried).

This is that missing first breadcrumb: ONE line at session start naming the
per-scope note counts and the navigation command, so the agent learns the corpus
exists WITHOUT already knowing `memgrep`.

Load-bearing constraints:

  - COUNTS ONLY, never note CONTENT. A PROJECT-scope page arrives via git from any
    contributor and is untrusted; the autorecall hook is the content path and does
    its own strip-invisible-unicode + bracket-defang sanitization before injecting.
    This surface injects integers and a path, so a poisoned note has nothing to
    ride on here. Do not "improve" it by inlining note titles.

  - Silent on an empty corpus. Zero notes in all three scopes → no line at all, so
    an install with no memory pays nothing and reads nothing.

  - Never raises. It runs inside SessionStart; an unreadable scope counts 0 rather
    than breaking session start.
"""

from __future__ import annotations

import os
from pathlib import Path

# This module is imported BOTH ways: hooks put `scripts/` on sys.path and do
# `from lib import memory_breadcrumb` (so the sibling is `lib.memory_scopes`), while
# detectors and tests put `scripts/lib/` on sys.path and import it flat (so the
# sibling is bare `memory_scopes`). A single spelling breaks one of the two callers —
# under the package form a bare `import memory_scopes` raises ImportError, and the
# hook's blanket except would swallow it and the breadcrumb would silently never
# print. Try the package form first, fall back to the flat one.
try:  # noqa: SIM105 -- two DIFFERENT import spellings, not a suppressible no-op
    from lib import memory_scopes
except ImportError:  # pragma: no cover - exercised by the flat-import callers
    import memory_scopes  # type: ignore[no-redef]

# Scope keys are the `memory_scopes.resolve_scope_dirs()` labels verbatim (LOCAL →
# PROJECT → USER, most-specific-first) so this module never re-derives what a scope
# is. The values are how each scope reads in the line.
_SCOPE_LABELS = {"LOCAL": "local", "PROJECT": "project", "USER": "user-global"}

# `memgrep overview` prints `<project>-overview.md` — the wiki's entry-point page,
# which bootstrap seeds in the PROJECT scope. Prefer that scope when it has notes;
# fall back to whichever scope does, so the command we print always has a corpus to
# open.
_OVERVIEW_PREFERENCE = ("PROJECT", "LOCAL", "USER")


def count_notes(root: Path) -> int:
    """How many real memory NOTES live under ``root``.

    Delegates to the `memory_scopes` SSOT so the count means exactly what recall
    means: the private `user-mem/` subtree, `MEMORY.md`, `memory-index.md`, the
    `*-proposed.md` detector reports, `.memgrep/` and `.maint-staging/` are all
    excluded. An unreadable root counts 0 (never raises — see module docstring).
    """
    try:
        return len(memory_scopes.iter_note_files(root))
    except OSError:
        return 0


def format_breadcrumb(counts: dict[str, int], overview_dir: Path | None) -> str | None:
    """The one-line breadcrumb, or None when there is nothing to say. PURE.

    ``counts`` maps scope label (LOCAL/PROJECT/USER) → note count; scopes at 0 are
    omitted from the line (a project with only USER-global notes should not read
    "0 local"). All-zero (or no ``overview_dir``) → None, so an empty corpus emits
    nothing.
    """
    parts = [
        f"{counts[scope]} {label}"
        for scope, label in _SCOPE_LABELS.items()
        if counts.get(scope, 0) > 0
    ]
    if not parts or overview_dir is None:
        return None
    return (
        f"[janitor-memory] Memory corpus: {' + '.join(parts)} notes. Entry point: "
        f"`memgrep overview {overview_dir}` — the same dir also serves "
        '`memgrep recall "<symptom>" <dir>`. Relevant notes auto-surface by symptom on '
        "each prompt; protocol: ~/.claude/rules/markdown-memory-recall.md."
    )


def breadcrumb() -> str | None:
    """Resolve every existing memory scope, count its notes, and render the line.

    Returns None when the feature is opted out, when no scope exists, or when every
    scope is empty. The ONLY I/O entry point (`format_breadcrumb` stays pure so the
    wording is testable without a filesystem).
    """
    if os.environ.get("CLAUDE_PLUGIN_OPTION_MEMORY_BREADCRUMB", "").strip().lower() in (
        "false",
        "0",
        "no",
        "off",
    ):
        return None
    try:
        scopes = memory_scopes.resolve_scope_dirs()
    except OSError:
        return None
    counts = {name: count_notes(root) for name, root in scopes}
    roots = dict(scopes)
    overview_dir = next(
        (roots[s] for s in _OVERVIEW_PREFERENCE if counts.get(s, 0) > 0),
        None,
    )
    return format_breadcrumb(counts, overview_dir)
