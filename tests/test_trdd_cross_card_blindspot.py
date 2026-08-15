"""Integration tests for the trdd-cross-card-blindspot detector (TRDD-XFPOAF2I).

Real I/O, no mocks: each case writes fixture TRDDs directly under
design/tasks/ (no git needed — this detector never touches git) and runs the
detector as a SUBPROCESS with CLAUDE_PROJECT_DIR pointed at the fixture.

Load-bearing cases:
  * two open cards sharing a ref, neither citing the other -> ONE pair reported.
  * card A's external-refs names card B -> SILENT.
  * card A's BODY mentions TRDD-<B-id8> -> SILENT.
  * one of the two cards is terminal -> SILENT.
  * three cards sharing one ref -> 3 pairs, each reported once (no dupes).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

DETECTOR = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "detectors"
    / "trdd-cross-card-blindspot.py"
)


def _load_blindspot_module() -> Any:
    """Load the detector as an importable module for white-box unit tests.

    Returns `Any`, deliberately: the falsification tests below ASSIGN to the module's
    attributes (break the gate, observe, restore), and pyright rejects attribute
    assignment on `ModuleType` — 4 errors on the first CI run where pyright had a real
    venv (31850287797). The dynamic typing is the point of a white-box loader.

    The detector's filename has hyphens (it is invoked as a script, not
    imported normally elsewhere), so it needs `importlib.util` the same way
    the rest of this repo's white-box tests load hyphenated scripts (see
    tests/test_daemon_throttle.py). The module's own top-level code inserts
    `scripts/lib` onto `sys.path` before importing `dedupe`/`state`/
    `trdd_common`, so exec_module resolves those without extra setup here.
    """
    spec = importlib.util.spec_from_file_location("trdd_cross_card_blindspot_mod", DETECTOR)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # MUST be registered in sys.modules before exec — the module uses
    # `from __future__ import annotations` (string annotations) and its
    # `@dataclass` decorator resolves them via `sys.modules[cls.__module__]`.
    # Skipping this makes the dataclass decorator crash with an
    # AttributeError on a None module lookup.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

_TS = "20260101_000000+0000"


def _trdd_path(root: Path, uid: str) -> Path:
    return root / "design" / "tasks" / f"TRDD-{_TS}-{uid}-slug.md"


def _write_trdd(
    root: Path,
    uid: str,
    *,
    column: str = "todo",
    external_refs: str = "[]",
    body: str = "\n# body\nx\n",
) -> Path:
    text = textwrap.dedent(
        f"""\
        ---
        trdd-id: {uid}
        title: T
        column: {column}
        external-refs: {external_refs}
        ---
        """
    ) + body
    p = _trdd_path(root, uid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "design" / "tasks").mkdir(parents=True)
    return root


def _run(root: Path) -> str:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    env["JANITOR_FORCE_AI_MAESTRO"] = "1"
    env.pop("CLAUDE_PLUGIN_OPTION_TRDD_PATH", None)
    res = subprocess.run(
        [sys.executable, str(DETECTOR)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    return res.stdout


def test_shared_ref_no_cross_reference_reports_one_pair(repo: Path):
    """Two open cards citing the same issue, neither naming the other, surfaces one pair."""
    uid_a, uid_b = "aaaaaaaa", "bbbbbbbb"
    _write_trdd(repo, uid_a, external_refs="[janitor#241]")
    _write_trdd(repo, uid_b, external_refs="[janitor#241]")

    out = _run(repo)
    assert "[trdd-cross-card-blindspot]" in out
    assert f"TRDD-{uid_a}" in out
    assert f"TRDD-{uid_b}" in out
    assert "janitor#241" in out


def test_external_refs_cross_reference_silences_pair(repo: Path):
    """Card A's external-refs naming card B silences the pair entirely."""
    uid_a, uid_b = "cccccccc", "dddddddd"
    _write_trdd(repo, uid_a, external_refs=f"[janitor#241, TRDD-{uid_b}]")
    _write_trdd(repo, uid_b, external_refs="[janitor#241]")

    out = _run(repo)
    assert out.strip() == ""


def test_body_mention_silences_pair(repo: Path):
    """Card A's BODY mentioning TRDD-<B-id8> silences the pair, even with empty external-refs."""
    uid_a, uid_b = "eeeeeeee", "ffffffff"
    _write_trdd(
        repo, uid_a, external_refs="[janitor#241]",
        body=f"\n## STATE\nsee also TRDD-{uid_b} for the other half of this fix.\n",
    )
    _write_trdd(repo, uid_b, external_refs="[janitor#241]")

    out = _run(repo)
    assert out.strip() == ""


