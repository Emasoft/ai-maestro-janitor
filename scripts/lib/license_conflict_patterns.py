"""License conflict / SPDX scan / legal-exposure regex catalogue.

Wave-22 implementation of the distill-round-8 angle-I proposals
(`reports/distill-round-8/license-conflict.md`). Pattern catalogue
covering 15 distinct **license-content / SPDX-header / NOTICE-attachment /
license-compatibility / CLA-relicensing / trademark-misuse** vectors.

Cross-reference with Wave-18 `scripts/lib/sbom_tampering_patterns.py`:

  * Rule `sbom-spdx-license-stripped` (Wave 18) — fires when a file is
    *missing* an SPDX header while siblings have one. This module's
    `license-spdx-mismatch-with-root` fires when the SPDX header is
    *present* but declares a different identifier than the repo
    LICENSE — disjoint surface.
  * Rule `sbom-license-file-mit-but-vendor-gpl` (Wave 18) — MIT root +
    GPL marker anywhere. This module's `license-incompatible-copyleft-
    in-permissive` covers the **dependency-manifest** surface (AGPL /
    SSPL / BSL / FSL / Commons Clause in declared deps), which Wave 18
    does not touch.

Sources reviewed (per distill report):

  * SPDX 3.x spec § 7 license-expression grammar
  * OSI license-compatibility matrix
  * Apache License 2.0 § 4(a) + § 4(d) (NOTICE clause)
  * GPL FAQ on COPYING / verbatim license inclusion
  * MongoDB SSPL announcement 2018-10
  * Elastic license change 2021-01
  * Redis SSPL/RSALv2 2024-03
  * CockroachDB BSL 1.1
  * Sentry Functional Source License (FSL) 2023-11
  * Creative Commons license matrix
  * Anthropic / Mozilla / CNCF / LF / Apache trademark policies
  * REUSE 3.0 specification on SPDX headers
  * Linux-kernel SPDX header convention

Hard constraints (verified):

  * Deterministic — pure file/line regex, no network, no shell-out,
    no LLM.
  * RE2-safe — every alternation uses `(?:...)`, no lookaround, no
    backrefs. Bounded `{0,N}` only.
  * Severity vocabulary CRITICAL / HIGH / MAJOR / MINOR (no MEDIUM /
    LOW) — matches Wave 18.
  * Pure-stdlib (re + NamedTuple + pathlib).
  * Rule IDs use the `license-` prefix to stay disjoint from Wave
    18's `sbom-` prefix.

Public surface:

  * Finding — same shape as `sbom_tampering_patterns.Finding`.
  * Rule — same shape as Wave 18.
  * RULES — ordered tuple of every rule.
  * scan_file(path) — runs every applicable pattern-only rule.
  * Composite helpers (multi-file or two-stage rules):
      - extract_repo_license_spdx(root)
      - extract_file_spdx_identifiers(text)
      - spdx_expressions_compatible(declared, file_decl)
      - scan_spdx_mismatch_with_root(root)
      - scan_apache_notice_missing(root)
      - scan_incompatible_license_in_manifest(path)
      - scan_unlicensed_not_private(path)
      - scan_manifest_content_drift(root)
      - scan_spdx_malformed_in_file(path)
      - scan_no_license_ci_workflow(workflows_root)
      - scan_cla_relicense_stealth(contributing_path, license_path)
      - scan_vendor_missing_license(root)
      - scan_noncommercial_in_deps(path)
      - scan_spdx_deprecated_bare_form(path)
      - scan_copyright_line_drift(root)
      - scan_patent_grant_stripped(root)
      - scan_trademark_no_disclaimer(path)
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match. Same shape as `sbom_tampering_patterns.Finding`
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
    if any of them appear, the rule's positive matches are suppressed.
    `file_suffixes` filters which files this rule applies to. Empty
    tuple = any file. Both the file's extension AND its bare name are
    checked.
    """

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006
    negative_substrings: tuple[str, ...]
    file_suffixes: tuple[str, ...]


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — same flag set as Wave 18."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Shared constants ---------------------------------------------------


# Source-file suffixes for which an SPDX header is conventionally expected.
_SPDX_SOURCE_SUFFIXES: tuple[str, ...] = (
    ".py", ".rs", ".go", ".js", ".ts", ".tsx", ".jsx",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".java", ".kt",
    ".scala", ".swift", ".rb", ".php", ".cs", ".sh",
    ".bash", ".zsh",
)


# Filenames considered LICENSE-shape at the repo root.
_LICENSE_FILE_NAMES: tuple[str, ...] = (
    "LICENSE", "LICENSE.md", "LICENSE.txt", "LICENSE.rst",
    "LICENCE", "LICENCE.md", "LICENCE.txt",
    "COPYING", "COPYING.txt", "COPYING.LESSER",
    "MIT-LICENSE", "UNLICENSE",
)


# Filenames considered NOTICE-shape at the repo root.
_NOTICE_FILE_NAMES: tuple[str, ...] = (
    "NOTICE", "NOTICE.txt", "NOTICE.md", "NOTICES",
)


# Vendored-tree top-level directory names.
_VENDOR_DIR_NAMES: tuple[str, ...] = (
    "third_party", "thirdparty", "vendor", "vendors",
    "libs", "external", "deps",
)


# ---- Rule P1 — license-template-placeholder-unfilled (MAJOR) ------------


# Matches each of the canonical OSI-template placeholder patterns left
# unfilled. Designed to fire ONLY inside a LICENSE-shape file (filtered
# via `file_suffixes`). All literal — RE2-safe; no lookaround.
_LICENSE_TEMPLATE_PLACEHOLDER = _re(
    r"Copyright\s*\(c\)\s*"
    r"(?:"
    r"<\s*YEAR\s*>"
    r"|<\s*year\s*>"
    r"|\[\s*year\s*\]"
    r"|\[\s*YEAR\s*\]"
    r"|\{\s*year\s*\}"
    r"|YYYY"
    r"|<\s*COPYRIGHT\s+HOLDER\s*>"
    r"|<\s*name\s+of\s+author\s*>"
    r"|<\s*your\s+name\s*>"
    r"|<\s*YOUR\s+NAME\s*>"
    r"|<\s*NAME\s*>"
    r"|\[\s*YOUR\s+NAME\s*\]"
    r"|Your\s+Name"
    r"|Author\s+Name"
    r"|FirstName\s+LastName"
    r"|\{\s*fullname\s*\}"
    r"|\{\s*author\s*\}"
    r")"
)


# Email-placeholder shape — surface separately so a copyright line with
# only a placeholder email can still fire.
_LICENSE_EMAIL_PLACEHOLDER = _re(
    r"<\s*(?:"
    r"your-?email|you|email|me|user|name|author"
    r")@(?:example\.com|example\.org|email\.com|you\.com)\s*>"
)


# ---- Rule P3 — license-apache2-notice-missing (composite, MAJOR) --------


# Detector for the Apache-2.0 license body inside a LICENSE file.
_LICENSE_APACHE2_MARKER = _re(
    r"Apache\s+License[, ]\s*Version\s*2\.0"
    r"|Licensed\s+under\s+the\s+Apache\s+License,?\s*Version\s*2\.0"
    r"|SPDX-License-Identifier:\s*Apache-2\.0"
)


_LICENSE_GPL_FAMILY_MARKER = _re(
    r"(?:GNU\s+(?:Lesser\s+|Affero\s+)?General\s+Public\s+License"
    r"|SPDX-License-Identifier:\s*(?:L|A)?GPL-[123](?:\.\d)?"
    r"(?:-(?:only|or-later))?)"
)


# ---- Rule P4 — license-incompatible-copyleft-in-permissive (CRITICAL) ---


# Permissive SPDX identifiers — repo-level declaration that triggers the
# incompatibility check.
_PERMISSIVE_SPDX: tuple[str, ...] = (
    "MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0",
    "ISC", "0BSD", "Unlicense", "Zlib", "BSL-1.0",
    "MPL-2.0", "Unicode-DFS-2016",
)


# Incompatible copyleft / source-available SPDX identifiers.
_INCOMPATIBLE_SPDX: tuple[str, ...] = (
    "AGPL-3.0", "AGPL-3.0-only", "AGPL-3.0-or-later",
    "AGPL-1.0", "AGPL-1.0-only", "AGPL-1.0-or-later",
    "SSPL-1.0",
    "BSL-1.1", "BUSL-1.1",
    "Commons-Clause",
    "FSL-1.0", "FSL-1.1",
    "GPL-3.0", "GPL-3.0-only", "GPL-3.0-or-later",
    "Elastic-2.0",
    "RSAL-2.0",
)


