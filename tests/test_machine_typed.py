"""TRDD-9ORKPQCX: the janitor's own typed commands must not mint the owner's consent tokens.

The typer leaves a one-shot crumb (`<state_dir>/machine-typed/<crumb_id>.json`) BEFORE it types a
command; the UserPromptSubmit hook spends it. Everything here runs on real files under tmp_path;
the only seams are the ones the production code already exposes (`type_fn`, `reader`,
`fleet_inject.fire`), which stand in for the keystroke itself.

`machine-typed/` is not a security boundary (anything that can write the state dir can already
forge consent through user-intent-*.ts); a crumb only adds a one-shot denial. The disarm_guard
half of the guarantee (a kill-switch with no intent file authorizes as "global-stop") is already
pinned by tests/test_disarm_guard.py::test_a_machine_wide_stop_authorizes_the_self_disarm.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import fleet_inject  # type: ignore[import-not-found]  # noqa: E402
import fleet_scan  # type: ignore[import-not-found]  # noqa: E402
import pane_actuate as pa  # type: ignore[import-not-found]  # noqa: E402
import state  # type: ignore[import-not-found]  # noqa: E402
import terminal_trigger as tt  # type: ignore[import-not-found]  # noqa: E402
import user_intent  # type: ignore[import-not-found]  # noqa: E402

_FIXTURES = _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames"
_TYPED = [
    "/clear",
    "/janitor-arm",
    "/janitor-resume",
    "/reload-plugins --force",
    "/reload-skills",
    "/model opus",
    "/goal some text",
    "/janitor-disarm",
    "/janitor-pause",
]


def _crumbs(state_dir: Path) -> list[Path]:
    return sorted((state_dir / "machine-typed").glob("*.json"))


def test_note_then_spend_consumes_the_crumb(tmp_path: Path) -> None:
    """A noted command is recognised once; the crumb file is gone and a second spend is False."""
    user_intent.note_machine_typed("/clear", tmp_path, "a1")
    assert len(_crumbs(tmp_path)) == 1
    assert user_intent.spend_machine_typed("/clear", tmp_path) is True
    assert _crumbs(tmp_path) == []
    assert user_intent.spend_machine_typed("/clear", tmp_path) is False


def test_two_notes_of_the_same_text_are_each_consumed_by_one_spend(tmp_path: Path) -> None:
    """Two typed copies need two crumbs: both prompts are suppressed, the third is not, and the
    first spend removes exactly ONE file (never every match)."""
    user_intent.note_machine_typed("/janitor-arm", tmp_path, "a", now=1000)
    user_intent.note_machine_typed("/janitor-arm", tmp_path, "b", now=1001)
    assert user_intent.spend_machine_typed("/janitor-arm", tmp_path, now=1002) is True
    assert len(_crumbs(tmp_path)) == 1, "a spend must remove exactly one matching crumb"
    assert user_intent.spend_machine_typed("/janitor-arm", tmp_path, now=1003) is True
    assert user_intent.spend_machine_typed("/janitor-arm", tmp_path, now=1004) is False


def test_the_oldest_matching_crumb_is_spent_first(tmp_path: Path) -> None:
    """Oldest first, so the newer crumb (the one still waiting for its prompt) survives."""
    user_intent.note_machine_typed("/clear", tmp_path, "new", now=2000)
    user_intent.note_machine_typed("/clear", tmp_path, "old", now=1000)
    assert user_intent.spend_machine_typed("/clear", tmp_path, now=2001) is True
    assert [p.stem for p in _crumbs(tmp_path)] == ["new"]


def test_an_expired_crumb_is_pruned_and_does_not_suppress(tmp_path: Path) -> None:
    """Past the TTL the crumb is deleted by the spend and the prompt is treated as a human's."""
    user_intent.note_machine_typed("/clear", tmp_path, "a", now=1000)
    late = 1000 + user_intent.MACHINE_TYPED_TTL_S + 1
    assert user_intent.spend_machine_typed("/clear", tmp_path, now=late) is False
    assert _crumbs(tmp_path) == []


