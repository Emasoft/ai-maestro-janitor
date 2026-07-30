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


# ── janitor#110: capability, install-trigger and presence are DIFFERENT states ─
#
# The detector used to report all of them with the language and severity of the
# most alarming one, so `playwright` — whose `scripts` is EMPTY, and whose agent
# files are written only by an explicit `init-agents` command — was dispatched as
# a `critical` compromise and burned a full agent run to be verified false.
#
# These run as a PAIR so the fix cannot be "downgrade everything": the
# install-triggered package must still read as the serious case.

_WRITES_AGENT_FILE = (
    "const fs=require('fs');\n"
    "fs.writeFileSync('.claude/agents/planner.md', body);\n"
)


def _set_scripts(pkg_dir: Path, scripts: dict[str, str]) -> None:
    p = pkg_dir / "package.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["scripts"] = scripts
    p.write_text(json.dumps(data), encoding="utf-8")


def test_capability_without_install_hook_is_not_reported_as_install_time(tmp_path: Path) -> None:
    """The playwright shape: can write, but nothing runs it on install.

    `scripts: {}` means installing the package writes nothing, so the headline
    must not claim install-time behaviour and must say what the real control is.
    """
    pkg = _seed_npm_pkg(tmp_path, "playwrightish", _WRITES_AGENT_FILE)
    _set_scripts(pkg, {})
    out = _run(tmp_path).stdout

    assert "CAN write agent-context file" in out
    assert "none at install time" in out
    assert "AT INSTALL TIME" not in out
    assert "no install hook" in out, "the per-finding line must name the state too"
    assert "INVOCATION" in out, "a capability finding must point at the real control"


def test_install_hook_is_still_reported_as_the_serious_case(tmp_path: Path) -> None:
    """A postinstall that writes agent files IS the disclosed-attack shape.

    The load-bearing half: if this went quiet, the fix would have traded a false
    positive for a false negative on the state that actually matters.
    """
    pkg = _seed_npm_pkg(tmp_path, "evilish", _WRITES_AGENT_FILE)
    _set_scripts(pkg, {"postinstall": "node ./index.js"})
    out = _run(tmp_path).stdout

    assert "AT INSTALL TIME" in out
    assert "RUNS AT INSTALL via `postinstall`" in out
    assert "supply-chain attacks" in out


def test_every_install_hook_name_is_recognised(tmp_path: Path) -> None:
    """preinstall/install/prepare are triggers too — not just postinstall."""
    for hook in ("preinstall", "install", "prepare"):
        proj = tmp_path / hook
        proj.mkdir()
        pkg = _seed_npm_pkg(proj, "p", _WRITES_AGENT_FILE)
        _set_scripts(pkg, {hook: "node ./index.js"})
        out = _run(proj).stdout
        assert f"RUNS AT INSTALL via `{hook}`" in out, f"{hook} not recognised"


def test_unreadable_package_json_degrades_to_capability_not_critical(tmp_path: Path) -> None:
    """Unknown metadata must not be reported as an install trigger.

    Claiming a trigger we could not observe is the same overstatement the whole
    fix is about, so absence of evidence degrades DOWN, never up.
    """
    pkg = _seed_npm_pkg(tmp_path, "brokenmeta", _WRITES_AGENT_FILE)
    (pkg / "package.json").write_text("{ not json", encoding="utf-8")
    out = _run(tmp_path).stdout
    assert "none at install time" in out
    assert "AT INSTALL TIME" not in out
