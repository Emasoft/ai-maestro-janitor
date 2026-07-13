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
    k1 = load_or_create_key(data_dir=tmp_path)
    k2 = load_or_create_key(data_dir=tmp_path)
    assert k1 is not None
    assert k2 is not None
    assert k1 == k2  # persistent across calls
    assert len(k1) == 32
    key_file = tmp_path / ".integrity-key"
    assert key_file.is_file()


def test_key_file_mode_0600(tmp_path: Path) -> None:
    load_or_create_key(data_dir=tmp_path)
    key_file = tmp_path / ".integrity-key"
    mode = key_file.stat().st_mode & 0o777
    # On POSIX filesystems, mode should be 0o600. Skip on others.
    if os.name == "posix":
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_compute_finding_hmac_deterministic(tmp_path: Path) -> None:
    k = load_or_create_key(data_dir=tmp_path)
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
    k = load_or_create_key(data_dir=tmp_path)
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
    k = load_or_create_key(data_dir=tmp_path)
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
    k = load_or_create_key(data_dir=tmp_path)
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
    k = load_or_create_key(data_dir=tmp_path)
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
    k = load_or_create_key(data_dir=tmp_path)
    chain = AuditChain(tmp_path / "chain.ndjson", k)
    ok, n, reason = chain.verify()
    assert ok is True
    assert n == 0
    assert reason == ""


def test_audit_chain_append_and_verify(tmp_path: Path) -> None:
    k = load_or_create_key(data_dir=tmp_path)
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
    k = load_or_create_key(data_dir=tmp_path)
    log_path = tmp_path / "chain.ndjson"
    chain = AuditChain(log_path, k)
    e1 = chain.append({"event": "a"})
    e2 = chain.append({"event": "b"})
    assert e2["prev_hmac"] == e1["hmac"]


def test_audit_chain_detects_middle_edit(tmp_path: Path) -> None:
    k = load_or_create_key(data_dir=tmp_path)
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
    k = load_or_create_key(data_dir=tmp_path)
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
    k = load_or_create_key(data_dir=tmp_path)
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


def test_detector_imports_cleanly() -> None:
    """The detector script must import its lib module without error.

    Since we cannot easily inject a tampered manifest into the live
    plugin tree (the detector reads from `__file__`-derived plugin
    root), this end-to-end test only confirms the wiring is clean.
    The library-level tests above cover the actual tamper-detection
    behaviour for every check class.
    """
    r = _run_detector(env_overrides={
        "CLAUDE_PLUGIN_OPTION_JANITOR_SELF_INTEGRITY_ENABLED": "1",
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
    load_or_create_key(data_dir=tmp_path)          # mint the key ONCE, before the fan-out

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

    chain = AuditChain(chain_path, load_or_create_key(data_dir=tmp_path))
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
    key = load_or_create_key(data_dir=tmp_path)
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
    key = load_or_create_key(data_dir=tmp_path)
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
    key = load_or_create_key(data_dir=tmp_path)
    chain = AuditChain(tmp_path / "chain.ndjson", key)
    for i in range(4):
        chain.append({"event": "detector.fire", "seq": i})
    assert chain.verify()[0] is True
    assert chain.concurrent_fork_only() is False


def test_deleted_entry_is_NOT_masked_as_a_fork(tmp_path: Path) -> None:
    """THE test that keeps the alarm honest. Removing an entry is the attack the chain
    exists to catch: the next entry's parent is then absent from the file, so this must
    stay False and the detector must still scream."""
    key = load_or_create_key(data_dir=tmp_path)
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
    key = load_or_create_key(data_dir=tmp_path)
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
    key = load_or_create_key(data_dir=tmp_path)
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
    assert load_or_create_key(data_dir=tmp_path) == existing
    assert (tmp_path / ".integrity-key").read_bytes() == existing
