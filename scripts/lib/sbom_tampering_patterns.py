"""License / SBOM tampering & forgery regex catalogue.

Wave-18 implementation of the distill-round-4 angle-D proposals
(`reports/distill-round-4/license-sbom-tampering.md`). Pattern-only
catalogue covering 15 tampering / forgery / wildcard-validation
vectors that fire **even when every `provenance_patterns.py` rule
passes** — provenance_patterns detects **absence** (missing cosign,
missing SBOM, missing in-toto, missing trusted-publishing, missing
checksum manifest, missing reproducible-build flag, SLSA-level
floor); this module detects **active tampering** of artefacts that
are present but lying.

Cross-reference with `scripts/lib/provenance_patterns.py`:
  * Rule 11 (`sbom-frozen-lockfile-skip-on-publish`) shares the
    `_REPRO_PUBLISHER_TOKENS` publisher gate with
    `prov-reproducible-build-flag-absent`; the actual regex (publish-
    job-scoped + missing-frozen flag) is disjoint.
  * Every other rule below is on a strictly disjoint attack surface.

Sources reviewed (per distill report):

  * `macaron/src/macaron/provenance/provenance_verifier.py:96-144`
    (`verify_npm_provenance`) — signed-vs-unsigned digest equality.
  * `macaron/src/macaron/dependency_analyzer/cyclonedx.py` —
    `JsonStrictValidator` accepts structurally-valid SBOM with
    `components: []`.
  * `supply-chain-defense-main/2026-05-14-npm-install-shouldnt-run-
    your-code.md` — `GOSUMDB=off` / `GOPROXY=…,direct` traps.
  * `supply-chain-defense-main/README.md` (Java/Maven) — Maven
    default `<checksumPolicy>warn</checksumPolicy>`.
  * `supply-chain-mitigation-master/scenarios/10-lockfile-smuggle/`
    — `package-lock.json` `resolved` pointing at attacker host.
  * `package-manager-hardening-main/docs/helm.md` —
    `--certificate-identity-regexp '.*'` too-broad.
  * `supply-chain-defense-main/cross-ecosystem/slsa-sigstore.md` —
    same wildcard-validator surface.

Hard constraints (verified):

  * Deterministic — pure file/line regex, no network, no shell-out,
    no LLM.
  * RE2-safe — every alternation uses `(?:...)`, no lookaround, no
    backrefs. Rules 2, 11, 15 use a Pass-1-capture + Pass-2-substring
    shape (same as `prov-reproducible-build-flag-absent`); no regex
    lookaround appears in the live patterns. Bounded `{0,N}` only.
  * Severity vocabulary mirrors provenance_patterns: CRITICAL /
    HIGH / MAJOR / MINOR (no MEDIUM).
  * Pure-stdlib (re + NamedTuple + pathlib).

Public surface:

  * Rule(id, name, severity, description, pattern,
        negative_substrings, file_suffixes)
  * RULES — ordered tuple of every rule.
  * Finding(rule_id, line, column, matched_text, severity,
            description, file_path) — frozen NamedTuple, identical
            shape to provenance_patterns.Finding.
  * scan_file(path: Path) -> list[Finding]
  * extract_npm_digest_set(text: str) -> set[str] — helper for
    Rule 6 cross-file digest comparison.
  * compare_npm_provenance_digests(signed: Path, unsigned: Path) ->
    bool — True iff digest sets differ.
  * extract_pom_classifier_versions(text: str) ->
    tuple[list[int], list[int]] — helper for Rule 8.
  * scan_pom_classifier_mismatch(path: Path) -> list[Finding] —
    pom-aware composite of Rule 8.

The negative-substring two-pass shape mirrors `provenance_patterns`:
positive regex hit on a specific line + same-file substring scan to
confirm no mitigating counter-tooling appears in the file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match. Same shape as `provenance_patterns.Finding`
    so heartbeat detectors can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    file_path: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load.

    `negative_substrings` are checked against the FULL FILE content;
    if any of them appear, the rule's positive matches are suppressed
    (the file contains a mitigating tool / verifier / counter-action
    that makes the positive match a false alarm).

    `file_suffixes` filters which files this rule applies to. Empty
    tuple = any file. Both the file's extension AND its bare name are
    checked (so `("Chart.lock",)` matches a file named `Chart.lock`
    without extension, and `(".toml", "config.toml")` matches both
    every `*.toml` and the bare `config.toml` filename).
    """

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    negative_substrings: tuple[str, ...]
    file_suffixes: tuple[str, ...]


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE. Same flag
    set as `provenance_patterns._re` so the surface is uniform across
    rule modules."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Rule 1 — sbom-cyclonedx-empty-components (HIGH) --------------------


# Empty CycloneDX `components` array. The JSON-schema validator passes
# `"components": []`; downstream SBOM scanners then report zero
# transitive deps. This is the canonical CycloneDX scrubbing attack.
# Two shapes covered: JSON empty-array and XML self-closing /
# empty-element form.
_SBOM_EMPTY_COMPONENTS = _re(
    r'"components"\s*:\s*\[\s*\]'
    r"|"
    r"<components\s*/>"
    r"|"
    r"<components>\s*</components>"
)


# ---- Rule 2 — sbom-lockfile-resolved-non-registry (CRITICAL) ------------


# Pass-1: capture every `"resolved": "..."` URL line in a lockfile.
# Pass-2 (Python-side, see scan_file) is a substring allowlist check —
# RE2-safe shape that mirrors `prov-reproducible-build-flag-absent`.
_LOCKFILE_RESOLVED = _re(
    r'"resolved"\s*:\s*"(https?://[^"\n]{1,400})"'
)

