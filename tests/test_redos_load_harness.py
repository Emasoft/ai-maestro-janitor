"""The ReDoS load harness (TRDD-OD5Z90YL, design/specs/redos-load-harness-d8.md): pure rules, the import-existence guard, and REAL process tests.

The pure tests and the import-existence test run in the default suite. The REAL tests start real worker processes (and, for the smoke run, `claude`),
so they run only with REDOS_HARNESS_REAL=1 and never when the 1-min load is over 45. Each REAL test records its worker PIDs, kills the recorded group in a
`finally` and asserts every PID is gone. No test runs the 35-worker campaign.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from harness import redos_load_harness as h  # noqa: E402

HARNESS = ROOT / "tests" / "harness" / "redos_load_harness.py"
SHIELD = ROOT / "hooks" / "secret-shield"
LOAD_DIR = SHIELD / "tests" / "load"
MAX_REAL_LOAD = 45.0

# ---------------------------------------------------------------- synthetic runner output (format measured from `claude plugin test`, 2026-11-14)

GOOD_VERDICTS = {**{i: "linear" for i in h.LINEAR_IDS}, **{i: "superlinear" for i in h.MUTANT_IDS}}
EXPECTED_FILES = ["hooks/secret-shield/tests/incident.test.ts", h.PATTERNS_TEST_REL, h.PROBE_REL]
Z41_FULL = [f"{h.Z41_DESCRIBE} > {t}" for t in h.Z41_TESTS]


def make_output(
    verdicts: dict[str, str] | None = None,
    *,
    drop_row: str | None = None,
    extra_lines: list[str] | None = None,
    probe_header: bool = True,
    z41: dict[int, str] | None = None,
    collateral: list[str] | None = None,
    row_test_outcome: str = "pass",
    probe_tests: list[str] | None = None,
) -> str:
    """Build a runner output: REDOS-ROW console lines first (they print before the header), then headers with (pass)/(fail) lines and the counts."""
    use = {**GOOD_VERDICTS, **(verdicts or {})}
    lines = ["hooks/secret-shield/tests/incident.test.ts:", "(pass) incident > something [1.00ms]"]
    for row_id, verdict in use.items():
        if row_id != drop_row:
            lines += [f"RES|{row_id}|noise", f"REDOS-ROW {row_id} {h.ROW_KINDS[row_id]} {verdict}"]
    lines += extra_lines or []
    if probe_header:
        lines.append(h.PROBE_REL + ":")
        names = probe_tests if probe_tests is not None else [f"{i} some description 32-256K" for i in h.ROW_KINDS]
        lines += [f"(%s) {h.PROBE_TEST_PREFIX}{n} [10.00ms]" % row_test_outcome for n in names]
    lines.append(h.PATTERNS_TEST_REL + ":")
    for index, full in enumerate(Z41_FULL):
        lines.append(f"({(z41 or {}).get(index, 'pass')}) {full} [5.00ms]")
    lines += [f"(fail) {c} [1.00ms]" for c in collateral or []]
    lines += ["", " 100 pass", " 0 fail", "Ran 100 tests across 3 files. [1.00s]"]
    return "\n".join(lines) + "\n"


def judge(output: str, declared: int = 13) -> h.ProbeJudgement:
    return h.judge_probe(output, EXPECTED_FILES, declared)


# ---------------------------------------------------------------- pure: worker count, ambient, plan


@pytest.mark.parametrize(("cores", "expected"), [(14, 35), (8, 20), (1, 3), (7, 18)])
def test_worker_count_is_two_and_a_half_per_core_rounded_up(cores: int, expected: int) -> None:
    """2.5 workers per core, 35 on the 14-core dev host."""
    assert h.worker_count(cores) == expected


@pytest.mark.parametrize(
    ("samples", "refused"),
    [([1.0, 2.0, 9.79], False), ([1.0, 9.8, 1.0], True), ([0.0, 0.0, 20.0], True), ([0.1, 0.1, 0.1], False)],
)
def test_ambient_refusal_uses_the_maximum_against_point_seven_per_core(samples: list[float], refused: bool) -> None:
    """The ambient check refuses when the highest of the samples reaches 0.7 per core (9.8 on 14 cores)."""
    assert h.ambient_refused(samples, 14) is refused


@pytest.mark.parametrize(("elapsed", "dry", "expected"), [(400.0, 60.0, 20), (400.0, 200.0, 10), (400.0, 3000.0, 0), (2580.0, 10.0, 0), (0.0, 0.0, 20)])
def test_plan_probes_fits_the_cap_at_the_dry_run_duration(elapsed: float, dry: float, expected: int) -> None:
    """K is the largest count up to 20 whose expected end fits the 43 min cap."""
    assert h.plan_probes(h.DEFAULT_CAP_S, elapsed, dry, 20) == expected


# ---------------------------------------------------------------- pure: row and probe verdicts


@pytest.mark.parametrize(
    ("kind", "verdict", "status"),
    [
        ("linear", "linear", "pass"),
        ("linear", "superlinear", "fail"),
        ("linear", "out-of-rounds", "fail"),
        ("linear", "escaped", "undecided"),
        ("mutant", "superlinear", "pass"),
        ("mutant", "linear", "fail"),
        ("mutant", "out-of-rounds", "undecided"),
        ("mutant", "escaped", "undecided"),
        ("linear", "error", "invalid"),
        ("mutant", "error", "invalid"),
    ],
)
def test_row_verdict_table(kind: str, verdict: str, status: str) -> None:
    """Linear rows pass only on linear; mutant rows are detected only on superlinear; escaped and a mutant out of rounds are undecided."""
    assert h.judge_row(kind, verdict) == status


def test_a_clean_probe_passes_and_records_every_row() -> None:
    """13 rows, 6 linear and 7 superlinear mutants, pass the probe and appear in the record with kind, verdict, test outcome and status."""
    j = judge(make_output())
    assert (j.valid, j.status, j.undecided, j.collateral) == (True, "pass", 0, [])
    assert len(j.rows) == 13
    assert j.rows["Q2b"] == {"kind": "mutant", "verdict": "superlinear", "test": "pass", "status": "pass"}
    assert j.z41 == {t: "pass" for t in h.Z41_TESTS}
    assert (j.n_pass, j.n_fail) == (100, 0)


def test_rows_are_judged_from_the_reason_not_from_the_test_outcome() -> None:
    """A mutant row out of rounds fails its test by design and is undecided; a mutant detected with a (fail) test line still counts as detected."""
    undecided = judge(make_output({"Q3": "out-of-rounds"}, row_test_outcome="fail"))
    assert (undecided.status, undecided.undecided, undecided.rows["Q3"]["test"]) == ("undecided", 1, "fail")
    detected = judge(make_output(row_test_outcome="fail"))
    assert detected.status == "pass"


def test_a_failing_row_beats_an_undecided_one_in_the_probe() -> None:
    """A mutant judged linear is a failure even when another row is undecided."""
    assert judge(make_output({"Q1": "linear", "Q2": "escaped"})).status == "fail"


def test_an_error_verdict_makes_the_probe_invalid() -> None:
    """A row whose measurement threw means the probe is broken, not that the estimator decided."""
    j = judge(make_output({"L3": "error"}))
    assert not j.valid and j.status == "invalid"
    assert j.invalid_reason is not None and "L3" in j.invalid_reason


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"drop_row": "Q6"}, "REDOS-ROW missing for Q6"),
        ({"extra_lines": ["REDOS-ROW L1 linear linear"]}, "duplicate REDOS-ROW id: L1"),
        ({"extra_lines": ["REDOS-ROW Z9 mutant superlinear"]}, "unknown REDOS-ROW id: Z9"),
        ({"extra_lines": ["REDOS-ROW Q7"]}, "malformed REDOS-ROW line"),
        ({"extra_lines": ["REDOS-ROW L2d mutant linear"]}, "duplicate REDOS-ROW id: L2d"),
        ({"probe_header": False}, "no header line for"),
        ({"probe_tests": ["L1 a", "L1c b"]}, "2 probe tests reported, 13 declared"),
        ({"probe_tests": [f"{i} d" for i in h.ROW_KINDS][:12] + ["L1 again"]}, "duplicate probe test id: L1"),
    ],
)
def test_invalid_probe_reasons(kwargs: dict[str, object], needle: str) -> None:
    """A missing, duplicated, unknown or malformed REDOS-ROW, a missing header and a row count off the declared one make the probe invalid."""
    j = judge(make_output(**kwargs))  # type: ignore[arg-type]
    assert not j.valid and j.status == "invalid"
    assert j.invalid_reason is not None and needle in j.invalid_reason


def test_a_row_with_the_wrong_kind_or_verdict_is_invalid() -> None:
    """An id printed with the other kind, or with a verdict timing.ts does not produce, is invalid."""
    out = make_output().replace("REDOS-ROW Q1 mutant superlinear", "REDOS-ROW Q1 linear superlinear")
    assert "has kind linear, expected mutant" in (judge(out).invalid_reason or "")
    out = make_output().replace("REDOS-ROW Q1 mutant superlinear", "REDOS-ROW Q1 mutant maybe")
    assert "unknown verdict maybe" in (judge(out).invalid_reason or "")


def test_a_declared_row_count_other_than_thirteen_is_invalid() -> None:
    """probe.load.ts declaring a count other than the 13 expected rows means the probe changed."""
    assert "declares 14 rows" in (judge(make_output(), declared=14).invalid_reason or "")


def test_an_output_without_counts_is_invalid() -> None:
    """A run that printed no pass/fail count lines did not report."""
    out = make_output().replace(" 100 pass\n", "").replace(" 0 fail\n", "")
    assert "no pass/fail count lines" in (judge(out).invalid_reason or "")


def test_z41a13xv_tests_are_matched_by_full_name_and_missing_is_not_a_pass() -> None:
    """The two port-skip tests are read under the patterns.test.ts header; absent, they read missing; failing, they read fail and are not collateral."""
    assert judge(make_output(z41={1: "fail"})).z41[h.Z41_TESTS[1]] == "fail"
    assert judge(make_output(z41={1: "fail"})).collateral == []
    no_z41 = make_output().replace("(pass) " + Z41_FULL[0], "(pass) renamed")
    assert judge(no_z41).z41[h.Z41_TESTS[0]] == "missing"



def test_a_z41a13xv_name_with_a_suffix_reads_as_missing_not_as_a_pass() -> None:
    """A patterns.test.ts line whose name is the Z41A13XV name plus a suffix is not that test: it reads missing, and when it fails it is collateral."""
    suffixed = make_output(z41={0: "fail"}).replace(f"{Z41_FULL[0]} [5.00ms]", f"{Z41_FULL[0]} (renamed) [5.00ms]")
    j = judge(suffixed)
    assert j.z41[h.Z41_TESTS[0]] == "missing" and j.z41[h.Z41_TESTS[1]] == "pass"
    assert j.collateral == [f"{h.PATTERNS_TEST_REL}: {Z41_FULL[0]} (renamed)"]


def test_other_failing_tests_are_collateral_and_do_not_change_the_probe_status() -> None:
    """A failing test elsewhere is recorded by file and name and decides nothing."""
    j = judge(make_output(collateral=["something else breaks"]))
    assert j.status == "pass" and j.collateral == [f"{h.PATTERNS_TEST_REL}: something else breaks"]


# ---------------------------------------------------------------- pure: campaign verdict


def probe_judgement(status: str = "pass", z41: str = "pass") -> h.ProbeJudgement:
    return h.ProbeJudgement(True, None, {}, status, 1 if status == "undecided" else 0, {t: z41 for t in h.Z41_TESTS}, [], 1, 0)


def test_twenty_clean_probes_pass() -> None:
    """1a is met when every row passes in each of 20 probes."""
    v = h.judge_campaign([probe_judgement() for _ in range(20)])
    assert (v.one_a, v.z41a13xv, v.exit_code) == ("pass", "pass", h.EXIT_PASS)


def test_fewer_than_twenty_probes_is_incomplete() -> None:
    """A verdict needs K = 20; fewer probes exit 2."""
    v = h.judge_campaign([probe_judgement() for _ in range(19)])
    assert (v.one_a, v.exit_code) == ("incomplete", h.EXIT_UNFINISHED)


def test_an_undecided_probe_makes_the_campaign_incomplete() -> None:
    """An undecided probe (escaped, mutant out of rounds) is never a pass and never a failure."""
    v = h.judge_campaign([probe_judgement("undecided")] + [probe_judgement() for _ in range(19)])
    assert (v.one_a, v.exit_code) == ("incomplete", h.EXIT_UNFINISHED)


def test_a_definite_failure_beats_incomplete() -> None:
    """One failing probe means 1a is not met whatever the rest say, even with fewer than 20 probes or an undecided one."""
    v = h.judge_campaign([probe_judgement("fail"), probe_judgement("undecided")])
    assert (v.one_a, v.exit_code) == ("fail", h.EXIT_FAIL)


def test_a_failing_z41a13xv_test_fails_the_campaign() -> None:
    """The exit code joins both verdicts: a TRDD-Z41A13XV failure exits 1 even when 1a is met."""
    v = h.judge_campaign([probe_judgement(z41="fail")] + [probe_judgement() for _ in range(19)])
    assert (v.one_a, v.z41a13xv, v.exit_code) == ("pass", "fail", h.EXIT_FAIL)



# ---------------------------------------------------------------- pure: the campaign loop with an injected probe runner (no claude, no worker processes)


class FakeRunner:
    """A probe runner that returns a valid probe taking `seconds[n]` (the last value repeats) and counts its calls; `on_call(n, abort)` runs first."""

    def __init__(self, seconds: list[float], on_call: Callable[[int, threading.Event], None] | None = None) -> None:
        self.seconds = seconds
        self.on_call = on_call
        self.calls = 0

    def __call__(self, claude: str, mod_dir: Path, timeout_s: float, abort: threading.Event) -> h.ProbeRun:
        n = self.calls
        self.calls += 1
        if self.on_call is not None:
            self.on_call(n, abort)
        return h.ProbeRun(0, make_output(), self.seconds[min(n, len(self.seconds) - 1)], False, False, EXPECTED_FILES)


class FakeGroup(h.WorkerGroup):
    """A real worker group with no workers whose dead() answers from the test."""

    dead_pids: Callable[[], list[int]]

    def dead(self) -> list[int]:
        return self.dead_pids()


class SpyRecorder(h.Recorder):
    """A recorder that keeps what it writes and tells the test about each record."""

    def __init__(self, path: Path, hook: Callable[[dict[str, object]], None] | None) -> None:
        super().__init__(path)
        self.records: list[dict[str, object]] = []
        self.hook = hook

    def write(self, record: dict[str, object]) -> None:
        super().write(record)
        self.records.append(record)
        if self.hook is not None:
            self.hook(record)


@dataclass
class Driven:
    status: str
    reason: str | None
    judgements: list[h.ProbeJudgement]
    state: dict[str, object]
    records: list[dict[str, object]]


def drive(
    tmp_path: Path,
    runner: FakeRunner,
    *,
    dead: Callable[[h.Sampler, FakeRunner], list[int]] = lambda sampler, runner: [],
    on_write: Callable[[dict[str, object], h.Sampler], None] | None = None,
    cap_s: float = h.DEFAULT_CAP_S,
    started_ago: float = 0.0,
    max_probes: int = 3,
) -> Driven:
    """Run `_drive` with workers=0: the sampler is never started, so the test sets `sampler.aborted` itself."""
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    group = FakeGroup(write_fd)
    cfg = h.Config(workers=0, settle_s=0.0, cap_s=cap_s, max_probes=max_probes, cores=14)
    sampler = h.Sampler(lambda: 1.0, 0.1, h.ABORT_LOAD, group)
    group.dead_pids = lambda: dead(sampler, runner)
    recorder = SpyRecorder(tmp_path / "record.jsonl", None if on_write is None else lambda record: on_write(record, sampler))
    judgements: list[h.ProbeJudgement] = []
    state: dict[str, object] = {"planned": None, "dry_s": None}
    try:
        status, reason = h._drive(cfg, lambda: 1.0, "claude", group, sampler, recorder, time.monotonic() - started_ago, 0.0, 13, judgements, state, runner)
    finally:
        group.reap()
    return Driven(status, reason, judgements, state, recorder.records)


def test_drive_runs_one_dry_probe_and_k_judged_probes_and_completes(tmp_path: Path) -> None:
    """K=3 means exactly 4 runner calls: the dry run (excluded from the judgements) and 3 judged probes."""
    runner = FakeRunner([10.0])
    d = drive(tmp_path, runner)
    assert (d.status, d.reason, runner.calls, len(d.judgements), d.state["planned"]) == ("complete", None, 4, 3, 3)
    assert [r["dry_run"] for r in d.records] == [True, False, False, False]


@pytest.mark.parametrize("when", ["during a probe", "between probes"])
def test_a_sampler_abort_is_aborted_not_invalid_even_though_the_reaped_group_reads_dead(tmp_path: Path, when: str) -> None:
    """The sampler reaps the group when it aborts, so dead() then lists workers; the campaign must still say `aborted` (the load), not a dead worker."""

    def reaped(sampler: h.Sampler, runner: FakeRunner) -> list[int]:
        return [4242] if sampler.aborted.is_set() else []

    def abort_in_probe(n: int, abort: threading.Event) -> None:
        if n == 1:
            abort.set()

    def abort_after_record(record: dict[str, object], sampler: h.Sampler) -> None:
        if record["index"] == 1:
            sampler.aborted.set()

    if when == "during a probe":
        runner, on_write = FakeRunner([10.0], abort_in_probe), None
    else:
        runner, on_write = FakeRunner([10.0]), abort_after_record
    d = drive(tmp_path, runner, dead=reaped, on_write=on_write)
    assert d.status == "aborted" and (d.reason or "").startswith("load over")
    assert runner.calls == 2


def test_a_dead_worker_is_recorded_as_invalid_with_a_dead_worker_reason(tmp_path: Path) -> None:
    """A worker found dead before a probe, or after one, ends the campaign as status `invalid` whose reason starts `dead worker` (one vocabulary, spec "Liveness")."""
    runner = FakeRunner([10.0])
    before = drive(tmp_path, runner, dead=lambda sampler, runner: [4242])
    assert before.status == "invalid" and (before.reason or "").startswith("dead worker: ") and runner.calls == 0
    runner = FakeRunner([10.0])
    after = drive(tmp_path, runner, dead=lambda sampler, runner: [4242] if runner.calls >= 1 else [])
    assert after.status == "invalid" and (after.reason or "").startswith("dead worker: ") and runner.calls == 1
    assert after.records[0]["status"] == "invalid"


def test_the_cap_guard_stops_before_a_probe_that_would_pass_the_cap(tmp_path: Path) -> None:
    """With 50 s used of a 100 s cap, the dry run (10 s) fits and sets K=3, but after a probe that took 60 s no further probe starts."""
    runner = FakeRunner([10.0, 60.0])
    d = drive(tmp_path, runner, cap_s=100.0, started_ago=50.0)
    assert d.status == "aborted" and (d.reason or "").startswith("cap would be passed")
    assert (runner.calls, len(d.judgements)) == (2, 1)


@pytest.mark.skipif(shutil.which("claude") is None, reason="`claude` is not on PATH (run_campaign looks it up; the probe itself is the fake runner)")
def test_run_campaign_passes_the_injected_runner_through(tmp_path: Path) -> None:
    """run_campaign with 0 workers and a fake runner runs the dry run plus one probe and records a `complete` campaign (1 probe is fewer than 20, so exit 2)."""
    cfg = h.Config(workers=0, settle_s=0.0, cap_s=600.0, max_probes=1, ambient_interval_s=0.0, sample_interval_s=0.1, cores=14)
    runner = FakeRunner([5.0])
    record = tmp_path / "campaign.jsonl"
    code = h.run_campaign(cfg, lambda: 1.0, h.Recorder(record), runner=runner)
    campaign = json.loads(record.read_text(encoding="utf-8").splitlines()[-1])
    assert (runner.calls, campaign["status"], campaign["probes_judged"], code) == (2, "complete", 1, h.EXIT_UNFINISHED)


# ---------------------------------------------------------------- probe file facts


def test_probe_declares_the_ids_the_harness_expects() -> None:
    """probe.load.ts declares 13 rows and the ids L1..L3c (linear) and Q1..Q6 (mutant) the harness checks, in the kind the harness expects."""
    assert h.declared_rows(SHIELD) == 13
    text = (LOAD_DIR / "probe.load.ts").read_text(encoding="utf-8")
    found = {m.group(2): ("linear" if m.group(3) == "true" else "mutant") for m in re.finditer(r"\{ id: '((\S+) [^']*)', expectLinear: (true|false)", text)}
    assert found == h.ROW_KINDS


# ---------------------------------------------------------------- import-existence guard


def imported_names(source: str) -> dict[str, set[str]]:
    """Names imported from `../../<module>` in a .ts file (incl. `import type` and multi-line lists), keyed by module path."""
    found: dict[str, set[str]] = {}
    for match in re.finditer(r"import\s+(?:type\s+)?\{([^}]*)\}\s+from\s+'(\.\./\.\./[^']+)'", source):
        names = {re.sub(r"^type\s+", "", part.strip()).split(" as ")[0].strip() for part in match.group(1).split(",") if part.strip()}
        found.setdefault(match.group(2)[len("../../") :], set()).update(names)
    return found


def exports(source: str, name: str) -> bool:
    """True when `source` exports `name` by declaration or by an `export { ... }` list (a re-export included)."""
    declared = re.search(rf"^export\s+(?:declare\s+)?(?:async\s+)?(?:const|let|var|function\*?|class|type|interface|enum)\s+{re.escape(name)}\b", source, re.MULTILINE)
    listed = re.search(rf"^export\s+(?:type\s+)?\{{[^}}]*\b{re.escape(name)}\b[^}}]*\}}", source, re.MULTILINE)
    return declared is not None or listed is not None


def test_the_export_helper_can_fail() -> None:
    """The guard's helper sees a missing export, a type export, a listed re-export and a multi-line import."""
    src = "export const a = 1\nexport type T = {}\nexport { b, c as d } from './x'\n"
    assert exports(src, "a") and exports(src, "T") and exports(src, "b")
    assert not exports(src, "gone") and not exports(src, "ab")
    assert imported_names("import {\n  x,\n  type Y,\n  z as w,\n} from '../../m'\n") == {"m": {"x", "Y", "z"}}


