"""Table-driven detector: a dependency CLI that writes agent-context files without consent.

Vector (Emasoft/ai-maestro-janitor#110, reported by the AgentlensPro Claude). A package such
as ``playwright`` ships a subcommand — ``playwright init-agents`` — that transcribes its own
agent definitions into whichever coding agent you use, WITHOUT confirmation:

    claude   → .claude/agents/*.md, .mcp.json
    copilot  → .github/agents/*.agent.md, .github/workflows/copilot-setup-steps.yml
    opencode → .opencode/prompts/*.md, opencode.json
    vscode   → .github/chatmodes/*.chatmode.md, .vscode/mcp.json

The bare form (no ``--loop``) falls through to the Copilot generator, so it can even
introduce a **GitHub Actions workflow**. Installing the package triggers nothing (its
``package.json`` has empty ``scripts``) — the COMMAND is the only trigger. So the guard binds
the TOOL layer: it stops an *agent* from silently running the command; a human typing it is a
deliberate act, out of scope.

Why the janitor owns this and not the tool: the exposed population installs a CLI from npm and
runs it inside their OWN projects — a repo-scoped ``.claude/settings.json`` reaches only the
handful who clone that one repo, and protects none of the OTHER projects on the machine, which
is where the hazard lives. The janitor is the only component installed at USER scope,
machine-wide, whose domain this is.

Two mistakes the AgentlensPro reference impl already paid for, encoded here as invariants:

  1. **MATCH ON TOKENS, NEVER SUBSTRINGS.** A substring regex (``\\bplaywright\\b.*\\binit-agents\\b``)
     blocked ``git add scripts/deny-playwright-init-agents.js`` — the guard's OWN filename
     carries both words, so the control could not even be committed, and it blocked writing any
     file whose text quoted the command. We split the command into shell segments, tokenize
     each **quote-aware** (via ``shlex`` — so ``git commit -m "add playwright init-agents guard"``
     stays ONE token and is NOT mistaken for the binary + subcommand, the same lesson applied to
     commit messages), and require a token whose **basename** is the binary followed LATER by
     the subcommand token. That matches ``npx playwright init-agents``,
     ``pnpm exec playwright init-agents``, ``./node_modules/.bin/playwright init-agents`` and a
     bare ``playwright init-agents``, while a hyphen-joined path (``deny-playwright-init-agents.js``,
     basename != the binary) never matches.

  2. **AN UNREADABLE PAYLOAD MUST ALLOW** — enforced by the hook: a guard that denies every
     ``Bash`` call because it could not parse its own stdin is worse than the thing it guards.
     Here that shows up as *fail-open on malformed quoting*: ``shlex`` raising falls back to the
     literal split, and a non-string / empty command returns ``None``.

``playwright`` is row one, not the feature. The durable primitive is the TABLE below — one
generated deny rule over it — so the next offender is a DATA change, not new code.

Deliberate conservatism (recall over precision, per the AgentlensPro contract): the subcommand
need only appear LATER in the same segment, so ``playwright test init-agents`` (a test-name
filter) is also blocked. Over-blocking a rare, benign form is the cheap failure — the hook's
deny message names the per-project opt-out — whereas letting the real generator through is not.
"""

from __future__ import annotations

import posixpath
import re
import shlex
from typing import NamedTuple, Optional


class AgentContextWriter(NamedTuple):
    """One known offender: the binary + the subcommand that triggers the write, plus the
    agent-context paths it writes (informational — used only in the deny message and docs)."""

    package: str
    subcommand: str
    writes: tuple[str, ...]


# THE TABLE. Add the next offender as a DATA row — no new code, no new hook.
AGENT_CONTEXT_WRITERS: tuple[AgentContextWriter, ...] = (
    AgentContextWriter(
        package="playwright",
        subcommand="init-agents",
        writes=(
            ".claude/agents/*.md",
            ".claude/prompts/",
            ".mcp.json",
            ".github/agents/*.agent.md",
            ".github/workflows/copilot-setup-steps.yml",
            ".opencode/prompts/*.md",
            "opencode.json",
            ".github/chatmodes/*.chatmode.md",
            ".vscode/mcp.json",
        ),
    ),
)

# Shell operator tokens that bound one command inside a compound line. Splitting on them keeps
# a token from segment A from ever pairing with one from segment B — so `playwright test &&
# echo init-agents` is TWO segments and matches neither.
_OPERATOR_TOKENS = frozenset({"|", "||", "&", "&&", ";", ";;", "|&"})

# Fallback separators (used only when shlex cannot parse the command's quoting).
_SEGMENT_SEP_RE = re.compile(r"[;&|\n]+")
_STRIP_QUOTES = "\"'"


def _segments(command: str) -> list[list[str]]:
    """Return COMMAND's shell token SEGMENTS (a list of token lists), split at shell
    operators. Quote-aware via ``shlex``; on a quoting error it degrades to the literal
    separator/whitespace split rather than raising (fail-open)."""
    try:
        toks = shlex.split(command, comments=False, posix=True)
    except ValueError:
        # Unbalanced quoting → conservative literal fallback (never raise).
        out: list[list[str]] = []
        for seg in _SEGMENT_SEP_RE.split(command):
            naive = [t.strip(_STRIP_QUOTES) for t in seg.split() if t]
            if naive:
                out.append(naive)
        return out

    segments: list[list[str]] = []
    current: list[str] = []
    for tok in toks:
        if tok in _OPERATOR_TOKENS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    return segments


def _segment_invokes(tokens: list[str], writer: AgentContextWriter) -> bool:
    """True iff TOKENS invoke WRITER: a token whose BASENAME is the binary, followed LATER by
    the subcommand token in the same segment. Basename-match is what lets
    ``deny-playwright-init-agents.js`` pass while ``./node_modules/.bin/playwright`` matches."""
    for i, tok in enumerate(tokens):
        if tok and posixpath.basename(tok) == writer.package and writer.subcommand in tokens[i + 1:]:
            return True
    return False


def command_invokes_agent_writer(command: str) -> Optional[AgentContextWriter]:
    """The ``AgentContextWriter`` a shell COMMAND invokes, or ``None``.

    PURE + total: no I/O, never raises. A non-string / empty command returns ``None`` (the
    hook owns the fail-open stdin contract; this stays defensive too)."""
    if not command or not isinstance(command, str):
        return None
    for tokens in _segments(command):
        for writer in AGENT_CONTEXT_WRITERS:
            if _segment_invokes(tokens, writer):
                return writer
    return None
