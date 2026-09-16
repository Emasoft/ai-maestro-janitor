#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""rotate_to.py [email] — one-call account rotation (TRDD-S2RZHXU7).

USER directive 2026-09-06: the manual path (recall, list slots, read usage, find the
switch verb, run it) took ~15 tool calls while the Fable window sat at 100%. The
keychain write itself is one call; the cost was entirely in FINDING the target. This
script IS that one call — it reuses `rotator.py`'s slot reads, usage probe and switch
primitive, adding only the selection ranking the card asks for.

Never prompts, never sleeps, never retries. Every failure is one stdout token + a
non-zero exit, so the wrapping skill can relay the first line verbatim.
"""

from __future__ import annotations

import contextlib
import io
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_LIB = _HERE.parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import rotator  # type: ignore[import-not-found]  # noqa: E402
import terminal_trigger  # type: ignore[import-not-found]  # noqa: E402
import token_burn  # type: ignore[import-not-found]  # noqa: E402


def _known_emails() -> set[str]:
    """`rotator.cmd_known_emails()` only prints — capture its stdout instead of
    re-walking slots/state/live ourselves (that roster's root-resolution edge cases
    already live in one place; duplicating it here is how the two rosters drift)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rotator.cmd_known_emails()
    return {line.strip() for line in buf.getvalue().splitlines() if line.strip()}


def _fable_used(usage: dict | None, now: int) -> float | None:
    """Fable's own percent-USED, or None when the payload carries no Fable-scoped window
    (unknown headroom ranks last, never treated as spent or as clear)."""
    if not usage:
        return None
    windows = [
        w for w in token_burn.model_windows_from_usage(usage, now)
        if str(w.get("label", "")).rsplit("/", 1)[-1] == "Fable"
    ]
    if not windows:
        return None
    return max(float(w["util_pct"]) for w in windows)


def _account_windows(usage: dict, now: int) -> dict[str, float]:
    """label ("5h"/"7d") -> util_pct, PROVEN only. `token_burn.windows_from_usage` drops a
    window whose `resets_at` does not parse — a never-probed slot's flat
    `{"utilization": 0.0, "resets_at": None}` therefore contributes NOTHING here, instead
    of masquerading as a genuine 0%-used (max-headroom) candidate."""
    return {str(w["label"]): float(w["util_pct"]) for w in token_burn.windows_from_usage(usage, now)}


def _request_model_opus() -> str:
    """Type `/model opus` into this session's own pane before a no-Fable-headroom switch
    (owner directive). Returns 'typed' or 'not-automatable' — never raises; a rotation
    that already found its target must not fail over a keystroke."""
    # `self_terminal()` is the injector's own pane resolver (validates the tmux pane / iTerm
    # session id it finds in the env); a local copy here would be a second definition of
    # "this session's pane" for the two to drift apart on.
    terminal = terminal_trigger.self_terminal()
    if terminal["kind"] == "unknown":
        return "not-automatable"
    try:
        # why: this call is itself part of rotation/recovery (a post-rotation model
        # switch when no Fable headroom remains) -- it must land even inside the
        # self-send interrupt cooldown, same as the rotation send it follows.
        sent, _why = terminal_trigger.send_verified(
            terminal, "/model opus", esc_first=True, bypass_interrupt_cooldown=True,
        )
    except Exception as exc:  # noqa: BLE001 — keystroke failure must not block the rotation
        # Rotation must continue on a failed keystroke, but silently swallowing it
        # is the exact failure shape TRDD-V2U2ZECI removed elsewhere: the operator
        # needs to see WHY the model switch was not typed, not just that it wasn't.
        if sys.stderr is not None:
            sys.stderr.write(
                f"janitor rotate_to: WARNING /model opus not typed "
                f"({type(exc).__name__}: {exc}); continuing\n"
            )
        return "not-automatable"
    return "typed" if sent else "not-automatable"


