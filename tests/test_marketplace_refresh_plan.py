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
