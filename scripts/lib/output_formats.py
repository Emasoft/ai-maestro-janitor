"""Output formats — HMAC-signed scan badge, approval-gate protocol, FP-filters DSL.

Distilled from the deep-UX-suppression study of `skill-scan-main/` and
`supply-chain-mitigation-master/`. Pure-stdlib primitives the rest of the
janitor composes into detectors / heartbeat output / agent gates.

Public surface
==============

  * make_badge(report_id, verdict, scanned_at, key, expiry_days=30) -> str
      Build a `report_id|verdict|scanned_at|expires_at|sig` token.
      `sig` = base64(hmac_sha256(key, "report_id|verdict|scanned_at|expires_at")).
      Matches skill-scan/src/badge/generator.ts:89-97 shape; key source is
      caller's responsibility (skill-scan uses a server key, janitor derives
      from `git config remote.origin.url` + first-commit SHA — that
      derivation lives in the caller, not here, so this primitive stays
      pure-stdlib and unit-testable).

  * verify_badge(badge, key, *, now=None) -> (valid, reason)
      Returns ``(False, "malformed")`` on shape errors, ``(False, "expired")``
      when ``expires_at <= now``, ``(False, "bad signature")`` on HMAC
      mismatch, ``(True, "OK")`` on success. Uses ``hmac.compare_digest`` so
      the comparison is timing-safe (matches verify.ts:68-72).

  * format_security_triggered(action, normalized_diff) -> str
      Canonical "SECURITY TRIGGERED:" block emitted before any sensitive-file
      edit. The ``normalized_diff`` MUST be the rule-normalized output (what
      janitor will actually write after pin-rewriting / lifecycle-stripping /
      secret-sanitizing) — NOT the user's literal request. Callers handle the
      normalization; this primitive just formats the block.

  * parse_approval_response(reply) -> bool
      Returns True iff the reply is EXACTLY ``APPROVED`` (case-sensitive,
      after stripping leading/trailing whitespace). Matches the
      supply-chain-mitigation rules-CLAUDE.md two-categories protocol — only
      the literal token unlocks; nothing else does.

  * apply_fp_filters(text, filters) -> bool
      Substring per-rule allowlist. Returns True iff ANY filter is found as a
      plain substring in ``text``. No regex — filters are plain substrings so
      rule authors can't accidentally ship a broken pattern. Compile-once
      regex shape from skill-scan/src/rules/engine.ts:65-78 is a follow-up.

Iron rule — these are protocol primitives, not detectors. They format /
verify / parse the wire; the caller decides WHAT to format and WHEN. That
split is what keeps this file pure stdlib and ~100% covered by unit tests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Final

# Field separator inside the badge token. Chosen to avoid collision with
# UUID v4 hex (no `|`), ISO-8601 timestamps (no `|`), and base64 signature
# alphabet (no `|`). Same separator both inside the signed payload and
# between fields of the wire-format token, so the wire layout matches the
# signed layout byte-for-byte — no re-quoting / re-escaping.
_SEP: Final[str] = "|"

# 30-day expiry default matches skill-scan's BADGE_EXPIRY_MS
# (30 * 24 * 60 * 60 * 1000). Caller may override per-call.
_SECONDS_PER_DAY: Final[int] = 86_400

# Canonical literal that unlocks a SECURITY-TRIGGERED gate. Case-sensitive,
# whitespace-stripped. NO synonyms (yes / ok / sure / lgtm / "approved"
# lowercase) — synonym tolerance is the exact surface attackers exploit
# to launder approval through misread tokens. Bare "APPROVED" only.
_APPROVAL_TOKEN: Final[str] = "APPROVED"


def _sign(payload: str, key: bytes) -> str:
    """Return base64 of HMAC-SHA256(key, payload) — no padding stripped.

    Pure helper so the test file can independently re-sign a payload and
    verify make_badge / verify_badge agree on the wire format.
    """
    mac = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(mac).decode("ascii")


def make_badge(
    report_id: str,
    verdict: str,
    scanned_at: int,
    key: bytes,
    expiry_days: int = 30,
) -> str:
    """Build a signed badge token.

    Wire format: ``report_id|verdict|scanned_at|expires_at|sig``

    The signed payload is the first four fields joined by ``|`` (so the
    signature line is the FIFTH field, never part of what's signed).

    Parameters
    ----------
    report_id
        Stable identifier for the audit run (typically a UUID v4). Must not
        contain the separator ``|`` — caller's responsibility.
    verdict
        Janitor verdict literal (``"safe"`` / ``"drift"`` / ``"blocked"``).
        Same no-``|`` rule.
    scanned_at
        Unix epoch seconds when the audit completed. The wire format encodes
        epoch seconds (not ISO) so badge parsing is locale-free.
    key
        HMAC key bytes. Caller derives this however it wants; this function
        treats it as opaque bytes.
    expiry_days
        Days until the badge is considered stale. Default 30 matches
        skill-scan. ``expires_at = scanned_at + expiry_days * 86400``.

    Returns
    -------
    str
        The five-field token. Pass to verify_badge to validate.
    """
    if expiry_days <= 0:
        # Fail-fast: a zero / negative expiry would mint a pre-expired
        # badge, which has no legitimate use case and silently misleads
        # consumers who don't read the expires_at field.
        raise ValueError("expiry_days must be positive")
    if _SEP in report_id or _SEP in verdict:
        # Embedded separators would let an attacker craft a payload that
        # round-trips through verify_badge with a forged verdict. Fail
        # fast at mint time — caller controls these fields.
        raise ValueError(f"badge fields must not contain {_SEP!r}")

    expires_at = scanned_at + (expiry_days * _SECONDS_PER_DAY)
    payload = _SEP.join((report_id, verdict, str(scanned_at), str(expires_at)))
    sig = _sign(payload, key)
    return _SEP.join((payload, sig))


def verify_badge(
    badge: str,
    key: bytes,
    *,
    now: int | None = None,
) -> tuple[bool, str]:
    """Verify a signed badge token.

    Returns
    -------
    tuple[bool, str]
        ``(True, "OK")`` on full success.
        ``(False, "malformed")`` if the wire shape is wrong (wrong field
        count, non-integer timestamps, ...).
        ``(False, "expired")`` if ``expires_at <= now``.
        ``(False, "bad signature")`` if HMAC mismatch.

    The signature check uses ``hmac.compare_digest`` so the comparison time
    does not depend on which byte differs first — matches verify.ts:68-72
    timing-safe contract.

    Parameters
    ----------
    badge
        The five-field token returned by make_badge.
    key
        Same HMAC key used at mint time.
    now
        Override "now" in unit tests; production passes None to use
        ``time.time()``. Epoch seconds.
    """
    parts = badge.split(_SEP)
    if len(parts) != 5:
        return (False, "malformed")
    report_id, verdict, scanned_at_str, expires_at_str, sig = parts
    if not report_id or not verdict:
        return (False, "malformed")
    try:
        # We don't use scanned_at after parsing — it's only validated as an
        # integer so the wire shape stays well-formed. Keep the int() call
        # for that validation side effect.
        int(scanned_at_str)
        expires_at = int(expires_at_str)
    except ValueError:
        return (False, "malformed")

    # Verify signature FIRST, then expiry. Both checks are constant-time
    # relative to their own inputs; the order matters only when an
    # attacker can probe the response — and even then leaking
    # "the signature matches but the badge is expired" is fine (the
    # attacker had to already know the key to produce that state).
    payload = _SEP.join((report_id, verdict, scanned_at_str, expires_at_str))
    expected = _sign(payload, key)
    if not hmac.compare_digest(expected.encode("ascii"), sig.encode("ascii")):
        return (False, "bad signature")

    current = int(time.time()) if now is None else int(now)
    if expires_at <= current:
        return (False, "expired")

    return (True, "OK")


def format_security_triggered(action: str, normalized_diff: str) -> str:
    """Build the canonical SECURITY-TRIGGERED gate block.

    The output is the exact wire format the agent layer must emit before any
    sensitive-file edit. ``normalized_diff`` MUST reflect rule-normalized
    output (post pin-rewriting / lifecycle-stripping / secret-sanitizing) —
    NOT the user's literal request. This guarantees the preview matches what
    will actually land on disk, defeating "asked for X, applied Y" attacks.

    The trailing instruction is the literal "Reply APPROVED to proceed." —
    matches the supply-chain-mitigation rules-CLAUDE.md two-categories
    protocol. Pair with parse_approval_response on the reply.

    Layout
    ------
    ::

        SECURITY TRIGGERED:
        <action>
        <normalized_diff>

        Reply APPROVED to proceed.

    A blank line precedes the reply instruction so it visually separates
    from the diff body and the reader cannot mistake it for diff content.
    """
    return (
        "SECURITY TRIGGERED:\n"
        f"{action}\n"
        f"{normalized_diff}\n"
        "\n"
        "Reply APPROVED to proceed."
    )


def parse_approval_response(reply: str) -> bool:
    """Return True iff the reply is EXACTLY ``APPROVED`` after .strip().

    Case-sensitive. ``approved`` / ``APPROVE`` / ``yes`` / ``y`` /
    ``ok`` / ``lgtm`` all return False. Surrounding whitespace is stripped
    (so newlines from a copy-paste don't break legit approvals) but
    embedded whitespace fails (``"APP ROVED"`` → False).

    The strict literal is deliberate — synonym tolerance is exactly the
    surface attackers use to launder approval through misread tokens or
    auto-completed text.
    """
    return reply.strip() == _APPROVAL_TOKEN


def apply_fp_filters(text: str, filters: list[str]) -> bool:
    """Return True iff ``text`` contains ANY substring from ``filters``.

    Per-rule allowlist DSL distilled from skill-scan/src/rules/engine.ts
    falsePositiveFilters. Plain substring match — no regex. Rule authors
    ship filter substrings ("test_", "fixtures/", "examples/") that travel
    WITH the rule, complementing janitor's per-path sha-pinned suppression
    in `.janitor.toml`.

    Empty filter list returns False (no allowlist means "no filtering").
    Empty filter strings inside the list are skipped — an empty substring
    is contained in every text and would always match, hiding all findings.

    Parameters
    ----------
    text
        File content / line / chunk the rule is about to flag.
    filters
        Plain substrings. Case-sensitive (callers normalise if they want
        case-insensitive matching). Empty list = no allowlist applies.

    Returns
    -------
    bool
        True iff at least one non-empty filter substring is found in
        ``text``. The caller skips emitting the finding when True.
    """
    return any(f in text for f in filters if f)
