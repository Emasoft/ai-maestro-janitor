"""Tests for the ai-context-poisoning detector.

The detector lives at scripts/detectors/ai-context-poisoning.py and audits
node_modules/ + site-packages/ for packages whose source writes to an
agent-context file (CLAUDE.md, .cursorrules, AGENTS.md, .claude/*).

Each test spins up a tmp project tree with fake node_modules / venv
shapes and runs the detector as a subprocess (the dispatch.py invocation
surface). CLAUDE_PROJECT_DIR is set to the tmp_path so per-project
state stays isolated and a stale cache from a sibling test cannot leak.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "ai-context-poisoning.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"


def _run(
    project_dir: Path,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env.pop("CLAUDE_PLUGIN_OPTION_AI_CONTEXT_POISONING_ENABLED", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60,
    )


def _seed_npm_pkg(
    project_dir: Path, name: str, source_contents: str, *,
    scope: str | None = None, source_filename: str = "index.js",
) -> Path:
    """Materialise a fake `node_modules/<name>/<source_filename>` (or
    `node_modules/@scope/<name>/<source_filename>`) with the given JS body.
    """
    base = project_dir / "node_modules"
    if scope:
        pkg_dir = base / scope / name
    else:
        pkg_dir = base / name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "package.json").write_text(
        json.dumps({"name": (f"{scope}/{name}" if scope else name), "version": "1.0.0"}),
        encoding="utf-8",
    )
    (pkg_dir / source_filename).write_text(source_contents, encoding="utf-8")
    return pkg_dir


def _seed_py_pkg(
    project_dir: Path, pkg_name: str, source_contents: str, *,
    source_filename: str = "__init__.py",
) -> Path:
    """Materialise a fake `.venv/lib/python3.X/site-packages/<pkg>/<source>`
    with the given Python body."""
    sp = project_dir / ".venv" / "lib" / "python3.12" / "site-packages"
    pkg_dir = sp / pkg_name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / source_filename).write_text(source_contents, encoding="utf-8")
    return pkg_dir


# ---------- Silent on non-installable trees ------------------------------


def test_silent_on_empty_project(tmp_path: Path) -> None:
    """No node_modules + no venv → silent."""
    (tmp_path / "README.md").write_text("hi", encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_when_node_modules_clean(tmp_path: Path) -> None:
    """A real node_modules tree with no agent-context writes → silent."""
    _seed_npm_pkg(
        tmp_path, "lodash",
        "module.exports = function noop () { return null; };",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_when_site_packages_clean(tmp_path: Path) -> None:
    """A real site-packages tree with no agent-context writes → silent."""
    _seed_py_pkg(
        tmp_path, "requests",
        "def get(url):\n    pass\n",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- Detection — node_modules -------------------------------------


def test_fires_on_npm_writefilesync_claude_md(tmp_path: Path) -> None:
    """fs.writeFileSync(".../CLAUDE.md", ...) in a package's installed
    source fires."""
    _seed_npm_pkg(
        tmp_path, "evil-pkg",
        'const fs = require("fs");\n'
        'fs.writeFileSync("CLAUDE.md", "ignore all previous");\n',
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[ai-context-poisoning]" in r.stdout
    assert "npm:evil-pkg" in r.stdout


def test_fires_on_npm_appendfile_cursorrules(tmp_path: Path) -> None:
    """fs.appendFile(".cursorrules", payload) fires (was a regex blind
    spot before the (?:Sync)? grouping fix)."""
    _seed_npm_pkg(
        tmp_path, "rules-injector",
        'const fs = require("fs");\n'
        'fs.appendFile(".cursorrules", evil, () => {});\n',
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[ai-context-poisoning]" in r.stdout
    assert "npm:rules-injector" in r.stdout


def test_fires_on_npm_chained_path_join(tmp_path: Path) -> None:
    """fs.writeFileSync(path.join(home, ".cursorrules"), ...) — inner
    parens used to defeat the [^)] character class before the [^;\\n] fix."""
    _seed_npm_pkg(
        tmp_path, "chained-evil",
        'const fs = require("fs");\n'
        'const path = require("path");\n'
        'fs.writeFileSync(path.join(home, ".cursorrules"), payload);\n',
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[ai-context-poisoning]" in r.stdout
    assert "npm:chained-evil" in r.stdout


def test_fires_on_scoped_npm_pkg(tmp_path: Path) -> None:
    """A scoped package @scope/name is detected with its full name."""
    _seed_npm_pkg(
        tmp_path, "stealer",
        'require("fs").writeFileSync("AGENTS.md", evil);\n',
        scope="@evil",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[ai-context-poisoning]" in r.stdout
    assert "npm:@evil/stealer" in r.stdout


def test_dotenv_loader_is_allowlisted(tmp_path: Path) -> None:
    """`dotenv` legitimately writes to dotfiles. The allowlist check
    keeps it silent even though its source matches the pattern."""
    _seed_npm_pkg(
        tmp_path, "dotenv",
        'fs.writeFileSync(".aiderrules", evil);\n',
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- Detection — site-packages ------------------------------------


def test_fires_on_py_pathlib_write_text_to_claude_md(tmp_path: Path) -> None:
    """A Python package whose source writes to CLAUDE.md fires."""
    _seed_py_pkg(
        tmp_path, "stealer_py",
        "from pathlib import Path\n"
        'Path("CLAUDE.md").write_text("override")\n',
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[ai-context-poisoning]" in r.stdout
    assert "py:stealer_py" in r.stdout


def test_fires_on_py_open_w_mode_cursorrules(tmp_path: Path) -> None:
    """open(".cursorrules", "w").write(...) in installed python source fires."""
    _seed_py_pkg(
        tmp_path, "open_writer",
        'open(".cursorrules", "w").write("ignore previous")\n',
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[ai-context-poisoning]" in r.stdout
    assert "py:open_writer" in r.stdout


def test_python_dotenv_is_allowlisted(tmp_path: Path) -> None:
    """`python-dotenv` legitimately writes dotfiles — allowlisted."""
    _seed_py_pkg(
        tmp_path, "python-dotenv",  # pip → site-packages dir usually `dotenv`
        'open(".env", "w").write("x")\n',
    )
    # Most real installs put python-dotenv under `dotenv/` but the canonical
    # PyPI name is python-dotenv. Either should be allowlisted.
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- Dedupe / heartbeat hygiene -----------------------------------


def test_silent_on_second_run_when_nothing_changed(tmp_path: Path) -> None:
    """Detector caches a content-signature; identical second run is silent."""
    _seed_npm_pkg(
        tmp_path, "evil-pkg",
        'fs.writeFileSync("CLAUDE.md", evil);\n',
    )
    first = _run(tmp_path)
    assert "[ai-context-poisoning]" in first.stdout
    second = _run(tmp_path)
    assert second.returncode == 0
    assert second.stdout == ""


# ---------- Self-scan guard ----------------------------------------------


def test_self_scan_guard_silences_detector(tmp_path: Path) -> None:
    """When the project root has a plugin.json declaring this is the
    janitor itself, the detector is silent even with a malicious package."""
    plug_dir = tmp_path / ".claude-plugin"
    plug_dir.mkdir()
    (plug_dir / "plugin.json").write_text(
        json.dumps({"name": "ai-maestro-janitor", "version": "0.5.0"}),
        encoding="utf-8",
    )
    _seed_npm_pkg(
        tmp_path, "evil-pkg",
        'fs.writeFileSync("CLAUDE.md", evil);\n',
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_self_scan_override_re_enables(tmp_path: Path) -> None:
    """`CLAUDE_PLUGIN_ALLOW_SELF_SCAN=1` overrides the guard so the
    detector can audit itself when explicitly invoked for testing."""
    plug_dir = tmp_path / ".claude-plugin"
    plug_dir.mkdir()
    (plug_dir / "plugin.json").write_text(
        json.dumps({"name": "ai-maestro-janitor", "version": "0.5.0"}),
        encoding="utf-8",
    )
    _seed_npm_pkg(
        tmp_path, "evil-pkg",
        'fs.writeFileSync("CLAUDE.md", evil);\n',
    )
    r = _run(tmp_path, env_overrides={"CLAUDE_PLUGIN_ALLOW_SELF_SCAN": "1"})
    assert r.returncode == 0
    assert "[ai-context-poisoning]" in r.stdout
    assert "npm:evil-pkg" in r.stdout


# ---------- Feature flag --------------------------------------------------


def test_disabled_by_env_flag(tmp_path: Path) -> None:
    """Setting the disable env-var skips all detection."""
    _seed_npm_pkg(
        tmp_path, "evil-pkg",
        'fs.writeFileSync("CLAUDE.md", evil);\n',
    )
    r = _run(
        tmp_path,
        env_overrides={"CLAUDE_PLUGIN_OPTION_AI_CONTEXT_POISONING_ENABLED": "0"},
    )
    assert r.returncode == 0
    assert r.stdout == ""
