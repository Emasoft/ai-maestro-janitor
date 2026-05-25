#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "google-re2>=1.1",
#   "pyyaml>=6.0",
# ]
# ///
"""Workflow-security detector — heartbeat-cadenced GitHub Actions audit.

Runs the janitor's native Sentinel scanner (the same regex + structural +
repo tiers the /janitor-github-workflow-doctor skill drives through
scripts/doctor_classify.py) over every workflow under .github/workflows/
and surfaces NEW high-severity findings (CRITICAL / HIGH) as a single
drift line. MAJOR / MINOR findings are deliberately left to the on-demand
doctor skill so the heartbeat stays signal-dense — a security regression
that can actually be weaponised (injection, credential leak, unpinned
third-party action) rides the heartbeat; cosmetic hardening does not.

Why a heartbeat detector and not only the on-demand skill: a workflow
edit can introduce a critical injection or a secret leak the moment it
lands. Surfacing it on the next heartbeat (≤ the configured cadence)
means a security regression cannot sit unnoticed between manual audits —
this is the "no security rule can be violated without it being detected"
guarantee, applied to CI definitions.

Efficiency + responsiveness: the detector hashes the combined content of
all workflow files. When the hash is unchanged since the last pass it
returns immediately without importing the scanner or re-parsing anything.
A workflow edit changes the hash, which both forces a fresh scan AND, by
comparing against the last-scanned hash, re-surfaces the current finding
set exactly once per change (no per-fire spam, no missed regressions —
reverting a fix back to a vulnerable state is itself a hash transition
and re-alerts).

Read-only: it parses files and runs pure-Python analysis. It never edits
a workflow, never calls the GitHub API, never mutates the repo. It
surfaces; the user (or /janitor-github-workflow-doctor) fixes.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
# scripts/lib for the detector helpers (bare `import state`)…
sys.path.insert(0, str(_SCRIPTS / "lib"))
# …and scripts/ so `lib.sentinel.*` / `lib.zizmor_classifier` resolve as a
# package, exactly the way scripts/doctor_classify.py wires the scanner.
sys.path.insert(0, str(_SCRIPTS))

import state  # noqa: E402

# Only these two severities ride the heartbeat. They mirror SEV_CRITICAL /
# SEV_HIGH in lib.sentinel.model and the JSON severity contract emitted by
# doctor_classify.py; MAJOR / MINOR are the on-demand doctor skill's job.
_HEARTBEAT_SEVERITIES = ("CRITICAL", "HIGH")
_MAX_SAMPLE = 10


def _iter_workflow_files(workflows_dir: Path) -> list[Path]:
    """Both .yml and .yaml — a security monitor that ignored .yaml would
    leave an obvious blind spot for an attacker to hide a workflow in."""
    return sorted(
        p for p in workflows_dir.iterdir()
        if p.is_file() and p.suffix in (".yml", ".yaml")
    )


def main() -> int:
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_WORKFLOW_SECURITY_ENABLED", True):
        return 0

    state.init_state()
    project_root = state.project_root()
    workflows_dir = project_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return 0  # not a GitHub Actions repo

    files = _iter_workflow_files(workflows_dir)
    if not files:
        return 0

    # Read every file once; the per-file content hash drives BOTH the cheap
    # short-circuit and the change-detection (its own dedupe mechanism).
    texts: dict[str, str] = {}
    per_file_hash: dict[str, str] = {}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(path.relative_to(project_root))
        texts[rel] = text
        per_file_hash[rel] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    if not texts:
        return 0

    combined = hashlib.sha256(
        "\n".join(f"{r}:{per_file_hash[r]}" for r in sorted(per_file_hash)).encode("utf-8")
    ).hexdigest()[:16]

    # Short-circuit: identical to the last scanned version → nothing can have
    # changed, so emit nothing and skip the scan entirely. The stamp file is
    # the single source of dedupe truth: we emit only when the freshly-read
    # hash differs from the last scanned hash, which is exactly once per
    # distinct workflow version (a revert to a vulnerable version differs
    # from the clean version that preceded it, so it re-alerts).
    last_hash_file = state.state_dir() / "workflow-security-last-hash.ts"
    if last_hash_file.is_file():
        try:
            if last_hash_file.read_text().strip() == combined:
                return 0
        except OSError:
            pass

    # Import the scanner lazily — AFTER the short-circuit — so an unchanged
    # repo never pays the import / uv-dependency-resolution cost on a heartbeat.
    try:
        from lib.sentinel.model import Workflow
        from lib.sentinel.rules_absence import RULES as _ABSENCE_RULES
        from lib.sentinel.rules_context import RULES as _CONTEXT_RULES
        from lib.sentinel.rules_injection import RULES as _INJECTION_RULES
        from lib.sentinel.rules_repo import REPO_RULES
        from lib.zizmor_classifier import Classifier
    except Exception as exc:  # noqa: BLE001 - a missing dep must not crash the heartbeat
        state.log_line("workflow-security", f"scanner import failed: {exc}")
        return 0

    structural_rules = [*_ABSENCE_RULES, *_CONTEXT_RULES, *_INJECTION_RULES]
    classifier = Classifier()

    # (severity, rel, line, rule_id) tuples for the high-severity findings.
    findings: list[tuple[str, str, int, str]] = []

    def _consider(rel: str, finding) -> None:
        if finding.severity in _HEARTBEAT_SEVERITIES:
            findings.append((finding.severity, rel, finding.line, finding.rule_id))

    for rel, text in texts.items():
        # Tier 1 — regex RegexSet.
        try:
            for finding in classifier.classify(text):
                _consider(rel, finding)
        except Exception as exc:  # noqa: BLE001 - one bad file must not blind the rest
            state.log_line("workflow-security", f"regex tier failed on {rel}: {exc}")
        # Tier 2 — structural rules, each isolated so one rule raising on a
        # pathological workflow cannot suppress every other rule/file.
        try:
            wf = Workflow(rel, text)
        except Exception as exc:  # noqa: BLE001
            state.log_line("workflow-security", f"parse failed on {rel}: {exc}")
            continue
        for rule in structural_rules:
            try:
                rule_findings = rule.check(wf)
            except Exception:  # noqa: BLE001 - scanner resilience (mirrors doctor_classify)
                continue
            for finding in rule_findings:
                _consider(rel, finding)

    # Tier 3 — repo-level rules over all texts. Today these are MINOR
    # (missing-zizmor) so they will not ride the heartbeat, but run them for
    # forward-compatibility if a future repo rule is CRITICAL/HIGH.
    workflows_rel = str(workflows_dir.relative_to(project_root))
    for repo_rule in REPO_RULES:
        try:
            for finding in repo_rule(list(texts.values())):
                _consider(workflows_rel, finding)
        except Exception:  # noqa: BLE001
            continue

    # Stamp the scanned hash regardless of outcome so an all-clean scan also
    # caches (next identical fire short-circuits) and a later edit re-scans.
    state.atomic_write(last_hash_file, combined)

    if not findings:
        state.rotate_log_if_big("workflow-security")
        return 0

    # CRITICAL before HIGH, then by file/line/rule for a stable sample order.
    sev_rank = {"CRITICAL": 0, "HIGH": 1}
    findings.sort(key=lambda f: (sev_rank.get(f[0], 9), f[1], f[2], f[3]))
    count = len(findings)
    crit = sum(1 for f in findings if f[0] == "CRITICAL")

    sample_lines = []
    for sev, rel, line, rule_id in findings[:_MAX_SAMPLE]:
        safe_rel = state.sanitize_for_drift_line(rel)
        safe_rule = state.sanitize_for_drift_line(rule_id)
        sample_lines.append(f"  - {safe_rel}:{line} {safe_rule} ({sev})")
    if count > _MAX_SAMPLE:
        sample_lines.append(f"  - …and {count - _MAX_SAMPLE} more")
    sample = "\n".join(sample_lines)

    print(
        f"[workflow-security] URGENT: {count} high-severity workflow finding(s) "
        f"({crit} CRITICAL, {count - crit} HIGH) in .github/workflows/ — a CI "
        f"workflow can be exploited or leak secrets. Run "
        f"/janitor-github-workflow-doctor for the full report + per-finding "
        f"fixes. Findings:\n{sample}"
    )

    state.rotate_log_if_big("workflow-security")
    return 0


if __name__ == "__main__":
    sys.exit(main())
