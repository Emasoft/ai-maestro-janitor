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
against a real state.py subprocess, in both a no-git and a git-repo cwd. POSIX
shell only (the rule's recipe is `bash`, skipped on win32). A future
project-anchor rung added to state.py ahead of the git rung (see the module
docstring above) is invisible to this test until it is extended with a fixture
that actually seeds that anchor — the recipe and state.py can only diverge on
a rung neither side's current inputs ever trigger.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the rule's recipe is POSIX shell")

_TESTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TESTS_DIR.parent
_LIB_DIR = _PROJECT_ROOT / "scripts" / "lib"
# The repo's own shipped source, not whatever happens to be installed under
# ~/.claude/rules/ on this machine (that copy may lag a plugin update/reinstall).
_RULE_FILE = _PROJECT_ROOT / "rules" / "janitor-heartbeat-protocol.md"
# The pre-fix recipe (before commit ac39cf13 added the `2>/dev/null || pwd -P`
# fallback) — proves the recipe/state.py comparison can actually fail: in a
# no-git folder this diverges from state.state_dir(), which is exactly the bug
# ac39cf13 fixed. Written as a full `STATE_DIR=...` statement (see _run_recipe)
# to match the shape the current recipe extraction now produces.
_OLD_RECIPE = 'STATE_DIR="$(git -C "$PWD" rev-parse --show-toplevel)/.janitor/state"'


def _extract_recipe() -> str:
    """Pull the STATE_DIR bash recipe out of the rule file, verbatim.

    Commit f0eb0848 moved the recipe out of the heartbeat table cell (where the
    regex used to match an inline "else `<expr>`" span) into a fenced ```bash
    code block below the table, introduced by the line "`STATE_DIR` composition
    referenced by the memory-chore row above:". Extract that block's content
    instead of the old inline form.
    """
    text = _RULE_FILE.read_text()
    match = re.search(
        r"composition referenced by the memory-chore row above:\s*```bash\n(.*?)\n```",
        text,
        re.DOTALL,
    )
    if match is None:
        pytest.fail(
            "could not find the '...composition referenced by the memory-chore row "
            f"above:\\n```bash ... ```' block in {_RULE_FILE} — the rule's wording "
            "or structure changed; update this test's extraction regex"
        )
    recipe = match.group(1)
    # Shape check anchored at the START of the capture (not just "somewhere in it") so a
    # stray line sandwiched between the intro sentence and the real recipe inside the
    # fence — which the non-greedy `.*?` would still capture and "match" — fails loudly
    # instead of silently comparing junk (review finding: a substring-anywhere check is
    # weaker than the old regex's `startswith` guard).
    if not recipe.startswith("STATE_DIR=") or ".janitor/state" not in recipe:
        pytest.fail(
            f"extracted STATE_DIR recipe {recipe!r} does not look like a "
            "'STATE_DIR=....janitor/state' assignment — the rule's code block changed; "
            "update this test's extraction regex"
        )
    return recipe


def _clean_env(home: Path, ceiling: Path) -> dict[str, str]:
    # Allowlist, not os.environ copy + pop: this suite's own pre-push git hook runs
    # pytest with GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE already set for the janitor
    # repo, and inheriting them makes `git -C <tmp>` answer for the janitor repo
    # instead of the temp one — silently invalidating the no-git/subfolder cases
    # this test exists to check. Only PATH (to find `git`/`bash`) and a fresh HOME
    # survive; no GIT_* or CLAUDE_* variable is ever passed through.
    # GIT_CEILING_DIRECTORIES stops git from walking above the temp area even if
    # some other real repo happens to be an ancestor of tmp_path on this machine.
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "GIT_CEILING_DIRECTORIES": str(ceiling),
    }