def test_terminal_card_excludes_pair(repo: Path):
    """One of the two cards being terminal (column: complete) silences the pair."""
    uid_a, uid_b = "11111111", "22222222"
    _write_trdd(repo, uid_a, column="complete", external_refs="[janitor#241]")
    _write_trdd(repo, uid_b, column="todo", external_refs="[janitor#241]")

    out = _run(repo)
    assert out.strip() == ""


def test_three_cards_sharing_ref_report_three_distinct_pairs(repo: Path):
    """Three open cards sharing one ref report exactly 3 pairs, no duplicates, no A/B + B/A."""
    uid_a, uid_b, uid_c = "33333333", "44444444", "55555555"
    _write_trdd(repo, uid_a, external_refs="[janitor#900]")
    _write_trdd(repo, uid_b, external_refs="[janitor#900]")
    _write_trdd(repo, uid_c, external_refs="[janitor#900]")

    out = _run(repo)
    assert "3 pair(s)" in out
    for pair in (
        f"TRDD-{uid_a} & TRDD-{uid_b}",
        f"TRDD-{uid_a} & TRDD-{uid_c}",
        f"TRDD-{uid_b} & TRDD-{uid_c}",
    ):
        assert pair in out
    # No reversed duplicate of any pair.
    assert f"TRDD-{uid_b} & TRDD-{uid_a}" not in out
    assert f"TRDD-{uid_c} & TRDD-{uid_a}" not in out
    assert f"TRDD-{uid_c} & TRDD-{uid_b}" not in out


def test_a_shared_trdd_ref_is_not_a_pair(repo: Path):
    """Two cards citing the same PARENT card is hub-and-spoke structure, not blindness.

    An umbrella card is cited by many unrelated children (one per contract row), so keying
    on a shared `TRDD-<id8>` pairs every child with every other and reports cards that have
    nothing to do with each other.

    It is also SELF-INFLICTED and unbounded, which is what makes it fatal rather than merely
    noisy: cross-linking is the remedy this detector RECOMMENDS, so each remedy adds a shared
    TRDD-ref and manufactures the next finding. Observed live immediately after shipping —
    cross-linking the janitor#246 pair created a brand-new pair whose only shared ref was the
    umbrella both had just been linked to. A check whose own advice re-arms it never
    converges, and a check that never converges gets switched off.
    """
    uid_a, uid_b = "11111111", "22222222"
    _write_trdd(repo, uid_a, external_refs="[TRDD-99999999]")
    _write_trdd(repo, uid_b, external_refs="[TRDD-99999999]")

    assert _run(repo).strip() == ""


def test_rg4iuz6i_3qiq2e6j_prelink_state_is_not_caught(repo: Path):
    """Characterization test (TRDD-4EKZ81MV) — the shared-ref mechanism CANNOT catch this
    real, confirmed miss, at any point before the two cards were cross-linked.

    Reconstructed from git history of the real cards: TRDD-RG4IUZ6I was created with
    `external-refs: [janitor#241, janitor#227]`; TRDD-3QIQ2E6J was created with
    `external-refs: [TRDD-WP7TCRME]` and only gained `janitor#241` in the SAME commit
    that added the `TRDD-RG4IUZ6I` cross-reference (854259d8). There was never a window
    where the two shared a ref without also already citing each other — the detector's
    grouping key never had anything to group on. This is NOT a regression to fix here;
    it documents why the detector's own docstring calls this a structural blind spot
    that needs a new (unratified) similarity signal, not a tweak to this detector.
    """
    rg4iuz6i, sanqiq = "rg4iuz61", "3qiq2e61"  # 8-char stand-ins for the real ids
    _write_trdd(repo, rg4iuz6i, external_refs="[janitor#241, janitor#227]")
    _write_trdd(repo, sanqiq, external_refs="[TRDD-WP7TCRME]")

    assert _run(repo).strip() == ""


def test_az6qrk0d_jpl0ju86_never_shared_a_ref(repo: Path):
    """Characterization test (TRDD-4EKZ81MV) — same structural miss, zero-overlap case.

    Reconstructed from git history of the real cards: TRDD-AZ6QRK0D was created with NO
    `external-refs:` at all; TRDD-JPL0JU86 was created with
    `external-refs: [janitor#249, TRDD-G4BCRUP7]`. The two never shared a ref, at
    creation or since — so the shared-ref grouping this detector implements has no
    signal to key on, regardless of how strongly the two cards' content overlaps.
    """
    az6qrk0d, jpl0ju86 = "az6qrk01", "jpl0ju81"  # 8-char stand-ins for the real ids
    _write_trdd(repo, az6qrk0d, external_refs="[]")
    _write_trdd(repo, jpl0ju86, external_refs="[janitor#249, TRDD-G4BCRUP7]")

    assert _run(repo).strip() == ""


