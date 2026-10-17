"""Tests for the cross-/clear verification harness (scripts/handoff_clear_verify.py).

The pure decision layer (extract_wikilinks / compute_verdicts / render_report) is
tested directly; the two phases are tested via real subprocess runs against an
isolated tmp project, so no real /clear, cron, or memory store is touched.
"""

from __future__ import annotations

import importlib.util as _u
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "handoff_clear_verify.py"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


def _import():
    spec = _u.spec_from_file_location("handoff_clear_verify_under_test", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(args: list[str], *, project: Path) -> subprocess.CompletedProcess:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "CLAUDE_PROJECT_DIR": str(project),
        # Skip the external agentlensPro probe in tests — the transcript fallback (None
        # in a tmp project) is deterministic.
        "CLAUDE_PLUGIN_OPTION_HANDOFF_VERIFY_CONTEXT_COMMAND": "",
    }
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _state_dir(project: Path) -> Path:
    return project / ".janitor" / "state"


# ---------- pure helpers ---------------------------------------------------


def test_extract_wikilinks_targets_dedupe_and_strip() -> None:
    mod = _import()
    text = (
        "see [[oauth-rotator-burn]] and [[oauth-rotator-burn|the rotator]] "
        "and [[continuity-engineering#section]] — but not a stray [[ open bracket\n"
    )
    links = mod.extract_wikilinks(text)
    assert links == ["oauth-rotator-burn", "continuity-engineering"], links


def test_extract_wikilinks_skips_line_range_jev_pointer() -> None:
    """A Jev pointer with a line range is a retrieval handle, not a wikilink (TRDD-AFW0CA65)."""
    mod = _import()
    text = '[[elided id=82c23f01-e48c-4049-9cb9-1816298db6a2:0 lines=150-181 tokens=393 "x"]] and [[real-page]]'
    assert mod.extract_wikilinks(text) == ["real-page"]


def test_extract_wikilinks_skips_pointer_without_range_and_listing_line() -> None:
    """A no-range pointer and the `[[elided: N more items ...]]` listing line yield no links."""
    mod = _import()
    text = (
        '[[elided id=5dda1f01-aaaa-bbbb-cccc-000000000000:0 tokens=781 "Bash(...)"]]\n'
        "[[elided: 545 more items not listed -- list/search]]\n"
    )
    assert mod.extract_wikilinks(text) == []


def test_extract_wikilinks_real_format_pointer_roundtrip() -> None:
    """Outer pointers from the real format_pointer are never extracted.

    A pointer whose summary embeds `[[x]]` is not matched at all (the wikilink regex
    cannot cross the embedded `[`); only "x" is extracted, which is pre-existing
    behaviour and fails safe. The third pointer (summary with `|`, no brackets) is the
    one that proves the _JEV_POINTER_TARGET_RE skip.
    """
    from jevctx.pipeline import format_pointer
    from jevctx.types import Pointer

    mod = _import()
    pointer = Pointer(id="abc123:0", lines=(150, 181), tokens=393, summary='a|b#c "q" back\\slash [[x]] end')
    plain = Pointer(id="abc123:1", lines=None, tokens=7, summary="no specials here")
    text = format_pointer(pointer) + "\n" + format_pointer(plain)
    assert mod.extract_wikilinks(text) == ["x"]
    assert mod.extract_wikilinks(format_pointer(plain)) == []
    # No embedded brackets: the wikilink regex DOES match this outer pointer (target cut at the
    # `|`), so only the _JEV_POINTER_TARGET_RE skip keeps it out.
    piped = Pointer(id="abc123:2", lines=(1, 2), tokens=5, summary='a|b#c "q" back\\slash end')
    assert mod.extract_wikilinks(format_pointer(piped)) == []


def test_extract_wikilinks_alias_and_anchor_still_resolve_to_page() -> None:
    """Guards: `[[page|alias]]` and `[[page#anchor]]` still yield the bare page slug."""
    mod = _import()
    assert mod.extract_wikilinks("[[page|alias]]") == ["page"]
    assert mod.extract_wikilinks("[[page#anchor]]") == ["page"]


def test_pointers_only_handoff_yields_skip_for_links_resolve() -> None:
    """A handoff whose only [[ ]] spans are Jev pointers carries no wikilinks, so the verdict is SKIP."""
    mod = _import()
    handoff = '[[elided id=5dda1f01-aaaa-bbbb-cccc-000000000000:0 tokens=781 "Bash(...)"]]'
    before = {
        "ts": 1000,
        "cron_id": "oldid",
        "context_tokens": 400000,
        "handoff_links": mod.extract_wikilinks(handoff),
        "resume_flag_present": True,
    }
    after = {
        "ts": 1100,
        "cron_id": "newid",
        "context_tokens": 40000,
        "resume_flag_present": False,
        "armed_at_ts": 1050,
        "links_resolved": {},
    }
    v = mod.compute_verdicts(before, after)
    assert v["handoff_links_resolve"]["status"] == "SKIP"
    assert "no [[wikilinks]]" in v["handoff_links_resolve"]["detail"]


def test_compute_verdicts_all_pass() -> None:
    mod = _import()
    before = {
        "ts": 1000,
        "cron_id": "oldid",
        "context_tokens": 400000,
        "handoff_links": ["page-a", "page-b"],
        "resume_flag_present": True,
    }
    after = {
        "ts": 1100,
        "cron_id": "newid",
        "context_tokens": 40000,
        "resume_flag_present": False,
        "armed_at_ts": 1050,
        "links_resolved": {"page-a": True, "page-b": True},
    }
    v = mod.compute_verdicts(before, after)
    assert {k: x["status"] for k, x in v.items()} == {
        "cron_recreated": "PASS",
        "context_collapsed": "PASS",
        "handoff_links_resolve": "PASS",
        "resume_flag_consumed": "PASS",
        "session_restarted": "PASS",
        "handoff_pointers_expand": "SKIP",  # this handoff carries no pointers
    }


