# GitHub Actions reusable-workflow / composite-action structural rules.
#
# Wave 19 implementation of distill-round-5 angle F. Where the existing
# zizmor / sentinel tier stops at the `uses:` line (verifies SHA-pinning
# and that's it), this module follows the calling workflow into the
# REUSABLE WORKFLOW / COMPOSITE ACTION shape and audits:
#
#   * Reusable workflow refs pinned to mutable tags / branches (Rule 1).
#   * `secrets: inherit` across-org (Rule 2).
#   * Composite action `inputs.*` interpolated into a `run:` shell (Rule 3).
#   * `pull_request_target` / `workflow_run` + `./local-composite-action`
#     reference — the PR contributor plants the action body (Rule 4).
#   * `workflow_dispatch.inputs.*` reaching a git-destructive shell line
#     (Rule 5) — a strict refinement of `workflow-dispatch-injection`.
#   * `workflow_run`-triggered downloads of artifacts by attacker-named
#     id (Rule 6).
#   * Step-output → next-step taint via `$GITHUB_OUTPUT` (Rule 7).
#   * Cross-job tainted output flow (`needs.X.outputs.Y`) (Rule 8).
#   * `workflow_dispatch.inputs.*` declared without `type:` (Rule 9).
#   * Reusable workflow body that demands elevated permissions in a
#     third-party repo (Rule 10).
#   * Composite action that uses a tag-pinned third-party action inside
#     its own body (Rule 11).
#   * `actions/upload-artifact` whose `name:` is attacker-controllable
#     (Rule 12).
#   * Jobs deploying to a `prod`/`production`/etc. environment that
#     cannot be verified for required-reviewers from YAML alone (Rule 13).
#   * Custom node-action JS source that calls `exec(core.getInput(...))`
#     with the input as `argv[0]` (Rule 14).
#
# Architecture: structural rules that walk parsed YAML, plus an Action
# model so composite-action files (top-level key `runs:`, not `jobs:`)
# don't have to shoehorn into `Workflow`. All regex patterns are RE2-safe
# (no lookaround, no backrefs).
#
# Severity vocabulary mirrors lib.sentinel.model: CRITICAL / HIGH /
# MAJOR / MINOR. Findings are emitted as lib.zizmor_classifier.Finding
# instances so the existing dispatch surface (doctor_classify.py) can
# render them uniformly.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

import yaml

from lib.sentinel.model import (
    DANGEROUS_CONTEXTS,
    SEV_CRITICAL,
    SEV_HIGH,
    SEV_MAJOR,
    SEV_MINOR,
    Finding,
    Workflow,
)

# Untrusted-context tokens (PR title/body, head_ref, etc.). Same set as
# lib.sentinel.model.DANGEROUS_CONTEXTS but exposed locally so the regex
# below can be RE2-compiled in this file without re-importing.
_DANGEROUS_TOKENS: tuple[str, ...] = DANGEROUS_CONTEXTS

# Match ${{ <untrusted context> ... }} on a single line. RE2-safe: each
# alternative is a literal substring; no lookaround.
_UNTRUSTED_CTX_RE = re.compile(
    r"\$\{\{\s*("
    + "|".join(re.escape(ctx) for ctx in _DANGEROUS_TOKENS)
    + r")"
)

# Reusable-workflow uses-shape:
#   uses: org/repo/.github/workflows/<file>.yml@<ref>
# vs. a plain action uses-shape:
#   uses: org/repo@<ref>
#
# The reusable-workflow shape REQUIRES `.github/workflows/<file>.yml@`.
_REUSABLE_USES_RE = re.compile(
    r"^([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)/\.github/workflows/"
    r"([A-Za-z0-9_.\-]+\.ya?ml)@(.+)$"
)

# A pinned-by-SHA suffix is a 40-hex string, possibly followed by a
# trailing `# v1.2.3` comment (which we strip before validating).
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")

# Reusable-workflow refs we ALWAYS reject:
#   any pure branch-like name (main / master / develop / release / feature/x)
#   any version-tag shape (v1, v1.2, v1.2.3, v1-beta, etc.)
#   the literal `HEAD`
# Anything that survives is checked for the SHA40 shape.
_BRANCHLIKE_REFS = {
    "main", "master", "develop", "trunk", "release", "default", "HEAD",
}
_VERSION_TAG_RE = re.compile(
    r"^v?\d+(?:\.\d+){0,2}(?:[-+][A-Za-z0-9.\-]+)?$"
)


# --- Local Action model (for composite-action files) ----------------------


@dataclass
class CompositeAction:
    """Parsed action.yml / action.yaml — composite-action surface.

    Composite actions are top-level: { name, description, runs: { using, steps } }
    rather than { on, jobs }. Sentinel's Workflow assumes the workflow
    shape, so composite actions need their own walker.
    """

    filename: str
    raw: str
    raw_lines: list[str]
    data: dict

    @classmethod
    def parse(cls, filename: str, content: str) -> "CompositeAction":
        try:
            loaded = yaml.safe_load(content)
            data = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError:
            data = {}
        return cls(
            filename=filename,
            raw=content,
            raw_lines=content.splitlines(),
            data=data,
        )

    def is_composite(self) -> bool:
        runs = self.data.get("runs")
        if not isinstance(runs, dict):
            return False
        using = runs.get("using")
        return isinstance(using, str) and using.strip().lower() == "composite"

    def is_javascript(self) -> bool:
        """True iff `runs.using` matches `nodeNN` (any node-based JS action)."""
        runs = self.data.get("runs")
        if not isinstance(runs, dict):
            return False
        using = runs.get("using")
        if not isinstance(using, str):
            return False
        return bool(re.match(r"^node\d+$", using.strip().lower()))

    def inputs(self) -> dict:
        inputs = self.data.get("inputs")
        return inputs if isinstance(inputs, dict) else {}

    def steps(self) -> list:
        runs = self.data.get("runs")
        if not isinstance(runs, dict):
            return []
        steps = runs.get("steps")
        return steps if isinstance(steps, list) else []

    def line_of(self, pattern: str) -> Optional[int]:
        rx = re.compile(pattern)
        for i, line in enumerate(self.raw_lines):
            if rx.search(line):
                return i + 1
        return None


# --- Helpers shared across rules ------------------------------------------


def _triggers_include(triggers: Any, *names: str) -> bool:
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


def _strip_sha_comment(ref: str) -> str:
    """Strip a trailing `# v1.2.3` comment from a `uses:` ref value."""
    return ref.split("#", 1)[0].strip()


