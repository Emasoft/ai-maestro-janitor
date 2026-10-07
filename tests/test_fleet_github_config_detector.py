"""Tests for the fleet-github-config SURFACE detector (TRDD-157OH2D7).

The detector reads ONLY the daemon's findings JSON (no gh) and emits ONE deduped drift line
+ the fix-skill pointer. Run as a real subprocess (no mocks) with the global-state dir and the
project dir redirected to tmp, so the real machine state is untouched.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "fleet-github-config.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"


def _run(
    tmp_path: Path,
    findings: list[dict] | None,
    *,
    disabled: bool = False,
    age_s: int = 0,
    server: list[dict] | None = None,
    server_age_s: int = 0,
) -> subprocess.CompletedProcess[str]:
    gsd = tmp_path / "global-state"
    gsd.mkdir(parents=True, exist_ok=True)
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    # HOME is ALWAYS redirected: the detector also reads `~/.aimaestro/github-config-findings.json`,
    # and without this a run on a machine with a real server audit would race the fixtures.
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    if findings is not None:
        (gsd / "github-config-findings.json").write_text(
            # A FRESH timestamp. This was `1` (epoch 1970) as a don't-care sentinel, which
            # stopped being a don't-care when the age gate landed (TRDD-88ZVEQY7): a payload
            # 56 years old is correctly WITHHELD, so every findings assertion below would be
            # testing the staleness path instead of the path it names. Staleness has its own
            # tests; these fixtures must represent a payload a live sweep just wrote.
            json.dumps({"generated_at": int(time.time()) - age_s, "repos_scanned": 13, "findings": findings}),
            encoding="utf-8",
        )
    if server is not None:
        (home / ".aimaestro").mkdir(parents=True, exist_ok=True)
        (home / ".aimaestro" / "github-config-findings.json").write_text(
            json.dumps({"generated_at": int(time.time()) - server_age_s, "repos_scanned": 14, "findings": server}),
            encoding="utf-8",
        )
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["JANITOR_GLOBAL_STATE_DIR"] = str(gsd)
    env["CLAUDE_PROJECT_DIR"] = str(proj)
    env.pop("CLAUDE_PLUGIN_OPTION_FLEET_GITHUB_CONFIG_ENABLED", None)
    if disabled:
        env["CLAUDE_PLUGIN_OPTION_FLEET_GITHUB_CONFIG_ENABLED"] = "0"
    return subprocess.run(
        [sys.executable, str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60
    )


def test_silent_when_no_findings_file(tmp_path: Path) -> None:
    """Daemon hasn't written a file yet → silent (the common early state)."""
    r = _run(tmp_path, None)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_silent_when_findings_empty(tmp_path: Path) -> None:
    r = _run(tmp_path, [])
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_a_stale_payload_withholds_findings_and_says_so(tmp_path: Path) -> None:
    """TRDD-88ZVEQY7 / janitor#244 — the peer nearly mutated a COMPLIANT repo acting on an
    18-day-old claim. Past 4x the 6h cadence the findings are WITHHELD and replaced by one
    line naming the staleness. Not silence: "nobody audited you in days" must never be
    presented as "you are clean"."""
    _with_origin(tmp_path, "o/mine")
    r = _run(tmp_path, [{"slug": "o/mine", "code": "UNPROTECTED", "detail": "d"}], age_s=30 * 86400)
    assert r.returncode == 0, r.stderr
    assert "WITHHELD" in r.stdout and "Nothing is claimed" in r.stdout
    assert "30.0d old" in r.stdout
    # The withheld verdict itself must not leak through.
    assert "UNPROTECTED" not in r.stdout


def test_a_fresh_payload_carries_the_evidence_age(tmp_path: Path) -> None:
    """Every surfaced line states how old its evidence is, so the reader can check the
    verdict instead of taking it on faith."""
    _with_origin(tmp_path, "o/mine")
    r = _run(tmp_path, [{"slug": "o/mine", "code": "UNPROTECTED", "detail": "d"}], age_s=8 * 3600)
    assert r.returncode == 0, r.stderr
    assert "UNPROTECTED" in r.stdout and "audit 0.3d old" in r.stdout

    # Below the 0.1d display floor the clause still appears — it reads "fresh" rather than
    # vanishing, because an ABSENT age is indistinguishable from a recent one to a hurried
    # reader, which is the failure this card closes.
    other = tmp_path / "sub"
    _with_origin(other, "o/mine")
    r2 = _run(other, [{"slug": "o/mine", "code": "UNPROTECTED", "detail": "d"}], age_s=120)
    assert "audit fresh" in r2.stdout


