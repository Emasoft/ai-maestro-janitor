"""Tests for the MEMORY.md ↔ wikimem bridge line (owner directive 2026-07-25).

`MEMORY.md` is the HARNESS's file; the janitor maintains exactly ONE line in it — a
link to the project's `<project>-overview.md` wiki page — and interferes with nothing
else. These tests pin that contract from both sides:

  * the ONE line is added when missing and re-added after deletion, and
  * every OTHER byte of the file is preserved, because the previous model "stubbed"
    MEMORY.md and destroyed harness-written pointer lines. That regression is the
    reason this module is append-only, so the preservation assertions below are the
    real point of the file — not the happy path.

Real filesystem throughout (tmp_path), no mocks: the whole contract is about what
actually lands on disk.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import memory_bridge as mbr  # noqa: E402  -- local module, needs the sys.path above

# A realistic harness-written MEMORY.md: pointer lines the janitor must never touch.
HARNESS_CONTENT = """# MEMORY

- [Some fact the harness recorded](some-fact.md) — a hook
- [Another harness memory](another.md) — another hook
"""


def _scope(tmp_path: Path, *, memory_md: str | None = HARNESS_CONTENT,
           overview: str | None = "demo-overview.md") -> Path:
    """Build a scope root with an optional MEMORY.md and an optional overview page."""
    root = tmp_path / "memory"
    (root / "wiki").mkdir(parents=True)
    if memory_md is not None:
        (root / mbr.MEMORY_MD).write_text(memory_md, encoding="utf-8")
    if overview is not None:
        (root / "wiki" / overview).write_text("# Overview\n", encoding="utf-8")
    return root


# --------------------------------------------------------------------------- #
# find_overview_page
# --------------------------------------------------------------------------- #

def test_finds_overview_page_recursively_under_wiki(tmp_path: Path) -> None:
    """The entry page is found recursively — a curated corpus keeps it under wiki/."""
    root = _scope(tmp_path)
    found = mbr.find_overview_page(root)
    assert found is not None and found.parent.name == "wiki"


def test_overview_found_by_suffix(tmp_path: Path) -> None:
    """Matches memgrep's own rule: basename ends with `-overview.md`."""
    root = _scope(tmp_path, overview="ai-maestro-janitor-overview.md")
    found = mbr.find_overview_page(root)
    assert found is not None and found.name == "ai-maestro-janitor-overview.md"


def test_overview_absent_returns_none(tmp_path: Path) -> None:
    """A corpus that was never bootstrapped has no entry page."""
    assert mbr.find_overview_page(_scope(tmp_path, overview=None)) is None


def test_overview_match_is_case_insensitive(tmp_path: Path) -> None:
    """memgrep lowercases before matching, so a capitalised page must still resolve."""
    root = _scope(tmp_path, overview="Demo-Overview.md")
    assert mbr.find_overview_page(root) is not None


def test_multiple_overviews_pick_is_deterministic(tmp_path: Path) -> None:
    """Two candidates must not make the bridge flap between runs."""
    root = _scope(tmp_path, overview="b-overview.md")
    (root / "a-overview.md").write_text("# A\n", encoding="utf-8")
    first = mbr.find_overview_page(root)
    second = mbr.find_overview_page(root)
    assert first == second
    assert first is not None and first.name == "a-overview.md"  # shallower path wins


# --------------------------------------------------------------------------- #
# ensure_bridge_line — the contract
# --------------------------------------------------------------------------- #

def test_adds_the_bridge_line_when_missing(tmp_path: Path) -> None:
    """The ONE line the janitor owns is appended when absent."""
    root = _scope(tmp_path)
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_ADDED
    text = (root / mbr.MEMORY_MD).read_text(encoding="utf-8")
    assert "demo-overview.md" in text


def test_harness_content_is_preserved_byte_for_byte(tmp_path: Path) -> None:
    """THE regression guard: appending the bridge must not disturb harness lines."""
    root = _scope(tmp_path)
    mbr.ensure_bridge_line(root)
    text = (root / mbr.MEMORY_MD).read_text(encoding="utf-8")
    assert text.startswith(HARNESS_CONTENT)
    for line in HARNESS_CONTENT.splitlines():
        assert line in text


