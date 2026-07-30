"""Provenance / SBOM / release-verification regex catalogue.

Wave 16 implementation of the distill2-f deep-dive proposals
(reports/study-github-monitoring-deep2/20260527_184033+0200-distill2-f-
provenance-sbom.md). Pattern-only port — the eight proposed rules are
encoded as RULES tuples with line-scoped, RE2-safe regexes and an
optional substring "negative-check" list that callers run against the
full file content. When the positive regex hits AND none of the negative
substrings appear in the file, the rule fires.

Sources reviewed (per distill report):

  * macaron (`build_as_code`, provenance verifier) — SLSA-level and
    in-toto attestation evidence checks.
  * sigstore-conformance — cosign verify / verify-blob shapes.
  * supply-chain-guardian `action_integrity_monitor.py` — tag-SHA drift
    and release-asset checksum-drift heuristics.
  * `r3dlight/phantom-tarball` — XZ-style release-tarball-vs-git-tag
    divergence shape (rule lives in this module; the tarball-diff
    detector is opt-in and ships separately).
  * GitHub-native attestations docs (`actions/attest-*`,
    `slsa-github-generator/.github/workflows/generator_*.yml`).
  * anchore/sbom-action, CycloneDX, syft, microsoft/sbom-tool — the
    canonical SBOM-generator inventory.

Hard constraints (verified):

  * Deterministic — pure file/line regex, no network, no shell-out, no
    LLM.
  * RE2-safe — every alternation uses `(?:...)`, no lookaround, no
    backrefs. The patterns DO use `re.IGNORECASE | re.MULTILINE`; that
    is the Python default flag set the existing janitor patterns
    catalogue uses (`agent_config_patterns.py::_re`). The detector
    paths are line-scoped, NOT span-greedy, so RE2 fall-back doesn't
    matter for the pattern shape itself.
  * Severity vocabulary mirrors the janitor's existing 4-tier set:
    CRITICAL / HIGH / MAJOR / MINOR. No MEDIUM.
  * Pure-stdlib (re + NamedTuple). Loads in any PEP 723 detector script
    block without third-party deps.

Public surface:

  * Rule(id, name, severity, description, pattern, negative_substrings,
        file_glob)
      - single rule record. Patterns are PRE-COMPILED at module load.
      - `negative_substrings`: tuple of bytes-or-str substrings that
        SUPPRESS the rule when they appear ANYWHERE in the file. Empty
        tuple = positive match always fires.
      - `file_glob`: tuple of glob fragments the file path must end
        with (e.g. (".yml", ".yaml")). Empty tuple = any file.
  * RULES — ordered tuple of every rule.
  * Finding(rule_id, line, column, matched_text, severity, description,
            file_path) — single match. Frozen tuple.
  * scan_file(path: Path) -> list[Finding] — apply every applicable
    rule to one file; consider negative-substring suppression.

The negative-substring two-pass shape comes from the existing
`workflow-security.py` two-pass detector flow: positive regex hit on a
specific line + same-file substring scan to confirm that NO mitigating
counter-tooling appears anywhere in the workflow. Substring scans are
PLAIN `bytes-in-bytes` lookups, not regexes — keeps the rule
deterministic AND avoids surprises from regex engine differences.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single provenance-rule match. Same NamedTuple shape used by
    every other janitor pattern catalogue so render code can treat
    findings uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    file_path: str  # absolute path of the file the finding came from


class Rule(NamedTuple):
    """A provenance-rule definition. Patterns are PRE-COMPILED at module
    load. `negative_substrings` are checked against the FULL FILE
    content; if any of them appear, the rule's positive matches are
    suppressed (the file contains a mitigating tool / verifier /
    counter-action that makes the positive match a false alarm)."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    negative_substrings: tuple[str, ...]
    # File-suffix filter (e.g. (".yml", ".yaml") for workflow files).
    # Empty tuple = any file. Suffixes are lowercased before comparison.
    file_suffixes: tuple[str, ...]
    # Regex mitigations, for when a plain substring cannot express the
    # difference between enabling a control and DISABLING it. `provenance:`
    # is the motivating case: as a substring it also matches
    # `provenance: false`, which would suppress the finding on a workflow
    # that explicitly turned the attestation OFF — a false negative on a
    # supply-chain control, strictly worse than the false positive being
    # fixed. Defaulted so every existing rule is untouched.
    negative_patterns: tuple[re.Pattern, ...] = ()  # noqa: UP006 — keep stdlib name


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE. Provenance
    rules scan YAML workflows + JSON metadata; YAML keys are
    case-sensitive but the human-typed values often are not. Multiline
    is needed because `$` should anchor at line ends, not file end."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Rule patterns ------------------------------------------------------


