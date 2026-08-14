"""Shared shrink-before-reload POLICY for the two reload triggers (TRDD-VHPYSN56).

`/reload-plugins` and `/reload-skills` are deliberate siblings whose own docstrings say to
"keep the two in step". They had already drifted once — the plugins path grew a context
guard and the skills path never got one — so the decision of WHETHER to shrink lives here,
in one place, rather than being copy-pasted into both and diverging again.

Only the POLICY lives here (pure predicates, the threshold, the context read). The chain
SPAWN stays in each trigger, because it needs `clear_trigger`, which lives in `scripts/`
and must not be imported from `scripts/lib/`.

WHY SHRINK AT ALL. These commands break the prompt-cache prefix, so the next turn re-caches
the WHOLE conversation at ~1.25x instead of reading it at ~0.1x. Clearing first makes that
break land on a near-floor context.

  - For `/reload-plugins` this is MEASURED and long-documented — see
    `token_meter.RELOAD_GUARD_DEFAULT_THRESHOLD` and the `claude-code-hook-types` wikimem
    note (`^no-plugin-reload-hook`).
  - For `/reload-skills` it is REASONED, NOT MEASURED (recorded 2026-08-14): a skill's
    description is injected into the system prompt, so reloading the skill set mutates the
    cached prefix by the same mechanism. The measurement that would settle it is one turn:
    note `cache_read`/`cache_write` on a warm heartbeat, run `/reload-skills`, and compare
    the next turn. Until someone runs it, treat the skills half as inference — which is why
    `auto` only ever clears sessions that are ALREADY above the threshold, bounding the cost
    of the inference being wrong to sessions where a reload is expensive anyway.
"""

from __future__ import annotations

import os

import state
import token_meter as tm

# Modes accepted by both triggers' `--shrink` flag.
SHRINK_MODES = ("auto", "never", "force")

# Seconds between the post-clear reload and the `/janitor-arm` that follows it. Neither
# reload command fires a hook, so completion is UNOBSERVABLE and nothing can gate on it. If
# `/janitor-arm` is dispatched into a mid-swap registry it can be rejected as an unknown
# command while the chain still reports OK — and since `/clear` destroyed the session-scoped
# cron, that leaves a session both cleared AND unwakeable. This pause shrinks the window; it
# does not close it.
RELOAD_SETTLE_S = 4.0


def shrink_threshold(env: dict[str, str] | None = None) -> int:
    """The context-token threshold above which a reload shrinks first.

    Reads the SAME env var and default as dispatch's reload guard, deliberately: the guard
    and this decision must agree, or dispatch defers a reload this would have handled
    cheaply (or the reverse) and the two disagree silently.
    """
    src = os.environ if env is None else env
    return state.coerce_int(
        src.get("CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD"),
        tm.RELOAD_GUARD_DEFAULT_THRESHOLD,
        detector_name="reload-shrink",
        var_name="CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD",
    )


def should_shrink(mode: str, *, context_tokens: int | None, threshold: int, hard: bool) -> bool:
    """PURE. True iff this reload should `/clear` first. Tested without a terminal.

    Three refusals, each deliberate and each failing toward the RECOVERABLE outcome — a
    reload that costs tokens is recoverable, a `/clear` that destroys an un-handed-off
    conversation is not:
      - `--hard` NEVER shrinks. Hard means urgent (a security fix, a marker whose new code
        must land now); a shrink adds a clear + re-arm + resume before the reload happens.
      - an UNREADABLE context (`None`) never shrinks in `auto`. We refuse to clear on a
        guess; the cost of being wrong is one expensive turn, versus a destroyed session.
      - below the threshold never shrinks: the reload is already cheap there, and clearing a
        320k session to reach the ~305k floor destroys the conversation to save nothing.
    `force` overrides the threshold (but still not `--hard`) so the path stays testable and
    a human can demand it.
    """
    if hard or mode == "never":
        return False
    if mode == "force":
        return True
    return context_tokens is not None and context_tokens >= threshold


def context_tokens() -> int | None:
    """Live context size, or None when it cannot be read (never raises).

    None is a REFUSAL to shrink in `auto` mode, not a zero — see `should_shrink`.
    """
    try:
        import cold_cache_compact  # noqa: PLC0415 -- lazy: fail-open when the lib is absent

        return cold_cache_compact.context_tokens_for(
            cold_cache_compact.newest_transcript(state.project_root())
        )
    except Exception as exc:  # noqa: BLE001 -- an unreadable context must never break the reload
        state.log_line("reload-shrink", f"context read failed, not shrinking: {exc}")
        return None


def resume_directive(what_reloaded: str) -> str:
    """The one-line pointer recorded for the post-clear auto-resume.

    Names WHAT was reloaded, so the resumed turn knows a reload happened during the clear
    and does not re-trigger one.
    """
    return (
        "read .janitor/state/agent-handoff.md FIRST (link-only handoff — follow its "
        "wikimem/TRDD links via memgrep recall on demand), then resume your prior "
        f"in-flight task. {what_reloaded} were reloaded during this clear."
    )
