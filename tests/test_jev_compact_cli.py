"""Tests for scripts/jev_compact.py (TRDD-541CBN36 card 2, TRDD-RAEGS1D5 card 3 part B).

`expand` is tested against a tiny synthetic transcript carrying the three block kinds the
spec names (user text, assistant text block, tool_result block) — not a real transcript,
which can be 24-258 MB per the study's facts. `probe`/`compact` are tested by monkeypatching
`jev_compact.make_client` (the name bound in jev_compact's own module namespace), so no
network call happens and every exit code the CLI contract promises is exercised directly.
Every test runs under an isolated `JANITOR_CONTROL_DIR` (see `_isolated_control_dir` below)
so the probe stamp `compact`/`probe` write never touches this machine's real
`~/.claude/janitor-control/`.
"""

from __future__ import annotations

import importlib.util as _u
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "jev_compact.py"
_FIXTURE = _PROJECT_ROOT / "tests" / "fixtures" / "jev_transcript_small.jsonl"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import jev_compaction as jc  # noqa: E402
from jevctx.testing import FakeJevClient  # noqa: E402  -- needs the sys.path line above


def _import():
    spec = _u.spec_from_file_location("jev_compact_under_test", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


jev_compact = _import()


@pytest.fixture(autouse=True)
def _isolated_control_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test in this file gets its OWN, empty control dir -- `probe`/`compact` write
    the probe stamp unconditionally, and without this every test run would write to (and a
    stale stamp from one test could leak into) this machine's real
    `~/.claude/janitor-control/jev-probe.json` (`global_state.control_dir()`'s
    `JANITOR_CONTROL_DIR` env override -- see `scripts/lib/global_state.py::control_dir`)."""
    control = tmp_path / "control"
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(control))
    return control


def _write_transcript(tmp_path: Path) -> Path:
    entries = [
        # (1) a human-typed user message: content is a plain str, block index 0.
        {"type": "user", "uuid": "u-1", "parentUuid": None, "message": {"role": "user", "content": "hello, please fix the bug"}},
        # (2) an assistant entry with a thinking block (index 0, not expandable) and a
        #     text block (index 1, expandable).
        {
            "type": "assistant",
            "uuid": "a-1",
            "parentUuid": "u-1",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "let me look..."},
                    {"type": "text", "text": "I found the bug and fixed it."},
                ],
            },
        },
        # (3) a user entry carrying a tool_result block, index 0.
        {
            "type": "user",
            "uuid": "u-2",
            "parentUuid": "a-1",
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "file written: 12 lines"}]},
        },
    ]
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


def _run(argv: list[str]) -> tuple[int, str]:
    import contextlib
    import io

    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = jev_compact.main(argv)
    return code, (out.getvalue() + err.getvalue())


def test_expand_user_str_content(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path)
    code, out = _run(["expand", "--transcript", str(transcript), "u-1:0"])
    assert code == 0
    assert out.strip() == "hello, please fix the bug"


def test_expand_assistant_text_block(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path)
    code, out = _run(["expand", "--transcript", str(transcript), "a-1:1"])
    assert code == 0
    assert out.strip() == "I found the bug and fixed it."


def test_expand_tool_result_block(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path)
    code, out = _run(["expand", "--transcript", str(transcript), "u-2:0"])
    assert code == 0
    assert out.strip() == "file written: 12 lines"


def test_expand_thinking_block_is_not_expandable(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path)
    code, out = _run(["expand", "--transcript", str(transcript), "a-1:0"])
    assert code == 3


def test_expand_unknown_uuid_exits_3(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path)
    code, _out = _run(["expand", "--transcript", str(transcript), "no-such-uuid:0"])
    assert code == 3


def test_expand_out_of_range_index_exits_3(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path)
    code, _out = _run(["expand", "--transcript", str(transcript), "u-1:5"])
    assert code == 3


def test_expand_malformed_id_exits_3(tmp_path: Path) -> None:
    transcript = _write_transcript(tmp_path)
    code, _out = _run(["expand", "--transcript", str(transcript), "not-an-id"])
    assert code == 3


class _FakeAnswer:
    def __init__(self, noul: float) -> None:
        self.noul = noul


class _FakeUsage:
    cost = 0.0001


class _FakeClient:
    """Stand-in with the exact shape `cmd_probe` reads: `.ask()`, `.usage.cost`, `.close()`."""

    def __init__(self, noul: float = 0.42) -> None:
        self._noul = noul
        self.usage = _FakeUsage()
        self.closed = False

    def ask(self, state: Any, questions: Any) -> dict[str, _FakeAnswer]:
        return {"a": _FakeAnswer(self._noul)}

    def close(self) -> None:
        self.closed = True


def test_probe_ok(_isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(noul=0.73)
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)
    code, out = _run(["probe"])
    assert code == 0
    assert "probe ok" in out
    assert "noul=0.73" in out
    assert client.closed
    stamp = json.loads((_isolated_control_dir / "jev-probe.json").read_text())
    assert stamp["kind"] == "ok"


def test_probe_make_client_raises(
    _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jevctx.types import JevAuthError

    def _raise() -> Any:
        raise JevAuthError("no key")

    monkeypatch.setattr(jev_compact, "make_client", _raise)
    code, out = _run(["probe"])
    assert code == 2
    assert "no key" in out
    stamp = json.loads((_isolated_control_dir / "jev-probe.json").read_text())
    assert stamp["kind"] == "auth"


def test_probe_ask_raises(
    _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jevctx.types import JevUnavailableError

    class _FailingClient(_FakeClient):
        def ask(self, state: Any, questions: Any) -> dict[str, _FakeAnswer]:
            # `status=503` mirrors what jev.py's real 5xx raise site sets -- a bare
            # `JevUnavailableError()` with no status now means "no response arrived"
            # (kind="unreachable", see the dedicated test below), since `status`
            # defaults to `None` on the base class itself (commit 40cc06d1 follow-up).
            raise JevUnavailableError("503", status=503, cause="HTTP 503")

    client = _FailingClient()
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)
    code, out = _run(["probe"])
    assert code == 2
    assert "503" in out
    assert client.closed
    stamp = json.loads((_isolated_control_dir / "jev-probe.json").read_text())
    assert stamp["kind"] == "unavailable"


def test_probe_ask_raises_429_writes_rate_limited_stamp(
    _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 429 is a per-key rate limit, not a whole-endpoint outage -- `_stamp_kind_for_error`
    must classify it as its own `kind="rate_limited"`, distinct from a real 5xx
    `kind="unavailable"`, and carry the server's `Retry-After` value forward as
    `retry_after_s` so `cmd_compact`'s decline gate can use it (commit 40cc06d1
    follow-up)."""
    from jevctx.types import JevUnavailableError

    class _FailingClient(_FakeClient):
        def ask(self, state: Any, questions: Any) -> dict[str, _FakeAnswer]:
            raise JevUnavailableError("429", status=429, cause="HTTP 429", retry_after=12.5)

    client = _FailingClient()
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)
    code, out = _run(["probe"])
    assert code == 2
    assert "429" in out
    stamp = json.loads((_isolated_control_dir / "jev-probe.json").read_text())
    assert stamp["kind"] == "rate_limited"
    assert stamp["retry_after_s"] == 12.5


