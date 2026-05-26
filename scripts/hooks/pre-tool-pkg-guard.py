#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0",
# ]
# ///
"""PreToolUse guard against package-manager safety-knob bypasses.

Closes GitHub issue #8 — the user-scope guardrail Atai Barkai called for in
the art-template npm compromise thread: a hook that an agent (this Claude
instance or any other) cannot talk itself past when it would otherwise
silently lower minimumReleaseAge / disable signature verification / re-enable
postinstall scripts to "make a stuck install work".

The hook fires before every Bash/Edit/Write/NotebookEdit call. It either:
  * allows silently (the vast majority of calls — pass-through),
  * denies with a one-line reason naming the safer alternative AND the
    userConfig knob to relax it (default behavior), or
  * asks the user to confirm (when pkg_manager_hook_allow_user_override is
    on — the issue's documented escape hatch).

Two classes of violation, mirroring issue #8:

  Class A — bypass flags in Bash commands
  Regex-matched on the normalised command string (whitespace collapsed so
  line-continuations and tabs cannot evade the match). Covers pnpm, npm,
  yarn, bun, corepack. Examples: `pnpm install --no-frozen-lockfile`,
  `npm config set audit-level none`, `bun install --no-verify`.

  Class B — edits that weaken trust knobs
  Parses both the before-state (the file on disk) and the after-state
  (before-state with the Edit applied, or the Write content). Compares
  guarded keys per file type (.npmrc, package.json#pnpm,
  pnpm-workspace.yaml, .yarnrc.yml, bunfig.toml). Denies when a guarded
  key is lowered, removed, or set to an unsafe value — including a brand-
  new file written from scratch with an unsafe value (no "prior state"
  loophole).

Logging: every block goes to ~/.claude/janitor-global-state/pkg-manager-guard.log
(global so users can audit blocks across all sessions; same dir as the
daemon's audit log).

Performance: sub-100 ms p99 target — single-pass regex for Class A, one
file read + one parse for Class B.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import tomllib
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import state  # noqa: E402


# --- userConfig knobs -----------------------------------------------------

def _threshold_minutes() -> int:
    """Minimum-release-age threshold in MINUTES (pnpm's unit). Default 7200 = 5 days."""
    return state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_PKG_MANAGER_MIN_RELEASE_AGE_MINUTES"),
        7200,
    )


def _allow_override() -> bool:
    """When true, deny becomes ask (user confirms each block). Default false."""
    return state.is_truthy_env("CLAUDE_PLUGIN_OPTION_PKG_MANAGER_HOOK_ALLOW_USER_OVERRIDE", False)


# --- Class A — Bash bypass-flag regex matchers ----------------------------

# Each entry: (compiled regex, reason string). The regex is applied to the
# whitespace-normalised command string, so chained `cd … && pnpm …`,
# multi-line backslash continuations, and tabs cannot evade the match.

_BASH_BLOCKS: list[tuple[re.Pattern[str], str]] = [
    # pnpm
    (re.compile(r"\bpnpm\b.*\s--ignore-pnpmfile\b"),
     "pnpm --ignore-pnpmfile skips trusted-script / hook policies"),
    (re.compile(r"\bpnpm\b.*\s--no-frozen-lockfile\b"),
     "pnpm --no-frozen-lockfile permits lockfile drift (use a real lockfile update + commit)"),
    (re.compile(r"\bpnpm\b.*\s--no-verify-store-integrity\b"),
     "pnpm --no-verify-store-integrity disables store integrity check"),
    (re.compile(r"\bpnpm\b.*\s--no-min-release-age\b"),
     "pnpm --no-min-release-age disables the minimum-release-age safety net"),
    (re.compile(r"\bpnpm\b.*\s--ignore-scripts\s*=\s*false\b"),
     "pnpm --ignore-scripts=false re-enables postinstall script execution"),
    # pnpm config knobs — block setting trustPolicy / blockExoticSubdeps to anything;
    # block setting minimumReleaseAge to a literal value below threshold (we let
    # raising it through, since that is hardening, not weakening).
    (re.compile(r"\bpnpm\s+config\s+set\s+trustPolicy\b"),
     "pnpm config set trustPolicy changes a safety knob — edit .npmrc / package.json#pnpm via a reviewed diff"),
    (re.compile(r"\bpnpm\s+config\s+set\s+blockExoticSubdeps\b"),
     "pnpm config set blockExoticSubdeps changes a safety knob — edit the config file with a reviewed diff"),
    # npm
    (re.compile(r"\bnpm\b.*\s--no-(integrity|audit)\b"),
     "npm --no-integrity / --no-audit disables a safety check"),
    (re.compile(r"\bnpm\b.*\s--ignore-scripts\s*=\s*false\b"),
     "npm --ignore-scripts=false re-enables postinstall script execution"),
    (re.compile(r"\bnpm\s+config\s+set\s+audit-level\s+(none|info|low)\b"),
     "lowering npm audit-level below 'moderate' hides advisories"),
    # yarn
    (re.compile(r"\byarn\s+config\s+set\s+enableScripts\s+true\b"),
     "yarn enableScripts true re-enables postinstall script execution"),
    (re.compile(r"\byarn\b.*\s--network-timeout\s+0\b"),
     "yarn --network-timeout 0 disables the network-timeout safety"),
    # bun
    (re.compile(r"\bbun\s+install\b.*\s--no-(verify|frozen-lockfile)\b"),
     "bun install --no-verify / --no-frozen-lockfile disables a safety check"),
    (re.compile(r"\bbun\b.*\s--ignore-scripts\s*=\s*false\b"),
     "bun --ignore-scripts=false re-enables postinstall script execution"),
    # corepack
    (re.compile(r"\bcorepack\s+disable\b"),
     "corepack disable removes package-manager pinning"),
    (re.compile(r"\bcorepack\b.*\s--no-verify\b"),
     "corepack --no-verify skips integrity checks"),
]


