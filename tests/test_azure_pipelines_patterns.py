"""Tests for scripts/lib/azure_pipelines_patterns.py.

Pattern-coverage tests for the Wave-36 distill-round-22 Azure Pipelines
security gap catalogue (10 ADO-specific anti-patterns). Each rule gets
exactly two tests: one positive (must fire) plus one negative near-miss
(must NOT fire — exercises the safe-shape or known carve-out).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import azure_pipelines_patterns as azp  # type: ignore[import-not-found]  # noqa: E402


def _hits(rule_id: str, text: str) -> list[azp.Finding]:
    return [f for f in azp.scan_text(text) if f.rule_id == rule_id]


# ============================================================
# Data-model sanity
# ============================================================


def test_rules_tuple_covers_every_advertised_rule() -> None:
    """RULES must contain all 10 documented rule IDs."""
    assert isinstance(azp.RULES, tuple)
    rule_ids = {r.id for r in azp.RULES}
    expected = {
        "azp-param-inject",
        "azp-macro-inject",
        "azp-secret-echo",
        "azp-wildcard-trigger",
        "azp-deploy-no-gate",
        "azp-endpoint-ref",
        "azp-repo-resource-branch",
        "azp-templatecontext-inject",
        "azp-pr-autocancel-false",
        "azp-vargroup-fork",
    }
    assert expected == rule_ids
    assert len(azp.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to an ASI-NN prefix and a known severity."""
    valid_sev = {"CRITICAL", "HIGH", "MAJOR", "MEDIUM", "MINOR", "LOW"}
    for rule in azp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid_sev, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding must mirror the standard NamedTuple contract."""
    f = azp.Finding(
        rule_id="azp-param-inject",
        line=3,
        column=0,
        matched_text="script: echo ${{ parameters.Branch }}",
        severity="CRITICAL",
        description="test",
        owasp_asi="ASI-05",
    )
    assert f.rule_id == "azp-param-inject"
    assert f.line == 3
    assert f.column == 0
    assert f.severity == "CRITICAL"
    assert f.owasp_asi == "ASI-05"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert azp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        "trigger: '*'\n"
        "variables:\n"
        "  - group: ProdSecrets\n"
    )
    findings = azp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


# ============================================================
# R1 : azp-param-inject
# ============================================================


def test_r1_param_inject_in_script_fires() -> None:
    """script: step with ${{ parameters.Branch }} must fire CRITICAL."""
    src = (
        "steps:\n"
        "  - script: git checkout ${{ parameters.BranchName }}\n"
    )
    hits = _hits("azp-param-inject", src)
    assert hits, "expected a finding for parameter expression in script step"
    assert hits[0].severity == "CRITICAL"


def test_r1_param_inject_in_condition_does_not_fire() -> None:
    """${{ parameters.X }} in a condition: or displayName: must NOT fire."""
    src = (
        "steps:\n"
        "  - task: Bash@3\n"
        "    condition: eq('${{ parameters.RunTests }}', 'true')\n"
        "    displayName: Run ${{ parameters.SuiteName }}\n"
        "    inputs:\n"
        "      script: echo 'running tests'\n"
    )
    assert _hits("azp-param-inject", src) == []


# ============================================================
# R2 : azp-macro-inject
# ============================================================


def test_r2_macro_inject_pr_source_branch_fires() -> None:
    """script: step with $(System.PullRequest.SourceBranch) must fire HIGH."""
    src = (
        "steps:\n"
        "  - script: echo \"PR branch: $(System.PullRequest.SourceBranch)\"\n"
    )
    hits = _hits("azp-macro-inject", src)
    assert hits, "expected a finding for PullRequest.SourceBranch in script"
    assert hits[0].severity == "HIGH"


def test_r2_macro_inject_safe_variable_does_not_fire() -> None:
    """script: step referencing only $(Build.BuildId) must NOT fire."""
    src = (
        "steps:\n"
        "  - script: echo \"Build $(Build.BuildId) completed\"\n"
    )
    assert _hits("azp-macro-inject", src) == []


# ============================================================
# R3 : azp-secret-echo
# ============================================================


def test_r3_secret_echo_write_host_fires() -> None:
    """Write-Host with a $(VarName) macro must fire HIGH."""
    src = (
        "steps:\n"
        "  - powershell: Write-Host $(MyApiToken)\n"
    )
    hits = _hits("azp-secret-echo", src)
    assert hits, "expected a finding for Write-Host with macro"
    assert hits[0].severity == "HIGH"


def test_r3_secret_echo_no_macro_does_not_fire() -> None:
    """echo with a hard-coded string (no ADO macro) must NOT fire."""
    src = (
        "steps:\n"
        "  - script: echo 'deployment started'\n"
    )
    assert _hits("azp-secret-echo", src) == []


# ============================================================
# R4 : azp-wildcard-trigger
# ============================================================


def test_r4_wildcard_trigger_star_fires() -> None:
    """trigger: '*' must fire HIGH."""
    src = "trigger: '*'\n"
    hits = _hits("azp-wildcard-trigger", src)
    assert hits, "expected a finding for wildcard trigger"
    assert hits[0].severity == "HIGH"


def test_r4_specific_branch_trigger_does_not_fire() -> None:
    """trigger: with a specific branch list must NOT fire."""
    src = (
        "trigger:\n"
        "  branches:\n"
        "    include:\n"
        "      - main\n"
        "      - release/*\n"
    )
    assert _hits("azp-wildcard-trigger", src) == []


# ============================================================
# R5 : azp-deploy-no-gate
# ============================================================


def test_r5_deploy_no_gate_ubuntu_latest_fires() -> None:
    """vmImage: ubuntu-latest inside a deployment job must fire HIGH."""
    src = (
        "jobs:\n"
        "  - deployment: DeployProd\n"
        "    pool:\n"
        "      vmImage: ubuntu-latest\n"
        "    strategy:\n"
        "      runOnce:\n"
        "        deploy:\n"
        "          steps:\n"
        "            - script: az webapp deploy\n"
    )
    hits = _hits("azp-deploy-no-gate", src)
    assert hits, "expected a finding for deployment on ubuntu-latest without gate"
    assert hits[0].severity == "HIGH"


def test_r5_self_hosted_runner_does_not_fire() -> None:
    """A job using a self-hosted pool (no vmImage) must NOT fire."""
    src = (
        "jobs:\n"
        "  - deployment: DeployProd\n"
        "    pool:\n"
        "      name: SelfHostedPool\n"
        "    environment: Production\n"
        "    strategy:\n"
        "      runOnce:\n"
        "        deploy:\n"
        "          steps:\n"
        "            - script: deploy.sh\n"
    )
    assert _hits("azp-deploy-no-gate", src) == []


# ============================================================
# R6 : azp-endpoint-ref
# ============================================================


def test_r6_endpoint_ref_fires() -> None:
    """endpoint: referencing a named service connection must fire CRITICAL."""
    src = (
        "steps:\n"
        "  - task: AzureCLI@2\n"
        "    inputs:\n"
        "      azureSubscription: MyServiceConnection\n"
        "      endpoint: MyAzureServiceConn\n"
    )
    hits = _hits("azp-endpoint-ref", src)
    assert hits, "expected a finding for endpoint: reference"
    assert hits[0].severity == "CRITICAL"


def test_r6_endpoint_key_absent_does_not_fire() -> None:
    """A task step with no endpoint: key must NOT fire."""
    src = (
        "steps:\n"
        "  - task: Bash@3\n"
        "    inputs:\n"
        "      targetType: inline\n"
        "      script: echo 'hello'\n"
    )
    assert _hits("azp-endpoint-ref", src) == []


# ============================================================
# R7 : azp-repo-resource-branch
# ============================================================


def test_r7_github_type_external_repo_fires() -> None:
    """resources: repository of type github must fire HIGH."""
    src = (
        "resources:\n"
        "  repositories:\n"
        "    - repository: SharedTemplates\n"
        "      type: github\n"
        "      name: myorg/shared-templates\n"
        "      ref: refs/heads/main\n"
    )
    hits = _hits("azp-repo-resource-branch", src)
    assert hits, "expected a finding for external github repo resource"
    assert hits[0].severity == "HIGH"


def test_r7_internal_git_type_does_not_fire() -> None:
    """resources: repository of internal type: git must NOT fire."""
    src = (
        "resources:\n"
        "  repositories:\n"
        "    - repository: InternalShared\n"
        "      type: git\n"
        "      name: MyProject/my-shared-repo\n"
        "      ref: refs/heads/main\n"
    )
    assert _hits("azp-repo-resource-branch", src) == []


# ============================================================
# R8 : azp-templatecontext-inject
# ============================================================


def test_r8_templatecontext_inject_fires() -> None:
    """script: step with ${{ templateContext.env }} must fire CRITICAL."""
    src = (
        "parameters:\n"
        "  - name: env\n"
        "    type: string\n"
        "steps:\n"
        "  - script: deploy.sh ${{ templateContext.env }}\n"
    )
    hits = _hits("azp-templatecontext-inject", src)
    assert hits, "expected a finding for templateContext expression in script"
    assert hits[0].severity == "CRITICAL"


def test_r8_templatecontext_in_displayname_does_not_fire() -> None:
    """${{ templateContext.X }} in a displayName field must NOT fire."""
    src = (
        "steps:\n"
        "  - task: Bash@3\n"
        "    displayName: Deploy to ${{ templateContext.targetEnv }}\n"
        "    inputs:\n"
        "      script: echo 'deploying'\n"
    )
    assert _hits("azp-templatecontext-inject", src) == []


# ============================================================
# R9 : azp-pr-autocancel-false
# ============================================================


def test_r9_pr_autocancel_false_fires() -> None:
    """autoCancel: false under a pr: block must fire MEDIUM."""
    src = (
        "pr:\n"
        "  branches:\n"
        "    include:\n"
        "      - main\n"
        "  autoCancel: false\n"
    )
    hits = _hits("azp-pr-autocancel-false", src)
    assert hits, "expected a finding for autoCancel: false"
    assert hits[0].severity == "MEDIUM"


def test_r9_autocancel_true_does_not_fire() -> None:
    """autoCancel: true (or absent) must NOT fire."""
    src = (
        "pr:\n"
        "  branches:\n"
        "    include:\n"
        "      - main\n"
        "  autoCancel: true\n"
    )
    assert _hits("azp-pr-autocancel-false", src) == []


# ============================================================
# R10 : azp-vargroup-fork
# ============================================================


def test_r10_vargroup_fork_fires() -> None:
    """- group: SomeGroup must fire HIGH."""
    src = (
        "variables:\n"
        "  - group: ProdSecrets\n"
        "  - name: MY_VAR\n"
        "    value: hello\n"
    )
    hits = _hits("azp-vargroup-fork", src)
    assert hits, "expected a finding for - group: reference"
    assert hits[0].severity == "HIGH"


def test_r10_plain_variable_no_group_does_not_fire() -> None:
    """variables: section with only name/value pairs must NOT fire."""
    src = (
        "variables:\n"
        "  - name: BUILD_ENV\n"
        "    value: production\n"
        "  - name: TIMEOUT\n"
        "    value: '30'\n"
    )
    assert _hits("azp-vargroup-fork", src) == []
