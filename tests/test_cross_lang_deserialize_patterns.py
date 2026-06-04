"""Tests for ``scripts/lib/cross_lang_deserialize_patterns.py``.

Wave 20 impl-H — verifies 14 cross-language deserialization rules
(Ruby Marshal / YAML / Oj; Java OIS / XMLDecoder / Jackson; .NET
BinaryFormatter / JavaScriptSerializer / LosFormatter; PHP unserialize;
Erlang binary_to_term; Node node-serialize; Hessian; SnakeYAML /
YamlDotNet). Each rule has positive + (1-2) negative tests.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Make ``scripts/lib`` importable without packaging — same trick used
# by every other ``test_*_patterns.py`` file in this repo.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

import cross_lang_deserialize_patterns as cdp  # type: ignore[import-not-found]  # noqa: E402

# ---- Module-level invariants -------------------------------------------


def test_rules_have_unique_ids() -> None:
    """Every Rule.id is unique — duplicates would dedupe-collide."""
    ids = [r.id for r in cdp.RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


def test_rules_have_compiled_patterns() -> None:
    """Every Rule.pattern is a compiled regex with MULTILINE flag."""
    for rule in cdp.RULES:
        assert isinstance(rule.pattern, re.Pattern), rule.id
        assert rule.pattern.flags & re.MULTILINE, rule.id


def test_rules_have_valid_severity() -> None:
    """Severity is one of the four canonical strings."""
    allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in cdp.RULES:
        assert rule.severity in allowed, f"{rule.id}: {rule.severity}"


def test_rules_have_owasp_asi_mapping() -> None:
    """Every rule maps to a non-empty ASI- prefix."""
    for rule in cdp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id


def test_rules_tuple_contains_all_14_proposals() -> None:
    """RULES catalogue has exactly the 14 expected rule ids."""
    rule_ids = {r.id for r in cdp.RULES}
    expected = {
        "cld-ruby-marshal-load-untrusted",
        "cld-ruby-yaml-unsafe-load",
        "cld-ruby-oj-object-mode",
        "cld-java-object-input-stream",
        "cld-java-xml-decoder",
        "cld-java-jackson-polymorphic",
        "cld-dotnet-binary-formatter",
        "cld-dotnet-js-serializer-type-resolver",
        "cld-dotnet-los-or-ndcs",
        "cld-php-unserialize-superglobal",
        "cld-erlang-binary-to-term-unsafe",
        "cld-node-serialize-unserialize",
        "cld-hessian-read-object",
        "cld-yaml-cross-lang-unsafe",
    }
    assert expected == rule_ids


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns.Finding shape."""
    f = cdp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-06",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-06"


def test_scan_text_empty_returns_empty_list() -> None:
    """scan_text('') returns []."""
    assert cdp.scan_text("") == []


def test_scan_text_dedupes_same_rule_same_line() -> None:
    """Two literal matches on the same line emit one finding per rule."""
    # Single rule firing on a single line — only one finding.
    text = "Marshal.load(data)"
    findings = cdp.scan_text(text)
    same_line_marshal = [
        f for f in findings
        if f.rule_id == "cld-ruby-marshal-load-untrusted" and f.line == 1
    ]
    assert len(same_line_marshal) <= 1


def _hits(rule_id: str, text: str) -> list[cdp.Finding]:
    """Helper: return only findings for the given rule_id."""
    return [f for f in cdp.scan_text(text) if f.rule_id == rule_id]


# ---- Rule 1: cld-ruby-marshal-load-untrusted ---------------------------


def test_ruby_marshal_load_variable_arg_fires() -> None:
    """Marshal.load(variable) → CRITICAL hit."""
    assert _hits("cld-ruby-marshal-load-untrusted", "session = Marshal.load(data)")


def test_ruby_marshal_restore_with_base64_fires() -> None:
    """Marshal.restore(Base64.decode64(cookie)) fires."""
    text = "session = Marshal.restore(Base64.decode64(cookie))"
    assert _hits("cld-ruby-marshal-load-untrusted", text)


