"""Spec-level checks on design/specs/issue-codes.toml and its generated artifacts (TRDD-DSN035UN, C10)."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import issue_catalog  # noqa: E402

CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{3}$")
REQUIRED = {"code", "name", "family", "severity", "fix", "gate_floor", "emitter", "summary", "why", "fix_text"}
ROWS = tomllib.loads((ROOT / "design" / "specs" / "issue-codes.toml").read_text(encoding="utf-8"))["issue"]


def test_generator_check_passes_on_committed_tree() -> None:
    """`build_issue_codes.py --check` exits 0: every generated file matches the TOML."""
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_issue_codes.py"), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_codes_match_regex_and_are_unique() -> None:
    """Every code matches the code regex; codes and names are unique."""
    codes = [r["code"] for r in ROWS]
    names = [r["name"] for r in ROWS]
    assert all(CODE_RE.match(c) for c in codes)
    assert len(set(codes)) == len(codes)
    assert len(set(names)) == len(names)


def test_every_row_has_required_keys() -> None:
    """Every row carries the required keys."""
    for r in ROWS:
        assert REQUIRED <= set(r), f"{r.get('code')}: missing {REQUIRED - set(r)}"


def test_issue_catalog_equals_toml_catalog_rows() -> None:
    """ISSUE_CATALOG is exactly the TOML rows that carry a `kind`."""
    cat = {r["code"]: r for r in ROWS if "kind" in r}
    assert set(issue_catalog.ISSUE_CATALOG) == set(cat)
    for code, i in issue_catalog.ISSUE_CATALOG.items():
        r = cat[code]
        assert (i.scanner, i.kind, i.severity, i.title, i.what, i.why, i.fix) == (r["emitter"].split(":", 1)[1], r["kind"], r["severity"].lower(), r["summary"], r["what"], r["why"], r["fix_text"])
