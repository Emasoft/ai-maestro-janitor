#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""provenance-audit — heartbeat-cadenced provenance / SBOM audit.

Wave 16 implementation of the distill2-f deep-dive proposals
(reports/study-github-monitoring-deep2/20260527_184033+0200-distill2-f-
provenance-sbom.md). Scans:

  * Every `.github/workflows/*.yml` / `.yaml` for the eight provenance
    rules catalogued in `scripts/lib/provenance_patterns.py` (cosign
    verification, npm provenance flag, SBOM presence, in-toto
    attestation, reproducible-build flags, OIDC trusted publishing,
    checksum manifests).
  * Repo-root SLSA-level declarations (`.slsa/level.json`, README /
    SECURITY headers, OpenSSF Scorecard markdown) — compared against
    the configured floor `JANITOR_OPT_SLSA_FLOOR` (default 2).
  * SBOM / cosign presence as a release-time invariant: at minimum
    ONE workflow that builds a release must reference an SBOM tool
    AND a sigstore / attestation tool. Absence emits a finding.

Heartbeat invariants (mirrors the shape of every other detector under
scripts/detectors/):

  * Self-scan guard — never scans the janitor's own tree
    (`state.is_self_scan_target()`).
  * Content-hash dedupe — silent if the workflow corpus + SLSA files
    haven't changed since the last heartbeat.
  * Bounded output — at most `_MAX_FINDINGS_SHOWN` per heartbeat, with
    an overflow tail line.
  * Deterministic — pure file/line regex, no network, no shell-out, no
    LLM. Patterns live in `scripts/lib/provenance_patterns.py`.

Severity vocabulary: CRITICAL / HIGH / MAJOR / MINOR (existing janitor
set). The detector surfaces HIGH and above by default; MAJOR / MINOR
ride only when `CLAUDE_PLUGIN_OPTION_PROVENANCE_AUDIT_FULL=1`.

Read-only: the detector parses files and runs pure-Python analysis. It
never edits a workflow, never calls the GitHub API, never mutates the
repo.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import provenance_patterns as pp  # type: ignore[import-not-found]  # noqa: E402
import state  # type: ignore[import-not-found]  # noqa: E402

_NAME = "provenance-audit"

# Max distinct findings printed per heartbeat. Anything beyond is rolled
# up into a single "+N more" tail line. Matches the convention in
# repo-trust-score / workflow-security.
_MAX_FINDINGS_SHOWN = 6

# Severity ranking — higher index = higher severity, so we can filter
# by `severity_rank(f.severity) >= threshold`.
_SEVERITY_ORDER = {"MINOR": 1, "MAJOR": 2, "HIGH": 3, "CRITICAL": 4}


def _is_self_scan() -> bool:
    """Self-scan guard wrapper. Centralised here so a test fixture can
    monkey-patch `state.is_self_scan_target` if it ever needs to."""
    return state.is_self_scan_target()


def _iter_workflow_files(project_root: Path) -> list[Path]:
    """Both `.yml` and `.yaml` under `.github/workflows/`. A workflow-
    security monitor that ignored either suffix would leave an obvious
    blind spot for an attacker to hide a workflow in. The same logic
    appears in `workflow-security.py`; reuse the convention."""
    workflows_dir = project_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return []
    return sorted(
        p for p in workflows_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".yml", ".yaml")
    )


def _iter_slsa_declaration_files(project_root: Path) -> list[Path]:
    """SLSA level can be declared in several documented locations.

    We scan all of them; the rule `prov-slsa-level-declared` extracts
    every match, and the detector compares against the floor. Limited
    to a small set of well-known paths so the heartbeat stays cheap.
    """
    candidates = (
        ".slsa/level.json",
        ".slsa/levels.json",
        "SECURITY.md",
        "security.txt",
        ".well-known/security.txt",
        "SCORECARD.md",
        "scorecard.md",
        "README.md",
    )
    found: list[Path] = []
    for rel in candidates:
        p = project_root / rel
        if p.is_file():
            found.append(p)
    return found


