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
    """Mirror user_mem_lib._project_slug: absolute path, separators dashed."""
    p = project_dir.replace(os.sep, "-")
    if os.altsep:
        p = p.replace(os.altsep, "-")
    return p


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
        self.assertGreaterEqual(found_interval, 21600, "background librarian must run no more often than 6h")


if __name__ == "__main__":
    unittest.main()
