"""Shared pytest fixtures for the ai-maestro-janitor test-suite.

Centralized rotator-path isolation (TRDD-56374Z36, re-surfacing TRDD-14IY6MAD / shipped v0.18.2).

Every rotator test module imports the rotator by path into a module-global ``rotator``
(``rotator = _load_rotator()``). That module resolves ROOT / LOG_FILE / SLOTS / STATE_FILE ONCE
at import to the REAL operational dir under ``~/.claude/plugins/data/.../oauth-rotator/``. A test
that re-points ``ROOT`` (e.g. the bootstrap ``_wire`` helper) but forgets ``LOG_FILE`` makes
``_log`` append to the PRODUCTION ``rotator.log`` — the exact leak that filled it with fixture
``auto-bootstrap: opening a browser … for seeded@x.com`` lines. TRDD-14IY6MAD fixed this once with
a per-MODULE autouse fixture inside ``test_oauth_rotator.py``; the bootstrap + cascade modules
never got it (``two input paths ≠ SSOT`` — the log path diverged from the isolated state path).

This autouse fixture CENTRALIZES that protection so EVERY rotator test module — present and future
— has its ``ROOT`` + ``LOG_FILE`` redirected to a per-test tmp dir, and a new module can't
re-introduce the leak. It is a deliberate PATH-redirect (NOT a ``_log`` no-op) so the dedicated
``_log`` tests, which re-point ``LOG_FILE`` inside their own body, still assert on real written
content. Non-rotator tests are a fast no-op: no ``rotator`` module global → nothing is patched and
a ``tmp_path`` is never even created for them.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_rotator_paths(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    rotator = getattr(request.module, "rotator", None)
    if rotator is None or not hasattr(rotator, "LOG_FILE"):
        return  # not a rotator test module — do nothing (and don't force a tmp_path)
    # Lazy: only rotator tests pay for a tmp dir. When the test itself also requests tmp_path,
    # this resolves to the SAME instance, so any test-local re-point of ROOT/STATE_FILE/SLOTS
    # stays consistent while LOG_FILE (which tests routinely forget) stays isolated by default.
    root: Path = request.getfixturevalue("tmp_path")
    monkeypatch.setattr(rotator, "ROOT", root, raising=False)
    monkeypatch.setattr(rotator, "LOG_FILE", root / "rotator.log", raising=False)
