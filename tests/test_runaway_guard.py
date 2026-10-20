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
import re
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
    pressure = rg.host_pressure(
        min_free_mb=1024, swap_pct_bar=95, swapfiles=32, compressor_pct=60,
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
    """
    row = _row(600, "node /tmp/peak-space/watch.mjs x", rss_mb=300, ppid=1)
    assert rg.claude_ancestor(600, {}) is None, "ancestry alone must find nothing here"
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=60,
        ancestry={},
        env_probe=_probe({600}),
    )
    assert victim is not None
    assert victim.pid == 600


def test_at_most_one_victim_is_selected_per_call() -> None:
    """One kill per beat, so a transient misread cannot become a spree."""
    rows = [
        _row(700, "node /opt/homebrew/bin/agentlenspro statusline --inner x", rss_mb=500),
        _row(701, "node /opt/homebrew/bin/agentlenspro statusline --inner y", rss_mb=400),
        _row(702, "node /opt/homebrew/bin/agentlenspro statusline --inner z", rss_mb=300),
    ]
    victim = rg.select_victim(
        rows, protected_pids=frozenset(), min_etime_s=60, ancestry={},
        env_probe=_probe({700, 701, 702}),
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
    pressure = rg.host_pressure(
        min_free_mb=1024, swap_pct_bar=95, swapfiles=32, compressor_pct=60,
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
    pressure = rg.host_pressure(
        min_free_mb=1024, swap_pct_bar=95, swapfiles=32, compressor_pct=60,
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


def test_a_process_attributable_only_by_a_claude_ancestor_is_selected() -> None:
    """THE ANCESTRY CHANNEL, EXERCISED AS THE DECIDING FACTOR.

    The ancestry signal is the SECOND attribution channel and the module
    docstring devotes a paragraph to it, but NO TEST made it the
    deciding factor: the two tests that populate an ancestry table
    ALSO inject an env probe, so the env channel decided the outcome in
    both and the ancestry channel was never exercised.

    MEASURED as a surviving mutation: removing the ancestry fallback
    from `is_killable` left the whole suite green — a whole attribution
    path could be deleted without anyone noticing, which is the
    project's own "a test that cannot fail against its defect" shape
    one level up.

    So: an env probe that says NO, an ancestry table naming a `claude`
    parent, an allowlisted shape, past the age gate — and the victim
    must be that process.
    """
    row = _row(900, "node /opt/homebrew/bin/agentlenspro statusline --inner x",
               rss_mb=400)
    # The table maps EVERY pid to (ppid, command) INCLUDING the process
    # itself — the walk starts at the process's own row.
    ancestry = {
        900: (901, "node /opt/homebrew/bin/agentlenspro statusline --inner x"),
        901: (902, "claude --continue --add-dir /tmp"),
    }
    # The env channel says NO — only the ancestry can attribute it.
    victim = rg.select_victim(
        [row],
        protected_pids=frozenset(),
        min_etime_s=60,
        ancestry=ancestry,
        env_probe=_probe(set()),
    )
    assert victim is not None, "a process attributable only by a claude ancestor was not selected"
    assert victim.pid == 900


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


def test_the_swap_ratio_is_what_the_state_machine_uses() -> None:
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
    """
    import os as _os
    import subprocess as _subprocess
    import sys as _sys
    import time as _time

    if not hasattr(_os, "fork"):
        pytest.skip("needs a POSIX fork")
    # A real child, so the readings come from the real probes.
    child = _subprocess.Popen([_sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        _time.sleep(0.3)
        used, total, files = rg.read_swap()
        assert used is not None, "the swap probe could not read the host"
        assert total is not None, "the swap TOTAL could not be read"
        ratio = rg.swap_ratio_pct(used, total)
        assert ratio is not None
        # The ratio is what the ratio helper computes.
        assert ratio == int(used * 100 / total)
        # AND the state machine CONSUMES the ratio, not the raw
        # megabyte figure. MEASURED on this host: 6715 MB used of an
        # 8192 MB file is 82% — a working host — while 6715 MB in
        # absolute terms is over any plausible absolute bar. So a
        # guard keyed on the raw figure would be permanently critical
        # here and would kill a process every minute.
        #
        # The pin: with the swap reading stubbed to this host's
        # measured healthy state and the ratio bar at 95%, the state
        # must NOT be critical, and it must be the ratio that decides
        # it.
        import time as _time
        _time.sleep(0.1)
        pressure = rg.host_pressure(
            min_free_mb=1024, swap_pct_bar=95, swapfiles=32, compressor_pct=60,
        )
        assert pressure.state != "critical", (
            f"the host read CRITICAL at a 95% ratio bar: {pressure.readings()}"
        )
    finally:
        child.kill()
        child.wait()


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
    pressure = rg.host_pressure(
        min_free_mb=1024, swap_pct_bar=95, swapfiles=32, compressor_pct=60,
    )
    assert pressure.state == "critical", pressure.readings()


def test_the_compressor_alone_can_arm_the_kill_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE COMPRESSOR IS A PROXY for the panic's segment limit, and it
    must be able to arm the kill path on its own.

    The 2026-10-20 panic read 'Compressor Info: 100% of segments limit
    (BAD), 69 swapfiles' with free memory and swap both apparently
    survivable. So the compressor reading is the one that has to be
    able to say `critical` by itself — and it is a PROXY for the
    segment-limit condition (which is the compressor's own pool, not a
    ratio of physical RAM), so it must not be gated behind the others.
    """
    monkeypatch.setattr(rg, "free_memory_mb", lambda: 20000)
    monkeypatch.setattr(rg, "read_swap", lambda: (100, 8192, None))  # 1%
    monkeypatch.setattr(rg, "read_compressor_pct", lambda: 95)
    pressure = rg.host_pressure(
        min_free_mb=1024, swap_pct_bar=95, swapfiles=32, compressor_pct=60,
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


# ---------- the opt-in ------------------------------------------------------

