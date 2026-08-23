"""Which skills were ACTIVE in a session, and their full text — TRDD-79LXF6PJ.

WHY. After a `/clear` the janitor injects the llm-ext session summary as the replacement context.
That summary describes a session in which skills were loaded, so it REFERENCES them — and a
reference to a skill whose text is gone resolves to nothing. The owner's requirement (2026-08-23):
re-inject the active skills IN FULL, immediately BEFORE the summary.

WHAT "ACTIVE" MEANS HERE: a skill the session actually INVOKED, not every skill installed on the
machine. The broad reading would inject tens of thousands of tokens the session never touched,
which defeats the point of clearing.

THE TWO REAL SHAPES, measured against a live transcript rather than assumed. A first draft looked
only for `{"name":"Skill"}` tool calls and found ZERO in a session that had demonstrably run two
skills — because slash-invoked skills never produce a Skill tool call. They arrive as
`<command-name>/plugin:skill</command-name>` in a user message. Both shapes are matched:

    <command-name>/ai-maestro-janitor:janitor-arm</command-name>   <- slash invocation
    "name":"Skill" … "skill":"tldr-code"                            <- Skill tool call

RESOLUTION IS THE FILTER. `/clear`, `/reload-plugins` and friends appear in exactly the same
`<command-name>` shape as a real skill, and no denylist of built-ins would stay current. So a name
is kept ONLY if it resolves to a `SKILL.md` on disk. A built-in resolves to nothing and drops out
by construction — no list to maintain, and a new built-in cannot silently start being injected.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# `<command-name>/name</command-name>` — the leading slash is optional in the capture so a future
# harness that drops it still matches.
_COMMAND_RE = re.compile(r"<command-name>\s*/?([A-Za-z0-9_:\-]+)\s*</command-name>")
# The Skill tool's argument, tolerant of whitespace variations in the serialized JSON.
_SKILL_TOOL_RE = re.compile(r'"skill"\s*:\s*"([A-Za-z0-9_:\-]+)"')

_MAX_SKILL_BYTES = 200_000  # a runaway SKILL.md must not become the whole injected context


def invoked_skills(transcript: str | Path) -> list[str]:
    """Skill names invoked in this transcript, in FIRST-INVOCATION order, deduped.

    Order matters: the summary tends to reference skills in the order the session met them, and a
    reader following it top-down should meet them the same way. Unreadable transcript => [], never
    a raise: a missing skill list must degrade the injection, never block the clear.
    """
    try:
        text = Path(transcript).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    seen: dict[str, None] = {}
    for m in _COMMAND_RE.finditer(text):
        seen.setdefault(m.group(1), None)
    for m in _SKILL_TOOL_RE.finditer(text):
        seen.setdefault(m.group(1), None)
    return list(seen)


def _skill_roots() -> list[Path]:
    """Every directory tree that can contain a `<name>/SKILL.md`, cheapest first."""
    home = Path(os.path.expanduser("~"))
    roots = [home / ".claude" / "skills"]
    project = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if project:
        roots.insert(0, Path(project) / ".claude" / "skills")
    cache = home / ".claude" / "plugins" / "cache"
    if cache.is_dir():
        roots.append(cache)
    return [r for r in roots if r.is_dir()]


def resolve_skill(name: str) -> Path | None:
    """Absolute path to a skill's `SKILL.md`, or None when the name is not a skill.

    A `plugin:skill` name is matched on its SKILL half — the plugin half is the marketplace
    directory, which varies by install and version. Returning None is the normal, expected answer
    for a built-in slash command; see the module docstring on why that IS the filter.
    """
    leaf = name.split(":")[-1]
    if not leaf or leaf in {".", ".."} or "/" in leaf:
        return None  # never let a transcript-derived string escape the roots
    for root in _skill_roots():
        direct = root / leaf / "SKILL.md"
        if direct.is_file():
            return direct
        # Plugin cache: <marketplace>/<plugin>/<version>/skills/<leaf>/SKILL.md. Newest version
        # last in glob order is not guaranteed, so prefer the most recently modified match.
        matches = sorted(
            root.glob(f"*/*/*/skills/{leaf}/SKILL.md"),
            key=lambda p: p.stat().st_mtime if p.is_file() else 0.0,
            reverse=True,
        )
        if matches:
            return matches[0]
    return None


def render(transcript: str | Path) -> str:
    """The full text of every skill this session invoked, or "" when there were none.

    "" is a normal outcome (a session that used no skills), and the caller must treat it as
    "nothing to prepend" rather than as a failure — an empty skill list is not a reason to
    withhold a summary.
    """
    parts: list[str] = []
    for name in invoked_skills(transcript):
        path = resolve_skill(name)
        if path is None:
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace")[:_MAX_SKILL_BYTES]
        except OSError:
            continue
        if body.strip():
            parts.append(f"<!-- skill: {name} ({path}) -->\n{body.rstrip()}")
    if not parts:
        return ""
    return (
        "# Active skills, re-injected in full\n\n"
        "These were loaded in the session the summary below describes, so the summary refers to "
        "them. They are reproduced here because a `/clear` discarded them.\n\n"
        + "\n\n---\n\n".join(parts)
    )


def _main() -> int:
    """`active_skills.py <transcript>` — prints the rendered block. For manual inspection."""
    import sys

    if len(sys.argv) != 2:
        print("usage: active_skills.py <transcript.jsonl>", file=sys.stderr)
        return 2
    names = invoked_skills(sys.argv[1])
    print(json.dumps({"invoked": names, "resolved": [n for n in names if resolve_skill(n)]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
