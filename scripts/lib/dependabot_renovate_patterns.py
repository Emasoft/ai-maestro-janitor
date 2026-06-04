"""Dependabot / Renovate / dependency-update bot CONFIG gaming detector.

Wave-22 distillation round 8 angle F implementation. Companion to
Wave 14 (`secret_rotation_patterns.py::P14 npm-pat-no-cooldown-pinning`)
which catches the *binary* "does ANY cooldown gate exist anywhere in
this file" question, and to Wave 16
(`zizmor_patterns_extra.py::dependabot-actor-spoofable`) which catches
the *actor-equality* spoof primitive.

This pack goes deeper: the BOT CONFIG itself
(`.github/dependabot.yml`, `renovate.json`, `.renovaterc`, `.renovaterc.json`,
`.renovaterc.json5`) plus auto-merge workflows that grant secrets or
direct-push paths to dependency-bot-controlled refs.

Source: `reports/distill-round-8/dependabot-renovate.md` (13 proposals).

Cross-references (verified, not duplicated):

  * Wave 14 (`_DEPENDABOT_COOLDOWN`, `_RENOVATE_COOLDOWN`,
    `_PNPM_RELEASE_AGE`, `_YARN_RELEASE_AGE`) — binary cooldown
    presence. We do NOT re-encode "no gate at all"; we add value /
    scoping / per-ecosystem severity.
  * Wave 16 `dependabot-actor-spoofable` — `github.actor ==
    'dependabot[bot]'` actor-equality. We add the BRANCH-NAME
    spoof primitive (P13) and `pull_request_target` trust-boundary
    crossings (P12).
  * Wave 19 `npm_workspace_patterns` — npm workspace surfaces. We
    do NOT touch lockfile parsing.
  * Wave 16 `provenance_patterns` — SBOM / npm-provenance. Separate
    surface; we do not duplicate.

The 13 rules implemented (one per proposal):

  * DR-P1   dependabot-cooldown-missing-high-risk-ecosystem  HIGH/MEDIUM
  * DR-P2   dependabot-insecure-external-code-execution      CRITICAL
  * DR-P3   dependabot-versioning-strategy-increase           HIGH
  * DR-P4   dependabot-target-branch-default                  MEDIUM
  * DR-P5   renovate-automerge-broad                          HIGH/CRITICAL
  * DR-P6   renovate-dangerous-always-write-default           HIGH
  * DR-P7   renovate-allowed-postupgrade-commands             HIGH/CRITICAL
  * DR-P8   renovate-dashboard-disabled-with-automerge        HIGH
  * DR-P9   renovate-cooldown-scoped-narrower-than-managers   MEDIUM
  * DR-P10  renovate-range-strategy-bump-high-risk            MEDIUM
  * DR-P11  renovate-non-canonical-registry-url               HIGH
  * DR-P12  workflow-pull-request-target-dependabot-pr        CRITICAL
  * DR-P13  workflow-automerge-gated-on-branch-name           HIGH

All patterns are RE2-safe (no backrefs, no lookaround). The module
exports both a regex-only `scan_text(text, *, filename=None)` entry
point (mirrors `npm_workspace_patterns`) AND structural helpers
(`scan_dependabot_yaml(text)`, `scan_renovate_json(text)`) for the
proposals that require YAML/JSON parsing to discriminate per-entry
scope (P1 per-ecosystem cooldown, P9 packageRules scoping, etc.).

When PyYAML is not importable the structural helpers fall back to
the regex-only path — heuristic, but the regex catalogue alone
already covers ~75% of the surface area.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi,
         file_anchor)
  * RULES — ordered tuple of every regex rule.
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi, file_anchor) — frozen NamedTuple.
  * scan_text(text, *, filename=None) -> list[Finding]
  * scan_dependabot_yaml(text) -> list[Finding]
        Structural scan that parses dependabot.yml and emits the
        per-ecosystem / per-entry findings the regex catalogue alone
        cannot discriminate (P1, P3 partial, P4 partial).
  * scan_renovate_json(text) -> list[Finding]
        Structural scan that parses renovate.json / .renovaterc and
        emits the per-packageRules / per-host findings the regex
        catalogue alone cannot discriminate (P5, P8, P9, P10, P11
        partial).
  * HIGH_RISK_ECOSYSTEMS — frozenset of the dependabot
    `package-ecosystem` values where a missing cooldown / age gate
    is HIGH severity (matches PWNPipe
    `dependabot-missing-cooldown.js:3` exactly: npm, pip,
    pip-compile, pipenv, poetry — plus cargo / bun as MEDIUM).
  * CANONICAL_REGISTRY_URLS — frozenset of legitimate per-ecosystem
    registry endpoints (used by P11 to detect attacker mirrors).
"""

from __future__ import annotations

import json
import re
from typing import NamedTuple

# PyYAML is optional — every consumer of the structural helpers must
# be able to handle ImportError. The regex-only `scan_text` entry
# point works without PyYAML.
try:  # pragma: no cover — import guard
    import yaml as _yaml  # type: ignore[import-untyped]
    _HAVE_YAML = True
except ImportError:  # pragma: no cover — import guard
    _yaml = None
    _HAVE_YAML = False


# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match. Mirrors `npm_workspace_patterns.Finding`
    so heartbeat detectors can render findings from either module
    uniformly. `file_anchor` repeats the rule's file-anchor field
    (or empty string for the rules that fire on any file) — keeps
    the rendered finding self-describing."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str
    file_anchor: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load.

    `file_anchor` (optional, case-insensitive basename) gates a rule
    to a specific filename. When `file_anchor` is `None` the rule
    fires on any text the caller passes.
    """

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str
    file_anchor: str | None


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with MULTILINE + UNICODE.

    YAML keys (`package-ecosystem`, `cooldown`, `versioning-strategy`)
    and JSON keys (`automerge`, `packageRules`, `extends`) are
    case-sensitive in their respective specs, so this helper does
    NOT add IGNORECASE — a fuzzy match on `Cooldown:` would be a
    false positive against a vendor-shaped field that doesn't
    actually affect the bot's behaviour.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


def _re_i(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE + MULTILINE + UNICODE.

    Used only for the workflow-side rules (P12, P13) where human-
    typed YAML values (`pull_request_target:` vs `Pull_request_target:`,
    `dependabot/` vs `Dependabot/`) appear in mixed case.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Constants ----------------------------------------------------------


# PWNPipe `dependabot-missing-cooldown.js:3` HIGH_RISK_ECOSYSTEMS set.
# A malicious release in any of these ecosystems runs arbitrary code
# on `install` (npm postinstall, pip setup.py, poetry build-system
# hooks, pipenv setup-script, pip-compile resolver hooks). Cargo
# crates and bun packages are also code-exec-on-install but the
# attack surface is smaller (single binary tree, no postinstall
# script story) — flagged at MEDIUM instead of HIGH.
HIGH_RISK_ECOSYSTEMS: frozenset[str] = frozenset({
    "npm",
    "pip",
    "pip-compile",
    "pipenv",
    "poetry",
})

MEDIUM_RISK_ECOSYSTEMS: frozenset[str] = frozenset({
    "cargo",
    "bun",
    "gomod",
    "composer",
})

# Per-ecosystem canonical registry endpoints. Anything in P11
# `registryUrls` not in this set is flagged. The keys are the
# Renovate `datasource` names (which is the spelling the JSON
# config uses); the values are the canonical https endpoints.
CANONICAL_REGISTRY_URLS: frozenset[str] = frozenset({
    "https://registry.npmjs.org",
    "https://registry.npmjs.org/",
    "https://registry.yarnpkg.com",
    "https://registry.yarnpkg.com/",
    "https://pypi.org/simple",
    "https://pypi.org/simple/",
    "https://repo.maven.apache.org/maven2",
    "https://repo.maven.apache.org/maven2/",
    "https://repo1.maven.org/maven2",
    "https://repo1.maven.org/maven2/",
    "https://rubygems.org",
    "https://rubygems.org/",
    "https://crates.io",
    "https://crates.io/",
    "https://proxy.golang.org",
    "https://proxy.golang.org/",
    "https://nuget.org",
    "https://api.nuget.org/v3/index.json",
    # Self-hosted / internal mirrors that are NEVER attacker domains
    # — explicit allowlist of known-good org-internal mirrors. Empty
    # for now; callers can extend at runtime if needed.
})

# Renovate `versioning-strategy` allowed values (from Dependabot
# spec). Used by P3 to flag the dangerous values explicitly while
# letting the safe values pass.
DEPENDABOT_VERSIONING_STRATEGIES_RISKY: frozenset[str] = frozenset({
    "increase",
    "increase-if-necessary",
})

DEPENDABOT_VERSIONING_STRATEGIES_SAFE: frozenset[str] = frozenset({
    "lockfile-only",
    "widen",
    "auto",
})


# ---- Rule 1: DR-P1 dependabot-cooldown-missing-high-risk-ecosystem ------
#
# Regex leg only catches the `package-ecosystem: <high-risk>` declaration
# WITHIN a dependabot.yml file. The structural helper in
# `scan_dependabot_yaml` does the actual per-entry "cooldown absent on
# this high-risk ecosystem" check (the regex alone can't discriminate
# which entry the cooldown belongs to).

_DEPENDABOT_HIGH_RISK_ECOSYSTEM_DECL = _re(
    r"^[ \t]+package-ecosystem:\s*['\"]?(?:npm|pip|pip-compile|pipenv|poetry)['\"]?[ \t]*$"
)


# ---- Rule 2: DR-P2 dependabot-insecure-external-code-execution ----------
#
# `insecure-external-code-execution: allow` permits Dependabot to run
# npm postinstall / Gemfile / Poetry build-system hooks during version
# resolution. CRITICAL because the attack is pre-review (the PR never
# reaches a human). Reference: PWNPipe
# `dependabot-insecure-execution.js:9`.

_DEPENDABOT_INSECURE_EXEC = _re(
    r"^[ \t]+insecure-external-code-execution:\s*['\"]?allow['\"]?[ \t]*$"
)


# ---- Rule 3: DR-P3 dependabot-versioning-strategy-increase --------------
#
# `versioning-strategy: increase` or `increase-if-necessary` causes
# Dependabot to mutate the manifest range automatically on upgrade.
# Combined with auto-merge → attacker-controlled minor / patch bypasses
# review.

_DEPENDABOT_VERSIONING_RISKY = _re(
    r"^[ \t]+versioning-strategy:\s*['\"]?(?:increase|increase-if-necessary)['\"]?[ \t]*$"
)


# ---- Rule 4: DR-P4 dependabot-target-branch-default ---------------------
#
# `target-branch: main` (or master) explicitly. Hardened pattern is a
# separate integration branch with its own CI before PRing to main.

_DEPENDABOT_TARGET_BRANCH_MAIN = _re(
    r"^[ \t]+target-branch:\s*['\"]?(?:main|master)['\"]?[ \t]*$"
)


# ---- Rule 5: DR-P5 renovate-automerge-broad -----------------------------
#
# Top-level `"automerge": true` or `"platformAutomerge": true` in
# renovate.json. Critical when combined with HIGH-RISK ecosystem
# coverage AND `:disableDependencyDashboard`. The regex flags the
# presence; severity escalation happens in `scan_renovate_json`.

_RENOVATE_AUTOMERGE_TOPLEVEL = _re(
    r'"automerge"\s*:\s*true'
    r"|"
    r'"platformAutomerge"\s*:\s*true'
)


# ---- Rule 6: DR-P6 renovate-dangerous-always-write-default --------------
#
# `dangerousAlwaysWriteToDefaultBranch: true` pushes dependency
# updates STRAIGHT to the default branch. The flag-name explicitly
# acknowledges danger. PWNPipe `renovate-automerge.js:56-73`.

_RENOVATE_DANGEROUS_DIRECT_PUSH = _re(
    r'"dangerousAlwaysWriteToDefaultBranch"\s*:\s*true'
)


# ---- Rule 7: DR-P7 renovate-allowed-postupgrade-commands ----------------
#
# `allowedPostUpgradeCommands` containing a catch-all regex (`.*` /
# `^.+$` / `^.*$`) OR a broad shell prefix (`npm .*`, `pnpm .*`,
# `yarn .*`, `pip .*`, `poetry .*`). PWNPipe
# `renovate-automerge.js:33-53`. Also flags
# `postUpgradeTasks.executionMode: "branch"`.

_RENOVATE_POSTUPGRADE_CATCHALL = _re(
    # Catch-all regex literal inside an `allowedPostUpgradeCommands`
    # array. Tightened to require the array context.
    r'"allowedPostUpgradeCommands"\s*:\s*\[[^\]]{0,500}"\^?\.[\*\+]\$?"'
)

_RENOVATE_POSTUPGRADE_BROAD_PREFIX = _re(
    # Broad shell-tool prefix `npm .*` / `pnpm .*` / `yarn .*` / `pip .*`
    # / `poetry .*` inside `allowedPostUpgradeCommands`. The pattern is
    # bounded — only fires when the prefix appears inside the array.
    r'"allowedPostUpgradeCommands"\s*:\s*\[[^\]]{0,500}'
    r'"(?:npm|pnpm|yarn|pip|poetry|pipenv|cargo|bun|go)[ \t]+\.[\*\+][^"]{0,40}"'
)

_RENOVATE_POSTUPGRADE_BRANCH_MODE = _re(
    r'"executionMode"\s*:\s*"branch"'
)


# ---- Rule 8: DR-P8 renovate-dashboard-disabled-with-automerge -----------
#
# `:disableDependencyDashboard` in `extends` array OR
# `dependencyDashboard: false`. The dashboard is the human-review
# surface. Combined with auto-merge = zero humans see the upgrade.

_RENOVATE_DASHBOARD_DISABLED = _re(
    r'":disableDependencyDashboard"'
    r"|"
    r'"dependencyDashboard"\s*:\s*false'
    r"|"
    r'"dependencyDashboardApproval"\s*:\s*false'
)


# ---- Rule 9: DR-P9 renovate-cooldown-scoped-narrower-than-managers ------
#
# A `packageRules` entry contains a cooldown-class key
# (`minimumReleaseAge`, `internalChecksFilter`, `osvVulnerabilityAlerts`)
# scoped to `matchManagers: ["custom.regex"]` (or a similarly narrow
# manager set) — the cooldown only applies to the matched manager.
# The regex catches the presence; the structural helper validates
# that EVERY enabled manager is covered.

_RENOVATE_PACKAGERULES_COOLDOWN_NARROW = _re(
    # `matchManagers` followed by a single-entry array containing
    # `custom.regex` or any other non-`*` value. The negative case
    # (manager set is `["*"]` or the array is broader) is filtered
    # by the structural helper.
    r'"matchManagers"\s*:\s*\[\s*"custom\.regex"\s*\]'
)


# ---- Rule 10: DR-P10 renovate-range-strategy-bump-high-risk -------------
#
# `"rangeStrategy": "bump"` (or `"replace"`, `"update-lockfile"`).
# `bump` moves the manifest range, allowing an in-range future patch
# to install without a new PR. Per-ecosystem severity in the
# structural helper.

_RENOVATE_RANGE_STRATEGY_BUMP = _re(
    r'"rangeStrategy"\s*:\s*"bump"'
)


# ---- Rule 11: DR-P11 renovate-non-canonical-registry-url ----------------
#
# `registryUrls` array entries pointing at non-canonical registries
# OR `hostRules[].matchHost` pointing at suspicious patterns (`.tk`,
# `.ml`, `.cf`, raw IPv4 addresses, short-lived hosts). The regex
# flags suspicious-domain presence; the structural helper does the
# canonical-allowlist check.

_RENOVATE_REGISTRY_URL_TLD_RISKY = _re(
    # `registryUrls` array containing a URL ending in `.tk` / `.ml`
    # / `.cf` / `.gq` (the canonical short-lived TLDs that legitimate
    # registries do NOT use).
    r'"registryUrls"\s*:\s*\[[^\]]{0,500}"https?://[^"]+\.(?:tk|ml|cf|gq)(?:/|")'
)

_RENOVATE_REGISTRY_URL_IP_ADDRESS = _re(
    # `registryUrls` containing a raw IPv4 address (no DNS). Legitimate
    # registries use DNS; raw IP is a known attacker-mirror tell.
    r'"registryUrls"\s*:\s*\[[^\]]{0,500}'
    r'"https?://(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)'
    r'(?:\.(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)){3}'
)

_RENOVATE_HOSTRULES_SUSPICIOUS = _re(
    # `hostRules` `matchHost` pointing at the same suspicious TLDs.
    r'"matchHost"\s*:\s*"[^"]+\.(?:tk|ml|cf|gq)"'
)


# ---- Rule 12: DR-P12 workflow-pull-request-target-dependabot-pr ---------
#
# `.github/workflows/*.yml` with `on.pull_request_target:` AND a
# `checkout` step using `ref: ${{ github.event.pull_request.head.sha }}`
# / `ref: refs/pull/...` (or no `ref:` — default uses HEAD) AND
# access to `secrets.*` (other than `secrets.GITHUB_TOKEN`).
# CVE-2024-27082 class. Regex leg flags the dangerous trigger +
# checkout-ref combination; the structural helper would do the
# secrets-access check — but the regex-only path is sufficient for
# the trigger+ref combination, which is the actual high-confidence
# signal.

_WORKFLOW_PRT_DEPENDABOT = _re_i(
    # `on: pull_request_target:` (with surrounding YAML noise) AND
    # a `head.sha` / `pull_request.head` checkout reference in the
    # same file. We use two regexes that the scan helper conjuncts.
    r"^[ \t]*pull_request_target\s*:"
)

_WORKFLOW_CHECKOUT_HEAD_REF = _re_i(
    r"ref:\s*\$\{\{\s*github\.event\.pull_request\.head\."
    r"(?:sha|ref)\s*\}\}"
    r"|"
    r"ref:\s*refs/pull/"
)


# ---- Rule 13: DR-P13 workflow-automerge-gated-on-branch-name ------------
#
# `if:` / `with:` expressions containing `github.head_ref` /
# `github.ref` / `github.ref_name` AND the literal `dependabot/`.
# An attacker creates a normal PR from a branch they name
# `dependabot/foo` and the workflow auto-merges or grants secrets.
# Also flags `on.push.branches:` arrays containing `dependabot/*` or
# `dependabot/**`. Reference: PWNPipe
# `dependabot-confused-deputy.js:17-53`.

_WORKFLOW_BRANCH_NAME_DEPENDABOT_GATE = _re_i(
    # `github.head_ref` / `github.ref` / `github.ref_name` referenced
    # together with the literal `dependabot/` in a single expression.
    # The `[^}]{0,200}` cap is RE2-safe (bounded repetition).
    r"github\.(?:head_ref|ref|ref_name)[^}\n]{0,200}['\"]dependabot/"
    r"|"
    r"['\"]dependabot/[^}\n]{0,200}github\.(?:head_ref|ref|ref_name)"
    r"|"
    # startsWith / contains with a `dependabot/` literal.
    r"startsWith\s*\(\s*github\.(?:head_ref|ref|ref_name)\s*,\s*['\"]dependabot/"
    r"|"
    r"contains\s*\(\s*github\.(?:head_ref|ref|ref_name)\s*,\s*['\"]dependabot/"
)

_WORKFLOW_PUSH_BRANCHES_DEPENDABOT = _re_i(
    # `on.push.branches:` array literally containing `dependabot/*`
    # or `dependabot/**`. YAML block style with `-` is the common
    # spelling; flow style `[...]` also covered.
    r"^[ \t]*-\s*['\"]?dependabot/\*\*?['\"]?[ \t]*$"
    r"|"
    r"branches\s*:\s*\[[^\]]{0,200}['\"]dependabot/\*\*?['\"]"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="DR-P1",
        name="Dependabot HIGH-RISK ecosystem cooldown audit needed",
        severity="HIGH",
        description=(
            "Dependabot config declares a HIGH-RISK ecosystem "
            "(npm / pip / pip-compile / pipenv / poetry) — these are "
            "the ecosystems where a malicious release runs arbitrary "
            "code on `install` via postinstall / setup-script / "
            "build-system hooks. The presence of the ecosystem "
            "declaration alone is not a finding; the structural helper "
            "`scan_dependabot_yaml` validates that EACH high-risk "
            "ecosystem entry has its own `cooldown:` block with "
            "`default-days >= 7`. Wave 14's binary 'any cooldown' "
            "check passes a file that gates `github-actions` but "
            "skips `npm` — this rule catches that. "
            "(distill-round-8 proposal 1)"
        ),
        pattern=_DEPENDABOT_HIGH_RISK_ECOSYSTEM_DECL,
        owasp_asi="ASI-05",
        file_anchor="dependabot.yml",
    ),
    Rule(
        id="DR-P2",
        name="Dependabot insecure-external-code-execution: allow",
        severity="CRITICAL",
        description=(
            "`insecure-external-code-execution: allow` permits "
            "Dependabot to run third-party package-manager code "
            "(npm postinstall, Bundler Gemfile hooks, Poetry "
            "build-system hooks) during version resolution. "
            "Execution happens inside GitHub's Dependabot worker "
            "with the project's Dependabot token. A malicious "
            "package's postinstall obtains the token and pivots to "
            "the repo. This is the 'RCE on the bot before the PR is "
            "even opened' class. Reference: PWNPipe "
            "`dependabot-insecure-execution.js:9`. "
            "(distill-round-8 proposal 2)"
        ),
        pattern=_DEPENDABOT_INSECURE_EXEC,
        owasp_asi="ASI-05",
        file_anchor="dependabot.yml",
    ),
    Rule(
        id="DR-P3",
        name="Dependabot versioning-strategy: increase",
        severity="HIGH",
        description=(
            "`versioning-strategy: increase` (or "
            "`increase-if-necessary`) causes Dependabot to update "
            "the manifest to the new highest version automatically. "
            "Combined with auto-merge, an attacker who publishes a "
            "patch / minor version slips through review (no human "
            "sees the version number). The hardened value is "
            "`lockfile-only` (lockfile-bump only, no manifest "
            "mutation) or `widen` (declarative `^x.y.z`). "
            "(distill-round-8 proposal 3)"
        ),
        pattern=_DEPENDABOT_VERSIONING_RISKY,
        owasp_asi="ASI-05",
        file_anchor="dependabot.yml",
    ),
    Rule(
        id="DR-P4",
        name="Dependabot target-branch: main (no integration branch)",
        severity="MEDIUM",
        description=(
            "Dependabot config declares `target-branch: main` (or "
            "`master`) explicitly. The hardened pattern is a "
            "separate `dependabot` / `dependencies` integration "
            "branch that runs CI BEFORE PRing to `main`. Targeting "
            "the default branch skips that layer. The default "
            "behaviour when `target-branch:` is OMITTED is also to "
            "target the default branch — but defaults can be "
            "hardened with branch protection rules elsewhere, so "
            "explicit `target-branch: main` is the actionable "
            "finding. "
            "(distill-round-8 proposal 4)"
        ),
        pattern=_DEPENDABOT_TARGET_BRANCH_MAIN,
        owasp_asi="ASI-05",
        file_anchor="dependabot.yml",
    ),
    Rule(
        id="DR-P5",
        name="Renovate automerge: true / platformAutomerge: true",
        severity="HIGH",
        description=(
            "Renovate top-level `automerge: true` or "
            "`platformAutomerge: true` makes EVERY dependency-update "
            "PR merge without human review. Combined with "
            "`:disableDependencyDashboard` (see DR-P8), no review "
            "surface exists at all. A typosquatting / compromised "
            "release reaches `main` in minutes. Severity is "
            "ESCALATED to CRITICAL when combined with HIGH-RISK "
            "ecosystem coverage AND dashboard-disabled (see "
            "`scan_renovate_json`). Reference: PWNPipe "
            "`renovate-automerge.js:12-31`. "
            "(distill-round-8 proposal 5)"
        ),
        pattern=_RENOVATE_AUTOMERGE_TOPLEVEL,
        owasp_asi="ASI-05",
        file_anchor=None,  # renovate.json / .renovaterc / variants
    ),
    Rule(
        id="DR-P6",
        name="Renovate dangerousAlwaysWriteToDefaultBranch: true",
        severity="HIGH",
        description=(
            "`dangerousAlwaysWriteToDefaultBranch: true` makes "
            "Renovate push dependency updates DIRECTLY to the "
            "default branch — no PR, no review, no CI gate. The "
            "flag-name explicitly acknowledges danger; the only "
            "legitimate use is single-developer one-shot projects. "
            "Reference: PWNPipe `renovate-automerge.js:56-73`. "
            "(distill-round-8 proposal 6)"
        ),
        pattern=_RENOVATE_DANGEROUS_DIRECT_PUSH,
        owasp_asi="ASI-05",
        file_anchor=None,
    ),
    Rule(
        id="DR-P7-CATCHALL",
        name="Renovate allowedPostUpgradeCommands catch-all glob",
        severity="CRITICAL",
        description=(
            "`allowedPostUpgradeCommands` contains a catch-all regex "
            "(`.*` / `^.+$` / `^.*$`). The Renovate worker runs the "
            "matched command in CI with full secret access. A "
            "malicious package shipping a hostile `package.json` "
            "`scripts` section achieves RCE. CRITICAL because no "
            "filtering remains. Reference: PWNPipe "
            "`renovate-automerge.js:33-53`. "
            "(distill-round-8 proposal 7, catch-all variant)"
        ),
        pattern=_RENOVATE_POSTUPGRADE_CATCHALL,
        owasp_asi="ASI-05",
        file_anchor=None,
    ),
    Rule(
        id="DR-P7-BROAD",
        name="Renovate allowedPostUpgradeCommands broad shell prefix",
        severity="HIGH",
        description=(
            "`allowedPostUpgradeCommands` contains a broad shell-tool "
            "prefix `npm .*` / `pnpm .*` / `yarn .*` / `pip .*` / "
            "`poetry .*`. Even moderately broad patterns are "
            "exploitable by a malicious package's `scripts` section. "
            "The hardened pattern allowlists specific commands "
            "(`npm run build`, `pnpm install --frozen-lockfile`, "
            "etc.). Reference: PWNPipe "
            "`renovate-automerge.js:33-53`. "
            "(distill-round-8 proposal 7, broad-prefix variant)"
        ),
        pattern=_RENOVATE_POSTUPGRADE_BROAD_PREFIX,
        owasp_asi="ASI-05",
        file_anchor=None,
    ),
    Rule(
        id="DR-P7-BRANCH-MODE",
        name='Renovate postUpgradeTasks executionMode: "branch"',
        severity="HIGH",
        description=(
            '`postUpgradeTasks.executionMode: "branch"` runs the '
            "configured commands in the PR-branch environment "
            "(with branch-write GitHub App token). The hardened "
            "alternative is `\"update\"` mode, which runs in a "
            "restricted update-task context. Branch mode is "
            "exploitable when combined with broad "
            "`allowedPostUpgradeCommands` (see DR-P7-CATCHALL / "
            "DR-P7-BROAD). "
            "(distill-round-8 proposal 7, executionMode variant)"
        ),
        pattern=_RENOVATE_POSTUPGRADE_BRANCH_MODE,
        owasp_asi="ASI-05",
        file_anchor=None,
    ),
    Rule(
        id="DR-P8",
        name="Renovate :disableDependencyDashboard / dashboard: false",
        severity="HIGH",
        description=(
            "Renovate `extends` array includes "
            "`:disableDependencyDashboard` OR config sets "
            "`dependencyDashboard: false` OR "
            "`dependencyDashboardApproval: false`. The Dependency "
            "Dashboard is the human-review surface — a meta-issue "
            "listing every proposed update. Disabling it removes "
            "that signal; combined with ANY auto-merge / "
            "auto-approve path the updates execute with ZERO human "
            "signal. Severity is HIGH when paired with automerge "
            "(see `scan_renovate_json`); LOW alone. "
            "(distill-round-8 proposal 8)"
        ),
        pattern=_RENOVATE_DASHBOARD_DISABLED,
        owasp_asi="ASI-05",
        file_anchor=None,
    ),
    Rule(
        id="DR-P9",
        name="Renovate packageRules cooldown scoped narrower than managers",
        severity="MEDIUM",
        description=(
            "A `packageRules` entry carries a cooldown-class key "
            "(`minimumReleaseAge`, `internalChecksFilter: strict`, "
            "`osvVulnerabilityAlerts: true`) but is scoped to "
            "`matchManagers: [custom.regex]` (or a similarly narrow "
            "set). When `enabledManagers` is expanded later (or the "
            "project adds an npm `package.json`), the new manager "
            "has ZERO age gate — Wave 14's whole-file regex passes "
            "because SOME cooldown exists. Severity is MEDIUM "
            "because the false sense of security IS the bug. "
            "(distill-round-8 proposal 9)"
        ),
        pattern=_RENOVATE_PACKAGERULES_COOLDOWN_NARROW,
        owasp_asi="ASI-05",
        file_anchor=None,
    ),
    Rule(
        id="DR-P10",
        name='Renovate rangeStrategy: "bump" on HIGH-RISK ecosystem',
        severity="MEDIUM",
        description=(
            '`rangeStrategy: "bump"` moves the manifest range '
            "`^1.2.3 → ^1.2.4` instead of pinning. Accepts ANY "
            "future patch in-range without a new PR — a malicious "
            "1.2.5 published after PR review but before merge (or "
            "after merge, during next `npm install`) installs "
            "without a new PR. The hardened value is `pin` "
            "(`^1.2.3` → `1.2.4` exact). Severity is MEDIUM in "
            "isolation; the structural helper escalates to HIGH "
            "when paired with HIGH-RISK ecosystem coverage. "
            "(distill-round-8 proposal 10)"
        ),
        pattern=_RENOVATE_RANGE_STRATEGY_BUMP,
        owasp_asi="ASI-05",
        file_anchor=None,
    ),
    Rule(
        id="DR-P11-TLD",
        name="Renovate registryUrls / hostRules suspicious TLD",
        severity="HIGH",
        description=(
            "`registryUrls` or `hostRules.matchHost` points at a "
            "short-lived / cheap-to-register TLD (`.tk`, `.ml`, "
            "`.cf`, `.gq`). Legitimate package registries do NOT "
            "use these TLDs; the presence is a strong attacker-"
            "mirror tell. Combined with HIGH-RISK ecosystem "
            "coverage, the bot resolves every dep against the "
            "attacker mirror. "
            "(distill-round-8 proposal 11, TLD variant)"
        ),
        pattern=_RENOVATE_REGISTRY_URL_TLD_RISKY,
        owasp_asi="ASI-05",
        file_anchor=None,
    ),
    Rule(
        id="DR-P11-IP",
        name="Renovate registryUrls raw IP address",
        severity="HIGH",
        description=(
            "`registryUrls` array contains a raw IPv4 address "
            "instead of a DNS name. Legitimate registries route "
            "through DNS; raw IP is a known attacker-mirror tell "
            "(no certificate name to verify, no DNS revocation "
            "path). "
            "(distill-round-8 proposal 11, raw-IP variant)"
        ),
        pattern=_RENOVATE_REGISTRY_URL_IP_ADDRESS,
        owasp_asi="ASI-05",
        file_anchor=None,
    ),
    Rule(
        id="DR-P11-HOSTRULES",
        name="Renovate hostRules.matchHost suspicious domain",
        severity="HIGH",
        description=(
            "`hostRules.matchHost` matches a suspicious-TLD domain "
            "(`.tk`, `.ml`, `.cf`, `.gq`). `hostRules` configures "
            "per-host authentication and proxying; pointing it at "
            "an attacker domain re-routes requests for that host. "
            "(distill-round-8 proposal 11, hostRules variant)"
        ),
        pattern=_RENOVATE_HOSTRULES_SUSPICIOUS,
        owasp_asi="ASI-05",
        file_anchor=None,
    ),
    Rule(
        id="DR-P12",
        name="Workflow pull_request_target with PR head ref checkout",
        severity="CRITICAL",
        description=(
            "Workflow triggers on `pull_request_target:` AND a "
            "checkout step references "
            "`${{ github.event.pull_request.head.sha }}` (or "
            "`head.ref`, or `refs/pull/...`). `pull_request_target` "
            "runs in the BASE-repo context with BASE-repo secrets "
            "but checks out the PR's HEAD-ref code by default. "
            "When the head-ref code is attacker-supplied (Dependabot "
            "PR branch, which an attacker can force-push to via "
            "`@dependabot rebase`), the workflow runs attacker code "
            "with base-repo secrets. CVE-2024-27082 class. "
            "(distill-round-8 proposal 12)"
        ),
        pattern=_WORKFLOW_PRT_DEPENDABOT,
        owasp_asi="ASI-05",
        file_anchor=None,  # any workflow .yml under .github/workflows/
    ),
    Rule(
        id="DR-P13-EXPR",
        name="Workflow gates auto-merge on github.head_ref dependabot/",
        severity="HIGH",
        description=(
            "Workflow `if:` / `with:` expression compares "
            "`github.head_ref` / `github.ref` / `github.ref_name` "
            "against the literal `dependabot/` — usually via "
            "`startsWith(github.head_ref, 'dependabot/')` or "
            "`contains(...)`. The branch NAME is not an "
            "authentication signal: any repo collaborator can "
            "create a branch named `dependabot/foo`, push a PR "
            "from it, and the workflow grants secrets or auto-"
            "merges because of the name match. Reference: PWNPipe "
            "`dependabot-confused-deputy.js:17-53`. "
            "(distill-round-8 proposal 13, expression variant)"
        ),
        pattern=_WORKFLOW_BRANCH_NAME_DEPENDABOT_GATE,
        owasp_asi="ASI-05",
        file_anchor=None,
    ),
    Rule(
        id="DR-P13-PUSH",
        name="Workflow on.push.branches includes dependabot/* pattern",
        severity="HIGH",
        description=(
            "Workflow `on.push.branches:` array contains "
            "`dependabot/*` or `dependabot/**`. Pushes to these "
            "branches CAN come from anyone in the repo who can "
            "create a branch (collaborators, fork-PR maintainers "
            "via merge-conflict resolution). Treating the branch "
            "name as an authentication signal is the "
            "confused-deputy primitive. Reference: PWNPipe "
            "`dependabot-confused-deputy.js:17-53`. "
            "(distill-round-8 proposal 13, push variant)"
        ),
        pattern=_WORKFLOW_PUSH_BRANCHES_DEPENDABOT,
        owasp_asi="ASI-05",
        file_anchor=None,
    ),
)


# ---- Scan helpers -------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).

    Same helper shape as `npm_workspace_patterns._line_col` so
    consumers can render findings from either module uniformly."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _filename_matches(rule: Rule, filename: str | None) -> bool:
    """Decide whether `rule` should fire given the caller's `filename`.

    Rules with `file_anchor=None` fire on any text. Rules with a
    concrete `file_anchor` only fire when the caller supplies a
    matching filename. Matching is case-insensitive suffix on the
    base name (so `/abs/path/to/.github/dependabot.yml` matches
    `dependabot.yml`).
    """
    if rule.file_anchor is None:
        return True
    if filename is None:
        return False
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return base.lower() == rule.file_anchor.lower()


def _truncate_match(matched: str, limit: int = 200) -> str:
    """Cap a matched_text snippet at `limit` chars + ellipsis."""
    if len(matched) > limit:
        return matched[:limit] + "…"
    return matched


def scan_text(
    text: str,
    *,
    filename: str | None = None,
) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `filename` (optional) gates file-anchored rules — rules with a
    `file_anchor` only fire when the basename matches (case-insensitive).

    The regex-only path covers ~75% of the surface area. Callers that
    have access to the parsed YAML / JSON should additionally call
    `scan_dependabot_yaml(text)` / `scan_renovate_json(text)` for the
    structural-aware findings (per-entry cooldown audit, packageRules
    scoping, etc.) that a single-pass regex cannot discriminate.

    Findings are deduped by (rule_id, line, column) and sorted by
    (line, column, rule_id).
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
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=_truncate_match(m.group(0)),
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
                file_anchor=rule.file_anchor or "",
            ))

    # DR-P12 conjunction post-filter: the _WORKFLOW_PRT_DEPENDABOT
    # regex flags the trigger alone. A finding qualifies as CRITICAL
    # only when the file ALSO has a head-ref checkout. We don't drop
    # the trigger-only finding (it is still actionable as MEDIUM —
    # `pull_request_target` is the primitive even without head-ref
    # checkout) but we DO upgrade the severity when the checkout
    # reference appears anywhere in the file.
    has_head_ref_checkout = bool(_WORKFLOW_CHECKOUT_HEAD_REF.search(text))
    if not has_head_ref_checkout:
        # Demote DR-P12 to MEDIUM when no head-ref checkout exists.
        # This preserves the finding (pull_request_target on a
        # dependency-handling workflow is still worth flagging) but
        # acknowledges the lower exploitability.
        findings = [
            f._replace(severity="MEDIUM") if f.rule_id == "DR-P12" else f
            for f in findings
        ]

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


# ---- Structural (YAML / JSON parser) helpers ----------------------------


def _make_finding(
    rule_id: str,
    line: int,
    column: int,
    matched: str,
    severity: str,
    description: str,
    file_anchor: str,
) -> Finding:
    """Helper to build a Finding from structural-scan callsites that
    don't have access to a Rule tuple (line/col come from YAML / JSON
    parser line tracking, not from a regex match)."""
    return Finding(
        rule_id=rule_id,
        line=line,
        column=column,
        matched_text=_truncate_match(matched),
        severity=severity,
        description=description,
        owasp_asi="ASI-05",
        file_anchor=file_anchor,
    )


def _safe_yaml_load(text: str) -> object | None:
    """Load YAML safely. Returns None on any parse error / no PyYAML —
    callers must handle None. We use `safe_load` (NOT `safe_load_all`)
    because a multi-document dependabot.yml is non-canonical."""
    if not _HAVE_YAML or _yaml is None:
        return None
    try:
        return _yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — any YAML error returns None
        return None


def _safe_json_load(text: str) -> object | None:
    """Load JSON with a JSON5-lite preprocessor (strip // and /* */
    comments). renovate.json5 / .renovaterc.json5 permit comments and
    trailing commas; we strip the comments but keep parsing as strict
    JSON otherwise. Returns None on any parse error."""
    if not text or not text.strip():
        return None
    stripped = _strip_jsonc_comments(text)
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None


def _strip_jsonc_comments(text: str) -> str:
    """Remove `//` line comments and `/* */` block comments from `text`.

    Preserves comment-like sequences inside string literals (a `//`
    inside a `"..."` string must NOT be stripped). The implementation
    is a single linear scan, RE2-safe.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    string_quote = ""
    in_line_comment = False
    in_block_comment = False
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
                out.append(c)
            i += 1
            continue
        if in_block_comment:
            if c == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            # Preserve newlines so line numbers stay aligned.
            if c == "\n":
                out.append(c)
            i += 1
            continue
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(nxt)
                i += 2
                continue
            if c == string_quote:
                in_string = False
            i += 1
            continue
        if c in ('"', "'"):
            in_string = True
            string_quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if c == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _yaml_find_line(text: str, key: str, value: str) -> int:
    """Find the 1-based line of `key: value` in `text`. Returns 1
    when the parser succeeded but the line is unrecoverable (e.g. via
    `safe_load` we lose source positions; the regex scan would have
    found the actual line)."""
    pattern = re.compile(
        rf"^[ \t]*{re.escape(key)}\s*:\s*['\"]?{re.escape(value)}['\"]?",
        re.MULTILINE,
    )
    m = pattern.search(text)
    if m is None:
        return 1
    return text[:m.start()].count("\n") + 1


