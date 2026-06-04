"""Tests for scripts/lib/suppression.py.

Covers TOML parsing, .janitorignore fallback, expiry handling, glob
matching, SHA matching, and the rule-id-required invariant.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import suppression as sup  # type: ignore[import-not-found]  # noqa: E402

# ---------- Empty / missing ----------------------------------------------


def test_no_files_returns_empty_table(tmp_path: Path) -> None:
    table = sup.load(tmp_path)
    assert table.entries == []
    assert not table.is_suppressed("any-rule", file="x.py")


# ---------- .janitor.toml — global rule suppression ---------------------


def test_global_rule_suppress(tmp_path: Path) -> None:
    (tmp_path / ".janitor.toml").write_text(
        '[[suppress]]\n'
        'rule_id = "shell-injection-expr"\n'
        'reason = "internal only"\n',
        encoding="utf-8",
    )
    table = sup.load(tmp_path)
    assert table.is_suppressed("shell-injection-expr")
    assert table.is_suppressed("shell-injection-expr", file=".github/workflows/x.yml")
    assert not table.is_suppressed("other-rule")


# ---------- .janitor.toml — path glob -----------------------------------


def test_path_glob_suppress(tmp_path: Path) -> None:
    (tmp_path / ".janitor.toml").write_text(
        '[[suppress]]\n'
        'rule_id = "missing-permissions"\n'
        'paths = [".github/workflows/legacy-*.yml"]\n'
        'expires = "2099-01-01"\n',
        encoding="utf-8",
    )
    table = sup.load(tmp_path)
    assert table.is_suppressed(
        "missing-permissions", file=".github/workflows/legacy-deploy.yml",
    )
    assert not table.is_suppressed(
        "missing-permissions", file=".github/workflows/ci.yml",
    )


def test_path_double_star_glob(tmp_path: Path) -> None:
    """`**/foo.yml` should match at any depth."""
    (tmp_path / ".janitor.toml").write_text(
        '[[suppress]]\n'
        'rule_id = "missing-permissions"\n'
        'paths = ["**/legacy.yml"]\n'
        'expires = "2099-01-01"\n',
        encoding="utf-8",
    )
    table = sup.load(tmp_path)
    assert table.is_suppressed(
        "missing-permissions", file=".github/workflows/legacy.yml",
    )


# ---------- SHA-based suppression --------------------------------------


def test_sha_suppress(tmp_path: Path) -> None:
    (tmp_path / ".janitor.toml").write_text(
        '[[suppress]]\n'
        'rule_id = "static-aws-credentials"\n'
        'sha = "abc123"\n'
        'reason = "test fixture"\n',
        encoding="utf-8",
    )
    table = sup.load(tmp_path)
    assert table.is_suppressed("static-aws-credentials", sha="abc123")
    assert not table.is_suppressed("static-aws-credentials", sha="def456")
    # Wrong rule_id never matches even with the right sha
    assert not table.is_suppressed("other-rule", sha="abc123")


def test_sha_as_list(tmp_path: Path) -> None:
    (tmp_path / ".janitor.toml").write_text(
        '[[suppress]]\n'
        'rule_id = "x"\n'
        'shas = ["a", "b", "c"]\n',
        encoding="utf-8",
    )
    table = sup.load(tmp_path)
    for sha in ("a", "b", "c"):
        assert table.is_suppressed("x", sha=sha)
    assert not table.is_suppressed("x", sha="d")


# ---------- Expiry semantics --------------------------------------------


def test_expired_waiver_ignored(tmp_path: Path, capsys) -> None:
    yesterday = dt.date.today() - dt.timedelta(days=1)
    (tmp_path / ".janitor.toml").write_text(
        '[[suppress]]\n'
        'rule_id = "missing-permissions"\n'
        f'expires = "{yesterday.isoformat()}"\n'
        'reason = "old waiver"\n',
        encoding="utf-8",
    )
    table = sup.load(tmp_path)
    assert not table.is_suppressed("missing-permissions")
    assert len(table.expired_entries) == 1
    # Loader emits a one-time stderr warning for expired entries
    captured = capsys.readouterr()
    assert "expired waiver IGNORED" in captured.err


def test_future_expiry_still_active(tmp_path: Path) -> None:
    future = dt.date.today() + dt.timedelta(days=365)
    (tmp_path / ".janitor.toml").write_text(
        '[[suppress]]\n'
        'rule_id = "missing-permissions"\n'
        f'expires = "{future.isoformat()}"\n',
        encoding="utf-8",
    )
    table = sup.load(tmp_path)
    assert table.is_suppressed("missing-permissions")


# ---------- Required-field invariants -----------------------------------


def test_missing_rule_id_skipped_with_warning(tmp_path: Path, capsys) -> None:
    (tmp_path / ".janitor.toml").write_text(
        '[[suppress]]\n'
        'reason = "no rule_id here"\n',
        encoding="utf-8",
    )
    table = sup.load(tmp_path)
    assert table.entries == []
    captured = capsys.readouterr()
    assert "missing required `rule_id`" in captured.err


def test_path_without_expires_warns(tmp_path: Path, capsys) -> None:
    """Path-based waivers without `expires` get a stderr warning so
    they don't rot in the repo forever — but they're still active."""
    (tmp_path / ".janitor.toml").write_text(
        '[[suppress]]\n'
        'rule_id = "missing-permissions"\n'
        'paths = [".github/workflows/legacy.yml"]\n',
        encoding="utf-8",
    )
    table = sup.load(tmp_path)
    assert table.is_suppressed(
        "missing-permissions", file=".github/workflows/legacy.yml",
    )
    captured = capsys.readouterr()
    assert "no `expires`" in captured.err


# ---------- .janitorignore fallback -------------------------------------


def test_janitorignore_simple_rule_list(tmp_path: Path) -> None:
    (tmp_path / ".janitorignore").write_text(
        "# blanket suppressions\n"
        "shell-injection-expr\n"
        "missing-timeouts\n",
        encoding="utf-8",
    )
    table = sup.load(tmp_path)
    assert table.is_suppressed("shell-injection-expr")
    assert table.is_suppressed("missing-timeouts")
    assert not table.is_suppressed("other-rule")


def test_janitor_toml_takes_precedence_over_janitorignore(tmp_path: Path) -> None:
    """When both files exist, .janitor.toml wins; .janitorignore is
    ignored so a user who upgrades to TOML doesn't double-suppress."""
    (tmp_path / ".janitor.toml").write_text(
        '[[suppress]]\n'
        'rule_id = "from-toml"\n',
        encoding="utf-8",
    )
    (tmp_path / ".janitorignore").write_text(
        "from-ignore\n", encoding="utf-8",
    )
    table = sup.load(tmp_path)
    assert table.is_suppressed("from-toml")
    assert not table.is_suppressed("from-ignore")


# ---------- Malformed TOML — never crashes ------------------------------


def test_malformed_toml_handled_gracefully(tmp_path: Path, capsys) -> None:
    (tmp_path / ".janitor.toml").write_text(
        '[[suppress\nrule_id = "broken"\n',  # missing closing ]]
        encoding="utf-8",
    )
    table = sup.load(tmp_path)
    assert table.entries == []
    captured = capsys.readouterr()
    assert "parse failed" in captured.err
