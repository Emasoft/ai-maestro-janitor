"""The CPV validator pin has exactly ONE literal, and nothing may re-fork it.

The pin used to be written out eight times — five in publish.py, three across ci.yml
and release.yml — with nothing tying them together. A bump was eight independent
edits, and missing one produced the worst available failure: the local publish gate
validating against a different CPV than CI does. That is invisible until a release
goes red on a rule the local run never applied, at which point it reads as a CPV bug
rather than a stale pin.

`.cpv-version` is now the single source of truth. These tests exist because the
divergence is only detectable by looking at all eight sites at once — exactly the
thing a human bumping a version does not do.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_PIN_FILE = _ROOT / ".cpv-version"
_PUBLISH = _ROOT / "scripts" / "publish.py"

# A pin baked into a `git+https://…@<tag>` spec. This is the shape that must appear
# NOWHERE but `.cpv-version` — matching the tag explicitly (not `${CPV_PIN}`) is the
# whole point, so the pattern deliberately requires a literal `v<digits>`.
_HARDCODED = re.compile(r"claude-plugins-validation@v\d")


def _load_publish() -> Any:
    """Import publish.py as a module (it is a script, not a package member)."""
    spec = importlib.util.spec_from_file_location("_publish_under_test", _PUBLISH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_pin_file_exists_and_names_a_well_formed_tag() -> None:
    """`.cpv-version` is present and holds exactly one `vX.Y.Z` tag."""
    assert _PIN_FILE.is_file(), f"the CPV single source of truth is missing: {_PIN_FILE}"
    pin = _PIN_FILE.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"v\d+\.\d+\.\d+", pin), f"malformed CPV pin: {pin!r}"


def test_publish_resolves_the_pin_from_the_file() -> None:
    """publish.py's spec is DERIVED from the file, not a second copy of the tag."""
    mod = _load_publish()
    pin = _PIN_FILE.read_text(encoding="utf-8").strip()
    assert mod._CPV_PIN == pin
    assert mod._CPV_SPEC.endswith("@" + pin)
    assert mod._CPV_SPEC.startswith("git+https://github.com/Emasoft/")


def test_a_missing_pin_file_fails_fast_instead_of_defaulting(tmp_path: Path) -> None:
    """No file -> SystemExit. A silent default would run the release's mandatory
    security-and-structure gate against an unintended validator while reporting
    success — a publish that cannot say which validator it used is not validated."""
    mod = _load_publish()
    with pytest.raises(SystemExit):
        mod._read_cpv_pin(tmp_path / "does-not-exist")


@pytest.mark.parametrize(
    "bad",
    [
        "",  # empty file
        "4.2.0",  # missing the leading v
        "v4.2",  # not a full triple
        "main",  # a branch, i.e. an UNPINNED resolve — the supply-chain hole
        "v4.2.0 && rm -rf /",  # shell metacharacters: this string is interpolated
        "v4.2.0\nv9.9.9",  # two tags: which one did we validate against?
    ],
)
def test_a_malformed_pin_fails_fast(tmp_path: Path, bad: str) -> None:
    """Anything that is not exactly one `vX.Y.Z` is refused. The value is
    interpolated into a URL here and re-split by the shell in the workflows, so a
    permissive reader turns a typo into either a broken build or an injection."""
    mod = _load_publish()
    f = tmp_path / ".cpv-version"
    f.write_text(bad, encoding="utf-8")
    with pytest.raises(SystemExit):
        mod._read_cpv_pin(f)


def test_no_source_file_hardcodes_the_pin() -> None:
    """The literal survives in `.cpv-version` and the WORKFLOWS alone.

    The workflows are exempt because CPV's validator reads their YAML statically and
    rejects an interpolated ref (see
    `test_every_workflow_cpv_ref_is_a_literal_equal_to_the_pin_file`, which pins them to
    `.cpv-version` instead). They are the only sanctioned copies; every other file must
    read the pin.

    Scans the tracked tree (git ls-files, so vendored/ignored trees are out of
    scope) rather than a hand-listed set of files: a ninth copy added to a NEW
    workflow or script is exactly the regression this guards, and a fixed list
    would not see it.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split("\0")

    offenders: list[str] = []
    for rel in tracked:
        if not rel or rel in {".cpv-version", "tests/test_cpv_pin_ssot.py"}:
            continue
        # RECORD files are exempt, and the distinction is "does this text ever
        # RESOLVE?" — not "is it source?". A pin quoted in a changelog entry, a TRDD,
        # or a memory page is a historical fact about what ran at the time; none of
        # them can fetch anything, and rewriting one to the current tag would falsify
        # the record it exists to preserve. (Real example: the memory page on the CPV
        # false-positive incident quotes the v2.153.1 command line as evidence.)
        if (
            rel.startswith("CHANGELOG")
            or rel.startswith("design/")
            or "/memory/" in f"/{rel}"
            # The two workflows MUST carry the literal — CPV cannot resolve a variable
            # statically. Their equality with .cpv-version is enforced by the sibling
            # test, so this exemption widens the write surface without loosening the
            # invariant.
            or rel.startswith(".github/workflows/")
        ):
            continue
        p = _ROOT / rel
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except (OSError, IsADirectoryError):
            continue
        if _HARDCODED.search(text):
            offenders.append(rel)

    assert not offenders, (
        "these files hardcode the CPV pin instead of reading .cpv-version: "
        f"{offenders}. Bump the tag in .cpv-version only."
    )


def test_every_workflow_cpv_ref_is_a_literal_equal_to_the_pin_file() -> None:
    """Each workflow resolves CPV at a LITERAL tag, and every one of them equals
    `.cpv-version`.

    The workflows are the ONE place the tag is written out rather than read, and it is
    deliberate. CPV's own validator inspects the workflow YAML STATICALLY, so a
    `@${VAR}` read from `.cpv-version` at runtime is unresolvable to it and raises a
    MAJOR that blocks the publish (measured 2026-08-01: 3 findings, one per call site,
    on a construction that would in fact have expanded correctly in bash). The static
    form is also the auditable one — a reviewer sees which CPV version CI executes
    without following an indirection.

    So `.cpv-version` stays the single place a human edits, and THIS test is what
    propagates it: publish.py runs the suite as a gate, so a drifted workflow pin can
    never reach the remote. That makes the duplication enforced rather than trusted."""
    pin = (_ROOT / ".cpv-version").read_text(encoding="utf-8").strip()
    ref_re = re.compile(r"claude-plugins-validation@(?P<ref>[^\"'\s\\]+)")
    total = 0
    for name in ("ci.yml", "release.yml"):
        text = (_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        refs = [m.group("ref") for m in ref_re.finditer(text)]
        assert refs, f"{name}: no CPV resolve found"
        total += len(refs)
        for ref in refs:
            assert "$" not in ref, (
                f"{name} resolves CPV at {ref!r} — an interpolated ref is a MAJOR "
                "finding for CPV's static validator. Write the tag literally."
            )
            assert ref == pin, (
                f"{name} pins CPV at {ref!r} but .cpv-version says {pin!r}. "
                "Bump .cpv-version and update every workflow call site in the same commit."
            )
    assert total >= 3, f"expected every known CPV call site to be checked, saw {total}"
