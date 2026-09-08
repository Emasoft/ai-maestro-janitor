"""Tests for rotate_to.py (TRDD-S2RZHXU7): the one-call account rotation script.

Real code against a monkeypatched rotator (same isolation shape as test_oauth_rotator.py's
own autouse fixture — ROOT/LOG_FILE redirected to a throwaway tmp dir) plus direct
monkeypatches of `load_state`/`save_state`/`read_slot`/`usage_request`/`read_live_blob`/
`write_live_blob` (the exact functions several existing rotator tests stub) so nothing here
touches a real keychain or the real oauth-usage endpoint.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROTATE_TO_PY = _HERE.parent / "scripts" / "oauth_rotator" / "rotate_to.py"


def _load_rotate_to():
    """Import rotate_to.py by path (it lives outside any package, like rotator.py)."""
    spec = importlib.util.spec_from_file_location("rotate_to_under_test", _ROTATE_TO_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rt = _load_rotate_to()
rotator = rt.rotator


@pytest.fixture(autouse=True)
def _isolate_rotator_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect ROOT/LOG_FILE to a throwaway dir for every test (mirrors
    test_oauth_rotator.py's own fixture) so `_switch_blob`'s ROOT-derived side files
    (stuck marker, live-identity beacon) never touch real state."""
    monkeypatch.setattr(rotator, "ROOT", tmp_path)
    monkeypatch.setattr(rotator, "LOG_FILE", tmp_path / "rotator.log")


def _blob(token: str, *, expires_ms: int | None = None) -> dict:
    inner: dict = {"accessToken": token, "refreshToken": "r"}
    if expires_ms is not None:
        inner["expiresAt"] = expires_ms
    return {"claudeAiOauth": inner}


def _limit(*, percent: float, model: str = "Fable") -> dict:
    """One `limits[]` entry in the shape /api/oauth/usage emits."""
    return {
        "kind": "weekly_scoped", "group": "weekly", "percent": percent, "severity": "normal",
        "resets_at": "2099-01-01T00:00:00Z",
        "scope": {"model": {"id": None, "display_name": model}, "surface": None},
        "is_active": False,
    }


def _usage(*, five: float, seven: float, fable: float | None = None, no_resets: bool = False) -> dict:
    """A usage payload. `no_resets=True` builds the never-probed shape (utilization present,
    resets_at absent) that must NOT be read as a genuine 0%-used candidate."""
    reset = None if no_resets else "2099-01-01T00:00:00Z"
    out: dict = {
        "five_hour": {"utilization": five, "resets_at": reset},
        "seven_day": {"utilization": seven, "resets_at": reset},
    }
    if fable is not None:
        out["limits"] = [_limit(percent=fable)]
    return out


def _known(monkeypatch: pytest.MonkeyPatch, emails: set) -> None:
    def _cmd() -> int:
        for e in sorted(emails):
            print(e)
        return 0
    monkeypatch.setattr(rotator, "cmd_known_emails", _cmd)


def _wire_state(monkeypatch: pytest.MonkeyPatch, *, live: str, slots: dict, usages: dict) -> dict:
    """slots: {email: blob}; usages: {email: (status, usage_dict)}. Returns the mutable
    `saved` dict `save_state` is captured into."""
    state = {"live_email": live, "slots": dict.fromkeys(slots)}
    saved: dict = {}
    monkeypatch.setattr(rotator, "load_state", lambda *a, **k: state)
    monkeypatch.setattr(rotator, "save_state", saved.update)
    monkeypatch.setattr(rotator, "read_slot", lambda email: slots.get(email))

    def _usage_request(blob: dict) -> tuple[int, dict | None]:
        for email, b in slots.items():
            if b is blob:
                return usages.get(email, (0, None))
        return (0, None)

    monkeypatch.setattr(rotator, "usage_request", _usage_request)
    monkeypatch.setattr(rotator, "read_live_blob", lambda: {})
    monkeypatch.setattr(rotator, "write_live_blob", lambda b: None)
    return saved


