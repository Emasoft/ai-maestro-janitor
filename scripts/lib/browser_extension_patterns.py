"""Browser-extension manifest tampering and CSP / frame-ancestry attack detectors.

Wave 18 impl-J — distillation of 16 proposals from
``reports/distill-round-4/browser-extension-manifest.md`` into deterministic
regex rules covering the Chrome / Edge / Firefox MV2 + MV3 manifest layer.

Companion to ``scripts/lib/frontend_patterns.py`` (Wave 17) which covers
in-page React/Vue/Angular/Svelte XSS. The patterns here are
NON-OVERLAPPING — they target the extension-host layer specifically:

  * Blanket ``<all_urls>`` host_permissions / content_scripts.matches.
  * ``run_at: document_start`` + broad content-script injection.
  * Dangerous-permission clusters (webRequestBlocking, cookies, debugger,
    history, nativeMessaging, desktopCapture, proxy, management, ...).
  * ``optional_permissions`` blanket pre-approval.
  * ``externally_connectable.matches: <all_urls>`` (universal-XSS amp).
  * ``web_accessible_resources`` with broad ``matches``.
  * MV3 CSP regression to ``unsafe-eval`` / remote ``script-src`` host.
  * ``update_url`` pointing at non-Chrome-Web-Store host.
  * ``nativeMessaging`` + native-host manifest pointing into user-writable
    paths (``/tmp/``, ``~/.cache/``, ``~/Downloads/``).
  * ``declarativeNetRequest`` rules rewriting Authorization / Cookie /
    Set-Cookie / X-Auth-Token / X-Api-Key request headers.
  * ``omnibox.keyword`` URL-bar keylogger AND
    ``chrome_url_overrides.newtab/history/bookmarks`` browser-surface hijack.
  * ``chrome_settings_overrides.search_provider`` hijack.
  * ``sandbox.pages`` declared without a ``frame-ancestors`` directive on
    the sandbox CSP.
  * ``content_scripts.world: "MAIN"`` (page-world script injection).
  * Service-worker ``importScripts("https://...")`` / dynamic ``import()``
    / fetch-then-eval from off-store host.
  * ``incognito: "spanning"`` + broad host permissions (defeats incognito
    privacy expectation).

Architecture mirrors ``scripts/lib/frontend_patterns.py``:

  * ``Rule(id, name, severity, description, pattern, owasp_asi)``
                                  — single rule record. Patterns are
                                    pre-compiled at module load.
  * ``RULES``                     — ordered tuple of every catalogued rule.
  * ``scan_text(text)`` -> list[Finding]
                                  — run every rule, return findings.
  * ``Finding(rule_id, line, column, matched_text, severity,
              description, owasp_asi)``
                                  — single finding record.

Pure-stdlib (re, NamedTuple) so the module loads under PEP 723 script
blocks without third-party deps.

**RE2 safety:** every regex uses bounded character classes / bounded
non-greedy quantifiers AND avoids overlapping alternations on
unbounded spans. The ``[^\\]]*`` / ``[^}]*`` idiom bounds matches to
the surrounding JSON array / object — these character classes are
constant-time-per-character in any DFA engine. Catastrophic-backtracking
shapes (e.g. ``(a+)+``) are absent by construction. Lookaheads are
constant-character-class only where used. Patterns compile under both
the CPython ``re`` engine and the more restrictive ``re2`` /
``regex`` engines.

**Discovery convention:** scanners should identify extension manifests
by (a) filename is exactly ``manifest.json`` AND (b) the top-level
parsed JSON contains a ``manifest_version`` key with value 2 or 3.
Auxiliary scanners apply to native-messaging-host JSON, ruleset JSON
referenced by ``declarative_net_request.rule_resources``, and the
extension's background service-worker JS file(s).

Severity strings: ``CRITICAL``, ``HIGH``, ``MEDIUM``, ``LOW`` —
matching the existing janitor sentinel/zizmor convention. The mapping
from the source report's severity is direct, with one normalization:
the report's ``MAJOR`` tier collapses to ``MEDIUM`` since this module
uses the same four-tier scheme as ``frontend_patterns.py``.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    ``scripts/lib/frontend_patterns.Finding`` so the heartbeat
    detectors and SARIF emitter can render either kind uniformly."""

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
    """Compile a pattern with MULTILINE+UNICODE.

    Unlike ``frontend_patterns._re`` this does NOT set ``IGNORECASE``.
    Manifest keys (``host_permissions``, ``manifest_version``, etc.)
    are case-sensitive per the Chromium / Mozilla spec — Chrome
    silently ignores typo-cased keys, so a case-insensitive match
    would generate false positives on documentation that quotes
    the key in a sentence. Header-name comparisons inside DNR rules
    intentionally use ``(?i:...)`` inline to be case-insensitive
    where the spec mandates that behaviour.

    MULTILINE makes ``^`` / ``$`` line-anchored, which is what we
    want for JSON pretty-printed across many lines.

    UNICODE is the default in Python 3 but stated explicitly so the
    behaviour is identical on every platform the doctor runs on.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- Rule 1: host_permissions: ["<all_urls>"] blanket scope -------------


# Match ``"host_permissions"`` followed by an array containing the
# literal ``"<all_urls>"`` entry. The ``[^\]]*`` bound keeps the
# match constant-time per character and prevents the engine from
# straying past the closing ``]`` into a sibling key. The same
# pattern is reused for the legacy MV2 ``"permissions"`` array
# below.
_HOST_PERMISSIONS_ALL_URLS = _re(
    r'"host_permissions"\s*:\s*\[[^\]]*"<all_urls>"'
)


# Wildcarded host pattern that is equivalent to ``<all_urls>``:
#   ``"https://*/*"`` / ``"http://*/*"`` / ``"*://*/*"``
# All three reach every URL in the user's browsing.
_HOST_PERMISSIONS_WILDCARD = _re(
    r'"host_permissions"\s*:\s*\[[^\]]*"(?:https?|\*)://\*/\*"'
)


# Legacy MV2 ``"permissions": ["<all_urls>"]`` — same blanket intent.
# Note: in MV3 ``permissions`` carries API permissions only, NOT host
# patterns, so this regex specifically catches the MV2 shape.
_MV2_PERMISSIONS_ALL_URLS = _re(
    r'"permissions"\s*:\s*\[[^\]]*"<all_urls>"'
)


# ---- Rule 2: content_scripts <all_urls> + run_at document_start ---------


# Composite match: a content_scripts entry with
# ``matches: [..., "<all_urls>", ...]`` AND
# ``run_at: "document_start"``. The ``[\s\S]`` character class is
# RE2-safe and matches across newlines without enabling DOTALL
# (which would break ``^``/``$`` semantics for sibling rules). The
# bounded ``{0,400}?`` window keeps the engine from straying past
# the closing brace of the content_scripts entry.
_CONTENT_SCRIPTS_BROAD_EARLY = _re(
    r'"content_scripts"\s*:\s*\[\s*\{'
    r'[\s\S]{0,800}?'
    r'"matches"\s*:\s*\[[^\]]*"<all_urls>"'
    r'[\s\S]{0,400}?'
    r'"run_at"\s*:\s*"document_start"'
)


# Reverse-order variant: ``run_at`` BEFORE ``matches``. JSON keys
# are unordered so both forms occur in the wild.
_CONTENT_SCRIPTS_BROAD_EARLY_REV = _re(
    r'"content_scripts"\s*:\s*\[\s*\{'
    r'[\s\S]{0,400}?'
    r'"run_at"\s*:\s*"document_start"'
    r'[\s\S]{0,800}?'
    r'"matches"\s*:\s*\[[^\]]*"<all_urls>"'
)


# ---- Rule 3: dangerous permissions cluster ------------------------------


# Single dangerous permission tokens we flag — see the
# DANGEROUS_EXT_PERMS frozenset below for the policy list. The regex
# matches one occurrence of any of these names inside a JSON
# permissions array. The caller composes the cluster-count by
# running ``finditer`` and counting unique permission names; the
# rule fires when ANY dangerous permission appears so the audit
# surfaces every single one for review.
_DANGEROUS_PERMISSION_TOKEN = _re(
    r'"(?:webRequestBlocking|cookies|debugger|history|'
    r'clipboardRead|clipboardWrite|nativeMessaging|'
    r'desktopCapture|tabCapture|proxy|privacy|management)"'
)


# ---- Rule 4: optional_permissions blanket pre-approval ------------------


# Match ``"optional_permissions"`` followed by an array containing
# any of the dangerous escalation tokens. The deferred-ambush attack
# uses these as "ask once at runtime" then escalates silently.
_OPTIONAL_PERMS_DANGEROUS = _re(
    r'"optional_permissions"\s*:\s*\[[^\]]*'
    r'"(?:<all_urls>|nativeMessaging|debugger|desktopCapture|'
    r'management|proxy|webRequest|webRequestBlocking|'
    r'tabCapture|cookies|history)"'
)


# Companion source-code pattern: ``chrome.permissions.request(``
# call. When BOTH the manifest carries dangerous
# optional_permissions AND a JS file invokes
# ``chrome.permissions.request(...)``, the deferred-escalation is
# wired up and the finding upgrades to CRITICAL. The caller is
# responsible for the two-file gate.
_CHROME_PERMISSIONS_REQUEST_CALL = _re(
    r'\bchrome\.permissions\.request\s*\('
)


# ---- Rule 5: externally_connectable.matches: <all_urls> -----------------


# An extension that accepts runtime messages from ANY web page is
# effectively a universal-XSS amplifier — any XSS on any site can
# drive the extension's full permission set. Variants:
#   - "<all_urls>"
#   - "https://*/*"   "http://*/*"
#   - "*://*/*"
_EXTERNALLY_CONNECTABLE_WILD = _re(
    r'"externally_connectable"\s*:\s*\{[^}]*"matches"\s*:\s*\[[^\]]*'
    r'"(?:<all_urls>|https?://\*/\*|\*://\*/\*)"'
)


# Companion source-code pattern: an unguarded
# ``chrome.runtime.onMessageExternal.addListener(...)`` handler
# (i.e. the handler does not check ``sender.id`` / ``sender.url``
# against an allowlist). The caller is responsible for the
# allowlist-check verification; this regex just locates the handler.
_RUNTIME_ON_MESSAGE_EXTERNAL = _re(
    r'\bchrome\.runtime\.onMessageExternal\.addListener\s*\('
)


# ---- Rule 6: web_accessible_resources with broad matches ---------------


# Two forms — MV2 (flat array of paths) and MV3 (array of objects
# with ``resources`` and ``matches``). The MV2 form fires when any
# entry is ``"*"``; the MV3 form fires when ``resources`` contains
# ``"*"`` AND ``matches`` contains ``"<all_urls>"``.
#
# MV2 form: ``"web_accessible_resources": ["*", "popup.html"]``.
_WEB_ACCESSIBLE_RESOURCES_MV2 = _re(
    r'"web_accessible_resources"\s*:\s*\[[^\]]*"\*"[^\]]*\]'
)


# MV3 form: ``"web_accessible_resources": [{ "resources": ["*"],
# "matches": ["<all_urls>"] }]``. Two orderings (resources first,
# matches first) are possible.
_WEB_ACCESSIBLE_RESOURCES_MV3 = _re(
    r'"web_accessible_resources"\s*:\s*\[\s*\{'
    r'[\s\S]{0,400}?'
    r'"resources"\s*:\s*\[[^\]]*"\*"[^\]]*\]'
    r'[\s\S]{0,400}?'
    r'"matches"\s*:\s*\[[^\]]*"<all_urls>"'
)


_WEB_ACCESSIBLE_RESOURCES_MV3_REV = _re(
    r'"web_accessible_resources"\s*:\s*\[\s*\{'
    r'[\s\S]{0,400}?'
    r'"matches"\s*:\s*\[[^\]]*"<all_urls>"'
    r'[\s\S]{0,400}?'
    r'"resources"\s*:\s*\[[^\]]*"\*"[^\]]*\]'
)


# ---- Rule 7: content_security_policy regression -------------------------


# MV3 forbids ``'unsafe-eval'`` and ``'unsafe-inline'`` in the
# extension's CSP by default. A manifest that puts them back is
# either shipping packed/obfuscated payloads OR shipping trojan
# code that needs runtime eval. Also: external ``script-src`` host
# lets the extension pull live updates bypassing the Chrome Web
# Store review.
#
# Match either the MV2 string form (``"content_security_policy":
# "script-src 'self' 'unsafe-eval' ..."``) or the MV3 object form
# (``"content_security_policy": { "extension_pages": "script-src
# 'self' 'unsafe-eval' ..." }``).
#
# Bounded ``[\s\S]{0,400}?`` is RE2-safe and prevents the engine
# from straying past the closing brace/quote of the CSP value.
_EXT_CSP_UNSAFE_EVAL = _re(
    r'"content_security_policy"\s*:\s*'
    r'(?:"|\{[\s\S]{0,200}?"extension_pages"\s*:\s*")'
    r'[^"]*'
    r"(?:'unsafe-eval'|'unsafe-inline')"
)


# Tighter form: remote ``script-src`` host (``https://...``,
# ``http://...``, or wildcard subdomain ``*.cdn.tld``) inside a
# CSP directive. Matches the whole ``script-src`` segment up to
# the next ``;`` or closing quote.
_EXT_CSP_REMOTE_SCRIPT_SRC = _re(
    r'"content_security_policy"\s*:\s*'
    r'(?:"|\{[\s\S]{0,200}?"extension_pages"\s*:\s*")'
    r'[^"]*script-src[^";]*'
    r'(?:https?://[a-zA-Z0-9.-]+|\*\.[a-zA-Z0-9.-]+)'
)


# ---- Rule 8: rogue update_url -------------------------------------------


# Chromium / Firefox / Edge / Opera all use known update hosts.
# Any other host on the ``update_url`` field means the extension
# fetches updates from attacker-controlled infrastructure — review,
# signing, and Chrome-Web-Store kill-switch are all bypassed.
#
# The regex captures the host portion for the caller to compare
# against ``LEGIT_UPDATE_HOSTS``. ``LEGIT_UPDATE_HOSTS`` is a
# frozenset so the membership check is O(1); subdomain spoofs
# (``clients2.google.com.attacker.tld``) fail the strict equality.
_UPDATE_URL_HOST = _re(
    r'"update_url"\s*:\s*"https?://([a-zA-Z0-9.-]+)'
)


# Policy frozenset — the only legitimate auto-update hosts.
LEGIT_UPDATE_HOSTS: frozenset[str] = frozenset({
    "clients2.google.com",  # Chrome Web Store
    "edge.microsoft.com",   # Edge Add-ons
    "addons.mozilla.org",   # Firefox / Thunderbird
    "addons.opera.com",     # Opera
})


# ---- Rule 9: nativeMessaging + suspicious native-host path -------------


# Just the permission token. The extension-manifest fire alone is
# HIGH ("review-required") because legitimate uses exist (password
# managers, screenshot tools). The CRITICAL upgrade comes from the
# companion native-host-manifest scan below.
_NATIVE_MESSAGING_PERM = _re(
    r'"nativeMessaging"'
)


# Native-host manifest ``"path"`` pointing into user-writable
# directories. ``/tmp/``, ``/var/tmp/``, ``~/.cache/``,
# ``~/Downloads/``, ``~/.local/tmp/`` are all writable without
# sudo and therefore controllable by any process running as the
# user — including the extension itself.
#
# The macOS / Linux path shapes are unified by accepting both
# ``/Users/<name>/`` and ``/home/<name>/`` prefixes. Windows
# (``C:\Users\<name>\AppData\Local\Temp\``) follows the same idea
# with backslash separators.
_NATIVE_HOST_PATH_SUSPICIOUS = _re(
    r'"path"\s*:\s*"'
    r'(?:'
    r'/tmp/|/var/tmp/'
    r'|/?Users/[^"/]+/Downloads/'
    r'|/?Users/[^"/]+/\.cache/'
    r'|/?home/[^"/]+/\.cache/'
    r'|/?home/[^"/]+/Downloads/'
    r'|/?home/[^"/]+/\.local/tmp/'
    r'|C:\\\\Users\\\\[^"\\\\]+\\\\AppData\\\\Local\\\\Temp\\\\'
    r')'
)


# ---- Rule 10: declarativeNetRequest header rewriting -------------------


# DNR is MV3's replacement for ``webRequestBlocking``. A trojan
# extension can rewrite ``Authorization`` / ``Cookie`` /
# ``X-Auth-Token`` etc. on outbound requests, appending the user's
# session tokens to attacker-controlled URLs.
#
# Two detection arms:
#   (a) source code: ``chrome.declarativeNetRequest.updateDynamic
#       Rules`` / ``updateSessionRules`` calls.
#   (b) rule-JSON files: ``"header": "Authorization"`` /
#       ``"Cookie"`` / ``"Set-Cookie"`` / ``"X-Auth-Token"`` /
#       ``"X-Api-Key"`` / ``"Bearer"``.
#
# Header names are case-insensitive per RFC 7230 §3.2, but the
# detection should fire on the canonical casing AND common
# mis-spellings — using ``(?i:...)`` for these specific tokens
# only.
_DNR_DYNAMIC_RULES_CALL = _re(
    r'\bchrome\.declarativeNetRequest\.update(?:Dynamic|Session)Rules\s*\('
)


_DNR_HEADER_TARGET_SENSITIVE = _re(
    r'"header"\s*:\s*'
    r'"(?i:authorization|cookie|set-cookie|'
    r'x-auth-token|x-api-key|bearer)"'
)


# Manifest-level: ``"permissions": [..., "declarativeNetRequest",
# ...]``. Combined with ``<all_urls>`` host scope this is HIGH;
# combined with a header-target match in the linked rule JSON the
# finding upgrades to CRITICAL.
_DNR_PERMISSION = _re(
    r'"permissions"\s*:\s*\[[^\]]*"declarativeNetRequest(?:WithHostAccess)?"'
)


# ---- Rule 11: omnibox + chrome_url_overrides ---------------------------


# ``omnibox.keyword`` — once the user types this keyword + space in
# the URL bar, every subsequent character is sent to
# ``chrome.omnibox.onInputChanged``. A URL-bar keylogger restricted
# to one keyword, but combined with broad host perms it is an
# escalation vector.
_OMNIBOX_KEYWORD = _re(
    r'"omnibox"\s*:\s*\{[^}]*"keyword"'
)


# ``chrome_url_overrides.newtab / history / bookmarks`` —
# replaces the browser's own new-tab / bookmarks / history page
# with an extension HTML page. The textbook ad-injecting new-tab
# hijack family lives here.
_CHROME_URL_OVERRIDES = _re(
    r'"chrome_url_overrides"\s*:\s*\{[^}]*'
    r'"(?:newtab|history|bookmarks)"'
)


# ---- Rule 12: chrome_settings_overrides.search_provider ----------------


# Lets the extension change the user's default search engine. The
# typical malicious shape pairs an unknown ``search_url`` host with
# an affiliate query parameter (``aff=``, ``ref=``, ``partner=``,
# ``tag=``). The pattern captures the presence of the override;
# severity is upgraded by the caller when the URL host is not in
# the legitimate-search-provider allowlist.
_SEARCH_PROVIDER_OVERRIDE = _re(
    r'"chrome_settings_overrides"\s*:\s*\{[\s\S]{0,800}?"search_provider"'
)


# Affiliate-style query-parameter marker inside any
# ``"search_url"`` template. Combined with the override above this
# is the CRITICAL "monetised redirect" shape.
_SEARCH_PROVIDER_AFFILIATE_PARAM = _re(
    r'"search_url"\s*:\s*"[^"]*'
    r'(?:[?&](?:aff|ref|partner|tag|utm_source)=)'
)


# Policy frozenset — recognised search-provider hosts. The audit
# allowlists these; anything else gets escalated.
LEGIT_SEARCH_HOSTS: frozenset[str] = frozenset({
    "google.com", "www.google.com",
    "bing.com", "www.bing.com",
    "duckduckgo.com",
    "qwant.com",
    "kagi.com",
    "search.brave.com", "brave.com",
    "ecosia.org",
    "startpage.com",
})


# ---- Rule 13: sandbox iframe injection (composite) ---------------------


# ``sandbox.pages`` runs listed pages with extension privileges
# removed — useful for safely running untrusted HTML. But if the
# manifest ALSO declares ``web_accessible_resources`` over the same
# pages, ANY web page can iframe the sandboxed page. If the sandbox
# CSP also omits a ``frame-ancestors`` directive, the iframe is
# universally embeddable and the postMessage bridge becomes a
# bidirectional attack channel.
#
# This is a composite detection — handled by
# ``scan_sandbox_iframe_injection`` below — but we expose component
# regexes for the unit tests AND for callers that want piecewise
# evidence.
_SANDBOX_PAGES = _re(
    r'"sandbox"\s*:\s*\{[\s\S]{0,400}?"pages"\s*:\s*\[([^\]]*)\]'
)


_SANDBOX_CSP = _re(
    r'"sandbox"\s*:\s*\{[\s\S]{0,800}?"content_security_policy"\s*:\s*"([^"]*)"'
)


# Generic "list every quoted string in a JSON array" matcher,
# used to extract the page list from the sandbox.pages array.
_QUOTED_ITEM = _re(r'"([^"]+)"')


def scan_sandbox_iframe_injection(manifest_text: str) -> list[str]:
    """Composite scan for the sandbox-iframe-universal-embed attack.

    Returns a list of marker strings (zero or more) describing the
    nature of the finding:

      * ``"sandbox-iframe-universal-embed"`` — sandbox.pages is also
        web-accessible AND the sandbox CSP lacks a frame-ancestors
        directive.
      * ``"sandbox-iframe-permissive-ancestors"`` — frame-ancestors
        is present but allows anything other than ``'none'`` or
        ``'self'``.
      * ``"sandbox-iframe-with-unsafe-eval"`` — sandbox CSP also
        carries ``'unsafe-eval'`` (the embed becomes an
        arbitrary-code-execution vector).

    The caller wraps each marker into a Finding via the regex-based
    pipeline; this function exists because the underlying logic is
    cross-key and a single regex cannot express it without
    catastrophic-backtracking risk.
    """
    if not manifest_text:
        return []

    findings: list[str] = []
    sandbox_pages_match = _SANDBOX_PAGES.search(manifest_text)
    if not sandbox_pages_match:
        return findings

    sandbox_page_names = set(_QUOTED_ITEM.findall(sandbox_pages_match.group(1)))
    if not sandbox_page_names:
        return findings

    # Now look for web_accessible_resources entries that name any of
    # the sandbox pages. Both MV2 (flat array of paths) and MV3
    # (object form) shapes must be considered.
    war_mv2_match = re.search(
        r'"web_accessible_resources"\s*:\s*\[\s*"([^]]*)\]',
        manifest_text,
    )
    war_mv3_match = re.search(
        r'"web_accessible_resources"\s*:\s*\[\s*\{[\s\S]{0,400}?'
        r'"resources"\s*:\s*\[([^\]]*)\]',
        manifest_text,
    )

    war_names: set[str] = set()
    if war_mv2_match:
        war_names.update(_QUOTED_ITEM.findall(war_mv2_match.group(1)))
    if war_mv3_match:
        war_names.update(_QUOTED_ITEM.findall(war_mv3_match.group(1)))

    # Wildcard resource entries cover every sandbox page.
    if "*" in war_names or sandbox_page_names & war_names:
        sandbox_csp_match = _SANDBOX_CSP.search(manifest_text)
        csp = sandbox_csp_match.group(1) if sandbox_csp_match else ""
        if "frame-ancestors" not in csp:
            findings.append("sandbox-iframe-universal-embed")
        elif (
            "frame-ancestors 'none'" not in csp
            and "frame-ancestors 'self'" not in csp
        ):
            findings.append("sandbox-iframe-permissive-ancestors")
        if "'unsafe-eval'" in csp:
            findings.append("sandbox-iframe-with-unsafe-eval")
    return findings


# ---- Rule 14: content_scripts world: "MAIN" ----------------------------


# MV3 ``world: "MAIN"`` makes the content script execute in the
# PAGE's JavaScript world rather than the isolated extension world.
# The script then has direct access to page globals, can override
# ``fetch`` / ``XMLHttpRequest`` / ``localStorage`` and read every
# page-defined variable. The Cyberhaven Dec-2024 trojan used this
# combination (plus document_start + <all_urls>).
_CONTENT_SCRIPT_MAIN_WORLD = _re(
    r'"content_scripts"\s*:\s*\['
    r'[\s\S]{0,1200}?'
    r'"world"\s*:\s*"MAIN"'
)


# ---- Rule 15: service-worker remote importScripts / dynamic import -----


# Service-worker JS files that fetch remote code at runtime.
# Chrome Web Store explicitly forbids remotely-hosted code, but
# side-loaded / enterprise-policy-installed extensions skip that
# check. Three variants:
#   - importScripts("https://...")
#   - import("https://...")
#   - fetch("https://...").then(r => r.text()).then(eval)
#
# Localhost / 127.0.0.1 are excluded because they appear in dev
# fixtures. The non-capturing alternation
# ``(?:localhost|127\.0\.0\.1)`` is constant-time.
_SW_REMOTE_IMPORT_SCRIPTS = _re(
    r'\bimportScripts\s*\(\s*["\']https?://'
    r'(?!localhost|127\.0\.0\.1)'
)


_SW_REMOTE_DYNAMIC_IMPORT = _re(
    r'\bimport\s*\(\s*["\']https?://'
    r'(?!localhost|127\.0\.0\.1)'
)


# fetch(...).then(...).then(eval) — a 400-character window
# tolerates one transformer between fetch and the eval sink.
_SW_FETCH_THEN_EVAL = _re(
    r'\bfetch\s*\([^)]*\)'
    r'[\s\S]{0,400}?\.then\s*\([^)]*\)'
    r'[\s\S]{0,400}?\beval\b'
)


# ---- Rule 16: incognito: "spanning" + broad host permissions ----------


# The default for ``incognito`` is ``"spanning"`` which means the
# same extension service worker runs across BOTH normal and
# incognito profiles. Combined with broad host perms, it defeats
# the user's incognito-mode privacy expectation. The safe choices
# are ``"split"`` (per-profile state) or ``"not_allowed"`` (disabled
# in incognito).
#
# The explicit-spanning shape:
_INCOGNITO_SPANNING = _re(
    r'"incognito"\s*:\s*"spanning"'
)


# ---- Policy data --------------------------------------------------------


# Dangerous-permission policy frozenset — exported for callers that
# want to compose their own multi-key gates. Keep this list in sync
# with ``_DANGEROUS_PERMISSION_TOKEN`` above.
DANGEROUS_EXT_PERMS: frozenset[str] = frozenset({
    "webRequestBlocking",
    "cookies",
    "debugger",
    "history",
    "clipboardRead",
    "clipboardWrite",
    "nativeMessaging",
    "desktopCapture",
    "tabCapture",
    "proxy",
    "privacy",
    "management",
})


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    # ---- Tier-1 (CRITICAL) -------------------------------------------
    Rule(
        id="ext-host-permissions-all-urls",
        name="Extension manifest declares host_permissions: <all_urls>",
        severity="CRITICAL",
        description=(
            "Manifest V3 extension requests host_permissions: "
            "[\"<all_urls>\"]. Once granted, the extension can inject "
            "scripts and read/write requests on every site the user "
            "visits — bank pages, webmail, cloud consoles. Cyberhaven "
            "Dec-2024 and DataSpii 2019 are the canonical incidents."
        ),
        pattern=_HOST_PERMISSIONS_ALL_URLS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-host-permissions-wildcard",
        name="Extension manifest declares wildcarded host_permissions",
        severity="CRITICAL",
        description=(
            "host_permissions contains \"https://*/*\", \"http://*/*\", "
            "or \"*://*/*\" — all three reach every URL in the user's "
            "browsing. Functionally equivalent to <all_urls>."
        ),
        pattern=_HOST_PERMISSIONS_WILDCARD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-mv2-permissions-all-urls",
        name="MV2 extension declares permissions: <all_urls>",
        severity="CRITICAL",
        description=(
            "Legacy Manifest V2 carries host patterns inside the "
            "\"permissions\" array. \"<all_urls>\" there has the same "
            "blanket reach as the MV3 host_permissions equivalent."
        ),
        pattern=_MV2_PERMISSIONS_ALL_URLS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-content-script-broad-early-injection",
        name="content_scripts <all_urls> + run_at document_start",
        severity="CRITICAL",
        description=(
            "Content script targets every URL AND runs before the "
            "page's own scripts. Canonical recipe for credential "
            "keylogging, form sniffing, and CSP bypass — the content "
            "script runs in the extension's isolated world with "
            "extension-CSP, not page-CSP. Honey-extension affiliate-"
            "overwrite trojan and the Sign-In-with-Google trojan "
            "cluster (Dec-2024) shipped this exact shape."
        ),
        pattern=_CONTENT_SCRIPTS_BROAD_EARLY,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-content-script-broad-early-injection-rev",
        name="content_scripts run_at document_start + <all_urls> (reverse key order)",
        severity="CRITICAL",
        description=(
            "Same shape as ext-content-script-broad-early-injection "
            "but the JSON object lists run_at before matches. JSON "
            "keys are unordered so both shapes occur in the wild."
        ),
        pattern=_CONTENT_SCRIPTS_BROAD_EARLY_REV,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-externally-connectable-wildcard",
        name="externally_connectable.matches: <all_urls> / wildcard",
        severity="CRITICAL",
        description=(
            "Any web page can send runtime messages to the extension. "
            "Combined with a permissive onMessageExternal handler, a "
            "single XSS on any site drives the extension's full "
            "permission set — a universal-XSS amplifier."
        ),
        pattern=_EXTERNALLY_CONNECTABLE_WILD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-csp-unsafe-eval",
        name="Extension CSP regression — 'unsafe-eval' / 'unsafe-inline'",
        severity="CRITICAL",
        description=(
            "MV3 forbids 'unsafe-eval' and 'unsafe-inline' in the "
            "extension's CSP by default. Putting them back is a sign "
            "of packed/obfuscated payloads OR runtime-eval trojan "
            "code. Google's own MV3 docs flag this as the highest-"
            "priority review item."
        ),
        pattern=_EXT_CSP_UNSAFE_EVAL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-csp-remote-script-src",
        name="Extension CSP allows remote script-src host",
        severity="CRITICAL",
        description=(
            "An extension CSP that includes an external https:// "
            "host (or *.subdomain.tld) in script-src lets the "
            "extension pull live updates BYPASSING Chrome Web Store "
            "review. Same threat as a rogue update_url."
        ),
        pattern=_EXT_CSP_REMOTE_SCRIPT_SRC,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-sw-remote-import-scripts",
        name="Service worker importScripts() from remote host",
        severity="CRITICAL",
        description=(
            "Background service worker calls importScripts(\"https://"
            "...\") — fetches code at runtime OUTSIDE the Chrome Web "
            "Store review. The published code is innocuous; the "
            "executing code is whatever the CDN serves today. The "
            "textbook MV3 supply-chain backdoor pattern."
        ),
        pattern=_SW_REMOTE_IMPORT_SCRIPTS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ext-sw-remote-dynamic-import",
        name="Service worker dynamic import() from remote host",
        severity="CRITICAL",
        description=(
            "Dynamic import(\"https://...\") at runtime from a "
            "non-localhost host. Same stage-2 loader pattern as "
            "remote importScripts."
        ),
        pattern=_SW_REMOTE_DYNAMIC_IMPORT,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ext-sw-fetch-then-eval",
        name="Service worker fetch().then().then(eval) chain",
        severity="CRITICAL",
        description=(
            "fetch(remote-url).then(...).then(eval) — the same "
            "stage-2-loader threat as importScripts but the eval "
            "sink may be obfuscated as a .then handler. The 400-"
            "character window allows one transformer between fetch "
            "and eval."
        ),
        pattern=_SW_FETCH_THEN_EVAL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ext-dnr-header-target-sensitive",
        name="declarativeNetRequest rule rewrites Authorization / Cookie header",
        severity="CRITICAL",
        description=(
            "DNR rule's modifyHeaders action targets Authorization, "
            "Cookie, Set-Cookie, X-Auth-Token, X-Api-Key, or Bearer "
            "— the trojan extension can append the user's tokens to "
            "ANY outbound request to an attacker host."
        ),
        pattern=_DNR_HEADER_TARGET_SENSITIVE,
        owasp_asi="ASI-05",
    ),
    # ---- Tier-2 (HIGH) -----------------------------------------------
    Rule(
        id="ext-dangerous-permission",
        name="Dangerous extension permission",
        severity="HIGH",
        description=(
            "Extension declares one of webRequestBlocking, cookies, "
            "debugger, history, clipboardRead, clipboardWrite, "
            "nativeMessaging, desktopCapture, tabCapture, proxy, "
            "privacy, or management. Combined with broad host scope "
            "this becomes the session-hijacker kit (Avast \"Online "
            "Security\" 2019, Stylish 2018). Every occurrence is "
            "review-worthy."
        ),
        pattern=_DANGEROUS_PERMISSION_TOKEN,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-optional-permissions-dangerous",
        name="optional_permissions includes dangerous escalation token",
        severity="HIGH",
        description=(
            "optional_permissions are NOT installed automatically, "
            "but a single chrome.permissions.request() call at "
            "runtime grants them silently. Listing <all_urls>, "
            "nativeMessaging, debugger, etc. is the deferred-ambush "
            "pattern that passes Chrome Web Store review with a "
            "minimal install footprint."
        ),
        pattern=_OPTIONAL_PERMS_DANGEROUS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-chrome-permissions-request-call",
        name="chrome.permissions.request() call",
        severity="HIGH",
        description=(
            "Source-code call to chrome.permissions.request(...). "
            "Combined with dangerous optional_permissions in the "
            "manifest the deferred-escalation is wired up; caller "
            "should upgrade the finding to CRITICAL when both "
            "conditions hold."
        ),
        pattern=_CHROME_PERMISSIONS_REQUEST_CALL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-runtime-on-message-external",
        name="chrome.runtime.onMessageExternal.addListener handler",
        severity="HIGH",
        description=(
            "Extension exposes a runtime-message endpoint to web "
            "pages. Without an explicit allowlist check inside the "
            "handler (sender.id / sender.url), it is an open RPC "
            "bridge from any page that can connect."
        ),
        pattern=_RUNTIME_ON_MESSAGE_EXTERNAL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-war-mv2-wildcard",
        name="MV2 web_accessible_resources contains \"*\"",
        severity="HIGH",
        description=(
            "Legacy MV2 web_accessible_resources is a flat array of "
            "paths. \"*\" means every resource in the extension is "
            "loadable from arbitrary web pages — opens fingerprinting "
            "by extension-ID and exfil of embedded secrets."
        ),
        pattern=_WEB_ACCESSIBLE_RESOURCES_MV2,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-war-mv3-broad",
        name="MV3 web_accessible_resources allows <all_urls> + *",
        severity="HIGH",
        description=(
            "MV3 web_accessible_resources object has resources: "
            "[\"*\"] AND matches: [\"<all_urls>\"]. Any site can "
            "iframe extension resources, fingerprint the extension "
            "via its ID, and read embedded secrets. The iframe also "
            "inherits the extension's host_permissions for fetch() "
            "calls (USENIX 2021 WAR-fingerprinting paper)."
        ),
        pattern=_WEB_ACCESSIBLE_RESOURCES_MV3,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-war-mv3-broad-rev",
        name="MV3 web_accessible_resources allows <all_urls> + * (reverse order)",
        severity="HIGH",
        description=(
            "Same shape as ext-war-mv3-broad with matches and "
            "resources keys in reverse order."
        ),
        pattern=_WEB_ACCESSIBLE_RESOURCES_MV3_REV,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-native-messaging-permission",
        name="nativeMessaging permission declared",
        severity="HIGH",
        description=(
            "nativeMessaging lets the extension talk to a native "
            "binary registered via a Native Messaging Host manifest. "
            "Legitimate uses exist (password managers, screenshot "
            "tools), but every occurrence warrants review. The "
            "Mandiant 2023 Chinese APT browser-RAT report documents "
            "this as the canonical extension-to-OS escalation path."
        ),
        pattern=_NATIVE_MESSAGING_PERM,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-native-host-path-suspicious",
        name="Native-messaging host points into user-writable path",
        severity="CRITICAL",
        description=(
            "Native Messaging Host manifest \"path\" points to /tmp/, "
            "/var/tmp/, ~/.cache/, ~/Downloads/, ~/.local/tmp/, or "
            "%AppData%\\Local\\Temp\\ — directories writable by any "
            "user-level process. The extension can drop a binary "
            "there and execute it via the NMH bridge, turning a "
            "browser extension into a full-OS-access RAT."
        ),
        pattern=_NATIVE_HOST_PATH_SUSPICIOUS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-dnr-permission",
        name="declarativeNetRequest permission",
        severity="HIGH",
        description=(
            "Manifest declares declarativeNetRequest (or "
            "declarativeNetRequestWithHostAccess). MV3's replacement "
            "for webRequestBlocking — can rewrite request headers "
            "and redirect URLs. Combined with broad host scope, "
            "rule JSON files must be scanned for header-targets "
            "(see ext-dnr-header-target-sensitive)."
        ),
        pattern=_DNR_PERMISSION,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-dnr-dynamic-rules-call",
        name="chrome.declarativeNetRequest.updateDynamicRules() call",
        severity="HIGH",
        description=(
            "Source code installs DNR rules at runtime via "
            "updateDynamicRules / updateSessionRules. Dynamic "
            "rulesets are NOT reviewed at Chrome Web Store submission "
            "time — they can be fetched over HTTPS from a non-vetted "
            "host and applied immediately. Review the surrounding "
            "code for the ruleset source URL."
        ),
        pattern=_DNR_DYNAMIC_RULES_CALL,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-content-script-main-world",
        name="content_scripts world: \"MAIN\"",
        severity="HIGH",
        description=(
            "Content script runs in the page's own JavaScript world "
            "rather than the isolated extension world. Direct access "
            "to page globals; can override fetch/XHR/localStorage and "
            "read every page-defined variable. The Cyberhaven Dec-"
            "2024 trojan used MAIN-world + document_start + "
            "<all_urls> — the textbook three-strike."
        ),
        pattern=_CONTENT_SCRIPT_MAIN_WORLD,
        owasp_asi="ASI-05",
    ),
    # ---- Tier-3 (MEDIUM) ---------------------------------------------
    Rule(
        id="ext-omnibox-keyword",
        name="omnibox keyword handler",
        severity="MEDIUM",
        description=(
            "Extension intercepts the URL bar via an omnibox keyword "
            "handler. After the user types the keyword + space, every "
            "subsequent character is sent to onInputChanged. URL-bar "
            "keylogger restricted to one keyword; social-engineering "
            "(\"just type 'qq ' before your search\") broadens the "
            "reach."
        ),
        pattern=_OMNIBOX_KEYWORD,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-chrome-url-overrides",
        name="chrome_url_overrides hijacks newtab/history/bookmarks",
        severity="MEDIUM",
        description=(
            "Extension replaces the browser's own new-tab / history / "
            "bookmarks page with an extension HTML page. The classic "
            "ad-injecting new-tab hijack family (Awesome Screenshot "
            "and others) ships this. Combined with broad host "
            "permissions the finding upgrades to CRITICAL."
        ),
        pattern=_CHROME_URL_OVERRIDES,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-search-provider-override",
        name="chrome_settings_overrides.search_provider",
        severity="MEDIUM",
        description=(
            "Extension changes the user's default search engine. Pre-"
            "MV3 this was rampant. The malicious shape pairs an "
            "unknown search_url host with an affiliate query parameter "
            "(aff=, ref=, partner=, tag=)."
        ),
        pattern=_SEARCH_PROVIDER_OVERRIDE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-search-provider-affiliate",
        name="search_url contains affiliate parameter",
        severity="HIGH",
        description=(
            "search_url template carries an affiliate query parameter "
            "(aff=, ref=, partner=, tag=, utm_source=). Combined with "
            "the search_provider override this is the CRITICAL "
            "monetised-redirect shape — every search the user runs "
            "earns the extension author a kickback while leaking the "
            "query to a third party."
        ),
        pattern=_SEARCH_PROVIDER_AFFILIATE_PARAM,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="ext-incognito-spanning",
        name="incognito: \"spanning\" mode",
        severity="MEDIUM",
        description=(
            "Extension explicitly runs across normal AND incognito "
            "profiles. Combined with broad host perms, defeats the "
            "user's incognito-mode privacy expectation. The safe "
            "choices are \"split\" (per-profile state) or "
            "\"not_allowed\" (disabled in incognito)."
        ),
        pattern=_INCOGNITO_SPANNING,
        owasp_asi="ASI-05",
    ),
)


# ---- Composed scanner ---------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against ``text`` and return findings.

    Findings are deduped by ``(rule_id, line, col)`` — a single line
    that triggers two rules emits two findings, but the same rule
    firing twice on the same line emits one.

    The caller is responsible for the contextual gates documented at
    module top:

      * Compose the dangerous-permission CLUSTER count by running
        ``finditer`` on ``ext-dangerous-permission`` matches and
        counting unique permission names; 2+ unique = CRITICAL
        upgrade; combined with ``<all_urls>`` host scope = CRITICAL
        with a "hijacker-kit" tag.
      * Resolve ``ext-rogue-update-url`` by extracting hosts from
        ``UPDATE_URL_PATTERN`` and comparing against
        ``LEGIT_UPDATE_HOSTS``.
      * Resolve ``ext-search-provider-rogue-host`` by extracting the
        ``search_url`` host and comparing against
        ``LEGIT_SEARCH_HOSTS``.
      * The composite ``sandbox-iframe-*`` markers are produced by
        ``scan_sandbox_iframe_injection`` since the underlying check
        spans multiple JSON keys.

    Returned findings are sorted by ``(line, column, rule_id)`` so
    output is reproducible across Python versions.
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


def scan_rogue_update_urls(text: str) -> list[Finding]:
    """Extract every ``update_url`` host and emit findings for any
    host NOT in ``LEGIT_UPDATE_HOSTS``.

    Strict host equality — subdomain spoofs
    (``clients2.google.com.attacker.tld``) are correctly flagged.
    The caller composes this into the main scan_text result list."""
    if not text:
        return []
    findings: list[Finding] = []
    for m in _UPDATE_URL_HOST.finditer(text):
        host = m.group(1)
        if host in LEGIT_UPDATE_HOSTS:
            continue
        line, col = _line_col(text, m.start())
        matched = m.group(0)
        if len(matched) > 200:
            matched = matched[:200] + "…"
        findings.append(Finding(
            rule_id="ext-rogue-update-url",
            line=line,
            column=col,
            matched_text=matched,
            severity="CRITICAL",
            description=(
                f"update_url points to {host!r}, which is NOT in the "
                "known-good auto-update host allowlist (Chrome Web "
                "Store, Edge Add-ons, addons.mozilla.org, "
                "addons.opera.com). Any other host means the extension "
                "fetches updates from attacker-controlled "
                "infrastructure — review, signing, and Chrome-Web-"
                "Store kill-switch are all bypassed."
            ),
            owasp_asi="ASI-06",
        ))
    return findings


# Reusable export for downstream callers that want to enumerate
# update-url hosts without re-grepping.
UPDATE_URL_PATTERN: re.Pattern = _UPDATE_URL_HOST  # noqa: UP006
