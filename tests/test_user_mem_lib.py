"""Tests for user_mem_lib — the USER-MEMORY subsystem core (TRDD-4334aad0).

user_mem_lib implements a PRIVATE, agent-invisible user-memory store: one
markdown file per memory under a dedicated `user-mem/` subfolder of the
harness per-project memory dir, an immutable monotonic counter (numbers are
NEVER reused, even after delete — retire, never recycle), saving with/without
text, reading the previous user message from a transcript, routing search to
`memgrep find` with the +/- DSL, and reading a memory by its immutable number.

The privacy boundary itself (prompt erased from agent context, results shown
only via systemMessage) is a hook-level property tested in
test_user_mem_hooks.py; this file pins the storage + numbering + routing logic.

All filesystem state is redirected to tmp dirs so the real per-project memory
dir is never read or written.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import user_mem_lib  # noqa: E402

# --------------------------------------------------------------------------
# numbering: immutable, monotonic, never-reused
# --------------------------------------------------------------------------


def test_first_number_is_one(tmp_path):
    """A fresh store assigns 1 to the first memory."""
    store = user_mem_lib.UserMemStore(tmp_path / "user-mem")
    n = store.save("first memory")
    assert n == 1


def test_numbers_increment_monotonically(tmp_path):
    """Consecutive saves get strictly increasing numbers 1, 2, 3."""
    store = user_mem_lib.UserMemStore(tmp_path / "user-mem")
    assert store.save("a") == 1
    assert store.save("b") == 2
    assert store.save("c") == 3


def test_number_never_reused_after_delete(tmp_path):
    """Deleting memory #2 retires the number; the next save is #4, never #2."""
    store = user_mem_lib.UserMemStore(tmp_path / "user-mem")
    store.save("a")  # 1
    n2 = store.save("b")  # 2
    store.save("c")  # 3
    assert n2 == 2
    store.delete(2)
    # The retired number is gone from disk but the counter does not rewind.
    assert store.read(2) is None
    assert store.save("d") == 4


def test_counter_persists_across_store_instances(tmp_path):
    """A new UserMemStore over the same dir continues the counter (monotonic across processes)."""
    d = tmp_path / "user-mem"
    user_mem_lib.UserMemStore(d).save("a")  # 1
    user_mem_lib.UserMemStore(d).save("b")  # 2
    # Third, fresh instance: must yield 3, not restart at 1.
    assert user_mem_lib.UserMemStore(d).save("c") == 3


def test_counter_does_not_rewind_when_all_deleted(tmp_path):
    """Even after deleting every memory, the counter keeps climbing — numbers are permanent."""
    store = user_mem_lib.UserMemStore(tmp_path / "user-mem")
    store.save("a")  # 1
    store.save("b")  # 2
    store.delete(1)
    store.delete(2)
    assert store.save("c") == 3


def _save_one(args):
    """Worker for the concurrency test — save one memory in a fresh process."""
    import sys as _sys
    from pathlib import Path as _Path

    _root = _Path(__file__).resolve().parent.parent
    _sys.path.insert(0, str(_root / "scripts" / "lib"))
    import user_mem_lib as _uml  # noqa: PLC0415

    store_dir, text = args
    return _uml.UserMemStore(_Path(store_dir)).save(text)


def test_concurrent_saves_get_distinct_numbers(tmp_path):
    """N real concurrent processes saving to the same store get N distinct numbers (flock serialises the counter)."""
    import multiprocessing as mp

    d = tmp_path / "user-mem"
    n_workers = 12
    jobs = [(str(d), f"memory {i}") for i in range(n_workers)]
    # 'spawn' so each worker is a clean process (matches the real multi-session
    # case where independent Claude Code sessions each run the hook).
    ctx = mp.get_context("spawn")
    with ctx.Pool(n_workers) as pool:
        numbers = pool.map(_save_one, jobs)
    # Every number is unique (no collision) and the set is exactly 1..N.
    assert sorted(numbers) == list(range(1, n_workers + 1))
    # Every claimed number has a file on disk (no overwrite lost a memory).
    store = user_mem_lib.UserMemStore(d)
    for num in numbers:
        assert store.read(num) is not None


