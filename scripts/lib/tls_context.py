"""Shared TLS-context helper: a verifying `ssl.SSLContext` that still has CAs when the
interpreter's own default store is EMPTY (TRDD-X6I04SAO). The janitor daemon runs under
whatever Python launchd was pointed at — a python.org framework build ships with
`etc/openssl/cert.pem` MISSING until its "Install Certificates.command" is run, so every
`urlopen` there died with CERTIFICATE_VERIFY_FAILED, classified as "network — benign" by
the oauth rotator and hiding a 100%-failing slot keepalive for days. Every daemon-side
https call site should use `verifying_context()` instead of `ssl.create_default_context()`.
"""

from __future__ import annotations

import os
import ssl

# Where a CA bundle lives when the interpreter's own default store is empty.
FALLBACK_CA_BUNDLES: tuple[str, ...] = (
    "/etc/ssl/cert.pem",                     # macOS system bundle
    "/etc/ssl/certs/ca-certificates.crt",    # Debian / Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",      # RHEL / Fedora
)


def verifying_context() -> ssl.SSLContext:
    """A verifying TLS context that still has CAs when the interpreter's default store is empty.

    Tries the defaults first, then `certifi` if importable, then the OS bundles above. Never
    disables verification: with no bundle anywhere the context stays empty and the request
    fails LOUDLY as `tls` — the honest outcome, and one `classify_refresh_failure` now names.
    """
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats()["x509_ca"] > 0:
        return ctx
    candidates: list[str] = []
    try:
        # `type: ignore[import-not-found]`: certifi is deliberately NOT a dependency, so the
        # checker's own env may lack it — CPV's CI pyright did, and that one unresolved import
        # was the MINOR that turned the 3.4.11 release red while the local gate (a venv that
        # happens to carry certifi) passed. Same form as zizmor_classifier's optional re2.
        import certifi  # type: ignore[import-not-found]  # noqa: PLC0415 -- optional: a python.org build gets it only once "Install Certificates.command" has run; a fresh one has neither certifi nor a bundle, which is what the OS rung below is for

        candidates.append(certifi.where())
    except ImportError:
        pass
    candidates.extend(FALLBACK_CA_BUNDLES)
    for cafile in candidates:
        if not os.path.isfile(cafile):
            continue
        try:
            ctx.load_verify_locations(cafile=cafile)
        except (ssl.SSLError, OSError):
            continue
        if ctx.cert_store_stats()["x509_ca"] > 0:
            return ctx
    return ctx
