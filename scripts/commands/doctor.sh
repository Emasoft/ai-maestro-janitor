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
WARN_COUNT=0
FAIL_COUNT=0

# add_row <name> <status> <detail> <fix>
# Status taxonomy:
#   PASS — check passed, no action needed
#   FAIL — hard failure: the janitor cannot operate at all (missing scripts,
#          unreadable state dir, plugin.json corrupt). Exits 1.
#   WARN — soft failure: a specific subsystem is degraded but the rest of
#          the janitor still works (e.g. gh not authenticated → only
#          pr-reconciler / task-pr-mismatch silently skip). Counted, fix
#          hint shown, but does NOT change the exit code.
add_row() {
  local name="$1" status="$2" detail="$3" fix="$4"
  ROWS+=("${name}|${status}|${detail}|${fix}")
  case "$status" in
    PASS) PASS_COUNT=$((PASS_COUNT + 1)) ;;
    WARN) WARN_COUNT=$((WARN_COUNT + 1)) ;;
    FAIL) FAIL_COUNT=$((FAIL_COUNT + 1)) ;;
  esac
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
           remote-credentials stale-stash nested-git-safety tracked-ignored \
           plugin-updates mcp-config-drift \
           settings-scope-drift subagent-scope-drift claude-md-scope-drift \
           cross-scope-reference-drift; do
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
    add_row "gh-authenticated" "WARN" "gh CLI not in PATH" "Install gh + 'gh auth login' — pr-reconciler / task-pr-mismatch silently skip without it"
    return
  fi
  if gh auth status >/dev/null 2>&1; then
    add_row "gh-authenticated" "PASS" "gh CLI is authenticated" ""
  else
    add_row "gh-authenticated" "WARN" "gh CLI not authenticated" "Run 'gh auth login' — pr-reconciler / task-pr-mismatch silently skip without it"
  fi
}

check_jq_available() {
  if command -v jq >/dev/null 2>&1; then
    add_row "jq-available" "PASS" "jq in PATH ($(jq --version 2>&1 | head -1))" ""
  else
    add_row "jq-available" "WARN" "jq not in PATH" "Install jq — stale-task / pr-reconciler / task-pr-mismatch silently skip without it"
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
    # Fallback: python json. Pass the path via an environment variable
    # rather than interpolating into the python source — paths containing
    # `'` would otherwise be interpreted as Python syntax. The env var
    # name is uppercase by convention; the path is read via os.environ.
    if PJ_PATH="$pj" python3 -c "import json,os;json.load(open(os.environ['PJ_PATH']))" 2>/dev/null; then
      add_row "plugin-json-valid" "PASS" "plugin.json parses as valid JSON (via python3)" ""
    else
      add_row "plugin-json-valid" "FAIL" "plugin.json invalid (jq absent, python3 fallback failed)" "Install jq, then re-run /janitor-doctor"
    fi
  fi
}

check_libs_present() {
  local missing=""
  local lib
  for lib in state.sh dedupe.sh git-utils.sh; do
    if [ ! -f "$PLUGIN_ROOT/scripts/lib/${lib}" ]; then
      missing="${missing}${missing:+, }${lib}"
    fi
  done
  if [ -z "$missing" ]; then
    add_row "libs-present" "PASS" "scripts/lib/{state,dedupe,git-utils}.sh all present" ""
  else
    add_row "libs-present" "FAIL" "missing in scripts/lib/: $missing" "Reinstall the plugin — detectors will fail to source missing libs"
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
check_libs_present
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
  detail_short="${detail:0:44}"
  if [ "$first" = "1" ]; then
    first=0
  else
    printf '%s\n' "$ROW_SEP"
  fi
  printf '│ %-20s │ %-6s │ %-44s │\n' "${name:0:20}" "$status" "$detail_short"
done
printf '%s\n' "$HDR_BOT"

# Detail report: any non-PASS row with a fix line gets its hint surfaced.
if [ "$FAIL_COUNT" -gt 0 ] || [ "$WARN_COUNT" -gt 0 ]; then
  printf '\nFix hints:\n'
  for row in "${ROWS[@]}"; do
    IFS='|' read -r name status _detail fix <<< "$row"
    if [ "$status" != "PASS" ] && [ -n "$fix" ]; then
      printf '  • [%s] %s: %s\n' "$status" "$name" "$fix"
    fi
  done
fi

total=$((PASS_COUNT + WARN_COUNT + FAIL_COUNT))
# Exit code is gated on FAIL only — WARN rows surface in the report but do
# not block (e.g. missing gh / jq is fixable without taking the janitor
# down). Caller can still notice WARNs in the table or in the count line.
if [ "$FAIL_COUNT" -eq 0 ] && [ "$WARN_COUNT" -eq 0 ]; then
  printf '\n%d/%d passed. All green.\n' "$PASS_COUNT" "$total"
  exit 0
elif [ "$FAIL_COUNT" -eq 0 ]; then
  printf '\n%d/%d passed, %d warning(s) — janitor still operational.\n' \
    "$PASS_COUNT" "$total" "$WARN_COUNT"
  exit 0
else
  printf '\n%d/%d passed (%d failed' "$PASS_COUNT" "$total" "$FAIL_COUNT"
  [ "$WARN_COUNT" -gt 0 ] && printf ', %d warned' "$WARN_COUNT"
  printf ').\n'
  exit 1
fi
