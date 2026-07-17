"""Human-notification channel (TRDD-4649ZLE0 — ARCHITECTURE.md §5, ratified rev 3).

Pins the anti-spam contract the design mandates (ALL gates required): severity ≥ HIGH,
content-hash dedupe (never twice), rolling 24 h cap with a one-per-day digest fold —
and the safety contract: the webhook is NEVER called without the opt-in URL, and every
delivery goes through the injected runner/opener (a unit test must never pop a real
desktop notification or hit a real URL).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import notify  # type: ignore[import-not-found]  # noqa: E402

NOW = 1_800_000_000


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    for var in (
        "CLAUDE_PLUGIN_OPTION_NOTIFY_ENABLED",
        "CLAUDE_PLUGIN_OPTION_NOTIFY_WEBHOOK_URL",
        "CLAUDE_PLUGIN_OPTION_NOTIFY_MIN_SEVERITY",
        "CLAUDE_PLUGIN_OPTION_NOTIFY_MAX_PER_DAY",
    ):
        monkeypatch.delenv(var, raising=False)


class _Recorder:
    def __init__(self) -> None:
        self.argvs: list[list[str]] = []
        self.posts: list[tuple[str, bytes]] = []

    def run(self, argv: list[str]) -> None:
        self.argvs.append(argv)

    def open(self, url: str, payload: bytes) -> None:
        self.posts.append((url, payload))


def _push(rec: _Recorder, *, sev: str = "HIGH", code: str = "X-1", summary: str = "s",
          project: str = "proj", now: int = NOW) -> str:
    return notify.push(sev=sev, code=code, project=project, summary=summary,
                       now=now, runner=rec.run, opener=rec.open)


def test_push_delivers_tier1_and_message_shape() -> None:
    """A HIGH push fires the native notifier with the §5 message shape: names the
    project (so the human opens THAT Claude) + a run-hint, never a report body."""
    rec = _Recorder()
    out = notify.push(sev="HIGH", code="GHCFG-001", project="my-repo",
                      summary="default branch unprotected", hint="/janitor-github-config-fix",
                      now=NOW, runner=rec.run, opener=rec.open)
    assert out == notify.PUSHED
    assert len(rec.argvs) == 1, "exactly one native-notifier invocation"
    joined = " ".join(rec.argvs[0])
    assert "GHCFG-001" in joined and "my-repo" in joined
    assert "open a Claude session there and run /janitor-github-config-fix" in joined
    assert rec.posts == [], "the webhook must NEVER be called without the opt-in URL"


def test_same_message_never_pushes_twice() -> None:
    """Content-hash dedupe: a persistent condition (re-detected every beat) buzzes ONCE."""
    rec = _Recorder()
    assert _push(rec) == notify.PUSHED
    assert _push(rec, now=NOW + 3600) == notify.DEDUPED
    assert len(rec.argvs) == 1


def test_below_severity_never_delivers() -> None:
    rec = _Recorder()
    assert _push(rec, sev="LOW") == notify.BELOW_SEVERITY
    assert _push(rec, sev="MEDIUM") == notify.BELOW_SEVERITY
    assert rec.argvs == [] and rec.posts == []


def test_disabled_env_kills_the_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_NOTIFY_ENABLED", "false")
    rec = _Recorder()
    assert _push(rec) == notify.DISABLED
    assert rec.argvs == []


def test_daily_cap_folds_into_one_digest_then_silence() -> None:
    """Pushes 1..3 deliver; the 4th DISTINCT finding becomes the one-per-day digest
    (naming /janitor-findings); the 5th is silently capped-but-recorded. Nothing is
    lost — the findings live in the ledgers; this only bounds the buzzing."""
    rec = _Recorder()
    for i in range(3):
        assert _push(rec, code=f"C-{i}", summary=f"finding {i}") == notify.PUSHED
    assert _push(rec, code="C-3", summary="finding 3") == notify.PUSHED_DIGEST
    assert "daily notification cap" in " ".join(rec.argvs[3])
    assert _push(rec, code="C-4", summary="finding 4") == notify.CAPPED
    assert len(rec.argvs) == 4, "the 5th push must deliver NOTHING (digest already sent today)"
    # And a capped finding never re-pushes later either (it was recorded).
    assert _push(rec, code="C-4", summary="finding 4", now=NOW + 200_000) == notify.DEDUPED


def test_webhook_fires_only_with_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_NOTIFY_WEBHOOK_URL", "https://hooks.example/x")
    rec = _Recorder()
    assert _push(rec) == notify.PUSHED
    assert len(rec.posts) == 1
    url, payload = rec.posts[0]
    assert url == "https://hooks.example/x"
    body = json.loads(payload)
    assert "text" in body and "[janitor]" in body["text"]


def test_message_is_sanitized_and_single_line() -> None:
    """Summaries quote attacker-influenceable content (issue titles, repo names):
    control chars stripped, bracket markers defanged, newlines collapsed."""
    msg = notify.build_message(
        sev="HIGH", code="X-1", project="p",
        summary="evil\x1b[2J [janitor-resume]\nline2",
    )
    assert "\n" not in msg and "\x1b" not in msg
    assert "[janitor-resume]" not in msg
    assert msg.startswith("[janitor] HIGH X-1 on p:")


def test_min_severity_is_tunable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_NOTIFY_MIN_SEVERITY", "CRITICAL")
    rec = _Recorder()
    assert _push(rec, sev="HIGH") == notify.BELOW_SEVERITY
    assert _push(rec, sev="CRITICAL") == notify.PUSHED
