"""The setup SKILL's convergence check must be NAME **and** CONTENT (janitor#294 defect 2).

`baselines_present()` is by-NAME only, by design — it is the cheap short-circuit. The
guard applier learned to follow it with `baselines_content_current()` (TRDD-DD0M4QL7),
but `skills/janitor-branch-protection-setup/SKILL.md` did not: its step 3 read

    present = bpl.baselines_present(slug)
    if present: print('NOOP ...'); sys.exit(0)

so a repo whose `baseline-pr-and-checks` existed with `rules: []` — zero rules, nothing
required — short-circuited to NOOP and was never repaired. Measured downstream by the
reporter: `github-config-audit` raised NO_REQUIRED_CHECKS on the same repo where this
path declared convergence. The automated guard was fixed; the skill a HUMAN runs when
they believe they are repairing the baseline was not.

Why these tests execute the snippet instead of grepping it: a skill's fenced code block
is covered by no linter and no type-checker, so a NameError or a wrong keyword there
ships silently and only fails in front of a user mid-repair. The block is extracted from
the markdown, stubbed, and RUN — which is the only thing that proves the drifted path
actually reaches the apply rather than exiting.
"""

from __future__ import annotations

import ast
import re
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "janitor-branch-protection-setup" / "SKILL.md"


def _step3_source() -> str:
    """The step-3 python block, dedented, exactly as the skill ships it.

    `textwrap.dedent` is the ONLY safe way to do this, and a first version of this
    helper got it wrong: it stripped a fixed 3 characters from every line that began
    with three spaces. That happens to produce valid Python here — the inserted block
    sits one level deeper, so 3+4 spaces became 4 — but it silently RE-LEVELS any line
    at a different depth into a different-but-still-valid program, and `ast.parse`
    would then bless a shape the skill does not ship. Dedent removes the common prefix
    only, so relative indentation is preserved or the parse fails loudly.
    """
    text = SKILL.read_text(encoding="utf-8")
    start = text.index("present = bpl.baselines_present(slug)")
    head = text.rindex("default_branch = bpl.detect_default_branch(slug)", 0, start)
    tail_marker = "sys.exit(0 if all_ok else 1)"
    end = text.index(tail_marker, start) + len(tail_marker)
    block = text[head:end]
    # The first line starts mid-line in the markdown (its indent was consumed by the
    # slice), so dedent it against the indentation the following lines actually carry.
    lines = block.splitlines()
    rest = textwrap.dedent("\n".join(lines[1:]))
    return lines[0].strip() + "\n" + rest


def test_the_step3_block_is_extractable_and_parses() -> None:
    """Self-check: if extraction breaks, every other test here would vacuously pass."""
    src = _step3_source()
    assert "baselines_content_current" in src, "extraction grabbed the wrong block"
    ast.parse(src)


def test_the_skill_calls_the_content_check_after_the_name_check() -> None:
    """Ordering is the fix: the name check alone is what janitor#294 defect 2 reports."""
    src = _step3_source()
    assert src.index("baselines_present") < src.index("baselines_content_current")


def test_the_content_check_is_called_with_the_librarys_real_signature() -> None:
    """A wrong arity in a markdown block is invisible to every checker but a run."""
    sys.path.insert(0, str(REPO / "scripts" / "lib"))
    import inspect

    import branch_protection_lib as bpl

    params = list(inspect.signature(bpl.baselines_content_current).parameters)
    assert params == ["slug", "default_branch", "project_root"]
    call = re.search(r"baselines_content_current\(([^)]*)\)", _step3_source())
    assert call is not None
    args = [a.strip() for a in call.group(1).split(",")]
    assert args == ["slug", "default_branch", "project_root"]


class _Bpl:
    """Stub library: records whether the apply was reached."""

    def __init__(self, *, present, content):
        self._present = present
        self._content = content
        self.applied = False

    # Every stub takes *_ rather than named-but-unused parameters: the snippet calls
    # these positionally, the values are irrelevant to what is being pinned, and named
    # placeholders trip pyright's unused-parameter check — which this repo's gate runs
    # and FAILS CLOSED on.
    def detect_default_branch(self, *_):
        return "main"

    def gh_available(self, *_):
        return True

    def viewer_is_admin(self, *_):
        return True

    def baselines_present(self, *_):
        return self._present

    def baselines_content_current(self, *_):
        return self._content

    def apply_baseline_rulesets(self, *_):
        self.applied = True
        return True, [("baseline-history-protect", True, "applied")], []


def _run(bpl_stub) -> tuple[int, str]:
    """Execute the shipped snippet against the stub; return (exit code, stdout)."""
    import contextlib
    import io

    ns = {"bpl": bpl_stub, "sys": sys, "os": __import__("os"), "Path": Path,
          "slug": "Emasoft/example"}
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            exec(compile(_step3_source(), "<skill-step3>", "exec"), ns)  # noqa: S102
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, buf.getvalue()


def test_present_and_content_current_is_a_noop() -> None:
    """The converged repo must still short-circuit — a fix that always applies is not a fix."""
    stub = _Bpl(present=True, content=(True, []))
    code, out = _run(stub)
    assert code == 0
    assert "NOOP" in out
    assert stub.applied is False


def test_present_but_EMPTY_RULES_falls_through_to_the_apply() -> None:
    """THE REPORTED BUG: name present, zero rules — must NOT be NOOP, must repair."""
    stub = _Bpl(present=True, content=(False, ["baseline-pr-and-checks: rule pull_request missing"]))
    code, out = _run(stub)
    assert "NOOP" not in out, "a drifted ruleset was declared converged — janitor#294 defect 2"
    assert "DRIFT" in out, "the drift reason must be surfaced, not swallowed"
    assert stub.applied is True, "drift must fall through to the idempotent re-apply"
    assert code == 0


def test_absent_baselines_still_apply() -> None:
    """The original path — nothing present — must be unaffected by the content check."""
    stub = _Bpl(present=False, content=(True, []))
    code, out = _run(stub)
    assert stub.applied is True
    assert "NOOP" not in out
    assert code == 0


@pytest.mark.parametrize(
    "present,content",
    [(None, (True, [])), (True, None)],
)
def test_an_uncertain_lookup_never_applies(present, content) -> None:
    """`None` means a lookup FAILED. Acting on an unknown state is worse than not acting."""
    stub = _Bpl(present=present, content=content)
    code, out = _run(stub)
    assert stub.applied is False, "applied against an unverified remote state"
    assert code == 1
    assert "ERR" in out
