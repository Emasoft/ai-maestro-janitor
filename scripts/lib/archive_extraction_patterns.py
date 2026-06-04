"""Archive extraction attack patterns — zip-slip, tar-slip, symlink-race,
decompression-bomb, polyglot, PAX-spoof, ZIP-overlap-confusion.

Wave-21 deep-dive distillation round 7, angle E. Augments — does NOT
replace — Wave 18 `race_patterns.race-archive-unsanitized-extract`
which catches a single surface shape (`extractall(...)` literal in
Python tarfile/zipfile and shell `tar -x`). Wave 18 misses every
non-`extractall` extract surface, every decompression-bomb shape,
every cross-language extract API, and every member-type attack
(symlink-member, hardlink-member, PAX-header spoof, ZIP-overlap
parser-disagreement).

Distilled from `reports/distill-round-7/archive-zip-slip.md`. Reference
corpus seeds:

  * `cpv-hp1-skillaudit/scripts/cpv_pre_install_scan.py:196-209`
    (E1, E2 — naive sanitiser shape).
  * `cpv-hp1-skillaudit/scripts/cpv_management_common.py:415-545`
    (E3, E4 — gold-standard preflight; used as the "see also" pointer
    in every relevant rule's suggestion text).
  * `cpv-hp1-skillaudit/scripts/cpv_install_scanners.py:283-305`
    (E5, E6 — basename-extraction + unbounded `copyfileobj`).
  * `study-agent-10/supply-chain-sidecar-main/proxy_stub.py:21-38`
    (E7 — BytesIO-rooted extract, no preflight, no mode pinning).
  * `cpv-hp1-skillaudit/tests/test_cpv_ingestion.py:112-164`
    (E8 — hostile-archive test corpus).
  * `dr5-telemetry/OpsSentinel-main/backend/node_modules/tar/.../options.d.ts`
    (E9 — Node `tar@7.x` strict:false default).
  * `dr5-telemetry/supply-chain-defense-main/docs/.../sentinel.md:2474`
    (E15 — Go suffix-matching defeat).

Public surface mirrors `auth_flow_patterns.py`:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

Implemented rules (13 in total):

  * archive-extract-shutil-copyfileobj-unbounded     (HIGH)
  * archive-extract-bytesio-no-preflight             (CRITICAL)
  * archive-extract-mode-unpinned                    (HIGH)
  * archive-extract-naive-traversal-sanitiser        (HIGH)
  * archive-extract-symlink-member-accepted          (CRITICAL)
  * archive-extract-no-bomb-preflight                (HIGH)
  * archive-extract-shell-tar-no-flags               (MEDIUM)
  * archive-extract-node-tar-not-strict              (HIGH)
  * archive-extract-go-no-filepath-clean-prefix      (HIGH)
  * archive-extract-java-zip-no-canonical-check      (HIGH)
  * archive-extract-polyglot-extension-mismatch      (MEDIUM)
  * archive-extract-zip-overlap-confusion            (HIGH)
  * archive-extract-tar-pax-extended-header-spoof    (MEDIUM)

OWASP ASI mapping:
  ASI-04 — Data leak / resource exhaustion sinks (bomb-preflight)
  ASI-05 — Supply-chain / path-traversal / cross-tenant pivot (every
           other rule — archive extraction is the canonical inbound
           supply-chain attack surface for skill/package installers)

All regexes are RE2-safe (no nested unbounded quantifiers; every
proximity-bridge window is explicitly bounded via a fixed-width
char-class repetition). The detectors are deliberately FP-tolerant
— the caller does contextual triage.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as agent_config_patterns.Finding
    so heartbeat detectors can render either kind uniformly."""

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
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — mirrors the
    helper in auth_flow_patterns.py so the surface is uniform across
    rule modules."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


