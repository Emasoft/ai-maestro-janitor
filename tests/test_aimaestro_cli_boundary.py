"""The ai-maestro boundary is the SCRIPTS, never the HTTP API (owner directive 2026-08-02).

IRON RULE, and it has two halves. The first is the prohibition: no plugin element may call
`/api/*` or `:23000` directly, from any surface. The second is the one that is easy to skip and
is the reason this file exists — **every skill that touches the boundary must SAY so.** Merely
not violating it is not compliance: a skill that names `aimaestro-agent.sh` without stating that
the API is forbidden lets the next agent read the script as one option among several.

ai-maestro's own audit (janitor#166) found the janitor clean on the first half. It could not
check the second, because "does this skill instruct?" is not greppable as an absence — which is
exactly why it is pinned here.

Note for whoever runs a similar audit: do NOT trust `grep -r --include`. ai-maestro reported a
positive control with `--include=*.cjs` returning `LICENSE` and `.cspell.json`, and their first
pass produced 38 API references that were ALL false. These tests enumerate with pathlib and read
each file.
"""

from __future__ import annotations

import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The frozen CLI families that ARE the sanctioned boundary.
_CLI_RE = re.compile(r"\b(?:aimaestro|amp|aid)-[a-z0-9-]+\.sh\b")

# A direct call at AI-MAESTRO's HTTP surface — its port, or an `/api/` path on the loopback
# host it serves from. Scoped this tightly on purpose, and the first draft proves why: matching
# any `https?://…/api/` flagged `api.anthropic.com/api/oauth/usage` and `crates.io/api/v1/…`,
# which are unrelated third-party APIs the janitor legitimately calls. That is the same
# all-false result ai-maestro measured with `grep -r --include` (janitor#166) — an over-broad
# audit pattern does not find more violations, it finds none and buries the real ones.
_API_RE = re.compile(
    r"(?::23000\b"
    r"|https?://(?:127\.0\.0\.1|localhost|\[::1\])[:/][^\s\"']*/api/"
    r"|\"/api/(?:agents|oauth/usage-local|statusline|teams)\b)"
)

# A line that FORBIDS the API necessarily names it. `"never call /api/*"` is compliance, not a
# violation — the question these tests ask is "does this teach the agent to make the call?", and
# a prohibition teaches the opposite. Without this, the iron-rule text fails its own test.
_PROHIBITION_RE = re.compile(r"MUST NOT|never|forbidden|do not call", re.IGNORECASE)

_EXEMPT_DIRS = ("scripts/lib", "tests", "reports", "design", "docs", "_corpus_dev")


def _executable_surfaces() -> list[Path]:
    """Every file that could actually PERFORM a call: detectors, hooks, top-level scripts."""
    out: list[Path] = []
    for sub in ("scripts/detectors", "scripts/hooks", "scripts/oauth_rotator"):
        out.extend(sorted((_PROJECT_ROOT / sub).glob("*.py")))
    out.extend(sorted((_PROJECT_ROOT / "scripts").glob("*.py")))
    return out


def _markdown_surfaces() -> list[Path]:
    """Skills, agents, commands — the prose an agent reads and acts on."""
    out: list[Path] = []
    for sub in ("skills", "agents", "commands"):
        d = _PROJECT_ROOT / sub
        if d.is_dir():
            out.extend(sorted(d.rglob("*.md")))
    return out


def test_no_executable_surface_calls_the_api_directly() -> None:
    """Half one. A detector, hook, or script that curls the API bypasses the versioned
    boundary and breaks on any internal route change."""
    offenders: list[str] = []
    for p in _executable_surfaces():
        rel = p.relative_to(_PROJECT_ROOT).as_posix()
        if any(rel.startswith(d) for d in _EXEMPT_DIRS):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _API_RE.search(line) and not _PROHIBITION_RE.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not offenders, (
        "direct ai-maestro API call(s) — use the frozen CLI (aimaestro-*.sh / amp-*.sh / "
        "aid-*.sh); a missing verb is a gap to REPORT, not to bypass:\n" + "\n".join(offenders)
    )


def test_no_skill_or_agent_markdown_embeds_api_syntax() -> None:
    """Half one, prose edition. API syntax in a skill teaches the agent to make the call —
    the instruction is the vulnerability, even though the markdown executes nothing."""
    offenders: list[str] = []
    for p in _markdown_surfaces():
        rel = p.relative_to(_PROJECT_ROOT).as_posix()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _API_RE.search(line) and not _PROHIBITION_RE.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not offenders, (
        "ai-maestro API syntax embedded in agent-facing markdown:\n" + "\n".join(offenders)
    )


def test_every_skill_naming_the_cli_also_states_the_boundary() -> None:
    """Half TWO — the half that is not a greppable absence, and the owner's actual words:
    *"all plugins must instruct in their skills to use the ai-maestro scripts, never the api
    directly"*.

    A skill that routes through `aimaestro-agent.sh` without saying the API is forbidden has
    not complied; it has merely not offended. The next agent reading it sees one option among
    several and picks whichever is convenient — which is how a boundary erodes without anyone
    deciding to cross it."""
    silent: list[str] = []
    for p in _markdown_surfaces():
        text = p.read_text(encoding="utf-8")
        if not _CLI_RE.search(text):
            continue  # does not touch the boundary — nothing to state
        # The instruction must name the prohibition, not merely mention the API in passing.
        if not re.search(r"never its HTTP API|never the API|MUST NOT call", text):
            silent.append(p.relative_to(_PROJECT_ROOT).as_posix())
    assert not silent, (
        "these skills route through the ai-maestro CLI but never state that the API is "
        "forbidden — not offending is not the same as instructing:\n  " + "\n  ".join(silent)
    )