# Rule 1 — prov-missing-cosign-verify-on-download (MAJOR)
#
# Workflow downloads a binary release asset (gh release download, curl /
# wget against a release-binary URL, or one of the well-known CDNs) AND
# the same workflow file lacks any documented release-asset verifier
# (cosign verify, slsa-verifier, gh attestation verify, sigstore-
# conformance, cosign-installer).
_PROV_COSIGN_DOWNLOAD = _re(
    r"(?:gh\s+release\s+download"
    r"|curl[^\n]{0,200}github\.com/[^\n]+/releases/download/"
    r"|wget[^\n]{0,200}github\.com/[^\n]+/releases/download/"
    r"|curl[^\n]{0,200}(?:dl\.k8s\.io|cli\.github\.com|releases\.hashicorp\.com|get\.helm\.sh|download\.docker\.com)"
    r"|wget[^\n]{0,200}(?:dl\.k8s\.io|cli\.github\.com|releases\.hashicorp\.com|get\.helm\.sh|download\.docker\.com)"
    r")"
)

_COSIGN_VERIFIERS = (
    "cosign verify",
    "cosign-installer",
    "slsa-verifier verify",
    "slsa-verifier-installer",
    "gh attestation verify",
    "sigstore-conformance",
)


# Rule 2 — prov-npm-publish-without-provenance (HIGH)
#
# A line invokes `npm publish` (or pnpm 8+ / yarn berry equivalent) and
# the SAME file lacks both the `--provenance` flag AND any
# `NPM_CONFIG_PROVENANCE` env. RE2-safe; the negative-substring scan
# handles the "is provenance enabled anywhere in this file" question.
# FP-hardening (round 3): tightened to require workflow STEP context.
# The unanchored shape fired on prose like *"npm publish without
# provenance"* inside README threat-research notes and on test-helper
# shell scripts (`tests/test-private-proxy.sh`). The fix is two-fold:
# (a) the rule's file_suffixes is already `.yml`/`.yaml` (caller-side
# scoping); (b) the regex now requires the publish to appear inside a
# YAML run-step context — either directly after `- run:` on the same
# logical step, OR inside a `run: |` multi-line block scalar. The
# `(?:^|\s)` keeps the prefix anchor for the publish-command body.
_PROV_NPM_PUBLISH = _re(
    # Shape 1: `- run: npm publish ...` on one line (single-line step).
    r"^[\s]*-?\s*run:\s*(?:npm|pnpm|yarn)\s+publish\b[^\n]*$"
    # Shape 2: multi-line `run: |` block scalar containing `npm publish ...`
    # within the next 400 chars. (Unlike the secret-attribution case — see
    # rules_injection.py::SecretBareInRun, moved structural in issue #24 — a
    # run:-window bleed here is benign: `npm publish` in a sibling step IS still
    # a publish in a run somewhere, so a provenance check on it is not a FP.)
    r"|run:[ \t]*[|>][^\n]*\n(?:[\s\S]{0,400}?)(?:^|\s)(?:npm|pnpm|yarn)\s+publish\b[^\n]*$"
)

_NPM_PROVENANCE_TOKENS = (
    "--provenance",
    "NPM_CONFIG_PROVENANCE",
    "npm_config_provenance",
)


# Rule 3 — prov-sbom-absent-but-release-built (MAJOR)
#
# Workflow file invokes a release-publisher (softprops/action-gh-release,
# ncipollo/release-action, actions/upload-release-asset, goreleaser-
# action, pypa/gh-action-pypi-publish, gh release create) AND the file
# never mentions any SBOM generator (anchore/sbom-action, syft,
# CycloneDX/*, microsoft/sbom-tool, cyclonedx-cli, spdx-sbom-generator).
_PROV_RELEASE_NO_SBOM = _re(
    r"(?:uses:\s*softprops/action-gh-release@"
    r"|uses:\s*ncipollo/release-action@"
    r"|uses:\s*actions/upload-release-asset@"
    r"|uses:\s*goreleaser/goreleaser-action@"
    r"|uses:\s*pypa/gh-action-pypi-publish@"
    r"|\bgh\s+release\s+create\b)"
)

