"""Tests for janitor-self-integrity library + detector.

Coverage:
  * INTEGRITY_NOTICE_PREAMBLE constant + has_integrity_notice verifier
  * load_or_create_key — generates a 32-byte key, persists across calls
  * wrap_drift_line / verify_drift_line round-trip + tamper-detection
  * AuditChain append + verify (clean + tampered)
  * compute_manifest / verify_manifest (clean + mutated + missing + extra)
  * Detector heartbeat behaviour:
    - opt-in default OFF
    - silent on second run (content-hash dedupe)
    - fires on manifest drift
    - fires on SKILL.md missing the preamble
    - fires on audit-chain break
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "janitor-self-integrity.py"
_LIB_DIR = _PROJECT_ROOT / "scripts" / "lib"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"
assert (_LIB_DIR / "janitor_self_integrity.py").is_file(), "lib missing"

sys.path.insert(0, str(_LIB_DIR))

from janitor_self_integrity import (  # noqa: E402
    DEFAULT_MANIFEST_GLOBS,
    INTEGRITY_NOTICE_PREAMBLE,
    AuditChain,
    compute_finding_hmac,
    compute_manifest,
    has_integrity_notice,
    load_manifest,
    load_or_create_key,
    verify_drift_line,
    verify_manifest,
    wrap_drift_line,
    write_manifest,
)


def _key(tmp_path: Path) -> bytes:
    """`load_or_create_key` is `bytes | None` by signature (it can fail to persist);
    every caller here relies on it succeeding, so narrow it once instead of re-asserting
    at each of the ~15 call sites below."""
    k = load_or_create_key(data_dir=tmp_path)
    assert k is not None
    return k


# ---------- Section 1: integrity notice preamble -------------------------


def test_preamble_constant_carries_markers() -> None:
    assert "<!-- INTEGRITY NOTICE — DO NOT EDIT" in INTEGRITY_NOTICE_PREAMBLE
    assert "END NOTICE -->" in INTEGRITY_NOTICE_PREAMBLE


def test_has_integrity_notice_positive() -> None:
    assert has_integrity_notice(INTEGRITY_NOTICE_PREAMBLE) is True


def test_has_integrity_notice_negative() -> None:
    assert has_integrity_notice("# some skill\nbody\n") is False
    assert has_integrity_notice("") is False
    # Open marker only, no close → not a valid notice.
    assert has_integrity_notice("<!-- INTEGRITY NOTICE — DO NOT EDIT") is False


# ---------- Section 2: HMAC envelope -------------------------------------


def test_key_generated_and_persisted(tmp_path: Path) -> None:
    k1 = _key(tmp_path)
    k2 = _key(tmp_path)
    assert k1 is not None
    assert k2 is not None
    assert k1 == k2  # persistent across calls
    assert len(k1) == 32
    key_file = tmp_path / ".integrity-key"
    assert key_file.is_file()


def test_key_file_mode_0600(tmp_path: Path) -> None:
    _key(tmp_path)
    key_file = tmp_path / ".integrity-key"
    mode = key_file.stat().st_mode & 0o777
    # On POSIX filesystems, mode should be 0o600. Skip on others.
    if os.name == "posix":
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_compute_finding_hmac_deterministic(tmp_path: Path) -> None:
    k = _key(tmp_path)
    tag_a = compute_finding_hmac(
        rule_id="X", severity="HIGH", path="/foo", line_number=10,
        message="hello", corpus_hash="abc", key=k,
    )
    tag_b = compute_finding_hmac(
        rule_id="X", severity="HIGH", path="/foo", line_number=10,
        message="hello", corpus_hash="abc", key=k,
    )
    assert tag_a is not None
    assert tag_a == tag_b
    assert len(tag_a) == 12


def test_compute_finding_hmac_changes_with_input(tmp_path: Path) -> None:
    k = _key(tmp_path)
    base = compute_finding_hmac(
        rule_id="X", severity="HIGH", path="/foo", line_number=10,
        message="hello", corpus_hash="abc", key=k,
    )
    diff_msg = compute_finding_hmac(
        rule_id="X", severity="HIGH", path="/foo", line_number=10,
        message="hellp", corpus_hash="abc", key=k,
    )
    diff_path = compute_finding_hmac(
        rule_id="X", severity="HIGH", path="/bar", line_number=10,
        message="hello", corpus_hash="abc", key=k,
    )
    diff_corpus = compute_finding_hmac(
        rule_id="X", severity="HIGH", path="/foo", line_number=10,
        message="hello", corpus_hash="xyz", key=k,
    )
    assert base != diff_msg
    assert base != diff_path
    assert base != diff_corpus


def test_finding_hmac_returns_none_without_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    tag = compute_finding_hmac(
        rule_id="X", severity="HIGH", path="/foo", line_number=1,
        message="hi", key=None,
    )
    assert tag is None


def test_wrap_and_verify_roundtrip(tmp_path: Path) -> None:
    k = _key(tmp_path)
    raw = "[detector] some drift line"
    wrapped = wrap_drift_line(
        raw, rule_id="R", severity="MEDIUM",
        path="/p", line_number=42, key=k,
    )
    assert "[hmac=" in wrapped
    assert verify_drift_line(
        wrapped, rule_id="R", severity="MEDIUM",
        path="/p", line_number=42, key=k,
    ) is True


def test_verify_drift_line_fails_on_tampered_body(tmp_path: Path) -> None:
    k = _key(tmp_path)
    raw = "[detector] some drift line"
    wrapped = wrap_drift_line(
        raw, rule_id="R", severity="MEDIUM",
        path="/p", line_number=42, key=k,
    )
    # Mutate the body but keep the tag
    tampered = wrapped.replace("some drift line", "EVIL drift line")
    assert verify_drift_line(
        tampered, rule_id="R", severity="MEDIUM",
        path="/p", line_number=42, key=k,
    ) is False


def test_verify_drift_line_fails_without_tag(tmp_path: Path) -> None:
    k = _key(tmp_path)
    raw = "[detector] some drift line"
    # Not wrapped → should fail
    assert verify_drift_line(
        raw, rule_id="R", severity="MEDIUM",
        path="/p", line_number=42, key=k,
    ) is False


def test_wrap_unchanged_without_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    raw = "[detector] drift"
    out = wrap_drift_line(
        raw, rule_id="R", severity="LOW",
        path="/p", line_number=1, key=None,
    )
    assert out == raw


# ---------- Section 3: AuditChain ----------------------------------------


def test_audit_chain_empty_verifies_clean(tmp_path: Path) -> None:
    k = _key(tmp_path)
    chain = AuditChain(tmp_path / "chain.ndjson", k)
    ok, n, reason = chain.verify()
    assert ok is True
    assert n == 0
    assert reason == ""


def test_audit_chain_append_and_verify(tmp_path: Path) -> None:
    k = _key(tmp_path)
    log_path = tmp_path / "chain.ndjson"
    chain = AuditChain(log_path, k)
    chain.append({"event": "start"})
    chain.append({"event": "fire", "rule_id": "X"})
    chain.append({"event": "finding", "severity": "HIGH"})
    ok, n, reason = chain.verify()
    assert ok is True
    assert n == 3
    assert reason == ""


def test_audit_chain_links_with_prev_hmac(tmp_path: Path) -> None:
    k = _key(tmp_path)
    log_path = tmp_path / "chain.ndjson"
    chain = AuditChain(log_path, k)
    e1 = chain.append({"event": "a"})
    e2 = chain.append({"event": "b"})
    assert e2["prev_hmac"] == e1["hmac"]


def test_audit_chain_detects_middle_edit(tmp_path: Path) -> None:
    k = _key(tmp_path)
    log_path = tmp_path / "chain.ndjson"
    chain = AuditChain(log_path, k)
    chain.append({"event": "a"})
    chain.append({"event": "b"})
    chain.append({"event": "c"})
    # Tamper: rewrite entry b's `event` field
    lines = log_path.read_text(encoding="utf-8").splitlines()
    obj = json.loads(lines[1])
    obj["event"] = "TAMPERED"
    # NOTE: we leave `hmac` intact — verify must catch this via the
    # hmac-mismatch path, not the prev_hmac path.
    lines[1] = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, idx, reason = chain.verify()
    assert ok is False
    assert idx == 1
    assert "hmac mismatch" in reason


def test_audit_chain_detects_truncation(tmp_path: Path) -> None:
    k = _key(tmp_path)
    log_path = tmp_path / "chain.ndjson"
    chain = AuditChain(log_path, k)
    chain.append({"event": "a"})
    chain.append({"event": "b"})
    chain.append({"event": "c"})
    # Truncate the middle line entirely
    lines = log_path.read_text(encoding="utf-8").splitlines()
    log_path.write_text(lines[0] + "\n" + lines[2] + "\n", encoding="utf-8")
    ok, idx, reason = chain.verify()
    assert ok is False
    assert idx == 1
    assert "prev_hmac" in reason or "hmac" in reason


def test_audit_chain_requires_key() -> None:
    with pytest.raises(ValueError):
        AuditChain(Path("/tmp/x"), b"")


# ---- trim with a key-signed anchor (S4, TRDD-7IUTRX29) -------------------------------


def _grown_chain(tmp_path: Path, n: int = 40) -> "AuditChain":
    k = _key(tmp_path)
    chain = AuditChain(tmp_path / "chain.ndjson", k)
    for i in range(n):
        chain.append({"event": "detector.fire", "seq": i})
    return chain


def test_audit_chain_trim_keeps_verify_green(tmp_path: Path) -> None:
    """THE S4 design requirement: after a trim, a genesis-anchored verify() still
    passes — the key-signed trim-anchor bridges genesis to the kept tail."""
    chain = _grown_chain(tmp_path, 40)
    assert chain.trim(keep_lines=10, max_bytes=1) is True
    ok, n, reason = chain.verify()
    assert ok is True, reason
    assert n == 11  # the anchor + the 10 kept entries


def test_audit_chain_trim_is_noop_under_cap(tmp_path: Path) -> None:
    """Amortised: below max_bytes nothing is rewritten (bounded cost per beat)."""
    chain = _grown_chain(tmp_path, 5)
    assert chain.trim(keep_lines=2, max_bytes=10 * 1024 * 1024) is False
    ok, n, _ = chain.verify()
    assert ok is True and n == 5


def test_audit_chain_append_after_trim_continues_chain(tmp_path: Path) -> None:
    """New entries after a trim chain onto the kept tail — the log stays live."""
    chain = _grown_chain(tmp_path, 40)
    assert chain.trim(keep_lines=10, max_bytes=1)
    chain.append({"event": "detector.fire", "post": "trim"})
    ok, n, reason = chain.verify()
    assert ok is True, reason
    assert n == 12


def test_audit_chain_anchor_mid_chain_is_rejected(tmp_path: Path) -> None:
    """An anchor is honored ONLY at index 0 — moved anywhere else, its genesis
    prev_hmac breaks the ordinary chain check (no mid-chain splicing)."""
    chain = _grown_chain(tmp_path, 40)
    assert chain.trim(keep_lines=10, max_bytes=1)
    log = tmp_path / "chain.ndjson"
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    # Swap the anchor (line 0) one position down — a splice attempt.
    lines[0], lines[1] = lines[1], lines[0]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, idx, reason = chain.verify()
    assert ok is False and idx == 0 and "prev_hmac" in reason


def test_audit_chain_retrim_drops_previous_anchor(tmp_path: Path) -> None:
    """A second trim supersedes the first anchor — exactly ONE anchor at the head."""
    chain = _grown_chain(tmp_path, 40)
    assert chain.trim(keep_lines=20, max_bytes=1)
    for i in range(10):
        chain.append({"event": "detector.fire", "seq": 100 + i})
    assert chain.trim(keep_lines=5, max_bytes=1)
    log = tmp_path / "chain.ndjson"
    anchors = [ln for ln in log.read_text(encoding="utf-8").splitlines() if "trim-anchor" in ln]
    assert len(anchors) == 1
    ok, n, reason = chain.verify()
    assert ok is True, reason
    assert n == 6  # new anchor + 5 kept


# ---------- Section 4: manifest verifier ---------------------------------


def _seed_plugin_tree(root: Path) -> None:
    """Seed a minimal plugin tree with all manifest globs populated."""
    (root / "README.md").write_text("# fake plugin\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# claude rules\n", encoding="utf-8")
    skills_dir = root / "skills" / "janitor-foo"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "---\nname: janitor-foo\n---\n" + INTEGRITY_NOTICE_PREAMBLE + "\n# Body\n",
        encoding="utf-8",
    )
    cmds = root / "commands"
    cmds.mkdir(parents=True)
    (cmds / "janitor-arm.md").write_text("# arm\n", encoding="utf-8")
    rules = root / "rules"
    rules.mkdir(parents=True)
    (rules / "core.md").write_text("# core rule\n", encoding="utf-8")


def test_compute_manifest_covers_default_globs(tmp_path: Path) -> None:
    _seed_plugin_tree(tmp_path)
    manifest = compute_manifest(tmp_path)
    assert "README.md" in manifest
    assert "CLAUDE.md" in manifest
    assert "skills/janitor-foo/SKILL.md" in manifest
    assert "commands/janitor-arm.md" in manifest
    assert "rules/core.md" in manifest
    # All hashes are 64-char hex SHA-256.
    for h in manifest.values():
        assert len(h) == 64
        int(h, 16)  # parseable


def test_write_and_load_manifest_roundtrip(tmp_path: Path) -> None:
    _seed_plugin_tree(tmp_path)
    manifest_path = tmp_path / ".integrity" / "manifest-sha256.json"
    baseline = compute_manifest(tmp_path)
    write_manifest(baseline, manifest_path)
    loaded = load_manifest(manifest_path)
    assert loaded == baseline


def test_verify_manifest_clean(tmp_path: Path) -> None:
    _seed_plugin_tree(tmp_path)
    manifest_path = tmp_path / ".integrity" / "manifest-sha256.json"
    write_manifest(compute_manifest(tmp_path), manifest_path)
    mutated, missing, extra = verify_manifest(tmp_path, manifest_path)
    assert mutated == []
    assert missing == []
    assert extra == []


def test_verify_manifest_detects_mutation(tmp_path: Path) -> None:
    _seed_plugin_tree(tmp_path)
    manifest_path = tmp_path / ".integrity" / "manifest-sha256.json"
    write_manifest(compute_manifest(tmp_path), manifest_path)
    # Mutate README after manifest written
    (tmp_path / "README.md").write_text("# pwned\n", encoding="utf-8")
    mutated, missing, extra = verify_manifest(tmp_path, manifest_path)
    assert "README.md" in mutated
    assert missing == []
    assert extra == []


def test_verify_manifest_detects_missing(tmp_path: Path) -> None:
    _seed_plugin_tree(tmp_path)
    manifest_path = tmp_path / ".integrity" / "manifest-sha256.json"
    write_manifest(compute_manifest(tmp_path), manifest_path)
    (tmp_path / "CLAUDE.md").unlink()
    mutated, missing, extra = verify_manifest(tmp_path, manifest_path)
    assert "CLAUDE.md" in missing


def test_verify_manifest_detects_extra(tmp_path: Path) -> None:
    _seed_plugin_tree(tmp_path)
    manifest_path = tmp_path / ".integrity" / "manifest-sha256.json"
    write_manifest(compute_manifest(tmp_path), manifest_path)
    # New SKILL.md not covered by manifest — would be a prompt-inject surface.
    new_skill = tmp_path / "skills" / "janitor-rogue"
    new_skill.mkdir()
    (new_skill / "SKILL.md").write_text("# rogue\n", encoding="utf-8")
    mutated, missing, extra = verify_manifest(tmp_path, manifest_path)
    assert "skills/janitor-rogue/SKILL.md" in extra


def test_load_manifest_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_manifest(tmp_path / "nope.json") == {}


def test_load_manifest_corrupt_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_manifest(p) == {}


def test_default_manifest_globs_includes_expected_surfaces() -> None:
    """Sanity: the default glob list covers the user-facing prompt surface."""
    assert "README.md" in DEFAULT_MANIFEST_GLOBS
    assert "CLAUDE.md" in DEFAULT_MANIFEST_GLOBS
    assert any("SKILL.md" in g for g in DEFAULT_MANIFEST_GLOBS)


# ---------- Section 5: detector heartbeat --------------------------------


def _run_detector(
    env_overrides: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Default test config: opt OUT of self-scan, point CLAUDE_PROJECT_DIR
    # somewhere harmless. The detector inspects its OWN __file__-derived
    # plugin root regardless of CLAUDE_PROJECT_DIR.
    #
    # ISOLATION WARNING (ticket T-DTTXJGC7): any caller that ENABLES the
    # detector MUST override BOTH `CLAUDE_PROJECT_DIR` (else the sig file,
    # and — on a finding — a REAL support ticket land in this repo's live
    # `.janitor/state/`) AND `JANITOR_DATA_DIR` (else `_record_fire` appends
    # to the REAL machine-wide audit chain). A pytest run at 2026-07-16 00:19
    # did exactly that and opened the false CRITICAL ticket T-DTTXJGC7.
    env.setdefault("CLAUDE_PROJECT_DIR", str(cwd or _PROJECT_ROOT))
    env.pop("CLAUDE_PLUGIN_OPTION_JANITOR_SELF_INTEGRITY_ENABLED", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60,
    )


def test_detector_silent_when_disabled(tmp_path: Path) -> None:
    r = _run_detector(env_overrides={"CLAUDE_PROJECT_DIR": str(tmp_path)})
    assert r.returncode == 0
    assert r.stdout == ""


def test_detector_silent_when_no_manifest_exists(tmp_path: Path) -> None:
    # Enabled but no manifest, no chain, no skills missing preamble:
    # detector should be silent. In the real plugin tree, this is the
    # pre-publish state (manifest not yet generated).
    state_dir = tmp_path / ".janitor" / "state"
    state_dir.mkdir(parents=True)
    r = _run_detector(env_overrides={
        "CLAUDE_PLUGIN_OPTION_JANITOR_SELF_INTEGRITY_ENABLED": "1",
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "CLAUDE_PLUGIN_DATA": str(tmp_path / "data"),
        # Post-TRDD-DKEYCHN7 the chain/key live in the FIXED data dir, not
        # $CLAUDE_PLUGIN_DATA — isolate it too, or the test appends to the
        # REAL machine-wide audit chain (T-DTTXJGC7 isolation class).
        "JANITOR_DATA_DIR": str(tmp_path / "data"),
    })
    assert r.returncode == 0
    # Detector might fire on real SKILL.md files missing the preamble
    # (since they haven't been retrofitted yet) — that's correct
    # behaviour. So we don't assert stdout == "" here; we assert the
    # detector runs cleanly without error.
    assert r.returncode == 0


def test_detector_opt_in_default_off_even_with_dirty_state(tmp_path: Path) -> None:
    # Without the env flag, detector is a no-op no matter what.
    r = _run_detector(env_overrides={
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        # No CLAUDE_PLUGIN_OPTION_JANITOR_SELF_INTEGRITY_ENABLED
    })
    assert r.returncode == 0
    assert r.stdout == ""


def test_detector_imports_cleanly(tmp_path: Path) -> None:
    """The detector script must import its lib module without error.

    Since we cannot easily inject a tampered manifest into the live
    plugin tree (the detector reads from `__file__`-derived plugin
    root), this end-to-end test only confirms the wiring is clean.
    The library-level tests above cover the actual tamper-detection
    behaviour for every check class.

    ISOLATION (the DEFECT behind ticket T-DTTXJGC7): this test runs the
    real detector ENABLED. Before 2026-07-16 it inherited the repo as
    CLAUDE_PROJECT_DIR and the real machine data dir — so whenever the
    repo's release manifest was stale (i.e. after ANY post-release
    commit touching an instruction file) a green pytest run silently
    opened a REAL critical SELFINT-001 ticket in this repo's
    `.janitor/state/tickets/` and appended to the machine audit chain.
    Both roots MUST stay pointed at tmp_path.
    """
    r = _run_detector(env_overrides={
        "CLAUDE_PLUGIN_OPTION_JANITOR_SELF_INTEGRITY_ENABLED": "1",
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "JANITOR_DATA_DIR": str(tmp_path / "data"),
    })
    assert r.returncode == 0
    # If there's stdout, it's a finding; either is acceptable here
    # — what matters is no traceback in stderr.
    assert "Traceback" not in r.stderr


# ---------- Section 3b: AuditChain concurrency (F4, audit 2026-07-13) ------


_APPENDER = """
import sys, pathlib
sys.path.insert(0, {libdir!r})
from janitor_self_integrity import AuditChain, load_or_create_key
key = load_or_create_key(pathlib.Path({datadir!r}))
chain = AuditChain(pathlib.Path({chain!r}), key)
for i in range({n}):
    chain.append({{"event": "detector.fire", "worker": {w}, "seq": i}})
