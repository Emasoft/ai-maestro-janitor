"""Commit-time secret scan of what a commit would contain (TRDD-FNPDFZWU, increment 1).

OWNER ORDER 2026-11-18: the secrets shield must also prevent committing secrets, by running the
scanner on the committed files at each commit, before git-cliff builds the changelog (a secret
in a commit would reach GitHub release notes and package metadata).

WHY A GIT HOOK AND NOT A PreToolUse GUARD: `git add x && git commit` is ONE Bash call, so a guard
fires before the add; `commit -a` and a pathspec commit build their index inside git. Only the hooks
see what is committed: pre-commit sees the index, commit-msg sees the message (the message is what
git-cliff publishes).

What it does. No argument: the staged blobs (read from the index through the OIDs of
`git diff --cached --raw`, so a partly staged file is judged as committed, and a hook that git runs
on a temporary index sees that index through GIT_INDEX_FILE). `--message-file PATH`: the commit
message. Each blob is written into a fresh 0700 temp dir outside any git tree, with its path
mirrored, and the shield scanner (scripts/shield_scan/scan.ts, run by bun) scans that tree.
The scanner and bun start in the PLUGIN folder, never in the committing repo: bun reads bunfig.toml
(whose `preload` runs code) and .env from its working folder (TRDD-6E2I17HN).

Blocking rule. A staged finding blocks unless its whole line text is also in the HEAD blob of the
same path (the rename source when renamed): an existing fixture line is not re-flagged, a new one is.
A finding with no line number cannot be compared and blocks. The commit message has no baseline: any
finding blocks. v1 never rewrites a file: a marker written into a working file that is not restorable
could overwrite uncommitted content; redaction belongs to the vault-backed redact path, later.

Exit codes: 0 clean (or inert), 1 block, 2 cannot run (also blocks while the janitor is active: a
scan that did not run is not a clean scan). Inert = exit 0 with one line, when the janitor DATA dir
is absent (plugin uninstalled) or the kill-switch file exists, so an uninstall never bricks commits.

Nothing printed ever holds a secret value, a line of a scanned file, or the text of an exception.
The scan stops at the first failure: a scan that is incomplete (scanner exit 3) is cannot-run, never clean.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import transcript_redact  # noqa: E402  (resolve_bun; stdlib-only sibling)

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_SHIELD_DIR = _PLUGIN_ROOT / "scripts" / "shield_scan"
_SCAN_TS = _SHIELD_DIR / "scan.ts"
_DATA_NAME = "ai-maestro-janitor-ai-maestro-plugins"
_SCAN_TIMEOUT_S = 300.0
_MESSAGE_LABEL = "commit message"
_SCISSORS = b"# ------------------------ >8 ------------------------"
_ZERO_OID = "0" * 40
_GITLINK_MODE = "160000"
# WHY GIT_OPTIONAL_LOCKS=0: every git call here is read-only, and a read-only git can take .git/index.lock and kill a concurrent
# WRITE (janitor#245; tests/test_git_optional_locks_guard.py). The rest of the hook environment (GIT_INDEX_FILE) is kept.
_GIT_ENV = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}


class ScannerError(RuntimeError):
    """The scan could not run. The message is fixed text and never carries file content."""


class StagedBlob(NamedTuple):
    """One staged file: its path, the staged blob and the baseline blob OID (zeros = no baseline)."""

    path: str
    new_oid: str
    old_oid: str
    symlink: bool


class Finding(NamedTuple):
    path: str
    line: int | None
    kind: str


def _inert_reason() -> str | None:
    """Why the janitor is not active, or None when it is. Paths derive from HOME only (never JANITOR_DATA_DIR)."""
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    data = home / ".claude" / "plugins" / "data" / _DATA_NAME
    if not data.is_dir():
        return "the janitor DATA dir is absent"
    if (home / ".claude" / "janitor-control" / "kill-switch.flag").is_file() or (data / "global-state" / "kill-switch.flag").is_file():
        return "the janitor kill-switch is set"
    return None


def _git(root: Path, args: list[str], *, stdin: bytes | None = None) -> bytes:
    """Run git in `root` with the hook environment (GIT_INDEX_FILE and the like) kept: that is how the index of a `commit -a` is seen."""
    try:
        r = subprocess.run(["git", *args], cwd=root, input=stdin, capture_output=True, check=False, timeout=60, env=_GIT_ENV)
    except (OSError, subprocess.SubprocessError):
        raise ScannerError("git could not be run") from None
    if r.returncode != 0:
        raise ScannerError("a git command failed")
    return r.stdout


def _repo_root() -> Path:
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, check=False, timeout=10, env=_GIT_ENV)
    except (OSError, subprocess.SubprocessError):
        raise ScannerError("git could not be run") from None
    if r.returncode != 0 or not r.stdout.strip():
        raise ScannerError("not inside a git repository")
    return Path(os.fsdecode(r.stdout.strip()))


def _staged_blobs(root: Path) -> list[StagedBlob]:
    """Every added, copied, modified, renamed or type-changed staged path, with its blob OIDs.

    WHY the raw diff and not the paths alone: it carries the staged blob OID, the HEAD-side blob OID
    (the rename source for a rename, zeros on an added file or an unborn branch) and the modes in one
    call, and `-z` keeps odd path bytes intact. A gitlink (mode 160000) has no blob and is skipped.
    """
    out = _git(root, ["diff", "--cached", "--raw", "-z", "--no-abbrev", "-M"])
    tokens = out.split(b"\0")
    blobs: list[StagedBlob] = []
    i = 0
    while i < len(tokens) and tokens[i]:
        meta = tokens[i].lstrip(b":").split(b" ")
        if len(meta) < 5:
            raise ScannerError("the staged diff could not be read")
        _old_mode, new_mode, old_oid, new_oid, status = (m.decode("ascii", "replace") for m in meta[:5])
        if status[:1] in ("R", "C"):
            path = os.fsdecode(tokens[i + 2])
            i += 3
        else:
            path = os.fsdecode(tokens[i + 1])
            i += 2
        if status[:1] == "D" or new_mode == _GITLINK_MODE or new_oid == _ZERO_OID:
            continue
        blobs.append(StagedBlob(path, new_oid, old_oid, new_mode == "120000"))
    return blobs


def _read_blobs(root: Path, oids: set[str]) -> dict[str, bytes]:
    """Content of each blob, in one `git cat-file --batch` run. A missing blob is an error, never an empty file."""
    wanted = sorted(o for o in oids if o != _ZERO_OID)
    if not wanted:
        return {}
    raw = _git(root, ["cat-file", "--batch"], stdin=("\n".join(wanted) + "\n").encode("ascii"))
    result: dict[str, bytes] = {}
    pos = 0
    for oid in wanted:
        nl = raw.find(b"\n", pos)
        header = raw[pos:nl].split(b" ") if nl >= 0 else []
        if len(header) != 3 or header[1] != b"blob" or header[0].decode("ascii", "replace") != oid:
            raise ScannerError("a git blob could not be read")
        size = int(header[2])
        result[oid] = raw[nl + 1 : nl + 1 + size]
        pos = nl + 1 + size + 1
    return result


def _mirror(tree: Path, rel: str, content: bytes) -> None:
    """Write `content` at `tree/rel`. A path that escapes the tree or collides with another staged path is an error."""
    parts = Path(rel).parts
    if not parts or Path(rel).is_absolute() or ".." in parts:
        raise ScannerError("a staged path is not a plain relative path")
    dest = tree.joinpath(*parts)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        # WHY exclusive create: on a case-insensitive filesystem two staged paths that differ only in case
        # map to one file; overwriting the first would hide its content from the scan.
        with open(dest, "xb") as fh:
            fh.write(content)
    except FileExistsError:
        raise ScannerError("two staged paths map to the same file here (case-insensitive filesystem)") from None


def _run_scanner(tree: Path, findings_file: Path) -> list[dict[str, object]]:
    """Run scan.ts over `tree`; return its finding records. Anything but a complete run is ScannerError."""
    if not _SCAN_TS.is_file():
        raise ScannerError("the shield scanner script is missing")
    bun = transcript_redact.resolve_bun()
    # WHY GIT_* stripped: scan.ts runs git itself; an inherited GIT_DIR / GIT_INDEX_FILE would make it read
    # the committing repo instead of the temp tree.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    cmd = [bun, "--cwd", str(_SHIELD_DIR), str(_SCAN_TS), "--all", "--passes", "secrets,cards", "--out", str(findings_file), str(tree)]
    try:
        # cwd is the plugin scanner folder, never the caller folder (TRDD-6E2I17HN): bunfig.toml preload and .env.
        proc = subprocess.run(cmd, cwd=_SHIELD_DIR, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=_SCAN_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        raise ScannerError("the shield scanner could not be run or timed out") from None
    records: list[dict[str, object]] = []
    try:
        for raw in findings_file.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                rec = json.loads(raw)
                if isinstance(rec, dict):
                    records.append(rec)
    except (OSError, ValueError):
        raise ScannerError("the shield scanner wrote no readable findings file") from None
    summary = records[-1] if records else {}
    if proc.returncode == 3:
        skipped = sorted(f"{r.get('path')} ({r.get('reason')})" for r in records if r.get("type") == "skip" and r.get("reason") != "binary")
        raise ScannerError("the shield scan was incomplete; not scanned: " + ", ".join(skipped) if skipped else "the shield scan was incomplete")
    if proc.returncode not in (0, 1) or summary.get("type") != "summary" or summary.get("complete") is not True:
        raise ScannerError("the shield scan did not complete")
    return [r for r in records if r.get("type") == "finding"]


def _as_findings(records: list[dict[str, object]]) -> list[Finding]:
    out: list[Finding] = []
    for r in records:
        line = r.get("line")
        out.append(Finding(str(r.get("path")), line if isinstance(line, int) else None, str(r.get("kind"))))
    return sorted(set(out), key=lambda f: (f.path, f.line or 0, f.kind))


def _lines(content: bytes) -> list[bytes]:
    """Lines as the scanner counts them: split on LF only (never splitlines, which also splits on CR, FF and U+2028), final CR removed."""
    return [ln.rstrip(b"\r") for ln in content.split(b"\n")]


def _scan_tree(files: dict[str, bytes]) -> list[Finding]:
    tmp = Path(tempfile.mkdtemp(prefix="staged-secret-scan-"))
    try:
        tree = tmp / "tree"
        tree.mkdir()
        for rel, content in files.items():
            _mirror(tree, rel, content)
        return _as_findings(_run_scanner(tree, tmp / "findings.jsonl"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def scan_index(root: Path) -> tuple[list[Finding], int]:
    """Scan the staged blobs; return (new findings, count of pre-existing ones)."""
    blobs = _staged_blobs(root)
    if not blobs:
        return [], 0
    contents = _read_blobs(root, {b.new_oid for b in blobs})
    # symlink blobs are written as regular files holding the link target text: scanned, never followed.
    found = _scan_tree({b.path: contents[b.new_oid] for b in blobs})
    if not found:
        return [], 0
    by_path = {b.path: b for b in blobs}
    baseline = _read_blobs(root, {by_path[f.path].old_oid for f in found if f.path in by_path})
    new: list[Finding] = []
    old = 0
    for f in found:
        blob = by_path.get(f.path)
        if blob is None or f.line is None:
            new.append(f)
            continue
        staged = _lines(contents[blob.new_oid])
        base = set(_lines(baseline.get(blob.old_oid, b"")))
        if f.line - 1 < len(staged) and staged[f.line - 1] in base:
            old += 1
        else:
            new.append(f)
    return new, old


def scan_message(message_file: Path) -> list[Finding]:
    """Scan a commit message; every finding blocks. `git commit -v` appends the diff below a scissors line: it is not part of the message."""
    try:
        text = message_file.read_bytes()
    except OSError:
        raise ScannerError("the commit message file could not be read") from None
    cut = text.find(_SCISSORS)
    if cut >= 0:
        text = text[:cut]
    return [Finding(_MESSAGE_LABEL, f.line, f.kind) for f in _scan_tree({"message.txt": text})]


def _report(findings: list[Finding], pre_existing: int) -> None:
    print("BLOCKED: secret in what this commit would contain (file, line and kind only; the value is never printed):")
    for f in findings:
        print(f"  {f.path}:{f.line if f.line is not None else '?'}  [{f.kind}]")
    if pre_existing:
        print(f"  · {pre_existing} pre-existing finding(s) already at HEAD, not blocking")
    print("Remove the secret from the file or the message (and rotate it if it is real), then commit again.")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    reason = _inert_reason()
    if reason is not None:
        print(f"staged-secret-scan: inert — {reason}")
        return 0
    try:
        if args[:1] == ["--message-file"] and len(args) == 2:
            findings, pre_existing = scan_message(Path(args[1])), 0
        elif not args:
            findings, pre_existing = scan_index(_repo_root())
        else:
            raise ScannerError("usage: staged_secret_scan.py [--message-file PATH]")
    except (ScannerError, transcript_redact.RedactionUnavailable) as exc:
        print(f"BLOCKED: the secret scan could not run — {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 - fail closed; the type name only, the message could quote file text
        print(f"BLOCKED: the secret scan stopped on an internal error ({type(exc).__name__})")
        return 2
    if findings:
        _report(findings, pre_existing)
        return 1
    if pre_existing:
        print(f"clean · {pre_existing} pre-existing finding(s) already at HEAD, not blocking")
    return 0


if __name__ == "__main__":
    sys.exit(main())
