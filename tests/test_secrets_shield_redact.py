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
import re
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
import transcript_redact as tr
from _fake_secrets import secret

# The suite denies every real binary by default (tests/sandbox_guard.py); this file exists to run the REAL bun and the REAL git, so it opts in.
pytestmark = pytest.mark.real_subprocess("bun", "git")

_SHIELD = Path(__file__).resolve().parents[1] / "scripts" / "shield_scan"
SCAN = _SHIELD / "scan.ts"
VAULT = _SHIELD / "vault.ts"
REDACT = _SHIELD / "redact.ts"
TIMEOUT_S = 180.0
TOKEN = secret("gh" + "p_", "redact-1", 36)
TOKEN2 = secret("gh" + "p_", "redact-2", 36)
AT = chr(64)
MARKER_RE = re.compile(r"\[REDACTED-BY-SECRET-SHIELD\. Type: ([A-Za-z0-9_-]+)\. ID: ([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\]")


class Scan:
    """The result of one scanner run: exit code, both streams, and the records of the findings file when it was written."""

    def __init__(self, done: subprocess.CompletedProcess[str], out: Path) -> None:
        self.code = done.returncode
        self.stdout = done.stdout
        self.stderr = done.stderr
        self.out = out
        self.records: list[dict[str, Any]] = []
        if out.exists():
            self.records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

    @property
    def summary(self) -> dict[str, Any]:
        """The last record of the findings file."""
        assert self.records[-1]["type"] == "summary"
        return self.records[-1]

    @property
    def skips(self) -> list[tuple[str, str]]:
        """Every skip record as (path, reason), in file order."""
        return [(r["path"], r["reason"]) for r in self.records if r["type"] == "skip"]

    def streams(self) -> str:
        """Everything the run wrote that a person could read: stdout, stderr and the findings file."""
        return self.stdout + self.stderr + (self.out.read_text(encoding="utf-8") if self.out.exists() else "")


