#!/usr/bin/env bash
# Plugin-updates detector — auto-installs newer versions of plugins that
# Claude Code has installed in `project` or `local` scope, restricted to
# the project this janitor was armed in. Self-update of the janitor itself
# is handled by version-update.sh; this detector covers all OTHER plugins
# whose configuration lives inside the project's own `.claude/` directory.
#
# Claude Code's four configuration scopes (see docs/en/settings.md). The
# scope of an installed plugin is determined by which settings file
# pins it; the simple rule of thumb is "git-tracked = project, gitignored
# = local":
#
#   ┌──────────┬─────────────────────────────────────┬─────────────────────┐
#   │ scope    │ file the install reference lives in │ git status          │
#   ├──────────┼─────────────────────────────────────┼─────────────────────┤
#   │ managed  │ /etc/claude-code/managed-...        │ admin-deployed      │
#   │ project  │ <repo>/.claude/settings.json        │ TRACKED  → shared   │
#   │ local    │ <repo>/.claude/settings.local.json  │ GITIGNORED → personal│
#   │ user     │ ~/.claude/settings.json             │ outside any repo    │
#   └──────────┴─────────────────────────────────────┴─────────────────────┘
#
#   * `project` scope = the install reference is committed to the repo,
#     so every collaborator's checkout sees the same plugin pin. Updating
#     here moves the version pin for the whole team. The same convention
#     applies to direct-in-repo content under .claude/ (skills, agents,
#     commands, rules) — git-tracked → effectively shared with the team.
#   * `local` scope = the install reference is in settings.local.json
#     (gitignored), so only this user's checkout sees it. Updating only
#     affects this machine's personal pin.
#
# Both `project` and `local` live inside the project's `.claude/` and
# carry a `projectPath` field in the installed-plugins manifest, which is
# how we filter them to the project the janitor was armed in.
#
# The PLUGIN'S ACTUAL CONTENT (cache + manifest) sits in
# ~/.claude/plugins/cache/ regardless of scope; only the per-scope
# settings file's pin differs. That is why a multi-scope plugin needs
# multiple `claude plugin update` calls (one per scope) — each call
# advances ONE settings file's pointer, even though they all share the
# same cache slot.
#
# DESIGN PRINCIPLE: the janitor is project-scoped infrastructure. It must
# NEVER touch `user`-scope (global, every project on this machine) or
# `managed`-scope (set by an enterprise administrator) plugins. Even if
# the user explicitly configures `plugin_auto_update_scopes` to include
# them, those scopes are hard-filtered out below. The reasoning:
#
#   * A user-scope plugin update affects every project on the machine. A
#     project-armed janitor has no mandate over the user's other projects.
#   * A managed-scope plugin update could conflict with admin policy.
#
# The userConfig `plugin_auto_update_scopes` only chooses between `local`
# and `project` (default both). For `user`/`managed`-scope updates, the
# user must run `claude plugin update <id> --scope <scope>` manually.
#
# Algorithm:
#
#   1. `claude plugin list --json` → enumerate installed plugins (id,
#      version, scope, projectPath).
#   2. Group by marketplace; refresh each marketplace's metadata once with
#      `claude plugin marketplace update <mp>`. Skipped marketplaces (no
#      installed plugin from them) are not touched, keeping the per-fire
#      cost proportional to actual usage rather than the full marketplace
#      cache.
#   3. For each unique plugin, read the marketplace.json that the refresh
#      just wrote and look up the latest published version. Compare against
#      the installed version using `sort -V`.
#   4. If `plugin_auto_update_enabled` is true (default), run
#      `claude plugin update <plugin>@<marketplace>` and emit a drift line
#      announcing the upgrade. If false, only emit a "manual update
#      available" line.
#
# Safety gates:
#
#   * The janitor's own plugin id is excluded — version-update.sh owns
#     that path. Updating the same plugin twice in one heartbeat would
#     race on the cache.
#
#   * Local- and project-scope plugins are filtered by `projectPath`: we
#     only auto-update local installs whose projectPath is the current
#     project. User-scope plugins are global and are processed regardless
#     of cwd.
#
#   * `plugin_auto_update_scopes` lets the user restrict which scopes are
#     touched (default "user,local,project" — i.e. all). Setting it to
#     just "user" makes the detector safe for shared dev machines where
#     project-local installs may be customised.
#
#   * `plugin_auto_update_exclude` accepts a comma-separated list of
#     plugin@marketplace IDs to skip entirely.
#
#   * Same plugin in multiple scopes updates only once — the cache is
#     shared, and a single `claude plugin update` covers every consumer.
#
# Failures are silent at the heartbeat surface (logged to
# .janitor/logs/plugin-updates.log). The user requested "auto-update
# without asking", so we never block on a prompt; we always log so an
# audit trail exists.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

