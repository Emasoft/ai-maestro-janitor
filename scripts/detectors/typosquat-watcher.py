#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Typosquat-watcher — heartbeat detector for typo-squat dependency names.

Walks every lockfile in the project (package-lock.json, pnpm-lock.yaml,
yarn.lock, requirements.txt, uv.lock, poetry.lock) and surfaces any
direct dependency whose name is within Levenshtein distance ≤ 1 of a
curated popular package — the documented shape of every disclosed
typosquat campaign (react/reactt, lodash/lodahs, web3/web33, etc.).

This is the FAST complement to the on-demand `janitor-supply-chain-watcher`
skill: the skill audits known-CVE / known-malicious advisories, the
detector catches typosquats BEFORE they show up in an advisory feed.
A typosquat is the canonical malware-delivery shape in 2024/2025;
catching it at lockfile-write time closes the gap before the malicious
postinstall runs the next time `npm install` is invoked.

Heartbeat invariants:
  * Self-scan guard — never scans the janitor's own tree.
  * Content-hash dedupe on the (lockfile, name-set) pair.
  * Read-only — never edits a lockfile.
  * Bounded output — at most one drift line per heartbeat, capped sample.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import security_helpers as sh  # type: ignore[import-not-found]  # noqa: E402
import state  # type: ignore[import-not-found]  # noqa: E402

_NAME = "typosquat-watcher"


def _max_distance() -> int:
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_TYPOSQUAT_MAX_DISTANCE", "1")
    try:
        n = int(raw)
    except ValueError:
        return 1
    # Distance > 2 produces too many false positives; cap defensively.
    return max(1, min(2, n))


def _extract_npm_names_from_package_lock(path: Path) -> set[str]:
    """Return the set of npm package names referenced in package-lock.json.
    npm v7+ uses the `packages` map keyed by `node_modules/<name>` (and
    the top-level "" key for the project itself). v6 used `dependencies`."""
    out: set[str] = set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    if not isinstance(data, dict):
        return out
    pkgs = data.get("packages")
    if isinstance(pkgs, dict):
        for key in pkgs:
            if not isinstance(key, str) or not key:
                continue
            if key.startswith("node_modules/"):
                name = key[len("node_modules/"):]
                # Strip nested node_modules/ (transitive deps live under
                # node_modules/<x>/node_modules/<y>)
                if "/node_modules/" in name:
                    name = name.split("/node_modules/")[-1]
                # Scoped packages stay as @scope/pkg
                out.add(name)
    deps = data.get("dependencies")
    if isinstance(deps, dict):
        for k in deps:
            if isinstance(k, str):
                out.add(k)
    return out


def _extract_npm_names_from_yarn_lock(path: Path) -> set[str]:
    """Yarn classic and Yarn berry both start each entry with the package
    spec. Yarn classic: `"react@^18.0.0", "react@~18.1.0":`. Yarn berry:
    `"react@npm:^18.0.0":`. Either way the package name is up to the `@`
    that's NOT the leading `@` of a scope."""
    out: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or not line.endswith(":"):
            continue
        if " " in line.split(":", 1)[0]:
            # Some yarn versions have inline-key with no quotes - skip
            continue
        # Strip quotes and trailing colon
        body = line.rstrip(":").strip()
        # The line may contain multiple specs separated by ", "
        for spec in body.split(", "):
            spec = spec.strip().strip('"').strip("'")
            if not spec:
                continue
            # Split on @ but preserve scope's leading @
            if spec.startswith("@"):
                # @scope/name@version → name = @scope/name
                rest = spec[1:]
                if "/" not in rest:
                    continue
                slash = rest.index("/")
                # Find the next @ after the slash (the version separator)
                after = rest[slash:]
                at_idx = after.find("@")
                if at_idx == -1:
                    name = "@" + rest
                else:
                    name = "@" + rest[: slash + at_idx]
            else:
                at_idx = spec.find("@")
                name = spec if at_idx == -1 else spec[:at_idx]
            if name:
                out.add(name)
    return out


def _extract_pypi_names_from_requirements(path: Path) -> set[str]:
    """Parse a requirements.txt-style file. Each non-comment line begins
    with the package name; tokens after `==` / `>=` / etc. are the spec."""
    out: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Split on any version operator or extras bracket.
        m = re.match(r"^([A-Za-z0-9_.\-]+)", line)
        if m:
            out.add(m.group(1).lower().replace("_", "-"))
    return out


def _extract_pypi_names_from_uv_lock(path: Path) -> set[str]:
    """uv.lock is TOML — `[[package]]` blocks each have a `name = "..."`."""
    out: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r'^name\s*=\s*"([^"]+)"', line)
        if m:
            out.add(m.group(1).lower().replace("_", "-"))
    return out


def _extract_pypi_names_from_poetry_lock(path: Path) -> set[str]:
    """poetry.lock uses the same `[[package]]` / `name = "..."` shape."""
    return _extract_pypi_names_from_uv_lock(path)