def _check_pnpm_min_age(command: str, threshold: int) -> Optional[str]:
    """Block `pnpm config set minimumReleaseAge N` only when N < threshold."""
    m = re.search(r"\bpnpm\s+config\s+set\s+minimumReleaseAge\s+(\d+)\b", command)
    if not m:
        return None
    val = int(m.group(1))
    if val < threshold:
        return (f"pnpm config set minimumReleaseAge={val} below threshold {threshold} min "
                f"(pkg_manager_min_release_age_minutes) — would expose to fresh-publish attacks")
    return None


# --- Class B — config-file diff matchers ---------------------------------

def _parse_npmrc(text: str) -> dict[str, str]:
    """Minimal .npmrc parser — ini-style key=value, comments stripped.

    Good enough for our key set; we don't need full ini semantics
    (sections, multi-line values). Robust to extra whitespace + CRLF.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "//")):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip().lower()] = v.strip().strip('"').strip("'")
    return out


def _parse_json(text: str) -> dict[str, Any]:
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _parse_yaml(text: str) -> dict[str, Any]:
    try:
        v = yaml.safe_load(text)
        return v if isinstance(v, dict) else {}
    except yaml.YAMLError:
        return {}


def _parse_toml(text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}


def _as_int(v: Any) -> Optional[int]:
    """Coerce a config value to int — handles 7200, "7200", and "7200m" forms.

    Returns None when the value isn't sensibly numeric so callers can treat
    it as missing rather than as zero.
    """
    if isinstance(v, bool):
        return None  # JSON true/false would become 1/0 — skip
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        m = re.match(r"^\s*(\d+)\b", v)
        if m:
            return int(m.group(1))
    return None


def _check_npmrc_diff(before: str, after: str, threshold: int) -> Optional[str]:
    """Detect lowering / removal of guarded keys in an .npmrc-like file."""
    b = _parse_npmrc(before)
    a = _parse_npmrc(after)
    return _diff_kv(b, a, threshold,
                    age_keys=("minimum-release-age",),
                    trust_key="trust-policy",
                    block_exotic_key="block-exotic-subdeps",
                    audit_key="audit-level",
                    frozen_key="frozen-lockfile")


def _check_package_json_diff(before: str, after: str, threshold: int) -> Optional[str]:
    """package.json: only the `.pnpm` subtree carries our guarded knobs."""
    b = _parse_json(before).get("pnpm", {}) if isinstance(_parse_json(before).get("pnpm", {}), dict) else {}
    a = _parse_json(after).get("pnpm", {}) if isinstance(_parse_json(after).get("pnpm", {}), dict) else {}
    if not isinstance(b, dict):
        b = {}
    if not isinstance(a, dict):
        a = {}
    return _diff_kv(b, a, threshold,
                    age_keys=("minimumReleaseAge",),
                    trust_key="trustPolicy",
                    block_exotic_key="blockExoticSubdeps")


def _check_yaml_diff(before: str, after: str, threshold: int) -> Optional[str]:
    """pnpm-workspace.yaml uses the camelCase pnpm keys at top level."""
    b = _parse_yaml(before)
    a = _parse_yaml(after)
    return _diff_kv(b, a, threshold,
                    age_keys=("minimumReleaseAge",),
                    trust_key="trustPolicy",
                    block_exotic_key="blockExoticSubdeps")


def _check_yarnrc_diff(before: str, after: str, _threshold: int) -> Optional[str]:
    """yarn: enableScripts true is the dangerous transition; httpTimeout lowered too.

    `_threshold` is unused (yarn lacks an equivalent min-release-age knob)
    but the signature is shared with the other Class B checkers.
    """
    b = _parse_yaml(before)
    a = _parse_yaml(after)
    # enableScripts: false (or missing) → true is a weakening.
    b_es = bool(b.get("enableScripts", False))
    a_es = bool(a.get("enableScripts", False))
    if a_es and not b_es:
        return "yarn enableScripts true re-enables postinstall script execution (was false / unset)"
    # httpTimeout lowered (treat 0 as off).
    b_to = _as_int(b.get("httpTimeout"))
    a_to = _as_int(a.get("httpTimeout"))
    if a_to is not None and a_to == 0 and (b_to is None or b_to > 0):
        return "yarn httpTimeout 0 disables network-timeout safety"
    return None


def _check_toml_diff(before: str, after: str, _threshold: int) -> Optional[str]:
    """bunfig.toml / bun.toml: require [install].verify = true to stay set.

    `_threshold` is unused (bun has no min-release-age knob today) but the
    signature is shared with the other Class B checkers.
    """
    b = _parse_toml(before)
    a = _parse_toml(after)
    b_install = b.get("install", {}) if isinstance(b.get("install", {}), dict) else {}
    a_install = a.get("install", {}) if isinstance(a.get("install", {}), dict) else {}
    if not isinstance(b_install, dict):
        b_install = {}
    if not isinstance(a_install, dict):
        a_install = {}
    b_v = b_install.get("verify")
    a_v = a_install.get("verify")
    if b_v is True and a_v is not True:
        return "bun [install].verify removed/false — integrity check disabled"
    # New file with verify explicitly false is also bad.
    if a_v is False:
        return "bun [install].verify=false disables integrity checks"
    return None


def _diff_kv(
    b: dict[str, Any],
    a: dict[str, Any],
    threshold: int,
    *,
    age_keys: tuple[str, ...] = (),
    trust_key: Optional[str] = None,
    block_exotic_key: Optional[str] = None,
    audit_key: Optional[str] = None,
    frozen_key: Optional[str] = None,
) -> Optional[str]:
    """Generic key-walker shared by .npmrc / package.json#pnpm / YAML config."""
    # Minimum release age — lowered, removed (when previously safe), or
    # written from scratch below threshold.
    for ak in age_keys:
        a_val = _as_int(a.get(ak))
        b_val = _as_int(b.get(ak))
        # After is missing / unsafe but before was safe.
        if a_val is None and b_val is not None and b_val >= threshold:
            return f"{ak} removed (was {b_val} ≥ threshold {threshold})"
        if a_val is not None and a_val < threshold:
            note = f"was {b_val}" if b_val is not None else "previously unset"
            return f"{ak}={a_val} below threshold {threshold} ({note})"
    # Trust policy — anything other than no-downgrade is a weakening.
    if trust_key is not None:
        a_v = str(a.get(trust_key, "")).strip().lower() if trust_key in a else None
        b_v = str(b.get(trust_key, "")).strip().lower() if trust_key in b else None
        if b_v == "no-downgrade" and a_v != "no-downgrade":
            tail = a_v if a_v else "removed"
            return f"{trust_key} {tail!r} (was 'no-downgrade')"
        if a_v is not None and a_v not in ("no-downgrade", ""):
            return f"{trust_key}={a_v!r} (only 'no-downgrade' is allowed)"
    # blockExoticSubdeps — true → anything-else is a weakening.
    if block_exotic_key is not None:
        b_v: Any = b.get(block_exotic_key)
        a_v: Any = a.get(block_exotic_key)
        # Normalise .npmrc "true"/"false" strings to bool.
        if isinstance(b_v, str):
            b_v = b_v.strip().lower() == "true"
        if isinstance(a_v, str):
            a_v = a_v.strip().lower() == "true"
        if b_v is True and a_v is not True:
            return f"{block_exotic_key} set false / removed (was true)"
        if a_v is False and b_v is not False:
            return f"{block_exotic_key}=false (was true / unset)"
    # audit-level lowered (only relevant for .npmrc).
    if audit_key is not None:
        rank = {"none": 0, "info": 1, "low": 2, "moderate": 3, "high": 4, "critical": 5}
        b_v = rank.get(str(b.get(audit_key, "")).strip().lower())
        a_v = rank.get(str(a.get(audit_key, "")).strip().lower())
        if a_v is not None and a_v < 3:  # below 'moderate'
            note = f"was {b.get(audit_key)}" if audit_key in b else "previously unset"
            return f"{audit_key}={a.get(audit_key)} below 'moderate' ({note})"
    # frozen-lockfile (npmrc) lowered to false / removed.
    if frozen_key is not None:
        b_fk: Any = b.get(frozen_key)
        a_fk: Any = a.get(frozen_key)
        if isinstance(b_fk, str):
            b_fk = b_fk.strip().lower() == "true"
        if isinstance(a_fk, str):
            a_fk = a_fk.strip().lower() == "true"
        if b_fk is True and a_fk is not True:
            return f"{frozen_key} removed / false (was true)"
    return None


