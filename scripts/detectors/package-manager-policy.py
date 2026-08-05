#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0",
# ]
# ///
"""Package-manager-policy detector — supply-chain hardening audit.

The DETECTION complement to scripts/hooks/pre-tool-pkg-guard.py. The hook
prevents an agent from WEAKENING a project's package-manager safety knobs
in real time; this detector tells the user when those knobs are MISSING
in the first place, so a project can be hardened proactively before the
next supply-chain attack lands. Closes the second gap in the safedep.io
art-template recommendation: minimumReleaseAge / trustPolicy /
blockExoticSubdeps / audit-level configured, AND an install-time malware
firewall (sfw / safe-chain) on PATH.

Scope (v1): scans the project root for the canonical config files —
.npmrc, package.json#pnpm, pnpm-workspace.yaml, .yarnrc.yml, bunfig.toml.
A node-flavoured project is detected by the presence of package.json
or any of the JS lockfiles (so we silently skip pure-Python / Rust /
Go projects).

Hardening checklist (any FAIL produces a drift-line bullet):
  1. minimumReleaseAge ≥ pkg_manager_min_release_age_minutes (default 7200 = 5 d).
  2. trustPolicy == "no-downgrade".
  3. blockExoticSubdeps == true.
  4. audit-level >= "moderate" (only when .npmrc sets one — npm default
     is already 'low' so a missing key is not flagged; the rule fires
     only when an explicit weakening is committed).
  5. An install-time malware firewall on PATH: `sfw` (Socket Free) OR
     `safe-chain` (AikidoSec). Neither installed → recommend.

Caching: content-hash the relevant config files plus the PATH-presence
booleans; short-circuit when nothing changed. Emits at most one drift
line per content-version per project. Read-only — never edits a file.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional

import yaml

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import issue_catalog  # noqa: E402
import security_helpers as sec  # noqa: E402
import state  # noqa: E402

# The finding's LOCATION for dedupe purposes: the project's package-manager configuration, taken as
# one surface. The individual knobs live in `found`; they are not separate incidents, because they
# are not separate repairs.
_WHERE = "package-manager config"

_NAME = "package-manager-policy"


def _threshold_minutes() -> int:
    """Same knob the pre-tool-pkg-guard hook honours."""
    return state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_PKG_MANAGER_MIN_RELEASE_AGE_MINUTES"),
        7200,
    )


# ---- parsers ------------------------------------------------------------

def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _parse_npmrc(text: str) -> dict[str, str]:
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
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip().split()[0] if v.strip() else ""
        return int(s) if s.isdigit() else None
    return None


def _is_truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "on")
    return False


# ---- project shape detection --------------------------------------------

# Must stay a SUPERSET of `_LOCKFILE_MANAGER`'s keys below: a lockfile this list omits makes
# `_is_node_project` return False, so the detector exits before the manager resolution that
# lockfile would have driven ever runs. `npm-shrinkwrap.json` was exactly that hole — mapped to
# npm below, but invisible here, so a shrinkwrap-only repo was audited by nobody.
_NODE_LOCKFILES = (
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "bun.lock",
)

# Dependency-block keys whose presence (with at least one entry) proves a
# package.json describes a project that actually consumes npm packages. A
# package.json that exists only as project metadata (skill manifest, doc-
# site config, monorepo placeholder with no own deps) does NOT expose the
# install-time attack surface this detector is built to harden, and would
# therefore false-positive on every supply-chain check below.
_NPM_INSTALLABLE_DEP_KEYS = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
    "bundledDependencies",  # legacy synonym
    "bundleDependencies",
)


def _has_installable_deps(pjson: Any) -> bool:
    """True iff the package.json declares at least one installable dependency
    OR is a workspace root (monorepo parent — sub-packages have deps).

    Used as a context guard before running the supply-chain audits: a
    metadata-only package.json (e.g. a Claude skill bundle that only sets
    `{name, version, files, skill: {...}}`) has no install attack surface
    and should not be flagged for missing `.npmrc`.

    Takes Any (not dict) because `json.loads` of a malformed package.json
    could be a list / string / number / null — the isinstance guard below
    is the only thing keeping the function safe in that case.
    """
    if not isinstance(pjson, dict):
        return False
    for key in _NPM_INSTALLABLE_DEP_KEYS:
        v = pjson.get(key)
        if isinstance(v, dict) and v:
            return True
        if isinstance(v, list) and v:  # bundledDependencies is a list
            return True
    # Monorepo root: workspaces field present (string list OR object with
    # `packages:` key). Sub-packages carry their own deps; the root still
    # needs hardened defaults to govern child installs.
    ws = pjson.get("workspaces")
    if isinstance(ws, list) and ws:
        return True
    if isinstance(ws, dict) and ws.get("packages"):
        return True
    return False


# ---- which package manager actually installs here (janitor#130) ----------
#
# `.npmrc`'s policy knobs (minimum-release-age / trust-policy /
# block-exotic-subdeps) are npm's. Yarn Classic reads `.npmrc` for registry,
# auth and proxy ONLY — it ignores these — so proposing them on a yarn repo
# writes a file that LOOKS like an enforced supply-chain policy and enforces
# nothing. That is worse than the gap it closes: the next auditor sees
# `minimum-release-age` set and concludes the cooldown is active. Reported by
# the ai-maestro Claude (janitor#130) after the detector proposed exactly that
# on a repo pinned to yarn@1.22.22.
_MANAGERS_HONOURING_NPMRC_POLICY = frozenset({"npm"})

_LOCKFILE_MANAGER = {
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "bun.lockb": "bun",
    "bun.lock": "bun",
    "yarn.lock": "yarn",
}


def _lockfile_managers(lockfiles: Iterable[str]) -> set[str]:
    """The distinct managers whose lockfiles are present. ONE source of truth, because two
    callers ask the same question for different reasons: the resolver (to decide whether the
    install path is knowable) and `main` (to report the conflict itself)."""
    return {_LOCKFILE_MANAGER[f] for f in lockfiles if f in _LOCKFILE_MANAGER}


def present_lockfile_managers(root: Path) -> set[str]:
    """Filesystem wrapper around `_lockfile_managers`. Never raises."""
    return _lockfile_managers([name for name in _LOCKFILE_MANAGER if (root / name).is_file()])


def resolve_package_manager(
    *,
    package_manager_field: str = "",
    lockfiles: Iterable[str] = (),
    has_yarnrc_yml: bool = False,
) -> str:
    """Which manager installs this project: npm | yarn-classic | yarn-berry | pnpm | bun |
    ambiguous | unknown. PURE — all evidence is injected, so it tests without a filesystem.

    Evidence order is deliberate:

    1. **`package.json#packageManager`** (the Corepack pin, e.g. `yarn@1.22.22`) — an explicit
       declaration by the project beats anything inferred, and it is the only signal that
       distinguishes Yarn Classic from Berry by version rather than by side effect.
    2. **Lockfiles** — a lockfile only exists because that manager actually ran. `yarn.lock`
       alone cannot tell Classic from Berry, so `.yarnrc.yml` (a Berry-only file) breaks the tie;
       absent it, Classic is the safer read, because Classic is the one that silently ignores
       npm's knobs and is therefore the case worth being right about.
    3. **Nothing** → `unknown`, which callers may treat as npm: npm is Node's default, and every
       other manager leaves evidence we just looked for. This is an inference, not a guess.

    Two or more DIFFERENT managers' lockfiles → `ambiguous`. Never silently pick one: a repo
    with both `yarn.lock` and `package-lock.json` has a real problem, and choosing a winner would
    hide it behind whichever knob set we then proposed.
    """
    field = (package_manager_field or "").strip().lower()
    if field:
        name, _, version = field.partition("@")
        name = name.strip()
        if name == "yarn":
            major = version.strip().split(".", 1)[0]
            if major:
                return "yarn-classic" if major == "1" else "yarn-berry"
            # An UNVERSIONED pin (`"yarn"`, or `"yarn@"`) names the family but not the major, so
            # it cannot decide Classic-vs-Berry. Apply the SAME tiebreak the lockfile path uses
            # rather than the empty string falling through `!= "1"` into Berry: that read is both
            # unevidenced and the unsafe direction. Falling through to the lockfile block instead
            # would be worse still — a bare `yarn` pin with no lockfile yet would land on
            # `unknown`, which callers treat as npm, re-opening janitor#130 on a yarn repo.
            return "yarn-berry" if has_yarnrc_yml else "yarn-classic"
        if name in ("npm", "pnpm", "bun"):
            return name

    found = _lockfile_managers(lockfiles)
    if len(found) > 1:
        return "ambiguous"
    if not found:
        return "unknown"
    only = found.pop()
    if only == "yarn":
        return "yarn-berry" if has_yarnrc_yml else "yarn-classic"
    return only


def detect_package_manager(root: Path) -> str:
    """Filesystem wrapper around `resolve_package_manager`. Never raises."""
    field = ""
    pj = root / "package.json"
    if pj.is_file():
        j = _parse_json(_read_text(pj))
        if isinstance(j, dict):
            raw = j.get("packageManager")
            if isinstance(raw, str):
                field = raw
    lockfiles = [name for name in _LOCKFILE_MANAGER if (root / name).is_file()]
    return resolve_package_manager(
        package_manager_field=field,
        lockfiles=lockfiles,
        has_yarnrc_yml=(root / ".yarnrc.yml").is_file() or (root / ".yarnrc.yaml").is_file(),
    )


def _is_node_project(root: Path) -> bool:
    """True iff the project actually installs npm packages.

    Two acceptance shapes:
      1. A JS lockfile exists (`package-lock.json` / `pnpm-lock.yaml` /
         `yarn.lock` / `bun.lockb` / `bun.lock`). A lockfile is only
         generated when `npm install` (or its equivalent) has actually run
         against real deps, so its existence is proof of installation
         intent.
      2. `package.json` exists AND declares at least one installable
         dependency block (or is a workspace root). A `package.json`
         WITHOUT any deps is metadata-only and produces no install
         attack surface, so the supply-chain knobs do not apply.

    Skipping a metadata-only package.json is a context-precision
    improvement, NOT a rule weakening: the day a real dependency is
    added, the next heartbeat re-fires every relevant audit. A truly
    malicious package.json that hides deps in an unusual location
    (e.g. directly in a sub-script) is not the threat model this
    detector is built for — that lives upstream in `pre-tool-pkg-guard`
    and `supply-chain-watcher`.
    """
    # Lockfile path: definitive proof a node project has been installed.
    if any((root / lf).exists() for lf in _NODE_LOCKFILES):
        return True
    pjson_path = root / "package.json"
    if not pjson_path.is_file():
        return False
    try:
        pjson = json.loads(pjson_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Malformed package.json — be conservative, treat as node-project
        # so the user is told to harden it (and so we don't silently swallow
        # a real defect via a parse error).
        return True
    return _has_installable_deps(pjson)


# ---- the per-knob policy walker -----------------------------------------

def _audit_npmrc(root: Path, threshold: int, issues: list[str], manager: str = "npm") -> None:
    """Audit npm's `.npmrc` policy knobs — ONLY when npm is what installs here (janitor#130).

    `unknown` counts as npm: npm is Node's default and `detect_package_manager` has already
    looked for every other manager's evidence. `ambiguous` does NOT — a repo with two managers'
    lockfiles gets its own finding rather than a knob set chosen by coin-flip.

    A manager that ignores these keys is NOT left unguarded by this return: the install-time
    malware firewall (`_audit_install_firewall`) is manager-agnostic — Socket Firewall and
    Aikido safe-chain shim `npm`/`yarn`/`pnpm` alike — runs unconditionally, and is the honest
    remedy for a repo whose manager cannot express a release cooldown. Going quiet here removes
    a false positive without creating a false negative.
    """
    if manager not in _MANAGERS_HONOURING_NPMRC_POLICY and manager != "unknown":
        return
    p = root / ".npmrc"
    if not p.is_file():
        # No .npmrc at all → flag all the missing safety knobs at once.
        issues.append(
            f"no .npmrc — missing supply-chain knobs (set minimum-release-age={threshold}, "
            "trust-policy=no-downgrade, block-exotic-subdeps=true)"
        )
        return
    cfg = _parse_npmrc(_read_text(p))
    age = _as_int(cfg.get("minimum-release-age"))
    if age is None or age < threshold:
        issues.append(
            f".npmrc minimum-release-age={age if age is not None else 'unset'} "
            f"< {threshold} (5-day exposure window vs fresh-published packages)"
        )
    tp = (cfg.get("trust-policy") or "").strip().lower()
    if tp != "no-downgrade":
        cur = tp if tp else "unset"
        issues.append(f".npmrc trust-policy={cur!r} (require 'no-downgrade' to block silent downgrades)")
    bes = cfg.get("block-exotic-subdeps")
    if bes is None or not _is_truthy(bes):
        issues.append(".npmrc block-exotic-subdeps unset/false (set true to refuse exotic transitives)")
    # audit-level: only flag explicit weakening (none/info/low); silence when unset.
    al = (cfg.get("audit-level") or "").strip().lower()
    if al in ("none", "info", "low"):
        issues.append(f".npmrc audit-level={al!r} below 'moderate' (raise to hide fewer advisories)")


# The pnpm policy keys, and the ONE file pnpm reads them from.
#
# VERIFIED against pnpm 11.11.0, not inferred (janitor#148). pnpm's docs are
# categorical — "Only auth and registry settings are read from `.npmrc` files.
# All other settings must be configured in `pnpm-workspace.yaml` or the global
# `~/.config/pnpm/config.yaml`" — and an A/B of pnpm's own effective config
# agrees: a `minimumReleaseAge` written to `pnpm-workspace.yaml` appears in
# `pnpm config list`, the SAME key written to `package.json#pnpm` does not.
_PNPM_POLICY_KEYS = ("minimumReleaseAge", "trustPolicy", "blockExoticSubdeps")
_PNPM_SETTINGS_FILE = "pnpm-workspace.yaml"


def _project_uses_pnpm(root: Path) -> bool:
    return (root / "pnpm-lock.yaml").exists() or (root / _PNPM_SETTINGS_FILE).exists()


def _pnpm_workspace_gaps(root: Path, threshold: int) -> list[str]:
    """Compliance findings for the file pnpm ACTUALLY reads; empty list = fully protected.

    ONE predicate, consumed by both pnpm audits below. It exists because the two used
    independent readings of "is the repo protected", and the misplaced-keys audit firing
    while this file is fully compliant is precisely the false alarm of
    ai-maestro-plugins#15: the proposal's catalog title says a safety knob is DISABLED,
    when the live file has every knob at strength and the package.json copies are
    redundant duplicates. A shared predicate makes that disagreement impossible.
    """
    p = root / _PNPM_SETTINGS_FILE
    y = _parse_yaml(_read_text(p)) if p.is_file() else {}
    if not any(k in y for k in _PNPM_POLICY_KEYS):
        return [
            f"{_PNPM_SETTINGS_FILE} lacks pnpm supply-chain settings "
            f"(add minimumReleaseAge: {threshold}, trustPolicy: 'no-downgrade', "
            f"blockExoticSubdeps: true)"
        ]
    gaps: list[str] = []
    age = _as_int(y.get("minimumReleaseAge"))
    if age is None or age < threshold:
        cur = age if age is not None else "unset"
        gaps.append(f"{_PNPM_SETTINGS_FILE} minimumReleaseAge={cur} < {threshold}")
    tp = str(y.get("trustPolicy") or "").strip().lower()
    if tp != "no-downgrade":
        cur_tp = tp if tp else "unset"
        gaps.append(f"{_PNPM_SETTINGS_FILE} trustPolicy={cur_tp!r} (require 'no-downgrade')")
    bes = y.get("blockExoticSubdeps")
    if bes is None or not _is_truthy(bes):
        gaps.append(f"{_PNPM_SETTINGS_FILE} blockExoticSubdeps unset/false (set true)")
    return gaps


def _audit_pjson_pnpm(root: Path, threshold: int, issues: list[str]) -> None:
    """Flag pnpm POLICY keys parked in `package.json#pnpm`, where pnpm ignores them.

    This function used to PROPOSE that location and then read the keys back from it
    to decide the repo was protected — so following our own advice produced a clean
    report and no enforcement at all. That is worse than the false positive #130 was
    about: a false positive costs attention, this manufactures false assurance on a
    supply-chain control, and it is invisible to any test that only checks whether
    the finding fires.

    `package.json#pnpm` is still a REAL field — `overrides`, `packageExtensions` and
    `patchedDependencies` genuinely live there — which is exactly why the near-miss
    survived review. Only these three POLICY keys are misplaced, so only they are
    flagged, and the remedy names the file that actually takes effect.

    NOT flagged when `pnpm-workspace.yaml` is already fully compliant
    (ai-maestro-plugins#15): the parked copies are then redundant duplicates of LIVE
    values — a tidiness matter — while the finding feeds a proposal whose catalog
    title asserts a DISABLED safeguard. A knob reported at its intended value by the
    file pnpm reads is not disabled, whatever other files say. When the workspace
    file has ANY gap, the misplaced-keys message still fires alongside the gap
    finding, because then it is genuine context for the fix.
    """
    p = root / "package.json"
    if not p.is_file():
        return
    j = _parse_json(_read_text(p))
    pnpm = j.get("pnpm", {})
    if not isinstance(pnpm, dict) or not pnpm:
        return
    misplaced = [k for k in _PNPM_POLICY_KEYS if k in pnpm]
    if misplaced and _pnpm_workspace_gaps(root, threshold):
        issues.append(
            f"package.json#pnpm sets {', '.join(misplaced)} but pnpm does NOT read "
            f"settings from package.json — move to {_PNPM_SETTINGS_FILE} (verified pnpm 11)"
        )


def _audit_pnpm_workspace(root: Path, threshold: int, issues: list[str]) -> None:
    """Audit the file pnpm ACTUALLY reads — including the keys' ABSENCE.

    Owns the missing-settings proposal now, because proposing a control belongs
    wherever that control takes effect. Previously absence was only ever reported
    against `package.json`, so a repo correctly configured in `pnpm-workspace.yaml`
    was still told to add a `pnpm` block it did not need — a false positive and a
    false-assurance path from the same split.
    """
    if not _project_uses_pnpm(root):
        return
    issues.extend(_pnpm_workspace_gaps(root, threshold))


def _audit_yarnrc(root: Path, _threshold: int, issues: list[str]) -> None:
    p = root / ".yarnrc.yml"
    if not p.is_file():
        p = root / ".yarnrc.yaml"
        if not p.is_file():
            return
    y = _parse_yaml(_read_text(p))
    if _is_truthy(y.get("enableScripts", False)):
        issues.append(".yarnrc.yml enableScripts=true (set false to disable postinstall scripts)")


def _audit_bunfig(root: Path, _threshold: int, issues: list[str]) -> None:
    for name in ("bunfig.toml", "bun.toml"):
        p = root / name
        if not p.is_file():
            continue
        t = _parse_toml(_read_text(p))
        raw_install = t.get("install")
        install: dict[str, Any] = raw_install if isinstance(raw_install, dict) else {}
        if install.get("verify") is False:
            issues.append(f"{name} [install].verify=false (set true)")
        return


def _audit_install_firewall(root: Path, issues: list[str]) -> None:
    """Verify an install-time malware firewall is reachable for THIS project.

    Two firewalls are recognised:
      * `sfw` — Socket Firewall Free (docs.socket.dev/docs/socket-firewall-free).
        Wraps `sfw npm install` etc.; just having it on PATH is enough — the
        user opts into protection at call time.
      * `@aikidosec/safe-chain` — Aikido safe-chain (github.com/AikidoSec/safe-chain).
        PATH-shim model: when installed globally it shadows `npm`/`yarn`/`pnpm`,
        so every install is intercepted automatically. The CLI is exposed
        under several executable names depending on install style.

    Resolution order, any-hit short-circuits:
      1. Global binary on PATH (the common case for `npm i -g`).
      2. Project-local install — `<root>/node_modules/.bin/<bin>`. Tracked
         for projects that vendor the firewall as a devDependency.
      3. Listed as a (dev)dependency in `<root>/package.json`. Some
         workflows use the package only via `npx <bin>` without ever
         dropping a wrapper, so listing alone is acceptance.

    Detected binary names: `sfw`, `safe-chain`, `aikido-safe-chain`,
    `aikido` — covering every shim the two tools ship with.
    """
    candidate_bins = ("sfw", "safe-chain", "aikido-safe-chain", "aikido")
    candidate_pkgs = ("sfw", "@aikidosec/safe-chain")

    # 1. Global PATH check.
    if any(shutil.which(b) for b in candidate_bins):
        return

    # 2. Project-local node_modules/.bin shim.
    local_bin = root / "node_modules" / ".bin"
    if local_bin.is_dir() and any((local_bin / b).exists() for b in candidate_bins):
        return

    # 3. Declared as a (dev)dependency in package.json.
    pjson = root / "package.json"
    if pjson.is_file():
        try:
            data = _parse_json(_read_text(pjson))
        except Exception:  # noqa: BLE001 - any parse failure → fall through
            data = {}
        for dep_block in ("dependencies", "devDependencies", "optionalDependencies"):
            block = data.get(dep_block)
            if isinstance(block, dict) and any(p in block for p in candidate_pkgs):
                return

    issues.append(
        "no install-time malware firewall on PATH (install Aikido safe-chain via "
        "`npm i -g @aikidosec/safe-chain` for npm/yarn/pnpm/npx/pip/uv/poetry coverage, "
        "or Socket Firewall Free via `npm i -g sfw` and prefix installs with `sfw`)"
    )


# ---- content-hash short-circuit -----------------------------------------

_CONFIG_FILES = (
    ".npmrc",
    "package.json",
    "pnpm-workspace.yaml",
    ".yarnrc.yml",
    ".yarnrc.yaml",
    "bunfig.toml",
    "bun.toml",
)


def _content_hash(root: Path) -> str:
    """Combined hash of all relevant config files + PATH-firewall presence.

    A change in ANY config file (or installing/removing sfw/safe-chain)
    invalidates the cache and re-emits the current finding set.
    """
    parts: list[str] = []
    for name in _CONFIG_FILES:
        p = root / name
        try:
            parts.append(f"{name}:{p.stat().st_mtime_ns}:{p.stat().st_size}")
        except FileNotFoundError:
            parts.append(f"{name}:absent")
        except OSError:
            parts.append(f"{name}:err")
    # Lockfile PRESENCE is an input to the audit — it decides `detect_package_manager` (janitor#130)
    # and the lockfile-conflict finding — so it MUST be in the cache key. It was not: a repo that
    # migrated yarn→npm without touching package.json kept the yarn-era hash and stayed silent
    # about its now-missing npm knobs forever (reproduced 2026-07-29). Presence ONLY, deliberately:
    # a lockfile's mtime/size changes on every install, and hashing that would re-emit an unchanged
    # finding after every `npm install`.
    for name in _LOCKFILE_MANAGER:
        parts.append(f"{name}:{'1' if (root / name).is_file() else '0'}")
    fw = "1" if (shutil.which("sfw") or shutil.which("safe-chain")) else "0"
    parts.append(f"firewall:{fw}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def main() -> int:
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_PKG_MANAGER_POLICY_ENABLED", True):
        return 0
    # Hard self-scan guard — see state.is_self_scan_target() docstring.
    if state.is_self_scan_target():
        return 0

    state.init_state()
    project_root = state.project_root()

    if not _is_node_project(project_root):
        state.rotate_log_if_big(_NAME)
        return 0  # not a node-family project

    combined = _content_hash(project_root)
    last_hash_file = state.state_dir() / "package-manager-policy-last-hash.ts"
    if last_hash_file.is_file():
        try:
            if last_hash_file.read_text(encoding="utf-8").strip() == combined:
                return 0  # nothing changed → silent
        except OSError:
            pass

    threshold = _threshold_minutes()
    issues: list[str] = []
    # Resolve WHO installs here before auditing manager-specific config (janitor#130): an
    # `.npmrc` policy proposal on a yarn repo enforces nothing while reading as enforcement.
    manager = detect_package_manager(project_root)
    # Judge the lockfile conflict INDEPENDENTLY of `manager`. A `packageManager` pin makes the
    # resolver authoritative, so it answers e.g. "yarn-classic" and NEVER "ambiguous" — which
    # would have hidden the hazard the resolver's own docstring calls "a real problem" on exactly
    # the repos disciplined enough to declare a pin. This check subsumes the old
    # `manager == "ambiguous"` branch: that verdict is only ever reached when >1 manager's
    # lockfiles are present.
    if len(present_lockfile_managers(project_root)) > 1:
        issues.append(
            "two package managers' lockfiles are present — the install path is undecidable, "
            "so no supply-chain policy can be verified. Keep one lockfile."
        )
    _audit_npmrc(project_root, threshold, issues, manager)
    _audit_pjson_pnpm(project_root, threshold, issues)
    _audit_pnpm_workspace(project_root, threshold, issues)
    _audit_yarnrc(project_root, threshold, issues)
    _audit_bunfig(project_root, threshold, issues)
    _audit_install_firewall(project_root, issues)

    # Stamp the hash regardless of outcome — same dedupe shape as workflow-security.
    state.atomic_write(last_hash_file, combined)

    if not issues:
        # Hardened now — withdraw any standing proposal, so a board never carries a gap that has
        # since been closed.
        issue_catalog.clear_issue("PKGPOL-001", where=_WHERE)
        state.rotate_log_if_big(_NAME)
        return 0

    # Cap the sample so a project with many issues still produces a bounded line.
    cap = 8
    sample = "\n".join(f"  - {state.sanitize_for_drift_line(s)}" for s in issues[:cap])
    if len(issues) > cap:
        sample += f"\n  - …and {len(issues) - cap} more"

    hint = sec.security_agent_hint(
        "supply-chain",
        enabled=state.is_truthy_env(sec.SECURITY_AGENT_HINT_ENV, True),
    )
    print(
        f"[package-manager-policy] {len(issues)} supply-chain hardening gap(s). "
        f"See README §'Supply-chain defense stack' for the full layered model. "
        f"Issues:\n{sample}"
        + (f"\n{hint}" if hint else "")
    )

    # ONE proposal for the project's package-manager config (TRDD-CGYMUKO6): every gap here is the
    # same job — restore the safeguards in the same handful of config files — so splitting them into
    # a ticket per knob would dispatch N agents to edit one `.npmrc`.
    r = issue_catalog.raise_issue(
        "PKGPOL-001",
        where=_WHERE,
        evidence=["package.json", ".npmrc"],
        path=_WHERE,
        detail=f"{len(issues)} gap(s)",
        found="; ".join(issues[:12]),
    )
    if r.first_seen and r.line:
        print(r.line)
    elif not r.ok:
        state.log_line(_NAME, f"could not raise PKGPOL-001: {r.why}")

    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
