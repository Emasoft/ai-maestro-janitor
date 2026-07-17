"""Fleet GitHub-config audit — the pure classifier + the read-only gather (TRDD-157OH2D7).

WHY this exists: the per-session `branch-protection` detector only ever inspects the
CURRENT session's repo, so a DIFFERENT plugin's repo could sit unprotected (open to
stranger PRs/force-pushes) and never be seen — and nothing at all detected a
`required_linear_history` rule, which silently JAMS the many-agent merge workflow. This
module audits the WHOLE ai-maestro plugin fleet in ONE machine-wide daemon pass (issue #7:
fleet-scope work is the daemon's single-writer job, never N sessions), and the near-free
per-session `fleet-github-config` detector just surfaces the daemon's findings.

Two layers, cleanly split (mirrors fleet_recovery/fleet_inject — pure policy vs I/O):
  * `classify_repo(facts) -> list[Finding]` is PURE and total: no `gh`, no I/O, no env. It
    is the whole opinion of the audit and is exhaustively unit-testable.
  * `gather_repo_facts` / `audit_fleet` do the READ-ONLY `gh` probing and hand `classify_repo`
    a plain `RepoFacts`. Reuses branch_protection_lib's `viewer_is_admin`,
    `list_existing_rulesets`, `detect_default_branch`.

Never-nag-on-unverifiable (the existing branch-protection rule, preserved): a repo the
viewer cannot administer (can't fix it) or whose probes were indeterminate yields ZERO
findings — the audit only speaks when it can both prove the gap AND the human could act.
It NEVER mutates a repo; the on-demand `/janitor-github-config-fix` skill does that.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# The daemon writes findings here (under the global-state dir); the per-session
# `fleet-github-config` detector reads ONLY this file. One name, two consumers.
FINDINGS_FILENAME = "github-config-findings.json"

# The on-demand fix skill the surface line always points at (the user's hard
# requirement: the notification must carry the remedy).
FIX_SKILL = "/janitor-github-config-fix"

# branch_protection_lib lives in the same lib/ dir; import as a sibling. The caller
# (daemon / detector) puts scripts/lib on sys.path, matching every other lib module.
import branch_protection_lib as bpl  # noqa: E402

# The janitor's OWN ratified ruleset names. A `required_linear_history` rule sitting in
# one of THESE is fixed automatically by re-applying the (corrected) baseline, which PUTs
# the ruleset with the ratified rule set (linear-history excluded). Only linear-history in
# a NON-baseline (user-authored) ruleset needs the separate preserve-the-rest PUT below.
BASELINE_RULESET_NAMES = frozenset(
    {bpl.HISTORY_RULESET_NAME, bpl.PR_CHECKS_RULESET_NAME, bpl.TAG_PROTECT_RULESET_NAME}
)

# The finding codes, ordered by how loudly they matter in a summary line. UNPROTECTED
# and LINEAR_HISTORY are the two the user reported; the rest are the CI/review baseline.
FINDING_CODES = (
    "UNPROTECTED",         # no branch ruleset AND no classic protection → strangers can force-push
    "LINEAR_HISTORY",      # a ruleset carries required_linear_history → BLOCKS merge commits
    "NO_PR_REVIEW",        # protected, but no ruleset requires a pull request → merge without review
    "NO_REQUIRED_CHECKS",  # protected + CI exists, but no required_status_checks gate
    "NO_CI",               # no .github/workflows at all
    "NO_TAG_PROTECT",      # protected branch, but published release tags are mutable/deletable
)

# Human-readable one-liners keyed by code — used by the fix skill and the surface detector
# so the wording lives in ONE place.
FINDING_BLURB = {
    "UNPROTECTED": "no branch ruleset and no classic protection — anyone with write access "
    "can force-push, rewrite history, or delete the default branch",
    "LINEAR_HISTORY": "a ruleset requires linear history — this BLOCKS merge commits and jams "
    "the many-agent merge workflow (Claude cannot merge)",
    "NO_PR_REVIEW": "no ruleset requires a pull request — changes can be merged with no review",
    "NO_REQUIRED_CHECKS": "CI exists but no ruleset requires status checks — a red build can merge",
    "NO_CI": "no .github/workflows — the repo runs no CI at all",
    "NO_TAG_PROTECT": "release tags are unprotected — a leaked token could move/delete a "
    "published vX.Y.Z tag and re-point installers",
}


@dataclass(frozen=True)
class Finding:
    """One classified gap on one repo. `code` is a FINDING_CODES member (fixed vocab,
    never untrusted text); `detail` is a short human string for the drift line."""

    slug: str
    code: str
    detail: str


@dataclass(frozen=True)
class RepoFacts:
    """Everything `classify_repo` needs about ONE repo — all gathered READ-ONLY.

    Optional fields are None when the probe could NOT determine the answer (network/perm
    error), which the classifier treats as "cannot prove a gap" → stays silent. That is
    distinct from an empty list / False, which are definite negatives it CAN act on.
    """

    slug: str
    admin: bool | None = None            # None = couldn't determine viewer permission
    default_branch: str | None = None
    rulesets: list[dict] | None = None   # FULL per-ruleset detail dicts (with 'rules'); None = probe failed
    classic_protected: bool | None = None  # True=200, False=definitive 404, None=indeterminate
    has_workflows: bool | None = None    # whether .github/workflows has any workflow file


def _active_branch_rulesets(rulesets: list[dict]) -> list[dict]:
    return [
        rs for rs in rulesets
        if isinstance(rs, dict) and rs.get("target") == "branch" and rs.get("enforcement") == "active"
    ]


def _active_tag_rulesets(rulesets: list[dict]) -> list[dict]:
    return [
        rs for rs in rulesets
        if isinstance(rs, dict) and rs.get("target") == "tag" and rs.get("enforcement") == "active"
    ]


def _rule_types(ruleset: dict) -> set[str]:
    """The set of rule `type`s in one ruleset detail dict (empty if none/malformed)."""
    out: set[str] = set()
    for rule in ruleset.get("rules", []) or []:
        if isinstance(rule, dict):
            t = rule.get("type")
            if isinstance(t, str):
                out.add(t)
    return out


def classify_repo(facts: RepoFacts) -> list[Finding]:
    """PURE, total classifier: RepoFacts → the list of Findings for that repo.

    Silence rules (never-nag-on-unverifiable):
      * admin is False           → [] (the viewer cannot fix it — nagging is pure noise)
      * rulesets is None         → [] (we could not read the rulesets — cannot prove any gap)
    Everything else is a definite negative we can act on.
    """
    if facts.admin is False:
        return []
    if facts.rulesets is None:
        return []

    branch_rs = _active_branch_rulesets(facts.rulesets)
    tag_rs = _active_tag_rulesets(facts.rulesets)
    # The union of rule types across ALL active branch rulesets (protection is additive:
    # two rulesets each contributing one rule protect jointly).
    all_branch_rule_types: set[str] = set()
    for rs in branch_rs:
        all_branch_rule_types |= _rule_types(rs)

    has_branch_protection = bool(branch_rs) or facts.classic_protected is True
    findings: list[Finding] = []

    # 1) UNPROTECTED — only when BOTH negatives are DEFINITIVE (no active branch ruleset
    #    AND classic protection is a genuine 404). classic_protected=None → indeterminate,
    #    so we do NOT claim unprotected (mirrors the branch-protection detector exactly).
    if not branch_rs and facts.classic_protected is False:
        findings.append(Finding(facts.slug, "UNPROTECTED", FINDING_BLURB["UNPROTECTED"]))

    # 2) LINEAR_HISTORY — independent of everything else: if ANY active branch ruleset
    #    carries required_linear_history it jams merges even on an otherwise-fine repo.
    if "required_linear_history" in all_branch_rule_types:
        findings.append(Finding(facts.slug, "LINEAR_HISTORY", FINDING_BLURB["LINEAR_HISTORY"]))

    # The review / checks gaps are inferred from the RULE TYPES of the active branch
    # RULESETS, so they may only be claimed when protection is actually EXPRESSED as
    # rulesets (`branch_rs` non-empty). A repo protected ONLY by CLASSIC branch protection
    # has an empty rule-type set through no fault of its own — its `required_pull_request_
    # reviews` / `required_status_checks` live in the classic protection body, which this
    # audit does not read. Gating these on `has_branch_protection` (which classic
    # satisfies) therefore claimed a gap we cannot see, false-flagging a compliant
    # classic-protected repo — and /janitor-github-config-fix would then mutate it. That
    # breaks this module's own never-nag-on-unverifiable rule, so the gate is `branch_rs`:
    # we only reason about rules we can actually READ. (An UNPROTECTED repo has no
    # rulesets either, so it is silent here too — the headline finding subsumes it.)
    if branch_rs:
        if "pull_request" not in all_branch_rule_types:
            findings.append(Finding(facts.slug, "NO_PR_REVIEW", FINDING_BLURB["NO_PR_REVIEW"]))
        # NO_REQUIRED_CHECKS only when CI actually exists (has_workflows True); if there is
        # no CI at all that is the NO_CI finding below, not a missing gate.
        if facts.has_workflows is True and "required_status_checks" not in all_branch_rule_types:
            findings.append(
                Finding(facts.slug, "NO_REQUIRED_CHECKS", FINDING_BLURB["NO_REQUIRED_CHECKS"])
            )
    # Tag protection is orthogonal to the BRANCH mechanism (it is its own ruleset target),
    # and `rulesets is not None` means we definitively read the tag rulesets too — so this
    # one stays gated on "the repo is protected at all", classic included.
    if has_branch_protection and not tag_rs:
        findings.append(Finding(facts.slug, "NO_TAG_PROTECT", FINDING_BLURB["NO_TAG_PROTECT"]))

    # 3) NO_CI — independent of branch protection: a repo with no workflows runs no CI.
    #    Only when we DEFINITELY saw no workflows (has_workflows is False, not None).
    if facts.has_workflows is False:
        findings.append(Finding(facts.slug, "NO_CI", FINDING_BLURB["NO_CI"]))

    return findings


# ---- linear-history removal helpers (pure — the fix skill's core) --------

def nonbaseline_rulesets_with_linear_history(rulesets: list[dict]) -> list[dict]:
    """Every ACTIVE branch ruleset that (a) carries `required_linear_history` AND (b) is
    NOT one of the janitor's baseline rulesets — i.e. the ones the baseline re-apply will
    NOT fix, so the fix skill must PUT them itself (preserving their other rules). PURE."""
    out: list[dict] = []
    for rs in _active_branch_rulesets(rulesets):
        name = rs.get("name")
        if name in BASELINE_RULESET_NAMES:
            continue  # the baseline re-apply corrects these
        if "required_linear_history" in _rule_types(rs):
            out.append(rs)
    return out


def linear_history_present(slug: str, summary_rulesets: list[dict]) -> bool | None:
    """Given a repo's ALREADY-FETCHED ruleset SUMMARY list, resolve whether any active branch
    ruleset carries `required_linear_history`. Fetches per-ruleset DETAIL (the summary lacks
    the rules array) only for the active branch rulesets, so it adds no work when there are
    none. Returns:
      * True  — a definite linear-history rule was found (safe to alert),
      * False — every active branch ruleset was resolved and none carried it,
      * None  — indeterminate (a detail probe failed) → the caller must NOT claim.

    This lets the per-session branch-protection detector flag the merge-jam without adopting the
    full fleet classifier (which would change its established UNPROTECTED-only contract)."""
    active = _active_branch_rulesets(summary_rulesets)
    if not active:
        return False  # no active branch ruleset → no linear-history rule (UNPROTECTED covers it)
    indeterminate = False
    for rs in active:
        rid = rs.get("id")
        if not isinstance(rid, int):
            if "required_linear_history" in _rule_types(rs):
                return True
            indeterminate = True
            continue
        rc, detail = _gh_json(["api", f"repos/{slug}/rulesets/{rid}"])
        if rc == 0 and isinstance(detail, dict):
            if "required_linear_history" in _rule_types(detail):
                return True
        else:
            indeterminate = True
    return None if indeterminate else False


def strip_linear_history_payload(ruleset: dict) -> dict:
    """Build the GitHub 'Update ruleset' (PUT) body for `ruleset` with ONLY the
    `required_linear_history` rule removed — every other rule, the conditions, the
    bypass_actors and the enforcement are preserved verbatim. PURE + total.

    This is the merge-jam fix for a linear-history rule living in a USER's own ruleset:
    we do not delete their ruleset or touch their other protections, we drop exactly the
    one rule that blocks Claude's merges.
    """
    kept_rules = [
        r for r in (ruleset.get("rules") or [])
        if not (isinstance(r, dict) and r.get("type") == "required_linear_history")
    ]
    payload: dict = {
        "name": ruleset.get("name"),
        "target": ruleset.get("target", "branch"),
        "enforcement": ruleset.get("enforcement", "active"),
        "rules": kept_rules,
    }
    # Preserve conditions + bypass_actors when present (GitHub's PUT wants the full body).
    if isinstance(ruleset.get("conditions"), dict):
        payload["conditions"] = ruleset["conditions"]
    if isinstance(ruleset.get("bypass_actors"), list):
        payload["bypass_actors"] = ruleset["bypass_actors"]
    return payload


# ---- READ-ONLY gather (the I/O half) -------------------------------------

_REPO_SLUG_RE = re.compile(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?/?$")


def marketplace_catalog_path(plugins_root: Path) -> Path:
    """Where the ai-maestro-plugins marketplace catalog lives on disk."""
    return (
        plugins_root / "marketplaces" / "ai-maestro-plugins"
        / ".claude-plugin" / "marketplace.json"
    )


def fleet_repo_slugs(plugins_root: Path) -> list[str]:
    """Every ai-maestro plugin's `owner/repo` slug, parsed from the marketplace catalog's
    per-plugin `source.url`. Deduped, sorted, best-effort (a malformed entry is skipped).

    PURE over the catalog file — no network. Returns [] when the catalog is unreadable, so
    the caller degrades to "no fleet to audit" rather than crashing.
    """
    path = marketplace_catalog_path(plugins_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    slugs: set[str] = set()
    for entry in data.get("plugins", []):
        if not isinstance(entry, dict):
            continue
        source = entry.get("source")
        url = source.get("url") if isinstance(source, dict) else None
        if not isinstance(url, str):
            continue
        m = _REPO_SLUG_RE.search(url)
        if m:
            slugs.add(m.group(1))
    return sorted(slugs)


def _gh_json(args: list[str], *, timeout: float = 15.0):
    """Run `gh <args>` read-only → (returncode, parsed_json_or_None). None rc = gh missing
    or it raised (never propagates)."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["gh", *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    parsed = None
    if proc.stdout and proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            parsed = None
    return proc.returncode, parsed


