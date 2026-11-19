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

`--range <rev-list args>` (increment 2): the same scan over every commit of `git rev-list <args>` (message plus the blobs each commit changes
against its first parent), for the commits no commit-time hook saw. git-hooks/pre-push runs it on every pushed ref and publish.py before git-cliff.

Exit codes: 0 clean (or inert), 1 block, 2 cannot run (also blocks while the janitor is active: a
scan that did not run is not a clean scan). Inert = exit 0 with one line, when the janitor DATA dir
is absent (plugin uninstalled) or the kill-switch file exists, so an uninstall never bricks commits.

Nothing printed ever holds a secret value, a line of a scanned file, or the text of an exception.
The scan stops at the first failure: a scan that is incomplete (scanner exit 3) is cannot-run, never clean.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import transcript_redact  # noqa: E402  (resolve_bun; stdlib-only sibling)
from exe_path import exe  # noqa: E402

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_SHIELD_DIR = _PLUGIN_ROOT / "scripts" / "shield_scan"
_SCAN_TS = _SHIELD_DIR / "scan.ts"
_DATA_NAME = "ai-maestro-janitor-ai-maestro-plugins"
_SCAN_TIMEOUT_S = 300.0
_MESSAGE_LABEL = "commit message"
_RANGE_FLAGS = ("--not", "--remotes")
_ALLOW_FILE = ".janitor-secret-allow"
_PRINT_ENTRIES = "--print-allow-entries"
_HEX = frozenset("0123456789abcdef")
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


class ScanResult(NamedTuple):
    """What one scan found: the blocking findings, and the counts and entry lines the report discloses."""

    findings: list[Finding]
    pre_existing: int = 0
    exempted: int = 0  # file findings cleared by a .janitor-secret-allow entry
    exempted_new: int = 0  # of those, cleared only by entries absent from the base list
    entries: tuple[str, ...] = ()  # ready allow-list lines for the blocking file findings (--print-allow-entries)


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
        r = subprocess.run([exe("git"), *args], cwd=root, input=stdin, capture_output=True, check=False, timeout=60, env=_GIT_ENV)
    except (OSError, subprocess.SubprocessError):
        raise ScannerError("git could not be run") from None
    if r.returncode != 0:
        raise ScannerError("a git command failed")
    return r.stdout


def _repo_root() -> Path:
    try:
        r = subprocess.run([exe("git"), "rev-parse", "--show-toplevel"], capture_output=True, check=False, timeout=10, env=_GIT_ENV)
    except (OSError, subprocess.SubprocessError):
        raise ScannerError("git could not be run") from None
    if r.returncode != 0 or not r.stdout.strip():
        raise ScannerError("not inside a git repository")
    return Path(os.fsdecode(r.stdout.strip()))


def _staged_blobs(root: Path, diff_cmd: tuple[str, ...] = ("diff", "--cached")) -> list[StagedBlob]:
    """Every added, copied, modified, renamed or type-changed path of `git <diff_cmd> --raw`, with its blob OIDs. Default: the staged set.

    WHY the raw diff and not the paths alone: it carries the staged blob OID, the HEAD-side blob OID
    (the rename source for a rename, zeros on an added file or an unborn branch) and the modes in one
    call, and `-z` keeps odd path bytes intact. A gitlink (mode 160000) has no blob and is skipped.
    The range scan passes a `diff-tree` command so one commit is read the same way against its first parent.
    """
    out = _git(root, [*diff_cmd, "--raw", "-z", "--no-abbrev", "-M"])
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


def _read_blobs(root: Path, oids: set[str], kind: str = "blob") -> dict[str, bytes]:
    """Content of each object (blob, or commit for a range scan), in one `git cat-file --batch` run. A missing object is an error, never an empty file."""
    wanted = sorted(o for o in oids if o != _ZERO_OID)
    if not wanted:
        return {}
    raw = _git(root, ["cat-file", "--batch"], stdin=("\n".join(wanted) + "\n").encode("ascii"))
    result: dict[str, bytes] = {}
    pos = 0
    for oid in wanted:
        nl = raw.find(b"\n", pos)
        header = raw[pos:nl].split(b" ") if nl >= 0 else []
        if len(header) != 3 or header[1] != kind.encode("ascii") or header[0].decode("ascii", "replace") != oid:
            raise ScannerError("a git object could not be read")
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


