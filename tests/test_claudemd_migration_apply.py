"""Tests for the CLAUDE.md migration DELIVERY half — the code that REMOVES (TRDD-LFSWY0C6).

The card's §5 names knowledge-shredding as risk #1 and its pre-check is explicit about what
would make these tests worthless: *"the preservation oracle is not merely A gate — it is the
ONLY evidence the chore is safe. It must be falsified explicitly: plant content, break the
oracle, and prove the chore REFUSES to remove. An oracle that has never been seen to say no
is decoration."* So the refusal tests here are the point, and the happy path is the control.

Every fixture is synthetic and every write lands in `tmp_path`; the repo's real CLAUDE.md and
its real memory corpus are never touched. The one real-input test copies the live CLAUDE.md
into a tmp root and runs the DRY-RUN path, which writes nothing anywhere.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import claudemd_migration_apply as cma  # noqa: E402
import claudemd_migration_plan as cmig  # noqa: E402
from repomap.claudemd_slim import WIKIMEM_FENCE_END, WIKIMEM_FENCE_START  # noqa: E402
from repomap.renderer import FENCE_END as MAP_END  # noqa: E402
from repomap.renderer import FENCE_START as MAP_START  # noqa: E402

_CLI = _PROJECT_ROOT / "scripts" / "claudemd_slim.py"

_MAP_BLOCK = f"{MAP_START} v1 sha=x digest=y generated=z\nmap body\n{MAP_END}\n"
_WIKI_BLOCK = f"{WIKIMEM_FENCE_START} v1 digest=abcdef123456 generated=z\nindex body\n{WIKIMEM_FENCE_END}\n"

_DESCRIPTION = "A one-paragraph description of proj, the thing this repository builds."
_URL_LINE = "- Repo: https://github.com/o/r"
_COMMAND_LINE = "- Tests: `uv run pytest`"
# Both excess fixtures are MULTI-LINE, because real narrative wraps and because a
# single-line paragraph is a different classification case: `classify_exemption`'s gate is
# structural (one line + a §CM-3 word), so a one-line sentence merely CONTAINING a category
# word — "an earlier event-push design…" matches `\bpush\b` across the hyphen — reads as
# dev-ops and is PERMITTED. That is the decision half's documented, deliberate bias toward
# keeping a block (TRDD-LFSWY0C6's classifier section), not a delivery-half concern; a
# fixture that tripped it would be testing the classifier instead of the applier.
_EXCESS = (
    "The widget frobnicator subsystem synchronizes its internal state by polling\n"
    "a queue of pending frobnications and applying them in strict timestamp order,\n"
    "because an earlier event-driven design silently dropped frobnications during\n"
    "a reconnect."
)
_SECOND_EXCESS = (
    "The retry budget is deliberately six attempts and not ten, because ten kept\n"
    "the socket open past the upstream gateway idle timeout of ninety seconds."
)


def _claude_md(*, excess: tuple[str, ...] = (_EXCESS,)) -> str:
    """A CLAUDE.md carrying all three narrative-visible §CM-1 permitted elements PLUS
    excess narrative — the intersection shape the card demands, since a fixture missing
    either half lets one of the two failure classes hide behind the other."""
    body = "\n\n".join(excess)
    return (
        "# proj\n\n"
        f"{_DESCRIPTION}\n\n"
        "## Links\n\n"
        f"{_URL_LINE}\n\n"
        "## Commands\n\n"
        f"{_COMMAND_LINE}\n\n"
        "## Notes\n\n"
        f"{body}\n\n"
        f"{_MAP_BLOCK}"
        f"{_WIKI_BLOCK}"
    )


def _corpus(*texts: str) -> list[str]:
    """A wiki corpus that has ALREADY received the migrated text — what the memory agent
    produces in CM-2 step 3, before it is allowed to ask for step 4."""
    return [
        f"---\nname: p{i}\ndescription: \"x\"\n---\n{t}\n\n## Notes and lessons learned\n"
        for i, t in enumerate(texts)
    ]


def _reasons(result: cma.ApplyResult) -> set[str]:
    return {r.reason for r in result.refusals}


# ── the control: a correct migration goes through ────────────────────────────────────


def test_apply_removes_the_excess_and_leaves_every_permitted_element_intact() -> None:
    """The happy path, asserted in BOTH directions — the excess is gone AND all three
    permitted elements survive. Either assertion alone is passable by a wrong
    implementation: removing nothing satisfies "permitted elements survive", and removing
    everything satisfies "the excess is gone"."""
    text = _claude_md()
    result = cma.apply_migration(text, [_EXCESS], _corpus(_EXCESS))
    assert result.ok, result.refusals
    assert result.removed == 1
    assert _EXCESS not in result.text
    assert _DESCRIPTION in result.text
    assert _URL_LINE in result.text
    assert _COMMAND_LINE in result.text


def test_apply_leaves_both_janitor_fences_byte_identical() -> None:
    """CM-2 step 5: "the map fence byte-identical when only narrative moved". The fences
    are the janitor's own generated regions — a migration that perturbs them makes the map
    and index digests lie about content nobody changed."""
    text = _claude_md()
    result = cma.apply_migration(text, [_EXCESS], _corpus(_EXCESS))
    assert result.ok, result.refusals
    assert _MAP_BLOCK in result.text
    assert _WIKI_BLOCK in result.text


def test_apply_removes_several_blocks_in_one_pass() -> None:
    text = _claude_md(excess=(_EXCESS, _SECOND_EXCESS))
    result = cma.apply_migration(text, [_EXCESS, _SECOND_EXCESS], _corpus(_EXCESS, _SECOND_EXCESS))
    assert result.ok, result.refusals
    assert result.removed == 2
    assert _EXCESS not in result.text and _SECOND_EXCESS not in result.text


# ── the refusals — the reason this module exists ─────────────────────────────────────


def test_apply_refuses_when_the_content_was_never_written_anywhere() -> None:
    """THE oracle, OBSERVED SAYING NO. An empty corpus is exactly the state before the
    memory agent has done CM-2 step 3, and removing then is the knowledge-shredding this
    card's §5 lists as risk #1. A gate that has only ever been seen to pass is decoration —
    this is the test that makes it evidence."""
    result = cma.apply_migration(_claude_md(), [_EXCESS], corpus_texts=[])
    assert not result.ok
    assert cma.REFUSE_CONTENT_DROPPED in _reasons(result)
    assert result.text == ""  # nothing to write, not even a partial candidate


def test_apply_refuses_a_permitted_element_even_though_preservation_would_pass() -> None:
    """The guard the ORACLE CANNOT PROVIDE. The description here HAS been copied into the
    corpus, so preservation is satisfied — and removing it is still wrong, because §CM-1
    requires CLAUDE.md to carry a description. Preservation and correctness are different
    properties; this asserts the applier checks the second one."""
    result = cma.apply_migration(_claude_md(), [_DESCRIPTION], _corpus(_DESCRIPTION))
    assert not result.ok
    assert _reasons(result) == {cma.REFUSE_NOT_EXCESS}
    assert "description" in result.refusals[0].detail


def test_apply_refuses_a_project_url_line_and_a_devops_command() -> None:
    """The other two permitted elements, each with its content safely in the corpus so
    that only the correctness gate can be what refuses."""
    for permitted in (_URL_LINE, _COMMAND_LINE):
        result = cma.apply_migration(_claude_md(), [permitted], _corpus(permitted))
        assert not result.ok, permitted
        assert _reasons(result) == {cma.REFUSE_NOT_EXCESS}


def test_apply_refuses_text_that_is_not_a_narrative_block_of_this_file() -> None:
    """A caller's paraphrase, or a block read from an earlier revision. Matching such a
    string against the raw file is how a delete lands somewhere nobody intended, so the
    request is rejected before any matching happens."""
    result = cma.apply_migration(_claude_md(), ["frobnicator"], _corpus(_EXCESS))
    assert not result.ok
    assert _reasons(result) == {cma.REFUSE_NOT_EXCESS}
    assert "not a narrative block" in result.refusals[0].detail


def test_apply_refuses_when_nothing_is_requested() -> None:
    """An empty request that reported success would be the "green because there was no
    work" failure this card has already hit twice — a caller cannot distinguish it from a
    migration that ran."""
    result = cma.apply_migration(_claude_md(), [], _corpus(_EXCESS))
    assert not result.ok
    assert _reasons(result) == {cma.REFUSE_NOTHING_REQUESTED}


def test_apply_refuses_when_the_block_is_not_uniquely_located() -> None:
    """Two identical paragraphs: the file cannot say which one the plan meant, so neither
    is removed. Exact-unique-match is the Edit tool's discipline, for the same reason."""
    text = _claude_md(excess=(_EXCESS, _EXCESS))
    result = cma.apply_migration(text, [_EXCESS], _corpus(_EXCESS))
    assert not result.ok
    assert _reasons(result) == {cma.REFUSE_NOT_UNIQUE}