# --------------------------------------------------------------------------
# save: content lands on disk, with/without text
# --------------------------------------------------------------------------


def test_save_writes_text_to_disk(tmp_path):
    """save() persists the exact memory text to its numbered file (round-trips via read)."""
    store = user_mem_lib.UserMemStore(tmp_path / "user-mem")
    n = store.save("logistic regression failure at epoch 12")
    assert store.read(n) == "logistic regression failure at epoch 12"


def test_save_preserves_multiline_text(tmp_path):
    """A multi-line memory round-trips byte-for-byte through save/read."""
    store = user_mem_lib.UserMemStore(tmp_path / "user-mem")
    body = "line one\nline two\n\nline four with trailing"
    n = store.save(body)
    assert store.read(n) == body


def test_save_empty_text_is_rejected(tmp_path):
    """Saving empty/whitespace-only text raises (no empty memories, fail-fast)."""
    store = user_mem_lib.UserMemStore(tmp_path / "user-mem")
    for bad in ("", "   ", "\n\t  "):
        try:
            store.save(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


def test_saved_file_carries_the_number_in_frontmatter(tmp_path):
    """The saved markdown file records its immutable number in frontmatter (recoverable on listing)."""
    store = user_mem_lib.UserMemStore(tmp_path / "user-mem")
    n = store.save("alpha")
    path = store.path_for(n)
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert f"number: {n}" in text
    assert "alpha" in text


# --------------------------------------------------------------------------
# read: by number; missing returns None
# --------------------------------------------------------------------------


def test_read_missing_number_returns_none(tmp_path):
    """Reading a number that was never assigned returns None (no crash)."""
    store = user_mem_lib.UserMemStore(tmp_path / "user-mem")
    assert store.read(999) is None


def test_read_after_delete_returns_none(tmp_path):
    """Reading a deleted memory's number returns None."""
    store = user_mem_lib.UserMemStore(tmp_path / "user-mem")
    n = store.save("gone soon")
    assert store.read(n) == "gone soon"
    store.delete(n)
    assert store.read(n) is None


# --------------------------------------------------------------------------
# transcript: recover the previous user message (bare /to-user-mem)
# --------------------------------------------------------------------------


def _write_transcript(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def test_previous_user_message_skips_the_command_line(tmp_path):
    """The bare-form helper returns the user message BEFORE the /to-user-mem line, not the command itself."""
    tr = tmp_path / "t.jsonl"
    _write_transcript(
        tr,
        [
            {"type": "user", "message": {"role": "user", "content": "remember this important fact"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "ok"}},
            {"type": "user", "message": {"role": "user", "content": "/to-user-mem"}},
        ],
    )
    got = user_mem_lib.previous_user_message(tr)
    assert got == "remember this important fact"


def test_previous_user_message_handles_block_content(tmp_path):
    """A user message whose content is a list of text blocks is flattened to plain text."""
    tr = tmp_path / "t.jsonl"
    _write_transcript(
        tr,
        [
            {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "block one"}, {"type": "text", "text": "block two"}]}},
            {"type": "user", "message": {"role": "user", "content": "/to-user-mem"}},
        ],
    )
    got = user_mem_lib.previous_user_message(tr)
    assert "block one" in got and "block two" in got


def test_previous_user_message_missing_transcript_returns_none(tmp_path):
    """A missing transcript path yields None (the hook then reports nothing-to-save, never crashes)."""
    assert user_mem_lib.previous_user_message(tmp_path / "does-not-exist.jsonl") is None


