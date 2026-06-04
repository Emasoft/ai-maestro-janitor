"""Tests for the binary-magic-scanner detector.

The detector at scripts/detectors/binary-magic-scanner.py reads the
first 8 bytes of every file in well-known "unexpected binary"
directories (`.github/`, `scripts/`, `docs/`, `tests/`, `examples/`,
`samples/`, `image*/`, `download*/`, `release*/`) and matches against a
short magic-byte table — closing the gap that lets attackers ship a
renamed Lua interpreter as `dir.cc` or an obfuscated Lua-source payload
as `bytecode.txt` (the extension-only `repo-trust-score` misses both).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "binary-magic-scanner.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"


def _run(
    project_dir: Path,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env.pop("CLAUDE_PLUGIN_OPTION_BINARY_MAGIC_SCANNER_ENABLED", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60,
    )


# Magic-byte fixtures — each is "<magic> + padding" so the file is
# unambiguously identified by its prefix.
_PE_TIGHT = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 56          # snakebite renamed lua.exe shape
_PE_LOOSE = b"MZ" + b"\xab" * 62                                  # generic MZ — no \x90\x00
_ELF = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 56
_MACHO_64LE = b"\xcf\xfa\xed\xfe" + b"\x07\x00\x00\x01" + b"\x00" * 56
_MACHO_FAT = b"\xca\xfe\xba\xbe" + b"\x00\x00\x00\x03" + b"\x00" * 56
_JAVA_CLASS = b"\xca\xfe\xba\xbe\x00\x00\x00\x02" + b"\x00" * 56  # tight Java prefix
_WASM = b"\x00asm\x01\x00\x00\x00" + b"\x00" * 56
_ZIP = b"PK\x03\x04\x14\x00\x00\x00" + b"\x00" * 56
_LUA_BYTECODE = b"\x1bLua\x51\x00\x01\x04" + b"\x00" * 56
_LUA_SOURCE_TROJAN = b"return(function(...)local J=function(...)" + b" " * 32
_GZIP = b"\x1f\x8b\x08\x00\x00\x00\x00\x00" + b"\x00" * 56


def _seed_minimal_project(project_dir: Path) -> None:
    """A baseline project with no binaries — used for silent runs."""
    (project_dir / "README.md").write_text("# x\n", encoding="utf-8")
    (project_dir / "src").mkdir(exist_ok=True)
    (project_dir / "src" / "main.py").write_text("def m(): pass\n", encoding="utf-8")


# ---------- Silent runs --------------------------------------------------


def test_silent_on_empty_project(tmp_path: Path) -> None:
    _seed_minimal_project(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_when_no_unexpected_dirs(tmp_path: Path) -> None:
    """Binaries that live ONLY in src/ (not an unexpected dir) are NOT
    surfaced. The unexpected-dir filter is the whole point of the
    detector — we don't compete with the suffix-only score that
    repo-trust-score already provides."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "src" / "loader.exe").write_bytes(_PE_TIGHT)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_on_known_safe_filenames(tmp_path: Path) -> None:
    """gradlew / mvnw wrappers ship with PE/MZ magic but are universally
    legitimate. They must be on the safe-list."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "gradlew.bat").write_bytes(_PE_TIGHT)
    (tmp_path / "scripts" / "mvnw.cmd").write_bytes(_PE_TIGHT)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- Fires on magic-byte hits in unexpected directories -----------


def test_fires_on_pe_in_image_dir(tmp_path: Path) -> None:
    """The canonical snakebite shape: a renamed PE in image/."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "dir.cc").write_bytes(_PE_TIGHT)  # renamed lua.exe
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[binary-magic-scanner]" in r.stdout
    assert "dir.cc" in r.stdout
    assert "pe-tight" in r.stdout


def test_fires_on_loose_mz_when_no_tight_match(tmp_path: Path) -> None:
    """A bare MZ binary (no \\x90\\x00 follow-up) still fires under the
    loose PE signature."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "old.exe").write_bytes(_PE_LOOSE)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[binary-magic-scanner]" in r.stdout
    assert "pe-loose" in r.stdout


def test_fires_on_elf_in_scripts_dir(tmp_path: Path) -> None:
    _seed_minimal_project(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "helper").write_bytes(_ELF)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "elf" in r.stdout


def test_fires_on_macho_in_examples_dir(tmp_path: Path) -> None:
    _seed_minimal_project(tmp_path)
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "demo").write_bytes(_MACHO_64LE)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "macho-64le" in r.stdout


def test_fires_on_wasm_in_docs_dir(tmp_path: Path) -> None:
    _seed_minimal_project(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "module.bin").write_bytes(_WASM)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "wasm" in r.stdout


def test_fires_on_zip_in_release_dir(tmp_path: Path) -> None:
    """PK\\x03\\x04 in a release/ dir — Proposal 2 nested-zip companion."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "release").mkdir()
    (tmp_path / "release" / "Software-2.9.zip").write_bytes(_ZIP)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "zip" in r.stdout


def test_fires_on_lua_bytecode_in_tests_dir(tmp_path: Path) -> None:
    """\\x1bLua bytecode magic — Proposal 10 compiled-Lua form."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "payload.dat").write_bytes(_LUA_BYTECODE)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "lua-bytecode" in r.stdout


def test_fires_on_lua_source_trojan_in_image_dir(tmp_path: Path) -> None:
    """The Lua-source obfuscator IIFE — Proposal 5 textual form. The
    snakebite / Sentinel / Pipeline-Sentinel `.txt`/`.cc` payloads all
    start with `return(function(...)`."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "bytecode.txt").write_bytes(_LUA_SOURCE_TROJAN)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "lua-source-iife" in r.stdout
    assert "bytecode.txt" in r.stdout


# ---------- Mach-O / Java disambiguation --------------------------------


