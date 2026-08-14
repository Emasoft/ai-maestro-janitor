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
    """Returns user+assistant TEXT turns newest-last; heartbeat / meta / tool / thinking excluded."""
    hook = _hook()
    tx = tmp_path / "t.jsonl"
    _write_jsonl(tx, [
        _umsg("first real question"),
        _amsg("first answer"),
        _tool_result_turn(),
        _thinking_turn(),
        _umsg("[janitor-heartbeat]\n/path/to/stub ... long cron prompt"),  # excluded
        _amsg("Clean — holding."),
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