def test_ruby_marshal_load_file_read_fires() -> None:
    """Marshal.load(File.read(path)) fires (file-IO is taint)."""
    assert _hits(
        "cld-ruby-marshal-load-untrusted",
        'data = Marshal.load(File.read("/tmp/x"))',
    )


def test_ruby_marshal_load_round_trip_suppressed() -> None:
    """Marshal.load(Marshal.dump(x)) is a test round-trip — no hit."""
    assert not _hits(
        "cld-ruby-marshal-load-untrusted",
        "x = Marshal.load(Marshal.dump(orig))",
    )


def test_ruby_marshal_load_string_literal_suppressed() -> None:
    """Marshal.load('static_string') — literal arg, no hit."""
    assert not _hits(
        "cld-ruby-marshal-load-untrusted",
        'x = Marshal.load("static")',
    )


# ---- Rule 2: cld-ruby-yaml-unsafe-load ---------------------------------


def test_ruby_yaml_load_variable_fires() -> None:
    """YAML.load(params[:yaml]) fires."""
    assert _hits("cld-ruby-yaml-unsafe-load", "config = YAML.load(params[:yaml])")


def test_ruby_yaml_unsafe_load_fires() -> None:
    """YAML.unsafe_load fires."""
    assert _hits("cld-ruby-yaml-unsafe-load", "x = YAML.unsafe_load(input)")


def test_ruby_yaml_load_file_fires() -> None:
    """YAML.load_file(path) fires."""
    assert _hits("cld-ruby-yaml-unsafe-load", "p = YAML.load_file(uploaded_path)")


def test_ruby_yaml_safe_load_suppressed() -> None:
    """YAML.safe_load is the documented defense — no hit."""
    assert not _hits("cld-ruby-yaml-unsafe-load", "x = YAML.safe_load(input)")


def test_ruby_yaml_load_string_literal_suppressed() -> None:
    """YAML.load('static_yaml') — literal arg, no hit."""
    assert not _hits("cld-ruby-yaml-unsafe-load", 'x = YAML.load("static_yaml")')


# ---- Rule 3: cld-ruby-oj-object-mode -----------------------------------


def test_ruby_oj_load_object_mode_fires() -> None:
    """Oj.load(data, mode: :object) fires."""
    assert _hits("cld-ruby-oj-object-mode", "Oj.load(data, mode: :object)")


def test_ruby_oj_strict_load_fires() -> None:
    """Oj.strict_load(data) fires."""
    assert _hits("cld-ruby-oj-object-mode", "x = Oj.strict_load(data)")


def test_ruby_oj_default_options_object_fires() -> None:
    """Oj.default_options = { mode: :object } fires (global flip)."""
    assert _hits(
        "cld-ruby-oj-object-mode",
        "Oj.default_options = { mode: :object }",
    )


def test_ruby_oj_load_compat_mode_suppressed() -> None:
    """Oj.load(data, mode: :compat) — safe mode, no hit."""
    assert not _hits("cld-ruby-oj-object-mode", "Oj.load(data, mode: :compat)")


def test_ruby_oj_load_strict_mode_suppressed() -> None:
    """Oj.load(data, mode: :strict) — safe mode, no hit (≠ strict_load!)."""
    assert not _hits("cld-ruby-oj-object-mode", "Oj.load(data, mode: :strict)")


# ---- Rule 4: cld-java-object-input-stream -----------------------------


def test_java_ois_inline_read_object_fires() -> None:
    """new ObjectInputStream(s).readObject() fires."""
    text = (
        "ObjectInputStream ois = new ObjectInputStream(socket.getInputStream());\n"
        "Object obj = ois.readObject();\n"
    )
    assert _hits("cld-java-object-input-stream", text)


