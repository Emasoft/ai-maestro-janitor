"""Crossplane composition + provider-trust security patterns.

Wave-37 distillation round 23, angle Crossplane.

Catalogue of 10 Crossplane-specific attack classes distilled in
`reports/distill-round-23/20260528_111104+0200-crossplane-composition.md`.
Targets Composition / CompositeResourceDefinition (XRD) / Configuration /
Provider / Function / DeploymentRuntimeConfig / ProviderConfig manifests and
the RBAC objects that bind provider ServiceAccounts.

The source proposal expresses several signals with negative lookahead /
lookbehind (`(?!...)`, `(?<!...)`) and notes those are NOT portable to RE2.
This module therefore rewrites every such signal as a RE2-safe candidate
regex plus a Python-level `absent` check ("block X that lacks token Y"), so
no rule relies on a lookaround. Multi-line YAML matching uses bounded
dot-all repetition (a fixed upper bound on the spanned characters) so the
match stays linear and ReDoS-safe on large manifests.

Rules (10 net-new attack classes; some carry two patterns):

  * xplane-compositetyperef-untrusted-group         (HIGH)
  * xplane-providerconfig-plain-secretref           (HIGH)
  * xplane-configuration-floating-tag               (HIGH)
  * xplane-function-deployment-admin-sa             (CRITICAL)
  * xplane-patch-fromcomposite-no-guardrail         (MEDIUM)
  * xplane-xrd-no-schema-validation                 (HIGH)
  * xplane-provider-sa-cluster-admin                (CRITICAL)
  * xplane-status-atprovider-credential-leak        (HIGH)
  * xplane-package-latest-image-auto-activation     (HIGH)
  * xplane-function-privileged-securitycontext      (CRITICAL)

Public surface mirrors `argocd_fluxcd_patterns`:

  * Rule(id, name, severity, description, pattern, owasp_asi, absent)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-03 — Injection / unvalidated input (FromCompositeFieldPath no guardrail,
                                          XRD no schema)
  ASI-05 — Supply-chain / cross-tenant pivot (untrusted compositeTypeRef
                                              group, floating Configuration
                                              tag, :latest image + auto
                                              activation)
  ASI-07 — Authority / authorisation gaps (admin SA function, provider SA
                                           cluster-admin, privileged function
                                           securityContext)
  ASI-02 — Secret leak (plain secretRef, status.atProvider credential leak)
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as argocd_fluxcd_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load.

    `pattern` matches a candidate region. `absent`, when set, is a second
    pattern: if it matches *inside* the candidate region the finding is
    suppressed — the RE2-safe replacement for the proposal's negative
    lookahead / lookbehind.
    """

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str
    absent: re.Pattern | None = None  # noqa: UP006


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with IGNORECASE+MULTILINE+UNICODE — RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind, no lookahead."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- R1 : xplane-compositetyperef-untrusted-group -----------------------

# compositeTypeRef whose group ends in a public TLD (candidate). The internal
# / org-controlled domains are filtered with `absent` rather than a negative
# lookahead.
_XPLANE_COMPOSITETYPEREF_GROUP = _re(
    r"compositeTypeRef:[\s\S]{0,120}?group:[ \t]+"
    r"[\w-]{1,63}(?:\.[\w-]{1,63})*\.(?:io|com|org|dev|cloud)\b"
)
_XPLANE_INTERNAL_GROUP = _re(r"group:[ \t]+(?:[\w-]+\.)*(?:internal|corp|example)\.")

# Configuration package pull with no digest pin (candidate). The match spans
# the whole package reference line so the `absent` digest check can see a
# trailing @sha256: pin (the candidate's [^\s@] body stops at the first @, so
# the [^\n]* tail is what brings the digest into the matched region).
_XPLANE_PACKAGE_UPBOUND = _re(
    r"package:[ \t]+(?:registry\.upbound\.io|xpkg\.upbound\.io)/[^\s@]{1,200}[^\n]*"
)
_XPLANE_SHA256_DIGEST = _re(r"@sha256:[0-9a-f]{64}")

# ---- R2 : xplane-providerconfig-plain-secretref -------------------------

_XPLANE_PROVIDERCONFIG_SECRETREF = _re(
    r"kind:[ \t]+ProviderConfig[\s\S]{0,400}?secretRef:[ \t]*\n[ \t]+name:[ \t]+\S+"
)

