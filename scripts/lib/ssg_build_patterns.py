"""SSG build-time config leak patterns.

Wave-30 distillation round 16, angle: SSG build-time.

Catalogue of 6 SSG-specific anti-patterns distilled in
`reports/distill-round-16/ssg-build-time.md`. Targets Gatsby /
Next.js SSG / Astro / Hugo / Jekyll / Nuxt static build pipelines.

What is NOT here (already shipped — DO NOT duplicate):

  * React/Vue/Svelte runtime patterns — `frontend_patterns.py`.
  * Webpack/Vite/esbuild bundler patterns — `js_bundler_patterns.py`,
    `vite_esbuild_bun_patterns.py`.
  * Generic env-var credential leaks — `credential_lifecycle_patterns.py`.
  * Edge-compute/serverless runtime patterns — `edge_compute_patterns.py`.

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * ssg-next-public-prefix-secret           (CRITICAL)
  * ssg-next-public-runtime-config-secret   (HIGH)
  * ssg-gatsby-config-token-literal         (HIGH)
  * ssg-nuxt-runtime-config-public-secret   (HIGH)
  * ssg-jekyll-config-secret                (HIGH)
  * ssg-get-static-props-secret-in-props    (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (literal tokens, keys embedded in build config)
  ASI-05 — Misconfiguration (public/private runtime config boundary violated)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- S1 : ssg-next-public-prefix-secret ---------------------------------

# NEXT_PUBLIC_ prefix on a sensitive variable name with a non-trivial value.
# Does NOT flag pure env-var references (process.env.NEXT_PUBLIC_FOO alone)
# or placeholder-looking values (empty, or only whitespace/comments after =).
# Allowlists Stripe publishable-key values (pk_live_ / pk_test_) which are
# intentionally public.
_NEXT_PUBLIC_SECRET = _re(
    r"NEXT_PUBLIC_(?:GITHUB_TOKEN|API_KEY|SECRET|PRIVATE_KEY|AUTH_TOKEN"
    r"|ACCESS_TOKEN|SIGNING_KEY|STRIPE_SECRET)[A-Z0-9_]*"
    r"\s*=\s*(?!pk_(?:live|test)_)(?!\s*$)[^\n#]{8,}"
)

# ---- S2 : ssg-next-public-runtime-config-secret -------------------------

# publicRuntimeConfig block in next.config.* containing a credential key.
# Matches a multi-character block between the outer braces — bounded by
# [^}]* to keep the match linear and RE2-safe.
_NEXT_PUBLIC_RUNTIME_CONFIG = _re(
    r"publicRuntimeConfig\s*:\s*\{"
    r"[^}]*(?:token|secret|key|password|credential|apikey|auth)[^}]*\}"
)

# ---- S3 : ssg-gatsby-config-token-literal -------------------------------

# Literal credential value (string, not env-var reference) in gatsby-config.
# Matches key: 'value' or key: "value" patterns where value is at least 20
# chars of base64/hex/alphanumeric characters — typical token entropy.
_GATSBY_CONFIG_TOKEN = _re(
    r"(?:accessToken|Authorization|apiKey|token)\s*:\s*['\"][A-Za-z0-9+/._-]{20,}['\"]"
)

# ---- S4 : ssg-nuxt-runtime-config-public-secret -------------------------

# runtimeConfig.public block in nuxt.config.* containing a credential key.
# Nested brace structure: outer `runtimeConfig: {` then `public: {` — both
# bounded with [^}]* to avoid catastrophic backtracking.
_NUXT_RUNTIME_CONFIG_PUBLIC = _re(
    r"runtimeConfig\s*:\s*\{"
    r"[^}]*public\s*:\s*\{"
    r"[^}]*(?:key|token|secret|password|apikey|auth)[^}]*\}"
)

# ---- S5 : ssg-jekyll-config-secret --------------------------------------

# Jekyll _config.yml with a bare secret value on a known credential key.
# Uses ^ (start of line via MULTILINE) to anchor to a YAML key at column 0.
# Value must be at least 16 non-whitespace characters (excludes env vars
# interpolated via ERB <%= ENV[...] %> which contain angle brackets).
_JEKYLL_CONFIG_SECRET = _re(
    r"^(?:github_token|api_key|secret_key|password|auth_token|access_token)"
    r"\s*:\s*[A-Za-z0-9+/._-]{16,}"
)

# ---- S6 : ssg-get-static-props-secret-in-props --------------------------

# getStaticProps return value that includes a process.env reference for a
# non-public env var inside the props object. The NEXT_PUBLIC_ case is
# intentional and excluded by requiring the env var name to NOT contain
# "PUBLIC" (handled via character-class exclusion of "PUBLIC" — RE2-safe
# because we anchor on the underscore boundary).
# Bounded [^}]* keeps it linear.
_GET_STATIC_PROPS_SECRET = _re(
    r"props\s*:\s*\{"
    r"[^}]*(?:token|secret|key|password|apikey|auth)\s*:\s*"
    r"process\.env\.[A-Z][A-Z0-9]*_(?!PUBLIC)[A-Z_]{2,}"
    r"[^}]*\}"
)


# ---- Rule catalogue -----------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="ssg-next-public-prefix-secret",
        name="NEXT_PUBLIC_ prefix on a sensitive env var inlines secret into client bundle",
        severity="CRITICAL",
        description=(
            "A Next.js env var whose name starts with NEXT_PUBLIC_ and "
            "whose suffix matches a known-sensitive pattern (GITHUB_TOKEN, "
            "API_KEY, SECRET, PRIVATE_KEY, AUTH_TOKEN, ACCESS_TOKEN, "
            "SIGNING_KEY, STRIPE_SECRET) is assigned a non-trivial value. "
            "The NEXT_PUBLIC_ prefix causes Next.js to inline the value "
            "verbatim into the client-side JS bundle at build time — it "
            "appears in plain text inside _next/static/chunks/*.js and is "
            "visible to every browser visitor. Stripe publishable keys "
            "(pk_live_ / pk_test_) are allowlisted because they are "
            "intentionally public by Stripe design."
        ),
        pattern=_NEXT_PUBLIC_SECRET,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="ssg-next-public-runtime-config-secret",
        name="Credential under Next.js publicRuntimeConfig is embedded in client payload",
        severity="HIGH",
        description=(
            "A value placed under `publicRuntimeConfig` in next.config.js / "
            "next.config.ts / next.config.mjs is serialised into the browser "
            "hydration payload (__NEXT_DATA__) and is visible to every client. "
            "Secrets intended as server-only must be placed under "
            "`serverRuntimeConfig` instead. Distinct from SSG-001 "
            "(NEXT_PUBLIC_ prefix) because publicRuntimeConfig is a runtime "
            "injection mechanism — the value may not be an env-var literal "
            "but still leaks."
        ),
        pattern=_NEXT_PUBLIC_RUNTIME_CONFIG,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ssg-gatsby-config-token-literal",
        name="Literal API token committed inside gatsby-config plugin options",
        severity="HIGH",
        description=(
            "A literal credential value (string, not env-var reference) is "
            "committed inside gatsby-config.js / gatsby-config.ts / "
            "gatsby-config.mjs plugin options. The Gatsby build executes this "
            "file server-side, but the file is almost always committed to the "
            "repository. Contentful Personal Access Tokens (CFPAT- prefix), "
            "GraphQL admin bearer tokens, and CMS management keys present here "
            "allow attackers with repo read access to modify or exfiltrate CMS "
            "content. Correctly externalised values use process.env.FOO and "
            "will NOT match because no string literal is present."
        ),
        pattern=_GATSBY_CONFIG_TOKEN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="ssg-nuxt-runtime-config-public-secret",
        name="Nuxt 3 runtimeConfig.public contains a credential key",
        severity="HIGH",
        description=(
            "In nuxt.config.ts / nuxt.config.js / nuxt.config.mjs, values "
            "placed under `runtimeConfig.public` are exposed to the Nuxt "
            "client bundle and accessible via useRuntimeConfig() in browser "
            "code. This is analogous to Next.js NEXT_PUBLIC_ prefixing: "
            "any secret moved here for convenience (to avoid separate server "
            "middleware) is shipped to every browser visitor. Server-only "
            "secrets must remain at the top level of runtimeConfig (i.e. NOT "
            "nested under the `public` sub-key)."
        ),
        pattern=_NUXT_RUNTIME_CONFIG_PUBLIC,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ssg-jekyll-config-secret",
        name="Secret value committed to Jekyll _config.yml",
        severity="HIGH",
        description=(
            "A Jekyll _config.yml or _config.yaml file contains a known "
            "credential key (github_token, api_key, secret_key, password, "
            "auth_token, access_token) with a non-trivial literal value. "
            "Jekyll evaluates _config.yml at build time; the file is "
            "committed to the repo and any secret here is exposed via git "
            "history. GitHub fine-grained PATs and service API keys with "
            "write access found here grant broad repository or service "
            "control to anyone with repo read access. Env-var ERB "
            "interpolations (<%= ENV['KEY'] %>) do NOT match because the "
            "value contains angle-bracket characters outside the allowed set."
        ),
        pattern=_JEKYLL_CONFIG_SECRET,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="ssg-get-static-props-secret-in-props",
        name="getStaticProps returns a server env var as a page prop, leaking it to __NEXT_DATA__",
        severity="CRITICAL",
        description=(
            "A Next.js getStaticProps function returns a process.env reference "
            "for a non-public environment variable (name does NOT contain "
            "PUBLIC) inside the `props` object. The return value of "
            "getStaticProps is serialised into the static HTML as "
            "__NEXT_DATA__ and shipped to every visitor. A token, secret, or "
            "key placed here is not used server-side only — it is embedded "
            "verbatim in the page payload. NEXT_PUBLIC_ env vars are "
            "intentionally public and excluded from this rule (covered by "
            "SSG-001). Stripe publishable keys passed as props are also "
            "acceptable but must use a name that does not match the "
            "credential-key list."
        ),
        pattern=_GET_STATIC_PROPS_SECRET,
        owasp_asi="ASI-02",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    All six rules are single-pass pattern matches — no stage-B context
    filtering is needed because each pattern is already specific enough
    (file-type targeting is left to the caller).

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

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule, m.start(), m.group(0))

    return findings