def _full_rulesets(slug: str) -> list[dict] | None:
    """Every ruleset for `slug` WITH its `rules` array resolved.

    The list endpoint (`repos/{slug}/rulesets`) returns summaries WITHOUT the rules, so we
    fetch each ruleset's detail (`repos/{slug}/rulesets/{id}`) to see required_linear_history
    / pull_request / required_status_checks. Returns None if the list probe itself failed
    (indeterminate → the classifier stays silent); a per-ruleset detail failure drops just
    that ruleset (best-effort).
    """
    summaries = bpl.list_existing_rulesets(slug)
    if summaries is None:
        return None
    detailed: list[dict] = []
    for rs in summaries:
        if not isinstance(rs, dict):
            continue
        rid = rs.get("id")
        if not isinstance(rid, int):
            # No id to resolve detail — keep the summary (target/enforcement still usable).
            detailed.append(rs)
            continue
        rc, detail = _gh_json(["api", f"repos/{slug}/rulesets/{rid}"])
        detailed.append(detail if rc == 0 and isinstance(detail, dict) else rs)
    return detailed


def _has_workflows(slug: str) -> bool | None:
    """Whether `.github/workflows` contains any workflow file. None on an indeterminate
    probe (so NO_CI is only claimed when we DEFINITELY saw an empty/absent dir)."""
    rc, data = _gh_json(["api", f"repos/{slug}/contents/.github/workflows"])
    if rc is None:
        return None
    # A 404 (dir absent) comes back as a dict with status "404" → definitely no workflows.
    if isinstance(data, dict) and str(data.get("status")) == "404":
        return False
    if isinstance(data, list):
        return any(
            isinstance(f, dict) and str(f.get("name", "")).endswith((".yml", ".yaml"))
            for f in data
        )
    return None


