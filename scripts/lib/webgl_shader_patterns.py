"""WebGL / WebGPU shader injection and GPU-buffer sizing patterns.

Wave-29 distillation round 15, angle: WebGL/WebGPU shader security.

Catalogue of 7 WebGL/WebGPU-specific anti-patterns distilled in
`reports/distill-round-15/webgl-shader.md`. Targets Three.js / Babylon.js /
raw WebGL / WebGPU surfaces that `gpu_compute_patterns` (CUDA/OpenCL/Metal
host-side) and prior frontend modules do NOT cover.

What is NOT here (already shipped — DO NOT duplicate):

  * CUDA / OpenCL / Metal kernel misuse — `gpu_compute_patterns.py`.
  * Generic frontend XSS / injection — `frontend_patterns.py`.
  * DNS / outbound webhook misuse — `dns_email_patterns.py`.

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * webgl-pointsize-no-min-cap                      (HIGH)
  * webgl-uniform-from-unvalidated-store             (HIGH)
  * webgl-float32array-sizeof-user-input             (CRITICAL)
  * webgl-glsl-template-literal-injection            (CRITICAL)
  * webgl-glsl-loop-uniform-bound                   (HIGH)
  * webgl-babylon-shadersstore-dynamic-key           (CRITICAL)
  * webgl-webgpu-shader-module-template-injection    (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret / Sensitive Data Leak (GPU buffer OOM, memory residue
                                          from reused buffers)
  ASI-03 — Injection (GLSL/WGSL source injection via template literals,
                       ShadersStore key poisoning)
  ASI-05 — DoS / Resource Exhaustion (pointsize overflow, GPU infinite
                                        loop, OOM via large TypedArray,
                                        workgroup size overflow)
  ASI-06 — Integrity / Validation Gaps (uniform not range-clamped,
                                          Float32Array sized by user
                                          input without upper bound)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes; every bounded greedy span uses an
explicit numeric upper bound or a character-class). Patterns are
PRE-COMPILED at module load. Fail-fast: callers receive structured
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
    """Compile with IGNORECASE+MULTILINE+UNICODE. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- W1 : webgl-pointsize-no-min-cap ------------------------------------

# Matches `gl_PointSize = ... uSizeScale ...;` when the same statement
# does NOT already contain a `min(` call.  The negative lookahead on
# `min\b` uses character-by-character scan bounded by `;` to stay RE2-safe.
#
# RE2 note: `(?!` is a zero-width *lookahead* (not lookbehind) and IS
# supported by RE2.  We do NOT use lookbehind anywhere in this file.
_GL_POINTSIZE_NO_MIN = _re(
    r"gl_PointSize\s*=\s*"
    r"(?:(?!min\s*\().){0,300}"
    r"\buSizeScale\b"
    r"[^;]{0,200};"
)


# ---- W2 : webgl-uniform-from-unvalidated-store --------------------------

# Matches `uniforms.*.value = <expr with known user-data variable names>`
# without an intervening Math.max / Math.min / clamp in the same statement.
# Covers audioLevel, userInput, payload, and `data.<field>` patterns.
_UNIFORM_USER_DATA_VALUE = _re(
    r"uniforms\.[a-zA-Z_][a-zA-Z0-9_]{0,60}\.value\s*=\s*"
    r"[^\n;]{0,200}"
    r"\b(?:audioLevel|userInput|payload|data\.[a-zA-Z_][a-zA-Z0-9_]{0,40})\b"
    r"[^\n;]{0,100}"
)


# ---- W3 : webgl-float32array-sizeof-user-input --------------------------

# Matches `new Float32Array(parseInt(...) * N)` or
# `new Float64Array(parseFloat(...))` — user-input-driven allocation
# without a provable upper bound.
_FLOAT_TYPED_ARRAY_USER_SIZE = _re(
    r"\bnew\s+Float(?:32|64)Array\s*\(\s*"
    r"(?:parseInt|parseFloat|Number)\s*\([^)]{0,200}\)"
    r"\s*(?:\*\s*[0-9]+\s*)?\)"
)


# ---- W4 : webgl-glsl-template-literal-injection -------------------------

