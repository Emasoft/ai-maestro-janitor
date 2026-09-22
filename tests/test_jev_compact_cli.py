"""Tests for scripts/jev_compact.py (TRDD-541CBN36 card 2): `expand` and `probe`.

`expand` is tested against a tiny synthetic transcript carrying the three block kinds the
spec names (user text, assistant text block, tool_result block) — not a real transcript,
which can be 24-258 MB per the study's facts. `probe` is tested by monkeypatching
`jev_compact.make_client` (the name bound in jev_compact's own module namespace), so no
network call happens and every exit code the CLI contract promises is exercised directly.
`compact` is a card-3 stub here; this file only pins its exit code so nothing external
starts depending on a richer stub shape by accident.
"""

from __future__ import annotations

import importlib.util as _u
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "jev_compact.py"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


def _import():
    spec = _u.spec_from_file_location("jev_compact_under_test", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


jev_compact = _import()


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


def test_probe_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(noul=0.73)
    monkeypatch.setattr(jev_compact, "make_client", lambda: client)
    code, out = _run(["probe"])
    assert code == 0
    assert "probe ok" in out
    assert "noul=0.73" in out
    assert client.closed


def test_probe_make_client_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from jevctx.types import JevAuthError

    def _raise() -> Any:
        raise JevAuthError("no key")

    monkeypatch.setattr(jev_compact, "make_client", _raise)
    code, out = _run(["probe"])
    assert code == 2
    assert "no key" in out


def test_probe_ask_raises(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_compact_is_still_a_card3_stub() -> None:
    code, out = _run(["compact"])
    assert code == 4
    assert "card 3" in out
