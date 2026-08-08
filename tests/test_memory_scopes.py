"""Tests for the shared three-scope memory-root resolver (scripts/lib/memory_scopes.py).

Real fixtures, no mocks: HOME / CLAUDE_PROJECT_DIR are redirected to tmp dirs and a
real ``git init`` creates the PROJECT-scope repo, so the live ``~/.claude`` tree and
the real plugin-DATA dir are never touched. This module is the SSOT extracted from
memory-maintenance + memory-librarian (TRDD-87935f21 priority #2); these tests pin
the behavior both detectors now depend on — especially the USER-scope gotcha (the
fixed plugin-DATA path is used, NOT ``${CLAUDE_PLUGIN_DATA}``, which at heartbeat
time points at the wrong plugin).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import memory_scopes as msc  # noqa: E402


def _git_init(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # A bogus CLAUDE_PLUGIN_DATA that resolve_user_dir MUST ignore (the gotcha):
    # at heartbeat time this var points at whatever plugin owns the turn.
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "WRONG-plugin" / "data"))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return home


# ---- project_slug ----------------------------------------------------------

def test_project_slug_dashes_separators():
    """Every path separator becomes a dash; a leading sep yields a leading dash."""
    assert msc.project_slug("/Users/me/Code/proj") == "-Users-me-Code-proj"


def test_project_slug_is_literal_not_normalized():
    """The slug is built from the literal string, never a resolved/normalized path.

    The `..` segment is NOT collapsed — but its dots ARE dashed: the harness replaces
    every non-alphanumeric char (verified on disk, TRDD-E9LMBNPE), so the old
    separators-only expectation `-a-b-..-c` pinned the bug this fix removed."""
    assert msc.project_slug("/a/b/../c") == "-a-b----c"


# ---- resolve_local_dir -----------------------------------------------------

def test_resolve_local_dir_uses_slug(monkeypatch, _isolate):
    """LOCAL = $HOME/.claude/projects/<slug>/memory for CLAUDE_PROJECT_DIR."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/Users/me/proj")
    got = msc.resolve_local_dir()
    assert got == _isolate / ".claude" / "projects" / "-Users-me-proj" / "memory"


def test_resolve_local_dir_for_matches_resolve_local_dir(monkeypatch, _isolate):
    """M-11 (wikimem audit 2026-07-07): the explicit-project export resolves the
    SAME dir the implicit resolver does, using the harness slug rules (dash every
    non-alphanumeric, never realpath) — the SSOT for callers like fleet_status
    that resolve LOCAL roots for OTHER projects."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/Users/me/my_proj.v2")
    assert msc.resolve_local_dir_for("/Users/me/my_proj.v2") == msc.resolve_local_dir()
    assert msc.resolve_local_dir_for("/Users/me/my_proj.v2").parent.name == "-Users-me-my-proj-v2"


def test_settings_dir_shares_the_data_dir_constant(monkeypatch, _isolate):
    """M-11: memory_settings.settings_dir builds its default path from the
    memory_scopes SSOT constant — the two literals can never drift again."""
    monkeypatch.delenv("JANITOR_MEMORY_SETTINGS_DIR", raising=False)
    import memory_settings as ms
    d = ms.settings_dir()
    assert d.name == msc.JANITOR_DATA_DIR_NAME
    assert msc.resolve_user_dir().parent == d


# ---- resolve_user_dir (the hard-coded-path gotcha) -------------------------

def test_resolve_user_dir_ignores_claude_plugin_data(_isolate):
    """USER root is the FIXED janitor plugin-DATA path, NOT ${CLAUDE_PLUGIN_DATA}."""
    got = msc.resolve_user_dir()
    expected = (
        _isolate / ".claude" / "plugins" / "data"
        / "ai-maestro-janitor-ai-maestro-plugins" / "memory"
    )
    assert got == expected
    assert "WRONG-plugin" not in str(got)


# ---- resolve_project_dir ---------------------------------------------------

def test_resolve_project_dir_in_git_repo(tmp_path, monkeypatch):
    """Inside a git repo, PROJECT = <toplevel>/.claude/project/memory."""
    repo = tmp_path / "repo"
    _git_init(repo)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    got = msc.resolve_project_dir()
    assert got is not None
    # macOS /tmp symlinks through /private — compare resolved roots.
    assert got.resolve() == (repo.resolve() / ".claude" / "project" / "memory")


def test_resolve_project_dir_none_outside_repo(tmp_path, monkeypatch):
    """Outside any git repo, PROJECT resolves to None (never raises)."""
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(bare))
    assert msc.resolve_project_dir() is None


# ---- resolve_scope_dirs ----------------------------------------------------

def test_resolve_scope_dirs_existing_only_most_specific_first(
    monkeypatch, _isolate
):
    """Only scopes whose dir EXISTS are returned, in LOCAL → PROJECT → USER order.

    PROJECT is omitted here because CLAUDE_PROJECT_DIR is not a git repo (its cwd
    does not even exist) → resolve_project_dir returns None.
    """
    proj = "/Users/me/proj"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", proj)
    local = _isolate / ".claude" / "projects" / msc.project_slug(proj) / "memory"
    local.mkdir(parents=True)
    user = msc.resolve_user_dir()
    user.mkdir(parents=True)

    out = msc.resolve_scope_dirs()
    assert [label for label, _ in out] == ["LOCAL", "USER"]


def test_resolve_scope_dirs_empty_when_nothing_exists(monkeypatch):
    """No scope dirs on disk → an empty list (silent, never an error)."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/Users/me/nonexistent")
    assert msc.resolve_scope_dirs() == []


