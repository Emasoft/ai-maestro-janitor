"""keychain-health detector (the 2026-07-12 fleet outage) — real, no mocks.

The outage: every Claude agent reported `Not logged in` while the credential was perfectly
fine. A long-lived tmux server (ppid 1) held a securityd connection that DIED in a securityd
recycle; every pane it forked inherited that dead security session, in which the Keychain
Services API fails outright. `/login` could not fix it because the credential was never the
problem — REACHABILITY was.

These feed the PURE decision layer the EXACT strings macOS produced during that incident, so
the detector is proven against reality rather than against a guess. Feeding a pure classifier
real input dicts is not mocking — it is the only way to test a decision layer.

The load-bearing test here is `test_detector_never_reads_a_secret`: the ACL prompt FLOOD
(macos-keychain gotcha 3 — hundreds of GUI modals, user locked out) is caused by the `-w`
SECRET read. A guardian that fixes one outage by causing a worse one is not a fix, so `-w`
must be structurally impossible in this detector, not merely absent today.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import keychain_health as kh  # noqa: E402

# The VERBATIM stderr macOS emitted inside a poisoned tmux pane during the incident.
REAL_BROKEN_STDERR = "SecKeychainCopySearchList: The specified item could not be found in the keychain."
REAL_BROKEN_STDERR_2 = "SecKeychainCopySettings: parameters were not valid"
# The VERBATIM `security list-keychains` output, including the dangling "" dotenclave left.
REAL_POISONED_LIST = '    ""\n    "/Users/x/Library/Keychains/login.keychain-db"\n'
REAL_HEALTHY_LIST = (
    '    "/Users/x/Library/Keychains/login.keychain-db"\n'
    '    "/Library/Keychains/System.keychain"\n'
)


# ---------- broken-session detection (the fleet-killer) --------------------

def test_broken_session_detected_from_real_stderr() -> None:
    """The REAL `SecKeychainCopySearchList` stderr from the outage is recognised as a dead
    security session."""
    assert kh.looks_like_broken_session(REAL_BROKEN_STDERR) is True


def test_broken_session_detected_from_settings_variant() -> None:
    """The sibling `SecKeychainCopySettings: parameters were not valid` is recognised too —
    the API reports the dead session through more than one call."""
    assert kh.looks_like_broken_session(REAL_BROKEN_STDERR_2) is True


def test_healthy_stderr_is_not_a_broken_session() -> None:
    """A quiet/empty stderr must NOT be read as a breakage (no false fleet alarm)."""
    assert kh.looks_like_broken_session("") is False
    assert kh.looks_like_broken_session("some unrelated warning") is False


# ---------- search-list parsing + the dangling entry (the CAUSE) -----------

def test_parse_search_list_reads_quoted_indented_paths() -> None:
    """`security list-keychains` emits one quoted, indented path per line; parse to bare paths."""
    assert kh.parse_search_list(REAL_HEALTHY_LIST) == [
        "/Users/x/Library/Keychains/login.keychain-db",
        "/Library/Keychains/System.keychain",
    ]


def test_parse_search_list_preserves_the_empty_dangling_entry() -> None:
    """The `""` entry MUST survive parsing — it IS the corruption we are hunting. Silently
    dropping it would hide the exact defect that poisoned the fleet's keychain lookups."""
    assert kh.parse_search_list(REAL_POISONED_LIST)[0] == ""


def test_empty_entry_is_dangling_by_definition() -> None:
    """An empty search-list entry can never resolve to a keychain file, so it is dangling
    without needing to touch the filesystem."""
    paths = kh.parse_search_list(REAL_POISONED_LIST)
    assert kh.dangling_entries(paths, lambda p: True) == [""]


def test_nonexistent_keychain_file_is_dangling() -> None:
    """A registered keychain whose FILE is gone is dangling — the dotenclave failure mode."""
    paths = ["/gone/custom.keychain-db", "/real/login.keychain-db"]
    dangling = kh.dangling_entries(paths, lambda p: p.startswith("/real"))
    assert dangling == ["/gone/custom.keychain-db"]


def test_healthy_search_list_has_no_dangling_entries() -> None:
    """Every entry resolving to a real file => nothing to report."""
    paths = kh.parse_search_list(REAL_HEALTHY_LIST)
    assert kh.dangling_entries(paths, lambda p: True) == []


