"""Real-bun tests of restore.ts, the human-only restore of the secrets-shield redact (TRDD-BAQB9SYO increment 3, step 3a-4b).

No mock: every test redacts a fixture tree with the real `scan.ts --redact` and then runs the real `restore.ts` under real bun, on real git repos, with a real SQLite vault under tmp_path (SECRETS_SHIELD_VAULT_DIR is set in `Box.env`, so no test can write the real vault; the one run that unsets it is the guard run of test 7, which must exit before any vault code).
Every fake credential is generated at call time by `_fake_secrets`, so no contiguous credential literal sits in this file (see tests/test_secret_fixture_hygiene.py). The redact runs use `--min-age-minutes 0` (Box.run).
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import transcript_redact as tr
from _shield_redact_box import MARKER_RE, SHIELD, TIMEOUT_S, TOKEN, TOKEN2, VAULT, Box, read_text

# The suite denies every real binary by default (tests/sandbox_guard.py); this file exists to run the REAL bun and the REAL git, so it opts in.
pytestmark = pytest.mark.real_subprocess("bun", "git")

RESTORE = SHIELD / "restore.ts"
GUARD_TEXT = "restore.ts is for a person at a terminal: stdin is not a terminal; agents never run it"
NO_VAULT_TEXT = "no vault: nothing to restore from"
# A text file of about 67 KB: over --max-file-mb 0.01 (10485 bytes) for the redact run, over --max-large-mb 0.02 (20971 bytes) for the restore run.
FILLER = "lorem ipsum dolor sit amet\n" * 2500
UNKNOWN_MARKER = "[REDACTED-BY-SECRET-SHIELD. Type: github-token. ID: 6f1c2d3e-4a5b-4c6d-8e7f-0a1b2c3d4e5f]"


class Restored:
    """The result of one restore run: exit code, both streams and the JSON-line records of stdout."""

    def __init__(self, done: subprocess.CompletedProcess[str]) -> None:
        self.code = done.returncode
        self.stdout = done.stdout
        self.stderr = done.stderr
        self.records: list[dict[str, Any]] = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]

    @property
    def summary(self) -> dict[str, Any]:
        """The last record of stdout."""
        assert self.records[-1]["type"] == "summary"
        return self.records[-1]

    def of(self, kind: str) -> list[dict[str, Any]]:
        """Every record of one type, in output order."""
        return [r for r in self.records if r["type"] == kind]

    def streams(self) -> str:
        """Everything the run wrote that a person could read: stdout and stderr."""
        return self.stdout + self.stderr


def restore_run(box: Box, *args: str, env_extra: dict[str, str] | None = None, env_drop: tuple[str, ...] = (), stdin: str | None = None) -> Restored:
    """Run restore.ts under real bun with the box environment (env_drop names variables to remove); stdin is the given text, or an empty pipe, never a terminal."""
    env = box.env(env_extra)
    for name in env_drop:
        env.pop(name, None)
    done = subprocess.run([tr.resolve_bun(), str(RESTORE), *args], input=stdin or "", capture_output=True, text=True, timeout=TIMEOUT_S, env=env, check=False)
    return Restored(done)


_INSERT = f"""
import {{ openVault }} from {json.dumps(str(VAULT))}
const [origin, value] = JSON.parse(await Bun.stdin.text())
const v = openVault()
const [uuid] = v.lookupOrInsert(origin, [{{ value, type: "github-token", encoding: "raw" }}])
v.close()
console.log(JSON.stringify(uuid))
"""

_GUARD = f"""
import {{ restoreAllowed }} from {json.dumps(str(RESTORE))}
import {{ accountHome }} from {json.dumps(str(VAULT))}
const cases = JSON.parse(await Bun.stdin.text())
console.log(JSON.stringify({{ allowed: cases.map(([set, tty]) => restoreAllowed(set, tty)), home: accountHome() }}))
"""


def vaulted(box: Box, origin: Path, value: str) -> str:
    """Put one row into the box vault, for a file at origin, and return its uuid (the vault is created when missing)."""
    uuid: str = box.bun_json(_INSERT, [str(origin), value])
    return uuid


def marker_of(uuid: str) -> str:
    """The shield marker of a github-token row."""
    return f"[REDACTED-BY-SECRET-SHIELD. Type: github-token. ID: {uuid}]"


@pytest.fixture
def box(tmp_path: Path) -> Box:
    """A fresh Box in tmp_path."""
    return Box(tmp_path)


def test_round_trip_is_byte_identical_and_a_second_restore_changes_nothing(box: Box) -> None:
    """A token file (mode 0640), a CRLF file with a byte order mark and a large-lane file are redacted and restored byte for byte, the mode stays, no temp file is left, no value is in any output, and a second restore exits 0 and touches nothing."""
    original_a = f"one\nk = {TOKEN}\nend\n"
    original_b = "﻿a\r\nkey = " + TOKEN2 + "\r\nz\r\n"
    original_big = f"{FILLER}k = {TOKEN}\n"
    a = box.put(box.root / "a.txt", original_a)
    b = box.put(box.root / "sub" / "b.txt", original_b)
    big = box.put(box.root / "big.txt", original_big)
    a.chmod(0o640)
    redacted = box.run("--max-file-mb", "0.01")
    assert redacted.code == 0, redacted.stderr
    assert redacted.summary["large_lane_files"] == 1
    assert all(MARKER_RE.search(read_text(p)) for p in (a, b, big))
    done = restore_run(box, str(box.root))
    assert done.code == 0, done.stderr
    summary = done.summary
    assert summary["files_with_markers"] == 3 and summary["files_restored"] == 3 and summary["markers_restored"] == 3
    assert summary["markers_left"] == 0 and summary["complete"] is True and summary["skipped"] == {}
    for path, original in ((a, original_a), (b, original_b), (big, original_big)):
        assert path.read_bytes() == original.encode("utf-8")
    assert stat.S_IMODE(a.stat().st_mode) == 0o640
    assert sorted(p.name for p in box.root.rglob("*") if p.is_file()) == ["a.txt", "b.txt", "big.txt"]
    assert TOKEN not in done.streams() and TOKEN2 not in done.streams()
    stamps = {p: p.stat().st_mtime_ns for p in (a, b, big)}
    again = restore_run(box, str(box.root))
    assert again.code == 0 and again.summary["files_with_markers"] == 0 and again.summary["files_restored"] == 0
    assert {p: p.stat().st_mtime_ns for p in (a, b, big)} == stamps


def test_a_copy_of_the_redacted_root_needs_any_origin(box: Box) -> None:
    """A copy of the redacted root elsewhere is left as it is without --any-origin (exit 1, markers reported as moved) and restored byte for byte with it."""
    original = f"k = {TOKEN}\n"
    a = box.put(box.root / "a.txt", original)
    assert box.run().code == 0
    copy = box.base / "copy"
    shutil.copytree(box.root, copy)
    copied = copy / "a.txt"
    redacted_bytes = copied.read_bytes()
    plain = restore_run(box, str(copy))
    assert plain.code == 1 and copied.read_bytes() == redacted_bytes
    assert [(r["path"], r["reason"]) for r in plain.of("left")] == [("a.txt", "moved")] and plain.summary["markers_left"] == 1
    moved = restore_run(box, "--any-origin", str(copy))
    assert moved.code == 0, moved.stderr
    assert copied.read_bytes() == original.encode("utf-8")
    assert moved.summary["markers_restored"] == 1 and moved.summary["markers_moved_restored"] == 1
    assert TOKEN not in read_text(a)


def test_a_marker_copied_into_another_file_of_the_same_root_is_left_and_the_origin_file_is_restored(box: Box) -> None:
    """A marker pasted into a second file of the same root is reported as moved and left (exit 1), while the file the row came from is restored."""
    a = box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    assert box.run().code == 0
    found = MARKER_RE.search(read_text(a))
    assert found is not None
    pasted = f"copied {found.group(0)}\n"
    b = box.put(box.root / "b.txt", pasted)
    done = restore_run(box, str(box.root))
    assert done.code == 1
    assert read_text(a) == f"k = {TOKEN}\n" and read_text(b) == pasted
    assert [(r["path"], r["uuid"], r["reason"]) for r in done.of("left")] == [("b.txt", found.group(2), "moved")]


def test_an_unknown_well_formed_uuid_is_left_and_reported(box: Box) -> None:
    """A marker whose uuid is in no vault row is left as it is and reported as unknown (exit 1)."""
    box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    assert box.run().code == 0
    x = box.put(box.root / "x.txt", f"u = {UNKNOWN_MARKER}\n")
    done = restore_run(box, str(box.root))
    assert done.code == 1 and read_text(x) == f"u = {UNKNOWN_MARKER}\n"
    assert done.of("left") == [{"type": "left", "path": "x.txt", "uuid": "6f1c2d3e-4a5b-4c6d-8e7f-0a1b2c3d4e5f", "reason": "unknown"}]


def test_a_marker_with_a_changed_type_is_restored_and_noted(box: Box) -> None:
    """A marker whose Type was edited is still restored by its uuid, with one type-mismatch note and exit 0."""
    original = f"k = {TOKEN}\n"
    a = box.put(box.root / "a.txt", original)
    assert box.run().code == 0
    text = read_text(a)
    found = MARKER_RE.search(text)
    assert found is not None and "Type: github-token." in text
    box.put(a, text.replace("Type: github-token.", "Type: other-kind."))
    done = restore_run(box, str(box.root))
    assert done.code == 0, done.stderr
    assert read_text(a) == original
    assert done.of("note") == [{"type": "note", "path": "a.txt", "uuid": found.group(2), "reason": "type-mismatch"}]
    assert done.summary["type_mismatch"] == 1 and done.summary["markers_restored"] == 1


def test_no_vault_exits_2_with_fixed_text_and_creates_nothing(box: Box) -> None:
    """With no vault.db restore exits 2 with the fixed text and does not create the vault folder."""
    box.put(box.root / "a.txt", "plain\n")
    done = restore_run(box, str(box.root))
    assert done.code == 2 and NO_VAULT_TEXT in done.stderr and done.stdout == ""
    assert not box.vault_dir.exists()


def test_the_terminal_guard_function_and_a_real_run_without_the_vault_variable(box: Box) -> None:
    """restoreAllowed refuses only an unset vault variable with no terminal, and a real run without the variable and with a pipe on stdin exits 2 with the guard text before any vault code, leaving the real vault folder as it was."""
    got = box.bun_json(_GUARD, [[True, True], [True, False], [False, False], [False, True]])
    assert got["allowed"] == [True, True, False, True]
    real_vault = Path(got["home"]) / ".secrets_shield"
    existed = real_vault.exists()
    box.put(box.root / "a.txt", "plain\n")
    done = restore_run(box, str(box.root), env_drop=("SECRETS_SHIELD_VAULT_DIR",), stdin="")
    assert done.code == 2 and GUARD_TEXT in done.stderr and done.stdout == ""
    assert real_vault.exists() == existed


def test_a_hardlinked_file_and_a_repo_with_a_merge_in_progress_are_skipped(box: Box) -> None:
    """A file with a second name and a file in a repo with MERGE_HEAD are not written (skip records, exit 1) and stay redacted; the second name is reported as moved."""
    h = box.put(box.root / "plain" / "h.txt", f"k = {TOKEN}\n")
    box.put(box.root / "repo" / "r.txt", f"k = {TOKEN2}\n")
    repo = box.repo(box.root / "repo", "r.txt")
    assert box.run().code == 0
    link = box.root / "plain" / "h-link.txt"
    os.link(h, link)
    (repo / ".git" / "MERGE_HEAD").write_text(box.git(repo, "rev-parse", "HEAD"), encoding="utf-8")
    before = {p: p.read_bytes() for p in (h, link, repo / "r.txt")}
    done = restore_run(box, str(box.root))
    assert done.code == 1, done.stderr
    # WHY the link is only reported as moved: its path is not the origin of the row, so its marker is left; the file at the origin path has a second name, so it is skipped as hardlinked.
    assert sorted((r["path"], r["reason"]) for r in done.of("skip")) == [("plain/h.txt", "hardlinked"), ("repo/r.txt", "git-operation")]
    assert [(r["path"], r["reason"]) for r in done.of("left")] == [("plain/h-link.txt", "moved")]
    assert done.summary["skipped"] == {"hardlinked": 1, "git-operation": 1} and done.summary["files_restored"] == 0
    assert {p: p.read_bytes() for p in before} == before
    # With --any-origin the other name reaches the hardlink guard too, so it is skipped as hardlinked and no longer reported as moved.
    anywhere = restore_run(box, "--any-origin", str(box.root))
    assert anywhere.code == 1, anywhere.stderr
    assert sorted((r["path"], r["reason"]) for r in anywhere.of("skip")) == [("plain/h-link.txt", "hardlinked"), ("plain/h.txt", "hardlinked"), ("repo/r.txt", "git-operation")]
    assert anywhere.of("left") == []
    assert {p: p.read_bytes() for p in before} == before


def test_a_raw_row_holding_json_escapes_is_restored_as_written_and_the_line_still_parses(box: Box) -> None:
    """A raw row whose value holds the escaped text of a quote, a backslash and a newline is written back unchanged: the JSON line parses and decodes to the value."""
    value = 'pre"quote\\back\nnl'
    f = box.put(box.root / "data.json", "{}\n")
    uuid = vaulted(box, f, json.dumps(value)[1:-1])
    box.put(f, json.dumps({"k": marker_of(uuid)}) + "\n")
    done = restore_run(box, str(f))
    assert done.code == 0, done.stderr
    text = read_text(f)
    assert "\\n" in text and "\n" not in text.rstrip("\n")
    assert json.loads(text)["k"] == value


def test_a_marker_inside_a_git_folder_and_inside_the_vault_folder_is_not_written(box: Box) -> None:
    """Markers in .git content and in the vault folder are left untouched even when their row names that very file, while an ordinary file of the same run is restored."""
    box.vault_dir = box.root / "vaultdir"
    paths = {"git": box.root / "proj" / ".git" / "notes.txt", "config": box.root / "proj" / ".git" / "config", "vault": box.root / "vaultdir" / "notes.txt", "ok": box.root / "ok.txt"}
    for path in paths.values():
        box.put(path, "{}\n")
    for name, path in paths.items():
        value = f"value-{name}-0123456789"
        box.put(path, f"x {marker_of(vaulted(box, path, value))} y\n")
    before = {name: path.read_bytes() for name, path in paths.items() if name != "ok"}
    done = restore_run(box, str(box.root))
    assert done.code == 0, done.stderr
    assert done.summary["files_restored"] == 1 and read_text(paths["ok"]) == "x value-ok-0123456789 y\n"
    assert {name: paths[name].read_bytes() for name in before} == before


def test_a_file_argument_restores_only_that_file(box: Box) -> None:
    """With a file argument only that file is restored and the other redacted file of the folder is left alone."""
    a = box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    b = box.put(box.root / "b.txt", f"k = {TOKEN2}\n")
    assert box.run().code == 0
    redacted_b = b.read_bytes()
    done = restore_run(box, str(a))
    assert done.code == 0, done.stderr
    assert read_text(a) == f"k = {TOKEN}\n" and b.read_bytes() == redacted_b
    assert done.summary["files_with_markers"] == 1 and done.summary["files_restored"] == 1


def test_a_non_utf8_file_with_a_marker_is_skipped(box: Box) -> None:
    """A file that is not UTF-8 and holds a marker is not rewritten (skip not-utf8, exit 1) while a valid file is restored."""
    a = box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    assert box.run().code == 0
    found = MARKER_RE.search(read_text(a))
    assert found is not None
    bad_bytes = b"\xff\xfe " + found.group(0).encode("utf-8") + b"\n"
    bad = box.put(box.root / "bad.txt", bad_bytes)
    done = restore_run(box, str(box.root))
    assert done.code == 1 and bad.read_bytes() == bad_bytes and read_text(a) == f"k = {TOKEN}\n"
    assert [(r["path"], r["reason"]) for r in done.of("skip")] == [("bad.txt", "not-utf8")]


def test_a_file_with_a_nul_in_its_head_is_a_binary_skip_even_with_a_vaulted_marker(box: Box) -> None:
    """A file whose first bytes hold a NUL and that holds a real vaulted marker after it is counted as a binary skip and left byte-identical, with exit 0."""
    path = box.put(box.root / "blob.bin", b"\x00\x01")
    binary = b"\x00\x01 " + marker_of(vaulted(box, path, "value-blob-0123456789")).encode("utf-8") + b"\n"
    box.put(path, binary)
    done = restore_run(box, str(box.root))
    assert done.code == 0, done.stderr
    assert path.read_bytes() == binary
    assert done.summary["skipped"] == {"binary": 1} and done.summary["files_with_markers"] == 0 and done.summary["files_restored"] == 0


def test_a_text_file_over_the_probe_size_with_markers_on_both_sides_of_it_is_restored_whole(box: Box) -> None:
    """A text file of about 20 KB with a vaulted marker before byte 8192 and another after it is restored byte for byte (exit 0, files_restored 1), so the whole file is read after the head probe."""
    path = box.put(box.root / "long.txt", "x\n")
    first, second = "value-first-0123456789", "value-second-0123456789"
    marked = f"a = {marker_of(vaulted(box, path, first))}\n{FILLER[:19989]}b = {marker_of(vaulted(box, path, second))}\n"
    original = f"a = {first}\n{FILLER[:19989]}b = {second}\n"
    assert marked.index("b = ") > 8192
    box.put(path, marked)
    done = restore_run(box, str(box.root))
    assert done.code == 0, done.stderr
    assert done.summary["files_restored"] == 1 and done.summary["markers_restored"] == 2
    assert path.read_bytes() == original.encode("utf-8")


def test_a_text_file_over_max_large_mb_is_skipped_and_the_run_is_incomplete(box: Box) -> None:
    """A text file with a marker over --max-large-mb is not read (skip too-large, complete false, exit 3) while a small file is restored."""
    a = box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    assert box.run().code == 0
    found = MARKER_RE.search(read_text(a))
    assert found is not None
    big_text = f"{FILLER}{found.group(0)}\n"
    big = box.put(box.root / "big.txt", big_text)
    done = restore_run(box, "--max-large-mb", "0.02", str(box.root))
    assert done.code == 3, done.stderr
    assert [(r["path"], r["reason"]) for r in done.of("skip")] == [("big.txt", "too-large")]
    assert done.summary["complete"] is False and done.summary["skipped"] == {"too-large": 1}
    assert read_text(big) == big_text and read_text(a) == f"k = {TOKEN}\n"


# A vault created before spec v6 has the old table, whose CHECK still accepts json-string; this creates such a vault holding one json-string row.
_LEGACY_VAULT = """
import { Database } from "bun:sqlite"
const [file, origin, value] = JSON.parse(await Bun.stdin.text())
const db = new Database(file)
db.exec(`CREATE TABLE secrets (
  uuid TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  origin TEXT NOT NULL,
  value TEXT NOT NULL,
  encoding TEXT NOT NULL CHECK (encoding IN ('raw', 'json-string')),
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  count INTEGER NOT NULL,
  UNIQUE (origin, value, encoding)
)`)
const uuid = crypto.randomUUID()
const now = new Date().toISOString()
db.query("INSERT INTO secrets (uuid, type, origin, value, encoding, first_seen, last_seen, count) VALUES (?, 'github-token', ?, ?, 'json-string', ?, ?, 1)").run(uuid, origin, value, now, now)
db.close()
console.log(JSON.stringify(uuid))
"""


def legacy_json_string_row(box: Box, origin: Path, value: str) -> str:
    """Create the box vault with the pre-v6 table holding one json-string row for origin, and return its uuid."""
    box.vault_dir.mkdir(parents=True, exist_ok=True)
    uuid: str = box.bun_json(_LEGACY_VAULT, [str(box.vault_dir / "vault.db"), str(origin), value])
    return uuid


def test_a_json_string_row_of_an_old_vault_is_left_and_the_run_goes_on(box: Box) -> None:
    """A marker whose row is json-string (an old vault) is left as it is and reported as unknown-encoding, while a raw marker of another file is restored, the run exits 1, and the value appears in no output."""
    value = "value-legacy-0123456789"
    legacy = box.put(box.root / "legacy.txt", "{}\n")
    legacy_uuid = legacy_json_string_row(box, legacy, value)
    box.put(legacy, f"k = {marker_of(legacy_uuid)}\n")
    raw = box.put(box.root / "raw.txt", "{}\n")
    raw_uuid = vaulted(box, raw, "value-raw-0123456789")
    box.put(raw, f"k = {marker_of(raw_uuid)}\n")
    done = restore_run(box, str(box.root))
    assert done.code == 1, done.stderr
    assert read_text(raw) == "k = value-raw-0123456789\n"
    assert read_text(legacy) == f"k = {marker_of(legacy_uuid)}\n"
    assert done.of("left") == [{"type": "left", "path": "legacy.txt", "uuid": legacy_uuid, "reason": "unknown-encoding"}]
    assert done.summary["markers_restored"] == 1 and done.summary["markers_left"] == 1
    assert value not in done.streams()
