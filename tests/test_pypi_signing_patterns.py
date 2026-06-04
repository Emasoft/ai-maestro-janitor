"""Tests for scripts/lib/pypi_signing_patterns.py.

Pattern-coverage tests for the Wave-21 Round-7 angle G PyPI ecosystem
rule catalogue (dep-confusion, quarantine, sdist-build-allowed,
unhashed-requirements, long-lived-publish-token, mutable-action-tag,
missing-attestations, arbitrary-URL install, mutable-git-ref,
trusted-host TLS bypass, unpinned [build-system], legacy setup.py,
weak-conda-channel-priority, --no-build-isolation, missing-pip-audit
gate, known-typosquat-IOC, gitignored-audit-log).

Each rule gets one or more positive tests + at least one negative
test exercising the carve-out. ~40 tests in total.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import pypi_signing_patterns as psp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Synthetic secret-shaped fixtures ---------------------------------
# Prefixes are assembled from fragments at runtime so no contiguous
# real-format secret literal exists in this source file at rest.
_PYPI = "pypi" + "-"

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(psp.RULES, tuple)
    rule_ids = {r.id for r in psp.RULES}
    expected = {
        "pypi-dep-confusion-extra-index-url",
        "pypi-quarantine-window-missing",
        "pypi-quarantine-malformed-iso8601",
        "pypi-sdist-build-allowed",
        "pypi-requirements-no-hashes",
        "pypi-publish-long-lived-token",
        "pypi-publish-action-tag-not-sha-pinned",
        "pypi-publish-missing-attestations",
        "pypi-install-from-arbitrary-url",
        "pypi-install-from-mutable-git-ref",
        "pypi-trusted-host-tls-bypass",
        "pypi-build-system-unpinned",
        "pypi-legacy-setup-py-install",
        "pypi-conda-channel-priority-weak",
        "pypi-no-build-isolation",
        "pypi-no-pip-audit-gate",
        "pypi-known-typosquat-ioc",
        "pypi-audit-log-missing-marker",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_owasp_mapping() -> None:
    """Every rule maps to a non-empty ASI- prefix + valid severity."""
    for rule in psp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the agent_config_patterns.Finding shape."""
    f = psp.Finding(
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


def test_known_pypi_iocs_is_tuple_of_tuples() -> None:
    """KNOWN_PYPI_IOCS is the curated frozen IOC list."""
    assert isinstance(psp.KNOWN_PYPI_IOCS, tuple)
    for entry in psp.KNOWN_PYPI_IOCS:
        assert isinstance(entry, tuple)
        assert len(entry) == 3
        name, ver, reason = entry
        assert isinstance(name, str) and name
        assert ver is None or isinstance(ver, str)
        assert isinstance(reason, str) and reason


def test_empty_text_returns_no_findings() -> None:
    """Empty input is a no-op."""
    assert psp.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[psp.Finding]:
    return [f for f in psp.scan_text(text) if f.rule_id == rule_id]


# ---------- Rule 1 : pypi-dep-confusion-extra-index-url ------------------


def test_dep_confusion_extra_index_url_in_requirements() -> None:
    """`--extra-index-url` flag fires the rule."""
    src = (
        "requests==2.31.0\n"
        "--extra-index-url https://my-private.example.com/simple\n"
        "my-private-pkg==1.0.0\n"
    )
    assert _hits("pypi-dep-confusion-extra-index-url", src)


def test_dep_confusion_env_var_assignment() -> None:
    """`PIP_EXTRA_INDEX_URL=...` shell-script form fires."""
    src = 'export PIP_EXTRA_INDEX_URL="https://internal/simple"\n'
    assert _hits("pypi-dep-confusion-extra-index-url", src)


def test_dep_confusion_pipfile_verify_ssl_false() -> None:
    """Pipfile `verify_ssl = false` source block fires."""
    src = (
        "[[source]]\n"
        'name = "private"\n'
        'url = "https://my-private.example.com/simple"\n'
        "verify_ssl = false\n"
    )
    assert _hits("pypi-dep-confusion-extra-index-url", src)


def test_dep_confusion_poetry_supplemental_priority() -> None:
    """Poetry `priority = \"supplemental\"` fires."""
    src = (
        "[[tool.poetry.source]]\n"
        'name = "private"\n'
        'url = "https://my-private.example.com/simple"\n'
        'priority = "supplemental"\n'
    )
    assert _hits("pypi-dep-confusion-extra-index-url", src)


def test_dep_confusion_canonical_pypi_url_does_not_fire() -> None:
    """`--extra-index-url https://pypi.org/simple` is canonical → no hit."""
    src = "--extra-index-url https://pypi.org/simple\n"
    assert not _hits("pypi-dep-confusion-extra-index-url", src)


def test_dep_confusion_canonical_files_pythonhosted_does_not_fire() -> None:
    """files.pythonhosted.org is canonical → no hit."""
    src = "-i https://files.pythonhosted.org/simple\n"
    assert not _hits("pypi-dep-confusion-extra-index-url", src)


# ---------- Rule 2 : pypi-quarantine-window-missing ----------------------


def test_quarantine_window_too_short_seven_days() -> None:
    """`exclude-newer = \"7 days\"` is below the 14-day floor."""
    src = (
        "[tool.uv]\n"
        'exclude-newer = "7 days"\n'
    )
    assert _hits("pypi-quarantine-window-missing", src)


def test_quarantine_window_too_short_env_var() -> None:
    """`UV_EXCLUDE_NEWER=5 days` env-assignment fires."""
    src = 'export UV_EXCLUDE_NEWER="5 days"\n'
    assert _hits("pypi-quarantine-window-missing", src)


def test_quarantine_window_pip_p7d() -> None:
    """`uploaded-prior-to = P7D` fires (< 14 days)."""
    src = (
        "[install]\n"
        "uploaded-prior-to = P7D\n"
    )
    assert _hits("pypi-quarantine-window-missing", src)


def test_quarantine_window_fourteen_days_does_not_fire() -> None:
    """`exclude-newer = \"14 days\"` is on the floor → no hit."""
    src = 'exclude-newer = "14 days"\n'
    assert not _hits("pypi-quarantine-window-missing", src)


def test_quarantine_window_thirty_days_does_not_fire() -> None:
    """`UV_EXCLUDE_NEWER=30 days` is above the floor → no hit."""
    src = "UV_EXCLUDE_NEWER='30 days'\n"
    assert not _hits("pypi-quarantine-window-missing", src)


# ---------- Rule 3 : pypi-quarantine-malformed-iso8601 -------------------


def test_quarantine_malformed_human_readable_form() -> None:
    """`PIP_UPLOADED_PRIOR_TO=14 days` silently fails to parse → finding."""
    src = 'PIP_UPLOADED_PRIOR_TO="14 days"\n'
    assert _hits("pypi-quarantine-malformed-iso8601", src)


def test_quarantine_malformed_garbage_value() -> None:
    """Arbitrary garbage fires."""
    src = "PIP_UPLOADED_PRIOR_TO=hello\n"
    assert _hits("pypi-quarantine-malformed-iso8601", src)


def test_quarantine_correct_p14d_does_not_fire() -> None:
    """`PIP_UPLOADED_PRIOR_TO=P14D` is the correct form → no hit."""
    src = "PIP_UPLOADED_PRIOR_TO=P14D\n"
    assert not _hits("pypi-quarantine-malformed-iso8601", src)


def test_quarantine_correct_p30d_in_quotes_does_not_fire() -> None:
    """`PIP_UPLOADED_PRIOR_TO=\"P30D\"` in quotes is correct → no hit."""
    src = 'PIP_UPLOADED_PRIOR_TO="P30D"\n'
    assert not _hits("pypi-quarantine-malformed-iso8601", src)


# ---------- Rule 4 : pypi-sdist-build-allowed ----------------------------


def test_sdist_build_no_binary_all_in_requirements() -> None:
    """`pip install --no-binary :all:` is the canonical re-allow."""
    src = "pip install --no-binary :all: -r requirements.txt\n"
    assert _hits("pypi-sdist-build-allowed", src)


def test_sdist_build_uv_no_build_false() -> None:
    """Env `UV_NO_BUILD=false` re-enables source builds."""
    src = "export UV_NO_BUILD=false\n"
    assert _hits("pypi-sdist-build-allowed", src)


def test_sdist_build_pip_only_binary_subset() -> None:
    """`PIP_ONLY_BINARY=numpy` (subset) defeats the global protection."""
    src = "PIP_ONLY_BINARY=numpy\n"
    assert _hits("pypi-sdist-build-allowed", src)


def test_sdist_build_pip_only_binary_all_does_not_fire() -> None:
    """`PIP_ONLY_BINARY=:all:` is the SAFE value → no hit."""
    src = "PIP_ONLY_BINARY=:all:\n"
    assert not _hits("pypi-sdist-build-allowed", src)


# ---------- Rule 5 : pypi-requirements-no-hashes -------------------------


def test_no_hash_pin_in_requirements_fires() -> None:
    """`pkg==version` without `--hash=` continuation fires."""
    src = (
        "requests==2.31.0\n"
        "urllib3==2.0.7\n"
    )
    assert _hits("pypi-requirements-no-hashes", src)


def test_no_hash_pin_with_inline_hash_does_not_fire() -> None:
    """`pkg==v --hash=sha256:abc` inline → no hit."""
    src = "requests==2.31.0 --hash=sha256:abcdef1234567890\n"
    assert not _hits("pypi-requirements-no-hashes", src)


def test_no_hash_pin_with_require_hashes_file_guard_suppresses() -> None:
    """File-level `--require-hashes` suppresses every per-line hit."""
    src = (
        "--require-hashes\n"
        "requests==2.31.0 \\\n"
        "    --hash=sha256:abcdef1234567890\n"
    )
    assert not _hits("pypi-requirements-no-hashes", src)


def test_no_hash_pin_with_backslash_continuation_does_not_fire() -> None:
    """`pkg==v \\` then `--hash=sha256:` next line → continuation suppresses."""
    src = (
        "requests==2.31.0 \\\n"
        "    --hash=sha256:abcdef1234567890\n"
    )
    assert not _hits("pypi-requirements-no-hashes", src)


# ---------- Rule 6 : pypi-publish-long-lived-token -----------------------


def test_long_lived_token_twine_password_env() -> None:
    """`TWINE_PASSWORD: ...` workflow env fires."""
    src = (
        "env:\n"
        "  TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}\n"
    )
    assert _hits("pypi-publish-long-lived-token", src)


def test_long_lived_token_twine_username_token() -> None:
    """`TWINE_USERNAME=__token__` is the API-token-mode marker."""
    src = "TWINE_USERNAME=__token__\n"
    assert _hits("pypi-publish-long-lived-token", src)


def test_long_lived_token_action_with_password() -> None:
    """`password: ${{ secrets.PYPI_API_TOKEN }}` step input fires."""
    src = (
        "- uses: pypa/gh-action-pypi-publish@v1.12\n"
        "  with:\n"
        "    password: ${{ secrets.PYPI_API_TOKEN }}\n"
    )
    assert _hits("pypi-publish-long-lived-token", src)


def test_long_lived_token_pypirc_password() -> None:
    """`.pypirc` `password = pypi-...` literal token fires."""
    src = (
        "[pypi]\n"
        "username = __token__\n"
        f"password = {_PYPI}AgEIcHlwaS5vcmcCJDhmYjY1\n"
    )
    assert _hits("pypi-publish-long-lived-token", src)


# ---------- Rule 7 : pypi-publish-action-tag-not-sha-pinned --------------


def test_publish_action_v_tag_fires() -> None:
    """`@v1.12` is a mutable tag → finding."""
    src = "  - uses: pypa/gh-action-pypi-publish@v1.12\n"
    assert _hits("pypi-publish-action-tag-not-sha-pinned", src)


def test_publish_action_release_branch_fires() -> None:
    """`@release/v1` (non-40-hex) fires."""
    src = "uses: pypa/gh-action-pypi-publish@release/v1\n"
    assert _hits("pypi-publish-action-tag-not-sha-pinned", src)


def test_publish_action_40_char_sha_does_not_fire() -> None:
    """A 40-char hex SHA → no hit."""
    src = (
        "uses: pypa/gh-action-pypi-publish@"
        "a1b2c3d4e5f6789012345678901234567890abcd\n"
    )
    assert not _hits("pypi-publish-action-tag-not-sha-pinned", src)


# ---------- Rule 8 : pypi-publish-missing-attestations -------------------


def test_publish_missing_attestations_fires_without_guard() -> None:
    """A publish step without `attestations:` anywhere fires."""
    src = (
        "- uses: pypa/gh-action-pypi-publish@v1.12\n"
        "  with:\n"
        "    repository-url: https://upload.pypi.org/legacy/\n"
    )
    assert _hits("pypi-publish-missing-attestations", src)


def test_publish_with_attestations_true_suppresses() -> None:
    """`attestations: true` in file → suppress every hit."""
    src = (
        "- uses: pypa/gh-action-pypi-publish@v1.12\n"
        "  with:\n"
        "    attestations: true\n"
    )
    assert not _hits("pypi-publish-missing-attestations", src)


# ---------- Rule 9 : pypi-install-from-arbitrary-url ---------------------


def test_arbitrary_url_install_tarball() -> None:
    """`pip install https://example.com/foo.tar.gz` fires."""
    src = "pip install https://example.com/foo.tar.gz\n"
    assert _hits("pypi-install-from-arbitrary-url", src)


def test_arbitrary_url_install_pep508_direct_ref() -> None:
    """PEP 508 `pkg @ https://example.com/foo.whl` fires."""
    src = "mypkg @ https://my-internal.example.com/dist/foo-1.0-py3-none-any.whl\n"
    assert _hits("pypi-install-from-arbitrary-url", src)


def test_arbitrary_url_install_bare_url_line_in_requirements() -> None:
    """Bare `https://...whl` URL on a requirements.txt line fires."""
    src = "https://example.com/wheelhouse/some-package-1.0.0.whl\n"
    assert _hits("pypi-install-from-arbitrary-url", src)


# ---------- Rule 10 : pypi-install-from-mutable-git-ref ------------------


def test_mutable_git_ref_no_ref_fires() -> None:
    """`git+https://github.com/org/repo.git` (no ref) fires."""
    src = "pip install git+https://github.com/org/repo.git\n"
    assert _hits("pypi-install-from-mutable-git-ref", src)


def test_mutable_git_ref_branch_fires() -> None:
    """`git+https://...@main` (branch ref) fires."""
    src = "mypkg @ git+https://github.com/org/repo.git@main\n"
    assert _hits("pypi-install-from-mutable-git-ref", src)


def test_mutable_git_ref_40_char_sha_does_not_fire() -> None:
    """A 40-char SHA ref → no hit."""
    src = (
        "mypkg @ git+https://github.com/org/repo.git@"
        "a1b2c3d4e5f6789012345678901234567890abcd\n"
    )
    assert not _hits("pypi-install-from-mutable-git-ref", src)


def test_mutable_git_ref_poetry_branch_form() -> None:
    """`branch = \"main\"` inside a Poetry source block fires."""
    src = 'branch = "main"\n'
    assert _hits("pypi-install-from-mutable-git-ref", src)


# ---------- Rule 11 : pypi-trusted-host-tls-bypass -----------------------


def test_trusted_host_cli_flag_fires() -> None:
    """`pip install --trusted-host my-private.example.com` fires."""
    src = "pip install --trusted-host my-private.example.com -r requirements.txt\n"
    assert _hits("pypi-trusted-host-tls-bypass", src)


def test_trusted_host_config_line_fires() -> None:
    """`trusted-host = my-private.example.com` in pip.conf fires."""
    src = (
        "[global]\n"
        "trusted-host = my-private.example.com\n"
    )
    assert _hits("pypi-trusted-host-tls-bypass", src)


def test_trusted_host_env_var_fires() -> None:
    """`PIP_TRUSTED_HOST=my-private.example.com` env fires."""
    src = "PIP_TRUSTED_HOST=my-private.example.com\n"
    assert _hits("pypi-trusted-host-tls-bypass", src)


def test_trusted_host_conda_ssl_verify_false() -> None:
    """`ssl_verify: false` in condarc fires."""
    src = "ssl_verify: false\n"
    assert _hits("pypi-trusted-host-tls-bypass", src)


# ---------- Rule 12 : pypi-build-system-unpinned -------------------------


def test_build_system_unpinned_setuptools() -> None:
    """`requires = [\"setuptools\"]` unpinned fires."""
    src = (
        "[build-system]\n"
        'requires = ["setuptools", "wheel"]\n'
        'build-backend = "setuptools.build_meta"\n'
    )
    assert _hits("pypi-build-system-unpinned", src)


def test_build_system_unpinned_setuptools_geq() -> None:
    """`requires = [\"setuptools>=68\"]` (>= not ==) fires."""
    src = (
        "[build-system]\n"
        'requires = ["setuptools>=68"]\n'
    )
    assert _hits("pypi-build-system-unpinned", src)


def test_build_system_pinned_does_not_fire() -> None:
    """`requires = [\"setuptools==75.0.0\"]` is pinned → no hit."""
    src = (
        "[build-system]\n"
        'requires = ["setuptools==75.0.0", "wheel==0.44.0"]\n'
    )
    assert not _hits("pypi-build-system-unpinned", src)


def test_build_system_outside_section_does_not_fire() -> None:
    """A `\"setuptools\"` token in a [project] section without a "
    "[build-system] section → no hit."""
    src = (
        "[project]\n"
        'dependencies = ["setuptools", "wheel"]\n'
    )
    assert not _hits("pypi-build-system-unpinned", src)


# ---------- Rule 13 : pypi-legacy-setup-py-install -----------------------


def test_legacy_setup_py_install_fires() -> None:
    """`python setup.py install` fires."""
    src = "python setup.py install\n"
    assert _hits("pypi-legacy-setup-py-install", src)


def test_legacy_setup_py_develop_fires() -> None:
    """`python setup.py develop` fires."""
    src = "python setup.py develop\n"
    assert _hits("pypi-legacy-setup-py-install", src)


def test_legacy_easy_install_fires() -> None:
    """`easy_install pkg` fires."""
    src = "easy_install requests\n"
    assert _hits("pypi-legacy-setup-py-install", src)


def test_modern_pip_install_does_not_fire() -> None:
    """`pip install .` (modern equivalent) → no hit."""
    src = "pip install .\n"
    assert not _hits("pypi-legacy-setup-py-install", src)


# ---------- Rule 14 : pypi-conda-channel-priority-weak -------------------


def test_conda_channel_priority_flexible_fires() -> None:
    """`channel_priority: flexible` fires."""
    src = "channel_priority: flexible\n"
    assert _hits("pypi-conda-channel-priority-weak", src)


def test_conda_channel_priority_disabled_fires() -> None:
    """`channel_priority: disabled` fires."""
    src = "channel_priority: disabled\n"
    assert _hits("pypi-conda-channel-priority-weak", src)


def test_conda_add_personal_channel_fires() -> None:
    """`conda config --add channels conda.anaconda.org/<user>` fires."""
    src = "conda config --add channels https://conda.anaconda.org/some-user/\n"
    assert _hits("pypi-conda-channel-priority-weak", src)


def test_conda_channel_priority_strict_does_not_fire() -> None:
    """`channel_priority: strict` is the SAFE value → no hit."""
    src = "channel_priority: strict\n"
    assert not _hits("pypi-conda-channel-priority-weak", src)


# ---------- Rule 15 : pypi-no-build-isolation ----------------------------


def test_no_build_isolation_pip_fires() -> None:
    """`pip install --no-build-isolation` fires."""
    src = "pip install --no-build-isolation .\n"
    assert _hits("pypi-no-build-isolation", src)


def test_no_build_isolation_uv_fires() -> None:
    """`uv pip install --no-build-isolation` fires."""
    src = "uv pip install --no-build-isolation foo\n"
    assert _hits("pypi-no-build-isolation", src)


def test_no_build_isolation_pyproject_fires() -> None:
    """`no-build-isolation = true` in pyproject fires."""
    src = (
        "[tool.uv]\n"
        "no-build-isolation = true\n"
    )
    assert _hits("pypi-no-build-isolation", src)


def test_pip_install_without_no_build_isolation_does_not_fire() -> None:
    """Plain `pip install` (default isolation) → no hit."""
    src = "pip install .\n"
    assert not _hits("pypi-no-build-isolation", src)


# ---------- Rule 16 : pypi-no-pip-audit-gate -----------------------------


def test_no_pip_audit_gate_install_without_audit_fires() -> None:
    """`pip install` without follow-up audit → finding."""
    src = (
        "steps:\n"
        "  - run: pip install -r requirements.txt\n"
        "  - run: python -m unittest\n"
    )
    assert _hits("pypi-no-pip-audit-gate", src)


def test_no_pip_audit_gate_with_pip_audit_step_suppresses() -> None:
    """File contains `pip-audit` step → suppress every install hit."""
    src = (
        "steps:\n"
        "  - run: pip install -r requirements.txt\n"
        "  - run: pip-audit\n"
    )
    assert not _hits("pypi-no-pip-audit-gate", src)


def test_no_pip_audit_gate_with_osv_scanner_suppresses() -> None:
    """File contains `osv-scanner` step → suppress every install hit."""
    src = (
        "steps:\n"
        "  - run: uv sync --frozen\n"
        "  - run: osv-scanner scan source -L uv.lock\n"
    )
    assert not _hits("pypi-no-pip-audit-gate", src)


# ---------- Rule 17 : pypi-known-typosquat-ioc ---------------------------


def test_ioc_torchtriton_2_0_0_fires() -> None:
    """`torchtriton==2.0.0` is in the curated IOC list."""
    src = "torchtriton==2.0.0\n"
    assert _hits("pypi-known-typosquat-ioc", src)


def test_ioc_ultralytics_8_3_41_fires() -> None:
    """`ultralytics==8.3.41` is in the curated IOC list."""
    src = "ultralytics==8.3.41\n"
    assert _hits("pypi-known-typosquat-ioc", src)


def test_ioc_litellm_1_82_7_fires() -> None:
    """`litellm==1.82.7` is in the curated IOC list."""
    src = "litellm==1.82.7\n"
    assert _hits("pypi-known-typosquat-ioc", src)


def test_ioc_durabletask_1_4_2_fires() -> None:
    """`durabletask==1.4.2` is in the curated IOC list."""
    src = "durabletask==1.4.2\n"
    assert _hits("pypi-known-typosquat-ioc", src)


def test_ioc_colourama_any_version_fires() -> None:
    """`colourama==<any>` is a typosquat (version_pattern is None)."""
    src = "colourama==0.4.6\n"
    assert _hits("pypi-known-typosquat-ioc", src)


def test_ioc_safe_version_does_not_fire() -> None:
    """`ultralytics==8.3.40` (the last clean version) → no hit."""
    src = "ultralytics==8.3.40\n"
    assert not _hits("pypi-known-typosquat-ioc", src)


def test_ioc_unrelated_package_does_not_fire() -> None:
    """`requests==2.31.0` is benign → no hit."""
    src = "requests==2.31.0\n"
    assert not _hits("pypi-known-typosquat-ioc", src)


def test_ioc_normalises_underscore_to_hyphen() -> None:
    """PyPI canonical name interchange: `pytorch_lightning==2.6.2` fires."""
    src = "pytorch_lightning==2.6.2\n"
    assert _hits("pypi-known-typosquat-ioc", src)


# ---------- Rule 18 : pypi-audit-log-missing-marker ----------------------


def test_audit_log_gitignored_fires() -> None:
    """`.gitignore` entry for `supply-chain-audit-log.md` fires."""
    src = "supply-chain-audit-log.md\n"
    assert _hits("pypi-audit-log-missing-marker", src)


def test_audit_log_gitignored_with_slash_fires() -> None:
    """`/supply-chain-audit-log.md` (anchored form) fires."""
    src = "/supply-chain-audit-log.md\n"
    assert _hits("pypi-audit-log-missing-marker", src)


def test_audit_log_unrelated_gitignore_line_does_not_fire() -> None:
    """`reports/` gitignore is unrelated → no hit."""
    src = "reports/\nnode_modules/\n*.pyc\n"
    assert not _hits("pypi-audit-log-missing-marker", src)


# ---------- Integration: multi-rule scan ---------------------------------


def test_scan_finds_multiple_rule_kinds() -> None:
    """A single text with several violations → multiple findings."""
    src = (
        "# requirements.txt with stacked sins\n"
        "--extra-index-url https://my-private.example.com/simple\n"
        "ultralytics==8.3.41\n"
        "python setup.py install\n"
    )
    hits = psp.scan_text(src)
    rule_ids = {f.rule_id for f in hits}
    assert "pypi-dep-confusion-extra-index-url" in rule_ids
    assert "pypi-known-typosquat-ioc" in rule_ids
    assert "pypi-legacy-setup-py-install" in rule_ids


def test_findings_sorted_by_line_then_column() -> None:
    """Findings are ordered (line, column, rule_id)."""
    src = (
        "python setup.py install\n"
        "torchtriton==2.0.0\n"
    )
    hits = psp.scan_text(src)
    assert len(hits) >= 2
    for a, b in zip(hits, hits[1:]):
        assert (a.line, a.column, a.rule_id) <= (b.line, b.column, b.rule_id)


def test_findings_are_deduped_by_rule_line_col() -> None:
    """Same (rule_id, line, column) appears only once."""
    src = (
        # Single line that could match the dep-confusion env-pattern
        # AND nothing else
        'export PIP_EXTRA_INDEX_URL="https://internal/simple"\n'
    )
    hits = psp.scan_text(src)
    keys = {(f.rule_id, f.line, f.column) for f in hits}
    assert len(keys) == len(hits)


def test_matched_text_truncated_at_200() -> None:
    """Findings clip matched_text at 200 chars to avoid log bloat."""
    # The dep-confusion env-pattern starts at PIP_EXTRA_INDEX_URL=, and
    # the lazy quantifier doesn't apply — we just need a long-enough
    # match to trigger truncation.
    long_url = "https://" + "abcde" * 80 + "/simple"
    src = f"PIP_EXTRA_INDEX_URL={long_url}\n"
    hits = psp.scan_text(src)
    # Whether truncation applies depends on the specific pattern's
    # span; the test guarantees the field is at most 201 characters
    # (200 + ellipsis) for every finding.
    for f in hits:
        assert len(f.matched_text) <= 201