def _extract_npm_names_from_pnpm_lock(path: Path) -> set[str]:
    """pnpm-lock.yaml: the `packages:` block keys are `/<name>@<version>`
    or `/<name>/<version>`. We pull the name before the first `@` (or
    `/` for the second style), preserving scope's leading `@`."""
    out: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    # Look for top-level keys under `packages:` that look like /<spec>:
    in_packages = False
    for raw in text.splitlines():
        if raw.startswith("packages:"):
            in_packages = True
            continue
        if in_packages and raw and not raw[0].isspace() and not raw.startswith("#"):
            # Left the `packages:` block.
            in_packages = False
        if not in_packages:
            continue
        line = raw.strip()
        if not line.startswith("/"):
            continue
        # Strip the trailing colon + the leading slash
        spec = line.rstrip(":").lstrip("/")
        # Format A: name@version  (most common). Scope: @scope/name@version
        if spec.startswith("@"):
            rest = spec[1:]
            if "/" not in rest:
                continue
            slash = rest.index("/")
            after = rest[slash:]
            at_idx = after.find("@")
            if at_idx == -1:
                continue
            name = "@" + rest[: slash + at_idx]
        else:
            at_idx = spec.find("@")
            if at_idx == -1:
                # Format B: name/version
                slash = spec.find("/")
                if slash == -1:
                    continue
                name = spec[:slash]
            else:
                name = spec[:at_idx]
        if name:
            out.add(name)
    return out


_LOCKFILE_PARSERS = {
    "package-lock.json": ("npm", _extract_npm_names_from_package_lock),
    "yarn.lock": ("npm", _extract_npm_names_from_yarn_lock),
    "pnpm-lock.yaml": ("npm", _extract_npm_names_from_pnpm_lock),
    "requirements.txt": ("py", _extract_pypi_names_from_requirements),
    "uv.lock": ("py", _extract_pypi_names_from_uv_lock),
    "poetry.lock": ("py", _extract_pypi_names_from_poetry_lock),
}


def _scan_project(project_root: Path) -> list[str]:
    """Walk every supported lockfile under the project (skip vendored
    dirs) and return drift lines for typosquat candidates."""
    issues: list[str] = []
    max_dist = _max_distance()
    popular_npm = sh.popular_npm_packages()
    popular_py = sh.popular_pypi_packages()

    skip_dirs = {"node_modules", ".venv", "venv", "env",
                 "vendor", "third_party", ".git"}

    for lockname, (ecosystem, parser) in _LOCKFILE_PARSERS.items():
        for path in project_root.rglob(lockname):
            # Skip vendored / cached lockfiles.
            if any(part in skip_dirs for part in path.parts):
                continue
            names = parser(path)
            if not names:
                continue
            popular = popular_npm if ecosystem == "npm" else popular_py
            for name in sorted(names):
                target = sh.is_typosquat_candidate(
                    name, popular, max_distance=max_dist,
                )
                if target and target != name:
                    rel = path.relative_to(project_root)
                    issues.append(
                        f"{ecosystem}:{name} looks like a typosquat of "
                        f"'{target}' (distance ≤ {max_dist}) — installed via {rel}"
                    )
    return issues


def _content_signature(project_root: Path) -> str:
    """Cheap dedupe — mtime + size of every supported lockfile."""
    h = hashlib.sha256()
    for lockname in _LOCKFILE_PARSERS:
        for path in sorted(project_root.rglob(lockname)):
            if any(part in {"node_modules", ".venv", "venv", "env",
                            "vendor", "third_party", ".git"}
                   for part in path.parts):
                continue
            try:
                st = path.stat()
                h.update(f"{path}|{st.st_mtime_ns}|{st.st_size}\n".encode())
            except OSError:
                pass
    return h.hexdigest()


def main() -> int:
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_TYPOSQUAT_WATCHER_ENABLED", True,
    ):
        return 0
    if state.is_self_scan_target():
        return 0

    state.init_state()
    project_root = state.project_root()

    combined = _content_signature(project_root)
    last_hash_file = state.state_dir() / "typosquat-watcher-last-hash.ts"
    if last_hash_file.is_file():
        try:
            if last_hash_file.read_text(encoding="utf-8").strip() == combined:
                return 0  # nothing changed → silent
        except OSError:
            pass

    issues = _scan_project(project_root)
    state.atomic_write(last_hash_file, combined)

    if not issues:
        state.rotate_log_if_big(_NAME)
        return 0

    cap = 5
    sample = "\n".join(f"  - {state.sanitize_for_drift_line(s)}" for s in issues[:cap])
    if len(issues) > cap:
        sample += f"\n  - …and {len(issues) - cap} more"

    print(
        f"[typosquat-watcher] {len(issues)} dependency name(s) match the "
        f"typosquat shape (Levenshtein ≤ {_max_distance()} from a popular "
        f"package). Review each before the next install — typosquats are "
        f"the documented #1 supply-chain attack vector.\n{sample}"
    )
    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