_SBOM_TOOLS = (
    "anchore/sbom-action",
    "CycloneDX/",
    "cyclonedx-",
    "syft",
    "microsoft/sbom-tool",
    "spdx-sbom-generator",
    # Lowercase too — IGNORECASE on regex but plain-substring scan is
    # case-sensitive, so include the common case variants explicitly.
    "anchore/sbom",
    "cyclonedx",
)


# Rule 4 — prov-in-toto-attestation-missing-on-build (MAJOR)
#
# Workflow ships an artifact (Docker push, gh release upload, PyPI
# publish, softprops release) AND lacks any in-toto attestation
# (actions/attest-build-provenance, actions/attest-sbom, actions/attest,
# slsa-github-generator reusable workflow, or a raw `cosign attest`).
_PROV_INTOTO_MISSING = _re(
    r"(?:docker\s+push\s+(?:ghcr\.io|docker\.io)/"
    r"|uses:\s*pypa/gh-action-pypi-publish@"
    r"|uses:\s*softprops/action-gh-release@"
    r"|uses:\s*docker/build-push-action@)"
)

_INTOTO_TOKENS = (
    "actions/attest-build-provenance",
    "actions/attest-sbom",
    "actions/attest@",
    "slsa-github-generator/.github/workflows/generator_",
    "cosign attest",
)

# BuildKit emits SLSA provenance natively, so `docker/build-push-action` with
# `provenance:` enabled ALREADY attaches an in-toto attestation — no separate
# attest step is needed, and demanding one was a false positive (janitor#99).
#
# Enumerating the ENABLING spellings is deliberate: the inverse (a substring
# `provenance:`, or a negative lookahead for `false`) would also suppress the
# finding on `provenance: false`, which is a workflow explicitly DISABLING the
# attestation — precisely the case that most needs to be reported. `mode=max` is
# the stronger setting of the two (full build steps + materials), not a weaker
# variant of `true`.
_PROV_BUILDKIT_ATTESTATION = _re(
    r"""provenance:\s*["']?(?:true|mode\s*=\s*(?:min|max))"""
)


# Rule 5 — prov-slsa-level-below-floor (MAJOR)
#
# Repo declares its SLSA level (in `.slsa/level.json`, a workflow header
# comment, security.txt with `Slsa-Build-Level:`, or an OpenSSF Scorecard
# markdown). The pattern only EXTRACTS the declared level; the caller
# compares against the configured floor (env knob
# JANITOR_OPT_SLSA_FLOOR, default 2). Patterns must capture exactly ONE
# digit 0-3 in a numbered group.
_PROV_SLSA_LEVEL = _re(
    r'(?:"slsa[_ -]?level"\s*:\s*"?(?P<l1>[0-3])"?'
    r"|slsa[- ]?build[- ]?level\s*[:=]\s*L?(?P<l2>[0-3])\b"
    r"|Slsa-Build-Level:\s*L?(?P<l3>[0-3])\b"
    r"|slsa[- ]?level\s*:\s*L?(?P<l4>[0-3])\b)"
)


# Rule 6 — prov-reproducible-build-flag-absent (MINOR)
#
# A build command runs in a workflow but omits a documented reproducible-
# build flag. Different tools have different flag names; the line-scoped
# positive match catches the command shape, and the same-step substring
# check (left to the detector — we expose only the positive regex) is
# what confirms the flag is missing. Five common tools covered:
#
#   * cargo --release without --locked
#   * go build without -trimpath
#   * docker build without SOURCE_DATE_EPOCH
#   * npm install (instead of npm ci) — non-reproducible install
#   * pip install without --require-hashes
_PROV_REPRO_BUILD = _re(
    r"(?:^|\s)(?:cargo\s+(?:build|test|install)\s+[^\n]*--release\b"
    r"|\bgo\s+build\b[^\n]*-o\s+\S+"
    r"|^[^\n]*\bdocker\s+build\b[^\n]*"
    r"|^[^\n]*\bnpm\s+install\b[^\n]*"
    r"|^[^\n]*\bpnpm\s+install\b[^\n]*"
    r"|^[^\n]*\bpip\s+install\b[^\n]*)"
)

