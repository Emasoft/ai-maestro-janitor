"""The osascript interpreter must have a STABLE CODE-SIGNING IDENTITY, not just a stable path.

WHY THIS EXISTS. The previous fix (TRDD-DB1P25S4 / GH#92) replaced `uv run --script`'s
per-spawn ephemeral shim with uv's MANAGED CPython, reasoning that macOS TCC needs a client
binary at a fixed path. True, and insufficient: TCC binds an Automation grant to the binary's
code-signing IDENTITY, and uv's managed CPython is ad-hoc signed with `Identifier=-`. So the
grant had nothing durable to attach to and the daemon's fleet scans kept enumerating ZERO
iTerm sessions — while the same osascript, run from a session-parented process on the same
host in the same minute, returned 34.

Measured 2026-08-16 with `codesign -dv`:

    uv-managed 3.12   Identifier=-       Signature=adhoc (linker-signed)  TeamIdentifier=not set
    homebrew 3.12     Identifier=python3-5555…  Signature=adhoc           TeamIdentifier=not set
    python.org 3.12   Identifier=python3  real signature                  TeamIdentifier=BMM5U3QVKW

These tests pin the ORDERING RULE, not this host's filesystem: an ad-hoc candidate must never
be chosen while a signed one exists, and the check must FAIL OPEN so a host without `codesign`
still resolves something rather than spawning no watcher at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import global_state as gs  # noqa: E402


def test_an_adhoc_signature_is_recognised(monkeypatch):
    """`Signature=adhoc` in codesign's output disqualifies a candidate."""

    class _P:
        returncode = 1
        stdout = ""
        stderr = "Identifier=-\nCodeDirectory v=20400 flags=0x20002(adhoc,linker-signed)\nSignature=adhoc\n"

    monkeypatch.setattr(gs.subprocess, "run", lambda *a, **k: _P())
    assert gs._is_adhoc_signed("/any/python3.12") is True


def test_a_real_signature_is_not_adhoc(monkeypatch):
    """A Developer-ID signed runtime (python.org carries TeamIdentifier BMM5U3QVKW) passes."""

    class _P:
        returncode = 0
        stdout = ""
        stderr = "Identifier=python3\nSignature size=9002\nTeamIdentifier=BMM5U3QVKW\n"

    monkeypatch.setattr(gs.subprocess, "run", lambda *a, **k: _P())
    assert gs._is_adhoc_signed("/any/python3.12") is False


@pytest.mark.parametrize("boom", [OSError("no codesign"), FileNotFoundError()])
def test_an_unreadable_signature_FAILS_OPEN(monkeypatch, boom):
    """No codesign ⇒ 'unknown', never 'disqualified'.

    A host without the tool must still resolve an interpreter. Treating unknown as
    disqualified would resolve to None on such a host and spawn NO watcher — strictly worse
    than spawning one that might be denied, because a denial at least gets logged.
    """

    def _raise(*_a, **_k):
        raise boom

    monkeypatch.setattr(gs.subprocess, "run", _raise)
    assert gs._is_adhoc_signed("/any/python3.12") is False


def test_a_signed_candidate_WINS_over_the_adhoc_uv_managed_one(monkeypatch):
    """The whole point: uv's managed CPython must not be chosen while a signed runtime exists."""
    signed = "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12"
    monkeypatch.setattr(gs.os.path, "isfile", lambda p: p == signed)
    monkeypatch.setattr(gs.os, "access", lambda p, _m: p == signed)
    monkeypatch.setattr(gs, "_is_adhoc_signed", lambda _p: False)
    monkeypatch.setattr(
        gs, "_managed_python_path", lambda: "/uv/managed/python3.12"
    )  # must NOT be reached
    assert gs.automation_python_path() == signed


def test_every_adhoc_candidate_is_SKIPPED_down_to_the_uv_last_resort(monkeypatch):
    """When everything available is ad-hoc, uv's managed CPython is still returned.

    Deliberate: ad-hoc means the grant probably will not stick, but the watcher RUNS and logs
    its denial. Returning None here would make a partially-broken host completely silent,
    which is the failure mode that hid this bug for weeks.
    """
    monkeypatch.setattr(gs.os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(gs.os, "access", lambda _p, _m: True)
    monkeypatch.setattr(gs, "_is_adhoc_signed", lambda _p: True)
    monkeypatch.setattr(gs.shutil, "which", lambda _n: "/some/adhoc/python3")
    monkeypatch.setattr(gs, "_managed_python_path", lambda: "/uv/managed/python3.12")
    assert gs.automation_python_path() == "/uv/managed/python3.12"


def test_a_PATH_hit_is_identity_checked_too(monkeypatch):
    """`command -v python3.12` inside a project finds its `.venv` python — ad-hoc and cwd-dependent.

    Pinned because this is the trap `--system` was added to `uv python find` to avoid, and a
    plain PATH fallback would walk straight back into it.
    """
    venv = "/repo/.venv/bin/python3.12"
    monkeypatch.setattr(gs.os.path, "isfile", lambda _p: False)  # no absolute candidate exists
    monkeypatch.setattr(gs.shutil, "which", lambda _n: venv)
    monkeypatch.setattr(gs, "_is_adhoc_signed", lambda p: p == venv)
    monkeypatch.setattr(gs, "_managed_python_path", lambda: "/uv/managed/python3.12")
    assert gs.automation_python_path() == "/uv/managed/python3.12"


def test_the_candidate_list_is_ordered_signed_first():
    """The framework build leads; Apple's shim is the floor. Order is the contract."""
    cands = gs._signed_python_candidates()
    assert cands[0].startswith("/Library/Frameworks/Python.framework/")
    assert cands[-1] == "/usr/bin/python3"
    assert not any("uv" in c for c in cands)
