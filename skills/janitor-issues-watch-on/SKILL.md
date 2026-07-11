---
name: janitor-issues-watch-on
description: Turn ON GitHub issue monitoring for THIS project - the heartbeat then notifies you whenever a new issue is opened or a new comment lands on the tracker, and keeps reporting until it is turned off. Use when the user says "watch the github issues", "notify me about new issues", "monitor the issue tracker", "enable issue notifications". Seeds a baseline from the currently-open issues first, so enabling it does NOT dump the existing backlog into context.
---

# Janitor issues-watch ON

## Overview

Turns ON the `github-issues-watch` detector (TRDD-2KQQAEPP) for THIS project. Once on,
every due heartbeat (default 30 min) asks GitHub for the open issues and prints one line
per **new issue** or **new comment**:

```
[github-issues] #12 "Crash on empty config" — new (0 comments) https://github.com/owner/repo/issues/12
[github-issues] #7 "Slow startup" — updated (3 comments) https://github.com/owner/repo/issues/7
```

It keeps reporting until `/janitor-issues-watch-off`. An issue that has not changed since
the last pass never re-fires, so the stream stays quiet unless something actually happened.

## Prerequisites

- The project has a GitHub `origin` remote (a non-GitHub remote is a silent no-op).
- `gh` is installed and authenticated. If it is not, the detector stays silent — say so
  when reporting, rather than pretending the watcher is live.

## Instructions

1. **Baseline first, flag second.** Seeding the seen-map from the currently-open issues is
   what stops the first fire from dumping the whole existing backlog into context. Do it
   in this order — if the flag were written first, a heartbeat could fire in between and
   report every open issue at once.

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   mkdir -p "$STATE_DIR"

   SLUG="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)"
   if [ -z "$SLUG" ]; then
     echo "NO_GH_REPO"
   else
     gh issue list --repo "$SLUG" --state open \
       --json number,updatedAt --limit 50 2>/dev/null \
     | python3 -c 'import json,sys; print(json.dumps({str(i["number"]): i.get("updatedAt","") for i in json.load(sys.stdin)}))' \
       > "$STATE_DIR/issues-watch-seen.json.tmp.$$" \
     && mv -f "$STATE_DIR/issues-watch-seen.json.tmp.$$" "$STATE_DIR/issues-watch-seen.json"

     printf 'on' > "$STATE_DIR/issues-watch.flag.tmp.$$" && \
       mv -f "$STATE_DIR/issues-watch.flag.tmp.$$" "$STATE_DIR/issues-watch.flag"

     echo "WATCHING $SLUG"
     python3 -c 'import json;print(len(json.load(open("'"$STATE_DIR"'/issues-watch-seen.json"))),"open issues baselined")'
   fi
   ```

2. Report ONE line: the repo slug, how many open issues were baselined, and that you will
   be notified of anything new from now on. If the script printed `NO_GH_REPO`, say the
   project has no GitHub remote (or `gh` is not authenticated) and that nothing was
   enabled.

## Output

Two project-scoped state files and one line to the user. Writes:
`.janitor/state/issues-watch.flag` (the opt-in sentinel the detector gates on) and
`.janitor/state/issues-watch-seen.json` (the `{number: updatedAt}` baseline).

## Scope

ONLY this project. Does NOT touch other projects, the daemon, user-scope config, or the
GitHub repo itself (the watcher is strictly read-only — it never comments, labels, or
closes anything). Disable with `/janitor-issues-watch-off`.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/detectors/github-issues-watch.py` — the detector.
- `${CLAUDE_PLUGIN_ROOT}/scripts/lib/issues_watch.py` — the pure diff/format core.
- `CLAUDE_PLUGIN_OPTION_ISSUES_WATCH_INTERVAL` — cadence in seconds (default 1800).
