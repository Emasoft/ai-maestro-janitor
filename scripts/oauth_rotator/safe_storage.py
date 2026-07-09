"""Cross-platform OS secret storage — the single abstraction for keeping rotator
secrets ENCRYPTED at rest in the platform's native secret store, never as plaintext
on disk (TRDD-dfc0959a Phase 2, USER directive #2).

Today the rotator stores OAuth TOKENS in the OS keychain via rotator._slot_keychain_*
(macOS `security`, Linux `secret-tool`). Phase 2 adds claude.ai session COOKIES to the
same encrypted-at-rest model so the keychain — not a plaintext Chrome profile sqlite —
is the source used to switch profiles. This module is that shared, generalized API
(both tokens and cookies can use it); it does NOT rip out the working token path —
the cookie path is built on it first, token migration is a later, separate step.

Backends (auto-selected; override for tests via ``CLAUDE_SAFE_STORAGE_BACKEND``):
  - ``macos``       — `security add/find/delete-generic-password` (the proven macOS path).
  - ``secret_tool`` — Linux Secret Service / libsecret (`secret-tool store/lookup/clear`).
  - ``dpapi``       — Windows per-user DPAPI via PowerShell `ConvertFrom/To-SecureString`,
                      persisted under ``%LOCALAPPDATA%\\ai-maestro-janitor\\safe-storage``.
                      Best-effort: implemented but not yet round-trip-verified on Windows.
  - ``none``        — no backend present → ``store`` returns ``NO_BACKEND`` so the caller
                      decides its fallback. It MUST NEVER silently drop a plaintext secret.

Write semantics generalize the proven three-valued result of
``rotator._slot_keychain_write`` (audit §3.1): a present-but-locked/declined store that
REFUSES a write returns ``FAILED`` (the caller fails closed — no plaintext fallback),
distinct from ``NO_BACKEND`` (no store at all, a documented plaintext fallback is legit).

Secret transit per backend (NOT uniform — a hard platform constraint, not a choice):
  - macOS: the value goes on ARGV (`security add-generic-password -w <data>`). The
    stdin-prompt form (`-w` with no value) reads via macOS ``getpass()``, whose buffer is
    a hard **128 bytes**, so it SILENTLY TRUNCATES any larger secret — the exact
    "rotator never worked" bug (TRDD-5539cd6e: an 8884-byte blob stored as 128). Cookie
    jars are kilobytes, so argv is mandatory. The brief `ps` exposure adds nothing: these
    keychain items are already readable by any same-user process via
    `find-generic-password -w` with no prompt.
  - Linux (`secret-tool`) and Windows (PowerShell DPAPI): the value goes on STDIN — no
    128-byte limit there — so it never touches argv.

Every secret is base64-wrapped at the public API before it reaches any backend (and
unwrapped on read). This is NOT for confidentiality (the backend already encrypts at
rest) — it makes the stored bytes PRINTABLE ASCII so the value round-trips byte-for-byte
regardless of newlines / unicode / binary content. Without it, macOS `security
find-generic-password -w` returns a HEX DUMP for any value containing non-printable
bytes (verified), silently corrupting cookie jars. base64 sidesteps that uniformly
across all three backends.

This module never logs a secret value.
"""

from __future__ import annotations

import base64
import binascii
import os
import platform
import subprocess
import sys
import time
from enum import Enum
from typing import NamedTuple

# How long to wait on a secret-store CLI before giving up (a hung keyring prompt must
# never wedge the unattended daemon tick).
_CLI_TIMEOUT_S = 10.0


# ==========================================================================
# THE SAFE KEYCHAIN PROTOCOL (TRDD-K3WQ7XM9 P1) — one choke-point every `security`
# call routes through, making a prompt-flood STRUCTURALLY IMPOSSIBLE.
#
# The 2026 flood was 0.31.0 rotator daemons doing UNBOUNDED `-w` reads of a slot whose
# ACL broke after the user rotated accounts → each read raised a keychain prompt → the
# daemon respawned → ~100 prompts. Three ordered defenses close it for good:
#   (b) DENIED-LATCH FIRST: once ANY `security` op is denied/hangs, a persistent flag is
#       set and EVERY later op short-circuits to "denied" WITHOUT spawning `security` —
#       so at most ONE prompt can EVER occur machine-wide until a human clears the latch.
#   (a) HARD TIMEOUT on every subprocess (a hung prompt can never wedge the caller).
#   (d) On a timeout / ACL-denied / user-canceled result: SET the latch + log ONE line.
# The headless primitive (skip the `-w` primary read entirely in daemon/detector/tick
# context) lives in rotator._primary_secret_read_permitted; the latch is the backstop that
# also covers SLOT reads and any path that isn't headless-gated.
# ==========================================================================

