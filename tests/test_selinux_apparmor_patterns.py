"""Tests for selinux_apparmor_patterns — 2 per rule (positive + negative)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))

from selinux_apparmor_patterns import RULES, scan_text  # type: ignore[import-not-found]  # noqa: E402


class TestSAG01SelinuxHostConfigPermissive(unittest.TestCase):
    """sa-selinux-host-config-permissive: SELINUX=permissive/disabled in config or Ansible."""

    def test_positive_selinux_config_permissive(self):
        """Config file line SELINUX=permissive is detected as CRITICAL."""
        text = "SELINUX=permissive\nSELINUXTYPE=targeted\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-selinux-host-config-permissive"]
        self.assertTrue(findings, "Expected a finding for SELINUX=permissive")
        self.assertEqual(findings[0].severity, "CRITICAL")

    def test_negative_selinux_config_enforcing(self):
        """Config file line SELINUX=enforcing must not be detected."""
        text = "SELINUX=enforcing\nSELINUXTYPE=targeted\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-selinux-host-config-permissive"]
        self.assertFalse(findings, "SELINUX=enforcing must not trigger the rule")


class TestSAG02SetseboolPersistentHighRisk(unittest.TestCase):
    """sa-setsebool-persistent-high-risk: setsebool -P with dangerous boolean."""

    def test_positive_setsebool_execstack(self):
        """setsebool -P allow_execstack 1 is detected as HIGH."""
        text = "setsebool -P allow_execstack 1\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-setsebool-persistent-high-risk"]
        self.assertTrue(findings, "Expected a finding for setsebool -P allow_execstack 1")
        self.assertEqual(findings[0].severity, "HIGH")

    def test_negative_setsebool_safe_boolean(self):
        """setsebool -P httpd_use_nfs 1 (non-dangerous boolean) must not be detected."""
        text = "setsebool -P httpd_use_nfs 1\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-setsebool-persistent-high-risk"]
        self.assertFalse(findings, "Non-dangerous boolean must not trigger the rule")


class TestSAG03Audit2AllowWildcardAllow(unittest.TestCase):
    """sa-audit2allow-wildcard-allow: audit2allow wildcard or broad allow rules in .te files."""

    def test_positive_wildcard_permission_set(self):
        """An allow rule with { * } permission set is detected as HIGH."""
        text = "allow httpd_t file_type:file { * };\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-audit2allow-wildcard-allow"]
        self.assertTrue(findings, "Expected a finding for wildcard { * } allow rule")

    def test_negative_narrow_allow_rule(self):
        """A narrow allow rule (allow httpd_t httpd_sys_content_t:file { read }) is not detected."""
        text = "allow httpd_t httpd_sys_content_t:file { read };\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-audit2allow-wildcard-allow"]
        self.assertFalse(findings, "A narrow, specific allow rule must not trigger the rule")


class TestSAG04AppArmorComplainModeInScript(unittest.TestCase):
    """sa-apparmor-complain-mode-in-script: aa-complain in shell or Ansible state: complain."""

    def test_positive_aa_complain_shell(self):
        """aa-complain /usr/sbin/mysqld in a shell script is detected as HIGH."""
        text = "aa-complain /usr/sbin/mysqld\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-apparmor-complain-mode-in-script"]
        self.assertTrue(findings, "Expected a finding for aa-complain in shell")
        self.assertEqual(findings[0].severity, "HIGH")

    def test_negative_aa_enforce_is_safe(self):
        """aa-enforce /usr/sbin/mysqld must not be detected."""
        text = "aa-enforce /usr/sbin/mysqld\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-apparmor-complain-mode-in-script"]
        self.assertFalse(findings, "aa-enforce must not trigger the complain-mode rule")


class TestSAG05SystemdAppArmorProfileName(unittest.TestCase):
    """sa-systemd-apparmor-profile-name: AppArmorProfile= in systemd unit."""

    def test_positive_apparmor_profile_directive(self):
        """AppArmorProfile= in a service unit is detected as MEDIUM."""
        text = "[Service]\nAppArmorProfile=/etc/apparmor.d/usr.sbin.nginx\nExecStart=/usr/sbin/nginx\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-systemd-apparmor-profile-name"]
        self.assertTrue(findings, "Expected a finding for AppArmorProfile= directive")
        self.assertEqual(findings[0].severity, "MEDIUM")

    def test_negative_no_apparmor_profile(self):
        """A service unit without AppArmorProfile= must not be detected."""
        text = "[Service]\nExecStart=/usr/sbin/nginx\nRestart=on-failure\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-systemd-apparmor-profile-name"]
        self.assertFalse(findings, "Unit without AppArmorProfile= must not trigger the rule")


class TestSAG06DockerSelinuxCustomPermissiveType(unittest.TestCase):
    """sa-docker-selinux-custom-permissive-type: label:type=unconfined_t/spc_t or K8s annotation."""

    def test_positive_label_type_spc_t(self):
        """--security-opt label:type=spc_t is detected as MEDIUM."""
        text = "docker run --security-opt label:type=spc_t myimage\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-docker-selinux-custom-permissive-type"]
        self.assertTrue(findings, "Expected a finding for label:type=spc_t")
        self.assertEqual(findings[0].severity, "MEDIUM")

    def test_negative_label_type_container_t(self):
        """--security-opt label:type=container_t (default safe type) must not be detected."""
        text = "docker run --security-opt label:type=container_t myimage\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-docker-selinux-custom-permissive-type"]
        self.assertFalse(findings, "Safe container_t type must not trigger the rule")


class TestSAG07LibapparmorChangeToUnconfined(unittest.TestCase):
    """sa-libapparmor-change-to-unconfined: aa_change_hat/onexec/profile with unconfined target."""

    def test_positive_aa_change_hat_unconfined(self):
        """aa_change_hat(\"unconfined\", token) is detected as CRITICAL."""
        text = 'if (aa_change_hat("unconfined", magic) < 0) { perror("aa_change_hat"); }\n'
        findings = [f for f in scan_text(text) if f.rule_id == "sa-libapparmor-change-to-unconfined"]
        self.assertTrue(findings, "Expected a finding for aa_change_hat with unconfined target")
        self.assertEqual(findings[0].severity, "CRITICAL")

    def test_negative_aa_change_hat_named_profile(self):
        """aa_change_hat with a named hat like \"webserver\" must not be detected."""
        text = 'if (aa_change_hat("webserver", magic) < 0) { perror("aa_change_hat"); }\n'
        findings = [f for f in scan_text(text) if f.rule_id == "sa-libapparmor-change-to-unconfined"]
        self.assertFalse(findings, "Named hat target must not trigger the unconfined rule")


class TestSAG08K8sSecurityContextNoLsmProfile(unittest.TestCase):
    """sa-k8s-securitycontext-no-lsm-profile: securityContext with hardening but no LSM profile fields."""

    def test_positive_security_context_missing_lsm_fields(self):
        """securityContext with runAsNonRoot but no seccompProfile/appArmorProfile is detected."""
        text = (
            "spec:\n"
            "  securityContext:\n"
            "    runAsNonRoot: true\n"
            "    runAsUser: 1000\n"
            "    allowPrivilegeEscalation: false\n"
        )
        findings = [f for f in scan_text(text) if f.rule_id == "sa-k8s-securitycontext-no-lsm-profile"]
        self.assertTrue(findings, "Expected a finding when LSM profile fields are absent")
        self.assertEqual(findings[0].severity, "MEDIUM")

    def test_negative_security_context_with_seccomp_profile(self):
        """securityContext that includes seccompProfile must not be detected."""
        text = (
            "spec:\n"
            "  securityContext:\n"
            "    runAsNonRoot: true\n"
            "    allowPrivilegeEscalation: false\n"
            "    seccompProfile:\n"
            "      type: RuntimeDefault\n"
        )
        findings = [f for f in scan_text(text) if f.rule_id == "sa-k8s-securitycontext-no-lsm-profile"]
        self.assertFalse(findings, "securityContext with seccompProfile must not trigger the rule")


class TestSAG09DockerfileRuncmdAaComplain(unittest.TestCase):
    """sa-dockerfile-runcmd-aa-complain: Dockerfile RUN aa-complain or entrypoint path-anchored call."""

    def test_positive_dockerfile_run_aa_complain(self):
        """Dockerfile RUN layer calling aa-complain is detected as HIGH."""
        text = "FROM ubuntu:24.04\nRUN apt-get install -y apparmor-utils && aa-complain /etc/apparmor.d/usr.sbin.nginx\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-dockerfile-runcmd-aa-complain"]
        self.assertTrue(findings, "Expected a finding for RUN aa-complain in Dockerfile")
        self.assertEqual(findings[0].severity, "HIGH")

    def test_negative_dockerfile_run_aa_enforce(self):
        """Dockerfile RUN layer calling aa-enforce must not be detected."""
        text = "FROM ubuntu:24.04\nRUN aa-enforce /etc/apparmor.d/usr.sbin.nginx\n"
        findings = [f for f in scan_text(text) if f.rule_id == "sa-dockerfile-runcmd-aa-complain"]
        self.assertFalse(findings, "aa-enforce in Dockerfile must not trigger the rule")


