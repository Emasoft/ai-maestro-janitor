"""Credential / token-lifecycle attack patterns (Wave-impl deep-dive batch M).

A targeted pattern catalogue for credential / OAuth-token / refresh-token
LIFECYCLE attacks. Patterns are convergent across the public corpus
surveyed in
`reports/study-github-monitoring-deep2/20260527_184319+0200-distill2-c-credential-lifecycle.md`:

  * claude-code-cve-gate (CVE-aware install-time gate)
  * sealed-env (THREAT_MODEL.md T1-T13 + docs/09-lifecycle.md)
  * secret-leak-sentinel (regex detector corpus + CI gating)
  * secretops-sentinel (rotation workflow + per-vendor rotation
    checklists)
  * supply-chain-defense (install-time cross-ecosystem threat matrix +
    Shai-Hulud post-mortems)

What's NOT here (already shipped elsewhere — do not duplicate):

  * `hardcoded-secrets` / `sensitive-secret-ref` — catch the literal
    token shape in a source file; THIS module catches the
    *lifecycle behaviour* around the token (mint, revoke, refresh,
    write-to-target).
  * `missing-persist-credentials`             — checkout-with-creds
                                                  pollution; this module
                                                  covers post-checkout
                                                  mint/revoke flow.
  * `/proc/PID/mem credential extraction`     — runtime memory read;
                                                  this module covers
                                                  at-rest + on-wire
                                                  behaviours.
  * `secrets-inherit`                         — inherit-everywhere;
                                                  this module covers
                                                  scoped-mint + cross-job
                                                  survival.
  * `github-app-skip-token-revoke`            — single-action mint-revoke
                                                  pair; this module
                                                  generalises to
                                                  Vault/STS/GCP/Azure.

What IS here (8 net-new lifecycle rules from distill2-c):

  * refresh-token-written-to-disk           (P2, CRITICAL) — refresh
                                              token name landing near
                                              a filesystem write / log
                                              sink.
  * refresh-token-sent-to-non-issuer-url    (P3, CRITICAL) — refresh
                                              token POSTed to host that
                                              does not match the
                                              OAuth issuer recorded in
                                              the same module.
  * oauth-state-param-missing               (P4, HIGH)     — OAuth
                                              authorize URL build with
                                              NO `state=...` parameter
                                              in the 400-char window.
  * oidc-nonce-missing                      (P4, HIGH)     — OIDC
                                              authorize URL (openid in
                                              window) with NO `nonce`.
  * revoke-error-suppressed-shell           (P6, HIGH)     — shell call
                                              `revoke|invalidate|logout`
                                              swallowed by `|| true`
                                              `2>/dev/null` / `&> /dev/null`.
  * revoke-error-suppressed-python          (P6, HIGH)     — Python AST
                                              try-except with bare
                                              except / pass-only handler
                                              wrapping a revoke call.
  * token-format-mismatch-in-secret-write   (P7, MAJOR)    — wrong-
                                              prefix token written into
                                              a target labelled for a
                                              different vendor.
  * npmrc-pypirc-token-injection-from-job-env (P8, CRITICAL) — workflow
                                              `run:` block writes a
                                              `secrets.X` reference into
                                              `~/.npmrc` / `.pypirc` /
                                              `~/.cargo/credentials` /
                                              `~/.docker/config.json` /
                                              `~/.m2/settings.xml`.
  * token-create-without-revoke-pair        (P1, MAJOR)    — workflow
                                              YAML walk: job has at
                                              least one mint step
                                              (Vault / STS / gcloud /
                                              az / tibdex GitHub App)
                                              with no matching revoke
                                              step. Reported via
                                              `find_mint_without_revoke()`.
  * credential-survives-workflow-dispatch-via-artifact (P5, CRITICAL) —
                                              `on: workflow_dispatch`
                                              + secret usage + upload-
                                              artifact with retention
                                              greater than 7 days.
                                              Reported via
                                              `find_dispatch_artifact_survival()`.

Architecture: mirrors `agent_config_patterns.py` /
`mcp_security_patterns.py`. Pure stdlib — re, NamedTuple, optional
PyYAML for the two YAML-walking helpers (graceful degrade if PyYAML
absent). No network, no LLM, no third-party regex engine.

Severity strings: "CRITICAL", "HIGH", "MAJOR", "MINOR" — matches the
janitor sentinel/zizmor + version-bump-class vocabulary. Note that
this module emits MAJOR (not MEDIUM) for medium-confidence findings
to match the `zizmor_patterns_extra.py` convention; MEDIUM remains
the `agent_config_patterns` vocabulary for prose findings.

OWASP-ASI mapping (Agentic Security Initiative):
  ASI-02 = data exfiltration
  ASI-04 = credential / secret access (most lifecycle rules)
  ASI-05 = supply chain (artifact survival)
  ASI-07 = authority hijacking (OAuth state CSRF)
"""