def test_exactly_one_line_is_added(tmp_path: Path) -> None:
    """'Exactly ONE line' is literal — count them."""
    root = _scope(tmp_path)
    before = len((root / mbr.MEMORY_MD).read_text(encoding="utf-8").splitlines())
    mbr.ensure_bridge_line(root)
    after = len((root / mbr.MEMORY_MD).read_text(encoding="utf-8").splitlines())
    assert after == before + 1


def test_is_idempotent(tmp_path: Path) -> None:
    """A second run reports PRESENT and leaves the file byte-identical."""
    root = _scope(tmp_path)
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_ADDED
    once = (root / mbr.MEMORY_MD).read_bytes()
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_PRESENT
    assert (root / mbr.MEMORY_MD).read_bytes() == once


def test_re_adds_after_deletion(tmp_path: Path) -> None:
    """'Re-add if it is deleted' — the explicit duty in the owner's directive."""
    root = _scope(tmp_path)
    mbr.ensure_bridge_line(root)
    (root / mbr.MEMORY_MD).write_text(HARNESS_CONTENT, encoding="utf-8")  # user deleted it
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_ADDED
    assert "demo-overview.md" in (root / mbr.MEMORY_MD).read_text(encoding="utf-8")


def test_never_creates_memory_md(tmp_path: Path) -> None:
    """Creation is the harness's business; a janitor-made MEMORY.md would be a
    second system claiming the same filename."""
    root = _scope(tmp_path, memory_md=None)
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_NO_MEMORY_MD
    assert not (root / mbr.MEMORY_MD).exists()


def test_no_overview_leaves_file_untouched(tmp_path: Path) -> None:
    """With no entry page there is nothing to point at — never write a broken link."""
    root = _scope(tmp_path, overview=None)
    before = (root / mbr.MEMORY_MD).read_bytes()
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_NO_OVERVIEW
    assert (root / mbr.MEMORY_MD).read_bytes() == before


def test_respects_a_hand_written_link(tmp_path: Path) -> None:
    """A human who wrote their own link to the same page must not get a duplicate."""
    root = _scope(tmp_path, memory_md="# MEMORY\n\nSee [the wiki](wiki/demo-overview.md).\n")
    before = (root / mbr.MEMORY_MD).read_bytes()
    assert mbr.ensure_bridge_line(root) == mbr.OUTCOME_PRESENT
    assert (root / mbr.MEMORY_MD).read_bytes() == before


def test_file_without_trailing_newline_is_not_mangled(tmp_path: Path) -> None:
    """Appending to a file whose last line lacks \\n must not join two lines."""
    root = _scope(tmp_path, memory_md="# MEMORY\n\n- [a](a.md) — hook")
    mbr.ensure_bridge_line(root)
    lines = (root / mbr.MEMORY_MD).read_text(encoding="utf-8").splitlines()
    assert lines[-2] == "- [a](a.md) — hook"
    assert "demo-overview.md" in lines[-1]


def test_link_is_relative_not_absolute(tmp_path: Path) -> None:
    """PROJECT-scope MEMORY.md is PUSHED — an absolute path would leak one machine's
    layout into every contributor's clone."""
    root = _scope(tmp_path)
    mbr.ensure_bridge_line(root)
    text = (root / mbr.MEMORY_MD).read_text(encoding="utf-8")
    assert "(wiki/demo-overview.md)" in text
    assert str(tmp_path) not in text


def test_accepts_a_string_scope_root(tmp_path: Path) -> None:
    """The documented shell one-liner (and the bootstrap skill) pass a plain STRING.
    Requiring Path made that crash with TypeError mid-chore — regression guard."""
    root = _scope(tmp_path)
    assert mbr.ensure_bridge_line(str(root)) == mbr.OUTCOME_ADDED
    assert mbr.find_overview_page(str(root)) is not None


