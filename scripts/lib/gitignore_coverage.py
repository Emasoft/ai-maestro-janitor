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
  * ALREADY TRACKED — a file in the class is in the index. Adding a rule does NOT fix this
    (git keeps existing index entries by design); the remedy is `git rm --cached`, NEVER a
    working-tree delete.

WHY THERE IS NO GITIGNORE PARSER HERE: `git check-ignore` already answers "would this path be
ignored?" — negation lines, precedence, `.git/info/exclude`, nested ignore files and all. A
hand-rolled matcher would be a second, worse implementation of git's own rules, and it would
disagree with git exactly where the syntax is subtle, which is exactly where a leak hides.
`is_ignored` is injected so the classification is pure and testable without a repo.
"""
from __future__ import annotations

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
        "reports", "reports/x.md", "reports/",
        "agent reports carry absolute paths, hostnames and quoted source",
    ),
    PrivateClass(
        "dev-dirs", "scripts_dev/x.py", "*_dev/",
        "the _dev folders are the sanctioned home for unpublished work",
    ),
    PrivateClass("venv", ".venv/pyvenv.cfg", ".venv/", "a virtualenv is machine-specific bulk"),
    PrivateClass("node-modules", "node_modules/x.js", "node_modules/", "dependency bulk"),
    PrivateClass("ds-store", ".DS_Store", ".DS_Store", "macOS directory metadata"),
    PrivateClass("logs", "debug.log", "*.log", "logs quote whatever the run touched"),
    PrivateClass("trashcan", ".trashcan/x", ".trashcan/", "safe-delete staging holds deleted work"),
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


def tracked_offenders(
    tracked: Iterable[str],
    is_ignored: Callable[[str], bool],
) -> list[str]:
    """Tracked paths that a private-class rule covers — already in the index despite the rule.

    Adding the rule did not untrack them; only `git rm --cached` does. Protected PROJECT paths
    are excluded, since being tracked is their whole point.
    """
    return sorted(p for p in tracked if not is_protected(p) and is_ignored(p))
