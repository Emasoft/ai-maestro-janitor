#!/usr/bin/env bash
# /janitor-doctor backing script — pre-flight health check.
#
# Runs a series of named pass/fail checks and prints a unicode-bordered
# table. Exits 0 if all pass, 1 if any fail. Stdout is structured for
# direct rendering inside Claude Code's markdown surface; no ANSI colour
# (the user's terminal may not support it; the unicode markers carry the
# signal alone).
#
# Each check function:
#   * sets RESULT to 0 (pass) or 1 (fail)
#   * sets DETAIL to a short description
#   * sets FIX to a one-line remediation hint (empty when not applicable)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
init_state

PROJECT_ROOT=$(resolve_project_root)
PLUGIN_ROOT="$(cd "$HERE/../.." && pwd -P)"

ROWS=()
PASS_COUNT=0
FAIL_COUNT=0

add_row() {
  local name="$1" status="$2" detail="$3" fix="$4"
  ROWS+=("${name}|${status}|${detail}|${fix}")
  if [ "$status" = "PASS" ]; then
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

check_state_dir_writable() {
  if [ -d "$STATE_DIR" ] && [ -w "$STATE_DIR" ]; then
    add_row "state-dir-writable" "PASS" "$STATE_DIR exists and is writable" ""
  else
    add_row "state-dir-writable" "FAIL" "$STATE_DIR not writable" "Run /janitor-arm to bootstrap state, or check directory permissions"
  fi
}

check_log_dir_writable() {
  if [ -d "$LOG_DIR" ] && [ -w "$LOG_DIR" ]; then
    add_row "log-dir-writable" "PASS" "$LOG_DIR exists and is writable" ""
  else
    add_row "log-dir-writable" "FAIL" "$LOG_DIR not writable" "Run /janitor-arm to bootstrap, or check directory permissions"
  fi
}

check_dispatch_executable() {
  if [ -x "$PLUGIN_ROOT/scripts/dispatch.sh" ]; then
    add_row "dispatch-executable" "PASS" "scripts/dispatch.sh is executable" ""
  else
    add_row "dispatch-executable" "FAIL" "scripts/dispatch.sh missing or not executable" "Reinstall the plugin via /plugin install ai-maestro-janitor"
  fi
}

check_detectors_executable() {
  local missing=""
  local d
  for d in pr-reconciler worktree-janitor trdd-drift trdd-reminder task-pr-mismatch \
           stale-task dirty-tree subagent-report version-update trashcan-purge \
           remote-credentials stale-stash nested-git-safety tracked-ignored; do
    if [ ! -x "$PLUGIN_ROOT/scripts/detectors/${d}.sh" ]; then
      missing="${missing}${missing:+, }${d}"
    fi
  done
  if [ -z "$missing" ]; then
    add_row "detectors-executable" "PASS" "all detectors present and executable" ""
  else
    add_row "detectors-executable" "FAIL" "missing/non-executable: $missing" "Reinstall the plugin via /plugin install ai-maestro-janitor"
  fi
}

check_git_available() {
  if command -v git >/dev/null 2>&1; then
    add_row "git-available" "PASS" "git in PATH ($(git --version 2>&1 | head -1))" ""
  else
    add_row "git-available" "FAIL" "git not in PATH" "Install git — most detectors require it"
  fi
}

check_gh_authenticated() {
  if ! command -v gh >/dev/null 2>&1; then
    add_row "gh-authenticated" "FAIL" "gh CLI not in PATH" "Install gh and run 'gh auth login' — pr-reconciler and task-pr-mismatch require it"
    return
  fi
  if gh auth status >/dev/null 2>&1; then
    add_row "gh-authenticated" "PASS" "gh CLI is authenticated" ""
  else
    add_row "gh-authenticated" "FAIL" "gh CLI not authenticated" "Run 'gh auth login' — pr-reconciler and task-pr-mismatch will silently skip without it"
  fi
}

check_jq_available() {
  if command -v jq >/dev/null 2>&1; then
    add_row "jq-available" "PASS" "jq in PATH ($(jq --version 2>&1 | head -1))" ""
  else
    add_row "jq-available" "FAIL" "jq not in PATH" "Install jq — stale-task and pr-reconciler use it for JSON parsing"
  fi
}

check_gitignore_reports() {
  local gi="$PROJECT_ROOT/.gitignore"
  if [ ! -f "$gi" ]; then
    add_row "gitignore-reports" "FAIL" ".gitignore missing at project root" "Create .gitignore and add /reports/ + /reports_dev/"
    return
  fi
  local missing=""
  grep -qxF '/reports/' "$gi" 2>/dev/null      || missing="${missing}${missing:+, }/reports/"
  grep -qxF '/reports_dev/' "$gi" 2>/dev/null  || missing="${missing}${missing:+, }/reports_dev/"
  if [ -z "$missing" ]; then
    add_row "gitignore-reports" "PASS" "/reports/ and /reports_dev/ both gitignored" ""
  else
    add_row "gitignore-reports" "FAIL" "missing in .gitignore: $missing" "Add the missing entries to .gitignore — agents write reports there and they may contain private data"
  fi
}

check_plugin_json_valid() {
  local pj="$PLUGIN_ROOT/.claude-plugin/plugin.json"
  if [ ! -f "$pj" ]; then
    add_row "plugin-json-valid" "FAIL" ".claude-plugin/plugin.json missing" "Reinstall the plugin"
    return
  fi
  if command -v jq >/dev/null 2>&1; then
    if jq -e . "$pj" >/dev/null 2>&1; then
      add_row "plugin-json-valid" "PASS" "plugin.json parses as valid JSON" ""
    else
      add_row "plugin-json-valid" "FAIL" "plugin.json is not valid JSON" "Restore from a clean install"
    fi
  else
    # Fallback: python json
    if python3 -c "import json,sys;json.load(open('$pj'))" 2>/dev/null; then
      add_row "plugin-json-valid" "PASS" "plugin.json parses as valid JSON (via python3)" ""
    else
      add_row "plugin-json-valid" "FAIL" "plugin.json invalid (jq absent, python3 fallback failed)" "Install jq, then re-run /janitor-doctor"
    fi
  fi
}

check_in_git_repo() {
  if (cd "$PROJECT_ROOT" && git rev-parse --git-dir >/dev/null 2>&1); then
    add_row "in-git-repo" "PASS" "$PROJECT_ROOT is a git repo" ""
  else
    add_row "in-git-repo" "FAIL" "$PROJECT_ROOT is NOT a git repo" "Most detectors will silently skip — run /janitor-doctor in a git project"
  fi
}

# Run all checks
check_state_dir_writable
check_log_dir_writable
check_dispatch_executable
check_detectors_executable
check_git_available
check_in_git_repo
check_gh_authenticated
check_jq_available
check_gitignore_reports
check_plugin_json_valid

# Render unicode-bordered table. Column widths sized to fit on an 80-col
# terminal: name=22, status=6, detail=44.
HDR_TOP='┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓'
HDR_MID='┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩'
HDR_BOT='└──────────────────────┴────────┴──────────────────────────────────────────────┘'
ROW_SEP='├──────────────────────┼────────┼──────────────────────────────────────────────┤'

printf '%s\n' "$HDR_TOP"
printf '┃ %-20s ┃ %-6s ┃ %-44s ┃\n' "Check" "Status" "Detail"
printf '%s\n' "$HDR_MID"

first=1
for row in "${ROWS[@]}"; do
  IFS='|' read -r name status detail _fix <<< "$row"
  marker="$status"
  [ "$status" = "PASS" ] && marker="PASS"
  [ "$status" = "FAIL" ] && marker="FAIL"
  detail_short="${detail:0:44}"
  if [ "$first" = "1" ]; then
    first=0
  else
    printf '%s\n' "$ROW_SEP"
  fi
  printf '│ %-20s │ %-6s │ %-44s │\n' "${name:0:20}" "$marker" "$detail_short"
done
printf '%s\n' "$HDR_BOT"

# Detail report: any FAIL with a non-empty fix line gets surfaced
if [ "$FAIL_COUNT" -gt 0 ]; then
  printf '\nFix hints:\n'
  for row in "${ROWS[@]}"; do
    IFS='|' read -r name status _detail fix <<< "$row"
    if [ "$status" = "FAIL" ] && [ -n "$fix" ]; then
      printf '  • %s: %s\n' "$name" "$fix"
    fi
  done
fi

total=$((PASS_COUNT + FAIL_COUNT))
printf '\n%d/%d passed' "$PASS_COUNT" "$total"
if [ "$FAIL_COUNT" -eq 0 ]; then
  printf '. All green.\n'
  exit 0
else
  printf ' (%d failed).\n' "$FAIL_COUNT"
  exit 1
fi
