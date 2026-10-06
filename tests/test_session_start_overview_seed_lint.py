"""The SessionStart overview stub must pass the janitor's own `memgrep lint` (janitor#333/#334/#335).

Runs the REAL `_seed_overview_if_absent` for both non-PROJECT scopes into one corpus, then the
in-repo memgrep binary over it — no mocks. Needs `cargo build --release --manifest-path
scripts/memgrep/Cargo.toml` first (fails, never skips, when the binary is missing).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MEMGREP = REPO / "scripts" / "memgrep" / "target" / "release" / "memgrep"
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "lib"))


def _hook():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location(
        "on_session_start_under_test", REPO / "scripts" / "hooks" / "on-session-start.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seeded_overview_stubs_pass_memgrep_lint_at_authoring_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seed LOCAL and USER stubs into one corpus; lint reports zero findings. The phrase floor is
    the authoring floor (15): a stub the plugin writes today is new authoring, not legacy."""
    import memory_bridge  # noqa: PLC0415
    import state  # noqa: PLC0415

    assert MEMGREP.is_file(), f"build memgrep first: {MEMGREP}"
    project = tmp_path / "demo"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    hook = _hook()
    for scope in ("LOCAL", "USER"):
        root = corpus / scope.lower()
        root.mkdir()
        hook._seed_overview_if_absent(state, memory_bridge, scope, root)
        assert list(root.glob("*-overview.md")), f"{scope} stub was not written"
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEMGREP_")}
    # Hold the stub to the authoring floor (janitor#334), not the lenient legacy lint floor.
    env["MEMGREP_LINT_MIN_PAGE_PHRASES"] = "15"
    res = subprocess.run(  # noqa: S603
        [str(MEMGREP), "lint", str(corpus / "local"), str(corpus / "user")],
        capture_output=True, text=True, env=env, check=False,
    )
    out = res.stdout + res.stderr
    assert res.returncode == 0 and "0 finding(s)" in out, out
