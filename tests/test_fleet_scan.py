"""Tests for the daemon-side fleet scanner (TRDD-324223a6).

The parsers are pure — real captured tool output, no mocks. ``diagnose_root``
runs against real files in a tmp tree (still no mocks; just real ``.janitor``
state). The load-bearing properties: a claude process is recognized from either
install shape; a TTY round-trips ps→lsof→iTerm; and a ``disarmed.flag`` makes a
project sacrosanct no matter how broken its other signals look.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import fleet_scan as fs  # type: ignore[import-not-found]  # noqa: E402


def test_parse_ps_claude_recognizes_both_shapes() -> None:
    """A versions-launcher path and a bare 'claude' argv0 are both claude; an
    unrelated daemon and a non-matching node cmd are not. TTY is normalized."""
    txt = (
        "  101 s001 /Users/x/.local/share/claude/versions/2.1.0/claude --continue\n"
        "  202 ?? /usr/sbin/some-daemon --foo\n"
        "  404 s004 claude\n"
        "   bad line without enough fields\n"
    )
    res = fs.parse_ps_claude(txt)
    pids = sorted(r[0] for r in res)
    assert pids == [101, 404]
    by_pid = {r[0]: r[1] for r in res}
    assert by_pid[101] == "ttys001"
    assert by_pid[404] == "ttys004"


def test_parse_iterm_sessions() -> None:
    """tty<TAB>id lines → {normalized_tty: id}; malformed/half rows dropped."""
    txt = "/dev/ttys003\tw0t1p0:ABC\n/dev/ttys005\tw0t2p0:DEF\n\tonlyid\n/dev/ttys006\t\n"
    assert fs.parse_iterm_sessions(txt) == {
        "ttys003": "w0t1p0:ABC",
        "ttys005": "w0t2p0:DEF",
    }


def test_parse_tmux_panes() -> None:
    """`#{pane_tty} #{pane_id}` lines → {normalized_tty: pane}; junk dropped."""
    txt = "/dev/ttys004 %5\n/dev/ttys007 %9\ngarbage-no-pane\n"
    assert fs.parse_tmux_panes(txt) == {"ttys004": "%5", "ttys007": "%9"}


def test_find_janitor_root(tmp_path: Path) -> None:
    """Walks up to the nearest .janitor project; None when none above / no cwd."""
    proj = tmp_path / "proj"
    (proj / ".janitor" / "state").mkdir(parents=True)
    sub = proj / "a" / "b"
    sub.mkdir(parents=True)
    assert fs.find_janitor_root(str(sub)) == os.path.realpath(str(proj))
    assert fs.find_janitor_root(str(tmp_path)) is None
    assert fs.find_janitor_root(None) is None


def test_diagnose_root_health_progression(tmp_path: Path) -> None:
    """Real .janitor state, IDLE session → the right diagnosis at each stage:
    fresh dispatch = healthy; stale = cron_dead→rearm; +rate-limit = frozen→ladder;
    +disarm = unarmed→leave alone (sacrosanct even though stale+rate-limited)."""
    root = tmp_path / "p"
    sdir = root / ".janitor" / "state"
    ldir = root / ".janitor" / "logs"
    sdir.mkdir(parents=True)
    ldir.mkdir(parents=True)
    now = 1_000_000
    dispatch = ldir / "dispatch.log"
    dispatch.write_text("x")

    os.utime(dispatch, (now - 60, now - 60))  # fresh
    assert fs.diagnose_root(str(root), now=now, active=False)[:2] == ("healthy", None)

    os.utime(dispatch, (now - 3600, now - 3600))  # 1h stale
    assert fs.diagnose_root(str(root), now=now, active=False)[:2] == ("cron_dead", "rearm")

    (sdir / "rate-limited.flag").write_text("")
    assert fs.diagnose_root(str(root), now=now, active=False)[:2] == ("frozen", "ladder")

    (sdir / "disarmed.flag").write_text("")  # user opted out → sacrosanct
    assert fs.diagnose_root(str(root), now=now, active=False)[:2] == ("unarmed", None)


def test_diagnose_root_active_session_is_healthy_despite_stale(tmp_path: Path) -> None:
    """A busy session (active=True) with a 1h-stale dispatch AND a rate-limit flag
    is HEALTHY — its heartbeat is queued behind the live turn; never nudge it.
    The exact false positive the dashboard surfaced on the real fleet."""
    root = tmp_path / "p"
    sdir = root / ".janitor" / "state"
    ldir = root / ".janitor" / "logs"
    sdir.mkdir(parents=True)
    ldir.mkdir(parents=True)
    now = 1_000_000
    dispatch = ldir / "dispatch.log"
    dispatch.write_text("x")
    os.utime(dispatch, (now - 3600, now - 3600))
    (sdir / "rate-limited.flag").write_text("")
    assert fs.diagnose_root(str(root), now=now, active=True)[:2] == ("healthy", None)


def test_diagnose_root_missing_dispatch_log_is_cron_dead(tmp_path: Path) -> None:
    """An armed IDLE project that has NEVER dispatched (no dispatch.log) is a dead
    cron, not healthy — the absence of progress is itself the signal."""
    root = tmp_path / "p"
    (root / ".janitor" / "state").mkdir(parents=True)
    (root / ".janitor" / "logs").mkdir(parents=True)
    assert fs.diagnose_root(str(root), now=1_000_000, active=False)[:2] == ("cron_dead", "rearm")