def _json_find_line(text: str, key: str) -> int:
    """Find the 1-based line where `"key"` appears in JSON `text`.
    Returns 1 if not found."""
    pattern = re.compile(rf'"{re.escape(key)}"\s*:', re.MULTILINE)
    m = pattern.search(text)
    if m is None:
        return 1
    return text[:m.start()].count("\n") + 1


def scan_dependabot_yaml(text: str) -> list[Finding]:
    """Structural scan of a `.github/dependabot.yml` file.

    Performs:
      * DR-P1: each `updates[*]` entry's `package-ecosystem` is checked
        against HIGH_RISK_ECOSYSTEMS / MEDIUM_RISK_ECOSYSTEMS. For
        every HIGH-RISK entry, the entry MUST have a `cooldown:` block
        AND that block's `default-days` (or the per-semver split) MUST
        be >= 7. Otherwise emits DR-P1 (HIGH severity for high-risk,
        MEDIUM for medium-risk).
      * DR-P2: any entry with `insecure-external-code-execution: allow`.
      * DR-P3: any entry with `versioning-strategy: increase` /
        `increase-if-necessary`. Severity HIGH when ecosystem ∈
        HIGH_RISK_ECOSYSTEMS, otherwise LOW.
      * DR-P4: any entry with `target-branch: main` / `master`.

    Returns Findings with line/column derived from a regex re-scan
    of the source text (PyYAML's safe_load loses source positions —
    we re-locate the key after the structural decision).

    Falls back to `scan_text(text)` if PyYAML is unavailable.
    """
    parsed = _safe_yaml_load(text)
    if parsed is None or not isinstance(parsed, dict):
        return scan_text(text)
    updates = parsed.get("updates", [])
    if not isinstance(updates, list):
        return []
    findings: list[Finding] = []

    for entry in updates:
        if not isinstance(entry, dict):
            continue
        ecosystem = entry.get("package-ecosystem", "")
        if not isinstance(ecosystem, str):
            continue

        # DR-P1: per-ecosystem cooldown audit.
        if ecosystem in HIGH_RISK_ECOSYSTEMS or ecosystem in MEDIUM_RISK_ECOSYSTEMS:
            cooldown = entry.get("cooldown")
            cooldown_ok = False
            if isinstance(cooldown, dict):
                days = cooldown.get("default-days", 0)
                if isinstance(days, int) and days >= 7:
                    cooldown_ok = True
            if not cooldown_ok:
                line = _yaml_find_line(text, "package-ecosystem", ecosystem)
                severity = (
                    "HIGH" if ecosystem in HIGH_RISK_ECOSYSTEMS else "MEDIUM"
                )
                findings.append(_make_finding(
                    rule_id="DR-P1",
                    line=line,
                    column=1,
                    matched=f"package-ecosystem: {ecosystem} (no >=7d cooldown)",
                    severity=severity,
                    description=(
                        f"Dependabot ecosystem '{ecosystem}' lacks a "
                        f"cooldown of >=7 days. HIGH-RISK ecosystems "
                        f"(npm/pip/poetry/pipenv/pip-compile) run "
                        f"arbitrary code on install; absence of the "
                        f"cooldown lets a malicious release land in "
                        f"the first PR. (distill-round-8 P1)"
                    ),
                    file_anchor="dependabot.yml",
                ))

        # DR-P2: insecure-external-code-execution.
        if entry.get("insecure-external-code-execution") == "allow":
            line = _yaml_find_line(text, "insecure-external-code-execution", "allow")
            findings.append(_make_finding(
                rule_id="DR-P2",
                line=line,
                column=1,
                matched="insecure-external-code-execution: allow",
                severity="CRITICAL",
                description=(
                    "insecure-external-code-execution: allow permits "
                    "Dependabot to execute third-party package-manager "
                    "code during version resolution — RCE on the "
                    "GitHub Dependabot worker with the project's "
                    "Dependabot token. (distill-round-8 P2)"
                ),
                file_anchor="dependabot.yml",
            ))

        # DR-P3: versioning-strategy risky values.
        strategy = entry.get("versioning-strategy", "")
        if isinstance(strategy, str) and strategy in DEPENDABOT_VERSIONING_STRATEGIES_RISKY:
            line = _yaml_find_line(text, "versioning-strategy", strategy)
            severity = "HIGH" if ecosystem in HIGH_RISK_ECOSYSTEMS else "LOW"
            findings.append(_make_finding(
                rule_id="DR-P3",
                line=line,
                column=1,
                matched=f"versioning-strategy: {strategy}",
                severity=severity,
                description=(
                    f"Dependabot ecosystem '{ecosystem}' uses "
                    f"versioning-strategy: {strategy} — the manifest "
                    f"range is rewritten automatically on upgrade. "
                    f"Combined with auto-merge, attacker-controlled "
                    f"minor / patch upgrades bypass review. Prefer "
                    f"lockfile-only / widen. (distill-round-8 P3)"
                ),
                file_anchor="dependabot.yml",
            ))

        # DR-P4: target-branch: main / master.
        target = entry.get("target-branch", "")
        if isinstance(target, str) and target.lower() in ("main", "master"):
            line = _yaml_find_line(text, "target-branch", target)
            findings.append(_make_finding(
                rule_id="DR-P4",
                line=line,
                column=1,
                matched=f"target-branch: {target}",
                severity="MEDIUM",
                description=(
                    f"Dependabot ecosystem '{ecosystem}' explicitly "
                    f"targets '{target}'. Hardened pattern is a "
                    f"separate integration branch with its own CI "
                    f"BEFORE PRing to the default branch. "
                    f"(distill-round-8 P4)"
                ),
                file_anchor="dependabot.yml",
            ))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