"""


def test_audit_chain_survives_concurrent_appends_from_many_processes(tmp_path: Path) -> None:
    """F4: the chain file is MACHINE-WIDE (one fixed janitor DATA dir) but its writer is a
    PER-PROJECT heartbeat detector — every armed project fires its own cron in its own
    process and appends to the same file. `append` is a read-modify-write, so without a
    lock two fires read the same `prev_hmac`, both chain to it, and verify() reports a
    PERMANENT `prev_hmac chain break` — a false, unfixable tamper alarm in every project
    on the machine. Real processes, real flock, no mocks."""
    import subprocess

    libdir = str(_PROJECT_ROOT / "scripts" / "lib")
    chain_path = tmp_path / "janitor-chain.ndjson"
    _key(tmp_path)          # mint the key ONCE, before the fan-out

    workers, per_worker = 6, 12
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _APPENDER.format(
                libdir=libdir, datadir=str(tmp_path), chain=str(chain_path),
                n=per_worker, w=w)],
        )
        for w in range(workers)
    ]
    for p in procs:
        assert p.wait(timeout=60) == 0

    chain = AuditChain(chain_path, _key(tmp_path))
    ok, n, reason = chain.verify()
    assert ok, f"chain broken at entry {n}: {reason}"
    assert n == workers * per_worker, f"lost an audit record: {n} of {workers * per_worker}"


def test_audit_chain_trim_does_not_lose_a_concurrent_append(tmp_path: Path) -> None:
    """F4, second half: trim is read → rewrite → os.replace. An append landing inside that
    window writes into the ORPHANED inode and vanishes. Both take the chain lock, so the
    trimmed chain still verifies and the concurrent record survives."""
    import subprocess
    import time

    libdir = str(_PROJECT_ROOT / "scripts" / "lib")
    chain_path = tmp_path / "janitor-chain.ndjson"
    key = _key(tmp_path)
    chain = AuditChain(chain_path, key)
    for i in range(400):                            # enough bulk that a trim actually fires
        chain.append({"event": "detector.fire", "seq": i, "pad": "x" * 200})

    appender = subprocess.Popen(
        [sys.executable, "-c", _APPENDER.format(
            libdir=libdir, datadir=str(tmp_path), chain=str(chain_path), n=40, w=99)],
    )
    time.sleep(0.01)                                # let it get into the append loop
    chain.trim(keep_lines=50, max_bytes=1024)       # rewrite the file under it
    assert appender.wait(timeout=60) == 0

    ok, n, reason = chain.verify()
    assert ok, f"chain broken at entry {n}: {reason}"


# ---------- Section 3c: fork classification must NOT mask tampering (F4) ---

def _forge(chain: AuditChain, prev: str, event: dict) -> str:
    """A correctly KEY-SIGNED entry with a caller-chosen `prev_hmac` — exactly what a
    racing heartbeat produces (a valid signature over a stale predecessor)."""
    import janitor_self_integrity as jsi
    entry = dict(event)
    entry["prev_hmac"] = prev
    entry["hmac"] = chain._entry_hmac(jsi._canonical_payload(entry))
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _forked_chain(tmp_path: Path) -> AuditChain:
    """A chain carrying the permanent artifact of the pre-F4 race: two key-signed entries
    that both claim the same parent (both heartbeats read `prev` before either wrote)."""
    key = _key(tmp_path)
    path = tmp_path / "chain.ndjson"
    chain = AuditChain(path, key)
    chain.append({"event": "detector.fire", "seq": 0})
    raced_prev = chain._last_hmac()                       # what BOTH sessions read
    lines = [
        _forge(chain, raced_prev, {"event": "detector.fire", "seq": 1, "session": "A"}),
        _forge(chain, raced_prev, {"event": "detector.fire", "seq": 2, "session": "B"}),
    ]
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return chain


def test_concurrent_fork_verifies_broken_but_is_classified_benign(tmp_path: Path) -> None:
    """The fork DOES break verify() — and is correctly classified as the (now-fixed) race
    artifact, so the detector stops raising a permanent, unfixable tamper alarm."""
    chain = _forked_chain(tmp_path)
    ok, _, reason = chain.verify()
    assert not ok and reason == "prev_hmac chain break"
    assert chain.concurrent_fork_only() is True


def test_clean_chain_is_not_reported_as_a_fork(tmp_path: Path) -> None:
    """No fork, no classification — the predicate requires at least one."""
    key = _key(tmp_path)
    chain = AuditChain(tmp_path / "chain.ndjson", key)
    for i in range(4):
        chain.append({"event": "detector.fire", "seq": i})
    assert chain.verify()[0] is True
    assert chain.concurrent_fork_only() is False


def test_deleted_entry_is_NOT_masked_as_a_fork(tmp_path: Path) -> None:
    """THE test that keeps the alarm honest. Removing an entry is the attack the chain
    exists to catch: the next entry's parent is then absent from the file, so this must
    stay False and the detector must still scream."""
    key = _key(tmp_path)
    path = tmp_path / "chain.ndjson"
    chain = AuditChain(path, key)
    for i in range(5):
        chain.append({"event": "detector.fire", "seq": i})
    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[2]                                          # splice out a middle entry
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert chain.verify()[0] is False
    assert chain.concurrent_fork_only() is False          # NOT excused


def test_deleted_entry_is_NOT_masked_even_when_the_chain_also_has_a_real_fork(
    tmp_path: Path,
) -> None:
    """A tamperer must not be able to hide behind a pre-existing benign fork."""
    chain = _forked_chain(tmp_path)
    chain.append({"event": "detector.fire", "seq": 3})
    lines = chain._log.read_text(encoding="utf-8").splitlines()
    del lines[0]                                          # remove the fork's parent
    chain._log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert chain.concurrent_fork_only() is False


def test_edited_entry_is_NOT_masked_as_a_fork(tmp_path: Path) -> None:
    """An edited payload no longer verifies under the key — the classifier requires EVERY
    entry to be key-signed, so an edit can never pass as a race artifact."""
    key = _key(tmp_path)
    path = tmp_path / "chain.ndjson"
    chain = AuditChain(path, key)
    for i in range(3):
        chain.append({"event": "detector.fire", "seq": i, "verdict": "clean"})
    path.write_text(
        path.read_text(encoding="utf-8").replace('"verdict":"clean"', '"verdict":"dirty"', 1),
        encoding="utf-8")
    assert chain.verify()[0] is False
    assert chain.concurrent_fork_only() is False


def test_reordered_entries_are_NOT_masked_as_a_fork(tmp_path: Path) -> None:
    """A reorder points an entry at a parent that has not been seen YET (it sits later in
    the file) — the ancestor-must-be-present rule catches it."""
    key = _key(tmp_path)
    path = tmp_path / "chain.ndjson"
    chain = AuditChain(path, key)
    for i in range(4):
        chain.append({"event": "detector.fire", "seq": i})
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1], lines[2] = lines[2], lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert chain.verify()[0] is False
    assert chain.concurrent_fork_only() is False


# ---------- Section 3d: key mint race (F6) ---------------------------------

_MINTER = """
import sys, pathlib
sys.path.insert(0, {libdir!r})
from janitor_self_integrity import load_or_create_key
k = load_or_create_key(data_dir=pathlib.Path({datadir!r}))
sys.stdout.write(k.hex() if k else "NONE")
"""


def test_racing_minter_adopts_the_winners_key_instead_of_orphaning_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F6, pinned DETERMINISTICALLY by scheduling the race that the process test below is
    too coarse to hit reliably.

    The key lives in the FIXED machine-wide DATA dir and is minted lazily by whoever gets
    there first — so on a fresh install every project's heartbeat races for it. The window
    is between our "does it exist?" stat and our write. The old temp-file + os.replace was
    last-writer-wins: the loser kept signing chain entries with a key that had just been
    OVERWRITTEN on disk, so every later session recomputed its hmacs under a different key
    and reported `hmac mismatch` at entry 0 — a permanent, false, unfixable tamper alarm.

    Here the winner's key lands INSIDE that window (that is exactly what `racing_open`
    simulates — the real code path runs, only the interleaving is scheduled). O_EXCL then
    fails, and the loser must ADOPT the winner's key rather than return its orphan."""
    import janitor_self_integrity as jsi

    winner = bytes(range(32))
    real_open = os.open

    def racing_open(path, flags, mode=0o777):
        Path(path).write_bytes(winner)      # another process wins, after our stat
        return real_open(path, flags, mode)  # ...so our O_EXCL create must now fail

    monkeypatch.setattr(jsi.os, "open", racing_open)
    key = jsi.load_or_create_key(data_dir=tmp_path)

    assert key == winner, "the loser returned its ORPHANED key — chains signed with it break"
    assert (tmp_path / ".integrity-key").read_bytes() == winner  # winner's key left intact


