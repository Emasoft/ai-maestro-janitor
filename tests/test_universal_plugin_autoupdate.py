"""Universal user-scope plugin auto-update (TRDD-YMTUPQER) — the three pieces, real, no mocks.

A user-scope plugin that fell behind its marketplace used to lag up to 1 h (the daemon's
`task_user_plugins_update` sweep) — the per-session `plugin-updates` detector could not
close the gap because it MUST NOT run `claude plugin update --scope user` itself (N sessions
across N projects would stampede the single machine-global command — issue #7 / PRRD S2.1).
The fix keeps that single-writer invariant: the detector ENQUEUES a per-plugin request; the
daemon (the sole user-scope writer) CONSUMES it on its next loop. The ai-maestro fleet + the
janitor itself are excluded (fleet-skew lockstep — the USER decision); the janitor's own fast
path is [[TRDD-Y9KM5RCJ]].

Three units under test, all pure/deterministic:
  * `global_state.{request,plugin_update_requests,clear}_plugin_update...` — the per-plugin
    request QUEUE, isolated via JANITOR_GLOBAL_STATE_DIR.
  * `plugin-updates.should_signal_user_update` — the detector's pure signal decision.
  * `daemon._consume_plugin_update_requests` — the daemon's clear-before-run consume. Only its
    GUARD paths (empty / non-user / no-`@` / fleet / self) are exercised: those never reach a
    subprocess, so the tests hit zero real `claude` CLI and zero network. A user-scope
    NON-fleet request is the ONLY branch that shells out, so no test enqueues one (that would
    mutate the real machine — the antithesis of a hermetic unit test).
"""

from __future__ import annotations

import importlib
import importlib.util as _u
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
daemon = importlib.import_module("daemon")
gs = importlib.import_module("global_state")


def _load_detector():
    """Import the hyphen-named detector module by path (not a valid import name)."""
    spec = _u.spec_from_file_location(
        "janitor_plugin_updates_under_test",
        str(_PROJECT_ROOT / "scripts" / "detectors" / "plugin-updates.py"),
    )
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pu = _load_detector()

_FLEET_ID = "ai-maestro-maintainer@ai-maestro-plugins"  # is_ai_maestro_plugin_id fast-path => True


@pytest.fixture(autouse=True)
def _isolate_janitor_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect every janitor global-state / DATA / HOME / project path to a per-test tmp tree
    so no test touches the real ~/.claude/janitor-global-state/, the plugin DATA dir, or the
    repo's own .janitor/logs (the fleet-skip consume path calls state.log_line)."""
    home = tmp_path / "_home"
    data = home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
    gsd = tmp_path / "_global-state"
    proj = tmp_path / "_project"
    for d in (home, data, gsd, proj):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)


# ---------- the per-plugin request QUEUE (global_state) --------------------

def test_queue_request_present_clear_roundtrip() -> None:
    """request() enqueues one entry, plugin_update_requests() returns it, clear() removes it."""
    assert gs.plugin_update_requests() == []
    gs.request_plugin_update("foo@mkt", "user", "0.1.0->0.2.0")
    reqs = gs.plugin_update_requests()
    assert len(reqs) == 1
    assert reqs[0]["plugin_id"] == "foo@mkt"
    assert reqs[0]["scope"] == "user"
    assert reqs[0]["reason"] == "0.1.0->0.2.0"
    gs.clear_plugin_update_request("foo@mkt", "user")
    assert gs.plugin_update_requests() == []


def test_queue_request_is_idempotent_per_key() -> None:
    """Re-enqueueing the same (plugin_id, scope) overwrites in place — the queue keeps ONE
    entry, and the latest reason wins."""
    gs.request_plugin_update("foo@mkt", "user", "a")
    gs.request_plugin_update("foo@mkt", "user", "b")
    gs.request_plugin_update("foo@mkt", "user", "c")
    reqs = gs.plugin_update_requests()
    assert len(reqs) == 1
    assert reqs[0]["reason"] == "c"


def test_queue_distinct_keys_coexist() -> None:
    """Different plugin_ids (and different scopes of the same id) are SEPARATE queue entries."""
    gs.request_plugin_update("foo@mkt", "user", "")
    gs.request_plugin_update("bar@mkt", "user", "")
    gs.request_plugin_update("foo@mkt", "local", "")  # same id, different scope => own key
    keys = {(r["plugin_id"], r["scope"]) for r in gs.plugin_update_requests()}
    assert keys == {("foo@mkt", "user"), ("bar@mkt", "user"), ("foo@mkt", "local")}