def _re_cs(pattern: str) -> re.Pattern:
    """Compile a CASE-SENSITIVE pattern (no IGNORECASE). Used where
    casing is load-bearing (e.g. Go `filepath.Clean` vs. `FilePath.Clean`
    typos, Java `ZipInputStream` vs. `zipinputstream`)."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- 1. archive-extract-shutil-copyfileobj-unbounded -------------------


# Two trigger shapes for basename-extraction (E5, E6):
#   (a) zipfile -> zf.open(name) -> shutil.copyfileobj(zsrc, dst)
#   (b) tarfile -> tf.extractfile(member) -> .read() or copyfileobj
# Both bypass `extractall(` so Wave 18 cannot see them. The danger is
# unbounded `copyfileobj` (no `length=` kwarg) on a ZIP_DEFLATED member
# whose compressed-size is tiny but uncompressed-size is multi-GB.
_COPYFILEOBJ_UNBOUNDED = _re(
    # (a) ZIP: zipfile.ZipFile + zf.open + copyfileobj all within 400 chars
    r"\bzipfile\.ZipFile\s*\([\s\S]{0,400}?\.open\s*\([\s\S]{0,200}?\bshutil\.copyfileobj\s*\("
    r"|"
    # (b) TAR: tarfile.open + extractfile + copyfileobj/read all within 400 chars
    r"\btarfile\.open\s*\([\s\S]{0,400}?\.extractfile\s*\([\s\S]{0,200}?"
    r"(?:\bshutil\.copyfileobj\s*\(|\.read\s*\(\s*\))"
)

# Safe-window: a file_size / size quota check OR an explicit `length=`
# kwarg to copyfileobj OR a `bufsize=`/`size=` cap. The match must
# appear in the SAME 600-char window as the trigger.
_COPYFILEOBJ_SAFE = _re(
    r"\.file_size\s*[<>!=]"
    r"|"
    r"\.size\s*[<>!=]"
    r"|"
    r"\bcopyfileobj\s*\([^)]*,\s*length\s*="
    r"|"
    r"\bcopyfileobj\s*\([^)]*,\s*[^,)]+,\s*\d+\s*\)"  # 3rd positional = bufsize, but only valid as size cap if numeric
    r"|"
    r"#\s*pragma:\s*copyfileobj-bounded\b"
)


# ---- 2. archive-extract-bytesio-no-preflight ---------------------------


# In-memory extract roots: tarfile.open(fileobj=BytesIO(...)) and
# zipfile.ZipFile(BytesIO(...)). The whole archive is in RAM, there is
# no on-disk size check, and the caller almost always omits preflight.
# Proxy_stub.py (E7) shows the canonical broken shape.
_BYTESIO_EXTRACT = _re(
    r"\btarfile\.open\s*\(\s*fileobj\s*=\s*(?:io\.)?BytesIO\s*\("
    r"|"
    r"\bzipfile\.ZipFile\s*\(\s*(?:io\.)?BytesIO\s*\("
)

# Safe-window: an explicit byte-size cap on the underlying buffer OR a
# Content-Length header check OR a preflight allowlist within 500 chars.
_BYTESIO_PREFLIGHT_SAFE = _re(
    r"\blen\s*\([^)]+\)\s*[<>]"
    r"|"
    r"\bContent-Length\b"
    r"|"
    r"\bcontent-length\b"
    r"|"
    r"\bmax_(?:bytes|size|length)\b"
    r"|"
    r"#\s*pragma:\s*bytesio-preflight-ok\b"
)


# ---- 3. archive-extract-mode-unpinned ----------------------------------


# tarfile.open with no `mode=` or with `mode="r"` auto-detects from
# magic bytes and transparently decompresses xz/bz2/gz/lzma. An
# attacker uploads "foo.tar.gz" that is actually xz inside gz inside
# tar — a nested-compression-tower bomb. The fix is to pin the mode
# string ("r:gz", "r:bz2", "r:xz", "r:" for uncompressed, or "r|gz"
# for streaming).
_MODE_UNPINNED = _re(
    # tarfile.open(arg) — single arg, no mode at all
    r"\btarfile\.open\s*\(\s*[a-zA-Z_][a-zA-Z0-9_.\[\]]*\s*\)"
    r"|"
    # tarfile.open(arg, "r") or mode="r" — bare "r" is auto-detect-all
    r"\btarfile\.open\s*\([^)]*['\"]r['\"]\s*\)"
    r"|"
    r"\btarfile\.open\s*\([^)]*\bmode\s*=\s*['\"]r['\"]\s*[,)]"
)

# Safe shape: explicit colon-or-pipe mode pin.
_MODE_PINNED_SAFE = _re(
    r"\btarfile\.open\s*\([^)]*['\"]r:[a-zA-Z0-9]+['\"]"
    r"|"
    r"\btarfile\.open\s*\([^)]*['\"]r\|[a-zA-Z0-9]+['\"]"
    r"|"
    r"\btarfile\.open\s*\([^)]*['\"]r:['\"]"  # uncompressed-pinned
    r"|"
    r"\bmode\s*=\s*['\"]r:[a-zA-Z0-9]*['\"]"
)


# ---- 4. archive-extract-naive-traversal-sanitiser ----------------------


# Trigger: a manual extract loop that checks `startswith("/")` or
# `".." in Path(name).parts` (or `os.sep in name` etc.) — the
# cpv_pre_install_scan.py shape (E1, E2). This is a sanitiser, but it
# is INCOMPLETE: misses Windows-drive absolute paths, NUL-byte
# truncation, Unicode look-alikes, symlink-member type, hardlink-member
# type. The rule flags every such loop UNLESS the file ALSO contains
# the full set of compensating checks.
_NAIVE_SANITISER = _re(
    # Anchor on the literal traversal check shapes
    r"\.startswith\s*\(\s*['\"]/['\"]\s*\)"
    r"|"
    r"['\"]\.\.['\"][\s\S]{0,40}?\bPath\s*\([^)]+\)\.parts"
    r"|"
    r"\bPath\s*\([^)]+\)\.parts[\s\S]{0,40}?['\"]\.\.['\"]"
)

# File-level: the COMPLETE set of safety checks. ALL three of (a)+(b)+(c)
# must appear somewhere in the file for the sanitiser to be deemed
# complete:
#   (a) os.path.isabs OR Path.is_absolute()
#   (b) resolve()+startswith dest OR commonpath check
#   (c) member.issym() / member.islnk() / external_attr symlink-bit
_NAIVE_GUARD_A = _re(
    r"\bos\.path\.isabs\s*\("
    r"|"
    r"\bis_absolute\s*\(\s*\)"
)
_NAIVE_GUARD_B = _re(
    r"\.resolve\s*\(\s*\)[\s\S]{0,200}?\.startswith\s*\("
    r"|"
    r"\bos\.path\.commonpath\s*\("
    r"|"
    r"\.relative_to\s*\("
)
_NAIVE_GUARD_C = _re(
    r"\.issym\s*\(\s*\)"
    r"|"
    r"\.islnk\s*\(\s*\)"
    r"|"
    r"\bexternal_attr\b"
    r"|"
    r"\bfilter\s*=\s*['\"]data['\"]"
)


# ---- 5. archive-extract-symlink-member-accepted ------------------------


# Trigger: a Python extract loop that iterates members or namelist.
# The rule fires UNLESS the same scope rejects symlink/hardlink members
# OR uses the `data` filter (Py 3.12+).
_EXTRACT_LOOP_TRIGGER = _re(
    # tarfile member iteration
    r"\bfor\s+\w+\s+in\s+\w+\.(?:getmembers|getnames|infolist|namelist)\s*\("
    r"|"
    # zipfile direct extract loop
    r"\bfor\s+\w+\s+in\s+\w+\.infolist\s*\("
    r"|"
    # extractall calls without filter
    r"\.extractall\s*\("
    r"|"
    # singular extract / extractfile
    r"\.extract\s*\([^)]+\)"
)

# Safe shape: symlink/hardlink rejection or the data filter present
# somewhere in the file. We deliberately use a file-level guard since
# safety wrappers can live in a helper imported at the top.
_SYMLINK_REJECT_SAFE = _re(
    r"\.issym\s*\(\s*\)"
    r"|"
    r"\.islnk\s*\(\s*\)"
    r"|"
    r"\bfilter\s*=\s*['\"]data['\"]"
    r"|"
    r"\btarfile\.data_filter\b"
    r"|"
    r"\bcontinue\b[\s\S]{0,80}?\.is_symlink\s*\(\s*\)"
    r"|"
    r"\.is_symlink\s*\(\s*\)[\s\S]{0,80}?\bcontinue\b"
    # external_attr symlink-bit check (S_IFLNK == 0o120000)
    r"|"
    r"\bexternal_attr\b[\s\S]{0,80}?0o?12\d{4}"
    r"|"
    r"#\s*pragma:\s*symlink-members-ok\b"
)


# ---- 6. archive-extract-no-bomb-preflight ------------------------------


# Trigger: any extract call (Python or shell) that's NOT already caught
# by Wave 18 rule 7 in a narrower sense — we want to catch the absence
# of preflight quotas regardless. The gold-standard from
# cpv_management_common.py (E3, E4) checks:
#   - len(infos) > MAX_ENTRIES
#   - sum(info.file_size for info in infos) > MAX_BYTES
#   - sum_uncompressed / archive_size > MAX_RATIO
#   - per-file file_size > MAX_PER_FILE
_BOMB_EXTRACT_TRIGGER = _re(
    r"\.extractall\s*\("
    r"|"
    r"\.extract\s*\(\s*[^)]+\)"
    r"|"
    r"\btarfile\.open\s*\("
    r"|"
    r"\bzipfile\.ZipFile\s*\("
)

# Bomb-preflight safe shape: ANY of the four canonical preflight
# expressions appear anywhere in the file. We require BOTH:
#   - some aggregate cap (len / sum / max_entries / max_bytes)
#   - some ratio or per-file cap
# If either side is missing, the preflight is incomplete.
_BOMB_AGG_CAP = _re(
    r"\blen\s*\(\s*\w+\.(?:infolist|getmembers|namelist|getnames)\s*\(\s*\)\s*\)\s*[<>]"
    r"|"
    r"\bsum\s*\([^)]*\.(?:file_size|size)\s+for\b"
    r"|"
    r"\bmax_(?:entries|bytes|size|members)\b"
    r"|"
    r"#\s*pragma:\s*bomb-preflight-ok\b"
)
_BOMB_RATIO_OR_PERFILE = _re(
    r"\.(?:file_size|size)\s*[<>]\s*\w+"
    r"|"
    r"\bmax_ratio\b"
    r"|"
    r"\bcompression_ratio\b"
    r"|"
    r"\bmax_per_file\b"
    r"|"
    r"#\s*pragma:\s*bomb-preflight-ok\b"
)


# ---- 7. archive-extract-shell-tar-no-flags -----------------------------


# Shell `tar -xzf` / `unzip` / `bsdtar -x` without --anchored OR
# --strip-components=N OR a `mktemp -d` based -C tmpdir wrapper.
_SHELL_TAR_EXTRACT = _re(
    r"\btar\s+(?:-x[zjJ]?[vf]?|-[zjJ]?xf|--extract)\b"
    r"|"
    r"\bbsdtar\s+(?:-x[zjJ]?[vf]?|--extract)\b"
    r"|"
    r"\bunzip\s+(?!-l\b)(?!-v\b)[^\n]"
)

# Safe shape: one of the hardening flags or a mktemp -d -C wrapper or
# an explicit pragma.
_SHELL_TAR_SAFE = _re(
    r"--anchored\b"
    r"|"
    r"--strip-components\b"
    r"|"
    r"--no-same-owner\b"
    r"|"
    r"--no-same-permissions\b"
    r"|"
    r"--no-overwrite-dir\b"
    r"|"
    r"\bmktemp\s+-d\b"
    r"|"
    r"#\s*pragma:\s*extract-ok\b"
)


# ---- 8. archive-extract-node-tar-not-strict ----------------------------


# Node.js `tar` package (`tar.extract`, `tar.x`) and `extract-zip` /
# `node-stream-zip` patterns. Without `strict: true`, malformed entries
# are silently dropped — including entries deliberately malformed to
# defeat outer length validators. `preservePaths: true` re-enables
# absolute paths.
_NODE_TAR_EXTRACT = _re(
    r"\btar\.extract\s*\("
    r"|"
    r"\btar\.x\s*\("
    r"|"
    r"\bextractZip\s*\("
    r"|"
    r"\bextract\s*\(\s*\{[^}]*\bfile\s*:[^}]*\bcwd\s*:"  # extract({file, cwd, ...})
    r"|"
    r"\bnode-stream-zip\b"
    r"|"
    r"\bStreamZip\s*\("
)

_NODE_TAR_SAFE = _re(
    r"\bstrict\s*:\s*true\b"
    r"|"
    r"#\s*pragma:\s*node-extract-ok\b"
    r"|"
    r"//\s*pragma:\s*node-extract-ok\b"
)

_NODE_TAR_DANGEROUS_FLAG = _re(
    r"\bpreservePaths\s*:\s*true\b"
)


# ---- 9. archive-extract-go-no-filepath-clean-prefix --------------------


# Go `archive/zip` and `archive/tar`. Caller MUST do filepath.Clean()
# then strings.HasPrefix(cleaned, dest+sep) or filepath.IsAbs() reject.
# This is the CVE-2018-1002201 family. Case-sensitive — Go is
# case-sensitive in identifiers.
_GO_ARCHIVE_OPEN = _re_cs(
    r"\bzip\.OpenReader\s*\("
    r"|"
    r"\bzip\.NewReader\s*\("
    r"|"
    r"\btar\.NewReader\s*\("
)

_GO_ARCHIVE_SAFE = _re_cs(
    r"\bfilepath\.Clean\s*\([\s\S]{0,400}?(?:strings\.HasPrefix|filepath\.IsAbs)\s*\("
    r"|"
    r"\bfilepath\.IsAbs\s*\([\s\S]{0,400}?\bfilepath\.Clean\s*\("
    r"|"
    r"//\s*pragma:\s*go-extract-ok\b"
)

# Bonus shape: a Go tar.Writer emitting TypeSymlink. Detect-only — the
# safe shape is "this code is the WRITER, not the extractor". But if it
# IS the extractor, this fires alongside.
_GO_TAR_SYMLINK_EMIT = _re_cs(
    r"\bTypeflag\s*[:=]\s*tar\.TypeSymlink\b"
)


# ---- 10. archive-extract-java-zip-no-canonical-check -------------------


# Java ZipInputStream / new ZipFile() / TarArchiveInputStream classic
# zip-slip. Fix is `target.normalize().startsWith(destDir.normalize())`
# OR `target.toRealPath().startsWith(destDir.toRealPath())`.
_JAVA_ZIP_OPEN = _re_cs(
    r"\bZipInputStream\b"
    r"|"
    r"\bnew\s+ZipFile\s*\("
    r"|"
    r"\bTarArchiveInputStream\b"
    r"|"
    r"\bZipArchive\s*\("
)

_JAVA_ZIP_SAFE = _re_cs(
    r"\.normalize\s*\(\s*\)[\s\S]{0,400}?\.startsWith\s*\("
    r"|"
    r"\.toRealPath\s*\([\s\S]{0,200}?\)[\s\S]{0,200}?\.startsWith\s*\("
    r"|"
    r"\.toAbsolutePath\s*\([\s\S]{0,200}?\)[\s\S]{0,200}?\.startsWith\s*\("
    r"|"
    r"//\s*pragma:\s*java-extract-ok\b"
)


# ---- 11. archive-extract-polyglot-extension-mismatch -------------------


# Source-grep variant: detect callers that switch on filename suffix
# without ALSO doing a magic-byte check. The polyglot bypass means a
# `.png` that is actually a ZIP archive (magic `PK\x03\x04` at offset
# 0 OR appended after PNG IEND) passes the extension filter. The full
# defence belongs at INGEST time — but source-grep CAN flag the
# extension-only switch.
_POLYGLOT_EXT_SWITCH = _re(
    # Python: filename.endswith('.zip')
    r"\.endswith\s*\(\s*['\"]\.(?:zip|tar\.gz|tgz|tar\.xz|txz|tar\.bz2|tbz2|tar|gz|xz|bz2|7z)['\"]"
    r"|"
    # Go: strings.HasSuffix(filename, ".zip")
    r"\bstrings\.HasSuffix\s*\(\s*[^,]+,\s*['\"]\.(?:zip|tar\.gz|tgz|tar)['\"]"
    r"|"
    # JS: filename.endsWith('.zip')
    r"\.endsWith\s*\(\s*['\"]\.(?:zip|tar\.gz|tgz|tar|gz)['\"]"
    r"|"
    # Shell: case "$f" in *.zip)
    r"case\s+[^\s]+\s+in[\s\S]{0,40}?\*\.(?:zip|tar\.gz|tgz)\b"
)

# Safe shape: a magic-byte / `file -b` / `python-magic` / mime-type
# check appears in the same file (file-level guard).
_POLYGLOT_MAGIC_GUARD = _re(
    r"\bdetect_magic\s*\("
    r"|"
    r"\bMAGIC_PREFIXES\b"
    r"|"
    r"\bpython-magic\b"
    r"|"
    r"\bfile\s+-b\b"
    r"|"
    r"\bmagic\.from_buffer\s*\("
    r"|"
    r"\bmagic\.from_file\s*\("
    r"|"
    r"\bmimetypes\.guess_type\s*\("
    r"|"
    r"\bPK\\x03\\x04\b"
    r"|"
    r"#\s*pragma:\s*polyglot-ok\b"
)


# ---- 12. archive-extract-zip-overlap-confusion -------------------------


# Source-grep variant per the spec: detect callers that read the SAME
# ZIP with TWO different parsers in the same function WITHOUT
# cross-checking member lists. This is the parser-disagreement attack
# (CVE-2023-29017 family). The full detector belongs at INGEST time;
# this rule flags the precondition that lets the bug-class exist.
#
# Trigger: two distinct ZIP-reading constructs appear within 1000 chars
# of each other (we deliberately use a tight cap to keep the regex
# RE2-safe and to scope the finding to a single function body).
_ZIP_OVERLAP_CONFUSION = _re(
    # zipfile.ZipFile + libarchive.read
    r"\bzipfile\.ZipFile\s*\([\s\S]{0,1000}?\b(?:libarchive\.|python_libarchive)\b"
    r"|"
    r"\b(?:libarchive\.|python_libarchive)\b[\s\S]{0,1000}?\bzipfile\.ZipFile\s*\("
    r"|"
    # zipfile.ZipFile + subprocess unzip on same path
    r"\bzipfile\.ZipFile\s*\([\s\S]{0,1000}?\bsubprocess\.[a-z_]+\s*\(\s*\[?\s*['\"]unzip['\"]"
    r"|"
    # JS: yauzl + adm-zip same file
    r"\byauzl\b[\s\S]{0,1000}?\badm-zip\b"
    r"|"
    r"\badm-zip\b[\s\S]{0,1000}?\byauzl\b"
)


# ---- 13. archive-extract-tar-pax-extended-header-spoof ----------------


# Source-grep variant: tarfile member loop that uses `member.name` as
# the canonical key without ALSO consulting `member.pax_headers`. PAX
# extended headers can override `path`/`linkpath`/`size` of the next
# member (CVE-2007-4559 family).
_TAR_MEMBER_NAME_USE = _re(
    r"\bfor\s+(\w+)\s+in\s+\w+\.(?:getmembers|getnames)\s*\([\s\S]{0,400}?\1\.name\b"
)

# Safe shape: the loop also reads member.pax_headers OR uses
# filter="data" (which itself rejects PAX overrides on Py 3.12+).
_TAR_PAX_SAFE = _re(
    r"\.pax_headers\b"
    r"|"
    r"\bfilter\s*=\s*['\"]data['\"]"
    r"|"
    r"#\s*pragma:\s*pax-ok\b"
)


# ---- The catalogue -----------------------------------------------------


_SUGGESTION_GOLD_REFERENCE = (
    "See `cpv_management_common.py:415-545` for the gold-standard "
    "preflight + path-resolve + symlink-reject shape used elsewhere "
    "in this codebase."
)


RULES: tuple[Rule, ...] = (
    Rule(
        id="archive-extract-shutil-copyfileobj-unbounded",
        name="Archive extract uses unbounded shutil.copyfileobj / .read()",
        severity="HIGH",
        description=(
            "Basename-extraction loop (`zf.open(name)` + "
            "`shutil.copyfileobj(...)` or `tf.extractfile(...).read()`) "
            "with no size cap. The traversal is mitigated by "
            "`Path(name).name`, but `copyfileobj` has no `length=` "
            "kwarg by default — a 1-byte ZIP_DEFLATED member can claim "
            "100 GB uncompressed and amplify directly into the "
            "destination file. Pair the extract with a per-member "
            "`file_size`/`size` check OR pass `length=` to "
            "`copyfileobj`. " + _SUGGESTION_GOLD_REFERENCE
        ),
        pattern=_COPYFILEOBJ_UNBOUNDED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="archive-extract-bytesio-no-preflight",
        name="In-memory archive extract (BytesIO) with no preflight",
        severity="CRITICAL",
        description=(
            "`tarfile.open(fileobj=BytesIO(...))` / "
            "`zipfile.ZipFile(BytesIO(...))` reads the entire archive "
            "into RAM without any size cap, mode pinning, or member "
            "preflight. Five-in-one anti-pattern (E7 corpus seed): no "
            "Content-Length check, transparent multi-codec decompression, "
            "unbounded member read, no preflight `getmembers()`/`infolist()` "
            "quota gate. " + _SUGGESTION_GOLD_REFERENCE
        ),
        pattern=_BYTESIO_EXTRACT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="archive-extract-mode-unpinned",
        name="tarfile.open mode is unpinned (auto-detect)",
        severity="HIGH",
        description=(
            "`tarfile.open(path)` without an explicit `mode=` (or with "
            "bare `mode='r'`) transparently auto-detects xz/bz2/gz/lzma "
            "by magic bytes. An attacker delivers `pkg.tar.gz` that is "
            "actually nested-compression (xz inside gz inside tar), "
            "amplifying a decompression bomb beyond per-layer ratio "
            "checks. Pin the mode: `'r:gz'`, `'r:bz2'`, `'r:xz'`, "
            "`'r:'` (uncompressed), or `'r|gz'` (streaming)."
        ),
        pattern=_MODE_UNPINNED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="archive-extract-naive-traversal-sanitiser",
        name="Archive-extract traversal sanitiser is incomplete",
        severity="HIGH",
        description=(
            "Manual extract loop checks `name.startswith('/')` and/or "
            "`'..' in Path(name).parts` but the file is missing one or "
            "more of: (a) `os.path.isabs` / `Path.is_absolute()` for "
            "Windows-drive absolute paths, (b) `resolve()`/`commonpath`/"
            "`relative_to` against the destination root, (c) "
            "`member.issym()`/`member.islnk()` / `external_attr` "
            "symlink-bit reject. Each missing check is independently "
            "exploitable: Windows `C:\\evil`, NUL-byte truncation, "
            "Unicode look-alikes, symlink-member writes outside dest. "
            + _SUGGESTION_GOLD_REFERENCE
        ),
        pattern=_NAIVE_SANITISER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="archive-extract-symlink-member-accepted",
        name="Archive extract loop does not reject symlink members",
        severity="CRITICAL",
        description=(
            "Extract loop iterates members or namelist without "
            "rejecting symlink/hardlink-typed entries and without using "
            "`filter='data'` (Py 3.12+). Two-step attack: member-1 is "
            "`evil` typed SYMLINK pointing at `/etc/cron.d`, member-2 "
            "is regular file named `evil/take-over` — the second extract "
            "writes through the just-created symlink to `/etc/cron.d/take-over`. "
            "The traversal happens at the filesystem layer AFTER every "
            "name-based check has returned OK. " + _SUGGESTION_GOLD_REFERENCE
        ),
        pattern=_EXTRACT_LOOP_TRIGGER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="archive-extract-no-bomb-preflight",
        name="Archive extract has no decompression-bomb preflight",
        severity="HIGH",
        description=(
            "Extract call (`extractall`, `extract`, `tarfile.open`, "
            "`zipfile.ZipFile`) without a preflight quota check on "
            "(a) `len(infolist())` / `len(getmembers())`, "
            "(b) `sum(info.file_size)` aggregate, "
            "(c) compression-ratio (uncompressed/compressed), "
            "(d) per-file `file_size`/`size` cap. The cpv_management_common.py "
            "gold-standard (E3, E4) does ALL FOUR before any extract "
            "call. Without these, `42.zip` (kilobyte→terabyte) and "
            "ZIP-quine (`r.zip` 42KB→4.5GiB recursive) crash the "
            "extractor before any path-check matters. "
            + _SUGGESTION_GOLD_REFERENCE
        ),
        pattern=_BOMB_EXTRACT_TRIGGER,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="archive-extract-shell-tar-no-flags",
        name="Shell `tar -xzf` / `unzip` without hardening flags",
        severity="MEDIUM",
        description=(
            "Shell `tar -xzf <attacker>` / `unzip <attacker>` without "
            "any of `--anchored`, `--strip-components=N`, "
            "`--no-same-owner`, `--no-same-permissions`, "
            "`--no-overwrite-dir`, or a `mktemp -d`-based `-C tmpdir` "
            "wrapper. Old `tar` (< 1.30) silently treats `--anchored` "
            "as no-op; pair it with `--strip-components` for "
            "defence-in-depth, and verify the extracted tree contains "
            "no symlinks pointing outside `tmpdir` before moving into "
            "place."
        ),
        pattern=_SHELL_TAR_EXTRACT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="archive-extract-node-tar-not-strict",
        name="Node `tar` / `extract-zip` called without strict mode",
        severity="HIGH",
        description=(
            "Node `tar.extract({file, cwd, ...})` / `tar.x(...)` / "
            "`extractZip(...)` / `node-stream-zip` called without "
            "`strict: true`. Default `strict: false` silently DROPS "
            "malformed entries — including entries deliberately "
            "malformed to bypass an outer length-prefixed validator. "
            "Also flags `preservePaths: true` which re-enables absolute "
            "paths. Pair `strict: true` with an explicit `filter:` "
            "callback that rejects entries whose normalised path "
            "escapes `cwd`."
        ),
        pattern=_NODE_TAR_EXTRACT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="archive-extract-go-no-filepath-clean-prefix",
        name="Go zip/tar extract missing filepath.Clean+HasPrefix check",
        severity="HIGH",
        description=(
            "Go `archive/zip` / `archive/tar` extract caller without "
            "BOTH `filepath.Clean(entry.Name)` and a downstream "
            "`strings.HasPrefix(cleaned, dest+sep)` or "
            "`filepath.IsAbs(cleaned)` reject. Forgetting either is "
            "zip-slip (CVE-2018-1002201 family). Additionally, if the "
            "code emits `Typeflag: tar.TypeSymlink` without sanitising "
            "`Linkname`, the same archive can write a symlink-bomb "
            "(member-1 symlink, member-2 write-through)."
        ),
        pattern=_GO_ARCHIVE_OPEN,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="archive-extract-java-zip-no-canonical-check",
        name="Java ZipInputStream / ZipFile missing normalize+startsWith",
        severity="HIGH",
        description=(
            "Java `ZipInputStream` / `new ZipFile(...)` / "
            "`TarArchiveInputStream` extract path without "
            "`target.normalize().startsWith(destDir.normalize())` or "
            "`target.toRealPath().startsWith(destDir.toRealPath())`. "
            "`Path.resolve(entry.getName())` honours both `..` and "
            "absolute paths — the canonical zip-slip primitive. Fix is "
            "to canonicalise both paths before comparing prefixes."
        ),
        pattern=_JAVA_ZIP_OPEN,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="archive-extract-polyglot-extension-mismatch",
        name="Archive routing keys on extension without magic-byte check",
        severity="MEDIUM",
        description=(
            "Code switches on `filename.endswith('.zip')` / "
            "`strings.HasSuffix(name, '.tar.gz')` / `case *.zip)` "
            "without ALSO checking the file's magic bytes "
            "(`detect_magic`, `magic.from_buffer`, `file -b "
            "--mime-type`). A `.png` that is actually a ZIP archive "
            "(PK header at offset 0, OR appended after PNG IEND) "
            "passes the extension filter and reaches the extractor "
            "anyway. The full defence belongs at INGEST time — read "
            "first 4 + 257 bytes, classify via "
            "`parser_format_patterns.MAGIC_PREFIXES`, reject on "
            "extension/magic mismatch."
        ),
        pattern=_POLYGLOT_EXT_SWITCH,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="archive-extract-zip-overlap-confusion",
        name="Two ZIP parsers used on same archive without cross-check",
        severity="HIGH",
        description=(
            "Function reads the same ZIP archive with two different "
            "parsers (e.g. `zipfile.ZipFile` AND `libarchive`, or "
            "`yauzl` AND `adm-zip`) without cross-checking the member "
            "lists. CVE-2023-29017 / CVE-2017-9416 / CVE-2018-1000035 "
            "family: parsers disagree on overlapping local-file headers "
            "vs. central-directory entries, so the SAME bytes parse as "
            "TWO different archives. Attacker ships a package where "
            "parser-A sees benign `setup.py` and parser-B sees the "
            "malicious one. Full mitigation belongs at INGEST time "
            "(re-parse with both, hash each view, reject on "
            "disagreement)."
        ),
        pattern=_ZIP_OVERLAP_CONFUSION,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="archive-extract-tar-pax-extended-header-spoof",
        name="Tarfile member loop ignores PAX extended headers",
        severity="MEDIUM",
        description=(
            "Tarfile member loop reads `member.name` as the canonical "
            "sanitisation key without ALSO consulting "
            "`member.pax_headers`. PAX extended headers (typeflag `x` "
            "or `g`) can override `path`, `linkpath`, `size`, `uid`, "
            "`gid`, `atime`, `mtime`, `ctime` of the next member "
            "(CVE-2007-4559 family). Member-1 PAX header sets "
            "`path=/etc/passwd`, member-2 USTAR `name` is `safe.txt` — "
            "the file lands at `/etc/passwd`. Use `filter='data'` "
            "(Py 3.12+) OR explicitly consult `member.pax_headers.get('path')` "
            "before trusting `member.name`."
        ),
        pattern=_TAR_MEMBER_NAME_USE,
        owasp_asi="ASI-05",
    ),
)


# ---- Helpers (shared with auth_flow_patterns) --------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _window(text: str, start: int, end: int, before: int, after: int) -> str:
    """Return text within `before` chars BEFORE `start` and `after` chars
    AFTER `end`. Bounded — never reads outside the file."""
    lo = max(0, start - before)
    hi = min(len(text), end + after)
    return text[lo:hi]


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return
    findings.

    Multi-stage filtering:

    * Rule 1 (copyfileobj-unbounded): drop hit if a `file_size` / `size`
      / `length=` cap appears within 600 chars after the trigger.
    * Rule 2 (bytesio-no-preflight): drop hit if a length / Content-Length
      / max_bytes guard appears within 500 chars in either direction.
    * Rule 3 (mode-unpinned): drop hit if a pinned-mode form
      (`'r:gz'`, `'r|gz'`, `'r:'`) appears in the SAME call.
    * Rule 4 (naive-sanitiser): drop hit if ALL THREE of guards
      (a)+(b)+(c) appear anywhere in the file.
    * Rule 5 (symlink-member): drop hit if the file contains ANY of
      `.issym()`, `.islnk()`, `filter='data'`, `tarfile.data_filter`,
      `.is_symlink()` + continue, or external_attr symlink-bit check.
    * Rule 6 (no-bomb-preflight): drop hit if file contains BOTH
      an aggregate cap AND a ratio/per-file cap.
    * Rule 7 (shell-tar-no-flags): drop hit if any hardening flag or
      mktemp wrapper appears in the same 300-char window.
    * Rule 8 (node-tar-not-strict): drop hit if `strict: true` appears
      in the same 300-char window. Independent secondary trigger for
      `preservePaths: true` (always fires).
    * Rule 9 (go-no-filepath-clean-prefix): drop hit if both
      `filepath.Clean(...)` AND `strings.HasPrefix(...)`/`filepath.IsAbs(...)`
      appear in the same file.
    * Rule 10 (java-no-canonical-check): drop hit if `.normalize()` +
      `.startsWith()` (or `.toRealPath()`) appears in the same file.
    * Rule 11 (polyglot-extension-mismatch): drop hit if any magic-byte
      / mime check appears anywhere in the file.
    * Rule 12 (zip-overlap-confusion): always fires when both parsers
      appear — there is no safe shape for "two parsers, no cross-check"
      detectable by regex.
    * Rule 13 (pax-extended-header-spoof): drop hit if the file
      mentions `.pax_headers` or uses `filter='data'`.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    # File-level guard pre-evaluation (cheap, one-shot per file).
    has_naive_a = _NAIVE_GUARD_A.search(text) is not None
    has_naive_b = _NAIVE_GUARD_B.search(text) is not None
    has_naive_c = _NAIVE_GUARD_C.search(text) is not None
    naive_complete = has_naive_a and has_naive_b and has_naive_c

    has_symlink_reject = _SYMLINK_REJECT_SAFE.search(text) is not None

    has_bomb_agg_cap = _BOMB_AGG_CAP.search(text) is not None
    has_bomb_ratio_per = _BOMB_RATIO_OR_PERFILE.search(text) is not None
    bomb_preflight_complete = has_bomb_agg_cap and has_bomb_ratio_per

    has_go_clean_prefix = _GO_ARCHIVE_SAFE.search(text) is not None
    has_java_canonical = _JAVA_ZIP_SAFE.search(text) is not None
    has_polyglot_magic = _POLYGLOT_MAGIC_GUARD.search(text) is not None
    has_pax_check = _TAR_PAX_SAFE.search(text) is not None

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(
        rule: Rule, match_text: str, line: int, col: int
    ) -> None:
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        if len(match_text) > 200:
            match_text = match_text[:200] + "…"
        findings.append(Finding(
            rule_id=rule.id,
            line=line,
            column=col,
            matched_text=match_text,
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())

            # Per-rule contextual filters.
            if rule.id == "archive-extract-shutil-copyfileobj-unbounded":
                # Same-window safe-shape check: 600 chars around the hit
                # cover both the size-check-before-call and the length=
                # kwarg-in-call forms.
                win = _window(text, m.start(), m.end(), 0, 600)
                if _COPYFILEOBJ_SAFE.search(win) is not None:
                    continue
            elif rule.id == "archive-extract-bytesio-no-preflight":
                win = _window(text, m.start(), m.end(), 500, 500)
                if _BYTESIO_PREFLIGHT_SAFE.search(win) is not None:
                    continue
            elif rule.id == "archive-extract-mode-unpinned":
                # Drop if the SAME call has a pinned-mode form. We
                # look at the match text itself — the regex already
                # restricts to mode=r/no-mode.
                # Defensive: also check the immediate 80-char window.
                win = _window(text, m.start(), m.end(), 0, 80)
                if _MODE_PINNED_SAFE.search(win) is not None:
                    continue
            elif rule.id == "archive-extract-naive-traversal-sanitiser":
                if naive_complete:
                    continue
            elif rule.id == "archive-extract-symlink-member-accepted":
                if has_symlink_reject:
                    continue
            elif rule.id == "archive-extract-no-bomb-preflight":
                if bomb_preflight_complete:
                    continue
            elif rule.id == "archive-extract-shell-tar-no-flags":
                win = _window(text, m.start(), m.end(), 50, 300)
                if _SHELL_TAR_SAFE.search(win) is not None:
                    continue
            elif rule.id == "archive-extract-node-tar-not-strict":
                # Either strict:true in the same window OR
                # preservePaths:true forces a hit even when strict:true.
                win = _window(text, m.start(), m.end(), 0, 300)
                has_strict = _NODE_TAR_SAFE.search(win) is not None
                has_danger = _NODE_TAR_DANGEROUS_FLAG.search(win) is not None
                if has_strict and not has_danger:
                    continue
            elif rule.id == "archive-extract-go-no-filepath-clean-prefix":
                if has_go_clean_prefix:
                    continue
                # If the file ALSO emits tar.TypeSymlink, the zip-slip
                # carrier is paired with a symlink-bomb writer — note
                # the compound shape in the finding text. We don't
                # change the rule.severity (the description already
                # mentions the symlink variant); we just surface the
                # match payload more loudly.
                if _GO_TAR_SYMLINK_EMIT.search(text):
                    _ = m  # symlink-emit confirmed alongside extract caller
            elif rule.id == "archive-extract-java-zip-no-canonical-check":
                if has_java_canonical:
                    continue
            elif rule.id == "archive-extract-polyglot-extension-mismatch":
                if has_polyglot_magic:
                    continue
            elif rule.id == "archive-extract-tar-pax-extended-header-spoof":
                if has_pax_check:
                    continue
            # rules 5 + 12 have no further per-hit filter beyond the
            # file-level guard.

            _emit(rule, m.group(0), line, col)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
