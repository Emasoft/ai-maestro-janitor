#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PreToolUse: memgrep is the ONLY write path to a wikimem page (TRDD-VOWAUVE5, USER #6).

USER ruling 2026-08-22: *"enforce the use of memgrep when writing/updating/editing/migrate/
create new pages/create new atoms. Everything must pass via memgrep. so memgrep can lint and
ensure always 100% compliance with the wikimem specs."*

This REVERSES a documented decision, so the reversal is stated where the old one lived:
`post-edit-wikimem-lint.py` is deliberately a POST hook and says *"the standing rule explicitly
permits the plain Edit tool as an alternative"* and *"denying it would fight the documented
workflow."* That was true under the old rule. The rule changed; that header is updated in the
same commit, because a codebase arguing with itself is worse than either answer.

WHY a deny and not another nudge: the corpus's structural guarantees come from memgrep
SYNTHESISING the element (`main.rs:475` — "the parser's own crate SYNTHESISES the element so a
malformed atom/page/lesson is impossible"). A hand-written page bypasses that by construction,
so no amount of after-the-fact linting restores the guarantee — it can only report the damage.

FAIL-OPEN, deliberately. Every uncertainty — unreadable stdin, a path we cannot classify, an
exception anywhere — allows the write. A memory hook that blocks writes when confused would
make the corpus UNEDITABLE at exactly the moment someone is trying to repair it, and an
un-writable memory is a worse failure than an unlinted page.

The Bash branch (TRDD-XI10BA5D step D) extends the same deny to shell writes — redirections,
tee, in-place editors, cp/mv/rm-class — with per-segment evaluation and the sanctioned
exemptions (git restores, memgrep itself, safe-delete, the USER-memory mirror restore).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ENABLED_ENV = "CLAUDE_PLUGIN_OPTION_WIKIMEM_WRITE_PATH_ENFORCED"

# Same shape as post-edit-wikimem-lint / post-edit-memory-correction: `*/memory/*.md`, minus the
# private user-mem store, the MEMORY.md / memory-index.md index files, and the `.memgrep/`
# sidecar. Copied rather than imported for the reason that file states: importing a HOOK from a
# hook makes both un-runnable standalone.
_MEMORY_PATH_RE = re.compile(r"(?:^|/)memory/.*\.md$")
_EXCLUDE_RE = re.compile(
    r"(?:^|/)user-mem/"
    r"|(?:^|/)\.memgrep/"
    r"|(?:^|/)MEMORY\.md$"
    r"|(?:^|/)memory-index\.md$"
    # The transaction core's own staging + journal. memgrep writes these THROUGH the Edit path
    # while a chore is in flight; denying them would deadlock the very tool this hook exists to
    # funnel writes into.
    r"|(?:^|/)\.maint-staging/"
)

_REASON = """This is a wikimem memory page, and memgrep is the only write path to one
(USER ruling 2026-08-22, TRDD-VOWAUVE5).

Use the write verb that matches the intent — each SYNTHESISES the element, so a malformed
atom/page/lesson is impossible by construction, and each validates + reindexes as it writes:

  memgrep new-mem-topic     --scope local --name N --tier component --type reference --description "..."
  memgrep new-mem-atom      --page <path> --desc "..." --keywords "..."  # a new fact (body on stdin)
  memgrep update-mem-atom   --page <path> --lesson --atom <id> --keywords "..."  # a [^N] lesson
  memgrep update-mem-topic  --page <path> --old-file F1 --new-file F2   # CAS replace of exact text
  memgrep update-mem-atom   --page <path> --atom <id>                   # rewrite ONE atom, id kept
  memgrep migrate-mem-atom  <atom> --from <page> --to <page>            # move an atom + its lessons

Also available: `delete-mem-topic`/`delete-mem-atom` (remove, never bypassing the recall
guarantees), `merge-mem-topic`/`merge-mem-atom` (fold duplicates together), `split-mem-topic`/
`split-mem-atom` (break up an over-long page or atom), and `reference-mem-topic`/
`reference-mem-atom` (wire a bidirectional `[[wikilink]]`) — reach for whichever matches the
edit you actually intend, instead of hand-authoring it.

Correct a WRONG fact with `update-mem-atom --lesson --supersedes` (same atom id) — never by
overwriting it. Then: `memgrep validate <page> && memgrep lint <page>`.

Editing the file directly bypasses the parser, the CAS staleness guard, and the scope lock, so
the corpus loses the guarantees the memory system is built on. Nothing here forbids the CONTENT
you were about to write — only the path it takes to get in."""


def _enabled() -> bool:
    v = os.environ.get(ENABLED_ENV)
    return True if v is None else v.strip().lower() not in {"0", "false", "no", "off"}


# The Bash-branch reason: _REASON's verb menu composed with a shell-specific opening, so the
# menu is maintained in exactly one place (A7).
_SHELL_REASON = _REASON + """

The blocked command wrote to (or destroyed) a memory page THROUGH THE SHELL. Run the memgrep
verb DIRECTLY instead — never shell-redirect, pipe, copy or sed into a page. Feeding stdin via
a heredoc INTO a memgrep verb is fine (that is memgrep's normal channel); anything that bypasses
it is not. If you were copying a page into or out of a memory tree, do it with a memgrep verb
(`migrate-mem-atom`, `merge-mem-topic`, ...) or ask the janitor repair flow to do it.
"""

# A1: `is_memory_page()` requires a *.md LEAF, so `cp /tmp/draft.md memory/` (directory
# destination — the most natural hand-copy) escapes it. This second classifier accepts the
# TREE: any path containing a `/memory/` segment, or ending with `/memory`.
_MEMORY_TREE_RE = re.compile(r"(?:^|/)memory(?:/|$)")
_MEMORY_TREE_EXCLUDE_RE = re.compile(
    r"(?:^|/)user-mem/"
    r"|(?:^|/)\.memgrep/"
    r"|(?:^|/)\.maint-staging/"
)
# The USER-memory backup mirror (TRDD-GFT33HT9, `~/.claude/ai-maestro-janitor-memory/`).
# There is no standalone restore script: the routine restore is `sync_user_memory_mirror()`
# in scripts/lib/memory_scopes.py, invoked from on-session-start.py — script-side file ops
# that never cross the Bash tool boundary, so they are invisible to this hook by
# construction. The exemption below therefore covers the mirror's only live Bash path: the
# MANUAL post-loss restore (`cp ~/.claude/ai-maestro-janitor-memory/... <memory>/`).
# memgrep's own mirror check (memgrep/src/memory.rs:6191) CLASSIFIES the real mirror path,
# where substring looseness is harmless; this hook's check GRANTS an exemption, where a
# look-alike dir name would smuggle a write past every deny — hence the SEGMENT match in
# _is_mirror_source, not a substring (adversarial review 2026-09-29).
_MEMORY_MIRROR_DIR = "ai-maestro-janitor-memory"
# The safe-delete script (the sh ancestor `safe-delete.sh` was ported to this in commit
# 12263f26; only the .py exists today).
_SAFE_DELETE_SCRIPT = "safe_delete.py"

_GIT_RESTORE_SUBCOMMANDS = frozenset(
    {"checkout", "restore", "stash", "reset", "revert", "merge", "rebase", "pull"}
)

# Write operators: `>>` before `>` in the alternation so the greedy longest-match wins, and
# the dup forms (`2>&1`, `>&1`) must never be read as `>` + path `&1` — hence the negative
# lookahead for a `&`-led dup target. `>\|` (clobber) is matched as ONE operator so the
# segment splitter's `(?<!>)\|` does not cut it in two. CEILING (A8): args-via-stdin
# (`find memory/ | xargs rm` — targets statically invisible) and shell variables (`> "$MEM"`)
# are NOT visible to a static string scan; the Edit-tool deny + post-edit-wikimem-lint.py are
# the backstops.
_REDIRECT_RE = re.compile(r"(?:>>|2>>|&>>|>\||2>|&>|<>|>)(?!>&)\s*(\S+)")
# In-place editors. DELIBERATE OVER-DENY (A4): `sed -i` (or `perl -i/-pi`) plus an UNRELATED
# memory-path mention anywhere in the command false-positives; accepted, because the
# alternative (parsing operand positions under shell quoting) fails worse. The rule keys on
# the `sed`/`perl` COMMAND WORDS — the next reader must NOT extend in-place detection to
# `grep` (grep -i is a read flag, and grep is read-only by nature).
_SED_INPLACE_RE = re.compile(r"\bsed\b[^\n|;&]*?\s-i\b")
_PERL_INPLACE_RE = re.compile(r"\bperl\b[^\n|;&]*?\s-(?:pi|p|i)\b")
# CEILING (A8): writes hidden inside arbitrary interpreters (`python -c 'open(...).write()'`,
# `node -e`, `osascript`, awk printing to a variable target) are not statically visible; a
# denied command retried via interpreter indirection is an ESCALATION the post-edit lint
# still catches on the bytes. Layered defense, not absolute.

# A command word is the first token of a segment; a flag is a `-`-prefixed token.
_TOKEN_SPLIT_RE = re.compile(r"\s+")
# `(?<!>)\|` keeps `>|` (clobber) whole — a bare `|` split would amputate the operator and
# free the memory path into an operator-less segment. `||` still splits (matched first).
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||(?<!>)\||;|\n")
# ACCEPTED OVER-DENY (adversarial review 2026-09-29): the splitter is quote-unaware, so a
# quoted string containing a separator (`echo 'a; rm memory/p.md'`, `git commit -m "x &&
# rm memory/y.md"`) is evaluated as two segments and denied. Over-deny is the fail-safe
# direction; quote-aware parsing is the upgrade path if it bites.

_COPY_COMMANDS = frozenset({"cp", "rsync", "install"})
_DELETE_COMMANDS = frozenset({"rm", "unlink", "shred", "rmdir"})


def _strip_quotes(token: str) -> str:
    """A3: strip ONE paired leading/trailing quote from a candidate path before
    classification — `> ".claude/project/memory/p.md"` must classify like its bare form."""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        return token[1:-1]
    return token


def _is_memory_page_raw(path: str) -> bool:
    """Classification on an already-normalized (quote-stripped) path — the shared body of
    `is_memory_page`, without re-normalizing, so `is_memory_page()` stays byte-identical in
    behavior for the Edit branch."""
    if not path.endswith(".md"):
        return False
    return bool(_MEMORY_PATH_RE.search(path)) and not _EXCLUDE_RE.search(path)


def _inside_memory_tree(path: str) -> bool:
    """A1: True when the path contains a `/memory/` segment or ends with `/memory`
    (after normalization). Exclusions follow `is_memory_page` — user-mem, .memgrep,
    .maint-staging are not wiki stores."""
    if not path:
        return False
    p = str(Path(path)).replace(os.sep, "/")
    return bool(_MEMORY_TREE_RE.search(p)) and not _MEMORY_TREE_EXCLUDE_RE.search(p)


def _classifies(path: str) -> bool:
    """EITHER classifier, after quote-stripping (A3)."""
    p = _strip_quotes(path)
    return _is_memory_page_raw(p) or _inside_memory_tree(p)


def _is_mirror_source(path: str) -> bool:
    """A6: the source of a sanctioned mirror-restore copy — inside the
    `ai-maestro-janitor-memory` backup-mirror dir. SEGMENT match, not substring: a
    look-alike dir (`x-ai-maestro-janitor-memory/`) must not inherit the exemption."""
    return any(part == _MEMORY_MIRROR_DIR for part in path.replace(os.sep, "/").split("/"))


def _is_safe_delete_destination(path: str) -> bool:
    """A destination with a `.trashcan` path segment — the safe-delete flow's staging
    (sanctioned). Matches relative (`.trashcan/<ts>/`) and absolute (`/repo/.trashcan/…`)."""
    p = str(Path(path)).replace(os.sep, "/")
    return bool(re.search(r"(?:^|/)\.trashcan(?:/|$)", p))


def _is_process_substitution(token: str) -> bool:
    """`>(...)` / `<(...)` — bash process substitution. The token after such an operator is
    a COMMAND, not a file path; classifying it would false-deny `> >(cmd)`."""
    return token.startswith(">(") or token.startswith("<(")


def _git_restores_segment(segment: str) -> bool:
    """A2: True iff THIS segment is a git restore-class invocation (wholesale allowance).
    Subcommand = the FIRST non-`-`-prefixed token after `git`, so `git -C elsewhere pull`
    is exempt, not false-denied."""
    tokens = _TOKEN_SPLIT_RE.split(segment.strip())
    try:
        i = tokens.index("git")
    except ValueError:
        return False
    for tok in tokens[i + 1 :]:
        if tok.startswith("-"):
            continue
        return tok in _GIT_RESTORE_SUBCOMMANDS
    return False


def _segment_is_memgrep(segment: str) -> bool:
    """A memgrep invocation in any form — including heredoc STDIN into it (`memgrep
    add-atom ... <<EOF`): input INTO memgrep is its normal channel; memgrep writes through
    its own gate."""
    tokens = _TOKEN_SPLIT_RE.split(segment.strip())
    return bool(tokens) and tokens[0].endswith("memgrep")


def _segment_invokes_safe_delete(segment: str) -> bool:
    """Any invocation of the safe-delete script (sanctioned removal path)."""
    return _SAFE_DELETE_SCRIPT in segment


def _segment_has_memory_write(segment: str) -> bool:
    """The deny rules for ONE segment. Order: exemptions first (git restore, memgrep,
    safe-delete script), then redirections, then per-command rules."""
    if _git_restores_segment(segment) or _segment_is_memgrep(segment) or _segment_invokes_safe_delete(segment):
        return False

    # 1. Redirections into a memory path (dup targets `2>&1`/`>&1` are excluded by the
    #    regex's negative lookahead — a dup is not a path; `>(cmd)` targets are commands,
    #    not paths, and are skipped).
    for m in _REDIRECT_RE.finditer(segment):
        target = m.group(1)
        if not _is_process_substitution(target) and _classifies(target):
            return True

    # 2. tee: its FILE operands are ALL its non-flag tokens (tee reads stdin) — deny iff
    #    any non-flag token after `tee` in this segment classifies (A4). This keeps
    #    `grep foo memory/p.md | tee /tmp/out.md` (read memory, write tmp) allowed while
    #    `echo x | tee -a memory/p.md` denies.
    tokens = _TOKEN_SPLIT_RE.split(segment.strip())
    if "tee" in tokens:
        idx = tokens.index("tee")
        if any(_classifies(tok) for tok in tokens[idx + 1 :] if not tok.startswith("-")):
            return True

    # 3. In-place editors: sed/perl carrying -i/-pi AND a memory path anywhere in the
    #    command (see the over-deny note on _SED_INPLACE_RE above).
    if _SED_INPLACE_RE.search(segment) and any(_classifies(tok) for tok in tokens):
        return True
    if _PERL_INPLACE_RE.search(segment) and any(_classifies(tok) for tok in tokens):
        return True

    if not tokens:
        return False
    cmd = tokens[0]

    # 4. Copy/move into a memory page or memory tree (A1). Destination inference:
    #    LAST non-flag token for cp/rsync/install (plus GNU `-t DEST`), ALL operands for
    #    truncate (A5 — every operand is a target), and for `mv` BOTH directions, except a
    #    destination under `/.trashcan/` (safe-delete). dd is caught by `of=<mempath>`
    #    below. A6 mirror-restore exemption: a copy whose SOURCE is under the
    #    `ai-maestro-janitor-memory` backup mirror and whose destination is a memory tree
    #    is the manual post-loss restore (the routine restore runs script-side from
    #    on-session-start.py and never crosses the Bash boundary — see the A6 note above).
    if cmd in _COPY_COMMANDS:
        operands = [tok for tok in tokens[1:] if not tok.startswith("-")]
        dest = _strip_quotes(operands[-1]) if operands else ""
        src = _strip_quotes(operands[0]) if len(operands) >= 2 else ""
        mirror_restore = _is_mirror_source(src) and _inside_memory_tree(dest)
        if dest and not mirror_restore and _classifies(dest):
            return True
        # GNU `cp -t DEST src...` / `rsync`/`install` same form.
        for i, tok in enumerate(tokens[1:], start=1):
            if tok == "-t" and i + 1 < len(tokens) and not _is_mirror_source(src) and _classifies(tokens[i + 1]):
                return True
    elif cmd == "truncate":
        # A5: every operand is a target.
        if any(_classifies(tok) for tok in tokens[1:] if not tok.startswith("-")):
            return True
    elif cmd == "dd":
        if any(tok.startswith("of=") and _classifies(tok[3:]) for tok in tokens[1:]):
            return True
    elif cmd == "mv":
        operands = [tok for tok in tokens[1:] if not tok.startswith("-")]
        if len(operands) >= 2:
            src, dst = operands[0], operands[-1]
            if _classifies(dst) and not _is_safe_delete_destination(dst):
                return True
            # mv FROM a memory path to a non-.trashcan destination is deletion-class.
            if _classifies(src) and not _is_safe_delete_destination(dst):
                return True
    # 5. Deletion: rm/unlink/shred/rmdir with ANY argument satisfying either classifier
    #    (A1: `rm -r memory/` — the catastrophic tree shape — included).
    elif cmd in _DELETE_COMMANDS:
        if any(_classifies(tok) for tok in tokens[1:] if not tok.startswith("-")):
            return True
    # 6. touch: manufactures a malformed page (memgrep new-mem-topic is the create path).
    #    ACCEPTED FALSE-POSITIVE (A7): an mtime-only `touch` of an EXISTING page is denied
    #    too — harmless (content unchanged), and distinguishing it would need filesystem
    #    state this static scan must not depend on. Do not "fix" this by probing existence.
    elif cmd == "touch":
        if any(_classifies(tok) for tok in tokens[1:] if not tok.startswith("-")):
            return True

    return False


def _shell_writes_memory_page(command: str) -> bool:
    """True iff any segment of the Bash command writes to or destroys a memory page or
    memory tree (A2: per-segment evaluation — `git checkout x && rm memory/p.md` denies
    because the rm segment rides no exemption)."""
    if not command:
        return False
    for segment in _SEGMENT_SPLIT_RE.split(command):
        if segment.strip() and _segment_has_memory_write(segment):
            return True
    return False


def is_memory_page(file_path: str) -> bool:
    """True iff `file_path` is a wikimem page this hook governs."""
    if not file_path:
        return False
    p = str(Path(file_path)).replace(os.sep, "/")
    if not p.endswith(".md"):
        return False
    return bool(_MEMORY_PATH_RE.search(p)) and not _EXCLUDE_RE.search(p)


def main() -> int:
    if not _enabled():
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 -- unreadable stdin must never block a write
        return 0
    try:
        tool = payload.get("tool_name") or ""
        if tool not in {"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"}:
            return 0
        ti = payload.get("tool_input") or {}
        if tool == "Bash":
            reason = _SHELL_REASON if _shell_writes_memory_page(str(ti.get("command") or "")) else None
        else:
            target = ti.get("file_path") or ti.get("notebook_path") or ""
            reason = _REASON if is_memory_page(str(target)) else None
        if reason is None:
            return 0
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                },
            },
            sys.stdout,
        )
    except Exception:  # noqa: BLE001 -- see the FAIL-OPEN note in the module docstring
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