# ---- R3 : xplane-configuration-floating-tag -----------------------------

_XPLANE_CONFIGURATION_LATEST = _re(
    r"kind:[ \t]+Configuration[\s\S]{0,300}?package:[ \t]+[^@\s]{1,200}:latest"
)
# Any crossplane package (Configuration/Provider/Function) from a known
# registry (candidate); suppressed when a @sha256: digest pins it. The [^\n]*
# tail brings a trailing digest into the matched region for the absence check.
_XPLANE_PACKAGE_ANY_REGISTRY = _re(
    r"package:[ \t]+(?:registry\.upbound\.io|xpkg\.upbound\.io|ghcr\.io|docker\.io)"
    r"/[^\s@]{1,200}[^\n]*"
)

# ---- R4 : xplane-function-deployment-admin-sa ---------------------------

_XPLANE_FUNCTION_ADMIN_SA = _re(
    r"kind:[ \t]+(?:Function|DeploymentRuntimeConfig)[\s\S]{0,500}?"
    r"serviceAccountName:[ \t]+(?:default|admin|cluster-admin)\b"
)
# DeploymentRuntimeConfig with a containers spec (candidate); suppressed when
# automountServiceAccountToken: false is set somewhere in the block.
_XPLANE_DRC_CONTAINERS = _re(
    r"kind:[ \t]+DeploymentRuntimeConfig[\s\S]{0,600}?containers:"
)
_XPLANE_AUTOMOUNT_FALSE = _re(r"automountServiceAccountToken:[ \t]+false")

# ---- R5 : xplane-patch-fromcomposite-no-guardrail -----------------------

# A FromCompositeFieldPath patch with a fromFieldPath (candidate); suppressed
# when a transforms: or policy: guardrail appears in the patch entry.
_XPLANE_FROMCOMPOSITE_PATCH = _re(
    r"-[ \t]+type:[ \t]+FromCompositeFieldPath[ \t]*\n"
    r"[ \t]+fromFieldPath:[^\n]+(?:\n[ \t]+\S[^\n]*){0,6}"
)
_XPLANE_PATCH_GUARDRAIL = _re(r"(?:transforms:|policy:)")

# ---- R6 : xplane-xrd-no-schema-validation -------------------------------

# An XRD version entry marked served/referenceable (candidate); suppressed
# when a schema: subkey is present in the version entry.
_XPLANE_XRD_VERSION = _re(
    r"-[ \t]+name:[ \t]+v\d[\w.]*[ \t]*\n"
    r"(?:[ \t]+(?:referenceable|served):[ \t]+true[ \t]*\n)"
    r"(?:[ \t]+\S[^\n]*\n){0,10}"
)
_XPLANE_SCHEMA_KEY = _re(r"\bschema:")

# ---- R7 : xplane-provider-sa-cluster-admin ------------------------------

_XPLANE_PROVIDER_SA_CLUSTER_ADMIN = _re(
    r"roleRef:[ \t]*\n[ \t]+(?:apiGroup:[^\n]+\n[ \t]+)?(?:kind:[^\n]+\n[ \t]+)?"
    r"name:[ \t]+cluster-admin\b[\s\S]{0,300}?subjects:[\s\S]{0,300}?"
    r"name:[ \t]+(?:crossplane-provider|provider-)[\w-]+"
)

# ---- R8 : xplane-status-atprovider-credential-leak ----------------------

_XPLANE_STATUS_ATPROVIDER_LEAK = _re(
    r"type:[ \t]+ToCompositeFieldPath[ \t]*\n"
    r"[ \t]+fromFieldPath:[ \t]+status\.atProvider\."
)

# ---- R9 : xplane-package-latest-image-auto-activation -------------------

_XPLANE_PROVIDER_FUNCTION_LATEST_IMAGE = _re(
    r"image:[ \t]+[^\s:]{1,200}:latest\b"
)
_XPLANE_REVISION_AUTOMATIC = _re(
    r"revisionActivationPolicy:[ \t]+Automatic\b"
)

# ---- R10 : xplane-function-privileged-securitycontext -------------------

