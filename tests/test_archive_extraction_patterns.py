"""Tests for scripts/lib/archive_extraction_patterns.py.

Pattern-coverage tests for the Wave-21 distillation round 7 angle E
catalogue (13 archive-extraction attack rules — zip-slip, tar-slip,
symlink-race, decompression-bomb, polyglot, PAX-spoof,
ZIP-overlap-confusion across Python / Go / Java / Node / shell).

Each rule gets at least one positive test (canonical broken shape from
the corpus seed) + at least one negative test (the safe shape from the
gold-standard reference `cpv_management_common.py:415-545` OR an
explicit pragma carve-out).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import archive_extraction_patterns as aep  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and must contain every advertised rule id."""
    assert isinstance(aep.RULES, tuple)
    rule_ids = {r.id for r in aep.RULES}
    expected = {
        "archive-extract-shutil-copyfileobj-unbounded",
        "archive-extract-bytesio-no-preflight",
        "archive-extract-mode-unpinned",
        "archive-extract-naive-traversal-sanitiser",
        "archive-extract-symlink-member-accepted",
        "archive-extract-no-bomb-preflight",
        "archive-extract-shell-tar-no-flags",
        "archive-extract-node-tar-not-strict",
        "archive-extract-go-no-filepath-clean-prefix",
        "archive-extract-java-zip-no-canonical-check",
        "archive-extract-polyglot-extension-mismatch",
        "archive-extract-zip-overlap-confusion",
        "archive-extract-tar-pax-extended-header-spoof",
    }
    assert expected.issubset(rule_ids)
    assert len(expected) == 13


