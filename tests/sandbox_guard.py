"""The write sandbox — enforced in the pytest process AND inside every CHILD process.

This is the BLOCKING layer (S1e/S1g). The suite already has a DETECTING layer (the
sessionfinish manifest guard), but detection tells you the damage happened; this makes the
write fail. It exists because on 2026-07-11 an unsandboxed keepalive restage overwrote this
repo's `scripts/**` with the released v0.39.0 — silently reverting committed work and
clearing exec bits (TRDD-RYZCVVKA).

WHY THIS IS A MODULE AND NOT JUST CONFTEST CODE (S1g — the hole the first version left):
patching `open`/`os.replace`/`shutil.rmtree` protects only the process that did the
patching. A test that spawns a CHILD (`subprocess.run([sys.executable, "daemon.py"])`) hands
that child a completely unpatched interpreter, free to write anywhere. That is not
hypothetical — it is the exact shape of the incident (something ran
`daemon_keepalive_entry.py`, whose boot gate staged the cached plugin over this repo), and it
was proven live on 2026-07-11 when the running daemon wrote the real plugin-data dir mid-suite
and the in-process sandbox never saw it.

So the guard lives here, importable, and `tests/_sandbox_boot/sitecustomize.py` installs it in
EVERY child Python at interpreter startup (Python auto-imports `sitecustomize` if it is on the
path; conftest puts it there and passes the protected roots through the environment). One rule,
one implementation, enforced everywhere.

Reads are never blocked. Only writes into a protected root raise.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import re
import shlex
import shutil
from pathlib import Path
from typing import NamedTuple

#: Protected roots are passed to children through the environment (os.pathsep-joined), so a
#: child enforces the SAME roots the parent computed — including the REAL home, which the
#: child can no longer derive itself once HOME has been redirected into a tmp tree.
ENV_DENY = "JANITOR_TEST_SANDBOX_DENY"

#: AUDIT MODE (Phase 0 of the process sandbox). When set to a path, every process spawn is
#: LOGGED there and NOTHING is denied. This exists to build the allow-list from REALITY: the
#: suite's true subprocess surface is a fact to be measured, not guessed. Guessing it would
#: either break dozens of tests (too strict) or leave a dangerous binary un-denied (too loose).
#: Unset ⇒ audit is off and the process guard enforces (deny-by-default).
ENV_AUDIT = "JANITOR_TEST_SANDBOX_AUDIT"

#: The `@pytest.mark.real_subprocess(...)` escape hatch, published per-test. A comma-list of
#: binary basenames, or "*" for all. Deliberate friction: a real call to a dangerous binary is
#: then VISIBLE in the test's source and in review, instead of being an invisible default.
ENV_ALLOW_REAL = "JANITOR_TEST_SANDBOX_ALLOW_REAL"

#: Where to log DENIED spawns. Enforcement is on regardless; this only makes it observable —
#: see `record_denial` for why a green suite alone proves nothing.
ENV_DENYLOG = "JANITOR_TEST_SANDBOX_DENYLOG"

#: The REAL os primitives, bound at import — BEFORE `install()` wraps `os.open`. The audit
#: writer must use these: routing its own bookkeeping through the patched syscalls would
#: recurse through the very guard it is reporting on.
_REAL_OS_OPEN = os.open
_REAL_OS_WRITE = os.write
_REAL_OS_CLOSE = os.close

#: Python writes import bytecode into the source tree on every run; that is the interpreter,
#: not a test escaping its boundary.
ALLOW_PARTS = ("__pycache__", ".pytest_cache")

_PATCHED: list[tuple[object, str, object]] = []


class SandboxViolation(RuntimeError):
    """A write was attempted OUTSIDE the caller's boundary — into real machine state or the repo source."""


def deny_roots_from_env() -> tuple[Path, ...]:
    """The protected roots this process must enforce, as published by the parent. Empty ⇒ the
    sandbox is not active (so an unrelated Python that merely inherits PYTHONPATH is untouched)."""
    raw = os.environ.get(ENV_DENY, "")
    return tuple(Path(p) for p in raw.split(os.pathsep) if p)


def publish_roots(roots: tuple[Path, ...]) -> None:
    """Publish `roots` into the environment so every descendant process enforces them too."""
    os.environ[ENV_DENY] = os.pathsep.join(str(r) for r in roots)


def _fd_relative(kwargs: dict) -> bool:
    """True when a syscall's path is relative to a `dir_fd`, not to the cwd.

    `shutil.rmtree` (hence `TemporaryDirectory` cleanup) walks with
    `os.rmdir("design", dir_fd=<fd of the tmp dir>)` — a BARE relative name plus an open
    directory fd. Resolving that name against the cwd is simply wrong: it made a tmp-dir
    cleanup look like an attack on the REAL repo's design/ and failed 68 innocent tests. We
    cannot portably resolve an fd-relative name, so we skip it here — `shutil.rmtree` is
    guarded at its entry point instead, which is what actually bounds the recursive delete.
    """
    return kwargs.get("dir_fd") is not None