from __future__ import annotations

import ast
import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match. Identical shape to the one in
    `agent_config_patterns.Finding` so heartbeat detectors can render
    either kind uniformly."""

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
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE+DOTALL.

    DOTALL is included because lifecycle rules routinely scan windows
    that include newlines (refresh-token-to-disk, OAuth state in URL
    builder, multi-line `run:` blocks). The simple alternative — leave
    DOTALL off and use `[\\s\\S]` explicitly — produces longer patterns
    with worse error messages.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE | re.DOTALL)


# ---- P2: refresh-token-written-to-disk ----------------------------------


# Refresh-token field-name appearing within 200 characters of a file
# write or logging sink. Refresh tokens have no fixed prefix (they're
# JWT-like or opaque base64) so only the variable name + the sink
# combo gives signal.
#
# Sinks covered:
#   * Python: open(path, "w"|"a") / json.dump / pathlib write_text
#   * Node:   writeFileSync / writeFile / fs.write
#   * Shell:  > / >> / tee
#   * Logging sinks: console.log / logger.info / .debug / .warn
#
# The 200-character window is deliberately tight — refresh-token mention
# at the top of a 5,000-line module with a write call at the bottom is
# not a finding.
_REFRESH_TOKEN_TO_DISK = _re(
    r"refresh[_-]?token"
    r"[^\n]{0,200}?"
    r"(?:"
        r"open\s*\([^)]*?,\s*['\"][wa]"          # python open(path,"w")
        r"|write_text\s*\("                       # pathlib
        r"|writeFileSync\s*\("                    # node sync
        r"|writeFile\s*\("                        # node
        r"|fs\.write\b"
        r"|>>?\s*[~/.$]"                          # shell redir to a path
        r"|tee\s+[~/.$]"
        r"|json\.dump\s*\("
        r"|JSON\.stringify\s*\([^)]*?[fF]ile"
        r"|console\.log\s*\("
        r"|logger\.(?:info|debug|warn|error)\s*\("
    r")"
)
# Reverse shape: the write call appears FIRST, refresh_token follows
# within 200 chars (e.g. `open("token.json", "w") as f: f.write(
# json.dumps({"refresh_token": rt}))` — common pattern).
_REFRESH_TOKEN_TO_DISK_REVERSE = _re(
    r"(?:"
        r"open\s*\([^)]*?,\s*['\"][wa]"
        r"|write_text\s*\("
        r"|writeFileSync\s*\("
        r"|writeFile\s*\("
        r"|fs\.write\b"
        r"|tee\s+[~/.$]"
        r"|json\.dump\s*\("
        r"|JSON\.stringify\s*\("
        r"|console\.log\s*\("
        r"|logger\.(?:info|debug|warn|error)\s*\("
    r")"
    r"[^\n]{0,200}?refresh[_-]?token"
)


# ---- P3: refresh-token-sent-to-non-issuer-url ---------------------------


# Two regexes collaborate at scan time:
#   1. _OAUTH_ISSUER_DECL — find issuer host(s) declared in module
#   2. _REFRESH_TOKEN_POST — find POST whose body mentions refresh_token,
#      capture the target host.
# A finding is emitted when (1) is non-empty and (2)'s host is not in (1).
# Both patterns expose a capture group on the host segment.
_OAUTH_ISSUER_DECL = _re(
    r"(?:TOKEN_URL|TOKEN_ENDPOINT|OAUTH_BASE|ISSUER_URL|AUTH_URL|"
    r"OAUTH_TOKEN_ENDPOINT)\s*[:=]\s*['\"]https?://([^/'\"]+)"
)
_REFRESH_TOKEN_POST = _re(
    r"(?:fetch|requests\.post|axios\.post|axios\(|http\.post|urlopen|"
    r"httpx\.post|httpClient\.post)"
    r"\s*\(\s*['\"]https?://([^/'\"]+)[^)]{0,500}?refresh[_-]?token"
)


# ---- P4: OAuth state / OIDC nonce missing -------------------------------


_AUTH_URL_BUILD = _re(
    r"(?:authorize_url|authorization_url|/oauth/authorize\b|"
    r"/oauth2/v\d/auth\b|/o/oauth2/v\d/auth\b|"
    r"\bauthorize\?[^\s'\")]{0,400}"
    r"|response_type\s*[:=]\s*['\"]?code)"
    r"[^\n]{0,400}"
)
# Used as a positive-presence check on the same 400-char window —
# scan_text() composes them.
_HAS_STATE = _re(r"\bstate\s*[=:]\s*[^&'\"\s]{4,}")
_HAS_NONCE = _re(r"\bnonce\s*[=:]\s*[^&'\"\s]{4,}")
# The dummy emitter regex below is the pattern that LANDS on the
# offending line when scan_text resolves "missing state". The rule
# entry uses this pattern but its actual emit decision is computed by
# the composed scanner — keep this regex broad on intent.
_OAUTH_STATE_MISSING_LOCATOR = _re(
    r"(?:authorize_url|authorization_url|/oauth/authorize|"
    r"/oauth2/v\d/auth)\b[^\n]{0,4}"
)


# ---- P6: revoke-error-suppressed (shell) --------------------------------


# `gh|curl|aws|az|gcloud|vault|kubectl` + revoke-class verb followed by
# error-suppression operator on the SAME line. The 300-char window
# allows for chained options like
# `gh auth token --revoke "$T" 2>/dev/null || true`.
_REVOKE_VERB = (
    r"(?:revoke|delete-token|delete-access-key|delete-access-token"
    r"|logout|expire-session|invalidate|token\s+revoke)"
)
_REVOKE_SUPPRESSED_SHELL = _re(
    r"\b(?:curl|gh|aws|az|gcloud|vault|kubectl|hcp|doctl|oc)\s+[^\n]{0,300}?"
    + _REVOKE_VERB
    + r"[^\n]{0,300}?"
    r"(?:"
        r"\|\|\s*(?:true|:|noop)\b"          # || true
        r"|2>\s*/dev/null"                    # stderr → null
        r"|2>&1\s*\|\s*true"                  # stderr-merged then swallowed
        r"|&>\s*/dev/null"                    # bash combined-redirect
        r"|>\s*/dev/null\s+2>&1"              # both → null
    r")"
)
# Symmetric form: suppression operator appears BEFORE the revoke verb
# (rare in shell but possible with `(<cmd>) || true` shape).
_REVOKE_SUPPRESSED_SHELL_REVERSE = _re(
    r"(?:\|\|\s*(?:true|:|noop)|2>\s*/dev/null|&>\s*/dev/null)"
    r"[^\n]{0,200}?\b(?:curl|gh|aws|az|gcloud|vault|kubectl)\s+[^\n]{0,200}?"
    + _REVOKE_VERB
)


# ---- P7: token-format-mismatch-in-secret-write --------------------------


# Map: regex matching the assignment target → expected prefix set.
# Empty set = no fixed prefix; mismatch detection skipped for that target.
# We deliberately whitelist `${{ secrets.* }}` and `$VAR` substitution
# tokens — those are not literal token values, so cross-provider routing
# (e.g. `NPM_TOKEN=${{ secrets.GITHUB_TOKEN }}`) is allowed by design.
_TARGET_EXPECTATIONS: tuple[tuple[re.Pattern, frozenset[str]], ...] = (
    (re.compile(r"\bGITHUB_TOKEN\b"),
     frozenset({"ghp_", "ghs_", "gho_", "ghu_", "github_pat_"})),
    (re.compile(r"\bGH_TOKEN\b"),
     frozenset({"ghp_", "ghs_", "gho_", "ghu_", "github_pat_"})),
    (re.compile(r"\bAWS_ACCESS_KEY_ID\b"),
     frozenset({"AKIA", "ASIA"})),
    (re.compile(r"\.npmrc\b|/\.npmrc"),
     frozenset({"npm_"})),
    (re.compile(r"\.pypirc\b|/\.pypirc"),
     frozenset({"pypi-"})),
    (re.compile(r"\bSLACK_TOKEN\b|\bSLACK_BOT_TOKEN\b"),
     frozenset({"xoxb-", "xoxp-", "xoxa-", "xoxs-"})),
)
# Pattern catching a generic `<target>=<literal>` or `<target>: <literal>`
# (used both in shell `export X=...`, env-block YAML, and JSON). The
# scanner correlates the captured target with the literal's prefix.
_SECRET_WRITE_LINE = _re(
    r"(?:export\s+|\bENV\s+|\b)(?P<target>[A-Z][A-Z0-9_]*"
    r"|\.npmrc\b|/\.npmrc\b|\.pypirc\b|/\.pypirc\b)\s*[:=]\s*"
    r"['\"](?P<value>[A-Za-z0-9_.\-+/=]{8,256})['\"]"
)


# ---- P8: npmrc-pypirc-token-injection-from-job-env ----------------------


_CRED_FILE_TARGET = (
    r"(?:[~]|\$HOME|\$\{HOME\}|/root|/home/runner)"
    r"/?\.(?:npmrc|pypirc|cargo/credentials|m2/settings\.xml"
    r"|docker/config\.json|gem/credentials|composer/auth\.json)"
)
# 1) Redirect / tee / cat-heredoc into a credential file
_CRED_FILE_WRITE = (
    r"(?:>>?|tee\s+[-A-Za-z]*|cat\s*<<\s*\w+\s*>?)\s*"
    + _CRED_FILE_TARGET
)
# 2) Token source is either ${{ secrets.X }} or an environment expansion
#    ($VAR / ${VAR}). The full regex co-occurs both within a 600-char
#    window of the same `run:` block.
_TOKEN_SOURCE = (
    r"(?:"
        r"\$\{\{\s*secrets\.\w+\s*\}\}"        # workflow secrets context
        r"|\$\{?(?:[A-Z_][A-Z0-9_]*_TOKEN|[A-Z_][A-Z0-9_]*_KEY"
            r"|NPM_TOKEN|PYPI_TOKEN|TWINE_PASSWORD|REGISTRY_TOKEN)\}?"
    r")"
)
_NPMRC_INJECT_FORWARD = _re(
    _TOKEN_SOURCE + r"[^\n]{0,600}?" + _CRED_FILE_WRITE
)
_NPMRC_INJECT_REVERSE = _re(
    _CRED_FILE_WRITE + r"[^\n]{0,600}?" + _TOKEN_SOURCE
)


# ---- The RULES catalogue ------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="refresh-token-written-to-disk",
        name="Refresh token persisted to disk / log sink",
        severity="CRITICAL",
        description=(
            "Refresh-token field name lands within 200 characters of a "
            "filesystem write (open/write_text/writeFileSync), a shell "
            "redirect (>, tee), JSON serialisation, or a log emitter "
            "(console.log, logger.info). Refresh tokens are the long-"
            "lived offline credential — persisting one in plaintext "
            "gives an attacker permanent re-auth ability until manually "
            "revoked at the provider. Disclosed in sealed-env 09-"
            "lifecycle (phase-3 plaintext-to-disk warning)."
        ),
        pattern=_REFRESH_TOKEN_TO_DISK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="refresh-token-written-to-disk-reverse",
        name="Refresh token persisted to disk (write-call-first form)",
        severity="CRITICAL",
        description=(
            "Sink-then-name variant of refresh-token-written-to-disk — "
            "catches `open('token.json','w').write(json.dumps({'refresh"
            "_token': rt}))` where the write call appears textually "
            "before the refresh-token field name. Same CRITICAL "
            "rationale as the forward shape."
        ),
        pattern=_REFRESH_TOKEN_TO_DISK_REVERSE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="refresh-token-sent-to-non-issuer-url",
        name="Refresh token POSTed to host outside the OAuth issuer set",
        severity="CRITICAL",
        description=(
            "Module declares an OAuth issuer constant (TOKEN_URL / "
            "ISSUER_URL / OAUTH_BASE / AUTH_URL) AND a POST elsewhere "
            "in the same module sends a refresh_token body to a "
            "DIFFERENT host. Classic refresh-token-leak attack shape "
            "(malicious npm package intercepts the SDK refresh flow "
            "and routes the token to `auth.legit-looking.com` instead "
            "of `oauth2.googleapis.com`). Disclosed in claude-code-cve-"
            "gate red-team narrative."
        ),
        # The pattern matches the POST locator; the scanner applies the
        # host-mismatch test in find_refresh_token_exfil(). Listed here
        # so heartbeat detectors that iterate RULES still surface the
        # rule existence even if the YAML scanner isn't reached.
        pattern=_REFRESH_TOKEN_POST,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="oauth-state-param-missing",
        name="OAuth authorize URL build missing `state` parameter",
        severity="HIGH",
        description=(
            "An authorization-code URL is constructed (authorize_url / "
            "/oauth/authorize / response_type=code) but the surrounding "
            "400-char window contains no `state=...` value. Bypassing "
            "state means an attacker can race a victim into an "
            "account-fixation / login-CSRF flow. OAuth 2.1 RFC normative "
            "MUST. Disclosed in supply-chain-defense cross-ecosystem "
            "doc as an OAuth handshake hygiene gap."
        ),
        pattern=_OAUTH_STATE_MISSING_LOCATOR,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="oidc-nonce-missing",
        name="OIDC authorize URL build missing `nonce` parameter",
        severity="HIGH",
        description=(
            "An authorize URL with `openid` scope in the surrounding "
            "window contains no `nonce=...` — OIDC replay-protection "
            "MUST. Listed alongside oauth-state-param-missing because "
            "OIDC clients almost always need both."
        ),
        pattern=_OAUTH_STATE_MISSING_LOCATOR,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="revoke-error-suppressed-shell",
        name="Shell revoke / invalidate call swallowed by error suppressor",
        severity="HIGH",
        description=(
            "A `curl|gh|aws|az|gcloud|vault|kubectl` revoke / invalidate "
            "/ logout call is wrapped in `|| true` / `2>/dev/null` / "
            "`&> /dev/null`. Hidden-revoke-evasion shape: the operator "
            "thinks the credential is dead, but the swallowed exit "
            "code masks a provider 5xx and the credential survives. "
            "Disclosed in secretops-sentinel rotation workflow."
        ),
        pattern=_REVOKE_SUPPRESSED_SHELL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="revoke-error-suppressed-shell-reverse",
        name="Shell suppression before revoke (chain form)",
        severity="HIGH",
        description=(
            "Reverse-form companion to revoke-error-suppressed-shell — "
            "catches `(some_op) || true; gh revoke …` shapes where the "
            "suppressor textually precedes the revoke command on the "
            "same line / chain. Same HIGH rationale."
        ),
        pattern=_REVOKE_SUPPRESSED_SHELL_REVERSE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="npmrc-pypirc-token-injection-from-job-env",
        name="Job env / secret written into ~/.npmrc / .pypirc / credentials file",
        severity="CRITICAL",
        description=(
            "A workflow `run:` block (or Dockerfile RUN, or shell "
            "script) writes a `${{ secrets.X }}` reference or an "
            "uppercase `_TOKEN` / `_KEY` environment variable into a "
            "credentials file that outlives the job (~/.npmrc, "
            "~/.pypirc, ~/.cargo/credentials, ~/.docker/config.json, "
            "~/.m2/settings.xml, ~/.gem/credentials). Shai-Hulud primary "
            "persistence mechanism: the file remains on the cached "
            "runner volume and bleeds the secret into every subsequent "
            "matrix re-use."
        ),
        pattern=_NPMRC_INJECT_FORWARD,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="npmrc-pypirc-token-injection-from-job-env-reverse",
        name="Credentials file write followed by env token reference (chain form)",
        severity="CRITICAL",
        description=(
            "Reverse-form companion that catches `cat <<EOF >~/.npmrc … "
            "//registry.npmjs.org/:_authToken=${NPM_TOKEN} … EOF` "
            "where the credential-file redirect appears textually "
            "before the secret/env reference."
        ),
        pattern=_NPMRC_INJECT_REVERSE,
        owasp_asi="ASI-04",
    ),
)


# ---- Composed scanner ---------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).
    Mirrors `agent_config_patterns._line_col` so callers get identical
    coordinate semantics across modules."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _emit(
    rule_id: str,
    text: str,
    offset: int,
    matched: str,
    severity: str,
    description: str,
    owasp_asi: str,
) -> Finding:
    """Build a Finding for a single match, truncating long matches."""
    line, col = _line_col(text, offset)
    if len(matched) > 200:
        matched = matched[:200] + "…"
    return Finding(
        rule_id=rule_id,
        line=line,
        column=col,
        matched_text=matched,
        severity=severity,
        description=description,
        owasp_asi=owasp_asi,
    )


def find_refresh_token_exfil(text: str) -> list[Finding]:
    """Detect refresh_token POSTed to a host that doesn't match any
    OAuth issuer declared in `text`.

    Returns Findings for rule `refresh-token-sent-to-non-issuer-url`.
    Conservative — only emits when the module declares at least one
    issuer, and the captured POST host is not in that set."""
    if not text:
        return []
    issuers = {m.group(1).lower() for m in _OAUTH_ISSUER_DECL.finditer(text)}
    if not issuers:
        return []  # no baseline → cannot decide mismatch deterministically
    rule = next(r for r in RULES if r.id == "refresh-token-sent-to-non-issuer-url")
    findings: list[Finding] = []
    for m in _REFRESH_TOKEN_POST.finditer(text):
        host = m.group(1).lower()
        if host in issuers:
            continue
        findings.append(_emit(
            rule.id, text, m.start(), m.group(0),
            rule.severity, rule.description, rule.owasp_asi,
        ))
    return findings


def find_oauth_state_missing(text: str) -> list[Finding]:
    """Detect authorize URL builds that lack `state` (and OIDC builds
    that lack `nonce`).

    Returns Findings tagged `oauth-state-param-missing` or
    `oidc-nonce-missing` depending on which presence check fails.
    Conservative — only emits when the 400-character window AFTER the
    locator does not contain the expected parameter at all."""
    if not text:
        return []
    state_rule = next(r for r in RULES if r.id == "oauth-state-param-missing")
    nonce_rule = next(r for r in RULES if r.id == "oidc-nonce-missing")
    findings: list[Finding] = []
    for m in _AUTH_URL_BUILD.finditer(text):
        window = text[m.start():m.start() + 800]
        is_oidc = "openid" in window.lower()
        if not _HAS_STATE.search(window):
            findings.append(_emit(
                state_rule.id, text, m.start(),
                window.split("\n", 1)[0][:200],
                state_rule.severity, state_rule.description,
                state_rule.owasp_asi,
            ))
        if is_oidc and not _HAS_NONCE.search(window):
            findings.append(_emit(
                nonce_rule.id, text, m.start(),
                window.split("\n", 1)[0][:200],
                nonce_rule.severity, nonce_rule.description,
                nonce_rule.owasp_asi,
            ))
    return findings


def find_token_format_mismatch(text: str) -> list[Finding]:
    """Detect tokens written into a target labelled for a different
    vendor (e.g. `AKIA...` literal landing in `GITHUB_TOKEN=...`).

    Returns Findings tagged `token-format-mismatch-in-secret-write`.
    Skips any value that is a workflow expression (`${{ … }}`) or a
    shell substitution (`$VAR` / `${VAR}`) — those are not literal
    secrets and cross-provider routing through them is legitimate."""
    if not text:
        return []
    findings: list[Finding] = []
    for m in _SECRET_WRITE_LINE.finditer(text):
        value = m.group("value")
        target_text = m.group("target")
        # Skip substitutions and short noise values
        if value.startswith("$") or "${{" in value or len(value) < 12:
            continue
        for target_pat, expected_prefixes in _TARGET_EXPECTATIONS:
            if not target_pat.search(target_text):
                continue
            if not expected_prefixes:
                continue  # vendor has no fixed prefix → skip
            if any(value.startswith(p) for p in expected_prefixes):
                continue  # prefix matches → benign
            findings.append(Finding(
                rule_id="token-format-mismatch-in-secret-write",
                line=_line_col(text, m.start())[0],
                column=_line_col(text, m.start())[1],
                matched_text=(m.group(0)[:200] + "…") if len(m.group(0)) > 200 else m.group(0),
                severity="MAJOR",
                description=(
                    "Literal token value written into a destination "
                    f"labelled `{target_text}` does not start with any "
                    f"expected vendor prefix ({sorted(expected_prefixes)}) "
                    "— either operator confusion or deliberate "
                    "mis-labelling to mask exfil destination. "
                    "Disclosed in claude-code-cve-gate."
                ),
                owasp_asi="ASI-04",
            ))
    return findings


# ---- Python-AST revoke-error-suppression detector -----------------------


_REVOKE_NAMES = re.compile(
    r"^(?:revoke|invalidate|delete_token|delete_access_key|logout|"
    r"expire_session|expire_token|destroy_session)$",
    re.IGNORECASE,
)


def _call_name(node: ast.AST) -> str | None:
    """Return the rightmost name in a call expression (e.g.
    `session.revoke()` → "revoke") or None for unsupported shapes."""
    if not isinstance(node, ast.Call):
        return None
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return None


def _is_silent_handler(handler: ast.ExceptHandler) -> bool:
    """A handler is 'silent' if it's a bare `except:` OR its body is a
    single `pass` / `...` / `continue`. Anything more sophisticated
    (logging, re-raise, alternative recovery) is NOT considered silent."""
    if handler.type is None:
        return True  # bare except
    if len(handler.body) != 1:
        return False
    stmt = handler.body[0]
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        # `...` literal
        return stmt.value.value is Ellipsis
    if isinstance(stmt, ast.Continue):
        return True
    return False


def find_revoke_suppression_python(text: str) -> list[Finding]:
    """Detect Python try/except wrapping a revoke-class call where the
    handler swallows the exception silently.

    Returns Findings tagged `revoke-error-suppressed-python`. Skips
    files that don't parse as Python — silently returns []."""
    if not text:
        return []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    findings: list[Finding] = []
    seen: set[tuple[int, int]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if not any(_is_silent_handler(h) for h in node.handlers):
            continue
        for sub in ast.walk(node):
            fn = _call_name(sub)
            if not fn or not _REVOKE_NAMES.search(fn):
                continue
            # ast.AST nodes always carry .lineno / .col_offset
            line = getattr(sub, "lineno", 1)
            col = getattr(sub, "col_offset", 0) + 1
            key = (line, col)
            if key in seen:
                continue
            seen.add(key)
            findings.append(Finding(
                rule_id="revoke-error-suppressed-python",
                line=line,
                column=col,
                matched_text=f"try: ... {fn}(...) except: pass",
                severity="HIGH",
                description=(
                    "Python try/except swallows the result of a revoke-"
                    f"class call (`{fn}`) — hidden-revoke-evasion shape. "
                    "Use explicit logging + non-silent re-raise instead."
                ),
                owasp_asi="ASI-04",
            ))
    return findings


# ---- YAML walkers (mint-without-revoke, dispatch+artifact survival) ----


_MINT_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"(?:tibdex/github-app-token|actions/create-github-app-token"
                r"|peter-evans/create-pull-request)@"), "github-app"),
    (re.compile(r"\bvault\s+(?:write|token\s+create)\b"), "vault"),
    (re.compile(r"\baws\s+sts\s+(?:assume-role|get-session-token|"
                r"get-federation-token)\b"), "sts"),
    (re.compile(r"\bgcloud\s+auth\s+print-(?:access|identity)-token\b"), "gcp"),
    (re.compile(r"\baz\s+(?:account\s+get-access-token|ad\s+sp\s+credential)\b"), "azure"),
)
_REVOKE_INDICATORS = re.compile(
    r"(?:revoke|delete-access-token|/installation/token|"
    r"vault\s+token\s+revoke|aws\s+iam\s+(?:delete-access-key|"
    r"update-access-key.*--status\s+Inactive))",
    re.IGNORECASE,
)


