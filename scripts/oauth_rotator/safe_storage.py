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
from enum import Enum

# How long to wait on a secret-store CLI before giving up (a hung keyring prompt must
# never wedge the unattended daemon tick).
_CLI_TIMEOUT_S = 10.0


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
    try:
        # Value on argv (NOT stdin) — the stdin form truncates at 128 bytes via
        # getpass() (TRDD-5539cd6e); see macos_store_argv / the module docstring.
        proc = subprocess.run(
            macos_store_argv(service, account, secret),
            capture_output=True, text=True, timeout=_CLI_TIMEOUT_S,
        )
    except FileNotFoundError:
        return StoreResult.NO_BACKEND   # `security` absent → not really macOS
    except subprocess.TimeoutExpired:
        return StoreResult.FAILED       # a hung keychain prompt — fail closed
    return StoreResult.OK if proc.returncode == 0 else StoreResult.FAILED


def _macos_retrieve(service: str, account: str) -> str | None:
    try:
        proc = subprocess.run(
            macos_retrieve_argv(service, account),
            capture_output=True, text=True, timeout=_CLI_TIMEOUT_S,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    # `security -w` prints the secret + a trailing newline; strip ONLY the trailing
    # newline `security` adds, not interior whitespace the secret may legitimately hold.
    if proc.returncode == 0:
        out = proc.stdout
        return out[:-1] if out.endswith("\n") else out
    return None


def _macos_delete(service: str, account: str) -> None:
    try:
        subprocess.run(macos_delete_argv(service, account),
                       capture_output=True, text=True, timeout=_CLI_TIMEOUT_S)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


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
