#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""redos_load_harness: show the secret-shield timing checks hold under steady CPU contention (TRDD-OD5Z90YL, ruling D8).

The normative spec is design/specs/redos-load-harness-d8.md; every rule below cites it. Contention, not the 1-min load average, is the
controlled variable: N CPU-only workers run in one recorded process group while `claude plugin test` runs the estimator probe
(hooks/secret-shield/tests/load/probe.load.ts, copied to probe.test.ts in a fresh assembly) once per probe.

Exit codes: 0 pass, 1 fail, 2 aborted, incomplete or invalid (the record names which), 3 refused (ambient load too high).
The file is not named test_*, so pytest does not collect it; it ships with the plugin as test code. Its tests are tests/test_redos_load_harness*.py.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts"))
from run_secret_shield_tests import assemble_plugin_dir  # noqa: E402

MOD = "secret-shield"
PROBE_REL = f"hooks/{MOD}/tests/load/probe.test.ts"
PATTERNS_TEST_REL = f"hooks/{MOD}/tests/patterns.test.ts"
DEFAULT_OUT_DIR = _REPO / "reports_dev" / "redos-load-harness"

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_UNFINISHED = 2  # aborted, incomplete or invalid
EXIT_REFUSED = 3

# Spec "Harness behaviour" and "Verdicts": 6 linear + 7 mutant rows, the probe prints these ids exactly (checked against probe.load.ts).
LINEAR_IDS = ("L1", "L1c", "L2d", "L3", "L3b", "L3c")
MUTANT_IDS = ("Q1", "Q2", "Q2b", "Q3", "Q4", "Q5", "Q6")
ROW_KINDS = {**{i: "linear" for i in LINEAR_IDS}, **{i: "mutant" for i in MUTANT_IDS}}
# timing.ts Verdict, plus the `error` the probe prints when a row's measurement threw (C1 channel).
ROW_VERDICTS = frozenset({"linear", "superlinear", "escaped", "out-of-rounds", "error"})
PROBE_TEST_PREFIX = "estimator probe > "

# TRDD-Z41A13XV (spec "Verdicts"): the two tests that must pass in every probe, matched by the full "<describe> > <test>" name.
Z41_DESCRIBE = "a port-skip query scan is linear up to 256 KB and still tells a port from a password"
Z41_TESTS = (
    "8 times the text takes under 12 times as long, with a URL count that grows with the text",
    "the same growth followed by a short, self-contained URL password still hides exactly that password at both sizes",
)

AMBIENT_PER_CORE = 0.7
ABORT_LOAD = 60.0
REQUIRED_PROBES = 20
DEFAULT_LIFETIME_S = 48 * 60
DEFAULT_CAP_S = 43 * 60
DEFAULT_SETTLE_S = 70.0
PROBE_TIMEOUT_S = 300.0

LoadSource = Callable[[], float]

_ROW_LINE_RE = re.compile(r"^REDOS-ROW.*$", re.MULTILINE)
_ROW_RE = re.compile(r"REDOS-ROW (\S+) (\S+) (\S+)")
_HEADER_RE = re.compile(r"^(\S.*\.test\.tsx?):[ \t]*$")
_TEST_RE = re.compile(r"^\((pass|fail)\) (.*) \[[0-9.]+m?s\][ \t]*$")
_PASS_COUNT_RE = re.compile(r"^\s*(\d+) pass\s*$", re.MULTILINE)
_FAIL_COUNT_RE = re.compile(r"^\s*(\d+) fail\s*$", re.MULTILINE)
_DECLARED_RE = re.compile(r"^// expected-rows: (\d+)\s*$")

# The worker: CPU only. A reader thread blocks on the shared stdin pipe and exits the process on EOF, i.e. when the harness (or its SIGKILLed corpse)
# closes the write end; the main thread burns CPU until its lifetime. WHY (spec "Workers"): a SIGKILLed harness must not leave 35 busy processes behind.
_WORKER_CODE = """
import os, sys, threading, time
def _watch():
    sys.stdin.buffer.read()
    os._exit(0)
threading.Thread(target=_watch, daemon=True).start()
end = time.monotonic() + float(sys.argv[1])
x = 0
while time.monotonic() < end:
    for i in range(100000):
        x = (x * 31 + i) & 0xFFFFFFFF
os._exit(0)
"""


