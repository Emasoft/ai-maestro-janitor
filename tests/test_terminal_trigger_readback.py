"""Read-back verification for pane injection (owner directive 2026-08-02).

*"the injector must be improved. it must wait for the input prompt field to be empty. also
after injecting, it must not press enter immediately, but reread to verify that only the
command (in the form `/any-command`) should be displayed on the input prompt field. no spaces
before or after the `/` char. only then it should send the enter keypress. otherwise it should
simply try again every 5 seconds, until the field is empty again."*

Typing blind is destructive in two directions: our text is spliced into whatever the user was
drafting, and the Enter we send submits the mangled result under their name.

EVERY constant here was taken from a REAL `iTerm2 → contents of session` capture of a live
Claude Code prompt, not from documentation — and that mattered, because the marker is `❯`
followed by U+00A0 NO-BREAK SPACE. `startswith("❯ ")` with an ASCII space never matches.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import terminal_trigger as tt  # noqa: E402

NBSP = " "


def _pane(field: str) -> str:
    """A capture shaped like the real one: box rule, marker + NBSP + field, box rule."""
    return "some earlier output\n" + "─" * 40 + f"\n❯{NBSP}{field}\n" + "─" * 40 + "\n"


def test_field_is_extracted_from_the_real_prompt_shape() -> None:
    assert tt.extract_prompt_field(_pane("/compact")) == "/compact"
    assert tt.extract_prompt_field(_pane("")) == ""


def test_unreadable_pane_is_never_reported_empty() -> None:
    """None means "could not read" and must stay distinct from "" (empty). Conflating them
    would make an unreadable pane look free to type into — unknown is never a licence."""
    assert tt.extract_prompt_field("no prompt anywhere") is None
    assert tt.prompt_field_is_empty("no prompt anywhere") is False


def test_only_the_exact_command_passes() -> None:
    assert tt.prompt_field_shows_only(_pane("/compact"), "/compact") is True
    assert tt.prompt_field_shows_only(_pane("/compact   "), "/compact") is True, "trailing pad ok"


def test_a_leading_space_before_the_slash_is_REJECTED() -> None:
    """The owner's rule, literally: "no spaces before or after the `/` char".

    Caught by a real capture during development. The marker's separator is U+00A0, so an
    ASCII space after it is something the USER or a botched paste put there — and an earlier
    `.strip()` silently normalised " /compact" to "/compact" and let it pass. Claude Code
    treats a leading-space line as prose, so submitting it would post the command as chat."""
    assert tt.prompt_field_shows_only(_pane(" /compact"), "/compact") is False
    assert tt.prompt_field_shows_only(_pane("/ compact"), "/compact") is False


def test_user_text_in_the_field_blocks_submission() -> None:
    """The harm this exists to prevent: the user was mid-sentence and our command landed in
    their draft. Pressing Enter would submit the splice as if they wrote it."""
    assert tt.prompt_field_shows_only(_pane("hello /compact"), "/compact") is False
    assert tt.prompt_field_shows_only(_pane("/compact and then some"), "/compact") is False
    assert tt.prompt_field_shows_only(_pane("/compact/compact"), "/compact") is False


def test_a_wrapped_multiline_entry_is_read_whole() -> None:
    """A long draft wraps past the marker line; reading only that line would see a prefix that
    might look like our command and submit on top of the user's text."""
    text = "some output\n" + "─" * 40 + f"\n❯{NBSP}/compact\nplus more the user typed\n" + "─" * 40
    assert tt.prompt_field_shows_only(text, "/compact") is False


def test_the_LAST_prompt_wins_over_scrollback() -> None:
    """Scrollback holds earlier prompts. Only the live field matters; matching an old one
    would verify against a screenshot of the past."""
    stale = _pane("/compact")
    live = "\n" + "─" * 40 + f"\n❯{NBSP}user is typing now\n" + "─" * 40
    assert tt.prompt_field_shows_only(stale + live, "/compact") is False


def test_wait_for_empty_polls_until_the_field_clears() -> None:
    reads = iter([_pane("still typing"), _pane("still typing"), _pane("")])
    slept: list[float] = []
    ok, why = tt.wait_for_empty_prompt(
        {"kind": "tmux", "pane": "%1"},
        reader=lambda _t: next(reads), sleeper=slept.append, clock=lambda: 0.0,
    )
    assert ok, why
    assert slept == [5.0, 5.0], "the owner asked for a 5s retry interval"