def _parse_allow(raw: bytes) -> set[tuple[str, str, str]]:
    """The exemption entries of a `.janitor-secret-allow` file as (kind, path, spec) keys.

    One entry per line, TAB separated: kind, path, `line:<sha256 of the line text>` or `blob:<git blob oid>`, and a non-empty
    reason. Blank lines and `#` lines are skipped. Any other line is malformed: exit 2 naming the line NUMBER only (fail
    closed, and the line could hold anything).

    RULE (main-agent ruling 2026-11-18, not an owner order): a `line:` entry is only for a value judged FAKE. A real secret is never exempted: rotate it,
    then rewrite the history. WHY an unsalted line hash is acceptable: an entry exists only for a line that is itself in a pushed
    blob, so the hash gives an attacker nothing the blob does not already hold. When that line is later removed from history,
    its entry must be removed too. The list file is scanned like any other file.
    """
    keys: set[tuple[str, str, str]] = set()
    for n, line in enumerate(raw.decode("utf-8", "replace").split("\n"), 1):
        line = line.rstrip("\r")
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        what, _, digest = parts[2].partition(":") if len(parts) == 4 else ("", "", "")
        sized = (what == "line" and len(digest) == 64) or (what == "blob" and len(digest) in (40, 64))
        if len(parts) != 4 or not all(p.strip() for p in parts) or not sized or set(digest) - _HEX:
            raise ScannerError(f"{_ALLOW_FILE} line {n} is malformed")
        keys.add((parts[0], parts[1], parts[2]))
    return keys


def _load_allow(root: Path, tree_ish: str | None) -> set[tuple[str, str, str]]:
    """The exemption list as committed in `tree_ish`, or in the INDEX when None; empty when there is none.

    Never the working tree: an uncommitted list exempts nothing, so the list that clears a finding is itself reviewed history.
    """
    if tree_ish is None:
        out = _git(root, ["ls-files", "--stage", "--", _ALLOW_FILE]).split()
        oid = out[1].decode("ascii", "replace") if len(out) >= 2 else None
    else:
        out = _git(root, ["ls-tree", tree_ish, "--", _ALLOW_FILE]).split()
        oid = out[2].decode("ascii", "replace") if len(out) >= 3 else None
    return _parse_allow(_read_blobs(root, {oid})[oid]) if oid else set()


def _base_allow(root: Path, rev: str | None) -> set[tuple[str, str, str]]:
    """The list at the base of the scan, only to tell which exemptions are new. Missing, unreadable or malformed counts as empty: that can only make the disclosure larger."""
    if rev is None:
        return set()
    try:
        return _load_allow(root, rev)
    except ScannerError:
        return set()


