"""Fleet-wide plugin updates — update EVERY project's enabled plugins, not just the live one.

THE BUG THIS EXISTS FOR. `claude plugin update` takes no project argument — only `--scope` — so a
`local`/`project`-scope update resolves *which project* from the **process cwd**. Every existing
update path omits `cwd=` and works only by accident: a per-session detector already runs with its
process cwd set to its own project. A project with **no live Claude session is therefore never
updated by anyone**, and nothing reports that. Measured on the host this was written for: 101
local-scope install records across 79 project paths, six of them pinned at `ai-maestro-plugin`
2.5.0 while the marketplace was at 2.11.0.

So the fix is one keyword argument — `cwd=project_path` in `update_target` — and everything else
here is the plumbing that lets a session-less actor discover which (plugin, project) pairs exist.

FAIL-OPEN, and note it means SKIP here, not "act anyway". A project we cannot read is simply not
updated this pass; the next pass retries. That is the safe direction for an idempotent write. The
DESTRUCTIVE sibling (`prune_dead_installs.py`) inverts the burden of proof — it must PROVE a path
is gone before deleting its record, because there "cannot see it" and "it is gone" call for
opposite actions.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import state  # noqa: E402

# Scopes whose updates are cwd-relative. `user`/`managed` are machine-global and are the daemon's
# existing `task_user_plugins_update` job — deliberately not touched here.
PROJECT_SCOPES = ("local", "project")

# Which settings file carries a scope's `enabledPlugins` map.
_SETTINGS_FOR_SCOPE = {
    "local": ".claude/settings.local.json",
    "project": ".claude/settings.json",
}

# Bound one sweep. A host with a pathological registry must not turn a heartbeat into an hour of
# subprocess calls; the leftovers are picked up on the next pass.
MAX_TARGETS_PER_SWEEP = 60
UPDATE_TIMEOUT_S = 120


def registry_path() -> Path:
    """Claude Code's authoritative install registry — the same file `version_update_lib` reads."""
    return Path.home() / ".claude" / "plugins" / "installed_plugins.json"


@dataclass(frozen=True)
class Target:
    """One (plugin, scope, project) the sweep may update."""

    plugin_id: str  # "<name>@<marketplace>" — the registry key IS the id (no inner id field)
    scope: str
    project_path: str

    @property
    def settings_path(self) -> Path:
        return Path(self.project_path) / _SETTINGS_FOR_SCOPE[self.scope]


def enabled_plugins(settings_path: Path) -> list[str]:
    """Plugin ids explicitly enabled in a settings file, or `[]` on absent/malformed.

    THE shared implementation. This logic was copy-pasted in four detectors
    (`local-plugins-update`, `project-plugins-update`, `marketplace-refresh`,
    `janitor-install-scope`), each with its own log label and its own subtly different tolerance.
    One copy means one behaviour — and it is the gate the owner's wording asks for: *enabled and
    active* plugins, so a record present in the registry but switched OFF in the project is not
    "up to date" work, it is a plugin the project chose not to run.

    A value must be exactly `True`. Claude Code writes booleans here; anything else (a string, a
    nested object from a future schema) is NOT read as enabled, because guessing "truthy" would
    silently update a plugin a project had disabled in a spelling we do not understand.
    """
    try:
        raw = settings_path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    enabled = data.get("enabledPlugins")
    if not isinstance(enabled, dict):
        return []
    return [p for p, flag in enabled.items() if isinstance(p, str) and p and flag is True]


def plugin_is_enabled(plugin_id: str, enabled: list[str]) -> bool:
    """True iff `plugin_id` ("<name>@<market>") appears in an `enabledPlugins` list.

    Accepts BOTH spellings the settings files use in the wild: the fully-qualified
    `name@marketplace` and the bare `name` (the shape `janitor-install-scope` already tolerates).
    Matching only the qualified form would silently skip every project using the short one.
    """
    name = plugin_id.split("@", 1)[0]
    for entry in enabled:
        if entry == plugin_id or entry == name or entry.startswith(name + "@"):
            return True
    return False


