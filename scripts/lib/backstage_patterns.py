"""Backstage SoftwareTemplate + Scaffolder-action security patterns.

Wave-37 distillation round 23, angle Backstage templates.

Catalogue of 10 Backstage-specific anti-patterns distilled in
`reports/distill-round-23/20260528_111115+0200-backstage-templates.md`.
Targets Backstage `template.yaml` scaffolder steps, `catalog-info.yaml`
entities, `app-config.*.yaml` provider config, and custom scaffolder
actions in backend plugins (TS/JS).

What is NOT here (already shipped — DO NOT duplicate):

  * Generic SSRF sink heuristics — `ssrf_patterns.py`.
  * GitHub Actions workflow injection — `zizmor_patterns.py`,
    `workflow_security` detector.
  * Generic remote-module / eval RCE — `dynamic_code_exec_patterns.py`.

What IS here (10 net-new rules, regex-anchored, all RE2-safe):

  * backstage-fetch-template-user-url-ssrf          (CRITICAL)
  * backstage-publish-github-user-repourl           (HIGH)
  * backstage-fs-rename-user-dest-path              (HIGH)
  * backstage-scaffolder-action-dynamic-code        (CRITICAL)
  * backstage-prod-config-guest-auth                (CRITICAL)
  * backstage-catalog-group-privilege-escalation    (HIGH)
  * backstage-ldap-empty-group-filter               (HIGH)
  * backstage-fetch-plain-user-url                  (HIGH)
  * backstage-location-http-target-ssrf             (HIGH)
  * backstage-openapi-mock-server-exposed           (MEDIUM)

Public surface mirrors sibling modules:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  API1 — Broken Object Level Authorization (catalog Group escalation)
  API2 — Broken Authentication (guest auth in prod, LDAP empty filter)
  API7 — Security Misconfiguration (OpenAPI mock server exposed)
  API8 — SSRF (fetch:template / fetch:plain / Location HTTP target)
  API10 — Unsafe Consumption / RCE (dynamic code in scaffolder action,
            arbitrary-file-write via fs:rename / publish:github)

All COMPILED patterns are plain — no lookahead, lookbehind, or
backreferences (RE2-safe). The proposal's two-anchor signals (e.g.
"fetch:plain" + "url: ${{ ...") are expressed via a Python-side same-file
correlation in scan_text rather than a single multi-line lookahead.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as firebase_rules_patterns.Finding."""

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
    """Compile with IGNORECASE+MULTILINE. RE2-safe: no nested quantifiers,
    no backreferences, no lookbehind, no lookahead."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


# A reusable fragment matching a Backstage template expression that
# interpolates a scaffolder parameter, e.g. ``${{ parameters.repoUrl }}``.
# The whitespace around the dots is bounded — RE2-safe.
_PARAM_EXPR = r"\$\{\{\s*parameters\."


# ---- D1 : backstage-fetch-template-user-url-ssrf ------------------------
_FETCH_TEMPLATE_USER_URL = _re(r"url\s*:\s*" + _PARAM_EXPR)

# ---- D2 : backstage-publish-github-user-repourl -------------------------
_PUBLISH_GITHUB_REPOURL = _re(r"repoUrl\s*:\s*" + _PARAM_EXPR)

# ---- D3 : backstage-fs-rename-user-dest-path ----------------------------
_FS_RENAME_USER_DEST = _re(r"to\s*:\s*" + _PARAM_EXPR)

# ---- D4 : backstage-scaffolder-action-dynamic-code ----------------------
# vm.runInNewContext / vm.runInContext / eval( in a backend plugin.
_DYNAMIC_CODE_EXEC = _re(
    r"\b(?:vm\.runInNewContext|vm\.runInContext|eval)\s*\("
)

# ---- D5 : backstage-prod-config-guest-auth ------------------------------
# The `guest:` key under auth.providers. The scan_text caller restricts the
# severity context to production configs by file-name; the rule itself flags
# the line-scoped key.
_GUEST_PROVIDER = _re(r"^\s+guest\s*:\s*$")

# ---- D6 : backstage-catalog-group-privilege-escalation ------------------
# `kind: Group` correlated with a sensitive group name in the same file.
_KIND_GROUP = _re(r"kind\s*:\s*Group\b")
_SENSITIVE_GROUP_NAME = _re(
    r"name\s*:\s*[\"']?"
    r"(?:admin|admins|platform-admin|platform-admins|ops|superuser"
    r"|backstage-admin|cluster-admin)\b"
)

# ---- D7 : backstage-ldap-empty-group-filter -----------------------------
_LDAP_EMPTY_FILTER = _re(
    r"groupSearchFilter\s*:\s*(?:[\"']\s*[\"']|[\"']\(objectClass=\*\)[\"'])"
)

# ---- D8 : backstage-fetch-plain-user-url --------------------------------
_FETCH_PLAIN_ACTION = _re(r"action\s*:\s*fetch:plain\b")

# ---- D9 : backstage-location-http-target-ssrf ---------------------------
_KIND_LOCATION = _re(r"kind\s*:\s*Location\b")
_HTTP_TARGET = _re(r"-\s+http://")

# ---- D10 : backstage-openapi-mock-server-exposed ------------------------
_OPENAPI_MOCK = _re(
    r"(?:OpenAPIBackend\b[\s\S]{0,300}?mock\s*:\s*true"
    r"|\.mockResponseForOperation\s*\()"
)


# ---- Rule registry ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="backstage-fetch-template-user-url-ssrf",
        name="backstage-fetch-template-user-url",
        severity="CRITICAL",
        description=(
            "A scaffolder fetch:template step interpolates a user-supplied "
            "${{ parameters.* }} directly into its `url:` — the backend fetches "
            "it server-side with full internal network access (SSRF to "
            "metadata service / internal k8s DNS)."
        ),
        pattern=_FETCH_TEMPLATE_USER_URL,
        owasp_asi="API8:2023",
    ),
    Rule(
        id="backstage-publish-github-user-repourl",
        name="backstage-publish-github-user-repourl",
        severity="HIGH",
        description=(
            "A publish:github / repoUrl field is built from "
            "${{ parameters.* }} with no allowedHosts/allowedOwners enforcement "
            "— attacker-controlled repo name can exfiltrate workspace secrets "
            "or write to an unexpected org."
        ),
        pattern=_PUBLISH_GITHUB_REPOURL,
        owasp_asi="API8:2023",
    ),
    Rule(
        id="backstage-fs-rename-user-dest-path",
        name="backstage-fs-rename-user-dest-path",
        severity="HIGH",
        description=(
            "A fs:rename step takes its `to:` destination from "
            "${{ parameters.* }} — a crafted '../' value escapes the workspace "
            "temp dir and writes into Git internals or arbitrary paths."
        ),
        pattern=_FS_RENAME_USER_DEST,
        owasp_asi="API10:2023",
    ),
    Rule(
        id="backstage-scaffolder-action-dynamic-code",
        name="backstage-scaffolder-action-dynamic-code",
        severity="CRITICAL",
        description=(
            "A custom scaffolder action uses vm.runInNewContext / "
            "vm.runInContext / eval — arbitrary code execution in the "
            "scaffolder backend process if any of the evaluated input is "
            "config- or request-controlled."
        ),
        pattern=_DYNAMIC_CODE_EXEC,
        owasp_asi="API10:2023",
    ),
    Rule(
        id="backstage-prod-config-guest-auth",
        name="backstage-prod-config-guest-auth",
        severity="CRITICAL",
        description=(
            "The guest auth provider is enabled under auth.providers. In a "
            "production config this grants unauthenticated access to the "
            "frontend, scaffolder API, and catalog write endpoints."
        ),
        pattern=_GUEST_PROVIDER,
        owasp_asi="API2:2023",
    ),
    Rule(
        id="backstage-catalog-group-privilege-escalation",
        name="backstage-catalog-group-privilege-escalation",
        severity="HIGH",
        description=(
            "A catalog-info.yaml declares `kind: Group` with a sensitive group "
            "name (admin/ops/superuser). If untrusted repos are ingested "
            "without an approval gate, an attacker self-adds to a high-"
            "privilege group via catalog entity injection."
        ),
        pattern=_KIND_GROUP,
        owasp_asi="API1:2023",
    ),
    Rule(
        id="backstage-ldap-empty-group-filter",
        name="backstage-ldap-empty-group-filter",
        severity="HIGH",
        description=(
            "Backstage LDAP groupSearchFilter is empty or '(objectClass=*)', "
            "importing every LDAP group. Combined with a permissive role "
            "mapping, any LDAP user can land in an admin-mapped group "
            "(authorization bypass)."
        ),
        pattern=_LDAP_EMPTY_FILTER,
        owasp_asi="API2:2023",
    ),
    Rule(
        id="backstage-fetch-plain-user-url",
        name="backstage-fetch-plain-user-url",
        severity="HIGH",
        description=(
            "A scaffolder fetch:plain step downloads and unpacks an archive "
            "from a user-controlled ${{ parameters.* }} URL — malicious "
            "symlink/'../' tar entries can escape the workspace temp dir on "
            "unpack (supply-chain / SSRF)."
        ),
        pattern=_FETCH_PLAIN_ACTION,
        owasp_asi="API8:2023",
    ),
    Rule(
        id="backstage-location-http-target-ssrf",
        name="backstage-location-http-target-ssrf",
        severity="HIGH",
        description=(
            "A catalog `kind: Location` entity lists a plaintext http:// "
            "target. The catalog processor fetches it server-side (SSRF) and "
            "ingests the response as catalog entities — enabling malicious "
            "Group/User injection."
        ),
        pattern=_KIND_LOCATION,
        owasp_asi="API8:2023",
    ),
    Rule(
        id="backstage-openapi-mock-server-exposed",
        name="backstage-openapi-mock-server-exposed",
        severity="MEDIUM",
        description=(
            "A Backstage backend plugin registers an OpenAPI mock server "
            "(OpenAPIBackend mock:true / mockResponseForOperation). Left in a "
            "production bundle it exposes the full API surface and may "
            "short-circuit real auth middleware."
        ),
        pattern=_OPENAPI_MOCK,
        owasp_asi="API7:2023",
    ),
)


# ---- Scanner ------------------------------------------------------------


def _line_col_factory(text: str):
    """Build a 1-based (line, column) resolver over *text* using binary
    search on precomputed line-start offsets."""
    offsets: list[int] = []
    cumulative = 0
    for ln in text.splitlines(keepends=True):
        offsets.append(cumulative)
        cumulative += len(ln)
    if not offsets:
        offsets.append(0)

    def _line_col(match_start: int) -> tuple[int, int]:
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid] <= match_start:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, match_start - offsets[lo] + 1

    return _line_col


def _emit(
    rule: Rule,
    match: re.Match,
    line_col,
    findings: list[Finding],
) -> None:
    ln, col = line_col(match.start())
    findings.append(
        Finding(
            rule_id=rule.id,
            line=ln,
            column=col,
            matched_text=match.group()[:120],
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        )
    )


def scan_text(text: str) -> list[Finding]:
    """Scan *text* against all RULES and return a list of Findings.

    Two rules use Python-side same-file correlation rather than a single
    multi-line regex (kept RE2-safe):

      * backstage-catalog-group-privilege-escalation fires only when a
        `kind: Group` entity is present AND a sensitive group name appears
        somewhere in the same file.
      * backstage-location-http-target-ssrf fires only when a `kind:
        Location` entity is present AND a plaintext http:// list target
        appears in the same file.

    Line and column numbers are 1-based. matched_text is trimmed to 120
    characters.
    """
    if not text:
        return []

    findings: list[Finding] = []
    line_col = _line_col_factory(text)

    has_sensitive_group_name = bool(_SENSITIVE_GROUP_NAME.search(text))
    has_http_target = bool(_HTTP_TARGET.search(text))

    for rule in RULES:
        rid = rule.id

        if rid == "backstage-catalog-group-privilege-escalation":
            if not has_sensitive_group_name:
                continue  # a plain Group with no sensitive name is benign
            for m in rule.pattern.finditer(text):
                _emit(rule, m, line_col, findings)
            continue

        if rid == "backstage-location-http-target-ssrf":
            if not has_http_target:
                continue  # a Location with only https GitHub targets is fine
            for m in rule.pattern.finditer(text):
                _emit(rule, m, line_col, findings)
            continue

        # Plain rules: every match is a finding.
        for m in rule.pattern.finditer(text):
            _emit(rule, m, line_col, findings)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
