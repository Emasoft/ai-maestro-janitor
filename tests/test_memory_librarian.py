"""Tests for the memory-librarian detector — the FIRST, SAFE slice.

This detector is a *surfacer*, not a mutator (TRDD-c77dae09). It READS the
per-project agent-memory corpus (`~/.claude/projects/<slug>/memory/`), uses
`memgrep index`/`links` to cheaply (no-LLM) find AGGREGATION candidates
(clusters of same-topic notes) and CONFLICT candidates (same-topic note pairs
that are not linked and might duplicate/contradict), then WRITES a proposal
file `memory-reorg-proposed.md` and emits one heartbeat line. It NEVER moves,
merges, edits, or deletes a single memory note (RULE 0 — the load-bearing
safety invariant; an agent does the actual reorg).

Real I/O, no mocks: each case builds a temp HOME + memory dir and runs the
detector as a subprocess with CLAUDE_PROJECT_DIR + HOME pointed at the fixture.
Cases that exercise the memgrep-driven detection are skipped when the memgrep
binary is absent (the detector itself is a graceful no-op without it).
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "memory-librarian.py"
PROPOSAL_NAME = "memory-reorg-proposed.md"

_MEMGREP = (
    os.environ.get("MEMGREP_BIN")
    or shutil.which("memgrep")
    or str(Path(os.environ.get("HOME") or os.path.expanduser("~")) / ".cargo" / "bin" / "memgrep")
)
_HAVE_MEMGREP = bool(_MEMGREP) and Path(_MEMGREP).exists()


def _slug(project_dir: str) -> str:
    """Mirror memory_scopes.project_slug (the SSOT): dash EVERY non-alphanumeric
    char, not just separators. macOS TemporaryDirectory paths contain `_`
    (/var/folders/…), so a separators-only slug diverges from the detector's and
    it reads an empty dir (regression caught by publish, TRDD-4MMXTJFB wave 1)."""
    return re.sub(r"[^A-Za-z0-9]", "-", project_dir)


def _note(name: str, description: str, tags: list[str], body: str = "body.") -> str:
    """Render a memory note in the corpus's frontmatter shape — SHAPE-COMPLIANT.

    Includes the mandatory `## Notes and lessons learned` section and the
    `ocd:`/`lmd:` per-element dates, so the page-shape validator (rank 3) finds
    NOTHING wrong with it. Candidate-focused tests use this so their
    "no candidate" silence assertions are not perturbed by shape findings; the
    page-shape tests build deliberately-malformed notes inline.
    """
    taglist = "[" + ", ".join(tags) + "]" if tags else "[]"
    return (
        f"---\nname: {name}\ndescription: \"{description}\"\ntags: {taglist}\n"
        f"ocd: 2026-06-09\nlmd: 2026-06-09\n"
        f"metadata:\n  node_type: memory\n---\n{body}\n\n"
        f"## Notes and lessons learned\n"
    )


def _build(home: Path, project: Path) -> Path:
    """Create the per-project agent-memory dir under a fake HOME; return it."""
    memdir = home / ".claude" / "projects" / _slug(str(project)) / "memory"
    memdir.mkdir(parents=True, exist_ok=True)
    return memdir


def _run(home: Path, project: Path, session: str = "testsess") -> str:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_SESSION_ID"] = session
    # The detector self-resolves memgrep; make the test's choice explicit so a
    # cargo-bin-only install is found regardless of the subprocess PATH.
    if _HAVE_MEMGREP:
        env["MEMGREP_BIN"] = _MEMGREP
    env.pop("CLAUDE_PLUGIN_OPTION_MEMORY_LIBRARIAN_INTERVAL", None)
    res = subprocess.run(
        [sys.executable, str(DETECTOR)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    # Surface a crash loudly — the detector must NEVER exit non-zero on the
    # heartbeat path (it would log to dispatch as a failure).
    if res.returncode != 0:
        raise AssertionError(f"detector exited {res.returncode}; stderr:\n{res.stderr}")
    return res.stdout


def _corpus_fingerprint(memdir: Path) -> dict[str, str]:
    """SHA-256 of every NOTE file (the proposal/index are NOT notes).

    This is the load-bearing safety probe: the librarian must leave every
    memory note byte-identical. We hash the note bodies only — the proposal
    file is expected to appear/change, the notes are expected to be frozen.
    """
    out: dict[str, str] = {}
    for p in sorted(memdir.rglob("*.md")):
        if p.name in (PROPOSAL_NAME, "memory-index.md"):
            continue
        out[str(p.relative_to(memdir))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@unittest.skipUnless(_HAVE_MEMGREP, "memgrep binary not installed")
class TestMemoryLibrarianDetection(unittest.TestCase):
    """The memgrep-driven candidate detection (skipped without the binary)."""

    def test_aggregation_candidate_detected(self):
        """≥2 notes sharing a tag are surfaced as an aggregation candidate."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "oauth-keychain.md").write_text(
                _note("oauth-keychain", "rotator creds location", ["oauth", "rotator"]))
            (memdir / "oauth-rotator.md").write_text(
                _note("oauth-rotator", "rotator three layers", ["oauth", "rotator"]))
            (memdir / "head-tee.md").write_text(
                _note("head-tee", "tee head sigpipe truncation", ["shell"]))
            out = _run(home, project)
            self.assertIn("[memory-librarian]", out)
            self.assertIn("aggregation", out)
            self.assertIn(PROPOSAL_NAME, out)
            proposal = (memdir / PROPOSAL_NAME).read_text()
            # Both same-topic notes named in the proposal; the lone note is not
            # in any cluster.
            self.assertIn("oauth-keychain.md", proposal)
            self.assertIn("oauth-rotator.md", proposal)

    def test_conflict_candidate_detected_for_unlinked_same_topic_pair(self):
        """Same-topic notes that do NOT link each other are flagged as a conflict candidate."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            # Two notes, same tag, neither links the other → MIGHT contradict.
            (memdir / "retry-cap-a.md").write_text(
                _note("retry-cap-a", "widget retry cap value", ["retry"],
                      body="The widget retries 3 times then fails."))
            (memdir / "retry-cap-b.md").write_text(
                _note("retry-cap-b", "widget retry cap value", ["retry"],
                      body="The widget retries 5 times then fails."))
            out = _run(home, project)
            self.assertIn("[memory-librarian]", out)
            self.assertIn("conflict", out)
            proposal = (memdir / PROPOSAL_NAME).read_text()
            self.assertIn("retry-cap-a.md", proposal)
            self.assertIn("retry-cap-b.md", proposal)

    def test_linked_same_topic_pair_not_a_conflict_candidate(self):
        """Same-topic notes that DO `[[link]]` each other are not conflict candidates.

        A tangential mention that already links the canonical page is the wiki
        invariant working as intended — not a duplication to reconcile.
        """
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "topic-a.md").write_text(
                _note("topic-a", "canonical topic A", ["alpha"],
                      body="Canonical facts. See [[topic-b]]."))
            (memdir / "topic-b.md").write_text(
                _note("topic-b", "tangential topic B", ["alpha"],
                      body="Tangential mention. See [[topic-a]]."))
            _run(home, project)  # produces the proposal; we assert on the file
            # They still cluster for AGGREGATION (same tag), but the proposal's
            # conflict section must not pair an already-cross-linked couple.
            if (memdir / PROPOSAL_NAME).exists():
                proposal = (memdir / PROPOSAL_NAME).read_text()
                # The conflict section, if present, must not list this pair.
                conflict_section = proposal.split("## Conflict")[-1] if "## Conflict" in proposal else ""
                self.assertNotIn("topic-a.md", conflict_section)

    def test_no_candidates_when_every_note_distinct_topic(self):
        """A corpus where no two notes share a topic emits nothing and writes no proposal."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "a.md").write_text(_note("a", "alpha topic", ["alpha"]))
            (memdir / "b.md").write_text(_note("b", "bravo topic", ["bravo"]))
            (memdir / "c.md").write_text(_note("c", "charlie topic", ["charlie"]))
            out = _run(home, project)
            self.assertEqual(out.strip(), "")
            self.assertFalse((memdir / PROPOSAL_NAME).exists())

    def test_user_mem_subdir_never_scanned(self):
        """The private user-mem/ sibling store is excluded from the librarian scan.

        Privacy contract: the agent-corpus librarian must never walk into
        user-mem. Two user-mem notes sharing a tag must NOT produce a candidate.
        """
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            usermem = memdir / "user-mem"
            usermem.mkdir()
            (usermem / "000001.md").write_text(_note("u1", "secret a", ["private"]))
            (usermem / "000002.md").write_text(_note("u2", "secret b", ["private"]))
            # One lone agent note with a different topic — no agent-corpus cluster.
            (memdir / "agent.md").write_text(_note("agent", "agent topic", ["public"]))
            out = _run(home, project)
            self.assertEqual(out.strip(), "")
            self.assertFalse((memdir / PROPOSAL_NAME).exists())

    def test_wiki_only_scope_is_analyzed_and_shape_checked(self):
        """F20 (wikimem audit 2026-07-07): a scope whose notes ALL live under
        `wiki/` (exactly what the coexistence harvest produces) must be analyzed
        — the old top-level-only gate skipped it entirely, and the shape pass
        never saw curated wiki pages. The finding is labeled by the rel path."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            wiki = memdir / "wikimem"
            wiki.mkdir()
            # Malformed curated page: NO mandatory `## Notes and lessons learned`.
            (wiki / "badpage.md").write_text(
                "---\nname: badpage\ndescription: \"a curated page\"\n"
                "ocd: 2026-06-09\nlmd: 2026-06-09\n"
                "metadata:\n  node_type: memory\n  tier: component\n---\nA fact.\n"
            )
            out = _run(home, project)
            self.assertIn("[memory-librarian]", out)
            proposal = (memdir / PROPOSAL_NAME).read_text()
            self.assertIn("wikimem/badpage.md", proposal)

    def test_wiki_conflict_pair_reads_real_bodies(self):
        """F20: the contradiction scan must read a NESTED note's real body — the
        old basename keying made `_read_note_texts` read `memdir/<basename>`
        (nonexistent for `wiki/` pages) and silently compared empty bodies, so
        a wiki-page contradiction was invisible."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            wiki = memdir / "wikimem"
            wiki.mkdir()
            (wiki / "retry-cap-a.md").write_text(
                _note("retry-cap-a", "widget retry cap value", ["retry"],
                      body="The widget retries 3 times then fails."))
            (wiki / "retry-cap-b.md").write_text(
                _note("retry-cap-b", "widget retry cap value", ["retry"],
                      body="The widget retries 5 times then fails."))
            out = _run(home, project)
            self.assertIn("[memory-librarian]", out)
            self.assertIn("conflict", out)
            proposal = (memdir / PROPOSAL_NAME).read_text()
            self.assertIn("wikimem/retry-cap-a.md", proposal)
            self.assertIn("wikimem/retry-cap-b.md", proposal)

    def test_proposal_file_not_treated_as_a_note(self):
        """A pre-existing proposal file is never itself clustered/flagged."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            # A leftover proposal with tags must not become a candidate.
            (memdir / PROPOSAL_NAME).write_text(
                _note("proposal", "stale proposal", ["oauth"]))
            (memdir / "lone.md").write_text(_note("lone", "lone topic", ["solo"]))
            out = _run(home, project)
            self.assertEqual(out.strip(), "")

    def test_tagless_notes_cluster_by_name_description_overlap(self):
        """Harness-format notes (NO tags:) cluster via shared name/description topic words.

        Mirrors the real corpus: notes carry name+description but no `tags:`. Two
        notes whose names+descriptions share ≥2 significant topic words must be
        surfaced as an aggregation candidate, so the librarian is not dead on the
        actual notes it is meant to organize.
        """
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            # No tags at all — pure name/description signal (filenames carry topic).
            (memdir / "reference_oauth_rotator_keychain.md").write_text(
                _note("reference_oauth_rotator_keychain",
                      "the oauth rotator keychain credential storage layer", []))
            (memdir / "reference_oauth_rotator_layers.md").write_text(
                _note("reference_oauth_rotator_layers",
                      "the oauth rotator three layers rotate renew reauth", []))
            (memdir / "feedback_head_tee_sigpipe.md").write_text(
                _note("feedback_head_tee_sigpipe",
                      "tee head sigpipe truncation capture file", []))
            out = _run(home, project)
            self.assertIn("[memory-librarian]", out)
            self.assertIn("aggregation", out)
            proposal = (memdir / PROPOSAL_NAME).read_text()
            self.assertIn("reference_oauth_rotator_keychain.md", proposal)
            self.assertIn("reference_oauth_rotator_layers.md", proposal)

    def test_connected_components_collapse_one_topic_into_one_cluster(self):
        """Many same-topic notes form ONE cluster, not one bucket per token-subset.

        Three oauth/rotator notes (pairwise overlapping topic words) must collapse
        into a single aggregation cluster — the over-fragmentation bug (one cluster
        per shared-token-subset) must not recur.
        """
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "oauth_rotator_alpha.md").write_text(
                _note("oauth_rotator_alpha", "oauth rotator account slot capture", []))
            (memdir / "oauth_rotator_beta.md").write_text(
                _note("oauth_rotator_beta", "oauth rotator account renew keychain", []))
            (memdir / "oauth_rotator_gamma.md").write_text(
                _note("oauth_rotator_gamma", "oauth rotator account reauth cookie", []))
            out = _run(home, project)
            self.assertIn("[memory-librarian]", out)
            proposal = (memdir / PROPOSAL_NAME).read_text()
            # Count aggregation bullet lines — exactly ONE cluster covering all 3.
            agg = proposal.split("## Aggregation")[1].split("## Conflict")[0]
            bullets = [ln for ln in agg.splitlines() if ln.startswith("- topic ")]
            self.assertEqual(len(bullets), 1, f"expected ONE merged cluster, got:\n{agg}")
            self.assertIn("oauth_rotator_alpha.md", bullets[0])
            self.assertIn("oauth_rotator_beta.md", bullets[0])
            self.assertIn("oauth_rotator_gamma.md", bullets[0])

    def test_issue35_generic_theme_notes_do_not_overcluster(self):
        """Issue #35: distinct subtopics that merely share a generic THEME word are
        NOT collapsed into one aggregation cluster. Five tagless notes whose only
        common tokens are high-df theme words (document-frequency-gated out), each
        carrying its own distinctive word, must produce NO aggregation candidate
        and NO conflict pair — the small-corpus over-clustering FP is gone.
        """
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            for w in ("alpha", "bravo", "charlie", "delta", "echo"):
                (memdir / f"topic_{w}.md").write_text(
                    _note(f"topic_{w}", f"telemetry dashboard {w} subtopic", []))
            # one unrelated note keeps the corpus small (df threshold = the floor)
            (memdir / "unrelated.md").write_text(
                _note("unrelated", "keychain rotator cookie", []))
            out = _run(home, project)
            self.assertNotIn("aggregation", out)
            self.assertNotIn("conflict", out)

    def test_distinctive_token_pair_still_clusters(self):
        """Guard against over-gating: two notes sharing DISTINCTIVE (low-df) tokens
        are still surfaced as an aggregation candidate — the precision fix must not
        suppress a genuine same-subject duplicate.
        """
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "frobnicator_setup.md").write_text(
                _note("frobnicator_setup", "the frobnicator widget bootstrap routine", []))
            (memdir / "frobnicator_teardown.md").write_text(
                _note("frobnicator_teardown", "the frobnicator widget shutdown routine", []))
            (memdir / "unrelated.md").write_text(
                _note("unrelated", "keychain rotator cookie", []))
            out = _run(home, project)
            self.assertIn("[memory-librarian]", out)
            self.assertIn("aggregation", out)
            proposal = (memdir / PROPOSAL_NAME).read_text()
            self.assertIn("frobnicator_setup.md", proposal)
            self.assertIn("frobnicator_teardown.md", proposal)

    def test_issue43_distinct_userpreference_notes_not_conflict_or_aggregation(self):
        """Issues #38/#43: two DISTINCT user-preference notes that share ONLY the
        broad `user-preferences` tag (different subjects, no contradiction) must be
        surfaced as NEITHER a conflict NOR an aggregation candidate — the detector
        stays fully silent (coarse tag skipped, no distinctive-token overlap)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "feedback_github_comment_self_identification.md").write_text(
                _note("feedback_github_comment_self_identification",
                      "how to sign github comments with the self-id first line",
                      ["user-preferences"]))
            (memdir / "feedback_personal_account_automation_legit.md").write_text(
                _note("feedback_personal_account_automation_legit",
                      "automating the owner paid accounts is tos legitimate",
                      ["user-preferences"]))
            out = _run(home, project)
            self.assertEqual(out.strip(), "", f"expected silence, got: {out!r}")
            self.assertFalse((memdir / PROPOSAL_NAME).exists())

    def test_complementary_same_subject_is_aggregation_not_conflict(self):
        """Issue #35: two SAME-SUBJECT notes that are COMPLEMENTARY (no opposing
        claim) are an AGGREGATION candidate but NOT a conflict — conflict needs a
        real contradiction signal, not topic overlap."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "frobnicator_usage.md").write_text(
                _note("frobnicator_usage",
                      "the frobnicator widget calibration knob location", [],
                      body="Turn the frobnicator calibration knob clockwise to engage."))
            (memdir / "frobnicator_notes.md").write_text(
                _note("frobnicator_notes",
                      "the frobnicator widget calibration knob caveats", [],
                      body="The frobnicator calibration knob also resets on sleep."))
            (memdir / "unrelated.md").write_text(
                _note("unrelated", "keychain rotator cookie", []))
            out = _run(home, project)
            self.assertIn("aggregation", out)
            proposal = (memdir / PROPOSAL_NAME).read_text()
            conflict = proposal.split("### Conflict candidates")[1].split("### Page shape")[0]
            self.assertIn("(none)", conflict,
                          f"complementary pair must not be a conflict; got:\n{conflict}")

    def test_real_antonym_contradiction_is_a_conflict(self):
        """A GENUINE contradiction — two same-subject notes making OPPOSING claims
        (always vs never about the same subject) — IS surfaced as a conflict."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "widget_reset_always.md").write_text(
                _note("widget_reset_always", "widget reset policy on sleep", [],
                      body="Always reset the widget on sleep."))
            (memdir / "widget_reset_never.md").write_text(
                _note("widget_reset_never", "widget reset policy on sleep", [],
                      body="Never reset the widget on sleep."))
            out = _run(home, project)
            self.assertIn("[memory-librarian]", out)
            proposal = (memdir / PROPOSAL_NAME).read_text()
            conflict = proposal.split("### Conflict candidates")[1].split("### Page shape")[0]
            self.assertIn("widget_reset_always.md", conflict)
            self.assertIn("widget_reset_never.md", conflict)


