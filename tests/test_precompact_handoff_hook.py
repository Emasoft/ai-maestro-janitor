"""Tests for the PreCompact ground-truth handoff hook (TRDD-7DVNHLOP).

`scripts/hooks/pre-compact-handoff.py` writes a FILESYSTEM-DERIVED handoff (git
HEAD + recent commits, working tree, in-flight TRDD STATE blocks) into
`<project>/.janitor/state/precompact-handoff.md` on every compaction, so the
post-compaction turn re-grounds in VERIFIED state instead of a lossy summary.

We test the pure-ish helpers directly plus a REAL end-to-end subprocess run
against a real temp git repo + a fixture TRDD — no mocks. We also test the
minimal integration in post-compact-resume.py (the handoff pointer prefix).

Per-test isolation: $CLAUDE_PROJECT_DIR points at tmp_path so the user's real
state is never touched; the `state` module is reloaded so its lru_cached
project-root resolution picks up the env.
"""

from __future__ import annotations

import importlib.util as _u
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

_HOOK_PATH = _PROJECT_ROOT / "scripts" / "hooks" / "pre-compact-handoff.py"
_POST_HOOK_PATH = _PROJECT_ROOT / "scripts" / "hooks" / "post-compact-resume.py"


def _import(path: Path, name: str):
    """Import a hook script as a module (safe — no side effects at import)."""
    spec = _u.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hook():
    return _import(_HOOK_PATH, "pre_compact_handoff_under_test")


def _post_hook():
    return _import(_POST_HOOK_PATH, "post_compact_resume_under_test_for_handoff")


def _write_trdd(
    tasks_dir: Path,
    uid8: str,
    column: str,
    updated: str,
    title: str,
    *,
    state_block: str | None = None,
    slug: str = "x",
) -> None:
    """Write a schema-valid v2 TRDD with a canonical filename + optional STATE block."""
    tasks_dir.mkdir(parents=True, exist_ok=True)
    fn = f"TRDD-20260602_044555+0200-{uid8}-{slug}.md"
    body = "body text\n"
    if state_block is not None:
        body = (
            "## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-06-02\n\n"
            f"{state_block}\n\n## Next section\nmore body\n"
        )
    (tasks_dir / fn).write_text(
        "---\n"
        f"trdd-id: {uid8}\n"
        f"title: {title}\n"
        f"column: {column}\n"
        "created: 2026-06-02T04:45:55+0200\n"
        f"updated: {updated}\n"
        "---\n\n"
        f"# TRDD-{uid8} — {title}\n\n"
        f"{body}",
        encoding="utf-8",
    )


