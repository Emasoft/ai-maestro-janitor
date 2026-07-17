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
# Dedicated override for the singleton-CHORE ownership signal (applies to EVERY chore
# class) — lets an operator force chore takeover/yield without also flipping the
# fleet-actuation exclusion.
SERVER_CHORES_ENV = "JANITOR_AIMAESTRO_SERVER_CHORES"
# Explicit path override for the continuity CLI (mirrors $AIMAESTRO_CLI for the agent CLI).
CONTINUITY_CLI_ENV = "JANITOR_AIMAESTRO_CONTINUITY_CLI"
# Test/operator override for the server-liveness probe file path.
LIVENESS_FILE_ENV = "JANITOR_AIMAESTRO_LIVENESS_FILE"

BACKEND_AIMAESTRO = "aimaestro"
BACKEND_STANDALONE = "standalone"

# The per-class capability tokens of the #100 probe contract (ARCHITECTURE.md rev 2,
# §6.1). Each token is present in the probe file ONLY while its class is live and
# running server-side — the server's own load-bearing rule, so membership is a
# CONFIDENT signal both ways when the file is fresh.
CAP_FAMILY_A = "family-a"
CAP_SINGLETON_CHORES = "singleton-chores"
CAP_FLEET_RECOVERY = "fleet-recovery"  # reserved server-side (ai-maestro#60), never emitted yet

# The SSOT map: absorbed daemon task → the capability token that gates its yield
# (TRDD-N9YAH5E7, #100 round 1 §6.2). ONE bit must never gate two classes — the first
# class that goes live would silence chores nothing runs. daemon.py derives its
# absorbed-set from THIS map; daemon_watchdog gates the singleton-chores shims on the
# matching class.
SERVER_ABSORBED_TASK_CLASS: dict[str, str] = {
    "marketplace-refresh": CAP_SINGLETON_CHORES,
    "user-plugins-update": CAP_SINGLETON_CHORES,
    "version-update": CAP_SINGLETON_CHORES,
    "oauth-rotator-supervisor": CAP_FAMILY_A,
    "oauth-rotator-tick": CAP_FAMILY_A,
}

# Staleness window the probe contract mandates: the server rewrites the file every 30 s;
# consumers treat `now - ts > 90` (or file absent) as "no live capability claim".
LIVENESS_STALE_AFTER_S = 90

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


def _liveness_path() -> Path:
    """The server-liveness probe file path — `~/.aimaestro/server-liveness.json` per the
    #100 contract, env-overridable for tests. HOME resolved at CALL time (the
    frozen-constant-vs-monkeypatched-HOME trap; see `continuity_cli`)."""
    override = os.environ.get(LIVENESS_FILE_ENV, "").strip()
    if override:
        return Path(override)
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return Path(home) / ".aimaestro" / "server-liveness.json"


def server_capabilities(*, now: Optional[float] = None) -> frozenset[str] | None:
    """The LIVE server's advertised capability tokens, or None when there is no fresh claim.

    Reads the auth-free probe file the ai-maestro server rewrites every 30 s
    (`lib/server-liveness.ts`, #100 round 1 §6.1): `{"ts", "pid", "capabilities": [...]}`.
    Fresh (`now - ts <= 90`) ⇒ the token frozenset — a CONFIDENT per-class claim both
    ways, because the server includes a token ONLY while that class is live and running.
    Absent / stale / malformed ⇒ None ("no live capability claim" — the safe default).
    NEVER raises: this runs inside the daemon loop and per-session watchdogs.
    """
    try:
        import time  # noqa: PLC0415 -- stdlib, keep module import-light

        data = json.loads(_liveness_path().read_text(encoding="utf-8"))
        ts = data.get("ts")
        caps = data.get("capabilities")
        if not isinstance(ts, (int, float)) or isinstance(ts, bool) or not isinstance(caps, list):
            return None
        t = time.time() if now is None else now
        if t - float(ts) > LIVENESS_STALE_AFTER_S:
            return None
        return frozenset(c for c in caps if isinstance(c, str))
    except Exception:  # noqa: BLE001 -- no-claim beats a crashed daemon loop
        return None