def _raw_note(
    *,
    name: str | None = "n",
    description: str | None = "a topic description",
    body: str = "Some facts.",
    lessons_section: bool = True,
    ocd: bool = True,
    lmd: bool = True,
) -> str:
    """Build a note with FINE-GRAINED control over which shape elements exist.

    Lets a page-shape test omit exactly one element (the lessons section, the
    `name`/`description` key, the `ocd`/`lmd` date) and assert the validator
    flags precisely that. By default every element is present (shape-clean).
    """
    fm = ["---"]
    if name is not None:
        fm.append(f"name: {name}")
    if description is not None:
        fm.append(f'description: "{description}"')
    if ocd:
        fm.append("ocd: 2026-06-09")
    if lmd:
        fm.append("lmd: 2026-06-09")
    fm += ["metadata:", "  node_type: memory", "---"]
    text = "\n".join(fm) + "\n" + body + "\n"
    if lessons_section:
        text += "\n## Notes and lessons learned\n"
    return text


@unittest.skipUnless(_HAVE_MEMGREP, "memgrep binary not installed")
class TestMemoryLibrarianPageShape(unittest.TestCase):
    """Per-note structural-integrity validator (rank 3, TRDD-c77dae09).

    The detector no-ops entirely without memgrep, so these run only with the
    binary present — but the shape checks themselves read the note files
    directly (memgrep's index output is unreliable for frontmatter presence).
    """

    def _shape_section(self, memdir: Path) -> str:
        """The proposal's `### Page shape` block (the part after that header,
        up to the next `###` header). Empty string if no proposal was written."""
        prop = memdir / PROPOSAL_NAME
        if not prop.exists():
            return ""
        text = prop.read_text()
        if "### Page shape" not in text:
            return ""
        after = text.split("### Page shape", 1)[1]
        return after.split("\n### ", 1)[0]

    def test_missing_lessons_section_flagged(self):
        """A note with no `## Notes and lessons learned` section is surfaced."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "no_section.md").write_text(
                _raw_note(name="no_section", lessons_section=False))
            out = _run(home, project)
            self.assertIn("[memory-librarian]", out)
            self.assertIn("page-shape", out)
            shape = self._shape_section(memdir)
            self.assertIn("no_section.md", shape)
            self.assertIn("Notes and lessons learned", shape)

    def test_nested_ocd_lmd_under_metadata_not_flagged_missing(self):
        """#33: a write-path normalizer nests ocd/lmd under `metadata:` instead
        of top-level. The dates ARE present, so the date-presence advisory must
        not false-flag them missing."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "nested.md").write_text(
                '---\nname: nested\ndescription: "a topic"\n'
                "metadata:\n  node_type: memory\n"
                "  ocd: 2026-06-14\n  lmd: 2026-06-14\n---\n"
                "Body.\n\n## Notes and lessons learned\n")
            _run(home, project)
            shape = self._shape_section(memdir)
            self.assertNotIn("missing `ocd`", shape)
            self.assertNotIn("missing `lmd`", shape)

    def test_truly_missing_ocd_lmd_still_flagged(self):
        """Guard the positive direction: ocd/lmd absent at EVERY depth still fires
        the advisory (the depth-tolerant fix must not blind the check)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "nodate.md").write_text(_raw_note(name="nodate", ocd=False, lmd=False))
            _run(home, project)
            shape = self._shape_section(memdir)
            self.assertIn("nodate.md", shape)
            self.assertIn("missing `ocd`", shape)

    def test_hub_without_globs_flagged(self):
        """Wikimem (TRDD-bc16d602): a `tier: hub` page with no `globs:` is flagged
        (the file→functionality map RECALL Entry A depends on)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "myhub.md").write_text(
                '---\nname: myhub\ndescription: "frontend overview"\n'
                "ocd: 2026-06-10\nlmd: 2026-06-10\n"
                "metadata:\n  node_type: memory\n  tier: hub\n"
                "  functionality: frontend\n---\nOverview.\n\n"
                "## Notes and lessons learned\n")
            _run(home, project)
            shape = self._shape_section(memdir)
            self.assertIn("myhub.md", shape)
            self.assertIn("globs", shape)

    def test_component_with_applies_to_flagged_and_clean_wiki_pages_silent(self):
        """Wikimem: a component that RADIATES (`## Applies to`) is flagged;
        a well-formed hub (globs) + component (Governed by) are NOT flagged."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "badcomp.md").write_text(
                '---\nname: badcomp\ndescription: "a widget panel"\n'
                "ocd: 2026-06-10\nlmd: 2026-06-10\n"
                "metadata:\n  node_type: memory\n  tier: component\n---\n"
                "Body.\n\n## Applies to\n- [[goodhub]]\n\n"
                "## Notes and lessons learned\n")
            (memdir / "goodhub.md").write_text(
                '---\nname: goodhub\ndescription: "area overview"\n'
                "ocd: 2026-06-10\nlmd: 2026-06-10\n"
                "metadata:\n  node_type: memory\n  tier: hub\n"
                '  globs: ["src/widgets/**"]\n---\nOverview.\n\n'
                "## Applies to\n- [[badcomp]]\n\n"
                "## Notes and lessons learned\n")
            _run(home, project)
            shape = self._shape_section(memdir)
            self.assertIn("badcomp.md", shape)
            self.assertIn("must not radiate", shape)
            self.assertNotIn("goodhub.md", shape)

    def test_fenced_applies_to_is_not_a_radiating_violation(self):
        """Simulation S10b regression: a component whose body shows `## Applies
        to` ONLY inside a fenced code EXAMPLE must NOT be flagged as radiating
        (the shape scan is fence-aware, like memgrep's link parser)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "fencedcomp.md").write_text(
                '---\nname: fencedcomp\ndescription: "a widget panel"\n'
                "ocd: 2026-06-10\nlmd: 2026-06-10\n"
                "metadata:\n  node_type: memory\n  tier: component\n---\n"
                "Body. Doc example:\n\n```markdown\n## Applies to\n- [[ghost]]\n```\n\n"
                "## Notes and lessons learned\n")
            _run(home, project)
            shape = self._shape_section(memdir)
            self.assertNotIn("fencedcomp.md", shape,
                             "fenced example must not trigger the radiating check")

    def test_flow_style_metadata_tier_is_detected(self):
        """Simulation S10a regression: FLOW-style `metadata: {tier: hub}` must
        not be invisible to the tier checks — a flow-style hub missing globs is
        still flagged."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "flowhub.md").write_text(
                '---\nname: flowhub\ndescription: "area overview"\n'
                "ocd: 2026-06-10\nlmd: 2026-06-10\n"
                "metadata: {node_type: memory, tier: hub}\n---\nOverview.\n\n"
                "## Notes and lessons learned\n")
            _run(home, project)
            shape = self._shape_section(memdir)
            self.assertIn("flowhub.md", shape)
            self.assertIn("globs", shape)

    def test_lessons_section_case_insensitive_and_ampersand_accepted(self):
        """`## Notes & Lessons Learned` (historical spelling, any case) satisfies the section check."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            body = "Facts here."
            text = (
                '---\nname: histfmt\ndescription: "topic"\nocd: 2026-06-09\n'
                "lmd: 2026-06-09\nmetadata:\n  node_type: memory\n---\n"
                f"{body}\n\n## NOTES & lessons LEARNED\n"
            )
            (memdir / "histfmt.md").write_text(text)
            _run(home, project)
            shape = self._shape_section(memdir)
            # The note is otherwise clean, so it must NOT be flagged for a missing
            # section despite the `&` + mixed case.
            self.assertNotIn("histfmt.md: missing", shape)

    def test_undefined_footnote_ref_flagged(self):
        """A body `[^N]` reference with no `[^N]:` definition is surfaced (memgrep ignores it silently)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "danglingref.md").write_text(
                _raw_note(name="danglingref",
                          body="A fact with a broken footnote[^7]. No def below."))
            _run(home, project)
            shape = self._shape_section(memdir)
            self.assertIn("danglingref.md", shape)
            self.assertIn("[^7]", shape)
            self.assertIn("no definition", shape)

    def test_dangling_footnote_def_flagged(self):
        """A `[^N]:` definition that no body `[^N]` references is surfaced."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            text = (
                '---\nname: orphandef\ndescription: "topic"\nocd: 2026-06-09\n'
                "lmd: 2026-06-09\nmetadata:\n  node_type: memory\n---\n"
                "Facts with no reference to the lesson.\n\n"
                "## Notes and lessons learned\n[^9]: a lesson nobody points at.\n"
            )
            (memdir / "orphandef.md").write_text(text)
            _run(home, project)
            shape = self._shape_section(memdir)
            self.assertIn("orphandef.md", shape)
            self.assertIn("[^9]", shape)
            self.assertIn("never referenced", shape)

    def test_resolved_footnote_not_flagged(self):
        """A `[^N]` ref WITH a matching `[^N]:` def is clean (no footnote finding)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            text = (
                '---\nname: resolved\ndescription: "topic"\nocd: 2026-06-09\n'
                "lmd: 2026-06-09\nmetadata:\n  node_type: memory\n---\n"
                "A corrected fact[^3].\n\n"
                "## Notes and lessons learned\n[^3]: the WHY of the correction.\n"
            )
            (memdir / "resolved.md").write_text(text)
            _run(home, project)
            shape = self._shape_section(memdir)
            self.assertNotIn("resolved.md", shape)

    def test_missing_description_flagged(self):
        """A note with no `description:` frontmatter key is surfaced (unrecallable)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "nodesc.md").write_text(
                _raw_note(name="nodesc", description=None))
            _run(home, project)
            shape = self._shape_section(memdir)
            self.assertIn("nodesc.md", shape)
            self.assertIn("description", shape)

    def test_missing_name_flagged(self):
        """A note with no `name:` frontmatter key is surfaced."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "noname.md").write_text(_raw_note(name=None))
            _run(home, project)
            shape = self._shape_section(memdir)
            self.assertIn("noname.md", shape)
            self.assertIn("name", shape)

    def test_missing_ocd_lmd_is_advisory(self):
        """Missing `ocd`/`lmd` dates surface as ADVISORY (older notes predate the convention)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "nodates.md").write_text(
                _raw_note(name="nodates", ocd=False, lmd=False))
            _run(home, project)
            shape = self._shape_section(memdir)
            self.assertIn("nodates.md", shape)
            self.assertIn("ocd", shape)
            self.assertIn("advisory", shape)

    def test_created_updated_aliases_satisfy_ocd_lmd(self):
        """`created:`/`updated:` are accepted aliases — no advisory ocd/lmd finding."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            text = (
                '---\nname: aliased\ndescription: "topic"\ncreated: 2026-06-09\n'
                "updated: 2026-06-09\nmetadata:\n  node_type: memory\n---\n"
                "Facts.\n\n## Notes and lessons learned\n"
            )
            (memdir / "aliased.md").write_text(text)
            _run(home, project)
            shape = self._shape_section(memdir)
            self.assertNotIn("aliased.md", shape)

    def test_clean_corpus_has_no_page_shape_findings(self):
        """A fully shape-compliant corpus surfaces NO page-shape findings (silence test)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            # Two clean notes, DISTINCT topics with no shared significant token
            # (names + descriptions share nothing) → no clustering either, so the
            # whole detector stays silent and writes no proposal.
            (memdir / "alpha.md").write_text(
                _raw_note(name="alpha", description="alpha widget pipeline"))
            (memdir / "bravo.md").write_text(
                _raw_note(name="bravo", description="bravo keychain rotator"))
            out = _run(home, project)
            self.assertEqual(out.strip(), "")
            self.assertFalse((memdir / PROPOSAL_NAME).exists())

    def test_single_malformed_note_surfaces_even_without_a_cluster(self):
        """One malformed note (no cluster possible) still surfaces via the shape pass.

        Proves the shape pass is independent of the ≥2-note clustering gate —
        a lone broken page is not invisible just because it can't cluster.
        """
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "lonely.md").write_text(
                _raw_note(name="lonely", lessons_section=False))
            out = _run(home, project)
            self.assertIn("[memory-librarian]", out)
            self.assertIn("page-shape", out)