def test_apply_refuses_when_the_only_github_url_lives_in_the_migrated_block() -> None:
    """`slim_violations` requires a github url in the narrative, so a removal that strips
    the last one trades one contract violation for another. Constructed so the URL is NOT
    in a permitted `## Links` line — otherwise the correctness gate would refuse first and
    this gate would never be reached."""
    prose = (
        "The upstream mirror at https://github.com/o/mirror is polled hourly because the "
        "primary index lags behind releases by up to a day."
    )
    text = (
        "# proj\n\n"
        f"{_DESCRIPTION}\n\n"
        "## Commands\n\n"
        f"{_COMMAND_LINE}\n\n"
        "## Notes\n\n"
        f"{prose}\n\n"
        f"{_MAP_BLOCK}"
        f"{_WIKI_BLOCK}"
    )
    assert "github.com/" not in _DESCRIPTION  # precondition: the prose holds the ONLY url
    result = cma.apply_migration(text, [prose], _corpus(prose))
    assert not result.ok
    assert cma.REFUSE_URL_DROPPED in _reasons(result)


def test_apply_refuses_when_the_unique_match_lives_inside_a_janitor_fence() -> None:
    """The hazard the uniqueness gate CANNOT catch: a narrative block that straddles a
    fence has its pre- and post-fence lines joined in the narrative, so the joined string
    never occurs contiguously outside the fence — and if the fence body happens to contain
    that same string, the match is unique and it is in exactly the wrong place."""
    twin_map = f"{MAP_START} v1 sha=x digest=y generated=z\nfoo\nbar\n{MAP_END}\n"
    text = (
        "# proj\n\n"
        f"{_DESCRIPTION}\n\n"
        "## Notes\n\n"
        "foo\n"
        f"{twin_map}"
        "bar\n\n"
        f"{_WIKI_BLOCK}"
    )
    straddler = next(
        b.text for b, element in cmig.classify_blocks(text) if element is None and b.text == "foo\nbar"
    )
    assert text.count(straddler) == 1  # precondition: unique, and the one match is IN the fence
    result = cma.apply_migration(text, [straddler], _corpus(straddler))
    assert not result.ok
    assert cma.REFUSE_FENCE_ALTERED in _reasons(result)