_KEYCHAIN_LATCH_NAME = "keychain-denied.latch"
# Substrings that mark a `security` result as a DENIAL worth latching on (case-insensitive).
# Deliberately NARROW: an ACL/unlock/interaction denial or a user-canceled prompt — NEVER
# "item could not be found" (a normal not-found must not latch and deny everything).
_DENIAL_MARKERS = (
    "user interaction is not allowed",
    "the user name or passphrase you entered is not correct",
    "user canceled",
    "user cancelled",
    "errsecauthfailed",
    "-25293",  # errSecAuthFailed
    "errsecinteractionnotallowed",
    "-25308",  # errSecInteractionNotAllowed
    "errsecusercanceled",
    "-128",    # errSecUserCanceled
)


class SecurityRun(NamedTuple):
    """Outcome of ONE gated `security` invocation via ``run_security``."""

    ok: bool               # `security` ran AND returned 0
    stdout: str            # its stdout (empty unless it ran)
    stderr: str            # its stderr (empty unless it ran)
    spawned: bool          # True IFF the `security` subprocess was actually launched
    denied: bool           # blocked by the pre-set latch (no spawn) OR this call tripped it
    returncode: int | None


def _keychain_latch_path() -> str:
    """Absolute path of the machine-wide denied-latch flag, resolved AT CALL TIME.

    Honors ``JANITOR_GLOBAL_STATE_DIR`` (the isolation lever every janitor global-state
    writer + the test suite uses) → else the janitor's global-state dir under HOME. Kept a
    plain env read (no ``global_state`` import) so safe_storage stays dependency-light and
    the latch is fully test-isolatable."""
    d = os.environ.get("JANITOR_GLOBAL_STATE_DIR", "").strip() or os.path.join(
        os.path.expanduser("~"), ".claude", "janitor-global-state"
    )
    return os.path.join(d, _KEYCHAIN_LATCH_NAME)


def keychain_denied_latched() -> bool:
    """True iff the denied-latch is set — a prior `security` op was denied/hung, so NO
    further op should even spawn `security` (it would just prompt again)."""
    return os.path.isfile(_keychain_latch_path())


def set_keychain_denied(reason: str) -> None:
    """Set the persistent denied-latch (atomic tmp+replace) and log ONE actionable line.
    Idempotent — never raises (a latch we can't write must not crash the caller)."""
    path = _keychain_latch_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        tmp = f"{path}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(f"{stamp}\t{reason}\n")
        os.replace(tmp, path)
    except OSError:
        pass  # best-effort — the in-call denial still returned; the latch is an optimization
    try:
        print(
            "[safe-storage] KEYCHAIN DENIED-LATCH SET: %s. All further `security` ops are "
            "suppressed (no prompt) until you re-grant access and clear the latch — run "
            "`rotator.py clear-keychain-latch` (or call safe_storage.clear_keychain_denied())."
            % reason,
            file=sys.stderr, flush=True,
        )
    except Exception:
        pass


def clear_keychain_denied() -> bool:
    """Clear the denied-latch so `security` ops resume. Call this from the arm / ACL-re-grant
    flow (the user has re-granted access). Returns True iff a latch was present + removed.
    Never raises."""
    path = _keychain_latch_path()
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def run_security(argv: list[str], *, timeout: float = _CLI_TIMEOUT_S) -> SecurityRun:
    """THE single gate EVERY `security` invocation (safe_storage AND rotator) routes through.

    Enforces the protocol in order: (b) denied-latch short-circuit BEFORE spawning →
    (a) hard timeout → (d) latch-on-denial. Never raises. When the latch is unset and no
    denial occurs, this is byte-identical to a plain ``subprocess.run(argv, timeout=...)``."""
    if keychain_denied_latched():
        # Short-circuit: the latch is set, so we must NOT spawn `security` (it would prompt).
        return SecurityRun(ok=False, stdout="", stderr="", spawned=False, denied=True, returncode=None)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        # `security` absent → not really macOS. NOT a denial; caller may try another backend.
        return SecurityRun(ok=False, stdout="", stderr="", spawned=False, denied=False, returncode=None)
    except subprocess.TimeoutExpired:
        set_keychain_denied(f"a `security` op hung past {timeout:g}s (a keychain unlock/ACL prompt)")
        return SecurityRun(ok=False, stdout="", stderr="", spawned=True, denied=True, returncode=None)
    stderr = proc.stderr or ""
    if proc.returncode != 0 and _is_denial(stderr):
        set_keychain_denied("`security` returned an ACL/auth/user-canceled denial")
        return SecurityRun(ok=False, stdout=proc.stdout or "", stderr=stderr, spawned=True, denied=True, returncode=proc.returncode)
    return SecurityRun(ok=(proc.returncode == 0), stdout=proc.stdout or "", stderr=stderr,
                       spawned=True, denied=False, returncode=proc.returncode)


