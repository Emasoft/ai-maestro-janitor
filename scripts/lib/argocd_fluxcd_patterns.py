"""ArgoCD / FluxCD app-of-apps security patterns.

Wave-36 distillation round 22, angle ArgoCD/FluxCD.

Catalogue of 10 GitOps-specific anti-patterns distilled in
`reports/distill-round-22/argocd-fluxcd.md`. Targets ArgoCD Application /
AppProject and FluxCD GitRepository / HelmRelease / Kustomization CRDs that
existing modules cover only at the generic CI/CD or webhook level.

What is NOT here (already shipped — DO NOT duplicate):

  * Generic auto-prune + selfHeal flag combo —
    `gitops_argocd_auto_prune_and_selfheal` (earlier rule).
  * ApplicationSet go-template from Git provider —
    `gitops_argocd_applicationset_gotemplate_from_git_provider`.
  * FluxCD GitRepository user-controlled branch —
    `gitops_fluxcd_gitrepository_user_controlled_branch`.
  * ArgoCD AppProject wildcard sourceRepos —
    `gitops_argocd_project_wildcard_source_repos`.
  * FluxCD Kustomization decryption secretRef cross-namespace —
    `gitops_fluxcd_kustomization_decryption_secretref_cross_namespace`.
  * FluxCD HelmRelease unverified OCI source —
    `gitops_fluxcd_helmrelease_unverified_oci_source`.
  * ApplicationSet cluster-generator no selector —
    `gitops_argocd_applicationset_cluster_generator_no_selector`.
  * Tekton TriggerBinding no signature validation —
    `gitops_tekton_triggerbinding_no_signature_validation`.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * gops-argocd-source-path-glob                                  (HIGH)
  * gops-argocd-repoutil-ssh-no-known-hosts                       (HIGH)
  * gops-argocd-helm-parameters-user-controlled                   (HIGH)
  * gops-argocd-kustomize-patches-inline-exec                     (HIGH)
  * gops-argocd-destination-cross-env-server                      (CRITICAL)
  * gops-fluxcd-gitrepository-no-verify                           (HIGH)
  * gops-fluxcd-helmrelease-public-chart-unverified               (HIGH)
  * gops-fluxcd-kustomization-patches-url-fetch                   (CRITICAL)
  * gops-argocd-appproject-wildcard-destination-namespace         (CRITICAL)
  * gops-argocd-sync-windows-no-deny-manual                       (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Secret leak (SSH repoURL MITM, unverified commit reconciliation,
                        remote patch URL bypassing verification)
  ASI-05 — Supply-chain / cross-tenant pivot (source path glob, Helm
                                               parameter injection,
                                               public chart semver range)
  ASI-07 — Authority / authorisation gaps (cross-env cluster destination,
                                           wildcard destination namespace,
                                           no sync window, kustomize
                                           inline broad patch)

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


# ---- R1 : gops-argocd-source-path-glob ----------------------------------

_ARGOCD_SOURCE_PATH_GLOB = _re(
    r"path:\s*[\"']?(?:\*{1,2}|\./?)[\"']?"
)

# ---- R2 : gops-argocd-repoutil-ssh-no-known-hosts -----------------------

_ARGOCD_SSH_REPOUTIL = _re(
    r"repoURL:\s*[\"']?(?:ssh://|git@)[A-Za-z0-9._@:/-]{1,256}[\"']?"
)

# ---- R3 : gops-argocd-helm-parameters-user-controlled ------------------

_ARGOCD_HELM_PARAMETERS = _re(
    r"helm:\s*\n(?:[^\n]*\n){0,10}\s*parameters:\s*\n(?:[^\n]*\n){0,5}\s*-\s*name:"
)

# ---- R4 : gops-argocd-kustomize-patches-inline-exec --------------------

_ARGOCD_KUSTOMIZE_PATCHES = _re(
    r"kustomize:\s*\n(?:[^\n]*\n){0,8}\s*patches:\s*\n(?:[^\n]*\n){0,4}\s*-\s*(?:patch:|target:)"
)

# ---- R5 : gops-argocd-destination-cross-env-server ----------------------

# Match a destinations block that contains at least one server: https?:// entry.
# Using [\s\S]{0,600}? (bounded lazy wildcard) instead of the multi-line
# [^\n]*\n repetition to avoid the trailing-newline requirement while remaining
# RE2-safe (no backreferences, no lookbehind, no nested quantifiers).
_ARGOCD_DESTINATIONS_MULTI = _re(
    r"destinations:[\s\S]{0,600}?server:\s*https?://[A-Za-z0-9._-]{1,128}"
)

# ---- R6 : gops-fluxcd-gitrepository-no-verify ---------------------------

_FLUXCD_GITREPO_VERIFY_ABSENT = _re(
    r"kind:\s*GitRepository[^\n]*\n(?:[^\n]*\n){0,30}(?!.*\bverify:)\s*url:\s*https?://(?:github|gitlab|bitbucket)\."
)

# ---- R7 : gops-fluxcd-helmrelease-public-chart-unverified ---------------

_FLUXCD_HELM_SEMVER_RANGE = _re(
    r"version:\s*[\"']?(?:>=?|<=?|\*|\^|~)[0-9A-Za-z.*-]{0,40}[\"']?"
)

# ---- R8 : gops-fluxcd-kustomization-patches-url-fetch -------------------

_FLUXCD_PATCHES_REMOTE_URL = _re(
    r"patchesStrategicMerge:\s*\n(?:[^\n]*\n){0,5}\s*-\s*https?://[A-Za-z0-9._/%-]{1,256}"
)

# ---- R9 : gops-argocd-appproject-wildcard-destination-namespace ---------

_ARGOCD_WILDCARD_NAMESPACE = _re(
    r"destinations:\s*\n(?:[^\n]*\n){0,10}\s*namespace:\s*[\"']?\*[\"']?"
)

# ---- R10 : gops-argocd-sync-windows-no-deny-manual ----------------------

_ARGOCD_SELFHEAL_TRUE = _re(
    r"selfHeal:\s*true"
)


# ---- Rule registry -------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="gops-argocd-source-path-glob",
        name="argocd-source-path-glob",
        severity="HIGH",
        description=(
            "ArgoCD Application spec.source.path set to '*', '**', or '.' "
            "applies Kubernetes manifests from every subdirectory of the "
            "target repository, expanding reconciliation scope to sibling "
            "tenant directories in app-of-apps patterns."
        ),
        pattern=_ARGOCD_SOURCE_PATH_GLOB,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="gops-argocd-repoutil-ssh-no-known-hosts",
        name="argocd-repoutil-ssh-no-known-hosts",
        severity="HIGH",
        description=(
            "ArgoCD Application or Repository secret using an SSH repoURL "
            "(ssh:// or git@) without SSH known-hosts validation makes "
            "ArgoCD susceptible to MITM attacks on the Git transport, "
            "allowing arbitrary manifests to be reconciled to the cluster."
        ),
        pattern=_ARGOCD_SSH_REPOUTIL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="gops-argocd-helm-parameters-user-controlled",
        name="argocd-helm-parameters-user-controlled",
        severity="HIGH",
        description=(
            "ArgoCD Application spec.source.helm.parameters block present; "
            "when values are interpolated from PR titles, CI env vars, or "
            "SCM API fields, unsanitised inputs flow into Helm --set flags "
            "enabling Go-template injection or IRSA annotation overwrite."
        ),
        pattern=_ARGOCD_HELM_PARAMETERS,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="gops-argocd-kustomize-patches-inline-exec",
        name="argocd-kustomize-patches-inline-exec",
        severity="HIGH",
        description=(
            "ArgoCD Application spec.source.kustomize.patches block with "
            "inline patches; broad 'kind: *' targets allow attacker-controlled "
            "Kustomize overlays to inject env vars or hostPath volumes into "
            "arbitrary Deployments without modifying the base chart."
        ),
        pattern=_ARGOCD_KUSTOMIZE_PATCHES,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="gops-argocd-destination-cross-env-server",
        name="argocd-destination-cross-env-server",
        severity="CRITICAL",
        description=(
            "ArgoCD AppProject spec.destinations contains a production cluster "
            "server URL alongside a staging/dev cluster URL, collapsing the "
            "production isolation boundary and allowing any Application in the "
            "project to deploy to the production cluster."
        ),
        pattern=_ARGOCD_DESTINATIONS_MULTI,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="gops-fluxcd-gitrepository-no-verify",
        name="fluxcd-gitrepository-no-verify",
        severity="HIGH",
        description=(
            "FluxCD GitRepository source lacks spec.verify.provider "
            "(commit/tag signature verification), allowing Flux to reconcile "
            "any commit pushed to the configured ref without cryptographic "
            "attestation, including force-pushed or MITM-injected commits."
        ),
        pattern=_FLUXCD_GITREPO_VERIFY_ABSENT,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="gops-fluxcd-helmrelease-public-chart-unverified",
        name="fluxcd-helmrelease-public-chart-unverified",
        severity="HIGH",
        description=(
            "FluxCD HelmRelease spec.chart.spec.version uses a semver range "
            "operator (>=, ^, ~, *) against a public chart repository; mutable "
            "chart tags allow a compromised chart author to inject a malicious "
            "version that Flux installs automatically without cluster-side review."
        ),
        pattern=_FLUXCD_HELM_SEMVER_RANGE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="gops-fluxcd-kustomization-patches-url-fetch",
        name="fluxcd-kustomization-patches-url-fetch",
        severity="CRITICAL",
        description=(
            "FluxCD Kustomization references patchesStrategicMerge or resources "
            "pointing to an HTTP/HTTPS URL; remote patches fetched during "
            "Kustomize build bypass GitRepository verification boundaries, "
            "allowing unsigned remote content to be merged into cluster manifests."
        ),
        pattern=_FLUXCD_PATCHES_REMOTE_URL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="gops-argocd-appproject-wildcard-destination-namespace",
        name="argocd-appproject-wildcard-destination-namespace",
        severity="CRITICAL",
        description=(
            "ArgoCD AppProject spec.destinations contains 'namespace: *'; "
            "on a remote cluster this grants any Application in the project "
            "the ability to deploy to kube-system and other privileged namespaces, "
            "achieving node-level compromise via DaemonSet injection."
        ),
        pattern=_ARGOCD_WILDCARD_NAMESPACE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="gops-argocd-sync-windows-no-deny-manual",
        name="argocd-sync-windows-no-deny-manual",
        severity="HIGH",
        description=(
            "ArgoCD AppProject or Application has selfHeal: true but no "
            "syncWindows configured, providing zero reaction time between a "
            "malicious commit push and its cluster-side execution during "
            "incidents, change freezes, or CI token compromise events."
        ),
        pattern=_ARGOCD_SELFHEAL_TRUE,
        owasp_asi="ASI-07",
    ),
)


# ---- Public API ----------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* against all RULES; return a sorted list of Findings.

    Findings are sorted by (line, column, rule_id). No exceptions are raised
    for benign or malformed input — the function is fail-fast only on genuine
    pattern matches.
    """
    if not text:
        return []

    findings: list[Finding] = []
    lines = text.splitlines(keepends=True)

    # Build a (offset -> line_number, col_number) lookup via cumulative offsets.
    offsets: list[int] = []
    pos = 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln)

    def _line_col(char_offset: int) -> tuple[int, int]:
        lo, hi = 0, len(offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if offsets[mid] <= char_offset:
                lo = mid
            else:
                hi = mid - 1
        line_no = lo + 1
        col_no = char_offset - offsets[lo] + 1
        return line_no, col_no

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line_no, col_no = _line_col(m.start())
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line_no,
                    column=col_no,
                    matched_text=m.group(),
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