def check(path: object, op: str, deny: tuple[Path, ...]) -> None:
    """Raise unless `path` is outside every protected root. Reads are never routed here."""
    if not isinstance(path, (str, bytes, os.PathLike)):
        return  # an int fd — no path to police
    try:
        raw = os.fsdecode(path) if isinstance(path, bytes) else str(path)
        target = Path(os.path.abspath(raw))
    except (ValueError, TypeError):
        return
    if any(part in ALLOW_PARTS for part in target.parts):
        return
    for root in deny:
        if target == root or root in target.parents:
            raise SandboxViolation(
                f"BLOCKED {op}() -> {target}\n"
                f"This process may not write outside its own tmp boundary. The path is inside "
                f"the protected root {root}.\n"
                f"Real machine state and this repo's source are OFF LIMITS to the suite (and to "
                f"anything it spawns): on 2026-07-11 an unsandboxed keepalive restage overwrote "
                f"scripts/** with the released v0.39.0, reverting committed work (TRDD-RYZCVVKA).\n"
                f"Fix the TEST: write to `tmp_path`, and route janitor paths through the isolated "
                f"HOME / JANITOR_DATA_DIR / JANITOR_GLOBAL_STATE_DIR env."
            )


def _audit_target() -> str:
    """The audit-log path, or "" when audit mode is off. Read from the env EVERY call so a
    child process (which only inherits the env, never our globals) honours it too."""
    return os.environ.get(ENV_AUDIT, "").strip()


def _argv_of(args: object) -> list[str]:
    """Normalise Popen's polymorphic `args` (a str under shell=True, else a sequence) into a
    plain list of str. PURE — the classifier and the audit log share this one shape."""
    if isinstance(args, (str, bytes)):
        return [os.fsdecode(args) if isinstance(args, bytes) else args]
    if isinstance(args, (list, tuple)):
        return [os.fsdecode(a) if isinstance(a, bytes) else str(a) for a in args]
    return [str(args)]


def record_spawn(argv: list[str], *, cwd: str, shell: bool) -> None:
    """Append one JSON line describing a process spawn to the audit log. No-op when audit mode
    is off.

    `cwd` is the EFFECTIVE working directory (Popen's `cwd=` kwarg when given, else the
    process's own) — NOT `os.getcwd()`. The first audit pass logged `os.getcwd()` and so
    reported all ~400 tmp-repo `git commit`/`git init` calls as running in the REAL repo,
    because pytest's cwd IS the repo and the tests pass `cwd=tmp_path`. That misread is the
    whole ballgame for git: the effective cwd is precisely what separates a harmless tmp-repo
    mutation from one that rewrites this repo's history.

    Uses the REAL `os.open/write/close` captured at import (not the patched ones) and O_APPEND,
    so: (a) it cannot recurse through the file guard it lives beside, and (b) concurrent
    children — the suite spawns many — interleave safely instead of clobbering each other
    (a single <PIPE_BUF O_APPEND write is atomic on POSIX).

    NEVER raises: an audit failure must not change the outcome of the run it is only observing.
    """
    path = _audit_target()
    if not path:
        return
    try:
        line = json.dumps(
            {
                "argv": argv,
                "cwd": cwd,
                "shell": shell,
                # pytest publishes the running test id here; a child process inherits it, so a
                # spawn deep inside a subprocess still attributes back to the test that caused it.
                "test": os.environ.get("PYTEST_CURRENT_TEST", ""),
                "pid": os.getpid(),
            },
            ensure_ascii=False,
        ) + "\n"
        fd = _REAL_OS_OPEN(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            _REAL_OS_WRITE(fd, line.encode("utf-8", "replace"))
        finally:
            _REAL_OS_CLOSE(fd)
    except Exception:  # noqa: BLE001 — observation must never break the observed
        pass


# ══════════════ THE PROCESS + SIGNAL SURFACE — an ALLOW-LIST, deny by default ══════════════
#
# The file guards above see only PYTHON-level writes. Every genuinely dangerous janitor
# capability is a SUBPROCESS or a SIGNAL, and is therefore invisible to them:
#
#   real keychain          `security …`          real OS service   `launchctl …`
#   type into a terminal   `osascript` / `tmux`  real plugin tree  `claude plugin update`
#   real GitHub mutation   `gh api --method POST` kill a real pid  os.kill(<real pid>)
#
# A BLOCK-list here would be the same design that has been one incident behind all along:
# it can only forbid the binaries someone already thought of. So this is an ALLOW-list —
# a binary nobody has considered yet is DENIED, and the denial names the fix.
#
# The allow-table is built from a MEASURED audit of the real suite (2631 spawns, 68 binaries),
# not from a guess. Guessing would have been either too strict (breaking dozens of tests) or
# too loose (leaving a dangerous binary un-denied) — and the audit found five real escapes no
# amount of guessing would have produced.


class Verdict(NamedTuple):
    allowed: bool
    reason: str


_ALLOW = Verdict(True, "")

#: pids this process spawned. The signal guard permits killing ONLY these — a test may kill
#: its OWN child (test_kill_process_terminates_real_child does exactly that, legitimately),
#: but may never signal a process it did not create. `memory_guard.select_victim()` reads the
#: REAL `ps` table and therefore returns a REAL pid; `global_state.request_daemon_restart()`
#: SIGTERMs the REAL daemon. Both are one forgotten monkeypatch away from killing a live user
#: process, which no file guard could ever have seen.
_SPAWNED_PIDS: set[int] = set()

#: A shell is NOT sandboxed: `sitecustomize` reaches every child PYTHON, but a shell's own
#: children (e.g. the `launchctl` inside keepalive_install.sh) are invisible to us. So a shell
#: is allowed only when it cannot execute anything real — see `_classify_shell`.
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})

