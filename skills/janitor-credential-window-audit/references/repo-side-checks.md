# Repo-side credential checks

File-system checks the credential-window auditor runs against the project root. The audit reads only — it never edits `.gitignore`, never deletes a token file, never calls `gh secret set`. Findings are surfaced with copy-paste remediation recipes the user applies themselves.

## Table of contents

- [Check matrix](#check-matrix) — one row per check, with severity and remediation.
- [Per-check detail](#per-check-detail) — `.env`, dotfiles, plaintext token files, scanner config.
- [Value-leak guardrail](#value-leak-guardrail) — the auditor MUST NOT capture a secret value anywhere.

## Check matrix

| Check | Severity | Remediation recipe (user runs) |
|---|---|---|
| `.env` exists AND not in `.gitignore` | CRITICAL | `echo '.env' >> .gitignore && git rm --cached .env && git commit -m "chore: gitignore .env"` |
| `.env.*` (e.g. `.env.local`, `.env.production`) NOT in `.gitignore` | CRITICAL | `echo '.env.*' >> .gitignore && git rm --cached .env.* && git commit -m "chore: gitignore .env.*"` |
| `.npmrc` in repo NOT gitignored AND contains `_authToken` / `_password` | CRITICAL | Move to `~/.npmrc` (gitignored by default at home). Use env-var indirection: `//registry/:_authToken=${NPM_TOKEN}` |
| `~/.npmrc` contains a plaintext `_authToken` | HIGH | Switch to `gh auth token` or a secrets manager; never hold a long-lived registry token in a dotfile |
| `~/.netrc` exists with `password` field | HIGH | Replace with `gh auth login` / per-tool credential helper; rotate the leaked password |
| `~/.gitconfig` has `credential.helper = store` (or `[credential] helper = store`) | HIGH | Switch to `credential.helper = osxkeychain` (macOS) / `manager` (Windows) / `cache --timeout=3600` (Linux). `git config --global --unset credential.helper && git config --global credential.helper osxkeychain` |
| Plaintext file matching `*token*`, `*secret*`, `*credentials*`, `*.key` (excluding test fixtures and gitignored paths) NOT gitignored | HIGH | Move to a secrets manager. If a fixture, rename to `*.example.*` and gitignore the real file |
| Same name heuristic but file IS gitignored | LOW | Confirm intent in the report only — no action |
| `.gitleaks.toml` AND `.trufflehog/` BOTH missing | LOW | Suggest installing one as a pre-commit hook: `pre-commit install && pre-commit run gitleaks --all-files` |

## Per-check detail

### .env discovery

```bash
find . -maxdepth 3 -type f \( -name '.env' -o -name '.env.*' \) \
  -not -path './node_modules/*' -not -path './.git/*' \
  -not -path './.venv/*' -not -path './.trashcan/*' \
  -print0 | while IFS= read -r -d '' f; do
  rel="${f#./}"
  if git check-ignore -q "$rel" 2>/dev/null; then
    echo "OK gitignored: $rel"
  else
    echo "CRITICAL not-gitignored: $rel"
  fi
done
```

The auditor reports the PATH only. It never opens the `.env` file — opening risks transcript capture of the value.

### Dotfile token persistence

| File | Detection |
|---|---|
| `<repo>/.npmrc` | `git check-ignore .npmrc` AND `grep -lE '_(authToken\|password)' .npmrc` (NAME only, value ignored) |
| `~/.npmrc` | `grep -lE '_(authToken\|password)' ~/.npmrc 2>/dev/null` |
| `~/.netrc` | `grep -lE '^[[:space:]]*password' ~/.netrc 2>/dev/null` |
| `~/.gitconfig::credential.helper=store` | `git config --global --get credential.helper` returns `store` |

For each match, the report records the file path and the field NAME (`_authToken`, `password`, etc.). The matched LINE is not captured.

### Plaintext token-file heuristic

Patterns the auditor walks (case-insensitive) under the project root:

- `*token*`
- `*secret*`
- `*credentials*`
- `*.key` (excludes `*.pub.key`, `*.public.key`)
- `*.pem` (when not in a documented `certs/` or `keys/` ignored directory)

Exclusions (false-positive suppression):

- `node_modules/`, `.git/`, `.venv/`, `dist/`, `build/`, `.trashcan/`, `vendor/`
- Files matching `*.example.*`, `*.sample.*`, `*.template.*`, `*.test.*`, `*.spec.*`
- Files in `tests/fixtures/`, `__fixtures__/`, `e2e/fixtures/`

```bash
find . -type f \( -iname '*token*' -o -iname '*secret*' -o -iname '*credentials*' -o -iname '*.key' \) \
  -not -path './node_modules/*' -not -path './.git/*' \
  -not -path './.venv/*' -not -path './dist/*' -not -path './build/*' \
  -not -path './.trashcan/*' -not -path './vendor/*' \
  -not -iname '*.example.*' -not -iname '*.sample.*' -not -iname '*.template.*' \
  -not -iname '*.test.*' -not -iname '*.spec.*' \
  -print
```

For each hit, test `git check-ignore`. Not gitignored → HIGH. Gitignored → LOW (report-only).

### Secret-scanner config presence

```bash
test -f .gitleaks.toml && echo "gitleaks: configured" || echo "gitleaks: missing"
test -d .trufflehog || test -f .trufflehog.yml && echo "trufflehog: configured" || echo "trufflehog: missing"
```

If BOTH are missing → LOW finding suggesting a pre-commit hook. The auditor does not install one.

## Value-leak guardrail

CRITICAL invariant for the implementation: at no point does the auditor capture a secret VALUE in any of:

- the report file content
- stdout / stderr
- intermediate scratch files
- environment variable export back to the caller

If a check would require reading the value to classify it, the check is SKIPPED and reported as `[VALUE-NEEDED] <path>` for the user to inspect manually. There is no exception. Tripping this guardrail aborts the report write with `[FAILED] value leak guardrail tripped`.
