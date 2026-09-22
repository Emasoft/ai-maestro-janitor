"""`scripts/summarize_previous_session.py` under its REAL PEP-723 runtime (TRDD-RAEGS1D5).

WHY THIS FILE EXISTS SEPARATELY FROM `test_summarize_previous_session.py`: that file imports
the script in-process, inside the venv pytest itself runs in — every dependency the venv has
installed is on `sys.path`, whether or not it is declared in the script's own PEP-723 header.
In production this script is invoked as `uv run --script --quiet <path>` with the PROJECT'S
OWN venv nowhere on `PATH` (SessionStart hooks run outside it); `uv` then builds an ephemeral
env from ONLY the header's `requires-python` (no `dependencies = [...]`, i.e. stdlib-only). An
accidental `import` of a third-party module anywhere in this script's own import chain —
`external_clear`, `external_handoff_clear`, `handoff_files`, `jev_compaction_lane`, `state`, or
anything THEY import — would raise `ModuleNotFoundError`/`ImportError` there and only there;
the venv-hosted test cannot see it because the venv always has the dependency installed. This
test proves the boundary by actually crossing it: a real `uv run --script` subprocess, a `PATH`
that has `uv` and a system `python3` but not this repo's `.venv`, and a fresh `HOME`/project
dir carrying a tiny previous-session transcript for the script to find and hand to a stubbed
`jev_compact.py` (the one PEP-723-declared-dependency process this lane deliberately delegates
to — see `tests/test_jev_boundary.py` and the module docstring of
`scripts/summarize_previous_session.py`).
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "summarize_previous_session.py"

_ARGV_RECORD_NAME = "jev_compact_argv.txt"

_STUB_JEV_COMPACT = """#!/usr/bin/env python3
import sys
from pathlib import Path
argv = sys.argv
if "--out" in argv:
    out = Path(argv[argv.index("--out") + 1])
    out.write_text(
        "# Compacted context (Jev compaction)\\ntranscript: stub\\n\\n## Kept items\\nstub\\n",
        encoding="utf-8",
    )
    # Discriminates which jev_compact.py actually ran: the lane must exec the tmp plugin
    # root's copy (resolved from CLAUDE_PLUGIN_ROOT), never this repo's own real
    # scripts/jev_compact.py via __file__ -- record OUR argv and OUR resolved path so the
    # test can prove that from outside this subprocess.
    out.with_name("jev_compact_argv.txt").write_text(
        repr(argv) + "\\n" + str(Path(__file__).resolve()) + "\\n", encoding="utf-8",
    )
