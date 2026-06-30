# Marker file. Makes scripts/lib/ an importable Python package so hooks
# can do `from lib import state` after sys.path is extended with
# scripts/. This shape lets validate_hook.py recognise `lib` as a
# local-sibling package (it scans scripts/ for direct .py children and
# subdirs that contain __init__.py) rather than treating `state` /
# `git_utils` as third-party imports needing PEP 723 declarations.
#
# We also re-export the lib modules as submodule attributes so static
# type checkers (mypy/pyright) resolve `from lib import state` cleanly.
# Without these explicit submodule imports, mypy emits
# `[attr-defined] Module "lib" has no attribute "state"` because it
# does not auto-discover submodules of an empty package.

__all__ = ["leanctx_allowlist", "rules_installer", "state"]
from . import (
    leanctx_allowlist,
    rules_installer,
    state,
)
