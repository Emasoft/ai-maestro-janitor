"""A future-dated `updated:` — the board's sort key, and until now its only unread field.

WHY THIS EXISTS (TRDD-TUVQWLJF). On 2026-08-16 three TRDDs were found carrying HAND-TYPED
`updated:` stamps between 77 and 79 minutes AHEAD of the commits that wrote them, every one at a
round minute (`:50:00`, `:05:00`). The board sorts on `updated:`, so each pinned itself above every
honestly-stamped card, and the field is read as "when was this last measured" — so a session
reasoning from one reasons from a false measurement.

Nothing caught it, and the reason is exact rather than accidental: `trdd-drift` judges staleness
from GIT COMMIT TIME (`_last_touched_epoch`) and never read `updated:` at all. The field with no
consumer was the field with no validator. These tests pin the new consumer.

Two properties are load-bearing and easy to lose in a later "cleanup":

* the check runs BEFORE the active-column filter, so a TERMINAL card is audited too — rule §12
  freezes a terminal TRDD's body but still permits `updated:` to change, and the terminal columns
  are where most cards live;
* the dedupe key carries the OFFENDING VALUE, so a second bad stamp written after the first was
  fixed is reported instead of being swallowed by a once-per-card key.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_DRIFT = _ROOT / "scripts" / "detectors" / "trdd-drift.py"
_TS = "20260101_000000+0000"
_FMT = "%Y-%m-%dT%H:%M:%S%z"

# Same prologue as test_trdd_common.py: `scripts/lib` on sys.path, then a plain import. A
# `spec_from_file_location` load fails here — trdd_common does `from lib import memory_scopes`,
# which needs `scripts/` on the path as a package root, so loading the file in isolation cannot
# resolve it.
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import trdd_common as tc  # noqa: E402


def _stamp(offset_s: float) -> str:
    """An ISO stamp `offset_s` from now, in the LOCAL zone with its explicit offset."""
    return (datetime.now().astimezone() + timedelta(seconds=offset_s)).strftime(_FMT)


def _head(updated: str | None, *, column: str = "todo") -> str:
    lines = ["---", "trdd-id: TUVQWLJF", "title: T", f"column: {column}"]
    if updated is not None:
        lines.append(f"updated: {updated}")
    lines += ["created: 2026-01-01T00:00:00+0000", "---", "", "# body", "x"]
    return "\n".join(lines) + "\n"


# ── the pure predicate ───────────────────────────────────────────────────────────────────


def test_a_past_stamp_is_not_reported():
    """The overwhelmingly common case must stay silent, or the check is noise."""
    now = int(time.time())
    assert tc.future_updated(_head(_stamp(-86400)), now, 300) is None


def test_a_stamp_inside_the_tolerance_is_not_reported():
    """Clock skew between contributors is absorbed — PROJECT TRDDs are pushed and shared."""
    now = int(time.time())
    assert tc.future_updated(_head(_stamp(120)), now, 300) is None


def test_a_stamp_beyond_the_tolerance_is_reported_verbatim():
    """The RAW value comes back, because the reader must see the exact text to fix it."""
    now = int(time.time())
    bad = _stamp(4620)  # +77 min — the error actually measured
    assert tc.future_updated(_head(bad), now, 300) == bad


def test_a_missing_updated_field_is_silent():
    """Absent is not wrong. A card with no `updated:` is a different defect, owned elsewhere."""
    now = int(time.time())
    assert tc.future_updated(_head(None), now, 300) is None


@pytest.mark.parametrize(
    "value",
    [
        "not a date",
        "2026-08-16",  # date only
        "2026-08-16T06:05:32",  # NAIVE — no offset, so not the mandated format
        "2026-02-31T00:00:00+0200",  # calendar-invalid
        "",
    ],
)
def test_an_unparseable_value_fails_OPEN(value):
    """A value this cannot parse must NEVER become a finding.

    `frontmatter_defect` already owns "this frontmatter is unreadable". A date parser that also
    reported malformed input would report one defect twice, and the second report would name a
    cause the author cannot act on from this line.
    """
    now = int(time.time())
    assert tc.future_updated(_head(value), now, 300) is None


def test_the_tolerance_boundary_is_strict():
    """Exactly at the tolerance is NOT reported; one second past it is.

    Pinned because an off-by-one here is invisible in production — it only ever changes whether a
    card one second over the line is named, which no one would notice going wrong.
    """
    now = 1_000_000_000
    at = datetime.fromtimestamp(now + 300).astimezone().strftime(_FMT)
    past = datetime.fromtimestamp(now + 301).astimezone().strftime(_FMT)
    assert tc.future_updated(_head(at), now, 300) is None
    assert tc.future_updated(_head(past), now, 300) == past


# ── end to end, through the real detector ────────────────────────────────────────────────


def _project(tmp: str) -> Path:
    root = Path(tmp)
    (root / "design" / "tasks").mkdir(parents=True)
    return root


def _write(tasks: Path, uid8: str, content: str) -> Path:
    p = tasks / f"TRDD-{_TS}-{uid8}-slug.md"
    p.write_text(content)
    old = time.time() - 100 * 86400
    os.utime(p, (old, old))
    return p


def _run(project: Path) -> str:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_SESSION_ID"] = "sess"
    # The temp project is not an ai-maestro-plugins member; the context gate has its own tests.
    env["JANITOR_FORCE_AI_MAESTRO"] = "1"
    for k in ("CLAUDE_PLUGIN_OPTION_TRDD_STALENESS_DAYS", "CLAUDE_PLUGIN_OPTION_TRDD_PATH"):
        env.pop(k, None)
    res = subprocess.run(
        [sys.executable, str(_DRIFT)], capture_output=True, text=True, env=env, timeout=60
    )
    return res.stdout


def test_e2e_a_future_stamped_card_is_named_and_a_correct_one_is_not():
    """The whole point, through the real detector: one card fires, its honest neighbour does not."""
    with TemporaryDirectory() as tmp:
        root = _project(tmp)
        tasks = root / "design" / "tasks"
        _write(tasks, "AAAAAAAA", _head(_stamp(4620)))
        _write(tasks, "BBBBBBBB", _head(_stamp(-4620)))
        out = _run(root)
        future_lines = [ln for ln in out.splitlines() if "FUTURE" in ln]
        assert any("TRDD-AAAAAAAA" in ln for ln in future_lines)
        # Line-wise, NOT `"TRDD-BBBBBBBB" not in out`: the honest card is also 100 days old and
        # `column: todo`, so it legitimately earns the ORDINARY staleness line. Asserting on the
        # whole stdout conflated the two findings and failed against correct behaviour — the
        # assertion was wrong, not the detector.
        assert not any("TRDD-BBBBBBBB" in ln for ln in future_lines)


def test_e2e_a_terminal_card_is_audited_too():
    """A `complete` card still fires — the check sits BEFORE the active-column filter.

    Load-bearing: the terminal columns hold most of the board, rule §12 still allows `updated:` to
    change there, and a future stamp on a terminal card corrupts the sort exactly as much. Moving
    the check below the filter would silently exempt the majority of the corpus.
    """
    with TemporaryDirectory() as tmp:
        root = _project(tmp)
        _write(root / "design" / "tasks", "CCCCCCCC", _head(_stamp(4620), column="complete"))
        out = _run(root)
        assert "TRDD-CCCCCCCC" in out


def test_e2e_the_same_bad_stamp_is_reported_once_but_a_NEW_one_re_fires():
    """Dedupe keys on the VALUE, not just the card.

    A once-per-card key would report the first bad stamp and then stay silent forever — including
    for a second bad stamp written after the first was corrected, which is the likelier event on a
    card someone is actively (mis)editing.
    """
    with TemporaryDirectory() as tmp:
        root = _project(tmp)
        tasks = root / "design" / "tasks"
        first = _stamp(4620)
        p = _write(tasks, "DDDDDDDD", _head(first))

        assert "TRDD-DDDDDDDD" in _run(root)
        assert "TRDD-DDDDDDDD" not in _run(root)  # unchanged value → already reported

        second = _stamp(9000)
        assert second != first
        p.write_text(_head(second))
        old = time.time() - 100 * 86400
        os.utime(p, (old, old))
        assert "TRDD-DDDDDDDD" in _run(root)
