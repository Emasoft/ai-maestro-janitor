"""Tests for scripts/lib/service_worker_patterns.py.

Pattern-coverage tests for the Wave-31 distill-round-17 service-worker
catalogue (6 ServiceWorker / SharedWorker / Web Worker security
anti-patterns). Each rule has at least two tests: one positive exercising
the canary and one negative exercising the carve-out or FP suppression.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import service_worker_patterns as swp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 6 documented rule IDs."""
    assert isinstance(swp.RULES, tuple)
    rule_ids = {r.id for r in swp.RULES}
    expected = {
        "sw-scope-no-scope-arg",
        "sw-import-scripts-dynamic-url",
        "sw-push-handler-exfil",
        "sw-clients-claim-no-guard",
        "sw-worker-from-variable-url",
        "sw-cache-put-no-status-check",
    }
    assert expected == rule_ids
    assert len(swp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in swp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = swp.Finding(
        rule_id="sw-scope-no-scope-arg",
        line=1,
        column=3,
        matched_text="navigator.serviceWorker.register('/sw.js')",
        severity="HIGH",
        description="desc",
        owasp_asi="ASI-05",
    )
    assert f.rule_id == "sw-scope-no-scope-arg"
    assert f.line == 1
    assert f.column == 3
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-05"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert swp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        "navigator.serviceWorker.register('/sw.js');\n"
        "self.clients.claim();\n"
    )
    findings = swp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[swp.Finding]:
    return [f for f in swp.scan_text(text) if f.rule_id == rule_id]


# ---------- SW-001 : sw-scope-no-scope-arg -------------------------------