def _keep_only(*keywords: str):
    """A `FakeJevClient` answer function: keep an item iff its text contains one of
    `keywords`, on BOTH the relevance and decision question. Keys arrive as `<ref>:rel` /
    `<ref>:dec` (score_items sends both questions for an item in one request); the ref is
    the part before the ':'."""

    def answer(state: Any, questions: Any, key: str) -> float:
        ref = key.split(":", 1)[0]
        text = ""
        if isinstance(state, dict):
            for entry in state.get("items", []):
                if entry.get("ref") == ref:
                    text = entry.get("text", "")
        return 0.9 if any(kw in text for kw in keywords) else 0.05

    return answer


def test_compact_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"
    # "bug" keeps the user message and the assistant's text; the dangling tool_result item
    # ("file written: 12 lines") has no such keyword, so it must be elided -- giving this
    # test both a kept item AND a pointer, per the task's own "pointers present" requirement.
    client = FakeJevClient(_keep_only("bug"))
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 0
    assert "compacted items=" in output
    assert out.exists()
    doc = out.read_text(encoding="utf-8")
    pointer_lines = [line for line in doc.splitlines() if line.startswith("[[elided")]
    assert pointer_lines, "expected at least one elided pointer"
    for line in pointer_lines:
        assert str(transcript) not in line  # spec: a pointer never carries a path
    assert doc.count(str(transcript)) == 2  # header line + the one fixed trailing line


