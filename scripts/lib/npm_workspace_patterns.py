"""npm workspaces / pnpm catalog / Yarn berry workspace POISONING detector.

Companion to `pkg_bypass_patterns.py` (Wave 16), which catches install-time
BYPASS FLAGS (`--ignore-scripts=false`, `--no-frozen-lockfile`, etc.). This
module catches an entirely orthogonal surface: the workspace-graph fields
and dependency-protocol prefixes that LIVE INSIDE `package.json` /
`pnpm-workspace.yaml` / `.lockfile-lintrc`.

Distill round 5 angle G enumerates 15 such surfaces — `link:` / `portal:` /
`file:` protocols, `workspace:*` shadowing, `resolutions` / `overrides`,
`packageExtensions`, git-URL deps, `bundleDependencies`,
`peerDependenciesMeta.optional: true`, workspace dep cycles, lax
`engines.node`, lockfile-lint allowed-hosts misconfig, secret-copy
`prepublishOnly`, `npm-shrinkwrap.json` shadow, pnpm `catalogs:`,
and the composite "override pointing at git-URL" rule.

Every rule below is on a distinct file-and-field. No overlap with Wave 16
(command-line bypass) and no overlap with `package-manager-policy.py`
(missing-hardening config). All patterns are RE2-safe (no backreferences,
no lookarounds beyond what RE2 supports — but in practice this code uses
the `re` module and avoids backreferences/lookbehind regardless, so the
patterns can be lifted into RE2 unmodified).

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi, ecosystem,
         file_anchor)
                                  — single rule record.
  * RULES                         — ordered tuple of every catalogued
                                    workspace-poisoning rule (15 total).
  * scan_text(text, *, filename=None)  -> list[Finding]
                                  — run every rule against `text`. When
                                    `filename` is supplied, rules with a
                                    `file_anchor` only fire if the filename
                                    matches.
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi, ecosystem)
                                  — single finding record. Frozen.

Severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW" — same convention
as `pkg_bypass_patterns.py`. OWASP ASI tag is ASI-05 (Insecure Supply
Chain) for every rule in this module since every workspace-poisoning
finding weakens supply-chain integrity.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as `pkg_bypass_patterns.Finding`
    so consumers can render findings from either module uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str
    ecosystem: str  # e.g. "npm", "pnpm", "yarn", "bun"


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load.

    `file_anchor` is an optional case-insensitive suffix that gates a
    rule to a specific filename (e.g. `pnpm-workspace.yaml`). When
    set, callers MUST pass `filename=...` to `scan_text` for the rule
    to fire. When `None`, the rule fires on any text passed in (the
    caller is responsible for scope-gating in the detector wrapper).
    """

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str
    ecosystem: str
    file_anchor: str | None  # None => no per-file gating


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with MULTILINE + UNICODE.

    NOTE: case-sensitivity is INTENTIONAL here, unlike
    `pkg_bypass_patterns._re`. JSON keys (`"dependencies"`,
    `"resolutions"`, etc.) and YAML keys (`packageExtensions:`,
    `catalogs:`) are case-SENSITIVE in their respective specs — a
    fuzzy match on `"Dependencies"` would be a false positive against
    a vendor-shaped field that doesn't actually affect the install.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- Rule 1: link:/portal: protocol with parent traversal (CRITICAL) ----

# Documented Yarn berry / pnpm protocol prefixes. `link:` and `portal:`
# resolve to a directory and treat its contents as a package — the linked
# dir's `package.json` is read at install time and `prepare`/`postinstall`
# scripts run with full Node permissions, INCLUDING under
# `--ignore-scripts` on Yarn <= 3.x (the linked dir is treated as
# first-party local code, not as an installed dependency).
#
# Dangerous shapes (rule fires):
#   "my-dep": "link:../../../../tmp/attacker"  (parent traversal)
#   "my-dep": "link:/etc/secrets"              (absolute path)
#   "my-dep": "link:C:\\Windows\\System32"     (Windows drive letter)
#   "my-dep": "portal:../sibling/lib"          (parent traversal)
#
# Safe shapes (rule does NOT fire):
#   "my-dep": "link:./packages/util"           (workspace-internal)
#   "my-dep": "link:packages/util"             (bare relative)
#   "my-dep": "portal:./local/lib"             (workspace-internal)
#
# RE2-safe: pure alternation, no backreference, no lookaround.
_LINK_PORTAL_TRAVERSAL = _re(
    r'"[a-zA-Z0-9@/_.-]+"\s*:\s*"(?:link|portal):'
    r"(?:[^\"]*\.\.[\\/]|/[^/\"]|[a-zA-Z]:[\\/])"
    r'[^"]*"',
)