def _is_denial(stderr: str) -> bool:
    """True iff a NON-ZERO `security` result is an ACL/auth/user-canceled DENIAL (latch it),
    as opposed to a benign not-found. Matches only the narrow denial markers; a
    'could not be found' is explicitly NOT a denial."""
    low = stderr.lower()
    if "could not be found" in low or "the specified item could not be found" in low:
        return False
    return any(m in low for m in _DENIAL_MARKERS)


class StoreResult(str, Enum):
    """Outcome of a ``store`` call — three-valued so callers can fail closed.

    ``str`` mixin so it is log/JSON friendly.
    """

    OK = "ok"                 # a secret store accepted the write
    NO_BACKEND = "no_backend"  # no secret store is present — caller's plaintext fallback is legit
    FAILED = "failed"          # a store IS present but the write FAILED — caller MUST fail closed


def detect_backend() -> str:
    """Return the active backend id: ``macos`` | ``secret_tool`` | ``dpapi`` | ``none``.

    Honours the ``CLAUDE_SAFE_STORAGE_BACKEND`` override first (tests / forcing a
    backend), else picks by platform + tool availability. Selection is by which CLI
    is actually present, so a Linux box without libsecret resolves to ``none`` rather
    than a backend that would always fail.
    """
    forced = os.environ.get("CLAUDE_SAFE_STORAGE_BACKEND", "").strip()
    if forced:
        return forced
    system = platform.system()
    if system == "Darwin" and _which("security"):
        return "macos"
    if system == "Windows" and _which("powershell"):
        return "dpapi"
    # Linux (and any other Unix) → Secret Service if secret-tool is installed.
    if _which("secret-tool"):
        return "secret_tool"
    # A mac without `security` is not a real scenario, but be defensive.
    if system == "Darwin" and _which("security"):
        return "macos"
    return "none"


def _which(tool: str) -> bool:
    """True iff ``tool`` is on PATH. Isolated so tests can monkeypatch availability."""
    from shutil import which

    return which(tool) is not None


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def store(service: str, account: str, secret: str) -> StoreResult:
    """Store ``secret`` (an opaque string — the caller serialises) ENCRYPTED under
    (``service``, ``account``). Returns a three-valued ``StoreResult`` (see class doc).

    The secret is base64-wrapped first so it round-trips byte-for-byte across newlines /
    unicode / binary (see module docstring — without it macOS hex-dumps non-printable
    values). On macOS the (printable-ASCII) wrapped value goes on argv; elsewhere stdin."""
    wrapped = base64.b64encode(secret.encode("utf-8")).decode("ascii")
    backend = detect_backend()
    if backend == "macos":
        return _macos_store(service, account, wrapped)
    if backend == "secret_tool":
        return _secret_tool_store(service, account, wrapped)
    if backend == "dpapi":
        return _dpapi_store(service, account, wrapped)
    return StoreResult.NO_BACKEND


