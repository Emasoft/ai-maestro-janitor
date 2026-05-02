#!/usr/bin/env bash
# Version-update detector — keeps three versions in sync:
#
#   * running       — version of dispatch.sh that's actually firing on the
#                     cron prompt (extracted from the script's own path)
#   * latest_installed — highest version present in the plugin cache dir
#   * latest_published — latest GitHub release for the repo declared in
#                        the manifest's `repository` field
#
# When latest_published > latest_installed, the detector attempts to
# auto-update via `claude plugin marketplace update` +
# `claude plugin update <plugin>@<marketplace> --scope <auto-detected>`.
# Auto-update is on by default and gated by `auto_update_on_new_release`.
#
# After a possible auto-update, if running != latest_installed, the
# detector emits a single concise nudge — the cron prompt has the
# dispatch path baked in at /janitor-arm time, so a stale cache OR a
# stale cron both need a re-arm to take effect.
#
# Silent on transient failures (no network, gh auth expired, no
# releases yet, claude CLI missing). One nudge per state change, then
# dedupe.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

SEEN="$STATE_DIR/version-update-seen.txt"

PLUGIN_NAME="ai-maestro-janitor"
MARKETPLACE_NAME="ai-maestro-plugins"

# Detect where the plugin is enabled so we can pass `--scope` correctly to
# `claude plugin update`. Falls back to "" when no settings file mentions
# the plugin — the CLI then uses whatever default scope it picks. Order
# matters: user → local → project; first match wins.
detect_install_scope() {
  local f
  f="$HOME/.claude/settings.json"
  [ -f "$f" ] && grep -q -- "$PLUGIN_NAME" "$f" 2>/dev/null && { printf 'user'; return; }
  if [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
    f="$CLAUDE_PROJECT_DIR/.claude/settings.local.json"
    [ -f "$f" ] && grep -q -- "$PLUGIN_NAME" "$f" 2>/dev/null && { printf 'local'; return; }
    f="$CLAUDE_PROJECT_DIR/.claude/settings.json"
    [ -f "$f" ] && grep -q -- "$PLUGIN_NAME" "$f" 2>/dev/null && { printf 'project'; return; }
  fi
  printf ''
}

# List installed semver dirs in $1 (cache parent) on stdout, sorted.
list_installed_versions() {
  local parent="$1" entry
  for entry in "$parent"/*; do
    [ -d "$entry" ] || continue
    local name
    name="$(basename "$entry")"
    if printf '%s' "$name" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
      printf '%s\n' "$name"
    fi
  done | sort -V
}

# Best-effort auto-update via the `claude` CLI. Returns 0 on success,
# 1 on any failure. All output captured to the detector log so the user
# can inspect what happened — never echoed to stdout (that would surface
# noise to the heartbeat instead of a single concise nudge).
attempt_auto_update() {
  local log="$LOG_DIR/version-update.log"

  if ! command -v claude >/dev/null 2>&1; then
    log_line version-update "auto-update: claude CLI not in PATH — falling back to manual nudge"
    return 1
  fi

  log_line version-update "auto-update: refreshing marketplace '$MARKETPLACE_NAME'"
  if ! timeout 30 claude plugin marketplace update "$MARKETPLACE_NAME" >>"$log" 2>&1; then
    log_line version-update "auto-update: marketplace refresh failed"
    return 1
  fi

  local scope
  scope=$(detect_install_scope)
  log_line version-update "auto-update: detected install scope='$scope'"

  local rc=0
  if [ -n "$scope" ]; then
    log_line version-update "auto-update: claude plugin update ${PLUGIN_NAME}@${MARKETPLACE_NAME} --scope $scope"
    timeout 120 claude plugin update "${PLUGIN_NAME}@${MARKETPLACE_NAME}" --scope "$scope" >>"$log" 2>&1 || rc=$?
  else
    log_line version-update "auto-update: claude plugin update ${PLUGIN_NAME}@${MARKETPLACE_NAME} (no scope detected)"
    timeout 120 claude plugin update "${PLUGIN_NAME}@${MARKETPLACE_NAME}" >>"$log" 2>&1 || rc=$?
  fi

  if [ "$rc" -ne 0 ]; then
    log_line version-update "auto-update: plugin update failed (rc=$rc)"
    return 1
  fi

  log_line version-update "auto-update: success"
  return 0
}

main() {
  # ---------- Compute the three versions ----------

  # Running version — basename of the parent of scripts/. Matches the cache
  # layout `<plugin>/<version>/scripts/detectors/`. If that name doesn't
  # look like a semver, we're running from a dev checkout and the cron
  # version check is meaningless.
  local running_version cache_parent
  running_version="$(basename "$(cd "$HERE/../.." && pwd -P)")"
  cache_parent="$(cd "$HERE/../../.." && pwd -P)"

  local is_cache_install=1
  if ! printf '%s' "$running_version" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    is_cache_install=0
    log_line version-update "running from non-versioned dir ($running_version) — cron-version check disabled"
  fi

  # Latest installed — highest semver dir under the cache parent. ls is
  # fine here: cache dirs are tightly controlled and adversarial filenames
  # would be a much bigger problem than this detector.
  local latest_installed=""
  if [ "$is_cache_install" = "1" ]; then
    latest_installed=$(list_installed_versions "$cache_parent" | tail -n1 || true)
  fi

  # Latest published — GitHub releases/latest of the manifest's repo.
  local latest_published=""
  if command -v gh >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
    local plugin_root plugin_json
    plugin_root="${CLAUDE_PLUGIN_ROOT:-}"
    [ -z "$plugin_root" ] && plugin_root="$(cd "$HERE/../.." && pwd -P)"
    plugin_json="$plugin_root/.claude-plugin/plugin.json"
    if [ -f "$plugin_json" ]; then
      local repo_url slug
      repo_url=$(jq -r .repository "$plugin_json" 2>/dev/null || echo "")
      slug=$(printf '%s' "$repo_url" | sed -nE 's#^https?://github\.com/([^/]+/[^/]+)(\.git)?/?$#\1#p')
      if [ -n "$slug" ]; then
        local latest_tag
        latest_tag=$(timeout 5 gh api "repos/$slug/releases/latest" --jq .tag_name 2>/dev/null || true)
        latest_published="${latest_tag#v}"
      fi
    fi
  fi

  log_line version-update "state: running=${running_version} latest_installed=${latest_installed} latest_published=${latest_published}"

  # ---------- Decision tree ----------

  # Branch A: newer published than locally installed?
  local auto_updated=0
  local manual_update_needed=0
  if [ -n "$latest_published" ] && [ -n "$latest_installed" ] && [ "$latest_published" != "$latest_installed" ]; then
    local older
    older=$(printf '%s\n%s\n' "$latest_installed" "$latest_published" | sort -V | head -n1)
    if [ "$older" = "$latest_installed" ]; then
      local auto_enabled="${CLAUDE_PLUGIN_OPTION_AUTO_UPDATE_ON_NEW_RELEASE:-true}"
      case "$auto_enabled" in
        false|FALSE|False|0|no|NO|off|OFF) auto_enabled=0 ;;
        *) auto_enabled=1 ;;
      esac

      if [ "$auto_enabled" = "1" ]; then
        if attempt_auto_update; then
          auto_updated=1
          # Re-list cache parent so latest_installed reflects the freshly
          # fetched version. If the update somehow didn't add a new dir,
          # treat that as a failure.
          local new_latest
          new_latest=$(list_installed_versions "$cache_parent" | tail -n1 || true)
          if [ -n "$new_latest" ] && [ "$new_latest" != "$latest_installed" ]; then
            latest_installed="$new_latest"
          else
            log_line version-update "auto-update reported success but cache version did not advance — treating as failure"
            auto_updated=0
            manual_update_needed=1
          fi
        else
          manual_update_needed=1
        fi
      else
        manual_update_needed=1
      fi
    else
      # latest_installed > latest_published → dev checkout / pre-release work
      log_line version-update "local cache (${latest_installed}) ahead of GitHub latest (${latest_published}) — silent"
    fi
  fi

  # Branch B: pick the right nudge for the current state.
  if [ "$manual_update_needed" = "1" ]; then
    emit_once "$SEEN" "version-update@manual@${latest_published}" \
      "[version-update] ${PLUGIN_NAME} ${latest_installed} → ${latest_published} — run /plugin update ${PLUGIN_NAME} + /janitor-arm."
  elif [ "$auto_updated" = "1" ]; then
    emit_once "$SEEN" "version-update@updated@${latest_installed}" \
      "[version-update] ${PLUGIN_NAME}: cache updated to ${latest_installed}. Run /reload-plugins + /janitor-arm."
  elif [ "$is_cache_install" = "1" ] && [ -n "$latest_installed" ] && [ "$running_version" != "$latest_installed" ]; then
    emit_once "$SEEN" "version-update@stale-cron@${latest_installed}" \
      "[version-update] ${PLUGIN_NAME} ${latest_installed} installed; cron is on ${running_version}. /janitor-arm."
  fi

  rotate_log_if_big version-update
}

main
exit 0