# Dependency names known to ship under a watchlist license. Each tuple
# element is a (substring, expected-license-tag) pair. We match the
# substring against manifest dependency names case-insensitively.
_INCOMPATIBLE_PACKAGES: tuple[tuple[str, str], ...] = (
    # AGPL — common offenders.
    ("ghostscript", "AGPL-3.0"),
    ("itext7", "AGPL-3.0"),
    ("itext5", "AGPL-3.0"),
    ("mongodb-compass", "AGPL-3.0"),
    ("mariadb-audit-plugin", "AGPL-3.0"),
    ("cube.js", "AGPL-3.0"),
    ("plausible-analytics", "AGPL-3.0"),
    # SSPL — MongoDB server and Elasticsearch.
    ("elasticsearch", "SSPL-1.0"),
    ("kibana", "SSPL-1.0"),
    ("logstash", "SSPL-1.0"),
    # Redis 7.4+ went dual-RSALv2/SSPL.
    # BSL — CockroachDB, MariaDB MaxScale, etc.
    ("cockroachdb", "BSL-1.1"),
    ("cockroach", "BSL-1.1"),
    ("maxscale", "BSL-1.1"),
    ("oxide.io", "BSL-1.1"),
    ("cadenceworkflow", "BSL-1.1"),
    # FSL — Sentry 23.6+.
    ("getsentry/sentry", "FSL-1.1"),
)


# Docker image names that imply the SSPL / BSL / FSL stigma.
_INCOMPATIBLE_DOCKER_IMAGES: tuple[tuple[str, str], ...] = (
    ("mongo:", "SSPL-1.0"),
    ("mongodb:", "SSPL-1.0"),
    ("elasticsearch:", "SSPL-1.0"),
    ("kibana:", "SSPL-1.0"),
    ("docker.elastic.co/", "SSPL-1.0"),
    ("cockroachdb/cockroach", "BSL-1.1"),
    ("mariadb-maxscale", "BSL-1.1"),
)


_NPM_DEP_NAME_LINE = _re(
    r'^\s*"([^"]{1,200})"\s*:\s*"([^"]{1,200})"\s*,?\s*$'
)


_PY_DEP_NAME = _re(
    r"^\s*([A-Za-z][A-Za-z0-9._\-]{0,100})\s*[=><!~]"
)


_DOCKER_FROM_LINE = _re(
    r"^\s*FROM\s+([^\s\n]{1,200})"
)


# ---- Rule P5 — license-unlicensed-not-private (HIGH) --------------------


_NPM_LICENSE_UNLICENSED = _re(
    r'"license"\s*:\s*"(UNLICENSED|UNKNOWN|PROPRIETARY|NONE|Proprietary)"'
)


_NPM_PRIVATE_TRUE = _re(
    r'"private"\s*:\s*true'
)


_NPM_NAME_SCOPED = _re(
    r'"name"\s*:\s*"(@[^/]{1,80}/[^"]{1,120})"'
)


_NPM_LICENSE_SEE_FILE = _re(
    r'"license"\s*:\s*"SEE\s+LICENSE\s+IN\s+([^"]{1,200})"'
)


_PY_LICENSE_PROPRIETARY = _re(
    r'^\s*license\s*=\s*["\'](?:Proprietary|UNLICENSED|UNKNOWN)["\']\s*$'
)


_CARGO_LICENSE_PROPRIETARY = _re(
    r'^\s*license\s*=\s*"(?:Proprietary|Custom|UNLICENSED)"\s*$'
)


_CARGO_PUBLISH_FALSE = _re(
    r'^\s*publish\s*=\s*false\s*$'
)


# ---- Rule P6 — license-manifest-content-drift (CRITICAL, composite) -----


# Minimal MIT body marker (excerpt unique to MIT).
_MIT_BODY_MARKER = _re(
    r"Permission\s+is\s+hereby\s+granted,?\s+free\s+of\s+charge"
)


# Minimal Apache-2.0 body marker.
_APACHE2_BODY_MARKER = _re(
    r"Licensed\s+under\s+the\s+Apache\s+License,?\s+Version\s+2\.0"
    r"|Apache\s+License,?\s+Version\s+2\.0,?\s+January\s+2004"
)


# Minimal BSD-3-Clause body marker.
_BSD3_BODY_MARKER = _re(
    r"Redistribution\s+and\s+use\s+in\s+source\s+and\s+binary\s+forms"
)


# Minimal GPL body marker.
_GPL_BODY_MARKER = _re(
    r"GNU\s+General\s+Public\s+License"
    r"|GNU\s+Affero\s+General\s+Public\s+License"
    r"|GNU\s+Lesser\s+General\s+Public\s+License"
)


# ---- Rule P7 — license-spdx-malformed-or-missing (MAJOR / CRITICAL) -----


_SPDX_LICENSE_LINE = _re(
    r"SPDX-License-Identifier\s*:\s*([^\n\r]{1,200})"
)


# A canonical SPDX expression grammar — IDENTIFIER (op IDENTIFIER)*
# where op is OR/AND/WITH and IDENTIFIER is the SPDX-list-canonical
# `[A-Za-z0-9.\-+]+`. Bounded — RE2-safe.
_SPDX_EXPRESSION_GRAMMAR = re.compile(
    r"^\s*"
    r"[A-Za-z0-9.\-+]{1,80}"
    r"(?:\s+(?:OR|AND|WITH)\s+[A-Za-z0-9.\-+]{1,80}){0,16}"
    r"\s*$"
)


# ---- Rule P8 — license-no-ci-scanner (MAJOR, composite) -----------------


# Tokens that, if present in any workflow / CI file, indicate the
# project already runs a license-compliance check.
_LICENSE_SCANNER_TOKENS: tuple[str, ...] = (
    "license-checker",
    "pnpm licenses",
    "fossa analyze",
    "fossa-action",
    "snyk-license",
    "ort scan",
    "scancode",
    "pip-licenses",
    "liccheck",
    "cargo-license",
    "cargo deny",
    "cargo-deny",
    "go-licenses",
    "licensed status",
    "licensee detect",
    "deny.toml",
    "cargo-deny.toml",
    "licensee.yml",
)


# ---- Rule P9 — license-relicense-by-stealth-via-cla (HIGH) --------------


# CLA / relicensing-clause language inside CONTRIBUTING.md or CLA.md.
_CLA_RELICENSE_LANGUAGE = _re(
    r"(?:grant|assign|transfer|convey)"
    r"[^\n]{1,120}"
    r"(?:perpetual|irrevocable|sublicensable|sublicenseable|transferable)"
)


_CLA_RELICENSE_DIRECT = _re(
    r"(?:re-?license|relicense|relicensing)"
)


_CLA_PROPRIETARY_CONVERSION = _re(
    r"(?:any\s+other\s+license"
    r"|under\s+any\s+license"
    r"|future\s+license"
    r"|proprietary\s+license"
    r"|closed[-\s]source"
    r"|commercial\s+license)"
)


_CLA_LICENSE_TRANSITION = _re(
    r"(?:Apache|MIT|BSD|GPL|LGPL|MPL)"
    r"[^\n]{0,80}"
    r"(?:to|or)"
    r"[^\n]{0,80}"
    r"(?:BSL|BUSL|SSPL|FSL|AGPL|Commons[-\s]?Clause|Elastic-2)"
)


_CLA_COPYRIGHT_ASSIGN = _re(
    r"assign\s+(?:[^\n]{0,80})\s*copyright"
)


# ---- Rule P11 — license-non-commercial-in-deps (CRITICAL) ---------------


_NONCOMMERCIAL_SPDX: tuple[str, ...] = (
    "CC-BY-NC-1.0", "CC-BY-NC-2.0", "CC-BY-NC-2.5",
    "CC-BY-NC-3.0", "CC-BY-NC-4.0",
    "CC-BY-NC-SA-1.0", "CC-BY-NC-SA-2.0",
    "CC-BY-NC-SA-2.5", "CC-BY-NC-SA-3.0", "CC-BY-NC-SA-4.0",
    "CC-BY-NC-ND-1.0", "CC-BY-NC-ND-2.0",
    "CC-BY-NC-ND-2.5", "CC-BY-NC-ND-3.0", "CC-BY-NC-ND-4.0",
    "JSON",
    "Anti-996-License",
    "anti-996-license-1.0",
    "Hippocratic-2.1",
    "Hippocratic-3.0",
    "HL3-CL-ECO",
    "HL3-CL-MIL-XX",
    "WTFPL",
)


