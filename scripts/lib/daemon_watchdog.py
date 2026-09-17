# Shared daemon-task staleness constant.
#
# This module used to also hold `emit_if_daemon_stale`, the ONE staleness-watchdog
# implementation every per-session detector shim called into — issue #9's false
# positive (a fresh heartbeat misread as "daemon stuck" while a legitimate long
# bulk task was still in flight). Its only caller was the marketplace-refresh
# detector shim, retired 2026-09-17 (it ran `claude plugin marketplace update`
# across every registered marketplace and generated the file-churn that grew
# fseventsd to 27 GB); with that caller gone the function had zero callers and
# was deleted here too. `MAX_TASK_RUNTIME_S` below is still consumed by
# `detectors/global-chore-blackout.py` and `detectors/claimed-chore-stale.py`.

from __future__ import annotations

# A single daemon workload subprocess is capped at this many seconds
# (daemon.py::_WORKLOAD_TIMEOUT_SEC). A task's completion stamp legitimately
# ages by up to `cadence + this` before the next stamp lands, so the stale
# threshold must exceed that sum or a slow-but-successful run false-alarms.
# Keep in lock-step with daemon.py's cap if it changes.
MAX_TASK_RUNTIME_S = 1800


