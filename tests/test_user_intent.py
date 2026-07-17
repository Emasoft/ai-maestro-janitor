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

import state  # noqa: E402
import user_intent  # noqa: E402

NOW = 1_784_000_000

# Presence is PER-PANE (user directive 2026-07-16). The gate keys on the terminal pane id, so an
# env carrying a TMUX_PANE selects the per-pane path; an empty env forces the machine-global fallback.
PANE_A = {"TMUX_PANE": "%3"}
PANE_B = {"TMUX_PANE": "%9"}
NO_PANE: dict[str, str] = {}  # no pane id → machine-global fallback path


@pytest.fixture
def sdir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d


def _breadcrumb(path: Path, last_input_epoch: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "last_user_input_epoch": last_input_epoch,
                "source": "janitor",
                "written_at_epoch": last_input_epoch,
            }
        )
    )


def _presence(home: Path, last_input_epoch: int) -> Path:
    """Write the machine-GLOBAL breadcrumb (the no-pane-id fallback path)."""
    _breadcrumb(state.user_presence_path(home), last_input_epoch)
    return home


def _pane_presence(home: Path, last_input_epoch: int, *, pane: str = "%3") -> Path:
    """Write THIS pane's own breadcrumb (the primary per-pane path)."""
    key = state.terminal_pane_key({"TMUX_PANE": pane})
    assert key is not None
    _breadcrumb(state.per_pane_presence_path(key, home), last_input_epoch)
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


# presence — PER PANE (the primary path, user directive 2026-07-16)


def test_recent_input_in_this_pane_means_present(tmp_path: Path) -> None:
    """Submitted in THIS pane 5s ago (< the 10-second window) → present."""
    home = _pane_presence(tmp_path, NOW - 5)
    assert user_intent.user_is_present(home=home, now=NOW, env=PANE_A)


def test_silence_past_window_in_this_pane_means_away(tmp_path: Path) -> None:
    """Last submit in THIS pane was past the 10-second window → away."""
    home = _pane_presence(tmp_path, NOW - user_intent.USER_PRESENT_IDLE_S - 1)
    assert not user_intent.user_is_present(home=home, now=NOW, env=PANE_A)


def test_window_is_ten_seconds(tmp_path: Path) -> None:
    """The window is exactly 10 s (owner directive 2026-07-17): at the edge = present, one second
    past = away."""
    assert user_intent.USER_PRESENT_IDLE_S == 10
    edge = _pane_presence(tmp_path, NOW - 10)
    assert user_intent.user_is_present(home=edge, now=NOW, env=PANE_A)
    past = _pane_presence(tmp_path, NOW - 11)
    assert not user_intent.user_is_present(home=past, now=NOW, env=PANE_A)


def test_never_typed_in_this_pane_means_away_despite_global(tmp_path: Path) -> None:
    """THE per-pane fix: a pane with no breadcrumb of its own is UNATTENDED and self-trigger is
    allowed — even though the machine-global breadcrumb (some OTHER pane's activity) says present."""
    _presence(tmp_path, NOW - 10)  # a human typed 10s ago — but in some OTHER pane
    assert not user_intent.user_is_present(home=tmp_path, now=NOW, env=PANE_A)


def test_activity_in_pane_A_does_not_mark_pane_B_present(tmp_path: Path) -> None:
    """Cross-pane isolation: the user hammering pane A must not block pane B's self-trigger."""
    _pane_presence(tmp_path, NOW - 5, pane="%3")  # pane A active right now
    assert user_intent.user_is_present(home=tmp_path, now=NOW, env=PANE_A)  # A: present
    assert not user_intent.user_is_present(home=tmp_path, now=NOW, env=PANE_B)  # B: away


