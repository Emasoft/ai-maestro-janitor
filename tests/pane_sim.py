"""A simulated Claude Code composer behind a tmux pane, for tests of the keystroke path.

Only the TERMINAL is simulated (what `fleet_inject.fire` would type into, and what
`terminal_trigger.read_pane_text` would read back). Every plan the production code builds,
and every read it classifies through `pane_state`, is real: the sim consumes the plans
`fleet_inject` actually emits (tmux `send-keys` steps) and renders a frame the real parser
reads. Behaviour modelled is what was MEASURED on Claude Code 2.1.323 (TRDD-RJJGXPIK):

* ESC aborts a running turn and PUTS THE INTERRUPTED PROMPT BACK IN THE COMPOSER;
* Esc Esc on a NON-empty composer clears the draft (documented; it is rewind only when empty);
* literal text appends to whatever the composer already holds (`say hi` + `resume` -> `say hiresume`);
* Enter submits whatever the composer holds.
"""

from __future__ import annotations

_NBSP = " "




class Plans(list):
    """Every plan fired at a LivePane, in order. A plain list for the callers that only count
    or filter it, plus `.pane` so a test handed only this list can reach the composer."""

    def __init__(self, pane: "LivePane") -> None:
        super().__init__()
        self.pane = pane


def esc_plans(plans: list[dict]) -> list[dict]:
    """The plans that press Escape — the recovery rung itself, as opposed to the typed
    `resume` and Enter plans that follow it."""
    return [p for p in plans if any(s[-1] == "Escape" for s in p.get("steps", []) if s[0] == "RUN")]


class LivePane:
    """The composer state plus a log of every plan fired at it."""

    def __init__(self, *, restored_prompt: str | None = "say hi", stubborn: bool = False) -> None:
        self.field = ""
        self.restored_prompt = restored_prompt
        self.turn_running = restored_prompt is not None  # an abortable turn exists
        self.stubborn = stubborn  # True: Esc Esc does NOT clear (a draft that survives)
        self.plans = Plans(self)
        self.submitted: list[str] = []

    def fire(self, plan: dict | None) -> bool:
        if not plan:
            return False
        self.plans.append(plan)
        keys = [s[-1] for s in plan.get("steps", []) if s[0] == "RUN"]
        escapes = keys.count("Escape")
        if escapes and self.turn_running and self.restored_prompt is not None:
            self.turn_running = False
            self.field = self.restored_prompt  # the interrupted prompt comes back
            escapes -= 1
        if escapes >= 2 and self.field and not self.stubborn:
            self.field = ""
        for key in keys:
            if key == "Escape":
                continue
            if key == "Enter":
                if self.field:
                    self.submitted.append(self.field)
                    self.field = ""
            else:
                self.field += key  # a literal `send-keys -l` payload
        return True

    def read(self, _terminal: object) -> str:
        return "some earlier output\n" + "─" * 40 + f"\n❯{_NBSP}{self.field}\n" + "─" * 40 + "\n"

    def commands(self) -> list[str]:
        """The `command` of every plan fired, in order (ESC and Enter plans carry "")."""
        return [p["command"] for p in self.plans]
