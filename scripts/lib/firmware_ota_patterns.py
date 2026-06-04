"""Firmware / OTA update / secure-boot regex pattern library.

Wave-23 distillation round 9, angle "firmware-ota-update".

Catalogue of 5 firmware-update / secure-boot anti-patterns distilled in
`reports/distill-round-9/firmware-ota-update.md`. Targets ESP-IDF /
Zephyr / U-Boot / MCUboot / NXP / STM32 vendor SDK code paths where
the firmware-update / signed-image / anti-rollback / debug-surface
trust chain is broken.

What is NOT here (already covered by other modules — DO NOT duplicate):

  * Generic TLS / RSA / curve primitives — `crypto_misuse_patterns.py`.
  * HMAC over JSON webhooks — `webhook_signature_patterns.py`.
  * Generic hardcoded secrets in source — caught by other lifecycle
    rules; here the focus is the firmware-specific KEY SHAPES that
    other rules miss (PEM blob inlined as C string, fuse-seed
    static-array form, `espsecure` / `imgtool` / `west sign`
    invocations with in-tree key paths).
  * HSM / PKCS#11 token sessions — `hardware_token_hsm` module.
  * CDN / npm / pip pinning — `cdn_supply_chain_patterns.py`.

What IS here (5 net-new rules, regex-only, all RE2-safe):

  * firmware-ota-manifest-verify-skipped                       (CRITICAL)
  * firmware-ota-anti-rollback-not-enforced                    (HIGH)
  * firmware-ota-secure-boot-key-in-source                     (CRITICAL)
  * firmware-ota-recovery-debug-surface-in-prod                (HIGH)
  * firmware-ota-mkimage-imgtool-weak-hash-or-no-version       (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (secure-boot signing key inlined in source)
  ASI-04 — Information leak / Insecure-defaults (debug surface left on)
  ASI-07 — Authority / authorisation gaps (manifest signature skipped,
                                            anti-rollback not enforced,
                                            weak-hash / no-version
                                            packaging flags)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.

Stage-B filters (computed in scan_text) replace the lookarounds the
report's prose-form regexes used — RE2 cannot express those — and keep
the published regexes auditable.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns / chat_bot_patterns.
    RE2-safe: no nested quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- F1 : firmware-ota-manifest-verify-skipped --------------------------


# Variant A — C/C++ preprocessor guard macro that DISABLES verification
# in a non-debug-named build. The macro names follow the OTA / FIRMWARE /
# UPDATE prefix used by ESP-IDF / Zephyr / vendor SDKs.
_FOTA_VERIFY_GUARD_MACRO = _re(
    r"^\s*#\s*ifn?def\s+(?:CONFIG_)?(?:OTA|FIRMWARE|UPDATE|BOOT)_"
    r"(?:SKIP|DISABLE|NO|BYPASS)_(?:VERIFY|SIGNATURE|SIGN_CHECK)\b"
)

# Variant B — verify_signature(...) called as a STATEMENT (trailing `;`)
# with the return value silently discarded. RE2-safe: no lookbehind, so
# we ANCHOR on a beginning-of-statement marker (`;`, `{`, `}`, start of
# line) before the function name. The discarded-return shape is
# `name(...);` at statement position, not assigned or used in a condition.
_FOTA_VERIFY_DISCARDED_RETURN = _re(
    r"(?:^|[;{}])\s*"
    r"(?:verify_signature|esp_secure_boot_verify_signature"
    r"|esp_secure_boot_verify_rsa_signature_block"
    r"|esp_secure_boot_verify_ecdsa_signature_block"
    r"|zephyr_sign_verify|mcuboot_verify_signature|bootutil_img_validate)"
    r"\s*\([^;{}]{0,400}\)\s*;"
)

# Variant C — Python-side debug-bypass flag controlling verification.
_FOTA_VERIFY_PY_DEBUG_BYPASS = _re(
    r"^\s*if\s+(?:DEBUG|DEV|TEST|SKIP|UNSAFE)_?"
    r"(?:NO_VERIFY|SKIP_VERIFY|UNSIGNED|UNSAFE_OTA|NO_SIG_CHECK)\b"
)


# ---- F2 : firmware-ota-anti-rollback-not-enforced -----------------------


# Anchor A — the activate / set-pending call that flips the device to
# the new slot. After matching we look forward in scan_text for a
# rollback / secure_version / min_version check.
_FOTA_ACTIVATE_PARTITION_CALL = _re(
    r"\b(?:esp_ota_set_boot_partition|esp_ota_mark_app_valid_cancel_rollback"
    r"|boot_set_pending|boot_set_confirmed"
    r"|mcuboot_swap_type|mcuboot_set_pending"
    r"|flash_area_write|fih_uint_decode)"
    r"\s*\([^)]{0,400}\)"
)

# Marker — rollback / secure-version / min-version language in the
# vicinity of the activate call. Presence in the Stage-B window
# SUPPRESSES the F2 finding.
_FOTA_ROLLBACK_GUARD_MARKER = _re(
    r"\b(?:rollback|anti.?rollback|secure_version|min_version|monotonic_version"
    r"|esp_efuse_read_secure_version|esp_efuse_check_secure_version"
    r"|image_version_cmp|img_version_cmp)\b"
)

# Anchor B — secure-version read without subsequent comparison. The
# Stage-B logic checks the forward window for a comparison / branch.
_FOTA_SECURE_VERSION_READ = _re(
    r"\b(?:esp_efuse_read_secure_version|esp_efuse_read_field_blob"
    r"|boot_read_anti_rollback_counter|boot_nv_security_counter_get)"
    r"\s*\([^)]{0,200}\)\s*;"
)

# Marker — branch / comparison / abort in the post-read window.
_FOTA_COMPARE_OR_BRANCH_MARKER = _re(
    r"\b(?:if|else|return|abort|reject|<=?|>=?|==|!=)\b"
)

# FP-suppression — calls that legitimately downgrade (factory reset,
# RMA, recovery). If the surrounding context names one of these, the
# rule does NOT fire.
_FOTA_DOWNGRADE_LEGIT_CONTEXT = _re(
    r"\b(?:factory_reset|recovery_image|rma_|rma_unlock|return_to_factory"
    r"|emergency_downgrade|forced_downgrade_authorized)\b"
)


# ---- F3 : firmware-ota-secure-boot-key-in-source ------------------------


# Variant A — PEM private-key blob inlined in a C/C++ string literal.
# We accept both `BEGIN PRIVATE KEY` and the algo-tagged forms
# (`BEGIN EC PRIVATE KEY`, `BEGIN RSA PRIVATE KEY`).
_FOTA_PEM_PRIVATE_KEY_IN_C_STRING = _re(
    r'"-----BEGIN\s+(?:EC\s+|RSA\s+|DSA\s+|OPENSSH\s+)?PRIVATE\s+KEY-----'
)

# Variant B — fuse-seed / root-key / secure-boot-key as a static const
# byte array with a crypto-sized length (32 / 48 / 64 / 128 / 256).
_FOTA_FUSE_SEED_C_ARRAY = _re(
    r"\bstatic\s+const\s+u?int8?_t\s+"
    r"(?:fuse_seed|root_key|secure_boot_key|aes_key|hmac_key|ecdsa_priv"
    r"|signing_key|ota_key|boot_priv_key|kdf_seed)\b"
    r"\s*\[\s*(?:32|48|64|128|256)\s*\]\s*="
)

# Variant C — espsecure / imgtool / mcumgr / west sign invoked with a
# signing key path INSIDE the source tree. RE2-safe: bounded `[\s\S]`
# (lazy) permits shell backslash-newline continuation between the
# tool name and its `--keyfile` flag — the canonical multi-line
# build-script shape.
_FOTA_TOOL_INTREE_KEY_PATH = _re(
    r"\b(?:espsecure(?:\.py)?|imgtool|mcumgr|west\s+sign)\b"
    r"[\s\S]{0,300}?"
    r"--?(?:key|keyfile|key-file)[= ]+"
    r"(?:\./|\.?/?keys/|/repo/|/src/|src/|keys/)"
)

# FP-suppression — keys living explicitly under examples / samples /
# tests / fixtures paths, or accompanied by an EXAMPLE-ONLY / TEST-KEY
# comment within 3 lines (consumed in scan_text).
_FOTA_EXAMPLE_KEY_COMMENT = _re(
    r"(?:EXAMPLE\s+ONLY|TEST\s+KEY|SAMPLE\s+KEY|DO\s+NOT\s+USE\s+IN\s+PRODUCTION)"
)
_FOTA_EXAMPLE_PATH_MARKER = _re(
    r"(?:^|[\s/'\"])"
    r"(?:examples?|samples?|tests?|fixtures?|testdata)/"
)


# ---- F4 : firmware-ota-recovery-debug-surface-in-prod -------------------


# Variant A — sdkconfig sets CONFIG_SECURE_DISABLE_JTAG to 0 / n /
# "is not set" form Kconfig emits when a symbol is commented out.
_FOTA_JTAG_NOT_DISABLED = _re(
    r"^\s*#?\s*CONFIG_SECURE_DISABLE_JTAG\s*=?\s*"
    r"(?:0|n|is\s+not\s+set)\b"
)

# Variant B — Zephyr/ESP-IDF UART shell enabled in build.
_FOTA_SHELL_ENABLED = _re(
    r"^\s*CONFIG_SHELL\s*=\s*y\b"
)

# Variant C — debug optimisations (-O0) enabled in build.
_FOTA_DEBUG_OPTIMIZATIONS = _re(
    r"^\s*CONFIG_DEBUG_OPTIMIZATIONS\s*=\s*y\b"
)

# Variant D — recovery / debug / raw-flash HTTP route registered.
# RE2-safe: bounded `[\s\S]` permits the route URI to live on a
# subsequent line inside a struct/dict literal (`httpd_uri_t{ .uri
# = "/recovery/flash" }` is the canonical ESP-IDF shape and spans
# multiple lines).
_FOTA_RECOVERY_HTTP_ROUTE = _re(
    r"\b(?:httpd_register_uri_handler|esp_http_server|http\.HandleFunc"
    r"|server\.route|app\.(?:get|post|put|delete))"
    r"\s*\("
    r"[\s\S]{0,300}?"
    r"[\"'/]"
    r"(?:recovery|debug|test|jtag|dev|raw_flash|raw_write|backdoor)\b"
)


# ---- F5 : firmware-ota-mkimage-imgtool-weak-hash-or-no-version ----------


# Variant A — mkimage with --hash-algo md5 / sha1 / crc32.
_FOTA_MKIMAGE_WEAK_HASH = _re(
    r"\bmkimage\b[^\n]{0,400}"
    r"--hash-algo[= ]+"
    r"(?:md5|sha1|crc32)\b"
)

# Variant B — imgtool sign invocation. Stage-B checks the same line for
# the presence of --version / --security-counter; absence = missing
# version pin.
_FOTA_IMGTOOL_SIGN_LINE = _re(
    r"^[^#\n]*\bimgtool\b[^\n]{0,500}\bsign\b"
)
_FOTA_VERSION_OR_COUNTER_FLAG = _re(
    r"--(?:version|security-counter)\b"
)

# Variant C — explicit version-disable flag.
_FOTA_EXPLICIT_NO_VERSION_FLAG = _re(
    r"\b(?:imgtool|west\s+sign|mcumgr|espsecure(?:\.py)?)\b"
    r"[^\n]{0,200}"
    r"--(?:no-version|skip-version|allow-downgrade|no-security-counter)\b"
)

# FP-suppression — legacy-checksum allow-inline comment within 2 lines
# of the mkimage hit.
_FOTA_LEGACY_CHECKSUM_ALLOWED = _re(
    r"mkimage-hash-allowed:\s*legacy-checksum"
)


# ---- Rule registry ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="firmware-ota-manifest-verify-skipped",
        name="OTA manifest signature verification skipped or return value discarded",
        severity="CRITICAL",
        description=(
            "Firmware update path checks the manifest signature only "
            "when a build-time DEBUG/DEV flag is FALSE, or invokes "
            "`verify_signature(...)` (or its ESP-IDF / Zephyr / MCUboot "
            "equivalent) as a statement with the return value silently "
            "discarded. A production build that ships with "
            "`CONFIG_OTA_SKIP_VERIFY` set, or whose verifier's return "
            "code is ignored, accepts any attacker-supplied image. "
            "Single-line bypass yields full RCE on every device that "
            "boots the malicious image; recovery requires hardware "
            "return."
        ),
        pattern=_FOTA_VERIFY_GUARD_MACRO,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="firmware-ota-anti-rollback-not-enforced",
        name="A/B partition activation without anti-rollback counter check",
        severity="HIGH",
        description=(
            "Device supports A/B (or boot0/boot1) partition layouts "
            "but the firmware-update logic does NOT compare the "
            "candidate image's monotonic version against the on-fuse / "
            "on-NV anti-rollback counter before activation. Attackers "
            "re-flash a previously-shipped, signed-but-vulnerable image "
            "(carrying a known CVE) and the signature alone passes "
            "validation. Re-introduces every patched CVE on every "
            "fielded device. Signature verification alone does not "
            "catch this — the missing piece is the version-counter "
            "comparison surrounding `esp_ota_set_boot_partition` / "
            "`boot_set_pending` / `mcuboot_swap_type`."
        ),
        pattern=_FOTA_ACTIVATE_PARTITION_CALL,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="firmware-ota-secure-boot-key-in-source",
        name="Secure-boot signing key, fuse seed, or root key committed to source",
        severity="CRITICAL",
        description=(
            "The private signing key, the fuse-burn seed for secure-"
            "boot v1, or the per-device root key is committed verbatim "
            "into the firmware source tree (as a PEM blob inlined into "
            "a C string, as a `static const uint8_t fuse_seed[32] = "
            "{...}` array, or referenced by an `espsecure.py` / "
            "`imgtool` / `west sign` invocation whose `--keyfile` path "
            "points inside the repo). Anyone with read access to the "
            "repo can sign arbitrary firmware that the device accepts "
            "as authentic. Key compromise voids the entire secure-boot "
            "trust chain across the entire device family — distinct "
            "from generic hardcoded-secret rules which key on string "
            "shape, not on the firmware-specific build-system context."
        ),
        pattern=_FOTA_PEM_PRIVATE_KEY_IN_C_STRING,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="firmware-ota-recovery-debug-surface-in-prod",
        name="JTAG / UART shell / recovery HTTP endpoint left on in production image",
        severity="HIGH",
        description=(
            "Production firmware image leaves debug surfaces enabled: "
            "JTAG/SWD pads un-fused (`CONFIG_SECURE_DISABLE_JTAG=0`), "
            "a Zephyr UART shell active (`CONFIG_SHELL=y`), debug "
            "optimisations (`CONFIG_DEBUG_OPTIMIZATIONS=y`), or a "
            "`/recovery/flash` (or `/debug`, `/raw_write`) HTTP route "
            "registered unconditionally. These give a local attacker "
            "shell or arbitrary-flash-write access that bypasses every "
            "signature check the OTA path enforces. Exploitation "
            "requires physical access (JTAG/UART) or network reach "
            "(HTTP recovery)."
        ),
        pattern=_FOTA_JTAG_NOT_DISABLED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="firmware-ota-mkimage-imgtool-weak-hash-or-no-version",
        name="mkimage / imgtool / west sign uses weak hash or omits version pin",
        severity="HIGH",
        description=(
            "Build script calls a canonical firmware-packaging tool "
            "(`mkimage`, `imgtool sign`, `west sign`, `mcumgr`) with a "
            "weak hash (`md5`, `sha1`, `crc32`) where the bootloader is "
            "configured for SHA-256, or omits the `--version` / "
            "`--security-counter` flags the bootloader cross-checks, or "
            "explicitly passes `--no-version` / `--allow-downgrade`. "
            "Each path produces an image that signs cleanly but fails "
            "the bootloader's anti-downgrade check silently or trivially "
            "downgrades. Combines integrity weakness (md5/sha1 are "
            "signable but collidable for chosen-prefix attacks) with "
            "downgrade enablement (variant of "
            "firmware-ota-anti-rollback-not-enforced operating at the "
            "build layer instead of the bootloader layer)."
        ),
        pattern=_FOTA_MKIMAGE_WEAK_HASH,
        owasp_asi="ASI-07",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _line_text(text: str, line_no: int) -> str:
    """Return the single line at `line_no` (1-based) or empty string."""
    parts = text.split("\n")
    if 1 <= line_no <= len(parts):
        return parts[line_no - 1]
    return ""


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters compose adjacent-line context to replace the
    lookarounds the prose-form regexes used (RE2-safe):

      * F1 — emit on any of three independent anchors:
        - guard-macro at TU top (`#ifndef CONFIG_OTA_SKIP_VERIFY`),
        - `verify_signature(...);` statement with discarded return
          (NOT inside an `if (...)` / assignment),
        - Python `if DEBUG_NO_VERIFY:` guard.
      * F2 — anchor on `esp_ota_set_boot_partition` (or equivalent)
        and require NO `rollback` / `secure_version` / `min_version`
        / `image_version_cmp` token within a 300-character forward
        window AND NO `factory_reset` / `recovery_image` / `rma_`
        in the same window. Also fire on a secure-version READ that
        has no follow-up comparison branch within ~6 lines.
      * F3 — three independent anchors (PEM in C string, fuse-seed
        static array, in-tree --keyfile). Suppress when the same
        file lives under `examples/`, `samples/`, `tests/`, or
        `fixtures/` (path marker IN the text — most build scripts
        carry the path as a literal), OR when an EXAMPLE-ONLY /
        TEST-KEY comment sits within 3 lines.
      * F4 — four independent anchors (JTAG-not-disabled,
        CONFIG_SHELL=y, CONFIG_DEBUG_OPTIMIZATIONS=y, recovery HTTP
        route). All-fire; the rule emits once per anchor hit.
      * F5 — three anchors: weak `--hash-algo` arg to mkimage,
        `imgtool sign` line WITHOUT `--version` / `--security-counter`,
        explicit `--no-version` flag. Suppress F5 weak-hash hits when
        the line-or-window contains the `mkimage-hash-allowed:
        legacy-checksum` opt-out comment.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- F1 : firmware-ota-manifest-verify-skipped ----
    rule_f1 = rule_by_id["firmware-ota-manifest-verify-skipped"]
    # Anchor A — guard macro at preprocessor scope.
    for m in _FOTA_VERIFY_GUARD_MACRO.finditer(text):
        _emit(rule_f1, m.start(), m.group(0))
    # Anchor B — discarded-return statement.
    for m in _FOTA_VERIFY_DISCARDED_RETURN.finditer(text):
        # The match includes the leading anchor char (`;`, `{`, `}`,
        # or `\n`); shift offset/snippet so the user sees the call
        # itself, not the leading punctuation.
        raw = m.group(0)
        lead_off = 0
        for i, ch in enumerate(raw):
            if ch.isalpha() or ch == "_":
                lead_off = i
                break
        _emit(rule_f1, m.start() + lead_off, raw[lead_off:])
    # Anchor C — Python debug-bypass.
    for m in _FOTA_VERIFY_PY_DEBUG_BYPASS.finditer(text):
        _emit(rule_f1, m.start(), m.group(0))

    # ---- F2 : firmware-ota-anti-rollback-not-enforced ----
    rule_f2 = rule_by_id["firmware-ota-anti-rollback-not-enforced"]
    # Anchor A — activate-partition call. Suppress if rollback guard
    # marker is in the surrounding window OR a legitimate-downgrade
    # context name surrounds the call.
    for m in _FOTA_ACTIVATE_PARTITION_CALL.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 10, 10)
        if _FOTA_ROLLBACK_GUARD_MARKER.search(window) is not None:
            continue
        if _FOTA_DOWNGRADE_LEGIT_CONTEXT.search(window) is not None:
            continue
        _emit(rule_f2, m.start(), m.group(0))
    # Anchor B — secure-version READ with no follow-up compare/branch.
    for m in _FOTA_SECURE_VERSION_READ.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_forward(text, line + 1, 6)
        if _FOTA_COMPARE_OR_BRANCH_MARKER.search(window) is None:
            _emit(rule_f2, m.start(), m.group(0))

    # ---- F3 : firmware-ota-secure-boot-key-in-source ----
    rule_f3 = rule_by_id["firmware-ota-secure-boot-key-in-source"]
    # Path-level FP-suppression: if the text itself contains an
    # `examples/` / `samples/` / `tests/` / `fixtures/` marker (the
    # case where the source under scan carries its own pathname in a
    # comment / docstring), skip ALL F3 anchors. The scanner config
    # is expected to do file-path suppression separately; this is an
    # extra in-content guard so prose-form examples in docstrings
    # don't fire.
    skip_f3_pathwide = _file_contains(text, _FOTA_EXAMPLE_PATH_MARKER)
    if not skip_f3_pathwide:
        for m in _FOTA_PEM_PRIVATE_KEY_IN_C_STRING.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 3, 3)
            if _FOTA_EXAMPLE_KEY_COMMENT.search(window) is not None:
                continue
            _emit(rule_f3, m.start(), m.group(0))
        for m in _FOTA_FUSE_SEED_C_ARRAY.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 3, 3)
            if _FOTA_EXAMPLE_KEY_COMMENT.search(window) is not None:
                continue
            _emit(rule_f3, m.start(), m.group(0))
        for m in _FOTA_TOOL_INTREE_KEY_PATH.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 3, 3)
            if _FOTA_EXAMPLE_KEY_COMMENT.search(window) is not None:
                continue
            _emit(rule_f3, m.start(), m.group(0))

    # ---- F4 : firmware-ota-recovery-debug-surface-in-prod ----
    rule_f4 = rule_by_id["firmware-ota-recovery-debug-surface-in-prod"]
    for m in _FOTA_JTAG_NOT_DISABLED.finditer(text):
        _emit(rule_f4, m.start(), m.group(0))
    for m in _FOTA_SHELL_ENABLED.finditer(text):
        _emit(rule_f4, m.start(), m.group(0))
    for m in _FOTA_DEBUG_OPTIMIZATIONS.finditer(text):
        _emit(rule_f4, m.start(), m.group(0))
    for m in _FOTA_RECOVERY_HTTP_ROUTE.finditer(text):
        _emit(rule_f4, m.start(), m.group(0))

    # ---- F5 : firmware-ota-mkimage-imgtool-weak-hash-or-no-version ----
    rule_f5 = rule_by_id["firmware-ota-mkimage-imgtool-weak-hash-or-no-version"]
    # Anchor A — mkimage --hash-algo md5/sha1/crc32. Suppress when the
    # legacy-checksum opt-out comment is within 2 lines.
    for m in _FOTA_MKIMAGE_WEAK_HASH.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 2, 2)
        if _FOTA_LEGACY_CHECKSUM_ALLOWED.search(window) is not None:
            continue
        _emit(rule_f5, m.start(), m.group(0))
    # Anchor B — imgtool sign line missing --version / --security-counter.
    for m in _FOTA_IMGTOOL_SIGN_LINE.finditer(text):
        line, _ = _line_col(text, m.start())
        # Check the FULL logical line (single matched line is enough
        # for imgtool sign — multi-line backslash-continuation is rare
        # but supported by widening the window to the next line if
        # the matched line ends with `\`).
        line_str = _line_text(text, line)
        if line_str.rstrip().endswith("\\"):
            # Multi-line shell command — widen.
            line_str = _slice_forward(text, line, 5)
        if _FOTA_VERSION_OR_COUNTER_FLAG.search(line_str) is not None:
            continue
        _emit(rule_f5, m.start(), m.group(0))
    # Anchor C — explicit --no-version / --skip-version / --allow-downgrade.
    for m in _FOTA_EXPLICIT_NO_VERSION_FLAG.finditer(text):
        _emit(rule_f5, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
