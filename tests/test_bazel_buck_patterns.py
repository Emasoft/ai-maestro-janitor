"""Tests for bazel_buck_patterns — 2 tests per rule, 22 total."""

from __future__ import annotations

import os
import sys

# Allow importing from scripts/lib without an installed package.
sys.path.insert(  # type: ignore[misc]  # noqa: E402
    0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib")
)

import bazel_buck_patterns as bzl  # type: ignore[import]  # noqa: E402

# ---- helpers ------------------------------------------------------------


def _ids(findings: list[bzl.Finding]) -> list[str]:
    return [f.rule_id for f in findings]


def _has(rule_id: str, text: str) -> bool:
    return rule_id in _ids(bzl.scan_text(text))


# ---- bzl-http-archive-no-sha256 -----------------------------------------


def test_http_archive_http_url_detected() -> None:
    """http_archive with plain http:// URL triggers bzl-http-archive-no-sha256."""
    snippet = """
http_archive(
    name = "rules_go",
    url = "http://mirror.example.com/rules_go-0.42.0.tar.gz",
)
"""
    assert _has("bzl-http-archive-no-sha256", snippet)


def test_http_archive_https_url_not_flagged() -> None:
    """http_archive with https:// URL does not trigger bzl-http-archive-no-sha256."""
    snippet = """
http_archive(
    name = "rules_go",
    url = "https://mirror.example.com/rules_go-0.42.0.tar.gz",
    sha256 = "abc123",
)
"""
    assert not _has("bzl-http-archive-no-sha256", snippet)


# ---- bzl-git-repo-http-remote -------------------------------------------


def test_git_repo_http_remote_detected() -> None:
    """git_repository with http:// remote triggers bzl-git-repo-http-remote."""
    snippet = 'git_repository(name = "mylib", remote = "http://github.com/corp/mylib.git", commit = "abc")'
    assert _has("bzl-git-repo-http-remote", snippet)


def test_git_repo_https_remote_not_flagged() -> None:
    """git_repository with https:// remote does not trigger bzl-git-repo-http-remote."""
    snippet = 'git_repository(name = "mylib", remote = "https://github.com/corp/mylib.git", commit = "deadbeef")'
    assert not _has("bzl-git-repo-http-remote", snippet)


# ---- bzl-git-repo-branch-pin --------------------------------------------


def test_git_repo_branch_pin_detected() -> None:
    """git_repository with branch = triggers bzl-git-repo-branch-pin."""
    snippet = """
git_repository(
    name = "rules_python",
    remote = "https://github.com/bazelbuild/rules_python.git",
    branch = "main",
)
"""
    assert _has("bzl-git-repo-branch-pin", snippet)


def test_git_repo_commit_pin_not_flagged() -> None:
    """git_repository with commit = does not trigger bzl-git-repo-branch-pin."""
    snippet = """
git_repository(
    name = "rules_python",
    remote = "https://github.com/bazelbuild/rules_python.git",
    commit = "e8b4536b5c27d07f4ba5d5c9dcb95ebab49ac6e7",
)
"""
    assert not _has("bzl-git-repo-branch-pin", snippet)


# ---- bzl-remote-upload-local-results ------------------------------------


def test_remote_upload_local_results_detected() -> None:
    """--remote_upload_local_results=true triggers bzl-remote-upload-local-results."""
    snippet = "build --remote_cache=grpcs://cache.buildbuddy.io/org --remote_upload_local_results=true"
    assert _has("bzl-remote-upload-local-results", snippet)


def test_remote_upload_local_results_false_not_flagged() -> None:
    """--remote_upload_local_results=false does not trigger bzl-remote-upload-local-results."""
    snippet = "build --remote_cache=grpcs://cache.buildbuddy.io/org --remote_upload_local_results=false"
    assert not _has("bzl-remote-upload-local-results", snippet)


# ---- bzl-genrule-cmd-srcs-unquoted --------------------------------------


def test_genrule_cmd_srcs_detected() -> None:
    """genrule cmd with unquoted $(SRCS) triggers bzl-genrule-cmd-srcs-unquoted."""
    snippet = """
genrule(
    name = "process",
    srcs = ["input.txt"],
    outs = ["output.txt"],
    cmd = "process $(SRCS) > $@",
)
"""
    assert _has("bzl-genrule-cmd-srcs-unquoted", snippet)


def test_genrule_cmd_no_srcs_not_flagged() -> None:
    """genrule cmd with no Make-variable expansion does not trigger bzl-genrule-cmd-srcs-unquoted."""
    snippet = """
genrule(
    name = "copy",
    srcs = ["input.txt"],
    outs = ["output.txt"],
    cmd = "cp $< $@",
)
"""
    assert not _has("bzl-genrule-cmd-srcs-unquoted", snippet)


# ---- bzl-genrule-external-tools -----------------------------------------


def test_genrule_external_tools_detected() -> None:
    """tools with @external_repo reference triggers bzl-genrule-external-tools."""
    snippet = """
genrule(
    name = "codegen",
    srcs = ["schema.proto"],
    outs = ["schema.pb.go"],
    tools = ["@com_github_protocolbuffers_protobuf//:protoc"],
    cmd = "$(location @com_github_protocolbuffers_protobuf//:protoc) ...",
)
"""
    assert _has("bzl-genrule-external-tools", snippet)


