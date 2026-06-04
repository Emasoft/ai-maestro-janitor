"""Tests for scripts/lib/race_patterns.py.

Pattern-coverage tests for the Wave-18 distillation round 4 batch B
catalogue (TOCTOU + lockfile + symlink + atomic-write + archive-extract
race conditions). Each rule gets 3-5 positive/negative tests exercising
the primary trigger plus its FP carve-outs (file-level guards, window
probes, same-line documentation markers, atomic-create patterns).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import race_patterns as rp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(rp.RULES, tuple)
    rule_ids = {r.id for r in rp.RULES}
    expected = {
        "race-py-mktemp-banned",
        "race-py-namedtemp-delete-false-leak",
        "race-tmp-hardcoded-write-path",
        "race-symlink-append-without-nofollow",
        "race-chmod-after-write",
        "race-temp-pid-suffix-predictable",
        "race-archive-unsanitized-extract",
        "race-copytree-symlinks-follow",
        "race-rename-cross-fs",
        "race-bash-rmrf-unset-var",
        "race-lockfile-touch-not-exclusive",
        "race-docker-bindmount-tmp-shared",
        "race-setuid-chmod-after-write",
        "race-exists-then-rm",
        "race-parent-dir-attacker-controlled",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_owasp_mapping() -> None:
    """Every rule maps to a non-empty ASI- prefix + valid severity."""
    for rule in rp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns.Finding shape."""
    f = rp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-07",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-07"


def _hits(rule_id: str, text: str) -> list[rp.Finding]:
    return [f for f in rp.scan_text(text) if f.rule_id == rule_id]


# ---------- Rule 1 : race-py-mktemp-banned -------------------------------


def test_mktemp_bare_call_flags() -> None:
    """`tempfile.mktemp()` as a bare call is the textbook deprecation."""
    src = "path = tempfile.mktemp()\n"
    assert _hits("race-py-mktemp-banned", src)


def test_mktemp_with_prefix_flags() -> None:
    """`tempfile.mktemp(prefix='foo')` is still the deprecated primitive."""
    src = "path = tempfile.mktemp(prefix='foo', suffix='.tmp')\n"
    assert _hits("race-py-mktemp-banned", src)


def test_mktemp_qualified_via_module_alias_no_hit() -> None:
    """A custom function `my.mktemp(` is not the stdlib's banned name."""
    src = "path = mymodule.mktemp()\n"
    assert not _hits("race-py-mktemp-banned", src)


def test_mkstemp_correct_primitive_no_hit() -> None:
    """`tempfile.mkstemp()` (note the 's') is the CORRECT primitive."""
    src = "fd, path = tempfile.mkstemp()\n"
    assert not _hits("race-py-mktemp-banned", src)


# ---------- Rule 2 : race-py-namedtemp-delete-false-leak -----------------


def test_namedtemp_delete_false_no_cleanup_flags() -> None:
    """NamedTemporaryFile(delete=False) with no unlink anywhere fires."""
    src = (
        "import tempfile\n"
        "def run_in_sandbox():\n"
        "    f = tempfile.NamedTemporaryFile(delete=False)\n"
        "    f.write(b'data')\n"
        "    return f.name\n"
    )
    assert _hits("race-py-namedtemp-delete-false-leak", src)


def test_namedtemp_delete_false_with_unlink_safe() -> None:
    """`os.unlink` somewhere in the file suppresses the leak hit."""
    src = (
        "import os, tempfile\n"
        "def run():\n"
        "    f = tempfile.NamedTemporaryFile(delete=False)\n"
        "    try:\n"
        "        f.write(b'data')\n"
        "    finally:\n"
        "        os.unlink(f.name)\n"
    )
    assert not _hits("race-py-namedtemp-delete-false-leak", src)


def test_namedtemp_delete_false_with_path_unlink_safe() -> None:
    """`Path(...).unlink()` counts as a cleanup guard."""
    src = (
        "from pathlib import Path\n"
        "import tempfile\n"
        "f = tempfile.NamedTemporaryFile(delete=False)\n"
        "Path(f.name).unlink()\n"
    )
    assert not _hits("race-py-namedtemp-delete-false-leak", src)


def test_namedtemp_delete_true_no_hit() -> None:
    """Default delete=True does not fire the rule at all."""
    src = "f = tempfile.NamedTemporaryFile(delete=True)\n"
    assert not _hits("race-py-namedtemp-delete-false-leak", src)