#: Shell builtins that cannot touch machine state.
_SHELL_BUILTINS = frozenset({"echo", "exit", "true", "false", ":", "cd", "printf"})

#: Wrappers that RUN ANOTHER COMMAND. They must be unwrapped and the INNER command classified,
#: or they are a trivial one-token bypass of the entire guard: the daemon really does spawn
#: `taskpolicy -b claude plugin marketplace update`, so allowing `taskpolicy` by name would
#: have waved through the exact real-machine mutation this guard exists to stop.
_PREFIX_LAUNCHERS = frozenset({"taskpolicy", "nice", "ionice", "env", "stdbuf", "timeout"})

#: Pure OBSERVERS of the machine: they read state and cannot change it. Safe by nature, and
#: the suite genuinely needs them (memory_guard parses `ps`, disk_pressure parses `diskutil`).
_READONLY_TOOLS = frozenset({
    "ps", "lsof", "sw_vers", "vm_stat", "sysctl", "mount", "diskutil", "uname", "id",
    "whoami", "hostname", "df", "sleep", "echo", "true", "false", "date", "which", "printf",
    # `file` identifies a binary's format and cannot alter anything. It is here because
    # xdist's WORKER BOOTSTRAP calls it — `platform.platform()` -> `architecture()` ->
    # `file -b <python>` — which happens before any test exists, so neither the stub route
    # nor the `real_subprocess` marker the denial message offers can reach it: the guard
    # killed every worker at startup and the whole suite ran serially or not at all.
    # Allow-listing it is the narrowest fix that keeps the deny-by-default posture intact.
    "file",
})

#: git verbs that only READ. Anything else must prove it is operating on a tmp repo.
_GIT_READONLY_VERBS = frozenset({
    "status", "rev-parse", "log", "diff", "show", "cat-file", "ls-files", "ls-tree",
    "for-each-ref", "describe", "blame", "symbolic-ref", "var", "check-ignore", "merge-base",
    "name-rev", "rev-list", "shortlog", "count-objects", "version", "help", "check-attr",
    "ls-remote", "grep",
})

_SHELL_CHAIN = re.compile(r"\s*(?:;|&&|\|\||\|)\s*")
_PYTHON_EXE = re.compile(r"^python(\d+(\.\d+)*)?$")


