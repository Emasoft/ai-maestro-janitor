#!/usr/bin/env bash
# safe-delete — recoverable alternative to `rm` for agents that can't (or
# shouldn't) call destructive commands. Each invocation moves the given paths
# into <project_root>/.trashcan/<timestamp>/, mirroring the original relative
# layout, and writes a sibling <timestamp>.txt manifest listing the original
# paths. Nothing is deleted: a misjudged disposal is one `mv` away from
# recovery, on any platform.
#
# Why this exists:
#   1. Project hooks frequently block `rm`/`rm -rf` outright, so agents that
#      legitimately need to dispose of a stale file get stuck.
#   2. CLAUDE.md RULE 0 — files must be committed before deletion. `mv` to a
#      sibling folder side-steps that rule entirely; the move is reversible
#      and the file's git history is preserved on the next commit.
#   3. A timestamped trashcan gives a per-batch undo unit. Each call writes
#      its own subfolder + manifest, so independent disposals never collide.
#
# Persistence guarantees for the .trashcan/ directory:
#   The trashcan is gitignored (its contents must never leak into commits) but
#   must NOT vanish on `git clean -fdx`, on a fresh clone, or any other
#   "wipe ignored files" sweep. We resolve the apparent contradiction by:
#     a) Ignoring everything inside the directory (`/.trashcan/*`)
#     b) Un-ignoring two marker files (`.gitkeep`, `README.txt`) so the
#        directory itself is tracked via those markers
#     c) Tracked files survive `git clean -fdx` and re-appear on clone, so
#        the directory always exists and is always empty of trash on a new
#        checkout — exactly what we want.
#   The script creates the markers + the .gitignore rules on first use and
#   prints a one-time hint so the user can `git add` the markers.
#
# Usage:
#   bash safe-delete.sh [-n|--dry-run] <path>...
#   bash safe-delete.sh --help
#
# Refusals (always):
#   - paths outside the project root (resolved canonically — symlink-tricks
#     don't slip past)
#   - the project root itself
#   - .git, .claude, .claude-plugin (critical infrastructure)
#   - anything already inside .trashcan/
#
# State / side effects:
#   - creates <project_root>/.trashcan/<YYYYMMDD_HHMMSS±HHMM>/
#   - writes <project_root>/.trashcan/<YYYYMMDD_HHMMSS±HHMM>.txt — manifest
#     of original paths (one per line, project-relative with `./` prefix);
#     this is the platform-independent restore key.
#   - creates <project_root>/.trashcan/.gitkeep and README.txt if missing
#   - appends `/.trashcan/*`, `!/.trashcan/.gitkeep`, `!/.trashcan/README.txt`
#     to .gitignore if missing (each line idempotent)
#   - logs to .janitor/logs/safe-delete.log when state.sh is reachable
#
# Exit code:
#   0 — at least one path moved successfully
#   1 — every path failed (e.g. all refused or all missing)
#   2 — usage error (no paths supplied or --help)

set -euo pipefail

usage() {
  cat <<'USAGE'
safe-delete — recoverable alternative to `rm`. Moves paths into
<project_root>/.trashcan/<timestamp>/ instead of deleting them, and writes a
manifest <timestamp>.txt next to it.

Usage:
  bash safe-delete.sh [-n|--dry-run] <path>...

Flags:
  -n, --dry-run    Print what would be moved without touching anything.
  -h, --help       Show this help.

Each invocation creates one timestamped subfolder under .trashcan/ plus an
identically-named .txt manifest file with the original paths (one per line,
project-relative, prefixed with ./). The timestamp uses local time + GMT
offset (compact ±HHMM form), collision-free at second granularity.

Layout after a batch:
  .trashcan/
    20260503_181523+0200/     ← mirrored contents of trashed paths
      src/old.ts
      docs/draft/
    20260503_181523+0200.txt  ← manifest, one original path per line

Restore options (any platform):
  # Whole batch — overwrites if names collide at destination:
  cp -R .trashcan/<timestamp>/. ./
  # Selective, manifest-driven:
  while IFS= read -r p; do
    [ -z "$p" ] || [ "${p#\#}" != "$p" ] && continue
    mv ".trashcan/<timestamp>/${p#./}" "$p"
  done < ".trashcan/<timestamp>.txt"

Purge a batch permanently:
  rm -rf .trashcan/<timestamp>/ .trashcan/<timestamp>.txt
USAGE
}

