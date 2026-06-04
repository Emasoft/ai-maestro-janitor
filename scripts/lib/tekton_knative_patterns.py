"""Tekton Pipelines + Knative Eventing security anti-patterns.

Wave-36 distillation. Catalogue of 12 Tekton / Knative-specific
anti-patterns that are NOT covered by existing modules.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic Kubernetes RBAC / ServiceAccount over-permission —
    ``k8s_rbac_patterns.py``
  * Generic CI/CD secret injection / masking —
    ``ci_cd_secret_patterns.py``
  * Generic SSRF from untrusted webhook targets —
    ``webhook_signature_patterns.py`` / ``dns_email_patterns.py``
  * Generic OCI image pull without digest pinning — supply-chain
    modules.

What IS here (12 net-new rules, regex-only, all RE2-safe):

  * tkn-privileged-step-container                       (CRITICAL)
  * tkn-host-path-volume-mount                          (HIGH)
  * tkn-workspace-optional-without-emptydir             (MEDIUM)
  * tkn-param-substitution-shell-injection              (HIGH)
  * tkn-pipeline-run-service-account-default            (HIGH)
  * tkn-task-result-no-path-sanitize                    (MEDIUM)
  * tkn-knative-broker-no-dlq                           (MEDIUM)
  * tkn-knative-trigger-filter-missing                  (HIGH)
  * tkn-event-source-insecure-tls-skip                  (HIGH)
  * tkn-knative-sink-http-no-auth                       (HIGH)
  * tkn-pipeline-finally-no-failure-guard               (MEDIUM)
  * tkn-tekton-bundle-latest-tag                        (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak / credential exposure
  ASI-04 — Information disclosure (excessive result exposure, debug sinks)
  ASI-05 — Supply-chain / dependency hijacking (bundle latest tags)
  ASI-06 — Container / sandbox escape (privileged, hostPath)
  ASI-07 — Authority / authorisation gaps (missing auth, default SA,
            open broker, trigger without filter)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
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


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- T1 : tkn-privileged-step-container ---------------------------------

# Step or sidecar container with securityContext.privileged: true.
# YAML form: `privileged: true` under a securityContext block.
_PRIVILEGED_STEP = _re(
    r"^\s+privileged\s*:\s*true\s*$"
)


# ---- T2 : tkn-host-path-volume-mount ------------------------------------

# PipelineRun / TaskRun volume of type hostPath — mounts node filesystem.
_HOST_PATH_VOLUME = _re(
    r"\bhostPath\s*:"
    r"|\btype\s*:\s*['\"]?DirectoryOrCreate['\"]?"
    r"|\btype\s*:\s*['\"]?Directory['\"]?\b"
    r"|\bhostPath\s*:\s*\{[^}]{0,120}\bpath\s*:"
)


# ---- T3 : tkn-workspace-optional-without-emptydir -----------------------

# A Workspace declared optional:true but the Task/Pipeline does not
# provide a fallback emptyDir binding — any unbound run crashes.
_WORKSPACE_OPTIONAL = _re(
    r"^\s+optional\s*:\s*true\s*$"
)

_WORKSPACE_EMPTYDIR_BINDING = _re(
    r"\bemptyDir\s*:\s*\{?"
    r"|\bemptyDir\s*:\s*$"
)


# ---- T4 : tkn-param-substitution-shell-injection ------------------------

# Step script uses $(params.X) / $(context.pipeline.name) directly inside
# a shell one-liner without quoting or intermediate variable assignment.
# Pattern: shell-context keywords followed by an unquoted param expansion.
_PARAM_SHELL_INJECT = _re(
    r"(?:sh\s+-c|bash\s+-c|\/bin\/sh\s+-c|\/bin\/bash\s+-c)"
    r"[^'\"]{0,60}\$\((?:params|context)\.[A-Za-z0-9_.\-]{1,80}\)"
)


# ---- T5 : tkn-pipeline-run-service-account-default ---------------------

# PipelineRun / TaskRun with serviceAccountName set to "default" —
# inherits whatever permissions the default SA accumulated.
_SA_DEFAULT = _re(
    r"\bserviceAccountName\s*:\s*['\"]?default['\"]?\b"
)


# ---- T6 : tkn-task-result-no-path-sanitize ------------------------------

# Task step writes a parameter directly to $(results.X.path) via echo
# without first sanitizing the value — an attacker-controlled input can
# embed newlines that poison downstream result parsing.
_RESULT_ECHO_UNSAFE = _re(
    r"\becho\s+.*\$\(?(?:params|inputs)\.[A-Za-z0-9_.\-]{1,80}\)?.*"
    r"\$\(results\.[A-Za-z0-9_.\-]{1,80}\.path\)"
    r"|"
    r"printf\s+.*\$\(?(?:params|inputs)\.[A-Za-z0-9_.\-]{1,80}\)?.*"
    r"\$\(results\.[A-Za-z0-9_.\-]{1,80}\.path\)"
)


# ---- T7 : tkn-knative-broker-no-dlq -------------------------------------

# Knative Broker without a dead-letter-sink configured — silently drops
# events on delivery failure; events are unobservable.
_BROKER_KIND = _re(
    r"kind\s*:\s*Broker\b"
)

_BROKER_DLQ = _re(
    r"\bdeadLetterSink\b"
    r"|\bdead_letter_sink\b"
    r"|\bdlq\b"
)


# ---- T8 : tkn-knative-trigger-filter-missing ----------------------------

# Knative Trigger without a filter spec accepts ALL events from the Broker —
# any event type can activate the subscriber, enabling cross-tenant pivots.
_TRIGGER_KIND = _re(
    r"kind\s*:\s*Trigger\b"
)

_TRIGGER_FILTER = _re(
    r"\bfilter\s*:"
)


# ---- T9 : tkn-event-source-insecure-tls-skip ----------------------------

# EventSource (camel-k / knative-camel-source / eventing-gitlab /
# eventing-github) with insecureSkipVerify: true or tls: {insecure: true}.
_TLS_SKIP_VERIFY = _re(
    r"\binsecureSkipVerify\s*:\s*true\b"
    r"|\binsecure\s*:\s*true\b"
    r"|\bskipTLSVerify\s*:\s*true\b"
    r"|\bverify_ssl\s*:\s*false\b"
    r"|\bdisableTLS\s*:\s*true\b"
)


# ---- T10 : tkn-knative-sink-http-no-auth --------------------------------

# Knative SinkBinding or CloudEventSink pointing to an HTTP (not HTTPS)
# endpoint without OIDC/token auth annotation — event payload is sent
# in cleartext and any observer on the network path can read it.
_SINK_HTTP_PLAIN = _re(
    r"\bsink\s*:"
    r"[^`\"']{0,120}"
    r"""(?:uri|url|address)\s*:\s*['\"]?http://"""
)


