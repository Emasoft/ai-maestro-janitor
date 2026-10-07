"""TRDD-7YEVICVU: shipped skill/command markdown must not use BSD-only `stat -f` / `date -r`.

On GNU coreutils `stat -f` succeeds and prints file-system info (no failure to fall back
from) and `date -r` means "file reference", so a bare use silently misbehaves on Linux.
A use is allowed only when a `||` fallback follows it on the same line.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BSD_ONLY = re.compile(r"\b(?:stat -f|date -r)\b")


def find_bare_bsd_forms(text: str) -> list[int]:
    """1-based line numbers holding `stat -f` / `date -r` with no `||` after the match."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        m = _BSD_ONLY.search(line)
        if m and "||" not in line[m.end():]:
            hits.append(n)
    return hits


def test_no_shipped_markdown_uses_a_bare_bsd_only_stat_or_date() -> None:
    """No skill or command markdown has `stat -f` / `date -r` without a same-line `||` fallback."""
    offenders = []
    for sub in ("skills", "commands"):
        for path in sorted((_ROOT / sub).rglob("*.md")):
            for n in find_bare_bsd_forms(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(_ROOT)}:{n}")
    assert offenders == [], f"BSD-only stat -f / date -r without a fallback: {offenders}"


def test_scanner_flags_bare_and_accepts_fallback_forms() -> None:
    """Control: the scanner flags the bare forms and accepts a same-line `||` fallback."""
    assert find_bare_bsd_forms("t=$(stat -f %m f)") == [1]
    assert find_bare_bsd_forms("date -r 5 +%s") == [1]
    assert find_bare_bsd_forms("stat -f %m f || stat -c %Y f") == []
    assert find_bare_bsd_forms("echo nothing here") == []