def test_compute_verdicts_flags_failures() -> None:
    mod = _import()
    before = {
        "ts": 1000,
        "cron_id": "beforeid",
        "context_tokens": 400000,
        "handoff_links": ["page-a"],
        "resume_flag_present": True,
    }
    after = {
        "ts": 1100,
        "cron_id": "",  # gone after /clear, and no re-arm observed → genuinely broken
        "context_tokens": 390000,  # did not collapse
        "resume_flag_present": True,  # not consumed
        "armed_at_ts": 500,  # predates the snapshot
        "links_resolved": {"page-a": False},  # unresolved
    }
    v = mod.compute_verdicts(before, after)
    assert v["cron_recreated"]["status"] == "FAIL"
    assert v["context_collapsed"]["status"] == "FAIL"
    assert v["handoff_links_resolve"]["status"] == "FAIL"
    assert v["resume_flag_consumed"]["status"] == "FAIL"
    assert v["session_restarted"]["status"] == "FAIL"


def test_compute_verdicts_cron_survived_unchanged_is_healthy_not_a_failure() -> None:
    """#186 regression: /clear does not always destroy the session cron (SessionStart's
    re-arm is CONDITIONAL — "if it is missing" — so a cron that never went missing is
    correctly never re-armed). A prior version of this harness asserted destruction +
    recreation UNCONDITIONALLY and reported FAIL on a real, healthy machine where the
    cron simply survived `/clear` with the SAME id — the false assumption was the
    harness's, not the primitive's. Both the cron check and the dependent re-arm check
    must read this as healthy (PASS / SKIP), never FAIL."""
    mod = _import()
    before = {
        "ts": 1000,
        "cron_id": "4deceffa",
        "context_tokens": 400000,
        "handoff_links": [],
        "resume_flag_present": False,
    }
    after = {
        "ts": 1100,
        "cron_id": "4deceffa",  # UNCHANGED — this build's /clear does not drop the cron
        "context_tokens": 40000,
        "resume_flag_present": False,
        "armed_at_ts": 500,  # predates the snapshot — no fresh re-arm, because none was needed
        "links_resolved": {},
    }
    v = mod.compute_verdicts(before, after)
    assert v["cron_recreated"]["status"] == "PASS", v["cron_recreated"]
    assert v["session_restarted"]["status"] == "SKIP", v["session_restarted"]


def test_compute_verdicts_skips_on_missing_signals() -> None:
    """Missing data → SKIP, never a manufactured FAIL (fail-open diagnostic)."""
    mod = _import()
    before = {"ts": 1000, "cron_id": "", "context_tokens": None, "handoff_links": [], "resume_flag_present": False}
    after = {"ts": 1100, "cron_id": "", "context_tokens": None, "resume_flag_present": False, "armed_at_ts": 0, "links_resolved": {}}
    v = mod.compute_verdicts(before, after)
    assert all(x["status"] == "SKIP" for x in v.values()), v


def test_render_report_has_table_and_snapshots() -> None:
    mod = _import()
    before = {"ts": 1000, "cron_id": "oldid", "context_tokens": 400000, "handoff_links": ["p"], "resume_flag_present": True}
    after = {"ts": 1100, "cron_id": "newid", "context_tokens": 40000, "resume_flag_present": False, "armed_at_ts": 1050, "links_resolved": {"p": True}}
    report = mod.render_report(before, after, mod.compute_verdicts(before, after))
    assert "cross-/clear verification" in report
    assert "| # | assumption | result | detail |" in report
    assert "PASS" in report
    assert "before snapshot" in report and "after snapshot" in report


# ---------- phases via subprocess -----------------------------------------


def test_phase_before_writes_snapshot(tmp_path: Path) -> None:
    """--phase before records the cron id + handoff links into the survive-/clear JSON."""
    p = tmp_path / "proj"
    sd = _state_dir(p)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "heartbeat-cron-id.txt").write_text("cron-abc", encoding="utf-8")
    (sd / "agent-handoff.md").write_text(
        "NEXT: continue TRDD-Z582IKIR\n- [[page-a]] and [[page-b]]\n", encoding="utf-8"
    )
    (sd / "resume-after-clear.flag").write_text("resume me", encoding="utf-8")

    proc = _run(["--phase", "before"], project=p)
    assert proc.returncode == 0, proc.stderr
    assert "VERIFY_BEFORE" in proc.stdout
    saved = json.loads((sd / "handoff-clear-verify.json").read_text(encoding="utf-8"))
    before = saved["before"]
    assert before["cron_id"] == "cron-abc"
    assert before["handoff_links"] == ["page-a", "page-b"]
    assert before["handoff_link_count"] == 2
    assert before["resume_flag_present"] is True


def test_phase_before_surfaces_a_missing_flag_with_BOTH_readings(tmp_path: Path) -> None:
    """--phase before with no resume-after-clear.flag names both readings — expected-on-the-chain AND nothing-will-resume."""
    p = tmp_path / "proj"
    sd = _state_dir(p)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "heartbeat-cron-id.txt").write_text("cron-abc", encoding="utf-8")
    (sd / "agent-handoff.md").write_text("NEXT: something\n", encoding="utf-8")
    # deliberately NO resume-after-clear.flag. This state is AMBIGUOUS by design: on the
    # spawned-chain path the detached child writes the flag after this snapshot (skill step 4),
    # so absence is normal there; run standalone, absence means nothing will resume the clear —
    # the 2026-08-22 staging that left a resumed session idle. The message must not assert the
    # second reading alone, or it cries wolf on every correct orchestrated clear.

    proc = _run(["--phase", "before"], project=p)
    assert proc.returncode == 0, proc.stderr
    assert "VERIFY_BEFORE" in proc.stdout
    assert "VERIFY_BEFORE_NO_RESUME_FLAG" in proc.stderr
    assert "EXPECTED" in proc.stderr, "must name the benign reading (chain wrote it later)"
    # the WHOLE command, not just the flag: a bare `--phase after` substring would also match a
    # message that merely mentions the phase, which is coincidence rather than content
    assert "uv run scripts/handoff_clear_verify.py --phase after" in proc.stderr, (
        "the warning must carry the exact command to paste after clearing"
    )


