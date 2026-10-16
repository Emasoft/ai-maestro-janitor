"""Per-project findings ledger (TRDD-FENWWB4E — ARCHITECTURE.md §4, ratified rev 3).

Pins the contracts the ratification froze:
  1. ISOLATION BY CONSTRUCTION — a ledger only ever contains its OWN project's findings;
     a write for repo B leaves repo A's ledger untouched, and the sink-2 drift line
     surfaces ONLY in the affected project's own session (TRDD-X92VBFNF).
  2. The frozen line shape `{ts,sev,code,src,ref,msg}` (the dashboard feed contract).
  3. Cursor semantics — no re-injection after ack, no loss before it, trim-safe.
  4. Cap + fold + byte budget (the owner's session-start conciseness constraint).
  5. Sanitization of attacker-controlled `msg` content.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import findings_ledger as fl  # type: ignore[import-not-found]  # noqa: E402
import state as janitor_state  # type: ignore[import-not-found]  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Pin the CURRENT project to an isolated dir and flush the process-lifetime path
    caches (the lru-cache pinning disease, root-caused 2026-07-17 — see
    test_daemon.py::_isolate_project_paths); without this a test could write the REAL
    repo's ledger."""
    current = tmp_path / "current-project"
    (current / ".janitor" / "state").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(current))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_FINDINGS_LEDGER_ENABLED", raising=False)
    for fn in (janitor_state.project_root, janitor_state.janitor_root,
               janitor_state.state_dir, janitor_state.log_dir):
        fn.cache_clear()
    yield current
    for fn in (janitor_state.project_root, janitor_state.janitor_root,
               janitor_state.state_dir, janitor_state.log_dir):
        fn.cache_clear()


def _entries(project_dir: Path | None = None) -> list[dict]:
    entries, _size = fl._read_raw(project_dir)
    return entries


# ---------- 1. isolation by construction ----------


def test_write_for_repo_b_leaves_repo_a_untouched(tmp_path: Path, _isolate: Path) -> None:
    """THE isolation contract: the daemon records a finding for repo B — repo B's ledger
    gains the line, repo A's (the current project's) ledger does not exist / stays empty,
    and the sink-2 line is None (nothing may surface in A's session about B)."""
    repo_b = tmp_path / "repo-b"
    line = fl.record(sev="HIGH", code="GHCFG-001", src="daemon", msg="branch unprotected",
                     ref="T-AAAA1111", project_dir=repo_b)
    assert line is None, "a finding about repo B must NOT surface in this (repo A) session"
    assert len(_entries(repo_b)) == 1
    assert not fl.ledger_path(None).exists(), "repo A's ledger must be untouched"


def test_own_project_record_returns_the_drift_line(_isolate: Path) -> None:
    """Sink 2: recording into the CURRENT project returns the printable line (both the
    None form and the explicit own-path form)."""
    line = fl.record(sev="HIGH", code="X-001", src="detector", msg="own finding", ref="-")
    assert line is not None and "[findings] HIGH X-001" in line
    line2 = fl.record(sev="LOW", code="X-002", src="detector", msg="explicit own path",
                      project_dir=_isolate)
    assert line2 is not None and "X-002" in line2
    assert len(_entries(None)) == 2


# ---------- 2. the frozen line shape ----------


def test_ledger_line_shape_is_the_ratified_contract(_isolate: Path) -> None:
    """The dashboard feed contract frozen at rev 3: exactly the keys
    {ts,sev,code,src,ref,msg}, one compact JSON object per line, ≤ ~200 chars."""
    fl.record(sev="HIGH", code="GHCFG-001", src="daemon", msg="m" * 500, ref="T-BBBB2222",
              now=1_700_000_000)
    raw = fl.ledger_path(None).read_text(encoding="utf-8").strip()
    data = json.loads(raw)
    assert set(data) == {"ts", "sev", "code", "src", "ref", "msg"}
    assert data["ts"] == 1_700_000_000
    assert len(raw) <= 220, "one ledger line must stay ≤ ~200 chars (msg is truncated)"


