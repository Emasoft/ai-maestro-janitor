"""Tests for scripts/lib/tekton_knative_patterns.py.

Pattern-coverage tests for the Wave-36 Tekton Pipelines + Knative
Eventing catalogue (12 rules). Each rule has at least 2 tests: one
positive (canary that MUST fire) and one negative (safe pattern or
context filter that must NOT fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import tekton_knative_patterns as tnp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 12 documented rule IDs."""
    assert isinstance(tnp.RULES, tuple)
    rule_ids = {r.id for r in tnp.RULES}
    expected = {
        "tkn-privileged-step-container",
        "tkn-host-path-volume-mount",
        "tkn-workspace-optional-without-emptydir",
        "tkn-param-substitution-shell-injection",
        "tkn-pipeline-run-service-account-default",
        "tkn-task-result-no-path-sanitize",
        "tkn-knative-broker-no-dlq",
        "tkn-knative-trigger-filter-missing",
        "tkn-event-source-insecure-tls-skip",
        "tkn-knative-sink-http-no-auth",
        "tkn-pipeline-finally-no-failure-guard",
        "tkn-tekton-bundle-latest-tag",
    }
    assert expected == rule_ids
    assert len(tnp.RULES) == 12


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in tnp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the standard Finding shape (7 fields)."""
    f = tnp.Finding(
        rule_id="tkn-test",
        line=1,
        column=1,
        matched_text="foo",
        severity="HIGH",
        description="desc",
        owasp_asi="ASI-06",
    )
    assert f.rule_id == "tkn-test"
    assert f.owasp_asi == "ASI-06"


def test_scan_text_returns_list() -> None:
    """scan_text always returns a list, even for empty input."""
    assert isinstance(tnp.scan_text(""), list)


# ---------- T1 : tkn-privileged-step-container ---------------------------


def test_t1_privileged_true_fires() -> None:
    """Step with privileged: true must trigger tkn-privileged-step-container."""
    yaml = """\
steps:
  - name: build
    image: alpine
    securityContext:
      privileged: true
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-privileged-step-container" in ids


def test_t1_privileged_false_does_not_fire() -> None:
    """Step with privileged: false must NOT trigger the rule."""
    yaml = """\
steps:
  - name: build
    image: alpine
    securityContext:
      privileged: false
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-privileged-step-container" not in ids


# ---------- T2 : tkn-host-path-volume-mount ------------------------------


def test_t2_host_path_fires() -> None:
    """Volume using hostPath must trigger tkn-host-path-volume-mount."""
    yaml = """\
volumes:
  - name: node-sock
    hostPath:
      path: /var/run/docker.sock
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-host-path-volume-mount" in ids


def test_t2_pvc_volume_does_not_fire() -> None:
    """Volume using persistentVolumeClaim must NOT fire the rule."""
    yaml = """\
volumes:
  - name: workspace
    persistentVolumeClaim:
      claimName: my-pvc
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-host-path-volume-mount" not in ids


# ---------- T3 : tkn-workspace-optional-without-emptydir -----------------


def test_t3_optional_workspace_no_emptydir_fires() -> None:
    """Optional workspace without emptyDir fallback must fire."""
    yaml = """\
workspaces:
  - name: optional-source
    optional: true
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-workspace-optional-without-emptydir" in ids


def test_t3_optional_workspace_with_emptydir_suppressed() -> None:
    """Optional workspace WITH an emptyDir binding in the same file must NOT fire."""
    yaml = """\
workspaces:
  - name: optional-source
    optional: true
  - name: scratch
    emptyDir: {}
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-workspace-optional-without-emptydir" not in ids


# ---------- T4 : tkn-param-substitution-shell-injection ------------------


def test_t4_unquoted_param_in_shell_fires() -> None:
    """Unquoted $(params.X) in sh -c must trigger shell-injection rule."""
    yaml = """\
steps:
  - name: run
    script: |
      sh -c echo $(params.userInput) > /output
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-param-substitution-shell-injection" in ids


def test_t4_param_assigned_to_variable_does_not_fire() -> None:
    """Param used via environment variable must NOT fire the rule."""
    yaml = """\
steps:
  - name: run
    env:
      - name: USER_INPUT
        value: $(params.userInput)
    script: |
      echo "$USER_INPUT"
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-param-substitution-shell-injection" not in ids


# ---------- T5 : tkn-pipeline-run-service-account-default ----------------


def test_t5_default_sa_fires() -> None:
    """serviceAccountName: default must trigger the rule."""
    yaml = """\
spec:
  serviceAccountName: default
  pipelineRef:
    name: my-pipeline
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-pipeline-run-service-account-default" in ids


def test_t5_named_sa_does_not_fire() -> None:
    """A named dedicated ServiceAccount must NOT fire the rule."""
    yaml = """\
spec:
  serviceAccountName: pipeline-runner-sa
  pipelineRef:
    name: my-pipeline
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-pipeline-run-service-account-default" not in ids


# ---------- T6 : tkn-task-result-no-path-sanitize ------------------------


def test_t6_echo_param_to_result_path_fires() -> None:
    """echo $(params.X) into results path must trigger the rule."""
    yaml = """\
steps:
  - name: write-result
    script: |
      echo $(params.version) > $(results.image-digest.path)
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-task-result-no-path-sanitize" in ids


