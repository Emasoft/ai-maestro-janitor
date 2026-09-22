"""Put ``scripts/lib`` on sys.path so the vendored ``jevctx`` package (which the upstream
tests under this directory import as a bare top-level package) resolves — the same
`sys.path.insert(0, scripts/lib)` convention every other test file in this suite uses
(see tests/test_cold_cache_compact.py). Not part of the vendored files: this is project
test infrastructure, added so the upstream test files can stay byte-identical."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_LIB = _ROOT / "scripts" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