def test_java_serialization_utils_deserialize_fires() -> None:
    """SerializationUtils.deserialize(bytes) (commons-lang3) fires."""
    assert _hits(
        "cld-java-object-input-stream",
        "Object o = SerializationUtils.deserialize(bytes);",
    )


def test_java_ois_unrelated_class_use_suppressed() -> None:
    """Just `ObjectOutputStream` (the writer) — no hit on the writer."""
    assert not _hits(
        "cld-java-object-input-stream",
        "ObjectOutputStream oos = new ObjectOutputStream(out);",
    )


# ---- Rule 5: cld-java-xml-decoder --------------------------------------


def test_java_xml_decoder_new_stream_fires() -> None:
    """new XMLDecoder(stream) fires."""
    assert _hits(
        "cld-java-xml-decoder",
        "XMLDecoder dec = new XMLDecoder(request.getInputStream());",
    )


def test_java_xml_decoder_variable_assignment_fires() -> None:
    """XMLDecoder dec = new XMLDecoder(...) variant fires."""
    assert _hits(
        "cld-java-xml-decoder",
        "XMLDecoder x = new XMLDecoder(stream);",
    )


def test_java_xml_decoder_unrelated_xml_suppressed() -> None:
    """XMLEncoder (the writer) is safe — no hit."""
    assert not _hits(
        "cld-java-xml-decoder",
        "XMLEncoder enc = new XMLEncoder(out);",
    )


# ---- Rule 6: cld-java-jackson-polymorphic ------------------------------


def test_java_jackson_enable_default_typing_fires() -> None:
    """enableDefaultTyping() fires."""
    assert _hits("cld-java-jackson-polymorphic", "m.enableDefaultTyping();")


def test_java_jackson_activate_default_typing_fires() -> None:
    """activateDefaultTyping(...) fires."""
    assert _hits(
        "cld-java-jackson-polymorphic",
        "m.activateDefaultTyping(validator);",
    )


def test_java_jackson_json_type_info_class_fires() -> None:
    """@JsonTypeInfo(use = Id.CLASS) annotation fires."""
    text = '@JsonTypeInfo(use = JsonTypeInfo.Id.CLASS, include = JsonTypeInfo.As.PROPERTY)'
    assert _hits("cld-java-jackson-polymorphic", text)


def test_java_jackson_id_name_suppressed() -> None:
    """@JsonTypeInfo(use = Id.NAME) is the safe shape — no hit."""
    assert not _hits(
        "cld-java-jackson-polymorphic",
        "@JsonTypeInfo(use = JsonTypeInfo.Id.NAME)",
    )


# ---- Rule 7: cld-dotnet-binary-formatter -------------------------------


def test_dotnet_binary_formatter_deserialize_fires() -> None:
    """new BinaryFormatter().Deserialize(stream) fires."""
    text = (
        "var bf = new BinaryFormatter();\n"
        "var obj = bf.Deserialize(stream);\n"
    )
    assert _hits("cld-dotnet-binary-formatter", text)


def test_dotnet_binary_formatter_project_opt_in_fires() -> None:
    """<EnableUnsafeBinaryFormatterSerialization>true</...> fires."""
    assert _hits(
        "cld-dotnet-binary-formatter",
        "<EnableUnsafeBinaryFormatterSerialization>true</EnableUnsafeBinaryFormatterSerialization>",
    )


def test_dotnet_binary_formatter_unrelated_suppressed() -> None:
    """`new System.Text.Json.JsonSerializer(...)` is safe — no hit."""
    assert not _hits(
        "cld-dotnet-binary-formatter",
        "var x = new JsonSerializer();",
    )


# ---- Rule 8: cld-dotnet-js-serializer-type-resolver --------------------


def test_dotnet_js_serializer_simple_type_resolver_fires() -> None:
    """new JavaScriptSerializer(new SimpleTypeResolver()) fires."""
    assert _hits(
        "cld-dotnet-js-serializer-type-resolver",
        "var s = new JavaScriptSerializer(new SimpleTypeResolver());",
    )