def test_unknown_email_exits_2(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """A name that is not a known slot refuses with UNKNOWN_ACCOUNT, exit 2 — no switch attempted."""
    _known(monkeypatch, {"live@example.com"})
    monkeypatch.setattr(rotator, "load_state", lambda *a, **k: {"live_email": "live@example.com", "slots": {}})
    rc = rt.main(["rotate_to.py", "ghost@example.com"])
    assert rc == 2
    assert capsys.readouterr().out.splitlines()[0] == "UNKNOWN_ACCOUNT ghost@example.com"


def test_explicit_email_switches(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """A known, non-live email switches via rotator.cmd_switch and reports ROTATED as the
    first (and only) stdout line — cmd_switch's own chatter is swallowed."""
    slots = {"live@example.com": _blob("LIVE"), "alt@example.com": _blob("ALT")}
    saved = _wire_state(monkeypatch, live="live@example.com", slots=slots, usages={})
    _known(monkeypatch, set(slots))
    rc = rt.main(["rotate_to.py", "alt@example.com"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.splitlines() == ["ROTATED alt@example.com"]
    assert saved["live_email"] == "alt@example.com"


def test_already_live_exits_0(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """Naming the already-live account is a no-op success — idempotent, no switch attempted."""
    slots = {"live@example.com": _blob("LIVE")}
    _wire_state(monkeypatch, live="live@example.com", slots=slots, usages={})
    _known(monkeypatch, {"live@example.com"})
    rc = rt.main(["rotate_to.py", "live@example.com"])
    assert rc == 0
    assert capsys.readouterr().out.splitlines()[0] == "ALREADY_LIVE live@example.com"


def test_fable_headroom_ranking_picks_lowest_fable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """With multiple candidates under the account-headroom bar, the one with the LOWEST
    Fable usage (most Fable headroom) wins — no model-fallback keystroke needed."""
    slots = {"live@example.com": _blob("LIVE"), "alt-a@example.com": _blob("ALT-A"), "alt-b@example.com": _blob("ALT-B")}
    usages = {
        "alt-a@example.com": (200, _usage(five=10, seven=20, fable=80)),
        "alt-b@example.com": (200, _usage(five=10, seven=20, fable=30)),
    }
    _wire_state(monkeypatch, live="live@example.com", slots=slots, usages=usages)
    rc = rt.main(["rotate_to.py"])
    out = capsys.readouterr().out.splitlines()[0]
    assert rc == 0
    assert out == "ROTATED alt-b@example.com fable=30% 5h=10% 7d=20%"


def test_no_fable_path_picks_max_headroom_and_requests_model_fallback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """When every candidate's Fable window is spent (>= SCOPED_SWITCH_AT), the one with the
    lowest account usage (max headroom) wins, and the /model opus keystroke is requested first."""
    slots = {"live@example.com": _blob("LIVE"), "alt-a@example.com": _blob("ALT-A"), "alt-b@example.com": _blob("ALT-B")}
    usages = {
        "alt-a@example.com": (200, _usage(five=50, seven=60, fable=95)),
        "alt-b@example.com": (200, _usage(five=10, seven=20, fable=99)),
    }
    _wire_state(monkeypatch, live="live@example.com", slots=slots, usages=usages)
    monkeypatch.setattr(rt, "_request_model_opus", lambda: "not-automatable")
    rc = rt.main(["rotate_to.py"])
    out = capsys.readouterr().out.splitlines()[0]
    assert rc == 0
    assert out == "ROTATED alt-b@example.com fable=99% 5h=10% 7d=20% [model-fallback: not-automatable]"


def test_no_candidate_exits_3(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """No non-live slot under the account-headroom bar -> NO_TARGET, exit 3, nothing switched."""
    slots = {"live@example.com": _blob("LIVE"), "alt@example.com": _blob("ALT")}
    usages = {"alt@example.com": (200, _usage(five=95, seven=95, fable=99))}
    _wire_state(monkeypatch, live="live@example.com", slots=slots, usages=usages)
    rc = rt.main(["rotate_to.py"])
    assert rc == 3
    assert capsys.readouterr().out.splitlines()[0].startswith("NO_TARGET")


def test_never_probed_slot_does_not_masquerade_as_max_headroom(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A slot whose payload carries utilization=0.0 with NO resets_at (never actually
    probed) must be excluded, not picked as the 0%-used 'best' candidate — token_burn's
    window builder drops an unparseable resets_at, so headroom here is UNPROVEN."""
    slots = {"live@example.com": _blob("LIVE"), "never-probed@example.com": _blob("NP"), "real@example.com": _blob("REAL")}
    usages = {
        "never-probed@example.com": (200, _usage(five=0, seven=0, no_resets=True)),
        "real@example.com": (200, _usage(five=40, seven=50, fable=10)),
    }
    _wire_state(monkeypatch, live="live@example.com", slots=slots, usages=usages)
    rc = rt.main(["rotate_to.py"])
    out = capsys.readouterr().out.splitlines()[0]
    assert rc == 0
    assert out == "ROTATED real@example.com fable=10% 5h=40% 7d=50%"


def test_slot_with_hours_of_token_life_remains_auto_pickable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A slot well outside the 0.5h EXPIRY_GRACE_H window (7h of token life left) is NOT
    excluded by the expiry check — only a token actually near/at death is."""
    healthy_ms = int((time.time() + 7 * 3600) * 1000)
    slots = {"live@example.com": _blob("LIVE"), "alt@example.com": _blob("ALT", expires_ms=healthy_ms)}
    usages = {"alt@example.com": (200, _usage(five=40, seven=50, fable=10))}
    _wire_state(monkeypatch, live="live@example.com", slots=slots, usages=usages)
    rc = rt.main(["rotate_to.py"])
    out = capsys.readouterr().out.splitlines()[0]
    assert rc == 0
    assert out == "ROTATED alt@example.com fable=10% 5h=40% 7d=50%"


def test_locally_expired_slot_is_never_auto_picked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A slot whose token is within EXPIRY_GRACE_H of its local expiresAt (or already past
    it) is excluded from auto-selection even when its usage numbers look best — a dead
    token is not a rotation target. An explicit <email> still keeps cmd_switch's own
    warn-then-switch behaviour (untouched by this exclusion)."""
    expired_ms = int((time.time() - 3600) * 1000)  # already expired an hour ago
    slots = {
        "live@example.com": _blob("LIVE"),
        "expired@example.com": _blob("EXP", expires_ms=expired_ms),
        "real@example.com": _blob("REAL"),
    }
    usages = {
        "expired@example.com": (200, _usage(five=1, seven=1, fable=1)),  # best numbers, but dead
        "real@example.com": (200, _usage(five=40, seven=50, fable=10)),
    }
    _wire_state(monkeypatch, live="live@example.com", slots=slots, usages=usages)
    rc = rt.main(["rotate_to.py"])
    out = capsys.readouterr().out.splitlines()[0]
    assert rc == 0
    assert out == "ROTATED real@example.com fable=10% 5h=40% 7d=50%"


def test_never_consults_server_chore_ownership(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """USER directive: this verb exists for when the rotator chore is OWNED BY THE
    AI-MAESTRO SERVER (nothing rotates janitor-side) and for use OUTSIDE the harness
    entirely — it must switch on its own with no liveness file, no daemon, and no
    chore-coordination check, even when env vars claim a server owns every chore."""
    import harness_backend  # sys.path already carries scripts/lib (rt's own import did it)

    monkeypatch.delenv("JANITOR_AIMAESTRO_LIVENESS_FILE", raising=False)
    monkeypatch.setenv("JANITOR_AIMAESTRO_SERVER_STATE", "up")
    monkeypatch.setenv("JANITOR_AIMAESTRO_SERVER_CHORES", "up")
    # Positive control: prove the env actually registers as "server owns every chore"
    # BEFORE trusting that rotate_to.py ignoring it means anything (an unrecognised
    # value would make this test pass vacuously).
    assert harness_backend.server_runs_chores() is True
    slots = {"live@example.com": _blob("LIVE"), "alt@example.com": _blob("ALT")}
    saved = _wire_state(monkeypatch, live="live@example.com", slots=slots, usages={})
    _known(monkeypatch, set(slots))
    rc = rt.main(["rotate_to.py", "alt@example.com"])
    assert rc == 0
    assert saved["live_email"] == "alt@example.com"