def test_fat_macho_in_image_dir_labels_macho_fat(tmp_path: Path) -> None:
    """`CA FE BA BE` with a non-.class extension → universal Mach-O."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "tool").write_bytes(_MACHO_FAT)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "macho-fat" in r.stdout
    # Must NOT be labelled as java-class for the non-.class file.
    assert "java-class" not in r.stdout


def test_fat_macho_in_image_dir_with_class_extension_is_java(tmp_path: Path) -> None:
    """Same magic, `.class` extension → Java class file."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "Foo.class").write_bytes(_MACHO_FAT)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "java-class" in r.stdout


def test_tight_java_prefix_always_labels_java(tmp_path: Path) -> None:
    """The 8-byte tight Java prefix (CA FE BA BE 00 00 00 02) wins
    over the 4-byte fat-Mach-O prefix regardless of extension."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "no-ext").write_bytes(_JAVA_CLASS)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "java-class" in r.stdout


# ---------- Sample cap + count --------------------------------------------


def test_sample_cap_caps_at_five(tmp_path: Path) -> None:
    """Drop 7 binaries; the drift line must list 5 + an "…and 2 more" tail."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "image").mkdir()
    for i in range(7):
        (tmp_path / "image" / f"payload-{i}.bin").write_bytes(_PE_TIGHT)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "7 binary or Lua-payload" in r.stdout
    assert "and 2 more" in r.stdout


# ---------- Heartbeat hygiene --------------------------------------------


def test_silent_on_second_run_when_nothing_changed(tmp_path: Path) -> None:
    """Content-hash dedupe — same tree → no second drift line."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "x.exe").write_bytes(_PE_TIGHT)
    first = _run(tmp_path)
    assert "[binary-magic-scanner]" in first.stdout
    second = _run(tmp_path)
    assert second.returncode == 0
    assert second.stdout == ""


def test_re_fires_when_new_binary_appears(tmp_path: Path) -> None:
    """Adding a NEW binary bumps the hash and re-fires."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "x.exe").write_bytes(_PE_TIGHT)
    first = _run(tmp_path)
    assert "[binary-magic-scanner]" in first.stdout
    (tmp_path / "image" / "y.exe").write_bytes(_ELF)
    third = _run(tmp_path)
    assert "[binary-magic-scanner]" in third.stdout
    assert "y.exe" in third.stdout


# ---------- Skip trees ----------------------------------------------------


def test_node_modules_is_skipped(tmp_path: Path) -> None:
    """Binaries inside node_modules/ must NOT be reported even if the
    node_modules tree contains a scripts/ subdir."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "node_modules" / "foo" / "scripts").mkdir(parents=True)
    (tmp_path / "node_modules" / "foo" / "scripts" / "bad.exe").write_bytes(_PE_TIGHT)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_reports_dir_is_skipped(tmp_path: Path) -> None:
    """The janitor's own reports/ folder must NOT be scanned."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "reports" / "scripts").mkdir(parents=True)
    (tmp_path / "reports" / "scripts" / "leftover.exe").write_bytes(_PE_TIGHT)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- Self-scan guard ----------------------------------------------


def test_self_scan_guard_silences_detector(tmp_path: Path) -> None:
    """When the project root has a plugin.json claiming this IS the
    janitor's repo, the detector must short-circuit silently."""
    plug_dir = tmp_path / ".claude-plugin"
    plug_dir.mkdir()
    (plug_dir / "plugin.json").write_text(
        json.dumps({"name": "ai-maestro-janitor", "version": "0.5.1"}),
        encoding="utf-8",
    )
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "real-payload.exe").write_bytes(_PE_TIGHT)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- Feature flag --------------------------------------------------


def test_disabled_by_env_flag(tmp_path: Path) -> None:
    _seed_minimal_project(tmp_path)
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "bad.exe").write_bytes(_PE_TIGHT)
    r = _run(
        tmp_path,
        env_overrides={"CLAUDE_PLUGIN_OPTION_BINARY_MAGIC_SCANNER_ENABLED": "0"},
    )
    assert r.returncode == 0
    assert r.stdout == ""


# ---------- File budget ---------------------------------------------------


def test_max_files_budget_caps_walk(tmp_path: Path) -> None:
    """When the budget is 2, only 2 files get sniffed; everything else
    is invisible. The drift line reports those 2."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "image").mkdir()
    for i in range(5):
        (tmp_path / "image" / f"p{i}.exe").write_bytes(_PE_TIGHT)
    r = _run(
        tmp_path,
        env_overrides={"CLAUDE_PLUGIN_OPTION_BINARY_MAGIC_MAX_FILES": "2"},
    )
    assert r.returncode == 0
    assert "[binary-magic-scanner]" in r.stdout
    # Bounded count — depends on os.walk ordering, but never > 2.
    assert "2 binary" in r.stdout or "1 binary" in r.stdout


def test_invalid_max_files_falls_back_to_default(tmp_path: Path) -> None:
    """Non-numeric env value MUST not crash — degrades to default 5000."""
    _seed_minimal_project(tmp_path)
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "bad.exe").write_bytes(_PE_TIGHT)
    r = _run(
        tmp_path,
        env_overrides={"CLAUDE_PLUGIN_OPTION_BINARY_MAGIC_MAX_FILES": "not-a-number"},
    )
    assert r.returncode == 0
    assert "[binary-magic-scanner]" in r.stdout


# ---------- Gzip fixture (sanity check the magic table is wired) ---------


def test_fires_on_gzip_in_image_dir(tmp_path: Path) -> None:
    _seed_minimal_project(tmp_path)
    (tmp_path / "image").mkdir()
    (tmp_path / "image" / "data.bin").write_bytes(_GZIP)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "gzip" in r.stdout
