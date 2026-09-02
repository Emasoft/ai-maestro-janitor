"""Does `.gitignore` cover every PRIVATE class — before a secret can be tracked? TRDD-6WM4BFKF.

On Claude Code a plugin ships its **whole tracked repo**: there is no packaging-exclusion field
in `plugin.json`, and none in the plugin spec. Verified empirically on this repo's own installed
cache, which carries `design/` and `.claude/project/memory/` verbatim. So **TRACKED == SHIPPED
== PUBLIC**, and one missing ignore pattern is not untidiness — it is a publication of private
data to every installer.

The janitor already ships three adjacent detectors and **all three presuppose a correct
`.gitignore` already exists**: `tracked-ignored` fires only when a rule EXISTS and a file is
tracked against it, `memory-scope-leak` scans inside the memory corpus, `project-memory-tracked`
guards the opposite direction. None asks the prior question this module asks.

TWO INDEPENDENT FAULTS PER CLASS, because a rule does not untrack anything:
  * UNCOVERED — no ignore rule matches the class, so the next such file is committed silently.
  * ALREADY TRACKED — a file already IN the class (by the class's own pattern) is in the index.
    Adding a rule does NOT fix this (git keeps existing index entries by design); the remedy is
    `git rm --cached`, NEVER a working-tree delete. A tracked file merely COVERED by some other
    `.gitignore` rule but matching NO private class is `tracked-ignored`'s finding, not this
    module's — TRDD-IEAZQ9MK, the two used to report the same file, hourly, with different
    wording.

WHY THERE IS NO GITIGNORE PARSER HERE: `git check-ignore` already answers "would this path be
ignored?" — negation lines, precedence, `.git/info/exclude`, nested ignore files and all. A
hand-rolled matcher would be a second, worse implementation of git's own rules, and it would
disagree with git exactly where the syntax is subtle, which is exactly where a leak hides.
`is_ignored` is injected into `uncovered_classes` so that half of the classification stays pure
and testable without a repo.
"""
from __future__ import annotations

import fnmatch
from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class PrivateClass:
    """One class of file that must never reach a published tree."""

    name: str
    probe: str          # a representative path; asked of git, never string-matched
    pattern: str        # the canonical `.gitignore` line that would cover it
    why: str


# Table-driven, per TRDD-6WM4BFKF D1 — "a table of classes, not a regex pile". Extending this is
# the intended way to add coverage; adding a branch elsewhere is not.
#
# `/reports/`, `/*_dev/` and `/.trashcan/` are ROOT-anchored on purpose: the rules that define
# them put them at the project root, and nothing else. Unanchored, `reports/` named
# `skills/<x>/templates/reports/*.md` — a skill's report TEMPLATES, tracked on purpose — in a
# fleet repo on the 2026-09-02 sweep, and would have prescribed `git rm --cached` for them every
# hour. `.venv/` and `node_modules/` stay unanchored: a nested one is still machine bulk.
PRIVATE_CLASSES: tuple[PrivateClass, ...] = (
    PrivateClass("dotenv", ".env", ".env", "environment files routinely hold live credentials"),
    PrivateClass("dotenv-variant", ".env.local", ".env.*", "per-env variants leak the same way"),
    PrivateClass("private-key", "id_rsa", "id_rsa*", "an SSH private key in a shipped tree"),
    PrivateClass("pem", "server.pem", "*.pem", "certificates and private keys"),
    PrivateClass("key-file", "signing.key", "*.key", "signing and API keys"),
    PrivateClass(
        "local-settings", ".claude/settings.local.json", ".claude/settings.local.json",
        "machine-local Claude settings, often carrying tokens and absolute home paths",
    ),
    PrivateClass(
        "reports", "reports/x.md", "/reports/",
        "agent reports carry absolute paths, hostnames and quoted source",
    ),
    PrivateClass(
        "dev-dirs", "scripts_dev/x.py", "/*_dev/",
        "the _dev folders are the sanctioned home for unpublished work",
    ),
    PrivateClass("venv", ".venv/pyvenv.cfg", ".venv/", "a virtualenv is machine-specific bulk"),
    PrivateClass("node-modules", "node_modules/x.js", "node_modules/", "dependency bulk"),
    PrivateClass("ds-store", ".DS_Store", ".DS_Store", "macOS directory metadata"),
    PrivateClass("logs", "debug.log", "*.log", "logs quote whatever the run touched"),
    PrivateClass("trashcan", ".trashcan/x", "/.trashcan/", "safe-delete staging holds deleted work"),
)

# NEVER propose ignoring these, and never report them as leaks. They are PROJECT scope and are
# deliberately tracked + pushed — `design/` IS the shared kanban and `.claude/project/memory/` IS
# the shared wiki. This repo protects them with negation lines. A false positive here would not
# be noise: acting on it would delete the board and the corpus for every contributor, which is a
# far larger harm than the leak this module exists to prevent.
PROTECTED_PREFIXES: tuple[str, ...] = (
    "design/",
    ".claude/project/memory/",
)


