"""The wikimem worked-example fixture obeys the wiki model's invariants.

The fixture (`tests/fixtures/wikimem-example/`) is the canonical worked example
of the memory-wiki model (TRDD-bc16d602): a `frontend` hub + two radiating
aspects (`style-system`, `dialog-forms`) + three receiving components
(`login-panel`, `settings-panel`, `user-model`), fully wired.

Two layers of REAL tests, no mocks:

- pure-Python structural checks that always run — THE LINK LAW (every link
  bidirectional), no dangling wikilinks, tier schema, components-receive-only,
  and the hub-globs file→functionality mapping;
- memgrep graph checks (the exact commands the skills document) against the real
  binary, following the repo's find-or-build convention (skip-marked only when
  no binary exists AND cargo can't build one).

If a skill doc and this test disagree, the TEST is the empirically-verified
truth — fix the doc.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from fnmatch import fnmatch
from pathlib import Path

import pytest
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE = _PROJECT_ROOT / "tests" / "fixtures" / "wikimem-example"
_MEMGREP_CRATE = _PROJECT_ROOT / "tools" / "memgrep"

# MEMORY.md is the human index, not a wiki page: exempt from page invariants
# (it uses standard md links and legitimately has no inbound wikilinks).
_INDEX_NAME = "MEMORY.md"

_WIKILINK = re.compile(r"\[\[([^\]|#]+)")
_GENERAL_TIERS = {"hub", "aspect"}


def _find_or_build_memgrep() -> str | None:
    """Repo convention (see test_autorecall_hook.py): prebuilt target/ binary →
    PATH → cargo build into a tmp CARGO_TARGET_DIR → None (caller skips)."""
    for rel in ("target/release/memgrep", "target/debug/memgrep"):
        cand = _MEMGREP_CRATE / rel
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    on_path = shutil.which("memgrep")
    if on_path:
        return on_path
    cargo = shutil.which("cargo")
    if not cargo:
        return None
    target_dir = Path("/tmp/memgrep-build")
    env = dict(os.environ)
    env["CARGO_TARGET_DIR"] = str(target_dir)
    try:
        subprocess.run(
            [cargo, "build", "--release", "--manifest-path", str(_MEMGREP_CRATE / "Cargo.toml")],
            check=True, capture_output=True, text=True, timeout=600, env=env,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    built = target_dir / "release" / "memgrep"
    return str(built) if built.is_file() else None


_MEMGREP = _find_or_build_memgrep()
_needs_memgrep = pytest.mark.skipif(
    _MEMGREP is None, reason="memgrep binary unavailable and cargo build failed"
)


def _pages() -> dict[str, str]:
    """name -> raw text for every wiki PAGE (the index excluded)."""
    out: dict[str, str] = {}
    for p in sorted(_FIXTURE.glob("*.md")):
        if p.name == _INDEX_NAME:
            continue
        out[p.stem] = p.read_text(encoding="utf-8")
    return out


def _frontmatter(text: str) -> dict:
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "page must start with YAML frontmatter"
    fm = yaml.safe_load(m.group(1))
    assert isinstance(fm, dict)
    return fm


def _out_links(text: str) -> set[str]:
    return {t.strip() for t in _WIKILINK.findall(text)}


def _mg(args: list[str]) -> str:
    """Run the real memgrep in the fixture dir; fail loudly on error."""
    assert _MEMGREP is not None
    res = subprocess.run(
        [_MEMGREP, *args, "."], cwd=_FIXTURE, capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, f"memgrep {args} failed: {res.stderr}"
    return res.stdout


# ---------------------------------------------------------------- pure-Python

def test_fixture_is_present_and_complete():
    """The worked example ships all six pages plus the MEMORY.md index."""
    names = {p.name for p in _FIXTURE.glob("*.md")}
    assert names == {
        "frontend.md", "style-system.md", "dialog-forms.md",
        "login-panel.md", "settings-panel.md", "user-model.md", _INDEX_NAME,
    }


def test_every_wikilink_resolves():
    """No dangling [[link]]: every target names an existing page."""
    pages = _pages()
    for name, text in pages.items():
        for target in _out_links(text):
            assert target in pages, f"{name} links to missing page [[{target}]]"


def test_every_link_is_bidirectional():
    """THE LINK LAW: if A links to B, B links to A — always, See-also included."""
    pages = _pages()
    links = {name: _out_links(text) for name, text in pages.items()}
    one_sided = [
        f"{a} -> {b} has no back-link"
        for a, targets in links.items()
        for b in targets
        if a not in links.get(b, set())
    ]
    assert not one_sided, "one-sided links violate the link law:\n" + "\n".join(one_sided)


def test_tier_schema_and_lessons_section():
    """Every page declares a valid tier + functionality; hubs carry globs; every
    page keeps the standing lessons section."""
    for name, text in _pages().items():
        fm = _frontmatter(text)
        meta = fm.get("metadata", {})
        tier = meta.get("tier")
        assert tier in {"hub", "aspect", "component"}, f"{name}: bad tier {tier!r}"
        assert meta.get("functionality"), f"{name}: missing functionality"
        if tier == "hub":
            assert meta.get("globs"), f"hub {name}: missing globs (file->functionality map)"
        assert "## Notes and lessons learned" in text, f"{name}: missing lessons section"


def test_components_receive_only_generals_radiate():
    """A component never radiates (`## Applies to` is general-only); general
    pages DO radiate; components carry `## Governed by` up-links."""
    for name, text in _pages().items():
        tier = _frontmatter(text)["metadata"]["tier"]
        if tier == "component":
            assert "## Applies to" not in text, f"component {name} must not radiate"
        else:
            assert tier in _GENERAL_TIERS and "## Applies to" in text, (
                f"general page {name} must carry its Applies-to ray-list"
            )
    # The frontend components point up at their governors.
    for comp in ("login-panel", "settings-panel"):
        text = _pages()[comp]
        assert "## Governed by" in text, f"{comp} must list its governors"


def test_hub_globs_map_file_to_functionality():
    """RECALL Entry A: the file being edited maps to exactly the frontend hub."""
    fm = _frontmatter(_pages()["frontend"])
    globs = fm["metadata"]["globs"]
    assert any(fnmatch("src/frontend/panels/Login.tsx", g) for g in globs)
    assert not any(fnmatch("src/backend/models/user.py", g) for g in globs)


def test_superseded_memory_demoted_to_lesson():
    """The update invariant, demonstrated: dialog-forms carries a [^1] footnote
    whose lesson records the superseded rule WITH its WHY and dates."""
    text = _pages()["dialog-forms"]
    assert "[^1]" in text.split("## Notes and lessons learned")[0], "body cites the lesson"
    lesson = text.split("## Notes and lessons learned")[1]
    assert "[^1]:" in lesson and "[ocd:" in lesson, "dated lesson entry"
    assert "Superseded" in lesson and "Lesson:" in lesson, "lesson carries the WHY"


# ------------------------------------------------------------------- memgrep

@_needs_memgrep
def test_memgrep_no_broken_links():
    assert _mg(["links", "--broken"]).strip() == ""


@_needs_memgrep
def test_memgrep_orphans_only_the_index():
    orphans = {ln.strip() for ln in _mg(["links", "--orphans"]).splitlines() if ln.strip()}
    assert orphans <= {f"./{_INDEX_NAME}"}, f"unexpected orphan pages: {orphans}"


@_needs_memgrep
def test_memgrep_out_and_back_links_agree():
    """The link law via the tool: for every page, the set of pages it points at
    (`links --to`, out-links) equals the set pointing at it (`links --from`,
    backlinks), modulo the index file."""
    for page in _pages():
        out_targets = {m.group(1) for m in re.finditer(r"-> (\S+)", _mg(["links", "--to", page]))}
        back_sources = {
            Path(ln.strip()).stem
            for ln in _mg(["links", "--from", page]).splitlines()
            if ln.strip() and Path(ln.strip()).name != _INDEX_NAME
        }
        assert out_targets == back_sources, (
            f"{page}: out-links {sorted(out_targets)} != backlinks {sorted(back_sources)}"
        )


@_needs_memgrep
def test_memgrep_fm_queries_select_tiers():
    """The skills' documented --where queries select the right pages."""
    hubs = {Path(ln).stem for ln in
            _mg(["-l", ".", "--where", 'fm.tier "hub"']).splitlines() if ln.strip()}
    assert hubs == {"frontend"}
    comps = {Path(ln).stem for ln in
             _mg(["-l", ".", "--where", 'fm.tier "component" and fm.functionality "frontend"']).splitlines()
             if ln.strip()}
    assert comps == {"login-panel", "settings-panel"}


