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
import token_history  # noqa: E402  -- sibling lib; leaf-safe, provides parse_ts

# How long a recorded intent stays valid. The user types `/janitor-disarm`, the skill runs seconds
# later — this only has to bridge that gap. Generous, but far short of "the rest of the session".
INTENT_TTL_S = 600  # 10 minutes

# An Esc/Ctrl-C interrupt produces NO keystroke the typing probe (`typing_now`) can see, so a
# queued self-injector types over "I just stopped it" the moment the pane goes idle (owner
# complaint 2026-09-15). This is the marker Claude Code itself writes as a `type: user` transcript
# record on every interrupt — it has (at least) two live variants (`[Request interrupted by
# user]` on a bare Esc, `[Request interrupted by user for tool use]` mid-tool-call), verified
# against real transcripts before coding against it. Matched EXACTLY, never by prefix: a
# compaction summary that merely QUOTES the phrase must not count as a real interrupt.
INTERRUPT_MARKERS = (
    "[Request interrupted by user]",
    "[Request interrupted by user for tool use]",
)
INTERRUPT_COOLDOWN_ENV = "CLAUDE_PLUGIN_OPTION_INTERRUPT_COOLDOWN_S"
DEFAULT_INTERRUPT_COOLDOWN_S = 300
# Mirrors `token_meter._HEARTBEAT_MARKER` (duplicated, not imported, to avoid pulling that
# module's own imports into this leaf lib): the cron heartbeat's OWN triggering prompt starts
# with this line and is NOT a human keystroke -- see the skip in `recently_interrupted`, below.
_HEARTBEAT_MARKER = "[janitor-heartbeat]"
# The initial (and doubling-step) size of `recently_interrupted`'s backward scan window. A
# module constant, not a local literal, so a test can shrink it to force multiple doublings
# without needing a multi-hundred-KB fixture transcript.
_INTERRUPT_SCAN_CHUNK_BYTES = 64 * 1024

# How long after the user's last PROMPT SUBMIT we still consider them PRESENT at the terminal.
#
# NOTE the signal is SUBMIT-based, not per-keystroke: the breadcrumb is stamped only by the
# UserPromptSubmit hook (state.bump_user_presence), so "typed in the last N seconds" really means
# "submitted a prompt in the last N seconds" — a user composing a long follow-up they have NOT yet
# submitted reads as ABSENT once the window elapses. That is the risk a small window trades against
# faster resume, and it is why the window can never coerce to 0s (below).
#
# The window shrank 5 min → 10 s (owner directive 2026-07-17), then moved to 20 s ON A REAL
# TYPING SIGNAL (owner directive 2026-07-18): the breadcrumb is stamped only at prompt SUBMIT,
# so a user MID-TYPING with their last Enter >10 s ago read as ABSENT and got commands injected
# under their fingers — shrinking the window made that WORSE, not better. The owner's rule,
# verbatim: "make sure the user is detected as present if it was typing in the last 20 seconds."
# `hid_idle_seconds()` (macOS IOHIDSystem, nanoseconds since the last keyboard/mouse event) is
# that typing signal, and `user_is_present` consults it FIRST — any keystroke anywhere in the
# last 20 s means PRESENT, machine-wide, because a human at the keyboard must never have
# commands typed under them no matter which pane the injector targets. The per-pane breadcrumb
# (user directive 2026-07-16) remains the fallback for platforms without the HID probe.
# Tunable via CLAUDE_PLUGIN_OPTION_SELF_TRIGGER_PRESENCE_IDLE_S; any value ≤0 coerces back to
# the default so the gate can never be silently disabled to a 0-second window.
USER_PRESENT_IDLE_S = 20  # 20 seconds (owner directive 2026-07-18)
# Test/operator override for the rung-0 HID reading (see hid_idle_seconds).
HID_IDLE_OVERRIDE_ENV = "JANITOR_HID_IDLE_OVERRIDE_S"

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
    # MISSING UNTIL 2026-08-02, and its absence broke the user's own command. `clear_trigger`
    # correctly asks `injection_allowed(_ALL_CMDS)` — whose contract is "inject when the user is
    # away OR WHEN THEY ASKED" — but `_ALL_CMDS` is ['/clear', '/janitor-arm', '/janitor-resume']
    # and `/clear` mapped to NO verb, so `verbs_for_commands` returned only {arm, resume}. There
    # was nothing to check the intent AGAINST: the user typed `/janitor-handoff-and-clear`
    # themselves, no token was ever stamped, and the gate refused with USER_PRESENT — telling the
    # person at the keyboard to go away and try again when they are not there.
    #
    # The presence gate exists to stop the JANITOR typing into a pane someone is working in. When
    # the user issues the command, their presence is the AUTHORIZATION, not the objection. A verb
    # missing from this map does not fail closed in a safe direction — it silently removes the
    # only channel through which consent can be expressed at all.
    "clear": ("/janitor-handoff-and-clear", "/clear"),
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
    # Deliberately NOT a bare `\bclear\b`: "clear" is an ordinary English word ("is that clear",
    # "clear the error") and this verb authorises an IRREVERSIBLE action. Both forms below require
    # the object as well, so only a sentence actually about clearing the context matches.
    "clear": (
        r"\bhandoff[- ]and[- ]clear\b",
        r"\bclear\b[^.!?]{0,30}\b(context|conversation|session)\b",
    ),
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