def test_compact_declines_on_recent_probe_failure(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"ok": False, "reason": "simulated outage", "ts": time.time(),
              "cost": None, "model": None, "provider": "openrouter", "kind": "unavailable"}
    (_isolated_control_dir / "jev-probe.json").write_text(json.dumps(stamp))

    def _must_not_be_called() -> Any:
        raise AssertionError("make_client must not be called on a fast decline")

    monkeypatch.setattr(jev_compact, "make_client", _must_not_be_called)
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 5
    assert "declined: recent probe failure: simulated outage" in output
    assert not out.exists()


@pytest.mark.parametrize("kind", ["auth", "budget", "invalid", "unknown"])
def test_compact_does_not_decline_on_non_outage_stamp(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """An `auth`/`budget`/`invalid`/`unknown` stamp is scoped to one key/request/attempt, not
    the endpoint -- the fast decline (exit 5) must key on `kind` in
    `{"unavailable", "unreachable", "rate_limited"}` only, so a fresh attempt still tries the
    network instead of being blacked out by a problem scoped to a different caller or request
    (TRDD-RAEGS1D5 owner decision 2026-09-23: `"invalid"`/`"unknown"` are the two NEW kinds
    `_stamp_kind_for_error` can now produce, and neither may decline a later attempt either)."""
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"ok": False, "reason": "simulated non-outage failure", "ts": time.time(),
              "cost": None, "model": None, "provider": "openrouter", "kind": kind}
    (_isolated_control_dir / "jev-probe.json").write_text(json.dumps(stamp))

    client = FakeJevClient(_keep_only("bug"))
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 0
    assert out.exists()


def test_compact_no_digest_material(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A single dangling tool_result: extract_items yields one `kind="tool"` item and ZERO
    # user/assistant items, and no --state-heads is passed -- build_digest has nothing to
    # judge relevance against.
    entries = [{
        "type": "user", "uuid": "u1", "parentUuid": None,
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "missing", "content": "orphaned result"}
        ]},
    }]
    transcript = tmp_path / "no_digest.jsonl"
    transcript.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    out = tmp_path / "compacted.md"

    def _must_not_be_called() -> Any:
        raise AssertionError("make_client must not be called when there is no digest")

    monkeypatch.setattr(jev_compact, "make_client", _must_not_be_called)

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 6
    assert "declined: no digest material" in output
    assert not out.exists()


