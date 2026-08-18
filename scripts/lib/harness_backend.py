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
  * Outside, ACTUATION on a harness agent stays hands-off on any uncertainty
    (`instance_is_server_owned` — two owners actuating one agent is the corruption this
    split exists to prevent), while the machine-wide CHORES follow the BINARY liveness
    switch (`server_runs_chores`, TRDD-LU0C5KAR): server alive ⇒ ALL absorbed chores
    are the server's; server gone/unknown ⇒ the janitor runs them ALL. The Family-A
    fallback adoption (incl. resurrecting the server) is a FOLLOW-UP TRDD and must not
    be improvised off uncertainty.
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

# The machine-wide ONCE-ONLY daemon tasks the ai-maestro server absorbs while it RUNS
# (TRDD-LU0C5KAR, owner directive 2026-07-17): responsibility follows PROCESS LIVENESS
# — a running server owns ALL of these, full stop; a server that runs without executing
# one of them is a SERVER bug to fix there, never a janitor guard to keep. This
# replaced TRDD-N9YAH5E7's per-class capability gating (the owner: "too complicated").
# daemon.py derives its absorbed-set from THIS set; everything NOT in it keeps running
# regardless (population-split ops + janitor-only Family-B chores).
SERVER_ABSORBED_TASKS: frozenset[str] = frozenset({
    "marketplace-refresh",
    "user-plugins-update",
    "version-update",
    "oauth-rotator-supervisor",
    "oauth-rotator-tick",
    # Joined 2026-08-18 (janitor#274, ratified with the server on the rev-8/#126
    # thread): the server has executed its own github-config audit since 2026-08-05
    # (ai-maestro lib/janitor-chore-stamp.ts) and writes this chore's stamp —
    # verified on-host: ~/.claude/janitor-control/github-config-audit.last-run.ts
    # fresh the day this line landed. Keeping it out of the set made both sides run
    # it, and two writers on repo config is the exact class the absorption exists
    # to prevent.
    "github-config-audit",
})

# EVERY chore the machine-global daemon owns, with the env var + default cadence
# daemon.py resolves each from. The roster lives HERE, beside SERVER_ABSORBED_TASKS,
# because the two are only meaningful together: an absorption boundary says nothing
# without the full set it partitions.
#
# WHY this exists (ai-maestro#111, 2026-08-05): a live server does not make the daemon
# YIELD the absorbed chores — `global_state.ensure_daemon_running` refuses to spawn the
# daemon AT ALL. Every roster chore NOT in SERVER_ABSORBED_TASKS therefore has
# NO owner for as long as a server is up. Measured on the owner's host: all eleven stamps
# 10-14 days stale, and not one alarm, because the only staleness watchdog suppressed
# itself whenever a server was alive. Keeping the roster next to the boundary is what lets
# `unabsorbed_chores()` name the gap instead of it being invisible.
#
# tests/test_harness_backend.py asserts this table matches daemon.py's Task registry
# name-for-name and default-for-default, so this copy cannot drift from the daemon it
# describes.
GLOBAL_CHORES: dict[str, tuple[str, int]] = {
    "marketplace-refresh": ("CLAUDE_PLUGIN_OPTION_DAEMON_MARKETPLACE_REFRESH_INTERVAL", 3600),
    "user-plugins-update": ("CLAUDE_PLUGIN_OPTION_DAEMON_USER_PLUGINS_UPDATE_INTERVAL", 3600),
    "fleet-plugins-update": ("CLAUDE_PLUGIN_OPTION_DAEMON_FLEET_PLUGINS_UPDATE_INTERVAL", 21600),
    "version-update": ("CLAUDE_PLUGIN_OPTION_DAEMON_VERSION_UPDATE_INTERVAL", 21600),
    "oauth-rotator-supervisor": ("CLAUDE_PLUGIN_OPTION_DAEMON_OAUTH_SUPERVISOR_INTERVAL", 600),
    "oauth-rotator-tick": ("CLAUDE_PLUGIN_OPTION_DAEMON_OAUTH_TICK_INTERVAL", 60),
    "memory-guard": ("CLAUDE_PLUGIN_OPTION_DAEMON_MEMORY_GUARD_INTERVAL", 120),
    "cache-prune": ("CLAUDE_PLUGIN_OPTION_DAEMON_CACHE_PRUNE_INTERVAL", 21600),
    "rules-cleanup": ("CLAUDE_PLUGIN_OPTION_DAEMON_RULES_CLEANUP_INTERVAL", 3600),
    "github-config-audit": ("CLAUDE_PLUGIN_OPTION_DAEMON_GITHUB_CONFIG_AUDIT_INTERVAL", 21600),
    "session-liveness": ("CLAUDE_PLUGIN_OPTION_DAEMON_SESSION_LIVENESS_INTERVAL", 120),
    "fleet-stop": ("CLAUDE_PLUGIN_OPTION_DAEMON_FLEET_STOP_INTERVAL", 60),
    "cold-cache-clear": ("CLAUDE_PLUGIN_OPTION_DAEMON_COLD_CACHE_CLEAR_INTERVAL", 300),
}


