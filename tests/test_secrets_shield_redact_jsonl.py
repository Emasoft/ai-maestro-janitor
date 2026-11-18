"""Real-bun, real-git tests of the secrets-shield JSONL redact (TRDD-BAQB9SYO increment 3, step 3b-2b).

No mock: every test runs `scripts/shield_scan/scan.ts` under real bun on a fixture tree built in tmp_path, with real worker processes, the real shield core
and a real SQLite vault under tmp_path (`Box.env` sets SECRETS_SHIELD_VAULT_DIR, so no test can write the real vault). Every fake credential is generated at
call time by `_fake_secrets`, so no contiguous credential literal sits in this file (see tests/test_secret_fixture_hygiene.py).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import transcript_redact as tr
from _fake_secrets import b62
from _shield_redact_box import MARKER_RE, SCAN, SHIELD, TIMEOUT_S, TOKEN, TOKEN2, Box, Scan, read_text

# The suite denies every real binary by default (tests/sandbox_guard.py); this file exists to run the REAL bun and the REAL git, so it opts in.
pytestmark = pytest.mark.real_subprocess("bun", "git")

PATTERNS = SHIELD.parents[1] / "hooks" / "secret-shield" / "patterns.ts"
PEM_LINES = ["-----BEGIN " + "RSA PRIVATE KEY-----", "MIIEowIBAAKCAQEA" + b62("jsonl-pem-1", 26), b62("jsonl-pem-2", 40), b62("jsonl-pem-3", 38), "-----END " + "RSA PRIVATE KEY-----"]
PASSWORD = b62("jsonl-pw", 24)
# A JSON string that holds a newline written as the two characters backslash and n, then a line that starts with a password assignment: the assignment rule is anchored to a line start, so it fires only on the decoded string.
AFTER_NEWLINE = ["{\"id\":1}", "{\"text\":\"first line\\npassword = " + PASSWORD + "\"}"]


@pytest.fixture
def box(tmp_path: Path) -> Box:
    """A fresh Box in tmp_path."""
    return Box(tmp_path)


def parsed(text: str) -> list[object]:
    """Every non-empty line of the text parsed as JSON; a line that does not parse raises."""
    return [json.loads(line) for line in text.split("\n") if line]


def scan_only(box: Box) -> Scan:
    """Run the scanner without --redact over the box root: 2 jobs and an explicit findings file under the box."""
    box.runs += 1
    out_path = box.base / "out" / f"run{box.runs}.jsonl"
    cmd = [tr.resolve_bun(), str(SCAN), "--jobs", "2", "--out", str(out_path), str(box.root)]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S, env=box.env(), check=False)
    return Scan(done, out_path)


def test_escaped_pem_and_raw_password_pair_are_redacted_and_every_line_parses(box: Box) -> None:
    """An escaped PEM key and a raw password pair in JSON lines are redacted, every line still parses, and JSON numbers keep their bytes."""
    pem_line = json.dumps({"id": 1, "key": "\n".join(PEM_LINES)})
    pair_line = "{\"password\":\"" + PASSWORD + "\",\"count\":42,\"ratio\":1.5e-7}"
    number_line = "{\"big\":12345678901234567890,\"small\":2.5E+3}"
    a = box.put(box.root / "a.jsonl", f"{pem_line}\n{pair_line}\n{number_line}\n")
    result = box.run()
    assert result.code == 0, result.stderr
    text = read_text(a)
    assert len(parsed(text)) == 3
    assert PASSWORD not in text and PEM_LINES[1] not in text and PEM_LINES[2] not in text and PEM_LINES[3] not in text
    assert ",\"count\":42,\"ratio\":1.5e-7}" in text and text.endswith(number_line + "\n")
    summary = result.summary
    assert summary["files_redacted"] == 1 and summary["findings_not_redacted"] == 0 and summary["jsonl_lines_not_json"] == 0 and summary["residual"] == 0
    assert PASSWORD not in result.streams() and PEM_LINES[2] not in result.streams()


def test_redact_then_restore_is_byte_identical_for_escaped_forms(box: Box) -> None:
    """Redact then restore gives back the original bytes for strings that hold an escaped slash, a backslash-u escape and an escaped quote around a secret."""
    original = "\n".join(
        [
            "{\"a\":\"x\\/y token " + TOKEN + " end\"}",
            "{\"b\":\"caf\\u00e9 " + TOKEN2 + "\"}",
            "{\"c\":\"say \\\"" + TOKEN + "\\\" now\"}",
        ]
    ) + "\n"
    a = box.put(box.root / "a.jsonl", original)
    result = box.run()
    assert result.code == 0, result.stderr
    text = read_text(a)
    assert len(parsed(text)) == 3 and TOKEN not in text and TOKEN2 not in text
    assert len(MARKER_RE.findall(text)) == 3
    assert box.restore(text).encode("utf-8") == original.encode("utf-8")


def test_second_run_changes_nothing(box: Box) -> None:
    """A second run over a redacted JSONL file changes no byte of it and no vault row, finds nothing and exits 0."""
    a = box.put(box.root / "a.jsonl", "{\"k\":\"v " + TOKEN + "\"}\n" + PASSWORD.join(["{\"password\":\"", "\"}"]) + "\n")
    assert box.run().code == 0
    after_first = a.read_bytes()
    rows = box.vault_rows()
    second = box.run()
    assert second.code == 0 and second.summary["findings"] == 0 and second.summary["files_redacted"] == 0
    assert a.read_bytes() == after_first and box.vault_rows() == rows


def test_markers_already_in_a_line_survive_byte_for_byte(box: Box) -> None:
    """A core marker and a shield marker from an earlier run in the same line as a new token survive a new run byte for byte, and restore still gives back every value."""
    a = box.put(box.root / "a.jsonl", "{\"a\":\"k " + TOKEN + "\"}\n")
    assert box.run().code == 0
    old_line = read_text(a).split("\n")[0]
    old_marker = MARKER_RE.search(old_line)
    assert old_marker is not None
    core_marker = "[JANITOR-REDACTED:github-token]"
    # One line holds the old shield marker, a core marker and a new raw token; the next line holds a core marker alone.
    mixed_line = old_line[:-2] + " " + core_marker + " " + TOKEN2 + "\"}"
    core_line = "{\"b\":\"" + core_marker + " tail\"}"
    box.put(a, mixed_line + "\n" + core_line + "\n")
    result = box.run()
    assert result.code == 0 and result.summary["files_redacted"] == 1, result.stderr
    lines = read_text(a).split("\n")
    assert TOKEN2 not in lines[0] and lines[0].startswith(old_line[:-2] + " " + core_marker + " ") and lines[1] == core_line
    assert len(parsed(read_text(a))) == 2
    expected = "{\"a\":\"k " + TOKEN + " " + core_marker + " " + TOKEN2 + "\"}\n" + core_line + "\n"
    assert box.restore(read_text(a)) == expected


def test_lines_that_are_not_json_are_redacted_as_text_and_counted(box: Box) -> None:
    """A line that is not JSON is redacted as text and counted in jsonl_lines_not_json, and a PEM block over several non-JSON lines is hidden whole."""
    original = "\n".join(["{\"ok\":1}", "plain line " + TOKEN, *PEM_LINES, "{\"ok\":2}"]) + "\n"
    a = box.put(box.root / "a.jsonl", original)
    result = box.run()
    assert result.code == 0, result.stderr
    text = read_text(a)
    assert TOKEN not in text and not any(line in text for line in PEM_LINES[1:4]) and "BEGIN" not in text
    assert text.startswith("{\"ok\":1}\n") and text.endswith("\n{\"ok\":2}\n")
    assert result.summary["jsonl_lines_not_json"] == 6 and result.summary["findings_not_redacted"] == 0
    assert box.restore(text) == original


def test_sweep_copy_that_would_break_an_escape_skips_the_file_as_json_broken(box: Box) -> None:
    """A copy of a vaulted value found by the sweep right after a backslash would write a marker into an invalid escape: the file is left unchanged, skipped as json-broken, counted in findings_not_redacted, exit 1."""
    rest = b62("jsonl-sweep", 20)
    value = "n" + rest
    assert box.bun_json(f"import {{ propagates }} from {json.dumps(str(PATTERNS))}; console.log(JSON.stringify(propagates(JSON.parse(await Bun.stdin.text()))))", value) is True
    first = "{\"password\":\"" + value + "\"}"
    # ONE backslash then n and the rest, inside the string: JSON for a newline followed by the rest. Two backslashes would be an escaped backslash and stay valid.
    second = "{\"note\":\"" + "\\" + "n" + rest + "\"}"
    assert second.count("\\") == 1 and json.loads(second)["note"] == "\n" + rest
    original = first + "\n" + second + "\n"
    a = box.put(box.root / "a.jsonl", original)
    result = box.run()
    assert result.code == 1, result.stderr
    assert a.read_bytes() == original.encode("utf-8")
    assert ("a.jsonl", "json-broken") in result.skips
    assert result.summary["findings_not_redacted"] > 0 and result.summary["files_redacted"] == 0 and result.summary["skipped"]["json-broken"] == 1
    # WHY the findings are checked: json-broken also comes from a line the core could not hide (kind json-unredactable); here the only finding is the password pair on line 1, so the skip is the sweep copy on line 2.
    findings = [r for r in result.records if r["type"] == "finding"]
    assert findings and {r["line"] for r in findings} == {1} and all(r["kind"] != "json-unredactable" for r in findings)
    assert value not in result.streams()


def test_scan_only_finds_a_secret_after_an_escaped_newline_with_its_line_number(box: Box) -> None:
    """Scan-only finds a secret written right after an escaped newline in a JSON string, located on its line; the plain counter does not find it in the same text in a .txt file."""
    box.put(box.root / "a.jsonl", "\n".join(AFTER_NEWLINE) + "\n")
    box.put(box.root / "b.txt", "\n".join(AFTER_NEWLINE) + "\n")
    result = scan_only(box)
    assert result.code == 1, result.stderr
    findings = [r for r in result.records if r["type"] == "finding"]
    assert {r["line"] for r in findings if r["path"] == "a.jsonl"} == {2}
    assert [r for r in findings if r["path"] == "b.txt"] == []
    assert result.summary["jsonl_lines_not_json"] == 0
    assert PASSWORD not in result.streams()


def test_home_pass_rewrites_a_home_path_inside_a_json_string_also_with_escaped_slashes(box: Box) -> None:
    """With --passes secrets,home a home path inside a JSON string, also written with escaped slashes, becomes ~, every line parses and home_rewrites counts both."""
    home = str(box.home_dir)
    escaped = home.replace("/", "\\/")
    lines = ["{\"cwd\":\"" + home + "/proj\"}", "{\"cwd\":\"" + escaped + "\\/p\"}", "{\"k\":\"" + TOKEN + "\"}"]
    a = box.put(box.root / "a.jsonl", "\n".join(lines) + "\n")
    result = box.run("--passes", "secrets,home")
    assert result.code == 0, result.stderr
    text = read_text(a)
    assert home not in text and escaped not in text
    docs = parsed(text)
    assert docs[0] == {"cwd": "~/proj"} and docs[1] == {"cwd": "~/p"} and TOKEN not in text
    assert result.summary["home_rewrites"] == 2 and result.summary["findings_not_redacted"] == 0 and result.summary["files_redacted"] == 1


def test_ndjson_file_takes_the_json_path(box: Box) -> None:
    """A .ndjson file is read JSON-aware: the escaped-newline secret is redacted, the line still parses and restore gives back the original."""
    original = "\n".join(AFTER_NEWLINE) + "\n"
    a = box.put(box.root / "a.ndjson", original)
    result = box.run()
    assert result.code == 0, result.stderr
    text = read_text(a)
    assert len(parsed(text)) == 2 and PASSWORD not in text and len(MARKER_RE.findall(text)) == 1
    assert box.restore(text) == original