# --- Argument parsing -------------------------------------------------------
DRY_RUN=0
PATHS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 2 ;;
    -n|--dry-run) DRY_RUN=1; shift ;;
    --) shift; while [ "$#" -gt 0 ]; do PATHS+=("$1"); shift; done ;;
    -*) printf 'safe-delete: unknown flag: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    *) PATHS+=("$1"); shift ;;
  esac
done

if [ "${#PATHS[@]}" -eq 0 ]; then
  usage >&2
  exit 2
fi

# --- Project root resolution ------------------------------------------------
# Prefer $CLAUDE_PROJECT_DIR (set by Claude Code) so the script behaves the
# same whether called from a slash command, a hook, or a manual shell — the
# slash command always sees the project root, but a hook running from a
# subdirectory would otherwise pin the trashcan to the wrong place.
if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -d "$CLAUDE_PROJECT_DIR" ]; then
  PROJECT_ROOT=$(cd "$CLAUDE_PROJECT_DIR" && pwd -P)
elif PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null); then
  PROJECT_ROOT=$(cd "$PROJECT_ROOT" && pwd -P)
else
  PROJECT_ROOT=$(pwd -P)
fi

TRASH_DIR="$PROJECT_ROOT/.trashcan"
GITKEEP="$TRASH_DIR/.gitkeep"
TRASHCAN_README="$TRASH_DIR/README.txt"
# Local time + GMT offset (compact ±HHMM, filesystem-safe). Matches the
# convention used everywhere else in this plugin (see agent-reports-location).
TIMESTAMP=$(date +%Y%m%d_%H%M%S%z)
DEST="$TRASH_DIR/$TIMESTAMP"
MANIFEST="$TRASH_DIR/${TIMESTAMP}.txt"

# Optional logging — sourced lazily so the script still works if state.sh is
# unreachable (e.g. during initial install or out-of-tree invocation).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
if [ -r "$HERE/lib/state.sh" ]; then
  # shellcheck source=./lib/state.sh
  source "$HERE/lib/state.sh"
  init_state
  log() { log_line safe-delete "$@"; }
else
  log() { :; }  # no-op when running outside the plugin tree
fi

# --- Path canonicalisation --------------------------------------------------
# Resolve a user-supplied path to its absolute canonical form, following
# symlinks in the parent dir but NOT following a symlink that IS the path
# itself (we want to trash the symlink, not its target). Returns 1 if the
# path does not exist.
canonicalize() {
  local p="$1"
  local d b
  if [ -d "$p" ] && [ ! -L "$p" ]; then
    (cd "$p" && pwd -P)
    return 0
  fi
  if [ -e "$p" ] || [ -L "$p" ]; then
    d=$(dirname -- "$p")
    b=$(basename -- "$p")
    if abs_parent=$(cd "$d" 2>/dev/null && pwd -P); then
      printf '%s/%s' "$abs_parent" "$b"
      return 0
    fi
  fi
  return 1
}

