"""The `[janitor-reload]` marker must not fire mid-refetch — janitor#271.

`/reload-plugins --force` evaluates the load while the purge/refetch it triggered is still
running, so the session comes back with FEWER plugins and MORE load errors than before
(reported there: 36 -> 33 plugins, 1 -> 10 errors, whole namespaces missing). The harness owns
that race. All the janitor owns is WHEN it asks for a reload, so it must not ask mid-refetch.

The load-bearing half of these tests is the STALE case. Measured on the author's host while
writing this: 17 `temp_git*` dirs were present, the youngest 34.6 hours old and the oldest 6.3
days — the harness abandons them and nothing sweeps them. A presence-only check would have
blocked every reload on that machine forever.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO / "scripts" / "lib"))

import dispatch  # noqa: E402


def _cache(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    cache = home / ".claude" / "plugins" / "cache"
    cache.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return cache


def test_an_empty_cache_is_settled(tmp_path, monkeypatch) -> None:
    """No staging dirs at all — nothing in flight."""
    _cache(tmp_path, monkeypatch)
    assert dispatch._plugin_cache_is_settled() is True


def test_a_FRESH_staging_dir_means_NOT_settled(tmp_path, monkeypatch) -> None:
    """A refetch started seconds ago — asking for a reload now is the janitor#271 bug."""
    cache = _cache(tmp_path, monkeypatch)
    (cache / "temp_github_1787228820740_u3y048").mkdir()
    assert dispatch._plugin_cache_is_settled() is False


def test_a_STALE_staging_dir_does_NOT_block_forever(tmp_path, monkeypatch) -> None:
    """THE case that matters: abandoned debris must not read as an in-flight refetch.

    17 of these were live on the author's host, youngest 34.6h. Presence-only logic would
    have stopped every reload on that machine permanently — a worse bug, and an invisible one.
    """
    cache = _cache(tmp_path, monkeypatch)
    stale = cache / "temp_git_1787125460269_i58bls"
    stale.mkdir()
    old = time.time() - (36 * 3600)
    import os

    os.utime(stale, (old, old))
    assert dispatch._plugin_cache_is_settled() is True


def test_an_unreadable_cache_FAILS_OPEN(tmp_path, monkeypatch) -> None:
    """No cache dir ⇒ settled. A guard that cannot see must never silently stop reloads."""
    home = tmp_path / "nowhere"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    assert dispatch._plugin_cache_is_settled() is True


def test_the_window_is_short_enough_to_not_park_a_reload(tmp_path, monkeypatch) -> None:
    """A refetch takes seconds; the window must not be so wide it defers a healthy reload.

    Pinned as a number so a future widening has to argue with this line rather than drift.
    """
    assert 10.0 <= dispatch._CACHE_REFETCH_WINDOW_S <= 300.0