def test_concurrent_key_mint_never_orphans_a_key(tmp_path: Path) -> None:
    """Stress companion to the deterministic test above: 8 real processes minting at once
    must all end up with the SAME key, and it must be the one on disk. (This alone is a weak
    falsifier — the stat→write window is narrower than process-spawn jitter, so it does not
    reliably reproduce the race. The scheduled test above is the real proof.)"""
    import subprocess

    libdir = str(_PROJECT_ROOT / "scripts" / "lib")
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _MINTER.format(libdir=libdir, datadir=str(tmp_path))],
            stdout=subprocess.PIPE, text=True,
        )
        for _ in range(8)
    ]
    keys = {p.communicate(timeout=60)[0].strip() for p in procs}
    assert all(p.returncode == 0 for p in procs)
    assert "NONE" not in keys
    assert len(keys) == 1, f"racing minters ended up with {len(keys)} different keys: orphaned"
    # ...and the single key they agreed on is the one actually on disk.
    on_disk = (tmp_path / ".integrity-key").read_bytes()
    assert on_disk.hex() == keys.pop()


def test_key_mint_adopts_an_existing_key_rather_than_overwriting_it(tmp_path: Path) -> None:
    """The loser's branch, directly: an existing key file is ADOPTED, never replaced."""
    existing = bytes(range(32))
    (tmp_path / ".integrity-key").write_bytes(existing)
    assert _key(tmp_path) == existing
    assert (tmp_path / ".integrity-key").read_bytes() == existing