def test_wait_for_empty_refuses_on_an_UNREADABLE_channel() -> None:
    """wtype/xdotool are write-only key injectors — nothing can be read back. Returning
    "go ahead" there would be blind typing with a verification badge on it."""
    ok, why = tt.wait_for_empty_prompt(
        {"kind": "wtype"}, reader=lambda _t: None, sleeper=lambda _s: None, clock=lambda: 0.0
    )
    assert ok is False
    assert "not readable" in why


def test_wait_for_empty_gives_up_rather_than_hanging_forever() -> None:
    """"until the field is empty again" cannot be literally unbounded: this runs inside hooks
    and a daemon beat, and a wait that never returns is its own outage. Bounded, and the
    timeout is reported rather than silently treated as success."""
    clock = iter([0.0, 999.0])
    ok, why = tt.wait_for_empty_prompt(
        {"kind": "tmux", "pane": "%1"}, timeout_s=10.0,
        reader=lambda _t: _pane("busy"), sleeper=lambda _s: None, clock=lambda: next(clock),
    )
    assert ok is False
    assert "still busy" in why


def test_enter_is_sent_ONLY_after_the_field_verifies() -> None:
    sent: list[str] = []
    ok, _ = tt.verify_then_submit(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        submit=lambda: sent.append("Enter"),
        reader=lambda _t: _pane("/compact"), sleeper=lambda _s: None,
    )
    assert ok and sent == ["Enter"]


def test_enter_is_NOT_sent_when_the_field_never_settles() -> None:
    """The safe failure is leaving the text in the field for the user to see and fix.
    Pressing Enter on an unverified field commits whatever is there, under their name."""
    sent: list[str] = []
    ok, why = tt.verify_then_submit(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        submit=lambda: sent.append("Enter"),
        reader=lambda _t: _pane("user's half-written sentence"), sleeper=lambda _s: None,
    )
    assert ok is False
    assert sent == [], "Enter was pressed on an unverified field"
    assert "NOT submitting" in why


# --- persistence: presence DEFERS, never cancels (owner refinement 2026-08-02) -------------
#
# *"even if the user is reported as present, it should not stop the command! it should simply
# retry every 8 seconds! ... after 8 seconds without the user typing, then it should try again
# ... if it fails, it should retry after 5 seconds. until the command is successfully sent."*


def _seq(*items):
    it = iter(items)
    return lambda _t=None: next(it)


def test_a_present_user_DEFERS_the_command_instead_of_cancelling_it() -> None:
    """THE correction. The old contract discarded the command the moment anyone touched the
    keyboard — which is how the user who typed `/janitor-handoff-and-clear` themselves got
    `USER_PRESENT` and nothing else. Waiting costs seconds; discarding costs the request."""
    typing = iter([True, True, False])
    slept: list[float] = []
    sent: list[str] = []
    ok, why = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: sent.append("Enter"),
        reader=_seq(_pane(""), _pane("/compact")),
        is_typing=lambda _t: next(typing),
        sleeper=slept.append, clock=lambda: 0.0,
    )
    assert ok, why
    assert sent == ["Enter"]
    assert slept[:2] == [8.0, 8.0], "must defer in 8s steps while the user types"


def test_a_busy_field_retries_after_5_seconds_and_eventually_sends() -> None:
    slept: list[float] = []
    sent: list[str] = []
    ok, _ = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: sent.append("Enter"),
        reader=_seq(_pane("half a sentence"), _pane(""), _pane("/compact")),
        is_typing=lambda _t: False, sleeper=slept.append, clock=lambda: 0.0,
    )
    assert ok and sent == ["Enter"]
    assert slept == [5.0], "a FAILED attempt retries after 5s, per the directive"