def test_previous_user_message_ignores_meta_and_command_entries(tmp_path):
    """isMeta/command-only user entries are skipped when finding the real previous message."""
    tr = tmp_path / "t.jsonl"
    _write_transcript(
        tr,
        [
            {"type": "user", "message": {"role": "user", "content": "the real previous message"}},
            {"type": "user", "isMeta": True, "message": {"role": "user", "content": "<meta noise>"}},
            {"type": "user", "message": {"role": "user", "content": "/to-user-mem"}},
        ],
    )
    assert user_mem_lib.previous_user_message(tr) == "the real previous message"


# --------------------------------------------------------------------------
# search: routes to `memgrep find <query> <dir> --use-index`
# --------------------------------------------------------------------------


def test_build_search_argv_routes_to_memgrep_find(tmp_path):
    """build_search_argv produces `memgrep find <query> <user-mem-dir> --use-index` (only the user-mem dir)."""
    d = tmp_path / "user-mem"
    argv = user_mem_lib.build_search_argv("+keep -drop optional", d, memgrep="memgrep")
    assert argv[0] == "memgrep"
    assert argv[1] == "find"
    assert argv[2] == "+keep -drop optional"  # the whole query is ONE argv element (phrases/operators preserved)
    assert str(d) in argv
    assert "--use-index" in argv


def test_build_search_argv_preserves_quoted_phrase(tmp_path):
    """A quoted-phrase query is passed through verbatim as a single argv element for memgrep's DSL."""
    d = tmp_path / "user-mem"
    q = '+"logistic regression failure" -old'
    argv = user_mem_lib.build_search_argv(q, d, memgrep="memgrep")
    assert q in argv


def test_search_is_scoped_to_user_mem_dir_only(tmp_path):
    """The search argv references ONLY the user-mem dir — never the agent corpus (no leakage across stores)."""
    user_dir = tmp_path / "memory" / "user-mem"
    agent_dir = tmp_path / "memory"
    argv = user_mem_lib.build_search_argv("anything", user_dir, memgrep="memgrep")
    assert str(user_dir) in argv
    # The agent corpus path must not appear as a search root.
    assert str(agent_dir) not in [a for a in argv if a != str(user_dir)]


# --------------------------------------------------------------------------
# search results: numbered, end-to-end against the real memgrep binary
# --------------------------------------------------------------------------


def test_search_results_are_prefixed_with_immutable_number(tmp_path):
    """Live search via memgrep returns hits annotated with each memory's immutable number."""
    store = user_mem_lib.UserMemStore(tmp_path / "user-mem")
    store.save("the deployment script needs a keychain check")  # 1
    store.save("unrelated note about coffee")  # 2
    n3 = store.save("keychain rotation failed during deploy")  # 3
    results = store.search("+keychain -coffee")
    # Both keychain memories match; the coffee one is excluded by -coffee.
    nums = {r.number for r in results}
    assert 1 in nums
    assert n3 in nums
    assert 2 not in nums
    # Every result line carries its number for the user to act on.
    for r in results:
        assert r.number >= 1


def test_search_no_match_returns_empty(tmp_path):
    """A query matching nothing returns an empty result list (not an error)."""
    store = user_mem_lib.UserMemStore(tmp_path / "user-mem")
    store.save("alpha beta gamma")
    results = store.search("+nonexistentkeyword")
    assert results == []


# --------------------------------------------------------------------------
# memdir resolution
# --------------------------------------------------------------------------


def test_resolve_user_mem_dir_is_sibling_of_agent_corpus(tmp_path, monkeypatch):
    """The user-mem dir resolves to <project-memory-dir>/user-mem (sibling of the agent corpus)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    proj = "/Users/x/Code/Demo-Project/demo"
    d = user_mem_lib.resolve_user_mem_dir(project_dir=proj)
    assert d.name == "user-mem"
    # parent is the per-project memory dir under ~/.claude/projects/<slug>/memory
    assert d.parent.name == "memory"
    assert "Demo-Project" in str(d) or "demo" in str(d)
