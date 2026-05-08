#!/usr/bin/env bash
# Cron-fire entry point — back-compat thin wrapper around dispatch.py.
#
# Existing /janitor-arm cron jobs invoke this path by absolute reference,
# so we keep the .sh file alive but delegate to the Python implementation.
# After every armed cron renews itself (max 7-day TTL), this wrapper
# becomes unreachable and can eventually be retired.
exec uv run --script --quiet "$(dirname "$0")/dispatch.py" "$@"
