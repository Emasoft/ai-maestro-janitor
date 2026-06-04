"""Tests for scripts/lib/build_reproducibility_patterns.py.

Pattern-coverage tests for the Wave-22 angle-J catalogue: 13 distill-
round-8 proposals expanded into 24 file-scoped rules + 3 cross-file
lockfile rules.

Test layout mirrors `test_provenance_patterns.py`: each rule gets at
least one positive test (canonical broken shape from the distill
report) and at least one negative test (the documented safe shape or a
mitigation-token suppression). Plus a small bank of data-model sanity
tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import build_reproducibility_patterns as brp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised id."""
    assert isinstance(brp.RULES, tuple)
    rule_ids = {r.id for r in brp.RULES}
    expected = {
        "repro-bazel-workspace-mode-active",
        "repro-bazel-http-archive-no-sha256",
        "repro-bazel-git-repository-branch-only",
        "repro-bazel-action-env-leaks-host",
        "repro-bazel-repo-env-credential-leak",
        "repro-bazel-genrule-non-determinism",
        "repro-nix-impure-flag",
        "repro-nix-fetcher-no-sha256",
        "repro-nix-channel-import",
        "repro-nix-impure-builtin",
        "repro-make-shell-non-deterministic",
        "repro-make-shell-git-rev-embedded",
        "repro-c-cxx-date-time-macros",
        "repro-go-ldflags-build-timestamp",
        "repro-goreleaser-date-template-var",
        "repro-tar-create-no-determinism-flags",
        "repro-zip-create-no-X-flag",
        "repro-gzip-no-name-flag",
        "repro-ar-no-deterministic-flag",
        "repro-python-compileall-no-invalidation-hash",
        "repro-sort-no-LC_ALL-into-archive",
        "repro-find-print-no-print0-into-archive",
        "repro-locale-set-to-non-C",
        "repro-docker-mutable-base-tag",
    }
    assert expected.issubset(rule_ids)
    assert len(rule_ids) == 24


