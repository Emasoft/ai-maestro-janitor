"""Tests for the runaway-kill guard (TRDD-5G66S0HK).

The guard lives at scripts/lib/runaway_guard.py and its broadcast channel
at scripts/lib/runaway_alert.py.

THE LOAD-BEARING SAFETY TEST is number 2: an interactive `claude`
session is never selected as a victim EVEN WHEN IT IS THE LARGEST
PROCESS ON THE HOST. Everything else in this file exists to make sure
that one rule cannot be weakened by a change elsewhere.

Real process tables and real git-free fixtures; no mocks of the
behaviour under test. The `env_probe` hook is the ONE injection point,
and it exists because the environment signal is the attribution channel
that cannot be produced by a synthetic process table — the tests assert
the RULE over a table, and the rule reads the environment through one
narrow, documented seam.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, LIB / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rg = _load("runaway_guard_under_test", "runaway_guard.py")
ra = _load("runaway_alert_under_test", "runaway_alert.py")


def _load_daemon():
    """The daemon module, loaded the way the daemon itself loads its lib.

    The chore lives in scripts/daemon.py, which is NOT under scripts/lib,
    so it gets its own loader. It inserts scripts/lib on sys.path at
    import time — which is the daemon's own convention, and the reason
    the lib modules import cleanly inside it.
    """
    root = Path(__file__).resolve().parent.parent
    lib = root / "scripts" / "lib"
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    spec = importlib.util.spec_from_file_location("daemon_under_test", root / "scripts" / "daemon.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["daemon_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _row(pid: int, command: str, *, rss_mb: int = 100, age_s: int = 7200, ppid: int = 1):
    return rg.ProcRow(
        pid=pid, ppid=ppid, rss_kb=rss_mb * 1024, etime_s=age_s, command=command
    )


def _probe(attributed: set[int]):
    """An env_probe that reports the given pids as Claude-attributed."""
    return lambda pid: pid in attributed


def _owner_probe(owners: dict[int, int]):
    """An owner_probe that reports the given pids' CLAUDE_PID owner pid.

    A pid that is not in the map has NO owner pointer — the value None
    the real `read_claude_pid` returns for a process that carries no
    `CLAUDE_PID` token.
    """
    return lambda pid: owners.get(pid)


def _liveness_probe(names: dict[int, str]):
    """A liveness_probe reporting the given pids PRESENT under those names.

    A pid that is not in the map is ABSENT — the value None the real
    `read_owner_comm` returns for a pid that is not in the process table.
    """
    return lambda pid: names.get(pid)


# ---------- the pressure probe ---------------------------------------------

def test_the_pressure_state_never_reaches_critical_on_unknown_readings() -> None:
    """Missing data is a NO-OP, never a kill.

    A probe that cannot read swap must not read the host as critical,
    because "critical" arms the kill path.
    """
    pressure = rg.Pressure(
        state="healthy", free_mb=8192, swap_used_mb=None, swap_total_mb=None,
        swap_pct=None, swapfiles=None, compressor_pct=None,
    )
    assert pressure.state == "healthy"
    assert "?" in pressure.readings()


def test_parse_swapusage_reads_the_measured_format() -> None:
    """The measured `sysctl -n vm.swapusage` format.

    MEASURED on this host:
        total = 8192.00M  used = 6715.00M  free = 1477.00M  (encrypted)
    The TOTAL matters as much as the used figure, because the total is
    what makes the RATIO meaningful — see `swap_ratio_pct`.
    """
    used, total, files = rg.parse_swapusage(
        "total = 4096.00M  used = 2048.50M  free = 2047.50M  (encrypted)"
    )
    assert used == 2048
    assert total == 4096
    assert files is None
    used_gb, total_gb, _ = rg.parse_swapusage(
        "total = 2.00G  used = 1.00G  free = 1.00G"
    )
    assert used_gb == 1024
    assert total_gb == 2048


def test_the_swap_signal_is_a_ratio_of_the_files_own_total() -> None:
    """WHY A RATIO AND NOT AN ABSOLUTE FIGURE — MEASURED.

    macOS keeps a swapfile full once it has grown, so a host that used
    swap once keeps it used. On the owner's host the swapfile is 8192 MB
    with 6715 MB used — 82% — and that was STABLE across a minute of
    sampling on a day the host was entirely healthy (free memory
    22104 MB, compressor ~1% of physical RAM).

    So an absolute "swap used" bar of 2048 MB is crossed by this host's
    NORMAL operating point, and a guard armed with it would be
    permanently critical and would kill a process every minute. The
    ratio measures how much of the FILE is consumed, which is the only
    figure that scales with a swapfile that has grown.
    """
    assert rg.swap_ratio_pct(6715, 8192) == 81
    assert rg.swap_ratio_pct(2048, 8192) == 25
    # An unknown or zero total is UNKNOWN, never zero: "no swapfile" is
    # not "no swap pressure".
    assert rg.swap_ratio_pct(6715, None) is None
    assert rg.swap_ratio_pct(6715, 0) is None
    assert rg.swap_ratio_pct(None, 8192) is None


def test_a_healthy_host_with_a_full_swapfile_is_not_critical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE CALIBRATION, AS AN EXECUTABLE FACT.

    This host's measured healthy state: free 22104 MB, swap 6715 MB of
    an 8192 MB file (82%), compressor ~1%. With the shipped thresholds
    that state must read HEALTHY — an absolute swap bar would have read
    it CRITICAL and the guard would have killed a process every minute
    on a perfectly healthy machine.
    """
    monkeypatch.setattr(rg, "free_memory_mb", lambda: 22104)
    monkeypatch.setattr(rg, "read_swap", lambda: (6715, 8192, None))
    monkeypatch.setattr(rg, "read_compressor_pct", lambda: 1)
    # The SEGMENT-POOL reading is stubbed too, because it is a LIVE
    # sysctl reading: leaving it real makes the test's verdict a
    # property of the host's current compressor state rather than of
    # the code. MEASURED on the owner host it ranged over 12%..53%
    # within a single minute -- enough to flip `healthy` to `elevated`
    # on its own. (A-7/A-8's segment arm is CORRECT and is left alone;
    # it is only the TEST's dependency on the live host that is fixed.)
    monkeypatch.setattr(rg, "read_compressor_segment_pct", lambda: 1)
    pressure = rg.host_pressure(
        min_free_mb=1024, swap_pct_bar=95, swapfiles=32, compressor_pct=60,
        # The segment bar is PINNED here, because the default is read
        # from the user's plugin option -- a value on THIS host that the
        # test must not depend on.
        compressor_segment_pct=90,
    )
    # NOT CRITICAL — the kill path must not arm. `elevated` is the
    # correct answer here rather than `healthy`: this host's swapfile
    # is 80% consumed, which is over the WARNING bar, and a host whose
    # swapfile is nearly full IS worth reporting even though it is not
    # dying. What matters for the safety of the feature is that the
    # kill path does not arm, and `elevated` does not arm it.
    assert pressure.state == "elevated", pressure.readings()
    assert pressure.state != "critical"
    assert pressure.swap_pct == 81


def test_parse_compressor_pct_computes_from_the_measured_reading() -> None:
    """`Pages occupied by compressor` is the reading that costs physical RAM."""
    text = "Pages occupied by compressor: 1869016.\nPages free: 14084.\n"
    # 1869016 pages * 16384 bytes = ~28.5 GiB of a 65536 MB host.
    pct = rg.parse_compressor_pct(text, total_mb=65536, page_size=16384)
    assert pct is not None
    assert 40 < pct < 50
    assert rg.parse_compressor_pct("nothing here", 65536, 16384) is None


# ---------- the safety rules -----------------------------------------------

def test_an_interactive_claude_session_is_never_the_victim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE LOAD-BEARING SAFETY TEST.

    The user's own session is the largest `claude`-shaped process on the
    host, and killing the session the user is typing into is the single
    most likely harm of this whole feature. Even when it is 10x bigger
    than everything else AND carries the Claude environment signal, it
    must not be selected.

    WHY THE ALLOWLIST IS WIDENED IN THIS TEST, and it is the whole point.
    With the shipped allowlist, a bare `claude` matches NO shape, so the
    shape clause would reject the session even if the interactive clause
    were deleted — and the test would pass while proving nothing. That
    is the vacuous-test shape this codebase has been bitten by nine
    times: a test that cannot fail against its defect is worse than no
    test. So the test widens the allowlist to a pattern a bare
    `claude` DOES match, which makes the interactive clause the ONLY
    thing standing between the user's session and the kill path. Delete
    that clause and this test fails.

    The widened pattern is also the REAL risk the clause exists for: the
    allowlist is a list someone will extend, and one day a pattern will
    match an interactive session.
    """
    monkeypatch.setattr(
        rg, "RUNAWAY_SHAPES", rg.RUNAWAY_SHAPES + (re.compile(r"\bclaude\b"),)
    )
    session = _row(
        100, "claude --continue --add-dir /tmp --dangerously-skip-permissions",
        rss_mb=9000,
    )
    assert rg.is_interactive_claude(session.command)
    victim = rg.select_victim(
        [session],
        protected_pids=frozenset(),
        min_etime_s=60,
        ancestry={},
        env_probe=_probe({100}),
    )
    assert victim is None, "an interactive claude session was selected as a victim"


def test_a_codex_or_copilot_or_lmstudio_process_is_never_the_victim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The owner's directive: do not touch other AI clients.

    The forbidden process here even has a `claude` ANCESTOR and the
    Claude environment signal — two independent attributions — and is
    still refused, because the exclusion is by SHAPE and unconditional.

    THE ALLOWLIST IS WIDENED FOR THE SAME REASON as the test above: with
    the shipped allowlist a `codex` command matches no shape, so the
    shape clause would refuse it on its own and the test would pass
    while proving nothing about the forbidden-client clause. Widening
    the allowlist to match `codex` makes the forbidden-client clause the
    only thing that can refuse it.
    """
    monkeypatch.setattr(
        rg, "RUNAWAY_SHAPES", rg.RUNAWAY_SHAPES + (re.compile(r"\bcodex\b", re.IGNORECASE),)
    )
    for pid, cmd in (
        (200, "codex --serve"),
        (201, "copilot-agent run"),
        (202, "lm-studio server"),
        (203, "aider --model gpt"),
        (204, "cursor-agent"),
    ):
        row = _row(pid, cmd, rss_mb=8000)
        victim = rg.select_victim(
            [row],
            protected_pids=frozenset(),
            min_etime_s=60,
            ancestry={pid: (999, "claude --continue")},
            env_probe=_probe({pid}),
        )
        assert victim is None, f"{cmd} was selected as a victim"


