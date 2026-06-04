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

import re as _re_mod

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
        r"echo[^\n]*\$\{\{[^}]+}}[^\n]*>>\s*\"?\$GITHUB_ENV\b",
        "HIGH",
        "Writing to $GITHUB_ENV with a ${{ }} expression embedded in the "
        "value. Env vars persist across steps, so an attacker-controlled "
        "interpolation can poison later steps. Route the expression "
        "through env: first. ($GITHUB_OUTPUT has its own dedicated rule "
        "github-output-injection — the two no longer collide.)",
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
    # Wave 14 — from deep-workflow-security (PWNPipe-58 port)
    "actions-allow-unsecure-commands": (
        r"ACTIONS_ALLOW_UNSECURE_COMMANDS\s*:\s*(?:true|['\"]true['\"]|1|['\"]1['\"])"
        r"(?:[^\n]*#\s*allow)?",
        "CRITICAL",
        "ACTIONS_ALLOW_UNSECURE_COMMANDS re-enables deprecated "
        "::set-env::/::add-path:: shell commands — any step's stdout "
        "can inject env vars / PATH into following steps. Remove this "
        "env var and migrate to $GITHUB_ENV / $GITHUB_PATH.",
    ),
    "github-step-summary-injection": (
        # `echo "${{ untrusted }}" >> $GITHUB_STEP_SUMMARY` shape — the
        # attacker plants Markdown the maintainer sees in the Actions UI.
        # Allowlist of untrusted contexts mirrors the DANGEROUS_CONTEXTS
        # set used by the Sentinel injection rules.
        r"\$\{\{\s*github\.(?:event\.(?:pull_request|issue|comment|review|"
        r"discussion|commits|workflow_run)\.[^}]+|head_ref)\s*\}\}"
        r"[^\n]*>>?\s*\"?\$GITHUB_STEP_SUMMARY\b",
        "MAJOR",
        "Untrusted ${{ }} context appended to $GITHUB_STEP_SUMMARY — "
        "renders attacker-controlled Markdown in the Actions UI job-"
        "summary page. Phishing-link / credential-harvest vector. "
        "Sanitise via env: + plain text or remove.",
    ),
    "github-output-injection": (
        # Same shape but writing into $GITHUB_OUTPUT, which downstream
        # steps then expand via ${{ steps.X.outputs.Y }} = silent RCE.
        r"\$\{\{\s*github\.(?:event\.(?:pull_request|issue|comment|review|"
        r"discussion|commits|workflow_run)\.[^}]+|head_ref)\s*\}\}"
        r"[^\n]*>>?\s*\"?\$GITHUB_OUTPUT\b",
        "HIGH",
        "Untrusted ${{ }} context written to $GITHUB_OUTPUT — "
        "downstream steps that read ${{ steps.X.outputs.Y }} will "
        "interpolate attacker text into their own commands. Distinct "
        "from $GITHUB_ENV — that's covered by github-env-write-with-"
        "expr. Move the value through env: and sanitise.",
    ),
    "overprovisioned-secrets-tojson": (
        # `${{ toJSON(secrets) }}` or `${{ format('...', secrets.*) }}`
        # leaks every secret as one blob — even unused ones.
        r"\$\{\{\s*(?:toJSON|toPrettyJSON)\s*\(\s*secrets(?:\s*\))",
        "HIGH",
        "toJSON(secrets) / toPrettyJSON(secrets) serialises the FULL "
        "secret block into the workflow context — every secret is "
        "exposed even if only one was needed. Reference individual "
        "secrets explicitly via ${{ secrets.NAME }}.",
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


# =========================================================================
# FP-hardening (round 3) — caller-side discriminators
# =========================================================================
#
# The patterns above are intentionally fast and broad — they catch the
# attack shape but they don't know the FILE TYPE / PATH CONTEXT a hit
# lives in. Two of the rules (`hardcoded-secrets`, `ide-config-injection`)
# fire on legitimate plugin installers, test fixtures, and canonical
# AWS test placeholders. The helpers below let the orchestrator suppress
# those FP categories at dispatch time without modifying the regex.


# Canonical placeholder values that ARE NOT real secrets. AWS publishes
# `AKIAIOSFODNN7EXAMPLE` as the documented test placeholder; the GitHub
# token shapes `ghp_xxx...` / `ghp_TEST...` and a fully-`x`'d AKIA are
# universally used in CONTRIBUTING.md, training labs, and unit tests.
# Real attackers never use these — they're public, well-known, and
# every secret scanner ships an allowlist of them.
_HARDCODED_SECRETS_PLACEHOLDER = _re_mod.compile(
    r"AKIA(?:IOSFODNN7EXAMPLE|[X]{16}|TEST[A-Z0-9_-]*)"
    r"|ghp_(?:[xX]{36}|TEST[A-Za-z0-9_-]{0,40})"
    r"|github_pat_(?:[xX]{82}|TEST[A-Za-z0-9_-]{0,82})"
    r"|gho_(?:[xX]{36}|TEST[A-Za-z0-9_-]{0,40})"
    r"|ghs_(?:[xX]{36}|TEST[A-Za-z0-9_-]{0,40})"
)


def is_hardcoded_secret_placeholder(matched_text: str) -> bool:
    """Return True when the matched secret literal is one of the
    well-known test placeholders (AKIAIOSFODNN7EXAMPLE,
    ghp_xxxxxx..., AKIATEST..., etc.). Callers should drop the
    `hardcoded-secrets` finding when this returns True.
    FP-hardening (round 3) — mirrors truffleHog / gitleaks behaviour."""
    if not matched_text:
        return False
    return _HARDCODED_SECRETS_PLACEHOLDER.search(matched_text) is not None


# Path segments that indicate the file is a test fixture, training
# lab, or contributor-onboarding doc — places where placeholder
# secrets canonically appear in plaintext. FP-hardening (round 3):
# callers should NOT promote `hardcoded-secrets` to CRITICAL in these
# files even if the value isn't a known placeholder shape (the file's
# context is "documentation by example", not "live secret leak").
_HARDCODED_SECRETS_FP_PATH = _re_mod.compile(
    r"(?:^|/)("
    r"tests?|"
    r"test_[A-Za-z0-9_]+\.py|"
    r"[A-Za-z0-9_]+\.test\.[A-Za-z0-9]+|"
    r"__tests__|"
    r"labs?|"
    r"training|"
    r"CONTRIBUTING\.md|"
    r"IMPLEMENTATION_PLAN\.md|"
    r"docs?/contributing|"
    r"examples?|"
    r"fixtures?|"
    r"samples?"
    r")(?:$|/|\.)",
    _re_mod.IGNORECASE,
)


def is_hardcoded_secret_fp_path(filename: str) -> bool:
    """Return True when `filename` lives in a test fixture / training
    lab / contributor doc path. Callers should DEMOTE
    `hardcoded-secrets` findings (CRITICAL → MEDIUM) in these files —
    placeholders for documentation are normal here. The placeholder
    allowlist `is_hardcoded_secret_placeholder()` should be tried
    first; this is the broader fallback. FP-hardening (round 3)."""
    if not filename:
        return False
    return _HARDCODED_SECRETS_FP_PATH.search(filename) is not None


# Path discriminator for the `ide-config-injection` rule. The
# original intent was to catch WORKFLOWS writing to `.claude/` /
# `.vscode/` / `.cursor/` config — an injection vector when CI
# untrusted input ends up in an agent's persistent config. Plugin
# installers (`README.md`, `INSTALL.md`, `install.sh`,
# `setup.sh`, agent definition docs) ALSO touch those paths but
# they're consensual user installs, not injections.
#
# FP-hardening (round 3): callers should only fire
# `ide-config-injection` on `.github/workflows/*.yml` /
# `.github/workflows/*.yaml`. On every other file path the rule
# should be skipped.
_IDE_CONFIG_INJECTION_ONLY_PATH = _re_mod.compile(
    r"(?:^|/)\.github/workflows/[^/]+\.ya?ml$",
    _re_mod.IGNORECASE,
)


def is_ide_config_injection_applicable_path(filename: str) -> bool:
    """Return True iff `filename` is a GitHub Actions workflow YAML.
    Callers should skip the `ide-config-injection` rule for any other
    path (README, install scripts, agent docs, forensic docs). The
    threat is workflow CI writing attacker-controlled paths into
    `.claude/` — not user-initiated installs from a README.
    FP-hardening (round 3)."""
    if not filename:
        # No filename info => assume safest behaviour: do NOT apply
        # the rule (caller's choice). The unknown-path case is the
        # situation where the rule is most likely to FP.
        return False
    return _IDE_CONFIG_INJECTION_ONLY_PATH.search(filename) is not None