def _records(registry: dict) -> list[tuple[str, dict]]:
    """`(plugin_id, record)` for every install record. The registry maps id → LIST of records."""
    out: list[tuple[str, dict]] = []
    plugins = registry.get("plugins")
    if not isinstance(plugins, dict):
        return out
    for plugin_id, entries in plugins.items():
        if not isinstance(plugin_id, str):
            continue
        if isinstance(entries, dict):  # tolerate a single-record spelling
            entries = [entries]
        if not isinstance(entries, list):
            continue
        for rec in entries:
            if isinstance(rec, dict):
                out.append((plugin_id, rec))
    return out


def read_registry() -> dict:
    """Parse the install registry, or `{}` when it is missing/unreadable/malformed (fail-open)."""
    try:
        data = json.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def enumerate_targets(registry: dict | None = None) -> list[Target]:
    """Every (plugin, scope, project) this sweep should update, deduped and ordered.

    Filters, in order, each for a stated reason:

    * scope in `PROJECT_SCOPES` — user/managed scope is already the daemon's existing job.
    * `projectPath` present and still a DIRECTORY. A path we cannot see is skipped, not updated:
      running `claude plugin update` with a cwd that does not exist would fail anyway, and on this
      host 71 of 79 recorded paths are deleted agent workdirs and session scratchpads.
    * the plugin is ENABLED in that project's own settings file (`plugin_is_enabled`).

    Deduped on (plugin_id, scope, project) because one project legitimately holds several records
    for one plugin over its history, and updating it twice is pure waste.
    """
    reg = read_registry() if registry is None else registry
    seen: set[tuple[str, str, str]] = set()
    out: list[Target] = []
    enabled_cache: dict[Path, list[str]] = {}
    for plugin_id, rec in _records(reg):
        scope = rec.get("scope")
        project = rec.get("projectPath")
        if scope not in PROJECT_SCOPES or not isinstance(project, str) or not project:
            continue
        key = (plugin_id, scope, project)
        if key in seen:
            continue
        try:
            if not Path(project).is_dir():
                continue
        except OSError:
            continue  # unreadable ⇒ skip this pass (fail-open = do nothing, not do it blindly)
        target = Target(plugin_id=plugin_id, scope=scope, project_path=project)
        sp = target.settings_path
        if sp not in enabled_cache:
            enabled_cache[sp] = enabled_plugins(sp)
        if not plugin_is_enabled(plugin_id, enabled_cache[sp]):
            continue
        seen.add(key)
        out.append(target)
    return out


def update_target(target: Target, *, timeout_s: int = UPDATE_TIMEOUT_S) -> tuple[bool, str]:
    """Run `claude plugin update <id> --scope <scope>` FOR THAT PROJECT. Returns `(ok, detail)`.

    `cwd=target.project_path` IS the fix this module exists for. The CLI has no project flag, so
    the working directory is the only channel that tells it which project's `local`/`project`
    scope to act on — which is why every session-less caller before this one silently updated
    nothing (or, worse, would have updated whichever project the daemon happened to start in).
    """
    try:
        proc = subprocess.run(
            ["claude", "plugin", "update", target.plugin_id, "--scope", target.scope],
            cwd=target.project_path,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    detail = (proc.stdout or proc.stderr or "").strip().splitlines()
    return proc.returncode == 0, (detail[-1][:200] if detail else "")


def sweep(*, max_targets: int = MAX_TARGETS_PER_SWEEP, log: str = "fleet-plugins-update") -> list[str]:
    """Update every enabled plugin in every live project. Returns the ids actually updated.

    The caller bumps the reload generation on a non-empty result — an updated plugin is not live
    until the session reloads ("restart required to apply", per the CLI's own help), so an update
    without a reload is a change nobody is running.
    """
    targets = enumerate_targets()
    if not targets:
        return []
    updated: list[str] = []
    for target in targets[:max_targets]:
        ok, detail = update_target(target)
        if ok:
            updated.append(target.plugin_id)
        else:
            state.log_line(log, f"  {target.plugin_id} @ {target.project_path}: FAILED {detail}")
    if len(targets) > max_targets:
        # Never silently truncate: a capped sweep must say so, or a permanently-behind tail looks
        # like a fully-updated fleet (repo invariant: no silent caps).
        state.log_line(log, f"  capped at {max_targets}/{len(targets)} targets — rest next pass")
    return updated
