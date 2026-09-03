"""Marketplace-refresh plan — which marketplaces actually back an installed plugin.

WHY (TRDD-5EHBPH6G): `claude plugin marketplace update` (bare) loops EVERY
registered marketplace inside the CLI itself. A host that has accumulated
one-off community marketplaces (corpus-distillation work, abandoned
experiments) can have hundreds registered while only a handful back a plugin
that is actually INSTALLED — the other ~230 are dead weight the daemon has no
business re-cloning on a cadence. Deriving the refresh set from
`installed_plugins.json` (`<plugin>@<marketplace>` install-record keys) turns
an O(all-registered) serial sweep into O(installed), which is what let the
sweep blow the daemon's workload timeout on every single run.

PURE — no I/O. The caller reads `installed_plugins.json` itself (daemon.py
already has the `_plugins_cache_root()` helper for that) and passes the
parsed dict in, so this stays independently testable with a literal.
"""

from __future__ import annotations


def marketplaces_from_installed(installed: dict) -> set[str]:
    """Every marketplace name backing at least one installed plugin.

    An install record is keyed `<plugin-name>@<marketplace-name>` (the same
    shape used everywhere else in this codebase, e.g. `fleet_plugin_updates.py`
    and the targeted plugin-update consumer in daemon.py). A key with no `@`
    is malformed/unexpected and is skipped rather than guessed at.
    """
    plugins = installed.get("plugins") if isinstance(installed, dict) else None
    if not isinstance(plugins, dict):
        return set()
    return {pid.rsplit("@", 1)[1] for pid in plugins if "@" in pid}


def refresh_plan(installed: dict, extra_csv: str | None) -> list[str]:
    """Sorted, deduped marketplace names to refresh this cadence.

    `installed`  — the parsed `installed_plugins.json` dict.
    `extra_csv`  — raw `CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_EXTRA` value
                   (comma-separated marketplace names); `None`/blank tokens
                   are dropped so an unset or trailing-comma env var is a
                   no-op rather than an empty-string entry in the plan.
    """
    names = marketplaces_from_installed(installed)
    for tok in (extra_csv or "").split(","):
        tok = tok.strip()
        if tok:
            names.add(tok)
    return sorted(names)
