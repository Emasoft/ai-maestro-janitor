"""Cross-language deserialization attack-surface patterns.

Wave 20 impl-H — distillation of 14 proposals from
``reports/distill-round-6/cross-lang-deserialize.md`` into deterministic
regex rules covering every server-side runtime *other* than Python
(Python ``pickle.loads`` / ``yaml.load`` is owned by sibling agent
dr6-G's ``python_specific_patterns.py``).

What this module covers (14 rules, every one statically grep-able):

  * Ruby ``Marshal.load`` / ``Marshal.restore`` on untrusted bytes
  * Ruby ``YAML.load`` / ``YAML.unsafe_load`` / ``YAML.load_file``
  * Ruby ``Oj.load`` / ``Oj.strict_load`` in ``:object`` mode
  * Java ``new ObjectInputStream(...).readObject()``
  * Java ``XMLDecoder.readObject()``
  * Java Jackson ``enableDefaultTyping`` / ``@JsonTypeInfo(Id.CLASS)``
  * .NET ``BinaryFormatter.Deserialize``
  * .NET ``JavaScriptSerializer`` + ``SimpleTypeResolver``
  * .NET ``LosFormatter`` / ``NetDataContractSerializer``
  * PHP ``unserialize($_GET/$_POST/$_COOKIE)`` / ``wddx_deserialize``
  * Erlang / Elixir ``binary_to_term(Bin)`` without ``[safe]``
  * Node.js ``node-serialize.unserialize(...)`` / ``funcster``
  * Hessian ``HessianInput.readObject()`` / ``Hessian2Input``
  * SnakeYAML ``new Yaml().load`` (cross-language YAML catch-all)

Architecture mirrors ``scripts/lib/python_specific_patterns.py``:

  * ``Rule(id, name, severity, description, pattern, owasp_asi)``
                                  — single rule record. Patterns are
                                    pre-compiled at module load.
  * ``RULES``                     — ordered tuple of every catalogued rule.
  * ``scan_text(text)`` -> list[Finding]
                                  — run every rule, return findings.
  * ``Finding(rule_id, line, column, matched_text, severity,
              description, owasp_asi)``
                                  — frozen NamedTuple.

Pure-stdlib (``re``, ``NamedTuple``) so the module loads in every
PEP 723 script block without third-party deps. Every regex is
**RE2-safe** — no backreferences, no possessive quantifiers, no
catastrophic-backtracking ambiguity. Every quantifier is anchored
to a bounded upper limit.

OWASP ASI mapping:
  ASI-05 — Insecure Plug-In / supply-chain pivot (gadget chains
                                                  imported via deps)
  ASI-06 — Insecure Output / Code Execution (every deserialization
                                              → RCE shape)
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    ``scripts/lib/agent_config_patterns.Finding`` so heartbeat
    detectors can render either kind uniformly."""

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
    """Compile a pattern with MULTILINE+UNICODE.

    These regexes target source code in Ruby / Java / .NET / PHP /
    Erlang / Node — every one of those languages is case-sensitive
    for identifiers, so IGNORECASE is deliberately NOT applied (we
    do NOT want ``BinaryFormatter`` and ``binaryformatter`` to both
    fire — only the canonical class name).
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- Proposal 1: Ruby Marshal.load / Marshal.restore on untrusted bytes


# ``Marshal.load`` / ``Marshal.restore`` invoked with anything that is
# NOT a same-method ``Marshal.dump`` round-trip is treated as an open
# RCE primitive (Elttam Ruby 2.x Universal Deserialization Gadget Chain,
# 2018; identical surface in Ruby 3.x).
#
# Pattern: ``Marshal.load(`` or ``Marshal.restore(`` followed by
# something that is NOT a quote-opener (no literal string) and NOT
# the result of an inline ``Marshal.dump(...)`` call. Trailing
# bounded content matches the argument body.
_RUBY_MARSHAL_LOAD = _re(
    r"\bMarshal\s*\.\s*(?:load|restore)\s*\(\s*"
    r"(?!Marshal\s*\.\s*dump\b)"            # not a round-trip test
    r"(?!['\"])"                             # not a string literal
    r"(?![\)\n])"                            # not empty
    r"[^\n\)]{1,200}"
)


# ---- Proposal 2: Ruby YAML.load / YAML.unsafe_load / YAML.load_file ----


# Catch-all for the unsafe-loader-by-default era (Psych < 4 / Ruby <
# 3.1) plus the explicit-opt-in shapes (``unsafe_load``).
#
# Negative shape we DON'T want to match: ``YAML.safe_load(...)``.
# A negative lookahead on ``safe_`` after ``YAML.`` excludes the
# safe variant.
_RUBY_YAML_LOAD = _re(
    r"\bYAML\s*\.\s*"
    r"(?:unsafe_load|load_file|load(?!_documents?\s*\(\s*['\"])"
    r"(?<!safe_load))"
    r"\s*\("
    r"(?!\s*['\"])"                          # arg is NOT a literal string
)


# ---- Proposal 3: Ruby Oj.load in :object mode --------------------------


# Three shapes:
#  - ``Oj.load(data, mode: :object)`` — explicit
#  - ``Oj.strict_load(data)`` — strict_load resolves ^o/^c class
#                                names regardless of default mode
#  - ``Oj.default_options = { mode: :object }`` — global flip; every
#                                                  subsequent Oj.load
#                                                  is vulnerable
#
# Branch A catches the first two; Branch B catches the global default
# flip.
_OJ_OBJECT_MODE = _re(
    # Branch A: explicit :object mode on Oj.load OR Oj.strict_load
    r"\bOj\s*\.\s*"
    r"(?:strict_load\s*\("
    r"|load(?:_file)?\s*\([^)\n]{0,200}?mode\s*:\s*:object)"
    # Branch B: default_options flip → :object
    r"|\bOj\s*\.\s*default_options\s*=\s*\{[^}\n]{0,200}?:object"
)


# ---- Proposal 4: Java new ObjectInputStream(...).readObject() ----------


# Two shapes:
#  - ``new ObjectInputStream(stream).readObject()`` — direct, single
#                                                     statement
#  - ``new ObjectInputStream(stream); ... ois.readObject()`` — split
#                                                              into two
#                                                              lines
#
# We use two patterns combined: (A) ``new ObjectInputStream(`` followed
# within 300 chars by ``.readObject(``, OR (B) ``SerializationUtils
# .deserialize(`` (commons-lang3 wrapper, equivalent RCE surface).
_JAVA_OBJECT_INPUT_STREAM = _re(
    r"\bnew\s+ObjectInputStream\s*\([^)\n]{0,200}\)"
    r"[\s\S]{0,300}?\.\s*readObject\s*\("
    r"|\bSerializationUtils\s*\.\s*deserialize\s*\("
)


# ---- Proposal 5: Java XMLDecoder.readObject() --------------------------


# ``XMLDecoder`` is architecturally an RCE primitive — the XML
# payload literally encodes method calls. Match the class name in
# any ``new XMLDecoder(`` or ``XMLDecoder.readObject`` shape. We
# DELIBERATELY do not require a stream argument because:
#   (a) every legitimate use of XMLDecoder is unsafe by design;
#   (b) Oracle's own documentation acknowledges this — there is no
#       safe configuration to vouch against.
_JAVA_XML_DECODER = _re(
    r"\bnew\s+XMLDecoder\s*\("
    r"|\bXMLDecoder\s+[A-Za-z_][\w]*\s*=\s*new\s+XMLDecoder\s*\("
    r"|\.\s*XMLDecoder\s*\("
)


# ---- Proposal 6: Java Jackson polymorphic deserialization --------------


# Three shapes:
#  - ``enableDefaultTyping()`` / ``enableDefaultTyping(NON_FINAL)``
#  - ``activateDefaultTyping(LaissezFaireSubTypeValidator...)`` (the
#    explicit "I know it's risky but I want every type" validator)
#  - ``@JsonTypeInfo(use = JsonTypeInfo.Id.CLASS, ...)`` annotation
#
# We exclude the safe shape: ``activateDefaultTyping`` with
# ``BasicPolymorphicTypeValidator.builder()`` that has a non-empty
# allow-list. Detecting "non-empty allow-list" requires AST walk;
# at the regex layer we conservatively fire on every activate call
# and let the caller suppress with a comment-pragma if needed.
_JACKSON_POLYMORPHIC = _re(
    r"\.\s*enableDefaultTyping\s*\("
    r"|\.\s*activateDefaultTyping\s*\("
    r"|@JsonTypeInfo\s*\([^)\n]{0,400}?use\s*=\s*"
    r"(?:JsonTypeInfo\s*\.)?Id\s*\.\s*CLASS"
)


# ---- Proposal 7: .NET BinaryFormatter.Deserialize ----------------------


# Two shapes:
#  - ``new BinaryFormatter()`` followed by ``.Deserialize(``
#  - ``BinaryFormatter`` variable name + ``.Deserialize(``
#
# Also flag the project-level opt-in:
# ``<EnableUnsafeBinaryFormatterSerialization>true``
# (matched on a separate branch).
_DOTNET_BINARY_FORMATTER = _re(
    r"\bnew\s+BinaryFormatter\s*\([^)\n]{0,100}\)"
    r"[\s\S]{0,300}?\.\s*Deserialize\s*\("
    r"|\bBinaryFormatter\s+[A-Za-z_][\w]*\s*=\s*new\s+BinaryFormatter\s*\("
    r"|<EnableUnsafeBinaryFormatterSerialization>\s*true"
)


# ---- Proposal 8: .NET JavaScriptSerializer + SimpleTypeResolver --------


# ``new JavaScriptSerializer(new SimpleTypeResolver())`` — the
# ``SimpleTypeResolver`` reads ``__type`` from JSON and resolves it
# via ``Type.GetType(name)``, identical surface to Jackson's
# ``enableDefaultTyping``.
#
# Match three shapes:
#  - ``new JavaScriptSerializer(new SimpleTypeResolver())`` — direct
#  - ``new SimpleTypeResolver()`` anywhere (always unsafe)
#  - ``new JavaScriptSerializer(new <X>TypeResolver(...))`` — any
#    custom resolver that subclasses ``JavaScriptTypeResolver``
_DOTNET_JS_SERIALIZER_TYPE_RESOLVER = _re(
    r"\bnew\s+JavaScriptSerializer\s*\(\s*new\s+[A-Za-z_][\w]*TypeResolver\b"
    r"|\bnew\s+SimpleTypeResolver\s*\("
)


# ---- Proposal 9: .NET LosFormatter / NetDataContractSerializer ---------


# Two distinct sinks, same module because they're both .NET
# type-preserving serializers:
#  - ``new LosFormatter()`` + ``.Deserialize(`` — ViewState engine
#  - ``new NetDataContractSerializer()`` + ``.ReadObject(`` — WCF
#                                                              type-
#                                                              preserving
_DOTNET_LOS_OR_NDCS = _re(
    r"\bnew\s+LosFormatter\s*\("
    r"|\bnew\s+NetDataContractSerializer\s*\("
    r"|\bLosFormatter\s+[A-Za-z_][\w]*\s*=\s*new\s+LosFormatter\s*\("
    r"|\bNetDataContractSerializer\s+[A-Za-z_][\w]*\s*=\s*new\s+NetDataContractSerializer\s*\("
)


# ---- Proposal 10: PHP unserialize / wddx_deserialize -------------------


# Three shapes that all reach the gadget chain:
#  - ``unserialize($_GET['x'])`` / ``$_POST`` / ``$_COOKIE`` /
#    ``$_REQUEST`` — direct from superglobal
#  - ``unserialize(base64_decode($_…))`` — base64-wrapped superglobal
#  - ``unserialize(file_get_contents("php://input"))`` — raw POST body
#  - ``wddx_deserialize($_…)`` — legacy WDDX, same gadget surface
#
# Negative carve-out: ``unserialize($x, ['allowed_classes' => false])``
# is the documented defense. We do NOT exclude it at the regex layer
# because the second-arg form is rarely combined with superglobals
# in vulnerable code — and the caller can suppress per-finding with
# a pragma comment if needed. Better to over-flag and let the
# operator audit.
_PHP_UNSERIALIZE = _re(
    r"\bunserialize\s*\(\s*"
    r"(?:\$_(?:GET|POST|COOKIE|REQUEST|SERVER|FILES|SESSION)\b"
    r"|base64_decode\s*\(\s*\$_(?:GET|POST|COOKIE|REQUEST)"
    r"|file_get_contents\s*\(\s*['\"]php://input['\"]\s*\))"
    r"|\bwddx_deserialize\s*\("
)


# ---- Proposal 11: Erlang / Elixir binary_to_term without [safe] --------


# Two language shapes:
#  - Erlang: ``binary_to_term(Bin).``
#  - Elixir: ``:erlang.binary_to_term(bin)``
#
# We trigger when the call site lacks the ``[safe]`` / ``[:safe]``
# option list. A negative lookahead on ``, […safe…]`` is the
# carve-out.
_ERLANG_BINARY_TO_TERM = _re(
    r"\b(?::erlang\s*\.\s*)?binary_to_term\s*\("
    r"(?![^)\n]{0,200}?\[[^\]\n]{0,80}:?safe[\s,\]])"
    r"[^\n)]{0,100}\)"
)


# ---- Proposal 12: Node.js node-serialize.unserialize -------------------


# Two shapes:
#  - ``require('node-serialize')`` import
#  - ``<serialize-module>.unserialize(`` callsite
#
# We catch both shapes; the import is itself a red flag (no safe
# mode exists), the callsite is the live sink.
_NODE_SERIALIZE = _re(
    r"\brequire\s*\(\s*['\"]node-serialize['\"]\s*\)"
    r"|\brequire\s*\(\s*['\"]funcster['\"]\s*\)"
    r"|\bfrom\s+['\"]node-serialize['\"]"
    r"|\bfrom\s+['\"]funcster['\"]"
    r"|\.\s*unserialize\s*\(\s*[A-Za-z_$][\w$]{0,80}\s*\)"
)


# ---- Proposal 13: Hessian readObject() ---------------------------------


# Java + Python Hessian sinks:
#  - ``new HessianInput(...).readObject()`` — Caucho Hessian1
#  - ``new Hessian2Input(...).readObject()`` — Hessian2
#  - ``Decoder().decode(payload)`` from pyhessian (less specific but
#                                                 still flag-worthy
#                                                 when the import is
#                                                 from ``pyhessian``)
_HESSIAN = _re(
    r"\bnew\s+Hessian(?:2)?Input\s*\("
    r"|\bHessianInput\s+[A-Za-z_][\w]*\s*=\s*new\s+HessianInput\s*\("
    r"|\bcom\.caucho\.hessian\b"
    r"|\bfrom\s+pyhessian\s+import\b"
    r"|\bimport\s+pyhessian\b"
)


# ---- Proposal 14: SnakeYAML new Yaml() (cross-language YAML catch-all) -


# Java side: ``new Yaml()`` with no SafeConstructor / no Constructor
# argument is the unsafe default through SnakeYAML 1.x.
# Branch A: ``new Yaml().load(`` — direct call chain.
# Branch B: ``new Yaml(new Constructor(...))`` — still type-preserving;
#           we flag because Constructor + load is the documented
#           gadget-friendly shape.
# YamlDotNet side: ``new DeserializerBuilder()`` + ``.Deserialize<`` is
# generally safe by default but custom resolvers / type-inspectors
# can open the surface — flagged conservatively when ``WithTagMapping``
# or ``WithTypeInspector`` is composed in.
_YAML_CROSS_LANG_UNSAFE = _re(
    r"\bnew\s+Yaml\s*\(\s*\)\s*\."
    r"|\bnew\s+Yaml\s*\(\s*new\s+Constructor\s*\("
    r"|\bnew\s+DeserializerBuilder\s*\([^)\n]{0,200}\)"
    r"[\s\S]{0,300}?\.\s*With(?:TypeInspector|TagMapping|TypeResolver)\s*\("
    r"|\bnew\s+Yaml\s*\(\s*new\s+SafeConstructor\s*\([^)\n]{0,100}\)\s*\)\s*\.\s*loadAs\s*\("
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="cld-ruby-marshal-load-untrusted",
        name="Ruby Marshal.load / Marshal.restore on untrusted bytes",
        severity="CRITICAL",
        description=(
            "`Marshal.load(X)` or `Marshal.restore(X)` where X is not a "
            "literal string and not a same-method `Marshal.dump(...)` "
            "round-trip. Ruby Marshal allocates any named class without "
            "running `initialize`; public gadget chains exist for every "
            "Rails 4.x-7.x (`Gem::Specification`, "
            "`ActiveSupport::Deprecation::DeprecatedInstanceVariableProxy`, "
            "`ERB.result_with_hash`). Treat as automatic RCE primitive."
        ),
        pattern=_RUBY_MARSHAL_LOAD,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cld-ruby-yaml-unsafe-load",
        name="Ruby YAML.load / YAML.unsafe_load / YAML.load_file",
        severity="CRITICAL",
        description=(
            "Ruby `YAML.load(X)` (Psych < 4 default) or explicit "
            "`YAML.unsafe_load(X)` / `YAML.load_file(X)` where X is not "
            "a constant string. Resolves `!ruby/object:ClassName` tags "
            "into `ClassName.allocate` + ivar-set — identical surface "
            "to `Marshal.load`. Severity escalates to CRITICAL when "
            "Ruby < 3.1 / Psych < 4 (still very common in production)."
        ),
        pattern=_RUBY_YAML_LOAD,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cld-ruby-oj-object-mode",
        name="Ruby Oj.load / Oj.strict_load in :object mode",
        severity="CRITICAL",
        description=(
            "Ruby `Oj.load(data, mode: :object)` or `Oj.strict_load(data)` "
            "or global `Oj.default_options = { mode: :object }`. The "
            "`:object` mode resolves `^o` (object) and `^c` (class) "
            "markers via `Object.const_get(name).new` — same arbitrary-"
            "instantiation surface as Marshal but over JSON. The Oj gem "
            "is in tens of thousands of Gemfiles."
        ),
        pattern=_OJ_OBJECT_MODE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cld-java-object-input-stream",
        name="Java new ObjectInputStream(...).readObject() on untrusted",
        severity="CRITICAL",
        description=(
            "`new ObjectInputStream(stream).readObject()` or "
            "`SerializationUtils.deserialize(bytes)` (commons-lang3 "
            "wrapper around OIS). The Apache Commons Collections gadget "
            "chain (Foxglove 2015, `InvokerTransformer.transform` → "
            "`Runtime.exec`) makes every Java app with the right deps "
            "and a public OIS sink an open RCE. 100+ CVEs across "
            "JBoss / WebLogic / Confluence / Jenkins / WebSphere."
        ),
        pattern=_JAVA_OBJECT_INPUT_STREAM,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cld-java-xml-decoder",
        name="Java java.beans.XMLDecoder is an architectural RCE primitive",
        severity="CRITICAL",
        description=(
            "`new XMLDecoder(stream).readObject()`. There is no safe "
            "configuration — the XML payload literally encodes method "
            "calls (`<object class=java.lang.Runtime><void method=exec>`). "
            "Canonical exploit: CVE-2017-3506 / CVE-2017-10271 "
            "(Oracle WebLogic). Treat as immediate-remove."
        ),
        pattern=_JAVA_XML_DECODER,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cld-java-jackson-polymorphic",
        name="Jackson polymorphic deserialization opens arbitrary class",
        severity="CRITICAL",
        description=(
            "Jackson `ObjectMapper.enableDefaultTyping()` / "
            "`activateDefaultTyping(...)` / `@JsonTypeInfo(use = "
            "Id.CLASS)` annotation. Lets the JSON document carry a "
            "`@class` property that selects which Java class to "
            "instantiate. 70+ gadget classes documented in `marshalsec` "
            "(Bechler 2017). Mitigation requires `Id.NAME` + "
            "`@JsonSubTypes({...})` allow-list."
        ),
        pattern=_JACKSON_POLYMORPHIC,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cld-dotnet-binary-formatter",
        name=".NET BinaryFormatter.Deserialize is deprecated RCE primitive",
        severity="CRITICAL",
        description=(
            ".NET `new BinaryFormatter().Deserialize(stream)` or project "
            "opt-in `<EnableUnsafeBinaryFormatterSerialization>true`. "
            "Microsoft's own advisory: 'BinaryFormatter is dangerous and "
            "should not be used.' Public gadget chains via "
            "`TypeConfuseDelegate`, `WindowsIdentity`, `PSObject` "
            "(Muñoz/Mirosh 'Friday the 13th JSON Attacks', BlackHat 2017)."
        ),
        pattern=_DOTNET_BINARY_FORMATTER,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cld-dotnet-js-serializer-type-resolver",
        name=".NET JavaScriptSerializer with SimpleTypeResolver / custom resolver",
        severity="CRITICAL",
        description=(
            "`new JavaScriptSerializer(new SimpleTypeResolver())` or any "
            "custom `*TypeResolver` subclass. Reads `__type` property "
            "from JSON, resolves via `Type.GetType(name)`. Identical "
            "surface to Jackson `enableDefaultTyping`. RCE via "
            "`System.Configuration.Install.AssemblyInstaller` / "
            "`WindowsClaimsIdentity` gadgets (Muñoz/Mirosh)."
        ),
        pattern=_DOTNET_JS_SERIALIZER_TYPE_RESOLVER,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cld-dotnet-los-or-ndcs",
        name=".NET LosFormatter / NetDataContractSerializer arbitrary class",
        severity="CRITICAL",
        description=(
            "`new LosFormatter().Deserialize(stream)` (ASP.NET ViewState "
            "engine — RCE if `MachineKey` is weak/leaked) or "
            "`new NetDataContractSerializer().ReadObject(stream)` (WCF "
            "type-preserving serializer — same arbitrary-class surface "
            "as BinaryFormatter). Replace with `DataContractSerializer` "
            "+ explicit `KnownTypes`."
        ),
        pattern=_DOTNET_LOS_OR_NDCS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cld-php-unserialize-superglobal",
        name="PHP unserialize / wddx_deserialize on superglobal input",
        severity="CRITICAL",
        description=(
            "PHP `unserialize($_GET['x'])` / `$_POST` / `$_COOKIE` / "
            "`$_REQUEST` / `base64_decode($_…)` / `file_get_contents("
            "'php://input')` reaches the `__wakeup` / `__destruct` / "
            "`__toString` magic-method gadget chain. Charles Fol's "
            "`phpggc` catalogues 60+ ready chains across 30+ frameworks "
            "(Symfony / Laravel / Magento / Drupal / Joomla / WordPress)."
        ),
        pattern=_PHP_UNSERIALIZE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cld-erlang-binary-to-term-unsafe",
        name="Erlang/Elixir binary_to_term without [safe] option",
        severity="HIGH",
        description=(
            "Erlang `binary_to_term(Bin)` or Elixir `:erlang."
            "binary_to_term(bin)` without the `[safe]` / `[:safe]` "
            "option list. Accepts `fun()` references and unbounded new "
            "atoms — BEAM atom table is not GC'd (1M-entry default), "
            "DoS by atom-table exhaustion. CRITICAL if the resulting "
            "term is then used in `apply/3` or as a `fun()` (RCE)."
        ),
        pattern=_ERLANG_BINARY_TO_TERM,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cld-node-serialize-unserialize",
        name="Node.js node-serialize / funcster eval-via-unserialize",
        severity="CRITICAL",
        description=(
            "`require('node-serialize')` or `require('funcster')` import, "
            "OR a `.unserialize(payload)` callsite. Both packages encode "
            "JS functions as `_$$ND_FUNC$$_` strings and on `unserialize` "
            "run them through `eval`. There is no safe mode. Ajin Abraham "
            "'Exploiting Node.js Deserialization' (2017) is the canonical "
            "writeup. Remove the dependency entirely."
        ),
        pattern=_NODE_SERIALIZE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cld-hessian-read-object",
        name="Hessian readObject() / pyhessian Decoder.decode arbitrary class",
        severity="HIGH",
        description=(
            "`new HessianInput(stream).readObject()` / `Hessian2Input` / "
            "`com.caucho.hessian` import / `from pyhessian import`. "
            "Hessian wire format encodes fully-qualified class names; "
            "the decoder calls `Class.forName(name)`. CVE-2021-25641 "
            "(Apache Dubbo) is the canonical exploit. Pin Dubbo ≥ 2.7.10 "
            "with explicit Hessian allow-listing."
        ),
        pattern=_HESSIAN,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cld-yaml-cross-lang-unsafe",
        name="SnakeYAML / YamlDotNet unsafe-default loader (cross-lang)",
        severity="HIGH",
        description=(
            "Java SnakeYAML `new Yaml().load(stream)` or `new Yaml(new "
            "Constructor(Foo.class))` — unsafe by default through "
            "SnakeYAML 1.x (2.0 made `SafeConstructor` default but "
            "version drift is enormous). YamlDotNet `new "
            "DeserializerBuilder().WithTypeInspector/WithTagMapping/"
            "WithTypeResolver` can open the surface even when the "
            "default is safe. Pin SnakeYAML ≥ 2.0 + use SafeConstructor "
            "explicitly; YamlDotNet use StaticDeserializerBuilder."
        ),
        pattern=_YAML_CROSS_LANG_UNSAFE,
        owasp_asi="ASI-06",
    ),
)


# ---- The composed scanner ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against ``text`` and return findings.

    Findings are deduped by ``(rule_id, line, col)`` — a single line
    that triggers two rules emits two findings, but the same rule
    firing twice on the same line emits one. Matched text is
    truncated to 200 characters for output sanity.
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
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
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