def _content_signature(project_root: Path, *, mode_key: str) -> str:
    """Cheap dedupe — sizes + mtimes of the relevant input files. A
    matching hash means nothing in the audit corpus has changed and we
    can stay silent. Bounded to the workflow corpus + SLSA declaration
    files so the heartbeat stays O(small).

    `mode_key` mixes the current detector configuration (full-mode +
    SLSA floor) into the hash so a config change forces a fresh scan
    even when the file corpus is unchanged. Without this, toggling
    `CLAUDE_PLUGIN_OPTION_PROVENANCE_AUDIT_FULL` between runs would
    leave the second run silent, which is the opposite of what we want
    when the user is asking the audit to be more aggressive."""
    h = hashlib.sha256()
    h.update(f"mode={mode_key}\n".encode())
    for wf in _iter_workflow_files(project_root):
        try:
            st = wf.stat()
            h.update(f"{wf}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        except OSError:
            continue
    for sl in _iter_slsa_declaration_files(project_root):
        try:
            st = sl.stat()
            h.update(f"{sl}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        except OSError:
            continue
    return h.hexdigest()


def _check_slsa_floor(project_root: Path, floor: int) -> list[str]:
    """Return human-readable notes when ANY declared SLSA level is
    below the configured floor.

    A repo without any SLSA declaration produces no finding here —
    "undeclared SLSA" is a higher-FP advisory that lives outside this
    detector (per the distill report's §6 mitigation). The rule fires
    only when the project HAS opted in to declaring its level.
    """
    notes: list[str] = []
    for f in _iter_slsa_declaration_files(project_root):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for level, line in pp.extract_slsa_levels(text):
            if level < floor:
                gap = floor - level
                gap_sev = "HIGH" if gap >= 2 else "MAJOR"
                notes.append(
                    f"[{gap_sev}] prov-slsa-level-below-floor: "
                    f"{f.relative_to(project_root)}:{line} declares "
                    f"SLSA L{level} (floor is L{floor})"
                )
    return notes


def _check_release_sbom_invariant(
    project_root: Path,
) -> list[str]:
    """Cross-file invariant: when the repo has at least one workflow
    that publishes a release (gh release create, softprops/action-gh-
    release, pypa/gh-action-pypi-publish, etc.), at least ONE workflow
    file in the project must reference a SBOM tool AND ONE must
    reference a sigstore-/attestation-tool. Absence is a release-time
    drift signal.

    Returns at most one note (release process has no SBOM tool
    anywhere) and at most one note (release process has no
    cosign/attestation tool anywhere) — keeps the heartbeat compact.
    """
    notes: list[str] = []
    workflows = _iter_workflow_files(project_root)
    if not workflows:
        return notes

    publishes_release = False
    has_sbom_tool = False
    has_attestation_tool = False

    # The publisher token set is the union of the patterns in rules 3, 4,
    # 7, 8 — all the "this workflow ships a release" markers.
    release_publisher_tokens = (
        "softprops/action-gh-release",
        "ncipollo/release-action",
        "actions/upload-release-asset",
        "goreleaser/goreleaser-action",
        "pypa/gh-action-pypi-publish",
        "gh release create",
        "gh release upload",
    )
    sbom_tool_tokens = (
        "anchore/sbom-action",
        "cyclonedx",
        "CycloneDX/",
        "syft",
        "microsoft/sbom-tool",
        "spdx-sbom-generator",
    )
    attestation_tool_tokens = (
        "actions/attest-build-provenance",
        "actions/attest-sbom",
        "actions/attest@",
        "cosign",
        "slsa-github-generator",
        "slsa-verifier",
    )

    for wf in workflows:
        try:
            txt = wf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        txt_l = txt.lower()
        if any(tok.lower() in txt_l for tok in release_publisher_tokens):
            publishes_release = True
        if any(tok.lower() in txt_l for tok in sbom_tool_tokens):
            has_sbom_tool = True
        if any(tok.lower() in txt_l for tok in attestation_tool_tokens):
            has_attestation_tool = True

    if publishes_release and not has_sbom_tool:
        notes.append(
            "[MAJOR] prov-release-without-sbom-anywhere: project "
            "publishes a release but NO workflow references an SBOM "
            "tool (anchore/sbom-action, syft, CycloneDX/*, "
            "microsoft/sbom-tool, spdx-sbom-generator)."
        )
    if publishes_release and not has_attestation_tool:
        notes.append(
            "[MAJOR] prov-release-without-attestation-anywhere: project "
            "publishes a release but NO workflow references an "
            "attestation / sigstore tool (actions/attest-*, cosign, "
            "slsa-github-generator, slsa-verifier)."
        )
    return notes


def _format_finding(f: pp.Finding, project_root: Path) -> str:
    """Render one Finding as a single defanged drift line."""
    try:
        rel = Path(f.file_path).relative_to(project_root)
    except ValueError:
        rel = Path(f.file_path)
    matched = state.sanitize_for_drift_line(f.matched_text)
    return (
        f"[{f.severity}] {f.rule_id}: {rel}:{f.line}:{f.column} {matched}"
    )


def _floor_from_env() -> int:
    """Read the configured SLSA floor. Default 2 — corresponds to the
    macaron `SLSA_PROVENANCE_AVAILABLE` policy level. Negative or
    non-numeric → default."""
    raw = state.coerce_int(
        __import__("os").environ.get("JANITOR_OPT_SLSA_FLOOR"),
        default=2,
        detector_name=_NAME,
        var_name="JANITOR_OPT_SLSA_FLOOR",
    )
    # Clamp into the documented SLSA range 0..3 — anything higher is
    # outside the SLSA spec.
    if raw < 0:
        return 0
    if raw > 3:
        return 3
    return raw


def main() -> int:
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_PROVENANCE_AUDIT_ENABLED", True,
    ):
        return 0
    if _is_self_scan():
        return 0

    state.init_state()
    project_root = state.project_root()

    # Compute the FULL-mode + floor knobs BEFORE the dedupe hash so a
    # config change between runs forces a fresh scan.
    full_mode = state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_PROVENANCE_AUDIT_FULL", False,
    )
    floor = _floor_from_env()
    mode_key = f"full={int(full_mode)};floor={floor}"

    # Hash-based dedupe: bail out fast if nothing in the input set has
    # changed since the last pass. Matches the workflow-security.py +
    # repo-trust-score.py convention. Mode is mixed in so a knob flip
    # always forces a re-scan.
    combined = _content_signature(project_root, mode_key=mode_key)
    last_hash_file = state.state_dir() / "provenance-audit-last-hash.ts"
    if last_hash_file.is_file():
        try:
            if last_hash_file.read_text(encoding="utf-8").strip() == combined:
                return 0
        except OSError:
            pass

    findings_lines: list[str] = []

    # 1. Per-workflow rule scan (rules 1-4, 6-8).
    threshold = 1 if full_mode else _SEVERITY_ORDER["MAJOR"]  # MINOR=1, MAJOR=2

    for wf in _iter_workflow_files(project_root):
        for f in pp.scan_file(wf):
            if _SEVERITY_ORDER.get(f.severity, 0) < threshold:
                continue
            findings_lines.append(_format_finding(f, project_root))

    # 2. SLSA-level floor check (rule 5). `floor` was computed earlier so
    # it could be mixed into the dedupe hash.
    findings_lines.extend(_check_slsa_floor(project_root, floor))

    # 3. Cross-file release-SBOM / release-attestation invariants.
    findings_lines.extend(_check_release_sbom_invariant(project_root))

    # Persist the new hash AFTER we've computed everything so that a
    # crash mid-scan leaves the old hash in place and the next
    # heartbeat retries from scratch.
    state.atomic_write(last_hash_file, combined)

    if not findings_lines:
        state.rotate_log_if_big(_NAME)
        return 0

    # Bounded output — at most _MAX_FINDINGS_SHOWN findings printed.
    shown = findings_lines[:_MAX_FINDINGS_SHOWN]
    overflow = len(findings_lines) - len(shown)
    body = "\n".join(f"  - {ln}" for ln in shown)
    if overflow > 0:
        body += f"\n  - …and {overflow} more finding(s)"
    print(
        f"[provenance-audit] provenance/SBOM issues in the release path "
        f"({len(findings_lines)} finding(s)). The release pipeline of "
        f"this repo lacks one or more SLSA-aligned controls — inspect "
        f"and either fix the workflow or set the relevant opt-out env "
        f"vars before publishing.\n{body}"
    )
    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