def hid_idle_seconds(*, timeout_s: float = 3.0) -> float | None:
    """Seconds since the user's last REAL input event (keyboard or mouse), machine-wide,
    or None when unknowable (non-macOS, ioreg failure, parse miss).

    THE TYPING SIGNAL (TRDD-6Q0OYYYH, owner directive 2026-07-18): the presence breadcrumb
    is stamped only at prompt SUBMIT, so a user mid-typing read as absent and had commands
    injected under their fingers. macOS IOHIDSystem's HIDIdleTime is nanoseconds since the
    last HID event — it moves on EVERY keystroke, which is exactly what "was typing in the
    last 20 seconds" needs. Multiple registry matches → take the MINIMUM (the most recent
    event across input devices). Fail-open: None lets the caller fall back to the
    breadcrumb rungs rather than blocking or licensing an injection on a broken probe."""
    # Test/operator seam (TRDD-D2DD5GO8): a subprocess-driven test cannot monkeypatch this
    # module, and the REAL rung-0 probe reads the live keyboard — which made every test that
    # spawns the real injector hostage to whether a human happened to touch the machine
    # during its window. Set to a float ("9999" = provably idle, "1" = provably typing) or the
    # literal "blind" (probe unreadable — the incident's own condition, unreachable via any
    # number); malformed values fall through to the real probe rather than inventing a reading.
    override = os.environ.get(HID_IDLE_OVERRIDE_ENV, "").strip()
    if override:
        # "blind" reproduces the 2026-08-19 incident's actual condition — the probe EXISTS on
        # this platform and cannot be read (ioreg hung under load) — which the float values
        # cannot express, because a number is always a confident answer. Without it the one
        # state that caused the harm is the one state no drill can stage, so the guard against
        # it stays untestable on a healthy machine. Deliberately not spelled as a number: a
        # sentinel float would be indistinguishable from a real reading if it ever leaked into
        # an arithmetic path.
        if override.lower() == "blind":
            return None
        try:
            return float(override)
        except ValueError:
            pass
    if sys.platform != "darwin":
        return None
    try:
        import subprocess
        proc = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem", "-d", "4"],
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except Exception:  # noqa: BLE001 - a presence probe must never raise into an injection gate
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    best_ns: int | None = None
    for m in re.finditer(r'"HIDIdleTime"\s*=\s*(\d+)', proc.stdout):
        ns = int(m.group(1))
        if best_ns is None or ns < best_ns:
            best_ns = ns
    return None if best_ns is None else best_ns / 1e9


