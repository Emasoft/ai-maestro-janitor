#!/usr/bin/env bash
# MCP config drift — passively audits the project's MCP server configuration
# for the three classes of drift that have caused real "the MCP server
# silently doesn't connect" incidents:
#
#   1. JSON parse errors. A trailing comma or stray bracket in `.mcp.json`
#      makes Claude Code skip the entire file with no error visible to the
#      user. We catch the parse error explicitly.
#
#   2. Tracking ambiguity on `.mcp.json`. Per the project's git-tracking
#      ↔ scope convention (see plugin-updates.sh header), an MCP config
#      should be EITHER:
#        * git-tracked (in `git ls-files`) → effectively project scope:
#          team-shared, every collaborator gets the same servers.
#        * gitignored (matched by `git check-ignore`) → effectively local
#          scope: personal servers that won't leak into the repo.
#      Anything else — the file is on disk, not in git, not in
#      `.gitignore` — is ambiguous and a common source of "I configured
#      the server but my teammate's checkout doesn't have it" or "my
#      personal API token leaked into the repo on the next commit".
#
#   3. Per-server config sanity:
#        a. NO transport — neither `command` nor `url` is set. Claude
#           Code can't start the server.
#        b. Unset env var references — `command`, `args`, `env` values,
#           `headers` values, and `url` are scanned for `$VAR` / `${VAR}`
#           tokens. Any token whose corresponding env var is unset in
#           THIS shell is surfaced. False positives are possible (the
#           user may have set the var in a different shell that started
#           Claude Code) but the dominant case is "I forgot to add the
#           token to my .env" — worth surfacing.
#
# Three config locations are checked, all bound to the project:
#   * `<root>/.mcp.json`                       — top-level, used for
#                                                project-shared servers
#   * `<root>/.claude/settings.json`           — `.mcpServers` key,
#                                                project-scope (committed)
#   * `<root>/.claude/settings.local.json`     — `.mcpServers` key,
#                                                local-scope (gitignored)
#
# Per the janitor's project-scope-only mandate (matching plugin-updates),
# the user-scope `~/.claude/settings.json` is NEVER inspected here.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

SEEN="$STATE_DIR/mcp-config-drift-seen.txt"

# Surface a drift line, defanging ANY untrusted text (server names, env
# var references, paths) that originates from JSON files we don't fully
# control. Same convention as stale-stash and pr-reconciler.
emit() {
  local key="$1"
  local msg="$2"
  emit_once "$SEEN" "$key" "$msg"
}

# Scan a JSON value for $VAR or ${VAR} references. Returns one var name
# per line, deduped, sorted. Refs to lowercase or numeric-prefixed names
# are skipped (those are uncommon in shell env vars and more often
# coincidental matches like `$1` in a sample command).
extract_env_refs() {
  local json_value="$1"
  # `$` and `{` and `}` are the literal characters we want stripped from
  # the matched env-var tokens. Single quotes around the tr argset are
  # fine here — we deliberately want NO shell expansion. The shellcheck
  # disable silences the SC2016 false-positive: in this context single
  # quotes are correct.
  #
  # Trailing `|| true`: under `set -o pipefail`, a `grep -oE` pipeline that
  # finds zero matches exits non-zero. When this function is called via
  # `local refs=$(extract_env_refs ...)` from a script with `set -e`, that
  # non-zero would abort the entire detector mid-loop (subtle bash gotcha:
  # `local var=$(cmd)` propagates the failure even though `local` itself
  # returns 0). The `|| true` keeps the function's exit code always 0 —
  # zero matches is a normal outcome, not a failure.
  # shellcheck disable=SC2016
  {
    printf '%s' "$json_value" \
      | grep -oE '\$\{[A-Z_][A-Z0-9_]*\}|\$[A-Z_][A-Z0-9_]*' \
      | tr -d '${}' \
      | sort -u
  } || true
}

# Test whether a named env var is set (and non-empty). Uses bash indirect
# expansion `${!name:-}` so unset vars don't trigger `set -u`.
env_is_set() {
  local name="$1"
  [ -n "${!name:-}" ]
}