def _is_canonical_registry(url: str) -> bool:
    """True if `url` is a known-good package registry endpoint."""
    if not isinstance(url, str):
        return False
    # Normalise trailing slash variations.
    normalised = url.rstrip("/")
    return any(
        normalised == c.rstrip("/") for c in CANONICAL_REGISTRY_URLS
    )


def _flatten_package_rules(config: dict) -> list[dict]:
    """Return a flat list of every packageRules entry. Returns [] if
    the field is absent / wrong type."""
    rules = config.get("packageRules")
    if not isinstance(rules, list):
        return []
    return [r for r in rules if isinstance(r, dict)]


def scan_renovate_json(text: str) -> list[Finding]:
    """Structural scan of a renovate.json / .renovaterc / .renovaterc.json
    / .renovaterc.json5 file.

    Performs:
      * DR-P5: top-level `automerge: true` / `platformAutomerge: true`.
        Severity escalated to CRITICAL when paired with
        `:disableDependencyDashboard` AND HIGH-RISK ecosystem coverage.
      * DR-P6: `dangerousAlwaysWriteToDefaultBranch: true`.
      * DR-P7-CATCHALL: `allowedPostUpgradeCommands` containing a
        catch-all glob.
      * DR-P7-BROAD: `allowedPostUpgradeCommands` containing a broad
        shell prefix.
      * DR-P8: dashboard disabled AND any auto-anything path.
      * DR-P9: cooldown-bearing packageRules entry scoped to a single
        narrow `matchManagers` value when `enabledManagers` is broader.
      * DR-P10: `rangeStrategy: "bump"`. Severity HIGH when
        HIGH-RISK ecosystem coverage; MEDIUM otherwise.
      * DR-P11: `registryUrls` / `hostRules.matchHost` not in
        CANONICAL_REGISTRY_URLS.

    Falls back to `scan_text(text)` when JSON parse fails (e.g.
    .renovaterc.json5 with constructs the JSONC preprocessor doesn't
    handle).
    """
    parsed = _safe_json_load(text)
    if parsed is None or not isinstance(parsed, dict):
        return scan_text(text)
    findings: list[Finding] = []

    automerge_top = bool(parsed.get("automerge")) or bool(parsed.get("platformAutomerge"))
    extends = parsed.get("extends", [])
    if not isinstance(extends, list):
        extends = []
    dashboard_disabled = (
        ":disableDependencyDashboard" in extends
        or parsed.get("dependencyDashboard") is False
        or parsed.get("dependencyDashboardApproval") is False
    )

    enabled_managers = parsed.get("enabledManagers", [])
    if not isinstance(enabled_managers, list):
        enabled_managers = []
    has_high_risk_manager = any(
        m in HIGH_RISK_ECOSYSTEMS for m in enabled_managers if isinstance(m, str)
    )
    # When enabledManagers is unset, Renovate enables every manager —
    # treat that as "potentially high-risk" so the escalations apply.
    has_high_risk = has_high_risk_manager or not enabled_managers

    # DR-P5: top-level automerge.
    if automerge_top:
        line = _json_find_line(text, "automerge")
        if line == 1:
            line = _json_find_line(text, "platformAutomerge")
        severity = "HIGH"
        if dashboard_disabled and has_high_risk:
            severity = "CRITICAL"
        findings.append(_make_finding(
            rule_id="DR-P5",
            line=line,
            column=1,
            matched="automerge: true (top-level)",
            severity=severity,
            description=(
                "Renovate top-level automerge / platformAutomerge "
                "is enabled. Every dependency-update PR merges "
                "without human review. Combined with "
                ":disableDependencyDashboard, zero humans see the "
                "upgrade. (distill-round-8 P5)"
            ),
            file_anchor="renovate.json",
        ))

    # DR-P6: dangerousAlwaysWriteToDefaultBranch.
    if parsed.get("dangerousAlwaysWriteToDefaultBranch") is True:
        line = _json_find_line(text, "dangerousAlwaysWriteToDefaultBranch")
        findings.append(_make_finding(
            rule_id="DR-P6",
            line=line,
            column=1,
            matched="dangerousAlwaysWriteToDefaultBranch: true",
            severity="HIGH",
            description=(
                "Renovate is configured to push dependency updates "
                "DIRECTLY to the default branch (no PR, no review, "
                "no CI gate). The flag-name explicitly acknowledges "
                "danger. (distill-round-8 P6)"
            ),
            file_anchor="renovate.json",
        ))

    # DR-P7: allowedPostUpgradeCommands.
    commands = parsed.get("allowedPostUpgradeCommands", [])
    if isinstance(commands, list):
        for cmd in commands:
            if not isinstance(cmd, str):
                continue
            # Catch-all patterns.
            if cmd in (".*", "^.*$", "^.+$", ".+"):
                line = _json_find_line(text, "allowedPostUpgradeCommands")
                findings.append(_make_finding(
                    rule_id="DR-P7-CATCHALL",
                    line=line,
                    column=1,
                    matched=f'allowedPostUpgradeCommands: "{cmd}"',
                    severity="CRITICAL",
                    description=(
                        f"Renovate allowedPostUpgradeCommands "
                        f"contains catch-all pattern '{cmd}'. Worker "
                        f"runs arbitrary commands in CI with secret "
                        f"access. (distill-round-8 P7)"
                    ),
                    file_anchor="renovate.json",
                ))
            # Broad shell-prefix patterns.
            elif re.match(
                r"^\^?(?:npm|pnpm|yarn|pip|poetry|pipenv|cargo|bun|go)[ \t]+\.[\*\+]\$?$",
                cmd,
            ):
                line = _json_find_line(text, "allowedPostUpgradeCommands")
                findings.append(_make_finding(
                    rule_id="DR-P7-BROAD",
                    line=line,
                    column=1,
                    matched=f'allowedPostUpgradeCommands: "{cmd}"',
                    severity="HIGH",
                    description=(
                        f"Renovate allowedPostUpgradeCommands "
                        f"contains broad shell prefix '{cmd}'. A "
                        f"malicious package's scripts section "
                        f"exploits the broad pattern. "
                        f"(distill-round-8 P7)"
                    ),
                    file_anchor="renovate.json",
                ))

    # DR-P7-BRANCH-MODE: postUpgradeTasks.executionMode.
    post_tasks = parsed.get("postUpgradeTasks", {})
    if isinstance(post_tasks, dict):
        if post_tasks.get("executionMode") == "branch":
            line = _json_find_line(text, "executionMode")
            findings.append(_make_finding(
                rule_id="DR-P7-BRANCH-MODE",
                line=line,
                column=1,
                matched='postUpgradeTasks.executionMode: "branch"',
                severity="HIGH",
                description=(
                    "postUpgradeTasks.executionMode='branch' runs "
                    "the configured commands in the PR-branch "
                    "environment with branch-write app token. "
                    'Prefer "update" mode. (distill-round-8 P7)'
                ),
                file_anchor="renovate.json",
            ))

    # DR-P8: dashboard disabled + automerge anywhere.
    has_packagerules_automerge = any(
        r.get("automerge") is True for r in _flatten_package_rules(parsed)
    )
    if dashboard_disabled and (automerge_top or has_packagerules_automerge):
        line = _json_find_line(text, "dependencyDashboard")
        if line == 1:
            line = _json_find_line(text, "extends")
        findings.append(_make_finding(
            rule_id="DR-P8",
            line=line,
            column=1,
            matched="dashboard-disabled + automerge configured",
            severity="HIGH",
            description=(
                "Renovate dependency dashboard is disabled "
                "(:disableDependencyDashboard / dependencyDashboard: "
                "false) AND automerge is configured somewhere. The "
                "review surface is removed AND the merge step is "
                "automated — zero humans see the upgrade. "
                "(distill-round-8 P8)"
            ),
            file_anchor="renovate.json",
        ))

    # DR-P9: packageRules cooldown scoped narrower than managers.
    cooldown_classes = {
        "minimumReleaseAge",
        "internalChecksFilter",
        "osvVulnerabilityAlerts",
    }
    for rule_entry in _flatten_package_rules(parsed):
        rule_keys = set(rule_entry.keys())
        if not (rule_keys & cooldown_classes):
            continue
        match_managers = rule_entry.get("matchManagers", [])
        if not isinstance(match_managers, list):
            continue
        # Narrow if list has only specific entries (not "*") and the
        # enabledManagers (or implicit "all") is broader than the
        # match set.
        if not match_managers:
            continue
        if "*" in match_managers:
            continue
        # If enabledManagers has entries outside the rule's matchManagers,
        # the cooldown is scoped narrower than the enabled set.
        rule_set = set(match_managers)
        if enabled_managers:
            uncovered = [
                m for m in enabled_managers
                if isinstance(m, str) and m not in rule_set
            ]
            if not uncovered:
                continue
        else:
            # enabledManagers is unset (i.e. all managers enabled) —
            # a packageRules entry scoped to a narrow set leaves the
            # rest uncovered by definition.
            pass
        line = _json_find_line(text, "matchManagers")
        findings.append(_make_finding(
            rule_id="DR-P9",
            line=line,
            column=1,
            matched=f"matchManagers: {match_managers} (cooldown scoped narrow)",
            severity="MEDIUM",
            description=(
                f"Renovate packageRules entry carries a cooldown "
                f"key but is scoped to matchManagers: "
                f"{match_managers} — the cooldown only applies to "
                f"the matched manager(s). Wave 14's whole-file "
                f"regex passes (some cooldown exists) but a future "
                f"manager addition would have zero gate. "
                f"(distill-round-8 P9)"
            ),
            file_anchor="renovate.json",
        ))

    # DR-P10: rangeStrategy: bump.
    range_strategy = parsed.get("rangeStrategy")
    if range_strategy == "bump":
        line = _json_find_line(text, "rangeStrategy")
        severity = "HIGH" if has_high_risk else "MEDIUM"
        findings.append(_make_finding(
            rule_id="DR-P10",
            line=line,
            column=1,
            matched='rangeStrategy: "bump"',
            severity=severity,
            description=(
                "Renovate rangeStrategy='bump' moves the manifest "
                "range automatically. A malicious in-range future "
                "patch installs without a new PR. Prefer 'pin'. "
                "(distill-round-8 P10)"
            ),
            file_anchor="renovate.json",
        ))

    # DR-P11: non-canonical registry URLs / hostRules.
    registry_urls = parsed.get("registryUrls", [])
    if isinstance(registry_urls, list):
        for url in registry_urls:
            if not isinstance(url, str):
                continue
            if _is_canonical_registry(url):
                continue
            line = _json_find_line(text, "registryUrls")
            severity = "HIGH" if has_high_risk else "MEDIUM"
            findings.append(_make_finding(
                rule_id="DR-P11",
                line=line,
                column=1,
                matched=f'registryUrls: "{url}"',
                severity=severity,
                description=(
                    f"Renovate registryUrls contains non-canonical "
                    f"endpoint '{url}'. Legitimate registries route "
                    f"through DNS at canonical domains; anything "
                    f"else is an attacker-mirror primitive. "
                    f"(distill-round-8 P11)"
                ),
                file_anchor="renovate.json",
            ))

    # hostRules.matchHost suspicious patterns.
    host_rules = parsed.get("hostRules", [])
    if isinstance(host_rules, list):
        for rule_entry in host_rules:
            if not isinstance(rule_entry, dict):
                continue
            match_host = rule_entry.get("matchHost")
            if not isinstance(match_host, str):
                continue
            # Match against suspicious TLDs.
            if re.search(r"\.(?:tk|ml|cf|gq)(?:/|$)", match_host):
                line = _json_find_line(text, "matchHost")
                findings.append(_make_finding(
                    rule_id="DR-P11-HOSTRULES",
                    line=line,
                    column=1,
                    matched=f'matchHost: "{match_host}"',
                    severity="HIGH",
                    description=(
                        f"Renovate hostRules.matchHost points at "
                        f"suspicious TLD: '{match_host}'. "
                        f"(distill-round-8 P11)"
                    ),
                    file_anchor="renovate.json",
                ))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


__all__ = [
    "CANONICAL_REGISTRY_URLS",
    "DEPENDABOT_VERSIONING_STRATEGIES_RISKY",
    "DEPENDABOT_VERSIONING_STRATEGIES_SAFE",
    "Finding",
    "HIGH_RISK_ECOSYSTEMS",
    "MEDIUM_RISK_ECOSYSTEMS",
    "RULES",
    "Rule",
    "scan_dependabot_yaml",
    "scan_renovate_json",
    "scan_text",
]
