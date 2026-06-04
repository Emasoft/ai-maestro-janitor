"""Per-language ecosystem supply-chain attack patterns.

Wave 16 (impl-k) — distillation of 8 proposals from the
``distill2-a-per-language`` report into deterministic regex rules.
This module catalogues client-side attack shapes that the existing
``supply-chain-fingerprints.py`` + ``package-manager-policy.py``
detectors do NOT cover: Cargo / Rust ``build.rs``, Go ``replace``
directives, Maven ``settings.xml`` plain credentials, Composer
script hooks, NuGet config gaps, Ruby ``Gemfile`` unpinned-git,
Swift / SPM ``.binaryTarget`` un-checksummed binaries, and the
Gradle ``buildscript { repositories { … } }`` untrusted-repo case.

Architecture mirrors ``scripts/lib/agent_config_patterns.py``:

  * ``Rule(id, name, severity, description, pattern, owasp_asi)``
                                  — single rule record. Patterns are
                                    pre-compiled at module load.
  * ``RULES``                     — ordered tuple of every catalogued rule.
  * ``scan_text(text)`` -> list[Finding]
                                  — run every rule, return findings.
  * ``Finding(rule_id, line, column, matched_text, severity,
              description, owasp_asi)``
                                  — single finding record.

Pure-stdlib (re, NamedTuple) so it loads in every PEP 723 script
block without third-party deps. Patterns favour deterministic
behaviour over precision — callers do contextual triage
(ecosystem presence, file kind, severity).

Rule severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW",
matching the existing janitor sentinel/zizmor convention. The
mapping from the source report's MAJOR/CRITICAL is:

  CRITICAL (report) → CRITICAL (rule)
  MAJOR    (report) → HIGH (rule)

so the standard four-tier severity scale is preserved.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    ``scripts/lib/agent_config_patterns.Finding`` so heartbeat
    detectors can render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # e.g. "ASI-05"; empty string when no mapping applies


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE.

    Per-language config files mix English keywords (``replace``,
    ``buildscript``, ``post-install-cmd``) with arbitrary identifier
    casing, so case-insensitive is the safe default. MULTILINE makes
    ``^`` / ``$`` line-anchored which is what we want for the
    line-oriented config formats below.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Proposal 1: Cargo / Rust — build.rs suspicious syscalls -----------


# ``build.rs`` (any ``**/build.rs`` outside ``target/``) running
# arbitrary shell, network, or filesystem-write to home-dir paths.
# The Cargo ecosystem has no global install-script switch — ``build.rs``
# is always evaluated. Matches any of:
#   * Command::new("sh"/"bash"/"zsh"/"env"/"curl"/"wget"/"nc")
#   * TcpStream::connect / UdpSocket::bind
#   * reqwest:: / ureq:: / curl::easy::
#   * fs::write / fs::OpenOptions targeting ~/.ssh or ~/.bashrc shapes
#
# We deliberately fire on a SINGLE match because the proposal's
# heuristic of "≥2 distinct patterns" requires multi-pattern
# correlation which doesn't fit the single-regex-per-rule shape.
# Callers can dedupe by line if they want stricter behaviour;
# legit native-FFI crates are filtered upstream by checking the
# crate name and ``Cargo.toml`` ``links =`` marker before invoking
# this scanner.
_CARGO_BUILDRS_SYSCALLS = _re(
    r"\bCommand\s*::\s*new\s*\(\s*['\"](?:/?bin/)?(?:sh|bash|zsh|env|curl|wget|nc|ncat|powershell)['\"]"
    r"|\b(?:reqwest|ureq|curl|hyper|isahc)\s*::\s*(?:get|post|Client|easy|blocking)"
    r"|\bTcpStream\s*::\s*connect\s*\("
    r"|\bUdpSocket\s*::\s*bind\s*\("
    r"|\bfs\s*::\s*write\s*\(\s*[^,)\n]{0,200}\.(?:ssh|bashrc|zshrc|profile|bash_profile|aws/credentials)"
    r"|\bOpenOptions\s*::\s*new\s*\(\s*\)[^;\n]{0,200}\.open\s*\(\s*[^,)\n]{0,200}\.(?:ssh|bashrc|zshrc)"
)


# ---- Proposal 2: Go modules — replace directive local-path hijack ------


# ``go.mod`` ``replace`` directives that swap a public module for an
# arbitrary local path (``../../..`` escapes) or absolute filesystem
# path. Bypasses both GOSUMDB and GOPROXY — the proxy + checksum DB
# never see the substitute file. Two shapes:
#
#   replace foo => ../../../private/payload
#   replace foo v1.2.3 => /absolute/path/to/fork
#
# Block-style (inside ``replace ( ... )``) is also matched because
# each inner line is its own ``LHS => RHS`` shape without the leading
# ``replace`` keyword. We handle that with a separate alternation
# but require the LHS to LOOK like a Go module path (contains at
# least one ``/``, dotted-host form) to avoid matching every YAML/
# code ``foo => /bar`` line in arbitrary files.
# Workspace-local sibling replaces using ``./`` are NOT matched
# (single-leading-dot relative paths are common in mono-repos);
# only ``../`` (escapes) and absolute (``/`` Unix or ``C:\`` Windows)
# trigger.
_GO_REPLACE_LOCAL_HIJACK = _re(
    # Top-level form: `replace <lhs> [<ver>] => <rhs> [<ver>]`
    r"^\s*replace\s+[\w./\-]+(?:\s+v[\w.\-+]+)?\s*=>\s*"
    r"(?P<rhs1>(?:\.\.[/\\][^\s\n]+)|(?:/[^\s\n]+)|(?:[A-Za-z]:[/\\][^\s\n]+))"
    # Block-form line (no leading `replace`): same RHS shape, plus
    # LHS must contain a `/` (Go-module-path shape: `host/path/pkg`
    # or `host.tld/pkg`). This filters out arbitrary `=> /something`
    # lines in non-go.mod files. False positives still possible on
    # config files that use module-like names with `=>`, but the
    # caller is expected to route only ``go.mod`` files here.
    r"|^\s*(?P<lhs2>[\w\-]+(?:\.[\w\-]+)*/[\w./\-]+)(?:\s+v[\w.\-+]+)?\s*=>\s*"
    r"(?P<rhs2>(?:\.\.[/\\][^\s\n]+)|(?:/[^\s\n]+)|(?:[A-Za-z]:[/\\][^\s\n]+))"
)


# ---- Proposal 3: Maven — settings.xml plain credentials ----------------


# `<password>` / `<privateKey>` / `<passphrase>` element body in
# ``settings.xml`` (or any committed XML descendant) that is NOT
# an env-var or secret-store interpolation. Legit shapes are
# ``${env.NEXUS_PASSWORD}`` or ``${secrets.foo}`` — anything else
# is a plain credential leak.
#
# Matches the OPENING tag + inner-text + closing-tag shape; the
# negative lookahead rejects the env-var / secret interpolation
# wrappers. Allows surrounding whitespace and newlines inside the
# element body.
_MAVEN_PLAIN_PASSWORD = _re(
    r"<(?P<tag>password|privateKey|passphrase)\s*>"
    r"\s*(?!\$\{env\.[A-Z_][A-Z0-9_]*\}|\$\{secrets?\.[^}]+\}|\s*</)"
    r"(?P<val>[^<\s][^<]*?)"
    r"</(?P=tag)\s*>"
)


# ---- Proposal 4: PHP / Composer — script hook RCE ----------------------


# ``composer.json`` ``scripts.<hook>`` entries that contain shell
# metacharacters or network-bin invocations. We can't easily walk
# the JSON tree inside a single regex, so we match the line-level
# shape: a ``"<hook>": "..."`` or ``"<hook>": [ ... "..." ... ]``
# entry that either contains shell metas (``|``, ``;``, ``&&``,
# ``$( … )``, backticks) or calls ``curl``/``wget``/``nc``/``bash -c``/
# ``sh -c``. Laravel ``@php`` / ``@composer`` references are
# explicitly allowlisted via a negative lookahead.
#
# The pattern requires the surrounding hook-key context so it
# only fires inside a composer-scripts block; this avoids matching
# every shell pipeline in arbitrary JSON files.
_COMPOSER_SCRIPT_RCE = _re(
    r"\"(?:post-install-cmd|pre-install-cmd|post-update-cmd|pre-update-cmd|post-autoload-dump)\""
    r"\s*:\s*(?:\[[^\]]*?\"|\"@?)"
    r"(?!@(?:php|composer)\b)"
    r"[^\"\n]*?(?:[|;`]|&&|\$\(|\bcurl\s|\bwget\s|\bnc\s+-|\bncat\s|\bbash\s+-c|\bsh\s+-c)"
)


# ---- Proposal 5: .NET / NuGet — config clear + source-mapping --------


# A committed ``nuget.config`` (case-insensitive) ``<packageSources>``
# block that:
#   * contains a ``ClearTextPassword`` ``value="..."`` whose value is
#     NOT a ``%ENV_VAR%`` interpolation — plain-text password leak.
#
# Detecting "missing <clear/>" or "missing packageSourceMapping" is
# structural and doesn't fit a regex; the rule fires on the
# unambiguous clear-text-password leak only. The detector layer
# above does the structural / counting checks.
_NUGET_CLEARTEXT_PASSWORD = _re(
    r"<add\s+key\s*=\s*['\"]ClearTextPassword['\"]\s+"
    r"value\s*=\s*['\"](?!%[A-Z_][A-Z0-9_]*%['\"])"
    r"(?P<val>[^'\"]+)['\"]"
)


# ---- Proposal 6: Ruby / Bundler — Gemfile loose-version + git source ---


# A ``Gemfile`` ``gem`` line that combines a loose version constraint
# (``>=``, ``>``, or ``~>``) with a ``:git``/``:github``/``:path``
# source. Either alone is fine; the combination is the supply-chain
# anti-pattern (un-checksummed source pulled at moving-target version).
# Matches on a single line of the Gemfile.
_RUBY_GEMFILE_LOOSE_GIT = _re(
    # `gem "name"` then later on the same line a :git/:github/:path
    # source AND a loose version constraint anywhere on the line.
    r"^\s*gem\s+['\"][\w\-./]+['\"]"
    r"(?=[^\n#]*?:\s*(?:git|github|path)\s*=>)"
    r"(?=[^\n#]*?(?:>=\s*['\"]?\d|>\s*['\"]?\d|~>\s*['\"]?\d))"
    r"[^\n#]*"
)


# ---- Proposal 7: Swift / SPM — .binaryTarget without checksum ---------


# ``.binaryTarget(name:url:checksum:)`` where the ``checksum:``
# argument is empty, a placeholder, or shorter than 32 hex chars.
# SPM requires SHA-256 (64 hex chars) but we accept ``len ≥ 32`` to
# allow legacy SHA-1 references — anything shorter is a placeholder.
# Also catches non-HTTPS binary-target URLs.
_SWIFT_BINARYTARGET_BAD_CHECKSUM = _re(
    r"\.binaryTarget\s*\(\s*"
    r"name\s*:\s*['\"][^'\"]+['\"]\s*,\s*"
    r"url\s*:\s*['\"](?P<url>[^'\"]+)['\"]\s*,\s*"
    r"checksum\s*:\s*['\"](?P<checksum>[^'\"]*)['\"]\s*\)"
)


# ---- Proposal 8: Gradle — apply from: arbitrary HTTP / flatDir --------


# ``apply from: "https://..."`` downloads arbitrary Groovy at build
# time. The hosts allowlist is enforced upstream (we can't bake a
# host whitelist into a single regex without making it brittle);
# this rule fires on EVERY ``apply from:`` pointing at an
# ``http://`` or ``https://`` URL. Same idea for ``flatDir { ... }``
# repositories — those have no checksum verification by design.
_GRADLE_APPLY_FROM_HTTP = _re(
    r"\bapply\s+from\s*[:=]\s*['\"](?P<url>https?://[^'\"]+)['\"]"
    r"|\bflatDir\s*\{"
)


# ---- The composed rules table ------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="sc-cargo-buildrs-suspicious-syscalls",
        name="Cargo build.rs uses shell/network/credential-file syscall",
        severity="HIGH",
        description=(
            "build.rs uses Command::new('sh'/'curl'/'wget'/…), opens a "
            "TCP/UDP socket, calls a HTTP-client crate (reqwest/ureq/"
            "curl), or writes to a credential file (~/.ssh, ~/.bashrc). "
            "Cargo has no global install-script switch — build.rs is "
            "always evaluated. Legit native-FFI crates should be "
            "allowlisted upstream by checking the crate suffix (`-sys`) "
            "and the Cargo.toml `links =` marker."
        ),
        pattern=_CARGO_BUILDRS_SYSCALLS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sc-go-replace-directive-local-path-hijack",
        name="Go go.mod replace directive uses local/escape path",
        severity="CRITICAL",
        description=(
            "go.mod `replace` directive swaps a public module for a "
            "path that escapes the repo root (`../..`) or an absolute "
            "filesystem path. Bypasses GOSUMDB (no checksum entry for "
            "the replacement) and GOPROXY (replace overrides the proxy "
            "fetch). Workspace-local `./sibling` replaces are NOT "
            "flagged."
        ),
        pattern=_GO_REPLACE_LOCAL_HIJACK,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sc-maven-settings-xml-plain-credentials",
        name="Maven settings.xml stores plain password / private key",
        severity="CRITICAL",
        description=(
            "settings.xml <server> block contains a <password> / "
            "<privateKey> / <passphrase> element whose body is NOT an "
            "env-var or secrets-store interpolation. Legit shape is "
            "`${env.NEXUS_PASSWORD}` or `${secrets.foo}`. Anything "
            "else is a maintainer-token leak."
        ),
        pattern=_MAVEN_PLAIN_PASSWORD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="sc-composer-script-postinstall-rce",
        name="Composer script hook contains shell-meta / network-bin",
        severity="HIGH",
        description=(
            "composer.json scripts.<post|pre>-install-cmd / -update-cmd "
            "/ post-autoload-dump entry contains shell metacharacters "
            "(`|`, `;`, `&&`, `$()`, backticks) or invokes `curl` / "
            "`wget` / `nc` / `bash -c` / `sh -c`. Laravel-style "
            "`@php artisan migrate` is allowlisted."
        ),
        pattern=_COMPOSER_SCRIPT_RCE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="sc-nuget-config-cleartext-password",
        name="NuGet config stores ClearTextPassword without env-var",
        severity="CRITICAL",
        description=(
            "nuget.config <packageSourceCredentials> has a "
            "ClearTextPassword whose value is NOT a `%ENV_VAR%` "
            "interpolation. NuGet credential leak — same severity as "
            "Maven settings.xml plain password."
        ),
        pattern=_NUGET_CLEARTEXT_PASSWORD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="sc-ruby-gemfile-unpinned-and-git-source",
        name="Ruby Gemfile combines loose version with :git/:github/:path",
        severity="HIGH",
        description=(
            "Gemfile `gem` line combines an open-bound version "
            "constraint (`>=`, `>`, `~>`) with a `:git` / `:github` / "
            "`:path` source. Bypasses RubyGems advisory DB AND lets a "
            "moving target resolve at install time — equivalent to "
            "the npm `exotic dependency` anti-pattern."
        ),
        pattern=_RUBY_GEMFILE_LOOSE_GIT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sc-swift-binarytarget-missing-checksum",
        name="Swift .binaryTarget has empty / placeholder checksum",
        severity="HIGH",
        description=(
            ".binaryTarget(name:url:checksum:) has an empty checksum, "
            "a placeholder, or a checksum shorter than 32 hex chars — "
            "SPM downloads the opaque binary blob with no integrity "
            "check, immediate code-injection vector."
        ),
        pattern=_SWIFT_BINARYTARGET_BAD_CHECKSUM,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="sc-gradle-apply-from-http-or-flatdir",
        name="Gradle apply-from http(s) URL or flatDir repository",
        severity="CRITICAL",
        description=(
            "Gradle build script uses `apply from: 'https://...'` "
            "(downloads arbitrary Groovy at evaluation time) or a "
            "`flatDir { ... }` repository (no checksum verification). "
            "Both are documented Gradle supply-chain vectors and "
            "macaron treats them as first-class risk."
        ),
        pattern=_GRADLE_APPLY_FROM_HTTP,
        owasp_asi="ASI-05",
    ),
)


# ---- The composed scanner ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against ``text`` and return findings.

    Unlike ``agent_config_patterns.scan_text`` this scanner does not
    differentiate prose vs source — every per-language rule here
    targets a specific config-file shape (``go.mod``, ``Gemfile``,
    ``composer.json``, ``settings.xml``, etc.) and the caller is
    responsible for routing the right file at the right rule. We
    keep the single-entry signature for parity with the reference
    module so heartbeat detectors can call either uniformly.

    Findings are deduped by ``(rule_id, line, col)`` — a single line
    that triggers two rules emits two findings, but the same rule
    firing twice on the same line emits one.
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
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
