"""Java / JVM / JNDI security pattern catalogue.

Wave-26 distillation round 12 — JVM-runtime-specific attack surfaces NOT
covered by Waves 17-25 nor by `cross_lang_deserialize_patterns` (generic)
nor `js_deserialization` (browser). The angle here is JVM-runtime code
constructs that turn an untrusted String into remote class loading,
gadget execution, or arbitrary instantiation.

Catalogue (6 net-new rules, regex-only, all RE2-safe):

  * JAVA-JNDI-001  log4j-jndi-lookup-expansion-in-input         (CRITICAL)
  * JAVA-JNDI-002  initialcontext-lookup-untrusted-input        (CRITICAL)
  * JAVA-JNDI-003  objectinputstream-readobject-untrusted-bytes (CRITICAL)
  * JAVA-JNDI-004  class-forname-untrusted-input                (HIGH)
  * JAVA-JNDI-005  log4j-core-vulnerable-version-pin            (CRITICAL)
  * JAVA-JNDI-006  rmi-registry-attacker-reachable-codebase     (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-01 — Code injection / arbitrary execution (JNDI lookup expansion,
                                                   reflective class load,
                                                   deserialization gadget,
                                                   RMI codebase fetch)
  ASI-05 — Supply-chain / vulnerable-component pin (Log4j ≤ 2.16)
  ASI-07 — Authority / authorisation gaps (unauthenticated RMI registry)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes, all quantifiers are bounded). Patterns
are PRE-COMPILED at module load. Fail-fast: callers receive structured
Finding tuples, never raised exceptions on benign input.
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
    chat_bot_patterns / auth_flow_patterns / webhook_signature_patterns.
    RE2-safe: no nested quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- J1 : log4j-jndi-lookup-expansion-in-input --------------------------


# `${jndi:scheme://host/payload}` — the Log4Shell payload shape. Schemes
# enumerated explicitly (RE2-safe; no nested quantifier on the scheme).
# Path body is bounded {1,256}; closing `}` is required.
_LOG4SHELL_PLACEHOLDER = _re(
    r"\$\{jndi:(?:ldap|ldaps|rmi|dns|nis|iiop|corba|nds|http|t3|t3s)"
    r"://[^\"'\s}]{1,256}\}"
)


# ---- J2 : initialcontext-lookup-untrusted-input -------------------------


# `<Context-subtype>.lookup(<user-source>...)` — sink primitive Log4Shell
# exploits when the argument is request-scoped. The regex covers three
# realistic shapes on a single match:
#   (a) static-ish: `LdapContext.lookup(req.X)` (rare but seen)
#   (b) declaration + same-line var: `LdapContext myCtx.lookup(req.X)`
#       (also rare, would normally span two statements)
#   (c) chained ctor: `new InitialDirContext(env).lookup(req.X)`
#       (very common — `[\s\S]{0,80}?` bridges the nested `(env)`
#       paren without backtracking explosion)
# Bounded user-source body `{0,200}`. RE2-safe: lazy `?` quantifier on
# a bounded character class, no nested unbounded quantifiers.
_JNDI_LOOKUP_FROM_INPUT = _re(
    r"\b(?:InitialContext|InitialDirContext|DirContext|Context|LdapContext)"
    r"(?:\s*(?:[A-Za-z_][A-Za-z0-9_]{0,64})?|\s*\([^)\n]{0,80}\))?"
    r"\.lookup\s*\(\s*"
    r"(?:request\.|req\.|input|params?\[|getParameter|getHeader"
    r"|getQueryString|userInput|cfg\.)"
    r"[^)]{0,200}\)"
)


# ---- J3 : objectinputstream-readobject-untrusted-bytes ------------------


# `new ObjectInputStream(...).readObject()` or `.readUnshared()` — the
# canonical native-deserialization sink. Constructor body excludes `)`
# (bounded {1,200}) to handle a single-level inner paren by re-anchoring
# on the chained `.readObject(`/`.readUnshared(` call within 300 chars
# (RE2-safe lazy `[\s\S]{0,300}?` bridges nested parens / whitespace /
# newlines without backtracking explosion).
_OBJECTINPUTSTREAM_READ = _re(
    r"\bnew\s+ObjectInputStream\s*\([^)\n]{0,200}\)"
    r"[\s\S]{0,300}?"
    r"\.(?:readObject|readUnshared)\s*\(\s*\)"
)

# Companion: presence of `setObjectInputFilter(` in the surrounding window
# means the call site is JEP-290-hardened — suppress the finding.
_OBJECTINPUTSTREAM_FILTER_GUARD = _re(
    r"\bsetObjectInputFilter\s*\("
)


# ---- J4 : class-forname-untrusted-input ---------------------------------


# `Class.forName(<user-source>...)` — reflective class load whose name is
# attacker-controlled. The user-source clause is what separates this from
# the benign JDBC-driver bootstrap (constant string literal).
_CLASS_FORNAME_FROM_INPUT = _re(
    r"\bClass\.forName\s*\(\s*"
    r"(?:request\.|req\.|input|params?\[|getParameter|getHeader"
    r"|userInput|System\.getenv|System\.getProperty)"
    r"[^)]{0,200}\)"
)


# ---- J5 : log4j-core-vulnerable-version-pin -----------------------------


# Dependency-manifest pin to log4j-core / log4j-api version 2.0 through
# 2.16.x (inclusive). RE2 has no numeric range matching — minor versions
# enumerated explicitly. Matches Maven (`:`), Gradle (`:`), and pom-XML
# (`>`) separator conventions.
#
# Critical anti-FP measure: the minor-version group is followed by a
# trailing CHARACTER CLASS that EXCLUDES `[0-9]` (i.e. one of `.`, `'`,
# `"`, `<`, whitespace, or EOL). Without it, the regex would match the
# `2.1` prefix of `2.17.0` (`1` is a single-digit minor that fits
# `[0-9]`). Consuming the terminator (not using lookahead) keeps the
# regex RE2-safe.
_LOG4J_VULNERABLE_VERSION_PIN = _re(
    r"org\.apache\.logging\.log4j[:/]log4j-(?:core|api)"
    r"[:>]\s*['\"]?"
    r"2\.(?:[0-9]|1[0-6])"
    r"(?:\.[0-9]{1,3})?"
    r"(?:[-.][A-Za-z0-9]{1,20})?"
    r"['\"<\s]"
)

# Companion mitigations — when EITHER appears anywhere in the same
# manifest/config text, the version pin is considered mitigated and J5
# is suppressed.
_LOG4J_FORMATMSG_NOLOOKUPS_GUARD = _re(
    r"log4j2\.formatMsgNoLookups\s*=\s*true"
    r"|"
    r"LOG4J_FORMAT_MSG_NO_LOOKUPS\s*=\s*true"
    r"|"
    r"%m\{nolookups\}"
)


# ---- J6 : rmi-registry-attacker-reachable-codebase ----------------------


# RMI registry / Naming bind / lookup primitive. The call alone is not
# proof of vulnerability; the Stage-B check looks for an explicit
# `useCodebaseOnly=false` flip OR a non-loopback bind address in the
# surrounding window.
_RMI_REGISTRY_PRIMITIVE = _re(
    r"\b(?:LocateRegistry\.(?:createRegistry|getRegistry)"
    r"|Naming\.(?:rebind|bind|lookup))\s*\("
)

# Codebase trust flip — explicit opt-in to the dangerous default.
_RMI_USE_CODEBASE_ONLY_FALSE = _re(
    r"System\.setProperty\s*\(\s*['\"]java\.rmi\.server\.useCodebaseOnly['\"]"
    r"\s*,\s*['\"]false['\"]\s*\)"
)

# Loopback guard — if the registry is bound to 127.0.0.1 / localhost only
# in the same window, the finding is down-rated to FP.
_RMI_LOOPBACK_BIND = _re(
    r"\b(?:127\.0\.0\.1|localhost|0:0:0:0:0:0:0:1|::1|InetAddress\.getLoopback)"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="log4j-jndi-lookup-expansion-in-input",
        name="Log4Shell-shape `${jndi:scheme://...}` placeholder in source",
        severity="CRITICAL",
        description=(
            "Log4j 2 prior to 2.16 expanded `${jndi:scheme://host/payload}` "
            "placeholders inside any logged String, even when that String "
            "came from an HTTP header / form field / log argument. The "
            "LDAP path then deserialized the returned remote object "
            "reference, yielding RCE (CVE-2021-44228 / Log4Shell). The "
            "literal `${jndi:` prefix appears in attacker payloads, "
            "logs, WAF rules, and any source/sink that handles arbitrary "
            "text. Mitigate by upgrading to Log4j 2.17+ and treating the "
            "placeholder as untrusted on inbound channels."
        ),
        pattern=_LOG4SHELL_PLACEHOLDER,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="initialcontext-lookup-untrusted-input",
        name="`InitialContext.lookup(<user input>)` without allowlist",
        severity="CRITICAL",
        description=(
            "Direct call to `javax.naming.InitialContext#lookup(String)` "
            "(or `DirContext#lookup`, `Context#lookup`, `LdapContext#lookup`) "
            "where the argument comes from request-scoped input. This is "
            "the primitive Log4Shell exploited: a `ldap://` URL returns a "
            "`javaNamingReference` whose `factory` / `factoryLocation` "
            "triggers `URLClassLoader` to fetch a remote class. With "
            "`com.sun.jndi.ldap.object.trustURLCodebase=true` the returned "
            "class is instantiated → arbitrary RCE. Enforce an allowlist "
            "of permitted JNDI names and reject everything else."
        ),
        pattern=_JNDI_LOOKUP_FROM_INPUT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="objectinputstream-readobject-untrusted-bytes",
        name="`ObjectInputStream.readObject()` on attacker-reachable bytes",
        severity="CRITICAL",
        description=(
            "Native Java deserialization on a byte stream that originates "
            "from outside the JVM trust boundary (HTTP body, RMI message, "
            "JMS payload, Redis cache, cookie, file upload) without an "
            "`ObjectInputFilter`. The deserialization protocol invokes "
            "`readObject` callbacks on every reconstructed class — "
            "CommonsCollections, ROME, Spring, Groovy, Hibernate, JBoss "
            "Interceptor proxies, etc. reach `Runtime.exec` purely from "
            "the deserialization side-effects. The cast to a DTO happens "
            "AFTER the gadgets have fired, so type checks are useless. "
            "Mitigate with `setObjectInputFilter(...)` (JEP 290)."
        ),
        pattern=_OBJECTINPUTSTREAM_READ,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="class-forname-untrusted-input",
        name="`Class.forName(<user input>)` reflective dispatch",
        severity="HIGH",
        description=(
            "Reflective class loading where the class name comes from "
            "untrusted input. The attacker picks any class on the "
            "classpath whose default constructor or initializer has a "
            "useful side-effect: ScriptEngineManager + Nashorn, "
            "Launcher$AppClassLoader, Groovy's MetaClassImpl, "
            "InvokerTransformer, SpelExpressionParser, or anything that "
            "performs work in `<clinit>`. This is the JVM equivalent of "
            "`eval(req.param)` operating at the class-graph layer, "
            "bypassing most 'no eval' linters."
        ),
        pattern=_CLASS_FORNAME_FROM_INPUT,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="log4j-core-vulnerable-version-pin",
        name="Dependency manifest pins log4j-core to a vulnerable 2.x range",
        severity="CRITICAL",
        description=(
            "Defense-in-depth detector: a project pins "
            "`org.apache.logging.log4j:log4j-core` (or log4j-api) to any "
            "version 2.0 through 2.16.0. 2.15.0 patched the default but "
            "left attack surface via Thread Context Map lookups; 2.16.0 "
            "removed Message Lookups; only 2.17.0+ removed recursive "
            "evaluation (fixed CVE-2021-45105 DoS). The version line "
            "alone is the flag; presence of `log4j2.formatMsgNoLookups=true` "
            "or `LOG4J_FORMAT_MSG_NO_LOOKUPS=true` or `%m{nolookups}` in "
            "the same manifest/config suppresses the finding as mitigated."
        ),
        pattern=_LOG4J_VULNERABLE_VERSION_PIN,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="rmi-registry-attacker-reachable-codebase",
        name="RMI Registry / Naming primitive with codebase trust flipped on",
        severity="HIGH",
        description=(
            "Java RMI treats `java.rmi.server.codebase` as a remote URL "
            "from which remote objects' classes are fetched. An "
            "unauthenticated `LocateRegistry.createRegistry(...)` exposed "
            "on a routable interface, combined with "
            "`useCodebaseOnly=false`, lets an attacker bind a stub whose "
            "class definition is served from the attacker's codebase URL. "
            "Any client (including the server's own introspection) then "
            "downloads and instantiates the attacker's class. Same "
            "trust-the-remote-codebase root cause as Log4Shell, different "
            "transport. Down-rate when the registry binds to 127.0.0.1 / "
            "localhost / ::1 / `InetAddress.getLoopback()` only."
        ),
        pattern=_RMI_REGISTRY_PRIMITIVE,
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


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines / file-level context:

      * J3 (objectinputstream-readobject-untrusted-bytes) — suppress when
        `setObjectInputFilter(` appears within a 30-line window around
        the call site (JEP-290-hardened).
      * J5 (log4j-core-vulnerable-version-pin) — suppress when ANY of
        `log4j2.formatMsgNoLookups=true`, `LOG4J_FORMAT_MSG_NO_LOOKUPS=true`,
        or `%m{nolookups}` appears anywhere in the same text (mitigated).
      * J6 (rmi-registry-attacker-reachable-codebase) — emit only when
        `useCodebaseOnly=false` appears in the file AND the call site is
        NOT inside a 30-line window with a loopback bind marker.

    Findings are deduped by (rule_id, line, col) and sorted by
    (line, col, rule_id) for deterministic output.
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

    # ---- J1 : log4j-jndi-lookup-expansion-in-input ----
    rule_j1 = rule_by_id["log4j-jndi-lookup-expansion-in-input"]
    for m in _LOG4SHELL_PLACEHOLDER.finditer(text):
        _emit(rule_j1, m.start(), m.group(0))

    # ---- J2 : initialcontext-lookup-untrusted-input ----
    rule_j2 = rule_by_id["initialcontext-lookup-untrusted-input"]
    for m in _JNDI_LOOKUP_FROM_INPUT.finditer(text):
        _emit(rule_j2, m.start(), m.group(0))

    # ---- J3 : objectinputstream-readobject-untrusted-bytes ----
    rule_j3 = rule_by_id["objectinputstream-readobject-untrusted-bytes"]
    for m in _OBJECTINPUTSTREAM_READ.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 15, 15)
        if _OBJECTINPUTSTREAM_FILTER_GUARD.search(window) is not None:
            continue
        _emit(rule_j3, m.start(), m.group(0))

    # ---- J4 : class-forname-untrusted-input ----
    rule_j4 = rule_by_id["class-forname-untrusted-input"]
    for m in _CLASS_FORNAME_FROM_INPUT.finditer(text):
        _emit(rule_j4, m.start(), m.group(0))

    # ---- J5 : log4j-core-vulnerable-version-pin ----
    rule_j5 = rule_by_id["log4j-core-vulnerable-version-pin"]
    has_mitigation = _file_contains(text, _LOG4J_FORMATMSG_NOLOOKUPS_GUARD)
    if not has_mitigation:
        for m in _LOG4J_VULNERABLE_VERSION_PIN.finditer(text):
            _emit(rule_j5, m.start(), m.group(0))

    # ---- J6 : rmi-registry-attacker-reachable-codebase ----
    rule_j6 = rule_by_id["rmi-registry-attacker-reachable-codebase"]
    codebase_flip = _file_contains(text, _RMI_USE_CODEBASE_ONLY_FALSE)
    if codebase_flip:
        for m in _RMI_REGISTRY_PRIMITIVE.finditer(text):
            line, _ = _line_col(text, m.start())
            window = _slice_window(text, line, 5, 10)
            if _RMI_LOOPBACK_BIND.search(window) is not None:
                continue
            _emit(rule_j6, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
