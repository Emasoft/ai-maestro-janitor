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
SKILL = REPO / "scripts" / "memgrep" / "SKILL.md"

# The wikimem verbs, from main.rs's hand-rolled dispatch (it pre-empts clap, so `--help` has no
# `Commands:` section to enumerate — hence the literal list, which the first test pins to source).
# `new-page`/`add-atom`/`edit`/`migrate` are LEGACY spellings now: `dispatch_key()` resolves them
# onto their replacement (`new-mem-topic`/`new-mem-atom`/`update-mem-topic`/`migrate-mem-atom`)
# BEFORE the match statement ever runs, so the literal `Some("add-atom")` pattern no longer exists
# in source — only the canonical name does. `add-lesson` is NOT in that table (no replacement
# resolves it away) and still dispatches on its own literal arm, so it stays a first-class verb
# here, not a legacy alias.
VERBS = (
    # ---- READ / SEARCH ----
    "recall",
    "recall-mem-topic",
    "recall-mem-atom",
    "find",
    "overview",
    "atom",
    "atom-page",
    "fact",
    "links",
    "find-claude-mem-ref",
    "find-trdd",
    # ---- WRITE ----
    "new-mem-topic",
    "new-mem-atom",
    "add-lesson",
    "update-mem-topic",
    "update-mem-atom",
    "delete-mem-topic",
    "delete-mem-atom",
    "merge-mem-topic",
    "merge-mem-atom",
    "split-mem-topic",
    "split-mem-atom",
    "reference-mem-topic",
    "reference-mem-atom",
    "migrate-mem-atom",
    # ---- MAINTAIN ----
    "lint",
    "validate",
    "index",
    "reindex",
)

# Flags the spec deliberately does not describe, each with the reason it is exempt. An allowlist
# is only honest when every entry states WHY, otherwise it becomes the place inconvenient drift
# goes to be forgotten — which is the failure this test exists to prevent, re-created inside it.
EXEMPT: dict[str, str] = {
    "--help": "clap builtin, not a wikimem behaviour",
    "--version": "clap builtin, not a wikimem behaviour",
    "--hidden": ("generic walker knob shared with the grep half: descend into dotfiles. It changes WHICH files are visited, never what any wikimem rule means"),
    "--find": (
        "the verb-free note-search shortcut (`memgrep --find '<query>'`) is hand-parsed BEFORE "
        "clap ever sees argv (same trick as the top-level `--where`), so it never appears in any "
        "`--help` output `_flags_of()` can scan — real, but invisible to this test's flag scanner"
    ),
}

# Dispatch-table entries that are NOT wikimem verbs — the same "clap builtin, not a wikimem
# behaviour" reasoning as --help/--version above, one level up: a hand-dispatched match arm in
# main.rs that exists only to REACH a clap builtin rather than to do memory-toolkit work. Kept
# separate from VERBS (rather than adding it there) so `test_every_verb_is_named_in_the_skill`
# does not demand a SKILL.md invocation example for something that is not an invocable behaviour.
DISPATCH_EXEMPT_VERBS: dict[str, str] = {
    "help": (
        "janitor#127: a bare `memgrep help` used to succeed as a literal grep for the word "
        "\"help\" (exit 0, plausible output) instead of showing the verb list, which every other "
        "CLI's `help` convention does. The fix dispatches it to the SAME `Cli::command().print_help()` "
        "--help already reaches — not a new wikimem behaviour, so it earns no spec/skill entry of "
        "its own, exactly like --help itself above."
    ),
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
    """The VERBS tuple (plus the explicitly-reasoned DISPATCH_EXEMPT_VERBS) must be the dispatch
    table, or every other assertion here is scoped to a stale list and passes by checking
    nothing."""
    dispatch = (REPO / "scripts" / "memgrep" / "src" / "main.rs").read_text(encoding="utf-8")
    # `\||=>` (not just `=>`): a shared arm like `Some("recall") | Some("recall-mem-topic") |
    # Some("recall-mem-atom") => {` only has `=>` after the LAST alternative — anchoring on `=>`
    # alone silently drops every alternative before it, which is a false negative this test would
    # otherwise not catch (measured: it made `recall`/`recall-mem-topic` invisible to this check).
    in_source = set(re.findall(r'Some\("([a-z][a-z0-9-]*)"\)\s*(?:\||=>)', dispatch))
    expected = set(VERBS) | set(DISPATCH_EXEMPT_VERBS)
    assert in_source == expected, f"main.rs's dispatch and this test's VERBS+DISPATCH_EXEMPT_VERBS have diverged — only in source: {sorted(in_source - expected)}; only in test: {sorted(expected - in_source)}"


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


_SPAN_FIRST_WORD = re.compile(r"^([a-z][a-z0-9-]*)")


def _skill_documented_verbs() -> set[str]:
    """Every verb SKILL.md documents as an INVOCATION — the first token of a backticked span
    (`` `verb ARGS` ``, the shape every command-syntax mention in this file already uses).

    Verb names are ordinary English words (`find`, `edit`, `atom`, `index`...), so a bare
    substring/word-boundary search over the whole file would match them constantly in plain prose
    ("an atom's body", "find the...") and pass whether or not the verb is actually documented as a
    command. Scoping to backticked spans, and to the FIRST token of each span, is what makes a
    match mean "this is command syntax" rather than "this English word occurs somewhere".
    """
    return {
        m.group(1)
        for span in _backticked_spans(SKILL.read_text(encoding="utf-8"))
        if (m := _SPAN_FIRST_WORD.match(span))
    }


def test_every_verb_is_named_in_the_skill() -> None:
    """Every verb `main.rs` dispatches must be documented in SKILL.md — the artefact an agent
    actually LOADS into context (janitor#127).

    `memgrep --help` listing a verb is not enough: an agent handed "your index is broken" reaches
    for the skill, not `--help`. Measured on this file before the fix: `validate` — the one verb
    the safety-critical repair protocol depends on (`memgrep validate <page> && memgrep lint
    <page>`) — existed in the CLI with zero mention here, so the skill's own advice for a broken
    index was `reindex`, which MEMGREP-011's catalog text says NOT to do. This is the mechanical
    check the issue's own text asked for: it would have caught that the day `validate` landed.
    """
    documented = _skill_documented_verbs()
    missing = sorted(v for v in VERBS if v not in documented)
    assert not missing, (
        f"{SKILL.name} never documents `memgrep {{{','.join(missing)}}}` as an invocation (a "
        "backticked `verb ...` span) — an agent loading the skill cannot discover it. Add a "
        "table row or example line."
    )