def _init_git_repo(root: Path) -> None:
    """Create a real git repo with one commit so HEAD/log/status are populated."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    run = lambda *a: subprocess.run(  # noqa: E731 - terse test helper
        ["git", *a], cwd=str(root), env=env, capture_output=True, text=True, check=True
    )
    run("init", "-q")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    run("add", "README.md")
    run("commit", "-q", "-m", "initial commit")


# ---------- frontmatter / in-flight helpers --------------------------------

def test_is_inflight_v2_column() -> None:
    """A v2 `column:` in the in-flight set is in-flight; parked/terminal is not."""
    hook = _hook()
    assert hook._is_inflight("column: dev\nupdated: x\n")
    assert hook._is_inflight("column: testing\n")
    assert not hook._is_inflight("column: backburner\n")
    assert not hook._is_inflight("column: complete\n")
    assert not hook._is_inflight("column: published\n")


def test_is_inflight_v1_status_fallback() -> None:
    """Legacy v1 `status: in-progress` is treated as in-flight when no column present."""
    hook = _hook()
    assert hook._is_inflight("status: in-progress\n")
    assert not hook._is_inflight("status: completed\n")
    assert not hook._is_inflight("status: not-started\n")


def test_state_block_extracted_and_capped() -> None:
    """`_state_block` returns the `## STATE` head section up to the next `## `."""
    hook = _hook()
    text = (
        "---\nfront\n---\n"
        "## ⏵ STATE — READ FIRST\n"
        "NEXT ACTION: do the thing\n"
        "fact: the cap is 3\n"
        "## Another section\n"
        "should not appear\n"
    )
    block = hook._state_block(text)
    assert block is not None
    assert "NEXT ACTION: do the thing" in block
    assert "the cap is 3" in block
    assert "should not appear" not in block


def test_inflight_trdds_newest_first(tmp_path: Path) -> None:
    """Only in-flight TRDDs are returned, most-recently-`updated:` first."""
    hook = _hook()
    tasks = tmp_path / "design" / "tasks"
    _write_trdd(tasks, "11110000", "dev", "2026-06-01T10:00:00+0200", "Older", slug="older")
    _write_trdd(tasks, "22220000", "testing", "2026-06-02T09:30:00+0200", "Newer", slug="newer")
    _write_trdd(tasks, "33330000", "complete", "2026-06-03T09:30:00+0200", "Done", slug="done")
    rows = hook._inflight_trdds(tmp_path)
    names = [r[1] for r in rows]
    assert names[0].startswith("TRDD-20260602_044555+0200-22220000")  # newest in-flight first
    assert any("11110000" in n for n in names)
    assert not any("33330000" in n for n in names)  # terminal excluded


def test_build_handoff_contains_ground_truth(tmp_path: Path) -> None:
    """The composed handoff carries git HEAD, the STATE block verbatim, and the warning."""
    hook = _hook()
    _init_git_repo(tmp_path)
    _write_trdd(
        tmp_path / "design" / "tasks",
        "31095269",
        "dev",
        "2026-06-02T05:00:00+0200",
        "Context watchdog",
        state_block="NEXT ACTION: run the suite\nFACT: OAuth health is UNKNOWN until re-checked",
    )
    handoff = hook._build_handoff(tmp_path, str(_PROJECT_ROOT), "manual")
    assert "FAITHFULNESS INSTRUCTION" in handoff
    assert "UNVERIFIED" in handoff
    assert "## Git HEAD" in handoff
    assert "initial commit" in handoff  # recent-commit log is real
    assert "TRDD-20260602_044555+0200-31095269" in handoff
    assert "NEXT ACTION: run the suite" in handoff  # STATE block copied verbatim
    assert "OAuth health is UNKNOWN" in handoff
    assert "Compaction trigger: manual" in handoff


def test_build_handoff_degrades_without_git(tmp_path: Path) -> None:
    """No git repo and no TRDDs → still a valid handoff, '(unavailable)' sections, no crash."""
    hook = _hook()
    handoff = hook._build_handoff(tmp_path, str(_PROJECT_ROOT), "auto")
    assert "# PreCompact ground-truth handoff" in handoff
    assert "(unavailable)" in handoff
    assert "no in-flight TRDD found" in handoff


# ---------- git-root resolution: repo as a SUBDIR of $CLAUDE_PROJECT_DIR (issue #66) ----

def test_resolve_git_root_repo_at_project_root(tmp_path: Path) -> None:
    """Repo AT project_root → resolves to project_root (historical behavior preserved)."""
    hook = _hook()
    _init_git_repo(tmp_path)
    assert hook._resolve_git_root(tmp_path).resolve() == tmp_path.resolve()


def test_resolve_git_root_repo_in_subdir(tmp_path: Path) -> None:
    """Repo in a CHILD of project_root → resolved by the child-scan (the issue #66 fix)."""
    hook = _hook()
    repo = tmp_path / "myrepo"
    repo.mkdir()
    _init_git_repo(repo)
    # project_root has NO .git of its own; git run there exits 128. The fix scans children.
    assert hook._resolve_git_root(tmp_path).resolve() == repo.resolve()


def test_resolve_git_root_prefers_subdir_containing_cwd(tmp_path: Path) -> None:
    """With two sibling sub-repos, the one containing the session cwd wins."""
    hook = _hook()
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    _init_git_repo(a)
    _init_git_repo(b)
    # cwd is inside `beta` → that repo is the right ground-truth even though `alpha` sorts first.
    assert hook._resolve_git_root(tmp_path, str(b)).resolve() == b.resolve()


def test_resolve_git_root_cwd_inside_subdir_repo(tmp_path: Path) -> None:
    """A session cwd that is itself inside a repo resolves to that repo's toplevel directly."""
    hook = _hook()
    repo = tmp_path / "repo"
    sub = repo / "pkg"
    sub.mkdir(parents=True)
    _init_git_repo(repo)
    # cwd points DEEP inside the repo; show-toplevel (step 1) finds the repo root.
    assert hook._resolve_git_root(tmp_path, str(sub)).resolve() == repo.resolve()


def test_resolve_git_root_no_repo_anywhere_falls_back(tmp_path: Path) -> None:
    """No repo at project_root and none in any child → fall back to project_root unchanged."""
    hook = _hook()
    (tmp_path / "plain_child").mkdir()
    assert hook._resolve_git_root(tmp_path).resolve() == tmp_path.resolve()


def test_build_handoff_finds_git_in_subdir(tmp_path: Path) -> None:
    """REGRESSION (issue #66): repo in a subdir → git sections POPULATE, not '(unavailable)'.

    Before the fix the four git commands ran with cwd=project_root (== $CLAUDE_PROJECT_DIR),
    which exits 128 when the repo lives one level below, so Branch/HEAD/Recent-commits/Working
    tree all silently degraded to their '(unavailable)' fallbacks despite a healthy repo."""
    hook = _hook()
    repo = tmp_path / "the-plugin"
    repo.mkdir()
    _init_git_repo(repo)
    handoff = hook._build_handoff(tmp_path, str(_PROJECT_ROOT), "manual")
    assert "## Git HEAD" in handoff
    assert "initial commit" in handoff  # the real recent-commit log from the SUBDIR repo
    # The git sections must NOT have degraded to their unavailable fallbacks.
    assert "- Branch: (unavailable)" not in handoff
    assert "- HEAD: (unavailable)" not in handoff
    assert "## Recent commits" in handoff


# ---------- end-to-end subprocess ------------------------------------------

def test_hook_subprocess_writes_handoff(tmp_path: Path) -> None:
    """Real run: PreCompact JSON on stdin → handoff file on disk, exit 0. No mocks."""
    project = tmp_path / "project"
    project.mkdir()
    _init_git_repo(project)
    _write_trdd(
        project / "design" / "tasks",
        "31095269",
        "dev",
        "2026-06-02T05:00:00+0200",
        "Context watchdog",
        state_block="NEXT ACTION: run the suite\nFACT: do not trust the summary",
    )

    env = {
        "PATH": os.environ.get("PATH", ""),
        "CLAUDE_PLUGIN_ROOT": str(_PROJECT_ROOT),
        "CLAUDE_PROJECT_DIR": str(project),
    }
    payload = json.dumps(
        {
            "session_id": "sess-1",
            "cwd": str(project),
            "transcript_path": str(project / "transcript.jsonl"),
            "trigger": "manual",
            "hook_event_name": "PreCompact",
        }
    )
    proc = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook must always exit 0; stderr={proc.stderr!r}"

    handoff = project / ".janitor" / "state" / "precompact-handoff.md"
    assert handoff.exists(), f"handoff not written; stderr={proc.stderr!r}"
    text = handoff.read_text(encoding="utf-8")
    assert "FAITHFULNESS INSTRUCTION" in text
    assert "TRDD-20260602_044555+0200-31095269" in text
    assert "NEXT ACTION: run the suite" in text
    assert "initial commit" in text  # real git log section

    # Must NEVER block compaction: no decision:"block" in stdout. A systemMessage
    # pointer is allowed (and expected).
    if proc.stdout.strip():
        emitted = json.loads(proc.stdout.strip())
        assert emitted.get("decision") != "block"
        assert "precompact-handoff.md" in emitted.get("systemMessage", "")


def test_hook_subprocess_recent_conversation_resolves_transcript_roles_import(
    tmp_path: Path,
) -> None:
    """Real subprocess run, BY PATH, as Claude Code invokes the hook (TRDD-91D2VHW3 follow-up).

    In-process tests (`_hook()` via `importlib.util`) already have `scripts/` and
    `scripts/lib/` on `sys.path` from THIS test file's own setup — they cannot see whether the
    hook's module-top `import transcript_roles` actually resolves when the file is executed
    as its own process, the way Claude Code runs it, with only `CLAUDE_PLUGIN_ROOT` on the
    environment. This test proves (or disproves) exactly that: a real fixture transcript with
    a human turn, run through `[sys.executable, _HOOK_PATH]` — the same subprocess shape as
    `test_hook_subprocess_writes_handoff` above — and the human turn plus its reply must show
    up in the written handoff's "Recent conversation" section. If the module-top import were
    broken (the IDE's "transcript_roles is unknown import symbol" claim), the hook would raise
    at import time and exit non-zero, and `handoff.exists()` would be False — either failure
    mode is directly observable here, unlike in the in-process tests.
    """
    project = tmp_path / "project"
    project.mkdir()
    _init_git_repo(project)

    transcript = project / "transcript.jsonl"
    _write_jsonl(transcript, [
        _umsg("what is the current git status"),
        _amsg("clean working tree, HEAD at the initial commit"),
    ])

    env = {
        "PATH": os.environ.get("PATH", ""),
        "CLAUDE_PLUGIN_ROOT": str(_PROJECT_ROOT),
        "CLAUDE_PROJECT_DIR": str(project),
    }
    payload = json.dumps(
        {
            "session_id": "sess-transcript-roles",
            "cwd": str(project),
            "transcript_path": str(transcript),
            "trigger": "manual",
            "hook_event_name": "PreCompact",
        }
    )
    proc = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"hook exited non-zero — the module-top transcript_roles import likely failed; "
        f"stderr={proc.stderr!r}"
    )
    handoff = project / ".janitor" / "state" / "precompact-handoff.md"
    assert handoff.exists(), f"handoff not written; stderr={proc.stderr!r}"
    text = handoff.read_text(encoding="utf-8")
    assert "what is the current git status" in text
    assert "clean working tree, HEAD at the initial commit" in text