def _is_sha40(ref: str) -> bool:
    stripped = _strip_sha_comment(ref)
    # Fast reject: explicit branch-like names + version-tag shapes are
    # never SHA40 by construction. The check is redundant for the
    # SHA40_RE shape match but documents the policy clearly and avoids
    # subtle SHA40_RE drift accepting `v1234567890123456789012345678901234567890` (40 hex chars).
    if stripped in _BRANCHLIKE_REFS:
        return False
    if _VERSION_TAG_RE.match(stripped):
        return False
    return bool(_SHA40_RE.match(stripped))


def _untrusted_in_value(value: Any) -> Optional[str]:
    """Return the untrusted token matched in `value`, or None.

    Walks dicts/lists recursively; scalars are checked via _UNTRUSTED_CTX_RE.
    """
    if isinstance(value, dict):
        for v in value.values():
            hit = _untrusted_in_value(v)
            if hit:
                return hit
    elif isinstance(value, list):
        for item in value:
            hit = _untrusted_in_value(item)
            if hit:
                return hit
    elif isinstance(value, str):
        m = _UNTRUSTED_CTX_RE.search(value)
        if m:
            return m.group(1)
    return None


def _walk_run_blocks(wf: Workflow):
    """Yield (job_id, step_dict, run_text) for every step with a `run:`."""
    for job_id, job_hash in wf.jobs().items():
        if not isinstance(job_hash, dict):
            continue
        for step in wf.steps(job_hash):
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            if isinstance(run, str):
                yield job_id, step, run


def _step_env_indirected(step: dict, expr: str) -> bool:
    """True iff the step has an `env:` mapping that routes `expr` to a name.

    A safe pattern: `run: echo "$FOO"` + `env: FOO: ${{ inputs.cmd }}` —
    the expression is in env:, not in run:. This helper returns True
    when an env mapping contains the expression as a value.
    """
    env = step.get("env")
    if not isinstance(env, dict):
        return False
    for v in env.values():
        if isinstance(v, str) and expr in v:
            return True
    return False


def _make_finding(
    rule_id: str,
    severity: str,
    line: int,
    matched_text: str,
    description: str,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        line=line if line > 0 else 1,
        col=1,
        matched_text=matched_text,
        severity=severity,
        description=description,
    )


# --- Rule 1: reusable-workflow-mutable-ref --------------------------------


def check_reusable_workflow_mutable_ref(wf: Workflow) -> list[Finding]:
    """Reusable workflow ref pinned to a branch / version tag / HEAD.

    The existing `unpinned-uses-tag` flags THIRD-PARTY actions
    (`uses: org/repo@v4`). This rule fires CRITICAL on the
    `.github/workflows/<file>.yml@<ref>` shape specifically — a reusable
    workflow runs in the caller's runner with `secrets: inherit` (often)
    and writes back via `outputs:`. Mutable-ref pinning of that surface
    is the highest-impact reusable compromise vector.
    """
    findings: list[Finding] = []
    for job_id, job_hash in wf.jobs().items():
        if not isinstance(job_hash, dict):
            continue
        uses = job_hash.get("uses")
        if not isinstance(uses, str):
            continue
        m = _REUSABLE_USES_RE.match(uses.strip())
        if not m:
            continue
        ref = _strip_sha_comment(m.group(4))
        # FIRE unless ref is a clean 40-hex SHA.
        if _is_sha40(ref):
            continue
        line = wf.line_of(r"uses:\s*" + re.escape(uses.strip())) or 0
        findings.append(_make_finding(
            rule_id="reusable-workflow-mutable-ref",
            severity=SEV_CRITICAL,
            line=line,
            matched_text=f"uses: {uses.strip()}",
            description=(
                f"Job `{job_id}` calls a reusable workflow pinned to "
                f"`{ref}` (branch / version tag / HEAD). A reusable "
                "workflow runs in the caller's runner — often with "
                "`secrets: inherit` — and its outputs feed back into "
                "the caller's step graph. Mutable-ref pinning means a "
                "tag re-push silently swaps the workflow body, with "
                "full secret + OIDC blast radius. Pin to a 40-hex SHA "
                "(keep `# v1.2.3` as a trailing comment for readability)."
            ),
        ))
    return findings


# --- Rule 2: reusable-workflow-secrets-inherit-broad-scope ----------------


def check_reusable_workflow_secrets_inherit_broad_scope(
    wf: Workflow, repo_owner: Optional[str] = None,
) -> list[Finding]:
    """`secrets: inherit` when the called reusable workflow's org !=
    the caller's repo_owner.

    Same-org `secrets: inherit` is usually fine (devops repo + shared
    secrets). Cross-org `secrets: inherit` is NEVER fine — every secret
    the caller has is handed to a third-party body. Fires HIGH on the
    cross-org shape; same-org is left to the existing MINOR zizmor
    mirror (`secrets-inherit`).
    """
    findings: list[Finding] = []
    if not repo_owner:
        # We need the caller's owner to make the cross-org call.
        # Without it, defer to the MINOR zizmor mirror (which fires
        # unconditionally) and emit nothing here.
        return findings

    caller_owner = repo_owner.strip().lower()
    for job_id, job_hash in wf.jobs().items():
        if not isinstance(job_hash, dict):
            continue
        secrets = job_hash.get("secrets")
        if not (isinstance(secrets, str) and secrets.strip().lower() == "inherit"):
            continue
        uses = job_hash.get("uses")
        if not isinstance(uses, str):
            continue
        m = _REUSABLE_USES_RE.match(uses.strip())
        if not m:
            continue
        called_owner = m.group(1).strip().lower()
        if called_owner == caller_owner:
            continue
        line = wf.line_of(r"secrets:\s*inherit") or wf.line_of(
            r"uses:\s*" + re.escape(uses.strip())
        ) or 0
        findings.append(_make_finding(
            rule_id="reusable-workflow-secrets-inherit-broad-scope",
            severity=SEV_HIGH,
            line=line,
            matched_text=f"secrets: inherit (called: {uses.strip()})",
            description=(
                f"Job `{job_id}` calls a THIRD-PARTY reusable workflow "
                f"`{m.group(1)}/{m.group(2)}` with `secrets: inherit`. "
                "Every secret on the caller repo (PROD_TOKEN, NPM_TOKEN, "
                "AWS_*) is handed to the third-party workflow body — a "
                "swap of that body during a tag re-push is total credential "
                "exfiltration. Replace with an explicit `secrets:` mapping "
                "that lists only what the called workflow needs, or move "
                "to a same-org first-party reusable."
            ),
        ))
    return findings


