# Pattern catalog for the janitor's second-pass workflow auditor.
#
# Each entry maps a rule_id to (pattern, severity, description). The
# patterns are deliberately simpler than zizmor's full rule engine —
# they're a fast pre-check the doctor runs IN ADDITION to zizmor's own
# SARIF output to catch the janitor-extension recipes (jq-arg-trap and
# friends) plus a few high-signal mirrors of common zizmor rules.
#
# All current patterns are RE2-compatible (no lookaround, no backrefs).
# When a future pattern needs lookaround / backreferences, set
# PATTERN_FALLBACK_FLAGS[rule_id] = False and the classifier will route
# that single pattern to the Python re fallback bucket while keeping
# every other pattern on the fast RE2 RegexSet path.

from __future__ import annotations

# rule_id → (pattern, severity, description)
PATTERNS: dict[str, tuple[str, str, str]] = {
    # janitor-extension recipes (not in upstream zizmor catalogue).
    "jq-arg-trap": (
        r"jq[^\n]{0,200}--arg[^\n]{0,200}\$\{\{",
        "MAJOR",
        "jq --arg used with a ${{ }} expression — the shell expands the "
        "expression BEFORE jq sees the value, defeating --arg's purpose. "
        "Move the expression to an env: key and reference $ENV_VAR.",
    ),
    # zizmor-mirror recipes — fast pre-screen so the doctor surfaces a
    # finding immediately if zizmor is unavailable. zizmor's own SARIF
    # output is the authoritative source when present; these patterns
    # are advisory under the second pass.
    "unpinned-uses-tag": (
        r"uses:\s+[\w.-]+/[\w.-]+@(?:v?\d+(?:\.\d+){0,2}|main|master|HEAD)\s*(?:#.*)?$",
        "MAJOR",
        "third-party action pinned to a version tag or branch instead of "
        "a full commit SHA. Resolve via 'gh api repos/<repo>/commits/<tag>' "
        "and replace with the SHA, preserving '# v<tag>' as a comment.",
    ),
    "unpinned-docker-image": (
        r"(?:docker://[^\n]*:latest|image:[^\n]*:latest|uses:[^\n]*:latest|container:[^\n]*:latest)",
        "MAJOR",
        "a Docker image pinned to the mutable :latest tag — pin to "
        "@sha256:<digest>.",
    ),
    "dangerous-triggers-pr-target": (
        r"^\s*pull_request_target\s*:",
        "HIGH",
        "pull_request_target runs with base-repo secrets and write scope; "
        "verify the workflow does not check out fork code.",
    ),
    "secrets-inherit": (
        r"\bsecrets\s*:\s*inherit\b",
        "MINOR",
        "secrets: inherit hands EVERY secret to the called workflow. "
        "Replace with an explicit mapping listing only what it needs.",
    ),
    "ref-confusion-in-run": (
        # Require the match to be inside (or shortly after) a `run:` block.
        # The 0-to-400 character window between `run:` and the interpolation
        # is enough for multi-line block scalars without crossing into the
        # next step. Concurrency / env / if blocks no longer false-positive.
        r"run:[ \t]*[|>][^\n]*\n(?:[\s\S]{0,400}?)\$\{\{\s*github\.ref\s*\}\}",
        "MINOR",
        "github.ref interpolated inside a run: block — prefer $GITHUB_REF "
        "(env var indirection) so untrusted ref input cannot break shell "
        "quoting. The concurrency:/env:/if: contexts are unaffected.",
    ),
    "unsound-contains": (
        r"contains\s*\(\s*[\w.\[\]'\"+-]+\s*,\s*['\"][^'\"]+['\"]\s*\)",
        "MINOR",
        "contains() used where == or startsWith would be safer and clearer "
        "for an identity-based comparison.",
    ),
    "secret-env-bare-in-run": (
        # Multi-line `run: |` block followed by a `${{ secrets.X }}` reference.
        # The `[\s\S]*?` non-greedy "any content" works under both RE2 and
        # Python re (RE2 supports `[\s\S]*` natively; lookahead is avoided).
        r"run:[ \t]*[|>][^\n]*\n(?:[\s\S]{0,400}?)\$\{\{\s*secrets\.",
        "HIGH",
        "${{ secrets.* }} interpolated inside a run: block (multi-line OK). "
        "Route the secret through an env: key on the step and reference "
        "$ENV_VAR — never let secrets touch the shell directly.",
    ),
    "github-env-write-with-expr": (
        r"echo[^\n]*\$\{\{[^}]+}}[^\n]*>>\s*\"?\$(?:GITHUB_ENV|GITHUB_OUTPUT)\"?",
        "HIGH",
        "Writing to $GITHUB_ENV / $GITHUB_OUTPUT with a ${{ }} expression "
        "embedded in the value. Route the expression through env: first.",
    ),
    # Sentinel-port regex-tier rules (mirrors of the security-scanner
    # detection corpus). All RE2-safe: no lookaround, no backrefs; only
    # inline (?i:...) scoped flags where case-insensitivity is needed.
    "hardcoded-secrets": (
        r"(?:AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82}|gho_[A-Za-z0-9]{36}|ghs_[A-Za-z0-9]{36}|-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----|hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+|(?i:api[_-]?key|apikey|secret[_-]?key|auth[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9]{30,}['\"])",
        "CRITICAL",
        "a hardcoded AWS key / GitHub token / private key / Slack webhook / "
        "API key — move it to ${{ secrets.NAME }}.",
    ),
    "ide-config-injection": (
        r"(?:echo|cat|tee|printf|cp|mv|install|sed|>|>>)[^\n]*\.(?:claude|vscode|cursor)/",
        "CRITICAL",
        "workflow writes to an IDE/AI agent config dir (.claude/.vscode/"
        ".cursor) — these auto-execute code on project open; remove or "
        "validate before writing.",
    ),
    "curl-pipe-shell": (
        r"(?:curl\s[^\n]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh|source|\.)|wget\s[^\n]*-O\s*-\s*\|\s*(?:sudo\s+)?(?:sh|bash|zsh))",
        "HIGH",
        "remote script piped to a shell with no integrity check — download, "
        "verify checksum, then run, or use a pinned action.",
    ),
    "git-config-global": (
        r"git config --global[^\n]*(?:insteadOf|url\.|credential)",
        "MINOR",
        "git config --global writes credentials to ~/.gitconfig (visible to "
        "every later git op) — use --local.",
    ),
    "github-dependency-refs": (
        r"(?:npm|pnpm|yarn|bun)\s+(?:install|add)\s+[^\n]*(?:github:|git\+https://github\.com)",
        "MAJOR",
        "package installed from a GitHub commit/branch ref bypasses registry "
        "integrity — install from the registry.",
    ),
    "jq-arg-escape-sequences": (
        r"jq\s[^\n]*--arg\s+\w+\s+\"[^\"]*\\[nt\\][^\"]*\"",
        "MAJOR",
        "jq --arg treats the value as a raw literal, so \\n/\\t stay literal "
        "backslash sequences — use real newlines or --argjson.",
    ),
}

# Per-pattern toggle: True if the pattern is safe for RE2 (no lookaround
# or backreferences). Patterns flagged False are forced through the
# Python re fallback path even when google-re2 is available.
#
# Every current pattern is RE2-safe by construction; this dict is kept
# explicit so a future contributor adding a (?=...) / (?!...) / \1
# pattern remembers to flip the flag and document why.
PATTERN_FALLBACK_FLAGS: dict[str, bool] = {rule_id: True for rule_id in PATTERNS}
