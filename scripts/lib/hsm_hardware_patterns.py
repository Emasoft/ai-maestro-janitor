"""Hardware-token / HSM / Keystore / WebAuthn misuse pattern catalogue.

Wave-22 implementation, angle A — hardware-token substrate misuse. Source:
`reports/distill-round-8/hardware-token-hsm.md`.

What IS here (13 net-new hardware-substrate rules from distill-round-8/A,
RE2-safe regex — no negative lookaheads, no lookbehinds, no backreferences,
no non-possessive nested quantifiers):

  * hsm.macos-keychain-secret-via-argv             (HIGH)
  * hsm.windows-dpapi-via-powershell-arg-interpolation  (HIGH)
  * hsm.dpapi-ciphertext-path-from-env             (HIGH)
  * hsm.macos-keychain-missing-this-device-only    (MEDIUM)
  * hsm.pkcs11-lib-path-from-env-or-argv           (HIGH)
  * hsm.softhsm2-in-production-path                (HIGH)
  * hsm.pkcs11-pin-in-immutable-string             (HIGH)
  * hsm.hardware-rng-software-fallback             (MEDIUM)
  * hsm.secure-enclave-tokenid-missing             (HIGH)
  * hsm.android-keystore-user-auth-required-false  (HIGH)
  * hsm.totp-no-single-use-replay-tracking         (MEDIUM)
  * hsm.totp-secret-stored-plaintext-at-rest       (HIGH)
  * hsm.webauthn-attestation-none-accepted         (HIGH)

What is NOT here (deferred — listed for cross-reference):

  * TPM 2.0 PCR sealing / `tpm2_unseal` without policy — corpus has zero
    instances; deferred to a future wave with AST-level support.
  * WebAuthn `userVerification: 'discouraged'` — distill report parks
    this as "documented for future waves".
  * WebAuthn `timeout > 300000` — distill report parks this for future.
  * Backup-code single-use — distill report parks this for future.

What is NOT here (duplication carve-outs — DO NOT re-encode):

  * JWT alg=none / aud-iss missing — caught by auth_flow_patterns.py.
  * HMAC / KDF / RSA / RNG misuse OUTSIDE the hardware-substrate
    context — caught by crypto_misuse_patterns.py. The "hardware-RNG
    software-fallback" rule here is the substrate-specific case that
    crypto_misuse_patterns does not surface.

Severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW" — matches the
agent_config_patterns / auth_flow_patterns / crypto_misuse_patterns
conventions.

OWASP ASI mapping used here:
  ASI-04 — Insecure Output / data leak (secret-via-argv,
                                          DPAPI-via-PS-interpolation,
                                          PIN-in-immutable-string,
                                          TOTP-plaintext-at-rest)
  ASI-05 — Supply-chain / cross-tenant pivot (PKCS#11-lib-path-env,
                                                softhsm2-in-prod,
                                                LOCALAPPDATA path)
  ASI-07 — Authority / authorisation gaps (Keychain ACL flags,
                                             Secure-Enclave tokenID,
                                             Android Keystore auth-flag,
                                             TOTP single-use,
                                             WebAuthn attestation=none)
  ASI-08 — Cryptographic failures (hardware-RNG software fallback)

Public surface mirrors auth_flow_patterns.py exactly:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * Finding(rule_id, line, column, matched_text, severity, description, owasp_asi)
  * RULES — ordered tuple of every catalogued rule
  * scan_text(text, *, filename="") -> list[Finding]
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/auth_flow_patterns.Finding
    so heartbeat detectors can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — mirrors the
    helper in auth_flow_patterns.py so the surface is uniform across rule
    modules."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


def _re_cs(pattern: str) -> re.Pattern:
    """Compile a pattern WITHOUT IGNORECASE — case-sensitivity preserved.
    Used by rules where the `kSecAttr…` Apple constants and Java
    `KeyGenParameterSpec` builder calls are case-sensitive identifiers
    that must not absorb lowercase prose."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- Rule 1: hsm.macos-keychain-secret-via-argv -------------------------


# Verified from corpus (sealed-env `keychain.ts:170-182`). macOS
# `security add-generic-password -w <secret>` exposes the secret value
# on the process command line. The two shapes catch the JS / Python /
# shell forms of the same shell-out: the argv contains `-w` followed
# by a NON-empty literal or interpolation.
#
# The pattern is RE2-safe: simple character classes, bounded
# quantifiers, no lookarounds. The `[^\]\n]+` allows the captured
# value to be a literal or a JS template / Python f-string variable;
# the empty-value form (`-w` followed immediately by `,` or end-of-array)
# is the SAFE form (prompts on TTY / reads from stdin) and must NOT
# match — see the trailing requirement of `[^,\]\s][^\]\n]*` for at
# least one non-trivial value char.
_KEYCHAIN_ARGV_SECRET_RE = _re(
    # JS spawn/exec: spawnSync('security', [..., '-w', <value>, ...])
    r"\b(?:spawn(?:Sync)?|exec(?:File)?(?:Sync)?)\s*\(\s*"
    r"['\"]security['\"]\s*,\s*\[[^\]]*"
    r"['\"]-w['\"]\s*,\s*[^,\]\s\n][^,\]\n]*"
    r"|"
    # Python subprocess: subprocess.run(['security', ..., '-w', value])
    r"\bsubprocess\.(?:run|call|check_call|check_output|Popen)\s*\(\s*\[[^\]]*"
    r"['\"]security['\"][^\]]*['\"]-w['\"]\s*,\s*[^,\]\s\n][^,\]\n]*"
    r"|"
    # Shell-line: security add-generic-password ... -w <secret-non-prompt>
    r"\bsecurity\b[^\n|]*\badd-generic-password\b[^\n]*"
    r"\s-w\s+[^\s\-][^\s\n]*"
)


