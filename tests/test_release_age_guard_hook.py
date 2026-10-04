"""Tests for the release-age observation-window guard hook (TRDD-BUR8AW77).

The hook lives at scripts/hooks/pre-tool-release-age-guard.py and is invoked
as a subprocess by Claude Code's PreToolUse plumbing — tests run it the same
way, with a JSON payload on stdin and the JSON decision parsed off stdout.

No mocked HTTP: each test spins a real local HTTP server serving canned
registry JSON, and the hook reaches it through the
CLAUDE_PLUGIN_OPTION_RELEASE_AGE_REGISTRY_BASE seam ({base}/pypi/…,
{base}/npm/…, …). That exercises the hook's real urllib path end to end.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Generator, Optional

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "pre-tool-release-age-guard.py"

assert _HOOK.is_file(), f"hook not found at {_HOOK}"


# --- local registry server (real HTTP, canned JSON) -------------------------

# Computed at import: a fixed date ages out of the hook's release-age window and the tests rot (TRDD-BUR8AW77).
_NOWISH = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
_AGED = "2024-01-01T00:00:00.000000Z"  # years old

_REGISTRY: dict[str, Any] = {
    "pypi": {
        "requests/json": {
            "info": {"version": "2.34.2"},
            "urls": [{"upload_time_iso_8601": _AGED}],
            "releases": {
                "2.34.2": [{"upload_time_iso_8601": _AGED}],
                "9.9.9": [{"upload_time_iso_8601": _NOWISH}],
            },
        },
        "brand-new-pkg/json": {
            "info": {"version": "1.0.0"},
            "urls": [{"upload_time_iso_8601": _NOWISH}],
            "releases": {"1.0.0": [{"upload_time_iso_8601": _NOWISH}]},
        },
    },
    "npm": {
        "left-pad": {"dist-tags": {"latest": "1.3.0"}, "time": {"1.3.0": _AGED, "created": _AGED}},
        "fresh-npm-pkg": {"dist-tags": {"latest": "2.0.0"}, "time": {"2.0.0": _NOWISH}},
    },
    "crates": {
        "serde": {"crate": {"max_stable_version": "1.0.229"}, "versions": [{"num": "1.0.229", "created_at": _AGED}]},
        "fresh-crate": {"crate": {"max_stable_version": "0.1.0"}, "versions": [{"num": "0.1.0", "created_at": _NOWISH}]},
    },
    "rubygems": {
        "rails/versions/latest.json": {"version": "8.1.4"},
        "rails/versions/8.1.4.json": {"version": "8.1.4", "version_created_at": _AGED},
        "fresh-gem/versions/latest.json": {"version": "0.2.0"},
        "fresh-gem/versions/0.2.0.json": {"version": "0.2.0", "version_created_at": _NOWISH},
    },
    "go": {
        "golang.org/x/tools/@latest": {"Version": "v0.50.0", "Time": _AGED},
        "example.com/fresh/@v/v1.0.1.info": {"Version": "v1.0.1", "Time": _NOWISH},
    },
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — stdlib API
        path = self.path.lstrip("/")
        for family, table in _REGISTRY.items():
            if path.startswith(f"{family}/"):
                key = path[len(family) + 1:]
                body = table.get(key)
                if body is None:
                    self.send_response(404)
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(body).encode())
                return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature; silence the test log
        pass


@pytest.fixture()
def registry_base() -> Generator[str, Any, Any]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


# --- subprocess harness ------------------------------------------------------


def _run(
    payload: dict[str, Any],
    registry_base: str,
    env_overrides: Optional[dict[str, str]] = None,
) -> tuple[int, dict[str, Any]]:
    env = os.environ.copy()
    for key in (
        "CLAUDE_PLUGIN_OPTION_RELEASE_AGE_GUARD_ENABLED",
        "CLAUDE_PLUGIN_OPTION_RELEASE_AGE_OBSERVATION_MINUTES",
        "CLAUDE_PLUGIN_OPTION_RELEASE_AGE_HOOK_ALLOW_USER_OVERRIDE",
    ):
        env.pop(key, None)
    env["CLAUDE_PLUGIN_OPTION_RELEASE_AGE_REGISTRY_BASE"] = registry_base
    if env_overrides:
        env.update(env_overrides)
    proc = subprocess.run(
        [str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,  # scaled suite-wide by conftest's seam (TRDD-7NSRD8OV)
    )
    if not proc.stdout.strip():
        return proc.returncode, {}
    try:
        return proc.returncode, json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.returncode, {"raw": proc.stdout, "stderr": proc.stderr}


def _decision(out: dict[str, Any]) -> str:
    return out.get("hookSpecificOutput", {}).get("permissionDecision", "")


def _context(out: dict[str, Any]) -> str:
    return out.get("hookSpecificOutput", {}).get("additionalContext", "")


def _reason(out: dict[str, Any]) -> str:
    return out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


BASH_PAYLOAD = {"tool_name": "Bash", "tool_input": {"command": "PLACEHOLDER"}}


# --- early release → warning -------------------------------------------------


def test_pypi_early_release_warns(registry_base: str) -> None:
    """A 0-day-ish PyPI install emits an additionalContext warning naming the package."""
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "pip install brand-new-pkg"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0
    assert _decision(out) == ""  # NEVER blocking
    ctx = _context(out)
    assert "brand-new-pkg" in ctx
    assert "release-age-guard" in ctx
    assert "WARNING" in ctx


def test_pypi_pinned_early_version_warns(registry_base: str) -> None:
    """pip install pkg==9.9.9 resolves the pinned version's upload time."""
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "pip install requests==9.9.9"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0
    assert "requests 9.9.9" in _context(out)