def _tmp_roots() -> tuple[str, ...]:
    import tempfile

    raw = (tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
    return tuple({os.path.realpath(r) for r in raw} | set(raw))


def _under(path: str, root: str) -> bool:
    if not path or not root:
        return False
    p, r = os.path.realpath(path), os.path.realpath(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def is_tmp_path(path: str) -> bool:
    """True iff `path` lives in a temp tree — i.e. it is something the TEST created."""
    return any(_under(path, root) for root in _tmp_roots())


def resolve_exe(argv0: str, cwd: str, env: dict) -> str:
    """The REAL absolute path (symlinks followed) of the binary that will run, or "" when
    nothing exists to run.

    Resolution is the load-bearing step, and it is why the guard needs no per-stub special
    cases: the suite already fakes binaries by writing them into a tmp dir and prepending it
    to PATH (`spy-memgrep`, the fake `secret-tool`, the `*.sh` fixtures). Resolving argv[0]
    against the SPAWN's OWN PATH tells a stub apart from the real thing — `/tmp/.../bin/gh` is
    the test's own code and is allowed; `/opt/homebrew/bin/gh` is the user's machine and is not.

    Symlinks are followed ON PURPOSE, and ONLY for the containment question: a symlink sitting
    in tmp that points at the real `/opt/homebrew/bin/gh` must NOT read as "a test's own stub".
    The policy NAME, though, must come from what the caller INVOKED — never from this path —
    because following a symlink can RENAME the binary: Homebrew's coreutils makes `echo`
    resolve to `…/bin/gecho`, which turned three allow-listed tools into unknown binaries and
    denied them. Containment wants the real target; identity wants the invoked name.
    """
    if os.sep in argv0:
        candidate = os.path.join(cwd or os.getcwd(), argv0)
        return os.path.realpath(candidate) if os.path.exists(candidate) else ""
    found = shutil.which(argv0, path=env.get("PATH", os.defpath))
    return os.path.realpath(found) if found else ""


def _allow_real_names(env: dict) -> set[str]:
    """The binaries this test explicitly opted into via `@pytest.mark.real_subprocess(...)`."""
    return {n.strip() for n in env.get(ENV_ALLOW_REAL, "").split(",") if n.strip()}


def _unwrap_launcher(argv: list[str]) -> list[str]:
    """Strip a prefix launcher and its own flags, returning the command it will RUN."""
    rest = argv[1:]
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok.startswith("-") or tok.isdigit() or ("=" in tok and not tok.startswith(os.sep)):
            i += 1
            continue
        break
    return rest[i:]


def _is_python_spawn(name: str, argv0: str) -> bool:
    """True iff this spawn is a Python interpreter — including a repo script with a
    `#!/usr/bin/env -S uv run --script` shebang spawned BY PATH, which is how every detector
    and hook runs, and is Python by another name."""
    pythonish = bool(_PYTHON_EXE.match(name)) or name in {"uv", "uvx", "pytest", "py.test"}
    return pythonish or argv0.endswith(".py")


def _harden_child_env(argv: list[str], child_env: dict) -> dict:
    """Guarantee a child Python BOOTS THE SANDBOX, by handing it the env that installs it.

    A child Python is safe not because it is Python, but because `tests/_sandbox_boot/
    sitecustomize.py` re-installs this very guard inside it at startup — which happens only if
    the child inherits `PYTHONPATH` and the deny roots. A test that builds an explicit `env=`
    from scratch (47 of them do, to isolate the child's janitor paths) silently strips both,
    producing a completely UNGUARDED interpreter free to write anywhere. That is not a
    hypothetical — it is the exact shape of the 2026-07-11 source clobber (TRDD-RYZCVVKA),
    where an unsandboxed child restaged the released plugin over this repo's `scripts/**`.

    The first cut of this guard DENIED such a spawn. That was wrong twice over: it broke 47
    legitimate tests whose curated env IS their isolation, and it "protected" them by refusing
    to run rather than by making them safe. Injecting the two sandbox vars instead keeps every
    test's own env intact and UPGRADES the child from unguarded to guarded — the strictly
    better outcome, and it costs nothing.

    The test's own vars always win: we only ADD what is missing. A test that has explicitly
    opted out (`@pytest.mark.real_subprocess`) is left exactly as it wrote it, so the
    positive-control test which proves the sandbox is OPT-IN can still spawn a raw interpreter.
    """
    if not _is_python_spawn(os.path.basename(argv[0]), argv[0]):
        return child_env
    if _allow_real_names(dict(os.environ)):
        return child_env  # this test explicitly asked for an unmodified real spawn
    hardened = dict(child_env)
    for var in (ENV_DENY, "PYTHONPATH", ENV_AUDIT, ENV_ALLOW_REAL, ENV_DENYLOG):
        if var not in hardened and os.environ.get(var):
            hardened[var] = os.environ[var]
    return hardened


# The repo that CONTAINS the running suite — protected from git mutation REGARDLESS of where
# it lives. `is_tmp_path` alone cannot protect it: when the whole repo is checked out under a
# tmp tree (the standard cross-project flow clones contributions to /tmp), "the real repo" and
# "a throwaway fixture repo" are indistinguishable by path prefix, and the guard classified
# real history as mutable — which is precisely the incident class this module exists for
# (TRDD-RYZCVVKA overwrote committed work in THIS repo). Found because the suite's own
# test_git_may_not_mutate_the_real_repo FAILED from a /tmp clone: the test was right and the
# heuristic was leaky. Resolved (symlinks followed) so the /tmp vs /private/tmp macOS alias
# cannot split the comparison.
_SUITE_REPO = str(Path(__file__).resolve().parent.parent)


# Every classifier below takes the SAME `(argv, cwd, env)` shape because `classify_argv`
# dispatches them positionally out of `_ALLOW_TABLE` — so a parameter one classifier does not
# read is still structurally required. Those are spelled with a leading underscore: it keeps the
# uniform signature (which is what makes the table possible) while saying out loud that this
# classifier reaches its verdict WITHOUT that input, so a reader does not go looking for the use.
def _classify_git(argv: list[str], cwd: str, _env: dict) -> Verdict:
    """READ anywhere; MUTATE only inside a tmp repo — and NEVER the suite's own repo.

    `-C <dir>` retargets git independently of the cwd, so it must be honoured — otherwise
    `git -C <real repo> commit` reads as a harmless tmp operation.
    """
    target = cwd
    if "-C" in argv:
        target = os.path.join(cwd, argv[argv.index("-C") + 1])
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        # `-C <dir>` and `-c <name=value>` each consume a SEPARATE following token, so skip two;
        # otherwise `git -c core.pager=cat log` parses the verb as `core.pager=cat` and a
        # read-only `log` outside tmp is wrongly denied.
        i += 2 if argv[i] in ("-C", "-c") else 1
    verb = argv[i] if i < len(argv) else ""
    if verb in _GIT_READONLY_VERBS:
        return _ALLOW
    if _under(os.path.realpath(target), _SUITE_REPO):
        pass  # the suite's own repo: fall through to the DENY below, tmp-resident or not
    elif is_tmp_path(target):
        return _ALLOW  # a throwaway repo the test built for itself
    return Verdict(
        False,
        f"`git {verb}` would MUTATE a real repository at {target}.\n"
        f"Only READ-ONLY git verbs are allowed outside a tmp tree. Build the fixture repo in "
        f"`tmp_path` and pass `cwd=<that dir>` (or `-C <that dir>`) to the git call.",
    )


def _classify_security(argv: list[str], _cwd: str, _env: dict) -> Verdict:
    """`security` is allowed ONLY when confined to a throwaway keychain file in tmp.

    This turns the `keychain_scope_args()` CONVENTION into an enforced INVARIANT. An unscoped
    `security` op runs against the login keychain, where a write corrupts real credentials and
    a `-w` secret read raises the macOS ACL dialog — the prompt FLOOD that once locked the user
    out with hundreds of modals. The audit proved all 161 current calls are already scoped, so
    this costs nothing today; it is here so the 162nd cannot forget.
    """
    keychains = [a for a in argv[1:] if a.endswith((".keychain-db", ".keychain"))]
    if not keychains:
        return Verdict(
            False,
            "unscoped `security` call — it would target the user's REAL login keychain.\n"
            "Every keychain op must be confined to a throwaway keychain: use the "
            "`isolated_keychain` fixture (or the session-default `JANITOR_ROTATOR_KEYCHAIN`) "
            "and pass the keychain path as the trailing positional — that is exactly what "
            "`safe_storage.keychain_scope_args()` does.",
        )
    for kc in keychains:
        if not is_tmp_path(kc):
            return Verdict(
                False,
                f"`security` targets a keychain OUTSIDE any tmp tree: {kc}\n"
                f"Tests may only touch a throwaway keychain (see the `isolated_keychain` fixture).",
            )
    return _ALLOW


def _classify_touch(argv: list[str], cwd: str, _env: dict) -> Verdict:
    """`touch` writes files WITHOUT going through Python, so the file guard cannot see it.
    Allowed only when every path it names is in tmp."""
    paths = [a for a in argv[1:] if not a.startswith("-")]
    bad = [p for p in paths if not is_tmp_path(os.path.join(cwd, p))]
    if bad:
        return Verdict(False, f"`touch` would create a file outside tmp: {bad[0]}")
    return _ALLOW


def _classify_shell_string(script: str, cwd: str, env: dict) -> Verdict:
    """Classify each command in a `sh -c` string. Redirection and command substitution are
    refused outright: `>` writes a file behind the file guard's back, and `$(…)`/backticks can
    hide an arbitrary command from static inspection."""
    if any(tok in script for tok in ("`", "$(", ">", "<")):
        return Verdict(
            False,
            f"shell string uses redirection or command substitution — a write or a command "
            f"the guard cannot see: {script[:120]}",
        )
    for segment in _SHELL_CHAIN.split(script):
        segment = segment.strip()
        if not segment:
            continue
        try:
            tokens = shlex.split(segment)
        except ValueError:
            return Verdict(False, f"unparsable shell string: {segment[:120]}")
        if not tokens or tokens[0] in _SHELL_BUILTINS:
            continue
        verdict = classify_argv(tokens, cwd=cwd, env=env)
        if not verdict.allowed:
            return verdict
    return _ALLOW


def _classify_shell(argv: list[str], cwd: str, env: dict) -> Verdict:
    rest = argv[1:]
    if "-n" in rest:
        return _ALLOW  # `bash -n <file>` — parse-only; the shell never executes a command
    if "-c" in rest:
        idx = rest.index("-c")
        return _classify_shell_string(rest[idx + 1] if idx + 1 < len(rest) else "", cwd, env)
    scripts = [t for t in rest if not t.startswith("-")]
    # Same _SUITE_REPO carve-out as _classify_git, for the same reason: when the repo itself is
    # checked out under a tmp tree, its REAL scripts (keepalive_install.sh — the incident script)
    # satisfy is_tmp_path and would be classified as harmless test fixtures.
    if (
        scripts
        and is_tmp_path(os.path.join(cwd, scripts[0]))
        and not _under(os.path.realpath(os.path.join(cwd, scripts[0])), _SUITE_REPO)
    ):
        return _ALLOW  # a script the test itself wrote into tmp
    return Verdict(
        False,
        f"a shell script is NOT sandboxed — its own children (launchctl, security, …) are "
        f"invisible to this guard, so running a REAL script would silently escape it: "
        f"{' '.join(argv[:3])}\n"
        f"Use `bash -n <file>` to syntax-check, or write the script into `tmp_path` and run it "
        f"from there.",
    )


def _allow_always(_argv: list[str], _cwd: str, _env: dict) -> Verdict:
    return _ALLOW


#: basename -> predicate. ANYTHING NOT LISTED IS DENIED — that is the entire point.
_ALLOW_TABLE: dict[str, "object"] = {
    "git": _classify_git,
    "security": _classify_security,
    "touch": _classify_touch,
    # memgrep is OUR binary, built from this tree, and only ever pointed at a tmp corpus.
    # cargo builds it, writing solely into the gitignored scripts/memgrep/target/.
    "memgrep": _allow_always,
    "cargo": _allow_always,
    **{s: _classify_shell for s in _SHELLS},
    **{t: _allow_always for t in _READONLY_TOOLS},
}


def _deny_unknown(name: str, exe_path: str, argv: list[str]) -> str:
    return (
        f"BLOCKED spawn: `{name}`" + (f" ({exe_path})" if exe_path else " (not on PATH)") + "\n"
        f"  argv: {' '.join(argv[:8])}\n"
        f"`{name}` is not on the allow-list, so it is DENIED BY DEFAULT. The list is an "
        f"allow-list on purpose: a block-list can only forbid the binaries someone already "
        f"thought of, and every isolation layer this suite has ever had was one incident "
        f"behind for exactly that reason.\n"
        f"Fix the TEST — one of:\n"
        f"  * STUB it: write a fake `{name}` into `tmp_path/bin`, prepend that dir to PATH, and "
        f"pass the env to the call. A tmp-resolved binary is auto-allowed (the suite already "
        f"does this for memgrep and secret-tool). This is NOT a mock: the real code path runs, "
        f"only the machine-touching binary is a fixture.\n"
        f"  * or, if the REAL binary is genuinely required, opt in explicitly:\n"
        f"        @pytest.mark.real_subprocess(\"{name}\")\n"
        f"    That marker is deliberate friction — it makes a real machine-touching call "
        f"visible in code review instead of an invisible default."
    )


def classify_argv(argv: list[str], *, cwd: str, env: dict) -> Verdict:
    """PURE. Decide whether this spawn may proceed. No I/O beyond PATH/realpath resolution,
    so the whole policy is unit-testable without patching a thing."""
    if not argv or not argv[0]:
        return Verdict(False, "empty argv")

    exe_path = resolve_exe(argv[0], cwd, env)
    # IDENTITY comes from what the caller INVOKED, never from the resolved path — see resolve_exe.
    name = os.path.basename(argv[0])
    allow_real = _allow_real_names(env)
    if "*" in allow_real or name in allow_real:
        return _ALLOW  # @pytest.mark.real_subprocess — explicit, reviewable opt-in

    # Nothing to run. Exec of a non-existent file cannot touch the machine: Popen raises
    # FileNotFoundError, which is precisely what the "binary is missing" tests assert. Denying
    # here would replace a real, tested failure mode with a sandbox error and prove nothing.
    if not exe_path:
        return _ALLOW

    # A binary the TEST ITSELF wrote into tmp: its own code, at its own trust level. The test
    # body could do the same thing in Python, so denying its fixture scripts would buy no
    # safety and break ~20 tests. This is what makes "stub it on PATH" the universal fix.
    if is_tmp_path(exe_path):
        return _ALLOW

    # Unwrap BEFORE the table, or `taskpolicy -b <anything>` is a one-token bypass.
    if name in _PREFIX_LAUNCHERS:
        inner = _unwrap_launcher(argv)
        return classify_argv(inner, cwd=cwd, env=env) if inner else _ALLOW

    if _is_python_spawn(name, argv[0]):
        # A child Python boots this same guard — `_harden_child_env` (called in guarded_init
        # before we get here) injects ENV_DENY/PYTHONPATH into the child, and a child spawned
        # WITHOUT env= inherits them, so it is always guarded, never unguarded. (Every disjunct
        # of the old "unguarded python → deny" branch that followed this was a subset of
        # `_is_python_spawn`, so it was unreachable dead code and was removed.)
        return _ALLOW

    rule = _ALLOW_TABLE.get(name)
    if rule is None:
        return Verdict(False, _deny_unknown(name, exe_path, argv))
    return rule(argv, cwd, env)  # type: ignore[operator]


_PPID_CACHE: dict = {"at": 0.0, "table": {}}


def _ppid_table(*, refresh: bool) -> dict[int, int]:
    """`{pid: ppid}` for every process, from a `ps` SNAPSHOT.

    Snapshotting is not incidental: `pgrep -f` / `ps | grep` match the searching shell's own
    argv as a false positive, because they scan a table that already contains the scanner.
    """
    import time

    now = time.monotonic()
    if not refresh and _PPID_CACHE["table"] and now - _PPID_CACHE["at"] < 2.0:
        return _PPID_CACHE["table"]
    import subprocess

    table: dict[int, int] = {}
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:  # noqa: BLE001 — a guard that crashes is worse than one that denies
        return _PPID_CACHE["table"]
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                table[int(parts[0])] = int(parts[1])
            except ValueError:
                continue
    _PPID_CACHE.update(at=now, table=table)
    return table


def _walk_to_us(target: int, table: dict[int, int]) -> bool:
    me, cur, seen = os.getpid(), target, set()
    while cur > 1 and cur not in seen:
        seen.add(cur)
        if cur == me or cur in _SPAWNED_PIDS:
            return True
        parent = table.get(cur)
        if parent is None:
            return False
        cur = parent
    return False


def _descends_from_us(target: int) -> bool:
    """True iff `target` is a DESCENDANT of this test process.

    Tracking only the pids we get back from `Popen` is not enough, because the process a test
    means to signal is frequently its GRANDCHILD: the daemon is launched through `uv`, so the
    pid in `daemon.pid` is not the pid `Popen` returned; and `multiprocessing`'s spawn workers
    are created by `_posixsubprocess.fork_exec`, which never passes through `Popen` at all.
    Both are unambiguously the test's own processes, and both must remain killable.

    Ancestry is the honest criterion: a process the test created (at any depth) is the test's
    to kill; the user's live daemon, editor or Claude session is not, and can never appear in
    this chain. Two passes — the cached table, then a fresh one — so a child spawned in the
    last two seconds is not denied over a stale snapshot.
    """
    return any(_walk_to_us(target, _ppid_table(refresh=r)) for r in (False, True))


def _signal_allowed(pid: object, sig: object, env: dict) -> bool:
    """A test may signal ONLY itself or a process it created. Signal 0 delivers nothing — it is
    a pure liveness probe (`os.kill(pid, 0)`) — so it is always allowed."""
    try:
        signum, target = int(sig), abs(int(pid))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if signum == 0:
        return True
    if target in _SPAWNED_PIDS or target == os.getpid():
        return True
    allow_real = _allow_real_names(env)
    if "*" in allow_real or "kill" in allow_real:
        return True
    return _descends_from_us(target)


def record_denial(argv: list[str], reason: str) -> None:
    """Append a denied spawn to the denial log (`JANITOR_TEST_SANDBOX_DENYLOG`), if set.

    This exists because a green suite is NOT proof the guard did nothing — it may equally mean
    the guard fired and the denial was SWALLOWED. `state.run_subprocess` catches every
    exception by design (a detector must never crash the heartbeat), so a SandboxViolation
    raised inside it vanishes and the test still passes. Safe, but invisible — and an
    invisible guard is one nobody can audit or trust. The log makes "what did the sandbox
    actually stop this run?" a question with a factual answer instead of an assumption.
    """
    path = os.environ.get(ENV_DENYLOG, "").strip()
    if not path:
        return
    try:
        line = json.dumps(
            {"argv": argv, "reason": reason.splitlines()[0],
             "test": os.environ.get("PYTEST_CURRENT_TEST", "")},
            ensure_ascii=False,
        ) + "\n"
        fd = _REAL_OS_OPEN(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            _REAL_OS_WRITE(fd, line.encode("utf-8", "replace"))
        finally:
            _REAL_OS_CLOSE(fd)
    except Exception:  # noqa: BLE001 — observation must never break the observed
        pass


def _enforce_spawn(argv: list[str], *, cwd: str, env: dict, shell: bool) -> None:
    """Record, then (unless auditing) enforce. Raises SandboxViolation on a denied spawn."""
    record_spawn(argv, cwd=cwd, shell=shell)
    if _audit_target():
        return  # Phase-0 audit: observe everything, deny nothing
    if not deny_roots_from_env():
        return  # the sandbox is not active in this process
    verdict = (
        _classify_shell_string(argv[0], cwd, env) if shell else classify_argv(argv, cwd=cwd, env=env)
    )
    if not verdict.allowed:
        record_denial(argv, verdict.reason)
        raise SandboxViolation(verdict.reason)


def _install_process_guard() -> None:
    """Wrap every way a Python process can start ANOTHER process, or signal one.

    `subprocess.Popen.__init__` is the single choke point that `subprocess.run` / `call` /
    `check_output` / `check_call` all funnel through, so wrapping it covers all of them at once.
    `os.system` / `os.exec*` / `os.posix_spawn` bypass Popen entirely and are wrapped separately.
    """
    import subprocess  # local: keep the import cost off the non-sandboxed path

    original_init = subprocess.Popen.__init__

    def guarded_init(self, args, *a, **kw):  # type: ignore[no-untyped-def]
        # The EFFECTIVE cwd/env — the kwargs the CHILD will actually get, not this process's.
        # Using os.getcwd()/os.environ here would misclassify every `cwd=tmp_path` git call as
        # running in the real repo (pytest's own cwd IS the repo).
        argv = _argv_of(args)
        cwd = str(kw.get("cwd") or os.getcwd())
        if kw.get("env") is not None and not kw.get("shell"):
            kw["env"] = _harden_child_env(argv, dict(kw["env"]))
        env = dict(kw["env"]) if kw.get("env") is not None else dict(os.environ)
        _enforce_spawn(argv, cwd=cwd, env=env, shell=bool(kw.get("shell")))
        original_init(self, args, *a, **kw)
        pid = getattr(self, "pid", None)
        if isinstance(pid, int):
            _SPAWNED_PIDS.add(pid)  # a child we created — the test may signal THIS

    def guarded_system(original):
        def guarded(command):  # type: ignore[no-untyped-def]
            _enforce_spawn(_argv_of(command), cwd=os.getcwd(), env=dict(os.environ), shell=True)
            return original(command)

        return guarded

    def guarded_exec(original):
        def guarded(prog, args, *a, **kw):  # type: ignore[no-untyped-def]
            argv = [os.fsdecode(prog) if isinstance(prog, bytes) else str(prog)]
            try:
                argv += [
                    os.fsdecode(x) if isinstance(x, bytes) else str(x) for x in list(args)[1:]
                ]
            except TypeError:
                pass
            _enforce_spawn(argv, cwd=os.getcwd(), env=dict(os.environ), shell=False)
            return original(prog, args, *a, **kw)

        return guarded

    def guarded_signal(original, kind):
        def guarded(pid, sig, *a, **kw):  # type: ignore[no-untyped-def]
            if not _signal_allowed(pid, sig, dict(os.environ)):
                raise SandboxViolation(
                    f"BLOCKED os.{kind}({pid}, {sig}) — that process was NOT spawned by this "
                    f"test.\n"
                    f"`memory_guard.select_victim()` reads the REAL `ps` table and returns a "
                    f"REAL pid; `global_state.request_daemon_restart()` SIGTERMs the REAL "
                    f"daemon. Either is one forgotten monkeypatch away from killing a live user "
                    f"process, and no file guard could ever see it.\n"
                    f"Fix the TEST: signal a child you spawned yourself, or monkeypatch the "
                    f"killer. (Signal 0 — a liveness probe — is always allowed.)"
                )
            return original(pid, sig, *a, **kw)

        return guarded

    _PATCHED.append((subprocess.Popen, "__init__", original_init))
    subprocess.Popen.__init__ = guarded_init  # type: ignore[method-assign]

    for name, factory in (
        ("system", guarded_system),
        ("execv", guarded_exec),
        ("execve", guarded_exec),
        ("execvp", guarded_exec),
        ("execvpe", guarded_exec),
        ("posix_spawn", guarded_exec),
        ("kill", lambda o: guarded_signal(o, "kill")),
        ("killpg", lambda o: guarded_signal(o, "killpg")),
    ):
        original = getattr(os, name, None)
        if original is None:
            continue  # not on this platform
        _PATCHED.append((os, name, original))
        setattr(os, name, factory(original))


def install(deny: tuple[Path, ...]) -> None:
    """Wrap every write-capable syscall so a protected path raises instead of being written.

    These are choke points, not a blocklist of callers: shutil, json.dump, tempfile and
    `stage_closure`'s tmp+os.replace all bottom out here. Two traps this code fell into once
    and must not fall into again — both are held by tests/test_write_sandbox.py, which is why
    those positive controls exist:

    * `io.open` is a SEPARATE binding from `builtins.open`. `pathlib.Path.open` (hence
      `write_text`/`write_bytes`) calls `io.open`, so patching only `builtins.open` lets every
      pathlib write straight through. Both names are wrapped.
    * For `os.replace(src, dst)` the file that gets DESTROYED is `dst`, not `src`. Guarding the
      source argument polices the harmless tmp file and waves the clobber through — which is
      precisely how `stage_closure` overwrote this repo. For rename/replace BOTH ends are
      checked: moving a protected source away destroys it just as surely.

    `os.chmod` is included because the clobber's most damaging side effect was a CLEARED EXEC
    BIT (100755 -> 100644) — damage no content manifest would ever flag.

    No-op when `deny` is empty, so importing this module never changes behavior by itself.
    """
    if not deny or _PATCHED:
        return

    # The exact syscalls this module is ever allowed to wrap. `_patch` refuses any name not on
    # this list before touching setattr — a guard against wrapping an unintended attribute, and
    # the reason `name` reaching setattr is not a taint sink: it is checked against a fixed
    # allowlist of our own literals, never against caller-supplied data.
    _ALLOWED_TARGETS = frozenset(
        {"open", "remove", "unlink", "rmdir", "mkdir", "makedirs", "chmod",
         "truncate", "replace", "rename", "symlink", "link", "rmtree"}
    )

    def _patch(module: object, requested: str, factory) -> None:
        # Resolve the attribute name from the constant allowlist rather than using the
        # caller's argument directly: the value that reaches setattr is one of OUR OWN
        # literals (bound from `_ALLOWED_TARGETS`), never caller-supplied data. That is both
        # a real guard against wrapping an unintended attribute AND why this setattr is not a
        # taint sink — the attribute name provably originates from a fixed constant set.
        name = next((t for t in _ALLOWED_TARGETS if t == requested), None)
        if name is None:
            raise ValueError(f"sandbox_guard refuses to patch unlisted syscall {requested!r}")
        original = getattr(module, name)
        _PATCHED.append((module, name, original))
        setattr(module, name, factory(original, name))

    def _open_guard(original, name):
        def guarded(file, mode="r", *args, **kwargs):
            if isinstance(mode, str) and any(c in mode for c in "wax+"):
                check(file, name, deny)
            return original(file, mode, *args, **kwargs)

        return guarded

    def _os_open_guard(original, name):
        writes = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

        def guarded(path, flags, *args, **kwargs):
            if isinstance(flags, int) and flags & writes:
                check(path, name, deny)
            return original(path, flags, *args, **kwargs)

        return guarded

    def _path_guard(original, name):
        def guarded(path, *args, **kwargs):
            if not _fd_relative(kwargs):
                check(path, name, deny)
            return original(path, *args, **kwargs)

        return guarded

    def _two_ended_guard(original, name):
        def guarded(src, dst, *args, **kwargs):
            if not _fd_relative(kwargs):
                check(dst, name, deny)  # the file being overwritten — THE clobber vector
                if name in ("replace", "rename"):
                    check(src, name, deny)  # a move out of a protected root destroys it too
            return original(src, dst, *args, **kwargs)

        return guarded

    _patch(builtins, "open", _open_guard)
    _patch(io, "open", _open_guard)  # pathlib's write path — NOT covered by builtins
    _patch(os, "open", _os_open_guard)
    for fn in ("remove", "unlink", "rmdir", "mkdir", "makedirs", "chmod", "truncate"):
        _patch(os, fn, _path_guard)
    for fn in ("replace", "rename", "symlink", "link"):
        _patch(os, fn, _two_ended_guard)
    # shutil.rmtree walks with fd-relative unlink/rmdir (see _fd_relative), so its children are
    # invisible to the os.* guards above. Guard its ENTRY POINT instead — one check on the root
    # it was handed covers the whole recursive delete.
    _patch(shutil, "rmtree", _path_guard)

    # The PROCESS surface. The file guards above see only Python-level writes; every genuinely
    # dangerous janitor capability (keychain via `security`, OS service via `launchctl`, typing
    # into a real terminal via `osascript`/`tmux`, killing a real pid) is a SUBPROCESS or a
    # SIGNAL and is therefore invisible to them. This closes that class at its own choke point.
    #
    # There is deliberately NO env-var kill switch here. Falsification (disabling this call and
    # proving the 5 enforcement tests fail) is done by EDITING this line, not by shipping an
    # off-switch: an env var that turns the guard off is a hole in the guard.
    _install_process_guard()


def remove() -> None:
    """Restore every patched syscall. Safe to call when nothing is patched."""
    for module, name, original in reversed(_PATCHED):
        setattr(module, name, original)
    _PATCHED.clear()
