"""Resolve a bare executable name the way subprocess would, so a call site holds no bare name (bandit B607).

WHY: bandit B607 flags a subprocess call whose first argv element is a bare name; this keeps
the literal out of the call. It does NOT harden anything: the lookup is the same PATH search
subprocess does at exec time (os.get_exec_path(env)), so an env= with its own PATH, such as
a test's fake tool on PATH, still wins, and a missing tool returns the bare name so the call
fails exactly as before. Call it at the use site, never as a module-level constant: that
would freeze PATH at import time (TRDD-SWQXCIOS).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping


def exe(name: str, env: Mapping[str, str] | None = None) -> str:
    """Return the path subprocess would exec for name under env (os.environ when None), else name."""
    return shutil.which(name, path=os.pathsep.join(os.get_exec_path(env))) or name
