"""scripts/lib/marketplace_refresh_plan.py — the installed-backing refresh set
(TRDD-5EHBPH6G, acceptance box 1).

PURE function, no I/O — exercised directly with literal dicts, no mocking. The
whole point of the fix is that a host's hundreds of REGISTERED-but-unused
marketplaces (`known_marketplaces.json`) never enter this computation at all;
these tests don't even construct one, to prove the module has no path that
would read it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib"
_MODULE_PATH = _LIB / "marketplace_refresh_plan.py"
assert _MODULE_PATH.is_file(), f"module not found at {_MODULE_PATH}"


def _load():
    spec = importlib.util.spec_from_file_location("marketplace_refresh_plan", _MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mrp = _load()


def test_refresh_plan_is_installed_backing_plus_extras() -> None:
    """3 installed plugins across 2 marketplaces + 1 extra name -> plan is exactly
    those 3 names, regardless of how many OTHER marketplaces are registered on the
    host (this fixture never mentions a 4th/5th/…/262nd one — that's the fix)."""
    installed = {
        "plugins": {
            "frontend-design@claude-plugins-official": [{"scope": "user"}],
            "greptile@claude-plugins-official": [{"scope": "user"}],
            "ponytail@emasoft-plugins": [{"scope": "user"}],
        }
    }
    plan = mrp.refresh_plan(installed, "extra-marketplace")
    assert plan == ["claude-plugins-official", "emasoft-plugins", "extra-marketplace"]


def test_refresh_plan_dedupes_and_ignores_blank_extras() -> None:
    """Repeated/blank tokens in the extras CSV don't produce duplicate or empty entries."""
    installed = {"plugins": {"a@mkt-1": [{}], "b@mkt-1": [{}]}}
    plan = mrp.refresh_plan(installed, "mkt-1, , mkt-2,")
    assert plan == ["mkt-1", "mkt-2"]


def test_refresh_plan_empty_installed_and_no_extras_is_empty() -> None:
    """No installed plugins + no extras -> an empty plan (the daemon then logs a
    0/0 no-op and returns instead of calling the CLI at all)."""
    assert mrp.refresh_plan({"plugins": {}}, None) == []


def test_refresh_plan_ignores_malformed_keys() -> None:
    """An install-record key with no `@` is skipped rather than guessed at."""
    installed = {"plugins": {"malformed-key-no-at": [{}], "ok@mkt": [{}]}}
    assert mrp.refresh_plan(installed, None) == ["mkt"]


def test_marketplaces_from_installed_handles_missing_or_malformed_top_level() -> None:
    """A missing/non-dict `plugins` key (corrupt or partial installed_plugins.json)
    degrades to an empty set instead of raising."""
    assert mrp.marketplaces_from_installed({}) == set()
    assert mrp.marketplaces_from_installed({"plugins": "not-a-dict"}) == set()
    assert mrp.marketplaces_from_installed("not-a-dict-at-all") == set()


# ─── filter_refreshable — the hourly rc=1 defect (owner report 2026-09-04) ──────────
#
# `marketplace-refresh` logged `ai-maestro-local-marketplace exited rc=1` on EVERY run,
# a permanent 31/32 that never converged and escalated to nobody. Two causes, both
# pinned here: an ORPHAN install record naming a renamed marketplace, and LOCAL
# directory marketplaces that belong to the ai-maestro server harness.

def _known(**names: str) -> dict:
    """A `known_marketplaces.json`-shaped registry: name -> source kind."""
    return {n: {"source": {"source": kind}} for n, kind in names.items()}


def test_filter_drops_a_marketplace_that_is_not_registered() -> None:
    """The exact reported defect: an install record names a marketplace the CLI does
    not know (it was RENAMED), so refreshing it can only ever fail. Dropped, with a
    reason, instead of retried hourly forever."""
    known = _known(**{"ai-maestro-plugins": "github"})
    plan, dropped = mrp.filter_refreshable(
        ["ai-maestro-local-marketplace", "ai-maestro-plugins"], known
    )
    assert plan == ["ai-maestro-plugins"]
    assert "ai-maestro-local-marketplace" in dropped
    assert "not registered" in dropped["ai-maestro-local-marketplace"]


def test_filter_drops_local_directory_marketplaces() -> None:
    """Directory-source marketplaces belong to the ai-maestro server harness and have
    no remote to fetch — the janitor must not refresh them even though they ARE
    registered (owner ruling 2026-09-04)."""
    known = _known(**{
        "ai-maestro-local-roles-marketplace": "directory",
        "ai-maestro-local-custom-marketplace": "directory",
        "ai-maestro-plugins": "github",
    })
    plan, dropped = mrp.filter_refreshable(sorted(known), known)
    assert plan == ["ai-maestro-plugins"]
    assert set(dropped) == {
        "ai-maestro-local-roles-marketplace",
        "ai-maestro-local-custom-marketplace",
    }
    assert all("ai-maestro server" in why for why in dropped.values())


def test_filter_keeps_git_and_github_sources() -> None:
    """Only `directory` is local. A `git` remote is a real remote and stays."""
    known = _known(**{"gh-one": "github", "git-one": "git"})
    plan, dropped = mrp.filter_refreshable(["gh-one", "git-one"], known)
    assert plan == ["gh-one", "git-one"]
    assert dropped == {}


def test_filter_fails_open_when_the_registry_is_unreadable() -> None:
    """`None` (missing/corrupt known_marketplaces.json) must return the plan UNCHANGED.
    Refusing to refresh anything because we cannot read the registry would be a far
    worse failure than the rc=1 this filter fixes."""
    names = ["a", "b"]
    assert mrp.filter_refreshable(names, None) == (["a", "b"], {})
    assert mrp.filter_refreshable(names, "not-a-dict") == (["a", "b"], {})


def test_filter_drops_a_record_that_is_not_a_dict() -> None:
    """A corrupt registry entry is treated as unregistered, not crashed on."""
    plan, dropped = mrp.filter_refreshable(["weird"], {"weird": "not-a-dict"})
    assert plan == []
    assert "not registered" in dropped["weird"]


def test_filter_keeps_a_registered_entry_with_no_source_block() -> None:
    """A registered marketplace whose record lacks `source` is NOT local, so it stays
    refreshable — absence of evidence must not silently stop refreshing a real remote."""
    plan, dropped = mrp.filter_refreshable(["m"], {"m": {}})
    assert plan == ["m"]
    assert dropped == {}


def test_filter_also_drops_an_unregistered_OPERATOR_EXTRA() -> None:
    """`CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_EXTRA` is an explicit operator override,
    but it is NOT exempt from the registry check — you cannot refresh what the CLI does
    not know, so an unregistered extra would just be the rc=1 defect under a new name.
    Pinned because it makes an operator's explicit request subordinate to the registry,
    which is a deliberate choice rather than an oversight."""
    plan = mrp.refresh_plan({"plugins": {}}, "typo-marketplace,ai-maestro-plugins")
    assert plan == ["ai-maestro-plugins", "typo-marketplace"]
    keep, dropped = mrp.filter_refreshable(plan, _known(**{"ai-maestro-plugins": "github"}))
    assert keep == ["ai-maestro-plugins"]
    assert "not registered" in dropped["typo-marketplace"]