def test_resolve_scope_dirs_includes_project_in_git_repo(tmp_path, monkeypatch):
    """A real git repo whose .claude/project/memory EXISTS is returned as PROJECT.

    HOME is already redirected by the autouse fixture; the repo is a sibling tmp
    dir so LOCAL/USER do not exist and only PROJECT is on disk.
    """
    repo = tmp_path / "repo"
    _git_init(repo)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    (repo / ".claude" / "project" / "memory").mkdir(parents=True)

    out = msc.resolve_scope_dirs()
    assert [label for label, _ in out] == ["PROJECT"]


# ---- coexistence primitives (TRDD-ab232dbd) --------------------------------

def test_resolve_wiki_dir_is_the_wiki_subnamespace(tmp_path):
    """The curated wiki lives at ``<scope_root>/wiki`` — the buffer at the root, the
    wiki one level down, so memgrep recall (which recurses the root) covers both."""
    assert msc.resolve_wiki_dir(tmp_path / "memory") == tmp_path / "memory" / "wikimem"
    assert msc.resolve_wiki_dir(tmp_path / "memory").name == msc.WIKI_SUBDIR


def test_is_curated_wiki_page_true_for_full_frontmatter():
    """A wikimem page (``node_type: memory`` and/or ``tier:``) reads as CURATED —
    harvest SKIPS it. Both nested-under-metadata and top-level keys are detected."""
    nested = "---\nname: x\nmetadata:\n  node_type: memory\n  tier: hub\n---\nbody\n"
    top_tier = "---\nname: x\ndescription: y\ntier: component\n---\nbody\n"
    assert msc.is_curated_wiki_page(nested)
    assert msc.is_curated_wiki_page(top_tier)


def test_is_curated_wiki_page_true_for_flow_style_metadata():
    """janitor#212: ``metadata: {node_type: memory, type: overview, tier: hub}`` — the
    EXACT shape SessionStart writes for every freshly-bootstrapped scope's
    ``*-overview.md`` stub — must read as CURATED. Unfixed, the per-line key scan only
    ever saw "metadata" as the line's key (the wikimem-only keys sit INSIDE the braces
    on that same line), so every fresh overview stub misclassified as RAW and harvest
    tried (and could never succeed) to mirror an already-curated page forever."""
    flow = (
        "---\nname: proj-local-overview\n"
        'description: "LOCAL memory scope entry point"\n'
        "ocd: 2026-08-06T11:30:26+0200\nlmd: 2026-08-06T11:30:26+0200\n"
        "metadata: {node_type: memory, type: overview, tier: hub}\n---\nbody\n"
    )
    assert msc.is_curated_wiki_page(flow)


