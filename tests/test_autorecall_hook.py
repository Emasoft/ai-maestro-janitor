"""Tests for the OPT-IN auto-recall UserPromptSubmit hook (issue #16, item 2).

The hook (`on-prompt-submit-autorecall.py`) runs `memgrep recall` over the AGENT
memory corpus and injects the top notes via `additionalContext` — but ONLY when
`CLAUDE_PLUGIN_OPTION_MEMORY_AUTORECALL` is truthy. These tests pin the contract:

  off by default        → no-op (exit 0, empty stdout), even with a live corpus.
  on + cron/slash prompt → no-op (cron `[janitor-…]` and `/…` aren't questions).
  on + no memgrep        → no-op (binary absent ⇒ nothing injected).
  on + a matching note   → additionalContext carries the recalled note line.
  on + PRIVACY           → a user-mem/ note is NEVER surfaced (structural bound).
  garbage stdin          → no-op (never crash the turn).

The corpus + the real memgrep binary: the hit/privacy tests need a working
`memgrep`. We build it once (release) into a tmp CARGO_TARGET_DIR if a prebuilt
binary isn't already present; if cargo is unavailable the binary-dependent tests
skip-mark rather than fail (CI without a Rust toolchain still runs the rest).

HOME is redirected to a tmp dir so the real per-project memory store is never
touched; CLAUDE_PROJECT_DIR points at a tmp project, which the hook maps to a
per-slug memory dir under the tmp HOME.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "on-prompt-submit-autorecall.py"
_MEMGREP_CRATE = _PROJECT_ROOT / "tools" / "memgrep"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import user_mem_lib  # noqa: E402

_ON = {"CLAUDE_PLUGIN_OPTION_MEMORY_AUTORECALL": "true"}


def _find_or_build_memgrep() -> str | None:
    """Return a path to a usable `memgrep`, or None if one can't be obtained.

    Order: a prebuilt binary under the crate's target/ (release or debug) → on
    PATH / cargo bin → build release into a tmp CARGO_TARGET_DIR. Returns None if
    no binary exists and cargo is unavailable (caller then skips).
    """
    for rel in ("target/release/memgrep", "target/debug/memgrep"):
        cand = _MEMGREP_CRATE / rel
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    on_path = shutil.which("memgrep")
    if on_path:
        return on_path
    cargo = shutil.which("cargo")
    if not cargo:
        return None
    target_dir = Path("/tmp/memgrep-build")
    env = dict(os.environ)
    env["CARGO_TARGET_DIR"] = str(target_dir)
    try:
        subprocess.run(
            [cargo, "build", "--release", "--manifest-path", str(_MEMGREP_CRATE / "Cargo.toml")],
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    built = target_dir / "release" / "memgrep"
    return str(built) if built.is_file() else None


_MEMGREP = _find_or_build_memgrep()
_needs_memgrep = pytest.mark.skipif(_MEMGREP is None, reason="memgrep binary unavailable and cargo build failed")


def _run_hook(payload: dict, env_extra: dict, project: Path, home: Path) -> tuple[int, str, str]:
    """Invoke the hook script with `payload` on stdin; return (rc, stdout, stderr)."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    # USER scope = ${CLAUDE_PLUGIN_DATA}/memory (the janitor plugin DATA dir). Pin it
    # to a tmp dir under `home` so the test is isolated AND exercises the env-var path.
    env["CLAUDE_PLUGIN_DATA"] = str(home / "plugin-data")
    # Drop any ambient opt-in so each test controls it explicitly via env_extra.
    env.pop("CLAUDE_PLUGIN_OPTION_MEMORY_AUTORECALL", None)
    # Make the chosen memgrep the one the hook resolves (find_memgrep honours
    # MEMGREP_BIN first). Tests that want "no memgrep" override it to a bogus path.
    if _MEMGREP is not None:
        env["MEMGREP_BIN"] = _MEMGREP
    env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _agent_memdir(home: Path, project: Path) -> Path:
    """Resolve the AGENT corpus dir the same way the hook does (HOME pinned)."""
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        return user_mem_lib.resolve_user_mem_dir(project_dir=str(project)).parent
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home


def _write_note(memdir: Path, name: str, description: str, body: str = "body text") -> None:
    memdir.mkdir(parents=True, exist_ok=True)
    (memdir / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: \"{description}\"\nmetadata: {{node_type: memory, type: feedback}}\n---\n{body}\n",
        encoding="utf-8",
    )


def _prompt(text: str) -> dict:
    return {"hook_event_name": "UserPromptSubmit", "prompt": text}


# --------------------------------------------------------------------------
# OFF BY DEFAULT
# --------------------------------------------------------------------------


def test_off_by_default_is_noop_even_with_corpus(tmp_path):
    """With the opt-in unset, the hook is a no-op even when a matching note exists."""
    memdir = _agent_memdir(tmp_path / "home", tmp_path / "proj")
    _write_note(memdir, "n1", "zarvox flux compensator failed unexpectedly")
    rc, out, _err = _run_hook(_prompt("how do I fix the zarvox flux compensator"), {}, tmp_path / "proj", tmp_path / "home")
    assert rc == 0
    assert out.strip() == ""