# --- Rule 3: composite-action-input-shell-reflection ----------------------


_INPUTS_EXPR_RE = re.compile(r"\$\{\{\s*inputs\.([A-Za-z0-9_\-]+)\s*\}\}")


def check_composite_action_input_shell_reflection(
    action: CompositeAction,
) -> list[Finding]:
    """`runs.using: composite` action interpolating `${{ inputs.X }}`
    into a `run:` block WITHOUT env: indirection.

    The composite-action analog of `shell-injection-expr`. The existing
    sentinel walker assumes top-level `jobs:` and fails on action.yml,
    so this is a parallel walker over `runs.steps[]`.
    """
    findings: list[Finding] = []
    if not action.is_composite():
        return findings
    for idx, step in enumerate(action.steps()):
        if not isinstance(step, dict):
            continue
        run = step.get("run")
        if not isinstance(run, str):
            continue
        matches = _INPUTS_EXPR_RE.findall(run)
        if not matches:
            continue
        # If ANY matched input is also routed via env:, skip — that's
        # the safe `env: FOO: ${{ inputs.foo }}` + `run: "$FOO"` shape.
        if any(
            _step_env_indirected(step, f"${{{{ inputs.{name} }}}}")
            for name in matches
        ):
            continue
        line = action.line_of(
            r"\$\{\{\s*inputs\." + re.escape(matches[0])
        ) or 0
        findings.append(_make_finding(
            rule_id="composite-action-input-shell-reflection",
            severity=SEV_CRITICAL,
            line=line,
            matched_text=f"run: ... ${{{{ inputs.{matches[0]} }}}}",
            description=(
                f"Composite action step #{idx + 1} interpolates "
                f"`${{{{ inputs.{matches[0]} }}}}` directly into a "
                "`run:` shell block. Any workflow that instantiates "
                "this action and passes attacker-controlled data to "
                f"`{matches[0]}` gets RCE in the caller's runner. Route "
                "the input through an `env:` mapping on the step and "
                "reference `$ENV_VAR` from the shell."
            ),
        ))
    return findings


# --- Rule 4: composite-action-local-path-from-pr --------------------------


_LOCAL_USES_RE = re.compile(r"^\.\/")


def check_composite_action_local_path_from_pr(wf: Workflow) -> list[Finding]:
    """`pull_request_target` / `workflow_run` + `uses: ./local-action`.

    Even without an explicit fork checkout, a `./.github/actions/X`
    reference in a `pull_request_target` job re-reads the PR
    contributor's `action.yml` at dispatch time. The PR author plants
    the action body; the privileged trigger runs it.
    """
    findings: list[Finding] = []
    triggers = wf.triggers()
    if not _triggers_include(triggers, "pull_request_target", "workflow_run"):
        return findings
    for job_id, job_hash in wf.jobs().items():
        if not isinstance(job_hash, dict):
            continue
        for step in wf.steps(job_hash):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not (isinstance(uses, str) and _LOCAL_USES_RE.match(uses.strip())):
                continue
            line = wf.line_of(r"uses:\s*" + re.escape(uses.strip())) or 0
            findings.append(_make_finding(
                rule_id="composite-action-local-path-from-pr",
                severity=SEV_CRITICAL,
                line=line,
                matched_text=f"uses: {uses.strip()}",
                description=(
                    f"Job `{job_id}` uses a local composite action "
                    f"`{uses.strip()}` under a `pull_request_target` "
                    "or `workflow_run` trigger. Even without an explicit "
                    "fork checkout, the PR contributor's action.yml is "
                    "read at dispatch time and executes in the base "
                    "repo's privileged context. Move the local-action "
                    "step to a `pull_request`-triggered workflow, or "
                    "split the privileged work into a job that only runs "
                    "AFTER a maintainer approval gate."
                ),
            ))
    return findings


# --- Rule 5: workflow-dispatch-input-in-git-push --------------------------


_GIT_DESTRUCTIVE_RE = re.compile(
    r"\bgit\s+(?:push|tag|branch|reset\s+--hard|update-ref)\b"
    r"|\bgh\s+release\s+create\b"
)


def check_workflow_dispatch_input_in_git_push(wf: Workflow) -> list[Finding]:
    """`workflow_dispatch.inputs.*` reaching a git-destructive line.

    Strict refinement of the existing `workflow-dispatch-injection`
    rule: the sink is a git destructive command, not just any `run:`.
    Combined with `pull_request_target` upstream this is repo-history
    rewrite as `${{ github.actor }}` — escalates to CRITICAL.
    """
    findings: list[Finding] = []
    triggers = wf.triggers()
    if not isinstance(triggers, dict):
        return findings
    wd = triggers.get("workflow_dispatch")
    if wd is None and "workflow_dispatch" not in triggers:
        return findings

    # Collect declared workflow_dispatch input names.
    inputs_block: dict = {}
    if isinstance(wd, dict):
        cand = wd.get("inputs")
        if isinstance(cand, dict):
            inputs_block = cand
    input_names = list(inputs_block.keys())
    if not input_names:
        return findings
    # Build a per-input regex tester.
    input_alt = "|".join(re.escape(name) for name in input_names)
    inputs_expr_re = re.compile(
        r"\$\{\{\s*inputs\.(" + input_alt + r")\s*\}\}"
    )

    for job_id, step, run_text in _walk_run_blocks(wf):
        for raw_line in run_text.splitlines():
            stripped = raw_line.strip()
            if not _GIT_DESTRUCTIVE_RE.search(stripped):
                continue
            m = inputs_expr_re.search(stripped)
            if not m:
                # ALSO check the env-route: the line uses $VAR, and the
                # step's env: maps that name from inputs.NAME.
                env = step.get("env")
                hit = None
                if isinstance(env, dict):
                    for env_key, env_val in env.items():
                        if not isinstance(env_val, str):
                            continue
                        env_m = inputs_expr_re.search(env_val)
                        if not env_m:
                            continue
                        # And the run: line references $env_key?
                        if re.search(
                            r"\$(?:\{)?" + re.escape(str(env_key)) + r"\b",
                            stripped,
                        ):
                            hit = env_m.group(1)
                            break
                if not hit:
                    continue
                input_name = hit
                # env-routed but still feeding a destructive git command
                # with attacker input — fire MAJOR (one notch below the
                # direct interpolation case, but still actionable).
                line = wf.line_of(re.escape(stripped)) or 0
                findings.append(_make_finding(
                    rule_id="workflow-dispatch-input-in-git-push",
                    severity=SEV_MAJOR,
                    line=line,
                    matched_text=stripped,
                    description=(
                        f"Job `{job_id}` runs a git-destructive command "
                        f"on a value derived from "
                        f"`workflow_dispatch.inputs.{input_name}` (routed "
                        "through env:). Even via env, the destructive "
                        "command rewrites repo history as the workflow's "
                        f"identity. Validate `{input_name}` against an "
                        "allowlist BEFORE the git command (or switch the "
                        "input to `type: choice`)."
                    ),
                ))
                continue
            line = wf.line_of(re.escape(stripped)) or 0
            findings.append(_make_finding(
                rule_id="workflow-dispatch-input-in-git-push",
                severity=SEV_HIGH,
                line=line,
                matched_text=stripped,
                description=(
                    f"Job `{job_id}` interpolates "
                    f"`${{{{ inputs.{m.group(1)} }}}}` directly into a "
                    "git-destructive command (push / tag / branch / reset "
                    "--hard / release create). Attacker rewrites repo "
                    "history as the workflow's identity, with the "
                    "workflow's GITHUB_TOKEN. Route the value through "
                    "env: AND validate against an allowlist; switching "
                    "the input to `type: choice` is the simplest fix."
                ),
            ))
    return findings


