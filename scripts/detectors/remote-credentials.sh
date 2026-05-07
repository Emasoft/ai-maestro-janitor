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

# Decide whether a remote URL embeds a credential. We flag two patterns:
#
#   Pattern A — explicit basic-auth: `scheme://user:secret@host/...`
#               with a non-empty password component after the `:`.
#               Matches the historical "username + password" format.
#
#   Pattern B — token-as-username over HTTP(S):
#               `https://<token>@host/...` or `http://<token>@host/...`.
#               This is the canonical GitHub Personal Access Token form
#               (`https://ghp_xxxxxx@github.com/owner/repo.git`) and the
#               GitHub Apps installation-token form
#               (`https://x-access-token:<token>@github.com/...` — that
#               variant is already caught by Pattern A). Some Bitbucket
#               and GitLab token flows also use this shape.
#
# We deliberately do NOT flag Pattern B for `ssh://` because `ssh://git@host`
# is the legitimate SSH form (the `git` user component carries no secret).
# Pattern A still catches `ssh://user:password@host/` (rare but a real leak).
has_password_in_url() {
  local url="$1"
  # Pattern A: any URL with `:non-empty-password@` in the userinfo
  if [[ "$url" =~ ^[a-zA-Z][a-zA-Z0-9+.-]*://[^/@]*:[^@/]+@[^/]+ ]]; then
    return 0
  fi
  # Pattern B: HTTP(S)-only — any non-empty userinfo without a colon. The
  # userinfo character class excludes `:` (so we don't double-match A) and
  # `@` and `/` (so we stop at the userinfo→host boundary).
  if [[ "$url" =~ ^https?://[^:@/]+@[^/]+ ]]; then
    return 0
  fi
  return 1
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
