#!/usr/bin/env python3
"""Install the janitor secret shield as a chained git pre-commit hook (TRDD-NYKNE7MY).

    shield_hook.py install   [--repo DIR] [--data-dir DIR] [--plugin-root DIR]
    shield_hook.py uninstall [--repo DIR]
    shield_hook.py status    [--repo DIR] [--data-dir DIR]
    shield_hook.py scan-staged --plugin-root DIR      (what the installed hook runs)

The hook scans the STAGED blobs of the commit (the index, not the working tree) with the
scripts/shield_scan/scan.ts scanner and blocks the commit on any finding. It never prints a secret
value: a finding line is `rule path:line` only.

Chaining: an existing pre-commit is renamed to pre-commit.pre-janitor (a rename, so byte for byte and
mode kept) and the new pre-commit runs it first and honours its exit code. Uninstall renames it back.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

from arm_prepare import install_stub, resolve_data_dir  # noqa: E402
from exe_path import exe  # noqa: E402

MARKER = "# janitor-shield-hook: installed by /janitor-secrets-shield-scan --install-hook, remove with --uninstall-hook"
HOOK = "pre-commit"
CHAINED = "pre-commit.pre-janitor"
STUB_NAME = "shield-hook-stub.py"
BUN_INSTALL = "brew install oven-sh/bun/bun"
UPDATE_JANITOR = "claude plugin update ai-maestro-janitor@ai-maestro-plugins --scope user"
GIT_TIMEOUT_S = 60
SCAN_TIMEOUT_S = 3600


class HookError(Exception):
    """A refusal that is shown to the user verbatim and ends the command with exit 1."""


# -- git plumbing -------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git -C repo with the caller environment (a hook run needs GIT_DIR and GIT_INDEX_FILE kept)."""
    # Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes .git/index.lock and collides with the commit in flight (janitor#245).
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run([exe("git"), "-C", str(repo), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=False, env=env)


def hooks_dir(repo: Path) -> Path:
    """The EFFECTIVE hooks folder: honours core.hooksPath, and in a linked worktree is the shared one."""
    done = _git(repo, "rev-parse", "--path-format=absolute", "--git-path", "hooks")
    if done.returncode != 0:
        raise HookError(f"{repo} is not inside a git repository: {done.stderr.strip()}")
    return Path(done.stdout.strip())


def _tracked(directory: Path) -> bool:
    """True when git tracks any file in the folder. Asked from inside the folder, so a core.hooksPath
    that points into another repository is judged by that repository, not by a path prefix."""
    if not directory.is_dir():
        return False
    # WHY the work-tree check first: inside a .git folder (the default hooks folder) git is not in any work
    # tree and `ls-files -- .` lists the WHOLE index, which would read as tracked hooks.
    inside = _git(directory, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return False
    done = _git(directory, "ls-files", "--", ".")
    return done.returncode == 0 and bool(done.stdout.strip())


# -- hook text ----------------------------------------------------------------


def hook_text(stub: Path, plugin_root: Path | None) -> str:
    """The sh text of the installed pre-commit. The stub path is baked in (absolute, quoted)."""
    pin = f" --plugin-root {shlex.quote(str(plugin_root))}" if plugin_root else ""
    stub_q = shlex.quote(str(stub))
    chained = "$hook_dir/" + CHAINED
    # WHY the stub and python3 checks live in the sh text: a missing stub or python3 must not turn into a
    # silent pass, nor into a bare "command not found"; the committer gets the tool, the command, the next step.
    return (
        "#!/bin/sh\n"
        f"{MARKER}\n"
        "hook_dir=$(dirname \"$0\")\n"
        f"if [ -x \"{chained}\" ]; then\n"
        f"  \"{chained}\" \"$@\" || exit $?\n"
        "fi\n"
        f"if [ ! -x {stub_q} ]; then\n"
        f"  echo \"janitor shield pre-commit: commit REFUSED, the stub {stub} is missing.\" >&2\n"
        "  echo \"  install it:  /janitor-secrets-shield-scan --install-hook   (run in Claude Code, in this repository)\" >&2\n"
        "  echo \"  then proceed: run the same git commit again.\" >&2\n"
        "  exit 1\n"
        "fi\n"
        "if ! command -v python3 >/dev/null 2>&1; then\n"
        "  echo \"janitor shield pre-commit: commit REFUSED, python3 is not on PATH.\" >&2\n"
        "  echo \"  install it:  brew install python\" >&2\n"
        "  echo \"  then proceed: run the same git commit again.\" >&2\n"
        "  exit 1\n"
        "fi\n"
        f"exec {stub_q}{pin}\n"
    )


def _is_ours(path: Path) -> bool:
    """True when the file is a regular file carrying the marker line."""
    try:
        return path.is_file() and not path.is_symlink() and MARKER in path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False


# -- install / uninstall / status ---------------------------------------------


def cmd_install(repo: Path, data_dir: Path, plugin_root: Path, pin: bool) -> int:
    """Install the chained hook; idempotent; refuses a tracked hooks folder and a hook it cannot chain."""
    target = hooks_dir(repo)
    stub = install_stub(plugin_root, data_dir, STUB_NAME)
    if not pin and not (data_dir / "dispatcher-stub.py").is_file():
        # Only when absent: that file is the heartbeat cron entry point, and an install of this hook must not overwrite (or downgrade) it.
        # The stub verifies the cached version with dispatcher-stub.py routines, loaded from beside it.
        install_stub(plugin_root, data_dir)
    if _tracked(target):
        # WHY refuse: a tracked hooks folder (husky style) belongs to the project, and writing there
        # edits the project tree for every cloner. The owner adds the line by hand instead.
        line = shlex.quote(str(stub)) + (f" --plugin-root {shlex.quote(str(plugin_root))}" if pin else "")
        print(f"refused: the hooks folder {target} holds git-tracked files; nothing was written there.")
        print(f"add this line to {target}/{HOOK}, after the existing checks, to run the shield on staged content:")
        print(f"  {line} || exit $?")
        return 1
    hook = target / HOOK
    chained = target / CHAINED
    if hook.is_symlink() or (hook.exists() and not hook.is_file()):
        raise HookError(f"refused: {hook} is a symlink or not a regular file, so it cannot be chained safely; nothing was changed.")
    ours = _is_ours(hook)
    if hook.exists() and not ours and chained.exists():
        # WHY refuse: renaming would overwrite the saved original, losing it for good.
        raise HookError(f"refused: {hook} exists and so does {chained}; chaining would overwrite {chained}. Resolve by hand; nothing was changed.")
    target.mkdir(parents=True, exist_ok=True)
    tmp = target / f".{HOOK}.janitor-tmp.{os.getpid()}"
    tmp.write_text(hook_text(stub, plugin_root if pin else None), encoding="utf-8")
    tmp.chmod(0o755)
    try:
        if hook.exists() and not ours:
            os.rename(hook, chained)  # a rename keeps the original bytes and mode exactly
        os.replace(tmp, hook)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"installed: {hook} (stub {stub})" + (f"; chained the existing hook as {chained}" if chained.exists() else ""))
    return 0


def cmd_uninstall(repo: Path) -> int:
    """Remove the janitor hook and put the original back under its own name, byte for byte."""
    target = hooks_dir(repo)
    hook = target / HOOK
    chained = target / CHAINED
    if not _is_ours(hook):
        raise HookError(f"refused: {hook} was not installed by the janitor (no marker line); nothing was changed.")
    hook.unlink()
    if chained.exists():
        os.rename(chained, hook)
    print(f"uninstalled: {hook}" + (" (original hook restored)" if hook.exists() else ""))
    return 0


def cmd_status(repo: Path, data_dir: Path) -> int:
    """Print the state as key=value lines."""
    target = hooks_dir(repo)
    yes_no = {True: "yes", False: "no"}
    print(f"hooks-dir={target}")
    print(f"installed={yes_no[_is_ours(target / HOOK)]}")
    print(f"chained={yes_no[(target / CHAINED).exists()]}")
    print(f"tracked-hooks-dir={yes_no[_tracked(target)]}")
    print(f"stub={yes_no[(data_dir / STUB_NAME).is_file()]}")
    return 0


# -- scan-staged (run by the hook) --------------------------------------------


def _staged(repo: Path) -> list[tuple[str, str]]:
    """(index blob sha, path) of every staged added/copied/modified file, from the live index (GIT_INDEX_FILE honoured)."""
    # GIT_OPTIONAL_LOCKS=0: the commit that runs this hook holds the index lock (janitor#245); GIT_INDEX_FILE etc. stay inherited.
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    done = subprocess.run(
        [exe("git"), "diff", "--cached", "--raw", "-z", "--no-renames", "--no-abbrev", "--diff-filter=ACM"],
        cwd=repo,
        capture_output=True,
        timeout=GIT_TIMEOUT_S,
        check=False,
        env=env,
    )
    if done.returncode != 0:
        raise HookError("git diff --cached failed, so the staged content cannot be listed")
    fields = done.stdout.decode("utf-8", "surrogateescape").split("\0")
    out: list[tuple[str, str]] = []
    for i in range(0, len(fields) - 1, 2):
        meta, path = fields[i].split(), fields[i + 1]
        if meta[1] == "160000":  # a submodule pointer has no blob to scan
            continue
        out.append((meta[3], path))
    return out


def _export(repo: Path, items: list[tuple[str, str]], dest: Path) -> None:
    """Write each staged blob (raw index content, no smudge filter) under dest at its repository path."""
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"  # janitor#245: read-only, never contend for the index lock
    proc = subprocess.Popen([exe("git"), "cat-file", "--batch"], cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    if proc.stdin is None or proc.stdout is None:
        raise HookError("git cat-file --batch started without pipes")
    try:
        for sha, path in items:
            proc.stdin.write(sha.encode() + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            if len(header) != 3 or header[1] != b"blob":
                raise HookError(f"git could not read the staged blob of {path}")
            data = proc.stdout.read(int(header[2]))
            proc.stdout.read(1)  # the newline after the content
            file = dest / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
    finally:
        proc.stdin.close()
        proc.wait(timeout=GIT_TIMEOUT_S)


def cmd_scan_staged(plugin_root: Path) -> int:
    """Scan the staged blobs; 0 clean, 1 blocked (a finding, or the scan could not complete)."""
    scanner = plugin_root / "scripts" / "shield_scan" / "scan.ts"
    bun = shutil.which("bun")
    # WHY fail closed, and WHY each message carries install + proceed: this gate will sit in many repos;
    # a bare "scanner missing" leaves the committer stuck, and a silent pass defeats the gate.
    if bun is None:
        raise HookError(f"commit REFUSED, bun is not on PATH.\n  install it:  {BUN_INSTALL}\n  then proceed: run the same `git commit` again.")
    if not scanner.is_file():
        raise HookError(f"commit REFUSED, the shield scanner is missing ({scanner}).\n  install it:  {UPDATE_JANITOR}\n  then proceed: run the same `git commit` again.")
    repo = Path.cwd()
    items = _staged(repo)
    if not items:
        return 0
    # GIT_* must not reach the scanner: its git-top detection would take GIT_DIR for the export folder.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    work = Path(tempfile.mkdtemp(prefix="janitor-shield-"))  # mkdtemp is 0700
    try:
        export = work / "staged"
        export.mkdir()
        _export(repo, items, export)
        out = work / "findings.jsonl"
        # --all: hidden files (.env) are in scope; the export folder has no .gitignore to honour anyway.
        done = subprocess.run(
            [bun, "--cwd", str(plugin_root), str(scanner), "--all", "--out", str(out), str(export)],
            capture_output=True,
            text=True,
            timeout=SCAN_TIMEOUT_S,
            check=False,
            env=env,
        )
        findings = []
        if out.exists():
            for raw in out.read_text(encoding="utf-8").splitlines():
                rec = json.loads(raw)
                if rec.get("type") == "finding":
                    findings.append(rec)
        if done.returncode == 0:
            return 0
        if done.returncode == 1 and findings:
            sys.stderr.write("janitor shield pre-commit: commit REFUSED, secrets found in the staged content (values are never printed):\n")
            for rec in findings:
                line = rec.get("line")
                where = f":{line}" if line else ""
                kind, rel = rec["kind"], rec["path"]
                sys.stderr.write(f"  {kind} {rel}{where}\n")
            sys.stderr.write("  unstage the file or remove the secret, then run `git commit` again.\n")
            return 1
        sys.stderr.write(f"janitor shield pre-commit: commit REFUSED, the scan did not complete (exit {done.returncode}); a gate that cannot scan blocks.\n")
        if done.stderr.strip():
            sys.stderr.write(f"  scanner said: {done.stderr.strip()}\n")
        sys.stderr.write("  then proceed: fix the cause named above and run the same `git commit` again.\n")
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    """CLI entry; a HookError prints its text on stderr and exits 1."""
    ap = argparse.ArgumentParser(prog="shield_hook")
    ap.add_argument("command", choices=["install", "uninstall", "status", "scan-staged"])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--data-dir", default="")
    ap.add_argument("--plugin-root", default="")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    data_dir = Path(args.data_dir) if args.data_dir else resolve_data_dir()
    plugin_root = Path(args.plugin_root) if args.plugin_root else _HERE.parent
    try:
        if args.command == "install":
            # An explicit --plugin-root pins the hook to that folder (a plugin update then needs a reinstall); the default does not.
            return cmd_install(repo, data_dir, plugin_root, pin=bool(args.plugin_root))
        if args.command == "uninstall":
            return cmd_uninstall(repo)
        if args.command == "status":
            return cmd_status(repo, data_dir)
        return cmd_scan_staged(plugin_root)
    except HookError as err:
        sys.stderr.write(f"shield-hook: {err}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
