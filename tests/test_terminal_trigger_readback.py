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


def test_a_busy_field_rechecks_after_8_seconds_and_eventually_sends() -> None:
    """RULE 1: *"inject the command only when the input field is empty, otherwise recheck after
    8 seconds"*. The two intervals are different on purpose — 8s is "a human is composing, wait
    for them", 5s is "our own attempt did not take". A busy field is the FORMER."""
    slept: list[float] = []
    sent: list[str] = []
    ok, _ = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: sent.append("Enter"),
        clear_fn=lambda: None,
        reader=_seq(_pane("half a sentence"), _pane(""), _pane("/compact")),
        is_typing=lambda _t: False, sleeper=slept.append, clock=lambda: 0.0,
    )
    assert ok and sent == ["Enter"]
    assert slept == [8.0], "a non-empty field means a human is composing — wait the 8s window"


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
    assert slept == [8.0, 8.0], "busy field re-checks every 8s until the human submits"


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


def test_the_8s_quiet_window_gates_the_WHOLE_procedure_not_just_the_typing() -> None:
    """*"the procedure is not started if the user has typed anything in the last 8 seconds.
    8 seconds before must be free of any user typing, only then the procedure start and the
    input field checked"* (owner, 2026-08-02).

    So the quiet check STRICTLY PRECEDES the field read — the pane is not even inspected while
    a human is mid-keystroke. Asserted by ordering, not by outcome: the reader must not be
    called at all on a pass where the user is typing."""
    reads: list[str] = []

    def _reader(_t):
        reads.append("read")
        return _pane("")

    typing = iter([True, True, False])
    slept: list[float] = []
    sent: list[str] = []
    ok, _ = tt.wait_until_pane_free(
        {"kind": "tmux", "pane": "%1"},
        reader=_reader, is_typing=lambda _t: next(typing),
        sleeper=slept.append, clock=lambda: 0.0,
    )
    assert ok
    assert slept == [8.0, 8.0], "two typing passes -> two 8s waits"
    assert reads == ["read"], "the pane must NOT be read while the user is typing"
    assert sent == []


def test_a_keystroke_RESETS_the_window_it_does_not_merely_delay_it() -> None:
    """*"any human keystroke resets the counter. 8 seconds must be counted before the procedure
    is started. if an user type anything, the counter restarts from 0."*  (owner, 2026-08-02).

    There is no counter variable to reset, and that is the design: the probe reads the HID idle
    timer — *time since the last keystroke* — so the window restarts at every key by
    construction. A hand-rolled countdown is what would drift, because it can only observe the
    keystrokes that happen to land while it is looking.

    Asserted by ORDERING over four consecutive typing passes: each one must produce a fresh full
    window and NO pane read. A loop that merely delayed once and then proceeded would read the
    pane on pass 2 — which is the regression this pins."""
    log: list[str] = []
    typing = iter([True, True, True, True, False])

    def _probe(_t):
        t = next(typing)
        log.append(f"probe={t}")
        return t

    def _reader(_t):
        log.append("read")
        return _pane("")

    ok, _ = tt.wait_until_pane_free(
        {"kind": "tmux", "pane": "%1"},
        reader=_reader, is_typing=_probe,
        sleeper=lambda s: log.append(f"wait{s:.0f}"), clock=lambda: 0.0,
    )
    assert ok
    assert log == [
        "probe=True", "wait8", "probe=True", "wait8",
        "probe=True", "wait8", "probe=True", "wait8",
        "probe=False", "read",
    ], "every keystroke must restart a FULL window, and never a pane read while typing"


def test_an_abort_mid_procedure_restarts_the_window_it_does_not_resume() -> None:
    """The second half of the same directive: *"if the procedure was already started, it must be
    stopped immediately and the counter reset again."*

    So after a mid-injection abort the loop must go back to the TOP — probing for quiet before it
    touches the pane again — rather than resuming at the retry it was in the middle of. Ordering
    proves it: the event right after the abort is a `probe`, and the wait is the 8 s QUIET window,
    never the 5 s OUR-failed-attempt retry."""
    log: list[str] = []
    typing = iter([False, True, False, False])
    reads = iter([_pane(""), _pane("/compact half-typed by a human"), _pane(""), _pane("/compact")])

    def _probe(_t):
        t = next(typing)
        log.append(f"probe={t}")
        return t

    def _reader(_t):
        log.append("read")
        return next(reads)

    sent: list[str] = []
    ok, why = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: log.append("type"), submit_fn=lambda: sent.append("Enter"),
        clear_fn=lambda: log.append("CLEAR"),
        reader=_reader, is_typing=_probe,
        sleeper=lambda s: log.append(f"wait{s:.0f}"), clock=lambda: 0.0,
    )
    assert ok, why
    assert log == [
        "probe=False", "read", "type", "read",   # injected, then the human typed
        "probe=True", "wait8",                   # STOP: no cleanup, full window restarts
        "probe=False", "read", "type", "read",   # start over from the top
    ], "an abort must re-enter the quiet window, not resume the 5s retry"
    assert "CLEAR" not in log, "the user's own keystrokes must never be cleared"
    assert sent == ["Enter"]


