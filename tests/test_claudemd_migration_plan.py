"""Tests for the CLAUDE.md migration PLANNER — the DECISION half only (TRDD-LFSWY0C6).

The card's own 2026-08-13 pre-check is explicit: this repo's CLAUDE.md conforms today, so
every acceptance box MUST be exercised against a SYNTHETIC fixture — a run against the live
file would pass every assertion while doing nothing at all (the "green because there was no
work" failure TRDD-4ZSYW21E and TRDD-XFPOAF2I already hit). None of the tests below touch
the repo's real CLAUDE.md or its real PROJECT/LOCAL/USER memory corpus; `roots=` is always a
`tmp_path` fixture corpus, and the recall step runs the REAL memgrep binary built from this
tree (`conftest.MEMGREP_BIN_PATH`) — never a mock.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import MEMGREP_BIN_PATH

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import claudemd_migration_plan as cmig  # noqa: E402
from repomap.claudemd_slim import WIKIMEM_FENCE_END, WIKIMEM_FENCE_START  # noqa: E402
from repomap.renderer import FENCE_END as MAP_END  # noqa: E402
from repomap.renderer import FENCE_START as MAP_START  # noqa: E402

_CLI = _PROJECT_ROOT / "scripts" / "claudemd_slim.py"

needs_memgrep = pytest.mark.skipif(MEMGREP_BIN_PATH is None, reason="memgrep binary unavailable")


def _run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CLI), "--root", str(root), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _page(memdir: Path, name: str, *, desc: str, body: str) -> None:
    memdir.mkdir(parents=True, exist_ok=True)
    (memdir / f"{name}.md").write_text(
        f'---\nname: {name}\ndescription: "{desc}"\nocd: 2026-08-01\nlmd: 2026-08-01\n'
        f"metadata:\n  node_type: memory\n  type: project\n  tier: component\n---\n{body}\n\n"
        "## Notes and lessons learned\n",
        encoding="utf-8",
    )


def _corpus(root: Path) -> Path:
    """A tiny synthetic PROJECT-scope corpus: one page that OWNS the daemon-crash subject
    the fixture's architecture paragraph is about. Nothing owns "widget frobnicator" —
    the fixture the NEW-PAGE guard needs."""
    memdir = root / "mem"
    _page(
        memdir,
        "daemon-restart-behavior",
        desc="why does the daemon restart after it crashes / supervisor loop respawns it",
        body="The daemon is respawned by a supervising watchdog loop whenever its pid file goes stale.",
    )
    return memdir


_MAP_BLOCK = f"{MAP_START} v1 sha=x digest=y generated=z\nmap\n{MAP_END}\n"

_DESCRIPTION_PARAGRAPH = "A one-paragraph description of proj, the thing this repo builds."
_ARCHITECTURE_PARAGRAPH = (
    "The daemon restarts on crash automatically via a supervising watchdog loop that "
    "re-execs the process whenever its pid file goes stale, because a bare launchd "
    "KeepAlive retried too fast and thrashed the process table."
)
_DEVOPS_COMMAND_LINE = "- Tests: `uv run pytest`"
_ORPHAN_PARAGRAPH = (
    "The widget frobnicator subsystem synchronizes its internal state by polling a "
    "queue of pending frobnications and applying them in timestamp order."
)


def _fixture_claude_md() -> str:
    """A non-conforming CLAUDE.md (no wikimem fence) that nonetheless carries a REAL §CM-1
    element-1 description. The description is not decoration: without it the architecture
    paragraph would be the first preamble block and would take the description's one
    permitted slot, so every "this paragraph is migratable" assertion below would be
    testing the wrong block."""
    return (
        "# proj\n\n"
        f"{_DESCRIPTION_PARAGRAPH}\n\n"
        "## Notes\n\n"
        f"{_ARCHITECTURE_PARAGRAPH}\n\n"
        f"{_ORPHAN_PARAGRAPH}\n\n"
        "## Commands\n\n"
        f"{_DEVOPS_COMMAND_LINE}\n\n"
        f"{_MAP_BLOCK}\n"
    )


# ── pure unit tests ──────────────────────────────────────────────────────────────────


def test_split_narrative_blocks_separates_paragraphs_and_list_items() -> None:
    """A heading is structure (skipped); a paragraph is one block; each list item is its
    own block — the granularity the exemption check needs to judge a §Commands line
    independently of its neighbours."""
    narrative = "# H\n\npara one line a\npara one line b\n\n- item one\n- item two\n"
    blocks = cmig.split_narrative_blocks(narrative)
    assert [b.text for b in blocks] == ["para one line a\npara one line b", "- item one", "- item two"]


def test_classify_exemption_matches_the_real_commands_vocabulary() -> None:
    """The literal category table must recognize the surface forms this repo's own
    §Commands section actually uses ("Tests:", "Lint:", "install", "publish.py"), not
    only the spec's own gerund spelling."""
    assert cmig.classify_exemption("- Tests: `uv run pytest`") == "testing"
    assert cmig.classify_exemption("- Lint: `uv run ruff check scripts tests`") in ("linting", "testing")
    assert cmig.classify_exemption("- Release pipeline: `uv run scripts/publish.py`") == "publishing"
    assert cmig.classify_exemption("- Bundled crate: `cargo install --path scripts/memgrep`") == "installing"


