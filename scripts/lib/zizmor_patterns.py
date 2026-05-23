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
    "hardcoded-container-latest": (
        r"image:\s+[\w./-]+:latest\b",
        "MAJOR",
        "container image pinned to :latest — replace with @sha256:<digest> "
        "via 'docker buildx imagetools inspect <image>'.",
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
}

# Per-pattern toggle: True if the pattern is safe for RE2 (no lookaround
# or backreferences). Patterns flagged False are forced through the
# Python re fallback path even when google-re2 is available.
#
# Every current pattern is RE2-safe by construction; this dict is kept
# explicit so a future contributor adding a (?=...) / (?!...) / \1
# pattern remembers to flip the flag and document why.
PATTERN_FALLBACK_FLAGS: dict[str, bool] = {rule_id: True for rule_id in PATTERNS}