def unabsorbed_chores() -> tuple[str, ...]:
    """The global chores that have NO owner while a live server suppresses the daemon.

    Registry order (which is daemon.py's Task order), so a report reads the same way
    the daemon runs them. This is the set `global-chore-blackout` alarms on: the server
    never claimed them, and the daemon it displaced is the only thing that ran them.
    """
    return tuple(n for n in GLOBAL_CHORES if n not in SERVER_ABSORBED_TASKS)


# A COARSE capability token maps to the chore set it stands for. The server publishes
# `family-a` today, meaning the five family-A chores. A token equal to a CHORE NAME is a
# per-chore claim and is honoured directly, so ai-maestro can migrate chore-by-chore
# without needing a janitor release to recognise each one (asked for on janitor#134).
_CAPABILITY_CHORE_SETS: dict[str, frozenset[str]] = {
    "family-a": SERVER_ABSORBED_TASKS,
}


def _explicit_chore_override() -> bool:
    """True iff a human has set one of the chore/state knobs to a recognised value.

    Distinguishes "an operator asserted this by hand" from "we inferred it from a probe" —
    the only reason the override branch in `claimed_chores` is allowed to claim anything
    without a capability list to read.
    """
    for env_name in (SERVER_CHORES_ENV, SERVER_STATE_ENV):
        value = os.environ.get(env_name, "").strip().lower()
        if value in _TRUE or value in _FALSE:
            return True
    return False


def claimed_chores(*, now: Optional[float] = None) -> frozenset[str]:
    """The chores a live ai-maestro server has actually CLAIMED — not merely "is alive".

    OWNER RULING 2026-08-05, answering janitor#134 ("does the server's responsibility mean
    ALIVE or CLAIMED?"): **it means BOTH.** A chore belongs to the server only while the
    server is running AND has claimed it. The target state is that every chore in
    GLOBAL_CHORES is passed to an ai-maestro equivalent; until one is claimed, the daemon
    keeps it. That makes the handover incremental instead of a cliff.

    FAILS TOWARD COVERAGE, always. No fresh probe, an empty token list, or a token this
    version does not recognise ⇒ the EMPTY set ⇒ the janitor keeps every chore. The
    opposite default is precisely what produced the 10-14 day blackout (ai-maestro#111):
    six chores the server had never claimed were yielded anyway, because the only question
    asked was "is a server alive?", and then ran nowhere. **A chore run twice is wasteful
    and guarded by cross-process file locks; a chore run by nobody is invisible.** When in
    doubt, keep it.
    """
    caps = server_capabilities(now=now)
    if not caps:
        # No probe, or a probe claiming nothing. ONE exception: an operator who has
        # EXPLICITLY forced the chores knob (or the state knob) "up" is asserting by hand
        # that the server owns the absorbed set — there is no capability list to read in
        # that path, and silently degrading the knob to a no-op would break an operator
        # tool rather than fix anything. It is honoured as a claim on the LEGACY absorbed
        # set only, and it can recreate the ai-maestro#111 blackout for the other six
        # chores — which is acceptable only because it takes a deliberate human action,
        # unlike the default that caused it.
        if _explicit_chore_override() and server_runs_chores():
            return SERVER_ABSORBED_TASKS
        return frozenset()
    claimed: set[str] = set()
    for token in caps:
        if token in GLOBAL_CHORES:  # a per-chore claim: exact, preferred
            claimed.add(token)
        else:  # a coarse token, or one we do not know — unknown claims nothing
            claimed |= _CAPABILITY_CHORE_SETS.get(token, frozenset())
    return frozenset(claimed)


def orphaned_chores(*, daemon_alive: bool, now: Optional[float] = None) -> frozenset[str]:
    """The chores NOTHING will run right now, and why they slip through.

    THE RIGHT QUESTION. The first version of the blackout detector asked "which UNABSORBED
    chores are stale?", which catches only one of the two ways a chore ends up ownerless:

      * **yielded into a hole** — the chore IS claimed, but no live server is there to run
        it. Reachable through the explicit operator override, which asserts "the server
        runs chores" with no probe to corroborate it: the daemon then yields all five
        absorbed chores to a server that does not exist.
      * **dropped by an absent daemon** — the chore is NOT claimed, so it belongs to the
        daemon, and the daemon is not running. This is the ai-maestro#111 shape.

    Both are the same defect wearing different clothes: a handover with no receiver. Asking
    per chore "who will run this?" catches both by construction, and cannot be fooled by a
    future arrangement neither case anticipated.

    `daemon_alive` is INJECTED rather than probed here: `global_state` imports this module,
    so reading daemon liveness from inside it would invert that dependency, and the caller
    already knows the answer.
    """
    claimed = claimed_chores(now=now)
    live = server_is_alive(now=now)
    orphans = {
        chore for chore in GLOBAL_CHORES
        if (chore in claimed and not live) or (chore not in claimed and not daemon_alive)
    }
    return frozenset(orphans)