_NPM_REGISTRY_ALLOW: tuple[str, ...] = (
    "registry.npmjs.org/",
    "registry.yarnpkg.com/",
    "registry.npmmirror.com/",
    "npm.pkg.github.com/",
    # Common internal mirror patterns.
    "nexus.",
    "nexus-",
    "artifactory.",
    # Default GitHub Packages registry endpoint.
    "ghcr.io/",
)


# ---- Rule 3 — sbom-cargo-lock-replace-with (CRITICAL) -------------------


# `[source.crates-io] replace-with = "..."` block. The bounded `{0,400}`
# repetition between the section header and the captured value keeps
# the pattern RE2-safe (no unbounded quantifier).
_CARGO_REPLACE_WITH = _re(
    r"\[source\.crates-io\][^\[]{0,400}?"
    r"replace-with\s*=\s*\"([^\"\n]+)\""
)

_CARGO_MIRROR_ALLOW: tuple[str, ...] = (
    # cargo-vendor canonical name. Suppress only when this exact value
    # is used (the rule wants to surface every OTHER replace-with).
    "vendored-sources",
)


# ---- Rule 4 — sbom-go-sum-disabled (CRITICAL) ---------------------------


# Go checksum-database / sumdb / proxy bypasses. Four canonical shapes:
#   * GOSUMDB=off — disables checksum DB
#   * GONOSUMCHECK=1 — disables checksum verification
#   * GOFLAGS=…-insecure — broad insecure mode
#   * GOPROXY=…,direct — direct fallback bypasses proxy + checksum log
# All anchored to a word-boundary at start (start-of-line or whitespace)
# so they don't fire inside identifier strings.
_GO_SUM_BYPASS = _re(
    r"(?:^|\s)"
    r"(?:GOSUMDB\s*=\s*off"
    r"|GONOSUMCHECK\s*=\s*1"
    r"|GOFLAGS\s*=\s*[^\n]{0,200}-insecure"
    r"|GOPROXY\s*=\s*[^,\n]{1,200},\s*direct"
    r")\b"
)


# ---- Rule 5 — sbom-cosign-cert-identity-too-broad (HIGH) ----------------


# `--certificate-identity-regexp` with a pattern too broad to be safe.
# The three shapes we surface:
#   * `'.*'` — universal
#   * `'https://github.com/owner/.*'` — any workflow/branch in repo
#   * `'https://github.com/.*/.*'` — any repo
#   * `'https://github.com/owner/repo/.*'` — any workflow file in repo
# Quotes can be single or double; equals or space separator allowed.
_COSIGN_CERT_IDENTITY_BROAD = _re(
    r"--certificate-identity-regexp\s*[=\s]\s*"
    r"['\"]"
    r"(?:"
    r"\.\*"                                                # `.*`
    r"|\^?\.\*\$?"                                         # `^.*`, `.*$`, `^.*$`
    r"|https?://github\.com/[^/'\"\s]+/\.\*"               # any/branch
    r"|https?://github\.com/\.\*/\.\*"                     # any/any
    r"|https?://github\.com/[^/'\"\s]+/[^/'\"\s]+/\.\*"    # owner/repo/anything
    r")"
    r"['\"]"
)


# ---- Rule 6 — sbom-npm-provenance-digest-mismatch (CRITICAL) ------------


# Single-file pattern just extracts every `"sha256":"<hex>"` so the
# composite Python-side helper can cross-reference signed vs unsigned
# provenance pairs.
_NPM_PROVENANCE_DIGEST = _re(
    r'"sha256"\s*:\s*"([a-f0-9]{64})"'
)


# ---- Rule 7 — sbom-maven-checksum-policy-warn (HIGH) --------------------


# `<checksumPolicy>warn</checksumPolicy>` inside a `<mirror>` /
# `<repository>` / `<releases>` / `<snapshots>` block. The naive
# substring match is enough — Maven's default behaviour is `warn`,
# and surfacing every literal occurrence is the rule's purpose.
_MAVEN_CHECKSUM_WARN = _re(
    r"<checksumPolicy>\s*warn\s*</checksumPolicy>"
)

_MAVEN_CHECKSUM_FAIL: tuple[str, ...] = (
    "<checksumPolicy>fail</checksumPolicy>",
)


# ---- Rule 8 — sbom-pom-classifier-version-mismatch (MAJOR) --------------


# Stage 1 — extract every classifier matching a JDK / JRE / native /
# OS-arch suffix. Used by the composite helper to compare against the
# declared maven.compiler.source / target / java.version.
_POM_CLASSIFIER = _re(
    r"<classifier>\s*(?P<cls>jdk\d+|jre\d+|native|linux-x86_64|darwin-arm64)\s*</classifier>"
)

# Stage 2 — extract every Java version declaration. Three shapes:
#   * <java.version>11</java.version>
#   * <maven.compiler.source>11</maven.compiler.source>
#   * <maven.compiler.target>11</maven.compiler.target>
_POM_JAVA_VERSION = _re(
    r"<(?:java\.version|maven\.compiler\.source|maven\.compiler\.target)>"
    r"\s*(?P<ver>\d{1,3})\s*"
    r"</(?:java\.version|maven\.compiler\.source|maven\.compiler\.target)>"
)


# ---- Rule 9 — sbom-cosign-blob-noverify (HIGH) --------------------------


