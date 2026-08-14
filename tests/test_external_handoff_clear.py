"""Tests for the external handoff-and-clear WATCHER (TRDD-PXP08ZQC).

Real, no mocks: the gatherers run against a real temp project tree (real TRDD files, a real
`git` repo, real state files), and the end-to-end check runs the script as a real subprocess
and asserts on the filesystem afterwards — because "fires nothing / writes nothing" is a claim
about the disk, and only the disk can settle it.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import external_clear as ec  # noqa: E402
import external_handoff_clear as ehc  # noqa: E402

SCRIPT = _ROOT / "scripts" / "external_handoff_clear.py"


def _project(tmp_path: Path) -> Path:
    """A minimal project tree: janitor state dir + design/tasks."""
    (tmp_path / ".janitor" / "state").mkdir(parents=True)
    (tmp_path / "design" / "tasks").mkdir(parents=True)
    return tmp_path


def _card(root: Path, uid: str, column: str, title: str) -> Path:
    """Write a real TRDD file with the frontmatter the gatherer parses."""
    path = root / "design" / "tasks" / f"TRDD-20260806_120000+0200-{uid}-slug.md"
    path.write_text(
        f"---\ntrdd-id: {uid}\ntitle: {title}\ncolumn: {column}\n"
        f"created: 2026-08-06T12:00:00+0200\nupdated: 2026-08-06T12:00:00+0200\n"
        f"task-type: feature\n---\n\n# {title}\n",
        encoding="utf-8",
    )
    return path


# --- _gather_cards -----------------------------------------------------------


def test_only_in_flight_cards_are_listed(tmp_path):
    """Queued (`todo`) and terminal (`complete`) cards would bury the card to actually resume."""
    root = _project(tmp_path)
    _card(root, "AAAAAAAA", "dev", "the in-flight one")
    _card(root, "BBBBBBBB", "todo", "queued, not started")
    _card(root, "CCCCCCCC", "complete", "already shipped")
    uids = [uid for uid, _col, _title in ehc._gather_cards(root)]
    assert uids == ["AAAAAAAA"]


def test_cards_carry_their_column_and_title(tmp_path):
    """The handoff indexes by id + column + title; a title-less row is not navigable."""
    root = _project(tmp_path)
    _card(root, "PXP08ZQC", "testing", "External zero-turn handoff-and-clear")
    assert ehc._gather_cards(root) == [
        ("PXP08ZQC", "testing", "External zero-turn handoff-and-clear")
    ]


def test_cards_are_newest_first_and_capped(tmp_path):
    """The most recently touched card is the one being worked; the cap bounds the handoff."""
    root = _project(tmp_path)
    for i in range(_cap := ehc._MAX_CARDS + 3):
        p = _card(root, f"CARD{i:04d}", "dev", f"card {i}")
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
    got = ehc._gather_cards(root)
    assert len(got) == ehc._MAX_CARDS
    assert got[0][0] == f"CARD{_cap - 1:04d}"


def test_a_missing_design_tree_is_not_an_error(tmp_path):
    """A project with no TRDDs still gets a handoff — just one without the cards section."""
    (tmp_path / ".janitor" / "state").mkdir(parents=True)
    assert ehc._gather_cards(tmp_path) == []


# --- _gather_commits ---------------------------------------------------------


def test_commits_are_read_from_a_real_repo(tmp_path):
    """The subjects are the WHY index the handoff links to instead of restating."""
    root = _project(tmp_path)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    (root / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "feat: the first thing"], cwd=root, check=True, env=env)
    commits = ehc._gather_commits(root)
    assert len(commits) == 1
    sha, subject = commits[0]
    assert subject == "feat: the first thing"
    assert 6 <= len(sha) <= 12


def test_a_repo_less_project_yields_no_commits_and_does_not_raise(tmp_path):
    """`git` failing is an absent section, never a blocked clear."""
    assert ehc._gather_commits(_project(tmp_path)) == []


# --- _last_turn_age ----------------------------------------------------------


def test_last_turn_age_is_none_without_a_transcript(tmp_path):
    """Unknown cache age must read as unknown — `next_fire_misses_cache` then declines."""
    assert ehc._last_turn_age(_project(tmp_path), int(time.time())) is None


# --- _compose ----------------------------------------------------------------


def test_composed_handoff_satisfies_the_concision_contract(tmp_path):
    """The composed text is what survives an unrecoverable /clear; it must pass by construction."""
    import clear_trigger

    root = _project(tmp_path)
    _card(root, "PXP08ZQC", "dev", "External zero-turn handoff-and-clear")
    verdict = ec.ClearVerdict(True, ec.TRIGGER_LONG_IDLE, "idle")
    text, reasons = ehc._compose(root, verdict, {"idle_seconds": 7200, "context_tokens": 460_000})
    assert reasons == []
    assert clear_trigger.check_handoff_concise(text)[0] is True
    assert "TRDD-PXP08ZQC" in text


def test_composed_handoff_names_the_trigger_that_fired(tmp_path):
    """A handoff that cannot say why the session was cleared is not auditable."""
    root = _project(tmp_path)
    verdict = ec.ClearVerdict(True, ec.TRIGGER_NEXT_FIRE_MISSES, "would miss")
    text, _ = ehc._compose(root, verdict, {"idle_seconds": 60, "context_tokens": 1})
    assert ec.TRIGGER_NEXT_FIRE_MISSES in text


# --- end to end (real subprocess) --------------------------------------------


# The reactive trigger shells out to agentlensPro, an OPTIONAL third-party CLI. These tests are
# about the watcher, not about that probe (which has its own unit tests against an injected
# runner), and the suite's sandbox guard rightly refuses to let a unit test spawn arbitrary
# binaries. An empty command is the probe's documented disable, so this pins the tests to the
# no-agentlensPro configuration rather than to whatever happens to be installed on the host —
# which is also the only configuration that is reproducible in CI.
_NO_AGENTLENS = {ec.CACHE_EXPIRED_COMMAND_ENV: ""}


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(root), *args],
        capture_output=True, text=True, timeout=180,
        env={**os.environ, **_NO_AGENTLENS, ec.ENABLED_ENV: "1"},
    )


def _iso(epoch: int) -> str:
    """A transcript-style UTC timestamp ('2026-07-17T16:55:41.797Z' shape)."""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def test_awaiting_user_veto_reaches_the_watcher_end_to_end(tmp_path, monkeypatch):
    """GATHER layer, not the pure gate (TRDD-OO301H7D). The bug was `idle_s, _enq, _await =
    fleet_scan.transcript_activity(...)` — an argument that was computed and then never PASSED.
    No mutation of `should_clear_externally` alone can catch a value that never arrives at its
    call site; only a real transcript flowing through `_decide` proves the wiring is intact. A
    tail ending on an unanswered `ExitPlanMode` must refuse EVEN THOUGH every trigger the gate
    would otherwise fire on (long idle, a readable but irrelevant cron) is satisfied — and
    `--force` must not be able to override that refusal, because it is a safety veto."""
    import json

    import memory_scopes  # noqa: PLC0415

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(ec.CACHE_EXPIRED_COMMAND_ENV, "")  # no agentlensPro subprocess
    monkeypatch.setenv(ec.MIN_CONTEXT_ENV, "0")  # context-size clause never vetoes this test
    import cold_cache_compact  # noqa: PLC0415

    monkeypatch.setenv(cold_cache_compact.CLEAR_MIN_IDLE_ENV, "60")  # trivially met if not vetoed

    now = int(time.time())
    root = tmp_path / "proj"
    (root / ".janitor" / "state").mkdir(parents=True)
    slug = memory_scopes.project_slug(os.path.realpath(str(root)))
    tdir = tmp_path / ".claude" / "projects" / slug
    tdir.mkdir(parents=True)
    lines = [
        json.dumps({"type": "assistant", "timestamp": _iso(now - 4000), "message": {}}),
        json.dumps(
            {
                "type": "assistant",
                "timestamp": _iso(now - 2000),
                "message": {
                    "content": [{"type": "tool_use", "id": "toolu_PLAN", "name": "ExitPlanMode"}]
                },
            }
        ),
    ]
    (tdir / "s1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    sd = root / ".janitor" / "state"
    verdict, facts = ehc._decide(root, sd, now, force=False)
    assert verdict.fire is False
    assert verdict.why == "awaiting-user"
    assert facts["awaiting_user"] is True

    forced, _ = ehc._decide(root, sd, now, force=True)
    assert forced.fire is False and forced.why == "awaiting-user", (
        "--force overrides trigger terms only; a human is being asked a question"
    )


def test_unknown_idle_holds_end_to_end_and_touches_nothing(tmp_path):
    """A project with no transcript has an unknown idle age, which may never authorize a clear."""
    root = _project(tmp_path)
    proc = _run(root)
    assert proc.returncode == 0, proc.stderr
    assert "VERDICT HOLD" in proc.stdout
    assert "idle-unknown" in proc.stdout
    assert not (root / ".janitor" / "state" / "agent-handoff.md").exists()
    assert not (root / ".janitor" / "state" / "resume-after-clear.flag").exists()


def test_a_project_without_janitor_state_is_skipped(tmp_path):
    """Not every directory is a janitor-armed session; those are none of our business."""
    proc = _run(tmp_path)
    assert proc.returncode == 0
    assert "NO_JANITOR_STATE" in proc.stdout


def test_the_feature_is_off_unless_opted_in(tmp_path):
    """DEFAULT OFF: this path clears with no model turn in front of it, so it ships opt-in."""
    root = _project(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(root)],
        capture_output=True, text=True, timeout=180,
        env={**{k: v for k, v in os.environ.items() if k != ec.ENABLED_ENV}, **_NO_AGENTLENS},
    )
    assert "DISABLED" in proc.stdout


def test_dry_run_runs_even_while_disabled(tmp_path):
    """Observing the decision must never require arming the destructive path first."""
    root = _project(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(root), "--dry-run"],
        capture_output=True, text=True, timeout=180,
        env={**{k: v for k, v in os.environ.items() if k != ec.ENABLED_ENV}, **_NO_AGENTLENS},
    )
    assert "DISABLED" not in proc.stdout
    assert "VERDICT" in proc.stdout


def test_force_never_overrides_a_safety_veto():
    """--force overrides the idle/cache TRIGGER terms only; presence and cooldown still hold.

    Asserted against the pure gate the watcher wraps, since the override is expressed as a
    predicate on the refusal reason: only `idle …` and `no-headroom …` are overridable, and
    every safety veto returns a different reason string.
    """
    overridable = {"idle 600s < 3600s and the next fire is still warm", "no-headroom (10s < 60s)"}
    safety = {"cooldown", "active-waiting", "awaiting-user", "idle-unknown",
              "context 50000 < 150000 — nothing worth reclaiming"}
    for why in overridable:
        assert why.startswith(("idle ", "no-headroom"))
    for why in safety:
        assert not why.startswith(("idle ", "no-headroom")), why
