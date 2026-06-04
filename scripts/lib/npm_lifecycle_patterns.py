"""npm/yarn/pnpm lifecycle script and .npmrc abuse patterns.

Wave-36 distillation round 22, topic: npm/yarn/pnpm lifecycle script +
.npmrc abuse.

Catalogue of 10 attack sub-classes distilled in
`reports/distill-round-22/npm-lifecycle-scripts.md`.

What is NOT here (already covered by existing modules):

  * `npm install` / `pnpm install` without `--ignore-scripts` in CI
    workflows — `rules_context.py` rule `dangerous-lifecycle-scripts`.
  * `NPM_TOKEN` literal name in workflow YAML env block —
    `rules_context.py:345`.
  * `npm install` without `--ci` flag — `rules_absence.py:421`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * nls-lifecycle-fetch-exec       postinstall/preinstall fetch+exec     (CRITICAL)
  * nls-npmrc-auth-token           _authToken / _auth committed to VCS   (CRITICAL)
  * nls-npmrc-registry-redirect    registry= override to non-npmjs host  (HIGH)
  * nls-npmrc-always-auth          always-auth=true present in file      (HIGH)
  * nls-npm-token-echoed           NPM_TOKEN / NODE_AUTH_TOKEN echoed    (HIGH)
  * nls-bin-field-external-path    bin field resolves outside package    (HIGH)
  * nls-npx-auto-install           npx -y / npm exec @latest unverified  (MEDIUM)
  * nls-optional-dep-orphan-commit optionalDependencies orphan commit    (CRITICAL)
  * nls-node-gyp-lifecycle         node-gyp in lifecycle script value    (MEDIUM)
  * nls-npm-pack-no-npmignore      npm pack without .npmignore sentinel  (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)

OWASP ASI mapping used:
  ASI-02 — Secret leak (_authToken committed, token echoed)
  ASI-05 — Supply-chain / dependency confusion (registry redirect,
            orphan commit, npx unverified, node-gyp no allowlist,
            npm pack secrets, lifecycle fetch-exec)
  ASI-07 — Authority / authorisation gaps (always-auth broadcast,
            bin external path)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : nls-lifecycle-fetch-exec ---------------------------------------


# postinstall / preinstall value in package.json that fetches a URL and
# pipes to a shell interpreter — canonical worm delivery vector.
# Bounded: [^|;"']{0,200} prevents catastrophic backtracking.
_LIFECYCLE_FETCH_EXEC = _re(
    r"(?:curl|wget)\b[^|;\"']{0,200}\|\s*(?:bash|sh|node|python[23]?)\b"
)


# ---- R2 : nls-npmrc-auth-token -------------------------------------------


# _authToken (granular access token) or legacy base64 _auth committed in
# .npmrc. Both forms are credential leaks.
_NPMRC_AUTH_TOKEN = _re(
    r"_auth(?:Token)?\s*=\s*\S{8,}"
)


# ---- R3 : nls-npmrc-registry-redirect ------------------------------------


# Global or scoped registry override pointing to a non-npmjs.org host.
# Negative look-ahead is not RE2-safe, so we match ANY registry= line and
# let the caller filter; the pattern itself uses a non-greedy bounded run.
# Matches lines like: registry=https://evil.example.com/
# Also matches: @scope:registry=https://attacker.io/
_NPMRC_REGISTRY_REDIRECT = _re(
    r"(?:^|^@[A-Za-z0-9_.\-]+:)registry\s*=\s*https?://[A-Za-z0-9._\-]{1,200}"
)


# ---- R4 : nls-npmrc-always-auth ------------------------------------------


# always-auth=true in .npmrc broadcasts credentials to every request,
# including those to redirected (attacker-controlled) registries.
_NPMRC_ALWAYS_AUTH = _re(
    r"always-auth\s*=\s*true\b"
)


# ---- R5 : nls-npm-token-echoed -------------------------------------------


# NPM_TOKEN or NODE_AUTH_TOKEN printed/echoed to stdout in workflow YAML
# or shell scripts — leaks token value into CI logs.
_NPM_TOKEN_ECHOED = _re(
    r"(?:echo|printf|run)\s+[^\n]{0,200}(?:NPM_TOKEN|NODE_AUTH_TOKEN|_authToken)\b"
)


# ---- R6 : nls-bin-field-external-path ------------------------------------


# `bin` field in package.json pointing outside the package tree.
# Object form:  "bin": { "cmd": "../evil.js" }
# String form:  "bin": "/usr/bin/evil"
_BIN_FIELD_EXTERNAL_PATH = _re(
    r"\"bin\"\s*:\s*(?:\{[^}]{0,400}:\s*[\"'](?:\.\./|/|~|https?://)"
    r"|[\"'](?:\.\./|/|~|https?://))"
)


# ---- R7 : nls-npx-auto-install -------------------------------------------


# npx -y (auto-install without confirmation) or npm exec with a floating
# version tag, both bypass lockfile integrity.
_NPX_AUTO_INSTALL = _re(
    r"(?:\bnpx\s+(?:-y|--yes)\s+\S"
    r"|\bnpm\s+exec\s+(?:--\s*)?\S+@(?:latest|next|\*)"
    r"|\bnpx\s+(?:-y\s+)?https?://\S)"
)


# ---- R8 : nls-optional-dep-orphan-commit ---------------------------------


# optionalDependencies (or any *Dependencies) value referencing a GitHub
# orphan commit SHA rather than a semver — TanStack 2026-05-11 vector.
_OPTIONAL_DEP_ORPHAN_COMMIT = _re(
    r"\"(?:optional|peer)?[Dd]ependencies\"\s*:\s*\{[^}]{0,600}:\s*"
    r"[\"'](?:github:|git\+https://github\.com/)[^\"']{0,200}#[0-9a-f]{7,40}[\"']"
)


# ---- R9 : nls-node-gyp-lifecycle -----------------------------------------


# node-gyp rebuild / configure / build inside a lifecycle script value in
# package.json — compiles native addon without mandatory allowlist vetting.
_NODE_GYP_LIFECYCLE = _re(
    r"\"(?:pre|post)?install\"\s*:\s*[\"'][^\"']{0,400}"
    r"\bnode-gyp\s+(?:rebuild|configure|build)\b"
)


# ---- R10 : nls-npm-pack-no-npmignore -------------------------------------


# Presence of a `scripts` key containing `npm pack` or `npm publish`
# without a corresponding .npmignore sentinel comment or `files` array
# in the same file — absence signal that tarball may include secrets.
# Heuristic: match `npm pack` or `npm publish` in script values.
_NPM_PACK_NO_NPMIGNORE = _re(
    r"\"(?:pack|publish|prepublish|prepublishOnly)\"\s*:\s*[\"'][^\"']{0,200}"
    r"\bnpm\s+(?:pack|publish)\b"
)


# ---- RULES tuple (ordered, one entry per rule ID) -----------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="nls-lifecycle-fetch-exec",
        name="npm lifecycle fetch-and-exec remote payload",
        severity="CRITICAL",
        description=(
            "A postinstall or preinstall script fetches a remote URL and pipes "
            "it directly into a shell interpreter (bash/sh/node/python). This is "
            "the canonical supply-chain worm delivery pattern."
        ),
        pattern=_LIFECYCLE_FETCH_EXEC,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="nls-npmrc-auth-token",
        name="npm _authToken or _auth committed to VCS",
        severity="CRITICAL",
        description=(
            "_authToken (granular access token) or legacy base64 _auth field "
            "found in .npmrc. Committing registry credentials exposes write-level "
            "package publish access."
        ),
        pattern=_NPMRC_AUTH_TOKEN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="nls-npmrc-registry-redirect",
        name="npm registry= override to non-default host",
        severity="HIGH",
        description=(
            "A global or scoped registry= directive overrides the default "
            "registry.npmjs.org endpoint. Attacker-controlled redirects enable "
            "dependency confusion / registry substitution attacks."
        ),
        pattern=_NPMRC_REGISTRY_REDIRECT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="nls-npmrc-always-auth",
        name="npm always-auth=true broadcasts credentials to all requests",
        severity="HIGH",
        description=(
            "always-auth=true in .npmrc forces the auth header to be sent to "
            "every registry request, including those to redirected or HTTP hosts."
        ),
        pattern=_NPMRC_ALWAYS_AUTH,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="nls-npm-token-echoed",
        name="NPM_TOKEN / NODE_AUTH_TOKEN printed to CI log",
        severity="HIGH",
        description=(
            "An echo, printf, or run step prints NPM_TOKEN, NODE_AUTH_TOKEN, or "
            "_authToken to standard output, leaking the token value into CI logs."
        ),
        pattern=_NPM_TOKEN_ECHOED,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="nls-bin-field-external-path",
        name="package.json bin field resolves outside package tree",
        severity="HIGH",
        description=(
            "The bin field maps to a path starting with ../, /, ~, or a URL, "
            "causing the installed binary to land outside the declared package "
            "tree and enabling arbitrary code execution on global install or npx."
        ),
        pattern=_BIN_FIELD_EXTERNAL_PATH,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="nls-npx-auto-install",
        name="npx -y or npm exec @latest installs without lockfile pin",
        severity="MEDIUM",
        description=(
            "npx with the -y/--yes flag, npm exec with a floating version tag "
            "(@latest/@next/@*), or npx with a direct tarball URL installs and "
            "runs a package without lockfile integrity verification."
        ),
        pattern=_NPX_AUTO_INSTALL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="nls-optional-dep-orphan-commit",
        name="optionalDependencies references GitHub orphan commit SHA",
        severity="CRITICAL",
        description=(
            "A *Dependencies field references a package via github: protocol or "
            "git+https://github.com/ pinned to a commit SHA. Orphan commits "
            "bypass registry integrity checks — the TanStack 2026-05-11 vector."
        ),
        pattern=_OPTIONAL_DEP_ORPHAN_COMMIT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="nls-node-gyp-lifecycle",
        name="node-gyp in lifecycle script without build allowlist",
        severity="MEDIUM",
        description=(
            "A pre/postinstall script calls node-gyp rebuild/configure/build, "
            "compiling native C/C++ code. Without pnpm onlyBuiltDependencies or "
            "allowBuilds, this runs unvetted native addon build scripts."
        ),
        pattern=_NODE_GYP_LIFECYCLE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="nls-npm-pack-no-npmignore",
        name="npm pack or publish in scripts without explicit exclusion",
        severity="MEDIUM",
        description=(
            "A publish/pack lifecycle script calls npm pack or npm publish. "
            "Without a .npmignore or package.json files array, the tarball may "
            "include .env, .npmrc, or private keys."
        ),
        pattern=_NPM_PACK_NO_NPMIGNORE,
        owasp_asi="ASI-05",
    ),
)


# ---- Public scanner ------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* with every rule in RULES.

    Returns a list of Finding tuples, deduplicated on (rule_id, line, col)
    so that overlapping patterns or repeated calls never inflate results.
    Results are ordered by (line, column, rule_id).
    """
    seen: set[tuple[str, int, int]] = set()
    findings: list[Finding] = []

    lines = text.splitlines()
    # Build per-line start-offset table for column calculation.
    offsets: list[int] = []
    pos = 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln) + 1  # +1 for the newline

    for rule in RULES:
        for match in rule.pattern.finditer(text):
            start = match.start()
            # Determine line number (1-based) via bisect-style scan.
            line_no = 1
            for i, off in enumerate(offsets):
                if off <= start:
                    line_no = i + 1
                else:
                    break
            col = start - offsets[line_no - 1] + 1  # 1-based column

            key = (rule.id, line_no, col)
            if key in seen:
                continue
            seen.add(key)

            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line_no,
                    column=col,
                    matched_text=match.group(0),
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
