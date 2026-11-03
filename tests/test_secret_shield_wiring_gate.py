"""hooks/hooks.json may load the secret-shield mod (a "modules" key) only after TRDD-0Y3UW1NF
and TRDD-TEP6F3A3 shipped (TRDD-2V7OAUPE, TRDD-M1218EMH).

TRDD-2V7OAUPE is the card that wires the mod, and it is `blocked-by: [0Y3UW1NF, TEP6F3A3]`.
trdd-drift releases it only when each blocker's column is terminal AND done. This guard refuses
the expected edit (a "modules" key in hooks/hooks.json, the only hooks file the plugin loads while
plugin.json declares none) until each blocker has shipped; it cannot stop someone editing this test.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "lib"))

import trdd_common  # noqa: E402

HOOKS_JSON = _REPO / "hooks" / "hooks.json"
PLUGIN_JSON = _REPO / ".claude-plugin" / "plugin.json"

BLOCKERS = ("0Y3UW1NF", "TEP6F3A3")
WIRING_CARD = "2V7OAUPE"  # the card whose blocked-by the gate also reads

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


def wiring_refusal(hooks: dict[str, Any], columns: dict[str, str], blockers: Iterable[str]) -> str | None:
    """Why `hooks` may not load the secret-shield mod yet, or None when it may."""
    if "modules" not in hooks:
        return None
    # A blocker id absent from the board reads as column "": never assume a card shipped.
    pending = [f"TRDD-{uid} (column {columns.get(uid, '')!r})" for uid in blockers if not _releases(columns.get(uid, ""))]
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


def _card_blockers(root: Path) -> tuple[str, ...]:
    """The ids in TRDD-2V7OAUPE's frontmatter `blocked-by:`, or () when that field is absent or empty."""
    for folder in trdd_common.DESIGN_FOLDERS:
        for _scope, card in trdd_common.trdd_files(folder, str(root)):
            if trdd_common.extract_uid(card.name) != WIRING_CARD:
                continue
            # The same head read as parse_trdd_state, and the same blocked_by_ids trdd-drift's
            # hold uses: it keeps TRDD-shaped ids only, so a non-card blocker is not checked here.
            with card.open("r", encoding="utf-8", errors="replace") as f:
                head = f.read(trdd_common.HEAD_BYTES)
            fm = trdd_common.FRONTMATTER_RE.match(head)
            if fm is None:
                pytest.fail(f"TRDD-{WIRING_CARD} has no frontmatter block, so the gate cannot read its blocked-by")
            bm = trdd_common.FM_BLOCKED_BY_RE.search(fm.group(1))
            return tuple(trdd_common.blocked_by_ids(bm.group(1))) if bm else ()
    # Fail rather than return (): a renamed or deleted card would silently shrink the gate to BLOCKERS.
    pytest.fail(f"TRDD-{WIRING_CARD} is not on the board (renamed or deleted), so the gate cannot read its blocked-by")


def _gate_blockers(card_blockers: Iterable[str]) -> list[str]:
    """Every id the gate checks: BLOCKERS plus the ids TRDD-2V7OAUPE's blocked-by lists."""
    # Both lists count: BLOCKERS alone misses a blocker added to the card, and blocked-by alone lets the wiring through once someone empties it by hand.
    return sorted(set(BLOCKERS) | set(card_blockers))


def _other(blocker: str) -> str:
    return next(uid for uid in BLOCKERS if uid != blocker)


# trdd_common.trdd_files resolves the LOCAL design root through _main_checkout_root, which runs
# `git worktree list --porcelain`: read-only, but the sandbox classes the `worktree` verb as
# mutating. The test itself spawns nothing. Every real-board test carries the marker because
# _main_checkout_root is lru_cached: an unmarked one would pass only after a marked one ran.
@pytest.mark.real_subprocess("git")
def test_real_hooks_json_respects_the_wiring_gate() -> None:
    """The shipped hooks.json loads the mod only if every blocker of TRDD-2V7OAUPE has shipped."""
    hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    blockers = _gate_blockers(_card_blockers(_REPO))
    refusal = wiring_refusal(hooks, _repo_columns(_REPO), blockers)
    assert refusal is None, refusal


