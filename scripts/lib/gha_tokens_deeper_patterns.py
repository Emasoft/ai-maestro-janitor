"""GitHub Actions token / permission scope — deeper patterns.

Wave-30 distillation round 16, angle: GHA tokens / GHEC SSO.

Catalogue of 7 GHA-specific token/permission anti-patterns distilled in
`reports/distill-round-16/gha-tokens-deeper.md`. These are distinct from:

  * `gha_reusable_patterns.py` — reusable-workflow / composite-action
    structural rules (Rules 1-14). This module does NOT cover:
    reusable-workflow mutable ref, secrets-inherit, composite-action
    input injection, upload-artifact attacker-name, or permissions-
    elevation on workflow_call bodies.
  * `cicd_secret_leak_patterns.py` — specific compromised action names
    (tj-actions, etc.), self-hosted runner cleanup.
  * `zizmor_patterns.py` — `dangerous-triggers-pr-target`,
    `unpinned-uses-tag`, `secrets-inherit`, `hardcoded-secrets`.
  * `zizmor_patterns_extra.py` — `insteadof-secret-in-url`,
    `workflow-run-pwn-checkout`, `github-app-skip-token-revoke`.
  * `ci_runner_injection_patterns.py` — fork injection, matrix injection,
    expression injection into run: blocks.

What IS here (7 net-new rules, all RE2-safe where noted):

  * gha-prt-wrong-scope-write                         (HIGH)
  * gha-pat-checkout-fork-ref                         (CRITICAL)
  * gha-id-token-write-without-oidc-consumer          (MAJOR → mapped HIGH)
  * gha-missing-permissions-default-write             (MAJOR → mapped HIGH)
  * gha-third-party-action-token-no-sha-pin           (CRITICAL)
  * gha-checkout-persist-creds-git-push               (HIGH)
  * gha-workflow-dispatch-write-all-workflow-level     (CRITICAL)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-GHA-01 — Unconstrained Token Scope (write-all)
  ASI-GHA-02 — Missing Permissions Declaration
  ASI-GHA-03 — Excessive Token Privileges (prt-wrong-scope)
  ASI-GHA-04 — Credential Exposure via Fork Checkout
  ASI-GHA-05 — Over-permissioned OIDC Scope
  ASI-GHA-06 — Supply Chain Token Theft via Mutable Tag
  ASI-GHA-07 — Credential Window Expansion (persist-credentials)

All regexes are RE2-compatible (no lookaheads, no backreferences, no
catastrophic backtracking). Patterns involving negative-lookahead are
implemented via two-stage scan (Stage-A positive match + Stage-B
absence check in Python). Patterns are PRE-COMPILED at module load.
Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.

Severity mapping: MAJOR (from the distillation report) → HIGH in this
module, aligning with the four-level vocabulary used across the pattern
library (CRITICAL / HIGH / MEDIUM / LOW).
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookahead / lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- G1 : gha-prt-wrong-scope-write ------------------------------------
#
# A workflow triggered by `pull_request_target` followed within 800 chars
# by a `permissions:` block. Stage-B (Python-level) checks that the block
# does NOT contain `pull-requests:`, signalling the declared scope
# understates the actual token power granted by pull_request_target.


_PRT_TRIGGER = _re(r"\bpull_request_target\b")

# Match a permissions block: `permissions:` followed by 1-6 lines of
# `  key: value` (YAML mapping entries). RE2-safe — no nested quantifiers.
_PRT_PERMISSIONS_BLOCK = _re(
    r"permissions:\s*\n(?:[ \t]+[\w][\w-]*:\s*\w+[ \t]*\n){1,6}"
)

# Suppressor: if `pull-requests:` appears inside the matched block,
# the declaration is not understating scope.
_PRT_PR_SCOPE_PRESENT = _re(r"\bpull-requests\s*:")


# ---- G2 : gha-pat-checkout-fork-ref ------------------------------------
#
# A `token:` input on any step that receives a secret other than
# `secrets.GITHUB_TOKEN`. Stage-B checks for a pull_request_target or
# workflow_run trigger in the same file (critical context), and for the
# presence of a non-first-party action with a mutable ref.
#
# The literal token: ${{ secrets.GITHUB_TOKEN }} is the safe built-in;
# any other secrets.* name is a PAT and receives this finding.


# Positive: `token: ${{ secrets.SOMETHING }}` — broad.
_PAT_TOKEN_INPUT = _re(
    r"token:\s*\$\{\{\s*secrets\.[A-Z_][A-Z0-9_]{2,}\s*\}\}"
)

# Suppressor: `secrets.GITHUB_TOKEN` (the built-in ephemeral token).
_PAT_GITHUB_TOKEN = _re(r"\bsecrets\.GITHUB_TOKEN\b")

# Context amplifier: fork-execution trigger in the file.
_FORK_EXEC_TRIGGER = _re(r"\b(?:pull_request_target|workflow_run)\b")


# ---- G3 : gha-id-token-write-without-oidc-consumer --------------------
#
# `id-token: write` in a permissions block. Stage-B checks whether
# any known OIDC relying party step is present in the file. If absent,
# flag — the permission is stranded.


_ID_TOKEN_WRITE = _re(r"\bid-token\s*:\s*write\b")

# Known OIDC relying party action prefixes / commands.
_OIDC_CONSUMER = _re(
    r"\baws-actions/configure-aws-credentials\b"
    r"|"
    r"\bgoogle-github-actions/auth\b"
    r"|"
    r"\bazure/login\b"
    r"|"
    r"\bhashicorp/vault-action\b"
    r"|"
    r"\bsigstore/cosign-installer\b"
    r"|"
    r"\bactions/attest-build-provenance\b"
    r"|"
    # npm publish --provenance triggers an implicit OIDC call.
    r"\bnpm\s+publish\s+.*--provenance\b"
    r"|"
    r"\bpython\s+-m\s+twine\s+upload\b"
)


# ---- G4 : gha-missing-permissions-default-write ------------------------
#
# Workflow file with no `permissions:` keyword at all. Full-file
# structural check implemented in scan_text — no anchor regex needed
# because the finding is based on absence.


# Detect a GitHub Actions workflow (has `on:` or `jobs:` at top level).
_WORKFLOW_FILE_MARKER = _re(r"^(?:on|jobs)\s*:")

# Presence of any permissions declaration (suppressor).
_PERMISSIONS_PRESENT = _re(r"\bpermissions\s*:")


# ---- G5 : gha-third-party-action-token-no-sha-pin ----------------------
#
# A third-party `uses:` step (not actions/ or github/) referencing a
# mutable version tag, followed within 8 lines by a token/secret input.
# RE2-safe: no negative-lookahead; first-party filter applied in Python.


# Match: uses: <org>/<repo>@<mutable-ref>
# Mutable-ref: any tag that is NOT a 40-hex SHA.
# We positively match semver tags, branch names, and bare major refs.
_THIRD_PARTY_USES = _re(
    r"uses:\s+"
    r"([A-Za-z0-9][\w.\-]{0,38}/[\w.\-]{1,60})"
    r"@"
    r"(v\d[\w.\-]{0,30}|main|master|HEAD|\d+\.\d[\w.\-]{0,20})\b"
)

# First-party orgs — suppress if the matched org is one of these.
_FIRST_PARTY_ORGS = frozenset({"actions", "github"})

# Token / credential input on the following lines.
_TOKEN_INPUT_NEAR = _re(
    r"\b(?:token|github-token|auth-token|credentials)\s*:\s*\$\{\{"
)


# ---- G6 : gha-checkout-persist-creds-git-push --------------------------
#
# `actions/checkout` step without an explicit `persist-credentials: false`
# followed within 30 lines by a `git push`. Two-stage: Stage-A finds the
# checkout step; Stage-B scans the forward window for `git push` and
# requires the absence of the suppress flag.


_CHECKOUT_STEP = _re(r"\buses\s*:\s*actions/checkout@[^\n]+")

# Suppressor: explicit opt-out persisted in the checkout's `with:` block.
_PERSIST_FALSE = _re(r"\bpersist-credentials\s*:\s*false\b")

# Trigger for the follow-up push command.
_GIT_PUSH_CMD = _re(r"\bgit\s+push\b")


# ---- G7 : gha-workflow-dispatch-write-all-workflow-level ---------------
#
# `permissions: write-all` at any level in a non-reusable workflow.
# The suppressor `workflow_call` is checked to avoid overlap with
# `gha_reusable_patterns.py`.


_WRITE_ALL = _re(r"\bpermissions\s*:\s*write-all\b")

# Context suppressor: if `workflow_call` is present in the on: section
# the existing gha_reusable_patterns rule already covers it.
_WORKFLOW_CALL_TRIGGER = _re(r"\bworkflow_call\b")


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="gha-prt-wrong-scope-write",
        name="pull_request_target with understated permissions scope",
        severity="HIGH",
        description=(
            "A workflow triggered by `pull_request_target` declares a "
            "`permissions:` block that does NOT include `pull-requests:`. "
            "The `pull_request_target` trigger grants base-repo write "
            "access to every job; a narrow-looking `issues: write` or "
            "`statuses: write` block understates the actual token power, "
            "causing auditors to miss the elevated blast radius and "
            "making it easy to add future steps that silently inherit "
            "full base-repo write permissions."
        ),
        pattern=_PRT_TRIGGER,
        owasp_asi="ASI-GHA-03",
    ),
    Rule(
        id="gha-pat-checkout-fork-ref",
        name="PAT passed as token: to a step in a fork-execution workflow",
        severity="CRITICAL",
        description=(
            "A personal access token (any `secrets.*` name other than "
            "`secrets.GITHUB_TOKEN`) is passed as the `token:` input to "
            "an action step in a workflow that runs against fork PRs "
            "(`pull_request_target` or `workflow_run`). The PAT is "
            "embedded in the Git credential helper and accessible to every "
            "subsequent `run:` step, including code injected by a malicious "
            "fork contributor."
        ),
        pattern=_PAT_TOKEN_INPUT,
        owasp_asi="ASI-GHA-04",
    ),
    Rule(
        id="gha-id-token-write-without-oidc-consumer",
        name="id-token: write declared with no OIDC relying party step",
        severity="HIGH",
        description=(
            "`id-token: write` allows any step in the job to mint a signed "
            "OIDC JWT asserting the repository's identity. When no OIDC "
            "relying party step (aws-actions/configure-aws-credentials, "
            "google-github-actions/auth, azure/login, vault-action, "
            "attest-build-provenance, npm publish --provenance, etc.) is "
            "present, the permission is stranded — a copy-paste from a "
            "cloud-deploy template — and exposes all steps to JWT "
            "exfiltration risk."
        ),
        pattern=_ID_TOKEN_WRITE,
        owasp_asi="ASI-GHA-05",
    ),
    Rule(
        id="gha-missing-permissions-default-write",
        name="workflow with no permissions block inherits default write token",
        severity="HIGH",
        description=(
            "A GitHub Actions workflow file contains no `permissions:` "
            "declaration (neither at the top level nor in any job). In "
            "repositories where the organization Actions default is not "
            "explicitly set to `read`, every job runs with legacy write "
            "permissions on all scopes (contents, pull-requests, issues, "
            "checks, packages, etc.). This is detectable at lint time and "
            "is classified by GitHub as a security misconfiguration."
        ),
        pattern=_WORKFLOW_FILE_MARKER,
        owasp_asi="ASI-GHA-02",
    ),
    Rule(
        id="gha-third-party-action-token-no-sha-pin",
        name="third-party action at mutable tag receives a secret token input",
        severity="CRITICAL",
        description=(
            "A `uses:` step references a third-party action (not `actions/` "
            "or `github/`) at a mutable version tag (semver, branch name, "
            "or bare major ref) and receives a `token:`, `github-token:`, "
            "`auth-token:`, or `credentials:` input referencing `${{`. "
            "Because the tag is mutable, a compromised action author can "
            "push attacker-controlled code behind the same tag on the next "
            "workflow run — receiving the caller's token. This is the "
            "structural precondition that enabled the tj-actions/changed-"
            "files supply-chain attack (2025)."
        ),
        pattern=_THIRD_PARTY_USES,
        owasp_asi="ASI-GHA-06",
    ),
    Rule(
        id="gha-checkout-persist-creds-git-push",
        name="checkout without persist-credentials:false followed by git push",
        severity="HIGH",
        description=(
            "`actions/checkout` persists the GITHUB_TOKEN as a Git "
            "credential helper in `.git/config` by default "
            "(`persist-credentials: true` is the implicit default). Any "
            "`git push` step in the same job implicitly uses that persisted "
            "credential — HIGH severity when combined with "
            "`pull_request_target` (base-repo write) or when untrusted "
            "input modifies the workspace before the push. The safe pattern "
            "is `persist-credentials: false` on the checkout step."
        ),
        pattern=_CHECKOUT_STEP,
        owasp_asi="ASI-GHA-07",
    ),
    Rule(
        id="gha-workflow-dispatch-write-all-workflow-level",
        name="permissions: write-all at workflow level in a non-reusable workflow",
        severity="CRITICAL",
        description=(
            "`permissions: write-all` grants every job in the workflow "
            "the maximum GITHUB_TOKEN scope across all APIs (contents, "
            "pull-requests, issues, packages, security-events, "
            "deployments, actions, checks, id-token, etc.). This is "
            "almost always a copy-paste from a template. In GHEC "
            "organizations with SAML SSO the token is further constrained "
            "by the calling user's SAML session, but `write-all` still "
            "bypasses all per-job minimization. Distinct from "
            "`gha_reusable_patterns.py` Rule 10 which targets "
            "`workflow_call` bodies."
        ),
        pattern=_WRITE_ALL,
        owasp_asi="ASI-GHA-01",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters apply context checks beyond the anchor regex:

      * G1 (prt-wrong-scope-write) — anchor on `pull_request_target`;
        find the nearest `permissions:` block within 800 chars forward;
        suppress if `pull-requests:` appears inside the block.
      * G2 (pat-checkout-fork-ref) — anchor on `token: ${{ secrets.X }}`;
        suppress if the secret is `GITHUB_TOKEN`; raise severity only when
        a fork-execution trigger (`pull_request_target` / `workflow_run`)
        is present anywhere in the file.
      * G3 (id-token-write-without-oidc-consumer) — anchor on
        `id-token: write`; suppress if any known OIDC relying party step
        appears anywhere in the file.
      * G4 (missing-permissions-default-write) — anchor on the workflow
        file marker (`on:` / `jobs:`); flag only when `permissions:` is
        absent from the entire file. Only one finding emitted per file.
      * G5 (third-party-action-token-no-sha-pin) — anchor on a third-
        party `uses:` at a mutable tag; suppress if the org is `actions`
        or `github`; confirm only when a token/credential input appears
        within the next 10 lines.
      * G6 (checkout-persist-creds-git-push) — anchor on an
        `actions/checkout` step; scan a 30-line forward window for
        `git push`; suppress if `persist-credentials: false` appears in
        the same window.
      * G7 (workflow-dispatch-write-all-workflow-level) — anchor on
        `permissions: write-all`; suppress if `workflow_call` appears
        anywhere in the file (already covered by gha_reusable_patterns).

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- G1 : gha-prt-wrong-scope-write ----
    rule_g1 = rule_by_id["gha-prt-wrong-scope-write"]
    for m in _PRT_TRIGGER.finditer(text):
        # Look forward up to 800 chars for a permissions block.
        window_text = text[m.start(): m.start() + 800]
        pb = _PRT_PERMISSIONS_BLOCK.search(window_text)
        if pb is None:
            continue
        # Check the matched block for pull-requests: presence.
        block_text = pb.group(0)
        if _PRT_PR_SCOPE_PRESENT.search(block_text) is not None:
            continue
        _emit(rule_g1, m.start(), m.group(0))

    # ---- G2 : gha-pat-checkout-fork-ref ----
    rule_g2 = rule_by_id["gha-pat-checkout-fork-ref"]
    has_fork_trigger = _file_contains(text, _FORK_EXEC_TRIGGER)
    for m in _PAT_TOKEN_INPUT.finditer(text):
        matched = m.group(0)
        # Suppress if the matched text refers to the built-in token.
        if _PAT_GITHUB_TOKEN.search(matched) is not None:
            continue
        # Only flag as CRITICAL when a fork-execution trigger is present.
        if not has_fork_trigger:
            continue
        _emit(rule_g2, m.start(), matched)

    # ---- G3 : gha-id-token-write-without-oidc-consumer ----
    rule_g3 = rule_by_id["gha-id-token-write-without-oidc-consumer"]
    has_oidc_consumer = _file_contains(text, _OIDC_CONSUMER)
    if not has_oidc_consumer:
        for m in _ID_TOKEN_WRITE.finditer(text):
            _emit(rule_g3, m.start(), m.group(0))

    # ---- G4 : gha-missing-permissions-default-write ----
    # File-level structural check: flag once if the file looks like a
    # workflow but has no `permissions:` declaration.
    rule_g4 = rule_by_id["gha-missing-permissions-default-write"]
    if _file_contains(text, _WORKFLOW_FILE_MARKER) and not _file_contains(
        text, _PERMISSIONS_PRESENT
    ):
        # Emit at offset 0 (start of file) — one finding per file.
        _emit(rule_g4, 0, text[:80].rstrip())

    # ---- G5 : gha-third-party-action-token-no-sha-pin ----
    rule_g5 = rule_by_id["gha-third-party-action-token-no-sha-pin"]
    for m in _THIRD_PARTY_USES.finditer(text):
        slug = m.group(1)  # org/repo
        org = slug.split("/")[0].lower()
        if org in _FIRST_PARTY_ORGS:
            continue
        line, _ = _line_col(text, m.start())
        # Check the next 10 lines for a token/credential input.
        window = _slice_forward(text, line, 10)
        if _TOKEN_INPUT_NEAR.search(window) is None:
            continue
        _emit(rule_g5, m.start(), m.group(0))

    # ---- G6 : gha-checkout-persist-creds-git-push ----
    rule_g6 = rule_by_id["gha-checkout-persist-creds-git-push"]
    for m in _CHECKOUT_STEP.finditer(text):
        line, _ = _line_col(text, m.start())
        # Scan 30-line forward window for git push.
        window = _slice_forward(text, line, 30)
        if _GIT_PUSH_CMD.search(window) is None:
            continue
        # Suppress if persist-credentials: false appears in the same window.
        if _PERSIST_FALSE.search(window) is not None:
            continue
        _emit(rule_g6, m.start(), m.group(0))

    # ---- G7 : gha-workflow-dispatch-write-all-workflow-level ----
    rule_g7 = rule_by_id["gha-workflow-dispatch-write-all-workflow-level"]
    has_workflow_call = _file_contains(text, _WORKFLOW_CALL_TRIGGER)
    if not has_workflow_call:
        for m in _WRITE_ALL.finditer(text):
            _emit(rule_g7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
