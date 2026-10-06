from __future__ import annotations

import os

import conftest
import state  # type: ignore[import-not-found]


def test_conftest_pane_env_names_match_state() -> None:
    """The conftest autouse delenv list equals state._PANE_ID_ENV_VARS (no drift)."""
    assert conftest._PANE_ID_ENV_NAMES == tuple(v for _, v in state._PANE_ID_ENV_VARS)


def test_host_pane_env_is_cleared_for_every_test() -> None:
    """No terminal pane-id env var survives into a test body."""
    assert not [n for n in conftest._PANE_ID_ENV_NAMES if n in os.environ]
