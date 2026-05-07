#!/usr/bin/env bash
# Remote-credentials detector — flags git remotes whose URL embeds a password
# in the userinfo component (e.g. `https://user:token@github.com/...`). These
# leak the secret into:
#   * `git remote -v` output (visible in screen-shares, paste-bins, CI logs)
#   * any clone of the repo that copies the local config
#   * shell history when the URL was set via `git remote add`
#
# Detection is intentionally cheap (one `git remote -v`, no network) and the
# nudge is unconditional — there is no legitimate reason to keep credentials
# in a remote URL when SSH keys, OAuth tokens via the credential helper, or a
# `~/.netrc` entry all do the same job without leaking.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=../lib/state.sh
source "$HERE/../lib/state.sh"
# shellcheck source=../lib/dedupe.sh
source "$HERE/../lib/dedupe.sh"
init_state

SEEN="$STATE_DIR/remote-credentials-seen.txt"

# Strip credentials from a URL of the form `scheme://user:pass@host/...`,
# producing `scheme://host/...`. POSIX-portable; no python/perl required.
strip_userinfo() {
  local url="$1"
  printf '%s' "$url" | sed -E 's#^([a-zA-Z][a-zA-Z0-9+.-]*://)([^/@]*@)?#\1#'
}

# Match `scheme://...:something@host` where `something` is non-empty. Plain
# user-only (`scheme://user@host`) is allowed because that is the standard
# SSH form for the user component (e.g. `git@github.com`); it carries no
# secret. The userinfo regex below requires a `:` followed by at least one
# non-`@` char before the `@`, which matches passwords/tokens but not bare
# usernames.
has_password_in_url() {
  local url="$1"
  [[ "$url" =~ ^[a-zA-Z][a-zA-Z0-9+.-]*://[^/@]*:[^@/]+@[^/]+ ]]
}

main() {
  git rev-parse --git-dir >/dev/null 2>&1 || {
    log_line remote-credentials "not a git repo — skipping"
    return
  }

  local seen_remotes=""
  while IFS=$'\t' read -r name url _direction; do
    [ -z "$name" ] && continue
    [ -z "$url" ] && continue

    # `git remote -v` lists each remote twice (fetch + push). Skip the second
    # row for the same name+url pair so we don't double-emit.
    local key="${name}@${url}"
    case " $seen_remotes " in
      *" $key "*) continue ;;
    esac
    seen_remotes="$seen_remotes $key"

    has_password_in_url "$url" || continue

    local clean_url
    clean_url=$(strip_userinfo "$url")
    local safe_name safe_clean
    safe_name=$(printf '%q' "$name")
    safe_clean=$(printf '%q' "$clean_url")

    # Use a hash of url+name as the dedup key so rotating the secret (which
    # changes the URL) re-fires the alert with the new value.
    local fp
    fp=$(printf '%s' "$key" | cksum | awk '{print $1}')

    emit_once "$SEEN" "creds@${name}@${fp}" \
      "[remote-credentials] URGENT: git remote '${name}' embeds a secret in its URL — anyone with read access to the repo, CI logs, or your screen can see it. Strip with: git remote set-url ${safe_name} ${safe_clean}. Then rotate the leaked credential immediately."
  done < <(git remote -v 2>/dev/null \
              | awk '{print $1"\t"$2"\t"$3}' \
              || true)

  rotate_log_if_big remote-credentials
}

main
exit 0
