# Sentinel structural rules — "absence / context" tier.
#
# Native Python port of seven Sentinel (Ruby) rules that detect MISSING
# hardening or require job/step/trigger CONTEXT rather than a single-line
# regex match. Each rule is a faithful port of its lib/rules/<file>.rb
# counterpart; line-number logic mirrors the Ruby exactly so findings point
# at the same source line. Severity map: Sentinel medium→MAJOR, low→MINOR,
# high→HIGH (no critical in this tier).
#
# The module exposes a single module-level RULES list (one instance per
# rule) that scripts/doctor_classify.py collects and runs.

from __future__ import annotations

import re
from typing import NamedTuple

from lib.sentinel.model import (
    SEV_HIGH,
    SEV_MAJOR,
    SEV_MINOR,
    Finding,
    Rule,
    Workflow,
)
from lib.sentinel.rules_extra import IdTokenWriteUnscoped

# --- 1. missing-permissions (Sentinel medium → two-state MAJOR / MINOR) ----

class MissingPermissions(Rule):
    """Missing-permissions rule with FP-hardening round 3 two-state
    severity. The original rule fired MAJOR on every workflow lacking
    a top-level `permissions:` block — but ~50% of clean repos have
    pure read-only CI workflows (label / stale / welcome / build /
    test only) where the default `GITHUB_TOKEN` is fine. Calibrate
    the severity by looking at what the workflow actually does:

      * **MAJOR** when the workflow uses one of the documented
        write-actions (push-action / pull-request-creator / release
        creator) or runs `git push` / `gh pr create` / `gh release
        create` — write scope without an explicit permissions block
        IS a real risk.
      * **MINOR** otherwise — best-practice hardening rather than an
        active vulnerability."""
    name = "missing-permissions"
    severity = SEV_MAJOR  # default (overridden per-finding in check())
    description = (
        "No top-level permissions block — jobs inherit broad default token "
        "permissions"
    )

    def check(self, wf: Workflow) -> list[Finding]:
        # Ruby truthiness: an empty `permissions: {}` block is truthy and
        # suppresses the finding, so we test `is not None` (not Python falsy,
        # which would wrongly fire on `permissions: {}`). A bare `permissions:`
        # parses to None and DOES fire, matching Ruby `nil`.
        if wf.permissions(scope="workflow") is not None:
            return []
        line = wf.line_of(r"^jobs:") or 1

        # FP-hardening (round 3): inspect every step in every job to
        # decide whether the workflow performs any write operation.
        # Re-uses the same write-action / write-command regex lists
        # that `ExcessivePermissions` defines below — keeping the two
        # rules' definitions of "writes" in lockstep.
        has_writes = self._workflow_does_writes(wf)
        sev = SEV_MAJOR if has_writes else SEV_MINOR
        desc = (
            "No top-level permissions block — jobs inherit broad default "
            "token permissions, and the workflow performs write operations "
            "(push / release / PR) without explicit permissions."
            if has_writes else
            "No top-level permissions block — jobs inherit broad default "
            "token permissions. The workflow appears read-only; declaring "
            "`permissions: {}` is a best-practice hardening step."
        )
        finding = self._finding(wf, line, description=desc)
        # Override the per-finding severity (the base _finding helper
        # uses self.severity; we patched it post-construction).
        return [Finding(
            rule_id=finding.rule_id,
            line=finding.line,
            col=finding.col,
            matched_text=finding.matched_text,
            severity=sev,
            description=finding.description,
        )]

    def _workflow_does_writes(self, wf: Workflow) -> bool:
        """Return True if any step in any job uses one of the
        write-actions or write-commands enumerated by the
        `ExcessivePermissions` rule. Keeping the two rules' notions
        of 'writes' in lockstep avoids drift."""
        write_actions = ExcessivePermissions.WRITE_ACTIONS
        write_commands = ExcessivePermissions.WRITE_COMMANDS
        for job in wf.jobs().values():
            for step in wf.steps(job):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if uses and any(p.search(str(uses)) for p in write_actions):
                    return True
                run = step.get("run")
                if run and any(p.search(str(run)) for p in write_commands):
                    return True
        return False


# --- 2. missing-timeouts (Sentinel low → MINOR) ----------------------------

