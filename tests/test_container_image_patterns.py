"""Tests for scripts/lib/container_image_patterns.py.

Pattern-coverage tests for the Wave-25 distill-round-11 angle
catalogue (11 container image-composition anti-patterns covering
Dockerfile / Containerfile / docker-compose surfaces). Each rule has
two tests — one positive (canary fires) and one negative (carve-out
or context filter suppresses).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import container_image_patterns as cip  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 11 documented rule IDs."""
    assert isinstance(cip.RULES, tuple)
    rule_ids = {r.id for r in cip.RULES}
    expected = {
        "container-from-tag-mutable-label",
        "container-copy-from-external-image-no-digest",
        "container-no-user-directive",
        "container-cmd-shell-form",
        "container-copy-root-no-dockerignore",
        "container-add-remote-url",
        "container-no-healthcheck",
        "container-arg-env-secret-propagation",
        "container-apt-source-check-valid-until-no-signed-by",
        "container-compose-image-mutable-label",
        "container-package-install-no-version-pin",
    }
    assert expected == rule_ids
    assert len(cip.RULES) == 11


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in cip.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "MAJOR", "MINOR"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = cip.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="MAJOR", description="d", owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "MAJOR"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-08"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert cip.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[cip.Finding]:
    return [f for f in cip.scan_text(text) if f.rule_id == rule_id]


# ---------- P1 : container-from-tag-mutable-label ------------------------


def test_p1_from_latest_tag_flags() -> None:
    """FROM nginx:latest → MAJOR hit on mutable-label tag."""
    src = "FROM nginx:latest\nRUN echo hi\nUSER nobody\n"
    hits = _hits("container-from-tag-mutable-label", src)
    assert hits
    assert hits[0].severity == "MAJOR"


def test_p1_from_pinned_version_no_hit() -> None:
    """FROM nginx:1.27.3 → no hit (pinned version-series tag)."""
    src = "FROM nginx:1.27.3\nUSER nobody\n"
    assert not _hits("container-from-tag-mutable-label", src)


# ---------- P2 : container-copy-from-external-image-no-digest ------------