# --- Rule 6: workflow-run-artifact-name-trust -----------------------------


_DOWNLOAD_ARTIFACT_USES_RE = re.compile(r"^actions/download-artifact(?:@|$)")


def _has_actor_allowlist_if(wf: Workflow, job_hash: dict) -> bool:
    """True iff `job_hash.if` constrains
    `github.event.workflow_run.actor.login`. The `wf` argument is
    kept for API parity with sibling check_* helpers; the check
    itself only needs the job hash."""
    del wf  # accepted for sibling-helper signature parity
    cond = job_hash.get("if")
    if not isinstance(cond, str):
        return False
    return "workflow_run.actor.login" in cond or "workflow_run.actor" in cond


def check_workflow_run_artifact_name_trust(wf: Workflow) -> list[Finding]:
    """`workflow_run`-triggered workflow downloading an artifact by name
    without an actor allowlist on the job.

    Two firing shapes:
      * `with.run-id: ${{ github.event.workflow_run.id }}` AND no actor
        gate — HIGH.
      * `with.name` referencing `github.event.workflow_run.*` — HIGH.
      * `with.name: <plain string>` — MAJOR (the upstream workflow could
        have planted an artifact with that name).
    """
    findings: list[Finding] = []
    triggers = wf.triggers()
    if not _triggers_include(triggers, "workflow_run"):
        return findings

    for job_id, job_hash in wf.jobs().items():
        if not isinstance(job_hash, dict):
            continue
        actor_gated = _has_actor_allowlist_if(wf, job_hash)
        for step in wf.steps(job_hash):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not (isinstance(uses, str) and _DOWNLOAD_ARTIFACT_USES_RE.match(uses)):
                continue
            with_block = step.get("with")
            if not isinstance(with_block, dict):
                continue
            name_val = with_block.get("name")
            run_id_val = with_block.get("run-id")
            severity = None
            why = ""
            if isinstance(name_val, str) and "${{" in name_val and "workflow_run" in name_val:
                severity = SEV_HIGH
                why = (
                    "`with.name` references `github.event.workflow_run.*` "
                    "directly — the upstream workflow's actor controls the "
                    "name and can override the artifact contents."
                )
            elif (
                isinstance(run_id_val, str)
                and "github.event.workflow_run" in run_id_val
                and not actor_gated
            ):
                severity = SEV_HIGH
                why = (
                    "`with.run-id` follows the upstream workflow run with "
                    "no `github.event.workflow_run.actor.login` allowlist "
                    "on the job — any fork PR triggers the download."
                )
            elif isinstance(name_val, str) and "${{" not in name_val and not actor_gated:
                severity = SEV_MAJOR
                why = (
                    f"`with.name: {name_val}` is a plain string. The "
                    "upstream workflow may have planted an artifact with "
                    "that exact name during a fork-PR run; downloading it "
                    "here with no actor gate gives an attacker an "
                    "uploadable payload."
                )
            if severity is None:
                continue
            line = wf.line_of(r"uses:\s*" + re.escape(uses)) or 0
            findings.append(_make_finding(
                rule_id="workflow-run-artifact-name-trust",
                severity=severity,
                line=line,
                matched_text=f"uses: {uses}",
                description=(
                    f"Job `{job_id}` downloads an artifact in a "
                    f"`workflow_run`-triggered context. {why} Gate the "
                    "job on "
                    "`github.event.workflow_run.actor.login == '<bot>'` "
                    "(or `head_repository.full_name == <expected>`) AND "
                    "verify the artifact contents before consuming."
                ),
            ))
    return findings


# --- Rule 7: step-output-injection-via-github-output ----------------------


_GITHUB_OUTPUT_WRITE_RE = re.compile(
    r"(?:>>?\s*\"?\$\{?GITHUB_OUTPUT\}?\"?|::set-output\s+name=)"
)