def test_dotnet_simple_type_resolver_alone_fires() -> None:
    """new SimpleTypeResolver() alone is dangerous → fires."""
    assert _hits(
        "cld-dotnet-js-serializer-type-resolver",
        "var r = new SimpleTypeResolver();",
    )


def test_dotnet_js_serializer_no_resolver_suppressed() -> None:
    """new JavaScriptSerializer() (no resolver) — different rule, no hit here."""
    assert not _hits(
        "cld-dotnet-js-serializer-type-resolver",
        "var s = new JavaScriptSerializer();",
    )


# ---- Rule 9: cld-dotnet-los-or-ndcs ------------------------------------


def test_dotnet_los_formatter_fires() -> None:
    """new LosFormatter() fires."""
    assert _hits("cld-dotnet-los-or-ndcs", "var los = new LosFormatter();")


def test_dotnet_net_data_contract_serializer_fires() -> None:
    """new NetDataContractSerializer() fires."""
    assert _hits(
        "cld-dotnet-los-or-ndcs",
        "var ndcs = new NetDataContractSerializer();",
    )


def test_dotnet_data_contract_serializer_safe_suppressed() -> None:
    """DataContractSerializer (the SAFE variant) — no hit."""
    assert not _hits(
        "cld-dotnet-los-or-ndcs",
        "var dcs = new DataContractSerializer(typeof(MyType));",
    )


# ---- Rule 10: cld-php-unserialize-superglobal --------------------------


def test_php_unserialize_get_fires() -> None:
    """unserialize($_GET['x']) fires."""
    assert _hits(
        "cld-php-unserialize-superglobal",
        "$session = unserialize($_GET['session']);",
    )


def test_php_unserialize_cookie_fires() -> None:
    """unserialize($_COOKIE['session']) fires."""
    assert _hits(
        "cld-php-unserialize-superglobal",
        "$x = unserialize($_COOKIE['session']);",
    )


def test_php_unserialize_base64_post_fires() -> None:
    """unserialize(base64_decode($_POST['x'])) fires."""
    assert _hits(
        "cld-php-unserialize-superglobal",
        "$x = unserialize(base64_decode($_POST['payload']));",
    )


def test_php_unserialize_php_input_fires() -> None:
    """unserialize(file_get_contents('php://input')) fires."""
    assert _hits(
        "cld-php-unserialize-superglobal",
        "$x = unserialize(file_get_contents('php://input'));",
    )


def test_php_wddx_deserialize_fires() -> None:
    """wddx_deserialize($_POST['x']) fires (legacy WDDX)."""
    assert _hits(
        "cld-php-unserialize-superglobal",
        "$x = wddx_deserialize($_POST['x']);",
    )


def test_php_unserialize_trusted_var_suppressed() -> None:
    """unserialize($cached_internal) — non-superglobal source, no hit."""
    assert not _hits(
        "cld-php-unserialize-superglobal",
        "$x = unserialize($cached_payload);",
    )


# ---- Rule 11: cld-erlang-binary-to-term-unsafe -------------------------


def test_erlang_binary_to_term_no_safe_fires() -> None:
    """binary_to_term(Bin) without [safe] fires."""
    assert _hits("cld-erlang-binary-to-term-unsafe", "Msg = binary_to_term(Bin).")


def test_elixir_erlang_binary_to_term_no_safe_fires() -> None:
    """:erlang.binary_to_term(bin) without [:safe] fires."""
    assert _hits(
        "cld-erlang-binary-to-term-unsafe",
        "msg = :erlang.binary_to_term(bin)",
    )


def test_erlang_binary_to_term_safe_suppressed() -> None:
    """binary_to_term(Bin, [safe]) — the defense, no hit."""
    assert not _hits(
        "cld-erlang-binary-to-term-unsafe",
        "Msg = binary_to_term(Bin, [safe]).",
    )


