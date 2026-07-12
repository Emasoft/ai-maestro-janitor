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
import shutil
from pathlib import Path

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


def record_spawn(argv: list[str]) -> None:
    """Append one JSON line describing a process spawn to the audit log. No-op when audit mode
    is off.

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
                "cwd": os.getcwd(),
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


def _install_process_guard() -> None:
    """Wrap `subprocess.Popen.__init__` — the ONE choke point every `subprocess.run/call/
    check_output/check_call` funnels through, so wrapping it covers all of them at once.

    PHASE 0 (this commit): audit only — record the spawn, deny nothing. The allow-list that
    Phase 1 enforces is built from what this measures.
    """
    import subprocess  # local: keep module import cost off the non-sandboxed path

    original_init = subprocess.Popen.__init__

    def guarded_init(self, args, *a, **kw):  # type: ignore[no-untyped-def]
        record_spawn(_argv_of(args))
        return original_init(self, args, *a, **kw)

    _PATCHED.append((subprocess.Popen, "__init__", original_init))
    subprocess.Popen.__init__ = guarded_init  # type: ignore[method-assign]


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
    _install_process_guard()


def remove() -> None:
    """Restore every patched syscall. Safe to call when nothing is patched."""
    for module, name, original in reversed(_PATCHED):
        setattr(module, name, original)
    _PATCHED.clear()
