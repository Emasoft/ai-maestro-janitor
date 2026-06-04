"""Kubernetes RBAC drift + ServiceAccount over-privilege patterns.

Wave-37 distillation round 23 — k8s/service-mesh group.

Orthogonal to `scripts/lib/k8s_admission_patterns.py`: that module walks
parsed YAML docs and already covers admission webhooks, Gatekeeper
constraints, the bare `escalate`/`bind`/`impersonate` verbs (rule-level),
ClusterRole `*/*/*` wildcards, PodSecurity admission labels, default-deny
NetworkPolicy, kubelet/apiserver flags, etcd hostPath/port-2379, CSR
auto-approval, and the SA-token automount default. The rules below are a
purely-regex, RE2-safe second-pass focused on RBAC *grant scope* and
ServiceAccount *binding* mistakes that AI-generated manifests routinely
emit — cross-namespace secret reads, `system:authenticated` bindings,
`pods/exec` grants, `cluster-admin` bindings to workload SAs, aggregation
label injection, and `automountServiceAccountToken: true`.

Reference proposal: `reports/distill-round-23/k8s-rbac-drift.md`.

Rule inventory (10 rules):

  1.  k8s-rbac-wildcard-clusterrole-grant        (HIGH)
  2.  k8s-rbac-bind-system-authenticated         (HIGH)
  3.  k8s-rbac-pods-exec-grant                    (HIGH)
  4.  k8s-rbac-cluster-secret-read               (HIGH)
  5.  k8s-rbac-automount-token-true              (MEDIUM)
  6.  k8s-rbac-aggregationrule-broad-selector    (MEDIUM)
  7.  k8s-rbac-escalate-or-bind-verb             (CRITICAL)
  8.  k8s-rbac-clusteradmin-binding              (CRITICAL)

Public surface mirrors `k8s_admission_patterns`:

  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — NamedTuple.
  * Rule(id, name, severity, description, owasp_asi) — NamedTuple.
  * RULES — ordered tuple of every rule.
  * scan_text(text, *, file_kind="auto", file_path="") -> list[Finding]
  * scan_k8s(text, *, file_path="") -> list[Finding]

OWASP ASI mapping:
  ASI-07 — Authority / authorisation gaps (every RBAC over-grant).
"""

from __future__ import annotations

import re
from typing import Callable, NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as
    `scripts/lib/k8s_admission_patterns.Finding` so heartbeat detectors
    render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """Static rule metadata. Patterns live alongside in module scope."""

    id: str
    name: str
    severity: str
    description: str
    owasp_asi: str


def _re(pattern: str) -> re.Pattern[str]:
    """Compile a pattern with IGNORECASE.

    RE2-safe: every quantifier is bounded, no backreferences, no
    lookaround. `(?s)` dot-all is applied inline per-pattern where a
    rule must span lines, so it is NOT forced module-wide here.
    """
    return re.compile(pattern, re.IGNORECASE)