# `cosign verify` / `verify-blob` invoked with one of the documented
# "for testing only" insecure flags. The bounded `[^\n]{0,300}` keeps
# the pattern RE2-safe. The COSIGN_EXPERIMENTAL env-var form is a
# separate disjunct anchored to a line context.
_COSIGN_NOVERIFY = _re(
    r"(?:^|\s)cosign\s+(?:verify|verify-blob)[^\n]{0,300}"
    r"(?:--insecure-ignore-tlog"
    r"|--insecure-ignore-sct"
    r"|--insecure-skip-verify"
    r"|--allow-insecure-registry"
    r")\b"
    r"|"
    r"(?:^|\s)COSIGN_EXPERIMENTAL\s*=\s*1\b"
)

_COSIGN_REKOR_OVERRIDE: tuple[str, ...] = (
    # An explicit Rekor URL override turns "ignore-tlog" into a
    # documented internal-Rekor flow — suppress when present.
    "--rekor-url=",
)


# ---- Rule 10 — sbom-spdx-license-stripped (MAJOR) -----------------------


# Single-file regex: does the file contain `SPDX-License-Identifier:`
# anywhere in its first 30 lines? The composite helper checks both
# this file AND sibling files in the same directory.
_SPDX_LICENSE_IDENTIFIER = _re(
    r"SPDX-License-Identifier\s*:\s*\S+"
)

# Recognised source-code extensions that conventionally carry SPDX
# headers when the project uses them. Generated-file globs are
# suppressed via the negative-substring set below.
_SPDX_SOURCE_SUFFIXES: tuple[str, ...] = (
    ".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".cpp", ".c", ".h", ".cs", ".rb", ".swift", ".kt",
)


# ---- Rule 11 — sbom-frozen-lockfile-skip-on-publish (HIGH) --------------


# Pass-1: capture every install command inside a workflow run step.
# Pass-2 (Python-side): substring check the captured line for a
# guard token from `_FROZEN_GUARDS`.
_FROZEN_INSTALL_LINE = _re(
    r"^[\s]*-?\s*run:\s*"
    r"((?:npm|pnpm|yarn|bun|pip)\s+install\b[^\n]*)$"
)

_FROZEN_GUARDS: tuple[str, ...] = (
    "--frozen-lockfile",
    "--immutable",
    "--require-hashes",
    "npm ci",
    "pnpm ci",
    # `--frozen` (uv) and `--locked` (cargo) also count
    "--frozen",
    "--locked",
)

# Publisher gate — reuses the publisher-token list documented in
# `provenance_patterns._REPRO_PUBLISHER_TOKENS`. Reproduced verbatim
# here so this module is self-contained (consumer modules pick whichever
# import path they already have). Keep in sync with provenance_patterns.
_REPRO_PUBLISHER_TOKENS: tuple[str, ...] = (
    "npm publish",
    "pnpm publish",
    "yarn publish",
    "JS-DevTools/npm-publish",
    "twine upload",
    "pypa/gh-action-pypi-publish",
    "poetry publish",
    "flit publish",
    "uv publish",
    "gem push",
    "cargo publish",
    "mvn deploy",
    "gradle publish",
    "dotnet nuget push",
    "docker push",
    "docker buildx build",
    "gh release create",
    "gh release upload",
    "softprops/action-gh-release",
    "ncipollo/release-action",
    "goreleaser/goreleaser-action",
    "actions/upload-release-asset",
    "actions/upload-artifact",
    "docker/build-push-action",
)


# ---- Rule 12 — sbom-source-date-epoch-mismatch (MAJOR) ------------------


# `SOURCE_DATE_EPOCH=<literal>` where the literal is implausible:
#   * `0` (Unix epoch 1970-01-01)
#   * `1` (also nonsensical)
#   * `1234567890` (canonical test fixture value)
#   * any value < 10 digits — < 2001-09-09 so almost certainly fake
# Plausible recent epochs are >= 10 digits; the regex deliberately
# omits 10+ digit captures.
_SDE_LITERAL_BAD = _re(
    r"SOURCE_DATE_EPOCH\s*=\s*(?:0\b|1\b|1234567890\b|\d{2,9}\b)"
)

_SDE_FROM_GIT: tuple[str, ...] = (
    "SOURCE_DATE_EPOCH=$(git log",
    'SOURCE_DATE_EPOCH="$(git log',
    "SOURCE_DATE_EPOCH=$(git log -1",
    "git log -1 --format=%ct",
    "git log --pretty=format:%ct",
)


# ---- Rule 13 — sbom-release-from-non-tag-ref (HIGH) ---------------------


# A release/publish workflow with an `actions/checkout` step whose
# `ref:` points at a branch name (`main`, `master`, `develop`,
# `release`, `HEAD`) instead of a tagged ref. The bounded
# `[\s\S]{0,2000}?` between the job header and the checkout step is
# RE2-safe (no unbounded `*`/`+`).
# NOTE: `jobs:` and the named job (`release:` / `publish:`) sit on
# separate lines in YAML, so the span between them MUST traverse
# newlines — use bounded `[\s\S]{0,400}?` not `[^\n]{0,400}`. Same
# for the `uses:` and `ref:` lookups inside the job body. Bounded
# multi-line spans are RE2-safe (`{0,N}` literal upper bound, no
# unbounded `*`/`+`).
_RELEASE_NON_TAG_REF = _re(
    r"(?:jobs?:[\s\S]{0,400}?(?:release|publish):"
    r"|name:\s*[^\n]{0,200}(?:release|publish))"
    r"[\s\S]{0,2000}?"
    r"uses:\s*actions/checkout@[^\n]+"
    r"[\s\S]{0,500}?"
    r"ref:\s*['\"]?(?:main|master|develop|release|HEAD)['\"]?\b"
)