def test_classify_exemption_is_multiline_gated() -> None:
    """A multi-sentence explanation that happens to MENTION a dev-ops word is still
    narrative — the spec is explicit that short prose is not exempt however short, and a
    multi-line block is prose, not a single command."""
    prose = "We test this thoroughly.\nSee the architecture page for why."
    assert cmig.classify_exemption(prose) is None


def test_classify_exemption_rejects_unlisted_words() -> None:
    """A word NOT in the closed enumeration (e.g. "verify", "audit", "deploying" spelled
    as "deployment") must never be treated as exempt — the closed-list guarantee."""
    assert cmig.classify_exemption("- Verify: `uv run scripts/audit.py`") is None
    assert cmig.classify_exemption("- Architecture: see the deployment diagram") is None


def test_is_project_url_line_accepts_the_three_link_shapes_and_rejects_prose() -> None:
    """§CM-1 element 2. The three surface forms a project-URL line actually takes — bare,
    angle-bracketed, markdown link — with or without a short `<label>: ` prefix; and NOT a
    prose sentence that merely mentions a URL, which is what separates element 2 from
    narrative."""
    assert cmig.is_project_url_line("- Repo: https://github.com/o/r")
    assert cmig.is_project_url_line("- Marketplace (`ai-maestro-plugins`): https://github.com/o/m")
    assert cmig.is_project_url_line("- Docs: <https://example.com/d>")
    assert cmig.is_project_url_line("- Related: [upstream](https://github.com/o/u)")
    assert cmig.is_project_url_line("https://github.com/o/r")
    assert not cmig.is_project_url_line(
        "The daemon polls https://x.example on every fire because a push model lost events."
    )
    assert not cmig.is_project_url_line("- Note: see https://x.example and then restart the daemon")
    assert not cmig.is_project_url_line("- " + "w" * 70 + ": https://x.example")
    assert not cmig.is_project_url_line("- Tests: `uv run pytest`")


def test_description_is_only_the_first_preamble_paragraph() -> None:
    """§CM-1 element 1 is "ONE-paragraph", so exactly one block can hold it: the first, and
    only while still above the first section heading. A second preamble paragraph is
    excess."""
    blocks = cmig.split_narrative_blocks("# T\n\nfirst para\n\nsecond para\n\n## S\n\nthird para\n")
    assert [b.in_preamble for b in blocks] == [True, True, False]
    assert cmig.classify_permitted(blocks[0], index=0) == cmig.PERMITTED_DESCRIPTION
    assert cmig.classify_permitted(blocks[1], index=1) is None
    assert cmig.classify_permitted(blocks[2], index=2) is None


def test_a_narrative_opening_under_a_section_heading_has_no_description() -> None:
    """The preamble gate is load-bearing, not decoration: put a `## Section` before the
    first paragraph and it is ordinary narrative again. Without this, the description rule
    would hand a free pass to whatever text happened to come first."""
    blocks = cmig.split_narrative_blocks("# T\n\n## Architecture\n\nA long architecture note.\n")
    assert blocks[0].in_preamble is False
    assert cmig.classify_permitted(blocks[0], index=0) is None