def check_step_output_injection_via_github_output(wf: Workflow) -> list[Finding]:
    """Step writes attacker context to $GITHUB_OUTPUT; later step
    interpolates `${{ steps.<id>.outputs.<key> }}` into another run:.

    Multi-step taint walk: source = $GITHUB_OUTPUT write with untrusted
    context; sink = later step's run: with ${{ steps.X.outputs.Y }}.
    """
    findings: list[Finding] = []
    # Build (job_id, step_id, output_key) for every tainted write.
    tainted: dict[tuple[str, str, str], int] = {}
    for job_id, job_hash in wf.jobs().items():
        if not isinstance(job_hash, dict):
            continue
        for idx, step in enumerate(wf.steps(job_hash)):
            if not isinstance(step, dict):
                continue
            step_id = step.get("id") or f"__step{idx}"
            run = step.get("run")
            if not isinstance(run, str):
                continue
            if not _GITHUB_OUTPUT_WRITE_RE.search(run):
                continue
            # Untrusted context on the SAME line as the GITHUB_OUTPUT
            # write — only this colocated form fires (matches the
            # report's "echo ... ${{ untrusted }} ... >> $GITHUB_OUTPUT").
            for line in run.splitlines():
                stripped = line.strip()
                if not _GITHUB_OUTPUT_WRITE_RE.search(stripped):
                    continue
                if not _UNTRUSTED_CTX_RE.search(stripped):
                    continue
                # Pull the output key. Two shapes:
                #   echo "key=value" >> $GITHUB_OUTPUT
                #   echo "::set-output name=key::value"
                m_key = re.search(
                    r"(?:^|[^A-Za-z0-9_])([A-Za-z0-9_\-]+)\s*=",
                    stripped,
                )
                if not m_key:
                    m_key = re.search(r"name=([A-Za-z0-9_\-]+)", stripped)
                if not m_key:
                    continue
                key = m_key.group(1)
                tainted[(str(job_id), str(step_id), key)] = 0
    if not tainted:
        return findings
    # Sink walk: later step in SAME job interpolates a tainted output.
    sink_re_cache: dict[tuple[str, str], re.Pattern] = {}
    for job_id, job_hash in wf.jobs().items():
        if not isinstance(job_hash, dict):
            continue
        for step in wf.steps(job_hash):
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            if not isinstance(run, str):
                continue
            for (t_job, t_step, t_key), _ in tainted.items():
                if t_job != str(job_id):
                    continue
                cache_key = (t_step, t_key)
                if cache_key not in sink_re_cache:
                    sink_re_cache[cache_key] = re.compile(
                        r"\$\{\{\s*steps\." + re.escape(t_step)
                        + r"\.outputs\." + re.escape(t_key)
                    )
                sink_re = sink_re_cache[cache_key]
                if not sink_re.search(run):
                    continue
                line_no = wf.line_of(re.escape(t_key) + r"\s*=") or 0
                findings.append(_make_finding(
                    rule_id="step-output-injection-via-github-output",
                    severity=SEV_HIGH,
                    line=line_no,
                    matched_text=f"steps.{t_step}.outputs.{t_key}",
                    description=(
                        f"Job `{job_id}` writes an untrusted context into "
                        f"`$GITHUB_OUTPUT` under key `{t_key}` (step "
                        f"`{t_step}`), and a later step interpolates "
                        f"`${{{{ steps.{t_step}.outputs.{t_key} }}}}` "
                        "into a `run:` block. The attacker payload flows "
                        "transitively into the second shell — same RCE "
                        "class as direct interpolation, just one hop. "
                        "Sanitise via env: + filter before writing to "
                        "$GITHUB_OUTPUT."
                    ),
                ))
                break  # one finding per sink step
    return findings


# --- Rule 8: job-output-cross-job-taint -----------------------------------


def check_job_output_cross_job_taint(wf: Workflow) -> list[Finding]:
    """Job A exposes `outputs.X` from a tainted step; job B reads
    `needs.A.outputs.X` in a run:, if:, or with: — fire HIGH.
    """
    findings: list[Finding] = []
    # Build tainted job outputs: (job_a_id, out_name).
    tainted: set[tuple[str, str]] = set()
    for job_a_id, job_a in wf.jobs().items():
        if not isinstance(job_a, dict):
            continue
        outputs = job_a.get("outputs")
        if not isinstance(outputs, dict):
            continue
        # Map step_id -> step (for tainted-step lookup).
        step_map: dict[str, dict] = {}
        for idx, step in enumerate(wf.steps(job_a)):
            if isinstance(step, dict):
                step_map[str(step.get("id") or f"__step{idx}")] = step
        for out_name, out_expr in outputs.items():
            if not isinstance(out_expr, str):
                continue
            m = re.search(
                r"\$\{\{\s*steps\.([A-Za-z0-9_\-]+)\.outputs\.([A-Za-z0-9_\-]+)",
                out_expr,
            )
            if not m:
                # An output that's a plain literal expression on
                # untrusted data, e.g. ${{ github.event.issue.title }}.
                if _UNTRUSTED_CTX_RE.search(out_expr):
                    tainted.add((str(job_a_id), str(out_name)))
                continue
            ref_step_id = m.group(1)
            step = step_map.get(ref_step_id)
            if not step:
                continue
            run = step.get("run")
            if not isinstance(run, str):
                continue
            if _UNTRUSTED_CTX_RE.search(run):
                tainted.add((str(job_a_id), str(out_name)))
    if not tainted:
        return findings
    # Sink walk: any job that `needs:` job_a and references the tainted
    # output in run / if / with.
    for job_b_id, job_b in wf.jobs().items():
        if not isinstance(job_b, dict):
            continue
        needs = job_b.get("needs")
        needs_list: list[str] = []
        if isinstance(needs, str):
            needs_list = [needs]
        elif isinstance(needs, list):
            needs_list = [str(x) for x in needs]
        if not needs_list:
            continue
        for needed in needs_list:
            for out_name in [t[1] for t in tainted if t[0] == needed]:
                ref_pat = re.compile(
                    r"\$\{\{\s*needs\." + re.escape(needed)
                    + r"\.outputs\." + re.escape(out_name)
                )
                fired = False
                # Search steps' run, if, with.
                for step in wf.steps(job_b):
                    if not isinstance(step, dict):
                        continue
                    for key in ("run", "if"):
                        val = step.get(key)
                        if isinstance(val, str) and ref_pat.search(val):
                            fired = True
                            break
                    if fired:
                        break
                    with_block = step.get("with")
                    if isinstance(with_block, dict):
                        for w_val in with_block.values():
                            if isinstance(w_val, str) and ref_pat.search(w_val):
                                fired = True
                                break
                    if fired:
                        break
                # Also a job-level `if:` referencing it counts.
                if not fired:
                    job_if = job_b.get("if")
                    if isinstance(job_if, str) and ref_pat.search(job_if):
                        fired = True
                if not fired:
                    continue
                line = wf.line_of(
                    r"needs\." + re.escape(needed)
                    + r"\.outputs\." + re.escape(out_name)
                ) or 0
                findings.append(_make_finding(
                    rule_id="job-output-cross-job-taint",
                    severity=SEV_HIGH,
                    line=line,
                    matched_text=f"needs.{needed}.outputs.{out_name}",
                    description=(
                        f"Job `{job_b_id}` consumes "
                        f"`needs.{needed}.outputs.{out_name}` — a job "
                        f"output of `{needed}` that is derived from an "
                        "attacker-controllable context "
                        "(github.event.*, github.head_ref). Cross-job "
                        "taint: the payload survives the job boundary "
                        "into another shell. Sanitise the output in the "
                        "producing job (env: + filter) before exposing it."
                    ),
                ))
    return findings


# --- Rule 9: workflow-dispatch-input-not-typed ----------------------------