# ---------- the verdict (classify) ----------------------------------------

def test_classify_broken_session_is_critical() -> None:
    """A dead security session is CRITICAL: every agent started in it will say 'Not logged in'."""
    v = kh.classify(list_ok=False, list_stderr=REAL_BROKEN_STDERR, dangling=[], credential_findable=None)
    assert v is not None
    assert v.code == "broken-session"
    assert v.severity == "CRITICAL"


def test_classify_broken_session_says_login_will_not_help() -> None:
    """The message must state that /login will NOT fix it — the single fact whose absence cost
    the original investigation hours (the credential was never the problem)."""
    v = kh.classify(list_ok=False, list_stderr=REAL_BROKEN_STDERR, dangling=[], credential_findable=None)
    assert v is not None
    assert "not help" in v.message.lower()


def test_classify_dangling_entry_is_high() -> None:
    """A dangling search-list entry is the CAUSE — reported even before anything visibly fails."""
    v = kh.classify(list_ok=True, list_stderr="", dangling=[""], credential_findable=None)
    assert v is not None
    assert v.code == "dangling-keychain"
    assert v.severity == "HIGH"


def test_classify_unfindable_credential_is_critical() -> None:
    """If Claude's OAuth item cannot be FOUND from this session, agents here are already broken."""
    v = kh.classify(list_ok=True, list_stderr="", dangling=[], credential_findable=False)
    assert v is not None
    assert v.code == "credential-unfindable"
    assert v.severity == "CRITICAL"


def test_classify_healthy_session_is_silent() -> None:
    """A healthy session yields NO verdict — the detector must never nag a working machine."""
    assert kh.classify(list_ok=True, list_stderr="", dangling=[], credential_findable=True) is None


def test_broken_session_outranks_dangling_entry() -> None:
    """Root cause first: when the API is dead AND the list is dangling, report the dead session
    — telling the operator about a downstream symptom would send them fixing the wrong thing."""
    v = kh.classify(list_ok=False, list_stderr=REAL_BROKEN_STDERR, dangling=[""], credential_findable=None)
    assert v is not None
    assert v.code == "broken-session"


def test_undetermined_credential_never_alarms_on_its_own() -> None:
    """`credential_findable=None` means "not determined" and must NEVER produce a verdict.

    Absence of evidence is not evidence — treating an unanswered probe as a failure is the
    precise error that produced false conclusions throughout the original incident."""
    assert kh.classify(list_ok=True, list_stderr="", dangling=[], credential_findable=None) is None


# ---------- the drift line -------------------------------------------------

def test_format_drift_routes_detail_through_the_sanitizer() -> None:
    """The evidence carries filesystem paths + raw `security` stderr — untrusted text that must
    be sanitized before it reaches the model's context."""
    v = kh.KeychainVerdict(code="x", severity="HIGH", message="msg", detail="[evil]")
    seen: list[str] = []

    def _sanitize(text: str) -> str:
        seen.append(text)
        return "SAFE"

    line = kh.format_drift(v, sanitize=_sanitize)
    assert seen == ["[evil]"], "the detail must be passed to the injected sanitizer"
    assert "SAFE" in line


# ---------- THE load-bearing safety test ----------------------------------

def test_detector_never_reads_a_secret() -> None:
    """STRUCTURAL: the detector must never pass `-w` to `security`.

    `-w` reads an item's SECRET. When the caller is not on the item's ACL that raises the
    macOS keychain GUI dialog — the ACL prompt FLOOD that once opened hundreds of modals and
    locked the user out (macos-keychain gotcha 3). A guardian that fixes one outage by causing
    a worse one is not a fix. This asserts on the SOURCE, so the property cannot regress even
    if someone "just adds a quick secret check" later: findability is all this detector is
    ever allowed to ask for.
    """
    src = (_PROJECT_ROOT / "scripts" / "detectors" / "keychain-health.py").read_text()
    assert '"-w"' not in src and "'-w'" not in src, (
        "keychain-health must NEVER read a keychain SECRET (`-w`) — that is what causes the "
        "ACL prompt flood. Check FINDABILITY only (find-generic-password WITHOUT -w)."
    )