def test_every_name_the_load_files_import_from_the_shield_is_still_exported() -> None:
    """The only guard between releases: each name probe.load.ts, old-quadratic.ts and timing.ts import from ../../patterns and ../../rules/* must still be exported there."""
    wanted: dict[str, set[str]] = {}
    for file in ("probe.load.ts", "old-quadratic.ts", "timing.ts"):
        for module, names in imported_names((LOAD_DIR / file).read_text(encoding="utf-8")).items():
            wanted.setdefault(module, set()).update(names)
    # WHY non-vacuous: a parser that finds nothing would pass every check below.
    assert {"applyRule", "JSON_ESCAPED", "redact"} <= wanted["patterns"]
    assert "jwt" in wanted["rules/key-material"] and "Rule" in wanted["rules/rule"]
    missing = []
    for module, names in sorted(wanted.items()):
        source = (SHIELD / f"{module}.ts").read_text(encoding="utf-8")
        missing += [f"{module}: {name}" for name in sorted(names) if not exports(source, name)]
    assert not missing, f"imported by hooks/secret-shield/tests/load but not exported: {missing}"


# ---------------------------------------------------------------- REAL tests (REDOS_HARNESS_REAL=1)


def real_gate() -> None:
    if os.environ.get("REDOS_HARNESS_REAL") != "1":
        pytest.skip("real process test: set REDOS_HARNESS_REAL=1")
    load = os.getloadavg()[0]
    if load > MAX_REAL_LOAD:
        pytest.skip(f"1-min load {load:.1f} is over {MAX_REAL_LOAD}: not starting real workers")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_gone(pids: list[int], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while any(alive(p) for p in pids) and time.monotonic() < deadline:
        time.sleep(0.2)
    return not any(alive(p) for p in pids)


def kill_recorded_group(pgid: int, pids: list[int]) -> None:
    """Kill the recorded group only while a recorded PID still exists (an exited group's id may be recycled), then assert every PID is gone."""
    if any(alive(p) for p in pids):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    assert wait_gone(pids, 10), f"workers still alive: {[p for p in pids if alive(p)]}"


def test_real_abort_at_reading_61_reaps_every_worker() -> None:
    """A sampler fed a reading of 61 while real workers run kills the group; every recorded PID is reaped (waitpid finds no child, kill(pid, 0) raises)."""
    real_gate()
    group = h.WorkerGroup.start(3, 30)
    pids = group.pids
    print(f"abort test workers pgid={group.pgid} pids={pids}")
    sampler = h.Sampler(lambda: 61.0, 0.1, h.ABORT_LOAD, group)
    try:
        assert all(alive(p) for p in pids)
        sampler.start()
        assert sampler.aborted.wait(15), "the sampler did not abort on a reading of 61"
        assert sampler.peak == 61.0
        for pid in pids:
            with pytest.raises(ChildProcessError):
                os.waitpid(pid, os.WNOHANG)
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        sampler.stop()
        kill_recorded_group(group.pgid, pids)
        group.reap()


def test_real_orphaned_workers_exit_when_the_harness_is_sigkilled() -> None:
    """SIGKILL of the harness in workers-only mode closes the stdin pipe; its workers exit within 10 s although their lifetime is 30 s."""
    real_gate()
    proc = subprocess.Popen([sys.executable, str(HARNESS), "--workers-only", "--workers", "3", "--lifetime", "30"], stdout=subprocess.PIPE, text=True, start_new_session=True)
    pids: list[int] = []
    pgid = 0
    try:
        assert proc.stdout is not None
        info = json.loads(proc.stdout.readline())
        pids, pgid = info["pids"], info["pgid"]
        print(f"orphan test harness pid={info['harness_pid']} pgid={pgid} workers={pids}")
        assert len(pids) == 3 and all(alive(p) for p in pids)
        os.kill(info["harness_pid"], signal.SIGKILL)
        proc.wait(timeout=10)
        assert wait_gone(pids, 10), "workers outlived the SIGKILLed harness by more than 10 s"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        if pids:
            kill_recorded_group(pgid, pids)


# WHY the marker: tests/sandbox_guard.py denies any binary not allow-listed; the smoke run needs the real `claude` (its mods test kit), so it opts in explicitly.
@pytest.mark.real_subprocess("claude")
@pytest.mark.skipif(shutil.which("claude") is None, reason="`claude` is not on PATH")
def test_real_smoke_one_probe_two_workers_runs_end_to_end(tmp_path: Path) -> None:
    """K=1, N=2 proves only that the harness runs end to end: a dry run and one probe are recorded, valid, and the workers are gone.

    Its constant load source (`lambda: 1.0`) disables the ambient refusal and the >60 abort, and it never exercises `system_load()` (the real `os.getloadavg()` reading).
    """
    real_gate()
    # WHY lifetime 150 s, not the spec's ~30 s: the liveness poll ends the campaign when a worker exits, and a dry run plus one probe take about 40 s idle (spec "Tests" says
    # ~30 s for the abort and orphan tests, which run no probe). WHY a constant load source: the real 1-min load on the dev host is over the 0.7 per core ambient refusal.
    cfg = h.Config(workers=2, lifetime_s=150, settle_s=1, cap_s=600, max_probes=1, ambient_interval_s=0, sample_interval_s=0.5)
    record = tmp_path / "smoke.jsonl"
    groups: list[h.WorkerGroup] = []
    try:
        code = h.run_campaign(cfg, lambda: 1.0, h.Recorder(record), groups.append)
    finally:
        for group in groups:
            print(f"smoke workers pgid={group.pgid} pids={group.pids}")
            kill_recorded_group(group.pgid, group.pids)
            group.reap()
    lines = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]
    probes, campaign = [x for x in lines if x["kind"] == "probe"], lines[-1]
    assert campaign["kind"] == "campaign" and campaign["status"] == "complete", campaign
    assert [p["dry_run"] for p in probes] == [True, False]
    assert all(p["invalid_reason"] is None and len(p["rows"]) == 13 for p in probes), probes
    # K=1 makes the campaign's Z41A13XV verdict always incomplete, so only this check proves the exact names match real runner output; whether they pass is left to the step 5 idle check and the campaign, because the smoke may run under load.
    assert all(p["z41a13xv"][t] in ("pass", "fail") for p in probes if not p["dry_run"] for t in h.Z41_TESTS), probes
    assert code in (h.EXIT_FAIL, h.EXIT_UNFINISHED) and code == campaign["exit_code"]
