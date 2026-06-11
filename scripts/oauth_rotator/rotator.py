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

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# scripts/lib holds janitor_integrity (backup + corruption-recovery, TRDD-7100178d).
# rotator.py runs both standalone (`uv run …/rotator.py`) and under the daemon (which
# already puts scripts/lib on sys.path); the insert below makes the import work in the
# standalone case too. janitor_integrity is pure-stdlib, so it adds no PEP-723 deps.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import cascade  # noqa: E402  # scripts/oauth_rotator/cascade.py (ROTATE→RENEW→REAUTH SSOT, TRDD-dfc0959a)
import global_state as gs  # noqa: E402  # scripts/lib/global_state.py (rotator-tick single-writer flock, audit §3.4)
import janitor_integrity as integrity  # noqa: E402  # scripts/lib/janitor_integrity.py

KEYCHAIN_SERVICE = "Claude Code-credentials"
# Per-account slot tokens are stored in the OS keychain too — ENCRYPTED at rest,
# keyed by this service + the account EMAIL (NOT plaintext 0600 files, which malware
# running as the user, backups, and Time Machine can all read). Mirrors the LIVE
# credential's keychain helpers. One-time move: migrate_slots_to_keychain().
# Env-overridable ONLY so tests can target a throwaway keychain service and clean it
# up — production always uses the default.
SLOT_KEYCHAIN_SERVICE = os.environ.get(
    "CLAUDE_ROTATOR_SLOT_KEYCHAIN_SERVICE", "Claude Code-rotator-slot")
# A second keychain service holding a REDUNDANT MIRROR of every slot token (TRDD-7100178d,
# Pillar 2, Decision 2). write_slot writes both; read_slot falls back to this when the
# primary keychain item is missing/corrupt (e.g. deleted via Keychain Access). Encrypted
# at rest, same as the primary — no plaintext reintroduced. Env-overridable for tests only.
SLOT_BACKUP_KEYCHAIN_SERVICE = os.environ.get(
    "CLAUDE_ROTATOR_SLOT_BACKUP_KEYCHAIN_SERVICE", "Claude Code-rotator-slot-backup")
# A third keychain service holding a REDUNDANT MIRROR of the LIVE credential blob
# (TRDD-7100178d, Pillar 2). write_live_blob mirrors here on every switch, the tick's
# integrity-repair pass refreshes it from the current live credential, read_live_blob falls
# back to it, and _repair_integrity RESTORES the primary live keychain item from it when the
# primary is missing/corrupt. Keychain-only — never writes ~/.claude/.credentials.json, so
# the macOS live-re-read property (Claude clears its cache off that file's ABSENCE) is kept.
# Env-overridable for tests only.
LIVE_BACKUP_KEYCHAIN_SERVICE = os.environ.get(
    "CLAUDE_ROTATOR_LIVE_BACKUP_KEYCHAIN_SERVICE", "Claude Code-credentials-livebak")


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
_LOG_MAX_BYTES = 256 * 1024   # self-trim ceiling — bounds the unattended 60s-cadence log
_LOG_KEEP_BYTES = 128 * 1024  # on overflow, retain (roughly) the most-recent this-many bytes