def test_inflight_trdds_found_in_subdir_repo(tmp_path: Path) -> None:
    """REGRESSION (issue #267): design/tasks/ lives under the nested repo (git_root), not
    under $CLAUDE_PROJECT_DIR (project_root) — the common layout #66 fixed for the git
    sections. `_build_handoff` must find the TRDD via the resolved git_root fallback
    instead of silently reporting 'no in-flight TRDD found' next to correct git state."""
    hook = _hook()
    repo = tmp_path / "the-repo"  # git_root — one level below project_root
    repo.mkdir()
    _init_git_repo(repo)
    _write_trdd(
        repo / "design" / "tasks",
        "31095269",
        "dev",
        "2026-06-02T05:00:00+0200",
        "Context watchdog",
        state_block="NEXT ACTION: run the suite",
    )
    handoff = hook._build_handoff(tmp_path, str(_PROJECT_ROOT), "manual")
    assert "no in-flight TRDD found" not in handoff
    assert "TRDD-20260602_044555+0200-31095269" in handoff
    assert "NEXT ACTION: run the suite" in handoff


def test_hook_subprocess_writes_handoff_with_subdir_repo(tmp_path: Path) -> None:
    """End-to-end (issue #66): $CLAUDE_PROJECT_DIR is the PARENT of the repo → git sections
    populate from the discovered subdir repo, not '(unavailable)'. No mocks."""
    project = tmp_path / "project"  # $CLAUDE_PROJECT_DIR — NO .git of its own
    repo = project / "the-repo"     # the actual git repo, one level below
    repo.mkdir(parents=True)
    _init_git_repo(repo)

    env = {
        "PATH": os.environ.get("PATH", ""),
        "CLAUDE_PLUGIN_ROOT": str(_PROJECT_ROOT),
        "CLAUDE_PROJECT_DIR": str(project),
    }
    payload = json.dumps(
        {"session_id": "s2", "cwd": str(project), "hook_event_name": "PreCompact"}
    )
    proc = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook must always exit 0; stderr={proc.stderr!r}"

    handoff = project / ".janitor" / "state" / "precompact-handoff.md"
    assert handoff.exists(), f"handoff not written; stderr={proc.stderr!r}"
    text = handoff.read_text(encoding="utf-8")
    assert "initial commit" in text  # real git log resolved from the subdir repo
    assert "- Branch: (unavailable)" not in text
    assert "- HEAD: (unavailable)" not in text


def test_hook_subprocess_never_blocks_on_missing_project(tmp_path: Path) -> None:
    """Even with a non-repo project dir, the hook exits 0 and writes a degraded handoff."""
    project = tmp_path / "bare"
    project.mkdir()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "CLAUDE_PLUGIN_ROOT": str(_PROJECT_ROOT),
        "CLAUDE_PROJECT_DIR": str(project),
    }
    payload = json.dumps({"cwd": str(project), "hook_event_name": "PreCompact"})
    proc = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    handoff = project / ".janitor" / "state" / "precompact-handoff.md"
    assert handoff.exists()
    assert "(unavailable)" in handoff.read_text(encoding="utf-8")


# ---------- integration: post-compact-resume prepends the handoff pointer ---

@pytest.fixture
def state_mod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh `state` module rooted at a tmp project dir."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    sys.modules.pop("state", None)
    import state  # noqa: PLC0415 - intentional per-test reload

    return project, state


def test_resume_prepends_handoff_pointer_when_present(state_mod) -> None:
    """When the handoff exists, post-compact-resume prepends a 'read it FIRST' pointer."""
    project, state = state_mod
    post = _post_hook()
    state.init_state()
    (state.state_dir() / post._HANDOFF_FILENAME).write_text("handoff body\n", encoding="utf-8")
    _write_trdd(
        project / "design" / "tasks", "31095269", "dev", "2026-06-02T05:00:00+0200", "Watchdog"
    )
    post._record_resume_directive(state)
    flag = (state.state_dir() / "resume-after-compact.flag").read_text()
    assert flag.startswith("read .janitor/state/precompact-handoff.md FIRST")
    assert "UNVERIFIED" in flag
    assert "TRDD-31095269" in flag  # the board directive is still appended after the pointer


def test_resume_no_pointer_when_handoff_absent(state_mod) -> None:
    """With no handoff file, the directive is the plain board directive (no pointer)."""
    project, state = state_mod
    post = _post_hook()
    _write_trdd(
        project / "design" / "tasks", "31095269", "dev", "2026-06-02T05:00:00+0200", "Watchdog"
    )
    post._record_resume_directive(state)
    flag = (state.state_dir() / "resume-after-compact.flag").read_text()
    assert not flag.startswith("read .janitor/state/precompact-handoff.md FIRST")
    assert "TRDD-31095269" in flag


def test_resume_handoff_alone_yields_reground_directive(state_mod) -> None:
    """Handoff present but NO in-flight task → still resume, targeting the handoff."""
    project, state = state_mod
    post = _post_hook()
    state.init_state()
    (state.state_dir() / post._HANDOFF_FILENAME).write_text("handoff body\n", encoding="utf-8")
    # No in-flight TRDD on the board (only a terminal one).
    _write_trdd(
        project / "design" / "tasks", "deadbeef", "complete", "2026-06-02T05:00:00+0200", "Done"
    )
    post._record_resume_directive(state)
    flag_path = state.state_dir() / "resume-after-compact.flag"
    assert flag_path.exists(), "a handoff alone is worth a resume turn for re-grounding"
    flag = flag_path.read_text()
    assert flag.startswith("read .janitor/state/precompact-handoff.md FIRST")
    assert "re-ground" in flag


# ---------- recent conversation (transcript-derived) -----------------------

def _umsg(text: str, **flags) -> dict:
    """A user TEXT turn (the real Claude Code user-message shape)."""
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        **flags,
    }


def _amsg(text: str) -> dict:
    """An assistant TEXT turn."""
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _tool_result_turn() -> dict:
    """A user turn carrying a tool_result (no text block) — NOT conversation."""
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "out"}]}}


def _thinking_turn() -> dict:
    """An assistant turn that is only thinking — NOT visible conversation."""
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "h"}]}}