def _classic_protected(slug: str, branch: str) -> bool | None:
    """Classic branch protection: True=200, False=definitive 404, None=indeterminate."""
    rc, body = _gh_json(["api", f"repos/{slug}/branches/{branch}/protection"])
    if rc is None:
        return None
    if rc == 0:
        return True
    if isinstance(body, dict) and str(body.get("status")) == "404":
        return False
    return None


def gather_repo_facts(slug: str) -> RepoFacts:
    """READ-ONLY probe of ONE repo into a RepoFacts. Never raises, never mutates."""
    admin = bpl.viewer_is_admin(slug)
    # If we are not admin we cannot fix the repo → the classifier will stay silent, so skip
    # the remaining probes (saves API calls on repos we could never act on anyway).
    if not admin:
        return RepoFacts(slug=slug, admin=False)
    branch = bpl.detect_default_branch(slug)
    rulesets = _full_rulesets(slug)
    classic = _classic_protected(slug, branch) if branch else None
    return RepoFacts(
        slug=slug,
        admin=True,
        default_branch=branch,
        rulesets=rulesets,
        classic_protected=classic,
        has_workflows=_has_workflows(slug),
    )


@dataclass
class FleetAudit:
    """The whole-fleet result the daemon serializes to JSON."""

    generated_at: int
    repos_scanned: int
    findings: list[Finding] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "repos_scanned": self.repos_scanned,
            "findings": [
                {"slug": f.slug, "code": f.code, "detail": f.detail} for f in self.findings
            ],
        }


