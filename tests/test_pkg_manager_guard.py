"""Tests for the PreToolUse package-manager safety guard hook.

Closes GitHub issue #8. The hook lives at
scripts/hooks/pre-tool-pkg-guard.py and is invoked as a subprocess by
Claude Code's PreToolUse plumbing — tests run it the same way, with a
JSON payload on stdin and the JSON decision parsed off stdout.

Each test asserts the post-call permissionDecision and (when blocking)
that the reason names what was caught. The fixture isolates the
janitor's per-project state dir (CLAUDE_PROJECT_DIR=tmp) AND the global
state dir (JANITOR_GLOBAL_STATE_DIR=tmp) so the audit log never lands
in the user's real ~/.claude/.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "pre-tool-pkg-guard.py"

assert _HOOK.is_file(), f"hook not found at {_HOOK}"


def _run(payload: dict[str, Any], env_overrides: Optional[dict[str, str]] = None,
         tmp_path: Optional[Path] = None) -> tuple[int, dict[str, Any]]:
    """Invoke the hook as Claude Code would. Return (returncode, parsed_decision)."""
    env = os.environ.copy()
    if tmp_path is not None:
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        env["JANITOR_GLOBAL_STATE_DIR"] = str(tmp_path / "global")
    # Default: override OFF so deny is hard; threshold left at default 7200.
    env.pop("CLAUDE_PLUGIN_OPTION_PKG_MANAGER_HOOK_ALLOW_USER_OVERRIDE", None)
    env.pop("CLAUDE_PLUGIN_OPTION_PKG_MANAGER_MIN_RELEASE_AGE_MINUTES", None)
    if env_overrides:
        env.update(env_overrides)
    proc = subprocess.run(
        [str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    if not proc.stdout.strip():
        return proc.returncode, {}
    try:
        return proc.returncode, json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.returncode, {"raw": proc.stdout, "stderr": proc.stderr}


def _decision(out: dict[str, Any]) -> str:
    return out.get("hookSpecificOutput", {}).get("permissionDecision", "")


def _reason(out: dict[str, Any]) -> str:
    return out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


# ---------------------------------------------------------------------------
# Class A — Bash bypass flags
# ---------------------------------------------------------------------------

def test_classA_pnpm_no_frozen_lockfile_denied(tmp_path: Path) -> None:
    """pnpm --no-frozen-lockfile is blocked."""
    rc, out = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "pnpm install --no-frozen-lockfile"},
    }, tmp_path=tmp_path)
    assert rc == 0
    assert _decision(out) == "deny"
    assert "no-frozen-lockfile" in _reason(out).lower() or "frozen" in _reason(out).lower()


def test_classA_pnpm_no_verify_store_integrity_denied(tmp_path: Path) -> None:
    """pnpm --no-verify-store-integrity is blocked."""
    rc, out = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "pnpm install --no-verify-store-integrity"},
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"
    assert "store" in _reason(out).lower() or "verify" in _reason(out).lower()


def test_classA_pnpm_min_age_zero_denied(tmp_path: Path) -> None:
    """pnpm config set minimumReleaseAge 0 (below threshold) is blocked."""
    rc, out = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "pnpm config set minimumReleaseAge 0"},
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"
    assert "minimumReleaseAge" in _reason(out) or "minimum" in _reason(out).lower()


def test_classA_pnpm_min_age_above_threshold_allowed(tmp_path: Path) -> None:
    """Raising pnpm minimumReleaseAge above threshold is allowed (hardening)."""
    rc, out = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "pnpm config set minimumReleaseAge 10080"},
    }, tmp_path=tmp_path)
    assert rc == 0 and _decision(out) == ""  # silent pass


def test_classA_npm_no_integrity_denied(tmp_path: Path) -> None:
    """npm install --no-integrity is blocked."""
    rc, out = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "npm install --no-integrity"},
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"


def test_classA_npm_audit_level_none_denied(tmp_path: Path) -> None:
    """Lowering npm audit-level to 'none' is blocked."""
    rc, out = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "npm config set audit-level none"},
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"
    assert "audit-level" in _reason(out)


def test_classA_bun_no_verify_denied(tmp_path: Path) -> None:
    """bun install --no-verify is blocked."""
    rc, out = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "bun install --no-verify"},
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"
    assert "verify" in _reason(out).lower() or "bun" in _reason(out).lower()


def test_classA_corepack_disable_denied(tmp_path: Path) -> None:
    """corepack disable is blocked (removes packageManager pinning)."""
    rc, out = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "corepack disable"},
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"


def test_classA_chained_command_still_caught(tmp_path: Path) -> None:
    """A bypass flag inside a chained `cd … && pnpm …` is still caught."""
    rc, out = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "cd /tmp && pnpm install --no-frozen-lockfile"},
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"


def test_classA_multiline_continuation_still_caught(tmp_path: Path) -> None:
    """Backslash-newline continuation does not evade the regex (whitespace normalised)."""
    rc, out = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "pnpm install \\\n  --no-frozen-lockfile"},
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"


def test_classA_safe_command_passes(tmp_path: Path) -> None:
    """A plain `pnpm install` (no bypass flag) passes silently."""
    rc, out = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "pnpm install"},
    }, tmp_path=tmp_path)
    assert rc == 0 and _decision(out) == ""


def test_classA_unrelated_command_passes(tmp_path: Path) -> None:
    """An unrelated command (ls) is a pure pass-through."""
    rc, out = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la /tmp"},
    }, tmp_path=tmp_path)
    assert rc == 0 and _decision(out) == ""


# ---------------------------------------------------------------------------
# Class B — config-file diff edits
# ---------------------------------------------------------------------------

def test_classB_npmrc_lower_min_release_age_denied(tmp_path: Path) -> None:
    """Editing .npmrc to lower minimum-release-age below threshold is blocked."""
    npmrc = tmp_path / ".npmrc"
    npmrc.write_text("minimum-release-age=10080\ntrust-policy=no-downgrade\n", encoding="utf-8")
    rc, out = _run({
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(npmrc),
            "old_string": "minimum-release-age=10080",
            "new_string": "minimum-release-age=60",
        },
        "cwd": str(tmp_path),
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"
    assert "minimum-release-age" in _reason(out)


def test_classB_npmrc_remove_trust_policy_denied(tmp_path: Path) -> None:
    """Removing trust-policy from .npmrc is blocked."""
    npmrc = tmp_path / ".npmrc"
    npmrc.write_text("trust-policy=no-downgrade\nminimum-release-age=10080\n", encoding="utf-8")
    rc, out = _run({
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(npmrc),
            "old_string": "trust-policy=no-downgrade\n",
            "new_string": "",
        },
        "cwd": str(tmp_path),
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"


def test_classB_npmrc_audit_level_lowered_denied(tmp_path: Path) -> None:
    """Lowering audit-level to 'info' is blocked."""
    npmrc = tmp_path / ".npmrc"
    npmrc.write_text("audit-level=moderate\n", encoding="utf-8")
    rc, out = _run({
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(npmrc),
            "old_string": "audit-level=moderate",
            "new_string": "audit-level=info",
        },
        "cwd": str(tmp_path),
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"


def test_classB_package_json_pnpm_age_lowered_denied(tmp_path: Path) -> None:
    """Lowering package.json#pnpm.minimumReleaseAge is blocked."""
    pjson = tmp_path / "package.json"
    pjson.write_text(json.dumps({
        "name": "x",
        "pnpm": {"minimumReleaseAge": 10080, "trustPolicy": "no-downgrade",
                 "blockExoticSubdeps": True},
    }, indent=2), encoding="utf-8")
    rc, out = _run({
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(pjson),
            "content": json.dumps({
                "name": "x",
                "pnpm": {"minimumReleaseAge": 60, "trustPolicy": "no-downgrade",
                         "blockExoticSubdeps": True},
            }, indent=2),
        },
        "cwd": str(tmp_path),
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"
    assert "minimumReleaseAge" in _reason(out)


def test_classB_package_json_blockExoticSubdeps_disabled_denied(tmp_path: Path) -> None:
    """Setting package.json#pnpm.blockExoticSubdeps from true → false is blocked."""
    pjson = tmp_path / "package.json"
    pjson.write_text(json.dumps({"pnpm": {"blockExoticSubdeps": True}}), encoding="utf-8")
    rc, out = _run({
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(pjson),
            "content": json.dumps({"pnpm": {"blockExoticSubdeps": False}}),
        },
        "cwd": str(tmp_path),
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"


def test_classB_yarnrc_enable_scripts_true_denied(tmp_path: Path) -> None:
    """Setting .yarnrc.yml enableScripts: true (was false) is blocked."""
    y = tmp_path / ".yarnrc.yml"
    y.write_text("enableScripts: false\n", encoding="utf-8")
    rc, out = _run({
        "tool_name": "Write",
        "tool_input": {"file_path": str(y), "content": "enableScripts: true\n"},
        "cwd": str(tmp_path),
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"


def test_classB_bunfig_verify_removed_denied(tmp_path: Path) -> None:
    """Removing [install].verify=true from bunfig.toml is blocked."""
    b = tmp_path / "bunfig.toml"
    b.write_text("[install]\nverify = true\n", encoding="utf-8")
    rc, out = _run({
        "tool_name": "Write",
        "tool_input": {"file_path": str(b), "content": "[install]\nfrozen = true\n"},
        "cwd": str(tmp_path),
    }, tmp_path=tmp_path)
    assert _decision(out) == "deny"


def test_classB_safe_edit_allowed(tmp_path: Path) -> None:
    """An edit that does NOT weaken any guarded key passes silently."""
    npmrc = tmp_path / ".npmrc"
    npmrc.write_text("save-exact=true\nminimum-release-age=10080\n", encoding="utf-8")
    rc, out = _run({
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(npmrc),
            "old_string": "save-exact=true",
            "new_string": "save-exact=true\nfund=false",
        },
        "cwd": str(tmp_path),
    }, tmp_path=tmp_path)
    assert rc == 0 and _decision(out) == ""


def test_classB_unrelated_file_passes(tmp_path: Path) -> None:
    """An edit to a non-package-manager file is a pure pass-through."""
    f = tmp_path / "README.md"
    f.write_text("hello\n", encoding="utf-8")
    rc, out = _run({
        "tool_name": "Edit",
        "tool_input": {"file_path": str(f), "old_string": "hello", "new_string": "hi"},
        "cwd": str(tmp_path),
    }, tmp_path=tmp_path)
    assert rc == 0 and _decision(out) == ""


def test_classB_raising_age_allowed(tmp_path: Path) -> None:
    """RAISING minimum-release-age (hardening) is allowed."""
    npmrc = tmp_path / ".npmrc"
    npmrc.write_text("minimum-release-age=7200\n", encoding="utf-8")
    rc, out = _run({
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(npmrc),
            "old_string": "minimum-release-age=7200",
            "new_string": "minimum-release-age=20160",  # 14 days
        },
        "cwd": str(tmp_path),
    }, tmp_path=tmp_path)
    assert rc == 0 and _decision(out) == ""


# ---------------------------------------------------------------------------
# Override knob + threshold knob
# ---------------------------------------------------------------------------

def test_override_downgrades_deny_to_ask(tmp_path: Path) -> None:
    """With override on, a Class A block becomes 'ask' (user confirms each)."""
    rc, out = _run(
        {"tool_name": "Bash", "tool_input": {"command": "pnpm install --no-frozen-lockfile"}},
        env_overrides={"CLAUDE_PLUGIN_OPTION_PKG_MANAGER_HOOK_ALLOW_USER_OVERRIDE": "true"},
        tmp_path=tmp_path,
    )
    assert _decision(out) == "ask"


def test_custom_threshold_relaxes_block(tmp_path: Path) -> None:
    """Lowering the threshold knob unblocks a previously-too-low value."""
    rc, out = _run(
        {"tool_name": "Bash", "tool_input": {"command": "pnpm config set minimumReleaseAge 60"}},
        env_overrides={"CLAUDE_PLUGIN_OPTION_PKG_MANAGER_MIN_RELEASE_AGE_MINUTES": "30"},
        tmp_path=tmp_path,
    )
    assert rc == 0 and _decision(out) == ""  # 60 > 30 → allowed


# ---------------------------------------------------------------------------
# Audit log + ungated tools
# ---------------------------------------------------------------------------

def test_block_writes_audit_log(tmp_path: Path) -> None:
    """Every deny appends a line to pkg-manager-guard.log under global state."""
    _run(
        {"tool_name": "Bash", "tool_input": {"command": "pnpm install --no-frozen-lockfile"}},
        tmp_path=tmp_path,
    )
    log = tmp_path / "global" / "pkg-manager-guard.log"
    assert log.is_file()
    content = log.read_text(encoding="utf-8")
    assert "ClassA" in content
    assert "Bash" in content
    assert "no-frozen-lockfile" in content


def test_other_tools_pass_through(tmp_path: Path) -> None:
    """Tools the hook does not handle (Read, Grep, etc.) are pure pass-through."""
    rc, out = _run({"tool_name": "Read", "tool_input": {"file_path": "/etc/hosts"}}, tmp_path=tmp_path)
    assert rc == 0 and _decision(out) == ""


def test_malformed_input_silent_allow(tmp_path: Path) -> None:
    """Malformed JSON on stdin → silent allow (don't accidentally block everything)."""
    proc = subprocess.run(
        [str(_HOOK)],
        input="not json",
        capture_output=True,
        text=True,
        env={**os.environ, "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "g")},
        timeout=10,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""