_TAGGED_RELEASE_TOKENS: tuple[str, ...] = (
    "refs/tags/",
    "github.ref_name",
    "tag_name:",
    "github.event.release.tag_name",
)


# ---- Rule 14 — sbom-license-file-mit-but-vendor-gpl (MAJOR) -------------


# Stage 1 — repository root LICENSE that looks like MIT. Two canonical
# substrings catch every variant.
_LICENSE_MIT_MARKER = _re(
    r"MIT License"
    r"|"
    r"Permission is hereby granted, free of charge"
)

# Stage 2 — somewhere else in the tree, a source file declares a
# GPL-family license via SPDX line or the canonical GPL preamble.
_LICENSE_GPL_MARKER = _re(
    r"SPDX-License-Identifier\s*:\s*(?:GPL-2\.0|GPL-3\.0|AGPL-3\.0|LGPL-[23]\.[01])"
    r"|"
    r"This program is free software[^\n]{0,200}GNU General Public License"
)


# ---- Rule 15 — sbom-helm-chart-lock-digest-missing (MAJOR) --------------


# Pass-1: capture every dependency stanza from Chart.lock — between
# `- name:` and either the next `- name:` or EOF. RE2-safe via the
# bounded `[\s\S]{0,2000}?` non-greedy span.
# Pass-2 (Python-side): substring-check each captured stanza for
# `digest: sha256:<64 hex>`.
_HELM_LOCK_DEP_STANZA = _re(
    r"-\s+name:\s*[^\n]{1,200}\n"
    r"(?:[ \t]+[^\n]{0,300}\n){0,40}"
)

