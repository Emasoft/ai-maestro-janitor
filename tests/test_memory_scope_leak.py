"""Tests for the memory-scope-leak detector (TRDD-c77dae09, ranks 2+6).

The PROJECT memory scope (`<git-root>/.claude/project/memory/`) is git-tracked
and PUSHED, so it MUST NOT carry machine/user-private material. This detector
scans those pages with the private-path lib + privacy PII shapes + credential
libs + entropy and surfaces `[memory-scope-leak] <file>: <class> — demote to
LOCAL scope` findings. It also guards the gitignore invariants: PROJECT
`.claude/project/memory/` must be TRACKED (and since it lives under the commonly
ignored `.claude/`, a missing `!.claude/project/memory/**` exception is flagged),
and a LOCAL-shaped store must not be committed into the repo.

Real I/O, no mocks: each case builds a tmp git repo with a
`.claude/project/memory/` dir and runs the detector as a subprocess with
CLAUDE_PROJECT_DIR + HOME pointed at the fixture. The detector is project-scoped
and a graceful no-op when there is no PROJECT memory dir, no git repo, or an
unchanged finding set.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _fake_secrets import b62 as fake_b62  # noqa: E402  (runtime-generated fixtures — see that module's docstring)
from _fake_secrets import secret as fake_secret  # noqa: E402

DETECTOR = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "detectors" / "memory-scope-leak.py"
)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "t")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "t")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@example.com")
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env, check=False,
    )


def _init_repo(root: Path) -> None:
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "t"], root)


def _run(home: Path, project: Path, *, extra_env: dict | None = None) -> str:
    """Run the detector with HOME + CLAUDE_PROJECT_DIR pointed at the fixture.
    Returns stdout; raises if the detector exits non-zero (heartbeat must be
    crash-free)."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_SESSION_ID"] = "testsess"
    # Force scanning even though the fixture isn't the janitor's own repo; and
    # make the per-run cadence irrelevant (the detector self-checks last-run).
    env["CLAUDE_PLUGIN_ALLOW_SELF_SCAN"] = "1"
    env.pop("CLAUDE_PLUGIN_OPTION_MEMORY_SCOPE_LEAK_INTERVAL", None)
    if extra_env:
        env.update(extra_env)
    res = subprocess.run(
        [sys.executable, str(DETECTOR)],
        capture_output=True, text=True, env=env, timeout=60, check=False,
    )
    if res.returncode != 0:
        raise AssertionError(f"detector exited {res.returncode}; stderr:\n{res.stderr}")
    return res.stdout


def _project_memdir(root: Path) -> Path:
    """The PROJECT-scope memory dir (in-repo, namespaced under .claude/)."""
    return root / ".claude" / "project" / "memory"


def _write_project_memory(root: Path, name: str, content: str) -> Path:
    mem = _project_memdir(root)
    mem.mkdir(parents=True, exist_ok=True)
    page = mem / name
    page.write_text(content, encoding="utf-8")
    return page


def _proposal(root: Path) -> str:
    """The detector's proposal file content (the per-page leak detail lives here;
    the heartbeat line is intentionally terse, like the librarian's)."""
    p = _project_memdir(root) / "memory-scope-leak-proposed.md"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