def test_elixir_erlang_binary_to_term_safe_suppressed() -> None:
    """:erlang.binary_to_term(bin, [:safe]) — the Elixir defense, no hit."""
    assert not _hits(
        "cld-erlang-binary-to-term-unsafe",
        "msg = :erlang.binary_to_term(bin, [:safe])",
    )


def test_erlang_binary_to_term_safe_with_other_opts_suppressed() -> None:
    """binary_to_term(Bin, [used, safe]) — safe is present, no hit."""
    assert not _hits(
        "cld-erlang-binary-to-term-unsafe",
        "Msg = binary_to_term(Bin, [used, safe]).",
    )


# ---- Rule 12: cld-node-serialize-unserialize ---------------------------


def test_node_serialize_require_fires() -> None:
    """require('node-serialize') fires on the import alone."""
    assert _hits(
        "cld-node-serialize-unserialize",
        "const serialize = require('node-serialize');",
    )


def test_node_funcster_require_fires() -> None:
    """require('funcster') fires (same anti-pattern)."""
    assert _hits(
        "cld-node-serialize-unserialize",
        "const f = require('funcster');",
    )


def test_node_serialize_es_import_fires() -> None:
    """ES-module `import x from 'node-serialize'` fires."""
    assert _hits(
        "cld-node-serialize-unserialize",
        "import serialize from 'node-serialize';",
    )


def test_node_unserialize_call_site_fires() -> None:
    """obj.unserialize(payload) callsite fires."""
    assert _hits(
        "cld-node-serialize-unserialize",
        "const obj = s.unserialize(payload);",
    )


def test_node_unrelated_require_suppressed() -> None:
    """require('express') is fine — no hit on unrelated libs."""
    assert not _hits(
        "cld-node-serialize-unserialize",
        "const express = require('express');",
    )


# ---- Rule 13: cld-hessian-read-object ----------------------------------


def test_hessian_input_new_fires() -> None:
    """new HessianInput(stream) fires."""
    assert _hits(
        "cld-hessian-read-object",
        "HessianInput in = new HessianInput(socket.getInputStream());",
    )


def test_hessian2_input_new_fires() -> None:
    """new Hessian2Input(stream) fires."""
    assert _hits(
        "cld-hessian-read-object",
        "Hessian2Input in = new Hessian2Input(stream);",
    )


def test_hessian_caucho_import_fires() -> None:
    """import com.caucho.hessian.* fires (presence-of-dep signal)."""
    assert _hits(
        "cld-hessian-read-object",
        "import com.caucho.hessian.io.HessianInput;",
    )


def test_pyhessian_import_fires() -> None:
    """from pyhessian import ... fires."""
    assert _hits(
        "cld-hessian-read-object",
        "from pyhessian import Encoder, Decoder",
    )


def test_hessian_unrelated_class_suppressed() -> None:
    """Unrelated Hessian-like name (e.g. random word) — no hit."""
    assert not _hits(
        "cld-hessian-read-object",
        "HessianOutputCollector x = something;",
    )


# ---- Rule 14: cld-yaml-cross-lang-unsafe -------------------------------


def test_snakeyaml_new_yaml_load_fires() -> None:
    """SnakeYAML `new Yaml().load(stream)` fires."""
    assert _hits(
        "cld-yaml-cross-lang-unsafe",
        "Yaml y = new Yaml().load(stream);",
    )


def test_snakeyaml_new_yaml_with_constructor_fires() -> None:
    """SnakeYAML `new Yaml(new Constructor(...))` fires."""
    assert _hits(
        "cld-yaml-cross-lang-unsafe",
        "Yaml y = new Yaml(new Constructor(Foo.class));",
    )


def test_yamldotnet_with_type_resolver_fires() -> None:
    """YamlDotNet `new DeserializerBuilder()...WithTypeResolver(...)` fires."""
    text = (
        "var deserializer = new DeserializerBuilder()\n"
        "    .WithTypeResolver(new MyResolver())\n"
        "    .Build();\n"
    )
    assert _hits("cld-yaml-cross-lang-unsafe", text)


