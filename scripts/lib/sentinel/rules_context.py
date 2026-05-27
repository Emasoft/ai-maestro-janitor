# Context-tier Sentinel rules: ones whose detection needs job/step/trigger
# context (not a plain regex) but are NOT injection rules.
#
# Native Python port of eight Sentinel reference rules (Ruby originals under
# lib/rules/*.rb). Each rule keeps the upstream kebab `name` verbatim so the
# janitor classifier and the Sentinel test corpus refer to the same id, and the
# line-number logic reproduces the Ruby so findings point at the same source
# line. Severity maps Sentinel critical/high/medium/low → janitor
# CRITICAL/HIGH/MAJOR/MINOR via the SEV_* constants in model.py.

from __future__ import annotations

import re
from typing import Optional

from lib.sentinel.model import (
    SEV_HIGH,
    SEV_MAJOR,
    SEV_MINOR,
    Finding,
    Rule,
    Workflow,
)


def _stringify_env(value) -> str:
    """Flatten a step/job `env` value to a single string that preserves every
    key and scalar value.

    The Ruby rules call `.to_s` on the env Hash and substring-match the result
    for `secrets.` / a publish-secret name. We need the SAME property — the
    flattened text must contain both the env var names and their values — so a
    nested dict/list is walked recursively and scalars are appended verbatim.
    """
    parts: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                parts.append(str(k))
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif node is not None:
            parts.append(str(node))

    walk(value)
    return " ".join(parts)


class StaticAwsCredentials(Rule):
    name = "static-aws-credentials"
    severity = SEV_MAJOR
    description = "AWS credentials using static keys instead of OIDC"

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        for job_hash in wf.jobs().values():
            for step in wf.steps(job_hash):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if not (isinstance(uses, str) and "configure-aws-credentials" in uses):
                    continue
                with_block = step.get("with")
                with_block = with_block if isinstance(with_block, dict) else {}
                has_static = "aws-access-key-id" in with_block
                has_oidc = "role-to-assume" in with_block
                if has_static and not has_oidc:
                    line = wf.line_of(r"aws-access-key-id")
                    findings.append(self._finding(
                        wf,
                        line or 0,
                        description=(
                            "Static AWS access keys — long-lived credentials "
                            "that don't auto-expire. Use OIDC federation: "
                            "role-to-assume with id-token: write permission"
                        ),
                    ))
        return findings


class UnscopedAppToken(Rule):
    name = "unscoped-app-token"
    severity = SEV_MAJOR
    description = "GitHub App token without scoped permissions"

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        for job_hash in wf.jobs().values():
            for step in wf.steps(job_hash):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if not (isinstance(uses, str) and "create-github-app-token" in uses):
                    continue
                with_block = step.get("with")
                with_block = with_block if isinstance(with_block, dict) else {}
                has_permissions = any(
                    str(k).startswith("permission-") for k in with_block.keys()
                )
                if not has_permissions:
                    line = wf.line_of(r"create-github-app-token")
                    findings.append(self._finding(
                        wf,
                        line or 0,
                        description=(
                            "App token inherits blanket installation "
                            "permissions. Add permission-<name>: write inputs "
                            "to scope the token"
                        ),
                    ))
        return findings


class DockerBuildArgSecrets(Rule):
    name = "docker-build-arg-secrets"
    severity = SEV_MAJOR
    description = "Secrets passed as Docker build-args (visible in image layers)"

    _NEW_KEY = re.compile(r"^\s*\w+:")
    _ARG_ASSIGN = re.compile(r"^\s+[\"']?[A-Z_]+=")
    _SECRET = re.compile(r"secrets\.")

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        total = len(wf.raw_lines)
        for line_num in wf.lines_of(r"build-args:"):
            # Scan the build-args block (the start line plus up to 20 lines).
            for i in range(line_num, line_num + 21):
                if i > total:
                    break
                line = wf.line_content(i)
                # Stop at the next sibling YAML key that is NOT an arg
                # assignment (FOO=...) — that means the build-args list ended.
                if line and self._NEW_KEY.search(line) and not self._ARG_ASSIGN.search(line):
                    break
                if line and self._SECRET.search(line):
                    findings.append(self._finding(
                        wf,
                        i,
                        matched_text=line.strip(),
                        description=(
                            "Secret in Docker build-arg — extractable via "
                            "docker history. Use --secret flag or "
                            "RUN --mount=type=secret instead of build-arg"
                        ),
                    ))
        return findings