# ---- Rule 2: file: protocol with path traversal or absolute (HIGH) ------

# `file:` is the npm-spec workspace protocol for pointing at a local
# tarball or directory. A path like
# `"file:../../../etc/secrets/legit-looking.tgz"` instructs npm to
# extract a tarball from outside the project tree.
#
# Distinct from Rule 1: `file:` is treated by npm core as a TARBALL
# EXTRACT (not just a symlink), so the attack surface is every
# post-extract file operation inside the tarball, not just install
# scripts.
#
# Dangerous shapes (rule fires):
#   "my-dep": "file:../../../etc/secrets/legit.tgz"
#   "my-dep": "file:/var/tmp/attacker.tgz"
#   "my-dep": "file://../../parent.tgz"
#   "my-dep": "file:C:\\Users\\Public\\evil.tgz"
#
# Safe shapes (rule does NOT fire):
#   "my-dep": "file:./packages/util"           (workspace-internal)
#   "my-dep": "file:./vendor/local.tgz"        (workspace-internal)
#
# RE2-safe.
_FILE_PROTOCOL_TRAVERSAL = _re(
    r'"[a-zA-Z0-9@/_.-]+"\s*:\s*"file:(?://)?'
    r"(?:\.\.[\\/]|/[^/\"]|[a-zA-Z]:[\\/])"
    r'[^"]*"',
)


# ---- Rule 3: workspace:* protocol on UNSCOPED name (HIGH) ---------------

# pnpm / Yarn berry resolve `workspace:*` (and `workspace:^`, `workspace:~`)
# to the sibling workspace package whose `name` field matches. If the
# monorepo ships `packages/lodash/package.json` with
# `"name": "lodash"`, then `"lodash": "workspace:*"` resolves to the
# WORKSPACE one. The danger surfaces when the workspace ever publishes
# the same name (with a typoed/dropped scope) to the public registry.
#
# Heuristic: fire on `workspace:*`/`workspace:^`/`workspace:~` where
# the dep NAME is UNSCOPED (no leading `@scope/`). Scoped names
# (`@myorg/lodash`) are far less likely to collide with public
# packages — this is the false-positive guard built into the regex.
#
# Dangerous shapes (rule fires):
#   "lodash": "workspace:*"
#   "axios": "workspace:^"
#   "react": "workspace:~"
#
# Safe shapes (rule does NOT fire):
#   "@myorg/internal-utils": "workspace:*"     (scoped, low collision)
#   "lodash": "^4.17.21"                       (registry version)
#
# RE2-safe. We force the first character of the dep name to be in
# `[a-zA-Z0-9_]` — that excludes `@` by character-class construction,
# no lookahead needed. RE2 does NOT support negative lookahead.
_WORKSPACE_PROTOCOL_UNSCOPED = _re(
    r'"[a-zA-Z0-9_][a-zA-Z0-9_.-]*"\s*:\s*'
    r'"workspace:[*^~][^"]*"',
)


# ---- Rule 4: resolutions / overrides block declared (HIGH) --------------

# `resolutions` (Yarn) and `overrides` (npm 8.3+) are documented features
# for pinning transitive deps the project owner doesn't directly depend
# on. They BYPASS the normal install resolution: the lockfile's
# `integrity` field for the indirect dep gets replaced, and `npm audit`
# may not flag the override target because the override's authoring user
# is presumed trusted.
#
# Rule fires on the MERE PRESENCE of a non-empty `resolutions:` or
# `overrides:` block at top level of `package.json`. Severity is HIGH
# by default; detectors can promote to CRITICAL if the override target
# is on the security-critical-deps curated list.
#
# Dangerous shapes (rule fires):
#   "resolutions": { "lodash": "0.0.1-malicious" }
#   "overrides": { "@scope/critical-dep": "0.0.1-malicious" }
#
# Safe shapes (rule does NOT fire):
#   "resolutions": {}                          (empty)
#   no `resolutions` / `overrides` key
#
# RE2-safe. The `{0,4096}` bounded quantifier avoids ReDoS on a
# pathologically large empty object.
_RESOLUTIONS_OR_OVERRIDES = _re(
    r'"(?:resolutions|overrides)"\s*:\s*\{[^}]{0,4096}'
    r'"[a-zA-Z0-9@/_*<>~^.-]+"\s*:\s*"[^"]+"',
)