def test_npm_early_release_warns(registry_base: str) -> None:
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "npm install fresh-npm-pkg"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0
    assert "fresh-npm-pkg" in _context(out)


def test_cargo_early_release_warns(registry_base: str) -> None:
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "cargo install fresh-crate"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0
    assert "fresh-crate" in _context(out)


def test_gem_early_release_warns(registry_base: str) -> None:
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "gem install fresh-gem"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0
    assert "fresh-gem" in _context(out)


def test_go_early_release_warns(registry_base: str) -> None:
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "go install example.com/fresh@v1.0.1"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0
    assert "example.com/fresh" in _context(out)


def test_uv_install_early_release_warns(registry_base: str) -> None:
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "uv pip install brand-new-pkg"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0
    assert "brand-new-pkg" in _context(out)


# --- well-aged → nothing ------------------------------------------------------


def test_pypi_well_aged_silent(registry_base: str) -> None:
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "pip install requests"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0 and out == {}


def test_npm_well_aged_silent(registry_base: str) -> None:
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "npm install left-pad"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0 and out == {}


def test_cargo_well_aged_silent(registry_base: str) -> None:
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "cargo install serde"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0 and out == {}


def test_gem_well_aged_silent(registry_base: str) -> None:
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "gem install rails"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0 and out == {}


# --- non-installers and non-Bash → nothing -----------------------------------


def test_non_installer_command_ignored(registry_base: str) -> None:
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "ls -la && git status"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0 and out == {}


def test_installer_like_word_not_matched(registry_base: str) -> None:
    """`pipx` inside a longer word must not fire the pip/pipx family."""
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "cat README.md | grep pipinstalling"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0 and out == {}


def test_non_bash_tool_ignored(registry_base: str) -> None:
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x.py", "old_string": "a", "new_string": "b"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0 and out == {}


def test_local_install_skipped_no_lookup(registry_base: str) -> None:
    """The owner's named exception: user-authored local paths never hit a registry."""
    for cmd in (
        "pip install -e ./my-own-lib",
        "uv pip install /Users/me/mine.whl",
        "npm install /home/me/mylib",
        "cargo install --path ./mycrate",
    ):
        payload = {**BASH_PAYLOAD, "tool_input": {"command": cmd}}
        rc, out = _run(payload, registry_base)
        assert rc == 0 and out == {}, cmd


# --- escalation (the git-safety "ask" mechanism) ------------------------------


def test_override_knob_escalates_to_ask(registry_base: str) -> None:
    """With the override knob on, an early release asks the user to confirm (OTP step)."""
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "pip install brand-new-pkg"}}
    rc, out = _run(payload, registry_base, {"CLAUDE_PLUGIN_OPTION_RELEASE_AGE_HOOK_ALLOW_USER_OVERRIDE": "true"})
    assert rc == 0
    assert _decision(out) == "ask"
    assert "brand-new-pkg" in _reason(out)


def test_never_denies(registry_base: str) -> None:
    """Owner verbatim: it must be only a warning, not blocking — no path may emit deny."""
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "pip install brand-new-pkg"}}
    for overrides in (
        None,
        {"CLAUDE_PLUGIN_OPTION_RELEASE_AGE_HOOK_ALLOW_USER_OVERRIDE": "true"},
        {"CLAUDE_PLUGIN_OPTION_RELEASE_AGE_OBSERVATION_MINUTES": "999999999"},
    ):
        rc, out = _run(payload, registry_base, overrides)
        assert rc == 0
        assert _decision(out) != "deny"


# --- knobs and fail-open ------------------------------------------------------


def test_disabled_hook_silent(registry_base: str) -> None:
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "pip install brand-new-pkg"}}
    rc, out = _run(payload, registry_base, {"CLAUDE_PLUGIN_OPTION_RELEASE_AGE_GUARD_ENABLED": "false"})
    assert rc == 0 and out == {}


def test_registry_outage_fails_open(registry_base: str) -> None:
    """A package the local registry 404s on (== an outage / unknown pkg) → silent allow."""
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "pip install totally-unknown-pkg"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0 and out == {}



def test_get_json_refuses_non_http_scheme(tmp_path: Path) -> None:
    """A file: URL holding valid JSON is refused (it was readable before the scheme check)."""
    import importlib.util

    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps({"ok": True}))
    spec = importlib.util.spec_from_file_location("release_age_guard_under_test", _HOOK)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._get_json(payload.as_uri()) is None


def test_malformed_input_silent_allow() -> None:
    proc = subprocess.run(
        [str(_HOOK)],
        input="not json",
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=10,  # scaled suite-wide by conftest's seam (TRDD-7NSRD8OV)
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_shell_chained_installer_matched(registry_base: str) -> None:
    """`cd x && pip install fresh` still recognizes the installer (no operator evasion)."""
    payload = {**BASH_PAYLOAD, "tool_input": {"command": "cd /tmp && pip install brand-new-pkg && ls"}}
    rc, out = _run(payload, registry_base)
    assert rc == 0
    assert "brand-new-pkg" in _context(out)
