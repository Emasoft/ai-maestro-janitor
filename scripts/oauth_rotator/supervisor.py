#!/usr/bin/env python3
"""OAuth-rotator supervisor — the governance layer (TRDD-32acd15f, P2).

The user's requirement: *"some process must be responsible for managing it …
verify it is correctly configured … completely automatic, without human, never
stopping … save a log."*

Home = the janitor GLOBAL DAEMON (a periodic Task), because rotating the live
credential (a keychain swap) is a user/global-scope mutation (scope invariant,
issue #7) and the daemon is the always-on singleton, so "without human, never
stopping" holds by construction.

Since TRDD-f892e109 decision 3 the rotation runs as the daemon's 60 s
`oauth-rotator-tick` Task — it REPLACED the launchd agent. There is therefore no
scheduler to install or repair any more, so this supervisor is **alert-only**:
it gathers facts and surfaces the conditions a HUMAN must act on (a pinning env
var that defeats rotation, an opted-in non-macOS host where the keychain swap
cannot run, a no-refresh setup-token nearing expiry).

OPT-IN GATED: a total no-op unless `/janitor-auto-manage-oauth-on` wrote the
`opt-in.flag`. For every janitor install without the rotator it never acts.

Design split (so the decision logic is unit-testable with NO network / keychain /
mocks):
  - `gather_facts()` — all I/O: read the flag, scan env, read slot metadata.
  - `diagnose(facts)` — PURE: facts -> list[Finding]. Heavily unit-tested.
  - `apply(findings, …)` — records + logs the alert findings.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# A pinning env var is read at process start and overrides the keychain, so the
# live `claude` never sees a swapped credential — rotation is silently defeated.
PINNING_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
# A no-refresh setup-token (~1y) cannot be keepalive-refreshed; warn this many
# days ahead so the human re-captures BEFORE it dies (matches the cookie
# reminder's CLAUDE_ROTATOR_SETUP_REMIND_DAYS default).
SETUP_REMIND_DAYS = 30

# F4 (TRDD-7PYTX4E9): alert when the 60s tick hasn't COMPLETED in this long while
# the daemon is alive. The 2026-07-08 tick hung on a keychain ACL prompt and
# stopped silently for 30+ minutes with zero alarms — rotation was dead exactly
# when it was needed. 600s = ten missed beats: far past any transient slowness,
# early enough to matter within a 5h window.
TICK_STALL_ALERT_S = float(os.environ.get("ROTATOR_TICK_STALL_ALERT_S", "600"))

# D3 (TRDD-WBYFTU2L): alert when an account has been unable to SELF-renew (no usable
# refresh path — the cascade's human/browser-dependent RENEW_COOKIE / REAUTH legs) for
# this long. The 2026-07-18 incident: ipazia sat in the renew-cookie leg 232 ticks
# (all day) as a silent plan line — no actor executes that leg and nothing told the
# human — so the fleet ran one account deep until the next deadlock forced a manual
# login. 2h: long enough that a transient refresh flake self-heals first, short
# enough that the human can act well before the fleet thins out.
COOKIE_LEG_ALERT_S = float(os.environ.get("ROTATOR_COOKIE_LEG_ALERT_S", "7200"))


_JANITOR_DATA_DIRNAME = "ai-maestro-janitor-ai-maestro-plugins"


def _rotator_root() -> Path:
    """DELEGATE to rotator.py's smart resolver so the supervisor and the engine agree on
    ONE active state dir (the canonical DATA-dir root, with a legacy-standalone fallback;
    TRDD-7100178d). Only if rotator can't be imported (it always can at runtime) does this
    inline-mirror the same logic, so the supervisor's pure unit tests still resolve a root
    without the engine on the path."""
    rot = _rotator_module()
    if rot is not None:
        return rot._rotator_root()
    raw = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    if raw and _JANITOR_DATA_DIRNAME in raw:
        canonical = Path(raw) / "oauth-rotator"
    else:
        canonical = Path.home() / ".claude" / "plugins" / "data" / _JANITOR_DATA_DIRNAME / "oauth-rotator"
    legacy = Path.home() / ".claude" / "account-rotator"
    if (canonical / "state.json").is_file():
        return canonical
    if (legacy / "state.json").is_file():
        return legacy
    return canonical


def opt_in_present(root: Path | None = None) -> bool:
    """True iff `/janitor-auto-manage-oauth-on` wrote the opt-in flag.

    A single cheap stat — this is the gate the daemon's 60 s
    `oauth-rotator-tick` Task checks before spawning the rotator subprocess, so
    a non-opted-in machine pays nothing per tick.
    """
    root = root or _rotator_root()
    return (root / "opt-in.flag").is_file()


@dataclass(frozen=True)
class SlotFact:
    """Observable, non-secret metadata for one captured account slot."""
    email: str
    has_refresh: bool
    expires_days: float | None  # days until the token's expiresAt, or None
    refresh_failures: int = 0  # consecutive failed keepalive refreshes (TRDD-HJGR4I5W); a dead
    #                            present refresh token escalates to the REAUTH login nudge
    cannot_self_renew_age_s: float | None = None  # D3 (TRDD-WBYFTU2L): seconds this slot has
    #                            continuously lacked a USABLE refresh path (absent, or dead —
    #                            refresh_failures ≥ the cascade's max) → it sits in a
    #                            human/browser-dependent cascade leg. None = self-renewable.


@dataclass(frozen=True)
class Facts:
    """Everything `diagnose` needs, gathered by `gather_facts` (the only I/O)."""
    opt_in: bool
    on_macos: bool
    pinning_env: tuple[str, ...] = ()
    slots: tuple[SlotFact, ...] = ()
    # F4 (TRDD-7PYTX4E9): tick liveness. `tick_completed_age_s` is seconds since the
    # rotator last stamped tick-completed.ts (None = never stamped / unreadable);
    # `daemon_alive` gates the alert — a stale stamp with the daemon DOWN is the
    # daemon's own problem, not a tick stall.
    tick_completed_age_s: float | None = None
    daemon_alive: bool = False
    # TRDD-9T0U3M00: when an ACTIVE ai-maestro server owns the absorbed chores, the janitor
    # daemon YIELDS `oauth-rotator-tick` to it — so the janitor's own stamp goes stale BY
    # DESIGN and a stale stamp is what healthy server-side execution looks like. Defaults
    # False so a standalone host (no server) keeps the F4 alert unchanged.
    server_owns_chores: bool = False


@dataclass(frozen=True)
class Finding:
    """One supervisor conclusion — always an alert a human must act on (the
    rotator self-heals nothing now that the daemon owns the tick). `code` is a
    stable machine code, e.g. 'pinning-env'."""
    code: str
    message: str


def diagnose(facts: Facts) -> list[Finding]:
    """PURE: turn gathered facts into alert findings. No I/O.

    Order: opt-in gate first (no-op when off), then the things that DEFEAT
    rotation entirely (a pinning env var, an opted-in non-macOS host where the
    keychain swap cannot run), then the per-slot credential alerts a human must
    act on.
    """
    if not facts.opt_in:
        return []  # rotator not activated on this machine -> silent no-op
    out: list[Finding] = []

    # A pinning env var overrides the keychain and silently defeats rotation.
    # The daemon cannot unset a user's shell env -> alert only.
    for var in facts.pinning_env:
        out.append(Finding(
            "pinning-env",
            f"${var} is set — it overrides the keychain and DEFEATS rotation. "
            f"Unset it so the rotator's keychain swaps take effect.",
        ))

    if not facts.on_macos:
        # The keychain swap uses macOS `security`; off-mac the opt-in flag is set
        # but rotation cannot run here. Alert rather than thrash.
        out.append(Finding(
            "non-macos",
            "OAuth rotator is opted-in but the keychain swap is macOS-only; "
            "rotation cannot run on this platform.",
        ))
        return out

    # F4 (TRDD-7PYTX4E9): the tick machinery itself must be observed. A stamp that
    # goes stale while the daemon is ALIVE means the tick is hanging (the 2026-07-08
    # keychain-ACL-prompt freeze) or silently failing — rotation is OFF exactly when
    # the user relies on it. None (never stamped) counts as stalled too: once this
    # version ships, every completed tick stamps, so a persistent None is a real
    # signal, not noise.
    #
    # …UNLESS the chore is ABSORBED. TRDD-9T0U3M00: `daemon.py` yields `oauth-rotator-tick`
    # to an active ai-maestro server, so on such a host the janitor's stamp is stale WHENEVER
    # THE SYSTEM IS HEALTHY — the tick is running, just not here. Measured 2026-08-21: this
    # alert claimed "rotation is effectively OFF" against a server that had owned the chore
    # all day, and it cost three consecutive misdiagnoses before `daemon.log` was read. The
    # janitor's `version-update` stamp has the identical property and CLAUDE.md already warns
    # not to read it as a dead daemon; this predicate never got the same guard.
    if facts.daemon_alive and not facts.server_owns_chores and (
        facts.tick_completed_age_s is None or facts.tick_completed_age_s > TICK_STALL_ALERT_S
    ):
        age = ("%.0fs" % facts.tick_completed_age_s) if facts.tick_completed_age_s is not None else "never"
        out.append(Finding(
            "tick-stalled",
            f"the 60s rotator tick has not COMPLETED for {age} (> {TICK_STALL_ALERT_S:.0f}s) "
            f"while the daemon is alive — the tick is hanging or failing; rotation is "
            f"effectively OFF. Check rotator.log and the daemon log.",
        ))

    # Per-slot credential alerts (a human must re-capture / re-auth).
    for s in facts.slots:
        if not s.has_refresh and s.expires_days is not None and s.expires_days < SETUP_REMIND_DAYS:
            out.append(Finding(
                "setup-token-expiring",
                f"{s.email} is a no-refresh setup-token expiring in {s.expires_days:.0f}d "
                f"(< {SETUP_REMIND_DAYS}d) — re-capture a full OAuth login for it.",
            ))
        # D3 (TRDD-WBYFTU2L): the cascade's RENEW_COOKIE / REAUTH legs are human/browser
        # driven BY DESIGN — no daemon actor executes them, so an account stuck there is
        # invisible unless we ALERT. Every supervisor finding is notify-pushed by the
        # daemon, so this line is what reaches the human BEFORE the fleet runs thin.
        if s.cannot_self_renew_age_s is not None and s.cannot_self_renew_age_s > COOKIE_LEG_ALERT_S:
            out.append(Finding(
                "cookie-leg-stuck",
                f"{s.email} has needed a one-time login for "
                f"{s.cannot_self_renew_age_s / 3600.0:.1f}h (> {COOKIE_LEG_ALERT_S / 3600.0:.0f}h) "
                f"— its refresh path is dead and only a human can renew it; run "
                f"/janitor-refresh-cc-logins before the fleet runs out of accounts.",
            ))
    return out


# --------------------------------------------------------------------------
# I/O wrappers (not unit-tested against the live system; exercised at runtime)
# --------------------------------------------------------------------------
def _rotator_module():
    """Import the sibling rotator.py robustly — works both when the daemon already
    put `oauth_rotator/` on sys.path AND when supervisor.py was loaded by file path
    (the test harness). Returns the module, or None to degrade to file-only reads."""
    import sys
    try:
        import rotator  # type: ignore[import-not-found]
        return rotator
    except ImportError:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        try:
            import rotator  # type: ignore[import-not-found]
            return rotator
        except ImportError:
            return None


def _slot_facts(root: Path, now: float) -> tuple[SlotFact, ...]:
    """Read non-secret metadata for every captured slot. Never reads token VALUES
    beyond presence (refreshToken truthiness) + expiresAt.

    Since P4a the token blobs live ENCRYPTED in the OS keychain, so the email list
    comes from the state.json INDEX (root-scoped) — the same source the rotator's own
    cmd_list/cmd_auto enumerate — and each blob is read keychain-first, with a legacy
    plaintext-file fallback for any slot not migrated yet."""
    # KEYCHAIN-SAFETY GATE (TRDD-K3WQ7XM9): refuse to touch the OS keychain unless the user
    # has OPTED IN to rotator auto-management. This is the choke-point BOTH oauth-login-needed
    # and oauth-cookie-reminder reach DIRECTLY (bypassing gather_facts, which already gates on
    # opt_in), so without this gate a "paused" rotator still read the keychain from the
    # heartbeat — and when the login keychain is LOCKED, every such read raises a GUI unlock
    # prompt (the 2026-07-09 flood). gather_facts already checks opt_in before calling here, so
    # this is redundant-safe for it. Reading the keychain is only ever OK once the user has
    # explicitly enabled auto-management; until then "paused" MUST mean zero keychain access.
    if not opt_in_present(root):
        return ()
    emails: list[str] = []
    idx: dict = {}  # the state-index slots map, kept so the per-slot loop can read refresh_failures
    sf = root / "state.json"
    if sf.is_file():
        try:
            parsed = json.loads(sf.read_text()).get("slots")
            if isinstance(parsed, dict):
                idx = parsed
                emails = list(idx.keys())
        except (json.JSONDecodeError, OSError):
            emails = []
    slots_dir = root / "slots"
    if slots_dir.is_dir():  # legacy plaintext files not (yet) reflected in the index
        for f in sorted(slots_dir.glob("*.json")):
            if f.stem not in emails:
                emails.append(f.stem)
    if not emails:
        return ()
    rot = _rotator_module()
    out: list[SlotFact] = []
    for email in emails:
        blob = rot._slot_keychain_read(email) if rot is not None else None
        if blob is None:  # legacy plaintext fallback (pre-migration / no keyring)
            p = slots_dir / (email.replace("/", "_") + ".json")
            if p.is_file():
                try:
                    blob = json.loads(p.read_text())
                except (json.JSONDecodeError, OSError):
                    blob = None
        inner = blob.get("claudeAiOauth", blob) if isinstance(blob, dict) else None
        if not isinstance(inner, dict):
            continue
        has_refresh = bool(inner.get("refreshToken") or inner.get("refresh_token"))
        exp = inner.get("expiresAt") or inner.get("expires_at")
        days: float | None = None
        if isinstance(exp, (int, float)):
            secs = exp / 1000 if exp > 1e12 else exp
            days = (secs - now) / 86400.0
        slot_meta = idx.get(email)
        rf = int(slot_meta.get("refresh_failures", 0)) if isinstance(slot_meta, dict) else 0
        out.append(SlotFact(email=email, has_refresh=has_refresh, expires_days=days, refresh_failures=rf))
    return _track_cannot_self_renew(root, tuple(out), now)


def _track_cannot_self_renew(root: Path, slots: tuple[SlotFact, ...], now: float) -> tuple[SlotFact, ...]:
    """D3 (TRDD-WBYFTU2L): persist the FIRST-SEEN epoch of each slot's cannot-self-renew
    state in `cookie-leg-since.json` and stamp each SlotFact with its continuous age.

    "Cannot self-renew" = no usable refresh path — the refresh token is ABSENT, or present
    but DEAD (refresh_failures ≥ the cascade's max, matching `cascade.classify`'s
    RENEW_COOKIE/REAUTH boundary) — AND the access token is already dead or dies within a
    day (expires_days None/< 1). The runway clause keeps a healthy ~1y no-refresh SETUP
    token (which `setup-token-expiring` already covers at <30d) from tripping a login
    alert it doesn't need. Those cascade legs are human/browser-driven by design, so the
    DURATION in that state is the alert signal: a transient refresh flake clears in
    minutes; ipazia's 2026-07-18 all-day limbo is what this exists to surface. The map is
    pruned to the currently-known slots so retired accounts don't leave stale entries.
    Best-effort I/O: an unreadable/unwritable sidecar degrades to age-unknown (None) —
    never breaks fact gathering."""
    # Sibling-module import, robust to being loaded by file path (the same reason
    # _rotator_module exists): the daemon context has this dir on sys.path; the test
    # harness may not. A missing cascade.py is a broken install — raising is correct.
    try:
        from cascade import DEFAULT_MAX_REFRESH_FAILURES
    except ImportError:
        import sys
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        from cascade import DEFAULT_MAX_REFRESH_FAILURES
    sidecar = root / "cookie-leg-since.json"
    since: dict = {}
    try:
        if sidecar.is_file():
            parsed = json.loads(sidecar.read_text())
            if isinstance(parsed, dict):
                since = parsed
    except (json.JSONDecodeError, OSError):
        since = {}
    updated: dict[str, float] = {}
    stamped: list[SlotFact] = []
    for s in slots:
        no_usable_refresh = (not s.has_refresh) or s.refresh_failures >= DEFAULT_MAX_REFRESH_FAILURES
        dying = s.expires_days is None or s.expires_days < 1.0
        cannot = no_usable_refresh and dying
        if cannot:
            first = since.get(s.email)
            first_f = float(first) if isinstance(first, (int, float)) else now
            updated[s.email] = first_f
            stamped.append(SlotFact(
                email=s.email, has_refresh=s.has_refresh, expires_days=s.expires_days,
                refresh_failures=s.refresh_failures,
                cannot_self_renew_age_s=max(0.0, now - first_f),
            ))
        else:
            stamped.append(s)  # self-renewable → age stays None; any sidecar entry is dropped
    if updated != since:
        try:
            tmp = sidecar.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(updated, indent=0, sort_keys=True))
            tmp.replace(sidecar)
        except OSError:
            pass  # observability state only — never break fact gathering
    return tuple(stamped)


def _tick_completed_age_s(root: Path, now: float) -> float | None:
    """Seconds since the rotator's tick-completed.ts stamp (TRDD-7PYTX4E9 F4), or
    None when the stamp is absent/garbage — which diagnose treats as stalled."""
    try:
        return max(0.0, now - float((root / "tick-completed.ts").read_text().strip()))
    except (OSError, ValueError):
        return None


def _daemon_alive() -> bool:
    """Best-effort: is the global janitor daemon alive? Robust import of
    scripts/lib/global_state (the daemon context already has scripts/ on the path;
    the test harness may not — fail to False, which silences the tick-stalled
    alert rather than false-alarming in unknown contexts)."""
    import importlib
    import sys
    try:
        gs = importlib.import_module("lib.global_state")
    except ImportError:
        lib_dir = str(Path(__file__).resolve().parent.parent / "lib")
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        try:
            gs = importlib.import_module("global_state")
        except ImportError:
            return False
    try:
        return bool(gs.daemon_is_alive())
    except Exception:  # noqa: BLE001 -- observability probe; never crash the supervisor
        return False


def gather_facts(root: Path | None = None, *, now: float | None = None) -> Facts:
    """Collect every observable fact `diagnose` needs. The ONLY I/O entry point."""
    root = root or _rotator_root()
    now = now if now is not None else time.time()
    opt_in = (root / "opt-in.flag").is_file()
    on_macos = (os.uname().sysname == "Darwin") if hasattr(os, "uname") else False
    pinning = tuple(v for v in PINNING_ENV if os.environ.get(v))
    return Facts(
        opt_in=opt_in,
        on_macos=on_macos,
        pinning_env=pinning,
        slots=_slot_facts(root, now) if opt_in else (),
        tick_completed_age_s=_tick_completed_age_s(root, now) if opt_in else None,
        daemon_alive=_daemon_alive() if opt_in else False,
        server_owns_chores=_server_owns_chores() if opt_in else False,
    )


_TICK_CHORE = "oauth-rotator-tick"


def _server_owns_chores() -> bool:
    """Is `oauth-rotator-tick` currently YIELDED to an active ai-maestro server?

    THE SAME PREDICATE `daemon.py::_task_yielded_to_server` uses — `server_runs_chores()` AND
    the chore appearing in `claimed_chores()`. Both halves, because the handover is INCREMENTAL
    (owner ruling 2026-08-05, janitor#134: "it means BOTH"): a live server that has not claimed
    `oauth-rotator-tick` leaves the tick running HERE, so asking only "is a server alive?" would
    suppress the F4 alert for a chore nobody had taken — the silenced-alert form of the
    ai-maestro#111 blackout. The supervisor and the daemon must not disagree about who owns the
    tick, and they only cannot when they evaluate the same two terms.

    Fails to **False** on any import or probe error, which keeps the F4 alert LOUD by default:
    a supervisor that cannot tell whether the chore is absorbed must not silently suppress a
    genuine stall. `scripts/lib` is on sys.path in the daemon context but not necessarily in a
    test harness — same reason `_track_cannot_self_renew` carries its own fallback.
    """
    try:
        import harness_backend
    except ImportError:
        import sys
        lib = str(Path(__file__).resolve().parent.parent / "lib")
        if lib not in sys.path:
            sys.path.insert(0, lib)
        try:
            import harness_backend
        except ImportError:
            return False
    try:
        return bool(
            harness_backend.server_runs_chores()
            and _TICK_CHORE in harness_backend.claimed_chores()
        )
    except Exception:  # noqa: BLE001 - a probe fault must not break fact gathering
        return False


@dataclass
class SupervisorResult:
    """What `apply` did — alert codes recorded + logged (no heals: the daemon
    owns the 60 s tick now, so the supervisor never mutates anything)."""
    alerts: list[str] = field(default_factory=list)


def apply(
    findings: list[Finding],
    *,
    log: Callable[[str], None] = lambda *_a: None,
) -> SupervisorResult:
    """Record + log every alert finding. The supervisor heals nothing now that
    the daemon owns the 60 s tick, so this just surfaces the human-actionable
    conditions (and returns their codes for the daemon / SessionStart log line)."""
    res = SupervisorResult()
    for fnd in findings:
        res.alerts.append(fnd.code)
        log(f"[oauth-supervisor] ALERT {fnd.code}: {fnd.message}")
    return res
