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


@dataclass(frozen=True)
class Facts:
    """Everything `diagnose` needs, gathered by `gather_facts` (the only I/O)."""
    opt_in: bool
    on_macos: bool
    pinning_env: tuple[str, ...] = ()
    slots: tuple[SlotFact, ...] = ()


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

    # Per-slot credential alerts (a human must re-capture / re-auth).
    for s in facts.slots:
        if not s.has_refresh and s.expires_days is not None and s.expires_days < SETUP_REMIND_DAYS:
            out.append(Finding(
                "setup-token-expiring",
                f"{s.email} is a no-refresh setup-token expiring in {s.expires_days:.0f}d "
                f"(< {SETUP_REMIND_DAYS}d) — re-capture a full OAuth login for it.",
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
    emails: list[str] = []
    sf = root / "state.json"
    if sf.is_file():
        try:
            idx = json.loads(sf.read_text()).get("slots")
            if isinstance(idx, dict):
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
        out.append(SlotFact(email=email, has_refresh=has_refresh, expires_days=days))
    return tuple(out)


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
    )


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
