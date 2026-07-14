"""The ISSUE-CODE CATALOG — every incident the janitor can detect, with a stable id (TRDD-CGYMUKO6).

One registry, one entry point:

    raise_issue("WFSEC-001", where="ci.yml:42", evidence=[".github/workflows/ci.yml"], expr="github.event.issue.title")

`raise_issue` is the ONLY call a detector needs to turn a finding into work. It looks the code up,
resolves `kind` → (domain, agent) through `tickets.KIND_REGISTRY`, renders OUR template with the
detector's SANITIZED data, and routes by domain:

    HARNESS  → tickets.open_ticket()      — the janitor's own machinery; it fixes itself, unattended.
    PROJECT  → ticket_proposal.propose()  — the user's repo; it may only propose + recommend.

**THE CODE DECIDES THE DOMAIN.** A detector cannot pass a `kind`, a `domain`, or an `agent`, so no
producer can accidentally (or maliciously) grant itself unattended dispatch into the user's code. That
is the whole reason this indirection exists rather than each detector calling `open_ticket` directly.

**THE TEMPLATE IS OURS; ONLY THE DATA IS THEIRS.** Every value a detector interpolates is
attacker-influenceable (a filename, a dependency name, a workflow line, a GitHub issue title), so it is
run through `tickets._clean` — which defangs `[`/`]` so a payload cannot mimic a `[janitor-…]` marker
in heartbeat stdout, where the model reads lines AS INSTRUCTIONS. The surrounding prose — the title,
the explanation, the fix the agent is told to attempt — is authored here, in our source.

**A CODE IS IMMUTABLE ONCE SHIPPED**, like a schema version: `<SCANNER>-<NNN>`, never renumbered,
never reused. A citation in a closed ticket, a report, or a TRDD must still resolve years later.
`docs/ISSUE-CODES.md` is GENERATED from this file (`scripts/issue_catalog_doc.py --write`) and a test
fails when the two drift — a stale list of what the janitor can see is worse than no list, because it
is a document that lies.
"""

from __future__ import annotations

import re
import string
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ticket_proposal  # noqa: E402
import tickets  # noqa: E402

CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{3}$")

# How many proposals ONE detector may author in ONE fire. A proposal is a file in the user's
# git-tracked design board, so a scanner that trips over a vendored tree full of matches must not be
# able to commit a hundred of them. The ones over the cap are not lost — the finding is still printed,
# and the next fire proposes them (dedupe means the earlier ones do not repeat). Any detector that
# caps MUST log what it dropped: a silent truncation reads as "that was everything".
MAX_RAISES_PER_FIRE = 5


@dataclass(frozen=True)
class Issue:
    """One detectable issue. `kind` is the ONLY thing that decides domain + agent (via KIND_REGISTRY)."""

    scanner: str  # the detector/validator that emits it — the grep handle
    kind: str  # must exist in tickets.KIND_REGISTRY
    severity: str  # default; a producer may override only with another known severity
    title: str  # ONE line, `{placeholder}`s filled from the detector's sanitized data
    what: str  # what the condition IS (the user-facing description in the TRDD and the docs)
    why: str  # why it matters — why this is worth an agent's time
    fix: str  # what the dispatched agent is told to ATTEMPT (never "what it will do")


# --------------------------------------------------------------------------- #
# THE CATALOG. Append only: a shipped code is immutable.
# --------------------------------------------------------------------------- #

