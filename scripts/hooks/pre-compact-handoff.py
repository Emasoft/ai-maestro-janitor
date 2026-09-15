#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PreCompact hook — write a FILESYSTEM-GROUNDED handoff before each compaction.

Why this hook exists (the load-bearing reason — the real failure it fixes):
After a compaction the agent treated the compaction SUMMARY as ground truth and
confidently asserted stale/wrong facts (an OAuth account's health %, "published
vs not", whole narratives) it NEVER re-verified — the summary promoted day-old
hypotheses to "fact". A compaction summary is lossy and can PROMOTE a transient
wrong hypothesis to a stated fact.

This hook gives the post-compaction turn an AUTHORITATIVE, un-hallucinatable
re-grounding point. On every PreCompact it writes a handoff built from on-disk
truth + VERBATIM transcript MESSAGES (never the lossy SUMMARY — raw recent turns
are ground truth, not a summary) to a STABLE path under the project's janitor
state dir (`<state>/precompact-handoff.md`):

  * git HEAD + the last ~12 commits (oneline),
  * `git status --short` (the real working-tree state),
  * the plugin version,
  * the newest in-flight TRDD(s) on the design board, with their `## ⏵ STATE`
    blocks copied VERBATIM,
  * the last N user↔assistant turns VERBATIM from the transcript (raw messages,
    NOT the summary; heartbeat / tool-result / meta turns filtered out, each turn
    bounded + truncated, the most-recent user ask always surfaced),
  * the most-recently-updated memory pages — IDs ONLY (the atom ids, or the page
    itself when it holds >5 atoms); detector artifacts and the PRIVATE user-mem
    store are never listed,
  * a standing faithfulness instruction (treat the summary as UNVERIFIED).

Because every line is read from disk at compaction time, NONE of it can be
hallucinated. The next session is steered to read this file FIRST: the existing
resume loop (post-compact-resume.py records the directive → dispatch.py emits the
single `[janitor-resume]` cue) prepends a "read precompact-handoff.md FIRST"
pointer when this file exists.

CONTRACT (verified against the official Claude Code hooks docs 2026-06-25 —
https://code.claude.com/docs/en/hooks):
  * PreCompact stdin JSON carries the COMMON fields: `session_id`,
    `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`. The
    `/compact`-vs-auto distinction is the hook MATCHER (`manual`|`auto`); the
    payload is not guaranteed to carry a `trigger` field, so we read it
    opportunistically and never depend on it.
  * PreCompact does NOT support `hookSpecificOutput.additionalContext` — it
    CANNOT inject text into the compacted context. So the faithfulness
    instruction is delivered through the EXISTING [janitor-resume] loop (which
    DOES reach the next turn), not through this hook's output. This hook MAY emit
    a best-effort `systemMessage` pointing at the handoff for the summarizer in
    the SAME turn.
  * Exit 2 OR `decision:"block"` would BLOCK compaction. This hook MUST NEVER
    block — it always exits 0 and never sets `decision`. A hook fault must never
    disrupt compaction, so everything is wrapped and degrades to a
    "(unavailable)" line.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# The stable, in-place handoff file the post-compaction turn must read first.
HANDOFF_FILENAME = "precompact-handoff.md"

# In-flight = a TRDD actively being worked (matches post-compact-resume.py): not
# parked (backburner/todo), not blocked, not terminal, not soak-monitoring.
_INFLIGHT_COLUMNS = frozenset(
    {"design", "dispatch", "dev", "testing", "ai_review", "human_review"}
)

# Canonical TRDD filename shape: TRDD-<YYYYMMDD_HHMMSS±HHMM>-<uid8>-<slug>.md.
# [0-9A-Za-z]: TRDD v2 ids are UPPERCASE base36, legacy v1 ids lowercase hex — hex-only
# here dropped every modern in-flight TRDD from the pre-compaction handoff, so the
# post-compact turn re-grounded without the current task's STATE block.
_UID_RE = re.compile(r"TRDD-\d{8}_\d{6}[+-]\d{4}-([0-9A-Za-z]{8})-")

# Matches the STATE head heading "## ⏵ STATE …" / "## STATE …" (⏵ = U+23F5).
_STATE_HEADING = re.compile(r"^##\s+(?:⏵\s*)?STATE\b")

MAX_TRDDS = 3              # how many in-flight TRDDs to copy STATE blocks for
MAX_STATE_LINES = 160      # cap STATE lines per TRDD so the handoff stays bounded
MAX_COMMITS = 12           # recent commits in the oneline log
_FRONT = 4000              # bytes of head to scan for frontmatter fields
RECENT_TURNS = 5           # verbatim user/assistant turns to carry from the transcript
_TAIL_BYTES = 2_000_000    # scan the transcript TAIL (the log can be 100s of MB; user-text
                           #   turns are sparse — dwarfed by tool_result/assistant turns — so
                           #   the tail must be generous to contain the recent real exchange)
_MAX_TURN_CHARS = 1500     # truncate each turn so the handoff stays bounded
_MEM_RECENT_WINDOW_S = 86_400  # a memory page counts as "recently updated" within 24h
_MEM_MAX_FILES = 8             # cap the recent-memory section
_MEM_ATOMS_COLLAPSE = 5        # > this many atoms in one file → list the FILE, not the atoms

# --- trigger=="auto" continuity record (TRDD-7MGJYLY5) ---------------------------------
# Owner ruling: an autocompaction needs no summarization/handoff — the harness already
# does that — the janitor only nudges the resumed turn toward its prior work. So a
# harness autocompact writes a SMALL machine-readable record instead of the prose
# handoff above; only a manual/unknown-trigger compaction still gets the prose.
CONTINUITY_FILENAME = "precompact-continuity.json"
# Written on EVERY PreCompact firing (auto or manual, even when the auto record itself
# is debounced) — the ordering-hole fix (review finding on TRDD-7MGJYLY5): SessionStart
# must decide which of the two records to read by WHAT PreCompact SAID it saw, never by
# comparing file mtimes. A manual /compact (writes the prose handoff) followed within
# the debounce window by an auto firing (debounced — no continuity write) left the prose
# file the newer one under the old mtime comparison, so an AUTO compaction injected the
# full prose handoff — exactly the ruling this feature exists to prevent.
_LAST_TRIGGER_FILENAME = "precompact-last-trigger.json"
# Debounce applies ONLY to trigger=="auto" (coordinator addendum to TRDD-7MGJYLY5): a
# manual /compact typed twice on purpose must write both times. Measured 2026-09-15
# (TRDD-ANIME2SVG): 7 auto firings in 48s for one real compaction.
_CONTINUITY_DEBOUNCE_WINDOW_S = 120
# "Active" skills = every distinct `Skill` tool_use name across the WHOLE transcript,
# most-recent first, capped — a turn-count window misses a MODE skill (e.g. /ponytail)
# activated long before the window (review finding on TRDD-7MGJYLY5). Read backward in
# fixed-size chunks so a long transcript is never loaded whole into memory.
_ACTIVE_SKILLS_MAX = 8
_ACTIVE_SKILLS_CHUNK_BYTES = 65_536
_OPEN_FILES_MAX = 20
# Uncapped background_agents was a real bug (review finding, TRDD-7MGJYLY5): the nudge's
# ≤15-line render is a single END-OF-LIST slice, so a session with many live agents could
# silently truncate the active_skills/open_files sections entirely, and — because
# `pending_agents.pending()` is OLDEST-first — keep the STALEST agents while dropping the
# newest (most relevant) ones. Cap + reverse to newest-first at the source instead.
_BACKGROUND_AGENTS_MAX = 5

# Files under a memory dir that are NOT wiki notes — never list them here (the librarian's
# reorg/index files regenerate constantly, and MEMORY.md is the HARNESS's own file, a
# coexisting system the janitor only bridges to, never a wiki note to summarize).
_MEM_EXCLUDE_NAMES = frozenset({"MEMORY.md", "memory-reorg-proposed.md", "memory-index.md"})

# An atom's LEADING block-property marker `^<id> [<props>]` (TRDD-3b9b2040): group 1 = the atom
# id; group 2 = the rest of the marker line after `[` (where a `desc:` slug, if any, lives).
_ATOM_MARKER_RE = re.compile(r"(?m)^\s*\^([A-Za-z0-9][\w-]*)\s*\[([^\n]*)")
# The atom `desc:` value is a snake_case SLUG (`[a-z0-9_]+`, TRDD-056384eb) — a single token,
# stored AS the slug, DISPLAYED `_`→space (mirrors memgrep's desc_display). memgrep's Rust parser
# is the authoritative grammar; this is a best-effort, fail-open single-line scan, never the SSOT.
_ATOM_DESC_RE = re.compile(r"desc:\s*([a-z0-9_]+)")


def _run_git(args: list[str], cwd: Path, *, timeout: float = 5.0) -> str:
    """Run a git command in `cwd`, return stdout or "" on any failure.

    Best-effort and exception-proof: a missing git, a non-repo cwd, or a timeout
    must not break the handoff (the section degrades to "(unavailable)").

    Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes .git/index.lock and
    collides with a concurrent `publish.py` commit (janitor#245).
    """
    try:
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=git_env,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.rstrip("\n")


def _git_toplevel(start: Path) -> str:
    """The work-tree root of the repo containing `start`, or "" if `start` is not in a repo.

    `git rev-parse --show-toplevel` walks UP only — so it finds a repo at `start` or any
    ancestor of it, but never a repo in a CHILD of `start`. That asymmetry is the whole
    bug this resolution exists to work around (issue #66)."""
    return _run_git(["rev-parse", "--show-toplevel"], start)


def _resolve_git_root(project_root: Path, cwd: str = "") -> Path:
    """Resolve the actual git work-tree root to run the handoff's git sections from.

    WHY (issue #66): the git commands used to run with `cwd=$CLAUDE_PROJECT_DIR`, but
    `git rev-parse` only walks UP toward parents — never DOWN into children. In the common
    multi-repo layout where `$CLAUDE_PROJECT_DIR` is the PARENT of the actual repo
    (`<project>/<repo>/.git`), every git command exits 128 and each section silently
    degraded to "(unavailable)" even though a healthy repo sits one level below.

    Resolution order (strictly ADDITIVE — the repo-at-root case is unchanged, and we fall
    back to `project_root` so a genuinely repo-less tree still renders "(unavailable)"):
      1. the session `cwd` (if it is inside a repo) — handles a session launched within a
         subdir-repo, and is preferred so the RIGHT repo wins when several siblings exist;
      2. `project_root` itself (the historical behavior — repo at, or above, $CLAUDE_PROJECT_DIR);
      3. a shallow scan of `project_root`'s IMMEDIATE children for a `.git` entry (a dir for a
         normal repo, a FILE for a worktree/submodule), verified to be a real repo; when more
         than one child matches, prefer the one that contains `cwd`, else the first by name;
      4. `project_root` unchanged — nothing found, preserve today's degraded output.
    """
    # 1. The session cwd, if it sits inside a repo (subdir-repo session, or any descendant).
    if cwd:
        top = _git_toplevel(Path(cwd))
        if top:
            return Path(top)
    # 2. project_root itself — repo at or above $CLAUDE_PROJECT_DIR (the historical path).
    top = _git_toplevel(project_root)
    if top:
        return Path(top)
    # 3. Shallow-scan immediate children for a repo `project_root` can't see by walking up.
    cwd_path = Path(cwd).resolve() if cwd else None
    matches: list[Path] = []
    try:
        children = sorted(project_root.iterdir(), key=lambda p: p.name)
    except OSError:
        children = []
    for child in children:
        try:
            if not child.is_dir():
                continue
            if not (child / ".git").exists():  # .git is a dir (normal) OR a file (worktree/submodule)
                continue
        except OSError:
            continue
        top = _git_toplevel(child)
        if not top:
            continue
        root = Path(top)
        # Prefer the repo that actually contains the session cwd when siblings both match.
        if cwd_path is not None:
            try:
                cwd_path.relative_to(root.resolve())
                return root
            except ValueError:
                pass
        matches.append(root)
    if matches:
        return matches[0]
    # 4. Nothing found — keep the historical fallback (renders "(unavailable)" if repo-less).
    return project_root


def _plugin_version(plugin_root: str) -> str:
    """Read the plugin's declared version from .claude-plugin/plugin.json."""
    if not plugin_root:
        return "unknown"
    try:
        data = json.loads(
            (Path(plugin_root) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        return str(data.get("version", "unknown")) if isinstance(data, dict) else "unknown"
    except (OSError, ValueError, TypeError):
        return "unknown"


def _frontmatter_field(head: str, key: str) -> str:
    """First value of a top-level `key:` line in a TRDD frontmatter head.

    maxsplit=1 keeps the colons inside an ISO `updated:` value intact.
    """
    for line in head.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""


def _is_inflight(head: str) -> bool:
    """True iff this TRDD head is actively being worked (v2 column OR v1 status)."""
    column = _frontmatter_field(head, "column")
    if column:
        return column in _INFLIGHT_COLUMNS
    # Legacy v1 fallback: status: in-progress is the in-flight equivalent.
    return _frontmatter_field(head, "status") == "in-progress"


def _state_block(text: str) -> str | None:
    """Extract the `## STATE` head section (until the next `## ` heading), capped."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if _STATE_HEADING.match(ln)), None)
    if start is None:
        return None
    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")),
        len(lines),
    )
    block = lines[start:end]
    if len(block) > MAX_STATE_LINES:
        block = block[:MAX_STATE_LINES] + [
            "… (STATE block truncated — read the full TRDD file)"
        ]
    return "\n".join(block).strip()


def _inflight_trdds(
    project_root: Path, git_root: Path | None = None
) -> list[tuple[str, str, str, str]]:
    """Return in-flight TRDDs as (updated, name, title, full_text), newest first.

    `updated:` is an ISO-8601 string that sorts lexicographically within a shared
    local TZ offset, so a reverse string sort puts the most recently touched
    in-flight task first — the best "what was I just doing" heuristic.

    WHY the `git_root` fallback (issue #267): per `trdd-design-tasks.md`, `design/tasks/`
    is a PROJECT-scope dir rooted at the *repo* root, not necessarily at
    `$CLAUDE_PROJECT_DIR`. #66 already resolves that nested-repo layout (repo one level
    below `$CLAUDE_PROJECT_DIR`) into `git_root` for the git sections; without applying
    the same resolution here, a nested layout makes this function silently return `[]`
    — byte-identical to "the board is genuinely empty" — right next to git sections that
    correctly show the resolved subdir repo. Trying `project_root` FIRST preserves the
    historical/common case (repo at project_root, or no git_root) unchanged.
    """
    tasks_dir = project_root / "design" / "tasks"
    if not tasks_dir.is_dir() and git_root is not None:
        tasks_dir = git_root / "design" / "tasks"
    if not tasks_dir.is_dir():
        return []
    rows: list[tuple[str, str, str, str]] = []
    for path in tasks_dir.glob("TRDD-*.md"):
        if not _UID_RE.search(path.name):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        head = text[:_FRONT]
        if not _is_inflight(head):
            continue
        updated = _frontmatter_field(head, "updated")
        title = _frontmatter_field(head, "title") or path.name
        rows.append((updated, path.name, title[:80].strip(), text))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows[:MAX_TRDDS]


def _extract_text(content: object) -> str:
    """Concatenate the TEXT of a transcript message's content, ignoring tool_use /
    tool_result / thinking blocks. Content is a plain string OR a list of typed
    blocks (the real Claude Code transcript shape). Defensive: an unknown shape → ""."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                txt = block.get("text")
                if isinstance(txt, str) and txt:
                    parts.append(txt)
        return "\n".join(parts)
    return ""


def _recent_turns(transcript_path: str, n: int = RECENT_TURNS) -> list[tuple[str, str]] | None:
    """The last `n` GENUINE user/assistant TEXT turns from the session transcript.

    Sourced from the PreCompact payload's `transcript_path` (a JSONL log). This is
    the one handoff section that is conversation-derived rather than disk/git — but
    it is VERBATIM (the recorded turns), NOT the lossy summary, so it stays an
    un-hallucinatable anchor: what the user just asked and what was just answered.

    Robustness (the hook must NEVER break a compaction):
      * Only the TAIL (`_TAIL_BYTES`) is read — the transcript can be many MB; a
        seek-to-tail bounds the work regardless of session length (a fragmentary
        first line after the seek is dropped).
      * Every line is parsed defensively — a malformed line is skipped, never fatal.
      * Heartbeat-cron `user` prompts, `isMeta`/`isSidechain`/`isCompactSummary`
        turns, and pure tool_use / tool_result / thinking turns are filtered out so
        the `n` slots hold real exchange.
      * Each kept turn is truncated to `_MAX_TURN_CHARS`.
    Any failure (or nothing usable) returns None → the caller renders
    "(recent conversation unavailable)". Returns (role, text) newest-LAST.
    """
    if not transcript_path:
        return None
    path = Path(transcript_path)
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            seeked = size > _TAIL_BYTES
            if seeked:
                fh.seek(size - _TAIL_BYTES)
            raw = fh.read()
    except OSError:
        return None
    lines = raw.decode("utf-8", errors="replace").splitlines()
    if seeked and lines:
        lines = lines[1:]  # drop the probably-partial first line after the tail seek

    turns: list[tuple[str, str]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") not in ("user", "assistant"):
            continue
        if obj.get("isMeta") or obj.get("isSidechain") or obj.get("isCompactSummary"):
            continue
        message = obj.get("message")
        role = str((message.get("role") if isinstance(message, dict) else None) or obj.get("type") or "")
        content = message.get("content") if isinstance(message, dict) else obj.get("content")
        text = _extract_text(content).strip()
        if not text:
            continue  # pure tool_use / tool_result / thinking turn — no conversation
        if role == "user" and text.startswith("[janitor-heartbeat]"):
            continue  # the cron heartbeat prompt, not user conversation
        turns.append((role, text))

    if not turns:
        return None
    window = turns[-n:]
    # A long ASSISTANT work-streak (autonomous building) would push the user's most
    # recent ask off a pure last-n window — leaving only my replies with no context
    # of what was asked. Always include the most recent user turn.
    if not any(role == "user" for role, _ in window):
        last_user = next(
            (i for i in range(len(turns) - 1, -1, -1) if turns[i][0] == "user"), None
        )
        if last_user is not None and last_user < len(turns) - n:
            window = [turns[last_user], *window]
    out: list[tuple[str, str]] = []
    for role, text in window:
        if len(text) > _MAX_TURN_CHARS:
            text = text[:_MAX_TURN_CHARS] + " … (truncated)"
        out.append((role, text))
    return out


def _memory_scope_dirs(project_root: Path) -> list[tuple[str, Path]]:
    """Best-effort: the (scope, root) memory dirs to scan (LOCAL + PROJECT + USER).

    Prefers the shared `lib.memory_scopes` resolver (the SSOT for the three scopes);
    on ANY failure falls back to the PROJECT-scope dir under `project_root`. Returns
    only existing dirs, SCOPE-LABELLED so a same-named page in two scopes is
    distinguishable. Never raises — a resolution fault must not break the handoff."""
    try:
        from lib import memory_scopes  # noqa: PLC0415 - local package, best-effort

        pairs = [(scope, Path(root)) for scope, root in memory_scopes.resolve_scope_dirs()]
    except Exception:  # noqa: BLE001 - import/resolution must never break the handoff
        pairs = [("project", project_root / ".claude" / "project" / "memory")]
    return [(scope, d) for scope, d in pairs if d.is_dir()]


def _recent_memory_atoms(
    scope_dirs: list[tuple[str, Path]], *, now: float
) -> list[tuple[str, str, str, int, list[tuple[str, str | None]]]]:
    """Recently-updated memory pages across `scope_dirs`, with their atom IDs + `desc`.

    A best-effort proxy for "memories created/updated this session": the `*.md`
    pages modified within `_MEM_RECENT_WINDOW_S`, newest first, capped at
    `_MEM_MAX_FILES`. For each we extract the LEADING block-property atom markers
    (`^<id> [...]`) — the atom ID and its optional one-line `desc:` SLUG, never the
    atom BODY content. Collapse rule: a page with more than `_MEM_ATOMS_COLLAPSE`
    atoms is reported as the FILE (with a count), not its individual atoms; a prose
    page (no atoms) is reported by filename (the page IS the memory unit). Rows are
    (kind, scope, name, atom_count, atoms) — `atoms` a list of `(id, desc_slug|None)`
    — with kind ∈ {"atoms", "collapsed", "page"}.

    EXCLUSIONS: `_MEM_EXCLUDE_NAMES` (detector artifacts, not memories) are skipped;
    the PRIVATE `user-mem/` store is NEVER listed — the handoff is read by the agent
    and user-mem is agent-invisible by design, so surfacing its ids would leak it.
    Same physical file reached via overlapping scopes is de-duplicated. Never raises."""
    candidates: list[tuple[float, str, Path]] = []
    seen_paths: set[str] = set()
    for scope, d in scope_dirs:
        try:
            for path in d.rglob("*.md"):
                if path.name in _MEM_EXCLUDE_NAMES:
                    continue
                if "user-mem" in path.parts:  # PRIVATE store — never surface to the agent
                    continue
                key = str(path.resolve())
                if key in seen_paths:  # same physical file via overlapping scope roots
                    continue
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if now - mtime <= _MEM_RECENT_WINDOW_S:
                    seen_paths.add(key)
                    candidates.append((mtime, scope, path))
        except OSError:
            continue
    candidates.sort(key=lambda r: r[0], reverse=True)

    rows: list[tuple[str, str, str, int, list[tuple[str, str | None]]]] = []
    for _, scope, path in candidates[:_MEM_MAX_FILES]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        atoms: list[tuple[str, str | None]] = []
        seen_ids: set[str] = set()
        for m in _ATOM_MARKER_RE.finditer(text):
            atom_id = m.group(1)
            if atom_id in seen_ids:
                continue
            seen_ids.add(atom_id)
            dm = _ATOM_DESC_RE.search(m.group(2))  # the desc slug on this marker line, if any
            atoms.append((atom_id, dm.group(1) if dm else None))
        if not atoms:
            rows.append(("page", scope, path.name, 0, []))
        elif len(atoms) > _MEM_ATOMS_COLLAPSE:
            rows.append(("collapsed", scope, path.name, len(atoms), []))
        else:
            rows.append(("atoms", scope, path.name, len(atoms), atoms))
    return rows


def _format_memory_rows(
    rows: list[tuple[str, str, str, int, list[tuple[str, str | None]]]],
) -> list[str]:
    """Render the recent-memory rows as handoff lines. An atom's `desc` SLUG is shown `_`→space
    (mirrors memgrep's desc_display, so the reader sees a phrase, not the raw slug); a page with
    more than `_MEM_ATOMS_COLLAPSE` atoms collapses to the FILE; a prose page is its filename."""
    lines: list[str] = []
    for kind, scope, name, count, atoms in rows:
        if kind == "atoms":
            lines.append(f"- [{scope}] {name}:")
            for atom_id, desc in atoms:
                lines.append(f"    ^{atom_id} — {desc.replace('_', ' ')}" if desc else f"    ^{atom_id}")
        elif kind == "collapsed":
            lines.append(f"- [{scope}] {name} ({count} atoms — file listed, >{_MEM_ATOMS_COLLAPSE})")
        else:
            lines.append(f"- [{scope}] {name}")
    return lines


def _tool_use_blocks_tail(transcript_path: str, tail_bytes: int = _TAIL_BYTES) -> list[dict]:
    """All ASSISTANT `tool_use` blocks in the transcript TAIL, oldest-first, fail-open [].

    Same tail-seek/decode/skip-malformed-line contract as `_recent_turns` — the
    transcript can be many MB, and a parser fault must never break the handoff.
    """
    if not transcript_path:
        return []
    path = Path(transcript_path)
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            seeked = size > tail_bytes
            if seeked:
                fh.seek(size - tail_bytes)
            raw = fh.read()
    except OSError:
        return []
    lines = raw.decode("utf-8", errors="replace").splitlines()
    if seeked and lines:
        lines = lines[1:]  # drop the probably-partial first line after the tail seek
    blocks: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict) or obj.get("type") != "assistant":
            continue
        message = obj.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        blocks.extend(b for b in content if isinstance(b, dict) and b.get("type") == "tool_use")
    return blocks


def _active_skills_from_transcript(
    transcript_path: str,
    max_skills: int = _ACTIVE_SKILLS_MAX,
    chunk_bytes: int = _ACTIVE_SKILLS_CHUNK_BYTES,
) -> list[str]:
    """Distinct `Skill` tool_use names across the WHOLE transcript, most-recent first,
    capped at `max_skills` (review fix on TRDD-7MGJYLY5: a turn-count window misses a
    MODE skill — e.g. /ponytail — activated long before the window; a fresh-invocation
    skill used minutes ago and a still-active mode skill loaded hours ago are equally
    "active" for the resumed turn). Reads the transcript BACKWARD in `chunk_bytes`
    slices — never the whole file at once, however long the session ran — and stops as
    soon as `max_skills` distinct names are found or the file is exhausted. Fail-open:
    never raises."""
    if not transcript_path:
        return []
    path = Path(transcript_path)
    try:
        size = path.stat().st_size
    except OSError:
        return []
    names: list[str] = []
    seen: set[str] = set()
    pos = size
    carry = b""  # partial line (RAW BYTES) left over from the START of the chunk read so
    # far. Splitting on the byte b"\n" BEFORE decoding — never decode-then-split — is
    # load-bearing: a UTF-8 continuation byte is never 0x0A, so a multi-byte character
    # split across a chunk boundary can never straddle a line split, and `carry` glues the
    # two halves of its raw bytes back together before either side is decoded. Decoding
    # each chunk independently (the earlier, wrong shape) would run `errors="replace"` on
    # each half separately and silently corrupt any name whose bytes crossed a boundary.
    while pos > 0 and len(names) < max_skills:
        start = max(0, pos - chunk_bytes)
        try:
            with path.open("rb") as fh:
                fh.seek(start)
                raw = fh.read(pos - start)
        except OSError:
            break
        data = raw + carry
        lines = data.split(b"\n")
        # lines[0] may be a partial line split mid-record at the chunk boundary — carry
        # it into the NEXT (earlier) chunk read, unless this chunk already reached byte 0.
        carry = lines[0] if start > 0 else b""
        body_lines = lines[1:] if start > 0 else lines
        for line_bytes in reversed(body_lines):
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(obj, dict) or obj.get("type") != "assistant":
                continue
            message = obj.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in reversed(content):
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                if block.get("name") != "Skill":
                    continue
                tool_input = block.get("input")
                name = ""
                if isinstance(tool_input, dict):
                    name = str(tool_input.get("command", "") or tool_input.get("skill", "") or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                names.append(name)
                if len(names) >= max_skills:
                    return names
        pos = start
    return names


def _open_files_from_transcript(
    transcript_path: str, project_root: Path, limit: int = _OPEN_FILES_MAX
) -> list[str]:
    """Distinct `Read`/`Edit` file_paths, most-recent first, kept only when they sit
    UNDER `project_root` and are not scratch/report noise — a scratch or report path
    told to the resumed turn as "open" is worse than not mentioning it (review fix on
    TRDD-7MGJYLY5). Excludes: any `reports/`- or `*_dev/`-named path segment, and any
    dotfile/dotdir segment. Capped at `limit`. MENTIONED only — the resumed turn is
    never asked to re-read them (owner ruling TRDD-7MGJYLY5). Fail-open: a path that
    can't be resolved is skipped, never raises.

    DELIBERATELY `project_root`, not `git_root` (review churn, TRDD-7MGJYLY5, third
    pass): widening to `git_root` for the issue #66 nested-repo case (`CLAUDE_PROJECT_DIR`
    a subdir of the real repo) re-admits whatever sits BETWEEN the two roots, and a
    denylist of "noise" directory names to compensate matches ANYWHERE in the relative
    path — excluding a genuinely in-scope file that happens to live under a
    project-owned `build/`/`vendor/`/`target/` directory. Trading a rare
    under-inclusion (a file open outside a narrower `project_root`, in the rare nested
    layout) for a broader false-exclusion risk across every session is the wrong
    trade; the nested-repo case is accepted as a known, narrow limitation instead."""
    blocks = [b for b in _tool_use_blocks_tail(transcript_path) if b.get("name") in ("Read", "Edit")]
    try:
        root = project_root.resolve()
    except OSError:
        root = project_root
    paths: list[str] = []
    seen: set[str] = set()
    for block in reversed(blocks):
        tool_input = block.get("input")
        path_str = str(tool_input.get("file_path", "") or "").strip() if isinstance(tool_input, dict) else ""
        if not path_str or path_str in seen:
            continue
        try:
            resolved = Path(path_str).resolve()
            rel_parts = resolved.relative_to(root).parts
        except (OSError, ValueError):
            continue  # unresolvable, or not under the project root
        if any(part.startswith(".") for part in rel_parts):
            continue
        if any(part == "reports" or part.endswith("_dev") for part in rel_parts):
            continue
        seen.add(path_str)
        paths.append(path_str)
        if len(paths) >= limit:
            break
    return paths


def _inflight_trdd_ids(project_root: Path, git_root: Path | None) -> list[str]:
    """`TRDD-<uid8>` ids of the in-flight tasks, newest first — id only, no title/STATE
    (the continuity record is a small pointer, not a second prose handoff)."""
    ids: list[str] = []
    for _updated, name, _title, _text in _inflight_trdds(project_root, git_root):
        m = _UID_RE.search(name)
        if m:
            ids.append(f"TRDD-{m.group(1)}")
    return ids


def _background_agents(state_dir: Path | None) -> list[dict[str, str]]:
    """Live (non-`stopped`) background agents from `pending-agents.json`, as
    `{agentId, description}` — enough for a `SendMessage` resume, no more. Capped at
    `_BACKGROUND_AGENTS_MAX`, NEWEST first — `pending_agents.pending()` is
    oldest-first, so this both bounds the nudge render and keeps the agents most
    likely to still matter (review finding: an uncapped, oldest-first list let a busy
    session's nudge exhaust its line budget on stale agents). Fail-open: any
    import/read fault (missing lib, corrupt manifest) degrades to []."""
    try:
        from lib import pending_agents  # noqa: PLC0415 - local package, best-effort

        entries = pending_agents.pending(state_dir=state_dir)
    except Exception:  # noqa: BLE001 - a manifest fault must never break the hook
        return []
    live = [
        {"agentId": str(e.get("agentId", "")), "description": str(e.get("description", ""))}
        for e in entries
        if isinstance(e, dict) and not e.get("stopped")
    ]
    return list(reversed(live[-_BACKGROUND_AGENTS_MAX:]))


def _build_continuity_record(
    project_root: Path,
    trigger: str,
    transcript_path: str,
    session_id: str,
    cwd: str,
    state_dir: Path | None,
) -> dict:
    """The trigger=="auto" continuity record: on-disk facts only, no prose. Every
    field is best-effort/fail-open by construction of the helpers it calls."""
    git_root = _resolve_git_root(project_root, cwd)
    return {
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "session_id": session_id,
        "trigger": trigger or "unknown",
        "inflight_trdds": _inflight_trdd_ids(project_root, git_root),
        "background_agents": _background_agents(state_dir),
        "active_skills": _active_skills_from_transcript(transcript_path),
        # `project_root`, deliberately not `git_root` (review churn, TRDD-7MGJYLY5,
        # settled on third pass) — see `_open_files_from_transcript`'s own docstring
        # for why widening to `git_root` was tried and reverted.
        "open_files": _open_files_from_transcript(transcript_path, project_root),
    }


def _file_mtime(path: Path) -> float:
    """`path`'s mtime, or 0.0 if it doesn't exist — stdlib-only (no `lib.state`
    dependency, since this hook must degrade even when the state lib fails to import)."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _debounced(sd: Path, session_id: str, now: float) -> bool:
    """True iff the last trigger=="auto" continuity write for this SAME session was
    < `_CONTINUITY_DEBOUNCE_WINDOW_S` ago (measured 7 firings in 48s on one real
    compaction, TRDD-TWF7DXXR/TRDD-ANIME2SVG). Debounce applies ONLY to `auto` — a
    manual `/compact` typed twice on purpose must write both times (coordinator
    addendum to TRDD-7MGJYLY5), so a DIFFERENT session_id, or no prior record, never
    debounces."""
    path = sd / CONTINUITY_FILENAME
    mtime = _file_mtime(path)
    if not mtime or (now - mtime) >= _CONTINUITY_DEBOUNCE_WINDOW_S:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("session_id") == session_id


def _build_handoff(
    project_root: Path, plugin_root: str, trigger: str, transcript_path: str = "", cwd: str = ""
) -> str:
    """Compose the handoff. Disk/git sections + the VERBATIM recent conversation;
    every section is best-effort (fail-open)."""
    now = time.time()
    local = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(now))
    utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    version = _plugin_version(plugin_root)

    # Run the git sections from the ACTUAL repo root — which may be a SUBDIR of
    # $CLAUDE_PROJECT_DIR (issue #66). `git rev-parse` only walks up, so without this the
    # sections silently degrade to "(unavailable)" in a parent-dir-holds-the-repo layout.
    git_root = _resolve_git_root(project_root, cwd)
    head_sha = _run_git(["rev-parse", "HEAD"], git_root) or "(unavailable)"
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], git_root) or "(unavailable)"
    log = _run_git(["log", "-n", str(MAX_COMMITS), "--oneline", "--no-decorate"], git_root)
    status = _run_git(["status", "--short"], git_root)
    # TRDD scan: try project_root first (the common/historical case), fall back to the
    # already-resolved git_root for the nested-repo layout (issue #267 — #66's descend
    # reached the git sections but not this collector). Memory scopes are resolved
    # separately via lib.memory_scopes, which is not affected by this.
    trdds = _inflight_trdds(project_root, git_root)

    out: list[str] = []
    out.append("# PreCompact ground-truth handoff")
    out.append(
        "_Authoritative state captured at compaction time. The disk/git sections are "
        "read from the filesystem; the Recent-conversation section is the VERBATIM "
        "transcript turns — NEITHER is a lossy summary, so none of it is hallucinated._"
    )
    out.append("")
    out.append("## ⚠️ FAITHFULNESS INSTRUCTION — read before trusting any summary")
    out.append(
        "A context compaction occurred. The compaction SUMMARY is lossy and may "
        "promote stale or wrong hypotheses (e.g. a service's health %, "
        "\"published vs not\", whole narratives) to \"fact\". Treat EVERY technical "
        "claim in the summary as UNVERIFIED until you have checked it against this "
        "handoff, the TRDD `## STATE` blocks, and the VERBATIM Recent-conversation "
        "turns below (reliable, but RECENT-ONLY — not the whole history). Do NOT "
        "promote an uncertain hypothesis to fact. Re-ground here first, then act."
    )
    out.append("")
    out.append("## Capture metadata")
    out.append(f"- Captured (local): {local}")
    out.append(f"- Captured (UTC): {utc}")
    out.append(f"- Compaction trigger: {trigger or 'unknown'}")
    out.append(f"- Project root: {project_root}")
    out.append(f"- ai-maestro-janitor version: {version}")
    out.append("")
    out.append("## Git HEAD")
    out.append(f"- Branch: {branch}")
    out.append(f"- HEAD: {head_sha}")
    out.append("")
    out.append(f"## Recent commits (last {MAX_COMMITS}, oneline)")
    out.append("```")
    out.append(log if log else "(unavailable)")
    out.append("```")
    out.append("")
    out.append("## Working tree (`git status --short`)")
    out.append("```")
    out.append(status if status else "(clean or unavailable)")
    out.append("```")
    out.append("")
    if trdds:
        out.append(
            f"## In-flight TRDD STATE blocks ({len(trdds)}, newest first) — VERBATIM, AUTHORITATIVE"
        )
        for updated, name, title, text in trdds:
            out.append("")
            out.append(f"### design/tasks/{name} — {title}")
            out.append(f"(updated: {updated or 'unknown'})")
            block = _state_block(text)
            if block:
                out.append("")
                out.append(block)
            else:
                out.append("")
                out.append("(no `## STATE` block — read the full TRDD file top-to-bottom)")
    else:
        out.append("## In-flight TRDD STATE blocks")
        out.append("(no in-flight TRDD found on the design board)")

    # Recent conversation — the ONLY conversation-derived section. VERBATIM turns
    # (not the lossy summary), bounded + fail-open: a parser fault degrades to
    # "(recent conversation unavailable)" and never breaks the handoff.
    try:
        turns = _recent_turns(transcript_path)
    except Exception:  # noqa: BLE001 - a parser bug must never break the handoff
        turns = None
    out.append("")
    out.append(
        f"## Recent conversation (last {RECENT_TURNS} turns — VERBATIM transcript, not the summary)"
    )
    if turns:
        for role, text in turns:
            out.append("")
            out.append(f"**{role.upper()}:**")
            out.append("")
            out.append(text)
    else:
        out.append("(recent conversation unavailable)")

    # Recent memory changes — IDs/hashes ONLY (never content). Most-recently-updated
    # memory pages across scopes; a page with > _MEM_ATOMS_COLLAPSE atoms collapses to
    # just its filename. Fail-open: any fault degrades to "(unavailable)".
    try:
        mem_rows: list[tuple[str, str, str, int, list[tuple[str, str | None]]]] | None = _recent_memory_atoms(
            _memory_scope_dirs(project_root), now=now
        )
    except Exception:  # noqa: BLE001 - never break the handoff
        mem_rows = None
    out.append("")
    out.append("## Recent memory changes (atom IDs + one-line desc — most-recently-updated)")
    if mem_rows is None:
        out.append("(recent memory changes unavailable)")
    elif not mem_rows:
        out.append("(no memory pages updated recently)")
    else:
        out.extend(_format_memory_rows(mem_rows))
    out.append("")
    return "\n".join(out) + "\n"


def _emit_system_message(path: Path, *, continuity: bool = False) -> None:
    """Best-effort breadcrumb for the SAME-turn summarizer.

    PreCompact cannot inject into the compacted context, but a `systemMessage` is
    a supported common field. We NEVER set `decision` (that would block), and we
    always exit 0 — so this is advisory-only. `continuity=True` (trigger=="auto")
    points at the small machine-readable record instead of the prose handoff.
    """
    text = (
        f"[janitor] A continuity record was written to {path} (harness autocompact — "
        "no prose handoff this time, per TRDD-7MGJYLY5). It names in-flight TRDDs, "
        "live background agents, recently-active skills, and files that were open."
        if continuity
        else (
            "[janitor] An authoritative filesystem-derived handoff was written to "
            f"{path}. Prior transcript summaries may contain HALLUCINATED "
            "state — after compaction, treat every technical claim in the summary as "
            "UNVERIFIED until checked against that handoff and the TRDD STATE blocks."
        )
    )
    payload = {"systemMessage": text}
    try:
        print(json.dumps(payload))
    except (OSError, ValueError):
        pass


def _atomic_write(state, path: Path, text: str) -> None:  # noqa: ANN001 - local module type
    """Write `text` to `path` atomically, using `lib.state` when available, else an
    inline atomic-by-rename write (mirrors `state.atomic_write`) so a missing state
    lib never costs us the write."""
    if state is not None:
        state.atomic_write(path, text)
    else:
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)


def _log(state, message: str) -> None:  # noqa: ANN001 - local module type
    """Best-effort log line via `lib.state`, else stderr. Never raises — a logging
    fault must never break the hook."""
    try:
        if state is not None:
            state.log_line("pre-compact-handoff", message)
        else:
            print(f"[pre-compact-handoff] {message}", file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    # Drain stdin (PreCompact delivers a JSON payload there). We rely on
    # CLAUDE_PROJECT_DIR for project resolution, falling back to the payload `cwd`.
    raw = ""
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
    except (OSError, ValueError):
        raw = ""

    cwd_fallback = ""
    trigger = ""
    transcript_path = ""
    session_id = ""
    if raw.strip():
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                cwd_fallback = str(payload.get("cwd", "") or "")
                # `trigger` is read opportunistically — the docs don't guarantee it
                # in the payload (it's the matcher value), so we never depend on it.
                trigger = str(payload.get("trigger", "") or "")
                # transcript_path → the VERBATIM recent-conversation section.
                transcript_path = str(payload.get("transcript_path", "") or "")
                # session_id → the debounce key + the continuity record's own field.
                session_id = str(payload.get("session_id", "") or "")
        except (ValueError, TypeError):
            cwd_fallback = ""

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    project_env = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    project_dir = Path(project_env or cwd_fallback or os.getcwd())

    # Prefer the local state lib (atomic_write, state_dir, init_state, log_line) for
    # convention parity. If it can't be imported, fall back to a direct atomic write
    # so the handoff is STILL produced — the whole point is to never silently skip.
    state = None
    if plugin_root:
        sys.path.insert(0, str(Path(plugin_root) / "scripts"))
        try:
            from lib import state as _state  # noqa: E402 - local package, not PyPI

            state = _state
            if cwd_fallback and not project_env:
                # Hand cwd to the state lib as a guarded fallback (set BEFORE the first
                # project_root()/state_dir() call — those lru-cache on first use). Avoids
                # mutating the reserved $CLAUDE_PROJECT_DIR env (which would clobber it
                # session-wide for every other plugin).
                state.set_project_dir_override(cwd_fallback)
        except Exception as exc:  # noqa: BLE001
            print(f"[pre-compact-handoff] state import failed: {exc}", file=sys.stderr)
            state = None

    try:
        if state is not None:
            state.init_state()
            sd = state.state_dir()
            project_dir = state.project_root()
        else:
            sd = project_dir / ".janitor" / "state"
            sd.mkdir(parents=True, exist_ok=True)

        now = time.time()
        # ALWAYS stamp what trigger PreCompact actually saw — even when the auto record
        # below is debounced away. SessionStart reads THIS to decide manual-vs-auto,
        # never file mtimes (the ordering-hole fix, review finding on TRDD-7MGJYLY5): a
        # manual /compact (prose handoff) followed within the debounce window by a
        # debounced auto firing (no continuity write) would otherwise leave the prose
        # file the newer one, injecting 44 KB of prose on an auto path.
        try:
            _atomic_write(
                state,
                sd / _LAST_TRIGGER_FILENAME,
                json.dumps(
                    {"trigger": trigger or "unknown", "written_at": now, "session_id": session_id},
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - a stamp fault must never block compaction
            _log(state, f"last-trigger stamp failed: {exc}")
        if trigger == "auto":
            # Harness autocompact: the harness ALREADY summarizes and hands the next
            # turn a resume point (owner ruling TRDD-7MGJYLY5 — "no need of
            # summarization or handoff, the harness does this automatically"). Only a
            # small machine-readable continuity record is written, so the janitor can
            # NUDGE the resumed turn toward its in-flight work instead of duplicating
            # the harness's own summary.
            if _debounced(sd, session_id, now):
                age = now - _file_mtime(sd / CONTINUITY_FILENAME)
                _log(state, f"handoff debounced ({age:.0f}s)")
                return 0
            record = _build_continuity_record(
                project_dir, trigger, transcript_path, session_id, cwd_fallback, sd
            )
            continuity_json = json.dumps(record, ensure_ascii=False)
            continuity_path = sd / CONTINUITY_FILENAME
            _atomic_write(state, continuity_path, continuity_json)
            _log(state, f"continuity written ({len(continuity_json)} bytes, trigger=auto)")
            _emit_system_message(continuity_path, continuity=True)
        else:
            handoff = _build_handoff(project_dir, plugin_root, trigger, transcript_path, cwd_fallback)
            handoff_path = sd / HANDOFF_FILENAME
            _atomic_write(state, handoff_path, handoff)
            _log(state, f"handoff written ({len(handoff)} bytes, trigger={trigger or 'unknown'})")
            _emit_system_message(handoff_path)
    except Exception as exc:  # noqa: BLE001 - a hook fault must NEVER block compaction
        # Best-effort log, then swallow. Never raise, never set decision, never exit 2.
        try:
            if state is not None:
                state.log_line("pre-compact-handoff", f"failed: {exc}")
            else:
                print(f"[pre-compact-handoff] {exc}", file=sys.stderr)
        except Exception:  # noqa: BLE001
            print(f"[pre-compact-handoff] {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    # Bare main() — side effects live inside it so the module is import-safe (no
    # module-scope sys.exit), matching the sibling janitor hooks.
    main()