def user_presence(
    *,
    idle_s: int = USER_PRESENT_IDLE_S,
    home: Path | None = None,
    now: int | None = None,
    env: Mapping[str, str] | None = None,
) -> bool | None:
    """TRI-STATE presence: True = provably present, False = provably away, None = UNKNOWN.

    Extracted from `user_is_present` (2026-08-15) because ONE boolean cannot serve its two
    consumer classes, and forcing it to was a live defect on every headless runner:

      * INJECTORS (dispatch, on-stop-proactive-compact) must map unknown → present — typing
        `/clear` into a pane somebody might be using is unrecoverable. That mapping is
        `user_is_present()` below, unchanged.
      * The PUSH gate (post-compact-resume) and the TYPING PROBES (terminal_trigger) must map
        unknown → absent: their own documented contract is "no breadcrumb at all → treat as
        UNATTENDED", and mapping unknown → present there suppressed every push on a headless
        box AND spun `inject_until_sent`'s wait loop forever under a frozen test clock — the
        22-minute silent hang that killed the first Linux CI run (31844013197).

    The ladder itself is IDENTICAL to what `user_is_present` always ran; only the
    cannot-tell outcomes now say so instead of picking a side here. Consumers pick the side,
    each with its own safety argument at the call site (`is not False` = fail toward present;
    `is True` = fail toward absent).
    """
    # RUNG 0 — the REAL typing signal: any keyboard/mouse event in the last `idle_s`
    # seconds means the user is AT the machine RIGHT NOW, whatever pane is targeted.
    hid = hid_idle_seconds()
    if hid is not None and hid <= idle_s:
        return True
    current = int(time.time()) if now is None else int(now)
    pane_key = state.terminal_pane_key(env)
    if pane_key is not None:
        pane_path = state.per_pane_presence_path(pane_key, home)
        if not pane_path.exists():
            return False  # user never typed in THIS pane → provably unattended here
        last = _presence_epoch(pane_path)
        if last is None:
            return None  # corrupt breadcrumb → cannot tell
        if last <= 0:
            return False  # stamped but no real input recorded → unattended
        return (current - last) <= idle_s
    # No pane id → machine-global fallback.
    last = _presence_epoch(state.user_presence_path(home))
    if last is None:
        return None  # no breadcrumb at all → cannot tell (headless box, fresh HOME, …)
    if last <= 0:
        return False  # breadcrumb exists but no user input was EVER recorded → unattended
    return (current - last) <= idle_s


