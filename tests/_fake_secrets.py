"""Runtime-generated, NON-FUNCTIONAL secret fixtures for detector tests.

WHY THIS EXISTS
---------------
This project is a secret scanner. Its detector tests must be fed secret-shaped
inputs. If those inputs are written as literals — even *fragmented* literals
like ``"sk_" + "live_" + "51J2aVCL..."`` — a sufficiently smart scanner (one
that reconstructs string concatenation, evaluates f-strings, or flags the
high-entropy tail on its own) can still recover a realistic-looking credential
from the SOURCE. That would make this security tool's own repo trip secret
scanners (GitHub push-protection, gitleaks, GitGuardian, semantic/AI auditors).

The robust defense is to never write the realistic value as a literal at all.
Every helper here COMPUTES a realistic-but-fake value at call time from a seed.
A scanner reading the source sees only ``secret("sk_" + "live_", "psk001")`` —
a function call, not a credential. The value materializes only in memory at
runtime, where this project's own detectors receive it and fire.

WHY THE GENERATED VALUES STILL TRIGGER OUR DETECTORS
----------------------------------------------------
The bodies are high-entropy base62 (sha256-derived). They do NOT contain the
``*EXAMPLE`` / ``*TEST*`` / ``xxxx...`` shapes that
``zizmor_patterns.is_hardcoded_secret_placeholder()`` suppresses, so the
detectors treat them as real-looking leaks (which is the point of the test).
They are deterministic (stable across runs, so assertions are reproducible),
non-functional, and tied to no real account.

USAGE
-----
    from _fake_secrets import b62, hexs, secret, dsn, joinpath
    sk   = secret("sk_" + "live_", "psk001", 30)          # sk_live_<gen30>
    pat  = secret("ghp_", "ghcr-token", 36)               # ghp_<gen36>
    pg   = dsn("postgres", "rls-pg", db="appdb")          # -> a postgres:// DSN, creds generated
    jdbc = dsn("jdbc:postgresql", "iac-jdbc", port=5432)  # -> a jdbc:postgresql:// DSN, creds generated
    hook = joinpath("https://hooks." + "slack.com/services", "slack1", (9, 9, 24))
"""

from __future__ import annotations

import hashlib

_B62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 62 chars


def _stream(seed: str):
    """Infinite deterministic byte stream from a seed (chained sha256)."""
    counter = 0
    while True:
        block = hashlib.sha256(f"{seed}:{counter}".encode()).digest()
        counter += 1
        yield from block


def b62(seed: str, n: int) -> str:
    """Deterministic ``n``-char base62 string derived from ``seed``.

    High-entropy (looks like a real token body) yet reproducible. Never a
    placeholder shape, so detectors fire on it.
    """
    s = _stream(seed)
    return "".join(_B62[next(s) % 62] for _ in range(n))


def hexs(seed: str, n: int) -> str:
    """Deterministic ``n``-char lowercase-hex string derived from ``seed``."""
    s = _stream(seed)
    digits = "0123456789abcdef"
    return "".join(digits[next(s) % 16] for _ in range(n))


def secret(prefix: str, seed: str, body_len: int = 30) -> str:
    """``prefix`` + a generated base62 body.

    Pass ``prefix`` FRAGMENTED at the call site (e.g. ``"sk_" + "live_"``) so
    that not even the recognizable prefix is a contiguous literal in source.
    The body never exists as a literal — it is generated here.
    """
    return prefix + b62(seed, body_len)


def dsn(
    scheme: str,
    seed: str,
    *,
    host: str = "localhost",
    port: int | None = 5432,
    db: str = "appdb",
    user_prefix: str = "u_",
) -> str:
    """A connection string ``scheme://user:password@host[:port]/db`` whose
    credentials are generated at runtime.

    The ``scheme`` (e.g. ``"postgres"``, ``"mongodb"``, ``"jdbc:postgresql"``)
    is a plain word in source — it is not a secret on its own, and the
    credential-bearing structure ``://user:pass@host`` only exists at runtime.
    """
    user = user_prefix + b62(seed + ":user", 8)
    pw = b62(seed + ":pw", 16)
    authority = f"{host}:{port}" if port is not None else host
    return f"{scheme}://{user}:{pw}@{authority}/{db}"


def joinpath(base: str, seed: str, segs: tuple[int, ...]) -> str:
    """``base`` + ``/``-joined generated path segments — for token-in-URL
    shapes (Slack webhooks, etc.).

    Fragment any recognizable host inside ``base`` at the call site (e.g.
    ``"https://hooks." + "slack.com/services"``) so the bare host indicator is
    not a contiguous literal either; the token segments are generated here.
    """
    parts = [b62(f"{seed}:{i}", n) for i, n in enumerate(segs)]
    sep = "" if base.endswith("/") else "/"
    return base + sep + "/".join(parts)