def retrieve(service: str, account: str) -> str | None:
    """Return the stored secret string for (``service``, ``account``), or ``None`` if
    absent / unreadable / no backend / not a value this module wrote.

    Reads the base64-wrapped form the backend holds and unwraps it. A value that fails
    base64/UTF-8 decode (corrupt, or written by something other than ``store``) returns
    ``None`` rather than a garbled string — fail-safe."""
    backend = detect_backend()
    raw: str | None
    if backend == "macos":
        raw = _macos_retrieve(service, account)
    elif backend == "secret_tool":
        raw = _secret_tool_retrieve(service, account)
    elif backend == "dpapi":
        raw = _dpapi_retrieve(service, account)
    else:
        raw = None
    if raw is None:
        return None
    try:
        return base64.b64decode(raw.encode("ascii"), validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None


def delete(service: str, account: str) -> None:
    """Best-effort removal of (``service``, ``account``) from the active backend.
    Never raises — a missing item or absent backend is a no-op."""
    backend = detect_backend()
    if backend == "macos":
        _macos_delete(service, account)
    elif backend == "secret_tool":
        _secret_tool_delete(service, account)
    elif backend == "dpapi":
        _dpapi_delete(service, account)


# --------------------------------------------------------------------------
# Keychain-scope lever — the SINGLE source of truth for confining every rotator
# `security` op to a named keychain (TRDD-K3WQ7XM9 FIX B).
# --------------------------------------------------------------------------
def keychain_scope_args() -> list[str]:
    """Trailing `security` positional args that SCOPE every generic-password op to a
    specific keychain when ``JANITOR_ROTATOR_KEYCHAIN`` is set, else ``[]``.

    macOS ``security {add,find,delete}-generic-password`` all accept a trailing keychain
    path positional; naming it confines the op to THAT keychain instead of the default
    login-keychain search list. UNSET (production, the default) → ``[]`` → every argv is
    BYTE-IDENTICAL to before → the login keychain exactly as today. The lever exists so
    the keychain TESTS can point at a REAL but ISOLATED temp keychain (created via
    ``security create-keychain``): a genuine `security` round-trip that NEVER prompts /
    unlocks the user's real login keychain (the ~100× password/allow-prompt storm the
    OAuth real_state tests caused, 2026-07-09). Resolved AT CALL TIME so a test's
    ``monkeypatch.setenv`` is honored."""
    kc = os.environ.get("JANITOR_ROTATOR_KEYCHAIN", "").strip()
    return [kc] if kc else []


# --------------------------------------------------------------------------
# Argv builders — pure, so tests assert command construction without executing.
# --------------------------------------------------------------------------
def macos_store_argv(service: str, account: str, secret: str) -> list[str]:
    """`security add-generic-password` argv with the value ON ARGV (`-w <secret>`).

    Argv — NOT stdin — because the stdin form (`-w` with no value) reads via macOS
    ``getpass()`` (hard 128-byte buffer → silent truncation of any larger secret;
    TRDD-5539cd6e). `-U` updates an existing item. See the module docstring for the
    full rationale and why the brief `ps` exposure is acceptable for these items. A
    trailing ``keychain_scope_args()`` confines the write to the test keychain when set
    (empty in production → argv unchanged)."""
    return ["security", "add-generic-password", "-U", "-s", service, "-a", account, "-w", secret, *keychain_scope_args()]


def macos_retrieve_argv(service: str, account: str) -> list[str]:
    return ["security", "find-generic-password", "-s", service, "-a", account, "-w", *keychain_scope_args()]


def macos_delete_argv(service: str, account: str) -> list[str]:
    return ["security", "delete-generic-password", "-s", service, "-a", account, *keychain_scope_args()]


def secret_tool_store_argv(service: str, account: str) -> list[str]:
    return ["secret-tool", "store", "--label", "ai-maestro-janitor safe-storage",
            "service", service, "account", account]


def secret_tool_retrieve_argv(service: str, account: str) -> list[str]:
    return ["secret-tool", "lookup", "service", service, "account", account]


def secret_tool_delete_argv(service: str, account: str) -> list[str]:
    return ["secret-tool", "clear", "service", service, "account", account]


# --------------------------------------------------------------------------
# macOS backend (`security`) — mirrors the proven rotator._slot_keychain_* path.
# --------------------------------------------------------------------------
def _macos_store(service: str, account: str, secret: str) -> StoreResult:
    # Value on argv (NOT stdin) — the stdin form truncates at 128 bytes via getpass()
    # (TRDD-5539cd6e). Routed through the protocol choke-point (latch/timeout/latch-on-deny).
    run = run_security(macos_store_argv(service, account, secret))
    if not run.spawned and not run.denied:
        return StoreResult.NO_BACKEND   # `security` absent → not really macOS
    if not run.ok:
        return StoreResult.FAILED       # latched, hung, denied, or non-zero — fail closed
    return StoreResult.OK


def _macos_retrieve(service: str, account: str) -> str | None:
    run = run_security(macos_retrieve_argv(service, account))
    if not run.ok:
        return None                     # absent / latched / hung / denied / not-found
    # `security -w` prints the secret + a trailing newline; strip ONLY the trailing
    # newline `security` adds, not interior whitespace the secret may legitimately hold.
    out = run.stdout
    return out[:-1] if out.endswith("\n") else out


def _macos_delete(service: str, account: str) -> None:
    run_security(macos_delete_argv(service, account))  # best-effort; latch/timeout enforced


# --------------------------------------------------------------------------
# Linux backend (`secret-tool` / libsecret).
# --------------------------------------------------------------------------
def _secret_tool_store(service: str, account: str, secret: str) -> StoreResult:
    try:
        proc = subprocess.run(
            secret_tool_store_argv(service, account),
            input=secret, capture_output=True, text=True, timeout=_CLI_TIMEOUT_S,
        )
    except FileNotFoundError:
        return StoreResult.NO_BACKEND
    except subprocess.TimeoutExpired:
        return StoreResult.FAILED
    return StoreResult.OK if proc.returncode == 0 else StoreResult.FAILED


def _secret_tool_retrieve(service: str, account: str) -> str | None:
    try:
        proc = subprocess.run(
            secret_tool_retrieve_argv(service, account),
            capture_output=True, text=True, timeout=_CLI_TIMEOUT_S,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode == 0 and proc.stdout:
        # secret-tool lookup prints the secret with NO trailing newline of its own; but
        # strip a single trailing newline defensively in case a value was stored with one.
        out = proc.stdout
        return out[:-1] if out.endswith("\n") else out
    return None


def _secret_tool_delete(service: str, account: str) -> None:
    try:
        subprocess.run(secret_tool_delete_argv(service, account),
                       capture_output=True, text=True, timeout=_CLI_TIMEOUT_S)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


# --------------------------------------------------------------------------
# Windows backend (DPAPI via PowerShell). Best-effort: per-user encryption
# (ConvertFrom-SecureString uses DPAPI) persisted under %LOCALAPPDATA%. The secret
# is fed to PowerShell on STDIN, never on argv. Not yet round-trip-verified on Windows.
# --------------------------------------------------------------------------
def _dpapi_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "ai-maestro-janitor", "safe-storage")


def _dpapi_path(service: str, account: str) -> str:
    # Encode (service, account) into a filesystem-safe name; the DPAPI ciphertext is
    # per-user so the filename carries no secret.
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in f"{service}__{account}")
    return os.path.join(_dpapi_dir(), safe + ".dpapi")