# ---------- Rule 3 : race-tmp-hardcoded-write-path -----------------------


def test_tmp_hardcoded_python_open() -> None:
    """`open('/tmp/foo', 'w')` is the textbook predictable-path write."""
    src = "with open('/tmp/script.py', 'w') as f:\n    f.write('x')\n"
    assert _hits("race-tmp-hardcoded-write-path", src)


def test_tmp_hardcoded_python_write_text() -> None:
    """`Path('/tmp/foo').write_text(...)` fires."""
    src = "Path('/tmp/audit.log').write_text(data)\n"
    assert _hits("race-tmp-hardcoded-write-path", src)


def test_tmp_hardcoded_node_writefile() -> None:
    """`fs.writeFile('/tmp/foo', ...)` fires."""
    src = "fs.writeFileSync('/tmp/cache.json', payload);\n"
    assert _hits("race-tmp-hardcoded-write-path", src)


def test_tmp_hardcoded_documentation_carveout() -> None:
    """A same-line `# EXAMPLE` marker suppresses the hit."""
    src = "open('/tmp/example.txt', 'w')  # EXAMPLE: documentation only\n"
    assert not _hits("race-tmp-hardcoded-write-path", src)


def test_tmp_safe_non_tmp_path_no_hit() -> None:
    """A normal path outside /tmp/ does not fire."""
    src = "with open('/var/log/myapp.log', 'a') as f: pass\n"
    assert not _hits("race-tmp-hardcoded-write-path", src)


# ---------- Rule 4 : race-symlink-append-without-nofollow ----------------


def test_append_without_nofollow_flags() -> None:
    """`open(LOG_PATH, 'a')` with no O_NOFOLLOW anywhere → hit."""
    src = (
        "def audit(line):\n"
        "    with open(LOG_PATH, 'a') as f:\n"
        "        f.write(line)\n"
    )
    assert _hits("race-symlink-append-without-nofollow", src)


def test_append_with_nofollow_nearby_safe() -> None:
    """`O_NOFOLLOW` mentioned within the window suppresses."""
    src = (
        "import os\n"
        "fd = os.open(LOG_PATH, os.O_APPEND | os.O_NOFOLLOW)\n"
        "with open(LOG_PATH, 'a') as f:\n"
        "    pass\n"
    )
    assert not _hits("race-symlink-append-without-nofollow", src)


def test_append_with_is_symlink_check_safe() -> None:
    """`is_symlink()` probe within window suppresses."""
    src = (
        "if not Path(LOG_PATH).is_symlink():\n"
        "    with open(LOG_PATH, 'a') as f:\n"
        "        f.write(x)\n"
    )
    assert not _hits("race-symlink-append-without-nofollow", src)


def test_append_with_trusted_path_pragma_safe() -> None:
    """`# audit-log: trusted-path` comment in window suppresses."""
    src = (
        "# audit-log: trusted-path — log directory is mode 0o700\n"
        "with open(LOG_PATH, 'a') as f:\n"
        "    f.write(x)\n"
    )
    assert not _hits("race-symlink-append-without-nofollow", src)


def test_open_write_mode_no_hit() -> None:
    """`open(path, 'w')` (not append) is a different rule's territory."""
    src = "with open(LOG_PATH, 'w') as f: pass\n"
    assert not _hits("race-symlink-append-without-nofollow", src)


# ---------- Rule 5 : race-chmod-after-write ------------------------------


def test_chmod_after_write_text_python() -> None:
    """`p.write_text(x); p.chmod(0o755)` is the canonical race."""
    src = (
        "target = Path('hook.sh')\n"
        "target.write_text(SCRIPT)\n"
        "target.chmod(0o755)\n"
    )
    assert _hits("race-chmod-after-write", src)


def test_chmod_after_open_write_python() -> None:
    """`open(p, 'w'); os.chmod(p, ...)` fires the low-level variant."""
    src = (
        "with open(target, 'w') as f:\n"
        "    f.write(data)\n"
        "os.chmod(target, 0o755)\n"
    )
    assert _hits("race-chmod-after-write", src)


def test_chmod_after_cp_bash() -> None:
    """Shell `cp src dst; chmod +x dst` fires."""
    src = (
        "cp \"$src/hook.sh\" \"$dst/hook.sh\"\n"
        "chmod +x \"$dst/hook.sh\"\n"
    )
    assert _hits("race-chmod-after-write", src)


