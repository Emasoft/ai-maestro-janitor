"""F4 (wikimem audit runtime): memory_settings' two read-modify-write sites are
flock-serialized — concurrent writers must not lose each other's updates.

Real I/O, no mocks: threads hammer the real functions against tmp dirs (flock
serializes across fds, so same-process threads contend exactly like two
sessions' processes do)."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import memory_settings  # noqa: E402

_RATE_KEYS = [
    "split_per_day",
    "repair_per_day",
    "harvest_per_day",
    "conflict_per_day",
    "consolidation_per_day",
    "atomize_per_day",
]


def test_concurrent_set_value_loses_no_update(monkeypatch, tmp_path):
    """F4: N threads each persist a DIFFERENT deviation concurrently; with the
    rmw lock every deviation survives (pre-fix the unlocked load->write
    interleaving could drop all but the last writer's key)."""
    monkeypatch.setenv("JANITOR_MEMORY_SETTINGS_DIR", str(tmp_path / "settings"))
    threads = [
        threading.Thread(target=memory_settings.set_value, args=(k, 7.0))
        for k in _RATE_KEYS
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    loaded = memory_settings.load()
    assert all(loaded[k] == 7.0 for k in _RATE_KEYS), loaded


def test_concurrent_harvest_marks_lose_no_entry(monkeypatch, tmp_path):
    """F4: concurrent harvest_mark_mirrored calls on the same (scope, root) all
    land in the watermark map — a lost entry means a wasteful duplicate
    re-mirror on the next harvest pass."""
    monkeypatch.setenv("JANITOR_MEMORY_SETTINGS_DIR", str(tmp_path / "settings"))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    root = tmp_path / "mem"
    names = [f"note-{i}.md" for i in range(8)]
    threads = [
        threading.Thread(
            target=memory_settings.harvest_mark_mirrored,
            args=("LOCAL", root, n, f"content of {n}"),
        )
        for n in names
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wm = memory_settings.harvest_watermark_read("LOCAL", root)
    assert sorted(wm) == sorted(names), wm
