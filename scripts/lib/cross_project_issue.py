"""File a finding as an issue on the repo it BELONGS to (TRDD-WP7TCRME, Rule 4).

The janitor runs in every project on the machine, so it routinely detects a problem that
belongs to a DIFFERENT repo. Telling the current project's Claude about it is the worst of
both worlds: that session cannot fix another repo (the cross-project rule forbids it), the
finding interrupts work it is unrelated to, and it costs tokens on the turn it lands AND on
every later turn, since the transcript is re-read. Meanwhile the repo that has the problem is
never told.

So the finding goes where it can be acted on. When the affected repo is one the USER OWNS, a
script opens the issue there directly — no model turn, no interruption of an unrelated
session.

THREE THINGS THIS REFUSES TO DO, each because the alternative is worse than silence:

  * **Never file on a repo the user does not own.** Ownership is decided by comparing the
    repo's owner against the authenticated `gh` login. A janitor that opens issues on
    strangers' repositories is a spam bot wearing the owner's identity, and the identity is
    shared across every agent on this machine.
  * **Never file twice.** Every issue carries a hidden marker keyed to the finding, and the
    filer searches for it first. A detector fires every cadence forever; without this, one
    persistent condition becomes one issue per fire — which is how an automated reporter
    destroys the tracker it was meant to help.
  * **Never `@`-mention.** Bodies are built from a template that carries no `@` at all. A bare
    `@name` outside a code span PAGES a real account, and templates are copied verbatim into
    places where that is not obvious (janitor#171 — a template shipped `@owner` inside a code
    span for months and still paged a real org once someone quoted it).

The self-identification line is PRRD G1.1: every AI Maestro agent writes to GitHub through the
same human owner's auth, so a post that does not say which agent wrote it is indistinguishable
from the human writing it by hand.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import env_detect  # noqa: E402
import state  # noqa: E402

__all__ = [
    "build_body",
    "dedupe_marker",
    "defang_mentions",
    "file_finding",
    "is_owned_by",
    "repo_slug_for",
]

# A bare `@name` at a WORD BOUNDARY pages a real GitHub account; the same token inside a code
# span does not (`~/.claude/rules/github-mentions.md`, measured with `gh api markdown`). The
# lookbehind excludes both an address' local part (`user@host` never pages) and a token already
# opened by a backtick, so re-wrapping cannot nest.
_MENTION_RE = re.compile(r"(?<![\w`@])@([A-Za-z0-9][A-Za-z0-9-]{0,38})")


def defang_mentions(text: str) -> str:
    """`text` with every bare `@name` wrapped in backticks, so it names without PAGING.

    The module docstring promises this file never `@`-mentions, but only the TEMPLATE was ever
    `@`-free: `detail` and `title` are caller-supplied and interpolated verbatim, so a finding
    built from an issue title, a workflow string, or a pasted log carries whatever `@` it found.
    And this posts through `subprocess`, NOT the Bash tool — so `pre-bash-safety.
    check_outbound_publication`, the PreToolUse guard that would have caught it, never sees the
    command at all. The promise has to be kept HERE or it is not kept.
    """
    return _MENTION_RE.sub(lambda m: f"`@{m.group(1)}`", text)

# The hidden marker that makes a re-file detectable. An HTML comment so it is invisible in the
# rendered issue but exactly greppable through the search API — the issue TITLE is not usable
# for this, because a human editing the title would silently un-dedupe the finding forever.
_MARKER = "<!-- janitor-finding: {key} -->"


def dedupe_marker(code: str, key: str) -> str:
    """The stable identity of ONE finding, as it is embedded in the issue body.

    `key` must name the specific condition, not just its class — two different unpinned
    actions in one repo are two findings and deserve two issues, while the SAME one seen on
    500 consecutive fires is one.
    """
    safe = "".join(ch if ch.isalnum() or ch in "-._/@" else "-" for ch in f"{code}:{key}")
    return _MARKER.format(key=safe)


def repo_slug_for(project_dir: str | os.PathLike[str]) -> str:
    """`owner/repo` for a project's `origin`, or "" when it has none / is not GitHub."""
    proc = state.run_subprocess(
        ["git", "-C", str(project_dir), "remote", "get-url", "origin"],
        timeout=8,
        detector_name="cross-project-issue",
    )
    if proc is None or proc.returncode != 0:
        return ""
    return env_detect.github_slug(proc.stdout.strip()) or ""


