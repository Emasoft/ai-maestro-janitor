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


# Marketplaces whose `source.source` is this are LOCAL DIRECTORIES on this host.
# Two independent reasons the janitor must never refresh one, either sufficient:
#   1. OWNERSHIP (owner ruling 2026-09-04): local marketplaces are an internal
#      mechanism of the ai-maestro SERVER harness. They are not the janitor's to
#      touch, regardless of whether refreshing them would work.
#   2. It is a no-op by construction — there is no remote to re-fetch from; the
#      "marketplace" is a path that is already on disk.
_LOCAL_SOURCE = "directory"


def filter_refreshable(
    names: list[str], known: dict | None
) -> tuple[list[str], dict[str, str]]:
    """Split a plan into (refreshable, {dropped_name: reason}).

    WHY (owner report 2026-09-04): `marketplace-refresh` logged
    `ai-maestro-local-marketplace exited rc=1` on EVERY hourly run — a permanent
    31/32 that never converged and never escalated. Two distinct defects fed it,
    and this filter closes both at the only place that can see them:

    * **An orphan install record.** The plan is derived from
      `installed_plugins.json` keys, and that file still carried
      `backend-infrastructure-engineer@ai-maestro-local-marketplace` for a
      marketplace that had since been RENAMED (to `-roles-` / `-custom-`). The
      CLI cannot refresh a name it does not know, so the item failed every hour,
      forever. Deriving intent from install records is right; treating a stale
      record as a live target is not.
    * **Ownership.** Both surviving local marketplaces are directory-source and
      belong to the ai-maestro server harness (see `_LOCAL_SOURCE`).

    **A DROP IS A SKIP, NOT A RETRY — this is the trade, stated so nobody has to
    reconstruct it.** Before this filter, an unregistered name failed with `rc=1`
    on every run, which was useless noise but *did* retry forever, so a registry
    entry that landed late would self-heal on the next tick. Now the name is
    dropped before the CLI is called. The steady state still self-heals (the name
    reappears in `known` and is refreshed again), but a marketplace that is
    installed and PERMANENTLY absent from the registry for some reason other than
    a rename — a truncated or partially-written registry — is now silent where it
    used to be loudly broken. That is a deliberate trade of a loud-but-ignored
    failure for a quiet advisory, and the advisory line in `daemon.py` is the only
    thing that will say so. Read it before concluding a marketplace is fine.

    `known` is the parsed `known_marketplaces.json` (the CLI's own registry,
    name -> record). **Passing `None` disables filtering entirely** and returns
    the plan unchanged — deliberate FAIL-OPEN: if that file is missing or
    unreadable we do not know what is registered, and silently refusing to
    refresh anything would be a far worse failure than the rc=1 this fixes.
    PURE — no I/O; the caller reads the registry (see `daemon.py`).
    """
    if not isinstance(known, dict):
        return list(names), {}
    keep: list[str] = []
    dropped: dict[str, str] = {}
    for name in names:
        record = known.get(name)
        if not isinstance(record, dict):
            dropped[name] = "not registered (orphan install record?)"
            continue
        source = record.get("source")
        src_kind = source.get("source") if isinstance(source, dict) else None
        if src_kind == _LOCAL_SOURCE:
            dropped[name] = "local directory marketplace (ai-maestro server owns it)"
            continue
        keep.append(name)
    return keep, dropped