def test_an_issue_ref_still_pairs_when_a_trdd_ref_is_also_shared(repo: Path):
    """The TRDD-ref exclusion must not swallow a REAL finding that rides alongside it —
    two cards sharing both an umbrella AND a genuine issue still surface on the issue."""
    uid_a, uid_b = "33333333", "44444444"
    _write_trdd(repo, uid_a, external_refs="[TRDD-99999999, janitor#777]")
    _write_trdd(repo, uid_b, external_refs="[TRDD-99999999, janitor#777]")

    out = _run(repo)
    assert "1 pair(s)" in out
    assert "janitor#777" in out
    assert "99999999" not in out


# ── Signal 2: shared rare vocabulary (TRDD-4EKZ81MV acceptance) ──────────────


def test_az6qrk0d_jpl0ju86_content_similarity_now_catches_prelink_state(repo: Path):
    """TRDD-4EKZ81MV acceptance box 1: the pre-link JPL0JU86/AZ6QRK0D pair — reconstructed
    from real evidence, zero shared `external-refs:` at any point before or after the
    manual 2026-08-12 cross-link — is now caught by the content-similarity signal, which
    the shared-ref signal (see `test_az6qrk0d_jpl0ju86_never_shared_a_ref` above)
    structurally cannot see.

    Both cards describe the SAME symlink mechanism from opposite ends (one calls it the
    wrong mechanism, the other generalises it) but never cite each other or share a ref.
    Frontmatter reconstructs the PRE-link state (refs as they were at creation, no
    cross-reference in either body) — testing against today's already-cross-linked files
    would pass for the wrong reason, per the acceptance box's own wording.
    """
    az6qrk0d, jpl0ju86 = "az6qrk01", "jpl0ju81"
    _write_trdd(
        repo, az6qrk0d, external_refs="[]",
        body=(
            "\n## STATE\nThe USER-scope memory symlink mechanism points the wrong "
            "direction — it links the plugin DATA dir INTO the mirror instead of the "
            "other way around.\n"
        ),
    )
    _write_trdd(
        repo, jpl0ju86, external_refs="[janitor#249, TRDD-G4BCRUP7]",
        body=(
            "\n## STATE\nGeneralising the symlink mechanism so any USER-scope store, "
            "not just memory, survives a plugin uninstall via the same technique.\n"
        ),
    )

    out = _run(repo)
    assert "[trdd-cross-card-blindspot]" in out
    assert f"TRDD-{az6qrk0d}" in out
    assert f"TRDD-{jpl0ju86}" in out
    assert "shared vocabulary" in out
    assert "symlink" in out


def test_iterm_trio_content_similarity_catches_the_no_refs_card(repo: Path):
    """TRDD-4EKZ81MV acceptance box 2: at least one pair from the real iTerm-alarm trio
    is caught, INCLUDING the card that carries no `external-refs:` at all — the case the
    shared-ref signal cannot see even in principle, since pairing needs two refs to share.
    """
    no_refs, with_refs = "9pdh8g01", "ez3pmqx1"
    _write_trdd(
        repo, no_refs, external_refs="[]",
        body="\n# Notes\nThe iTerm automation alarm keeps firing after every session grant.\n",
    )
    _write_trdd(
        repo, with_refs, external_refs="[janitor#92, janitor#233]",
        body="\n# Notes\nDedupe for the iTerm automation alarm is scoped per grant window.\n",
    )
    _write_trdd(
        repo, "ku3eryf1", external_refs="[janitor#234]",
        body="\n# Notes\nCompletely unrelated card about a different subsystem entirely.\n",
    )

    out = _run(repo)
    assert f"TRDD-{no_refs}" in out
    assert f"TRDD-{with_refs}" in out
    assert "shared vocabulary" in out


def test_content_similarity_silenced_by_cross_reference(repo: Path):
    """The same cross-link silencer signal 1 uses also clears a content-similarity pair —
    one remedy (naming the other card) resolves either finding."""
    uid_a, uid_b = "symlk001", "symlk002"
    _write_trdd(
        repo, uid_a, external_refs="[]",
        body=f"\n## STATE\nsymlink mechanism generalises to TRDD-{uid_b}.\n",
    )
    _write_trdd(
        repo, uid_b, external_refs="[]",
        body="\n## STATE\nsymlink mechanism direction confusion here.\n",
    )

    assert _run(repo).strip() == ""