ISSUE_CATALOG: dict[str, Issue] = {
    # ---------------- HARNESS — the janitor's own machinery (auto-open, auto-dispatch) -------------
    "MEMGREP-001": Issue(
        scanner="memgrep-validate",
        kind="index-corruption",
        severity="high",
        title="the FTS index in {scope} does not match its content table",
        what="An external-content FTS5 table holds no data of its own, so its rows can silently fall "
        "out of step with the table they index. `PRAGMA integrity_check` returns `ok` and a "
        "`SELECT count(*)` reads the CONTENT table — both lie. Only "
        "`INSERT INTO t(t, rank) VALUES('integrity-check', 1)` compares index against content.",
        why="Recall degrades to nothing while every surface reports a healthy database, so a memory the agent depends on is simply never found — and nothing says so.",
        fix="Rebuild the index from its content tables (`INSERT INTO t(t) VALUES('rebuild')`), then re-validate. If a FRESH index still fails, the bug is in the schema code, not the data.",
    ),
    "MEMGREP-002": Issue(
        scanner="memgrep-validate",
        kind="index-corruption",
        severity="critical",
        title="the memgrep database in {scope} fails SQLite's own integrity check",
        what="`PRAGMA integrity_check` reports structural damage: the file itself is corrupt, not merely out of step with its content.",
        why="Every read can return wrong rows or throw. Unlike an FTS desync, this cannot be repaired by a rebuild — the pages are damaged.",
        fix="Delete the database AND its `-wal`/`-shm` siblings (a fresh db beside a stale WAL is REAL corruption), then reindex the corpus from the markdown notes, which are the source of truth.",
    ),
    "MEMGREP-003": Issue(
        scanner="memgrep-validate",
        kind="migration-failure",
        severity="critical",
        title="an FTS table in {scope} has the wrong column set: {table}",
        what="A migration recreated an FTS table with columns that no longer match what the code queries.",
        why="Queries fail or — worse — silently match the wrong column, so recall returns confidently wrong results.",
        fix="Recreate the table with the current column set and rebuild it from the content tables. The migration step that produced this shape is the real defect; fix it too.",
    ),
    "MEMGREP-004": Issue(
        scanner="memgrep-validate",
        kind="migration-failure",
        severity="critical",
        title="a migration left `{table}` without column `{column}` in {scope}",
        what="A base table does not have the shape the current schema version claims it has.",
        why="The database is stamped as migrated but is not. Every later migration builds on a false premise, so the damage compounds silently.",
        fix="Read the migration ladder, find the step that failed to add the column, and repair it so it is transactional and self-validating. Then rebuild the database from the notes.",
    ),
    "MEMGREP-005": Issue(
        scanner="memgrep-validate",
        kind="index-corruption",
        severity="high",
        title="orphaned rows in {scope}: {table} references memories that no longer exist",
        what="Child rows survived the deletion of their parent memory — a foreign-key invariant the schema depends on is broken.",
        why="Recall surfaces notes and lessons that belong to a page that is gone, so the agent acts on knowledge the corpus no longer contains.",
        fix="Delete the orphans, then find the delete path that failed to cascade — the orphans are a symptom, the missing cascade is the defect.",
    ),
    "MEMGREP-006": Issue(
        scanner="memgrep-validate",
        kind="migration-failure",
        severity="high",
        title="the schema version stamp in {scope} disagrees with the database's actual shape",
        what="`PRAGMA user_version` was stamped without the migration that earns it (or the database is NEWER than this build's schema).",
        why="A wrong stamp makes every future migration skip or repeat. A newer-than-expected database must never be 'migrated' downward — that mangles data written by a build we do not know.",
        fix="If the stamp is ahead of this build's schema, REFUSE to touch it and tell the user to update. Otherwise rebuild from the notes and re-run the ladder transactionally.",
    ),
    "MEMGREP-007": Issue(
        scanner="memgrep-validate",
        kind="migration-failure",
        severity="critical",
        title="a base table is missing entirely from the memgrep database in {scope}",
        what="A table the schema requires does not exist at all — the schema was never fully applied, or something dropped it.",
        why="Every query against that table throws. Unlike a missing column (which fails quietly), this fails loudly — but only once something reads it, which may be days later.",
        fix="Re-apply the schema and reindex from the markdown notes, which are the source of truth. Then find what dropped the table — a table does not vanish on its own.",
    ),
    "MEMGREP-008": Issue(
        scanner="memgrep-validate",
        kind="migration-failure",
        severity="critical",
        title="an FTS index is missing entirely from the memgrep database in {scope}",
        what="A full-text index the schema requires does not exist — a DROP without the matching CREATE, the shape a half-applied migration leaves behind.",
        why="Search silently returns nothing rather than failing, so the corpus looks empty instead of broken. That is the worst failure mode there is: it is indistinguishable from having no memories.",
        fix="Recreate the FTS table and rebuild it from its content table, then fix the migration step that dropped it without recreating it.",
    ),
    "MEMGREP-009": Issue(
        scanner="memgrep-index-health",
        kind="index-corruption",
        severity="high",
        title="the memgrep index in {scope} has needed self-repair {count} times in {window}",
        what="The index keeps failing validation on open, and the self-heal keeps repairing it. The data is fine — something is RE-BREAKING it.",
        why="This is the signal the original incident had no way to produce. The self-heal RACES any observer and wins: every process that opens the index (the autorecall hook on every prompt, the librarian, a memory agent) repairs it in passing, so a probe that inspects the DATABASE always finds it pristine. A corruption re-manufactured daily is invisible to state inspection — and that is exactly how the 2026-07-14 migration bug hid for days. The repair EVENT is the only durable evidence.",
        fix="Do NOT just rebuild it again — that is what has been happening. Read `.memgrep/self-heal.log` for what failed and when, then find the WRITER that keeps corrupting it (a migration step, a schema change, a concurrent writer without the busy timeout). The index is the victim; the code that breaks it is the defect.",
    ),
    "DAEMON-001": Issue(
        scanner="daemon-supervisor",
        kind="daemon-crash-loop",
        severity="critical",
        title="the global janitor daemon has died and respawned {count} times in the guard window",
        what="The machine-wide singleton keeps exiting shortly after spawn. The crash-loop breaker is tripped, so the janitor has stopped trying to restart it.",
        why="The daemon owns every user-scope mutation — plugin updates, OAuth keepalive, the fleet guardian. With it dead, unattended sessions stop recovering from rate limits.",
        fix="Read the daemon log for the exception, reproduce it, and fix the crash. If the cause is a bad plugin version, the last-good rollback is already available — verify it engaged.",
    ),
    "SELFINT-001": Issue(
        scanner="janitor-self-integrity",
        kind="self-integrity",
        severity="critical",
        title="a janitor file failed attestation against the shipped manifest: {path}",
        what="A plugin file's sha256 does not match the manifest published with its release — it was modified after install.",
        why="The janitor runs with the user's full privileges on every project on this machine. A tampered detector is a tampered guardian, and it would be the last thing to report itself.",
        fix="Do NOT self-heal by overwriting: preserve the modified file as evidence FIRST, then reinstall the plugin from its release and diff the two. Report to the user before anything else.",
    ),
    "SELFINT-002": Issue(
        scanner="janitor-self-integrity",
        kind="self-integrity",
        severity="high",
        title="the janitor's audit chain no longer verifies: {detail}",
        what="The HMAC-chained audit log has a break that is not the known concurrent-fork artifact.",
        why="The audit chain is how the janitor proves what it did to this machine. A chain that cannot be verified is not evidence.",
        fix="Preserve the chain, identify the break point, and determine whether it is a lost update (a concurrency bug to fix) or a rewrite (a security event to report).",
    ),
    "SELFINT-003": Issue(
        scanner="janitor-self-integrity",
        kind="self-integrity",
        severity="medium",
        title="a janitor skill has lost its integrity notice: {path}",
        what="A shipped `janitor-*` SKILL.md no longer carries the preamble that tells its reader the skill's instructions come from the plugin's own source and never from the data it is handed.",
        why="That preamble is the skill's anti-injection boundary, stated where the agent will actually read it. A skill that has quietly lost it is one an attacker's payload can argue with.",
        fix="Restore the notice in the janitor's SOURCE repository and ship it. Do NOT patch the plugin CACHE — that directory is replaced wholesale by the next update, so a fix applied there disappears without a trace and the finding comes back looking like a new one.",
    ),
    "STATE-001": Issue(
        scanner="state-guard",
        kind="state-corruption",
        severity="high",
        title="a janitor state file is unreadable: {path}",
        what="A file under `.janitor/state/` cannot be parsed — truncated, or half-written by a process that died mid-write.",
        why="State drives the heartbeat's decisions (cadence, resume, dedupe). A file that fails to parse is usually treated as absent, so the janitor silently forgets something it knew.",
        fix="Find the write site and make it ATOMIC (tmp + `os.replace`). A non-atomic write to state is the defect; the corrupt file is only its symptom.",
    ),
    "MEMCORP-001": Issue(
        scanner="memory-librarian",
        kind="memory-corpus",
        severity="medium",
        title="the wikimem corpus in {scope} has structural damage: {detail}",
        what="Pages are malformed, links dangle, or footnote refs do not resolve.",
        why="A corpus whose links do not resolve cannot be navigated, and the LINK LAW (every link is bidirectional) is what makes recall work at all.",
        fix="Run the memory curator's repair pass under the edit transaction, which proves no knowledge was lost before it commits.",
    ),
    # ---------------- PROJECT — the USER's repo. PROPOSE ONLY, never unattended. -------------------
    # The six WFSEC codes are grouped by THE FIX, not by the scanner's rule name: the workflow auditor
    # emits 54 rule ids, and two rules belong to the same code exactly when the same repair answers
    # both. `workflow_issue_codes.CODE_FOR_RULE` is the map (and a test proves it is total), so one
    # dispatched agent fixes one coherent class across the repo instead of 54 agents each editing the
    # same file. `{rules}` names the specific rule ids and locations found.
    "WFSEC-001": Issue(
        scanner="workflow-security",
        kind="security-workflow",
        severity="high",
        title="a workflow lets attacker-controlled input reach an executable position in {where}",
        what="A GitHub Actions workflow interpolates `${{ github.event.* }}` (or another attacker-controllable expression) directly into something that gets EXECUTED or EVALUATED — a shell `run:` body, a `github-script` block, `runs-on:`, a matrix, `$GITHUB_ENV`, `$GITHUB_OUTPUT`, or an AI tool's config.",
        why="Anyone who can open an issue or a PR can put shell metacharacters in that field and execute code on the runner — with the workflow's secrets and token in scope. The title of an issue is not data the workflow gets to trust.",
        fix='Pass the value through an `env:` variable and reference it as `"$VAR"` inside the script — the value then arrives as data, not as source. Never interpolate an expression into anything that will be parsed as code.',
    ),
    "WFSEC-002": Issue(
        scanner="workflow-security",
        kind="security-workflow",
        severity="critical",
        title="a workflow runs fork-controlled code with the base repo's privileges in {where}",
        what="A workflow that holds the BASE repo's write token and secrets executes code the contributor controls — checking out a PR head under `pull_request_target`, re-running a `workflow_run` head, acting on an `issue_comment`, or handing a fork's artifact/cache to a privileged job.",
        why="This is the single most exploited GitHub Actions pattern: it executes untrusted code with full write access to the base repository. There is no sandbox — the token is right there.",
        fix="Use `pull_request` (no secrets, no write token) for anything that runs contributor code, or split into an UNTRUSTED build job and a PRIVILEGED job that never checks out fork code and only consumes verified inputs.",
    ),
    "WFSEC-003": Issue(
        scanner="workflow-security",
        kind="security-workflow",
        severity="medium",
        title="a workflow's token or permission scope is wider than the job needs in {where}",
        what="The workflow inherits (or explicitly grants) more privilege than it uses: no `permissions:` block, a broad grant, `secrets: inherit`, an unscoped app token, an ungated `id-token: write`, or a checkout that leaves the token persisted on disk.",
        why="Every excess grant is blast radius. A compromised step — or one malicious dependency in one action — inherits whatever the job holds, and 'write to contents' is enough to rewrite the repository.",
        fix="Declare least privilege: start from an EMPTY `permissions:` map and grant only what each job actually needs; scope app tokens; gate `id-token: write` behind an environment; stop persisting credentials.",
    ),
    "WFSEC-004": Issue(
        scanner="workflow-security",
        kind="security-workflow",
        severity="medium",
        title="a workflow depends on a MUTABLE reference in {where}",
        # The pipe-to-shell installer is DESCRIBED, never spelled out. Written literally it is a
        # supply-chain scanner's needle, so a catalog entry ABOUT the attack trips every scanner that
        # reads this file — ours included (it failed our own publish gate). Prose is not a payload, but
        # a matcher cannot tell the difference, so do not hand it one.
        what="A step pulls something that can change under it without the repo changing: an action on a tag or branch, an unpinned Docker image, an unfrozen lockfile, a remote script fetched and piped straight into a shell, or a build that publishes from the same job it built in.",
        why="Tags move. An upstream account takeover or a rewritten tag silently changes what runs in CI — with the repo's secrets — and the diff that would have shown it does not exist, because nothing in the repo changed.",
        fix="Pin it: a full commit SHA (with the version in a trailing comment — `pinact run` automates this), an image digest, a frozen lockfile. What ran yesterday must be what runs today.",
    ),
    "WFSEC-005": Issue(
        scanner="workflow-security",
        kind="security-workflow",
        severity="critical",
        title="a workflow exposes a secret in {where}",
        what="A credential is present where it can escape: hard-coded in the workflow, a static cloud key, a token in a URL or a Docker build-arg, a secret interpolated bare into a `run:` body, or the whole secrets object dumped via `toJSON`.",
        why="A secret in a workflow is a secret in every fork, every log, and every cached layer. Build-args and env dumps end up in artifacts that outlive the run.",
        fix="Move it behind `secrets:` (or OIDC, which mints a short-lived token and stores nothing). If it was ever COMMITTED, it is burned: tell the user to ROTATE it — do not rotate it yourself — and only then remove it and purge it from history.",
    ),
    "WFSEC-006": Issue(
        scanner="workflow-security",
        kind="security-workflow",
        severity="medium",
        title="a workflow's own safety rail is missing or defeated in {where}",
        what="A guard that was supposed to catch failures is absent or neutered: no `timeout-minutes`, an `if:` condition that is always true, `continue-on-error` on a SECURITY step, or a global git config that rewrites what later steps fetch.",
        why="A defeated guard is worse than no guard: the job reports success, the security step's failure is swallowed, and everyone downstream believes the check ran. A hung job with no timeout burns the runner budget until someone notices by hand.",
        fix="Restore the guard — set `timeout-minutes`, make the condition mean something, and let a failing security step FAIL the job. A check whose result is ignored is not a check.",
    ),
    "BRPROT-001": Issue(
        scanner="branch-protection",
        kind="branch-protection",
        severity="high",
        title="the default branch of {slug} is unprotected",
        what="No active ruleset protects the default branch against deletion, force-push, or unreviewed merges.",
        why="A single mistaken force-push rewrites history that other clones have already fetched, and there is no server-side record of what was there before.",
        fix="Apply the ratified baseline ruleset pair (`baseline-history-protect` + `baseline-pr-and-checks`). Applying the baseline AS-IS is pre-approved; any DEVIATION from it needs the user.",
    ),
    "BRPROT-002": Issue(
        scanner="branch-protection",
        kind="branch-protection",
        severity="high",
        title="the branch-protection baseline on {slug} has drifted: {detail}",
        what="A ruleset that was part of the ratified baseline has been weakened, disabled, or given a new bypass actor.",
        why="Protection that silently degrades is worse than none, because everyone still believes the branch is protected.",
        fix="Restore the ruleset to the ratified baseline. If the deviation was deliberate, it needs an explicit decision from the user — do not re-apply over it without asking.",
    ),
    "DEP-001": Issue(
        scanner="supply-chain",
        kind="dependency-advisory",
        severity="high",
        title="{package} {version} carries a known advisory: {advisory}",
        what="An installed dependency matches a published security advisory.",
        why="The vulnerable code is already on disk and in the build. An advisory is public, so exploit code usually is too.",
        fix="Bump to the fixed version and run the project's full test suite. If no fixed version exists, FLAG it for the user with the exposure — never silently pin to a vulnerable release.",
    ),
    "DEP-002": Issue(
        scanner="historical-cache-scan",
        kind="dependency-advisory",
        severity="critical",
        title="a KNOWN-MALICIOUS package version is present: {package} {version}",
        what="A dependency version that was published as malware (a compromised maintainer account, a hijacked release) is in the tree or the package cache.",
        why="This is not a latent vulnerability — it is code that was written to steal credentials, and it may have already run in a postinstall hook.",
        fix="Remove it, purge the package cache, and treat every credential reachable from this machine as potentially exposed. Report to the user IMMEDIATELY — do not quietly bump the version.",
    ),
    "DEP-003": Issue(
        scanner="typosquat-watcher",
        kind="dependency-advisory",
        severity="high",
        title="`{package}` is one edit away from the popular package `{target}`",
        what="A declared dependency's name is within a small edit distance of a widely-used package — the signature of a typosquat.",
        why="Typosquats exist to be installed by accident and to run code at install time. The cost of checking is one lookup; the cost of missing one is a compromised machine.",
        fix="Verify the package is the one that was intended (registry, repo, download counts). If it is a squat, remove it and audit what its install scripts did.",
    ),
    "CRED-001": Issue(
        scanner="remote-credentials",
        kind="leaked-credential",
        severity="critical",
        title="a credential appears to be exposed in {path}",
        what="A high-entropy secret matching a known credential shape is present in a file that is (or could be) committed or transmitted.",
        why="A secret in a repo is a secret in every clone, every fork, and every CI log — forever, even after the commit is 'removed'.",
        fix="FLAG IT — do NOT rotate anything automatically. Confirm whether it is live, tell the user to rotate it, and only then remove it from the file and purge it from history.",
    ),
    "PKGPOL-001": Issue(
        scanner="package-manager-policy",
        kind="github-config",
        severity="medium",
        title="a package-manager safety knob is disabled in {path}: {detail}",
        what="Configuration disables a supply-chain safeguard — lockfile enforcement, integrity checking, or install-script sandboxing.",
        why="These knobs are the only thing standing between a compromised transitive dependency and arbitrary code execution at install time.",
        fix="Restore the safeguard and re-run the install to confirm nothing depended on it being off. If something did, that dependency is the real finding.",
    ),
    "GHCFG-001": Issue(
        scanner="fleet-github-config",
        kind="github-config",
        severity="medium",
        title="the GitHub config of {slug} is off-baseline: {detail}",
        what="A repository's settings, workflows, or rulesets diverge from the ratified fleet baseline.",
        why="Drift accumulates silently until an incident proves the protection everyone assumed was in place is not.",
        fix="Bring the repo back to the baseline. Applying the baseline AS-IS is pre-approved; any deviation from it needs the user's decision.",
    ),
    "AICTX-001": Issue(
        scanner="ai-context-poisoning",
        kind="security-workflow",
        severity="critical",
        title="an agent-context file may be poisoned: {path}",
        what="A file the AI reads as INSTRUCTIONS (CLAUDE.md, a skill, an agent definition, a rule) contains authority impersonation, invisible unicode, or a jailbreak pattern.",
        why="This is the highest-leverage attack on an agentic system: the payload does not exploit the code, it exploits the reader — and the reader has the user's full privileges.",
        fix="Do not 'clean it up' silently. Preserve the file, show the user the exact payload and where it came from, and strip the covert unicode only after they have seen it.",
    ),
    "MCPSEC-001": Issue(
        scanner="mcp-rugpull",
        kind="security-workflow",
        severity="high",
        title="an installed MCP server changed its fingerprint: {server}",
        what="A server's tool definitions or code changed after installation — the rug-pull shape, where a benign server is updated into a malicious one.",
        why="MCP tool descriptions are injected into every turn's context. A server that silently rewrites its own tool descriptions is rewriting the agent's instructions.",
        fix="Diff the old and new definitions, show the user what changed, and do not re-enable the server until they have approved the change.",
    ),
}