_CHECKERS: dict[str, Callable[[str, str, int], Optional[str]]] = {
    ".npmrc": _check_npmrc_diff,
    "package.json": _check_package_json_diff,
    "pnpm-workspace.yaml": _check_yaml_diff,
    ".yarnrc.yml": _check_yarnrc_diff,
    ".yarnrc.yaml": _check_yarnrc_diff,
    "bunfig.toml": _check_toml_diff,
    "bun.toml": _check_toml_diff,
}


# --- Class A driver -------------------------------------------------------

def check_bash(command: str) -> Optional[str]:
    if not command:
        return None
    norm = re.sub(r"\s+", " ", command).strip()
    threshold = _threshold_minutes()
    # Numeric-aware check first (skipped if N >= threshold).
    r = _check_pnpm_min_age(norm, threshold)
    if r is not None:
        return r
    for pat, reason in _BASH_BLOCKS:
        if pat.search(norm):
            return reason
    return None


# --- Class B driver -------------------------------------------------------

def _resolve_file_path(file_path: str, cwd: str) -> Path:
    p = Path(file_path)
    if not p.is_absolute() and cwd:
        p = Path(cwd) / p
    return p


def check_edit(tool: str, tool_input: dict[str, Any], cwd: str) -> Optional[str]:
    file_path = tool_input.get("file_path") or ""
    if not file_path:
        return None
    basename = Path(file_path).name
    checker = _CHECKERS.get(basename)
    if checker is None:
        return None
    abs_path = _resolve_file_path(file_path, cwd)
    try:
        before = abs_path.read_text(encoding="utf-8") if abs_path.is_file() else ""
    except OSError:
        before = ""
    if tool == "Edit":
        old_s = tool_input.get("old_string", "") or ""
        new_s = tool_input.get("new_string", "") or ""
        replace_all = bool(tool_input.get("replace_all", False))
        after = before.replace(old_s, new_s, -1 if replace_all else 1) if old_s in before else (before + new_s if not before else before)
    elif tool == "Write":
        after = tool_input.get("content", "") or ""
    else:
        return None  # NotebookEdit not used for package configs
    threshold = _threshold_minutes()
    return checker(before, after, threshold)


