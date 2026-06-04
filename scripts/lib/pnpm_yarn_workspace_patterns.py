"""pnpm + yarn workspace + lerna monorepo pollution patterns.

Wave-36 distillation round 22.

Catalogue of 8 pnpm/yarn/lerna-specific anti-patterns distilled in
`reports/distill-round-22/pnpm-yarn-workspace.md`. Targets monorepo
configuration surfaces that existing modules cover only at the abstract
level.

What is NOT here (already covered — DO NOT duplicate):

  * `node-linker: hoisted` in `.npmrc` — `cdn_supply_chain_patterns.py` C-11.
  * `enableScripts: true` in `.yarnrc.yml` — `pkg_bypass_patterns.py`.
  * `link:` / `portal:` / `file:` protocol traversal — `npm_workspace_patterns.py` rules 1-2.
  * `workspace:*` protocol shadowing public registry — `npm_workspace_patterns.py` rule 3.
  * `resolutions` / `overrides` transitive rewrite — `npm_workspace_patterns.py` rule 4.
  * `packageExtensions` injection — `npm_workspace_patterns.py` rule 5.
  * `pnpm catalogs:` version rewrite — `npm_workspace_patterns.py` rule 14.

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * pyw-pnpm-glob-too-broad                          (HIGH)
  * pyw-yarn-nodelinker-node-modules                 (HIGH)
  * pyw-lerna-npmclientargs-injection                (HIGH)
  * pyw-pnpm-manage-pkg-manager-off                  (MEDIUM)
  * pyw-yarn-nohoist-missing-sensitive               (MEDIUM)
  * pyw-internal-star-semver-override                (HIGH)
  * pyw-lerna-independent-no-exact-cross-dep         (MEDIUM)
  * pyw-pnpm-shamefully-hoist                        (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret / config leak (committed tokens, registry redirects)
  ASI-05 — Supply-chain / dependency confusion attacks
  ASI-07 — Authority / authorisation gaps (phantom deps, hoisting)

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


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with MULTILINE+UNICODE — RE2-safe: no nested quantifiers,
    no backreferences, no lookbehind."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- pyw-pnpm-glob-too-broad -------------------------------------------


_PNPM_GLOB_TOO_BROAD = _re(
    r"^\s*-\s*['\"]?(?:\*{1,2}|\*{1,2}/\*{1,2})['\"]?\s*$"
)

# ---- pyw-yarn-nodelinker-node-modules -----------------------------------


_YARN_NODELINKER_NODE_MODULES = _re(
    r"^\s*nodeLinker\s*:\s*node-modules\b"
)

# ---- pyw-lerna-npmclientargs-injection ----------------------------------


_LERNA_NPMCLIENTARGS = _re(
    r'"npmClientArgs"\s*:\s*\['
)

# ---- pyw-pnpm-manage-pkg-manager-off ------------------------------------


_PNPM_MANAGE_PKG_MANAGER_OFF = _re(
    r"^\s*manage-package-manager-versions\s*[:=]\s*(?:false|0|no)\b"
)

# ---- pyw-yarn-nohoist-missing-sensitive ---------------------------------


_YARN_NOHOIST_MISSING = _re(
    r'"workspaces"\s*:\s*\{\s*"packages"\s*:'
)

# ---- pyw-internal-star-semver-override ----------------------------------


_INTERNAL_STAR_SEMVER = _re(
    r'"(?:dependencies|devDependencies|peerDependencies|optionalDependencies)"'
    r'\s*:\s*\{[^}]*"\s*:\s*"\*"'
)

# ---- pyw-lerna-independent-no-exact-cross-dep ---------------------------


_LERNA_INDEPENDENT_VERSION = _re(
    r'"version"\s*:\s*"independent"'
)

# ---- pyw-pnpm-shamefully-hoist ------------------------------------------


_PNPM_SHAMEFULLY_HOIST = _re(
    r"^\s*shamefully-hoist\s*[:=]\s*(?:true|1|yes)\b"
)

# ---- Rule catalogue -----------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="pyw-pnpm-glob-too-broad",
        name="pnpm-workspace.yaml packages glob too broad",
        severity="HIGH",
        description=(
            "pnpm-workspace.yaml declares packages: ['*'] or packages: ['**'] — "
            "any directory at the repo root containing a package.json gains workspace "
            "membership and its scripts run on every pnpm install."
        ),
        pattern=_PNPM_GLOB_TOO_BROAD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pyw-yarn-nodelinker-node-modules",
        name="Yarn Berry nodeLinker downgraded to node-modules",
        severity="HIGH",
        description=(
            "nodeLinker: node-modules in .yarnrc.yml reverts to classic hoisting "
            "semantics, allowing phantom-dependency attacks where any transitive "
            "on the hoisting path is importable by any workspace member."
        ),
        pattern=_YARN_NODELINKER_NODE_MODULES,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pyw-lerna-npmclientargs-injection",
        name="lerna.json npmClientArgs can inject CLI flags",
        severity="HIGH",
        description=(
            "lerna.json#npmClientArgs passes flags verbatim to npm/yarn/pnpm on "
            "every lerna publish and lerna bootstrap, enabling flag injection such "
            "as --ignore-scripts=false or --registry https://attacker.example/."
        ),
        pattern=_LERNA_NPMCLIENTARGS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pyw-pnpm-manage-pkg-manager-off",
        name="pnpm manage-package-manager-versions explicitly disabled",
        severity="MEDIUM",
        description=(
            "manage-package-manager-versions=false allows corepack to silently "
            "switch the active pnpm version, bypassing the project-locked version "
            "tested and audited by the team."
        ),
        pattern=_PNPM_MANAGE_PKG_MANAGER_OFF,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pyw-yarn-nohoist-missing-sensitive",
        name="Yarn classic workspaces declared without nohoist",
        severity="MEDIUM",
        description=(
            "Yarn v1 workspace with packages block but no nohoist configuration — "
            "security-sensitive packages (crypto, auth, signing) are lifted to root "
            "node_modules and importable by any workspace member."
        ),
        pattern=_YARN_NOHOIST_MISSING,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="pyw-internal-star-semver-override",
        name="Bare * semver can resolve workspace dep against public registry",
        severity="HIGH",
        description=(
            'Using "*" as a semver constraint for a workspace-internal package '
            "resolves against the public registry when the workspace is not fully "
            "bootstrapped, enabling dependency-confusion attacks."
        ),
        pattern=_INTERNAL_STAR_SEMVER,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pyw-lerna-independent-no-exact-cross-dep",
        name="lerna independent mode detected — cross-dep ranges may resolve from registry",
        severity="MEDIUM",
        description=(
            'lerna.json "version": "independent" with floating range cross-deps '
            "may resolve sibling packages from the public registry during lerna "
            "publish, enabling a supply-chain injection window."
        ),
        pattern=_LERNA_INDEPENDENT_VERSION,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="pyw-pnpm-shamefully-hoist",
        name="pnpm shamefully-hoist enables phantom-dependency attacks",
        severity="HIGH",
        description=(
            "shamefully-hoist=true makes pnpm use flat node_modules identical to "
            "npm's layout — every transitive is importable by any package regardless "
            "of declared dependencies, enabling phantom-dependency exploitation."
        ),
        pattern=_PNPM_SHAMEFULLY_HOIST,
        owasp_asi="ASI-07",
    ),
)


# ---- Public scanner -----------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* for all rules and return sorted Findings.

    Returns an empty list for empty input. Results are ordered by
    (line, column, rule_id) for deterministic output.
    """
    if not text:
        return []

    findings: list[Finding] = []

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            # Compute 1-based line and 1-based column from match start.
            start = m.start()
            # Count newlines before start to get line number.
            line_no = text.count("\n", 0, start) + 1
            # Column = chars after last newline before start.
            last_nl = text.rfind("\n", 0, start)
            col = start - last_nl  # 1-based: if no prior newline, last_nl==-1 -> col==start+1
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line_no,
                    column=col,
                    matched_text=m.group(0),
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