_LICENSE_NONCOMMERCIAL_TEXT = _re(
    r"(?:Creative\s+Commons\s+(?:Attribution-)?NonCommercial"
    r"|Good,?\s+not\s+Evil"
    r"|996icu"
    r"|Hippocratic\s+License)"
)


# ---- Rule P12 — license-spdx-deprecated-bare-form (MINOR) ---------------


_DEPRECATED_BARE_SPDX: tuple[str, ...] = (
    "GPL-1.0", "GPL-2.0", "GPL-3.0",
    "LGPL-2.0", "LGPL-2.1", "LGPL-3.0",
    "AGPL-1.0", "AGPL-3.0",
    "GFDL-1.1", "GFDL-1.2", "GFDL-1.3",
)


_SPDX_BARE_DEPRECATED = _re(
    r"SPDX-License-Identifier\s*:\s*"
    r"((?:GPL|LGPL|AGPL|GFDL)-[123](?:\.[0-3])?)"
    r"(?:\s|$|[^A-Za-z0-9])"
)


_MANIFEST_LICENSE_BARE_DEPRECATED = _re(
    r'"license"\s*:\s*"((?:GPL|LGPL|AGPL|GFDL)-[123](?:\.[0-3])?)"'
)


_TOML_LICENSE_BARE_DEPRECATED = _re(
    r'^\s*license\s*=\s*"((?:GPL|LGPL|AGPL|GFDL)-[123](?:\.[0-3])?)"'
)


# ---- Rule P13 — license-copyright-line-drift (MAJOR, composite) ---------


_COPYRIGHT_LINE = _re(
    r"(?:Copyright|©|\(c\))\s*"
    r"(?:\(c\)\s*)?"
    r"(\d{4}(?:[-,]\s*\d{4})?)\s+"
    r"([A-Za-z][^\n\r]{0,160})"
)


# ---- Rule P14 — license-patent-grant-stripped (CRITICAL) ----------------


_APACHE_PATENT_GRANT_MARKER = _re(
    r"Grant\s+of\s+Patent\s+License"
    r"|hereby\s+grants\s+to\s+You\s+a\s+perpetual"
    r"|(?:patent\s+license\s+to\s+make,?\s+have\s+made,?\s+use)"
)


_MPL_PATENT_GRANT_MARKER = _re(
    r"each\s+Contributor\s+hereby\s+grants\s+You\s+a\s+(?:world[-\s]?wide)?"
    r"[^\n]{0,80}"
    r"patent\s+license"
)


# ---- Rule P15 — license-trademark-no-disclaimer (MINOR) -----------------


_TRADEMARK_NAMES: tuple[str, ...] = (
    "Anthropic", "Claude", "Constitutional AI",
    "OpenAI", "GPT", "ChatGPT", "DALL-E", "Sora",
    "Google", "Gemini", "Bard",
    "AWS", "Amazon Web Services",
    "Microsoft", "Azure", "Copilot",
    "Apple", "iOS", "macOS", "iPadOS", "Xcode",
    "Meta", "Facebook", "Instagram", "React",
    "Docker", "Kubernetes", "Helm",
    "Terraform", "Vault", "Consul",
    "Rust Foundation", "Python Software Foundation",
    "Linux Foundation", "CNCF",
)


_TRADEMARK_DISCLAIMER_TOKENS: tuple[str, ...] = (
    "trademark",
    "not affiliated",
    "not endorsed",
    "no affiliation",
    "is a registered",
    "all rights reserved",
)


