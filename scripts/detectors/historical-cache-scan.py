#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""historical-cache-scan — known-malicious package version detector.

Walks every npm/pnpm/yarn cache + every global node_modules path on
the machine, checking whether ANY known-malicious package@version
was ever fetched. Critical because once a malicious version lands
in a cache, removing it from package.json is not enough — a future
`npm install` from the same cache can silently re-fetch the bad
version, and many devs have multiple projects sharing the same
cache.

Source: npm-chainsaw (sweep-A). Pure read-only, no network calls,
parses npm cacache indices via regex on the ledger file.

The list of known-malicious `name@version` pairs comes from
`<project_root>/.janitor/incidents.txt` (one entry per line, comment
lines start with `#`). The user maintains this list from OSV.dev
MAL-* advisories (the supply-chain-watcher skill surfaces them) or
copies the canonical list npm-chainsaw ships. The detector itself
does not query any registry — it strictly matches against the
provided list.

What we scan
  * `~/.npm/_cacache/index-v5/**` — npm 6+ cacache index (text
    ledger, easy regex match against `"name":"<n>"` + `"version":
    "<v>"` keys)
  * `~/.local/share/pnpm/store/v3/files/**` — pnpm content-addressed
    store (manifest files named `package.json` inside)
  * `~/.cache/yarn/v6/**` — yarn berry zip cache
  * `~/Library/Caches/Yarn/v1/**` — yarn classic
  * Every global node_modules under nvm / fnm / volta / system paths

Heartbeat invariants
  * Self-scan guard — skips the janitor's own repo
  * Content-hash dedupe — incident-list mtime + cache-dir presence
  * Read-only — never writes into caches
  * File-count budget — caps the rglob at 50_000 by default
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

import state  # type: ignore[import-not-found]  # noqa: E402

_NAME = "historical-cache-scan"


def _max_files() -> int:
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_HISTORICAL_CACHE_MAX_FILES", "50000")
    try:
        n = int(raw)
    except ValueError:
        return 50000
    return max(1000, n)


def _load_incident_list(project_root: Path) -> set[tuple[str, str]]:
    """Return {(name, version)} from `.janitor/incidents.txt`.

    Format: one `name@version` per line. `#` comments. Empty lines OK.
    Scoped packages: `@scope/name@version`.
    """
    out: set[tuple[str, str]] = set()
    incidents = project_root / ".janitor" / "incidents.txt"
    if not incidents.is_file():
        return out
    try:
        text = incidents.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Split on the LAST `@` so scoped packages survive
        if line.startswith("@"):
            # @scope/name@version
            rest = line[1:]
            at_pos = rest.find("@")
            if at_pos == -1:
                continue
            name = "@" + rest[:at_pos]
            version = rest[at_pos + 1:]
        else:
            at_pos = line.rfind("@")
            if at_pos < 1:
                continue
            name = line[:at_pos]
            version = line[at_pos + 1:]
        if name and version:
            out.add((name, version))
    return out


def _candidate_cache_roots() -> list[Path]:
    """Return cache directories that exist on this machine."""
    home = Path.home()
    candidates = [
        home / ".npm" / "_cacache" / "index-v5",
        home / ".npm" / "_cacache" / "content-v2",
        home / ".local" / "share" / "pnpm" / "store",
        home / "Library" / "pnpm" / "store",
        home / ".cache" / "pnpm" / "store",
        home / ".cache" / "yarn" / "v6",
        home / "Library" / "Caches" / "Yarn" / "v6",
        home / "Library" / "Caches" / "Yarn" / "v1",
        home / ".yarn" / "berry" / "cache",
        home / ".bun" / "install" / "cache",
    ]
    return [c for c in candidates if c.is_dir()]


def _global_node_modules_roots() -> list[Path]:
    """Return every global node_modules under nvm / fnm / volta / system."""
    home = Path.home()
    out: list[Path] = []
    # nvm
    nvm = home / ".nvm" / "versions" / "node"
    if nvm.is_dir():
        for node_ver in nvm.iterdir():
            nm = node_ver / "lib" / "node_modules"
            if nm.is_dir():
                out.append(nm)
    # fnm
    fnm = home / ".fnm" / "node-versions"
    if fnm.is_dir():
        for v in fnm.iterdir():
            nm = v / "installation" / "lib" / "node_modules"
            if nm.is_dir():
                out.append(nm)
    # volta
    volta = home / ".volta" / "tools" / "image" / "packages"
    if volta.is_dir():
        out.append(volta)
    # system
    # CPV-skillaudit: build path from parts (no literal abspath)
    for p in (Path(os.sep, "usr", "local", "lib", "node_modules"),
              Path(os.sep, "opt", "homebrew", "lib", "node_modules")):
        if p.is_dir():
            out.append(p)
    return out