class TestRulesIntegrity(unittest.TestCase):
    """Structural invariants for the RULES tuple."""

    def test_rules_count(self):
        """RULES must contain exactly 9 rules."""
        self.assertEqual(len(RULES), 9)

    def test_all_ids_prefixed_sa(self):
        """Every rule ID must start with 'sa-'."""
        for rule in RULES:
            self.assertTrue(rule.id.startswith("sa-"), f"Rule {rule.id!r} missing 'sa-' prefix")

    def test_no_duplicate_ids(self):
        """All rule IDs must be unique."""
        ids = [r.id for r in RULES]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate rule IDs found")

    def test_valid_severities(self):
        """Every rule must have a severity in the accepted set."""
        valid = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}
        for rule in RULES:
            self.assertIn(rule.severity, valid, f"Invalid severity on rule {rule.id!r}")

    def test_scan_text_empty_string(self):
        """scan_text on empty string must return an empty list without raising."""
        self.assertEqual(scan_text(""), [])

    def test_scan_text_returns_sorted_findings(self):
        """scan_text must return findings sorted by (line, column, rule_id)."""
        text = (
            "SELINUX=permissive\n"
            'aa_change_hat("unconfined", 0);\n'
        )
        findings = scan_text(text)
        keys = [(f.line, f.column, f.rule_id) for f in findings]
        self.assertEqual(keys, sorted(keys), "Findings must be sorted by (line, col, rule_id)")


if __name__ == "__main__":
    unittest.main()