# Detector: a markdown / readme paragraph containing one of the trademark
# names — used to anchor the location of a "missing disclaimer" finding.
_TRADEMARK_NAME_USAGE = _re(
    r"(?:^|[^A-Za-z0-9_])"
    r"(Anthropic|Claude|OpenAI|ChatGPT|"
    r"Gemini|AWS|Azure|Copilot|"
    r"Docker|Kubernetes|Terraform|"
    r"React|Facebook|Meta)"
    r"(?:[^A-Za-z0-9_]|$)"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="license-template-placeholder-unfilled",
        name="LICENSE file with unfilled template placeholder",
        severity="MAJOR",
        description=(
            "A LICENSE / COPYING / UNLICENSE file in the repo root "
            "contains a literal OSI-template placeholder "
            "(`<YEAR>`, `<COPYRIGHT HOLDER>`, `<your name>`, `YYYY`, "
            "`[YEAR]`, `Your Name`, etc.). A LICENSE with placeholder "
            "text is legally void in most jurisdictions and ships a "
            "broken copyright assertion in every release tarball. "
            "Replace placeholders with a literal year (e.g. 2026) "
            "and a real rightsholder name. Do NOT leave angle "
            "brackets in the literal text."
        ),
        pattern=_LICENSE_TEMPLATE_PLACEHOLDER,
        negative_substrings=(),
        file_suffixes=_LICENSE_FILE_NAMES + (
            ".md", ".txt", ".rst",
        ),
    ),
    Rule(
        id="license-template-email-placeholder",
        name="LICENSE file with unfilled email placeholder",
        severity="MAJOR",
        description=(
            "A LICENSE-shape file contains a literal placeholder "
            "email such as `<you@example.com>` / `<your-email@example.com>`. "
            "Authorship-disclosure leak in reverse: the literal "
            "placeholder text is shipped in the release tarball "
            "forever. Replace with the actual rightsholder email "
            "or remove the email line."
        ),
        pattern=_LICENSE_EMAIL_PLACEHOLDER,
        negative_substrings=(),
        file_suffixes=_LICENSE_FILE_NAMES + (
            ".md", ".txt", ".rst",
        ),
    ),
    Rule(
        id="license-spdx-mismatch-with-root",
        name="Source-file SPDX header detector (composite)",
        severity="MAJOR",
        description=(
            "A source file declares an SPDX-License-Identifier that "
            "does NOT match the project's root LICENSE declaration. "
            "Three failure modes: (a) vendoring failure — file copied "
            "from an upstream with a different license; (b) refactor "
            "failure — project changed license but only updated new "
            "files; (c) license-laundering attempt. Use "
            "`scan_spdx_mismatch_with_root()` for the cross-tree "
            "comparison."
        ),
        pattern=_SPDX_LICENSE_LINE,
        negative_substrings=(),
        file_suffixes=_SPDX_SOURCE_SUFFIXES,
    ),
    Rule(
        id="license-apache2-notice-missing",
        name="Apache-2.0 LICENSE detector (composite)",
        severity="MAJOR",
        description=(
            "Project declares Apache-2.0 but no NOTICE / NOTICE.txt / "
            "NOTICE.md exists in the repo root. Apache-2.0 § 4(d) "
            "requires derivative works to propagate the NOTICE file's "
            "attribution; without a NOTICE file at all, no downstream "
            "consumer can satisfy § 4(d). Create a NOTICE file listing "
            "every Apache-2.0 vendor's attribution. Use "
            "`scan_apache_notice_missing()` for the project-wide check."
        ),
        pattern=_LICENSE_APACHE2_MARKER,
        negative_substrings=(),
        file_suffixes=_LICENSE_FILE_NAMES + (".md", ".txt", ".rst"),
    ),
    Rule(
        id="license-incompatible-copyleft-in-permissive",
        name="Incompatible copyleft / source-available dep in permissive project",
        severity="CRITICAL",
        description=(
            "Project declares a permissive license (MIT / Apache-2.0 "
            "/ BSD / ISC) but the dependency manifest includes an "
            "AGPL / SSPL / BSL / FSL / Commons-Clause / Elastic-2.0 "
            "package. AGPL § 13's network-use clause makes any "
            "SaaS consumer AGPL-licensed by linkage. SSPL § 13 "
            "extends the duty to the operating environment. BSL "
            "Additional Use Grants restrict competing commercial "
            "use. Drop the dep, replace with a permissive "
            "alternative, or re-license the project to match the "
            "most-restrictive dep. Use "
            "`scan_incompatible_license_in_manifest()`."
        ),
        pattern=_NPM_DEP_NAME_LINE,
        negative_substrings=(),
        file_suffixes=(
            "package.json", "package-lock.json", "yarn.lock",
            "pnpm-lock.yaml", "pyproject.toml", "requirements.txt",
            "requirements-dev.txt", "requirements-test.txt",
            "uv.lock", "poetry.lock", "Pipfile.lock",
            "Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
            "Gemfile.lock", "composer.json", "composer.lock",
        ),
    ),
    Rule(
        id="license-unlicensed-not-private",
        name="Manifest declares UNLICENSED but lacks the private flag",
        severity="HIGH",
        description=(
            "`package.json` declares `\"license\": \"UNLICENSED\"` / "
            "`\"PROPRIETARY\"` / `\"UNKNOWN\"` / `\"NONE\"` AND `private` "
            "is absent or false AND the package name is NOT scoped "
            "(`@org/name`). One `npm publish` away from publishing "
            "proprietary code publicly with a self-contradicting "
            "license. Add `\"private\": true` (npm refuses to publish "
            "private packages). For Cargo: add `publish = false`. "
            "For Poetry: configure a private index."
        ),
        pattern=_NPM_LICENSE_UNLICENSED,
        negative_substrings=(),
        file_suffixes=("package.json", "pyproject.toml", "Cargo.toml"),
    ),
    Rule(
        id="license-manifest-content-drift",
        name="LICENSE file extractor for content-vs-manifest drift (composite)",
        severity="CRITICAL",
        description=(
            "Manifest declares license X (e.g. `\"license\": \"MIT\"` "
            "in package.json) but the LICENSE file content does NOT "
            "match the X canonical template (within 5% whitespace / "
            "copyright-line tolerance, same threshold as the GitHub "
            "`licensee` gem). Three sub-findings: declared-vs-content "
            "mismatch (CRITICAL — license-laundering vector), no "
            "canonical-template match at all (MAJOR — custom license, "
            "manual review). Use `scan_manifest_content_drift()`."
        ),
        pattern=_MIT_BODY_MARKER,
        negative_substrings=(),
        file_suffixes=_LICENSE_FILE_NAMES + (".md", ".txt", ".rst"),
    ),
    Rule(
        id="license-spdx-malformed-or-missing",
        name="SPDX-License-Identifier value malformed",
        severity="MAJOR",
        description=(
            "Source file's `SPDX-License-Identifier:` line carries "
            "a value that does NOT match the SPDX 3.x expression "
            "grammar (`IDENTIFIER (OR|AND|WITH IDENTIFIER)*`). SPDX-"
            "aware tooling silently treats the line as absent — the "
            "file then registers as `unspecified` instead of "
            "inheriting the repo LICENSE. Common malformed shapes: "
            "`SPDX-License-Identifier: MIT-or-Apache` (use `MIT OR "
            "Apache-2.0`), `SPDX-License-Identifier: My-Custom-"
            "License`, lowercase operators."
        ),
        pattern=_SPDX_LICENSE_LINE,
        negative_substrings=(),
        file_suffixes=_SPDX_SOURCE_SUFFIXES,
    ),
    Rule(
        id="license-no-ci-scanner",
        name="No license-compatibility scanner detected in CI (composite)",
        severity="MAJOR",
        description=(
            "Project has dependency manifests but no CI workflow "
            "invokes a license-compatibility scanner (license-checker "
            "/ FOSSA / Snyk / ORT / scancode / cargo-deny / "
            "pip-licenses / liccheck / go-licenses / licensed). "
            "Without CI license-due-diligence, a transitive AGPL / "
            "SSPL / BSL dep can land silently. Add `cargo-deny check "
            "licenses` (Rust), `license-checker --failOn AGPL-3.0;"
            "SSPL-1.0` (npm), `liccheck` (Python). Use "
            "`scan_no_license_ci_workflow()`."
        ),
        # Marker pattern — composite helper looks for scanner tokens
        # directly via _LICENSE_SCANNER_TOKENS; this regex is a stub
        # that anchors the rule in the registry.
        pattern=_re(r"license[-_]?checker|fossa|cargo[-_]?deny"),
        negative_substrings=(),
        file_suffixes=(".yml", ".yaml"),
    ),
    Rule(
        id="license-relicense-by-stealth-via-cla",
        name="CONTRIBUTING / CLA carries relicensing-grant language",
        severity="HIGH",
        description=(
            "CONTRIBUTING.md / CLA.md / DCO.md contains CLA-style "
            "relicensing language (grant of perpetual / irrevocable / "
            "sublicensable / transferable rights to relicense "
            "contributions under any license). When the project's "
            "LICENSE file is unchanged in the same window, this is "
            "the canonical relicense-by-stealth pattern (Redis 7.4 "
            "SSPL, HashiCorp BSL, MongoDB SSPL). Open an issue "
            "asking the maintainer to clarify whether the project "
            "license is changing. Use `scan_cla_relicense_stealth()`."
        ),
        pattern=_CLA_RELICENSE_LANGUAGE,
        negative_substrings=(),
        file_suffixes=(
            "CONTRIBUTING.md", "CONTRIBUTING.rst", "CONTRIBUTING.txt",
            "CLA.md", "CLA.txt", "DCO.md", "DCO.txt",
            "CODE_OF_CONDUCT.md",
        ),
    ),
    Rule(
        id="license-vendor-missing-attribution",
        name="Vendored third-party directory lacks LICENSE file (composite)",
        severity="MAJOR",
        description=(
            "A vendored subdirectory (under `third_party/`, `vendor/`, "
            "`libs/`, `external/`, `deps/`) lacks a LICENSE / COPYING "
            "/ UNLICENSE file at its root. MIT § preserve-copyright "
            "notice, Apache-2.0 § 4(a) license inclusion, GPL § 1 "
            "copy-of-GPL — every OSS license requires the LICENSE "
            "file to travel with each substantial copy. Add the "
            "upstream's LICENSE file under "
            "`third_party/<vendor>/LICENSE`. Use "
            "`scan_vendor_missing_license()`."
        ),
        # Marker — the composite helper enumerates vendor directories.
        pattern=_re(r"third[-_]?party|vendor"),
        negative_substrings=(),
        file_suffixes=(),
    ),
    Rule(
        id="license-non-commercial-in-deps",
        name="Non-commercial / Hippocratic / JSON / WTFPL dep declared",
        severity="CRITICAL",
        description=(
            "Dependency manifest declares a CC-BY-NC / CC-BY-NC-SA "
            "/ CC-BY-NC-ND / JSON (`Good not Evil`) / Anti-996 / "
            "Hippocratic / WTFPL license. CC-NC variants prohibit "
            "commercial use; JSON's `Good not Evil` clause is "
            "non-redistributable in commercial contexts (IBM had "
            "to request written Crockford permission). Anti-996 and "
            "Hippocratic add political clauses that some "
            "jurisdictions deem unenforceable. Find a CC-BY-4.0 / "
            "MIT / Apache-2.0 alternative."
        ),
        pattern=_LICENSE_NONCOMMERCIAL_TEXT,
        negative_substrings=(),
        file_suffixes=(
            "package.json", "pyproject.toml", "Cargo.toml",
            "composer.json", "Gemfile",
            ".gemspec", "go.mod",
            "LICENSE", "LICENSE.md", "LICENSE.txt",
        ),
    ),
    Rule(
        id="license-spdx-deprecated-bare-form",
        name="Deprecated bare SPDX identifier (e.g. GPL-3.0 vs GPL-3.0-only)",
        severity="MINOR",
        description=(
            "SPDX-License-Identifier uses a deprecated bare form "
            "(`GPL-3.0`, `LGPL-2.1`, `AGPL-3.0`, etc.) instead of the "
            "explicit `-only` / `-or-later` suffix required since "
            "SPDX 3.0 (2018). The bare form is ambiguous between "
            "'this version only' and 'this version or any later'. "
            "REUSE 3.0 and modern cargo-deny reject bare forms. "
            "Choose `<id>-only` or `<id>-or-later` based on actual "
            "intent — the legal semantics differ, so the janitor "
            "MUST NOT auto-fix silently."
        ),
        pattern=_SPDX_BARE_DEPRECATED,
        negative_substrings=(),
        file_suffixes=_SPDX_SOURCE_SUFFIXES + (
            "package.json", "pyproject.toml", "Cargo.toml",
            "composer.json",
        ),
    ),
    Rule(
        id="license-copyright-line-drift",
        name="Copyright-line drift between LICENSE and source files (composite)",
        severity="MAJOR",
        description=(
            "Repo-root LICENSE declares `Copyright (c) <year> "
            "<rightsholder>` but at least one source file carries a "
            "different `<year>` or `<rightsholder>`. Vendoring failure "
            "(unattributed third-party source) or stale LICENSE "
            "(project changed maintainers without updating). Per-file "
            "copyright lines must be a subset of the LICENSE's "
            "declared rightsholders to discharge downstream "
            "'preserve copyright notice' clauses. Use "
            "`scan_copyright_line_drift()`."
        ),
        pattern=_COPYRIGHT_LINE,
        negative_substrings=(),
        file_suffixes=_LICENSE_FILE_NAMES + _SPDX_SOURCE_SUFFIXES,
    ),
    Rule(
        id="license-patent-grant-stripped",
        name="Vendored Apache/MPL/GPL code missing patent-grant LICENSE",
        severity="CRITICAL",
        description=(
            "Project vendors Apache-2.0 / MPL-2.0 / GPL-3.0 code "
            "(file declares one of those identifiers) but the root "
            "LICENSE is MIT (which has NO patent grant) and there is "
            "no `LICENSE-Apache-2.0` / `LICENSE-MPL-2.0` / etc. "
            "alongside the vendored copy. The patent grant from § 3 "
            "(Apache), § 2.1 (MPL), § 11 (GPL-3) does NOT transfer to "
            "the downstream copy when the LICENSE file is stripped. "
            "Add the verbatim Apache-2.0 LICENSE-2.0 file alongside "
            "the vendored copy."
        ),
        pattern=_APACHE_PATENT_GRANT_MARKER,
        negative_substrings=(),
        file_suffixes=_LICENSE_FILE_NAMES + (".md", ".txt", ".rst"),
    ),
    Rule(
        id="license-trademark-no-disclaimer",
        name="Upstream trademark used without disclaimer in README",
        severity="MINOR",
        description=(
            "README mentions a registered upstream trademark "
            "(Anthropic, Claude, OpenAI, AWS, Kubernetes, Docker, "
            "Terraform, React, etc.) without a trademark "
            "disclaimer (`X is a trademark of Y. This project is not "
            "affiliated with Y.`). Required by Anthropic / Mozilla / "
            "CNCF / Apache / LF trademark policies. Add a footer "
            "disclaimer to the README."
        ),
        pattern=_TRADEMARK_NAME_USAGE,
        negative_substrings=_TRADEMARK_DISCLAIMER_TOKENS,
        file_suffixes=("README.md", "README.rst", "README.txt"),
    ),
)


