"""janitor#209: a git ref and a file path are not a leak — but everything else still is.

Reported by the Claude developing ai-maestro-plugin, against a PROJECT memory page:

    Emasoft/ai-maestro@governance-rules:docs/GOVERNANCE-RULES.md   -> "machine-host"
    skills/team-governance/references/GOVERNANCE-RULES.md          -> "high-entropy secret"

Both false. `memory-scope-leak` is a PRE-PUSH control on the one memory scope that is committed
and pushed, so a false positive costs a real push and trains the reader to wave the detector
through — which is the failure mode that matters for a security control.

Every test here is TWO-SIDED by construction: the file is a matched pair of "this must go quiet"
and "this must still fire". A one-sided version of this file would pass just as well if the fix
had simply disabled the rules.
"""

from __future__ import annotations

import importlib.util
import pathlib
import tempfile

import pytest

_DETECTOR = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "memory-scope-leak.py"


def _load():
    spec = importlib.util.spec_from_file_location("memory_scope_leak", _DETECTOR)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scan(text: str) -> list[str]:
    mod = _load()
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        path = pathlib.Path(fh.name)
    try:
        return mod._scan_page(path)
    finally:
        path.unlink()


@pytest.mark.parametrize(
    "label,text",
    [
        # The two shapes from the report, in BARE PROSE — the peer's region-awareness fix already
        # covered them inside code markup, so prose is the only place they still fired.
        ("git ref spec", "See Emasoft/ai-maestro@governance-rules:docs/GOVERNANCE-RULES.md now"),
        ("repo-relative path", "The file skills/team-governance/references/GOVERNANCE-RULES.md defines it."),
        ("path in a table cell", "| doc | scripts/detectors/memory-scope-leak.py | surfaces it |"),
    ],
)
def test_documentation_shapes_are_not_leaks(label: str, text: str) -> None:
    """A page CITING a repo ref or a file path carries no private data and must stay silent."""
    assert _scan(text) == [], f"{label} must not be reported as a leak"


@pytest.mark.parametrize(
    "label,text",
    [
        # The counter-cases. Each targets the specific hole its sibling exemption could open.
        ("ssh user@host", "Run ssh deploy@prod-box-01.internal to reach it."),
        # The exemption's lookbehind rejects `://`, so a URL-form ssh target is still an account
        # on a machine even though a `/` precedes the `@`.
        ("ssh:// url", "Use ssh://deploy@prod-box-01 for the tunnel."),
        # Fragmented per tests/README.md: `test_secret_fixture_hygiene` forbids a CONTIGUOUS
        # credential literal anywhere in tracked source, and it is right to — a fake token that
        # matches the real format is indistinguishable from a leaked one to every scanner that
        # ever reads this repo. Assembled at runtime, so the detector still sees the full token.
        ("vendor-prefixed token", "token = " + "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"),
        ("home directory path", "It lives at /Users/emanuele/Code/secret-thing/x.md here."),
        ("aws secret access key", "AKIAIOSFODNN7EXAMPLE and wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"),
        # THE load-bearing counter-case for the path exemption: base64 legitimately contains `/`,
        # so "has a slash" alone could never be the test. This blob has slashes and no file
        # extension following it, and must still convict.
        ("base64 blob containing slashes", "payload = aGVsbG8vd29ybGQvc2VjcmV0L3Rva2VuL2FiY2RlZmdoaWprbG1ub3A="),
    ],
)
def test_real_leaks_still_fire(label: str, text: str) -> None:
    """The exemptions are narrow: every genuine private-data shape must still be reported."""
    assert _scan(text), f"{label} must still be reported — the exemption must not open a hole"


def test_path_exemption_needs_both_a_separator_and_an_extension() -> None:
    """Unit-level guard on the predicate itself, so the two halves cannot be relaxed silently."""
    mod = _load()
    text = "see scripts/detectors/memory-scope-leak.py ok"
    tok = "scripts/detectors/memory-scope-leak"
    end = text.index(tok) + len(tok)
    assert mod._is_path_shaped(tok, text, end), "a real path with an extension must be exempt"
    # Same token, but nothing that looks like a file extension follows it.
    bare = f"see {tok} ok"
    assert not mod._is_path_shaped(tok, bare, len("see ") + len(tok)), (
        "without a trailing extension the token is not provably a filename"
    )
    # An extension, but no separator — cannot be a repo-relative path.
    assert not mod._is_path_shaped("abcdefghijklmnopqrstuvwx", "abcdefghijklmnopqrstuvwx.md", 24)