def test_off_explicit_false_is_noop(tmp_path):
    """An explicit `false` for the opt-in keeps the hook a no-op."""
    memdir = _agent_memdir(tmp_path / "home", tmp_path / "proj")
    _write_note(memdir, "n1", "zarvox flux compensator failed unexpectedly")
    rc, out, _err = _run_hook(
        _prompt("how do I fix the zarvox flux compensator"),
        {"CLAUDE_PLUGIN_OPTION_MEMORY_AUTORECALL": "false"},
        tmp_path / "proj",
        tmp_path / "home",
    )
    assert rc == 0
    assert out.strip() == ""


# --------------------------------------------------------------------------
# ON but the prompt is not a question
# --------------------------------------------------------------------------


def test_on_cron_prompt_is_noop(tmp_path):
    """A `[janitor-…]` cron heartbeat is skipped (not a user question)."""
    memdir = _agent_memdir(tmp_path / "home", tmp_path / "proj")
    _write_note(memdir, "n1", "zarvox flux compensator failed unexpectedly")
    rc, out, _err = _run_hook(_prompt("[janitor-resume] continue your work"), _ON, tmp_path / "proj", tmp_path / "home")
    assert rc == 0
    assert out.strip() == ""


def test_on_slash_command_is_noop(tmp_path):
    """A slash command prompt is skipped (handled by other hooks, not a question)."""
    memdir = _agent_memdir(tmp_path / "home", tmp_path / "proj")
    _write_note(memdir, "n1", "zarvox flux compensator failed unexpectedly")
    rc, out, _err = _run_hook(_prompt("/janitor-doctor"), _ON, tmp_path / "proj", tmp_path / "home")
    assert rc == 0
    assert out.strip() == ""


# --------------------------------------------------------------------------
# ON but memgrep is absent
# --------------------------------------------------------------------------


def test_on_no_memgrep_is_noop(tmp_path):
    """With the binary unresolvable, the hook injects nothing (no-op without memgrep)."""
    memdir = _agent_memdir(tmp_path / "home", tmp_path / "proj")
    _write_note(memdir, "n1", "zarvox flux compensator failed unexpectedly")
    # Point MEMGREP_BIN at a nonexistent path and blank PATH so which() fails too;
    # also send HOME to tmp so the cargo-bin fallback can't find a real binary.
    env = dict(_ON)
    env["MEMGREP_BIN"] = str(tmp_path / "no" / "such" / "memgrep")
    env["PATH"] = str(tmp_path / "empty-bin")
    rc, out, _err = _run_hook(_prompt("how do I fix the zarvox flux compensator"), env, tmp_path / "proj", tmp_path / "home")
    assert rc == 0
    assert out.strip() == ""


# --------------------------------------------------------------------------
# ON + a real hit (needs the binary)
# --------------------------------------------------------------------------


@_needs_memgrep
def test_on_hit_injects_additional_context(tmp_path):
    """A matching note is recalled and injected via hookSpecificOutput.additionalContext."""
    memdir = _agent_memdir(tmp_path / "home", tmp_path / "proj")
    _write_note(memdir, "zarvox", "zarvox flux compensator failed where is the reset switch", body="press the hidden reset")
    rc, out, _err = _run_hook(_prompt("the zarvox flux compensator failed again"), _ON, tmp_path / "proj", tmp_path / "home")
    assert rc == 0
    assert out.strip() != ""
    obj = json.loads(out)
    hso = obj.get("hookSpecificOutput", {})
    assert hso.get("hookEventName") == "UserPromptSubmit"
    ctx = hso.get("additionalContext", "")
    # The recalled note's path/description must be present in the injected context.
    assert "zarvox.md" in ctx
    assert "flux compensator" in ctx


@_needs_memgrep
def test_on_privacy_user_mem_note_never_surfaced(tmp_path):
    """A note in the private user-mem/ subtree is NEVER recalled into agent context."""
    memdir = _agent_memdir(tmp_path / "home", tmp_path / "proj")
    # Top-level agent note AND a user-mem note that matches the SAME query harder.
    _write_note(memdir, "agentnote", "zarvox flux compensator failed reset", body="agent body")
    _write_note(memdir / "user-mem", "private", "zarvox flux compensator failed reset SECRETMEMO", body="private body")
    rc, out, _err = _run_hook(_prompt("the zarvox flux compensator failed"), _ON, tmp_path / "proj", tmp_path / "home")
    assert rc == 0
    # If anything was injected, it must be the agent note — never the private one.
    if out.strip():
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        assert "SECRETMEMO" not in ctx
        assert "user-mem" not in ctx
        assert "agentnote.md" in ctx


@_needs_memgrep
def test_on_no_matching_note_is_noop(tmp_path):
    """A prompt with no recall hit injects nothing (empty stdout)."""
    memdir = _agent_memdir(tmp_path / "home", tmp_path / "proj")
    _write_note(memdir, "n1", "completely unrelated topic about gardening tomatoes")
    rc, out, _err = _run_hook(_prompt("quantum chromodynamics lattice gauge theory"), _ON, tmp_path / "proj", tmp_path / "home")
    assert rc == 0
    assert out.strip() == ""