class UnpinnedArtifact(Rule):
    name = "unpinned-artifact"
    severity = SEV_MINOR
    description = "download-artifact without specific artifact name"

    _DOWNLOAD_ARTIFACT = re.compile(r"\bactions/download-artifact\b")

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        for action in wf.uses_actions():
            uses = action.get("uses")
            if not (isinstance(uses, str) and self._DOWNLOAD_ARTIFACT.search(uses)):
                continue
            step = action.get("step")
            with_block = step.get("with") if isinstance(step, dict) else None
            has_name = (
                isinstance(with_block, dict)
                and with_block.get("name") is not None
                and str(with_block.get("name")).strip() != ""
            )
            if not has_name:
                findings.append(self._finding(
                    wf,
                    action.get("line") or 0,
                    matched_text=f"uses: {uses}",
                    description=(
                        "download-artifact without specific name downloads ALL "
                        "artifacts — may include untrusted content. Specify "
                        "artifact name: to avoid downloading unintended artifacts"
                    ),
                ))
        return findings


class SelfHostedRunnerFork(Rule):
    name = "self-hosted-runner-fork"
    severity = SEV_HIGH
    description = "Self-hosted runner exposed to fork PRs"

    _FORK_TRIGGERS = ("pull_request", "pull_request_target")
    _SAFE_TYPES = frozenset({"labeled", "unlabeled"})

    def _detect_fork_trigger(self, triggers) -> Optional[str]:
        # Preserve the upstream priority order (pull_request first), not the
        # parsed-dict order — the message embeds the matched trigger name.
        for trigger in self._FORK_TRIGGERS:
            if isinstance(triggers, dict) and trigger in triggers:
                return trigger
            if isinstance(triggers, list) and trigger in triggers:
                return trigger
            if isinstance(triggers, str) and triggers == trigger:
                return trigger
        return None

    def _gated_by_label(self, triggers, fork_trigger: str) -> bool:
        if not isinstance(triggers, dict):
            return False
        config = triggers.get(fork_trigger)
        if not isinstance(config, dict):
            return False
        types = config.get("types")
        if not isinstance(types, list):
            return False
        # Safe iff ONLY label-based types (no code-execution types like
        # opened/synchronize).
        return all(t in self._SAFE_TYPES for t in types)

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        triggers = wf.triggers()

        fork_trigger = self._detect_fork_trigger(triggers)
        if not fork_trigger:
            return findings
        if self._gated_by_label(triggers, fork_trigger):
            return findings

        runs_on_lines = wf.lines_of(r"runs-on:")
        runs_on_idx = 0

        for job_hash in wf.jobs().values():
            if not isinstance(job_hash, dict):
                continue
            runs_on = job_hash.get("runs-on")
            if not runs_on:
                continue
            if isinstance(runs_on, list):
                runs_on_str = ", ".join(str(x) for x in runs_on)
            else:
                runs_on_str = str(runs_on)

            # Advance through runs-on lines for each job regardless of
            # self-hosted, so subsequent jobs map to the right source line.
            line = runs_on_lines[runs_on_idx] if runs_on_idx < len(runs_on_lines) else None
            runs_on_idx += 1

            if "self-hosted" not in runs_on_str:
                continue

            findings.append(self._finding(
                wf,
                line or 0,
                matched_text=f"runs-on: {runs_on_str}",
                description=(
                    f"Self-hosted runner with '{fork_trigger}' trigger — fork "
                    "PRs can run arbitrary code on your infrastructure. Use "
                    "GitHub-hosted runners for fork PR workflows, or gate with "
                    "a label-based trigger"
                ),
            ))
        return findings