def _server_owns_capability(capability: str) -> bool | None:
    """The ONE per-class ownership ladder (TRDD-N9YAH5E7):

      1. `$JANITOR_AIMAESTRO_SERVER_STATE` override — tests + emergency operator control
         (forces EVERY class: "down" is the adoption escape hatch, "up" a forced yield).
      2. The fresh probe file: `capability in capabilities` — CONFIDENT True/False.
      3. No fresh claim: CLI absent ⇒ False (no ai-maestro install at all — the only
         confident False); CLI present ⇒ None (a down or pre-probe server — capability
         unknowable; each caller's own None-policy breaks the tie).

    The legacy `aimaestro-agent.sh list --json` rung was REMOVED here deliberately: a
    successful agent-list proves LIVENESS, not capability — treating it as a True source
    would let a live server that never claimed a class silence the janitor's chores for
    that class (#100 round 1 §6.2, the exact conflict this rewrite fixes). It also 401'd
    without AID_AUTH from the daemon's context anyway (F6), so nothing real is lost.
    """
    override = os.environ.get(SERVER_STATE_ENV, "").strip().lower()
    if override in _TRUE:
        return True
    if override in _FALSE:
        return False
    if override == "unknown":
        return None
    caps = server_capabilities()
    if caps is not None:
        return capability in caps
    try:
        return False if _resolve_agent_cli() is None else None
    except Exception:  # noqa: BLE001 -- unknown beats a crashed caller
        return None


def server_owns_family_a(*, timeout: int = 10) -> bool | None:  # noqa: ARG001
    """Does a LIVE ai-maestro server own Family-A continuity for this machine's harness agents?

    True/False/None per `_server_owns_capability(CAP_FAMILY_A)` — the #100 canonical
    probe is wired (the formerly-reserved rung 2), with zero call-site changes as
    designed. `timeout` is retained for call-site compatibility; the probe is now a
    file read, no subprocess.
    """
    return _server_owns_capability(CAP_FAMILY_A)


# Per-class chore-ownership memo: {capability: (monotonic_ts, value)}. The daemon calls
# the chore gate every loop tick (60 s); amortize the file read. 300 s max staleness is
# fine for chores whose cadences are 60 s (lock-protected) to hours.
_CHORES_TTL_S = 300
_chores_cache: dict[str, tuple[float, bool | None]] = {}


def server_owns_chore_class(capability: str) -> bool | None:
    """Does a LIVE ai-maestro server own the chore CLASS gated by `capability`?

    Owner directive (2026-07-17, verbatim intent): "if the ai-maestro server is active,
    the non-aimaestro-janitor daemon must deactivate all the chores that only need to be
    executed once (i.e. oauth rotation, upgrade all marketplaces, ~/.claude config
    monitoring, etc.)" — while the population-split operations (liveness recovery,
    fleet-stop, reload flags) keep running on BOTH sides, each for its own population.

    PER-CLASS (TRDD-N9YAH5E7, #100 round 1 §6.2): each absorbed task yields on its OWN
    token (`SERVER_ABSORBED_TASK_CLASS`) — the OAuth pair on `family-a`, the
    marketplace/version trio on `singleton-chores` (which the server never emits today,
    so the janitor keeps them). One shared bit would let the first live class silence
    chores nothing runs.

    Resolution: `$JANITOR_AIMAESTRO_SERVER_CHORES` override first (chores-only knob,
    every class), then the memoized `_server_owns_capability(capability)` ladder (which
    starts with the `$JANITOR_AIMAESTRO_SERVER_STATE` override — both env rungs bypass
    the memo so an operator flip acts immediately, never up to _CHORES_TTL_S late).

    NONE-POLICY — deliberately the OPPOSITE of the fleet-actuation exclusion, and this
    asymmetry is load-bearing:
      * Actuation on a harness AGENT: unknown ⇒ HANDS OFF (two actuators on one agent
        corrupt it; doing nothing is safe).
      * A machine-wide CHORE: unknown ⇒ RUN IT (nobody doing the chore breaks the
        machine — tokens lapse, plugins rot; doing it twice is merely wasteful and the
        cross-process file locks — oauth-rotator-tick.lock, marketplace-op.lock — are
        the collision backstop, per the #100 lock contract).
    So a caller yields a chore IFF this returns CONFIDENTLY True.
    """
    override = os.environ.get(SERVER_CHORES_ENV, "").strip().lower()
    if override in _TRUE:
        return True
    if override in _FALSE:
        return False
    if override == "unknown":
        return None
    # The STATE override rung must ALSO bypass the memo — an operator flip (or a
    # test's monkeypatched env) acts immediately, never up to _CHORES_TTL_S late.
    state_override = server_state_override()
    if state_override is not None:
        return state_override

    import time  # noqa: PLC0415 -- stdlib, keep module import-light

    now = time.monotonic()
    cached = _chores_cache.get(capability)
    if cached is not None and now - cached[0] < _CHORES_TTL_S:
        return cached[1]
    value = _server_owns_capability(capability)
    _chores_cache[capability] = (now, value)
    return value


