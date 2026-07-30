"""Tests for the plugin-cache prune primitives (TRDD-a6d2fdaf, Fix A).

Real fixtures, no mocks: the integration tests build an actual cache tree with
`os.utime`-stamped version dirs and assert exactly which survive. The safety
property under test is the cardinal rule — a version a live session may have
loaded is NEVER pruned.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import cache_prune as cp  # type: ignore[import-not-found]  # noqa: E402

_DAY = 86400
_HOUR = 3600


# ---------- claude-session matcher (the safety oracle) --------------------

def test_is_claude_session_matches_real_cli() -> None:
    """argv[0] basename `claude`, or the versioned binary path, is a session."""
    assert cp._is_claude_session("claude --continue")
    assert cp._is_claude_session("/usr/local/bin/claude")
    assert cp._is_claude_session(
        "/Users/x/.local/share/claude/versions/2.1.180/claude"
    )


def test_is_claude_session_rejects_lookalikes() -> None:
    """Substring `claude` must NOT match — .claude paths, plugin names, the
    janitor's own python argv. A false positive only keeps MORE cache (safe), but
    we still mirror the rotator's precise matcher to avoid pinning the cutoff to
    some unrelated long-lived process."""
    assert not cp._is_claude_session(
        "python3 /Users/x/.claude/plugins/.../rotator.py tick"
    )
    assert not cp._is_claude_session(
        "node /Users/x/.claude/.../claude-plugins-validation/cli.js"
    )
    assert not cp._is_claude_session("claude-health-monitor --watch")
    assert not cp._is_claude_session("")


def test_oldest_claude_session_start_picks_earliest() -> None:
    """Returns now - the LARGEST etime among claude sessions; ignores non-claude."""
    now = 1_000_000
    sessions = [
        ("claude --continue", 2 * _HOUR),
        ("/usr/local/bin/claude", 50 * _HOUR),   # the oldest session
        ("python3 something.py", 999 * _HOUR),   # NOT a session — ignored
    ]
    assert cp.oldest_claude_session_start(sessions, now) == now - 50 * _HOUR


def test_oldest_claude_session_start_none_when_no_session() -> None:
    now = 1_000_000
    assert cp.oldest_claude_session_start([("python3 x.py", 10)], now) is None
    assert cp.oldest_claude_session_start([], now) is None


# ---------- cutoff arithmetic --------------------------------------------

def test_prune_cutoff_floor_only() -> None:
    """No live session → cutoff is simply now - min_age."""
    now = 1_000_000
    assert cp.prune_cutoff(
        now=now, min_age_s=7 * _DAY, oldest_session_start=None, session_margin_s=_DAY
    ) == now - 7 * _DAY


def test_prune_cutoff_pulled_back_behind_session() -> None:
    """A long session pulls the cutoff back behind its start (minus margin), so
    nothing it could have loaded is pruned — even past the min-age floor."""
    now = 1_000_000
    # Session started 25 days ago; margin 1 day → cutoff = now - 26d, NOT now - 7d.
    cutoff = cp.prune_cutoff(
        now=now,
        min_age_s=7 * _DAY,
        oldest_session_start=now - 25 * _DAY,
        session_margin_s=_DAY,
    )
    assert cutoff == now - 26 * _DAY


# ---------- per-plugin decision ------------------------------------------

def test_plan_plugin_prune_keeps_recent_and_pinned() -> None:
    """Keep newest-N ∪ pinned; prune the rest that predate the cutoff."""
    now = 1_000_000
    versions = ["2.0.0", "2.0.1", "2.0.2", "2.0.3", "2.0.4"]  # ascending
    # Everything is old (mtime well before cutoff).
    mtimes = {v: now - 30 * _DAY for v in versions}
    cutoff = now - 7 * _DAY
    prune, keep = cp.plan_plugin_prune(
        versions=versions,
        version_mtime=mtimes,
        pinned={"2.0.1"},        # a non-newest pinned version (a downgrade)
        keep_recent=2,           # keep 2.0.3, 2.0.4
        cutoff_epoch=cutoff,
        now=now,
    )
    assert set(keep) == {"2.0.3", "2.0.4", "2.0.1"}      # recent ∪ pinned
    assert set(prune) == {"2.0.0", "2.0.2"}              # old, not protected


def test_plan_plugin_prune_spares_young_versions() -> None:
    """A version younger than the cutoff is kept even if beyond newest-N — a live
    session may still hold it (this is the load-bearing safety case)."""
    now = 1_000_000
    versions = ["1.0.0", "1.0.1", "1.0.2"]
    mtimes = {
        "1.0.0": now - 30 * _DAY,   # old → prunable
        "1.0.1": now - 2 * _DAY,    # YOUNG → must be kept despite being beyond newest-1
        "1.0.2": now - 1 * _HOUR,   # newest (kept by keep_recent=1)
    }
    prune, keep = cp.plan_plugin_prune(
        versions=versions,
        version_mtime=mtimes,
        pinned=set(),
        keep_recent=1,
        cutoff_epoch=now - 7 * _DAY,
        now=now,
    )
    assert prune == ["1.0.0"]
    assert set(keep) == {"1.0.1", "1.0.2"}


def test_plan_plugin_prune_unknown_mtime_is_never_pruned() -> None:
    """A version with no recorded mtime defaults to `now` → kept (never delete
    what you can't date)."""
    now = 1_000_000
    prune, keep = cp.plan_plugin_prune(
        versions=["9.9.9", "9.9.8"],
        version_mtime={},                # both undateable
        pinned=set(),
        keep_recent=0,
        cutoff_epoch=now - 7 * _DAY,
        now=now,
    )
    assert prune == []
    assert set(keep) == {"9.9.9", "9.9.8"}


# ---------- pinned-version parsing ---------------------------------------

def test_pinned_versions_for_parses_installed_plugins() -> None:
    """The legacy `path`-keyed single-record shape still resolves, as a SET."""
    installed = {
        "version": 1,
        "plugins": {
            "claude-plugins-validation@emasoft-plugins": [
                {"path": "claude-plugins-validation/2.137.0", "enabled": True}
            ],
        },
    }
    assert cp.pinned_versions_for(
        installed, "claude-plugins-validation", "emasoft-plugins"
    ) == {"2.137.0"}
    assert cp.pinned_versions_for(installed, "nope", "emasoft-plugins") == set()
    assert cp.pinned_versions_for({}, "x", "y") == set()


def test_pinned_versions_for_returns_EVERY_record_not_just_the_first() -> None:
    """A real multi-record host: 4 records spanning 2 versions (issue #137).

    Verbatim shape from a live `installed_plugins.json` — one janitor record per ai-maestro
    agent workdir, three on 0.64.1 and one left behind on 0.60.1. The predecessor scanned the
    serialised entry for the FIRST `<plugin>/<version>` token, so it reported only 0.60.1 and
    `plan_plugin_prune` protected only that one — leaving three version dirs that three
    running agents were loading eligible for deletion.
    """
    installed = {
        "version": 1,
        "plugins": {
            "ai-maestro-janitor@ai-maestro-plugins": [
                {
                    "scope": "local",
                    "projectPath": "/Users/x/agents/scen001-manager",
                    "installPath": "/Users/x/.claude/plugins/cache/ai-maestro-plugins/"
                    "ai-maestro-janitor/0.60.1",
                    "version": "0.60.1",
                },
                {"scope": "local", "installPath": "/c/ai-maestro-janitor/0.64.1",
                 "version": "0.64.1", "auto": True},
                {"scope": "local", "installPath": "/c/ai-maestro-janitor/0.64.1",
                 "version": "0.64.1", "auto": True},
                {"scope": "local", "installPath": "/c/ai-maestro-janitor/0.61.1"},
            ],
        },
    }
    pins = cp.pinned_versions_for(installed, "ai-maestro-janitor", "ai-maestro-plugins")

    assert pins == {"0.60.1", "0.64.1", "0.61.1"}
    # The load-bearing consequence: every in-use version survives a prune that would
    # otherwise delete it.
    now = 1_000_000
    versions = ["0.60.1", "0.61.1", "0.64.1"]
    prune, keep = cp.plan_plugin_prune(
        versions=versions,
        version_mtime={v: now - 30 * _DAY for v in versions},
        pinned=pins,
        keep_recent=0,                    # no newest-N cushion — pins are the only guard
        cutoff_epoch=now - 7 * _DAY,
        now=now,
    )
    assert prune == [] and set(keep) == set(versions)


def test_a_record_with_no_parseable_version_contributes_nothing() -> None:
    """A malformed record yields no version rather than a wrong one.

    The empty set means "nothing known to be in use", which downgrades to `keep_recent`;
    a fabricated version would be asserted with false confidence.
    """
    installed = {
        "plugins": {
            "p@m": [
                {"scope": "local"},                       # no version, no path
                {"installPath": "/cache/p/not-a-version"},  # leaf is not semver-ish
                "a bare string, not a record",
            ],
        },
    }
    assert cp.pinned_versions_for(installed, "p", "m") == set()


def test_semver_sorted_ascending() -> None:
    assert cp._semver_sorted(["2.10.0", "2.9.0", "2.100.0", "2.9.1"]) == [
        "2.9.0",
        "2.9.1",
        "2.10.0",
        "2.100.0",
    ]


# ---------- end-to-end on a real cache tree -------------------------------

def _make_version(plugin_dir: Path, version: str, age_s: int, now: int) -> None:
    vd = plugin_dir / version
    vd.mkdir(parents=True)
    (vd / "marker").write_text("x", encoding="utf-8")  # non-empty dir
    ts = now - age_s
    os.utime(vd, (ts, ts))


def test_plan_and_apply_real_tree_no_session(tmp_path: Path) -> None:
    """Build a real cache tree, plan + apply, assert exactly the stale dirs were
    deleted and pinned/recent/young survive."""
    now = int(__import__("time").time())
    cache = tmp_path / "cache"
    plug = cache / "emasoft-plugins" / "claude-plugins-validation"
    _make_version(plug, "2.0.0", 40 * _DAY, now)   # old → prune
    _make_version(plug, "2.0.1", 30 * _DAY, now)   # old → prune
    _make_version(plug, "2.0.2", 20 * _DAY, now)   # old, but kept (newest-2)
    _make_version(plug, "2.0.3", 1 * _DAY, now)    # newest → keep
    installed = {
        "plugins": {
            "claude-plugins-validation@emasoft-plugins": [
                {"path": "claude-plugins-validation/2.0.3"}
            ]
        }
    }
    cutoff = cp.prune_cutoff(
        now=now, min_age_s=7 * _DAY, oldest_session_start=None, session_margin_s=_DAY
    )
    plans = cp.plan_cache_prune(cache, installed, keep_recent=2, cutoff_epoch=cutoff, now=now)
    removed, failed = cp.apply_prune_plan(plans)

    assert failed == []
    assert sorted(removed) == [
        "emasoft-plugins/claude-plugins-validation/2.0.0",
        "emasoft-plugins/claude-plugins-validation/2.0.1",
    ]
    survivors = {p.name for p in plug.iterdir()}
    assert survivors == {"2.0.2", "2.0.3"}  # newest-2 kept; the two old ones gone


def test_real_tree_long_session_protects_everything(tmp_path: Path) -> None:
    """SAFETY: when a claude session has been alive longer than every version's
    age, the cutoff is pulled back behind it and NOTHING is pruned — the session
    might have loaded any of these versions."""
    now = int(__import__("time").time())
    cache = tmp_path / "cache"
    plug = cache / "mp" / "somePlugin"
    _make_version(plug, "1.0.0", 40 * _DAY, now)
    _make_version(plug, "1.0.1", 30 * _DAY, now)
    _make_version(plug, "1.0.2", 1 * _DAY, now)
    # A session alive for 50 days → cutoff = now - 51d → older than every dir.
    oldest = now - 50 * _DAY
    cutoff = cp.prune_cutoff(
        now=now, min_age_s=7 * _DAY, oldest_session_start=oldest, session_margin_s=_DAY
    )
    plans = cp.plan_cache_prune(cache, {}, keep_recent=1, cutoff_epoch=cutoff, now=now)
    removed, failed = cp.apply_prune_plan(plans)
    assert removed == []
    assert failed == []
    assert {p.name for p in plug.iterdir()} == {"1.0.0", "1.0.1", "1.0.2"}