def _pick_target(now: int) -> tuple[str, dict, float | None, float, float, bool] | None:
    """Rank every non-live slot with a readable usage snapshot. Returns
    (email, blob, fable_used, five_hour_used, seven_day_used, needs_model_fallback), or
    None when no slot qualifies.

    Both rotator knobs are percent-USED thresholds (verified against
    `token_burn.model_fallback_verdict`): a slot is a CANDIDATE when its worst account
    window is at/under `SCOPED_ACCOUNT_HEADROOM`; among candidates, one with a Fable
    window strictly under `SCOPED_SWITCH_AT` still has model headroom. Prefer the lowest
    Fable usage; failing that, the lowest account usage (max headroom) — which needs the
    `/model opus` keystroke first, since it means every candidate's Fable window is spent.
    """
    state = rotator.load_state()
    live = state.get("live_email")
    candidates: list[tuple[str, dict, float | None, float, float]] = []
    # has-Fable-headroom membership is ONE shared predicate (token_burn.model_headroom_candidate):
    # the model-fallback detector's rotate-first stand-down asks it about the same slots, so it
    # can never name a slot this verb would refuse (TRDD-M4HVFU2A review, 2026-09-08).
    with_headroom: set[str] = set()
    for email in state.get("slots", {}):
        if email == live:
            continue
        blob = rotator.read_slot(email)
        if blob is None:
            continue
        if rotator._blob_locally_expired(blob):
            continue  # a token about to die is not a rotation target — cmd_switch(email) still works
        status, usage = rotator.usage_request(blob)
        if status != 200 or usage is None:
            continue
        windows = _account_windows(usage, now)
        if not windows:
            continue  # unproven headroom (never-probed slot) — never rank an unknown as clear
        fh = windows.get("5h")
        sd = windows.get("7d")
        account_used = max(v for v in (fh, sd) if v is not None)
        if account_used > rotator.SCOPED_ACCOUNT_HEADROOM:
            continue
        if token_burn.model_headroom_candidate(
            usage, now, "Fable",
            scoped_high=rotator.SCOPED_SWITCH_AT, account_headroom=rotator.SCOPED_ACCOUNT_HEADROOM,
        ) is not None:
            with_headroom.add(email)
        candidates.append((email, blob, _fable_used(usage, now), fh or 0.0, sd or 0.0))
    if not candidates:
        return None
    with_fable_headroom: list[tuple[str, dict, float, float, float]] = [
        (email, blob, fable, fh, sd) for email, blob, fable, fh, sd in candidates
        if email in with_headroom and fable is not None
    ]
    if with_fable_headroom:
        best_f = min(with_fable_headroom, key=lambda c: c[2])
        return (*best_f, False)
    best = min(candidates, key=lambda c: max(c[3], c[4]))
    return (*best, True)


def main(argv: list[str]) -> int:
    email = argv[1].strip() if len(argv) > 1 else ""
    state = rotator.load_state()
    live = state.get("live_email")

    if email:
        if email == live:
            print("ALREADY_LIVE %s" % email)
            return 0
        if email not in _known_emails():
            print("UNKNOWN_ACCOUNT %s" % email)
            return 2
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = rotator.cmd_switch(email)
        # cmd_switch's stdout is captured so the first line stays the token, but its
        # WARNING (e.g. "token is already expired") must not vanish with it — the operator
        # named this account, so they get the switch AND the caveat, on stderr.
        for line in buf.getvalue().splitlines():
            if line.startswith("WARNING"):
                print(line, file=sys.stderr)
        if rc != 0:
            print("SWITCH_FAILED %s" % email)
            return rc or 1
        print("ROTATED %s" % email)
        return 0

    now = int(time.time())
    picked = _pick_target(now)
    if picked is None:
        print("NO_TARGET no non-live slot has both a usable usage snapshot and account headroom")
        return 3
    target, blob, fable_used, fh, sd, needs_model_fallback = picked
    fallback_note = ""
    if needs_model_fallback:
        fallback_note = " [model-fallback: %s]" % _request_model_opus()
    rotator._switch_blob(target, blob, reason="rotate_to.py auto-select")
    fable_s = ("%.0f" % fable_used) if fable_used is not None else "?"
    print("ROTATED %s fable=%s%% 5h=%.0f%% 7d=%.0f%%%s" % (target, fable_s, fh, sd, fallback_note))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