def test_a_crumb_for_a_different_text_does_not_suppress(tmp_path: Path) -> None:
    """The crumb is bound to the exact command text; another prompt neither matches nor spends it."""
    user_intent.note_machine_typed("/clear", tmp_path, "a", now=1000)
    assert user_intent.spend_machine_typed("/janitor-disarm", tmp_path, now=1001) is False
    assert len(_crumbs(tmp_path)) == 1


def test_a_spend_ten_minutes_after_the_note_still_matches(tmp_path: Path) -> None:
    """A soft send can be dequeued minutes later; the 2 h TTL must cover it."""
    user_intent.note_machine_typed("/clear", tmp_path, "a", now=1000)
    assert user_intent.spend_machine_typed("/clear", tmp_path, now=1000 + 600) is True


@pytest.mark.parametrize("command", _TYPED)
def test_normalization_matches_a_prompt_with_surrounding_whitespace(tmp_path: Path, command: str) -> None:
    """The hook may receive the typed line with leading spaces, a trailing newline, or leading
    blank lines and later lines; each reduces to the command the typer noted (first non-empty line)."""
    user_intent.note_machine_typed(command, tmp_path, "plain", now=1000)
    assert user_intent.spend_machine_typed(f"  {command}\n", tmp_path, now=1001) is True
    user_intent.note_machine_typed(command, tmp_path, "blank-led", now=1000)
    assert user_intent.spend_machine_typed(f"\n\n{command}\nmore text", tmp_path, now=1001) is True
    assert _crumbs(tmp_path) == []


def test_spend_on_a_missing_directory_is_false(tmp_path: Path) -> None:
    """No machine-typed/ directory at all (the normal human-prompt case) is simply False."""
    assert user_intent.spend_machine_typed("/clear", tmp_path / "nowhere") is False


def _pane(text: str) -> str:
    """A capture shaped like the real one: box rule, marker + NBSP + field, box rule."""
    return "some earlier output\n" + "─" * 40 + f"\n❯ {text}\n" + "─" * 40 + "\n"


def _seq(*items):
    it = iter(items)
    return lambda _t=None: next(it, _pane(""))


def test_inject_until_sent_writes_the_crumb_before_every_type_attempt(tmp_path: Path) -> None:
    """The crumb exists at the moment type_fn runs, and a retry (mangled read-back, clear, retype)
    rewrites the SAME file: exactly one crumb for the logical send."""
    seen: list[list[str]] = []

    def _type() -> None:
        seen.append([p.name for p in _crumbs(tmp_path)])

    ok, why = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=_type, submit_fn=lambda: None, clear_fn=lambda: None,
        reader=_seq(_pane(""), _pane("xx/compact"), _pane(""), _pane("/compact")),
        is_typing=lambda _t: False, sleeper=lambda _s: None, clock=lambda: 0.0,
        state_dir=tmp_path,
    )
    assert ok, why
    assert len(seen) == 2, "the scenario must have typed twice"
    assert all(len(names) == 1 for names in seen), seen
    assert seen[0] == seen[1], "a retry must rewrite the same crumb file"
    assert user_intent.spend_machine_typed("/compact", tmp_path) is True


def test_a_send_into_project_b_writes_its_crumb_under_b_not_under_the_callers_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With CLAUDE_PROJECT_DIR naming project A, a send whose state_dir is project B's leaves the
    crumb under B only: B's hook is the one that will see the typed line."""
    proj_a, proj_b = tmp_path / "A", tmp_path / "B"
    sd_a, sd_b = proj_a / ".janitor" / "state", proj_b / ".janitor" / "state"
    sd_a.mkdir(parents=True)
    sd_b.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj_a))
    ok, why = tt.inject_until_sent(
        {"kind": "tmux", "pane": "%1"}, "/compact",
        type_fn=lambda: None, submit_fn=lambda: None, clear_fn=lambda: None,
        reader=_seq(_pane(""), _pane("/compact")),
        is_typing=lambda _t: False, sleeper=lambda _s: None, clock=lambda: 0.0,
        state_dir=sd_b,
    )
    assert ok, why
    assert len(_crumbs(sd_b)) == 1
    assert _crumbs(sd_a) == []