def server_owns_every_chore(*, now: Optional[float] = None) -> bool:
    """True iff a live server has claimed EVERY chore the daemon owns.

    THE condition under which the standalone daemon is genuinely redundant, and therefore
    the only one that may suppress it. While even one chore is unclaimed, suppressing the
    daemon leaves that chore with no runner at all — the composition failure behind
    ai-maestro#111, where a total suppression was paired with a partial absorption.

    There is no two-owner hazard in the gap: the daemon yields each CLAIMED chore
    individually (`claimed_chores`), so a running daemon and a running server never
    execute the same chore, and the cross-process locks remain the backstop.
    """
    return server_is_alive(now=now) and claimed_chores(now=now) >= frozenset(GLOBAL_CHORES)


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
    (`lib/server-liveness.ts`, #100 §6.1): `{"ts", "pid", "capabilities": [...]}`.
    Fresh (`now - ts <= 90`) ⇒ the token frozenset; absent / stale / malformed ⇒ None.
    Since ARCHITECTURE.md rev 4 (TRDD-LU0C5KAR) the TOKEN CONTENT is informational —
    the janitor gates on FILE FRESHNESS alone (`server_is_alive`); this stays the one
    validated probe reader both build on. NEVER raises: this runs inside the daemon
    loop and per-session watchdogs.
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


def server_is_alive(*, now: Optional[float] = None) -> bool:
    """Binary: is an ai-maestro server RUNNING on this machine right now?

    True iff the probe file is present, well-formed, and FRESH (ts within
    LIVENESS_STALE_AFTER_S — the server rewrites it every 30 s, so it goes stale
    within 90 s of an exit or crash). The `capabilities` content is deliberately
    IGNORED: per the owner's 2026-07-17 directive (TRDD-LU0C5KAR), a RUNNING server
    owns every absorbed chore by definition — "any other event is a bug" to fix on
    the server, never a per-chore verification to keep here. Absent / stale /
    malformed ⇒ False ⇒ the janitor runs everything (fail-safe: a machine with no
    visible server must never lose its chores).
    """
    return server_capabilities(now=now) is not None


def server_runs_chores() -> bool:
    """THE binary chore switch (TRDD-LU0C5KAR, owner directive 2026-07-17): must the
    #N daemon yield the absorbed chores (`SERVER_ABSORBED_TASKS`) to the server?

    Owner's rule, verbatim: "by design, if the ai-maestro server is running, those
    chores are its responsibility. so the janitor daemon must switch off those
    chores. any other event is a bug." So: server alive ⇒ yield them ALL; server
    gone ⇒ run them ALL — no per-class capability checks (that design, TRDD-N9YAH5E7,
    was overruled as too complicated), no None tri-state.

    Resolution: `$JANITOR_AIMAESTRO_SERVER_CHORES` override (chores-only knob) →
    `$JANITOR_AIMAESTRO_SERVER_STATE` override (machine-wide knob; also drives the
    fleet-actuation exclusion) → `server_is_alive()`. No memo — the probe is one
    small file read per 60 s daemon tick, and a memo would only delay the handoff
    at a server start/stop boundary. The cross-process file locks
    (oauth-rotator-tick.lock, marketplace-op.lock) remain the collision backstop
    across the 90 s staleness window around those boundaries.
    """
    for env_name in (SERVER_CHORES_ENV, SERVER_STATE_ENV):
        override = os.environ.get(env_name, "").strip().lower()
        if override in _TRUE:
            return True
        if override in _FALSE:
            return False
    return server_is_alive()


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
    """True iff `root` sits inside the agents home — the REGISTRY-FREE harness signal.

    `root` arrives from `fleet_scan.find_janitor_root`, which ALWAYS runs the cwd through
    `os.path.realpath` (a kernel realpath). `agents_home()` builds its answer from `$HOME`
    (or `AIMAESTRO_AGENTS_HOME`) WITHOUT realpath'ing it, so a lexical `==`/`startswith`
    compare is asymmetric: on a host where the agents home is itself reached via a symlink
    (a symlinked `$HOME`, an NFS mount, or an override pointed at `/tmp/...` rather than
    its macOS realpath `/private/tmp/...`) the two strings name the SAME directory yet
    never match — this instance is then treated as NOT harness-owned, the exact
    fail-open-in-the-wrong-direction the daemon's hands-off doctrine above depends on
    getting right. Same lesson as janitor#142's "canonicalize before comparing paths"
    (measured there on ai-maestro's own agent-registry compare, called out as applying to
    the janitor's own tooling too) — resolve `base` here rather than trust it comes in
    canonical.
    """
    if not root:
        return False
    base = os.path.realpath(agents_home())
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