def test_the_janitors_own_daemon_is_never_the_victim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The janitor's daemon and its launchd agent are protected.

    A janitor that kills itself is worse than one that does nothing.
    The protected set is the caller's job, but the guard must honour it.

    THE ALLOWLIST IS WIDENED HERE TOO, for the same reason as the two
    tests above: `python3 scripts/daemon.py` matches no shipped runaway
    shape, so the shape clause would refuse it on its own and the test
    would pass while proving nothing about the protected-pid clause.
    Widening the allowlist to match the daemon's own command line makes
    the protected-pid clause the only thing that can refuse it.
    """
    monkeypatch.setattr(
        rg, "RUNAWAY_SHAPES", rg.RUNAWAY_SHAPES + (re.compile(r"scripts/daemon\.py"),)
    )
    daemon = _row(300, "python3 scripts/daemon.py", rss_mb=500)
    victim = rg.select_victim(
        [daemon],
        protected_pids=frozenset({300}),
        min_etime_s=60,
        ancestry={},
        env_probe=_probe({300}),
    )
    assert victim is None


def test_an_attributed_process_outside_the_shape_allowlist_is_not_a_victim() -> None:
    """Attribution proves RELATEDNESS, never KILL-WORTHINESS.

    A dev server the user started inside a Claude session is attributed
    and enormous, and is still not a runaway — it is the user's work.
    """
    dev_server = _row(400, "node /srv/project/node_modules/.bin/vite", rss_mb=6000)
    assert rg.has_claude_env.__doc__ is not None  # the env channel is the point
    victim = rg.select_victim(
        [dev_server],
        protected_pids=frozenset(),
        min_etime_s=60,
        ancestry={400: (999, "claude --continue")},
        env_probe=_probe({400}),
    )
    assert victim is None


def test_a_process_with_no_claude_signal_at_all_is_not_a_victim() -> None:
    """Not attributed = not killable, even when it is the biggest process.

    This is the iOS Simulator class: 166 runnable processes, enormous,
    and not the janitor's business.
    """
    sim = _row(
        500,
        "/Library/Developer/CoreSimulator/Volumes/iOS_21A328/Library/x",
        rss_mb=7000,
    )
    victim = rg.select_victim(
        [sim],
        protected_pids=frozenset(),
        min_etime_s=60,
        ancestry={},
        env_probe=_probe(set()),
    )
    assert victim is None


def test_the_environment_signal_is_detected_on_a_reparented_process() -> None:
    """The case ancestry alone misses: ppid=1, the session long gone.

    An abandoned watcher is by definition a reparented process, so if
    attribution were ancestry-only the janitor could never catch the
    exact class of runaway it was built for. The env probe is consulted
    FIRST and independently of the ancestry table.

    THE ANCESTRY TABLE NOW CARRIES THE CANDIDATE'S OWN DEAD-ENDED ROW
    (600 -> launchd). That is not decoration: the table's ABSENCE cannot
    make a process abandoned (see
    `test_an_empty_ancestry_table_never_makes_a_process_abandoned`), so
    a table that does not mention the candidate at all makes it
    UNKILLABLE. This is the reparented-orphan case, where the chain
    genuinely dead-ends at launchd.

    WHAT CHANGED WITH THE A-1 POLARITY FIX, and it is the point of the
    rewrite: under the old rule "abandoned" was the NEGATION of the
    attribution channel, so a reparented process with NO claude ancestor
    was abandoned BY CONSTRUCTION — the ancestry channel was structurally
    incapable of producing a kill, because attributing by ancestry and
    refusing by ancestry were the same test. Under the new rule the
    process must be abandoned by a POSITIVE statement about its owner:
    it carries a `CLAUDE_PID` pointer, and that pointer's target is
    PROVABLY DEAD. The owner pid here (20716) is one MEASURED on the
    owner host as ABSENT from the process table while its four
    descendants kept running.
    """
    row = _row(600, "node /tmp/peak-space/watch.mjs x", rss_mb=300, ppid=1)
    ancestry = {600: (1, "launchd")}
    assert rg.claude_ancestor(600, ancestry) is None, (
        "ancestry alone must find no claude ancestor for a reparented process"
    )
    dead_owner = 20716
    assert rg.is_abandoned(
        row,
        ancestry,
        owner_probe=_owner_probe({600: dead_owner}),
        liveness_probe=_liveness_probe({}),  # the owner pid is ABSENT
    ), (
        "a reparented process whose owner pointer names a PROVABLY DEAD "
        "session IS abandoned"
    )
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=60,
        ancestry=ancestry,
        env_probe=_probe({600}),
        owner_probe=_owner_probe({600: dead_owner}),
        liveness_probe=_liveness_probe({}),
    )
    assert victim is not None


def test_at_most_one_victim_is_selected_per_call() -> None:
    """One kill per beat, so a transient misread cannot become a spree."""
    rows = [
        _row(700, "node /opt/homebrew/bin/agentlenspro statusline --inner x", rss_mb=500),
        _row(701, "node /opt/homebrew/bin/agentlenspro statusline --inner y", rss_mb=400),
        _row(702, "node /opt/homebrew/bin/agentlenspro statusline --inner z", rss_mb=300),
    ]
    # Each row's OWN chain dead-ends at launchd — three orphans. Under
    # the A-1 polarity fix, "orphaned" is a POSITIVE statement: each
    # carries a `CLAUDE_PID` pointer at an owner pid that is ABSENT from
    # the process table, so each is provably abandoned.
    ancestry = {
        700: (1, "launchd"),
        701: (1, "launchd"),
        702: (1, "launchd"),
    }
    victim = rg.select_victim(
        rows, protected_pids=frozenset(), min_etime_s=60, ancestry=ancestry,
        env_probe=_probe({700, 701, 702}),
        owner_probe=_owner_probe({700: 20716, 701: 20716, 702: 20716}),
        liveness_probe=_liveness_probe({}),
    )
    assert victim is not None
    assert victim.pid == 700, "the LARGEST killable row must win"


def test_a_young_process_is_not_a_victim() -> None:
    """The age gate: a legitimately-running workload that is merely slow."""
    row = _row(800, "node /opt/homebrew/bin/agentlenspro statusline --inner x", age_s=10)
    victim = rg.select_victim(
        [row], protected_pids=frozenset(), min_etime_s=3600, ancestry={},
        env_probe=_probe({800}),
    )
    assert victim is None


def test_the_interactive_check_does_not_depend_on_the_allowlist_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The interactive-session rule must not be able to change by accident.

    It used to be `not any(sig.search(cmd) for sig in RUNAWAY_SHAPES[:3])`
    — a POSITIONAL SLICE of the runaway-shape allowlist. That made the
    rule that stands between the user and the killing of their own
    session depend on the ORDER OF A LITERAL: inserting a pattern before
    index 3 would silently redefine "interactive", with no comment saying
    the order mattered.

    MEASURED as a surviving mutation: changing `RUNAWAY_SHAPES[:3]` to
    `RUNAWAY_SHAPES[:1]` left the ENTIRE suite green. A rule that
    important cannot rest on a tuple's order, so it now names its own
    patterns (`CLAUDE_PLUGIN_SUBCOMMAND`).

    This test pins that independence: with the allowlist rewritten so a
    bare-`claude` pattern comes FIRST, the interactive check must still
    hold. It fails against the old positional form.
    """
    monkeypatch.setattr(
        rg, "RUNAWAY_SHAPES", (re.compile(r"\bclaude\b"),) + rg.RUNAWAY_SHAPES
    )
    assert rg.is_interactive_claude("claude --continue --add-dir /tmp")
    assert rg.is_interactive_claude("claude --resume")
    # The plugin subcommands are the ONLY exemption, and they still work.
    assert not rg.is_interactive_claude("claude plugin update ai-maestro-plugin")


def test_the_interactive_session_is_refused_even_when_the_allowlist_matches_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule that stands between the user and the kill path.

    A bare `claude` matches no shipped runaway shape, so with the shipped
    allowlist the shape clause would refuse it on its own and a test
    would prove nothing. The allowlist is widened here so the
    interactive clause is the ONLY thing that can refuse it.
    """
    monkeypatch.setattr(
        rg, "RUNAWAY_SHAPES", rg.RUNAWAY_SHAPES + (re.compile(r"\bclaude\b"),)
    )
    session = _row(100, "claude --continue --add-dir /tmp", rss_mb=9000)
    victim = rg.select_victim(
        [session], protected_pids=frozenset(), min_etime_s=60,
        ancestry={}, env_probe=_probe({100}),
    )
    assert victim is None


def test_the_pressure_state_machine_reaches_critical_on_swap_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The state function itself, not a Pressure object built by hand.

    The card's clause 2: a host can be dying of SWAP while free memory
    looks fine. The 2026-10-20 panic log said "Compressor Info: 100% of
    segments limit (BAD), 69 swapfiles" — a free-memory-only probe read
    that host as HEALTHY.

    The earlier version of this test constructed a `rg.Pressure` with
    state="critical" and then asserted the object said what it was built
    to say — it never called `host_pressure` at all, so inverting the
    entire state machine would have left it green. This one drives the
    real function with the readings stubbed, so the STATE COMPUTATION is
    what is under test.
    """
    monkeypatch.setattr(rg, "free_memory_mb", lambda: 8192)      # healthy free RAM
    monkeypatch.setattr(rg, "read_swap", lambda: (8192, 8192, 69))  # swap exhausted
    monkeypatch.setattr(rg, "read_compressor_pct", lambda: 95)   # compressor at the wall
    # The SEGMENT-POOL reading is stubbed too, because it is a LIVE
    # sysctl reading: leaving it real makes the test's verdict a
    # property of the host's current compressor state rather than of
    # the code. MEASURED on the owner host it ranged over 12%..53%
    # within a single minute -- enough to flip `healthy` to `elevated`
    # on its own. (A-7/A-8's segment arm is CORRECT and is left alone;
    # it is only the TEST's dependency on the live host that is fixed.)
    monkeypatch.setattr(rg, "read_compressor_segment_pct", lambda: 1)
    pressure = rg.host_pressure(
        min_free_mb=1024, swap_pct_bar=95, swapfiles=32, compressor_pct=60,
        # The segment bar is PINNED here, because the default is read
        # from the user's plugin option -- a value on THIS host that the
        # test must not depend on.
        compressor_segment_pct=90,
    )
    assert pressure.state == "critical", pressure.readings()
    assert pressure.free_mb == 8192
    assert pressure.swap_used_mb == 8192