def test_is_curated_wiki_page_true_for_flow_style_metadata_tier_only():
    """The flow-style fix must key on ANY wikimem-only key inside the braces, not just
    node_type — a page carrying only ``tier`` in flow form is still CURATED."""
    flow = "---\nname: x\nmetadata: {type: reference, tier: component}\n---\nbody\n"
    assert msc.is_curated_wiki_page(flow)


def test_is_curated_wiki_page_false_for_flow_style_metadata_without_wikimem_keys():
    """A flow-style ``metadata: {type: feedback}`` with NEITHER node_type nor tier
    inside the braces is still a RAW buffer note — the fix must not over-fire and
    treat every flow-style metadata line as curated regardless of its content."""
    flow = '---\nname: foo\ndescription: "a fact"\nmetadata: {type: feedback}\n---\nbody\n'
    assert not msc.is_curated_wiki_page(flow)


def test_is_curated_wiki_page_false_for_raw_harness_note():
    """A raw harness BUFFER note (minimal frontmatter: name/description/metadata.type,
    NO node_type/tier) reads as RAW — harvest MIRRORS it. The harness writes exactly
    this shape, so it must never be mistaken for an already-curated page."""
    raw = '---\nname: foo\ndescription: "a fact"\nmetadata:\n  type: feedback\n---\nbody\n'
    assert not msc.is_curated_wiki_page(raw)


def test_is_curated_wiki_page_false_without_frontmatter():
    """No frontmatter block at all (or an unclosed fence) → RAW (a bare note is a
    buffer artifact, not a curated wiki page)."""
    assert not msc.is_curated_wiki_page("just plain text, no frontmatter\n")
    assert not msc.is_curated_wiki_page("---\nname: x\ntier: hub\n(no closing fence)\n")


# ---- is_note_file (the non-note / user-mem SSOT, TRDD-87935f21) -------------

def test_is_note_file_true_for_a_plain_note():
    """A bare `*.md` basename or relative note path reads as a real note."""
    assert msc.is_note_file("feedback_oauth_rotator.md")
    assert msc.is_note_file("sub/project_auth.md")


def test_is_note_file_false_for_generated_index_files():
    """The generated/index files (MEMORY.md stub, memory-index.md) are NOT notes."""
    assert not msc.is_note_file("MEMORY.md")
    assert not msc.is_note_file("memory-index.md")
    assert not msc.is_note_file("any/dir/MEMORY.md")


def test_is_note_file_false_for_detector_proposal_family():
    """The whole `*-proposed.md` detector-output family is excluded by SUFFIX —
    so a future detector's report never re-introduces the collision (issue #54)."""
    assert not msc.is_note_file("memory-reorg-proposed.md")
    assert not msc.is_note_file("memory-scope-leak-proposed.md")
    assert not msc.is_note_file("some-future-detector-proposed.md")


def test_is_note_file_false_under_user_mem_at_any_depth():
    """A path that recurses into the PRIVATE user-mem/ store is NOT a note — the
    load-bearing privacy fix of mandate #3 (agent-invisible by design)."""
    assert not msc.is_note_file("user-mem/000001.md")
    assert not msc.is_note_file("memory/user-mem/000001.md")
    assert not msc.is_note_file("/abs/memory/user-mem/deep/n.md")


def test_is_note_file_false_under_other_excluded_dirs():
    """The memgrep cache + the transaction staging dir are never notes either."""
    assert not msc.is_note_file(".memgrep/index.md")
    assert not msc.is_note_file("memory/.maint-staging/staged.md")


def test_is_note_file_false_for_non_markdown():
    """Only markdown is a note — a `.txt`/`.json` sibling is not."""
    assert not msc.is_note_file("notes.txt")
    assert not msc.is_note_file(".memgrep/index.db")