class MissingTimeouts(Rule):
    name = "missing-timeouts"
    severity = SEV_MINOR
    description = "Job without timeout-minutes — default is 360 minutes (6 hours)"

    def check(self, wf: Workflow) -> list[Finding]:
        findings: list[Finding] = []
        for job_id, job in wf.jobs().items():
            if isinstance(job, dict) and "timeout-minutes" in job:
                continue
            line = wf.line_of(r"^\s+" + re.escape(str(job_id)) + r":")
            findings.append(self._finding(
                wf,
                line or 0,
                matched_text=f"{job_id}:",
                description=(
                    f"Job '{job_id}' has no timeout-minutes — default is 360 "
                    "minutes (6 hours)"
                ),
            ))
        return findings


# --- 3. excessive-permissions (Sentinel low → MINOR) -----------------------

class ExcessivePermissions(Rule):
    name = "excessive-permissions"
    severity = SEV_MINOR
    description = (
        "This job has contents: write permission but no steps that appear to "
        "need it"
    )

    # Actions that perform write operations (commit, push, release, tag).
    WRITE_ACTIONS = (
        re.compile(r"peter-evans/create-pull-request"),
        re.compile(r"stefanzweifel/git-auto-commit-action"),
        re.compile(r"ad-m/github-push-action"),
        re.compile(r"EndBug/add-and-commit"),
        # Release-creating actions all need contents: write.
        re.compile(r"softprops/action-gh-release"),
        re.compile(r"ncipollo/release-action"),
        re.compile(r"svenstaro/upload-release-action"),
        re.compile(r"release-drafter/release-drafter"),
        re.compile(r"googleapis/release-please-action"),
        re.compile(r"changesets/action"),
        re.compile(r"actions/create-release"),
        re.compile(r"actions/upload-release-asset"),
    )

    # Run commands that require write access.
    WRITE_COMMANDS = (
        re.compile(r"\bgit\s+push\b"),
        re.compile(r"\bgit\s+tag\b"),
        re.compile(r"\bgh\s+pr\s+create\b"),
        re.compile(r"\bgh\s+pr\s+merge\b"),
        re.compile(r"\bgh\s+pr\s+comment\b"),
        re.compile(r"\bgh\s+pr\s+review\b"),
        re.compile(r"\bgh\s+release\s+(?:create|edit|upload|delete)\b"),
        re.compile(r"\bgh\s+api\b"),
    )

    def check(self, wf: Workflow) -> list[Finding]:
        findings: list[Finding] = []
        for job_id, job in wf.jobs().items():
            job_perms = wf.permissions(scope="job", job=job)
            if not isinstance(job_perms, dict):
                continue
            if job_perms.get("contents") != "write":
                continue
            if self._has_write_operations(wf.steps(job)):
                continue
            line = wf.line_of(r"^\s+" + re.escape(str(job_id)) + r":")
            findings.append(self._finding(
                wf,
                line or 0,
                matched_text=f"{job_id}: permissions: contents: write",
            ))
        return findings

    def _has_write_operations(self, steps) -> bool:
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if uses and any(p.search(str(uses)) for p in self.WRITE_ACTIONS):
                return True
            run = step.get("run")
            if run and any(p.search(str(run)) for p in self.WRITE_COMMANDS):
                return True
        return False


# --- 4. missing-persist-credentials (Sentinel high → HIGH) -----------------

