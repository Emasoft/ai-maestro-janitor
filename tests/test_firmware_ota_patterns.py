"""Tests for scripts/lib/firmware_ota_patterns.py.

Pattern-coverage tests for the Wave-23 distill-round-9 firmware /
OTA-update / secure-boot catalogue (5 anti-patterns covering ESP-IDF,
Zephyr, MCUboot, U-Boot, NXP/STM32 vendor SDKs). Each rule has at
least one positive test exercising a canary AND at least one negative
test exercising the carve-out or context filter (2 tests per rule
minimum, per the wave-23 implementation contract).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import firmware_ota_patterns as fop  # type: ignore[import-not-found]  # noqa: E402

# ---------- Synthetic secret-shaped fixtures -----------------------------
# PEM markers are split so no contiguous BEGIN/END PRIVATE KEY token exists
# at rest in this file. Runtime values are byte-identical to a real PEM.
_PEM_BEGIN_PK = "-----BEGIN " + "PRIVATE KEY-----"
_PEM_END_PK = "-----END " + "PRIVATE KEY-----"

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 5 documented rule IDs."""
    assert isinstance(fop.RULES, tuple)
    rule_ids = {r.id for r in fop.RULES}
    expected = {
        "firmware-ota-manifest-verify-skipped",
        "firmware-ota-anti-rollback-not-enforced",
        "firmware-ota-secure-boot-key-in-source",
        "firmware-ota-recovery-debug-surface-in-prod",
        "firmware-ota-mkimage-imgtool-weak-hash-or-no-version",
    }
    assert expected == rule_ids
    assert len(fop.RULES) == 5


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in fop.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = fop.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="CRITICAL", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "CRITICAL"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert fop.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — JTAG-not-disabled (F4)
        "CONFIG_SECURE_DISABLE_JTAG=0\n"
        # Line 2 — CONFIG_SHELL=y (F4)
        "CONFIG_SHELL=y\n"
    )
    findings = fop.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[fop.Finding]:
    return [f for f in fop.scan_text(text) if f.rule_id == rule_id]


# ---------- F1 : firmware-ota-manifest-verify-skipped --------------------