def test_shared_house_vocabulary_across_many_cards_does_not_manufacture_a_pair(repo: Path):
    """TRDD-4EKZ81MV acceptance box 4 (no regression): a word used broadly across the
    OPEN board is common, not distinctive — the rarity gate must suppress it even though
    two cards share it twice over, or ordinary house vocabulary would manufacture pairs
    everywhere the board happens to reuse the same two words.
    """
    common_words = "gateway cluster"
    x, y = "gwclus01", "gwclus02"
    _write_trdd(repo, x, external_refs="[]", body=f"\n# Notes\n{common_words} config for team A.\n")
    _write_trdd(repo, y, external_refs="[]", body=f"\n# Notes\n{common_words} rollout for team B.\n")
    # Three more cards reusing the SAME two words, unrelated to X/Y or each other — pushes
    # the document frequency of "gateway"/"cluster" above the rarity threshold.
    for i in range(3):
        _write_trdd(
            repo, f"gwclus0{3 + i}", external_refs="[]",
            body=f"\n# Notes\n{common_words} note {i}.\n",
        )

    assert _run(repo).strip() == ""


def test_rarity_gate_falsified_without_it_common_words_pair_everything():
    """Falsification (TRDD-4EKZ81MV): the rarity gate (`_rarity_threshold`) is
    load-bearing for the no-regression case above — proven by BREAKING it in-process
    (monkeypatching it to accept every word regardless of document frequency), observing
    the pair now fires (RED for the guarded expectation), then restoring it (GREEN)."""
    mod = _load_blindspot_module()
    Card = mod._Card
    cards = {
        "x": Card(uid="x", scope="project", ext_refs=[], body="gateway cluster team A", title=""),
        "y": Card(uid="y", scope="project", ext_refs=[], body="gateway cluster team B", title=""),
        "p": Card(uid="p", scope="project", ext_refs=[], body="gateway cluster note", title=""),
        "q": Card(uid="q", scope="project", ext_refs=[], body="gateway cluster note", title=""),
        "r": Card(uid="r", scope="project", ext_refs=[], body="gateway cluster note", title=""),
    }

    # GREEN — guarded: "gateway"/"cluster" have document frequency 5, well above the
    # rarity threshold (2 for a 5-card board), so they are filtered and x/y do not pair.
    guarded = mod._find_content_similarity_pairs(cards)
    assert frozenset({"x", "y"}) not in guarded

    # RED — falsified: with the gate forced open (every word accepted as "rare"
    # regardless of frequency), x/y now DO pair. This is the observation that proves
    # the gate — not some other guard — was what suppressed them above.
    original = mod._rarity_threshold
    try:
        mod._rarity_threshold = lambda total_cards: total_cards  # accept everything
        broken = mod._find_content_similarity_pairs(cards)
        assert frozenset({"x", "y"}) in broken
    finally:
        mod._rarity_threshold = original  # restore — GREEN again

    # Confirm the restore actually took effect (not just scoped to the `finally`).
    assert frozenset({"x", "y"}) not in mod._find_content_similarity_pairs(cards)


def test_min_shared_words_gate_falsified_single_rare_word_would_pair_without_it():
    """Falsification (TRDD-4EKZ81MV): `_MIN_SHARED_CONTENT_WORDS` guards against a
    SINGLE coincidental rare-word match between two otherwise-unrelated cards. Proven by
    breaking it in-process (lowering the threshold to 1), observing the pair now fires,
    then restoring it."""
    mod = _load_blindspot_module()
    Card = mod._Card
    cards = {
        "a": Card(uid="a", scope="project", ext_refs=[], body="symlink unrelated topic alpha", title=""),
        "b": Card(uid="b", scope="project", ext_refs=[], body="symlink totally different topics", title=""),
    }

    # GREEN — guarded: only one shared rare word ("symlink"); below the >=2 threshold.
    guarded = mod._find_content_similarity_pairs(cards)
    assert frozenset({"a", "b"}) not in guarded

    # RED — falsified: threshold lowered to 1, the single shared word is now enough.
    original = mod._MIN_SHARED_CONTENT_WORDS
    try:
        mod._MIN_SHARED_CONTENT_WORDS = 1
        broken = mod._find_content_similarity_pairs(cards)
        assert frozenset({"a", "b"}) in broken
    finally:
        mod._MIN_SHARED_CONTENT_WORDS = original  # restore — GREEN again

    assert frozenset({"a", "b"}) not in mod._find_content_similarity_pairs(cards)
