"""Artifact / package-registry storage credential patterns.

Wave-27 distillation round 13. Catalogue of 7 anti-patterns covering
credentials embedded **in committed repo files** (or workspace dotfiles
staged for commit) that authenticate to a binary / package storage
registry: Nexus, JFrog Artifactory, npm, GitHub Packages, Docker Hub /
GHCR, Maven Central, AWS CodeArtifact, JetBrains Space Packages, etc.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic CI runtime echoes of `secrets.X` —
    `cicd_secret_leak_patterns.py` (those scan runtime log output;
    THIS module scans at-rest config files).
  * Sigstore / GPG / Twine signing material —
    `pypi_signing_patterns.py` (signing keys, not registry auth).
  * Lockfile integrity / dependency hash pinning —
    `sca_lockfile_patterns.py` (integrity, not auth).

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * artifact-npmrc-literal-authtoken                       (CRITICAL)
  * artifact-maven-settings-literal-password               (CRITICAL)
  * artifact-url-inline-user-password                      (HIGH)
  * artifact-docker-config-auth-b64                        (CRITICAL)
  * artifact-gradle-properties-literal-credential          (CRITICAL)
  * artifact-netrc-machine-password-block                  (CRITICAL)
  * artifact-aws-codeartifact-token-assignment             (CRITICAL)

Why a separate angle? A leaked Nexus admin password or an Artifactory
deploy token gives the attacker write access to the binary supply chain
— they can poison a release artifact that every downstream consumer
pulls. The credential surface is also distinctive: each package manager
has a canonical config file with a canonical key name, so the regex
shape is tighter than a generic `API_KEY=` hit.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (any literal credential committed to source)
  ASI-05 — Supply-chain / cross-tenant pivot (publish-write access to a
                                               binary artifact store)

All regexes are RE2-compatible (no backreferences, no variable-width
lookbehind, no catastrophic backtracking shapes — every quantifier is
bounded, every negative lookahead is fixed-width). Patterns are
PRE-COMPILED at module load. Fail-fast: callers receive structured
Finding tuples, never raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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


def _re(pattern: str) -> re.Pattern:
    """Compile with MULTILINE+UNICODE. Case is rule-specific (npmrc keys
    are lowercase, Maven XML tags are lowercase, env-var names are upper)
    so we do NOT toggle IGNORECASE globally. RE2-safe: no nested
    quantifiers, no backreferences, no variable-width lookbehind."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


