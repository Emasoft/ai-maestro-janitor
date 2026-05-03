#!/usr/bin/env bash
# trashcan-purge — auto-removes timestamped batches in <project_root>/.trashcan/
# whose age (computed from the folder-name timestamp, NOT file mtimes) exceeds
# CLAUDE_PLUGIN_OPTION_TRASHCAN_MAX_AGE_DAYS (default: 90).
#
# Why folder-name timestamps and not mtimes:
#   A user (or another tool) could `touch` a file inside an old batch and
#   accidentally reset its mtime. The folder name encodes the disposal moment
#   that the safe-delete script wrote at trash time, and is immutable for the
#   life of the batch — so an old batch stays old regardless of what happens
#   to its contents.
#
# Why this detector NEVER touches .gitkeep / README.txt / unrecognised files:
#   The trashcan directory is kept alive by tracked .gitkeep + README.txt
#   markers (see scripts/safe-delete.sh). Removing those would defeat the
#   whole survival mechanism — the dir would vanish on the next
#   `git clean -fdx`. The case-pattern matcher below only matches the exact
#   timestamp shape; anything else is skipped silently.
#
# Configurable knobs (userConfig in plugin.json):
#   trashcan_max_age_days     — purge threshold (default: 90)
#   trashcan_purge_interval   — min seconds between purges (default: 86400)
#   trashcan_purge_enabled    — bool, default true; set false to skip entirely

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

ENABLED="${CLAUDE_PLUGIN_OPTION_TRASHCAN_PURGE_ENABLED:-true}"
case "$ENABLED" in
  false|False|FALSE|0|no|NO) exit 0 ;;
esac

MAX_AGE_DAYS=$(coerce_int "${CLAUDE_PLUGIN_OPTION_TRASHCAN_MAX_AGE_DAYS:-}" 90)
THRESHOLD_SEC=$(( MAX_AGE_DAYS * 86400 ))

PROJECT_ROOT=$(resolve_project_root)
TRASH_DIR="$PROJECT_ROOT/.trashcan"

[ -d "$TRASH_DIR" ] || exit 0

# Parse a folder name of shape YYYYMMDD_HHMMSS±HHMM into epoch seconds. Tries
# GNU `date -d` first, falls back to BSD `date -j -f`. Returns 1 if neither
# parser accepts the input — caller should skip the entry rather than panic.
# Usage: epoch=$(parse_ts_to_epoch "20260503_173513+0200") || continue
parse_ts_to_epoch() {
  local ts="$1"
  local date_part time_part offset
  date_part="${ts:0:8}"           # YYYYMMDD
  time_part="${ts:9:6}"           # HHMMSS
  offset="${ts:15}"               # +HHMM or -HHMM
  local iso="${date_part:0:4}-${date_part:4:2}-${date_part:6:2}T${time_part:0:2}:${time_part:2:2}:${time_part:4:2}${offset}"
  if date -d "$iso" +%s 2>/dev/null; then return 0; fi
  if date -j -f "%Y-%m-%dT%H:%M:%S%z" "$iso" +%s 2>/dev/null; then return 0; fi
  return 1
}

main() {
  local now purged_count=0 purged_oldest_days=0
  now=$(date +%s)

  shopt -s nullglob
  local entry name ts entry_epoch age age_days txt_sibling
  for entry in "$TRASH_DIR"/*; do
    [ -e "$entry" ] || continue
    name=$(basename -- "$entry")

    # Match folder pattern (YYYYMMDD_HHMMSS±HHMM) or manifest pattern
    # (YYYYMMDD_HHMMSS±HHMM.txt). Anything else is left alone — that's how
    # .gitkeep, README.txt, and any human-added file or folder stay safe.
    ts=""
    case "$name" in
      [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]+[0-9][0-9][0-9][0-9])
        ts="$name" ;;
      [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9])
        ts="$name" ;;
      [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]+[0-9][0-9][0-9][0-9].txt)
        ts="${name%.txt}" ;;
      [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9].txt)
        ts="${name%.txt}" ;;
      *)
        continue
        ;;
    esac

    if ! entry_epoch=$(parse_ts_to_epoch "$ts"); then
      log_line trashcan-purge "could not parse timestamp from '$name' — skipping"
      continue
    fi

    age=$(( now - entry_epoch ))
    [ "$age" -lt "$THRESHOLD_SEC" ] && continue

    age_days=$(( age / 86400 ))

    # When we delete a folder, also delete its sibling .txt manifest so we
    # don't leave orphans. When we delete a .txt manifest first (loop order
    # is filesystem-defined), that's fine — the folder will follow on its
    # own iteration.
    if [ -d "$entry" ] && [ ! -L "$entry" ]; then
      txt_sibling="$TRASH_DIR/${ts}.txt"
      rm -rf -- "$entry"
      [ -f "$txt_sibling" ] && rm -f -- "$txt_sibling"
      log_line trashcan-purge "purged folder + manifest '$ts' (age: ${age_days}d)"
    elif [ -f "$entry" ]; then
      rm -f -- "$entry"
      log_line trashcan-purge "purged orphan manifest '$name' (age: ${age_days}d)"
    fi

    purged_count=$(( purged_count + 1 ))
    [ "$age_days" -gt "$purged_oldest_days" ] && purged_oldest_days=$age_days
  done
  shopt -u nullglob

  if [ "$purged_count" -gt 0 ]; then
    echo "[trashcan-purge] auto-removed ${purged_count} batch(es) from .trashcan/ older than ${MAX_AGE_DAYS} days (oldest: ${purged_oldest_days}d). Folder-name timestamps are the source of truth — file mtimes inside batches are ignored."
  fi

  rotate_log_if_big trashcan-purge
}

main
exit 0