def audit_fleet(plugins_root: Path, *, now: int) -> FleetAudit:
    """Probe every fleet repo READ-ONLY and classify. The daemon's single entry point."""
    slugs = fleet_repo_slugs(plugins_root)
    findings: list[Finding] = []
    for slug in slugs:
        findings.extend(classify_repo(gather_repo_facts(slug)))
    return FleetAudit(generated_at=now, repos_scanned=len(slugs), findings=findings)


# ---- surface helpers (pure, shared by the detector) ----------------------

# Short, drift-line-friendly labels per code (the blurbs are the fuller wording).
_SHORT = {
    "UNPROTECTED": "UNPROTECTED default branch (strangers can force-push/rewrite/delete)",
    "LINEAR_HISTORY": "required_linear_history (BLOCKS Claude's merges)",
    "NO_PR_REVIEW": "no required PR review",
    "NO_REQUIRED_CHECKS": "no required status checks",
    "NO_CI": "no CI workflows",
    "NO_TAG_PROTECT": "unprotected release tags",
}


def findings_digest(payload: object) -> str:
    """A stable 12-hex digest over the (slug, code) finding set — the dedupe key so an
    UNCHANGED finding set never re-nags, but ANY change (a repo fixed, a new gap) re-alerts.

    `payload` is typed `object` because it comes from `json.loads` of a file that could be
    malformed (a list, None, garbage) — the isinstance guard is a real runtime check."""
    findings = payload.get("findings", []) if isinstance(payload, dict) else []
    keys = sorted(
        f"{f.get('slug')}|{f.get('code')}" for f in findings if isinstance(f, dict)
    )
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()[:12]