# ---- Rule metadata ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="k8s-rbac-wildcard-clusterrole-grant",
        name="ClusterRole with wildcard resources + wildcard verbs",
        severity="HIGH",
        description=(
            "A ClusterRole granting resources: [\"*\"] and verbs: [\"*\"] "
            "confers cluster-admin equivalence. No legitimate non-admin "
            "ClusterRole needs both wildcards simultaneously."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-rbac-bind-system-authenticated",
        name="RoleBinding/ClusterRoleBinding to system:authenticated",
        severity="HIGH",
        description=(
            "Binding any role to system:authenticated grants it to every "
            "authenticated identity — including OIDC tokens and "
            "cross-namespace service accounts. Treat as effectively public."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-rbac-pods-exec-grant",
        name="pods/exec verb granted in a Role/ClusterRole",
        severity="HIGH",
        description=(
            "pods/exec lets the holder spawn an interactive shell in any "
            "pod within scope — arbitrary code execution on the node if "
            "the pod is not sandboxed."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-rbac-cluster-secret-read",
        name="ClusterRole reading secrets cluster-wide",
        severity="HIGH",
        description=(
            "A ClusterRole granting get/list/watch on secrets allows the "
            "holder to read every namespace's secrets — TLS keys, DB "
            "passwords, and ServiceAccount tokens."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-rbac-automount-token-true",
        name="automountServiceAccountToken: true",
        severity="MEDIUM",
        description=(
            "Explicitly mounting the SA token into a workload that needs "
            "no API access is a trivial lateral-move vector: any RCE in "
            "the container immediately gains a Kubernetes API credential."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-rbac-aggregationrule-broad-selector",
        name="Aggregated ClusterRole with clusterRoleSelectors",
        severity="MEDIUM",
        description=(
            "An aggregationRule merges rules from label-matched "
            "ClusterRoles. A broad selector lets an attacker who can "
            "create a labelled ClusterRole inject arbitrary rules into a "
            "high-privilege aggregate role."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-rbac-escalate-or-bind-verb",
        name="escalate / bind verb granted",
        severity="CRITICAL",
        description=(
            "escalate lets the holder grant themselves higher privileges "
            "than they hold; bind lets them create RoleBindings to "
            "powerful roles. Together a privilege-escalation primitive to "
            "cluster-admin. No application workload SA needs these."
        ),
        owasp_asi="ASI-07",
    ),
    Rule(
        id="k8s-rbac-clusteradmin-binding",
        name="ClusterRoleBinding to cluster-admin",
        severity="CRITICAL",
        description=(
            "Binding the built-in cluster-admin ClusterRole to a workload "
            "ServiceAccount or a non-operator user/group grants "
            "unrestricted API access — the most direct escalation."
        ),
        owasp_asi="ASI-07",
    ),
)


# ---- Regex constants (RE2-safe, bounded) --------------------------------


# Rule 1 — ClusterRole + wildcard resources + wildcard verbs (multi-line).
_WILDCARD_CLUSTERROLE = _re(
    r"(?s)kind:\s*ClusterRole\b.{0,600}?"
    r"resources:\s*\[[^\]]{0,200}\"?\*\"?[^\]]{0,200}\]"
    r".{0,300}?verbs:\s*\[[^\]]{0,200}\"?\*\"?[^\]]{0,200}\]"
)

# Rule 2 — Role/ClusterRoleBinding to system:authenticated.
_BIND_SYSTEM_AUTHENTICATED = _re(
    r"(?s)kind:\s*(?:Role|Cluster)RoleBinding\b.{0,600}?"
    r"subjects:.{0,400}?name:\s*system:authenticated\b"
)
# Also catch the matchLabels-free inline list-item subject form.
_SUBJECT_SYSTEM_AUTHENTICATED_INLINE = _re(
    r"name:\s*system:authenticated\b"
)

# Rule 3 — pods/exec verb. Catches both inline-array and list-item forms.
_PODS_EXEC = _re(
    r"\"?pods/exec\"?"
)

# Rule 4 — ClusterRole reading secrets cluster-wide (multi-line).
_CLUSTER_SECRET_READ = _re(
    r"(?s)kind:\s*ClusterRole\b.{0,600}?"
    r"resources:\s*\[[^\]]{0,200}\"?\s*secrets\s*\"?[^\]]{0,200}\]"
    r".{0,300}?verbs:\s*\[[^\]]{0,300}\"?\s*(?:get|list|watch)\s*\"?[^\]]{0,300}\]"
)

# Rule 5 — automountServiceAccountToken: true. `(?m)` so `^` anchors per
# line (the module `_re` does not force MULTILINE — it is set per-pattern).
_AUTOMOUNT_TOKEN_TRUE = _re(
    r"(?m)^\s*automountServiceAccountToken:\s*true\b"
)

# Rule 6 — aggregationRule with clusterRoleSelectors (multi-line).
_AGGREGATIONRULE_SELECTOR = _re(
    r"(?s)kind:\s*ClusterRole\b.{0,400}?"
    r"aggregationRule:\s*[\r\n\s]{0,40}clusterRoleSelectors:"
)

# Rule 7 — `escalate` / `bind` verb as a YAML list-item or array member.
# The trailing `(?:["\s,\]]|$)` is a *consumed* terminator (a char class
# OR end-of-string), NOT a lookahead — so this pattern is fully RE2-pure
# (no lookahead/lookbehind/backreference). It still rejects `escalated`
# / `binding` because those continue with a letter, not a terminator.
_ESCALATE_BIND_VERB = _re(
    r"(?:-\s*|\[\s*|,\s*)\"?(?:escalate|bind)\"?(?:[\"\s,\]]|$)"
)

# Rule 8 — ClusterRoleBinding whose roleRef.name is cluster-admin
# (multi-line; the subject kind anchors that it is a real binding).
_CLUSTERADMIN_BINDING = _re(
    r"(?s)kind:\s*ClusterRoleBinding\b.{0,400}?"
    r"roleRef:.{0,200}?name:\s*cluster-admin\b"
    r".{0,400}?subjects:.{0,300}?kind:\s*(?:ServiceAccount|User|Group)\b"
)

# YAML multi-doc separator — two-pass suppression checks (rules 4 & 8)
# must scope to the SINGLE document the anchor lives in, otherwise a
# `system:` subject / system ClusterRole name in a neighbouring doc would
# mask a real finding in another.
_DOC_SPLIT = re.compile(r"^---\s*$", re.MULTILINE)


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


def _rule(rule_id: str) -> Rule:
    """Lookup a Rule by id. Raises KeyError if missing (programmer error)."""
    for r in RULES:
        if r.id == rule_id:
            return r
    raise KeyError(rule_id)


def _emit(
    rule_id: str,
    text: str,
    match: re.Match[str],
    findings: list[Finding],
    *,
    severity: str | None = None,
    matched_text: str | None = None,
) -> None:
    """Append a Finding for `match` using `rule_id`'s metadata."""
    rule = _rule(rule_id)
    line, col = _line_col(text, match.start())
    findings.append(
        Finding(
            rule_id=rule_id,
            line=line,
            column=col,
            matched_text=_trunc(matched_text if matched_text is not None else match.group(0)),
            severity=severity or rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        )
    )


def _docs_with_offsets(text: str) -> list[tuple[int, str]]:
    """Split a multi-doc YAML stream into (absolute_offset, doc_text)."""
    docs: list[tuple[int, str]] = []
    last = 0
    for m in _DOC_SPLIT.finditer(text):
        docs.append((last, text[last : m.start()]))
        last = m.end()
    docs.append((last, text[last:]))
    return docs


def _doc_for_offset(text: str, offset: int) -> str:
    """Return the single YAML document containing `offset`."""
    for start, doc in _docs_with_offsets(text):
        if start <= offset < start + len(doc) + 1:
            return doc
    return text


def _is_system_subject_only(doc: str) -> bool:
    """True when every subject `name:` in the doc is system: prefixed.

    Used by rule 8: a cluster-admin binding to ONLY `system:` subjects
    (the built-in operator wiring) is the expected shape, not drift. The
    `cluster-admin` roleRef name and any inline-flow `{name: ...}`
    metadata are excluded — only real subject names matter.
    """
    names = re.findall(r"name:\s*(\S+)", doc)
    subject_names = [n.strip("'\"{},") for n in names]
    subject_names = [n for n in subject_names if n and n != "cluster-admin"]
    if not subject_names:
        return False
    return all(n.startswith("system:") for n in subject_names)


# ---- Scanners -----------------------------------------------------------


def _scan_simple(
    text: str,
    findings: list[Finding],
    rule_id: str,
    pattern: re.Pattern[str],
) -> None:
    """Emit one Finding per non-overlapping match of `pattern`."""
    for m in pattern.finditer(text):
        _emit(rule_id, text, m, findings)


def _scan_wildcard_clusterrole(text: str, findings: list[Finding]) -> None:
    """Rule 1 — ClusterRole with both resources:* and verbs:*."""
    _scan_simple(text, findings, "k8s-rbac-wildcard-clusterrole-grant", _WILDCARD_CLUSTERROLE)


def _scan_system_authenticated(text: str, findings: list[Finding]) -> None:
    """Rule 2 — binding to system:authenticated."""
    m = _BIND_SYSTEM_AUTHENTICATED.search(text)
    if m is not None:
        _emit("k8s-rbac-bind-system-authenticated", text, m, findings)
        return
    # Fallback: a bare subject name in a RoleBinding-shaped doc.
    if re.search(r"(?i)kind:\s*(?:Role|Cluster)RoleBinding\b", text):
        m2 = _SUBJECT_SYSTEM_AUTHENTICATED_INLINE.search(text)
        if m2 is not None:
            _emit("k8s-rbac-bind-system-authenticated", text, m2, findings)


def _scan_pods_exec(text: str, findings: list[Finding]) -> None:
    """Rule 3 — pods/exec only inside an RBAC rules: block."""
    # Only meaningful inside a Role/ClusterRole; avoids matching a
    # `kubectl exec` doc-string. Confirm a `verbs:` key precedes.
    if not re.search(r"(?i)kind:\s*(?:Cluster)?Role\b", text):
        return
    if not re.search(r"(?i)verbs:", text):
        return
    for m in _PODS_EXEC.finditer(text):
        _emit("k8s-rbac-pods-exec-grant", text, m, findings)


def _scan_cluster_secret_read(text: str, findings: list[Finding]) -> None:
    """Rule 4 — ClusterRole get/list/watch on secrets."""
    for m in _CLUSTER_SECRET_READ.finditer(text):
        # Suppress when the ClusterRole name is a system component: a
        # `system:` ClusterRole legitimately reads secrets cluster-wide.
        # Scope the name lookup to the document the match lives in (the
        # `name:` sits inside the match span, so a match-local search
        # is correct and a neighbouring doc cannot interfere).
        doc = _doc_for_offset(text, m.start())
        if re.search(r"(?i)name:\s*system:[^\s]+", doc):
            continue
        _emit("k8s-rbac-cluster-secret-read", text, m, findings)


def _scan_automount_token(text: str, findings: list[Finding]) -> None:
    """Rule 5 — automountServiceAccountToken: true."""
    _scan_simple(text, findings, "k8s-rbac-automount-token-true", _AUTOMOUNT_TOKEN_TRUE)


def _scan_aggregationrule(text: str, findings: list[Finding]) -> None:
    """Rule 6 — aggregationRule with clusterRoleSelectors."""
    _scan_simple(
        text, findings, "k8s-rbac-aggregationrule-broad-selector", _AGGREGATIONRULE_SELECTOR
    )


def _scan_escalate_bind(text: str, findings: list[Finding]) -> None:
    """Rule 7 — escalate / bind verb in an RBAC rules: block."""
    if not re.search(r"(?i)verbs:", text):
        return
    for m in _ESCALATE_BIND_VERB.finditer(text):
        _emit("k8s-rbac-escalate-or-bind-verb", text, m, findings)


def _scan_clusteradmin_binding(text: str, findings: list[Finding]) -> None:
    """Rule 8 — ClusterRoleBinding to cluster-admin for non-system subject."""
    for m in _CLUSTERADMIN_BINDING.finditer(text):
        # The regex match span ends at the subject `kind:`; the subject
        # `name:` comes AFTER it, so check the whole enclosing document.
        if _is_system_subject_only(_doc_for_offset(text, m.start())):
            continue
        _emit("k8s-rbac-clusteradmin-binding", text, m, findings)


_SCANNERS: tuple[Callable[[str, list[Finding]], None], ...] = (
    _scan_wildcard_clusterrole,
    _scan_system_authenticated,
    _scan_pods_exec,
    _scan_cluster_secret_read,
    _scan_automount_token,
    _scan_aggregationrule,
    _scan_escalate_bind,
    _scan_clusteradmin_binding,
)


def scan_k8s(text: str, *, file_path: str = "") -> list[Finding]:
    """Apply every RBAC rule to a K8s YAML manifest.

    `file_path` is accepted for signature parity with sibling modules;
    no rule currently uses it (RBAC drift is content-determined).
    """
    _ = file_path
    findings: list[Finding] = []
    for scan in _SCANNERS:
        scan(text, findings)
    return findings


def scan_text(
    text: str,
    *,
    file_kind: str = "auto",
    file_path: str = "",
) -> list[Finding]:
    """Top-level dispatcher.

    file_kind: "auto" (sniff) or "k8s". Findings come out sorted by
    (line, column, rule_id) and deduped on
    (rule_id, line, column, matched_text).
    """
    if not text:
        return []
    # Only one file_kind is meaningful (k8s YAML); "auto" resolves to it.
    _ = file_kind
    findings = scan_k8s(text, file_path=file_path)

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
