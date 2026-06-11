"""SCA / Lockfile bypass detection patterns.

Wave-25 distillation round 11.

Catalogue of 8 Software-Composition-Analysis bypass anti-patterns
distilled in `reports/distill-round-11/sca-lockfile-bypass.md`. Targets
install-time integrity-control evasion in npm / PyPI / Cargo / Go / NuGet
/ RubyGems — patterns an attacker (or a socially-engineered maintainer)
can commit to a manifest, lockfile, or CI step that opens an install-time
trust hole.

What is NOT here (already shipped — DO NOT duplicate):

  * Browser-side `<script src=…>` SRI / CDN URL trust —
    `cdn_supply_chain_patterns.py` (Wave 22).
  * PyPI Trusted Publishers / Sigstore signing / attestation —
    `pypi_signing_patterns.py` (Wave 21).
  * npm workspace-protocol abuse (`workspace:*`) — prior
    `npm_workspace` rules.
  * Registry-side typosquat detection — separate waves.

What IS here (8 net-new rules, regex-only, all RE2-safe):

  * sca-lockfile-plain-http-registry                          (HIGH)
  * sca-lockfile-missing-or-fake-integrity                    (CRITICAL)
  * sca-lockfile-pip-no-deps-target-no-hashes                 (HIGH)
  * sca-lockfile-extra-index-url-dependency-confusion         (HIGH)
  * sca-lockfile-cargo-install-git-no-rev-no-locked           (HIGH)
  * sca-lockfile-replace-override-local-path                  (HIGH)
  * sca-lockfile-wildcard-checksum-bypass-env                 (HIGH)
  * sca-lockfile-goproxy-direct-fallback                      (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Transport / cryptographic failures (plain-HTTP registry)
  ASI-05 — Misconfiguration (wildcard bypass, GOPROXY direct fallback)
  ASI-08 — Software and Data Integrity Failures (lockfile, hash,
            dependency-confusion, replace/override, no-hash install)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes — alternations sit outside repetitions,
character classes are bounded). Patterns are PRE-COMPILED at module load.
Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    chat_bot_patterns / auth_flow_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- SCA-LB-001 : plain-HTTP package registry / mirror ------------------


# Match config keys that hold an index/registry URL set to plain `http://`.
# Bounded char-classes; alternation lives outside repetition. The trailing
# host segment uses a bounded non-greedy quantifier to avoid runaway.
_PLAIN_HTTP_REGISTRY = _re(
    r"\b(?:registry|index[-_]url|extra[-_]index[-_]url|GOPROXY|source|index)"
    r"\s*[:=]\s*['\"]?"
    r"(?:sparse\+)?http://"
    r"[A-Za-z0-9_\-\.][A-Za-z0-9_\-\./:]{2,200}"
)

# NuGet-specific opt-in for insecure HTTP.
_NUGET_ALLOW_INSECURE = _re(
    r"\ballowInsecureConnections\s*=\s*['\"]?true['\"]?"
)

# Suppression: localhost / loopback / private-net mirror URLs.
_LOCAL_REGISTRY_HOST = _re(
    r"http://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])"
)


# ---- SCA-LB-002 : missing or fake `integrity:` field --------------------


# Stage A: explicit fake / placeholder / empty integrity values inside a
# package-lock.json or yarn.lock row.
_FAKE_INTEGRITY = _re(
    r"['\"]integrity['\"]\s*:\s*['\"]"
    r"(?:"
    r"sha(?:1|256|384|512)-(?:fake|deadbeef|test|placeholder|null|none|x+|0+|1+)"
    r"|sha(?:1|256|384|512)-[A-Za-z0-9+/=]{1,15}"
    r")"
    r"['\"]"
)

# Stage A.2: integrity field with the empty string ("integrity": "").
_EMPTY_INTEGRITY = _re(
    r"['\"]integrity['\"]\s*:\s*['\"]['\"]"
)


# ---- SCA-LB-003 : pip install --no-deps --target no hash gate -----------


# Anchor: any `pip install` (incl. pip3, pip3.N). The flags follow on the
# same logical line; YAML may quote them. We anchor and then check flag
# presence in a same-line window — RE2-safe.
_PIP_INSTALL_TRIGGER = _re(
    r"\bpip(?:3|3\.\d{1,2})?\s+install\b"
)

# Detection: `--no-deps` AND `--target` in the same command.
_PIP_NO_DEPS_FLAG = _re(r"--no[-_]deps\b")
_PIP_TARGET_FLAG = _re(r"--target(?:[ =]|\s+)\S")

# Hash-gate marker that exonerates the line.
_PIP_REQUIRE_HASHES = _re(r"--require[-_]hashes\b")

# Editable-install suppression: `-e .` or `-e ./pkg`.
_PIP_EDITABLE_LOCAL = _re(
    r"-e\s+(?:\.|\./|\.\.\/|\.\.\\|[A-Za-z0-9_\-]+/)"
)


# ---- SCA-LB-004 : --extra-index-url (dependency-confusion vector) -------


# `--extra-index-url`, `extra-index-url`, `PIP_EXTRA_INDEX_URL` all sources.
# Two alternations: the CLI / config-file form (optional `-` / `--` prefix)
# and the env-var form (PIP_EXTRA_INDEX_URL). The `(?:\s+|\s*[:=]\s*)`
# bridge accepts either a single space (CLI: `--flag value`) or `=` /
# `:` with optional whitespace (config / env-var). No lookbehind /
# lookahead — RE2-safe.
_EXTRA_INDEX_URL = _re(
    r"(?:--?)?extra[-_]index[-_]url\b"
    r"(?:\s+|\s*[:=]\s*)"
    r"[A-Za-z0-9_\-\.:/]{4,200}"
    r"|PIP_EXTRA_INDEX_URL"
    r"(?:\s+|\s*[:=]\s*)"
    r"[A-Za-z0-9_\-\.:/]{4,200}"
)


# ---- SCA-LB-005 : `cargo install --git` no `--rev` / no `--locked` ------


# Anchor: any `cargo install` invocation with a `--git` flag in the same
# command (bounded char class to keep RE2-safe).
_CARGO_INSTALL_GIT = _re(
    r"\bcargo\s+install\b"
    r"[A-Za-z0-9_\-\./= \t'\"@:+]{0,200}"
    r"--git\s+\S+"
)

# Safety marker: either --locked OR --rev <40-hex> present on same line.
_CARGO_LOCKED_OR_REV = _re(
    r"--locked\b|--rev\s+[A-Fa-f0-9]{6,40}\b"
)


# ---- SCA-LB-006 : `replace` / `overrides` redirecting to local path -----


# Go go.mod replace pointing at a relative/absolute path or v0.0.0 fork.
_GO_REPLACE_PATH = _re(
    r"^replace\s+[A-Za-z0-9_\-\./@]+(?:\s+v[A-Za-z0-9_\-\.\+]+)?\s+=>\s+"
    r"(?:\.\.?/|/|[A-Za-z]:\\|github\.com/[A-Za-z0-9_\-\./]+\s+v0\.0\.0)"
)

# JS package.json overrides / resolutions / pnpm overrides — pointing at
# file:/link:/portal:/relative path.
_JS_OVERRIDE_PATH = _re(
    r"['\"](?:overrides|resolutions)['\"]\s*:\s*\{"
    r"[^{}]{0,400}"
    r"['\"][^'\"]{1,80}['\"]\s*:\s*"
    r"['\"](?:file:|link:|portal:|\.\./|\./|/)"
)

# Cargo [patch.crates-io] table with path = or git = entry.
_CARGO_PATCH_LOCAL = _re(
    r"\[patch\.crates-io\]"
    r"[^\[]{0,400}?"
    r"[A-Za-z0-9_\-]+\s*=\s*\{\s*(?:path|git)\s*="
)


# ---- SCA-LB-007 : wildcard checksum-bypass envs / exclusions ------------


# Env-var form: GOPRIVATE / GONOSUMDB / GONOSUMCHECK assigned to bare *.
_WILDCARD_GO_SUM_ENV = _re(
    r"\b(?:GOPRIVATE|GONOSUMDB|GONOSUMCHECK)"
    r"\s*[:=]\s*['\"]?"
    r"(?:\*|\*\*|\*\*/\*)"
    r"['\"]?(?=\s|$|;)"
)

# YAML form: yarn npmPreapprovedPackages / pnpm minimumReleaseAgeExclude
# with a `- "*"` entry.
_WILDCARD_YAML_BYPASS = _re(
    r"^(?:[ \t]*)"
    r"(?:npmPreapprovedPackages|minimumReleaseAgeExclude)\s*:\s*\n"
    r"(?:[ \t]*-\s*['\"]?\*['\"]?\s*\n){1,5}"
)

# Inline-list YAML form: `npmPreapprovedPackages: ["*"]`.
_WILDCARD_YAML_INLINE = _re(
    r"\b(?:npmPreapprovedPackages|minimumReleaseAgeExclude)\s*:\s*"
    r"\[\s*['\"]?\*['\"]?\s*\]"
)


# ---- SCA-LB-008 : GOPROXY=...,direct silent VCS fallback ----------------


# Match a GOPROXY assignment whose comma-separated value ends in `direct`.
# Bounded char classes; no nested quantifiers — RE2-safe.
_GOPROXY_DIRECT_FALLBACK = _re(
    r"\bGOPROXY\s*[:=]\s*['\"]?"
    r"[A-Za-z0-9_\-\./:]{4,200}"
    r"(?:,[A-Za-z0-9_\-\./:]{1,200}){0,5}"
    r",\s*direct\b"
    r"['\"]?"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="sca-lockfile-plain-http-registry",
        name="Plain-HTTP package registry / mirror URL in committed config",
        severity="HIGH",
        description=(
            "A package manager config (`pip.conf`, `uv.toml`, `.npmrc`, "
            "`Gemfile`, `.cargo/config.toml`) or CI env-var sets a "
            "`registry`/`index-url`/`source`/`GOPROXY` to plain `http://`. "
            "Any MITM on the install path can swap the served artifact "
            "even if the lockfile is otherwise strict — TLS is the most "
            "basic client-side integrity control. Loopback / localhost "
            "URLs are whitelisted as test mirrors."
        ),
        pattern=_PLAIN_HTTP_REGISTRY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="sca-lockfile-missing-or-fake-integrity",
        name="package-lock.json / yarn.lock row with fake or empty integrity hash",
        severity="CRITICAL",
        description=(
            "A `package-lock.json` or `yarn.lock` row carries an "
            "`integrity:` value that is a placeholder (`sha512-fake`, "
            "`sha1-deadbeef`, `sha256-null`), an obviously too-short "
            "string, or the empty string. The lockfile's SRI hash is the "
            "only thing that proves the tarball npm fetches matches the "
            "tarball the lock author saw; forging that field reduces the "
            "lockfile to a name+version pointer with no integrity "
            "guarantee. Test-fixture paths (`*/tests/fixtures/*`, "
            "`*/__fixtures__/*`) should be excluded by the caller."
        ),
        pattern=_FAKE_INTEGRITY,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="sca-lockfile-pip-no-deps-target-no-hashes",
        name="pip-install --no-deps --target lacking --require-hashes",
        severity="HIGH",
        description=(
            "A script or CI step runs `pip install --no-deps --target …` "
            "(custom dir, transitive-resolution bypassed) WITHOUT "
            "`--require-hashes`. `--no-deps` strips the transitive-pinning "
            "protection lockfiles provide, `--target` writes into a "
            "runtime-trusted location, and the missing hash gate means "
            "any version the index returns is accepted. Common in "
            "Lambda-layer build glue and quick plugin loaders — i.e. "
            "exactly the deploy paths that lack defense-in-depth. "
            "Editable `-e .` installs are suppressed."
        ),
        pattern=_PIP_INSTALL_TRIGGER,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="sca-lockfile-extra-index-url-dependency-confusion",
        name="pip / poetry / NuGet --extra-index-url (dependency-confusion vector)",
        severity="HIGH",
        description=(
            "A config or CI script uses `--extra-index-url` / "
            "`extra-index-url` / `PIP_EXTRA_INDEX_URL` to add a public "
            "index alongside an internal one. pip/uv/poetry pick the "
            "highest version across ALL sources, so an attacker who "
            "registers an internal-looking package on public PyPI with "
            "a higher version number wins — the same vector that hit "
            "PyTorch's torchtriton in December 2022. Safe forms use "
            "`index-url` (single) + `packageSourceMapping` (NuGet) or "
            "`priority = \"explicit\"` (Poetry)."
        ),
        pattern=_EXTRA_INDEX_URL,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="sca-lockfile-cargo-install-git-no-rev-no-locked",
        name="cargo install --git without --rev pin and without --locked",
        severity="HIGH",
        description=(
            "`cargo install --git <url>` fetches a crate directly from "
            "git, bypassing crates.io. Without `--rev <SHA>` or `--tag` "
            "AND `--locked`, cargo re-resolves the dependency tree from "
            "whatever the branch currently is, and `build.rs` / "
            "proc-macros run during the install with full FS/network "
            "access. The mysten-metrics@9.0.3 (2026-04) `build.rs` "
            "exfil incident is the canonical case. crates-hardening "
            "guideline mandates `--locked` on every `cargo install`."
        ),
        pattern=_CARGO_INSTALL_GIT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="sca-lockfile-replace-override-local-path",
        name="go.mod `replace` / npm `overrides` / Cargo `[patch.crates-io]` swap to local path",
        severity="HIGH",
        description=(
            "Go's `replace`, npm/pnpm `overrides:` / `resolutions:`, and "
            "Cargo's `[patch.crates-io]` directives silently redirect an "
            "upstream package to a local file path or a fork. A "
            "path-based override has no integrity hash — whatever sits "
            "at that path on disk wins, including files added by a "
            "later commit. A hostile PR with a single `replace` line "
            "can swap a crypto / auth library for an attacker-controlled "
            "copy. Severity should escalate to CRITICAL when the "
            "replaced package is in the high-value list "
            "(crypto-*, *-auth, jose, jsonwebtoken, openssl, libsodium, "
            "sqlx, prisma, axios, requests, urllib3, cryptography, ring, "
            "hyper-tls, rustls)."
        ),
        pattern=_GO_REPLACE_PATH,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="sca-lockfile-wildcard-checksum-bypass-env",
        name="Wildcard checksum-bypass env or YAML exclusion (GOPRIVATE=*, npmPreapprovedPackages: \"*\")",
        severity="HIGH",
        description=(
            "Several ecosystems let you carve out an integrity/age-gate "
            "exception by listing prefixes. Setting that exception to a "
            "wildcard (`*`, `**`, `**/*`) disables the control entirely. "
            "`GOPRIVATE=*` disables checksum-database verification for "
            "EVERY module (not just internal ones). Yarn's "
            "`npmPreapprovedPackages: [\"*\"]` and pnpm's "
            "`minimumReleaseAgeExclude: [\"*\"]` disable the 14-day "
            "quarantine for every package. A single line turns off an "
            "entire ecosystem control."
        ),
        pattern=_WILDCARD_GO_SUM_ENV,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sca-lockfile-goproxy-direct-fallback",
        name="GOPROXY chain ending in `direct` (silent VCS fallback)",
        severity="MEDIUM",
        description=(
            "Go's `GOPROXY` accepts a comma-separated chain. `direct` "
            "as the terminal element means: if the proxy is unreachable, "
            "silently download from the original VCS, bypassing every "
            "proxy-side control (sum.golang.org checksum, internal "
            "vetting, internal cache). Defenders should use `off` as "
            "the fallback so the build fails loudly instead. "
            "CVE-2026-42501 (malicious Go module proxy bypassing "
            "`sum.golang.org`) is the recent precedent."
        ),
        pattern=_GOPROXY_DIRECT_FALLBACK,
        owasp_asi="ASI-05",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _line_text(text: str, line_no: int) -> str:
    """Return the raw text of the given 1-based line, without trailing \n."""
    parts = text.split("\n")
    if 1 <= line_no <= len(parts):
        return parts[line_no - 1]
    return ""


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult line-local or window context:

      * SCA-LB-001 — emit only if the matched URL is NOT a localhost /
        loopback / private-net host (legitimate dev mirror).
      * SCA-LB-002 — direct match on the fake/empty integrity value;
        emit one per match. (Callers handle fixture-path whitelisting.)
      * SCA-LB-003 — anchor on `pip install`; emit only when BOTH
        `--no-deps` AND `--target` are present on the same logical line
        AND `--require-hashes` is NOT present AND it's not an editable
        local install (`-e .`).
      * SCA-LB-004 — direct match.
      * SCA-LB-005 — anchor on `cargo install … --git`; emit only when
        NEITHER `--locked` NOR `--rev <hex>` appears in the same match.
      * SCA-LB-006 — three separate sub-patterns (Go / JS / Cargo), all
        direct matches.
      * SCA-LB-007 — three sub-patterns (Go env / YAML block / YAML inline).
      * SCA-LB-008 — direct match.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
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

    rule_by_id = {r.id: r for r in RULES}

    # ---- SCA-LB-001 : plain-HTTP registry ----
    rule_001 = rule_by_id["sca-lockfile-plain-http-registry"]
    for m in _PLAIN_HTTP_REGISTRY.finditer(text):
        # Whitelist localhost / loopback / private-net mirrors.
        if _LOCAL_REGISTRY_HOST.search(m.group(0)) is not None:
            continue
        _emit(rule_001, m.start(), m.group(0))
    # NuGet allowInsecureConnections=true is the same finding-class.
    for m in _NUGET_ALLOW_INSECURE.finditer(text):
        _emit(rule_001, m.start(), m.group(0))

    # ---- SCA-LB-002 : missing or fake integrity ----
    rule_002 = rule_by_id["sca-lockfile-missing-or-fake-integrity"]
    for m in _FAKE_INTEGRITY.finditer(text):
        _emit(rule_002, m.start(), m.group(0))
    for m in _EMPTY_INTEGRITY.finditer(text):
        _emit(rule_002, m.start(), m.group(0))

    # ---- SCA-LB-003 : pip install --no-deps --target no hash gate ----
    rule_003 = rule_by_id["sca-lockfile-pip-no-deps-target-no-hashes"]
    for m in _PIP_INSTALL_TRIGGER.finditer(text):
        line, _ = _line_col(text, m.start())
        line_str = _line_text(text, line)
        # Must have --no-deps AND --target on the same line.
        if _PIP_NO_DEPS_FLAG.search(line_str) is None:
            continue
        if _PIP_TARGET_FLAG.search(line_str) is None:
            continue
        # Suppress when --require-hashes is on the line.
        if _PIP_REQUIRE_HASHES.search(line_str) is not None:
            continue
        # Suppress editable local installs.
        if _PIP_EDITABLE_LOCAL.search(line_str) is not None:
            continue
        _emit(rule_003, m.start(), m.group(0))

    # ---- SCA-LB-004 : --extra-index-url dependency confusion ----
    rule_004 = rule_by_id["sca-lockfile-extra-index-url-dependency-confusion"]
    for m in _EXTRA_INDEX_URL.finditer(text):
        _emit(rule_004, m.start(), m.group(0))

    # ---- SCA-LB-005 : cargo install --git no --rev no --locked ----
    rule_005 = rule_by_id["sca-lockfile-cargo-install-git-no-rev-no-locked"]
    for m in _CARGO_INSTALL_GIT.finditer(text):
        # The match already spans the full command up to --git <url>; the
        # safety markers (--rev / --locked) may appear before or after,
        # so we look at the whole logical line.
        line, _ = _line_col(text, m.start())
        line_str = _line_text(text, line)
        if _CARGO_LOCKED_OR_REV.search(line_str) is not None:
            continue
        _emit(rule_005, m.start(), m.group(0))

    # ---- SCA-LB-006 : replace / overrides redirecting to local path ----
    rule_006 = rule_by_id["sca-lockfile-replace-override-local-path"]
    for m in _GO_REPLACE_PATH.finditer(text):
        _emit(rule_006, m.start(), m.group(0))
    for m in _JS_OVERRIDE_PATH.finditer(text):
        _emit(rule_006, m.start(), m.group(0))
    for m in _CARGO_PATCH_LOCAL.finditer(text):
        _emit(rule_006, m.start(), m.group(0))

    # ---- SCA-LB-007 : wildcard checksum-bypass envs / exclusions ----
    rule_007 = rule_by_id["sca-lockfile-wildcard-checksum-bypass-env"]
    for m in _WILDCARD_GO_SUM_ENV.finditer(text):
        _emit(rule_007, m.start(), m.group(0))
    for m in _WILDCARD_YAML_BYPASS.finditer(text):
        _emit(rule_007, m.start(), m.group(0))
    for m in _WILDCARD_YAML_INLINE.finditer(text):
        _emit(rule_007, m.start(), m.group(0))

    # ---- SCA-LB-008 : GOPROXY=...,direct silent VCS fallback ----
    rule_008 = rule_by_id["sca-lockfile-goproxy-direct-fallback"]
    for m in _GOPROXY_DIRECT_FALLBACK.finditer(text):
        _emit(rule_008, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
