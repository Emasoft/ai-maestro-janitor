# Extended Sentinel structural rules — net-new detectors beyond the Wave 14
# RegexSet set, sourced from the deep-workflow-security audit
# (reports/study-github-monitoring-deep/*deep-workflow-security*.md).
#
# Each rule mirrors the existing rules_context.py architecture (subclass of
# Rule, name/severity/description, check(wf) -> list[Finding]). The module
# extends — it does NOT modify — the existing sentinel/* files; dispatch
# wire-up is the orchestrator's job.
#
# Rule selection criteria (per the deep-workflow-security report):
#   1. NOT already shipped in zizmor RegexSet or sentinel/rules_context.py.
#   2. Needs YAML / job / step / trigger context (not pure regex).
#   3. High-impact (CVSS >= 7) and low-FP when guarded properly.
#
# Five rules ship in this module:
#   - workflow-run-pwn-checkout   (CRITICAL) — workflow_run trigger + checkout
#                                              of head_sha/head_branch
#   - matrix-strategy-injection   (HIGH)     — matrix populated from
#                                              github.event.* AND consumed via
#                                              ${{ matrix.* }} in run:
#   - github-app-skip-token-revoke (HIGH)    — create-github-app-token with
#                                              skip-token-revoke: true
#   - actions-allow-unsecure-commands (CRITICAL) — ACTIONS_ALLOW_UNSECURE_COMMANDS
#                                                  env re-enables ::set-env::
#   - id-token-write-unscoped     (HIGH)     — id-token: write without an
#                                              environment: gate

from __future__ import annotations

import re
from typing import Optional

from lib.sentinel.model import (
    SEV_CRITICAL,
    SEV_HIGH,
    Finding,
    Rule,
    Workflow,
)

# --- shared helpers --------------------------------------------------------

# Contexts an attacker controls on a workflow_run / pull_request_target /
# issue_comment / discussion event. Same allowlist the report names in
# rules #4, #5, #7.
_UNTRUSTED_CONTEXTS = (
    r"github\.event\.issue\b",
    r"github\.event\.pull_request\b",
    r"github\.event\.comment\b",
    r"github\.event\.review\b",
    r"github\.event\.discussion\b",
    r"github\.event\.commits\b",
    r"github\.event\.workflow_run\b",
    r"github\.head_ref\b",
)
_UNTRUSTED_CTX_RE = re.compile(
    r"\$\{\{[^}]*(?:" + "|".join(_UNTRUSTED_CONTEXTS) + r")"
)


def _truthy_yaml_value(value) -> bool:
    """True iff a YAML scalar is one of the obvious truthy spellings.

    The same env-var coercion the GitHub Actions runner applies for boolean
    feature toggles — accept Python True, the string forms "true"/"1"/"yes"
    (case-insensitive), and reject everything else. Keep this conservative:
    setting a feature toggle to "0" / "false" / "no" must NOT fire.
    """
    if value is True:
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return False


def _triggers_include(triggers, *names) -> bool:
    """True iff the workflow's `on:` block names ANY of the given triggers."""
    if isinstance(triggers, dict):
        keys = [str(k) for k in triggers.keys()]
    elif isinstance(triggers, list):
        keys = [str(x) for x in triggers]
    elif isinstance(triggers, str):
        keys = [triggers]
    else:
        keys = []
    return any(k in names for k in keys)


def _all_env_blocks(wf: Workflow):
    """Yield every (env_dict, scope, owner_label) reachable in the workflow.

    `scope` is one of "workflow", "job", "step"; `owner_label` is the job id
    or step name used for finding messages.
    """
    workflow_env = wf.data.get("env") if isinstance(wf.data, dict) else None
    if isinstance(workflow_env, dict):
        yield workflow_env, "workflow", ""
    for job_id, job_hash in wf.jobs().items():
        if not isinstance(job_hash, dict):
            continue
        job_env = job_hash.get("env")
        if isinstance(job_env, dict):
            yield job_env, "job", str(job_id)
        for step in wf.steps(job_hash):
            if not isinstance(step, dict):
                continue
            step_env = step.get("env")
            if isinstance(step_env, dict):
                label = str(step.get("name") or step.get("id") or step.get("uses") or "")
                yield step_env, "step", label


# --- rules -----------------------------------------------------------------