def test_the_pressure_state_machine_reaches_critical_when_free_memory_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A FAILED memory read must not make the guard stand down.

    `host_pressure` requires the free-memory reading to be bad before it
    will call the host critical — so on a host where `vm_stat` failed
    (the call most likely to fail under memory pressure!) a swap-exhausted
    host would read as merely elevated and the guard would not act. The
    condition must be a disjunction over the KNOWN bad readings, with
    free memory as one arm rather than the gate on all of them.
    """
    monkeypatch.setattr(rg, "free_memory_mb", lambda: None)      # the read FAILED
    monkeypatch.setattr(rg, "read_swap", lambda: (8192, 8192, 69))  # swap exhausted
    monkeypatch.setattr(rg, "read_compressor_pct", lambda: 95)
    # The SEGMENT-POOL reading is stubbed too, because it is a LIVE
    # sysctl reading: leaving it real makes the test's verdict a
    # property of the host's current compressor state rather than of
    # the code. MEASURED on the owner host it ranged over 12%..53%
    # within a single minute -- enough to flip `healthy` to `elevated`
    # on its own. (A-7/A-8's segment arm is CORRECT and is left alone;
    # it is only the TEST's dependency on the live host that is fixed.)
    monkeypatch.setattr(rg, "read_compressor_segment_pct", lambda: 1)
    pressure = rg.host_pressure(
        min_free_mb=1024, swap_pct_bar=95, swapfiles=32, compressor_pct=60,
        # The segment bar is PINNED here, because the default is read
        # from the user's plugin option -- a value on THIS host that the
        # test must not depend on.
        compressor_segment_pct=90,
    )
    assert pressure.state == "critical", (
        "a failed free-memory read must not stand the guard down on a "
        f"swap-exhausted host (state={pressure.state})"
    )


def test_the_pressure_state_machine_never_reaches_critical_on_unknown_readings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing data is a NO-OP: "critical" arms the kill path."""
    monkeypatch.setattr(rg, "free_memory_mb", lambda: None)
    monkeypatch.setattr(rg, "read_swap", lambda: (None, None, None))
    monkeypatch.setattr(rg, "read_compressor_pct", lambda: None)
    # The SEGMENT-POOL reading is stubbed too, because it is a LIVE
    # sysctl reading: leaving it real makes the test's verdict a
    # property of the host's current compressor state rather than of
    # the code. MEASURED on the owner host it ranged over 12%..53%
    # within a single minute -- enough to flip `healthy` to `elevated`
    # on its own. (A-7/A-8's segment arm is CORRECT and is left alone;
    # it is only the TEST's dependency on the live host that is fixed.)
    # Here it is UNREADABLE, so the arm is UNKNOWN like the others.
    monkeypatch.setattr(rg, "read_compressor_segment_pct", lambda: None)
    pressure = rg.host_pressure()
    assert pressure.state == "healthy"
    assert "?" in pressure.readings()


def test_the_chore_does_nothing_when_the_option_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chore's OWN default-off guard, not the janitor's generic helper.

    The earlier version of this test asserted that `is_truthy_env`
    returns False for an absent variable — it tested the janitor's
    helper, and would have passed even if `task_runaway_guard` ignored
    the option entirely and always ran. This one drives the CHORE and
    asserts that it produces no snapshot and no kill record.
    """
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_RUNAWAY_GUARD_ENABLED", raising=False)
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    daemon = _load_daemon()
    daemon.task_runaway_guard()
    assert not (tmp_path / "runaway-guard.ps-snapshot.txt").exists(), (
        "the disabled chore took a process snapshot"
    )
    assert not (tmp_path / "runaway-alert.json").exists(), (
        "the disabled chore wrote a kill broadcast"
    )


def test_the_chore_acts_when_the_option_is_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The enabled chore REACHES the scan. It must not be a no-op.

    This is the other half of the default-off test: an option that is
    read but never acted on would pass the disabled test forever.
    """
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_RUNAWAY_GUARD_ENABLED", "1")
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_RUNAWAY_GUARD_SWAP_PCT", "0")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_RUNAWAY_GUARD_MIN_FREE_MB", "999999999")
    # THE KILLER MUST BE STUBBED. This test drives the real chore, which
    # reads the REAL process table — and the real table on this host holds
    # a LIVE pytest run belonging to another session. The project's own
    # sandbox guard blocked the signal when this test did it for real
    # (measured 2026-10-20: it tried to SIGTERM pid 29880, a live test
    # run in this very repo, 3716 s old — and the guard would have
    # selected it as the victim at the shipped 3600 s age gate).
    #
    # So a test that exercises the kill path MUST NOT be able to signal
    # a process it did not spawn. Stubbing the killer is the only way to
    # assert the path is reached without that risk.
    import runaway_guard as _rg
    monkeypatch.setattr(_rg, "kill_process", lambda pid, **kw: False)
    daemon = _load_daemon()
    daemon.task_runaway_guard()
    assert (tmp_path / "runaway-guard.ps-snapshot.txt").exists(), (
        "the enabled chore did not reach the process scan"
    )


def test_the_forbidden_client_check_matches_the_executable_form() -> None:
    """The `aider` exclusion was BROKEN, and the test missed it.

    The pattern was `\\b aider\\b` — a LEADING SPACE inside the word
    boundary — so it only matched `aider` when it appeared MID-STRING.
    MEASURED: 'aider --model x' -> not forbidden; '/usr/bin/aider' ->
    not forbidden; 'x aider y' -> forbidden. So the executable form of
    aider was never protected at all.

    The rule now matches the EXECUTABLE (argv[0]'s basename) or a path
    SEGMENT, so every spelling of a forbidden client is refused.
    """
    for cmd in (
        "aider --model x",
        "/usr/bin/aider",
        "/opt/homebrew/bin/codex",
        "node /opt/homebrew/lib/node_modules/@openai/codex/bin/codex.js",
        "copilot-agent run",
        "lm-studio server",
        "lm_studio --port",
        "cursor-agent",
        "late --continue-project",
        "/usr/local/bin/late",
    ):
        assert rg.is_forbidden_client(cmd), f"{cmd!r} was not recognised as a forbidden client"


def test_the_forbidden_client_check_does_not_match_a_bare_argument() -> None:
    """A FILENAME mentioning a client is not the client.

    `\bcodex\b` matched anywhere on the line, so
    `pytest tests/test_codex_pagination.py` was refused as a "forbidden
    client". Over-refusing is the safe direction for a kill, but a rule
    that is wrong for the wrong reason gets "fixed" into being wrong the
    other way.
    """
    for cmd in (
        "pytest tests/test_codex_pagination.py",
        "node /srv/project/src/copilot-client.js",
        "/srv/data/aider-notes.md",
        "pytest tests/test_late_client.py",
        "/srv/data/late-notes.md",
    ):
        assert not rg.is_forbidden_client(cmd), f"{cmd!r} was wrongly refused"


