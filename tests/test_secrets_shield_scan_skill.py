"""The janitor-secrets-shield-scan skill documents exactly the options of the scan CLI.

TRDD-BAQB9SYO increment 1c. The skill text is read by an agent that passes options to
scripts/shield_scan/scan.ts; an option the CLI gained but the skill never named is invisible
to that agent, and an option the skill names but the CLI dropped makes the agent run a command
that exits 2. Only the "## Options" section of SKILL.md is compared, so flags named elsewhere
in the skill (examples, a later --history) do not break the test.
"""

from __future__ import annotations

import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SKILL = _PROJECT_ROOT / "skills" / "janitor-secrets-shield-scan" / "SKILL.md"
_SCAN = _PROJECT_ROOT / "scripts" / "shield_scan" / "scan.ts"


def _section(text: str, heading: str) -> str:
    """Return the body of `## <heading>` up to the next line starting with `## `."""
    lines = text.splitlines()
    assert heading in lines, f"{_SKILL}: no `{heading}` section"
    body: list[str] = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def _parse_args_source(text: str) -> str:
    """Return the source of parseArgs in scan.ts, from its declaration to the root checks."""
    start = text.index("function parseArgs(")
    end = text.index("opts.root = realpathSync", start)
    return text[start:end]


def test_options_section_matches_the_cli_options() -> None:
    """The `--flag` tokens of the skill `## Options` section equal the `case '--...'` labels of parseArgs."""
    in_skill = set(re.findall(r"--[a-z][a-z-]*", _section(_SKILL.read_text(encoding="utf-8"), "## Options")))
    in_cli = set(re.findall(r"case '(--[a-z][a-z-]*)':", _parse_args_source(_SCAN.read_text(encoding="utf-8"))))
    assert in_cli, "no case labels found in parseArgs of scan.ts: the parser of this test is stale"
    assert in_skill == in_cli, f"documented but not in the CLI: {sorted(in_skill - in_cli)}; in the CLI but not documented: {sorted(in_cli - in_skill)}"


def test_exit_codes_section_names_every_exit_code() -> None:
    """The `## Exit codes` section names the codes 0, 1, 2 and 3 of the scan CLI."""
    body = _section(_SKILL.read_text(encoding="utf-8"), "## Exit codes")
    named = set(re.findall(r"^- (\d):", body, flags=re.MULTILINE))
    assert named == {"0", "1", "2", "3"}, f"exit codes named in the skill: {sorted(named)}"