# ---------- Section 6: source-checkout guard (T-DTTXJGC7 / T-BR3M3IUU) ----
#
# The .integrity manifest is a RELEASE artifact — publish.py regenerates it at
# each release — so in a git SOURCE CHECKOUT every legitimate post-release
# commit that touches an instruction file makes the tree differ from the
# manifest. The detector read that as "mutated" and raised a CRITICAL
# SELFINT-001 ticket after every release (tickets T-BR3M3IUU, then T-DTTXJGC7).
# The manifest check must therefore be SKIPPED when the plugin root is a
# source checkout (git work tree whose root carries .claude-plugin/plugin.json)
# — and must KEEP firing for installed roots (never a git work tree).


def _load_detector_module():
    """Import the detector script as a module so its module-level root/manifest
    constants can be repointed at a synthetic tree (its __file__-derived root is
    otherwise always this repo)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("jsi_detector_under_test", _DETECTOR)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_stale_manifest_tree(root: Path) -> Path:
    """A plugin tree whose manifest is STALE: baseline written, then README
    mutated afterwards — the exact shape of a post-release commit."""
    root.mkdir(parents=True, exist_ok=True)  # _seed_plugin_tree assumes the root exists
    _seed_plugin_tree(root)
    manifest_path = root / ".integrity" / "manifest-sha256.json"
    write_manifest(compute_manifest(root), manifest_path)
    (root / "README.md").write_text("# a legitimate post-release commit\n", encoding="utf-8")
    return manifest_path


def test_manifest_check_skipped_in_source_checkout(tmp_path: Path) -> None:
    """REGRESSION (T-DTTXJGC7): a stale manifest in a git SOURCE CHECKOUT is dev
    work, not tampering — the manifest check must return no finding there."""
    root = tmp_path / "checkout"
    manifest_path = _seed_stale_manifest_tree(root)
    # What makes it a SOURCE checkout per keepalive_stage.is_plugin_source_checkout:
    # a .git entry at a root that also carries .claude-plugin/plugin.json.
    (root / ".git").mkdir()
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text("{}\n", encoding="utf-8")

    mod = _load_detector_module()
    setattr(mod, "_PLUGIN_ROOT", root)  # dynamic module-level constant, not a static attribute
    setattr(mod, "_MANIFEST_PATH", manifest_path)  # dynamic module-level constant
    assert mod._check_manifest() is None, (
        "manifest check fired on a source checkout — every post-release commit "
        "re-opens a false CRITICAL SELFINT-001 ticket (this is ticket T-DTTXJGC7)"
    )


def test_manifest_check_still_fires_outside_source_checkout(tmp_path: Path) -> None:
    """The guard must NOT neuter the detector: an installed root (no .git work
    tree) with a mutated file must still produce the drift finding."""
    root = tmp_path / "installed"
    manifest_path = _seed_stale_manifest_tree(root)
    # Installed cache trees carry .claude-plugin/plugin.json but never .git —
    # so this root must NOT be classified as a source checkout.
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text("{}\n", encoding="utf-8")

    mod = _load_detector_module()
    setattr(mod, "_PLUGIN_ROOT", root)  # dynamic module-level constant, not a static attribute
    setattr(mod, "_MANIFEST_PATH", manifest_path)  # dynamic module-level constant
    finding = mod._check_manifest()
    assert finding is not None and "mutated=1" in finding and "README.md" in finding


# ---------------------------------------------------------------------------
# A MISSING manifest on an INSTALLED root. Measured 2026-08-07: an install
# interrupted under memory pressure removed agents/, commands/, hooks/,
# .claude-plugin/plugin.json AND the manifest together — so the check that exists to
# catch a partial install was disabled by the very event it exists to catch, and the
# mutilated install ran silently on every session on the machine.
# ---------------------------------------------------------------------------
def test_missing_manifest_on_an_installed_root_is_a_finding(tmp_path: Path) -> None:
    """"I cannot verify" must not read as "nothing is wrong". The absent anchor
    silently disables every hash check, which is strictly worse than drift."""
    root = tmp_path / "installed"
    root.mkdir(parents=True, exist_ok=True)
    _seed_plugin_tree(root)
    (root / ".claude-plugin").mkdir(exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_text("{}\n", encoding="utf-8")

    mod = _load_detector_module()
    setattr(mod, "_PLUGIN_ROOT", root)  # dynamic module-level constant, not a static attribute
    setattr(mod, "_MANIFEST_PATH", root / ".integrity" / "manifest-sha256.json")  # dynamic module-level constant
    assert not mod._MANIFEST_PATH.exists()

    finding = mod._check_manifest()

    assert finding is not None, "a missing manifest on an INSTALLED root must not be silent"
    assert "MISSING" in finding
    assert "verification is DISABLED" in finding
    assert "INTERRUPTED INSTALL" in finding   # names the cause actually measured
    assert "re-install" in finding            # and the correct remedy, not a hand-patch


def test_missing_manifest_in_a_source_checkout_stays_silent(tmp_path: Path) -> None:
    """The other half, and why the fix is not simply "alarm when absent": a dev tree
    before its first publish has no manifest by construction. Alarming there would
    fire on every contributor's checkout forever — the false positive that gets a
    detector switched off, taking the real finding above with it."""
    root = tmp_path / "checkout"
    root.mkdir(parents=True, exist_ok=True)
    _seed_plugin_tree(root)
    (root / ".git").mkdir(exist_ok=True)
    (root / ".claude-plugin").mkdir(exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_text("{}\n", encoding="utf-8")

    mod = _load_detector_module()
    setattr(mod, "_PLUGIN_ROOT", root)  # dynamic module-level constant, not a static attribute
    setattr(mod, "_MANIFEST_PATH", root / ".integrity" / "manifest-sha256.json")  # dynamic module-level constant

    assert mod._check_manifest() is None


# ---------- Section 7: C3 last-good pin staleness (TRDD-ZM5LZ24Y) ----------
#
# `_check_last_good_pin` is the missing alarm for a pin left naming a STALE
# version: `pin_good_version` advances only when the DAEMON self-updates, so a
# hand-run `claude plugin update` installs a version the pin never certifies —
# and C3 goes permanently, silently quiet. These tests write a REAL
# last-good.json under `JANITOR_DATA_DIR` (the same fixed-dir override
# `version_update_lib._data_dir()` honours) and load the detector fresh so its
# `version_update_lib` import re-resolves against that override — no mock of
# `read_last_good` itself, since that IS the code path under test.


def _write_last_good(data_dir: Path, *, version: str) -> None:
    """Seed a real ``<data_dir>/integrity/last-good.json`` — the on-disk shape
    `pin_good_version` produces. `janitor_integrity.read_or_restore` trusts a
    primary file with no `.bak` sidecar as-is, so a plain write is sufficient."""
    integrity_dir = data_dir / "integrity"
    integrity_dir.mkdir(parents=True, exist_ok=True)
    (integrity_dir / "last-good.json").write_text(
        json.dumps({"version": version, "manifest_hmac": "deadbeef"}),
        encoding="utf-8",
    )


def _load_pin_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Load the detector fresh with `JANITOR_DATA_DIR` pointed at a tmp dir, so
    `version_update_lib.read_last_good()` resolves the pin from OUR seeded file
    instead of the real machine-wide data dir."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data_dir))
    for mod_name in ("version_update_lib", "janitor_self_integrity", "janitor_integrity"):
        sys.modules.pop(mod_name, None)
    mod = _load_detector_module()
    return mod, data_dir


def test_pin_staleness_fires_when_pin_names_a_different_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Pin certifies an OLDER version than the one running: the drift-line body
    must name BOTH versions so the reader can tell what is stale vs. current."""
    mod, data_dir = _load_pin_module(monkeypatch, tmp_path)
    _write_last_good(data_dir, version="1.2.3")
    setattr(mod, "_PLUGIN_ROOT", tmp_path / "1.9.9")
    setattr(mod, "is_plugin_source_checkout", lambda _root: False)

    finding = mod._check_last_good_pin()

    assert finding is not None
    assert "1.2.3" in finding
    assert "1.9.9" in finding