def find_mint_without_revoke(workflow: dict) -> list[Finding]:
    """Walk a parsed GitHub Actions workflow (YAML → dict) and report
    each job that mints a privileged token via Vault/STS/gcloud/az/
    tibdex-GitHub-App and has NO matching revoke step.

    Generalises the shipped `github-app-skip-token-revoke` rule beyond
    the single tibdex-action shape to cover Vault / STS / GCP / Azure
    mint sources.

    Returns Findings tagged `token-create-without-revoke-pair`. The
    caller is expected to pre-parse the YAML (PyYAML / ruamel) — this
    function takes the resulting dict so callers can use whichever
    loader they already depend on."""
    findings: list[Finding] = []
    if not isinstance(workflow, dict):
        return findings
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return findings
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        minted: list[tuple[int, str]] = []
        revoke_seen = False
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            blob = (str(step.get("uses", "")) + "\n"
                    + str(step.get("run", "")))
            for pat, kind in _MINT_PATTERNS:
                if pat.search(blob):
                    minted.append((idx, kind))
            if _REVOKE_INDICATORS.search(blob):
                revoke_seen = True
        if minted and not revoke_seen:
            for idx, kind in minted:
                findings.append(Finding(
                    rule_id="token-create-without-revoke-pair",
                    line=idx + 1,  # 1-based step index as line proxy
                    column=1,
                    matched_text=f"job={job_name} mint={kind}",
                    severity="MAJOR",
                    description=(
                        f"Job `{job_name}` mints a `{kind}` token but "
                        "contains no revoke / delete-access-token / "
                        "delete-access-key / token-revoke step. TTL-"
                        "based cleanup leaves a post-job replay window "
                        "(sealed-env T10, claude-code-cve-gate)."
                    ),
                    owasp_asi="ASI-04",
                ))
    return findings


