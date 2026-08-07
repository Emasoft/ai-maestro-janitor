#!/usr/bin/env python3
"""Claude Code multi-subscription account rotator.

Captures the OAuth credential blob Claude Code stores in the macOS keychain
(service "Claude Code-credentials") whenever it changes (i.e. after a /login
or a token refresh), identifies which account it belongs to via the
/api/oauth/claude_cli/roles endpoint, and files it into a per-account 0600
slot. Lets you switch the live credential to a chosen account.

Storage model
-------------
- LIVE credential: keychain item  service="Claude Code-credentials"
  account=<macOS user>.  Owned/managed by Claude Code itself.
- SLOTS (our backups): OS keychain items  service="Claude Code-rotator-slot"
  account=<email> — ENCRYPTED at rest (P4a). Legacy plaintext
  ~/.claude/account-rotator/slots/<email>.json files are migrated in then deleted
  (`migrate-slots` / `delete-plaintext-slots`); a 0600-file fallback is used ONLY
  on Linux without a keyring.
- STATE (no secrets): ``<root>/state.json`` — emails, sha256 token fingerprints
  (not tokens), timestamps, expiresAt. ``<root>`` is the canonical janitor DATA dir
  ``~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/oauth-rotator``
  (TRDD-7100178d); the pre-migration standalone ``~/.claude/account-rotator/`` is read
  as a fallback and promoted by `migrate-root`. NEVER keyed off a foreign plugin's
  ``CLAUDE_PLUGIN_DATA`` (the codex-clobber bug).

Safety invariants
-----------------
- Never prints or logs a token value.
- Never puts a token in argv (so `ps` cannot see it). READS use `security
  find-generic-password -w` (the secret comes back on STDOUT, not argv).
  WRITES (live credential AND per-account slots) use `security
  add-generic-password` with `-w` at the END of the command, which makes
  `security` read the secret from STDIN (data + retype-confirm) instead of
  taking it as an argv value — see `_security_add_password_via_stdin`. The
  Linux/Windows fallbacks pass the secret via `secret-tool ... <stdin>` or
  write a `0o600` file; in no path does a token transit argv.
- `capture --only-if-claude-running` no-ops unless the real Claude Code binary
  (path under /share/claude/versions/) is running — matched precisely so the
  rotator's own path under ~/.claude/ never self-matches.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

# scripts/lib holds janitor_integrity (backup + corruption-recovery, TRDD-7100178d); the
# sibling `cascade` lives in THIS dir (scripts/oauth_rotator). rotator.py runs standalone
# (`uv run …/rotator.py`), under the daemon, AND under a test that loads it by importlib
# spec — the two inserts below make BOTH imports resolve in all three. The own-dir insert is
# load-bearing: importlib spec-load does NOT auto-add the file's directory, so without it
# `import cascade` depended on another test (test_cascade.py) inserting the path first — a
# hidden ordering leak that broke running test_oauth_rotator.py in isolation. janitor_integrity
# is pure-stdlib, so it adds no PEP-723 deps.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # this dir — so `import cascade` resolves under any loader
import burn_gate  # noqa: E402  # scripts/oauth_rotator/burn_gate.py — pure fast-burn/learned-cap gate (TRDD-FQXBURNR)
import cascade  # noqa: E402  # scripts/oauth_rotator/cascade.py (ROTATE→RENEW→REAUTH SSOT, TRDD-dfc0959a)
import global_state as gs  # noqa: E402  # scripts/lib/global_state.py (rotator-tick single-writer flock, audit §3.4)
import janitor_integrity as integrity  # noqa: E402  # scripts/lib/janitor_integrity.py
import safe_storage  # noqa: E402  # scripts/oauth_rotator/safe_storage.py — keychain_scope_args() lever (TRDD-K3WQ7XM9 FIX B)
import token_burn  # noqa: E402  # scripts/lib/token_burn.py — scoped_rotation_veto (TRDD-QE390SJA)
import usage_probe  # noqa: E402  # scripts/lib/usage_probe.py (throttled /api/oauth/usage, TRDD-WEBA1RMF)

KEYCHAIN_SERVICE = "Claude Code-credentials"
# Per-account slot tokens are stored in the OS keychain too — ENCRYPTED at rest,
# keyed by this service + the account EMAIL (NOT plaintext 0600 files, which malware
# running as the user, backups, and Time Machine can all read). Mirrors the LIVE
# credential's keychain helpers. One-time move: migrate_slots_to_keychain().
# Env-overridable ONLY so tests can target a throwaway keychain service and clean it
# up — production always uses the default.
SLOT_KEYCHAIN_SERVICE = os.environ.get("CLAUDE_ROTATOR_SLOT_KEYCHAIN_SERVICE", "Claude Code-rotator-slot")
# A second keychain service holding a REDUNDANT MIRROR of every slot token (TRDD-7100178d,
# Pillar 2, Decision 2). write_slot writes both; read_slot falls back to this when the
# primary keychain item is missing/corrupt (e.g. deleted via Keychain Access). Encrypted
# at rest, same as the primary — no plaintext reintroduced. Env-overridable for tests only.
SLOT_BACKUP_KEYCHAIN_SERVICE = os.environ.get("CLAUDE_ROTATOR_SLOT_BACKUP_KEYCHAIN_SERVICE", "Claude Code-rotator-slot-backup")
# A third keychain service holding a REDUNDANT MIRROR of the LIVE credential blob
# (TRDD-7100178d, Pillar 2). write_live_blob mirrors here on every switch, the tick's
# integrity-repair pass refreshes it from the current live credential, read_live_blob falls
# back to it, and _repair_integrity RESTORES the primary live keychain item from it when the
# primary is missing/corrupt. Keychain-only — never writes ~/.claude/.credentials.json, so
# the macOS live-re-read property (Claude clears its cache off that file's ABSENCE) is kept.
# Env-overridable for tests only.
LIVE_BACKUP_KEYCHAIN_SERVICE = os.environ.get("CLAUDE_ROTATOR_LIVE_BACKUP_KEYCHAIN_SERVICE", "Claude Code-credentials-livebak")


class SlotKeychainWriteError(RuntimeError):
    """A keychain/keyring was PRESENT but refused a slot write — fail CLOSED.

    Raised by write_slot when _slot_keychain_write reports KEYCHAIN_WRITE_FAILED
    (a locked keychain, a declined ACL prompt, a `security` non-zero exit). The
    caller must NOT fall back to a plaintext slot file in this case — that would
    silently re-create exactly the plaintext token files the P4a migration +
    delete-plaintext-slots removed. The plaintext fallback is reachable ONLY when
    the keychain is genuinely ABSENT (off-mac, no keyring)."""


# Distinct, truthy sentinel returned by _slot_keychain_write when a keychain that
# IS present FAILS the write (vs plain False = "no keychain accepted it, the
# off-mac plaintext fallback is legitimate"). A unique object so callers can tell
# the three outcomes apart: True (stored), False (no keychain → fallback OK), and
# KEYCHAIN_WRITE_FAILED (keychain present but failed → fail closed). SECURITY-critical
# (audit §3.1): it stops a transient keychain hiccup from dropping a plaintext token.
KEYCHAIN_WRITE_FAILED = object()
ROLES_URL = "https://api.anthropic.com/api/oauth/claude_cli/roles"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"
# OAuth client config — CANONICAL HOME (slot_capture_browser.py aliases these). Verbatim from
# the audited claude-login-automation ref. Used by the F2b refresh-token keepalive exchange.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"

# The janitor plugin's OWN data dir, resolved by its FIXED install name. This is the
# documented stable per-plugin DATA path (plugins-reference#environment-variables): it
# survives plugin/marketplace/version updates and is purged only on uninstall.
_JANITOR_DATA_DIRNAME = "ai-maestro-janitor-ai-maestro-plugins"


def _canonical_rotator_root() -> Path:
    """The CANONICAL state dir: ``${CLAUDE_PLUGIN_DATA}/oauth-rotator`` — but ONLY when
    the ambient ``CLAUDE_PLUGIN_DATA`` actually points at THIS plugin's data dir. Any
    other plugin's value is ignored and the path is derived from the fixed install name
    instead. (TRDD-7100178d: a foreign plugin — codex — exports the reserved
    ``CLAUDE_PLUGIN_DATA`` into the global session env via its SessionStart hook, so a
    long-lived detached daemon inherits codex's value and would otherwise resolve to
    ``…/codex-openai-codex/oauth-rotator`` and find zero accounts.)"""
    raw = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    if raw and _JANITOR_DATA_DIRNAME in raw:
        return Path(raw) / "oauth-rotator"
    return Path.home() / ".claude" / "plugins" / "data" / _JANITOR_DATA_DIRNAME / "oauth-rotator"


def _legacy_rotator_root() -> Path:
    """The pre-TRDD-7100178d standalone root. Kept as a read fallback + migration source
    so an install whose state still lives here keeps working until it is migrated."""
    return Path.home() / ".claude" / "account-rotator"


def _rotator_root() -> Path:
    """The ACTIVE state dir. Prefer the canonical DATA-dir root; fall back to the legacy
    standalone root when IT (and not the canonical one) holds ``state.json``, so a
    not-yet-migrated install never silently points at an empty dir and loses its slots.
    A fresh install writes to the canonical root. NEVER trusts a foreign plugin's
    ``CLAUDE_PLUGIN_DATA`` (see _canonical_rotator_root)."""
    canonical = _canonical_rotator_root()
    if (canonical / "state.json").is_file():
        return canonical
    legacy = _legacy_rotator_root()
    if (legacy / "state.json").is_file():
        return legacy
    return canonical


def configured_rotator_home() -> Path | None:
    """The rotator home the daemon ACTUALLY uses, or None when none is configured (opt-in by
    presence). This is the SINGLE SOURCE OF TRUTH the user-facing detectors (oauth-login-needed,
    oauth-cookie-reminder) MUST resolve through, so they read the SAME state.json the daemon does.

    The detectors used to resolve their OWN home `~/.claude/account-rotator` FIRST, opposite to
    `_rotator_root()`'s canonical-first order. On a MIGRATED install both state.json files exist
    (migrate_root_to_canonical keeps the legacy copy non-destructively), so the detector read the
    STALE legacy file (e.g. refresh_failures=0) while the daemon read the live CANONICAL file
    (refresh_failures over the dead-refresh threshold) — the detector classified the account
    healthy and the REAUTH login-nudge NEVER reached the user even though the daemon was nudging
    internally every tick (TRDD-5EUYV08H). Delegating here also inherits `_canonical_rotator_root`'s
    foreign-`CLAUDE_PLUGIN_DATA` guard (TRDD-7100178d), which the detectors' own resolver lacked.

    `CLAUDE_ROTATOR_HOME` (the tests' + the standalone seed-login setup's explicit override) still
    wins when it holds a state.json; otherwise the daemon's canonical-first resolution applies.
    Returns None when no state.json exists anywhere — the opt-in-by-presence semantic the detectors
    rely on to stay a silent no-op on a machine with no rotator configured."""
    env_home = os.environ.get("CLAUDE_ROTATOR_HOME", "").strip()
    if env_home and (Path(env_home) / "state.json").is_file():
        return Path(env_home)
    root = _rotator_root()
    return root if (root / "state.json").is_file() else None


def migrate_root_to_canonical() -> tuple[Path, Path, bool]:
    """One-time: copy ``state.json`` + ``opt-in.flag`` from the legacy standalone root
    into the canonical DATA-dir root (atomic, NON-destructive — the legacy copy is kept
    so a rollback is trivial and no credential state can be lost). No-op if the canonical
    root already has ``state.json``, if the legacy root has none, or if the two roots are
    the same. Keychain slots are root-independent (P4a) so they need no move. Returns
    ``(legacy, canonical, migrated)``."""
    canonical = _canonical_rotator_root()
    legacy = _legacy_rotator_root()
    if canonical == legacy:
        return legacy, canonical, False
    if (canonical / "state.json").is_file():
        return legacy, canonical, False  # already migrated
    if not (legacy / "state.json").is_file():
        return legacy, canonical, False  # nothing to migrate
    canonical.mkdir(parents=True, exist_ok=True)
    for name in ("state.json", "opt-in.flag"):
        src = legacy / name
        if not src.is_file():
            continue
        dst = canonical / name
        tmp = dst.with_suffix(dst.suffix + ".tmp.%d" % os.getpid())
        tmp.write_bytes(src.read_bytes())
        if name == "state.json":
            os.chmod(tmp, 0o600)
        os.replace(tmp, dst)
    return legacy, canonical, True


ROOT = _rotator_root()
SLOTS = ROOT / "slots"
STATE_FILE = ROOT / "state.json"

# Persistent decision log (TRDD-924645bb). The daemon runs the 60s tick as a
# subprocess whose stdout is NOT retained, so the rotator's per-tick decision —
# printed by cmd_auto — used to vanish, leaving NO durable trail (the reason the
# overnight failure was undiagnosable; see TRDD-5539cd6e). `_decide()` mirrors
# every decision both to stdout (manual runs + daemon stdout) AND to this file.
LOG_FILE = ROOT / "rotator.log"
_LOG_MAX_BYTES = 256 * 1024  # rotate at this size — bounds the unattended 60s-cadence log


def _log(msg: str) -> None:
    """Append a timestamped line to the persistent rotator log.

    Rotates (never read-modify-writes) so the file stays bounded under the daemon's
    60s cadence AND under a SECOND appender (janitor#177): as of the ai-maestro
    server's own decision-log.ts, `rotator.log` has two independent writers. The
    former approach — read the last N bytes into memory, then os.replace a tmp file
    over LOG_FILE — silently DISCARDS anything the other writer appended in the
    window between that read and the replace, and asymmetrically: it always eats
    the OTHER writer's lines, because we are the one trimming. `os.replace(LOG_FILE,
    ...".1")` is a pure rename: nothing is read, so nothing in that window can be
    lost, and a writer holding an O_APPEND fd on the OLD inode (ours mid-write, or
    the other process racing us) simply keeps writing into the rotated file rather
    than into the void. Best-effort by design: a log-IO error must NEVER crash a
    rotation decision — the decision is already on stdout, so we report the log
    failure to stderr and carry on. This is deliberate separation of an
    observability side-channel from the critical path, NOT a fallback of the core
    rotation logic. SECURITY: callers pass decision strings (emails + usage %s +
    fingerprints) — NEVER token values; the log shares state.json's trust boundary
    (under CLAUDE_PLUGIN_DATA, gitignored, user-only)."""
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S%z"), msg))
        if LOG_FILE.stat().st_size > _LOG_MAX_BYTES:
            # Rename, not read+rewrite: any appender (including one racing us right
            # now) that holds a fd on the CURRENT inode keeps writing into the file
            # under its new name — worst case a few lines land in rotator.log.1,
            # which is recoverable, never destroyed.
            os.replace(LOG_FILE, ROOT / "rotator.log.1")
    except OSError as exc:
        print("rotator: decision-log append failed (non-fatal): %r" % (exc,), file=sys.stderr)


def _decide(msg: str) -> None:
    """Emit one rotation DECISION: print to stdout AND append to the persistent log.

    Use for every terminal cmd_auto/keepalive outcome so an unattended overnight run
    leaves a durable, examinable trail of exactly-one decision per tick."""
    print(msg)
    _log(msg)


# Auto-rotation thresholds (percent of a usage window consumed, 0-100). The
# rotator switches the live credential to an alternate slot once the LIVE
# account crosses SWITCH_AT on EITHER the 5-hour or the 7-day window —
# proactively, BEFORE a hard 429 stalls a turn. It only switches onto an
# alternate whose own usage is below SAFE on BOTH windows, so we never jump
# to an account that is itself nearly exhausted.
#
# THE WINDOWS ARE NOT EQUALLY PRECIOUS (owner directive 2026-07-18, the overnight
# stall). The 7-DAY window is the scarce one: 1% of it is hours of tokens, 10% is
# most of a day — so an account at 90% 7d still has ~0.7 days of usable budget and
# MUST NOT be rejected as a rotation target. The 5-HOUR window is cheap: it refills
# every 5h, so being near its top costs at most minutes before it resets. Hence the
# asymmetric thresholds — reject the 7d only at the true wall (99), reject the 5h a
# little earlier (97). Before this, SAFE_5H=SAFE_7D=90 rejected a fresh-5h/90%-7d
# alternate as "not safe", so the rotator sat on a fully-exhausted live account for
# hours logging "all paid accounts maxed" while a usable account waited — the exact
# 3am deadlock this fixes (a fresh /login onto that "unsafe" account worked instantly).
#
# SWITCH_AT must sit AT OR ABOVE SAFE on each window, or we would rotate AWAY from an
# account we would immediately re-ACCEPT as a target (thrash). So SWITCH_AT_7D rises to
# 99 with SAFE_7D; SWITCH_AT_5H stays 97 (headroom for the in-flight turn to finish on
# the old account before the swap propagates — at 99 the 5h turn risks a hard 429
# first). All overridable via env so a loop test can force an immediate switch
# (e.g. ROTATOR_SWITCH_AT_5H=1).
SWITCH_AT_5H = float(os.environ.get("ROTATOR_SWITCH_AT_5H", "97"))
SWITCH_AT_7D = float(os.environ.get("ROTATOR_SWITCH_AT_7D", "99"))
SAFE_5H = float(os.environ.get("ROTATOR_SAFE_5H", "97"))
SAFE_7D = float(os.environ.get("ROTATOR_SAFE_7D", "99"))
# Anti-thrash: minimum seconds between two auto-switches.
MIN_DWELL_S = float(os.environ.get("ROTATOR_MIN_DWELL_S", "60"))
# F2 expiry ladder (TRDD-7100178d, blocker 5): a token within this many hours of its LOCAL
# expiresAt (or already past it) counts as dead/dying. API-INDEPENDENT — read straight off the
# blob — so rotation can fire even when /api/oauth/usage is unreachable. Default 0.5h headroom;
# env-overridable for loop tests.
EXPIRY_GRACE_H = float(os.environ.get("ROTATOR_EXPIRY_GRACE_H", "0.5"))
# F2b keepalive (TRDD-7100178d): proactively refresh a SLOT token once its local runway drops
# below this many hours, so an idle alternate stays valid for an overnight rotation. MUST stay
# below the OAuth access-token lifetime (~8 h) so a freshly-refreshed token isn't immediately
# back in the window (no re-refresh spam). Raised 2 → 6 (TRDD-a6d2fdaf): at 2 h an alternate's
# token could drift API-stale (a 401 while still locally "valid") in the gap between keepalive
# windows, which DEADLOCKED rotation on 2026-06-20 (the live account exhausted, the lone
# alternate excluded for a stale probe). A 6 h horizon refreshes every ~2 h so alternate tokens
# stay fresh long before they can lapse — and 6 < ~8 h keeps the no-spam invariant. The cascade
# classifier reads the SAME constant (cascade_plan keepalive_ahead_h=…), so keepalive and the
# RENEW classification stay consistent. Env-overridable for loop tests.
KEEPALIVE_AHEAD_H = float(os.environ.get("ROTATOR_KEEPALIVE_AHEAD_H", "6"))
# Consecutive _keepalive_refresh failures after which the cascade SSOT treats a slot's refresh
# token as DEAD and escalates it from RENEW_REFRESH to the human REAUTH nudge (TRDD-HJGR4I5W) —
# so a present-but-dead refresh token can never sit as a silent dead rotation alternate. Mirrors
# cascade.DEFAULT_MAX_REFRESH_FAILURES; env-overridable for power users / loop tests.
MAX_REFRESH_FAILURES = int(os.environ.get("ROTATOR_MAX_REFRESH_FAILURES", str(cascade.DEFAULT_MAX_REFRESH_FAILURES)))
# Per-slot cap on AUTO-bootstrap browser LAUNCHES (the RENEW_COOKIE analogue of
# MAX_REFRESH_FAILURES, TRDD-5OJX3SCF / TRDD-HJGR4I5W): a capture that never mints a
# refresh-bearing slot leaves the slot eligible forever, so without a cap the daemon re-opens
# a browser every ~60s tick. After this many launches without success the auto-bootstrap STOPS
# and the oauth-capture-stalled detector nudges the human. Env-overridable for power users / tests.
MAX_BOOTSTRAP_LAUNCHES = int(os.environ.get("ROTATOR_MAX_BOOTSTRAP_LAUNCHES", "3"))
# A 429 on /api/oauth/usage can mean EITHER the account is genuinely rate-limited
# OR our polling tripped the endpoint's own throttle (transient). A genuinely
# maxed account 429s persistently; a throttle clears within a tick. So require
# the live-account 429 to persist across this many consecutive checks before
# treating it as "exhausted" and rotating away — a debounce against false trips.
LIVE_429_DEBOUNCE = int(os.environ.get("ROTATOR_LIVE_429_DEBOUNCE", "2"))
# ALTERNATE-probe 429 debounce (TRDD-WBYFTU2L D1). The 2026-07-18 09:18 deadlock: an
# alternate's single probe 429 was read as "genuinely MAXED" and hard-dropped, while the
# SAME code debounces the live account's 429 as "likely a transient usage-endpoint
# throttle" — both readings cannot be true, and one throttled tick against the only fresh
# alternate deadlocked rotation on a usable fleet. Same default as the live debounce.
ALT_429_DEBOUNCE = int(os.environ.get("ROTATOR_ALT_429_DEBOUNCE", str(LIVE_429_DEBOUNCE)))


# --------------------------------------------------------------------------
# keychain helpers
# --------------------------------------------------------------------------
def _keychain_account() -> str:
    # The account attribute Claude Code uses is the macOS short username.
    return os.environ.get("USER") or os.environ.get("LOGNAME") or ""


def _security_add_password_via_stdin(service: str, account: str, data: str, *, allow_any: bool = False, set_acl: bool = True) -> None:
    """Write a keychain item with `security add-generic-password`, value on argv.

    `allow_any` + `set_acl` (TRDD-EQJPPZ2L) are threaded straight to `_add_password_argv` —
    see there for the full rationale. `set_acl` MUST be True only when the item is being
    CREATED; on an UPDATE of an existing item it MUST be False (a data-only write, no ACL
    flag) or the ACL re-set prompts and hangs the daemon. `allow_any` picks `-A` (slot
    family) vs `-T` (live-cred family) for the create case. The caller
    (`_slot_keychain_write`, `write_live_blob`) decides both via a silent existence probe
    (`_keychain_item_exists`).

    NAME IS HISTORICAL — it now uses argv, NOT stdin. WHY (TRDD-5539cd6e, the
    "rotator never worked" bug): the previous stdin-PROMPT mode (`-w` with no value,
    feeding the secret on stdin) reads via macOS `getpass()`, whose buffer is a hard
    **128 bytes**, so it SILENTLY TRUNCATED every value over 128 bytes. OAuth blobs are
    400-8900 bytes, so EVERY captured slot was a 128-byte corrupt JSON fragment ->
    unreadable -> rotation had no usable alternate. Verified: in=8884 -> stored=128.

    The argv value (`-w data`) is briefly visible in `ps`, but these slot keychain items
    are ALREADY readable by any user process via `security find-generic-password -w` with
    NO prompt (verified) — so the write-time argv exposure adds nothing a local attacker
    couldn't already read at will. The prompt-mode "hardening" was security-theater that
    broke the feature. Callers strip slots to the ~480B claudeAiOauth credential
    (see write_slot), so only that — not the full ~8.8KB MCP-bloated blob — transits argv.
    (A zero-argv-exposure ctypes SecKeychainAddGenericPassword path is a deferred
    hardening, NOT done here — getting ctypes argtypes wrong risks worse than this.)

    Raises subprocess.CalledProcessError on failure (fail-fast); FileNotFoundError if
    `security` is absent (not macOS); subprocess.TimeoutExpired if the write HANGS on a
    locked/prompting keychain (2026-07-09: an unbounded write froze the daemon tick + the
    test suite) — the caller (`_slot_keychain_write`) treats that as KEYCHAIN_WRITE_FAILED
    and fails CLOSED, never dropping a plaintext token.
    """
    # Routed through the Safe Keychain Protocol choke-point (TRDD-K3WQ7XM9 P1): latch
    # short-circuit → hard timeout → latch-on-denial. Preserve this fn's historical
    # exception contract so `_slot_keychain_write` still fails CLOSED on any failure.
    run = safe_storage.run_security(_add_password_argv(service, account, data, allow_any=allow_any, set_acl=set_acl), timeout=5)
    if not run.spawned and not run.denied:
        raise FileNotFoundError("`security` not found")  # not macOS → caller tries secret-tool
    if not run.ok:
        raise subprocess.CalledProcessError(  # latched / hung / denied / non-zero → fail closed
            run.returncode if run.returncode is not None else 1,
            ["security", "add-generic-password"],
        )


def _add_password_argv(service: str, account: str, data: str, *, allow_any: bool = False, set_acl: bool = True) -> list[str]:
    """The `security add-generic-password` argv, as a PURE builder so tests can assert
    its shape without touching a keychain.

    THE CREATE-vs-UPDATE RULE (TRDD-EQJPPZ2L — the definitive rotation-death fix). An
    ACL flag (`-A` or the `-T` partners) is emitted ONLY on CREATE (`set_acl=True`); a
    data-only UPDATE (`set_acl=False`) carries NO ACL flag. WHY this is the whole fix:
    under `-U`, passing ANY ACL flag on an item that ALREADY EXISTS forces macOS to
    re-apply the ACL via `SecKeychainItemSetAccess` — a PRIVILEGED op that PROMPTS every
    single time ("SecKeychainItemSetAccess: User canceled the operation"). The DATA still
    updates; only the ACL re-set prompts. Unattended (daemon tick) that prompt HANGS →
    the 5 s timeout trips `keychain-denied.latch` → every later `security` op
    short-circuits → rotation goes dark (the recurring window-exhaustion incident).
    Proven on throwaway keychains: `create -A`=silent · `update -A`/`-T`=HANGS on the
    SetAccess prompt · `update (no ACL flag)`=silent. The earlier belief that `-T` on
    `-U` was a harmless no-op ("keeps the item's old ACL") was WRONG — it triggers the
    same prompt; fa46a49's `-A`-on-EVERY-write had the identical failure mode and is
    SUPERSEDED by this. The caller decides create-vs-update with a silent attribute-only
    existence probe (`_keychain_item_exists`).

    `allow_any` selects WHICH ACL to set on CREATE: `-A` (allow ANY application) for the
    rotator's OWN slot family (`SLOT_KEYCHAIN_SERVICE` + its backup — USER-APPROVED, so a
    shifting uv-python cache path can never later mismatch the item's ACL and re-prompt),
    vs the two `-T` partners (/usr/bin/security — the binary ALL our reads go through —
    plus the real python) for the live-cred family. It is consulted ONLY when `set_acl`
    is True; on an update no ACL flag is emitted at all, so `allow_any` is irrelevant
    there. `-A` and `-T` are mutually exclusive by intent (allow-all vs a partner list).

    On CREATE the item is born with the chosen ACL; every later data-only update
    preserves it (macOS keeps the existing item's ACL when `-U` carries no ACL flag). A
    user `/login` still REPLACES the live item with a Claude-only-ACL one the daemon
    cannot read — no write-side flag prevents that, which is why the beacon (F2) +
    mirror-source distrust (F1) exist."""
    if set_acl:
        acl = ["-A"] if allow_any else ["-T", "/usr/bin/security", "-T", os.path.realpath(sys.executable)]
    else:
        acl = []  # data-only UPDATE — NO ACL flag → no SecKeychainItemSetAccess → no prompt
    return [
        "security", "add-generic-password", "-U",
        "-s", service, "-a", account,
        *acl,
        "-w", data,
        # Trailing keychain scope (empty in production → argv unchanged; a test's temp
        # keychain when JANITOR_ROTATOR_KEYCHAIN is set — TRDD-K3WQ7XM9 FIX B).
        *safe_storage.keychain_scope_args(),
    ]


def _keychain_item_exists(service: str, account: str) -> bool:
    """True iff a keychain item (service, account) PROVABLY exists — via an attribute-only
    `find-generic-password` (NO `-w`), so it never touches the ACL-protected secret and never
    prompts (the whole reason it is safe to call before every write). TRDD-EQJPPZ2L.

    The write path uses this to choose create-vs-update: an ACL flag (`-A`/`-T`) is set ONLY
    when the item is NEW; re-applying an ACL to an EXISTING item forces `SecKeychainItemSetAccess`,
    which PROMPTS every time (the rotation-death flood). So absence must be PROVEN
    (errSecItemNotFound = rc 44 / "could not be found") — every other outcome (not macOS, a
    latched/hung/denied probe, an odd rc) returns True, "assume it exists", so the write NEVER
    sets an ACL on a maybe-present item: the safe direction is to never risk the prompt. The
    latched/hung branches are moot anyway — the write itself short-circuits/fails-closed there."""
    run = safe_storage.run_security(
        ["security", "find-generic-password", "-s", service, "-a", account, *safe_storage.keychain_scope_args()],
        timeout=5,
    )
    if run.ok:
        return True  # rc 0 → the item exists
    if run.spawned and not run.denied and (run.returncode == 44 or "could not be found" in run.stderr):
        return False  # errSecItemNotFound → PROVEN absent → create with its ACL
    return True  # not macOS / latched / hung / ambiguous → assume exists (never set an ACL flag)


def _primary_secret_read_permitted() -> bool:
    """False when this process must NOT do a PROMPTING `-w` secret read of the ACL-restricted
    primary live item (`Claude Code-credentials`) — TRDD-K3WQ7XM9 FIX B2.

    The daemon sets ``JANITOR_ROTATOR_HEADLESS=1`` for its rotator-tick subprocess. Headless,
    that `-w` read can ONLY ever raise a GUI keychain prompt the daemon cannot answer (it
    hangs, then times out — the ~100× prompt storm the user hit once bug #1 lets the tick
    run). It is pure cost: a headless context can NEVER read Claude's Claude-only-ACL primary
    anyway, so the read was already guaranteed to fail. Skipping it makes read_live_blob()
    fall to the `-T`-accessible `-livebak` mirror (read_live_blob_with_source → source
    "mirror", which cmd_auto's F1 distrust already treats as an untrusted identity) — the
    SAME account resolution the daemon reached AFTER the read failed, now WITHOUT the prompt.
    Unset (a manual / session-context run, hooks, the statusline) → True → byte-identical
    `-w` behavior. Only the READ changes; the credential is never written or modified."""
    raw = os.environ.get("JANITOR_ROTATOR_HEADLESS", "").strip().lower()
    return raw in ("", "0", "false", "no", "off")


def _read_primary_macos_keychain(acct: str) -> dict | None:
    """The macOS `security -w` read of the primary live item, or None if absent / unreadable /
    SKIPPED because headless (FIX B2).

    TIMEOUT is load-bearing (TRDD-7PYTX4E9): reading the SECRET (`-w`) of an item whose ACL
    excludes us raises a GUI prompt — headless, the call HANGS (the 2026-07-08 daemon tick
    froze ~30 min on exactly this). When headless (`_primary_secret_read_permitted()` is
    False), we don't even attempt it — the daemon can never read Claude's Claude-only-ACL
    primary, so the `-w` read is pure prompt-cost; skipping it returns None and read_live_blob
    falls to the -livebak mirror (the same resolution, no prompt)."""
    if not _primary_secret_read_permitted():
        return None
    # Choke-point (TRDD-K3WQ7XM9 P1): latch short-circuit → hard timeout → latch-on-denial.
    run = safe_storage.run_security(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", acct, "-w", *safe_storage.keychain_scope_args()],
        timeout=10,
    )
    if run.ok and run.stdout.strip():
        try:
            return json.loads(run.stdout.strip())
        except json.JSONDecodeError:
            pass
    return None


# `security` renders a timedate attribute BOTH as hex and as a quoted ASCII form:
#   "mdat"<timedate>=0x32303236303731373034303634395A00  "20260717040649Z\000"
# Prefer the quoted form; fall back to decoding the hex, since a `security` build that
# emits only the hex would otherwise silently yield "unknown" forever.
_KEYCHAIN_TIMEDATE_QUOTED = re.compile(r'"(\d{14})Z')
_KEYCHAIN_TIMEDATE_HEX = re.compile(r"=0x([0-9A-Fa-f]+)")


def _parse_keychain_timedate(raw: str) -> float | None:
    """Parse ONE `security` attribute line's timedate into an epoch, or None. PURE.

    The wire form is UTC (`YYYYMMDDHHMMSSZ`), so it is parsed as UTC via calendar.timegm —
    NEVER time.mktime, which would silently apply the LOCAL offset and skew every comparison
    by hours (here: the beacon-vs-credential staleness test would flip near a /login)."""
    m = _KEYCHAIN_TIMEDATE_QUOTED.search(raw)
    stamp = m.group(1) if m else None
    if stamp is None:
        h = _KEYCHAIN_TIMEDATE_HEX.search(raw)
        if h is not None:
            try:
                decoded = bytes.fromhex(h.group(1)).decode("ascii", "ignore")
            except ValueError:
                return None
            m2 = re.search(r"(\d{14})Z", decoded)
            stamp = m2.group(1) if m2 else None
    if stamp is None:
        return None
    try:
        return float(calendar.timegm(time.strptime(stamp, "%Y%m%d%H%M%S")))
    except (ValueError, OverflowError):
        return None


def _primary_last_modified() -> float | None:
    """When the PRIMARY live credential last changed, as an epoch — or None if unknowable.

    The whole point is that this NEVER prompts and NEVER reads the secret (TRDD-6AABK2BG):
      - macOS: an attribute-only `find-generic-password` (NO `-w`) → the `mdat` attribute.
        Same shape/choke-point as _keychain_item_exists; a `-w` read here would reintroduce
        the ACL prompt flood this gate exists to avoid.
      - else: ~/.claude/.credentials.json mtime — on Linux/Windows the primary is a plain
        file, so there is no keychain and no prompt to avoid in the first place.
    None = unknowable (not macOS + no file, latched, hung, item absent); callers must treat
    it as "assume changed" so an unknowable state never SUPPRESSES a needed re-stamp."""
    acct = _keychain_account()
    if acct:
        run = safe_storage.run_security(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", acct, *safe_storage.keychain_scope_args()],
            timeout=5,
        )
        # The attribute dump goes to STDOUT (verified on macOS 15: stderr is empty on rc 0);
        # stderr is still scanned so a future/older `security` that splits them still parses.
        if run.ok:
            for line in (run.stdout + "\n" + run.stderr).splitlines():
                if '"mdat"' in line:
                    ts = _parse_keychain_timedate(line)
                    if ts is not None:
                        return ts
    try:
        return (Path.home() / ".claude" / ".credentials.json").stat().st_mtime
    except OSError:
        return None


def _read_live_primary() -> dict | None:
    """Return the parsed live credential from its PRIMARY store, or None if absent/unreadable.
    read_live_blob() wraps this with the -livebak mirror fallback (Pillar 2).

    Cross-platform, first hit wins (ladder cribbed from the statusline helper):
      1. macOS keychain (account = $USER — precise, and the USER-override the
         capture flow relies on keys off this account attribute).
      2. ~/.claude/.credentials.json — the native store on Linux/Windows.
      3. GNOME Keyring via `secret-tool` — the Linux desktop keyring.
    On macOS the keychain path wins and the others are never reached (unless headless, where
    it is skipped so the daemon never prompts — FIX B2 — and the ladder falls through).
    """
    acct = _keychain_account()
    macos = _read_primary_macos_keychain(acct)
    if macos is not None:
        return macos
    # 2. Linux/Windows credentials file
    cf = Path.home() / ".claude" / ".credentials.json"
    if cf.exists():
        try:
            return json.loads(cf.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    # 3. GNOME Keyring (Linux desktop)
    try:
        r = subprocess.run(
            ["secret-tool", "lookup", "service", KEYCHAIN_SERVICE],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None


def _live_backup_read() -> dict | None:
    """Read the redundant -livebak mirror of the LIVE credential (keychain-only, account =
    $USER). None if absent/unreadable. Reuses the slot keychain helpers — same encrypted
    store, just a different (service, account) pair."""
    return _slot_keychain_read(_keychain_account(), service=LIVE_BACKUP_KEYCHAIN_SERVICE)


def _live_backup_write(blob: dict) -> None:
    """Mirror the LIVE credential into the -livebak keychain service (Pillar 2 in-advance
    backup). Keychain-only — never creates ~/.claude/.credentials.json, so Claude's
    live-re-read property (which keys off that file's ABSENCE on macOS) is preserved."""
    _slot_keychain_write(_keychain_account(), blob, service=LIVE_BACKUP_KEYCHAIN_SERVICE)


def _primary_live_item_absent() -> bool:
    """True ONLY when the primary live credential is PROVABLY absent (TRDD-7PYTX4E9).

    The distinction that matters: an ACL-DENIED primary (unreadable from this
    context) still EXISTS and holds the user's current login — it must never be
    treated as "gone". The probe lists the item WITHOUT `-w`: attribute reads do
    not touch the ACL-protected secret, so this never raises the GUI prompt that
    hangs a headless `-w` read. Anything ambiguous (timeout, odd rc, no `security`
    with a credentials file present) counts as PRESENT — the restore stays refused."""
    acct = _keychain_account()
    # No `-w` → an attribute-only presence probe (never touches the secret, never prompts);
    # still routed through the choke-point so a latched state short-circuits it too.
    run = safe_storage.run_security(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", acct, *safe_storage.keychain_scope_args()],
        timeout=10,
    )
    if not run.spawned and not run.denied:
        # Not macOS (no `security`) — the primary is the credentials file; absent means absent.
        return not (Path.home() / ".claude" / ".credentials.json").exists()
    if run.denied or run.returncode is None:
        return False  # latched / hung — ambiguous; never prove absence
    if run.ok:
        return False  # the item exists (whether or not its secret is readable by us)
    # errSecItemNotFound is rc 44 / "could not be found" — the only proven-absent case.
    return run.returncode == 44 or "could not be found" in run.stderr


def read_live_blob_with_source() -> tuple[dict | None, str]:
    """The live credential PLUS where it came from: ("primary" | "mirror" | "none").

    TRDD-7PYTX4E9 F1: the 2026-07-08 incident proved a DECISION path must never
    consume the -livebak mirror as if it were the primary — a user `/login` writes a
    Claude-only-ACL keychain item the headless daemon cannot read, the silent mirror
    fallback then substitutes a STALE credential, and every identity/usage decision
    downstream operates on the WRONG account (the daemon watched fmuaddib while
    emanuele burned to 100%). Durability fallbacks (cmd_live_email, display paths)
    may keep using read_live_blob(); rotation decisions (cmd_auto) MUST branch on
    the source and treat "mirror" as an UNTRUSTED identity."""
    prim = _read_live_primary()
    if prim is not None:
        return prim, "primary"
    mirror = _live_backup_read()
    if mirror is not None:
        return mirror, "mirror"
    return None, "none"


def read_live_blob() -> dict | None:
    """The live credential, robust against a corrupt/missing primary: the PRIMARY store ladder
    (_read_live_primary) first, then the redundant -livebak mirror (Pillar 2). A read never
    RESTORES the primary — that is _repair_integrity's job at tick start (a deliberate,
    once-per-tick action, not a side effect of every read) — it just always returns a usable
    blob while one survives anywhere. Decision paths that must distinguish a mirror-sourced
    blob use read_live_blob_with_source() instead (TRDD-7PYTX4E9 F1)."""
    return read_live_blob_with_source()[0]


# --------------------------------------------------------------------------
# Live-identity BEACON (TRDD-7PYTX4E9 F2) — the session-context ground truth
# --------------------------------------------------------------------------
# A session-context process (hooks, a manual `rotator.py tick`) CAN read the
# primary keychain item even when the headless daemon cannot (a user /login
# writes a Claude-only-ACL item). The beacon is that context's stamp of WHO is
# live — {fp, email, ts} — so the daemon's mirror-source path (F1) has an
# independent identity source instead of trusting a stale mirror.
BEACON_MAX_AGE_S = float(os.environ.get("ROTATOR_BEACON_MAX_AGE_S", str(24 * 3600)))


def _live_identity_path() -> Path:
    # Resolved at call time off the module-global ROOT so test isolation
    # (monkeypatched ROOT) and the canonical/legacy root split both hold.
    return ROOT / "live-identity.json"


def write_live_identity_beacon(*, now: float | None = None) -> bool:
    """Stamp the live credential's identity from a context that can READ the primary.

    Reads the PRIMARY only — NEVER the mirror (a beacon derived from the mirror would
    launder the very staleness F1 distrusts). Email resolution ladder, cheapest first:
    a slot whose fp matches (free, offline), then /roles (network, ~1s — callers run
    this detached), then state's own record when state.live_fp already matches this
    exact credential. An unresolvable email still yields a useful beacon (the fp lets
    the daemon at least confirm mirror==live). Returns True iff a beacon was written."""
    prim = _read_live_primary()
    if prim is None:
        return False
    fp = fingerprint(prim)
    if not fp:
        return False
    email: str | None = None
    state = load_state()
    for em in state.get("slots", {}):
        sb = read_slot(em)
        if sb is not None and fingerprint(sb) == fp:
            email = em
            break
    if email is None:
        email = account_email(prim)
    if email is None and state.get("live_fp") == fp:
        le = state.get("live_email")
        email = le if isinstance(le, str) else None
    payload = json.dumps(
        {"fp": fp, "email": email, "ts": (now if now is not None else time.time())},
        separators=(",", ":"),
    )
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        target = _live_identity_path()
        tmp = target.with_suffix(".json.tmp.%d" % os.getpid())
        tmp.write_text(payload)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except OSError as exc:
        # Best-effort observability side-channel: never crash a hook/tick over it.
        print("rotator: beacon write failed (non-fatal): %r" % (exc,), file=sys.stderr)
        return False
    return True


def read_live_identity_beacon(*, max_age_s: float | None = None, now: float | None = None) -> dict | None:
    """The last session-stamped live identity, or None when absent/garbage/STALE.

    Staleness matters: an old beacon may predate a /login, and trusting it would
    recreate the wrong-identity failure with extra steps. Default freshness window
    24h (ROTATOR_BEACON_MAX_AGE_S) — SessionStart + every session-context tick
    re-stamp it, so any actively-used machine keeps it fresh."""
    try:
        data = json.loads(_live_identity_path().read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("fp"):
        return None
    ts = data.get("ts")
    if not isinstance(ts, (int, float)):
        return None
    limit = max_age_s if max_age_s is not None else BEACON_MAX_AGE_S
    if ((now if now is not None else time.time()) - ts) > limit:
        return None
    return data


def beacon_needs_restamp(*, primary_mtime: float | None, now: float | None = None) -> bool:
    """Would a re-stamp change anything? PURE — `primary_mtime` is injected (see
    refresh_beacon_if_stale) so the decision is testable without a keychain.

    True iff the beacon is absent/garbage/stale, OR the primary's last-modified is UNKNOWN,
    OR the credential changed after the beacon was stamped (mtime > ts).

    FAIL-OPEN on unknown is deliberate and safe: the re-stamp it triggers attempts a `-w`
    read that the denied-latch short-circuits WITHOUT spawning, so an unknowable state can
    never become a prompt loop — whereas fail-CLOSED would leave a wrong beacon in place,
    which is the exact bug this gate exists to kill (TRDD-6AABK2BG)."""
    beacon = read_live_identity_beacon(now=now)
    if beacon is None:
        return True
    if primary_mtime is None:
        return True
    ts = beacon.get("ts")
    if not isinstance(ts, (int, float)):
        return True
    return primary_mtime > ts


def refresh_beacon_if_stale(*, now: float | None = None) -> bool:
    """Re-stamp the live-identity beacon ONLY when the credential actually changed.

    THE BUG THIS FIXES (TRDD-6AABK2BG): the beacon is only stamped from a context that can
    read the primary, and the sole automatic one is SessionStart — ONCE per session. The
    daemon's own cmd_tick stamp is a guaranteed no-op (it runs headless, so FIX B2 skips the
    primary read by design). So a manual /login mid-session left the beacon FRESH-BUT-WRONG
    for up to BEACON_MAX_AGE_S (24h); _resolve_untrusted_live then matched it against the
    equally-stale mirror, "confirmed" the wrong account, and rotation watched a phantom while
    the real account burned to its cap.

    Returns True iff a beacon was written. The gate keeps the steady state free (one cheap
    attribute read, ZERO `-w` reads); only a real credential change pays for a stamp."""
    before = read_live_identity_beacon(now=now)
    if not beacon_needs_restamp(primary_mtime=_primary_last_modified(), now=now):
        return False
    if not write_live_identity_beacon(now=now):
        return False
    after = read_live_identity_beacon(now=now)
    # Log ONLY a real identity change: an unchanged re-stamp is routine bookkeeping and would
    # bury the durable rotator.log in noise, but a live-account change is exactly the event
    # whose absence made this bug invisible for so long.
    old = (before or {}).get("email")
    new = (after or {}).get("email")
    if after is not None and old != new:
        _decide(
            "beacon: live account changed %s -> %s — re-stamped the session identity beacon "
            "so rotation evaluates the REAL live account (TRDD-6AABK2BG)"
            % (old or "(unknown)", new or "(unknown)")
        )
    return True


def _stamp_tick_completed(*, now: float | None = None) -> None:
    """Record that a tick ran to COMPLETION (TRDD-7PYTX4E9 F4). The supervisor alerts
    when this stamp goes stale while the daemon is alive — the 2026-07-08 tick hung on
    a keychain ACL prompt and stopped silently for 30+ min with zero alarms. A hang
    never reaches this stamp (that is the point); a crash does (a crashed tick FINISHED,
    the failure is visible elsewhere). Best-effort: never crashes the beat."""
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        target = ROOT / "tick-completed.ts"
        tmp = target.with_suffix(".ts.tmp.%d" % os.getpid())
        tmp.write_text("%d" % int(now if now is not None else time.time()))
        os.replace(tmp, target)
    except OSError as exc:
        print("rotator: tick-completed stamp failed (non-fatal): %r" % (exc,), file=sys.stderr)


def write_live_blob(blob: dict) -> None:
    """Overwrite the live credential with `blob`, cross-platform.

    macOS  -> keychain (account=$USER). The blob is fed to `security` via the
              `-w`-at-end-of-command STDIN prompt (see
              _security_add_password_via_stdin), so the token never appears in
              argv / `ps`. Used only for an explicit switch, never the hot path.
    Linux/Windows -> ~/.claude/.credentials.json, written ATOMICALLY. We write
              the file ONLY when the keychain write did not apply (i.e. macOS's
              `security` binary is absent). This is deliberate: creating that
              file ON macOS would defeat the live-re-read property (its ABSENCE
              is what makes Claude's mt1() clear its cache every check). On
              Linux/Windows the file's mtime change is itself the re-read trigger.
    GNOME Keyring is updated best-effort when `secret-tool` is present.
    """
    data = json.dumps(blob, separators=(",", ":"))
    keychain_ok = False
    acct = _keychain_account()
    try:
        # TRDD-EQJPPZ2L: set the `-T` live-cred ACL ONLY when creating the item; a data-only
        # update of the EXISTING live item carries no ACL flag (no SecKeychainItemSetAccess
        # prompt). allow_any stays False → the live cred never gets the slot family's `-A`.
        _security_add_password_via_stdin(
            KEYCHAIN_SERVICE, acct, data, set_acl=not _keychain_item_exists(KEYCHAIN_SERVICE, acct)
        )
        keychain_ok = True
    except FileNotFoundError:
        pass  # not macOS — fall through to file / keyring
    if not keychain_ok:
        cf = Path.home() / ".claude" / ".credentials.json"
        cf.parent.mkdir(parents=True, exist_ok=True)
        tmp = cf.with_suffix(".json.tmp.%d" % os.getpid())
        tmp.write_text(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, cf)
        try:
            subprocess.run(
                ["secret-tool", "store", "--label=Claude Code-credentials", "service", KEYCHAIN_SERVICE],
                input=data,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    # Pillar 2 (TRDD-7100178d): mirror every live write into the redundant -livebak keychain
    # service so a corrupt/deleted primary live item is restorable by _repair_integrity.
    # Keychain-only — does NOT create ~/.claude/.credentials.json (preserves live-re-read).
    _live_backup_write(blob)


# --------------------------------------------------------------------------
# small utils
# --------------------------------------------------------------------------
def _oauth(blob: dict) -> dict:
    return blob.get("claudeAiOauth", {}) if isinstance(blob, dict) else {}


def fingerprint(blob: dict) -> str:
    tok = _oauth(blob).get("accessToken", "")
    return hashlib.sha256(tok.encode()).hexdigest()[:16] if tok else ""


def file_slot(email: str, blob: dict, *, via: str, expires_at, timeout_s: float = 60.0) -> bool:
    """Persist a CAPTURED account — the token into the keychain AND its index entry into
    state.json — as ONE step, under the machine-wide rotator lock.

    The two capture entry points (`slot_capture_browser.py`, `slot_capture_token.py`) each
    used to do this inline and UNLOCKED, while the daemon's 60 s tick mutates the same
    `state.json` under `gs.oauth_rotator_lock()`. That is a lost-update race with two ugly
    outcomes: the tick's read-modify-write can overwrite the capture's entry, ORPHANING a
    freshly captured account (its token sits in the keychain but no slot indexes it, so the
    rotator never uses it) — or the capture's stale snapshot can clobber the tick's write and
    split `state.live_email` from the actual live credential. Those scripts are separate
    PROCESSES that import this module as a library, so they bypass `main()`'s lock entirely;
    only a shared OS-level lock can serialise them (audit §3.4, the same reasoning that put
    the lock in `main()` rather than the daemon's task wrapper).

    Returns False iff the lock could not be taken within `timeout_s` — and NOTHING is written
    on that path, by construction: the keychain write happens inside the lock, so a lost race
    can never leave a half-filed account. The caller reports the failure and the human re-runs.

    MUST NOT be called from inside `main()`'s locked commands (see `oauth_rotator_lock_wait`)."""
    with gs.oauth_rotator_lock_wait(timeout_s) as got:
        if not got:
            return False
        write_slot(email, blob)
        st = load_state()
        st.setdefault("slots", {})[email] = {
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "fp": fingerprint(blob),
            "expires_at": expires_at,
            "via": via,
        }
        save_state(st)
    return True


def expires_in_h(blob: dict) -> float | None:
    exp = _oauth(blob).get("expiresAt")
    if not isinstance(exp, (int, float)):
        return None
    secs = exp / 1000 if exp > 1e12 else exp
    return (secs - time.time()) / 3600


# Heterogeneous values (str | None live_email/live_fp, dict slots, int 429-streak, float
# last_switch_at) → annotate as dict[str, object] so mypy has a concrete element type.
_DEFAULT_STATE: dict[str, object] = {"live_email": None, "live_fp": None, "slots": {}}


def load_state() -> dict:
    """Read the state index with corruption recovery (TRDD-7100178d, Pillar 2). The
    raw bytes come via `integrity.read_or_restore`, which serves the primary when its
    `.sha256` sidecar matches, else restores from the verified `.bak`, else returns
    None. A None (both copies unrecoverable) or a non-dict / JSON-garbage payload
    falls back to the empty default — never crashes the tick. A pre-integrity
    state.json (no sidecar yet) is trusted as-is, so this is backward-compatible."""
    raw = integrity.read_or_restore(STATE_FILE)
    if raw is None:
        return dict(_DEFAULT_STATE)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return dict(_DEFAULT_STATE)
    return data if isinstance(data, dict) else dict(_DEFAULT_STATE)


def save_state(state: dict) -> None:
    """Persist the state index with an in-advance backup: `integrity.backup_and_write`
    snapshots the current file to `<state>.bak` (+ sha256) BEFORE overwriting, writes
    the new content atomically (0600), and records a `<state>.sha256` sidecar so the
    next load can detect corruption."""
    integrity.backup_and_write(STATE_FILE, json.dumps(state, indent=2).encode(), mode=0o600)


def slot_path(email: str) -> Path:
    """Legacy plaintext slot path — kept ONLY for the no-keychain fallback (Linux
    without a keyring) and for migrating pre-keychain `.json` files in."""
    safe = email.replace("/", "_")
    return SLOTS / (safe + ".json")


def _slot_keychain_read(email: str, service: str = SLOT_KEYCHAIN_SERVICE) -> dict | None:
    """Read an account's slot token from the OS keychain (macOS `security`, then
    Linux `secret-tool`) under `service`. None if absent/unreadable."""
    # Choke-point (TRDD-K3WQ7XM9 P1): the SLOT `-w` read was the 2026 flood source (a slot
    # whose ACL broke after account rotation → unbounded hanging reads). The gate makes it
    # impossible: a latched state short-circuits WITHOUT spawning; the FIRST hang sets the
    # latch (hard timeout still bounds that one). On any non-success we fall through to the
    # Linux `secret-tool` branch (a no-op on macOS → None).
    run = safe_storage.run_security(
        ["security", "find-generic-password", "-s", service, "-a", email, "-w", *safe_storage.keychain_scope_args()],
        timeout=5,
    )
    if run.ok and run.stdout.strip():
        try:
            return json.loads(run.stdout.strip())
        except json.JSONDecodeError:
            pass
    try:
        r = subprocess.run(
            ["secret-tool", "lookup", "service", service, "account", email],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None


def _slot_keychain_write(email: str, blob: dict, service: str = SLOT_KEYCHAIN_SERVICE):
    """Store an account's slot token ENCRYPTED in the OS keychain under `service`.

    Three-valued result so callers can distinguish "no keychain" from "keychain
    failed" (SECURITY-critical — audit §3.1):
      * True                  — a keychain/keyring accepted the write.
      * False                 — NO keychain/keyring is present (off-mac, no
                                `secret-tool`); the plaintext-file fallback is legitimate.
      * KEYCHAIN_WRITE_FAILED — macOS `security` IS present but the write FAILED
                                (CalledProcessError: locked keychain, declined ACL,
                                non-zero exit). The caller MUST fail closed and must
                                NOT drop a plaintext token file.
    """
    data = json.dumps(blob, separators=(",", ":"))
    # TRDD-EQJPPZ2L (the definitive rotation-death fix). Two orthogonal ACL decisions:
    #  • WHICH ACL on CREATE — `allow_any`: `-A` (allow-ALL) for the rotator's OWN slot
    #    family (SLOT_KEYCHAIN_SERVICE + backup, USER-approved — a shifting uv-python cache
    #    path can then never re-prompt); `-T` partners for the live-cred family (`-A` there
    #    would expose the ACTIVE session token to every app — a broader, user-only choice).
    #  • WHETHER to set an ACL at all — `set_acl`: ONLY on CREATE. Re-applying an ACL to an
    #    EXISTING item forces SecKeychainItemSetAccess, which PROMPTS every time and —
    #    unattended — hangs the daemon, trips `keychain-denied.latch`, and kills rotation
    #    (fa46a49's `-A`-on-EVERY-write hit this exact wall; it is SUPERSEDED). So probe
    #    existence first (attribute-only → silent) and set the ACL only when the item is
    #    NEW; an existing item is updated DATA-ONLY (no ACL flag) → no prompt. New machines
    #    self-migrate: the first write creates with `-A`, every later write is data-only.
    allow_any = service in (SLOT_KEYCHAIN_SERVICE, SLOT_BACKUP_KEYCHAIN_SERVICE)
    set_acl = not _keychain_item_exists(service, email)
    try:
        _security_add_password_via_stdin(service, email, data, allow_any=allow_any, set_acl=set_acl)
        return True
    except FileNotFoundError:
        pass  # `security` ABSENT → not macOS — try the Linux keyring below
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # `security` PRESENT but the write FAILED (non-zero exit) or HUNG on a
        # locked/prompting keychain then timed out (2026-07-09). Either way we ARE on
        # macOS: do NOT fall through to the Linux keyring and do NOT let write_slot drop a
        # plaintext file — surface the fail-closed sentinel.
        return KEYCHAIN_WRITE_FAILED
    try:
        r = subprocess.run(
            ["secret-tool", "store", "--label", "Claude Code rotator slot", "service", service, "account", email],
            input=data,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _slot_keychain_delete(email: str, service: str = SLOT_KEYCHAIN_SERVICE) -> None:
    """Remove an account's slot token from the keychain `service` (best-effort, both
    stores). Used to forget a retired account and by the keychain tests' cleanup."""
    # Choke-point (TRDD-K3WQ7XM9 P1): best-effort, but still gated so a latched state never
    # spawns `security` and a hung delete bounds+latches like every other op.
    safe_storage.run_security(
        ["security", "delete-generic-password", "-s", service, "-a", email, *safe_storage.keychain_scope_args()],
        timeout=5,
    )
    try:
        subprocess.run(
            ["secret-tool", "clear", "service", service, "account", email],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def write_slot(email: str, blob: dict) -> None:
    """Persist an account's slot token ENCRYPTED in the OS keychain — to BOTH the primary
    and the redundant backup service (Pillar 2, Decision 2), so a deleted/corrupt primary
    keychain item is recoverable from the mirror. Only when no keychain/keyring is present
    (Linux desktop without one) does it fall back to a 0600 plaintext file — never on macOS.

    FAIL CLOSED (audit §3.1): if the keychain IS present but the write FAILS
    (KEYCHAIN_WRITE_FAILED — locked keychain, declined ACL, `security` non-zero exit),
    raise SlotKeychainWriteError instead of dropping a 0600 plaintext token file. Returning
    False (no keychain at all) is the ONLY case that reaches the plaintext fallback, so a
    momentary keychain hiccup can never silently re-create the plaintext slots P4a removed.

    Stores ONLY the `claudeAiOauth` credential (TRDD-5539cd6e): the rotator never needs the
    `mcpOAuth` section (per-MCP-server tokens — ~8KB of bloat), and a small slot limits both
    keychain size and the argv-write exposure. Every rotator helper reaches the credential via
    `_oauth(blob)`, so a `{"claudeAiOauth": {...}}` slot is fully compatible. The ONLY consumer
    that needs the full live blob is `_switch_blob`, which MERGES (preserving the live mcpOAuth)
    rather than overwriting — so a rotation never wipes the user's MCP-server OAuth tokens."""
    inner = _oauth(blob)
    if inner:
        blob = {"claudeAiOauth": inner}  # strip mcpOAuth + any other top-level keys
    primary_ok = _slot_keychain_write(email, blob)
    if primary_ok is KEYCHAIN_WRITE_FAILED:
        # macOS keychain present but refused the write — do NOT write plaintext.
        raise SlotKeychainWriteError("keychain write failed for slot %s — refusing to drop a plaintext token (unlock the keychain / approve the access prompt, then retry)" % email)
    if primary_ok:
        _slot_keychain_write(email, blob, service=SLOT_BACKUP_KEYCHAIN_SERVICE)  # mirror
        return
    p = slot_path(email)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp.%d" % os.getpid())
    tmp.write_text(json.dumps(blob, separators=(",", ":")))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def read_slot(email: str) -> dict | None:
    """Read an account's slot token: primary keychain → backup keychain (Pillar 2 mirror,
    so a deleted/corrupt primary self-recovers) → any LEGACY plaintext file (so
    pre-migration slots stay readable until migrate_slots_to_keychain runs)."""
    blob = _slot_keychain_read(email)
    if blob is not None:
        return blob
    blob = _slot_keychain_read(email, service=SLOT_BACKUP_KEYCHAIN_SERVICE)
    if blob is not None:
        # Primary missing/corrupt but the mirror survived — re-heal the primary.
        _slot_keychain_write(email, blob)
        return blob
    p = slot_path(email)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def migrate_slots_to_keychain() -> list[tuple[str, bool]]:
    """One-time: copy every legacy plaintext `slots/<email>.json` into the keychain
    and VERIFY (read back, compare fingerprint). Does NOT delete the plaintext files
    — the caller removes them only after every entry verifies. Returns [(email, ok)]."""
    out: list[tuple[str, bool]] = []
    if not SLOTS.is_dir():
        return out
    for f in sorted(SLOTS.glob("*.json")):
        email = f.stem
        try:
            blob = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            out.append((email, False))
            continue
        _slot_keychain_write(email, blob)
        back = _slot_keychain_read(email)
        ok = back is not None and bool(fingerprint(blob)) and fingerprint(back) == fingerprint(blob)
        out.append((email, ok))
    return out


def delete_plaintext_slot_files() -> list[str]:
    """Remove the legacy plaintext `slots/*.json` files (security cleanup, only AFTER
    a verified migration). Returns the removed paths."""
    removed: list[str] = []
    if not SLOTS.is_dir():
        return removed
    for f in sorted(SLOTS.glob("*.json")):
        try:
            f.unlink()
            removed.append(str(f))
        except OSError:
            pass
    return removed


def claude_running() -> bool:
    """True iff a real Claude Code CLI process is running.

    Detection matches a process whose argv[0] BASENAME is exactly ``claude``
    (how the launcher/symlink invokes the REPL: ``claude --continue ...``) or
    whose argv carries the versioned binary path (full-path launches:
    ``.../share/claude/versions/<ver>``).

    Why argv[0] basename, not a substring search: the rotator's own process is
    ``python3 .../.claude/account-rotator/rotator.py tick --only-if-claude-running``
    — its argv contains the substrings ``claude`` (in ``.claude`` and in the
    ``--only-if-claude-running`` flag) but its argv[0] basename is ``python3``,
    so it never self-matches. Sibling helpers like ``claude-health-monitor``
    (argv[0] basename ``python3``) and ``claude-<x>`` binaries (basename
    ``claude-x`` != ``claude``) are likewise excluded.
    """
    proc = subprocess.run(["ps", "-eo", "args="], capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        first = line.split()[0]
        if os.path.basename(first) == "claude":
            return True
        if "/share/claude/versions/" in line:
            return True
    return False


def account_email(blob: dict) -> str | None:
    """Resolve the account email via the roles endpoint. Network call."""
    tok = _oauth(blob).get("accessToken")
    if not tok:
        return None
    req = urllib.request.Request(
        ROLES_URL,
        headers={
            "Authorization": "Bearer " + tok,
            "Content-Type": "application/json",
            "anthropic-beta": OAUTH_BETA,
            "User-Agent": "claude-account-rotator",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310 -- hardcoded https Anthropic API endpoint; scheme not attacker-controlled
            data = json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None
    name = data.get("organization_name") or ""
    # "fmuaddib@gmail.com's Organization" -> "fmuaddib@gmail.com"
    marker = "'s Organization"
    if name.endswith(marker):
        return name[: -len(marker)].strip()
    return name.strip() or None


def usage_request(blob: dict) -> tuple[int, dict | None]:
    """Probe /api/oauth/usage. Returns (http_status, data).

    Costs ZERO inference quota (same endpoint as Claude Code's fetchUtilization).
    The STATUS is load-bearing and must NOT be collapsed into None:
      200 -> ("ok", data with five_hour/seven_day utilization)
      429 -> the account is RATE-LIMITED (maxed) — for the LIVE account this is
             precisely the signal to rotate AWAY; for an alternate it means "not
             a safe target".
      401/403/0 -> bad token / network error -> "unknown, don't act".
    `status == 0` means a network/parse failure (no HTTP response).

    The request itself lives in `usage_probe` (TRDD-WEBA1RMF), which caches per account,
    honors the endpoint's back-off, and — load-bearing — sends a `claude-code/*`
    User-Agent. This function used to build the request inline with
    `User-Agent: claude-account-rotator` and no throttle at all, on a 60 s beat. That is
    an aggressive-rate-limit bucket by construction, and the 429 it earns is
    indistinguishable here from a genuinely maxed account: the live account looks maxed
    AND every alternate looks unsafe, so rotation stalls exactly when it is needed (the
    2026-07-18 deadlock, TRDD-WBYFTU2L). The status vocabulary above is unchanged, so the
    LIVE_429_DEBOUNCE / ALT_429_DEBOUNCE logic keeps working as written — a persistently
    maxed account still 429s on every tick, now from the local cooldown at zero request
    cost instead of by re-provoking the endpoint.

    Passing `expires_at` through is a second small win the inline version could not get:
    a credential inside its last 30 s no longer spends a request to learn it is dead.
    """
    tok, exp_s = usage_probe.token_from_blob(blob)
    if not tok:
        return (0, None)
    return usage_probe.probe(tok, exp_s)


def account_usage(blob: dict) -> dict | None:
    """Convenience wrapper for display: the usage dict on HTTP 200, else None."""
    status, data = usage_request(blob)
    return data if status == 200 else None


# refresh_oauth_token failure causes (janitor#228) — HTTPError subclasses URLError, so a bare
# `except URLError` cannot tell a Cloudflare transport refusal, a genuinely revoked refresh
# token, and a plain network blip apart. These four constants are the classifier's whole output
# vocabulary; keep them stable, they are logged into slot state (`last_refresh_failure`).
REFRESH_FAIL_TRANSPORT_REFUSED = "transport-refused"  # CF 403 / error 1010 — retryable, alarming
REFRESH_FAIL_CREDENTIAL_DEAD = "credential-dead"  # 400/401 invalid_grant — human-actionable
REFRESH_FAIL_NETWORK = "network"  # timeout / DNS / connection — retryable, benign
REFRESH_FAIL_MALFORMED = "malformed"  # bad JSON or a 200 with no access token


def classify_refresh_failure(exc: BaseException, body: str = "") -> str:
    """PURE classifier: turn a `refresh_oauth_token` failure into one of the REFRESH_FAIL_*
    causes above, so callers can tell "Cloudflare is blocking us" from "this refresh token is
    dead" from "the network hiccuped" instead of collapsing all three into a bare None.

    `body` is an already-read fallback (the caller may have consumed `exc.read()` itself);
    when `exc` is an HTTPError this function ALSO tries to read the body straight off it —
    defensively, since `.read()` can raise (socket already closed) or return b"" (body
    already consumed upstream). Never raises."""
    if isinstance(exc, urllib.error.HTTPError):
        status = exc.code
        text = body
        if not text:
            try:
                raw = exc.read()
                text = raw.decode("utf-8", "replace") if raw else ""
            except Exception:  # noqa: BLE001 -- defensive: a dead/consumed HTTPError body must never crash the classifier
                text = ""
        low = text.lower()
        if status == 403 or "1010" in text or "banned" in low:
            return REFRESH_FAIL_TRANSPORT_REFUSED
        if status in (400, 401) and ("invalid_grant" in low or "invalid_request" in low):
            return REFRESH_FAIL_CREDENTIAL_DEAD
        return REFRESH_FAIL_NETWORK
    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return REFRESH_FAIL_MALFORMED
    return REFRESH_FAIL_NETWORK  # URLError (non-HTTP) / TimeoutError — plain network trouble


def refresh_oauth_token(blob: dict, *, on_failure: Callable[[str], None] | None = None) -> dict | None:
    """Exchange a SLOT's refreshToken for a fresh token pair at the OAuth token endpoint and
    return a NEW blob (accessToken / refreshToken / expiresAt updated, other inner fields kept),
    or None on any failure (no refreshToken, HTTP/network error, or a response without an access
    token). Fail-soft by design — a keepalive failure must never crash the tick; the slot keeps
    its still-current token and F2a rotates away if it ever lapses.

    `on_failure`, when given, is called with the `classify_refresh_failure` cause on every
    failure path that ACTUALLY ATTEMPTED an exchange — the HTTP/network errors, and a 200 with
    no access token ("malformed"). It is deliberately NOT called for a blob carrying no
    refreshToken at all: no request was made, so there is no failure to classify, and reporting
    a cause there would invent one. (`_keepalive_refresh` skips such slots before calling, so
    that path is unreachable from the keepalive leg anyway.)

    The return contract is UNCHANGED — this still always returns None on failure. Callers use
    `on_failure` only to make the CAUSE visible (janitor#228); it must never change control
    flow here.

    Only ever call this on SLOT tokens. The LIVE credential's refresh is owned by Claude Code;
    refreshing it here would race Claude's own (single-use, rotating) refresh-token grant and
    could invalidate its session — so _keepalive_refresh skips the live account."""
    inner = _oauth(blob)
    rtok = inner.get("refreshToken") or inner.get("refresh_token")
    if not rtok:
        # Not a network/CF/credential failure — there was never a call to make. Nothing to
        # classify, so on_failure is deliberately not invoked here.
        return None
    body = json.dumps(
        {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": rtok,
        }
    ).encode()
    # MUST send a non-default User-Agent: urllib's default Python-urllib/<ver> is banned by
    # Cloudflare at the token endpoint (HTTP 403 / error code 1010 — "banned browser
    # signature"; empirically verified 2026-06-09). Reuse the same UA the /roles + /usage
    # calls already use (which pass CF) so keepalive-refresh isn't silently 1010-blocked.
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "claude-account-rotator"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310 -- hardcoded https OAuth token endpoint; scheme not attacker-controlled
            tok = json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError) as exc:
        if on_failure is not None:
            on_failure(classify_refresh_failure(exc))
        return None
    access = tok.get("access_token") or tok.get("accessToken")
    if not access:
        if on_failure is not None:
            on_failure(REFRESH_FAIL_MALFORMED)
        return None
    expires_at = tok.get("expiresAt")
    if expires_at is None and "expires_in" in tok:
        expires_at = int((time.time() + float(tok["expires_in"])) * 1000)
    # A rotating endpoint returns a NEW refresh token; keep the old one if the response omits it
    # (non-rotating server) so we never lose the ability to refresh again next time.
    new_inner = dict(inner)
    new_inner["accessToken"] = access
    new_inner["refreshToken"] = tok.get("refresh_token") or tok.get("refreshToken") or rtok
    if expires_at is not None:
        new_inner["expiresAt"] = expires_at
    return {"claudeAiOauth": new_inner}


def _util(usage: dict | None, window: str) -> float | None:
    """Extract one window's utilization percent (0-100) from a usage dict."""
    if not isinstance(usage, dict):
        return None
    w = usage.get(window)
    if not isinstance(w, dict):
        return None
    u = w.get("utilization")
    return float(u) if isinstance(u, (int, float)) else None


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_capture(only_if_running: bool) -> int:
    if only_if_running and not claude_running():
        return 0  # silent no-op
    blob, src = read_live_blob_with_source()
    if blob is None:
        return 0
    if src != "primary":
        # F1 (TRDD-7PYTX4E9): NEVER capture the mirror as "the live account". In the
        # daemon context (primary ACL-unreadable) the mirror can be a STALE credential;
        # filing it here would rewrite state.live_email/live_fp from that stale blob on
        # EVERY tick — silently re-poisoning the identity right after any heal (observed
        # live 2026-07-09 00:57: state reverted to the mirror's account overnight).
        # A session-context capture (primary readable) is unaffected.
        _log("capture: primary live credential unreadable — skipping capture (a mirror-sourced blob is never 'the live account'; TRDD-7PYTX4E9 F1)")
        return 0
    fp = fingerprint(blob)
    if not fp:
        return 0
    state = load_state()
    if fp == state.get("live_fp"):
        return 0  # unchanged since last capture; no /roles call
    email = account_email(blob)
    if not email:
        # could not identify; record fp so we don't spam /roles, but do not
        # misfile the blob into an unknown slot.
        state["live_fp"] = fp
        save_state(state)
        print("captured: unidentified account (roles lookup failed); not filed")
        return 0
    write_slot(email, blob)
    # READ-BACK VERIFY (TRDD-5539cd6e): the keychain write silently truncated large blobs to
    # 128B of corrupt JSON for months and nobody noticed because capture never checked. Read
    # the slot back and confirm it round-trips to a usable credential (parses + has a non-empty
    # accessToken whose fingerprint matches what we just wrote). FAIL LOUD rather than recording
    # a corrupt slot as "captured" — the guardrail that would have caught the overnight failure.
    rb = read_slot(email)
    if rb is None or fingerprint(rb) != fp:
        print("capture FAILED: slot for %s did not round-trip (stored value corrupt or unreadable) — NOT recording it. See TRDD-5539cd6e." % email, file=sys.stderr)
        return 1
    eh = expires_in_h(blob)
    state["live_email"] = email
    state["live_fp"] = fp
    state.setdefault("slots", {})[email] = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "fp": fp,
        "expires_at": _oauth(blob).get("expiresAt"),
    }
    save_state(state)
    eh_s = ("~%.1fh" % eh) if eh is not None else "?"
    print("captured: %s (token expires %s)" % (email, eh_s))
    return 0


def cmd_list() -> int:
    state = load_state()
    live = state.get("live_email")
    print("live account: %s" % (live or "(unknown)"))
    slots = state.get("slots", {})
    if not slots:
        print("no slots captured yet")
        return 0
    print("slots:")
    for email, meta in slots.items():
        blob = read_slot(email)
        eh = expires_in_h(blob) if blob else None
        eh_s = ("~%.1fh" % eh) if eh is not None else "?"
        flag = "  <- LIVE" if email == live else ""
        print("  %-32s captured=%s  token-expiry=%s%s" % (email, meta.get("captured_at", "?"), eh_s, flag))
    return 0


def cmd_switch(email: str) -> int:
    blob = read_slot(email)
    if blob is None:
        print("no slot for %r — capture it first (login to that account)" % email)
        return 1
    eh = expires_in_h(blob)
    if eh is not None and eh < 0:
        print("WARNING: %s slot's access token is already expired (%.1fh ago); a live process may need a refresh/restart." % (email, -eh))
    _switch_blob(email, blob, reason="manual switch")
    print("switched live credential -> %s" % email)
    # VERIFIED (binary 2.1.153 + this macOS host): no ~/.claude/.credentials.json
    # exists, so Claude Code's mt1() cache-guard clears the in-memory OAuth cache
    # on every token check and re-reads the keychain. A running `claude` therefore
    # picks up this account on its NEXT turn — no restart required.
    print("note: a running `claude` re-reads the keychain on its next turn (macOS), so it adopts this account without a restart.")
    return 0


def _switch_blob(email: str, blob: dict, reason: str) -> None:
    """Swap the live account to `blob`'s credential and record the switch in state.

    `blob` is a claudeAiOauth-only slot (TRDD-5539cd6e). MERGE it into the CURRENT live
    blob — replace only `claudeAiOauth`, preserving the user's live `mcpOAuth` (and any
    other live top-level keys) — instead of overwriting the whole live credential. Else a
    rotation would wipe the MCP-server OAuth tokens. fingerprint() keys off the accessToken
    inside claudeAiOauth, so the merged live blob and the slot share the same fp (state
    stays consistent, and _reconcile_live_email won't see false drift)."""
    cred = _oauth(blob)
    if cred:
        live = read_live_blob() or {}
        merged = dict(live)
        merged["claudeAiOauth"] = cred
        write_live_blob(merged)
    else:
        write_live_blob(blob)  # degenerate slot (no claudeAiOauth) — write as-is
    state = load_state()
    state["live_email"] = email
    state["live_fp"] = fingerprint(blob)
    state["last_switch_at"] = time.time()
    state["last_switch_reason"] = reason
    state["live_429_streak"] = 0  # new live account starts with a clean debounce slate
    # The ACCOUNT is fixed; the PANES are not (TRDD-UA4FAX67). Panes that hit the wall under
    # the old credential are still sitting at the rate-limit UI, so without this the owner
    # presses the key a successful rotation was supposed to make unnecessary. Stamp only —
    # the daemon's liveness beat owns the decision of whom to wake and how.
    gs.record_rotation_success(int(time.time()))
    save_state(state)
    # F2 (TRDD-7PYTX4E9): the rotator AUTHORED this live write, so it knows the identity
    # with certainty even in a context that cannot read the primary back — stamp the
    # beacon directly instead of via write_live_identity_beacon()'s primary read.
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        target = _live_identity_path()
        tmp = target.with_suffix(".json.tmp.%d" % os.getpid())
        tmp.write_text(json.dumps(
            {"fp": fingerprint(blob), "email": email, "ts": time.time()},
            separators=(",", ":"),
        ))
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except OSError:
        pass  # best-effort observability side-channel — never fail a switch over it


def _usage_row(blob: dict | None) -> tuple[str, str]:
    """Return (5h, 7d) display strings, distinguishing maxed (429) from unknown."""
    if blob is None:
        return ("?", "?")
    status, data = usage_request(blob)
    if status == 429:
        return ("MAX", "MAX")  # rate-limited right now
    if status != 200:
        return ("err", "err")
    fh = _util(data, "five_hour")
    sd = _util(data, "seven_day")
    return (("%.0f%%" % fh) if fh is not None else "?", ("%.0f%%" % sd) if sd is not None else "?")


def cmd_usage() -> int:
    """Print live + every slot's 5h/7d utilization. Zero inference cost.
    `MAX` = the account is rate-limited (429) right now; `err`/`?` = unreachable.
    """
    state = load_state()
    live = state.get("live_email")
    live_blob = read_live_blob()
    rows = []
    if live_blob is not None:
        fh_s, sd_s = _usage_row(live_blob)
        rows.append((live or "(live)", fh_s, sd_s, True))
    for email in state.get("slots", {}):
        if email == live:
            continue
        fh_s, sd_s = _usage_row(read_slot(email))
        rows.append((email, fh_s, sd_s, False))
    if not rows:
        print("no accounts to report")
        return 0
    for email, fh_s, sd_s, is_live in rows:
        flag = "  <- LIVE" if is_live else ""
        print("  %-32s 5h=%-5s 7d=%-5s%s" % (email, fh_s, sd_s, flag))
    return 0


def _blob_locally_expired(blob: dict) -> bool:
    """True iff the blob's token is at/within EXPIRY_GRACE_H of its LOCAL expiresAt (or already
    past it). API-independent (reads expiresAt off the blob) so it answers 'is this credential
    dead?' even with no network — the basis of the F2 'works even if the API is unreachable'
    rotation. A blob WITHOUT an expiresAt returns False: we never declare a token dead on
    missing data (fail-safe; the /usage probe and a 401 remain the authority in that case)."""
    e = expires_in_h(blob)
    return e is not None and e <= EXPIRY_GRACE_H


def is_near_limit(fh: float | None, sd: float | None) -> bool:
    """The LIVE account is 'near a limit' (→ rotate away) once EITHER window
    crosses its switch threshold. Unknown (None) usage on a window never trips
    it — fail-safe: we only rotate on a positive over-threshold signal."""
    return (fh is not None and fh >= SWITCH_AT_5H) or (sd is not None and sd >= SWITCH_AT_7D)


def is_safe_alternate(bfh: float, bsd: float) -> bool:
    """An alternate is a safe rotation TARGET only if it is below SAFE on BOTH
    windows — never jump onto an account that is itself nearly exhausted."""
    return bfh < SAFE_5H and bsd < SAFE_7D


def select_drain_first(
    candidates: list[tuple[str, dict, float, float]],
) -> tuple[str, dict, float, float] | None:
    """DRAIN-FIRST selection (user decision 2026-05-29, TRDD-32acd15f). Among
    already-filtered healthy alternates ``(email, blob, util_5h, util_7d)``,
    pick the one CLOSEST to its own limit — highest utilisation on its tightest
    window, ``max(util_5h, util_7d)`` — so partially-spent accounts are consumed
    before fresh ones and the freshest accounts stay in reserve, maximally
    rested. Pure (no network/keychain) so the rule is unit-testable. Returns the
    chosen tuple, or None when ``candidates`` is empty. On a tie the first
    candidate wins (stable — caller order = slot iteration order)."""
    best: tuple[str, dict, float, float] | None = None
    for cand in candidates:
        if best is None or max(cand[2], cand[3]) > max(best[2], best[3]):
            best = cand
    return best


def _reconcile_live_email(state: dict, live_blob: dict) -> dict:
    """Make state.json agree with the ACTUAL live keychain credential (ground truth).

    The live credential can change WITHOUT the rotator's knowledge: an out-of-band
    `claude` login, a `switch` from another process, or a Tier-3 reauth that wrote the
    refreshed token to the keychain but never updated the index (TRDD-7100178d#6). When
    that happens `state.live_email` / `live_fp` drift away from reality, and every
    consumer that trusts them mislabels — worse, the candidate-list logic in cmd_auto
    would treat the REAL live account as a rotation TARGET and skip the actually-stale
    one. Reconcile here so the real credential always wins, BEFORE any rotation decision.

    Network-cheap: the fingerprint compare is local, so the steady-state path (no drift)
    does zero network and zero writes; `account_email` (/roles) is called at most once per
    genuine drift event.
    """
    real_fp = fingerprint(live_blob)
    if state.get("live_fp") == real_fp:
        return state  # already in sync — steady state, no network, no write
    old_email = state.get("live_email")
    # Resolve the real account's email: Anthropic /roles is ground truth; fall back to a
    # local fingerprint match against known slots.
    real_email = account_email(live_blob)
    if not real_email:
        for em in state.get("slots", {}):
            sb = read_slot(em)
            if sb and fingerprint(sb) == real_fp:
                real_email = em
                break
    if not real_email:
        # F5 (TRDD-7PYTX4E9): the credential CHANGED but its account is unresolvable
        # (roles unreachable AND no slot fp match). The old code pinned the NEW fp
        # onto the OLD email — after which the fp-equality early-return above saw
        # "no drift" forever and the mislabel became permanent. Leave state UNTOUCHED
        # so the drift stays detectable and the next tick retries the resolution.
        _decide(
            "auto: live credential CHANGED (fp %s -> %s) but its account is UNRESOLVABLE "
            "(roles unreachable, no slot fp match) — leaving state unreconciled so the "
            "drift stays detectable; will retry next tick (TRDD-7PYTX4E9 F5)"
            % (state.get("live_fp") or "?", real_fp)
        )
        return state
    state["live_email"] = real_email
    state["live_fp"] = real_fp
    state["live_429_streak"] = 0  # the debounce streak belonged to the stale account
    state["last_reconcile_at"] = time.time()
    save_state(state)
    # _decide (not bare print): a reconcile is a real identity decision — it must land
    # in the durable rotator.log, not just a vanishing subprocess stdout (F4 spirit).
    _decide("auto: reconciled live account — state said %r but the real live credential is %r; state.json corrected" % (old_email, state["live_email"]))
    return state


def _resolve_untrusted_live(mirror_blob: dict, state: dict) -> tuple[dict | None, dict]:
    """The MIRROR-SOURCE decision path (TRDD-7PYTX4E9 F1+F2) — the primary live
    credential was unreadable from this context, so `mirror_blob` is of UNKNOWN
    relation to the account actually in use. Establish the live identity from an
    independent source and return (probe_blob, state):

      - probe_blob is a token OF THE TRUE LIVE ACCOUNT usable for the usage probe
        (the mirror itself when the beacon proves mirror == live; else the live
        account's slot twin, keepalive-refreshed if needed), or
      - None → the identity is unknowable / no usable twin: the caller MUST stay
        put this tick (fail-safe — a wrong stay-put costs one tick; a wrong
        rotation decision on a phantom identity is the 2026-07-08 incident).

    Never trusts the fp=="no drift" shortcut: the stale mirror is EXACTLY the blob
    whose fp matches stale state (the trap that blinded the reconciler)."""
    _decide(
        "auto: ⚠ primary live credential UNREADABLE from this context — using the "
        "-livebak MIRROR; identity untrusted until independently resolved (TRDD-7PYTX4E9 F1)"
    )
    beacon = read_live_identity_beacon()
    mirror_fp = fingerprint(mirror_blob)
    if beacon is not None:
        b_fp = beacon.get("fp")
        b_email = beacon.get("email")
        if b_fp == mirror_fp:
            # The session last saw THIS exact credential live → the mirror IS live.
            if isinstance(b_email, str) and b_email and state.get("live_email") != b_email:
                state["live_email"] = b_email
                state["live_fp"] = b_fp
                state["live_429_streak"] = 0
                save_state(state)
                _decide("auto: live identity confirmed via session beacon: %s (mirror == live credential)" % b_email)
            return mirror_blob, state
        if isinstance(b_email, str) and b_email:
            # The mirror holds a DIFFERENT credential than the true live. Correct the
            # identity from the beacon and probe the live account via its slot twin
            # (same account ⇒ same usage windows).
            if state.get("live_email") != b_email or state.get("live_fp") != b_fp:
                state["live_email"] = b_email
                state["live_fp"] = b_fp
                state["live_429_streak"] = 0
                save_state(state)
            _decide(
                "auto: live identity from session beacon: %s — the mirror holds a DIFFERENT "
                "credential; probing the live account via its slot token (TRDD-7PYTX4E9 F2)" % b_email
            )
            twin = read_slot(b_email)
            if twin is not None and not _blob_locally_expired(twin):
                return twin, state
            if twin is not None and _oauth(twin).get("refreshToken"):
                refreshed, healed = _refresh_and_heal_slot(b_email, twin, state)
                if refreshed is not None and not _blob_locally_expired(refreshed):
                    if healed:
                        save_state(state)
                    return refreshed, state
            _decide(
                "auto: live account %s has no usable slot twin to probe — staying put "
                "this tick (fail-safe; TRDD-7PYTX4E9)" % b_email
            )
            return None, state
        # beacon carries a fp but no email, and the fp differs from the mirror → the
        # true live account is a credential we cannot name or probe. Fall through.
    m_email = account_email(mirror_blob)
    _decide(
        "auto: live identity UNKNOWABLE (no fresh session beacon; the mirror resolves to %s "
        "but its relation to the account in use is unknown) — staying put rather than "
        "deciding on an untrusted identity (TRDD-7PYTX4E9 F1)" % (m_email or "unresolvable")
    )
    return None, state


def _refresh_and_heal_slot(email: str, blob: dict, state: dict) -> tuple[dict | None, bool]:
    """Refresh ONE slot's OAuth token and heal both stores — the shared kernel of cmd_auto's two
    refresh paths (the locally-expired RENEW-before-rotate guard and the refresh-on-err net).

    Returns ``(fresh_blob, index_changed)``:
      - ``fresh_blob`` is ``None`` when the refresh grant yielded nothing — the CALLER decides
        whether to keep the slot as a degraded fallback or drop it (the two call sites differ).
      - otherwise ``fresh_blob`` is the re-minted token and ``write_slot`` has mirrored it to the
        keychain. FAIL-SOFT: a locked/declined keychain is logged and tolerated — the fresh token
        is still returned for in-memory use (a rotation writes the LIVE credential, a DIFFERENT
        keychain item, so a refused slot-write never blocks the decision; same accepted hazard as
        _keepalive_refresh's skip-on-refusal: if the token endpoint ROTATES refresh tokens the
        slot's stored grant may now be spent, but a locked keychain already degrades every persist
        path equally and NOT refreshing would deadlock rotation outright). ``index_changed`` is
        True iff the state.json slot meta (fp/expires_at) was updated — the F3 self-heal invariant,
        and so MUST be persisted by the caller BEFORE any _switch_blob (which re-loads state from
        disk, so an unsaved update would be lost).
    """
    refreshed = refresh_oauth_token(blob)
    if refreshed is None:
        return None, False
    try:
        write_slot(email, refreshed)  # heal the lapsed slot in the keychain (as keepalive would)
    except SlotKeychainWriteError as exc:
        _log("[auto] %s: keychain write refused after refresh (%s) — using fresh token in-memory" % (email, exc))
        return refreshed, False
    meta = state.get("slots", {}).get(email)
    if isinstance(meta, dict):
        meta["fp"] = fingerprint(refreshed)
        meta["expires_at"] = _oauth(refreshed).get("expiresAt")
        # A SUCCESSFUL exchange clears the dead-refresh counter — the SAME invariant
        # _keepalive_refresh enforces (TRDD-HJGR4I5W). cmd_auto's refresh paths are the
        # OTHER place a slot's refresh succeeds, so they must reset it too: a slot whose
        # refresh transiently failed >= MAX_REFRESH_FAILURES (cascade → REAUTH_NUDGE) and is
        # then rescued HERE (refresh-on-err / locally-expired guard) but NOT rotated onto —
        # it loses drain-first or is kept only as a degraded fallback — would otherwise keep
        # refresh_failures >= max forever (keepalive skips it: a freshly-refreshed token is
        # outside KEEPALIVE_AHEAD_H, so it never re-runs the reset), so the cascade nudges the
        # human to manually re-login a now-healthy account — the exact "had to rotate the auth
        # manually" pain TRDD-J9TM3WQK eliminated. Clearing it here strictly REDUCES spurious
        # REAUTH nudges and never touches a token, so it cannot affect live auth.
        meta["refresh_failures"] = 0
        return refreshed, True
    return refreshed, False


def cmd_auto() -> int:
    """Proactive usage-based rotation. No-op unless the LIVE account is near a
    limit AND a safer alternate slot exists. Reads quota from /api/oauth/usage
    (zero inference cost), never switches onto an account that is itself near a
    limit, and honours an anti-thrash dwell guard. Fails safe: unknown usage
    never triggers a switch.
    """
    state = load_state()
    live_blob, live_src = read_live_blob_with_source()
    if live_blob is None:
        _decide("auto: no live credential")
        return 0
    if live_src == "mirror":
        # F1 (TRDD-7PYTX4E9): a mirror-sourced blob is NOT the live identity — resolve
        # it independently (session beacon → slot twin) or stay put. Skips the fp-based
        # reconcile below: the stale mirror's fp matching stale state is exactly the
        # blind spot that let the 2026-07-08 exhaustion go unobserved.
        live_blob, state = _resolve_untrusted_live(live_blob, state)
        if live_blob is None:
            return 0  # fail-safe: identity unknowable this tick — already logged
    else:
        # GROUND-TRUTH RECONCILE (TRDD-7100178d#6 stale-index / live-account drift): the
        # actual live keychain credential is authoritative. Correct state.json to match it
        # BEFORE the decision below, or the candidate list would treat the real live
        # account as a target.
        state = _reconcile_live_email(state, live_blob)
    live_email = state.get("live_email")
    live_status, live_data = usage_request(live_blob)
    fh = _util(live_data, "five_hour")
    sd = _util(live_data, "seven_day")
    fh_s = ("%.0f%%" % fh) if fh is not None else "?"
    sd_s = ("%.0f%%" % sd) if sd is not None else "?"
    live_expired = _blob_locally_expired(live_blob)  # API-independent death signal (F2)
    # `network_up` separates a token-specific failure (401/403/429 — the server answered, so
    # alternate tokens CAN still be usage-probed) from a transport failure (status 0 — no HTTP
    # response, so alternates are unreachable too and we fall back to LOCAL expiry signals).
    network_up = live_status != 0
    # Decide whether the LIVE account must be rotated AWAY from. A 429 is the usage-limit signal
    # (debounced — it can be a transient endpoint throttle); 401/403 is the server rejecting a
    # dead token; a local-expiry hit is an API-independent death signal that lets us rotate even
    # when /usage is unreachable (the user's "must work even if the API is not reachable").
    if live_status == 429:
        streak = int(state.get("live_429_streak", 0)) + 1
        state["live_429_streak"] = streak
        if streak >= LIVE_429_DEBOUNCE and live_email:
            # A DEBOUNCED 429 is a real limit — record where the wall actually was as an
            # effective-cap sample (TRDD-FQXBURNR). The 61%-then-hard-429 incident means the
            # cap can sit far below the configured threshold; learning it makes the next
            # near-limit check on this account honest.
            burn_gate.observe_wall(state, live_email, time.time())
        save_state(state)
        if streak < LIVE_429_DEBOUNCE:
            _decide("auto: live %s returned 429 (streak %d/%d) — likely a transient usage-endpoint throttle, not a real limit; deferring rotation" % (live_email or "(live)", streak, LIVE_429_DEBOUNCE))
            return 0
        near = True
        live_desc = "RATE-LIMITED (429 x%d)" % streak
    elif live_status == 200:
        if state.get("live_429_streak"):
            state["live_429_streak"] = 0
        # Feed the per-tick reading into the burn ring (TRDD-FQXBURNR) BEFORE deciding, so
        # this very tick's sample participates in the slope. Bounded (ring-capped) and
        # persisted with the streak reset in ONE save below.
        if live_email:
            burn_gate.observe(state, live_email, time.time(), fh, sd)
        save_state(state)
        # Usage near a limit OR the token is about to expire locally (proactive pre-expiry swap).
        near = is_near_limit(fh, sd) or live_expired
        live_desc = "5h=%s 7d=%s%s" % (fh_s, sd_s, " +LOCALLY-EXPIRING" if live_expired else "")
        if not near and live_email:
            # The threshold did not trip — ask the burn gate (TRDD-FQXBURNR): a projected
            # wall inside the horizon, or a reading at/over the LEARNED cap bar, rotates
            # NOW. Fail-open by construction: no samples / flat slope / no caps ⇒ None ⇒
            # the pure-threshold behavior above stands byte-for-byte.
            burn_why = burn_gate.live_burn_verdict(state, live_email, time.time())
            if burn_why:
                near = True
                live_desc += " +BURN[%s]" % burn_why
    elif live_status in (401, 403):
        near = True  # server REJECTED the token (expired/invalid) — authoritative death signal
        live_desc = "token REJECTED (HTTP %d) — expired/invalid" % live_status
    elif live_expired:
        near = True  # no HTTP response, but the local expiresAt says the token is already dead
        live_desc = "LOCALLY EXPIRED + API unreachable (status %s)" % live_status
    else:
        _decide("auto: live %s usage unreachable (status %s) but token still valid locally; staying put" % (live_email or "(live)", live_status))
        return 0
    if not near:
        _decide("auto: live %s %s — within limits" % (live_email or "(live)", live_desc))
        return 0
    last = state.get("last_switch_at")
    if isinstance(last, (int, float)) and (time.time() - last) < MIN_DWELL_S:
        _decide("auto: live %s exhausted (%s) but inside dwell window; deferring" % (live_email or "(live)", live_desc))
        return 0
    # Build the alternate-candidate list. A safe TARGET is NEVER itself locally expired. When the
    # network is up we also require a fresh /usage 200 below SAFE on both windows and apply the
    # pure DRAIN-FIRST rule. When the network is DOWN (we are only here because the live token is
    # locally dead) we cannot usage-probe — fall back to LOCAL expiry: any alternate with a known
    # future expiry is a valid target, and we pick the one with the MOST runway.
    candidates: list[tuple[str, dict, float, float]] = []
    # Usage-confirmed, account-healthy targets whose window for the model this session is
    # actually running is spent (TRDD-QE390SJA). A SECOND-CHOICE pool, not a rejection pile —
    # see the tier-1b block below for why they must never be dropped.
    scoped_blocked: list[tuple[str, dict, float, float]] = []
    scoped_veto: dict[str, str] = {}  # email -> the window label that demoted it
    degraded: list[tuple[str, dict, float]] = []  # (email, blob, expires_in_h) — no-usage path
    index_healed = False  # set when refresh-on-err re-mints a slot → index meta must be persisted
    meta_dirty = False  # set when an alt_429_streak changes → index meta must be persisted
    # Per-alternate VERDICTS (TRDD-WBYFTU2L D2): why each examined alternate was (not) usable
    # this tick. Appended to the all-maxed line ONLY — the composite "no alternate is
    # healthy…" verdict without per-account reasons cost a forensic log dig on 2026-07-18.
    verdicts: list[str] = []
    for email in state.get("slots", {}):
        if email == live_email:
            continue
        b = read_slot(email)
        if not b:
            verdicts.append("%s:no-slot" % email)
            continue
        if _blob_locally_expired(b):
            # RENEW-before-rotate (TRDD-1IKF0A6D, lesson [^2] of oauth-rotation-renew-reauth.md):
            # this slot's ACCESS token is locally expired, but it may merely have MISSED a keepalive
            # tick (the daemon was down, a tick was skipped, a transient refresh 1010'd) while its
            # refresh grant is still good. Before excluding it — the documented residual, "a slot
            # excluded EARLIER by the locally-expired guard is not yet refresh-retried" — refresh-
            # retry-then-heal it when it carries a refreshToken AND the network is up (mirroring the
            # refresh-on-err net below), so a lapsed-but-rescuable alternate REJOINS the candidate
            # flow instead of deadlocking rotation. A slot with no refresh grant, an unreachable API
            # (network down → a refresh HTTP call would also fail), a refresh that yields nothing, or
            # a refreshed token STILL locally expired is excluded exactly as before — the guard's
            # invariant (never rotate ONTO a dead/dying token) is preserved.
            if not (network_up and _oauth(b).get("refreshToken")):
                verdicts.append("%s:locally-expired-no-refresh" % email)
                continue
            refreshed, healed = _refresh_and_heal_slot(email, b, state)
            if refreshed is None or _blob_locally_expired(refreshed):
                verdicts.append("%s:refresh-failed" % email)
                continue
            index_healed = index_healed or healed
            b = refreshed
            # fall through: `b` is now a fresh, non-expired token — handled like any candidate below
        if network_up:
            st2, d2 = usage_request(b)
            if st2 not in (200, 429):
                # REFRESH-ON-ERR safety net (TRDD-32acd15f, the 2026-06-11 incident): a non-200,
                # non-429 probe almost always means the alternate's SLOT access token has EXPIRED
                # (401/403). Excluding it here is what deadlocked rotation — "all paid accounts
                # maxed" while a genuinely FRESH alternate sat unusable because its token had lapsed
                # (a keepalive gap, e.g. the daemon running a pre-CF-1010-fix build whose refresh
                # silently 1010'd). Refresh the token and re-probe BEFORE excluding, so one stale
                # access token can never again deadlock rotation. 429 is deliberately NOT refreshed
                # (the account is maxed, not the token expired — a refresh would not help).
                refreshed, healed = _refresh_and_heal_slot(email, b, state)
                if refreshed is None:
                    # The in-tick refresh grant returned nothing. If the slot is
                    # STRUCTURALLY renewable — carries a refresh token AND a future
                    # expiry AND is not locally expired — keep it as a DEGRADED
                    # fallback instead of dropping it outright: the grant may have
                    # failed transiently (CF-1010, a slow/timed-out token endpoint,
                    # a rotating refresh token already spent this tick) and a later
                    # tick's keepalive will re-mint it. A degraded rotate beats
                    # pinning the user to a dead live account — the 2026-06-20
                    # deadlock, where a rescuable alternate was excluded here while
                    # the live account sat at 100%/401. Only a slot that truly
                    # cannot renew (no refresh token) is dropped.
                    _eh = expires_in_h(b)
                    if _oauth(b).get("refreshToken") and _eh is not None and not _blob_locally_expired(b):
                        degraded.append((email, b, _eh))
                        verdicts.append("%s:probe-%s-degraded" % (email, st2))
                    else:
                        verdicts.append("%s:probe-%s-unrenewable" % (email, st2))
                    continue
                index_healed = index_healed or healed
                b = refreshed
                st2, d2 = usage_request(b)  # re-probe with the fresh token
            if st2 != 200:
                # Not a usage-confirmed safe target. Distinguish WHY:
                #  - 429 → DEBOUNCED (TRDD-WBYFTU2L D1): a single probe 429 is just as
                #    likely a transient usage-endpoint throttle for an ALTERNATE as it is
                #    for the LIVE account (whose 429 gets LIVE_429_DEBOUNCE) — reading it
                #    as "genuinely maxed" hard-dropped the only fresh alternate on
                #    2026-07-18 and deadlocked rotation on a usable fleet. Below the
                #    streak: UNKNOWN → keep as a DEGRADED fallback when structurally
                #    valid. At/after the streak: genuinely MAXED → drop (rotating onto a
                #    maxed account is useless).
                #  - else (401/403/0 after a SUCCESSFUL refresh) → the usage probe
                #    failed transiently while we hold a FRESH token; keep it as a
                #    DEGRADED fallback so one bad probe can't pin the user to a dead
                #    live account when a rescuable alternate is right there.
                if st2 == 429:
                    meta = state.get("slots", {}).get(email)
                    streak = 1
                    if isinstance(meta, dict):
                        streak = int(meta.get("alt_429_streak", 0) or 0) + 1
                        meta["alt_429_streak"] = streak
                        meta_dirty = True
                    if streak < ALT_429_DEBOUNCE:
                        _eh = expires_in_h(b)
                        if _eh is not None and not _blob_locally_expired(b):
                            degraded.append((email, b, _eh))
                            verdicts.append("%s:probe-429(x%d,throttle?)-degraded" % (email, streak))
                        else:
                            verdicts.append("%s:probe-429(x%d,throttle?)-expired" % (email, streak))
                    else:
                        verdicts.append("%s:maxed-429(x%d)" % (email, streak))
                else:
                    _eh = expires_in_h(b)
                    if _eh is not None and not _blob_locally_expired(b):
                        degraded.append((email, b, _eh))
                        verdicts.append("%s:probe-%s-degraded" % (email, st2))
                    else:
                        verdicts.append("%s:probe-%s-expired" % (email, st2))
                continue
            meta = state.get("slots", {}).get(email)
            if isinstance(meta, dict) and meta.get("alt_429_streak"):
                meta["alt_429_streak"] = 0  # a 200 proves the endpoint answers → reset the streak
                meta_dirty = True
            bfh = _util(d2, "five_hour")
            bsd = _util(d2, "seven_day")
            if bfh is None or bsd is None:
                verdicts.append("%s:unknown-usage" % email)
                continue  # unknown usage -> not a safe target
            # Feed the alternate's reading into ITS burn ring too (TRDD-FQXBURNR) — probes
            # only happen while a rotation is being considered, so history is sparse, but
            # across consecutive near-ticks it is exactly the slope that predicts whether
            # this candidate walls right after we land on it (the 42→61%-in-3-min shape).
            burn_gate.observe(state, email, time.time(), bfh, bsd)
            meta_dirty = True
            if not is_safe_alternate(bfh, bsd):
                verdicts.append("%s:util(5h=%.0f,7d=%.0f)" % (email, bfh, bsd))
                continue  # itself near a limit -> skip
            rings2 = burn_gate.account_rings(state, email)
            caps2 = burn_gate.account_caps(state, email)
            if any(
                burn_gate.candidate_walls_soon(rings2.get(w, []), caps2.get(w, []), time.time())
                for w in ("5h", "7d")
            ):
                # Below SAFE but burning toward its wall inside the horizon — rotating onto
                # it buys minutes, not a session (the second half of the 2026-07-17
                # incident). Fail-open: sparse history simply never trips this.
                verdicts.append("%s:walls-soon" % email)
                continue
            veto = token_burn.scoped_rotation_veto(
                live_data, d2, int(time.time()), bars={"5h": SAFE_5H, "7d": SAFE_7D}
            )
            if veto:
                # Account-healthy, but its window for the model the LIVE account is
                # demonstrably running is spent: landing here trades one model wall for the
                # same wall on another account. DEMOTED, never dropped — dropping it is the
                # mirror-image bug that sidelined the fleet's healthiest account for ~123h
                # (janitor#222). Availability is decided by the account windows above; this
                # only orders the survivors.
                scoped_blocked.append((email, b, bfh, bsd))
                scoped_veto[email] = veto
                verdicts.append("%s:scoped-spent(%s)" % (email, veto))
                continue
            candidates.append((email, b, bfh, bsd))
        else:
            eh = expires_in_h(b)
            if eh is None:
                continue  # cannot confirm validity offline -> not a safe degraded target
            degraded.append((email, b, eh))
    if index_healed or meta_dirty:
        save_state(state)  # before any _switch_blob (it re-loads state from disk)
    # 1) Best usage-confirmed safe target (DRAIN-FIRST), when the network is up.
    best = select_drain_first(candidates) if network_up else None
    if best is not None:
        target_email, target_blob, bfh, bsd = best
        reason = "live %s %s -> rotate" % (live_email or "(live)", live_desc)
        _switch_blob(target_email, target_blob, reason)
        _decide("auto: switched %s -> %s (target 5h=%.0f%% 7d=%.0f%%; %s)" % (live_email or "(live)", target_email, bfh, bsd, reason))
        return 0
    # 1b) Every usage-confirmed target is spent on the model this session is running. Rotate
    # onto the best of them ANYWAY: their account windows are below safe, so the rotation
    # still buys real runway on every other model, and a model wall answered by a model
    # switch (TRDD-QE390SJA's other half) beats no credential at all. This tier is why the
    # veto above is allowed to exist — without it the veto would be the very
    # sideline-the-fleet bug it was written to avoid.
    if best is None and network_up and scoped_blocked:
        alt = select_drain_first(scoped_blocked)
        if alt is not None:
            target_email, target_blob, bfh, bsd = alt
            label = scoped_veto.get(target_email, "a model window")
            reason = "live %s %s -> rotate (every target spent on %s)" % (live_email or "(live)", live_desc, label)
            _switch_blob(target_email, target_blob, reason)
            _decide("auto: switched %s -> %s (target 5h=%.0f%% 7d=%.0f%%, but its %s is spent — model-scoped runway does NOT improve; switch model to recover it; %s)" % (live_email or "(live)", target_email, bfh, bsd, label, reason))
            return 0
    # 2) DEGRADED fallback — no usage-confirmed target (or the network is down), but a
    # structurally-valid alternate exists (future expiry; its usage probe failed
    # transiently / its token just needs one mint). Rotating onto the most-runway one
    # beats pinning the user to an exhausted/dead live account. THIS is the fix for the
    # 2026-06-20 deadlock: previously the network-up path returned "all paid accounts
    # maxed" here even when a rescuable alternate sat in `degraded`, which was only ever
    # consulted on the no-network path. A degraded rotate writes a fresh live credential
    # and the next tick's keepalive (now on the live slot's twin) keeps it alive.
    if degraded:
        target_email, target_blob, target_eh = max(degraded, key=lambda c: c[2])
        why = "no usage-confirmed target" if network_up else "no usage; API unreachable"
        reason = "live %s %s -> degraded rotate (%s)" % (live_email or "(live)", live_desc, why)
        _switch_blob(target_email, target_blob, reason)
        _decide("auto: switched %s -> %s (degraded; target token valid ~%.1fh; %s)" % (live_email or "(live)", target_email, target_eh, reason))
        return 0
    # 3) Genuinely stuck — nothing rotatable in either path. Name EVERY alternate's verdict
    # (TRDD-WBYFTU2L D2) so the next incident is diagnosable from this one line.
    if network_up:
        detail = ("; ".join(verdicts)) if verdicts else "no alternate slots"
        _decide("auto: live %s exhausted (%s) but no alternate is healthy + below safe threshold and none is structurally renewable — all paid accounts maxed; waiting for a window to reset [%s]" % (live_email or "(live)", live_desc, detail))
    else:
        _decide("auto: live %s is LOCALLY EXPIRED and the API is unreachable, but no alternate with a known future expiry exists — cannot rotate; manual re-auth needed" % (live_email or "(live)"))
    return 0


def _keepalive_refresh() -> list[str]:
    """F2b keepalive: PREVENT slot expiry (vs F2a which RECOVERS from it). For each SLOT whose
    token carries a refreshToken and is within KEEPALIVE_AHEAD_H of expiry, exchange it for a
    fresh token and write it back (write_slot mirrors to the -slot-backup; the state index's
    fp/expires_at are updated). Slots are idle (no live consumer) so this never races anyone.

    The LIVE account is deliberately NOT refreshed here — Claude Code owns its refresh; doing it
    underneath Claude would race its single-use rotating refresh grant. setup-token slots (no
    refreshToken) are skipped (unrefreshable; the supervisor warns on their ~1y expiry). Each
    slot's refresh is best-effort (refresh_oauth_token returns None on failure) and never raises.
    Returns the list of refreshed emails."""
    actions: list[str] = []
    state = load_state()
    slots = state.get("slots") or {}
    live_email = state.get("live_email")
    changed = False
    for email in list(slots.keys()):
        if email == live_email:
            continue  # never refresh the live account out from under Claude Code
        blob = read_slot(email)
        if not blob:
            continue
        inner = _oauth(blob)
        if not (inner.get("refreshToken") or inner.get("refresh_token")):
            continue  # setup-token slot — cannot be refreshed
        eh = expires_in_h(blob)
        if eh is None or eh > KEEPALIVE_AHEAD_H:
            continue  # plenty of runway (or undatable) — leave it
        failure_cause: list[str] = []
        fresh = refresh_oauth_token(blob, on_failure=failure_cause.append)
        if fresh is None:
            # Refresh FAILED — keep the old token (F2a rotates away if it lapses) AND record the
            # failure. A refresh token that keeps failing to exchange is DEAD; N consecutive
            # failures escalate this slot from RENEW_REFRESH to the human REAUTH nudge via the
            # cascade SSOT (TRDD-HJGR4I5W) so a dead alternate is never silent. The counter lives
            # in the slot's state-index meta so it survives daemon restarts; it is reset to 0 on
            # any successful exchange below. `on_failure` (janitor#228) additionally records the
            # CAUSE (transport-refused / credential-dead / network / malformed) so a Cloudflare
            # block is no longer indistinguishable from a genuinely revoked token — this is
            # purely diagnostic and must NEVER change the escalation counter above.
            cause = failure_cause[0] if failure_cause else None
            meta = slots.get(email)
            if isinstance(meta, dict):
                meta["refresh_failures"] = int(meta.get("refresh_failures", 0)) + 1
                if cause is not None:
                    meta["last_refresh_failure"] = cause
                changed = True
            if cause is not None:
                _log("[keepalive] %s: refresh failed (%s)" % (email, cause))
            continue
        try:
            write_slot(email, fresh)
        except SlotKeychainWriteError as exc:
            # FAIL CLOSED (P1): a locked/declined keychain refused the write. Do NOT drop a
            # plaintext token and do NOT crash the unattended tick — keep the old slot token
            # (F2a rotates away if it lapses) and skip the state update for this slot.
            print("[keepalive] %s: keychain write refused (%s) — kept old token, skipped" % (email, exc), file=sys.stderr)
            _log("[keepalive] %s: keychain write refused (%s) — kept old token, skipped" % (email, exc))  # failure deserves a durable record, not just ephemeral stderr
            continue
        meta = slots.get(email)
        if isinstance(meta, dict):
            meta["fp"] = fingerprint(fresh)
            meta["expires_at"] = _oauth(fresh).get("expiresAt")
            meta["refresh_failures"] = 0  # a successful exchange clears the dead-refresh counter (TRDD-HJGR4I5W)
            changed = True
        actions.append(email)
    if changed:
        save_state(state)
    return actions


def _bootstrap_eligible(
    has_refresh: bool,
    has_session_key: bool,
    *,
    refresh_failures: int = 0,
    max_refresh_failures: int = MAX_REFRESH_FAILURES,
) -> bool:
    """PURE: is this slot a candidate for post-login auto-bootstrap?

    Eligible iff it CANNOT self-renew — either NO refreshToken, OR a refreshToken whose
    exchange is persistently FAILING (``refresh_failures`` ≥ the dead-refresh threshold) —
    but DOES have a live claude.ai Chrome session we can mint a fresh refresh-bearing slot
    from (slot_capture_browser auto-clicks Authorize on the seeded session). A slot that
    still self-renews needs nothing; a slot with no live session has nothing to bootstrap
    FROM (that one needs a human login — surfaced by the oauth-login-needed detector).

    Delegates to the cascade SSOT (TRDD-dfc0959a): bootstrap-eligible ⇔ the account lands in
    the cascade's RENEW_COOKIE leg. ``refresh_failures`` MUST be threaded through so a
    dead-refresh + live-cookie slot is eligible (TRDD-J9TM3WQK) instead of nudging REAUTH;
    omitting it (default 0) reproduces the historical no-refresh-only truth table exactly.
    Token expiry is irrelevant to this leg (the cookie, not the token, is what gets minted
    from), so it is passed as None. test_cascade proves this equals classify exactly."""
    return (
        cascade.classify(
            cascade.AccountState(
                email="",
                is_live=False,
                has_refresh=has_refresh,
                token_expires_h=None,
                has_session_cookie=has_session_key,
                refresh_failures=refresh_failures,
            ),
            max_refresh_failures=max_refresh_failures,
        )
        is cascade.CascadeLeg.RENEW_COOKIE
    )


def _profiles_root() -> Path:
    """The Chrome profiles root — the SINGLE resolver every profile consumer shares
    (``_profile_has_session_key`` here and ``slot_capture_browser.profile_dir``), so
    open-login.sh / the daemon / the capture all agree on where
    ``chrome-profile-<email>`` lives. Resolution order:

      1. ``CLAUDE_ROTATOR_PROFILES`` env override — explicit wins (used by tests and
         by any caller that pins the profiles dir).
      2. the canonical ``<ROOT>/profiles`` when it EXISTS.
      3. the legacy ``~/.claude/account-rotator/profiles`` when IT exists but the
         canonical one does NOT — a DURABLE fallback that replaces the old runtime
         symlink: the human seeded the login under the standalone account-rotator
         layout (open-login.sh's historical home) while state.json has since migrated
         to the DATA dir (TRDD-7100178d), so the profiles and the state can live under
         different roots. Without this, the daemon would look under an empty
         ``<DATA>/oauth-rotator/profiles`` and never find the seeded session.
      4. else ``<ROOT>/profiles`` — the default a fresh install writes to."""
    raw = os.environ.get("CLAUDE_ROTATOR_PROFILES", "").strip()
    if raw:
        return Path(raw)
    canonical = ROOT / "profiles"
    if canonical.is_dir():
        return canonical
    legacy = _legacy_rotator_root() / "profiles"
    if legacy.is_dir():
        return legacy
    return canonical


def _profile_has_session_key(email: str, *, now: float | None = None) -> bool:
    """True iff a LIVE (not-yet-expired) claude.ai session cookie exists in the
    account's Chrome profile — i.e. slot_capture_browser could auto-bootstrap a
    refresh token from it. Read-only sqlite probe; never reads cookie VALUES, only
    the sessionKey's host/name/expiry. Mirrors oauth-cookie-reminder._cookie_days."""
    now = now if now is not None else time.time()
    db = _profiles_root() / f"chrome-profile-{email}" / "Default" / "Cookies"
    if not db.is_file():
        return False
    chrome_now = int((now + 11644473600) * 1_000_000)  # Chrome epoch: us since 1601-01-01
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute("SELECT expires_utc FROM cookies WHERE name = 'sessionKey' AND host_key LIKE '%claude.ai'").fetchall()
        con.close()
    except sqlite3.Error:
        return False
    return any(exp > chrome_now for (exp,) in rows)


def _env_truthy(val: str | None) -> bool:
    """True iff `val` is a recognised affirmative (`1/true/yes/on`, case-insensitive).

    Mirrors scripts/lib/state.is_truthy_env so the rotator (which imports only
    janitor_integrity, not state) agrees on env-flag parsing — an unset/empty/garbage
    value is False, so CLAUDE_ROTATOR_BOOTSTRAP_HEADLESS defaults OFF (headful)."""
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


def _bootstrap_pid_path(email: str) -> Path:
    """Per-email PID lockfile for the detached capture (``<ROOT>/.bootstrap-<email>.pid``).

    Sanitises the email the same way slot_path does (`/`→`_`) so the filename is safe."""
    safe = email.replace("/", "_")
    return ROOT / (".bootstrap-%s.pid" % safe)


def _bootstrap_pid_alive(pid: int) -> bool:
    """True iff `pid` is a live process (so a prior capture for this email is still
    running). Any OSError (ESRCH = gone, EPERM = recycled to a stranger we don't own)
    means "not our live worker" → False, so we never wedge waiting on it. Mirrors the
    detached-worker detectors' _pid_alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


# Auto-bootstrap browser-launch DENY-LIST (TRDD-56374Z36). The bootstrap path opens a VISIBLE
# browser to mint a refresh token; it must NEVER do so for an implausible / fixture account.
# These are the obvious test/placeholder email domains — a real Claude subscription is never
# under one of them, so denying them is FAIL-OPEN for every real account. This is the runtime
# belt behind the primary test-isolation fix (tests/conftest.py redirects ROOT + LOG_FILE per
# test): even if a fixture account somehow reached the daemon's real state.json, the daemon
# never launches a visible browser for it. Matched case-insensitively on the domain part only.
_DENIED_BOOTSTRAP_DOMAINS = frozenset(
    {
        "x.com",
        "example.com",
        "example.org",
        "test.local",
        "invalid",
    }
)


def _bootstrap_email_denied(email: str) -> bool:
    """True iff `email`'s domain is a known fixture/placeholder domain that must NEVER trigger an
    auto-bootstrap browser launch (see _DENIED_BOOTSTRAP_DOMAINS). FAIL-OPEN: an email with no
    parseable domain is NOT denied — a malformed address is not this guard's concern (the launch
    fails elsewhere), and a real account must never be blocked."""
    _, _, domain = (email or "").rpartition("@")
    return bool(domain) and domain.strip().lower() in _DENIED_BOOTSTRAP_DOMAINS


def _invoke_slot_capture(email: str) -> bool:
    """LAUNCH (detached) a capture that mints a refresh-bearing slot for `email` from its
    SEEDED Chrome session. Returns True iff a capture was LAUNCHED this call, False if one
    was SKIPPED because a prior capture for the same email is still running.

    Why DETACHED + a PID lock (audit §2, §3.5):
      * A VISIBLE (headful) capture can take tens of seconds and polls the consent page up
        to 300 s. Run inline under the daemon's 120 s tick cap it would be SIGKILLed and,
        worse, STARVE real rotation. So we fire-and-forget via subprocess.Popen (no wait):
        the tick returns immediately and the slot appears on a LATER tick once the capture
        finishes and writes it (at which point the slot has a refreshToken and is no longer
        bootstrap-eligible — that absence IS the success signal).
      * A per-email PID lockfile (`<ROOT>/.bootstrap-<email>.pid`) makes it skip-if-running,
        so a slow capture spanning several 60 s ticks is launched ONCE, not re-spawned every
        minute (mirrors the janitor's detached-PID-worker detectors).

    Invocation (audit §2(b).1): run via `uv run --with playwright python …` so Playwright is
    PROVISIONED — the daemon's own `uv run --script` interpreter declares no playwright, so a
    bare `sys.executable` crash-on-imports every tick. HEADFUL by default (the mode the user
    tested working — the consent page's "log in in the window" affordance is impossible
    headless, and the project's STATE block records automation-flagged HEADLESS Chrome as
    CF-blocked); `--headless` is appended ONLY when CLAUDE_ROTATOR_BOOTSTRAP_HEADLESS is truthy.
    The child INHERITS the current env (we deliberately do NOT strip CLAUDE_PLUGIN_DATA) so it
    resolves the SAME rotator ROOT the daemon did — slots written where the daemon reads them.

    This is the ONE external-process seam — tests monkeypatch it so no real browser / network /
    keychain is ever touched."""
    if _bootstrap_email_denied(email):
        # Runtime belt (TRDD-56374Z36): refuse to open a browser for an implausible/fixture
        # account BEFORE any Popen. This is the tightest gate — the literal browser-launch
        # site — so no denied domain ever spawns a capture, whatever the caller. Only ever
        # reachable if a fixture account is in the real state.json (it should not be), so the
        # one-line skip is self-diagnosing rather than routine noise; the log self-rotates.
        _log("auto-bootstrap: refusing browser launch for implausible/fixture account %s (denied domain) — skipped" % email)
        return False
    script = Path(__file__).resolve().parent / "slot_capture_browser.py"
    pid_path = _bootstrap_pid_path(email)
    try:
        prior = int(pid_path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        prior = 0
    if prior and _bootstrap_pid_alive(prior):
        # A capture for this email is already in flight — skip (don't double-launch).
        return False
    ROOT.mkdir(parents=True, exist_ok=True)
    cmd = ["uv", "run", "--with", "playwright", "python", str(script), email]
    if _env_truthy(os.environ.get("CLAUDE_ROTATOR_BOOTSTRAP_HEADLESS")):
        cmd.append("--headless")  # opt-in only — the daemon path runs VISIBLE by default
    log_path = ROOT / ("bootstrap-%s.log" % email.replace("/", "_"))
    logf = log_path.open("a", encoding="utf-8")
    try:
        # Detached: own session (immune to the daemon's SIGHUP/terminal), stdout+stderr to a
        # logfile under ROOT, no wait(). Env INHERITED (Popen default) — CLAUDE_PLUGIN_DATA
        # intact so the child resolves the daemon's ROOT.
        proc = subprocess.Popen(  # noqa: S603 - explicit argv list, no shell
            cmd,
            stdout=logf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        logf.close()
    try:
        tmp = pid_path.with_suffix(pid_path.suffix + ".tmp.%d" % os.getpid())
        tmp.write_text(str(proc.pid), encoding="utf-8")
        os.replace(tmp, pid_path)
    except OSError:
        pass  # pid-file write is best-effort; worst case the next tick re-launches
    return True


def _bootstrap_action(*, eligible: bool, auto_on: bool, attempts: int, max_launches: int) -> str:
    """PURE: what should _bootstrap_seeded_slots do for ONE slot this tick? Returns one of:
    'reset' (self-renewing slot carrying a stale launch counter to clear, so a future
    dead-refresh gets a fresh cap), 'noop' (nothing to do - self-renewing with a zero counter,
    OR eligible but auto-launch is opted OFF so the detector nudges the human instead),
    'cap-announce' (just reached the launch cap: log once + bump the counter past it), 'capped'
    (already past the cap: stay silent), or 'launch' (open a capture this tick). No I/O -
    a unit-testable truth table; the caller owns every state write + log (TRDD-5OJX3SCF)."""
    if not eligible:
        return "reset" if attempts != 0 else "noop"
    if not auto_on:
        return "noop"
    if attempts >= max_launches:
        return "cap-announce" if attempts == max_launches else "capped"
    return "launch"


def _bootstrap_seeded_slots() -> list[str]:
    """Post-login auto-bootstrap (P4d): for every indexed slot that was SEEDED by a
    human login (a live claude.ai Chrome session) but cannot yet self-renew (no
    refreshToken), LAUNCH a detached slot_capture_browser to mint a full refresh-bearing
    slot. This is what lets the "log me in once, the rotator manages the rest" UX work —
    the human runs open-login.sh per dead account, and a later tick converts those seeded
    sessions into self-renewing slots with NO further human action.

    LAUNCH contract (audit §2): _invoke_slot_capture fires the capture DETACHED and returns
    immediately — it does NOT wait for the (visible, up-to-300 s) browser flow. So this
    returns the list of emails for which a capture was LAUNCHED this call, NOT "succeeded".
    Success is observed on a LATER tick: a successful capture writes a refresh-bearing slot,
    which then fails _bootstrap_eligible (has_refresh) and is no longer launched. An email
    whose capture is still in flight is skipped by _invoke_slot_capture's PID lock (so it is
    NOT in the returned list while a prior capture for it runs).

    Best-effort and defensive: each launch is wrapped so a spawn failure (uv/Playwright
    missing, bad env, missing profile) is logged and SKIPPED, never aborting the loop or the
    tick (a non-fatal helper must not crash the beat it runs in).

    AUTO-LAUNCH is OPT-IN, default OFF (CLAUDE_ROTATOR_AUTO_BOOTSTRAP), SEPARATE from the
    rotation opt-in: opening a VISIBLE browser from the unattended daemon is a higher-surprise
    act, so it never fires unless explicitly enabled (TRDD-5OJX3SCF). Even when on, each slot is
    LAUNCH-CAPPED at MAX_BOOTSTRAP_LAUNCHES (the RENEW_COOKIE analogue of MAX_REFRESH_FAILURES,
    TRDD-HJGR4I5W) so a never-minting capture cannot re-open a browser every tick; a successful
    mint replaces the slot meta (counter gone) and a recovered slot resets to 0. Every launch and
    the cap boundary are announced via _log."""
    launched: list[str] = []
    auto_on = _env_truthy(os.environ.get("CLAUDE_ROTATOR_AUTO_BOOTSTRAP"))
    state = load_state()
    now = time.time()
    changed = False
    for email in list((state.get("slots") or {}).keys()):
        blob = read_slot(email)
        inner = _oauth(blob) if blob else {}
        has_refresh = bool(inner.get("refreshToken") or inner.get("refresh_token"))
        has_session = _profile_has_session_key(email, now=now)
        # Thread refresh_failures so a DEAD-but-present refresh + live cookie is bootstrap-
        # eligible (TRDD-J9TM3WQK) — the cookie mints a fresh refresh with no human, instead
        # of the slot silently nudging REAUTH. A successful capture REPLACES the slot meta
        # (dropping refresh_failures → 0), so a recovered slot is never re-captured in a loop.
        meta = (state.get("slots") or {}).get(email)
        rf = int(meta.get("refresh_failures", 0)) if isinstance(meta, dict) else 0
        attempts = int(meta.get("bootstrap_attempts", 0)) if isinstance(meta, dict) else 0
        action = _bootstrap_action(
            eligible=_bootstrap_eligible(has_refresh, has_session, refresh_failures=rf),
            auto_on=auto_on,
            attempts=attempts,
            max_launches=MAX_BOOTSTRAP_LAUNCHES,
        )
        if action == "reset":  # self-renewing again -> clear the launch counter (fresh future cap)
            if isinstance(meta, dict):
                meta["bootstrap_attempts"] = 0
                changed = True
            continue
        if action == "noop":  # not eligible (zero counter), OR eligible but auto-launch opted OFF
            continue  # (the oauth-capture-stalled detector nudges the human in the OFF case)
        if action == "cap-announce":  # just hit the cap: announce ONCE, then never auto-launch it again
            _log("auto-bootstrap: %s capped at %d launches without a refresh-bearing mint - STOPPING auto-launch; run /janitor-refresh-cc-logins to capture it manually" % (email, MAX_BOOTSTRAP_LAUNCHES))
            if isinstance(meta, dict):
                meta["bootstrap_attempts"] = attempts + 1  # bump past the cap so the log fires once
                changed = True
            continue
        if action == "capped":  # already past the cap: stay silent, do not launch
            continue
        try:  # action == "launch"
            if _invoke_slot_capture(email):  # True = LAUNCHED, False = skipped (already running)
                # Announce the visible window so it is never "without reason" (TRDD-5OJX3SCF).
                _log("auto-bootstrap: opening a browser to mint a refresh token for %s (expected - post-login auto-bootstrap); live account untouched" % email)
                if isinstance(meta, dict):
                    meta["bootstrap_attempts"] = attempts + 1
                    meta["last_bootstrap_at"] = int(now)
                    changed = True
                launched.append(email)
        except Exception as exc:  # noqa: BLE001 — documented best-effort contract
            # Best-effort by design: a launch failure (uv/Playwright spawn error, missing
            # profile, bad env) must NOT abort the remaining slots or the daemon tick this
            # runs inside. We deliberately swallow EVERY exception here (the one place
            # fail-fast is wrong — this is a last-line convenience, not a correctness gate)
            # and continue to the next eligible slot.
            print("[bootstrap] %s: capture launch failed (%r) — skipped" % (email, exc), file=sys.stderr)
    if changed:
        save_state(state)  # persist bootstrap_attempts / last_bootstrap_at across ticks
    return launched


def _repair_integrity() -> list[str]:
    """Pillar 2 in-advance backup / corruption-repair pass, run at the START of every tick
    BEFORE any rotation decision, so the three credential stores each carry a verified
    redundant copy and a corrupt one self-heals:

      - state.json: load_state() already restores a corrupt primary from <state>.bak
        (integrity.read_or_restore re-heals on disk); we then ensure the in-advance mirror +
        sidecars are established/consistent (re-save iff not), so even a pre-integrity
        state.json gets its backup before it is ever needed.
      - slots: reading each indexed slot re-heals a deleted/corrupt primary keychain item from
        its -slot-backup mirror (read_slot's built-in self-heal).
      - live credential: refresh the -livebak mirror from the current primary so an
        externally-written credential (Claude's own login/refresh) is backed up too; and if
        the primary live store is unreadable but the mirror survived, RESTORE the primary.

    Returns the list of repair actions taken (empty = everything was already healthy).
    I/O-error tolerant: a disk-full / permission failure here is logged into the returned
    list and the tick proceeds — a last line of defence must not crash the beat it guards.
    A non-OSError (a real logic bug) still propagates (fail-fast)."""
    actions: list[str] = []
    try:
        state = load_state()
        if not integrity.backup_is_consistent(STATE_FILE):
            save_state(state)
            actions.append("state.json: established/refreshed redundant backup mirror")
        for email in list((state.get("slots") or {}).keys()):
            read_slot(email)  # self-heals the primary keychain item from the mirror if needed
        primary_live = _read_live_primary()
        if primary_live is not None:
            _live_backup_write(primary_live)  # keep the in-advance -livebak mirror current
        else:
            mirror = _live_backup_read()
            if mirror is not None:
                # F1 write-path gate (TRDD-7PYTX4E9): restore ONLY when the primary item
                # is PROVABLY ABSENT. "Unreadable" ≠ "absent" — an ACL-denied primary
                # (the state after every user /login, from the headless daemon) still
                # holds the USER'S CURRENT credential; "restoring" the (possibly stale)
                # mirror over it would OVERWRITE the user's login with an old token —
                # the mutating twin of the read-path blind spot.
                if _primary_live_item_absent():
                    write_live_blob(mirror)  # primary truly gone/corrupt -> restore
                    actions.append("live credential: restored primary from -livebak mirror")
                    _log("repair: primary live item ABSENT — restored it from the -livebak mirror")
                else:
                    actions.append("live credential: primary unreadable but PRESENT — restore refused (TRDD-7PYTX4E9)")
                    _log("repair: primary live item present but unreadable from this context — refusing the mirror restore (it would overwrite the user's current login; TRDD-7PYTX4E9 F1)")
    except OSError as exc:
        actions.append("repair pass I/O error (non-fatal): %r" % (exc,))
    return actions


def _build_fleet_state(state: dict, now: float) -> list[cascade.AccountState]:
    """Snapshot every account's cascade-relevant facts (all NON-secret) for the explicit
    cascade plan logged each beat: has_refresh + token-expiry from the keychain slot (the
    live account's from the live store), has_session_cookie from the seeded Chrome profile —
    the same sources keepalive/bootstrap already read. Best-effort per account: an unreadable
    slot contributes an all-False state (→ the REAUTH_NUDGE leg in the log) rather than
    aborting the snapshot."""
    live_email = state.get("live_email")
    emails = set((state.get("slots") or {}).keys())
    if live_email:
        emails.add(live_email)
    out: list[cascade.AccountState] = []
    for email in sorted(emails):
        blob = read_slot(email)
        if blob is None and email == live_email:
            blob = read_live_blob()  # the live token lives in the live store, not a slot
        inner = _oauth(blob) if blob else {}
        slot_meta = (state.get("slots") or {}).get(email)
        out.append(
            cascade.AccountState(
                email=email,
                is_live=(email == live_email),
                has_refresh=bool(inner.get("refreshToken") or inner.get("refresh_token")),
                token_expires_h=(expires_in_h(blob) if blob else None),
                has_session_cookie=_profile_has_session_key(email, now=now),
                refresh_failures=(int(slot_meta.get("refresh_failures", 0)) if isinstance(slot_meta, dict) else 0),
            )
        )
    return out


def _log_cascade_plan() -> None:
    """Log the explicit ROTATE→RENEW→REAUTH cascade plan (TRDD-dfc0959a) for the current
    fleet — the per-account fallback legs (renew-refresh / renew-cookie / reauth-nudge /
    waiting), so the daemon's cascade is auditable in rotator.log. Best-effort VISIBILITY
    ONLY: never a gate, and a snapshot failure (unreadable keychain/state) must not break the
    beat. Extracted from cmd_tick so the daemon has ONE call and tests have ONE mock point
    (it does real keychain/state/log IO, so a cmd_tick test isolates it by stubbing THIS fn).

    The authoritative reauth-nudge grace is the detector's env-configurable value; this summary
    uses the cascade default, so a borderline account may bucket slightly differently in the LOG
    than in the nudge — the detector nudge is the source of truth."""
    try:
        fleet = _build_fleet_state(load_state(), time.time())
        _log(cascade.cascade_plan(fleet, keepalive_ahead_h=KEEPALIVE_AHEAD_H, max_refresh_failures=MAX_REFRESH_FAILURES).summary_line())
    except Exception as exc:  # noqa: BLE001 — explicit-cascade visibility log is best-effort
        _log("cascade: plan unavailable (%r)" % exc)


def cmd_tick(only_if_running: bool) -> int:
    """One daemon beat: migrate the legacy root once, keepalive-refresh slot tokens nearing
    expiry (F2b), run the Pillar-2 integrity-repair pass (verify/restore state + slots + live
    before any decision), refresh the index, auto-rotate if needed, and LAST launch any
    seeded-slot bootstrap captures. No-ops entirely unless the real Claude Code binary is running.

    Ordering note (audit §2(b).2): bootstrap runs DEAD LAST — AFTER cmd_auto — so the
    usage-based rotation that keeps the user's session alive overnight is NEVER starved by a
    bootstrap launch, and the detached capture (fire-and-forget) can't delay the beat. (The
    launch itself returns immediately; this ordering is belt-and-braces.)
    """
    try:
        if only_if_running and not claude_running():
            return 0
        # One-time, non-destructive: move state.json/opt-in from the legacy standalone root
        # into the canonical DATA-dir root. The smart _rotator_root() already reads from
        # whichever root holds the state, so this is just promotion — the NEXT tick process
        # then resolves to the canonical root. Safe to call every tick (no-op once migrated).
        migrate_root_to_canonical()
        # F2 (TRDD-7PYTX4E9): a tick running in a context that CAN read the primary (a
        # manual/session-context run) refreshes the live-identity beacon for free — the
        # daemon's own ticks can't (their primary read fails), which is the point.
        write_live_identity_beacon()
        _log_cascade_plan()  # explicit ROTATE→RENEW→REAUTH cascade visibility (best-effort, never a gate)
        refreshed = _keepalive_refresh()  # F2b: refresh slot tokens nearing expiry (prevent an overnight lapse)
        if refreshed:
            _log("keepalive: refreshed %s" % ", ".join(refreshed))  # durable record of token-prolonging action
        _repair_integrity()  # Pillar 2: verify/restore state + slots + live BEFORE deciding
        try:
            cmd_capture(False)
        except SlotKeychainWriteError as exc:
            # FAIL CLOSED (P1) without crashing the unattended tick: a locked/declined keychain
            # refused the slot write. The LIVE credential is untouched (Claude owns it); we simply
            # don't mirror it into a slot this beat (and never drop a plaintext token). The
            # standalone `rotator.py capture` still surfaces this error to the present human.
            print("[capture] keychain write refused (%s) — slot not filed this tick" % exc, file=sys.stderr)
            _log("[capture] keychain write refused (%s) — slot not filed this tick" % exc)
        rc = cmd_auto()  # usage-based rotation FIRST — never starved by bootstrap
        _bootstrap_seeded_slots()  # P4d (LAST): launch detached captures from human-seeded sessions
        return rc
    finally:
        # F4 (TRDD-7PYTX4E9): a completed tick — including the only-if-running no-op and a
        # crashed-but-finished one — stamps its liveness; only a HANG leaves the stamp stale,
        # which is exactly what the supervisor's tick-stalled alert watches for.
        _stamp_tick_completed()


def cmd_live_email() -> int:
    """Print the authoritative email of the CURRENTLY LIVE account, or empty.

    Used by reauth.py as the identity guard's "intended" account. Prefers the
    /roles resolution of the live token (ground truth from Anthropic); falls
    back to the last-known live_email in state when the live token is too
    expired for /roles to answer (which is exactly the case that triggers a
    Tier-3 re-auth).
    """
    blob = read_live_blob()
    email = account_email(blob) if blob else None
    if not email:
        email = load_state().get("live_email")
    print(email or "")
    return 0


def cmd_known_emails() -> int:
    """Print every known account email (live + all slots), one per line.

    reauth.py uses this list to detect a *positive* wrong-account match on the
    consent page (if the page shows a known email that is NOT the intended one,
    abort before clicking Authorize).
    """
    state = load_state()
    emails = set(state.get("slots", {}).keys())
    live = state.get("live_email")
    if live:
        emails.add(live)
    for e in sorted(emails):
        print(e)
    return 0


def cmd_print_profiles_root() -> int:
    """Print the canonical Chrome-profiles root (``_profiles_root()``).

    The shell helpers (open-login.sh / check-login.sh / lifetime-status.sh) call
    this so every profile consumer resolves the SAME path the Python engine uses,
    instead of hardcoding the legacy ``~/.claude/account-rotator/profiles`` default
    and diverging on a migrated / symlink-less install (audit H1). Read-only.
    """
    print(_profiles_root())
    return 0


def build_oauth_health(
    emails: list[str],
    live: str | None,
    slot_blobs: dict[str, dict | None],
    denied: set[str],
    live_blob: dict | None,
) -> dict[str, dict]:
    """PURE assembly of per-account OAuth health from ALREADY-READ data — no keychain I/O.

    Split out from ``cmd_oauth_health`` so the reporting/degradation logic is testable
    without a live keychain (janitor #82). Each entry carries a ``status`` that keeps the
    three cases lifetime-status.sh MUST NOT conflate distinct:

      * ``"ok"``      — a readable blob (it may or may not carry a refresh token / expiry).
      * ``"latched"`` — the read was DENIED / short-circuited by the machine-wide keychain
        denied-latch: the account's OAuth state is UNKNOWN, NOT proven absent. Reporting it
        as "no oauth" (a definite negative) was the alarming-and-wrong bug (janitor #82 fix
        #1) — a latched store is unknown-state.
      * ``"no-oauth"`` — the read SUCCEEDED and the account genuinely has no OAuth material
        (or the item was genuinely not-found, which does not latch).

    For the live account we prefer the fresher ``live_blob`` but fall back to its readable
    slot when the live read was skipped/denied (janitor #82 fix #2 graceful degradation):
    one account's unreadable live credential never zeroes the accounts whose slots ARE
    readable.
    """
    health: dict[str, dict] = {}
    for e in emails:
        blob = live_blob if (e == live and isinstance(live_blob, dict)) else slot_blobs.get(e)
        if isinstance(blob, dict):
            o = _oauth(blob)
            hrs = expires_in_h(blob)
            health[e] = {
                "has_refresh": bool(o.get("refreshToken")),
                "expires_days": (hrs / 24) if hrs is not None else None,
                "expires_at": o.get("expiresAt"),
                "status": "ok",
            }
        elif e in denied:
            health[e] = {"has_refresh": False, "expires_days": None, "expires_at": None, "status": "latched"}
        else:
            health[e] = {"has_refresh": False, "expires_days": None, "expires_at": None, "status": "no-oauth"}
    return health


def cmd_oauth_health(as_json: bool) -> int:
    """Print per-account OAuth health (has_refresh + expiry + status) read from the KEYCHAIN.

    The source is the keychain slots (and the live credential for the live account),
    NOT the legacy plaintext ``slots/<email>.json`` files the keychain migration
    deletes by design. lifetime-status.sh consumes this so its "is OAuth healthy /
    safe to refresh" verdict reflects the real keychain state on a migrated machine
    instead of asserting a false "no healthy OAuth" banner (audit C2). Read-only.

    Read ORDER is load-bearing (janitor #82 fix #2 — graceful degradation): the
    CLI-written per-account SLOTS are read FIRST — they stay readable even when the
    signed-app-owned live credential item flaps its ACL/partition-list — and the flaky
    live-credential read runs LAST, and only while the denied-latch is CLEAR. So a live
    read that hangs and trips the machine-wide latch can no longer erase the slot truth
    already captured, and a store that is ALREADY latched is reported as UNKNOWN per
    account ("latched") instead of a false "no oauth". Every individual read is
    byte-identical to before — only the order + latch-awareness are new; no credential
    read/write path is modified.

    With ``--json`` emits ``{email: {has_refresh, expires_days, expires_at, status}}``;
    otherwise a human-readable line per account.
    """
    state = load_state()
    emails = set(state.get("slots", {}).keys())
    live = state.get("live_email")
    if live:
        emails.add(live)
    ordered = sorted(emails)

    # SLOTS first. A None read is UNKNOWN ("latched") only when the denied-latch is set —
    # a genuine not-found does NOT latch, so it stays "no-oauth". `keychain_denied_latched()`
    # only stats a flag FILE (never spawns `security`), so this is not a keychain read.
    slot_blobs: dict[str, dict | None] = {}
    denied: set[str] = set()
    for e in ordered:
        b = read_slot(e)
        slot_blobs[e] = b
        if b is None and safe_storage.keychain_denied_latched():
            denied.add(e)

    # Live read LAST, and skipped entirely once latched (it would only short-circuit — and
    # attempting it is the prompt-risk this fix exists to avoid). Enriches only the live
    # account; every other account already has its (readable) slot captured above.
    live_blob = read_live_blob() if (live and not safe_storage.keychain_denied_latched()) else None

    health = build_oauth_health(ordered, live, slot_blobs, denied, live_blob)
    if as_json:
        print(json.dumps(health))
    else:
        for e, h in health.items():
            days = ("%.1f" % h["expires_days"]) if h["expires_days"] is not None else "?"
            print("%s\trefresh=%s\tdays=%s\tstatus=%s" % (e, "yes" if h["has_refresh"] else "no", days, h.get("status", "ok")))
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: rotator.py {capture [--only-if-claude-running] | tick [--only-if-claude-running] | auto | usage | live-email | known-emails | print-profiles-root | oauth-health [--json] | list | beacon [--if-stale] | switch <email> | migrate-slots | delete-plaintext-slots | migrate-root}")
        return 2
    cmd = argv[0]
    # ── Read-only commands: no lock needed (they never write state.json / keychain). ──
    if cmd == "clear-keychain-latch":
        # Safe Keychain Protocol (TRDD-K3WQ7XM9 P1): the human's re-grant / re-arm path.
        # After re-granting keychain ACL (e.g. re-login / "Always Allow"), clear the latch so
        # `security` ops resume. Until then EVERY op is suppressed (no prompt can recur).
        cleared = safe_storage.clear_keychain_denied()
        print("keychain denied-latch cleared" if cleared else "no keychain denied-latch was set")
        return 0
    if cmd == "keychain-latch-status":
        print("LATCHED" if safe_storage.keychain_denied_latched() else "clear")
        return 0
    if cmd == "beacon":
        # F2 (TRDD-7PYTX4E9): session-context live-identity stamp. Writes only the
        # atomic live-identity.json (never state.json / keychain), so it is safe
        # lock-free — the SessionStart hook spawns it detached and must never block
        # behind the daemon's tick lock.
        #
        # --if-stale (TRDD-6AABK2BG): re-stamp ONLY when the credential actually changed,
        # decided by a NON-prompting attribute read. This is what the heartbeat detector
        # runs every fire; the bare form stays unconditional because SessionStart wants an
        # unconditional stamp. rc 0 = wrote, rc 1 = did not (already current, or no primary
        # readable) — never an error either way.
        if "--if-stale" in argv[1:]:
            return 0 if refresh_beacon_if_stale() else 1
        return 0 if write_live_identity_beacon() else 1
    if cmd == "usage":
        return cmd_usage()
    if cmd == "live-email":
        return cmd_live_email()
    if cmd == "known-emails":
        return cmd_known_emails()
    if cmd == "print-profiles-root":
        return cmd_print_profiles_root()
    if cmd == "oauth-health":
        return cmd_oauth_health("--json" in argv[1:])
    if cmd == "list":
        return cmd_list()

    # ── Mutating commands: serialise EVERY rotator write (state.json + the live/slot
    # keychain) behind the machine-wide rotator-tick flock so the daemon's 60 s tick and
    # a human's manual `rotator.py …` can NEVER race (audit §3.4 — a lost state update or
    # a live credential split from state.live_email). Non-blocking: a loser SKIPS (the
    # daemon re-fires next tick; a human re-runs). The lock lives HERE, in the subprocess
    # every invocation runs — NOT in the daemon's task wrapper. A daemon-side lock would
    # only block the daemon's OWN rotator.py subprocess and would never see a manual run,
    # so it could not prevent the daemon-vs-manual race it was meant to. ──
    _MUTATING = {"capture", "tick", "auto", "switch", "migrate-slots", "delete-plaintext-slots", "migrate-root"}
    if cmd not in _MUTATING:
        print("unknown command: %s" % cmd)
        return 2
    with gs.oauth_rotator_lock() as got:
        if not got:
            print("rotator: another rotator operation is in progress — skipped this run (safe to retry).", file=sys.stderr)
            return 0
        if cmd == "capture":
            return cmd_capture("--only-if-claude-running" in argv[1:])
        if cmd == "tick":
            return cmd_tick("--only-if-claude-running" in argv[1:])
        if cmd == "auto":
            return cmd_auto()
        if cmd == "switch":
            if len(argv) < 2:
                print("usage: rotator.py switch <email>")
                return 2
            return cmd_switch(argv[1])
        if cmd == "migrate-slots":
            res = migrate_slots_to_keychain()
            if not res:
                print("migrate-slots: no legacy plaintext slot files to migrate")
                return 0
            for email, ok in res:
                print("migrate-slots: %s -> keychain %s" % (email, "VERIFIED" if ok else "FAILED"))
            return 0 if all(ok for _, ok in res) else 1
        if cmd == "delete-plaintext-slots":
            # SECURITY cleanup — only AFTER migrate-slots verified. Refuse if any
            # plaintext slot is not yet readable from the keychain (would lose a token).
            legacy = sorted(SLOTS.glob("*.json")) if SLOTS.is_dir() else []
            unsafe = [f.stem for f in legacy if _slot_keychain_read(f.stem) is None]
            if unsafe:
                print("delete-plaintext-slots REFUSED — not yet in the keychain (run migrate-slots first): %s" % ", ".join(unsafe))
                return 1
            removed = delete_plaintext_slot_files()
            print("delete-plaintext-slots: removed %d plaintext file(s): %s" % (len(removed), ", ".join(removed) or "(none)"))
            return 0
        # cmd == "migrate-root"  (legacy_root is a Path here, not the list[Path] used in the
        # delete-plaintext-slots branch above — a distinct name avoids the type collision)
        legacy_root, canonical, moved = migrate_root_to_canonical()
        if legacy_root == canonical:
            print("migrate-root: canonical and legacy root are identical (%s) — no-op" % canonical)
        elif moved:
            print("migrate-root: copied state.json/opt-in %s -> %s (legacy kept)" % (legacy_root, canonical))
        elif (canonical / "state.json").is_file():
            print("migrate-root: already migrated (%s has state.json)" % canonical)
        else:
            print("migrate-root: nothing to migrate (no state.json in %s)" % legacy_root)
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
