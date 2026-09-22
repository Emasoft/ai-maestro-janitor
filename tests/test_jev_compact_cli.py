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
            raise JevUnavailableError("503")

    client = _FailingClient()
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)
    code, out = _run(["probe"])
    assert code == 2
    assert "503" in out
    assert client.closed
    stamp = json.loads((_isolated_control_dir / "jev-probe.json").read_text())
    assert stamp["kind"] == "unavailable"


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


@pytest.mark.parametrize("kind", ["auth", "budget"])
def test_compact_does_not_decline_on_non_outage_stamp(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """An `auth`/`budget` stamp is scoped to one key/request, not the endpoint -- the fast
    decline (exit 5) must key on `kind == "unavailable"` alone, so a fresh attempt still
    tries the network instead of being blacked out by a config bug from a different shell."""
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
            raise JevUnavailableError("simulated 503")

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


def test_compact_does_not_decline_on_unreachable_stamp(
    tmp_path: Path, _isolated_control_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `kind="unreachable"` stamp is a LOCAL transport problem (this machine/lane), not
    evidence the Jev endpoint itself is down -- the fast-decline gate (exit 5) must key on
    `kind == "unavailable"` alone, same as the existing auth/budget non-decline test."""
    _isolated_control_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"ok": False, "reason": "simulated local networking failure", "ts": time.time(),
              "cost": None, "model": None, "provider": "openrouter", "kind": "unreachable"}
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