# ---------------------------------------------------------------- pure functions


def worker_count(cores: int) -> int:
    """2.5 workers per core, rounded up (35 on the 14-core dev host). Spec "Workers"."""
    return (5 * cores + 1) // 2


def ambient_refused(samples: list[float], cores: int) -> bool:
    """True when the highest ambient 1-min sample is 0.7 per core or more. Spec "Ambient check": refuse, run nothing, exit 3."""
    return max(samples) >= AMBIENT_PER_CORE * cores


def plan_probes(cap_s: float, elapsed_s: float, dry_s: float, max_probes: int) -> int:
    """K: the largest count up to `max_probes` whose expected end, at the dry-run duration per probe, fits the cap. Spec "Timing and cap"."""
    if dry_s <= 0:
        return max_probes
    return max(0, min(max_probes, int((cap_s - elapsed_s) // dry_s)))


def judge_row(kind: str, verdict: str) -> str:
    """Status of one row from its REDOS-ROW verdict: pass, fail, undecided or invalid. Spec "Verdicts": rows are judged from the verdict, never from the test's (pass)/(fail)."""
    if verdict == "error":
        # WHY invalid: an exception means the probe is broken, not that the estimator decided.
        return "invalid"
    if verdict == "escaped":
        # WHY undecided for either kind: too fast to time proves nothing; never a pass and never a 1a failure.
        return "undecided"
    if kind == "linear":
        # WHY out-of-rounds fails a linear row: under load a false failure of a linear rule is what the campaign measures.
        return "pass" if verdict == "linear" else "fail"
    if verdict == "superlinear":
        return "pass"  # WHY only superlinear: a mutant is detected only when never confirmed linear and the last ratio is over the limit.
    # WHY: a mutant judged linear makes 1a NOT MET; a mutant out of rounds is undecided (not a detection).
    return "fail" if verdict == "linear" else "undecided"


@dataclass
class Parsed:
    rows: dict[str, tuple[str, str]] = field(default_factory=dict)  # id -> (kind, verdict)
    problems: list[str] = field(default_factory=list)
    tests: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # file header -> [(outcome, name)]
    n_pass: int | None = None
    n_fail: int | None = None


def parse_output(output: str) -> Parsed:
    """Parse `claude plugin test` output: REDOS-ROW lines, `<path>:` headers with their (pass)/(fail) lines, and the final counts."""
    parsed = Parsed()
    # WHY across the whole output: the console lines print BEFORE the file header of the file that emitted them (measured 2026-11-14).
    for line in _ROW_LINE_RE.findall(output):
        match = _ROW_RE.fullmatch(line.rstrip())
        if match is None:
            parsed.problems.append(f"malformed REDOS-ROW line: {line!r}")
            continue
        row_id, kind, verdict = match.groups()
        if row_id not in ROW_KINDS:
            parsed.problems.append(f"unknown REDOS-ROW id: {row_id}")
        elif row_id in parsed.rows:
            parsed.problems.append(f"duplicate REDOS-ROW id: {row_id}")
        elif kind != ROW_KINDS[row_id]:
            parsed.problems.append(f"REDOS-ROW {row_id} has kind {kind}, expected {ROW_KINDS[row_id]}")
        elif verdict not in ROW_VERDICTS:
            parsed.problems.append(f"REDOS-ROW {row_id} has unknown verdict {verdict}")
        else:
            parsed.rows[row_id] = (kind, verdict)
    current: str | None = None
    for line in output.splitlines():
        header = _HEADER_RE.match(line)
        if header is not None:
            current = str(header.group(1))
            parsed.tests.setdefault(current, [])
            continue
        test = _TEST_RE.match(line)
        if test is not None and current is not None:
            parsed.tests[current].append((test.group(1), test.group(2)))
    counts_pass, counts_fail = _PASS_COUNT_RE.findall(output), _FAIL_COUNT_RE.findall(output)
    if counts_pass and counts_fail:
        parsed.n_pass, parsed.n_fail = int(counts_pass[-1]), int(counts_fail[-1])
    return parsed


@dataclass
class ProbeJudgement:
    valid: bool
    invalid_reason: str | None
    rows: dict[str, dict[str, str | None]]  # id -> kind, verdict, test outcome, status
    status: str  # pass, fail, undecided or invalid
    undecided: int
    z41: dict[str, str]  # test name -> pass, fail or missing
    collateral: list[str]
    n_pass: int | None
    n_fail: int | None


def judge_probe(output: str, expected_files: list[str], declared_rows: int) -> ProbeJudgement:
    """Judge one probe's output. Spec "Verdicts": probe validity, row statuses, the TRDD-Z41A13XV tests and collateral failures."""
    parsed = parse_output(output)
    problems = list(parsed.problems)
    if parsed.n_pass is None or parsed.n_fail is None:
        problems.append("no pass/fail count lines in the output (the run did not report)")
    missing_headers = [rel for rel in expected_files if rel not in parsed.tests]
    if missing_headers:
        problems.append(f"no header line for: {', '.join(missing_headers)}")
    if declared_rows != len(ROW_KINDS):
        problems.append(f"probe.load.ts declares {declared_rows} rows, expected {len(ROW_KINDS)}")
    probe_tests: dict[str, str] = {}
    for outcome, name in parsed.tests.get(PROBE_REL, []):
        if not name.startswith(PROBE_TEST_PREFIX):
            problems.append(f"unexpected test in the probe file: {name}")
            continue
        test_id = name[len(PROBE_TEST_PREFIX) :].split(" ", 1)[0]
        if test_id in probe_tests:
            problems.append(f"duplicate probe test id: {test_id}")
        elif test_id not in ROW_KINDS:
            problems.append(f"unknown probe test id: {test_id}")
        else:
            probe_tests[test_id] = outcome
    if PROBE_REL in parsed.tests and len(parsed.tests[PROBE_REL]) != declared_rows:
        problems.append(f"{len(parsed.tests[PROBE_REL])} probe tests reported, {declared_rows} declared")
    for row_id in ROW_KINDS:
        if row_id not in parsed.rows:
            problems.append(f"REDOS-ROW missing for {row_id} (its reason cannot be read)")
        if row_id not in probe_tests:
            problems.append(f"no test line for row {row_id}")
    rows: dict[str, dict[str, str | None]] = {}
    statuses: list[str] = []
    for row_id, (kind, verdict) in parsed.rows.items():
        status = judge_row(kind, verdict)
        statuses.append(status)
        rows[row_id] = {"kind": kind, "verdict": verdict, "test": probe_tests.get(row_id), "status": status}
        if status == "invalid":
            problems.append(f"row {row_id} verdict is error (the probe is broken)")
    z41: dict[str, str] = {}
    z41_names: set[str] = set()
    for test in Z41_TESTS:
        full = f"{Z41_DESCRIBE} > {test}"
        z41_names.add(full)
        # WHY an exact name, not startswith: a prefix match would silently count a renamed or suffixed replacement test as Z41A13XV's; an exact match makes any rename read as missing (incomplete) until Z41_TESTS is updated.
        found = [outcome for outcome, name in parsed.tests.get(PATTERNS_TEST_REL, []) if name == full]
        # WHY missing unless exactly one match: a replaced or renamed test must never read as a silent pass.
        z41[test] = found[0] if len(found) == 1 else "missing"
    collateral = [
        f"{file}: {name}"
        for file, tests in parsed.tests.items()
        if file != PROBE_REL
        for outcome, name in tests
        if outcome == "fail" and name not in z41_names
    ]
    undecided = statuses.count("undecided")
    if problems:
        status = "invalid"
    elif "fail" in statuses:
        status = "fail"
    elif undecided:
        status = "undecided"
    else:
        status = "pass"
    return ProbeJudgement(not problems, "; ".join(problems) or None, rows, status, undecided, z41, collateral, parsed.n_pass, parsed.n_fail)


@dataclass
class CampaignVerdict:
    one_a: str  # pass, fail or incomplete
    z41a13xv: str
    exit_code: int


def judge_campaign(probes: list[ProbeJudgement], required: int = REQUIRED_PROBES) -> CampaignVerdict:
    """Verdict of a campaign that ran to its end, from the non-dry-run, valid probes. Spec "Verdicts"."""
    # WHY a definite failure beats incomplete: 1a needs every row to pass in all K probes, so one failure means not met whatever the remaining probes say.
    # (The spec does not rank them; chosen here and listed in the report.)
    one_a = "fail" if any(p.status == "fail" for p in probes) else "incomplete" if len(probes) < required or any(p.status == "undecided" for p in probes) else "pass"
    z41_all = [v for p in probes for v in p.z41.values()]
    z41 = "fail" if "fail" in z41_all else "incomplete" if len(probes) < required or "missing" in z41_all else "pass"
    # WHY the exit code joins both verdicts: either failing means the card's acceptance is not met (the spec lists the two verdicts, not their combination).
    exit_code = EXIT_FAIL if "fail" in (one_a, z41) else EXIT_UNFINISHED if "incomplete" in (one_a, z41) else EXIT_PASS
    return CampaignVerdict(one_a, z41, exit_code)


# ---------------------------------------------------------------- processes


class WorkerGroup:
    """CPU-only workers in one process group of their own, never the caller's group (so a killpg cannot reach the harness or pytest)."""

    def __init__(self, write_fd: int) -> None:
        self.procs: list[subprocess.Popen[bytes]] = []
        self.pgid = 0
        self._write_fd = write_fd
        self._lock = threading.Lock()
        self._reaped = False

    @classmethod
    def start(cls, count: int, lifetime_s: float) -> WorkerGroup:
        """Start `count` workers in one batch. The harness keeps the write end of their shared stdin pipe; EOF on it ends them."""
        read_fd, write_fd = os.pipe()
        group = cls(write_fd)
        argv = [sys.executable, "-I", "-c", _WORKER_CODE, str(lifetime_s)]
        try:
            for index in range(count):
                if index == 0:
                    # WHY process_group=0, not start_new_session: setpgid cannot join a group of another session (EPERM, measured), so the later workers could not follow a
                    # session leader; a group of its own inside the harness's session still keeps a killpg away from the harness and pytest.
                    proc = subprocess.Popen(argv, stdin=read_fd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, process_group=0)
                    group.pgid = proc.pid
                else:
                    proc = subprocess.Popen(argv, stdin=read_fd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, process_group=group.pgid)
                group.procs.append(proc)
        except BaseException:
            group.reap()
            raise
        finally:
            # WHY close the read end here: only the workers hold it, and the pipe fds are non-inheritable (close_fds), so no later child can keep the write end open.
            os.close(read_fd)
        return group

    @property
    def pids(self) -> list[int]:
        return [p.pid for p in self.procs]

    def dead(self) -> list[int]:
        """PIDs of workers that have exited (poll reaps them). Spec "Liveness": a dead worker ends the campaign."""
        return [p.pid for p in self.procs if p.poll() is not None]

    def all_gone(self) -> bool:
        """True when no recorded PID exists any more (`kill(pid, 0)` raises)."""
        for pid in self.pids:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            return False
        return True

    def reap(self) -> None:
        """Kill and reap every worker. Idempotent; the lock is held for the whole teardown because the sampler thread and the main thread can both call it."""
        with self._lock:
            if self._reaped:
                return
            self._reaped = True
            os.close(self._write_fd)
            # WHY killpg only while a worker is unreaped: once all are reaped the pgid may be recycled by another process group.
            if any(p.poll() is None for p in self.procs):
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.pgid, signal.SIGKILL)
            for proc in self.procs:
                proc.wait(timeout=30)


def system_load() -> float:
    """The real 1-min load average."""
    return os.getloadavg()[0]


class Sampler:
    """Reads the 1-min load every `interval_s` from `source` in every phase; above `limit` it kills and reaps the group and sets `aborted`. Spec "Sampler"."""

    def __init__(self, source: LoadSource, interval_s: float, limit: float, group: WorkerGroup) -> None:
        self._source = source
        self._interval_s = interval_s
        self._limit = limit
        self._group = group
        self._stop = threading.Event()
        self.aborted = threading.Event()
        self.latest = 0.0
        self.peak = 0.0
        self.error: str | None = None
        self._thread = threading.Thread(target=self._run, name="redos-sampler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=30)

    def _run(self) -> None:
        try:
            while True:
                self.latest = self._source()
                self.peak = max(self.peak, self.latest)
                if self.latest > self._limit:
                    self._abort()
                    return
                if self._stop.wait(self._interval_s):
                    return
        except Exception as exc:  # noqa: BLE001
            # WHY abort on any sampler failure: a blind sampler cannot hold the 60 limit, and a silent thread death would run the campaign unguarded.
            self.error = f"{type(exc).__name__}: {exc}"
            self._abort()

    def _abort(self) -> None:
        # WHY `aborted` is set only AFTER the group is reaped (and even if the reap raises): whoever sees the flag may assume the workers are gone.
        try:
            self._group.reap()
        finally:
            self.aborted.set()


@dataclass
class ProbeRun:
    exit_code: int | None
    output: str
    seconds: float
    timed_out: bool
    aborted: bool
    expected: list[str]


def declared_rows(mod_dir: Path) -> int:
    """The count in the `// expected-rows: N` first line of probe.load.ts."""
    first = (mod_dir / "tests" / "load" / "probe.load.ts").read_text(encoding="utf-8").splitlines()[0]
    match = _DECLARED_RE.match(first)
    if match is None:
        raise ValueError(f"probe.load.ts first line is not `// expected-rows: N`: {first!r}")
    return int(match.group(1))


def run_probe(claude: str, mod_dir: Path, timeout_s: float, abort: threading.Event, poll_s: float = 0.5) -> ProbeRun:
    """One `claude plugin test` run in its own session over a fresh assembly. Spec "Assembly per probe" and "Probe"."""
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="redos-probe-") as tmp_name:
        tmp = Path(tmp_name)
        expected = assemble_plugin_dir(tmp, MOD, mod_dir)
        load_dir = tmp / "hooks" / MOD / "tests" / "load"
        shutil.copy2(load_dir / "probe.load.ts", load_dir / "probe.test.ts")
        expected.append(PROBE_REL)
        # WHY a session of its own: the runner starts a child per test file; killing only the direct child on a timeout or abort would orphan them.
        proc = subprocess.Popen([claude, "plugin", "test", str(tmp)], cwd=str(tmp), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", start_new_session=True)
        deadline = started + timeout_s
        timed_out = aborted = False
        output = ""
        try:
            while True:
                try:
                    output, _ = proc.communicate(timeout=poll_s)
                    break
                except subprocess.TimeoutExpired:
                    aborted = abort.is_set()
                    timed_out = not aborted and time.monotonic() > deadline
                    if aborted or timed_out:
                        break
            if aborted or timed_out:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                output, _ = proc.communicate(timeout=30)
        except BaseException:
            if proc.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate(timeout=30)
            raise
    return ProbeRun(None if (aborted or timed_out) else proc.returncode, output, time.monotonic() - started, timed_out, aborted, expected)

ProbeRunner = Callable[[str, Path, float, threading.Event], ProbeRun]


# ---------------------------------------------------------------- campaign


@dataclass(frozen=True)
class Config:
    workers: int
    lifetime_s: float = DEFAULT_LIFETIME_S
    settle_s: float = DEFAULT_SETTLE_S
    cap_s: float = DEFAULT_CAP_S
    max_probes: int = REQUIRED_PROBES
    probe_timeout_s: float = PROBE_TIMEOUT_S
    ambient_samples: int = 3
    ambient_interval_s: float = 10.0
    sample_interval_s: float = 2.0
    abort_load: float = ABORT_LOAD
    cores: int = field(default_factory=lambda: os.cpu_count() or 1)
    mod_dir: Path = _REPO / "hooks" / MOD


class Recorder:
    """One JSON line per probe plus one closing campaign line, in `path`. Spec "Records"."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict[str, object]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def default_record_path(out_dir: Path) -> Path:
    return out_dir / f"{datetime.now().astimezone().strftime('%Y%m%d_%H%M%S%z')}-campaign.jsonl"


def run_campaign(
    cfg: Config, load: LoadSource, recorder: Recorder, on_group: Callable[[WorkerGroup], None] | None = None, runner: ProbeRunner = run_probe
) -> int:
    """Run one campaign: ambient check, workers, settle, dry run, K probes. Returns the exit code; the record names the outcome.

    `on_group` receives the worker group as soon as it exists, so a caller (the real tests) can record its PIDs and prove them reaped.
    """
    started = time.monotonic()
    ambient: list[float] = []
    for index in range(cfg.ambient_samples):
        if index:
            time.sleep(cfg.ambient_interval_s)
        ambient.append(load())
    ambient_estimate = max(ambient)
    summary: dict[str, object] = {"kind": "campaign", "ambient_samples": ambient, "ambient_estimate": ambient_estimate, "workers": cfg.workers, "cores": cfg.cores}
    if ambient_refused(ambient, cfg.cores):
        recorder.write({**summary, "status": "refused", "reason": f"ambient load {ambient_estimate} is at or over {AMBIENT_PER_CORE} per core ({cfg.cores} cores)", "exit_code": EXIT_REFUSED})
        return EXIT_REFUSED
    claude = shutil.which("claude")
    if claude is None:
        recorder.write({**summary, "status": "invalid", "reason": "`claude` is not on PATH", "exit_code": EXIT_UNFINISHED})
        return EXIT_UNFINISHED
    declared = declared_rows(cfg.mod_dir)
    group = WorkerGroup.start(cfg.workers, cfg.lifetime_s)
    if on_group is not None:
        on_group(group)
    sampler = Sampler(load, cfg.sample_interval_s, cfg.abort_load, group)
    sampler.start()
    judgements: list[ProbeJudgement] = []
    state: dict[str, object] = {"planned": None, "dry_s": None}
    try:
        status, reason = _drive(cfg, load, claude, group, sampler, recorder, started, ambient_estimate, declared, judgements, state, runner)
    finally:
        sampler.stop()
        group.reap()
    if not group.all_gone():
        raise RuntimeError(f"workers still exist after reap: {group.pids}")
    # WHY any status, not only "complete": a sampler abort reaps the group, so a drive that lost the race may have returned another status for what was a load abort.
    if sampler.aborted.is_set() and status != "aborted":
        status, reason = "aborted", sampler.error or f"load over {cfg.abort_load}"
    verdict = judge_campaign(judgements) if status == "complete" else None
    exit_code = verdict.exit_code if verdict is not None else EXIT_UNFINISHED
    recorder.write(
        {
            **summary,
            **state,
            "status": status,
            "reason": reason,
            "exit_code": exit_code,
            "verdict_1a": verdict.one_a if verdict else None,
            "verdict_z41a13xv": verdict.z41a13xv if verdict else None,
            "probes_judged": len(judgements),
            "undecided": sum(j.undecided for j in judgements),
            "peak_load": sampler.peak,
            "seconds": time.monotonic() - started,
        }
    )
    return exit_code


def _drive(
    cfg: Config,
    load: LoadSource,
    claude: str,
    group: WorkerGroup,
    sampler: Sampler,
    recorder: Recorder,
    started: float,
    ambient_estimate: float,
    declared: int,
    judgements: list[ProbeJudgement],
    state: dict[str, object],
    runner: ProbeRunner = run_probe,
) -> tuple[str, str | None]:
    """Settle, dry run, then the K probes; returns (status, reason) where status is `complete` or the reason the campaign ended."""
    if sampler.aborted.wait(cfg.settle_s):
        return "aborted", sampler.error or f"load over {cfg.abort_load} during the settle"
    planned: int | None = None
    index = 0  # 0 is the dry run: excluded from verdicts, included in the cap (spec "Timing and cap")
    last_s = 0.0  # duration of the last probe: 0 before the dry run
    while planned is None or index <= planned:
        dry = index == 0
        # WHY the sampler abort is checked BEFORE group.dead(), here and after the probe: a sampler abort reaps the group, so dead() would then report every worker as
        # dead and misrecord the cause of a load abort as a dead worker.
        if sampler.aborted.is_set():
            return "aborted", sampler.error or f"load over {cfg.abort_load} before probe {index}"
        dead = group.dead()
        if dead:
            return "invalid", f"dead worker: workers {dead} had exited before probe {index}"
        elapsed = time.monotonic() - started
        # WHY elapsed + the last probe's duration: workers live 48 min against a 43 min cap and a probe may take up to 300 s, so a probe that would run past the cap must not start.
        if elapsed + last_s > cfg.cap_s:
            return "aborted", f"cap would be passed: {elapsed:.0f} s elapsed + {last_s:.0f} s for the last probe is over the {cfg.cap_s} s cap, before probe {index}"
        load_start = load()
        run = runner(claude, cfg.mod_dir, cfg.probe_timeout_s, sampler.aborted)
        load_end = load()
        if sampler.aborted.is_set() or run.aborted:
            return "aborted", sampler.error or f"load over {cfg.abort_load} during probe {index}"
        last_s = run.seconds
        judged = judge_probe(run.output, run.expected, declared)
        if run.timed_out:
            # WHY invalid: a timed-out probe's rows cannot be read, and the spec's "probe failure" for a timeout is read here as an invalid probe (listed in the report).
            judged.valid, judged.invalid_reason, judged.status = False, f"timeout after {cfg.probe_timeout_s} s", "invalid"
        dead = group.dead()
        if dead and judged.valid:
            judged.valid, judged.invalid_reason, judged.status = False, f"dead worker: workers {dead} died during the probe", "invalid"
        # WHY (TRDD-LAUPB305): two cut-off runs on 2026-11-14 left no output to examine; an invalid probe keeps its raw output next to the record.
        raw_output = None if judged.valid else save_invalid_output(recorder.path, index, run.output)
        recorder.write(_probe_record(index, dry, run, judged, load_start, load_end, ambient_estimate, raw_output))
        if not judged.valid:
            # WHY one vocabulary: a dead worker is recorded as `invalid` (spec "Liveness"); its reason starts "dead worker".
            return "invalid", judged.invalid_reason
        if dry:
            planned = plan_probes(cfg.cap_s, time.monotonic() - started, run.seconds, cfg.max_probes)
            state["planned"], state["dry_s"] = planned, run.seconds
        else:
            judgements.append(judged)
        index += 1
    return "complete", None


def _probe_record(
    index: int, dry: bool, run: ProbeRun, judged: ProbeJudgement, load_start: float, load_end: float, ambient_estimate: float, raw_output: Path | None = None
) -> dict[str, object]:
    record: dict[str, object] = {
        "kind": "probe",
        "index": index,
        "dry_run": dry,
        "claude_exit": run.exit_code,
        "seconds": run.seconds,
        "pass": judged.n_pass,
        "fail": judged.n_fail,
        "status": judged.status,
        "rows": judged.rows,
        "z41a13xv": judged.z41,
        "collateral": judged.collateral,
        "undecided": judged.undecided,
        "invalid_reason": judged.invalid_reason,
        "load_start": load_start,
        "load_end": load_end,
        "ambient_estimate": ambient_estimate,
    }
    # WHY present only for an invalid probe (TRDD-LAUPB305): a valid record keeps its shape, and the key itself says the raw output was kept.
    if raw_output is not None:
        record["raw_output"] = str(raw_output)
    return record


def save_invalid_output(record_path: Path, index: int, output: str) -> Path:
    """Write an invalid probe's raw output to `<record stem>-probe<index>.txt` beside the JSONL record and return that path."""
    raw_path = record_path.with_name(f"{record_path.stem}-probe{index}.txt")
    raw_path.write_text(output, encoding="utf-8")
    return raw_path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="ReDoS load harness (TRDD-OD5Z90YL, design/specs/redos-load-harness-d8.md).")
    cores = os.cpu_count() or 1
    parser.add_argument("--workers", type=int, default=worker_count(cores), help="CPU-only workers (default 2.5 per core)")
    parser.add_argument("--lifetime", type=float, default=DEFAULT_LIFETIME_S, help="worker lifetime in seconds (default 48 min)")
    parser.add_argument("--settle", type=float, default=DEFAULT_SETTLE_S, help="seconds the load settles before the dry run")
    parser.add_argument("--cap", type=float, default=DEFAULT_CAP_S, help="cap for the whole run in seconds (default 43 min)")
    parser.add_argument("--probes", type=int, default=REQUIRED_PROBES, help="most probes after the dry run (default 20)")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="where the JSON-lines record goes")
    parser.add_argument("--workers-only", action="store_true", help="start the workers, print one JSON line with their PIDs and sleep (orphan test)")
    args = parser.parse_args(argv)
    if args.workers_only:
        group = WorkerGroup.start(args.workers, args.lifetime)
        try:
            print(json.dumps({"harness_pid": os.getpid(), "pgid": group.pgid, "pids": group.pids}), flush=True)
            time.sleep(args.lifetime + 5)
        finally:
            group.reap()
        return EXIT_PASS
    cfg = Config(workers=args.workers, lifetime_s=args.lifetime, settle_s=args.settle, cap_s=args.cap, max_probes=args.probes, cores=cores)
    return run_campaign(cfg, system_load, Recorder(default_record_path(args.out_dir)))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
