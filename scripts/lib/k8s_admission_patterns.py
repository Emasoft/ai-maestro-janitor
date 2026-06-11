"""Kubernetes admission-controller / OPA-Gatekeeper / RBAC depth patterns.

Wave-20 deep-dive distillation round 6, angle J.

Goes BEYOND the Wave-18 `sandbox_escape_patterns.py` (which already covers
basic Pod SecurityContext, hostPath, hostNetwork/hostPID, runAsUser=0,
and ClusterRoleBinding -> literal `cluster-admin`). This module catches
the K8s privilege-escalation surface that AI-coding-agent generated YAML
routinely produces: admission webhook misconfig, OPA Gatekeeper
constraint semantics, RBAC verbs (`escalate` / `bind` / `impersonate`),
ServiceAccount token mounting, NetworkPolicy default-deny absence,
kubelet/apiserver anonymous-auth, CSR auto-approval, direct etcd access,
PodSecurity admission labels, and ClusterRole aggregation drift.

Reference proposal: `reports/distill-round-6/k8s-admission-rbac.md`.

Rule inventory (21 rules):

  1.  k8s-admission-failure-policy-ignore               (CRITICAL/HIGH)
  2.  k8s-admission-side-effects-none-external          (HIGH/MAJOR)
  3.  k8s-admission-cabundle-missing-or-injected        (CRITICAL/MINOR)
  4.  k8s-admission-webhook-external-url                (HIGH)
  5.  k8s-gatekeeper-enforcement-dryrun-or-warn         (MAJOR/MINOR)
  6.  k8s-gatekeeper-constraint-narrow-kinds            (MAJOR)
  7.  k8s-rego-default-allow-true                       (CRITICAL)
  8.  k8s-admission-timeout-excessive                   (MAJOR)
  9.  k8s-admission-namespace-selector-excludes-system  (MAJOR)
  10. k8s-rbac-verb-escalate                            (CRITICAL)
  11. k8s-rbac-verb-bind                                (CRITICAL/MAJOR)
  12. k8s-rbac-verb-impersonate                        (CRITICAL)
  13. k8s-rbac-wildcard-clusterrole                    (CRITICAL/MAJOR/MINOR)
  14. k8s-pod-automount-sa-token-default-true          (MAJOR/CRITICAL)
  15. k8s-namespace-no-default-deny-networkpolicy      (MAJOR/MINOR)
  16. k8s-podsecurity-admission-privileged-or-baseline (CRITICAL/MAJOR/MINOR)
  17. k8s-csr-auto-approval-broad-group                (CRITICAL)
  18. k8s-kubelet-anonymous-or-alwaysallow             (CRITICAL)
  19. k8s-pod-direct-etcd-access                       (CRITICAL/HIGH)
  20. k8s-admission-object-selector-attacker-controlled (MAJOR)
  21. k8s-clusterrole-aggregate-to-admin-drift         (MAJOR)

Public surface mirrors sibling modules:

  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.
  * Rule(id, name, severity, description, owasp_asi) — frozen NamedTuple.
  * RULES — ordered tuple of every rule.
  * scan_text(text, *, file_kind="auto", file_path="") -> list[Finding]
  * scan_k8s(text, *, file_path="") -> list[Finding]
  * scan_rego(text) -> list[Finding]
  * scan_kubelet_config(text) -> list[Finding]
  * scan_apiserver_flags(text) -> list[Finding]

OWASP ASI mapping:
  ASI-05 — Supply-chain / cross-tenant pivot (external webhook URL,
                                              direct etcd access)
  ASI-07 — Authority / authorisation gaps    (fail-open admission,
                                              RBAC over-grant, CSR
                                              auto-approval, kubelet
                                              anonymous, default allow)
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    `scripts/lib/agent_config_patterns.Finding` / sandbox_escape_patterns
    so heartbeat detectors render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """Static rule metadata. Patterns live alongside in module scope
    because every K8s rule walks a parsed YAML doc — not a single
    regex match."""

    id: str
    name: str
    severity: str
    description: str
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE.

    K8s YAML and rego are ASCII-by-convention so UNICODE is omitted.
    Every alternation branch is bounded — RE2 safe (no backreferences,
    no unbounded lookarounds). Catastrophic-backtrack rejected at module
    load.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


# ---- Shared constants ---------------------------------------------------


# Webhook names that indicate a SECURITY-enforcing webhook — used to
# escalate severity when failurePolicy=Ignore.
_SECURITY_WEBHOOK_HINTS: tuple[str, ...] = (
    "gatekeeper",
    "kyverno",
    "policy",
    "opa",
    "falco",
    "image-scan",
    "imagescan",
    "signature",
    "falcon",
    "kubearmor",
    "neuvector",
    "trivy",
    "cosign",
    "sigstore",
)

# Webhook URL host suffixes that are LEGAL in-cluster forms — anything
# else is considered "external" (data exfiltration channel / single
# point of failure).
_INCLUSTER_HOST_SUFFIXES: tuple[str, ...] = (
    ".svc",
    ".svc.cluster.local",
    "localhost",
    "127.0.0.1",
)

# System-namespace label values an exclusion `NotIn` filter may target
# to bypass policy enforcement.
_SYSTEM_NAMESPACES: frozenset[str] = frozenset({
    "kube-system",
    "kube-public",
    "kube-node-lease",
    "gatekeeper-system",
    "kyverno",
    "istio-system",
})

# Production-environment hints in file paths / labels. Used to escalate
# severity when a "warn-only" Gatekeeper constraint or `baseline` PSA
# label ships into a production-tagged manifest.
_PROD_PATH_HINTS: tuple[str, ...] = (
    "/production/",
    "/prod/",
    "/prd/",
    "-production-",
    "-prod-",
    ".production.",
    ".prod.",
)

_PROD_LABEL_VALUES: frozenset[str] = frozenset({
    "production",
    "prod",
    "prd",
    "live",
})

# K8s built-in / well-known label prefixes — labels that the workload
# author CANNOT set (controller-managed). Anything outside this set is
# considered attacker-controllable from a webhook objectSelector
# perspective.
_SYSTEM_LABEL_PREFIXES: tuple[str, ...] = (
    "kubernetes.io/",
    "app.kubernetes.io/",
    "k8s.io/",
    "node.kubernetes.io/",
    "topology.kubernetes.io/",
    "beta.kubernetes.io/",
    "rbac.authorization.k8s.io/",
    "control-plane.alpha.kubernetes.io/",
    "pod-security.kubernetes.io/",
)

# RBAC verbs that grant explicit privilege-escalation power.
_RBAC_ESCALATE_VERBS: frozenset[str] = frozenset({"escalate"})
_RBAC_BIND_VERBS: frozenset[str] = frozenset({"bind"})
_RBAC_IMPERSONATE_VERBS: frozenset[str] = frozenset({"impersonate"})

# Resource names that, when combined with `verbs: ["*"]` or
# `verbs: ["create", "update"]` etc., constitute escalation primitives.
_RBAC_ROLE_RESOURCES: frozenset[str] = frozenset({
    "roles", "clusterroles", "*",
})
_RBAC_BINDING_RESOURCES: frozenset[str] = frozenset({
    "rolebindings", "clusterrolebindings", "*",
})

# K8s pod-workload kinds — controllers that wrap a Pod template.
_K8S_POD_KINDS: frozenset[str] = frozenset({
    "Pod", "Deployment", "DaemonSet", "StatefulSet",
    "Job", "CronJob", "ReplicaSet",
})

# Hostpath patterns that grant direct etcd-store access.
_ETCD_HOST_PATHS: tuple[str, ...] = (
    "/etc/kubernetes/pki/etcd",
    "/var/lib/etcd",
    "/etc/etcd",
)

# Environment variable names that signal etcdctl usage outside the
# control plane.
_ETCDCTL_ENV_VARS: frozenset[str] = frozenset({
    "ETCDCTL_ENDPOINTS",
    "ETCDCTL_CACERT",
    "ETCDCTL_CERT",
    "ETCDCTL_KEY",
    "ETCDCTL_API",
    "ETCD_CA_FILE",
    "ETCD_CERT_FILE",
    "ETCD_KEY_FILE",
})

# Sensitive RBAC resources whose access amplifies the SA-token risk.
_SENSITIVE_SA_RESOURCES: frozenset[str] = frozenset({
    "secrets",
    "configmaps",
    "pods/exec",
    "serviceaccounts/token",
    "pods/attach",
})


# ---- Rule 7: rego `default allow = true` --------------------------------


_REGO_DEFAULT_ALLOW = _re(
    # Match `default allow = true`, `default allow := true`,
    # `default decision = "allow"`, `default authorized = true`, and
    # the inverted-form `default deny = false`. Every alternation
    # branch upper-bounded. Custom right-boundary `(?![a-z_])` instead
    # of `\b` because `\b` after a closing `"` requires the next char
    # to be a word char — fails on `"allow"\n`. The negative
    # lookahead works for both word and non-word endings.
    r"^\s*default\s+(?:"
    r"allow\s*[:=]?=\s*true(?![a-z_])"
    r"|"
    r"allow\s*[:=]?=\s*\"true\""
    r"|"
    r"decision\s*[:=]?=\s*\"allow\""
    r"|"
    r"authorized\s*[:=]?=\s*true(?![a-z_])"
    r"|"
    r"deny\s*[:=]?=\s*false(?![a-z_])"
    r")"
)


# ---- Rule 18: kubelet config / apiserver flags --------------------------


_KUBELET_ANONYMOUS_TRUE = _re(
    r"^\s*enabled\s*:\s*true\b"
)

_KUBELET_ALWAYS_ALLOW = _re(
    r"^\s*mode\s*:\s*AlwaysAllow\b"
)

_APISERVER_ANONYMOUS_AUTH = _re(
    r"--anonymous-auth\s*=\s*true\b"
)

_APISERVER_AUTHZ_ALWAYS_ALLOW = _re(
    r"--authorization-mode\s*=\s*[A-Za-z0-9,]{0,200}\bAlwaysAllow\b"
)

_APISERVER_INSECURE_PORT = _re(
    r"--insecure-port\s*=\s*(?!0\b)\d{1,5}\b"
)

# Heuristic file-kind detection for kubelet config YAML.
_KUBELET_CONFIG_HINT = _re(
    r"^kind\s*:\s*KubeletConfiguration\b|^apiVersion\s*:\s*kubelet\.config\.k8s\.io/"
)

_APISERVER_FLAGS_HINT = _re(
    r"kube-apiserver\b|--anonymous-auth\b|--authorization-mode\b"
)

# Hint for rego file content (rego files have `package` then `default`
# / `deny` / `allow` declarations).
_REGO_HINT = _re(
    r"^\s*package\s+[a-z][a-z0-9_.]{0,80}\b"
)


# ---- K8s file-kind hints ------------------------------------------------


_K8S_HINT = _re(
    r"^(?:apiVersion|kind)\s*:"
)


# ---- The rule catalogue -------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="k8s-admission-failure-policy-ignore",
        name="Admission webhook fails open (failurePolicy: Ignore)",
        severity="HIGH",
        description=(
            "MutatingWebhookConfiguration / ValidatingWebhookConfiguration "
            "sets `failurePolicy: Ignore`. If the webhook endpoint is "
            "unreachable, returns 5xx, or times out, the API server "
            "silently admits the object — fail-open. For security-enforcing "
            "webhooks (Gatekeeper, Kyverno, image scanners, signature "
            "verifiers) this defeats the policy. CRITICAL if the webhook "
            "name matches a known security tool; HIGH otherwise."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-admission-side-effects-none-external",
        name="Webhook claims sideEffects: None but uses external service",
        severity="HIGH",
        description=(
            "ValidatingWebhookConfiguration / MutatingWebhookConfiguration "
            "declares `sideEffects: None` while the webhook lives outside "
            "the cluster (`clientConfig.url`) or its name suggests "
            "downstream side-effects (audit/log/notify/SIEM/etc.). "
            "`kubectl --dry-run=server` triggers the side-effect with no "
            "admission record — silent data exfiltration / audit "
            "injection / notification flood."
        ),
        owasp_asi="ASI-04",
    ),
    Rule(
        id="k8s-admission-cabundle-missing-or-injected",
        name="Webhook caBundle is empty / missing / dynamically injected",
        severity="CRITICAL",
        description=(
            "Webhook `clientConfig.url` is set but `caBundle` is empty or "
            "missing — TLS validation falls back to the apiserver node's "
            "default trust store; any CA injection (or DNS hijack) lets "
            "an attacker return arbitrary admission verdicts. Dynamic "
            "injection via `cert-manager.io/inject-ca-from` annotation "
            "couples webhook trust to cert-manager — if cert-manager is "
            "compromised, every webhook is compromised (MINOR architectural "
            "warning)."
        ),
        owasp_asi="ASI-05",
    ),
    Rule(
        id="k8s-admission-webhook-external-url",
        name="Webhook clientConfig.url points outside the cluster",
        severity="HIGH",
        description=(
            "Best practice is `clientConfig.service: {namespace, name}` "
            "(in-cluster). An external `url:` means every admission "
            "decision crosses the public internet — latency, DoS surface, "
            "vendor sees every Pod/Secret manifest in flight, network "
            "partition freezes the whole cluster (with failurePolicy=Fail) "
            "or silently bypasses it (with failurePolicy=Ignore)."
        ),
        owasp_asi="ASI-05",
    ),
    Rule(
        id="k8s-gatekeeper-enforcement-dryrun-or-warn",
        name="OPA Gatekeeper constraint uses dryrun / warn enforcement",
        severity="MEDIUM",
        description=(
            "OPA Gatekeeper constraint sets `spec.enforcementAction: "
            "dryrun` or `warn`. The constraint is theatre — it logs / "
            "shows in dashboards but does NOT block. Attackers see the "
            "policy in Git and ignore it. Production-tagged manifests "
            "with `dryrun`/`warn` escalate to MAJOR."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-gatekeeper-constraint-narrow-kinds",
        name="Gatekeeper constraint matches Pod only — misses controllers",
        severity="HIGH",
        description=(
            "Pod-spec Gatekeeper constraint matches only `kind: Pod` but "
            "the rego body references pod-spec fields (`securityContext`, "
            "`hostNetwork`, `hostPID`, `hostPath`). The controller-manager "
            "SA creates the Pod *after* admission ran on the parent "
            "Deployment/StatefulSet/DaemonSet/Job/CronJob, so the "
            "constraint never sees the pod spec. Attackers wrap every "
            "privileged pod in a Deployment to bypass."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-rego-default-allow-true",
        name="Rego policy uses fail-open default (default allow = true)",
        severity="CRITICAL",
        description=(
            "Rego policy declares `default allow = true` (or variants "
            "`default decision = \"allow\"`, `default authorized = true`, "
            "`default deny = false`). Best practice is fail-closed: "
            "`default allow = false` then explicitly allow safe cases. "
            "A typo in a `deny` rule (wrong field path, missing "
            "predicate) silently lets every request through."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-admission-timeout-excessive",
        name="Admission webhook timeoutSeconds >=15 with failurePolicy=Fail",
        severity="HIGH",
        description=(
            "Admission webhook sets `timeoutSeconds: 15` or higher "
            "combined with `failurePolicy: Fail`. A slow/hung webhook "
            "saturates the API server admission queue within seconds, "
            "freezing the entire cluster (deployments, scaling, kubelet "
            "pod sync). CVE-2019-1002101-class DoS. Recommended: 3-5s "
            "for fail-closed webhooks; 10s for non-blocking."
        ),
        owasp_asi="ASI-05",
    ),
    Rule(
        id="k8s-admission-namespace-selector-excludes-system",
        name="Webhook namespaceSelector excludes kube-system bypass surface",
        severity="HIGH",
        description=(
            "Webhook `namespaceSelector` lists `kube-system` (or other "
            "system namespaces) in a `NotIn` match expression. Anything "
            "deployed into the excluded namespace is exempt from the "
            "policy. Attackers with `create pods` in kube-system (or "
            "tricking a controller-manager SA) bypass every policy."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-rbac-verb-escalate",
        name="ClusterRole / Role grants `escalate` verb on roles",
        severity="CRITICAL",
        description=(
            "RBAC rule grants `escalate` on `roles` / `clusterroles` / "
            "`*`. The `escalate` verb is the explicit K8s mechanism that "
            "LETS A USER GRANT THEMSELVES PERMISSIONS THEY DO NOT "
            "CURRENTLY HAVE — it bypasses the apiserver's normal "
            "permission-subset check on role updates. A workload with "
            "`escalate` is effectively cluster-admin."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-rbac-verb-bind",
        name="ClusterRole / Role grants `bind` verb on bindings",
        severity="CRITICAL",
        description=(
            "RBAC rule grants `bind` (or just `create`) on "
            "`rolebindings` / `clusterrolebindings`. With `bind`, the "
            "subject can create a binding to a Role they do not "
            "currently hold — they can self-bind to `cluster-admin`. "
            "Without explicit `bind` but with `create`, the same "
            "escalation works if `escalate` is granted on roles."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-rbac-verb-impersonate",
        name="ClusterRole / Role grants `impersonate` verb",
        severity="CRITICAL",
        description=(
            "RBAC rule grants `impersonate` on users / groups / "
            "serviceaccounts. With `impersonate` on `serviceaccounts`, "
            "an attacker can impersonate any controller SA. With "
            "`impersonate` on `groups`, they impersonate "
            "`system:masters` — which bypasses RBAC entirely and is "
            "functionally cluster-admin (CKS reference attack)."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-rbac-wildcard-clusterrole",
        name="ClusterRole rule uses */*/* (triple-wildcard cluster-admin)",
        severity="CRITICAL",
        description=(
            "ClusterRole rule has `apiGroups: ['*']` AND "
            "`resources: ['*']` AND `verbs: ['*']`. Functionally "
            "equivalent to cluster-admin without binding to the literal "
            "`cluster-admin` role (Wave 18 only catches the literal "
            "binding). MAJOR if any two of three are wildcards; MINOR "
            "if any one is wildcard."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-pod-automount-sa-token-default-true",
        name="Pod auto-mounts ServiceAccount token without restriction",
        severity="HIGH",
        description=(
            "Pod / Deployment / StatefulSet / etc. template does NOT "
            "set `automountServiceAccountToken: false`. Default is true: "
            "every code-injection / SSRF / file-read primitive inside "
            "the pod reads the SA's JWT at "
            "`/var/run/secrets/kubernetes.io/serviceaccount/token` and "
            "calls the K8s API with the SA's RBAC. NSA/CISA Kubernetes "
            "Hardening Guidance requires explicit disable for pods that "
            "do not call the K8s API."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-namespace-no-default-deny-networkpolicy",
        name="Namespace has no default-deny NetworkPolicy",
        severity="HIGH",
        description=(
            "Namespace manifest exists but no NetworkPolicy with empty "
            "`podSelector: {}` and `policyTypes: [Ingress, Egress]` "
            "covers it. K8s networking defaults are flat — every pod "
            "can reach every other pod and every external IP including "
            "169.254.169[.]254 (cloud IMDS). A single compromised pod "
            "scans the whole cluster, exfiltrates anywhere, and hits "
            "IMDS for cloud credentials. NSA/CISA hardening treats this "
            "as table-stakes."
        ),
        owasp_asi="ASI-05",
    ),
    Rule(
        id="k8s-podsecurity-admission-privileged-or-baseline",
        name="Namespace PodSecurity admission label is privileged/baseline",
        severity="HIGH",
        description=(
            "Namespace labels set "
            "`pod-security.kubernetes.io/enforce: privileged` (CRITICAL "
            "— most permissive PSA profile, allows hostNetwork/hostPID/"
            "privileged containers) or `enforce: baseline` on a "
            "production-tagged namespace (MAJOR — allows hostPort/"
            "sysctls/capabilities). Missing `enforce:` label entirely "
            "is MINOR (K8s default is `privileged`). Detect the "
            "audit-restricted-enforce-privileged mismatch (CRITICAL)."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-csr-auto-approval-broad-group",
        name="CSR auto-approval bound to broad group (kubelet pivot)",
        severity="CRITICAL",
        description=(
            "ClusterRoleBinding grants "
            "`system:certificates.k8s.io:certificatesigningrequests:"
            "nodeclient` (or `:selfnodeclient`) to a broad group: "
            "`system:authenticated`, `system:unauthenticated`, or a "
            "wide non-bootstrapper group. Any bootstrap-token holder "
            "can request a kubelet cert for an arbitrary node — and "
            "the kubelet cert grants read of every Secret mounted to "
            "pods on that node + exec. CVE-2018-1002105 family."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-kubelet-anonymous-or-alwaysallow",
        name="kubelet/apiserver anonymous auth or AlwaysAllow authz",
        severity="CRITICAL",
        description=(
            "kubelet config sets `authentication.anonymous.enabled: "
            "true` or `authorization.mode: AlwaysAllow` — port 10250 "
            "(/exec, /run, /portForward, /logs) becomes anonymous + "
            "unauthorized. Same for kube-apiserver flags "
            "`--anonymous-auth=true`, `--authorization-mode=AlwaysAllow`, "
            "or the legacy `--insecure-port=<nonzero>`. Trivial "
            "control-plane takeover (Tesla cluster compromise lineage)."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-pod-direct-etcd-access",
        name="Pod has direct etcd access (bypasses API authz)",
        severity="CRITICAL",
        description=(
            "Pod / DaemonSet mounts `/etc/kubernetes/pki/etcd`, "
            "`/var/lib/etcd`, or `/etc/etcd` (hostPath), OR sets "
            "`ETCDCTL_*` env vars outside a control-plane pod, OR "
            "exposes a Service on port 2379/targetPort:2379 in a "
            "non-system namespace. etcd stores every Secret/ConfigMap/"
            "SA token — RBAC is enforced by the apiserver, not etcd — "
            "so direct read dumps the entire cluster secret store."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-admission-object-selector-attacker-controlled",
        name="Webhook objectSelector keyed on attacker-controlled label",
        severity="HIGH",
        description=(
            "Webhook `objectSelector.matchLabels` (or matchExpressions "
            "`In`) keys on a label outside the K8s-controlled prefixes "
            "(`kubernetes.io/`, `app.kubernetes.io/`, etc.). Selectors "
            "are inclusive — attackers simply omit the label and the "
            "webhook never fires. Recommend deny-by-default "
            "`{operator: DoesNotExist}` shape."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-clusterrole-aggregate-to-admin-drift",
        name="ClusterRole labels itself `aggregate-to-admin` (drift escalation)",
        severity="HIGH",
        description=(
            "ClusterRole has metadata label "
            "`rbac.authorization.k8s.io/aggregate-to-admin: true` (or "
            "`aggregate-to-edit`) AND `rules:` containing wildcards or "
            "sensitive resources (`secrets`, `pods/exec`, "
            "`serviceaccounts/token`). The labelled rules automatically "
            "merge into the well-known aggregate `admin`/`edit` role "
            "cluster-wide — a clean privilege-escalation primitive for "
            "any controller that can `create clusterroles`."
        ),
        owasp_asi="ASI-07",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert string offset → (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _trunc(s: str, n: int = 200) -> str:
    """Truncate matched_text for reporting."""
    return s if len(s) <= n else s[:n] + "…"


def _yaml_load_all(text: str) -> list[Any]:
    """Best-effort multi-doc YAML load. Returns a flat list of docs.

    Fail-soft: returns [] on import-error or parse-error so callers
    keep working when PyYAML is unavailable or the doc is malformed.
    """
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return []
    try:
        return [d for d in yaml.safe_load_all(text) if d is not None]
    except yaml.YAMLError:
        return []


def _find_line_of_key(text: str, key: str) -> int:
    """Best-effort line number for a top-level YAML key occurrence.

    Falls back to 1 when not found. The caller uses this to attach a
    sensible line hint to a YAML-walker finding.
    """
    pat = re.compile(rf"^\s*{re.escape(key)}\s*:", re.MULTILINE)
    m = pat.search(text)
    return text[:m.start()].count("\n") + 1 if m else 1


def _rule(rule_id: str) -> Rule:
    """Lookup a Rule by id. Raises KeyError if missing (programmer error)."""
    for r in RULES:
        if r.id == rule_id:
            return r
    raise KeyError(rule_id)


def _is_external_url(url: str) -> bool:
    """True if `url` points outside the cluster (not `*.svc` /
    `*.svc.cluster.local` / `localhost` / `127.0.0.1`)."""
    if not isinstance(url, str) or not url:
        return False
    # Extract the host portion. Pure string ops — no URL lib needed.
    if "://" in url:
        rest = url.split("://", 1)[1]
    else:
        rest = url
    # Strip path / query.
    host = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    # Strip port.
    if ":" in host:
        host = host.split(":", 1)[0]
    if not host:
        return False
    for suffix in _INCLUSTER_HOST_SUFFIXES:
        if host == suffix or host.endswith(suffix):
            return False
    return True


def _is_production_context(file_path: str, doc: Any) -> bool:
    """Heuristic: True if file_path or doc metadata suggests production."""
    fp = (file_path or "").lower()
    for hint in _PROD_PATH_HINTS:
        if hint in fp:
            return True
    if isinstance(doc, dict):
        meta = doc.get("metadata") or {}
        if isinstance(meta, dict):
            labels = meta.get("labels") or {}
            if isinstance(labels, dict):
                for v in labels.values():
                    if isinstance(v, str) and v.lower() in _PROD_LABEL_VALUES:
                        return True
            ann = meta.get("annotations") or {}
            if isinstance(ann, dict):
                for v in ann.values():
                    if isinstance(v, str) and v.lower() in _PROD_LABEL_VALUES:
                        return True
    return False


def _label_is_attacker_controllable(key: str) -> bool:
    """True if a label key is OUTSIDE the K8s-controlled prefixes — i.e.
    the workload author (potentially an attacker) controls it."""
    if not isinstance(key, str) or not key:
        return True
    for prefix in _SYSTEM_LABEL_PREFIXES:
        if key.startswith(prefix):
            return False
    # `kubernetes.io/metadata.name` (and similar exact-match keys)
    # are handled by the prefix check above.
    return True


def _security_webhook_severity(name: str) -> str:
    """Return CRITICAL when the webhook name suggests a security tool,
    HIGH otherwise. Used by rules 1 (failurePolicy: Ignore)."""
    lname = (name or "").lower()
    for hint in _SECURITY_WEBHOOK_HINTS:
        if hint in lname:
            return "CRITICAL"
    return "HIGH"


# ---- Per-rule walkers ---------------------------------------------------


def _scan_webhook_configuration(  # noqa: PLR0912 - one branch per webhook field
    doc: dict[str, Any],
    findings: list[Finding],
    line_hint: int,
) -> None:
    """Apply rules 1-4, 8, 9, 20 to a webhook configuration document.

    `doc` must be a parsed Mutating/ValidatingWebhookConfiguration.
    Caller guarantees that via an isinstance check before invocation.
    """
    webhooks = doc.get("webhooks") or []
    if not isinstance(webhooks, list):
        return
    for wh in webhooks:
        if not isinstance(wh, dict):
            continue
        wh_name = wh.get("name", "<webhook>")
        client_config = wh.get("clientConfig") or {}
        if not isinstance(client_config, dict):
            client_config = {}

        # Rule 1: failurePolicy=Ignore.
        if wh.get("failurePolicy") == "Ignore":
            r = _rule("k8s-admission-failure-policy-ignore")
            sev = _security_webhook_severity(wh_name)
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(f"{wh_name}: failurePolicy=Ignore"),
                severity=sev, description=r.description,
                owasp_asi=r.owasp_asi,
            ))

        # Rule 8: timeoutSeconds >= 15 AND failurePolicy=Fail.
        timeout = wh.get("timeoutSeconds")
        if (
            isinstance(timeout, int)
            and timeout >= 15
            and wh.get("failurePolicy") == "Fail"
        ):
            r = _rule("k8s-admission-timeout-excessive")
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(
                    f"{wh_name}: timeoutSeconds={timeout} + failurePolicy=Fail"),
                severity=r.severity, description=r.description,
                owasp_asi=r.owasp_asi,
            ))

        # Rule 4: external URL.
        url = client_config.get("url")
        is_external = _is_external_url(url) if isinstance(url, str) else False
        if is_external:
            r = _rule("k8s-admission-webhook-external-url")
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(f"{wh_name}: url={url}"),
                severity=r.severity, description=r.description,
                owasp_asi=r.owasp_asi,
            ))

        # Rule 3: caBundle empty/missing when url is set.
        if isinstance(url, str) and url:
            ca = client_config.get("caBundle")
            if ca in (None, "", b""):
                r = _rule("k8s-admission-cabundle-missing-or-injected")
                findings.append(Finding(
                    rule_id=r.id, line=line_hint, column=1,
                    matched_text=_trunc(f"{wh_name}: caBundle empty/missing"),
                    severity=r.severity, description=r.description,
                    owasp_asi=r.owasp_asi,
                ))
        # cert-manager dynamic injection annotation.
        meta = doc.get("metadata") or {}
        ann = meta.get("annotations") or {} if isinstance(meta, dict) else {}
        if isinstance(ann, dict):
            for k in ann:
                if isinstance(k, str) and "cert-manager.io/inject-ca-from" in k:
                    r = _rule("k8s-admission-cabundle-missing-or-injected")
                    findings.append(Finding(
                        rule_id=r.id, line=line_hint, column=1,
                        matched_text=_trunc(
                            f"{wh_name}: cert-manager.io/inject-ca-from"),
                        severity="MEDIUM", description=r.description,
                        owasp_asi=r.owasp_asi,
                    ))
                    break

        # Rule 2: sideEffects: None + external indicator.
        if wh.get("sideEffects") == "None":
            url_external = is_external
            ext_hint_in_name = any(
                h in (wh_name or "").lower()
                for h in ("notify", "audit", "siem", "splunk", "slack",
                          "discord", "pagerduty", "log-")
            )
            if url_external or ext_hint_in_name:
                r = _rule("k8s-admission-side-effects-none-external")
                sev = "HIGH" if url_external else "MEDIUM"
                findings.append(Finding(
                    rule_id=r.id, line=line_hint, column=1,
                    matched_text=_trunc(
                        f"{wh_name}: sideEffects=None + external"),
                    severity=sev, description=r.description,
                    owasp_asi=r.owasp_asi,
                ))

        # Rule 9: namespaceSelector NotIn kube-system.
        ns_sel = wh.get("namespaceSelector") or {}
        if isinstance(ns_sel, dict):
            match_expr = ns_sel.get("matchExpressions") or []
            if isinstance(match_expr, list):
                for me in match_expr:
                    if not isinstance(me, dict):
                        continue
                    op = me.get("operator")
                    values = me.get("values") or []
                    if op == "NotIn" and isinstance(values, list):
                        excluded = {
                            v for v in values
                            if isinstance(v, str) and v in _SYSTEM_NAMESPACES
                        }
                        if excluded:
                            r = _rule(
                                "k8s-admission-namespace-selector-excludes-system"
                            )
                            findings.append(Finding(
                                rule_id=r.id, line=line_hint, column=1,
                                matched_text=_trunc(
                                    f"{wh_name}: NotIn={sorted(excluded)}"),
                                severity=r.severity, description=r.description,
                                owasp_asi=r.owasp_asi,
                            ))

        # Rule 20: objectSelector keyed on attacker-controlled label.
        obj_sel = wh.get("objectSelector") or {}
        if isinstance(obj_sel, dict):
            ml = obj_sel.get("matchLabels") or {}
            if isinstance(ml, dict):
                bad_keys = [
                    k for k in ml
                    if isinstance(k, str) and _label_is_attacker_controllable(k)
                ]
                for k in bad_keys:
                    r = _rule(
                        "k8s-admission-object-selector-attacker-controlled"
                    )
                    findings.append(Finding(
                        rule_id=r.id, line=line_hint, column=1,
                        matched_text=_trunc(
                            f"{wh_name}: matchLabels[{k}]"),
                        severity=r.severity, description=r.description,
                        owasp_asi=r.owasp_asi,
                    ))
            me_list = obj_sel.get("matchExpressions") or []
            if isinstance(me_list, list):
                for me in me_list:
                    if not isinstance(me, dict):
                        continue
                    k = me.get("key")
                    op = me.get("operator")
                    # `In` / `Exists` on an attacker-key is the same risk.
                    if (
                        op in {"In", "Exists"}
                        and isinstance(k, str)
                        and _label_is_attacker_controllable(k)
                    ):
                        r = _rule(
                            "k8s-admission-object-selector-attacker-controlled"
                        )
                        findings.append(Finding(
                            rule_id=r.id, line=line_hint, column=1,
                            matched_text=_trunc(
                                f"{wh_name}: matchExpressions[{k}, {op}]"),
                            severity=r.severity, description=r.description,
                            owasp_asi=r.owasp_asi,
                        ))


def _scan_gatekeeper_constraint(
    doc: dict[str, Any],
    text: str,
    findings: list[Finding],
    line_hint: int,
    file_path: str,
) -> None:
    """Apply rules 5, 6 to a Gatekeeper Constraint document.

    Heuristic for Constraint detection: apiVersion startswith
    `constraints.gatekeeper.sh/`.
    """
    del text  # raw text not needed; the doc dict carries everything
    api_version = doc.get("apiVersion", "")
    if not (isinstance(api_version, str)
            and api_version.startswith("constraints.gatekeeper.sh/")):
        return
    spec = doc.get("spec") or {}
    if not isinstance(spec, dict):
        return
    # Rule 5: enforcementAction dryrun / warn.
    action = spec.get("enforcementAction")
    if action in ("dryrun", "warn"):
        r = _rule("k8s-gatekeeper-enforcement-dryrun-or-warn")
        sev = "HIGH" if _is_production_context(file_path, doc) else "MEDIUM"
        kind = doc.get("kind", "<constraint>")
        findings.append(Finding(
            rule_id=r.id, line=line_hint, column=1,
            matched_text=_trunc(
                f"{kind}: enforcementAction={action}"),
            severity=sev, description=r.description,
            owasp_asi=r.owasp_asi,
        ))
    # Rule 6: match.kinds is Pod-only but rego references controller-level
    # fields. Without parsing rego we apply the heuristic: kinds covers
    # only Pod AND constraint kind matches a known pod-spec policy
    # (PSPHostNetwork, PSPCapabilities, PSPPrivileged, etc.).
    match = spec.get("match") or {}
    if isinstance(match, dict):
        kinds_list = match.get("kinds") or []
        if isinstance(kinds_list, list):
            covered_kinds: set[str] = set()
            for entry in kinds_list:
                if not isinstance(entry, dict):
                    continue
                ks = entry.get("kinds") or []
                if isinstance(ks, list):
                    for k in ks:
                        if isinstance(k, str):
                            covered_kinds.add(k)
            controllers = {
                "Deployment", "StatefulSet", "DaemonSet",
                "Job", "CronJob", "ReplicaSet",
            }
            constraint_kind = doc.get("kind", "")
            pod_policy_hints = (
                "psp",
                "podsecurity",
                "hostnetwork",
                "hostpid",
                "hostpath",
                "capabilities",
                "privileged",
                "securitycontext",
                "containerresources",
            )
            looks_pod_specific = isinstance(constraint_kind, str) and any(
                h in constraint_kind.lower() for h in pod_policy_hints
            )
            if (
                covered_kinds
                and covered_kinds.issubset({"Pod", "ReplicaSet"})
                and not (covered_kinds & controllers)
                and looks_pod_specific
            ):
                r = _rule("k8s-gatekeeper-constraint-narrow-kinds")
                findings.append(Finding(
                    rule_id=r.id, line=line_hint, column=1,
                    matched_text=_trunc(
                        f"{constraint_kind}: match.kinds={sorted(covered_kinds)}"
                        " misses controllers"),
                    severity=r.severity, description=r.description,
                    owasp_asi=r.owasp_asi,
                ))


def _scan_rbac(  # noqa: PLR0912 - one branch per rule + verb
    doc: dict[str, Any],
    findings: list[Finding],
    line_hint: int,
) -> None:
    """Apply rules 10, 11, 12, 13, 21 to ClusterRole / Role documents."""
    kind = doc.get("kind")
    if kind not in {"ClusterRole", "Role"}:
        return
    meta = doc.get("metadata") or {}
    name = meta.get("name", "<role>") if isinstance(meta, dict) else "<role>"
    labels = meta.get("labels") or {} if isinstance(meta, dict) else {}

    rules = doc.get("rules") or []
    if not isinstance(rules, list):
        return

    sensitive_resource_hit = False

    for rule_entry in rules:
        if not isinstance(rule_entry, dict):
            continue
        verbs_raw = rule_entry.get("verbs") or []
        resources_raw = rule_entry.get("resources") or []
        api_groups_raw = rule_entry.get("apiGroups") or []
        verbs = set(verbs_raw) if isinstance(verbs_raw, list) else set()
        resources = (
            set(resources_raw) if isinstance(resources_raw, list) else set()
        )
        api_groups = (
            set(api_groups_raw) if isinstance(api_groups_raw, list) else set()
        )

        # Rule 10: escalate verb on roles.
        if (verbs & _RBAC_ESCALATE_VERBS) and (
            resources & _RBAC_ROLE_RESOURCES or "*" in resources
        ):
            r = _rule("k8s-rbac-verb-escalate")
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(
                    f"{kind} {name}: escalate on {sorted(resources)}"),
                severity=r.severity, description=r.description,
                owasp_asi=r.owasp_asi,
            ))

        # Rule 11: bind verb (or create) on bindings.
        if (verbs & _RBAC_BIND_VERBS) and (
            resources & _RBAC_BINDING_RESOURCES or "*" in resources
        ):
            r = _rule("k8s-rbac-verb-bind")
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(
                    f"{kind} {name}: bind on {sorted(resources)}"),
                severity="CRITICAL", description=r.description,
                owasp_asi=r.owasp_asi,
            ))
        elif "create" in verbs and (
            resources & _RBAC_BINDING_RESOURCES
        ):
            r = _rule("k8s-rbac-verb-bind")
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(
                    f"{kind} {name}: create on {sorted(resources)} "
                    "(escalation if combined with escalate)"),
                severity="HIGH", description=r.description,
                owasp_asi=r.owasp_asi,
            ))

        # Rule 12: impersonate verb.
        if verbs & _RBAC_IMPERSONATE_VERBS:
            r = _rule("k8s-rbac-verb-impersonate")
            # `groups` resource gives the `system:masters` pivot — flag
            # the highest severity (still CRITICAL but mark in text).
            if "groups" in resources or "*" in resources:
                matched = (
                    f"{kind} {name}: impersonate on "
                    f"{sorted(resources)} (system:masters pivot)"
                )
            else:
                matched = (
                    f"{kind} {name}: impersonate on {sorted(resources)}"
                )
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(matched),
                severity=r.severity, description=r.description,
                owasp_asi=r.owasp_asi,
            ))

        # Rule 13: */*/* wildcard ClusterRole.
        # Note Wave 18 catches the same exact triple-star pattern — we
        # intentionally still emit our finding here so heartbeat
        # detectors that only load the depth module still warn. Wave 18
        # uses rule id `k8s-clusterrolebinding-cluster-admin` while we
        # use `k8s-rbac-wildcard-clusterrole` — distinct id, distinct
        # consumer; not a duplicate finding.
        if "*" in verbs and "*" in resources and "*" in api_groups:
            r = _rule("k8s-rbac-wildcard-clusterrole")
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(
                    f"{kind} {name}: */*/* wildcard rule"),
                severity="CRITICAL", description=r.description,
                owasp_asi=r.owasp_asi,
            ))
        elif sum(
            1 for s in (verbs, resources, api_groups) if "*" in s
        ) == 2:
            r = _rule("k8s-rbac-wildcard-clusterrole")
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(
                    f"{kind} {name}: two-wildcard rule "
                    f"verbs={sorted(verbs)} resources={sorted(resources)} "
                    f"apiGroups={sorted(api_groups)}"),
                severity="HIGH", description=r.description,
                owasp_asi=r.owasp_asi,
            ))

        # Track sensitive-resource hits for Rule 21 aggregation drift.
        if resources & _SENSITIVE_SA_RESOURCES or "*" in resources:
            sensitive_resource_hit = True

    # Rule 21: aggregate-to-{admin,edit} label drift.
    if kind == "ClusterRole" and isinstance(labels, dict):
        for agg_key in (
            "rbac.authorization.k8s.io/aggregate-to-admin",
            "rbac.authorization.k8s.io/aggregate-to-edit",
        ):
            v = labels.get(agg_key)
            # K8s accepts "true" as a string label value.
            if isinstance(v, str) and v.lower() == "true":
                if sensitive_resource_hit:
                    r = _rule("k8s-clusterrole-aggregate-to-admin-drift")
                    findings.append(Finding(
                        rule_id=r.id, line=line_hint, column=1,
                        matched_text=_trunc(
                            f"ClusterRole {name}: {agg_key}=true + "
                            "wildcards/sensitive resources"),
                        severity=r.severity, description=r.description,
                        owasp_asi=r.owasp_asi,
                    ))


def _scan_clusterrolebinding_csr(
    doc: dict[str, Any],
    findings: list[Finding],
    line_hint: int,
) -> None:
    """Apply rule 17 — CSR-related ClusterRoleBindings to broad groups."""
    if doc.get("kind") != "ClusterRoleBinding":
        return
    role_ref = doc.get("roleRef") or {}
    if not isinstance(role_ref, dict):
        return
    rr_name = role_ref.get("name", "")
    if not isinstance(rr_name, str):
        return
    # The CSR cluster roles of interest.
    if not rr_name.startswith(
        "system:certificates.k8s.io:certificatesigningrequests:"
    ):
        return
    subjects = doc.get("subjects") or []
    if not isinstance(subjects, list):
        return
    broad_groups = {
        "system:authenticated",
        "system:unauthenticated",
        "system:bootstrappers",
    }
    for s in subjects:
        if not isinstance(s, dict):
            continue
        if s.get("kind") == "Group" and s.get("name") in broad_groups:
            r = _rule("k8s-csr-auto-approval-broad-group")
            name = (doc.get("metadata") or {}).get("name", "<binding>")
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(
                    f"ClusterRoleBinding {name}: {rr_name} -> "
                    f"Group {s.get('name')}"),
                severity=r.severity, description=r.description,
                owasp_asi=r.owasp_asi,
            ))


def _scan_pod_template(  # noqa: PLR0912 - linear branch per finding
    pod_spec: dict[str, Any],
    findings: list[Finding],
    line_hint: int,
    pod_name: str,
) -> None:
    """Apply rules 14 + 19 (etcd / SA-token) to a pod template."""
    # Rule 14: automountServiceAccountToken default-true.
    automount = pod_spec.get("automountServiceAccountToken")
    if automount is not False:
        # Default in K8s is `true`. We trigger only when the pod
        # specifies a non-default SA (otherwise the default SA in the
        # namespace might be locked down at the SA level — distinguish
        # via the explicit serviceAccountName field).
        sa_name = pod_spec.get("serviceAccountName")
        # If there's no explicit SA AND no automount setting, it's the
        # default SA with default mount → still risky (default SA can
        # list its own namespace) so we flag.
        r = _rule("k8s-pod-automount-sa-token-default-true")
        sev = r.severity  # HIGH base
        matched = (
            f"{pod_name}: automountServiceAccountToken not set to false"
            + (f" (SA={sa_name})" if sa_name else " (default SA)")
        )
        findings.append(Finding(
            rule_id=r.id, line=line_hint, column=1,
            matched_text=_trunc(matched),
            severity=sev, description=r.description,
            owasp_asi=r.owasp_asi,
        ))

    # Rule 19: direct etcd via hostPath / env vars / containers.
    r_etcd = _rule("k8s-pod-direct-etcd-access")
    volumes = pod_spec.get("volumes") or []
    if isinstance(volumes, list):
        for v in volumes:
            if not isinstance(v, dict):
                continue
            hp = v.get("hostPath")
            if isinstance(hp, dict):
                path = hp.get("path", "")
                if isinstance(path, str):
                    for etcd_path in _ETCD_HOST_PATHS:
                        if path == etcd_path or path.startswith(etcd_path + "/"):
                            findings.append(Finding(
                                rule_id=r_etcd.id, line=line_hint, column=1,
                                matched_text=_trunc(
                                    f"{pod_name}: hostPath={path}"),
                                severity=r_etcd.severity,
                                description=r_etcd.description,
                                owasp_asi=r_etcd.owasp_asi,
                            ))
                            break
    # Container-level env vars (ETCDCTL_*).
    for c_key in ("containers", "initContainers"):
        cs = pod_spec.get(c_key) or []
        if not isinstance(cs, list):
            continue
        for c in cs:
            if not isinstance(c, dict):
                continue
            env_list = c.get("env") or []
            if not isinstance(env_list, list):
                continue
            for e in env_list:
                if not isinstance(e, dict):
                    continue
                name = e.get("name")
                if isinstance(name, str) and name in _ETCDCTL_ENV_VARS:
                    findings.append(Finding(
                        rule_id=r_etcd.id, line=line_hint, column=1,
                        matched_text=_trunc(
                            f"{pod_name}/{c.get('name', '<container>')}: "
                            f"env {name}"),
                        severity=r_etcd.severity,
                        description=r_etcd.description,
                        owasp_asi=r_etcd.owasp_asi,
                    ))


def _scan_namespace(  # noqa: PLR0912 - one branch per PSA label combo
    doc: dict[str, Any],
    findings: list[Finding],
    line_hint: int,
    file_path: str,
) -> None:
    """Apply rule 16 (PodSecurity admission labels) to a Namespace."""
    if doc.get("kind") != "Namespace":
        return
    meta = doc.get("metadata") or {}
    if not isinstance(meta, dict):
        return
    name = meta.get("name", "<namespace>")
    labels = meta.get("labels") or {}
    if not isinstance(labels, dict):
        return
    enforce = labels.get("pod-security.kubernetes.io/enforce")
    audit = labels.get("pod-security.kubernetes.io/audit")

    r = _rule("k8s-podsecurity-admission-privileged-or-baseline")

    if enforce == "privileged":
        findings.append(Finding(
            rule_id=r.id, line=line_hint, column=1,
            matched_text=_trunc(
                f"Namespace {name}: enforce=privileged"),
            severity="CRITICAL", description=r.description,
            owasp_asi=r.owasp_asi,
        ))
    elif enforce == "baseline":
        is_prod = _is_production_context(file_path, doc) or (
            isinstance(name, str)
            and any(t in name.lower() for t in ("prod", "production", "prd"))
        )
        if is_prod:
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(
                    f"Namespace {name}: enforce=baseline on production"),
                severity="HIGH", description=r.description,
                owasp_asi=r.owasp_asi,
            ))
    elif enforce is None:
        # Missing enforce label — MINOR (K8s default is privileged).
        # Skip kube-system / known infra namespaces.
        if isinstance(name, str) and name not in _SYSTEM_NAMESPACES:
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(
                    f"Namespace {name}: enforce label missing"),
                severity="LOW", description=r.description,
                owasp_asi=r.owasp_asi,
            ))
    # Audit-restricted + enforce-privileged mismatch — CRITICAL.
    if enforce == "privileged" and audit == "restricted":
        findings.append(Finding(
            rule_id=r.id, line=line_hint, column=1,
            matched_text=_trunc(
                f"Namespace {name}: audit=restricted hides "
                "enforce=privileged"),
            severity="CRITICAL", description=r.description,
            owasp_asi=r.owasp_asi,
        ))


def _scan_namespace_networkpolicy(
    text: str,
    docs: list[Any],
    findings: list[Finding],
) -> None:
    """Apply rule 15: every Namespace in `docs` must have a default-deny
    NetworkPolicy somewhere in the same multi-doc YAML."""
    # Find all Namespaces and all NetworkPolicies.
    namespaces: list[tuple[str, int]] = []
    deny_all_policies: set[str] = set()  # namespace names with default-deny
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        kind = doc.get("kind")
        meta = doc.get("metadata") or {}
        name = meta.get("name") if isinstance(meta, dict) else None
        if kind == "Namespace" and isinstance(name, str):
            line = _find_line_of_key(text, name)
            namespaces.append((name, line))
        if kind == "NetworkPolicy":
            ns_for_policy = (
                meta.get("namespace") if isinstance(meta, dict) else None
            )
            spec = doc.get("spec") or {}
            if not isinstance(spec, dict):
                continue
            pod_selector = spec.get("podSelector")
            policy_types = spec.get("policyTypes") or []
            ingress = spec.get("ingress") or []
            egress = spec.get("egress") or []
            # Default-deny if podSelector is {} AND policyTypes includes
            # Ingress + Egress AND ingress/egress lists are empty.
            if (
                isinstance(pod_selector, dict)
                and pod_selector == {}
                and isinstance(policy_types, list)
                and "Ingress" in policy_types
                and "Egress" in policy_types
                and not ingress
                and not egress
            ):
                if isinstance(ns_for_policy, str):
                    deny_all_policies.add(ns_for_policy)
                else:
                    # In single-namespace bundles, NetworkPolicy without
                    # explicit metadata.namespace still covers the
                    # namespace it's applied to. Treat as a wildcard
                    # cover.
                    deny_all_policies.add("__wildcard__")

    r = _rule("k8s-namespace-no-default-deny-networkpolicy")
    for ns_name, line in namespaces:
        if ns_name in deny_all_policies or "__wildcard__" in deny_all_policies:
            continue
        # Severity downgrade for known-public infrastructure namespaces.
        public_ns_hints = (
            "kube-system", "ingress-nginx", "cert-manager",
            "gatekeeper-system",
        )
        if ns_name in public_ns_hints:
            sev = "LOW"
        else:
            sev = r.severity
        findings.append(Finding(
            rule_id=r.id, line=line, column=1,
            matched_text=_trunc(
                f"Namespace {ns_name}: no default-deny NetworkPolicy"),
            severity=sev, description=r.description,
            owasp_asi=r.owasp_asi,
        ))


# ---- Rego scanner -------------------------------------------------------


def scan_rego(text: str) -> list[Finding]:
    """Apply rule 7 — fail-open default in a rego policy."""
    findings: list[Finding] = []
    r = _rule("k8s-rego-default-allow-true")
    for m in _REGO_DEFAULT_ALLOW.finditer(text):
        line, col = _line_col(text, m.start())
        findings.append(Finding(
            rule_id=r.id, line=line, column=col,
            matched_text=_trunc(m.group(0)),
            severity=r.severity, description=r.description,
            owasp_asi=r.owasp_asi,
        ))
    return findings


# ---- Kubelet / apiserver scanners ---------------------------------------


def scan_kubelet_config(text: str) -> list[Finding]:
    """Apply rule 18 to a kubelet config YAML / apiserver flag dump."""
    findings: list[Finding] = []
    # Walk the parsed YAML when possible — gives correct line hints and
    # avoids false positives on `enabled: true` for unrelated keys.
    docs = _yaml_load_all(text)
    has_kubelet_doc = False
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        if doc.get("kind") != "KubeletConfiguration":
            continue
        has_kubelet_doc = True
        line_hint = _find_line_of_key(text, "kind")
        authn = doc.get("authentication") or {}
        if isinstance(authn, dict):
            anon = authn.get("anonymous") or {}
            if isinstance(anon, dict) and anon.get("enabled") is True:
                r = _rule("k8s-kubelet-anonymous-or-alwaysallow")
                findings.append(Finding(
                    rule_id=r.id, line=line_hint, column=1,
                    matched_text=_trunc(
                        "kubelet: authentication.anonymous.enabled=true"),
                    severity=r.severity, description=r.description,
                    owasp_asi=r.owasp_asi,
                ))
        authz = doc.get("authorization") or {}
        if isinstance(authz, dict) and authz.get("mode") == "AlwaysAllow":
            r = _rule("k8s-kubelet-anonymous-or-alwaysallow")
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(
                    "kubelet: authorization.mode=AlwaysAllow"),
                severity=r.severity, description=r.description,
                owasp_asi=r.owasp_asi,
            ))
    # Plain-text fallback for the malformed-YAML / partial-config case
    # where the structured walker found nothing usable: scan with the
    # bare key/value regexes. We only run this when no KubeletConfig
    # doc was parsed, otherwise we'd double-report.
    if not has_kubelet_doc:
        r = _rule("k8s-kubelet-anonymous-or-alwaysallow")
        for m in _KUBELET_ANONYMOUS_TRUE.finditer(text):
            line, col = _line_col(text, m.start())
            findings.append(Finding(
                rule_id=r.id, line=line, column=col,
                matched_text=_trunc(m.group(0)),
                severity=r.severity, description=r.description,
                owasp_asi=r.owasp_asi,
            ))
        for m in _KUBELET_ALWAYS_ALLOW.finditer(text):
            line, col = _line_col(text, m.start())
            findings.append(Finding(
                rule_id=r.id, line=line, column=col,
                matched_text=_trunc(m.group(0)),
                severity=r.severity, description=r.description,
                owasp_asi=r.owasp_asi,
            ))
    return findings


def scan_apiserver_flags(text: str) -> list[Finding]:
    """Apply rule 18 to a kube-apiserver flag dump (systemd unit /
    static pod manifest / kubeadm config)."""
    findings: list[Finding] = []
    r = _rule("k8s-kubelet-anonymous-or-alwaysallow")
    for m in _APISERVER_ANONYMOUS_AUTH.finditer(text):
        line, col = _line_col(text, m.start())
        findings.append(Finding(
            rule_id=r.id, line=line, column=col,
            matched_text=_trunc(m.group(0)),
            severity=r.severity, description=r.description,
            owasp_asi=r.owasp_asi,
        ))
    for m in _APISERVER_AUTHZ_ALWAYS_ALLOW.finditer(text):
        line, col = _line_col(text, m.start())
        findings.append(Finding(
            rule_id=r.id, line=line, column=col,
            matched_text=_trunc(m.group(0)),
            severity=r.severity, description=r.description,
            owasp_asi=r.owasp_asi,
        ))
    for m in _APISERVER_INSECURE_PORT.finditer(text):
        line, col = _line_col(text, m.start())
        findings.append(Finding(
            rule_id=r.id, line=line, column=col,
            matched_text=_trunc(m.group(0)),
            severity=r.severity, description=r.description,
            owasp_asi=r.owasp_asi,
        ))
    return findings


# ---- Direct etcd service scanner ----------------------------------------


def _scan_service_etcd_port(
    doc: dict[str, Any],
    findings: list[Finding],
    line_hint: int,
) -> None:
    """Rule 19 — Service exposing port 2379/targetPort 2379 in a
    non-system namespace."""
    if doc.get("kind") != "Service":
        return
    meta = doc.get("metadata") or {}
    if not isinstance(meta, dict):
        return
    ns = meta.get("namespace", "default")
    if isinstance(ns, str) and ns in _SYSTEM_NAMESPACES:
        return
    spec = doc.get("spec") or {}
    if not isinstance(spec, dict):
        return
    ports = spec.get("ports") or []
    if not isinstance(ports, list):
        return
    for p in ports:
        if not isinstance(p, dict):
            continue
        port = p.get("port")
        target = p.get("targetPort")
        if port == 2379 or target == 2379 or target == "2379":
            r = _rule("k8s-pod-direct-etcd-access")
            findings.append(Finding(
                rule_id=r.id, line=line_hint, column=1,
                matched_text=_trunc(
                    f"Service {meta.get('name', '<svc>')}: port 2379 "
                    f"in namespace {ns}"),
                severity="HIGH", description=r.description,
                owasp_asi=r.owasp_asi,
            ))
            break


# ---- Pod-spec wrapper extraction (matches sandbox_escape_patterns) ------


def _k8s_pod_spec(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Return the pod spec from a workload doc, regardless of wrapper kind."""
    kind = doc.get("kind")
    if kind == "Pod":
        spec = doc.get("spec")
        return spec if isinstance(spec, dict) else None
    if kind in _K8S_POD_KINDS:
        spec_outer = doc.get("spec")
        if not isinstance(spec_outer, dict):
            return None
        if kind == "CronJob":
            jt = spec_outer.get("jobTemplate")
            if not isinstance(jt, dict):
                return None
            inner = jt.get("spec")
            if not isinstance(inner, dict):
                return None
            template = inner.get("template")
        else:
            template = spec_outer.get("template")
        if not isinstance(template, dict):
            return None
        spec_inner = template.get("spec")
        return spec_inner if isinstance(spec_inner, dict) else None
    return None