def test_never_raises_on_unreadable_scope(tmp_path: Path) -> None:
    """Runs on the SessionStart path — it must fail OPEN, never cost a session."""
    assert mbr.ensure_bridge_line(tmp_path / "does-not-exist") == mbr.OUTCOME_NO_MEMORY_MD


def test_lock_held_skips_without_touching_the_file(tmp_path: Path, monkeypatch) -> None:
    """TRDD-7YHT3FNK P3: the append rides the scope's commit lock; a held lock means
    another janitor writer is mid-edit — skip (SessionStart re-runs next session)
    and leave MEMORY.md byte-identical."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    root = _scope(tmp_path)
    before = (root / mbr.MEMORY_MD).read_text(encoding="utf-8")
    import memory_txn
    with memory_txn.commit_lock(root) as held:
        assert held is True
        # Same process re-acquisition would deadlock/no-op differently per-OS; probe
        # via a CHILD process, the real contention shape.
        import subprocess
        import sys as _sys
        code = (
            "import sys; sys.path.insert(0, %r); import memory_bridge as m; "
            "print(m.ensure_bridge_line(%r))" % (str(Path(mbr.__file__).parent), str(root))
        )
        out = subprocess.run(
            [_sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30,
            env={**__import__("os").environ, "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "gstate")},
        )
    assert out.stdout.strip() == mbr.OUTCOME_LOCK_HELD, out.stderr
    assert (root / mbr.MEMORY_MD).read_text(encoding="utf-8") == before


def test_scope_lock_path_resolves_symlinks(tmp_path: Path, monkeypatch) -> None:
    """TRDD-7YHT3FNK P3: memgrep's Rust write_gate hashes the CANONICAL scope root;
    the Python side must hash the same string or a symlinked invocation forks the
    lock and the two languages stop excluding each other."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    import memory_txn
    # The dir MUST be named `memory`: since TRDD-X4LI97IK a root with any other basename is
    # treated as out-of-scope and collapses to the shared sentinel, so a `real-memory`/
    # `link-memory` pair would compare two sentinels and pass no matter what resolve() did —
    # a test that agrees with itself. Naming it `memory` keeps the hash path under test.
    real = tmp_path / "real" / "memory"
    real.mkdir(parents=True)
    link = tmp_path / "link-memory"
    link.symlink_to(real)
    assert memory_txn._scope_lock_path(link) == memory_txn._scope_lock_path(real)
    assert memory_txn._scope_lock_path(real).name.startswith("memory-maint-")
    assert memory_txn._scope_lock_path(real).name != memory_txn._OUT_OF_SCOPE_LOCK_NAME


def test_out_of_scope_roots_share_one_lock_matching_the_rust_constant(tmp_path, monkeypatch) -> None:
    """TRDD-X4LI97IK: a root that is not a `.../memory` scope must not mint its own lock.

    memgrep's `scope_root_for` falls back to a page's own parent dir when there is no `memory`
    ancestor, which made the machine-wide lock key unbounded (1,128 orphan files). Both languages
    now collapse those onto ONE sentinel — and the sentinel STRING is read back out of the Rust
    source here, because a constant duplicated across two languages is exactly the drift
    TRDD-7YHT3FNK exists to prevent, and a hand-copied literal in this test would not notice.
    """
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    import memory_txn
    a = tmp_path / "notmemory"
    b = tmp_path / "somewhere-else"
    a.mkdir()
    b.mkdir()
    assert memory_txn._scope_lock_path(a) == memory_txn._scope_lock_path(b)
    assert memory_txn._scope_lock_path(a).name == memory_txn._OUT_OF_SCOPE_LOCK_NAME

    rust = (Path(__file__).resolve().parents[1] / "scripts/memgrep/src/write_gate.rs").read_text(
        encoding="utf-8"
    )
    assert f'OUT_OF_SCOPE_LOCK_NAME: &str = "{memory_txn._OUT_OF_SCOPE_LOCK_NAME}"' in rust, (
        "the Rust and Python out-of-scope lock names have drifted — they must be byte-identical "
        "or the two languages stop excluding each other on out-of-scope writes"
    )