# --------------------------------------------------------------------------- #
# raising an issue — the ONE entry point a detector needs
# --------------------------------------------------------------------------- #


class _SafeDict(dict):
    """Missing placeholder → a visible marker, never a KeyError.

    A detector that forgets one `{key}` must not crash the heartbeat: the finding is worth more than
    the formatting. `<?>` is loud enough to be caught in review and harmless in a ticket.
    """

    def __missing__(self, key: str) -> str:  # pragma: no cover - exercised via _render
        return "<?>"


def _render(template: str, data: dict[str, str]) -> str:
    """Fill OUR template with the detector's ALREADY-SANITIZED data. Never formats the data itself."""
    return string.Formatter().vformat(template, (), _SafeDict(data))


def _fields(where: str, data: dict[str, object]) -> dict[str, str]:
    """Sanitize every value a detector interpolates. The ONE place untrusted text is defanged."""
    fields = {k: tickets._clean(str(v), 200) for k, v in data.items()}
    fields["where"] = tickets._clean(where, 200)
    return fields


def _finding_key(code: str, issue: Issue, fields: dict[str, str], dedupe_key: str) -> str:
    """The identity of ONE finding: per code + LOCATION.

    The same defect found on every fire is ONE ticket; the same defect in two different files is
    genuinely two. `raise_issue` and `clear_issue` MUST derive this identically — a clear that
    computed the key even slightly differently would silently never match, and the retract would look
    like it worked while the proposal stayed on the board forever.
    """
    return dedupe_key or f"{code}:{fields['where'] or _render(issue.title, fields)}"