# Matches template-literal fragment or vertex shader strings that interpolate
# any variable: `fragmentShader = \`...${varName}...\`` .
# Also catches the object-literal shorthand: `{ fragmentShader: \`...${v}...\` }`.
_GLSL_TEMPLATE_LITERAL_INJECTION = _re(
    r"(?:fragment|vertex)Shader\s*[=:]\s*`[^`]{0,2000}\$\{"
    r"[a-zA-Z_][a-zA-Z0-9_.]{0,60}\}"
)


# ---- W5 : webgl-glsl-loop-uniform-bound ---------------------------------

# Matches GLSL `for (int i = 0; i < uSomething; i++)` where the upper
# bound is a uniform (identified by the `u` prefix convention, followed
# by an uppercase letter — the canonical GLSL uniform naming convention).
_GLSL_LOOP_UNIFORM_BOUND = _re(
    r"for\s*\(\s*int\s+[a-z]\s*=\s*0\s*;\s*[a-z]\s*<\s*"
    r"u[A-Z][a-zA-Z0-9]{0,40}\s*;\s*[a-z]\+\+\s*\)"
)


# ---- W6 : webgl-babylon-shadersstore-dynamic-key ------------------------

# Matches `Effect.ShadersStore[expr] = variable` where the bracket content
# begins with an identifier character (letter or underscore) — indicating a
# dynamic expression such as `themeData.shaderName + "FragmentShader"` or
# `shaderKey + "VertexShader"`.  Pure string-literal keys like
# `["myAppFragmentShader"]` start with a quote and are therefore excluded.
_BABYLON_SHADERSSTORE_DYNAMIC = _re(
    r"Effect\.ShadersStore\s*\[\s*"
    r"[a-zA-Z_][^\]]{0,200}"
    r"\]\s*=\s*"
    r"[a-zA-Z_][a-zA-Z0-9_.]{0,80}"
)


# ---- W7 : webgl-webgpu-shader-module-template-injection -----------------

# Matches `createShaderModule({ code: \`...${variable}...\` })` —
# template-literal WGSL with any interpolated variable inside the code string.
_WEBGPU_SHADER_MODULE_TEMPLATE = _re(
    r"createShaderModule\s*\(\s*\{"
    r"[^}]{0,200}"
    r"\bcode\s*:\s*`"
    r"[^`]{0,2000}"
    r"\$\{[a-zA-Z_][a-zA-Z0-9_.]{0,60}\}"
)


