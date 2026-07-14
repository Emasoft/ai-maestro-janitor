"""Every workflow rule id → the issue code it raises (TRDD-CGYMUKO6, Phase 3 coverage).

The workflow auditor emits 54 distinct `rule_id`s across two tiers (the zizmor regex catalog and the
Sentinel structural rules). The acceptance criterion for the issue catalog is that **every finding
every scanner can emit has a code** — so this is the map that makes that claim true rather than merely
stated, and `test_workflow_issue_codes.py` fails the build if a rule id is ever added without one.

**Grouped by THE FIX, not by the rule's name.** A ticket's `fix` field is what the dispatched agent is
told to attempt, so two rules belong to the same code exactly when the same repair answers both.
`shell-injection-expr` and `github-script-injection` are different rules and the same job: stop letting
attacker-controlled text reach an executable position. Splitting them into two tickets would dispatch
two agents to make the same edit in the same file; merging unrelated ones would hand one agent a task
it cannot state in a sentence.

The runtime fallback (`code_for` → `WFSEC-006`) exists ONLY so an unmapped rule can never cause a
security finding to be silently dropped on a live heartbeat. It is a safety net, not the design: the
coverage test forbids reaching it in the shipped rule set, so a new scanner rule forces a real mapping
decision at build time rather than quietly landing in a bucket labelled "other".
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# WFSEC-001 — attacker-controlled input reaches an executable position.
# Fix: route it through `env:` and quote it; never interpolate into source.
# --------------------------------------------------------------------------- #
_INJECTION = (
    "shell-injection-expr",
    "shell-injection-jq",
    "github-script-injection",
    "workflow-dispatch-injection",
    "runs-on-injection",
    "matrix-strategy-injection",
    "matrix-fromjson-untrusted",
    "github-env-write-with-expr",
    "github-output-injection",
    "github-step-summary-injection",
    "ai-config-injection",
    "ide-config-injection",
    "ref-confusion-in-run",
    "jq-arg-trap",
    "jq-arg-escape-sequences",
    "unsound-contains",
    # Re-enabling the deprecated `::set-env::` protocol turns any logged string into an env write —
    # it is an injection vector wearing a compatibility flag.
    "actions-allow-unsecure-commands",
)

# --------------------------------------------------------------------------- #
# WFSEC-002 — fork / PR-controlled code runs with the base repo's privileges.
# Fix: never run untrusted code in a job that holds the write token or secrets.
# --------------------------------------------------------------------------- #
_UNTRUSTED_CODE = (
    "dangerous-triggers",
    "dangerous-triggers-pr-target",
    "workflow-run-pwn-checkout",
    "issue-comment-toctou",
    "cache-poisoning-pr-trigger",
    "self-hosted-runner-fork",
    "artipacked-upload",
    "allow-forks-artifact",
    "dependabot-actor-spoofable",
    "overly-broad-triggers",
)

# --------------------------------------------------------------------------- #
# WFSEC-003 — the token / permission scope is wider than the job needs.
# Fix: declare least privilege; scope, gate, and revoke.
# --------------------------------------------------------------------------- #
_PRIVILEGE = (
    "missing-permissions",
    "excessive-permissions",
    "id-token-write-unscoped",
    "secrets-inherit",
    "unscoped-app-token",
    "github-app-skip-token-revoke",
    "missing-env-protection",
    "missing-persist-credentials",
)

# --------------------------------------------------------------------------- #
# WFSEC-004 — the workflow depends on a MUTABLE reference.
# Fix: pin it (SHA, digest, lockfile) so what ran yesterday is what runs today.
# --------------------------------------------------------------------------- #
_MUTABLE_DEPENDENCY = (
    "unpinned-uses-tag",
    "unpinned-docker-image",
    "unpinned-artifact",
    "github-dependency-refs",
    "missing-frozen-lockfile",
    "dangerous-lifecycle-scripts",
    "curl-pipe-shell",
    # Build and publish in ONE job means a compromised build step already holds the publish
    # credential — the supply chain is only as pinned as the job boundary that carries it.
    "build-publish-same-job",
)

# --------------------------------------------------------------------------- #
# WFSEC-005 — a secret is exposed by the workflow itself.
# Fix: move it behind `secrets:`/OIDC — and if it was committed, it is BURNED.
# --------------------------------------------------------------------------- #
_SECRET_EXPOSURE = (
    "hardcoded-secrets",
    "static-aws-credentials",
    "insteadof-secret-in-url",
    "docker-build-arg-secrets",
    "secret-env-bare-in-run",
    "overprovisioned-secrets-tojson",
    "actions-debug-env-committed",
)

# --------------------------------------------------------------------------- #
# WFSEC-006 — the workflow's own safety rail is missing or defeated.
# Fix: restore the guard that was supposed to catch the failure.
# --------------------------------------------------------------------------- #
_DEFEATED_GUARD = (
    "missing-timeouts",
    "if-always-true",
    "continue-on-error-on-security-step",
    "git-config-global",
)

CODE_FOR_RULE: dict[str, str] = {
    **{r: "WFSEC-001" for r in _INJECTION},
    **{r: "WFSEC-002" for r in _UNTRUSTED_CODE},
    **{r: "WFSEC-003" for r in _PRIVILEGE},
    **{r: "WFSEC-004" for r in _MUTABLE_DEPENDENCY},
    **{r: "WFSEC-005" for r in _SECRET_EXPOSURE},
    **{r: "WFSEC-006" for r in _DEFEATED_GUARD},
}

FALLBACK_CODE = "WFSEC-006"


def code_for(rule_id: str) -> str:
    """The issue code for a workflow rule id. Never raises, never returns "" — a security finding
    with no code would be a finding with no ticket, and a finding with no ticket is a finding lost."""
    return CODE_FOR_RULE.get(rule_id, FALLBACK_CODE)