# ---- T11 : tkn-pipeline-finally-no-failure-guard ------------------------

# A Pipeline `finally` task calls a cleanup/notification step but does
# NOT guard with `when:` on execution status — the step runs even when
# the pipeline SUCCEEDED, leaking an "alert" on every green run.
_FINALLY_TASK = _re(
    r"^\s+finally\s*:\s*$"
    r"|\bfinallyTasks\s*:"
)

_FINALLY_WHEN_GUARD = _re(
    r"^\s+when\s*:\s*$"
    r"|\bwhen\s*:\s*\["
    r"|\bFailedCondition\b"
    r"|\$\(tasks\.[A-Za-z0-9_\-]{1,80}\.status\)"
)


# ---- T12 : tkn-tekton-bundle-latest-tag ---------------------------------

# Tekton Bundle ref — three forms:
#   1. Direct key:  `bundle: gcr.io/org/name:latest`
#   2. Resolver params value:  `value: gcr.io/org/name:latest`
#      (only under a resolver: bundles / bundle context — we match the
#       value form broadly because false-positives are unlikely in YAML
#       containing "bundle" at all; the broader pattern avoids needing
#       multi-line context in a single RE2 regex)
#   3. URI scheme:  `bundle://gcr.io/org/name:latest`
_BUNDLE_LATEST = _re(
    r"\bbundle\s*:\s*['\"]?[A-Za-z0-9][^'\"\s\n]{1,200}:latest['\"]?"
    r"|\bvalue\s*:\s*['\"]?[A-Za-z0-9][^'\"\s\n]{1,200}:latest['\"]?"
    r"|\bbundle://[^'\"\s\n]{1,200}:latest\b"
)


