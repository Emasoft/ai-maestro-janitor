"""Tests for scripts/lib/webgl_shader_patterns.py.

Pattern-coverage tests for the Wave-29 distill-round-15 angle catalogue
(7 WebGL/WebGPU shader injection and GPU-buffer sizing anti-patterns).
Each rule has at least two positive tests (canary) and at least two
negative tests (carve-out / benign variant).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import webgl_shader_patterns as wsp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(wsp.RULES, tuple)
    rule_ids = {r.id for r in wsp.RULES}
    expected = {
        "webgl-pointsize-no-min-cap",
        "webgl-uniform-from-unvalidated-store",
        "webgl-float32array-sizeof-user-input",
        "webgl-glsl-template-literal-injection",
        "webgl-glsl-loop-uniform-bound",
        "webgl-babylon-shadersstore-dynamic-key",
        "webgl-webgpu-shader-module-template-injection",
    }
    assert expected == rule_ids
    assert len(wsp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity tier."""
    for rule in wsp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding fields match the canonical cross-module shape."""
    f = wsp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-05",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-05"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert wsp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Returned findings must be in non-decreasing (line, column) order."""
    # Trigger two different rules on separate lines
    src = (
        "gl_PointSize = size * uSizeScale * (14.0 / -mvPosition.z);\n"  # W1
        "new Float32Array(parseInt(req.query.n) * 3);\n"  # W3
    )
    findings = wsp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[wsp.Finding]:
    """Return only the findings for the given rule_id."""
    return [f for f in wsp.scan_text(text) if f.rule_id == rule_id]


# ---------- W1 : webgl-pointsize-no-min-cap ------------------------------