def typing_now(
    *,
    idle_s: int = USER_PRESENT_IDLE_S,
    home: Path | None = None,
    now: int | None = None,
    env: Mapping[str, str] | None = None,
) -> bool | None:
    """The INJECTION-GATE typing signal (TRDD-D2DD5GO8): True = typed within `idle_s`,
    False = provably not typing, None = the typing signal is BLINDED — do not trust a
    'not typing' answer built without it.

    Why `user_presence` alone was not enough (the 2026-08-19 incident, measured): under
    host load `ioreg` hangs past its 3 s timeout, so `hid_idle_seconds()` — the ONLY rung
    that moves on every keystroke — returns None, and the ladder falls through to the
    presence breadcrumb, which is stamped only at prompt SUBMIT. A user mid-sentence has a
    STALE breadcrumb by construction, so the ladder returned a confident-looking False and
    the injector typed over their fingers. The failure was never surfaced as 'unknown';
    it was laundered into 'not typing'. This function un-launders it:

      * hid readable  → hid alone answers BOTH ways (`hid <= idle_s`) — it is machine-wide
        and moves on every keystroke, so it can prove 'not typing' where breadcrumbs cannot.
      * hid blinded ON DARWIN (the signal exists but could not be read) → a fresh breadcrumb
        may still prove True (a submit IS typing); anything else is None — the breadcrumb's
        absence/staleness is NOT evidence of an idle keyboard.
      * non-darwin (no HID signal exists at all) → the breadcrumb ladder collapsed to a
        bool exactly as before — returning None here would make sustained-blind deferral
        permanent on every headless Linux runner, resurrecting the 22-minute CI hang class
        (31844013197) as a permanent give-up instead of a spin.
    """
    hid = hid_idle_seconds()
    if hid is not None:
        return hid <= idle_s
    presence = user_presence(idle_s=idle_s, home=home, now=now, env=env)
    if sys.platform == "darwin":
        return True if presence is True else None
    return presence is True


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

    THE INJECTOR WRAPPER over `user_presence` (the tri-state SSOT above): unknown maps to
    PRESENT here — `is not False` — because every caller of THIS function is deciding whether
    it may type into a pane, and an unknown must never authorize that. Consumers whose safe
    side is the opposite (the push gate, the typing probes) call `user_presence` directly.
    """
    return user_presence(idle_s=idle_s, home=home, now=now, env=env) is not False


def _resolve_idle_s(env: Mapping[str, str] | None) -> int:
    """The presence window in seconds — the 10-second default, overridable via env.

    ``CLAUDE_PLUGIN_OPTION_SELF_TRIGGER_PRESENCE_IDLE_S`` tunes it; a non-int or a value ≤0
    coerces back to the default, so the gate can never be silently disabled to a 0-second
    window (which would let a self-trigger clobber a human who submitted a moment ago)."""
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

    Presence is per-pane and the window is 10 s (owner directive 2026-07-17); see
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


def resolve_interrupt_cooldown_s(env: Mapping[str, str] | None = None) -> int:
    """The interrupt-cooldown window in seconds — overridable via `INTERRUPT_COOLDOWN_ENV`.

    Public (unlike `_resolve_idle_s`) because `terminal_trigger` needs the SAME number it fed to
    `recently_interrupted` to log a meaningful cooldown value, not just "deferred, window unknown".
    A non-int or a value <=0 coerces back to the default, same defend-the-floor shape as
    `_resolve_idle_s`."""
    e = os.environ if env is None else env
    raw = e.get(INTERRUPT_COOLDOWN_ENV)
    if raw is None:
        return DEFAULT_INTERRUPT_COOLDOWN_S
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_INTERRUPT_COOLDOWN_S
    return val if val > 0 else DEFAULT_INTERRUPT_COOLDOWN_S


def _tail_bytes(path: Path, max_bytes: int = 64 * 1024) -> list[str]:
    """The last `max_bytes` of `path` as non-blank text lines. Empty list on any I/O failure.

    A near-duplicate of `fleet_scan._tail_lines` — NOT imported from there because `fleet_scan`
    imports `terminal_trigger`, which imports THIS module: importing `fleet_scan` here would be a
    straight import cycle (fleet_scan -> terminal_trigger -> user_intent -> fleet_scan). Small,
    stable, and cheap enough to duplicate rather than restructure three modules to share it."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            data = fh.read(max_bytes + 1)
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if len(lines) > 1 and size > max_bytes:
        lines = lines[1:]  # first line is almost certainly truncated mid-record
    return [ln for ln in lines if ln.strip()]


def _interrupt_text(rec: Mapping) -> str | None:
    """The flattened text of a `type: user` transcript record's `message.content`, or None.

    `content` is either a bare string or a list of `{"type": "text", "text": ...}` blocks —
    verified against real `~/.claude/projects/*/*.jsonl` transcripts before writing this."""
    if rec.get("type") != "user":
        return None
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, Mapping) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text") for b in content if isinstance(b, Mapping) and isinstance(b.get("text"), str)]
        return "\n".join(p for p in parts if p) or None
    return None



# Consecutive same-type (user/assistant) records the backward scan must see OLDER than the
# cooldown window before it stops widening -- NOT the first old timestamp it meets. An
# attachment/task-notification record can carry a timestamp OLDER than its true position in the
# file (owner finding 2026-09-15): stopping on the very first old `ts` let one such out-of-order
# record hide a real, in-window interrupt sitting just behind it. Only `user`/`assistant` role
# records count toward the streak; other types are skipped without affecting it.
_OLD_STREAK_LIMIT = 3

# How close (seconds) a `type: user` transcript record's text must land to this session's OWN
# `terminal_trigger` self-send stamp for the SAME command text to be treated as an echo of our
# own injection rather than the human typing (owner finding 2026-09-15: an injected
# `/janitor-resume` looked exactly like "the user is back" and ended the cooldown for every other
# injector). 30s, not 10s: the stamp is written at SEND time but the transcript record lands at
# SUBMIT time, and a verified-send retry (issue #306: 14:28:07 timeout, 14:28:15 landed -- 8s on
# the retry alone, before submit latency) can exceed a 10s window outright. Generous relative to
# typical injection + retry latency, tight enough that an unrelated earlier command a minute
# later is not mistaken for the same send.
_SELF_SENT_MATCH_WINDOW_S = 30.0
_SELF_SEND_STAMPS_GLOB = "self-send.*.stamps.json"