def _scan_blobs(
    root: Path,
    blobs: list[StagedBlob],
    extra: dict[str, bytes],
    allow: set[tuple[str, str, str]],
    base_allow: set[tuple[str, str, str]],
    shown: Callable[[str], str] = lambda p: p,
) -> ScanResult:
    """Scan `blobs` (their `path` is the path in the scan tree) plus `extra` files (any finding blocks, never exemptable).

    A file finding does not block when its whole line text is in the parent blob (pre-existing) or when `allow` has an entry
    for its kind and path with `line:<sha256 of that line>` or `blob:<oid>` (a finding with no line number only matches a
    blob entry). `shown` maps a tree path to the repo path the entries are written with.
    """
    if not blobs and not extra:
        return ScanResult([])
    contents = _read_blobs(root, {b.new_oid for b in blobs})
    # symlink blobs are written as regular files holding the link target text: scanned, never followed.
    found = _scan_tree({**{b.path: contents[b.new_oid] for b in blobs}, **extra})
    if not found:
        return ScanResult([])
    by_path = {b.path: b for b in blobs}
    baseline = _read_blobs(root, {by_path[f.path].old_oid for f in found if f.path in by_path})
    new: list[Finding] = []
    entries: list[str] = []
    old = exempted = exempted_new = 0
    parent_lines: dict[str, set[bytes]] = {}
    for f in found:
        blob = by_path.get(f.path)
        if blob is None:
            new.append(f)
            continue
        staged = _lines(contents[blob.new_oid])
        text = staged[f.line - 1] if f.line is not None and 0 < f.line <= len(staged) else None
        if blob.old_oid not in parent_lines:
            parent_lines[blob.old_oid] = set(_lines(baseline.get(blob.old_oid, b"")))
        if text is not None and text in parent_lines[blob.old_oid]:
            old += 1
            continue
        keys = [(f.kind, shown(f.path), f"blob:{blob.new_oid}")]
        if text is not None:
            keys.append((f.kind, shown(f.path), f"line:{hashlib.sha256(text).hexdigest()}"))
        hit = [k for k in keys if k in allow]
        if hit:
            exempted += 1
            exempted_new += not any(k in base_allow for k in hit)
            continue
        new.append(f)
        entries.append("\t".join((*keys[-1], "REVIEW-ME")))
    return ScanResult(new, old, exempted, exempted_new, tuple(entries))


def _name_in_range(f: Finding) -> Finding:
    """A finding in the range tree (`<sha>/f/<path>` or `<sha>/.message`) as `<short sha>:<path>` or `<short sha>:commit message`."""
    sha, _, rest = f.path.partition("/")
    name = _MESSAGE_LABEL if rest == ".message" else rest.removeprefix("f/")
    return Finding(f"{sha[:12]}:{name}", f.line, f.kind)


def scan_index(root: Path) -> ScanResult:
    """Scan the staged blobs. The exemption list is the INDEX version of `.janitor-secret-allow`; its base is the one at HEAD."""
    return _scan_blobs(root, _staged_blobs(root), {}, _load_allow(root, None), _base_allow(root, "HEAD"))


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


def scan_range(root: Path, rev_args: list[str]) -> ScanResult:
    """Scan every commit of `git rev-list <rev_args>`: its message and every blob it adds or changes against its FIRST parent.

    WHY a range scan: the commit-time hooks miss commits made elsewhere (cherry-pick, rebase picks and `commit --no-verify`
    skip pre-commit and commit-msg; a fast-forward merge or pull runs no blocking hook; `am` skips them unless
    pre-applypatch is installed), so every commit that leaves the machine or that git-cliff reads is scanned as a range.
    A root commit has no baseline; a merge is compared with its first parent. One temp tree holds the whole range, laid out
    as <sha>/f/<path> (files, under f/ so a repo file named `.message` cannot collide) and <sha>/.message, so one scan run
    covers it. The stored message is scanned whole: it is exactly what git-cliff reads, so no scissors cut.
    Findings are named `<short sha>:<path>` or `<short sha>:commit message`; a value is never part of one.
    The exemption list is the one COMMITTED at the tip of the range (the listed commit no other listed commit has as a
    parent), so a list that is not in the scanned history exempts nothing; its base is the list at the commit just below the range.
    """
    for arg in rev_args:
        if arg.startswith("-") and arg not in _RANGE_FLAGS:
            raise ScannerError("a range argument is not a revision")
    # The trailing `--` ends the revisions: a ref that is also a file name is not ambiguous.
    listing = _git(root, ["rev-list", "--parents", *rev_args, "--"]).decode("ascii").splitlines()
    commits = [ln.split() for ln in listing if ln.strip()]
    if not commits:
        return ScanResult([])
    blobs: list[StagedBlob] = []
    for sha, *parents in commits:
        diff_cmd = ("diff-tree", "-r", parents[0], sha) if parents else ("diff-tree", "--root", "--no-commit-id", "-r", sha)
        blobs += [b._replace(path=f"{sha}/f/{b.path}") for b in _staged_blobs(root, diff_cmd)]
    objects = _read_blobs(root, {c[0] for c in commits}, "commit")
    # The message follows the first blank line of the commit object; a gpgsig header continues on lines that start with a space.
    messages = {f"{sha}/.message": objects[sha].partition(b"\n\n")[2] for sha, *_ in commits}
    listed = {c[0] for c in commits}
    parent_of = {p for c in commits for p in c[1:]}
    tip = next(c[0] for c in commits if c[0] not in parent_of)
    below = next((p for c in commits for p in c[1:] if p not in listed), None)
    res = _scan_blobs(root, blobs, messages, _load_allow(root, tip), _base_allow(root, below), lambda key: key.partition("/f/")[2])
    return res._replace(findings=[_name_in_range(f) for f in res.findings])