def test_the_forbidden_client_clause_refuses_aider_when_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The clause under test must be the ONLY thing that can refuse it.

    The earlier version of this test widened the allowlist to `codex`
    only, so `aider --model gpt` matched no shape and was refused by
    the SHAPE clause — the forbidden-client clause was never exercised,
    which is how the broken `aider` pattern survived a green suite.
    """
    monkeypatch.setattr(
        rg, "RUNAWAY_SHAPES", rg.RUNAWAY_SHAPES + (re.compile(r"\baider\b", re.IGNORECASE),)
    )
    row = _row(205, "aider --model gpt", rss_mb=8000)
    victim = rg.select_victim(
        [row], protected_pids=frozenset(), min_etime_s=60,
        ancestry={205: (999, "claude --continue")}, env_probe=_probe({205}),
    )
    assert victim is None, "aider was selected as a victim"


def test_the_env_probe_requires_a_name_equals_value_token(tmp_path: Path) -> None:
    """A bare word in the COMMAND LINE is not an environment variable.

    `ps eww` returns the argv and the environment concatenated with no
    separator, so a probe that scanned for the marker's NAME anywhere
    credited any process whose command line merely MENTIONED the string.
    MEASURED on this host: a `grep` whose own pattern was
    `CLAUDECODE|CLAUDE_PROJECT_DIR` came back as a token containing
    `CLAUDECODE` — from the argv, not from any environment.

    So the probe must require the `NAME=value` form, and the ARGV must
    not be able to fake it.
    """
    import os as _os
    import subprocess as _subprocess
    import sys as _sys

    if not hasattr(_os, "fork"):
        pytest.skip("needs a POSIX fork")
    # A child whose ARGV mentions the marker but whose ENVIRONMENT does
    # not carry it.
    env = {k: v for k, v in _os.environ.items() if k not in rg.CLAUDE_ENV_MARKERS}
    env["MY_MARKER_VAR"] = "hello"
    child = _subprocess.Popen(
        [_sys.executable, "-c", "import time; time.sleep(30)", "CLAUDECODE"],
        env=env,
    )
    try:
        import time as _time
        _time.sleep(0.4)
        assert not rg.has_claude_env(child.pid), (
            "a process whose ARGV merely mentions the marker was credited "
            "as agent-started"
        )
    finally:
        child.kill()
        child.wait()


def test_a_process_attributable_only_by_a_claude_ancestor_is_not_selected() -> None:
    """THE ANCESTRY CHANNEL, EXERCISED — AND WHAT IT NOW MEANS.

    THE ANCESTRY CHANNEL IS NO LONGER STRUCTURALLY INCAPABLE OF A KILL,
    and that is the whole point of the A-1 polarity fix. Under the old
    rule the two clauses were exact complements — the ancestry channel
    attributed a process by finding a `claude` ancestor, and the
    abandonment rule refused a process by finding NO `claude` ancestor —
    so a process attributed BY ancestry could, by construction, never be
    a victim. The channel meant to catch a reparented orphan was the
    same channel the rule used to exclude it.

    Under the new rule, abandonment is a POSITIVE statement about the
    owner: the owner is IDENTIFIED (by the `CLAUDE_PID` pointer, or else
    by the claude-family ancestor) and PROVABLY DEAD. So the ancestry
    channel can now attribute a process AND find its owner, and if that
    owner turns out to be dead, the process is abandoned.

    THIS TEST STILL ASSERTS A REFUSAL, and the refusal is now for a
    DIFFERENT and STRONGER reason: the ancestor it finds is ALIVE. The
    live-session refusal is the load-bearing safety property, and it is
    exactly what the old test was really about.
    """
    row = _row(900, "node /opt/homebrew/bin/agentlenspro statusline --inner x",
               rss_mb=400)
    # The table maps EVERY pid to (ppid, command) INCLUDING the process
    # itself — the walk starts at the process's own row.
    ancestry = {
        900: (901, "node /opt/homebrew/bin/agentlenspro statusline --inner x"),
        901: (902, "claude --continue --add-dir /tmp"),
    }
    # The ancestry channel still SEES the claude ancestor — that part of
    # the rule is unchanged and is pinned here. The pid it returns is
    # the process whose PARENT is the `claude` session (the nearest
    # ancestor in the chain), which is the walk's own contract.
    assert rg.claude_ancestor(900, ancestry) == 901, (
        "the ancestry channel stopped finding the claude ancestor"
    )
    # ... and because that ancestor is ALIVE, the process is not
    # abandoned, so it is not a victim.
    assert not rg.is_abandoned(
        row, ancestry, liveness_probe=_liveness_probe({901: "claude"})
    ), (
        "a process whose claude session ancestor is alive is not abandoned"
    )
    # The env channel says NO — only the ancestry could attribute it.
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=60,
        ancestry=ancestry,
        env_probe=_probe(set()),
        owner_probe=_owner_probe({}),
        liveness_probe=_liveness_probe({901: "claude"}),
    )
    assert victim is None, (
        "a process attributable only by a LIVE claude ancestor was selected; "
        "the abandonment rule must refuse it"
    )


def test_a_process_with_neither_env_nor_ancestor_is_not_selected() -> None:
    """The other half: attribution must be REQUIRED, not merely sufficient.

    The env channel says NO and there is no claude ancestor, so the
    process is not attributable and must not be a victim — even though
    it matches an allowlisted shape and is enormous. This is the pair
    that makes the ancestry channel a real rule rather than a
    decoration.
    """
    row = _row(901, "node /opt/homebrew/bin/agentlenspro statusline --inner x",
               rss_mb=400)
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=60,
        ancestry={
            901: (902, "node /opt/homebrew/bin/agentlenspro statusline --inner x"),
            902: (903, "/bin/zsh"),
        },
        env_probe=_probe(set()),
    )
    assert victim is None


# ---------- the second abandonment signal (TRDD-ZIKYQQY0 A-1) ---------------

def test_a_live_session_ancestor_makes_a_process_not_a_victim() -> None:
    """THE NEAR-MISS REGRESSION — the most important test in the change.

    MEASURED on the live host (2026-10-20): a test that drove the real
    chore against the real process table made the guard select pid
    29880 as its victim — a LIVE `pytest` run in this very repo, 5675 s
    old, belonging to ANOTHER session and running at that moment. The
    age gate was the ONLY thing standing between it and the kill path,
    and the age gate has no floor, so an owner who set it to 0 to "be
    more responsive" would have had the janitor kill another session's
    running work.

    So the guard needs a SECOND, INDEPENDENT discriminator for
    "abandoned": the candidate's Claude owner must be PROVABLY DEAD. A
    live `pytest` running inside a live session has a LIVE owner.

    THE CLAUSE UNDER TEST MUST BE THE ONLY ONE THAT CAN REFUSE THE
    SUBJECT. So every earlier clause is made to PASS:

      * the SHAPE allowlist matches (the command is a `pytest` path, so
        the shipped `(?:^|/)pytest\\b` shape matches it);
      * the AGE GATE passes — the age is far above the floor, and the
        knob is passed as 0 to prove the rule does not depend on it;
      * ATTRIBUTION passes — the env probe says YES;
      * the process is not protected and is not a forbidden client and
        is not an interactive `claude` session.

    The ONLY thing left to refuse it is the abandonment clause. Delete
    that clause and this test fails.

    THE OWNER IS EXPLICIT HERE, not inferred from the tree: the process
    carries a `CLAUDE_PID` pointer at pid 91163, and the liveness probe
    reports 91163 PRESENT under the name `claude`. MEASURED on the
    owner host: pid 91163 is one of the nine owner pids that point at a
    live process whose `comm` is exactly `claude`.
    """
    pid = 29880
    row = _row(pid, "/srv/proj/.venv/bin/pytest -q", rss_mb=440, age_s=5675, ppid=29811)
    # The chain MEASURED on the live host: 29880 -> 29811 -> 29775 ->
    # 91163, and 91163 is a live `claude --continue` session.
    ancestry = {
        pid: (29811, "/srv/proj/.venv/bin/pytest -q"),
        29811: (29775, "/bin/zsh -c uv run pytest -q"),
        29775: (91163, "claude --continue --add-dir /tmp --dangerously-skip-permissions"),
    }
    # The shape clause must NOT be what refuses it.
    assert any(sig.search(row.command) for sig in rg.RUNAWAY_SHAPES), (
        "the subject does not match the runaway-shape allowlist, so the "
        "shape clause would refuse it and this test would prove nothing"
    )
    # The age clause must NOT be what refuses it.
    assert row.etime_s >= rg.MIN_RUNAWAY_ETIME_S
    # The ancestry channel finds the live session — that is the fact
    # the whole rule turns on.
    assert rg.claude_ancestor(pid, ancestry) == 29775 or rg.claude_ancestor(
        pid, ancestry
    ) is not None
    live_owner = 91163
    assert not rg.is_abandoned(
        row,
        ancestry,
        owner_probe=_owner_probe({pid: live_owner}),
        liveness_probe=_liveness_probe({live_owner: "claude"}),
    ), (
        "a process with a LIVE claude owner is not abandoned"
    )
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=0,  # the knob, relaxed to nothing
        ancestry=ancestry,
        env_probe=_probe({pid}),
        owner_probe=_owner_probe({pid: live_owner}),
        liveness_probe=_liveness_probe({live_owner: "claude"}),
    )
    assert victim is None, (
        "a LIVE other-session process was selected as a victim; the "
        "abandonment rule must refuse it"
    )


def test_an_orphaned_process_with_no_session_ancestor_is_still_a_victim() -> None:
    """THE COMPLEMENT: the new rule must not simply disable the guard.

    The same subject as the test above, with the ONE difference that
    matters — the chain dead-ends at launchd instead of reaching a live
    `claude`, and the owner pointer names an owner pid that is ABSENT
    from the process table. That is the genuinely orphaned shape the
    guard exists for, and it must still be selected.

    Every other clause passes for the same reasons as in the test above
    (shape matches, age gate passes with the knob at 0, env probe says
    YES), so the abandonment clause is the ONLY one that could refuse
    it — and here it must NOT.
    """
    pid = 29880
    row = _row(pid, "/srv/proj/.venv/bin/pytest -q", rss_mb=440, age_s=5675, ppid=1)
    # A reparented orphan: its session is gone, so the chain dead-ends
    # at launchd and there is no claude ancestor to find.
    ancestry = {pid: (1, "launchd")}
    assert rg.claude_ancestor(pid, ancestry) is None
    dead_owner = 20716
    assert rg.is_abandoned(
        row,
        ancestry,
        owner_probe=_owner_probe({pid: dead_owner}),
        liveness_probe=_liveness_probe({}),
    ), (
        "a reparented process whose owner pointer names a PROVABLY DEAD "
        "session IS abandoned"
    )
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=0,
        ancestry=ancestry,
        env_probe=_probe({pid}),
        owner_probe=_owner_probe({pid: dead_owner}),
        liveness_probe=_liveness_probe({}),
    )
    assert victim is not None, (
        "a genuinely orphaned, shape-matching, attributed process was NOT "
        "selected; the new rule must not disable the guard"
    )
    assert victim.pid == pid

def test_an_empty_ancestry_table_never_makes_a_process_abandoned() -> None:
    """THE SAFETY PROPERTY: "unknown" is never "abandoned".

    Under the A-1 polarity fix the ANCESTRY TABLE IS NO LONGER A
    NEGATIVE TEST, and the empty-table rule survives in a different
    form: an empty table means the ancestry FALLBACK cannot resolve an
    owner, and the environment pointer still can. So the empty-table
    case is no longer "the table cannot speak" but "the fallback
    channel is silent" — and the owner must come from somewhere else.

    HERE THE OWNER POINTER IS ALSO SILENT, so the owner is UNKNOWN and
    the process is not abandoned. The subject is otherwise a perfect
    victim: shape-matching, old enough, env-attributed, not protected,
    not forbidden, not an interactive session. So the UNKNOWN-owner
    clause is the ONLY thing that can refuse it.
    """
    pid = 1500
    row = _row(pid, "/srv/proj/.venv/bin/pytest -q", rss_mb=440, age_s=5675)
    assert not rg.is_abandoned(
        row, {}, owner_probe=_owner_probe({}), liveness_probe=_liveness_probe({})
    ), (
        "no owner could be identified; unknown must never mean abandoned"
    )
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=0,
        ancestry={},
        env_probe=_probe({pid}),
        owner_probe=_owner_probe({}),
        liveness_probe=_liveness_probe({}),
    )
    assert victim is None, (
        "a process was selected with an UNKNOWN owner — a failed snapshot "
        "must not make every attributed process killable"
    )


def test_a_process_absent_from_the_ancestry_table_is_not_abandoned() -> None:
    """THE PARTIAL-TABLE CASE: a table cannot speak for a pid it lacks.

    The table is not empty — it holds OTHER pids — but it does not hold
    the candidate's. A partial table knows nothing about that
    candidate's ancestry, so it cannot resolve an owner through the
    fallback channel. If it could, a table that lost a row would turn
    that row's process into a victim.

    This pins the partial-table case separately from the empty-table
    case: the table here is non-empty, so the empty-table guard does not
    fire and the membership question is the only thing that can leave
    the fallback channel silent.
    """
    pid = 1600
    row = _row(pid, "/srv/proj/.venv/bin/pytest -q", rss_mb=440, age_s=5675)
    partial = {9999: (1, "launchd")}
    assert partial, "the fixture table must be non-empty"
    assert pid not in partial
    assert not rg.is_abandoned(
        row, partial, owner_probe=_owner_probe({}), liveness_probe=_liveness_probe({})
    ), (
        "a process absent from a PARTIAL ancestry table was read as "
        "abandoned; the table cannot speak for a pid it does not hold"
    )
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=0,
        ancestry=partial,
        env_probe=_probe({pid}),
        owner_probe=_owner_probe({}),
        liveness_probe=_liveness_probe({}),
    )
    assert victim is None, (
        "a process absent from the ancestry table was selected as a victim"
    )
def test_the_age_gate_knob_cannot_be_lowered_below_the_floor() -> None:
    """A-0: the age gate has a FLOOR, and the knob cannot remove it.

    The knob existed with no lower bound, so `min_etime_s=0` — one
    mistyped option value away — turned the ONLY protection that
    another session's live work had into no protection at all. The gate
    may be RAISED, never LOWERED: a caller passing 0 gets the floor.

    The subject is otherwise a perfect victim (shape-matching,
    env-attributed, abandoned by a PROVABLY DEAD owner, not protected,
    not forbidden, not an interactive session), so the age clause is the
    ONLY thing that can refuse it.
    """
    pid = 1700
    row = _row(pid, "/srv/proj/.venv/bin/pytest -q", rss_mb=440, age_s=10, ppid=1)
    ancestry = {pid: (1, "launchd")}
    dead_owner = 20716
    assert rg.is_abandoned(
        row,
        ancestry,
        owner_probe=_owner_probe({pid: dead_owner}),
        liveness_probe=_liveness_probe({}),
    )
    assert row.etime_s < rg.MIN_RUNAWAY_ETIME_S
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=0,  # the knob, lowered to nothing
        ancestry=ancestry,
        env_probe=_probe({pid}),
        owner_probe=_owner_probe({pid: dead_owner}),
        liveness_probe=_liveness_probe({}),
    )
    assert victim is None, (
        "a 10-second-old process was selected with the age gate at 0; the "
        "gate has a floor"
    )
    # AND the floor does not raise the gate above a legitimate value: a
    # caller that asks for MORE than the floor still gets what it asked
    # for.
    old = _row(pid + 1, "/srv/proj/.venv/bin/pytest -q", rss_mb=440, age_s=10_000, ppid=1)
    victim = rg.select_victim(
        [old],
        protected_pids=frozenset(),
        min_etime_s=5_000,
        ancestry={pid + 1: (1, "launchd")},
        env_probe=_probe({pid + 1}),
        owner_probe=_owner_probe({pid + 1: dead_owner}),
        liveness_probe=_liveness_probe({}),
    )
    assert victim is not None, "a caller asking for MORE than the floor was not honoured"
    assert victim.pid == pid + 1
    assert victim is not None, "a caller asking for MORE than the floor was not honoured"
    assert victim.pid == pid + 1


def test_a_forbidden_client_reached_through_a_launcher_is_recognised() -> None:
    """`npx codex` IS a forbidden client.

    The executable check alone misses it, because `codex` is neither
    argv[0] nor a path segment there — it is the word after a
    launcher. A rule that a different spelling gets past is a rule with
    a hole, not a stricter rule, and `npx codex` is a plausible way to
    start the Codex CLI.
    """
    for cmd in ("npx codex", "uvx codex", "bunx aider", "npx --yes @openai/codex"):
        assert rg.is_forbidden_client(cmd), f"{cmd!r} was not recognised"


def test_a_forbidden_client_name_inside_a_filename_is_not_the_client() -> None:
    """The over-refusing direction must still be closed.

    `pytest tests/test_codex_pagination.py` is not a forbidden client —
    `codex` there is a SUBSTRING of a filename, not a name. Over-
    refusing is the safe direction for a kill, but a rule that is wrong
    for the wrong reason gets "fixed" into being wrong the other way,
    so both directions are pinned.
    """
    for cmd in (
        "pytest tests/test_codex_pagination.py",
        "pytest /srv/codex-fixtures/test_a.py",
        "node /srv/project/src/copilot-client.js",
        "/srv/data/aider-notes.md",
    ):
        assert not rg.is_forbidden_client(cmd), f"{cmd!r} was wrongly refused"


def test_the_swap_ratio_is_what_the_state_machine_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE CALIBRATED SIGNAL IS THE ONE THAT ARMS THE KILL PATH.

    MEASURED on the owner's host: the swapfile is 8192 MB with 6715 MB
    used — 82% — and STABLE across a minute of sampling on a day the
    host was entirely healthy, because macOS keeps a swapfile full once
    it has grown. An absolute "swap used" bar is therefore crossed by
    this host's NORMAL operating point.

    So the state machine must use the RATIO, and a swap reading that is
    over the absolute figure but under the ratio must NOT arm the kill
    path. This test pins that the ratio is the input — removing it
    fails here.

    HOST-INDEPENDENT BY CONSTRUCTION: every probe is stubbed with the
    MEASURED figures above, so the outcome is a property of the state
    machine, not of the machine the suite happens to run on. The
    previous version of this test read the LIVE host's free memory and
    swap, and it failed on the owner's host at 430 MB free — a test
    that fails on a healthy machine because the machine is busy is a
    test of the machine, not of the code.
    """
    # The MEASURED healthy operating point: 6715 MB used of an 8192 MB
    # swapfile is 82% — a working host — while 6715 MB in absolute
    # terms is over any plausible absolute bar. So a guard keyed on
    # the raw figure would be permanently critical here and would kill
    # a process every minute.
    monkeypatch.setattr(rg, "free_memory_mb", lambda: 22104)
    monkeypatch.setattr(rg, "read_swap", lambda: (6715, 8192, None))
    monkeypatch.setattr(rg, "read_compressor_pct", lambda: 1)
    monkeypatch.setattr(rg, "read_compressor_segment_pct", lambda: 1)

    used, total, _files = rg.read_swap()
    assert used is not None, "the stubbed swap probe returned no reading"
    assert total is not None, "the stubbed swap TOTAL could not be read"
    ratio = rg.swap_ratio_pct(used, total)
    assert ratio is not None
    # The ratio is what the ratio helper computes.
    assert ratio == int(used * 100 / total)

    # THE PIN: the same 82% reading must NOT arm the kill path at a 95%
    # ratio bar, and MUST arm it at an 80% bar. Both directions are
    # stubbed, so neither depends on the host's state at run time.
    healthy = rg.host_pressure(
        min_free_mb=1024,
        swap_pct_bar=95,
        swapfiles=32,
        compressor_pct=60,
        compressor_segment_pct=90,
    )
    assert healthy.state != "critical", (
        f"an 82% swap ratio armed the kill path at a 95% bar: "
        f"{healthy.readings()}"
    )

    exhausted = rg.host_pressure(
        min_free_mb=1024,
        swap_pct_bar=80,
        swapfiles=32,
        compressor_pct=60,
        compressor_segment_pct=90,
    )
    assert exhausted.state == "critical", (
        f"an 82% swap ratio did NOT arm the kill path at an 80% bar: "
        f"{exhausted.readings()}"
    )


