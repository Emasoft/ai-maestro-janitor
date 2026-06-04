"""Tests for scripts/lib/ci_runner_injection_patterns.py.

Pattern-coverage tests for the Wave-24 distill-round-10 angle
ci-runner-injection catalogue (10 runner-side injection patterns
covering CircleCI / GitLab CI / Jenkins / Drone / Buildkite / Tekton /
Azure Pipelines / Bitrise / Coverity-Sonar-Snyk dashboards). Each rule
gets exactly two tests: one positive (must fire) plus one negative
near-miss (must NOT fire — exercises the carve-out or safe-shape).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import ci_runner_injection_patterns as crip  # type: ignore[import-not-found]  # noqa: E402


def _hits(rule_id: str, text: str) -> list[crip.Finding]:
    return [f for f in crip.scan_text(text) if f.rule_id == rule_id]


# ============================================================
# Data-model sanity
# ============================================================


def test_rules_tuple_covers_every_advertised_rule() -> None:
    """RULES must contain all 10 documented rule IDs."""
    assert isinstance(crip.RULES, tuple)
    rule_ids = {r.id for r in crip.RULES}
    expected = {
        "circleci-param-cmd-substitution",
        "gitlab-predefined-var-script-injection",
        "jenkins-groovy-interpolation-in-sh",
        "drone-trusted-mode-enabled",
        "buildkite-plugin-unpinned",
        "tekton-param-script-injection",
        "azure-pipelines-vso-untrusted-expr",
        "bitrise-env-rewrite-untrusted",
        "dashboard-report-xml-inject-via-testname",
        "jenkins-agent-label-spoof",
    }
    assert expected == rule_ids
    assert len(crip.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a CICD-SEC-NN prefix and a known severity."""
    valid_sev = {"CRITICAL", "HIGH", "MAJOR", "MEDIUM", "MINOR", "LOW"}
    for rule in crip.RULES:
        assert rule.owasp_asi.startswith("CICD-SEC-"), rule.id
        assert rule.severity in valid_sev, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = crip.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="CICD-SEC-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "CICD-SEC-04"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert crip.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — Drone trusted-mode toggle
        "trusted: true\n"
        # Line 3 — CircleCI run: with pipeline.git.branch
        "jobs:\n"
        "  run: echo 'on << pipeline.git.branch >>'\n"
    )
    findings = crip.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


# ============================================================
# R1 : circleci-param-cmd-substitution
# ============================================================