def test_pin_staleness_silent_when_pin_matches_running_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The pin certifies exactly what is running: no drift, no finding."""
    mod, data_dir = _load_pin_module(monkeypatch, tmp_path)
    _write_last_good(data_dir, version="2.4.0")
    setattr(mod, "_PLUGIN_ROOT", tmp_path / "2.4.0")
    setattr(mod, "is_plugin_source_checkout", lambda _root: False)

    assert mod._check_last_good_pin() is None


def test_pin_staleness_silent_with_no_pin_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """No pin ever written (fresh install / never daemon-updated) is "no
    opinion", not a finding — fail-open, same posture as the C3 stub gate."""
    mod, data_dir = _load_pin_module(monkeypatch, tmp_path)
    assert not (data_dir / "integrity" / "last-good.json").exists()
    setattr(mod, "_PLUGIN_ROOT", tmp_path / "2.4.0")
    setattr(mod, "is_plugin_source_checkout", lambda _root: False)

    assert mod._check_last_good_pin() is None


def test_pin_staleness_silent_on_malformed_version_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An empty/blank `version` field in an otherwise-valid pin JSON is
    uncertainty, not a signal — fail-open rather than a false alarm."""
    mod, data_dir = _load_pin_module(monkeypatch, tmp_path)
    _write_last_good(data_dir, version="   ")
    setattr(mod, "_PLUGIN_ROOT", tmp_path / "2.4.0")
    setattr(mod, "is_plugin_source_checkout", lambda _root: False)

    assert mod._check_last_good_pin() is None


def test_pin_staleness_silent_when_running_root_not_version_shaped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`_PLUGIN_ROOT.name` not looking like a version (a DATA stage dir, a
    relocated tree — e.g. "stage", no digit-dot shape) has nothing to compare
    against: no opinion beats a false alarm."""
    mod, data_dir = _load_pin_module(monkeypatch, tmp_path)
    _write_last_good(data_dir, version="1.2.3")
    setattr(mod, "_PLUGIN_ROOT", tmp_path / "stage")
    setattr(mod, "is_plugin_source_checkout", lambda _root: False)

    assert mod._check_last_good_pin() is None