def _job_has_secret_reference(steps: list) -> bool:
    """True iff any step references `secrets.X` via the workflow
    expression context. We string-search the JSON-ish dump of each
    step to catch references inside `with:` blocks, `env:` blocks,
    and `run:` blocks uniformly."""
    pat = re.compile(r"\$\{\{\s*secrets\.\w+\s*\}\}")
    for step in steps:
        if not isinstance(step, dict):
            continue
        # Joining str(step.values()) handles `with`/`env`/`run` in one go.
        if pat.search(str(step)):
            return True
    return False


def find_dispatch_artifact_survival(workflow: dict) -> list[Finding]:
    """Detect a workflow_dispatch-triggered job that uploads a
    secret-bearing artifact with retention greater than 7 days.

    Returns Findings tagged `credential-survives-workflow-dispatch-
    via-artifact`. Default GitHub Actions retention is 90 days, which
    is the canonical Shai-Hulud cross-run survival window."""
    findings: list[Finding] = []
    if not isinstance(workflow, dict):
        return findings
    triggers = workflow.get("on") or workflow.get(True)  # YAML quirk: "on" → True
    has_dispatch = False
    if isinstance(triggers, dict):
        has_dispatch = "workflow_dispatch" in triggers
    elif isinstance(triggers, list):
        has_dispatch = "workflow_dispatch" in triggers
    elif isinstance(triggers, str):
        has_dispatch = triggers == "workflow_dispatch"
    if not has_dispatch:
        return findings
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return findings
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        if not _job_has_secret_reference(steps):
            continue
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            uses = str(step.get("uses", ""))
            if "actions/upload-artifact@" not in uses:
                continue
            raw_with = step.get("with")
            with_block: dict = raw_with if isinstance(raw_with, dict) else {}
            retention = with_block.get("retention-days")
            try:
                retention_int = int(retention) if retention is not None else None
            except (TypeError, ValueError):
                retention_int = None
            if retention_int is not None and retention_int <= 7:
                continue  # operator explicitly chose a short window
            findings.append(Finding(
                rule_id="credential-survives-workflow-dispatch-via-artifact",
                line=idx + 1,
                column=1,
                matched_text=(
                    f"job={job_name} upload-artifact retention="
                    f"{retention if retention is not None else 'default-90d'}"
                ),
                severity="CRITICAL",
                description=(
                    "workflow_dispatch-triggered job uses `secrets.*` "
                    "AND uploads an artifact with retention > 7 days. "
                    "The artifact persists by default for 90 days — a "
                    "later workflow_run worm (Shai-Hulud Second Coming) "
                    "can fetch it and re-use the secret. Override the "
                    "retention-days to <=7, or drop the upload."
                ),
                owasp_asi="ASI-05",
            ))
    return findings