_HELM_LOCK_DIGEST_PATTERN = _re(
    r"digest:\s*sha256:[a-f0-9]{64}"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="sbom-cyclonedx-empty-components",
        name="CycloneDX bom file with empty components array",
        severity="HIGH",
        description=(
            "A CycloneDX bom file is committed but has zero dependency "
            "components listed. Either the SBOM generator was "
            "misconfigured (CI lies about what it scanned), or the file "
            "was scrubbed post-build to hide a poisoned transitive. "
            "Regenerate with `syft . -o cyclonedx-json` and compare line "
            "counts."
        ),
        pattern=_SBOM_EMPTY_COMPONENTS,
        negative_substrings=(),
        # CycloneDX positional names — checked by filename, not extension.
        file_suffixes=(
            "bom.json", "bom.xml",
            ".cdx.json", ".cdx.xml",
        ),
    ),
    Rule(
        id="sbom-lockfile-resolved-non-registry",
        name="npm lockfile pins dependency to non-canonical registry",
        severity="CRITICAL",
        description=(
            "A lockfile pins a dependency to a non-canonical registry "
            "URL. In the lockfile-smuggle attack, a tiny `package.json` "
            "diff hides a 5000-line `package-lock.json` diff that "
            "rewires one transitive to an attacker-controlled host. "
            "`npm ci` honours `resolved` verbatim — bypassing every "
            "flag in `.npmrc`. Review every `resolved` change in "
            "lockfile diffs."
        ),
        # Pass-1 regex; pass-2 allowlist applied in scan_file().
        pattern=_LOCKFILE_RESOLVED,
        negative_substrings=(),
        file_suffixes=("package-lock.json", "npm-shrinkwrap.json"),
    ),
    Rule(
        id="sbom-cargo-lock-replace-with",
        name="Cargo registry replace-with points at third-party source",
        severity="CRITICAL",
        description=(
            "`Cargo.toml` / `.cargo/config.toml` replaces the official "
            "crates.io index with a third-party source. The lockfile's "
            "checksums get regenerated from that source — an attacker "
            "who controls the replacement registry controls every "
            "crate hash. If this is an internal mirror, document it; "
            "if it isn't, this is registry-confusion."
        ),
        pattern=_CARGO_REPLACE_WITH,
        negative_substrings=(),  # allowlist applied in scan_file()
        file_suffixes=(".toml", "config.toml", "Cargo.toml"),
    ),
    Rule(
        id="sbom-go-sum-disabled",
        name="Go checksum-database / sumdb / proxy bypass",
        severity="CRITICAL",
        description=(
            "A workflow or shell script disables Go's module-checksum "
            "database or sets `GOPROXY=…,direct`. The `direct` "
            "fallback bypasses the proxy AND the checksum log when "
            "the proxy returns 404 — exactly the failure-mode an "
            "attacker would induce. Use `GOPROXY=…,off` and keep "
            "`GOSUMDB=sum.golang.org`."
        ),
        pattern=_GO_SUM_BYPASS,
        negative_substrings=(),
        file_suffixes=(
            ".yml", ".yaml", ".sh", ".bash",
            "Dockerfile", "Makefile",
            ".env", ".envrc",
        ),
    ),
    Rule(
        id="sbom-cosign-cert-identity-too-broad",
        name="cosign --certificate-identity-regexp matches any workflow/branch",
        severity="HIGH",
        description=(
            "`cosign verify` uses a certificate-identity regex broad "
            "enough to accept signatures from any branch / workflow / "
            "fork. An attacker who can run any workflow in the named "
            "org/repo can produce a signature that passes this check. "
            "Tighten the regex to the exact publish workflow file + "
            "branch ref: `^https://github.com/owner/repo/\\.github/"
            "workflows/publish\\.yml@refs/heads/main$`."
        ),
        pattern=_COSIGN_CERT_IDENTITY_BROAD,
        negative_substrings=(),
        file_suffixes=(".yml", ".yaml", ".sh", ".bash", ".md"),
    ),
    Rule(
        id="sbom-npm-provenance-digest-mismatch",
        name="npm provenance sha256 digest extractor",
        severity="CRITICAL",
        description=(
            "A signed/unsigned npm provenance pair has divergent "
            "`subject[].digest.sha256` values for the same package. "
            "macaron's verifier (and npm's) reject this — the signed "
            "payload's subject digest MUST equal the unsigned "
            "payload's subject digest. A mismatch indicates tampering "
            "between sign-and-publish. Use "
            "`compare_npm_provenance_digests()` for the pair-check."
        ),
        pattern=_NPM_PROVENANCE_DIGEST,
        negative_substrings=(),
        # NamedTuple covers the pair extraction; single-file scan only
        # emits findings via the composite helper, but the rule must
        # still appear in RULES so the scanner can route file matches.
        file_suffixes=(
            ".intoto.jsonl", ".sigstore.json", ".jsonl",
            ".sig", ".provenance.json",
        ),
    ),
    Rule(
        id="sbom-maven-checksum-policy-warn",
        name="Maven <checksumPolicy>warn</checksumPolicy>",
        severity="HIGH",
        description=(
            "Maven's default `<checksumPolicy>warn</checksumPolicy>` "
            "silently installs jars whose declared SHA-1 doesn't "
            "match what was downloaded. Set to `fail` in every "
            "`<mirror>` and `<repository>` block."
        ),
        pattern=_MAVEN_CHECKSUM_WARN,
        negative_substrings=_MAVEN_CHECKSUM_FAIL,
        file_suffixes=("settings.xml", "pom.xml"),
    ),
    Rule(
        id="sbom-pom-classifier-version-mismatch",
        name="Maven dependency classifier extractor",
        severity="MAJOR",
        description=(
            "A maven dependency uses a classifier (jdk16/jre/native) "
            "that implies a runtime variant the build doesn't target. "
            "Classifiers are opaque to maven's version-pinning — an "
            "attacker who controls a published jar can ship a "
            "JDK16-classified artefact whose code actually targets a "
            "vulnerable older JVM. Use `scan_pom_classifier_mismatch()` "
            "for the comparison."
        ),
        pattern=_POM_CLASSIFIER,
        negative_substrings=(),
        file_suffixes=("pom.xml",),
    ),
    Rule(
        id="sbom-cosign-blob-noverify",
        name="cosign verify invoked with insecure flag",
        severity="HIGH",
        description=(
            "`cosign verify` invoked with `--insecure-ignore-tlog` / "
            "`--insecure-ignore-sct` / `--insecure-skip-verify`. Each "
            "flag disables a distinct integrity check — transparency-"
            "log inclusion, Signed Certificate Timestamp, or TLS "
            "validation. None should appear in a production verify "
            "step. Remove the flag or run a proper internal Rekor "
            "with `--rekor-url=`."
        ),
        pattern=_COSIGN_NOVERIFY,
        negative_substrings=_COSIGN_REKOR_OVERRIDE,
        file_suffixes=(".yml", ".yaml", ".sh", ".bash", "Dockerfile"),
    ),
    Rule(
        id="sbom-spdx-license-stripped",
        name="Source file missing SPDX-License-Identifier",
        severity="MAJOR",
        description=(
            "A source file in a directory where "
            "SPDX-License-Identifier is the convention is missing its "
            "license header. Common tampering: a vendored file is "
            "copied in, the SPDX line is stripped, and license-"
            "compliance tooling (FOSSA / Scancode / cyclonedx-cli) "
            "treats the file as 'no license declared = permissive.' "
            "Use `scan_spdx_stripped_dir()` for the comparison."
        ),
        # Marker pattern — composite helper uses it to detect presence.
        pattern=_SPDX_LICENSE_IDENTIFIER,
        negative_substrings=(),
        file_suffixes=_SPDX_SOURCE_SUFFIXES,
    ),
    Rule(
        id="sbom-frozen-lockfile-skip-on-publish",
        name="Publish job runs install without --frozen-lockfile",
        severity="HIGH",
        description=(
            "A publish-job runs `npm install` (or pnpm/yarn/bun/pip "
            "equivalent) without `--frozen-lockfile` / `--immutable` / "
            "`--require-hashes`. The lockfile gets re-resolved mid-"
            "publish; any registry-side change between checkout and "
            "publish lands in the released artefact — with no commit-"
            "side evidence. Use `npm ci`, `pnpm install --frozen-"
            "lockfile`, `yarn install --immutable`, `bun install "
            "--frozen-lockfile`, or `pip install --require-hashes`."
        ),
        pattern=_FROZEN_INSTALL_LINE,
        negative_substrings=(),  # guard tokens applied in scan_file()
        file_suffixes=(".yml", ".yaml"),
    ),
    Rule(
        id="sbom-source-date-epoch-mismatch",
        name="SOURCE_DATE_EPOCH set to implausible literal",
        severity="MAJOR",
        description=(
            "`SOURCE_DATE_EPOCH` is set to a literal constant. The "
            "whole point of `SOURCE_DATE_EPOCH` is to make build "
            "outputs deterministic based on commit timestamp; a hard-"
            "coded value makes every build at every commit look "
            "identical, defeating reproducibility and any attestation "
            "that depends on it. Derive from `git log -1 --format=%ct`."
        ),
        pattern=_SDE_LITERAL_BAD,
        negative_substrings=_SDE_FROM_GIT,
        file_suffixes=(
            ".yml", ".yaml", "Dockerfile", ".sh", ".bash",
        ),
    ),
    Rule(
        id="sbom-release-from-non-tag-ref",
        name="Release workflow checks out branch ref instead of tag",
        severity="HIGH",
        description=(
            "A `release` / `publish` workflow checks out a branch ref "
            "instead of a tagged ref. The published artefact reflects "
            "whatever is at branch HEAD at build time — an attacker "
            "who races a commit in seconds before the trigger fires "
            "lands code in the release with no tagged-commit audit "
            "trail. Use `ref: ${{ github.event.release.tag_name }}` "
            "or `ref: refs/tags/${{ github.ref_name }}`."
        ),
        pattern=_RELEASE_NON_TAG_REF,
        negative_substrings=_TAGGED_RELEASE_TOKENS,
        file_suffixes=(".yml", ".yaml"),
    ),
    Rule(
        id="sbom-license-file-mit-but-vendor-gpl",
        name="License-file extractor (MIT marker)",
        severity="MAJOR",
        description=(
            "Repo root declares MIT in `LICENSE` but at least one "
            "source file carries a GPL-family SPDX line or GPL "
            "preamble. Either (a) the root LICENSE is wrong and must "
            "be updated to the most-restrictive license actually in "
            "the tree, or (b) the GPL file was vendored without "
            "attribution and should be removed/replaced. License "
            "laundering is a real supply-chain attack — copyleft "
            "obligation evasion is a documented pattern. Use "
            "`scan_license_mit_vendor_gpl()` for the cross-tree "
            "comparison."
        ),
        pattern=_LICENSE_MIT_MARKER,
        negative_substrings=(),
        # Repository-root LICENSE filenames — no extension is normal.
        file_suffixes=(
            "LICENSE", "LICENSE.md", "LICENSE.txt", "LICENSE.rst",
            "COPYING",
        ),
    ),
    Rule(
        id="sbom-helm-chart-lock-digest-missing",
        name="Helm Chart.lock dependency lacks sha256 digest",
        severity="MAJOR",
        description=(
            "`Chart.lock` has a dependency stanza with no `digest:` "
            "field (or a non-sha256 digest). `helm dependency build` "
            "will pull whatever the registry currently serves at the "
            "named tag — bypassing integrity for that one subchart. "
            "Regenerate `Chart.lock` with `helm dependency update` "
            "against the locked Helm CLI version."
        ),
        pattern=_HELM_LOCK_DEP_STANZA,
        negative_substrings=(),  # digest check applied per-stanza
        file_suffixes=("Chart.lock",),
    ),
)