def test_the_swap_ratio_alone_can_arm_the_kill_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE RATIO IS AN ARM IN ITS OWN RIGHT, not a modifier.

    MEASURED: this host's swapfile is 8192 MB with 6715 MB used — 82%
    — and that is its NORMAL operating point, because macOS keeps a
    swapfile full once it has grown. So a ratio at 95% is reachable on
    a host in real trouble, and the ratio must be able to reach
    `critical` ON ITS OWN with free memory still healthy and the
    compressor still low. Otherwise the signal that matters is gated
    behind the other two, which is the blind spot the disjunction
    removed.
    """
    monkeypatch.setattr(rg, "free_memory_mb", lambda: 20000)
    monkeypatch.setattr(rg, "read_swap", lambda: (7900, 8192, None))  # 96%
    monkeypatch.setattr(rg, "read_compressor_pct", lambda: 5)
    # The SEGMENT-POOL reading is stubbed too, because it is a LIVE
    # sysctl reading: leaving it real makes the test's verdict a
    # property of the host's current compressor state rather than of
    # the code. MEASURED on the owner host it ranged over 12%..53%
    # within a single minute -- enough to flip `healthy` to `elevated`
    # on its own. (A-7/A-8's segment arm is CORRECT and is left alone;
    # it is only the TEST's dependency on the live host that is fixed.)
    monkeypatch.setattr(rg, "read_compressor_segment_pct", lambda: 5)
    pressure = rg.host_pressure(
        min_free_mb=1024, swap_pct_bar=95, swapfiles=32, compressor_pct=60,
        # The segment bar is PINNED here, because the default is read
        # from the user's plugin option -- a value on THIS host that the
        # test must not depend on.
        compressor_segment_pct=90,
    )
    assert pressure.state == "critical", pressure.readings()


def test_the_compressor_alone_can_arm_the_kill_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE COMPRESSOR'S SEGMENT POOL is the panic's own condition, and it
    must be able to arm the kill path on its own.

    The 2026-10-20 panic read 'Compressor Info: 100% of segments limit
    (BAD), 69 swapfiles' with free memory and swap both apparently
    survivable. So the compressor reading is the one that has to be
    able to say `critical` by itself, and it must not be gated behind
    the others.

    A-8: the quantity is the SEGMENT POOL
    (`vm.compressor.segment.total` over `vm.compressor.segment.limit`),
    which is the condition the panic log named — not the RAM
    percentage, which is only a proxy. So the segment reading is what
    is stubbed here, and the RAM proxy is stubbed HEALTHY to prove the
    arm is the segment pool's and not the proxy's.

    The fallback is pinned separately: the RAM proxy arms the arm when
    the segment sysctls are unavailable.
    """
    monkeypatch.setattr(rg, "free_memory_mb", lambda: 20000)
    monkeypatch.setattr(rg, "read_swap", lambda: (100, 8192, None))  # 1%
    monkeypatch.setattr(rg, "read_compressor_pct", lambda: 5)  # the proxy is FINE
    monkeypatch.setattr(rg, "read_compressor_segment_pct", lambda: 95)  # the pool is NOT
    pressure = rg.host_pressure(
        min_free_mb=1024, swap_pct_bar=95, swapfiles=32, compressor_pct=60,
        # The segment bar is PINNED here, because the default is read
        # from the user's plugin option -- a value on THIS host that the
        # test must not depend on.
        compressor_segment_pct=90,
    )
    assert pressure.state == "critical", pressure.readings()
    assert pressure.compressor_segment_pct == 95