# ---- Rule 5: pnpm packageExtensions injection (HIGH) --------------------

# pnpm's `packageExtensions` field forcibly rewrites a published
# package's `package.json` AT INSTALL TIME on the consumer's machine.
# The legitimate use is `peerDependenciesMeta: optional: true` to
# silence noisy peer warnings.
#
# The malicious use:
#   packageExtensions:
#     "trusted-package":
#       dependencies:
#         "@attacker/innocuous-name": "*"
#
# Every install now ALSO installs `@attacker/innocuous-name`, fully
# with its postinstall scripts, and the dependency appears in
# node_modules WITHOUT a corresponding line in any package.json the
# developer reads.
#
# Rule fires on the MERE PRESENCE of a top-level `packageExtensions:`
# block followed by a nested `dependencies:` or `peerDependencies:`
# (NOT `peerDependenciesMeta:` — that's the documented legitimate use).
#
# Pattern walks lines because this is YAML. RE2-safe.
_PACKAGE_EXTENSIONS_INJECTION = _re(
    r"^packageExtensions\s*:\s*$"
    r"(?:\n[ \t]+[^\n]*){1,200}?"
    r"\n[ \t]+(?:dependencies|peerDependencies)\s*:\s*$",
)


# ---- Rule 6: git URL dependency (HIGH) ----------------------------------

# A dep value of `"my-dep": "github:attacker/repo#commit"` makes npm
# clone the git repo and RUN `npm install --ignore-scripts=false`
# inside the clone PLUS run `prepare` script if defined. The `prepare`
# script is documented to run on install from git — the npm registry
# does NOT see this tarball, so registry-side validation (`npm audit`,
# provenance attestations, package signing) is BYPASSED.
#
# Even the user-side `minimum-release-age` / `npmMinimalAgeGate`
# gates do NOT fire on git deps because there is no published version
# with a publish timestamp.
#
# Dangerous shapes (rule fires):
#   "my-dep": "github:attacker/repo#abc123"
#   "my-dep": "git+https://github.com/attacker/repo.git"
#   "my-dep": "git+ssh://git@github.com/attacker/repo.git"
#   "my-dep": "gitlab:attacker/repo"
#   "my-dep": "bitbucket:attacker/repo"
#
# Safe shapes (rule does NOT fire):
#   "my-dep": "^1.0.0"                         (registry semver)
#   "my-dep": "https://example.com/tgz"        (https tarball)
#
# RE2-safe.
_GIT_URL_DEP = _re(
    r'"[a-zA-Z0-9@/_.-]+"\s*:\s*"'
    r"(?:github:|git\+|git:|gitlab:|bitbucket:)"
    r'[^"]+"',
)


# ---- Rule 7: bundleDependencies / bundledDependencies declared (MEDIUM) -

# `bundleDependencies` instructs npm to include the listed deps' tarball
# CONTENT inside the publishing package's own tarball. Two consequences:
# (1) the bundled bytes can differ from the registry's same-version;
# (2) the integrity check on install uses the publisher's own tarball
# checksum, not the registry's, so registry-side compromise detection
# does not fire on the bundled bytes.
#
# Rule fires on the MERE PRESENCE of a non-empty `bundleDependencies`
# or `bundledDependencies` array.
#
# RE2-safe. We require a NON-EMPTY array (at least one quoted entry)
# to filter out the documented "`"bundleDependencies": []`" idiom that
# some tooling emits as a no-op.
_BUNDLE_DEPENDENCIES = _re(
    r'"(?:bundleDependencies|bundledDependencies)"\s*:\s*'
    r'\[\s*"[^"]+"',
)


# ---- Rule 8: peerDependenciesMeta.optional: true (LOW) ------------------

# `optional: true` in `peerDependenciesMeta` tells the package manager
# to NOT WARN when a peer is missing or mismatched. The legitimate use
# is to soft-depend on a peer that some consumers don't need. The
# misuse: an attacker who lands a PR adding an optional peer entry for
# a malicious package gets the package SILENTLY INSTALLED when present
# in the dep tree (because lockfile honors it) without any of the
# normal "version mismatch" warnings consumers rely on for change
# detection.
#
# Low severity because the package still has to enter the tree some
# other way; this rule complements Proposals 4 / 5 / 6 by removing
# the warning channel.
#
# RE2-safe. Bounded `{0,2048}` keeps the search cheap.
_PEER_DEPS_META_OPTIONAL = _re(
    r'"peerDependenciesMeta"\s*:\s*\{'
    r'[^}]{0,2048}"optional"\s*:\s*true',
)