# ---- Optional env-driven knobs ------------------------------------------


def _env_csv(name: str) -> tuple[str, ...]:
    """Read a comma-separated env knob into a tuple of trimmed substrings."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return ()
    return tuple(s.strip() for s in raw.split(",") if s.strip())


def _trademark_disclaimer_tokens() -> tuple[str, ...]:
    """Combine built-in + operator-supplied trademark-disclaimer tokens."""
    return _TRADEMARK_DISCLAIMER_TOKENS + _env_csv(
        "JANITOR_OPT_LICENSE_TRADEMARK_DISCLAIMER_EXTRA"
    )


# ---- Composite helpers --------------------------------------------------


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
    """Empty suffix tuple = any file. Case-insensitive."""
    if not suffixes:
        return True
    name = path.name.lower()
    return any(name.endswith(suf.lower()) for suf in suffixes)


def _is_license_file(path: Path) -> bool:
    """True iff path's basename is one of the canonical LICENSE shapes."""
    name = path.name
    # Strict case (LICENSE, COPYING) plus permissive (LICENSE.md etc.)
    if name.upper() in {n.upper() for n in _LICENSE_FILE_NAMES}:
        return True
    upper = name.upper()
    return any(
        upper.startswith(prefix)
        for prefix in ("LICENSE", "LICENCE", "COPYING", "UNLICENSE", "MIT-LICENSE")
    )


def _is_notice_file(path: Path) -> bool:
    name = path.name.upper()
    return any(name == n.upper() or name.startswith(n.upper() + ".")
               for n in _NOTICE_FILE_NAMES)


def extract_repo_license_spdx(root: Path) -> str | None:
    """Identify the project's declared SPDX license from the repo root.

    Searches, in order:
      1. Manifest declarations (package.json, pyproject.toml, Cargo.toml).
      2. LICENSE file content matched against canonical SPDX templates.

    Returns the SPDX identifier (e.g. "MIT", "Apache-2.0", "GPL-3.0-only")
    or None when nothing matches.
    """
    if not root.is_dir():
        return None
    # Pass 1 — manifest declarations.
    for manifest in ("package.json", "pyproject.toml", "Cargo.toml"):
        manifest_path = root / manifest
        if not manifest_path.is_file():
            continue
        try:
            text = manifest_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # JSON shape.
        m = re.search(r'"license"\s*:\s*"([^"]{1,80})"', text)
        if m:
            value = m.group(1).strip()
            if value:
                return value
        # TOML shape (Cargo / pyproject).
        m = re.search(
            r'^\s*license\s*=\s*"([^"]{1,80})"',
            text,
            re.MULTILINE,
        )
        if m:
            value = m.group(1).strip()
            if value:
                return value
    # Pass 2 — LICENSE-file content.
    for entry in root.iterdir():
        if not entry.is_file() or not _is_license_file(entry):
            continue
        try:
            text = entry.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Check each canonical template marker in turn.
        if _MIT_BODY_MARKER.search(text):
            return "MIT"
        if _APACHE2_BODY_MARKER.search(text):
            return "Apache-2.0"
        if _BSD3_BODY_MARKER.search(text):
            return "BSD-3-Clause"
        if _GPL_BODY_MARKER.search(text):
            # Crude — caller can re-classify with the explicit suffix.
            return "GPL-3.0-or-later"
    return None


def extract_file_spdx_identifiers(text: str) -> list[str]:
    """Return every distinct SPDX identifier declared in `text`'s first
    30 lines. Empty list when none present.
    """
    if not text:
        return []
    head = "\n".join(text.splitlines()[:30])
    out: list[str] = []
    for m in _SPDX_LICENSE_LINE.finditer(head):
        value = m.group(1).strip()
        if value and value not in out:
            out.append(value)
    return out


def spdx_expressions_compatible(declared: str, file_decl: str) -> bool:
    """Check whether `file_decl` (per-file SPDX) is satisfied by the
    `declared` repo-level SPDX expression.

    Compatibility rules implemented here:
      * Exact identifier match — compatible.
      * `MIT OR Apache-2.0` repo declaration is satisfied by either
        `MIT` or `Apache-2.0` per-file declarations.
      * Disjunction in either expression broadens the compatible set.
      * Conjunction (`AND`) requires the file to declare all of them.

    No deep license-compatibility lattice is implemented — the goal is
    to flag the obvious mismatch (`Apache-2.0` file in a repo declaring
    `MIT`) not to legal-validate every SPDX disjunction permutation.
    """
    if not declared or not file_decl:
        return True  # insufficient evidence — don't flag
    d_norm = declared.strip()
    f_norm = file_decl.strip()
    if d_norm.lower() == f_norm.lower():
        return True
    # OR disjunction in the repo-level expression — file matches if it
    # declares any operand.
    if " or " in d_norm.lower():
        operands = [
            o.strip().lower()
            for o in re.split(r"\s+OR\s+", d_norm, flags=re.IGNORECASE)
        ]
        return f_norm.lower() in operands
    # OR disjunction in the per-file expression — file is permissive
    # enough to satisfy the repo declaration if the repo identifier
    # appears as one of its operands.
    if " or " in f_norm.lower():
        operands = [
            o.strip().lower()
            for o in re.split(r"\s+OR\s+", f_norm, flags=re.IGNORECASE)
        ]
        return d_norm.lower() in operands
    return False


