#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "google-re2>=1.1",
#   "pyyaml>=6.0",
# ]
# ///
"""Doctor's second-pass workflow classifier — CLI driver.

Reads every workflow file under .github/workflows/ and runs two
detection tiers, emitting findings as JSON-lines on stdout:
  1. the single-pass google-re2 RegexSet matcher from
     scripts/lib/zizmor_classifier.py (regex-amenable rules), and
  2. the structural rules from scripts/lib/sentinel/ (rules that need
     job/step/trigger context or absence checks a RegexSet cannot
     express).
The doctor skill consumes this output between zizmor's SARIF pass and
the per-finding fix pass.

Why a separate CLI driver:
  - The skill is a markdown document; it cannot import Python directly.
  - PEP 723 declares google-re2 as a uv dependency so `uv run` callers
    get the fast path on first invocation.
  - JSON-lines output is trivially streamable into the skill's existing
    classification step.

Output shape (one per line):
  {"file": "...", "rule_id": "...", "line": N, "col": N,
   "severity": "...", "description": "...", "matched_text": "..."}

Exit codes:
  0 — zero findings.
  1 — at least one finding emitted.
  2 — no .github/workflows/ or no .yml files.
  3 — internal error (printed to stderr).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    project_root = Path.cwd()
    workflows_dir = project_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        print(f"[FAILED] no .github/workflows/ under {project_root}", file=sys.stderr)
        return 2

    files = sorted(p for p in workflows_dir.glob("*.yml") if p.is_file())
    if not files:
        print(f"[FAILED] no .yml files in {workflows_dir}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(project_root / "scripts"))
    from lib.sentinel.model import Workflow  # noqa: E402
    from lib.sentinel.rules_absence import RULES as _ABSENCE_RULES  # noqa: E402
    from lib.sentinel.rules_context import RULES as _CONTEXT_RULES  # noqa: E402
    from lib.sentinel.rules_injection import RULES as _INJECTION_RULES  # noqa: E402
    from lib.zizmor_classifier import Classifier  # noqa: E402

    structural_rules = [*_ABSENCE_RULES, *_CONTEXT_RULES, *_INJECTION_RULES]

    def emit(rel_path: Path, finding) -> None:
        print(json.dumps({
            "file": str(rel_path),
            "rule_id": finding.rule_id,
            "line": finding.line,
            "col": finding.col,
            "severity": finding.severity,
            "description": finding.description,
            "matched_text": finding.matched_text,
        }, ensure_ascii=False))

    classifier = Classifier()
    finding_count = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(project_root)

        # Tier 1 — regex RegexSet.
        for finding in classifier.classify(text):
            emit(rel, finding)
            finding_count += 1

        # Tier 2 — structural rules. One rule raising on a pathological
        # workflow must not blind the auditor to every other rule/file, so
        # each rule is isolated (mirrors the Sentinel rule-engine contract
        # and the janitor's cron hot-path resilience).
        wf = Workflow(str(rel), text)
        for rule in structural_rules:
            try:
                rule_findings = rule.check(wf)
            except Exception as exc:  # noqa: BLE001 - scanner resilience, logged below
                print(f"[doctor-classify] rule {rule.name} failed on {rel}: {exc}", file=sys.stderr)
                continue
            for finding in rule_findings:
                emit(rel, finding)
                finding_count += 1

    # Diagnostic to stderr — surfaces whether the RE2 fast path was active.
    print(
        f"[doctor-classify] {finding_count} finding(s) across {len(files)} workflow(s); "
        f"re2_active={classifier.re2_active}; structural_rules={len(structural_rules)}",
        file=sys.stderr,
    )
    return 1 if finding_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
