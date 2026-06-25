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
