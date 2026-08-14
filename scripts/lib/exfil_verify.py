"""Exfiltration ALARM verification — the ladder that stands between a match and a human.

TRDD-HYV0SOC6, owner ruling 2026-08-14: *"if the janitor detects an exfiltration it must
immediately notify the main claude and the user, but it must be sure. make the thing verify
before reporting."*

THE SPLIT THIS MODULE EXISTS TO ENFORCE: a finding and an alarm are not the same event, and
the whole precision/recall argument on that card came from treating them as one. Measured on
the seeded corpus, the same structural rule scores 3/8 with 1 false positive unmasked, and
2/8 with 0 masked — so filtering at the DETECTION layer buys the false positive by discarding
a real attack. Moving the same discriminator to the ALARM layer keeps both: the attack is
recorded, and the post-mortem that triggered the false positive never reaches a human.

So:

  * DETECT WIDE — the rule stays unmasked; a match is a SUSPICION.
  * VERIFY — every rung below must clear, and each rung answers on evidence the trigger never
    looked at. Re-running the trigger's own regex is the same claim twice, not verification.
  * ALARM ONLY ON VERIFIED — `verified` gates the push, nothing else.

**FAIL-CLOSED ON THE ALARM, NOT ON THE FINDING.** A candidate that fails a rung is still
recorded by the caller, at low severity. Dropping it would reintroduce the blocklist's 0/8
blindness through the back door — the thing being made "sure" is the interrupt, not the
observation. That asymmetry is the entire design: on the push path a false positive costs more
than a miss (janitor#254 exists because that balance was got wrong once and the channel learned
to be ignored), and on the ledger path the reverse is true.

PURE — no I/O, no logging, no notification. It renders a verdict and the caller decides. That
is what lets every rung be tested for its ability to KILL a candidate, which is the only
property that matters here: a rung that cannot say no is decoration.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

# ── rung 1: is the destination really OUTBOUND? ───────────────────────────────────────────
#
# An agent posting to its own loopback or to a private LAN address is not exfiltrating to an
# attacker — it is talking to a local service, which is what a dev-setup README documents. The
# trigger only knows "there is a URL"; this rung knows WHERE it points, which the trigger never
# asked.
_URL_RE = re.compile(r"https?://[^\s\"'`<>)\]}]+", re.IGNORECASE)

#: Hostnames that are never an exfiltration destination however the URL is spelled.
_LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "broadcasthost"})

#: Reserved documentation domains (RFC 2606 / 6761). A URL under one cannot resolve to an
#: attacker's host, so it is a placeholder in prose — not a live sink.
_DOC_TLDS = ("example.com", "example.org", "example.net", ".example", ".invalid", ".test", ".localhost")


def _host_of(url: str) -> str:
    """The lowercased hostname of `url`, or "" when it has none / cannot be parsed."""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def destination_is_outbound(url: str) -> bool:
    """True iff `url`'s host could actually carry data OFF this machine.

    False for loopback, RFC1918 / carrier-grade / link-local / unique-local addresses, and the
    reserved documentation domains. Each of those is a destination an attacker cannot receive
    at, so a match on one is a description of exfiltration, not an instance of it.
    """
    host = _host_of(url)
    if not host or host in _LOCAL_HOSTNAMES:
        return False
    if any(host == d or host.endswith("." + d.lstrip(".")) or host.endswith(d) for d in _DOC_TLDS):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # a real DNS name — outbound unless one of the cases above caught it
    return not (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_unspecified)


# ── rung 3: is the PAYLOAD a real secret REFERENCE, or just the English word? ──────────────
#
# The trigger fires on a vocabulary hit — "credential", "token", ".env". Prose uses those words
# constantly ("rotate the credential", "never commit your .env"). What distinguishes an
# instruction to STEAL is a reference that RESOLVES to a value: an interpolation, an env read, a
# file read. This rung asks for that resolution, which the vocabulary match cannot see.
_SECRET_REFERENCE = re.compile(
    r"""(?x)
      \$\{[A-Z0-9_]*(?:TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL|SESSION)[A-Z0-9_]*\}   # ${API_TOKEN}
    | \$[A-Z0-9_]*(?:TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL)[A-Z0-9_]*\b             # $API_TOKEN
    | \bos\.environ(?:\.get)?\s*[\[(]                                              # os.environ[...]
    | \bprocess\.env\.[A-Za-z_]                                                    # process.env.X
    | \bgetenv\s*\(                                                                # getenv(...)
    | (?:cat|read|open|load)\w*\s*\(?\s*['"`]?[^\s'"`]*\.env\b                     # read('.env')
      # NO leading \b here — it made this whole branch DEAD, and it had never once fired.
      # Every alternative begins with a NON-word char (`~`, `$`, `/`), and the character
      # before it is normally a space: non-word -> non-word is not a word boundary, so the
      # group could never start matching. Measured 2026-08-14 — `~/.aws/`, `~/.ssh/` and
      # `~/.config/gh/` all failed. The branch LOOKED alive only because `~/.config/gh/hosts.yml`
      # matched the separate `hosts.yml` named-store alternative below, so a spot-check on the
      # obvious example passed while the branch itself did nothing. Do not re-add the \b.
    | (?:~|\$HOME|/home/[^\s]+|/Users/[^\s]+)/\.(?:aws|ssh|config/(?:gh|glab)|netrc)  # ~/.aws, ~/.ssh, gh/glab
    | \b(?:credentials|id_rsa|\.netrc|hosts\.yml)\b\s*(?:file|path)?               # named stores
    | \bsession[_-]?token\s*[=:]                                                   # session_token=
    """,
    re.IGNORECASE,
)


def payload_is_secret_reference(window: str) -> bool:
    """True iff `window` carries a reference that RESOLVES to a secret value.

    The distinction is deliberate and is the rung's whole contribution: "rotate the credential"
    names a secret, `${API_TOKEN}` and `os.environ["API_KEY"]` and `cat ~/.aws/credentials`
    dereference one. Only the second class can be exfiltrated by the instruction that mentions it.
    """
    return _SECRET_REFERENCE.search(window) is not None


@dataclass(frozen=True)
class Rung:
    """One verification step: its name, whether it cleared, and — when it did not — WHY.

    `why` is populated only on failure, because that string is what a human reads when asking
    "why did this not alarm?", and a reason recorded for a step that passed is noise.
    """

    name: str
    passed: bool
    why: str = ""


@dataclass(frozen=True)
class Verdict:
    """The alarm decision. `verified` gates the PUSH and nothing else — the caller records the
    finding either way (see the module docstring's fail-closed asymmetry)."""

    verified: bool
    rungs: tuple[Rung, ...]
    reason: str

    def failed(self) -> tuple[str, ...]:
        """Names of the rungs that did NOT clear, in ladder order."""
        return tuple(r.name for r in self.rungs if not r.passed)


def verify_exfil_candidate(
    text: str,
    start: int,
    end: int,
    *,
    filename: str = "",
    window: int = 400,
    negative_context: Callable[[str, int, int], bool] | None = None,
    fixture_path: Callable[[str], bool] | None = None,
) -> Verdict:
    """Run the four-rung ladder over the candidate at `text[start:end]`.

    `negative_context` and `fixture_path` are INJECTED rather than imported so this module stays
    free of a circular import with `agent_config_patterns` (which will call it) and so a test can
    drive a rung in isolation. Both default to the real implementations at call time.

    Every rung must be able to KILL the candidate on evidence the trigger never looked at:

      1. `outbound-destination`   — the URL points somewhere data could actually go.
      2. `not-negative-context`   — the surrounding prose is not NAMING this as a threat to find,
                                     avoid, or narrate after the fact (janitor#254 / XOITBRIZ).
      3. `secret-reference`       — the payload dereferences a secret, rather than mentioning one.
      4. `instruction-context`    — the file is loaded AS INSTRUCTIONS, not a fixture / IOC
                                     catalogue / red-team sample, which are the corpus OF an
                                     attack rather than one.

    The ladder is evaluated in FULL, not short-circuited: a caller triaging a near-miss needs to
    know every rung that failed, and the cost is four regex passes over a 400-char window.
    """
    if negative_context is None or fixture_path is None:
        import agent_config_patterns as acp  # local: breaks the import cycle

        if negative_context is None:
            negative_context = acp.dynamic_exec_negative_context_near
        if fixture_path is None:
            fixture_path = acp.is_exfil_fp_path

    lo, hi = max(0, start - window), min(len(text), end + window)
    ctx = text[lo:hi]

    # Each predicate is evaluated ONCE and reused for both the pass flag and the reason. Calling
    # it twice (once per branch of a conditional) would let a non-pure injected predicate answer
    # differently in the two places and produce a Rung whose `passed` and `why` disagree.
    urls = _URL_RE.findall(ctx)
    outbound = [u for u in urls if destination_is_outbound(u)]
    is_negative = bool(negative_context(text, start, end))
    has_secret = payload_is_secret_reference(ctx)
    is_fixture = bool(fixture_path(filename))

    rungs = [
        Rung(
            "outbound-destination",
            bool(outbound),
            "" if outbound else (
                f"no outbound destination near the match ({len(urls)} URL(s), all loopback / "
                "private / reserved-documentation)"
            ),
        ),
        Rung(
            "not-negative-context",
            not is_negative,
            "surrounding prose NAMES this as a threat to find or avoid, not an instruction to "
            "perform it" if is_negative else "",
        ),
        Rung(
            "secret-reference",
            has_secret,
            "" if has_secret else (
                "the payload only MENTIONS a secret; nothing near the match dereferences one"
            ),
        ),
        Rung(
            "instruction-context",
            not is_fixture,
            f"`{filename}` is a fixture / IOC catalogue / red-team path — the corpus of an "
            "attack, not an attack" if is_fixture else "",
        ),
    ]
    failed = [r for r in rungs if not r.passed]
    return Verdict(
        verified=not failed,
        rungs=tuple(rungs),
        reason="all rungs cleared" if not failed else "; ".join(r.why for r in failed),
    )
