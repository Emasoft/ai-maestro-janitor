"""Harness-backend SSOT (TRDD-PZLVT2RN) — the ONE place that answers "which world am I in?".

The same plugin serves two worlds (owner directive 2026-07-17, contract settled on
janitor#100): INSIDE an ai-maestro harness agent the session runs THIN (#J — no daemon
spawn, no user/global-scope writes, no OAuth surfaces; Family-A continuity is delegated
to the ai-maestro SERVER); OUTSIDE, the standalone backend (#N) is unchanged and its
daemon actuates ONLY on non-harness instances. Every branch point imports THIS module —
never a scattered env check — so the discriminator and the server probe each have exactly
one implementation to fix when the contract evolves.

FAIL-SAFE DOCTRINE (load-bearing; do not weaken):
  * Inside, an UNKNOWN server state degrades to "surface, don't act" — the janitor never
    substitutes itself for a server it cannot see.
  * Outside, the daemon must NOT touch a harness agent unless `server_owns_family_a()`
    is CONFIDENTLY False (no ai-maestro on this machine at all). A transient probe
    failure returns None, and None keeps the exclusion HELD — two owners actuating one
    agent is the corruption this split exists to prevent, so the tie always breaks
    toward "hands off". The Family-A fallback adoption (incl. resurrecting the server)
    is a FOLLOW-UP TRDD and must not be improvised off a None.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Mapping, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import state  # noqa: E402  -- sibling lib

# Test/override surface. "up" | "down" | "unknown" (or truthy/falsy spellings).
SERVER_STATE_ENV = "JANITOR_AIMAESTRO_SERVER_STATE"
# Explicit path override for the continuity CLI (mirrors $AIMAESTRO_CLI for the agent CLI).
CONTINUITY_CLI_ENV = "JANITOR_AIMAESTRO_CONTINUITY_CLI"

BACKEND_AIMAESTRO = "aimaestro"
BACKEND_STANDALONE = "standalone"

_TRUE = frozenset({"up", "true", "1", "yes", "on"})
_FALSE = frozenset({"down", "false", "0", "no", "off"})


def is_harness_session(env: Optional[Mapping[str, str]] = None) -> bool:
    """True iff THIS process runs inside an ai-maestro harness agent.

    Thin wrapper over `state.in_ai_maestro_agent_env` (the env-flag fast check:
    AIMAESTRO_AGENT / THIS_IS_AIMAESTRO, fallback AMP_AGENT_ID / AID_AUTH presence) so
    call sites depend on the BACKEND concept, not on the detection mechanics.
    """
    return state.in_ai_maestro_agent_env(env)


def backend(env: Optional[Mapping[str, str]] = None) -> str:
    """The actuation backend for THIS session: "aimaestro" (thin #J) or "standalone" (#N)."""
    return BACKEND_AIMAESTRO if is_harness_session(env) else BACKEND_STANDALONE


def _resolve_agent_cli() -> str | None:
    """The ai-maestro agent CLI path, or None. Delegates to terminal_trigger's resolver
    ($AIMAESTRO_CLI → ~/.local/bin/aimaestro-agent.sh → PATH) — the ONE ladder both the
    self-trigger and the fleet scanner already use; duplicating it here would drift."""
    try:
        import terminal_trigger  # noqa: PLC0415 -- lazy: keep this module import-light

        return terminal_trigger._resolve_aimaestro_cli(os.environ)  # noqa: SLF001 -- same package
    except Exception:
        return None


def server_owns_family_a(*, timeout: int = 10) -> bool | None:
    """Does a LIVE ai-maestro server own Family-A continuity for this machine's harness agents?

    Returns True / False / None(unknown). Resolution ladder:
      1. `$JANITOR_AIMAESTRO_SERVER_STATE` override — tests + emergency operator control.
      2. (Reserved slot: the canonical probe ai-maestro specifies on janitor#100 — wire it
         HERE; no call site changes.)
      3. Heuristic: `aimaestro-agent.sh list --json` — verified to curl the server's
         `/api/agents` with a 5s cap, so SUCCESS is a live-server proof. CLI absent ⇒ no
         ai-maestro install on this machine ⇒ False (the only CONFIDENT False). CLI
         present but the call fails ⇒ None — a down server and a transient error are
         indistinguishable here, and the doctrine (module docstring) requires the tie to
         break toward "hands off", so None it stays until #100 pins a sharper probe.
    """
    override = os.environ.get(SERVER_STATE_ENV, "").strip().lower()
    if override in _TRUE:
        return True
    if override in _FALSE:
        return False
    if override == "unknown":
        return None

    cli = _resolve_agent_cli()
    if cli is None:
        return False
    proc = state.run_subprocess(
        [cli, "list", "--json"],
        timeout=timeout,
        capture=True,
        detector_name="harness-backend",
    )
    if proc is None or proc.returncode != 0:
        return None
    try:
        json.loads(proc.stdout or "")
    except ValueError:
        return None
    return True


def continuity_cli() -> str | None:
    """Path of `aimaestro-continuity.sh` (the Family-A delegation surface: `status <self>`,
    `ensure-resume <self>`), or None when not installed. FEATURE-DETECT, never assume — the
    script ships with the ai-maestro server install and may lag the contract.

    Everything resolves at CALL time (never a module-level Path.home() constant — the
    frozen-constant-vs-monkeypatched-HOME trap corrupted real state once; see the
    janitor-keepalive-test-isolation memory lesson).
    """
    override = os.environ.get(CONTINUITY_CLI_ENV, "").strip()
    if override:
        p = Path(override)
        return override if p.is_file() and os.access(p, os.X_OK) else None
    home = os.environ.get("HOME") or os.path.expanduser("~")
    cand = Path(home) / ".local" / "bin" / "aimaestro-continuity.sh"
    if cand.is_file() and os.access(cand, os.X_OK):
        return str(cand)
    return shutil.which("aimaestro-continuity.sh")
