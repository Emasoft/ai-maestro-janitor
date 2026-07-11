---
name: janitor-issues-watch-off
description: Turn OFF GitHub issue monitoring for THIS project - the heartbeat stops notifying you about new issues and new comments on the tracker. Use when the user says "stop watching the issues", "disable issue notifications", "turn off the issue tracker monitoring", "too many github issue notifications".
---

# Janitor issues-watch OFF

## Overview

Turns OFF the `github-issues-watch` detector (TRDD-2KQQAEPP) for THIS project by removing
its opt-in sentinel. The detector then costs one `stat` per fire and prints nothing.

## Instructions

1. Remove the opt-in sentinel:

   ```bash
   STATE_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.janitor/state"
   rm -f "$STATE_DIR/issues-watch.flag"
   ```

   The seen-map (`issues-watch-seen.json`) is deliberately LEFT in place. It is a tiny
   cache, not user work, and keeping it means re-enabling later resumes from where you
   left off instead of re-baselining. `/janitor-issues-watch-on` overwrites it anyway.

2. Report one line: issue notifications are off for this project.

## Output

One line to the user. Removes `.janitor/state/issues-watch.flag`.

## Scope

ONLY this project. Does NOT disarm the heartbeat, stop the daemon, touch other projects,
or change anything on GitHub. Re-enable with `/janitor-issues-watch-on`.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/detectors/github-issues-watch.py` — the detector this
  sentinel gates.