# ---- Rule 9: Workspace cycle amplification marker (MEDIUM) ---------------

# True cycle detection requires a graph walk over every workspace
# package's deps — that's a parser-level rule, not a regex. The regex
# leg of this module catches the AMPLIFICATION CANDIDATE: a
# `package.json` that has BOTH a `workspace:`-protocol dependency AND
# a `postinstall` (or `preinstall`) script. Either alone is benign;
# both together means the package is BOTH a node in the workspace
# graph (so any cycle that touches it amplifies) AND ships a hook
# that runs eagerly when a cycle partner is installed.
#
# Backreferences are NOT RE2-safe — we explicitly avoid them. The
# pattern uses two `[^]` greedy bodies bounded by `{0,8192}` to keep
# the search linear-time.
#
# Marker shape (rule fires):
#   { "scripts": { "postinstall": "..." },
#     "dependencies": { "@scope/x": "workspace:*" } }
#
# Full multi-package cycle detection lives in `pkg_workspace_graph.py`
# (future Wave 19 work).
_WORKSPACE_DEP_PLUS_POSTINSTALL = _re(
    r'"(?:postinstall|preinstall)"\s*:\s*"[^"]+"'
    r'[\s\S]{0,8192}'
    r'"[a-zA-Z0-9@/_.-]+"\s*:\s*"workspace:'
    r"|"
    r'"[a-zA-Z0-9@/_.-]+"\s*:\s*"workspace:'
    r'[\s\S]{0,8192}'
    r'"(?:postinstall|preinstall)"\s*:\s*"[^"]+"',
)


# ---- Rule 10: engines.node unbounded (LOW) ------------------------------

# Lax `engines.node` allows installation on EOL Node versions with
# known unpatched CVEs. An attacker publishing a malicious package can
# target the long tail of developers still on EOL Node; refusing to
# install on EOL Node closes this attack tail.
#
# Dangerous shapes (rule fires):
#   "engines": { "node": "*" }
#   "engines": { "node": ">=0" }
#   "engines": { "node": ">=4" }
#   "engines": { "node": "" }
#
# Safe shapes (rule does NOT fire):
#   "engines": { "node": ">=18" }
#   "engines": { "node": "^22" }
#
# RE2-safe.
_ENGINES_NODE_UNBOUNDED = _re(
    r'"engines"\s*:\s*\{[^}]{0,1024}'
    r'"node"\s*:\s*"'
    r"(?:"
    r"\*"                                 # any
    r"|>=?\s*0"                           # >= 0 or > 0
    r"|>=?\s*[1-9]\b"                     # >= 1..9 (single-digit, EOL Node 4..16 area)
    r"|>=?\s*1[0-6]\b"                    # >= 10..16 (EOL)
    r"|"                                  # empty
    r')"',
)


# ---- Rule 11: lockfile-lintrc allowed-hosts missing npmjs (HIGH) --------

# `lockfile-lint` validates `package-lock.json#resolved` URLs against a
# host allowlist. If the allowlist DOESN'T include `registry.npmjs.org`,
# it doesn't restrict to it. A maliciously crafted lockfile whose
# `resolved` URLs point at `attacker-mirror.example.com` passes the lint
# as long as `attacker-mirror.example.com` is in the allowlist.
#
# Rule fires on a `.lockfile-lintrc` / `.lockfile-lintrc.json` /
# `.lockfile-lint.json` whose `allowed-hosts` array is declared.
#
# RE2 does NOT support negative lookahead, so we can't express "an
# allowed-hosts array that does NOT contain `registry.npmjs.org`" in
# a single regex. The regex leg matches the MERE PRESENCE of an
# `allowed-hosts` array (non-empty); the detector level walks the
# parsed JSON and demotes findings whose array DOES include
# `registry.npmjs.org`. This keeps the regex linear-time and shifts
# the contains-check to the detector where JSON parsing is already
# happening.
#
# RE2-safe. Bounded `{0,4096}`.
_LOCKFILE_LINTRC_ALLOWED_HOSTS = _re(
    r'"allowed-hosts"\s*:\s*\[[^\]]{0,4096}"[^"]+"[^\]]{0,4096}\]',
)


# ---- Rule 12: prepublishOnly script copies secrets (MEDIUM) -------------