_REPRO_TOKENS = (
    "--locked",
    "-trimpath",
    "SOURCE_DATE_EPOCH",
    "npm ci",
    "pnpm ci",
    "--frozen-lockfile",
    "--require-hashes",
)


# FP-hardening (round 3): the reproducible-build rule was the
# noisiest in the catalogue (~30 FPs / repo) — every `pip install`,
# `npm install`, and `docker build` line in any CI workflow fired,
# but reproducible builds only MATTER when the workflow also
# PUBLISHES an artefact (otherwise it's just a CI test install and
# reproducibility is irrelevant). The tokens below indicate the
# workflow is a PUBLISHER and the reproducible-build rule should
# apply. If none appear in the same file, the rule is suppressed by
# `scan_file`.
_REPRO_PUBLISHER_TOKENS = (
    # JavaScript / TypeScript publishers
    "npm publish",
    "pnpm publish",
    "yarn publish",
    "JS-DevTools/npm-publish",
    # Python publishers
    "twine upload",
    "pypa/gh-action-pypi-publish",
    "poetry publish",
    "flit publish",
    "uv publish",
    # Ruby
    "gem push",
    # Rust
    "cargo publish",
    # Java
    "mvn deploy",
    "gradle publish",
    # .NET
    "dotnet nuget push",
    # Docker
    "docker push",
    "docker buildx build",
    # GitHub release
    "gh release create",
    "gh release upload",
    "softprops/action-gh-release",
    "ncipollo/release-action",
    "goreleaser/goreleaser-action",
    "actions/upload-release-asset",
    "actions/upload-artifact",
    # Container registries / image publishing actions
    "docker/build-push-action",
)


# Per-rule positive-required-substring map. A rule appearing in this
# dict only fires when AT LEAST ONE of its substrings ALSO appears in
# the same file. Rules NOT in this dict run unconditionally.
# FP-hardening (round 3).
_REQUIRED_SUBSTRINGS: dict[str, tuple[str, ...]] = {
    "prov-reproducible-build-flag-absent": _REPRO_PUBLISHER_TOKENS,
}


# Rule 7 — prov-trusted-publishing-missing (MAJOR)
#
# PyPI / npm / cargo publishing without trusted-publishing — uses an
# API token-based publish flow instead of OIDC-trusted publishing. The
# pattern matches the publish action; the negative-check substrings are
# the OIDC trusted-publishing markers (`id-token: write`,
# `permissions: id-token`).
_PROV_TRUSTED_PUBLISH = _re(
    r"(?:uses:\s*pypa/gh-action-pypi-publish@"
    r"|uses:\s*JS-DevTools/npm-publish@"
    r"|uses:\s*cycjimmy/semantic-release-action@)"
)

_TRUSTED_PUB_TOKENS = (
    "id-token: write",
    "id-token:write",
    "permissions: id-token",
    "permissions:id-token",
    # The OIDC permission can be a multi-line block — check for the
    # action's documented config keys.
    "trusted-publishing",
)


# Rule 8 — prov-release-asset-no-checksum (MAJOR)
#
# A workflow uploads release assets but never generates a sha256
# checksum file alongside them. Negative check: presence of
# `sha256sum`, `shasum`, `Get-FileHash`, or `goreleaser` (goreleaser
# always emits checksums.txt automatically).
_PROV_RELEASE_CHECKSUM = _re(
    r"(?:uses:\s*softprops/action-gh-release@"
    r"|uses:\s*ncipollo/release-action@"
    r"|uses:\s*actions/upload-release-asset@"
    r"|\bgh\s+release\s+upload\b)"
)

