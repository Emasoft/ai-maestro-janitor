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


GENERIC_FORMS = ("where do i start", "how does", "how to ", "replace this", "seeded by", "janitor#")


def test_seeded_overview_stubs_pass_memgrep_lint_with_honest_description(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seed LOCAL and USER stubs into one corpus; default lint reports zero findings, and the
    description stays small and free of generic questions (a padded stub outranks real pages)."""
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
    descs = []
    for scope in ("local", "user"):
        text = next((corpus / scope).glob("*-overview.md")).read_text(encoding="utf-8")
        desc = next(ln for ln in text.splitlines() if ln.startswith("description:"))
        descs.append(desc)
        phrases = [p for p in desc.removeprefix("description:").strip('" ').split(" / ") if p.strip()]
        assert 4 <= len(phrases) <= 6, phrases
        assert all(scope in p.lower() for p in phrases), phrases
        assert not [g for g in GENERIC_FORMS if g in desc.lower()], desc
    assert descs[0] != descs[1]
    # DEFAULT lint configuration: the stub meets the lint floor (4), not the authoring floor.
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEMGREP_")}
    res = subprocess.run(  # noqa: S603
        [str(MEMGREP), "lint", str(corpus / "local"), str(corpus / "user")],
        capture_output=True, text=True, env=env, check=False,
    )
    out = res.stdout + res.stderr
    assert res.returncode == 0 and "0 finding(s)" in out, out
