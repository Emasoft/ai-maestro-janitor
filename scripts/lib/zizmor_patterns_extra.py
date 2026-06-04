# Extension catalog for the janitor's second-pass workflow auditor.
#
# This module ADDS new rules on top of scripts/lib/zizmor_patterns.py without
# modifying that file. It mirrors the (regex, severity, description) shape of
# `PATTERNS` so the classifier can merge `PATTERNS_EXTRA` into its dispatch
# table by simple dict union.
#
# Source: reports/study-github-monitoring-deep/*deep-workflow-security*.md
# (12-rule proposal catalogue). Wave 14 already shipped 4 of those 12
# (actions-allow-unsecure-commands, github-step-summary-injection,
# github-output-injection, overprovisioned-secrets-tojson). This module
# ports the REMAINING regex-tier rules — anything that requires a YAML
# walk / AST parse is deferred to a Sentinel structural wave and is NOT
# included here.
#
# Constraints (same as PATTERNS):
#   * RE2-safe: no lookaround, no backrefs. Inline (?i:...) flags only.
#   * Severities limited to CRITICAL / HIGH / MAJOR / MINOR — the existing
#     classifier vocabulary. There is no MEDIUM tier.
#   * Each pattern is a high-fidelity discriminator that requires BOTH a
#     dangerous sink AND a tainted source colocated on the same line
#     (regex single-line scan), to keep FP-rate near-zero.
#
# Wiring: scripts/lib/zizmor_classifier.py merges PATTERNS_EXTRA into the
# classifier's pattern table at module load (_ALL_PATTERNS = {**PATTERNS,
# **PATTERNS_EXTRA}). Both consumers — doctor_classify.py and the
# workflow-security detector — build a Classifier(), so they inherit these
# rules automatically; this catalog only declares the rules, it does not
# wire them.

from __future__ import annotations