# ---- The catalogue -------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="tkn-privileged-step-container",
        name="Tekton Step container runs with securityContext.privileged: true",
        severity="CRITICAL",
        description=(
            "A Tekton Task Step (or sidecar) has `privileged: true` in its "
            "securityContext. This gives the container full root access to "
            "the host node kernel, bypassing all namespace and cgroup "
            "isolation. A compromised pipeline step can read secrets from "
            "other pods, modify the node's filesystem, and escape the "
            "cluster. Remove privileged: true and use the minimum required "
            "Linux capabilities instead."
        ),
        pattern=_PRIVILEGED_STEP,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="tkn-host-path-volume-mount",
        name="Tekton Task mounts a hostPath volume — node filesystem exposure",
        severity="HIGH",
        description=(
            "A Tekton Task or PipelineRun mounts a `hostPath` volume, "
            "granting the step direct read/write access to the node's "
            "underlying filesystem. Malicious pipeline code can read "
            "kubelet credentials, other pods' secrets or caches, and "
            "Docker socket files. Replace hostPath with a PVC, emptyDir, "
            "or a Workspace bound to a PVC."
        ),
        pattern=_HOST_PATH_VOLUME,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="tkn-workspace-optional-without-emptydir",
        name="Optional Workspace declared without emptyDir fallback binding",
        severity="MEDIUM",
        description=(
            "A Tekton Task/Pipeline Workspace marked `optional: true` is "
            "not paired with an `emptyDir` fallback in the accompanying "
            "Run resource. If a caller omits the workspace binding, the "
            "Step fails with a runtime error instead of degrading "
            "gracefully. Provide an `emptyDir: {}` fallback binding in "
            "every PipelineRun/TaskRun that uses optional workspaces."
        ),
        pattern=_WORKSPACE_OPTIONAL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="tkn-param-substitution-shell-injection",
        name="Tekton param substitution used unquoted inside sh -c / bash -c",
        severity="HIGH",
        description=(
            "A Task Step script passes a Tekton param substitution "
            "expression — `$(params.X)` — directly inside a `sh -c` or "
            "`bash -c` string without quoting. An attacker who controls "
            "the PipelineRun param value can inject arbitrary shell "
            "commands. Always assign `$(params.X)` to a shell variable "
            "first (`PARAM=\"$(params.X)\"`), then reference `\"$PARAM\"`."
        ),
        pattern=_PARAM_SHELL_INJECT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tkn-pipeline-run-service-account-default",
        name="PipelineRun/TaskRun uses the 'default' ServiceAccount",
        severity="HIGH",
        description=(
            "A PipelineRun or TaskRun sets `serviceAccountName: default`, "
            "inheriting all bindings that have accumulated on the namespace "
            "default ServiceAccount over time. In practice clusters often "
            "have cluster-wide RoleBindings pointing at `default`, giving "
            "pipeline steps far more RBAC than intended. Create a dedicated "
            "least-privilege ServiceAccount for each pipeline."
        ),
        pattern=_SA_DEFAULT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tkn-task-result-no-path-sanitize",
        name="Task Step echoes raw param into results path — newline injection",
        severity="MEDIUM",
        description=(
            "A Task Step pipes an unsanitized `$(params.X)` value directly "
            "into `$(results.Y.path)` via `echo` or `printf`. Tekton "
            "result files are line-delimited; an attacker-controlled "
            "parameter containing embedded newlines can inject extra "
            "key=value pairs, poisoning downstream Pipeline param "
            "substitutions. Sanitize with `tr -d '\\n'` before writing."
        ),
        pattern=_RESULT_ECHO_UNSAFE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tkn-knative-broker-no-dlq",
        name="Knative Broker configured without a dead-letter sink",
        severity="MEDIUM",
        description=(
            "A Knative Broker manifest does not define a `deadLetterSink`. "
            "When event delivery fails after the retry budget is exhausted, "
            "the event is silently dropped with no observable artefact. "
            "Operators cannot distinguish between 'no events' and "
            "'all events failed delivery'. Configure `deadLetterSink` to "
            "route failed events to an error queue or logging channel."
        ),
        pattern=_BROKER_KIND,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="tkn-knative-trigger-filter-missing",
        name="Knative Trigger has no event filter — accepts all Broker events",
        severity="HIGH",
        description=(
            "A Knative Trigger spec contains no `filter:` block, so the "
            "subscriber receives every event published to the Broker "
            "regardless of type or source. In a multi-tenant Broker, "
            "components from other tenants' workflows can trigger the "
            "subscriber unexpectedly, enabling cross-tenant data access or "
            "denial-of-service via event flooding. Add a "
            "`filter.attributes` block limiting the event type and source."
        ),
        pattern=_TRIGGER_KIND,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tkn-event-source-insecure-tls-skip",
        name="EventSource / integration component skips TLS certificate verification",
        severity="HIGH",
        description=(
            "A Knative EventSource or Camel-K integration sets "
            "`insecureSkipVerify: true` (or equivalent), disabling TLS "
            "certificate validation on the upstream event source. This "
            "enables man-in-the-middle attacks: an attacker on the network "
            "path can substitute arbitrary events, inject crafted payloads, "
            "or intercept sensitive event data. Remove the flag and supply "
            "the correct CA bundle instead."
        ),
        pattern=_TLS_SKIP_VERIFY,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="tkn-knative-sink-http-no-auth",
        name="Knative sink URI uses plain HTTP without authentication",
        severity="HIGH",
        description=(
            "A Knative SinkBinding or CloudEvent sink address uses a plain "
            "`http://` URI. Event payloads transit the network unencrypted "
            "and without transport-layer integrity. Any node on the cluster "
            "overlay network or a shared cloud LAN can eavesdrop on or "
            "modify events. Use `https://` sinks and configure OIDC token "
            "authentication via the eventing `auth-secret-ref` annotation."
        ),
        pattern=_SINK_HTTP_PLAIN,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="tkn-pipeline-finally-no-failure-guard",
        name="Pipeline finally task runs on every exit — no failure-status guard",
        severity="MEDIUM",
        description=(
            "A Tekton Pipeline `finally` task (e.g. a Slack notification "
            "or PagerDuty alert) is not guarded by a `when:` expression "
            "that checks `$(tasks.<name>.status)`. The finally step fires "
            "on EVERY pipeline exit — including successful runs — "
            "generating spurious alerts, polluting on-call channels, and "
            "eroding alert trust. Add a `when:` guard using "
            "`$(tasks.<taskname>.status) == Failed`."
        ),
        pattern=_FINALLY_TASK,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="tkn-tekton-bundle-latest-tag",
        name="Tekton Bundle ref uses mutable :latest tag — supply-chain risk",
        severity="HIGH",
        description=(
            "A Tekton TaskRef or PipelineRef resolves a bundle via a "
            "`:latest` OCI tag. Mutable tags can be overwritten by the "
            "registry owner at any time; a compromised registry push can "
            "silently replace the bundle content and execute arbitrary "
            "code in all pipelines using that reference. Pin to an "
            "immutable digest (`@sha256:<hash>`) to guarantee provenance."
        ),
        pattern=_BUNDLE_LATEST,
        owasp_asi="ASI-05",
    ),
)


