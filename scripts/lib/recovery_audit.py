"""Recovery audit log (immortality F3, TRDD-F3AUDLOG) — append-only, tamper-evident
NDJSON of every fleet-guardian recovery DECISION.

The daemon's fleet beat (`daemon.task_session_liveness`) keeps only per-instance
recovery *state* (`{attempts, last_ts, identity, alerted}`) and OVERWRITES it every
beat — so "which rung fired, on which session, when, with what outcome — historically"
is unanswerable. This module adds that missing forensic record without touching the
recovery logic: it is a pure side-channel.

Design (REUSE, don't reinvent — per the TRDD):
  * The log format is the EXISTING `janitor_self_integrity.AuditChain` HMAC-SHA256
    chained NDJSON primitive (already tested), so the recovery log is tamper-evident
    for free and no new format is invented.
  * The HMAC key resolves via the SAME canonical FIXED-DATA-dir resolver the
    self-integrity detector uses (`version_update_lib._data_dir()` →
    `load_or_create_key`), NEVER `$CLAUDE_PLUGIN_DATA` (that points at whichever
    plugin owns the running turn — the documented foot-gun) — so the key is stable
    across sessions and survives plugin updates.
  * Rotation mirrors `token_meter.trim_log` (bounded size, oldest-trimmed).

FAIL-OPEN is the load-bearing invariant. `record_recovery` is the brick-risk call
the daemon makes from inside the recovery beat: a logging fault (disk full, missing
key, AuditChain raise) must NEVER perturb the beat. So the whole append+rotate body
is wrapped `try/except Exception` (BLE001) and returns None on any failure — the audit
is best-effort observability, the recovery beat is survival-critical and stays byte-
untouched. The daemon ALSO wraps the call (belt-and-suspenders); this module is the
primary guard and is independently unit-testable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import global_state as gs  # noqa: E402  -- sibling in scripts/lib/
import janitor_self_integrity as jsi  # noqa: E402  -- AuditChain + key resolver
import version_update_lib as vu  # noqa: E402  -- the canonical FIXED-DATA-dir resolver

# Spec-mandated filename: the audit log lives beside the per-instance recovery state
# the daemon already writes under the global-state dir.
_AUDIT_FILENAME = "recovery-audit.ndjson"

# Rotation caps — mirror token_meter.trim_log's defaults. At one record per recovery
# DECISION (only fired/declined/dry-run/crash-loop instances, not every healthy one),
# 5000 records is a deep history; the 1 MB cap rewrites rarely.
_KEEP_LINES = 5000
_MAX_BYTES = 1_000_000

# The fields every record carries (the TRDD's record shape). Kept as a constant so the
# producer and any reader agree on the schema. `outcome` ∈ fired | fire_failed |
# dry_run | declined_cooldown | declined_crash_loop | unreachable | declined_unwired.
_RECORD_FIELDS = (
    "ts", "project_root", "pid", "tty", "diagnosis", "rung", "channel", "outcome",
)


def recovery_audit_path() -> Path:
    """The recovery-audit NDJSON path: ``<global_state_dir>/recovery-audit.ndjson``.

    The FILE lives under the global-state dir (alongside the per-instance recovery
    state). The HMAC KEY lives in the FIXED DATA dir (see ``_resolve_key``) — a
    deliberate split: the file is host-machine state, the key is the stable signing
    secret that must survive plugin updates.
    """
    return gs.global_state_dir() / _AUDIT_FILENAME


def _resolve_key() -> Optional[bytes]:
    """The DATA-dir HMAC key (minted on first use), or None when no DATA dir is
    resolvable. NEVER ``$CLAUDE_PLUGIN_DATA`` — uses the SAME canonical resolver the
    self-integrity detector + C3 pin use, so the key matches across sessions and the
    recovery chain stays verifiable. None ⇒ the audit append fail-opens (no key, no
    record — never a crash)."""
    return jsi.load_or_create_key(vu._data_dir())


def record_recovery(
    *,
    ts: int,
    project_root: str,
    pid: int | None,
    tty: str | None,
    diagnosis: str,
    rung: str | None,
    channel: str | None,
    outcome: str,
    path: Path | None = None,
) -> Optional[dict]:
    """Append ONE recovery-decision record to the audit chain. FAIL-OPEN.

    Returns the written entry (incl. the chain's ``prev_hmac``/``hmac``) on success,
    or None on ANY failure (no key, I/O error, AuditChain raise). A None return is
    NOT an error the caller must handle — the audit is best-effort; the recovery beat
    proceeds regardless. This is the whole point of F3 being pure observability with
    zero blast radius.

    Every branch is inside the single ``try`` so that NOTHING — not key resolution,
    not path resolution, not the append, not the rotation — can escape into the
    daemon's recovery loop.
    """
    try:
        key = _resolve_key()
        if not key:
            return None  # no signing key ⇒ no tamper-evident record; skip (fail-open)
        log_path = path if path is not None else recovery_audit_path()
        record = {
            "ts": int(ts),
            "project_root": project_root,
            "pid": int(pid) if pid is not None else None,
            "tty": tty or "",
            "diagnosis": diagnosis,
            "rung": rung or "",
            "channel": channel or "",
            "outcome": outcome,
        }
        chain = jsi.AuditChain(log_path, key)
        entry = chain.append(record)
        # Rotate AFTER the append so the just-written record is always present even if
        # rotation later trims older history. Pass the module-level caps EXPLICITLY (not
        # via trim's defaults) so the production cap is the single-source-of-truth module
        # constant — read live, so an operator/test override of _MAX_BYTES/_KEEP_LINES
        # actually takes effect. Rotation is itself fail-open (see below).
        trim_recovery_audit(log_path, keep_lines=_KEEP_LINES, max_bytes=_MAX_BYTES)
        return entry
    except Exception:  # noqa: BLE001 -- an audit fault must NEVER crash the recovery beat
        # Intentionally silent: this is a side-channel. The daemon logs its own
        # recovery line regardless, so a dropped audit record loses only forensic
        # history, never recovery behaviour. (Mirrors the C4 rollback producer's
        # fail-open guard in dispatch.py.)
        return None


def trim_recovery_audit(
    path: Path | None = None,
    *,
    keep_lines: int = _KEEP_LINES,
    max_bytes: int = _MAX_BYTES,
) -> None:
    """Cap the append-only audit log — mirror of ``token_meter.trim_log``.

    When the file exceeds ``max_bytes``, atomically rewrite it keeping only the last
    ``keep_lines`` records. Amortised-cheap: only rewrites when oversized.

    TRADE-OFF (documented): the audit log is an ``AuditChain`` whose ``prev_hmac``
    links each entry back to a key-derived genesis. Trimming the PREFIX means a later
    full-chain ``verify()`` from genesis will report a break at the new first line.
    That is acceptable AND intentional here: F3 is a forensic *rollup* ("the last N
    recoveries"), not a genesis-anchored attestation — so bounded size beats an
    unbounded chain, exactly as ``token_meter`` chose. Each retained record's OWN
    ``hmac`` still detects in-place tampering of that record; only the cross-line
    chain back past the trim point is sacrificed. Fail-open: any I/O error leaves the
    file untouched.
    """
    p = path if path is not None else recovery_audit_path()
    try:
        if not p.is_file() or p.stat().st_size <= max_bytes:
            return
        lines = [ln for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        kept = lines[-keep_lines:]
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass


def load_records(path: Path | None = None) -> list[dict]:
    """Every audit record as a dict, file order. Fail-open ``[]`` on a missing /
    unreadable / malformed file (one bad line is skipped, not fatal)."""
    p = path if path is not None else recovery_audit_path()
    if not p.is_file():
        return []
    out: list[dict] = []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            rec = json.loads(s)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def load_recent(path: Path | None = None, *, limit: int = 10) -> list[dict]:
    """The most-recent ``limit`` records, newest LAST (file order is chronological
    because the log is append-only). Fail-open ``[]``."""
    if limit <= 0:
        return []
    return load_records(path)[-limit:]


def summarize_recent(records: list[dict]) -> Optional[dict]:
    """A compact rollup of recovery history for the dashboard, or None on empty input.

    Returns counts the F2 dashboard can render at a glance: how many decisions total,
    how many actually FIRED, a per-outcome breakdown, the distinct projects touched,
    and the latest decision's timestamp. Pure — no I/O."""
    if not records:
        return None
    by_outcome: dict[str, int] = {}
    projects: set[str] = set()
    latest_ts = 0
    fired = 0
    for r in records:
        outcome = str(r.get("outcome", "") or "unknown")
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        if outcome == "fired":
            fired += 1
        proj = r.get("project_root")
        if isinstance(proj, str) and proj:
            projects.add(proj)
        try:
            ts = int(r.get("ts", 0) or 0)
        except (ValueError, TypeError):
            ts = 0
        if ts > latest_ts:
            latest_ts = ts
    return {
        "total": len(records),
        "fired": fired,
        "by_outcome": by_outcome,
        "projects": len(projects),
        "latest_ts": latest_ts or None,
    }
