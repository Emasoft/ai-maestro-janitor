"""User-intent provenance — the one place that can tell "the USER asked" from "an agent decided".

The janitor has exactly ONE surface that sees the user's raw keystrokes: the `UserPromptSubmit` hook.
Everything downstream of it — a skill, a detector, a heartbeat marker — is the *model* acting. So any
state whose meaning is "a human authorized this" MUST be stamped from that hook, or it is an
authority claim that nobody ever checked. Both bugs this module exists to fix are exactly that:

- **`disarmed.flag` (TRDD-RDFWQIFA).** The flag means "the USER opted out", and the fleet guardian
  treats such a project as sacrosanct — it will not re-arm a heartbeat that a human deliberately
  stopped. But `/janitor-disarm` wrote it unconditionally, so an agent that ran the skill on its own
  judgment FORGED a human decision and permanently disabled the one mechanism that would have undone
  its mistake. (It did. The session sat dead for hours on 2026-07-14.)

- **Self-injection (TRDD-USRPRES1).** The self-trigger types a slash-command into the session's own
  terminal pane. Do that while the user is mid-sentence and it CLOBBERS their input — which is not
  hypothetical either: a `[janitor-reload]` marker fired `/reload-plugins` into the user's pane while
  they were typing and truncated their message. The *fleet* injector already refuses to type into a
  pane whose user is active (`fleet_stop.is_injectable`); the *self*-trigger never checked.

The asymmetry that makes this safe: this module's `record_intent_from_prompt` runs ONLY from the
UserPromptSubmit hook, which by construction only ever sees genuine user input (cron `[janitor-…]`
prompts are filtered out upstream). An agent cannot call it with a prompt it made up, because an agent
never gets to author a UserPromptSubmit payload.

**Failure direction is deliberate.** Every consumer of this module degrades SAFELY when no intent is
found: the disarm still stops the cron (it just doesn't claim the user opted out, so the guardian may
re-arm), and the injection is simply not sent (the model tells the user to run the command instead).
So a MISSED intent costs a little friction, while a FALSELY-ASSUMED intent costs a forged human
decision or a clobbered prompt. We therefore match conservatively and NEVER guess.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import state  # noqa: E402

# How long a recorded intent stays valid. The user types `/janitor-disarm`, the skill runs seconds
# later — this only has to bridge that gap. Generous, but far short of "the rest of the session".
INTENT_TTL_S = 600  # 10 minutes

# How long after the user's last keystroke we still consider them PRESENT at the terminal.
#
# The per-pane presence window (user directive 2026-07-16): "if I typed in the pane in the last 5
# minutes I must be considered present." Before per-pane keying this was biased LONG (30 min)
# because the breadcrumb was machine-global and a false-absent could clobber a human typing in ANY
# session; now the gate is scoped to THIS pane (state.terminal_pane_key), so 30 min was pure
# over-block — it kept an unattended pane gated for a full half-hour after the user's last keystroke
# HERE, defeating self-trigger. 5 min covers a human who is actively working this pane while letting
# a pane they walked away from self-trigger promptly. Tunable via env; any value ≤0 coerces back to
# the default so the gate can never be silently disabled to 0s.
USER_PRESENT_IDLE_S = 300  # 5 minutes

# The verbs whose authority we track. Keyed by verb → the slash-commands that mean it.
_VERB_COMMANDS: dict[str, tuple[str, ...]] = {
    "disarm": ("/janitor-disarm",),
    "global-disarm": ("/janitor-global-disarm",),
    "global-pause": ("/janitor-global-pause",),
    "arm": ("/janitor-arm",),
    "reload": ("/janitor-reload-plugins", "/reload-plugins"),
    "reload-skills": ("/janitor-reload-skills", "/reload-skills"),
    "compact": ("/janitor-compact-context", "/compact", "/janitor-write-handoff"),
    "resume": ("/janitor-resume",),
}

# Natural-language forms that unambiguously request a verb. Kept TIGHT: an over-eager pattern here
# manufactures consent, which is the whole failure mode this module exists to prevent.
_VERB_PHRASES: dict[str, tuple[str, ...]] = {
    "disarm": (
        r"\bdisarm\b[^.!?]{0,40}\bjanitor\b",
        r"\bjanitor\b[^.!?]{0,40}\bdisarm\b",
        r"\bstop\b[^.!?]{0,30}\bjanitor\b",
        r"\bkill\b[^.!?]{0,30}\b(janitor|heartbeat)\b[^.!?]{0,20}\bcron\b",
    ),
    "global-disarm": (
        r"\bdisarm\b[^.!?]{0,40}\b(globally|machine[- ]wide|everywhere|all\s+projects)\b",
        r"\bstop\b[^.!?]{0,30}\b(all|every)\b[^.!?]{0,20}\bjanitors?\b",
    ),
    "global-pause": (r"\bpause\b[^.!?]{0,40}\b(globally|machine[- ]wide|everywhere|all\s+projects)\b",),
    "reload": (r"\breload\b[^.!?]{0,20}\bplugins?\b",),
    "reload-skills": (r"\breload\b[^.!?]{0,20}\bskills?\b",),
    "compact": (r"\bcompact\b[^.!?]{0,30}\b(context|conversation|session)\b",),
}

# A prompt carrying a negation anywhere is NEVER treated as a request. This is not paranoia: the very
# message that exposed the disarm bug was *"you must NEVER disarm the janitor heartbeat!!"* — which
# names the verb and the subject, and would have been read as a REQUEST TO DISARM by any matcher
# without this guard. The user's angriest possible "don't do X" would have authorized X.
_NEGATION_RE = re.compile(
    r"\b(?:do\s?n[o']?t|dont|don't|never|no\s+longer|stop\s+\w+ing|avoid|without|refrain)\b",
    re.IGNORECASE,
)


def intent_path(verb: str, state_dir: Path | None = None) -> Path:
    """Where a recorded intent for `verb` lives (per project, alongside the other janitor state)."""
    base = state_dir if state_dir is not None else state.state_dir()
    return Path(base) / f"user-intent-{verb}.ts"


def verbs_for_commands(commands: list[str] | tuple[str, ...]) -> set[str]:
    """Which verbs the given slash-commands correspond to. Unknown commands map to nothing."""
    wanted: set[str] = set()
    for cmd in commands:
        head = cmd.strip().split()[0] if cmd.strip() else ""
        for verb, forms in _VERB_COMMANDS.items():
            if head in forms:
                wanted.add(verb)
    return wanted


def record_intent_from_prompt(prompt: str, *, state_dir: Path | None = None, now: int | None = None) -> list[str]:
    """Stamp an intent token for every verb the USER's raw prompt explicitly asks for.

    Called ONLY from the UserPromptSubmit hook — that is what makes the token unforgeable. Returns
    the verbs stamped (for tests/logging). Best-effort: never raises, so a stamping problem can never
    break the user's turn.
    """
    if not prompt or not prompt.strip():
        return []
    # One negation anywhere disqualifies the WHOLE prompt. Coarse on purpose: a prompt that both
    # forbids and requests the same verb is ambiguous, and ambiguity must not become consent.
    if _NEGATION_RE.search(prompt):
        return []

    ts = int(time.time()) if now is None else int(now)
    stamped: list[str] = []
    for verb in _VERB_COMMANDS:
        hit = any(cmd in prompt for cmd in _VERB_COMMANDS[verb]) or any(re.search(pat, prompt, re.IGNORECASE) for pat in _VERB_PHRASES.get(verb, ()))
        if not hit:
            continue
        try:
            state.atomic_write(intent_path(verb, state_dir), str(ts))
            stamped.append(verb)
        except OSError:
            pass  # never break the turn over a breadcrumb
    return stamped


def intent_fresh(
    verb: str,
    *,
    ttl_s: int = INTENT_TTL_S,
    state_dir: Path | None = None,
    now: int | None = None,
) -> bool:
    """True iff the USER asked for `verb` within the last `ttl_s` seconds."""
    ts = state.read_int_state(intent_path(verb, state_dir), 0)
    if ts <= 0:
        return False
    current = int(time.time()) if now is None else int(now)
    return (current - ts) <= ttl_s


def consume_intent(verb: str, state_dir: Path | None = None) -> None:
    """Spend a recorded intent so ONE request authorizes exactly ONE action, not a standing licence."""
    try:
        intent_path(verb, state_dir).unlink()
    except OSError:
        pass


def _presence_epoch(path: Path) -> int | None:
    """`last_user_input_epoch` from a presence breadcrumb, or None if unreadable/corrupt.

    None is the fail-CLOSED signal (the caller treats it as "present, do not inject"); a
    valid `0` means the breadcrumb exists but no input was ever recorded.
    """
    try:
        raw = path.read_text(encoding="utf-8")
        return int(json.loads(raw)["last_user_input_epoch"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def user_is_present(
    *,
    idle_s: int = USER_PRESENT_IDLE_S,
    home: Path | None = None,
    now: int | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    """True iff the user typed recently IN THIS PANE — i.e. they are AT this terminal right now.

    Presence is PER-PANE (user directive 2026-07-16). The old machine-global breadcrumb made a
    human typing in ANY session mark EVERY unattended pane on the machine "present" for 30 min,
    so a fleet where the user pokes one session had self-trigger (compact/reload) blocked
    everywhere. Now the gate reads THIS pane's own breadcrumb (keyed by `state.terminal_pane_key`,
    the SAME id the UserPromptSubmit hook stamps): a pane the user has never typed in is
    correctly "away", regardless of activity elsewhere.

    Resolution order:
      * pane id resolvable (tmux/iTerm) → read the PER-PANE breadcrumb. ABSENT means the user
        never typed HERE → away (safe to inject: there are no in-progress keystrokes to clobber,
        the one harm the gate exists to prevent). Present+recent → present; present+old → away;
        corrupt → present (fail-closed).
      * pane id NOT resolvable (plain terminal — which also cannot be self-triggered) → fall back
        to the machine-global breadcrumb, preserving the pre-2026-07-16 behaviour.

    Fails CLOSED: a corrupt/unreadable breadcrumb returns True (assume present), so a breadcrumb
    problem can never license typing into someone's pane.
    """
    current = int(time.time()) if now is None else int(now)
    pane_key = state.terminal_pane_key(env)
    if pane_key is not None:
        pane_path = state.per_pane_presence_path(pane_key, home)
        if not pane_path.exists():
            return False  # user never typed in THIS pane → unattended here
        last = _presence_epoch(pane_path)
        if last is None:
            return True  # corrupt → fail closed
        if last <= 0:
            return False  # stamped but no real input recorded → unattended
        return (current - last) <= idle_s
    # No pane id → machine-global fallback (unchanged behaviour).
    last = _presence_epoch(state.user_presence_path(home))
    if last is None:
        return True  # unknown → assume present → do not inject
    if last <= 0:
        return False  # breadcrumb exists but no user input was EVER recorded → unattended
    return (current - last) <= idle_s


def _resolve_idle_s(env: Mapping[str, str] | None) -> int:
    """The presence window in seconds — the 5-min default, overridable via env.

    ``CLAUDE_PLUGIN_OPTION_SELF_TRIGGER_PRESENCE_IDLE_S`` tunes it; a non-int or a value ≤0
    coerces back to the default, so the gate can never be silently disabled to a 0-second
    window (which would let a self-trigger clobber a human who typed a moment ago)."""
    e = os.environ if env is None else env
    raw = e.get("CLAUDE_PLUGIN_OPTION_SELF_TRIGGER_PRESENCE_IDLE_S")
    if raw is None:
        return USER_PRESENT_IDLE_S
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return USER_PRESENT_IDLE_S
    return val if val > 0 else USER_PRESENT_IDLE_S


def injection_allowed(
    commands: list[str] | tuple[str, ...],
    *,
    state_dir: Path | None = None,
    home: Path | None = None,
    now: int | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    """May we type `commands` into the user's own pane right now? Returns (allowed, why).

    The rule, in one line: **inject only when the user is away FROM THIS PANE, or when they asked.**

    Presence is per-pane and the window is 5 min (user directive 2026-07-16); see
    `user_is_present`. A fresh intent token is CONSUMED on success, so one request buys one
    injection.
    """
    if not user_is_present(idle_s=_resolve_idle_s(env), home=home, now=now, env=env):
        return True, "user is away"
    for verb in verbs_for_commands(list(commands)):
        if intent_fresh(verb, state_dir=state_dir, now=now):
            consume_intent(verb, state_dir)
            return True, f"user explicitly asked ({verb})"
    return False, "user is present and did not ask"