_XPLANE_PRIVILEGED_SECURITYCONTEXT = _re(
    r"(?:privileged:[ \t]+true|allowPrivilegeEscalation:[ \t]+true)"
)
# DeploymentRuntimeConfig containers spec (candidate); suppressed when both
# runAsNonRoot: true is present (hardened). seccompProfile alone is not enough
# but runAsNonRoot is the strongest single signal the proposal calls out.
_XPLANE_DRC_NO_RUNASNONROOT = _re(
    r"kind:[ \t]+DeploymentRuntimeConfig[\s\S]{0,800}?containers:"
)
_XPLANE_RUNASNONROOT_TRUE = _re(r"runAsNonRoot:[ \t]+true")


# ---- Rule registry -------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="xplane-compositetyperef-untrusted-group",
        name="xplane-compositetyperef-untrusted-group",
        severity="HIGH",
        description=(
            "A Composition compositeTypeRef points at an XRD whose group is a "
            "public/third-party domain (not internal/corp/example). If that XRD "
            "ships in an unpinned public Configuration package, an attacker who "
            "publishes a malicious XRD update redirects the composition to a "
            "schema that relaxes validation or exposes extra managed-resource "
            "fields."
        ),
        pattern=_XPLANE_COMPOSITETYPEREF_GROUP,
        owasp_asi="ASI-05",
        absent=_XPLANE_INTERNAL_GROUP,
    ),
    Rule(
        id="xplane-compositetyperef-untrusted-group",
        name="xplane-configuration-package-no-digest-upbound",
        severity="HIGH",
        description=(
            "A Configuration package pulled from the Upbound registry with no "
            "@sha256: digest pin; a registry-account compromise pushes a new "
            "image at the same tag and the next reconcile installs it."
        ),
        pattern=_XPLANE_PACKAGE_UPBOUND,
        owasp_asi="ASI-05",
        absent=_XPLANE_SHA256_DIGEST,
    ),
    Rule(
        id="xplane-providerconfig-plain-secretref",
        name="xplane-providerconfig-plain-secretref",
        severity="HIGH",
        description=(
            "A ProviderConfig pulls cloud credentials from a bare v1/Secret via "
            "secretRef with no External-Secrets / SOPS wrapper; any "
            "namespace-editor can `kubectl edit secret` the ref target and "
            "inject a rogue cloud account key."
        ),
        pattern=_XPLANE_PROVIDERCONFIG_SECRETREF,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="xplane-configuration-floating-tag",
        name="xplane-configuration-floating-tag",
        severity="HIGH",
        description=(
            "A Configuration spec.package uses a floating :latest tag; a "
            "compromised registry account pushes a malicious Configuration at "
            "the same tag and the next reconcile installs it cluster-wide."
        ),
        pattern=_XPLANE_CONFIGURATION_LATEST,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="xplane-configuration-floating-tag",
        name="xplane-package-any-registry-no-digest",
        severity="HIGH",
        description=(
            "A crossplane package (Configuration/Provider/Function) from a "
            "known registry with no @sha256: digest pin; mutable tags allow "
            "silent supply-chain substitution on re-pull."
        ),
        pattern=_XPLANE_PACKAGE_ANY_REGISTRY,
        owasp_asi="ASI-05",
        absent=_XPLANE_SHA256_DIGEST,
    ),
    Rule(
        id="xplane-function-deployment-admin-sa",
        name="xplane-function-deployment-admin-sa",
        severity="CRITICAL",
        description=(
            "A Composition Function rendered as a Deployment binds to a "
            "default/admin/cluster-admin ServiceAccount; a malicious or "
            "compromised function then inherits full cluster access through the "
            "SA's RBAC."
        ),
        pattern=_XPLANE_FUNCTION_ADMIN_SA,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="xplane-function-deployment-admin-sa",
        name="xplane-function-deployment-automount-token",
        severity="CRITICAL",
        description=(
            "A DeploymentRuntimeConfig containers spec without "
            "automountServiceAccountToken: false mounts the SA token into the "
            "function pod, giving a compromised function an API-server "
            "credential to escalate with."
        ),
        pattern=_XPLANE_DRC_CONTAINERS,
        owasp_asi="ASI-07",
        absent=_XPLANE_AUTOMOUNT_FALSE,
    ),
    Rule(
        id="xplane-patch-fromcomposite-no-guardrail",
        name="xplane-patch-fromcomposite-no-guardrail",
        severity="MEDIUM",
        description=(
            "A FromCompositeFieldPath patch copies a user-supplied claim field "
            "directly into a managed-resource spec with no transforms or "
            "policy.fromFieldPath: Required guardrail; null/malformed values "
            "propagate silently, or a claim-editor injects arbitrary strings "
            "into cloud API calls (IAM ARN, bucket name, VPC CIDR)."
        ),
        pattern=_XPLANE_FROMCOMPOSITE_PATCH,
        owasp_asi="ASI-03",
        absent=_XPLANE_PATCH_GUARDRAIL,
    ),
    Rule(
        id="xplane-xrd-no-schema-validation",
        name="xplane-xrd-no-schema-validation",
        severity="HIGH",
        description=(
            "A served/referenceable XRD version has no OpenAPI schema subkey; "
            "any field value passes validation and unvalidated user input flows "
            "through downstream Compositions into managed-resource specs."
        ),
        pattern=_XPLANE_XRD_VERSION,
        owasp_asi="ASI-03",
        absent=_XPLANE_SCHEMA_KEY,
    ),
    Rule(
        id="xplane-provider-sa-cluster-admin",
        name="xplane-provider-sa-cluster-admin",
        severity="CRITICAL",
        description=(
            "A ClusterRoleBinding grants cluster-admin to a crossplane provider "
            "ServiceAccount; every managed resource the provider reconciles can "
            "then read/write arbitrary cluster state — other Secrets, CRDs, and "
            "RBAC objects included."
        ),
        pattern=_XPLANE_PROVIDER_SA_CLUSTER_ADMIN,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="xplane-status-atprovider-credential-leak",
        name="xplane-status-atprovider-credential-leak",
        severity="HIGH",
        description=(
            "A ToCompositeFieldPath patch sources from status.atProvider, where "
            "some providers write back sensitive fields (access keys, "
            "passwords, certificates); patching those into the composite's "
            "status leaks credentials to any principal with `get` on the XR."
        ),
        pattern=_XPLANE_STATUS_ATPROVIDER_LEAK,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="xplane-package-latest-image-auto-activation",
        name="xplane-package-latest-image",
        severity="HIGH",
        description=(
            "A Provider/Function image field uses a floating :latest tag; "
            "combined with revisionActivationPolicy: Automatic a new (possibly "
            "malicious) image rolls out on re-pull with no operator review."
        ),
        pattern=_XPLANE_PROVIDER_FUNCTION_LATEST_IMAGE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="xplane-package-latest-image-auto-activation",
        name="xplane-revision-activation-automatic",
        severity="HIGH",
        description=(
            "revisionActivationPolicy: Automatic auto-installs any new package "
            "revision without operator review; paired with a mutable image tag "
            "it is a silent-rollout attack surface."
        ),
        pattern=_XPLANE_REVISION_AUTOMATIC,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="xplane-function-privileged-securitycontext",
        name="xplane-function-privileged-securitycontext",
        severity="CRITICAL",
        description=(
            "privileged: true or allowPrivilegeEscalation: true in a Function "
            "Deployment container securityContext lets the function escape the "
            "container boundary and reach node-level credentials — cloud IMDS "
            "tokens and kubelet certificates."
        ),
        pattern=_XPLANE_PRIVILEGED_SECURITYCONTEXT,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="xplane-function-privileged-securitycontext",
        name="xplane-function-no-runasnonroot",
        severity="CRITICAL",
        description=(
            "A DeploymentRuntimeConfig containers spec without runAsNonRoot: "
            "true runs the function as root, a precondition for the container "
            "escape and node-credential theft the privileged-securityContext "
            "rule targets."
        ),
        pattern=_XPLANE_DRC_NO_RUNASNONROOT,
        owasp_asi="ASI-07",
        absent=_XPLANE_RUNASNONROOT_TRUE,
    ),
)


# ---- Public API ----------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* against all RULES; return a sorted list of Findings.

    Findings are sorted by (line, column, rule_id). For rules carrying an
    `absent` pattern, a candidate match is dropped when the `absent` pattern
    also matches inside the matched region (the RE2-safe analogue of a
    negative lookahead / lookbehind). No exceptions are raised for benign or
    malformed input.
    """
    if not text:
        return []

    findings: list[Finding] = []
    lines = text.splitlines(keepends=True)

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
            if rule.absent is not None and rule.absent.search(m.group()):
                continue
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