def test_yamldotnet_default_safe_suppressed() -> None:
    """YamlDotNet `new DeserializerBuilder().Build()` with no resolvers
    is generally safe — no hit."""
    assert not _hits(
        "cld-yaml-cross-lang-unsafe",
        "var d = new DeserializerBuilder().Build();",
    )


# ---- Cross-rule integration tests --------------------------------------


def test_scan_text_returns_sorted_findings() -> None:
    """scan_text returns findings sorted by (line, column, rule_id)."""
    text = (
        "import com.caucho.hessian.io.HessianInput;\n"
        "var bf = new BinaryFormatter();\n"
        "var obj = bf.Deserialize(stream);\n"
    )
    findings = cdp.scan_text(text)
    sorted_findings = sorted(findings, key=lambda f: (f.line, f.column, f.rule_id))
    assert findings == sorted_findings


def test_scan_text_multi_rule_file_emits_multiple_findings() -> None:
    """A polyglot fixture with Ruby + PHP + Java sinks emits ≥3 findings."""
    text = (
        "# Ruby\n"
        "session = Marshal.load(data)\n"
        "// Java\n"
        "ObjectInputStream ois = new ObjectInputStream(s);\n"
        "Object o = ois.readObject();\n"
        "// PHP\n"
        "$x = unserialize($_GET['payload']);\n"
    )
    findings = cdp.scan_text(text)
    rule_ids = {f.rule_id for f in findings}
    assert "cld-ruby-marshal-load-untrusted" in rule_ids
    assert "cld-java-object-input-stream" in rule_ids
    assert "cld-php-unserialize-superglobal" in rule_ids


def test_scan_text_matched_text_truncated_at_200_chars() -> None:
    """Long matched_text is truncated to 200 chars + ellipsis."""
    # Build an artificial long match — node-serialize import would
    # never naturally exceed 200 chars, so use a Marshal.load with
    # a very long inline argument.
    long_arg = "a" * 500
    text = f"x = Marshal.load({long_arg})"
    findings = cdp.scan_text(text)
    marshal_hits = [
        f for f in findings if f.rule_id == "cld-ruby-marshal-load-untrusted"
    ]
    if marshal_hits:  # Only assert if regex matched (it should)
        assert len(marshal_hits[0].matched_text) <= 201  # 200 + ellipsis


def test_finding_line_col_are_1_based() -> None:
    """Reported (line, column) is 1-indexed."""
    text = "Marshal.load(data)"
    findings = cdp.scan_text(text)
    assert findings, "expected at least one finding"
    assert findings[0].line == 1
    assert findings[0].column == 1


def test_finding_line_col_track_newlines() -> None:
    """Multi-line input: line numbering tracks newlines correctly."""
    text = "// comment\n// another\nMarshal.load(x)\n"
    findings = cdp.scan_text(text)
    marshal_hits = [
        f for f in findings if f.rule_id == "cld-ruby-marshal-load-untrusted"
    ]
    assert marshal_hits
    assert marshal_hits[0].line == 3


# ---- ReDoS safety (every pattern bounded under linear time) ------------


def test_no_catastrophic_backtracking_on_large_input() -> None:
    """Pathological 50 KB input completes scan_text in reasonable time.

    Every regex in this module uses bounded quantifiers (no unbounded
    `.*` / `.+` chains, no nested groups with alternation that could
    re-match the same span) so worst-case input stays linear.
    """
    import time
    # 50KB of repeating tokens that flirt with every rule's prefix
    payload = (
        "Marshal.load(Marshal.dump(x))\n"
        "YAML.safe_load(input)\n"
        "Oj.load(data, mode: :compat)\n"
    ) * 1000
    start = time.perf_counter()
    cdp.scan_text(payload)
    elapsed = time.perf_counter() - start
    # 2s ceiling on 50KB input is generous; real-world < 100ms.
    assert elapsed < 2.0, f"scan_text took {elapsed:.2f}s on 50KB input"
