"""Tests for scripts/lib/leanctx_allowlist.py — the lean-ctx allowlist self-heal.

`ensure_janitor_allowed()` additively runs `lean-ctx allow <tok>` for each
token the janitor heartbeat needs, on machines that run the lean-ctx
Bash-allowlist wrapper. The contract under test:

  * the PURE `required_tokens()` is the exact janitor token set;
  * gated by CLAUDE_PLUGIN_OPTION_LEANCTX_AUTOALLOW (default ON);
  * a silent no-op when lean-ctx is not on PATH;
  * FAIL-OPEN — a non-zero exit or a per-call timeout is swallowed, every token
    is still attempted, nothing raises;
  * SECURITY-SAFE — it only ever runs the additive `allow` subcommand.

No mocks: the present-path is exercised with a REAL fake `lean-ctx` executable
placed on a temp PATH that records each invocation's args to a log file.

scripts/lib is put on sys.path (the repo's lib-test convention) so both
`import leanctx_allowlist` and the module's internal config-gate import resolve
— the gate's dual-form import falls back to bare `import state` in this context.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import leanctx_allowlist  # noqa: E402  -- local module under scripts/lib, not PyPI

_OPTION_ENV = "CLAUDE_PLUGIN_OPTION_LEANCTX_AUTOALLOW"

# A fake `lean-ctx`: append this invocation's args to $LEANCTX_LOG, then exit
# per $LEANCTX_EXIT (default 0). When $LEANCTX_SLEEP is set AND this is the
# `allow dispatcher-stub.py` call, `exec sleep` so the call exceeds the timeout
# — `exec` makes sleep the SAME pid the parent spawned, so the timeout's SIGKILL
# reaps it with NO orphan process. Pure POSIX sh (no python3 dependency,
# /bin/sh is always present) so the fake runs regardless of the test PATH.
_LEANCTX_FAKE = """#!/bin/sh
printf '%s\\n' "$*" >> "$LEANCTX_LOG"
if [ "$2" = "dispatcher-stub.py" ] && [ -n "${LEANCTX_SLEEP:-}" ]; then
  exec sleep "$LEANCTX_SLEEP"
fi
exit "${LEANCTX_EXIT:-0}"
"""


def _make_fake_leanctx(bindir: Path) -> None:
    """Write an executable fake `lean-ctx` into bindir."""
    bindir.mkdir(parents=True, exist_ok=True)
    fake = bindir / "lean-ctx"
    fake.write_text(_LEANCTX_FAKE, encoding="utf-8")
    fake.chmod(0o755)


def _prepend_path(monkeypatch, bindir: Path) -> None:
    """Put bindir FIRST on PATH while keeping the real PATH (so the fake's
    `exec sleep` can still resolve `sleep`)."""
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")


def _read_calls(log: Path) -> list[str]:
    """The recorded `lean-ctx` invocations, one per call, args space-joined."""
    if not log.exists():
        return []
    return [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln]


# --- pure token list -------------------------------------------------------

def test_required_tokens_is_the_exact_janitor_set():
    """required_tokens() returns the exact janitor heartbeat allowlist tokens, in order."""
    assert leanctx_allowlist.required_tokens() == [
        "dispatcher-stub.py",
        "uv",
        "python3",
        "git",
        "memgrep",
        "-d",
    ]


def test_required_tokens_returns_a_fresh_copy():
    """required_tokens() returns a fresh list each call so a caller cannot mutate the constant."""
    first = leanctx_allowlist.required_tokens()
    first.append("rm")
    assert "rm" not in leanctx_allowlist.required_tokens()


# --- gating ----------------------------------------------------------------

def test_option_off_is_a_noop_even_with_leanctx_present(tmp_path, monkeypatch):
    """With the feature disabled, ensure_janitor_allowed() makes NO calls even when lean-ctx is on PATH."""
    bindir = tmp_path / "bin"
    log = tmp_path / "calls.log"
    _make_fake_leanctx(bindir)
    _prepend_path(monkeypatch, bindir)
    monkeypatch.setenv("LEANCTX_LOG", str(log))
    monkeypatch.setenv(_OPTION_ENV, "false")

    assert leanctx_allowlist.ensure_janitor_allowed() == []
    assert _read_calls(log) == []


def test_leanctx_absent_is_a_noop(tmp_path, monkeypatch):
    """With lean-ctx not on PATH, ensure_janitor_allowed() is a no-op (returns [], no calls)."""
    empty_bin = tmp_path / "emptybin"
    empty_bin.mkdir()
    # Isolate PATH to a dir with NO lean-ctx so the machine's real wrapper is
    # not found either — shutil.which returns None → early return, no run.
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.delenv(_OPTION_ENV, raising=False)  # default ON

    assert leanctx_allowlist.ensure_janitor_allowed() == []


# --- present path (real fake lean-ctx) ------------------------------------

def test_present_path_allows_every_token_in_order(tmp_path, monkeypatch):
    """With lean-ctx present and the feature ON, every required token is passed to `lean-ctx allow`, in order."""
    bindir = tmp_path / "bin"
    log = tmp_path / "calls.log"
    _make_fake_leanctx(bindir)
    _prepend_path(monkeypatch, bindir)
    monkeypatch.setenv("LEANCTX_LOG", str(log))
    monkeypatch.delenv(_OPTION_ENV, raising=False)  # default ON

    attempted = leanctx_allowlist.ensure_janitor_allowed()

    assert attempted == leanctx_allowlist.required_tokens()
    assert _read_calls(log) == [
        f"allow {tok}" for tok in leanctx_allowlist.required_tokens()
    ]


def test_nonzero_exit_is_best_effort(tmp_path, monkeypatch):
    """A non-zero `lean-ctx allow` exit does not abort the loop or raise — every token is still attempted."""
    bindir = tmp_path / "bin"
    log = tmp_path / "calls.log"
    _make_fake_leanctx(bindir)
    _prepend_path(monkeypatch, bindir)
    monkeypatch.setenv("LEANCTX_LOG", str(log))
    monkeypatch.setenv("LEANCTX_EXIT", "3")
    monkeypatch.delenv(_OPTION_ENV, raising=False)

    attempted = leanctx_allowlist.ensure_janitor_allowed()

    assert attempted == leanctx_allowlist.required_tokens()
    assert _read_calls(log) == [
        f"allow {tok}" for tok in leanctx_allowlist.required_tokens()
    ]


def test_timeout_is_best_effort(tmp_path, monkeypatch):
    """A `lean-ctx allow` that exceeds the per-call timeout is swallowed; the loop still finishes every token."""
    bindir = tmp_path / "bin"
    log = tmp_path / "calls.log"
    _make_fake_leanctx(bindir)
    _prepend_path(monkeypatch, bindir)
    monkeypatch.setenv("LEANCTX_LOG", str(log))
    monkeypatch.setenv("LEANCTX_SLEEP", "5")  # the dispatcher-stub.py call sleeps
    monkeypatch.delenv(_OPTION_ENV, raising=False)
    # Shrink the per-call cap so the real slow subprocess trips it quickly.
    monkeypatch.setattr(leanctx_allowlist, "_ALLOW_TIMEOUT_S", 0.5)

    attempted = leanctx_allowlist.ensure_janitor_allowed()

    # The TimeoutExpired on the first token was swallowed (not propagated), and
    # the remaining tokens still ran — every token counts as attempted.
    assert attempted == leanctx_allowlist.required_tokens()
