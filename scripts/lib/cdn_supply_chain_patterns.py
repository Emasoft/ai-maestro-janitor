"""Browser-side CDN supply-chain patterns.

Wave 22 (impl-c) — distillation of 12 proposals from
``reports/distill-round-8/cdn-supply-chain.md`` into deterministic,
RE2-safe regex rules. This module catalogues HTML / JSX / TSX / Vue /
Svelte / Astro / MDX / service-worker / npm-pnpm-config attack shapes
that target **third-party asset inclusion** on the browser side:

  * Subresource Integrity (SRI) hash strength downgrade.
  * ``<link rel="preload|modulepreload">`` to CDN without SRI.
  * ``<iframe sandbox>`` privilege escalation
    (``allow-scripts`` AND ``allow-same-origin`` combo).
  * ``<iframe>`` without ``referrerpolicy`` — embedder-URL leak.
  * Service-worker ``importScripts()`` with cross-origin URL.
  * Service-worker registration at broad scope from third-party origin.
  * ``<link rel="preconnect|dns-prefetch">`` typo-squat host.
  * Tag-manager script (impossible-to-SRI risk-class inventory).
  * Vendored asset tree without SBOM manifest.
  * Non-canonical registry redirection
    (``.npmrc``, ``.yarnrc.yml``, ``pyproject.toml``, ``Cargo.toml``).
  * pnpm ``node-linker: hoisted`` (declared-vs-installed drift).
  * Mixed-content HTTP scheme on a production page.

Architecture mirrors ``scripts/lib/cdn_cache_patterns.py`` (Wave 18)
and ``scripts/lib/frontend_patterns.py`` (Wave 17):

  * ``Rule(id, name, severity, description, pattern, owasp_asi)``
                                  — single rule record. Patterns are
                                    pre-compiled at module load.
  * ``RULES``                     — ordered tuple of every catalogued rule.
  * ``scan_text(text)`` -> list[Finding]
                                  — run every rule, return findings.
  * ``Finding(rule_id, line, column, matched_text, severity,
              description, owasp_asi)``
                                  — single finding record.

Why a separate module — Wave 18's ``cdn_cache_patterns.py`` already
catches the basic ``<script src=CDN>`` without ``integrity=`` case
(rule #11). The 12 proposals here EXTEND it onto adjacent surfaces
the runtime stage-1 regex previously missed (hash-strength downgrade,
``<link rel=preload>`` bypass, iframe sandbox escape, referrer-policy
leak, service-worker importScripts, registry mirror redirection,
vendor SBOM absence, pnpm hoisting, mixed-content). No proposal
duplicates a Wave-17 or Wave-18 rule.

Pure-stdlib (re, NamedTuple) so it loads in every PEP 723 script
block without third-party deps. Patterns favour FP-tolerance over
precision — the caller (the doctor's CDN sweep) is responsible for
the contextual gates documented per-rule in the source report:

  * ``cdn-c1-sri-weak-hash`` — caller should skip when a sibling
    sha384 / sha512 hash also appears in the same ``integrity=``
    attribute (multi-hash safe-fallback form).
  * ``cdn-c2-preload-no-sri`` — same multi-hash exemption.
  * ``cdn-c3-iframe-sandbox-escape`` — caller should skip when the
    iframe ``src`` is same-origin OR ``srcdoc=`` carries inline HTML.
  * ``cdn-c5-sw-importscripts-cross-origin`` — caller should skip
    when the URL is built from ``self.location.origin`` or
    a documented Workbox CDN pin.
  * ``cdn-c9-vendor-tree-no-sbom`` — caller should skip when a
    sibling SBOM manifest exists.
  * ``cdn-c10-registry-non-canonical`` — caller should skip when an
    organization allowlist file documents the mirror.

Rule severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW",
matching the existing janitor sentinel/zizmor convention. The
mapping from the source report's severity is:
  CRITICAL → "CRITICAL"; MAJOR → "HIGH"; MINOR → "MEDIUM".

OWASP ASI tagging (browser-side supply chain bucket):
  * ASI-01 (Compromised Build Pipeline / Vendor) — C-9, C-10, C-11
  * ASI-02 (Insecure Dependency) — C-1, C-2, C-5, C-6, C-12
  * ASI-04 (Insecure HTTP Headers) — C-4, C-8
  * ASI-06 (Origin Trust Issues) — C-3, C-7

All patterns are RE2-safe — no backreferences, no possessive
quantifiers, no lookbehinds. Lookaheads are anchored (no
unbounded backtracking) so the engine performs in O(input).
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    ``scripts/lib/cdn_cache_patterns.Finding`` so heartbeat detectors
    and SARIF emitters render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # e.g. "ASI-02"; empty string when no mapping applies


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

    HTML tag names (``<script>``, ``<link>``, ``<iframe>``) are
    case-insensitive in browsers but XHTML strict mode requires
    lowercase; we accept both. JSX preserves casing
    (``<Script>`` is a React component, not the HTML element), but
    React-component CDN inclusion is the same supply-chain shape so
    case-insensitive match is correct here.

    MULTILINE makes ``^`` / ``$`` line-anchored for the
    ``registry=`` line-start rule (C-10) and the
    ``node-linker:`` declaration rule (C-11).

    UNICODE is the default in Python 3 but stated explicitly for
    platform-consistency.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- C-1: SRI hash uses sha224 or sha256 (downgrade) --------------------


# Match ``<script>`` / ``<link>`` with integrity="sha256-..." or
# "sha224-..." that does NOT contain a sibling sha384/sha512 hash in
# the SAME integrity attribute. The lookahead inside the attribute
# value rejects the multi-hash safe-fallback form.
#
# Bounded body: ``[^>]{0,400}`` keeps the match RE2-safe (no
# unbounded greedy spans that could ReDoS on a degenerate tag).
_SRI_WEAK_HASH = _re(
    r"<(?:script|link)\b"
    # Up to 400 chars of attributes before integrity= (RE2-safe bound).
    r"[^>]{0,400}?"
    # integrity= attribute opening
    r"\bintegrity\s*=\s*[\"']"
    # Inside the quotes: a sha224/sha256 prefix.
    # Reject the multi-hash form: the attribute value must NOT contain
    # any sha384- or sha512- prefix anywhere.
    r"(?=[^\"']*sha(?:224|256)-)"
    r"(?![^\"']*sha384-)"
    r"(?![^\"']*sha512-)"
    # Match the actual sha224/sha256 hash for the finding's matched_text.
    r"[^\"']{0,200}"
    r"sha(?:224|256)-[A-Za-z0-9+/=]{16,}"
    r"[^\"']{0,200}"
    r"[\"']"
    # Up to 200 chars more attributes, then close.
    r"[^>]{0,200}>"
)


# ---- C-2: <link rel="preload|modulepreload"> to CDN without SRI ---------


# Match a ``<link>`` tag with rel=preload|modulepreload|prefetch and a
# cross-origin href that does NOT carry integrity="sha384-..." /
# "sha512-...".
#
# RE2-safe: we use a single bounded attribute window, then assert via
# anchored lookaheads that (a) no integrity= attribute is present, OR
# (b) integrity= is present but does NOT contain sha384/sha512.
_PRELOAD_NO_SRI = _re(
    r"<link\b"
    # Bounded attribute window.
    r"(?=[^>]{0,500}>)"
    # Must have rel=preload | modulepreload | prefetch
    r"[^>]{0,400}?"
    r"\brel\s*=\s*[\"'](?:preload|modulepreload|prefetch)[\"']"
    r"[^>]{0,400}?"
    # Must have href= to an http(s):// URL that is NOT localhost.
    r"\bhref\s*=\s*[\"']https?://"
    # Anchored host rejection: the next non-quote char must NOT start
    # with "localhost" or "127." — the lookahead is bounded so RE2-safe.
    r"(?!localhost)(?!127\.)(?!\[::1\])"
    r"[^\"']{1,300}[\"']"
    # The remainder of the tag MUST NOT contain integrity="sha384-..."
    # or integrity="sha512-..." — the absence is the bug. We approximate
    # via a global negative lookahead anchored on the tag-open above.
    # Note: we re-assert the bounded window so the lookahead is RE2-safe.
    r"[^>]{0,300}>"
)


# Helper: confirm at stage-2 that the matched tag truly lacks sha384/sha512.
# A pure regex cannot express "attribute value does not appear elsewhere
# in the SAME tag" without an unbounded backreference / lookbehind. We
# do the second pass in pure Python instead, mirroring Wave 18's
# ``has_sri_on_tag`` helper.
_PRELOAD_TAG_HAS_STRONG_SRI = re.compile(
    r"\bintegrity\s*=\s*[\"'][^\"']*sha(?:384|512)-",
    re.IGNORECASE,
)


# ---- C-3: <iframe sandbox> grants allow-scripts AND allow-same-origin --


# Match an iframe whose sandbox value contains BOTH `allow-scripts`
# and `allow-same-origin` (in either order). Bounded attribute window.
_IFRAME_SANDBOX_ESCAPE = _re(
    r"<iframe\b"
    r"[^>]{0,400}?"
    r"\bsandbox\s*=\s*[\"']"
    # The order is either A→B or B→A. Express as an alternation
    # within a single value group, with bounded gaps.
    r"(?:"
    r"[^\"']{0,200}allow-scripts[^\"']{0,200}allow-same-origin"
    r"|"
    r"[^\"']{0,200}allow-same-origin[^\"']{0,200}allow-scripts"
    r")"
    r"[^\"']{0,200}[\"']"
    r"[^>]{0,400}>"
)


# Stage-2 helper: matched tag has srcdoc= (inline HTML — safe)?
_IFRAME_HAS_SRCDOC = re.compile(
    r"\bsrcdoc\s*=\s*[\"']",
    re.IGNORECASE,
)


# ---- C-4: <iframe> without referrerpolicy (referrer leak) --------------


# Match an iframe with cross-origin src= that does NOT carry
# referrerpolicy=. Bounded attribute window; the absence is verified
# at stage-2 by a simple "tag does not contain referrerpolicy" check.
_IFRAME_NO_REFERRERPOLICY = _re(
    r"<iframe\b"
    r"[^>]{0,400}?"
    r"\bsrc\s*=\s*[\"']https?://"
    r"(?!localhost)(?!127\.)(?!\[::1\])"
    r"[^\"']{1,300}[\"']"
    r"[^>]{0,400}>"
)


# Stage-2 helper: tag carries referrerpolicy= attribute?
_IFRAME_HAS_REFERRERPOLICY = re.compile(
    r"\breferrerpolicy\s*=\s*[\"']",
    re.IGNORECASE,
)


# ---- C-5: service-worker importScripts() with cross-origin URL ---------


# Match an importScripts call whose argument is a string literal
# starting with `https?://` to a non-localhost host. Reject explicit
# same-origin templating (`self.location.origin`, `location.origin`).
_SW_IMPORTSCRIPTS_CROSS_ORIGIN = _re(
    r"\bimportScripts\s*\(\s*"
    r"[\"']https?://"
    # Reject localhost / 127.* / self / origin / location.origin.
    r"(?!localhost)(?!127\.)(?!\[::1\])(?!self)(?!origin)(?!location\.)"
    r"[^\"']{1,300}[\"']"
)


# Stage-2 helper: same-origin template-literal form is rare but exists.
_SW_IMPORTSCRIPTS_SAME_ORIGIN_TEMPLATE = re.compile(
    r"\bimportScripts\s*\(\s*"
    r"`(?:https?://)?\$\{(?:self\.|window\.)?location\.origin\}",
    re.IGNORECASE,
)


# ---- C-6: SW registration at scope '/' from third-party origin ---------


# Match navigator.serviceWorker.register('<url>', { scope: '/' }) where
# the URL is either a cross-origin string literal OR same-origin path
# that callers must cross-check at stage-2 against any proxy rewrite
# rules. The default scope (omitted) inherits the SW URL's directory —
# for /sw.js that means scope='/' implicitly. We flag the explicit
# '/' and the omitted-scope same-origin SW.
#
# Two shapes:
#   A) explicit scope='/' AND broad/3rd-party URL
#   B) cross-origin URL (which the browser will block on register, but
#      we still flag the source-code shape because the developer's
#      intent is exposed and may pass on older browsers / via proxy).
_SW_REGISTER_BROAD_SCOPE = _re(
    # Shape A: explicit scope: '/' or "/"
    r"navigator\.serviceWorker\.register\s*\(\s*"
    r"[\"'][^\"']{1,300}[\"']"
    r"\s*,\s*\{[^}]{0,200}\bscope\s*:\s*[\"']/[\"']"
    r"|"
    # Shape B: register call with a cross-origin URL (host has dot,
    # explicit scheme, not localhost / 127.*).
    r"navigator\.serviceWorker\.register\s*\(\s*"
    r"[\"']https?://"
    r"(?!localhost)(?!127\.)(?!\[::1\])"
    r"[^\"']{1,300}[\"']"
)


# ---- C-7: <link rel="preconnect|dns-prefetch"> to non-allowlisted host -


# Match a preconnect / dns-prefetch link tag. The host is captured at
# stage-1; stage-2 checks the captured host against the allowlist.
# Allowlist is exported as ``CDN_PRECONNECT_ALLOWLIST`` so callers can
# extend it per-repo.
_PRECONNECT_LINK = _re(
    r"<link\b"
    r"[^>]{0,400}?"
    r"\brel\s*=\s*[\"'](?:preconnect|dns-prefetch)[\"']"
    r"[^>]{0,400}?"
    r"\bhref\s*=\s*[\"']https?://"
    r"([A-Za-z0-9.-]{1,253})"
    r"(?:[:/][^\"']{0,300})?"
    r"[\"']"
    r"[^>]{0,400}>"
)


# Standard public-CDN host allowlist. Stage-2 callers use this set
# to decide whether the captured host is benign. Any host NOT in this
# set is a finding (typo-squat candidate). Callers may union with
# repo-local lists.
CDN_PRECONNECT_ALLOWLIST: frozenset[str] = frozenset({
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
    "unpkg.com",
    "esm.sh",
    "cdn.skypack.dev",
    "ajax.googleapis.com",
    "stackpath.bootstrapcdn.com",
    "code.jquery.com",
    "use.fontawesome.com",
})


# ---- C-8: tag-manager script (impossible-to-SRI risk-class) ------------


# Match a tag-manager-class script src. The presence itself is the
# inventory signal — SRI is documented as not-applicable for these
# loaders, so the runbook control is CSP + synthetic monitor, not SRI.
# Hosts enumerated verbatim from the proposal.
_TAG_MANAGER_SCRIPT = _re(
    r"<script\b"
    r"[^>]{0,400}?"
    r"\bsrc\s*=\s*[\"']https://"
    r"(?:www\.)?"
    r"(?:"
    r"googletagmanager\.com"
    r"|google-analytics\.com"
    r"|connect\.facebook\.net"
    r"|js\.hsforms\.net"
    r"|js\.hsadspixel\.net"
    r"|cdn\.segment\.(?:com|io)"
    r"|cdn\.heapanalytics\.com"
    r"|static\.hotjar\.com"
    r"|js-agent\.newrelic\.com"
    r"|js\.intercomcdn\.com"
    r"|widget\.intercom\.io"
    r"|cdn\.amplitude\.com"
    r"|js\.stripe\.com"
    r")"
    r"/[^\"']{0,300}[\"']"
    r"[^>]{0,400}>"
)


# Tag-manager host inventory — exported so the doctor's CSP audit
# can pair the finding with a CSP `script-src` check.
TAG_MANAGER_HOSTS: tuple[str, ...] = (
    "googletagmanager.com",
    "google-analytics.com",
    "connect.facebook.net",
    "js.hsforms.net",
    "js.hsadspixel.net",
    "cdn.segment.com",
    "cdn.segment.io",
    "cdn.heapanalytics.com",
    "static.hotjar.com",
    "js-agent.newrelic.com",
    "js.intercomcdn.com",
    "widget.intercom.io",
    "cdn.amplitude.com",
    "js.stripe.com",
)


# ---- C-9: vendored asset tree without SBOM (filesystem rule) ----------


# This rule is a FILESYSTEM-shape detection (presence of vendored asset
# files with no SBOM sibling) — the regex below catches an inline
# marker that occasionally appears at the top of a build script or in
# repo-level configuration referencing such a tree. The detector's
# stage-2 (caller) walks the filesystem to verify; the regex serves as
# a stage-1 fast-fail.
#
# Match a comment / config line that references a vendor directory
# WITHOUT a sibling SBOM file. The caller's filesystem stage is the
# real check.
_VENDOR_DIR_REFERENCE = _re(
    r"(?:public|static|assets|wwwroot|dist)/(?:vendor|lib)/"
    r"[A-Za-z0-9._/-]{1,200}\.(?:min\.js|umd\.js|min\.css)"
)


# Stage-2 SBOM marker — caller checks the vendor directory for any of
# these filenames; if none present, the finding fires.
SBOM_MANIFEST_NAMES: frozenset[str] = frozenset({
    "VENDOR.md",
    "vendor-sbom.json",
    "cyclonedx.json",
    "sbom.json",
    "THIRD_PARTY_NOTICES.md",
    "vendor-manifest.json",
    "vendor-manifest.yaml",
    "vendor-manifest.toml",
})


# ---- C-10: registry= points at non-canonical host ----------------------


# Match a `registry=` config line whose URL is NOT one of the canonical
# package-registry hosts. The detector accepts the canonical npm /
# yarn / GitHub Packages hosts; anything else is a finding subject to
# an organization-allowlist override at stage-2.
#
# Surface: .npmrc / .yarnrc.yml / .pnpmrc / pip.conf / uv.toml /
# Cargo.toml / pyproject.toml lines.
_REGISTRY_NON_CANONICAL = _re(
    # Anchored to start-of-line (npmrc / yarnrc / pnpmrc are line-based).
    r"^\s*"
    r"(?:registry|npmRegistryServer|index-url|extra-index-url)"
    r"\s*[:=]\s*"
    r"[\"']?"
    r"https?://"
    # Negative lookaheads for canonical hosts. Anchored, so RE2-safe.
    r"(?!registry\.npmjs\.org)"
    r"(?!registry\.yarnpkg\.com)"
    r"(?!npm\.pkg\.github\.com)"
    r"(?!pypi\.org)"
    r"(?!files\.pythonhosted\.org)"
    r"(?!crates\.io)"
    r"(?!static\.crates\.io)"
    # Capture the URL host for stage-2.
    r"([A-Za-z0-9.-]{1,253})"
    r"(?:[:/][^\s\"'#]{0,500})?"
)


# Canonical package-registry hosts — stage-2 callers use this set to
# decide whether a captured host is benign. Anything not in the set
# is a finding.
CANONICAL_REGISTRY_HOSTS: frozenset[str] = frozenset({
    "registry.npmjs.org",
    "registry.yarnpkg.com",
    "npm.pkg.github.com",
    "pypi.org",
    "files.pythonhosted.org",
    "crates.io",
    "static.crates.io",
})


# ---- C-11: pnpm node-linker: hoisted (declared-vs-installed drift) -----


# Match the node-linker configuration set to hoisted in .npmrc or
# pnpm-workspace.yaml. Anchored to start-of-line (line-based config).
_PNPM_HOISTED_LINKER = _re(
    r"^\s*node-linker\s*[:=]\s*[\"']?hoisted\b"
)


# ---- C-12: mixed-content HTTP URL on production page -------------------


# Match a <script>/<link>/<img>/<iframe>/<source>/<video>/<audio>/
# <embed>/<object> tag whose src/href/data uses HTTP (not HTTPS) and
# is NOT a localhost / private-IP / link-local URL.
#
# Bounded attribute window for RE2 safety. The detector's stage-2
# additionally verifies that the surrounding HTML does NOT carry a
# CSP `upgrade-insecure-requests` directive (which would automatically
# rewrite the URL at fetch time).
_MIXED_CONTENT_HTTP = _re(
    r"<(?:script|link|img|iframe|source|video|audio|embed|object)\b"
    r"[^>]{0,400}?"
    r"\b(?:src|href|data)\s*=\s*[\"']http://"
    # Reject local / private addresses. Anchored, RE2-safe.
    r"(?!localhost)"
    r"(?!127\.)"
    r"(?!10\.)"
    r"(?!192\.168\.)"
    r"(?!172\.(?:1[6-9]|2[0-9]|3[01])\.)"
    r"(?!169\.254\.)"
    r"(?!0\.0\.0\.0)"
    r"(?!::1)"
    r"(?!\[::1\])"
    r"[^\"']{1,300}[\"']"
    r"[^>]{0,400}>"
)


# Stage-2 helper: surrounding HTML carries upgrade-insecure-requests?
_HAS_UPGRADE_INSECURE_REQUESTS = re.compile(
    r"upgrade-insecure-requests",
    re.IGNORECASE,
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="cdn-c1-sri-weak-hash",
        name="<script>/<link> integrity= uses sha224/sha256 only (no sha384/sha512 fallback)",
        severity="HIGH",
        description=(
            "A <script> or <link> tag carries an integrity= attribute "
            "whose hash prefix is sha224 or sha256 with no sibling "
            "sha384 / sha512 hash in the same attribute. The W3C SRI "
            "spec accepts all three prefixes, but browsers pick the "
            "strongest one present — a sha256-only hash on a "
            "cross-origin asset is a downgrade against sha384/sha512. "
            "Stage-2 must confirm the URL is cross-origin (not "
            "same-origin / localhost / private-IP)."
        ),
        pattern=_SRI_WEAK_HASH,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="cdn-c2-preload-no-sri",
        name="<link rel='preload|modulepreload|prefetch'> to CDN without strong SRI",
        severity="HIGH",
        description=(
            "A <link rel='preload|modulepreload|prefetch' href='<CDN>'> "
            "tag does NOT carry integrity='sha384-...' / sha512. The "
            "preload cache fills BEFORE the matching <script>'s SRI "
            "check runs; on Safari and older Firefox the preloaded "
            "(potentially malicious) bytes may be served. Stage-2 "
            "confirms the tag truly lacks a strong-SRI attribute via "
            "the has_strong_sri_on_tag() helper."
        ),
        pattern=_PRELOAD_NO_SRI,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="cdn-c3-iframe-sandbox-escape",
        name="<iframe sandbox> grants allow-scripts AND allow-same-origin",
        severity="CRITICAL",
        description=(
            "An <iframe> tag's sandbox= value grants BOTH allow-scripts "
            "AND allow-same-origin. MDN documents this combination as "
            "'effectively the same as not using the sandbox attribute' "
            "because the iframed page can run JS and access the "
            "embedder's cookies / localStorage / DOM via same-origin "
            "privileges. For cross-origin iframe content this is a "
            "confused-deputy attack. Stage-2 must skip if the iframe "
            "uses srcdoc= (inline HTML — safe)."
        ),
        pattern=_IFRAME_SANDBOX_ESCAPE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cdn-c4-iframe-referrer-leak",
        name="<iframe src='<cross-origin>'> without referrerpolicy attribute",
        severity="HIGH",
        description=(
            "An <iframe> with cross-origin src= does NOT carry "
            "referrerpolicy='no-referrer' / 'origin'. The default "
            "Referrer-Policy leaks the embedder's origin to the "
            "iframed origin; when the embedder URL contains tokens / "
            "magic-link parameters in the query, older browsers and "
            "any embedder that sets referrer-policy='unsafe-url' leak "
            "the FULL URL. Stage-2 confirms there is no site-wide "
            "Referrer-Policy HTTP header configured."
        ),
        pattern=_IFRAME_NO_REFERRERPOLICY,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cdn-c5-sw-importscripts-cross-origin",
        name="service-worker importScripts() with cross-origin URL (no SRI possible)",
        severity="CRITICAL",
        description=(
            "A service-worker file calls importScripts('https://...') "
            "with a cross-origin URL. importScripts has NO SRI support "
            "(it is a worker-context API), so a compromised CDN bytes "
            "pwn the whole origin for as long as the SW stays installed "
            "(default: forever, because the malicious SW can intercept "
            "its own update fetch). Worst-case browser-side rugpull. "
            "Stage-2 must skip same-origin template literals built from "
            "self.location.origin / location.origin."
        ),
        pattern=_SW_IMPORTSCRIPTS_CROSS_ORIGIN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="cdn-c6-sw-broad-scope-3rd-party",
        name="navigator.serviceWorker.register at scope '/' (or cross-origin URL)",
        severity="CRITICAL",
        description=(
            "Code calls navigator.serviceWorker.register() either (a) "
            "with explicit scope: '/' (broadest possible scope on the "
            "origin) or (b) with a cross-origin URL string literal. The "
            "browser blocks (b) since Chrome 89 / Firefox 78 / Safari "
            "14, but the source-code shape is still a red flag. "
            "Combined with a thin proxy /sw.js that 302-forwards to a "
            "3rd-party CDN, the registered SW sits between every fetch "
            "on the origin. Pin the SW to a narrow scope and self-host "
            "the bytes."
        ),
        pattern=_SW_REGISTER_BROAD_SCOPE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="cdn-c7-preconnect-rogue-host",
        name="<link rel='preconnect|dns-prefetch'> to non-allowlisted host (typo-squat)",
        severity="MEDIUM",
        description=(
            "A <link rel='preconnect|dns-prefetch' href='https://<host>'> "
            "tag's host is NOT in the standard public-CDN allowlist. "
            "Preconnect leaks the embedder's IP / Referer / TLS "
            "fingerprint to the partner host on every pageview. The "
            "real risk is typo-squat: 'fonts.googleapi.com' (missing "
            "'s') silently warms up an attacker-controlled host. "
            "Stage-2 caller checks the captured host against "
            "CDN_PRECONNECT_ALLOWLIST (extensible per-repo)."
        ),
        pattern=_PRECONNECT_LINK,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="cdn-c8-tag-manager-impossible-sri",
        name="tag-manager / analytics script (impossible-to-SRI risk-class inventory)",
        severity="HIGH",
        description=(
            "A <script src='https://(googletagmanager|google-analytics|"
            "connect.facebook.net|cdn.segment.com|static.hotjar.com|"
            "js.intercomcdn.com|cdn.amplitude.com|js.stripe.com|...)/' "
            "tag is present. SRI cannot be applied (publishers update "
            "the script body without changing the URL — Google's own "
            "docs say so). This is an INVENTORY rule — the audit "
            "decides whether the operational controls (CSP "
            "strict-dynamic + nonce, kill-switch runbook, synthetic "
            "hash monitor) are in place. The 2018 British Airways and "
            "2019 Ticketmaster MageCart attacks exploited this class."
        ),
        pattern=_TAG_MANAGER_SCRIPT,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cdn-c9-vendor-tree-no-sbom",
        name="vendored asset reference without SBOM manifest sibling",
        severity="HIGH",
        description=(
            "A reference to a vendored asset path "
            "(public/vendor/, static/vendor/, assets/vendor/, "
            "public/lib/, wwwroot/lib/, dist/vendor/) appears in the "
            "source. The detector's stage-2 walks the directory and "
            "fires the finding when NO sibling SBOM manifest is "
            "present (cyclonedx.json / sbom.json / VENDOR.md / "
            "THIRD_PARTY_NOTICES.md / vendor-manifest.{json,yaml,toml}). "
            "Without an SBOM, CVE-tracking against vendored bytes is "
            "impossible."
        ),
        pattern=_VENDOR_DIR_REFERENCE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="cdn-c10-registry-non-canonical",
        name=".npmrc / .yarnrc.yml / pip.conf registry= points at non-canonical host",
        severity="CRITICAL",
        description=(
            "A registry= / npmRegistryServer: / index-url = / "
            "extra-index-url = line in package-manager config points "
            "at a host that is NOT the canonical npm / yarn / pypi / "
            "crates.io / GitHub Packages endpoint. Every install "
            "afterwards fetches from that 3rd-party server — a "
            "malicious mirror can serve typosquats, swap popular "
            "packages, or simply log the dependency graph. Stage-2 "
            "checks an organization allowlist; legitimate cases (China "
            "mirror, internal Verdaccio uplink) document the host."
        ),
        pattern=_REGISTRY_NON_CANONICAL,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="cdn-c11-pnpm-hoisted-linker",
        name="pnpm node-linker: hoisted (declared-vs-installed dependency drift)",
        severity="HIGH",
        description=(
            "A .npmrc / pnpm-workspace.yaml / .pnpmrc declares "
            "node-linker = hoisted (or yaml `node-linker: hoisted`). "
            "pnpm's default is `isolated`: each package can ONLY "
            "import dependencies it declared in its own package.json. "
            "Hoisted mode reverts to flat npm-style layout where "
            "transitive deps are reachable without declaration — the "
            "2024 npm 'shadow dependency' research exploited exactly "
            "this misconfiguration. Stage-2 confirms the repo uses "
            "pnpm (pnpm-lock.yaml present)."
        ),
        pattern=_PNPM_HOISTED_LINKER,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="cdn-c12-mixed-content-http",
        name="<script>/<link>/<img>/<iframe> over HTTP (mixed-content)",
        severity="CRITICAL",
        description=(
            "An HTML tag's src= / href= / data= uses HTTP (not HTTPS) "
            "to a non-localhost / non-private-IP host. Active mixed "
            "content (script, link, iframe) is MITM-trivially "
            "exploitable; passive mixed content (img, video) is "
            "fingerprint-leaks + Referer-leaks at minimum. CSP "
            "upgrade-insecure-requests rewrites every HTTP URL to "
            "HTTPS at fetch time — single-line fix. Stage-2 confirms "
            "no CSP upgrade-insecure-requests directive is set."
        ),
        pattern=_MIXED_CONTENT_HTTP,
        owasp_asi="ASI-02",
    ),
)


# ---- Stage-2 helpers exported -------------------------------------------


def has_strong_sri_on_tag(tag: str) -> bool:
    """Stage-2: does the matched HTML tag carry sha384 or sha512 SRI?

    The detector uses this on the matched_text of a
    ``cdn-c2-preload-no-sri`` finding to drop false positives — a
    preload tag with sha384/sha512 SRI is correct, not a finding.
    """
    return _PRELOAD_TAG_HAS_STRONG_SRI.search(tag) is not None


def iframe_has_srcdoc(tag: str) -> bool:
    """Stage-2: does the matched <iframe> tag carry srcdoc= (inline HTML)?

    The detector uses this on the matched_text of a
    ``cdn-c3-iframe-sandbox-escape`` finding to drop false positives —
    a sandbox with srcdoc has no cross-origin attack surface.
    """
    return _IFRAME_HAS_SRCDOC.search(tag) is not None


def iframe_has_referrerpolicy(tag: str) -> bool:
    """Stage-2: does the matched <iframe> tag carry referrerpolicy=?

    The detector uses this on the matched_text of a
    ``cdn-c4-iframe-referrer-leak`` finding to drop false positives —
    a tag with referrerpolicy= is configured, not a finding.
    """
    return _IFRAME_HAS_REFERRERPOLICY.search(tag) is not None


def is_canonical_registry_host(host: str) -> bool:
    """Stage-2: is ``host`` one of the canonical package-registry hosts?

    Used by the detector to drop ``cdn-c10-registry-non-canonical``
    findings whose captured host is the canonical npm / yarn / pypi /
    crates.io / GitHub Packages endpoint.
    """
    return host.lower() in CANONICAL_REGISTRY_HOSTS


def is_preconnect_allowlisted(host: str) -> bool:
    """Stage-2: is ``host`` in the default preconnect allowlist?

    Used by the detector to drop ``cdn-c7-preconnect-rogue-host``
    findings whose captured host is a known public CDN.
    """
    return host.lower() in CDN_PRECONNECT_ALLOWLIST


def has_upgrade_insecure_requests(block: str) -> bool:
    """Stage-2: does the surrounding HTML carry the
    ``upgrade-insecure-requests`` CSP directive?

    The detector passes a window of source around the matched
    mixed-content tag. If the CSP rewrites HTTP to HTTPS, the finding
    is downgraded.
    """
    return _HAS_UPGRADE_INSECURE_REQUESTS.search(block) is not None


def has_sw_same_origin_template(text: str) -> bool:
    """Stage-2: does ``text`` contain an importScripts(...) call whose
    URL is built from ``self.location.origin`` / ``location.origin``?

    The detector uses this to drop ``cdn-c5-sw-importscripts-cross-origin``
    findings when the URL is dynamically pinned to same-origin.
    """
    return _SW_IMPORTSCRIPTS_SAME_ORIGIN_TEMPLATE.search(text) is not None


# ---- Composed scanner ---------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against ``text`` and return findings.

    Findings are deduped by ``(rule_id, line, col)``: the same rule
    firing twice on the same line emits one finding, but different
    rules on the same line emit independent findings.

    Stage-1.5 refinements applied inline (cheap second-pass tag
    inspections that the engine can't express as one regex):

      * ``cdn-c2-preload-no-sri`` — drop the finding when the matched
        tag actually carries sha384 or sha512 SRI.
      * ``cdn-c3-iframe-sandbox-escape`` — drop the finding when the
        matched iframe carries ``srcdoc=`` (inline HTML).
      * ``cdn-c4-iframe-referrer-leak`` — drop the finding when the
        matched iframe carries ``referrerpolicy=``.

    The remaining stage-2 contextual gates documented in the module
    docstring (organization registry allowlist for C-10, vendor SBOM
    presence for C-9, repo-uses-pnpm for C-11, surrounding CSP for
    C-12) are the caller's responsibility — they require filesystem
    or cross-file information the scanner does not have.

    Findings are sorted by ``(line, column, rule_id)`` so output is
    reproducible across Python versions.
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
            matched = m.group(0)
            # Stage-1.5 refinements.
            if rule.id == "cdn-c2-preload-no-sri":
                if has_strong_sri_on_tag(matched):
                    continue
            elif rule.id == "cdn-c3-iframe-sandbox-escape":
                if iframe_has_srcdoc(matched):
                    continue
            elif rule.id == "cdn-c4-iframe-referrer-leak":
                if iframe_has_referrerpolicy(matched):
                    continue
            seen.add(key)
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