def test_a_failed_verify_retries_rather_than_pressing_enter() -> None:
    """The two intervals are different on purpose: 8s is 'the human is typing, wait for them',
    5s is 'that attempt did not take, try again'. Collapsing them would lose the distinction the
    directive draws."""
    slept: list[float] = []
    sent: list[str] = []
    ok, _ = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: sent.append("Enter"),
        clear_fn=lambda: None,
        # empty -> type -> read back MANGLED -> clear -> retry -> empty -> type -> clean -> send
        reader=_seq(_pane(""), _pane("xx/compact"), _pane(""), _pane("/compact")),
        is_typing=lambda _t: False, sleeper=slept.append, clock=lambda: 0.0,
    )
    assert ok and sent == ["Enter"]
    assert slept == [5.0]


def test_presence_is_rechecked_every_pass_not_once() -> None:
    """The user can start typing between the quiet check and the read-back — exactly the window
    where blind typing splices into their sentence. A one-shot check at the top would miss it."""
    typing = iter([False, True, False])
    sent: list[str] = []
    ok, _ = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: sent.append("Enter"),
        reader=_seq(_pane("busy"), _pane(""), _pane("/compact")),
        is_typing=lambda _t: next(typing), sleeper=lambda _s: None, clock=lambda: 0.0,
    )
    assert ok and sent == ["Enter"]
    assert list(typing) == [], "every pass must consult presence again"


def test_it_gives_up_LOUDLY_rather_than_looping_forever() -> None:
    """"until sent" cannot be literally unbounded here: this runs inside hooks and a daemon
    beat, so a call that never returns is not persistence, it is an outage that also silences
    the heartbeat. Bounded, and the give-up is reported — never a silent success."""
    clock = iter([0.0, 0.0, 9999.0])
    sent: list[str] = []
    ok, why = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: sent.append("Enter"),
        reader=lambda _t: _pane("permanently busy"),
        is_typing=lambda _t: False, sleeper=lambda _s: None,
        clock=lambda: next(clock), giveup_s=10.0,
    )
    assert ok is False and sent == []
    assert "gave up" in why and "not empty" in why


def test_an_unreadable_channel_reports_instead_of_spinning() -> None:
    """wtype/xdotool cannot be read back at all. Retrying cannot make them readable, so looping
    would just burn an hour pretending to verify."""
    ok, why = tt.inject_until_sent(
        {"kind": "wtype"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: None,
        reader=lambda _t: None, is_typing=lambda _t: False,
        sleeper=lambda _s: None, clock=lambda: 0.0,
    )
    assert ok is False and "not readable" in why


# --- the owner's worked example, walked step by step (2026-08-02) --------------------------


def test_the_owners_worked_example_end_to_end() -> None:
    """User is composing a prompt, pauses 8s, we check, field is busy, we wait 5s and re-check
    until they press Enter; then the field is empty, we inject, verify, and send.

    Written from the owner's own narration so each step is pinned by the sentence that asked
    for it, rather than by my reading of it."""
    slept: list[float] = []
    sent: list[str] = []
    reads = _seq(
        _pane("the user is composing"),   # paused 8s, but field is FULL -> do nothing
        _pane("the user is composing"),   # +5s, still composing
        _pane(""),                        # they pressed Enter -> field empty
        _pane("/compact"),                # our injection, clean
    )
    ok, why = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: sent.append("Enter"),
        clear_fn=lambda: None,
        reader=reads, is_typing=lambda _t: False,
        sleeper=slept.append, clock=lambda: 0.0,
    )
    assert ok, why
    assert sent == ["Enter"], "Enter only after the form verified"
    assert slept == [5.0, 5.0], "busy field re-checks every 5s until it clears"


def test_a_malformed_injection_is_CLEARED_or_the_loop_deadlocks_on_its_own_text() -> None:
    """The step the worked example added, and the bug it exposed in my first draft.

    After a malformed injection OUR OWN text is in the field. The next pass's empty-check then
    sees it, waits, sees it again — forever. The loop could recover from the user being busy but
    never from its own failed write. Clearing is what closes that."""
    cleared: list[str] = []
    sent: list[str] = []
    reads = _seq(
        _pane(""),              # empty -> type
        _pane("/comp"),         # MALFORMED (truncated)
        _pane(""),              # after clear_fn -> empty again
        _pane("/compact"),      # retype, clean
    )
    ok, _ = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: sent.append("Enter"),
        clear_fn=lambda: cleared.append("C-u"),
        reader=reads, is_typing=lambda _t: False,
        sleeper=lambda _s: None, clock=lambda: 0.0,
    )
    assert ok and sent == ["Enter"]
    assert cleared == ["C-u"], "the malformed text must be cleared before retrying"