def test_phase_before_is_quiet_when_the_flag_is_there(tmp_path: Path) -> None:
    """The warning stays silent once the flag has landed — a warning that always fires gets ignored."""
    p = tmp_path / "proj"
    sd = _state_dir(p)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "heartbeat-cron-id.txt").write_text("cron-abc", encoding="utf-8")
    (sd / "agent-handoff.md").write_text("NEXT: something\n", encoding="utf-8")
    (sd / "resume-after-clear.flag").write_text("resume me", encoding="utf-8")

    proc = _run(["--phase", "before"], project=p)
    assert proc.returncode == 0, proc.stderr
    assert "VERIFY_BEFORE_NO_RESUME_FLAG" not in proc.stderr


def test_phase_after_no_before_is_graceful(tmp_path: Path) -> None:
    """--phase after with no before-snapshot → a warning, never a crash."""
    p = tmp_path / "proj"
    (_state_dir(p)).mkdir(parents=True, exist_ok=True)
    proc = _run(["--phase", "after"], project=p)
    assert proc.returncode == 0
    assert "VERIFY_NO_BEFORE" in proc.stderr


def test_phase_after_proves_cron_recreated_and_writes_report(tmp_path: Path) -> None:
    """--phase after: a changed cron id + a fresh re-arm ts → PASS, report emitted."""
    p = tmp_path / "proj"
    sd = _state_dir(p)
    sd.mkdir(parents=True, exist_ok=True)
    # Seed a before-snapshot as if the invoking session recorded it pre-/clear.
    now = int(time.time())
    (sd / "handoff-clear-verify.json").write_text(
        json.dumps({"before": {"ts": now - 60, "cron_id": "old-cron", "context_tokens": 400000, "handoff_links": [], "resume_flag_present": True}}),
        encoding="utf-8",
    )
    # The fresh session's re-arm wrote a NEW cron id + a fresh armed-at stamp.
    (sd / "heartbeat-cron-id.txt").write_text("new-cron", encoding="utf-8")
    (sd / "heartbeat-armed-at.ts").write_text(str(now), encoding="utf-8")
    # The resume flag was consumed by _phase_clear_resume (absent now).

    proc = _run(["--phase", "after"], project=p)
    assert proc.returncode == 0, proc.stderr
    assert "VERIFY_AFTER" in proc.stdout
    assert "[PASS] cron_recreated" in proc.stdout
    assert "[PASS] resume_flag_consumed" in proc.stdout
    # A PASS/FAIL report was written under reports/continuity-build/ of the tmp project.
    reports = list((p / "reports" / "continuity-build").glob("*-handoff-clear-verify.md"))
    assert reports, "a verification report must be written"
    body = reports[0].read_text(encoding="utf-8")
    assert "cross-/clear verification" in body
    # The JSON now carries the verdicts too.
    saved = json.loads((sd / "handoff-clear-verify.json").read_text(encoding="utf-8"))
    assert saved["verdicts"]["cron_recreated"]["status"] == "PASS"


# --- janitor#224: two verdicts that misreported a healthy clear -------------------


def _snap(**over):
    base = {"ts": 1000, "cron_id": "a", "context_tokens": 177_499,
            "resume_flag_present": False, "handoff_links": []}
    return {**base, **over}


def test_consumption_stamp_proves_the_resume_even_when_before_never_saw_the_flag():
    """Defect 2: on the spawned-chain path the flag is written by a detached child AFTER
    the before-snapshot (measured 23:29:10 vs 23:29:12), so `b_flag` is False on exactly
    the runs that worked. The stamp is direct evidence and outranks that inference."""
    v = _import().compute_verdicts(
        _snap(resume_flag_present=False),
        _snap(ts=2000, resume_consumed_at=1500, resume_flag_present=False),
    )
    assert v["resume_flag_consumed"]["status"] == "PASS"


def test_without_a_stamp_the_skip_no_longer_asserts_a_falsehood():
    """The old text said 'no resume-after-clear flag was set before /clear' — stated as
    fact, on runs where one had been set AND consumed. A verdict that cannot observe its
    subject must not narrate it."""
    v = _import().compute_verdicts(_snap(), _snap(ts=2000))
    d = v["resume_flag_consumed"]
    assert d["status"] == "SKIP"
    assert "could not observe" in d["detail"]
    assert "no resume-after-clear flag was set" not in d["detail"]


def test_a_stale_stamp_from_a_previous_clear_does_not_count():
    """A stamp older than the before-snapshot belongs to an earlier event; crediting it
    would let one real resume vouch for every later one."""
    v = _import().compute_verdicts(_snap(ts=5000), _snap(ts=6000, resume_consumed_at=100))
    assert v["resume_flag_consumed"]["status"] == "SKIP"


