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
import os
import shutil
from pathlib import Path

#: Protected roots are passed to children through the environment (os.pathsep-joined), so a
#: child enforces the SAME roots the parent computed — including the REAL home, which the
#: child can no longer derive itself once HOME has been redirected into a tmp tree.
ENV_DENY = "JANITOR_TEST_SANDBOX_DENY"

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

    def _patch(module: object, name: str, factory) -> None:
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


def remove() -> None:
    """Restore every patched syscall. Safe to call when nothing is patched."""
    for module, name, original in reversed(_PATCHED):
        setattr(module, name, original)
    _PATCHED.clear()