@dataclass(frozen=True)
class Raised:
    """The outcome of `raise_issue`. `line` is a ready-to-print heartbeat line (empty when silent).

    The two domains are deliberately NOT symmetric about that line, because only one of them can act:

      HARNESS — announced ONCE, on open. The janitor is about to fix it itself; repeating the line
                every five minutes would be pure nag, and a nag that recurs forever trains its reader
                to ignore it.
      PROJECT — re-announced on EVERY raise, until someone approves. Nothing is fixed until the main
                Claude runs the command, so a reminder that stops is a finding silently dropped — and
                the one line that WAS printed may well have landed inside a compaction. The user asked
                for exactly this: "proactively recommend and remind".

    `first_seen` tells a caller which raise actually created something, so a detector with its own
    cadence can still choose to be quieter than this default.
    """

    code: str
    domain: str
    ok: bool
    ticket_id: str = ""
    trdd: str = ""
    command: str = ""
    line: str = ""
    why: str = ""
    first_seen: bool = False


def raise_issue(
    code: str,
    *,
    evidence: list[str] | None = None,
    severity: str = "",
    dedupe_key: str = "",
    where: str = "",
    origin: str = "",
    project_dir: str | None = None,
    now: int | None = None,
    **data: object,
) -> Raised:
    """Turn a detected issue into WORK. The one call a detector makes; the code decides everything else.

    HARNESS codes open (and later dispatch) a ticket unattended — the janitor repairing its own
    machinery. PROJECT codes only author a proposal TRDD and hand back the exact approval command; no
    ticket exists, and nothing is dispatched, until a human or the main Claude runs it.

    Every `**data` value is sanitized before it touches a template, so a detector may pass a filename,
    a dependency name, or a workflow line straight from an attacker-influenceable source.
    """
    issue = ISSUE_CATALOG.get(code)
    if issue is None:
        # Fail LOUD but not fatal: a typo'd code must not silently swallow a real finding.
        return Raised(code=code, domain="", ok=False, why=f"unknown issue code `{tickets._clean(code, 24)}`")

    fields = _fields(where, data)
    title = _render(issue.title, fields)

    parts = [
        f"**{code}** ({issue.scanner}, severity `{severity or issue.severity}`)",
        "",
        f"**What:** {issue.what}",
        "",
        f"**Why it matters:** {issue.why}",
        "",
        f"**Fix to attempt:** {issue.fix}",
    ]
    # `found` carries THIS occurrence's specifics — the rule ids, the files, the lines. It is passed
    # as data (already sanitized) rather than rendered into the templates, because `what` and `fix`
    # quote real Actions syntax (`${{ github.event.* }}`) and running them through a formatter would
    # eat the braces and leave the ticket teaching the agent a syntax that does not exist.
    if fields.get("found"):
        parts += ["", f"**Found:** {fields['found']}"]
    detail = "\n".join(parts)
    key = _finding_key(code, issue, fields, dedupe_key)
    ev = list(evidence or [])
    org = origin or issue.scanner
    kind_spec = tickets.KIND_REGISTRY[issue.kind]

    if kind_spec.domain == tickets.HARNESS:
        t, why = tickets.open_ticket(
            kind=issue.kind,
            title=title,
            detail=detail,
            evidence=ev,
            severity=severity or issue.severity,
            dedupe_key=key,
            origin=org,
            now=now,
        )
        if t is None:
            return Raised(code=code, domain=tickets.HARNESS, ok=False, why=why)
        first_time = why.startswith("opened")
        line = f"[ticket] {code} {t.id} ({t.severity}): {title} — the janitor will repair this itself" if first_time else ""
        return Raised(code=code, domain=tickets.HARNESS, ok=True, ticket_id=t.id, line=line, why=why, first_seen=first_time)

    proposed = ticket_proposal.propose(
        kind=issue.kind,
        title=title,
        detail=detail,
        evidence=ev,
        severity=severity or issue.severity,
        dedupe_key=key,
        origin=org,
        project_dir=project_dir,
        now=now,
    )
    if proposed is None:
        # The finding is ALREADY an open ticket — approved, and the queue owns it now. Silence here is
        # correct: re-recommending a fix that is already scheduled would be noise.
        return Raised(code=code, domain=tickets.PROJECT, ok=True, why="already an open ticket")
    uid, command, is_new = proposed
    line = f"[ticket] {code} ({severity or issue.severity}): {title} — approve the fix with: {command}"
    return Raised(
        code=code,
        domain=tickets.PROJECT,
        ok=True,
        trdd=uid,
        command=command,
        line=line,
        why="proposed" if is_new else "already proposed — still awaiting approval",
        first_seen=is_new,
    )