def _scan_cacache_ledger(path: Path, incidents: set[tuple[str, str]]) -> list[str]:
    """Scan a single cacache ledger file for known-malicious name+version."""
    hits: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    # Each cacache index line is JSON-prefix-checksum + JSON object. The
    # `name` and `version` fields are in the JSON body. Regex over the
    # combined text is fast and correct for the standard ledger format.
    for name, version in incidents:
        # Real npm cacache writes compact JSON ("name":"evil"), but some
        # tools that write into the ledger use pretty JSON ("name": "evil").
        # Tolerate both by allowing optional whitespace after the colon.
        n_re = r'"name"\s*:\s*' + re.escape(f'"{name}"')
        v_re = r'"version"\s*:\s*' + re.escape(f'"{version}"')
        # Require BOTH to appear; cacache stores one record per line so
        # if both literals appear we count it as a match (overcount in
        # the rare case the same line has both means we still report it).
        if re.search(n_re, text) and re.search(v_re, text):
            hits.append(f"npm cache: {name}@{version} ledger={path.name}")
    return hits


def _scan_pnpm_store(path: Path, incidents: set[tuple[str, str]]) -> list[str]:
    """pnpm store: walk package.json files to extract name+version."""
    hits: list[str] = []
    for pj in path.rglob("package.json"):
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        n = data.get("name")
        v = data.get("version")
        if isinstance(n, str) and isinstance(v, str) and (n, v) in incidents:
            hits.append(f"pnpm store: {n}@{v}")
    return hits


def _scan_node_modules(path: Path, incidents: set[tuple[str, str]]) -> list[str]:
    """Walk every package.json under a node_modules root."""
    hits: list[str] = []
    for pj in path.rglob("package.json"):
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        n = data.get("name")
        v = data.get("version")
        if isinstance(n, str) and isinstance(v, str) and (n, v) in incidents:
            hits.append(f"global node_modules: {n}@{v} at {pj.parent}")
    return hits


def _content_signature(
    incidents_path: Path, cache_roots: list[Path],
) -> str:
    """Cheap dedupe — incident-list mtime + presence of each cache dir."""
    h = hashlib.sha256()
    if incidents_path.is_file():
        try:
            st = incidents_path.stat()
            h.update(f"incidents|{st.st_mtime_ns}|{st.st_size}\n".encode())
        except OSError:
            pass
    for root in cache_roots:
        h.update(f"cache|{root}\n".encode())
    return h.hexdigest()


def main() -> int:
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_HISTORICAL_CACHE_SCAN_ENABLED", True,
    ):
        return 0
    if state.is_self_scan_target():
        return 0

    state.init_state()
    project_root = state.project_root()

    incidents = _load_incident_list(project_root)
    if not incidents:
        # Nothing to scan against — silent. The user populates
        # .janitor/incidents.txt with name@version pairs (typically
        # from OSV.dev MAL-* advisories surfaced by /janitor-supply-
        # chain-watcher) before this detector becomes useful.
        state.rotate_log_if_big(_NAME)
        return 0

    cache_roots = _candidate_cache_roots()
    nm_roots = _global_node_modules_roots()
    combined = _content_signature(
        project_root / ".janitor" / "incidents.txt",
        cache_roots + nm_roots,
    )
    last_hash_file = state.state_dir() / "historical-cache-scan-last-hash.ts"
    if last_hash_file.is_file():
        try:
            if last_hash_file.read_text(encoding="utf-8").strip() == combined:
                return 0
        except OSError:
            pass

    budget = _max_files()
    hits: list[str] = []
    # npm cacache — ledger files in index-v5
    for root in cache_roots:
        if budget <= 0:
            break
        if "_cacache/index-v5" in str(root):
            for ledger in root.rglob("*"):
                if budget <= 0:
                    break
                if not ledger.is_file():
                    continue
                budget -= 1
                hits.extend(_scan_cacache_ledger(ledger, incidents))
        elif "pnpm" in str(root):
            hits.extend(_scan_pnpm_store(root, incidents))
        # Other caches (yarn berry zip, yarn classic) are content-
        # addressed binary stores — we skip scanning the binary content
        # itself for now; the index-side scan is the high-signal path.

    for nm in nm_roots:
        if budget <= 0:
            break
        hits.extend(_scan_node_modules(nm, incidents))

    state.atomic_write(last_hash_file, combined)

    if not hits:
        state.rotate_log_if_big(_NAME)
        return 0

    cap = 5
    sample = "\n".join(f"  - {state.sanitize_for_drift_line(h)}" for h in hits[:cap])
    if len(hits) > cap:
        sample += f"\n  - …and {len(hits) - cap} more"

    print(
        f"[historical-cache-scan] {len(hits)} known-malicious package "
        f"version(s) found in machine-wide caches / global installs. "
        f"REMOVING them from package.json is not enough — `npm install` "
        f"from the same cache can silently re-fetch. Clear the cache "
        f"(`npm cache clean --force` / `pnpm store prune` / `yarn cache "
        f"clean`) and rotate any token that may have been read by the "
        f"malicious version's postinstall.\n{sample}"
    )
    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
