#!/usr/bin/env python3
"""`pre-tool-wikimem-write-path.py` — memgrep is the only write path (TRDD-VOWAUVE5, USER #6).

The four things worth pinning are the ones that make this hook safe to ship at all: it denies
the pages it governs, it does NOT deny the look-alikes, it fails OPEN on every uncertainty, and
it can be switched off. A memory hook that blocks writes when confused makes the corpus
un-editable at exactly the moment someone is trying to repair it, so fail-open is the property
under test, not an implementation detail.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "scripts" / "hooks" / "pre-tool-wikimem-write-path.py"


def _run(payload: object, env_extra: dict[str, str] | None = None) -> dict:
    import os

    env = {**os.environ, **(env_extra or {})}
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload) if not isinstance(payload, str) else payload,
        capture_output=True, text=True, timeout=60, env=env, check=False,
    )
    assert proc.returncode == 0, f"a hook must never exit non-zero: {proc.stderr}"
    out = (proc.stdout or "").strip()
    return json.loads(out) if out else {}


def _denies(result: dict) -> bool:
    return result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


@pytest.mark.parametrize("path", [
    ".claude/project/memory/some-page.md",
    "/Users/x/.claude/projects/slug/memory/a-page.md",
    "/Users/x/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/p.md",
])
def test_a_wikimem_page_is_denied(path: str) -> None:
    """The whole point: the parser SYNTHESISES the element, so a hand-written page bypasses the
    structural guarantee by construction — no after-the-fact lint can restore it."""
    r = _run({"tool_name": "Edit", "tool_input": {"file_path": path}})
    assert _denies(r), f"{path} is a wikimem page and must be denied"
    assert "memgrep" in r["hookSpecificOutput"]["permissionDecisionReason"], (
        "a deny that does not name the verb to use instead is a dead end, not a guardrail"
    )


@pytest.mark.parametrize("path", [
    ".claude/project/memory/MEMORY.md",            # the harness index, not a wiki page
    ".claude/project/memory/memory-index.md",
    ".claude/project/memory/.memgrep/index.db.md",  # the sidecar
    ".claude/project/memory/.maint-staging/wip.md",  # an IN-FLIGHT memgrep transaction
    "scripts/daemon.py",
    "design/tasks/TRDD-something.md",
    "notes/memory/../elsewhere.py",
])
def test_look_alikes_are_not_denied(path: str) -> None:
    """Over-reach is the failure mode that gets a guard deleted.

    `.maint-staging/` matters most: memgrep writes its own staging + journal through this path
    while a chore is in flight, so denying it would deadlock the very tool the hook funnels
    writes INTO.
    """
    r = _run({"tool_name": "Edit", "tool_input": {"file_path": path}})
    assert not _denies(r), f"{path} must NOT be denied"


def test_non_write_tools_are_untouched() -> None:
    r = _run({"tool_name": "Bash", "tool_input": {"command": "cat memory/x.md"}})
    assert not _denies(r), "the hook governs writes, not reads or shell"


@pytest.mark.parametrize("payload", ["not json at all", "", "[]", '{"tool_name":"Edit"}'])
def test_fails_open_on_anything_it_cannot_read(payload: str) -> None:
    """FAIL-OPEN is the safety property, so it is tested with garbage rather than assumed.

    An un-writable memory is a worse failure than an unlinted page: it strands the corpus when
    someone is trying to fix it.
    """
    assert not _denies(_run(payload)), f"must allow on unparseable input: {payload!r}"


def test_the_knob_turns_it_off() -> None:
    """A guard with no off switch gets worked around instead of fixed."""
    r = _run(
        {"tool_name": "Edit", "tool_input": {"file_path": ".claude/project/memory/p.md"}},
        {"CLAUDE_PLUGIN_OPTION_WIKIMEM_WRITE_PATH_ENFORCED": "0"},
    )
    assert not _denies(r), "the documented knob must disable the deny"


def test_it_is_registered_in_hooks_json() -> None:
    """A hook that exists but is not wired runs never — and looks shipped."""
    hooks = json.loads((Path(__file__).resolve().parents[1] / "hooks" / "hooks.json").read_text())
    wired = json.dumps(hooks)
    assert "pre-tool-wikimem-write-path.py" in wired, "hook not registered in hooks.json"