def test_build_recall_query_strips_markdown_noise() -> None:
    q = cmig.build_recall_query("- Tests: `uv run pytest` for everything")
    assert "`" not in q
    assert q.startswith("Tests:")


def test_decide_new_page_scope_routes_machine_paths_to_local() -> None:
    assert cmig.decide_new_page_scope("Config lives at /Users/alice/.claude/foo.json") == "local"
    assert cmig.decide_new_page_scope("On this machine we always use the fast path.") == "local"
    assert cmig.decide_new_page_scope("The daemon retries three times before giving up.") == "project"


def test_parse_recall_full_output_extracts_page_atom_score() -> None:
    stdout = (
        "/tmp/x/daemon-restart-behavior.md#ATOM1 — why does it restart\n"
        "\tscore: 2\n"
        "\tkeywords: daemon crash restart\n"
        "some body text that is not a header line\n"
        "/tmp/x/orphan-page.md — an unrelated page\n"
        "\tscore: 0\n"
    )
    hits = cmig.parse_recall_full_output(stdout)
    assert [h.locator for h in hits] == ["daemon-restart-behavior#ATOM1", "orphan-page"]
    assert hits[0].score == 2.0
    assert hits[1].score == 0.0


# ── the three guards from the acceptance list, each against a hermetic tmp_path corpus ──


@needs_memgrep
def test_architecture_paragraph_is_migratable_and_names_the_owning_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance box 1 (§4): a planted architecture paragraph is MIGRATABLE and the
    planner names the wikimem page that owns the subject via recall — never dumped into
    an unrelated page and never silently dropped."""
    monkeypatch.setenv("MEMGREP_BIN", str(MEMGREP_BIN_PATH))
    memdir = _corpus(tmp_path)
    plans = cmig.plan_migration(_fixture_claude_md(), roots=[memdir])
    arch = next(p for p in plans if p.block.text == _ARCHITECTURE_PARAGRAPH)
    assert arch.verdict == "fold"
    assert arch.candidate_page == "daemon-restart-behavior"
    assert arch.candidate_score >= cmig.MIN_RECALL_SCORE


@needs_memgrep
def test_devops_command_line_is_exempt_and_names_the_matched_word(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance box 3 (§4): a dev-ops command line under §Commands is left ALONE, and
    we can name WHICH §CM-3 enumeration word triggered the exemption."""
    monkeypatch.setenv("MEMGREP_BIN", str(MEMGREP_BIN_PATH))
    memdir = _corpus(tmp_path)
    plans = cmig.plan_migration(_fixture_claude_md(), roots=[memdir])
    cmd = next(p for p in plans if p.block.text == _DEVOPS_COMMAND_LINE)
    assert cmd.verdict == "permitted"
    assert cmd.permitted_element == cmig.PERMITTED_DEVOPS
    assert cmd.exemption_word == "testing"


@needs_memgrep
def test_orphan_subject_yields_new_page_not_a_dump_into_an_unrelated_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance box 7 (§4): a subject with no owning page gets NEW PAGE at a named
    scope/tier — specifically NOT folded into the corpus's one unrelated existing page."""
    monkeypatch.setenv("MEMGREP_BIN", str(MEMGREP_BIN_PATH))
    memdir = _corpus(tmp_path)
    plans = cmig.plan_migration(_fixture_claude_md(), roots=[memdir])
    orphan = next(p for p in plans if p.block.text == _ORPHAN_PARAGRAPH)
    assert orphan.verdict == "new_page"
    assert orphan.new_page_scope == "project"
    assert orphan.new_page_tier == "component"
    assert orphan.candidate_page == ""  # never assigned to the unrelated existing page


# ── the planner writes nothing ───────────────────────────────────────────────────────