# ---- Scanner-level helpers ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against ``text`` and return findings.

    Stage-B context filters:

      * T3 (workspace-optional-without-emptydir) — flag only when the same
        file does NOT contain an emptyDir fallback binding anywhere.
      * T7 (knative-broker-no-dlq) — anchor on kind: Broker and require
        NO deadLetterSink marker anywhere in the same file.
      * T8 (knative-trigger-filter-missing) — anchor on kind: Trigger and
        require NO filter: block anywhere in the same file.
      * T11 (pipeline-finally-no-failure-guard) — anchor on finally: and
        require NO when: / status guard anywhere in the same file.

    All other rules fire on the primary pattern match alone (the pattern
    is sufficiently precise to stand alone without context gating).
    """
    findings: list[Finding] = []
    file_has_emptydir = _file_contains(text, _WORKSPACE_EMPTYDIR_BINDING)
    file_has_broker_dlq = _file_contains(text, _BROKER_DLQ)
    file_has_trigger_filter = _file_contains(text, _TRIGGER_FILTER)
    file_has_finally_when = _file_contains(text, _FINALLY_WHEN_GUARD)

    for rule in RULES:
        for match in rule.pattern.finditer(text):
            line_no, col = _line_col(text, match.start())
            matched = match.group(0)

            # --- Stage-B context gates ---

            if rule.id == "tkn-workspace-optional-without-emptydir":
                if file_has_emptydir:
                    continue

            elif rule.id == "tkn-knative-broker-no-dlq":
                if file_has_broker_dlq:
                    continue

            elif rule.id == "tkn-knative-trigger-filter-missing":
                if file_has_trigger_filter:
                    continue

            elif rule.id == "tkn-pipeline-finally-no-failure-guard":
                if file_has_finally_when:
                    continue

            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line_no,
                    column=col,
                    matched_text=matched,
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )

    return findings
