"""Tests for scripts/lib/image_processing_patterns.py.

Pattern-coverage tests for the Wave-27 distill-round-13 image-
processing catalogue (10 anti-patterns covering ImageMagick `policy.xml`,
Pillow `Image.open`, node-sharp, OpenCV `imread`/`imdecode`, exiftool
argument injection, libvips/pyvips, GraphicsMagick `convert`,
libheif/pillow-heif, server-side image fetch SSRF, and Pillow
`LOAD_TRUNCATED_IMAGES`). Each rule has at least one positive test
exercising the canary AND at least one negative test exercising the
carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import image_processing_patterns as ipp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(ipp.RULES, tuple)
    rule_ids = {r.id for r in ipp.RULES}
    expected = {
        "image-imagemagick-policy-xml-coder-rights-enabled",
        "image-pillow-image-open-no-max-pixels-bound",
        "image-sharp-fail-on-error-false-no-pixel-limit",
        "image-opencv-imdecode-on-untrusted-bytes",
        "image-exiftool-shell-out-no-dash-dash-separator",
        "image-pyvips-new-from-file-untrusted-input",
        "image-graphicsmagick-convert-shell-out-no-separator",
        "image-libheif-pillow-heif-register-no-dimension-check",
        "image-server-side-image-fetch-ssrf-and-bomb",
        "image-pillow-load-truncated-images-global-flag",
    }
    assert expected == rule_ids
    assert len(ipp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in ipp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = ipp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert ipp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — ImageMagick policy MVG dangerous coder
        '<policy domain="coder" rights="read|write" pattern="MVG" />\n'
        # Line 2 — PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True
        "PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True\n"
    )
    findings = ipp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line, findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[ipp.Finding]:
    return [f for f in ipp.scan_text(text) if f.rule_id == rule_id]


# ---------- IMG-001 : imagemagick-policy-xml-coder-rights-enabled --------


def test_img1_mvg_coder_read_write_rights_flags() -> None:
    """policy.xml with MVG coder at read|write → CRITICAL hit."""
    src = '<policy domain="coder" rights="read|write" pattern="MVG" />\n'
    hits = _hits("image-imagemagick-policy-xml-coder-rights-enabled", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_img1_msl_coder_read_rights_flags() -> None:
    """policy.xml with MSL coder at read rights → flagged."""
    src = '<policy domain="coder" rights="read" pattern="MSL" />\n'
    assert _hits("image-imagemagick-policy-xml-coder-rights-enabled", src)


def test_img1_wildcard_delegate_execute_flags() -> None:
    """policy.xml with delegate execute=* → flagged."""
    src = '<policy domain="delegate" rights="execute" pattern="*" />\n'
    assert _hits("image-imagemagick-policy-xml-coder-rights-enabled", src)


def test_img1_hardened_none_rights_silent() -> None:
    """policy.xml with rights=none on MVG → no hit (hardened)."""
    src = '<policy domain="coder" rights="none" pattern="MVG" />\n'
    assert not _hits("image-imagemagick-policy-xml-coder-rights-enabled", src)


# ---------- IMG-002 : pillow-image-open-no-max-pixels-bound --------------


def test_img2_pillow_image_open_on_request_stream_flags() -> None:
    """Image.open(request.files['avatar'].stream) → HIGH hit."""
    src = (
        "from PIL import Image\n"
        "img = Image.open(request.files['avatar'].stream)\n"
    )
    hits = _hits("image-pillow-image-open-no-max-pixels-bound", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_img2_pillow_image_open_on_bytesio_requests_flags() -> None:
    """Image.open(BytesIO(requests.get(...).content)) → flagged."""
    src = (
        "from PIL import Image\n"
        "from io import BytesIO\n"
        "resp = requests.get(user_supplied_url)\n"
        "img = Image.open(BytesIO(resp.content))\n"
    )
    assert _hits("image-pillow-image-open-no-max-pixels-bound", src)


def test_img2_max_pixels_set_to_none_flags() -> None:
    """Image.MAX_IMAGE_PIXELS = None → flagged (direct vuln)."""
    src = "Image.MAX_IMAGE_PIXELS = None\n"
    assert _hits("image-pillow-image-open-no-max-pixels-bound", src)


def test_img2_decompression_bomb_warning_silenced_flags() -> None:
    """filterwarnings('ignore', DecompressionBombWarning) → flagged."""
    src = (
        "import warnings\n"
        "warnings.filterwarnings('ignore', "
        "category=Image.DecompressionBombWarning)\n"
    )
    assert _hits("image-pillow-image-open-no-max-pixels-bound", src)


def test_img2_max_pixels_bound_suppresses() -> None:
    """File with Image.MAX_IMAGE_PIXELS = <int> suppresses → no hit."""
    src = (
        "from PIL import Image\n"
        "Image.MAX_IMAGE_PIXELS = 50000000\n"
        "img = Image.open(request.files['avatar'].stream)\n"
    )
    # The Image.open trigger is suppressed, but the bound itself is
    # within the safe range (1..999_999_999) so MAX_PIXELS_DISABLED
    # does NOT fire.
    assert not _hits("image-pillow-image-open-no-max-pixels-bound", src)


# ---------- IMG-003 : sharp-fail-on-error-false-no-pixel-limit -----------


def test_img3_sharp_fail_on_error_false_flags() -> None:
    """sharp(buf, { failOnError: false }) → HIGH hit."""
    src = (
        "const out = await sharp(req.body, { failOnError: false })"
        ".resize(256, 256).toBuffer();\n"
    )
    hits = _hits("image-sharp-fail-on-error-false-no-pixel-limit", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_img3_sharp_fail_on_none_flags() -> None:
    """sharp(buf, { failOn: 'none' }) → flagged (sharp ≥ 0.33)."""
    src = "return sharp(buf, { failOn: 'none' }).resize({ width: 1024 }).toBuffer();\n"
    assert _hits("image-sharp-fail-on-error-false-no-pixel-limit", src)


def test_img3_sharp_limit_input_pixels_false_flags() -> None:
    """sharp(buf, { limitInputPixels: false }) → flagged."""
    src = (
        "const out = await sharp(req.body, "
        "{ limitInputPixels: false }).toBuffer();\n"
    )
    assert _hits("image-sharp-fail-on-error-false-no-pixel-limit", src)


def test_img3_sharp_density_bomb_flags() -> None:
    """sharp(buf).resize density: 600 → flagged (SVG bomb)."""
    src = (
        "const out = await sharp(svg).resize({ width: 1024, "
        "density: 600 }).toBuffer();\n"
    )
    assert _hits("image-sharp-fail-on-error-false-no-pixel-limit", src)


def test_img3_sharp_on_req_body_no_safe_failon_flags() -> None:
    """sharp(req.body) with no `failOn: 'error'` mitigation → flagged."""
    src = (
        "const out = await sharp(req.body).resize(256, 256).toBuffer();\n"
    )
    assert _hits("image-sharp-fail-on-error-false-no-pixel-limit", src)


def test_img3_sharp_with_safe_fail_on_error_suppresses() -> None:
    """sharp(buf, { failOn: 'error', limitInputPixels: 16384 * 16384 }) → no hit."""
    src = (
        "const out = await sharp(req.body, { failOn: 'error', "
        "limitInputPixels: 268435456 }).resize(256, 256).toBuffer();\n"
    )
    assert not _hits("image-sharp-fail-on-error-false-no-pixel-limit", src)


# ---------- IMG-004 : opencv-imdecode-on-untrusted-bytes -----------------


def test_img4_imdecode_on_req_body_flags() -> None:
    """cv2.imdecode(np.frombuffer(req.body, np.uint8), ...) → HIGH hit."""
    src = (
        "import cv2, numpy as np\n"
        "arr = np.frombuffer(req.body, np.uint8)\n"
        "img = cv2.imdecode(np.frombuffer(req.body, np.uint8), "
        "cv2.IMREAD_UNCHANGED)\n"
    )
    hits = _hits("image-opencv-imdecode-on-untrusted-bytes", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_img4_imdecode_on_request_files_flags() -> None:
    """cv2.imdecode(np.frombuffer(request.files['x'].read(), ...)) → flagged."""
    src = (
        "img = cv2.imdecode(np.frombuffer(request.files['x'].read(), "
        "np.uint8), cv2.IMREAD_COLOR)\n"
    )
    assert _hits("image-opencv-imdecode-on-untrusted-bytes", src)


def test_img4_imread_unchanged_flag_flags() -> None:
    """cv2.imread(path, cv2.IMREAD_UNCHANGED) → flagged (broad surface)."""
    src = "img = cv2.imread(path, cv2.IMREAD_UNCHANGED)\n"
    assert _hits("image-opencv-imdecode-on-untrusted-bytes", src)


def test_img4_imread_fstring_user_var_flags() -> None:
    """cv2.imread(f'/var/uploads/{slug}') → flagged."""
    src = 'img = cv2.imread(f"/var/uploads/{slug}")\n'
    assert _hits("image-opencv-imdecode-on-untrusted-bytes", src)


def test_img4_imread_literal_path_silent() -> None:
    """cv2.imread('./fixtures/test.png') → no hit (literal path)."""
    src = "img = cv2.imread('./fixtures/test.png')\n"
    assert not _hits("image-opencv-imdecode-on-untrusted-bytes", src)


# ---------- IMG-005 : exiftool-shell-out-no-dash-dash-separator ----------


def test_img5_subprocess_run_exiftool_no_separator_flags() -> None:
    """subprocess.run(['exiftool', path], ...) → CRITICAL hit (no `--`)."""
    src = (
        "import subprocess\n"
        'def get_exif(path):\n'
        '    return subprocess.run(["exiftool", path], capture_output=True).stdout\n'
    )
    hits = _hits("image-exiftool-shell-out-no-dash-dash-separator", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_img5_child_process_exec_exiftool_flags() -> None:
    """child_process.exec('exiftool ...') with interpolation → flagged."""
    src = (
        "const { exec } = require('child_process');\n"
        "exec(`exiftool -all= \"${filename}\"`, callback);\n"
    )
    assert _hits("image-exiftool-shell-out-no-dash-dash-separator", src)


def test_img5_exiftool_with_dash_dash_separator_suppressed() -> None:
    """subprocess.run(['exiftool', '--', path], ...) → no hit (hardened)."""
    src = (
        'subprocess.run(["exiftool", "--", path], capture_output=True, '
        'check=True, timeout=10)\n'
    )
    assert not _hits("image-exiftool-shell-out-no-dash-dash-separator", src)


def test_img5_exiftool_config_from_user_var_flags() -> None:
    """exiftool -config ${req.body.cfg} → flagged."""
    src = "exiftool -config ${req.body.cfg} ${file}\n"
    assert _hits("image-exiftool-shell-out-no-dash-dash-separator", src)


# ---------- IMG-006 : pyvips-new-from-file-untrusted-input ---------------


def test_img6_pyvips_new_from_file_on_upload_path_flags() -> None:
    """pyvips.Image.new_from_file(upload_path) → HIGH hit."""
    src = (
        "import pyvips\n"
        "img = pyvips.Image.new_from_file(upload_path)\n"
    )
    hits = _hits("image-pyvips-new-from-file-untrusted-input", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_img6_pyvips_access_sequential_flags() -> None:
    """pyvips.Image.new_from_file(path, access='sequential') → flagged."""
    src = "img = pyvips.Image.new_from_file(path, access='sequential')\n"
    assert _hits("image-pyvips-new-from-file-untrusted-input", src)


def test_img6_pyvips_fail_false_flags() -> None:
    """pyvips.Image.new_from_file(path, fail=False) → flagged."""
    src = "img = pyvips.Image.new_from_file(path, fail=False)\n"
    assert _hits("image-pyvips-new-from-file-untrusted-input", src)


def test_img6_pyvips_svg_input_flags() -> None:
    """pyvips.Image.new_from_file('input.svg') → flagged (SVG SSRF)."""
    src = "img = pyvips.Image.new_from_file('input.svg')\n"
    assert _hits("image-pyvips-new-from-file-untrusted-input", src)


def test_img6_pyvips_write_to_file_silent() -> None:
    """pyvips Image.write_to_file (no decoder dispatch) → no hit."""
    src = "img.write_to_file('output.png')\n"
    assert not _hits("image-pyvips-new-from-file-untrusted-input", src)


# ---------- IMG-007 : graphicsmagick-convert-shell-out-no-separator ------


def test_img7_subprocess_run_convert_no_separator_flags() -> None:
    """subprocess.run(['convert', upload_path, ...]) → CRITICAL hit."""
    src = (
        'subprocess.run(["convert", upload_path, "-resize", "256x256", '
        'thumb_path], check=True)\n'
    )
    hits = _hits("image-graphicsmagick-convert-shell-out-no-separator", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_img7_os_system_convert_flags() -> None:
    """os.system(f'convert {user_path} ...') → flagged."""
    src = 'os.system(f"convert {user_path} -resize 256x256 {out}")\n'
    assert _hits("image-graphicsmagick-convert-shell-out-no-separator", src)


def test_img7_gm_convert_flags() -> None:
    """subprocess.run(['gm convert', ...]) → flagged."""
    src = 'subprocess.run(["gm convert", upload_path, out_path])\n'
    assert _hits("image-graphicsmagick-convert-shell-out-no-separator", src)


def test_img7_convert_with_separator_suppressed() -> None:
    """subprocess.run(['convert', '--', basename, ...]) → no hit."""
    src = (
        'subprocess.run(["convert", "--", safe_in, "-resize", '
        '"256x256", out], check=True)\n'
    )
    assert not _hits("image-graphicsmagick-convert-shell-out-no-separator", src)


def test_img7_convert_coder_prefix_user_var_flags() -> None:
    """convert ${req.coder}:upload — coder-prefix injection → flagged."""
    src = "convert ${req.body.coder}:upload out.png\n"
    assert _hits("image-graphicsmagick-convert-shell-out-no-separator", src)


# ---------- IMG-008 : libheif-pillow-heif-register-no-dimension-check ----


def test_img8_register_heif_opener_flags() -> None:
    """register_heif_opener() at module level → HIGH hit."""
    src = (
        "from pillow_heif import register_heif_opener\n"
        "register_heif_opener()\n"
    )
    hits = _hits("image-libheif-pillow-heif-register-no-dimension-check", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_img8_pyheif_read_on_request_flags() -> None:
    """pyheif.read(req.body) → flagged."""
    src = "heif_file = pyheif.read(req.body)\n"
    assert _hits("image-libheif-pillow-heif-register-no-dimension-check", src)


def test_img8_libheif_context_read_flags() -> None:
    """heif_context_read_from_file(...) → flagged."""
    src = "heif_context_read_from_file(ctx, path, NULL)\n"
    assert _hits("image-libheif-pillow-heif-register-no-dimension-check", src)


def test_img8_unrelated_import_silent() -> None:
    """Unrelated Pillow code without HEIC registration → no hit."""
    src = "from PIL import Image\nimg = Image.new('RGB', (256, 256))\n"
    assert not _hits(
        "image-libheif-pillow-heif-register-no-dimension-check", src
    )


# ---------- IMG-009 : server-side-image-fetch-ssrf-and-bomb --------------


def test_img9_pillow_fetch_open_ssrf_chain_flags() -> None:
    """Image.open(BytesIO(requests.get(user_url).content)) → CRITICAL hit."""
    src = (
        "import requests\n"
        "from PIL import Image\n"
        "from io import BytesIO\n"
        "def fetch_og_image(url):\n"
        "    resp = requests.get(url, timeout=10)\n"
        "    return Image.open(BytesIO(requests.get(url).content))\n"
    )
    hits = _hits("image-server-side-image-fetch-ssrf-and-bomb", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_img9_sharp_axios_ssrf_chain_flags() -> None:
    """sharp(Buffer.from(axios.get(req.body.url).data)) → flagged (JS)."""
    src = (
        "const out = await sharp(Buffer.from(await axios.get(req.body.url, "
        "{ responseType: 'arraybuffer' }).data)).resize(512).toBuffer();\n"
    )
    assert _hits("image-server-side-image-fetch-ssrf-and-bomb", src)


def test_img9_local_image_open_silent() -> None:
    """Image.open from a local path literal → no hit."""
    src = "img = Image.open('local.png')\n"
    assert not _hits("image-server-side-image-fetch-ssrf-and-bomb", src)


# ---------- IMG-010 : pillow-load-truncated-images-global-flag -----------


def test_img10_load_truncated_images_module_level_flags() -> None:
    """ImageFile.LOAD_TRUNCATED_IMAGES = True → MEDIUM hit."""
    src = (
        "from PIL import ImageFile\n"
        "ImageFile.LOAD_TRUNCATED_IMAGES = True\n"
    )
    hits = _hits("image-pillow-load-truncated-images-global-flag", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_img10_pil_imagefile_fqdn_flags() -> None:
    """PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True → flagged."""
    src = "PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True\n"
    assert _hits("image-pillow-load-truncated-images-global-flag", src)


def test_img10_load_truncated_false_silent() -> None:
    """LOAD_TRUNCATED_IMAGES = False (default) → no hit."""
    src = "ImageFile.LOAD_TRUNCATED_IMAGES = False\n"
    assert not _hits("image-pillow-load-truncated-images-global-flag", src)