def _report(findings: list[Finding], pre_existing: int, *, in_range: bool = False) -> None:
    if in_range:
        print("BLOCKED: secret in a commit about to leave this machine or be read by git-cliff (commit, file, line and kind only; the value is never printed):")
    else:
        print("BLOCKED: secret in what this commit would contain (file, line and kind only; the value is never printed):")
    for f in findings:
        print(f"  {f.path}:{f.line if f.line is not None else '?'}  [{f.kind}]")
    if pre_existing:
        print(f"  · {pre_existing} pre-existing finding(s) already in the parent, not blocking" if in_range else f"  · {pre_existing} pre-existing finding(s) already at HEAD, not blocking")
    if in_range:
        print("Rewrite the named commit(s) so no secret remains in any of them (and rotate it if it is real), then try again.")
    else:
        print("Remove the secret from the file or the message (and rotate it if it is real), then commit again.")


def _disclose_exemptions(res: ScanResult) -> None:
    """On stderr, never a value: how many file findings the committed exemption list cleared, and how many of those only by entries new since the base."""
    if res.exempted:
        print(f"· {res.exempted} finding(s) exempted by {_ALLOW_FILE}", file=sys.stderr)
        print(f"· {res.exempted_new} of them by entries not present at the base", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    reason = _inert_reason()
    if reason is not None:
        print(f"staged-secret-scan: inert — {reason}")
        return 0
    print_entries = _PRINT_ENTRIES in args
    args = [a for a in args if a != _PRINT_ENTRIES]
    in_range = args[:1] == ["--range"]
    try:
        if args[:1] == ["--message-file"] and len(args) == 2 and not print_entries:
            res = ScanResult(scan_message(Path(args[1])))
        elif in_range and len(args) >= 2:
            res = scan_range(_repo_root(), args[1:])
        elif not args:
            res = scan_index(_repo_root())
        else:
            raise ScannerError(f"usage: staged_secret_scan.py [{_PRINT_ENTRIES}] [--range <rev-list args>] | --message-file PATH")
    except (ScannerError, transcript_redact.RedactionUnavailable) as exc:
        print(f"BLOCKED: the secret scan could not run — {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 - fail closed; the type name only, the message could quote file text
        print(f"BLOCKED: the secret scan stopped on an internal error ({type(exc).__name__})")
        return 2
    if print_entries:
        # Helper for writing the list: one ready line per blocking FILE finding, reason REVIEW-ME to be replaced by the reviewer.
        # It never writes the list and never prints a value; a finding in a commit message cannot be exempted, so it gets no entry.
        for entry in dict.fromkeys(res.entries):
            print(entry)
        return 1 if res.entries else 0
    _disclose_exemptions(res)
    if res.findings:
        _report(res.findings, res.pre_existing, in_range=in_range)
        return 1
    if res.pre_existing:
        where = "in the parent" if in_range else "at HEAD"
        print(f"clean · {res.pre_existing} pre-existing finding(s) already {where}, not blocking")
    return 0


if __name__ == "__main__":
    sys.exit(main())