def clear_issue(
    code: str,
    *,
    where: str = "",
    dedupe_key: str = "",
    project_dir: str | None = None,
    **data: object,
) -> str | None:
    """The finding is GONE — withdraw its unapproved proposal. Returns the withdrawn TRDD id, or None.

    Call this on the path where a detector can PROVE the condition is absent (the ruleset is back, the
    advisory is gone, the workflow was fixed by hand). Pass the SAME `code` + `where`/`dedupe_key` the
    raise used — the key is derived by the same function, so they cannot drift apart.

    It only ever touches an UNAPPROVED proposal, and that asymmetry is deliberate in both directions:

      PROJECT — nothing has happened yet. No ticket, no agent, no work. Withdrawing the proposal costs
                nothing and keeps the user's git-tracked board honest.
      HARNESS — an OPEN harness ticket is NEVER cancelled by a clear, even though it would be easy and
                would save a dispatch. That is precisely the trap this whole subsystem exists to avoid:
                the memgrep self-heal RACES any observer and wins, so a harness incident "clearing" is
                usually the damage being papered over, not repaired. Cancelling the ticket on that
                signal would reconstruct the exact blind spot that let the migration bug hide for days.
                An opened harness incident gets worked; the agent decides whether it was real.
    """
    issue = ISSUE_CATALOG.get(code)
    if issue is None or tickets.KIND_REGISTRY[issue.kind].domain != tickets.PROJECT:
        return None
    key = _finding_key(code, issue, _fields(where, data), dedupe_key)
    return ticket_proposal.retract(key, project_dir=project_dir)