def test_emits_line_about_this_repo_only(tmp_path: Path) -> None:
    """Per-project channeling (user directive 2026-07-17): the line names THIS repo's
    findings and the slug-scoped fix — and carries NOTHING about any other repo (not its
    name, not its finding class): wrong skills, wrong budget, forbidden cross-repo action,
    and a data-exfiltration surface otherwise."""
    _with_origin(tmp_path, "o/mine")
    r = _run(tmp_path, [
        {"slug": "o/mine", "code": "UNPROTECTED", "detail": "d"},
        {"slug": "o/other", "code": "LINEAR_HISTORY", "detail": "d"},
    ])
    assert r.returncode == 0, r.stderr
    assert "[github-config]" in r.stdout
    assert "o/mine" in r.stdout and "UNPROTECTED" in r.stdout
    assert "/janitor-github-config-fix --slug o/mine" in r.stdout
    assert "o/other" not in r.stdout
    assert "linear_history" not in r.stdout and "LINEAR_HISTORY" not in r.stdout


def test_silent_when_only_other_repos_drift(tmp_path: Path) -> None:
    """The rest of the fleet's problems are INVISIBLE here — they route to their own
    sessions, or to the human via the daemon channel (TRDD-4649ZLE0), never to us."""
    _with_origin(tmp_path, "o/mine")
    r = _run(tmp_path, [{"slug": "o/other", "code": "UNPROTECTED", "detail": "d"}])
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_silent_when_project_has_no_github_origin(tmp_path: Path) -> None:
    """No resolvable slug ⇒ the session is unattributable ⇒ it receives NOTHING —
    the fallback is silence, never fleet data."""
    r = _run(tmp_path, [{"slug": "o/a", "code": "UNPROTECTED", "detail": "d"}])
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_deduped_on_second_run(tmp_path: Path) -> None:
    """Same finding set for OUR repo → fires once, silent on repeat (content-hash dedupe)."""
    _with_origin(tmp_path, "o/a")
    findings = [{"slug": "o/a", "code": "UNPROTECTED", "detail": "d"}]
    assert "[github-config]" in _run(tmp_path, findings).stdout
    # second run against the SAME tmp (seen-file persists) with the same findings → silent
    r2 = _run(tmp_path, findings)
    assert r2.returncode == 0, r2.stderr
    assert r2.stdout == ""


def test_reemits_when_our_finding_set_changes_but_not_for_other_repos(tmp_path: Path) -> None:
    """The dedupe digest is scoped to OUR repo: a new gap in OUR repo re-alerts; a change
    in ANOTHER repo neither re-alerts nor silences this session."""
    _with_origin(tmp_path, "o/a")
    assert "[github-config]" in _run(
        tmp_path, [{"slug": "o/a", "code": "UNPROTECTED", "detail": "d"}]
    ).stdout
    # ANOTHER repo's set changes, ours unchanged → still silent (per-repo digest).
    r2 = _run(tmp_path, [
        {"slug": "o/a", "code": "UNPROTECTED", "detail": "d"},
        {"slug": "o/b", "code": "LINEAR_HISTORY", "detail": "d"},
    ])
    assert r2.stdout == ""
    # OUR set changes → new digest → fires again, still naming only us.
    r3 = _run(tmp_path, [
        {"slug": "o/a", "code": "UNPROTECTED", "detail": "d"},
        {"slug": "o/a", "code": "NO_CI", "detail": "d"},
        {"slug": "o/b", "code": "LINEAR_HISTORY", "detail": "d"},
    ])
    assert "[github-config]" in r3.stdout and "o/b" not in r3.stdout