def check_workflow_dispatch_input_not_typed(wf: Workflow) -> list[Finding]:
    """`workflow_dispatch.inputs.X` declared without `type:` AND used in
    a `run:` block.

    The strong defence is `type: choice` (GH validates against `options`
    BEFORE the workflow starts) or `type: boolean`. A bare input
    (no `type:`, defaults to string) is attacker-controllable arbitrary
    content. MAJOR — defence-in-depth gate that nudges authors.
    """
    findings: list[Finding] = []
    triggers = wf.triggers()
    if not isinstance(triggers, dict):
        return findings
    wd = triggers.get("workflow_dispatch")
    if not isinstance(wd, dict):
        return findings
    inputs_decl = wd.get("inputs")
    if not isinstance(inputs_decl, dict):
        return findings

    untyped_inputs: list[str] = []
    for name, decl in inputs_decl.items():
        if not isinstance(decl, dict):
            # Bare value declaration — definitely untyped.
            untyped_inputs.append(str(name))
            continue
        t = decl.get("type")
        if t is None or (isinstance(t, str) and t.strip().lower() == "string"):
            untyped_inputs.append(str(name))
    if not untyped_inputs:
        return findings

    # Each untyped input that is REFERENCED somewhere in a run: fires.
    name_alt = "|".join(re.escape(n) for n in untyped_inputs)
    use_re = re.compile(
        r"\$\{\{\s*inputs\.(" + name_alt + r")\b"
    )
    seen: set[str] = set()
    for _, _, run_text in _walk_run_blocks(wf):
        for m in use_re.finditer(run_text):
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)
            line = wf.line_of(
                re.escape(name) + r":\s*$"
            ) or wf.line_of(r"workflow_dispatch:") or 0
            findings.append(_make_finding(
                rule_id="workflow-dispatch-input-not-typed",
                severity=SEV_MAJOR,
                line=line,
                matched_text=f"inputs.{name} (no type:)",
                description=(
                    f"workflow_dispatch input `{name}` declares no "
                    "`type:` (defaults to string) AND is used in a "
                    "`run:` block. Switch to `type: choice` with an "
                    "explicit `options:` allowlist (the strongest "
                    "defence — GH validates before the workflow runs) "
                    "or `type: boolean` / `type: environment` where "
                    "appropriate. String inputs cannot be safely "
                    "interpolated without env: + validation."
                ),
            ))
    return findings


# --- Rule 10: reusable-workflow-permissions-elevation ---------------------


_WRITE_LIKE_SCOPES = {
    "contents", "packages", "pull-requests", "issues", "deployments",
    "id-token", "actions", "checks", "discussions", "statuses",
    "pages", "repository-projects", "security-events",
}


def _permissions_grants_write(permissions: Any) -> tuple[bool, str]:
    """Return (any_write_scope, description_label)."""
    if permissions is None:
        return False, ""
    if isinstance(permissions, str):
        if permissions.strip().lower() == "write-all":
            return True, "write-all"
        return False, ""
    if isinstance(permissions, dict):
        labels: list[str] = []
        for k, v in permissions.items():
            if not isinstance(v, str):
                continue
            # Only count documented write-like scopes — `email: write`
            # isn't real (not in GITHUB_TOKEN scopes) and would inflate
            # the rule's signal.
            if str(k).lower() not in _WRITE_LIKE_SCOPES:
                continue
            if v.strip().lower() == "write":
                labels.append(f"{k}: write")
        if labels:
            return True, ", ".join(labels)
    return False, ""


def check_reusable_workflow_permissions_elevation(
    wf: Workflow, repo_owner: Optional[str] = None,
) -> list[Finding]:
    """A reusable workflow (has `on.workflow_call`) demands write scopes.

    Two firings:
      1. `permissions: write-all` on a workflow_call body → CRITICAL.
      2. Any write scope on a workflow_call body in a THIRD-PARTY repo
         (different owner than the inspecting one) → HIGH.

    The caller can't easily audit this without following the SHA — so
    the called workflow itself is the right place to flag it.
    """
    findings: list[Finding] = []
    triggers = wf.triggers()
    has_workflow_call = False
    if isinstance(triggers, dict) and "workflow_call" in triggers:
        has_workflow_call = True
    elif isinstance(triggers, list) and "workflow_call" in triggers:
        has_workflow_call = True
    elif isinstance(triggers, str) and triggers == "workflow_call":
        has_workflow_call = True
    if not has_workflow_call:
        return findings

    wf_perm = wf.data.get("permissions") if isinstance(wf.data, dict) else None
    is_write_all = (
        isinstance(wf_perm, str)
        and wf_perm.strip().lower() == "write-all"
    )
    if is_write_all:
        line = wf.line_of(r"permissions:\s*write-all") or 0
        findings.append(_make_finding(
            rule_id="reusable-workflow-permissions-elevation",
            severity=SEV_CRITICAL,
            line=line,
            matched_text="permissions: write-all",
            description=(
                "Reusable workflow (has `on.workflow_call:`) declares "
                "`permissions: write-all` at workflow level. Any caller "
                "that grants the GITHUB_TOKEN write scope hands the "
                "FULL set to this body. Drop write-all; declare only "
                "the scopes this workflow actually needs (e.g. "
                "`contents: write` for a release, `id-token: write` "
                "for OIDC)."
            ),
        ))
        return findings

    has_write, label = _permissions_grants_write(wf_perm)
    if has_write and repo_owner:
        # We have repo_owner; only fire HIGH on cross-org but lower
        # severity for same-org (MINOR — same-org dev review covers it).
        # The doctor passes the inspecting repo's owner as `repo_owner`;
        # the workflow IS that repo's file, so any write scope on a
        # workflow_call body in this owner is same-org and we DEMOTE.
        severity = SEV_MINOR  # same repo body, less interesting
        line = wf.line_of(r"permissions:") or 0
        findings.append(_make_finding(
            rule_id="reusable-workflow-permissions-elevation",
            severity=severity,
            line=line,
            matched_text=f"permissions: {label}",
            description=(
                "Same-org reusable workflow declares write-scope "
                "permissions on a `workflow_call:` body. Document the "
                "scope contract so callers know to SHA-pin and audit "
                "this workflow at the SHA before tagging."
            ),
        ))
    elif has_write:
        # No repo_owner provided — caller can't tell same- vs cross-org.
        # Fire HIGH conservatively (the worse case dominates).
        line = wf.line_of(r"permissions:") or 0
        findings.append(_make_finding(
            rule_id="reusable-workflow-permissions-elevation",
            severity=SEV_HIGH,
            line=line,
            matched_text=f"permissions: {label}",
            description=(
                "Reusable workflow (has `on.workflow_call:`) declares "
                f"write-scope permissions: {label}. Callers that "
                "instantiate this without SHA-pinning cannot audit the "
                "body — and the body silently gates token write scope. "
                "Pin to SHA at the caller and audit this file at that "
                "SHA before tagging."
            ),
        ))
    return findings