class BuildPublishSameJob(Rule):
    name = "build-publish-same-job"
    severity = SEV_HIGH
    description = "Build and publish in same job with publish secrets available during build"

    _INSTALL_PATTERNS = re.compile("|".join([
        # JavaScript / TypeScript
        r"\bnpm\s+(install|ci)\b",
        r"\bpnpm\s+install\b",
        r"\byarn\s+install\b",
        r"\byarn\b(?!\s+(publish|add|remove|run|build|test|lint))",
        r"\bbun\s+install\b",
        # Python
        r"\bpip3?\s+install\b",
        r"\buv\s+(pip\s+install|sync)\b",
        r"\bpoetry\s+install\b",
        r"\bpipenv\s+install\b",
        r"\bconda\s+install\b",
        # Ruby
        r"\bbundle\s+install\b",
        r"\bbundle\b(?!\s+(exec|push|open|show|update|outdated|gem))",
        r"\bgem\s+install\b",
        # Go
        r"\bgo\s+mod\s+download\b",
        r"\bgo\s+get\b",
        r"\bgo\s+install\b",
        # Rust
        r"\bcargo\s+(build|fetch)\b",
        # Java / Kotlin
        r"\bmvn\s+(install|package)\b",
        r"\bgradle\s+build\b",
        r"\./gradlew\s+build\b",
        # .NET
        r"\bdotnet\s+restore\b",
        r"\bnuget\s+restore\b",
        # PHP
        r"\bcomposer\s+(install|update)\b",
        # Elixir
        r"\bmix\s+deps\.get\b",
        # Swift
        r"\bswift\s+package\s+resolve\b",
    ]))

    _PUBLISH_PATTERNS = re.compile("|".join([
        # JavaScript / TypeScript
        r"\bnpm\s+publish\b",
        r"\bpnpm\s+publish\b",
        r"\bnpx\s+pkg-pr-new\b",
        r"\byarn\s+publish\b",
        # Python
        r"\btwine\s+upload\b",
        r"\bpoetry\s+publish\b",
        r"\bflit\s+publish\b",
        r"\buv\s+publish\b",
        # Ruby
        r"\bgem\s+push\b",
        r"\brake\s+release\b",
        # Rust
        r"\bcargo\s+publish\b",
        # Java / Kotlin
        r"\bmvn\s+deploy\b",
        r"\bgradle\s+publish\b",
        r"\./gradlew\s+publish\b",
        # .NET
        r"\bdotnet\s+nuget\s+push\b",
        r"\bnuget\s+push\b",
        # Docker
        r"\bdocker\s+push\b",
        r"\bdocker\s+buildx\s+build\b.*--push",
        # Homebrew
        r"\bbrew\s+tap\b",
        r"\bbrew\s+bump-formula-pr\b",
    ]))

    _PUBLISH_SECRETS = re.compile("|".join([
        # JavaScript
        r"\bNPM_TOKEN\b",
        r"\bNODE_AUTH_TOKEN\b",
        r"\bNPM_AUTH_TOKEN\b",
        # Python
        r"\bPYPI_TOKEN\b",
        r"\bPYPI_API_TOKEN\b",
        r"\bTWINE_PASSWORD\b",
        r"\bPOETRY_PYPI_TOKEN_PYPI\b",
        # Ruby
        r"\bGEM_HOST_API_KEY\b",
        r"\bRUBYGEMS_API_KEY\b",
        r"\bRUBYGEMS_AUTH_TOKEN\b",
        # Rust
        r"\bCARGO_REGISTRY_TOKEN\b",
        r"\bCRATES_IO_TOKEN\b",
        # Java / Gradle
        r"\bMAVEN_PASSWORD\b",
        r"\bMAVEN_GPG_PASSPHRASE\b",
        r"\bGRADLE_PUBLISH_KEY\b",
        r"\bOSSRH_PASSWORD\b",
        r"\bSONATYPE_PASSWORD\b",
        # .NET
        r"\bNUGET_API_KEY\b",
        r"\bNUGET_AUTH_TOKEN\b",
        # Docker
        r"\bDOCKER_PASSWORD\b",
        r"\bDOCKER_TOKEN\b",
        r"\bDOCKERHUB_TOKEN\b",
        # General
        r"\bREGISTRY_TOKEN\b",
        r"\bPUBLISH_TOKEN\b",
    ]))

    _SECRETS_REF = re.compile(r"secrets\.")

    @staticmethod
    def _run_text(step) -> str:
        run = step.get("run") if isinstance(step, dict) else None
        return run if isinstance(run, str) else ""

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        for job_id, job in wf.jobs().items():
            steps = wf.steps(job)
            has_install = any(self._INSTALL_PATTERNS.search(self._run_text(s)) for s in steps)
            has_publish = any(self._PUBLISH_PATTERNS.search(self._run_text(s)) for s in steps)
            if not (has_install and has_publish):
                continue

            job_env = _stringify_env(job.get("env")) if isinstance(job, dict) else ""
            step_envs = " ".join(
                _stringify_env(s.get("env")) for s in steps if isinstance(s, dict)
            )
            all_env = job_env + " " + step_envs

            if self._PUBLISH_SECRETS.search(all_env) or self._SECRETS_REF.search(all_env):
                line = wf.line_of(re.escape(str(job_id)) + r":")
                findings.append(self._finding(
                    wf,
                    line or 0,
                    matched_text=f"job: {job_id}",
                    description=(
                        "Build and publish in same job — a compromised "
                        "dependency could leak publish credentials. "
                        "Split into separate build (read-only) and publish "
                        "(with secrets) jobs connected via artifacts"
                    ),
                ))
        return findings


