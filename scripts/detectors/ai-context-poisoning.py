#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""AI-context-poisoning detector — npm + pip postinstall write audit.

Detects the shape of disclosed supply-chain attacks where a package's
postinstall / setup script writes to an agent-context file
(CLAUDE.md, .cursorrules, AGENTS.md, .claude/*, etc.) to silently
modify how the user's IDE-bound agent behaves on the next session.
Convergent intelligence across:
  * argus      — regex catalogue of context-file writes from npm/pip
  * sentinel-ai-o — CLAUDE.md attack-pattern corpus
  * honeybadger — write-detection in postinstall lifecycle scripts

Scope (v1, conservative):
  * scans `node_modules/**` for `.js` / `.cjs` / `.mjs` / `.ts` files
    that match AI_CONTEXT_WRITE_PATTERNS,
  * scans every `**/site-packages/**` for `.py` files that match the
    Python-shape patterns,
  * cross-checks against `is_known_config_loader()` so dotenv-cli and
    friends don't FP,
  * caps the file count to avoid burning compute on huge node_modules
    trees (`CLAUDE_PLUGIN_OPTION_AI_CONTEXT_POISONING_MAX_FILES`,
    default 5000).

Heartbeat invariants:
  * Self-scan guard — never scans the janitor's own tree.
  * Content-hash dedupe — silent if the relevant tree hasn't changed.
  * Read-only — never edits a file.
  * Bounded output — at most one drift line per heartbeat, capped sample.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import agent_config_patterns as acp  # type: ignore[import-not-found]  # noqa: E402
import issue_catalog  # type: ignore[import-not-found]  # noqa: E402
import security_helpers as sh  # type: ignore[import-not-found]  # noqa: E402
import state  # type: ignore[import-not-found]  # noqa: E402

_NAME = "ai-context-poisoning"

_NODE_SOURCE_SUFFIXES = (".js", ".cjs", ".mjs", ".ts", ".tsx")
_PY_SOURCE_SUFFIX = ".py"

# Per-suffix hard byte cap — a single payload-fat 100MB JS bundle can
# burn the whole heartbeat budget. 256 KB is enough to catch postinstall
# scripts (which are tiny by convention) while bounded against monsters.
_PER_FILE_BYTE_CAP = 256 * 1024


def _max_files() -> int:
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_AI_CONTEXT_POISONING_MAX_FILES", "5000")
    try:
        n = int(raw)
    except ValueError:
        return 5000
    return max(100, n)


def _iter_node_packages(project_root: Path) -> list[Path]:
    """Return every immediate `node_modules/<pkg>` directory under the
    project. Excludes the inner `.bin/` shim directory and the registry's
    own `.cache/` and `.package-lock.json` etc."""
    out: list[Path] = []
    nm = project_root / "node_modules"
    if not nm.is_dir():
        return out
    for entry in sorted(nm.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue  # .bin, .cache, .pnpm
        if entry.name.startswith("@"):
            # scope dir → recurse one level
            for sub in sorted(entry.iterdir()):
                if sub.is_dir() and not sub.name.startswith("."):
                    out.append(sub)
        else:
            out.append(entry)
    return out


def _iter_site_packages(project_root: Path) -> list[Path]:
    """Return every `site-packages` directory under the project (typically
    `.venv/lib/pythonX.Y/site-packages/` and similar). We deliberately do
    NOT recurse into system-wide site-packages — those are outside the
    project's blast radius."""
    out: list[Path] = []
    for venv_candidate in ("venv", ".venv", "env", ".env"):
        # `.env` is the gitignored env-vars file pattern; the directory
        # `.env/` is uncommon but used. Both shapes are checked.
        root = project_root / venv_candidate
        if not root.is_dir():
            continue
        # Walk a few levels deep looking for site-packages.
        for sp in root.glob("**/site-packages"):
            if sp.is_dir():
                out.append(sp)
    return out


def _pkg_name_from_node_dir(pkg_dir: Path, project_root: Path) -> str:
    """Reconstruct the npm package name from its node_modules path.
    Scope packages live at node_modules/@scope/name, so the npm name is
    `@scope/name`. Plain packages live at node_modules/name."""
    parts = pkg_dir.relative_to(project_root / "node_modules").parts
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2 and parts[0].startswith("@"):
        return f"{parts[0]}/{parts[1]}"
    return parts[-1]


def _scan_source_file(path: Path) -> list[str]:
    """Return matched-text snippets (max 80 chars each) from a single
    source file, or empty list if the file is clean / unreadable / too big."""
    try:
        if path.stat().st_size > _PER_FILE_BYTE_CAP:
            return []
    except OSError:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits = acp.find_ai_context_writes(text)
    if not hits:
        return []
    snips: list[str] = []
    for m in hits[:3]:  # cap snippets per file
        s = m.group(0).strip()
        if len(s) > 80:
            s = s[:77] + "…"
        snips.append(s)
    return snips


# npm lifecycle hooks that run WITHOUT the user asking. The presence of one is
# what separates "this package can write agent-context files" from "this package
# writes them when you install it" — the difference between a capability and an
# active supply-chain risk (janitor#110). `playwright` is the motivating case:
# its `scripts` is empty, so installing it writes nothing and the only trigger is
# an explicit `playwright init-agents` command.
_NPM_INSTALL_HOOKS = ("preinstall", "install", "postinstall", "prepare", "prepublish")


def _install_time_trigger(pkg_dir: Path) -> str | None:
    """The install hook that would run this package's code unasked, else None.

    Reads the package's OWN package.json. Unreadable/absent metadata returns None
    — a capability finding is still emitted, just at the lower severity, because
    claiming an install trigger we could not observe is the exact overstatement
    this function exists to prevent.
    """
    try:
        data = json.loads((pkg_dir / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return None
    for hook in _NPM_INSTALL_HOOKS:
        val = scripts.get(hook)
        if isinstance(val, str) and val.strip():
            return hook
    return None


def _scan_node_modules(project_root: Path, budget: int) -> list[tuple[str, str, str | None]]:
    """Return (drift bullet, path) pairs for any node_modules package that
    writes to an agent-context file from its installable shipping code.

    The path is returned alongside the bullet (not re-parsed from it later)
    so the issue-catalog raise below has the finding's LOCATION without
    reaching back into a formatted string."""
    issues: list[tuple[str, str, str | None]] = []
    seen_pkgs: set[str] = set()
    for pkg_dir in _iter_node_packages(project_root):
        if budget <= 0:
            break
        pkg_name = _pkg_name_from_node_dir(pkg_dir, project_root)
        if pkg_name in seen_pkgs:
            continue
        # Allowlist: known config-loaders (dotenv et al.) legitimately
        # rewrite dotfiles; not interesting for context-poisoning audit.
        if sh.is_known_config_loader(pkg_name, "npm"):
            continue
        for src in pkg_dir.rglob("*"):
            if budget <= 0:
                break
            if not src.is_file():
                continue
            if src.suffix.lower() not in _NODE_SOURCE_SUFFIXES:
                continue
            budget -= 1
            snips = _scan_source_file(src)
            if not snips:
                continue
            seen_pkgs.add(pkg_name)
            rel = src.relative_to(project_root)
            hook = _install_time_trigger(pkg_dir)
            # Say which state this is. The old wording ("writes to agent-context
            # file") read as an action already taken, for what is only a capability.
            trigger = (
                f"RUNS AT INSTALL via `{hook}`"
                if hook
                else "no install hook — reachable only by an explicit command"
            )
            issues.append((
                f"npm:{pkg_name} CAN write agent-context files from {rel} "
                f"({trigger}) — first hit: {snips[0]}",
                str(rel),
                hook,
            ))
            break  # one finding per package is enough
    return issues


def _scan_site_packages(project_root: Path, budget: int) -> list[tuple[str, str, str | None]]:
    """Return (drift bullet, path) pairs for any installed Python package
    whose source writes to an agent-context file."""
    issues: list[tuple[str, str, str | None]] = []
    seen_pkgs: set[str] = set()
    for sp in _iter_site_packages(project_root):
        if budget <= 0:
            break
        for src in sp.rglob("*" + _PY_SOURCE_SUFFIX):
            if budget <= 0:
                break
            if not src.is_file():
                continue
            budget -= 1
            # Reconstruct best-effort package name (dir under site-packages)
            parts = src.relative_to(sp).parts
            pkg_name = parts[0] if parts else src.name
            if pkg_name.endswith(".py"):
                pkg_name = pkg_name[:-3]
            if pkg_name in seen_pkgs:
                continue
            if sh.is_known_config_loader(pkg_name, "py"):
                continue
            snips = _scan_source_file(src)
            if not snips:
                continue
            seen_pkgs.add(pkg_name)
            rel = src.relative_to(project_root)
            issues.append((
                f"py:{pkg_name} CAN write agent-context files from {rel} — "
                f"first hit: {snips[0]}",
                str(rel),
                # No install-hook probe for Python: a wheel install runs nothing,
                # and a sdist's setup.py runs EVERYTHING, so presence of the file
                # would not discriminate. Reported as capability-only rather than
                # guessed either way.
                None,
            ))
    return issues


def _content_signature(project_root: Path) -> str:
    """Cheap dedupe signature — mtime + size of every package.json under
    node_modules + every top-level dir under site-packages. Avoids re-
    walking the full tree when nothing actually changed."""
    h = hashlib.sha256()
    nm = project_root / "node_modules"
    if nm.is_dir():
        for pj in sorted(nm.rglob("package.json")):
            try:
                st = pj.stat()
                h.update(f"{pj}|{st.st_mtime_ns}|{st.st_size}\n".encode())
            except OSError:
                pass
    for sp in _iter_site_packages(project_root):
        try:
            entries = sorted(sp.iterdir())
        except OSError:
            continue
        for e in entries:
            try:
                st = e.stat()
                h.update(f"{e}|{st.st_mtime_ns}|{st.st_size}\n".encode())
            except OSError:
                pass
    return h.hexdigest()


def main() -> int:
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_AI_CONTEXT_POISONING_ENABLED", True,
    ):
        return 0
    # Hard self-scan guard — janitor never scans itself.
    if state.is_self_scan_target():
        return 0

    state.init_state()
    project_root = state.project_root()

    # Fast-exit when neither tree exists.
    if not (project_root / "node_modules").is_dir() and not _iter_site_packages(project_root):
        state.rotate_log_if_big(_NAME)
        return 0

    combined = _content_signature(project_root)
    last_hash_file = state.state_dir() / "ai-context-poisoning-last-hash.ts"
    if last_hash_file.is_file():
        try:
            if last_hash_file.read_text(encoding="utf-8").strip() == combined:
                return 0  # nothing changed → silent
        except OSError:
            pass

    budget = _max_files()
    findings: list[tuple[str, str, str | None]] = []
    findings.extend(_scan_node_modules(project_root, budget))
    # Re-compute budget for python scan based on what node consumed:
    # cheap approximation — give each scan half the total budget if both
    # trees are present.
    py_budget = max(100, budget // 2)
    findings.extend(_scan_site_packages(project_root, py_budget))

    state.atomic_write(last_hash_file, combined)

    if not findings:
        # Clean now — withdraw every standing proposal. Reconciling ONLY when there is something to
        # report would leave the last proposal on the board forever, and that is exactly the one that
        # matters: the finding the user just fixed.
        for uid in issue_catalog.reconcile("AICTX-002", []):
            state.log_line(_NAME, f"withdrew TRDD-{uid} — the poisoned package is gone")
        state.rotate_log_if_big(_NAME)
        return 0

    issues = [f[0] for f in findings]
    cap = 5
    sample = "\n".join(f"  - {state.sanitize_for_drift_line(s)}" for s in issues[:cap])
    if len(issues) > cap:
        sample += f"\n  - …and {len(issues) - cap} more"

    hint = sh.security_agent_hint(
        "skill-bundle",
        enabled=state.is_truthy_env(sh.SECURITY_AGENT_HINT_ENV, True),
    )
    # Count the states separately. The old line said every hit "writes … at
    # install time", which is the CRITICAL claim, for findings that were mostly
    # capability-only — so a documented opt-in CLI read as an active compromise.
    at_install = sum(1 for _i, _p, hook in findings if hook)
    if at_install:
        headline = (
            f"{at_install} of {len(issues)} installed package(s) write to "
            f"agent-context file(s) AT INSTALL TIME — this is the shape of "
            f"disclosed supply-chain attacks that silently modify agent behaviour."
        )
    else:
        headline = (
            f"{len(issues)} installed package(s) CAN write agent-context file(s) "
            f"(CLAUDE.md / .cursorrules / .claude/* / AGENTS.md / etc.), none at "
            f"install time — a capability to be aware of, not an incident. The "
            f"realistic control is guarding the INVOCATION, since that is the only "
            f"trigger."
        )
    print(f"[ai-context-poisoning] {headline}\n{sample}" + (f"\n{hint}" if hint else ""))

    # Route each finding into the issue catalog, capped per fire.
    raised = 0
    skipped = 0
    for issue, path, hook in findings:
        if raised >= issue_catalog.MAX_RAISES_PER_FIRE:
            skipped += 1
            continue
        # Severity is the STATE, not the shape: an install hook means the code
        # runs unasked (state 2), no hook means the capability is only reachable
        # by an explicit command (state 1). Reporting state 1 at state 2's
        # severity is what produced a `critical` ticket for a documented opt-in
        # feature, and what teaches the reader to discount the detector for the
        # day a real state-2 package appears (janitor#110).
        r = issue_catalog.raise_issue(
            "AICTX-002",
            where=path,
            evidence=[path],
            severity="critical" if hook else "low",
            path=path,
            found=issue,
        )
        if r.first_seen and r.line:
            print(r.line)
        elif not r.ok:
            state.log_line(_NAME, f"could not raise AICTX-002: {r.why}")
        raised += 1
    if skipped:
        state.log_line(
            _NAME,
            f"{skipped} AICTX-002 raise(s) skipped by the {issue_catalog.MAX_RAISES_PER_FIRE}-per-fire cap",
        )

    # Withdraw the proposals whose finding is no longer in the scan. A detector cannot CLEAR what it
    # can no longer name — a scan yields the findings that EXIST, and the vanished ones are by
    # definition absent from the result — so the reconcile is driven by what IS here, not by what was.
    for uid in issue_catalog.reconcile("AICTX-002", [p for _, p, _h in findings]):
        state.log_line(_NAME, f"withdrew TRDD-{uid} — the poisoned package is gone")

    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
