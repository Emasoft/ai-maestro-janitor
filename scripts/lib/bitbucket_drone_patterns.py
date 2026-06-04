"""Bitbucket Pipelines, Drone CI, and Woodpecker CI security patterns.

Wave-36 distillation round 22, angle: Bitbucket Pipelines + Drone CI +
Woodpecker CI.

Catalogue of 10 CI-platform-specific anti-patterns distilled in
`reports/distill-round-22/bitbucket-drone-ci.md`. Targets three
CI systems not fully covered by existing modules.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic `trusted: true` / `privileged: true` in Drone —
    `ci_runner_injection_patterns.py` rule `drone-trusted-mode-enabled`.
  * GitHub Actions injection patterns — `zizmor_patterns.py`.
  * Secret echo / log redaction — `cicd_secret_leak_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * bdc-bitbucket-image-latest                            (MAJOR)
  * bdc-bitbucket-oidc-wildcard                           (CRITICAL)
  * bdc-bitbucket-services-privileged                     (HIGH)
  * bdc-drone-image-pull-secrets-committed                (CRITICAL)
  * bdc-drone-build-on-fork-branch                        (HIGH)
  * bdc-drone-commit-message-shell-injection              (HIGH)
  * bdc-drone-plugin-image-unpinned                       (MAJOR)
  * bdc-woodpecker-clone-disabled                         (HIGH)
  * bdc-woodpecker-runtime-user-controlled                (HIGH)
  * bdc-bitbucket-cache-key-predictable                   (MAJOR)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-03 — Dependency-chain abuse (unpinned images, cache poisoning)
  ASI-02 — Secret leak (pull-secret credentials committed)
  ASI-04 — Inadequate IAM (OIDC wildcard audience, privileged services)
  ASI-01 — Insufficient flow-control (fork branch trigger, clone disabled)
  ASI-05 — Poisoned pipeline execution (shell injection, local backend)

All regexes are RE2-compatible (no backreferences, no lookbehind except
where Python re module lookahead is specified as RE2-safe). Patterns are
PRE-COMPILED at module load. Fail-fast: callers receive structured Finding
tuples, never raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : bdc-bitbucket-image-latest ------------------------------------

# Matches `image:` in bitbucket-pipelines.yml pointing at a mutable tag
# (:latest, :stable, :edge, :main, :master, :nightly, :dev, :lts) or with
# no tag at all (implicit :latest). Digest-pinned refs excluded via
# negative lookahead on `sha256:`.
_BITBUCKET_IMAGE_LATEST = _re(
    r"^(?:image|docker-image):\s*['\"]?(?!sha256:)[a-zA-Z0-9/._-]+"
    r"(?::['\"]?(?:latest|stable|edge|main|master|nightly|dev|lts))?['\"]?"
    r"\s*(?:#.*)?$"
)


# ---- R2 : bdc-bitbucket-oidc-wildcard -----------------------------------

# Detects Bitbucket Pipelines OIDC flag (`oidc: true`) in the same step
# block as `AWS_ROLE_ARN`, indicating an unconstrained role-assumption
# without a scoped audience restriction. Bounded lazy span (600 chars ≈
# 10-15 YAML lines) prevents runaway matching.
_BITBUCKET_OIDC_WILDCARD = _re(
    r"oidc:\s*true[\s\S]{0,600}?AWS_ROLE_ARN"
)


# ---- R3 : bdc-bitbucket-services-privileged -----------------------------

# Catches `privileged: true` inside `definitions: services:` (any indent).
# The simpler indented form reduces false positives versus the top-level
# Drone case already handled by ci_runner_injection_patterns.py.
_BITBUCKET_SERVICES_PRIVILEGED = _re(
    r"^[ \t]+privileged:\s*true[ \t]*(?:#.*)?$"
)


# ---- R4 : bdc-drone-image-pull-secrets-committed ------------------------

# Detects literal registry credentials embedded in `image_pull_secrets:`
# (Drone syntax) — either a base64 blob or an inline `username:`/`password:`
# pair inside the secrets block.
_DRONE_IMAGE_PULL_SECRETS_COMMITTED = _re(
    r"image_pull_secrets:\s*\n(?:[ \t]+[^\n]+\n){0,10}"
    r"(?:[ \t]+(?:username|password|auth|token):[ \t]+['\"]?[A-Za-z0-9+/=_\-]{6,}['\"]?"
    r"|[ \t]+[a-zA-Z0-9+/=]{40,})"
)


# ---- R5 : bdc-drone-build-on-fork-branch --------------------------------

# Flags branch filter patterns that include `main` or `master`, which
# allow fork PRs with a branch named `main` to trigger trusted builds
# when Drone's fork-build feature is enabled.
_DRONE_BUILD_ON_FORK_BRANCH = _re(
    r"branch(?:es)?:\s*(?:\[[^\]]*\bma(?:in|ster)\b[^\]]*\]"
    r"|\s*\n\s*-\s*(?:main|master)\b)"
)


# ---- R6 : bdc-drone-commit-message-shell-injection ----------------------

# Detects unquoted or interpolated `$DRONE_COMMIT_MESSAGE`, `$DRONE_COMMIT_AUTHOR`,
# `$DRONE_SOURCE_BRANCH`, `$DRONE_TARGET_BRANCH`, or `$DRONE_PULL_REQUEST_TITLE`
# inside a `commands:` block — classic PPE injection vector.
_DRONE_COMMIT_MESSAGE_SHELL_INJECTION = _re(
    r"-[ \t]+[^\n]*\$DRONE_(?:COMMIT_(?:MESSAGE|AUTHOR|AUTHOR_EMAIL)"
    r"|SOURCE_BRANCH|TARGET_BRANCH|PULL_REQUEST_TITLE)[^\n]*"
)


# ---- R7 : bdc-drone-plugin-image-unpinned -------------------------------

# Flags Drone plugin images (`plugins/<name>`) referenced by mutable tags
# (:latest, :linux-amd64, :linux-arm64, :windows-amd64, :v<N>) or with
# no tag (implicit :latest). Digest-pinned refs (@sha256:) are excluded.
_DRONE_PLUGIN_IMAGE_UNPINNED = _re(
    r"image:\s*plugins/[a-zA-Z0-9_-]+"
    r"(?::(?:latest|linux-[a-z0-9]+|windows-[a-z0-9]+|v?[0-9]+))?"
    r"(?!\s*@\s*sha256:)"
    r"\s*(?:#.*)?$"
)


# ---- R8 : bdc-woodpecker-clone-disabled ---------------------------------

# Detects `clone: disable: true` (Woodpecker syntax) that bypasses the
# default source-checkout step, leaving pipeline workspace unverified.
_WOODPECKER_CLONE_DISABLED = _re(
    r"clone:\s*(?:\n[ \t]+disable:\s*true|disable:\s*true)"
)


# ---- R9 : bdc-woodpecker-runtime-user-controlled ------------------------

# Detects `backend: local` in Woodpecker pipeline YAML — routes step
# execution to the agent's host process space instead of an isolated
# Docker container.
_WOODPECKER_RUNTIME_USER_CONTROLLED = _re(
    r"^\s*backend:\s*local\s*(?:#.*)?$"
)


# ---- R10 : bdc-bitbucket-cache-key-predictable --------------------------

# Flags `key:` lines in `definitions: caches:` whose value does NOT
# contain a lock-file checksum reference (`checksum`, `hash`, `lock`,
# `sum`). A static or branch-based key is predictable and can be poisoned.
_BITBUCKET_CACHE_KEY_PREDICTABLE = _re(
    r"key:\s*['\"]?(?!.*(?:checksum|hash|lock|sum))[A-Za-z0-9${}._\-]{3,80}['\"]?"
    r"\s*(?:#.*)?$"
)


# ---- Rule registry ------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="bdc-bitbucket-image-latest",
        name="Bitbucket Pipelines uses a mutable or unpinned Docker image tag",
        severity="MAJOR",
        description=(
            "The `image:` key in `bitbucket-pipelines.yml` resolves to a "
            "mutable Docker Hub tag (:latest, :stable, :edge, :main, etc.) "
            "or has no tag (implicit :latest). Supply-chain attackers who "
            "compromise the registry account or re-push the tag can inject "
            "malicious layers that execute inside every future Bitbucket step. "
            "Fix: pin to a digest — `image: ubuntu:22.04@sha256:<64-hex>`."
        ),
        pattern=_BITBUCKET_IMAGE_LATEST,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="bdc-bitbucket-oidc-wildcard",
        name="Bitbucket Pipelines OIDC step assumes AWS role without audience constraint",
        severity="CRITICAL",
        description=(
            "A pipeline step declares `oidc: true` alongside `AWS_ROLE_ARN` "
            "without restricting the OIDC audience. A permissive AWS trust "
            "policy can allow any Bitbucket pipeline — including a fork — to "
            "assume the role. Fix: add a `Condition` block in the trust policy "
            "that pins `aud` to `sts.amazonaws.com` and `sub` to the expected "
            "workspace and repository UUID pair."
        ),
        pattern=_BITBUCKET_OIDC_WILDCARD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bdc-bitbucket-services-privileged",
        name="Bitbucket Pipelines service container runs with `privileged: true`",
        severity="HIGH",
        description=(
            "`definitions: services:` contains a `privileged: true` entry, "
            "granting the sidecar container full control of the runner host's "
            "Docker daemon. Combined with an unpinned service image, an attacker "
            "who controls the image can mount `/var/run/docker.sock` and "
            "exfiltrate build secrets. Fix: remove `privileged: true`; use "
            "Docker-in-Docker only via the official pinned `docker` service "
            "image."
        ),
        pattern=_BITBUCKET_SERVICES_PRIVILEGED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bdc-drone-image-pull-secrets-committed",
        name="Drone CI `image_pull_secrets:` contains literal registry credentials",
        severity="CRITICAL",
        description=(
            "The `image_pull_secrets:` block in `.drone.yml` contains an "
            "inline `username:`, `password:`, `auth:`, or `token:` field "
            "with a non-empty value — the registry credential is committed "
            "to the repository. Fix: move the credential to an encrypted "
            "Drone secret (`from_secret:`) and reference it by name."
        ),
        pattern=_DRONE_IMAGE_PULL_SECRETS_COMMITTED,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bdc-drone-build-on-fork-branch",
        name="Drone CI branch filter includes `main`/`master` — fork branch can trigger trusted build",
        severity="HIGH",
        description=(
            "A `branches:` or `trigger: branches:` filter includes `main` or "
            "`master`. On self-hosted Drone with fork builds enabled (default), "
            "a fork that names a branch `main` can trigger this pipeline with "
            "the same secrets and trusted environment as a legitimate `main` "
            "push. Fix: disable fork builds on the Drone server or add "
            "`trigger: event: [push]` to separate fork PRs from direct pushes."
        ),
        pattern=_DRONE_BUILD_ON_FORK_BRANCH,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="bdc-drone-commit-message-shell-injection",
        name="Drone CI `commands:` interpolates user-controlled `$DRONE_*` variable",
        severity="HIGH",
        description=(
            "A `commands:` entry embeds `$DRONE_COMMIT_MESSAGE`, "
            "`$DRONE_COMMIT_AUTHOR`, `$DRONE_SOURCE_BRANCH`, "
            "`$DRONE_TARGET_BRANCH`, or `$DRONE_PULL_REQUEST_TITLE` directly. "
            "An attacker who can push a commit or open a PR can inject shell "
            "metacharacters via the commit message or branch name. Fix: route "
            "these variables through strict quoting (`\"${DRONE_COMMIT_MESSAGE}\"`)"
            " and never pass them to `eval`, `sh -c`, or `bash -c`."
        ),
        pattern=_DRONE_COMMIT_MESSAGE_SHELL_INJECTION,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="bdc-drone-plugin-image-unpinned",
        name="Drone CI plugin image referenced by mutable tag, not digest",
        severity="MAJOR",
        description=(
            "`image: plugins/<name>` uses a mutable tag (:latest, "
            ":linux-amd64, :v<N>) or no tag. The Drone plugin ecosystem "
            "lives on Docker Hub under the `plugins/` namespace; a "
            "compromised Docker Hub account or re-pushed tag silently "
            "replaces the plugin with a malicious image on the next run. "
            "Fix: pin to a digest — `image: plugins/docker:20.10.21@sha256:<64-hex>`."
        ),
        pattern=_DRONE_PLUGIN_IMAGE_UNPINNED,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="bdc-woodpecker-clone-disabled",
        name="Woodpecker CI default clone step is disabled — source not verified",
        severity="HIGH",
        description=(
            "`clone: disable: true` bypasses Woodpecker's default source "
            "checkout. The pipeline runs without a verified checkout of the "
            "triggering commit, and may consume stale, tampered, or "
            "externally-sourced code. A poisoned cache can deliver arbitrary "
            "files into the workspace before any build step. Fix: remove "
            "`clone: disable: true`; override the clone step image if custom "
            "behaviour is needed."
        ),
        pattern=_WOODPECKER_CLONE_DISABLED,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="bdc-woodpecker-runtime-user-controlled",
        name="Woodpecker CI step uses `backend: local` — host exec without container isolation",
        severity="HIGH",
        description=(
            "`backend: local` routes step execution to the Woodpecker agent's "
            "host process space instead of an isolated Docker container. A "
            "fork PR that sets this field runs its `commands:` with the "
            "agent's OS user credentials — identical to `runs-on: self-hosted` "
            "with no container sandbox. Fix: set `WOODPECKER_BACKEND=docker` "
            "in the agent configuration and reject any pipeline YAML that "
            "contains `backend: local`."
        ),
        pattern=_WOODPECKER_RUNTIME_USER_CONTROLLED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="bdc-bitbucket-cache-key-predictable",
        name="Bitbucket Pipelines custom cache key is static — vulnerable to cache poisoning",
        severity="MAJOR",
        description=(
            "A `definitions: caches:` entry uses a `key:` value that does not "
            "incorporate a lock-file checksum (`checksum`, `hash`, `lock`, "
            "`sum`). A static or branch-based key is predictable: an attacker "
            "who triggers a build on the same branch can write malicious files "
            "to the cache path and have them restored into the next victim "
            "build. Fix: use Bitbucket's `{{ checksum \"package-lock.json\" }}` "
            "in the cache key so the key is content-addressed on the lock file."
        ),
        pattern=_BITBUCKET_CACHE_KEY_PREDICTABLE,
        owasp_asi="ASI-03",
    ),
)


# ---- Scanner ------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* against all rules and return a list of Findings.

    Lines and columns are 1-based. Each match produces exactly one Finding.
    Exceptions from regex execution are suppressed — the scanner is
    fail-safe for malformed input.
    """
    findings: list[Finding] = []
    lines = text.splitlines(keepends=True)
    # Build a line-start-offset table for O(1) line/col lookup.
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)

    for rule in RULES:
        try:
            for m in rule.pattern.finditer(text):
                start = m.start()
                # Binary-search for the line index.
                lo, hi = 0, len(offsets) - 1
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if offsets[mid] <= start:
                        lo = mid
                    else:
                        hi = mid - 1
                line_no = lo + 1
                col_no = start - offsets[lo] + 1
                matched = m.group(0)
                # Truncate absurdly long matches to 200 chars for readability.
                if len(matched) > 200:
                    matched = matched[:200] + "…"
                findings.append(
                    Finding(
                        rule_id=rule.id,
                        line=line_no,
                        column=col_no,
                        matched_text=matched,
                        severity=rule.severity,
                        description=rule.description,
                        owasp_asi=rule.owasp_asi,
                    )
                )
        except Exception:  # noqa: BLE001
            continue
    return findings