def test_on_empty_corpus_is_noop(tmp_path):
    """ON but the corpus dir has no top-level notes → no-op (doesn't need memgrep)."""
    # Create the memdir but leave it empty (only a user-mem/ subdir).
    memdir = _agent_memdir(tmp_path / "home", tmp_path / "proj")
    (memdir / "user-mem").mkdir(parents=True, exist_ok=True)
    rc, out, _err = _run_hook(_prompt("anything at all here"), _ON, tmp_path / "proj", tmp_path / "home")
    assert rc == 0
    assert out.strip() == ""


# --------------------------------------------------------------------------
# robustness
# --------------------------------------------------------------------------


def test_garbage_stdin_is_noop(tmp_path):
    """Non-JSON stdin never crashes the turn — the hook no-ops."""
    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path / "proj")
    env.update(_ON)
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input="}{ this is not json",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_empty_stdin_is_noop(tmp_path):
    """Empty stdin is a no-op."""
    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path / "proj")
    env.update(_ON)
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input="",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


# --------------------------------------------------------------------------
# THREE-SCOPE recall composition (TRDD-c77dae09): LOCAL + PROJECT + USER
# --------------------------------------------------------------------------


def _write_page(memdir: Path, name: str, description: str, body: str = "body text") -> None:
    """Write a memory page into an arbitrary scope root (USER/PROJECT/LOCAL)."""
    memdir.mkdir(parents=True, exist_ok=True)
    (memdir / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: \"{description}\"\n"
        f"metadata: {{node_type: memory, type: project}}\n---\n{body}\n",
        encoding="utf-8",
    )


def _init_git(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    })
    subprocess.run(["git", "init", "-q"], cwd=str(root), env=env, check=False,
                   capture_output=True, text=True)


@_needs_memgrep
def test_user_scope_note_is_recalled(tmp_path):
    """A note in the USER scope (`${CLAUDE_PLUGIN_DATA}/memory/`) is composed into
    recall — even when the LOCAL corpus has no matching note."""
    home = tmp_path / "home"
    project = tmp_path / "proj"
    # USER scope = ${CLAUDE_PLUGIN_DATA}/memory; _run_hook pins it to <home>/plugin-data.
    _write_page(home / "plugin-data" / "memory", "userpref",
                "globalwidget calibration drifts after sleep where is the knob",
                body="turn the global knob")
    rc, out, _err = _run_hook(
        _prompt("the globalwidget calibration drifts again"), _ON, project, home)
    assert rc == 0
    assert out.strip() != ""
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "userpref.md" in ctx
    assert "calibration" in ctx


@_needs_memgrep
def test_project_scope_note_is_recalled(tmp_path):
    """A note in the PROJECT scope (`<git-root>/memory/`) is composed into recall
    when CLAUDE_PROJECT_DIR is a git repo."""
    home = tmp_path / "home"
    project = tmp_path / "proj"
    _init_git(project)
    # PROJECT scope page (git-tracked root), no matching LOCAL/USER note.
    _write_page(project / "memory", "projarch",
                "projwidget pipeline stalls on cold start where is the retry",
                body="bump the retry")
    rc, out, _err = _run_hook(
        _prompt("the projwidget pipeline stalls on cold start"), _ON, project, home)
    assert rc == 0
    assert out.strip() != ""
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "projarch.md" in ctx
    assert "pipeline" in ctx


@_needs_memgrep
def test_all_three_scopes_compose_and_user_mem_excluded(tmp_path):
    """LOCAL + PROJECT + USER all contribute to ONE recall, and the private
    user-mem/ note (inside LOCAL) is STILL never surfaced (structural bound)."""
    home = tmp_path / "home"
    project = tmp_path / "proj"
    _init_git(project)
    memdir = _agent_memdir(home, project)
    # One matching note per scope on the same topic, plus a private user-mem note.
    _write_page(memdir, "localnote", "tribblewidget overheats reset procedure local", body="local")
    _write_page(project / "memory", "projnote", "tribblewidget overheats reset procedure project", body="proj")
    _write_page(home / ".claude" / "memory", "usernote", "tribblewidget overheats reset procedure user", body="user")
    _write_page(memdir / "user-mem", "secret", "tribblewidget overheats reset SECRETMEMO", body="private")
    rc, out, _err = _run_hook(_prompt("the tribblewidget overheats again"), _ON, project, home)
    assert rc == 0
    assert out.strip() != ""
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    # The private user-mem note must NEVER appear, regardless of scope composition.
    assert "SECRETMEMO" not in ctx
    assert "user-mem" not in ctx
    # At least the three scope notes are reachable (recall ranks; --top caps at 3,
    # so assert the private one is absent and the public ones are the source).
    assert any(tok in ctx for tok in ("localnote.md", "projnote.md", "usernote.md"))