# A well-formed `owner/repo` — the ONLY slug shape allowed into a drift line (it comes off
# a git remote URL, so it is untrusted text; the fullmatch doubles as the sanitizer).
_SLUG_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def payload_for_slug(payload: object, slug: str) -> dict:
    """The findings sub-payload for ONE repo — the ONLY view a per-session surface may
    consume. PURE. `payload` is untrusted JSON off disk (see findings_digest)."""
    findings = payload.get("findings", []) if isinstance(payload, dict) else []
    return {"findings": [f for f in findings if isinstance(f, dict) and f.get("slug") == slug]}


def summarize_for_slug(payload: object, slug: str) -> str | None:
    """Build THIS repo's one-line drift summary, or None when this repo is clean.

    REPLACES the fleet-aggregate `summarize` (user directive 2026-07-17): an
    automatically-surfaced line must speak ONLY about the project it appears in. A session
    in repo A receiving findings about repo B — even as counts — has the wrong skills, the
    wrong token budget, is FORBIDDEN from acting on another agent's workdir/repo, and
    becomes a data-exfiltration surface into projects with weaker protections. Fleet-wide
    views exist only on the HUMAN's explicit ask (`/janitor-github-config-fix --all`,
    `/janitor-show-global-status`) — never on the automatic per-session channel.

    PURE — unit-tested here so the wording never diverges. Always ends with the fix-skill
    pointer scoped to THIS slug (notify + carry the remedy, for this repo only).
    """
    if not slug or not _SLUG_RE.fullmatch(slug):
        return None  # unattributable or unsafe slug → surface NOTHING, never fleet data
    mine = payload_for_slug(payload, slug)["findings"]
    counts: dict[str, int] = {}
    for f in mine:
        code = f.get("code")
        if code in _SHORT:
            counts[code] = counts.get(code, 0) + 1
    if not counts:
        return None
    parts = [f"{counts[c]} {_SHORT[c]}" for c in FINDING_CODES if c in counts]
    return (
        f"[github-config] THIS repo ({slug}) has GitHub-config drift: "
        + "; ".join(parts)
        + f". → Run {FIX_SKILL} --slug {slug} to review + fix (shows a plan first; "
        "mutates the repo only on your confirmation, and only if you are an admin)."
    )