def test_chmod_after_file_write_ruby() -> None:
    """Ruby `File.write(...); File.chmod(...)` fires."""
    src = (
        "File.write(hook_path, HOOK_SCRIPT)\n"
        "File.chmod(0o755, hook_path)\n"
    )
    assert _hits("race-chmod-after-write", src)


def test_chmod_before_write_no_hit() -> None:
    """Reverse order (chmod before any write) is not the race."""
    src = (
        "target.chmod(0o600)\n"
        "target.write_text(data)\n"
    )
    assert not _hits("race-chmod-after-write", src)


# ---------- Rule 6 : race-temp-pid-suffix-predictable --------------------


def test_pid_suffix_node_process_pid() -> None:
    """`${path}.tmp-${process.pid}` is the sealed-env shape."""
    src = "const tmp = `${path}.tmp-${process.pid}`;\n"
    assert _hits("race-temp-pid-suffix-predictable", src)


def test_pid_suffix_python_getpid() -> None:
    """`f'{path}.tmp-{os.getpid()}'` fires too."""
    src = "tmp = f'{path}.tmp-{os.getpid()}'\n"
    assert _hits("race-temp-pid-suffix-predictable", src)


def test_pid_suffix_bash_dollar_dollar() -> None:
    """Bash `${path}.tmp-$$` is the shell-script equivalent."""
    src = 'tmp="${path}.tmp-$$"\n'
    assert _hits("race-temp-pid-suffix-predictable", src)


def test_pid_suffix_lock_extension() -> None:
    """`.lock-${PID}` also fires (lock-file race)."""
    src = "const lock = `${target}.lock-${PID}`;\n"
    assert _hits("race-temp-pid-suffix-predictable", src)


def test_pid_suffix_secrets_token_hex_no_hit() -> None:
    """`secrets.token_hex(8)` suffix is the random-suffix safe shape."""
    src = "tmp = f'{path}.tmp-{secrets.token_hex(8)}'\n"
    assert not _hits("race-temp-pid-suffix-predictable", src)


# ---------- Rule 7 : race-archive-unsanitized-extract --------------------


def test_tarfile_extractall_no_filter_flags() -> None:
    """`tarfile.open(...).extractall(dst)` without filter fires."""
    src = (
        "import tarfile\n"
        "with tarfile.open('pkg.tar.gz', 'r:gz') as tar:\n"
        "    tar.extractall('/tmp/extracted')\n"
    )
    assert _hits("race-archive-unsanitized-extract", src)


def test_tarfile_extractall_with_filter_data_safe() -> None:
    """`filter='data'` (Python 3.12+) suppresses the hit."""
    src = (
        "import tarfile\n"
        "with tarfile.open('pkg.tar.gz', 'r:gz') as tar:\n"
        "    tar.extractall('/tmp/extracted', filter='data')\n"
    )
    assert not _hits("race-archive-unsanitized-extract", src)


def test_zipfile_extractall_no_filter_flags() -> None:
    """`ZipFile(...).extractall(...)` is also unsanitized by default."""
    src = (
        "import zipfile\n"
        "with zipfile.ZipFile('pkg.zip') as z:\n"
        "    z.extractall('/tmp/extracted')\n"
    )
    assert _hits("race-archive-unsanitized-extract", src)


def test_tar_xzf_bash_no_flags() -> None:
    """`tar -xzf` without `--no-same-owner` fires."""
    src = 'tar -xzf "$tmp/$archive" -C "$tmp"\n'
    assert _hits("race-archive-unsanitized-extract", src)


def test_tar_xzf_bash_with_safe_flags() -> None:
    """`tar -xzf ... --no-same-owner --no-same-permissions` is safe."""
    src = (
        'tar -xzf "$tmp/$archive" -C "$tmp" '
        '--no-same-owner --no-same-permissions\n'
    )
    assert not _hits("race-archive-unsanitized-extract", src)


# ---------- Rule 8 : race-copytree-symlinks-follow -----------------------


def test_copytree_default_symlinks_false_flags() -> None:
    """`shutil.copytree(src, dst)` with default kwargs fires."""
    src = (
        "import shutil\n"
        "shutil.copytree(pkg_dir, target_dir)\n"
    )
    assert _hits("race-copytree-symlinks-follow", src)


