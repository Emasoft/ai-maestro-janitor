"""Regression guard: `tls_context.verifying_context()` must still yield a CA-populated,
verifying `ssl.SSLContext` even when the interpreter's own default store is EMPTY
(TRDD-X6I04SAO) — the exact failure mode of the janitor daemon's python.org framework
Python, which shipped no `etc/openssl/cert.pem` and made every daemon-side `urlopen` die
with CERTIFICATE_VERIFY_FAILED.
"""

from __future__ import annotations

import os
import ssl
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scripts" / "lib"))

import tls_context  # noqa: E402


def test_verifying_context_has_ca_store() -> None:
    """verifying_context() returns a REQUIRED-verification context with CAs loaded."""
    ctx = tls_context.verifying_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.cert_store_stats()["x509_ca"] > 0


def test_verifying_context_falls_back_when_default_store_is_empty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """With the interpreter's default CA store empty (the daemon's failure), the fallback
    bundles still populate the context — reproducing the daemon's own empty-store case."""
    if not any(os.path.isfile(p) for p in tls_context.FALLBACK_CA_BUNDLES):
        import pytest

        pytest.skip("no fallback CA bundle present on this machine")

    def _noop_load_default_certs(self: ssl.SSLContext, *a: object, **k: object) -> None:
        return None

    monkeypatch.setattr(ssl.SSLContext, "load_default_certs", _noop_load_default_certs)
    ctx = tls_context.verifying_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.cert_store_stats()["x509_ca"] > 0