def _tool_use_turn(name: str, **tool_input: object) -> dict:
    """An assistant turn containing exactly one `tool_use` block."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": name, "input": tool_input}],
        },
    }


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def test_extract_text_shapes() -> None:
    """_extract_text pulls text blocks only; tool/thinking → ''; string → itself; junk → ''."""
    hook = _hook()
    assert hook._extract_text("plain") == "plain"
    assert hook._extract_text([{"type": "text", "text": "a"}, {"type": "tool_use", "name": "x"}]) == "a"
    assert hook._extract_text([{"type": "tool_result", "content": "z"}]) == ""
    assert hook._extract_text([{"type": "thinking", "thinking": "h"}]) == ""
    assert hook._extract_text(None) == ""
    assert hook._extract_text(12345) == ""


def test_recent_turns_filters_and_order(tmp_path: Path) -> None:
    """Returns user+assistant TEXT turns newest-last; heartbeat / meta / tool / thinking excluded.

    The heartbeat PROMPT itself is dropped (not "human"-classified), but the assistant's own
    substantive reply to it ("Clean — holding.") IS kept — orchestrator revision on
    TRDD-91D2VHW3: an unattended, heartbeat-started turn is still real agent work, dropping it
    would lose "what was the agent doing" (same choice card 2a made for
    `external_clear.recent_messages`). Only a BARE heartbeat-protocol reply
    (`transcript_roles.is_heartbeat_reply`) is dropped — see the dedicated test below.
    """
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [
        _umsg("first real question"),
        _amsg("first answer"),
        _tool_result_turn(),
        _thinking_turn(),
        _umsg("[janitor-heartbeat]\n/path/to/stub ... long cron prompt"),  # excluded
        _amsg("Clean — holding."),  # kept — substantive reply to the heartbeat-started turn
        _umsg("second question", isMeta=True),  # meta excluded
        _umsg("third question"),
        _amsg("third answer"),
    ])
    turns = hook._recent_turns(str(tx), n=5)
    assert turns is not None
    assert ("user", "first real question") in turns
    assert ("assistant", "Clean — holding.") in turns
    assert ("user", "third question") in turns
    assert turns[-1] == ("assistant", "third answer")  # chronological, newest last
    assert all("janitor-heartbeat" not in t for _, t in turns)
    assert all(t != "second question" for _, t in turns)


def test_recent_turns_excludes_task_notification(tmp_path: Path) -> None:
    """TRDD-91D2VHW3: a task-notification record is not human conversation — must be dropped."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [
        _umsg("<task-notification>\n<status>completed</status>\n...</task-notification>"),
        _umsg("real human question"),
        _amsg("real human answer"),
    ])
    turns = hook._recent_turns(str(tx), n=5)
    assert turns is not None
    assert all("task-notification" not in t for _, t in turns)
    assert ("user", "real human question") in turns


def test_recent_turns_excludes_local_command_stdout(tmp_path: Path) -> None:
    """TRDD-91D2VHW3: a `<local-command-stdout>` wrapper is a command result, not human text."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [
        _umsg("<local-command-stdout>\nsome command output\n</local-command-stdout>"),
        _umsg("real human question"),
        _amsg("real human answer"),
    ])
    turns = hook._recent_turns(str(tx), n=5)
    assert turns is not None
    assert all("local-command-stdout" not in t for _, t in turns)
    assert ("user", "real human question") in turns


def test_recent_turns_excludes_command_message(tmp_path: Path) -> None:
    """TRDD-91D2VHW3: a `<command-message>` with no `<command-name>` is a non-human echo.

    Narrowed per transcript_roles' own defect-1 carve-out: a `<command-message>` record that
    ALSO carries `<command-name>` is a typed slash command (origin.kind "human" or absent) and
    classifies "human", not "system" — this fixture has no `<command-name>`, so it stays the
    generic wrapper case this test is pinning.
    """
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [
        _umsg("<command-message>some-command</command-message>"),
        _umsg("real human question"),
        _amsg("real human answer"),
    ])
    turns = hook._recent_turns(str(tx), n=5)
    assert turns is not None
    assert all("command-message" not in t for _, t in turns)
    assert ("user", "real human question") in turns


def test_recent_turns_keeps_human_message(tmp_path: Path) -> None:
    """A plain human record (classify_record → "human") is kept, alongside its assistant reply."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [
        _umsg("fix the deploy script"),
        _amsg("done — deploy script fixed"),
    ])
    turns = hook._recent_turns(str(tx), n=5)
    assert turns == [("user", "fix the deploy script"), ("assistant", "done — deploy script fixed")]


def test_recent_turns_drops_bare_heartbeat_reply_but_keeps_substantive_heartbeat_work(
    tmp_path: Path,
) -> None:
    """Only the BARE `is_heartbeat_reply` text is dropped — real work in the same unattended
    session (heartbeat-started or not) is kept, per the orchestrator's revision of this card:
    an unattended session's heartbeat-started turns ARE the real work.
    """
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [
        _umsg("[janitor-heartbeat]\n/path/to/stub"),
        _amsg("janitor heartbeat"),  # bare quiet reply — dropped
        _umsg("[janitor-heartbeat]\n/path/to/stub"),
        _amsg("janitor heartbeat\ndrift: OAuth slot 2 at 40%"),  # <=3 lines, still bare — dropped
        _umsg("[janitor-heartbeat]\n/path/to/stub"),
        _amsg("Reading the TRDD card and dispatching the fix agent."),  # real work — kept
    ])
    turns = hook._recent_turns(str(tx), n=10)
    assert turns is not None
    assert ("assistant", "janitor heartbeat") not in turns
    assert not any(t.startswith("janitor heartbeat\ndrift") for _, t in turns)
    assert ("assistant", "Reading the TRDD card and dispatching the fix agent.") in turns


def test_recent_turns_drops_api_error_message(tmp_path: Path) -> None:
    """An `isApiErrorMessage` assistant record is an error surface, not conversation — dropped
    the same way `jev_compaction` and `external_clear` already skip it.
    """
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [
        _umsg("run the migration"),
        {
            "type": "assistant",
            "isApiErrorMessage": True,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "API Error: 529"}]},
        },
        _amsg("migration complete"),
    ])
    turns = hook._recent_turns(str(tx), n=5)
    assert turns is not None
    assert all("API Error" not in t for _, t in turns)
    assert ("assistant", "migration complete") in turns


def test_recent_turns_seeks_back_for_human_message_older_than_tail_window(tmp_path: Path) -> None:
    """The owner's last message, once, then ~3 MiB of heartbeat-only filler pushing it out of
    the 2 MiB tail window (`_TAIL_BYTES`) entirely — TRDD-91D2VHW3 follow-up: the handoff must
    still surface it, doubling the read window backward rather than losing it silently.
    """
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    filler = [_umsg("[janitor-heartbeat]\n/path/to/stub"), _amsg("x" * 300_000)] * 10
    _write_jsonl(tx, [
        _umsg("what is the deploy password rotation policy"),
        _amsg("check the runbook"),
        *filler,
    ])
    assert tx.stat().st_size > hook._TAIL_BYTES  # the human turn really is outside the tail

    turns = hook._recent_turns(str(tx))
    assert turns is not None
    older = turns[0]
    assert "older" in older[0] and "user" in older[0]
    assert older[1] == "what is the deploy password rotation policy"


def test_recent_turns_no_human_message_anywhere_emits_explicit_placeholder(tmp_path: Path) -> None:
    """No human message in the transcript at all (even after the backward seek) — an explicit
    placeholder line replaces the silent gap, per the coordinator's TRDD-91D2VHW3 follow-up.
    """
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [
        _umsg("[janitor-heartbeat]\n/path/to/stub"),
        _amsg("Clean — holding."),
        _umsg("[janitor-heartbeat]\n/path/to/stub"),
        _amsg("Dispatched the fix agent."),
    ])
    turns = hook._recent_turns(str(tx))
    assert turns is not None
    assert turns[0] == ("note", "(last owner message is older than the recent window)")