def test_sw001_register_no_scope_double_quote_flags() -> None:
    """register('/sw.js') with double quotes and no scope object → HIGH hit."""
    src = 'navigator.serviceWorker.register("/sw.js");\n'
    hits = _hits("sw-scope-no-scope-arg", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_sw001_register_no_scope_single_quote_flags() -> None:
    """register('/sw.js') with single quotes and no scope object → HIGH hit."""
    src = "navigator.serviceWorker.register('/service-worker.js');\n"
    hits = _hits("sw-scope-no-scope-arg", src)
    assert hits
    assert hits[0].line == 1


def test_sw001_register_with_scope_object_silent() -> None:
    """register('/sw.js', { scope: '/app/' }) → no hit (scope argument present)."""
    src = "navigator.serviceWorker.register('/sw.js', { scope: '/app/' });\n"
    assert not _hits("sw-scope-no-scope-arg", src)


def test_sw001_workbox_register_call_silent() -> None:
    """serviceWorkerRegistration.register() call on a different object → no hit."""
    src = "serviceWorkerRegistration.register();\n"
    assert not _hits("sw-scope-no-scope-arg", src)


# ---------- SW-002 : sw-import-scripts-dynamic-url -----------------------


def test_sw002_import_scripts_concat_flags() -> None:
    """importScripts(baseUrl + '/analytics.js') → CRITICAL hit."""
    src = "importScripts(baseUrl + '/analytics.js');\n"
    hits = _hits("sw-import-scripts-dynamic-url", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_sw002_import_scripts_template_literal_flags() -> None:
    """importScripts(`https://cdn.example.com/${version}.js`) → CRITICAL hit."""
    src = "importScripts(`https://cdn.example.com/${version}/sw-helper.js`);\n"
    hits = _hits("sw-import-scripts-dynamic-url", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_sw002_import_scripts_static_url_silent() -> None:
    """importScripts('https://cdn.example.com/workbox-v7.js') → no hit."""
    src = "importScripts('https://cdn.example.com/workbox-v7.js');\n"
    assert not _hits("sw-import-scripts-dynamic-url", src)


def test_sw002_import_scripts_no_dynamic_silent() -> None:
    """importScripts('/static/polyfill.js') static path → no hit."""
    src = "importScripts('/static/polyfill.js');\n"
    assert not _hits("sw-import-scripts-dynamic-url", src)


# ---------- SW-003 : sw-push-handler-exfil --------------------------------


def test_sw003_pushsubscriptionchange_listener_flags() -> None:
    """addEventListener('pushsubscriptionchange', handler) → HIGH hit."""
    src = (
        "self.addEventListener('pushsubscriptionchange', async (event) => {\n"
        "  const sub = await self.registration.pushManager.subscribe(event.oldSubscription.options);\n"
        "  await fetch('/api/subscription', { method: 'POST', body: JSON.stringify(sub) });\n"
        "});\n"
    )
    hits = _hits("sw-push-handler-exfil", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_sw003_pushsubscriptionchange_double_quote_flags() -> None:
    """addEventListener(\"pushsubscriptionchange\", ...) double-quote form → hit."""
    src = 'self.addEventListener("pushsubscriptionchange", handler);\n'
    hits = _hits("sw-push-handler-exfil", src)
    assert hits


def test_sw003_plain_push_listener_silent() -> None:
    """addEventListener('push', handler) — not pushsubscriptionchange → no hit."""
    src = (
        "self.addEventListener('push', (event) => {\n"
        "  const data = event.data.json();\n"
        "  event.waitUntil(self.registration.showNotification(data.title, {}));\n"
        "});\n"
    )
    assert not _hits("sw-push-handler-exfil", src)


def test_sw003_unrelated_event_listener_silent() -> None:
    """addEventListener('activate', ...) → no hit."""
    src = "self.addEventListener('activate', (event) => { event.waitUntil(self.clients.claim()); });\n"
    # claim() will fire SW-004, but NOT SW-003
    assert not _hits("sw-push-handler-exfil", src)


# ---------- SW-004 : sw-clients-claim-no-guard ---------------------------


def test_sw004_self_clients_claim_flags() -> None:
    """self.clients.claim() in activate handler → HIGH hit."""
    src = (
        "self.addEventListener('activate', (event) => {\n"
        "  event.waitUntil(self.clients.claim());\n"
        "});\n"
    )
    hits = _hits("sw-clients-claim-no-guard", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_sw004_workbox_clients_claim_flags() -> None:
    """Workbox clientsClaim() at module top-level → HIGH hit."""
    src = (
        "import { clientsClaim } from 'workbox-core';\n"
        "clientsClaim();\n"
        "precacheAndRoute(self.__WB_MANIFEST);\n"
    )
    hits = _hits("sw-clients-claim-no-guard", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_sw004_no_claim_silent() -> None:
    """SW activate handler without clients.claim() → no hit."""
    src = (
        "self.addEventListener('activate', (event) => {\n"
        "  event.waitUntil(caches.keys().then(ks => Promise.all(ks.map(k => caches.delete(k)))));\n"
        "});\n"
    )
    assert not _hits("sw-clients-claim-no-guard", src)


def test_sw004_other_clients_method_silent() -> None:
    """self.clients.matchAll() is not clients.claim() → no hit."""
    src = "event.waitUntil(self.clients.matchAll().then(all => all.forEach(c => c.postMessage('updated'))));\n"
    assert not _hits("sw-clients-claim-no-guard", src)


# ---------- SW-005 : sw-worker-from-variable-url -------------------------


def test_sw005_new_worker_variable_flags() -> None:
    """new Worker(workerUrl) where workerUrl is a variable → HIGH hit."""
    src = (
        "const workerUrl = new URLSearchParams(location.search).get('worker');\n"
        "const w = new Worker(workerUrl);\n"
    )
    hits = _hits("sw-worker-from-variable-url", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_sw005_new_shared_worker_variable_flags() -> None:
    """new SharedWorker(scriptPath) variable form → HIGH hit."""
    src = "const sw = new SharedWorker(scriptPath, 'shared-analytics');\n"
    hits = _hits("sw-worker-from-variable-url", src)
    assert hits


def test_sw005_blob_worker_flags() -> None:
    """new Worker(URL.createObjectURL(blob)) → HIGH hit."""
    src = (
        "const blob = new Blob([script], { type: 'application/javascript' });\n"
        "const w = new Worker(URL.createObjectURL(blob));\n"
    )
    hits = _hits("sw-worker-from-variable-url", src)
    assert hits


def test_sw005_worker_static_string_silent() -> None:
    """new Worker('./worker.js') with a static string → no hit."""
    src = "const w = new Worker('./my-worker.js');\n"
    assert not _hits("sw-worker-from-variable-url", src)


def test_sw005_worker_static_computed_url_flags() -> None:
    """new Worker(computedUrl) where computedUrl is a plain identifier → hit."""
    src = "const computedUrl = '/workers/crypto.js';\nconst w = new Worker(computedUrl);\n"
    hits = _hits("sw-worker-from-variable-url", src)
    assert hits


# ---------- SW-006 : sw-cache-put-no-status-check ------------------------


def test_sw006_cache_put_no_ok_check_flags() -> None:
    """cache.put(req, res) without .ok check → HIGH hit."""
    src = (
        "return fetch(event.request).then(res => {\n"
        "  cache.put(event.request, res.clone());\n"
        "  return res;\n"
        "});\n"
    )
    hits = _hits("sw-cache-put-no-status-check", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_sw006_cache_put_response_no_ok_flags() -> None:
    """cache.put(req, response.clone()) without status guard → HIGH hit."""
    src = "cache.put(request, response.clone());\n"
    hits = _hits("sw-cache-put-no-status-check", src)
    assert hits


def test_sw006_cache_put_with_ok_guard_silent() -> None:
    """cache.put(...) on a line that also contains .ok → no hit (guarded)."""
    src = "if (res.ok) cache.put(event.request, res.clone());\n"
    assert not _hits("sw-cache-put-no-status-check", src)


def test_sw006_cache_put_with_status_guard_silent() -> None:
    """cache.put(...) on a line that also contains .status → no hit (guarded)."""
    src = "res.status === 200 && cache.put(event.request, res.clone());\n"
    assert not _hits("sw-cache-put-no-status-check", src)
