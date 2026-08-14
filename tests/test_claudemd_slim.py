"""Tests for the slim janitor-managed CLAUDE.md feature (TRDD-H12K9JYX).

Covers the pure lib (scan/render/violations/staleness), the parameterized fence surgery
(both fences coexisting without eating each other), and the CLI (index splice round-trip,
check exit codes, the preservation verifier accepting a faithful migration and REJECTING
a lossy one — the negative case is the whole point of the oracle).
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

from repomap import claudemd_slim as cs  # noqa: E402
from repomap.markers import _fence_span  # noqa: E402
from repomap.renderer import FENCE_END as MAP_END  # noqa: E402
from repomap.renderer import FENCE_START as MAP_START  # noqa: E402

_CLI = _PROJECT_ROOT / "scripts" / "claudemd_slim.py"


def _page(memdir: Path, name: str, *, tier: str, desc: str, body: str = "", lmd: str = "2026-08-01") -> None:
    memdir.mkdir(parents=True, exist_ok=True)
    (memdir / f"{name}.md").write_text(
        f'---\nname: {name}\ndescription: "{desc}"\nocd: 2026-08-01\nlmd: {lmd}\n'
        f"metadata:\n  node_type: memory\n  type: project\n  tier: {tier}\n---\n{body}\n",
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
    """scan_pages reads name/description/tier/wikilinks from frontmatter+body and skips
    MEMORY.md and maintenance artifacts — the index must never list the harness stub."""
    memdir = _corpus(tmp_path)
    (memdir / "memory-reorg-proposed.md").write_text("proposals\n", encoding="utf-8")
    pages = cs.scan_pages(memdir)
    names = [p.name for p in pages]
    assert names == ["arch-hub", "daemon-page", "orphan-page", "proj-overview"]
    hub = next(p for p in pages if p.name == "arch-hub")
    assert hub.tier == "hub" and hub.wikilinks == ["daemon-page", "missing-page"]
    assert next(p for p in pages if p.name == "proj-overview").is_overview


def test_render_index_topic_order_and_truncation(tmp_path: Path) -> None:
    """Overview first, hubs as topic groups with their linked pages beneath, orphans
    under Other; descriptions truncated to the first symptom segment (the index rides
    every turn — entries stay one line)."""
    pages = cs.scan_pages(_corpus(tmp_path))
    block = cs.render_index(pages, generated_iso="2026-08-02T18:00:00+0200")
    assert block.startswith(cs.WIKIMEM_FENCE_START)
    assert block.rstrip("\n").endswith(cs.WIKIMEM_FENCE_END)
    body = block.splitlines()
    ov = next(i for i, ln in enumerate(body) if "proj-overview" in ln and ln.startswith("- "))
    hub = next(i for i, ln in enumerate(body) if ln.startswith("**arch-hub**"))
    child = next(i for i, ln in enumerate(body) if ln.startswith("  - [daemon-page]"))
    other = next(i for i, ln in enumerate(body) if ln.startswith("**Other topics**"))
    orphan = next(i for i, ln in enumerate(body) if "orphan-page" in ln)
    assert ov < hub < child < other < orphan
    # Truncation: the hub's multi-symptom description keeps only the first segment.
    assert "more symptoms" not in "\n".join(body)
    # A wikilink naming no real page is silently skipped, never rendered as a dead link.
    assert "missing-page" not in block


def test_corpus_digest_tracks_description_not_lmd(tmp_path: Path) -> None:
    """The freshness digest mixes (name, description) — the two fields the rendered index
    actually shows. A changed description MUST churn CLAUDE.md; an `lmd` bump alone must NOT.

    `lmd` used to be in the mix and was harmless only because nothing ever bumped it
    (janitor#265). memgrep's write verbs now stamp it on every add-atom/add-lesson/edit, so
    keeping it would flip this digest on every atom edit — precisely the cache-bust the
    nudge-only discipline exists to avoid."""
    memdir = _corpus(tmp_path)
    d1 = cs.corpus_digest(cs.scan_pages(memdir))

    # lmd alone moves: the index renders nothing that changed, so the digest must hold.
    _page(memdir, "daemon-page", tier="component",
          desc="how the daemon works / when it dies", lmd="2026-08-02")
    assert cs.corpus_digest(cs.scan_pages(memdir)) == d1

    # The description changes: the index WOULD render differently, so the digest must move.
    _page(memdir, "daemon-page", tier="component",
          desc="a materially different symptom surface", lmd="2026-08-02")
    assert cs.corpus_digest(cs.scan_pages(memdir)) != d1


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
    overflow otherwise."""
    pages = cs.scan_pages(_corpus(tmp_path))
    idx = cs.render_index(pages, generated_iso="2026-08-02T18:00:00+0200")
    map_block = f"{MAP_START} v1 sha=x digest=y generated=z\nmap\n{MAP_END}\n"
    good = f"# P — a project (https://github.com/o/r)\n\nBuild: `uv run pytest`\n\n{map_block}\n{idx}"
    assert cs.slim_violations(good) == []
    bare = "# P\n\njust prose, no fences, no url\n"
    probs = cs.slim_violations(bare, require_map=True)
    assert any("project-map fence" in p for p in probs)
    # ...but ONLY for an opted-in project. The map is opt-in
    # (`/janitor-auto-repomap-on`), so for everyone else a missing fence is the normal
    # state, not a defect — reporting it flagged every project that correctly declined,
    # and kept demanding the map back after a deliberate `/janitor-auto-repomap-off`.
    assert not any(
        "project-map fence" in p for p in cs.slim_violations(bare)
    ), "opted-out (the default) must not be told to generate a map it declined"
    assert any("wikimem-index fence" in p for p in probs)
    assert any("github repo url" in p for p in probs)
    monkeypatch.setenv(cs.NARRATIVE_MAX_BYTES_ENV, "10")
    assert any("narrative is" in p for p in cs.slim_violations(good))


def test_index_is_stale_tracks_corpus(tmp_path: Path) -> None:
    memdir = _corpus(tmp_path)
    pages = cs.scan_pages(memdir)
    idx = cs.render_index(pages, generated_iso="2026-08-02T18:00:00+0200")
    text = f"# P\n\n{idx}"
    assert cs.index_is_stale(text, pages) is False
    _page(memdir, "new-page", tier="component", desc="fresh knowledge")
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
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, timeout=30)
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