def test_copytree_symlinks_true_safe() -> None:
    """`shutil.copytree(src, dst, symlinks=True)` is the safe shape."""
    src = (
        "import shutil\n"
        "shutil.copytree(pkg_dir, target_dir, symlinks=True)\n"
    )
    assert not _hits("race-copytree-symlinks-follow", src)


def test_copytree_in_multiline_call_safe() -> None:
    """`symlinks=True` in a multi-line call still suppresses."""
    src = (
        "shutil.copytree(\n"
        "    src,\n"
        "    dst,\n"
        "    symlinks=True,\n"
        "    dirs_exist_ok=True,\n"
        ")\n"
    )
    assert not _hits("race-copytree-symlinks-follow", src)


def test_copy_not_copytree_no_hit() -> None:
    """`shutil.copy2` is single-file — does not trigger copytree rule."""
    src = "shutil.copy2(src, dst)\n"
    assert not _hits("race-copytree-symlinks-follow", src)


# ---------- Rule 9 : race-rename-cross-fs --------------------------------


def test_rename_from_tmp_literal_flags() -> None:
    """`os.rename('/tmp/foo', dst)` is the cross-fs race shape."""
    src = "os.rename('/tmp/staged.txt', user_dest)\n"
    assert _hits("race-rename-cross-fs", src)


def test_renamesync_from_tmpdir_flags() -> None:
    """`fs.renameSync(os.tmpdir() + '/x', dst)` fires."""
    src = "fs.renameSync(`${os.tmpdir()}/staged.txt`, finalPath);\n"
    assert _hits("race-rename-cross-fs", src)


def test_shutil_move_from_tmp_flags() -> None:
    """`shutil.move('/tmp/x', ...)` fires."""
    src = "shutil.move('/tmp/audit.log', '/home/user/audit.log')\n"
    assert _hits("race-rename-cross-fs", src)


def test_rename_same_dir_no_hit() -> None:
    """Same-directory rename is the safe atomic pattern."""
    src = (
        "tmp = os.path.join(os.path.dirname(dest), '.tmp-' + suffix)\n"
        "os.rename(tmp, dest)\n"
    )
    assert not _hits("race-rename-cross-fs", src)


# ---------- Rule 10 : race-bash-rmrf-unset-var ---------------------------


def test_rmrf_var_no_set_u_flags() -> None:
    """`rm -rf "$TMPDIR"/` with no set -u is catastrophic."""
    src = (
        "#!/usr/bin/env bash\n"
        'rm -rf "$TMPDIR"/\n'
    )
    assert _hits("race-bash-rmrf-unset-var", src)


def test_rmrf_var_with_set_u_safe() -> None:
    """`set -u` somewhere in the file suppresses."""
    src = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'rm -rf "$TMPDIR"/\n'
    )
    assert not _hits("race-bash-rmrf-unset-var", src)


def test_rmrf_var_with_set_o_nounset_safe() -> None:
    """`set -o nounset` is the long-form equivalent."""
    src = (
        "set -o nounset\n"
        'rm -rf "$WORK"/\n'
    )
    assert not _hits("race-bash-rmrf-unset-var", src)


def test_rmrf_var_with_default_guard_same_line_safe() -> None:
    """`${VAR:?error}` built-in unset guard suppresses same-line."""
    src = 'rm -rf "${TMPDIR:?TMPDIR is unset}"/\n'
    assert not _hits("race-bash-rmrf-unset-var", src)


def test_rmrf_lowercase_var_no_hit() -> None:
    """Lowercase variables are not in the conventional shell-VAR shape."""
    src = 'rm -rf "$tmpdir"/\n'
    assert not _hits("race-bash-rmrf-unset-var", src)


# ---------- Rule 11 : race-lockfile-touch-not-exclusive ------------------


def test_lockfile_exists_then_touch_flags() -> None:
    """`if not lock.exists(): lock.touch()` is the broken-lock shape."""
    src = (
        "lock = Path('/var/lib/myapp/lock')\n"
        "if not lock.exists():\n"
        "    lock.touch()\n"
    )
    assert _hits("race-lockfile-touch-not-exclusive", src)