# ---- Rule 2: hsm.windows-dpapi-via-powershell-arg-interpolation ---------


# Verified from corpus (sealed-env `keychain.ts:104-129`). The marker:
# a `child_process` / `subprocess` call invoking PowerShell whose
# command-string interpolates the secret AND references
# `ProtectedData::Protect`. The combined shape is the bug — PS itself
# is fine if the secret is fed via stdin.
#
# Two regex parts (regex 1 picks up the JS form, regex 2 the Python
# form) — both require BOTH the interpolation marker (`${...}` or
# `{...}`) AND the `ProtectedData` payload, joined by an alternation
# in the same character window.
_DPAPI_PS_INTERPOLATION_RE = _re(
    # JS template-literal interpolation:  `... ${value} ... Protect ...`
    r"\b(?:spawn(?:Sync)?|exec(?:File)?(?:Sync)?)\s*\(\s*"
    r"['\"](?:powershell(?:\.exe)?|pwsh)['\"][^)]*\$\{[^}]+\}[^)]*ProtectedData"
    r"|"
    r"\b(?:spawn(?:Sync)?|exec(?:File)?(?:Sync)?)\s*\(\s*"
    r"['\"](?:powershell(?:\.exe)?|pwsh)['\"][^)]*ProtectedData[^)]*\$\{[^}]+\}"
    r"|"
    # Python f-string / .format interpolation
    r"\bsubprocess\.(?:run|call|check_call|check_output|Popen)\s*\([^)]*"
    r"(?:powershell|pwsh)[^)]*ProtectedData[^)]*\{[^}]+\}"
    r"|"
    r"\bsubprocess\.(?:run|call|check_call|check_output|Popen)\s*\([^)]*"
    r"(?:powershell|pwsh)[^)]*\{[^}]+\}[^)]*ProtectedData"
)


# Cross-line correlation: the `ProtectedData::Protect` payload is built
# in a variable using template-literal / f-string interpolation. We
# pair this with a separate same-file detection of a PowerShell spawn
# (any spawn, since the variable carries the unsafe payload there).
_DPAPI_INTERPOLATED_PAYLOAD_RE = _re(
    # JS template literal containing ProtectedData::Protect + ${...}
    r"`[^`]*\[System\.Security\.Cryptography\.ProtectedData\]"
    r"[^`]*\$\{[^}]+\}[^`]*`"
    r"|"
    r"`[^`]*\$\{[^}]+\}[^`]*\[System\.Security\.Cryptography\.ProtectedData\][^`]*`"
    r"|"
    # Python f-string with double-quote outer; inner content may include
    # single quotes — so the body class excludes only the outer quote.
    r"f\"[^\"\n]*ProtectedData[^\"\n]*\{[^}]+\}[^\"\n]*\""
    r"|"
    r"f\"[^\"\n]*\{[^}]+\}[^\"\n]*ProtectedData[^\"\n]*\""
    r"|"
    # Python f-string with single-quote outer; inner content may include
    # double quotes.
    r"f'[^'\n]*ProtectedData[^'\n]*\{[^}]+\}[^'\n]*'"
    r"|"
    r"f'[^'\n]*\{[^}]+\}[^'\n]*ProtectedData[^'\n]*'"
)


_POWERSHELL_SPAWN_RE = _re(
    r"\b(?:spawn(?:Sync)?|exec(?:File)?(?:Sync)?)\s*\(\s*"
    r"['\"](?:powershell(?:\.exe)?|pwsh)['\"]"
    r"|"
    r"\bsubprocess\.(?:run|call|check_call|check_output|Popen)\s*\("
    r"[^)]*['\"](?:powershell(?:\.exe)?|pwsh)['\"]"
)


# ---- Rule 3: hsm.dpapi-ciphertext-path-from-env -------------------------


# Verified from corpus (sealed-env `keychain.ts:146`). The bug: a
# DPAPI ciphertext path is built by interpolating
# `process.env['LOCALAPPDATA']` (or `process.env.LOCALAPPDATA` /
# `os.environ['LOCALAPPDATA']`) without canonicalisation. Attacker
# sets the env var to point anywhere the user can write — arbitrary
# write primitive.
_DPAPI_LOCALAPPDATA_RE = _re(
    # JS — process.env['LOCALAPPDATA'] / process.env.LOCALAPPDATA
    r"\bprocess\.env\s*(?:\.\s*LOCALAPPDATA|\[\s*['\"]LOCALAPPDATA['\"]\s*\])"
    r"[^\n]{0,200}(?:[/\\]|sealed[-_]env|\.bin\b|WriteAllBytes|New-Item|writeFileSync|fs\.writeFile)"
    r"|"
    # Python — os.environ['LOCALAPPDATA'] / os.getenv('LOCALAPPDATA')
    r"\bos\.(?:environ\s*\[\s*['\"]LOCALAPPDATA['\"]\s*\]|getenv\s*\(\s*['\"]LOCALAPPDATA['\"]\s*\))"
    r"[^\n]{0,200}(?:[/\\]|open\s*\(|Path\(|WriteAllBytes|writeFile)"
)


# ---- Rule 4: hsm.macos-keychain-missing-this-device-only ----------------