class Box:
    """One test's folders (root, out, home, vault, global git config) and the commands that run in them."""

    def __init__(self, base: Path) -> None:
        self.base = base.resolve()
        self.root = self.base / "root"
        self.root.mkdir()
        self.home_dir = self.base / "home"
        self.home_dir.mkdir()
        self.vault_dir = self.base / "vault"
        self.gitconfig = self.base / "gitconfig"
        self.gitconfig.write_text(f"[user]\n\tname = redact test\n\temail = redact{AT}example.test\n", encoding="utf-8")
        self.runs = 0

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """The environment of every child: HOME, the global git config and the vault folder are the test's own."""
        env = dict(os.environ)
        env.update({"HOME": str(self.home_dir), "GIT_CONFIG_GLOBAL": str(self.gitconfig), "GIT_CONFIG_NOSYSTEM": "1", "SECRETS_SHIELD_VAULT_DIR": str(self.vault_dir)})
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            env.pop(name, None)
        env.update(extra or {})
        return env

    def git(self, cwd: Path, *args: str) -> str:
        """Run git in cwd and return its stdout; a failure raises."""
        done = subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, timeout=TIMEOUT_S, env=self.env())
        return done.stdout

    def put(self, path: Path, text: str | bytes) -> Path:
        """Write a file, creating its folders."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8", newline="")
        return path

    def repo(self, path: Path, *tracked: str) -> Path:
        """Make a git repo at path and commit the named files (relative to path)."""
        path.mkdir(parents=True, exist_ok=True)
        self.git(path, "init", "-q")
        if tracked:
            self.git(path, "add", "-f", "--", *tracked)
            self.git(path, "commit", "-q", "-m", "c")
        return path

    def run(self, *args: str, root: Path | None = None, min_age: str | None = "0", env_extra: dict[str, str] | None = None) -> Scan:
        """Run the scanner with --redact over root (default: the box root), 2 jobs and an explicit findings file under the box."""
        self.runs += 1
        out_path = self.base / "out" / f"run{self.runs}.jsonl"
        cmd = [tr.resolve_bun(), str(SCAN), "--jobs", "2", "--out", str(out_path), "--redact"]
        if min_age is not None:
            cmd += ["--min-age-minutes", min_age]
        cmd += [*args, str(root or self.root)]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S, env=self.env(env_extra), check=False)
        return Scan(done, out_path)

    def bun_json(self, script: str, data: object) -> Any:
        """Run a `bun -e` script that reads one JSON value from stdin and prints one JSON value."""
        done = subprocess.run([tr.resolve_bun(), "-e", script], input=json.dumps(data), capture_output=True, text=True, timeout=TIMEOUT_S, env=self.env(), check=True)
        return json.loads(done.stdout)

    def vault_rows(self) -> list[dict[str, Any]]:
        """Every vault row (uuid, type, origin, encoding, count, value)."""
        script = f"import {{ openVault }} from {json.dumps(str(VAULT))}; await Bun.stdin.text(); const v = openVault(); console.log(JSON.stringify(v.list().map((m) => ({{ ...m, value: v.byUuid(m.uuid)?.value }})))); v.close()"
        rows: list[dict[str, Any]] = self.bun_json(script, None)
        return rows

    def restore(self, text: str) -> str:
        """The text with every shield marker replaced by the value of its vault row (what restore.ts will do in step 3a-4)."""
        script = f"import {{ openVault }} from {json.dumps(str(VAULT))}; const uuids = JSON.parse(await Bun.stdin.text()); const v = openVault(); const out = {{}}; for (const u of uuids) out[u] = v.byUuid(u)?.value ?? null; console.log(JSON.stringify(out)); v.close()"
        values: dict[str, str | None] = self.bun_json(script, sorted({m.group(2) for m in MARKER_RE.finditer(text)}))

        def put_back(m: re.Match[str]) -> str:
            value = values[m.group(2)]
            assert value is not None, "a marker has no vault row"
            return value

        return MARKER_RE.sub(put_back, text)


@pytest.fixture
def box(tmp_path: Path) -> Box:
    """A fresh Box in tmp_path."""
    return Box(tmp_path)


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


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
    # WHY the field is asserted: step 3a-3 (sweep and re-scan) does not exist yet, so no run may claim that no copy is left.
    assert summary["residual_check"] == "not-run" and summary["complete"] is True
    for path, original in ((a, original_a), (b, original_b)):
        text = _read(path)
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
    in_a = [m.group(2) for m in MARKER_RE.finditer(_read(a))]
    in_b = [m.group(2) for m in MARKER_RE.finditer(_read(b))]
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
    redacted = _read(a)
    box.put(a, redacted + f"other = {TOKEN}\n")
    result = box.run()
    assert result.code == 0 and result.summary["files_redacted"] == 1, result.stderr
    ids = [m.group(2) for m in MARKER_RE.finditer(_read(a))]
    assert len(ids) == 2 and ids[0] == ids[1]
    assert box.restore(_read(a)) == f"k = {TOKEN}\nother = {TOKEN}\n"


def test_gitignored_env_is_untouched_by_default_and_redacted_with_all(box: Box) -> None:
    """A gitignored .env with a token is not read by default (untouched), and with --all it is redacted."""
    box.put(box.root / ".gitignore", ".env\n")
    box.put(box.root / "a.txt", "plain\n")
    env_file = box.put(box.root / ".env", f"API = {TOKEN}\n")
    box.repo(box.root, "a.txt", ".gitignore")
    default = box.run()
    assert default.code == 0 and _read(env_file) == f"API = {TOKEN}\n" and default.summary["gitignored_entries"] == 1
    everything = box.run("--all")
    assert everything.code == 0, everything.stderr
    assert TOKEN not in _read(env_file) and box.restore(_read(env_file)) == f"API = {TOKEN}\n"


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
    assert first.code == 1 and _read(a) == f"k = {TOKEN}\n"
    assert ("a.txt", "git-operation") in first.skips and first.summary["findings_not_redacted"] == 1
    merge_head.unlink()
    second = box.run()
    assert second.code == 0 and TOKEN not in _read(a)


def test_recent_file_is_skipped_by_default_and_redacted_once_old(box: Box) -> None:
    """A file modified a moment ago is skipped as recent with the default of 10 minutes (exit 1); with an old mtime the same run redacts it."""
    a = box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    first = box.run(min_age=None)
    assert first.code == 1 and _read(a) == f"k = {TOKEN}\n"
    assert ("a.txt", "recent") in first.skips and first.summary["findings_not_redacted"] == 1 and first.summary["min_age_minutes"] == 10
    old = time.time() - 3600
    os.utime(a, (old, old))
    second = box.run(min_age=None)
    assert second.code == 0 and TOKEN not in _read(a)


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
    assert TOKEN2 not in _read(ok)
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


def test_redact_with_the_home_pass_exits_2(box: Box) -> None:
    """--redact with --passes secrets,home exits 2 with the fixed text that the home pass comes in a later step, and changes nothing."""
    a = box.put(box.root / "a.txt", f"k = {TOKEN}\n")
    result = box.run("--passes", "secrets,home")
    assert result.code == 2 and "home pass with --redact" in result.stderr
    assert a.read_bytes() == f"k = {TOKEN}\n".encode()


_ALIGN = f"""
import {{ alignStretches, cutMarkers, CORE_MARKER, planRedaction, finalText, restoreCheck }} from {json.dumps(str(REDACT))}
import {{ mark }} from {json.dumps(str(_SHIELD.parents[1] / "hooks" / "secret-shield" / "patterns.ts"))}
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