@unittest.skipUnless(_HAVE_MEMGREP, "memgrep binary not installed")
class TestMemoryLibrarianLinksAndSync(unittest.TestCase):
    """Broken-links, orphans, and MEMORY.md↔disk sync (rank 4, TRDD-c77dae09)."""

    def _section(self, memdir: Path, header: str) -> str:
        """Return the proposal block under `### <header>` (up to the next `###`)."""
        prop = memdir / PROPOSAL_NAME
        if not prop.exists():
            return ""
        text = prop.read_text()
        marker = f"### {header}"
        if marker not in text:
            return ""
        return text.split(marker, 1)[1].split("\n### ", 1)[0]

    def test_broken_link_surfaced(self):
        """A page with a `[[link]]` to a nonexistent note is flagged as a broken link."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "has_broken.md").write_text(
                _note("has_broken", "topic about widgets and retries", [],
                      body="See [[does-not-exist]] for more."))
            out = _run(home, project)
            self.assertIn("[memory-librarian]", out)
            self.assertIn("link/sync", out)
            broken = self._section(memdir, "Broken links")
            self.assertIn("has_broken.md", broken)
            self.assertIn("does-not-exist", broken)

    def test_one_sided_link_surfaced(self):
        """THE LINK LAW (TRDD-bc16d602): a note→note link with no reciprocal is
        flagged as one-sided, naming both endpoints and the missing back-link."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            # alpha links beta; beta does NOT link back → one-sided.
            (memdir / "alpha.md").write_text(
                _note("alpha", "alpha widget topic", [], body="See [[beta]]."))
            (memdir / "beta.md").write_text(
                _note("beta", "beta gadget topic", [], body="No links here."))
            out = _run(home, project)
            self.assertIn("[memory-librarian]", out)
            self.assertIn("link/sync", out)
            one_sided = self._section(memdir, "One-sided links (the link law)")
            self.assertIn("alpha", one_sided)
            self.assertIn("beta", one_sided)
            self.assertIn("no back-link", one_sided)

    def test_bidirectional_links_are_not_flagged(self):
        """A fully reciprocal pair satisfies the link law → the one-sided section
        stays `(none)` (the corpus also carries a broken link so a proposal
        exists to inspect, without perturbing the a<->b reciprocity)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "a.md").write_text(
                _note("a", "alpha widget topic", [], body="See [[b]]."))
            (memdir / "b.md").write_text(
                _note("b", "bravo gadget topic", [],
                      body="Back to [[a]]. Also [[missing-page]]."))
            _run(home, project)
            one_sided = self._section(memdir, "One-sided links (the link law)")
            self.assertIn("(none)", one_sided)
            # the a<->b reciprocal pair itself is never reported one-sided
            self.assertNotIn("no back-link to `a`", one_sided)
            self.assertNotIn("no back-link to `b`", one_sided)

    def test_orphan_surfaced_only_in_a_linked_corpus(self):
        """An orphan page is surfaced when the corpus HAS a link graph it is left out of."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            # a <-> b form a link graph; c is isolated → c is the orphan.
            (memdir / "a.md").write_text(
                _note("a", "alpha topic core", [], body="See [[b]]."))
            (memdir / "b.md").write_text(
                _note("b", "bravo topic core", [], body="See [[a]]."))
            (memdir / "c.md").write_text(
                _note("c", "gamma standalone", [], body="No links here."))
            _run(home, project)
            orphans = self._section(memdir, "Orphan pages")
            self.assertIn("c.md", orphans)

    def test_no_orphans_in_a_linkless_corpus(self):
        """A corpus with NO links at all surfaces NO orphans (every note would trivially be one)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            # Two notes, NO [[links]], distinct topics → no link graph → no orphan
            # noise, and (distinct topics) no clusters → whole detector silent.
            (memdir / "iso_one.md").write_text(
                _note("iso_one", "widget pipeline alpha", []))
            (memdir / "iso_two.md").write_text(
                _note("iso_two", "keychain rotator bravo", []))
            out = _run(home, project)
            self.assertEqual(out.strip(), "")
            self.assertFalse((memdir / PROPOSAL_NAME).exists())

    def test_index_line_to_deleted_note_no_longer_surfaced(self):
        """Issue #55: the MEMORY.md↔disk sync check is RETIRED. A stale index
        line pointing at a deleted note is NO LONGER a sync mismatch (MEMORY.md
        is the deprecated memgrep stub, never an authoritative index)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "present.md").write_text(
                _note("present", "a present topic", []))
            (memdir / "MEMORY.md").write_text(
                "# Memory index\n"
                "- [Present](present.md) — present hook.\n"
                "- [Gone](deleted_note.md) — points at a deleted file.\n"
            )
            _run(home, project)
            sync = self._section(memdir, "MEMORY.md sync")
            self.assertNotIn("deleted_note.md", sync)
            self.assertNotIn("missing on disk", sync)

    def test_note_missing_from_index_no_longer_surfaced(self):
        """Issue #55: a note on disk that MEMORY.md does not list is NO LONGER a
        sync mismatch — pointers were intentionally retired in favor of memgrep,
        so 'missing from MEMORY.md' is never a finding."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "listed.md").write_text(_note("listed", "listed topic", []))
            (memdir / "unlisted.md").write_text(_note("unlisted", "unlisted topic", []))
            (memdir / "MEMORY.md").write_text(
                "# Memory index\n- [Listed](listed.md) — only this one is indexed.\n"
            )
            _run(home, project)
            sync = self._section(memdir, "MEMORY.md sync")
            self.assertNotIn("unlisted.md", sync)
            self.assertNotIn("missing from MEMORY.md", sync)

    def test_memory_md_in_sync_is_silent_on_sync(self):
        """A MEMORY.md that lists exactly the notes on disk surfaces no sync mismatch."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "one.md").write_text(_note("one", "first topic alpha", []))
            (memdir / "two.md").write_text(_note("two", "second topic bravo", []))
            (memdir / "MEMORY.md").write_text(
                "# Memory index\n"
                "- [One](one.md) — first.\n"
                "- [Two](two.md) — second.\n"
            )
            _run(home, project)
            sync = self._section(memdir, "MEMORY.md sync")
            # Section may be absent (no proposal) or present-but-(none); either way
            # neither note basename appears as a mismatch.
            self.assertNotIn("one.md", sync.replace("(none)", ""))
            self.assertNotIn("two.md", sync.replace("(none)", ""))

    def test_memory_md_excluded_from_notes_disk_set(self):
        """MEMORY.md itself is never counted as a 'note missing from the index'."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "solo.md").write_text(_note("solo", "solo topic", []))
            (memdir / "MEMORY.md").write_text(
                "# Memory index\n- [Solo](solo.md) — the one note.\n"
            )
            _run(home, project)
            sync = self._section(memdir, "MEMORY.md sync")
            self.assertNotIn("MEMORY.md", sync)


@unittest.skipUnless(_HAVE_MEMGREP, "memgrep binary not installed")
class TestMemoryLibrarianNoMutation(unittest.TestCase):
    """The load-bearing safety guarantee: ZERO mutation of the memory corpus."""

    def test_corpus_byte_identical_before_and_after_run(self):
        """Every memory NOTE is byte-identical before and after a librarian run.

        This is the load-bearing safety test (RULE 0): the detector SURFACES,
        it never moves/merges/edits/deletes a note. We fingerprint the whole
        note set, run the detector (which DOES find candidates here), and
        assert every note's hash is unchanged. Only the proposal file — which
        is not a note — may appear.
        """
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "oauth-keychain.md").write_text(
                _note("oauth-keychain", "rotator creds", ["oauth", "rotator"]))
            (memdir / "oauth-rotator.md").write_text(
                _note("oauth-rotator", "rotator layers", ["oauth", "rotator"]))
            (memdir / "retry-a.md").write_text(
                _note("retry-a", "retry cap", ["retry"], body="retries 3x."))
            (memdir / "retry-b.md").write_text(
                _note("retry-b", "retry cap", ["retry"], body="retries 5x."))
            before = _corpus_fingerprint(memdir)
            note_files_before = set(before)
            self.assertTrue(note_files_before, "fixture must have notes")

            out = _run(home, project)
            self.assertIn("[memory-librarian]", out)  # candidates WERE found

            after = _corpus_fingerprint(memdir)
            # No note added, removed, moved, or modified.
            self.assertEqual(
                before, after,
                "memory-librarian mutated the corpus — it must only surface, never mutate")
            # The only NEW file in the dir is the proposal (not a note).
            new_files = {p.name for p in memdir.iterdir()} - {
                Path(k).name for k in note_files_before}
            self.assertTrue(new_files <= {PROPOSAL_NAME, "memory-index.md", ".memgrep"})

    def test_no_note_deleted_even_when_clustered(self):
        """A cluster never causes a member note to be removed (no auto-merge)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            for i in range(4):
                (memdir / f"dup{i}.md").write_text(
                    _note(f"dup{i}", f"same topic variant {i}", ["dupe"]))
            before = {p.name for p in memdir.glob("dup*.md")}
            _run(home, project)
            after = {p.name for p in memdir.glob("dup*.md")}
            self.assertEqual(before, after, "no clustered note may be deleted")