# Two-stage rule (Stage A + file-level guard in scan_text).
# Stage A trigger: any `SecItemAdd` / `kSecAttrAccessibleAlways` /
# `kSecAttrAccessibleAfterFirstUnlock` / `security add-generic-password`
# call. The file-level guard suppresses if `ThisDeviceOnly` appears
# anywhere in the file (then the dev DID opt out of sync — fine).
#
# Stage A is case-sensitive for the `kSecAttr…` constants (Apple's
# identifiers are camelCase and prose like "ksecattr" must NOT match).
_KEYCHAIN_NOT_DEVICE_ONLY_RE = _re_cs(
    r"\bkSecAttrAccessibleAlways\b"
    r"|"
    r"\bkSecAttrAccessibleAfterFirstUnlock\b"
    r"|"
    # CLI: `security add-generic-password` — trigger; file-level
    # ThisDeviceOnly / -T guard handled in scan_text.
    r"\bsecurity\b\s+add-generic-password\b"
)


# File-level guard — ANY of these anywhere in the file means the
# author considered Keychain ACL flags and explicitly chose the
# device-bound shape. Drop every Stage-A hit.
_KEYCHAIN_DEVICE_ONLY_GUARDS: tuple[re.Pattern, ...] = (
    re.compile(r"\bkSecAttrAccessibleWhenUnlockedThisDeviceOnly\b",
               re.MULTILINE | re.UNICODE),
    re.compile(r"\bkSecAttrAccessibleAfterFirstUnlockThisDeviceOnly\b",
               re.MULTILINE | re.UNICODE),
    re.compile(r"\bkSecAttrAccessibleWhenPasscodeSetThisDeviceOnly\b",
               re.MULTILINE | re.UNICODE),
    re.compile(r"#\s*keychain-sync-ok\b", re.IGNORECASE | re.MULTILINE),
)


# ---- Rule 5: hsm.pkcs11-lib-path-from-env-or-argv -----------------------


# PKCS#11 module path sourced from the environment or argv. The
# loaded `.so`/`.dll` runs in-process and sees every PIN / key handle
# / signature op (RFC 7512). Same trust class as `LD_PRELOAD`.
_PKCS11_LIB_PATH_RE = _re(
    # Python ctypes.CDLL with env-controlled path
    r"\bCDLL\s*\(\s*(?:os\.environ\s*\.\s*get\s*\(|os\.environ\s*\[|os\.getenv\s*\(|sys\.argv\s*\[)"
    r"|"
    r"\bcdll\.LoadLibrary\s*\(\s*(?:os\.environ\s*\.\s*get\s*\(|os\.environ\s*\[|os\.getenv\s*\(|sys\.argv\s*\[)"
    r"|"
    # PyKCS11Lib().load(env-var)
    r"\bPyKCS11Lib\s*\(\s*\)\s*\.\s*load\s*\(\s*(?:os\.environ\s*\.\s*get\s*\(|os\.environ\s*\[|os\.getenv\s*\(|sys\.argv\s*\[)"
    r"|"
    # Shell: pkcs11-tool --module $VAR / --module ${VAR}
    r"\bpkcs11-tool\b[^\n]*--module\s+(?:\$\w+|\$\{\w+\}|%\w+%)"
    r"|"
    # Generic: PKCS11_MODULE / PKCS11_LIB env-var name on a load line
    r"\b(?:os\.environ\s*\[\s*['\"](?:PKCS11_LIB|PKCS11_MODULE)['\"]\s*\]|os\.getenv\s*\(\s*['\"](?:PKCS11_LIB|PKCS11_MODULE)['\"])"
)


# ---- Rule 6: hsm.softhsm2-in-production-path ----------------------------


# Two-stage. Stage A: any reference to `libsofthsm2.so` /
# `softhsm2-util`. Stage B (in scan_text): suppress if the source
# path or surrounding lines (window=4) look like a test fixture.
_SOFTHSM2_REF_RE = _re(
    r"\blibsofthsm2\.so(?:\.\d+)?\b"
    r"|"
    r"\bsofthsm2-util\b"
)


# Filename-hint allow-list for softhsm2 references — softhsm2 IS the
# canonical PKCS#11 test fixture, so tests/fixtures/e2e directories
# are exempt. Production paths are NOT exempt.
_SOFTHSM2_TEST_FILENAME_HINTS: tuple[re.Pattern, ...] = (
    re.compile(r"(?:^|/)tests?/", re.IGNORECASE),
    re.compile(r"(?:^|/)__tests?__/", re.IGNORECASE),
    re.compile(r"(?:^|/)_tests?/", re.IGNORECASE),
    re.compile(r"(?:^|/)e2e/", re.IGNORECASE),
    re.compile(r"(?:^|/)fixtures?/", re.IGNORECASE),
    re.compile(r"(?:^|/)spec/", re.IGNORECASE),
    re.compile(r"(?:^|/)specs?/", re.IGNORECASE),
    re.compile(r"_test(?:s)?\.[A-Za-z]+$", re.IGNORECASE),
    re.compile(r"\.test\.[A-Za-z]+$", re.IGNORECASE),
    re.compile(r"\.spec\.[A-Za-z]+$", re.IGNORECASE),
)


# Context-hint allow-list — if the surrounding lines say "test
# fixture" / "softhsm2 for testing" the hit is benign.
_SOFTHSM2_TEST_CONTEXT_RE = _re(
    r"#\s*softhsm2-test-only\b"
    r"|"
    r"#\s*test\s+fixture\b"
    r"|"
    r"//\s*softhsm2-test-only\b"
)