def test_recent_turns_prepends_last_user_on_assistant_streak(tmp_path: Path) -> None:
    """A long assistant streak (last n all assistant) still surfaces the most recent user ask."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [
        _umsg("the driving request"),
        _amsg("step 1"), _amsg("step 2"), _amsg("step 3"),
        _amsg("step 4"), _amsg("step 5"), _amsg("step 6"),
    ])
    turns = hook._recent_turns(str(tx), n=5)
    assert turns is not None
    assert turns[0] == ("user", "the driving request")  # prepended despite being >n back
    assert sum(1 for r, _ in turns if r == "user") >= 1


def test_recent_turns_truncates_long_turn(tmp_path: Path) -> None:
    """An over-long turn is truncated with a marker so the handoff stays bounded."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [_umsg("u"), _amsg("X" * (hook._MAX_TURN_CHARS + 500))])
    turns = hook._recent_turns(str(tx), n=5)
    assert turns is not None
    long = next(t for _, t in turns if t.startswith("X"))
    assert long.endswith("… (truncated)")
    assert len(long) <= hook._MAX_TURN_CHARS + len(" … (truncated)")


def test_recent_turns_missing_or_empty(tmp_path: Path) -> None:
    """Missing path / nonexistent file / only-noise → None (fail-open)."""
    hook = _hook()
    assert hook._recent_turns("", n=5) is None
    assert hook._recent_turns(str(tmp_path / "nope.jsonl"), n=5) is None
    noise = tmp_path / "n.jsonl"
    _write_jsonl(noise, [_tool_result_turn(), _thinking_turn()])
    assert hook._recent_turns(str(noise), n=5) is None


def test_recent_turns_skips_malformed_lines(tmp_path: Path) -> None:
    """A malformed JSONL line is skipped, never fatal — the good turns still return."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    tx.write_text(
        json.dumps(_umsg("good one")) + "\n"
        + "{ this is not json\n"
        + json.dumps(_amsg("good answer")) + "\n",
        encoding="utf-8",
    )
    turns = hook._recent_turns(str(tx), n=5)
    assert turns is not None
    assert ("user", "good one") in turns
    assert ("assistant", "good answer") in turns


# ---------- recent memory atoms (filesystem-derived) -----------------------

def _mem_page(d: Path, name: str, atom_ids: list[str], *, prose: str = "topic prose") -> None:
    d.mkdir(parents=True, exist_ok=True)
    body = "---\nname: x\ndescription: y\n---\n\n" + prose + "\n\n"
    for a in atom_ids:
        body += f"^{a} [keywords: alpha beta]\nA fact owned by {a}.\n\n"
    (d / name).write_text(body, encoding="utf-8")


def test_recent_memory_atoms_lists_collapses_and_pages(tmp_path: Path) -> None:
    """≤N atoms → list ids; >N atoms → collapse to file; prose page (no atoms) → page row."""
    hook = _hook()
    mem = tmp_path / "mem"
    _mem_page(mem, "few.md", ["memory-a1", "memory-a2"])
    _mem_page(mem, "many.md", [f"memory-b{i}" for i in range(hook._MEM_ATOMS_COLLAPSE + 2)])
    _mem_page(mem, "prose.md", [])
    rows = hook._recent_memory_atoms([("local", mem)], now=time.time())
    by_name = {name: (kind, count, atoms) for kind, _scope, name, count, atoms in rows}
    assert by_name["few.md"][0] == "atoms"
    # rows carry (id, desc) pairs; these fixture markers have no desc, so every desc is None
    assert [aid for aid, _d in by_name["few.md"][2]] == ["memory-a1", "memory-a2"]
    assert all(desc is None for _aid, desc in by_name["few.md"][2])
    assert by_name["many.md"][0] == "collapsed"
    assert by_name["many.md"][1] == hook._MEM_ATOMS_COLLAPSE + 2
    assert by_name["prose.md"][0] == "page"


def test_recent_memory_atoms_excludes_artifacts_and_private(tmp_path: Path) -> None:
    """MEMORY.md + librarian artifacts are skipped; the private user-mem/ is NEVER listed."""
    hook = _hook()
    mem = tmp_path / "mem"
    _mem_page(mem, "real.md", ["memory-x1"])
    _mem_page(mem, "MEMORY.md", ["memory-stub"])
    _mem_page(mem, "memory-reorg-proposed.md", ["memory-reorg"])
    _mem_page(mem / "user-mem", "0001.md", ["memory-private"])  # PRIVATE store
    rows = hook._recent_memory_atoms([("local", mem)], now=time.time())
    names = {name for _k, _s, name, _c, _i in rows}
    assert "real.md" in names
    assert "MEMORY.md" not in names
    assert "memory-reorg-proposed.md" not in names
    assert "0001.md" not in names  # user-mem privacy boundary
    all_ids = [aid for _k, _s, _n, _c, atoms in rows for aid, _d in atoms]
    assert "memory-private" not in all_ids  # no private atom id leaked


def test_recent_memory_atoms_window_excludes_old(tmp_path: Path) -> None:
    """A page older than the recency window is not listed."""
    hook = _hook()
    mem = tmp_path / "mem"
    _mem_page(mem, "fresh.md", ["memory-f1"])
    _mem_page(mem, "stale.md", ["memory-s1"])
    old = time.time() - hook._MEM_RECENT_WINDOW_S - 3600
    os.utime(mem / "stale.md", (old, old))
    rows = hook._recent_memory_atoms([("local", mem)], now=time.time())
    names = {name for _k, _s, name, _c, _i in rows}
    assert "fresh.md" in names
    assert "stale.md" not in names


def test_recent_memory_atoms_dedupes_overlapping_scopes(tmp_path: Path) -> None:
    """The same physical file reached via two scope entries is listed once."""
    hook = _hook()
    mem = tmp_path / "mem"
    _mem_page(mem, "one.md", ["memory-o1"])
    rows = hook._recent_memory_atoms([("local", mem), ("project", mem)], now=time.time())
    assert sum(1 for _k, _s, name, _c, _i in rows if name == "one.md") == 1


def test_recent_memory_atoms_parses_desc_slug(tmp_path: Path) -> None:
    """The `desc:` SLUG is parsed per atom (PARITY with memgrep's DESC_CORPUS); absent → None."""
    hook = _hook()
    mem = tmp_path / "mem"
    mem.mkdir()
    # The SAME marker lines as memgrep's DESC_CORPUS parity fixture (TRDD-056384eb DERIVED #4) —
    # both parsers MUST extract the same desc from the same line.
    (mem / "handoff-hub.md").write_text(
        "---\nname: handoff-hub\n---\n# Handoff hub\n\n"
        "^new-handoff [desc: new_handoff_carries_recent_turns, keywords: zqxdesc handoff]\n"
        "The new handoff lists recent turns and memory ids.\n"
        "^plain [keywords: zqxplain bare]\nThis atom carries no desc slug.\n",
        encoding="utf-8",
    )
    rows = hook._recent_memory_atoms([("local", mem)], now=time.time())
    atoms = next(a for _k, _s, name, _c, a in rows if name == "handoff-hub.md")
    by_id = dict(atoms)
    assert by_id["new-handoff"] == "new_handoff_carries_recent_turns"  # STORED as the slug
    assert by_id["plain"] is None  # an atom with no desc → None


def test_format_memory_rows_renders_desc_as_spaced_phrase() -> None:
    """An atom's desc slug renders `_`→space; a desc-less atom shows the bare id; collapse/page kept."""
    hook = _hook()
    lines = hook._format_memory_rows([
        ("atoms", "LOCAL", "h.md", 2,
         [("new-handoff", "new_handoff_carries_recent_turns"), ("plain", None)]),
        ("collapsed", "USER", "big.md", 9, []),
        ("page", "PROJECT", "prose.md", 0, []),
    ])
    text = "\n".join(lines)
    assert "^new-handoff — new handoff carries recent turns" in text  # slug shown as a phrase
    assert "new_handoff_carries_recent_turns" not in text  # the raw slug is never shown
    assert "    ^plain" in text  # desc-less atom → bare id
    assert "^plain —" not in text
    assert "big.md (9 atoms — file listed" in text
    assert "- [PROJECT] prose.md" in text


# ---------- the two new sections appear in the composed handoff -------------

def test_build_handoff_has_conversation_and_memory_sections(tmp_path: Path) -> None:
    """_build_handoff renders both new sections; a transcript fixture surfaces a user turn."""
    hook = _hook()
    _init_git_repo(tmp_path)
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [_umsg("what did I ask"), _amsg("my reply")])
    handoff = hook._build_handoff(tmp_path, str(_PROJECT_ROOT), "manual", str(tx))
    assert "## Recent conversation" in handoff
    assert "**USER:**" in handoff
    assert "what did I ask" in handoff
    assert "## Recent memory changes" in handoff


