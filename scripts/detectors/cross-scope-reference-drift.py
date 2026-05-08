#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.10"
# ///
"""Cross-scope reference drift — Python port of cross-scope-reference-drift.sh.

Enforces SCOPE PARITY between a source (agent/skill/command/CLAUDE.md)
and the targets it references. Per the project-wide rule:

  'If a skill or agent under <proj>/.claude/{skills,agents}/ references
   a skill or agent under <proj>/.claude/{skills,agents}/, then BOTH
   must be either git-tracked (project scope) OR gitignored (local
   scope). They must travel together as one bundle.'

Two classes of drift fall out of this rule, both flagged here:

  1. SILENT-CLONE-BREAK — tracked source → gitignored or ambiguous
     target. The source ships to the repo on push; the target doesn't.
     Teammates' clones see the source reference a target that isn't
     there, the slash-command silently no-ops, and the bug is invisible
     in code review.

  2. SCOPE-MISMATCH — gitignored source → tracked target. The
     personal/local source has a hidden dependency on a team-shared
     target. Locally everything works; if the team later renames or
     removes the target, the local source silently breaks.

Out of scope (good follow-ups):
  * User-scope references (~/.claude/skills/<name>/) — needs a way to
    distinguish 'user skill we'd lose on clone' from 'plugin skill the
    team also has installed'.
  * Plain-prose mentions ('see the foo skill') — too lossy.
"""

from __future__ import annotations

import re
import subprocess
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import git_utils  # noqa: E402
import state  # noqa: E402


# Body refs ---------------------------------------------------------------

# `/<name>` slash-commands. Length ≥3 (avoids false matches on `/a` and
# `/x` in URLs/paths). Tolerates leading garbage by capturing only the
# `/<name>` substring.
_SLASH_RE = re.compile(r"/([a-z][a-z0-9-]{2,})")
# `Skill('<name>')` / `Skill("<name>")` explicit invocations.
_SKILL_BODY_RE = re.compile(r'Skill\(["\']([a-zA-Z][a-zA-Z0-9_-]+)["\']\)')

# Frontmatter refs --------------------------------------------------------

_FM_DELIM_RE = re.compile(r"^---\s*$")
_AGENT_LINE_RE = re.compile(r"^agent:\s+(.+?)\s*(?:#.*)?$")
_SKILL_FM_RE = re.compile(r"Skill\(([a-zA-Z][a-zA-Z0-9_-]+)")
_SKILLS_LINE_RE = re.compile(r"^skills:\s*(.*?)\s*(?:#.*)?$")
_BLOCK_ITEM_RE = re.compile(r"^\s+-\s+(.+?)\s*(?:#.*)?$")
_IDENT_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _extract_frontmatter_refs(file: Path) -> set[str]:
    """Pull refs from the YAML frontmatter (between the first `---` pair).

    Three named-by-value fields are scanned, all documented in the
    Claude Code skills + sub-agents schema tables:

      1. `agent: <name>`              → resolves to `.claude/agents/<name>.md`
      2. `Skill(<name>...)` patterns  → resolves to `.claude/skills/<name>/`
      3. `skills: [<a>, <b>]` or
         indented block list          → resolves to `.claude/skills/<name>/`

    YAML parsing in pure Python without a YAML lib is fragile — same
    constraint as the bash awk port. We handle the common documented
    forms (single-line scalar, inline flow list, indented block list).
    Less common forms (multi-line strings, anchors, &refs) silently
    produce no matches — better a false negative than a false positive.
    """
    refs: set[str] = set()
    in_fm = False
    delim_count = 0
    in_skills_block = False

    try:
        content = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return refs

    for raw in content.splitlines():
        if _FM_DELIM_RE.match(raw):
            delim_count += 1
            if delim_count == 1:
                in_fm = True
                continue
            if delim_count >= 2:
                break
        if not in_fm:
            continue

        # Strip trailing YAML comment (only outside of quoted strings —
        # we don't try to be perfect, just match the bash awk port).
        line = re.sub(r"\s*#.*$", "", raw)

        # Pattern 1: agent: <name>
        m = _AGENT_LINE_RE.match(line)
        if m:
            v = _strip_quotes(m.group(1)).replace(" ", "")
            if _IDENT_RE.match(v):
                refs.add(v)

        # Pattern 2: any Skill(<name>...) on the line — multiple per line OK
        for m in _SKILL_FM_RE.finditer(line):
            refs.add(m.group(1))

        # Pattern 3a/3b: skills: ...
        m = _SKILLS_LINE_RE.match(line)
        if m:
            rest = m.group(1)
            if rest.startswith("["):
                stripped = re.sub(r"[\[\]\"' ]", "", rest)
                for tok in stripped.split(","):
                    if _IDENT_RE.match(tok):
                        refs.add(tok)
                in_skills_block = False
            elif rest and rest[:1].isalpha():
                stripped = re.sub(r"[\"']", "", rest)
                for tok in re.split(r"\s+", stripped):
                    if _IDENT_RE.match(tok):
                        refs.add(tok)
                in_skills_block = False
            else:
                # No same-line value → expect indented block list below.
                in_skills_block = True
            continue

        if in_skills_block:
            m = _BLOCK_ITEM_RE.match(line)
            if m:
                v = _strip_quotes(m.group(1).strip())
                if _IDENT_RE.match(v):
                    refs.add(v)
            elif line.strip() == "":
                # blank line — keep block alive
                pass
            elif not line.startswith((" ", "\t")):
                # Non-indented non-empty line ends the list.
                in_skills_block = False

    return refs


