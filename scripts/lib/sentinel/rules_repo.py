# Repo-level Sentinel rules — checks that span the whole repository rather
# than a single workflow file. A RegexSet / per-file Rule cannot express
# "no workflow ANYWHERE runs zizmor", so these run once over the collected
# text of every workflow. Mirrors how the Sentinel reference handles
# missing-zizmor / missing-dependabot at the scanner level (not as per-file
# Workflow rules).
#
# Each callable takes the list of raw workflow texts and returns a list of
# Findings. scripts/doctor_classify.py runs REPO_RULES once after the
# per-file passes.

from __future__ import annotations

import re

from lib.sentinel.model import SEV_MINOR
from lib.zizmor_classifier import Finding

_ZIZMOR = re.compile(r"\bzizmor\b", re.IGNORECASE)


def missing_zizmor(workflow_texts: list[str]) -> list[Finding]:
    """Repo-level: no workflow runs the zizmor static analyzer anywhere.

    Detecting zizmor by a bare token match is deliberate — it catches both
    the action form (`uses: zizmorcore/zizmor-action`) and the run form
    (`run: zizmor .`) without enumerating every spelling.
    """
    if any(_ZIZMOR.search(text) for text in workflow_texts):
        return []
    return [Finding(
        rule_id="missing-zizmor",
        line=1,
        col=1,
        matched_text="",
        severity=SEV_MINOR,
        description=(
            "No workflow runs the zizmor static analyzer — add a CI job that "
            "runs zizmor on every PR so GitHub Actions security regressions "
            "are caught automatically, not only on a manual audit."
        ),
    )]


# Ordered list of repo-level rules the doctor runs once over all workflows.
REPO_RULES = [missing_zizmor]