# --- Logging --------------------------------------------------------------

def _log_block(class_label: str, tool: str, tool_input: dict[str, Any], reason: str) -> None:
    """Append one line to the global pkg-manager-guard.log audit trail."""
    try:
        import global_state as gs  # type: ignore[import-not-found]
        gs.init_global_state()
        log_path = gs.global_state_dir() / "pkg-manager-guard.log"
    except Exception:  # noqa: BLE001 - fall back to project log on any import / FS error
        state.init_state()
        log_path = state.log_dir() / "pkg-manager-guard.log"
    snippet = ""
    if tool == "Bash":
        snippet = (tool_input.get("command") or "")[:200]
    else:
        snippet = f"file_path={tool_input.get('file_path', '')}"
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    line = f"[{ts}] {class_label} tool={tool} reason={reason!r} arg={snippet!r}\n"
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


# --- Main hook entry ------------------------------------------------------

def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input → don't block; let Claude Code handle it

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    cwd = data.get("cwd") or ""

    reason: Optional[str] = None
    class_label = ""
    if tool == "Bash":
        reason = check_bash(tool_input.get("command", "") or "")
        class_label = "ClassA"
    elif tool in ("Edit", "Write"):
        reason = check_edit(tool, tool_input, cwd)
        class_label = "ClassB"
    # All other tools — silent pass-through.

    if reason is None:
        return 0  # silent allow

    _log_block(class_label, tool, tool_input, reason)

    override = _allow_override()
    decision = "ask" if override else "deny"
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": (
                f"[pkg-manager-guard] {reason}. "
                f"Set CLAUDE_PLUGIN_OPTION_PKG_MANAGER_HOOK_ALLOW_USER_OVERRIDE=true to confirm per call, "
                f"or raise CLAUDE_PLUGIN_OPTION_PKG_MANAGER_MIN_RELEASE_AGE_MINUTES if the threshold is wrong."
            ),
        }
    }
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