def test_disabled_env_silent(tmp_path: Path) -> None:
    r = _run(tmp_path, [{"slug": "o/a", "code": "UNPROTECTED", "detail": "d"}], disabled=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


# ---- TRDD-CGYMUKO6: it PROPOSES for this repo, and NEVER for another one ----


def _with_origin(tmp_path: Path, slug: str) -> Path:
    """Give the tmp project a GitHub origin, so the detector can recognise itself in the fleet."""
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", f"https://github.com/{slug}.git"], cwd=proj, check=True
    )
    return proj


def _proposals(tmp_path: Path) -> list[Path]:
    """OPEN proposals: a withdrawn card stays in proposals/ as `column: refused` (owner ruling
    2026-09-24, janitor#309/#329), so it is not counted as open."""
    return [
        p
        for p in sorted((tmp_path / "proj" / "design" / "proposals").glob("TRDD-*.md"))
        if "column: refused" not in p.read_text(encoding="utf-8")
    ]


def test_proposes_a_fix_when_THIS_repo_is_the_drifted_one(tmp_path: Path) -> None:
    """The fleet line only NOTIFIES. For the repo we are actually standing in, the janitor also
    proposes the fix and hands back the one command that authorizes it."""
    _with_origin(tmp_path, "o/a")

    r = _run(tmp_path, [{"slug": "o/a", "code": "UNPROTECTED", "detail": "d"}])

    assert "GHCFG-001" in r.stdout
    assert "/janitor-support-open-ticket TRDD-" in r.stdout
    assert len(_proposals(tmp_path)) == 1


def test_NEVER_writes_a_proposal_OR_a_line_about_ANOTHER_repo(tmp_path: Path) -> None:
    """The load-bearing boundary, TIGHTENED by the user directive (2026-07-17): another
    repo's drift produces NEITHER a proposal in this board NOR a drift line in this
    session. (The pre-directive contract still emitted the fleet summary line here — that
    was the cross-project leak: wrong skills, wrong budget, forbidden cross-repo action,
    exfiltration into weaker-protected projects.) The other repo is reached in ITS OWN
    session, or via the daemon's human channel (TRDD-4649ZLE0) — never through us."""
    _with_origin(tmp_path, "o/mine")

    r = _run(tmp_path, [{"slug": "o/someone-else", "code": "UNPROTECTED", "detail": "d"}])

    assert r.stdout == "", "another repo's drift must be INVISIBLE here"
    assert _proposals(tmp_path) == [], "no TRDD about a repo we are not in"


def test_a_repo_fixed_while_the_fleet_is_still_dirty_has_its_proposal_WITHDRAWN(tmp_path: Path) -> None:
    """The clear path that the fleet-is-clean check alone would miss: our repo gets fixed while some
    OTHER repo is still broken. Without this, the stale proposal sits on our board forever."""
    _with_origin(tmp_path, "o/mine")
    assert "GHCFG-001" in _run(tmp_path, [{"slug": "o/mine", "code": "UNPROTECTED", "detail": "d"}]).stdout
    assert len(_proposals(tmp_path)) == 1

    _run(tmp_path, [{"slug": "o/other", "code": "UNPROTECTED", "detail": "d"}])

    assert _proposals(tmp_path) == []


# ── the server's findings file (janitor#197 ask 2) ────────────────────────────────────
# ai-maestro absorbs `github-config-audit` and publishes a wire-identical payload — but to
# `~/.aimaestro/`, because a standing owner directive on that project limits its writes to
# `~/.aimaestro` and `~/agents`. It cannot reach into our state dir, so the consumer reaches
# across. Selection is by `generated_at`, NOT by a server-liveness probe.
#
# These call `_read_findings()` DIRECTLY rather than driving the detector as a subprocess.
# A subprocess test here would be vacuous: the tmp project has no resolvable repo slug, so the
# detector exits 0 silently down every path and `returncode == 0` would assert nothing about
# which file was read. The new logic lives in `_read_findings`, so that is what gets tested.


def _load_detector():
    import importlib.util
    spec = importlib.util.spec_from_file_location("fgc_under_test", _DETECTOR)
    assert spec is not None and spec.loader is not None, f"cannot load {_DETECTOR}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _payload(when: str) -> dict:
    return {"generated_at": when, "repos_scanned": 14, "findings": []}