def _run_recipe(recipe: str, cwd: Path, env: dict[str, str]) -> str:
    # `recipe` is a full `STATE_DIR=...` bash statement (assignment + `||` fallback),
    # containing `$(...)` command substitution, which the suite's sandbox_guard
    # (tests/sandbox_guard.py) refuses outright in a bare `bash -c "..."` argv — it
    # cannot statically prove no hidden write happens inside the substitution. Writing
    # it to a script FILE under tmp_path and running `bash <script>` is the guard's own
    # sanctioned escape hatch (a script the test itself wrote into tmp is trusted at
    # the test's own level; see _classify_shell). Run the statement, then echo the
    # variable it sets — the recipe no longer IS an expression to echo directly (it
    # moved from an inline `else `<expr>`` span to a standalone assignment statement
    # when the rule's recipe relocated into a fenced code block, commit f0eb0848).
    script = cwd / "recipe.sh"
    script.write_text(f'{recipe}\necho "$STATE_DIR"\n')
    result = subprocess.run(
        ["bash", str(script)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"recipe subprocess failed: {result.stderr}"
    output = result.stdout.strip()
    assert output, f"recipe subprocess printed nothing: {result.stderr}"
    return output


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
    )
    assert result.returncode == 0, f"state.state_dir() subprocess failed: {result.stderr}"
    output = result.stdout.strip()
    assert output, f"state.state_dir() subprocess printed nothing: {result.stderr}"
    return output


def test_no_git_folder_matches_state_dir(tmp_path: Path) -> None:
    """No CLAUDE_PROJECT_DIR, no .git: the rule's recipe and state.state_dir() must agree."""
    home = tmp_path / "home"
    home.mkdir()
    env = _clean_env(home, ceiling=tmp_path.resolve().parent)

    # With GIT_CEILING_DIRECTORIES set, tmp_path can no longer resolve into a git
    # repo above it — assert that directly instead of silently skipping when it
    # does, which would hide a broken ceiling.
    probe = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert probe.returncode != 0, (
        f"{tmp_path} is unexpectedly inside a git repo despite the ceiling: {probe.stdout.strip()}"
    )

    recipe = _extract_recipe()
    recipe_result = _run_recipe(recipe, cwd=tmp_path, env=env)
    state_result = _run_state_dir(cwd=tmp_path, env=env)

    assert Path(recipe_result).resolve() == Path(state_result).resolve()
    assert Path(recipe_result).resolve() == (tmp_path / ".janitor" / "state").resolve()


def test_old_recipe_diverges_from_state_dir_in_no_git_folder(tmp_path: Path) -> None:
    """Proves the comparison can fail: the pre-ac39cf13 recipe disagrees with state.state_dir()."""
    home = tmp_path / "home"
    home.mkdir()
    env = _clean_env(home, ceiling=tmp_path.resolve().parent)

    old_result = _run_recipe(_OLD_RECIPE, cwd=tmp_path, env=env)
    state_result = _run_state_dir(cwd=tmp_path, env=env)

    assert Path(old_result).resolve() != Path(state_result).resolve()


def test_git_repo_subfolder_matches_state_dir(tmp_path: Path) -> None:
    """Inside a git repo (run from a subfolder), both resolve to <repo-toplevel>/.janitor/state."""
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    env = _clean_env(home, ceiling=tmp_path.resolve().parent)
    # `cwd=repo`, not a `-C <path>` argument — the suite's sandbox_guard classifies a git
    # verb by where the PROCESS runs, and only trusts `init` on a path already under
    # tmp_path. Same allowlisted `env` as everything else in this test: a bare os.environ
    # (the default when `env=` is omitted) would let a leaked GIT_DIR make `init` write
    # into the *janitor* repo's own .git instead of `repo/.git`, which then makes the
    # git-repo case silently behave like the no-git case below.
    subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True)
    subfolder = repo / "sub" / "dir"
    subfolder.mkdir(parents=True)

    recipe = _extract_recipe()

    recipe_result = _run_recipe(recipe, cwd=subfolder, env=env)
    state_result = _run_state_dir(cwd=subfolder, env=env)

    assert Path(recipe_result).resolve() == Path(state_result).resolve()
    assert Path(recipe_result).resolve() == (repo / ".janitor" / "state").resolve()