def test_r1_circleci_pipeline_git_branch_flags() -> None:
    """CircleCI `run:` line with `<< pipeline.git.branch >>` must fire HIGH."""
    src = (
        "version: 2.1\n"
        "jobs:\n"
        "  greet:\n"
        "    steps:\n"
        "      - run: echo \"Building branch << pipeline.git.branch >>\"\n"
    )
    hits = _hits("circleci-param-cmd-substitution", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r1_circleci_safe_run_does_not_fire() -> None:
    """A `run:` step that does NOT reference pipeline.git.* or $CIRCLE_* PR vars stays clean."""
    src = (
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        "      - run: echo 'static build step'\n"
        "      - run: make test\n"
    )
    assert _hits("circleci-param-cmd-substitution", src) == []


# ============================================================
# R2 : gitlab-predefined-var-script-injection
# ============================================================


def test_r2_gitlab_commit_title_in_script_flags() -> None:
    """`script:` consuming $CI_COMMIT_TITLE within 400 chars must fire."""
    src = (
        "build:\n"
        "  stage: build\n"
        "  script:\n"
        "    - echo \"Building $CI_COMMIT_TITLE by $GITLAB_USER_NAME\"\n"
        "    - git log --grep=\"$CI_MERGE_REQUEST_TITLE\" --oneline\n"
    )
    hits = _hits("gitlab-predefined-var-script-injection", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r2_gitlab_server_set_var_does_not_fire() -> None:
    """A `script:` using only server-set vars ($CI_JOB_ID, $CI_PROJECT_DIR) stays clean."""
    src = (
        "build:\n"
        "  script:\n"
        "    - echo \"Job $CI_JOB_ID in $CI_PROJECT_DIR\"\n"
        "    - cd $CI_PROJECT_DIR && make\n"
    )
    assert _hits("gitlab-predefined-var-script-injection", src) == []


# ============================================================
# R3 : jenkins-groovy-interpolation-in-sh
# ============================================================


def test_r3_jenkins_change_title_in_triple_double_quotes_flags() -> None:
    """sh \"\"\"...${env.CHANGE_TITLE}...\"\"\" must fire HIGH."""
    src = (
        "pipeline {\n"
        "  agent any\n"
        "  stages {\n"
        "    stage('Build') {\n"
        "      steps {\n"
        "        sh \"\"\"echo 'PR title: ${env.CHANGE_TITLE}'\"\"\"\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    hits = _hits("jenkins-groovy-interpolation-in-sh", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r3_jenkins_literal_triple_single_quotes_does_not_fire() -> None:
    """`sh '''echo ${env.CHANGE_TITLE}'''` (literal, no interpolation) stays clean."""
    src = (
        "pipeline {\n"
        "  stages { stage('B') { steps {\n"
        "    sh '''echo ${env.CHANGE_TITLE} but literal'''\n"
        "  } } }\n"
        "}\n"
    )
    assert _hits("jenkins-groovy-interpolation-in-sh", src) == []


# ============================================================
# R4 : drone-trusted-mode-enabled
# ============================================================


def test_r4_drone_trusted_true_flags() -> None:
    """`trusted: true` on its own line must fire CRITICAL."""
    src = (
        "kind: pipeline\n"
        "type: docker\n"
        "name: deploy\n"
        "trusted: true\n"
        "steps:\n"
        "  - name: build\n"
        "    image: alpine\n"
    )
    hits = _hits("drone-trusted-mode-enabled", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r4_drone_trusted_false_does_not_fire() -> None:
    """`trusted: false` (the safe posture) stays clean."""
    src = (
        "kind: pipeline\n"
        "type: docker\n"
        "name: deploy\n"
        "trusted: false\n"
        "steps:\n"
        "  - name: build\n"
    )
    assert _hits("drone-trusted-mode-enabled", src) == []


# ============================================================
# R5 : buildkite-plugin-unpinned
# ============================================================


def test_r5_buildkite_plugin_semver_tag_flags() -> None:
    """`docker-compose#v4.0.0:` (mutable tag) must fire MAJOR."""
    src = (
        "steps:\n"
        "  - label: \":docker: Build\"\n"
        "    plugins:\n"
        "      - docker-compose#v4.0.0:\n"
        "          run: app\n"
    )
    hits = _hits("buildkite-plugin-unpinned", src)
    assert hits
    assert hits[0].severity == "MAJOR"


def test_r5_buildkite_plugin_pinned_to_sha_does_not_fire() -> None:
    """A plugin ref pinned to a full git SHA does NOT match the unpinned regex."""
    src = (
        "steps:\n"
        "  - label: \":docker: Build\"\n"
        "    plugins:\n"
        "      - docker-compose#a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2:\n"
        "          run: app\n"
    )
    assert _hits("buildkite-plugin-unpinned", src) == []


# ============================================================
# R6 : tekton-param-script-injection
# ============================================================


def test_r6_tekton_params_pr_title_in_script_flags() -> None:
    """`$(params.pr-title)` inside a `script:` block must fire HIGH."""
    src = (
        "apiVersion: tekton.dev/v1\n"
        "kind: Task\n"
        "spec:\n"
        "  params:\n"
        "    - name: pr-title\n"
        "      type: string\n"
        "  steps:\n"
        "    - name: build\n"
        "      image: alpine\n"
        "      script: |\n"
        "        echo \"Building PR: $(params.pr-title)\"\n"
    )
    hits = _hits("tekton-param-script-injection", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r6_tekton_script_without_params_does_not_fire() -> None:
    """A `script:` block with no `$(params.*)` reference stays clean."""
    src = (
        "spec:\n"
        "  steps:\n"
        "    - name: build\n"
        "      image: alpine\n"
        "      script: |\n"
        "        echo 'static build'\n"
        "        make\n"
    )
    assert _hits("tekton-param-script-injection", src) == []


# ============================================================
# R7 : azure-pipelines-vso-untrusted-expr
# ============================================================


def test_r7_azure_vso_setvariable_with_pr_branch_flags() -> None:
    """##vso[task.setvariable] + $(System.PullRequest.SourceBranch) must fire HIGH."""
    src = (
        "- script: |\n"
        "    echo \"##vso[task.setvariable variable=PR_TITLE]"
        "$(System.PullRequest.SourceBranch)\"\n"
    )
    hits = _hits("azure-pipelines-vso-untrusted-expr", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r7_azure_vso_with_immutable_sha_does_not_fire() -> None:
    """##vso[task.setvariable] embedding $(Build.SourceVersion) (a SHA) stays clean."""
    src = (
        "- script: |\n"
        "    echo \"##vso[task.setvariable variable=BUILD_SHA]"
        "$(Build.SourceVersion)\"\n"
    )
    assert _hits("azure-pipelines-vso-untrusted-expr", src) == []


# ============================================================
# R8 : bitrise-env-rewrite-untrusted
# ============================================================


def test_r8_bitrise_envman_add_value_from_git_message_flags() -> None:
    """`envman add --key X --value $BITRISE_GIT_MESSAGE` must fire MAJOR."""
    src = (
        "workflows:\n"
        "  primary:\n"
        "    steps:\n"
        "      - script:\n"
        "          inputs:\n"
        "            - content: |\n"
        "                envman add --key DEPLOY_DIR --value "
        "\"$BITRISE_GIT_MESSAGE\"\n"
    )
    hits = _hits("bitrise-env-rewrite-untrusted", src)
    assert hits
    assert hits[0].severity == "MAJOR"


def test_r8_bitrise_envman_with_server_set_var_does_not_fire() -> None:
    """`envman add --value $BITRISE_BUILD_STATUS` (server-set) stays clean."""
    src = (
        "workflows:\n"
        "  primary:\n"
        "    steps:\n"
        "      - script:\n"
        "          inputs:\n"
        "            - content: |\n"
        "                envman add --key STATUS --value "
        "\"$BITRISE_BUILD_STATUS\"\n"
    )
    assert _hits("bitrise-env-rewrite-untrusted", src) == []


# ============================================================
# R9 : dashboard-report-xml-inject-via-testname
# ============================================================


def test_r9_coverity_import_description_from_commit_message_flags() -> None:
    """`cov-import-results --description $CI_COMMIT_MESSAGE` must fire MAJOR."""
    src = (
        "steps:\n"
        "  - run: |\n"
        "      cov-import-results --user \"$COV_USER\" "
        "--description \"$CI_COMMIT_MESSAGE\"\n"
    )
    hits = _hits("dashboard-report-xml-inject-via-testname", src)
    assert hits
    assert hits[0].severity == "MAJOR"


def test_r9_sonar_scanner_without_free_form_flag_does_not_fire() -> None:
    """A `sonar-scanner` invocation with no free-form metadata flag stays clean."""
    src = (
        "steps:\n"
        "  - run: |\n"
        "      sonar-scanner -Dsonar.projectKey=myapp\n"
    )
    assert _hits("dashboard-report-xml-inject-via-testname", src) == []


# ============================================================
# R10 : jenkins-agent-label-spoof
# ============================================================


def test_r10_jenkins_agent_label_from_params_flags() -> None:
    """`agent { label \"${params.AGENT_LABEL}\" }` must fire HIGH."""
    src = (
        "pipeline {\n"
        "  agent { label \"${params.AGENT_LABEL}\" }\n"
        "  parameters {\n"
        "    string(name: 'AGENT_LABEL', defaultValue: 'linux-untrusted')\n"
        "  }\n"
        "}\n"
    )
    hits = _hits("jenkins-agent-label-spoof", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r10_jenkins_agent_static_label_does_not_fire() -> None:
    """`agent { label 'linux' }` (static literal) stays clean."""
    src = (
        "pipeline {\n"
        "  agent { label 'linux' }\n"
        "  stages { stage('B') { steps { sh 'make' } } }\n"
        "}\n"
    )
    assert _hits("jenkins-agent-label-spoof", src) == []