def test_lockfile_exists_then_open_w_flags() -> None:
    """`os.path.exists(lock); open(lock, 'w')` fires the variant."""
    src = (
        "if os.path.exists(LOCK):\n"
        "    raise SystemExit(1)\n"
        "open(LOCK, 'w')\n"
    )
    assert _hits("race-lockfile-touch-not-exclusive", src)


def test_lockfile_with_o_excl_safe() -> None:
    """O_EXCL within window suppresses the hit."""
    src = (
        "import os\n"
        "if not Path(lock).exists():\n"
        "    fd = os.open(lock, os.O_CREAT | os.O_EXCL)\n"
        "    Path(lock).touch()\n"
    )
    assert not _hits("race-lockfile-touch-not-exclusive", src)


def test_lockfile_with_fcntl_flock_safe() -> None:
    """`fcntl.flock` within window suppresses."""
    src = (
        "if not Path(lock).exists():\n"
        "    Path(lock).touch()\n"
        "    fcntl.flock(fd, fcntl.LOCK_EX)\n"
    )
    assert not _hits("race-lockfile-touch-not-exclusive", src)


# ---------- Rule 12 : race-docker-bindmount-tmp-shared -------------------


def test_docker_bindmount_tmp_volumes_flags() -> None:
    """`volumes={'/tmp/script.py': {...}}` fires."""
    src = (
        "client.containers.run(\n"
        "    image='python:3.12',\n"
        '    volumes={"/tmp/script.py": {"bind": "/tmp/script.py", "mode": "ro"}},\n'
        ")\n"
    )
    assert _hits("race-docker-bindmount-tmp-shared", src)


def test_docker_command_references_tmp_path() -> None:
    """`command='python /tmp/script.py'` references the bound path."""
    src = 'container.run(command=f"python /tmp/script.py")\n'
    assert _hits("race-docker-bindmount-tmp-shared", src)


def test_docker_bindmount_with_mkstemp_no_hit() -> None:
    """A bindmount of a non-/tmp path does not fire."""
    src = (
        "with tempfile.NamedTemporaryFile() as f:\n"
        '    client.containers.run(volumes={f.name: {"bind": "/script.py"}})\n'
    )
    assert not _hits("race-docker-bindmount-tmp-shared", src)


# ---------- Rule 13 : race-setuid-chmod-after-write ----------------------


def test_setuid_chmod_after_open_w_flags() -> None:
    """`open(p, 'w') ... chmod(p, 0o4755)` is the setuid TOCTOU."""
    src = (
        "with open(target, 'w') as f:\n"
        "    f.write(payload)\n"
        "os.chmod(target, 0o4755)\n"
    )
    assert _hits("race-setuid-chmod-after-write", src)


def test_setuid_chmod_after_write_text_flags() -> None:
    """`Path.write_text(...); chmod(..., 0o6755)` is the setgid+setuid variant."""
    src = (
        "Path(p).write_text(data)\n"
        "os.chmod(p, 0o6755)\n"
    )
    assert _hits("race-setuid-chmod-after-write", src)


def test_setuid_chmod_with_atomic_open_safe() -> None:
    """`os.open(..., O_CREAT, 0o4755)` atomically sets mode — safe."""
    src = (
        "fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o4755)\n"
        "os.write(fd, payload)\n"
        "os.chmod(target, 0o4755)\n"  # redundant but harmless
    )
    assert not _hits("race-setuid-chmod-after-write", src)


def test_chmod_non_setuid_mode_no_hit() -> None:
    """`chmod(p, 0o755)` (no setuid bit) is normal executable mode."""
    src = (
        "with open(target, 'w') as f:\n"
        "    f.write(payload)\n"
        "os.chmod(target, 0o755)\n"
    )
    assert not _hits("race-setuid-chmod-after-write", src)


def test_setuid_chmod_no_write_context_no_hit() -> None:
    """Standalone chmod with no preceding write context is fine."""
    src = "os.chmod('/usr/bin/sudo', 0o4755)\n"
    assert not _hits("race-setuid-chmod-after-write", src)


# ---------- Rule 14 : race-exists-then-rm --------------------------------


def test_exists_then_unlink_flags() -> None:
    """`if os.path.exists(p): os.unlink(p)` is the textbook TOCTOU."""
    src = (
        "if os.path.exists(p):\n"
        "    os.unlink(p)\n"
    )
    assert _hits("race-exists-then-rm", src)