def test_compact_scorer_error_writes_failure_stamp(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jevctx.types import JevUnavailableError

    class _FailingScoreClient:
        def ask(self, state: Any, questions: Any) -> dict[str, Any]:
            raise JevUnavailableError("simulated 503", status=503, cause="HTTP 503")

    monkeypatch.setattr(jev_compact, "make_client", lambda: _FailingScoreClient())
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 7
    assert "simulated 503" in output
    assert not out.exists()

    stamp = json.loads((_isolated_control_dir / "jev-probe.json").read_text())
    assert stamp["ok"] is False
    assert "simulated 503" in stamp["reason"]
    assert stamp["kind"] == "unavailable"


def test_compact_scorer_429_writes_rate_limited_stamp(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same scorer-error path as the 503 test above, but a 429 must land
    `kind="rate_limited"` with the server's `retry_after_s` -- not `"unavailable"`."""
    from jevctx.types import JevUnavailableError

    class _FailingScoreClient:
        def ask(self, state: Any, questions: Any) -> dict[str, Any]:
            raise JevUnavailableError(
                "simulated 429", status=429, cause="HTTP 429", retry_after=7.0
            )

    monkeypatch.setattr(jev_compact, "make_client", lambda: _FailingScoreClient())
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 7
    assert "simulated 429" in output
    assert not out.exists()

    stamp = json.loads((_isolated_control_dir / "jev-probe.json").read_text())
    assert stamp["ok"] is False
    assert stamp["kind"] == "rate_limited"
    assert stamp["retry_after_s"] == 7.0


def test_compact_budget_error_exits_7_with_budget_stamp(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`JevBudgetError` during scoring is the planner's own bug, not an outage -- exit 7
    with a `budget:`-prefixed message and a `kind="budget"` stamp, distinct from the generic
    `compact failed:` / `kind="unavailable"` path the JevUnavailableError test above covers."""
    from jevctx.types import JevBudgetError

    class _BudgetBustingClient:
        def ask(self, state: Any, questions: Any) -> dict[str, Any]:
            raise JevBudgetError("too many questions for one state")

    monkeypatch.setattr(jev_compact, "make_client", lambda: _BudgetBustingClient())
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 7
    assert "budget: too many questions for one state" in output
    assert not out.exists()

    stamp = json.loads((_isolated_control_dir / "jev-probe.json").read_text())
    assert stamp["ok"] is False
    assert stamp["kind"] == "budget"


def test_probe_ask_raises_unreachable_when_status_is_none(
    _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `JevUnavailableError` whose `.status` is explicitly `None` (jevctx's shape for a
    transport failure -- no response ever came back, e.g. TRDD-X6I04SAO's CA-bundle gap)
    must classify as `kind="unreachable"`, distinct from a real `kind="unavailable"`
    outage -- see `_stamp_kind_for_error`'s docstring."""
    from jevctx.types import JevUnavailableError

    class _FailingClient(_FakeClient):
        def ask(self, state: Any, questions: Any) -> dict[str, _FakeAnswer]:
            exc = JevUnavailableError("connection refused")
            exc.status = None  # type: ignore[attr-defined]
            exc.cause = "ConnectError: connection refused"  # type: ignore[attr-defined]
            raise exc

    client = _FailingClient()
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)
    code, _out = _run(["probe"])
    assert code == 2
    stamp = json.loads((_isolated_control_dir / "jev-probe.json").read_text())
    assert stamp["kind"] == "unreachable"


def test_stamp_kind_for_validation_error_is_invalid() -> None:
    """TRDD-RAEGS1D5 owner decision 2026-09-23: `JevValidationError` (400/404/413/422, or a
    malformed response -- 408 is now retried in openrouter.py, so exhausted 408s never reach
    this class) must classify as `kind="invalid"`, never fall through to the old
    `"unavailable"` default -- a bad REQUEST is not evidence the endpoint itself is down, and
    the old fallthrough was a live defect: it declined every OTHER caller's compaction on the
    (then 30-minute) outage TTL for a problem scoped to one request."""
    from jevctx.types import JevValidationError

    assert jev_compact._stamp_kind_for_error(JevValidationError("bad request")) == "invalid"


def test_stamp_kind_for_unrecognized_jev_error_is_unknown() -> None:
    """A `JevError` subclass this CLI does not special-case at all must classify as
    `kind="unknown"` -- non-declining, like `"invalid"`, rather than the old `"unavailable"`
    default that would have blacked out every other caller's compaction on an error this file
    cannot even name."""
    from jevctx.types import JevError

    class _SomeFutureJevError(JevError):
        pass

    assert jev_compact._stamp_kind_for_error(_SomeFutureJevError("mystery")) == "unknown"


def test_compact_declines_on_recent_unreachable_stamp(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Card 5 content-fit (TRDD-RAEGS1D5, item 4): a fresh `kind="unreachable"` stamp (DNS/TLS/
    offline -- no HTTP response ever came back) now declines fast (exit 5), same policy as
    `kind="unavailable"`, just with a shorter `PROBE_UNREACHABLE_TTL_S` TTL. This used to be
    true ONLY inside `on-session-start-post-clear-compact.py`'s own duplicate pre-check --
    `summarize_previous_session.py`'s detached lane had none and paid the full retry/backoff
    wall on the same outage. Moved into `cmd_compact`'s own gate so every caller of this CLI
    (not just one hook) honours the same decline, superseding the old `test_compact_does_not_
    decline_on_unreachable_stamp` (which asserted the now-retired non-decline behaviour)."""
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"ok": False, "reason": "simulated local networking failure", "ts": time.time(),
              "cost": None, "model": None, "provider": "openrouter", "kind": "unreachable"}
    (_isolated_control_dir / "jev-probe.json").write_text(json.dumps(stamp))

    def _must_not_be_called() -> Any:
        raise AssertionError("make_client must not be called on a fast decline")

    monkeypatch.setattr(jev_compact, "make_client", _must_not_be_called)
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 5
    assert "declined: recent probe failure: simulated local networking failure" in output
    assert not out.exists()


def test_compact_does_not_decline_once_unreachable_ttl_has_passed(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An `kind="unreachable"` stamp older than `PROBE_UNREACHABLE_TTL_S` (5min) must NOT
    decline -- a fixed local issue (DNS, a VPN) is worth retrying again, unlike a real
    `kind="unavailable"` outage's much longer `PROBE_FAIL_TTL_S` (30min)."""
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    stamp = {
        "ok": False, "reason": "simulated local networking failure",
        "ts": time.time() - (jev_compact.PROBE_UNREACHABLE_TTL_S + 5),
        "cost": None, "model": None, "provider": "openrouter", "kind": "unreachable",
    }
    (_isolated_control_dir / "jev-probe.json").write_text(json.dumps(stamp))

    client = FakeJevClient(_keep_only("bug"))
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 0
    assert out.exists()


def test_compact_declines_on_recent_rate_limited_probe_failure(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh `kind="rate_limited"` stamp declines like `"unavailable"` does, but the TTL
    it honours is the server's own `retry_after_s`, not `PROBE_FAIL_TTL_S`."""
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"ok": False, "reason": "simulated 429", "ts": time.time(),
              "cost": None, "model": None, "provider": "openrouter", "kind": "rate_limited",
              "retry_after_s": 20.0}
    (_isolated_control_dir / "jev-probe.json").write_text(json.dumps(stamp))

    def _must_not_be_called() -> Any:
        raise AssertionError("make_client must not be called on a fast decline")

    monkeypatch.setattr(jev_compact, "make_client", _must_not_be_called)
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 5
    assert "declined: recent probe failure: simulated 429" in output
    assert not out.exists()


def test_compact_does_not_decline_once_rate_limited_ttl_has_passed(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `kind="rate_limited"` stamp older than its own short `retry_after_s` TTL must NOT
    decline -- unlike `"unavailable"`'s much longer `PROBE_FAIL_TTL_S` (30min), this stamp
    is stale after just a few seconds."""
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"ok": False, "reason": "simulated 429", "ts": time.time() - 30,
              "cost": None, "model": None, "provider": "openrouter", "kind": "rate_limited",
              "retry_after_s": 5.0}
    (_isolated_control_dir / "jev-probe.json").write_text(json.dumps(stamp))

    client = FakeJevClient(_keep_only("bug"))
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 0
    assert out.exists()


def test_compact_rate_limited_ttl_falls_back_and_caps_without_retry_after(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No `retry_after_s` on the stamp (the 429 carried no `Retry-After` header) falls back
    to `_RATE_LIMIT_FALLBACK_TTL_S` (60s) -- a stamp 90s old must therefore NOT decline."""
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"ok": False, "reason": "simulated 429", "ts": time.time() - 90,
              "cost": None, "model": None, "provider": "openrouter", "kind": "rate_limited",
              "retry_after_s": None}
    (_isolated_control_dir / "jev-probe.json").write_text(json.dumps(stamp))

    client = FakeJevClient(_keep_only("bug"))
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 0
    assert out.exists()


def test_read_probe_stamp_torn_json_treated_as_no_stamp(
    _isolated_control_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A torn/garbage stamp (e.g. a crash mid-write, or a reader racing the atomic
    tmp+os.replace) must not crash `compact` -- `read_probe_stamp` returns `None` (proceed
    as if nothing is known) and reports the reason on stderr, never raises."""
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    (_isolated_control_dir / "jev-probe.json").write_text("{not valid json,,,")

    assert jev_compact.read_probe_stamp() is None
    assert "probe stamp unreadable" in capsys.readouterr().err


def test_read_probe_stamp_wrong_shape_treated_as_no_stamp(
    _isolated_control_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Valid JSON that isn't an object (e.g. a JSON array or a bare number) is also "no
    stamp", not a crash -- the shape contract is `dict`, and `compact` must proceed."""
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    (_isolated_control_dir / "jev-probe.json").write_text("[1, 2, 3]")

    assert jev_compact.read_probe_stamp() is None
    assert "probe stamp unreadable" in capsys.readouterr().err


def test_write_probe_stamp_uses_atomic_replace(
    _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`write_probe_stamp` must go through `state.atomic_write` (tmp file + `os.replace`),
    not a direct write -- a concurrent reader must never see a half-written stamp. Proven
    two ways: (1) `os.replace` is spied on directly, showing the rename actually happens
    (not just a `.write_text` that a reader could catch mid-write); (2) a simulated
    `os.replace` failure (the crash-mid-write case) leaves the ORIGINAL target file
    untouched -- a reader never sees a torn stamp, only the old content or none at all."""
    replace_calls: list[tuple[Path, Path]] = []
    real_replace = jev_compact.state.os.replace

    def _spy_replace(src: Any, dst: Any) -> None:
        replace_calls.append((Path(src), Path(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(jev_compact.state.os, "replace", _spy_replace)
    jev_compact.write_probe_stamp(
        ok=True, reason=None, cost=0.01, model=None, provider="openrouter", kind="ok"
    )

    target = _isolated_control_dir / "jev-probe.json"
    assert len(replace_calls) == 1
    src, dst = replace_calls[0]
    assert dst == target
    assert src.name.startswith("jev-probe.json.tmp.")
    assert target.exists()
    leftover_tmp = list(_isolated_control_dir.glob("*.tmp.*"))
    assert leftover_tmp == [], f"atomic write left a partial file: {leftover_tmp}"

    # Simulated crash: os.replace raises AFTER the tmp file is fully written. The
    # original target must be left exactly as it was -- never a torn/partial stamp.
    before = target.read_text(encoding="utf-8")

    def _failing_replace(src: Any, dst: Any) -> None:
        raise OSError("simulated crash during os.replace")

    monkeypatch.setattr(jev_compact.state.os, "replace", _failing_replace)
    with pytest.raises(OSError, match="simulated crash"):
        jev_compact.write_probe_stamp(
            ok=False, reason="should not land", cost=None, model=None,
            provider="openrouter", kind="unavailable",
        )
    assert target.read_text(encoding="utf-8") == before


def test_compact_budget_error_from_planner_site_exits_7_with_budget_stamp(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`JevBudgetError` from `BudgetPlanner.plan` (inside `jc.score_items`, BEFORE any
    request is sent) must be caught by the same `except JevBudgetError` in `cmd_compact`
    as the client's own `check_request_budget` inside `ask()` -- proven here by making the
    planner itself raise, not the client."""

    from jevctx.types import JevBudgetError

    def _raising_plan(self: Any, items: Any, question_tokens: int, envelope_tokens: int = 0) -> Any:
        raise JevBudgetError("item too large for even one batch")

    monkeypatch.setattr(jc.BudgetPlanner, "plan", _raising_plan)
    monkeypatch.setattr(jev_compact, "make_client", lambda: FakeJevClient(_keep_only("bug")))
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 7
    assert "budget: item too large for even one batch" in output
    assert not out.exists()
    stamp = json.loads((_isolated_control_dir / "jev-probe.json").read_text())
    assert stamp["kind"] == "budget"


def test_expand_round_trips_a_composed_pointer_id() -> None:
    """`compose()`'s pointer ids are `<entry uuid>:<block index>` positions in the RAW
    content list (jev_compaction.Item's own contract) -- prove that claim against `expand`'s
    OWN indexing, on the real fixture transcript, not just by construction. A `kind="tool"`
    item is deliberately skipped for the round-trip: its `Item.text` is a SYNTHESIZED
    "name(input)\\nresult" pairing (see jev_compaction.extract_items), not the raw
    tool_result block's own content -- `expand` correctly returns the latter, so comparing
    against a tool item would be a false mismatch, not evidence of an indexing bug."""
    items = jc.extract_items(_FIXTURE)
    scores = {
        it.id: jc.Scores(relevance=0.0, decision=0.0, oversized=False, kept=False,
                          decision_passed=False)
        for it in items
    }
    doc = jc.compose(items, scores, budget_tokens=8000,
                      header={"transcript_path": str(_FIXTURE), "session_key": "s"})

    by_id = {it.id: it for it in items}
    target_id = None
    for line in doc.splitlines():
        if not line.startswith("[[elided"):
            continue
        candidate = line.split("id=", 1)[1].split(" ", 1)[0]
        if by_id[candidate].kind != "tool":
            target_id = candidate
            break
    assert target_id is not None, "expected at least one non-tool elided item"

    code, out = _run(["expand", "--transcript", str(_FIXTURE), target_id])
    assert code == 0
    assert out.rstrip("\n") == by_id[target_id].text


# --- Card 5 two-renderings (TRDD-RAEGS1D5) -----------------------------------------------------


def test_compact_inject_out_writes_a_capped_companion_pointing_at_the_full_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--out` stays the FULL, card-3-sized document (digest included); `--inject-out` is a
    SEPARATE, capped rendering over the SAME scored items (no second scoring call) -- digest
    omitted, ending with a trailer pointing back at `--out`'s absolute path."""
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"
    inject_out = tmp_path / "compacted.inject.md"
    client = FakeJevClient(_keep_only("bug"))
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)

    code, output = _run([
        "compact", "--transcript", str(transcript), "--out", str(out),
        "--inject-out", str(inject_out), "--max-elided-pointers", "1", "--inject-max-bytes", "2000",
    ])

    assert code == 0
    assert out.exists() and inject_out.exists()
    full_doc = out.read_text(encoding="utf-8")
    inject_doc = inject_out.read_text(encoding="utf-8")
    assert "## Digest" in full_doc
    # The digest text itself (the build_digest output, always non-empty here since the
    # transcript carries human messages) must be present in the full doc.
    assert full_doc.split("## Digest\n", 1)[1].split("\n\n", 1)[0].strip() != ""
    # ... but omitted from the capped rendering.
    assert inject_doc.split("## Digest\n", 1)[1].split("\n\n", 1)[0].strip() == ""
    assert f"Full compacted context: {out.resolve()}" in inject_doc
    assert "Full compacted context:" not in full_doc

def test_compact_inject_out_scores_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Card 5 injection-caps review (TRDD-RAEGS1D5) verification item (a): "score once, render
    twice" means exactly that -- `--inject-out` must never trigger a SECOND `jc.score_items`
    call. Counts calls to the wrapping function itself (never the Jev endpoint's own per-item
    `ask()` calls, which scale with item count and would not distinguish one scoring pass from
    two smaller ones)."""
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"
    inject_out = tmp_path / "compacted.inject.md"
    client = FakeJevClient(_keep_only("bug"))
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)

    calls: list[int] = []
    real_score_items = jc.score_items

    def _counting_score_items(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real_score_items(*args, **kwargs)

    monkeypatch.setattr(jc, "score_items", _counting_score_items)

    code, output = _run([
        "compact", "--transcript", str(transcript), "--out", str(out),
        "--inject-out", str(inject_out),
    ])

    assert code == 0, output
    assert len(calls) == 1, f"expected exactly one score_items() call, got {len(calls)}"

def test_compact_state_heads_reach_the_digest_at_full_card3_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Card 5 injection-caps review (TRDD-RAEGS1D5) verification item (d): the AUTOMATIC lane's
    now-retired `LANE_DIGEST_TOKENS` used to shrink the digest `cmd_compact` builds from
    `--state-heads` down to a small cap; `--digest-tokens` now defaults to the full card-3
    ~4000 whatever the caller (the two owned callers pass nothing, per `run_compact`'s own
    docstring). A 30-line STATE head sized well past a plausible small shrink cap (~1,200
    tokens) but comfortably under 4000 must survive WHOLE into `--out`'s digest, including its
    last line -- a marker there would be the first thing a re-introduced small cap cuts."""
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"
    head_lines = [f"STATE line {i}: " + ("filler word " * 25) for i in range(29)]
    head_lines.append("STATE line 29 (LAST): MARKER_END_OF_STATE_HEAD")
    head_text = "\n".join(head_lines)
    assert jc.estimate_tokens(head_text) > 1200, "fixture must exceed a plausible small cap"
    assert jc.estimate_tokens(head_text) < 4000, "fixture must still fit the full card-3 default"
    head_path = tmp_path / "state-head.md"
    head_path.write_text(head_text, encoding="utf-8")

    client = FakeJevClient(_keep_only("bug"))
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)

    code, output = _run([
        "compact", "--transcript", str(transcript), "--out", str(out),
        "--state-heads", str(head_path),
    ])

    assert code == 0, output
    full_doc = out.read_text(encoding="utf-8")
    digest_section = full_doc.split("## Digest\n", 1)[1].split("\n\nusage:", 1)[0]
    assert "MARKER_END_OF_STATE_HEAD" in digest_section


def test_compact_without_inject_out_writes_only_the_full_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare `compact` invocation (no `--inject-out`) behaves exactly as before this card --
    one document, at `--out`, no companion file."""
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"
    client = FakeJevClient(_keep_only("bug"))
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)

    code, _output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 0
    assert out.exists()
    assert not (tmp_path / "compacted.inject.md").exists()


def test_compact_no_decline_bypasses_a_recent_unavailable_stamp(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TRDD-RAEGS1D5, owner decision 2026-09-23 (R1): `--no-decline` now bypasses the
    `kind="unavailable"` branch too, not just `"unreachable"` -- without this, the AUTOMATIC
    retry lane (`jev_compaction_lane.run_compact_with_fallback`, which passes `--no-decline`
    on every retry inside its 5-minute budget) would stamp `kind="unavailable"` on its first
    real failure and every later retry would exit 5 in microseconds for the rest of the
    window -- "retry for 5 minutes" would mean one real attempt plus a 5-minute sleep. See
    `test_compact_no_decline_still_honours_a_recent_rate_limited_stamp` below: `rate_limited`
    is the one kind `--no-decline` must NEVER bypass."""
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"ok": False, "reason": "simulated outage", "ts": time.time(),
              "cost": None, "model": None, "provider": "openrouter", "kind": "unavailable"}
    (_isolated_control_dir / "jev-probe.json").write_text(json.dumps(stamp))

    client = FakeJevClient(_keep_only("bug"))
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run([
        "compact", "--transcript", str(transcript), "--out", str(out), "--no-decline",
    ])

    assert code == 0, output
    assert out.exists()


def test_compact_unavailable_stamp_ttl_is_5_minutes_not_30(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TRDD-RAEGS1D5, owner decision 2026-09-23 (R1): `PROBE_FAIL_TTL_S` dropped from 30min to
    5min -- a stamp just past the NEW 5-minute TTL (but still well inside the OLD 30-minute
    one) must NOT decline, proving the shorter window actually took effect."""
    assert jev_compact.PROBE_FAIL_TTL_S == 5 * 60
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"ok": False, "reason": "simulated outage",
              "ts": time.time() - (jev_compact.PROBE_FAIL_TTL_S + 5),
              "cost": None, "model": None, "provider": "openrouter", "kind": "unavailable"}
    (_isolated_control_dir / "jev-probe.json").write_text(json.dumps(stamp))

    client = FakeJevClient(_keep_only("bug"))
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run(["compact", "--transcript", str(transcript), "--out", str(out)])

    assert code == 0, output
    assert out.exists()


def test_compact_no_decline_still_honours_a_recent_rate_limited_stamp(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same as the `unavailable` case: a per-key 429 (`kind="rate_limited"`) is not a
    transport-level "cannot reach it" -- `--no-decline` must not bypass it either."""
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"ok": False, "reason": "simulated 429", "ts": time.time(),
              "cost": None, "model": None, "provider": "openrouter", "kind": "rate_limited",
              "retry_after_s": 60}
    (_isolated_control_dir / "jev-probe.json").write_text(json.dumps(stamp))

    def _must_not_be_called() -> Any:
        raise AssertionError("make_client must not be called on a fast decline")

    monkeypatch.setattr(jev_compact, "make_client", _must_not_be_called)
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run([
        "compact", "--transcript", str(transcript), "--out", str(out), "--no-decline",
    ])

    assert code == 5, output
    assert not out.exists()


def test_compact_no_decline_bypasses_a_recent_unreachable_stamp(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Card 5 injection-caps review (TRDD-RAEGS1D5, item 5): the AUTOMATIC lane still declines
    on a fresh `kind="unreachable"` stamp (the default, no `--no-decline`) -- an EXPLICIT
    `--no-decline` request bypasses THIS ONE kind, since a transport-level "cannot even reach
    it" condition (DNS, a VPN) is exactly the kind of stale, possibly-since-fixed state a manual
    request is meant to re-probe past."""
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"ok": False, "reason": "simulated local networking failure", "ts": time.time(),
              "cost": None, "model": None, "provider": "openrouter", "kind": "unreachable"}
    (_isolated_control_dir / "jev-probe.json").write_text(json.dumps(stamp))

    client = FakeJevClient(_keep_only("bug"))
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)
    transcript = _write_transcript(tmp_path)
    out = tmp_path / "compacted.md"

    code, output = _run([
        "compact", "--transcript", str(transcript), "--out", str(out), "--no-decline",
    ])

    assert code == 0, output
    assert out.exists()


def test_expand_list_default_limit_and_transcript_header(tmp_path: Path) -> None:
    """Card 5 two-renderings (TRDD-RAEGS1D5, item 6): `--list` prints a `transcript: <path>`
    header line first, then caps at 50 results by default, narrowable with `--limit`."""
    entries = [
        {"type": "user", "uuid": f"u-{i}", "parentUuid": None,
         "message": {"role": "user", "content": f"message number {i}"}}
        for i in range(60)
    ]
    transcript = tmp_path / "many.jsonl"
    transcript.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

    code, out = _run(["expand", "--transcript", str(transcript), "--list"])
    assert code == 0
    lines = out.strip("\n").splitlines()
    assert lines[0] == f"transcript: {transcript}"
    item_lines = lines[1:]
    assert len(item_lines) == 50, "default --list limit must be 50"

    code, out = _run(["expand", "--transcript", str(transcript), "--list", "--limit", "5"])
    assert code == 0
    item_lines = out.strip("\n").splitlines()[1:]
    assert len(item_lines) == 5