class WorkflowRunPwnCheckout(Rule):
    """`workflow_run` trigger + checkout of the triggering workflow's head.

    Disclosed Ultralytics 2024 attack — `workflow_run` runs in the BASE
    repo's privileged context (full `GITHUB_TOKEN`, secrets available)
    but with `github.event.workflow_run.head_sha` / `head_branch`
    pointing at the FORK's tip. A step that `uses: actions/checkout`
    with `ref: ${{ github.event.workflow_run.head_sha }}` (or head_branch)
    therefore checks out fork-controlled code into a privileged
    environment — classic confused-deputy RCE.

    Symmetric to `dangerous-triggers-pr-target` (which covers
    `pull_request_target`); identical attack class, different trigger.
    """

    name = "workflow-run-pwn-checkout"
    severity = SEV_CRITICAL
    description = "workflow_run + checkout of fork head SHA in privileged context"

    _CHECKOUT_USES = re.compile(r"^actions/checkout(?:@|$)")
    _DANGEROUS_REFS = (
        "github.event.workflow_run.head_sha",
        "github.event.workflow_run.head_branch",
        "github.event.workflow_run.head_commit",
    )

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        if not _triggers_include(wf.triggers(), "workflow_run"):
            return findings

        for job_hash in wf.jobs().values():
            if not isinstance(job_hash, dict):
                continue
            for step in wf.steps(job_hash):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if not (isinstance(uses, str) and self._CHECKOUT_USES.match(uses)):
                    continue
                with_block = step.get("with")
                if not isinstance(with_block, dict):
                    continue
                ref_value = with_block.get("ref")
                if not isinstance(ref_value, str):
                    continue
                # Strip ${{ ... }} wrapper for the comparison.
                inner = re.sub(r"\$\{\{\s*|\s*\}\}", "", ref_value).strip()
                if not any(token in inner for token in self._DANGEROUS_REFS):
                    continue
                line = wf.line_of(re.compile(r"ref:\s*" + re.escape(ref_value))) or wf.line_of(
                    re.compile(re.escape(uses))
                ) or 0
                findings.append(self._finding(
                    wf,
                    line=line,
                    matched_text=f"ref: {ref_value}",
                    description=(
                        "workflow_run-triggered job checks out "
                        f"`{inner}` — fork-controlled code lands in the base "
                        "repo's privileged context (full GITHUB_TOKEN, secrets "
                        "available). Either move the checkout to a "
                        "pull_request-triggered workflow, gate on "
                        "`github.event.workflow_run.conclusion == 'success'` "
                        "AND a same-repo head_repository filter, or drop the "
                        "explicit fork-SHA ref entirely."
                    ),
                ))
        return findings


class MatrixStrategyInjection(Rule):
    """Matrix value populated from `github.event.*` AND consumed in `run:`.

    Disclosed PWNPipe `matrix-injection.js` pattern — `strategy.matrix`
    values are inlined by the runner BEFORE shell parsing, so a PR title
    containing `"; curl evil... #"` becomes a literal shell command when
    referenced via `${{ matrix.foo }}` in a `run:` block. Two conditions
    must hold simultaneously to fire — untrusted source AND shell sink.

    Different attack shape from `shell-injection-expr` (which catches
    `${{ github.event.* }}` directly in run:); this one catches the
    INDIRECTION through the matrix axis.
    """

    name = "matrix-strategy-injection"
    severity = SEV_HIGH
    description = "Matrix axis from github.event.* consumed by run: shell"

    _MATRIX_IN_RUN = re.compile(r"\$\{\{\s*matrix\.")
    _UNTRUSTED_IN_MATRIX = _UNTRUSTED_CTX_RE

    @staticmethod
    def _matrix_has_untrusted(matrix_dict) -> Optional[str]:
        """Return the first untrusted token found anywhere in matrix, or None.

        Walks matrix axes including nested `include`/`exclude` arrays —
        every scalar leaf is checked for an `${{ github.event.* }}` or
        `${{ github.head_ref }}` interpolation.
        """
        if not isinstance(matrix_dict, dict):
            return None

        def walk(node) -> Optional[str]:
            if isinstance(node, dict):
                for v in node.values():
                    hit = walk(v)
                    if hit:
                        return hit
            elif isinstance(node, list):
                for item in node:
                    hit = walk(item)
                    if hit:
                        return hit
            elif isinstance(node, str):
                m = _UNTRUSTED_CTX_RE.search(node)
                if m:
                    return node
            return None

        return walk(matrix_dict)

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        for job_id, job_hash in wf.jobs().items():
            if not isinstance(job_hash, dict):
                continue
            strategy = job_hash.get("strategy")
            if not isinstance(strategy, dict):
                continue
            matrix = strategy.get("matrix")
            tainted_value = self._matrix_has_untrusted(matrix)
            if not tainted_value:
                continue
            # Now check whether any step in this job interpolates matrix.*
            # inside a run: block. The shell sink condition is required so
            # that pure value-passing matrices (e.g. matrix axes consumed
            # only via with:) do not fire.
            for step in wf.steps(job_hash):
                if not isinstance(step, dict):
                    continue
                run_value = step.get("run")
                if not isinstance(run_value, str):
                    continue
                if not self._MATRIX_IN_RUN.search(run_value):
                    continue
                line = wf.line_of(re.compile(r"strategy:\s*$")) or wf.line_of(
                    re.compile(r"matrix:")
                ) or 0
                findings.append(self._finding(
                    wf,
                    line=line,
                    matched_text=f"matrix tainted by: {tainted_value.strip()}",
                    description=(
                        f"Job `{job_id}` has a strategy.matrix value derived "
                        f"from an attacker-controlled context "
                        f"(`{tainted_value.strip()}`) AND a step that "
                        "interpolates `${{ matrix.* }}` inside a `run:` "
                        "block. Matrix values are inlined before shell "
                        "parsing — a crafted PR title becomes a literal "
                        "shell command. Hard-code matrix axes, or stage "
                        "untrusted values through env: with proper quoting."
                    ),
                ))
                break  # one finding per job is enough
        return findings