class AllowForksArtifact(Rule):
    name = "allow-forks-artifact"
    severity = SEV_MAJOR
    description = "Artifact download with allow_forks: true in privileged context"

    def check(self, wf: Workflow) -> list:
        findings: list[Finding] = []
        for line_num in wf.lines_of(r"allow_forks:\s*true"):
            line = wf.line_content(line_num)
            findings.append(self._finding(
                wf,
                line_num,
                matched_text=(line or "").strip(),
                description=(
                    "Downloading fork-produced artifacts in a privileged "
                    "workflow_run context. Ensure fork-produced artifact "
                    "content is not executed or processed unsafely"
                ),
            ))
        return findings


class DangerousLifecycleScripts(Rule):
    name = "dangerous-lifecycle-scripts"
    severity = SEV_MAJOR
    description = "Package install without --ignore-scripts in workflow with secrets"

    # (match, safe-flag, ecosystem) — install commands that run lifecycle
    # scripts unless the safe flag is present.
    _INSTALL_CMDS = (
        (re.compile(r"\bnpm\s+(install|ci)\b"), re.compile(r"--ignore-scripts"), "npm"),
        (re.compile(r"\bpnpm\s+install\b"), re.compile(r"--ignore-scripts"), "pnpm"),
        (re.compile(r"\byarn\s+install\b"), re.compile(r"--ignore-scripts"), "yarn"),
        (re.compile(r"\bbun\s+install\b"), re.compile(r"--ignore-scripts|--no-scripts"), "bun"),
    )

    _HAS_SECRETS = re.compile(r"\$\{\{\s*secrets\.")

    def check(self, wf: Workflow) -> list:
        if not self._HAS_SECRETS.search(wf.raw):
            return []

        findings: list[Finding] = []
        for i, line in enumerate(wf.raw_lines):
            if line.strip().startswith("#"):
                continue
            for match_rx, safe_rx, eco in self._INSTALL_CMDS:
                if not match_rx.search(line):
                    continue
                if safe_rx.search(line):
                    continue
                findings.append(self._finding(
                    wf,
                    i + 1,
                    matched_text=line.strip(),
                    description=(
                        f"{eco} install runs lifecycle scripts in a workflow "
                        "with secrets — a compromised dependency can leak "
                        f"credentials. Add --ignore-scripts, then explicitly "
                        f"rebuild trusted native deps: {eco} rebuild sharp esbuild"
                    ),
                ))
        return findings


RULES = [
    StaticAwsCredentials(),
    UnscopedAppToken(),
    DockerBuildArgSecrets(),
    UnpinnedArtifact(),
    SelfHostedRunnerFork(),
    BuildPublishSameJob(),
    AllowForksArtifact(),
    DangerousLifecycleScripts(),
]
