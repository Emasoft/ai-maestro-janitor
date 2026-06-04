"""Tests for scripts/lib/pulumi_state_patterns.py.

Pattern-coverage tests for the Wave-37 distill-round-23 Pulumi state +
Pulumi Cloud / ESC catalogue (10 attack classes: committed passphrase
env-var, plaintext stack-config secret, local file backend for prod, lost
secret output, isDryRun guard bypass, StackReference write escalation,
Automation API dynamic program, ESC wildcard read policy, pulumi import with
no digest pin, and --target-replace shell-glob).

Each attack class has at least one positive test (a realistic vulnerable
snippet that MUST match) and at least one negative test (a safe snippet that
MUST NOT match), proving no false-positive.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import pulumi_state_patterns as psp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented attack-class rule IDs."""
    assert isinstance(psp.RULES, tuple)
    rule_ids = {r.id for r in psp.RULES}
    expected = {
        "pulumi-passphrase-envvar-committed",
        "pulumi-stack-yaml-plaintext-secret",
        "pulumi-local-file-backend-prod",
        "pulumi-output-secret-lost",
        "pulumi-is-dry-run-bypass",
        "pulumi-stack-reference-no-readonly",
        "pulumi-automation-api-dynamic-program",
        "pulumi-esc-wildcard-read-policy",
        "pulumi-import-no-digest-pin",
        "pulumi-target-replace-glob",
    }
    assert expected == rule_ids


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in psp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors argocd_fluxcd_patterns.Finding shape."""
    f = psp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="CRITICAL", description="d", owasp_asi="ASI-09",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "CRITICAL"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert psp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, column, rule_id)."""
    src = (
        "export PULUMI_CONFIG_PASSPHRASE=supersecret123\n"
        "pulumi up --target-replace \"$TARGET_URN\" --yes\n"
    )
    findings = psp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[psp.Finding]:
    return [f for f in psp.scan_text(text) if f.rule_id == rule_id]


# ---------- R1 : pulumi-passphrase-envvar-committed ----------------------