def _log(msg: str) -> None:
    """Append a timestamped line to the persistent rotator log.

    Self-trims so the file stays bounded under the daemon's 60s cadence (read the
    last `_LOG_KEEP_BYTES`, drop the partial leading line so the file always starts
    on a record boundary, atomic os.replace). Best-effort by design: a log-IO error
    must NEVER crash a rotation decision — the decision is already on stdout, so we
    report the log failure to stderr and carry on. This is deliberate separation of
    an observability side-channel from the critical path, NOT a fallback of the core
    rotation logic. SECURITY: callers pass decision strings (emails + usage %s +
    fingerprints) — NEVER token values; the log shares state.json's trust boundary
    (under CLAUDE_PLUGIN_DATA, gitignored, user-only)."""
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S%z"), msg))
        if LOG_FILE.stat().st_size > _LOG_MAX_BYTES:
            tail = LOG_FILE.read_bytes()[-_LOG_KEEP_BYTES:]
            nl = tail.find(b"\n")  # discard the partial first record so we start on a boundary
            if nl != -1:
                tail = tail[nl + 1:]
            tmp = ROOT / "rotator.log.trim.tmp"
            tmp.write_bytes(tail)
            os.replace(tmp, LOG_FILE)
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
# to an account that is itself nearly exhausted. Switching at 97 (not 99/100)
# leaves headroom for the in-flight turn to finish on the old account while
# the next heartbeat turn picks up the new one (97 = the agreed middle between
# the original 95 and the user's 99; at 99 the in-flight turn risks a hard 429
# before the swap propagates). All overridable via env so a loop test can force
# an immediate switch (e.g. ROTATOR_SWITCH_AT_5H=1).
SWITCH_AT_5H = float(os.environ.get("ROTATOR_SWITCH_AT_5H", "97"))
SWITCH_AT_7D = float(os.environ.get("ROTATOR_SWITCH_AT_7D", "97"))
SAFE_5H = float(os.environ.get("ROTATOR_SAFE_5H", "90"))
SAFE_7D = float(os.environ.get("ROTATOR_SAFE_7D", "90"))
# Anti-thrash: minimum seconds between two auto-switches.
MIN_DWELL_S = float(os.environ.get("ROTATOR_MIN_DWELL_S", "60"))
# F2 expiry ladder (TRDD-7100178d, blocker 5): a token within this many hours of its LOCAL
# expiresAt (or already past it) counts as dead/dying. API-INDEPENDENT — read straight off the
# blob — so rotation can fire even when /api/oauth/usage is unreachable. Default 0.5h headroom;
# env-overridable for loop tests.
EXPIRY_GRACE_H = float(os.environ.get("ROTATOR_EXPIRY_GRACE_H", "0.5"))
# F2b keepalive (TRDD-7100178d): proactively refresh a SLOT token once its local runway drops
# below this many hours, so an idle alternate stays valid for an overnight rotation. MUST stay
# below the OAuth access-token lifetime so a freshly-refreshed token isn't immediately back in
# the window (no re-refresh spam). Env-overridable for loop tests.
KEEPALIVE_AHEAD_H = float(os.environ.get("ROTATOR_KEEPALIVE_AHEAD_H", "2"))
# A 429 on /api/oauth/usage can mean EITHER the account is genuinely rate-limited
# OR our polling tripped the endpoint's own throttle (transient). A genuinely
# maxed account 429s persistently; a throttle clears within a tick. So require
# the live-account 429 to persist across this many consecutive checks before
# treating it as "exhausted" and rotating away — a debounce against false trips.
LIVE_429_DEBOUNCE = int(os.environ.get("ROTATOR_LIVE_429_DEBOUNCE", "2"))


# --------------------------------------------------------------------------
# keychain helpers
# --------------------------------------------------------------------------
def _keychain_account() -> str:
    # The account attribute Claude Code uses is the macOS short username.
    return os.environ.get("USER") or os.environ.get("LOGNAME") or ""


def _security_add_password_via_stdin(service: str, account: str, data: str) -> None:
    """Write a keychain item with `security add-generic-password`, value on argv.

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
    `security` is absent (not macOS).
    """
    subprocess.run(
        ["security", "add-generic-password", "-U", "-s", service, "-a", account, "-w", data],
        check=True, capture_output=True, text=True,
    )


def _read_live_primary() -> dict | None:
    """Return the parsed live credential from its PRIMARY store, or None if absent/unreadable.
    read_live_blob() wraps this with the -livebak mirror fallback (Pillar 2).

    Cross-platform, first hit wins (ladder cribbed from the statusline helper):
      1. macOS keychain (account = $USER — precise, and the USER-override the
         capture flow relies on keys off this account attribute).
      2. ~/.claude/.credentials.json — the native store on Linux/Windows.
      3. GNOME Keyring via `secret-tool` — the Linux desktop keyring.
    On macOS the keychain path wins and the others are never reached.
    """
    # 1. macOS keychain
    acct = _keychain_account()
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", acct, "-w"],
            capture_output=True, text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                return json.loads(proc.stdout.strip())
            except json.JSONDecodeError:
                pass
    except FileNotFoundError:
        pass  # `security` only exists on macOS
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
            capture_output=True, text=True, timeout=5,
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