def _is_self_sent_echo(text: str, ts: int | None, state_dir: Path) -> bool:
    """True when `text` matches a command THIS session's own `terminal_trigger` verified-sender
    stamped within `_SELF_SENT_MATCH_WINDOW_S` of `ts` -- i.e. the record is an echo of our own
    injection landing in the transcript as a `type: user` record, not the human typing.

    Reads `terminal_trigger._stamp_self_sent`'s `self-send.<pane>.stamps.json` files (one per
    pane, `{command: epoch}`) -- globbed rather than a single fixed name because a project may
    have more than one live pane, each with its own stamp file. `ts is None` fails CLOSED (False,
    the pre-fix behaviour): with no timestamp there is no window to verify, and treating an
    unstamped/untimed record as an echo on a text-only coincidence would be the false-exclusion
    this window guards against."""
    if ts is None:
        return False
    for stamps_path in sorted(state_dir.glob(_SELF_SEND_STAMPS_GLOB)):
        try:
            data = json.loads(stamps_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        stamp = data.get(text)
        if isinstance(stamp, (int, float)) and abs(ts - stamp) <= _SELF_SENT_MATCH_WINDOW_S:
            return True
    return False


def recently_interrupted(
    project_dir: str | Path,
    window_s: int | None = None,
    now: float | None = None,
    *,
    transcript_path: str | Path | None = None,
    home: Path | None = None,
    state_dir: Path | None = None,
) -> float | None:
    """Seconds since the newest Esc/Ctrl-C interrupt in the SESSION-SCOPED transcript, or None
    when none happened within `window_s` (default `resolve_interrupt_cooldown_s()`), the
    session is unknown, or a NEWER ordinary user prompt shows the user is already back.

    `transcript_path` MUST be the caller's own session (a hook's `transcript_path`, or
    `JANITOR_TRANSCRIPT_PATH` threaded through by `terminal_trigger`) -- there is deliberately
    NO fallback to "the newest transcript under this project's slug": two live sessions of the
    same project must never share a cooldown just because one of them typed more recently and
    so owns the newer file. When no session is known, this SKIPS the cooldown (logged) rather
    than guess at one -- a caller with no session identity has no interrupt to defer for.

    The scan walks the transcript BACKWARDS in growing 64 KB windows, bounded by TIME (not a
    fixed byte cap): it keeps widening the window until it finds the interrupt marker, finds an
    ordinary user prompt newer than any interrupt (the user is back -- see below), or sees
    `_OLD_STREAK_LIMIT` CONSECUTIVE `user`/`assistant`-role records older than `now - window_s`
    (everything of that role before them is older still). A single fixed-size tail read would
    let one large tool-result line written just after the Esc push the marker out of the window
    entirely; stopping on the FIRST old timestamp (rather than a streak) would let one
    out-of-order attachment/task-notification record -- these can carry a timestamp earlier than
    their real position in the file -- hide a real, in-window interrupt sitting just behind it.
    Only `user`/`assistant` records count toward that streak; every other type is skipped
    without affecting it.

    A newer plain user-role text block that is NOT the exact interrupt marker means the user
    resumed typing after the interrupt, so the cooldown ends immediately (returns None) --
    this is an EXACT match against the marker text (never a prefix): a compaction summary that
    merely quotes the phrase must not be mistaken for a live interrupt. EXCEPT when that text is
    itself an ECHO of a command THIS session self-sent (`_is_self_sent_echo`, via
    `terminal_trigger`'s stamp files): an injected `/janitor-resume` lands in the transcript as
    an ordinary `type: user` record, and without this check it would look exactly like "the user
    is back" and end the cooldown for every other queued injector (owner finding 2026-09-15).
    Such a record is skipped -- neither an interrupt nor proof of the user's return -- and the
    backward scan continues.

    Fails OPEN (returns None) on any unreadable/missing transcript or unparseable content --
    this is the CALLER's decision to make (defer or not), never a hard error over a breadcrumb.
    """
    resolved_window = resolve_interrupt_cooldown_s() if window_s is None else window_s
    resolved_now = time.time() if now is None else now
    sd = state.state_dir() if state_dir is None else state_dir
    _ = home  # kept for signature compatibility with existing callers/tests; no longer used

    if transcript_path is None:
        state.log_line("user_intent", "recently_interrupted: interrupt cooldown skipped: session unknown")
        return None

    transcript = Path(transcript_path)
    if not transcript.is_file():
        state.log_line("user_intent", f"recently_interrupted: session-scoped transcript_path not found: {transcript}")
        return None

    try:
        size = transcript.stat().st_size
    except OSError:
        state.log_line("user_intent", f"recently_interrupted: unreadable transcript: {transcript}")
        return None

    deadline_ts = resolved_now - resolved_window
    window_bytes = min(_INTERRUPT_SCAN_CHUNK_BYTES, size) if size else 0
    while True:
        lines = _tail_bytes(transcript, window_bytes) if window_bytes else []
        if not lines:
            state.log_line("user_intent", f"recently_interrupted: unreadable transcript: {transcript}")
            return None
        # Re-scan the WHOLE window every growth step, not just the newly-revealed prefix:
        # `_tail_bytes` decides whether to drop a guessed-truncated first line purely from
        # `size > max_bytes` on THIS call, so the exact line boundaries shift between windows
        # of different size -- a "just scan what's new" diff would silently trust that the tail
        # is byte-for-byte stable across windows, which it is not guaranteed to be. Re-scanning
        # is idempotent (same record, same verdict) and the window only grows a handful of
        # times before hitting the whole-file fallback, so the extra work is bounded and cheap;
        # a wrong verdict from a misaligned diff is not an acceptable trade for it.
        consecutive_old = 0  # reset each growth step: this re-scans the window from its own tail
        for raw in reversed(lines):
            try:
                rec = json.loads(raw)
            except ValueError:
                continue  # malformed line -- keep walking back for an earlier valid record
            if not isinstance(rec, dict):
                continue
            ts = token_history.parse_ts(rec.get("timestamp", ""))
            text = _interrupt_text(rec)
            if text is not None:
                stripped = text.strip()
                if stripped in INTERRUPT_MARKERS:
                    if ts is None:
                        try:
                            ts = int(transcript.stat().st_mtime)
                        except OSError:
                            continue
                    age = max(0.0, resolved_now - ts)
                    if age <= resolved_window:
                        state.log_line(
                            "user_intent",
                            f"recently_interrupted: hit ({transcript}), age={age:.0f}s",
                        )
                        return age
                    return None  # newest interrupt already outside the window
                if _is_self_sent_echo(stripped, ts, sd):
                    # Our own injected command echoed back as a `type: user` record -- not
                    # evidence the user is back, and not an interrupt. Keep scanning backward.
                    continue
                if stripped.startswith(_HEARTBEAT_MARKER):
                    # TRDD-ECHOKVZC review finding: the cron heartbeat's own prompt
                    # (`[janitor-heartbeat] ...`, `token_meter._HEARTBEAT_MARKER`) lands in the
                    # transcript as an ordinary `type: user` record, but NO human typed it and
                    # `terminal_trigger` never stamps a self-send for it (it is not sent through
                    # that path at all). Without this skip it hit the "user is back" branch
                    # below and ended the cooldown for EVERY injector within one cron cadence
                    # (as little as a few minutes) of a real Esc -- blast radius: every caller
                    # of `recently_interrupted`, not just `pane_actuate.act`. Neither an
                    # interrupt nor proof of return: keep scanning backward.
                    continue
                # A newer, non-interrupt, non-self-sent, non-heartbeat user prompt found before
                # any interrupt: the user is back -- the cooldown is over regardless of any
                # earlier interrupt.
                return None
            role = rec.get("type")
            if role in ("user", "assistant") and ts is not None:
                if ts < deadline_ts:
                    consecutive_old += 1
                    if consecutive_old >= _OLD_STREAK_LIMIT:
                        # Everything of this role before this streak is older still -- nothing
                        # left worth reading further back.
                        return None
                    continue
                consecutive_old = 0  # an in-window role record breaks the old-streak
        if window_bytes >= size:
            return None
        window_bytes = min(window_bytes * 2, size)

# --- TARGET-session pane -> transcript mapping (TRDD-ECHOKVZC) -----------------------------
#
# `pane_actuate.act` types into OTHER sessions' panes and has no transcript of its own, so it
# can never call `recently_interrupted` -- the wedge-recovery ESC bypasses the 300s
# user-interrupt cooldown every other injector honours. The TARGET session is the only one
# that knows its own `transcript_path`; it publishes the mapping here (from its own hooks) and
# the actuator reads it back by pane, keyed the same way `terminal_trigger`'s self-send stamps
# already are (pane, not project -- two panes must never share a file).

_PANE_KEY_TMUX_RE = re.compile(r"^%[0-9]+$")
_PANE_KEY_ITERM_RE = re.compile(r"[0-9a-fA-F-]{8,64}")


def _pane_key(env: Mapping[str, str] | None = None) -> str | None:
    """THIS session's own pane identity, in the filename-safe form `record_pane_transcript`
    files under. Mirrors `terminal_trigger.self_terminal()`'s env-derivation exactly (bare
    `TMUX_PANE`, else `ITERM_SESSION_ID`'s trailing UUID) -- duplicated rather than imported
    because `terminal_trigger` already imports THIS module, so importing it back would be
    circular. Validated with the same shape `terminal_trigger` enforces so a malformed env
    value can never become a filename component."""
    e: Mapping[str, str] = os.environ if env is None else env
    pane = (e.get("TMUX_PANE") or "").strip()
    if _PANE_KEY_TMUX_RE.match(pane):
        return pane
    sid = (e.get("ITERM_SESSION_ID") or "").strip().split(":")[-1].strip()
    if _PANE_KEY_ITERM_RE.fullmatch(sid):
        return sid
    return None


def record_pane_transcript(
    transcript_path: str | Path | None,
    *,
    state_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    """Publish THIS session's pane -> transcript mapping so `pane_transcript_path` (below) can
    find it later. Writes `<state_dir>/pane-transcript.<pane>.txt` = the absolute transcript
    path, one line -- ONLY when the file is missing or its content differs (the state dir is
    fsevents-watched; a same-content rewrite on every prompt/turn is pure churn, see memory
    page janitor-keepalive-test-isolation-fsevents).

    Writes nothing (returns None) when this session has no pane identity in `env`, or
    `transcript_path` is empty/None -- a headless/unknown terminal has no pane key to file
    under. A write fault is caught and logged, never raised: callers are hooks, and a mapping
    write must never break the turn it rides in on.

    The DEFAULT `state_dir` routes through `target_state_dir(os.path.realpath(...))` -- the
    SAME helper and the SAME realpath normalisation the READ side gets for free from
    `fleet_scan.find_janitor_root` (`os.path.realpath(cwd)` before its `.janitor` walk,
    `fleet_scan.py:633`). `state.state_dir()` on its own does NOT canonicalize
    (`_resolve_project_root` is a bare `Path($CLAUDE_PROJECT_DIR)`, `state.py`), so without this
    the writer and reader could resolve to two different-looking (but same-content) directories
    for a project reached through a symlink -- coordinator review finding, TRDD-ECHOKVZC; see
    `tests/test_user_intent_interrupt.py`'s writer/reader parity tests."""
    pane = _pane_key(env)
    if not pane or not transcript_path:
        return None
    sd = target_state_dir(os.path.realpath(str(state.project_root()))) if state_dir is None else state_dir
    target = sd / f"pane-transcript.{pane}.txt"
    content = os.path.realpath(str(transcript_path))
    try:
        if target.is_file() and target.read_text(encoding="utf-8").strip() == content:
            return target
        state.atomic_write(target, content + "\n")
    except OSError as exc:
        state.log_line("user_intent", f"record_pane_transcript: write failed ({target}): {exc}")
        return None
    return target


def target_state_dir(project_dir: str | Path) -> Path:
    """`<project_dir>/.janitor/state` -- the TARGET project's own state dir, as opposed to
    `state.state_dir()` (this PROCESS's own project, e.g. the daemon's). `pane_transcript_path`
    (below) uses this to find the mapping file; `pane_actuate.act` MUST pass the same value as
    `recently_interrupted`'s `state_dir=` (coordinator review finding, TRDD-ECHOKVZC): without
    it, `recently_interrupted` defaults to the CALLING process's `state.state_dir()`, so
    `_is_self_sent_echo` globs `self-send.*.stamps.json` in the daemon's own project instead of
    the target's -- an injected `/janitor-resume` in the target pane is then invisible to the
    self-sent-echo check and misread as "the user is back," ending the cooldown early. One
    function, used by both call sites, so they cannot drift apart again.

    Does NOT itself `.resolve()`/canonicalize `project_dir` -- it trusts the CALLER to hand it
    an already-canonical path, and both real callers do: `pane_transcript_path` (below) is fed
    `fleet_scan.find_janitor_root`'s result, which already ran `os.path.realpath(cwd)`
    (`fleet_scan.py:633`) before its `.janitor` walk; `record_pane_transcript`'s own default
    (above) wraps `state.project_root()` in `os.path.realpath(...)` before calling this, for
    the SAME reason -- `state.state_dir()` on its own does NOT canonicalize
    (`_resolve_project_root`, `state.py`, is a bare `Path($CLAUDE_PROJECT_DIR)`), and second
    review finding (TRDD-ECHOKVZC) confirmed that asymmetry (canonicalized reader, raw writer)
    is a REAL divergence for a project reached through a symlink, not just a theoretical one --
    see `tests/test_user_intent_interrupt.py`'s writer/reader parity tests, plain and
    symlinked."""
    return Path(project_dir) / ".janitor" / "state"


def pane_transcript_path(project_dir: str | Path | None, terminal: Mapping[str, str]) -> Path | None:
    """The transcript path `record_pane_transcript` filed for THIS pane, or None.

    `terminal` is the dict `pane_actuate.act`/`fleet_scan.Instance.terminal` already carries
    (`tmux_pane` / `iterm_session_id` keys -- fleet_scan.py:76-109), not the `pane`/`session_id`
    keys `terminal_trigger.self_terminal()` returns for the CURRENT session: the two describe
    the same identity under different key names because fleet_scan discovers OTHER sessions'
    panes rather than reading its own env. `iterm_session_id` is normalised the same way
    fleet_scan's OWN consumer already does (`.split(":")[-1]`, fleet_scan.py:1037) -- verified:
    the AppleScript `(id of s)` fleet_scan reads it from carries a `w0t0p0:`-style window/tab/
    pane prefix that `ITERM_SESSION_ID` (and so `record_pane_transcript`'s bare-UUID filename)
    never does, so both sides must normalise or a live pane's mapping is never found.

    Fails OPEN (None, logged) on no pane key, no `project_dir`, or a dangling/missing/unreadable
    mapping file -- a caller with no known target transcript has nothing to defer for."""
    if not project_dir:
        return None
    pane = (terminal.get("tmux_pane") or "").strip()
    if not pane:
        pane = (terminal.get("iterm_session_id") or "").strip().split(":")[-1].strip()
    if not pane:
        return None
    mapping = target_state_dir(project_dir) / f"pane-transcript.{pane}.txt"
    try:
        content = mapping.read_text(encoding="utf-8").strip()
    except OSError:
        state.log_line("user_intent", f"pane_transcript_path: no mapping for pane {pane!r}")
        return None
    if not content:
        # An empty file is the ONE case worth its own trace: unlike a missing mapping (routine,
        # never written yet) or a dangling one (routine, pane reused), an EMPTY file means
        # `record_pane_transcript`'s write landed truncated -- `atomic_write`'s rename should
        # make that impossible, so seeing it here is a signal something upstream is wrong.
        state.log_line("user_intent", f"pane_transcript_path: empty mapping for pane {pane!r} ({mapping})")
        return None
    transcript = Path(content)
    if not transcript.is_file():
        state.log_line("user_intent", f"pane_transcript_path: mapping names missing file: {transcript}")
        return None
    return transcript