def is_owned_by(slug: str, login: str) -> bool:
    """True iff `slug`'s owner is exactly `login` (case-insensitive).

    A prefix or substring test would be a real hazard here: `emasoft-labs/x` is not
    `emasoft/x`, and filing on the wrong account under the owner's shared auth is the failure
    this whole check exists to prevent. Empty inputs are never owned.
    """
    if not slug or not login or "/" not in slug:
        return False
    return slug.split("/", 1)[0].strip().lower() == login.strip().lower()


def gh_login() -> str:
    """The authenticated gh username, or "" when gh is absent/logged out."""
    proc = state.run_subprocess(
        ["gh", "api", "user", "--jq", ".login"], timeout=15, detector_name="cross-project-issue"
    )
    if proc is None or proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def build_body(*, code: str, key: str, detail: str, detector: str, observed_in: str) -> str:
    """The issue body: self-ID, the finding, and the hidden dedupe marker.

    `observed_in` names the project that OBSERVED the problem, which is often not this repo —
    without it the reader cannot tell whether the janitor was running here or elsewhere, and
    that is the first question they will ask.
    """
    return "\n".join([
        "_Posted by the ai-maestro-janitor plugin running in another workdir "
        "(via the shared owner gh auth)._",
        "",
        f"## {code}",
        "",
        defang_mentions(detail.strip()),
        "",
        f"- detector: `{detector}`",
        f"- observed by a janitor running in: `{observed_in}`",
        "",
        "This issue was opened automatically because the finding belongs to THIS repo, not to "
        "the project whose session detected it. It is filed once per distinct finding; a "
        "recurring detector will not reopen it.",
        "",
        dedupe_marker(code, key),
    ])


def _already_filed(slug: str, marker: str) -> bool | None:
    """True/False, or None when the answer is UNKNOWN (search failed).

    Three-valued on purpose. A failed search must NOT read as "not filed": that is precisely
    the state in which filing again is wrong, and a transient network error would otherwise
    reopen an issue on every fire until someone noticed.

    THE SEARCH IS A PRE-FILTER, NEVER THE VERDICT. `--search` runs GitHub's full-text query,
    which TOKENIZES: `<!--` and `-->` are noise, `janitor-finding:` reads as a qualifier
    attempt, and the remaining words match any issue that shares them. Asking only for
    `number` and calling a non-empty list "already filed" therefore reports EVERY janitor
    finding on a repo as a duplicate of the first one ever filed there — a permanent, silent
    suppression of every later, distinct finding. So we fetch the BODY and require the exact
    marker substring; the search only narrows what we have to read.
    """
    proc = state.run_subprocess(
        ["gh", "issue", "list", "--repo", slug, "--state", "all", "--limit", "100",
         "--search", marker, "--json", "number,body"],
        timeout=30,
        detector_name="cross-project-issue",
    )
    if proc is None or proc.returncode != 0:
        return None
    try:
        issues = json.loads(proc.stdout or "[]")
    except (ValueError, TypeError):
        return None
    if not isinstance(issues, list):
        return None
    return any(isinstance(i, dict) and marker in str(i.get("body") or "") for i in issues)


def file_finding(
    *,
    slug: str,
    code: str,
    key: str,
    title: str,
    detail: str,
    detector: str,
    observed_in: str,
    login: str | None = None,
    runner=None,
) -> tuple[str, str]:
    """File the finding on `slug`. Returns `(outcome, detail)`; NEVER raises.

    Outcomes: `filed` · `duplicate` · `not-owned` · `unknown` (search failed — deliberately
    does not file) · `error`.
    """
    who = gh_login() if login is None else login
    if not is_owned_by(slug, who):
        return ("not-owned", f"{slug} is not owned by {who or '(no gh login)'}")

    marker = dedupe_marker(code, key)
    seen = _already_filed(slug, marker)
    if seen is None:
        return ("unknown", "could not search existing issues — not filing (a failed search is "
                           "not evidence that nothing was filed)")
    if seen:
        return ("duplicate", f"already filed on {slug}")

    body = build_body(code=code, key=key, detail=detail, detector=detector,
                      observed_in=observed_in)
    run = runner if runner is not None else state.run_subprocess
    proc = run(
        ["gh", "issue", "create", "--repo", slug, "--title", defang_mentions(title), "--body", body],
        timeout=60,
        detector_name="cross-project-issue",
    )
    if proc is None or getattr(proc, "returncode", 1) != 0:
        return ("error", "gh issue create failed")
    return ("filed", (getattr(proc, "stdout", "") or "").strip())
