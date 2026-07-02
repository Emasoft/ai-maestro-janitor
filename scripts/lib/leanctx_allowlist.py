# Self-heal the lean-ctx shell allowlist for the janitor heartbeat
# (TRDD-ZGLCGC6A).
#
# `lean-ctx` is a machine-global shell-allowlist wrapper that gates the Bash
# tool. On a machine that runs it, the heartbeat cron's bare
# `dispatcher-stub.py` invocation (and a handful of dash-flags the dispatcher
# passes) are BLOCKED until the allowlist explicitly permits them. The ONLY
# correct, safe fix is the ADDITIVE `lean-ctx allow <cmd>` — it merges the token
# into the user's allowlist over the built-in defaults and is idempotent (prints
# "already allowed" on a repeat). It is NEVER correct to disable shell security
# (`shell_security=off`) or to redefine `shell_allowlist` wholesale: both open
# the Bash tool to everything, which is exactly the danger lean-ctx exists to
# prevent. An armed janitor session that hits the block must self-heal the
# additive way, not bypass the wrapper.
#
# This module makes EVERY armed session self-heal on session start: it runs
# `lean-ctx allow <tok>` once per janitor-required token. Everything here is
# FAIL-OPEN and SECURITY-SAFE by construction — a missing binary, a timeout, a
# non-zero exit, ANY exception is swallowed so an absent/broken lean-ctx can
# never break session start, and the module ONLY ever runs the additive
# `allow` subcommand. It never touches a shell-security toggle.
#
# Imported (not invoked as a script) so no PEP 723 metadata block here.
# Stdlib-only: shutil + subprocess are all the module level needs; the
# config-gate's `state` import is lazy (see `_autoallow_enabled`).

from __future__ import annotations

import shutil
import subprocess

# The exact tokens the janitor heartbeat needs on the lean-ctx allowlist:
#   - dispatcher-stub.py — the cron's bare-script invocation (the primary block)
#   - uv / python3       — the interpreters the stub + dispatch.py run under
#   - git / memgrep      — invoked by detectors and the memory-recall path
#   - -d                 — a dash-flag the dispatcher passes that lean-ctx gates
# Held as a module-level tuple so the pure accessor below is the SINGLE source
# of truth and tests can assert the list without any I/O.
_REQUIRED_TOKENS: tuple[str, ...] = (
    "dispatcher-stub.py",
    "uv",
    "python3",
    "git",
    "memgrep",
    "-d",
)

# Per-call cap. `lean-ctx allow` is a fast local config edit; 10 s is generous
# headroom so a wedged wrapper can never park session start.
_ALLOW_TIMEOUT_S = 10.0

# Plugin option (default ON). The CLAUDE_PLUGIN_OPTION_* env var is derived from
# the `leanctx_autoallow` userConfig key in .claude-plugin/plugin.json.
_OPTION_ENV = "CLAUDE_PLUGIN_OPTION_LEANCTX_AUTOALLOW"


def required_tokens() -> list[str]:
    """Return the janitor's required lean-ctx allowlist tokens.

    PURE — no I/O, no environment reads. Returns a fresh list each call so a
    caller mutating the result cannot corrupt the module constant. Kept
    separate from the I/O path so the token contract is trivially testable.
    """
    return list(_REQUIRED_TOKENS)


def _autoallow_enabled() -> bool:
    """True iff CLAUDE_PLUGIN_OPTION_LEANCTX_AUTOALLOW is truthy (default ON).

    Reads through `state.is_truthy_env` — the single source of truth for the
    plugin's yes/no env-var spelling — rather than re-implementing the
    false-spelling rules here. The import is LAZY (so the pure
    `required_tokens()` above carries no dependency) and dual-form so it resolves
    in BOTH runtime contexts: the hook call site puts `scripts/` on sys.path
    (→ `from lib import state`), while a detector/test call site puts
    `scripts/lib` on sys.path (→ bare `import state`). Any failure to read the
    config falls back to the documented default (ON) — a config-read error must
    never silently DISABLE the self-heal.
    """
    try:
        try:
            from lib import state  # hook context: scripts/ on sys.path
        except ImportError:
            import state  # type: ignore[no-redef]  # detector / test context: scripts/lib on sys.path

        return bool(state.is_truthy_env(_OPTION_ENV, True))
    except Exception:  # noqa: BLE001 -- a config-read failure must not decide anything but the default
        return True


def ensure_janitor_allowed() -> list[str]:
    """Additively allow every janitor-required token on the lean-ctx allowlist.

    Runs `lean-ctx allow <tok>` once per token (see `_REQUIRED_TOKENS`).
    Returns the list of tokens it attempted (empty when the feature is off or
    lean-ctx is not installed) so the caller can log what it did.

    FAIL-OPEN and SECURITY-SAFE by construction:
      * No-op when CLAUDE_PLUGIN_OPTION_LEANCTX_AUTOALLOW is false.
      * No-op when `lean-ctx` is not on PATH (`shutil.which` falsy) — a machine
        that does not run the wrapper has nothing to heal.
      * Each `lean-ctx allow` is best-effort: a TimeoutExpired, an OSError (e.g.
        the binary vanished between the `which` and the run), or any other
        subprocess error is swallowed and the loop continues to the next token.
        A non-zero exit is already non-raising (`check` is left False) — the
        additive allow is idempotent, so a "already allowed" exit is harmless.
      * It ONLY ever runs the additive `lean-ctx allow <tok>` subcommand. It
        NEVER disables shell security and NEVER redefines the allowlist — the
        dangerous bypasses this whole module exists to make unnecessary. Args
        are passed as a list (never a shell string) so a token can never be
        re-interpreted as a shell construct.
    """
    if not _autoallow_enabled():
        return []
    if not shutil.which("lean-ctx"):
        return []

    attempted: list[str] = []
    for tok in _REQUIRED_TOKENS:
        attempted.append(tok)
        try:
            subprocess.run(
                ["lean-ctx", "allow", tok],
                capture_output=True,
                text=True,
                check=False,
                timeout=_ALLOW_TIMEOUT_S,
            )
        except (subprocess.SubprocessError, OSError):
            # Best-effort: one token's failure must abort neither the remaining
            # tokens nor session start. SubprocessError covers TimeoutExpired.
            continue
    return attempted
