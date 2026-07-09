"""Tests for the daemon's tool-PATH repair (TRDD-VQ4LX7ND).

The bug this locks down: a launchd/systemd child inherits a bare PATH with no
`/opt/homebrew/bin` and no `~/.local/bin`, so `tmux` and `aimaestro-agent.sh`
were unresolvable. `fleet_scan._run` swallowed the FileNotFoundError into "" and
the fleet guardian logged `UNREACHABLE ({})` and skipped every rearm — silently,
254 consecutive beats, while the identical code fired 93 injections from a
session-spawned daemon that had a login PATH.

`augmented_path` is pure (the `exists` predicate is injected), so the decision is
tested without touching the filesystem. Only the two idempotence/integration
tests read the real environment, and neither mutates `os.environ`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import daemon_path as dpth  # type: ignore[import-not-found]  # noqa: E402

# The PATH actually observed on `ps -p <daemon-pid> -wwEo command` for the
# launchd-spawned daemon (pid 89016, 2026-07-09). Verbatim — this IS the bug.
LAUNCHD_PATH = (
    "/Users/someone/.local/share/uv/python/cpython-3.12.9-macos-aarch64-none/bin"
    ":/usr/bin:/bin:/usr/sbin:/sbin"
)


def _exists(present: set[str]):
    return lambda d: d in present


def test_appends_only_dirs_that_exist() -> None:
    """A candidate absent from disk is never added to PATH."""
    new, added = dpth.augmented_path(
        "/usr/bin",
        candidates=["/opt/homebrew/bin", "/nope/bin"],
        exists=_exists({"/opt/homebrew/bin"}),
    )
    assert added == ["/opt/homebrew/bin"]
    assert new == "/usr/bin:/opt/homebrew/bin"


def test_appends_never_prepends() -> None:
    """The launcher's own PATH keeps priority — we can only ever make an
    unresolvable tool resolvable, never shadow one the host chose."""
    new, _ = dpth.augmented_path(
        "/usr/bin:/bin",
        candidates=["/opt/homebrew/bin"],
        exists=_exists({"/opt/homebrew/bin"}),
    )
    assert new.split(os.pathsep)[:2] == ["/usr/bin", "/bin"]
    assert new.split(os.pathsep)[-1] == "/opt/homebrew/bin"


def test_skips_dirs_already_on_path() -> None:
    """An already-present dir is not duplicated."""
    new, added = dpth.augmented_path(
        "/usr/bin:/opt/homebrew/bin",
        candidates=["/opt/homebrew/bin"],
        exists=_exists({"/opt/homebrew/bin"}),
    )
    assert added == []
    assert new == "/usr/bin:/opt/homebrew/bin"


def test_expands_tilde_before_dedupe_and_append() -> None:
    """`~/.local/bin` already on PATH in expanded form is not re-appended."""
    home_local = os.path.expanduser("~/.local/bin")
    new, added = dpth.augmented_path(
        f"/usr/bin:{home_local}",
        candidates=["~/.local/bin"],
        exists=_exists({home_local}),
    )
    assert added == []
    assert new == f"/usr/bin:{home_local}"


def test_expanded_tilde_is_what_gets_appended() -> None:
    """A `~` candidate is appended in EXPANDED form (a literal `~` on PATH would
    not resolve for a subprocess)."""
    home_cargo = os.path.expanduser("~/.cargo/bin")
    _, added = dpth.augmented_path(
        "/usr/bin", candidates=["~/.cargo/bin"], exists=_exists({home_cargo})
    )
    assert added == [home_cargo]
    assert "~" not in added[0]


def test_nothing_to_add_returns_path_unchanged() -> None:
    """No candidate exists → the original string is returned identically."""
    original = "/usr/bin:/bin"
    new, added = dpth.augmented_path(original, candidates=["/nope"], exists=_exists(set()))
    assert added == []
    assert new is original


def test_candidate_order_is_preserved() -> None:
    """Candidates are appended in declaration order (most-likely prefix first)."""
    present = {"/a", "/b", "/c"}
    _, added = dpth.augmented_path(
        "/usr/bin", candidates=["/a", "/b", "/c"], exists=_exists(present)
    )
    assert added == ["/a", "/b", "/c"]


def test_empty_path_entries_are_dropped() -> None:
    """A trailing/duplicate separator must not produce an empty PATH entry (an
    empty entry means CWD to execvp — a real security footgun)."""
    new, _ = dpth.augmented_path(
        "/usr/bin::", candidates=["/opt/homebrew/bin"], exists=_exists({"/opt/homebrew/bin"})
    )
    assert "" not in new.split(os.pathsep)


def test_default_prefixes_per_platform() -> None:
    """macOS gets Homebrew first; Linux gets linuxbrew; an unknown platform gets
    NOTHING (we never guess at directories on a host we don't understand)."""
    assert dpth.default_prefixes("darwin")[0] == "/opt/homebrew/bin"
    assert "/home/linuxbrew/.linuxbrew/bin" in dpth.default_prefixes("linux")
    assert dpth.default_prefixes("win32") == ()


def test_regression_launchd_path_cannot_find_tmux_before_repair() -> None:
    """THE BUG: the real launchd PATH resolves neither tmux nor the ai-maestro CLI.

    Asserted against a fake filesystem so the test is host-independent — the point
    is that neither tool's directory is on the inherited PATH.
    """
    entries = set(LAUNCHD_PATH.split(os.pathsep))
    assert "/opt/homebrew/bin" not in entries  # tmux lives here
    assert os.path.expanduser("~/.local/bin") not in entries  # aimaestro-agent.sh lives here


def test_repair_puts_tmux_and_aimaestro_dirs_on_the_launchd_path() -> None:
    """THE FIX: after augmentation both channel dirs are present, appended."""
    home_local = os.path.expanduser("~/.local/bin")
    present = {"/opt/homebrew/bin", home_local}
    new, added = dpth.augmented_path(
        LAUNCHD_PATH,
        candidates=["/opt/homebrew/bin", "~/.local/bin", "/nonexistent"],
        exists=_exists(present),
    )
    entries = new.split(os.pathsep)
    assert "/opt/homebrew/bin" in entries
    assert home_local in entries
    assert added == ["/opt/homebrew/bin", home_local]
    # Original entries survive, in order, ahead of the additions.
    assert entries[: len(LAUNCHD_PATH.split(os.pathsep))] == LAUNCHD_PATH.split(os.pathsep)


def test_ensure_tool_path_is_idempotent_and_mutates_the_given_env() -> None:
    """A second call adds nothing; the mapping passed in is the one mutated (so the
    daemon's real os.environ is never touched by this test)."""
    env: dict[str, str] = {"PATH": "/usr/bin"}
    first = dpth.ensure_tool_path(env)
    after_first = env["PATH"]
    second = dpth.ensure_tool_path(env)
    assert second == []
    assert env["PATH"] == after_first
    for d in first:
        assert d in after_first.split(os.pathsep)


def test_ensure_tool_path_never_drops_existing_entries() -> None:
    """Whatever the launcher gave us stays on the PATH."""
    env = {"PATH": LAUNCHD_PATH}
    dpth.ensure_tool_path(env)
    for entry in LAUNCHD_PATH.split(os.pathsep):
        assert entry in env["PATH"].split(os.pathsep)


def test_resolve_injection_tools_reports_missing_as_none() -> None:
    """A dead channel is reported as None — this is what makes the failure VISIBLE
    at daemon start instead of a mute `UNREACHABLE ({})` loop."""
    tools = dpth.resolve_injection_tools({"PATH": "/nonexistent-dir-for-tests"})
    assert set(tools) == set(dpth.INJECTION_TOOLS)
    assert all(v is None for v in tools.values())


def test_aimaestro_cli_is_a_tracked_injection_tool() -> None:
    """The ai-maestro CLI ENQUEUES a command a hibernated agent runs on wake — the
    only channel that reaches a wedged agent from a headless daemon. Its absence
    must be surfaced, not silently skipped."""
    assert "aimaestro-agent.sh" in dpth.INJECTION_TOOLS