def test_p2_copy_from_external_image_unpinned_flags() -> None:
    """COPY --from=hashicorp/terraform:1.15.2 ... → CRITICAL hit."""
    src = (
        "FROM ubuntu:24.04@sha256:abc\n"
        "COPY --from=hashicorp/terraform:1.15.2 /bin/terraform /usr/local/bin/terraform\n"
        "USER nobody\n"
    )
    hits = _hits("container-copy-from-external-image-no-digest", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p2_copy_from_stage_name_no_hit() -> None:
    """COPY --from=builder /app/binary . → no hit (in-Dockerfile stage)."""
    src = (
        "FROM ubuntu:24.04@sha256:abc AS builder\n"
        "COPY --from=builder /app/binary /usr/local/bin/binary\n"
        "USER nobody\n"
    )
    assert not _hits("container-copy-from-external-image-no-digest", src)


# ---------- P3 : container-no-user-directive -----------------------------


def test_p3_no_user_directive_flags() -> None:
    """Dockerfile with FROM but no USER → MAJOR hit at the FROM line."""
    src = (
        "FROM python:3.12-slim\n"
        "WORKDIR /app\n"
        "COPY . .\n"
        "CMD [\"uvicorn\", \"app.main:app\"]\n"
    )
    hits = _hits("container-no-user-directive", src)
    assert hits
    assert hits[0].severity == "MAJOR"
    assert hits[0].line == 1


def test_p3_with_user_directive_no_hit() -> None:
    """Dockerfile with a USER line → no P3 hit."""
    src = (
        "FROM python:3.12-slim\n"
        "RUN adduser --disabled-password app\n"
        "USER app\n"
        "CMD [\"uvicorn\", \"app.main:app\"]\n"
    )
    assert not _hits("container-no-user-directive", src)


# ---------- P4 : container-cmd-shell-form --------------------------------


def test_p4_cmd_shell_form_flags() -> None:
    """CMD uvicorn app.main:app ... (shell form) → MAJOR hit."""
    src = (
        "FROM python:3.12-slim\n"
        "USER nobody\n"
        "CMD uvicorn app.main:app --host 0.0.0.0 --port 8000\n"
    )
    hits = _hits("container-cmd-shell-form", src)
    assert hits
    assert hits[0].severity == "MAJOR"


def test_p4_cmd_exec_form_no_hit() -> None:
    """CMD [\"uvicorn\", \"app.main:app\"] (exec form) → no hit."""
    src = (
        "FROM python:3.12-slim\n"
        "USER nobody\n"
        "CMD [\"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\"]\n"
    )
    assert not _hits("container-cmd-shell-form", src)


# ---------- P5 : container-copy-root-no-dockerignore ---------------------


def test_p5_copy_dot_to_dot_flags() -> None:
    """COPY . . → MAJOR hit (regex stage; FS check is caller's job)."""
    src = (
        "FROM python:3.12-slim\n"
        "USER nobody\n"
        "WORKDIR /app\n"
        "COPY . .\n"
    )
    hits = _hits("container-copy-root-no-dockerignore", src)
    assert hits
    assert hits[0].severity == "MAJOR"


def test_p5_copy_specific_files_no_hit() -> None:
    """COPY requirements.txt . → no hit (selective copy)."""
    src = (
        "FROM python:3.12-slim\n"
        "USER nobody\n"
        "WORKDIR /app\n"
        "COPY requirements.txt /app/requirements.txt\n"
        "COPY ./src/app /app/src\n"
    )
    assert not _hits("container-copy-root-no-dockerignore", src)


# ---------- P6 : container-add-remote-url --------------------------------


def test_p6_add_remote_url_flags() -> None:
    """ADD https://... → CRITICAL hit (no integrity verification)."""
    src = (
        "FROM ubuntu:24.04\n"
        "USER nobody\n"
        "ADD https://example.com/installer.sh /tmp/installer.sh\n"
    )
    hits = _hits("container-add-remote-url", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p6_add_remote_url_with_checksum_no_hit() -> None:
    """ADD --checksum=sha256:abc https://... → no hit (BuildKit safe form)."""
    src = (
        "FROM ubuntu:24.04\n"
        "USER nobody\n"
        "ADD --checksum=sha256:abc123def456 https://example.com/installer.sh /tmp/installer.sh\n"
    )
    assert not _hits("container-add-remote-url", src)


# ---------- P7 : container-no-healthcheck --------------------------------


def test_p7_expose_without_healthcheck_flags() -> None:
    """EXPOSE 8000 without HEALTHCHECK → MINOR hit."""
    src = (
        "FROM python:3.12-slim\n"
        "USER nobody\n"
        "EXPOSE 8000\n"
        "CMD [\"uvicorn\", \"app:app\"]\n"
    )
    hits = _hits("container-no-healthcheck", src)
    assert hits
    assert hits[0].severity == "MINOR"


def test_p7_expose_with_healthcheck_no_hit() -> None:
    """EXPOSE + HEALTHCHECK CMD → no hit."""
    src = (
        "FROM python:3.12-slim\n"
        "USER nobody\n"
        "EXPOSE 8000\n"
        "HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8000/health || exit 1\n"
        "CMD [\"uvicorn\", \"app:app\"]\n"
    )
    assert not _hits("container-no-healthcheck", src)


# ---------- P8 : container-arg-env-secret-propagation --------------------


def test_p8_arg_env_propagation_flags() -> None:
    """ARG SECRET_TOKEN then ENV SECRET_TOKEN=$SECRET_TOKEN → CRITICAL hit."""
    src = (
        "FROM node:20-alpine\n"
        "USER nobody\n"
        "ARG SECRET_TOKEN\n"
        "ENV SECRET_TOKEN=$SECRET_TOKEN\n"
        "CMD [\"node\", \"app.js\"]\n"
    )
    hits = _hits("container-arg-env-secret-propagation", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_p8_public_prefix_no_hit() -> None:
    """ARG NEXT_PUBLIC_API_URL + ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL → no hit."""
    src = (
        "FROM node:20-alpine\n"
        "USER nobody\n"
        "ARG NEXT_PUBLIC_API_URL\n"
        "ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL\n"
        "CMD [\"node\", \"server.js\"]\n"
    )
    assert not _hits("container-arg-env-secret-propagation", src)


# ---------- P9 : container-apt-source-check-valid-until-no-signed-by -----


def test_p9_apt_deb_check_valid_until_no_signed_by_flags() -> None:
    """deb [check-valid-until=no] without signed-by → MAJOR hit."""
    src = (
        "FROM debian:bookworm\n"
        "USER nobody\n"
        "RUN echo 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20240501 trixie main' "
        ">> /etc/apt/sources.list\n"
    )
    hits = _hits("container-apt-source-check-valid-until-no-signed-by", src)
    assert hits
    assert hits[0].severity == "MAJOR"


def test_p9_apt_deb_with_signed_by_no_hit() -> None:
    """deb [check-valid-until=no signed-by=/usr/share/keyrings/k.gpg] → no hit."""
    src = (
        "FROM debian:bookworm\n"
        "USER nobody\n"
        "RUN echo 'deb [check-valid-until=no signed-by=/usr/share/keyrings/debian.gpg] "
        "http://snapshot.debian.org/archive/debian/20240501 trixie main' >> /etc/apt/sources.list\n"
    )
    assert not _hits("container-apt-source-check-valid-until-no-signed-by", src)


# ---------- P10 : container-compose-image-mutable-label ------------------


def test_p10_compose_image_latest_flags() -> None:
    """compose `image: prom/prometheus:latest` → MAJOR hit."""
    src = (
        "services:\n"
        "  prometheus:\n"
        "    image: prom/prometheus:latest\n"
        "    ports:\n"
        "      - 9090:9090\n"
    )
    hits = _hits("container-compose-image-mutable-label", src)
    assert hits
    assert hits[0].severity == "MAJOR"


def test_p10_helm_values_yaml_image_key_no_hit() -> None:
    """A Helm-style values.yaml `image:` key with no compose marker → no hit."""
    src = (
        "# Helm values.yaml — not a compose file\n"
        "replicaCount: 3\n"
        "image: nginx:latest\n"
        "ingress:\n"
        "  enabled: true\n"
    )
    assert not _hits("container-compose-image-mutable-label", src)


# ---------- P11 : container-package-install-no-version-pin ---------------


def test_p11_apk_add_unpinned_flags() -> None:
    """RUN apk add --no-cache gitleaks → MAJOR hit (no version pin)."""
    src = (
        "FROM alpine:3.20\n"
        "USER nobody\n"
        "RUN apk add --no-cache gitleaks\n"
    )
    hits = _hits("container-package-install-no-version-pin", src)
    assert hits
    assert hits[0].severity == "MAJOR"


def test_p11_apk_add_pinned_no_hit() -> None:
    """RUN apk add --no-cache gitleaks=8.18.4-r0 → no hit (version pin present)."""
    src = (
        "FROM alpine:3.20\n"
        "USER nobody\n"
        "RUN apk add --no-cache gitleaks=8.18.4-r0\n"
    )
    assert not _hits("container-package-install-no-version-pin", src)