# `prepublishOnly` runs ONLY on `npm publish` (not on consumer install),
# so the publisher's CI can stage files into the published tarball that
# the consumer would never accept in source. An attacker who compromises
# the publisher's CI can add `cp .env dist/` to `prepublishOnly`; the
# published tarball contains the publisher's secrets; every consumer
# install unpacks them.
#
# Rule fires on a `prepublishOnly` script value that contains BOTH a
# file-copy tool (cp/cpx/rsync/fs-extra/copy-file/copy-files) AND a
# secret-name token (secret/env/config/key/token/.env).
#
# RE2-safe. Two `[^"]*` segments — bounded by the JSON string
# terminator. No backreference, no lookbehind.
_PREPUBLISHONLY_SECRET_COPY = _re(
    r'"prepublishOnly"\s*:\s*"'
    r'[^"]*(?:\bcp\b|\bcpx\b|\brsync\b|fs-extra|copy-file|copy-files)'
    r'[^"]*(?:secret|env|config|key|token|\.env)'
    r'[^"]*"',
)


# ---- Rule 13: npm-shrinkwrap.json filename marker (MEDIUM) --------------

# `npm-shrinkwrap.json` was npm's pre-package-lock dependency-pinning
# mechanism and is STILL honored — when both files exist, npm reads
# shrinkwrap and IGNORES package-lock. An attacker who lands
# `npm-shrinkwrap.json` with resolved URLs pointing to a typosquat
# tarball gets every install to fetch the typosquat, while
# `package-lock.json` shows clean origins.
#
# Regex leg: catches the FILENAME REFERENCE inside CI / Docker / docs.
# Cross-file co-existence detection ("both shrinkwrap AND package-lock
# present in the same dir") is a detector-level rule in
# `pkg-workspace-graph.py`; this regex only catches the filename
# being referenced (e.g. a workflow step that ADD-COMMITS a
# shrinkwrap.json without removing package-lock.json).
#
# RE2-safe.
_SHRINKWRAP_FILENAME = _re(
    r"\bnpm-shrinkwrap\.json\b",
)


# ---- Rule 14: pnpm catalogs: declared (MEDIUM) --------------------------

# pnpm catalogs (since 8.10) let one file set the version of a
# dependency for every workspace package that uses `"my-dep": "catalog:"`.
# A single PR editing `pnpm-workspace.yaml` upgrades the dep EVERYWHERE
# in the monorepo — no per-package commit, no per-package diff, no
# per-package CODEOWNERS notification.
#
# Rule fires on the MERE PRESENCE of a top-level `catalogs:` (plural)
# or `catalog:` (singular) key in `pnpm-workspace.yaml`. Detectors can
# promote severity when CODEOWNERS coverage of `pnpm-workspace.yaml`
# is absent, or when Dependabot/Renovate is configured to auto-merge
# changes to that file.
#
# RE2-safe. Anchored to start-of-line.
_PNPM_CATALOGS = _re(
    r"^catalogs?\s*:\s*$",
)


# ---- Rule 15: override value is a non-registry source (CRITICAL) --------