@needs_memgrep
def test_planner_writes_nothing_pure_function(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling `plan_migration` must not change CLAUDE.md bytes or the memory corpus
    bytes — the DECISION half's whole point is that it removes nothing, writes nothing,
    and creates no memory pages."""
    monkeypatch.setenv("MEMGREP_BIN", str(MEMGREP_BIN_PATH))
    memdir = _corpus(tmp_path)
    claude_md_text = _fixture_claude_md()
    before_corpus = {p.name: p.read_bytes() for p in sorted(memdir.glob("*.md"))}
    before_listing = sorted(p.name for p in memdir.iterdir())

    plans = cmig.plan_migration(claude_md_text, roots=[memdir])
    assert plans  # sanity: the fixture does have narrative blocks to plan over

    after_corpus = {p.name: p.read_bytes() for p in sorted(memdir.glob("*.md"))}
    after_listing = sorted(p.name for p in memdir.iterdir())
    assert before_listing == after_listing
    assert before_corpus == after_corpus


@needs_memgrep
def test_planner_writes_nothing_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same guarantee through the CLI subprocess: `claudemd_slim.py plan` must leave
    CLAUDE.md byte-identical and print a non-empty, non-error plan."""
    monkeypatch.setenv("MEMGREP_BIN", str(MEMGREP_BIN_PATH))
    _corpus(tmp_path)  # memory dir the CLI's own resolve_scope_dirs may or may not see;
    # irrelevant here — this test only proves the CLI never mutates CLAUDE.md.
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(_fixture_claude_md(), encoding="utf-8")
    before = claude_md.read_bytes()

    env_extra = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
    import os

    env = dict(os.environ)
    env.update(env_extra)
    env["MEMGREP_BIN"] = str(MEMGREP_BIN_PATH)
    res = subprocess.run(
        [sys.executable, str(_CLI), "--root", str(tmp_path), "plan"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "narrative block" in res.stdout
    after = claude_md.read_bytes()
    assert before == after


def test_render_plan_reports_no_blocks_when_conforming() -> None:
    """A conforming CLAUDE.md (no narrative outside the fences) plans to nothing — the
    live-file case the card's pre-check warns is otherwise vacuously "green"."""
    text = f"# P — https://github.com/o/r\n\n{_MAP_BLOCK}\n"
    plans = cmig.plan_migration(text, roots=[])
    assert plans == []
    assert "no narrative blocks" in cmig.render_plan(plans)


# ── the 2026-08-13 keystone regression: candidate selection keys on actual violations ──

_WIKI_BLOCK = f"{WIKIMEM_FENCE_START} v1 digest=x generated=y\nindex\n{WIKIMEM_FENCE_END}\n"


def _conforming_claude_md() -> str:
    """A file that GENUINELY conforms to the slim contract: both fences present, a
    github URL in the narrative, and the narrative — title, one-paragraph description,
    a `## Links` URL, a `## Commands` dev-ops line — well under the byte cap. This is
    exactly the shape of the five PERMITTED elements the 2026-08-13 pre-check found the
    planner wrongly proposing to migrate."""
    return (
        "# proj\n\n"
        "A short one-paragraph project description with a link https://github.com/o/r for context.\n\n"
        "## Links\n\n"
        "- Repo: https://github.com/o/r\n\n"
        "## Commands\n\n"
        f"{_DEVOPS_COMMAND_LINE}\n\n"
        f"{_MAP_BLOCK}"
        f"{_WIKI_BLOCK}"
    )


def test_conforming_claude_md_yields_empty_plan() -> None:
    """The keystone regression (TRDD-LFSWY0C6, 2026-08-13 pre-check): a CLAUDE.md that
    `check` already calls conforming (`slim_violations` reports nothing) MUST plan to
    migrate nothing. None of the OTHER fixtures in this file can catch this class of bug
    — every one of them plants a real violation (a missing fence, a missing github URL,
    or both) — which is exactly why 13 green tests missed the live-input defect."""
    text = _conforming_claude_md()
    assert cmig.slim_violations(text) == []  # sanity: this fixture is genuinely conforming
    assert cmig.plan_migration(text, roots=[]) == []


def test_slim_violations_empty_implies_empty_plan_on_the_live_claude_md() -> None:
    """The exact invariant the card demands, checked for free against the repo's own
    live `CLAUDE.md` — no synthetic fixture needed, and no memgrep binary needed either:
    a conforming file short-circuits before the (impure) recall step ever runs."""
    text = (_PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert cmig.slim_violations(text) == []
    assert cmig.plan_migration(text, roots=[]) == []


def test_conforming_gate_actually_gates_a_would_be_migratable_block() -> None:
    """Prove the `slim_violations` SCOPE gate is load-bearing, not vacuous — using a
    genuinely migratable block.

    This test previously asserted that stripping a fence made the DESCRIPTION migratable
    again: the 2026-08-13 defect written down as the expected result. A guard whose
    fixture is the bug cannot fail when the bug is present, which is exactly how it
    survived a green suite. The orphan paragraph is the honest subject — it is excess
    under §CM-1 whether or not the file is over cap, so the only thing varying here is the
    gate itself.
    """
    with_excess = _conforming_claude_md().replace("## Commands\n", f"## Notes\n\n{_ORPHAN_PARAGRAPH}\n\n## Commands\n")
    assert cmig.slim_violations(with_excess) == []  # still conforming: under the byte cap
    assert cmig.plan_migration(with_excess, roots=[]) == []  # ...so the gate suppresses it

    non_conforming = with_excess.replace(_WIKI_BLOCK, "")
    assert cmig.slim_violations(non_conforming) != []
    plans = cmig.plan_migration(non_conforming, roots=[])
    assert [p.block.text for p in plans if p.verdict != "permitted"] == [_ORPHAN_PARAGRAPH]


# ── THE acceptance test: over cap AND carrying every permitted element ─────────────────

_EXCESS_SENTENCE = (
    "The widget frobnicator keeps its internal state consistent by polling a queue of "
    "pending frobnications and applying them in timestamp order, because an earlier "
    "design applied them on arrival and two concurrent producers could interleave a "
    "stale write over a fresh one. "
)
_EXCESS_COUNT = 10
_URL_LINES = (
    "- Repo: https://github.com/o/r",
    "- Marketplace (`plugins`): https://github.com/o/m",
    "- Related: [upstream](https://github.com/o/u)",
)
_COMMAND_LINES = (_DEVOPS_COMMAND_LINE, "- Lint: `uv run ruff check scripts tests`")


def _over_cap_claude_md() -> str:
    """A CLAUDE.md that is BOTH over the narrative byte cap AND carries all three
    narrative-visible §CM-1 elements (description, project URLs, dev-ops commands).

    Neither earlier round of fixtures had this shape, and each missed what the other
    covered: round 1 planted a violation in every fixture but gave none of them the
    permitted elements, round 2 gave the permitted elements only to a CONFORMING file that
    short-circuits before any per-block decision runs. The defect lives exactly in the
    intersection they left empty.
    """
    excess = "\n\n".join(f"Excess paragraph {n}. " + _EXCESS_SENTENCE * 4 for n in range(_EXCESS_COUNT))
    return (
        "# proj\n\n"
        "A short one-paragraph project description with a link https://github.com/o/r for context.\n\n"
        "## Links\n\n" + "\n".join(_URL_LINES) + "\n\n"
        "## Commands\n\n" + "\n".join(_COMMAND_LINES) + "\n\n"
        "## Notes\n\n"
        f"{excess}\n\n"
        f"{_MAP_BLOCK}"
        f"{_WIKI_BLOCK}"
    )


def test_over_cap_file_migrates_the_excess_and_never_a_permitted_element() -> None:
    """The keystone: on the only input shape the chore exists for — a file already over
    the byte cap — every §CM-1 permitted element is left alone AND all of the excess is
    still found.

    Both halves are asserted because either alone is passable by a wrong fix: "no
    permitted element is migratable" is satisfied by planning nothing (the `20f226ba`
    partial fix), and "the excess is found" is satisfied by migrating everything (the
    original defect).
    """
    text = _over_cap_claude_md()
    violations = cmig.slim_violations(text)
    assert any("cap" in v for v in violations), violations  # precondition: OVER CAP, not some other defect

    plans = cmig.plan_migration(text, roots=[])
    by_text = {p.block.text: p for p in plans}

    desc = next(p for p in plans if p.block.text.startswith("A short one-paragraph project description"))
    assert (desc.verdict, desc.permitted_element) == ("permitted", cmig.PERMITTED_DESCRIPTION)
    for line in _URL_LINES:
        assert (by_text[line].verdict, by_text[line].permitted_element) == ("permitted", cmig.PERMITTED_URLS)
    for line in _COMMAND_LINES:
        assert (by_text[line].verdict, by_text[line].permitted_element) == ("permitted", cmig.PERMITTED_DEVOPS)

    migratable = [p for p in plans if p.verdict != "permitted"]
    assert len(migratable) == _EXCESS_COUNT
    assert all(p.block.text.startswith("Excess paragraph ") for p in migratable)
