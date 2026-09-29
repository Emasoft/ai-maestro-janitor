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
    # The hook self-filters tool names in main(), so its matcher must cover BOTH the edit
    # tools AND Bash — the Bash branch is dead code if the matcher omits Bash.
    for entry in hooks["hooks"]["PreToolUse"]:
        if "pre-tool-wikimem-write-path.py" in json.dumps(entry):
            matcher = entry.get("matcher", "")
            assert "Bash" in matcher, "wikimem write-path hook matcher must include Bash"


# ---------------------------------------------------------------------------
# TRDD-XI10BA5D step D — the Bash branch (shell writes to wikimem pages).
# Every path below is a STRING fed through the hook's stdin; no test touches a
# real memory dir.


def _bash(cmd: str) -> dict:
    return _run({"tool_name": "Bash", "tool_input": {"command": cmd}})


def _assert_deny(result: dict, cmd: str) -> None:
    assert _denies(result), f"must deny shell write: {cmd}"
    assert "memgrep" in result["hookSpecificOutput"]["permissionDecisionReason"], (
        f"deny reason must name the memgrep path back: {cmd}"
    )


def _assert_allow(result: dict, cmd: str) -> None:
    assert not _denies(result), f"must NOT deny: {cmd}"


@pytest.mark.parametrize("cmd", [
    "echo x > .claude/project/memory/p.md",
    'echo x > ".claude/project/memory/p.md"',  # A3: quoted target classifies too
])
def test_redirect_into_memory_page_denied(cmd: str) -> None:
    _assert_deny(_bash(cmd), cmd)


@pytest.mark.parametrize("op", [">>", "2>", "&>", ">|"])
def test_redirect_operators_denied(op: str) -> None:
    cmd = f"echo x {op} .claude/project/memory/p.md"
    _assert_deny(_bash(cmd), cmd)


@pytest.mark.parametrize("cmd", [
    "cmd 2>&1",
    "cmd >&1",
    "cmd > >(tee /tmp/x.log)",
])
def test_dup_targets_and_process_substitution_not_denied(cmd: str) -> None:
    """A dup target (`2>&1`) is not a path; `>(cmd)` is a command, not a file."""
    _assert_allow(_bash(cmd), cmd)


@pytest.mark.parametrize("cmd,denied", [
    ("sed -i s/a/b/ memory/p.md", True),
    ("sed -i '' s/a/b/ memory/p.md", True),  # BSD form
    ("sed s/a/b/ memory/p.md", False),       # no -i: a read/transform, not in-place
    ("perl -pi -e s/a/b/ memory/p.md", True),
    ("grep -i x memory/p.md", False),        # A4 boundary: grep untouched
])
def test_inplace_editors(cmd: str, denied: bool) -> None:
    r = _bash(cmd)
    if denied:
        _assert_deny(r, cmd)
    else:
        _assert_allow(r, cmd)


@pytest.mark.parametrize("cmd,denied", [
    ("tee memory/p.md", True),
    ("echo x | tee -a memory/p.md", True),
    ("grep foo memory/p.md | tee /tmp/out.md", False),  # A4: read memory, write tmp
])
def test_tee_operand_rule(cmd: str, denied: bool) -> None:
    r = _bash(cmd)
    if denied:
        _assert_deny(r, cmd)
    else:
        _assert_allow(r, cmd)


@pytest.mark.parametrize("cmd,denied", [
    ("cp /tmp/src memory/p.md", True),
    ("cp /tmp/draft.md memory/", True),   # A1: directory destination inside memory tree
    ("cp memory/p.md /tmp/out", False),   # copy FROM a page is allowed
])
def test_copy_rules(cmd: str, denied: bool) -> None:
    r = _bash(cmd)
    if denied:
        _assert_deny(r, cmd)
    else:
        _assert_allow(r, cmd)


@pytest.mark.parametrize("cmd,denied", [
    ("mv anywhere memory/p.md", True),
    ("mv memory/p.md /tmp/", True),       # mv FROM a page is deletion-class
    ("mv memory/p.md .trashcan/20260929/", False),  # safe-delete staging
    ("uv run scripts/safe_delete.py memory/p.md", False),  # the sanctioned script
])
def test_move_and_safe_delete_rules(cmd: str, denied: bool) -> None:
    r = _bash(cmd)
    if denied:
        _assert_deny(r, cmd)
    else:
        _assert_allow(r, cmd)