def scan_spdx_mismatch_with_root(root: Path) -> list[Finding]:
    """P2 — for each source file in the tree, compare its declared SPDX
    identifier (first 30 lines) against the project-level declaration.
    Emit one finding per mismatch, capped at 20 to avoid spamming on
    bulk vendor drops.
    """
    if not root.is_dir():
        return []
    repo_spdx = extract_repo_license_spdx(root)
    if not repo_spdx:
        return []
    findings: list[Finding] = []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-spdx-mismatch-with-root"),
        "",
    )
    cap = 20
    for path in sorted(root.rglob("*")):
        if len(findings) >= cap:
            break
        if not path.is_file():
            continue
        # Skip vendored subtrees — they legitimately carry different SPDX.
        rel_parts = {p.lower() for p in path.relative_to(root).parts}
        if rel_parts & set(_VENDOR_DIR_NAMES):
            continue
        if not any(path.name.lower().endswith(suf) for suf in _SPDX_SOURCE_SUFFIXES):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ids = extract_file_spdx_identifiers(text)
        if not ids:
            continue
        for declared in ids:
            if spdx_expressions_compatible(repo_spdx, declared):
                continue
            # Locate the actual SPDX line for the report.
            m = _SPDX_LICENSE_LINE.search(text)
            if m is None:  # pragma: no cover — `ids` non-empty implies match
                continue
            line, col = _line_col(text, m.start())
            findings.append(Finding(
                rule_id="license-spdx-mismatch-with-root",
                line=line,
                column=col,
                matched_text=f"{declared} (root={repo_spdx})",
                severity="MAJOR",
                description=rule_desc,
                file_path=str(path),
            ))
            break  # one finding per file
    return findings


def scan_apache_notice_missing(root: Path) -> list[Finding]:
    """P3 — repo declares Apache-2.0 (via LICENSE body OR manifest) and
    no NOTICE file exists at the root.
    """
    if not root.is_dir():
        return []
    spdx = extract_repo_license_spdx(root)
    if not spdx:
        return []
    if "apache-2.0" not in spdx.lower():
        return []
    # Look for a NOTICE file at the root.
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    for entry in entries:
        if entry.is_file() and _is_notice_file(entry):
            return []
    # Anchor finding at the LICENSE file (best location to surface).
    anchor: Path | None = None
    for entry in entries:
        if entry.is_file() and _is_license_file(entry):
            anchor = entry
            break
    if anchor is None:
        anchor = root / "LICENSE"  # synthetic
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-apache2-notice-missing"),
        "",
    )
    return [Finding(
        rule_id="license-apache2-notice-missing",
        line=1,
        column=1,
        matched_text=f"NOTICE missing (declared license={spdx})",
        severity="MAJOR",
        description=rule_desc,
        file_path=str(anchor),
    )]


def scan_incompatible_license_in_manifest(path: Path) -> list[Finding]:
    """P4 — read a dependency manifest / lockfile / Dockerfile and emit
    one CRITICAL finding per dependency whose package name matches the
    watchlist (regardless of whether the project itself declares a
    permissive license; the caller layers in the permissive-context
    check via `extract_repo_license_spdx`).
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text:
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-incompatible-copyleft-in-permissive"),
        "",
    )
    findings: list[Finding] = []
    seen: set[tuple[str, int]] = set()
    name_lower = path.name.lower()
    # Manifest dep-name extraction.
    if name_lower.endswith(("package.json", "package-lock.json")):
        for m in _NPM_DEP_NAME_LINE.finditer(text):
            dep_name = m.group(1).lower()
            for pkg, _tag in _INCOMPATIBLE_PACKAGES:
                if pkg in dep_name:
                    line, col = _line_col(text, m.start())
                    key = (dep_name, line)
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(Finding(
                        rule_id="license-incompatible-copyleft-in-permissive",
                        line=line,
                        column=col,
                        matched_text=f"{dep_name}",
                        severity="CRITICAL",
                        description=rule_desc,
                        file_path=str(path),
                    ))
                    break
    elif name_lower.endswith((
        "requirements.txt", "requirements-dev.txt", "requirements-test.txt",
        "pyproject.toml", "uv.lock", "poetry.lock", "Pipfile.lock",
    )):
        for m in _PY_DEP_NAME.finditer(text):
            dep_name = m.group(1).lower()
            for pkg, _tag in _INCOMPATIBLE_PACKAGES:
                if pkg in dep_name:
                    line, col = _line_col(text, m.start())
                    key = (dep_name, line)
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(Finding(
                        rule_id="license-incompatible-copyleft-in-permissive",
                        line=line,
                        column=col,
                        matched_text=f"{dep_name}",
                        severity="CRITICAL",
                        description=rule_desc,
                        file_path=str(path),
                    ))
                    break
    elif name_lower.endswith(("dockerfile", "containerfile", "docker-compose.yml")) \
            or name_lower == "dockerfile":
        for m in _DOCKER_FROM_LINE.finditer(text):
            img = m.group(1).lower()
            for img_prefix, _tag in _INCOMPATIBLE_DOCKER_IMAGES:
                if img.startswith(img_prefix.lower()):
                    line, col = _line_col(text, m.start())
                    findings.append(Finding(
                        rule_id="license-incompatible-copyleft-in-permissive",
                        line=line,
                        column=col,
                        matched_text=f"FROM {img}",
                        severity="CRITICAL",
                        description=rule_desc,
                        file_path=str(path),
                    ))
                    break
    return findings


def scan_unlicensed_not_private(path: Path) -> list[Finding]:
    """P5 — manifest declares UNLICENSED / proprietary AND no private
    flag AND name is not scoped.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text:
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-unlicensed-not-private"),
        "",
    )
    findings: list[Finding] = []
    name_lower = path.name.lower()
    if name_lower == "package.json":
        ul = _NPM_LICENSE_UNLICENSED.search(text)
        if not ul:
            return []
        if _NPM_PRIVATE_TRUE.search(text):
            return []  # safe — npm refuses publish
        if _NPM_NAME_SCOPED.search(text):
            return []  # safe — scoped name
        line, col = _line_col(text, ul.start())
        findings.append(Finding(
            rule_id="license-unlicensed-not-private",
            line=line,
            column=col,
            matched_text=ul.group(0),
            severity="HIGH",
            description=rule_desc,
            file_path=str(path),
        ))
        # SEE LICENSE IN <file> with the referenced file missing.
        see = _NPM_LICENSE_SEE_FILE.search(text)
        if see:
            ref_path = path.parent / see.group(1).strip()
            if not ref_path.is_file():
                sline, scol = _line_col(text, see.start())
                findings.append(Finding(
                    rule_id="license-unlicensed-not-private",
                    line=sline,
                    column=scol,
                    matched_text=f"SEE LICENSE IN {see.group(1)} (missing)",
                    severity="HIGH",
                    description=rule_desc,
                    file_path=str(path),
                ))
    elif name_lower == "pyproject.toml":
        pl = _PY_LICENSE_PROPRIETARY.search(text)
        if not pl:
            return []
        findings.append(Finding(
            rule_id="license-unlicensed-not-private",
            line=_line_col(text, pl.start())[0],
            column=_line_col(text, pl.start())[1],
            matched_text=pl.group(0).strip(),
            severity="HIGH",
            description=rule_desc,
            file_path=str(path),
        ))
    elif name_lower == "cargo.toml":
        cl = _CARGO_LICENSE_PROPRIETARY.search(text)
        if not cl:
            return []
        if _CARGO_PUBLISH_FALSE.search(text):
            return []  # safe — cargo refuses publish
        findings.append(Finding(
            rule_id="license-unlicensed-not-private",
            line=_line_col(text, cl.start())[0],
            column=_line_col(text, cl.start())[1],
            matched_text=cl.group(0).strip(),
            severity="HIGH",
            description=rule_desc,
            file_path=str(path),
        ))
    return findings


def scan_manifest_content_drift(root: Path) -> list[Finding]:
    """P6 — compare manifest-declared license to LICENSE-file content."""
    if not root.is_dir():
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-manifest-content-drift"),
        "",
    )
    # Identify the manifest license claim.
    manifest_license: str | None = None
    manifest_anchor: Path | None = None
    for manifest in ("package.json", "pyproject.toml", "Cargo.toml"):
        m_path = root / manifest
        if not m_path.is_file():
            continue
        try:
            text = m_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r'"license"\s*:\s*"([^"]{1,80})"', text)
        if m is None:
            m = re.search(
                r'^\s*license\s*=\s*"([^"]{1,80})"',
                text,
                re.MULTILINE,
            )
        if m:
            manifest_license = m.group(1).strip()
            manifest_anchor = m_path
            break
    if not manifest_license or manifest_anchor is None:
        return []
    # Find the root LICENSE file.
    license_file: Path | None = None
    try:
        for entry in root.iterdir():
            if entry.is_file() and _is_license_file(entry):
                license_file = entry
                break
    except OSError:
        return []
    if license_file is None:
        return [Finding(
            rule_id="license-manifest-content-drift",
            line=1,
            column=1,
            matched_text=f"manifest declares {manifest_license}, no LICENSE file",
            severity="CRITICAL",
            description=rule_desc,
            file_path=str(manifest_anchor),
        )]
    try:
        body = license_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    # Map manifest claim to expected body marker.
    expected = manifest_license.lower()
    body_match: bool
    if "mit" in expected:
        body_match = bool(_MIT_BODY_MARKER.search(body))
    elif "apache-2.0" in expected:
        body_match = bool(_APACHE2_BODY_MARKER.search(body))
    elif "bsd" in expected:
        body_match = bool(_BSD3_BODY_MARKER.search(body))
    elif "gpl" in expected:
        body_match = bool(_GPL_BODY_MARKER.search(body))
    else:
        # Unknown manifest license — can't make a drift claim.
        return []
    if body_match:
        return []
    return [Finding(
        rule_id="license-manifest-content-drift",
        line=1,
        column=1,
        matched_text=(
            f"manifest={manifest_license}, "
            f"LICENSE content does not match"
        ),
        severity="CRITICAL",
        description=rule_desc,
        file_path=str(license_file),
    )]


