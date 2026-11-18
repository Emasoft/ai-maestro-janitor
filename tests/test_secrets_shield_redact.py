"""Real-bun, real-git tests of the secrets-shield plain-file redact (TRDD-BAQB9SYO increment 3, step 3a-2).

No mock: every test runs `scripts/shield_scan/scan.ts --redact` under real bun on a fixture tree built in tmp_path, with real git
repos, real worker processes, the real shield core and a real SQLite vault under tmp_path (SECRETS_SHIELD_VAULT_DIR is set in
`Box.env`, so no test can write the real vault). The vault is read back through a small `bun -e` call to vault.ts (restore.ts is
step 3a-4). Every fake credential is generated at call time by `_fake_secrets`, so no contiguous credential literal sits in this
file (see tests/test_secret_fixture_hygiene.py). The scanner is run with `--min-age-minutes 0` unless the test is about recency.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

import pytest
from _fake_secrets import secret
from _shield_redact_box import AT, MARKER_RE, REDACT, SHIELD, TOKEN, TOKEN2, VAULT, Box, read_text

# The suite denies every real binary by default (tests/sandbox_guard.py); this file exists to run the REAL bun and the REAL git, so it opts in.
pytestmark = pytest.mark.real_subprocess("bun", "git")


@pytest.fixture
def box(tmp_path: Path) -> Box:
    """A fresh Box in tmp_path."""
    return Box(tmp_path)


def test_redact_then_restore_is_byte_identical(box: Box) -> None:
    """A file with a token, a CRLF file with a byte order mark and a mode of 0640 are redacted, restore from the vault gives each back byte for byte, the mode stays, no temp file is left and no value is in any output."""
    original_a = f"one\nk = {TOKEN}\nend\n"
    original_b = "﻿a\r\nkey = " + TOKEN2 + "\r\nz\r\n"
    a = box.put(box.root / "a.txt", original_a)
    b = box.put(box.root / "sub" / "b.txt", original_b)
    a.chmod(0o640)
    result = box.run()
    assert result.code == 0, result.stderr
    summary = result.summary
    assert summary["files_redacted"] == 2 and summary["values_vaulted"] == 2 and summary["findings_not_redacted"] == 0 and summary["redact"] is True
    # WHY the fields are asserted: a --redact run reports that the re-scan ran and how many residual hits it found.
    assert summary["residual_check"] == "run" and summary["residual"] == 0 and summary["complete"] is True
    for path, original in ((a, original_a), (b, original_b)):
        text = read_text(path)
        assert TOKEN not in text and TOKEN2 not in text and "REDACTED-BY-SECRET-SHIELD. Type: github-token. ID: " in text
        assert box.restore(text).encode("utf-8") == original.encode("utf-8")
    assert stat.S_IMODE(a.stat().st_mode) == 0o640
    assert sorted(p.name for p in box.root.rglob("*") if p.is_file()) == ["a.txt", "b.txt"]
    assert TOKEN not in result.streams() and TOKEN2 not in result.streams()
    assert {row["origin"] for row in box.vault_rows()} == {str(a), str(b)}


def test_same_value_twice_is_one_uuid_and_in_two_files_two_uuids(box: Box) -> None:
    """The same token twice in one file gets one uuid; the same token in a second file gets another; the vault holds two rows."""
    a = box.put(box.root / "a.txt", f"x = {TOKEN}\ny = {TOKEN}\n")
    b = box.put(box.root / "b.txt", f"z = {TOKEN}\n")
    result = box.run()
    assert result.code == 0, result.stderr
    in_a = [m.group(2) for m in MARKER_RE.finditer(read_text(a))]
    in_b = [m.group(2) for m in MARKER_RE.finditer(read_text(b))]
    assert len(in_a) == 2 and in_a[0] == in_a[1] and len(in_b) == 1 and in_a[0] != in_b[0]
    assert len(box.vault_rows()) == 2
    assert result.summary["values_vaulted"] == 2


def test_second_run_changes_nothing(box: Box) -> None:
    """A second run over a redacted tree changes no file and no vault row, finds nothing and exits 0."""
    a = box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    assert box.run().code == 0
    after_first = a.read_bytes()
    rows = box.vault_rows()
    second = box.run()
    assert second.code == 0 and second.summary["findings"] == 0 and second.summary["files_redacted"] == 0
    assert a.read_bytes() == after_first and box.vault_rows() == rows


def test_marker_already_in_the_file_and_a_new_copy_of_its_value_share_one_uuid(box: Box) -> None:
    """A redacted file that gets a new raw copy of the same value is redacted again with the same uuid; the old marker is kept and restore gives back the whole file."""
    a = box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    assert box.run().code == 0
    redacted = read_text(a)
    box.put(a, redacted + f"other = {TOKEN}\n")
    result = box.run()
    assert result.code == 0 and result.summary["files_redacted"] == 1, result.stderr
    ids = [m.group(2) for m in MARKER_RE.finditer(read_text(a))]
    assert len(ids) == 2 and ids[0] == ids[1]
    assert box.restore(read_text(a)) == f"k = {TOKEN}\nother = {TOKEN}\n"


def test_gitignored_env_is_untouched_by_default_and_redacted_with_all(box: Box) -> None:
    """A gitignored .env with a token is not read by default (untouched), and with --all it is redacted."""
    box.put(box.root / ".gitignore", ".env\n")
    box.put(box.root / "a.txt", "plain\n")
    env_file = box.put(box.root / ".env", f"API = {TOKEN}\n")
    box.repo(box.root, "a.txt", ".gitignore")
    default = box.run()
    assert default.code == 0 and read_text(env_file) == f"API = {TOKEN}\n" and default.summary["gitignored_entries"] == 1
    everything = box.run("--all")
    assert everything.code == 0, everything.stderr
    assert TOKEN not in read_text(env_file) and box.restore(read_text(env_file)) == f"API = {TOKEN}\n"


def test_git_config_token_under_all_is_reported_and_left_unchanged(box: Box) -> None:
    """A token in .git/config is a finding under --all, is never written (git-internal skip), and the run exits 1."""
    box.put(box.root / "a.txt", "plain\n")
    box.repo(box.root, "a.txt")
    config = box.root / ".git" / "config"
    with config.open("a", encoding="utf-8") as handle:
        handle.write(f'[remote "origin"]\n\turl = https://x-access-token:{TOKEN}{AT}github.example/o/r.git\n')
    before = config.read_bytes()
    result = box.run("--all")
    assert result.code == 1, result.stderr
    assert config.read_bytes() == before
    assert (".git/config", "git-internal") in result.skips
    assert result.summary["findings_not_redacted"] > 0 and result.summary["files_redacted"] == 0
    assert TOKEN not in result.streams()


def test_repo_with_a_merge_in_progress_is_untouched_until_the_merge_ends(box: Box) -> None:
    """A tracked file in a repo with MERGE_HEAD is left alone (git-operation, exit 1); once MERGE_HEAD is gone the same file is redacted."""
    a = box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    box.repo(box.root, "a.txt")
    merge_head = box.root / ".git" / "MERGE_HEAD"
    merge_head.write_text(box.git(box.root, "rev-parse", "HEAD"), encoding="utf-8")
    first = box.run()
    assert first.code == 1 and read_text(a) == f"k = {TOKEN}\n"
    assert ("a.txt", "git-operation") in first.skips and first.summary["findings_not_redacted"] == 1
    merge_head.unlink()
    second = box.run()
    assert second.code == 0 and TOKEN not in read_text(a)


def test_recent_file_is_skipped_by_default_and_redacted_once_old(box: Box) -> None:
    """A file modified a moment ago is skipped as recent with the default of 10 minutes (exit 1); with an old mtime the same run redacts it."""
    a = box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    first = box.run(min_age=None)
    assert first.code == 1 and read_text(a) == f"k = {TOKEN}\n"
    assert ("a.txt", "recent") in first.skips and first.summary["findings_not_redacted"] == 1 and first.summary["min_age_minutes"] == 10
    old = time.time() - 3600
    os.utime(a, (old, old))
    second = box.run(min_age=None)
    assert second.code == 0 and TOKEN not in read_text(a)


def test_hardlinked_and_invalid_utf8_files_are_skipped_and_counted(box: Box) -> None:
    """A hardlinked pair and an invalid UTF-8 file are left unchanged, each is a skip record and counted in findings_not_redacted, while a plain file in the same run is redacted; the run exits 1."""
    hard = box.put(box.root / "hard.txt", f"k = {TOKEN}\n")
    link = box.root / "hard2.txt"
    os.link(hard, link)
    bad_bytes = f"k = {TOKEN}\n".encode() + b"\xff\xfe tail\n"
    bad = box.put(box.root / "bad.txt", bad_bytes)
    ok = box.put(box.root / "ok.txt", f"k = {TOKEN2}\n")
    result = box.run()
    assert result.code == 1, result.stderr
    assert hard.read_bytes() == link.read_bytes() == f"k = {TOKEN}\n".encode() and bad.read_bytes() == bad_bytes
    assert sorted(result.skips) == [("bad.txt", "not-utf8"), ("hard.txt", "hardlinked"), ("hard2.txt", "hardlinked")]
    assert result.summary["findings_not_redacted"] == 3 and result.summary["files_redacted"] == 1
    assert TOKEN2 not in read_text(ok)
    assert TOKEN not in result.streams()


def test_unwritable_vault_leaves_the_file_unchanged_and_exits_2(box: Box) -> None:
    """A vault folder made read-only stops the run with exit 2 and a fixed message, the file keeps its bytes and no value is printed."""
    a = box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    box.vault_dir.mkdir()
    box.vault_dir.chmod(0o500)
    try:
        result = box.run()
    finally:
        box.vault_dir.chmod(0o700)
    assert result.code == 2
    assert "vault" in result.stderr and TOKEN not in result.streams()
    assert a.read_bytes() == f"k = {TOKEN}\n".encode()


def test_vault_write_failure_in_a_worker_ends_the_run_with_exit_2_and_keeps_the_file(box: Box) -> None:
    """A vault that opens but refuses every insert (a trigger of its own) makes the worker reply vault-error: exit 2, the fixed vault message, the file unchanged and no temp file left."""
    a = box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    script = (
        f"import {{ openVault }} from {json.dumps(str(VAULT))}; import {{ Database }} from 'bun:sqlite'; await Bun.stdin.text(); openVault().close(); "
        "const db = new Database(process.env.SECRETS_SHIELD_VAULT_DIR + '/vault.db'); "
        "db.exec(\"CREATE TRIGGER no_insert BEFORE INSERT ON secrets BEGIN SELECT RAISE(ABORT, 'blocked'); END\"); db.close(); console.log('null')"
    )
    box.bun_json(script, None)
    result = box.run()
    assert result.code == 2 and "the vault write failed" in result.stderr
    assert a.read_bytes() == f"k = {TOKEN}\n".encode() and [p.name for p in box.root.iterdir()] == ["a.txt"]
    assert TOKEN not in result.streams()


def test_a_competing_row_with_another_uuid_at_the_commit_rolls_back_and_skips_the_file(box: Box) -> None:
    """A row for the same (origin, value) that appears under another uuid after the lookup (a trigger of its own stands in for another writer) makes the commit roll back: the file is unchanged and skipped as vault-conflict, the vault holds 0 rows (the competitor too), the run exits 1 and no value is printed."""
    original = f"k = {TOKEN}\n"
    a = box.put(box.root / "a.txt", original)
    script = (
        f"import {{ openVault }} from {json.dumps(str(VAULT))}; import {{ Database }} from 'bun:sqlite'; await Bun.stdin.text(); openVault().close(); "
        "const db = new Database(process.env.SECRETS_SHIELD_VAULT_DIR + '/vault.db'); "
        "db.exec(\"CREATE TRIGGER rival BEFORE INSERT ON secrets WHEN NEW.uuid <> '00000000-0000-4000-8000-000000000001' BEGIN "
        "INSERT OR IGNORE INTO secrets (uuid, type, origin, value, encoding, first_seen, last_seen, count) VALUES ('00000000-0000-4000-8000-000000000001', NEW.type, NEW.origin, NEW.value, NEW.encoding, 'x', 'x', 1); END\"); "
        "db.close(); console.log('null')"
    )
    box.bun_json(script, None)
    result = box.run()
    assert result.code == 1, result.stderr
    assert result.skips == [("a.txt", "vault-conflict")] and result.summary["skipped"]["vault-conflict"] == 1
    assert a.read_bytes() == original.encode("utf-8") and [p.name for p in box.root.iterdir()] == ["a.txt"]
    assert box.vault_rows() == []
    assert result.summary["files_redacted"] == 0 and result.summary["values_vaulted"] == 0
    assert TOKEN not in result.streams()


def test_a_write_that_fails_after_the_vault_commit_keeps_its_rows_by_design_and_a_later_run_reuses_them(box: Box) -> None:
    """A folder that refuses the temp file makes writeAtomic fail AFTER the vault commit: the file is unchanged and skipped as write-error, and its row REMAINS in the vault by design (the commit comes before the write so that a crash leaves a row with no marker, never a marker with no row); a later run on the same file reuses that row (one row, same uuid in the marker, count 2) instead of adding another."""
    original = f"k = {TOKEN}\n"
    sub = box.root / "sub"
    a = box.put(sub / "a.txt", original)
    sub.chmod(0o500)
    try:
        failed = box.run()
    finally:
        sub.chmod(0o700)
    assert failed.code == 1, failed.stderr
    assert failed.skips == [("sub/a.txt", "write-error")]
    assert a.read_bytes() == original.encode("utf-8")
    rows = box.vault_rows()
    assert len(rows) == 1 and rows[0]["value"] == TOKEN and rows[0]["count"] == 1
    assert TOKEN not in failed.streams()
    again = box.run()
    assert again.code == 0, again.stderr
    after = box.vault_rows()
    assert len(after) == 1 and after[0]["uuid"] == rows[0]["uuid"] and after[0]["count"] == 2
    assert [m.group(2) for m in MARKER_RE.finditer(read_text(a))] == [rows[0]["uuid"]]
    assert box.restore(read_text(a)) == original


def test_a_two_round_redact_bumps_the_vault_count_once_per_run(box: Box) -> None:
    """A file that needs two rounds (two assignments on one line) leaves its rows with count 1: the vault is written once per run, not once per round."""
    a = box.put(box.root / "a.txt", "\"password\":\"abc12345\"password: abc12345\n")
    result = box.run()
    assert result.code == 0 and result.summary["rounds_used_max"] == 2, result.stderr
    rows = box.vault_rows()
    assert rows and all(row["count"] == 1 for row in rows)
    assert "abc12345" not in read_text(a)


def test_home_pass_with_redact_rewrites_home_paths_last_and_they_are_not_restorable(box: Box) -> None:
    """--passes secrets,cards,home with --redact: the token becomes a restorable marker and the home path becomes ~ (not vaulted, so restore gives back the ~); a file whose only hit is a home path is still written; home_rewrites counts the rewrites, findings_not_redacted is 0, and the home findings are reported with the kind home-path."""
    home = str(box.home_dir)
    a = box.put(box.root / "a.txt", f"dir = {home}/proj/x\nk = {TOKEN}\n")
    b = box.put(box.root / "b.txt", f"cfg = {home}/y\n")
    result = box.run("--passes", "secrets,cards,home")
    assert result.code == 0, result.stderr
    assert read_text(b) == "cfg = ~/y\n"
    text = read_text(a)
    assert text.startswith("dir = ~/proj/x\nk = [REDACTED-BY-SECRET-SHIELD. Type: github-token. ID: ") and TOKEN not in text
    assert box.restore(text) == f"dir = ~/proj/x\nk = {TOKEN}\n"
    summary = result.summary
    assert summary["home_rewrites"] == 2 and summary["findings_not_redacted"] == 0 and summary["files_redacted"] == 2 and summary["skipped"]["align-error"] == 0
    assert sorted(r["path"] for r in result.records if r["type"] == "finding" and r["kind"] == "home-path") == ["a.txt", "b.txt"]
    assert len(box.vault_rows()) == 1
    assert TOKEN not in result.streams() and home not in result.streams()


def test_a_home_only_file_skipped_as_recent_adds_nothing_to_findings_not_redacted(box: Box) -> None:
    """A file whose only hit is a home path and that is skipped as recent stays unchanged, the skip is recorded, the home hit is still a finding of kind home-path, and findings_not_redacted is 0 (a home path is not a secret left in the file)."""
    a = box.put(box.root / "a.txt", f"cfg = {box.home_dir}/y\n")
    result = box.run("--passes", "secrets,home", min_age=None)
    assert result.code == 0, result.stderr
    assert read_text(a) == f"cfg = {box.home_dir}/y\n"
    assert ("a.txt", "recent") in result.skips
    assert result.summary["findings_not_redacted"] == 0 and result.summary["files_redacted"] == 0 and result.summary["home_rewrites"] == 0
    assert [(r["kind"], r["count"]) for r in result.records if r["type"] == "finding"] == [("home-path", 1)]


# A text file of about 67 KB: over --max-file-mb 0.01 (10485 bytes), under --max-large-mb 0.1 (104857 bytes).
_FILLER = "lorem ipsum dolor sit amet\n" * 2500


def test_text_over_max_file_mb_is_redacted_through_the_large_lane(box: Box) -> None:
    """With --max-file-mb 0.01 a 67 KB text file is redacted through the large lane (counted in large_lane_files, restore byte-identical) while a small file in the same run goes through the ordinary slots and does not count."""
    original = f"{_FILLER}k = {TOKEN}\n"
    big = box.put(box.root / "big.txt", original)
    small = box.put(box.root / "small.txt", f"k = {TOKEN2}\n")
    result = box.run("--max-file-mb", "0.01")
    assert result.code == 0, result.stderr
    assert result.summary["large_lane_files"] == 1 and result.summary["files_redacted"] == 2 and result.summary["files_not_scanned"] == 0
    assert TOKEN not in read_text(big) and TOKEN2 not in read_text(small)
    assert box.restore(read_text(big)) == original
    assert TOKEN not in result.streams()


def test_text_over_max_large_mb_is_not_scanned_and_makes_the_run_incomplete(box: Box) -> None:
    """A 67 KB text file over --max-large-mb 0.02 is neither scanned nor redacted: a not-scanned-too-large skip record, files_not_scanned 1, complete false, exit 3, the file unchanged; a small file in the same run is still redacted."""
    original = f"{_FILLER}k = {TOKEN}\n"
    big = box.put(box.root / "big.txt", original)
    small = box.put(box.root / "small.txt", f"k = {TOKEN2}\n")
    result = box.run("--max-file-mb", "0.01", "--max-large-mb", "0.02")
    assert result.code == 3, result.stderr
    assert ("big.txt", "not-scanned-too-large") in result.skips
    summary = result.summary
    assert summary["files_not_scanned"] == 1 and summary["complete"] is False and summary["large_lane_files"] == 0 and summary["files_scanned"] == 1
    assert big.read_bytes() == original.encode() and TOKEN2 not in read_text(small)
    assert [r for r in result.records if r["type"] == "finding" and r["path"] == "big.txt"] == []


def test_an_over_size_binary_file_is_an_ordinary_binary_skip(box: Box) -> None:
    """A 50 KB file with a NUL byte and a token in it, over --max-file-mb 0.01 and also over --max-large-mb 0.02, is counted as a binary skip (no record, not over-size, not a large-lane or not-scanned file) and left unchanged, exit 0."""
    blob = b"\x00" + b"x" * 50_000 + TOKEN.encode()
    path = box.put(box.root / "blob.bin", blob)
    for extra in ([], ["--max-large-mb", "0.02"]):
        result = box.run("--max-file-mb", "0.01", *extra)
        assert result.code == 0, result.stderr
        summary = result.summary
        assert summary["skipped"]["binary"] == 1 and summary["skipped"]["over-size"] == 0 and summary["files_not_scanned"] == 0 and summary["large_lane_files"] == 0
        assert result.skips == [] and path.read_bytes() == blob


def test_max_large_mb_below_max_file_mb_exits_2(box: Box) -> None:
    """--max-large-mb smaller than --max-file-mb with --redact exits 2 with fixed text."""
    result = box.run("--max-file-mb", "2", "--max-large-mb", "1")
    assert result.code == 2 and "--max-large-mb must be at least --max-file-mb" in result.stderr


_LANE_DELAY_S = 3.0


def _lane_delay() -> dict[str, str]:
    """The test-only worker hook: every worker sleeps this long, in milliseconds, after its whole-file reply of a file with findings."""
    return {"SHIELD_SCAN_TEST_LOCATE_DELAY_MS": str(int(_LANE_DELAY_S * 1000))}


def test_large_files_run_one_at_a_time_even_with_four_jobs(box: Box) -> None:
    """Two large files that each hold the worker for 3 s (the test hook) take at least 6 s with --jobs 4, because the large lane runs one file at a time; both are redacted."""
    box.put(box.root / "big1.txt", f"{_FILLER}k = {TOKEN}\n")
    box.put(box.root / "big2.txt", f"{_FILLER}k = {TOKEN2}\n")
    started = time.monotonic()
    result = box.run("--max-file-mb", "0.01", "--jobs", "4", env_extra=_lane_delay())
    elapsed = time.monotonic() - started
    print(f"large lane, 2 files, delay {_LANE_DELAY_S} s each, jobs 4: {elapsed:.2f} s")
    assert result.code == 0, result.stderr
    assert result.summary["large_lane_files"] == 2 and result.summary["files_redacted"] == 2
    assert elapsed >= 2 * _LANE_DELAY_S


def test_ordinary_slots_keep_working_while_a_large_file_runs(box: Box) -> None:
    """One large file and three small ones, each held 3 s by the test hook, with --jobs 4: the small ones run in the ordinary slots beside the large lane, so the run takes well under the 12 s of one after another (under 9 s here)."""
    box.put(box.root / "big.txt", f"{_FILLER}k = {TOKEN}\n")
    for index in range(3):
        box.put(box.root / f"s{index}.txt", f"k = {secret('gh' + 'p_', f'lane-{index}', 36)}\n")
    started = time.monotonic()
    result = box.run("--max-file-mb", "0.01", "--jobs", "4", env_extra=_lane_delay())
    elapsed = time.monotonic() - started
    print(f"large lane plus 3 ordinary files, delay {_LANE_DELAY_S} s each, jobs 4: {elapsed:.2f} s")
    assert result.code == 0, result.stderr
    assert result.summary["large_lane_files"] == 1 and result.summary["files_redacted"] == 4
    assert elapsed < 3 * _LANE_DELAY_S


_ALIGN = f"""
import {{ alignStretches, cutMarkers, CORE_MARKER, planRedaction, finalText, restoreCheck }} from {json.dumps(str(REDACT))}
import {{ mark }} from {json.dumps(str(SHIELD.parents[1] / "hooks" / "secret-shield" / "patterns.ts"))}
const input = JSON.parse(await Bun.stdin.text())
const out = {{
  pin: new RegExp('^' + CORE_MARKER + '$').test(mark('github-token')) && mark('github-token') === '[JANITOR-REDACTED:github-token]',
  align: input.align.map(([original, redacted]) => alignStretches(original, redacted)),
  cut: cutMarkers(input.cut),
}}
console.log(JSON.stringify(out))
"""


def test_alignment_recovers_stretches_at_the_edges_next_to_each_other_and_fails_loudly(box: Box) -> None:
    """alignStretches: a secret at the start, at the end, two touching secrets (one stretch), a secret between literals, and an output that cannot be explained gives null; the core marker grammar matches mark()."""
    cases = [
        ["SEC1 tail", "[JANITOR-REDACTED:k] tail"],
        ["head SEC2", "head [JANITOR-REDACTED:k]"],
        ["aSEC3SEC4b", "a[JANITOR-REDACTED:x][JANITOR-REDACTED:y]b"],
        ["a SEC5, SEC6 b", "a [JANITOR-REDACTED:x], [JANITOR-REDACTED:y] b"],
        ["abc", "a[JANITOR-REDACTED:k]x"],
        ["abc", "abd"],
        ["same", "same"],
    ]
    got = box.bun_json(_ALIGN, {"align": cases, "cut": "p [JANITOR-REDACTED:z] q"})
    assert got["pin"] is True
    assert got["align"][0] == [{"value": "SEC1", "kind": "k"}, {"lit": " tail"}]
    assert got["align"][1] == [{"lit": "head "}, {"value": "SEC2", "kind": "k"}]
    assert got["align"][2] == [{"lit": "a"}, {"value": "SEC3SEC4", "kind": "x"}, {"lit": "b"}]
    assert got["align"][3] == [{"lit": "a "}, {"value": "SEC5", "kind": "x"}, {"lit": ", "}, {"value": "SEC6", "kind": "y"}, {"lit": " b"}]
    assert got["align"][4] is None and got["align"][5] is None
    assert got["align"][6] == [{"lit": "same"}]
    assert got["cut"] == [{"seg": "p "}, {"lit": "[JANITOR-REDACTED:z]"}, {"seg": " q"}]


_PLAN = f"""
import {{ planRedaction, finalText, restoreCheck, vaultEntries }} from {json.dumps(str(REDACT))}
const input = JSON.parse(await Bun.stdin.text())
const passes = new Set(['secrets', 'cards'])
const {{ plan, hits }} = planRedaction(input.text, [], passes)
const entries = plan ? vaultEntries(plan) : null
const uuids = plan && entries ? entries.slot.map((i) => input.uuids[i]) : []
const final = plan ? finalText(plan, uuids) : null
const values = new Map(plan && entries ? entries.entries.map((e, i) => [input.uuids[i], e.value]) : [])
console.log(JSON.stringify({{
  hits,
  stretches: plan ? plan.stretches.length : null,
  distinct: entries ? entries.entries.length : null,
  final,
  check: plan && final !== null ? restoreCheck(plan, final, uuids, (u) => values.get(u) ?? null, input.text) : null,
  wrong: plan && final !== null ? restoreCheck(plan, final, uuids, () => 'wrong', input.text) : null,
}}))
"""

_OLD = "[REDACTED-BY-SECRET-SHIELD. Type: github-token. ID: 6f1c2d3e-4a5b-4c6d-8e7f-0a1b2c3d4e5f]"
_NEW_UUID = "11111111-2222-4333-8444-555555555555"


def test_plan_keeps_old_markers_and_the_restore_check_works_by_position(box: Box) -> None:
    """planRedaction leaves a shield marker and a core marker already in the text alone, redacts the raw token beside them, and restoreCheck passes only when the vault values put the original back."""
    text = f"a {_OLD}\nb [JANITOR-REDACTED:github-token]\nc {TOKEN}\n"
    got = box.bun_json(_PLAN, {"text": text, "uuids": [_NEW_UUID]})
    assert got["stretches"] == 1 and got["distinct"] == 1 and got["hits"] == {"github-token": 1}
    assert got["final"] == text.replace(TOKEN, f"[REDACTED-BY-SECRET-SHIELD. Type: github-token. ID: {_NEW_UUID}]")
    assert got["check"] is True and got["wrong"] is False
    nothing = box.bun_json(_PLAN, {"text": f"a {_OLD}\n", "uuids": []})
    assert nothing["hits"] == {} and nothing["stretches"] == 0 and nothing["final"] == f"a {_OLD}\n" and nothing["check"] is True


# A value that propagates() accepts (16 characters with upper case, lower case, digits and punctuation) and that no rule matches bare; the assignment rule fires on it only beside its key.
SWEEP_VALUE = "Zq9!kT3#vR8$mW2x"


def test_a_copy_left_by_the_marker_cut_is_swept_and_shares_the_uuid(box: Box) -> None:
    """A pair "password":"<value>" is redacted, an old shield marker follows, then the bare value (which no rule matches alone): the sweep turns both copies into markers with one uuid, the run exits 0 with no residual, and restore (which also puts back the old marker) gives the file with the old marker replaced by its token."""
    a = box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    assert box.run().code == 0
    old_line = read_text(a)
    assert MARKER_RE.search(old_line) is not None
    original = f'{{"password":"{SWEEP_VALUE}"}}\n{old_line}note {SWEEP_VALUE} end\n'
    box.put(a, original)
    result = box.run()
    assert result.code == 0 and result.summary["residual"] == 0 and result.summary["files_redacted"] == 1, result.stderr
    text = read_text(a)
    assert SWEEP_VALUE not in text
    ids = [m.group(2) for m in MARKER_RE.finditer(text)]
    assert len(ids) == 3
    assert ids[0] == ids[2] and ids[0] != ids[1]
    # Restore puts back every marker, the old one too: its value is the token of the first run.
    assert box.restore(text) == f'{{"password":"{SWEEP_VALUE}"}}\nk = {TOKEN}\nnote {SWEEP_VALUE} end\n'
    assert result.summary["values_vaulted"] == 1
    assert SWEEP_VALUE not in result.streams()


_SWEEP = f"""
import {{ sweepPlan, vaultEntries }} from {json.dumps(str(REDACT))}
const plan = JSON.parse(await Bun.stdin.text())
const swept = sweepPlan(plan)
const entries = vaultEntries(swept)
console.log(JSON.stringify({{ swept, slot: entries.slot, distinct: entries.entries.length }}))
"""


def test_sweep_skips_a_short_value_and_never_splits_a_value_out_of_a_longer_one(box: Box) -> None:
    """sweepPlan: a value under 10 characters is not swept; a longer value is swept first so a shorter one inside it is not split out; a shield marker part is never searched; every copy shares the row of its value."""
    short = {"parts": [{"t": "new", "stretch": 0}, {"t": "lit", "text": " ab1 ab1 "}], "stretches": [{"value": "ab1", "kind": "k"}]}
    got_short = box.bun_json(_SWEEP, short)
    assert got_short["swept"] == short and got_short["distinct"] == 1
    inner = "kT3#vR8$mW2x"
    assert SWEEP_VALUE.endswith(inner) and len(inner) >= 10
    old = f"x{SWEEP_VALUE}x"
    plan = {
        "parts": [{"t": "new", "stretch": 0}, {"t": "lit", "text": f" {SWEEP_VALUE} / {inner} "}, {"t": "new", "stretch": 1}, {"t": "old", "text": old}],
        "stretches": [{"value": inner, "kind": "ki"}, {"value": SWEEP_VALUE, "kind": "kl"}],
    }
    got = box.bun_json(_SWEEP, plan)
    assert got["swept"]["parts"] == [
        {"t": "new", "stretch": 0},
        {"t": "lit", "text": " "},
        {"t": "new", "stretch": 2},
        {"t": "lit", "text": " / "},
        {"t": "new", "stretch": 3},
        {"t": "lit", "text": " "},
        {"t": "new", "stretch": 1},
        {"t": "old", "text": old},
    ]
    assert got["swept"]["stretches"][2:] == [{"value": SWEEP_VALUE, "kind": "kl"}, {"value": inner, "kind": "ki"}]
    assert got["distinct"] == 2 and got["slot"] == [0, 1, 1, 0]


def test_a_residual_hit_is_redacted_by_a_further_round_in_the_same_run(box: Box) -> None:
    """Two assignments on one line: round 1 hides the first pair and the re-scan finds the second, so a second round hides it in the same run: the file is written once, the run exits 0 with no residual record, rounds_used_max is 2, no value is printed, restore gives the original and a second run changes nothing."""
    original = '"password":"abc12345"password: abc12345\n'
    a = box.put(box.root / "a.txt", original)
    first = box.run()
    assert first.code == 0, first.stderr
    assert [r for r in first.records if r["type"] == "residual"] == []
    assert first.summary["residual"] == 0 and first.summary["residual_check"] == "run" and first.summary["files_redacted"] == 1 and first.summary["findings_not_redacted"] == 0
    assert first.summary["rounds_used_max"] == 2
    assert "abc12345" not in read_text(a) and box.restore(read_text(a)) == original
    assert "abc12345" not in first.streams()
    after = a.read_bytes()
    second = box.run()
    assert second.code == 0 and second.summary["files_redacted"] == 0 and second.summary["rounds_used_max"] == 0
    assert a.read_bytes() == after


def test_round_cap_of_one_leaves_a_residual_that_the_run_reports_and_a_run_without_the_cap_redacts(box: Box) -> None:
    """With the test-only cap at 1 round a residual is reported (exit 1), and a run without the cap redacts it (exit 0)."""
    original = '"password":"abc12345"password: abc12345\n'
    a = box.put(box.root / "a.txt", original)
    first = box.run(env_extra={"SHIELD_SCAN_TEST_MAX_ROUNDS": "1"})
    assert first.code == 1, first.stderr
    assert [r for r in first.records if r["type"] == "residual"] == [{"type": "residual", "path": "a.txt", "kind": "assignment", "count": 1}]
    assert first.summary["residual"] == 1 and first.summary["residual_check"] == "run" and first.summary["files_redacted"] == 1
    assert first.summary["findings_not_redacted"] == 0 and first.summary["rounds_used_max"] == 1
    assert MARKER_RE.search(read_text(a)) is not None and box.restore(read_text(a)) == original
    assert "abc12345" not in first.streams()
    second = box.run()
    assert second.code == 0, second.stderr
    assert "abc12345" not in read_text(a) and box.restore(read_text(a)) == original


def test_round_cap_outside_one_to_three_ends_the_run_with_the_file_unchanged_and_no_value_printed(box: Box) -> None:
    """A test-only cap of 7 makes the workers fail to start: exit 2, file unchanged, no value printed; the same file without the cap exits 0."""
    original = f"k = {TOKEN}\n"
    a = box.put(box.root / "a.txt", original)
    result = box.run(env_extra={"SHIELD_SCAN_TEST_MAX_ROUNDS": "7"})
    assert result.code == 2 and "a worker process did not start" in result.stderr
    assert read_text(a) == original
    assert TOKEN not in result.streams()
    assert box.run().code == 0


_RESIDUAL = f"""
import {{ HOME_KIND, residualHits }} from {json.dumps(str(REDACT))}
import {{ redactHome }} from {json.dumps(str(SHIELD.parents[1] / "hooks" / "secret-shield" / "home.ts"))}
const input = JSON.parse(await Bun.stdin.text())
console.log(JSON.stringify({{ residual: residualHits(input.text, [], new Set(['secrets'])), clean: residualHits(input.clean, [], new Set(['secrets'])), homeKind: Object.keys(redactHome('/a/b/x', ['/a/b']).hits), pinned: HOME_KIND }}))
"""


def test_the_re_scan_reports_kinds_and_counts_between_markers_and_the_home_kind_matches_the_core(box: Box) -> None:
    """residualHits (a unit test: no real input makes a run still find something after its 3 rounds) gives only kind and count for a hit between markers and nothing for marker-only text; HOME_KIND equals the kind redactHome gives its hits."""
    got = box.bun_json(_RESIDUAL, {"text": f"a {_OLD}\npassword: abc12345\n", "clean": f"a {_OLD}\nb {_OLD}\n"})
    assert got["residual"] == {"assignment": 1} and got["clean"] == {}
    assert got["homeKind"] == [got["pinned"]]


def test_linked_worktree_with_its_own_merge_head_is_untouched_while_the_main_worktree_is_redacted(box: Box) -> None:
    """A linked worktree whose own git dir holds MERGE_HEAD keeps its file (git-operation skip, counted), while the same file in the main worktree, whose git dir has none, is redacted."""
    main = box.root / "main"
    box.put(main / "a.txt", f"k = {TOKEN}\n")
    box.repo(main, "a.txt")
    linked = box.root / "wt"
    box.git(main, "worktree", "add", "-q", "-b", "wtbranch", str(linked))
    linked_file = linked / "a.txt"
    assert read_text(linked_file) == f"k = {TOKEN}\n"
    git_dir = Path(box.git(linked, "rev-parse", "--absolute-git-dir").strip())
    assert git_dir != main / ".git"
    (git_dir / "MERGE_HEAD").write_text(box.git(linked, "rev-parse", "HEAD"), encoding="utf-8")
    result = box.run()
    assert result.code == 1, result.stderr
    assert read_text(linked_file) == f"k = {TOKEN}\n"
    assert ("wt/a.txt", "git-operation") in result.skips
    assert TOKEN not in read_text(main / "a.txt") and box.restore(read_text(main / "a.txt")) == f"k = {TOKEN}\n"
    assert result.summary["files_redacted"] == 1 and result.summary["findings_not_redacted"] == 1


_GUARD = f"""
import {{ checkWriteTarget }} from {json.dumps(str(SHIELD / "writeguard.ts"))}
const input = JSON.parse(await Bun.stdin.text())
console.log(JSON.stringify(input.map(([path, root]) => checkWriteTarget(path, root))))
"""


def test_write_target_guard_refuses_a_symlink_a_missing_file_a_directory_and_a_path_outside_the_root(box: Box) -> None:
    """checkWriteTarget: a regular file inside the root (also behind a symlinked folder that stays inside) is ok; a symlink to a file outside, a missing path and a folder are not regular; a file outside the root, also behind a symlinked folder, is outside-root."""
    outside = box.put(box.base / "outside" / "f.txt", "x\n")
    inside = box.put(box.root / "inside.txt", "x\n")
    (box.root / "link.txt").symlink_to(outside)
    (box.root / "dirlink").symlink_to(outside.parent, target_is_directory=True)
    real_dir = box.root / "real_dir"
    box.put(real_dir / "x.txt", "x\n")
    (box.root / "alias").symlink_to(real_dir, target_is_directory=True)
    (box.root / "sub").mkdir()
    root = str(box.root)
    cases = [
        [str(inside), root],
        [str(box.root / "alias" / "x.txt"), root],
        [str(box.root / "link.txt"), root],
        [str(box.root / "missing.txt"), root],
        [str(box.root / "sub"), root],
        [str(outside), root],
        [str(box.root / "dirlink" / "f.txt"), root],
    ]
    got = box.bun_json(_GUARD, cases)
    assert got == ["ok", "ok", "not-regular-at-write", "not-regular-at-write", "not-regular-at-write", "outside-root", "outside-root"]