class TestMemoryLibrarianGracefulNoOp(unittest.TestCase):
    """No-op safety: absent dir / absent binary / unchanged corpus → silent."""

    def test_absent_memory_dir_is_silent(self):
        """A project with no memory dir emits nothing and never crashes."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            # Deliberately do NOT create the memory dir.
            out = _run(home, project)
            self.assertEqual(out.strip(), "")

    def test_empty_memory_dir_is_silent(self):
        """An empty memory dir (dir exists, no notes) emits nothing."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            _build(home, project)  # creates empty memdir
            out = _run(home, project)
            self.assertEqual(out.strip(), "")
            self.assertFalse((Path(_build(home, project)) / PROPOSAL_NAME).exists())

    def test_memgrep_absent_is_silent_no_op(self):
        """When memgrep cannot be resolved, the detector is a silent no-op.

        Points MEMGREP_BIN at a path that does not exist and clears PATH so the
        detector's own resolution also fails — it must not crash, must emit
        nothing, and must not write a proposal even when same-topic notes exist.
        """
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "x.md").write_text(_note("x", "topic", ["t"]))
            (memdir / "y.md").write_text(_note("y", "topic", ["t"]))
            env = dict(os.environ)
            env["HOME"] = str(home)
            env["CLAUDE_PROJECT_DIR"] = str(project)
            env["CLAUDE_SESSION_ID"] = "nomemgrep"
            env["MEMGREP_BIN"] = str(home / "definitely-not-memgrep")
            env["PATH"] = ""  # break which() resolution too
            env.pop("CLAUDE_PLUGIN_OPTION_MEMORY_LIBRARIAN_INTERVAL", None)
            res = subprocess.run(
                [sys.executable, str(DETECTOR)],
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(res.stdout.strip(), "")
            self.assertFalse((memdir / PROPOSAL_NAME).exists())


@unittest.skipUnless(_HAVE_MEMGREP, "memgrep binary not installed")
class TestMemoryLibrarianDedupe(unittest.TestCase):
    """Seen-file dedupe: the same candidate set is announced at most once."""

    def test_unchanged_corpus_is_silent_on_second_run(self):
        """Identical candidate set on a second run emits nothing (dedupe silence)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "a.md").write_text(_note("a", "shared topic", ["topic"]))
            (memdir / "b.md").write_text(_note("b", "shared topic", ["topic"]))
            first = _run(home, project)
            second = _run(home, project)
            self.assertIn("[memory-librarian]", first)
            self.assertEqual(second.strip(), "", "unchanged candidate set must be silent")

    def test_new_candidate_set_re_emits(self):
        """Adding a new same-topic cluster produces a fresh finding."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "a.md").write_text(_note("a", "topic one", ["one"]))
            (memdir / "b.md").write_text(_note("b", "topic one", ["one"]))
            first = _run(home, project)
            self.assertIn("[memory-librarian]", first)
            # Add a second, distinct cluster → candidate set changes → re-emit.
            (memdir / "c.md").write_text(_note("c", "topic two", ["two"]))
            (memdir / "d.md").write_text(_note("d", "topic two", ["two"]))
            second = _run(home, project)
            self.assertIn("[memory-librarian]", second)


class TestMemoryLibrarianReindex(unittest.TestCase):
    """Scheduled reindex (rank 8): the librarian refreshes the SQLite index per root.

    Uses a SPY memgrep (a tiny script that logs every invocation's argv and
    returns empty stdout) so the test can assert `reindex <root>` was invoked
    per scope root — without depending on the real binary's index internals.
    """

    def _spy_memgrep(self, home: Path, *, reindex_exit: int = 0) -> tuple[Path, Path]:
        """Write a spy memgrep that logs argv to a file; return (binary, logfile).

        `reindex_exit` lets a test make ONLY the `reindex` subcommand fail (every
        other subcommand still exits 0 with empty stdout) to prove failure is
        tolerated.
        """
        log = home / "memgrep-calls.log"
        binary = home / "spy-memgrep"
        binary.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >> {log}\n'
            f'if [ "$1" = "reindex" ]; then exit {reindex_exit}; fi\n'
            "exit 0\n"
        )
        binary.chmod(0o755)
        return binary, log

    def _run_with_spy(self, home: Path, project: Path, binary: Path) -> str:
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["CLAUDE_PROJECT_DIR"] = str(project)
        env["CLAUDE_SESSION_ID"] = "reindexsess"
        env["MEMGREP_BIN"] = str(binary)
        env.pop("CLAUDE_PLUGIN_OPTION_MEMORY_LIBRARIAN_INTERVAL", None)
        res = subprocess.run(
            [sys.executable, str(DETECTOR)],
            capture_output=True, text=True, env=env, timeout=60, check=False,
        )
        if res.returncode != 0:
            raise AssertionError(f"detector exited {res.returncode}; stderr:\n{res.stderr}")
        return res.stdout

    def test_reindex_invoked_for_the_local_root(self):
        """`memgrep reindex <local-root>` is invoked when the LOCAL scope has notes."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "n.md").write_text(_note("n", "a topic", []))
            binary, log = self._spy_memgrep(home)
            self._run_with_spy(home, project, binary)
            self.assertTrue(log.exists(), "spy memgrep was never invoked")
            calls = log.read_text()
            # The reindex line must name the LOCAL memory root.
            self.assertRegex(calls, rf"(?m)^reindex .*{re.escape(str(memdir))}\s*$")

    def test_reindex_runs_before_index_query(self):
        """reindex is invoked BEFORE the `index --markdown` query (freshness-first)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "n.md").write_text(_note("n", "a topic", []))
            binary, log = self._spy_memgrep(home)
            self._run_with_spy(home, project, binary)
            lines = log.read_text().splitlines()
            reindex_idx = next((i for i, ln in enumerate(lines) if ln.startswith("reindex ")), None)
            index_idx = next((i for i, ln in enumerate(lines) if ln.startswith("index ")), None)
            self.assertIsNotNone(reindex_idx, "reindex was never invoked")
            assert reindex_idx is not None  # narrow int|None for the type-checker
            if index_idx is not None:
                self.assertLess(reindex_idx, index_idx, "reindex must precede the index query")

    def test_reindex_failure_is_tolerated(self):
        """A failing `reindex` does not crash the detector (it falls back to the walk)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "n.md").write_text(_note("n", "a topic", []))
            binary, log = self._spy_memgrep(home, reindex_exit=3)
            # Must NOT raise (the _run_with_spy helper asserts exit 0).
            self._run_with_spy(home, project, binary)
            # reindex was still attempted (proving the failure path was exercised).
            self.assertRegex(log.read_text(), r"(?m)^reindex ")

    def test_no_reindex_when_no_notes(self):
        """An empty scope root is not reindexed (no point indexing nothing)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            _build(home, project)  # empty memdir, no notes
            binary, log = self._spy_memgrep(home)
            self._run_with_spy(home, project, binary)
            # The spy is never invoked at all (the detector no-ops on an empty root).
            self.assertFalse(log.exists(), "reindex must not run on an empty scope")


