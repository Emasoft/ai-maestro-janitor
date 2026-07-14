"""User-intent provenance + the self-injection presence gate (TRDD-RDFWQIFA, TRDD-USRPRES1).

The property under test is a security property, not a convenience one: an AGENT must not be able to
manufacture a token that says "a HUMAN authorized this". Every test here is written from the attacker's
side — what would it take to get a `True` out of this module without a human having asked?
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))

import user_intent  # noqa: E402

NOW = 1_784_000_000


@pytest.fixture
def sdir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d


def _presence(home: Path, last_input_epoch: int) -> Path:
    p = home / ".aimaestro" / "state" / "user-presence.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "last_user_input_epoch": last_input_epoch,
                "source": "janitor",
                "written_at_epoch": last_input_epoch,
            }
        )
    )
    return home


# --------------------------------------------------------------------------- #
# recording intent — what counts as the user asking
# --------------------------------------------------------------------------- #


def test_explicit_slash_command_records_intent(sdir: Path) -> None:
    """The user typing `/janitor-disarm` is the canonical authorization."""
    got = user_intent.record_intent_from_prompt("/janitor-disarm", state_dir=sdir, now=NOW)
    assert "disarm" in got
    assert user_intent.intent_fresh("disarm", state_dir=sdir, now=NOW)


def test_plain_english_request_records_intent(sdir: Path) -> None:
    """A genuine prose request must work too — otherwise 'stop the janitor' silently doesn't stick."""
    got = user_intent.record_intent_from_prompt("please stop the janitor on this project", state_dir=sdir, now=NOW)
    assert "disarm" in got


def test_a_negated_prompt_never_authorizes(sdir: Path) -> None:
    """THE test. The real message that exposed the disarm bug was:

        "you must never disarm the janitor heartbeat!!"

    It names the verb AND the subject, so any matcher without a negation guard would read the user's
    angriest possible *prohibition* as a *request* — and would have re-authorized the exact thing they
    were forbidding. A prompt that forbids and names the same verb is ambiguous, and ambiguity must
    never become consent.
    """
    got = user_intent.record_intent_from_prompt(
        "you must never disarm the janitor heartbeat!! look at what you did!",
        state_dir=sdir,
        now=NOW,
    )
    assert got == []
    assert not user_intent.intent_fresh("disarm", state_dir=sdir, now=NOW)


def test_intent_expires(sdir: Path) -> None:
    """A token bridges the seconds between the user typing and the skill running — not the session."""
    user_intent.record_intent_from_prompt("/janitor-disarm", state_dir=sdir, now=NOW)
    assert user_intent.intent_fresh("disarm", state_dir=sdir, now=NOW + user_intent.INTENT_TTL_S)
    assert not user_intent.intent_fresh("disarm", state_dir=sdir, now=NOW + user_intent.INTENT_TTL_S + 1)


def test_intent_is_absent_by_default(sdir: Path) -> None:
    """No token unless a human typed one. This is the whole point: an agent starts with NO authority."""
    assert not user_intent.intent_fresh("disarm", state_dir=sdir, now=NOW)
    assert not user_intent.intent_fresh("reload", state_dir=sdir, now=NOW)


# --------------------------------------------------------------------------- #
# presence
# --------------------------------------------------------------------------- #


def test_recent_input_means_present(tmp_path: Path) -> None:
    home = _presence(tmp_path, NOW - 60)
    assert user_intent.user_is_present(home=home, now=NOW)


def test_long_silence_means_away(tmp_path: Path) -> None:
    home = _presence(tmp_path, NOW - user_intent.USER_PRESENT_IDLE_S - 1)
    assert not user_intent.user_is_present(home=home, now=NOW)


def test_missing_breadcrumb_fails_CLOSED(tmp_path: Path) -> None:
    """Unknown presence → assume the user IS there. A breadcrumb problem must never license typing
    into someone's pane; the cost of being wrong that way is destroying their input."""
    assert user_intent.user_is_present(home=tmp_path, now=NOW)


def test_corrupt_breadcrumb_fails_CLOSED(tmp_path: Path) -> None:
    p = tmp_path / ".aimaestro" / "state" / "user-presence.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json")
    assert user_intent.user_is_present(home=tmp_path, now=NOW)


# --------------------------------------------------------------------------- #
# the gate — inject only when the user is away, or when the user asked
# --------------------------------------------------------------------------- #


def test_injection_refused_while_user_present_and_silent(tmp_path: Path, sdir: Path) -> None:
    """The bug that truncated the user's message: a [janitor-reload] marker typed /reload-plugins
    into their pane while they were writing."""
    home = _presence(tmp_path, NOW - 10)
    allowed, why = user_intent.injection_allowed(["/reload-plugins --force"], state_dir=sdir, home=home, now=NOW)
    assert not allowed
    assert "did not ask" in why


def test_injection_allowed_when_user_is_away(tmp_path: Path, sdir: Path) -> None:
    """The unattended case self-injection exists for — hours of silence, nobody to clobber."""
    home = _presence(tmp_path, NOW - user_intent.USER_PRESENT_IDLE_S - 1)
    allowed, _ = user_intent.injection_allowed(["/reload-plugins --force"], state_dir=sdir, home=home, now=NOW)
    assert allowed


def test_injection_allowed_when_present_user_asked(tmp_path: Path, sdir: Path) -> None:
    """A present user who TYPED the command must still get it — the gate protects them, not blocks them."""
    home = _presence(tmp_path, NOW - 5)
    user_intent.record_intent_from_prompt("/reload-plugins", state_dir=sdir, now=NOW)
    allowed, why = user_intent.injection_allowed(["/reload-plugins --force"], state_dir=sdir, home=home, now=NOW)
    assert allowed
    assert "explicitly asked" in why


def test_one_request_authorizes_exactly_one_injection(tmp_path: Path, sdir: Path) -> None:
    """The token is CONSUMED. Otherwise one `/reload-plugins` would license every injection for the
    next 10 minutes — a standing licence is not what the user granted."""
    home = _presence(tmp_path, NOW - 5)
    user_intent.record_intent_from_prompt("/reload-plugins", state_dir=sdir, now=NOW)
    first, _ = user_intent.injection_allowed(["/reload-plugins --force"], state_dir=sdir, home=home, now=NOW)
    second, _ = user_intent.injection_allowed(["/reload-plugins --force"], state_dir=sdir, home=home, now=NOW)
    assert first
    assert not second, "the intent token must be spent, not standing"


def test_intent_for_one_verb_does_not_authorize_another(tmp_path: Path, sdir: Path) -> None:
    """Asking to reload plugins is not consent to ESC-interrupt the turn and compact the context."""
    home = _presence(tmp_path, NOW - 5)
    user_intent.record_intent_from_prompt("/reload-plugins", state_dir=sdir, now=NOW)
    allowed, _ = user_intent.injection_allowed(["/compact"], state_dir=sdir, home=home, now=NOW)
    assert not allowed
