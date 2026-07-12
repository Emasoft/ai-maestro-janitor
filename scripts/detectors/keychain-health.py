#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""keychain-health — detect a security session that cannot reach the keychain.

THE INCIDENT THIS EXISTS FOR (2026-07-12). Every Claude agent on the machine suddenly
reported `Not logged in`. Hours went into suspecting the credential, the rotator, the test
suite, the workdir and the env — all wrong. The credential was FINE. A LONG-LIVED tmux
server (ppid 1, 22 h old) held a securityd connection that DIED in a securityd recycle, and
every pane it forks inherits that dead security session: inside them the Keychain Services
API fails outright, so Claude Code cannot read its OAuth item. `/login` could not fix it,
because the credential was never the problem — REACHABILITY was.

The janitor is the guardian of the fleet, so it must catch this in ONE heartbeat instead of
a day of forensics. The per-session heartbeat is uniquely able to: it runs INSIDE the same
security session as the agent, so it sees exactly what the agent will see.

HARD SAFETY — never `-w` (macos-keychain gotcha 3, the ACL prompt FLOOD): reading an item's
SECRET (`-w`) when the caller is not on its ACL opens a GUI keychain dialog — that is what
once opened hundreds of modals and locked the user out. This detector therefore checks
FINDABILITY, NEVER READABILITY: `list-keychains` and `find-generic-password` WITHOUT `-w`
return attributes only — no secret, no ACL check, no prompt. Every call is additionally
routed through `safe_storage.run_security`, the mandated choke point (hard timeout +
one-shot denied-latch), so a hung or prompting keychain can never stall the heartbeat.

macOS-only; a silent no-op elsewhere. Read-only, fail-open: any surprise yields zero findings
rather than a broken heartbeat.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))
sys.path.insert(0, str(_HERE.parent / "oauth_rotator"))

import dedupe  # noqa: E402
import keychain_health as kh  # noqa: E402
import safe_storage  # noqa: E402  # the mandated `security` choke point (timeout + latch)
import state  # noqa: E402

DETECTOR = "keychain-health"


def _probe_search_list() -> tuple[bool, str, list[str]]:
    """`security list-keychains` → (ok, stderr, paths). No secret, no prompt."""
    run = safe_storage.run_security(["security", "list-keychains"], timeout=5)
    if not run.spawned:
        # Not macOS (no `security`), or the denied-latch is set. Either way: say nothing.
        return True, "", []
    return run.ok, run.stderr, kh.parse_search_list(run.stdout)


def _credential_findable() -> bool | None:
    """Is Claude Code's OAuth item FINDABLE from this security session?

    NOTE THE MISSING `-w` — this asks only whether the item can be located, never what its
    secret is. That is the whole point: findable != readable, and only the readable (`-w`)
    form prompts. None = could not determine (never treated as a failure: absence of evidence
    is not evidence — the exact error that made the original incident take hours).
    """
    run = safe_storage.run_security(
        ["security", "find-generic-password", "-s", kh.CLAUDE_CREDENTIAL_SERVICE],
        timeout=5,
    )
    if not run.spawned:
        return None
    return run.ok


def main() -> int:
    if sys.platform != "darwin":
        return 0  # `security` / Keychain Services is macOS-only
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_KEYCHAIN_HEALTH_ENABLED", True):
        return 0
    try:
        state.init_state()
        list_ok, list_stderr, paths = _probe_search_list()

        # The existence probe is INJECTED so the pure lib needs no filesystem import at all.
        dangling = kh.dangling_entries(paths, lambda p: Path(p).exists()) if paths else []

        # Only probe the credential when the session is HEALTHY: on a broken session the probe
        # tells us nothing new (everything fails), and the verdict is already decided.
        findable = _credential_findable() if (list_ok and not dangling) else None

        verdict = kh.classify(
            list_ok=list_ok,
            list_stderr=list_stderr,
            dangling=dangling,
            credential_findable=findable,
        )
        if verdict is None:
            return 0

        line = kh.format_drift(verdict, sanitize=state.sanitize_for_drift_line)
        # Dedupe on the VERDICT (code + evidence), not the timestamp: a persistent breakage
        # must not re-nag every heartbeat, but a NEW/changed one must always surface.
        seen = state.state_dir() / f"{DETECTOR}-seen.txt"
        out = dedupe.emit_once(seen, f"{verdict.code}:{verdict.detail}", line)
        if out:
            print(out)
            state.log_line(DETECTOR, f"{verdict.severity} {verdict.code}: {verdict.detail}")
    except Exception as exc:  # noqa: BLE001 — a guardian must never break the heartbeat
        state.log_line(DETECTOR, f"skipped (non-fatal): {exc!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