# ---- Optional env-driven knobs ------------------------------------------


def _env_csv(name: str) -> tuple[str, ...]:
    """Read a comma-separated env knob (e.g. JANITOR_OPT_SBOM_ALLOW_HOSTS)
    into a tuple of trimmed non-empty substrings. Returns () if unset."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return ()
    return tuple(s.strip() for s in raw.split(",") if s.strip())


def _npm_registry_allowlist() -> tuple[str, ...]:
    """Composite of the built-in npm-registry allowlist and any
    operator-supplied extras via `JANITOR_OPT_SBOM_ALLOW_HOSTS`."""
    return _NPM_REGISTRY_ALLOW + _env_csv("JANITOR_OPT_SBOM_ALLOW_HOSTS")


def _cargo_mirror_allowlist() -> tuple[str, ...]:
    """Composite of the built-in cargo-mirror allowlist and any extras
    via `JANITOR_OPT_CARGO_MIRROR_ALLOW`."""
    return _CARGO_MIRROR_ALLOW + _env_csv("JANITOR_OPT_CARGO_MIRROR_ALLOW")


# ---- Composite helpers (multi-file / two-stage rules) -------------------


def extract_npm_digest_set(text: str) -> set[str]:
    """Return the set of sha256 hex digests found in `text`. Used by
    Rule 6 (`sbom-npm-provenance-digest-mismatch`) to compare signed
    vs unsigned provenance pairs.

    Pure extraction — no file I/O. The composite helper
    `compare_npm_provenance_digests` does the file I/O + comparison.
    """
    if not text:
        return set()
    out: set[str] = set()
    for m in _NPM_PROVENANCE_DIGEST.finditer(text):
        digest = m.group(1).lower()
        out.add(digest)
    return out


def compare_npm_provenance_digests(
    signed: Path,
    unsigned: Path,
) -> bool:
    """True iff the two files' digest sets differ AND both sets are
    non-empty. Mirrors macaron's `verify_npm_provenance` check: a
    mismatch between the signed and unsigned subject digests indicates
    the provenance bundle has been tampered with between sign and
    publish.

    Returns False on any read error or on an empty digest set from
    either file (insufficient evidence — caller decides whether to
    flag the missing-digest case via a separate rule).
    """
    try:
        signed_text = signed.read_text(encoding="utf-8", errors="replace")
        unsigned_text = unsigned.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    signed_set = extract_npm_digest_set(signed_text)
    unsigned_set = extract_npm_digest_set(unsigned_text)
    if not signed_set or not unsigned_set:
        return False
    return signed_set != unsigned_set


def extract_pom_classifier_versions(
    text: str,
) -> tuple[list[int], list[int]]:
    """Return (classifier_jdk_versions, declared_java_versions) found in
    a pom.xml. Used by Rule 8 (`sbom-pom-classifier-version-mismatch`).

    Classifier extraction recognises `jdk<N>` / `jre<N>` only — other
    classifiers (native, linux-x86_64, darwin-arm64) yield 0 (they
    don't carry a JDK-version constraint and are ignored by the
    mismatch comparison).

    Java-version extraction recognises `<java.version>` and
    `<maven.compiler.source|target>`. Multiple declarations are all
    captured.
    """
    if not text:
        return ([], [])
    jdks: list[int] = []
    for m in _POM_CLASSIFIER.finditer(text):
        cls = m.group("cls").lower()
        # JDK or JRE → strip prefix and parse the digits.
        if cls.startswith("jdk") or cls.startswith("jre"):
            num = cls[3:]
            if num.isdigit():
                jdks.append(int(num))
        # Other classifiers (native, OS-arch) don't carry a JDK number
        # so we omit them from the mismatch comparison.
    versions: list[int] = []
    for m in _POM_JAVA_VERSION.finditer(text):
        ver = m.group("ver")
        if ver.isdigit():
            versions.append(int(ver))
    return (jdks, versions)


def scan_pom_classifier_mismatch(path: Path) -> list[Finding]:
    """Composite Rule 8: read a pom.xml, extract classifiers + java
    versions, fire MAJOR if max(classifier_jdk) > max(declared_java).

    Empty list when:
      * path can't be read
      * no classifier extracted
      * no java version declared
      * classifier_max <= declared_max (the safe case)
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    jdks, versions = extract_pom_classifier_versions(text)
    if not jdks or not versions:
        return []
    if max(jdks) <= max(versions):
        return []
    # Anchor the finding at the first classifier line so the operator
    # has a concrete location to inspect.
    first_classifier = _POM_CLASSIFIER.search(text)
    if first_classifier is None:  # pragma: no cover — jdks non-empty
        return []
    line, col = _line_col(text, first_classifier.start())
    matched = first_classifier.group(0).strip()
    # The Rule record describes the surface in detail; reuse it.
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "sbom-pom-classifier-version-mismatch"),
        "",
    )
    return [Finding(
        rule_id="sbom-pom-classifier-version-mismatch",
        line=line,
        column=col,
        matched_text=matched,
        severity="MAJOR",
        description=rule_desc,
        file_path=str(path),
    )]