def test_run_verified_send_hands_the_payload_state_dir_to_the_sender(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The detached child's payload state_dir (the target's) reaches send_verified, not the
    child's own CLAUDE_PROJECT_DIR."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "A"))
    target = tmp_path / "B-state"
    got: list[Path] = []

    def _send(_terminal, command, *, esc_first, giveup_s, state_dir, still_wanted=None):
        got.append(state_dir)
        return True, "ok"

    data = {
        "terminal": {"kind": "tmux", "pane": "%7"}, "commands": ["/compact"],
        "esc_first": False, "state_dir": str(target),
    }
    assert tt.run_verified_send(data, send=_send, clock=lambda: 1000.0) == 0
    assert got == [target]


def _frames(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    text = (_FIXTURES / name).read_text(encoding="utf-8")
    monkeypatch.setattr(fleet_scan, "capture_pane_text", lambda _terminal: text)


def test_pane_actuate_type_writes_the_crumb_into_the_target_projects_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pane_actuate._type: the crumb goes to `<project_dir>/.janitor/state` (the pane owner's),
    not to the CLAUDE_PROJECT_DIR of the calling process, and is there before fire() runs.
    Only fleet_inject.fire (which would type into a real terminal) is replaced."""
    caller = tmp_path / "caller"
    target = tmp_path / "target"
    caller.mkdir()
    target.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(caller))
    _frames(monkeypatch, "synthetic-idle-empty-field.txt")
    at_fire: list[list[str]] = []
    target_sd = user_intent.target_state_dir(target)

    def _fire(plan):
        at_fire.append([p.name for p in _crumbs(target_sd)])
        return plan is not None

    monkeypatch.setattr(fleet_inject, "fire", _fire)
    outcome = pa.act(
        {"tmux_pane": "%5"}, pa.Event.RECOVERY_RUNG, command="/janitor-arm", esc_first=False,
        project_dir=str(target), settle_s=0.0, presence_blocked=lambda: False,
    )
    assert outcome.status is pa.OutcomeStatus.DONE, outcome
    assert at_fire and at_fire[0], "the crumb must exist before fire() runs"
    assert user_intent.spend_machine_typed("/janitor-arm", target_sd) is True
    assert not (caller / ".janitor" / "state" / "machine-typed").exists(), "the caller's own state dir must stay untouched"



def test_pane_actuate_retyping_one_command_rewrites_one_crumb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An act() that types the same command twice for one submit leaves exactly ONE crumb: a
    fresh id per attempt would orphan a crumb that later eats a real owner command. The real
    `execute` runs; only its `type_keys` is wrapped so each command keystroke is sent twice."""
    target = tmp_path / "target"
    target.mkdir()
    _frames(monkeypatch, "synthetic-idle-empty-field.txt")
    monkeypatch.setattr(fleet_inject, "fire", lambda plan: plan is not None)
    real_execute = pa.execute
    typed: list[str] = []

    def _execute_typing_twice(steps, *, type_keys, **kw):
        def _twice(step):
            for _ in range(2 if step.keys.startswith("/") else 1):
                typed.append(step.keys)
                type_keys(step)
        return real_execute(steps, type_keys=_twice, **kw)

    monkeypatch.setattr(pa, "execute", _execute_typing_twice)
    pa.act(
        {"tmux_pane": "%5"}, pa.Event.RECOVERY_RUNG, command="/janitor-arm", esc_first=False,
        project_dir=str(target), settle_s=0.0, presence_blocked=lambda: False,
    )
    assert typed.count("/janitor-arm") == 2, typed
    target_sd = user_intent.target_state_dir(target)
    assert len(_crumbs(target_sd)) == 1, "a retype must rewrite the same crumb, not add one"
    assert user_intent.spend_machine_typed("/janitor-arm", target_sd) is True
    assert user_intent.spend_machine_typed("/janitor-arm", target_sd) is False



def _log_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point this process's log dir at a fresh tmp project (log_line does not create the dir)."""
    # Relies on the autouse conftest fixture `_clear_state_path_caches` having emptied the state caches.
    monkeypatch.delenv("JANITOR_LOG_DIR", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    logs = tmp_path / "proj" / ".janitor" / "logs"
    logs.mkdir(parents=True)
    assert state.log_dir() == logs
    return logs


def test_a_successful_spend_logs_only_the_command_word_and_the_crumb_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A spend leaves one prompt-submit line naming the leading command word and the crumb's age,
    so a swallowed owner command can be diagnosed -- and never copies a /goal line's text."""
    logs = _log_env(tmp_path, monkeypatch)
    sd = tmp_path / "sd"
    user_intent.note_machine_typed("/goal finish the old transcript task\n", sd, "a", now=1000)
    assert user_intent.spend_machine_typed("/goal finish the old transcript task", sd, now=1042) is True
    log = (logs / "prompt-submit.log").read_text(encoding="utf-8")
    assert "machine-typed crumb spent for '/goal' (age 42s)" in log
    assert "old transcript" not in log


def test_probe_logs_only_the_two_shaped_forms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While a crumb is live, an unmatched prompt of one of the two SHAPED forms logs its first
    60 raw characters and the live-crumb count: a <pasted_content> wrapper whose line equals a live
    crumb, and the picker's NAMESPACED form of a live crumb's command word. Owner prose naming a
    crumb word, owner prose containing a crumb word as a substring ("unclear" vs /clear) and an
    unrelated owner slash command and a "<"-led owner prompt with no line equal to a crumb
    ("<div>hello</div>") log NOTHING; nothing logs when no crumb is live; and the wrapper
    is still NOT suppressed (the fail-safe: an unrecognised form counts as the owner's)."""
    logs = _log_env(tmp_path, monkeypatch)
    sd = tmp_path / "sd"
    assert user_intent.spend_machine_typed("/clear", sd, now=1001) is False  # no crumbs: silent
    user_intent.note_machine_typed("/janitor-arm", sd, "a", now=1000)
    user_intent.note_machine_typed("/compact", sd, "b", now=50)  # 7250 s old at 7300: expired, not counted
    user_intent.note_machine_typed("/clear", sd, "c", now=7000)
    wrapped = '<pasted_content id="1">\n/janitor-arm\n</pasted_content>'
    namespaced = "/ai-maestro-janitor:janitor-arm " + "x" * 80
    negatives = ["hello there", "please run janitor-arm now", "/janitor-disarm", "this is unclear", "<div>hello</div>"]
    for prompt in negatives:
        assert user_intent.spend_machine_typed(prompt, sd, now=7300) is False, prompt
    assert user_intent.spend_machine_typed(wrapped, sd, now=7300) is False, "the wrapper is not suppressed"
    assert user_intent.spend_machine_typed(namespaced, sd, now=7300) is False
    log = (logs / "prompt-submit.log").read_text(encoding="utf-8")
    assert log.count("machine-typed: no crumb matched") == 2, log
    assert f"no crumb matched {wrapped[:60]!r} (2 unexpired crumb(s))" in log
    assert f"no crumb matched {namespaced[:60]!r} (2 unexpired crumb(s))" in log
    for prompt in negatives:
        assert prompt not in log, prompt
    assert "x" * 40 not in log, "only the first 60 raw characters are logged"
    assert len(_crumbs(sd)) == 2, "the unmatched prompts spent nothing"


def test_an_unwritable_state_dir_logs_instead_of_passing_silently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A state_dir that cannot hold a directory (it is a regular file) must not raise -- the
    keystroke goes ahead -- but must leave a log line saying the crumb was not written."""
    logs = _log_env(tmp_path, monkeypatch)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    user_intent.note_machine_typed("/clear", blocker, "a", now=1000)
    log = (logs / "terminal_trigger.log").read_text(encoding="utf-8")
    assert f"machine-typed crumb NOT written for '/clear' under {str(blocker)!r}: " in log


def test_target_state_dir_of_a_project_equals_that_projects_own_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cross-project premise: the dir a typer writes for project p (`target_state_dir(p)`) is
    the dir p's own hook reads (`state.state_dir()` with CLAUDE_PROJECT_DIR=p)."""
    proj = tmp_path / "p"
    proj.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    for name in ("project_root", "janitor_root", "state_dir", "log_dir"):
        getattr(state, name).cache_clear()
    assert user_intent.target_state_dir(proj) == state.state_dir()
    assert user_intent.target_state_dir(str(proj)) == state.state_dir()
