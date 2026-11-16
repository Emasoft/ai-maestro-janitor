"""The names safe-delete gives what it moves into <project>/.trashcan/: one batch folder per run, named by the
disposal moment (YYYYMMDD_HHMMSS+HHMM or -HHMM), and a sibling "<batch>.txt" manifest. Shared by trashcan-purge
(age of a batch) and env_secrets (which batches are scanned by name). Anything not shaped like this (.gitkeep,
README.txt, migrate-memory-scope/, a human-added file) is not a batch and is never treated as one.
"""
from __future__ import annotations

import re
from datetime import datetime

# Either `+HHMM` or `-HHMM` offset. Manifest variants carry a trailing `.txt`.
TS_FOLDER_RE = re.compile(r"^(\d{8}_\d{6}[+-]\d{4})$")
TS_MANIFEST_RE = re.compile(r"^(\d{8}_\d{6}[+-]\d{4})\.txt$")


def parse_ts_to_epoch(ts: str) -> int | None:
    """Parse YYYYMMDD_HHMMSS±HHMM into epoch seconds. None on parse failure."""
    try:
        # `%z` accepts ±HHMM since Python 3.7.
        dt = datetime.strptime(ts, "%Y%m%d_%H%M%S%z")
    except ValueError:
        return None
    return int(dt.timestamp())


def batch_epoch(name: str) -> int | None:
    """The disposal moment of a batch FOLDER name, or None when `name` is not a batch (wrong shape, or a shape that is
    not a real date). One predicate for "is this a batch", so the sweep roots and the trash tier never disagree."""
    match = TS_FOLDER_RE.match(name)
    return parse_ts_to_epoch(match.group(1)) if match else None