# ---- Rule 7: hsm.pkcs11-pin-in-immutable-string -------------------------


# PKCS#11 PIN read into a Python `str` / Java `String` (both are
# immutable + interned). Correct form is `bytearray` / `char[]`
# zero-filled after `C_Login`.
_PKCS11_PIN_IMMUTABLE_RE = _re(
    # Python: <name>_pin = os.environ[...] / os.getenv(...) / input(...) / getpass.getpass(...)
    r"(?:^|\s)(?:hsm[_-]?pin|pkcs11[_-]?pin|user[_-]?pin|so[_-]?pin|slot[_-]?pin|token[_-]?pin)\s*=\s*"
    r"(?:os\.environ\s*\[|os\.environ\s*\.\s*get|os\.getenv\s*\(|input\s*\(|getpass\.getpass\s*\(|sys\.argv\s*\[)"
    r"|"
    # Python: any PIN var = a STRING LITERAL (not bytes / bytearray)
    r"(?:^|\s)(?:hsm[_-]?pin|pkcs11[_-]?pin|user[_-]?pin|so[_-]?pin)\s*=\s*['\"][^'\"\n]+['\"]"
    r"|"
    # Java: String pin = ... / String userPin = ...
    r"\bString\s+(?:hsmPin|pkcs11Pin|userPin|soPin|pin)\s*="
    r"|"
    # Java JNI: pPin / pin char[] is the SAFE form, so we flag the
    # String form (the unsafe form). Java: `pinValue.getBytes()` from
    # a String earlier in the file is also unsafe; we catch the
    # assignment.
    r"\bString\s+\w*[pP]in\w*\s*=\s*(?:System\.getenv|System\.getProperty)"
)


# ---- Rule 8: hsm.hardware-rng-software-fallback -------------------------


# A `try` block that calls a hardware-RNG entrypoint AND a paired
# `except` block that falls back to a software CSPRNG with NO
# logging / NO strict-mode raise. The pattern matches the multi-line
# shape; MULTILINE+DOTALL via the [\s\S] character class.
_HARDWARE_RNG_FALLBACK_RE = _re(
    r"\btry\s*:\s*\n[^\n]*"
    r"(?:tpm2_getrandom|C_GenerateRandom|yubikey[^\n]*\.get_random|"
    r"YK_get_serial|softhsm2[^\n]*get_random|nitrokey[^\n]*random)"
    r"[\s\S]{0,400}?"
    r"\bexcept\b[\s\S]{0,200}?"
    r"(?:os\.urandom|secrets\.token_bytes|secrets\.token_hex|"
    r"random\.SystemRandom|Random\.new\(\)\.read|crypto\.randomBytes)"
)


# Strict-mode / log marker — if the except-block contains a log
# call OR a STRICT_HARDWARE_RNG env-var check, suppress.
_HARDWARE_RNG_STRICT_CONTEXT_RE = _re(
    r"\b(?:log(?:ger|ging)?\.(?:warn|warning|error|critical)|"
    r"raise\s+(?:RuntimeError|HsmError|HardwareRequired|StrictHardwareRng)|"
    r"STRICT_HARDWARE_RNG)\b"
)


# ---- Rule 9: hsm.secure-enclave-tokenid-missing -------------------------


# Two-stage. Stage A: any `SecKeyCreateRandomKey(...)` call.
# Stage B (file-level): suppress if `kSecAttrTokenIDSecureEnclave`
# appears anywhere in the file (the dev IS using the Secure Enclave).
_SECKEY_CREATE_RANDOM_RE = _re_cs(
    r"\bSecKeyCreateRandomKey\s*\("
)


