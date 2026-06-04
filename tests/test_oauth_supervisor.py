"""Tests for the OAuth-rotator supervisor (scripts/oauth_rotator/supervisor.py).

Since TRDD-f892e109 decision 3 the supervisor is ALERT-ONLY — the launchd agent
is gone and the daemon's 60 s oauth-rotator-tick Task owns rotation, so there is
nothing to heal. The pure decision core `diagnose(facts)` is exercised
exhaustively (opt-in gate, pinning-env alert, non-macos alert, the per-slot
setup-token-expiry alert). The I/O bits — `opt_in_present`, `_slot_facts`,
`gather_facts`, `apply` — run against tmp dirs. No mocks anywhere.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SUP_PY = _HERE.parent / "scripts" / "oauth_rotator" / "supervisor.py"


def _load():
    spec = importlib.util.spec_from_file_location("supervisor_under_test", _SUP_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so frozen @dataclass can resolve cls.__module__.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sup = _load()


def _facts(**kw):
    """A healthy, opted-in, macOS Facts; override fields per test."""
    base = dict(opt_in=True, on_macos=True, pinning_env=(), slots=())
    base.update(kw)
    return sup.Facts(**base)


def _codes(findings) -> set[str]:
    return {f.code for f in findings}


def test_opt_out_is_total_noop() -> None:
    """No opt-in flag → diagnose returns nothing, whatever else is wrong."""
    f = _facts(opt_in=False, pinning_env=("ANTHROPIC_API_KEY",))
    assert sup.diagnose(f) == []


def test_healthy_system_has_no_findings() -> None:
    """Opted-in on macOS + clean env + no slots → silent."""
    assert sup.diagnose(_facts()) == []


def test_pinning_env_alerts_per_var() -> None:
    """Each pinning env var that overrides the keychain → one 'pinning-env' alert."""
    f = _facts(pinning_env=("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"))
    findings = sup.diagnose(f)
    pin = [x for x in findings if x.code == "pinning-env"]
    assert len(pin) == 2
    assert "ANTHROPIC_API_KEY" in pin[0].message


def test_non_macos_alerts_only() -> None:
    """Opted-in off macOS → a single 'non-macos' alert (keychain swap can't run here)."""
    findings = sup.diagnose(_facts(on_macos=False))
    assert _codes(findings) == {"non-macos"}


def test_setup_token_expiry_alerts_only_for_no_refresh() -> None:
    """A no-refresh setup-token within the remind window alerts; a full-OAuth
    slot (has_refresh) does NOT alert even when its own expiry is near."""
    soon = sup.SETUP_REMIND_DAYS - 1
    setup = sup.SlotFact(email="s@x.com", has_refresh=False, expires_days=soon)
    full = sup.SlotFact(email="f@x.com", has_refresh=True, expires_days=soon)
    findings = sup.diagnose(_facts(slots=(setup, full)))
    alerts = [x for x in findings if x.code == "setup-token-expiring"]
    assert len(alerts) == 1
    assert "s@x.com" in alerts[0].message
    # A no-refresh token NOT yet inside the window does not alert:
    far = sup.SlotFact(email="ok@x.com", has_refresh=False,
                       expires_days=sup.SETUP_REMIND_DAYS + 100)
    assert not [x for x in sup.diagnose(_facts(slots=(far,))) if x.code == "setup-token-expiring"]


def test_slot_facts_reads_refresh_and_expiry(tmp_path: Path) -> None:
    """_slot_facts parses has_refresh + expires_days from real slot JSON files."""
    slots = tmp_path / "slots"
    slots.mkdir()
    now = 1_780_000_000.0  # realistic epoch so ms-values clear the >1e12 ms/sec heuristic
    # full OAuth: refresh present, expires in 2 days (ms epoch)
    (slots / "full@x.com.json").write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "a", "refreshToken": "r",
        "expiresAt": int((now + 2 * 86400) * 1000)}}))
    # setup-token: no refresh, expires in 5 days (ms epoch)
    (slots / "setup@x.com.json").write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "a", "refreshToken": None,
        "expiresAt": int((now + 5 * 86400) * 1000)}}))
    facts = {s.email: s for s in sup._slot_facts(tmp_path, now)}
    assert facts["full@x.com"].has_refresh is True
    assert abs(facts["full@x.com"].expires_days - 2.0) < 0.01
    assert facts["setup@x.com"].has_refresh is False
    assert abs(facts["setup@x.com"].expires_days - 5.0) < 0.01


def test_opt_in_present_tracks_the_flag(tmp_path: Path) -> None:
    """opt_in_present() is the daemon tick gate: True iff opt-in.flag exists."""
    assert sup.opt_in_present(root=tmp_path) is False
    (tmp_path / "opt-in.flag").write_text("on")
    assert sup.opt_in_present(root=tmp_path) is True


def test_gather_facts_opt_out_when_flag_absent(tmp_path: Path) -> None:
    """gather_facts against a root with no opt-in.flag → opt_in False, no slots,
    and diagnose stays a no-op (never touches launchd/keychain)."""
    facts = sup.gather_facts(root=tmp_path, now=1_000_000.0)
    assert facts.opt_in is False
    assert facts.slots == ()
    assert sup.diagnose(facts) == []


def test_apply_records_alerts_and_logs() -> None:
    """apply() records every alert finding's code and logs it (the supervisor
    heals nothing now that the daemon owns the tick)."""
    logs: list[str] = []
    findings = [
        sup.Finding("pinning-env", "$ANTHROPIC_API_KEY set"),
        sup.Finding("setup-token-expiring", "s@x.com expiring"),
    ]
    res = sup.apply(findings, log=logs.append)
    assert res.alerts == ["pinning-env", "setup-token-expiring"]
    assert any("pinning-env" in m for m in logs)
