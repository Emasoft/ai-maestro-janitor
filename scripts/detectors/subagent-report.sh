#!/usr/bin/env bash
# Subagent report detector — nudges Claude Code to act on recent subagent
# report files in docs_dev/ / tests/scenarios/reports/ / scripts_dev/ that
# have not yet been referenced in any commit message. Catches the "agent
# wrote a report but the findings were never acted upon" drift pattern.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

SEEN="$STATE_DIR/subagent-report-seen.txt"

LOOKBACK=$(coerce_int "${CLAUDE_PLUGIN_OPTION_SUBAGENT_REPORT_LOOKBACK:-}" 86400)
MAX_EMIT_PER_FIRE=5

SCAN_DIRS=(
  "docs_dev"
  "tests/scenarios/reports"
  "scripts_dev"
)

main() {
  git rev-parse --git-dir >/dev/null 2>&1 || {
    log_line subagent-report "not a git repo — skipping"
    return
  }

  local root now cutoff
  root=$(resolve_project_root)
  now=$(date +%s)
  cutoff=$(( now - LOOKBACK ))

  # Collect last-7-days commit messages once so we can match filenames cheap.
  local commit_bodies
  commit_bodies=$(git log --since="7 days ago" --pretty='format:%s %b' 2>/dev/null || echo "")

  local count=0
  local d f
  for d in "${SCAN_DIRS[@]}"; do
    local full="$root/$d"
    [ -d "$full" ] || continue
    while IFS= read -r f; do
      [ -z "$f" ] && continue
      [ "$count" -ge "$MAX_EMIT_PER_FIRE" ] && break 2

      local mtime age
      mtime=$(file_mtime "$f")
      [ "$mtime" = "0" ] && continue
      [ "$mtime" -lt "$cutoff" ] && continue
      age=$(( now - mtime ))

      local rel="${f#"$root"/}"
      # Match the full project-relative path against recent commit messages
      # (not just the basename — a short filename like "notes.md" would
      # false-match commit bodies that mention "notes" in any unrelated way).
      if [ -n "$commit_bodies" ] && printf '%s' "$commit_bodies" | grep -qF -- "$rel"; then
        continue
      fi

      local age_h=$(( age / 3600 ))
      local bucket=$(( age / 86400 ))
      emit_once "$SEEN" "report@${rel}@d${bucket}" \
        "[subagent-report] ${rel} (${age_h}h old) has not been referenced in any commit — review and act on it, or commit a note explaining why it's deferred."
      count=$(( count + 1 ))
    done < <(find "$full" -type f -name '*.md' 2>/dev/null)
  done

  rotate_log_if_big subagent-report
}

main
exit 0