def test_the_compressor_ram_proxy_arms_the_arm_when_the_segment_pool_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE FALLBACK: an UNKNOWN real quantity is not "fine".

    On a host whose segment sysctls do not exist, the RAM-percentage
    proxy is the only compressor reading there is, and it must still
    arm the kill path when it is bad. "The reading I could not take is
    fine" is not a fact; "the reading I could take is bad" is.
    """
    monkeypatch.setattr(rg, "free_memory_mb", lambda: 20000)
    monkeypatch.setattr(rg, "read_swap", lambda: (100, 8192, None))  # 1%
    monkeypatch.setattr(rg, "read_compressor_pct", lambda: 95)
    monkeypatch.setattr(rg, "read_compressor_segment_pct", lambda: None)  # UNREADABLE
    pressure = rg.host_pressure(
        min_free_mb=1024, swap_pct_bar=95, swapfiles=32, compressor_pct=60,
        # The segment bar is PINNED here, because the default is read
        # from the user's plugin option -- a value on THIS host that the
        # test must not depend on.
        compressor_segment_pct=90,
    )
    assert pressure.state == "critical", pressure.readings()


def test_a_forbidden_client_named_as_a_path_directory_is_still_refused() -> None:
    """THE OVER-REFUSING DIRECTION, PINNED.

    A path whose DIRECTORY component is exactly a forbidden name
    (`/srv/codex/test_a.py`) is refused. Over-refusing is the safe
    direction for a kill, and it is a deliberate choice: a directory
    named `codex` is far more likely to be a forbidden client's data
    directory than a coincidence. The rule is pinned so a later edit
    that narrows it has to do so on purpose.
    """
    assert rg.is_forbidden_client("pytest /srv/codex/test_a.py")
    # AND THE HONEST LIMIT: this rule is REDUNDANT with the basename
    # check, so removing the segment branch alone leaves the suite
    # green — MEASURED. The basename check already matches a word whose
    # last path component is a forbidden name, and `/srv/codex/test_a.py`
    # has `test_a.py` as its basename, so what the segment branch adds
    # is the DIRECTORY name. Pinning the directory case does not make
    # the branch necessary, it pins the BEHAVIOUR — and the behaviour is
    # what the safety of the kill path depends on.


# ---------- the broadcast --------------------------------------------------

def test_the_broadcast_payload_carries_no_project_path() -> None:
    """A kill record must not carry one project's content to another.

    The per-project channeling invariant (TRDD-X92VBFNF) forbids it, and
    a command line like `pytest /Volumes/.../other-project/tests` would
    carry exactly that. The broadcast carries the BASE NAME only.
    """
    record = ra.kill_record(
        pid=900,
        name="pytest",
        rss_mb=2100,
        age_s=7200,
        reason="host pressure critical",
        readings="free 100MB, swap 4096MB",
    )
    line = ra.format_line(record)
    assert "pytest" in line
    assert "/Volumes/" not in line
    assert "other-project" not in line
    assert "900" in line
    assert "2100" in line


def test_the_base_name_drops_the_whole_command_line() -> None:
    """The redaction is in the NAME, not in the message."""
    name = rg.base_name(
        "pytest /srv/some-other-project/tests/test_x.py"
    )
    assert name == "pytest"
    assert "some-other-project" not in name


def test_the_kill_line_is_descriptive_and_never_imperative() -> None:
    """It states what happened; it does not tell the reader what to do.

    This codebase has already been burned by imperative status lines
    being executed by autonomous readers.
    """
    record = ra.kill_record(
        pid=901, name="node", rss_mb=100, age_s=10, reason="host pressure critical",
        readings="free 1MB",
    )
    line = ra.format_line(record).lower()
    assert "killed" in line
    for imperative in ("please ", "you must", "run /", "should ", "kill the"):
        assert imperative not in line




# ---------- A-5: the dead code and the false docstring ----------------------

def test_the_alert_module_carries_no_dead_code() -> None:
    """A-5: `drift_parts`, `REPEAT_S` and `MAX_MSG_CHARS` are GONE.

    All three were dead:

      * `drift_parts` was never called — the dispatch phase calls
        `pending_kills` directly — and its docstring described a
        clearing mechanism that does not exist;
      * `REPEAT_S` was declared and never used, and its comment PROMISED
        a one-hour broadcast backoff that no code kept;
      * `MAX_MSG_CHARS` was declared and never used, and its comment
        PROMISED a ledger budget that nothing in the module applied.

    A constant that promises a behaviour nobody implements is worse
    than no constant: a reader believes it.

    The absence IS the only thing this test can fail on: it asserts
    `hasattr` is False, which no other clause in the module can affect.
    """
    for name in ("drift_parts", "REPEAT_S", "MAX_MSG_CHARS"):
        assert not hasattr(ra, name), f"{name} is still in runaway_alert.py"


def test_the_alert_module_claims_no_clearing_mechanism() -> None:
    """A-5: the FALSE 'ack' docstring is gone.

    `record_kill`'s docstring said "the daemon's file is cleared by
    `ack`", and there is NO `ack` function anywhere in the plugin —
    the daemon never clears the file. A docstring that describes a
    mechanism which does not exist sends the next reader looking for
    the clearing code that was never written.

    The docstring now states the REAL lifecycle: append-only from the
    daemon's side, trimmed to the last 50 by `record_kill`, and never
    cleared — the re-print suppression is per-session and lives in
    `scripts/dispatch.py::_phase_runaway_alert`.
    """
    doc = ra.record_kill.__doc__ or ""
    assert "ack" not in doc.lower(), (
        "record_kill's docstring still claims a clearing mechanism"
    )
    assert "clears it" not in doc.lower()
    # AND it says what is true.
    assert "never clears" in doc.lower()


# ---------- A-6: the janitor's own installation is excluded -----------------

def test_a_janitor_owned_process_is_never_a_victim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-6: the exclusion is STRUCTURAL, not an accident of shape.

    The janitor's launchd agent was safe only because its command line
    happened to match no runaway shape TODAY. Since the allowlist
    already contains `pytest` and `uv run pytest`, a future allowlist
    entry could match the janitor itself — and then the janitor would
    kill its own daemon.

    So the subject here is a PYTEST-SHAPED command INSIDE the janitor's
    own installation, and every OTHER clause is made to pass, so the
    janitor-self clause is the ONLY thing that can refuse it:

      * the shape matches (`pytest` is on the shipped allowlist);
      * the age gate passes (the row is old);
      * the env probe says YES (it is attributed);
      * its owner pointer names an ABSENT owner pid, so it IS abandoned;
      * it is not protected, not a forbidden client, not an interactive
        `claude` session.

    Delete the janitor-self clause and this test fails.
    """
    pid = 1800
    own = str(rg.JANITOR_ROOT)
    command = f"{own}/.venv/bin/pytest -q"
    row = _row(pid, command, rss_mb=440, age_s=5675, ppid=1)
    ancestry = {pid: (1, "launchd")}
    dead_owner = 20716
    # Every other clause must PASS, or the test would prove nothing.
    assert any(sig.search(command) for sig in rg.RUNAWAY_SHAPES), (
        "the subject does not match the runaway-shape allowlist"
    )
    assert row.etime_s >= rg.MIN_RUNAWAY_ETIME_S
    assert rg.is_abandoned(
        row,
        ancestry,
        owner_probe=_owner_probe({pid: dead_owner}),
        liveness_probe=_liveness_probe({}),
    ), "the subject must be abandoned"
    assert not rg.is_forbidden_client(command)
    assert not rg.is_interactive_claude(command)
    # The clause under test.
    assert rg.is_janitor_own(command), (
        "a command inside the janitor's own installation was not "
        "recognised as the janitor's own"
    )
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=0,
        ancestry=ancestry,
        env_probe=_probe({pid}),
        owner_probe=_owner_probe({pid: dead_owner}),
        liveness_probe=_liveness_probe({}),
    )
    assert victim is None, (
        "a process of the janitor's own installation was selected as a victim"
    )


def test_the_janitors_launchd_label_is_recognised_as_its_own() -> None:
    """A-6: the launchd label is a SECOND, independent handle.

    A launchd-started job's command line does not always carry the
    plugin's own path, so the label is checked separately. The label
    is the one the install script writes
    (`scripts/keepalive_install.sh`).
    """
    assert rg.JANITOR_LAUNCHD_LABEL == "com.ai-maestro-janitor.daemon"
    assert rg.is_janitor_own(
        f"/usr/bin/python3 -m x {rg.JANITOR_LAUNCHD_LABEL}"
    )
    # And an ordinary command is not the janitor's own.
    assert not rg.is_janitor_own("/usr/bin/pytest -q")


# ---------- A-7: the swapfile count is read from the file listing -----------

def test_the_swapfile_count_is_read_from_the_file_listing(tmp_path: Path) -> None:
    """A-7: the count comes from the FILES, and the gap is honoured.

    MEASURED on this host: 7 files named swapfile0..4, 6, 7 — a GAP AT
    5. A count by name index would say 8; a count by FILE says 7. The
    test fixture reproduces the gap, so a name-index implementation
    fails it.

    The directory is the parameter, so the test is real and not
    host-dependent.
    """
    for name in ("swapfile0", "swapfile1", "swapfile2", "swapfile3", "swapfile4",
                 "swapfile6", "swapfile7"):
        (tmp_path / name).write_bytes(b"")
    # A file that is NOT a swapfile must not be counted.
    (tmp_path / "not-a-swapfile").write_bytes(b"")
    assert rg.count_swapfiles(str(tmp_path)) == 7, (
        "the swapfile count did not come from the file listing (7 files, "
        "with a gap at index 5)"
    )


def test_an_absent_swapfile_directory_is_unknown_not_zero(tmp_path: Path) -> None:
    """A-7: a missing directory is UNKNOWN, never 0.

    "No swapfiles" and "I could not look" are different facts, and the
    second one must not read as the first — a count of 0 would be
    reported as a healthy host.
    """
    assert rg.count_swapfiles(str(tmp_path / "does-not-exist")) is None


def test_the_swapfile_count_cross_checks_against_the_swap_total() -> None:
    """A-7: the count x the per-file size MUST equal the swap total.

    This is the cross-check that makes the count TRUSTWORTHY. It is
    the property MEASURED on this host: 7 files x 1 GiB = 7168 MB, and
    `vm.swapusage` reports total = 7168.00M. EXACT MATCH.

    So a count that disagreed with the swap total would mean the
    reading is wrong, and the test asserts the two agree — and that a
    DISAGREEMENT is reported as a disagreement rather than silently
    passed.

    The figures are passed in, so the test is real and not
    host-dependent: the host's live numbers change minute to minute,
    and a test that asserted against them would be a flake waiting
    for a busy afternoon.
    """
    per_file = 1073741824  # 1 GiB — the measured swapfile size
    count = 7
    total_mb = 7 * per_file // (1024 * 1024)  # 7168 MB
    assert rg.swapfile_total_matches_count(count, per_file, total_mb) is True
    # A count that disagrees with the total is a DISAGREEMENT.
    assert rg.swapfile_total_matches_count(8, per_file, total_mb) is False
    # And an UNKNOWN figure is an ABSENT check, not a passing one.
    assert rg.swapfile_total_matches_count(None, per_file, total_mb) is None
    assert rg.swapfile_total_matches_count(count, None, total_mb) is None
    assert rg.swapfile_total_matches_count(count, per_file, None) is None


# ---------- A-5: the alert's age filter is real ----------------------------

# ---------- A-1: the alert path (item 12 and item 14) -----------------------

def test_the_alert_path_reports_an_enormous_but_young_process() -> None:
    """THE ALERT PATH HAS NO AGE FLOOR, and that is the point.

    MEASURED (TRDD-ZIKYQQY0 A-1, item 12): BOTH the kill path and the
    alert path were handed `min_etime_s = 3600`, so the alert path
    silently gained a one-hour age floor it never had — and it now
    refuses to report a 9 GB `codex --serve` that is TEN SECONDS old.
    That is precisely the "enormous but young" case the alert exists
    for: a process that is about to become a problem, reported early.

    The floor's stated PURPOSE is to bound the KILL SURFACE. This path
    has no kill surface: it reports, it does not act. So the floor does
    not apply here, and the `min_etime_s` PARAMETER IS GONE from the
    function rather than merely ignored — a parameter that lies about
    what it does is worse than no parameter.
    """
    hog = _row(1900, "codex --serve", rss_mb=9000, age_s=10)
    assert rg.is_forbidden_client(hog.command)
    found = rg.select_refused_alert(
        [hog], protected_pids=frozenset(), min_rss_kb=4 * 1024 * 1024,
    )
    assert found is not None, (
        "a 9 GB process that is ten seconds old was NOT reported; the "
        "alert path must have no age floor"
    )
    assert found.pid == 1900