def test_build_handoff_no_transcript_degrades_conversation(tmp_path: Path) -> None:
    """No transcript → the conversation section degrades gracefully, never crashes (fail-open)."""
    hook = _hook()
    handoff = hook._build_handoff(tmp_path, str(_PROJECT_ROOT), "auto")  # transcript_path default ""
    assert "## Recent conversation" in handoff
    assert "(recent conversation unavailable)" in handoff

def test_active_skills_from_transcript_no_count_cap(tmp_path: Path) -> None:
    """The count cap is REMOVED (review fix, TRDD-7MGJYLY5 follow-up): every distinct
    `Skill` tool_use name survives, and the joined line comfortably fits the 400-byte
    budget for a handful of short names — no truncation marker appended."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    entries = [_tool_use_turn("Skill", command=f"skill-{i}") for i in range(9)]
    _write_jsonl(tx, entries)
    names = hook._active_skills_from_transcript(str(tx))
    assert len(names) == 9, "no count cap — all nine distinct names survive"
    assert len(", ".join(names).encode("utf-8")) <= hook._ACTIVE_SKILLS_LINE_MAX_BYTES
    assert not names[-1].startswith("…"), "well under budget — no truncation marker"


def test_active_skills_from_transcript_line_budget_truncates_with_marker(tmp_path: Path) -> None:
    """When the joined line would exceed the byte budget, the OLDEST names are kept (an
    early mode skill survives the cut) and a single `…(+N more)` marker replaces the
    dropped newest names — the line stays within budget."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    entries = [_tool_use_turn("Skill", command="ponytail")]  # oldest — must survive
    entries += [_tool_use_turn("Skill", command=f"skill-{'x' * 20}-{i}") for i in range(30)]
    _write_jsonl(tx, entries)
    names = hook._active_skills_from_transcript(str(tx), line_max_bytes=100)
    assert names[0] == "ponytail", "oldest name survives the truncation"
    assert names[-1].startswith("…(+"), "a marker replaces the dropped newest names"
    assert len(", ".join(names).encode("utf-8")) <= 100


def test_active_skills_from_transcript_slash_typed_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A user-typed `/skill-name` line is accepted only when it names a REAL skill (a
    directory under the plugin's own `skills/`) or a harness builtin mode command
    (`_HARNESS_SKILL_BUILTINS`) — an unrelated or unknown slash word is not."""
    hook = _hook()
    plugin_root = tmp_path / "plugin"
    (plugin_root / "skills" / "my-skill").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    tx = tmp_path / "t.jsonl"
    entries = [
        _umsg("/ponytail full"),
        _umsg("/my-skill"),
        _umsg("/not-a-real-skill"),
        _amsg("ack"),
    ]
    _write_jsonl(tx, entries)
    names = hook._active_skills_from_transcript(str(tx))
    assert names == ["ponytail", "my-skill"]


def test_active_skills_from_transcript_excludes_janitor_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`janitor-*` skills (on-demand commands run by hooks/the user, e.g. arm,
    disarm, findings, memory chores) are never surfaced as an "active mode" to
    reload after compaction — neither as a `Skill` tool_use nor a slash-typed
    command — while an unrelated skill still is."""
    hook = _hook()
    plugin_root = tmp_path / "plugin"
    (plugin_root / "skills" / "janitor-findings").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    tx = tmp_path / "t.jsonl"
    entries = [
        _tool_use_turn("Skill", command="janitor-arm"),
        _umsg("/janitor-findings"),
        _umsg("/ponytail full"),
        _amsg("ack"),
    ]
    _write_jsonl(tx, entries)
    names = hook._active_skills_from_transcript(str(tx))
    assert names == ["ponytail"]


def test_active_skills_from_transcript_path_not_mistaken_for_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pasted absolute path (`/Users/x/y/...`) is never mistaken for a slash-typed
    skill — the leading path segment is not in the allowlist, so it yields nothing."""
    hook = _hook()
    plugin_root = tmp_path / "plugin"
    (plugin_root / "skills").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [_umsg("/Users/x/y/some/path"), _amsg("ack")])
    names = hook._active_skills_from_transcript(str(tx))
    assert names == []


def test_active_skills_from_transcript_slash_only_checks_first_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the FIRST non-empty line of a user text block is tested for a slash-typed
    skill — a stub-path line (e.g. `/tmp/...`) appearing LATER in a multi-line paste
    (a heartbeat payload) must never match, even if it would otherwise be a real skill
    dir name."""
    hook = _hook()
    plugin_root = tmp_path / "plugin"
    (plugin_root / "skills" / "tmp").mkdir(parents=True)  # real skill dir named "tmp"
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [_umsg("some heartbeat text\n/tmp/janitor/state.json"), _amsg("ack")])
    names = hook._active_skills_from_transcript(str(tx))
    assert names == [], "the first line has no leading slash — the second line is never tested"