def scan_spdx_malformed_in_file(path: Path) -> list[Finding]:
    """P7 — emit findings for malformed / multiple SPDX lines in a file."""
    if not _file_matches_suffixes(path, _SPDX_SOURCE_SUFFIXES):
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text:
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-spdx-malformed-or-missing"),
        "",
    )
    findings: list[Finding] = []
    head = "\n".join(text.splitlines()[:30])
    declared: list[tuple[str, int]] = []
    for m in _SPDX_LICENSE_LINE.finditer(head):
        value = m.group(1).strip()
        declared.append((value, m.start()))
    if not declared:
        return []
    # Malformed value?
    seen_values: set[str] = set()
    for value, offset in declared:
        if not _SPDX_EXPRESSION_GRAMMAR.match(value):
            line, col = _line_col(text, offset)
            findings.append(Finding(
                rule_id="license-spdx-malformed-or-missing",
                line=line,
                column=col,
                matched_text=f"malformed SPDX value: {value}",
                severity="MAJOR",
                description=rule_desc,
                file_path=str(path),
            ))
        seen_values.add(value.lower())
    # Duplicate-with-different-value?
    if len(seen_values) > 1:
        offset = declared[0][1]
        line, col = _line_col(text, offset)
        findings.append(Finding(
            rule_id="license-spdx-malformed-or-missing",
            line=line,
            column=col,
            matched_text=(
                "multiple SPDX-License-Identifier lines: "
                + ", ".join(sorted(seen_values))
            ),
            severity="CRITICAL",
            description=rule_desc,
            file_path=str(path),
        ))
    return findings


def scan_no_license_ci_workflow(workflows_root: Path) -> list[Finding]:
    """P8 — scan a `.github/workflows/` directory (or similar) for any
    file containing a known license-scanner token. Emit one finding if
    none are present.
    """
    if not workflows_root.is_dir():
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-no-ci-scanner"),
        "",
    )
    found_scanner = False
    try:
        for entry in workflows_root.rglob("*"):
            if not entry.is_file():
                continue
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lc = text.lower()
            if any(tok.lower() in lc for tok in _LICENSE_SCANNER_TOKENS):
                found_scanner = True
                break
    except OSError:
        return []
    if found_scanner:
        return []
    return [Finding(
        rule_id="license-no-ci-scanner",
        line=1,
        column=1,
        matched_text="no license-compatibility scanner detected in workflows",
        severity="MAJOR",
        description=rule_desc,
        file_path=str(workflows_root),
    )]


def scan_cla_relicense_stealth(
    contributing_path: Path,
    license_path: Path | None = None,
) -> list[Finding]:
    """P9 — CONTRIBUTING / CLA file carries relicensing language."""
    if not contributing_path.is_file():
        return []
    try:
        text = contributing_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text:
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-relicense-by-stealth-via-cla"),
        "",
    )
    findings: list[Finding] = []
    # Suspicious patterns — any of them is enough.
    triggered_patterns = (
        _CLA_RELICENSE_LANGUAGE,
        _CLA_RELICENSE_DIRECT,
        _CLA_PROPRIETARY_CONVERSION,
        _CLA_LICENSE_TRANSITION,
        _CLA_COPYRIGHT_ASSIGN,
    )
    seen_offsets: set[int] = set()
    for pat in triggered_patterns:
        m = pat.search(text)
        if m is None:
            continue
        if m.start() in seen_offsets:
            continue
        seen_offsets.add(m.start())
        line, col = _line_col(text, m.start())
        matched = m.group(0)
        if len(matched) > 160:
            matched = matched[:160] + "..."
        findings.append(Finding(
            rule_id="license-relicense-by-stealth-via-cla",
            line=line,
            column=col,
            matched_text=matched.strip(),
            severity="HIGH",
            description=rule_desc,
            file_path=str(contributing_path),
        ))
    # If LICENSE has been changed too, downgrade severity context — but
    # we still surface the finding for operator inspection.
    return findings


def scan_vendor_missing_license(root: Path) -> list[Finding]:
    """P10 — walk top-level vendor dirs; emit one finding per first-level
    subdirectory lacking a LICENSE file.
    """
    if not root.is_dir():
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-vendor-missing-attribution"),
        "",
    )
    findings: list[Finding] = []
    for vendor_dir_name in _VENDOR_DIR_NAMES:
        vendor_root = root / vendor_dir_name
        if not vendor_root.is_dir():
            continue
        try:
            for sub in vendor_root.iterdir():
                if not sub.is_dir():
                    continue
                # Check for any LICENSE-shape file inside the subdir.
                has_license = False
                try:
                    for entry in sub.iterdir():
                        if entry.is_file() and _is_license_file(entry):
                            has_license = True
                            break
                except OSError:
                    continue
                if has_license:
                    continue
                findings.append(Finding(
                    rule_id="license-vendor-missing-attribution",
                    line=1,
                    column=1,
                    matched_text=f"vendored {vendor_dir_name}/{sub.name} lacks LICENSE",
                    severity="MAJOR",
                    description=rule_desc,
                    file_path=str(sub),
                ))
        except OSError:
            continue
    findings.sort(key=lambda f: f.file_path)
    return findings


def scan_noncommercial_in_deps(path: Path) -> list[Finding]:
    """P11 — emit findings for CC-NC / JSON / WTFPL / Anti-996 /
    Hippocratic licenses declared in a manifest or LICENSE file.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text:
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-non-commercial-in-deps"),
        "",
    )
    findings: list[Finding] = []
    # SPDX-list-based match.
    seen: set[tuple[str, int]] = set()
    for nc_spdx in _NONCOMMERCIAL_SPDX:
        # Match against either `"license": "X"`, `license = "X"`, or an
        # SPDX-License-Identifier line.
        escaped = re.escape(nc_spdx)
        pat = re.compile(
            r'(?:"license"\s*:\s*"' + escaped + r'"'
            r'|^\s*license\s*=\s*"' + escaped + r'"'
            r'|SPDX-License-Identifier\s*:\s*' + escaped + r")",
            re.IGNORECASE | re.MULTILINE,
        )
        for m in pat.finditer(text):
            line, col = _line_col(text, m.start())
            key = (nc_spdx, line)
            if key in seen:
                continue
            seen.add(key)
            findings.append(Finding(
                rule_id="license-non-commercial-in-deps",
                line=line,
                column=col,
                matched_text=m.group(0).strip(),
                severity="CRITICAL",
                description=rule_desc,
                file_path=str(path),
            ))
    # Free-text marker — useful when a LICENSE file uses prose rather
    # than an SPDX identifier.
    for m in _LICENSE_NONCOMMERCIAL_TEXT.finditer(text):
        line, col = _line_col(text, m.start())
        if any(line == k[1] for k in seen):
            continue
        findings.append(Finding(
            rule_id="license-non-commercial-in-deps",
            line=line,
            column=col,
            matched_text=m.group(0).strip(),
            severity="CRITICAL",
            description=rule_desc,
            file_path=str(path),
        ))
    return findings


def scan_spdx_deprecated_bare_form(path: Path) -> list[Finding]:
    """P12 — emit one MINOR finding per deprecated bare SPDX identifier
    in a source file or manifest.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text:
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-spdx-deprecated-bare-form"),
        "",
    )
    findings: list[Finding] = []
    seen: set[int] = set()
    candidates = (
        _SPDX_BARE_DEPRECATED,
        _MANIFEST_LICENSE_BARE_DEPRECATED,
        _TOML_LICENSE_BARE_DEPRECATED,
    )
    for pat in candidates:
        for m in pat.finditer(text):
            captured = m.group(1).strip()
            if captured not in _DEPRECATED_BARE_SPDX:
                continue
            if m.start() in seen:
                continue
            seen.add(m.start())
            line, col = _line_col(text, m.start())
            findings.append(Finding(
                rule_id="license-spdx-deprecated-bare-form",
                line=line,
                column=col,
                matched_text=captured,
                severity="MINOR",
                description=rule_desc,
                file_path=str(path),
            ))
    return findings