@unittest.skipUnless(_HAVE_MEMGREP, "memgrep binary not installed")
class TestMemoryLibrarianDetectorOutputExclusion(unittest.TestCase):
    """Issue #54: a SIBLING detector's `*-proposed.md` output dropped into the
    memory dir must NOT be scanned as a memory note (page-shape / sync / cluster).

    The librarian's own `memory-reorg-proposed.md` was already excluded by exact
    name; the bug was that another detector's output (`memory-scope-leak-proposed.md`,
    and the whole `*-proposed.md` family) still tripped the note scan.
    """

    def test_sibling_proposed_md_not_flagged_page_shape(self):
        """`memory-scope-leak-proposed.md` (a plain report, no frontmatter) must
        not surface as a malformed note."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            # The exact file the issue reports: another detector's output — a
            # frontmatter-less markdown report written INTO the memory dir.
            (memdir / "memory-scope-leak-proposed.md").write_text(
                "# Memory scope leak — PROPOSED\n\nSome report prose, not a note.\n")
            # One real, shape-clean note so the scope is non-empty.
            (memdir / "real_note.md").write_text(
                _note("real_note", "a genuine memory note", []))
            out = _run(home, project)
            # The proposed-file basename must appear in NO output and NO proposal.
            self.assertNotIn("memory-scope-leak-proposed.md", out)
            if (memdir / PROPOSAL_NAME).exists():
                proposal = (memdir / PROPOSAL_NAME).read_text()
                self.assertNotIn("memory-scope-leak-proposed.md", proposal)

    def test_arbitrary_proposed_md_excluded_by_pattern(self):
        """ANY `*-proposed.md` (not just the two known names) is excluded — the
        fix generalizes to the whole detector-output family (issue #54)."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            # A future/unknown detector output name — still a `*-proposed.md`.
            (memdir / "some-future-detector-proposed.md").write_text(
                "no frontmatter here, just a report body\n")
            (memdir / "real_note.md").write_text(
                _note("real_note", "a genuine memory note", []))
            out = _run(home, project)
            self.assertNotIn("some-future-detector-proposed.md", out)
            if (memdir / PROPOSAL_NAME).exists():
                proposal = (memdir / PROPOSAL_NAME).read_text()
                self.assertNotIn("some-future-detector-proposed.md", proposal)


@unittest.skipUnless(_HAVE_MEMGREP, "memgrep binary not installed")
class TestMemoryLibrarianMemoryMdSyncRetired(unittest.TestCase):
    """Issue #55: the MEMORY.md-sync check is retired — MEMORY.md is the
    DEPRECATED memgrep stub, not an index, so notes are never 'missing' from it
    (recall is 100% memgrep). The check must surface NOTHING for any scope.
    """

    def test_notes_not_flagged_missing_from_memory_md(self):
        """Notes on disk are never reported 'missing from MEMORY.md'."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            # The canonical deprecation stub — pointers intentionally retired.
            (memdir / "MEMORY.md").write_text(
                "# MEMORY — index retired (managed by memgrep)\n"
                "⚠ DEPRECATED stub — do NOT add pointers here.\n")
            (memdir / "one.md").write_text(_note("one", "first topic alpha", []))
            (memdir / "two.md").write_text(_note("two", "second topic bravo", []))
            out = _run(home, project)
            self.assertNotIn("missing from MEMORY.md", out)
            if (memdir / PROPOSAL_NAME).exists():
                proposal = (memdir / PROPOSAL_NAME).read_text()
                self.assertNotIn("missing from MEMORY.md", proposal)

    def test_stale_index_line_no_longer_flagged(self):
        """An old-style index line pointing at a deleted note is no longer a
        sync finding either — the whole MEMORY.md↔disk diff is retired."""
        with TemporaryDirectory() as h, TemporaryDirectory() as p:
            home, project = Path(h), Path(p)
            memdir = _build(home, project)
            (memdir / "present.md").write_text(_note("present", "a present topic", []))
            (memdir / "MEMORY.md").write_text(
                "# Memory index\n"
                "- [Gone](deleted_note.md) — points at a deleted file.\n")
            out = _run(home, project)
            self.assertNotIn("missing on disk", out)
            if (memdir / PROPOSAL_NAME).exists():
                proposal = (memdir / PROPOSAL_NAME).read_text()
                self.assertNotIn("deleted_note.md", proposal)


class TestMemoryLibrarianRegistration(unittest.TestCase):
    """dispatch.py must register the detector with a low (≥6h) cadence."""

    def test_registered_in_dispatch_roster(self):
        """memory-librarian appears in the dispatch detector roster, project-scoped, low cadence."""
        dispatch = (Path(__file__).resolve().parent.parent / "scripts" / "dispatch.py").read_text()
        self.assertIn('"memory-librarian"', dispatch)
        self.assertIn("CLAUDE_PLUGIN_OPTION_MEMORY_LIBRARIAN_INTERVAL", dispatch)

    def test_default_cadence_is_low(self):
        """The registered default cadence is at least 6h (slow/background detector)."""
        import ast as _ast
        dispatch_path = Path(__file__).resolve().parent.parent / "scripts" / "dispatch.py"
        tree = _ast.parse(dispatch_path.read_text())
        found_interval = None
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Tuple) or len(node.elts) != 3:
                continue
            name_node = node.elts[0]
            if isinstance(name_node, _ast.Constant) and name_node.value == "memory-librarian":
                cad = node.elts[1]
                if isinstance(cad, _ast.Constant) and isinstance(cad.value, int):
                    found_interval = cad.value
        self.assertIsNotNone(found_interval, "memory-librarian not found in roster tuple")
        assert found_interval is not None  # narrow int|None for the type-checker
        self.assertGreaterEqual(found_interval, 21600, "background librarian must run no more often than 6h")


if __name__ == "__main__":
    unittest.main()