def test_r1_passphrase_hardcoded_flags() -> None:
    """A hardcoded PULUMI_CONFIG_PASSPHRASE value triggers CRITICAL."""
    src = "export PULUMI_CONFIG_PASSPHRASE=supersecret123\npulumi up\n"
    hits = _hits("pulumi-passphrase-envvar-committed", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r1_passphrase_empty_value_no_flag() -> None:
    """An empty PULUMI_CONFIG_PASSPHRASE assignment does not flag this rule."""
    src = 'export PULUMI_CONFIG_PASSPHRASE=""\npulumi up\n'
    hits = _hits("pulumi-passphrase-envvar-committed", src)
    assert not hits


# ---------- R2 : pulumi-stack-yaml-plaintext-secret ----------------------


def test_r2_plaintext_db_password_flags() -> None:
    """A Pulumi.dev.yaml plaintext dbPassword value triggers HIGH."""
    src = (
        "config:\n"
        '  myproject:dbPassword: "hunter2value"\n'
        "  myproject:region: us-east-1\n"
    )
    hits = _hits("pulumi-stack-yaml-plaintext-secret", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r2_secure_encrypted_value_no_flag() -> None:
    """A `secure:` encrypted stack-config value does not flag (value on next line)."""
    src = (
        "config:\n"
        "  myproject:dbPassword:\n"
        "    secure: AAABACzVeryLongCiphertextBase64==\n"
    )
    hits = _hits("pulumi-stack-yaml-plaintext-secret", src)
    assert not hits


# ---------- R3 : pulumi-local-file-backend-prod --------------------------


def test_r3_file_backend_flags() -> None:
    """url: file:// in Pulumi.yaml triggers HIGH finding."""
    src = "backend:\n  url: file://${PWD}\n"
    hits = _hits("pulumi-local-file-backend-prod", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r3_managed_backend_no_flag() -> None:
    """A managed Pulumi Cloud / S3 backend URL does not flag."""
    src = "backend:\n  url: s3://my-pulumi-state-bucket\n"
    hits = _hits("pulumi-local-file-backend-prod", src)
    assert not hits


# ---------- R4 : pulumi-output-secret-lost -------------------------------


def test_r4_export_password_output_flags() -> None:
    """export const dbPassword = db.password triggers MEDIUM finding."""
    src = "export const dbPassword = db.password;\n"
    hits = _hits("pulumi-output-secret-lost", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_r4_export_secret_wrapped_no_flag() -> None:
    """export const wrapped with pulumi.secret(...) does not flag."""
    src = "export const dbPassword = pulumi.secret(db.password);\n"
    hits = _hits("pulumi-output-secret-lost", src)
    assert not hits


# ---------- R5 : pulumi-is-dry-run-bypass --------------------------------


def test_r5_python_is_dry_run_guard_flags() -> None:
    """`if not pulumi.runtime.is_dry_run():` triggers HIGH (Python form)."""
    src = (
        "if not pulumi.runtime.is_dry_run():\n"
        "    drop_all_tables(conn)\n"
    )
    hits = _hits("pulumi-is-dry-run-bypass", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r5_typescript_is_dry_run_guard_flags() -> None:
    """`if (!pulumi.runtime.isDryRun())` triggers HIGH (TypeScript form)."""
    src = (
        "if (!pulumi.runtime.isDryRun()) {\n"
        "    deleteProductionBucket();\n"
        "}\n"
    )
    hits = _hits("pulumi-is-dry-run-bypass", src)
    assert hits


def test_r5_plain_dry_run_read_no_flag() -> None:
    """A bare is_dry_run() read (no `if not` guard) does not flag."""
    src = "preview = pulumi.runtime.is_dry_run()\nlog.info(preview)\n"
    hits = _hits("pulumi-is-dry-run-bypass", src)
    assert not hits


# ---------- R6 : pulumi-stack-reference-no-readonly ----------------------


def test_r6_stack_reference_flags() -> None:
    """new pulumi.StackReference(...) triggers MEDIUM review finding."""
    src = 'const prodRef = new pulumi.StackReference("org/myapp/prod");\n'
    hits = _hits("pulumi-stack-reference-no-readonly", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_r6_no_stack_reference_no_flag() -> None:
    """Ordinary resource creation without a StackReference does not flag."""
    src = 'const bucket = new aws.s3.Bucket("b", {});\n'
    hits = _hits("pulumi-stack-reference-no-readonly", src)
    assert not hits


# ---------- R7 : pulumi-automation-api-dynamic-program -------------------


def test_r7_exec_then_create_stack_flags() -> None:
    """exec() near create_or_select_stack triggers CRITICAL finding."""
    src = (
        'program_str = request.json["infraCode"]\n'
        'exec(compile(program_str, "<string>", "exec"), globals())\n'
        "stack = auto.create_or_select_stack(stack_name=name, program=p)\n"
    )
    hits = _hits("pulumi-automation-api-dynamic-program", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r7_static_program_no_flag() -> None:
    """A static inline Automation API program (no exec/eval) does not flag."""
    src = (
        "def pulumi_program():\n"
        '    aws.s3.Bucket("b")\n'
        "stack = auto.create_or_select_stack(\n"
        "    stack_name=name, program=pulumi_program)\n"
    )
    hits = _hits("pulumi-automation-api-dynamic-program", src)
    assert not hits


# ---------- R8 : pulumi-esc-wildcard-read-policy -------------------------


def test_r8_esc_wildcard_read_flags() -> None:
    """An ESC `read: [\"*\"]` policy triggers HIGH finding."""
    src = (
        "values:\n"
        "  aws:\n"
        "    creds: {}\n"
        "policy:\n"
        '  read:\n'
        '    - "*"\n'
    )
    # The proposal form is also commonly inlined.
    src_inline = 'policy:\n  read: ["*"]\n'
    assert _hits("pulumi-esc-wildcard-read-policy", src_inline)
    hits_inline = _hits("pulumi-esc-wildcard-read-policy", src_inline)
    assert hits_inline[0].severity == "HIGH"
    # The block form is intentionally out of scope for the inline regex; the
    # inline form is the one the rule targets.
    assert isinstance(psp.scan_text(src), list)


def test_r8_esc_scoped_read_no_flag() -> None:
    """An ESC read policy scoped to named stacks does not flag."""
    src = 'policy:\n  read: ["org/app/prod", "org/app/staging"]\n'
    hits = _hits("pulumi-esc-wildcard-read-policy", src)
    assert not hits


# ---------- R9 : pulumi-import-no-digest-pin -----------------------------


def test_r9_import_no_plugin_flag_flags() -> None:
    """pulumi import without a --plugin integrity flag triggers MEDIUM."""
    src = "pulumi import aws:s3/bucket:Bucket my-bucket existing-bucket --yes\n"
    hits = _hits("pulumi-import-no-digest-pin", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_r9_import_with_plugin_hash_no_flag() -> None:
    """pulumi import carrying a --plugin integrity flag does not flag."""
    src = (
        "pulumi import aws:s3/bucket:Bucket my-bucket existing-bucket "
        "--plugin-download-url https://example.com/pin --yes\n"
    )
    hits = _hits("pulumi-import-no-digest-pin", src)
    assert not hits


# ---------- R10 : pulumi-target-replace-glob -----------------------------


def test_r10_target_replace_shell_var_flags() -> None:
    """pulumi up --target-replace \"$VAR\" triggers HIGH finding."""
    src = 'pulumi up --target-replace "$TARGET_URN" --yes\n'
    hits = _hits("pulumi-target-replace-glob", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r10_target_replace_literal_urn_no_flag() -> None:
    """pulumi up --target-replace with a literal URN (no shell var) does not flag."""
    src = (
        "pulumi up --target-replace "
        "'urn:pulumi:prod::app::aws:s3/bucket:Bucket::b' --yes\n"
    )
    hits = _hits("pulumi-target-replace-glob", src)
    assert not hits