def test_the_refused_alert_reports_every_refusal_with_a_reason() -> None:
    """THE ALERT IS EVERY REFUSAL, and it carries the REASON.

    The old alert selected only processes refused by `is_forbidden_client`
    or `is_interactive_claude` — the two categories refused BY POLICY. It
    was SILENT about the far more common category: a huge process that is
    simply UNATTRIBUTED, or not yet abandoned, or refused for a reason
    the owner has never heard of. MEASURED on the owner host: the largest
    real hog is `alcore serve` at 1 545 MB, and under the old rule the
    guard would have said NOTHING about it.

    The subject here is a big process that is NOT a forbidden client and
    NOT an interactive session — the class the old rule was blind to. It
    is unattributed, so the OWNERSHIP clause refuses it, and the reason
    must say so.

    THE RSS BAR IS LOWERED to 1 GB HERE, and that is a deliberate choice:
    the SHIPPED bar is 4 GB, and the point of the test is the CLASS of
    process the old rule was blind to, not the specific 1 545 MB figure
    against the 4 GB default. The measured `alcore serve` figure is
    quoted because it is the real one; the bar is set so the fixture can
    exercise the rule.
    """
    hog = _row(1950, "/opt/alcore/bin/alcore serve", rss_mb=1545, age_s=1724)
    assert not rg.is_forbidden_client(hog.command)
    assert not rg.is_interactive_claude(hog.command)
    found = rg.select_refused_alert_with_reason(
        [hog], protected_pids=frozenset(), min_rss_kb=1024 * 1024,
        env_probe=_probe(set()),
        owner_probe=_owner_probe({}),
        liveness_probe=_liveness_probe({}),
    )
    assert found is not None, (
        "a 1.5 GB unattributed process was NOT reported by the alert path; "
        "the old rule was blind to exactly this class"
    )
    row, reason = found
    assert row.pid == 1950
    assert reason == "not-claude-owned", (
        f"the refusal reason was {reason!r}, not the ownership reason"
    )
    # AND the reason is a short STABLE TOKEN, not a sentence.
    assert reason.islower()
    assert " " not in reason


def test_the_refused_alert_reports_a_live_owner_as_such() -> None:
    """A refusal by the OWNER-LIVENESS clause is reported with THAT reason.

    The reason is what lets the owner tell the two very different
    situations apart: a huge process belonging to a LIVE Claude session
    is the user's own work, and a huge process belonging to a DEAD
    session is a runaway. Both are refused; the reason says which.
    """
    hog = _row(1960, "/srv/proj/.venv/bin/pytest -q", rss_mb=9000, age_s=7200)
    live_owner = 91163
    found = rg.select_refused_alert_with_reason(
        [hog], protected_pids=frozenset(), min_rss_kb=4 * 1024 * 1024,
        env_probe=_probe({1960}),
        owner_probe=_owner_probe({1960: live_owner}),
        liveness_probe=_liveness_probe({live_owner: "claude"}),
    )
    assert found is not None
    _row_found, reason = found
    assert reason == "owner-alive", (
        f"the refusal reason was {reason!r}, not the liveness reason"
    )


# ---------- A-1: the POSITIVE owner liveness (TRDD-ZIKYQQY0 A-1) ------------

def test_a_claude_owned_orphaned_shape_matching_process_is_selected() -> None:
    """THE FIXTURE THAT PROVES THE FIX — all four properties at once.

    THE SUBJECT HAS ALL FOUR PROPERTIES THE SPEC NAMES, and they are
    built from a SYNTHETIC process table rather than a live host
    snapshot, because the advisor's Step 0 established that this host
    has NO long-lived shape-matching process, so a test written against
    a live snapshot would be VACUOUS:

      * CLAUDE-OWNED  — it carries a `CLAUDE_PID` pointer at an owner pid;
      * ORPHANED      — that owner pid is ABSENT from the process table
                        (case (a));
      * LONG-LIVED    — older than the age gate;
      * SHAPE-MATCHING — its command matches a `RUNAWAY_SHAPES` pattern.

    AND THE RULE MUST SELECT IT. This is the test that FAILS on the
    pre-A-1 code: the ancestry channel cannot attribute a reparented
    orphan (there is no `claude` ancestor anywhere in its chain), so the
    ownership clause refused it and the guard was inert on exactly the
    class of process it was built for.

    The command line is the MEASURED one: `node <path>/.bin/tsx
    server.mjs`, one of the four orphans of the dead owner 20716 on the
    owner host.
    """
    pid = 13033
    command = "node /Users/User/ai-maestro/node_modules/.bin/tsx server.mjs"
    dead_owner = 20716
    row = _row(pid, command, rss_mb=27, age_s=39_388, ppid=1)
    ancestry = {pid: (1, "launchd")}

    # THE SHAPE CLAUSE MUST NOT BE WHAT REFUSES IT.
    assert any(sig.search(command) for sig in rg.RUNAWAY_SHAPES), (
        "the subject does not match the runaway-shape allowlist, so the "
        "shape clause would refuse it and this test would prove nothing"
    )
    # THE AGE CLAUSE MUST NOT BE WHAT REFUSES IT.
    assert row.etime_s >= rg.MIN_RUNAWAY_ETIME_S
    # THE OWNER CLAUSE MUST NOT BE WHAT REFUSES IT: the pointer is there.
    assert rg.claude_owner_pid(
        row, ancestry, owner_probe=_owner_probe({pid: dead_owner})
    ) == dead_owner

    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=0,
        ancestry=ancestry,
        env_probe=_probe({pid}),
        owner_probe=_owner_probe({pid: dead_owner}),
        liveness_probe=_liveness_probe({}),  # the owner pid is ABSENT
    )
    assert victim is not None, (
        "a Claude-owned, orphaned, long-lived, shape-matching process was "
        "NOT selected; the A-1 polarity fix must make the guard useful"
    )
    assert victim.pid == pid


def test_a_process_whose_claude_owner_is_alive_is_refused() -> None:
    """THE LIVE-OWNER REFUSAL, and the one the old rule broke.

    The owner pid is PRESENT with the name `claude`, every other clause
    passes, and the age gate is at its FLOOR — so the age clause cannot
    be what refuses the subject, and the OWNER-LIVENESS clause is the
    only thing that can.

    MEASURED on the owner host: nine owner pids point at a live process
    whose `comm` is exactly `claude` (53551, 27435, 33461, 91163,
    65246, 91843, 84126, 71925, 57726). 91163 is used here.
    """
    pid = 13033
    command = "node /Users/User/ai-maestro/node_modules/.bin/tsx server.mjs"
    live_owner = 91163
    row = _row(pid, command, rss_mb=27, age_s=39_388, ppid=1)
    ancestry = {pid: (1, "launchd")}

    assert any(sig.search(command) for sig in rg.RUNAWAY_SHAPES)
    assert row.etime_s >= rg.MIN_RUNAWAY_ETIME_S

    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=0,  # the knob, relaxed to the floor
        ancestry=ancestry,
        env_probe=_probe({pid}),
        owner_probe=_owner_probe({pid: live_owner}),
        liveness_probe=_liveness_probe({live_owner: "claude"}),
    )
    assert victim is None, (
        "a process whose Claude owner is ALIVE was selected as a victim; "
        "the owner's live work must never be killed"
    )


def test_a_recycled_owner_pid_is_unknown_and_never_abandoned() -> None:
    """CASE (c): the owner pid EXISTS but is NOT Claude-family.

    `kern.maxproc` is 16000 on the owner host, so pids ARE recycled. A
    dead owner's pid is eventually handed to an unrelated process. A
    liveness test that only asks "does the pid exist" sees "yes" in
    this case, concludes "the session is alive", and REFUSES the orphan
    FOREVER — so the guard reads as inert, which is the exact symptom
    the card has been fighting. But treating this case as "dead" would
    kill the work of whatever process now holds that pid.

    So case (c) reads UNKNOWN, and UNKNOWN always fails SAFE. This test
    FAILS if the liveness test is two-case.
    """
    pid = 13033
    command = "node /Users/User/ai-maestro/node_modules/.bin/tsx server.mjs"
    recycled = 20716
    row = _row(pid, command, rss_mb=27, age_s=39_388, ppid=1)
    ancestry = {pid: (1, "launchd")}

    # The owner pid is PRESENT, but under a NON-Claude name.
    assert rg.owner_state(recycled, _liveness_probe({recycled: "codex"})) == "unknown"
    assert not rg.is_abandoned(
        row,
        ancestry,
        owner_probe=_owner_probe({pid: recycled}),
        liveness_probe=_liveness_probe({recycled: "codex"}),
    ), (
        "a RECYCLED owner pid was read as abandoned; the pid exists but "
        "the pointer can no longer prove anything about the real owner"
    )
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=0,
        ancestry=ancestry,
        env_probe=_probe({pid}),
        owner_probe=_owner_probe({pid: recycled}),
        liveness_probe=_liveness_probe({recycled: "codex"}),
    )
    assert victim is None, (
        "a process with a RECYCLED owner pid was selected as a victim"
    )


def test_an_unknown_owner_is_never_abandoned() -> None:
    """NO OWNER AT ALL -> UNKNOWN -> NOT ABANDONED -> REFUSE.

    No `CLAUDE_PID` pointer, and no claude-family ancestor. The owner
    cannot be identified, and an unidentified owner is never a dead one.
    """
    pid = 4242
    command = "node /Users/User/ai-maestro/node_modules/.bin/tsx server.mjs"
    row = _row(pid, command, rss_mb=27, age_s=39_388, ppid=1)
    ancestry = {pid: (1, "launchd")}

    assert rg.claude_owner_pid(
        row, ancestry, owner_probe=_owner_probe({})
    ) is None, (
        "no owner pointer and no claude ancestor must leave the owner "
        "UNKNOWN"
    )
    assert not rg.is_abandoned(
        row, ancestry, owner_probe=_owner_probe({}), liveness_probe=_liveness_probe({})
    ), "an UNKNOWN owner was read as abandoned"
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=0,
        ancestry=ancestry,
        env_probe=_probe({pid}),
        owner_probe=_owner_probe({}),
        liveness_probe=_liveness_probe({}),
    )
    assert victim is None, (
        "a process with an UNKNOWN owner was selected as a victim"
    )