def reconcile(
    code: str,
    live_wheres: Iterable[object],
    *,
    project_dir: str | None = None,
) -> list[str]:
    """Withdraw every proposal for `code` whose finding is NO LONGER THERE. Returns the withdrawn ids.

    `clear_issue` answers "this exact finding is gone" — which only works when the detector can still
    NAME the finding it wants to clear. Most scanners cannot: a scan produces the findings that EXIST,
    and the ones that vanished are, by definition, not in the result. Asking such a detector to clear
    what it no longer sees is asking it to remember every string it has ever emitted.

    So invert it. The detector passes the `where` of every finding it found THIS run, and anything else
    on the board under this code is stale by construction. That is also why it is one pass over the
    proposals rather than one pass per finding: a lockfile with 800 dependencies must not re-read the
    whole design board 800 times to discover that 799 of them are fine.

    Call it on EVERY run, including the clean one (with an empty set) — a scanner that only reconciles
    when it finds something can never withdraw its last proposal, which is precisely the one that
    matters.
    """
    issue = ISSUE_CATALOG.get(code)
    if issue is None or tickets.KIND_REGISTRY[issue.kind].domain != tickets.PROJECT:
        return []
    live = {_finding_key(code, issue, _fields(str(w), {}), "") for w in (live_wheres or [])}
    prefix = f"{code}:"
    withdrawn: list[str] = []
    for p in ticket_proposal.pending(project_dir):
        if not p.key.startswith(prefix) or p.key in live:
            continue
        uid = ticket_proposal.retract(p.key, project_dir=project_dir)
        if uid:
            withdrawn.append(uid)
    return withdrawn


def issue_domain(code: str) -> str:
    """The domain a code resolves to, or `""` for an unknown code. For docs + tests."""
    issue = ISSUE_CATALOG.get(code)
    return tickets.KIND_REGISTRY[issue.kind].domain if issue else ""


def scanners() -> list[str]:
    """Every scanner that has at least one code, sorted. The coverage handle."""
    return sorted({i.scanner for i in ISSUE_CATALOG.values()})
