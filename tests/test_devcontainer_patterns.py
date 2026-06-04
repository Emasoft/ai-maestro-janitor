"""Tests for scripts/lib/devcontainer_patterns.py.

Pattern-coverage tests for the Wave-31 distill-round-17 angle
catalogue (7 devcontainer/Codespaces specific anti-patterns). Each rule
has at least two tests: one positive (canary that must fire) and one
negative (carve-out or benign variant that must not fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import devcontainer_patterns as dcp  # type: ignore[import-not-found]  # noqa: E402

sys.path.insert(0, str(_PROJECT_ROOT / "tests"))
from _fake_secrets import b62, secret  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(dcp.RULES, tuple)
    rule_ids = {r.id for r in dcp.RULES}
    expected = {
        "dvc-runargs-privileged",
        "dvc-mounts-docker-sock",
        "dvc-forwardports-ssh",
        "dvc-containerenv-literal-token",
        "dvc-image-unpinned-mutable-tag",
        "dvc-vscode-extension-wildcard-activation",
        "dvc-codespaces-secret-broad-scope-env",
    }
    assert expected == rule_ids
    assert len(dcp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in dcp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = dcp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert dcp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — privileged runArgs
        '{"runArgs": ["--privileged"]}\n'
        # Line 2 — docker.sock mount
        '{"mounts": ["source=/var/run/docker.sock,target=/var/run/docker.sock,type=bind"]}\n'
    )
    findings = dcp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[dcp.Finding]:
    return [f for f in dcp.scan_text(text) if f.rule_id == rule_id]


# ---------- D1 : dvc-runargs-privileged ----------------------------------


def test_d1_runargs_privileged_flags() -> None:
    """runArgs containing --privileged → CRITICAL hit."""
    src = (
        '{\n'
        '  "name": "My Dev Container",\n'
        '  "image": "ubuntu:22.04",\n'
        '  "runArgs": ["--privileged", "--hostname=devbox"]\n'
        '}\n'
    )
    hits = _hits("dvc-runargs-privileged", src)
    assert hits
    assert hits[0].severity == "CRITICAL"
    assert hits[0].owasp_asi == "ASI-05"


def test_d1_runargs_privileged_single_element_flags() -> None:
    """runArgs with only --privileged (no other args) → CRITICAL hit."""
    src = '{"runArgs": ["--privileged"]}\n'
    assert _hits("dvc-runargs-privileged", src)


def test_d1_runargs_no_privileged_silent() -> None:
    """runArgs without --privileged → no hit."""
    src = '{"runArgs": ["--hostname=devbox", "--memory=4g"]}\n'
    assert not _hits("dvc-runargs-privileged", src)


def test_d1_runargs_absent_silent() -> None:
    """devcontainer with no runArgs key → no hit."""
    src = '{"name": "Safe Container", "image": "ubuntu:22.04"}\n'
    assert not _hits("dvc-runargs-privileged", src)


# ---------- D2 : dvc-mounts-docker-sock ----------------------------------


def test_d2_mounts_docker_sock_flags() -> None:
    """mounts containing /var/run/docker.sock → CRITICAL hit."""
    src = (
        '{\n'
        '  "name": "CI Dev Environment",\n'
        '  "image": "ghcr.io/myorg/dev:latest",\n'
        '  "mounts": [\n'
        '    "source=/var/run/docker.sock,target=/var/run/docker.sock,type=bind"\n'
        '  ]\n'
        '}\n'
    )
    hits = _hits("dvc-mounts-docker-sock", src)
    assert hits
    assert hits[0].severity == "CRITICAL"
    assert hits[0].owasp_asi == "ASI-02"


def test_d2_mounts_docker_sock_short_form_flags() -> None:
    """mounts with short source=..docker.sock path → hit."""
    src = '{"mounts": ["source=/var/run/docker.sock,target=/sock"]}\n'
    assert _hits("dvc-mounts-docker-sock", src)


def test_d2_mounts_no_docker_sock_silent() -> None:
    """mounts without docker.sock → no hit."""
    src = '{"mounts": ["source=/home/user/.ssh,target=/root/.ssh,type=bind"]}\n'
    assert not _hits("dvc-mounts-docker-sock", src)


def test_d2_mounts_absent_silent() -> None:
    """devcontainer with no mounts key → no hit."""
    src = '{"name": "Backend Dev", "image": "ubuntu:22.04"}\n'
    assert not _hits("dvc-mounts-docker-sock", src)


# ---------- D3 : dvc-forwardports-ssh ------------------------------------


def test_d3_forwardports_ssh_integer_22_flags() -> None:
    """forwardPorts containing integer 22 → HIGH hit."""
    src = (
        '{\n'
        '  "name": "Backend Dev",\n'
        '  "image": "mcr.microsoft.com/devcontainers/base:ubuntu",\n'
        '  "forwardPorts": [22, 8080, 5432]\n'
        '}\n'
    )
    hits = _hits("dvc-forwardports-ssh", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-05"


def test_d3_forwardports_ssh_only_port_22_flags() -> None:
    """forwardPorts with only 22 → hit."""
    src = '{"forwardPorts": [22]}\n'
    assert _hits("dvc-forwardports-ssh", src)


def test_d3_forwardports_no_ssh_silent() -> None:
    """forwardPorts without port 22 → no hit."""
    src = '{"forwardPorts": [3000, 8080, 5432]}\n'
    assert not _hits("dvc-forwardports-ssh", src)


def test_d3_forwardports_2200_not_flagged() -> None:
    """Port 2200 must not be confused with 22 (word-boundary anchors)."""
    src = '{"forwardPorts": [2200, 8022]}\n'
    assert not _hits("dvc-forwardports-ssh", src)


# ---------- D4 : dvc-containerenv-literal-token --------------------------


def test_d4_containerenv_github_token_literal_flags() -> None:
    """containerEnv GITHUB_TOKEN with 40-char literal → HIGH hit."""
    src = (
        '{\n'
        '  "name": "CI Dev",\n'
        '  "containerEnv": {\n'
        f'    "GITHUB_TOKEN": "{secret("ghp" + "_", "dvc-d4-github-token", 40)}"\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("dvc-containerenv-literal-token", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-02"


def test_d4_containerenv_npm_token_literal_flags() -> None:
    """containerEnv NPM_TOKEN with long literal → hit."""
    src = (
        f'{{"containerEnv": {{"NPM_TOKEN": "{secret("npm_", "devc-npm", 32)}"}}}}\n'
    )
    assert _hits("dvc-containerenv-literal-token", src)


def test_d4_containerenv_aws_secret_literal_flags() -> None:
    """containerEnv AWS_SECRET_ACCESS_KEY with literal → hit."""
    src = (
        '{"containerEnv": {"AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY"}}\n'
    )
    assert _hits("dvc-containerenv-literal-token", src)


def test_d4_containerenv_placeholder_silent() -> None:
    """Short or placeholder-like values must not trigger (FP suppression)."""
    src = (
        '{"containerEnv": {"GITHUB_TOKEN": "CHANGE_ME"}}\n'
    )
    # "CHANGE_ME" is only 9 chars — below the 20-char minimum
    assert not _hits("dvc-containerenv-literal-token", src)


def test_d4_containerenv_unrelated_key_silent() -> None:
    """containerEnv with a non-secret key name → no hit."""
    src = (
        '{"containerEnv": {"HOME": "/root", "EDITOR": "vim"}}\n'
    )
    assert not _hits("dvc-containerenv-literal-token", src)


# ---------- D5 : dvc-image-unpinned-mutable-tag --------------------------


def test_d5_image_latest_tag_flags() -> None:
    """image: with :latest tag → HIGH hit."""
    src = (
        '{\n'
        '  "name": "Node.js Dev",\n'
        '  "image": "ghcr.io/myorg/devcontainer-node:latest",\n'
        '  "forwardPorts": [3000]\n'
        '}\n'
    )
    hits = _hits("dvc-image-unpinned-mutable-tag", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-06"


def test_d5_image_edge_tag_flags() -> None:
    """image: with :edge mutable tag → hit."""
    src = '{"image": "ghcr.io/myorg/base:edge"}\n'
    assert _hits("dvc-image-unpinned-mutable-tag", src)


def test_d5_image_dev_tag_flags() -> None:
    """image: with :dev mutable tag → hit."""
    src = '{"image": "mcr.microsoft.com/devcontainers/python:dev"}\n'
    assert _hits("dvc-image-unpinned-mutable-tag", src)


def test_d5_image_main_tag_flags() -> None:
    """image: with :main mutable tag → hit."""
    src = '{"image": "ghcr.io/myorg/ci:main"}\n'
    assert _hits("dvc-image-unpinned-mutable-tag", src)


def test_d5_image_pinned_version_silent() -> None:
    """image: with a concrete semver tag → no hit."""
    src = '{"image": "mcr.microsoft.com/devcontainers/python:3.12-bookworm"}\n'
    assert not _hits("dvc-image-unpinned-mutable-tag", src)


def test_d5_image_no_image_key_silent() -> None:
    """devcontainer without image key → no hit."""
    src = '{"name": "Build Tool", "build": {"dockerfile": "Dockerfile"}}\n'
    assert not _hits("dvc-image-unpinned-mutable-tag", src)


# ---------- D6 : dvc-vscode-extension-wildcard-activation ----------------


def test_d6_extension_short_publisher_one_char_flags() -> None:
    """Extension with 1-char publisher namespace → MEDIUM hit."""
    src = (
        '{\n'
        '  "customizations": {\n'
        '    "vscode": {\n'
        '      "extensions": ["x.code-runner", "ms-python.python"]\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("dvc-vscode-extension-wildcard-activation", src)
    assert hits
    assert hits[0].severity == "MEDIUM"
    assert hits[0].owasp_asi == "ASI-08"


def test_d6_extension_short_publisher_two_char_flags() -> None:
    """Extension with 2-char publisher namespace → hit."""
    src = (
        '{"customizations": {"vscode": {"extensions": ["ab.super-helper"]}}}\n'
    )
    assert _hits("dvc-vscode-extension-wildcard-activation", src)


def test_d6_extension_normal_publisher_silent() -> None:
    """Extensions from reputable long-name publishers → no hit."""
    src = (
        '{\n'
        '  "customizations": {\n'
        '    "vscode": {\n'
        '      "extensions": [\n'
        '        "ms-python.python",\n'
        '        "dbaeumer.vscode-eslint",\n'
        '        "eamodio.gitlens"\n'
        '      ]\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    assert not _hits("dvc-vscode-extension-wildcard-activation", src)


def test_d6_extensions_absent_silent() -> None:
    """devcontainer without extensions key → no hit."""
    src = '{"name": "Minimal Dev", "image": "ubuntu:22.04"}\n'
    assert not _hits("dvc-vscode-extension-wildcard-activation", src)


# ---------- D7 : dvc-codespaces-secret-broad-scope-env -------------------


def test_d7_containerenv_github_token_broad_scope_flags() -> None:
    """containerEnv with GITHUB_TOKEN key (any value) → HIGH hit."""
    src = (
        '{\n'
        '  "name": "Org Dev Environment",\n'
        '  "containerEnv": {\n'
        '    "GITHUB_TOKEN": "${localEnv:GH_ADMIN_PAT}"\n'
        '  }\n'
        '}\n'
    )
    hits = _hits("dvc-codespaces-secret-broad-scope-env", src)
    assert hits
    assert hits[0].severity == "HIGH"
    assert hits[0].owasp_asi == "ASI-02"


def test_d7_remoteenv_org_token_flags() -> None:
    """remoteEnv with ORG_TOKEN key → hit."""
    src = (
        '{"remoteEnv": {"ORG_TOKEN": "${localEnv:ORG_SECRET}"}}\n'
    )
    assert _hits("dvc-codespaces-secret-broad-scope-env", src)


def test_d7_containerenv_admin_token_flags() -> None:
    """containerEnv with ADMIN_TOKEN key → hit."""
    src = (
        f'{{"containerEnv": {{"ADMIN_TOKEN": "{b62("devc-admin", 28)}"}}}}\n'
    )
    assert _hits("dvc-codespaces-secret-broad-scope-env", src)


def test_d7_containerenv_safe_key_silent() -> None:
    """containerEnv with a non-broad-scope key → no hit."""
    src = (
        '{"containerEnv": {"DATABASE_URL": "postgres://localhost/mydb"}}\n'
    )
    assert not _hits("dvc-codespaces-secret-broad-scope-env", src)


def test_d7_containerenv_absent_silent() -> None:
    """devcontainer without containerEnv/remoteEnv → no hit."""
    src = '{"name": "Minimal Dev", "image": "ubuntu:22.04"}\n'
    assert not _hits("dvc-codespaces-secret-broad-scope-env", src)