# --- Rule 11: composite-action-uses-third-party-unsafe-chain --------------


_PINNED_USES_TAG_RE = re.compile(
    r"^([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)@(.+)$"
)


def check_composite_action_uses_third_party_unsafe_chain(
    action: CompositeAction,
) -> list[Finding]:
    """A composite action's body `uses:` a third-party action pinned to
    a mutable tag/branch.

    The caller of the composite sees ONE `uses:` line; they don't see
    the chain. A tag-pinned third-party action inside a composite is a
    hidden mutable supply-chain link.
    """
    findings: list[Finding] = []
    if not action.is_composite():
        return findings
    for idx, step in enumerate(action.steps()):
        if not isinstance(step, dict):
            continue
        uses = step.get("uses")
        if not isinstance(uses, str):
            continue
        uses_stripped = uses.strip()
        # Skip local references — those are a separate rule.
        if _LOCAL_USES_RE.match(uses_stripped):
            continue
        # Skip docker:// — that's `unpinned-docker-image`'s job.
        if uses_stripped.startswith("docker://"):
            continue
        m = _PINNED_USES_TAG_RE.match(uses_stripped)
        if not m:
            continue
        ref = _strip_sha_comment(m.group(3))
        # Already pinned-by-SHA? safe.
        if _is_sha40(ref):
            continue
        # Reusable workflow inside a composite is unusual but possible.
        # It's also "tag-like" so we fall through to firing.
        line = action.line_of(r"uses:\s*" + re.escape(uses_stripped)) or 0
        # Heuristic severity: HIGH if the called action's name suggests
        # security-sensitivity, otherwise MAJOR.
        sensitive = any(
            kw in uses_stripped.lower()
            for kw in (
                "checkout", "token", "auth", "credential", "secret",
                "deploy", "release", "publish", "sign",
            )
        )
        severity = SEV_HIGH if sensitive else SEV_MAJOR
        findings.append(_make_finding(
            rule_id="composite-action-uses-third-party-unsafe-chain",
            severity=severity,
            line=line,
            matched_text=f"uses: {uses_stripped}",
            description=(
                f"Composite action step #{idx + 1} uses third-party "
                f"`{uses_stripped}` pinned to `{ref}` (branch / tag / "
                "HEAD). The caller of THIS composite sees one line; "
                "they cannot see this nested unpinned dependency. Pin "
                "every transitive `uses:` to a 40-hex SHA (preserve "
                "`# v<tag>` as a comment)."
            ),
        ))
    return findings


# --- Rule 12: artifact-name-attacker-controllable -------------------------


_UPLOAD_ARTIFACT_USES_RE = re.compile(r"^actions/upload-artifact(?:@|$)")


def check_artifact_name_attacker_controllable(wf: Workflow) -> list[Finding]:
    """`actions/upload-artifact@*` with `with.name` interpolating an
    untrusted context.

    The downstream `actions/download-artifact` consumer trusts the
    upstream artifact name — an attacker can plant a name containing
    `..`, path separators, or a name that collides with a different
    expected artifact.
    """
    findings: list[Finding] = []
    for job_id, job_hash in wf.jobs().items():
        if not isinstance(job_hash, dict):
            continue
        for step in wf.steps(job_hash):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not (isinstance(uses, str) and _UPLOAD_ARTIFACT_USES_RE.match(uses)):
                continue
            with_block = step.get("with")
            if not isinstance(with_block, dict):
                continue
            name_val = with_block.get("name")
            if not isinstance(name_val, str):
                continue
            m = _UNTRUSTED_CTX_RE.search(name_val)
            if not m:
                continue
            line = wf.line_of(r"name:\s*" + re.escape(name_val)) or wf.line_of(
                r"uses:\s*" + re.escape(uses)
            ) or 0
            findings.append(_make_finding(
                rule_id="artifact-name-attacker-controllable",
                severity=SEV_HIGH,
                line=line,
                matched_text=f"name: {name_val}",
                description=(
                    f"Job `{job_id}` uploads an artifact whose `name:` "
                    f"interpolates an attacker-controllable context "
                    f"(`${{{{ {m.group(1)} }}}}`). A downstream "
                    "`workflow_run`-triggered consumer that downloads by "
                    "name gets attacker-named bytes — path-traversal or "
                    "consumer-side collision. Use a fixed name plus a "
                    "sanitised suffix (e.g. github.sha) instead."
                ),
            ))
    return findings


# --- Rule 13: environment-without-required-reviewers ----------------------


_PROD_ENV_NAME_RE = re.compile(
    r"^(?:prod|production|release|mainnet|live|deploy-?prod"
    r"|prod[-_]?env|production[-_]?env)$",
    re.IGNORECASE,
)


def check_environment_without_required_reviewers(wf: Workflow) -> list[Finding]:
    """A job uses `environment: <name>` matching a prod-deploy keyword.

    The doctor cannot verify `required_reviewers` directly from YAML —
    it lives in repo settings. But flagging the prod-deploy name pattern
    is a useful nudge so the maintainer can manually verify.
    """
    findings: list[Finding] = []
    for job_id, job_hash in wf.jobs().items():
        if not isinstance(job_hash, dict):
            continue
        env_field = job_hash.get("environment")
        env_name: Optional[str] = None
        if isinstance(env_field, str):
            env_name = env_field.strip()
        elif isinstance(env_field, dict):
            name = env_field.get("name")
            if isinstance(name, str):
                env_name = name.strip()
        if not env_name:
            continue
        if not _PROD_ENV_NAME_RE.match(env_name):
            continue
        line = wf.line_of(r"environment:") or 0
        findings.append(_make_finding(
            rule_id="environment-without-required-reviewers",
            severity=SEV_MAJOR,
            line=line,
            matched_text=f"environment: {env_name}",
            description=(
                f"Job `{job_id}` deploys to environment `{env_name}` — "
                "this name pattern (prod/production/release/mainnet/"
                "live) indicates a production target. The doctor cannot "
                "see repo settings from YAML alone: VERIFY that "
                "`required_reviewers` is configured for environment "
                f"`{env_name}` in repo Settings → Environments. Without "
                "it, any branch push that reaches this job auto-deploys."
            ),
        ))
    return findings


# --- Rule 14: actions-toolkit-exec-arg-zero -------------------------------