def test_iter_note_files_yields_only_real_notes(tmp_path):
    """A real corpus with a note + a NON_NOTE_BASENAME + a proposal + a user-mem
    note + a .memgrep cache file → ONLY the real notes are yielded, sorted."""
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "project_auth.md").write_text("real note\n", encoding="utf-8")
    (mem / "feedback_x.md").write_text("another real note\n", encoding="utf-8")
    # Non-notes that MUST be excluded:
    (mem / "MEMORY.md").write_text("# stub\n", encoding="utf-8")
    (mem / "memory-index.md").write_text("# generated\n", encoding="utf-8")
    (mem / "memory-reorg-proposed.md").write_text("# proposal\n", encoding="utf-8")
    um = mem / "user-mem"
    um.mkdir()
    (um / "000001.md").write_text("PRIVATE user memory\n", encoding="utf-8")
    mg = mem / ".memgrep"
    mg.mkdir()
    (mg / "stray.md").write_text("cache\n", encoding="utf-8")

    got = {p.name for p in msc.iter_note_files(mem)}
    assert got == {"project_auth.md", "feedback_x.md"}


def test_iter_note_files_is_recursive(tmp_path):
    """Notes in sub-dirs (e.g. the curated wiki/ sub-namespace) are included —
    iter_note_files recurses, matching every editor/librarian scan it replaces."""
    mem = tmp_path / "memory"
    (mem / "wikimem").mkdir(parents=True)
    (mem / "root_note.md").write_text("root\n", encoding="utf-8")
    (mem / "wikimem" / "hub_frontend.md").write_text("curated\n", encoding="utf-8")

    got = {p.name for p in msc.iter_note_files(mem)}
    assert got == {"root_note.md", "hub_frontend.md"}


def test_iter_note_files_empty_for_missing_dir(tmp_path):
    """A missing memory dir yields [] (silent, never raises)."""
    assert msc.iter_note_files(tmp_path / "does-not-exist") == []


# ---- USER-memory backup mirror (TRDD-GFT33HT9) -----------------------------