def test_a_claude_desktop_ancestor_is_recognised_case_insensitively() -> None:
    """THE CLAUDE DESKTOP BINARY IS `Claude` — CAPITAL C.

    MEASURED on the owner host: Claude Desktop is installed as a binary
    named `Claude` (CAPITAL C) at
    /Applications/Claude.app/Contents/MacOS/Claude. The previous test
    was `basename in ("claude", "claude.exe")` — LOWERCASE ONLY — so a
    live Claude Desktop session's descendants had NO claude-named
    ancestor.

    Under the old NEGATED abandonment rule that made them read as
    ABANDONED, i.e. KILLABLE: a live session the user was working in
    was one case-sensitivity bug away from the kill path. This test
    FAILS on the case-sensitive implementation.
    """
    pid = 5000
    ancestry = {
        pid: (5001, "node /srv/project/server.js"),
        5001: (5002, "/Applications/Claude.app/Contents/MacOS/Helper"),
        5002: (5003, "/Applications/Claude.app/Contents/MacOS/Claude"),
    }
    assert rg.claude_ancestor(pid, ancestry) == 5002, (
        "the case-insensitive Claude-family test did not find the "
        "Desktop ancestor"
    )
    assert rg.is_claude_family_executable("/Applications/Claude.app/Contents/MacOS/Claude")
    assert rg.is_claude_family_executable("/usr/local/bin/claude")
    assert rg.is_claude_family_executable("/usr/local/bin/claude.exe")
    assert not rg.is_claude_family_executable("/usr/local/bin/codex")


def test_a_claude_desktop_session_is_never_a_victim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A LIVE CLAUDE DESKTOP SESSION IS NEVER A VICTIM.

    The whole chain is rooted at the Desktop binary, the owner is
    ALIVE, and the process is otherwise a perfect victim: shape-matching,
    long-lived, env-attributed, not protected, not forbidden, not an
    interactive `claude` session.

    The OWNER-LIVENESS clause is the only thing that can refuse it.
    """
    pid = 5000
    command = "node /srv/project/server.js"
    row = _row(pid, command, rss_mb=9000, age_s=39_388, ppid=5001)
    ancestry = {
        pid: (5001, "node /srv/project/server.js"),
        5001: (5002, "/Applications/Claude.app/Contents/MacOS/Helper"),
        5002: (5003, "/Applications/Claude.app/Contents/MacOS/Claude"),
    }
    # The shape clause must NOT be what refuses it: widen the allowlist
    # so the subject matches, making the owner clause the only one left.
    widened = rg.RUNAWAY_SHAPES + (re.compile(r"/srv/project/server\.js"),)
    # The allowlist is widened THROUGH MONKEYPATCH, so the fixture
    # restores the module attribute and no direct assignment to a module
    # attribute is needed (pyright rejects `rg.X = ...` on a ModuleType).
    monkeypatch.setattr(rg, "RUNAWAY_SHAPES", widened)
    assert any(sig.search(command) for sig in rg.RUNAWAY_SHAPES)
    assert row.etime_s >= rg.MIN_RUNAWAY_ETIME_S
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=0,
        ancestry=ancestry,
        env_probe=_probe({pid}),
        owner_probe=_owner_probe({}),
        liveness_probe=_liveness_probe({5002: "Claude"}),
    )
    assert victim is None, (
        "a live Claude Desktop session's descendant was selected as a victim"
    )


def test_a_gemini_process_is_never_a_victim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE FORBIDDEN LIST IS LOAD-BEARING FOR SAFETY.

    MEASURED on the owner host: `gemini` (Google's CLI) ran as pid
    65811 with RSS 152 MB carrying `CLAUDE_PID=20716` — the DEAD owner
    — plus `CLAUDE_CODE_CHILD_SESSION=1` and
    `CLAUDE_CODE_ENTRYPOINT=cli. It was NOT in `_FORBIDDEN_EXECUTABLES`,
    and the shape allowlist now carries `node`-based patterns that a
    `gemini` launcher can match.

    So without the name entry, a foreign client under a dead Claude
    owner would be KILLABLE — and the owner's directive forbids exactly
    that. The rule must be right for the population that APPEARS, not
    only for the one that is running at this instant.

    The subject here is otherwise a PERFECT victim: it carries a DEAD
    owner pointer, it is long-lived, and the allowlist is widened to
    match it so the forbidden-client clause is the ONLY thing that can
    refuse it.
    """
    pid = 65811
    command = "/opt/homebrew/Cellar/gemini-cli/0.46.0/libexec/bin/gemini --model gemini-2.5-pro"
    dead_owner = 20716
    row = _row(pid, command, rss_mb=152, age_s=39_388, ppid=1)
    ancestry = {pid: (1, "launchd")}

    assert rg.is_forbidden_client(command), (
        "the gemini launcher was not recognised as a forbidden client"
    )
    widened = rg.RUNAWAY_SHAPES + (re.compile(r"gemini-cli/0\.46\.0/libexec/bin/gemini"),)
    # The allowlist is widened THROUGH MONKEYPATCH, so the fixture
    # restores the module attribute and no direct assignment to a module
    # attribute is needed (pyright rejects `rg.X = ...` on a ModuleType).
    monkeypatch.setattr(rg, "RUNAWAY_SHAPES", widened)
    assert any(sig.search(command) for sig in rg.RUNAWAY_SHAPES)
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=0,
        ancestry=ancestry,
        env_probe=_probe({pid}),
        owner_probe=_owner_probe({pid: dead_owner}),
        liveness_probe=_liveness_probe({}),
    )
    assert victim is None, (
        "a gemini process under a DEAD Claude owner was selected as a victim; "
        "the owner directive forbids touching other AI clients"
    )


def test_a_recycled_owner_pid_never_reads_as_dead() -> None:
    """CASE (c) SPELLED OUT, so its intent is legible on its own.

    This is the explicit assertion that a RECYCLED owner pid is not
    "dead". It is separate from the test above on purpose: that one
    asserts the END-TO-END behaviour, and this one asserts the
    THREE-CASE LIVENESS TEST itself, so a future edit to `owner_state`
    that breaks case (c) fails HERE, with the failure naming the case.
    """
    recycled = 20716
    # Case (a): ABSENT -> dead.
    assert rg.owner_state(recycled, _liveness_probe({})) == "dead"
    # Case (b): PRESENT and Claude-family -> alive.
    assert rg.owner_state(recycled, _liveness_probe({recycled: "claude"})) == "alive"
    assert rg.owner_state(recycled, _liveness_probe({recycled: "Claude"})) == "alive"
    # Case (c): PRESENT and NOT Claude-family -> UNKNOWN, never dead.
    assert rg.owner_state(recycled, _liveness_probe({recycled: "codex"})) == "unknown"
    assert rg.owner_state(recycled, _liveness_probe({recycled: "node"})) == "unknown"
    assert rg.owner_state(recycled, _liveness_probe({recycled: "codex"})) != "dead", (
        "a RECYCLED owner pid read as DEAD; the pointer can no longer prove "
        "the real owner is gone, and the kill must be refused"
    )



def _raising_probe(pid: int):
    """A liveness_probe that cannot read the process table."""
    raise rg.OwnerProbeError("ps unreadable")


def test_an_unreadable_probe_reads_probe_failed_and_is_never_abandoned() -> None:
    """A raising liveness probe yields "probe-failed", never "dead", never abandoned."""
    pid = 13033
    owner = 20716
    row = _row(pid, "node /x/node_modules/.bin/tsx server.mjs", rss_mb=27, age_s=39_388, ppid=1)
    ancestry = {pid: (1, "launchd")}
    assert rg.owner_state(owner, _raising_probe) == "probe-failed"
    assert not rg.is_abandoned(
        row,
        ancestry,
        owner_probe=_owner_probe({pid: owner}),
        liveness_probe=_raising_probe,
    )
    # CONTROL: identical row/ancestry/owner_probe, owner ABSENT (dead) must
    # be abandoned, so the assertion above depends on the probe failing.
    assert rg.is_abandoned(
        row,
        ancestry,
        owner_probe=_owner_probe({pid: owner}),
        liveness_probe=_liveness_probe({}),
    )


def test_the_selection_gate_refuses_with_owner_probe_failed_when_the_probe_raises() -> None:
    """refusal_reason returns "owner-probe-failed" for a raising liveness probe."""
    pid = 13033
    owner = 20716
    command = "node /Users/User/ai-maestro/node_modules/.bin/tsx server.mjs"
    row = _row(pid, command, rss_mb=27, age_s=39_388, ppid=1)
    ancestry = {pid: (1, "launchd")}
    reason = rg.refusal_reason(
        row,
        protected_pids=frozenset(),
        min_etime_s=0,
        ancestry=ancestry,
        env_probe=_probe({pid}),
        owner_probe=_owner_probe({pid: owner}),
        liveness_probe=_raising_probe,
    )
    assert reason == "owner-probe-failed"


def test_read_owner_comm_returns_none_for_a_reaped_child() -> None:
    """The real ps probe reports a reaped child's pid ABSENT (None)."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    result = rg.read_owner_comm(child.pid)
    if result is not None:
        pytest.skip("pid reused")
    assert result is None


def test_read_owner_comm_names_the_current_process() -> None:
    """The real ps probe returns a non-empty name for a live pid."""
    name = rg.read_owner_comm(os.getpid())
    assert isinstance(name, str) and name


def test_read_owner_comm_refuses_non_positive_pids() -> None:
    """pid 0 and negative pids raise OwnerProbeError instead of reading ABSENT."""
    for bad in (0, -5):
        with pytest.raises(rg.OwnerProbeError):
            rg.read_owner_comm(bad)


def test_read_owner_comm_raises_for_an_out_of_range_pid() -> None:
    """A pid beyond the platform range makes ps fail, which raises OwnerProbeError."""
    with pytest.raises(rg.OwnerProbeError):
        rg.read_owner_comm(2**31)


def test_the_template_artefact_is_not_an_owner_pointer() -> None:
    """THE TEMPLATE ARTEFACTS ARE NOT POINTERS.

    MEASURED on the owner host: the literal token `CLAUDE_PID={v}` — a
    pid of `{v}` — exists, and so does a `CLAUDE_PID=[0-9]*` inside a
    shell command line. NEITHER is a pointer, and a template artefact
    read as an owner would point the liveness test at a pid that means
    nothing.

    The test is at the PARSER level, so it needs no live process.
    """
    # The template artefact.
    assert rg.parse_claude_pid_value("{v}") is None
    assert rg.parse_claude_pid_value("") is None
    assert rg.parse_claude_pid_value("   ") is None
    # A non-numeric value of any shape.
    assert rg.parse_claude_pid_value("abc") is None
    assert rg.parse_claude_pid_value("12a") is None
    assert rg.parse_claude_pid_value("-5") is None
    assert rg.parse_claude_pid_value("1.5") is None
    # A value that is not a plausible pid.
    assert rg.parse_claude_pid_value("0") is None
    assert rg.parse_claude_pid_value("1") is None
    assert rg.parse_claude_pid_value(str(2 ** 31)) is None
    # A SELF-POINTER is not an owner.
    assert rg.parse_claude_pid_value("4242", own_pid=4242) is None
    assert rg.parse_claude_pid_value("4242", own_pid=99) == 4242
    # A real pid parses.
    assert rg.parse_claude_pid_value("20716") == 20716
# ---------- the opt-in ------------------------------------------------------