# ---- The text-mode composed scanner -------------------------------------


# Rule IDs that the text scanner handles directly via pattern-iter.
# The remaining rules are exposed through dedicated helper functions
# (find_refresh_token_exfil, find_oauth_state_missing,
# find_token_format_mismatch, find_revoke_suppression_python,
# find_mint_without_revoke, find_dispatch_artifact_survival).
_TEXT_SCAN_RULE_IDS: frozenset[str] = frozenset({
    "refresh-token-written-to-disk",
    "refresh-token-written-to-disk-reverse",
    "revoke-error-suppressed-shell",
    "revoke-error-suppressed-shell-reverse",
    "npmrc-pypirc-token-injection-from-job-env",
    "npmrc-pypirc-token-injection-from-job-env-reverse",
})


def scan_text(text: str) -> list[Finding]:
    """Run every text-scan-eligible RULE against `text` and return
    findings. The catalogue's higher-level analyses (issuer mismatch,
    OAuth-state-missing, format mismatch, Python AST revoke, workflow
    walks) live in their own helper functions because they require
    cross-pattern correlation or non-regex inputs.

    Findings are deduped by (rule_id, line, col)."""
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        if rule.id not in _TEXT_SCAN_RULE_IDS:
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
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


def scan_all(text: str) -> list[Finding]:
    """Convenience entry-point: run scan_text() plus every helper that
    doesn't need a YAML dict. Use this on plain source / shell / .env
    files to get the full text-mode finding set in one call.

    The YAML-walk helpers (find_mint_without_revoke,
    find_dispatch_artifact_survival) are NOT included — they need a
    parsed workflow object as input."""
    if not text:
        return []
    out: list[Finding] = []
    out.extend(scan_text(text))
    out.extend(find_refresh_token_exfil(text))
    out.extend(find_oauth_state_missing(text))
    out.extend(find_token_format_mismatch(text))
    out.extend(find_revoke_suppression_python(text))
    # Final dedup + sort
    seen: set[tuple[str, int, int]] = set()
    deduped: list[Finding] = []
    for f in out:
        key = (f.rule_id, f.line, f.column)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    deduped.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return deduped