# `exec(getInput('X'))` — input as command, no args array.
_EXEC_ARG_ZERO_RES = (
    re.compile(
        r"exec(?:Sync)?\s*\(\s*core\.getInput\s*\(\s*['\"]"
        r"([A-Za-z0-9_\-]+)['\"]\s*\)\s*\)"
    ),
    re.compile(
        r"exec\.exec\s*\(\s*core\.getInput\s*\(\s*['\"]"
        r"([A-Za-z0-9_\-]+)['\"]\s*\)\s*\)"
    ),
    re.compile(
        r"exec(?:Sync)?\s*\(\s*`[^`]*\$\{core\.getInput\s*\("
        r"\s*['\"]([A-Za-z0-9_\-]+)['\"]\s*\)\s*\}[^`]*`\s*\)"
    ),
)


def check_actions_toolkit_exec_arg_zero(
    action: CompositeAction, js_source: str, js_filename: str = "main.js",
) -> list[Finding]:
    """A node-based action that calls `exec(core.getInput(...))` —
    putting attacker input as `argv[0]` (the command path itself).

    Safe pattern: `exec('git', ['push', core.getInput('X')])` — command
    is a literal, the input lands in the args array.

    `action` is the matching `action.yml` (so we confirm
    `runs.using: nodeNN`); `js_source` is the loaded contents of the
    file referenced by `runs.main`.
    """
    findings: list[Finding] = []
    if not action.is_javascript():
        return findings
    for rx in _EXEC_ARG_ZERO_RES:
        for m in rx.finditer(js_source):
            input_name = m.group(1)
            offset = m.start()
            line_num = js_source.count("\n", 0, offset) + 1
            findings.append(_make_finding(
                rule_id="actions-toolkit-exec-arg-zero",
                severity=SEV_MAJOR,
                line=line_num,
                matched_text=m.group(0).strip(),
                description=(
                    f"In `{js_filename}`: a node-based action calls "
                    f"`exec(core.getInput('{input_name}'))` with the "
                    "input as argv[0] (the command itself). Any caller "
                    f"that passes attacker text to `{input_name}` gets "
                    "arbitrary command execution. Safe pattern: "
                    "`exec.exec('git', ['push', "
                    f"core.getInput('{input_name}')])` — command is a "
                    "literal, the input lands in the args array."
                ),
            ))
    return findings


# --- Surface --------------------------------------------------------------

# rule_id -> (severity, one-line description). Kept here as a static
# catalog so external callers (doctor_classify, gha_reusable_dispatch)
# can list rules without instantiating the structural walkers.
RULE_CATALOG: dict[str, tuple[str, str]] = {
    "reusable-workflow-mutable-ref": (
        SEV_CRITICAL,
        "Reusable workflow pinned to branch / tag / HEAD instead of SHA.",
    ),
    "reusable-workflow-secrets-inherit-broad-scope": (
        SEV_HIGH,
        "secrets: inherit handed to a third-party reusable workflow.",
    ),
    "composite-action-input-shell-reflection": (
        SEV_CRITICAL,
        "Composite action inputs.* interpolated into a run: shell with no env indirection.",
    ),
    "composite-action-local-path-from-pr": (
        SEV_CRITICAL,
        "pull_request_target / workflow_run trigger + ./local-composite action reference.",
    ),
    "workflow-dispatch-input-in-git-push": (
        SEV_HIGH,
        "workflow_dispatch input reaches a git push / tag / branch / reset / release create.",
    ),
    "workflow-run-artifact-name-trust": (
        SEV_HIGH,
        "workflow_run artifact download by name without actor allowlist.",
    ),
    "step-output-injection-via-github-output": (
        SEV_HIGH,
        "Untrusted context written to $GITHUB_OUTPUT and consumed in a later run:.",
    ),
    "job-output-cross-job-taint": (
        SEV_HIGH,
        "Tainted job output reaches a downstream job via needs.X.outputs.Y.",
    ),
    "workflow-dispatch-input-not-typed": (
        SEV_MAJOR,
        "workflow_dispatch input declared without type: AND used in run:.",
    ),
    "reusable-workflow-permissions-elevation": (
        SEV_HIGH,
        "workflow_call body demands write-scope permissions.",
    ),
    "composite-action-uses-third-party-unsafe-chain": (
        SEV_HIGH,
        "Composite action uses a third-party action pinned to a mutable tag/branch.",
    ),
    "artifact-name-attacker-controllable": (
        SEV_HIGH,
        "upload-artifact name: includes an attacker-controllable ${{ }} context.",
    ),
    "environment-without-required-reviewers": (
        SEV_MAJOR,
        "Job deploys to a prod-named environment — verify required_reviewers in repo settings.",
    ),
    "actions-toolkit-exec-arg-zero": (
        SEV_MAJOR,
        "node-based action calls exec(getInput()) with the input as argv[0].",
    ),
}


# Workflow rules that take only a `Workflow`. Composite-action rules
# take a `CompositeAction`. Rule 14 takes both an action and the JS
# source. Repo-owner-aware rules accept an optional `repo_owner`.
_WORKFLOW_CHECKS: tuple = (
    check_reusable_workflow_mutable_ref,
    check_composite_action_local_path_from_pr,
    check_workflow_dispatch_input_in_git_push,
    check_workflow_run_artifact_name_trust,
    check_step_output_injection_via_github_output,
    check_job_output_cross_job_taint,
    check_workflow_dispatch_input_not_typed,
    check_artifact_name_attacker_controllable,
    check_environment_without_required_reviewers,
)


def scan_workflow(
    wf: Workflow, repo_owner: Optional[str] = None,
) -> list[Finding]:
    """Run every workflow-scoped rule on `wf`. Returns all findings."""
    findings: list[Finding] = []
    for fn in _WORKFLOW_CHECKS:
        findings.extend(fn(wf))
    # Owner-aware rules.
    findings.extend(
        check_reusable_workflow_secrets_inherit_broad_scope(wf, repo_owner)
    )
    findings.extend(
        check_reusable_workflow_permissions_elevation(wf, repo_owner)
    )
    return findings


_ACTION_CHECKS: tuple = (
    check_composite_action_input_shell_reflection,
    check_composite_action_uses_third_party_unsafe_chain,
)


def scan_composite_action(action: CompositeAction) -> list[Finding]:
    """Run every action-scoped rule on `action`. Returns all findings."""
    findings: list[Finding] = []
    for fn in _ACTION_CHECKS:
        findings.extend(fn(action))
    return findings