# Validate one server config. $1 = source label (file path), $2 = server
# name, $3 = JSON value of the server's config.
check_server() {
  local source_label="$1" name="$2" config="$3"
  local safe_label safe_name
  safe_label=$(sanitize_for_drift_line "$source_label")
  safe_name=$(sanitize_for_drift_line "$name")

  local cmd url
  cmd=$(printf '%s' "$config" | jq -r '.command // empty' 2>/dev/null)
  url=$(printf '%s' "$config" | jq -r '.url // empty' 2>/dev/null)

  if [ -z "$cmd" ] && [ -z "$url" ]; then
    emit "no-transport@${source_label}@${name}" \
      "[mcp-config-drift] ${safe_label} server '${safe_name}' declares neither 'command' (stdio) nor 'url' (http/sse/ws). Claude Code cannot start it."
    return
  fi

  # Pull the entire config back out as a flat string so a single pass of
  # extract_env_refs covers command, args, env values, headers values,
  # and url. We intentionally only look at .values of `env` and `headers`
  # — the keys themselves are not env vars to resolve.
  local searchable
  searchable=$(printf '%s' "$config" \
    | jq -r '
        [
          (.command // ""),
          ((.args // [])[]),
          ((.env // {} | to_entries[] | .value)),
          ((.headers // {} | to_entries[] | .value)),
          (.url // "")
        ] | join(" ")
      ' 2>/dev/null || true)

  local refs
  refs=$(extract_env_refs "$searchable")

  local ref
  for ref in $refs; do
    if ! env_is_set "$ref"; then
      emit "unset-env@${source_label}@${name}@${ref}" \
        "[mcp-config-drift] ${safe_label} server '${safe_name}' references env var \$${ref} but it is not set in the current shell. Set it in your shell startup (or .env), then restart Claude Code."
    fi
  done
}

# Iterate every server in a JSON file's `mcpServers` (or top-level if the
# whole file IS the servers map — `.mcp.json` is the latter shape).
iterate_servers() {
  local file="$1" key_path="$2"  # key_path is ".mcpServers" or "."
  local entries
  entries=$(jq -c "${key_path} // {} | to_entries[]" "$file" 2>/dev/null) || return 0
  [ -z "$entries" ] && return 0

  # Read line-by-line. Server names with whitespace (allowed) survive
  # because we never word-split — we feed jq each whole line.
  while IFS= read -r entry; do
    [ -z "$entry" ] && continue
    local name config
    name=$(printf '%s' "$entry" | jq -r '.key' 2>/dev/null) || continue
    config=$(printf '%s' "$entry" | jq -c '.value' 2>/dev/null) || continue
    [ -z "$name" ] && continue
    [ "$config" = "null" ] && continue
    check_server "$file" "$name" "$config"
  done <<< "$entries"
}

# Tracking-status check: `.mcp.json` should be either git-tracked OR
# explicitly gitignored. Anything else is an ambiguous configuration that
# typically results in either (a) a teammate not getting the server they
# expected (it never made it into the repo) or (b) a personal token
# accidentally being committed on the next `git add .`.
check_mcp_json_tracking() {
  local file="$1"
  local rel
  rel=$(basename "$file")
  [ -f "$file" ] || return 0

  cd "$(resolve_project_root)" 2>/dev/null || return 0
  git rev-parse --git-dir >/dev/null 2>&1 || {
    log_line mcp-config-drift "not a git repo — skipping tracking check for $rel"
    return 0
  }

  if git ls-files --error-unmatch -- "$rel" >/dev/null 2>&1; then
    return 0   # tracked → project scope, clear
  fi

  if git check-ignore -q -- "$rel" 2>/dev/null; then
    return 0   # gitignored → local scope, clear
  fi

  emit "tracking-ambig@${rel}" \
    "[mcp-config-drift] ${rel} exists but is neither git-tracked nor gitignored — its scope is ambiguous. Decide: 'git add ${rel}' to share with the team (project scope), or add '/${rel}' to .gitignore for personal MCP config (local scope, won't leak personal tokens)."
}

main() {
  command -v jq >/dev/null 2>&1 || {
    log_line mcp-config-drift "jq not in PATH — skipping"
    return
  }

  local root
  root=$(resolve_project_root)

  # 1. Project-root .mcp.json
  local mcp_json="$root/.mcp.json"
  if [ -f "$mcp_json" ]; then
    if ! jq empty "$mcp_json" 2>/dev/null; then
      emit "invalid-json@.mcp.json" \
        "[mcp-config-drift] .mcp.json is invalid JSON — Claude Code silently skips files it cannot parse. Run 'jq . .mcp.json' locally to find the parse error."
    else
      iterate_servers "$mcp_json" '.mcpServers'
    fi
    check_mcp_json_tracking "$mcp_json"
  fi

  # 2. Project-scope .claude/settings.json (committed)
  local proj_settings="$root/.claude/settings.json"
  if [ -f "$proj_settings" ]; then
    if jq empty "$proj_settings" 2>/dev/null; then
      iterate_servers "$proj_settings" '.mcpServers'
    else
      emit "invalid-json@.claude/settings.json" \
        "[mcp-config-drift] .claude/settings.json is invalid JSON. Run 'jq . .claude/settings.json' to find the parse error."
    fi
  fi

  # 3. Local-scope .claude/settings.local.json (gitignored)
  local local_settings="$root/.claude/settings.local.json"
  if [ -f "$local_settings" ]; then
    if jq empty "$local_settings" 2>/dev/null; then
      iterate_servers "$local_settings" '.mcpServers'
    else
      emit "invalid-json@.claude/settings.local.json" \
        "[mcp-config-drift] .claude/settings.local.json is invalid JSON. Run 'jq . .claude/settings.local.json' to find the parse error."
    fi
  fi

  rotate_log_if_big mcp-config-drift
}

main
exit 0