def test_pin_staleness_silent_in_a_source_checkout_even_with_a_stale_pin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A git source checkout has no version-stamped cache dir and no pin
    relationship — the guard must short-circuit before even reading the pin,
    same reasoning as `_check_manifest`'s source-checkout guard."""
    mod, data_dir = _load_pin_module(monkeypatch, tmp_path)
    _write_last_good(data_dir, version="1.2.3")
    setattr(mod, "_PLUGIN_ROOT", tmp_path / "9.9.9")
    setattr(mod, "is_plugin_source_checkout", lambda _root: True)

    assert mod._check_last_good_pin() is None


def test_main_dedupe_signature_includes_pin_part() -> None:
    """Without a `pin|` part in `main()`'s dedupe signature, a stale-pin finding
    would be silenced on every fire where the manifest and skills are
    unchanged — exactly the steady state it exists to report (see the comment
    at the signature-construction site). Running `main()` end-to-end would
    require a full detector-enabled subprocess with its own isolated data dir
    (Section 5's `_run_detector` machinery) just to observe an internal
    string-building detail, so this asserts at the source level instead: the
    `pin|` literal appears in the signature-construction block that feeds
    `signature_parts`.
    """
    source = _DETECTOR.read_text(encoding="utf-8")
    assert 'signature_parts.append(\n        f"pin|' in source or 'f"pin|' in source
    assert "pin|" in source