# ── the CLI: the surface the chore actually calls ────────────────────────────────────


def _write_root(tmp_path: Path, text: str, *, pages: dict[str, str] | None = None) -> Path:
    root = tmp_path / "proj"
    (root / ".claude" / "project" / "memory").mkdir(parents=True, exist_ok=True)
    (root / "CLAUDE.md").write_text(text, encoding="utf-8")
    for name, body in (pages or {}).items():
        (root / ".claude" / "project" / "memory" / f"{name}.md").write_text(
            f'---\nname: {name}\ndescription: "owns the frobnicator subject"\nocd: 2026-08-01\n'
            f"lmd: 2026-08-01\nmetadata:\n  node_type: memory\n  type: project\n  tier: component\n"
            f"---\n{body}\n\n## Notes and lessons learned\n",
            encoding="utf-8",
        )
    return root


def _run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CLI), "--root", str(root), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_apply_dry_run_refuses_and_writes_nothing(tmp_path: Path) -> None:
    """`--dry-run` runs every gate and touches no file — the free way to discover a
    refusal before the chore is trusted with the write."""
    root = _write_root(tmp_path, _claude_md())
    before = (root / "CLAUDE.md").read_text(encoding="utf-8")
    blocks = tmp_path / "blocks.json"
    blocks.write_text(json.dumps([_EXCESS]), encoding="utf-8")

    res = _run_cli(root, "apply", "--blocks", str(blocks), "--dry-run")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "REFUSED" in res.stdout and "content-dropped" in res.stdout
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == before