def test_context_at_the_install_floor_is_a_PASS_not_a_FAIL():
    """Defect 3, the reported numbers: 177499 → 166167 against a ~166k floor. The clear was
    perfect; the ratio was measuring the install."""
    v = _import().compute_verdicts(
        _snap(context_tokens=177_499),
        _snap(ts=2000, context_tokens=166_167, context_floor=166_000),
    )
    assert v["context_collapsed"]["status"] == "PASS", v["context_collapsed"]["detail"]


def test_a_before_too_close_to_the_floor_still_PASSes():
    """180k -> 175k against a 166k floor cannot satisfy a 0.5x ratio — but the session DID
    land at its floor, which is the only thing a clear can achieve. Judged by the ratio this
    was the reported FAIL; judged by the floor it is what success looks like."""
    v = _import().compute_verdicts(
        _snap(context_tokens=180_000),
        _snap(ts=2000, context_tokens=175_000, context_floor=166_000),
    )
    assert v["context_collapsed"]["status"] == "PASS"


def test_a_genuinely_uncollapsed_context_still_FAILs():
    """The floor must not become a blanket excuse: far above it and barely moved is a real
    failure, and this is what stops defect 3's fix from disabling the check."""
    v = _import().compute_verdicts(
        _snap(context_tokens=800_000),
        _snap(ts=2000, context_tokens=790_000, context_floor=166_000),
    )
    assert v["context_collapsed"]["status"] == "FAIL"


def test_an_unknown_floor_falls_back_to_the_ratio():
    """Fail-open: an unmeasured floor degrades to the old behaviour, never to a crash."""
    v = _import().compute_verdicts(
        _snap(context_tokens=400_000), _snap(ts=2000, context_tokens=100_000),
    )
    assert v["context_collapsed"]["status"] == "PASS"




# --- TRDD-I40IKPWU: every elided pointer in the handoff still expands ---------------------
#
# Real files in tmp_path, no mocks: a real transcript under a real (tmp) Claude config dir, and
# handoff text in the exact shape scripts/lib/jev_compaction.py::compose writes.

_SID = "abcdabcd"
_SID_FULL = "abcdabcd-bcde-4cde-8def-abcdefabcdef"
_U1 = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee01"
_U2 = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee02"
_U3 = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee03"


def _pointer(pointer_id: str) -> str:
    return f'[[elided id={pointer_id} tokens=12 "first line of the item"]]'


def _expand_line(transcript: str) -> str:
    return (
        'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" '
        f"expand --transcript {transcript} <id>"
    )


def _handoff(
    *, transcript: str, inline: tuple[str, ...] = (), elided: tuple[str, ...] = (), kept: str = "",
    expand_line: str | None = None,
) -> str:
    """A handoff in the real compose() layout: inline pointer AFTER the message text, a kept
    item, the trailing `## Elided` list, and the `pointers expand with:` line last."""
    lines = ["# Compacted context (Jev compaction)", "", "## Digest", "digest text", "",
             "## Conversation since the last compaction (verbatim, never scored)"]
    for pointer_id in inline:
        lines += [f"-- assistant {pointer_id} --", "truncated message text", "more text", _pointer(pointer_id)]
    lines += ["", "## Kept items", kept, "", "## Elided"]
    lines += [_pointer(pointer_id) for pointer_id in elided]
    lines += ["[[elided: 3 more items not listed -- list/search: replace <id> in the expand command below]]", ""]
    lines.append(expand_line if expand_line is not None else _expand_line(transcript))
    return "\n".join(lines) + "\n"


