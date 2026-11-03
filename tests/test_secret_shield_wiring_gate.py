"""hooks/hooks.json may load the secret-shield mod (a "modules" key) only after TRDD-0Y3UW1NF
and TRDD-TEP6F3A3 shipped (TRDD-2V7OAUPE, TRDD-M1218EMH).

TRDD-2V7OAUPE is the card that wires the mod, and it is `blocked-by: [0Y3UW1NF, TEP6F3A3]`.
trdd-drift releases it only when each blocker's column is terminal AND done. This guard applies
the same condition to the file the wiring edits, so the mod cannot be switched on before both
blockers ship, whatever column TRDD-2V7OAUPE itself is in.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "lib"))

import trdd_common  # noqa: E402

HOOKS_JSON = _REPO / "hooks" / "hooks.json"

BLOCKERS = ("0Y3UW1NF", "TEP6F3A3")

# Columns a blocker can sit in without having shipped: each one must keep the mod unwired.
# "completed" is left out of this list and of _SHIPPED below: it is done but not terminal
# today, so trdd-drift never releases a card on it — see TRDD-OEEH2W28.
_NEVER_SHIPPED = ["design", "dev", "blocked", "failed", "cancelled", "superseded", "refused"]
_SHIPPED = ["complete", "published", "live"]


def _releases(column: str) -> bool:
    """True iff a blocker in `column` lets TRDD-2V7OAUPE wire the mod."""
    # The same condition trdd-drift's `_try_unblock` applies to TRDD-2V7OAUPE: its
    # `unblock-when: trdd:<id> terminal` predicates need the terminal set, and its
    # `blocked-by:` hold needs the done set. Calling the shared predicates instead of copying
    # the sets makes this gate follow any change to either one (TRDD-OEEH2W28).
    return trdd_common.is_terminal_column(column) and trdd_common.is_done_column(column)


def wiring_refusal(hooks: dict[str, Any], columns: dict[str, str]) -> str | None:
    """Why `hooks` may not load the secret-shield mod yet, or None when it may."""
    if "modules" not in hooks:
        return None
    # A blocker id absent from the board reads as column "": never assume a card shipped.
    pending = [f"TRDD-{uid} (column {columns.get(uid, '')!r})" for uid in BLOCKERS if not _releases(columns.get(uid, ""))]
    if not pending:
        return None
    return f"hooks/hooks.json has a 'modules' key, which loads the secret-shield mod, but these blockers of TRDD-2V7OAUPE have not shipped (each needs a column that is both terminal and done): {', '.join(pending)}"


def _repo_columns(root: Path) -> dict[str, str]:
    """uid -> column over every design folder, built exactly as trdd-drift's Pass 1 builds it."""
    column_by_uid: dict[str, str] = {}
    for folder in trdd_common.DESIGN_FOLDERS:
        for _scope, card in trdd_common.trdd_files(folder, str(root)):
            uid = trdd_common.extract_uid(card.name)
            if uid is not None and uid not in column_by_uid:
                _, column = trdd_common.parse_trdd_state(card)
                column_by_uid[uid] = column
    return column_by_uid


def _other(blocker: str) -> str:
    return next(uid for uid in BLOCKERS if uid != blocker)


# trdd_common.trdd_files resolves the LOCAL design root through _main_checkout_root, which runs
# `git worktree list --porcelain`: read-only, but the sandbox classes the `worktree` verb as
# mutating. The test itself spawns nothing. Both real-board tests carry the marker because
# _main_checkout_root is lru_cached: an unmarked one would pass only after a marked one ran.
@pytest.mark.real_subprocess("git")
def test_real_hooks_json_respects_the_wiring_gate() -> None:
    """The shipped hooks.json loads the mod only if both blockers have shipped."""
    hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    refusal = wiring_refusal(hooks, _repo_columns(_REPO))
    assert refusal is None, refusal


@pytest.mark.real_subprocess("git")  # same LOCAL-root git probe as the test above
def test_both_blocker_cards_exist() -> None:
    """Both blocker cards are on the board, so a refusal never points at a card nobody can find."""
    columns = _repo_columns(_REPO)
    missing = [uid for uid in BLOCKERS if uid not in columns]
    assert missing == [], f"blocker card(s) renamed or deleted: {missing} — the wiring gate would refuse forever without explanation"


@pytest.mark.parametrize("blocker", BLOCKERS)
@pytest.mark.parametrize("column", [*_NEVER_SHIPPED, None], ids=[*_NEVER_SHIPPED, "missing"])
def test_gate_refuses_modules_until_both_blockers_ship(blocker: str, column: str | None) -> None:
    """A blocker that has not shipped keeps the mod unwired, and the refusal names that blocker."""
    columns = {_other(blocker): "complete"}
    if column is not None:  # None = the blocker's card is not on the board at all
        columns[blocker] = column
    refusal = wiring_refusal({"hooks": {}, "modules": {}}, columns)
    assert refusal is not None
    assert f"TRDD-{blocker}" in refusal
    assert f"TRDD-{_other(blocker)}" not in refusal


@pytest.mark.parametrize("column", _SHIPPED)
def test_gate_allows_modules_once_both_ship(column: str) -> None:
    """Once both blockers sit in a shipped column, hooks.json may load the mod."""
    assert wiring_refusal({"hooks": {}, "modules": {}}, dict.fromkeys(BLOCKERS, column)) is None


def test_gate_ignores_hooks_json_without_modules() -> None:
    """A hooks.json with no "modules" key loads no mod, so the blockers' columns do not matter."""
    assert wiring_refusal({"hooks": {}}, dict.fromkeys(BLOCKERS, "design")) is None