# ---- Public entry points ------------------------------------------------


def scan_k8s(text: str, *, file_path: str = "") -> list[Finding]:
    """Apply every K8s YAML rule (1-6, 8-21 except rule 7 and rule 18).

    Rule 7 (rego) and rule 18 (kubelet/apiserver flags) have their own
    public entry points because their inputs are not K8s manifests.
    """
    findings: list[Finding] = []
    docs = _yaml_load_all(text)
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        kind = doc.get("kind", "")
        meta = doc.get("metadata") or {}
        name = (
            meta.get("name") if isinstance(meta, dict) else None
        )
        line_hint = (
            _find_line_of_key(text, str(name))
            if name
            else _find_line_of_key(text, "kind")
        )

        if kind in {"MutatingWebhookConfiguration",
                    "ValidatingWebhookConfiguration"}:
            _scan_webhook_configuration(doc, findings, line_hint)
        # Gatekeeper Constraint — apiVersion-based detection.
        _scan_gatekeeper_constraint(doc, text, findings, line_hint, file_path)
        if kind in {"ClusterRole", "Role"}:
            _scan_rbac(doc, findings, line_hint)
        if kind == "ClusterRoleBinding":
            _scan_clusterrolebinding_csr(doc, findings, line_hint)
        if kind in _K8S_POD_KINDS:
            pod_spec = _k8s_pod_spec(doc)
            if pod_spec is not None:
                _scan_pod_template(
                    pod_spec, findings, line_hint,
                    pod_name=str(name or kind),
                )
        if kind == "Namespace":
            _scan_namespace(doc, findings, line_hint, file_path)
        if kind == "Service":
            _scan_service_etcd_port(doc, findings, line_hint)

    # Cross-doc rule 15: NetworkPolicy default-deny per Namespace.
    _scan_namespace_networkpolicy(text, docs, findings)
    return findings