def scan_spdx_stripped_dir(directory: Path) -> list[Finding]:
    """Composite Rule 10: scan every source file in `directory` for an
    SPDX header in its first 30 lines. If ≥ 50 % of siblings DO have a
    header and a given file does NOT → emit a MAJOR finding for that
    file.

    Empty list when:
      * directory unreadable
      * fewer than 2 source-extension files in directory
      * sibling-with-SPDX ratio < 50 %
    """
    if not directory.is_dir():
        return []
    candidates: list[Path] = []
    try:
        for entry in directory.iterdir():
            if not entry.is_file():
                continue
            name = entry.name.lower()
            if any(name.endswith(suf) for suf in _SPDX_SOURCE_SUFFIXES):
                candidates.append(entry)
    except OSError:
        return []
    if len(candidates) < 2:
        return []
    with_spdx: list[Path] = []
    without_spdx: list[Path] = []
    for cand in candidates:
        try:
            # First 30 lines only — slice in Python, not regex.
            lines = cand.read_text(
                encoding="utf-8", errors="replace",
            ).splitlines()[:30]
        except OSError:
            continue
        head = "\n".join(lines)
        if _SPDX_LICENSE_IDENTIFIER.search(head):
            with_spdx.append(cand)
        else:
            without_spdx.append(cand)
    if not with_spdx:
        return []
    # ≥ 50 % siblings with SPDX → convention is established here.
    if len(with_spdx) * 2 < len(candidates):
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "sbom-spdx-license-stripped"),
        "",
    )
    findings: list[Finding] = []
    for stripped in without_spdx:
        findings.append(Finding(
            rule_id="sbom-spdx-license-stripped",
            line=1,
            column=1,
            matched_text=stripped.name,
            severity="MAJOR",
            description=rule_desc,
            file_path=str(stripped),
        ))
    findings.sort(key=lambda f: f.file_path)
    return findings


def scan_license_mit_vendor_gpl(root: Path) -> list[Finding]:
    """Composite Rule 14: walk `root`, find a MIT LICENSE file at the
    top level AND any source file with a GPL marker anywhere in the
    tree. Fire MAJOR when both conditions hold.

    Empty list when:
      * root unreadable
      * no MIT LICENSE at root
      * no GPL-tagged file anywhere in tree
    """
    if not root.is_dir():
        return []
    # Step 1: find a top-level LICENSE-shape file that looks MIT.
    mit_license: Path | None = None
    try:
        for entry in root.iterdir():
            if not entry.is_file():
                continue
            if entry.name.upper().startswith(("LICENSE", "COPYING")):
                try:
                    text = entry.read_text(
                        encoding="utf-8", errors="replace",
                    )
                except OSError:
                    continue
                if _LICENSE_MIT_MARKER.search(text):
                    mit_license = entry
                    break
    except OSError:
        return []
    if mit_license is None:
        return []
    # Step 2: walk the tree for any file containing a GPL marker.
    gpl_file: Path | None = None
    for sub in root.rglob("*"):
        if not sub.is_file():
            continue
        # Skip the LICENSE file itself.
        if sub == mit_license:
            continue
        # Skip binary / large files heuristically.
        try:
            if sub.stat().st_size > 5_000_000:
                continue
            text = sub.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _LICENSE_GPL_MARKER.search(text):
            gpl_file = sub
            break
    if gpl_file is None:
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "sbom-license-file-mit-but-vendor-gpl"),
        "",
    )
    return [Finding(
        rule_id="sbom-license-file-mit-but-vendor-gpl",
        line=1,
        column=1,
        matched_text=f"MIT root={mit_license.name}, GPL file={gpl_file.name}",
        severity="MAJOR",
        description=rule_desc,
        file_path=str(mit_license),
    )]