def _stage(tmp_path: Path, monkeypatch, *, ours: object = None, theirs: object = None):
    """Write either/both findings files and point the module at them. Returns the module."""
    gsd = tmp_path / "global-state"
    gsd.mkdir(parents=True, exist_ok=True)
    home = tmp_path / "home"
    (home / ".aimaestro").mkdir(parents=True, exist_ok=True)
    if ours is not None:
        (gsd / "github-config-findings.json").write_text(
            ours if isinstance(ours, str) else json.dumps(ours), encoding="utf-8")
    if theirs is not None:
        (home / ".aimaestro" / "github-config-findings.json").write_text(
            theirs if isinstance(theirs, str) else json.dumps(theirs), encoding="utf-8")
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("HOME", str(home))
    mod = _load_detector()
    monkeypatch.setattr(mod.gs, "global_state_dir", lambda: gsd)
    return mod


def test_the_servers_file_is_read_when_we_have_none(tmp_path, monkeypatch) -> None:
    """The handover case: the server took the chore, so our daemon never wrote a file. Before
    janitor#197 this read only our path and went silent — the audit ran and nobody heard it."""
    mod = _stage(tmp_path, monkeypatch, ours=None, theirs=_payload("2026-08-05T12:00:00Z"))
    got = mod._read_findings()
    assert got is not None and got["generated_at"] == "2026-08-05T12:00:00Z"


def test_neither_side_present_returns_none(tmp_path, monkeypatch) -> None:
    """Absence is not a finding."""
    mod = _stage(tmp_path, monkeypatch)
    assert mod._read_findings() is None


def test_a_malformed_file_loses_and_never_suppresses_the_other(tmp_path, monkeypatch) -> None:
    """A corrupt payload must LOSE, not win — otherwise one bad writer silences the fleet audit."""
    mod = _stage(tmp_path, monkeypatch, ours="{ not json",
                 theirs=_payload("2026-08-05T12:00:00Z"))
    got = mod._read_findings()
    assert got is not None and got["generated_at"] == "2026-08-05T12:00:00Z"


def test_the_newer_side_wins_in_BOTH_directions(tmp_path, monkeypatch) -> None:
    """The invariant that keeps handover honest. A server that STOPS running the chore must stop
    winning the moment our daemon's next beat lands — choosing on liveness instead would let a
    live-but-idle server's stale audit mask a fresher local one, the same bug class as gating the
    daemon's exit on server_is_alive() rather than on the chore claim (#134)."""
    mod = _stage(tmp_path, monkeypatch, ours=_payload("2026-08-05T23:00:00Z"),
                 theirs=_payload("2026-08-05T01:00:00Z"))
    assert mod._read_findings()["generated_at"] == "2026-08-05T23:00:00Z", "ours newer -> ours"

    mod2 = _stage(tmp_path / "b", monkeypatch, ours=_payload("2026-08-05T01:00:00Z"),
                  theirs=_payload("2026-08-05T23:00:00Z"))
    assert mod2._read_findings()["generated_at"] == "2026-08-05T23:00:00Z", "theirs newer -> theirs"


def test_a_non_object_payload_is_rejected_not_returned(tmp_path, monkeypatch) -> None:
    """Valid JSON that is not an object (a bare list) must not reach the summarizer."""
    mod = _stage(tmp_path, monkeypatch, ours="[1, 2, 3]")
    assert mod._read_findings() is None

# ── TRDD-6L7OEJ8C: NO_PR_REVIEW is judged against THIS repo's own pull-request rule ──────────


def _prrd(tmp_path: Path, value: str) -> None:
    """Give the tmp project a PRRD stating `require-pull-request: <value>` in its frontmatter."""
    d = tmp_path / "proj" / "design" / "requirements"
    d.mkdir(parents=True, exist_ok=True)
    (d / "PRRD.md").write_text(f"---\nrequire-pull-request: {value}\n---\n\n# PRRD\n", encoding="utf-8")


_NO_PR = {"code": "NO_PR_REVIEW", "detail": "d"}