@_needs_memgrep
def test_memgrep_recall_surfaces_page_then_the_hop_returns_the_lesson():
    """Symptom recall lands on dialog-forms; the SECOND HOP brings back the lesson's WHY.

    Retrieval is two-hop since the output layers shipped: hop 1 is a lean triage row and the
    lessons — the largest block the tool emits — arrive only with the hop the reader chose to
    take. This test tracks that contract rather than the old always-rich default, because the
    old shape is exactly the per-hit cost the layers removed (441 -> 247 tokens/query).
    """
    out = _mg(["recall", "how should dialogs confirm destructive action"])
    # The locator is the page's `name:` — an IDENTITY and an exact recall key — NOT its filename
    # (TRDD-YBOZW3ES). Asserting `dialog-forms.md` here was asserting the pre-locator-change shape,
    # so this test could only pass against a binary older than the contract it claims to track.
    locator = out.splitlines()[0].split("\t")[1]
    assert locator == "dialog-forms", f"hop-1 locator must be the page name, got {locator!r}"
    assert "destructive default" not in out, (
        "hop 1 is a TRIAGE row — appending every hit's lessons is the cost the layers removed"
    )
    # Hop 2: pay for exactly the page the triage row named.
    full = _mg(["recall", "how should dialogs confirm destructive action", "--output", "full"])
    assert "destructive default" in full, "the lesson WHY must come back with the full record"