_CHECKSUM_TOKENS = (
    "sha256sum",
    "shasum",
    "Get-FileHash",
    "goreleaser",
    # CycloneDX SBOMs already carry component hashes — count those.
    "cyclonedx-",
    # signed checksum manifests
    "checksums.txt",
    "SHA256SUMS",
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="prov-missing-cosign-verify-on-download",
        name="Release asset downloaded without signature verification",
        severity="MAJOR",
        description=(
            "Workflow downloads a binary from a release URL but the same "
            "file never invokes cosign / slsa-verifier / gh attestation "
            "verify. An attacker who tampers with the asset lands "
            "directly inside CI. Add a verification step."
        ),
        pattern=_PROV_COSIGN_DOWNLOAD,
        negative_substrings=_COSIGN_VERIFIERS,
        file_suffixes=(".yml", ".yaml"),
    ),
    Rule(
        id="prov-npm-publish-without-provenance",
        name="npm/pnpm/yarn publish without Sigstore provenance",
        severity="HIGH",
        description=(
            "`npm publish` ran without `--provenance` / "
            "`NPM_CONFIG_PROVENANCE=true`. The published tarball will "
            "lack a Sigstore-signed provenance statement. With "
            "GitHub-native trusted publishing this is one flag."
        ),
        pattern=_PROV_NPM_PUBLISH,
        negative_substrings=_NPM_PROVENANCE_TOKENS,
        file_suffixes=(".yml", ".yaml"),
    ),
    Rule(
        id="prov-sbom-absent-but-release-built",
        name="Release published without an SBOM",
        severity="MAJOR",
        description=(
            "Workflow publishes a release but never produces an SBOM "
            "(CycloneDX/SPDX). Downstream consumers and security "
            "scanners can't reason about the artefact's dependency "
            "tree. Add `anchore/sbom-action` (or `syft`, `CycloneDX/*`) "
            "and upload the SBOM as a release asset."
        ),
        pattern=_PROV_RELEASE_NO_SBOM,
        negative_substrings=_SBOM_TOOLS,
        file_suffixes=(".yml", ".yaml"),
    ),
    Rule(
        id="prov-in-toto-attestation-missing-on-build",
        name="Build artifact produced without an in-toto attestation",
        severity="MAJOR",
        description=(
            "Workflow produces a release artefact (container image / "
            "PyPI wheel / GitHub release asset) but never attaches an "
            "in-toto build provenance attestation. Add "
            "`uses: actions/attest-build-provenance@v1` after the "
            "upload step, or wrap the build in slsa-github-generator."
        ),
        pattern=_PROV_INTOTO_MISSING,
        negative_substrings=_INTOTO_TOKENS,
        file_suffixes=(".yml", ".yaml"),
        negative_patterns=(_PROV_BUILDKIT_ATTESTATION,),
    ),
    Rule(
        id="prov-slsa-level-declared",
        name="SLSA build level declaration",
        severity="MAJOR",
        description=(
            "Project declares its SLSA build level. The detector "
            "compares this against the configured floor "
            "(JANITOR_OPT_SLSA_FLOOR, default 2); declarations below "
            "the floor surface as a finding."
        ),
        pattern=_PROV_SLSA_LEVEL,
        negative_substrings=(),
        file_suffixes=(),  # any file — .json/.md/.txt/.yml all qualify
    ),
    Rule(
        id="prov-reproducible-build-flag-absent",
        name="Build step missing reproducibility flag",
        severity="MINOR",
        description=(
            "Build step omits a reproducibility flag (cargo `--locked`, "
            "go `-trimpath`, docker `SOURCE_DATE_EPOCH`, npm `ci` "
            "instead of `install`, pip `--require-hashes`). Builds "
            "will differ between runs even from the same commit — "
            "defeats SLSA L3 verification."
        ),
        pattern=_PROV_REPRO_BUILD,
        negative_substrings=_REPRO_TOKENS,
        file_suffixes=(".yml", ".yaml"),
    ),
    Rule(
        id="prov-trusted-publishing-missing",
        name="Package publish action without OIDC trusted publishing",
        severity="MAJOR",
        description=(
            "Workflow publishes to PyPI / npm using a long-lived API "
            "token instead of OIDC trusted publishing. A leaked token "
            "can be reused for malicious releases until manually "
            "rotated. Use trusted publishing with "
            "`permissions: id-token: write`."
        ),
        pattern=_PROV_TRUSTED_PUBLISH,
        negative_substrings=_TRUSTED_PUB_TOKENS,
        file_suffixes=(".yml", ".yaml"),
    ),
    Rule(
        id="prov-release-asset-no-checksum",
        name="Release upload without sha256 checksum manifest",
        severity="MAJOR",
        description=(
            "Workflow uploads release assets but never generates a "
            "sha256 checksum manifest (sha256sum / shasum / "
            "Get-FileHash / checksums.txt). Downstream consumers can't "
            "verify integrity. Either compute checksums explicitly or "
            "switch to goreleaser which emits them automatically."
        ),
        pattern=_PROV_RELEASE_CHECKSUM,
        negative_substrings=_CHECKSUM_TOKENS,
        file_suffixes=(".yml", ".yaml"),
    ),
)