# rule_id → (pattern, severity, description)
PATTERNS_EXTRA: dict[str, tuple[str, str, str]] = {
    # Deep-workflow-security #6 — workflow_run pwn-checkout
    # Single-line discriminator: `ref:` value referencing
    # github.event.workflow_run.head_{sha,branch,commit,ref}. The full
    # rule needs a YAML walk to confirm the parent uses: is
    # actions/checkout, but the line-level shape is already a strong
    # indicator — there is no legitimate reason to check out
    # attacker-controlled fork code from a workflow_run trigger.
    "workflow-run-pwn-checkout": (
        r"ref:\s*\$\{\{\s*github\.event\.workflow_run\.head_(?:sha|branch|commit|ref)",
        "CRITICAL",
        "checkout step targets github.event.workflow_run.head_* — pulls "
        "attacker-controlled fork code into a privileged context (same "
        "trust-boundary class as pull_request_target, see Ultralytics 2024). "
        "Either drop the ref override (default checkout uses base SHA) or "
        "gate behind an explicit allowlist of approved actors.",
    ),
    # Deep-workflow-security #7 — matrix-strategy injection (subset)
    # Catch the most direct shape: `fromJSON(${{ github.event.* }})` or
    # any matrix-context value that interpolates github.event.* / head_ref
    # on the same line as the matrix key. The pattern is line-scoped so
    # the FP discriminator is the explicit fromJSON-of-untrusted-context
    # combination — there is no legitimate use.
    "matrix-fromjson-untrusted": (
        r"fromJSON\s*\(\s*\$\{\{\s*github\.(?:event\.(?:pull_request|issue|"
        r"comment|review|discussion|commits|workflow_run)\.[^}]+|head_ref)",
        "HIGH",
        "fromJSON() called on untrusted github.event.* / github.head_ref — "
        "parses attacker JSON into the matrix, then ${{ matrix.* }} "
        "interpolates the values into shell commands. PR title "
        '"; curl evil...#" becomes a runtime shell payload. Sanitise via '
        "env: + a parsed/validated intermediate, never feed raw event "
        "context to fromJSON inside strategy.matrix.",
    ),
    # Deep-workflow-security #8 — github-app-skip-token-revoke
    # The `skip-token-revoke: true` and `revoke-token: false` knobs keep
    # GitHub App installation tokens live for up to an hour after the job
    # ends. Any post-job log/artifact leak then becomes an org-wide
    # write-credential exposure during that window.
    "github-app-skip-token-revoke": (
        r"(?:skip-token-revoke:\s*(?:true|['\"]true['\"]|1|['\"]1['\"])"
        r"|revoke-token:\s*(?:false|['\"]false['\"]|0|['\"]0['\"]))",
        "HIGH",
        "GitHub App installation token has revocation suppressed "
        "(skip-token-revoke: true / revoke-token: false). The token stays "
        "valid up to 1 hour after the step finishes — any later log dump / "
        "artifact upload / dependency-RCE during that window leaks an "
        "org-wide write credential. Remove the flag (default is auto-revoke).",
    ),
    # Deep-workflow-security #9 — actions-debug-env-enabled
    # ACTIONS_STEP_DEBUG / ACTIONS_RUNNER_DEBUG should ONLY ever be set
    # via a repo secret (so the maintainer enables debug transiently for
    # a single run). Committing them in workflow YAML dumps the full
    # step env including derived secret transformations to public logs.
    "actions-debug-env-committed": (
        r"(?:ACTIONS_STEP_DEBUG|ACTIONS_RUNNER_DEBUG)\s*:\s*"
        r"(?:true|['\"]true['\"]|1|['\"]1['\"])",
        "MINOR",
        "ACTIONS_STEP_DEBUG / ACTIONS_RUNNER_DEBUG is committed in workflow "
        "YAML — dumps full step env + inputs/outputs to logs on every run. "
        "Often defeats secret-masking on derived/transformed values. Enable "
        "transiently via repo secret instead, never in committed YAML.",
    ),
    # Deep-workflow-security #10 — dependabot-confused-deputy via actor
    # Two regex shapes:
    #   * `github.actor == 'dependabot[bot]'`           (only `==`)
    #   * `contains(github.actor, 'dependabot')`        (always bypassable)
    # `!= 'dependabot[bot]'` is fine (exclusion), so the pattern requires
    # `==`. The contains() form is bypassable in either direction.
    "dependabot-actor-spoofable": (
        r"(?:github\.actor\s*==\s*['\"]dependabot\[bot\]['\"]"
        r"|contains\s*\(\s*github\.actor\s*,\s*['\"]dependabot)",
        "MINOR",
        "github.actor used to gate dependabot logic — actor is the user who "
        "TRIGGERED the run, not the PR author. An attacker comments "
        "'@dependabot rebase' on a Dependabot PR and inherits the "
        "triggered-by-bot identity while the code is theirs. Gate on "
        "github.event.pull_request.user.login + a signed-by-dependabot check "
        "instead.",
    ),
    # Deep-workflow-security #12 — credential-window: secrets/token in
    # `git config ... insteadOf` URL. The token gets persisted in
    # .git/config and stays readable to every later step in the same
    # job that touches git — a long credential-persistence window.
    "insteadof-secret-in-url": (
        r"git config[^\n]*url\.[^\n]*\$\{\{\s*(?:secrets\.|github\.token)"
        r"[^\n]*insteadOf",
        "HIGH",
        "git config url.<X>.insteadOf bakes a secret (${{ secrets.* }} or "
        "${{ github.token }}) into the URL — credential persists in "
        ".git/config and is readable by every subsequent step in the same "
        "job (logs, dependency-resolver subprocesses, artifact uploads). "
        "Use a one-shot HTTP header or the env-var indirection instead.",
    ),
    # Bonus port — continue-on-error: true on security/scan steps.
    # Common antipattern: a security gate marked continue-on-error so a
    # failed scan still lets the job pass green. Catches the exact YAML
    # line; the doctor escalates / suppresses based on neighbouring
    # context (action name) but the pattern itself is a single-line
    # discriminator that flags the antipattern wherever it appears
    # near a known security action.
    "continue-on-error-on-security-step": (
        r"continue-on-error:\s*(?:true|['\"]true['\"])"
        r"[^\n]*(?:#[^\n]*(?:scan|audit|security|sast|sca|secret|vuln|cve))",
        "MAJOR",
        "continue-on-error: true on a step the comment marks as a security / "
        "scan / audit task — the job stays green even if the scanner finds "
        "vulnerabilities, defeating the gate. Remove continue-on-error or "
        "move the scanner to a required check.",
    ),
}

# Per-pattern fallback flag, same shape as PATTERN_FALLBACK_FLAGS in
# zizmor_patterns.py. Every pattern in this module is RE2-safe (no
# lookaround, no backrefs) so each entry is True by default.
PATTERN_FALLBACK_FLAGS_EXTRA: dict[str, bool] = {
    rule_id: True for rule_id in PATTERNS_EXTRA
}