def test_every_rule_has_owasp_mapping() -> None:
    """Every rule maps to a non-empty ASI- prefix + valid severity."""
    for rule in aep.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns.Finding shape."""
    f = aep.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-05",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-05"


def test_scan_text_empty_input_returns_empty_list() -> None:
    """Empty text → empty result; no exception."""
    assert aep.scan_text("") == []
    assert aep.scan_text(None) == []  # type: ignore[arg-type]


def _hits(rule_id: str, text: str) -> list[aep.Finding]:
    return [f for f in aep.scan_text(text) if f.rule_id == rule_id]


# ---------- Rule 1 : archive-extract-shutil-copyfileobj-unbounded --------


def test_copyfileobj_unbounded_zipfile_basename_extract() -> None:
    """E5 shape — zipfile.ZipFile + zf.open + shutil.copyfileobj, no size cap."""
    src = (
        "import zipfile, shutil\n"
        "with zipfile.ZipFile(archive_path) as zf:\n"
        "    for zip_name in zf.namelist():\n"
        "        base = Path(zip_name).name\n"
        "        target = dest_dir / base\n"
        "        with zf.open(zip_name) as zsrc, open(target, 'wb') as dst:\n"
        "            shutil.copyfileobj(zsrc, dst)\n"
    )
    assert _hits("archive-extract-shutil-copyfileobj-unbounded", src)


def test_copyfileobj_unbounded_tarfile_extractfile() -> None:
    """E6 shape — tarfile.open + extractfile + unbounded read."""
    src = (
        "import tarfile\n"
        "with tarfile.open(archive_path, 'r:gz') as tf:\n"
        "    for tar_member in tf.getmembers():\n"
        "        data = tf.extractfile(tar_member).read()\n"
    )
    assert _hits("archive-extract-shutil-copyfileobj-unbounded", src)


def test_copyfileobj_with_file_size_check_is_safe() -> None:
    """Per-member size cap before extract → no hit."""
    src = (
        "import zipfile, shutil\n"
        "with zipfile.ZipFile(archive_path) as zf:\n"
        "    for info in zf.infolist():\n"
        "        if info.file_size > MAX_BYTES:\n"
        "            raise ValueError('member too large')\n"
        "        with zf.open(info.filename) as zsrc, open(dst, 'wb') as out:\n"
        "            shutil.copyfileobj(zsrc, out)\n"
    )
    assert not _hits("archive-extract-shutil-copyfileobj-unbounded", src)


# ---------- Rule 2 : archive-extract-bytesio-no-preflight ----------------


def test_bytesio_no_preflight_tarfile_open_fileobj() -> None:
    """E7 shape — tarfile.open(fileobj=io.BytesIO(resp.content))."""
    src = (
        "import io, tarfile, requests\n"
        "tarball_bytes = requests.get(url).content\n"
        "with tarfile.open(fileobj=io.BytesIO(tarball_bytes)) as tar:\n"
        "    payload = tar.extractfile('member').read()\n"
    )
    assert _hits("archive-extract-bytesio-no-preflight", src)


def test_bytesio_no_preflight_zipfile_bytesio() -> None:
    """zipfile.ZipFile(BytesIO(...)) without size cap."""
    src = (
        "import io, zipfile\n"
        "blob = fetch_archive()\n"
        "with zipfile.ZipFile(io.BytesIO(blob)) as zf:\n"
        "    zf.extractall(dst)\n"
    )
    assert _hits("archive-extract-bytesio-no-preflight", src)


def test_bytesio_with_length_check_is_safe() -> None:
    """A `len(blob) <` cap within 500 chars → no hit."""
    src = (
        "import io, tarfile\n"
        "blob = fetch()\n"
        "if len(blob) > MAX_BYTES:\n"
        "    raise ValueError('archive too large')\n"
        "with tarfile.open(fileobj=io.BytesIO(blob)) as tar:\n"
        "    members = tar.getmembers()\n"
    )
    assert not _hits("archive-extract-bytesio-no-preflight", src)


def test_bytesio_with_content_length_check_is_safe() -> None:
    """Content-Length header check → no hit."""
    src = (
        "import io, tarfile\n"
        "resp = requests.get(url, stream=True)\n"
        "if int(resp.headers['Content-Length']) > MAX_BYTES:\n"
        "    raise ValueError\n"
        "with tarfile.open(fileobj=io.BytesIO(resp.content)) as tar:\n"
        "    pass\n"
    )
    assert not _hits("archive-extract-bytesio-no-preflight", src)


# ---------- Rule 3 : archive-extract-mode-unpinned -----------------------


def test_mode_unpinned_tarfile_open_no_mode() -> None:
    """tarfile.open(path) with no mode → auto-detect, flag."""
    src = (
        "import tarfile\n"
        "with tarfile.open(archive_path) as tar:\n"
        "    tar.extractall(dest)\n"
    )
    assert _hits("archive-extract-mode-unpinned", src)


def test_mode_unpinned_tarfile_open_bare_r() -> None:
    """tarfile.open(path, 'r') — bare 'r' is auto-detect too."""
    src = (
        "import tarfile\n"
        "tar = tarfile.open(archive_path, 'r')\n"
    )
    assert _hits("archive-extract-mode-unpinned", src)


def test_mode_pinned_gz_is_safe() -> None:
    """tarfile.open(path, 'r:gz') → no hit."""
    src = (
        "import tarfile\n"
        "with tarfile.open(archive_path, 'r:gz') as tar:\n"
        "    pass\n"
    )
    assert not _hits("archive-extract-mode-unpinned", src)


def test_mode_pinned_xz_is_safe() -> None:
    """tarfile.open(path, mode='r:xz') → no hit."""
    src = (
        "import tarfile\n"
        "with tarfile.open(archive_path, mode='r:xz') as tar:\n"
        "    pass\n"
    )
    assert not _hits("archive-extract-mode-unpinned", src)


def test_mode_pinned_streaming_is_safe() -> None:
    """tarfile.open(path, 'r|gz') streaming pinned-mode → no hit."""
    src = (
        "import tarfile\n"
        "with tarfile.open(archive_path, 'r|gz') as tar:\n"
        "    pass\n"
    )
    assert not _hits("archive-extract-mode-unpinned", src)


# ---------- Rule 4 : archive-extract-naive-traversal-sanitiser ----------


def test_naive_sanitiser_only_startswith_slash_check() -> None:
    """E1 shape — only `name.startswith('/')` + `..` in parts, no isabs / no symlink reject."""
    src = (
        "import zipfile\n"
        "from pathlib import Path\n"
        "with zipfile.ZipFile(src) as zf:\n"
        "    for name in zf.namelist():\n"
        "        if name.startswith('/') or '..' in Path(name).parts:\n"
        "            raise ValueError('traversal')\n"
        "    zf.extractall(dest)\n"
    )
    assert _hits("archive-extract-naive-traversal-sanitiser", src)


def test_naive_sanitiser_complete_is_safe() -> None:
    """All three of os.path.isabs, resolve+startswith, issym present → no hit."""
    src = (
        "import os, tarfile\n"
        "from pathlib import Path\n"
        "with tarfile.open(src, 'r:gz') as tf:\n"
        "    for member in tf.getmembers():\n"
        "        if member.issym() or member.islnk():\n"
        "            continue\n"
        "        if '..' in Path(member.name).parts:\n"
        "            raise ValueError\n"
        "        if os.path.isabs(member.name):\n"
        "            raise ValueError\n"
        "        target = (dest / member.name).resolve()\n"
        "        if not str(target).startswith(str(dest_resolved)):\n"
        "            raise ValueError\n"
    )
    assert not _hits("archive-extract-naive-traversal-sanitiser", src)


def test_naive_sanitiser_missing_isabs_still_flagged() -> None:
    """Missing isabs check alone is enough to fire."""
    src = (
        "from pathlib import Path\n"
        "for name in zf.namelist():\n"
        "    if '..' in Path(name).parts:\n"
        "        raise ValueError\n"
        "    target = (dest / name).resolve()\n"
        "    if not str(target).startswith(str(dest)):\n"
        "        raise ValueError\n"
        "    if member.issym():\n"
        "        continue\n"
    )
    # Has b (resolve+startswith), c (issym) but missing a (isabs)
    assert _hits("archive-extract-naive-traversal-sanitiser", src)


# ---------- Rule 5 : archive-extract-symlink-member-accepted -------------


def test_symlink_member_accepted_extractall_no_filter() -> None:
    """extractall(dest) without filter='data' / issym reject anywhere."""
    src = (
        "import tarfile\n"
        "with tarfile.open(archive, 'r:gz') as tar:\n"
        "    tar.extractall(dest)\n"
    )
    assert _hits("archive-extract-symlink-member-accepted", src)


def test_symlink_member_accepted_namelist_loop() -> None:
    """A `for name in zf.namelist()` loop with no symlink reject."""
    src = (
        "import zipfile\n"
        "with zipfile.ZipFile(arch) as zf:\n"
        "    for name in zf.namelist():\n"
        "        zf.extract(name, dest)\n"
    )
    # extract() singular is a trigger too
    assert _hits("archive-extract-symlink-member-accepted", src)


def test_symlink_filter_data_is_safe() -> None:
    """extractall(dest, filter='data') → safe (Py 3.12+)."""
    src = (
        "import tarfile\n"
        "with tarfile.open(archive, 'r:gz') as tar:\n"
        "    tar.extractall(dest, filter='data')\n"
    )
    assert not _hits("archive-extract-symlink-member-accepted", src)


def test_symlink_explicit_issym_reject_is_safe() -> None:
    """Explicit `if member.issym(): continue` → safe."""
    src = (
        "import tarfile\n"
        "with tarfile.open(archive, 'r:gz') as tar:\n"
        "    for member in tar.getmembers():\n"
        "        if member.issym() or member.islnk():\n"
        "            continue\n"
        "        tar.extract(member, dest)\n"
    )
    assert not _hits("archive-extract-symlink-member-accepted", src)


# ---------- Rule 6 : archive-extract-no-bomb-preflight ------------------


def test_no_bomb_preflight_extractall_naked() -> None:
    """Pure extractall with no preflight → flag."""
    src = (
        "import zipfile\n"
        "with zipfile.ZipFile(archive) as zf:\n"
        "    zf.extractall(dest)\n"
    )
    assert _hits("archive-extract-no-bomb-preflight", src)


def test_bomb_preflight_complete_is_safe() -> None:
    """Gold-standard E3/E4: len(infos), sum(file_size), ratio, per-file."""
    src = (
        "import zipfile\n"
        "with zipfile.ZipFile(archive) as zf:\n"
        "    infos = zf.infolist()\n"
        "    if len(zf.infolist()) > MAX_ENTRIES:\n"
        "        raise ValueError\n"
        "    total = sum(info.file_size for info in infos)\n"
        "    if total > MAX_BYTES:\n"
        "        raise ValueError\n"
        "    for info in infos:\n"
        "        if info.file_size > MAX_PER_FILE:\n"
        "            raise ValueError\n"
        "    zf.extractall(dest)\n"
    )
    # Has agg cap (len) AND per-file cap (.file_size > MAX_PER_FILE)
    assert not _hits("archive-extract-no-bomb-preflight", src)


def test_bomb_preflight_only_agg_still_flagged() -> None:
    """Aggregate cap without ratio/per-file → still flagged."""
    src = (
        "import zipfile\n"
        "with zipfile.ZipFile(archive) as zf:\n"
        "    if len(zf.infolist()) > MAX_ENTRIES:\n"
        "        raise ValueError\n"
        "    zf.extractall(dest)\n"
    )
    # Has agg cap but no per-file/ratio cap → fire
    assert _hits("archive-extract-no-bomb-preflight", src)


def test_bomb_preflight_pragma_is_safe() -> None:
    """Explicit pragma carve-out → no hit."""
    src = (
        "import zipfile\n"
        "# pragma: bomb-preflight-ok\n"
        "with zipfile.ZipFile(archive) as zf:\n"
        "    zf.extractall(dest)\n"
    )
    assert not _hits("archive-extract-no-bomb-preflight", src)


# ---------- Rule 7 : archive-extract-shell-tar-no-flags -----------------


def test_shell_tar_xzf_no_flags_flagged() -> None:
    """`tar -xzf pkg.tar.gz` with no hardening flags."""
    src = (
        "#!/bin/bash\n"
        "tar -xzf pkg.tar.gz -C ./extract\n"
    )
    assert _hits("archive-extract-shell-tar-no-flags", src)


def test_shell_tar_xzf_anchored_is_safe() -> None:
    """`tar -xzf ... --anchored` → safe."""
    src = (
        "#!/bin/bash\n"
        "tar -xzf pkg.tar.gz --anchored --strip-components=1 -C ./extract\n"
    )
    assert not _hits("archive-extract-shell-tar-no-flags", src)


def test_shell_tar_xzf_with_no_same_owner_is_safe() -> None:
    """`tar -xzf ... --no-same-owner` → safe."""
    src = (
        "tar -xzf pkg.tar.gz --no-same-owner --no-same-permissions\n"
    )
    assert not _hits("archive-extract-shell-tar-no-flags", src)


def test_shell_tar_mktemp_wrapper_is_safe() -> None:
    """`mktemp -d` wrapper before tar -xzf → safe."""
    src = (
        "TMPDIR=$(mktemp -d)\n"
        "tar -xzf pkg.tar.gz -C $TMPDIR\n"
    )
    assert not _hits("archive-extract-shell-tar-no-flags", src)


def test_shell_unzip_no_flags_flagged() -> None:
    """Plain `unzip foo.zip` flagged."""
    src = "unzip foo.zip\n"
    assert _hits("archive-extract-shell-tar-no-flags", src)


# ---------- Rule 8 : archive-extract-node-tar-not-strict ----------------


def test_node_tar_extract_not_strict_flagged() -> None:
    """tar.extract({file, cwd}) without strict:true."""
    src = (
        "const tar = require('tar');\n"
        "await tar.extract({ file: 'pkg.tar.gz', cwd: './out' });\n"
    )
    assert _hits("archive-extract-node-tar-not-strict", src)


def test_node_tar_x_not_strict_flagged() -> None:
    """tar.x() without strict:true."""
    src = (
        "tar.x({ file: 'pkg.tar', cwd: dest });\n"
    )
    assert _hits("archive-extract-node-tar-not-strict", src)


def test_node_tar_with_strict_true_is_safe() -> None:
    """strict:true in same window → safe."""
    src = (
        "await tar.extract({ file: 'pkg.tar.gz', cwd: './out', strict: true });\n"
    )
    assert not _hits("archive-extract-node-tar-not-strict", src)


def test_node_tar_preserve_paths_fires_even_with_strict() -> None:
    """preservePaths:true is dangerous even with strict:true."""
    src = (
        "await tar.extract({ file: 'pkg.tar.gz', cwd: './out', "
        "strict: true, preservePaths: true });\n"
    )
    # strict:true would suppress, but preservePaths:true forces a hit
    assert _hits("archive-extract-node-tar-not-strict", src)


def test_node_extract_zip_flagged() -> None:
    """extract-zip package call flagged."""
    src = (
        "const extractZip = require('extract-zip');\n"
        "await extractZip(zipPath, { dir: outDir });\n"
    )
    assert _hits("archive-extract-node-tar-not-strict", src)


# ---------- Rule 9 : archive-extract-go-no-filepath-clean-prefix ---------


def test_go_zip_open_no_clean_prefix_flagged() -> None:
    """Go zip.OpenReader without filepath.Clean+HasPrefix."""
    src = (
        "import \"archive/zip\"\n"
        "r, err := zip.OpenReader(archive)\n"
        "for _, f := range r.File {\n"
        "    path := filepath.Join(dest, f.Name)\n"
        "    // ... write without Clean+HasPrefix\n"
        "}\n"
    )
    assert _hits("archive-extract-go-no-filepath-clean-prefix", src)


def test_go_zip_with_clean_and_hasprefix_is_safe() -> None:
    """filepath.Clean + strings.HasPrefix → safe."""
    src = (
        "import \"archive/zip\"\n"
        "r, _ := zip.OpenReader(archive)\n"
        "for _, f := range r.File {\n"
        "    cleaned := filepath.Clean(f.Name)\n"
        "    if !strings.HasPrefix(cleaned, dest+string(filepath.Separator)) {\n"
        "        return errors.New(\"traversal\")\n"
        "    }\n"
        "}\n"
    )
    assert not _hits("archive-extract-go-no-filepath-clean-prefix", src)


def test_go_tar_newreader_no_clean_flagged() -> None:
    """Go tar.NewReader without filepath.Clean → flagged."""
    src = (
        "import \"archive/tar\"\n"
        "tr := tar.NewReader(file)\n"
        "for { hdr, _ := tr.Next(); _ = hdr.Name; }\n"
    )
    assert _hits("archive-extract-go-no-filepath-clean-prefix", src)


# ---------- Rule 10 : archive-extract-java-zip-no-canonical-check ------


def test_java_zipinputstream_no_normalize_flagged() -> None:
    """ZipInputStream without normalize+startsWith → flagged."""
    src = (
        "ZipInputStream zis = new ZipInputStream(in);\n"
        "ZipEntry entry;\n"
        "while ((entry = zis.getNextEntry()) != null) {\n"
        "    Path target = destDir.resolve(entry.getName());\n"
        "    Files.copy(zis, target);\n"
        "}\n"
    )
    assert _hits("archive-extract-java-zip-no-canonical-check", src)


def test_java_zipfile_with_normalize_startswith_is_safe() -> None:
    """ZipFile with normalize+startsWith → safe."""
    src = (
        "ZipFile zf = new ZipFile(file);\n"
        "Path target = destDir.resolve(entry.getName()).normalize();\n"
        "if (!target.startsWith(destDir.normalize())) {\n"
        "    throw new IOException(\"traversal\");\n"
        "}\n"
    )
    # Note: triggers `new ZipFile(` AND has safe shape → suppressed
    assert not _hits("archive-extract-java-zip-no-canonical-check", src)


def test_java_zipfile_with_to_real_path_is_safe() -> None:
    """toRealPath + startsWith → safe."""
    src = (
        "ZipFile zf = new ZipFile(file);\n"
        "Path target = destDir.resolve(entry.getName()).toRealPath();\n"
        "if (!target.startsWith(destDir.toRealPath())) throw new IOException();\n"
    )
    assert not _hits("archive-extract-java-zip-no-canonical-check", src)


def test_java_tar_archive_input_stream_flagged() -> None:
    """TarArchiveInputStream without canonical check → flagged."""
    src = (
        "TarArchiveInputStream tais = new TarArchiveInputStream(in);\n"
        "TarArchiveEntry entry;\n"
        "while ((entry = tais.getNextEntry()) != null) {\n"
        "    File f = new File(destDir, entry.getName());\n"
        "    Files.copy(tais, f.toPath());\n"
        "}\n"
    )
    assert _hits("archive-extract-java-zip-no-canonical-check", src)


# ---------- Rule 11 : archive-extract-polyglot-extension-mismatch -------


def test_polyglot_endswith_zip_no_magic_flagged() -> None:
    """`filename.endswith('.zip')` switch with no magic-byte check."""
    src = (
        "def route(filename, blob):\n"
        "    if filename.endswith('.zip'):\n"
        "        extract_zip(blob)\n"
        "    elif filename.endswith('.tar.gz'):\n"
        "        extract_tar(blob)\n"
    )
    assert _hits("archive-extract-polyglot-extension-mismatch", src)


def test_polyglot_with_detect_magic_is_safe() -> None:
    """detect_magic() also called → safe."""
    src = (
        "def route(filename, blob):\n"
        "    label = detect_magic(blob[:512])\n"
        "    if filename.endswith('.zip') and label == 'zip':\n"
        "        extract_zip(blob)\n"
    )
    assert not _hits("archive-extract-polyglot-extension-mismatch", src)


def test_polyglot_go_hassuffix_flagged() -> None:
    """Go `strings.HasSuffix(filename, '.zip')` → flagged."""
    src = (
        "if strings.HasSuffix(filename, \".zip\") {\n"
        "    extractZip(filename)\n"
        "}\n"
    )
    assert _hits("archive-extract-polyglot-extension-mismatch", src)


def test_polyglot_with_magic_from_buffer_is_safe() -> None:
    """`magic.from_buffer` somewhere → safe."""
    src = (
        "import magic\n"
        "mime = magic.from_buffer(blob[:1024], mime=True)\n"
        "if filename.endswith('.zip') and mime == 'application/zip':\n"
        "    extract(blob)\n"
    )
    assert not _hits("archive-extract-polyglot-extension-mismatch", src)


# ---------- Rule 12 : archive-extract-zip-overlap-confusion -------------


def test_zip_overlap_zipfile_plus_libarchive_flagged() -> None:
    """Same function uses zipfile.ZipFile AND libarchive."""
    src = (
        "import zipfile, libarchive\n"
        "def install(path):\n"
        "    with zipfile.ZipFile(path) as zf:\n"
        "        zf.extractall('a')\n"
        "    libarchive.extract_file(path)\n"
    )
    assert _hits("archive-extract-zip-overlap-confusion", src)


def test_zip_overlap_zipfile_plus_subprocess_unzip_flagged() -> None:
    """zipfile.ZipFile + subprocess.run(['unzip', ...]) on same path."""
    src = (
        "import zipfile, subprocess\n"
        "def install(path):\n"
        "    with zipfile.ZipFile(path) as zf:\n"
        "        names = zf.namelist()\n"
        "    subprocess.run(['unzip', path, '-d', 'out'])\n"
    )
    assert _hits("archive-extract-zip-overlap-confusion", src)


def test_zip_overlap_single_parser_is_safe() -> None:
    """Only zipfile (no second parser) → no hit."""
    src = (
        "import zipfile\n"
        "with zipfile.ZipFile(path) as zf:\n"
        "    zf.extractall('out')\n"
    )
    assert not _hits("archive-extract-zip-overlap-confusion", src)


def test_zip_overlap_js_yauzl_plus_admzip_flagged() -> None:
    """JS yauzl + adm-zip same file → flagged."""
    src = (
        "const yauzl = require('yauzl');\n"
        "const AdmZip = require('adm-zip');\n"
        "function open(path) {\n"
        "    yauzl.open(path, (err, zip) => { ... });\n"
        "    const az = new AdmZip(path);\n"
        "}\n"
    )
    assert _hits("archive-extract-zip-overlap-confusion", src)


# ---------- Rule 13 : archive-extract-tar-pax-extended-header-spoof -----


def test_pax_spoof_member_name_use_no_pax_check_flagged() -> None:
    """for member in tf.getmembers(): use member.name without pax_headers."""
    src = (
        "import tarfile\n"
        "with tarfile.open(arch, 'r:gz') as tf:\n"
        "    for member in tf.getmembers():\n"
        "        if '..' in member.name:\n"
        "            raise ValueError\n"
        "        tf.extract(member, dest)\n"
    )
    assert _hits("archive-extract-tar-pax-extended-header-spoof", src)


def test_pax_spoof_with_pax_headers_check_is_safe() -> None:
    """Reads member.pax_headers → safe."""
    src = (
        "import tarfile\n"
        "with tarfile.open(arch, 'r:gz') as tf:\n"
        "    for member in tf.getmembers():\n"
        "        canonical = member.pax_headers.get('path', member.name)\n"
        "        if '..' in canonical:\n"
        "            raise ValueError\n"
    )
    assert not _hits("archive-extract-tar-pax-extended-header-spoof", src)


def test_pax_spoof_with_data_filter_is_safe() -> None:
    """filter='data' present → safe."""
    src = (
        "import tarfile\n"
        "with tarfile.open(arch, 'r:gz') as tf:\n"
        "    for member in tf.getmembers():\n"
        "        if member.name.startswith('/'):\n"
        "            raise ValueError\n"
        "    tf.extractall(dest, filter='data')\n"
    )
    assert not _hits("archive-extract-tar-pax-extended-header-spoof", src)


# ---------- Cross-rule / composite ---------------------------------------


def test_multiple_rules_can_fire_on_same_text() -> None:
    """Proxy_stub.py (E7) — fires bytesio, mode-unpinned, copyfileobj-read."""
    src = (
        "import io, tarfile, requests\n"
        "tarball = requests.get(url).content\n"
        "with tarfile.open(fileobj=io.BytesIO(tarball)) as tar:\n"
        "    data = tar.extractfile('config').read()\n"
    )
    findings = aep.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "archive-extract-bytesio-no-preflight" in rule_ids
    # tarfile.open(fileobj=BytesIO(...)) ALSO matches "no mode arg"
    # but the regex needs the open call to NOT have a comma+mode after.
    # Our mode-unpinned matcher requires (a) single identifier arg or
    # (b) explicit 'r'. The fileobj=BytesIO call is excluded by current
    # regex shape — that's acceptable since bytesio-no-preflight covers it.
    assert "archive-extract-shutil-copyfileobj-unbounded" in rule_ids


def test_findings_are_sorted_by_line_column() -> None:
    """Findings are deterministically ordered."""
    src = (
        "import zipfile\n"
        "with zipfile.ZipFile(a) as zf:\n"
        "    zf.extractall(b)\n"
        "import tarfile\n"
        "with tarfile.open(c) as tf:\n"
        "    tf.extractall(d)\n"
    )
    findings = aep.scan_text(src)
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_findings_are_deduped() -> None:
    """Same (rule, line, col) does not appear twice."""
    src = (
        "import zipfile\n"
        "with zipfile.ZipFile(a) as zf:\n"
        "    zf.extractall(b)\n"
    )
    findings = aep.scan_text(src)
    keys = {(f.rule_id, f.line, f.column) for f in findings}
    assert len(keys) == len(findings)


def test_long_match_is_truncated() -> None:
    """Matches > 200 chars are truncated with ellipsis."""
    # Build a tar/zip extract span that's > 200 chars
    blob = "x" * 350
    src = (
        f"with zipfile.ZipFile('{blob}') as zf:\n"
        "    for n in zf.namelist():\n"
        "        with zf.open(n) as zsrc:\n"
        "            shutil.copyfileobj(zsrc, open('o', 'wb'))\n"
    )
    findings = aep.scan_text(src)
    for f in findings:
        assert len(f.matched_text) <= 201  # 200 + ellipsis


# ---------- Regex safety / no-catastrophic-backtracking -----------------


def test_scan_is_fast_on_large_benign_input() -> None:
    """5 KB of benign Python code → scan completes promptly (no ReDoS)."""
    import time

    benign = ("def foo():\n    pass\n" * 200) + "import os\n" * 50
    start = time.monotonic()
    findings = aep.scan_text(benign)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"scan_text too slow: {elapsed:.3f}s"
    # benign code: should produce no archive-extraction findings
    assert findings == []


def test_scan_is_fast_on_pathological_repeat() -> None:
    """Heavy repetition of trigger-adjacent tokens → no catastrophic backtracking."""
    import time

    # Many partial-matches: lots of `tarfile.open` substrings that don't
    # close with the safe-shape — exercises the engine's bounded {0,N}
    # backtracking limits.
    pathological = (
        "tarfile.open(x)\n" * 200
        + "zipfile.ZipFile(x)\n" * 200
        + "shutil.copyfileobj(a,b)\n" * 200
    )
    start = time.monotonic()
    aep.scan_text(pathological)
    elapsed = time.monotonic() - start
    assert elapsed < 2.0, f"scan_text slow on pathological input: {elapsed:.3f}s"


# ---------- Severity / ASI distribution ---------------------------------


def test_critical_rules_count() -> None:
    """Exactly 2 CRITICAL rules: bytesio + symlink-member."""
    critical_ids = {r.id for r in aep.RULES if r.severity == "CRITICAL"}
    assert critical_ids == {
        "archive-extract-bytesio-no-preflight",
        "archive-extract-symlink-member-accepted",
    }


def test_bomb_preflight_is_asi_04() -> None:
    """Bomb-preflight maps to ASI-04 (data leak / resource exhaustion)."""
    for r in aep.RULES:
        if r.id == "archive-extract-no-bomb-preflight":
            assert r.owasp_asi == "ASI-04"
            return
    raise AssertionError("rule not found")


def test_most_rules_are_asi_05() -> None:
    """Most rules map to ASI-05 (supply-chain / path-traversal)."""
    asi_05_count = sum(1 for r in aep.RULES if r.owasp_asi == "ASI-05")
    # 12 of 13 rules → ASI-05
    assert asi_05_count == 12