def _config_with_transcript(tmp_path: Path, monkeypatch) -> Path:
    """A tmp CLAUDE_CONFIG_DIR holding `<sid>.jsonl` with three single-block user entries."""
    project_dir = tmp_path / "cfg" / "projects" / "-some-project"
    project_dir.mkdir(parents=True)
    transcript = project_dir / f"{_SID_FULL}.jsonl"
    transcript.write_text(
        "".join(
            json.dumps({"uuid": u, "type": "user", "message": {"role": "user", "content": f"text of {u}"}}) + "\n"
            for u in (_U1, _U2, _U3)
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    return transcript


def _before_for(mod, text: str, sid8: str | None = _SID) -> dict:
    """The `before` keys gather_before derives from a handoff text, without the state-dir I/O."""
    pointers, transcript = mod.extract_pointers(text)
    return {
        "handoff_pointers": pointers,
        "handoff_pointer_candidates": mod.count_pointer_candidates(text),
        "handoff_transcript": transcript,
        "handoff_sid8": sid8,
    }


def _pointer_verdict(mod, before: dict) -> dict:
    after = mod._check_pointers(before)
    return mod.compute_verdicts({"ts": 1, **before}, {"ts": 2, **after})["handoff_pointers_expand"]


def test_pointers_expand_passes_for_real_format_pointers(tmp_path: Path, monkeypatch) -> None:
    """Inline (after the message text) and `## Elided` pointers that resolve give PASS."""
    mod = _import()
    transcript = _config_with_transcript(tmp_path, monkeypatch)
    text = _handoff(transcript=str(transcript), inline=(f"{_U1}:0",), elided=(f"{_U2}:0", f"{_U3}:0"))
    before = _before_for(mod, text)
    assert before["handoff_pointers"] == [f"{_U1}:0", f"{_U2}:0", f"{_U3}:0"]
    assert before["handoff_transcript"] == str(transcript)
    assert _pointer_verdict(mod, before) == {"status": "PASS", "detail": "all 3 pointer(s) expand"}


def test_pointers_expand_fails_on_unknown_uuid_and_bad_span_naming_both(tmp_path: Path, monkeypatch) -> None:
    """An unknown uuid and an out-of-range span both fail, and the detail names both ids."""
    mod = _import()
    transcript = _config_with_transcript(tmp_path, monkeypatch)
    bad_span = f"{_U1}:0" + "@" + "5-9"  # built at runtime: the privacy scanner reads this as a user-at-host address
    text = _handoff(transcript=str(transcript), elided=(f"{_U2}:0", "ffffffff-dead-4bad-8bad-deadbeefdead:0", bad_span))
    verdict = _pointer_verdict(mod, _before_for(mod, text))
    assert verdict["status"] == "FAIL"
    assert verdict["detail"].startswith("2/3 pointer(s) did not expand: ")
    assert "ffffffff-dead-4bad-8bad-deadbeefdead:0=no transcript entry" in verdict["detail"]
    assert f"{bad_span}=line span 5-9 out of range" in verdict["detail"]


def test_pointers_expand_fails_when_an_inline_pointer_does_not_resolve(tmp_path: Path, monkeypatch) -> None:
    """A 'Newest messages' inline pointer is checked too, not only the `## Elided` list."""
    mod = _import()
    transcript = _config_with_transcript(tmp_path, monkeypatch)
    gone = "ffffffff-dead-4bad-8bad-deadbeefbeef:0"
    verdict = _pointer_verdict(mod, _before_for(mod, _handoff(transcript=str(transcript), inline=(gone,))))
    assert verdict["status"] == "FAIL"
    assert gone in verdict["detail"]


def test_pointers_expand_fails_when_the_transcript_is_gone(tmp_path: Path, monkeypatch) -> None:
    """A well-formed path to a vanished transcript is 'gone' (FAIL), not 'rejected'."""
    mod = _import()
    transcript = _config_with_transcript(tmp_path, monkeypatch)
    text = _handoff(transcript=str(transcript), elided=(f"{_U1}:0", f"{_U2}:0"))
    transcript.unlink()
    assert _pointer_verdict(mod, _before_for(mod, text)) == {
        "status": "FAIL",
        "detail": "transcript of the cleared session is gone: 2 pointer(s) unrecoverable",
    }


def test_pointers_expand_skips_a_handoff_with_no_pointers() -> None:
    """No compacted block (a hand-authored link-only handoff) is a SKIP, not a failure."""
    mod = _import()
    verdict = _pointer_verdict(mod, _before_for(mod, "NEXT: continue\n- [[page-a]]\n"))
    assert verdict == {"status": "SKIP", "detail": "handoff carried no elided pointers"}


def test_pointers_expand_fails_when_the_check_could_not_run() -> None:
    """An `after` snapshot carrying pointers_expanded_error is a FAIL, never a SKIP."""
    mod = _import()
    before = {"handoff_pointers": [f"{_U1}:0"]}
    verdict = mod.compute_verdicts({"ts": 1, **before}, {"ts": 2, "pointers_expanded_error": "ImportError: boom"})[
        "handoff_pointers_expand"
    ]
    assert verdict == {"status": "FAIL", "detail": "pointer check could not run: ImportError: boom"}


def test_pointers_expand_rejects_a_missing_path_outside_the_projects_root(tmp_path: Path, monkeypatch) -> None:
    """A transcript path outside every projects root that does not exist says 'rejected', not 'gone'."""
    mod = _import()
    _config_with_transcript(tmp_path, monkeypatch)
    outside = tmp_path / "elsewhere" / f"{_SID_FULL}.jsonl"
    text = _handoff(transcript=str(outside), elided=(f"{_U1}:0",))
    verdict = _pointer_verdict(mod, _before_for(mod, text))
    assert verdict["status"] == "FAIL"
    assert verdict["detail"] == "transcript path rejected: not directly under a Claude projects root"


def test_pointers_expand_rejects_when_no_session_id_can_be_derived(tmp_path: Path, monkeypatch) -> None:
    """A legacy/unkeyed handoff (sid8 None) cannot vouch for any transcript: FAIL, rejected."""
    mod = _import()
    transcript = _config_with_transcript(tmp_path, monkeypatch)
    text = _handoff(transcript=str(transcript), elided=(f"{_U1}:0",))
    verdict = _pointer_verdict(mod, _before_for(mod, text, sid8=None))
    assert verdict == {"status": "FAIL", "detail": "transcript path rejected: cannot derive session id"}


def test_pointers_expand_rejects_when_the_handoff_names_no_transcript(tmp_path: Path, monkeypatch) -> None:
    """Pointers but no trailing `pointers expand with:` line: FAIL 'handoff names no transcript'."""
    mod = _import()
    _config_with_transcript(tmp_path, monkeypatch)
    text = _handoff(transcript="unused", elided=(f"{_U1}:0",), expand_line="no expand line here")
    verdict = _pointer_verdict(mod, _before_for(mod, text))
    assert verdict == {"status": "FAIL", "detail": "transcript path rejected: handoff names no transcript"}


def test_validate_transcript_path_rejects_a_wrong_name_and_a_wrong_depth(tmp_path: Path) -> None:
    """The file must be `<root>/<project>/<sid8...>.jsonl`: wrong extension, prefix, or depth is refused."""
    mod = _import()
    root = tmp_path / "projects"
    (root / "p").mkdir(parents=True)
    ok = root / "p" / f"{_SID_FULL}.jsonl"
    assert mod.validate_transcript_path(str(ok), (root,), _SID) is None
    assert mod.validate_transcript_path(str(root / "p" / f"{_SID_FULL}.txt"), (root,), _SID) is not None
    assert mod.validate_transcript_path(str(root / "p" / "99999999-x.jsonl"), (root,), _SID) is not None
    assert mod.validate_transcript_path(str(root / f"{_SID_FULL}.jsonl"), (root,), _SID) is not None
    assert mod.validate_transcript_path(str(root / "p" / ".." / ".." / "x" / f"{_SID_FULL}.jsonl"), (root,), _SID) is not None
    assert mod.validate_transcript_path(None, (root,), _SID) == "handoff names no transcript"


def test_validate_transcript_path_accepts_any_of_several_roots(tmp_path: Path) -> None:
    """A path under the second of two roots is accepted (CLAUDE_CONFIG_DIR root + the home root)."""
    mod = _import()
    first, second = tmp_path / "a" / "projects", tmp_path / "b" / "projects"
    (second / "p").mkdir(parents=True)
    path = second / "p" / f"{_SID_FULL}.jsonl"
    assert mod.validate_transcript_path(str(path), (first, second), _SID) is None
    assert mod.validate_transcript_path(str(path), (first,), _SID) is not None


def test_extract_pointers_ignores_foreign_pointers_quoted_in_a_kept_item(tmp_path: Path) -> None:
    """Quoted pointers are foreign: line-number-prefixed, raw, a raw `## Elided` list above the
    real one, and an inline pointer whose uuid differs from its section header."""
    mod = _import()
    kept = "\n".join([
        f"256\t{_pointer('foreign-1:0')}",                      # line-number-prefixed quote
        _pointer("foreign-2:0"),                               # raw quote with no header
        "## Elided",                                           # a raw foreign list ABOVE the real one
        _pointer("foreign-3:0"),
        f"-- assistant {_U1}:0 --",
        _pointer("foreign-4:0"),                               # header uuid differs from the pointer's
    ])
    text = _handoff(transcript="/x/y.jsonl", inline=(f"{_U2}:0",), elided=(f"{_U3}:0",), kept=kept)
    pointers, _ = mod.extract_pointers(text)
    assert pointers == [f"{_U2}:0", f"{_U3}:0"]


def test_extract_pointers_inline_pointer_follows_the_message_text() -> None:
    """Layout: header, several text lines, then the pointer; an id with a span is not inline-real."""
    mod = _import()
    span_id = f"{_U1}:0" + "@" + "1-2"
    text = "\n".join([
        "# Compacted context (Jev compaction)", "## Conversation since the last compaction",
        f"-- assistant {_U1}:0 --", "a", "b", "c", _pointer(f"{_U1}:0"),
        _pointer(span_id),
        "", _expand_line("/x/y.jsonl"), "",
    ])
    assert mod.extract_pointers(text) == ([f"{_U1}:0"], "/x/y.jsonl")


def test_pointer_format_drift_fails_instead_of_skipping() -> None:
    """Defanged pointers (bracket form changed) parse to 0 but still count as candidates: FAIL."""
    mod = _import()
    text = _handoff(transcript="/x/y.jsonl", elided=(f"{_U1}:0", f"{_U2}:0")).replace("[[elided id=", "⟦⟦elided id=")
    before = _before_for(mod, text)
    assert before["handoff_pointers"] == []
    verdict = _pointer_verdict(mod, before)
    assert verdict == {"status": "FAIL", "detail": "pointer format not recognised: 2 candidate(s), 0 parsed"}


def test_pointers_expand_ignores_an_unprefixed_header_and_pointer_quoted_in_a_kept_item(tmp_path: Path, monkeypatch) -> None:
    """A kept item quoting a `-- role id --` header + its matching pointer is foreign: PASS, not FAIL."""
    mod = _import()
    transcript = _config_with_transcript(tmp_path, monkeypatch)
    kept = "\n".join([f"-- assistant {_SID_FULL}:0 --", "old quoted text", _pointer(f"{_SID_FULL}:0")])
    text = _handoff(transcript=str(transcript), inline=(f"{_U1}:0",), elided=(f"{_U2}:0",), kept=kept)
    assert mod.extract_pointers(text)[0] == [f"{_U1}:0", f"{_U2}:0"]
    assert _pointer_verdict(mod, _before_for(mod, text))["status"] == "PASS"


def test_extract_pointers_a_markdown_heading_in_a_message_body_keeps_the_header() -> None:
    """A `## ` line inside a message body must not reset the header, or its pointer is missed."""
    mod = _import()
    text = "\n".join([
        "# Compacted context (Jev compaction)", "## Newest messages since the last compaction",
        f"-- assistant {_U1}:0 --", "## a heading inside the body", "text", _pointer(f"{_U1}:0"),
        "## Kept items", "", _expand_line("/x/y.jsonl"), "",
    ])
    assert mod.extract_pointers(text) == ([f"{_U1}:0"], "/x/y.jsonl")


def test_pointers_expand_skips_when_only_a_kept_item_quotes_old_pointers() -> None:
    """No inline pointers and an empty Elided list: quoted pointers are not candidates, so SKIP."""
    mod = _import()
    kept = "\n".join([_pointer("old-1:0"), f"-- assistant {_U1}:0 --", _pointer(f"{_U1}:0")])
    text = _handoff(transcript="/x/y.jsonl", kept=kept)
    verdict = _pointer_verdict(mod, _before_for(mod, text))
    assert verdict["status"] == "SKIP"


def test_phase_before_records_the_pointers_transcript_and_session_id(tmp_path: Path) -> None:
    """--phase before stores the handoff's pointers, transcript path and sid8 for the after phase."""
    p = tmp_path / "proj"
    sd = _state_dir(p)
    sd.mkdir(parents=True, exist_ok=True)
    transcript = f"/cfg/projects/-p/{_SID_FULL}.jsonl"
    (sd / f"agent-handoff-{_SID}-20261010_144714+0200-61150.md").write_text(
        _handoff(transcript=transcript, elided=(f"{_U1}:0",)), encoding="utf-8"
    )
    proc = _run(["--phase", "before"], project=p)
    assert proc.returncode == 0, proc.stderr
    before = json.loads((sd / "handoff-clear-verify.json").read_text(encoding="utf-8"))["before"]
    assert before["handoff_pointers"] == [f"{_U1}:0"]
    assert before["handoff_transcript"] == transcript
    assert before["handoff_sid8"] == _SID



# --- TRDD-JK2MLS8Z: the after-figure is the FIRST assistant record of the new session ---------

_CLEAR_TS = 1_800_000_000  # the before-phase `ts`: 2027-01-15T08:00:00Z


def _iso(offset_s: int, tz_hours: int = 0) -> str:
    """ISO timestamp `offset_s` seconds after the clear, written with a `tz_hours` UTC offset."""
    from datetime import datetime, timedelta, timezone

    tz = timezone(timedelta(hours=tz_hours))
    stamp = datetime.fromtimestamp(_CLEAR_TS + offset_s, tz=timezone.utc).astimezone(tz)
    return stamp.isoformat().replace("+00:00", "Z") if tz_hours == 0 else stamp.isoformat()


def _assistant(ts: str, total: int) -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {"usage": {"input_tokens": 2, "cache_read_input_tokens": total - 2, "cache_creation_input_tokens": 0}},
    }


def _write_transcript(path: Path, records: list[dict], mtime: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _clear_env(tmp_path: Path, monkeypatch) -> Path:
    """A tmp project + tmp HOME; returns the project's transcript dir (real files, no mocks)."""
    from memory_scopes import project_slug

    project = tmp_path / "proj"
    (project / ".janitor" / "state").mkdir(parents=True)
    home = tmp_path / "home"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HANDOFF_VERIFY_CONTEXT_COMMAND", "")
    return home / ".claude" / "projects" / project_slug(str(project))


_BEFORE = {"ts": _CLEAR_TS, "handoff_sid8": "6feb5bae", "handoff_links": []}


def test_first_context_entry_picks_the_first_record_when_later_ones_are_bigger(tmp_path: Path) -> None:
    import token_meter

    t = _write_transcript(
        tmp_path / "s.jsonl",
        [{"type": "user"}, _assistant(_iso(1), 170_000), _assistant(_iso(2), 230_000), _assistant(_iso(3), 300_000)],
    )
    assert token_meter.first_context_entry(t) == 170_000
    assert token_meter.latest_context_size(t) == 300_000


def test_first_context_entry_is_none_without_assistant_usage(tmp_path: Path) -> None:
    import token_meter

    t = _write_transcript(tmp_path / "s.jsonl", [{"type": "user"}, {"type": "assistant", "message": {"content": "no usage"}}])
    assert token_meter.first_context_entry(t) is None
    assert token_meter.first_context_entry(tmp_path / "missing.jsonl") is None


def test_gather_after_picks_the_transcript_that_started_after_the_clear(tmp_path: Path, monkeypatch) -> None:
    """The cleared session (sid8) and a live OTHER session with a fresher mtime are both ignored."""
    tdir = _clear_env(tmp_path, monkeypatch)
    _write_transcript(tdir / "6feb5bae-aaaa.jsonl", [_assistant(_iso(-3600), 500_000)], _CLEAR_TS - 100)
    # The peer started BEFORE the clear and has the freshest mtime: mtime must never select it.
    _write_transcript(tdir / "99999999-other.jsonl", [_assistant(_iso(-600), 400_000), _assistant(_iso(10), 410_000)], _CLEAR_TS + 100)
    _write_transcript(
        tdir / "2bef3bfd-new.jsonl",
        [
            {"type": "attachment", "timestamp": _iso(5), "attachment": {"type": "hook_success", "hookEvent": "SessionStart", "content": "x" * 3500}},
            {"type": "attachment", "timestamp": _iso(5), "attachment": {"type": "hook_success", "hookEvent": "PreToolUse", "content": "y" * 3500}},
            _assistant(_iso(20), 172_635),
            _assistant(_iso(90), 260_000),
            {"type": "attachment", "timestamp": _iso(95), "attachment": {"type": "hook_success", "hookEvent": "SessionStart", "content": "z" * 3500}},
        ],
        _CLEAR_TS + 50,
    )
    after = _import().gather_after(dict(_BEFORE), int(time.time()))
    assert after["context_tokens"] == 172_635
    assert after["context_source"] == "transcript:first-assistant"
    # Only the SessionStart output before the first assistant record counts (3500 chars / 4).
    assert after["injected_tokens"] == 875


def test_gather_after_skips_when_two_transcripts_started_after_the_clear(tmp_path: Path, monkeypatch) -> None:
    tdir = _clear_env(tmp_path, monkeypatch)
    _write_transcript(tdir / "aaaaaaaa-one.jsonl", [_assistant(_iso(10), 170_000)])
    _write_transcript(tdir / "bbbbbbbb-two.jsonl", [_assistant(_iso(20), 180_000)])
    after = _import().gather_after(dict(_BEFORE), int(time.time()))
    assert after["context_tokens"] is None
    assert after["context_source"].startswith("skipped:") and "2 transcripts" in after["context_source"]


def test_gather_after_compares_instants_across_different_utc_offsets(tmp_path: Path, monkeypatch) -> None:
    """A stamp written at -08:00 that is 1 min BEFORE the clear must not beat wall-clock order."""
    tdir = _clear_env(tmp_path, monkeypatch)
    _write_transcript(tdir / "aaaaaaaa-before.jsonl", [_assistant(_iso(-60, -8), 400_000)])
    _write_transcript(tdir / "bbbbbbbb-after.jsonl", [_assistant(_iso(60, 5), 171_000)])
    after = _import().gather_after(dict(_BEFORE), int(time.time()))
    assert after["context_tokens"] == 171_000


def test_gather_after_ignores_a_stampless_candidate_last_modified_before_the_clear(tmp_path: Path, monkeypatch) -> None:
    tdir = _clear_env(tmp_path, monkeypatch)
    _write_transcript(
        tdir / "aaaaaaaa-notime.jsonl", [{"type": "assistant", "message": {"usage": {"input_tokens": 9}}}], _CLEAR_TS - 5
    )
    after = _import().gather_after(dict(_BEFORE), int(time.time()))
    assert after["context_tokens"] is None
    assert "0 transcripts" in after["context_source"]


def test_the_agentlenspro_live_reading_does_not_override_the_first_record(tmp_path: Path, monkeypatch) -> None:
    tdir = _clear_env(tmp_path, monkeypatch)
    _write_transcript(tdir / "bbbbbbbb-new.jsonl", [_assistant(_iso(20), 172_635), _assistant(_iso(90), 300_000)])
    probe = tmp_path / "probe.sh"
    probe.write_text('#!/bin/sh\necho \'{"context_tokens": 999999}\'\n', encoding="utf-8")
    probe.chmod(0o755)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HANDOFF_VERIFY_CONTEXT_COMMAND", str(probe))
    mod = _import()
    assert mod._context_tokens() == (999_999, "agentlenspro:context_tokens")  # the probe really answers
    after = mod.gather_after(dict(_BEFORE), int(time.time()))
    assert after["context_tokens"] == 172_635
    assert after["context_source"] == "transcript:first-assistant"


def test_a_first_record_above_the_threshold_FAILs_and_the_injection_is_only_reported():
    """Floor 10000 -> threshold 11000. 11400 is above it, and a reported 1500-token injection
    must NOT be added to the threshold (the 10% margin already covers it)."""
    v = _import().compute_verdicts(
        _snap(context_tokens=400_000),
        _snap(ts=2000, context_tokens=11_400, context_floor=10_000, injected_tokens=1500,
              context_source="transcript:first-assistant"),
    )["context_collapsed"]
    assert v["status"] == "FAIL"
    assert "threshold 11000" in v["detail"] and "injection ~1500 tokens" in v["detail"]


def test_a_first_record_within_the_threshold_PASSes_with_the_injection_reported():
    v = _import().compute_verdicts(
        _snap(context_tokens=400_000),
        _snap(ts=2000, context_tokens=10_900, context_floor=10_000, injected_tokens=1500,
              context_source="transcript:first-assistant"),
    )["context_collapsed"]
    assert v["status"] == "PASS"
    assert "transcript:first-assistant" in v["detail"] and "injection ~1500 tokens" in v["detail"]


def test_cron_id_change_detail_makes_no_claim_about_the_cause():
    v = _import().compute_verdicts(_snap(cron_id="old"), _snap(ts=2000, cron_id="new"))
    detail = v["cron_recreated"]["detail"]
    assert "destroyed" not in detail and detail == "cron id changed old → new"


def test_an_unplaceable_candidate_modified_after_the_clear_makes_the_check_SKIP(tmp_path: Path, monkeypatch) -> None:
    """A real successor without any timestamp (mtime after the clear) beside one stamped peer:
    accepting the peer would measure the wrong session and could PASS falsely."""
    tdir = _clear_env(tmp_path, monkeypatch)
    _write_transcript(
        tdir / "aaaaaaaa-successor.jsonl", [{"type": "assistant", "message": {"usage": {"input_tokens": 9}}}], _CLEAR_TS + 30
    )
    _write_transcript(tdir / "bbbbbbbb-peer.jsonl", [_assistant(_iso(60), 150_000)], _CLEAR_TS + 40)
    after = _import().gather_after(dict(_BEFORE), int(time.time()))
    assert after["context_tokens"] is None
    assert "ambiguous" in after["context_source"] and "1 started within the 15-minute window" in after["context_source"]


def test_a_candidate_starting_outside_the_15_minute_window_is_not_accepted(tmp_path: Path, monkeypatch) -> None:
    tdir = _clear_env(tmp_path, monkeypatch)
    _write_transcript(tdir / "aaaaaaaa-late.jsonl", [_assistant(_iso(20 * 60), 170_000)])
    after = _import().gather_after(dict(_BEFORE), int(time.time()))
    assert after["context_tokens"] is None
    assert "ambiguous" in after["context_source"] and "1 started after the 15-minute window" in after["context_source"]


def test_a_late_successor_beside_an_in_window_peer_makes_the_check_SKIP(tmp_path: Path, monkeypatch) -> None:
    """The real successor started 20 min after the clear; the lone in-window peer must not be accepted."""
    tdir = _clear_env(tmp_path, monkeypatch)
    _write_transcript(tdir / "aaaaaaaa-successor.jsonl", [_assistant(_iso(20 * 60), 170_000)])
    _write_transcript(tdir / "bbbbbbbb-peer.jsonl", [_assistant(_iso(2 * 60), 150_000)])
    after = _import().gather_after(dict(_BEFORE), int(time.time()))
    assert after["context_tokens"] is None
    assert "1 started after the 15-minute window" in after["context_source"]
    assert "1 started within the 15-minute window" in after["context_source"]


def test_a_candidate_starting_before_the_clear_beside_an_in_window_one_is_ignored(tmp_path: Path, monkeypatch) -> None:
    """A transcript that started before the clear is ignored, so the lone in-window one is accepted."""
    tdir = _clear_env(tmp_path, monkeypatch)
    _write_transcript(tdir / "aaaaaaaa-older.jsonl", [_assistant(_iso(-600), 400_000)])
    _write_transcript(tdir / "bbbbbbbb-new.jsonl", [_assistant(_iso(14 * 60), 171_000)])
    assert _import().gather_after(dict(_BEFORE), int(time.time()))["context_tokens"] == 171_000