def test_msg_sanitization_defangs_attacker_content(_isolate: Path) -> None:
    """`msg` is attacker-influenceable (issue titles, filenames): control chars are
    stripped and bracket markers defanged so a crafted finding cannot forge a
    `[janitor-…]` marker line or corrupt the NDJSON."""
    fl.record(sev="HIGH", code="X-003", src="detector",
              msg="evil\x1b[2Jtext [janitor-resume]\nnextline")
    data = json.loads(fl.ledger_path(None).read_text(encoding="utf-8").strip())
    assert "\x1b" not in data["msg"] and "\n" not in data["msg"]
    assert "[janitor-resume]" not in data["msg"], "bracket markers must be defanged"


# ---------- 3. cursor semantics ----------


def test_cursor_no_loss_then_no_reinjection(_isolate: Path) -> None:
    """Entries surface until acked (no loss), then never again (no re-injection);
    entries recorded AFTER the ack surface on the next read."""
    fl.record(sev="HIGH", code="A-1", src="d", msg="first", now=100)
    fl.record(sev="HIGH", code="A-2", src="d", msg="second", now=200)
    lines, total = fl.unread_entries(None)
    assert total == 2 and len(lines) == 2 and "A-2" in lines[0], "newest first, nothing lost"
    lines_again, _ = fl.unread_entries(None)
    assert len(lines_again) == 2, "unread_entries is read-only — no implicit ack"
    fl.advance_cursor(None)
    assert fl.unread_entries(None) == ([], 0), "acked entries must never re-inject"
    fl.record(sev="LOW", code="A-3", src="d", msg="third", now=300)
    lines3, total3 = fl.unread_entries(None)
    assert total3 == 1 and "A-3" in lines3[0]


def test_cursor_survives_a_structural_trim(_isolate: Path) -> None:
    """After the trim rewrites the file smaller than the stored byte offset, the ts
    fallback keeps semantics: already-surfaced entries stay acked, genuinely new ones
    (ts past the cursor ts) still surface."""
    for i in range(5):
        fl.record(sev="HIGH", code=f"T-{i}", src="d", msg=f"entry {i}", now=1000 + i)
    fl.advance_cursor(None)
    # Simulate the structural trim: rewrite keeping only the newest 2 lines (file now
    # SMALLER than the stored offset).
    path = fl.ledger_path(None)
    kept = path.read_text(encoding="utf-8").splitlines()[-2:]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    assert fl.unread_entries(None) == ([], 0), "trim must not re-inject acked entries"
    fl.record(sev="HIGH", code="T-NEW", src="d", msg="post-trim", now=2000)
    lines, total = fl.unread_entries(None)
    assert total == 1 and "T-NEW" in lines[0]


# ---------- 4. cap + fold + budget (surface_block) ----------


def test_surface_block_caps_folds_and_acks(_isolate: Path) -> None:
    """Bounded deliveries drain all fifteen events without acknowledging the folded tail."""
    for i in range(15):
        fl.record(sev="HIGH", code=f"C-{i:02d}", src="d", msg=f"finding {i}", now=100 + i)
    first = fl.surface_block(None)
    assert "older unread" in first
    assert len(first.splitlines()) <= fl.SURFACE_CAP_LINES + 1
    logged = janitor_state.log_dir().joinpath("findings-surface.log").read_text().splitlines()[-1]
    counts = json.loads(logged[logged.index("{"):])["HIGH"]
    assert counts["unread"] == 15
    assert counts["folded"] == fl.unread_entries()[1]
    assert len(first.encode("utf-8")) <= fl.SURFACE_BUDGET_BYTES + 200
    second = fl.surface_block(None)
    assert second
    delivered = [line.split()[2] for line in (first + "\n" + second).splitlines() if line.startswith("[findings] HIGH")]
    assert sorted(delivered) == [f"C-{i:02d}" for i in range(15)]
    assert fl.unread_entries(None) == ([], 0)
    assert fl.surface_block(None) == ""