def is_protected(path: str) -> bool:
    """Is this path deliberately tracked PROJECT scope that must never be proposed for ignoring?"""
    # `removeprefix`, NOT `lstrip("./")` — lstrip strips CHARACTERS, so it ate the leading dot of
    # `.claude/project/memory/...` and the guard silently stopped protecting the shared memory
    # corpus. Caught by `test_protected_prefixes_...`; the failure direction was the dangerous one
    # (a protected path reported as an offender, whose "fix" is untracking the wiki).
    norm = path.removeprefix("./")
    return any(norm.startswith(p) for p in PROTECTED_PREFIXES)


def uncovered_classes(
    is_ignored: Callable[[str], bool],
    classes: Iterable[PrivateClass] = PRIVATE_CLASSES,
) -> list[PrivateClass]:
    """Classes whose representative path git would NOT ignore — i.e. the next one gets committed.

    `is_ignored` is git's own answer (`git check-ignore -q <path>`), not a pattern match.
    """
    return [c for c in classes if not is_ignored(c.probe)]


def matches_private_class(
    path: str,
    classes: Iterable[PrivateClass] = PRIVATE_CLASSES,
) -> bool:
    """Does this tracked path fall in a private class by the class's OWN canonical pattern?

    This is the contamination half of D2 — `git ls-files` against the CLASS matcher — and it
    must not depend on the repo's `.gitignore`: the case it exists for is the file that was
    tracked BEFORE any rule existed, where `is_ignored` answers False and the coverage line's
    "the NEXT such file is published" is silently false for a file already shipping (found by
    the review fork on the 2026-09-02 close: a seeded repo with a tracked `.env` and no ignore
    file printed no contamination line at all). The module docstring's ban on a gitignore
    parser is about the USER's file — its negations and precedence. This matches only the
    thirteen patterns WE own, which have four fixed, simple shapes, each with git's meaning: a
    bare name or glob matches the basename at any depth, a `dir/` pattern matches any directory
    component, a `/dir/` pattern matches ONLY the root directory (the 2026-09-02 fleet sweep:
    unanchored `reports/` named a skill's tracked `templates/reports/` as contamination), and a
    pattern with an inner slash is anchored at the root.
    """
    norm = path.removeprefix("./")
    parts = norm.split("/")
    for c in classes:
        rooted = c.pattern.startswith("/")
        pat = c.pattern.removeprefix("/")
        if pat.endswith("/"):
            # `parts[:-1]` is every directory component; a rooted pattern may match only the
            # first. Both are empty for a root-level FILE, so `reports` (a file) never matches.
            dirs = parts[:-1][:1] if rooted else parts[:-1]
            if any(fnmatch.fnmatchcase(d, pat[:-1]) for d in dirs):
                return True
        elif "/" in pat:
            if norm == pat or norm.startswith(pat + "/"):
                return True
        elif fnmatch.fnmatchcase(parts[-1], pat):
            return True
    return False


def tracked_offenders(
    tracked: Iterable[str],
    is_negated: Callable[[str], bool] = lambda _: False,
) -> list[str]:
    """Tracked paths in one of the thirteen private classes, by the class's OWN pattern.

    ONE way in: `matches_private_class` — the file is in a private class whether or not any
    `.gitignore` rule exists for it. This module used to ALSO report a path merely because git
    said a rule covers it (`is_ignored`), even when the path matched no private class at all —
    but that rule-only case is exactly what `tracked-ignored` already reports (`git ls-files
    --ignored --exclude-standard --cached`), so a file both tracked and covered by a plain repo
    rule (e.g. `ccpm/**`, `logs/`) got one line from each detector, hourly, worded differently
    and neither saying "private class" truthfully (TRDD-IEAZQ9MK — 47 of 85 fleet contamination
    offenders on 2026-09-02 were rule-only, no private-class match). `tracked-ignored` is now the
    sole owner of the rule-only case; this module owns only the private-class case, so a rule
    that merely covers an ordinary tracked file is no longer misreported as "in a private class".

    The one way OUT is still "tracked ON PURPOSE": any path git reports as re-included by a `!`
    line (`is_negated`) — this repo's `.trashcan/.gitkeep` sits inside the `.trashcan/` class by
    name, and `/.trashcan/*` + `!/.trashcan/.gitkeep` is exactly how it is meant to be tracked.
    A negation is the user's explicit decision; reporting it would propose untracking what they
    deliberately kept. `is_protected` still excludes the shared PROJECT-scope prefixes.
    """
    return sorted(
        p for p in tracked
        if not is_protected(p) and not is_negated(p) and matches_private_class(p)
    )