@pytest.mark.parametrize("cmd", [
    "rm memory/p.md",
    "unlink memory/p.md",
    "rm -r memory/",  # A1: the catastrophic tree shape
])
def test_deletion_rules_denied(cmd: str) -> None:
    _assert_deny(_bash(cmd), cmd)


def test_touch_denied_with_mtime_cost_note() -> None:
    """A7: creation goes through memgrep; the accepted false-positive cost is an mtime-only
    touch of an EXISTING page — recorded in the hook's touch comment."""
    _assert_deny(_bash("touch memory/p.md"), "touch memory/p.md")


@pytest.mark.parametrize("cmd", [
    "git checkout -- memory/p.md",
    "git stash pop",
    "git reset --hard HEAD",
    "git pull",
    "git -C elsewhere pull",  # A2: subcommand = first non-flag token after git
])
def test_git_restores_allowed_wholesale(cmd: str) -> None:
    _assert_allow(_bash(cmd), cmd)


@pytest.mark.parametrize("cmd,denied", [
    ("git checkout x && rm memory/p.md", True),   # the rm segment rides no exemption
    ("echo x > memory/p.md && memgrep lint", True),  # the memgrep segment is irrelevant
    ("rm /tmp/x && git stash pop", False),
])
def test_compound_commands_deny_per_segment(cmd: str, denied: bool) -> None:
    """A2: exemptions apply PER SEGMENT, not per command."""
    r = _bash(cmd)
    if denied:
        _assert_deny(r, cmd)
    else:
        _assert_allow(r, cmd)


@pytest.mark.parametrize("cmd", [
    "memgrep lint memory/p.md",
    "memgrep add-atom --page memory/p.md <<EOF\nbody\nEOF",  # stdin INTO memgrep is normal
])
def test_memgrep_invocations_allowed(cmd: str) -> None:
    _assert_allow(_bash(cmd), cmd)


def test_hand_emulated_staging_copy_denied() -> None:
    """FINDING 8: .maint-staging/ is memgrep's own mid-chore staging — a HAND copy out of it
    emulates a commit around the txn core. The source path carries the exclusion, but the
    destination is a real page, and the copy command is not memgrep, so it denies."""
    r = _bash("cp .maint-staging/t/foo.md memory/foo.md")
    _assert_deny(r, "cp .maint-staging/t/foo.md memory/foo.md")


@pytest.mark.parametrize("cmd", [
    "cat memory/p.md",
])
def test_reads_not_denied(cmd: str) -> None:
    _assert_allow(_bash(cmd), cmd)


def test_bash_garbage_stdin_fails_open() -> None:
    """The Bash branch inherits fail-open: garbage stdin still exits 0 with no deny."""
    assert not _denies(_run('{"tool_name":"Bash","tool_input":'))


def test_the_knob_disables_bash_deny_too() -> None:
    r = _bash("echo x > memory/p.md")
    # Run again with the knob off via a fresh payload — same _run helper, knob env.
    r_off = _run(
        {"tool_name": "Bash", "tool_input": {"command": "echo x > memory/p.md"}},
        {"CLAUDE_PLUGIN_OPTION_WIKIMEM_WRITE_PATH_ENFORCED": "0"},
    )
    assert _denies(r), "sanity: the Bash deny fires when enabled"
    assert not _denies(r_off), "the documented knob must disable the Bash deny too"


def test_mirror_restore_copy_allowed() -> None:
    """A6: the manual post-loss restore copies FROM the `ai-maestro-janitor-memory` backup
    mirror INTO a memory tree. The routine restore is `sync_user_memory_mirror()` in
    scripts/lib/memory_scopes.py (script-side file ops, invisible to Bash) — this Bash shape
    is its only live manual path, so it must pass."""
    cmd = "cp ~/.claude/ai-maestro-janitor-memory/some-page.md ~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/some-page.md"
    _assert_allow(_bash(cmd), cmd)


def test_mirror_lookalike_dir_not_exempt() -> None:
    """The A6 exemption is a SEGMENT match, not a substring: a look-alike dir name must not
    smuggle a write into a real memory tree past every deny (adversarial review 2026-09-29)."""
    cmd = "cp /tmp/x-ai-maestro-janitor-memory/evil.md .claude/project/memory/evil.md"
    _assert_deny(_bash(cmd), cmd)
