"""redactInto in hooks/secret-shield/patterns.ts applies jwtWide as its final pass (TRDD-6A3XW3VO).

jwtWide hides the jr-shape JWTs (8-character segments, any second segment). Run before the bearer-token rule or the
assignment and connection-string passes it pre-empts them: they then see a marker and leave the tail of the value visible
(`Authorization: Bearer <token>+/=xyz` became `Bearer [mark]+/=xyz`; 10962 of 39072 contextual inputs regressed). As the
last pass it only hides what every other rule left. The context table in tests/patterns.test.ts fails when jwtWide moves
earlier, but a pass added below it would be pre-empted the same way and no row of that table would notice.

The position is pinned here, in pytest, because the plugin test sandbox refuses `node:fs`: a test under
hooks/secret-shield/tests/ cannot read patterns.ts (the file fails to load).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
PATTERNS_TS = _REPO / "hooks" / "secret-shield" / "patterns.ts"

JWTWIDE_LINE = "out = applyRule(out, jwtWide, hits, found)"


def _redact_into_statements(source: str) -> list[str]:
    """The non-comment lines of function redactInto, stripped, in source order."""
    start = source.index("function redactInto(")
    body = source[start : source.index("\n}", start)]
    return [line.strip() for line in body.splitlines() if line.strip() and not line.strip().startswith("//")]


def test_jwtwide_is_the_last_assignment_before_return_in_redact_into() -> None:
    """A pass added after jwtWide would be pre-empted by it the same way and re-create the tail-leak regression; the last `out =` must be the jwtWide pass."""
    statements = _redact_into_statements(PATTERNS_TS.read_text(encoding="utf-8"))
    assert statements[-1] == "return out"
    assignments = [line for line in statements if re.match(r"out = ", line)]
    assert assignments[-1] == JWTWIDE_LINE


def test_jwtwide_is_not_in_the_tokens_list() -> None:
    """In TOKENS (which run first, before the context passes) jwtWide leaked the tail of values the later rules hide whole; it must only run as the final pass."""
    source = PATTERNS_TS.read_text(encoding="utf-8")
    tokens = source[source.index("const TOKENS") : source.index("\n]", source.index("const TOKENS"))]
    assert "jwtWide" not in tokens
    assert source.count(JWTWIDE_LINE) == 1