def test_corrupt_per_pane_breadcrumb_fails_CLOSED(tmp_path: Path) -> None:
    """A corrupt (not merely absent) per-pane breadcrumb → assume present. Absence is 'away'; a
    parse error is a breadcrumb PROBLEM and must never license typing."""
    key = state.terminal_pane_key(PANE_A)
    assert key is not None
    p = state.per_pane_presence_path(key, tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json")
    assert user_intent.user_is_present(home=tmp_path, now=NOW, env=PANE_A)


# presence — machine-GLOBAL fallback (no pane id, e.g. a plain terminal)


def test_global_fallback_recent_input_means_present(tmp_path: Path) -> None:
    home = _presence(tmp_path, NOW - 5)
    assert user_intent.user_is_present(home=home, now=NOW, env=NO_PANE)


def test_global_fallback_long_silence_means_away(tmp_path: Path) -> None:
    home = _presence(tmp_path, NOW - user_intent.USER_PRESENT_IDLE_S - 1)
    assert not user_intent.user_is_present(home=home, now=NOW, env=NO_PANE)


def test_global_fallback_missing_breadcrumb_fails_CLOSED(tmp_path: Path) -> None:
    """Unknown presence → assume the user IS there. A breadcrumb problem must never license typing
    into someone's pane; the cost of being wrong that way is destroying their input."""
    assert user_intent.user_is_present(home=tmp_path, now=NOW, env=NO_PANE)


def test_global_fallback_corrupt_breadcrumb_fails_CLOSED(tmp_path: Path) -> None:
    _breadcrumb(state.user_presence_path(tmp_path), 0)
    state.user_presence_path(tmp_path).write_text("{ not json")
    assert user_intent.user_is_present(home=tmp_path, now=NOW, env=NO_PANE)


# --------------------------------------------------------------------------- #
# the gate — inject only when the user is away, or when the user asked
# --------------------------------------------------------------------------- #


def test_injection_refused_while_user_present_and_silent(tmp_path: Path, sdir: Path) -> None:
    """The bug that truncated the user's message: a [janitor-reload] marker typed /reload-plugins
    into their pane while they were writing. Present IN THIS PANE, no request → refuse."""
    home = _pane_presence(tmp_path, NOW - 10)
    allowed, why = user_intent.injection_allowed(["/reload-plugins --force"], state_dir=sdir, home=home, now=NOW, env=PANE_A)
    assert not allowed
    assert "did not ask" in why


def test_injection_allowed_when_user_is_away(tmp_path: Path, sdir: Path) -> None:
    """The unattended case self-injection exists for — silent in THIS pane, nobody to clobber."""
    home = _pane_presence(tmp_path, NOW - user_intent.USER_PRESENT_IDLE_S - 1)
    allowed, _ = user_intent.injection_allowed(["/reload-plugins --force"], state_dir=sdir, home=home, now=NOW, env=PANE_A)
    assert allowed


def test_injection_allowed_in_this_pane_when_other_pane_is_busy(tmp_path: Path, sdir: Path) -> None:
    """The overnight-fleet fix: the user is active in pane A, but pane B (this one) has no keystrokes
    of its own → B's self-trigger is allowed. Before per-pane keying this was blocked machine-wide."""
    _pane_presence(tmp_path, NOW - 5, pane="%3")  # the user is hammering pane A
    allowed, why = user_intent.injection_allowed(["/reload-plugins --force"], state_dir=sdir, home=tmp_path, now=NOW, env=PANE_B)
    assert allowed
    assert "away" in why


def test_injection_allowed_when_present_user_asked(tmp_path: Path, sdir: Path) -> None:
    """A present user who TYPED the command must still get it — the gate protects them, not blocks them."""
    home = _pane_presence(tmp_path, NOW - 5)
    user_intent.record_intent_from_prompt("/reload-plugins", state_dir=sdir, now=NOW)
    allowed, why = user_intent.injection_allowed(["/reload-plugins --force"], state_dir=sdir, home=home, now=NOW, env=PANE_A)
    assert allowed
    assert "explicitly asked" in why


def test_one_request_authorizes_exactly_one_injection(tmp_path: Path, sdir: Path) -> None:
    """The token is CONSUMED. Otherwise one `/reload-plugins` would license every injection for the
    next 10 minutes — a standing licence is not what the user granted."""
    home = _pane_presence(tmp_path, NOW - 5)
    user_intent.record_intent_from_prompt("/reload-plugins", state_dir=sdir, now=NOW)
    first, _ = user_intent.injection_allowed(["/reload-plugins --force"], state_dir=sdir, home=home, now=NOW, env=PANE_A)
    second, _ = user_intent.injection_allowed(["/reload-plugins --force"], state_dir=sdir, home=home, now=NOW, env=PANE_A)
    assert first
    assert not second, "the intent token must be spent, not standing"


def test_intent_for_one_verb_does_not_authorize_another(tmp_path: Path, sdir: Path) -> None:
    """Asking to reload plugins is not consent to ESC-interrupt the turn and compact the context."""
    home = _pane_presence(tmp_path, NOW - 5)
    user_intent.record_intent_from_prompt("/reload-plugins", state_dir=sdir, now=NOW)
    allowed, _ = user_intent.injection_allowed(["/compact"], state_dir=sdir, home=home, now=NOW, env=PANE_A)
    assert not allowed


def test_env_override_tunes_the_window(tmp_path: Path, sdir: Path) -> None:
    """CLAUDE_PLUGIN_OPTION_SELF_TRIGGER_PRESENCE_IDLE_S tunes the window; a value ≤0 coerces back
    to the 10-second default so the gate can never be silently disabled to 0s."""
    home = _pane_presence(tmp_path, NOW - 8)  # submitted 8s ago in this pane
    tight = {**PANE_A, "CLAUDE_PLUGIN_OPTION_SELF_TRIGGER_PRESENCE_IDLE_S": "4"}
    allowed, _ = user_intent.injection_allowed(["/reload-plugins --force"], state_dir=sdir, home=home, now=NOW, env=tight)
    assert allowed, "a 4s window makes 8s-ago AWAY"
    coerced = {**PANE_A, "CLAUDE_PLUGIN_OPTION_SELF_TRIGGER_PRESENCE_IDLE_S": "0"}
    allowed2, _ = user_intent.injection_allowed(["/reload-plugins --force"], state_dir=sdir, home=home, now=NOW, env=coerced)
    assert not allowed2, "≤0 coerces to the 10s default, so 8s-ago is PRESENT"
