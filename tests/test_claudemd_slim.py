"""Tests for the slim janitor-managed CLAUDE.md feature (TRDD-H12K9JYX).

Covers the pure lib (scan/render/violations/staleness), the parameterized fence surgery
(both fences coexisting without eating each other), and the CLI (index splice round-trip,
check exit codes, the preservation verifier accepting a faithful migration and REJECTING
a lossy one — the negative case is the whole point of the oracle).
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

from exe_path import exe  # noqa: E402
from repomap import claudemd_slim as cs  # noqa: E402
from repomap.markers import _fence_span  # noqa: E402
from repomap.renderer import FENCE_END as MAP_END  # noqa: E402
from repomap.renderer import FENCE_START as MAP_START  # noqa: E402

_CLI = _PROJECT_ROOT / "scripts" / "claudemd_slim.py"


def _page(
    memdir: Path, name: str, *, tier: str, desc: str, body: str = "", lmd: str = "2026-08-01", topic: str = ""
) -> None:
    memdir.mkdir(parents=True, exist_ok=True)
    topic_line = f"\n  topic: {topic}" if topic else ""
    (memdir / f"{name}.md").write_text(
        f'---\nname: {name}\ndescription: "{desc}"\nocd: 2026-08-01\nlmd: {lmd}\n'
        f"metadata:\n  node_type: memory\n  type: project\n  tier: {tier}{topic_line}\n---\n{body}\n",
        encoding="utf-8",
    )


def _corpus(root: Path) -> Path:
    """A small three-tier corpus: overview → hub → linked component + one orphan."""
    memdir = root / ".claude" / "project" / "memory"
    _page(memdir, "proj-overview", tier="hub", desc="the entry point", body="See [[arch-hub]].")
    _page(memdir, "arch-hub", tier="hub", desc="architecture topics / more symptoms", body="Links: [[daemon-page]] and [[missing-page]].")
    _page(memdir, "daemon-page", tier="component", desc="how the daemon works / when it dies")
    _page(memdir, "orphan-page", tier="component", desc="an unclaimed page")
    (memdir / "MEMORY.md").write_text("# MEMORY — stub\n", encoding="utf-8")
    return memdir


def test_scan_pages_filters_and_parses(tmp_path: Path) -> None:
    """scan_pages reads name/description/tier/topic from frontmatter and skips MEMORY.md and
    maintenance artifacts — the index must never list the harness stub."""
    memdir = _corpus(tmp_path)
    (memdir / "memory-reorg-proposed.md").write_text("proposals\n", encoding="utf-8")
    pages = cs.scan_pages(memdir)
    names = [p.name for p in pages]
    assert names == ["arch-hub", "daemon-page", "orphan-page", "proj-overview"]
    hub = next(p for p in pages if p.name == "arch-hub")
    assert hub.tier == "hub" and hub.description.startswith("architecture topics")
    assert next(p for p in pages if p.name == "proj-overview").is_overview


def test_render_index_lists_root_topics_only(tmp_path: Path) -> None:
    """WM-IDX-15: overview first, then each hub as a root topic; pages beneath a root topic
    and unclaimed pages are NOT listed; descriptions truncated to the first symptom segment."""
    pages = cs.scan_pages(_corpus(tmp_path))
    block = cs.render_index(pages, generated_iso="2026-08-02T18:00:00+0200")
    assert block.startswith(cs.WIKIMEM_FENCE_START)
    assert block.rstrip("\n").endswith(cs.WIKIMEM_FENCE_END)
    lines = block.splitlines()
    ov = next(i for i, ln in enumerate(lines) if ln.startswith("- [proj-overview]"))
    hub = next(i for i, ln in enumerate(lines) if ln.startswith("- [arch-hub]"))
    assert ov < hub
    assert "daemon-page" not in block and "orphan-page" not in block
    assert "Other topics" not in block
    assert "more symptoms" not in block
    assert "missing-page" not in block


def test_corpus_digest_tracks_description_not_lmd(tmp_path: Path) -> None:
    """The freshness digest follows what the index renders. A changed ROOT-topic description
    MUST churn CLAUDE.md; an `lmd` bump alone must NOT (memgrep write verbs stamp `lmd` on every
    edit, janitor#265); a changed description beneath a root topic must NOT either (janitor#328)."""
    memdir = _corpus(tmp_path)
    d1 = cs.corpus_digest(cs.scan_pages(memdir))
    hub_body = "Links: [[daemon-page]] and [[missing-page]]."
    _page(memdir, "arch-hub", tier="hub", desc="architecture topics / more symptoms", body=hub_body, lmd="2026-08-02")
    assert cs.corpus_digest(cs.scan_pages(memdir)) == d1
    _page(memdir, "daemon-page", tier="component", desc="a materially different symptom surface", lmd="2026-08-02")
    assert cs.corpus_digest(cs.scan_pages(memdir)) == d1
    _page(memdir, "arch-hub", tier="hub", desc="a materially different root topic", body=hub_body, lmd="2026-08-02")
    assert cs.corpus_digest(cs.scan_pages(memdir)) != d1


def test_corpus_digest_unchanged_by_description_edit_past_first_segment(tmp_path: Path) -> None:
    """TRDD-Q3WSQ9M5 / janitor#298 (over-fires): the index only ever renders the FIRST
    ' / ' symptom segment of a description (`_short_desc`). Editing text past that
    segment leaves the rendered body byte-identical, so the digest — now hashing the
    rendered body itself — must NOT move (the old hand-picked-field digest hashed the
    full description string and flipped here, cache-busting CLAUDE.md for nothing)."""
    memdir = _corpus(tmp_path)
    d1 = cs.corpus_digest(cs.scan_pages(memdir))

    _page(memdir, "arch-hub", tier="hub",
          desc="architecture topics / more symptoms / a brand new trailing symptom",
          body="Links: [[daemon-page]] and [[missing-page]].")
    assert cs.corpus_digest(cs.scan_pages(memdir)) == d1


def test_corpus_digest_changes_on_page_rename(tmp_path: Path) -> None:
    """TRDD-Q3WSQ9M5 / janitor#298 (under-fires): a page file rename changes the rendered
    link target (`_entry`'s `({memdir_rel}/{filename})`) but never touched the old
    `(name, description)` digest, so `index_is_stale` stayed False forever. Hashing the
    rendered body catches it."""
    memdir = _corpus(tmp_path)
    d1 = cs.corpus_digest(cs.scan_pages(memdir))

    (memdir / "arch-hub.md").rename(memdir / "arch-hub-renamed.md")
    assert cs.corpus_digest(cs.scan_pages(memdir)) != d1


def test_corpus_digest_changes_on_hub_tier_change(tmp_path: Path) -> None:
    """TRDD-Q3WSQ9M5 / janitor#298 (under-fires): a non-overview hub's `tier:` flipping to
    `component` removes its line from the hub root-topic list (it stops being a root
    topic), which changes the rendered body — the digest must follow."""
    memdir = _corpus(tmp_path)
    d1 = cs.corpus_digest(cs.scan_pages(memdir))

    _page(memdir, "arch-hub", tier="component", desc="architecture topics / more symptoms",
          body="Links: [[daemon-page]] and [[missing-page]].")
    assert cs.corpus_digest(cs.scan_pages(memdir)) != d1


def test_corpus_digest_stable_across_noop_regeneration(tmp_path: Path) -> None:
    """Regenerating the index twice with no corpus change must yield the same digest —
    the freshness probe must not be a source of its own churn."""
    memdir = _corpus(tmp_path)
    pages = cs.scan_pages(memdir)
    d1 = cs.corpus_digest(pages)
    d2 = cs.corpus_digest(cs.scan_pages(memdir))
    assert d1 == d2


def test_render_index_without_topics_renders_hub_roots(tmp_path: Path) -> None:
    """TRDD-KI0H9C8N / janitor#299 fallback + WM-IDX-15: a corpus where no page carries
    `metadata.topic:` renders the overview entry then the hub root lines, and the header digest
    is the digest of that body."""
    memdir = _corpus(tmp_path)
    pages = cs.scan_pages(memdir)
    assert all(p.topic == "" for p in pages), "fixture must carry no topic for this to test the fallback"
    rel = ".claude/project/memory"
    roots = cs._render_hub_roots(pages, rel)
    assert roots == [cs._entry(next(p for p in pages if p.name == "arch-hub"), rel)]
    body = cs._render_body(pages, rel)
    assert body.splitlines()[-len(roots):] == roots
    assert "digest=" + cs.corpus_digest(pages) in cs.render_index(pages, generated_iso="2026-08-02T18:00:00+0200")


def test_render_index_groups_by_topic_when_present(tmp_path: Path) -> None:
    """TRDD-KI0H9C8N / janitor#299 + WM-IDX-15: with `metadata.topic:` present the root topics
    are the distinct topic values, one bare line each; hub pages, member pages and untopiced
    pages are not listed, and the overview stays first and is never a topic of its own."""
    memdir = _corpus(tmp_path)
    _page(memdir, "arch-hub", tier="hub", desc="architecture topics", topic="architecture", body="Links: [[daemon-page]].")
    _page(memdir, "daemon-page", tier="component", desc="how the daemon works", topic="architecture")
    lines = cs.render_index(cs.scan_pages(memdir), generated_iso="2026-08-02T18:00:00+0200").splitlines()
    assert lines.count("- **architecture**") == 1
    ov = next(i for i, ln in enumerate(lines) if ln.startswith("- [proj-overview]"))
    assert ov < lines.index("- **architecture**")
    assert not any("[arch-hub]" in ln or "[daemon-page]" in ln or "orphan-page" in ln for ln in lines)
    assert "Other topics" not in "\n".join(lines)


def test_render_index_overview_first_in_both_grouping_modes(tmp_path: Path) -> None:
    """TRDD-KI0H9C8N / janitor#299 acceptance box 3: the overview entry is the first
    non-header line of the rendered body whether the corpus has topics or not."""
    memdir = _corpus(tmp_path)
    pages_no_topic = cs.scan_pages(memdir)
    body_no_topic = cs._render_body(pages_no_topic, ".claude/project/memory")
    first_entry_no_topic = next(ln for ln in body_no_topic.splitlines() if ln.startswith("- "))
    assert "proj-overview" in first_entry_no_topic

    _page(memdir, "arch-hub", tier="hub", desc="architecture topics", topic="architecture",
          body="Links: [[daemon-page]].")
    pages_topic = cs.scan_pages(memdir)
    body_topic = cs._render_body(pages_topic, ".claude/project/memory")
    first_entry_topic = next(ln for ln in body_topic.splitlines() if ln.startswith("- "))
    assert "proj-overview" in first_entry_topic


def test_corpus_digest_flips_once_when_topic_is_added(tmp_path: Path) -> None:
    """TRDD-Q3WSQ9M5's property, exercised by this card's own change: because the digest
    hashes `_render_body`'s output, adding `metadata.topic:` (which changes the rendered
    body from hub grouping to topic grouping) flips the digest with zero separate digest
    maintenance — there is no field list to remember to extend for `topic`."""
    memdir = _corpus(tmp_path)
    d1 = cs.corpus_digest(cs.scan_pages(memdir))
    _page(memdir, "arch-hub", tier="hub", desc="architecture topics / more symptoms", topic="architecture",
          body="Links: [[daemon-page]] and [[missing-page]].")
    d2 = cs.corpus_digest(cs.scan_pages(memdir))
    assert d2 != d1
    # Idempotent: regenerating again with the same (now-topiced) corpus is stable.
    assert cs.corpus_digest(cs.scan_pages(memdir)) == d2


def test_render_index_header_digest_matches_corpus_digest(tmp_path: Path) -> None:
    """Coordinator addition (review of 46048355): `render_index` and `corpus_digest` used
    to compute `hashlib.sha256(...).hexdigest()[:12]` as two separate inline copies of the
    same expression — the exact drift class TRDD-Q3WSQ9M5 fixed one level down, at
    `_render_body` vs the digest's input. Both now delegate to `_digest_of`; this test
    pins them together by parsing the spliced header's `digest=` and asserting it equals
    `corpus_digest(pages)` computed independently."""
    memdir = _corpus(tmp_path)
    pages = cs.scan_pages(memdir)
    block = cs.render_index(pages, generated_iso="2026-08-02T18:00:00+0200")
    header = block.splitlines()[0]
    m = re.search(r"digest=([0-9a-f]{12})", header)
    assert m is not None
    assert m.group(1) == cs.corpus_digest(pages)


def test_both_fences_coexist_and_neither_eats_the_other(tmp_path: Path) -> None:
    """The parameterized surgery must replace ONE fence's span and keep the other's
    bytes — the failure this guards is one splicer swallowing the other's block."""
    pages = cs.scan_pages(_corpus(tmp_path))
    idx = cs.render_index(pages, generated_iso="2026-08-02T18:00:00+0200")
    map_block = f"{MAP_START} v1 sha=x digest=y generated=z\nmap body\n{MAP_END}\n"
    text = f"# Proj\n\nNarrative.\n\n{map_block}\n{idx}"
    assert _fence_span(text, MAP_START, MAP_END) is not None
    assert _fence_span(text, cs.WIKIMEM_FENCE_START, cs.WIKIMEM_FENCE_END) is not None
    stripped = cs.narrative_outside_fences(text)
    assert "map body" not in stripped and "Wikimem index" not in stripped
    assert "Narrative." in stripped


def test_slim_violations_conforming_and_violating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty on a conforming file; names each missing element and the narrative
    overflow otherwise; a map is never among the violations (PRRD G7.3)."""
    pages = cs.scan_pages(_corpus(tmp_path))
    idx = cs.render_index(pages, generated_iso="2026-08-02T18:00:00+0200")
    good = f"# P — a project (https://github.com/o/r)\n\nBuild: `uv run pytest`\n\n{idx}"
    assert cs.slim_violations(good) == []
    # CLAUDE.md has no map element, so a leftover legacy fence is not a slim violation (it
    # is project-map-drift's own nudge) and its bytes do not count against the narrative.
    legacy = f"{MAP_START} v1 sha=x digest=y generated=z\nmap\n{MAP_END}\n"
    assert cs.slim_violations(f"{good}\n{legacy}") == []
    bare = "# P\n\njust prose, no fences, no url\n"
    probs = cs.slim_violations(bare)
    assert not any("map" in p.lower() for p in probs), "a map is no part of the slim contract"
    assert any("wikimem-index fence" in p for p in probs)
    assert any("github repo url" in p for p in probs)
    monkeypatch.setenv(cs.NARRATIVE_MAX_BYTES_ENV, "10")
    assert any("narrative is" in p for p in cs.slim_violations(good))


# `@name` pages a real GitHub account at a word boundary, but never before `/`
# (`@types/node`) — measured with the GitHub markdown API.
_CODE_SPAN_RE = re.compile(r"`[^`\n]*`")
_BARE_MENTION_RE = re.compile(r"(?<![A-Za-z0-9_])@[A-Za-z0-9_-]+(?![A-Za-z0-9_/-])")


def _bare_mentions(text: str) -> list[str]:
    return _BARE_MENTION_RE.findall(_CODE_SPAN_RE.sub("", text))


def test_bare_mention_scanner_flags_only_what_pages_an_account() -> None:
    """The guard below is only worth anything if it can fail: it flags a bare mention and
    ignores code spans, scoped packages and e-mail-like text."""
    assert _bare_mentions("ping @janitor. and (@foo-bar)") == ["@janitor", "@foo-bar"]
    assert _bare_mentions("`@janitor` `@lru_cache` @types/node a@b.c") == []


def test_this_repos_rendered_wikimem_index_never_names_the_map_or_pages_an_account() -> None:
    """TRDD-FADYLSQB: the index is what CLAUDE.md carries on every turn. A page description
    naming PROJECT_MAP would point every session at the whole map file; a bare @name in it
    would page a real GitHub account each time the index is read. Rendered from this repo's
    real PROJECT corpus, the way `claudemd_slim.py index` renders it."""
    pages = cs.scan_pages(_PROJECT_ROOT / ".claude" / "project" / "memory")
    assert pages, "this repo's PROJECT wikimem corpus must exist for the guard to mean anything"
    index = cs.render_index(pages, generated_iso="2026-11-15T00:00:00+0100")
    assert "PROJECT_MAP" not in index
    assert _bare_mentions(index) == []


def test_index_is_stale_tracks_corpus(tmp_path: Path) -> None:
    """The index is stale only when a ROOT topic changed: a new page beneath a root topic leaves
    it fresh (WM-IDX-15), a new hub page makes it stale, and no fence at all is always stale."""
    memdir = _corpus(tmp_path)
    pages = cs.scan_pages(memdir)
    idx = cs.render_index(pages, generated_iso="2026-08-02T18:00:00+0200")
    text = f"# P\n\n{idx}"
    assert cs.index_is_stale(text, pages) is False
    _page(memdir, "new-page", tier="component", desc="fresh knowledge")
    assert cs.index_is_stale(text, cs.scan_pages(memdir)) is False
    _page(memdir, "new-hub", tier="hub", desc="a new root topic")
    assert cs.index_is_stale(text, cs.scan_pages(memdir)) is True
    assert cs.index_is_stale("# no fence at all\n", pages) is True


def _run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CLI), "--root", str(root), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_index_inserts_then_is_idempotent(tmp_path: Path) -> None:
    """First run splices the fence after the narrative; second run is a digest-match
    no-write (mtime unchanged) — churning CLAUDE.md on every run would bust the prompt
    cache the nudge-only discipline protects."""
    _corpus(tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# P — https://github.com/o/r\n\nnarrative stays\n", encoding="utf-8")
    res = _run_cli(tmp_path, "index")
    assert res.returncode == 0, res.stdout + res.stderr
    text = claude_md.read_text(encoding="utf-8")
    assert text.count(cs.WIKIMEM_FENCE_START) == 1 and "narrative stays" in text
    sig = claude_md.stat().st_mtime_ns
    time.sleep(0.01)
    res2 = _run_cli(tmp_path, "index")
    assert res2.returncode == 0 and "no write" in res2.stdout
    assert claude_md.stat().st_mtime_ns == sig


def test_cli_index_consecutive_runs_leave_claude_md_byte_identical(tmp_path: Path) -> None:
    """janitor#328: the header's `generated=` timestamp differs on every run, so CLAUDE.md stays
    byte-identical only because the digest (over the rendered body, never the timestamp) gates
    the write. Run across a clock tick: a regression that rewrote on each run would change
    `generated=` and fail here."""
    _corpus(tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# P — https://github.com/o/r\n\nnarrative stays\n", encoding="utf-8")
    assert _run_cli(tmp_path, "index").returncode == 0
    first = claude_md.read_bytes()
    time.sleep(1.1)  # `generated=` has one-second resolution
    assert _run_cli(tmp_path, "index").returncode == 0
    assert claude_md.read_bytes() == first


def test_cli_index_ignores_edits_beneath_root_topics(tmp_path: Path) -> None:
    """janitor#328 option (b) / WM-IDX-15: re-describing a page, or adding one, BENEATH a root
    topic must leave CLAUDE.md byte-identical and unwritten — the tracked file goes dirty only
    when a root topic changes. Run across a clock tick so a timestamp-only rewrite would show."""
    memdir = _corpus(tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# P — https://github.com/o/r\n\nnarrative stays\n", encoding="utf-8")
    assert _run_cli(tmp_path, "index").returncode == 0
    first = claude_md.read_bytes()
    _page(memdir, "daemon-page", tier="component", desc="a materially different symptom surface")
    _page(memdir, "brand-new-page", tier="component", desc="added after the first run")
    time.sleep(1.1)  # `generated=` has one-second resolution
    res = _run_cli(tmp_path, "index")
    assert res.returncode == 0 and "no write" in res.stdout, res.stdout + res.stderr
    assert claude_md.read_bytes() == first


def test_cli_index_rewrites_when_a_root_topic_changes(tmp_path: Path) -> None:
    """janitor#328 option (b): the other half — a root topic (a hub page) re-described or added
    DOES rewrite the block, exactly one fence pair stays, and the marker lines keep their shape."""
    memdir = _corpus(tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# P — https://github.com/o/r\n\nnarrative stays\n", encoding="utf-8")
    assert _run_cli(tmp_path, "index").returncode == 0
    first = claude_md.read_text(encoding="utf-8")
    assert "daemon-page" not in first and "orphan-page" not in first
    _page(memdir, "arch-hub", tier="hub", desc="architecture re-described", body="Links: [[daemon-page]].")
    _page(memdir, "new-hub", tier="hub", desc="a brand new root topic")
    res = _run_cli(tmp_path, "index")
    assert res.returncode == 0 and "wrote wikimem index" in res.stdout, res.stdout + res.stderr
    after = claude_md.read_text(encoding="utf-8")
    assert after != first
    assert "architecture re-described" in after and "[new-hub]" in after
    assert after.count(cs.WIKIMEM_FENCE_START) == 1 and after.count(cs.WIKIMEM_FENCE_END) == 1
    assert "narrative stays" in after


def test_cli_check_exit_codes(tmp_path: Path) -> None:
    _corpus(tmp_path)
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# P\n\nprose only\n", encoding="utf-8")
    assert _run_cli(tmp_path, "check").returncode == 1  # violations
    # Make it conforming: map fence + index + url, tiny narrative.
    map_block = f"{MAP_START} v1 sha=x digest=y generated=z\nmap\n{MAP_END}\n"
    claude_md.write_text(f"# P — https://github.com/o/r\n\n{map_block}\n", encoding="utf-8")
    assert _run_cli(tmp_path, "index").returncode == 0
    res = _run_cli(tmp_path, "check")
    assert res.returncode == 0, res.stdout + res.stderr


def test_detector_slim_nudge_gates_on_corpus_and_dedupes(tmp_path: Path) -> None:
    """The project-map-drift slim half (TRDD-H12K9JYX): SILENT when the project has no
    PROJECT wikimem corpus (nothing to index — the nudge would point at a command that
    can only refuse); ONE deduped nudge when a corpus exists and the contract is broken;
    silent again once conforming. Runs through the real detector subprocess so the
    opt-in gate, the nudge text, and the never-writes invariant are all exercised."""
    import os

    detector = _PROJECT_ROOT / "scripts" / "detectors" / "project-map-drift.py"

    def run_detector(root: Path) -> str:
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(root)
        res = subprocess.run(
            [sys.executable, str(detector)], capture_output=True, text=True, timeout=120, env=env, cwd=root,
        )
        assert res.returncode == 0, res.stderr
        return res.stdout

    root = tmp_path
    subprocess.run([exe("git"), "init", "-q"], cwd=root, check=True, timeout=30)
    map_block = f"{MAP_START} v1 sha=x digest=y generated=z\nmap\n{MAP_END}\n"
    claude_md = root / "CLAUDE.md"
    claude_md.write_text(f"# P\n\nprose without url\n\n{map_block}", encoding="utf-8")
    flag_dir = root / ".janitor" / "state"
    flag_dir.mkdir(parents=True)
    (flag_dir / "repomap-opt-in.flag").write_text("on")
    # Freshness stamp so the MAP half stays silent and only the slim half is measured.
    assert "slim contract" not in run_detector(root)  # no corpus → silent slim half

    _corpus(root)
    before = claude_md.read_text(encoding="utf-8")
    out = run_detector(root)
    assert "slim contract" in out and "wikimem-index fence" in out
    assert claude_md.read_text(encoding="utf-8") == before, "detector must never write"
    assert "slim contract" not in run_detector(root)  # deduped on repeat

    # Conforming file → silent (fix acknowledged, no residual nudge).
    assert _run_cli(root, "index").returncode == 0
    conforming = claude_md.read_text(encoding="utf-8").replace(
        "# P\n\nprose without url\n", "# P — https://github.com/o/r\n"
    )
    claude_md.write_text(conforming, encoding="utf-8")
    assert "slim contract" not in run_detector(root)


def test_slim_nudge_fires_without_the_repomap_optin_or_a_map_block(tmp_path: Path) -> None:
    """The slim/wikimem-index half must NOT be gated behind the repo-MAP feature.

    These are two different fences and two different features: a project can want the wikimem
    index and not want the map. This repo IS that project — it deleted its map deliberately
    because the map cost ~46k tokens on every turn of every session — and under the old order
    it therefore got NO index check at all, via two gates it had no reason to connect (the
    `repomap-opt-in.flag` early-return, and `header is None` for a map fence it does not have).

    Measured consequence before the fix (TRDD-LFSWY0C6): the wikimem index sat STALE for FIVE
    DAYS across many sessions. The card read that as "the advisory fires and nobody acts on
    it" and built its argument on it — but the advisory was never reachable. This test is the
    guard that it stays reachable, so no future tidy-up re-couples them.
    """
    import os

    detector = _PROJECT_ROOT / "scripts" / "detectors" / "project-map-drift.py"
    root = tmp_path
    subprocess.run([exe("git"), "init", "-q"], cwd=root, check=True, timeout=30)
    _corpus(root)
    claude_md = root / "CLAUDE.md"
    # NO map block, and NO repomap-opt-in.flag — deliberately the shape this repo has.
    claude_md.write_text("# P\n\nprose without url\n", encoding="utf-8")
    (root / ".janitor" / "state").mkdir(parents=True)
    assert not (root / ".janitor" / "state" / "repomap-opt-in.flag").exists()

    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    before = claude_md.read_text(encoding="utf-8")
    res = subprocess.run(
        [sys.executable, str(detector)], capture_output=True, text=True, timeout=120,
        env=env, cwd=root,
    )
    assert res.returncode == 0, res.stderr
    assert "slim contract" in res.stdout, (
        f"the slim half must run with the MAP feature off — got: {res.stdout!r}"
    )
    assert claude_md.read_text(encoding="utf-8") == before, (
        "decoupling the check must not have made the detector a writer — CLAUDE.md sits in "
        "the cached prompt prefix and is co-owned with the human"
    )


def test_cli_verify_accepts_faithful_and_rejects_lossy(tmp_path: Path) -> None:
    """The preservation oracle: a migration whose facts all moved into wikimem pages
    passes; deleting a fact line (and its token) from both the new CLAUDE.md and the
    corpus fails with the dropped line named. The negative case is the reason the
    oracle exists — a verifier that cannot fail proves nothing."""
    memdir = _corpus(tmp_path)
    fact = "The daemon binds the flock at ~/.claude/janitor-control/daemon.flock on startup."
    old = tmp_path / "CLAUDE.md.old"
    old.write_text(f"# P — https://github.com/o/r\n\n{fact}\n\nBuild: `uv run pytest`\n", encoding="utf-8")
    claude_md = tmp_path / "CLAUDE.md"
    # Faithful: the fact line moved verbatim into a wikimem page.
    _page(memdir, "daemon-facts", tier="component", desc="daemon startup facts", body=fact)
    claude_md.write_text("# P — https://github.com/o/r\n\nBuild: `uv run pytest`\n", encoding="utf-8")
    res = _run_cli(tmp_path, "verify", "--old", str(old))
    assert res.returncode == 0, res.stdout + res.stderr
    # Lossy: the page vanishes → the fact (and its path token) is nowhere.
    (memdir / "daemon-facts.md").unlink()
    res2 = _run_cli(tmp_path, "verify", "--old", str(old))
    assert res2.returncode == 1
    assert "DROPPED" in res2.stdout
