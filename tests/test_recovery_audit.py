"""Tests for the F3 recovery audit log (TRDD-F3AUDLOG) — scripts/lib/recovery_audit.py.

Real I/O, no mocks. Each case isolates the audit FILE via ``JANITOR_GLOBAL_STATE_DIR``
and the HMAC KEY via ``JANITOR_DATA_DIR`` (both honored by the live resolvers), so the
test never touches the real machine state.

Coverage:
  * record_recovery → AuditChain round-trip (record fields present, chain verifies)
  * record_recovery is FAIL-OPEN: no key → None + no file written; AuditChain raise →
    None + no crash
  * trim_recovery_audit mirrors token_meter.trim_log (oversized → keep last N)
  * load_records / load_recent
  * summarize_recent counts, per-outcome breakdown, empty input
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LIB_DIR = _PROJECT_ROOT / "scripts" / "lib"

assert (_LIB_DIR / "recovery_audit.py").is_file(), "recovery_audit lib missing"

sys.path.insert(0, str(_LIB_DIR))

import janitor_self_integrity as jsi  # noqa: E402
import recovery_audit as ra  # noqa: E402


@pytest.fixture
def isolated(monkeypatch, tmp_path: Path):
    """Point both the audit FILE dir and the HMAC KEY dir at tmp dirs.

    ``JANITOR_GLOBAL_STATE_DIR`` controls where recovery-audit.ndjson lands;
    ``JANITOR_DATA_DIR`` controls where the integrity key is minted. A bogus
    ``CLAUDE_PLUGIN_DATA`` is set to prove the resolver IGNORES it (the foot-gun the
    module deliberately avoids)."""
    gstate = tmp_path / "gstate"
    data = tmp_path / "data"
    gstate.mkdir()
    data.mkdir()
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gstate))
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "bogus-other-plugin"))
    return {"gstate": gstate, "data": data}


def _rec(ra_mod, *, outcome: str = "fired", project_root: str = "/tmp/projA",
         pid: int = 123, diagnosis: str = "frozen", rung: str = "rearm",
         channel: str = "iterm") -> dict | None:
    return ra_mod.record_recovery(
        ts=1_750_000_000, project_root=project_root, pid=pid, tty="ttys001",
        diagnosis=diagnosis, rung=rung, channel=channel, outcome=outcome,
    )


def test_record_round_trip_and_chain_verifies(isolated) -> None:
    """A recorded decision lands in the audit ndjson at the spec path, carries every
    record field, and the underlying AuditChain verifies clean."""
    entry = _rec(ra)
    assert entry is not None
    # Every record field (the TRDD schema) plus the chain's prev_hmac/hmac.
    for field in ("ts", "project_root", "pid", "tty", "diagnosis", "rung", "channel", "outcome"):
        assert field in entry
    assert entry["outcome"] == "fired"
    assert entry["diagnosis"] == "frozen"
    assert entry["pid"] == 123

    path = ra.recovery_audit_path()
    assert path.name == "recovery-audit.ndjson"
    assert path.is_file()

    # The chain (keyed by the FIXED-DATA-dir key) verifies, proving it's a real
    # AuditChain — not a bespoke format.
    key = jsi.load_or_create_key(isolated["data"])
    assert isinstance(key, bytes)
    ok, checked, reason = jsi.AuditChain(path, key).verify()
    assert ok, reason
    assert checked == 1


def test_two_records_chain_links(isolated) -> None:
    """Two appends produce a 2-entry chain whose second prev_hmac links to the first
    hmac (tamper-evidence intact)."""
    first = _rec(ra, outcome="fired")
    second = _rec(ra, outcome="dry_run")
    assert first is not None and second is not None
    assert second["prev_hmac"] == first["hmac"]
    key = jsi.load_or_create_key(isolated["data"])
    assert isinstance(key, bytes)
    ok, checked, reason = jsi.AuditChain(ra.recovery_audit_path(), key).verify()
    assert ok, reason
    assert checked == 2


def test_fail_open_no_key(monkeypatch, tmp_path: Path) -> None:
    """No resolvable DATA dir ⇒ no signing key ⇒ record_recovery returns None and
    writes NOTHING — fail-open, never a crash."""
    gstate = tmp_path / "gstate"
    gstate.mkdir()
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gstate))
    # Force the key resolver to yield None (the real "no DATA dir / HOME unresolvable"
    # state) without depending on environment specifics.
    monkeypatch.setattr(ra, "_resolve_key", lambda: None)
    entry = _rec(ra)
    assert entry is None
    assert not ra.recovery_audit_path().is_file()


def test_fail_open_on_append_raise(isolated, monkeypatch) -> None:
    """If the AuditChain append raises (disk-full / corruption surrogate),
    record_recovery swallows it and returns None — the recovery beat must never see
    the exception."""
    class _Boom:
        def __init__(self, *a, **k):  # noqa: D401 - test surrogate
            pass

        def append(self, *_a, **_k):
            raise OSError("simulated disk-full")

    monkeypatch.setattr(ra.jsi, "AuditChain", _Boom)
    # Must not raise — the whole point of the fail-open guard.
    entry = _rec(ra)
    assert entry is None


def test_load_records_and_recent(isolated) -> None:
    """load_records returns all records in file order; load_recent returns the tail."""
    for i in range(5):
        _rec(ra, outcome="fired", project_root=f"/tmp/proj{i}")
    recs = ra.load_records()
    assert len(recs) == 5
    assert [r["project_root"] for r in recs] == [f"/tmp/proj{i}" for i in range(5)]
    recent = ra.load_recent(limit=2)
    assert len(recent) == 2
    assert recent[-1]["project_root"] == "/tmp/proj4"
    assert ra.load_recent(limit=0) == []


def test_load_records_missing_file(isolated) -> None:
    """No log yet ⇒ load_records is [] (fail-open), not an error."""
    assert ra.load_records() == []
    assert ra.load_recent(limit=5) == []
    assert ra.summarize_recent([]) is None


def test_trim_rotation_keeps_last_n(isolated) -> None:
    """trim_recovery_audit mirrors token_meter.trim_log: an oversized log is rewritten
    keeping only the last keep_lines records."""
    path = ra.recovery_audit_path()
    # Write 50 plausible NDJSON lines directly so we control the count + size.
    lines = [f'{{"ts":{1_750_000_000 + i},"outcome":"fired","n":{i}}}' for i in range(50)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Force a rewrite by setting max_bytes tiny; keep only the last 10.
    ra.trim_recovery_audit(path, keep_lines=10, max_bytes=1)
    kept = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(kept) == 10
    assert kept[0].endswith('"n":40}')
    assert kept[-1].endswith('"n":49}')


def test_trim_noop_when_small(isolated) -> None:
    """Under the size cap, trim leaves the file byte-identical."""
    path = ra.recovery_audit_path()
    _rec(ra)
    before = path.read_bytes()
    ra.trim_recovery_audit(path, keep_lines=10, max_bytes=10_000_000)
    assert path.read_bytes() == before


def test_record_triggers_rotation(isolated, monkeypatch) -> None:
    """record_recovery rotates AFTER appending — the just-written record always
    survives even when rotation trims older history."""
    # Tiny caps so every append rotates down to the most recent record.
    monkeypatch.setattr(ra, "_MAX_BYTES", 1)
    monkeypatch.setattr(ra, "_KEEP_LINES", 1)
    _rec(ra, outcome="fired", project_root="/tmp/old")
    last = _rec(ra, outcome="dry_run", project_root="/tmp/new")
    assert last is not None
    recs = ra.load_records()
    assert len(recs) == 1
    assert recs[0]["project_root"] == "/tmp/new"
    assert recs[0]["outcome"] == "dry_run"


def test_summarize_recent_counts_and_breakdown(isolated) -> None:
    """summarize_recent reports totals, fired count, per-outcome breakdown, distinct
    projects, and the latest ts."""
    records = [
        {"ts": 10, "outcome": "fired", "project_root": "/a"},
        {"ts": 20, "outcome": "fired", "project_root": "/a"},
        {"ts": 30, "outcome": "dry_run", "project_root": "/b"},
        {"ts": 25, "outcome": "declined_crash_loop", "project_root": "/b"},
    ]
    summ = ra.summarize_recent(records)
    assert summ is not None
    assert summ["total"] == 4
    assert summ["fired"] == 2
    assert summ["by_outcome"] == {"fired": 2, "dry_run": 1, "declined_crash_loop": 1}
    assert summ["projects"] == 2
    assert summ["latest_ts"] == 30


def test_summarize_handles_bad_ts(isolated) -> None:
    """A non-numeric ts in a record degrades to 0, never crashes the rollup."""
    records = [{"ts": "garbage", "outcome": "fired", "project_root": "/a"}]
    summ = ra.summarize_recent(records)
    assert summ is not None
    assert summ["fired"] == 1
    assert summ["latest_ts"] is None  # only bad ts → no latest


def test_pid_none_recorded_as_null(isolated) -> None:
    """A None pid is recorded as JSON null (not the string 'None'), and the record
    still round-trips + verifies."""
    entry = ra.record_recovery(
        ts=1_750_000_000, project_root="/tmp/p", pid=None, tty=None,
        diagnosis="cron_dead", rung="rearm", channel="tmux", outcome="fired",
    )
    assert entry is not None
    assert entry["pid"] is None
    assert entry["tty"] == ""
    recs = ra.load_records()
    assert recs[0]["pid"] is None
