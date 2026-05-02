#!/usr/bin/env bash
# Version-update detector — checks GitHub for a newer release of this
# plugin and emits a single nudge per new version. Stays silent on
# transient failures (no network, gh auth expired, no releases yet,
# rate-limit) — those aren't drift, they're environment, and noisy
# alerts on transient outages are worse than missed nudges.
#
# Why a detector and not a hook: the check needs the dispatch.sh cadence
# guard so we don't hammer api.github.com on every 5-minute heartbeat.
# Default cadence is 24h.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

SEEN="$STATE_DIR/version-update-seen.txt"

main() {
  command -v gh >/dev/null 2>&1 || { log_line version-update "gh not in PATH — skipping"; return; }
  command -v jq >/dev/null 2>&1 || { log_line version-update "jq not in PATH — skipping"; return; }

  # CLAUDE_PLUGIN_ROOT is set by Claude Code when plugin scripts run. Without
  # it we can't find the local plugin.json. The script is also invokable
  # outside that context (testing), so derive a fallback from $HERE.
  local plugin_root="${CLAUDE_PLUGIN_ROOT:-}"
  if [ -z "$plugin_root" ]; then
    plugin_root="$(cd "$HERE/../.." && pwd -P)"
  fi
  local plugin_json="$plugin_root/.claude-plugin/plugin.json"
  [ -f "$plugin_json" ] || { log_line version-update "plugin.json not found at $plugin_json — skipping"; return; }

  local local_version
  local_version=$(jq -r .version "$plugin_json" 2>/dev/null || echo "")
  [ -z "$local_version" ] && { log_line version-update "could not read .version from $plugin_json — skipping"; return; }

  # Parse owner/repo from the manifest's "repository" field. The plugin's
  # canonical home is wherever its manifest points — that lets a fork check
  # against the fork's releases instead of upstream's, which is what the user
  # actually installed.
  local repo_url slug
  repo_url=$(jq -r .repository "$plugin_json" 2>/dev/null || echo "")
  slug=$(printf '%s' "$repo_url" | sed -nE 's#^https?://github\.com/([^/]+/[^/]+)(\.git)?/?$#\1#p')
  [ -z "$slug" ] && { log_line version-update "could not derive owner/repo from '$repo_url' — skipping"; return; }

  # 5s timeout — keep the heartbeat unblocked if api.github.com is slow.
  # `releases/latest` skips drafts and pre-releases by design.
  local latest_tag latest_version
  latest_tag=$(timeout 5 gh api "repos/$slug/releases/latest" --jq .tag_name 2>/dev/null || true)
  [ -z "$latest_tag" ] && { log_line version-update "GitHub releases unreachable for $slug — skipping"; return; }
  latest_version="${latest_tag#v}"

  if [ "$local_version" = "$latest_version" ]; then
    log_line version-update "on latest ($local_version)"
    return
  fi

  # `sort -V` is version-aware — figures out which is older without us
  # parsing semver by hand. If local is newer than published latest, we're
  # mid-release-cycle on a dev checkout: stay silent.
  local older
  older=$(printf '%s\n%s\n' "$local_version" "$latest_version" | sort -V | head -n1)
  if [ "$older" != "$local_version" ]; then
    log_line version-update "local ($local_version) is newer than published ($latest_version) — skipping"
    return
  fi

  # Key by the new version: a *later* release after this one fires a fresh
  # nudge instead of being silenced by the existing seen-key.
  emit_once "$SEEN" "version-update@${latest_version}" \
    "[version-update] ai-maestro-janitor ${local_version} → ${latest_version} — run /plugin update ai-maestro-janitor + /janitor-arm."

  rotate_log_if_big version-update
}

main
exit 0
