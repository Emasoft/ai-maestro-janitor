"""Package-manager BYPASS / SMUGGLING detector — text-scan rules.

Third leg of the three-leg pkg-bypass design:

  * `scripts/hooks/pre-tool-pkg-guard.py`     — LIVE / future-tense.
        Blocks the bypass flag at agent-call time (Bash/Edit/Write).
  * `scripts/detectors/package-manager-policy.py` — STATUS QUO / config.
        Reports MISSING hardening in `.npmrc`, `package.json#pnpm`,
        `pnpm-workspace.yaml`, `.yarnrc.yml`, `bunfig.toml`.
  * THIS MODULE — ON-DISK / text scan.
        Catches the bypass flag in any human-authored text the agent
        will read or execute: CI workflows, install scripts, README
        copy-paste recipes, Dockerfiles, INSTALL.md, docs/.

A CI step `npm install --ignore-scripts=false` runs every PR. A README
banner `"if pnpm refuses, run with --ignore-scripts=false"` trains every
future contributor (and every agent reading the README) to break the
guard. The hook catches the moment, but the moment is too late — the
file already poisons the repo's culture and CI. Once merged, the bypass
flag is invisible to the existing hook (the hook sees the Bash command
the agent issues, not the workflow file the user copy-pastes from). It
is also invisible to the existing policy detector (the config files are
still hardened). Only a workflow / README / script SCAN catches it.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi, ecosystem)
                                  — single rule record.
  * RULES                         — ordered tuple of every catalogued
                                    bypass rule (8 total).
  * scan_text(text)  -> list[Finding]
                                  — run every rule against `text`.
  * Finding(rule_id, line, column, matched_text, severity, description,
                                  owasp_asi, ecosystem)
                                  — single finding record. Frozen.

All patterns are anchored to the actual COMMAND SURFACE (e.g.
`\\bnpm\\s+(?:i|install|ci|add)\\b`) so they NEVER fire on prose that
merely DESCRIBES the flag (`"the --ignore-scripts=false flag is..."`).
Pure stdlib (re, NamedTuple) — no third-party deps, no network, no I/O.

Rule severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW", matching
the existing janitor sentinel/zizmor convention. OWASP ASI mapping is
ASI-05 (Insecure Supply Chain) for every rule in this module since
every bypass detected here weakens the supply-chain guard rails.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as agent_config_patterns.Finding
    plus an `ecosystem` discriminator so heartbeat detectors can group
    findings by package manager."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str
    ecosystem: str  # e.g. "npm", "pnpm", "yarn", "bun", "pip", "uv",
                   # "cargo", "composer", "gem"


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str
    ecosystem: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE + MULTILINE + UNICODE.

    Bypass flags are case-insensitive on the canonical case mostly because
    Windows shells / README copy-paste tend to randomize casing on the
    flag name. The flag VALUES (`true`, `false`) are also case-insensitive
    in the actual package managers, so we follow suit.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Rule 1: NPM ignore-scripts=false (HIGH) -----------------------------

# Anchored to a real npm/yarn/bun install subcommand. Catches:
#   npm install --ignore-scripts=false
#   npm i --ignore-scripts = false
#   yarn add foo --ignore-scripts=false
#   bun ci --ignore-scripts=false
# Does NOT catch:
#   "the --ignore-scripts=false flag re-enables postinstall RCE"
#   (prose without `npm|yarn|bun` + subcommand anchor)
#
# Rationale: `--ignore-scripts=false` is the EXACT reversal of the canonical
# npm baseline (`ignore-scripts=true`). Re-enables postinstall RCE — the
# primary npm supply-chain attack surface (art-template, chalk, nx, etc.).
# Once in a CI workflow it runs every PR, every push, every release.
_NPM_SCRIPTS_FLAG = _re(
    r"\b(?:npm|yarn|bun)\s+(?:i|install|ci|add)\b[^\n]*\s--ignore-scripts\s*=\s*false\b",
)


# ---- Rule 2: PNPM hoist / lockfile / quarantine bypasses (HIGH) ----------

# Catches any of pnpm's six known weakening flags on an install/add/update.
# All six are explicit reversals of the strict-isolation defaults that
# protect against transitive smuggling and lockfile drift.
#
#   --shamefully-hoist   — flattens transitives into ./node_modules/,
#                          bypassing pnpm's strict-isolation defense
#                          against accidental transitive imports.
#   --no-frozen-lockfile — lets CI proceed with lockfile drift (attacker
#                          can ship a new transitive nobody reviewed).
#   --ignore-scripts=false — re-enables postinstall script execution.
#   --no-min-release-age — DIRECT counter of the 5-day quarantine the
#                          repo's .npmrc enforces; THE MOST DANGEROUS flag
#                          pnpm exposes for this threat model.
#   --ignore-pnpmfile    — skips trusted-script / hook policies.
#   --no-verify-store-integrity — disables store integrity check.
_PNPM_HOIST_LOCKFILE = _re(
    r"\bpnpm\s+(?:i|install|add|update|up)\b[^\n]*\s(?:"
    r"--shamefully-hoist\b"
    r"|--no-frozen-lockfile\b"
    r"|--ignore-scripts\s*=\s*false\b"
    r"|--no-min-release-age\b"
    r"|--ignore-pnpmfile\b"
    r"|--no-verify-store-integrity\b"
    r")",
)


# ---- Rule 3: YARN script-execution / checksum bypasses (HIGH) ------------

# Yarn Berry's `enableScripts true` is the explicit reversal of the safer
# default. `--update-checksums` overwrites the lockfile's integrity column
# — the literal attack vector in checksum-mismatch incidents (a malicious
# actor can swap a tarball without anyone noticing the SHA changed).
# `--check-files=false` silences yarn's PnP integrity verifier.
#
# IMPORTANT: We deliberately DO NOT match `--ignore-scripts` (the BARE form)
# because in yarn Berry the bare form is the SAFE form (means "skip
# scripts during install"). Only the EXPLICIT --enable-scripts true /
# config-set enableScripts true is the WEAKENING direction.
_YARN_SCRIPTS_CHECKSUM = _re(
    r"\byarn\s+(?:install|add|up|config\s+set)\b[^\n]*\s(?:"
    r"--check-files\s*=\s*false\b"
    r"|--update-checksums\b"
    r"|--enable-scripts\s+true\b"
    r"|enableScripts\s+true\b"
    r")",
)


# ---- Rule 4: PIP / UV build-isolation / break-system / no-deps (HIGH) ----

# `--break-system-packages` is PEP 668's emergency-override and a direct
# route to a system-Python takeover. `--no-build-isolation` lets a
# malicious setup.py import from the running interpreter (escapes the
# PEP 517 build sandbox). `--no-deps` evades the transitive scanner that
# Socket / OSV-Scanner / pip-audit rely on. `--trusted-host` for any
# non-loopback host disables TLS verification — an MITM smuggle path.
#
# We EXCLUDE `--trusted-host localhost|127.0.0.1` (legitimate proxy setup).
# We DO NOT match `--no-cache` (legitimately used in CI to avoid cache
# poisoning).
_PIP_UV_BYPASS = _re(
    r"\b(?:pip|pip3|uv\s+pip)\s+install\b[^\n]*\s(?:"
    r"--no-build-isolation\b"
    r"|--break-system-packages\b"
    r"|--no-deps\b"
    r"|--no-verify\b"
    r"|--trusted-host\s+(?!localhost\b|127\.0\.0\.1\b)\S+"
    r")",
)


# ---- Rule 5: CARGO --git + --no-default-features combo (MEDIUM) ----------

# The DANGEROUS pattern is the COMBINATION: `cargo install --git URL
# --no-default-features` skips the crate's own opt-in safety features
# (constant-time crypto, audited subsystems, etc.) AND bypasses crates.io
# review entirely. Either flag alone is legitimate; both together on a
# single line is the smuggling pattern.
#
# `--no-verify` (without --git) is also a weakening; we catch that too.
#
# Pattern uses lookahead AND on the same `cargo` invocation line — the
# `[^\n]*` between flags pins them to the same physical line.
_CARGO_GIT_NO_DEFAULTS = _re(
    r"\bcargo\s+(?:install|add|fetch|build)\b"
    r"(?:[^\n]*\s--git\s+\S+[^\n]*\s--no-default-features\b"
    r"|[^\n]*\s--no-default-features\b[^\n]*\s--git\s+\S+"
    r"|[^\n]*\s--no-verify\b)",
)


# ---- Rule 6: COMPOSER allow-plugins wildcard + --no-scripts=false (HIGH) -

# Two distinct shapes:
#   (a) CLI form: `composer install --no-scripts=false` or
#                 `composer install --no-plugins=false`.
#   (b) Config form: `"allow-plugins": { "*": true }` in composer.json —
#                    the wildcard form is the smuggle (legitimate use
#                    requires per-plugin FQN allows).
#
# Two patterns OR'd. The composer.json wildcard form is recognised
# even with arbitrary internal whitespace.
_COMPOSER_BYPASS_CLI = _re(
    r"\bcomposer\s+(?:install|update|require)\b[^\n]*\s(?:"
    r"--no-plugins\s*=\s*false\b"
    r"|--no-scripts\s*=\s*false\b"
    r")",
)

_COMPOSER_ALLOW_WILDCARD = _re(
    r'"allow-plugins"\s*:\s*\{\s*"\*"\s*:\s*true\s*\}',
)


# Combined into one pattern with alternation so a single re.finditer call
# covers both shapes.
_COMPOSER_BYPASS = _re(
    _COMPOSER_BYPASS_CLI.pattern + r"|" + _COMPOSER_ALLOW_WILDCARD.pattern,
)


# ---- Rule 7: GEM --pre / --ignore-dependencies / --force (MEDIUM) --------

# `--pre` opts into preview versions — typically NOT subject to the same
# review window as the stable release. The "feature flag" of fresh-publish
# attacks (an attacker can ship `1.2.3-pre.1` and have it land in CI
# before the 5-day quarantine on `1.2.3` expires). `--ignore-dependencies`
# evades the transitive scanner (same problem as `pip --no-deps`).
# `--force` skips signature verification (--no-verify is the alias).
_GEM_BYPASS = _re(
    r"\bgem\s+install\b[^\n]*\s(?:"
    r"--pre\b"
    r"|--ignore-dependencies\b"
    r"|--force\b"
    r"|--no-verify\b"
    r")",
)


# ---- Rule 8: BUN --no-cache / --no-verify / --trust (MEDIUM) -------------

# Bun's `--trust pkgname` is the per-invocation override that bypasses the
# trustedDependencies allowlist (bun equivalent of `--ignore-scripts=false`
# but per-package). `--no-cache` forces a fresh fetch every time which
# weakens the "I already verified this version" property of the local
# cache (AND increases registry-MITM exposure). `--no-verify` is the
# bun nuclear option.
#
# We also match `--no-frozen-lockfile` and `--ignore-scripts=false` here
# (defensive duplication of Rule 1's bun coverage — text scan needs full
# bun surface independent of npm/yarn).
_BUN_NO_CACHE_VERIFY = _re(
    r"\bbun\s+(?:i|install|add)\b[^\n]*\s(?:"
    r"--no-cache\b"
    r"|--no-verify\b"
    r"|--no-frozen-lockfile\b"
    r"|--trust\s+\S+"
    r"|--ignore-scripts\s*=\s*false\b"
    r")",
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="PKG-BYPASS-NPM-SCRIPTS-FLAG",
        name="npm/yarn/bun --ignore-scripts=false",
        severity="HIGH",
        description=(
            "An install command re-enables postinstall script execution via "
            "--ignore-scripts=false. Re-opens the primary npm supply-chain "
            "attack surface (chalk, nx, art-template pattern). Once in a CI "
            "workflow it runs every PR, every push."
        ),
        pattern=_NPM_SCRIPTS_FLAG,
        owasp_asi="ASI-05",
        ecosystem="npm",
    ),
    Rule(
        id="PKG-BYPASS-PNPM-HOIST-OR-LOCKFILE",
        name="pnpm strict-isolation / lockfile / quarantine bypass",
        severity="HIGH",
        description=(
            "A pnpm install/add/update command uses --shamefully-hoist, "
            "--no-frozen-lockfile, --ignore-scripts=false, --no-min-release-age, "
            "--ignore-pnpmfile, or --no-verify-store-integrity — each one "
            "reverses a strict-isolation default. --no-min-release-age is the "
            "direct counter of the 5-day quarantine."
        ),
        pattern=_PNPM_HOIST_LOCKFILE,
        owasp_asi="ASI-05",
        ecosystem="pnpm",
    ),
    Rule(
        id="PKG-BYPASS-YARN-SCRIPTS-OR-CHECKSUMS",
        name="yarn enableScripts / --update-checksums / --check-files=false",
        severity="HIGH",
        description=(
            "A yarn invocation enables scripts (enableScripts true / "
            "--enable-scripts true), overwrites lockfile integrity "
            "(--update-checksums — the literal checksum-mismatch attack), or "
            "silences PnP integrity verification (--check-files=false)."
        ),
        pattern=_YARN_SCRIPTS_CHECKSUM,
        owasp_asi="ASI-05",
        ecosystem="yarn",
    ),
    Rule(
        id="PKG-BYPASS-PIP-UV-ISOLATION-OR-BREAK-SYSTEM",
        name="pip/uv --break-system-packages / --no-build-isolation / --no-deps",
        severity="HIGH",
        description=(
            "A pip / uv pip install command uses --break-system-packages "
            "(PEP 668 override → system-Python takeover), --no-build-isolation "
            "(escapes the PEP 517 build sandbox), --no-deps (evades transitive "
            "scanners), --no-verify, or --trusted-host pointing at a non-loopback "
            "host (TLS-stripping MITM)."
        ),
        pattern=_PIP_UV_BYPASS,
        owasp_asi="ASI-05",
        ecosystem="pip",
    ),
    Rule(
        id="PKG-BYPASS-CARGO-GIT-NO-DEFAULTS",
        name="cargo install --git URL --no-default-features (or --no-verify)",
        severity="MEDIUM",
        description=(
            "A cargo command combines --git <URL> with --no-default-features "
            "— bypasses crates.io review AND skips the crate's opt-in safety "
            "features. Either flag alone is legitimate; the conjunction is "
            "the smuggling pattern. --no-verify alone also matches."
        ),
        pattern=_CARGO_GIT_NO_DEFAULTS,
        owasp_asi="ASI-05",
        ecosystem="cargo",
    ),
    Rule(
        id="PKG-BYPASS-COMPOSER-PLUGINS-OR-SCRIPTS",
        name="composer --no-scripts=false / allow-plugins wildcard",
        severity="HIGH",
        description=(
            "A composer install/update/require uses --no-scripts=false / "
            "--no-plugins=false, OR composer.json contains "
            '"allow-plugins": { "*": true } — the wildcard form is the '
            "explicit reversal of the safety knob (legitimate use requires "
            "per-plugin FQN allowlists)."
        ),
        pattern=_COMPOSER_BYPASS,
        owasp_asi="ASI-05",
        ecosystem="composer",
    ),
    Rule(
        id="PKG-BYPASS-GEM-PRE-OR-IGNORE-DEPS",
        name="gem install --pre / --ignore-dependencies / --force",
        severity="MEDIUM",
        description=(
            "A gem install uses --pre (opts into preview versions that "
            "bypass the stable-release review window — the rest-client 2019 "
            "incident vector), --ignore-dependencies (evades transitive "
            "scanners), --force or --no-verify (skip signature verification)."
        ),
        pattern=_GEM_BYPASS,
        owasp_asi="ASI-05",
        ecosystem="gem",
    ),
    Rule(
        id="PKG-BYPASS-BUN-NO-CACHE-OR-VERIFY",
        name="bun install --no-cache / --no-verify / --trust / --ignore-scripts=false",
        severity="MEDIUM",
        description=(
            "A bun install/add command uses --trust <pkg> (per-package "
            "override of trustedDependencies), --no-cache (weakens cache-"
            "verified state + increases MITM exposure), --no-verify (bun "
            "nuclear option), --no-frozen-lockfile, or --ignore-scripts=false."
        ),
        pattern=_BUN_NO_CACHE_VERIFY,
        owasp_asi="ASI-05",
        ecosystem="bun",
    ),
)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).

    Same helper shape as agent_config_patterns._line_col so consumers
    can render findings from either module uniformly.
    """
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    Findings are deduped by (rule_id, line, column) — a single line that
    triggers two rules emits two findings, but the same rule firing twice
    on the same line emits one.

    Caller is responsible for scope filtering (only invoke on paths the
    pkg-bypass scan was authorised to look at — see the detector wrapper
    in `scripts/detectors/pkg-manager-bypass-scan.py` for the canonical
    scope-glob list: workflows, scripts, Dockerfiles, README, INSTALL,
    docs/).
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
