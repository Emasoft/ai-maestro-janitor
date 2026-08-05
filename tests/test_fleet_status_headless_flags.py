"""`--no-open` and `--out` — the headless interface ai-maestro asked for (janitor#197).

The dashboard used to end with an unconditional browser open and a `tempfile.mkstemp()`
path printed to stdout. A headless caller therefore had exactly two options, and
ai-maestro was using both: shim the child's `PATH` with a no-op `open`, and scrape the
`Dashboard: <path>` line back out of stdout to find the artifact.

Both worked, and that is the problem worth testing against. They worked because of two
incidental properties — the opener is a bare PATH-resolved command name, and the call sits
in a `try/except` that degrades to one printed line. Neither is a promise, so both could
have been "fixed" without anyone noticing the downstream contract they were carrying. These
tests make the interface explicit so that can't happen quietly.

`--out` is tested for the property that actually matters to a caller who named a path: the
file lands THERE, still 0600, and a failure to write it is raised rather than silently
redirected to the default location — being told "written" about a different path is worse
than an error.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import fleet_scan  # type: ignore[import-not-found]  # noqa: E402
import fleet_status as fstat  # type: ignore[import-not-found]  # noqa: E402


@pytest.fixture
def stub_scan(monkeypatch):
    """Neutralise the host scan for the two tests that drive `main()`.

    `main()` calls `fleet_scan.gather_fleet`, which shells out to `aimaestro-agent.sh`,
    `ps`, and git. The suite's sandbox guard denies un-allow-listed binaries by default and
    is right to: these tests are about ONE decision — whether a browser window is opened —
    and scanning the real host to reach it would make them slow, machine-dependent, and
    liable to fail for reasons that have nothing to do with the flag under test.

    Stubbing the scan, not the binaries, keeps the code path from `main()` through the
    open decision fully real; only the data it renders is empty.
    """
    monkeypatch.setattr(fleet_scan, "gather_fleet", lambda **kw: [])


# ── _flag_value: the hand-rolled parser ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["prog", "--out", "/tmp/x.html"], "/tmp/x.html"),
        (["prog", "--out=/tmp/x.html"], "/tmp/x.html"),
        (["prog", "--ci", "--out", "/tmp/x.html", "--no-open"], "/tmp/x.html"),
        (["prog"], ""),
    ],
)
def test_flag_value_reads_both_spellings(monkeypatch, argv, expected) -> None:
    monkeypatch.setattr(sys, "argv", argv)
    assert fstat._flag_value("--out") == expected


def test_a_flag_with_no_value_does_not_swallow_the_next_flag(monkeypatch) -> None:
    """`--out --no-open` is a truncated invocation, not a request to write to a file
    named "--no-open". Returning "" falls back to the default path; consuming the next
    flag would both lose `--no-open` AND write somewhere absurd."""
    monkeypatch.setattr(sys, "argv", ["prog", "--out", "--no-open"])
    assert fstat._flag_value("--out") == ""


def test_a_trailing_flag_at_end_of_argv_does_not_index_past_the_end(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["prog", "--out"])
    assert fstat._flag_value("--out") == ""


# ── --out: the caller names the destination ───────────────────────────────────────────


def test_out_override_writes_exactly_where_asked(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dash.html"
    got = fstat._write_report("<html>x</html>", out_override=str(target))
    assert got == str(target)
    assert target.read_text(encoding="utf-8") == "<html>x</html>"


def test_out_override_keeps_the_0600_mode(tmp_path: Path) -> None:
    """An explicit path changes WHERE the fleet's status lands, never how exposed it is —
    this file carries every running session's project path, git remotes, pid and kanban."""
    target = tmp_path / "dash.html"
    fstat._write_report("<html>x</html>", out_override=str(target))
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_out_override_expands_a_tilde(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    got = fstat._write_report("<html>x</html>", out_override="~/dash.html")
    assert got == str(tmp_path / "dash.html")
    assert (tmp_path / "dash.html").is_file()


def test_an_unwritable_out_path_RAISES_rather_than_silently_using_the_default(
    tmp_path: Path,
) -> None:
    """The dangerous failure is not the error — it is reporting success about a path the
    caller did not ask for. ai-maestro embeds this file in a dashboard iframe by path; a
    silent fallback would leave it rendering a stale document forever with nothing wrong
    in any log."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")
    with pytest.raises(OSError):
        fstat._write_report("<html>x</html>", out_override=str(blocker / "dash.html"))


def test_no_override_still_lands_in_the_project_reports_dir(tmp_path: Path, monkeypatch) -> None:
    """The default path is unchanged by janitor#197 — it must NOT regress to the temp dir."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    got = Path(fstat._write_report("<html>x</html>"))
    assert got.parent == tmp_path / "reports" / "fleet-status"
    assert stat.S_IMODE(got.stat().st_mode) == 0o600


# ── --no-open: the browser must be suppressible by flag, not by PATH shimming ─────────


def test_no_open_suppresses_the_browser_launch(monkeypatch, capsys, stub_scan) -> None:
    """Asserted on the real main() path, because the bug this prevents is a desktop popup
    and the unconditional launch lived in main(), not in a helper.

    Patches `_open_in_browser`, NOT `subprocess.Popen`: the fleet scan calls
    `subprocess.run`, which constructs a Popen internally, so a module-wide patch breaks
    the scan instead of observing the open. That mistake made the first version of this
    test fail against correct code — which is the argument for the named seam."""
    opened: list[str] = []
    monkeypatch.setattr(fstat, "_open_in_browser", opened.append)
    monkeypatch.setattr(fstat, "_render_html", lambda *a, **k: "/tmp/fake-dash.html")

    monkeypatch.setattr(sys, "argv", ["prog", "--no-open"])
    assert fstat.main() == 0
    assert opened == [], "--no-open must not open a browser"
    assert "/tmp/fake-dash.html" in capsys.readouterr().out, (
        "the path must still be printed — suppressing the window must not hide the artifact"
    )


def test_without_no_open_the_browser_is_still_launched(monkeypatch, stub_scan) -> None:
    """The default stays interactive. Guards against 'fixing' the popup by removing it for
    everyone, which would break the human who runs this at a terminal."""
    opened: list[str] = []
    monkeypatch.setattr(fstat, "_open_in_browser", opened.append)
    monkeypatch.setattr(fstat, "_render_html", lambda *a, **k: "/tmp/fake-dash.html")

    monkeypatch.setattr(sys, "argv", ["prog"])
    assert fstat.main() == 0
    assert opened == ["/tmp/fake-dash.html"]