def test_no_pr_review_is_dropped_when_the_repos_own_prrd_says_false(tmp_path: Path) -> None:
    """Behaviour 1: a newer server audit flags NO_PR_REVIEW on this repo, whose PRRD says false:
    no line and no proposal (the 2026-10-07 false GHCFG-001 ticket)."""
    _with_origin(tmp_path, "o/proj")
    _prrd(tmp_path, "false")
    r = _run(tmp_path, [], age_s=3600, server=[{"slug": "o/proj", **_NO_PR}])
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""
    assert _proposals(tmp_path) == []


def test_no_pr_review_is_still_raised_when_the_repos_own_prrd_says_true(tmp_path: Path) -> None:
    """Behaviour 1, other side: the same finding with the PRRD saying true still surfaces and proposes."""
    _with_origin(tmp_path, "o/proj")
    _prrd(tmp_path, "true")
    r = _run(tmp_path, [], age_s=3600, server=[{"slug": "o/proj", **_NO_PR}])
    assert "NO_PR_REVIEW" in r.stdout or "no required PR review" in r.stdout
    assert "GHCFG-001" in r.stdout
    assert len(_proposals(tmp_path)) == 1


def test_an_undetermined_requirement_keeps_an_advisory_and_never_proposes(tmp_path: Path) -> None:
    """Behaviour 2: this repo's PRRD cannot be read from here (slug does not match the checkout),
    so the finding stays as an advisory marked undetermined, with NO proposal and NO approval or
    fix command."""
    _with_origin(tmp_path, "o/notmine")
    r = _run(tmp_path, [], age_s=3600, server=[{"slug": "o/notmine", **_NO_PR}])
    assert r.returncode == 0, r.stderr
    assert "undetermined" in r.stdout
    assert "GHCFG-001" not in r.stdout
    assert "/janitor-support-open-ticket" not in r.stdout
    assert "janitor-github-config-fix" not in r.stdout
    assert _proposals(tmp_path) == []


def test_other_repos_are_filtered_but_never_printed_and_the_drop_count_goes_to_the_log(tmp_path: Path) -> None:
    """Behaviour 3: the filter runs over every slug; only the CURRENT repo may produce output; the
    number dropped is logged, never printed."""
    _with_origin(tmp_path, "o/proj")
    _prrd(tmp_path, "false")
    r = _run(
        tmp_path, [], age_s=3600,
        server=[{"slug": "o/proj", **_NO_PR}, {"slug": "o/elsewhere", **_NO_PR}],
    )
    assert r.stdout == ""
    assert "elsewhere" not in r.stdout + r.stderr
    log = (tmp_path / "proj" / ".janitor" / "logs" / "fleet-github-config.log").read_text(encoding="utf-8")
    assert "dropped 1 NO_PR_REVIEW" in log
    assert "elsewhere" not in log


def _epoch(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp())


def test_generated_at_is_compared_as_time_not_as_text(tmp_path, monkeypatch) -> None:
    """Behaviour 4: an ISO string and an epoch integer are compared as epochs, and an unparseable
    value loses. A text compare ranks "2026-08..." above any 10-digit epoch and "garbage" above both."""
    iso_old = "2026-08-05T12:00:00+00:00"
    epoch_new = _epoch("2026-10-01T12:00:00+00:00")
    mod = _stage(tmp_path / "a", monkeypatch, ours=_payload(iso_old), theirs={"generated_at": epoch_new, "findings": []})
    assert mod._read_findings()["generated_at"] == epoch_new, "newer epoch must beat an older ISO string"

    mod = _stage(tmp_path / "b", monkeypatch, ours=_payload("garbage"), theirs={"generated_at": epoch_new, "findings": []})
    assert mod._read_findings()["generated_at"] == epoch_new, "an unparseable generated_at loses"

    mod = _stage(tmp_path / "c", monkeypatch, ours=_payload("2026-10-07T12:00:00+00:00"),
                 theirs={"generated_at": _epoch("2026-08-05T12:00:00+00:00"), "findings": []})
    assert mod._read_findings()["generated_at"] == "2026-10-07T12:00:00+00:00", "newer ISO beats an older epoch"