def server_owns_singleton_chores(*, timeout: int = 10) -> bool | None:  # noqa: ARG001
    """The `singleton-chores` class gate (marketplace-refresh / user-plugins-update /
    version-update — the chores the server does NOT perform today, so this is
    False/None until ai-maestro ships them and emits the token). Kept as a named
    wrapper because the two singleton-chores per-session shims (daemon_watchdog) gate
    on it by name. `timeout` retained for call-site compatibility (file read now)."""
    return server_owns_chore_class(CAP_SINGLETON_CHORES)


def server_state_override() -> bool | None:
    """JUST the `$JANITOR_AIMAESTRO_SERVER_STATE` override rung: True/False when the
    operator forced a state, None when unset (or "unknown" — both mean "no forced
    answer"). The fleet scanner uses this alone, because its OWN successful agent-list
    call already IS the live-server proof — running a second probe subprocess per scan
    would be waste."""
    override = os.environ.get(SERVER_STATE_ENV, "").strip().lower()
    if override in _TRUE:
        return True
    if override in _FALSE:
        return False
    return None


def agent_workdirs(agents: list) -> list[str]:
    """The registered workingDirectory of every ai-maestro agent, deduped, order-kept.
    Reuses terminal_trigger's field reader (the SAME one the tmux matcher uses) so the
    two never disagree about where an agent lives."""
    try:
        import terminal_trigger  # noqa: PLC0415 -- lazy: keep this module import-light

        reader = terminal_trigger._agent_working_dir  # noqa: SLF001 -- same package
    except Exception:
        return []
    out: list[str] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        wd = reader(agent)
        if wd and wd not in out:
            out.append(wd)
    return out


_AGENT_ROOTS_CACHE = "aimaestro-agent-roots.json"


def remember_agent_roots(roots: list[str]) -> None:
    """Persist the last-known harness-agent workdirs (global-state, atomic, best-effort).

    WHY a cache exists at all: when the server's agent-list call FAILS, the scanner
    cannot see which instances are harness agents — and "cannot see" must not become
    "free to actuate" (the doctrine tie-break). The cache lets the exclusion HOLD
    through a server hiccup using the last truth the server itself published."""
    try:
        import global_state  # noqa: PLC0415 -- lazy sibling (daemon-side only)

        target = global_state.global_state_dir() / _AGENT_ROOTS_CACHE
        payload = json.dumps(sorted(roots))
        try:
            if target.read_text(encoding="utf-8").strip() == payload:
                return  # unchanged — don't churn the file every scan
        except OSError:
            pass
        state.atomic_write(target, payload)
    except Exception:
        pass  # a cache write failure must never break a fleet scan