def read_live_blob() -> dict | None:
    """The live credential, robust against a corrupt/missing primary: the PRIMARY store ladder
    (_read_live_primary) first, then the redundant -livebak mirror (Pillar 2). A read never
    RESTORES the primary — that is _repair_integrity's job at tick start (a deliberate,
    once-per-tick action, not a side effect of every read) — it just always returns a usable
    blob while one survives anywhere."""
    return _read_live_primary() or _live_backup_read()


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
        _security_add_password_via_stdin(KEYCHAIN_SERVICE, acct, data)
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
                ["secret-tool", "store", "--label=Claude Code-credentials",
                 "service", KEYCHAIN_SERVICE],
                input=data, capture_output=True, text=True, timeout=5, check=False,
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
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service,
             "-a", email, "-w"],
            capture_output=True, text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                return json.loads(proc.stdout.strip())
            except json.JSONDecodeError:
                pass
    except FileNotFoundError:
        pass  # not macOS
    try:
        r = subprocess.run(
            ["secret-tool", "lookup", "service", service, "account", email],
            capture_output=True, text=True, timeout=5,
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
    try:
        _security_add_password_via_stdin(service, email, data)
        return True
    except FileNotFoundError:
        pass  # `security` ABSENT → not macOS — try the Linux keyring below
    except subprocess.CalledProcessError:
        # `security` PRESENT but the write FAILED. Do NOT fall through to the Linux
        # keyring (we ARE on macOS) and do NOT let write_slot drop a plaintext file —
        # surface a distinct sentinel so the caller fails closed.
        return KEYCHAIN_WRITE_FAILED
    try:
        r = subprocess.run(
            ["secret-tool", "store", "--label", "Claude Code rotator slot",
             "service", service, "account", email],
            input=data, capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _slot_keychain_delete(email: str, service: str = SLOT_KEYCHAIN_SERVICE) -> None:
    """Remove an account's slot token from the keychain `service` (best-effort, both
    stores). Used to forget a retired account and by the keychain tests' cleanup."""
    try:
        subprocess.run(
            ["security", "delete-generic-password", "-s", service, "-a", email],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        pass
    try:
        subprocess.run(
            ["secret-tool", "clear", "service", service, "account", email],
            capture_output=True, text=True, timeout=5,
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
        raise SlotKeychainWriteError(
            "keychain write failed for slot %s — refusing to drop a plaintext token "
            "(unlock the keychain / approve the access prompt, then retry)" % email)
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
        ok = (back is not None and bool(fingerprint(blob))
              and fingerprint(back) == fingerprint(blob))
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
        with urllib.request.urlopen(req, timeout=20) as r:
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
    """
    tok = _oauth(blob).get("accessToken")
    if not tok:
        return (0, None)
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": "Bearer " + tok,
            "Content-Type": "application/json",
            "anthropic-beta": OAUTH_BETA,
            "User-Agent": "claude-account-rotator",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return (getattr(r, "status", 200),
                    json.loads(r.read().decode("utf-8", "replace")))
    except urllib.error.HTTPError as e:        # MUST precede URLError (subclass)
        return (e.code, None)
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
        return (0, None)


def account_usage(blob: dict) -> dict | None:
    """Convenience wrapper for display: the usage dict on HTTP 200, else None."""
    status, data = usage_request(blob)
    return data if status == 200 else None


def refresh_oauth_token(blob: dict) -> dict | None:
    """Exchange a SLOT's refreshToken for a fresh token pair at the OAuth token endpoint and
    return a NEW blob (accessToken / refreshToken / expiresAt updated, other inner fields kept),
    or None on any failure (no refreshToken, HTTP/network error, or a response without an access
    token). Fail-soft by design — a keepalive failure must never crash the tick; the slot keeps
    its still-current token and F2a rotates away if it ever lapses.

    Only ever call this on SLOT tokens. The LIVE credential's refresh is owned by Claude Code;
    refreshing it here would race Claude's own (single-use, rotating) refresh-token grant and
    could invalidate its session — so _keepalive_refresh skips the live account."""
    inner = _oauth(blob)
    rtok = inner.get("refreshToken") or inner.get("refresh_token")
    if not rtok:
        return None
    body = json.dumps({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": rtok,
    }).encode()
    # MUST send a non-default User-Agent: urllib's default Python-urllib/<ver> is banned by
    # Cloudflare at the token endpoint (HTTP 403 / error code 1010 — "banned browser
    # signature"; empirically verified 2026-06-09). Reuse the same UA the /roles + /usage
    # calls already use (which pass CF) so keepalive-refresh isn't silently 1010-blocked.
    req = urllib.request.Request(
        TOKEN_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "claude-account-rotator"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            tok = json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError):
        return None
    access = tok.get("access_token") or tok.get("accessToken")
    if not access:
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
    blob = read_live_blob()
    if blob is None:
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
        print("capture FAILED: slot for %s did not round-trip (stored value corrupt or "
              "unreadable) — NOT recording it. See TRDD-5539cd6e." % email, file=sys.stderr)
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
        print("  %-32s captured=%s  token-expiry=%s%s"
              % (email, meta.get("captured_at", "?"), eh_s, flag))
    return 0


def cmd_switch(email: str) -> int:
    blob = read_slot(email)
    if blob is None:
        print("no slot for %r — capture it first (login to that account)" % email)
        return 1
    eh = expires_in_h(blob)
    if eh is not None and eh < 0:
        print("WARNING: %s slot's access token is already expired (%.1fh ago);"
              " a live process may need a refresh/restart." % (email, -eh))
    _switch_blob(email, blob, reason="manual switch")
    print("switched live credential -> %s" % email)
    # VERIFIED (binary 2.1.153 + this macOS host): no ~/.claude/.credentials.json
    # exists, so Claude Code's mt1() cache-guard clears the in-memory OAuth cache
    # on every token check and re-reads the keychain. A running `claude` therefore
    # picks up this account on its NEXT turn — no restart required.
    print("note: a running `claude` re-reads the keychain on its next turn "
          "(macOS), so it adopts this account without a restart.")
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
    save_state(state)


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
    return (("%.0f%%" % fh) if fh is not None else "?",
            ("%.0f%%" % sd) if sd is not None else "?")


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
    # local fingerprint match against known slots, then to the stale value as last resort.
    real_email = account_email(live_blob)
    if not real_email:
        for em in state.get("slots", {}):
            sb = read_slot(em)
            if sb and fingerprint(sb) == real_fp:
                real_email = em
                break
    state["live_email"] = real_email or old_email
    state["live_fp"] = real_fp
    state["live_429_streak"] = 0  # the debounce streak belonged to the stale account
    state["last_reconcile_at"] = time.time()
    save_state(state)
    print("auto: reconciled live account — state said %r but the real live credential "
          "is %r; state.json corrected" % (old_email, state["live_email"]))
    return state


def cmd_auto() -> int:
    """Proactive usage-based rotation. No-op unless the LIVE account is near a
    limit AND a safer alternate slot exists. Reads quota from /api/oauth/usage
    (zero inference cost), never switches onto an account that is itself near a
    limit, and honours an anti-thrash dwell guard. Fails safe: unknown usage
    never triggers a switch.
    """
    state = load_state()
    live_blob = read_live_blob()
    if live_blob is None:
        _decide("auto: no live credential")
        return 0
    # GROUND-TRUTH RECONCILE (TRDD-7100178d#6 stale-index / live-account drift): the actual
    # live keychain credential is authoritative. Correct state.json to match it BEFORE the
    # decision below, or the candidate list would treat the real live account as a target.
    state = _reconcile_live_email(state, live_blob)
    live_email = state.get("live_email")
    live_status, live_data = usage_request(live_blob)
    fh = _util(live_data, "five_hour")
    sd = _util(live_data, "seven_day")
    fh_s = ("%.0f%%" % fh) if fh is not None else "?"
    sd_s = ("%.0f%%" % sd) if sd is not None else "?"
    live_expired = _blob_locally_expired(live_blob)   # API-independent death signal (F2)
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
        save_state(state)
        if streak < LIVE_429_DEBOUNCE:
            _decide("auto: live %s returned 429 (streak %d/%d) — likely a transient "
                    "usage-endpoint throttle, not a real limit; deferring rotation"
                    % (live_email or "(live)", streak, LIVE_429_DEBOUNCE))
            return 0
        near = True
        live_desc = "RATE-LIMITED (429 x%d)" % streak
    elif live_status == 200:
        if state.get("live_429_streak"):
            state["live_429_streak"] = 0
            save_state(state)
        # Usage near a limit OR the token is about to expire locally (proactive pre-expiry swap).
        near = is_near_limit(fh, sd) or live_expired
        live_desc = "5h=%s 7d=%s%s" % (fh_s, sd_s, " +LOCALLY-EXPIRING" if live_expired else "")
    elif live_status in (401, 403):
        near = True   # server REJECTED the token (expired/invalid) — authoritative death signal
        live_desc = "token REJECTED (HTTP %d) — expired/invalid" % live_status
    elif live_expired:
        near = True   # no HTTP response, but the local expiresAt says the token is already dead
        live_desc = "LOCALLY EXPIRED + API unreachable (status %s)" % live_status
    else:
        _decide("auto: live %s usage unreachable (status %s) but token still valid locally; "
                "staying put" % (live_email or "(live)", live_status))
        return 0
    if not near:
        _decide("auto: live %s %s — within limits" % (live_email or "(live)", live_desc))
        return 0
    last = state.get("last_switch_at")
    if isinstance(last, (int, float)) and (time.time() - last) < MIN_DWELL_S:
        _decide("auto: live %s exhausted (%s) but inside dwell window; deferring"
                % (live_email or "(live)", live_desc))
        return 0
    # Build the alternate-candidate list. A safe TARGET is NEVER itself locally expired. When the
    # network is up we also require a fresh /usage 200 below SAFE on both windows and apply the
    # pure DRAIN-FIRST rule. When the network is DOWN (we are only here because the live token is
    # locally dead) we cannot usage-probe — fall back to LOCAL expiry: any alternate with a known
    # future expiry is a valid target, and we pick the one with the MOST runway.
    candidates: list[tuple[str, dict, float, float]] = []
    degraded: list[tuple[str, dict, float]] = []  # (email, blob, expires_in_h) — no-usage path
    for email in state.get("slots", {}):
        if email == live_email:
            continue
        b = read_slot(email)
        if not b:
            continue
        if _blob_locally_expired(b):
            continue  # never rotate ONTO a dead/dying token
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
                refreshed = refresh_oauth_token(b)
                if refreshed is None:
                    continue  # setup-token slot (no refreshToken) or the refresh grant failed
                try:
                    write_slot(email, refreshed)  # heal the lapsed slot in the keychain (as keepalive would)
                except SlotKeychainWriteError as exc:
                    # FAIL SOFT: a locked/declined keychain refused the persist. Still use the fresh
                    # token IN MEMORY for this decision — the goal is to not deadlock; a rotation
                    # onto it writes the live credential (a different keychain item), not this slot.
                    _log("[auto] %s: keychain write refused after refresh-on-err (%s) — "
                         "using fresh token in-memory" % (email, exc))
                b = refreshed
                st2, d2 = usage_request(b)  # re-probe with the fresh token
            if st2 != 200:
                continue  # still 429 (maxed) or error after the refresh attempt -> not a safe target
            bfh = _util(d2, "five_hour")
            bsd = _util(d2, "seven_day")
            if bfh is None or bsd is None:
                continue  # unknown usage -> not a safe target
            if not is_safe_alternate(bfh, bsd):
                continue  # itself near a limit -> skip
            candidates.append((email, b, bfh, bsd))
        else:
            eh = expires_in_h(b)
            if eh is None:
                continue  # cannot confirm validity offline -> not a safe degraded target
            degraded.append((email, b, eh))
    if network_up:
        best = select_drain_first(candidates)
        if best is None:
            _decide("auto: live %s exhausted (%s) but no alternate is healthy + below safe "
                    "threshold — all paid accounts maxed; waiting for a window to reset"
                    % (live_email or "(live)", live_desc))
            return 0
        target_email, target_blob, bfh, bsd = best
        reason = "live %s %s -> rotate" % (live_email or "(live)", live_desc)
        _switch_blob(target_email, target_blob, reason)
        _decide("auto: switched %s -> %s (target 5h=%.0f%% 7d=%.0f%%; %s)"
                % (live_email or "(live)", target_email, bfh, bsd, reason))
        return 0
    # Degraded (no-network) rotation: the live token is locally dead and /usage is unreachable.
    if not degraded:
        _decide("auto: live %s is LOCALLY EXPIRED and the API is unreachable, but no alternate "
                "with a known future expiry exists — cannot rotate; manual re-auth needed"
                % (live_email or "(live)"))
        return 0
    target_email, target_blob, target_eh = max(degraded, key=lambda c: c[2])
    reason = ("live %s %s -> degraded rotate (no usage; most-runway alternate)"
              % (live_email or "(live)", live_desc))
    _switch_blob(target_email, target_blob, reason)
    _decide("auto: switched %s -> %s (degraded; target token valid ~%.1fh; %s)"
            % (live_email or "(live)", target_email, target_eh, reason))
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
        fresh = refresh_oauth_token(blob)
        if fresh is None:
            continue  # refresh failed — keep the old token; F2a rotates away if it lapses
        try:
            write_slot(email, fresh)
        except SlotKeychainWriteError as exc:
            # FAIL CLOSED (P1): a locked/declined keychain refused the write. Do NOT drop a
            # plaintext token and do NOT crash the unattended tick — keep the old slot token
            # (F2a rotates away if it lapses) and skip the state update for this slot.
            print("[keepalive] %s: keychain write refused (%s) — kept old token, skipped"
                  % (email, exc), file=sys.stderr)
            _log("[keepalive] %s: keychain write refused (%s) — kept old token, skipped"
                 % (email, exc))  # failure deserves a durable record, not just ephemeral stderr
            continue
        meta = slots.get(email)
        if isinstance(meta, dict):
            meta["fp"] = fingerprint(fresh)
            meta["expires_at"] = _oauth(fresh).get("expiresAt")
            changed = True
        actions.append(email)
    if changed:
        save_state(state)
    return actions


def _bootstrap_eligible(has_refresh: bool, has_session_key: bool) -> bool:
    """PURE: is this slot a candidate for post-login auto-bootstrap?

    Eligible iff it CANNOT self-renew (no refreshToken — so keepalive can't keep
    it alive) but DOES have a live claude.ai Chrome session we can mint a fresh
    refresh-bearing slot from (slot_capture_browser auto-clicks Authorize on the
    seeded session). A slot that already has a refreshToken needs nothing; a slot
    with no live session has nothing to bootstrap FROM (that one needs a human
    login — surfaced by the oauth-login-needed detector).

    Delegates to the cascade SSOT (TRDD-dfc0959a): bootstrap-eligible ⇔ the
    account lands in the cascade's RENEW_COOKIE leg. Token expiry is irrelevant to
    this leg (the cookie, not the token, is what gets minted from), so it is
    passed as None. test_cascade proves this equals the historical truth table."""
    return cascade.classify(
        cascade.AccountState(
            email="", is_live=False, has_refresh=has_refresh,
            token_expires_h=None, has_session_cookie=has_session_key,
        )
    ) is cascade.CascadeLeg.RENEW_COOKIE


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
        rows = con.execute(
            "SELECT expires_utc FROM cookies WHERE name = 'sessionKey' "
            "AND host_key LIKE '%claude.ai'"
        ).fetchall()
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
    tick (a non-fatal helper must not crash the beat it runs in)."""
    launched: list[str] = []
    state = load_state()
    now = time.time()
    for email in list((state.get("slots") or {}).keys()):
        blob = read_slot(email)
        inner = _oauth(blob) if blob else {}
        has_refresh = bool(inner.get("refreshToken") or inner.get("refresh_token"))
        has_session = _profile_has_session_key(email, now=now)
        if not _bootstrap_eligible(has_refresh, has_session):
            continue
        try:
            if _invoke_slot_capture(email):  # True = LAUNCHED, False = skipped (already running)
                launched.append(email)
        except Exception as exc:  # noqa: BLE001 — documented best-effort contract
            # Best-effort by design: a launch failure (uv/Playwright spawn error, missing
            # profile, bad env) must NOT abort the remaining slots or the daemon tick this
            # runs inside. We deliberately swallow EVERY exception here (the one place
            # fail-fast is wrong — this is a last-line convenience, not a correctness gate)
            # and continue to the next eligible slot.
            print("[bootstrap] %s: capture launch failed (%r) — skipped" % (email, exc),
                  file=sys.stderr)
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
                write_live_blob(mirror)  # primary gone/corrupt -> restore it from the mirror
                actions.append("live credential: restored primary from -livebak mirror")
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
        out.append(cascade.AccountState(
            email=email,
            is_live=(email == live_email),
            has_refresh=bool(inner.get("refreshToken") or inner.get("refresh_token")),
            token_expires_h=(expires_in_h(blob) if blob else None),
            has_session_cookie=_profile_has_session_key(email, now=now),
        ))
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
        _log(cascade.cascade_plan(fleet, keepalive_ahead_h=KEEPALIVE_AHEAD_H).summary_line())
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
    if only_if_running and not claude_running():
        return 0
    # One-time, non-destructive: move state.json/opt-in from the legacy standalone root
    # into the canonical DATA-dir root. The smart _rotator_root() already reads from
    # whichever root holds the state, so this is just promotion — the NEXT tick process
    # then resolves to the canonical root. Safe to call every tick (no-op once migrated).
    migrate_root_to_canonical()
    _log_cascade_plan()       # explicit ROTATE→RENEW→REAUTH cascade visibility (best-effort, never a gate)
    refreshed = _keepalive_refresh()  # F2b: refresh slot tokens nearing expiry (prevent an overnight lapse)
    if refreshed:
        _log("keepalive: refreshed %s" % ", ".join(refreshed))  # durable record of token-prolonging action
    _repair_integrity()       # Pillar 2: verify/restore state + slots + live BEFORE deciding
    try:
        cmd_capture(False)
    except SlotKeychainWriteError as exc:
        # FAIL CLOSED (P1) without crashing the unattended tick: a locked/declined keychain
        # refused the slot write. The LIVE credential is untouched (Claude owns it); we simply
        # don't mirror it into a slot this beat (and never drop a plaintext token). The
        # standalone `rotator.py capture` still surfaces this error to the present human.
        print("[capture] keychain write refused (%s) — slot not filed this tick" % exc,
              file=sys.stderr)
        _log("[capture] keychain write refused (%s) — slot not filed this tick" % exc)
    rc = cmd_auto()           # usage-based rotation FIRST — never starved by bootstrap
    _bootstrap_seeded_slots()  # P4d (LAST): launch detached captures from human-seeded sessions
    return rc


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


def cmd_oauth_health(as_json: bool) -> int:
    """Print per-account OAuth health (has_refresh + expiry) read from the KEYCHAIN.

    The source is the keychain slots (and the live credential for the live account),
    NOT the legacy plaintext ``slots/<email>.json`` files the keychain migration
    deletes by design. lifetime-status.sh consumes this so its "is OAuth healthy /
    safe to refresh" verdict reflects the real keychain state on a migrated machine
    instead of asserting a false "no healthy OAuth" banner (audit C2). Read-only.

    With ``--json`` emits ``{email: {has_refresh, expires_days, expires_at}}``;
    otherwise a human-readable line per account.
    """
    state = load_state()
    emails = set(state.get("slots", {}).keys())
    live = state.get("live_email")
    if live:
        emails.add(live)
    live_blob = read_live_blob() if live else None
    health: dict[str, dict] = {}
    for e in sorted(emails):
        # Live account: trust the live keychain blob (freshest); everyone else (and a
        # failed live read) falls back to that account's stored slot.
        blob = (live_blob if (e == live and live_blob is not None) else None) or read_slot(e)
        if not isinstance(blob, dict):
            health[e] = {"has_refresh": False, "expires_days": None, "expires_at": None}
            continue
        o = _oauth(blob)
        hrs = expires_in_h(blob)
        health[e] = {
            "has_refresh": bool(o.get("refreshToken")),
            "expires_days": (hrs / 24) if hrs is not None else None,
            "expires_at": o.get("expiresAt"),
        }
    if as_json:
        print(json.dumps(health))
    else:
        for e, h in health.items():
            days = ("%.1f" % h["expires_days"]) if h["expires_days"] is not None else "?"
            print("%s\trefresh=%s\tdays=%s"
                  % (e, "yes" if h["has_refresh"] else "no", days))
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: rotator.py {capture [--only-if-claude-running] | "
              "tick [--only-if-claude-running] | auto | usage | live-email | "
              "known-emails | print-profiles-root | oauth-health [--json] | "
              "list | switch <email> | migrate-slots | "
              "delete-plaintext-slots | migrate-root}")
        return 2
    cmd = argv[0]
    # ── Read-only commands: no lock needed (they never write state.json / keychain). ──
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
    _MUTATING = {"capture", "tick", "auto", "switch",
                 "migrate-slots", "delete-plaintext-slots", "migrate-root"}
    if cmd not in _MUTATING:
        print("unknown command: %s" % cmd)
        return 2
    with gs.oauth_rotator_lock() as got:
        if not got:
            print("rotator: another rotator operation is in progress — skipped this run "
                  "(safe to retry).", file=sys.stderr)
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
                print("delete-plaintext-slots REFUSED — not yet in the keychain (run "
                      "migrate-slots first): %s" % ", ".join(unsafe))
                return 1
            removed = delete_plaintext_slot_files()
            print("delete-plaintext-slots: removed %d plaintext file(s): %s"
                  % (len(removed), ", ".join(removed) or "(none)"))
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