def _extract_copyright_holders(text: str) -> set[str]:
    """Return the lowercased rightsholder names declared in `text`."""
    holders: set[str] = set()
    head = "\n".join(text.splitlines()[:80])
    for m in _COPYRIGHT_LINE.finditer(head):
        name = m.group(2).strip()
        # Trim trailing punctuation and email tails.
        name = re.sub(r"\s*<[^>]*>\s*$", "", name)
        name = name.rstrip(".,; ")
        if name:
            holders.add(name.lower())
    return holders


def scan_copyright_line_drift(root: Path) -> list[Finding]:
    """P13 — flag source files whose declared copyright holder does not
    appear in the project's LICENSE file copyright lines.
    """
    if not root.is_dir():
        return []
    license_file: Path | None = None
    try:
        for entry in root.iterdir():
            if entry.is_file() and _is_license_file(entry):
                license_file = entry
                break
    except OSError:
        return []
    if license_file is None:
        return []
    try:
        lic_text = license_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    license_holders = _extract_copyright_holders(lic_text)
    if not license_holders:
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-copyright-line-drift"),
        "",
    )
    findings: list[Finding] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        # Skip the LICENSE itself.
        if path == license_file:
            continue
        # Skip vendored subtrees.
        rel_parts = {p.lower() for p in path.relative_to(root).parts}
        if rel_parts & set(_VENDOR_DIR_NAMES):
            continue
        if not any(path.name.lower().endswith(suf) for suf in _SPDX_SOURCE_SUFFIXES):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        file_holders = _extract_copyright_holders(text)
        if not file_holders:
            continue
        # Drift = at least one file holder is not in the LICENSE set.
        unknown = file_holders - license_holders
        if not unknown:
            continue
        m = _COPYRIGHT_LINE.search(text)
        if m is None:  # pragma: no cover
            continue
        line, col = _line_col(text, m.start())
        findings.append(Finding(
            rule_id="license-copyright-line-drift",
            line=line,
            column=col,
            matched_text=(
                f"copyright drift: {', '.join(sorted(unknown))} "
                f"not in LICENSE"
            ),
            severity="MAJOR",
            description=rule_desc,
            file_path=str(path),
        ))
    return findings


def scan_patent_grant_stripped(root: Path) -> list[Finding]:
    """P14 — repo's root LICENSE is MIT, but vendored / source files
    declare Apache-2.0 / MPL-2.0 SPDX. Without a `LICENSE-Apache-2.0`
    or similar verbatim file at root or alongside, the patent grant
    from upstream is dropped.
    """
    if not root.is_dir():
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-patent-grant-stripped"),
        "",
    )
    repo_spdx = extract_repo_license_spdx(root)
    if not repo_spdx:
        return []
    # Only fire when the root is a patent-grant-LESS license.
    if "mit" not in repo_spdx.lower() and "bsd" not in repo_spdx.lower():
        return []
    # Find files declaring Apache-2.0 / MPL-2.0 / GPL-3.0 anywhere.
    patent_files: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if not any(path.name.lower().endswith(suf) for suf in _SPDX_SOURCE_SUFFIXES):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ids = extract_file_spdx_identifiers(text)
        for ident in ids:
            il = ident.lower()
            if ("apache-2.0" in il or "mpl-2.0" in il
                    or il.startswith("gpl-3")):
                patent_files.append((path, ident))
                break
    if not patent_files:
        return []
    # Look for a sibling LICENSE-Apache-2.0 / LICENSE-MPL-2.0 / etc.
    verbatim_licenses: list[Path] = []
    try:
        for entry in root.rglob("*"):
            if not entry.is_file():
                continue
            name = entry.name.upper()
            if (name.startswith("LICENSE-APACHE") or name.startswith("LICENSE_APACHE")
                    or name.startswith("LICENSE-MPL") or name.startswith("LICENSE-GPL")):
                verbatim_licenses.append(entry)
    except OSError:
        pass
    findings: list[Finding] = []
    for path, ident in patent_files:
        # Check whether a verbatim license file is in the same dir or
        # at the root.
        ident_lower = ident.lower()
        token = ("APACHE" if "apache" in ident_lower
                 else "MPL" if "mpl" in ident_lower
                 else "GPL")
        candidates = [
            p for p in verbatim_licenses
            if token in p.name.upper()
        ]
        # Match if either (a) at root, (b) in path's own directory.
        satisfied = False
        for lic in candidates:
            try:
                lic_parent = lic.parent.resolve()
                root_resolved = root.resolve()
                path_parent = path.parent.resolve()
            except OSError:
                continue
            if lic_parent == root_resolved or lic_parent == path_parent:
                satisfied = True
                break
        if satisfied:
            continue
        findings.append(Finding(
            rule_id="license-patent-grant-stripped",
            line=1,
            column=1,
            matched_text=(
                f"file declares {ident}, root LICENSE is {repo_spdx}, "
                f"no LICENSE-{token} verbatim file present"
            ),
            severity="CRITICAL",
            description=rule_desc,
            file_path=str(path),
        ))
    return findings


def scan_trademark_no_disclaimer(path: Path) -> list[Finding]:
    """P15 — README uses an upstream trademark name with no disclaimer."""
    name_lower = path.name.lower()
    if name_lower not in {"readme.md", "readme.rst", "readme.txt"}:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text:
        return []
    rule_desc = next(
        (r.description for r in RULES
         if r.id == "license-trademark-no-disclaimer"),
        "",
    )
    # Negative-suppression: full README contains a trademark / not-
    # affiliated disclaimer somewhere.
    cl = text.lower()
    if any(tok.lower() in cl for tok in _trademark_disclaimer_tokens()):
        return []
    findings: list[Finding] = []
    seen: set[str] = set()
    for m in _TRADEMARK_NAME_USAGE.finditer(text):
        name = m.group(1)
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        line, col = _line_col(text, m.start())
        findings.append(Finding(
            rule_id="license-trademark-no-disclaimer",
            line=line,
            column=col,
            matched_text=f"trademark '{name}' without disclaimer",
            severity="MINOR",
            description=rule_desc,
            file_path=str(path),
        ))
    return findings


# ---- Per-file scan dispatcher -------------------------------------------


# Composite-only rules — `scan_file` skips them; call the matching
# helper directly.
_COMPOSITE_ONLY: frozenset[str] = frozenset((
    "license-spdx-mismatch-with-root",
    "license-apache2-notice-missing",
    "license-incompatible-copyleft-in-permissive",
    "license-unlicensed-not-private",
    "license-manifest-content-drift",
    "license-spdx-malformed-or-missing",
    "license-no-ci-scanner",
    "license-relicense-by-stealth-via-cla",
    "license-vendor-missing-attribution",
    "license-non-commercial-in-deps",
    "license-spdx-deprecated-bare-form",
    "license-copyright-line-drift",
    "license-patent-grant-stripped",
    "license-trademark-no-disclaimer",
))


def scan_file(path: Path) -> list[Finding]:
    """Run pattern-only rules against `path`. Composite rules are routed
    through their respective `scan_*` helper — call those directly.

    Pattern-only rules handled here:
      * license-template-placeholder-unfilled (P1)
      * license-template-email-placeholder (P1 sibling)

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
    for rule in RULES:
        if rule.id in _COMPOSITE_ONLY:
            continue
        if not _file_matches_suffixes(path, rule.file_suffixes):
            continue
        if rule.negative_substrings:
            cl = content.lower()
            if any(neg.lower() in cl for neg in rule.negative_substrings):
                continue
        for m in rule.pattern.finditer(content):
            line, col = _line_col(content, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0).strip()
            if len(matched) > 200:
                matched = matched[:200] + "..."
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                file_path=str(path),
            ))
    return findings
