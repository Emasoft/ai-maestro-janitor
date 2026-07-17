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
    """15 unread ⇒ at most SURFACE_CAP_LINES lines + ONE fold line naming the remainder
    and /janitor-findings; block ≤ ~1.2 KB; and surfacing ACKS (second call empty)."""
    for i in range(15):
        fl.record(sev="HIGH", code=f"C-{i:02d}", src="d", msg=f"finding {i}", now=100 + i)
    block = fl.surface_block(None)
    lines = block.splitlines()
    assert 0 < len(lines) <= fl.SURFACE_CAP_LINES + 1
    assert "older unread" in lines[-1] and "/janitor-findings" in lines[-1]
    assert len(block.encode("utf-8")) <= fl.SURFACE_BUDGET_BYTES + 200
    assert fl.surface_block(None) == "", "surfacing advances the cursor — no repeat"


def test_surface_block_silent_on_empty_inbox(_isolate: Path) -> None:
    """No unread ⇒ empty string — no empty-inbox chatter at session start."""
    assert fl.surface_block(None) == ""


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


def test_corrupt_lines_are_skipped_not_fatal(_isolate: Path) -> None:
    """A torn/garbage line in the NDJSON must not hide the valid entries around it."""
    fl.record(sev="HIGH", code="G-1", src="d", msg="good one", now=100)
    with fl.ledger_path(None).open("a", encoding="utf-8") as fh:
        fh.write("{torn json…\n")
    fl.record(sev="HIGH", code="G-2", src="d", msg="good two", now=200)
    lines, total = fl.unread_entries(None)
    assert total == 2 and "G-2" in lines[0] and "G-1" in lines[1]