def scan_helm_chart_lock_missing_digests(path: Path) -> list[Finding]:
    """Composite Rule 15: parse a Chart.lock and emit one MAJOR
    finding per dependency stanza lacking a valid sha256 digest.

    The two-pass shape: pass 1 captures every dependency stanza; pass
    2 substring-checks for `digest: sha256:<64 hex>`. RE2-safe.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text:
        return []
    findings: list[Finding] = []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "sbom-helm-chart-lock-digest-missing"),
        "",
    )
    for m in _HELM_LOCK_DEP_STANZA.finditer(text):
        stanza = m.group(0)
        if _HELM_LOCK_DIGEST_PATTERN.search(stanza):
            continue  # has a valid sha256 digest — safe
        line, col = _line_col(text, m.start())
        matched = stanza.splitlines()[0].strip() if stanza else ""
        findings.append(Finding(
            rule_id="sbom-helm-chart-lock-digest-missing",
            line=line,
            column=col,
            matched_text=matched,
            severity="MAJOR",
            description=rule_desc,
            file_path=str(path),
        ))
    return findings


# ---- Scan helpers -------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_matches_suffixes(
    path: Path,
    suffixes: tuple[str, ...],
) -> bool:
    """Empty suffix tuple → any file. Otherwise check the path's name
    ends with one of the suffixes (case-insensitive) — including bare
    filename matches (so `("Chart.lock",)` matches the literal name
    `Chart.lock` without extension)."""
    if not suffixes:
        return True
    name = path.name.lower()
    return any(name.endswith(suf.lower()) for suf in suffixes)


def scan_file(path: Path) -> list[Finding]:
    """Run every applicable rule against the file content and return
    findings. Mirrors `provenance_patterns.scan_file` semantics, with
    extra per-rule pass-2 logic for the two-stage rules.

    Rules with custom pass-2 logic (handled inline here):
      * `sbom-lockfile-resolved-non-registry` — captured URL must NOT
        contain any allowlist substring.
      * `sbom-cargo-lock-replace-with` — captured value must NOT match
        an allowlist mirror name.
      * `sbom-frozen-lockfile-skip-on-publish` — captured install line
        must NOT contain any guard token, AND the file must contain a
        publisher token (Stage-1 publisher gate).
      * `sbom-release-from-non-tag-ref` — negative-substring check
        already covers the tagged-release tokens (default flow).

    Composite rules (NOT routed through scan_file — call the matching
    composite helper):
      * `sbom-npm-provenance-digest-mismatch` →
        `compare_npm_provenance_digests`
      * `sbom-pom-classifier-version-mismatch` →
        `scan_pom_classifier_mismatch`
      * `sbom-spdx-license-stripped` → `scan_spdx_stripped_dir`
      * `sbom-license-file-mit-but-vendor-gpl` →
        `scan_license_mit_vendor_gpl`
      * `sbom-helm-chart-lock-digest-missing` →
        `scan_helm_chart_lock_missing_digests`

    Errors during read return an empty list — the detector path must
    not crash on a permission denied / binary file / partial read.
    """
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not content:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    path_str = str(path)

    cl_cached: str | None = None  # cached lowercase content (built once)
    npm_registry_allow = _npm_registry_allowlist()
    cargo_mirror_allow = _cargo_mirror_allowlist()

    # Composite-only rules are skipped here — the caller invokes the
    # composite helper directly. Rule 8 / 10 / 14 / 15 are composite;
    # Rule 6 is also composite (pair-comparison).
    composite_only = {
        "sbom-npm-provenance-digest-mismatch",
        "sbom-pom-classifier-version-mismatch",
        "sbom-spdx-license-stripped",
        "sbom-license-file-mit-but-vendor-gpl",
        "sbom-helm-chart-lock-digest-missing",
    }

    for rule in RULES:
        if rule.id in composite_only:
            continue
        if not _file_matches_suffixes(path, rule.file_suffixes):
            continue

        # Negative-substring suppression — checked against the FULL
        # lowercased file content (case-insensitive, plain substring).
        if rule.negative_substrings:
            if cl_cached is None:
                cl_cached = content.lower()
            if any(neg.lower() in cl_cached
                   for neg in rule.negative_substrings):
                continue

        # Rule-specific publisher-token gate (mirrors
        # `provenance_patterns._REQUIRED_SUBSTRINGS`).
        if rule.id == "sbom-frozen-lockfile-skip-on-publish":
            if cl_cached is None:
                cl_cached = content.lower()
            if not any(tok.lower() in cl_cached
                       for tok in _REPRO_PUBLISHER_TOKENS):
                continue

        for m in rule.pattern.finditer(content):
            line, col = _line_col(content, m.start())

            # Pass-2 logic for rules that need it.
            if rule.id == "sbom-lockfile-resolved-non-registry":
                url = m.group(1) if m.lastindex else m.group(0)
                if any(allowed.lower() in url.lower()
                       for allowed in npm_registry_allow):
                    continue
            elif rule.id == "sbom-cargo-lock-replace-with":
                value = m.group(1) if m.lastindex else m.group(0)
                if any(allowed.lower() == value.lower().strip()
                       for allowed in cargo_mirror_allow):
                    continue
            elif rule.id == "sbom-frozen-lockfile-skip-on-publish":
                captured = m.group(1) if m.lastindex else m.group(0)
                if any(guard.lower() in captured.lower()
                       for guard in _FROZEN_GUARDS):
                    continue

            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)

            matched = m.group(0).strip()
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                file_path=path_str,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
