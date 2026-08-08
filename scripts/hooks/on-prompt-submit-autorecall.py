#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""UserPromptSubmit hook — automatic memory recall, ON by default (issues #16, #45).

Every ordinary user prompt is run through `memgrep recall` against ALL THREE memory
scopes (LOCAL + PROJECT + USER), and the top notes are injected into the agent
context via `additionalContext` — so the agent is reminded of "have we hit this
before?" WITHOUT having to call recall by hand.

(The docstring's first line used to say "OPT-IN". It was stale: issue #45 flipped the
default to ON in the code below, but this line and the plugin.json manifest kept
saying opt-in for seven releases — see TRDD-98ISATJZ. Claude Code only exports
`CLAUDE_PLUGIN_OPTION_*` when the user SETS the option, so the code default is what
actually governs; the docs simply lied about it.)

Design contract (load-bearing — keep all of these):

  - ON BY DEFAULT (issue #45). The memory system's entire value is realized at
    RECALL time, and lived evidence shows discipline-only recall fails in
    practice — a heavily memory-aware agent still re-derived a framework it had
    itself authored because it did not recall first. So recall must be AUTOMATIC,
    not opt-in. Set `CLAUDE_PLUGIN_OPTION_MEMORY_AUTORECALL=false|0|no|off` to opt
    OUT. The hook stays cheap: it no-ops the instant memgrep is absent, the corpus
    is empty, or the prompt is a cron/slash/trivial line — so a janitor install
    with no memory corpus pays only a couple of fast dir checks, never the recall
    subprocess.

  - AGENT corpus only — PRIVACY BOUNDARY. It searches the agent-visible notes in
    `~/.claude/projects/<slug>/memory/`. It MUST NOT search the PRIVATE user-mem
    store (`…/memory/user-mem/`), which is deliberately agent-invisible: surfacing
    a user memory into agent context would breach the user-mem privacy boundary.
    `memgrep recall` walks a directory RECURSIVELY and has no exclude flag, so
    pointing it at `memory/` WOULD descend into `user-mem/` and leak a private
    note (verified). Instead we enumerate ONLY the top-level `*.md` files of
    `memory/` and pass them to recall as explicit file arguments — recall takes
    file paths verbatim and only walks DIRECTORIES, so the private subtree is
    never traversed. The exclusion is structural, not a flag.

  - Never blocks, never crashes. Cron `[janitor-…]` prompts and slash commands
    (`/…`) are skipped (they are not user questions). Malformed stdin, a missing
    memgrep binary, an empty corpus, a recall timeout, or ANY exception → the
    hook silently no-ops (exit 0, empty stdout) so the user's turn always
    proceeds. The injection is advisory; failure to recall is never fatal.

  - additionalContext is the ONLY channel used (the documented field that
    reaches the model). On a genuine hit it carries the recalled notes + a short
    recall INVITE; on a miss it carries the INVITE alone (TRDD-7B1THXTB); on an
    EMPTY corpus nothing is emitted, so a no-corpus install stays silent.

  - THE RECALL INVITE (TRDD-7B1THXTB). Auto-surfacing ranks the RAW prompt, which
    can miss the note that matters (the motivating failure: macos-keychain.md [^2]
    existed, was not surfaced for the go-live prompt, and the trap was re-hit).
    So every non-trivial prompt ALSO gets a one-line invitation for the agent to
    run its OWN `memgrep recall` with keywords IT derives — the hook never names
    or suggests a specific memory (a future Rust hook may add programmatic
    keyword extraction; this is deliberately just the nudge). Kept to one line
    because it rides every prompt (token economy). Opt out separately with
    `CLAUDE_PLUGIN_OPTION_MEMORY_RECALL_INVITE=false` (opting out of AUTORECALL
    disables the whole hook, invite included).
"""

from __future__ import annotations

import json
import os
import subprocess  # memgrep is invoked with a fixed argv (shell=False); no untrusted command string
import sys
from pathlib import Path

# How many notes to inject, and how long to let recall run. Recall over a local
# SQLite index is sub-second; the timeout only guards a pathological corpus so a
# slow recall degrades to "no recall this turn" instead of stalling the prompt.
_TOP = 3
_TIMEOUT_S = 4.0
# Hard cap on the injected text so a corpus of very long descriptions can't bloat
# the agent context; recall prints one `path — description` line per note.
_MAX_CHARS = 1200
# Triviality guard (issue #45). Now that recall is ON by default it fires on every
# user turn, so a sub-threshold prompt ("yes", "ok", "do it", "go", "push") — which
# carries no recall signal — must NOT trigger a recall+injection, or it would add
# noise to every trivial confirmation. Prompts shorter than this are skipped.
_MIN_PROMPT_CHARS = 12

def _load_libs():
    """Import `user_mem_lib` (for find_memgrep + the agent-memdir resolution) and
    `state` (for is_truthy_env), whether running via the plugin (CLAUDE_PLUGIN_ROOT
    set) or directly (tests). Returns (user_mem_lib, state) or (None, None) when
    the libs cannot be found — in which case the hook becomes a no-op rather than
    crashing the session."""
    candidates: list[Path] = []
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if plugin_root:
        candidates.append(Path(plugin_root) / "scripts" / "lib")
    # Fallback: resolve relative to this file (scripts/hooks/ → scripts/lib/).
    candidates.append(Path(__file__).resolve().parent.parent / "lib")
    for lib_dir in candidates:
        if (lib_dir / "user_mem_lib.py").is_file() and (lib_dir / "state.py").is_file():
            sys.path.insert(0, str(lib_dir))
            try:
                import state  # noqa: E402  -- local module, not PyPI
                import user_mem_lib  # noqa: E402  -- local module, not PyPI

                return user_mem_lib, state
            except Exception:  # pragma: no cover - defensive
                return None, None
    return None, None


def _agent_memdir(um, project_dir: str | None) -> Path:
    """The AGENT memory corpus dir: `~/.claude/projects/<slug>/memory/`.

    Derived as the PARENT of the user-mem store so the slug/HOME resolution stays
    in ONE place (user_mem_lib.resolve_user_mem_dir) — the agent corpus is the
    sibling of, and never includes, the private `user-mem/` subtree.
    """
    return um.resolve_user_mem_dir(project_dir=project_dir).parent


def _agent_notes(memdir: Path) -> list[str]:
    """The top-level real NOTE files of the agent corpus — the search set.

    ONLY the direct children of `memdir`; never the `user-mem/` subdirectory.
    Returns absolute paths sorted for determinism. An unreadable dir yields []
    (the caller then no-ops). This is the structural privacy boundary: by handing
    recall explicit FILE paths we guarantee the recursive walk never reaches the
    private user-mem subtree (recall walks directories, not files).

    F15 (wikimem audit 2026-07-07): each file is ALSO filtered through the
    memory_scopes SSOT `is_note_file` — the LOCAL root's TOP-LEVEL files include
    `MEMORY.md`, `memory-index.md`, and the detectors' `*-proposed.md` reports,
    none of which are notes; a proposal report's gloss lines used to be
    rankable and injectable into agent context as if they were memory.
    """
    import memory_scopes  # importable only after _load_libs put lib on sys.path

    try:
        return sorted(
            str(p) for p in memdir.glob("*.md")
            if p.is_file() and memory_scopes.is_note_file(p)
        )
    except OSError:  # pragma: no cover - defensive
        return []


def _scope_pages(root: Path) -> list[str]:
    """The recallable real NOTE pages of a PROJECT or USER memory root.

    The memory system has THREE scopes (TRDD-c77dae09): LOCAL (the agent corpus,
    handled by `_agent_notes` with its user-mem exclusion), PROJECT
    (`<git-root>/.claude/project/memory/`, git-tracked + pushed), and USER (the
    janitor's FIXED data dir — see `_user_memdir`). PROJECT/USER pages may live
    in subdirectories, so the scan recurses — via the memory_scopes SSOT
    `iter_note_files` (F15), which excludes the generated/index files, the
    `*-proposed.md` detector-report family, `.memgrep/`, `.maint-staging/`, and
    the private `user-mem/` subtree. Absolute paths, sorted; an absent or
    unreadable root yields [].
    """
    import memory_scopes  # importable only after _load_libs put lib on sys.path

    return [str(p) for p in memory_scopes.iter_note_files(root)]


def _project_memdir(project_dir: str | None) -> Path | None:
    """The PROJECT-scope memory root: `<git-root>/.claude/project/memory/`, or None
    when the cwd is not in a git repo. In-repo + namespaced under `.claude/` (a
    bare `memory/` collides with the very common GitHub root-folder name; the
    `.claude/project/memory` path is collision-free). Resolved via
    `git rev-parse --show-toplevel` so a worktree / sub-directory cwd still finds
    the repo root."""
    cwd = (project_dir or os.getcwd()).strip() or None
    try:
        # Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes .git/index.lock
        # and collides with a concurrent `publish.py` commit (janitor#245).
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
            env=git_env,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    top = proc.stdout.strip()
    return (Path(top) / ".claude" / "project" / "memory") if top else None


def _user_memdir() -> Path:
    """The USER-scope (global) memory root: the janitor's FIXED plugin-DATA dir
    `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/` —
    untouchable, survives plugin updates + `--keep-data` uninstall (NOT a
    `~/.claude/<custom>/` folder a cleanup pass could wipe). Not created.

    Resolved through the `memory_scopes` SSOT (M-11, wikimem audit 2026-07-07 —
    never a re-derived literal), which hard-codes the path EXPLICITLY and NEVER
    reads ``${CLAUDE_PLUGIN_DATA}``: that env var holds the *currently-running*
    plugin's data dir, which is the janitor ONLY inside the janitor's own plugin
    hooks. This is a UserPromptSubmit hook fired in the host session where
    ``CLAUDE_PLUGIN_DATA`` is unset or points at whatever plugin owns the turn —
    not necessarily the janitor — so reading it would route USER recall to the
    wrong plugin's dir. Only called AFTER `_load_libs` put scripts/lib on
    sys.path (user_mem_lib itself imports memory_scopes, so it is importable).
    """
    import memory_scopes  # noqa: PLC0415 — importable only after _load_libs

    return memory_scopes.resolve_user_dir()


def _recall(memgrep: str, query: str, note_paths: list[str]) -> str:
    """Run `memgrep recall <query> <note-files…> --top N --use-index` and return
    its stdout (the `path — description` lines) — or "" on any failure/timeout/
    no-hit. `note_paths` are explicit top-level FILES (never the dir), so recall
    never descends into the private user-mem subtree. Fixed argv, no shell.
    """
    argv = [
        memgrep,
        "recall",
        query,
        *note_paths,
        "--top",
        str(_TOP),
        "--use-index",
    ]
    try:
        # Fixed argv, shell=False: `memgrep` is a resolved binary path and the
        # query/paths are positional args (never a shell string), so neither the
        # user prompt nor the note paths can inject a command.
        proc = subprocess.run(
            argv,
            input="",
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout


# The one-line recall INVITE (TRDD-7B1THXTB). Constant, from OUR code — never from
# corpus data — and it names no memory: the agent derives its own keywords. One
# line only: it rides every non-trivial prompt, so every extra word is a standing
# per-turn tax.
_INVITE = (
    "[janitor-memory] Invite: BEFORE acting, consider running your own "
    '`memgrep recall "<symptom keywords you choose>" <memdir>` across the 3 memory '
    "scopes (protocol: ~/.claude/rules/markdown-memory-recall.md) — the corpus may "
    "already know this."
)


def _invite_enabled(state) -> bool:
    """The invite's own opt-out (default ON), separate from AUTORECALL's."""
    return state.is_truthy_env("CLAUDE_PLUGIN_OPTION_MEMORY_RECALL_INVITE", default=True)


def _format_context(recall_out: str) -> str | None:
    """Turn recall's `path — description` lines into a compact additionalContext
    block, or None when there are no usable lines. Caps total length so a few
    very long descriptions cannot bloat the agent context.

    F14 (wikimem audit 2026-07-07): every recall line is UNTRUSTED corpus data —
    note descriptions, atom bodies, lesson text; a poisoned PROJECT-scope page
    arrives via git from any contributor. Each line is stripped of invisible/
    bidi unicode and bracket-defanged (`[` `]` → `⟦` `⟧`) BEFORE injection, so a
    note cannot smuggle a marker-shaped or authority-shaped line (a fake
    `[janitor-…]` marker, a forged `[user-mem #N — shared by the user]` header)
    into the agent context on every matching prompt. The one legitimate `[…]`
    header below is OURS and is added AFTER sanitization.
    """
    import security_helpers  # importable only after _load_libs put lib on sys.path
    import state as state_mod

    lines = [
        state_mod.sanitize_for_drift_line(
            security_helpers.strip_invisible_unicode(ln.rstrip())
        )
        for ln in recall_out.splitlines()
        if ln.strip()
    ]
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return None
    body = "\n".join(lines)[:_MAX_CHARS]
    return (
        "[janitor-memory] Possibly-relevant notes from your memory corpus, as "
        "`<date>  <id-or-path>  <description>` rows — the description is a TRIAGE "
        "surface, not the answer. Run `memgrep recall <id-or-path>` on the one you "
        "want to get its full body and lessons:\n" + body
    )


def main() -> int:
    # ON BY DEFAULT (issue #45): there is no off-by-default early-out. The toggle is
    # resolved below via `is_truthy_env(default=True)` once `state` is imported, so
    # an unset/empty env var means recall is ON and only an explicit false value
    # (`false|0|no|off`) opts out. A no-corpus install still no-ops cheaply (no
    # notes → return before the recall subprocess), so default-ON is not costly.
    try:
        raw = sys.stdin.read()
    except Exception:  # pragma: no cover - stdin closed
        return 0
    if not raw or not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return 0

    um, state = _load_libs()
    if um is None or state is None:
        return 0

    # Honour the env var via the shared spelling-of-false rules — DEFAULT TRUE
    # (issue #45): unset/empty → recall is ON; `false`/`0`/`no`/`off` opts out.
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_MEMORY_AUTORECALL", default=True):
        return 0

    stripped = prompt.strip()
    # Skip our own cron heartbeats (`[janitor-…]`) and any slash command — neither
    # is a user question, and recalling on them would inject noise every tick.
    if stripped.startswith("[janitor-") or stripped.startswith("/"):
        return 0
    # Triviality guard (issue #45): now that recall is ON by default it fires on
    # every turn, so a very short prompt ("yes", "do it", "push") — which carries no
    # recall signal — is skipped, or it would inject notes on bare confirmations.
    if len(stripped) < _MIN_PROMPT_CHARS:
        return 0

    memgrep = um.find_memgrep()
    if not memgrep:
        # No binary → cannot recall; stay a silent no-op (issue #16: "no-op when
        # memgrep is absent").
        return 0

    project_dir = (os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "").strip() or None

    # Compose ALL THREE memory scopes into ONE recall (TRDD-c77dae09): LOCAL (the
    # agent corpus, with its structural user-mem exclusion) → PROJECT
    # (`<git-root>/.claude/project/memory/`) → USER (the janitor's FIXED data dir,
    # see `_user_memdir`). recall takes explicit
    # FILE paths and only walks DIRECTORIES, so passing files keeps the private
    # `user-mem/` subtree untraversed AND lets one invocation rank across all
    # roots. Ordering is most-specific-first so that, all else equal, a local note
    # precedes a project/user note in the input order. A scope whose dir is absent
    # contributes nothing.
    local_dir = _agent_memdir(um, project_dir)
    note_paths: list[str] = []
    if local_dir.is_dir():
        note_paths.extend(_agent_notes(local_dir))  # top-level *.md only (user-mem excluded)
    project_dir_mem = _project_memdir(project_dir)
    if project_dir_mem is not None:
        note_paths.extend(_scope_pages(project_dir_mem))
    note_paths.extend(_scope_pages(_user_memdir()))
    # De-duplicate while preserving most-specific-first order (a path could in
    # principle appear via two roots if they overlap; keep the first occurrence).
    seen_paths: set[str] = set()
    deduped: list[str] = []
    for pth in note_paths:
        if pth not in seen_paths:
            seen_paths.add(pth)
            deduped.append(pth)
    note_paths = deduped

    if not note_paths:
        # No notes in any scope (empty/absent corpora, or only the private
        # user-mem store) → nothing the agent may recall.
        return 0

    recall_out = _recall(memgrep, stripped, note_paths)
    context = _format_context(recall_out)

    # TRDD-7B1THXTB: the invite fires on hit AND miss — the miss is exactly the
    # case that burned us (the right note existed but the raw-prompt ranking did
    # not surface it). Only an EMPTY corpus (returned above) stays fully silent.
    if _invite_enabled(state):
        context = f"{context}\n{_INVITE}" if context is not None else _INVITE
    if context is None:
        return 0

    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    # Bare main() so the module is importable without side effects; the hook
    # always exits 0 (any internal failure degrades to a no-op, never aborting
    # the user's turn).
    main()