def test_without_a_clear_fn_it_refuses_rather_than_spinning_on_its_own_garbage() -> None:
    """Fail loudly instead of burning the give-up window re-reading text we put there."""
    ok, why = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: None, clear_fn=None,
        reader=_seq(_pane(""), _pane("/comp")),
        is_typing=lambda _t: False, sleeper=lambda _s: None, clock=lambda: 0.0,
    )
    assert ok is False
    assert "no clear_fn" in why


def test_clear_uses_kill_line_not_ESC() -> None:
    """ESC in Claude Code INTERRUPTS the turn. Tidying up after our own bad injection must not
    have that side effect, so the clear is `C-a C-k C-u`, never Escape."""
    steps = tt.build_clear_field_steps({"kind": "tmux", "pane": "%1"})
    assert steps is not None
    flat = " ".join(tok for s in steps for tok in s)
    assert "Escape" not in flat
    assert "C-u" in flat
    assert tt.build_clear_field_steps({"kind": "wtype"}) is None


def test_the_DEFAULT_presence_probe_is_callable(monkeypatch) -> None:
    """Regression for a bug my own tests could not have caught.

    Every other test here injects `is_typing=...`, so the PRODUCTION path — `is_typing=None`,
    which falls back to the internal probe — was never exercised. A refactor left the loop
    calling the parameter instead of the resolved probe, so real callers would have died on
    `None is not callable` while the whole suite stayed green.

    The lesson generalises: a default that no test uses is untested code on the hot path."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/nonexistent-for-this-test")
    sent: list[str] = []
    ok, why = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: sent.append("Enter"),
        clear_fn=lambda: None,
        reader=_seq(_pane(""), _pane("/compact")),
        # is_typing deliberately NOT passed — that is the whole point.
        sleeper=lambda _s: None, clock=lambda: 0.0,
    )
    assert ok, why
    assert sent == ["Enter"]


def test_user_typing_DURING_injection_backs_off_and_never_clears_their_text() -> None:
    """The dangerous case, and the reason the typing check sits BEFORE `clear_fn`.

    Owner, 2026-08-02: *"if the user typed anything between the injection and the verification,
    even if the input field is malformed, it should stop and retry after 8 seconds"*.

    If the field is malformed because the USER started typing into it, then their keystrokes are
    what is in there. Clearing would delete what they just wrote — a cosmetic retry turned into
    data loss. So: back off the full 8s QUIET window, clear NOTHING, and start over."""
    # pass 1: not typing -> empty -> inject; but by read-back the user HAS typed -> back off.
    # pass 2: quiet again -> empty -> inject -> clean -> send.
    typing = iter([False, True, False, False])
    cleared: list[str] = []
    slept: list[float] = []
    sent: list[str] = []
    ok, why = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: sent.append("Enter"),
        clear_fn=lambda: cleared.append("C-u"),
        reader=_seq(_pane(""), _pane("/compact but the user kept typing"),
                    _pane(""), _pane("/compact")),
        is_typing=lambda _t: next(typing),
        sleeper=slept.append, clock=lambda: 0.0,
    )
    assert ok, why
    assert cleared == [], "the user's own keystrokes must NEVER be cleared"
    assert 8.0 in slept, "must back off the QUIET window (8s), not the 5s retry"
    assert sent == ["Enter"]


def test_a_malformed_field_with_the_user_QUIET_is_still_cleared() -> None:
    """The complement — otherwise the fix above would disable recovery entirely. When the user
    is NOT typing, a malformed field is OUR garbage and clearing it is exactly right."""
    cleared: list[str] = []
    sent: list[str] = []
    ok, _ = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: sent.append("Enter"),
        clear_fn=lambda: cleared.append("C-u"),
        reader=_seq(_pane(""), _pane("/comp"), _pane(""), _pane("/compact")),
        is_typing=lambda _t: False, sleeper=lambda _s: None, clock=lambda: 0.0,
    )
    assert ok and sent == ["Enter"]
    assert cleared == ["C-u"], "our own malformed text must still be cleared"
