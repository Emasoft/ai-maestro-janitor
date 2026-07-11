"""Install the write sandbox in EVERY child Python process (S1g).

CPython imports a module named `sitecustomize` automatically at interpreter startup if one is
importable. conftest puts THIS directory on `PYTHONPATH` for the duration of the test session,
so every child the suite spawns — `subprocess.run([sys.executable, ...])`, a `uv run --script`
hook, a forked daemon — boots with the same write protection as the pytest process itself.

That closes the hole the in-process sandbox could never close: patching `open`/`os.replace` in
the parent does nothing to a child interpreter, and a child is exactly what overwrote this
repo's source on 2026-07-11 (TRDD-RYZCVVKA).

FAIL-LOUD, NOT FAIL-OPEN — but only when the sandbox is actually requested. The protected roots
arrive via `JANITOR_TEST_SANDBOX_DENY`; if that variable is absent the sandbox stays OFF, so an
unrelated Python that merely inherits PYTHONPATH is completely unaffected. If it IS present and
the guard cannot be installed, we say so on stderr rather than pretending we are protected —
a sandbox that silently fails to install is worse than none, because it is trusted.
"""

import os
import sys

if os.environ.get("JANITOR_TEST_SANDBOX_DENY"):
    try:
        import sandbox_guard

        sandbox_guard.install(sandbox_guard.deny_roots_from_env())
    except Exception as exc:  # noqa: BLE001 -- never mask WHY the guard is missing
        print(
            f"[sandbox_guard] FAILED to install the write sandbox in child pid {os.getpid()}: "
            f"{exc!r}. This child can write to protected roots — treat any source-tree or "
            f"~/.claude mutation from this run as UNGUARDED.",
            file=sys.stderr,
        )