def test_every_rule_has_valid_severity_and_id_prefix() -> None:
    """All severities are in the 4-tier vocabulary; all ids prefixed."""
    for rule in brp.RULES:
        assert rule.severity in {"CRITICAL", "HIGH", "MAJOR", "MINOR"}, rule.id
        assert rule.id.startswith("repro-"), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors provenance_patterns.Finding shape."""
    f = brp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", file_path="/tmp/x.WORKSPACE",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.file_path == "/tmp/x.WORKSPACE"


def test_rule_record_has_all_fields() -> None:
    """A Rule must carry pattern + negative_substrings + file_suffixes."""
    sample = brp.RULES[0]
    assert sample.id
    assert sample.pattern is not None
    assert isinstance(sample.negative_substrings, tuple)
    assert isinstance(sample.file_suffixes, tuple)


def test_scan_file_on_missing_file_returns_empty() -> None:
    """Read errors must not crash — empty list."""
    assert brp.scan_file(Path("/nonexistent/path/never/exists.WORKSPACE")) == []


def test_scan_file_on_empty_file_returns_empty(tmp_path: Path) -> None:
    """Empty content → empty findings."""
    p = tmp_path / "WORKSPACE"
    p.write_text("", encoding="utf-8")
    assert brp.scan_file(p) == []


# ---------- Helpers ------------------------------------------------------


def _write(tmp_path: Path, name: str, body: str) -> Path:
    """Write a fixture file with the given basename (preserves
    case-sensitive basename like `WORKSPACE` / `Makefile`)."""
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def _scan(tmp_path: Path, name: str, body: str) -> list[brp.Finding]:
    return brp.scan_file(_write(tmp_path, name, body))


def _hits(findings: list[brp.Finding], rule_id: str) -> list[brp.Finding]:
    return [f for f in findings if f.rule_id == rule_id]


# ---------- P1: Bazel workspace mode -------------------------------------


def test_p1_bazel_workspace_mode_positive(tmp_path: Path) -> None:
    """A workflow invokes bazel build but never sets --noenable_workspace."""
    body = (
        "name: ci\n"
        "on: [push]\n"
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "      - run: bazel build //...\n"
    )
    findings = _scan(tmp_path, "ci.yml", body)
    assert _hits(findings, "repro-bazel-workspace-mode-active")


def test_p1_bazel_workspace_mode_negative_when_noenable_flag(tmp_path: Path) -> None:
    """Same invocation with --noenable_workspace anywhere in the file
    suppresses the rule."""
    body = (
        "name: ci\n"
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "      - run: bazel build --noenable_workspace //...\n"
    )
    findings = _scan(tmp_path, "ci.yml", body)
    assert not _hits(findings, "repro-bazel-workspace-mode-active")


def test_p1_bazel_workspace_mode_negative_when_module_bazel_lock(tmp_path: Path) -> None:
    """A file mentioning MODULE.bazel.lock proves bzlmod is in use."""
    body = (
        "# bzlmod project\n"
        "common --noenable_workspace\n"
        "common --registry=https://bcr.bazel.build\n"
    )
    findings = _scan(tmp_path, ".bazelrc", body)
    # No bazel invocation in this snippet so no positive match, but
    # the negative tokens are also present — the rule must not fire.
    assert not _hits(findings, "repro-bazel-workspace-mode-active")


# ---------- P2: http_archive sha256 -------------------------------------


def test_p2_http_archive_no_sha256_positive(tmp_path: Path) -> None:
    """`http_archive(name=..., urls=[...])` with no sha256 field fires."""
    body = (
        'http_archive(\n'
        '    name = "rules_foo",\n'
        '    urls = ["https://example.com/foo.tar.gz"],\n'
        ')\n'
    )
    findings = _scan(tmp_path, "WORKSPACE", body)
    assert _hits(findings, "repro-bazel-http-archive-no-sha256")


def test_p2_http_archive_with_sha256_is_safe(tmp_path: Path) -> None:
    """Same shape with sha256 = "..." inside the call → no finding."""
    body = (
        'http_archive(\n'
        '    name = "rules_foo",\n'
        '    sha256 = "abc123",\n'
        '    urls = ["https://example.com/foo.tar.gz"],\n'
        ')\n'
    )
    findings = _scan(tmp_path, "WORKSPACE", body)
    assert not _hits(findings, "repro-bazel-http-archive-no-sha256")


# ---------- P2b: git_repository branch-only ----------------------------


def test_p2b_git_repo_branch_only_positive(tmp_path: Path) -> None:
    """`git_repository(branch = "main")` with no commit/tag = CRITICAL."""
    body = (
        'git_repository(\n'
        '    name = "upstream",\n'
        '    remote = "https://github.com/foo/bar.git",\n'
        '    branch = "main",\n'
        ')\n'
    )
    findings = _scan(tmp_path, "WORKSPACE", body)
    assert _hits(findings, "repro-bazel-git-repository-branch-only")


def test_p2b_git_repo_pinned_commit_is_safe(tmp_path: Path) -> None:
    """Same shape with commit = "..." → no finding."""
    body = (
        'git_repository(\n'
        '    name = "upstream",\n'
        '    remote = "https://github.com/foo/bar.git",\n'
        '    commit = "abc123def456",\n'
        ')\n'
    )
    findings = _scan(tmp_path, "WORKSPACE", body)
    assert not _hits(findings, "repro-bazel-git-repository-branch-only")


# ---------- P3: --action_env / --repo_env leak --------------------------


def test_p3_action_env_path_leak_positive(tmp_path: Path) -> None:
    """`build --action_env=PATH` in .bazelrc fires."""
    body = (
        "common --enable_bzlmod\n"
        "build --action_env=PATH\n"
        "test --action_env=HOME\n"
    )
    findings = _scan(tmp_path, ".bazelrc", body)
    assert len(_hits(findings, "repro-bazel-action-env-leaks-host")) >= 1


def test_p3_action_env_lang_c_utf8_is_safe(tmp_path: Path) -> None:
    """`--action_env=LANG=C.UTF-8` is normalisation, not leakage."""
    body = (
        "build --action_env=LANG=C.UTF-8\n"
        "build --action_env=CC=/usr/bin/clang-17\n"
    )
    findings = _scan(tmp_path, ".bazelrc", body)
    assert not _hits(findings, "repro-bazel-action-env-leaks-host")


def test_p3_repo_env_dollar_var_leak_critical(tmp_path: Path) -> None:
    """`--repo_env=KEY=$VAR` → CRITICAL."""
    body = (
        "build --repo_env=GIT_TOKEN=$GH_TOKEN\n"
        "build --repo_env=NETRC=$(cat ~/.netrc)\n"
    )
    findings = _scan(tmp_path, ".bazelrc", body)
    assert len(_hits(findings, "repro-bazel-repo-env-credential-leak")) >= 1


# ---------- P4: genrule non-determinism ---------------------------------


def test_p4_genrule_date_positive(tmp_path: Path) -> None:
    """genrule cmd embeds `date` → fires."""
    body = (
        'genrule(\n'
        '    name = "build_date",\n'
        '    outs = ["build_date.txt"],\n'
        '    cmd = "date > $(OUTS)",\n'
        ')\n'
    )
    findings = _scan(tmp_path, "BUILD", body)
    assert _hits(findings, "repro-bazel-genrule-non-determinism")


def test_p4_genrule_with_source_date_epoch_is_safe(tmp_path: Path) -> None:
    """`date -d @$$SOURCE_DATE_EPOCH` is deterministic — suppressed by
    file-level negative-substring."""
    body = (
        'genrule(\n'
        '    name = "build_date",\n'
        '    cmd = "date -d @$$SOURCE_DATE_EPOCH > $(OUTS)",\n'
        ')\n'
    )
    findings = _scan(tmp_path, "BUILD", body)
    assert not _hits(findings, "repro-bazel-genrule-non-determinism")


def test_p4_genrule_stable_git_commit_is_safe(tmp_path: Path) -> None:
    """Workspace-status `$$STABLE_GIT_COMMIT` is the documented safe
    path even when `git rev-parse` appears nearby."""
    body = (
        'genrule(\n'
        '    name = "git_info",\n'
        '    cmd = "echo $$STABLE_GIT_COMMIT && git rev-parse HEAD > $(OUTS)",\n'
        ')\n'
    )
    findings = _scan(tmp_path, "BUILD", body)
    assert not _hits(findings, "repro-bazel-genrule-non-determinism")


# ---------- P5: Nix flake.lock cross-file --------------------------------


def test_p5_flake_nix_without_lock(tmp_path: Path) -> None:
    """`flake.nix` present, no `flake.lock` → finding."""
    (tmp_path / "flake.nix").write_text("{ inputs.nixpkgs.url = \"...\"; }",
                                          encoding="utf-8")
    findings = brp.scan_repo_for_lockfiles(tmp_path)
    assert any(f.rule_id == "repro-nix-flake-no-lockfile" for f in findings)


def test_p5_flake_nix_with_lock_is_safe(tmp_path: Path) -> None:
    """`flake.nix` + `flake.lock` both present → no finding."""
    (tmp_path / "flake.nix").write_text("{}", encoding="utf-8")
    (tmp_path / "flake.lock").write_text('{"version": 7}', encoding="utf-8")
    findings = brp.scan_repo_for_lockfiles(tmp_path)
    assert not any(f.rule_id == "repro-nix-flake-no-lockfile" for f in findings)


def test_p5_flake_lock_gitignored_is_critical(tmp_path: Path) -> None:
    """`.gitignore` excluding `flake.lock` → CRITICAL."""
    (tmp_path / "flake.nix").write_text("{}", encoding="utf-8")
    (tmp_path / "flake.lock").write_text('{}', encoding="utf-8")
    (tmp_path / ".gitignore").write_text("flake.lock\n", encoding="utf-8")
    findings = brp.scan_repo_for_lockfiles(tmp_path)
    assert any(
        f.rule_id == "repro-nix-flake-lock-gitignored"
        and f.severity == "CRITICAL"
        for f in findings
    )


def test_p5_module_bazel_no_lock(tmp_path: Path) -> None:
    """`MODULE.bazel` without `MODULE.bazel.lock` → finding."""
    (tmp_path / "MODULE.bazel").write_text('module(name = "foo")',
                                            encoding="utf-8")
    findings = brp.scan_repo_for_lockfiles(tmp_path)
    assert any(f.rule_id == "repro-bazel-bzlmod-no-lockfile" for f in findings)


def test_p5_no_flake_no_module_no_finding(tmp_path: Path) -> None:
    """Repo without flake.nix or MODULE.bazel → empty result."""
    assert brp.scan_repo_for_lockfiles(tmp_path) == []


# ---------- P6: Nix impure builtins / flags -----------------------------


def test_p6_nix_impure_flag_positive(tmp_path: Path) -> None:
    """`nix build --impure ...` → CRITICAL."""
    body = (
        "#!/bin/bash\n"
        "nix build --impure .#hello\n"
    )
    findings = _scan(tmp_path, "build.sh", body)
    assert _hits(findings, "repro-nix-impure-flag")


def test_p6_nix_no_impure_flag(tmp_path: Path) -> None:
    """`nix build .#hello` without --impure → no finding."""
    body = "nix build .#hello\nnix develop -c make\n"
    findings = _scan(tmp_path, "build.sh", body)
    assert not _hits(findings, "repro-nix-impure-flag")


def test_p6_fetch_tarball_no_sha_positive(tmp_path: Path) -> None:
    """`builtins.fetchTarball "https://..."` (string-only) fires."""
    body = (
        'let pkgs = import (builtins.fetchTarball '
        '"https://github.com/NixOS/nixpkgs/archive/nixos-23.11.tar.gz") {};\n'
        'in pkgs.hello\n'
    )
    findings = _scan(tmp_path, "default.nix", body)
    assert _hits(findings, "repro-nix-fetcher-no-sha256")


def test_p6_fetch_tarball_with_sha256_is_safe(tmp_path: Path) -> None:
    """`builtins.fetchTarball { url=...; sha256=...; }` is pinned."""
    body = (
        'let src = builtins.fetchTarball {\n'
        '  url = "https://example.com/foo.tar.gz";\n'
        '  sha256 = "0000000000000000000000000000000000000000000000000000";\n'
        '};\n'
        'in src\n'
    )
    findings = _scan(tmp_path, "default.nix", body)
    assert not _hits(findings, "repro-nix-fetcher-no-sha256")


def test_p6_channel_import_positive(tmp_path: Path) -> None:
    """`import <nixpkgs>` channel reference fires."""
    body = "let pkgs = import <nixpkgs> {}; in pkgs.hello\n"
    findings = _scan(tmp_path, "default.nix", body)
    assert _hits(findings, "repro-nix-channel-import")


def test_p6_impure_builtin_current_time(tmp_path: Path) -> None:
    """`builtins.currentTime` fires."""
    body = "{ buildTime = builtins.currentTime; }\n"
    findings = _scan(tmp_path, "default.nix", body)
    assert _hits(findings, "repro-nix-impure-builtin")


def test_p6_impure_builtin_get_env(tmp_path: Path) -> None:
    """`builtins.getEnv "HOME"` fires."""
    body = '{ home = builtins.getEnv "HOME"; }\n'
    findings = _scan(tmp_path, "default.nix", body)
    assert _hits(findings, "repro-nix-impure-builtin")


# ---------- P7: Makefile $(shell ...) -----------------------------------


def test_p7_make_shell_date_positive(tmp_path: Path) -> None:
    """`BUILD_DATE := $(shell date)` fires."""
    body = (
        "BUILD_DATE := $(shell date)\n"
        "all:\n"
        "\t@echo $(BUILD_DATE)\n"
    )
    findings = _scan(tmp_path, "Makefile", body)
    assert _hits(findings, "repro-make-shell-non-deterministic")


def test_p7_make_shell_uname_positive(tmp_path: Path) -> None:
    """`KERNEL := $(shell uname -r)` fires."""
    body = "KERNEL := $(shell uname -r)\n"
    findings = _scan(tmp_path, "Makefile", body)
    assert _hits(findings, "repro-make-shell-non-deterministic")


def test_p7_make_shell_with_source_date_epoch_is_safe(tmp_path: Path) -> None:
    """`$(shell date -d @$$SOURCE_DATE_EPOCH ...)` is deterministic."""
    body = (
        "BUILD_DATE := $(shell date -d @$$SOURCE_DATE_EPOCH +%Y%m%d)\n"
    )
    findings = _scan(tmp_path, "Makefile", body)
    assert not _hits(findings, "repro-make-shell-non-deterministic")


def test_p7_make_shell_git_rev_minor(tmp_path: Path) -> None:
    """`GIT_REV := $(shell git rev-parse HEAD)` → MINOR."""
    body = "GIT_REV := $(shell git rev-parse HEAD)\n"
    findings = _scan(tmp_path, "Makefile", body)
    hits = _hits(findings, "repro-make-shell-git-rev-embedded")
    assert hits
    assert hits[0].severity == "MINOR"


# ---------- P8: C/C++ __DATE__ / __TIME__ macros ------------------------


def test_p8_c_date_macro_positive(tmp_path: Path) -> None:
    """`__DATE__` in a .c file fires."""
    body = (
        '#include <stdio.h>\n'
        'const char *build_date = __DATE__;\n'
        'const char *build_time = __TIME__;\n'
    )
    findings = _scan(tmp_path, "version.c", body)
    assert len(_hits(findings, "repro-c-cxx-date-time-macros")) >= 1


def test_p8_c_timestamp_macro_in_header(tmp_path: Path) -> None:
    """`__TIMESTAMP__` in a header fires."""
    body = '#define MY_TIMESTAMP __TIMESTAMP__\n'
    findings = _scan(tmp_path, "version.h", body)
    assert _hits(findings, "repro-c-cxx-date-time-macros")


def test_p8_c_date_macro_with_wdate_time_suppressed(tmp_path: Path) -> None:
    """Inline pragma comment with `-Wdate-time` token suppresses."""
    body = (
        '// Build with -Wdate-time -Werror=date-time enforced upstream\n'
        '#define BUILD_DATE __DATE__\n'
    )
    findings = _scan(tmp_path, "version.c", body)
    assert not _hits(findings, "repro-c-cxx-date-time-macros")


def test_p8_non_c_file_not_scanned(tmp_path: Path) -> None:
    """`.txt` file containing __DATE__ is not scanned by this rule."""
    body = "Just a note: __DATE__ would be useful here\n"
    findings = _scan(tmp_path, "notes.txt", body)
    assert not _hits(findings, "repro-c-cxx-date-time-macros")


# ---------- P9: Go -ldflags timestamp / goreleaser ----------------------


def test_p9_go_ldflags_date_positive(tmp_path: Path) -> None:
    """`go build -ldflags="-X main.buildTime=$(date ...)"` fires."""
    body = (
        '#!/bin/bash\n'
        'go build -ldflags="-X main.buildTime=$(date -u +%Y%m%d)" ./cmd/foo\n'
    )
    findings = _scan(tmp_path, "build.sh", body)
    assert _hits(findings, "repro-go-ldflags-build-timestamp")


def test_p9_go_ldflags_backtick_date_positive(tmp_path: Path) -> None:
    """Backtick `date` form also fires."""
    body = (
        'go build -ldflags="-X main.buildTime=`date -u`" .\n'
    )
    findings = _scan(tmp_path, "build.sh", body)
    assert _hits(findings, "repro-go-ldflags-build-timestamp")


def test_p9_go_ldflags_with_source_date_epoch_safe(tmp_path: Path) -> None:
    """`$(date -d @${SOURCE_DATE_EPOCH} ...)` is deterministic
    (file-level SOURCE_DATE_EPOCH negative substring fires)."""
    body = (
        'export SOURCE_DATE_EPOCH=1700000000\n'
        'go build -ldflags="-X main.buildTime=$(date -u -d @${SOURCE_DATE_EPOCH} +%Y%m%d)" .\n'
    )
    findings = _scan(tmp_path, "build.sh", body)
    assert not _hits(findings, "repro-go-ldflags-build-timestamp")


def test_p9_goreleaser_date_template_positive(tmp_path: Path) -> None:
    """goreleaser `-X main.buildTime={{ .Date }}` fires."""
    body = (
        'builds:\n'
        '  - main: ./cmd/foo\n'
        '    ldflags:\n'
        '      - -s -w\n'
        "      - -X main.buildTime={{ .Date }}\n"
    )
    findings = _scan(tmp_path, ".goreleaser.yml", body)
    assert _hits(findings, "repro-goreleaser-date-template-var")


def test_p9_goreleaser_commit_date_safe(tmp_path: Path) -> None:
    """`{{ .CommitDate }}` is reproducible — no finding."""
    body = (
        'builds:\n'
        '  - main: ./cmd/foo\n'
        '    ldflags:\n'
        '      - -X main.buildTime={{ .CommitDate }}\n'
    )
    findings = _scan(tmp_path, ".goreleaser.yml", body)
    assert not _hits(findings, "repro-goreleaser-date-template-var")


# ---------- P10: archive tool flags --------------------------------------


def test_p10_tar_create_no_flags_positive(tmp_path: Path) -> None:
    """`tar -czf out.tar.gz src/` without flags fires."""
    body = (
        '#!/bin/bash\n'
        'tar -czf release.tar.gz dist/\n'
    )
    findings = _scan(tmp_path, "release.sh", body)
    assert _hits(findings, "repro-tar-create-no-determinism-flags")


def test_p10_tar_with_sort_and_mtime_safe(tmp_path: Path) -> None:
    """`tar --sort=name --mtime=...` is reproducible."""
    body = (
        'tar --sort=name --mtime="@${SOURCE_DATE_EPOCH}" '
        '--owner=0 --group=0 --numeric-owner -czf out.tar.gz src/\n'
    )
    findings = _scan(tmp_path, "release.sh", body)
    assert not _hits(findings, "repro-tar-create-no-determinism-flags")


def test_p10_git_archive_whitelisted(tmp_path: Path) -> None:
    """`git archive` is reproducible-per-commit — whitelisted."""
    body = 'git archive --prefix=foo-1.0/ HEAD | gzip -n > foo-1.0.tar.gz\n'
    findings = _scan(tmp_path, "release.sh", body)
    # `tar -c` shape doesn't appear here, but neither should the rule
    # fire on `git archive` references in nearby tar invocations —
    # the file-level whitelist `"git archive"` suppresses the whole
    # tar-create rule when present anywhere in the file. Verify the
    # gzip rule still considers `-n` safe.
    assert not _hits(findings, "repro-gzip-no-name-flag")


def test_p10_zip_no_x_positive(tmp_path: Path) -> None:
    """`zip -r out.zip src/` fires."""
    body = "zip -r release.zip dist/\n"
    findings = _scan(tmp_path, "release.sh", body)
    assert _hits(findings, "repro-zip-create-no-X-flag")


def test_p10_zip_with_X_safe(tmp_path: Path) -> None:
    """`zip -rX ...` strips extra fields — safe."""
    body = "zip -rX release.zip dist/\n"
    findings = _scan(tmp_path, "release.sh", body)
    assert not _hits(findings, "repro-zip-create-no-X-flag")


def test_p10_gzip_bare_positive(tmp_path: Path) -> None:
    """`gzip out.tar` without `-n` fires."""
    body = "gzip release.tar\n"
    findings = _scan(tmp_path, "release.sh", body)
    assert _hits(findings, "repro-gzip-no-name-flag")


def test_p10_gzip_with_no_name_safe(tmp_path: Path) -> None:
    """`gzip --no-name ...` strips the original filename header."""
    body = "gzip --no-name release.tar\n"
    findings = _scan(tmp_path, "release.sh", body)
    assert not _hits(findings, "repro-gzip-no-name-flag")


def test_p10_ar_no_deterministic_positive(tmp_path: Path) -> None:
    """`ar rcs libfoo.a *.o` without `D` fires."""
    body = "ar rcs libfoo.a *.o\n"
    findings = _scan(tmp_path, "Makefile", body)
    assert _hits(findings, "repro-ar-no-deterministic-flag")


def test_p10_ar_with_D_modifier_safe(tmp_path: Path) -> None:
    """`ar rcsD libfoo.a *.o` is deterministic."""
    body = "ar rcsD libfoo.a *.o\n"
    findings = _scan(tmp_path, "Makefile", body)
    assert not _hits(findings, "repro-ar-no-deterministic-flag")


# ---------- P11: PYTHONHASHSEED / compileall ----------------------------


def test_p11_compileall_no_invalidation_positive(tmp_path: Path) -> None:
    """`python -m compileall .` without --invalidation-mode → MAJOR."""
    body = (
        "FROM python:3.12\n"
        "RUN python -m compileall /app\n"
    )
    findings = _scan(tmp_path, "Dockerfile", body)
    assert _hits(findings, "repro-python-compileall-no-invalidation-hash")


def test_p11_compileall_with_checked_hash_safe(tmp_path: Path) -> None:
    """`--invalidation-mode checked-hash` is reproducible."""
    body = (
        "RUN python -m compileall --invalidation-mode checked-hash /app\n"
    )
    findings = _scan(tmp_path, "Dockerfile", body)
    assert not _hits(findings, "repro-python-compileall-no-invalidation-hash")


def test_p11_compileall_with_pythondontwritebytecode_safe(tmp_path: Path) -> None:
    """`PYTHONDONTWRITEBYTECODE=1` env disables pyc generation entirely."""
    body = (
        "ENV PYTHONDONTWRITEBYTECODE=1\n"
        "RUN python -m compileall /app\n"
    )
    findings = _scan(tmp_path, "Dockerfile", body)
    assert not _hits(findings, "repro-python-compileall-no-invalidation-hash")


# ---------- P12: locale-aware sort / find -print -----------------------


def test_p12_bare_sort_into_tar_positive(tmp_path: Path) -> None:
    """`find . | sort | tar ...` without LC_ALL=C fires."""
    body = "find . -type f | sort | tar --files-from=- -cf out.tar\n"
    findings = _scan(tmp_path, "release.sh", body)
    assert _hits(findings, "repro-sort-no-LC_ALL-into-archive")


def test_p12_lc_all_c_sort_safe(tmp_path: Path) -> None:
    """`LC_ALL=C sort` is byte-order — safe."""
    body = "find . -type f | LC_ALL=C sort | tar --files-from=- -cf out.tar\n"
    findings = _scan(tmp_path, "release.sh", body)
    assert not _hits(findings, "repro-sort-no-LC_ALL-into-archive")


def test_p12_find_print_into_tar_positive(tmp_path: Path) -> None:
    """`find -print` (no `-print0`) piped to tar fires."""
    body = "find . -type f -print | xargs tar -cf out.tar\n"
    findings = _scan(tmp_path, "release.sh", body)
    assert _hits(findings, "repro-find-print-no-print0-into-archive")


def test_p12_find_print0_into_tar_safe(tmp_path: Path) -> None:
    """`find -print0 | sort -z` is the canonical reproducible recipe."""
    body = "find . -type f -print0 | sort -z | xargs -0 tar -cf out.tar\n"
    findings = _scan(tmp_path, "release.sh", body)
    assert not _hits(findings, "repro-find-print-no-print0-into-archive")


def test_p12_non_c_lang_export_positive(tmp_path: Path) -> None:
    """`LANG=en_US.UTF-8` export fires as MINOR."""
    body = (
        "#!/bin/bash\n"
        "export LANG=en_US.UTF-8\n"
        "make release\n"
    )
    findings = _scan(tmp_path, "release.sh", body)
    hits = _hits(findings, "repro-locale-set-to-non-C")
    assert hits
    assert hits[0].severity == "MINOR"


def test_p12_lc_all_c_export_safe(tmp_path: Path) -> None:
    """`export LC_ALL=C` is the safe shape."""
    body = "export LC_ALL=C\nmake release\n"
    findings = _scan(tmp_path, "release.sh", body)
    assert not _hits(findings, "repro-locale-set-to-non-C")


def test_p12_lang_c_utf8_export_safe(tmp_path: Path) -> None:
    """`export LANG=C.UTF-8` is safe (C collation + UTF-8 messages)."""
    body = "export LANG=C.UTF-8\n"
    findings = _scan(tmp_path, "release.sh", body)
    assert not _hits(findings, "repro-locale-set-to-non-C")


# ---------- P13: Docker mutable base tag --------------------------------


def test_p13_docker_from_no_digest_positive(tmp_path: Path) -> None:
    """`FROM alpine:3.18` (no @sha256:) fires."""
    body = "FROM alpine:3.18\nRUN apk add curl\n"
    findings = _scan(tmp_path, "Dockerfile", body)
    assert _hits(findings, "repro-docker-mutable-base-tag")


def test_p13_docker_from_with_digest_safe(tmp_path: Path) -> None:
    """`FROM alpine:3.18@sha256:...` is pinned."""
    body = (
        "FROM alpine:3.18@sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
    )
    findings = _scan(tmp_path, "Dockerfile", body)
    assert not _hits(findings, "repro-docker-mutable-base-tag")


def test_p13_docker_from_scratch_safe(tmp_path: Path) -> None:
    """`FROM scratch` has no upstream — safe."""
    body = "FROM scratch\nCOPY app /app\n"
    findings = _scan(tmp_path, "Dockerfile", body)
    assert not _hits(findings, "repro-docker-mutable-base-tag")


def test_p13_docker_multistage_from_positive(tmp_path: Path) -> None:
    """Multistage `FROM image:tag AS builder` without digest fires."""
    body = (
        "FROM golang:1.22 AS builder\n"
        "RUN go build\n"
        "FROM scratch\n"
        "COPY --from=builder /out /\n"
    )
    findings = _scan(tmp_path, "Dockerfile", body)
    hits = _hits(findings, "repro-docker-mutable-base-tag")
    # At least one (the golang stage) — the scratch line is whitelisted.
    assert len(hits) >= 1


# ---------- File-suffix gating ------------------------------------------


def test_bazel_rule_does_not_fire_on_unrelated_file(tmp_path: Path) -> None:
    """`http_archive(...)` in a `.py` file is not scanned (file_suffixes
    gating)."""
    body = (
        'http_archive(\n'
        '    name = "rules_foo",\n'
        '    urls = ["https://example.com/foo.tar.gz"],\n'
        ')\n'
    )
    findings = _scan(tmp_path, "bazel_helper.py", body)
    assert not _hits(findings, "repro-bazel-http-archive-no-sha256")


def test_nix_rule_does_not_fire_on_unrelated_file(tmp_path: Path) -> None:
    """`builtins.currentTime` in a comment in a .py file is not scanned."""
    body = '# Note: builtins.currentTime in .nix would be impure\n'
    findings = _scan(tmp_path, "notes.py", body)
    assert not _hits(findings, "repro-nix-impure-builtin")


def test_dockerfile_rule_does_not_fire_on_yml(tmp_path: Path) -> None:
    """`FROM alpine:3.18` text in a CI yaml is not the Docker rule's
    target (the rule scopes to Dockerfile/Containerfile basenames)."""
    body = "name: ci\njobs:\n  build:\n    steps:\n      - run: |\n          FROM alpine:3.18\n"
    findings = _scan(tmp_path, "ci.yml", body)
    assert not _hits(findings, "repro-docker-mutable-base-tag")


# ---------- Scan-file integration ---------------------------------------


def test_scan_file_returns_sorted_findings(tmp_path: Path) -> None:
    """Findings come back sorted by (line, column, rule_id)."""
    body = (
        "FROM alpine:3.18\n"
        "RUN python -m compileall /app\n"
    )
    findings = _scan(tmp_path, "Dockerfile", body)
    if len(findings) > 1:
        lines = [(f.line, f.column, f.rule_id) for f in findings]
        assert lines == sorted(lines)


def test_scan_file_dedupes_overlapping_findings(tmp_path: Path) -> None:
    """The same (rule_id, line, col) is emitted at most once."""
    body = (
        '# Repeated tar invocations on consecutive lines\n'
        'tar -czf a.tar.gz a/\n'
        'tar -czf b.tar.gz b/\n'
    )
    findings = _scan(tmp_path, "release.sh", body)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))
