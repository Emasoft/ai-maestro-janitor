"""Branch-protection ruleset helpers — shared between the Tier 1 user-invoked
skill (`/janitor-branch-protection-setup`) and the Tier 2 guarded auto path
(`scripts/guard/branch_protection_apply.py`).

Per TRDD-631fa3de §10 + the ratified unified baseline
(janitor #14 / maintainer #7):

* The baseline is the SAME pair of rulesets in both surfaces. Single
  source of truth here, byte-identical with the maintainer plugin.
* All `gh` calls use a fixed argv (no shell). Failures surface verbatim,
  no half-apply.
* Refuses on non-default branch, non-admin viewer, missing repo.
* Idempotent-by-name: callers PATCH a ruleset whose name already exists,
  else POST a new one.

## The ratified two-ruleset baseline

Both `target: branch`, `enforcement: active`, condition
`ref_name.include: ["~DEFAULT_BRANCH"]` (the GitHub magic ref that
resolves to whatever branch the repo declares as default at apply
time — NOT `refs/heads/<name>`; this is what makes the JSON byte-
identical and portable across repos that use main/master/custom):

1. ``baseline-history-protect`` — ``bypass_actors`` grants the repo-admin
   role (``actor_id: 5``) an ``always`` bypass, per the USER's Tier-3
   ruling of 2026-08-13 allowing the OWNER to mutate history (amend,
   rebase, force-push) on their own repos. NON-admins are still refused
   ``deletion`` and ``non_fast_forward``, which is what makes this a
   baseline rather than its removal. Rules: ``deletion``,
   ``non_fast_forward``.
   DELIBERATELY NOT ``required_linear_history`` — it forbids merge commits
   and jams the many-agent merge workflow (see the rules block below for
   the full rationale); deletion + non_fast_forward are the genuine
   protection, linear history is a harmful workflow opinion.
2. ``baseline-pr-and-checks`` — ``bypass_actors`` grants the repo-admin
   role (``actor_id: 5``) an ``always`` bypass so a solo admin is not
   locked out of their own repo by the self-approval requirement.
   Rules: ``pull_request`` (**0** approvals, dismiss-stale, thread-
   resolution — GitHub forbids self-approval, so on a solo-owner repo any
   non-zero count is UNSATISFIABLE and makes an agent-opened PR
   permanently unmergeable; raise it per-repo if a repo genuinely has two
   humans, never in the fleet baseline)
   + ``required_status_checks`` (strict policy; CI check contexts are
   AUTO-DETECTED at apply time — see ``detect_required_status_checks``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import state as _state  # sibling in scripts/lib/ — the SSOT for the subprocess-timeout scale


def _t(seconds: float) -> float:
    """`seconds` scaled by the shared subprocess-timeout knob — 1.0 in production.

    TRDD-7NSRD8OV. Every `gh` call below is a DIRECT `subprocess.run` with its own ceiling, so
    scaling `state.run_subprocess` never reached them. Each one fails soft (a None/empty result
    the caller treats as "could not determine"), so under suite load the apply script ran to
    completion and printed NOTHING — surfacing as `assert '[guard] applied …' in ''`, which reads
    as a guard that did not fire rather than as a `gh` call that never answered. Measured: 18
    such failures across two 2x-oversubscribed runs.
    """
    return seconds * _state.timeout_scale()

# NOTE (TRDD-157OH2D7): `yaml` is imported LAZILY inside detect_required_status_checks (the ONLY
# function that parses workflow YAML), NOT at module top. This lets lightweight importers of this
# module — the `uv run --script` detectors branch-protection.py and fleet-github-config.py, which
# reach it transitively via github_config_audit and never call detect_required_status_checks —
# load it WITHOUT declaring pyyaml in their PEP-723 headers. The heavier callers that DO parse
# workflows (github_config_fix.py, the daemon, the setup/guard paths) run in an env where pyyaml
# is available (declared in their headers / the project deps).

# The two ratified ruleset names. Recognised by exact name match so the
# idempotent-apply logic in branch_protection_apply.py PATCHes the right
# ruleset instead of POSTing a duplicate, and so we don't clobber
# user-authored rulesets sitting alongside ours.
HISTORY_RULESET_NAME = "baseline-history-protect"
PR_CHECKS_RULESET_NAME = "baseline-pr-and-checks"
# The ratified THIRD baseline ruleset (tri-party consensus closed on janitor#14,
# USER-ratified Tier-3 2026-06-05). Tag protection: closes the supply-chain gap
# where a leaked token / accident could DELETE or MOVE a published release tag and
# re-point installers at arbitrary code — a threat a post-hoc CI gate can't catch
# (a tag moved onto a commit that itself passes CI). Byte-identical with the
# maintainer plugin's `workflow-protect-branch` 3rd payload (maintainer#7).
TAG_PROTECT_RULESET_NAME = "baseline-tag-protect"

# Every pre-ratification ruleset name in the COMBINED lineage of BOTH the janitor
# and the maintainer-agent plugins — the shared orphan-delete UNION agreed on
# janitor#14 / maintainer#7. The apply path deletes ALL of these by EXACT NAME once
# the ratified baseline-* pair is confirmed in place, so a repo either plugin ever
# touched converges to EXACTLY {baseline-history-protect, baseline-pr-and-checks}
# with no straggler left behind. Name-based ONLY — we NEVER delete a ruleset we did
# not create (that would nuke an owner's own custom ruleset). This list MUST stay
# byte-identical to the maintainer plugin's union so whichever applies last fully
# converges the repo.
LEGACY_RULESET_NAMES: tuple[str, ...] = (
    # janitor lineage
    "janitor-baseline",                  # janitor v0.5.x single ruleset
    "main-hardening",                    # janitor live split-pair (manual, pre-rename)
    "main-ci-gate",                      # janitor live split-pair (manual, pre-rename)
    # maintainer-agent lineage (workflow-protect-branch, pre-ratification)
    "default-branch-ruleset",
    "default-branch-no-force-no-delete",
    "default-branch-required-checks",
)
# Back-compat alias: some callers/tests import the singular legacy name.
LEGACY_RULESET_NAME = LEGACY_RULESET_NAMES[0]

# The GitHub magic ref that resolves to the repo's default branch at apply
# time. Using this (instead of refs/heads/<name>) keeps the payload byte-
# identical to the maintainer plugin and portable across default-branch
# names — the ratified spec mandates it.
_DEFAULT_BRANCH_REF = "~DEFAULT_BRANCH"

# The repo-admin RepositoryRole id. GitHub assigns stable numeric ids to
# the built-in roles; 5 == admin. Granted an `always` bypass on the
# PR/checks ruleset so a solo admin can still merge their own work.
_ADMIN_REPOSITORY_ROLE_ID = 5

# The tag-protection ref pattern. `refs/tags/v*.*.*` is the REST-canonical form for a
# `target: tag` ruleset's ref_name.include; per the cross-plugin agreement the exact
# GitHub-accepted literal is READBACK-PINNED on first real apply (same defence-in-depth
# as actor_id:5) — if GitHub normalises or rejects this spelling, reconcile to the
# echoed form, byte-identical with the maintainer, before either plugin calls it done.
_TAG_PROTECT_REF = "refs/tags/v*.*.*"


def prrd_pull_request_requirement(slug: str | None) -> bool | None:
    """The repo's OWN governance: `require-pull-request:` in its PRRD frontmatter.

    `None` means the repo has not stated a requirement — NOT "no". Only an explicit
    `true`/`false` is an answer, because "absent" and "false" have to stay distinguishable
    for the caller's fallback to mean anything.

    Read from the repo ITSELF, over the network for a foreign slug, because that is the
    whole point (TRDD-R4XC8MV1): `design/` is project-scoped and public, one repo per
    project, so the repo is the single source every applier can agree on. A predicate
    derived from the CALLING PROCESS instead is what let the janitor and the hub compute
    different verdicts for the same repo and flip-flop its ruleset.

    Fails soft to `None` on every error — no `gh`, no network, no file, unparseable
    frontmatter. A governance question we could not ask is not a governance answer.
    """
    if not slug:
        return None
    text: str | None = None
    # The local checkout first: no network, and it is the common case (a repo applying its
    # own baseline). Only trust it when the slug really is THIS repo, or a fleet audit would
    # read one project's governance for another's.
    try:
        import state as _st  # noqa: PLC0415 -- local, same reason as the imports below

        local = _st.project_root() / "design" / "requirements" / "PRRD.md"
        if local.is_file() and slug.split("/")[-1] == _st.project_root().name:
            text = local.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 -- a local-read fault must fall through to the network
        text = None
    if text is None and gh_available():
        try:
            proc = subprocess.run(
                ["gh", "api", f"repos/{slug}/contents/design/requirements/PRRD.md",
                 "-H", "Accept: application/vnd.github.raw"],
                capture_output=True, text=True, timeout=_t(10), check=False,
            )
            if proc.returncode == 0:
                text = proc.stdout
        except (OSError, subprocess.SubprocessError):
            text = None
    if not text:
        return None
    # Frontmatter only — a `require-pull-request:` mentioned in the PROSE is discussion,
    # not governance, and must not be mistaken for the field.
    head = text.split("\n---", 1)[0] if text.startswith("---") else ""
    m = re.search(r"^require-pull-request:[ \t]*(\S+)[ \t]*$", head, re.MULTILINE)
    if not m:
        return None
    val = m.group(1).strip().lower()
    if val in {"true", "yes"}:
        return True
    if val in {"false", "no"}:
        return False
    return None


def require_pull_request_for(slug: str | None = None) -> bool:
    """Should the baseline demand a PULL REQUEST for this repo? PR only when a party OTHER
    than the author reviews it. USER governance ruling, 2026-08-13, amended 2026-08-22.

    Resolved in this order:

    1. **The repo's own PRRD `require-pull-request:` field** — authoritative, ends the
       decision. USER ruling 2026-08-22 (TRDD-R4XC8MV1): each project owns its governance
       under its own public `design/`, so the repo answers for itself and every applier
       reads the same answer.

    2. **A repo owned by SOMEONE ELSE** → True. Collaborating on another owner's project
       means the PR is a genuine request to a genuine second party. (Push would be refused
       anyway; the ruleset should not pretend otherwise.)

    3. **Otherwise False** — your own repo, governance unstated. The same agent writes the
       code and reviews it, so a PR is addressed to its own author: it reviews nothing,
       gates nothing, and is the direct cause of a repo sitting "eternally stuck with dozens
       of feature branches it can open but never merge" (USER, 2026-08-13).

    **The `harness_backend.backend()` branch was REMOVED, and that removal is the fix.** It
    returned True whenever the CALLING PROCESS ran inside the ai-maestro harness — a property
    of the caller, not of the repo. So the janitor standalone computed "no PR" and the hub
    inside the harness computed "PR" for the SAME repo, and the two appliers flip-flopped its
    ruleset; 15 of 22 fleet repos were measured carrying a `pull_request` rule none of them
    should have under the 2026-08-13 ruling. Harness governance did not go away — it moved to
    where it can be read consistently: a harness-managed project sets
    `require-pull-request: true` in its own PRRD and every applier obeys it.

    Fail-open toward the WORKFLOW: an unstated requirement or an unknown login returns False.
    A wrongly-DEMANDED PR silently halts all merging (the disaster this ruling exists to end);
    a wrongly-omitted one only means a solo owner pushes to their own default branch, which
    is what they would do anyway.
    """
    stated = prrd_pull_request_requirement(slug)
    if stated is not None:
        return stated
    if not slug:
        return False
    try:
        import cross_project_issue as cpi  # noqa: PLC0415 -- local, same reason

        login = cpi.gh_login()
        # Unknown login → False, per the fail-open note above: we must not demand a PR on a
        # repo we merely FAILED to confirm is ours.
        return bool(login) and not cpi.is_owned_by(slug, login)
    except Exception:  # noqa: BLE001
        return False


def require_pull_request_default() -> bool:
    """Back-compat shim for callers with no repo slug — harness-only decision."""
    return require_pull_request_for(None)


def baseline_ruleset_payloads(
    default_branch: str,
    required_status_checks: list[dict] | None = None,
    *,
    require_pull_request: bool | None = None,
) -> list[dict]:
    """Return the three ratified baseline ruleset payloads (branch pair + tag protection).

    Each element is a JSON-serialisable dict ready for
    `gh api {POST|PUT} /repos/{owner}/{repo}/rulesets`.

    `default_branch` is accepted for signature symmetry with the rest of
    the module and to fail loudly on an empty value, but the emitted
    `conditions.ref_name.include` uses the `~DEFAULT_BRANCH` magic ref
    (NOT `refs/heads/<default_branch>`) — that is what the ratified spec
    and the maintainer plugin emit, so the payloads are byte-identical
    regardless of the literal branch name.

    `required_status_checks` is the auto-detected list of
    `{"context": "<job-id>"}` dicts (see `detect_required_status_checks`).
    When None or empty the `required_status_checks` RULE IS OMITTED ENTIRELY
    and the PR/checks ruleset ships with only its `pull_request` rule.

    That omission is not a preference — it is forced by the API. GitHub
    REJECTS a `required_status_checks` rule whose `required_status_checks`
    parameter is an empty array with `422 Validation Failed`, and the 422
    fails the WHOLE ruleset write, taking the `pull_request` rule down with
    it. The previous shape emitted the empty list and claimed the rule
    "gates on no specific contexts until the repo's CI surfaces some" — that
    claim was false, and it made every remote-repo apply 422 while the one
    repo whose checkout happened to be the cwd (so contexts WERE detected)
    silently succeeded, which is why the bug hid. Omitting the rule keeps the
    PR-review gate — the part that actually matters — installable everywhere;
    the checks rule reappears automatically once contexts can be detected
    (i.e. when run from that repo's own checkout).
    """
    if not default_branch:
        raise ValueError("default_branch must be a non-empty string")
    checks = list(required_status_checks or [])
    want_pr = require_pull_request_default() if require_pull_request is None else require_pull_request
    history_protect = {
        "name": HISTORY_RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "include": [_DEFAULT_BRANCH_REF],
                "exclude": [],
            },
        },
        # The OWNER (admin role) bypasses history-protect. USER Tier-3 ruling 2026-08-13:
        # "both baseline-history-protect and baseline-pr-and-checks must be changed to allow
        # mutations in history and direct pushing/merging by the owner."
        #
        # This was `[]` — nobody, explicitly including the admin. On a repo whose only human
        # is the owner that is not protection, it is a lock with no key: an amend, a rebase of
        # a stale branch, or a force-push to undo a bad commit becomes impossible for the one
        # person entitled to do it, and the guardian ends up being the thing blocking the work.
        # Same reasoning that removed `required_linear_history` (janitor#14): the baseline may
        # protect against accident, never against the owner's deliberate act.
        #
        # `deletion` + `non_fast_forward` still apply to EVERY non-admin actor, so CI, agents
        # and outside contributors remain fully constrained — only the owner is exempt.
        "bypass_actors": [
            {
                "actor_id": _ADMIN_REPOSITORY_ROLE_ID,
                "actor_type": "RepositoryRole",
                "bypass_mode": "always",
            },
        ],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            # DELIBERATELY NO required_linear_history. It forbids merge commits,
            # which forces every contributor onto rebase/squash against a default
            # branch that OTHER agents are concurrently advancing — endless rebase
            # churn that makes a many-agent repo effectively unmergeable. The AI
            # Maestro model has many agents merging each other's branches; linear
            # history actively jams that. `deletion` + `non_fast_forward` already
            # give the genuine safety (no branch deletion, no history rewrite);
            # linear history is a workflow OPINION, not protection — and a harmful
            # one here. Removed per the user's direction (the guardian must not be
            # the thing blocking the work). The maintainer plugin's matching
            # baseline must drop it too — tracked as a cross-repo sync.
        ],
    }
    pr_and_checks: dict[str, Any] = {
        "name": PR_CHECKS_RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "include": [_DEFAULT_BRANCH_REF],
                "exclude": [],
            },
        },
        "bypass_actors": [
            {
                "actor_id": _ADMIN_REPOSITORY_ROLE_ID,
                "actor_type": "RepositoryRole",
                "bypass_mode": "always",
            },
        ],
        # The checks rule is APPENDED BELOW only when `checks` is non-empty — GitHub
        # 422s an empty required_status_checks array and fails the whole write.
        #
        # The pull_request rule below is emitted ONLY when `want_pr` (see
        # `require_pull_request_default`). Standalone, the author and the reviewer are the
        # same agent, so a PR is addressed to its own author — it reviews nothing and only
        # blocks the merge. CI still runs on push, and history-protect still forbids deletion
        # and history rewrite for every non-owner, so dropping the PR rule costs no real
        # protection; it removes a hand-off to a party that does not exist.
        "rules": [],
    }
    if want_pr:
        pr_and_checks["rules"].append(
            {
                "type": "pull_request",
                "parameters": {
                    # ZERO required approvals, not 1. USER Tier-3 ruling 2026-08-13, from a
                    # measured failure: a repo sat "eternally stuck with dozens of feature
                    # branches it can open but never merge".
                    #
                    # WHY 1 was unsatisfiable rather than merely strict: GitHub does not let
                    # an author approve their own pull request. On a repo whose only human is
                    # the owner — which is every repo in this fleet — a PR they opened can
                    # NEVER reach one approval. There is no second reviewer and there never
                    # will be. So the rule did not raise the bar, it closed the door, and the
                    # branches piled up behind it.
                    #
                    # The PR path itself is KEPT (this rule still exists): PRs still run CI,
                    # still collect review threads, and `required_review_thread_resolution`
                    # still forces open threads to be resolved before merge. What is removed
                    # is only the count that no solo-owner repo could ever reach.
                    #
                    # Do NOT "restore" this to 1 on the theory that review is being skipped.
                    # It is the same class of error as `required_linear_history` (janitor#14)
                    # — a rule that reads as rigour and functions as a deadlock. If a repo
                    # ever genuinely has two humans, raise it FOR THAT REPO, not in the
                    # fleet-wide baseline.
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                },
            }
        )
    if checks:
        pr_and_checks["rules"].append(
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": checks,
                },
            }
        )
    tag_protect = {
        "name": TAG_PROTECT_RULESET_NAME,
        "target": "tag",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "include": [_TAG_PROTECT_REF],
                "exclude": [],
            },
        },
        # No bypass actor: creating a NEW tag is unrestricted, so publish.py still
        # cuts each vX.Y.Z release — zero publish-path impact, nobody needs to bypass.
        "bypass_actors": [],
        # rules: [deletion, update] (NOT non_fast_forward). `update` ("Restrict
        # updates") blocks EVERY repoint of an existing tag — including a fast-forward
        # move onto a descendant commit, the bypass that non_fast_forward-only would
        # miss (append a malicious child commit, ff-move vX.Y.Z onto it). Minimal-
        # complete immutability, correct regardless of how GitHub evaluates tag
        # fast-forwards. Byte-identical with the maintainer plugin.
        "rules": [
            {"type": "deletion"},
            {"type": "update"},
        ],
    }
    return [history_protect, pr_and_checks, tag_protect]


_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def detect_repo_slug(plugin_root: Path) -> str | None:
    """Read `repository` from `.claude-plugin/plugin.json` and return
    the `owner/repo` slug. Returns None when the manifest is missing,
    unparseable, or the URL doesn't match a github.com repo."""
    manifest = plugin_root / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    url = str(data.get("repository", "") or "")
    m = re.match(r"^https?://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        return None
    slug = m.group(1)
    return slug if _REPO_RE.match(slug) else None


def gh_available() -> bool:
    return shutil.which("gh") is not None


def detect_default_branch(slug: str) -> str | None:
    """Ask gh for the repo's default branch. Returns None on failure."""
    if not gh_available():
        return None
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{slug}", "--jq", ".default_branch"],
            capture_output=True, text=True, timeout=_t(10), check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    name = (proc.stdout or "").strip()
    return name or None


def viewer_is_admin(slug: str) -> bool:
    """Best-effort: True iff the authenticated viewer has admin perms
    on `slug`. Used as a safety gate before posting a ruleset — if we
    can't administer, we can't fix.
    """
    if not gh_available():
        return False
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{slug}", "--jq", ".permissions.admin"],
            capture_output=True, text=True, timeout=_t(10), check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    return (proc.stdout or "").strip().lower() == "true"


def list_existing_rulesets(slug: str) -> list[dict] | None:
    """Return the ruleset list for `slug`, or None on failure."""
    if not gh_available():
        return None
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{slug}/rulesets"],
            capture_output=True, text=True, timeout=_t(10), check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def ruleset_id_by_name(slug: str, name: str) -> int | None:
    """Return the numeric id of the ruleset named `name`, or None.

    None means BOTH "lookup failed" and "no such ruleset" — the caller
    must distinguish those via `list_existing_rulesets` returning None
    when it needs the don't-act-when-uncertain behaviour. This helper is
    a convenience for the apply path's PATCH-vs-POST decision once the
    list lookup has already succeeded.
    """
    rulesets = list_existing_rulesets(slug)
    if rulesets is None:
        return None
    for r in rulesets:
        if isinstance(r, dict) and r.get("name") == name:
            rid = r.get("id")
            if isinstance(rid, int):
                return rid
    return None


def baselines_present(slug: str) -> bool | None:
    """True iff ALL THREE ratified rulesets are already attached to the repo.

    Returns None on lookup failure so the caller knows the answer is
    "unknown" rather than "no" (matters for the auto path — don't act
    when uncertain). Used for the cheap "already converged" short-circuit
    before doing any PUT/POST work. MUST require the tag ruleset too — else a
    repo that has the branch pair but not `baseline-tag-protect` would be
    wrongly judged "converged" and never get the 3rd ruleset applied.
    """
    rulesets = list_existing_rulesets(slug)
    if rulesets is None:
        return None
    names = {r.get("name") for r in rulesets if isinstance(r, dict)}
    return (HISTORY_RULESET_NAME in names
            and PR_CHECKS_RULESET_NAME in names
            and TAG_PROTECT_RULESET_NAME in names)


def _bypass_actor_key(actor: dict) -> tuple:
    return (actor.get("actor_id"), actor.get("actor_type"), actor.get("bypass_mode"))


def _params_match(expected: dict, live: dict) -> bool:
    """Every key the BASELINE pins must be equal in the live rule; server-added
    extra keys in `live` are ignored (a GET echoes the payload plus decoration).
    `required_status_checks` lists compare as context SETS — order is not pinned."""
    for key, want in expected.items():
        got = live.get(key)
        if key == "required_status_checks" and isinstance(want, list):
            want_ctx = {c.get("context") for c in want if isinstance(c, dict)}
            got_ctx = {c.get("context") for c in (got or []) if isinstance(c, dict)}
            if want_ctx != got_ctx:
                return False
            continue
        if got != want:
            return False
    return True


def ruleset_content_drift(expected: dict, live: dict) -> list[str]:
    """Drift reasons for ONE live ruleset vs its ratified payload; [] = current.

    TRDD-DD0M4QL7: `baselines_present` answers "do rulesets with the baseline
    NAMES exist?" and nothing ever asked "do they still carry the baseline
    CONTENT?", so a hand-loosened ruleset stayed "converged" forever — the
    baseline could be created but never MAINTAINED. This is the content half.
    The comparison runs against `baseline_ruleset_payloads` (the code SSOT,
    never prose) and is SUBSET-shaped: only fields the baseline pins are
    compared, so server-added response decoration can never false-positive.

    One deliberate asymmetry: a live `required_status_checks` rule that the
    expected payload OMITS is NOT drift. The payload omits that rule exactly
    when CI contexts cannot be detected from the CURRENT checkout (the
    documented cwd-dependence in `baseline_ruleset_payloads`), so the live
    rule is evidence of an earlier apply from the repo's own checkout —
    stricter than what we can currently express, never stale. Flagging it
    would make a foreign-cwd repair PUT strip a working checks gate.
    """
    name = expected.get("name", "?")
    drift: list[str] = []
    for field in ("target", "enforcement"):
        if live.get(field) != expected.get(field):
            drift.append(f"{name}: {field} {live.get(field)!r} != {expected.get(field)!r}")
    exp_ref = (expected.get("conditions") or {}).get("ref_name") or {}
    live_ref = (live.get("conditions") or {}).get("ref_name") or {}
    for part in ("include", "exclude"):
        if set(live_ref.get(part) or []) != set(exp_ref.get(part) or []):
            drift.append(f"{name}: conditions.ref_name.{part} differs")
    exp_bypass = {_bypass_actor_key(a) for a in expected.get("bypass_actors") or []}
    live_bypass = {_bypass_actor_key(a) for a in live.get("bypass_actors") or []}
    if exp_bypass != live_bypass:
        drift.append(f"{name}: bypass_actors differ")
    exp_rules = {r["type"]: r.get("parameters", {}) for r in expected.get("rules") or []}
    live_rules = {
        r.get("type"): r.get("parameters", {})
        for r in live.get("rules") or []
        if isinstance(r, dict)
    }
    for rtype, params in exp_rules.items():
        if rtype not in live_rules:
            drift.append(f"{name}: missing rule {rtype}")
        elif not _params_match(params, live_rules[rtype]):
            drift.append(f"{name}: rule {rtype} parameters loosened/changed")
    for rtype in live_rules:
        if rtype not in exp_rules and rtype != "required_status_checks":
            drift.append(f"{name}: extra rule {rtype} (a repair apply would remove it)")
    return drift


def fetch_ruleset_detail(slug: str, ruleset_id: int) -> dict | None:
    """GET one ruleset's FULL body (the list endpoint returns summaries without
    rules/conditions/bypass_actors, so content comparison needs the detail)."""
    if not gh_available():
        return None
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{slug}/rulesets/{ruleset_id}"],
            capture_output=True, text=True, timeout=_t(10), check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def baselines_content_current(
    slug: str, default_branch: str, project_root: Path,
) -> tuple[bool, list[str]] | None:
    """(True, []) when all three baseline rulesets are content-current; (False,
    reasons) on drift; None when any lookup failed (uncertain — don't act).

    Expected payloads are built EXACTLY as the apply path builds them
    (same checks detection, same per-slug PR toggle), so "current" means
    "a repair PUT would be a byte-level no-op on the pinned fields".
    """
    rulesets = list_existing_rulesets(slug)
    if rulesets is None:
        return None
    by_name: dict[str, int] = {}
    for r in rulesets:
        if isinstance(r, dict) and isinstance(r.get("id"), int) and isinstance(r.get("name"), str):
            by_name[r["name"]] = r["id"]
    checks = detect_required_status_checks(project_root)
    payloads = baseline_ruleset_payloads(
        default_branch, checks, require_pull_request=require_pull_request_for(slug)
    )
    drift: list[str] = []
    for payload in payloads:
        name = payload["name"]
        rid = by_name.get(name)
        if rid is None:
            drift.append(f"{name}: missing entirely")
            continue
        live = fetch_ruleset_detail(slug, rid)
        if live is None:
            return None
        drift.extend(ruleset_content_drift(payload, live))
    return (not drift, drift)


def _workflow_triggers(wf: dict) -> set[str]:
    """The set of event names in a workflow's ``on:`` trigger.

    LOAD-BEARING: GitHub's ``on:`` key parses as the YAML 1.1 boolean ``True``
    under PyYAML, so we look it up under BOTH ``True`` and the literal ``"on"`` —
    without the ``True`` lookup ``wf.get("on")`` is ``None`` and EVERY workflow
    would be (wrongly) treated as having no PR trigger, dropping every check.
    Byte-identical to the maintainer-agent plugin's `triggers()` (janitor#14 /
    maintainer cde65eb) so both plugins auto-detect the SAME contexts."""
    on = wf.get(True, wf.get("on"))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    if isinstance(on, dict):
        return set(on.keys())
    return set()


def detect_required_status_checks(project_root: Path) -> list[dict]:
    """Discover the repo's CI check contexts from its WORKFLOW FILES.

    Globs ``.github/workflows/*.yml`` and ``*.yaml`` under `project_root`,
    parses each, and returns a sorted, de-duplicated list of
    ``{"context": "<name>"}`` dicts — the EXACT shape the GitHub rulesets
    API wants for ``required_status_checks``. The context for a job is its
    ``name:`` if set, else the job id (matching how GitHub names a check
    when no display name is given).

    Why parse the CONFIGURED workflow jobs rather than query the runtime
    ``repos/{slug}/commits/{branch}/check-runs`` API (the previous
    approach):

    * Runtime check-runs are EMPTY on a fresh repo whose CI has never run
      — so the ruleset would ship with no required checks until the first
      push, defeating the purpose of protecting the very first PR.
    * Worse, check-run NAMES do not always equal the context GitHub uses
      for branch-protection matching; feeding the wrong contexts to the
      rulesets API gets the whole POST/PATCH rejected with **HTTP 422
      Validation Failed**, which fails the entire apply. The workflow-
      config job ids/names are the source of truth GitHub itself derives
      the contexts from.

    This is the cross-plugin-agreed source (janitor #14) and matches the
    maintainer plugin's documented approach.

    Never raises and never hard-codes job ids: a malformed/unreadable
    workflow file is skipped (not fatal), and a project with no workflows
    (or all unparseable) yields an empty list — the ruleset is still
    created with a ``required_status_checks`` rule that gates on no
    specific contexts.
    """
    import yaml  # lazy — see the module-top note; only this function needs it

    workflows_dir = project_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return []
    files = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    contexts: set[str] = set()
    for wf_path in files:
        try:
            wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            # A single broken/unreadable workflow must never crash the
            # applier — skip it and keep collecting from the rest.
            continue
        if not isinstance(wf, dict):
            continue
        # Only a PR-triggered workflow can produce a check on a PR. A push-only
        # workflow's jobs (release / notify / tag-deploy) NEVER report on a PR, so
        # requiring one as a required_status_checks context would wedge every
        # non-admin PR forever in "expected, not reported" (admins bypass — which is
        # exactly why it's invisible on a 1-person repo). Filter to PR-triggered
        # workflows only — the shared fix coordinated on janitor#14 / maintainer
        # cde65eb; both plugins MUST detect the same set to stay byte-identical.
        if not ({"pull_request", "pull_request_target"} & _workflow_triggers(wf)):
            continue
        jobs = wf.get("jobs", {})
        if not isinstance(jobs, dict):
            continue
        for job_id, job_cfg in jobs.items():
            name = (job_cfg.get("name") if isinstance(job_cfg, dict) else None) or job_id
            if isinstance(name, str) and name.strip():
                contexts.add(name.strip())
    return [{"context": ctx} for ctx in sorted(contexts)]


def _post_or_patch_ruleset(
    slug: str, payload: dict, existing: tuple[int, str | None] | None,
) -> tuple[bool, str]:
    """POST a new ruleset, or PUT (update) an existing one when `existing`
    is set (idempotent-by-name). Returns (success, message).

    `existing` is `(id, updated_at)` — the id selects the PUT endpoint, and the
    timestamp is what lets the message report the EFFECT instead of the action
    (TRDD-Q8ZT5NW3). An identical PUT is a server-side no-op: GitHub does not
    move `updated_at`. Saying "updated" for one is not a cosmetic inaccuracy —
    this audit line has already been cited as evidence that a repair happened,
    once by me closing TRDD-DD0M4QL7 and once by the ai-maestro hub auditing the
    fleet, and on the apply it describes, three rulesets reported `updated`
    while the live API showed exactly ONE had changed.

    NOTE: GitHub's "Update a repository ruleset" endpoint is **PUT**
    `/repos/{owner}/{repo}/rulesets/{id}` — NOT PATCH. A PATCH returns 404 on
    real GitHub (verified on the live repo, janitor#14); an earlier PATCH here
    only ever passed because the test gh-stub answers any method. The update
    path is rarely hit (the apply short-circuits once both baselines are
    present), which is why the bug stayed latent."""
    if not gh_available():
        return (False, "gh CLI not in PATH")
    was_updated_at: str | None = None
    if existing is None:
        argv = [
            "gh", "api", "--method", "POST",
            f"repos/{slug}/rulesets",
            "--input", "-",
        ]
        verb = "created"
    else:
        existing_id, was_updated_at = existing
        argv = [
            "gh", "api", "--method", "PUT",
            f"repos/{slug}/rulesets/{existing_id}",
            "--input", "-",
        ]
        verb = "updated"
    try:
        proc = subprocess.run(
            argv,
            input=json.dumps(payload),
            capture_output=True, text=True, timeout=_t(15), check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (False, f"gh subprocess failed: {exc}")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()[-1:] or ["gh exited non-zero"]
        return (False, err[0])
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return (True, verb)
    if existing is not None:
        # Report the EFFECT. Three states, because there are genuinely three:
        # the timestamp moved (a real repair), it did not (an identical PUT —
        # the server no-op this card is about), or we cannot tell. The third is
        # named rather than folded into "updated", since collapsing an unknown
        # into the confident answer is the exact defect being fixed — a reader
        # grepping the audit log for repairs must not count a guess.
        now_updated_at = data.get("updated_at")
        if isinstance(now_updated_at, str) and isinstance(was_updated_at, str):
            verb = "updated" if now_updated_at != was_updated_at else "unchanged"
        else:
            verb = "put-unverified"
    new_id = data.get("id")
    return (True, f"{verb} id={new_id}" if new_id is not None else verb)


def delete_ruleset_by_name(slug: str, name: str) -> tuple[bool, str]:
    """Delete the ruleset named `name` if present. Returns (success, msg).

    `success` is True when the ruleset was deleted OR was already absent
    (both are the desired post-state). Used to remove the orphaned
    legacy `janitor-baseline` ruleset after the ratified pair lands.
    """
    if not gh_available():
        return (False, "gh CLI not in PATH")
    rid = ruleset_id_by_name(slug, name)
    if rid is None:
        return (True, "absent")
    try:
        proc = subprocess.run(
            [
                "gh", "api", "--method", "DELETE",
                f"repos/{slug}/rulesets/{rid}",
            ],
            capture_output=True, text=True, timeout=_t(15), check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (False, f"gh subprocess failed: {exc}")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()[-1:] or ["gh exited non-zero"]
        return (False, err[0])
    return (True, f"deleted id={rid}")


def apply_baseline_rulesets(
    slug: str, default_branch: str, project_root: Path,
) -> tuple[bool, list[tuple[str, bool, str]], list[dict]]:
    """Apply ALL THREE ratified rulesets idempotent-by-name (branch pair +
    baseline-tag-protect), then delete the legacy orphan union.

    `project_root` is the directory whose `.github/workflows/` is parsed
    to auto-detect the required CI check contexts (see
    `detect_required_status_checks` — workflow-config, not runtime
    check-runs, so a fresh repo's first PR is still gated and we never
    feed wrong contexts that 422 the rulesets API).

    Returns (all_ok, results, checks) where:
      * `results` is a list of (label, ok, message) tuples — one per
        applied ruleset plus one for the legacy cleanup,
      * `all_ok` is True iff every step succeeded,
      * `checks` is the auto-detected required-status-checks list that
        was actually embedded in the applied payloads. The caller reuses
        this for its announcement so the displayed checks match the
        applied ones exactly (and so detection runs ONCE, not once here +
        once in the caller).

    The ruleset list is fetched ONCE up front: if that lookup fails we
    can't safely tell PATCH from POST (and would risk a duplicate), so
    we abort the whole apply with a single failure result.
    """
    rulesets = list_existing_rulesets(slug)
    if rulesets is None:
        return (False, [("list", False, "ruleset list lookup failed")], [])
    # name -> (id, updated_at). The timestamp rides along so the apply can report whether a
    # PUT actually CHANGED anything (TRDD-Q8ZT5NW3); it is Optional because the list response
    # is not guaranteed to carry it, and an absent one must read as "cannot tell", never as
    # "unchanged".
    by_name: dict[str, tuple[int, str | None]] = {}
    for r in rulesets:
        if isinstance(r, dict):
            rid = r.get("id")
            nm = r.get("name")
            if isinstance(rid, int) and isinstance(nm, str):
                seen_at = r.get("updated_at")
                by_name[nm] = (rid, seen_at if isinstance(seen_at, str) else None)

    checks = detect_required_status_checks(project_root)
    # Slug-aware: this caller KNOWS the repo, so it can tell "my own standalone project"
    # (push directly) from "someone else's repo" (PR is a real request). See
    # `require_pull_request_for`.
    payloads = baseline_ruleset_payloads(
        default_branch, checks, require_pull_request=require_pull_request_for(slug)
    )

    results: list[tuple[str, bool, str]] = []
    rulesets_ok = True
    for payload in payloads:
        name = payload["name"]
        ok, msg = _post_or_patch_ruleset(slug, payload, by_name.get(name))
        results.append((name, ok, msg))
        if not ok:
            rulesets_ok = False

    # Only remove the pre-ratification orphans once ALL THREE ratified rulesets are
    # confirmed in place (rulesets_ok is False if ANY payload — incl. the tag ruleset —
    # failed) — otherwise a failed apply would strip the legacy protection and leave the
    # branch unprotected. The baseline-* set is created FIRST (above), so there is no
    # unprotected window during the rename. Deletes
    # the SHARED UNION (janitor + maintainer lineage) by exact name so a repo
    # either plugin ever touched fully converges. Idempotent — a missing legacy
    # ruleset reports success "absent".
    all_ok = rulesets_ok
    if rulesets_ok:
        for legacy_name in LEGACY_RULESET_NAMES:
            legacy_ok, legacy_msg = delete_ruleset_by_name(slug, legacy_name)
            results.append((legacy_name, legacy_ok, legacy_msg))
            if not legacy_ok:
                all_ok = False
    else:
        for legacy_name in LEGACY_RULESET_NAMES:
            results.append((legacy_name, True, "kept (ratified apply incomplete)"))

    return (all_ok, results, checks)


def guard_mode_enabled() -> bool:
    """Master gate for the guarded auto-apply path. Default is **True** — opt-OUT.

    Flipped from default-False on 2026-08-12. The old default made this an opt-in
    feature that nobody opted into, so on every default install the janitor only ever
    FLAGGED an unprotected default branch and never fixed one — code that exists, is
    tested, is documented, and never runs.

    The USER's standing security directive (2026-06-30, `act-dont-ask-security`) names
    branch-protection rulesets explicitly: fix everything detected, commit, report
    after, do not ask — because "every minute a project sits with missing branch
    protection is a window for supply-chain compromise" and "asking permission turns
    the janitor from a guard into a clipboard". A guard that ships OFF is that
    clipboard, one step earlier. Applying the ratified `baseline-*` pair AS-IS is
    Tier-0 (manager-approval-defaults §F), so no approval gates it; any DEVIATION from
    the pair remains Tier-2 and is not reachable from this path at all.

    Turning it on is safe because the default does not widen what the applier may do —
    six further gates still bind, every one fail-closed: the per-project
    `/janitor-autofix-off` veto, a repo slug that must resolve from THIS project's
    `.claude-plugin/plugin.json` (so a non-plugin project is skipped outright), `gh` on
    PATH, a discoverable default branch, an admin viewer, and an unfetchable ruleset
    list meaning "uncertain → do not act".

    Spelled inline rather than via `state.is_truthy_env` on purpose: the module NOTE above
    keeps this file importable by the lightweight `uv run --script` detectors that reach it
    transitively, and adding a module-level import for one boolean would trade that away.
    """
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_GUARD_MODE_ENABLED", "").strip().lower()
    if not raw:
        return True
    return raw not in ("0", "false", "no", "off")