class MissingPersistCredentials(Rule):
    name = "missing-persist-credentials"
    severity = SEV_HIGH
    description = (
        "Checkout without persist-credentials: false — token persists in "
        ".git/config"
    )

    _CHECKOUT = re.compile(r"actions/checkout[@\s]|actions/checkout$")
    _PUSH_RUN = re.compile(r"git push|gh pr create|peter-evans/create-pull-request")
    _PUSH_USES = re.compile(r"create-pull-request|yaml-update-action")

    def check(self, wf: Workflow) -> list[Finding]:
        findings: list[Finding] = []
        # Line attribution comes from uses_actions(), which is the ONE place that
        # maps a step to its source line. This rule used to keep a second copy of
        # that per-`uses` occurrence counter — and advanced it only for AUDITED
        # steps, i.e. inside the `job_pushes` gate below. So the Nth audited
        # checkout was reported at the Nth TEXTUAL checkout, and those diverge the
        # instant any job is skipped (janitor#157).
        #
        # What that looked like in the wild: a workflow with two hardened,
        # non-pushing build jobs and one pushing job that omits the setting. The
        # finding was CORRECT — the pushing job really does leave the token in
        # .git/config — but it was reported against the first build job's
        # checkout, which sets `persist-credentials: false` a few lines below. The
        # reporter read the cited line, saw the hardening, and filed it as a false
        # positive. A true finding pointed at innocent code is worse than a false
        # one: it costs the same investigation AND discredits the HIGH banner.
        line_of_step = {id(e["step"]): e["line"] for e in wf.uses_actions()}

        for job in wf.jobs().values():
            job_pushes = self._job_does_push(job, wf)
            # FP-resistance (FP-test round 2): the persist-credentials threat is
            # a GITHUB_TOKEN left in .git/config that a LATER step in the SAME
            # job abuses to push / open a PR / mutate the repo. A read-only job
            # has no write path to abuse it, so its checkout is NOT a HIGH
            # "can leak secrets" finding — flagging every read-only CI checkout
            # (the overwhelmingly common case) was a guaranteed false positive.
            # Only audit jobs that actually push / PR-create. `job_pushes` was
            # already computed here but was never used to gate the main finding.
            if not job_pushes:
                continue

            for step in wf.steps(job):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if not uses or not self._CHECKOUT.search(str(uses)):
                    continue

                with_block = step.get("with") or {}
                persist = with_block.get("persist-credentials") if isinstance(with_block, dict) else None

                if persist is False or persist == "false":
                    continue
                # The job pushes (gated above). An explicit `persist-credentials:
                # true` is the author intentionally opting in because the push
                # needs the token — don't second-guess that deliberate choice.
                if persist is True:
                    continue

                findings.append(self._finding(
                    wf,
                    line_of_step.get(id(step), 0),
                    matched_text=f"uses: {uses}",
                ))
        return findings

    def _job_does_push(self, job, wf: Workflow) -> bool:
        for s in wf.steps(job):
            if not isinstance(s, dict):
                continue
            run = s.get("run")
            if run is not None and self._PUSH_RUN.search(str(run)):
                return True
            uses = s.get("uses")
            if uses and self._PUSH_USES.search(str(uses)):
                return True
        return False


# --- 5. missing-env-protection (Sentinel medium → MAJOR) -------------------

class MissingEnvProtection(Rule):
    name = "missing-env-protection"
    severity = SEV_MAJOR
    description = (
        "Publish/deploy job without environment protection — no human gate "
        "before publication"
    )

    PUBLISH_INDICATORS = re.compile(
        "|".join((
            # JavaScript / TypeScript
            r"\bnpm\s+publish\b",
            r"\bpnpm\s+publish\b",
            r"\byarn\s+publish\b",
            r"\bnpx\s+pkg-pr-new\b",
            # Python
            r"\btwine\s+upload\b",
            r"\bpoetry\s+publish\b",
            r"\bflit\s+publish\b",
            r"\buv\s+publish\b",
            # Ruby
            r"\bgem\s+push\b",
            r"\brake\s+release\b",
            # Rust
            r"\bcargo\s+publish\b",
            # Java / Kotlin
            r"\bmvn\s+deploy\b",
            r"\bgradle\s+publish\b",
            r"\./gradlew\s+publish\b",
            # .NET
            r"\bdotnet\s+nuget\s+push\b",
            r"\bnuget\s+push\b",
            # Docker
            r"\bdocker\s+push\b",
            r"\bdocker\s+buildx\s+build\b.*--push",
            # Infrastructure
            r"\brailway\s+up\b",
            r"\bcdk\s+deploy\b",
            r"\bterraform\s+apply\b",
            r"\bpulumi\s+up\b",
            r"\bfly\s+deploy\b",
            r"\bheroku\s+container:push\b",
            # Homebrew
            r"\bbrew\s+bump-formula-pr\b",
        ))
    )

    def check(self, wf: Workflow) -> list[Finding]:
        findings: list[Finding] = []
        for job_id, job in wf.jobs().items():
            if isinstance(job, dict) and "environment" in job:
                continue

            steps = wf.steps(job)
            has_publish = any(
                isinstance(s, dict) and s.get("run") is not None
                and self.PUBLISH_INDICATORS.search(str(s.get("run")))
                for s in steps
            )

            has_oidc = (
                self._oidc_id_token(wf.permissions(scope="job", job=job))
                or self._oidc_id_token(wf.permissions(scope="workflow"))
            )
            if has_oidc and isinstance(job, dict):
                # A Sigstore attestation mints a SIGNING token, not a deployment
                # credential — it proves provenance of an artifact already built,
                # it does not itself publish anything, so there is no "release
                # without human review" for an environment: gate to guard.
                # Registry-OIDC publishing (npm trusted publishing etc.) is
                # DELIBERATELY NOT exempted here: unlike attestation it IS a
                # publish action, and "should a human approve before this runs"
                # is a genuine, separate concern from the OIDC-SCOPE question
                # IdTokenWriteUnscoped answers (janitor#99) — conflating the two
                # was the mistake caught while fixing janitor#164's memgrep
                # release job (an attestation-only job with no publish step at
                # all still tripped this rule via has_oidc alone). Suppressed
                # only when the job does NOT also perform real cloud auth, which
                # is still a genuine risk.
                if IdTokenWriteUnscoped._job_uses_any(
                    job, IdTokenWriteUnscoped._ATTESTATION_USES
                ) and not IdTokenWriteUnscoped._job_uses_any(
                    job, IdTokenWriteUnscoped._CLOUD_AUTH_USES
                ):
                    has_oidc = False

            if has_publish or has_oidc:
                line = wf.line_of(r"^\s+" + re.escape(str(job_id)) + r":")
                findings.append(self._finding(
                    wf,
                    line or 0,
                    matched_text=f"{job_id}:",
                ))
        return findings

    def _oidc_id_token(self, perms) -> bool:
        # `permissions: write-all` is a STRING, not a dict, and implicitly
        # grants id-token: write — so a dict-only check silently misses the
        # unscoped-OIDC case for write-all workflows. Accept both shapes
        # (matches IdTokenWriteUnscoped._id_token_is_write).
        if isinstance(perms, str):
            return perms.strip().lower() == "write-all"
        if isinstance(perms, dict):
            return perms.get("id-token") == "write"
        return False