def _dpapi_store(service: str, account: str, secret: str) -> StoreResult:
    path = _dpapi_path(service, account)
    # Read the secret from stdin ($input), DPAPI-encrypt it (ConvertTo-SecureString
    # -AsPlainText | ConvertFrom-SecureString → per-user ciphertext), write to $path.
    ps = (
        "$ErrorActionPreference='Stop';"
        "$dir=Split-Path -Parent $env:SS_PATH;"
        "if(!(Test-Path $dir)){New-Item -ItemType Directory -Force -Path $dir | Out-Null};"
        "$s=[Console]::In.ReadToEnd();"
        "$sec=ConvertTo-SecureString $s -AsPlainText -Force;"
        "ConvertFrom-SecureString $sec | Set-Content -NoNewline -Path $env:SS_PATH"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            input=secret, capture_output=True, text=True, timeout=_CLI_TIMEOUT_S,
            env={**os.environ, "SS_PATH": path},
        )
    except FileNotFoundError:
        return StoreResult.NO_BACKEND
    except subprocess.TimeoutExpired:
        return StoreResult.FAILED
    return StoreResult.OK if proc.returncode == 0 else StoreResult.FAILED


def _dpapi_retrieve(service: str, account: str) -> str | None:
    path = _dpapi_path(service, account)
    if not os.path.isfile(path):
        return None
    ps = (
        "$ErrorActionPreference='Stop';"
        "$enc=Get-Content -Raw -Path $env:SS_PATH;"
        "$sec=ConvertTo-SecureString $enc;"
        "$b=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec);"
        "[Runtime.InteropServices.Marshal]::PtrToStringBSTR($b)"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=_CLI_TIMEOUT_S,
            env={**os.environ, "SS_PATH": path},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode == 0:
        out = proc.stdout
        return out[:-1] if out.endswith("\n") else out
    return None


def _dpapi_delete(service: str, account: str) -> None:
    try:
        os.remove(_dpapi_path(service, account))
    except OSError:
        pass