def recall_agent_roots() -> list[str]:
    """The cached last-known harness-agent workdirs. Fail-open []."""
    try:
        import global_state  # noqa: PLC0415 -- lazy sibling

        raw = (global_state.global_state_dir() / _AGENT_ROOTS_CACHE).read_text(encoding="utf-8")
        data = json.loads(raw)
        return [r for r in data if isinstance(r, str) and r] if isinstance(data, list) else []
    except Exception:
        return []


AGENTS_HOME_ENV = "AIMAESTRO_AGENTS_HOME"


def agents_home() -> str:
    """The ai-maestro agents home (workdir root of registry agents), default `~/agents`.
    Env-overridable; HOME resolved at CALL time (the frozen-constant trap)."""
    override = os.environ.get(AGENTS_HOME_ENV, "").strip()
    if override:
        return override.rstrip("/")
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return str(Path(home) / "agents")


def root_under_agents_home(root: str | None) -> bool:
    """True iff `root` sits inside the agents home — the REGISTRY-FREE harness signal."""
    if not root:
        return False
    base = agents_home()
    return root == base or root.startswith(base + "/")


def instance_is_server_owned(
    *,
    tagged: bool,
    root: str | None,
    cli_present: bool,
    list_ok: bool,
    cached_roots: list[str],
    override: bool | None,
    under_agents_home: bool = False,
) -> bool:
    """PURE: is THIS scanned instance a harness agent a live server owns (⇒ the daemon
    keeps its hands off)? The whole exclusion decision, in one testable table:

    - operator override False (forced "down") ⇒ never owned — the adoption escape hatch.
    - no ai-maestro CLI on the machine ⇒ never owned (the confident False).
    - `tagged` (matched an agent from THIS scan's successful server list) ⇒ owned — the
      tag doubles as the live-server proof, because the list came off the server's own
      HTTP API this very scan.
    - `under_agents_home` (the instance's root is inside `~/agents/`) ⇒ owned. This is
      the REGISTRY-FREE signal, and it is LOAD-BEARING today: verified live 2026-07-17,
      `aimaestro-agent.sh list` answers HTTP 401 to any caller without AID_AUTH — which
      the daemon does not have (AM8JD9SG F6) — so from the daemon's context the list
      ALWAYS fails, no instance is ever tagged, and the cache never fills. Without this
      signal the exclusion would be structurally inert exactly where it matters.
      Erring hands-off is the safe direction; #100 owes the auth-free canonical probe
      that will supersede it. Adopted workdirs OUTSIDE ~/agents remain covered only by
      tag/cache (a known gap until that probe lands).
    - list FAILED but the instance's root matches a CACHED agent workdir ⇒ owned — a
      down-or-hiccuping server is indistinguishable from a transient error, and the tie
      breaks toward hands-off (see `remember_agent_roots`). Deliberate consequence: a
      genuinely dead server keeps its agents excluded until the operator forces
      adoption via the override — automatic adoption is a FOLLOW-UP TRDD, not a guess.
    """
    if override is False or not cli_present:
        return False
    if tagged or under_agents_home:
        return True
    if not list_ok and root:
        return any(root == wd or root.startswith(wd.rstrip("/") + "/") for wd in cached_roots)
    return False


def self_agent_ref(env: Optional[Mapping[str, str]] = None) -> str | None:
    """THIS harness agent's own id for `<self>` CLI arguments (`aimaestro-continuity.sh
    status|ensure-resume <self>`), or None when unknowable.

    `$AMP_AGENT_ID` is the ai-maestro internal agent id the harness exports into the
    agent's env (the same var the discriminator treats as an "internal id present"
    signal). `AIMAESTRO_AGENT` / `THIS_IS_AIMAESTRO` are boolean FLAGS ("1"/"true"),
    never an identity — do not fall back to them. R42 (self-only) makes a wrong guess
    here an auth error server-side, so None (skip the call) beats a fabricated ref.
    """
    e = os.environ if env is None else env
    ref = (e.get("AMP_AGENT_ID") or "").strip()
    return ref or None


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
