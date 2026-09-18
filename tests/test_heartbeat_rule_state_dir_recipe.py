"""Pin the heartbeat rule's prose STATE_DIR recipe to scripts/lib/state.py's real lookup.

rules/janitor-heartbeat-protocol.md re-implements state.py's `_resolve_project_root`
(CLAUDE_PROJECT_DIR, then a caller override, then `git rev-parse --show-toplevel`,
then cwd) as a bash one-liner in its `[janitor-memory-*]` row, because a Claude
session composes STATE_DIR itself before spawning the memory agent — it cannot
import state.py. Commit ac39cf13 fixed the recipe's else-branch to fall back to
cwd (`2>/dev/null || pwd -P`) after a real bug: a no-git workspace root made the
rule refuse to spawn while state.py itself resolved fine. Nothing enforces that
the two stay in lock-step; a future edit to either side (e.g. a new project-anchor
rung planned ahead of git) can silently re-diverge and reproduce the exact same
bug. This test extracts the recipe verbatim from the rule file (never re-typed,
so wording drift breaks extraction loudly) and runs it as a real bash subprocess
against a real state.py subprocess, in both a no-git and a git-repo cwd.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TESTS_DIR.parent
_LIB_DIR = _PROJECT_ROOT / "scripts" / "lib"
# The repo's own shipped source, not whatever happens to be installed under
# ~/.claude/rules/ on this machine (that copy may lag a plugin update/reinstall).
_RULE_FILE = _PROJECT_ROOT / "rules" / "janitor-heartbeat-protocol.md"


def _extract_recipe() -> str:
    """Pull the else-branch STATE_DIR bash expression out of the rule file, verbatim."""
    text = _RULE_FILE.read_text()
    match = re.search(r"composes `STATE_DIR`.*?else `([^`]+)`", text, re.DOTALL)
    if match is None:
        pytest.fail(
            "could not find the '...composes `STATE_DIR`... else `<recipe>`' row in "
            f"{_RULE_FILE} — the rule's wording changed; update this test's extraction regex"
        )
    recipe = match.group(1)
    # Non-greedy `.*?` finds the FIRST backtick-quoted span after "else " — correct only
    # while no OTHER backtick term sits between "composes `STATE_DIR`" and the real "else
    # `<recipe>`". A prose edit that inserts one (e.g. "else, when `git` is present, `...`")
    # would make the regex still MATCH, just the wrong span — a silent wrong-extraction, not
    # the loud failure the docstring promises. This shape check turns that into a loud one.
    if not recipe.startswith('"$('):
        pytest.fail(
            f"extracted STATE_DIR recipe {recipe!r} does not look like the expected "
            "'\"$(...)/.janitor/state\"' shape — the rule's prose around the else-branch "
            "changed; update this test's extraction regex"
        )
    return recipe


def _clean_env(home: Path) -> dict[str, str]:
    # Strip CLAUDE_PROJECT_DIR (real sessions may have it set) and point HOME at
    # a scratch dir so neither side of the comparison can touch the real ~/.claude.
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    env["HOME"] = str(home)
    return env


def _run_recipe(recipe: str, cwd: Path, env: dict[str, str]) -> str:
    # `recipe` is already a quoted bash expression (e.g. `"$(...)/.janitor/state"`) containing
    # `$(...)` command substitution, which the suite's sandbox_guard (tests/sandbox_guard.py)
    # refuses outright in a bare `bash -c "..."` argv — it cannot statically prove no hidden
    # write happens inside the substitution. Writing it to a script FILE under tmp_path and
    # running `bash <script>` is the guard's own sanctioned escape hatch (a script the test
    # itself wrote into tmp is trusted at the test's own level; see _classify_shell).
    script = cwd / "recipe.sh"
    script.write_text(f"echo {recipe}\n")
    result = subprocess.run(
        ["bash", str(script)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _run_state_dir(cwd: Path, env: dict[str, str]) -> str:
    code = (
        f"import sys; sys.path.insert(0, {str(_LIB_DIR)!r}); "
        "import state; print(state.state_dir())"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_no_git_folder_matches_state_dir(tmp_path: Path) -> None:
    """No CLAUDE_PROJECT_DIR, no .git: the rule's recipe and state.state_dir() must agree."""
    probe = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        pytest.skip(f"{tmp_path} is unexpectedly inside a git repo: {probe.stdout.strip()}")

    home = tmp_path / "home"
    home.mkdir()
    env = _clean_env(home)
    recipe = _extract_recipe()

    recipe_result = _run_recipe(recipe, cwd=tmp_path, env=env)
    state_result = _run_state_dir(cwd=tmp_path, env=env)

    assert Path(recipe_result).resolve() == Path(state_result).resolve()
    assert Path(recipe_result).resolve() == (tmp_path / ".janitor" / "state").resolve()


def test_git_repo_subfolder_matches_state_dir(tmp_path: Path) -> None:
    """Inside a git repo (run from a subfolder), both resolve to <repo-toplevel>/.janitor/state."""
    repo = tmp_path / "repo"
    repo.mkdir()
    # `cwd=repo`, not a `-C <path>` argument — the suite's sandbox_guard classifies a git
    # verb by where the PROCESS runs, and only trusts `init` on a path already under tmp_path.
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subfolder = repo / "sub" / "dir"
    subfolder.mkdir(parents=True)

    home = tmp_path / "home"
    home.mkdir()
    env = _clean_env(home)
    recipe = _extract_recipe()

    recipe_result = _run_recipe(recipe, cwd=subfolder, env=env)
    state_result = _run_state_dir(cwd=subfolder, env=env)

    assert Path(recipe_result).resolve() == Path(state_result).resolve()
    assert Path(recipe_result).resolve() == (repo / ".janitor" / "state").resolve()
