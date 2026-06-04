"""Git-LFS / large-binary artifact poisoning patterns (Wave 19, round 5-D).

Detects the **content-bearing artifact** family of git supply-chain
attacks where the *committed pointer* and the *resolved bytes* can
diverge:

  * LFS pointer-file integrity (`oid sha256:` divergence, `size` OOM)
  * `.lfsconfig` URL hijacks (off-org `lfs.url`, custom transfer RCE)
  * `.gitattributes` LFS-filter sneaks (blanket `* filter=lfs`)
  * GitHub Releases asset poisoning (mutable URLs, missing checksum
    sidecars, `releases/latest/download/` redirects)
  * `actions/upload-artifact` / `download-artifact` cross-workflow
    smuggling (no `name:` filter on `workflow_run`, untrusted-input
    artifact names)
  * Submodule remote URL rewrites (CVE-2024-32002 class)
  * `git archive --prefix=../` path traversal
  * `git bundle` smuggling (unverified ingest)
  * `lfs.fetchinclude` / `fetchexclude` scope expansion

This module is the **content-bearing artifact** sibling of Wave 17's
`git_ops_patterns.py`, which already covers the **git-config-layer**
attack surface (hooks, refs, credential helpers, `core.sshCommand`).
Both modules share the `Finding` / `Rule` shape so detectors render
either output uniformly.

Rules (1:1 with proposals 1..15 in `reports/distill-round-5/git-lfs-artifact.md`):

| id                                          | severity | watched file/text             |
|---------------------------------------------|----------|-------------------------------|
| git-lfs-pointer-malformed                   | HIGH     | LFS pointer files             |
| git-lfs-pointer-size-implausible            | MEDIUM   | LFS pointer files             |
| git-lfs-pointer-size-zero                   | LOW      | LFS pointer files             |
| git-lfs-lfsconfig-url-offorg                | CRITICAL | `.lfsconfig`, `.gitconfig`    |
| git-lfs-lfsconfig-custom-transfer           | CRITICAL | `.lfsconfig`, `.gitconfig`    |
| git-lfs-lfsconfig-standalone-transfer       | CRITICAL | `.lfsconfig`, `.gitconfig`    |
| git-lfs-gitattributes-blanket-filter        | CRITICAL | `.gitattributes`              |
| git-lfs-gitattributes-source-extension      | HIGH     | `.gitattributes`              |
| git-lfs-skip-smudge-in-ci                   | HIGH     | workflow YAML / shell scripts |
| git-lfs-release-no-checksum-sidecar         | HIGH     | workflow YAML                 |
| git-lfs-install-latest-redirect             | HIGH     | shell scripts                 |
| git-lfs-install-asset-no-checksum           | HIGH     | shell scripts                 |
| git-lfs-prerelease-default-tag              | HIGH     | workflow YAML                 |
| git-lfs-upload-artifact-untrusted-name      | HIGH     | workflow YAML                 |
| git-lfs-download-artifact-no-name-filter    | CRITICAL | workflow YAML                 |
| git-lfs-gitmodules-suspicious-url           | CRITICAL | `.gitmodules`                 |
| git-lfs-gitmodules-relative-escape          | HIGH     | `.gitmodules`                 |
| git-lfs-archive-prefix-traversal            | HIGH     | shell scripts                 |
| git-lfs-archive-prefix-untrusted            | HIGH     | shell scripts                 |
| git-lfs-bundle-ingest-unverified            | MEDIUM   | shell scripts                 |
| git-lfs-fetchexclude-removed                | MEDIUM   | `.lfsconfig` diff             |
| git-lfs-fetchinclude-widened                | MEDIUM   | `.lfsconfig` diff             |

Public surface (mirrors `git_ops_patterns.py`):
  * `Rule`, `Finding` NamedTuples
  * `RULES` — ordered tuple
  * `scan_text(text, *, file_kind)` — entry point
  * Helper gates: `parse_lfs_pointer`, `is_lfs_host_allowed`,
    `is_dangerous_glob`, `is_source_extension_glob`,
    `is_release_asset_url`, `parse_gitmodules_urls`,
    `audit_gitattributes_diff`, `audit_lfs_fetch_scope_diff`

`file_kind` controls which subset of rules runs:
  * `lfs-pointer`     → pointer-file integrity rules
  * `lfsconfig`       → `.lfsconfig` content (and `[lfs]` sections in `.gitconfig`)
  * `gitattributes`   → `.gitattributes` content
  * `gitmodules`      → `.gitmodules` content
  * `workflow`        → GitHub Actions workflow YAML
  * `shell`           → shell scripts / `run:` blocks
  * `any` (default)   → run every rule; caller filters by file path
"""

from __future__ import annotations

import re
from typing import NamedTuple
from urllib.parse import urlsplit

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as `git_ops_patterns.Finding` so
    detectors can render either module's output uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are pre-compiled at import time."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - stdlib name
    owasp_asi: str
    # Which file_kind values this rule applies to. "any" matches every kind.
    applies_to: frozenset[str]