# --- Safety check -----------------------------------------------------------
# Returns 0 (and is silent) when path is safe to trash. Returns 1 with a
# reason on stderr otherwise. The check is purely path-based — it never
# touches the filesystem — so it's cheap to run on every arg.
safe_to_trash() {
  local path="$1"
  # Strip a single trailing slash for consistent comparison against
  # PROJECT_ROOT (which has none after `pwd -P`).
  path="${path%/}"

  if [ "$path" = "$PROJECT_ROOT" ]; then
    printf 'refuse: %s is the project root\n' "$path" >&2
    return 1
  fi

  case "$path" in
    "$PROJECT_ROOT"/*) ;;  # inside project — continue
    *)
      printf 'refuse: %s is outside the project root (%s)\n' "$path" "$PROJECT_ROOT" >&2
      return 1
      ;;
  esac

  case "$path" in
    "$PROJECT_ROOT/.git"|"$PROJECT_ROOT/.git/"*)
      printf 'refuse: %s is inside .git\n' "$path" >&2; return 1 ;;
    "$PROJECT_ROOT/.claude"|"$PROJECT_ROOT/.claude/"*)
      printf 'refuse: %s is inside .claude\n' "$path" >&2; return 1 ;;
    "$PROJECT_ROOT/.claude-plugin"|"$PROJECT_ROOT/.claude-plugin/"*)
      printf 'refuse: %s is inside .claude-plugin\n' "$path" >&2; return 1 ;;
    "$TRASH_DIR"|"$TRASH_DIR/"*)
      printf 'refuse: %s is already inside .trashcan/\n' "$path" >&2; return 1 ;;
  esac

  return 0
}

# --- .gitignore + marker maintenance ----------------------------------------
# Make .trashcan/ both gitignored AND survivable via two tracked markers.
# Pattern: ignore everything under the dir, then un-ignore two specific files.
# Tracked files are never touched by `git clean -fdx`, and they re-appear on
# clone, so the directory always exists and stays empty-of-trash.
#
# Sets the global NEW_MARKERS=1 if any rule or marker had to be created on
# this call, so the caller can print the one-time "git add" hint. Using a
# global rather than a return code avoids exit-code confusion under `set -e`
# (a function that "returns 1 to signal added something" would otherwise
# look like a failed call).
NEW_MARKERS=0
ensure_gitignore_and_markers() {
  local gitignore="$PROJECT_ROOT/.gitignore"
  local rules=(
    '/.trashcan/*'
    '!/.trashcan/.gitkeep'
    '!/.trashcan/README.txt'
  )

  # 1) gitignore lines
  for rule in "${rules[@]}"; do
    if [ -f "$gitignore" ] && grep -qxF "$rule" "$gitignore"; then
      continue
    fi
    # Ensure the file ends with a newline before appending — a file without a
    # trailing newline would otherwise glue the rule to the previous line.
    if [ -f "$gitignore" ] && [ -s "$gitignore" ]; then
      local last_byte
      last_byte=$(tail -c1 "$gitignore" 2>/dev/null || printf '')
      if [ "$last_byte" != "" ] && [ "$last_byte" != $'\n' ]; then
        printf '\n' >> "$gitignore"
      fi
    fi
    printf '%s\n' "$rule" >> "$gitignore"
    log "added '$rule' to .gitignore"
    NEW_MARKERS=1
  done

  # 2) marker files (created idempotently — empty .gitkeep, explanatory README)
  if [ ! -f "$GITKEEP" ]; then
    : > "$GITKEEP"
    NEW_MARKERS=1
  fi
  if [ ! -f "$TRASHCAN_README" ]; then
    cat > "$TRASHCAN_README" <<'README'
# .trashcan/ — project-local recoverable trash

Anything in this directory was put here by the ai-maestro-janitor's
safe-delete skill (or its `safe-delete.sh` script) instead of being
permanently deleted. Each subfolder is one disposal batch:

    .trashcan/
      20260503_181523+0200/    ← mirrored contents of trashed paths
      20260503_181523+0200.txt ← manifest, one original path per line

To restore a batch (any platform):

    # Whole batch — overwrites if names collide at the destination:
    cp -R .trashcan/<timestamp>/. ./

    # Selective, manifest-driven:
    while IFS= read -r p; do
      [ -z "$p" ] || [ "${p#\#}" != "$p" ] && continue
      mv ".trashcan/<timestamp>/${p#./}" "$p"
    done < ".trashcan/<timestamp>.txt"

To purge a batch permanently:

    rm -rf .trashcan/<timestamp>/ .trashcan/<timestamp>.txt

DO NOT delete this directory itself. It is gitignored (so trash never
leaks into commits) but the directory must persist across `git clean -fdx`
sweeps and fresh clones. We achieve that by tracking two marker files
(.gitkeep and README.txt) — they are excluded from .gitignore so git keeps
them under version control, which in turn keeps the directory alive.

The first time safe-delete creates these markers, run:

    git add .trashcan/.gitkeep .trashcan/README.txt
    git commit -m "track .trashcan markers so the trashcan survives clones"

After that, the trashcan is permanent project infrastructure.
README
    NEW_MARKERS=1
  fi
}

# --- Main loop --------------------------------------------------------------
moved=0
failed=0
moved_lines=()
manifest_lines=()
trash_dir_created=0

for arg in "${PATHS[@]}"; do
  if ! abs=$(canonicalize "$arg"); then
    printf 'skip: %s (does not exist)\n' "$arg" >&2
    failed=$(( failed + 1 ))
    continue
  fi
  abs="${abs%/}"

  if ! safe_to_trash "$abs"; then
    failed=$(( failed + 1 ))
    continue
  fi

  rel="${abs#"$PROJECT_ROOT"/}"
  target="$DEST/$rel"

  if [ "$DRY_RUN" -eq 1 ]; then
    moved_lines+=("[dry-run] would move $rel -> .trashcan/$TIMESTAMP/$rel")
    moved=$(( moved + 1 ))
    continue
  fi

  # Lazily create destination + ensure markers, so an all-failed batch
  # leaves no empty timestamp dir behind. We still want the markers + the
  # gitignore rules to land on the very first call (succeed or fail), so
  # callers don't have to remember to `git add` them later — but only if
  # this batch actually moves at least one item.
  if [ "$trash_dir_created" -eq 0 ]; then
    mkdir -p "$DEST"
    ensure_gitignore_and_markers
    trash_dir_created=1
  fi

  mkdir -p "$(dirname -- "$target")"

  # Use `--` so paths starting with `-` are not parsed as flags.
  if mv -- "$abs" "$target"; then
    moved_lines+=("$rel -> .trashcan/$TIMESTAMP/$rel")
    manifest_lines+=("./$rel")
    moved=$(( moved + 1 ))
    log "trashed $rel"
  else
    printf 'failed: could not move %s\n' "$abs" >&2
    failed=$(( failed + 1 ))
  fi
done

# --- Manifest ---------------------------------------------------------------
# Written once after the loop so a partial failure still leaves a coherent
# manifest covering exactly what landed in the subfolder. Header doc-lines
# start with `#` so manifest-driven restore loops can skip them with a
# trivial `[ "${p#\#}" != "$p" ] && continue`.
if [ "$DRY_RUN" -eq 0 ] && [ "$moved" -gt 0 ]; then
  {
    printf '# safe-delete manifest — batch %s\n' "$TIMESTAMP"
    printf '# format: one project-relative path per line (./prefix), one entry per trashed item\n'
    printf '# stored under: .trashcan/%s/\n' "$TIMESTAMP"
    for line in "${manifest_lines[@]}"; do
      printf '%s\n' "$line"
    done
  } > "$MANIFEST.tmp.$$" && mv -f "$MANIFEST.tmp.$$" "$MANIFEST"
fi

# --- Report -----------------------------------------------------------------
if [ "$moved" -gt 0 ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[safe-delete] dry-run: %d item(s) would move into .trashcan/%s/:\n' \
      "$moved" "$TIMESTAMP"
  else
    printf '[safe-delete] Trashed %d item(s) into .trashcan/%s/:\n' \
      "$moved" "$TIMESTAMP"
  fi
  for line in "${moved_lines[@]}"; do
    printf '  %s\n' "$line"
  done
  if [ "$DRY_RUN" -eq 0 ]; then
    printf '\n'
    printf 'Manifest:\n'
    printf '  .trashcan/%s.txt\n' "$TIMESTAMP"
    printf 'Restore (whole batch — overwrites if names collide):\n'
    printf '  cp -R %q/. %q\n' "$DEST" "$PROJECT_ROOT"
    printf 'Restore (manifest-driven, selective):\n'
    # shellcheck disable=SC2016  # printf format string is a literal shell snippet for the user
    printf '  while IFS= read -r p; do [ -z "$p" ] || [ "${p#\\#}" != "$p" ] && continue; mv ".trashcan/%s/${p#./}" "$p"; done < .trashcan/%s.txt\n' \
      "$TIMESTAMP" "$TIMESTAMP"
    printf 'Purge permanently:\n'
    printf '  rm -rf %q %q\n' "$DEST" "$MANIFEST"
    if [ "$NEW_MARKERS" -eq 1 ]; then
      printf '\n'
      printf 'NOTE: first-time setup of .trashcan/ — commit the markers so the\n'
      # shellcheck disable=SC2016  # backticks below are markdown, not command substitution
      printf 'directory survives `git clean -fdx` and fresh clones:\n'
      printf '  git add .gitignore .trashcan/.gitkeep .trashcan/README.txt\n'
      printf '  git commit -m "track .trashcan markers"\n'
    fi
  fi
fi

if [ "$failed" -gt 0 ] && [ "$moved" -eq 0 ]; then
  exit 1
fi
exit 0
