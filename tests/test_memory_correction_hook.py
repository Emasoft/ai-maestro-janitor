"""Tests for the memory correction-protocol advisory hook (TRDD-c77dae09, rank 5).

`post-edit-memory-correction.py` is a PostToolUse hook (matcher Edit|Write). It
NEVER blocks; it surfaces a one-line advisory `additionalContext` ONLY when a
memory PAGE was edited such that a fact was rewritten in place without adding a
lesson. Contract pinned here:

  fires    → Edit replaces body text on a `*/memory/*.md` page, no new lesson.
  silent   → pure append/insert (old text preserved inside the new).
  silent   → the rewrite DID add a `[^N]` / lessons-section (protocol followed).
  silent   → the path is not a memory page (fast path).
  silent   → user-mem/ / MEMORY.md / .memgrep/ (excluded memory-area paths).
  silent   → Write (no prior content in payload → append-vs-replace unknowable).
  no-op    → garbage stdin (must never crash the turn).

Pure regex on the tool payload — no memgrep, no filesystem state — so every case
just feeds JSON on stdin and inspects stdout/stderr/exit-code. The hook always
exits 0; `additionalContext` presence is the fire/silent signal.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "hooks" / "post-edit-memory-correction.py"
)

# A representative memory-page path (LOCAL scope shape); the hook only inspects
# the string, no file need exist.
_MEM_PAGE = "/home/u/.claude/projects/-proj/memory/reference_widget_retry.md"


def _run(payload: dict, *, env_extra: dict | None = None, raw_stdin: str | None = None):
    """Run the hook with `payload` (or `raw_stdin`) on stdin; return CompletedProcess."""
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    stdin = raw_stdin if raw_stdin is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin, capture_output=True, text=True, env=env, timeout=30, check=False,
    )


def _fired(res: subprocess.CompletedProcess) -> bool:
    """True iff the hook surfaced the advisory (additionalContext present)."""
    assert res.returncode == 0, f"hook must always exit 0; stderr:\n{res.stderr}"
    if not res.stdout.strip():
        return False
    try:
        out = json.loads(res.stdout)
    except json.JSONDecodeError:
        return False
    ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    return "[memory-correction]" in ctx


def _edit(file_path: str, old: str, new: str) -> dict:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path, "old_string": old, "new_string": new},
    }


class TestFiresOnReplaceWithoutLesson:
    def test_replace_body_fact_without_lesson_fires(self):
        """A fact rewritten in place on a memory page, no lesson added → advisory fires."""
        res = _run(_edit(
            _MEM_PAGE,
            old="The widget retries 5 times then fails.",
            new="The widget retries 3 times then fails.",
        ))
        assert _fired(res)
        assert "2-step" in res.stdout
        assert "[memory-correction]" in res.stderr  # user-visible line too


class TestSilentCases:
    def test_pure_append_is_silent(self):
        """An append (old text preserved verbatim inside the new) is not a rewrite → silent."""
        old = "The widget retries 3 times then fails."
        new = old + "\n\nAlso: it logs each attempt at debug level."
        res = _run(_edit(_MEM_PAGE, old=old, new=new))
        assert not _fired(res)

    def test_pure_insertion_empty_old_is_silent(self):
        """An empty old_string (pure insertion at a point) is never a replacement → silent."""
        res = _run(_edit(_MEM_PAGE, old="", new="A brand new sentence added here."))
        assert not _fired(res)

    def test_rewrite_that_adds_footnote_is_silent(self):
        """A fact rewrite that ALSO adds a `[^N]` reference followed the protocol → silent."""
        res = _run(_edit(
            _MEM_PAGE,
            old="The widget retries 5 times then fails.",
            new="The widget retries 3 times then fails.[^3]",
        ))
        assert not _fired(res)

    def test_rewrite_that_adds_lessons_section_is_silent(self):
        """A rewrite that introduces the `## Notes and lessons learned` header → silent."""
        res = _run(_edit(
            _MEM_PAGE,
            old="The widget retries 5 times.",
            new="The widget retries 3 times.\n\n## Notes and lessons learned\nlesson body.",
        ))
        assert not _fired(res)

    def test_non_memory_path_is_silent(self):
        """An Edit to a non-memory file never fires (fast path)."""
        res = _run(_edit(
            "/home/u/project/src/main.py",
            old="retries = 5", new="retries = 3",
        ))
        assert not _fired(res)
        assert res.stdout.strip() == ""

    def test_in_memory_substring_path_is_not_a_memory_page(self):
        """A file like `in-memory-cache.md` (no `memory/` segment) is not a memory page."""
        res = _run(_edit(
            "/home/u/project/docs/in-memory-cache.md",
            old="cap is 5", new="cap is 3",
        ))
        assert not _fired(res)

    def test_user_mem_path_is_excluded(self):
        """A page under the private user-mem/ store is excluded (privacy)."""
        res = _run(_edit(
            "/home/u/.claude/projects/-proj/memory/user-mem/000007.md",
            old="secret was 5", new="secret was 3",
        ))
        assert not _fired(res)

    def test_memory_md_index_is_excluded(self):
        """The MEMORY.md human index is not a content page → excluded."""
        res = _run(_edit(
            "/home/u/.claude/projects/-proj/memory/MEMORY.md",
            old="- [A](a.md) — old hook.", new="- [A](a.md) — new hook.",
        ))
        assert not _fired(res)

    def test_memgrep_sidecar_is_excluded(self):
        """A file under the `.memgrep/` sidecar dir is excluded."""
        res = _run(_edit(
            "/home/u/.claude/projects/-proj/memory/.memgrep/notes.txt.md",
            old="x", new="y",
        ))
        assert not _fired(res)

    def test_write_is_silent(self):
        """A Write carries no prior content → append-vs-replace unknowable → silent."""
        res = _run({
            "tool_name": "Write",
            "tool_input": {
                "file_path": _MEM_PAGE,
                "content": "Whole new page body with the corrected fact. retries 3.",
            },
        })
        assert not _fired(res)

    def test_opt_out_disables_the_hook(self):
        """Setting the opt-out env false suppresses the advisory even on a real correction."""
        res = _run(
            _edit(_MEM_PAGE, old="retries 5 times.", new="retries 3 times."),
            env_extra={"CLAUDE_PLUGIN_OPTION_MEMORY_CORRECTION_ADVISORY": "false"},
        )
        assert not _fired(res)
        assert res.stdout.strip() == ""


class TestRobustness:
    def test_garbage_stdin_is_a_noop(self):
        """Non-JSON stdin must exit 0 with no output (never crash the turn)."""
        res = _run({}, raw_stdin="this is not json {{{")
        assert res.returncode == 0
        assert res.stdout.strip() == ""

    def test_empty_stdin_is_a_noop(self):
        """Empty stdin exits 0 with no output."""
        res = _run({}, raw_stdin="")
        assert res.returncode == 0
        assert res.stdout.strip() == ""

    def test_unrelated_tool_is_a_noop(self):
        """A non-Edit/Write tool name is ignored."""
        res = _run({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        assert not _fired(res)
        assert res.stdout.strip() == ""

    def test_nested_memory_subdir_page_is_covered(self):
        """A note nested under `memory/<subdir>/note.md` is still a memory page."""
        res = _run(_edit(
            "/home/u/.claude/projects/-proj/memory/topics/retry.md",
            old="retries 5.", new="retries 3.",
        ))
        assert _fired(res)
