#!/bin/sh
# Run a janitor hook script, failing OPEN when the plugin tree is not there.
#
# WHY THIS EXISTS (measured 2026-08-20, janitor#281 / janitor#271 / TRDD-4OFMHOZ7):
# `uv run --script --quiet <MISSING FILE>` exits **2**. For a PreToolUse hook, exit 2 is
# not "the command failed" — it is the BLOCKING code, the one that DENIES the tool call.
# Any other non-zero exit is merely logged and execution continues.
#
# A plugin update / `/reload-plugins --force` empties the ACTIVE version directory in
# place while it refetches. During that window every hook command in hooks.json points at
# a path that no longer exists, so all six PreToolUse hooks exit 2 at once and EVERY Bash
# and Edit call in EVERY live session is denied until the refetch lands — reported as
# ~15 minutes of a session that cannot use a tool. The non-atomic refetch is upstream's;
# turning a transient file-absence into a session-wide lockout was ours, and this is our
# half of the fix.
#
# The distinction that makes it safe: "the script is not there" and "the script decided to
# deny" must not collapse into the same exit code. So this wrapper answers 0 (no opinion)
# ONLY for the absent case, and `exec`s otherwise — a hook that is present keeps its full
# ability to exit 2 and block, which is exactly what pre-bash-safety and the publish lock
# depend on. A blanket `|| exit 0` would have masked real denials; that is the trap here.
#
# If THIS wrapper is itself missing (same emptied-directory window), the shell cannot open
# it and exits 127 — non-zero but NOT 2, so it is non-blocking by the same rule. The
# failure mode is fail-open at every layer, by construction.
set -u
script="${1:-}"
[ -n "$script" ] || exit 0
[ -f "$script" ] || exit 0
shift
exec uv run --script --quiet "$script" "$@"