def test_f1_guard_macro_skip_verify_flags() -> None:
    """`#ifndef CONFIG_OTA_SKIP_VERIFY` guard → CRITICAL hit."""
    src = (
        "int apply_ota_update(const ota_manifest_t *m, const uint8_t *image) {\n"
        "#ifndef CONFIG_OTA_SKIP_VERIFY\n"
        "    verify_signature(m->sig, image, m->len);\n"
        "#endif\n"
        "    flash_write_partition(PART_OTA_1, image, m->len);\n"
        "    return 0;\n"
        "}\n"
    )
    hits = _hits("firmware-ota-manifest-verify-skipped", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_f1_discarded_return_verify_signature_flags() -> None:
    """`verify_signature(...);` with return value discarded → hit."""
    src = (
        "void apply(uint8_t *img, size_t n) {\n"
        "    verify_signature(sig_buf, img, n);\n"
        "    flash_write_partition(PART_OTA_1, img, n);\n"
        "}\n"
    )
    hits = _hits("firmware-ota-manifest-verify-skipped", src)
    assert hits


def test_f1_python_debug_no_verify_flags() -> None:
    """Python `if DEBUG_NO_VERIFY:` debug bypass → hit."""
    src = (
        "def apply(manifest, blob):\n"
        "    if DEBUG_NO_VERIFY:\n"
        "        return flash(blob)\n"
        "    sig_ok = verify_ed25519(manifest['sig'], blob)\n"
        "    return flash(blob) if sig_ok else None\n"
    )
    hits = _hits("firmware-ota-manifest-verify-skipped", src)
    assert hits


def test_f1_verify_signature_used_in_if_condition_not_flagged() -> None:
    """`if (!verify_signature(...))` → no hit (return value IS checked)."""
    src = (
        "int apply(const uint8_t *img, size_t n) {\n"
        "    if (!verify_signature(sig_buf, img, n)) return -EBADMSG;\n"
        "    flash_write_partition(PART_OTA_1, img, n);\n"
        "    return 0;\n"
        "}\n"
    )
    assert not _hits("firmware-ota-manifest-verify-skipped", src)


def test_f1_verify_signature_assigned_to_var_not_flagged() -> None:
    """`int rc = verify_signature(...);` → no hit (return captured)."""
    src = (
        "int apply(const uint8_t *img, size_t n) {\n"
        "    int rc = verify_signature(sig_buf, img, n);\n"
        "    if (rc != 0) return rc;\n"
        "    flash_write_partition(PART_OTA_1, img, n);\n"
        "    return 0;\n"
        "}\n"
    )
    assert not _hits("firmware-ota-manifest-verify-skipped", src)


# ---------- F2 : firmware-ota-anti-rollback-not-enforced -----------------


def test_f2_activate_partition_without_rollback_check_flags() -> None:
    """`esp_ota_set_boot_partition` with no rollback marker → HIGH hit."""
    src = (
        "int activate_partition(int slot) {\n"
        "    const ota_header_t *hdr = read_header(slot);\n"
        "    if (!verify_signature(hdr->sig, hdr->body, hdr->len)) return -1;\n"
        "    esp_ota_set_boot_partition(partition_for_slot(slot));\n"
        "    return 0;\n"
        "}\n"
    )
    hits = _hits("firmware-ota-anti-rollback-not-enforced", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_f2_secure_version_read_without_compare_flags() -> None:
    """`esp_efuse_read_secure_version` followed by no compare → hit."""
    src = (
        "void activate(int slot) {\n"
        "    uint32_t current = esp_efuse_read_secure_version();\n"
        "    do_unrelated_thing();\n"
        "    esp_ota_set_boot_partition(slot);\n"
        "}\n"
    )
    hits = _hits("firmware-ota-anti-rollback-not-enforced", src)
    # The secure-version-read anchor must fire (no compare/branch
    # within 6 lines of the read).
    assert any("secure_version" in h.matched_text for h in hits)


def test_f2_activate_with_rollback_marker_suppressed() -> None:
    """Same activate call WITH rollback comparison nearby → no F2 hit."""
    src = (
        "int activate_partition(int slot) {\n"
        "    uint32_t current = esp_efuse_read_secure_version();\n"
        "    const ota_header_t *hdr = read_header(slot);\n"
        "    if (hdr->version < current) return -EROLLBACK;\n"
        "    esp_ota_set_boot_partition(slot);\n"
        "    return 0;\n"
        "}\n"
    )
    assert not _hits("firmware-ota-anti-rollback-not-enforced", src)


def test_f2_factory_reset_context_suppressed() -> None:
    """Activate call inside `factory_reset` context → no F2 hit (legit downgrade)."""
    src = (
        "int factory_reset(void) {\n"
        "    /* RMA / return-to-factory path. */\n"
        "    esp_ota_set_boot_partition(PART_FACTORY);\n"
        "    return 0;\n"
        "}\n"
    )
    assert not _hits("firmware-ota-anti-rollback-not-enforced", src)


# ---------- F3 : firmware-ota-secure-boot-key-in-source ------------------


def test_f3_pem_private_key_in_c_string_flags() -> None:
    """PEM PRIVATE KEY block inlined in a C string literal → CRITICAL."""
    src = (
        'static const char SECURE_BOOT_SIGNING_KEY[] =\n'
        f'"{_PEM_BEGIN_PK}\\n"\n'
        '"MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDX...\\n"\n'
        f'"{_PEM_END_PK}\\n";\n'
    )
    hits = _hits("firmware-ota-secure-boot-key-in-source", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_f3_fuse_seed_static_array_flags() -> None:
    """`static const uint8_t fuse_seed[32] = {...}` → hit."""
    src = (
        "static const uint8_t fuse_seed[32] = {\n"
        "    0xDE, 0xAD, 0xBE, 0xEF, 0xCA, 0xFE, 0xBA, 0xBE,\n"
        "    0x01, 0x23, 0x45, 0x67, 0x89, 0xAB, 0xCD, 0xEF,\n"
        "    0x10, 0x32, 0x54, 0x76, 0x98, 0xBA, 0xDC, 0xFE,\n"
        "    0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88,\n"
        "};\n"
    )
    hits = _hits("firmware-ota-secure-boot-key-in-source", src)
    assert hits


def test_f3_espsecure_intree_key_path_flags() -> None:
    """`espsecure.py sign_data --keyfile ./keys/...` → hit."""
    src = (
        "#!/bin/bash\n"
        "espsecure.py sign_data \\\n"
        "  --keyfile ./keys/secure_boot_signing_key.pem \\\n"
        "  --output build/app-signed.bin build/app.bin\n"
    )
    hits = _hits("firmware-ota-secure-boot-key-in-source", src)
    assert hits


def test_f3_example_only_comment_suppresses_pem() -> None:
    """`EXAMPLE ONLY` comment within 3 lines of PEM → suppressed."""
    src = (
        "/* EXAMPLE ONLY — do not use in production builds. */\n"
        'static const char DEMO_KEY[] =\n'
        f'"{_PEM_BEGIN_PK}\\n"\n'
        '"MIIE...\\n"\n'
        f'"{_PEM_END_PK}\\n";\n'
    )
    assert not _hits("firmware-ota-secure-boot-key-in-source", src)


def test_f3_unrelated_pem_certificate_not_flagged() -> None:
    """PUBLIC certificate (not private key) → no hit."""
    src = (
        'static const char ROOT_CA[] =\n'
        '"-----BEGIN CERTIFICATE-----\\n"\n'
        '"MIIDdzCCAl+gAwIBAgIEAgAAuTANBg...\\n"\n'
        '"-----END CERTIFICATE-----\\n";\n'
    )
    assert not _hits("firmware-ota-secure-boot-key-in-source", src)


# ---------- F4 : firmware-ota-recovery-debug-surface-in-prod -------------


def test_f4_jtag_not_disabled_flags() -> None:
    """`CONFIG_SECURE_DISABLE_JTAG=0` → HIGH hit."""
    src = (
        "CONFIG_SECURE_BOOT_ENABLED=y\n"
        "CONFIG_SECURE_DISABLE_JTAG=0\n"
    )
    hits = _hits("firmware-ota-recovery-debug-surface-in-prod", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_f4_zephyr_shell_enabled_flags() -> None:
    """`CONFIG_SHELL=y` (Zephyr UART shell) → hit."""
    src = (
        "CONFIG_BT=y\n"
        "CONFIG_SHELL=y\n"
        "CONFIG_SHELL_BACKEND_SERIAL=y\n"
    )
    assert _hits("firmware-ota-recovery-debug-surface-in-prod", src)


def test_f4_debug_optimizations_flags() -> None:
    """`CONFIG_DEBUG_OPTIMIZATIONS=y` → hit."""
    src = "CONFIG_DEBUG_OPTIMIZATIONS=y\n"
    assert _hits("firmware-ota-recovery-debug-surface-in-prod", src)


def test_f4_recovery_http_route_flags() -> None:
    """`/recovery/flash` HTTP route registration → hit."""
    src = (
        "httpd_register_uri_handler(server, &(httpd_uri_t){\n"
        '    .uri      = "/recovery/flash",\n'
        "    .method   = HTTP_POST,\n"
        "    .handler  = recovery_flash_handler,\n"
        "});\n"
    )
    assert _hits("firmware-ota-recovery-debug-surface-in-prod", src)


def test_f4_jtag_disabled_correctly_not_flagged() -> None:
    """`CONFIG_SECURE_DISABLE_JTAG=1` (correct) → no hit."""
    src = (
        "CONFIG_SECURE_BOOT_ENABLED=y\n"
        "CONFIG_SECURE_DISABLE_JTAG=1\n"
    )
    assert not _hits("firmware-ota-recovery-debug-surface-in-prod", src)


def test_f4_no_debug_config_silent() -> None:
    """Plain production sdkconfig with no debug toggles → no hits."""
    src = (
        "CONFIG_BT=y\n"
        "CONFIG_BT_NUS=y\n"
        "CONFIG_FLASH=y\n"
    )
    assert not _hits("firmware-ota-recovery-debug-surface-in-prod", src)


# ---------- F5 : firmware-ota-mkimage-imgtool-weak-hash-or-no-version ----


def test_f5_mkimage_md5_hash_flags() -> None:
    """`mkimage --hash-algo md5` → HIGH hit."""
    src = (
        "mkimage -A arm -O linux -T kernel -C none "
        "-a 0x80008000 -e 0x80008000 -n kernel -d zImage "
        "--hash-algo md5 uImage\n"
    )
    hits = _hits("firmware-ota-mkimage-imgtool-weak-hash-or-no-version", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_f5_imgtool_sign_missing_version_flags() -> None:
    """`imgtool sign` without `--version` / `--security-counter` → hit."""
    src = (
        "imgtool sign --key signing-key.pem --header-size 0x200 "
        "--align 4 --slot-size 0x60000 app.bin signed.bin\n"
    )
    hits = _hits("firmware-ota-mkimage-imgtool-weak-hash-or-no-version", src)
    assert hits


def test_f5_explicit_no_version_flag_flags() -> None:
    """`west sign --no-version` explicit downgrade → hit."""
    src = (
        "west sign -t imgtool -- --no-version\n"
    )
    assert _hits("firmware-ota-mkimage-imgtool-weak-hash-or-no-version", src)


def test_f5_mkimage_sha256_not_flagged() -> None:
    """`mkimage --hash-algo sha256` (correct) → no hit."""
    src = (
        "mkimage -A arm -O linux -T kernel -C none "
        "-a 0x80008000 -e 0x80008000 -n kernel -d zImage "
        "--hash-algo sha256 uImage\n"
    )
    assert not _hits("firmware-ota-mkimage-imgtool-weak-hash-or-no-version", src)


def test_f5_imgtool_with_version_not_flagged() -> None:
    """`imgtool sign --version 1.2.3 --security-counter 5` → no hit."""
    src = (
        "imgtool sign --key signing-key.pem --header-size 0x200 "
        "--align 4 --slot-size 0x60000 --version 1.2.3 "
        "--security-counter 5 app.bin signed.bin\n"
    )
    assert not _hits("firmware-ota-mkimage-imgtool-weak-hash-or-no-version", src)


def test_f5_legacy_checksum_opt_out_suppresses() -> None:
    """`mkimage-hash-allowed: legacy-checksum` comment near hit → suppressed."""
    src = (
        "# mkimage-hash-allowed: legacy-checksum\n"
        "mkimage -A arm -O linux -T kernel -C none "
        "-a 0x80008000 -e 0x80008000 -n boot-index -d zImage "
        "--hash-algo md5 uImage\n"
    )
    assert not _hits("firmware-ota-mkimage-imgtool-weak-hash-or-no-version", src)