def test_queue_clear_one_key_leaves_the_others() -> None:
    """Clearing one key removes only that entry."""
    gs.request_plugin_update("foo@mkt", "user", "")
    gs.request_plugin_update("bar@mkt", "user", "")
    gs.clear_plugin_update_request("foo@mkt", "user")
    keys = {(r["plugin_id"], r["scope"]) for r in gs.plugin_update_requests()}
    assert keys == {("bar@mkt", "user")}


def test_queue_clear_when_absent_is_a_safe_noop() -> None:
    """clear() on a key that was never enqueued never raises and changes nothing."""
    gs.clear_plugin_update_request("nope@mkt", "user")
    assert gs.plugin_update_requests() == []


def test_queue_read_is_failopen_empty_when_no_file() -> None:
    """No queue file yet => plugin_update_requests() is a fail-open empty list."""
    assert gs.plugin_update_requests() == []


# ---------- the pure signal predicate (plugin-updates) --------------------

def _signal(**over) -> bool:
    """should_signal_user_update with the happy-path defaults, overridden per-test."""
    kw = dict(
        enabled=True, scope="user", is_self=False, is_fleet=False,
        user_scope_enabled=True, installed="0.1.0", latest="0.2.0",
    )
    kw.update(over)
    return pu.should_signal_user_update(**kw)


def test_signal_true_when_behind_user_enabled_notself_notfleet() -> None:
    """Behind + user-scope + opt-in on + not self + not fleet => signal the daemon."""
    assert _signal() is True


def test_signal_false_when_not_user_scope() -> None:
    """project/local scope is handled DIRECTLY by the detector, never signalled."""
    assert _signal(scope="local") is False
    assert _signal(scope="project") is False


def test_signal_false_when_plugin_disabled() -> None:
    """A disabled plugin is never updated."""
    assert _signal(enabled=False) is False


def test_signal_false_when_user_scope_optin_off() -> None:
    """CLAUDE_PLUGIN_OPTION_PLUGIN_AUTO_UPDATE_USER_SCOPE off => no user-scope signalling."""
    assert _signal(user_scope_enabled=False) is False


def test_signal_false_when_self() -> None:
    """The janitor itself is excluded here — it has its own fast release-triggered path."""
    assert _signal(is_self=True) is False


def test_signal_false_when_fleet() -> None:
    """ai-maestro fleet plugins update in lockstep, never one-at-a-time by this path."""
    assert _signal(is_fleet=True) is False


def test_signal_false_when_not_newer() -> None:
    """Equal installed/latest => already up to date, no signal."""
    assert _signal(installed="0.2.0", latest="0.2.0") is False


def test_signal_false_when_installed_ahead() -> None:
    """Installed strictly ahead of latest => never downgrade-signal."""
    assert _signal(installed="0.3.0", latest="0.2.0") is False


def test_signal_false_when_latest_missing() -> None:
    """Empty latest (transient marketplace read miss) => no signal."""
    assert _signal(latest="") is False


# ---------- the daemon consume-helper: GUARD paths only (daemon) ----------

def test_consume_noop_on_empty_queue() -> None:
    """Empty queue => returns 0 and touches nothing (no subprocess reached)."""
    assert daemon._consume_plugin_update_requests() == 0


def test_consume_skips_and_clears_non_user_scope() -> None:
    """A local-scope request is cleared and skipped BEFORE any subprocess (user-scope only)."""
    gs.request_plugin_update("foo@mkt", "local", "")
    assert daemon._consume_plugin_update_requests() == 0
    assert gs.plugin_update_requests() == [], "the consumed request must be cleared"


def test_consume_skips_and_clears_id_without_marketplace() -> None:
    """A plugin_id lacking `@<marketplace>` is cleared and skipped (nothing to update)."""
    gs.request_plugin_update("bare-id", "user", "")
    assert daemon._consume_plugin_update_requests() == 0
    assert gs.plugin_update_requests() == []


def test_consume_skips_and_clears_fleet_plugin() -> None:
    """A user-scope fleet plugin (@ai-maestro-plugins) is cleared and skipped (defense in
    depth): is_ai_maestro_plugin_id's suffix fast-path excludes the whole fleet — never a
    subprocess, so this stays hermetic."""
    gs.request_plugin_update(_FLEET_ID, "user", "0.1.0->0.2.0")
    assert daemon._consume_plugin_update_requests() == 0
    assert gs.plugin_update_requests() == []


def test_consume_clears_every_guard_hit_request_and_updates_nothing() -> None:
    """A queue of ONLY guard-hitting requests is fully drained, updates 0, reaches no CLI."""
    gs.request_plugin_update("foo@mkt", "local", "")   # non-user
    gs.request_plugin_update("bare-id", "user", "")    # no @
    gs.request_plugin_update(_FLEET_ID, "user", "")    # fleet
    assert daemon._consume_plugin_update_requests() == 0
    assert gs.plugin_update_requests() == [], "all consumed requests must be cleared"
