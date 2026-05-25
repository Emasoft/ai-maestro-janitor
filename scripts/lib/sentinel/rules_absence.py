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
from typing import NamedTuple, Optional

from lib.sentinel.model import (
    SEV_HIGH,
    SEV_MAJOR,
    SEV_MINOR,
    Finding,
    Rule,
    Workflow,
)


# --- 1. missing-permissions (Sentinel medium → MAJOR) ----------------------

class MissingPermissions(Rule):
    name = "missing-permissions"
    severity = SEV_MAJOR
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
        return [self._finding(wf, line)]


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
        # Mirrors Ruby `Hash.new(0)` — per-`uses` occurrence counter so two
        # identical checkout steps map to consecutive matching source lines.
        seen_checkout_lines: dict[str, int] = {}

        for job in wf.jobs().values():
            job_pushes = self._job_does_push(job, wf)

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
                if job_pushes and persist is True:
                    continue

                all_lines = wf.lines_of(r"uses:\s*" + re.escape(str(uses)))
                idx = seen_checkout_lines.get(uses, 0)
                if idx < len(all_lines):
                    line = all_lines[idx]
                elif all_lines:
                    line = all_lines[-1]
                else:
                    line = None
                seen_checkout_lines[uses] = idx + 1

                findings.append(self._finding(
                    wf,
                    line or 0,
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

            if has_publish or has_oidc:
                line = wf.line_of(r"^\s+" + re.escape(str(job_id)) + r":")
                findings.append(self._finding(
                    wf,
                    line or 0,
                    matched_text=f"{job_id}:",
                ))
        return findings

    def _oidc_id_token(self, perms) -> bool:
        if not isinstance(perms, dict):
            return False
        return perms.get("id-token") == "write"


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

    match: "re.Pattern[str]"
    message: str
    safe: Optional["re.Pattern[str]"] = None
    safe_alt: Optional["re.Pattern[str]"] = None
    skip: Optional["re.Pattern[str]"] = None


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
    # Ruby
    _BUNDLE_INSTALL = re.compile(r"\bbundle\b(?:\s+install\b)?")
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