# --- TRDD-0BVF4K7E: the chained injector's building blocks -------------------


def test_typing_and_ENTER_are_separate_acts_or_rule_3_cannot_exist() -> None:
    """The whole reason these builders exist. `build_tmux_steps` FUSES type+Enter, which is
    right for a blind send and unusable for a verified one — by the time we could look at
    the field, the command has already run. Rule 3 verifies BETWEEN the two, so they must
    be separable."""
    t = {"kind": "tmux", "pane": "%1"}
    typed = tt.build_type_only_steps(t, "/clear")
    assert typed == [["RUN", "tmux", "send-keys", "-t", "%1", "-l", "/clear"]]
    assert not any("Enter" in step for step in typed), "typing must NOT submit"
    assert tt.build_submit_steps(t) == [["RUN", "tmux", "send-keys", "-t", "%1", "Enter"]]


def test_literal_flag_is_present_or_a_command_becomes_a_KEYSTROKE() -> None:
    """`-l` is load-bearing: without it tmux reads the text as KEY NAMES, so typing a
    command containing `Enter` would send the Enter KEY instead of the characters."""
    steps = tt.build_type_only_steps({"kind": "tmux", "pane": "%1"}, "/janitor-resume")
    assert "-l" in steps[0], "missing -l turns typed text into key names"


def test_a_newline_is_REFUSED_not_escaped() -> None:
    """A newline would submit on its own and defeat the split — so it cannot be accepted at
    all. Refusing is the only safe handling; escaping would silently produce a blind send."""
    for bad in ("/clear\n/janitor-arm", "/clear\r"):
        try:
            tt.build_type_only_steps({"kind": "tmux", "pane": "%1"}, bad)
        except ValueError:
            continue
        raise AssertionError(f"a newline must be refused, not accepted: {bad!r}")


def test_write_only_channels_report_unsupported_rather_than_pretending() -> None:
    """wtype/xdotool cannot be read back, so a verified injection is impossible there. They
    must return None (the caller reports "cannot verify"), never a plausible step list."""
    for t in ({"kind": "wtype"}, {"kind": "xdotool"}, {"kind": "unknown"}):
        assert tt.build_type_only_steps(t, "/clear") is None
        assert tt.build_submit_steps(t) is None


def test_a_tampered_pane_or_session_id_reaches_NO_argv() -> None:
    """Both ids are interpolated — the pane into an argv, the session id into an AppleScript
    string literal. An invalid one must yield None, not a command built around it."""
    assert tt.build_type_only_steps({"kind": "tmux", "pane": "-x; rm -rf /"}, "/clear") is None
    assert tt.build_submit_steps({"kind": "tmux", "pane": "$(whoami)"}) is None
    assert tt.build_type_only_steps({"kind": "iterm", "session_id": 'x" & do shell script "'}, "/c") is None


def test_the_fresh_session_gate_waits_for_a_STRICTLY_NEWER_stamp(tmp_path) -> None:
    """Phase B chains on this, not on a clock. The baseline is captured BEFORE /clear is
    typed, so a stamp left by an EARLIER clear must not satisfy it — otherwise the bootstrap
    fires into the un-cleared session, which is the stranding bug this design exists to
    avoid."""
    stamp = tmp_path / "clear-observed.ts"
    stamp.write_text("1000", encoding="utf-8")
    ticks = iter([0.0, 1.0, 2.0, 3.0, 99.0])
    assert tt._await_fresh_session(
        stamp, 1000, timeout_s=10, sleeper=lambda _s: None, clock=lambda: next(ticks)
    ) is False, "an OLD stamp equal to the baseline must not satisfy the gate"

    stamp.write_text("1001", encoding="utf-8")
    assert tt._await_fresh_session(
        stamp, 1000, timeout_s=10, sleeper=lambda _s: None, clock=lambda: 0.0
    ) is True


def test_an_absent_or_corrupt_stamp_reads_as_NOT_YET_never_as_ready(tmp_path) -> None:
    """Absent = the fresh session has not started; corrupt = we cannot tell. Both must mean
    "keep waiting". Treating either as ready would submit the bootstrap blind."""
    missing = tmp_path / "nope.ts"
    assert tt._await_fresh_session(
        missing, 0, timeout_s=1, sleeper=lambda _s: None, clock=iter([0.0, 9.0]).__next__
    ) is False
    corrupt = tmp_path / "corrupt.ts"
    corrupt.write_text("not-a-number", encoding="utf-8")
    assert tt._await_fresh_session(
        corrupt, 0, timeout_s=1, sleeper=lambda _s: None, clock=iter([0.0, 9.0]).__next__
    ) is False
