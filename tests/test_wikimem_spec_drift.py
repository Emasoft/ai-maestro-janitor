"""The wikimem spec must describe the CLI that exists — in BOTH directions.

`design/specs/wikimem-memgrep-spec.md` is authoritative for memgrep, and this project treats
"absent from the spec" as an error to be fixed. That instruction cuts both ways, and both cuts
draw blood:

- **implemented but unspecced** ⇒ the behaviour is DELETABLE. An agent auditing the tree against
  the spec finds code nothing justifies and removes it, correctly by the rule and wrongly in fact.
  19 flags were in exactly this state when this test was written (TRDD-DO6X4ZF8 follow-up).
- **specced but unimplemented** ⇒ the spec promises machinery that does not exist, and an agent
  builds it on faith, calling the work a bug fix. WM-SCORE-08 was in exactly this state: it
  specified two tie-break keys the scorer never had.

Neither direction is visible by reading either artifact alone — that is what makes a mechanical
check worth its weight. This test cannot verify that a clause is TRUE (prose is not executable),
only that the surface both sides name is the SAME surface. That is a floor, not a ceiling, and
it is the part that rots silently.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from conftest import MEMGREP_BIN_PATH

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "design" / "specs" / "wikimem-memgrep-spec.md"

# The wikimem verbs, from main.rs's hand-rolled dispatch (it pre-empts clap, so `--help` has no
# `Commands:` section to enumerate — hence the literal list, which the first test pins to source).
VERBS = (
    "index",
    "reindex",
    "validate",
    "links",
    "lint",
    "fact",
    "recall",
    "find",
    "find-claude-mem-ref",
    "atom",
    "atom-page",
    "overview",
    "add-atom",
    "new-page",
    "add-lesson",
    "migrate",
)

# Flags the spec deliberately does not describe, each with the reason it is exempt. An allowlist
# is only honest when every entry states WHY, otherwise it becomes the place inconvenient drift
# goes to be forgotten — which is the failure this test exists to prevent, re-created inside it.
EXEMPT: dict[str, str] = {
    "--help": "clap builtin, not a wikimem behaviour",
    "--version": "clap builtin, not a wikimem behaviour",
    "--hidden": ("generic walker knob shared with the grep half: descend into dotfiles. It changes WHICH files are visited, never what any wikimem rule means"),
}

_FLAG = re.compile(r"--[a-z][a-z0-9-]*")


def _require_binary() -> str:
    if not MEMGREP_BIN_PATH:
        pytest.skip("memgrep could not be found or built from this tree")
    return MEMGREP_BIN_PATH


def _help(verb: str) -> str:
    proc = subprocess.run(
        [_require_binary(), verb, "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.stdout + proc.stderr


def _flags_of(verb: str) -> set[str]:
    """The long flags `verb` accepts, read from its own `--help`.

    Only the option COLUMN is scanned: a flag named inside a prose description (`"(--markdown
    only)"`, or an example command line) belongs to another flag's explanation, and counting it
    here would invent options that do not exist.
    """
    found: set[str] = set()
    for line in _help(verb).splitlines():
        m = re.match(r"\s{2,}(?:-[a-zA-Z], )?(--[a-z][a-z0-9-]*)", line)
        if m:
            found.add(m.group(1))
    return found


def _bench_flags() -> set[str]:
    """`wikimem_bench.py`'s own flags.

    The spec's WM-BENCH family specifies the HARNESS, not just the binary, so a flag it names
    there is as real a promise as a memgrep one — and without this the over-claim check would
    report every legitimate `--corpus` / `--baseline` mention as a phantom.
    """
    proc = subprocess.run(
        ["uv", "run", str(REPO / "scripts" / "wikimem_bench.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=REPO,
    )
    return set(_FLAG.findall(proc.stdout + proc.stderr))


def _spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def _backticked_spans(text: str) -> list[str]:
    """The inline code spans of `text`, with fenced blocks removed FIRST.

    Order matters and is not a detail. A fence delimiter is three backticks, which an inline-span
    regex cannot pair (`[^`]+` needs a character between them), so it consumes past the fence and
    every span boundary after it is off by one. Measured on this spec: pairing without stripping
    fences captured 712 spans yet found neither `--output` nor a freshly-planted phantom flag —
    i.e. the assertion built on it was VACUOUS while reporting success. Fenced content is dropped
    rather than scanned because a fence here holds example output and verb listings, not the
    normative promises this test polices.
    """
    return re.findall(r"`([^`\n]+)`", re.sub(r"(?ms)^```.*?^```", "", text))


def _names_flag(text: str, flag: str) -> bool:
    """Does `text` name exactly `flag`?

    The boundary is the whole point. A plain substring test reports `--to` as documented because
    the spec mentions `--top`, and `--full` as documented because it mentions `--full-notes` — so
    the check would pass while the flag it was asked about is entirely absent. That false negative
    was observed while measuring this drift, and it silently shrinks the reported gap.
    """
    return re.search(re.escape(flag) + r"(?![a-z0-9-])", text) is not None


def test_dispatch_list_matches_the_verbs_this_test_checks() -> None:
    """The VERBS tuple must be the dispatch table, or every other assertion here is scoped to a
    stale list and passes by checking nothing."""
    dispatch = (REPO / "scripts" / "memgrep" / "src" / "main.rs").read_text(encoding="utf-8")
    in_source = set(re.findall(r'Some\("([a-z][a-z0-9-]*)"\)\s*=>', dispatch))
    assert in_source == set(VERBS), f"main.rs's wikimem dispatch and this test's VERBS list have diverged — only in source: {sorted(in_source - set(VERBS))}; only in test: {sorted(set(VERBS) - in_source)}"


def test_every_verb_is_named_in_the_spec() -> None:
    text = _spec_text()
    missing = [v for v in VERBS if f"`{v}`" not in text and f"`memgrep {v}" not in text]
    assert not missing, f"verbs implemented but absent from {SPEC.name}: {missing}. An unspecced verb is a deletable verb — document it or remove it."


@pytest.mark.parametrize("verb", VERBS)
def test_every_flag_is_named_in_the_spec(verb: str) -> None:
    text = _spec_text()
    missing = sorted(f for f in _flags_of(verb) if f not in EXEMPT and not _names_flag(text, f))
    assert not missing, f"`memgrep {verb}` accepts {missing}, which {SPEC.name} never names. Document them, or add an EXEMPT entry stating why they are out of scope."


def test_the_spec_names_no_flag_that_does_not_exist() -> None:
    """The over-claim direction: a flag the spec promises must be real.

    Scanned from backticked spans only. Unquoted prose in this spec discusses rejected and
    deferred designs by name (WM-SCORE-08a is an entire clause about a key that was NOT built), so
    treating every `--word` in the prose as a promise would report the spec's own record of what
    it decided against as a defect.
    """
    real = {f for verb in VERBS for f in _flags_of(verb)}
    real |= set(EXEMPT)
    real |= _flags_of("--help")  # the top-level grep surface
    real |= _bench_flags()  # WM-BENCH specifies the harness, so its flags are real promises too

    promised = {flag for span in _backticked_spans(_spec_text()) for flag in _FLAG.findall(span)}
    assert "--output" in promised, "the span scanner found no `--output`, a flag this spec certainly promises — it is matching nothing, so the assertion below would pass vacuously"
    phantom = sorted(promised - real)
    assert not phantom, f"{SPEC.name} names flags that memgrep does not accept: {phantom}. A spec that promises a flag invites someone to 'restore' it."