def _extract_body_refs(file: Path) -> set[str]:
    """Pull slash-command and Skill() references from a markdown file's BODY."""
    refs: set[str] = set()
    try:
        content = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return refs
    for m in _SLASH_RE.finditer(content):
        refs.add(m.group(1))
    for m in _SKILL_BODY_RE.finditer(content):
        refs.add(m.group(1))
    return refs


def _extract_refs(file: Path) -> set[str]:
    return _extract_frontmatter_refs(file) | _extract_body_refs(file)


def _resolve_ref(name: str, root: Path) -> str | None:
    """Resolve a reference to a project-relative path. None on miss."""
    candidates = [
        f".claude/skills/{name}/SKILL.md",
        f".claude/skills/{name}/Skill.md",
        f".claude/agents/{name}.md",
        f".claude/commands/{name}.md",
    ]
    for cand in candidates:
        if (root / cand).is_file():
            return cand
    return None


def _collect_sources(root: Path) -> list[Path]:
    sources: list[Path] = []
    agents = root / ".claude" / "agents"
    if agents.is_dir():
        sources.extend(p for p in agents.rglob("*.md") if p.is_file())
    skills = root / ".claude" / "skills"
    if skills.is_dir():
        for p in skills.rglob("SKILL.md"):
            if p.is_file():
                sources.append(p)
        for p in skills.rglob("Skill.md"):
            if p.is_file():
                sources.append(p)
    cmds = root / ".claude" / "commands"
    if cmds.is_dir():
        sources.extend(p for p in cmds.rglob("*.md") if p.is_file())
    for top in ("CLAUDE.md", ".claude/CLAUDE.md"):
        p = root / top
        if p.is_file():
            sources.append(p)
    return sorted(sources)


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "cross-scope-reference-drift-seen.txt"
    root = state.project_root()

    if subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(root),
        capture_output=True, text=True, check=False,
    ).returncode != 0:
        state.log_line("cross-scope-reference-drift", "not a git repo — skipping")
        return 0

    sources = _collect_sources(root)
    if not sources:
        return 0

    for src in sources:
        rel_src = str(src.relative_to(root))
        src_status = git_utils.scope_tracking_status(rel_src)
        if src_status not in (git_utils.TRACKED, git_utils.GITIGNORED):
            # Source ambiguity is handled by subagent-scope-drift /
            # claude-md-scope-drift. Once resolved to tracked or gitignored,
            # this detector picks up any resulting parity violation on the
            # next fire.
            continue

        refs = _extract_refs(src)
        if not refs:
            continue

        for ref in sorted(refs):
            target_rel = _resolve_ref(ref, root)
            if target_rel is None:
                continue

            target_status = git_utils.scope_tracking_status(target_rel)
            pair = f"{src_status}/{target_status}"

            drift_class = ""
            if pair in ("tracked/tracked", "gitignored/gitignored"):
                continue
            if pair in ("tracked/gitignored", "tracked/ambiguous"):
                drift_class = "silent-clone-break"
            elif pair == "gitignored/tracked":
                drift_class = "scope-mismatch"
            else:
                # ambiguous target with gitignored source, or unexpected
                # combination — let the dedicated scope-drift detector
                # surface the underlying ambiguity. Not our concern here.
                continue

            safe_src = state.sanitize_for_drift_line(rel_src)
            safe_target = state.sanitize_for_drift_line(target_rel)

            if drift_class == "silent-clone-break":
                drift_msg = (
                    f"[cross-scope-reference-drift] '{safe_src}' is git-tracked but references "
                    f"'/{ref}' → '{safe_target}' ({target_status}, not in repo). On clone or push the "
                    f"source ships without its target — the reference will dangle in every teammate's "
                    f"checkout and in CI. Fix: 'git add {safe_target}' to ship the target with the team, "
                    f"OR 'git rm --cached {safe_src}' to keep both files private."
                )
            else:  # scope-mismatch
                drift_msg = (
                    f"[cross-scope-reference-drift] '{safe_src}' is gitignored (local scope) but "
                    f"references '/{ref}' → '{safe_target}' (git-tracked, project scope). The reference "
                    f"works locally but creates a hidden dependency: if the team renames or removes the "
                    f"target, your local source silently breaks. Either 'git add {safe_src}' to elevate "
                    f"the source to project scope, OR copy the target into a local-scope sibling and "
                    f"reference that copy instead so the dependency is self-contained."
                )

            fp = zlib.crc32(f"{rel_src}\t{target_rel}\t{pair}".encode("utf-8")) & 0xFFFFFFFF
            line = dedupe.emit_once(seen, f"{drift_class}@{fp}", drift_msg)
            if line is not None:
                print(line)

    state.rotate_log_if_big("cross-scope-reference-drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