SEEN="$STATE_DIR/plugin-updates-seen.txt"
LOG="$LOG_DIR/plugin-updates.log"

# Self — never updated by this detector. version-update.sh handles it.
SELF_PLUGIN_NAME="ai-maestro-janitor"

auto_enabled() {
  local v="${CLAUDE_PLUGIN_OPTION_PLUGIN_AUTO_UPDATE_ENABLED:-true}"
  case "$v" in
    false|FALSE|False|0|no|NO|off|OFF) return 1 ;;
  esac
  return 0
}

scope_allowed() {
  local scope="$1"
  # HARD FILTER: user and managed scopes are NEVER touched, regardless of
  # what `plugin_auto_update_scopes` says. See the design-principle block
  # at the top of this file for rationale. We refuse the request silently
  # rather than emit an error, because the user might legitimately have
  # configured `plugin_auto_update_scopes=user,local,project` for the
  # OLD behavior and we don't want to be noisy about ignoring `user`.
  case "$scope" in
    user|managed) return 1 ;;
  esac
  local allowed="${CLAUDE_PLUGIN_OPTION_PLUGIN_AUTO_UPDATE_SCOPES:-local,project}"
  case ",${allowed}," in
    *",${scope},"*) return 0 ;;
  esac
  return 1
}

plugin_excluded() {
  local id="$1"
  local list="${CLAUDE_PLUGIN_OPTION_PLUGIN_AUTO_UPDATE_EXCLUDE:-}"
  [ -z "$list" ] && return 1
  case ",${list}," in
    *",${id},"*) return 0 ;;
  esac
  return 1
}

# Locate marketplace.json for a given marketplace name. Newer marketplaces
# nest it under .claude-plugin/; older ones place it at the root. Both are
# checked.
find_marketplace_json() {
  local mp="$1"
  local root="$HOME/.claude/plugins/marketplaces/$mp"
  if [ -f "$root/.claude-plugin/marketplace.json" ]; then
    printf '%s\n' "$root/.claude-plugin/marketplace.json"
    return 0
  fi
  if [ -f "$root/marketplace.json" ]; then
    printf '%s\n' "$root/marketplace.json"
    return 0
  fi
  return 1
}

latest_version_in_marketplace() {
  local plugin_name="$1" mp_json="$2"
  jq -r --arg name "$plugin_name" \
    '.plugins[]? | select(.name == $name) | .version' \
    "$mp_json" 2>/dev/null | head -1
}