def test_genrule_local_tools_not_flagged() -> None:
    """tools referencing a local target does not trigger bzl-genrule-external-tools."""
    snippet = """
genrule(
    name = "codegen",
    srcs = ["schema.proto"],
    outs = ["schema.pb.go"],
    tools = ["//tools:protoc"],
    cmd = "$(location //tools:protoc) ...",
)
"""
    assert not _has("bzl-genrule-external-tools", snippet)


# ---- bzl-experimental-remote-downloader ---------------------------------


def test_experimental_remote_downloader_detected() -> None:
    """--experimental_remote_downloader to external host triggers the rule."""
    snippet = "build --experimental_remote_downloader=grpcs://downloader.corp.example.com:443"
    assert _has("bzl-experimental-remote-downloader", snippet)


def test_experimental_remote_downloader_localhost_not_flagged() -> None:
    """--experimental_remote_downloader=grpc://localhost is not flagged."""
    snippet = "build --experimental_remote_downloader=grpc://localhost:8080"
    assert not _has("bzl-experimental-remote-downloader", snippet)


# ---- bzl-pants-anonymous-telemetry --------------------------------------


def test_pants_telemetry_enabled_detected() -> None:
    """Pants [anonymous-telemetry] enabled = true triggers bzl-pants-anonymous-telemetry."""
    snippet = """
[anonymous-telemetry]
enabled = true
repo_id = "abc123"
"""
    assert _has("bzl-pants-anonymous-telemetry", snippet)


def test_pants_telemetry_disabled_not_flagged() -> None:
    """Pants [anonymous-telemetry] enabled = false does not trigger the rule."""
    snippet = """
[anonymous-telemetry]
enabled = false
"""
    assert not _has("bzl-pants-anonymous-telemetry", snippet)


# ---- bzl-pip-parse-http-requirements ------------------------------------


def test_pip_parse_http_requirements_detected() -> None:
    """pip_parse with http:// requirements_lock URL triggers the rule."""
    snippet = """
pip_parse(
    name = "pypi",
    requirements_lock = "http://internal.corp/requirements.lock",
)
"""
    assert _has("bzl-pip-parse-http-requirements", snippet)


def test_pip_parse_local_requirements_not_flagged() -> None:
    """pip_parse with a local path does not trigger bzl-pip-parse-http-requirements."""
    snippet = """
pip_parse(
    name = "pypi",
    requirements_lock = "//requirements.lock",
)
"""
    assert not _has("bzl-pip-parse-http-requirements", snippet)


# ---- bzl-disk-cache-world-writable --------------------------------------


def test_disk_cache_tmp_detected() -> None:
    """--disk_cache=/tmp/bazel triggers bzl-disk-cache-world-writable."""
    snippet = "build --disk_cache=/tmp/bazel-cache"
    assert _has("bzl-disk-cache-world-writable", snippet)


def test_disk_cache_home_dir_detected() -> None:
    """--disk_cache=~/.cache/bazel triggers bzl-disk-cache-world-writable."""
    snippet = "build --disk_cache=~/.cache/bazel"
    assert _has("bzl-disk-cache-world-writable", snippet)


# ---- bzl-buck2-run-local ------------------------------------------------


def test_buck2_run_local_detected() -> None:
    """ctx.actions.run_local() in BXL triggers bzl-buck2-run-local."""
    snippet = """
def _impl(ctx):
    out = ctx.actions.declare_output("result.txt")
    ctx.actions.run_local(
        cmd = ["bash", "-c", "echo hello > result.txt"],
        outputs = [out],
    )
"""
    assert _has("bzl-buck2-run-local", snippet)


def test_buck2_run_remote_not_flagged() -> None:
    """ctx.actions.run() (remote execution) does not trigger bzl-buck2-run-local."""
    snippet = """
def _impl(ctx):
    out = ctx.actions.declare_output("result.txt")
    ctx.actions.run(
        cmd = ["bash", "-c", "echo hello > result.txt"],
        outputs = [out],
    )
"""
    assert not _has("bzl-buck2-run-local", snippet)


# ---- contract checks ----------------------------------------------------


def test_rules_tuple_has_eleven_entries() -> None:
    """RULES tuple must contain exactly 11 rules."""
    assert len(bzl.RULES) == 11


def test_all_rule_ids_prefixed_bzl() -> None:
    """Every rule ID must start with 'bzl-'."""
    for rule in bzl.RULES:
        assert rule.id.startswith("bzl-"), f"Rule {rule.id!r} missing 'bzl-' prefix"


def test_scan_empty_string_returns_empty_list() -> None:
    """scan_text('') returns an empty list without raising."""
    assert bzl.scan_text("") == []


def test_finding_is_named_tuple_with_seven_fields() -> None:
    """Finding is a NamedTuple with the correct seven fields."""
    fields = bzl.Finding._fields  # type: ignore[attr-defined]
    assert fields == ("rule_id", "line", "column", "matched_text", "severity", "description", "owasp_asi")


def test_scan_text_line_numbers_are_one_based() -> None:
    """Finding.line values are 1-based."""
    snippet = "\n\nhttp_archive(\n    name = \"x\",\n    url = \"http://evil.com/x.tar\",\n)\n"
    findings = bzl.scan_text(snippet)
    assert findings, "Expected at least one finding"
    assert all(f.line >= 1 for f in findings)