def test_exists_then_rmtree_flags() -> None:
    """`if Path(p).exists(): shutil.rmtree(p)` is the directory variant."""
    src = (
        "if Path(p).exists():\n"
        "    shutil.rmtree(p)\n"
    )
    assert _hits("race-exists-then-rm", src)


def test_exists_then_path_unlink_flags() -> None:
    """`if p.exists(): Path(p).unlink()` fires."""
    src = (
        "if Path(p).exists():\n"
        "    Path(p).unlink()\n"
    )
    assert _hits("race-exists-then-rm", src)


def test_race_tolerated_annotation_safe() -> None:
    """`# race-tolerated` annotation suppresses."""
    src = (
        "if os.path.exists(p):  # race-tolerated — cleanup best-effort\n"
        "    os.unlink(p)\n"
    )
    assert not _hits("race-exists-then-rm", src)


def test_unlink_alone_no_hit() -> None:
    """A bare `os.unlink(p)` with no exists check is the correct shape."""
    src = (
        "try:\n"
        "    os.unlink(p)\n"
        "except FileNotFoundError:\n"
        "    pass\n"
    )
    assert not _hits("race-exists-then-rm", src)


# ---------- Rule 15 : race-parent-dir-attacker-controlled ----------------


def test_home_dotdir_python_open_flags() -> None:
    """`open(os.path.join(os.environ.get('HOME'), ...))` fires."""
    src = (
        "with open(os.path.join(os.environ.get('HOME'), '.claude', 'secrets.json'), 'w') as f:\n"
        "    f.write(secret)\n"
    )
    assert _hits("race-parent-dir-attacker-controlled", src)


def test_path_home_dotfile_flags() -> None:
    """`Path.home() / '.config' / 'app.toml'` write fires."""
    src = (
        "p = Path.home() / '.ssh' / 'authorized_keys'\n"
        "with open(p, 'w') as f:\n"
        "    f.write(key)\n"
    )
    assert _hits("race-parent-dir-attacker-controlled", src)


def test_home_dotfile_with_nofollow_safe() -> None:
    """`O_NOFOLLOW` in the surrounding window suppresses."""
    src = (
        "import os\n"
        "p = Path.home() / '.claude' / 'creds.json'\n"
        "fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)\n"
    )
    assert not _hits("race-parent-dir-attacker-controlled", src)


def test_home_dotfile_with_lstat_safe() -> None:
    """`lstat` in window indicates symlink-aware probe."""
    src = (
        "p = Path.home() / '.config' / 'app.toml'\n"
        "if os.lstat(p).st_mode & 0o170000 == 0o100000:\n"
        "    open(p, 'w')\n"
    )
    assert not _hits("race-parent-dir-attacker-controlled", src)


# ---------- Scanner-level invariants -------------------------------------


def test_scan_text_empty_returns_empty() -> None:
    assert rp.scan_text("") == []


def test_scan_text_dedupes_same_rule_same_line() -> None:
    """Same rule firing twice at the same (rule, line, col) emits once."""
    src = "path = tempfile.mktemp()\n"
    hits = _hits("race-py-mktemp-banned", src)
    keys = {(h.line, h.column) for h in hits}
    assert len(hits) == len(keys)


def test_scan_text_sorted_by_line_then_column() -> None:
    """Findings come out sorted by (line, column, rule_id)."""
    src = (
        "open('/tmp/foo.txt', 'w')\n"
        'rm -rf "$TMP"/\n'
    )
    findings = rp.scan_text(src)
    assert findings == sorted(findings, key=lambda f: (f.line, f.column, f.rule_id))


def test_finding_truncates_long_match() -> None:
    """Matched text longer than 200 chars truncates with an ellipsis."""
    # Construct an archive-extract trigger with a body of >200 chars
    # between open() and extractall() to ensure the truncation path runs.
    middle = "    # padding " + "x" * 220 + "\n"
    src = (
        "import tarfile\n"
        "with tarfile.open('p.tar.gz') as t:\n"
        f"{middle}"
        "    t.extractall('/tmp/x')\n"
    )
    findings = _hits("race-archive-unsanitized-extract", src)
    assert findings
    if len(findings[0].matched_text) > 0:
        # Either the match is short, or it's been truncated with the
        # ellipsis marker. Both are correct outcomes.
        assert "…" in findings[0].matched_text or len(findings[0].matched_text) <= 200