def _re(pattern: str) -> re.Pattern:
    """Compile a regex with MULTILINE+UNICODE. Case-sensitivity matters
    for git/yaml/url grammar — IGNORECASE is deliberately omitted."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- Proposal 1: LFS pointer-file shape ---------------------------------


# Canonical LFS pointer file. Anchored at start-of-string. The pointer
# spec REQUIRES the version URL, then `oid sha256:<64 hex>`, then
# `size <digits>`, in that exact order. Trailing newline optional.
# The 64-hex `oid` and the bounded `size` digits keep this RE2-safe —
# no nested quantifiers, no catastrophic backtracking.
#
# Pattern is BYTES-based: pointer files are ASCII on disk and we want
# to fail closed on stray non-ASCII bytes (rather than silently decode
# with replacement characters and accept a malformed pointer). All
# call sites pass `bytes`.
LFS_POINTER_RE: re.Pattern[bytes] = re.compile(
    rb"\Aversion https://git-lfs\.github\.com/spec/v1\n"
    rb"oid sha256:([0-9a-f]{64})\n"
    rb"size (\d{1,20})\n?\Z"
)


# Inside a regular text scan, this fires when we see what LOOKS like a
# pointer file header but the body diverges (e.g. truncated, extra
# garbage lines, wrong version URL). The single quantifier `\d{1,20}`
# is bounded — no ReDoS.
_LFS_POINTER_HEADER = _re(
    r"^version[ \t]+https://git-lfs\.[A-Za-z0-9.-]+/spec/v\d{1,3}[ \t]*$"
)


# ---- Proposal 2: `.lfsconfig` URL hijack --------------------------------


# Capture any `url = <value>` line inside `.lfsconfig`. The detector
# applies the host allowlist to the captured value. Same shape as
# the Wave 17 gitmodules URL extractor — keep consistent.
# Combined `url = …` / `pushurl = …` matcher. Both fields point at the
# LFS server (`pushurl` is the asymmetric write-path); a hijacked value
# in either is equally dangerous. RE2-safe alternation.
_LFSCONFIG_URL = _re(
    r"^[ \t]*url[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$"
    r"|^[ \t]*pushurl[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$"
)


# `lfs.customtransfer.<name>.path = <binary>` — direct RCE primitive
# identical in shape to `core.fsmonitor`. Section-aware detection is
# handled by the caller; this matches the `path = ...` line itself.
_LFSCONFIG_CUSTOM_TRANSFER = _re(
    r"^[ \t]*path[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$"
)


# Section header that introduces a `customtransfer` block. The detector
# pairs this with `_LFSCONFIG_CUSTOM_TRANSFER` to scope the path= rule.
_LFSCONFIG_CUSTOM_TRANSFER_SECTION = _re(
    r'^[ \t]*\[lfs[ \t]+"customtransfer\.[A-Za-z0-9_.-]{1,64}"\][ \t]*$'
)


# `standalonetransferagent` — same RCE shape; an arbitrary command name
# that LFS invokes. Captured for severity tiering against allowlist.
_LFSCONFIG_STANDALONE_AGENT = _re(
    r"^[ \t]*standalonetransferagent[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$"
)


# Default LFS hosts considered safe. Detectors that ship a project
# allowlist should call `is_lfs_host_allowed(host, extra=...)`.
_LFS_DEFAULT_ALLOWED_HOSTS: frozenset[str] = frozenset({
    "github.com",
    "lfs.github.com",
    "git-lfs.github.com",
})


# ---- Proposal 3: blanket `* filter=lfs` in `.gitattributes` -------------


# Capture every `<glob> filter=<name>` line so the detector can compare
# the glob against the danger set. The capture group is the glob, the
# second group is the filter name. Bounded character classes only.
_GITATTRIBUTES_LFS_LINE = _re(
    r"^[ \t]*([^\s#][^\s]{0,500})[ \t]+[^\n#]*?filter[ \t]*=[ \t]*([A-Za-z0-9_.-]+)"
)


# The literal danger set — these globs route the entire repository
# through the LFS filter when paired with `filter=lfs`.
_DANGEROUS_LFS_GLOBS: frozenset[str] = frozenset({"*", "**", "**/*", "**/**"})


# Source-extension regex. We deliberately enumerate the canonical
# build-system extensions — anything that lands here is being routed
# through LFS where it doesn't belong (source code lives in git,
# binaries live in LFS, not the reverse).
_SOURCE_EXT_RE = re.compile(
    r"^\*\.(?:py|pyi|js|jsx|ts|tsx|mjs|cjs|go|rs|java|kt|kts|scala|c|h|cc|cpp|cxx|hh|hpp|rb|sh|bash|zsh|fish|php|swift|m|mm|dart|lua|r|jl|el|clj|cljs|hs|ml|fs|cs|vb|sql|md|yaml|yml|toml|json|xml|html|css|scss|sass|less|vue|svelte)$"
)


# ---- Proposal 4: `--skip-smudge` / `GIT_LFS_SKIP_SMUDGE` in CI ---------


# Matches both shell-form (`GIT_LFS_SKIP_SMUDGE=1`) and YAML-form
# (`GIT_LFS_SKIP_SMUDGE: 1`) env-var assignments, plus the CLI form
# `git lfs install --skip-smudge`. Bounded character classes only —
# no nested quantifiers, no catastrophic backtracking. The OR-bar
# alternations are flat (each branch has a single bounded body).
_LFS_SKIP_SMUDGE_ANY = _re(
    # Shell env-var: GIT_LFS_SKIP_SMUDGE=1 / =true
    r"GIT_LFS_SKIP_SMUDGE[ \t]*=[ \t]*['\"]?(?:1|true|TRUE|True)\b"
    # YAML env-var: GIT_LFS_SKIP_SMUDGE: 1 / : true
    r"|GIT_LFS_SKIP_SMUDGE:[ \t]*['\"]?(?:1|true|TRUE|True)\b"
    # CLI form: `git lfs install --skip-smudge` — bounded body
    # between `install` and `--skip-smudge` (≤200 chars, no newlines).
    r"|git[ \t]+lfs[ \t]+install\b[^\n]{0,200}--skip-smudge\b"
)


# Matches `actions/checkout@<sha-or-tag>` followed within a small window
# by `lfs: false`. The window is bounded (<=10 short lines, each <=120
# chars) to keep this RE2-safe. We anchor on `uses:` because in YAML
# `uses:` always precedes `with:` for the same step.
_CHECKOUT_LFS_FALSE = _re(
    r"uses:[ \t]*actions/checkout@[^\r\n]{1,200}\r?\n"
    r"(?:[ \t]{0,20}[A-Za-z0-9_#.-][^\r\n]{0,200}\r?\n){0,10}"
    r"[ \t]{0,20}lfs:[ \t]*false\b"
)


# ---- Proposal 7: release-asset publish without checksum sidecar --------


# Capture `softprops/action-gh-release@<ref>` usage. The detector
# inspects sibling `run:` blocks for sha256sum / cosign / gpg.
_GH_RELEASE_USES = _re(
    r"uses:[ \t]*softprops/action-gh-release@([A-Za-z0-9_.-]{1,80})"
)


# Detects checksum-emission patterns in any nearby `run:` block.
# The negative side: if `_GH_RELEASE_USES` fires but this does NOT
# match anywhere in the same job, flag the missing sidecar.
_CHECKSUM_EMITTER_RE = re.compile(
    r"(?:sha256sum|shasum[ \t]+-a[ \t]+256|openssl[ \t]+dgst[ \t]+-sha256|"
    r"cosign[ \t]+sign-blob|cosign[ \t]+attest|slsa-github-generator)\b"
)


# ---- Proposal 8: install scripts pulling /releases/latest/download ----


# `releases/latest/download/` is the mutable-tag redirect. Both the
# tag mapping AND the asset bytes can rotate after a tag is "published".
_LATEST_DOWNLOAD_RE = _re(
    r"https://github\.com/[A-Za-z0-9_.-]{1,60}/[A-Za-z0-9_.-]{1,80}/releases/latest/download/[^\s\"'<>]{1,300}"
)


# Any `releases/download/<tag>/<asset>` URL — captures the tag so the
# detector can also flag `latest`-equivalents (`main`, `master`,
# `develop` are also moving targets even though `gh release create`
# accepts them as ref names).
_RELEASE_DOWNLOAD_RE = _re(
    r"https://github\.com/[A-Za-z0-9_.-]{1,60}/[A-Za-z0-9_.-]{1,80}/releases/download/([A-Za-z0-9_.-]{1,80})/[^\s\"'<>]{1,300}"
)


# Mutable-ref names that should trip the same severity as `latest`.
_MUTABLE_RELEASE_REFS: frozenset[str] = frozenset({
    "latest", "main", "master", "develop", "trunk", "edge", "nightly",
    "preview", "canary", "rolling", "head", "HEAD",
})


# Checksum-verifier shapes that, when present anywhere in the script,
# satisfy the "verified" requirement. Bounded character classes —
# RE2-safe.
_CHECKSUM_VERIFIER_RE = re.compile(
    r"(?:sha256sum[ \t]+-c|shasum[ \t]+-(?:a[ \t]+256[ \t]+)?-c|"
    r"openssl[ \t]+dgst[ \t]+-sha256[ \t]+[^\n]{0,200}[ \t]+-verify|"
    r"gpg[ \t]+--verify|cosign[ \t]+verify-blob|"
    r"minisign[ \t]+-V|signify[ \t]+-V)\b"
)


# ---- Proposal 9: prerelease=true with default `npm publish` ------------


# Capture `prerelease: true` from a workflow's `with:` block. The
# detector then searches for a subsequent `npm publish` without `--tag`.
_PRERELEASE_TRUE = _re(
    r"^[ \t]{0,40}prerelease:[ \t]*(['\"]?true['\"]?|yes|YES)[ \t]*$"
)


# Any `npm publish` line. The detector flags it iff `prerelease: true`
# appeared earlier in the workflow AND no `--tag` follows.
_NPM_PUBLISH_RE = _re(
    r"\bnpm[ \t]+publish\b([^\n]{0,400})"
)


# ---- Proposal 10: upload-artifact with untrusted name -----------------


# Captures `name:` value from an `upload-artifact` step. The detector
# checks the captured value against the untrusted-input set.
_UPLOAD_ARTIFACT_USES = _re(
    r"uses:[ \t]*actions/upload-artifact@[^\r\n]{1,200}"
)


_UPLOAD_ARTIFACT_NAME_RE = _re(
    r"^[ \t]{0,40}name:[ \t]*['\"]?([^\r\n'\"]{1,300}?)['\"]?[ \t]*$"
)


# Untrusted-input references — these GitHub event fields are
# attacker-controlled in `pull_request` / `pull_request_target` /
# `issue_comment` triggers. Bounded character classes throughout.
_UNTRUSTED_GH_INPUT_RE = re.compile(
    r"\$\{\{[ \t]*github\.event\.(?:"
    r"pull_request\.title|pull_request\.body|pull_request\.head\.ref|"
    r"issue\.title|issue\.body|"
    r"comment\.body|review\.body|"
    r"head_ref|"
    r"workflow_run\.head_branch|workflow_run\.head_commit\.message"
    r")[ \t]*\}\}"
    r"|\$\{\{[ \t]*github\.head_ref[ \t]*\}\}"
)


# ---- Proposal 11: download-artifact in workflow_run no name filter ---


_DOWNLOAD_ARTIFACT_USES = _re(
    r"uses:[ \t]*actions/download-artifact@[^\r\n]{1,200}"
)


# Captures the workflow trigger block start. We detect `workflow_run`
# / `pull_request_target` by line-scanning rather than parsing YAML
# — the detector takes the full text and looks for the trigger.
# Trigger sentinels MUST be at indent 0 or 2 (top-level `on:` block).
_WORKFLOW_RUN_TRIGGER = _re(
    r"^(?:on:[ \t]*\r?\n[ \t]{2,8})?workflow_run:[ \t]*$"
    r"|^[ \t]{2,8}workflow_run:[ \t]*$"
)


_PR_TARGET_TRIGGER = _re(
    r"^(?:on:[ \t]*\r?\n[ \t]{2,8})?pull_request_target:[ \t]*$"
    r"|^[ \t]{2,8}pull_request_target:[ \t]*$"
)


# A `name:` line scoped to a download-artifact step. We treat this as
# a presence signal — if the step has no `name:`, the artifact filter
# is wide open and any artifact in the run is downloaded.
_DOWNLOAD_ARTIFACT_NAME_PRESENT = _re(
    r"^[ \t]{0,40}name:[ \t]*['\"]?[A-Za-z0-9_.-]{1,200}['\"]?[ \t]*$"
)


# ---- Proposal 12: submodule URL rewrite / off-allowlist ---------------


# `.gitmodules` section header — captures the submodule name. Bounded.
_GITMODULES_SECTION = _re(
    r'^\[submodule[ \t]+"([^"\r\n]{1,200})"\][ \t]*$'
)


# `url = <value>` line inside `.gitmodules` — same as Wave 17, kept
# locally to keep modules import-independent.
_GITMODULES_URL_LINE = _re(
    r"^[ \t]*url[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$"
)


# Relative URLs starting with `../../` escape the parent org via the
# remote's default config — flagged separately because the URL itself
# may *look* internal but resolve attacker-side.
_RELATIVE_ESCAPE_URL_RE = re.compile(r"^\.\./\.\.(?:/|$)")


# ---- Proposal 13: `git archive --prefix=...` traversal ----------------


# Captures the prefix value (single- or double-quoted, or bare). The
# `[^\s'"]{0,200}` keeps this bounded. Real prefixes rarely exceed
# 60 chars — 200 is generous.
_GIT_ARCHIVE_PREFIX_RE = _re(
    r"git[ \t]+archive\b[^\n]{0,500}?--prefix[ \t]*[= ][ \t]*"
    r"(?:'([^'\r\n]{0,300})'|\"([^\"\r\n]{0,300})\"|([^\s\r\n'\"]{1,300}))"
)


# Traversal patterns inside the captured prefix.
_PREFIX_TRAVERSAL_RE = re.compile(r"\.\.[\\/]|^/|^\\")


# Untrusted interpolation patterns inside a shell/yaml prefix.
_PREFIX_UNTRUSTED_RE = re.compile(
    r"\$\{\{[ \t]*github\.(?:event\.|head_ref|ref_name|"
    r"event\.inputs\.|event\.client_payload\.)[^\}]{0,200}\}\}"
    r"|\$(?:GITHUB_HEAD_REF|GITHUB_REF_NAME|INPUT_[A-Z0-9_]{1,80})\b"
)


# ---- Proposal 14: `git bundle` unverified ingest ----------------------


# Any `git clone|fetch|bundle unbundle` consuming a `.bundle` file.
_BUNDLE_INGEST_RE = _re(
    r"git[ \t]+(?:clone|fetch|bundle[ \t]+unbundle)[ \t]+[^\n]{0,500}\.bundle\b"
)


# Verification primitive — `git bundle verify` MUST appear in the same
# script (the detector enforces "anywhere in the same text").
_BUNDLE_VERIFY_RE = re.compile(r"git[ \t]+bundle[ \t]+verify\b")


# ---- Proposal 15: `lfs.fetchexclude` / `fetchinclude` (diff-aware) ----


# Captures the key=value pair for the two scope keys. Returned as a
# dict by `audit_lfs_fetch_scope_diff` below.
_LFS_FETCH_EXCLUDE_RE = _re(
    r"^[ \t]*fetchexclude[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$"
)
_LFS_FETCH_INCLUDE_RE = _re(
    r"^[ \t]*fetchinclude[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$"
)


# ---- The catalogue ------------------------------------------------------


# Rule ordering = severity DESC then proposal order. The first finding
# rendered to a developer is also the most severe.
RULES: tuple[Rule, ...] = (
    Rule(
        id="git-lfs-lfsconfig-url-offorg",
        name="`.lfsconfig` `lfs.url` points off-org",
        severity="CRITICAL",
        description=(
            "`.lfsconfig` overrides the LFS endpoint to an attacker-controlled "
            "host. Every `git lfs pull` resolves bytes from that host while "
            "the committed pointer SHA stays unchanged — bytes rotate, audit "
            "trail does not. Same risk surface as Wave 17 `core.sshCommand` "
            "RCE."
        ),
        pattern=_LFSCONFIG_URL,
        owasp_asi="",
        applies_to=frozenset({"lfsconfig", "any"}),
    ),
    Rule(
        id="git-lfs-lfsconfig-custom-transfer",
        name="`lfs.customtransfer.<name>.path` defined (RCE primitive)",
        severity="CRITICAL",
        description=(
            "`lfs.customtransfer.<name>.path` is an arbitrary binary path "
            "that LFS invokes for every blob transfer. Identical RCE shape "
            "as `core.fsmonitor` (Wave 17, C-4) — any non-empty value is "
            "a finding."
        ),
        pattern=_LFSCONFIG_CUSTOM_TRANSFER,
        owasp_asi="",
        applies_to=frozenset({"lfsconfig", "any"}),
    ),
    Rule(
        id="git-lfs-lfsconfig-standalone-transfer",
        name="`lfs.standalonetransferagent` defined (RCE primitive)",
        severity="CRITICAL",
        description=(
            "`lfs.standalonetransferagent` names a transfer agent binary "
            "that LFS shells out to. Like `customtransfer.path`, any value "
            "is a finding — the default LFS install never sets this key."
        ),
        pattern=_LFSCONFIG_STANDALONE_AGENT,
        owasp_asi="",
        applies_to=frozenset({"lfsconfig", "any"}),
    ),
    Rule(
        id="git-lfs-gitattributes-blanket-filter",
        name="`.gitattributes` declares blanket `* filter=lfs` (or similar)",
        severity="CRITICAL",
        description=(
            "`* filter=lfs` (or `**`, `**/*`) routes EVERY file through the "
            "LFS smudge/clean filter. The next `git lfs migrate import` "
            "moves all source code into the LFS server — silently rotatable "
            "from there. CVE-2022-39253 class."
        ),
        pattern=_GITATTRIBUTES_LFS_LINE,
        owasp_asi="",
        applies_to=frozenset({"gitattributes", "any"}),
    ),
    Rule(
        id="git-lfs-gitattributes-source-extension",
        name="`.gitattributes` routes a source extension through LFS",
        severity="HIGH",
        description=(
            "`.gitattributes` routes a recognised source-code extension "
            "(`*.py`, `*.js`, `*.go`, ...) through `filter=lfs`. Source "
            "belongs in git, binaries belong in LFS — the reverse is a "
            "supply-chain pivot."
        ),
        pattern=_GITATTRIBUTES_LFS_LINE,
        owasp_asi="",
        applies_to=frozenset({"gitattributes", "any"}),
    ),
    Rule(
        id="git-lfs-skip-smudge-in-ci",
        name="`GIT_LFS_SKIP_SMUDGE=1` / `--skip-smudge` in CI",
        severity="HIGH",
        description=(
            "Skipping the LFS smudge filter in CI means subsequent build / "
            "test steps see literal pointer file contents instead of the "
            "real bytes. Either silent failure (tests pass against junk "
            "content) or active exploit (loader pre-allocates the "
            "attacker-controlled `size` field)."
        ),
        pattern=_LFS_SKIP_SMUDGE_ANY,
        owasp_asi="",
        applies_to=frozenset({"workflow", "shell", "any"}),
    ),
    Rule(
        id="git-lfs-release-no-checksum-sidecar",
        name="`softprops/action-gh-release` without checksum sidecar generation",
        severity="HIGH",
        description=(
            "GitHub Releases asset uploads are mutable — bytes can be "
            "re-uploaded under the same name. Every release publish step "
            "must emit a `*.sha256` sidecar AND record it in the release "
            "body or a signed attestation (cosign, slsa-github-generator)."
        ),
        pattern=_GH_RELEASE_USES,
        owasp_asi="",
        applies_to=frozenset({"workflow", "any"}),
    ),
    Rule(
        id="git-lfs-install-latest-redirect",
        name="install script pulls `releases/latest/download/` (mutable redirect)",
        severity="HIGH",
        description=(
            "`releases/latest/download/<asset>` always resolves to the "
            "currently-latest release — both tag and bytes are mutable. "
            "Install scripts must pin a specific tag AND verify the "
            "asset's SHA256."
        ),
        pattern=_LATEST_DOWNLOAD_RE,
        owasp_asi="",
        applies_to=frozenset({"shell", "workflow", "any"}),
    ),
    Rule(
        id="git-lfs-install-asset-no-checksum",
        name="release-asset download with no checksum verification",
        severity="HIGH",
        description=(
            "Any `https://github.com/.../releases/download/<tag>/<asset>` "
            "URL in an install script must be followed (in the same script) "
            "by `sha256sum -c` / `shasum -c` / `openssl dgst -verify` / "
            "`gpg --verify` / `cosign verify-blob` / `minisign -V`."
        ),
        pattern=_RELEASE_DOWNLOAD_RE,
        owasp_asi="",
        applies_to=frozenset({"shell", "workflow", "any"}),
    ),
    Rule(
        id="git-lfs-prerelease-default-tag",
        name="`prerelease: true` paired with default `npm publish`",
        severity="HIGH",
        description=(
            "Workflow marks the GitHub Release as a prerelease but then "
            "calls `npm publish` without `--tag` — the package lands on "
            "the default `latest` dist-tag, contradicting the GitHub-side "
            "prerelease badge. Version-channel confusion attack."
        ),
        pattern=_PRERELEASE_TRUE,
        owasp_asi="",
        applies_to=frozenset({"workflow", "any"}),
    ),
    Rule(
        id="git-lfs-upload-artifact-untrusted-name",
        name="`actions/upload-artifact` `name:` interpolates untrusted input",
        severity="HIGH",
        description=(
            "Artifact `name:` derived from `github.event.*` (PR title, "
            "branch name, comment body) is attacker-controlled. Lets a "
            "malicious PR collide with a trusted artifact name and "
            "smuggle bytes into the next workflow_run."
        ),
        pattern=_UPLOAD_ARTIFACT_NAME_RE,
        owasp_asi="",
        applies_to=frozenset({"workflow", "any"}),
    ),
    Rule(
        id="git-lfs-download-artifact-no-name-filter",
        name="`actions/download-artifact` in `workflow_run` without `name:` filter",
        severity="CRITICAL",
        description=(
            "Trusted workflow downloads ALL artifacts the triggering PR "
            "uploaded — attacker-controlled bytes land in the runner's "
            "workspace, where subsequent steps may execute them. Kill-chain "
            "link 1 of every modern Actions compromise (TanStack 2025, "
            "@antv worm 2026-05)."
        ),
        pattern=_DOWNLOAD_ARTIFACT_USES,
        owasp_asi="",
        applies_to=frozenset({"workflow", "any"}),
    ),
    Rule(
        id="git-lfs-gitmodules-suspicious-url",
        name="`.gitmodules` URL points off-allowlist (rewrite or hijack)",
        severity="CRITICAL",
        description=(
            "`.gitmodules` URL changed from the upstream host to an "
            "off-allowlist host. PR diff focus on code may miss this. "
            "CVE-2024-32002 / CVE-2024-32004 class — submodule clone "
            "primitive enables symlink-and-hook RCE on the runner."
        ),
        pattern=_GITMODULES_URL_LINE,
        owasp_asi="",
        applies_to=frozenset({"gitmodules", "any"}),
    ),
    Rule(
        id="git-lfs-gitmodules-relative-escape",
        name="`.gitmodules` URL uses `../../` (escapes parent org)",
        severity="HIGH",
        description=(
            "A `.gitmodules` URL starting with `../../` resolves relative "
            "to the parent remote's URL — when the parent is on a shared "
            "host, the relative path escapes the org boundary and may "
            "land on an attacker-owned repo."
        ),
        pattern=_GITMODULES_URL_LINE,
        owasp_asi="",
        applies_to=frozenset({"gitmodules", "any"}),
    ),
    Rule(
        id="git-lfs-archive-prefix-traversal",
        name="`git archive --prefix=` contains `..` or absolute path",
        severity="HIGH",
        description=(
            "`git archive --prefix=../<x>/` produces a tarball that, on "
            "naive extract, writes files outside the target directory. "
            "Targets: `../../etc/cron.d/...`, `../.ssh/authorized_keys`."
        ),
        pattern=_GIT_ARCHIVE_PREFIX_RE,
        owasp_asi="",
        applies_to=frozenset({"shell", "workflow", "any"}),
    ),
    Rule(
        id="git-lfs-archive-prefix-untrusted",
        name="`git archive --prefix=` interpolates untrusted input",
        severity="HIGH",
        description=(
            "`git archive --prefix=${{ github.event.pull_request.title }}/` "
            "lets a malicious PR title smuggle `../` into the tarball "
            "prefix. Even if the prefix string itself looks clean today, "
            "an attacker-supplied future value is a traversal primitive."
        ),
        pattern=_GIT_ARCHIVE_PREFIX_RE,
        owasp_asi="",
        applies_to=frozenset({"shell", "workflow", "any"}),
    ),
    Rule(
        id="git-lfs-bundle-ingest-unverified",
        name="`git bundle` ingest without `git bundle verify` or digest check",
        severity="MEDIUM",
        description=(
            "Scripts that `git clone <file>.bundle` / `git fetch <file>.bundle` "
            "without a preceding `git bundle verify` and a sha256/gpg check "
            "trust attacker-supplied refs — bundles can rewrite "
            "`refs/heads/main` at clone time."
        ),
        pattern=_BUNDLE_INGEST_RE,
        owasp_asi="",
        applies_to=frozenset({"shell", "workflow", "any"}),
    ),
    Rule(
        id="git-lfs-pointer-malformed",
        name="LFS pointer file is malformed (header present, body broken)",
        severity="HIGH",
        description=(
            "File header looks like an LFS pointer (`version "
            "https://git-lfs.../spec/v1`) but the full body does NOT match "
            "the canonical `oid sha256:<64hex>\\nsize <digits>` shape. "
            "Either a truncated/corrupted pointer (silent build failure) "
            "or a smuggle attempt (extra lines after the size, garbage "
            "before the oid)."
        ),
        pattern=_LFS_POINTER_HEADER,
        owasp_asi="",
        applies_to=frozenset({"lfs-pointer", "any"}),
    ),
)


# ---- Helper exports for callers ----------------------------------------


def parse_lfs_pointer(content: bytes) -> tuple[str, int] | None:
    """Parse an LFS pointer file. Return `(oid_hex, size_int)` on a
    clean canonical pointer, else None.

    `content` is bytes because pointer files are technically binary —
    but in practice they're ASCII. We validate strictly: non-ASCII
    bytes mean malformed and fail closed.
    """
    # Pre-check that the content is ASCII-only. The match itself
    # operates on bytes so we don't pay the decode cost twice — but
    # we still want to reject high bytes early.
    try:
        content.decode("ascii")
    except UnicodeDecodeError:
        return None
    m = LFS_POINTER_RE.match(content)
    if not m:
        return None
    return (m.group(1).decode("ascii"), int(m.group(2)))


def is_lfs_host_allowed(
    host: str | None,
    *,
    extra_allowed: frozenset[str] = frozenset(),
) -> bool:
    """Return True if `host` is on the default LFS allowlist (or the
    caller-supplied `extra_allowed`).

    Default allowlist is intentionally tiny — `github.com` and its
    LFS subdomains. Self-hosted LFS endpoints MUST be passed via
    `extra_allowed`.
    """
    if not host:
        return False
    h = host.strip().lower()
    if h in _LFS_DEFAULT_ALLOWED_HOSTS:
        return True
    return h in {x.lower() for x in extra_allowed}


def is_dangerous_glob(glob: str) -> bool:
    """Return True if `glob` is one of the literal danger patterns
    (`*`, `**`, `**/*`, `**/**`) that routes the entire repo through
    LFS when paired with `filter=lfs`."""
    return glob.strip() in _DANGEROUS_LFS_GLOBS


def is_source_extension_glob(glob: str) -> bool:
    """Return True if `glob` matches a recognised source-code extension
    pattern (e.g. `*.py`, `*.ts`, `*.go`). Source code belongs in git
    proper, not behind the LFS filter."""
    return _SOURCE_EXT_RE.match(glob.strip()) is not None


def is_release_asset_url(url: str) -> bool:
    """Return True if `url` looks like a GitHub Releases download URL
    (either pinned `/releases/download/<tag>/<asset>` or mutable
    `/releases/latest/download/<asset>`)."""
    u = url.strip()
    return bool(_RELEASE_DOWNLOAD_RE.match(u) or _LATEST_DOWNLOAD_RE.match(u))


def is_mutable_release_ref(ref: str) -> bool:
    """Return True if `ref` is one of the canonical mutable refs
    (`latest`, `main`, `develop`, etc.)."""
    return ref.strip() in _MUTABLE_RELEASE_REFS


def has_checksum_emitter(text: str) -> bool:
    """Return True if `text` contains at least one checksum-generation
    primitive (`sha256sum`, `cosign sign-blob`, etc.)."""
    return _CHECKSUM_EMITTER_RE.search(text) is not None


def has_checksum_verifier(text: str) -> bool:
    """Return True if `text` contains at least one checksum-verification
    primitive (`sha256sum -c`, `gpg --verify`, etc.)."""
    return _CHECKSUM_VERIFIER_RE.search(text) is not None


def has_bundle_verify(text: str) -> bool:
    """Return True if `text` calls `git bundle verify` anywhere."""
    return _BUNDLE_VERIFY_RE.search(text) is not None


def parse_gitmodules_urls(text: str) -> dict[str, str]:
    """Parse `.gitmodules` content. Return `{submodule_name: url}`.

    Submodule entries without a URL are skipped. The parser walks
    section-by-section in a single pass — RE2-safe.
    """
    out: dict[str, str] = {}
    current_name: str | None = None
    for line in text.splitlines():
        m_section = _GITMODULES_SECTION.match(line)
        if m_section:
            current_name = m_section.group(1)
            continue
        if current_name is None:
            continue
        m_url = _GITMODULES_URL_LINE.match(line)
        if m_url:
            out[current_name] = m_url.group(1).strip()
    return out


def _extract_gitattributes_lfs_globs(text: str) -> set[str]:
    """Return the set of glob patterns that route through `filter=lfs`
    in the given `.gitattributes` content. Comment lines (`#`) and
    blank lines are skipped automatically by the regex."""
    out: set[str] = set()
    for m in _GITATTRIBUTES_LFS_LINE.finditer(text):
        glob = m.group(1)
        filter_name = m.group(2)
        if filter_name == "lfs":
            out.add(glob)
    return out


def audit_gitattributes_diff(pre: str, post: str) -> list[str]:
    """Diff-aware audit. Return a list of human-readable findings for
    any newly-added LFS glob that is dangerous (blanket) or routes a
    source extension through LFS. Removed globs are ignored — those
    only reduce LFS coverage."""
    findings: list[str] = []
    pre_globs = _extract_gitattributes_lfs_globs(pre)
    post_globs = _extract_gitattributes_lfs_globs(post)
    added = post_globs - pre_globs
    for glob in sorted(added):
        if is_dangerous_glob(glob):
            findings.append(f".gitattributes: blanket LFS filter added: {glob}")
        elif is_source_extension_glob(glob):
            findings.append(f".gitattributes: source extension routed through LFS: {glob}")
    return findings


def _extract_lfs_fetch_scope(text: str) -> tuple[str | None, str | None]:
    """Return (fetchexclude, fetchinclude) values from an `.lfsconfig`
    block, or (None, None) when not set."""
    excl = None
    incl = None
    for m in _LFS_FETCH_EXCLUDE_RE.finditer(text):
        excl = m.group(1).strip()
        break
    for m in _LFS_FETCH_INCLUDE_RE.finditer(text):
        incl = m.group(1).strip()
        break
    return (excl, incl)


def audit_lfs_fetch_scope_diff(pre: str, post: str) -> list[str]:
    """Diff-aware audit of `.lfsconfig` fetch-scope keys. Flags:
      * `fetchexclude` removed → broader fetch scope
      * `fetchinclude` widened to wildcard
    """
    findings: list[str] = []
    pre_excl, pre_incl = _extract_lfs_fetch_scope(pre)
    post_excl, post_incl = _extract_lfs_fetch_scope(post)
    if pre_excl and not post_excl:
        findings.append("lfs.fetchexclude removed — broader fetch scope")
    if pre_incl and post_incl and post_incl != pre_incl:
        if "*" in post_incl and "*" not in pre_incl:
            findings.append("lfs.fetchinclude widened to wildcard — pulls all LFS blobs")
    return findings


def url_host(url: str) -> str | None:
    """Helper — parse a URL and return the lowercased hostname.
    Returns None for un-parseable URLs."""
    try:
        u = urlsplit(url.strip())
    except (ValueError, AttributeError):
        return None
    if not u.hostname:
        return None
    return u.hostname.lower()


# ---- Scanner ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _trigger_present(text: str) -> bool:
    """Return True if the workflow text declares either `workflow_run`
    or `pull_request_target` as a trigger."""
    return (
        _WORKFLOW_RUN_TRIGGER.search(text) is not None
        or _PR_TARGET_TRIGGER.search(text) is not None
    )


def _custom_transfer_section_present(text: str, line_offset: int) -> bool:
    """Return True if a `[lfs "customtransfer.<name>"]` section header
    appears anywhere BEFORE `line_offset` in `text`. Section-aware
    gating for the `path =` rule."""
    return _LFSCONFIG_CUSTOM_TRANSFER_SECTION.search(text[:line_offset]) is not None


def scan_text(
    text: str,
    *,
    file_kind: str = "any",
    extra_allowed_lfs_hosts: frozenset[str] = frozenset(),
) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` selects which rule subset to apply (mirrors the
    file-on-disk routing the heartbeat detector does):

    * `lfs-pointer`    — LFS pointer file content
    * `lfsconfig`      — `.lfsconfig` (and `[lfs]` sections in `.gitconfig`)
    * `gitattributes`  — `.gitattributes` content
    * `gitmodules`     — `.gitmodules`
    * `workflow`       — GitHub Actions workflow YAML
    * `shell`          — shell scripts / `run:` blocks
    * `any` (default)  — run every rule; caller routes by file path

    `extra_allowed_lfs_hosts` extends the default LFS host allowlist
    (`github.com`, `lfs.github.com`, `git-lfs.github.com`) — pass the
    self-hosted Gitea/GitLab origin used by the project.
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    # Pre-compute lookups used by multiple rule gates so we don't
    # re-search the same text once per rule. The `prerelease: true`
    # match is checked per-match in the prerelease rule (which needs
    # the offset for the `npm publish` window), so it's not hoisted.
    trigger_present = _trigger_present(text) if file_kind in ("workflow", "any") else False
    has_verifier = has_checksum_verifier(text)
    has_emitter = has_checksum_emitter(text)
    has_verify_bundle = has_bundle_verify(text)

    for rule in RULES:
        if file_kind != "any" and file_kind not in rule.applies_to:
            continue
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue

            # Per-rule gates — keep regex shape simple, gate in Python
            # so each gate is independently unit-testable.
            captured = m.group(1) if m.groups() else ""

            if rule.id == "git-lfs-lfsconfig-url-offorg":
                host = url_host(captured)
                if host is None:
                    # un-parseable URL is still suspicious — fall through
                    pass
                elif is_lfs_host_allowed(host, extra_allowed=extra_allowed_lfs_hosts):
                    continue

            elif rule.id == "git-lfs-lfsconfig-custom-transfer":
                # `path = ...` only fires when scoped inside a
                # `[lfs "customtransfer.<name>"]` section. Otherwise
                # the same line is just a benign config value
                # (e.g. inside `[remote "origin"]`).
                if not _custom_transfer_section_present(text, m.start()):
                    continue

            elif rule.id == "git-lfs-gitattributes-blanket-filter":
                # capture group 1 = glob, capture group 2 = filter name.
                if len(m.groups()) < 2:
                    continue
                glob = captured.strip()
                filter_name = m.group(2).strip()
                if filter_name != "lfs":
                    continue
                if not is_dangerous_glob(glob):
                    continue

            elif rule.id == "git-lfs-gitattributes-source-extension":
                if len(m.groups()) < 2:
                    continue
                glob = captured.strip()
                filter_name = m.group(2).strip()
                if filter_name != "lfs":
                    continue
                if not is_source_extension_glob(glob):
                    continue
                # Don't double-flag dangerous globs that already
                # tripped the blanket rule.
                if is_dangerous_glob(glob):
                    continue

            elif rule.id == "git-lfs-release-no-checksum-sidecar":
                if has_emitter:
                    continue

            elif rule.id == "git-lfs-install-asset-no-checksum":
                if has_verifier:
                    continue
                # If this URL points at `latest`, the latest-redirect
                # rule already fired — avoid duplicate noise.
                tag = captured.strip()
                if is_mutable_release_ref(tag):
                    continue

            elif rule.id == "git-lfs-prerelease-default-tag":
                # The prerelease-true line itself is not the finding —
                # the bug is the *combination* of prerelease=true PLUS
                # a downstream `npm publish` without `--tag`.
                npm_match = _NPM_PUBLISH_RE.search(text, m.end())
                if not npm_match:
                    continue
                tail = npm_match.group(1) or ""
                if "--tag" in tail:
                    continue

            elif rule.id == "git-lfs-upload-artifact-untrusted-name":
                # capture is the `name:` value. The detector requires
                # an `actions/upload-artifact@` step header within a
                # small window before the name line.
                if _UPLOAD_ARTIFACT_USES.search(text[:m.start()][-1500:]) is None:
                    continue
                if _UNTRUSTED_GH_INPUT_RE.search(captured) is None:
                    continue

            elif rule.id == "git-lfs-download-artifact-no-name-filter":
                # Only fires inside a `workflow_run` or
                # `pull_request_target` workflow.
                if not trigger_present:
                    continue
                # Check if a `name:` directive appears within ~10 lines
                # AFTER the `uses:` step header.
                window = text[m.end():m.end() + 800]
                if _DOWNLOAD_ARTIFACT_NAME_PRESENT.search(window):
                    continue

            elif rule.id == "git-lfs-gitmodules-suspicious-url":
                host = url_host(captured)
                # Reuse the LFS allowlist by default. Real allowlist
                # per-project flows via `extra_allowed_lfs_hosts`.
                if host is not None and is_lfs_host_allowed(
                    host, extra_allowed=extra_allowed_lfs_hosts
                ):
                    continue
                # Don't double-flag relative-escape URLs (they have
                # their own rule).
                if _RELATIVE_ESCAPE_URL_RE.match(captured.strip()):
                    continue
                # Skip plausible `git@github.com:owner/repo.git` SSH form.
                if captured.strip().startswith("git@"):
                    # Allow the standard SSH-form for allowlisted hosts.
                    ssh_host_match = re.match(
                        r"^git@([A-Za-z0-9.-]+):", captured.strip()
                    )
                    if ssh_host_match and is_lfs_host_allowed(
                        ssh_host_match.group(1), extra_allowed=extra_allowed_lfs_hosts
                    ):
                        continue

            elif rule.id == "git-lfs-gitmodules-relative-escape":
                if not _RELATIVE_ESCAPE_URL_RE.match(captured.strip()):
                    continue

            elif rule.id == "git-lfs-archive-prefix-traversal":
                # capture groups: ('quoted-1', 'quoted-2', 'bare')
                groups = [g for g in m.groups() if g]
                if not groups:
                    continue
                prefix = groups[0]
                if not _PREFIX_TRAVERSAL_RE.search(prefix):
                    continue

            elif rule.id == "git-lfs-archive-prefix-untrusted":
                groups = [g for g in m.groups() if g]
                if not groups:
                    continue
                prefix = groups[0]
                # Avoid double-firing with the traversal rule on the
                # same span — traversal wins (it is the actionable
                # finding; the untrusted-input rule is the warning).
                if _PREFIX_TRAVERSAL_RE.search(prefix):
                    continue
                if not _PREFIX_UNTRUSTED_RE.search(prefix):
                    continue

            elif rule.id == "git-lfs-bundle-ingest-unverified":
                # Suppress if EITHER a verify call OR a checksum verifier
                # is present in the script.
                if has_verify_bundle and has_verifier:
                    continue

            elif rule.id == "git-lfs-pointer-malformed":
                # Header was present at this offset. If the FULL file
                # matches the canonical shape, this is benign.
                # The pointer regex operates on bytes — re-encode the
                # caller's text once at the gate.
                if LFS_POINTER_RE.match(text.encode("utf-8", errors="replace")):
                    continue
                # Header only fires when LFS_POINTER_HEADER matched —
                # that already gates "this looks like a pointer file".

            elif rule.id == "git-lfs-install-latest-redirect":
                # No further gating — the URL shape itself is the
                # finding (mutable redirect, always bad).
                pass

            elif rule.id == "git-lfs-skip-smudge-in-ci":
                # Bare match is the finding. No gate.
                pass

            elif rule.id == "git-lfs-lfsconfig-standalone-transfer":
                # Any value is a finding (default install does not set
                # this key). No gate.
                pass

            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))

    # Second pass: `actions/checkout` with `lfs: false` — same skip-
    # smudge attack class but in YAML step form rather than CLI / env.
    # Emits under the same rule.id as the CLI variant.
    if file_kind in ("workflow", "any"):
        skip_rule = next(
            (r for r in RULES if r.id == "git-lfs-skip-smudge-in-ci"),
            None,
        )
        if skip_rule is not None:
            for m in _CHECKOUT_LFS_FALSE.finditer(text):
                line, col = _line_col(text, m.start())
                key = (skip_rule.id, line, col)
                if key in seen:
                    continue
                seen.add(key)
                matched = m.group(0)
                display = matched[:200] + "…" if len(matched) > 200 else matched
                findings.append(Finding(
                    rule_id=skip_rule.id,
                    line=line,
                    column=col,
                    matched_text=display,
                    severity=skip_rule.severity,
                    description=skip_rule.description,
                    owasp_asi=skip_rule.owasp_asi,
                ))

    # Second pass: pointer-file size sanity (proposals 5 + the LOW zero
    # check). These run only in `lfs-pointer` mode because they care
    # about the *parsed* size, not the regex match position.
    if file_kind in ("lfs-pointer", "any"):
        parsed = parse_lfs_pointer(text.encode("utf-8", errors="replace"))
        if parsed is not None:
            _, size = parsed
            if size > MAX_PLAUSIBLE_LFS_SIZE:
                findings.append(Finding(
                    rule_id="git-lfs-pointer-size-implausible",
                    line=3, column=1,
                    matched_text=f"size {size}",
                    severity="MEDIUM",
                    description=(
                        f"LFS pointer claims size {size} which exceeds the "
                        f"plausibility ceiling ({MAX_PLAUSIBLE_LFS_SIZE} = "
                        "2 GiB). Naive clients may pre-allocate this much "
                        "memory and OOM the host."
                    ),
                    owasp_asi="",
                ))
            elif size == 0:
                findings.append(Finding(
                    rule_id="git-lfs-pointer-size-zero",
                    line=3, column=1,
                    matched_text=f"size {size}",
                    severity="LOW",
                    description=(
                        "LFS pointer claims size 0. Likely a truncation "
                        "marker or copy-paste artefact — not necessarily "
                        "malicious but always wrong."
                    ),
                    owasp_asi="",
                ))

    # Fetch-scope diffing is callable on its own (`audit_lfs_fetch_scope_diff`)
    # — not folded into single-text scan because we need pre+post.

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


# Reasonable upper bound: 2 GiB. Tune per project via the caller.
# Real-world LFS use rarely stores blobs larger than this — most CI/CD
# tooling chokes on a 4 GiB+ download anyway.
MAX_PLAUSIBLE_LFS_SIZE: int = 2 * 1024 * 1024 * 1024
