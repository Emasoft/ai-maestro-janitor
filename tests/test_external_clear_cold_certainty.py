"""Cold-resume certainty + llm-ext resolution (TRDD-CEWVQ8DG).

Both defects these pin were MEASURED in this project's own logs, not imagined:

  * `source=resume fire=False why=cache state unknown — not clearing` — the shrink refused
    because the OPTIONAL agentlensPro probe could not answer, so a fleet of cold sessions each
    paid a full cache-creation write on its first turn.
  * `summary: permanent — llm-ext is not on PATH; not retrying` — the binary lives in a
    plugin-cache bin dir that an interactive shell has on PATH and a hook-spawned child does not,
    so every handoff degraded to the template.

The property that matters in both cases is the SAME one: a lever must not be reachable only when
some third party happens to be installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "lib"))

import external_clear as ec  # noqa: E402

_HOUR = 3600


class _Proc:
    def __init__(self, rc: int, out: str = "", err: str = "") -> None:
        self.returncode, self.stdout, self.stderr = rc, out, err


# --- D1: certainty from elapsed time alone ----------------------------------------


def test_age_past_the_certainty_floor_reports_expired() -> None:
    """An age beyond the longest possible cache TTL is CERTAIN expiry, with no probe involved."""
    assert ec.cache_expired_by_age(2 * _HOUR, ttl_minutes=5) is True


def test_age_below_the_floor_is_unknown_never_false() -> None:
    """Under the floor the answer is None — absence of certainty must not be reported as warmth."""
    assert ec.cache_expired_by_age(10 * 60, ttl_minutes=5) is None


def test_a_short_regime_ttl_cannot_lower_the_floor() -> None:
    """The 5-minute default TTL must NOT authorize a destructive clear at 6 minutes idle."""
    assert ec.cache_expired_by_age(6 * 60, ttl_minutes=5) is None
    assert ec.CERTAIN_EXPIRY_FLOOR_MINUTES == 60


def test_a_longer_configured_ttl_raises_the_floor() -> None:
    """A 2-hour TTL regime pushes certainty out to 2 hours — the floor is a minimum, not a cap."""
    assert ec.cache_expired_by_age(90 * 60, ttl_minutes=120) is None
    assert ec.cache_expired_by_age(121 * 60, ttl_minutes=120) is True


def test_an_unknown_age_stays_unknown() -> None:
    """An unmeasurable transcript must never authorize an unrecoverable /clear."""
    assert ec.cache_expired_by_age(None, ttl_minutes=5) is None


def test_the_age_predicate_never_returns_false() -> None:
    """Property: only True or None, so it can never override a probe that said 'expired'."""
    for age in (0, 60, 600, 3599, 3600, 86400):
        assert ec.cache_expired_by_age(age, ttl_minutes=5) in (True, None)


# --- D1: composition with the probe ------------------------------------------------


def test_a_probe_that_answered_expired_wins() -> None:
    """The probe is more precise than arithmetic, so its verdict is taken verbatim."""
    assert ec.resolve_cache_expired(True, last_turn_age_s=0, ttl_minutes=5) is True


def test_a_probe_that_said_warm_is_not_overridden_by_a_stale_transcript() -> None:
    """A warm probe must survive an old mtime — else we would throw away a LIVE cache."""
    assert ec.resolve_cache_expired(False, last_turn_age_s=99 * _HOUR, ttl_minutes=5) is False


def test_an_abstaining_probe_falls_back_to_the_age() -> None:
    """The whole point: agentlensPro absent no longer means the lever is unreachable."""
    assert ec.resolve_cache_expired(None, last_turn_age_s=3 * _HOUR, ttl_minutes=5) is True


def test_an_abstaining_probe_on_a_fresh_session_stays_unknown() -> None:
    """Recently active + no probe = no certainty = no clear."""
    assert ec.resolve_cache_expired(None, last_turn_age_s=120, ttl_minutes=5) is None


def test_the_resume_gate_fires_on_an_age_derived_verdict() -> None:
    """End-to-end for D1: the exact refusal seen in the log now becomes a fire."""
    verdict = ec.should_clear_on_resume(
        source="resume",
        cache_expired=ec.resolve_cache_expired(None, last_turn_age_s=3 * _HOUR, ttl_minutes=5),
        context_tokens=431_357,
        min_context=150_000,
        in_cooldown=False,
        already_fired_this_session=False,
    )
    assert verdict.fire is True
    assert verdict.trigger == ec.TRIGGER_RESUMED_COLD


# --- D2: resolving the CLI without an interactive PATH ------------------------------


def _install(home: Path, version: str, marketplace: str = "emasoft-plugins") -> Path:
    binary = home / ".claude" / "plugins" / "cache" / marketplace / "llm-externalizer" / version / "bin" / "llm-ext"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


def test_the_cli_is_found_with_an_empty_path(tmp_path, monkeypatch) -> None:
    """The measured failure: a hook-spawned child has no profile PATH, but the binary is there."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    binary = _install(tmp_path, "13.5.1")
    assert ec.resolve_llm_ext() == str(binary)


def test_the_newest_version_wins_numerically_not_lexicographically(tmp_path, monkeypatch) -> None:
    """As strings '9.0.0' > '13.5.1', which would pin the OLDEST install forever."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    _install(tmp_path, "9.0.0")
    newest = _install(tmp_path, "13.5.1")
    assert ec.resolve_llm_ext() == str(newest)


def test_a_genuinely_absent_cli_resolves_to_empty(tmp_path, monkeypatch) -> None:
    """No install anywhere must degrade to the template, not raise or invent a path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    assert ec.resolve_llm_ext() == ""


def test_a_real_path_entry_still_wins(tmp_path, monkeypatch) -> None:
    """An operator who put llm-ext on PATH keeps control — `which` is consulted first."""
    onpath = tmp_path / "bin"
    onpath.mkdir()
    shim = onpath / "llm-ext"
    shim.write_text("#!/bin/sh\n", encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(onpath))
    _install(tmp_path, "13.5.1")
    assert ec.resolve_llm_ext() == str(shim)


def test_the_summary_attempt_no_longer_reports_not_on_path(tmp_path, monkeypatch) -> None:
    """The regression pin for D2: a plugin-cache-only install must produce a SUMMARY, not a
    permanent 'not on PATH' that skips every retry and degrades the handoff."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    _install(tmp_path, "13.5.1")
    (tmp_path / ".claude" / "plugins" / "data" / "llm-externalizer-emasoft-plugins").mkdir(
        parents=True, exist_ok=True
    )
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")

    attempt = ec.attempt_llm_ext_summary(
        str(transcript), runner=lambda *a, **k: _Proc(0, "a real summary")
    )
    assert attempt.outcome == ec.OUTCOME_OK
    assert attempt.text == "a real summary"