# Composite of Rules 1+2+4+6: an `overrides`/`resolutions` block forcing
# a transitive dep to a non-registry source. Combining "force every
# transitive of X to resolve to Y" with "Y is a git URL / link: /
# portal: / file: the registry can't audit" is the strongest version of
# this attack class. The override bypasses the lockfile pin; the
# non-registry source bypasses the registry pin; nothing fires
# downstream.
#
# Dangerous shapes (rule fires):
#   "overrides": { "lodash": "github:attacker/lodash#abc" }
#   "resolutions": { "axios": "git+https://attacker/repo" }
#   "overrides": { "react": "link:../../tmp/attacker" }
#   "resolutions": { "lodash": "file:../attacker.tgz" }
#
# RE2-safe. Bounded `{0,4096}`.
_OVERRIDE_NON_REGISTRY = _re(
    r'"(?:resolutions|overrides)"\s*:\s*\{[^}]{0,4096}'
    r'"[a-zA-Z0-9@/_*<>~^.-]+"\s*:\s*'
    r'"(?:github:|git\+|git:|gitlab:|bitbucket:|file:|link:|portal:)'
    r'[^"]+"',
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="PKG-WORKSPACE-LINK-PROTOCOL-OUTSIDE-REPO",
        name="link: / portal: protocol path outside repo root",
        severity="CRITICAL",
        description=(
            "A package.json dependency uses link: or portal: protocol with a "
            "parent-traversal (..), absolute path (/), or Windows drive "
            "letter — resolves OUTSIDE the project tree. Linked dir's "
            "prepare/postinstall scripts run with full Node permissions, "
            "INCLUDING under --ignore-scripts on Yarn <= 3.x. "
            "(distill-round-5 proposal 1)"
        ),
        pattern=_LINK_PORTAL_TRAVERSAL,
        owasp_asi="ASI-05",
        ecosystem="npm",
        file_anchor="package.json",
    ),
    Rule(
        id="PKG-WORKSPACE-FILE-PROTOCOL-TRAVERSAL",
        name="file: protocol with path traversal",
        severity="HIGH",
        description=(
            "A package.json dependency uses file: protocol with a "
            "parent-traversal (..), absolute path (/), or Windows drive "
            "letter. npm core treats file: as a TARBALL EXTRACT — every "
            "post-extract file operation inside the tarball is in-scope, "
            "not just install scripts. "
            "(distill-round-5 proposal 2)"
        ),
        pattern=_FILE_PROTOCOL_TRAVERSAL,
        owasp_asi="ASI-05",
        ecosystem="npm",
        file_anchor="package.json",
    ),
    Rule(
        id="PKG-WORKSPACE-PROTOCOL-SHADOW",
        name="workspace:* on unscoped name shadows public package",
        severity="HIGH",
        description=(
            "An unscoped package name is bound to workspace:* / workspace:^ / "
            "workspace:~ — shadows any same-name public-registry package. "
            "Downstream consumers of the monorepo's PUBLIC artifact get the "
            "workspace version baked in; if the workspace ever publishes "
            "the same name under a different scope (or drops the scope by "
            "mistake), the public name is squatted. "
            "(distill-round-5 proposal 3)"
        ),
        pattern=_WORKSPACE_PROTOCOL_UNSCOPED,
        owasp_asi="ASI-05",
        ecosystem="pnpm",
        file_anchor="package.json",
    ),
    Rule(
        id="PKG-WORKSPACE-RESOLUTIONS-OVERRIDE-TRANSITIVE",
        name="Yarn resolutions / npm overrides forcing transitive",
        severity="HIGH",
        description=(
            "A top-level resolutions (Yarn) or overrides (npm 8.3+) block "
            "is declared. BYPASSES normal install resolution: lockfile "
            "integrity for the indirect dep is replaced, and npm audit "
            "may not flag the override target. Severity bumped to CRITICAL "
            "by the detector when the override target is on the "
            "security-critical-deps curated list. "
            "(distill-round-5 proposal 4)"
        ),
        pattern=_RESOLUTIONS_OR_OVERRIDES,
        owasp_asi="ASI-05",
        ecosystem="npm",
        file_anchor="package.json",
    ),
    Rule(
        id="PKG-WORKSPACE-PACKAGEEXTENSIONS-INJECTION",
        name="pnpm packageExtensions injecting dependencies",
        severity="HIGH",
        description=(
            "pnpm-workspace.yaml declares a packageExtensions block that ADDS "
            "dependencies or peerDependencies to a third-party package at "
            "install time. The legitimate use is peerDependenciesMeta: "
            "optional: true (warning silencer). Adding dependencies / "
            "peerDependencies forcibly grafts a hidden dep onto a benign "
            "upstream — the dep appears in node_modules without a "
            "corresponding line in any package.json the developer reads. "
            "(distill-round-5 proposal 5)"
        ),
        pattern=_PACKAGE_EXTENSIONS_INJECTION,
        owasp_asi="ASI-05",
        ecosystem="pnpm",
        file_anchor="pnpm-workspace.yaml",
    ),
    Rule(
        id="PKG-WORKSPACE-GIT-URL-DEP-PREPARE-RCE",
        name="git URL dependency runs prepare script",
        severity="HIGH",
        description=(
            "A package.json dependency value is a git URL (github:, git+, "
            "git:, gitlab:, bitbucket:). npm clones the repo and runs npm "
            "install --ignore-scripts=false inside the clone PLUS runs the "
            "prepare script. The npm registry does NOT see this tarball — "
            "provenance attestations, package signing, minimum-release-age "
            "gates ALL BYPASSED. "
            "(distill-round-5 proposal 6)"
        ),
        pattern=_GIT_URL_DEP,
        owasp_asi="ASI-05",
        ecosystem="npm",
        file_anchor="package.json",
    ),
    Rule(
        id="PKG-WORKSPACE-BUNDLE-DEPENDENCIES-TARBALL",
        name="bundleDependencies / bundledDependencies declared",
        severity="MEDIUM",
        description=(
            "package.json declares a non-empty bundleDependencies (or "
            "bundledDependencies) array. The bundled bytes ship inside the "
            "publisher's tarball, not from the registry — bundled lodash "
            "can differ from registry lodash@<same-version>, and the "
            "integrity check uses the publisher's checksum, bypassing "
            "registry-side compromise detection. "
            "(distill-round-5 proposal 7)"
        ),
        pattern=_BUNDLE_DEPENDENCIES,
        owasp_asi="ASI-05",
        ecosystem="npm",
        file_anchor="package.json",
    ),
    Rule(
        id="PKG-WORKSPACE-PEER-DEP-META-OPTIONAL-TRUE",
        name="peerDependenciesMeta.optional: true silences warning",
        severity="LOW",
        description=(
            "package.json declares peerDependenciesMeta with optional: true. "
            "Suppresses the normal 'peer version mismatch' warning consumers "
            "rely on for change detection. Low-severity on its own; "
            "amplifies proposals 4 / 5 / 6 by removing the warning channel. "
            "(distill-round-5 proposal 8)"
        ),
        pattern=_PEER_DEPS_META_OPTIONAL,
        owasp_asi="ASI-05",
        ecosystem="npm",
        file_anchor="package.json",
    ),
    Rule(
        id="PKG-WORKSPACE-CYCLE-AMPLIFICATION",
        name="workspace: dep + postinstall script in same package",
        severity="MEDIUM",
        description=(
            "A package.json declares BOTH a workspace:-protocol dep AND a "
            "postinstall (or preinstall) script. Either alone is benign; "
            "together the package is a cycle-amplification candidate — if "
            "any workspace cycle touches it, the postinstall fires on "
            "every install of any cycle partner. Full multi-package cycle "
            "detection lives in pkg_workspace_graph.py (future wave). "
            "(distill-round-5 proposal 9, regex leg only)"
        ),
        pattern=_WORKSPACE_DEP_PLUS_POSTINSTALL,
        owasp_asi="ASI-05",
        ecosystem="pnpm",
        file_anchor="package.json",
    ),
    Rule(
        id="PKG-WORKSPACE-ENGINES-NODE-UNBOUNDED",
        name="engines.node unbounded (allows EOL Node)",
        severity="LOW",
        description=(
            "package.json declares engines.node as '*', '>=0', a "
            "single-digit floor, or an EOL major (Node 4..16). Allows "
            "install on EOL Node versions with known unpatched CVEs. "
            "An attacker publishing a malicious package can target the "
            "long tail of developers still on EOL Node. "
            "(distill-round-5 proposal 10)"
        ),
        pattern=_ENGINES_NODE_UNBOUNDED,
        owasp_asi="ASI-05",
        ecosystem="npm",
        file_anchor="package.json",
    ),
    Rule(
        id="PKG-WORKSPACE-LOCKFILE-LINTRC-ALLOWED-HOSTS",
        name="lockfile-lint allowed-hosts declared (audit contents)",
        severity="HIGH",
        description=(
            ".lockfile-lintrc declares an allowed-hosts array. The regex "
            "leg fires on PRESENCE of the array — the detector (which "
            "parses the JSON) demotes findings whose array contains ONLY "
            "registry.npmjs.org and promotes findings whose array contains "
            "attacker-mirror-shaped hosts. A maliciously crafted lockfile "
            "whose resolved URLs point at attacker-mirror.example.com "
            "passes lint as long as that mirror is in the allowlist. "
            "(distill-round-5 proposal 11, regex leg)"
        ),
        pattern=_LOCKFILE_LINTRC_ALLOWED_HOSTS,
        owasp_asi="ASI-05",
        ecosystem="npm",
        file_anchor=".lockfile-lintrc",
    ),
    Rule(
        id="PKG-WORKSPACE-PREPUBLISHONLY-SECRET-COPY",
        name="prepublishOnly script copies secrets into tarball",
        severity="MEDIUM",
        description=(
            "package.json prepublishOnly script combines a file-copy tool "
            "(cp / cpx / rsync / fs-extra / copy-file / copy-files) with "
            "a secret-name token (secret / env / config / key / token / "
            ".env). prepublishOnly runs ONLY on npm publish, so consumers "
            "never see the source command; the published tarball contains "
            "the publisher's secrets. "
            "(distill-round-5 proposal 12)"
        ),
        pattern=_PREPUBLISHONLY_SECRET_COPY,
        owasp_asi="ASI-05",
        ecosystem="npm",
        file_anchor="package.json",
    ),
    Rule(
        id="PKG-WORKSPACE-SHRINKWRAP-OVERRIDES-LOCK",
        name="npm-shrinkwrap.json filename reference",
        severity="MEDIUM",
        description=(
            "Text references npm-shrinkwrap.json. When both shrinkwrap and "
            "package-lock.json exist in the same dir, npm READS SHRINKWRAP "
            "and IGNORES the lockfile. An attacker landing a shrinkwrap "
            "with typosquat resolved URLs gets every install to fetch the "
            "typosquat, while package-lock.json shows clean origins in "
            "the PR diff. Full cross-file co-existence detection lives in "
            "pkg_workspace_graph.py. "
            "(distill-round-5 proposal 13)"
        ),
        pattern=_SHRINKWRAP_FILENAME,
        owasp_asi="ASI-05",
        ecosystem="npm",
        file_anchor=None,
    ),
    Rule(
        id="PKG-WORKSPACE-PNPM-CATALOG-REWRITE",
        name="pnpm catalogs: declared",
        severity="MEDIUM",
        description=(
            "pnpm-workspace.yaml declares a top-level catalogs: or catalog: "
            "block. A single PR editing this file upgrades a dep EVERYWHERE "
            "in the monorepo — no per-package commit, no per-package diff, "
            "no per-package CODEOWNERS notification. Detector promotes "
            "severity when CODEOWNERS coverage is absent or Dependabot/"
            "Renovate auto-merges changes to this file. "
            "(distill-round-5 proposal 14)"
        ),
        pattern=_PNPM_CATALOGS,
        owasp_asi="ASI-05",
        ecosystem="pnpm",
        file_anchor="pnpm-workspace.yaml",
    ),
    Rule(
        id="PKG-WORKSPACE-OVERRIDE-VALUE-GIT-URL",
        name="overrides / resolutions value is non-registry source",
        severity="CRITICAL",
        description=(
            "A resolutions or overrides block forces a transitive dep to a "
            "non-registry source (github:, git+, git:, gitlab:, bitbucket:, "
            "file:, link:, portal:). The override bypasses the lockfile "
            "pin AND the non-registry source bypasses the registry pin — "
            "the maximum-impact single PR change in the workspace-poisoning "
            "taxonomy. "
            "(distill-round-5 proposal 15)"
        ),
        pattern=_OVERRIDE_NON_REGISTRY,
        owasp_asi="ASI-05",
        ecosystem="npm",
        file_anchor="package.json",
    ),
)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).

    Same helper shape as `pkg_bypass_patterns._line_col` so consumers
    can render findings from either module uniformly.
    """
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _filename_matches(rule: Rule, filename: str | None) -> bool:
    """Decide whether `rule` should fire given the caller's `filename`.

    Rules with `file_anchor=None` fire on any text. Rules with a
    concrete `file_anchor` only fire when the caller supplies a
    matching filename. Matching is case-insensitive suffix on the
    base name (so `/abs/path/to/package.json` matches `package.json`,
    and `pnpm-workspace.yaml` matches `pnpm-workspace.yaml` but not
    `pnpm-workspace.yml`).

    When `filename` is None, only un-anchored rules fire. Callers that
    don't know the filename should pass `filename=None` and accept the
    reduced rule coverage; callers that DO know should pass it so the
    file-anchored rules can fire.
    """
    if rule.file_anchor is None:
        return True
    if filename is None:
        return False
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return base.lower() == rule.file_anchor.lower()


def scan_text(
    text: str,
    *,
    filename: str | None = None,
) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `filename` (optional) gates file-anchored rules — rules with a
    `file_anchor` only fire when `filename` matches. Pass the filename
    you got from the filesystem (basename or absolute path; matching
    is case-insensitive suffix on the basename).

    Findings are deduped by (rule_id, line, column). Sorted by
    (line, column, rule_id).

    Caller is responsible for SCOPE FILTERING (only invoke on paths the
    pkg-workspace scan was authorised to look at — see the detector
    wrapper in `scripts/detectors/pkg-workspace-graph.py` for the
    canonical scope-glob list).
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        if not _filename_matches(rule, filename):
            continue
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
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
                ecosystem=rule.ecosystem,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


__all__ = [
    "Finding",
    "Rule",
    "RULES",
    "scan_text",
]