def test_active_skills_from_transcript_env_scan_budget_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`CLAUDE_PLUGIN_OPTION_ACTIVE_SKILLS_SCAN_MAX_BYTES` overrides the default 8 MB
    scan budget at import time; a small override still cuts the backward scan early,
    keeps the partial result, and logs the cutoff to stderr."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_ACTIVE_SKILLS_SCAN_MAX_BYTES", "200")
    hook = _hook()  # re-imported fresh — the module-level default reads the env now
    tx = tmp_path / "t.jsonl"
    entries = [_tool_use_turn("Skill", command="early-skill")]
    entries += [_amsg("x" * 5000) for _ in range(50)]
    entries += [_tool_use_turn("Skill", command="late-skill")]
    _write_jsonl(tx, entries)
    names = hook._active_skills_from_transcript(str(tx))
    assert names == ["late-skill"], "the env-overridden budget cut before reaching the early skill"
    assert "scan cut at" in capsys.readouterr().err


# ---------- trigger=="auto" continuity record (TRDD-7MGJYLY5) --------------

def test_active_skills_from_transcript_budget_cuts_scan_keeps_partial(tmp_path: Path) -> None:
    """A byte budget smaller than the transcript stops the backward scan early but keeps
    whatever distinct names it already found (fail-open, never crashes, never scans past
    budget)."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    entries = [_tool_use_turn("Skill", command="early-skill")]
    entries += [_amsg("x" * 5000) for _ in range(50)]  # pushes "early-skill" out of a tiny budget
    entries += [_tool_use_turn("Skill", command="late-skill")]
    _write_jsonl(tx, entries)
    names = hook._active_skills_from_transcript(str(tx), max_scan_bytes=200)
    assert names == ["late-skill"], "budget cut before reaching the early skill — partial result kept"


def test_active_skills_from_transcript_reads_backward_in_chunks(tmp_path: Path) -> None:
    """A transcript LARGER than one chunk still finds a skill near the start — the
    backward chunked reader must carry partial lines across chunk boundaries without
    dropping or duplicating a record."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    entries = [_tool_use_turn("Skill", command="early-skill")]
    entries += [_amsg("x" * 5000) for _ in range(50)]  # pad well past one small chunk
    _write_jsonl(tx, entries)
    names = hook._active_skills_from_transcript(str(tx), chunk_bytes=512)
    assert names == ["early-skill"]


def test_active_skills_from_transcript_never_corrupts_multibyte_boundary(tmp_path: Path) -> None:
    """A skill name containing a multi-byte UTF-8 character must survive intact even
    when a small chunk size forces the chunk boundary to fall mid-character (review
    fix: splitting on the raw byte b"\\n" BEFORE decoding, not decode-then-split, so a
    continuation byte — never 0x0A — can never be mistaken for a line break, and
    `carry` reunites the two raw halves before either is decoded)."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    name = "tldr-café-日本語"
    _write_jsonl(tx, [_tool_use_turn("Skill", command=name)])
    names = hook._active_skills_from_transcript(str(tx), chunk_bytes=3)
    assert names == [name]
    assert "�" not in "".join(names), "a replacement character means bytes were corrupted"


def test_open_files_from_transcript_dedupes_recent_read_edit(tmp_path: Path) -> None:
    """Distinct `Read`/`Edit` file_paths under the project root, most-recent first; a
    repeat path counts once."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [
        _tool_use_turn("Read", file_path=str(tmp_path / "a.py")),
        _tool_use_turn("Edit", file_path=str(tmp_path / "b.py")),
        _tool_use_turn("Bash", command="ls"),  # not Read/Edit — excluded
        _tool_use_turn("Read", file_path=str(tmp_path / "a.py")),  # repeat — deduped
        _tool_use_turn("Edit", file_path=str(tmp_path / "c.py")),
    ])
    paths = hook._open_files_from_transcript(str(tx), tmp_path)
    assert paths == [str(tmp_path / "c.py"), str(tmp_path / "a.py"), str(tmp_path / "b.py")]


def test_open_files_from_transcript_excludes_scratch_and_outside_paths(tmp_path: Path) -> None:
    """A `/tmp` path, a `reports/`-nested path, and a path outside the project root are
    all dropped — a continuity nudge naming scratch/report files is worse than silence
    (review fix on TRDD-7MGJYLY5)."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    outside = tx.parent.parent / "outside.py"
    _write_jsonl(tx, [
        _tool_use_turn("Read", file_path="/tmp/scratch.py"),
        _tool_use_turn("Read", file_path=str(tmp_path / "reports" / "audit.md")),
        _tool_use_turn("Read", file_path=str(outside)),
        _tool_use_turn("Edit", file_path=str(tmp_path / "src" / "real.py")),
    ])
    paths = hook._open_files_from_transcript(str(tx), tmp_path)
    assert paths == [str(tmp_path / "src" / "real.py")]


def test_open_files_from_transcript_caps_at_limit(tmp_path: Path) -> None:
    """More distinct in-scope files than `_OPEN_FILES_MAX` are truncated, newest kept."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    entries = [
        _tool_use_turn("Read", file_path=str(tmp_path / f"f{i}.py"))
        for i in range(hook._OPEN_FILES_MAX + 5)
    ]
    _write_jsonl(tx, entries)
    paths = hook._open_files_from_transcript(str(tx), tmp_path)
    assert len(paths) == hook._OPEN_FILES_MAX
    assert paths[0] == str(tmp_path / f"f{hook._OPEN_FILES_MAX + 4}.py")  # newest first


def test_debounced_true_within_window_same_session(tmp_path: Path) -> None:
    """A second `trigger=="auto"` write within the window for the SAME session debounces."""
    hook = _hook()
    (tmp_path / hook.CONTINUITY_FILENAME).write_text(
        json.dumps({"session_id": "s1"}), encoding="utf-8"
    )
    assert hook._debounced(tmp_path, "s1", time.time()) is True


def test_debounced_false_different_session(tmp_path: Path) -> None:
    """A DIFFERENT session_id must never debounce — debounce is per-session."""
    hook = _hook()
    (tmp_path / hook.CONTINUITY_FILENAME).write_text(
        json.dumps({"session_id": "s1"}), encoding="utf-8"
    )
    assert hook._debounced(tmp_path, "s2", time.time()) is False


def test_debounced_false_after_window(tmp_path: Path) -> None:
    """Past the debounce window the record is stale and must not suppress a write."""
    hook = _hook()
    path = tmp_path / hook.CONTINUITY_FILENAME
    path.write_text(json.dumps({"session_id": "s1"}), encoding="utf-8")
    old = time.time() - hook._CONTINUITY_DEBOUNCE_WINDOW_S - 5
    os.utime(path, (old, old))
    assert hook._debounced(tmp_path, "s1", time.time()) is False