def _seed(d: Path, name: str, body: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")


def test_resolve_user_mirror_dir_is_outside_the_data_dir(_isolate):
    """The mirror lives at ~/.claude/ai-maestro-janitor-memory/ — NOT under plugins/data,
    so a plain uninstall (which deletes the data dir) never touches it."""
    got = msc.resolve_user_mirror_dir()
    assert got == _isolate / ".claude" / "ai-maestro-janitor-memory"
    assert "plugins/data" not in str(got)


def test_sync_mirrors_primary_to_mirror():
    """Primary has memory → sync copies it into the mirror and reports 'mirrored'."""
    _seed(msc.resolve_user_dir(), "note.md", "canonical fact\n")
    assert msc.sync_user_memory_mirror() == "mirrored"
    assert (msc.resolve_user_mirror_dir() / "note.md").read_text(encoding="utf-8") == "canonical fact\n"


def test_sync_restores_mirror_to_primary_when_primary_empty():
    """Primary absent but mirror has memory (post-uninstall reinstall) → RESTORE."""
    _seed(msc.resolve_user_mirror_dir(), "note.md", "survived the uninstall\n")
    assert not msc.resolve_user_dir().exists()
    assert msc.sync_user_memory_mirror() == "restored"
    assert (msc.resolve_user_dir() / "note.md").read_text(encoding="utf-8") == "survived the uninstall\n"


def test_sync_noop_when_neither_side_has_memory():
    """Fresh install (no primary, no mirror) → nothing to sync."""
    assert msc.sync_user_memory_mirror() is None


def test_sync_is_additive_and_never_deletes():
    """Primary drives the sync, but a note only in the mirror is KEPT (never deleted) —
    the backup errs toward retaining memory."""
    _seed(msc.resolve_user_dir(), "a.md", "in primary\n")
    _seed(msc.resolve_user_mirror_dir(), "b.md", "only in mirror\n")
    assert msc.sync_user_memory_mirror() == "mirrored"
    mirror = msc.resolve_user_mirror_dir()
    assert (mirror / "a.md").exists(), "primary note is mirrored"
    assert (mirror / "b.md").read_text(encoding="utf-8") == "only in mirror\n", "mirror-only note survives"


def test_sync_carries_user_mem_and_index_subdirs():
    """The private user-mem store mirrors (it is real, irreplaceable knowledge). The .memgrep
    index does NOT (F10, audit 2026-07-13): it is derived state, regeneratable from the notes,
    and copying a live SQLite file byte-wise can only ever back up a TORN one — which the
    restore path would then write into the live corpus. The mirror carries knowledge, not
    caches."""
    primary = msc.resolve_user_dir()
    _seed(primary, "note.md", "x\n")
    _seed(primary / "user-mem", "0001.md", "private\n")
    _seed(primary / ".memgrep", "index.db", "SQLITE\n")
    assert msc.sync_user_memory_mirror() == "mirrored"
    mirror = msc.resolve_user_mirror_dir()
    assert (mirror / "user-mem" / "0001.md").read_text(encoding="utf-8") == "private\n"
    assert not (mirror / ".memgrep").exists()


def test_a_stray_index_in_an_empty_primary_does_not_block_the_restore():
    """The restore-blocking hazard `_dir_has_memory` used to carry (found while fixing F10).

    That predicate decides the sync DIRECTION, and it counted a bare `.memgrep/` as "primary
    has memory". So after a plain uninstall wiped the data dir, anything that recreated an
    index dir before the sync ran would send it down the primary→mirror branch — and the
    user's ONLY surviving copy of their memory would never be restored. An index is not a
    memory."""
    primary = msc.resolve_user_dir()
    _seed(primary / ".memgrep", "index.db", "SQLITE\n")     # derived state, no notes
    _seed(msc.resolve_user_mirror_dir(), "note.md", "the only surviving copy\n")

    assert msc.sync_user_memory_mirror() == "restored"
    assert (primary / "note.md").read_text(encoding="utf-8") == "the only surviving copy\n"


def test_sync_is_idempotent():
    """Running the sync twice is stable — same result, no error, corpus intact."""
    _seed(msc.resolve_user_dir(), "note.md", "stable\n")
    assert msc.sync_user_memory_mirror() == "mirrored"
    assert msc.sync_user_memory_mirror() == "mirrored"
    assert (msc.resolve_user_mirror_dir() / "note.md").read_text(encoding="utf-8") == "stable\n"


def test_sync_never_mirrors_the_txn_staging_tree_or_the_memgrep_index():
    """F10: the USER scope ROOT also hosts memory_txn's `.maint-staging/` and memgrep's
    `.memgrep/`. A blind copytree backed both up — so a SessionStart landing mid-transaction
    permanently archived that txn's staged page COPIES and its journal, and the restore path
    wrote them back into the live corpus. memgrep has no staging exclusion (only
    iter_note_files does), so the agent would then RECALL superseded, half-edited pages as
    real memories — and a restored `committing` journal is a live roll-forward instruction."""
    primary = msc.resolve_user_dir()
    _seed(primary, "note.md", "a real memory\n")
    staging = primary / ".maint-staging" / "abc123"
    staging.mkdir(parents=True)
    (staging / "note.md").write_text("HALF-EDITED staged copy\n", encoding="utf-8")
    (primary / ".maint-staging" / "abc123.json").write_text('{"phase":"committing"}\n',
                                                            encoding="utf-8")
    (primary / ".memgrep").mkdir()
    (primary / ".memgrep" / "index.db").write_bytes(b"SQLite format 3\x00torn")

    assert msc.sync_user_memory_mirror() == "mirrored"

    mirror = msc.resolve_user_mirror_dir()
    assert (mirror / "note.md").read_text(encoding="utf-8") == "a real memory\n"
    assert not (mirror / ".maint-staging").exists(), "staged page copies + journal backed up"
    assert not (mirror / ".memgrep").exists(), "the SQLite index was copied (possibly torn)"


def test_restore_never_reinjects_a_staging_tree_into_the_live_corpus():
    """The other direction of F10 — the one that actually corrupts recall: a mirror that
    already carries a stale staging tree must not write it back into the live USER scope."""
    mirror = msc.resolve_user_mirror_dir()
    _seed(mirror, "note.md", "survived the uninstall\n")
    stale = mirror / ".maint-staging" / "old"
    stale.mkdir(parents=True)
    (stale / "note.md").write_text("SUPERSEDED half-edited copy\n", encoding="utf-8")

    assert msc.sync_user_memory_mirror() == "restored"

    primary = msc.resolve_user_dir()
    assert (primary / "note.md").read_text(encoding="utf-8") == "survived the uninstall\n"
    assert not (primary / ".maint-staging").exists(), "a stale txn was restored into the corpus"


# --------------------------------------------------------------------------- #
# TRDD-DFKEXO79 component 2 — the CC 2.1.224 long-path tripwire.
#
# 2.1.224 fixed >200-char project paths colliding under a shared sanitized prefix,
# which implies the harness now TRUNCATES or HASHES such slugs. Our project_slug
# re-derives by plain dashing, so the day a long-path project appears on a host,
# every derived-slug consumer (LOCAL memory, transcript-age, user-mem) silently
# resolves a NONEXISTENT dir — the exact failure the separators bug already caused
# once (see project_slug's docstring). These tests pin today's reality and fail
# LOUDLY, naming the fix, the day it stops holding. Environment-dependent by
# design: they skip on hosts with no harness dir (CI).
# --------------------------------------------------------------------------- #

# The REAL home, resolved via the passwd db: the suite's conftest points $HOME (and
# Path.home()) at a fake isolation tree, which would make these env-dependent tests skip
# EVERYWHERE — a test that can never run is decoration. Read-only access; the write guard
# is about mutations, and these only iterdir().
def _real_harness_projects() -> Path:
    import pwd

    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".claude" / "projects"


def test_derived_slug_matches_the_harness_dir_for_this_repo() -> None:
    """CANARY: the slug we derive for THIS repo must name a dir the harness actually
    created. If this fails, derivation has diverged from the harness (a CC slug-scheme
    change) and every LOCAL-scope consumer is silently reading an empty dir — implement
    resolve-don't-rederive (TRDD-DFKEXO79 component 2) before trusting LOCAL memory."""
    harness = _real_harness_projects()
    if not harness.is_dir():
        pytest.skip("no harness projects dir on this host (CI)")
    repo_root = str(Path(__file__).resolve().parent.parent)
    derived = harness / msc.project_slug(repo_root)
    if not any(harness.iterdir()):
        pytest.skip("harness projects dir empty")
    assert derived.is_dir(), (
        f"derived slug {derived.name!r} names no harness dir — the harness slug scheme "
        "has diverged from project_slug; implement resolve-don't-rederive (TRDD-DFKEXO79)"
    )


def test_this_repos_slug_stays_clear_of_the_truncation_regime() -> None:
    """TRIPWIRE (TRDD-DFKEXO79 component 2). The CC 2.1.224 long-path scheme is PROVEN
    live on this host, not latent: a probe artifact sits in the harness dir at 207 chars —
    exactly 200 chars of plain-dashed path plus a `-<hash6>` suffix — so for any path whose
    dashed form exceeds ~200, the harness's name and `project_slug`'s plain dashing
    DIVERGE, and every derived-slug consumer (LOCAL memory, transcript-age, user-mem)
    resolves a nonexistent dir. This repo's slug is 132 chars today; this test fails while
    there is still margin, naming the fix, if the path ever grows toward the cliff. The
    fix at that point is resolve-don't-rederive: stamp the AUTHORITATIVE slug dir at
    SessionStart from the hook payload's transcript_path, and prefer the stamp."""
    repo_root = str(Path(__file__).resolve().parent.parent)
    derived = msc.project_slug(repo_root)
    assert len(derived) < 190, (
        f"this repo's derived slug is {len(derived)} chars — inside the margin of the "
        "harness's 200-char truncate+hash regime, where plain dashing diverges from the "
        "real dir name. Implement resolve-don't-rederive (TRDD-DFKEXO79 component 2) "
        "BEFORE trusting any derived-slug consumer here."
    )