def test_cli_apply_writes_only_once_the_content_is_in_the_corpus(tmp_path: Path) -> None:
    """End-to-end through the real CLI: the same request that was refused above succeeds
    the moment the wiki page owning the subject exists — the CM-2 step-3-before-step-4
    ordering, enforced rather than documented."""
    root = _write_root(tmp_path, _claude_md(), pages={"frobnicator": _EXCESS})
    blocks = tmp_path / "blocks.json"
    blocks.write_text(json.dumps([_EXCESS]), encoding="utf-8")

    res = _run_cli(root, "apply", "--blocks", str(blocks))
    assert res.returncode == 0, res.stdout + res.stderr
    after = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert _EXCESS not in after
    assert _DESCRIPTION in after and _URL_LINE in after and _COMMAND_LINE in after
    assert _MAP_BLOCK in after and _WIKI_BLOCK in after


def test_cli_apply_points_at_the_index_refresh_it_deliberately_does_not_do(tmp_path: Path) -> None:
    """CM-2 step 6 is a separate write with its own fence and lock, so `apply` does not
    perform it — but landing the owning page moved the corpus digest, so the index IS now
    stale. Observed on real input that nothing said so; silence there is its own defect."""
    root = _write_root(tmp_path, _claude_md(), pages={"frobnicator": _EXCESS})
    blocks = tmp_path / "blocks.json"
    blocks.write_text(json.dumps([_EXCESS]), encoding="utf-8")

    res = _run_cli(root, "apply", "--blocks", str(blocks))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "index is now STALE" in res.stdout
    # and it POINTED, it did not act: the wikimem fence is byte-identical.
    assert _WIKI_BLOCK in (root / "CLAUDE.md").read_text(encoding="utf-8")


def test_cli_apply_rejects_a_malformed_blocks_file(tmp_path: Path) -> None:
    root = _write_root(tmp_path, _claude_md())
    blocks = tmp_path / "blocks.json"
    blocks.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    res = _run_cli(root, "apply", "--blocks", str(blocks))
    assert res.returncode == 3
    assert "JSON array" in res.stdout


# ── real input, because fixtures are what let both earlier rounds ship broken ─────────


def test_the_live_claude_md_pushed_over_cap_refuses_without_a_corpus() -> None:
    """Run against THIS repo's real CLAUDE.md — the check that caught both earlier misses
    on this card, applied to the delivery half. Its excess is planned but nothing has been
    written to any wiki page, so the correct answer is a REFUSAL naming dropped content."""
    live = (_PROJECT_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    over_cap = live.replace(
        "## Links",
        "## Notes\n\n" + "\n\n".join(f"Excess note {n}. {_EXCESS}" for n in range(10)) + "\n\n## Links",
        1,
    )
    excess_blocks = [b.text for b, element in cmig.classify_blocks(over_cap) if element is None]
    assert excess_blocks, "precondition: the pushed-over-cap live file must have excess blocks"

    result = cma.apply_migration(over_cap, excess_blocks, corpus_texts=[])
    assert not result.ok
    assert cma.REFUSE_CONTENT_DROPPED in _reasons(result)
    assert result.text == ""