# --- 6. overly-broad-triggers (Sentinel low → MINOR) -----------------------

class OverlyBroadTriggers(Rule):
    name = "overly-broad-triggers"
    severity = SEV_MINOR
    description = "Push or pull_request trigger without branch filter"

    _FILTER_KEYS = (
        "branches", "branches-ignore", "tags", "tags-ignore",
        "paths", "paths-ignore",
    )

    def check(self, wf: Workflow) -> list[Finding]:
        findings: list[Finding] = []
        triggers = wf.triggers()
        if not isinstance(triggers, dict):
            return findings

        for trigger in ("push", "pull_request"):
            if trigger not in triggers:
                continue
            config = triggers[trigger]

            unfiltered = (
                config is None
                or config is True
                or (
                    isinstance(config, dict)
                    and not any(k in config for k in self._FILTER_KEYS)
                )
            )
            if unfiltered:
                line = wf.line_of(r"^\s+" + trigger + r":")
                findings.append(self._finding(
                    wf,
                    line or 0,
                    matched_text=f"{trigger}:",
                    description=(
                        f"'{trigger}' trigger with no branch filter — runs on "
                        "all branches"
                    ),
                ))
        return findings


# --- 7. missing-frozen-lockfile (Sentinel medium → MAJOR) ------------------

class _Check(NamedTuple):
    """One lockfile check (port of a Ruby CHECKS entry).

    `match` flags the line; `safe`/`safe_alt` suppress when present; `skip`
    ignores the line entirely (an unrelated subcommand). Optional patterns are
    None when the Ruby entry omits them.
    """

    match: re.Pattern[str]
    message: str
    safe: re.Pattern[str] | None = None
    safe_alt: re.Pattern[str] | None = None
    skip: re.Pattern[str] | None = None