@pytest.mark.real_subprocess("git")  # same LOCAL-root git probe as the test above
def test_both_blocker_cards_exist() -> None:
    """Both blocker cards are on the board, so a refusal never points at a card nobody can find."""
    columns = _repo_columns(_REPO)
    missing = [uid for uid in BLOCKERS if uid not in columns]
    assert missing == [], f"blocker card(s) renamed or deleted: {missing} — the wiring gate would refuse forever without explanation"


@pytest.mark.real_subprocess("git")  # same LOCAL-root git probe as the tests above
def test_card_lists_the_gate_blockers_while_blocked() -> None:
    """While TRDD-2V7OAUPE is blocked, its blocked-by names every id in BLOCKERS, so the two lists cannot drift apart."""
    columns = _repo_columns(_REPO)
    if columns.get(WIRING_CARD) != "blocked":
        pytest.skip(f"TRDD-{WIRING_CARD} left blocked (column {columns.get(WIRING_CARD, '')!r}); drift's release empties blocked-by, so only BLOCKERS still applies")
    card_blockers = set(_card_blockers(_REPO))
    assert set(BLOCKERS) <= card_blockers, f"TRDD-{WIRING_CARD} is blocked but its blocked-by lacks {sorted(set(BLOCKERS) - card_blockers)}: add them to the card or drop them from BLOCKERS so the two lists agree"


@pytest.mark.parametrize("blocker", BLOCKERS)
@pytest.mark.parametrize("column", [*_NEVER_SHIPPED, None], ids=[*_NEVER_SHIPPED, "missing"])
def test_gate_refuses_modules_until_both_blockers_ship(blocker: str, column: str | None) -> None:
    """A blocker that has not shipped keeps the mod unwired, and the refusal names that blocker."""
    columns = {_other(blocker): "complete"}
    if column is not None:  # None = the blocker's card is not on the board at all
        columns[blocker] = column
    refusal = wiring_refusal({"hooks": {}, "modules": {}}, columns, BLOCKERS)
    assert refusal is not None
    assert f"TRDD-{blocker}" in refusal
    assert f"TRDD-{_other(blocker)}" not in refusal


@pytest.mark.parametrize("column", _SHIPPED)
def test_gate_allows_modules_once_both_ship(column: str) -> None:
    """Once both blockers sit in a shipped column, hooks.json may load the mod."""
    assert wiring_refusal({"hooks": {}, "modules": {}}, dict.fromkeys(BLOCKERS, column), BLOCKERS) is None


def test_gate_ignores_hooks_json_without_modules() -> None:
    """A hooks.json with no "modules" key loads no mod, so the blockers' columns do not matter."""
    assert wiring_refusal({"hooks": {}}, dict.fromkeys(BLOCKERS, "design"), BLOCKERS) is None


def test_gate_refuses_a_blocker_only_the_card_lists() -> None:
    """A blocker named only in the card's blocked-by keeps the mod unwired even with both BLOCKERS shipped."""
    columns = {**dict.fromkeys(BLOCKERS, "complete"), "ZZZZZZZZ": "design"}
    refusal = wiring_refusal({"hooks": {}, "modules": {}}, columns, _gate_blockers(("ZZZZZZZZ",)))
    assert refusal is not None
    assert "TRDD-ZZZZZZZZ" in refusal
    assert not any(f"TRDD-{uid}" in refusal for uid in BLOCKERS)


def test_gate_keeps_blockers_when_the_card_lists_none() -> None:
    """An emptied blocked-by does not open the gate, because BLOCKERS still counts."""
    refusal = wiring_refusal({"hooks": {}, "modules": {}}, {}, _gate_blockers(()))
    assert refusal is not None
    assert all(f"TRDD-{uid}" in refusal for uid in BLOCKERS)


def test_plugin_json_declares_no_other_hooks_file() -> None:
    """plugin.json declares no hooks of its own, so hooks/hooks.json is the only hooks file to guard."""
    manifest = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    assert "hooks" not in manifest, "plugin.json now declares its own hooks, which could load the mod from a file this gate does not read; extend the gate to that file"