def test_t6_fixed_literal_to_result_path_does_not_fire() -> None:
    """Writing a fixed literal string to result path must NOT fire."""
    yaml = """\
steps:
  - name: write-result
    script: |
      echo "sha256:abc123" > $(results.image-digest.path)
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-task-result-no-path-sanitize" not in ids


# ---------- T7 : tkn-knative-broker-no-dlq -------------------------------


def test_t7_broker_without_dlq_fires() -> None:
    """Broker without deadLetterSink must trigger tkn-knative-broker-no-dlq."""
    yaml = """\
apiVersion: eventing.knative.dev/v1
kind: Broker
metadata:
  name: default
spec:
  config:
    apiVersion: v1
    kind: ConfigMap
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-knative-broker-no-dlq" in ids


def test_t7_broker_with_dlq_suppressed() -> None:
    """Broker with deadLetterSink configured must NOT fire."""
    yaml = """\
apiVersion: eventing.knative.dev/v1
kind: Broker
metadata:
  name: default
spec:
  delivery:
    deadLetterSink:
      ref:
        apiVersion: v1
        kind: Service
        name: error-handler
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-knative-broker-no-dlq" not in ids


# ---------- T8 : tkn-knative-trigger-filter-missing ----------------------


def test_t8_trigger_without_filter_fires() -> None:
    """Trigger without filter block must trigger tkn-knative-trigger-filter-missing."""
    yaml = """\
apiVersion: eventing.knative.dev/v1
kind: Trigger
metadata:
  name: my-trigger
spec:
  broker: default
  subscriber:
    ref:
      apiVersion: v1
      kind: Service
      name: my-service
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-knative-trigger-filter-missing" in ids


def test_t8_trigger_with_filter_suppressed() -> None:
    """Trigger with filter attributes must NOT fire the rule."""
    yaml = """\
apiVersion: eventing.knative.dev/v1
kind: Trigger
metadata:
  name: my-trigger
spec:
  broker: default
  filter:
    attributes:
      type: com.example.event
  subscriber:
    ref:
      apiVersion: v1
      kind: Service
      name: my-service
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-knative-trigger-filter-missing" not in ids


# ---------- T9 : tkn-event-source-insecure-tls-skip ----------------------


def test_t9_insecure_skip_verify_fires() -> None:
    """insecureSkipVerify: true must trigger tkn-event-source-insecure-tls-skip."""
    yaml = """\
spec:
  sink:
    ref:
      name: default
  tls:
    insecureSkipVerify: true
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-event-source-insecure-tls-skip" in ids


def test_t9_insecure_false_does_not_fire() -> None:
    """insecureSkipVerify: false must NOT fire the rule."""
    yaml = """\
spec:
  tls:
    insecureSkipVerify: false
    caBundle: /etc/ssl/certs/ca.pem
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-event-source-insecure-tls-skip" not in ids


# ---------- T10 : tkn-knative-sink-http-no-auth --------------------------


def test_t10_http_sink_uri_fires() -> None:
    """Plain http:// sink URI must trigger tkn-knative-sink-http-no-auth."""
    yaml = """\
spec:
  sink:
    uri: http://my-receiver.svc.cluster.local/events
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-knative-sink-http-no-auth" in ids


def test_t10_https_sink_uri_does_not_fire() -> None:
    """HTTPS sink URI must NOT fire the rule."""
    yaml = """\
spec:
  sink:
    uri: https://my-receiver.svc.cluster.local/events
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-knative-sink-http-no-auth" not in ids


# ---------- T11 : tkn-pipeline-finally-no-failure-guard ------------------


def test_t11_finally_without_when_fires() -> None:
    """finally block without when guard must trigger the rule."""
    yaml = """\
spec:
  tasks:
    - name: build
      taskRef:
        name: build-task
  finally:
    - name: notify-slack
      taskRef:
        name: send-slack-alert
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-pipeline-finally-no-failure-guard" in ids


def test_t11_finally_with_when_suppressed() -> None:
    """finally block with a when: guard must NOT fire the rule."""
    yaml = """\
spec:
  tasks:
    - name: build
      taskRef:
        name: build-task
  finally:
    - name: notify-slack
      when:
        - input: $(tasks.build.status)
          operator: in
          values: ["Failed"]
      taskRef:
        name: send-slack-alert
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-pipeline-finally-no-failure-guard" not in ids


# ---------- T12 : tkn-tekton-bundle-latest-tag ---------------------------


def test_t12_bundle_latest_fires() -> None:
    """bundle: gcr.io/org/task-bundle:latest must trigger the rule."""
    yaml = """\
taskRef:
  resolver: bundles
  params:
    - name: bundle
      value: gcr.io/my-org/my-task-bundle:latest
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-tekton-bundle-latest-tag" in ids


def test_t12_bundle_pinned_digest_does_not_fire() -> None:
    """bundle ref pinned with @sha256: digest must NOT fire the rule."""
    yaml = """\
taskRef:
  resolver: bundles
  params:
    - name: bundle
      value: gcr.io/my-org/my-task-bundle@sha256:abc123def456abc123def456abc123def456
"""
    ids = {f.rule_id for f in tnp.scan_text(yaml)}
    assert "tkn-tekton-bundle-latest-tag" not in ids
