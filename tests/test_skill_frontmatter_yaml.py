"""Every shipped SKILL.md must carry frontmatter that parses as YAML.

Guardrail for a publish-blocking CPV CRITICAL ("Malformed YAML frontmatter") that shipped in
commit ede9bdb4: a `description:` written as a plain scalar contained `Plan-first: shows …`,
and an unquoted `: ` inside a plain scalar turns the value into a nested mapping — invalid
YAML, invisible to every local gate because nothing here parsed the frontmatter. CPV only
runs at publish time, so the defect surfaced after the work "looked done". This test runs a
`yaml.safe_load` of every skill's frontmatter locally, so the next such typo fails `pytest`,
not the release. It checks ONLY that the frontmatter parses and `description` is a string —
no naming convention is enforced here; CPV owns the rest of the skill schema.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SKILLS = sorted((_PROJECT_ROOT / "skills").glob("*/SKILL.md"))


def _frontmatter(text: str) -> str:
    assert text.startswith("---\n"), "frontmatter must open with `---` on line 1"
    end = text.find("\n---", 4)
    assert end > 0, "frontmatter must close with a `---` line"
    return text[4:end]


@pytest.mark.parametrize("skill", _SKILLS, ids=lambda p: p.parent.name)
def test_skill_frontmatter_is_valid_yaml_with_name_and_description(skill: Path) -> None:
    """Each skills/<name>/SKILL.md frontmatter parses as a YAML mapping whose `description`
    is a non-empty string (not a nested mapping)."""
    data = yaml.safe_load(_frontmatter(skill.read_text(encoding="utf-8")))
    assert isinstance(data, dict), f"{skill}: frontmatter is not a mapping"
    desc = data.get("description")
    assert isinstance(desc, str) and desc.strip(), (
        f"{skill}: description must be a plain non-empty string — an unquoted `: ` inside it "
        f"parses as a nested mapping; got {type(desc).__name__}"
    )


def test_the_skill_corpus_is_not_empty() -> None:
    """The glob must find the shipped skills, or the parametrized test above passes vacuously."""
    assert len(_SKILLS) >= 50, f"only {len(_SKILLS)} SKILL.md found under skills/"
