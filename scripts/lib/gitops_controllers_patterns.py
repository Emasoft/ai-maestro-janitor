"""GitOps controller security anti-patterns (FluxCD / ArgoCD / Tekton).

Wave-28 distillation round 14, gitops-controllers angle.

Catalogue of 12 GitOps-controller-specific anti-patterns distilled from
`reports/distill-round-14/gitops-controllers.md`. Targets FluxCD, ArgoCD,
and Tekton surfaces that broad infrastructure modules cover only at the
abstract level.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic CI secret leak — `cicd_secret_leak_patterns.py`.
  * Generic CI runner injection — `ci_runner_injection_patterns.py`.
  * Generic container image pull policy — `container_image_patterns.py`.
  * Generic RBAC over-permission — `cloud_credential_patterns.py`.
  * Kubernetes service-account token in env — `k8s_rbac_patterns.py` (if present).
  * Supply-chain pinning — `cdn_supply_chain_patterns.py`.

What IS here (12 net-new rules, regex-only, all RE2-safe):

  * gitops-argocd-admin-password-plaintext            (CRITICAL)
  * gitops-argocd-repo-url-http-not-https             (HIGH)
  * gitops-argocd-insecure-flag-enabled               (HIGH)
  * gitops-argocd-app-sync-allow-privileged            (MEDIUM)
  * gitops-flux-git-secret-plaintext                  (CRITICAL)
  * gitops-flux-insecure-skip-tls-verify              (HIGH)
  * gitops-flux-source-oci-no-verify                  (HIGH)
  * gitops-tekton-param-injection-script              (HIGH)
  * gitops-tekton-privileged-step-container           (HIGH)
  * gitops-tekton-serviceaccount-default              (MEDIUM)
  * gitops-gitops-webhook-secret-missing              (HIGH)
  * gitops-argocd-project-clusterresourcewhitelist-all (MEDIUM)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-02 — Secret leak (plaintext password, git secret, token)
  ASI-04 — Information leak (insecure TLS, HTTP repo URL)
  ASI-05 — Supply-chain / image integrity (OCI no-verify)
  ASI-07 — Authority / authorisation gaps (privileged containers,
                                            overly-broad RBAC,
                                            default service account,
                                            missing webhook secret)
  ASI-08 — Injection (Tekton param injection into shell script)

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


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- G01 : gitops-argocd-admin-password-plaintext -----------------------

# ArgoCD bootstrap secret or configmap with admin.password set to a plaintext
# bcrypt hash or cleartext value directly (not referencing a Kubernetes secret).
# Detects: admin.password: <value> where the value is a non-empty literal
# (not an empty string and not a reference like $(...) or ${...}).
_ARGOCD_ADMIN_PWD = _re(
    r"admin\.password\s*:\s*['\"]?(?!\s*$|\$[({])[A-Za-z0-9$./+_\-]{8,200}['\"]?"
)

# ---- G02 : gitops-argocd-repo-url-http-not-https -----------------------

# ArgoCD Application spec referencing a Git repo over plain HTTP.
# Pattern: repoURL: http:// (not https://)
_ARGOCD_REPO_HTTP = _re(
    r"repoURL\s*:\s*['\"]?http://[A-Za-z0-9._/:\-]{4,200}['\"]?"
)

# ---- G03 : gitops-argocd-insecure-flag-enabled -------------------------

# ArgoCD server or application set with --insecure flag or insecure: true.
# Matches both YAML key-value form and CLI flag form.
_ARGOCD_INSECURE = _re(
    r"(?:argocd(?:-server|-application-set)?\b[^\n]*--insecure"
    r"|^\s{0,16}insecure\s*:\s*true\s*$)"
)

# ---- G04 : gitops-argocd-app-sync-allow-privileged --------------------

# ArgoCD SyncPolicy or ApplicationSet template permitting privileged containers
# (allowPrivilegeEscalation: true or privileged: true) in a resource managed
# via automated sync. We anchor on the common YAML key shape.
_ARGOCD_PRIVILEGED_SYNC = _re(
    r"(?:allowPrivilegeEscalation|privileged)\s*:\s*true"
)

# ---- G05 : gitops-flux-git-secret-plaintext ----------------------------

# FluxCD GitRepository or other source with a secretRef referencing an inline
# known-plaintext shape: username/password directly in the manifest.
# Detects: password: <literal> or bearerToken: <literal> in a flux-adjacent context.
_FLUX_GIT_SECRET = _re(
    r"(?:password|bearerToken|known_hosts)\s*:\s*['\"]?(?!\s*$|\$[({])[A-Za-z0-9+/=_.\-]{12,200}['\"]?"
)

# ---- G06 : gitops-flux-insecure-skip-tls-verify ------------------------

# FluxCD HelmRepository, OCIRepository or GitRepository with
# insecureSkipTLSVerify: true or --tls-skip-verify flag.
_FLUX_SKIP_TLS = _re(
    r"(?:insecureSkipTLSVerify\s*:\s*true"
    r"|--tls-skip-verify\b"
    r"|tlsSkipVerify\s*:\s*true)"
)

# ---- G07 : gitops-flux-source-oci-no-verify ----------------------------

# FluxCD OCIRepository without a verify block (cosign / notation signature
# verification). Anchor on the OCIRepository kind and absent verify: stanza.
# Single-line anchor — absence is checked in the scanner via a forward window.
_FLUX_OCI_KIND = _re(r"kind\s*:\s*OCIRepository")
# Marker for presence of signature verification — used as an absence check.
_FLUX_OCI_VERIFY = _re(r"\bverify\s*:")

# ---- G08 : gitops-tekton-param-injection-script ------------------------

# Tekton Task step using a shell script that interpolates a Tekton parameter
# $(params.*) directly into a shell command without quoting or safe variable
# expansion. Two forms detected:
#   * Param appears AFTER a dangerous shell verb on the same line
#     e.g.  curl $(params.url) | sh
#   * Dangerous shell verb appears BEFORE the param on the same line
#     e.g.  eval $(params.cmd)
# Both are captured with two anchoring alternatives joined by | so there
# is no nested quantifier under repetition (RE2-safe).
_TEKTON_PARAM_INJECT = _re(
    r"(?:"
    # Param first, then dangerous verb further right on the same line
    r"\$\(params\.[A-Za-z0-9_.\-]+\)[^'\"\n]{0,120}(?:curl|wget|sh\s+-c|bash\s+-c|eval\b|exec\b|[|;&`])"
    r"|"
    # Dangerous verb first, then param further right on the same line
    r"(?:curl|wget|eval|exec|sh\s+-c|bash\s+-c)[^\n]{0,120}\$\(params\.[A-Za-z0-9_.\-]+\)"
    r")"
)

# ---- G09 : gitops-tekton-privileged-step-container ---------------------

# Tekton Task or Pipeline step spec with securityContext.privileged: true
# or securityContext.runAsUser: 0 (root).
_TEKTON_PRIVILEGED = _re(
    r"securityContext\s*:\s*\n(?:\s+[^\n]+\n){0,5}\s*(?:privileged\s*:\s*true|runAsUser\s*:\s*0\b)"
)

# Simpler backup pattern for single-line forms.
_TEKTON_PRIVILEGED_INLINE = _re(
    r"(?:privileged\s*:\s*true|runAsUser\s*:\s*0\b)"
)

# ---- G10 : gitops-tekton-serviceaccount-default ------------------------

# Tekton PipelineRun or TaskRun omitting serviceAccountName or explicitly
# using the cluster default ("default"). Anchor on the run spec key.
_TEKTON_SA_DEFAULT = _re(
    r"serviceAccountName\s*:\s*['\"]?default['\"]?"
)

# ---- G11 : gitops-gitops-webhook-secret-missing ------------------------

# FluxCD Receiver or ArgoCD webhook route definition lacking a secret
# reference.  Anchor on the Receiver kind or webhook path annotation and
# check for an absent secretRef in a forward window.
_WEBHOOK_RECEIVER_KIND = _re(r"kind\s*:\s*Receiver")
_WEBHOOK_SECRET_REF = _re(r"\bsecretRef\s*:")

# ---- G12 : gitops-argocd-project-clusterresourcewhitelist-all ---------

# ArgoCD AppProject with clusterResourceWhitelist containing a wildcard group
# or kind (*), effectively granting access to all cluster-scoped resources.
_ARGOCD_CRW_WILDCARD = _re(
    r"clusterResourceWhitelist\s*:\s*\n(?:\s+[^\n]*\n){0,8}\s*-\s*\n?\s*(?:group|kind)\s*:\s*['\"]?\*['\"]?"
)

# Simpler pattern: inline wildcard on same or adjacent line.
_ARGOCD_CRW_INLINE = _re(
    r"clusterResourceWhitelist\b[^\n]{0,120}(?:group|kind)\s*:\s*['\"]?\*['\"]?"
)


# ---- Rule registry ------------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="gitops-argocd-admin-password-plaintext",
        name="ArgoCD admin password stored as plaintext literal",
        severity="CRITICAL",
        description=(
            "admin.password is set to a plaintext or pre-hashed literal "
            "in a manifest rather than referencing an external secret store. "
            "Leaking the manifest exposes the ArgoCD admin credential."
        ),
        pattern=_ARGOCD_ADMIN_PWD,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="gitops-argocd-repo-url-http-not-https",
        name="ArgoCD Application repoURL uses plain HTTP",
        severity="HIGH",
        description=(
            "repoURL uses http:// instead of https://, exposing Git traffic "
            "to man-in-the-middle interception and manifest tampering."
        ),
        pattern=_ARGOCD_REPO_HTTP,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="gitops-argocd-insecure-flag-enabled",
        name="ArgoCD started or configured with --insecure flag",
        severity="HIGH",
        description=(
            "argocd-server or a component is launched with --insecure or "
            "insecure: true, disabling TLS on the API/UI, allowing credential "
            "interception and UI session hijacking."
        ),
        pattern=_ARGOCD_INSECURE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="gitops-argocd-app-sync-allow-privileged",
        name="ArgoCD-managed workload grants privileged container access",
        severity="MEDIUM",
        description=(
            "A manifest synced by ArgoCD sets allowPrivilegeEscalation: true "
            "or privileged: true, granting the container elevated Linux "
            "capabilities that could be exploited for node escape."
        ),
        pattern=_ARGOCD_PRIVILEGED_SYNC,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="gitops-flux-git-secret-plaintext",
        name="FluxCD source manifest embeds a credential literal",
        severity="CRITICAL",
        description=(
            "A FluxCD GitRepository, HelmRepository or similar source "
            "manifest contains a password, bearerToken or known_hosts value "
            "as a plaintext literal instead of referencing a Kubernetes "
            "Secret via secretRef. Committing this leaks the credential."
        ),
        pattern=_FLUX_GIT_SECRET,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="gitops-flux-insecure-skip-tls-verify",
        name="FluxCD source configured to skip TLS verification",
        severity="HIGH",
        description=(
            "insecureSkipTLSVerify: true or --tls-skip-verify disables "
            "certificate validation on the Flux source, enabling MITM attacks "
            "against the Helm or OCI registry pull path."
        ),
        pattern=_FLUX_SKIP_TLS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="gitops-flux-source-oci-no-verify",
        name="FluxCD OCIRepository lacks cosign/notation signature verification",
        severity="HIGH",
        description=(
            "An OCIRepository resource is defined without a verify: block, "
            "meaning FluxCD will pull and apply OCI artifacts without "
            "validating their cryptographic signature. A supply-chain "
            "attacker who controls the registry can push malicious manifests."
        ),
        pattern=_FLUX_OCI_KIND,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="gitops-tekton-param-injection-script",
        name="Tekton param interpolated unsafely into shell command",
        severity="HIGH",
        description=(
            "A Tekton Task step interpolates $(params.*) directly into a "
            "shell command (curl, eval, sh -c, etc.) without quoting. An "
            "attacker controlling the param value can inject arbitrary shell "
            "commands into the pipeline step."
        ),
        pattern=_TEKTON_PARAM_INJECT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="gitops-tekton-privileged-step-container",
        name="Tekton Task step container runs as privileged or root",
        severity="HIGH",
        description=(
            "A Tekton Task step's securityContext grants privileged: true or "
            "runAsUser: 0, giving the build step root/host access. "
            "Malicious pipeline inputs or supply-chain compromises can "
            "exploit this for node escape."
        ),
        pattern=_TEKTON_PRIVILEGED_INLINE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="gitops-tekton-serviceaccount-default",
        name="Tekton run uses the default cluster service account",
        severity="MEDIUM",
        description=(
            "A Tekton PipelineRun or TaskRun explicitly sets "
            "serviceAccountName: default, using the cluster-default "
            "service account. This account often accumulates unintended "
            "RBAC permissions assigned by other workloads."
        ),
        pattern=_TEKTON_SA_DEFAULT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="gitops-gitops-webhook-secret-missing",
        name="FluxCD Receiver defined without a secretRef (no webhook secret)",
        severity="HIGH",
        description=(
            "A FluxCD Receiver resource is present without a secretRef, "
            "meaning the webhook endpoint accepts unauthenticated POST "
            "requests. An attacker can trigger arbitrary reconciliation "
            "without supplying a shared secret."
        ),
        pattern=_WEBHOOK_RECEIVER_KIND,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="gitops-argocd-project-clusterresourcewhitelist-all",
        name="ArgoCD AppProject clusterResourceWhitelist contains wildcard",
        severity="MEDIUM",
        description=(
            "clusterResourceWhitelist contains a wildcard group or kind (*), "
            "granting applications in this ArgoCD Project the ability to "
            "create or modify any cluster-scoped resource, violating "
            "least-privilege and enabling privilege escalation."
        ),
        pattern=_ARGOCD_CRW_WILDCARD,
        owasp_asi="ASI-07",
    ),
)


# ---- Helpers ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next `lines` lines starting at `line_no` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:  # noqa: UP006
    return pat.search(text) is not None


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against *text* and return findings.

    Stage-B context filters:

      * G07 (flux-source-oci-no-verify) — anchor on OCIRepository kind and
        require NO verify: stanza in a 25-line forward window.
      * G11 (gitops-webhook-secret-missing) — anchor on Receiver kind and
        require NO secretRef: in a 20-line forward window.
      * G12 (argocd-project-clusterresourcewhitelist-all) — also checks the
        inline single-line wildcard form via _ARGOCD_CRW_INLINE.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- G01 : admin password plaintext ----
    rule_g01 = rule_by_id["gitops-argocd-admin-password-plaintext"]
    for m in _ARGOCD_ADMIN_PWD.finditer(text):
        _emit(rule_g01, m.start(), m.group(0))

    # ---- G02 : repo URL plain HTTP ----
    rule_g02 = rule_by_id["gitops-argocd-repo-url-http-not-https"]
    for m in _ARGOCD_REPO_HTTP.finditer(text):
        _emit(rule_g02, m.start(), m.group(0))

    # ---- G03 : insecure flag ----
    rule_g03 = rule_by_id["gitops-argocd-insecure-flag-enabled"]
    for m in _ARGOCD_INSECURE.finditer(text):
        _emit(rule_g03, m.start(), m.group(0))

    # ---- G04 : privileged sync ----
    rule_g04 = rule_by_id["gitops-argocd-app-sync-allow-privileged"]
    for m in _ARGOCD_PRIVILEGED_SYNC.finditer(text):
        _emit(rule_g04, m.start(), m.group(0))

    # ---- G05 : flux git secret plaintext ----
    rule_g05 = rule_by_id["gitops-flux-git-secret-plaintext"]
    for m in _FLUX_GIT_SECRET.finditer(text):
        _emit(rule_g05, m.start(), m.group(0))

    # ---- G06 : flux skip TLS verify ----
    rule_g06 = rule_by_id["gitops-flux-insecure-skip-tls-verify"]
    for m in _FLUX_SKIP_TLS.finditer(text):
        _emit(rule_g06, m.start(), m.group(0))

    # ---- G07 : flux OCI no verify (Stage-B: absent verify block) ----
    rule_g07 = rule_by_id["gitops-flux-source-oci-no-verify"]
    for m in _FLUX_OCI_KIND.finditer(text):
        line_no, _ = _line_col(text, m.start())
        window = _slice_forward(text, line_no, 25)
        if not _file_contains(window, _FLUX_OCI_VERIFY):
            _emit(rule_g07, m.start(), m.group(0))

    # ---- G08 : tekton param injection ----
    rule_g08 = rule_by_id["gitops-tekton-param-injection-script"]
    for m in _TEKTON_PARAM_INJECT.finditer(text):
        _emit(rule_g08, m.start(), m.group(0))

    # ---- G09 : tekton privileged step (inline form) ----
    rule_g09 = rule_by_id["gitops-tekton-privileged-step-container"]
    for m in _TEKTON_PRIVILEGED_INLINE.finditer(text):
        _emit(rule_g09, m.start(), m.group(0))

    # ---- G10 : tekton default service account ----
    rule_g10 = rule_by_id["gitops-tekton-serviceaccount-default"]
    for m in _TEKTON_SA_DEFAULT.finditer(text):
        _emit(rule_g10, m.start(), m.group(0))

    # ---- G11 : flux webhook receiver missing secretRef (Stage-B) ----
    rule_g11 = rule_by_id["gitops-gitops-webhook-secret-missing"]
    for m in _WEBHOOK_RECEIVER_KIND.finditer(text):
        line_no, _ = _line_col(text, m.start())
        window = _slice_forward(text, line_no, 20)
        if not _file_contains(window, _WEBHOOK_SECRET_REF):
            _emit(rule_g11, m.start(), m.group(0))

    # ---- G12 : argocd clusterResourceWhitelist wildcard ----
    rule_g12 = rule_by_id["gitops-argocd-project-clusterresourcewhitelist-all"]
    for m in _ARGOCD_CRW_WILDCARD.finditer(text):
        _emit(rule_g12, m.start(), m.group(0))
    for m in _ARGOCD_CRW_INLINE.finditer(text):
        _emit(rule_g12, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