sys.exit(0)
"""

_PREV_TRANSCRIPT = [
    {"message": {"role": "user", "content": [{"type": "text", "text": "do the thing"}]}},
    {"message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}},
]


def _non_venv_path_dirs() -> list[str] | None:
    """Dirs carrying a real `uv` and a real `python3`/`python`, neither inside THIS repo's own
    `.venv` — the whole point being a PATH that cannot resolve the project's own dependencies,
    only what the script's PEP-723 header + `uv` itself provide. `None` when either is absent
    (caller skips rather than fails — this is an environment precondition, not a code defect)."""
    uv_bin = shutil.which("uv")
    if not uv_bin:
        return None
    # `shutil.which` only ever returns the FIRST PATH match — on a dev machine that is
    # routinely this repo's own activated `.venv/bin/python3`, which is exactly the thing
    # this test must NOT hand to the subprocess. Walk every PATH dir instead, so a `.venv`
    # entry ahead of the system interpreter is skipped rather than causing a false skip.
    python_bin = None
    for raw_dir in os.environ.get("PATH", "").split(os.pathsep):
        if not raw_dir or ".venv" in raw_dir or raw_dir.startswith(str(_REPO_ROOT)):
            continue
        for name in ("python3", "python"):
            candidate = Path(raw_dir) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                python_bin = str(candidate)
                break
        if python_bin:
            break
    if not python_bin:
        return None
    return list(dict.fromkeys([str(Path(uv_bin).parent), str(Path(python_bin).parent)]))


@pytest.mark.xdist_group("jev-compaction-runtime-boundary")
def test_summarize_previous_session_runs_stdlib_only_under_uv_run(tmp_path: Path) -> None:
    """Real `uv run --script` subprocess, real (stubbed-jev_compact) end to end: exit 0, the
    compacted artifact lands under the tmp project's `.janitor/state/`, and stderr carries no
    `ModuleNotFoundError`/`ImportError` — the one failure mode a venv-hosted test cannot see.
    The property proven is that the lane's imports resolve under the PEP-723 runtime without
    the project venv or user site-packages, and that the lane execs the stub `jev_compact.py`
    resolved from `CLAUDE_PLUGIN_ROOT`, never the real one via its own `__file__`."""
    path_dirs = _non_venv_path_dirs()
    if path_dirs is None:
        pytest.skip("uv (and a non-.venv python3/python) not found on PATH")

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    plugin_root = tmp_path / "plugin"

    # The stub `jev_compact.py`, at the path `jev_compaction_lane.run_compact` execs BY PATH —
    # `<CLAUDE_PLUGIN_ROOT>/scripts/jev_compact.py`. Nothing else under `plugin_root` is needed:
    # the real script resolves ITS OWN sibling imports from `Path(__file__).resolve().parent`
    # (this repo's real `scripts/`), never from `CLAUDE_PLUGIN_ROOT` — that env var only feeds
    # this one subprocess path (see `summarize_previous_session.py`'s own `PLUGIN_ROOT`).
    stub_path = plugin_root / "scripts" / "jev_compact.py"
    stub_path.parent.mkdir(parents=True, exist_ok=True)
    stub_path.write_text(_STUB_JEV_COMPACT, encoding="utf-8")
    stub_path.chmod(stub_path.stat().st_mode | stat.S_IEXEC)

    # `cold_cache_compact.newest_transcript` resolves the transcript dir as
    # `HOME/.claude/projects/<slug>/*.jsonl`, slug = every non-alnum char of the RESOLVED
    # project dir dashed (`memory_scopes.project_slug`, mirrored here so this file stays
    # boundary-only and imports nothing from `scripts/lib`).
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(project_dir.resolve()))
    transcripts_dir = home_dir / ".claude" / "projects" / slug
    transcripts_dir.mkdir(parents=True)
    prev = transcripts_dir / "11111111-2222-3333-4444-555555555555.jsonl"
    prev.write_text("\n".join(json.dumps(x) for x in _PREV_TRANSCRIPT) + "\n", encoding="utf-8")

    env = {
        "PATH": os.pathsep.join(path_dirs),
        "HOME": str(home_dir),
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "CLAUDE_CODE_SESSION_ID": "new-session",
        # A user-site package (e.g. a stray PyYAML install) must not be able to mask a
        # missing PEP-723 dependency declaration — the real production PATH has no user
        # site-packages either, and this test exists to catch exactly this gap.
        "PYTHONNOUSERSITE": "1",
    }
    if os.environ.get("TMPDIR"):
        env["TMPDIR"] = os.environ["TMPDIR"]

    proc = subprocess.run(
        ["uv", "run", "--script", "--quiet", str(_SCRIPT)],
        env=env, capture_output=True, text=True, timeout=180,
    )

    assert "ModuleNotFoundError" not in proc.stderr, proc.stderr
    assert "ImportError" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "SUMMARY_READY" in proc.stdout, proc.stdout

    artifacts = list((project_dir / ".janitor" / "state").glob("jev-compacted-*.md"))
    assert artifacts, "expected a jev-compacted-*.md artifact under .janitor/state"
    assert artifacts[0].read_text(encoding="utf-8").strip()

    # Discriminate which jev_compact.py actually ran: the lane must resolve the plugin root
    # from CLAUDE_PLUGIN_ROOT (the tmp copy), never from its own `__file__` (this repo's real
    # scripts/jev_compact.py, and its real control-dir stamp, must never be touched).
    record_path = artifacts[0].with_name(_ARGV_RECORD_NAME)
    assert record_path.is_file(), f"stub jev_compact.py never ran (no {record_path})"
    argv_line, resolved_line = record_path.read_text(encoding="utf-8").splitlines()
    # Parse the recorded argv structurally (not a substring match) so a coincidental
    # "compact" appearing elsewhere in argv (e.g. inside a tmp_path directory name) can't
    # produce a false pass.
    recorded_argv = ast.literal_eval(argv_line)
    assert "compact" in recorded_argv, recorded_argv
    recorded_path = Path(resolved_line)
    assert recorded_path.is_relative_to(plugin_root.resolve()), (
        f"jev_compact.py ran from outside the tmp plugin root: {recorded_path}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
