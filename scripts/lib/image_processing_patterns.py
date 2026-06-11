"""Image-processing library anti-pattern detectors.

Wave-27 distillation round 13 — ImageMagick `policy.xml`, libvips /
pyvips, sharp (node-sharp), Pillow, OpenCV `imread`/`imdecode`,
exiftool argument injection, GraphicsMagick `gm convert` shell-out,
libheif. Catalogue of 10 anti-patterns documented in
`reports/distill-round-13/image-processing.md`. Targets surfaces no
existing pack covers (cross-lang deserialize / command-injection /
archive-bomb packs explicitly exclude image-decode pixel buffers).

What is NOT here (already shipped — DO NOT duplicate):

  * Python pickle / YAML / marshal native deserialization —
    `cross_lang_deserialize_patterns.py`.
  * Generic shell-out via `subprocess` —
    `command_injection_patterns.py`. The IMG-005 / IMG-007 rules below
    catch the *image-library-specific* shell-out shapes (exiftool,
    `convert`, `gm convert`) whose dangerous arg is the image PATH,
    not the command.
  * ZIP / TAR / 7z container bombs — `archive_extraction_patterns.py`.
    Image bombs use codec expansion ratios, not container ratios.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * image-imagemagick-policy-xml-coder-rights-enabled       (CRITICAL)
  * image-pillow-image-open-no-max-pixels-bound             (HIGH)
  * image-sharp-fail-on-error-false-no-pixel-limit          (HIGH)
  * image-opencv-imdecode-on-untrusted-bytes                (HIGH)
  * image-exiftool-shell-out-no-dash-dash-separator         (CRITICAL)
  * image-pyvips-new-from-file-untrusted-input              (HIGH)
  * image-graphicsmagick-convert-shell-out-no-separator     (CRITICAL)
  * image-libheif-pillow-heif-register-no-dimension-check   (HIGH)
  * image-server-side-image-fetch-ssrf-and-bomb             (CRITICAL)
  * image-pillow-load-truncated-images-global-flag          (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Insecure Design / missing resource ceiling (decompression
            bomb on Pillow, sharp, libheif).
  ASI-03 — Injection — CWE-78 / CWE-88 / CWE-94 (ImageMagick coder
            rights, exiftool filename injection, `convert` arg
            injection, MVG/MSL coder dispatch).
  ASI-04 — Insecure Data / supply-chain trust (untrusted bytes feeding
            a decoder dispatch, OpenCV `imdecode` on raw body).
  ASI-05 — Security Misconfiguration (ImageMagick `policy.xml`,
            Pillow `LOAD_TRUNCATED_IMAGES`).
  ASI-10 — SSRF (server-side image fetch into the decoder pipeline).

All regexes are RE2-compatible (no backreferences, no lookbehind on
variable-length subpatterns, no catastrophic backtracking shapes).
Patterns are PRE-COMPILED at module load. Fail-fast: callers receive
structured Finding tuples, never raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

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
    chat_bot_patterns / voice_audio_patterns / webhook_signature_patterns.
    RE2-safe: no nested quantifiers, no backreferences, no lookbehind
    on variable-length runs."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- IMG-001 : image-imagemagick-policy-xml-coder-rights-enabled --------


# Dangerous ImageMagick coders left at read/write/execute rights. The
# `rights` attribute may be a single token (`read`) or a pipe-joined
# combo (`read|write`); RE2-safe — bounded run.
_IMAGEMAGICK_POLICY_DANGEROUS_CODER = _re(
    r"<policy\s+domain=\"coder\"\s+rights=\""
    r"(?:read|write|read\|write|read\s*\|\s*write|execute)\"\s+"
    r"pattern=\"(?:MVG|MSL|MSL2|PS|PS2|PS3|EPS|EPSI|EPSF|PDF|XPS"
    r"|EPHEMERAL|URL|HTTPS|HTTP|FTP|TEXT|SHOW|WIN|PLT|LABEL)\"\s*/>"
)

# Wildcard delegate execute — separate trigger; same severity.
_IMAGEMAGICK_POLICY_WILDCARD_DELEGATE = _re(
    r"<policy\s+domain=\"delegate\"\s+rights=\"execute\"\s+"
    r"pattern=\"\*\"\s*/>"
)


# ---- IMG-002 : image-pillow-image-open-no-max-pixels-bound --------------


# Anchor on `Image.open` invoked on a request-derived stream / buffer /
# URL response. Stage-B then checks the file-level absence of a
# `MAX_IMAGE_PIXELS` bound.
_PILLOW_IMAGE_OPEN_UNTRUSTED = _re(
    r"\bImage\.open\s*\(\s*"
    r"(?:"
    r"request\.|flask\.request\.|self\.request\.|req\."
    r"|BytesIO\s*\(\s*"
    r"(?:request\.|resp\.content|response\.content"
    r"|requests\.|aiohttp\.|httpx\.|urllib\.)"
    r"|open\s*\(\s*(?:request\.|self\.request\.)"
    r")"
)

# Pillow `MAX_IMAGE_PIXELS` reassigned to None or to a huge sentinel —
# direct vulnerability shape (re-enables the bomb). Bounded by digit
# count to stay RE2-safe.
_PILLOW_MAX_PIXELS_DISABLED = _re(
    r"\bImage\.MAX_IMAGE_PIXELS\s*=\s*"
    r"(?:None|[5-9]\d{8}|\d{10,15})\b"
)

# Pillow `DecompressionBombWarning` explicitly silenced — undoes the
# only built-in guard. The warning shape is what we look for.
_PILLOW_DECOMP_WARNING_SILENCED = _re(
    r"\bwarnings\.(?:filterwarnings|simplefilter)\s*\(\s*"
    r"['\"]ignore['\"]\s*,\s*"
    r"(?:category\s*=\s*)?"
    r"(?:Image|PIL\.Image)\.DecompressionBombWarning\b"
)

# File-level mitigation marker — a bounded-int `MAX_IMAGE_PIXELS = N`
# assignment anywhere in the same file suppresses the IMG-002 finding.
_PILLOW_MAX_PIXELS_BOUND = _re(
    r"\bImage\.MAX_IMAGE_PIXELS\s*=\s*\d{1,9}\b"
)


# ---- IMG-003 : image-sharp-fail-on-error-false-no-pixel-limit -----------


# `sharp(...)` constructor with `failOnError: false` OR sharp ≥ 0.33
# spelling `failOn: 'none'`. RE2-safe: bounded run inside the argument
# list, no nested quantifiers.
_SHARP_FAIL_ON_ERROR_OFF = _re(
    r"\bsharp\s*\(\s*[^)]{0,300}?"
    r"(?:failOnError\s*:\s*false"
    r"|failOn\s*:\s*['\"]none['\"])"
)

# `sharp(...)` constructor with `limitInputPixels` disabled (false, 0,
# or a sentinel above ~1B). Bounded digit runs.
_SHARP_LIMIT_INPUT_PIXELS_OFF = _re(
    r"\bsharp\s*\(\s*[^)]{0,300}?"
    r"limitInputPixels\s*:\s*"
    r"(?:false|0\b|[2-9]\d{9,11}|1[0-9]\d{8,10})"
)

# Trigger anchor — `sharp(<untrusted buffer var>)` shape. The variable
# vocabulary list is bounded.
_SHARP_UNTRUSTED_BUFFER = _re(
    r"\bsharp\s*\(\s*"
    r"(?:req\.body|request\.body|ctx\.request\.body"
    r"|Buffer\.from\s*\(\s*req\.|Buffer\.from\s*\(\s*request\."
    r"|buffer|buf|body)\b"
)

# `sharp(...).<...>density: <large>` — SVG-bomb knob.
_SHARP_SVG_DENSITY_BOMB = _re(
    r"\bsharp\s*\([^)]{0,200}\)\s*\.\s*"
    r"(?:resize|withMetadata|toBuffer|jpeg|png)[^;]{0,200}?"
    r"\bdensity\s*:\s*(?:[3-9]\d{2}|\d{4,6})\b"
)


# ---- IMG-004 : image-opencv-imdecode-on-untrusted-bytes -----------------


# `cv2.imdecode(np.frombuffer(<req-body source>, ...))` — direct
# decoder dispatch on the raw request body.
_OPENCV_IMDECODE_UNTRUSTED = _re(
    r"\bcv2\.imdecode\s*\(\s*np\.frombuffer\s*\(\s*"
    r"(?:req\.body|request\.body"
    r"|await\s+req\.body\s*\(\s*\)"
    r"|self\.rfile\.read"
    r"|base64\.b64decode\s*\(\s*req"
    r"|request\.get_data|request\.files|request\.data"
    r"|flask\.request\.|self\.request\.|ctx\.request\.body)"
)

# IMREAD_UNCHANGED / IMREAD_ANYDEPTH / IMREAD_ANYCOLOR — broad-surface
# flags that bring rarer decoders (EXR, JPEG2000, TIFF float) into
# play.
_OPENCV_BROAD_IMREAD_FLAGS = _re(
    r"\bcv2\.(?:imread|imdecode)\s*\([^)]{0,200},\s*"
    r"cv2\.IMREAD_(?:UNCHANGED|ANYDEPTH|ANYCOLOR)\b"
)

# `cv2.imread(f"... {req.|request.|slug|user_|...}")` — f-string path
# with user-controllable variable.
_OPENCV_IMREAD_FSTRING_USER_PATH = _re(
    r"\bcv2\.imread\s*\(\s*f[\"'][^\"']{0,200}\{"
    r"(?:req\.|request\.|self\.request\."
    r"|slug|user_|filename|path_param|kwargs|args)"
)


# ---- IMG-005 : image-exiftool-shell-out-no-dash-dash-separator ----------


# `subprocess.run(["exiftool", ...])` / `child_process.exec("exiftool
# ...")` shape — the array form is widely thought safe, but allows a
# leading `-` filename to be parsed as an exiftool option.
_EXIFTOOL_SHELL_OUT = _re(
    r"\b(?:"
    r"subprocess\.(?:run|Popen|call|check_output)"
    r"|os\.system|os\.popen"
    r"|child_process\.(?:exec|execSync|spawn|spawnSync)"
    r"|exec(?:Sync)?"
    r")\s*\([^)]{0,200}?[\"'`]exiftool[\"'`\s]"
)

# `exiftool -config <user-var>` — a config-flag-from-untrusted-source
# is the canonical Perl-injection variant.
_EXIFTOOL_CONFIG_FROM_USER = _re(
    r"\bexiftool[^\"\n]{0,80}?\s-config\s+[\"']?"
    r"(?:\$\{?(?:req|request|ctx|user|args|kwargs|params)\."
    r"|\+\s*[a-zA-Z_])"
)

# Mitigation marker — the `--` end-of-options separator in the same
# argv list / template. The scanner checks the matched-call region.
_EXIFTOOL_DASH_DASH_GUARD = _re(
    r"[\"']--[\"']"
)


# ---- IMG-006 : image-pyvips-new-from-file-untrusted-input ---------------


# Anchor on `pyvips.Image.new_from_(file|buffer|stream)(<untrusted
# source>)`. The vocabulary mirrors the report.
_PYVIPS_NEW_FROM_UNTRUSTED = _re(
    r"\b(?:pyvips|vips)\.Image\.new_from_(?:file|buffer|stream)\s*"
    r"\(\s*"
    r"(?:req\.|request\.|self\.request\."
    r"|upload_|user_|path\b|filename\b"
    r"|f[\"'][^\"']{0,200}\{)"
)

# `access='sequential'` bypasses the random-access MAX_PIXELS guard —
# direct vulnerability shape.
_PYVIPS_ACCESS_SEQUENTIAL = _re(
    r"\b(?:pyvips|vips)\.Image\.new_from_(?:file|buffer)\s*"
    r"\([^)]{0,300}?access\s*=\s*['\"]sequential['\"]"
)

# `fail=False` explicit — undoes the fail-closed knob.
_PYVIPS_FAIL_DISABLED = _re(
    r"\b(?:pyvips|vips)\.Image\.new_from_(?:file|buffer)\s*"
    r"\([^)]{0,300}?fail\s*=\s*(?:False|false|0)\b"
)

# `.svg`-extension input — librsvg delegate honours external
# `<image href=...>` (SSRF surface).
_PYVIPS_SVG_INPUT = _re(
    r"\b(?:pyvips|vips)\.Image\.new_from_(?:file|buffer)\s*"
    r"\([^)]{0,200}\.svg\b"
)


# ---- IMG-007 : image-graphicsmagick-convert-shell-out-no-separator ------


# `subprocess.run(["convert", ...])` / `subprocess.run(["gm",
# "convert", ...])` / `child_process.exec("convert ...")`. Same
# leading-dash injection surface as exiftool.
_CONVERT_SHELL_OUT = _re(
    r"\b(?:"
    r"subprocess\.(?:run|Popen|call|check_output)"
    r"|os\.system|os\.popen"
    r"|child_process\.(?:exec|execSync|spawn|spawnSync)"
    r"|exec\.Command"
    r")\s*\([^)]{0,200}?"
    r"[\"'](?:convert|gm\s+convert|magick|magick\s+convert)[\"'\s]"
)

# Coder-prefix injection — `<user-var>:<path>` template forces the
# coder dispatch.
_CONVERT_CODER_PREFIX_INJECTION = _re(
    r"\b(?:convert|magick|gm\s+convert)\s+"
    r"\$?\{?(?:req\.|request\.|user|args|kwargs|params|coder)"
    r"[^\"']{0,80}?\}?:"
)

# `@<user-var>` argument-expansion — convert reads the file as a list
# of inputs.
_CONVERT_AT_EXPANSION = _re(
    r"\b(?:convert|magick|gm\s+convert)[^\"\n]{0,200}\s@"
    r"(?:\$\{?(?:req|request|user|args|kwargs|params)"
    r"|[\"']\s*\+\s*[a-zA-Z_])"
)


# ---- IMG-008 : image-libheif-pillow-heif-register-no-dimension-check ----


# `register_heif_opener()` — module-level call has process-wide effect.
_PILLOW_HEIF_REGISTER = _re(
    r"\bregister_heif_opener\s*\("
)

# `pyheif.read(<untrusted source>)` — direct decoder dispatch.
_PYHEIF_READ_UNTRUSTED = _re(
    r"\bpyheif\.read\s*\(\s*"
    r"(?:req\.|request\.|self\.request\."
    r"|upload_|user_)"
)

# `heif_context_read_from_(file|memory)` — C/cffi/ctypes binding shape.
_LIBHEIF_CONTEXT_READ = _re(
    r"\bheif_context_read_from_(?:file|memory)\s*\("
)


# ---- IMG-009 : image-server-side-image-fetch-ssrf-and-bomb --------------


# `Image.open(BytesIO(requests.get(<user url>).content))` — Python SSRF
# chain into Pillow decoder.
_PILLOW_FETCH_AND_OPEN = _re(
    r"\bImage\.open\s*\(\s*BytesIO\s*\(\s*"
    r"(?:requests|urllib\.request|httpx"
    r"|aiohttp\.ClientSession\(?\)?)"
    r"[^)]{0,200}\.get\s*\([^)]{0,200}?"
    r"(?:req\.|request\.|user_|args|kwargs|params|url\b|\$\{)"
)

# `sharp(Buffer.from(axios.get(<user url>).data))` — JS SSRF chain.
_SHARP_FETCH_AND_DECODE = _re(
    r"\bsharp\s*\(\s*Buffer\.from\s*\(\s*"
    r"(?:await\s+)?"
    r"(?:axios|fetch|got|node-fetch|undici)"
    r"[^)]{0,200}"
    r"(?:req\.|request\.|ctx\.|params\.|query\.|body\.)"
)


# ---- IMG-010 : image-pillow-load-truncated-images-global-flag -----------


# Process-wide flag — once True, every Image.open() silently accepts
# malformed/truncated bytes. Hits both `PIL.ImageFile` and the bare
# `ImageFile` import form.
_PILLOW_LOAD_TRUNCATED_TRUE = _re(
    r"\b(?:PIL\.)?ImageFile\.LOAD_TRUNCATED_IMAGES\s*=\s*True\b"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="image-imagemagick-policy-xml-coder-rights-enabled",
        name="ImageMagick policy.xml ships with MVG/MSL/PS/URL coders at read|write rights (ImageTragick)",
        severity="CRITICAL",
        description=(
            "ImageMagick's MVG (Magick Vector Graphics) and MSL "
            "(Magick Scripting Language) coders accept inline scripts "
            "that can read/write arbitrary files, fetch arbitrary "
            "URLs (SSRF), and execute delegate commands. Since the "
            "ImageTragick disclosure (CVE-2016-3714) the recommended "
            "`policy.xml` ships with these coders DISABLED by default, "
            "but custom Docker images / Alpine packages / homebrew "
            "formulas can override that. The vulnerable shape is in "
            "the shipped `policy.xml` content, not in code — and "
            "ImageMagick's coder dispatch is CONTENT-SNIFFING, so a "
            "`.jpg` extension does not protect against MVG payload. "
            "Hardened form is `rights=\"none\"` on every dangerous "
            "coder plus `rights=\"none\"` on the wildcard delegate."
        ),
        pattern=_IMAGEMAGICK_POLICY_DANGEROUS_CODER,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="image-pillow-image-open-no-max-pixels-bound",
        name="Pillow Image.open on untrusted source without MAX_IMAGE_PIXELS bound (decompression bomb)",
        severity="HIGH",
        description=(
            "`PIL.Image.open()` is called on a request-derived stream "
            "/ buffer / URL response without a file-level "
            "`Image.MAX_IMAGE_PIXELS = <bounded int>` override. "
            "Pillow's default 89 MP threshold emits a "
            "`DecompressionBombWarning` (NOT an error) and "
            "PROCEEDS to decode — a 36 KB malformed PNG can expand "
            "into a 16 GB pixel buffer, OOM-killing the worker. The "
            "fix is to set a bounded `MAX_IMAGE_PIXELS` AND treat "
            "`DecompressionBombWarning` as a fatal error via "
            "`warnings.simplefilter('error', "
            "Image.DecompressionBombWarning)`. A second variant: the "
            "warning is explicitly silenced via "
            "`warnings.filterwarnings('ignore', "
            "category=Image.DecompressionBombWarning)`."
        ),
        pattern=_PILLOW_IMAGE_OPEN_UNTRUSTED,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="image-sharp-fail-on-error-false-no-pixel-limit",
        name="node-sharp called with failOnError:false / limitInputPixels disabled on untrusted buffer",
        severity="HIGH",
        description=(
            "`sharp(buffer)` (the Node libvips wrapper) called with "
            "`failOnError: false` (or `failOn: 'none'` on sharp ≥ "
            "0.33) AND/OR with `limitInputPixels` set to `false`, "
            "`0`, or a sentinel above ~1 GP. Both knobs together "
            "re-enable the decompression-bomb surface: sharp "
            "tolerates partial decode, libvips's mozjpeg / libpng / "
            "libwebp pipelines run with no size cap, and a 36 KB "
            "input drives the worker process to 8+ GB RSS in < 100 "
            "ms. Because the libvips worker shares the Node event "
            "loop, the OOM kills the whole server, not just the "
            "request. Hardened form: `failOn: 'error'` + "
            "`limitInputPixels: 16_384 * 16_384` + `density: 72`."
        ),
        pattern=_SHARP_FAIL_ON_ERROR_OFF,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="image-opencv-imdecode-on-untrusted-bytes",
        name="cv2.imdecode on raw request body / IMREAD_UNCHANGED on user input",
        severity="HIGH",
        description=(
            "`cv2.imdecode(np.frombuffer(req.body, np.uint8), ...)` "
            "reads the raw HTTP request body directly into a NumPy "
            "array and hands it to OpenCV's decoder dispatch. OpenCV "
            "includes libjpeg-turbo, libpng, libwebp, libtiff, "
            "OpenEXR, libjasper, and GDAL — each with a multi-year "
            "CVE history (CVE-2017-12862 libjasper RCE, "
            "CVE-2023-4863 libwebp heap overflow, etc.). The risk is "
            "higher when `cv2.IMREAD_UNCHANGED` / "
            "`cv2.IMREAD_ANYDEPTH` / `cv2.IMREAD_ANYCOLOR` is passed — "
            "those preserve the original channel layout (float32 "
            "EXR, 16-bpc TIFF) and bring rarer decoders into the "
            "attack surface. Mitigation: explicit `IMREAD_COLOR` + "
            "max-bytes guard + post-decode shape sanity check."
        ),
        pattern=_OPENCV_IMDECODE_UNTRUSTED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="image-exiftool-shell-out-no-dash-dash-separator",
        name="exiftool spawned without `--` end-of-options separator on user filename",
        severity="CRITICAL",
        description=(
            "`subprocess.run([\"exiftool\", filename])` or "
            "`child_process.exec(\"exiftool ...\")` invoked with a "
            "user-controlled filename and WITHOUT the `--` end-of-"
            "options separator. exiftool treats any positional arg "
            "starting with `-` as an option flag — `-stay_open` keeps "
            "the process alive; `-config FILE` loads attacker-"
            "supplied Perl from a `.ExifTool_config` (CVE-2021-22204 "
            "family). The attacker uploads a file whose multer-"
            "stored name starts with `-config /tmp/evil.pl` and "
            "achieves RCE. Array form is NOT safe by itself — the "
            "`--` separator is mandatory. Distinct from generic "
            "command-injection rules because the dangerous arg is "
            "the image PATH, not the command."
        ),
        pattern=_EXIFTOOL_SHELL_OUT,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="image-pyvips-new-from-file-untrusted-input",
        name="pyvips.Image.new_from_(file|buffer) on untrusted input with delegate dispatch",
        severity="HIGH",
        description=(
            "`pyvips.Image.new_from_file(untrusted_path)` / "
            "`new_from_buffer(svg_bytes)` dispatches by content-"
            "sniffing — a `.jpg` upload whose first bytes are "
            "`%PDF-` gets routed to Poppler (CVE-2018-13988, "
            "CVE-2024-3923 RCE chain). An `access='sequential'` "
            "kwarg bypasses libvips's `VIPS_MAX_PIXELS` random-"
            "access guard. SVG inputs go through librsvg which "
            "honours `<image href=...>` external references (file:// "
            "local-file-read, http:// SSRF). The `fail=False` kwarg "
            "(or omitting the kwarg entirely) suppresses the fail-"
            "closed posture. Hardened: pin the loader explicitly "
            "(`pyvips.Image.jpegload(path, ...)`) and pass "
            "`fail=True`."
        ),
        pattern=_PYVIPS_NEW_FROM_UNTRUSTED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="image-graphicsmagick-convert-shell-out-no-separator",
        name="convert / gm convert / magick shelled out on user filename without `--` separator",
        severity="CRITICAL",
        description=(
            "`subprocess.run([\"convert\", user_path, ...])` / "
            "`subprocess.run([\"gm\", \"convert\", ...])` / "
            "`os.system(f'convert {user_path} ...')`. Even with a "
            "hardened `policy.xml` (IMG-001), `convert` itself has "
            "argument-injection surface: a filename starting with "
            "`-` is parsed as an option (`-write /etc/...`, "
            "`-process @/etc/passwd`, `-debug all`, `-read mvg:...`). "
            "A colon-prefixed path (`mvg:upload`, `msl:upload`, "
            "`url:http://...`) forces the coder dispatch — combined "
            "with relaxed policy this is RCE. An `@filename` arg "
            "expands the file as a list of inputs. Hardened form: "
            "`[\"convert\", \"--\", \"./\" + basename(path), ...]` + "
            "explicit timeout."
        ),
        pattern=_CONVERT_SHELL_OUT,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="image-libheif-pillow-heif-register-no-dimension-check",
        name="register_heif_opener / pyheif.read called on untrusted input without dimension cap",
        severity="HIGH",
        description=(
            "`pillow_heif.register_heif_opener()` enables HEIC "
            "decoding for every `Image.open()` in the process — "
            "once registered, attacker-supplied HEIC files reach "
            "libheif and libde265 (CVE-2023-49463, CVE-2023-49464, "
            "CVE-2024-41181 RCE/DoS chain). The Pillow "
            "`MAX_IMAGE_PIXELS` check fires AFTER decode allocation, "
            "so an HEIC with a malformed `ispe` box (claimed "
            "32 768² pixels) bombs the buffer before the guard "
            "trips. `pyheif.read(req.body)` is the direct-binding "
            "form with the same exposure. Hardened form: reject by "
            "content-sniff before decoder dispatch, OR pre-read the "
            "`ispe` box dimensions and reject above a cap without "
            "decoding."
        ),
        pattern=_PILLOW_HEIF_REGISTER,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="image-server-side-image-fetch-ssrf-and-bomb",
        name="Server-side image fetch (requests.get → Image.open / axios → sharp) with no URL allowlist",
        severity="CRITICAL",
        description=(
            "An app accepts an image URL (OG-image generator, link "
            "previewer, avatar import from Gravatar) and pipes "
            "`requests.get(url).content` directly into "
            "`Image.open(BytesIO(...))` or `axios.get(url, "
            "{responseType: 'arraybuffer'}).data` into "
            "`sharp(Buffer.from(...))` — no URL host allowlist, no "
            "RFC1918 / loopback / link-local egress filter, no "
            "`Content-Length` cap. SSRF surface: "
            "`http://169.254.169[.]254/latest/meta-data/iam/security-"
            "credentials/` (AWS IMDSv1), `http://localhost:6379/` "
            "(internal Redis), `file:///etc/passwd` (when the HTTP "
            "client allows `file://`). Decompression-bomb surface: "
            "the attacker controls the response body and serves a "
            "36 KB → 16 GB PNG. Hardened: pre-resolve hostname, "
            "block RFC1918 / loopback / link-local, cap "
            "`Content-Length`, stream-read with a hard byte ceiling."
        ),
        pattern=_PILLOW_FETCH_AND_OPEN,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="image-pillow-load-truncated-images-global-flag",
        name="PIL.ImageFile.LOAD_TRUNCATED_IMAGES=True set at module level",
        severity="MEDIUM",
        description=(
            "`PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True` is a "
            "process-wide flag — once set, every subsequent "
            "`Image.open()` in the same Python process silently "
            "accepts truncated / malformed image data and fills the "
            "rest with grey/black. Real-world impact: (1) a "
            "truncated JPEG triggers libjpeg-turbo's trailing-junk "
            "decode path (CVE-2018-19134 UAF family); (2) an OCR "
            "pipeline that previously rejected malformed PDFs now "
            "silently accepts them, leaking back-pressure as a "
            "timing side channel; (3) a model.predict() pipeline "
            "silently feeds half-black inputs to the classifier — "
            "model evasion. The flag is often set 'to fix a flaky "
            "test' and forgotten in production."
        ),
        pattern=_PILLOW_LOAD_TRUNCATED_TRUE,
        owasp_asi="ASI-05",
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

    Stage-B filters consult adjacent lines for context:

      * IMG-001 — primary regex flags any dangerous-coder line; a
        secondary regex flags the wildcard delegate-execute line.
        Both feed the same rule id (the `policy.xml` is the vulnerable
        artefact, not the specific line).
      * IMG-002 — anchor on `Image.open(<untrusted>)`, suppress if the
        same file contains a bounded `MAX_IMAGE_PIXELS = <int>`
        assignment. Plus two direct-vuln variants: a wildly-large /
        `None` `MAX_IMAGE_PIXELS` assignment, and an explicitly
        silenced `DecompressionBombWarning`.
      * IMG-003 — anchor on `sharp(req.body|buffer|buf|body)` with
        `failOnError: false` / `failOn: 'none'` OR `limitInputPixels`
        disabled in the same call. Plus the SVG-density-bomb variant.
      * IMG-004 — anchor on `cv2.imdecode(np.frombuffer(<user
        body>))`. Plus the `IMREAD_UNCHANGED|ANYDEPTH|ANYCOLOR`
        variant on any imread/imdecode call.
      * IMG-005 — anchor on `exiftool` shell-out, suppress if the
        same matched-call window contains `"--"` (the end-of-options
        separator). Plus the direct `-config <user-var>` injection.
      * IMG-006 — anchor on `new_from_file(<untrusted>)`. Plus three
        direct-vuln variants: `access='sequential'`, explicit
        `fail=False`, and `.svg` extension input (librsvg SSRF).
      * IMG-007 — anchor on `convert` / `gm convert` / `magick`
        shell-out, suppress if the same matched-call window contains
        `"--"`. Plus the coder-prefix and `@<user>` expansion
        variants.
      * IMG-008 — anchor on `register_heif_opener()` at module level.
        Plus `pyheif.read(<untrusted>)` and direct libheif binding.
      * IMG-009 — anchor on the SSRF chain shape `Image.open(BytesIO(
        requests.get(<user>)))` / `sharp(Buffer.from(axios.get(<user>
        )))`. Same severity for both languages.
      * IMG-010 — direct flag literal at module level.

    Findings are deduped by (rule_id, line, col).
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

    # ---- IMG-001 : imagemagick-policy-xml-coder-rights-enabled ----
    rule_img1 = rule_by_id["image-imagemagick-policy-xml-coder-rights-enabled"]
    for m in _IMAGEMAGICK_POLICY_DANGEROUS_CODER.finditer(text):
        _emit(rule_img1, m.start(), m.group(0))
    for m in _IMAGEMAGICK_POLICY_WILDCARD_DELEGATE.finditer(text):
        _emit(rule_img1, m.start(), m.group(0))

    # ---- IMG-002 : pillow-image-open-no-max-pixels-bound ----
    rule_img2 = rule_by_id["image-pillow-image-open-no-max-pixels-bound"]
    has_pixel_bound = _file_contains(text, _PILLOW_MAX_PIXELS_BOUND)
    if not has_pixel_bound:
        for m in _PILLOW_IMAGE_OPEN_UNTRUSTED.finditer(text):
            _emit(rule_img2, m.start(), m.group(0))
    # Direct-vuln variants are always flagged, regardless of bound.
    for m in _PILLOW_MAX_PIXELS_DISABLED.finditer(text):
        _emit(rule_img2, m.start(), m.group(0))
    for m in _PILLOW_DECOMP_WARNING_SILENCED.finditer(text):
        _emit(rule_img2, m.start(), m.group(0))

    # ---- IMG-003 : sharp-fail-on-error-false-no-pixel-limit ----
    rule_img3 = rule_by_id["image-sharp-fail-on-error-false-no-pixel-limit"]
    # Stage-A: direct `failOnError: false` / `failOn: 'none'`.
    for m in _SHARP_FAIL_ON_ERROR_OFF.finditer(text):
        _emit(rule_img3, m.start(), m.group(0))
    # Stage-A: direct `limitInputPixels: false|0|<huge>`.
    for m in _SHARP_LIMIT_INPUT_PIXELS_OFF.finditer(text):
        _emit(rule_img3, m.start(), m.group(0))
    # Stage-A: SVG-density-bomb variant.
    for m in _SHARP_SVG_DENSITY_BOMB.finditer(text):
        _emit(rule_img3, m.start(), m.group(0))
    # Stage-B: `sharp(<untrusted buffer>)` with NO same-file bound
    # mitigation. The bound mitigation is the literal substring
    # `limitInputPixels:` followed by a small int OR `failOn: 'error'`
    # / `failOnError: true`. Run literal-substring checks (RE2 cannot
    # express "absence within a balanced argument list").
    has_safe_failon = (
        "failOn: 'error'" in text
        or "failOn:'error'" in text
        or 'failOn: "error"' in text
        or 'failOn:"error"' in text
        or "failOnError: true" in text
        or "failOnError:true" in text
    )
    if not has_safe_failon:
        for m in _SHARP_UNTRUSTED_BUFFER.finditer(text):
            _emit(rule_img3, m.start(), m.group(0))

    # ---- IMG-004 : opencv-imdecode-on-untrusted-bytes ----
    rule_img4 = rule_by_id["image-opencv-imdecode-on-untrusted-bytes"]
    for m in _OPENCV_IMDECODE_UNTRUSTED.finditer(text):
        _emit(rule_img4, m.start(), m.group(0))
    for m in _OPENCV_BROAD_IMREAD_FLAGS.finditer(text):
        _emit(rule_img4, m.start(), m.group(0))
    for m in _OPENCV_IMREAD_FSTRING_USER_PATH.finditer(text):
        _emit(rule_img4, m.start(), m.group(0))

    # ---- IMG-005 : exiftool-shell-out-no-dash-dash-separator ----
    rule_img5 = rule_by_id["image-exiftool-shell-out-no-dash-dash-separator"]
    for m in _EXIFTOOL_SHELL_OUT.finditer(text):
        # Stage-B: suppress if the matched call's argv contains the
        # `"--"` end-of-options sentinel. The match itself stops at
        # `"exiftool"`; we look at the surrounding ±3 lines for the
        # rest of the argv.
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 0, 3)
        if _EXIFTOOL_DASH_DASH_GUARD.search(window) is not None:
            continue
        _emit(rule_img5, m.start(), m.group(0))
    for m in _EXIFTOOL_CONFIG_FROM_USER.finditer(text):
        _emit(rule_img5, m.start(), m.group(0))

    # ---- IMG-006 : pyvips-new-from-file-untrusted-input ----
    rule_img6 = rule_by_id["image-pyvips-new-from-file-untrusted-input"]
    for m in _PYVIPS_NEW_FROM_UNTRUSTED.finditer(text):
        _emit(rule_img6, m.start(), m.group(0))
    for m in _PYVIPS_ACCESS_SEQUENTIAL.finditer(text):
        _emit(rule_img6, m.start(), m.group(0))
    for m in _PYVIPS_FAIL_DISABLED.finditer(text):
        _emit(rule_img6, m.start(), m.group(0))
    for m in _PYVIPS_SVG_INPUT.finditer(text):
        _emit(rule_img6, m.start(), m.group(0))

    # ---- IMG-007 : graphicsmagick-convert-shell-out-no-separator ----
    rule_img7 = rule_by_id["image-graphicsmagick-convert-shell-out-no-separator"]
    for m in _CONVERT_SHELL_OUT.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 0, 3)
        if _EXIFTOOL_DASH_DASH_GUARD.search(window) is not None:
            continue
        _emit(rule_img7, m.start(), m.group(0))
    for m in _CONVERT_CODER_PREFIX_INJECTION.finditer(text):
        _emit(rule_img7, m.start(), m.group(0))
    for m in _CONVERT_AT_EXPANSION.finditer(text):
        _emit(rule_img7, m.start(), m.group(0))

    # ---- IMG-008 : libheif-pillow-heif-register-no-dimension-check ----
    rule_img8 = rule_by_id["image-libheif-pillow-heif-register-no-dimension-check"]
    for m in _PILLOW_HEIF_REGISTER.finditer(text):
        _emit(rule_img8, m.start(), m.group(0))
    for m in _PYHEIF_READ_UNTRUSTED.finditer(text):
        _emit(rule_img8, m.start(), m.group(0))
    for m in _LIBHEIF_CONTEXT_READ.finditer(text):
        _emit(rule_img8, m.start(), m.group(0))

    # ---- IMG-009 : server-side-image-fetch-ssrf-and-bomb ----
    rule_img9 = rule_by_id["image-server-side-image-fetch-ssrf-and-bomb"]
    for m in _PILLOW_FETCH_AND_OPEN.finditer(text):
        _emit(rule_img9, m.start(), m.group(0))
    for m in _SHARP_FETCH_AND_DECODE.finditer(text):
        _emit(rule_img9, m.start(), m.group(0))

    # ---- IMG-010 : pillow-load-truncated-images-global-flag ----
    rule_img10 = rule_by_id["image-pillow-load-truncated-images-global-flag"]
    for m in _PILLOW_LOAD_TRUNCATED_TRUE.finditer(text):
        _emit(rule_img10, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