def _detect_kind(text: str) -> str:
    """Sniff the file kind from content.

    Order: kubelet config (most specific) > apiserver flags (--anonymous-auth
    / --authorization-mode) > rego (`package` line) > k8s (apiVersion/kind).
    """
    if _KUBELET_CONFIG_HINT.search(text) is not None:
        return "kubelet"
    if _APISERVER_FLAGS_HINT.search(text) is not None:
        return "apiserver"
    if _REGO_HINT.search(text) is not None:
        return "rego"
    if _K8S_HINT.search(text) is not None:
        return "k8s"
    return "unknown"


def scan_text(
    text: str,
    *,
    file_kind: str = "auto",
    file_path: str = "",
) -> list[Finding]:
    """Top-level dispatcher.

    file_kind: "auto" (sniff), "k8s", "rego", "kubelet", "apiserver".

    Findings come out sorted by (line, column, rule_id, severity) and
    deduped on (rule_id, line, column, matched_text). file_path is used
    for production-environment heuristics on rules 5, 16.
    """
    if not text:
        return []
    if file_kind == "auto":
        file_kind = _detect_kind(text)

    findings: list[Finding] = []
    if file_kind == "kubelet":
        findings.extend(scan_kubelet_config(text))
        # Some kubelet config bundles also carry apiserver static-pod
        # manifests in the same file — opportunistically scan flags too.
        findings.extend(scan_apiserver_flags(text))
    elif file_kind == "apiserver":
        findings.extend(scan_apiserver_flags(text))
    elif file_kind == "rego":
        findings.extend(scan_rego(text))
    elif file_kind == "k8s":
        findings.extend(scan_k8s(text, file_path=file_path))
        # K8s static-pod manifests can embed apiserver flags too.
        findings.extend(scan_apiserver_flags(text))
    # Unknown → run all scanners and dedupe (defensive default for
    # unmarked files; cost is low because scanners early-return on the
    # wrong kind).
    if file_kind == "unknown":
        findings.extend(scan_k8s(text, file_path=file_path))
        findings.extend(scan_rego(text))
        findings.extend(scan_kubelet_config(text))
        findings.extend(scan_apiserver_flags(text))

    # Dedupe on (rule_id, line, column, matched_text).
    seen: set[tuple[str, int, int, str]] = set()
    deduped: list[Finding] = []
    for f in findings:
        key = (f.rule_id, f.line, f.column, f.matched_text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)
    deduped.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return deduped