def _run_precompact(project: Path, payload: dict) -> subprocess.CompletedProcess:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "CLAUDE_PLUGIN_ROOT": str(_PROJECT_ROOT),
        "CLAUDE_PROJECT_DIR": str(project),
    }
    return subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_hook_subprocess_trigger_auto_writes_continuity_not_prose(tmp_path: Path) -> None:
    """Real run: trigger="auto" writes precompact-continuity.json and NOT the prose
    precompact-handoff.md (owner ruling TRDD-7MGJYLY5 — the harness already
    auto-summarizes; the janitor only needs a small machine-readable continuity record)."""
    project = tmp_path / "project"
    project.mkdir()
    _init_git_repo(project)
    proc = _run_precompact(project, {
        "session_id": "sess-auto-1",
        "cwd": str(project),
        "transcript_path": str(project / "transcript.jsonl"),
        "trigger": "auto",
        "hook_event_name": "PreCompact",
    })
    assert proc.returncode == 0, f"hook must always exit 0; stderr={proc.stderr!r}"
    sd = project / ".janitor" / "state"
    continuity = sd / "precompact-continuity.json"
    prose = sd / "precompact-handoff.md"
    assert continuity.exists(), f"continuity record not written; stderr={proc.stderr!r}"
    assert not prose.exists(), "trigger=auto must NOT write the prose handoff"
    data = json.loads(continuity.read_text(encoding="utf-8"))
    assert data["session_id"] == "sess-auto-1"
    assert data["trigger"] == "auto"
    for key in ("inflight_trdds", "background_agents", "active_skills", "open_files"):
        assert key in data


def test_hook_subprocess_trigger_auto_second_firing_is_debounced(tmp_path: Path) -> None:
    """Two auto firings within 120s for the SAME session must not double-write; the
    second logs 'debounced' (measured 7 firings in 48s on one real compaction,
    TRDD-TWF7DXXR)."""
    project = tmp_path / "project"
    project.mkdir()
    _init_git_repo(project)
    payload = {
        "session_id": "sess-debounce-1",
        "cwd": str(project),
        "transcript_path": "",
        "trigger": "auto",
        "hook_event_name": "PreCompact",
    }
    proc1 = _run_precompact(project, payload)
    assert proc1.returncode == 0, f"stderr={proc1.stderr!r}"
    continuity = project / ".janitor" / "state" / "precompact-continuity.json"
    assert continuity.exists(), "positive control failed — fixture is broken"
    first_bytes = continuity.read_bytes()
    proc2 = _run_precompact(project, payload)
    assert proc2.returncode == 0, f"stderr={proc2.stderr!r}"
    assert continuity.read_bytes() == first_bytes, "debounced firing must not rewrite the record"
    log = project / ".janitor" / "logs" / "pre-compact-handoff.log"
    assert log.is_file(), "positive control failed — no log at all"
    assert "debounced" in log.read_text(encoding="utf-8")


def test_hook_subprocess_manual_then_debounced_auto_stamps_auto_last(tmp_path: Path) -> None:
    """THE ORDERING HOLE (review fix, TRDD-7MGJYLY5): a manual /compact (writes the
    prose handoff) followed within the debounce window by a debounced auto firing (no
    continuity re-write) must still leave `precompact-last-trigger.json` naming "auto"
    — SessionStart decides manual-vs-auto by this stamp, never by comparing the prose
    and continuity files' mtimes, which the debounce would otherwise leave stale."""
    project = tmp_path / "project"
    project.mkdir()
    _init_git_repo(project)
    session = "sess-order-1"
    manual_payload = {
        "session_id": session,
        "cwd": str(project),
        "transcript_path": "",
        "trigger": "manual",
        "hook_event_name": "PreCompact",
    }
    auto_payload = {**manual_payload, "trigger": "auto"}
    # Manual first (prose handoff written), then an auto firing that debounces — the
    # SAME sequence that used to leave the prose file newer than the continuity record.
    proc1 = _run_precompact(project, manual_payload)
    assert proc1.returncode == 0, f"stderr={proc1.stderr!r}"
    # Pre-seed a continuity record for THIS session so the debounce guard actually
    # engages on the second firing (debounce keys off an existing same-session record).
    sd = project / ".janitor" / "state"
    (sd / "precompact-continuity.json").write_text(
        json.dumps({"session_id": session}), encoding="utf-8"
    )
    proc2 = _run_precompact(project, auto_payload)
    assert proc2.returncode == 0, f"stderr={proc2.stderr!r}"
    log = (project / ".janitor" / "logs" / "pre-compact-handoff.log").read_text(encoding="utf-8")
    assert "debounced" in log, "positive control failed — the auto firing must have debounced"
    stamp = json.loads((sd / "precompact-last-trigger.json").read_text(encoding="utf-8"))
    assert stamp["trigger"] == "auto", "the stamp must reflect the LAST firing, even when debounced"
    assert stamp["session_id"] == session


def test_hook_subprocess_manual_trigger_twice_writes_both_times(tmp_path: Path) -> None:
    """A manual /compact typed twice on purpose must write BOTH times — debounce
    applies ONLY to trigger=="auto" (coordinator addendum to TRDD-7MGJYLY5)."""
    project = tmp_path / "project"
    project.mkdir()
    _init_git_repo(project)
    payload = {
        "session_id": "sess-manual-1",
        "cwd": str(project),
        "transcript_path": "",
        "trigger": "manual",
        "hook_event_name": "PreCompact",
    }
    proc1 = _run_precompact(project, payload)
    assert proc1.returncode == 0, f"stderr={proc1.stderr!r}"
    proc2 = _run_precompact(project, payload)
    assert proc2.returncode == 0, f"stderr={proc2.stderr!r}"
    log = project / ".janitor" / "logs" / "pre-compact-handoff.log"
    text = log.read_text(encoding="utf-8")
    assert text.count("handoff written") == 2, "manual trigger must never be debounced"
    assert "debounced" not in text


def test_background_agents_caps_and_keeps_newest(tmp_path: Path) -> None:
    """`_background_agents` caps at `_BACKGROUND_AGENTS_MAX`, NEWEST first — a review
    finding: an uncapped, oldest-first list let a busy session's nudge exhaust its
    line budget on stale agents instead of the ones still likely to matter.

    `ts` increases with array position here (review finding: `pending_agents.pending()`
    preserves on-disk ARRAY order, it does not sort by `ts` — matching real usage,
    where `add()` appends, so array position IS chronological). Distinct, increasing
    `ts` values make this a genuine recency check, not one that would pass by array
    position alone if a future change made ordering `ts`-based instead."""
    hook = _hook()
    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    total = hook._BACKGROUND_AGENTS_MAX + 3
    entries = [
        {"agentId": f"agent-{i}", "description": f"task {i}", "ts": now - (total - i), "nudges": 0, "stopped": False}
        for i in range(total)
    ]
    (sd / "pending-agents.json").write_text(json.dumps(entries), encoding="utf-8")
    result = hook._background_agents(sd)
    assert len(result) == hook._BACKGROUND_AGENTS_MAX
    assert result[0]["agentId"] == f"agent-{total - 1}"  # newest first
    stale_id = "agent-0"
    assert all(a["agentId"] != stale_id for a in result), "the oldest agent must be dropped"
