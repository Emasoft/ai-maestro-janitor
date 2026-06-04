"""Bazel / Buck2 / Pants build-system security patterns.

Wave-36 distillation round 22, angle: remote-cache poisoning and
custom-rules RCE.

Catalogue of 10 build-system-specific anti-patterns distilled in
`reports/distill-round-22/bazel-buck-cache.md`. Targets WORKSPACE,
MODULE.bazel, BUILD / BUILD.bazel, .bazelrc, pants.toml, .buckconfig,
and BXL script surfaces.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic `http://` URL in source — `network_patterns.py`.
  * Supply-chain poisoning of PyPI packages — `pypi_patterns.py`.
  * CI environment-variable leaks — `ci_credential_patterns.py`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * bzl-http-archive-no-sha256          (CRITICAL)
  * bzl-git-repo-http-remote            (CRITICAL)
  * bzl-git-repo-branch-pin             (CRITICAL)
  * bzl-remote-upload-local-results     (CRITICAL)
  * bzl-genrule-cmd-srcs-unquoted       (HIGH)
  * bzl-genrule-external-tools          (HIGH)
  * bzl-experimental-remote-downloader  (CRITICAL)
  * bzl-pants-anonymous-telemetry       (MEDIUM)
  * bzl-pip-parse-http-requirements     (HIGH)
  * bzl-disk-cache-world-writable       (HIGH)
  * bzl-buck2-run-local                 (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret / integrity leak (cache poisoning, unverified fetch)
  ASI-05 — Supply-chain / build-time RCE (genrule injection, external tools,
            BXL run_local)
  ASI-04 — Information leak / reconnaissance (telemetry exfil)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- bzl-http-archive-no-sha256 -----------------------------------------


# Detect http_archive() calls that use a plain http:// URL — the server can
# be MITM'd without any integrity check stopping the poisoned archive.
_HTTP_ARCHIVE_HTTP_URL = _re(
    r"http_archive\s*\([^)]*?url\s*=\s*\"http://"
)


# ---- bzl-git-repo-http-remote -------------------------------------------


# git_repository with a plain http:// remote — transport is unencrypted and
# the tip-of-tree ref is mutable.
_GIT_REPO_HTTP_REMOTE = _re(
    r"git_repository\s*\([^)]*?remote\s*=\s*\"http://"
)


# ---- bzl-git-repo-branch-pin --------------------------------------------


# git_repository that pins to a branch name rather than an immutable commit
# SHA — the next push to that branch silently changes what is fetched.
_GIT_REPO_BRANCH_PIN = _re(
    r"git_repository\s*\([^)]*?branch\s*=\s*\"[^\"]*\""
)


# ---- bzl-remote-upload-local-results ------------------------------------


# --remote_upload_local_results=true lets a compromised developer machine
# poison the shared remote cache consumed by other machines and CI runners.
_REMOTE_UPLOAD_LOCAL_RESULTS = _re(
    r"--remote_upload_local_results\s*=\s*true"
)


# ---- bzl-genrule-cmd-srcs-unquoted --------------------------------------


# genrule cmd embedding $(SRCS) or $(location ...) without quoting — a
# filename containing shell metacharacters becomes an RCE vector.
_GENRULE_CMD_SRCS = _re(
    r"genrule\s*\([^)]*cmd\s*=\s*\"[^\"]*\$\((?:SRCS|location\s+[^)]+)\)"
)


# ---- bzl-genrule-external-tools -----------------------------------------


# tools = ["@external_repo//:bin"] — the binary is fetched from and built
# inside an external repo at build time; without an integrity pin this is
# a build-time RCE vector.
_GENRULE_EXTERNAL_TOOLS = _re(
    r"tools\s*=\s*\[[^\]]*\"@[A-Za-z0-9_-]+//:"
)


# ---- bzl-experimental-remote-downloader ---------------------------------


# Routes all http_archive fetches through an external proxy; an attacker
# controlling the endpoint can swap any dependency archive transparently.
_EXPERIMENTAL_REMOTE_DOWNLOADER = _re(
    r"--experimental_remote_downloader\s*=\s*grpcs?://(?!localhost|127\.0\.0\.1)"
)


# ---- bzl-pants-anonymous-telemetry --------------------------------------


# Pants sends build metadata to a remote endpoint; a supply-chain compromise
# of that endpoint turns telemetry into an exfil / fingerprinting channel.
_PANTS_ANONYMOUS_TELEMETRY = _re(
    r"\[anonymous-telemetry\][^\[]*enabled\s*=\s*true"
)


# ---- bzl-pip-parse-http-requirements ------------------------------------


# pip_parse / pip_install fetching a requirements lockfile over plain HTTP —
# the lockfile can be substituted en route, pointing builds at malicious pkgs.
_PIP_HTTP_REQUIREMENTS = _re(
    r"pip_(?:parse|install)\s*\([^)]*requirements(?:_lock)?\s*=\s*\"http://"
)


# ---- bzl-disk-cache-world-writable --------------------------------------


# --disk_cache pointing to /tmp, /mnt, or ~/ — any process with write access
# to that path can replace cached artifacts consumed by the next build.
_DISK_CACHE_WORLD_WRITABLE = _re(
    r"--disk_cache\s*=\s*(?:/tmp/|/mnt/|~[/\\])"
)


# ---- bzl-buck2-run-local ------------------------------------------------


# Buck2 BXL ctx.actions.run_local() bypasses the remote-execution sandbox
# and runs directly on the host at graph-evaluation time.
_BUCK2_RUN_LOCAL = _re(
    r"run_local\s*\("
)


# ---- Rule table ---------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="bzl-http-archive-no-sha256",
        name="http_archive with plain HTTP URL (no integrity)",
        severity="CRITICAL",
        description=(
            "http_archive() fetches over plain HTTP, enabling MITM or CDN "
            "substitution of the archive with no integrity check. "
            "Use HTTPS and add sha256 = \"...\"."
        ),
        pattern=_HTTP_ARCHIVE_HTTP_URL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bzl-git-repo-http-remote",
        name="git_repository over plain HTTP remote",
        severity="CRITICAL",
        description=(
            "git_repository() clones over plain HTTP, exposing the fetch to "
            "MITM and DNS hijacking. Switch to an https:// remote."
        ),
        pattern=_GIT_REPO_HTTP_REMOTE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bzl-git-repo-branch-pin",
        name="git_repository pinned to mutable branch",
        severity="CRITICAL",
        description=(
            "git_repository() pinned to a branch name is mutable — any new "
            "push to that branch changes the fetched commit with no integrity "
            "guarantee. Pin to a full commit SHA instead."
        ),
        pattern=_GIT_REPO_BRANCH_PIN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bzl-remote-upload-local-results",
        name="--remote_upload_local_results=true enables cache poisoning",
        severity="CRITICAL",
        description=(
            "--remote_upload_local_results=true allows a compromised developer "
            "machine to upload poisoned build artifacts to the shared remote "
            "cache. Enable only on trusted, controlled CI machines."
        ),
        pattern=_REMOTE_UPLOAD_LOCAL_RESULTS,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bzl-genrule-cmd-srcs-unquoted",
        name="genrule cmd embeds $(SRCS) or $(location) without quoting",
        severity="HIGH",
        description=(
            "Embedding $(SRCS) or $(location ...) in a genrule cmd without "
            "shell-quoting allows a filename with metacharacters to inject "
            "arbitrary shell commands at build time."
        ),
        pattern=_GENRULE_CMD_SRCS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="bzl-genrule-external-tools",
        name="genrule tools referencing external repository binary",
        severity="HIGH",
        description=(
            "tools = [\"@repo//:bin\"] fetches and potentially builds an "
            "external binary at build time. Without an integrity-pinned "
            "http_archive / commit SHA this is a build-time RCE vector."
        ),
        pattern=_GENRULE_EXTERNAL_TOOLS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="bzl-experimental-remote-downloader",
        name="--experimental_remote_downloader to non-localhost endpoint",
        severity="CRITICAL",
        description=(
            "Routes all http_archive fetches through an external proxy. "
            "An attacker controlling the downloader endpoint can substitute "
            "any dependency archive without altering WORKSPACE checksums."
        ),
        pattern=_EXPERIMENTAL_REMOTE_DOWNLOADER,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bzl-pants-anonymous-telemetry",
        name="Pants anonymous telemetry enabled",
        severity="MEDIUM",
        description=(
            "Pants sends build metadata to a remote telemetry endpoint on "
            "every invocation. A supply-chain compromise of that endpoint "
            "turns telemetry into an exfiltration or fingerprinting channel."
        ),
        pattern=_PANTS_ANONYMOUS_TELEMETRY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="bzl-pip-parse-http-requirements",
        name="pip_parse / pip_install fetching requirements over plain HTTP",
        severity="HIGH",
        description=(
            "Fetching a requirements lockfile over plain HTTP allows an "
            "attacker to substitute the lockfile en route, redirecting builds "
            "to malicious packages and bypassing local hash verification."
        ),
        pattern=_PIP_HTTP_REQUIREMENTS,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bzl-disk-cache-world-writable",
        name="--disk_cache pointing to world-writable or shared path",
        severity="HIGH",
        description=(
            "--disk_cache set to /tmp/, /mnt/, or ~/ gives any process with "
            "write access to that path the ability to replace cached build "
            "artifacts consumed on the next build."
        ),
        pattern=_DISK_CACHE_WORLD_WRITABLE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="bzl-buck2-run-local",
        name="Buck2 BXL run_local() bypasses remote-execution sandbox",
        severity="HIGH",
        description=(
            "ctx.actions.run_local() in a BXL script executes directly on "
            "the host at graph-evaluation time, before any sandbox is applied. "
            "Attacker-controlled BXL scripts or unverified external repos "
            "providing BXL scripts gain unrestricted host access."
        ),
        pattern=_BUCK2_RUN_LOCAL,
        owasp_asi="ASI-05",
    ),
)


# ---- Scanner ------------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* against all RULES and return one Finding per match.

    Lines and columns are 1-based. Matched text is capped at 200 characters
    to avoid flooding callers with multi-kilobyte blobs. Never raises on
    benign or malformed input.
    """
    findings: list[Finding] = []
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            start = m.start()
            # Derive 1-based line/column from the match start offset.
            line_no = text.count("\n", 0, start) + 1
            # Column: characters since the last newline before start.
            last_nl = text.rfind("\n", 0, start)
            col_no = start - last_nl  # 1-based because rfind returns -1 when absent
            matched = m.group(0)[:200]
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line_no,
                    column=col_no,
                    matched_text=matched,
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )
    # Stable order: line, then column, then rule_id.
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