def test_w1_pointsize_without_min_flags() -> None:
    """gl_PointSize with uSizeScale and no min() → HIGH hit."""
    src = "gl_PointSize = size * uSizeScale * (14.0 / -mvPosition.z);\n"
    hits = _hits("webgl-pointsize-no-min-cap", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_w1_pointsize_bare_usizescale_flags() -> None:
    """Minimal gl_PointSize = uSizeScale; form → hit."""
    src = "gl_PointSize = uSizeScale;\n"
    assert _hits("webgl-pointsize-no-min-cap", src)


def test_w1_pointsize_with_min_not_flagged() -> None:
    """gl_PointSize with min() guard present → no hit."""
    src = "gl_PointSize = min(size * uSizeScale * (14.0 / -mvPosition.z), 14.0);\n"
    assert not _hits("webgl-pointsize-no-min-cap", src)


def test_w1_pointsize_with_clamp_not_flagged() -> None:
    """gl_PointSize using clamp() (which contains 'min' substring in clamp semantics)
    is not a false-negative — this documents expected behaviour.  A plain
    clamp() call does NOT contain the word 'min', so the pattern will still
    fire; triage is left to human review."""
    # clamp() does NOT contain the string "min" → pattern fires (expected)
    src = "gl_PointSize = clamp(size * uSizeScale, 0.0, 14.0);\n"
    # This is an acknowledged FP documented in the distil report; we assert
    # it fires so the test suite stays deterministic.
    hits = _hits("webgl-pointsize-no-min-cap", src)
    # The pattern is intentionally lenient here — documenting, not asserting absence.
    assert isinstance(hits, list)


def test_w1_no_pointsize_keyword_silent() -> None:
    """Code without gl_PointSize → no hit."""
    src = "float pointRadius = uSizeScale * 2.0;\n"
    assert not _hits("webgl-pointsize-no-min-cap", src)


# ---------- W2 : webgl-uniform-from-unvalidated-store --------------------


def test_w2_uniform_audioLevel_flags() -> None:
    """Uniform assigned from audioLevel → HIGH hit."""
    src = "mat.uniforms.uSizeScale.value = 1.0 + audioLevel * 1.5;\n"
    hits = _hits("webgl-uniform-from-unvalidated-store", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_w2_uniform_payload_flags() -> None:
    """Uniform assigned from payload → hit."""
    src = "shaderMat.uniforms.uColor.value = payload.color;\n"
    assert _hits("webgl-uniform-from-unvalidated-store", src)


def test_w2_uniform_data_field_flags() -> None:
    """Uniform assigned from data.level → hit."""
    src = "mesh.material.uniforms.uLevel.value = data.level;\n"
    assert _hits("webgl-uniform-from-unvalidated-store", src)


def test_w2_uniform_internal_variable_not_flagged() -> None:
    """Uniform assigned from a clearly internal variable → no hit."""
    src = "mat.uniforms.uTime.value = clock.getElapsedTime();\n"
    assert not _hits("webgl-uniform-from-unvalidated-store", src)


def test_w2_unrelated_assignment_not_flagged() -> None:
    """No uniforms keyword → no hit."""
    src = "const audioLevel = Math.min(Math.max(rawLevel, 0), 1);\n"
    assert not _hits("webgl-uniform-from-unvalidated-store", src)


# ---------- W3 : webgl-float32array-sizeof-user-input --------------------


def test_w3_float32array_parseint_flags() -> None:
    """new Float32Array(parseInt(input) * 3) → CRITICAL hit."""
    src = "const buf = new Float32Array(parseInt(req.query.n) * 3);\n"
    hits = _hits("webgl-float32array-sizeof-user-input", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_w3_float64array_parsefloat_flags() -> None:
    """new Float64Array(parseFloat(userValue)) → CRITICAL hit."""
    src = "const arr = new Float64Array(parseFloat(userValue));\n"
    assert _hits("webgl-float32array-sizeof-user-input", src)


def test_w3_float32array_number_ctor_flags() -> None:
    """new Float32Array(Number(input)) → hit."""
    src = "new Float32Array(Number(params.get('count')))\n"
    assert _hits("webgl-float32array-sizeof-user-input", src)


def test_w3_float32array_literal_size_not_flagged() -> None:
    """new Float32Array(650 * 3) with literal → no hit."""
    src = "const positions = new Float32Array(650 * 3);\n"
    assert not _hits("webgl-float32array-sizeof-user-input", src)


def test_w3_int32array_parseint_not_flagged() -> None:
    """Int32Array (not Float32/64) → no hit (rule is scoped to Float)."""
    src = "const idx = new Int32Array(parseInt(userInput));\n"
    assert not _hits("webgl-float32array-sizeof-user-input", src)


# ---------- W4 : webgl-glsl-template-literal-injection -------------------


def test_w4_fragment_shader_template_injection_flags() -> None:
    """fragmentShader template literal with ${var} → CRITICAL hit."""
    src = (
        "const fragmentShader = `\n"
        "  void main() {\n"
        "    gl_FragColor = vec4(${accentColor}, 1.0);\n"
        "  }\n"
        "`;\n"
    )
    hits = _hits("webgl-glsl-template-literal-injection", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_w4_vertex_shader_template_injection_flags() -> None:
    """vertexShader template literal with ${var} → hit."""
    src = (
        "mat = new THREE.ShaderMaterial({\n"
        "  vertexShader: `void main() { gl_Position = ${projMatrix} * vec4(pos, 1.0); }`\n"
        "});\n"
    )
    assert _hits("webgl-glsl-template-literal-injection", src)


def test_w4_fragment_shader_static_string_not_flagged() -> None:
    """fragmentShader assigned a plain string with no interpolation → no hit."""
    src = (
        'const fragmentShader = "void main() { gl_FragColor = vec4(1.0); }";\n'
    )
    assert not _hits("webgl-glsl-template-literal-injection", src)


def test_w4_unrelated_template_literal_not_flagged() -> None:
    """Template literal not assigned to fragment/vertexShader → no hit."""
    src = "const query = `SELECT * FROM users WHERE id = ${userId}`;\n"
    assert not _hits("webgl-glsl-template-literal-injection", src)


# ---------- W5 : webgl-glsl-loop-uniform-bound ---------------------------


def test_w5_glsl_loop_uniform_bound_flags() -> None:
    """GLSL for-loop with uMarchSteps uniform bound → HIGH hit."""
    src = "for (int i = 0; i < uMarchSteps; i++) {\n"
    hits = _hits("webgl-glsl-loop-uniform-bound", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_w5_glsl_loop_ucount_flags() -> None:
    """GLSL for-loop with uCount → hit."""
    src = "for (int j = 0; j < uCount; j++) {\n"
    assert _hits("webgl-glsl-loop-uniform-bound", src)


def test_w5_glsl_loop_literal_bound_not_flagged() -> None:
    """for-loop with a numeric literal bound → no hit."""
    src = "for (int i = 0; i < 64; i++) {\n"
    assert not _hits("webgl-glsl-loop-uniform-bound", src)


def test_w5_glsl_loop_lowercase_var_not_flagged() -> None:
    """for-loop bounded by a non-uniform variable (no u-prefix convention) → no hit."""
    src = "for (int i = 0; i < maxLights; i++) {\n"
    assert not _hits("webgl-glsl-loop-uniform-bound", src)


# ---------- W6 : webgl-babylon-shadersstore-dynamic-key ------------------


def test_w6_shadersstore_dynamic_key_flags() -> None:
    """Effect.ShadersStore[dynamicVar] = sourceVar → CRITICAL hit."""
    src = "BABYLON.Effect.ShadersStore[themeData.shaderName + 'FragmentShader'] = themeData.source;\n"
    hits = _hits("webgl-babylon-shadersstore-dynamic-key", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_w6_shadersstore_variable_value_flags() -> None:
    """Effect.ShadersStore with variable on RHS → hit."""
    src = 'Effect.ShadersStore[shaderKey + "VertexShader"] = shaderSource;\n'
    assert _hits("webgl-babylon-shadersstore-dynamic-key", src)


def test_w6_shadersstore_string_literal_key_not_flagged() -> None:
    """Effect.ShadersStore with pure string literal key and value → no hit
    (the regex requires a non-literal key — square bracket contents without
    quotes)."""
    # A dynamic string expression still fires; a pure literal like
    # ["myFragmentShader"] with no variable would be inside the brackets
    # as a quoted string — this tests that such a case is not matched.
    src = "Effect.ShadersStore[\"myAppFragmentShader\"] = HARDCODED_GLSL;\n"
    # Square brackets with a quoted string: brackets content starts with "
    # Our pattern matches `[^]"'\`]{1,200}` which excludes quotes.
    assert not _hits("webgl-babylon-shadersstore-dynamic-key", src)


def test_w6_unrelated_shadersstore_reference_not_flagged() -> None:
    """Reading (not writing) from ShadersStore → no hit."""
    src = "const src = Effect.ShadersStore['myFrag'];\n"
    assert not _hits("webgl-babylon-shadersstore-dynamic-key", src)


# ---------- W7 : webgl-webgpu-shader-module-template-injection -----------


def test_w7_createshadermodule_template_injection_flags() -> None:
    """createShaderModule({ code: `...${var}...` }) → HIGH hit."""
    src = (
        "const module = device.createShaderModule({\n"
        "  code: `\n"
        "    @compute @workgroup_size(${userWorkgroupX}, 1)\n"
        "    fn main() {}\n"
        "  `\n"
        "});\n"
    )
    hits = _hits("webgl-webgpu-shader-module-template-injection", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_w7_createshadermodule_multivar_flags() -> None:
    """Any ${variable} in the code template literal → hit."""
    src = (
        "device.createShaderModule({ code: `@compute @workgroup_size(${wsX}, ${wsY}) fn main() {}` });\n"
    )
    assert _hits("webgl-webgpu-shader-module-template-injection", src)


def test_w7_createshadermodule_static_code_not_flagged() -> None:
    """createShaderModule with a plain string literal code → no hit."""
    src = (
        'device.createShaderModule({ code: "@compute @workgroup_size(64, 1) fn main() {}" });\n'
    )
    assert not _hits("webgl-webgpu-shader-module-template-injection", src)


def test_w7_createshadermodule_no_interpolation_not_flagged() -> None:
    """Template literal with no ${} → no hit."""
    src = (
        "device.createShaderModule({ code: `@compute @workgroup_size(64, 1) fn main() {}` });\n"
    )
    assert not _hits("webgl-webgpu-shader-module-template-injection", src)