class MissingFrozenLockfile(Rule):
    name = "missing-frozen-lockfile"
    severity = SEV_MAJOR
    description = "Package install without lockfile enforcement"

    # JavaScript / TypeScript
    _NPM_INSTALL = re.compile(r"\bnpm\s+install\b")
    _NPM_SAFE = re.compile(r"--ci\b|\bnpm\s+ci\b")
    _PNPM_INSTALL = re.compile(r"\bpnpm\s+install\b")
    _PNPM_SAFE = re.compile(r"--frozen-lockfile")
    _YARN_INSTALL = re.compile(r"\byarn\s+install\b")
    _YARN_SAFE = re.compile(r"--frozen-lockfile|--immutable")
    _BUN_INSTALL = re.compile(r"\bbun\s+install\b")
    _BUN_SAFE = re.compile(r"--frozen-lockfile")
    # Python
    _PIP_INSTALL = re.compile(r"\b(?:pip3?|uv\s+pip)\s+install\b")
    _PIP_SAFE = re.compile(r"-r\b|--requirement\b|-c\b|--constraint\b|--require-hashes")
    _PIP_LOCAL = re.compile(r"\binstall\s+(?:-e\s+)?\.(?:\s|$|\[)")
    # Ruby. Tightened vs the Sentinel source: require `bundle` to be a real
    # command token — a negative lookbehind drops `--bundle` / `webpack-bundle`
    # and the trailing `(?!\.)` drops `bundle.js`, both of which the bare
    # `\bbundle\b` form would have flagged as false positives.
    _BUNDLE_INSTALL = re.compile(r"(?<![\w.-])bundle\b(?!\.)(?:\s+install\b)?")
    _BUNDLE_SAFE = re.compile(r"--frozen|--deployment|BUNDLE_FROZEN\s*=\s*(?:true|1)")
    _BUNDLE_OTHER = re.compile(
        r"\bbundle\s+(?:exec|add|update|show|list|info|outdated|check|config|"
        r"lock|cache|clean|console|open|gem|platform|env|doctor|viz|version|"
        r"init|binstubs|pristine|plugin)\b"
    )
    # Go
    _GO_GET = re.compile(r"\bgo\s+get\b")
    # Rust
    _CARGO_INSTALL = re.compile(r"\bcargo\s+install\b")
    _CARGO_SAFE = re.compile(r"--locked")
    # PHP
    _COMPOSER_UPDATE = re.compile(r"\bcomposer\s+update\b")

    def __init__(self) -> None:
        # Each _Check: match (required), then optional safe/safe_alt (suppress
        # when present) and skip (ignore the line entirely). Mirrors the Ruby
        # CHECKS array order; Ruby appends ALL matching checks per line, so we
        # iterate every check and never break.
        self._checks: tuple[_Check, ...] = (
            _Check(
                match=self._NPM_INSTALL,
                safe=self._NPM_SAFE,
                message=(
                    "npm install without lockfile enforcement — dependency "
                    "resolution may differ from tested versions"
                ),
            ),
            _Check(
                match=self._PNPM_INSTALL,
                safe=self._PNPM_SAFE,
                message=(
                    "pnpm install without --frozen-lockfile — dependency "
                    "resolution may differ from tested versions"
                ),
            ),
            _Check(
                match=self._YARN_INSTALL,
                safe=self._YARN_SAFE,
                message=(
                    "yarn install without lockfile enforcement — dependency "
                    "resolution may differ from tested versions"
                ),
            ),
            _Check(
                match=self._BUN_INSTALL,
                safe=self._BUN_SAFE,
                message=(
                    "bun install without --frozen-lockfile — dependency "
                    "resolution may differ from tested versions"
                ),
            ),
            _Check(
                match=self._PIP_INSTALL,
                safe=self._PIP_SAFE,
                safe_alt=self._PIP_LOCAL,
                message=(
                    "pip install with unpinned packages — no lockfile or "
                    "constraints file ensuring reproducibility"
                ),
            ),
            _Check(
                match=self._BUNDLE_INSTALL,
                safe=self._BUNDLE_SAFE,
                skip=self._BUNDLE_OTHER,
                message=(
                    "bundle install without --frozen — Gemfile.lock may be "
                    "modified during install"
                ),
            ),
            _Check(
                match=self._GO_GET,
                message=(
                    "go get in CI is non-deterministic — resolved versions "
                    "may change between runs"
                ),
            ),
            _Check(
                match=self._CARGO_INSTALL,
                safe=self._CARGO_SAFE,
                message=(
                    "cargo install without --locked — Cargo.lock will be "
                    "ignored and dependencies re-resolved"
                ),
            ),
            _Check(
                match=self._COMPOSER_UPDATE,
                message=(
                    "composer update in CI resolves fresh dependencies, "
                    "ignoring composer.lock"
                ),
            ),
        )

    def check(self, wf: Workflow) -> list[Finding]:
        findings: list[Finding] = []
        for i, line in enumerate(wf.raw_lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            for chk in self._checks:
                if not chk.match.search(line):
                    continue
                if chk.skip and chk.skip.search(line):
                    continue
                if chk.safe and chk.safe.search(line):
                    continue
                if chk.safe_alt and chk.safe_alt.search(line):
                    continue

                findings.append(self._finding(
                    wf,
                    i + 1,
                    matched_text=stripped,
                    description=chk.message,
                ))
        return findings


RULES = [
    MissingPermissions(),
    MissingTimeouts(),
    ExcessivePermissions(),
    MissingPersistCredentials(),
    MissingEnvProtection(),
    OverlyBroadTriggers(),
    MissingFrozenLockfile(),
]
