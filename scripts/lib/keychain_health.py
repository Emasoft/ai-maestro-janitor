"""Keychain-health decision layer — the PURE half of the keychain-health detector.

WHY THIS EXISTS (the 2026-07-12 fleet outage). Every Claude agent on the machine suddenly
reported `Not logged in`. The credential was FINE — `/login` did not help, and the keychain
item was never rewritten. The real fault: a LONG-LIVED tmux server (pid 38493, ppid 1, 22 h
old) held a securityd connection that DIED in a securityd recycle. Every pane it forks
inherits that dead security session, so inside those panes the Keychain Services API fails
OUTRIGHT — `security list-keychains` returns `SecKeychainCopySearchList: parameters not
valid` — and Claude Code cannot read its OAuth item. The trigger was a `dotenclave unlock`
in `~/.zshrc` registering a custom keychain via `security list-keychains -s`, which REPLACES
the search list and left a DANGLING entry (a keychain registered in the list whose file is
gone). A search list with a dead entry poisons EVERY lookup in that security session.

The janitor is the guardian of the fleet, so this must never again go undetected: the
per-session heartbeat runs INSIDE the same security session as the agent, which makes it the
one component positioned to notice "this pane cannot reach the keychain" — before the user
discovers it as a fleet-wide outage.

THE HARD SAFETY RULE (macos-keychain gotcha 3 — the ACL prompt FLOOD): the thing that
opens hundreds of GUI keychain dialogs is the `-w` SECRET read of an item whose ACL excludes
the caller. So this layer checks **FINDABILITY, NEVER READABILITY**: `list-keychains` and
`find-generic-password` WITHOUT `-w` return attributes only — no secret, no ACL check, no
prompt. `-w` must never appear in this detector. (Findable != readable was also the exact
distinction that unlocked the investigation.)

PURE: no I/O. The detector shell runs the `security` calls through the mandated choke point
(`safe_storage.run_security` — hard timeout + one-shot denied-latch) and feeds the results in.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

#: The keychain item Claude Code stores its OAuth credential under. Findability of THIS item
#: from the current security session is the difference between a working agent and one that
#: says `Not logged in`.
CLAUDE_CREDENTIAL_SERVICE = "Claude Code-credentials"

#: Signatures of a security session whose securityd connection is dead. macOS reports the
#: broken Keychain Services API through these — the API does not fail with a clean "denied",
#: it fails with a *parameter* error, which is why it reads as nonsense and gets misdiagnosed.
_BROKEN_SESSION_SIGNS = (
    "SecKeychainCopySearchList",
    "SecKeychainCopySettings",
    "parameters were not valid",
    "parameters not valid",
)


@dataclass(frozen=True)
class KeychainVerdict:
    """What the heartbeat should say about this security session's keychain, if anything.

    `severity` is CRITICAL only for the conditions that BREAK agents (a dead security session
    or an unfindable credential): in both, every Claude process launched in this context will
    report `Not logged in`. A dangling search-list entry alone is HIGH — it is the *cause* that
    poisons lookups and will produce the CRITICAL state, so it is worth reporting even in the
    window before something actually fails.
    """

    code: str          # broken-session | dangling-keychain | credential-unfindable
    severity: str      # CRITICAL | HIGH
    message: str       # human-facing, already actionable
    detail: str = ""   # the raw evidence (stderr / the offending path)


def looks_like_broken_session(stderr: str) -> bool:
    """True iff `stderr` carries the signature of a DEAD securityd connection.

    PURE. This is the fleet-killer: when it is true, EVERY keychain lookup in this security
    session fails, so every Claude Code process here cannot read its OAuth item.
    """
    low = (stderr or "").lower()
    return any(sign.lower() in low for sign in _BROKEN_SESSION_SIGNS)


def parse_search_list(stdout: str) -> list[str]:
    """Parse `security list-keychains` output into the keychain paths, in order.

    Output is one quoted, indented path per line:
        "/Users/x/Library/Keychains/login.keychain-db"
    An EMPTY quoted entry ("") is preserved deliberately — it is itself a corruption (the
    dangling entry found in the 2026-07-12 incident), and dropping it here would hide the
    very thing we are hunting. PURE.
    """
    paths: list[str] = []
    for raw in (stdout or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        paths.append(line[1:-1] if line.startswith('"') and line.endswith('"') else line)
    return paths


def dangling_entries(paths: list[str], exists) -> list[str]:
    """The search-list entries that do NOT resolve to a real file — the corruption that
    poisons every lookup in the session.

    `exists` is injected (a `os.path.exists`-alike) so this stays PURE and testable. An empty
    entry is dangling by definition: it can never resolve to a keychain.
    """
    bad: list[str] = []
    for p in paths:
        if not p.strip():
            bad.append(p)  # the "" entry — a registered keychain with no path at all
        elif not exists(p):
            bad.append(p)
    return bad


def classify(
    *,
    list_ok: bool,
    list_stderr: str,
    dangling: list[str],
    credential_findable: bool | None,
) -> KeychainVerdict | None:
    """The whole decision, in one pure function. Returns the SINGLE most important verdict, or
    None when the keychain is healthy.

    Order is deliberate — most-causal first, so the operator is told the ROOT problem rather
    than a downstream symptom:

    1. broken session      — the API itself is dead; nothing else can even be measured.
    2. dangling entry      — the CAUSE that produces (1)/(3); fixable before anything breaks.
    3. credential unfindable — the agent-visible failure (`Not logged in`).

    `credential_findable=None` means "not determined" (e.g. the session was already broken, or
    the probe was skipped) and never produces a verdict on its own — absence of evidence is not
    evidence, the mistake that made the original incident take hours to diagnose.
    """
    if not list_ok or looks_like_broken_session(list_stderr):
        return KeychainVerdict(
            code="broken-session",
            severity="CRITICAL",
            message=(
                "this shell's macOS security session is BROKEN — every keychain lookup here "
                "fails, so any Claude Code started in it will say 'Not logged in' (the "
                "credential itself is FINE; re-running /login will NOT help). Cause: a dead "
                "securityd connection, typically a long-lived tmux/terminal server that "
                "survived a securityd recycle. Fix: recreate that server (its panes inherit "
                "the dead session); verify with `security list-keychains` inside a new pane."
            ),
            detail=(list_stderr or "").strip()[:200],
        )
    if dangling:
        shown = ", ".join(repr(d) for d in dangling[:3])
        return KeychainVerdict(
            code="dangling-keychain",
            severity="HIGH",
            message=(
                f"the keychain SEARCH LIST contains {len(dangling)} DANGLING entr"
                f"{'y' if len(dangling) == 1 else 'ies'} ({shown}) — a keychain registered in "
                "the list whose file does not exist. A dead entry poisons EVERY keychain "
                "lookup in this security session, which is how agents end up reporting 'Not "
                "logged in'. Usually left by a custom-keychain tool (e.g. `dotenclave unlock` "
                "in ~/.zshrc) calling `security list-keychains -s`, which REPLACES the list. "
                "Fix: re-set the list to the valid keychains only "
                "(`security list-keychains -s <paths...>`)."
            ),
            detail=" | ".join(dangling[:5]),
        )
    if credential_findable is False:
        return KeychainVerdict(
            code="credential-unfindable",
            severity="CRITICAL",
            message=(
                f"Claude Code's OAuth item ('{CLAUDE_CREDENTIAL_SERVICE}') is NOT FINDABLE "
                "from this security session — every Claude Code process started here will "
                "report 'Not logged in'. Note this is a REACHABILITY failure, not a bad "
                "credential: /login will not fix it if the session itself cannot see the "
                "keychain. Check `security list-keychains` here vs in a fresh terminal."
            ),
        )
    return None


def format_drift(verdict: KeychainVerdict, sanitize: Callable[[str], str] = str) -> str:
    """One greppable heartbeat line. `sanitize` is injected (the detector passes
    `state.sanitize_for_drift_line`) because the detail carries filesystem paths and raw
    `security` stderr — untrusted text that must never smuggle control chars or fake markers
    into the model's context.

    The annotation is load-bearing, not decoration: bare `sanitize=str` let the checker infer
    the parameter as `type[str]` (the class), so passing the real `(str) -> str` sanitizer —
    the ONLY way this is ever called in production — was a type error, while passing the
    do-nothing default type-checked clean. The types were inverted against the intent: the
    safe call looked wrong and the unsanitized one looked right."""
    line = f"[keychain-health] {verdict.severity}: {verdict.message}"
    if verdict.detail:
        line += f" (evidence: {sanitize(verdict.detail)})"
    return line
