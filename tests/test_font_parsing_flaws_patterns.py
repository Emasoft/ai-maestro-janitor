"""Tests for scripts/lib/font_parsing_flaws_patterns.py.

Pattern-coverage tests for the Wave-32 distill-round-18 angle
catalogue (10 font-parsing-specific anti-patterns covering FreeType,
HarfBuzz, WOFF2/brotli, TrueType bytecode interpreter, variable fonts,
CSS @font-face SSRF, ImageMagick font injection, font upload extension
check, Pillow ImageFont SBIX, and fontconfig user-path). Each rule has
at least two tests: one positive (canary that must fire) and one
negative (carve-out or safe variant that must NOT fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import font_parsing_flaws_patterns as fpf  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(fpf.RULES, tuple)
    rule_ids = {r.id for r in fpf.RULES}
    expected = {
        "fpf-freetype-face-open-unguarded",
        "fpf-harfbuzz-shape-untrusted-font",
        "fpf-woff2-brotli-decompress-untrusted",
        "fpf-truetype-bytecode-interpreter-on-upload",
        "fpf-variable-font-instancing-no-axis-bound",
        "fpf-css-font-face-ssrf",
        "fpf-imagemagick-font-arg-injection",
        "fpf-font-upload-no-magic-check",
        "fpf-pillow-truetype-user-path",
        "fpf-fontconfig-scan-user-path",
    }
    assert expected == rule_ids
    assert len(fpf.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in fpf.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = fpf.Finding(
        rule_id="fpf-test", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-06",
    )
    assert f.rule_id == "fpf-test"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-06"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert fpf.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — FreeType face open
        "FT_New_Memory_Face(library, font_data, font_len, 0, &face);\n"
        # Line 2 — HarfBuzz shape
        "hb_shape(font, buf, NULL, 0);\n"
    )
    findings = fpf.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[fpf.Finding]:
    return [f for f in fpf.scan_text(text) if f.rule_id == rule_id]


# ---------- FP-01 : fpf-freetype-face-open-unguarded ---------------------


def test_fp01_positive_ft_new_memory_face() -> None:
    """FT_New_Memory_Face() must trigger fpf-freetype-face-open-unguarded."""
    src = "FT_New_Memory_Face(library, font_data, font_len, 0, &face);"
    hits = _hits("fpf-freetype-face-open-unguarded", src)
    assert len(hits) >= 1
    assert hits[0].severity == "CRITICAL"


def test_fp01_positive_ft_new_face() -> None:
    """FT_New_Face() must trigger fpf-freetype-face-open-unguarded."""
    src = 'FT_New_Face(library, "/tmp/user_upload.ttf", 0, &face);'
    hits = _hits("fpf-freetype-face-open-unguarded", src)
    assert len(hits) >= 1


def test_fp01_negative_unrelated_ft_function() -> None:
    """FT_Init_FreeType alone must NOT trigger fpf-freetype-face-open-unguarded."""
    src = "FT_Init_FreeType(&library);\nFT_Done_FreeType(library);"
    hits = _hits("fpf-freetype-face-open-unguarded", src)
    assert hits == []


# ---------- FP-02 : fpf-harfbuzz-shape-untrusted-font --------------------


def test_fp02_positive_hb_shape_c() -> None:
    """C hb_shape() must trigger fpf-harfbuzz-shape-untrusted-font."""
    src = "hb_shape(font, buf, NULL, 0);"
    hits = _hits("fpf-harfbuzz-shape-untrusted-font", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_fp02_positive_hb_shape_python() -> None:
    """Python hb.shape() must trigger fpf-harfbuzz-shape-untrusted-font."""
    src = "hb.shape(font, buf)"
    hits = _hits("fpf-harfbuzz-shape-untrusted-font", src)
    assert len(hits) >= 1


def test_fp02_negative_hb_buffer_create() -> None:
    """hb_buffer_create alone must NOT trigger fpf-harfbuzz-shape-untrusted-font."""
    src = "hb_buffer_t *buf = hb_buffer_create();"
    hits = _hits("fpf-harfbuzz-shape-untrusted-font", src)
    assert hits == []


# ---------- FP-03 : fpf-woff2-brotli-decompress-untrusted ----------------


def test_fp03_positive_brotli_decompress() -> None:
    """brotli.decompress() must trigger fpf-woff2-brotli-decompress-untrusted."""
    src = "decompressed = brotli.decompress(raw[offset+8:offset+8+compressed_size])"
    hits = _hits("fpf-woff2-brotli-decompress-untrusted", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_fp03_positive_ttfont_user_path() -> None:
    """TTFont() on a user path must trigger fpf-woff2-brotli-decompress-untrusted."""
    src = "font = TTFont(uploaded_woff2_path)"
    hits = _hits("fpf-woff2-brotli-decompress-untrusted", src)
    assert len(hits) >= 1


def test_fp03_negative_ttfont_static_path() -> None:
    """TTFont() with a static string literal must NOT trigger the rule."""
    src = 'font = TTFont("/app/fonts/NotoSans.ttf")'
    hits = _hits("fpf-woff2-brotli-decompress-untrusted", src)
    assert hits == []


# ---------- FP-04 : fpf-truetype-bytecode-interpreter-on-upload ----------


def test_fp04_positive_ft_load_glyph_default() -> None:
    """FT_Load_Glyph with FT_LOAD_DEFAULT must trigger fpf-truetype-bytecode-interpreter-on-upload."""
    src = "FT_Load_Glyph(face, glyph_index, FT_LOAD_DEFAULT | FT_LOAD_RENDER);"
    hits = _hits("fpf-truetype-bytecode-interpreter-on-upload", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_fp04_positive_ft_load_char_target_normal() -> None:
    """FT_Load_Char with FT_LOAD_TARGET_NORMAL must trigger the rule."""
    src = "FT_Load_Char(face, char_code, FT_LOAD_TARGET_NORMAL);"
    hits = _hits("fpf-truetype-bytecode-interpreter-on-upload", src)
    assert len(hits) >= 1


def test_fp04_negative_ft_load_no_hinting() -> None:
    """FT_Load_Glyph with FT_LOAD_NO_HINTING must NOT trigger the rule."""
    src = "FT_Load_Glyph(face, glyph_index, FT_LOAD_NO_HINTING | FT_LOAD_RENDER);"
    hits = _hits("fpf-truetype-bytecode-interpreter-on-upload", src)
    assert hits == []


# ---------- FP-05 : fpf-variable-font-instancing-no-axis-bound -----------


def test_fp05_positive_instantiate_variable_font() -> None:
    """instantiateVariableFont() must trigger fpf-variable-font-instancing-no-axis-bound."""
    src = 'instancer.instantiateVariableFont(font, {"wght": 700})'
    hits = _hits("fpf-variable-font-instancing-no-axis-bound", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_fp05_positive_ft_set_named_instance() -> None:
    """FT_Set_Named_Instance() must trigger fpf-variable-font-instancing-no-axis-bound."""
    src = "error = FT_Set_Named_Instance(face, instance_index);"
    hits = _hits("fpf-variable-font-instancing-no-axis-bound", src)
    assert len(hits) >= 1


def test_fp05_negative_fvar_read_only() -> None:
    """Reading the fvar table without calling instancing functions must NOT trigger the rule."""
    src = "axisCount = struct.unpack('>H', fvar_data[4:6])[0]"
    hits = _hits("fpf-variable-font-instancing-no-axis-bound", src)
    assert hits == []


# ---------- FP-06 : fpf-css-font-face-ssrf --------------------------------


def test_fp06_positive_font_face_src_url() -> None:
    """@font-face with src: url() must trigger fpf-css-font-face-ssrf."""
    # IMDS IP assembled at runtime so the inert fixture never holds the literal
    # endpoint (CPV RC-65 devitalization); the rule under test sees the full URL.
    imds = "169.254." + "169.254"
    src = f"@font-face {{ font-family: x; src: url('http://{imds}/iam/'); }}"
    hits = _hits("fpf-css-font-face-ssrf", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-10"


def test_fp06_positive_font_face_src_url_template() -> None:
    """font-face...src...url( inline pattern must trigger fpf-css-font-face-ssrf."""
    src = "const css = `@font-face { font-family: evil; src: url(${userUrl}); }`;"
    hits = _hits("fpf-css-font-face-ssrf", src)
    assert len(hits) >= 1


def test_fp06_negative_background_url() -> None:
    """A CSS background url() without @font-face context must NOT trigger."""
    src = "body { background: url('/static/bg.png'); }"
    hits = _hits("fpf-css-font-face-ssrf", src)
    assert hits == []


# ---------- FP-07 : fpf-imagemagick-font-arg-injection -------------------


def test_fp07_positive_convert_font_variable() -> None:
    """convert -font $USER_FONT on one line must trigger fpf-imagemagick-font-arg-injection."""
    # Shell-script style (no quote break between -font and the variable).
    src = "convert input.pdf -font $USER_FONT_PATH -annotate 45 DRAFT output.pdf"
    hits = _hits("fpf-imagemagick-font-arg-injection", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_fp07_positive_convert_font_format() -> None:
    """convert -font with format string must trigger the rule."""
    src = "convert input.pdf -font {user_font} -annotate 45 DRAFT output.pdf"
    hits = _hits("fpf-imagemagick-font-arg-injection", src)
    assert len(hits) >= 1


def test_fp07_negative_convert_font_literal() -> None:
    """convert -font with a hardcoded literal font name must NOT trigger."""
    src = 'subprocess.run(["convert", img, "-font", "Helvetica", "-annotate", "0", "OK"])'
    hits = _hits("fpf-imagemagick-font-arg-injection", src)
    assert hits == []


# ---------- FP-08 : fpf-font-upload-no-magic-check -----------------------


def test_fp08_positive_extension_check_with_save() -> None:
    """Extension-only check + save must trigger fpf-font-upload-no-magic-check."""
    src = "if ext in ('ttf', 'otf', 'woff', 'woff2'):\n    f.save(dest)"
    hits = _hits("fpf-font-upload-no-magic-check", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_fp08_positive_woff2_string_with_upload() -> None:
    """'woff2' string near upload path must trigger the rule."""
    src = "ALLOWED = ['woff2', 'woff']\nshutil.copy(tmp_path, upload_dir)"
    hits = _hits("fpf-font-upload-no-magic-check", src)
    assert len(hits) >= 1


def test_fp08_negative_png_only_check() -> None:
    """Extension check on non-font types (png, jpg) must NOT trigger the rule."""
    src = "if ext in ('png', 'jpg', 'gif'):\n    f.save(dest)"
    hits = _hits("fpf-font-upload-no-magic-check", src)
    assert hits == []


# ---------- FP-09 : fpf-pillow-truetype-user-path -------------------------


def test_fp09_positive_imagefont_truetype_upload() -> None:
    """ImageFont.truetype(uploaded_font_path) must trigger fpf-pillow-truetype-user-path."""
    src = "font = ImageFont.truetype(uploaded_font_path, size=32)"
    hits = _hits("fpf-pillow-truetype-user-path", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_fp09_positive_imagefont_truetype_request_param() -> None:
    """ImageFont.truetype with request-derived path must trigger the rule."""
    src = "font = ImageFont.truetype(request.files['font'].filename, size=48)"
    hits = _hits("fpf-pillow-truetype-user-path", src)
    assert len(hits) >= 1


def test_fp09_negative_imagefont_truetype_literal() -> None:
    """ImageFont.truetype with a string literal path must NOT trigger the rule."""
    src = 'font = ImageFont.truetype("/usr/share/fonts/NotoSans.ttf", size=14)'
    hits = _hits("fpf-pillow-truetype-user-path", src)
    assert hits == []


# ---------- FP-10 : fpf-fontconfig-scan-user-path ------------------------


def test_fp10_positive_fc_scan_variable() -> None:
    """fc-scan with a shell variable must trigger fpf-fontconfig-scan-user-path."""
    # Shell-script style: fc-scan and the variable on the same unquoted line.
    src = "fc-scan $USER_FONT_PATH && fc-cache -fv"
    hits = _hits("fpf-fontconfig-scan-user-path", src)
    assert len(hits) >= 1
    assert hits[0].severity == "HIGH"


def test_fp10_positive_fc_config_app_font_add_file() -> None:
    """FcConfigAppFontAddFile() must trigger fpf-fontconfig-scan-user-path."""
    src = "fc.FcConfigAppFontAddFile(None, font_path.encode())"
    hits = _hits("fpf-fontconfig-scan-user-path", src)
    assert len(hits) >= 1


def test_fp10_negative_fc_list_static() -> None:
    """fc-list (not fc-scan/query/cache) must NOT trigger the rule."""
    src = "subprocess.run(['fc-list'], capture_output=True)"
    hits = _hits("fpf-fontconfig-scan-user-path", src)
    assert hits == []