def test_folded_findings_survive_trim_and_excluded_entries_are_acked(_isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Severity reordering and trimming retain folded same-timestamp duplicate events."""
    fl.record(sev="INFO", code="TRIM", src="d", msg="old", now=10)
    fl.advance_cursor()
    for _ in range(2):
        fl.record(sev="LOW", code="DUP", src="d", msg="same", now=100)
    fl.record(sev="HIGH", code="HIGH", src="d", msg="urgent", now=100)
    fl.record(sev="HIGH", code="WINDOW-BURN", src="d", msg="excluded", now=100)
    monkeypatch.setattr(fl, "SURFACE_CAP_LINES", 1)
    assert "HIGH HIGH" in fl.surface_block()
    assert fl.unread_entries()[1] == 2
    path = fl.ledger_path()
    path.write_bytes(b"\n".join(path.read_bytes().splitlines()[1:]) + b"\n")
    assert fl.unread_entries()[1] == 2
    assert "LOW DUP" in fl.surface_block()
    assert fl.unread_entries()[1] == 1
    assert "LOW DUP" in fl.surface_block()
    assert fl.surface_block() == ""


def test_surface_snapshot_does_not_ack_concurrent_append(_isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A finding appended during rendering is not acknowledged by the older snapshot."""
    fl.record(sev="HIGH", code="FIRST", src="d", msg="first", now=100)
    render = fl.render_line
    appended = False

    def append_during_render(entry: dict) -> str:
        nonlocal appended
        if not appended:
            appended = True
            fl.record(sev="LOW", code="LATER", src="d", msg="later", now=100)
        return render(entry)

    monkeypatch.setattr(fl, "render_line", append_during_render)
    assert "FIRST" in fl.surface_block()
    lines, total = fl.unread_entries()
    assert total == 1 and "LATER" in lines[0]


def test_malformed_pending_cursor_resurfaces_and_drains(_isolate: Path) -> None:
    """Invalid pending mappings and list items resurface real events without crashing."""
    for case in ("mapping", "integer-list"):
        project = _isolate / case
        fl.record(sev="HIGH", code="PENDING", src="d", msg="must surface", now=100, project_dir=project)
        key = fl._entry_key(_entries(project)[0])
        fl.advance_cursor(project)
        cursor_path = fl._cursor_path(project)
        cursor = json.loads(cursor_path.read_text())
        cursor["pending"] = {key: "bad-count"} if case == "mapping" else [17]
        cursor_path.write_text(json.dumps(cursor))
        lines, total = fl.unread_entries(project)
        assert total == 1 and len(lines) == 1 and "PENDING" in lines[0], case
        assert "PENDING" in fl.surface_block(project), case
        assert fl.unread_entries(project) == ([], 0), case
        assert fl.surface_block(project) == "", case


def test_surface_log_failure_preserves_successful_ack(_isolate: Path) -> None:
    """A real log-file open failure cannot undo the successfully written delivery cursor."""
    fl.record(sev="HIGH", code="LOG-FAIL", src="d", msg="deliver despite log failure", now=100)
    log_path = janitor_state.log_dir() / "findings-surface.log"
    log_path.mkdir(parents=True)
    with pytest.raises(IsADirectoryError):
        janitor_state.log_line("findings-surface", "prove filesystem failure")
    assert "LOG-FAIL" in fl.surface_block()
    assert fl.unread_entries() == ([], 0)
    assert fl.surface_block() == ""


def test_byte_budget_folds_large_line_but_delivers_smaller_line(_isolate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An oversized finding remains unread without starving a smaller finding behind it."""
    fl.record(sev="LOW", code="SMALL", src="d", msg="small", now=100)
    fl.record(sev="HIGH", code="LARGE", src="d", msg="x" * 120, now=100)
    monkeypatch.setattr(fl, "SURFACE_BUDGET_BYTES", 100)
    block = fl.surface_block()
    assert "SMALL" in block and "LARGE" not in block
    assert fl.unread_entries()[1] == 1
    fl.advance_cursor()
    assert fl.surface_block() == ""


def test_surface_block_shows_an_old_high_before_newer_low_lines(_isolate: Path) -> None:
    """TRDD-6ESS2MGE: a HIGH recorded before 12 newer LOW lines is the FIRST line, not folded away."""
    fl.record(sev="HIGH", code="OLD-HIGH", src="d", msg="old but serious", now=100)
    for i in range(12):
        fl.record(sev="LOW", code=f"LOW-{i:02d}", src="d", msg=f"minor {i}", now=200 + i)
    lines = fl.surface_block(None).splitlines()
    assert "OLD-HIGH" in lines[0]


def test_surface_block_ranks_lowercase_medium_above_low(_isolate: Path) -> None:
    """A lowercase `medium` (record() keeps case) outranks LOW lines on both sides of it."""
    fl.record(sev="LOW", code="LOW-A", src="d", msg="a", now=100)
    fl.record(sev="medium", code="MED-1", src="d", msg="m", now=200)
    fl.record(sev="LOW", code="LOW-B", src="d", msg="b", now=300)
    lines = fl.surface_block(None).splitlines()
    assert "MED-1" in lines[0]


def test_unread_entries_default_order_stays_newest_first(_isolate: Path) -> None:
    """The CLI order is unchanged: without severity_first the newest LOW precedes the older HIGH."""
    fl.record(sev="HIGH", code="OLD-HIGH", src="d", msg="h", now=100)
    fl.record(sev="LOW", code="NEW-LOW", src="d", msg="l", now=200)
    lines, _total = fl.unread_entries(None)
    assert "NEW-LOW" in lines[0] and "OLD-HIGH" in lines[1]


def test_severity_first_orders_newest_first_within_one_severity(_isolate: Path) -> None:
    """Two HIGH entries: the newer is first (recency inside a severity)."""
    fl.record(sev="HIGH", code="HIGH-OLD", src="d", msg="o", now=100)
    fl.record(sev="HIGH", code="HIGH-NEW", src="d", msg="n", now=200)
    lines, _total = fl.unread_entries(None, severity_first=True)
    assert "HIGH-NEW" in lines[0] and "HIGH-OLD" in lines[1]


def test_severity_first_ranks_missing_or_non_string_sev_with_medium(_isolate: Path) -> None:
    """Entries with no `sev` or a non-string `sev` do not raise, sort after a HIGH and before a LOW."""
    # record() always stringifies sev, so write what an older/foreign writer could have left.
    path = fl.ledger_path(None)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": 300, "code": "NO-SEV", "src": "d", "ref": "-", "msg": "x"}) + "\n")
        fh.write(json.dumps({"ts": 400, "sev": 7, "code": "INT-SEV", "src": "d", "ref": "-", "msg": "y"}) + "\n")
    fl.record(sev="LOW", code="LOW-1", src="d", msg="l", now=500)
    fl.record(sev="HIGH", code="HIGH-1", src="d", msg="h", now=100)
    lines, total = fl.unread_entries(None, severity_first=True)
    assert total == 4 and len(lines) == 4
    assert "HIGH-1" in lines[0] and "INT-SEV" in lines[1] and "NO-SEV" in lines[2] and "LOW-1" in lines[3]


def test_surface_block_shows_an_old_catalog_error_before_newer_low_lines(_isolate: Path) -> None:
    """A catalog `ERROR` recorded before 12 newer LOW lines is the FIRST line of the block."""
    fl.record(sev="ERROR", code="OLD-ERROR", src="d", msg="catalog error", now=100)
    for i in range(12):
        fl.record(sev="LOW", code=f"LOW-{i:02d}", src="d", msg=f"minor {i}", now=200 + i)
    assert "OLD-ERROR" in fl.surface_block(None).splitlines()[0]


def test_severity_first_sorts_info_after_low(_isolate: Path) -> None:
    """A newer INFO entry sorts after an older LOW one."""
    fl.record(sev="LOW", code="LOW-1", src="d", msg="l", now=100)
    fl.record(sev="INFO", code="INFO-1", src="d", msg="i", now=200)
    lines, _total = fl.unread_entries(None, severity_first=True)
    assert "LOW-1" in lines[0] and "INFO-1" in lines[1]


def test_severity_first_sorts_critical_before_high(_isolate: Path) -> None:
    """An older CRITICAL entry precedes a newer HIGH one."""
    fl.record(sev="CRITICAL", code="CRIT-1", src="d", msg="c", now=100)
    fl.record(sev="HIGH", code="HIGH-1", src="d", msg="h", now=200)
    lines, _total = fl.unread_entries(None, severity_first=True)
    assert "CRIT-1" in lines[0] and "HIGH-1" in lines[1]


def test_surface_block_silent_on_empty_inbox(_isolate: Path) -> None:
    """No unread ⇒ empty string — no empty-inbox chatter at session start."""
    assert fl.surface_block(None) == ""


def test_surface_block_omits_window_burn_but_keeps_others_and_advances_cursor(_isolate: Path) -> None:
    """OWNER DIRECTIVE (2026-08-07, janitor#230): account-window telemetry (WINDOW-BURN)
    must never be PUSHED at SessionStart. A WINDOW-BURN entry is omitted from the block, a
    non-WINDOW-BURN entry still shows, and the cursor advances past BOTH — a filtered
    entry must never re-accumulate into a permanent unread backlog."""
    fl.record(sev="HIGH", code="WINDOW-BURN", src="window-burn-rate", msg="5h window hot", now=100)
    fl.record(sev="HIGH", code="GHCFG-001", src="daemon", msg="branch unprotected", now=200)
    block = fl.surface_block(None)
    assert "WINDOW-BURN" not in block
    assert "GHCFG-001" in block
    assert fl.surface_block(None) == "", "both entries (incl. the filtered one) must be acked"


def test_window_burn_entries_are_recorded_and_visible_to_unread_entries(_isolate: Path) -> None:
    """The suppression is PUSH-only: the data itself is kept (still `record()`-ed to disk)
    and still visible via `unread_entries()` with no `exclude_codes` — the read
    `/janitor-findings` uses."""
    fl.record(sev="HIGH", code="WINDOW-BURN", src="window-burn-rate", msg="5h window hot", now=100)
    entries = _entries(None)
    assert len(entries) == 1 and entries[0]["code"] == "WINDOW-BURN"
    lines, total = fl.unread_entries(None)
    assert total == 1 and "WINDOW-BURN" in lines[0]


# ---------- 5. seams + fail-open ----------


def test_notify_seam_receives_the_entry_and_never_breaks_record(_isolate: Path) -> None:
    """Sink 3 (TRDD-4649ZLE0 seam): the callable gets the sanitized entry dict; a
    raising notifier must not break record()."""
    got: list[dict] = []
    fl.record(sev="HIGH", code="N-1", src="daemon", msg="pushable", notify=got.append)
    assert got and got[0]["code"] == "N-1"

    def boom(_e: dict) -> None:
        raise RuntimeError("push channel down")

    line = fl.record(sev="HIGH", code="N-2", src="daemon", msg="still records", notify=boom)
    assert line is not None and len(_entries(None)) == 2


def test_opt_out_disables_the_ledger_write_but_not_sink_2(
    _isolate: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLAUDE_PLUGIN_OPTION_FINDINGS_LEDGER_ENABLED=false: no file write, but the
    own-session drift line still returns — surfacing beats bookkeeping."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FINDINGS_LEDGER_ENABLED", "false")
    line = fl.record(sev="HIGH", code="O-1", src="d", msg="opted out")
    assert line is not None
    assert not fl.ledger_path(None).exists()


# ---------- 6. human-only findings class (TRDD-KU3ERYFX, janitor#234) ----------


def test_human_only_directive_reaches_the_reader_at_delivery(_isolate: Path) -> None:
    """`actor='human'` makes the reading agent's correct move unambiguous — surface it,
    do not act on it — and does so WITHOUT spending the finding's own character budget.

    Was: the directive was concatenated onto `msg` before the cap. It is 98 chars against
    a 120-char cap, so a human-only finding kept 22 characters of itself. The first real
    caller recorded a spend figure with the budget it was measured against truncated off.
    """
    fl.record(sev="HIGH", code="H-1", src="d", msg="TCC grant needed", actor="human")
    entries = _entries(None)
    assert len(entries) == 1
    assert entries[0]["actor"] == "human"
    assert entries[0]["msg"] == "TCC grant needed", "the content is stored intact"
    assert "surface this to your human" in fl.render_line(entries[0]), (
        "and the directive still reaches the reader — at delivery, not in storage"
    )


def test_human_only_costs_the_finding_none_of_its_budget(_isolate: Path) -> None:
    """A full-length human-only finding survives whole. This is the regression the split
    exists for, so it is asserted on a message that fills the cap rather than a short one
    (the old code passed every SHORT-message test while destroying every long one)."""
    msg = "x" * fl.MAX_MSG_CHARS
    fl.record(sev="HIGH", code="H-1b", src="d", msg=msg, actor="human")
    assert _entries(None)[0]["msg"] == msg, "no content lost to the marking"


def test_human_only_adds_one_additive_key_and_shortens_the_line(_isolate: Path) -> None:
    """The marking is a delivery property, so it is a KEY — the §6.5 dashboard feed shape
    {ts,sev,code,src,ref,msg} plus an OPTIONAL `actor`, present only when human-only.

    Additive by design: a consumer reading named fields is unaffected, and the ≤200-char
    promise is honoured BETTER than before, because moving the 98-char directive out of
    `msg` costs only the ~17 chars of the new key. A non-human entry is byte-identical to
    the old shape, which is what keeps this safe for the accepted feed.
    """
    fl.record(sev="HIGH", code="H-2", src="d", msg="grant needed", actor="human")
    human = json.loads(fl.ledger_path(None).read_text(encoding="utf-8").strip())
    assert set(human) == {"ts", "sev", "code", "src", "ref", "msg", "actor"}
    assert len(json.dumps(human, separators=(",", ":"))) <= 200, "the ≤200 promise holds"

    fl.ledger_path(None).unlink()
    fl.record(sev="HIGH", code="H-2", src="d", msg="grant needed")
    agent = json.loads(fl.ledger_path(None).read_text(encoding="utf-8").strip())
    assert set(agent) == {"ts", "sev", "code", "src", "ref", "msg"}, (
        "a normal entry keeps the original key set exactly — the new key is opt-in"
    )


def test_human_only_emits_once_per_episode_but_still_records(_isolate: Path) -> None:
    """Repeat calls with the SAME (code, msg) — the same episode — record to the ledger
    every time (data is never lost) but return the drift line only the first time (no
    alarm-fatigue repeat print)."""
    first = fl.record(sev="HIGH", code="H-3", src="d", msg="same observation", actor="human")
    second = fl.record(sev="HIGH", code="H-3", src="d", msg="same observation", actor="human")
    assert first is not None and second is None
    assert len(_entries(None)) == 2, "the ledger keeps BOTH events even though only one surfaced"


def test_human_only_distinct_content_resurfaces(_isolate: Path) -> None:
    """A DIFFERENT observation under the same code is new information — it surfaces."""
    first = fl.record(sev="HIGH", code="H-4", src="d", msg="observation A", actor="human")
    second = fl.record(sev="HIGH", code="H-4", src="d", msg="observation B", actor="human")
    assert first is not None and second is not None


def test_surfaced_to_human_status_never_reported_then_reported_pending(_isolate: Path) -> None:
    """The ledger's own answer to "was a human ever told?" — before any record: never
    reported; after: reported-pending (the peer's ask, janitor#234)."""
    content_hash = "deadbeefdeadbeef"
    assert fl.surfaced_to_human_status("H-5", content_hash) == "never-reported"
    assert fl.mark_surfaced_to_human("H-5", content_hash) is True
    assert fl.surfaced_to_human_status("H-5", content_hash) == "reported-pending"
    assert fl.mark_surfaced_to_human("H-5", content_hash) is False, "a repeat mark is not a NEW surfacing"


def test_clear_surfaced_to_human_resets_the_stamp(_isolate: Path) -> None:
    """The stamp must not outlive the condition (TRDD-KU3ERYFX LIVE INSTANCE #2): once
    cleared, the SAME content hash reports never-reported again and re-surfaces."""
    content_hash = "cafebabecafebabe"
    fl.mark_surfaced_to_human("H-6", content_hash)
    assert fl.surfaced_to_human_status("H-6", content_hash) == "reported-pending"
    fl.clear_surfaced_to_human("H-6")
    assert fl.surfaced_to_human_status("H-6", content_hash) == "never-reported"
    assert fl.mark_surfaced_to_human("H-6", content_hash) is True


def test_clear_surfaced_to_human_does_not_touch_other_codes(_isolate: Path) -> None:
    """Clearing one code's stamps must not disturb an unrelated code's."""
    fl.mark_surfaced_to_human("H-7", "hash1")
    fl.mark_surfaced_to_human("H-8", "hash2")
    fl.clear_surfaced_to_human("H-7")
    assert fl.surfaced_to_human_status("H-7", "hash1") == "never-reported"
    assert fl.surfaced_to_human_status("H-8", "hash2") == "reported-pending"


def test_human_only_isolation_still_holds(tmp_path: Path, _isolate: Path) -> None:
    """The human-only path must not weaken the per-project isolation invariant
    (TRDD-X92VBFNF, ARCHITECTURE.md §3): a human-only finding about repo B never
    surfaces in repo A's session, and its stamp lives under repo B's own state dir."""
    repo_b = tmp_path / "repo-b"
    line = fl.record(sev="HIGH", code="H-9", src="daemon", msg="repo B needs a human",
                     actor="human", project_dir=repo_b)
    assert line is None, "repo B's finding must not surface in repo A's session"
    assert fl.surfaced_to_human_status("H-9", "whatever") == "never-reported", (
        "repo A's own stamp store must be untouched by repo B's recording"
    )


def test_corrupt_lines_are_skipped_not_fatal(_isolate: Path) -> None:
    """A torn/garbage line in the NDJSON must not hide the valid entries around it."""
    fl.record(sev="HIGH", code="G-1", src="d", msg="good one", now=100)
    with fl.ledger_path(None).open("a", encoding="utf-8") as fh:
        fh.write("{torn json…\n")
    fl.record(sev="HIGH", code="G-2", src="d", msg="good two", now=200)
    lines, total = fl.unread_entries(None)
    assert total == 2 and "G-2" in lines[0] and "G-1" in lines[1]


# ---------- 7. the measurement's age (TRDD-D6RDPZIU) ----------
#
# A finding is recorded once and may be SURFACED much later — by the unread block on the
# next session, or by `/janitor-findings` days on. Without an age on the line, that later
# reading is indistinguishable from a fresh measurement. Measured 2026-08-16: a
# `system-daemon-runaway` line reporting "CPU 390%" was surfaced while the named process
# sat at 5.3% and a re-run of the detector produced nothing at all.


def test_the_drift_line_says_when_the_finding_was_measured(_isolate: Path) -> None:
    """End-to-end through the REAL record → render path, not a hand-built dict: a finding
    recorded now surfaces as `just now`. Driving `record` is the point — the bug was that
    `record` stored `ts` and the renderer never read it, so a test that formats its own
    entry would have passed against the defect."""
    line = fl.record(sev="HIGH", code="AGE-1", src="detector", msg="fresh finding")
    assert line is not None
    assert line.endswith("just now"), (
        f"a freshly recorded finding must date itself on the line the human reads: {line!r}"
    )


def test_an_old_finding_is_not_presented_as_a_current_one(_isolate: Path) -> None:
    """The incident's exact shape: an entry measured hours/days ago, surfaced later. The
    age is rendered from the stored `ts`, so the reader can tell it is history."""
    fl.record(sev="HIGH", code="AGE-2", src="detector", msg="stale finding", now=1_000_000)
    entry = _entries(None)[-1]
    assert fl.render_line(entry, now=1_000_000 + 7200).endswith("2h ago")
    assert fl.render_line(entry, now=1_000_000 + 3 * 86400).endswith("3d ago")
    assert fl.render_line(entry, now=1_000_000 + 600).endswith("10m ago")


def test_an_unusable_timestamp_says_so_instead_of_going_quiet(_isolate: Path) -> None:
    """An entry comes off DISK, where anything could have written it, so a missing or
    malformed `ts` is reachable without a bug. It must render an EXPLICIT unknown: an
    omitted age would read as 'fresh', which is the same ambiguity the age exists to
    remove (ATOM-ZFUE-H8IZ — silence cannot distinguish clean from did-not-look).

    A backwards clock (an NTP step, a restored ledger, a hand-edited entry) is the same
    case: a negative delta must never print as a measurement from the future."""
    base = {"sev": "HIGH", "code": "AGE-3", "src": "d", "msg": "m", "ref": "-"}
    for bad in ({}, {"ts": None}, {"ts": "1700000000"}, {"ts": True}):
        assert fl.render_line({**base, **bad}, now=1_000_000).endswith("age unknown"), (
            f"an unusable ts must render an explicit unknown, not nothing: {bad!r}"
        )
    assert fl.render_line({**base, "ts": 2_000_000}, now=1_000_000).endswith("age unknown")


# ---------- 6. .janitor.toml suppression at the choke point (TRDD-8524H5V1) ----------


def _rec_host() -> str | None:
    return fl.record(sev="MEDIUM", code="HOST-001", src="host-load", msg="load is high")


def test_lint_ignore_suppresses_record(_isolate: Path) -> None:
    """`[lint] ignore = ["HOST"]` makes record() return None and append nothing."""
    (_isolate / ".janitor.toml").write_text('[lint]\nignore = ["HOST"]\n', encoding="utf-8")
    assert _rec_host() is None
    assert _entries() == []


def test_record_without_config_is_recorded(_isolate: Path) -> None:
    """No .janitor.toml: nothing is suppressed, the finding is appended."""
    assert _rec_host() is not None
    assert [e["code"] for e in _entries()] == ["HOST-001"]


def test_malformed_config_records_finding_and_one_config_001(_isolate: Path) -> None:
    """A malformed .janitor.toml suppresses nothing; the typo is reported once, not per call."""
    (_isolate / ".janitor.toml").write_text("[lint\nignore = ", encoding="utf-8")
    assert _rec_host() is not None
    assert _rec_host() is not None
    codes = [e["code"] for e in _entries()]
    assert codes.count("HOST-001") == 2
    assert codes.count("CONFIG-001") == 1


def test_select_without_ignore_suppresses_nothing(_isolate: Path) -> None:
    """The same file configures memgrep lint: `select = ["WM"]` must not silence ledger records."""
    (_isolate / ".janitor.toml").write_text('[lint]\nselect = ["WM"]\n', encoding="utf-8")
    assert _rec_host() is not None
    assert [e["code"] for e in _entries()] == ["HOST-001"]


def test_high_and_human_findings_are_never_suppressed(_isolate: Path) -> None:
    """A repository's own file must not silence a HIGH/CRITICAL/ERROR or human-only alert."""
    (_isolate / ".janitor.toml").write_text('[lint]\nignore = ["HOST"]\n', encoding="utf-8")
    fl.record(sev="HIGH", code="HOST-001", src="s", msg="m")
    fl.record(sev="critical", code="HOST-001", src="s", msg="m")
    fl.record(sev="LOW", code="HOST-001", src="s", msg="m", actor="human")
    fl.record(sev="ERROR", code="HOST-001", src="s", msg="m")
    assert len(_entries()) == 4
    assert fl.record(sev="LOW", code="HOST-001", src="s", msg="m") is None  # suppression is active here
    assert len(_entries()) == 4


def test_empty_string_selector_selects_nothing(_isolate: Path) -> None:
    """`ignore = [""]` must not silence every code."""
    (_isolate / ".janitor.toml").write_text('[lint]\nignore = [""]\n', encoding="utf-8")
    assert _rec_host() is not None
    assert [e["code"] for e in _entries()] == ["HOST-001"]


def test_record_never_raises_when_state_dir_cannot_be_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    """record() must not raise even if the state dir resolution itself fails."""
    def boom(*_a: object, **_k: object) -> Path:
        raise RuntimeError("no state dir")

    monkeypatch.setattr(fl, "state_dir_for", boom)
    fl.record(sev="MEDIUM", code="HOST-001", src="s", msg="m")


def test_config_001_reports_again_after_fix_and_rebreak(_isolate: Path) -> None:
    """Broken, fixed, broken again: two CONFIG-001 entries (the latch is forgotten on a clean parse)."""
    cfg = _isolate / ".janitor.toml"
    cfg.write_text("[lint\n", encoding="utf-8")
    _rec_host()
    cfg.write_text('[lint]\nignore = ["NOPE"]\n', encoding="utf-8")
    _rec_host()
    cfg.write_text("[lint\n", encoding="utf-8")
    _rec_host()
    assert [e["code"] for e in _entries()].count("CONFIG-001") == 2