class TestMemoryScopeLeak(unittest.TestCase):
    # ----- graceful no-ops -----------------------------------------------

    def test_no_git_repo_is_noop(self) -> None:
        """Not a git repo → silent no-op (project-scoped, needs a repo)."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _write_project_memory(root, "a.md", "clean project fact.\n")
            out = _run(Path(td) / "home", root)
            self.assertEqual(out.strip(), "")

    def test_absent_memory_dir_is_noop(self) -> None:
        """A git repo with NO `memory/` dir → silent no-op."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            out = _run(Path(td) / "home", root)
            self.assertEqual(out.strip(), "")

    def test_clean_pages_yield_nothing(self) -> None:
        """A tracked PROJECT memory dir with only portable, non-private content → no leak."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "arch.md",
                "The parser retries 3× then fails. See [[other]] for the table.\n",
            )
            _git(["add", ".claude/project/memory/arch.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)

    # ----- leak classes ---------------------------------------------------

    def test_local_path_leak_flagged(self) -> None:
        """A /Users/<name>/ absolute home path in a pushed page is a leak."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "paths.md",
                "the script lives at /Users/emanuele/Code/run.sh on my box.\n",
            )
            _git(["add", ".claude/project/memory/paths.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            self.assertIn("demote to LOCAL", out)
            # The per-page detail (filename + class) lives in the proposal file.
            prop = _proposal(root)
            self.assertIn("paths.md", prop)
            self.assertIn("local-path", prop)

    def test_email_pii_leak_flagged(self) -> None:
        """An email address (PII via privacy_patterns) in a pushed page is a leak."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "contact.md",
                "ping the maintainer at someone.private@gmail.com when stuck.\n",
            )
            _git(["add", ".claude/project/memory/contact.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            prop = _proposal(root)
            self.assertIn("contact.md", prop)
            self.assertIn("pii:email", prop)

    def test_high_entropy_secret_leak_flagged(self) -> None:
        """A long high-entropy base64-ish blob (an unrecognised secret) is a leak."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            secret = "Zk9hQm*c2VjUmV0X3Rva2VuX3hQ8wLm5vdF9hX3JlYWxfb25lX2J1dF9yYW5kb20"
            _write_project_memory(
                root, "token.md",
                f"the api key was {secret} but it has been rotated since.\n",
            )
            _git(["add", ".claude/project/memory/token.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            prop = _proposal(root)
            self.assertIn("token.md", prop)
            self.assertIn("high-entropy secret", prop)

    def test_a_backticked_report_path_does_not_trip_the_entropy_scan(self) -> None:
        """ai-maestro-plugins#14, with the trigger MEASURED rather than described: the strings
        that actually tripped the entropy gate on a real corpus were timestamped report paths —
        `reports/<component>/20260721_100514+0200-<slug>` is base64-alphabet (the `+0200` offset
        even contributes a `+`), 60+ chars, mixed-class, entropy above the 4.5 gate. Citing a
        report path in backticks is a documentation convention every page of that corpus follows;
        a page must be able to cite its evidence without being flagged as leaking a secret."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "burn-doctrine.md",
                "Windows are metered by COST, not raw tokens. Evidence:\n"
                "`reports/burn-investigation/20260721_100514+0200-3-account-exhaustion-culprit.md`.\n"
                "The follow-up measurement lives at\n"
                "`reports/cumulative-delta-audit/20260805_043236+0200-differencing-sites.md`.\n",
            )
            _git(["add", ".claude/project/memory/burn-doctrine.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)
            self.assertNotIn("high-entropy secret", _proposal(root))

    def test_a_real_token_inside_a_code_fence_is_still_caught(self) -> None:
        """The counter-case that keeps the #14 fix honest. A code fence (a command example) is
        the single most common place a real token gets pasted, and the entropy pass is this
        detector's ONLY pasted-token catcher (the cloud/CI-CD libs carry zero token-shape
        rules — verified by probing them, which is what killed the first draft of this fix).
        So code regions are shape-GATED, not blanked: a known vendor prefix still convicts."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            # Runtime-generated per tests/_fake_secrets.py — a literal here, even a fake one,
            # trips the repo's own fixture-hygiene gate AND external secret scanners.
            tok = fake_secret("ghp_", "scope-leak-fence", 36)
            _write_project_memory(
                root, "deploy-notes.md",
                "run it like this:\n"
                "```bash\n"
                f"gh auth login --with-token <<< {tok}\n"
                "```\n",
            )
            _git(["add", ".claude/project/memory/deploy-notes.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            self.assertIn("high-entropy secret", _proposal(root))

    def test_an_unprefixed_generic_secret_in_a_code_fence_is_still_caught(self) -> None:
        """PR-204 review P1, verified real before fixing: prefixes-only shape gating left a
        credential from any UNLISTED vendor invisible inside code regions — the one place tokens
        get pasted. The generic conviction path (all 3 character classes + no ≥6-digit run, on a
        token already over the entropy gate) catches it; the generated fixture token measures
        entropy 4.83 with 3 classes and no digit run (deterministic — sha256-derived b62)."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            # Runtime-generated (tests/_fake_secrets.py): no vendor prefix, which is the point.
            tok = fake_b62("scope-leak-generic-vendor", 48)
            _write_project_memory(
                root, "vendor-notes.md",
                "the obscure vendor's CLI wants:\n"
                "```bash\n"
                f"obscurectl login --token {tok}\n"
                "```\n",
            )
            _git(["add", ".claude/project/memory/vendor-notes.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            self.assertIn("high-entropy secret", _proposal(root))

    def test_a_backticked_trdd_citation_is_not_a_generic_secret(self) -> None:
        """The measured near-miss that killed the naive mixed-case gate: a TRDD file citation
        (`TRDD-20260805_130129+0200-9COGK66W-…`) measures entropy 4.51 with all 3 character
        classes — over BOTH bars — and memory pages cite TRDDs constantly. Its ≥6-digit
        timestamp run is what separates it from a random secret, so the digit-run exclusion is
        the load-bearing part of the generic shape."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "task-notes.md",
                "The decision is recorded in\n"
                "`design/tasks/TRDD-20260805_130129+0200-9COGK66W-a-package-manager-safety-knob.md`\n"
                "and the follow-up in `TRDD-20260714_043000+0200-K3WDPR7M-ssd-write-amplification.md`.\n",
            )
            _git(["add", ".claude/project/memory/task-notes.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)
            self.assertNotIn("high-entropy secret", _proposal(root))

    def test_allowlist_no_false_positive(self) -> None:
        """Generic/shared paths + documentation hosts must NOT be flagged as leaks."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "ok.md",
                "CI runs in /home/runner/work; cache under /Users/Shared/x; "
                "docs at example.com and localhost; bare ~/bin is fine.\n",
            )
            _git(["add", ".claude/project/memory/ok.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)

    def test_memgrep_dir_skipped(self) -> None:
        """The tool's `.memgrep/` index sidecar inside the PROJECT memory dir is never scanned."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            mem = _project_memdir(root)
            mem.mkdir(parents=True)
            (mem / "arch.md").write_text("clean fact.\n", encoding="utf-8")
            idx = mem / ".memgrep"
            idx.mkdir()
            # A would-be leak INSIDE the index dir must be ignored (not a note).
            (idx / "cache.md").write_text(
                "/Users/secretuser/leak/path/here.sh\n", encoding="utf-8",
            )
            _git(["add", ".claude/project/memory/arch.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)

    # ----- issue #176: documentation is not a leak -------------------------

    def test_email_inside_code_span_not_flagged(self) -> None:
        """An address FORMAT quoted inside backticks (documenting a spec, not
        naming a real mailbox) must not be flagged — issue #176's `pii:email`
        false positives were all inside a code span or a fence."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "amp-format.md",
                "The AMP addressing spec uses forms like `alice@myteam.local` "
                "and `bob@acme.crabmail.ai` as placeholder examples.\n",
            )
            _git(["add", ".claude/project/memory/amp-format.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)

    def test_fenced_format_placeholder_not_flagged(self) -> None:
        """A FORMAT placeholder like `agentId@hostId`, quoted to explain why `@`
        and `.` are in a session-name charset, must not be misread as a real
        `user@host` ssh target just because it sits in a fenced example."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "tmux-charset.md",
                "Session names allow `@` and `.` for shapes like:\n\n"
                "```\nagentId@hostId\n```\n",
            )
            _git(["add", ".claude/project/memory/tmux-charset.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)

    def test_filename_substring_in_code_span_not_flagged(self) -> None:
        """A filename like `settings.local.json` referenced in backticks must not
        be misread as a `.local` LAN hostname."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "config-doc.md",
                "Per-machine overrides live in `settings.local.json`, never committed.\n",
            )
            _git(["add", ".claude/project/memory/config-doc.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)

    def test_reserved_tld_email_not_flagged_outside_code_span(self) -> None:
        """A `.test`/`.example`/`.invalid` address (RFC 2606 reserved for
        documentation) is never a real mailbox — flagged as `pii:email` even in
        PLAIN PROSE (no backticks) before the fix; must not be flagged after.
        (`.local` is deliberately excluded from this case: `private_path_patterns`
        treats it as a real mDNS/LAN suffix for its OWN `machine-host` shape, so an
        address on `.local` is still caught by that unrelated, correct rule — the
        masking test above already covers the `.local` documentation-example case.)"""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "addressing.md",
                "The default placeholder account is alice@default.test in every "
                "example throughout this document.\n",
            )
            _git(["add", ".claude/project/memory/addressing.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)

    def test_real_email_outside_code_span_still_flagged(self) -> None:
        """The masking + reserved-TLD fixes must not blind the detector to a REAL
        leak sitting in plain prose on a public-looking TLD (regression guard)."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "contact2.md",
                "reach the maintainer at someone.private@gmail.com if this breaks.\n",
            )
            _git(["add", ".claude/project/memory/contact2.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            self.assertIn("pii:email", _proposal(root))

    # ----- gitignore guards ----------------------------------------------

    def test_ignored_project_memory_flagged(self) -> None:
        """PROJECT `.claude/project/memory/` must be TRACKED. Because it lives under
        `.claude/` (commonly gitignored), a bare `.claude/` rule with no
        re-include exception swallows it — surface a guard finding (the shared
        scope would silently never be pushed)."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            # `.claude/` ignored, NO `!.claude/project/memory/**` exception → the
            # PROJECT scope is swallowed. This is the exact real-world misconfig.
            (root / ".gitignore").write_text(".claude/\n", encoding="utf-8")
            _write_project_memory(root, "arch.md", "clean fact.\n")
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            self.assertIn("gitignore guard", out.lower())
            # The guard detail (the word "gitignored" + the exception fix) is in
            # the proposal.
            prop = _proposal(root).lower()
            self.assertIn("gitignored", prop)
            self.assertIn("!.claude/project/memory/**", prop)

    def test_local_shaped_tracked_store_flagged(self) -> None:
        """F18: a TRACKED `projects/<x>/memory/` tree inside the repo (the
        harness LOCAL corpus committed by mistake) is a guard finding."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(root, "arch.md", "clean fact.\n")
            leaked = root / "projects" / "some-slug" / "memory"
            leaked.mkdir(parents=True)
            (leaked / "note.md").write_text("a local note\n", encoding="utf-8")
            _git(["add", ".claude/project/memory/arch.md",
                  "projects/some-slug/memory/note.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            prop = _proposal(root)
            self.assertIn("LOCAL-shaped memory store", prop)
            self.assertIn("projects/some-slug/memory", prop)

    def test_local_shaped_untracked_store_not_flagged(self) -> None:
        """F18: an UNTRACKED `projects/<x>/memory/` tree (a vendored monorepo
        shape) cannot leak via push — no guard, no false positive. Pre-fix the
        unbounded rglob flagged it (and walked the whole tree every fire)."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(root, "arch.md", "clean fact.\n")
            _git(["add", ".claude/project/memory/arch.md"], root)
            _git(["commit", "-qm", "x"], root)
            vendored = root / "vendor" / "projects" / "x" / "memory"
            vendored.mkdir(parents=True)
            (vendored / "note.md").write_text("vendored note\n", encoding="utf-8")
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)

    def test_stale_proposal_cleared_on_clean_scan(self) -> None:
        """F19: once the leak is fixed, the next run REMOVES the stale proposal
        (its own footer promises 'Re-run clears this') and resets the dedupe
        horizon so an identical leak recurring later re-emits."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            page = _write_project_memory(
                root, "paths.md", "see /Users/emanuele/x.sh on disk.\n",
            )
            _git(["add", ".claude/project/memory/paths.md"], root)
            _git(["commit", "-qm", "x"], root)
            home = Path(td) / "home"
            first = _run(home, root)
            self.assertIn("[memory-scope-leak]", first)
            self.assertTrue(_proposal(root))
            # The leak is fixed: the page becomes portable.
            page.write_text("the script lives in the repo's tools/ dir.\n", encoding="utf-8")
            _git(["add", ".claude/project/memory/paths.md"], root)
            _git(["commit", "-qm", "fix"], root)
            clean = _run(home, root, extra_env={"CLAUDE_PLUGIN_OPTION_MEMORY_SCOPE_LEAK_INTERVAL": "0"})
            self.assertEqual(clean.strip(), "")
            self.assertEqual(_proposal(root), "", "stale proposal must be removed on a clean scan")
            # The SAME leak recurring later must re-emit (dedupe horizon reset).
            page.write_text("see /Users/emanuele/x.sh on disk.\n", encoding="utf-8")
            _git(["add", ".claude/project/memory/paths.md"], root)
            _git(["commit", "-qm", "regress"], root)
            again = _run(home, root, extra_env={"CLAUDE_PLUGIN_OPTION_MEMORY_SCOPE_LEAK_INTERVAL": "0"})
            self.assertIn("[memory-scope-leak]", again)

    # ----- publish-globally awareness (issue #52, TRDD-4GQ94FNJ) -----------

    def test_published_clean_page_not_flagged(self) -> None:
        """A `publish-globally: true` page with NO private data is NOT flagged — publishing
        is an intentional, approved act and a clean published note must not be nagged."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "arch.md",
                "---\n"
                "name: arch\n"
                'description: "the deploy architecture"\n'
                "publish-globally: true\n"
                "metadata:\n"
                "  type: project\n"
                "  tier: hub\n"
                "---\n"
                "The parser retries 3x then fails. Portable, no private data.\n",
            )
            _git(["add", ".claude/project/memory/arch.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)

    def test_publish_false_clean_page_not_flagged(self) -> None:
        """`publish-globally: false` is a valid bare boolean meaning 'not published' — a
        clean such page is no finding."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "arch.md",
                "---\n"
                "name: arch\n"
                "publish-globally: false\n"
                "metadata:\n"
                "  type: project\n"
                "---\n"
                "Portable fact: the queue retries 3x then fails.\n",
            )
            _git(["add", ".claude/project/memory/arch.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertNotIn("[memory-scope-leak]", out)

    def test_published_page_leak_is_escalated(self) -> None:
        """A `publish-globally: true` page WITH a content leak is flagged AND the proposal
        ESCALATES it — a published note is symlinked into the USER root and recalled in
        every project, so the stock 'demote to LOCAL' remedy retracts nothing."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "deploy.md",
                "---\n"
                "name: deploy\n"
                "publish-globally: true\n"
                "metadata:\n"
                "  type: project\n"
                "---\n"
                "the runner lives at /Users/emanuele/Code/run.sh on my box.\n",
            )
            _git(["add", ".claude/project/memory/deploy.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            prop = _proposal(root)
            self.assertIn("deploy.md", prop)
            self.assertIn("local-path", prop)
            self.assertIn("PUBLISHED", prop)
            self.assertIn("publish-globally", prop)
            # The escalation REPLACES the stock advice for this page — it does not merely
            # sit beside it, or a reader skimming the line still under-reacts.
            leak_line = next(ln for ln in prop.splitlines() if "deploy.md" in ln)
            self.assertNotIn("demote to LOCAL scope", leak_line)
            # `published` is presentation, not a leak class — it must not pollute the list.
            self.assertNotIn("— published,", leak_line)

    def test_published_identity_key_flagged(self) -> None:
        """The privacy invariant: ONLY the bare `publish-globally: true` may be committed.
        A forbidden identity KEY (here `published-slug`) beside the flag is a
        `published-identity-leak` even when the body is otherwise clean."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "shared.md",
                "---\n"
                "name: shared\n"
                "publish-globally: true\n"
                "published-slug: my-secret-project\n"
                "metadata:\n"
                "  type: project\n"
                "---\n"
                "Portable fact: the queue retries 3x then fails.\n",
            )
            _git(["add", ".claude/project/memory/shared.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            prop = _proposal(root)
            self.assertIn("shared.md", prop)
            self.assertIn("published-identity-leak", prop)

    def test_published_nonboolean_value_flagged(self) -> None:
        """A `publish-globally` VALUE that carries data (a slug) instead of a bare boolean
        is itself an identity leak — the field says WHETHER, never WHAT."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "shared.md",
                "---\n"
                "name: shared\n"
                "publish-globally: my-secret-project\n"
                "metadata:\n"
                "  type: project\n"
                "---\n"
                "Portable fact: the queue retries 3x then fails.\n",
            )
            _git(["add", ".claude/project/memory/shared.md"], root)
            _git(["commit", "-qm", "x"], root)
            out = _run(Path(td) / "home", root)
            self.assertIn("[memory-scope-leak]", out)
            prop = _proposal(root)
            self.assertIn("published-identity-leak", prop)
            # A non-boolean value is NOT "published" — the flag never parsed, so the page
            # is not symlinked anywhere and the escalation must not fire.
            self.assertNotIn("PUBLISHED", prop)

    # ----- dedupe ---------------------------------------------------------

    def test_unchanged_findings_are_silent_on_rerun(self) -> None:
        """A second run over an unchanged corpus emits nothing (fingerprint
        dedupe — idempotent like the other detectors)."""
        with TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            _init_repo(root)
            _write_project_memory(
                root, "paths.md", "see /Users/emanuele/x.sh on disk.\n",
            )
            _git(["add", ".claude/project/memory/paths.md"], root)
            _git(["commit", "-qm", "x"], root)
            home = Path(td) / "home"
            first = _run(home, root)
            self.assertIn("[memory-scope-leak]", first)
            # last-run gating would suppress the 2nd run; bypass it by forcing
            # the interval to 0 so cadence never blocks, leaving ONLY the
            # content-fingerprint dedupe as the silencer.
            second = _run(home, root, extra_env={"CLAUDE_PLUGIN_OPTION_MEMORY_SCOPE_LEAK_INTERVAL": "0"})
            self.assertEqual(second.strip(), "")


if __name__ == "__main__":
    unittest.main()