_SECURE_ENCLAVE_FILE_GUARDS: tuple[re.Pattern, ...] = (
    re.compile(r"\bkSecAttrTokenIDSecureEnclave\b", re.MULTILINE | re.UNICODE),
    re.compile(r"#\s*secure-enclave-exempt\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"//\s*secure-enclave-exempt\b", re.IGNORECASE | re.MULTILINE),
)


# ---- Rule 10: hsm.android-keystore-user-auth-required-false -------------


# Direct shape: `.setUserAuthenticationRequired(false)` on a
# `KeyGenParameterSpec.Builder` chain. The Kotlin / Java forms are
# identical at the call site.
_ANDROID_KEYSTORE_AUTH_FALSE_RE = _re(
    r"\.setUserAuthenticationRequired\s*\(\s*false\s*\)"
)


# Two-stage variant: KeyGenParameterSpec.Builder(...) that contains
# NONE of the auth-binding calls. This is the "default is false on
# older API levels" shape — flagged only when the file uses
# KeyGenParameterSpec.Builder AND lacks any auth-binding call.
_KEYGEN_PARAM_BUILDER_TRIGGER_RE = _re(
    r"\bKeyGenParameterSpec\.Builder\s*\("
)


_ANDROID_KEYSTORE_AUTH_GUARDS: tuple[re.Pattern, ...] = (
    re.compile(r"\.setUserAuthenticationRequired\s*\(\s*true\s*\)",
               re.MULTILINE),
    re.compile(r"\.setUnlockedDeviceRequired\s*\(\s*true\s*\)",
               re.MULTILINE),
    re.compile(r"\.setUserAuthenticationValidityDurationSeconds\s*\(",
               re.MULTILINE),
    re.compile(r"\.setUserAuthenticationParameters\s*\(",
               re.MULTILINE),
    re.compile(r"//\s*android-keystore-no-auth\b", re.IGNORECASE | re.MULTILINE),
)


# ---- Rule 11: hsm.totp-no-single-use-replay-tracking --------------------


# Stage A trigger: a function named `verifyTotp`/`verifyHotp`/
# `verifyOtp` (any case). Stage B (file-level): suppress if the file
# anywhere references a "used codes" sink — Redis SADD, DB INSERT
# into a `used_otp`/`otp_used` table, a Set being added to, a
# Bloom filter, or a `@replay_guard` decorator.
_VERIFY_TOTP_TRIGGER_RE = _re(
    r"\b(?:function|def|fn)\s+verify(?:Totp|Hotp|Otp)\s*\("
    r"|"
    r"\b(?:const|let|var)\s+verify(?:Totp|Hotp|Otp)\s*="
    r"|"
    r"\bverify(?:Totp|Hotp|Otp)\s*:\s*(?:function|\([^)]*\)\s*=>)"
)


_TOTP_REPLAY_GUARD_RE = _re(
    r"\bSADD\s+\w*otp\w*"
    r"|"
    r"\bINSERT\b[^\n]+(?:used[_-]?otp|otp[_-]?used|used[_-]?codes|otp[_-]?history)"
    r"|"
    r"\b(?:used[_-]?codes|used[_-]?otp|otp[_-]?used)\s*\.\s*(?:add|push|append)"
    r"|"
    # `@` is non-word so `\b` cannot anchor on its left; match the decorator
    # at line-start or after whitespace instead.
    r"(?:^|\s)@replay[_-]?guard\b"
    r"|"
    r"\b(?:r|redis|cache)\.(?:setex|set|sadd)\s*\([^)]*otp"
    r"|"
    r"#\s*totp-replay-guarded\b"
    r"|"
    r"//\s*totp-replay-guarded\b"
)


# ---- Rule 12: hsm.totp-secret-stored-plaintext-at-rest ------------------


# Stage A trigger: a TOTP-secret assignment from a user-controlled
# / network-controlled source. Stage B (file-level): suppress if the
# file uses KMS / Fernet / nacl.secret / crypto.subtle.encrypt /
# envelope encryption.
_TOTP_SECRET_ASSIGN_RE = _re(
    r"\b(?:totp[_-]?secret|hotp[_-]?secret|otp[_-]?secret|"
    r"two[_-]?factor[_-]?secret|mfa[_-]?secret|2fa[_-]?secret)\s*=\s*"
    r"(?:request\.|req\.body|req\.json|input\s*\(|json\.loads\s*\(|json\.parse\s*\(|"
    r"new\s+OTPAuth|generateSecret|crypto\.randomBytes)"
)


# Persistence sink — INSERT / .save() / file write / Redis SET that
# appears WITHIN 12 lines AFTER the assign trigger.
_TOTP_PERSIST_SINK_RE = _re(
    r"\bINSERT\b[^\n]+(?:user|account|mfa|two[_-]?factor)"
    r"|"
    r"\bcursor\.execute\s*\(\s*['\"]INSERT"
    r"|"
    r"\bdb\.execute\s*\(\s*['\"]INSERT"
    r"|"
    r"\b\w+\.save\s*\(\s*\)"
    r"|"
    r"\bopen\s*\([^)]*['\"]w[b+]?['\"]"
    r"|"
    r"\bfs\.writeFile(?:Sync)?\s*\("
    r"|"
    r"\bredis\.(?:set|hset|setex|hmset)\s*\("
)


_TOTP_ENCRYPT_GUARDS: tuple[re.Pattern, ...] = (
    re.compile(r"\bkms\.(?:encrypt|generate_data_key)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\bFernet\s*\(", re.MULTILINE),
    re.compile(r"\bnacl\.secret\.SecretBox", re.MULTILINE),
    re.compile(r"\bcrypto\.subtle\.encrypt", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\bAES\.new\([^)]*MODE_GCM", re.MULTILINE),
    re.compile(r"\bencrypt(?:WithKms|Envelope|AtRest)\s*\(", re.MULTILINE),
    re.compile(r"#\s*totp-secret-encrypted-at-rest\b",
               re.IGNORECASE | re.MULTILINE),
)


# ---- Rule 13: hsm.webauthn-attestation-none-accepted --------------------


# Catches: client-side `navigator.credentials.create` with
# `attestation: 'none'`, server-side allow-list with
# `attestationType: "none"`, or a `verifyRegistration` call passing
# `requireUserVerification: false` AND no attestation policy.
_WEBAUTHN_ATTESTATION_NONE_RE = _re(
    # Client: navigator.credentials.create({publicKey:{...attestation:'none'...}})
    r"\bnavigator\.credentials\.create\s*\(\s*\{[\s\S]{0,300}?attestation\s*:\s*['\"]none['\"]"
    r"|"
    # Server (Python py_webauthn / fido2): attestation='none' kwargs
    r"\bgenerate_registration_options\s*\([^)]*attestation\s*=\s*['\"]none['\"]"
    r"|"
    # Server JS (SimpleWebAuthn): attestationType: 'none'
    r"\battestationType\s*:\s*['\"]none['\"]"
    r"|"
    # FIDO2 server config: allowedAttestationFormats: ['none']
    r"\ballowedAttestationFormats\s*[:=]\s*\[\s*['\"]none['\"]\s*\]"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="hsm.macos-keychain-secret-via-argv",
        name="macOS Keychain shell-out leaks secret via argv",
        severity="HIGH",
        description=(
            "macOS `security add-generic-password -w <secret>` shell-out "
            "puts the secret value on the process command line — visible "
            "to `ps -ef`, `/proc/<pid>/cmdline` equivalents (`libproc`), "
            "and any EDR audit hook. Correct shape: omit the value after "
            "`-w` and feed via stdin so the secret stays out of argv. "
            "Source: sealed-env `keychain.ts:170-182`."
        ),
        pattern=_KEYCHAIN_ARGV_SECRET_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="hsm.windows-dpapi-via-powershell-arg-interpolation",
        name="Windows DPAPI invoked via PowerShell with arg interpolation",
        severity="HIGH",
        description=(
            "`child_process` / `subprocess` invoking PowerShell with "
            "`[System.Security.Cryptography.ProtectedData]::Protect` "
            "AND interpolating the secret into the command string. The "
            "secret lands in the PowerShell child-process argv — readable "
            "via `Get-WmiObject Win32_Process` from any admin. Correct "
            "shape: feed the secret to `powershell -Command -` via stdin. "
            "Source: sealed-env `keychain.ts:104-129`."
        ),
        pattern=_DPAPI_PS_INTERPOLATION_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="hsm.dpapi-ciphertext-path-from-env",
        name="DPAPI ciphertext path interpolated from LOCALAPPDATA env-var",
        severity="HIGH",
        description=(
            "DPAPI on-disk ciphertext path built by interpolating "
            "`process.env['LOCALAPPDATA']` / `os.environ['LOCALAPPDATA']`. "
            "An attacker who controls the env var (parent shell, env "
            "file, sourced `.env`, Docker entrypoint) can redirect the "
            "write to any path the user can reach — arbitrary file "
            "write primitive. Correct shape: resolve via "
            "`SHGetFolderPath(CSIDL_LOCAL_APPDATA)` / "
            "`os.homedir() + '\\\\AppData\\\\Local'` and canonicalise. "
            "Source: sealed-env `keychain.ts:146`."
        ),
        pattern=_DPAPI_LOCALAPPDATA_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="hsm.macos-keychain-missing-this-device-only",
        name="macOS Keychain entry not pinned to ThisDeviceOnly",
        severity="MEDIUM",
        description=(
            "Keychain entry created with "
            "`kSecAttrAccessibleAlways` / "
            "`kSecAttrAccessibleAfterFirstUnlock`, OR via "
            "`security add-generic-password`, with NO "
            "`ThisDeviceOnly` flag anywhere in the file. The entry "
            "syncs to iCloud Keychain if the operator has it enabled — "
            "compromise of the Apple ID becomes master-key exfil. "
            "Correct flag for master keys: "
            "`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`."
        ),
        pattern=_KEYCHAIN_NOT_DEVICE_ONLY_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="hsm.pkcs11-lib-path-from-env-or-argv",
        name="PKCS#11 module path sourced from environment or argv",
        severity="HIGH",
        description=(
            "PKCS#11 module loaded by path read from "
            "`os.environ['PKCS11_LIB']`, `os.getenv('PKCS11_MODULE')`, "
            "`sys.argv`, or `pkcs11-tool --module $VAR`. The `.so`/`.dll` "
            "runs in-process with full visibility of every PIN, key "
            "handle, and signature op — same trust class as LD_PRELOAD. "
            "Correct shape: hardcode the canonical path or read from a "
            "root-owned config file, and verify SHA-256 of the loaded "
            "library against a pinned hash before `C_Initialize`."
        ),
        pattern=_PKCS11_LIB_PATH_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="hsm.softhsm2-in-production-path",
        name="softhsm2 (software HSM) loaded in non-test path",
        severity="HIGH",
        description=(
            "Reference to `libsofthsm2.so` / `softhsm2-util` outside of "
            "test / fixture / e2e directories. softhsm2 is software-only "
            "(README: 'for testing only, no hardware protection'). When "
            "the deployment manifest loads softhsm2 in production the "
            "claimed HSM threat model is fiction. Correct shape: use a "
            "real HSM in production (CloudHSM, YubiHSM2, vendor PKCS#11) "
            "and configure module path per environment."
        ),
        pattern=_SOFTHSM2_REF_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="hsm.pkcs11-pin-in-immutable-string",
        name="PKCS#11 PIN stored in immutable Python str / Java String",
        severity="HIGH",
        description=(
            "PKCS#11 PIN assigned to a Python `str` or Java `String` "
            "from `os.environ`, `getpass.getpass`, `input`, "
            "`System.getenv`, or a string literal. Both `str` and "
            "`String` are immutable + interned — the PIN persists in "
            "the GC heap / string table for the lifetime of the "
            "process even after the caller deletes the binding. Env "
            "vars additionally leak to every child `subprocess` that "
            "does not override `env=`. Correct shape: "
            "`bytearray(getpass.getpass().encode())` (Python) or "
            "`char[]` + `Arrays.fill` (Java), zero-filled immediately "
            "after `C_Login`."
        ),
        pattern=_PKCS11_PIN_IMMUTABLE_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="hsm.hardware-rng-software-fallback",
        name="Hardware RNG with silent software fallback",
        severity="MEDIUM",
        description=(
            "A `try` block invokes a hardware-RNG entrypoint "
            "(`tpm2_getrandom`, `C_GenerateRandom`, "
            "`yubikey.get_random`, nitrokey, softhsm2) and a paired "
            "`except` falls back to a software CSPRNG (`os.urandom`, "
            "`secrets.token_bytes`, `random.SystemRandom`, "
            "`crypto.randomBytes`) with NO log line and NO strict-mode "
            "raise. The CSPRNG output is fine, but the THREAT MODEL "
            "is wrong — the caller paid for a hardware-bound RNG. "
            "Correct shape: WARN-level log + opt-in "
            "`STRICT_HARDWARE_RNG=1` that raises on fallback."
        ),
        pattern=_HARDWARE_RNG_FALLBACK_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="hsm.secure-enclave-tokenid-missing",
        name="Secure Enclave key creation missing kSecAttrTokenID",
        severity="HIGH",
        description=(
            "`SecKeyCreateRandomKey` called in a file with NO "
            "`kSecAttrTokenIDSecureEnclave` reference. The key lands "
            "in the regular Keychain (software-backed) — extractable "
            "via jailbreak Keychain-dump, `security` CLI on macOS, or "
            "to any app in the same Keychain access group. Developer "
            "intent ('Secure Enclave key' per product spec) silently "
            "degrades to a software key. Correct shape: include "
            "`kSecAttrTokenID: kSecAttrTokenIDSecureEnclave` AND "
            "`kSecAttrKeyType: kSecAttrKeyTypeECSECPrimeRandom` "
            "(Secure Enclave is P-256-only)."
        ),
        pattern=_SECKEY_CREATE_RANDOM_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="hsm.android-keystore-user-auth-required-false",
        name="Android Keystore signing key without user-auth gate",
        severity="HIGH",
        description=(
            "`KeyGenParameterSpec.Builder(...).setUserAuthenticationRequired(false)` "
            "OR a `KeyGenParameterSpec.Builder` chain that calls NONE "
            "of `.setUserAuthenticationRequired(true)`, "
            "`.setUnlockedDeviceRequired(true)`, "
            "`.setUserAuthenticationValidityDurationSeconds(...)`, "
            "`.setUserAuthenticationParameters(...)`. Keystore-backed "
            "signing key without biometric/PIN gate is usable by any "
            "app component or Frida hook — the TEE/StrongBox guarantee "
            "is moot. Correct shape: "
            "`.setUserAuthenticationRequired(true)` plus "
            "`.setUnlockedDeviceRequired(true)`."
        ),
        pattern=_ANDROID_KEYSTORE_AUTH_FALSE_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="hsm.totp-no-single-use-replay-tracking",
        name="TOTP / HOTP verify with no single-use enforcement",
        severity="MEDIUM",
        description=(
            "`verifyTotp` / `verifyHotp` / `verifyOtp` defined and the "
            "file contains NO replay-tracking sink (Redis SADD, DB "
            "INSERT into used_otp, in-memory set add, `@replay_guard` "
            "decorator). RFC 6238 §5.2 mandates: 'the verifier MUST "
            "NOT accept the same OTP value that has already been "
            "verified'. With ±1-step tolerance the verifier accepts 3 "
            "distinct codes per moment — a phished code can be "
            "replayed for the remainder of validity. Source: sealed-env "
            "`totp.ts:49-69`."
        ),
        pattern=_VERIFY_TOTP_TRIGGER_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="hsm.totp-secret-stored-plaintext-at-rest",
        name="TOTP secret persisted without encryption at rest",
        severity="HIGH",
        description=(
            "TOTP / HOTP / MFA secret assigned from a network / user "
            "input AND a persistence sink (INSERT, `.save()`, file "
            "open-for-write, `fs.writeFile`, `redis.set`) appears in "
            "the same file with NO envelope-encryption call (KMS, "
            "Fernet, nacl.secret, crypto.subtle.encrypt). The secret "
            "is the seed — a DB dump = every user's MFA forged. "
            "Correct shape: wrap with KMS / HSM envelope before "
            "INSERT, decrypt only on verify, zero-fill after use."
        ),
        pattern=_TOTP_SECRET_ASSIGN_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="hsm.webauthn-attestation-none-accepted",
        name="WebAuthn registration accepts attestation='none'",
        severity="HIGH",
        description=(
            "`navigator.credentials.create({publicKey:{...attestation:'none'...}})` "
            "OR server-side `attestationType: 'none'` / "
            "`allowedAttestationFormats: ['none']` / "
            "`generate_registration_options(..., attestation='none')`. "
            "`'none'` instructs the authenticator NOT to prove its "
            "hardware origin — a malicious extension can present a "
            "software key indistinguishable from a YubiKey. For "
            "high-value flows the server MUST require `'direct'` and "
            "validate the attestation cert chain against the vendor "
            "CA (Yubico, Feitian) and the FIDO Metadata Service."
        ),
        pattern=_WEBAUTHN_ATTESTATION_NONE_RE,
        owasp_asi="ASI-07",
    ),
)


# Validate at module load: every Rule must use a compiled re.Pattern.
def _validate_rules(rules: tuple[Rule, ...]) -> None:
    for r in rules:
        if not isinstance(r.pattern, re.Pattern):
            msg = f"Rule {r.id} has non-compiled pattern"
            raise TypeError(msg)


_validate_rules(RULES)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of the 1-based line_no without trailing newline."""
    lines = text.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _following_lines(text: str, line_no: int, window: int = 12) -> str:
    """Return concatenation of the next `window` lines after line_no
    (inclusive of line_no). Used for Rule 12 — persistence sink that
    follows a TOTP-secret assignment within a small window."""
    lines = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(lines), line_no - 1 + window + 1)
    return "\n".join(lines[start:end])


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


def _filename_matches_any(
    filename: str,
    hints: tuple[re.Pattern, ...],
) -> bool:
    """True if filename matches any of the hint patterns. Empty filename
    returns False (no match) — used by the softhsm2 test-fixture
    carve-out so the caller can opt out by leaving filename blank."""
    if not filename:
        return False
    return any(h.search(filename) is not None for h in hints)


def scan_text(text: str, *, filename: str = "") -> list[Finding]:
    """Run every RULE against `text` and return findings.

    The scanner is composed of:

    * One linear pass over RULES that fires every regex.
    * Per-rule Stage-B filters that consult file-level guards, the
      surrounding text window, or filename hints. Filters mirror the
      shape used in auth_flow_patterns / crypto_misuse_patterns.
    * A separate Stage-A pass for Rule 10's KeyGenParameterSpec
      builder trigger that fires only when NO auth-binding call is
      anywhere in the file.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    # One-shot file-level guards.
    keychain_device_only_set = _file_contains_any(
        text, _KEYCHAIN_DEVICE_ONLY_GUARDS,
    )
    secure_enclave_set = _file_contains_any(
        text, _SECURE_ENCLAVE_FILE_GUARDS,
    )
    android_keystore_auth_set = _file_contains_any(
        text, _ANDROID_KEYSTORE_AUTH_GUARDS,
    )
    totp_replay_guard_set = (
        _TOTP_REPLAY_GUARD_RE.search(text) is not None
    )
    totp_encryption_set = _file_contains_any(
        text, _TOTP_ENCRYPT_GUARDS,
    )

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _add(rule: Rule, m: re.Match, line: int, col: int) -> None:
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        matched = m.group(0)
        if len(matched) > 200:
            matched = matched[:200] + "…"
        findings.append(Finding(
            rule_id=rule.id,
            line=line,
            column=col,
            matched_text=matched,
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())

            # Per-rule Stage-B filters.
            if rule.id == "hsm.macos-keychain-missing-this-device-only":
                if keychain_device_only_set:
                    continue
            elif rule.id == "hsm.softhsm2-in-production-path":
                if _filename_matches_any(filename, _SOFTHSM2_TEST_FILENAME_HINTS):
                    continue
                # Same-line / preceding-3-lines test-context marker.
                ln_text = _line_text(text, line)
                if _SOFTHSM2_TEST_CONTEXT_RE.search(ln_text) is not None:
                    continue
                # Look back 3 lines for the same marker.
                lines = text.split("\n")
                start = max(0, line - 1 - 3)
                ctx = "\n".join(lines[start:line])
                if _SOFTHSM2_TEST_CONTEXT_RE.search(ctx) is not None:
                    continue
            elif rule.id == "hsm.hardware-rng-software-fallback":
                # If the matched block already contains a log call OR
                # raises a strict-mode exception, suppress — the
                # developer DID document the fallback.
                if _HARDWARE_RNG_STRICT_CONTEXT_RE.search(m.group(0)) is not None:
                    continue
            elif rule.id == "hsm.secure-enclave-tokenid-missing":
                if secure_enclave_set:
                    continue
            elif rule.id == "hsm.android-keystore-user-auth-required-false":
                # Direct `.setUserAuthenticationRequired(false)` —
                # always flag, no file-level escape (calling it with
                # `false` IS the bug regardless of other guards).
                pass
            elif rule.id == "hsm.totp-no-single-use-replay-tracking":
                if totp_replay_guard_set:
                    continue
            elif rule.id == "hsm.totp-secret-stored-plaintext-at-rest":
                if totp_encryption_set:
                    continue
                # Persistence sink must appear within 12 lines AFTER
                # the assign trigger. If no sink, the secret is in
                # memory only — out of scope for this rule.
                window_text = _following_lines(text, line, window=12)
                if _TOTP_PERSIST_SINK_RE.search(window_text) is None:
                    continue

            _add(rule, m, line, col)

    # Rule 10 second pass — Builder() chains that have NO auth-binding
    # call ANYWHERE in the file. Only fires when the direct
    # `.setUserAuthenticationRequired(false)` form did NOT already fire
    # on the same chain.
    if not android_keystore_auth_set:
        rule_10 = next(
            (r for r in RULES
             if r.id == "hsm.android-keystore-user-auth-required-false"),
            None,
        )
        if rule_10 is not None:
            for m in _KEYGEN_PARAM_BUILDER_TRIGGER_RE.finditer(text):
                line, col = _line_col(text, m.start())
                _add(rule_10, m, line, col)

    # Rule 2 second pass — DPAPI ProtectedData via PowerShell with
    # cross-line variable indirection. The primary regex requires the
    # interpolation marker AND the `ProtectedData` payload to live in
    # the same span; real-world code often assigns the command string
    # to a variable on one line and spawns it on a separate line.
    # We detect that two-step shape with a file-level correlation.
    rule_2 = next(
        (r for r in RULES
         if r.id == "hsm.windows-dpapi-via-powershell-arg-interpolation"),
        None,
    )
    if rule_2 is not None:
        has_interpolated_dpapi = (
            _DPAPI_INTERPOLATED_PAYLOAD_RE.search(text) is not None
        )
        has_powershell_spawn = (
            _POWERSHELL_SPAWN_RE.search(text) is not None
        )
        if has_interpolated_dpapi and has_powershell_spawn:
            # Anchor the finding at the interpolated-DPAPI assignment.
            dpapi_m = _DPAPI_INTERPOLATED_PAYLOAD_RE.search(text)
            if dpapi_m is not None:
                line, col = _line_col(text, dpapi_m.start())
                _add(rule_2, dpapi_m, line, col)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