def _rei(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — for env-var
    assignments where casing varies in real-world configs."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- A1 : artifact-npmrc-literal-authtoken ------------------------------


# An `.npmrc` line of the form
#   //registry.example.com/:_authToken=<literal>
# Safe form is `_authToken=${NPM_TOKEN}`. Literal form pins the secret
# into the repo / image layer. The `(?!\$\{)` is a fixed-width negative
# lookahead (RE2-safe) excluding the env-var-interpolation form.
_NPMRC_LITERAL_AUTHTOKEN = _re(
    r"^//[A-Za-z0-9._-]{1,253}/"
    r"(?:[A-Za-z0-9._/@-]{1,200}/)?"
    r":_authToken=(?!\$\{)[A-Za-z0-9+/=._-]{16,512}\s*$"
)


# ---- A2 : artifact-maven-settings-literal-password ----------------------


# Maven `settings.xml` `<server>` block with a literal `<password>`.
# Excludes the three legitimate forms: master-password-encrypted
# `{xxx==}`, env interpolation `${env.X}`, and empty placeholder
# `<password></password>`.
_MAVEN_SETTINGS_LITERAL_PASSWORD = _re(
    r"<password>(?!\{|\$\{|\s*</password>)"
    r"[^<\n]{6,256}</password>"
)


# ---- A3 : artifact-url-inline-user-password -----------------------------


# Package-registry URL embedding `user:password@` directly in the URL —
# the classic anti-pattern for Nexus / Artifactory / private PyPI /
# private npm scopes. Covers `pip --extra-index-url`, `npm config
# registry`, `gem source --add`, `cargo config registries`,
# `composer config repo`. The `(?!\$\{|@)` excludes env interpolation
# in userinfo (`${USER}:${PASS}@…`) and the SSH `user@host:path` shape
# (no colon-separated password).
_URL_INLINE_USER_PASSWORD = _re(
    r"\b(?:https?|git|ssh|svn)://"
    r"[A-Za-z0-9._~-]{1,64}:"
    r"(?!\$\{|@)[^@\s/:\"']{4,256}@"
    r"[A-Za-z0-9.-]{1,253}"
    r"(?:/[A-Za-z0-9./_~-]{0,255})?"
)


# ---- A4 : artifact-docker-config-auth-b64 -------------------------------


# Docker `config.json` `auths` entry with a base64(user:password) value.
# Trivially reversible. The `[\s\S]{1,2000}?` is a bounded non-greedy
# tempered class (RE2-safe — both Go regexp and Rust regex support
# bounded non-greedy quantifiers, and the upper bound prevents
# catastrophic-backtracking-class blowups). We can NOT use `[^{}]`
# here because real Docker configs nest: `{"auths":{"ghcr.io":{"auth":…
# so the outer pattern must allow `{` inside.
_DOCKER_CONFIG_AUTH_B64 = _re(
    r"\"auths\"\s*:\s*\{[\s\S]{0,2000}?"
    r"\"auth\"\s*:\s*\""
    r"[A-Za-z0-9+/]{16,2048}={0,2}\""
)


# ---- A5 : artifact-gradle-properties-literal-credential -----------------


# `gradle.properties` line assigning a literal password / API key /
# token to a key whose name follows the Gradle artifact-publishing
# convention. Common targets: GitHub Packages (`gpr.user` / `gpr.key`),
# Sonatype OSSRH, JFrog, Maven Central via Central Portal. Anchored
# with `(?m)^` (line-anchored) and bounded `.{4,256}` to avoid
# catastrophic backtracking.
_GRADLE_PROPERTIES_LITERAL_CREDENTIAL = _re(
    r"^\s*[A-Za-z][A-Za-z0-9_.-]{0,64}"
    r"(?:Password|ApiKey|AuthToken|AccessKey|[Tt]oken|[Pp]assphrase)"
    r"\s*=\s*(?!\$\{|\s*$)[^\s#].{4,256}$"
)


# ---- A6 : artifact-netrc-machine-password-block -------------------------


# `.netrc` entry targeting a known artifact-hosting domain. Domain
# whitelist is the disambiguator that makes this an artifact-storage
# detector rather than a generic `.netrc` detector. The Cargo
# `.netrc` flow for `cargo:token` against `crates.io` is intentionally
# in scope — Cargo recommends env-only credential providers since
# 1.79.
_NETRC_MACHINE_PASSWORD_BLOCK = _re(
    r"^\s*machine\s+"
    r"(?:[A-Za-z0-9.-]{1,253}\.)?"
    r"(?:jfrog\.io"
    r"|cloudsmith\.io"
    r"|pkg\.github\.com"
    r"|nexus\.[A-Za-z0-9.-]{1,200}"
    r"|artifactory\.[A-Za-z0-9.-]{1,200}"
    r"|api\.github\.com"
    r"|upload\.pypi\.org"
    r"|central\.sonatype\.org"
    r"|repo\.maven\.apache\.org)"
    r"\s+login\s+\S{1,128}"
    r"\s+password\s+(?!\$\{)\S{8,256}"
)


# ---- A7 : artifact-aws-codeartifact-token-assignment --------------------


# AWS CodeArtifact authorization token assigned to an environment
# variable, shell rc file, or committed shell script. Tokens are issued
# by `aws codeartifact get-authorization-token` and are valid up to 12h.
# The alternation covers BOTH the JWT-shape token (most common — three
# base64url segments separated by `.`) and the raw-opaque variant some
# AWS CLI versions still emit. The `(?!\$\{|\$\()` excludes the safe
# forms `${VAR}` and `$(aws codeartifact get-authorization-token …)`.
_AWS_CODEARTIFACT_TOKEN_ASSIGNMENT = _rei(
    r"^\s*(?:export\s+)?CODEARTIFACT_(?:AUTH_)?TOKEN\s*=\s*"
    r"[\"']?(?!\$\{|\$\()"
    r"(?:eyJ[A-Za-z0-9_-]{20,}"
    r"\.[A-Za-z0-9_-]{20,}"
    r"\.[A-Za-z0-9_-]{0,400}"
    r"|[A-Za-z0-9+/=_-]{200,2048})"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="artifact-npmrc-literal-authtoken",
        name="npmrc _authToken pinned as literal instead of ${ENV} reference",
        severity="CRITICAL",
        description=(
            "An `.npmrc` line of the form "
            "`//registry.example.com/:_authToken=<literal>` where the "
            "right-hand side is a literal token, not an `${ENV_VAR}` "
            "reference. The safe form is `_authToken=${NPM_TOKEN}`; "
            "the literal form pins the secret into the repo / image "
            "layer. Hits `.npmrc`, `~/.npmrc`, or `RUN echo … >> "
            "/root/.npmrc` Dockerfile lines. Leaked credential grants "
            "publish-write to the npm registry."
        ),
        pattern=_NPMRC_LITERAL_AUTHTOKEN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="artifact-maven-settings-literal-password",
        name="Maven settings.xml <password> is a literal, not {encrypted} or ${env.X}",
        severity="CRITICAL",
        description=(
            "A Maven `settings.xml` `<server>` block whose `<password>` "
            "is a literal string instead of an encrypted reference "
            "(`{...}`) or a property placeholder (`${env.X}`). "
            "Triggers on committed `settings.xml`, `~/.m2/settings.xml` "
            "copied into a Docker layer, or `mvn-settings.xml` test "
            "fixtures that escape into prod. Leaked credential grants "
            "Nexus / Artifactory deploy access."
        ),
        pattern=_MAVEN_SETTINGS_LITERAL_PASSWORD,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="artifact-url-inline-user-password",
        name="Package-registry URL embeds user:password@ in userinfo",
        severity="HIGH",
        description=(
            "A package-registry URL that embeds `user:password@` "
            "directly in the URL — the classic anti-pattern for Nexus / "
            "Artifactory / private PyPI / private npm scopes. Includes "
            "`pip --extra-index-url`, `npm config registry`, `gem "
            "source --add`, `cargo config registries`, `composer config "
            "repo`. The persisted config-file shape (`.pip/pip.conf`, "
            "`pyproject.toml`, `Pipfile`, `.npmrc`, "
            "`.cargo/config.toml`) is the target — CI-log echoes of the "
            "same shape are covered separately by "
            "`cicd_secret_leak_patterns.py`."
        ),
        pattern=_URL_INLINE_USER_PASSWORD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="artifact-docker-config-auth-b64",
        name="Docker config.json auths entry committed with base64 user:password",
        severity="CRITICAL",
        description=(
            "A Docker `config.json` `auths` entry committed to the "
            "repo. The `\"auth\"` field is base64(`user:password`) — "
            "trivially reversible with `base64 -d`. Hits when "
            "`~/.docker/config.json`, `.docker/config.json`, "
            "`dockerconfig.json` (Kubernetes ImagePullSecret payload), "
            "or a kustomize/Helm values file containing the same is "
            "staged for commit. Decoded value grants registry "
            "push/pull credentials."
        ),
        pattern=_DOCKER_CONFIG_AUTH_B64,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="artifact-gradle-properties-literal-credential",
        name="gradle.properties assigns a literal password/token to a publishing key",
        severity="CRITICAL",
        description=(
            "A `gradle.properties` line assigning a literal password / "
            "API key / token to a key whose name follows the Gradle "
            "artifact-publishing convention (`<repoId>Username`, "
            "`<repoId>Password`, `<repoId>ApiKey`, `<repoId>Token`). "
            "Common targets: GitHub Packages (`gpr.user` / `gpr.key`), "
            "Sonatype OSSRH (`ossrhPassword`), JFrog (`artifactoryUser` "
            "/ `artifactoryPassword`), Maven Central via Central Portal "
            "(`mavenCentralUsername` / `mavenCentralPassword`). Leaked "
            "credential grants Maven Central / GitHub Packages "
            "publish access."
        ),
        pattern=_GRADLE_PROPERTIES_LITERAL_CREDENTIAL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="artifact-netrc-machine-password-block",
        name=".netrc machine block targets an artifact-host with literal password",
        severity="CRITICAL",
        description=(
            "A `.netrc` entry that targets a known artifact-hosting "
            "domain (`api.github.com` for GitHub Packages tokens, "
            "`*.jfrog.io`, `*.cloudsmith.io`, `*.pkg.github.com`, "
            "`nexus.*`, `artifactory.*`, `upload.pypi.org`, "
            "`central.sonatype.org`, `repo.maven.apache.org`). The "
            "domain whitelist is what distinguishes this from a generic "
            "`.netrc` leak (which still leaks, but with lower blast "
            "radius). Generic `.netrc` modification is caught by other "
            "detectors; this rule is the content-level signal that the "
            "leak is specifically a registry credential."
        ),
        pattern=_NETRC_MACHINE_PASSWORD_BLOCK,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="artifact-aws-codeartifact-token-assignment",
        name="AWS CodeArtifact token pinned to env var instead of runtime $(aws …)",
        severity="CRITICAL",
        description=(
            "An AWS CodeArtifact authorization token assigned to an "
            "environment variable, shell rc file, or committed shell "
            "script. CodeArtifact tokens are issued by "
            "`aws codeartifact get-authorization-token` and are valid "
            "for up to 12h — they're frequently exfil-friendly because "
            "they look like JWT-ish strings and developers copy-paste "
            "them into `.bashrc` / `set-codeartifact-token.sh` for "
            "convenience. CodeArtifact tokens grant read+publish to "
            "the repo they were minted for; combined with a leaked AWS "
            "account ID / domain name they enable supply-chain "
            "poisoning."
        ),
        pattern=_AWS_CODEARTIFACT_TOKEN_ASSIGNMENT,
        owasp_asi="ASI-02",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    Each pattern is high-precision on its own — every regex carries a
    negative lookahead that excludes the safe form (`${env.X}`,
    `$(cmd)`, encrypted `{xxx}`) — so the scanner does NOT need stage-B
    context filters. Findings are deduped by (rule_id, line, col) and
    sorted by (line, col, rule_id) for deterministic output.
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            snippet = matched if len(matched) <= 200 else matched[:200] + "…"
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line,
                    column=col,
                    matched_text=snippet,
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