main() {
  command -v claude >/dev/null 2>&1 || {
    log_line plugin-updates "claude CLI not in PATH — skipping"
    return
  }
  command -v jq >/dev/null 2>&1 || {
    log_line plugin-updates "jq not in PATH — skipping"
    return
  }

  local current_project
  current_project=$(resolve_project_root)

  # 1. Enumerate installed plugins. timeout guards against a pathological
  # CLI that hangs on a corrupted plugin index.
  local plugin_list
  plugin_list=$(timeout 30 claude plugin list --json 2>/dev/null) || {
    log_line plugin-updates "claude plugin list --json failed — skipping"
    return
  }
  [ -z "$plugin_list" ] && return

  # Sanity check: must be JSON array.
  printf '%s' "$plugin_list" | jq -e 'type == "array"' >/dev/null 2>&1 || {
    log_line plugin-updates "claude plugin list --json returned non-array — skipping"
    return
  }

  # 2. Build the CANDIDATE set first (apply every cheap filter — scope
  # rejection, projectPath match, self-exclusion, user excludes) BEFORE
  # touching any marketplace. Refreshing a marketplace is the expensive
  # operation: each call takes a few seconds, and on a machine with many
  # marketplaces it's the single biggest contributor to detector runtime.
  # By computing candidates first we skip refresh for marketplaces whose
  # installed plugins are all user/managed/other-project (the common
  # case — project-scoped plugins are typically a small subset).
  local candidates_tsv
  candidates_tsv=$(printf '%s' "$plugin_list" \
    | jq -r --arg cp "$current_project" --arg self "$SELF_PLUGIN_NAME" '
        .[]
        | select(.id | contains("@"))
        | select((.id | split("@") | .[0]) != $self)
        | select(.scope == "project" or .scope == "local")
        | select(.projectPath == $cp)
        | [.id, .version, .scope, (.projectPath // "")] | @tsv
      ' 2>/dev/null || true)

  if [ -z "$candidates_tsv" ]; then
    log_line plugin-updates "no project/local-scope plugins for $current_project — nothing to do"
    return
  fi

  # Extract unique marketplaces from the candidate set only, then refresh.
  local marketplaces
  marketplaces=$(printf '%s\n' "$candidates_tsv" \
    | awk -F'\t' '{print $1}' \
    | awk -F'@' '{print $2}' \
    | sort -u | grep -v '^$' || true)

  local mp
  for mp in $marketplaces; do
    log_line plugin-updates "refreshing marketplace: $mp"
    timeout 60 claude plugin marketplace update "$mp" >>"$LOG" 2>&1 \
      || log_line plugin-updates "marketplace refresh failed: $mp"
  done

  # 3. Walk each plugin record. The dedup key is (id, scope, projectPath)
  # — NOT just id — because `claude plugin update` requires `--scope` to
  # update the right settings file. Without --scope the CLI defaults to
  # `user`, so a plugin installed in `local` or `project` scope would
  # silently fail to update (the cache might advance, but the per-scope
  # settings.json keeps pointing at the old version).
  #
  # Concrete example:
  #   - Plugin X is installed in BOTH user and local scope for this project.
  #   - We see two records: (X, user) and (X, local, /path/to/this/project).
  #   - We need to call:
  #       claude plugin update X --scope user
  #       claude plugin update X --scope local
  #     The first one populates the cache; the second is fast (cache is
  #     already there) and updates the local settings to point at the new
  #     version.
  local seen_keys="" updates_applied=0 update_errors=0

  while IFS=$'\t' read -r id current_version scope project_path; do
    [ -z "$id" ] && continue

    # The candidate set was already filtered for scope=project|local,
    # projectPath=current_project, and plugin_name != self. We still
    # apply the user-driven filters (scope_allowed, plugin_excluded)
    # because those are configurable and live outside the jq pipeline
    # for clarity.
    local plugin_name="${id%@*}"
    local marketplace="${id#*@}"

    scope_allowed "$scope" || continue
    plugin_excluded "$id" && continue

    # Dedup by (id, scope, projectPath) so a plugin in multiple scopes
    # gets one update call PER SCOPE (each call uses a different
    # --scope flag). A `|` separator between fields keeps the key
    # parseable even when projectPath contains spaces.
    local dedup_key="${id}|${scope}|${project_path}"
    case "|${seen_keys}|" in
      *"|${dedup_key}|"*) continue ;;
    esac
    seen_keys="${seen_keys}|${dedup_key}"

    # Marketplace metadata required for version comparison. Skip if the
    # marketplace.json is missing (could happen if marketplace refresh
    # failed and there was no prior cache).
    local mp_json
    mp_json=$(find_marketplace_json "$marketplace") || {
      log_line plugin-updates "no marketplace.json for '$marketplace' — skipping $id"
      continue
    }

    # Read the marketplace's claim about the plugin's latest version.
    # `latest_version_in_marketplace` returns the literal string "null"
    # when the marketplace.json entry has no `version` field (or sets it
    # to JSON null) — that's the jq default. We treat both empty and
    # "null" as "no version metadata", and SKIP rather than guess. Such
    # plugins still auto-update via the user's manual `claude plugin
    # update`; the heartbeat-driven path requires authoritative version
    # data so we never push a "→ null" message to Claude.
    local latest
    latest=$(latest_version_in_marketplace "$plugin_name" "$mp_json")
    case "$latest" in
      ""|"null"|"None")
        log_line plugin-updates "no version field in marketplace.json for $id — skipping"
        continue
        ;;
    esac

    [ "$latest" = "$current_version" ] && continue

    # Decide whether `latest` is genuinely newer. For semver-shaped versions
    # we use `sort -V`; for hash-style versions (some plugins use git
    # short-SHAs as version strings) the only signal is "different string",
    # so we accept any non-equal value as a candidate update and rely on
    # the CLI's own output downstream to confirm whether the update was
    # actually a forward move.
    local update_candidate=0
    if [[ "$current_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]] \
       && [[ "$latest" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
      local newer
      newer=$(printf '%s\n%s\n' "$current_version" "$latest" | sort -V | tail -n1)
      if [ "$newer" = "$latest" ] && [ "$newer" != "$current_version" ]; then
        update_candidate=1
      fi
    else
      update_candidate=1
    fi
    [ "$update_candidate" = 0 ] && continue

    if auto_enabled; then
      # Pass `--scope` matching this record's actual installation scope.
      # Without it the CLI defaults to `--scope user`, which silently
      # fails to update plugins installed in local/project/managed
      # scopes (the cache may advance but the per-scope settings stay
      # pinned to the old version). Verified via `claude plugin update
      # --help`: accepts `user|project|local|managed`.
      log_line plugin-updates "auto-updating ${id} [scope=${scope}]: ${current_version} → ${latest}"
      local update_out rc=0
      update_out=$(timeout 120 claude plugin update "$id" --scope "$scope" 2>&1) || rc=$?
      printf '%s\n' "$update_out" >>"$LOG"

      if [ "$rc" -ne 0 ]; then
        log_line plugin-updates "auto-update of $id [scope=${scope}] failed (rc=$rc)"
        emit_once "$SEEN" "manual@${id}@${scope}@${latest}" \
          "[plugin-updates] auto-update of ${id} (scope ${scope}) failed (${current_version} → ${latest}). Run manually: claude plugin update ${id} --scope ${scope}"
        update_errors=$((update_errors + 1))
      elif printf '%s' "$update_out" | grep -qE 'updated from .+ to '; then
        # CLI confirmed an actual upgrade. Extract the REAL post-update
        # version from its output rather than trusting the marketplace.json
        # value — some plugins jump multiple minor versions in a single
        # update (the cache may have been stale by 2+ versions).
        local real_new
        real_new=$(printf '%s' "$update_out" \
          | grep -oE 'updated from [^ ]+ to [^ .]+' \
          | head -1 \
          | sed -E 's/^updated from .+ to //')
        [ -z "$real_new" ] && real_new="$latest"
        emit_once "$SEEN" "updated@${id}@${scope}@${current_version}->${real_new}" \
          "[plugin-updates] auto-updated ${id} [scope ${scope}]: ${current_version} → ${real_new}. Run /reload-plugins to apply in this session."
        updates_applied=$((updates_applied + 1))
      elif printf '%s' "$update_out" | grep -qE 'already at the latest'; then
        # No-op: marketplace metadata thought there was an update but the
        # CLI's source-of-truth disagrees. Silent in drift output.
        log_line plugin-updates "$id [scope=${scope}]: CLI reports already at latest (marketplace.json suggested ${latest})"
      else
        # Unexpected output shape — neither success nor known no-op marker.
        # Treat as failure for visibility.
        log_line plugin-updates "$id [scope=${scope}]: unexpected update output — treating as failure"
        emit_once "$SEEN" "manual@${id}@${scope}@${latest}" \
          "[plugin-updates] update of ${id} (scope ${scope}) returned unexpected output. Run manually: claude plugin update ${id} --scope ${scope}"
        update_errors=$((update_errors + 1))
      fi
    else
      emit_once "$SEEN" "available@${id}@${scope}@${latest}" \
        "[plugin-updates] update available for ${id} [scope ${scope}]: ${current_version} → ${latest}. Auto-update is off (plugin_auto_update_enabled=false). Run: claude plugin update ${id} --scope ${scope}"
    fi
  done <<< "$candidates_tsv"

  if [ "$updates_applied" -gt 0 ] || [ "$update_errors" -gt 0 ]; then
    log_line plugin-updates "summary: ${updates_applied} updated, ${update_errors} failed"
  fi

  rotate_log_if_big plugin-updates
}

main
exit 0