class GithubAppSkipTokenRevoke(Rule):
    """`actions/create-github-app-token` with revocation suppressed.

    Disclosed PWNPipe `github-app-unsafe.js` pattern — by default the
    create-github-app-token action revokes the App installation token
    at end-of-job. Setting `skip-token-revoke: true` (or, on the tibdex
    variant, `revoke-token: false`) leaves the token live for up to one
    hour after the job ends. A leak via logs, artifacts, or a dependency
    RCE during that hour grants org-wide write across every repo the App
    is installed on.

    Different from `unscoped-app-token` — that rule covers the scope of
    the App grant, this one covers the revocation control.
    """

    name = "github-app-skip-token-revoke"
    severity = SEV_HIGH
    description = "create-github-app-token with revocation suppressed"

    _APP_TOKEN_USES = re.compile(
        r"^(?:actions/create-github-app-token|tibdex/github-app-token)(?:@|$)"
    )

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        for job_hash in wf.jobs().values():
            if not isinstance(job_hash, dict):
                continue
            for step in wf.steps(job_hash):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if not (isinstance(uses, str) and self._APP_TOKEN_USES.match(uses)):
                    continue
                with_block = step.get("with")
                if not isinstance(with_block, dict):
                    continue
                # Both variants — accept truthy on skip-token-revoke,
                # falsy on revoke-token (tibdex inversion).
                skip = with_block.get("skip-token-revoke")
                revoke = with_block.get("revoke-token")
                fires = False
                if skip is not None and _truthy_yaml_value(skip):
                    fires = True
                if revoke is not None and not _truthy_yaml_value(revoke):
                    # revoke-token: false suppresses revocation. None is
                    # treated as "default = revoke" and does NOT fire.
                    if revoke is False or (
                        isinstance(revoke, str)
                        and revoke.strip().lower() in ("false", "0", "no", "off")
                    ):
                        fires = True
                if not fires:
                    continue
                line = (
                    wf.line_of(re.compile(r"skip-token-revoke:"))
                    or wf.line_of(re.compile(r"revoke-token:"))
                    or wf.line_of(re.compile(re.escape(uses)))
                    or 0
                )
                findings.append(self._finding(
                    wf,
                    line=line,
                    matched_text=f"uses: {uses}",
                    description=(
                        "GitHub App installation token kept alive after job end "
                        "(skip-token-revoke / revoke-token). Token stays valid "
                        "up to one hour — leak in logs/artifacts/dep-RCE during "
                        "that window grants org-wide write across every repo "
                        "the App is installed on. Drop the override; let the "
                        "action revoke the token at end-of-job."
                    ),
                ))
        return findings