# ---- Scan helpers -------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_matches_suffixes(path: Path, suffixes: tuple[str, ...]) -> bool:
    """Empty suffix tuple → any file. Otherwise check that the path's
    name ends with one of the suffixes (case-insensitive)."""
    if not suffixes:
        return True
    name = path.name.lower()
    return any(name.endswith(suf.lower()) for suf in suffixes)


def scan_file(path: Path) -> list[Finding]:
    """Run every applicable rule against the file content and return
    findings. The two-pass shape:

      1. POSITIVE: rule.pattern.finditer(content) — line-scoped regex.
      2. NEGATIVE: if ANY of rule.negative_substrings appears in the
         full file content, suppress all positive matches for that rule.

    Rule scoping: rule.file_suffixes filters which files this rule
    applies to (e.g. only `.yml`/`.yaml` for the workflow-targeted
    rules). An empty file_suffixes tuple means "any file".

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

    cl_cached: str | None = None  # cached lowercase content (only build once)

    for rule in RULES:
        if not _file_matches_suffixes(path, rule.file_suffixes):
            continue
        # Negative-substring suppression: if any documented mitigation
        # token appears ANYWHERE in the file, skip this rule entirely.
        # Case-insensitive plain substring (matches the regex `_re()`
        # IGNORECASE policy) — workflow YAMLs are written in mixed case
        # and we want every spelling variant.
        if rule.negative_substrings:
            if cl_cached is None:
                cl_cached = content.lower()
            if any(neg.lower() in cl_cached for neg in rule.negative_substrings):
                continue
        # Same suppression, for mitigations a substring cannot express (see
        # `Rule.negative_patterns`). Searched against the ORIGINAL content, not
        # the lowercased cache — the patterns carry their own IGNORECASE.
        if rule.negative_patterns and any(
            neg.search(content) for neg in rule.negative_patterns
        ):
            continue
        # FP-hardening (round 3): per-rule positive-required-substring
        # check. The reproducible-build rule fires N times per `npm
        # install` line — but reproducible builds only matter when the
        # workflow ALSO publishes an artefact. If the file lacks any
        # publisher token, the rule's positive matches are not actually
        # actionable findings; suppress the whole rule.
        required = _REQUIRED_SUBSTRINGS.get(rule.id)
        if required:
            if cl_cached is None:
                cl_cached = content.lower()
            if not any(req.lower() in cl_cached for req in required):
                continue
        for m in rule.pattern.finditer(content):
            line, col = _line_col(content, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            # Strip leading whitespace from the matched line so the
            # rendered finding reads cleanly. Cap at 200 chars.
            matched = matched.strip()
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


def extract_slsa_levels(text: str) -> list[tuple[int, int]]:
    """Return every SLSA-level declaration found in `text`, as a list
    of (level, line) pairs. Used by the detector to compare against
    JANITOR_OPT_SLSA_FLOOR.

    The regex `_PROV_SLSA_LEVEL` has four named groups (l1..l4) for the
    four declaration shapes; this helper picks whichever fired."""
    out: list[tuple[int, int]] = []
    if not text:
        return out
    for m in _PROV_SLSA_LEVEL.finditer(text):
        # Find the group that actually matched.
        for name in ("l1", "l2", "l3", "l4"):
            val = m.group(name)
            if val is not None:
                line, _ = _line_col(text, m.start())
                out.append((int(val), line))
                break
    return out
