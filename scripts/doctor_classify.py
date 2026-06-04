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
  2 — no .github/workflows/ or no .yml/.yaml files.
  3 — internal error (printed to stderr).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Upper bound on a single workflow file we will read into memory. Real
# workflow YAML is a few KB; anything past this is either generated junk or
# a deliberate memory-pressure payload, and reading it fully would balloon
# RSS. Mirrors the detector's intent so doctor and heartbeat agree.
_MAX_WORKFLOW_BYTES = 5 * 1024 * 1024  # 5 MB


def _is_self_scan(project_root: Path) -> bool:
    """Hard guard: never scan the janitor's own .github/workflows/.

    The doctor's classifier is meant for OTHER repos that arm the janitor —
    scanning the janitor's own CI from here would emit confusing self-
    reports the maintainer already audits via publish.py + GitHub Actions.

    Detection mirrors state.is_self_scan_target() (which the heartbeat
    detectors use): `.claude-plugin/plugin.json` with name == "ai-maestro-
    janitor" → self.

    Override: set `CLAUDE_PLUGIN_ALLOW_SELF_SCAN=1` to allow scanning
    (the official CI publish-gate uses this).
    """
    import os
    if os.environ.get("CLAUDE_PLUGIN_ALLOW_SELF_SCAN", "").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        return False
    manifest = project_root / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("name") == "ai-maestro-janitor"


_SARIF_SEVERITY = {
    "CRITICAL": "error",
    "HIGH": "error",
    "MAJOR": "warning",
    "MINOR": "note",
}


def _to_sarif(
    findings: list,
    project_root: Path,
) -> dict:
    """Convert (rel_path, Finding) tuples to a SARIF 2.1.0 log.

    SARIF (Static Analysis Results Interchange Format) is the format
    GitHub Code Scanning ingests via the upload-sarif action. Each
    rule_id seen in findings is materialised in `rules`; each finding
    becomes one `results[]` entry with location + level. Producing a
    valid SARIF lets the user wire `uv run doctor_classify.py --sarif`
    into a CI step that uploads to Code Scanning.
    """
    rules_seen: dict[str, dict] = {}
    results: list[dict] = []
    for rel, finding in findings:
        if finding.rule_id not in rules_seen:
            rules_seen[finding.rule_id] = {
                "id": finding.rule_id,
                "name": finding.rule_id,
                "shortDescription": {"text": finding.rule_id},
                "fullDescription": {"text": finding.description},
                "defaultConfiguration": {
                    "level": _SARIF_SEVERITY.get(finding.severity, "note"),
                },
                "properties": {
                    "severity": finding.severity,
                    "tags": ["security"],
                },
            }
        results.append({
            "ruleId": finding.rule_id,
            "level": _SARIF_SEVERITY.get(finding.severity, "note"),
            "message": {"text": finding.description},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": str(rel)},
                    "region": {
                        "startLine": max(1, finding.line),
                        "startColumn": max(1, finding.col),
                        "snippet": {"text": finding.matched_text},
                    },
                },
            }],
            "properties": {"severity": finding.severity},
        })

    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "ai-maestro-janitor-doctor",
                    "informationUri": "https://github.com/Emasoft/ai-maestro-janitor",
                    "rules": list(rules_seen.values()),
                },
            },
            "results": results,
            "invocations": [{
                "executionSuccessful": True,
                "workingDirectory": {"uri": project_root.as_uri()},
            }],
        }],
    }


def main() -> int:
    sarif_mode = "--sarif" in sys.argv[1:]
    project_root = Path.cwd()
    if _is_self_scan(project_root):
        print(
            "[SKIP] doctor_classify refuses to scan the janitor's own repo. "
            "Set CLAUDE_PLUGIN_ALLOW_SELF_SCAN=1 to override.",
            file=sys.stderr,
        )
        return 2
    workflows_dir = project_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        print(f"[FAILED] no .github/workflows/ under {project_root}", file=sys.stderr)
        return 2

    # Both .yml and .yaml — GitHub Actions treats them identically, so a
    # classifier that ignored .yaml would leave an obvious blind spot for an
    # attacker to hide a workflow in (mirrors workflow-security.py /
    # provenance-audit.py).
    files = sorted(
        p for p in workflows_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".yml", ".yaml")
    )
    if not files:
        print(f"[FAILED] no .yml/.yaml files in {workflows_dir}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(project_root / "scripts"))
    from lib.sentinel.model import Workflow  # noqa: E402
    from lib.sentinel.rules_absence import RULES as _ABSENCE_RULES  # noqa: E402
    from lib.sentinel.rules_context import RULES as _CONTEXT_RULES  # noqa: E402
    from lib.sentinel.rules_extra import RULES as _EXTRA_RULES  # noqa: E402
    from lib.sentinel.rules_injection import RULES as _INJECTION_RULES  # noqa: E402
    from lib.sentinel.rules_repo import REPO_RULES  # noqa: E402
    from lib.zizmor_classifier import Classifier  # noqa: E402

    # _EXTRA_RULES are the disclosed-CVE structural detectors (Ultralytics
    # workflow_run RCE, ACTIONS_ALLOW_UNSECURE_COMMANDS re-enable, …). Without
    # them the doctor's full audit silently skips those classes.
    structural_rules = [*_ABSENCE_RULES, *_CONTEXT_RULES, *_INJECTION_RULES, *_EXTRA_RULES]

    # Collected findings — emitted as JSON-lines or SARIF depending on flag.
    collected: list = []

    def emit_jsonl(rel_path: Path, finding) -> None:
        print(json.dumps({
            "file": str(rel_path),
            "rule_id": finding.rule_id,
            "line": finding.line,
            "col": finding.col,
            "severity": finding.severity,
            "description": finding.description,
            "matched_text": finding.matched_text,
        }, ensure_ascii=False))

    def emit(rel_path: Path, finding) -> None:
        collected.append((str(rel_path), finding))
        if not sarif_mode:
            emit_jsonl(rel_path, finding)

    classifier = Classifier()
    finding_count = 0
    all_texts: list[str] = []
    for path in files:
        # Match the detector's resilience: skip a file that is oversized
        # (a multi-hundred-MB workflow would balloon RSS) or undecodable
        # (a non-UTF-8 / binary file must NOT crash the whole doctor run via
        # an UnicodeDecodeError propagating out of main — the heartbeat
        # detector already skips such files gracefully).
        try:
            if path.stat().st_size > _MAX_WORKFLOW_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        all_texts.append(text)
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

    # Tier 3 — repo-level rules run once over every workflow's text
    # (e.g. missing-zizmor: no workflow runs the analyzer anywhere).
    workflows_rel = workflows_dir.relative_to(project_root)
    for repo_rule in REPO_RULES:
        for finding in repo_rule(all_texts):
            emit(workflows_rel, finding)
            finding_count += 1

    if sarif_mode:
        print(json.dumps(_to_sarif(collected, project_root), ensure_ascii=False, indent=2))

    # Diagnostic to stderr — surfaces whether the RE2 fast path was active.
    print(
        f"[doctor-classify] {finding_count} finding(s) across {len(files)} workflow(s); "
        f"re2_active={classifier.re2_active}; "
        f"structural_rules={len(structural_rules)}; repo_rules={len(REPO_RULES)}",
        file=sys.stderr,
    )
    return 1 if finding_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