class ActionsAllowUnsecureCommands(Rule):
    """`ACTIONS_ALLOW_UNSECURE_COMMANDS=true` re-enables `::set-env::`.

    Disclosed CVE-2020-15228 — GitHub deprecated the `::set-env::` and
    `::add-path::` workflow commands because any step's STDOUT could
    inject env vars / PATH into subsequent steps. Setting the
    `ACTIONS_ALLOW_UNSECURE_COMMANDS` env var to truthy re-enables them
    for that workflow / job / step. There is no legitimate use case in
    new code — every shipping workflow must use `>> $GITHUB_ENV` and
    `>> $GITHUB_PATH` instead.
    """

    name = "actions-allow-unsecure-commands"
    severity = SEV_CRITICAL
    description = "ACTIONS_ALLOW_UNSECURE_COMMANDS re-enables ::set-env::"

    _KEY = "ACTIONS_ALLOW_UNSECURE_COMMANDS"

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        seen_lines: set[int] = set()
        for env_block, scope, owner in _all_env_blocks(wf):
            # YAML maps are case-sensitive — the runner env coercion is too,
            # so check the exact (uppercase) key the docs spell out.
            value = env_block.get(self._KEY)
            if value is None:
                continue
            if not _truthy_yaml_value(value):
                continue
            line = wf.line_of(re.compile(re.escape(self._KEY) + r":")) or 0
            if line in seen_lines:
                continue
            seen_lines.add(line)
            owner_label = f" (in {scope}{' ' + owner if owner else ''})" if scope != "workflow" else ""
            findings.append(self._finding(
                wf,
                line=line,
                matched_text=f"{self._KEY}: {value}",
                description=(
                    f"ACTIONS_ALLOW_UNSECURE_COMMANDS=true{owner_label} re-enables "
                    "the deprecated ::set-env:: / ::add-path:: workflow commands "
                    "(CVE-2020-15228). Any step's stdout can inject env vars or "
                    "PATH into subsequent steps. There is no legitimate use case "
                    "in new code — remove the override; use "
                    "`echo \"FOO=value\" >> $GITHUB_ENV` and `>> $GITHUB_PATH`."
                ),
            ))
        return findings


class IdTokenWriteUnscoped(Rule):
    """`id-token: write` permission without an `environment:` gate.

    Disclosed supply-chain-guardian `oidc_scanner.py:SCA-061` pattern.
    OIDC token issuance with no `environment:` gate means any workflow
    run can mint cloud credentials when the IAM trust policy is
    `repo:owner/repo:*` rather than
    `repo:owner/repo:environment:production`. Different concern from
    `static-aws-credentials` — that catches long-lived static keys, this
    one catches unscoped OIDC.

    Two firing shapes:
      1. Workflow-level `permissions.id-token: write` (or write-all) AND
         a job in that workflow with NO `environment:` block.
      2. Job-level `permissions.id-token: write` AND no `environment:`
         on the same job.

    A job that scopes to an `environment:` (which carries deployment
    protection rules) does NOT fire — that is the entire mitigation.
    """

    name = "id-token-write-unscoped"
    severity = SEV_HIGH
    description = "id-token: write without environment: gate"

    @staticmethod
    def _id_token_is_write(permissions) -> bool:
        if permissions is None:
            return False
        if isinstance(permissions, str):
            return permissions.strip().lower() in ("write-all",)
        if isinstance(permissions, dict):
            val = permissions.get("id-token")
            return isinstance(val, str) and val.strip().lower() == "write"
        return False

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        workflow_perm = wf.permissions("workflow")
        workflow_grants = self._id_token_is_write(workflow_perm)

        for job_id, job_hash in wf.jobs().items():
            if not isinstance(job_hash, dict):
                continue
            job_perm = job_hash.get("permissions")
            job_grants = self._id_token_is_write(job_perm)
            grants_id_token = workflow_grants or job_grants
            if not grants_id_token:
                continue
            # `environment:` may be a scalar (env name) or a mapping with
            # name/url — both gate the trust policy. Absence / empty
            # scalar = unscoped.
            env_field = job_hash.get("environment")
            has_environment = False
            if isinstance(env_field, str) and env_field.strip():
                has_environment = True
            elif isinstance(env_field, dict):
                name = env_field.get("name")
                if isinstance(name, str) and name.strip():
                    has_environment = True
            if has_environment:
                continue
            # Locate the line — prefer the job-level id-token: write line,
            # else the workflow-level one.
            line = 0
            if job_grants:
                # Find within the job's region.
                line = wf.line_of(re.compile(r"id-token:\s*write")) or 0
            if not line:
                line = wf.line_of(re.compile(r"id-token:\s*write")) or wf.line_of(
                    re.compile(r"permissions:\s*write-all")
                ) or 0
            findings.append(self._finding(
                wf,
                line=line,
                matched_text=(
                    "permissions: write-all"
                    if isinstance(workflow_perm, str)
                    and workflow_perm.strip().lower() == "write-all"
                    and not job_grants
                    else "id-token: write"
                ),
                description=(
                    f"Job `{job_id}` mints OIDC tokens (id-token: write) "
                    "without an environment: gate. Any branch run can "
                    "obtain cloud credentials when the IAM trust policy "
                    "is `repo:owner/repo:*`. Move id-token: write to job "
                    "level and add `environment: <name>` with deployment "
                    "protection rules; scope the cloud trust policy to "
                    "`repo:owner/repo:environment:<name>`."
                ),
            ))
        return findings


RULES = [
    WorkflowRunPwnCheckout(),
    MatrixStrategyInjection(),
    GithubAppSkipTokenRevoke(),
    ActionsAllowUnsecureCommands(),
    IdTokenWriteUnscoped(),
]
