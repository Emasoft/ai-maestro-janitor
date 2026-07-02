"""Shared READ-ONLY account-usage gather (TRDD-OY0W6LX5).

The `window-burn-rate` detector and `/janitor-token-report --live` both need "every known
account's live `/api/oauth/usage` payload". This is that one impure glue: it drives the
OAuth rotator's read-only probes and returns `[{"label": <email-prefix>, "usage": <payload>}]`
so the two consumers share ONE gather (and the pure burn math lives in `token_burn`).

Every rotator call is wrapped — a missing rotator, a bad token, or a network error yields
fewer/zero accounts, never an exception. It NEVER writes, rotates, or mutates any credential
(no `write_*`, no `switch`, no `refresh`): read the live blob, the state index, and each
slot; probe usage; return. `rotator` is imported LAZILY so a janitor install without the
rotator (and the flag-off / not-due detector paths) never even loads it."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "oauth_rotator"))

import token_burn  # noqa: E402


def _probe(rotator: object, email: str | None, blob: dict | None, out: list[dict]) -> None:
    """Probe ONE account's usage READ-ONLY and append it to `out` on HTTP 200; skip silently
    on a missing blob, non-200 status, or any error."""
    if not blob:
        return
    try:
        status, data = rotator.usage_request(blob)  # type: ignore[attr-defined]
    except Exception:
        return
    if status == 200 and isinstance(data, dict):
        out.append({"label": token_burn.account_prefix(email), "usage": data})


def _read_slot_blob(rotator: object, email: str) -> dict | None:
    """Read one slot's token blob, never raising."""
    try:
        return rotator.read_slot(email)  # type: ignore[attr-defined]
    except Exception:
        return None


def _read_live(rotator: object) -> dict | None:
    """Read the live credential blob, never raising."""
    try:
        return rotator.read_live_blob()  # type: ignore[attr-defined]
    except Exception:
        return None


def _collect(rotator: object, out: list[dict]) -> None:
    """Probe the live account then every slot (deduped by email), appending each HTTP-200
    usage payload to `out`. Every rotator call is individually fail-soft."""
    seen: set[str] = set()
    try:
        st = rotator.load_state()  # type: ignore[attr-defined]
    except Exception:
        st = {}
    live_email = st.get("live_email") if isinstance(st, dict) else None
    live = _read_live(rotator)
    if live is not None and isinstance(live_email, str):
        seen.add(live_email)
        _probe(rotator, live_email, live, out)
    for email in (st.get("slots") if isinstance(st, dict) else {}) or {}:
        if not isinstance(email, str) or email in seen:
            continue
        seen.add(email)
        _probe(rotator, email, _read_slot_blob(rotator, email), out)


def accounts_usage() -> list[dict]:
    """`[{"label", "usage"}]` for every unique known account (live + slots, deduped by
    email). [] when no rotator is configured or on any failure. READ-ONLY."""
    try:
        import rotator  # noqa: PLC0415  # lazy — only load the rotator when actually gathering
    except Exception:
        return []
    # OPT-IN BY PRESENCE (mirrors oauth-cookie-reminder): do NOTHING — not even a keychain
    # read_live_blob or a usage probe — unless a rotator is actually configured on this
    # machine. This keeps a rotator-less janitor install (and every hermetic test with an
    # isolated HOME) fully network-free, and is the "function the tests bypass" guard.
    try:
        if rotator.configured_rotator_home() is None:
            return []
    except Exception:
        return []
    out: list[dict] = []
    _collect(rotator, out)
    return out