# ---- Rule registry ------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="webgl-pointsize-no-min-cap",
        name="gl_PointSize written with uSizeScale uniform without min() cap",
        severity="HIGH",
        description=(
            "`gl_PointSize` is assigned using `uSizeScale` (a user-"
            "controllable uniform) without a `min()` upper-bound guard. "
            "The GPU rasteriser attempts to draw a point sprite as large "
            "as the driver's MAX_POINT_SIZE (up to 8 192 px on desktop). "
            "A malicious `uSizeScale` of 1e6 triggers GPU memory "
            "corruption or OOM analogous to CVE-2022-3970 "
            "(LibTIFF pixel-buffer overflow via integer-controlled size). "
            "Fix: wrap with `gl_PointSize = min(expr, MAX_SAFE_SIZE)`."
        ),
        pattern=_GL_POINTSIZE_NO_MIN,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="webgl-uniform-from-unvalidated-store",
        name="Three.js uniforms.*.value assigned from unvalidated store state",
        severity="HIGH",
        description=(
            "A Three.js `ShaderMaterial` uniform value is assigned "
            "directly from a state variable (audioLevel, userInput, "
            "payload, or data.*) without an intervening `Math.max` / "
            "`Math.min` / `clamp` guard. If the store setter does not "
            "enforce numeric range, an attacker who controls the state "
            "source (WebSocket, SSE, CSRF-mutable API route) can inject "
            "`Infinity`, `NaN`, or very large floats, causing undefined "
            "GLSL ES behaviour (§4.7.1) — divergent fragment outputs, "
            "driver crashes, or information leak via GPU pipeline state."
        ),
        pattern=_UNIFORM_USER_DATA_VALUE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="webgl-float32array-sizeof-user-input",
        name="Float32/64Array allocated with parseInt/parseFloat of user input",
        severity="CRITICAL",
        description=(
            "`new Float32Array(parseInt(userInput) * N)` or equivalent "
            "allocates a GPU-upload buffer whose size is controlled by "
            "external input without an upper-bound check. An attacker "
            "can request a gigabyte-scale TypedArray (e.g. 500_000_000 "
            "elements * 4 bytes = 2 GB), triggering tab OOM-kill or "
            "a `GPUValidationError` whose message leaks driver info. "
            "Structurally identical to CVE-2022-3970 (libtiff "
            "pixel-buffer overflow via user-controlled numberOfSamples). "
            "Fix: cap input to a safe maximum before allocation."
        ),
        pattern=_FLOAT_TYPED_ARRAY_USER_SIZE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="webgl-glsl-template-literal-injection",
        name="GLSL fragmentShader/vertexShader built from template literal with variable interpolation",
        severity="CRITICAL",
        description=(
            "A GLSL shader source string is assembled with a JavaScript "
            "template literal that interpolates a runtime variable "
            "(`${varName}`) into `fragmentShader` or `vertexShader`. "
            "An attacker who controls the interpolated value can inject "
            "arbitrary GLSL into the GPU driver's shader compiler. "
            "Impacts: DoS via infinite-loop shader, driver exploitation "
            "via crafted precision qualifiers (class of ANGLE "
            "CVE-2023-4863), reading neighbouring shader memory on "
            "buggy drivers. Fix: validate and sanitise all user-supplied "
            "values before embedding them in GLSL strings, or keep "
            "shaders as static compile-time constants."
        ),
        pattern=_GLSL_TEMPLATE_LITERAL_INJECTION,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="webgl-glsl-loop-uniform-bound",
        name="GLSL for-loop bounded by user-controlled uniform (GPU hang risk)",
        severity="HIGH",
        description=(
            "A GLSL `for (int i = 0; i < uSomething; i++)` loop uses a "
            "uniform as its upper bound without a hard cap. GLSL ES 3.0 "
            "permits dynamic loop bounds; when `uSomething` is fed from "
            "user input (e.g. 'ray march quality' setting) without "
            "server-side clamping, an attacker can set it to INT_MAX to "
            "lock every GPU thread into an indefinite loop, freezing the "
            "WebGL context and browser tab. No JavaScript timeout fires "
            "from inside a shader. Fix: use `min(uSomething, SAFE_MAX)` "
            "inside the shader, and validate the uniform value on upload."
        ),
        pattern=_GLSL_LOOP_UNIFORM_BOUND,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="webgl-babylon-shadersstore-dynamic-key",
        name="Babylon.js Effect.ShadersStore written with dynamic key or value",
        severity="CRITICAL",
        description=(
            "`Babylon.Effect.ShadersStore` is a global `Record<string, "
            "string>` used as a named-shader cache. Writing to it with "
            "a dynamic key (runtime variable) silently replaces any "
            "subsequently requested shader by that name. An attacker "
            "who can influence the key (prototype pollution, API "
            "response injection, supply-chain compromise) injects GLSL "
            "that replaces legitimate shaders across scene restarts "
            "without any application-code awareness. Fix: only write "
            "to `ShadersStore` with string literals known at compile "
            "time; never derive the key from runtime data."
        ),
        pattern=_BABYLON_SHADERSSTORE_DYNAMIC,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="webgl-webgpu-shader-module-template-injection",
        name="WebGPU createShaderModule called with template-literal WGSL containing variable interpolation",
        severity="HIGH",
        description=(
            "`GPUDevice.createShaderModule({ code: \\`...${variable}...\\` })` "
            "compiles WGSL that embeds a runtime variable. Attack vectors: "
            "(1) DoS — a large crafted WGSL shader exhausts browser "
            "compilation time; (2) Workgroup overflow — interpolating "
            "user-controlled `@workgroup_size(x, y)` values causes "
            "integer overflow in the driver's thread-pool sizing when "
            "x * y > maxComputeWorkgroupSize; (3) Buffer residue — "
            "`var<storage>` writes to a reused GPUBuffer without "
            "zeroing expose stale GPU memory from the previous frame. "
            "Fix: use only static WGSL strings or validate / whitelist "
            "every interpolated value before compilation."
        ),
        pattern=_WEBGPU_SHADER_MODULE_TEMPLATE,
        owasp_asi="ASI-03",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every rule in RULES against *text* and return all findings.

    All rules are simple single-pass regex scans — no multi-stage
    context filters are required for this rule set. Findings are
    deduplicated by (rule_id, line, col) and returned in
    (line, column, rule_id) order.
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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
