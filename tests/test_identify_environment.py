"""Tests for the /janitor-identify-environment backing script.

The detection functions read the real host, so the tests pin the parts that can
be driven deterministically: the sandbox-signal detection (env-driven), the
report shape, the JSON contract, and that a live run never crashes and returns a
sane result on this host.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "identify_environment.py"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


def _load():
    spec = importlib.util.spec_from_file_location("identify_environment_under_test", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sandboxing_empty_on_bare_host(monkeypatch):
    mod = _load()
    for var in ("KUBERNETES_SERVICE_HOST", "CODESPACES", "REMOTE_CONTAINERS",
                "DEVCONTAINER", "GITPOD_WORKSPACE_ID", "container", "APP_SANDBOX_CONTAINER_ID"):
        monkeypatch.delenv(var, raising=False)
    # The non-env markers (/.dockerenv, /proc/1/cgroup) are absent on a macOS bare
    # host; on a CI Linux host they may be present, so only assert the env path.
    signals = mod.detect_sandboxing()
    assert not any("$CODESPACES" in s for s in signals)


def test_sandboxing_detects_codespaces(monkeypatch):
    mod = _load()
    monkeypatch.setenv("CODESPACES", "true")
    assert any("Codespaces" in s and "$CODESPACES" in s for s in mod.detect_sandboxing())


def test_sandboxing_detects_devcontainer(monkeypatch):
    mod = _load()
    monkeypatch.setenv("REMOTE_CONTAINERS", "true")
    assert any("dev container" in s for s in mod.detect_sandboxing())


def test_detect_terminal_uses_forced_kind(monkeypatch):
    mod = _load()
    monkeypatch.setenv("JANITOR_FORCE_TERMINAL_KIND", "tmux")
    t = mod.detect_terminal()
    assert t["kind"] == "tmux"
    assert isinstance(t["in_ai_maestro_agent"], bool)


def test_detect_os_has_fields():
    mod = _load()
    o = mod.detect_os()
    assert o["system"] and o["arch"] and o["version"]


def test_gather_shape():
    mod = _load()
    info = mod.gather()
    for key in ("terminal", "ancestry", "tmux", "os", "filesystem", "sandboxing", "project_dir", "cwd"):
        assert key in info, f"missing key {key}"
    assert isinstance(info["ancestry"], list)
    assert isinstance(info["sandboxing"], list)


def test_render_contains_sections():
    mod = _load()
    out = mod._render(mod.gather())
    assert "Terminal/program" in out
    assert "OS:" in out
    assert "Filesystem" in out
    assert "Container/dev-box/sandbox" in out


# The live probe shells out to a dozen external tools (ifconfig, scutil, lsof, gh, security, …),
# so it is SLOW and its cost is dominated by the machine, not by this repo: measured 9.7 s cold and
# ~1.5 s warm on an idle box, and this test pays it TWICE. A 30 s cap was therefore ~3x the cold
# path on an idle machine and marginal on a loaded one — it went red once during a full-suite run
# that itself took 624 s against a usual ~270-360 s, i.e. the timeout fired on load, not on a
# defect. The cap exists to catch a HANG, and a hang is unbounded, not 40 s — so budget for the
# slowest honest run and keep the backstop meaningful.
_LIVE_PROBE_TIMEOUT_S = 120


def test_live_run_human_and_json():
    # A real subprocess run: must exit 0 and emit valid JSON with --json.
    human = subprocess.run(
        [sys.executable, str(_SCRIPT)], capture_output=True, text=True, timeout=_LIVE_PROBE_TIMEOUT_S
    )
    assert human.returncode == 0 and "## Environment" in human.stdout

    js = subprocess.run(
        [sys.executable, str(_SCRIPT), "--json"],
        capture_output=True,
        text=True,
        timeout=_LIVE_PROBE_TIMEOUT_S,
    )
    assert js.returncode == 0
    data = json.loads(js.stdout)
    assert data["terminal"]["kind"]  # non-empty label
    assert data["os"]["system"]
