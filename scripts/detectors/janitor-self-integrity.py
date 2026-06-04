#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""janitor-self-integrity — heartbeat self-attestation detector.

OPT-IN. Off by default; set
    CLAUDE_PLUGIN_OPTION_JANITOR_SELF_INTEGRITY_ENABLED=1
to arm.

This detector is the runtime sibling of scripts/lib/janitor_self_integrity.py.
It runs once per heartbeat fire and surfaces ONE drift line when ANY of
the following deterministic self-attestation checks fails. Conservative
by design — a false positive here is louder than the false-negative
risk, so the detector silences on missing optional inputs (no manifest,
no audit chain yet, etc.) and fires only on positive evidence of
mutation.

Checks performed (in order; first finding wins, the detector emits at
most one drift line per fire):

  1. Manifest verification (claude-md-anti-tamper)
     If `${CLAUDE_PLUGIN_ROOT}/.integrity/manifest-sha256.json` exists,
     compare the live README.md / CLAUDE.md / skills/**/SKILL.md /
     commands/**/*.md / rules/**/*.md file hashes against the baseline.
     Surface "mutated/missing/extra" file counts.

  2. Audit-chain verification
     If `${CLAUDE_PLUGIN_DATA}/janitor-chain.ndjson` exists, walk the
     chain and surface the first broken link.

  3. SKILL.md integrity-notice preamble drift
     If a janitor SKILL.md is missing the canonical integrity-notice
     block (per `INTEGRITY_NOTICE_PREAMBLE` in the library), surface
     it as a separate finding class — a SKILL.md without its tamper
     warning is itself a prompt-injection attack surface.

Heartbeat invariants:
  * Opt-in env flag (default OFF)
  * Self-scan guard — never fires when CLAUDE_PROJECT_DIR is a
    DIFFERENT plugin. We only inspect the janitor's own files
    (resolved via the script's own __file__), so the self-scan
    guard is inverted here: we DO want to scan ourselves.
  * Atomic content-hash dedupe — silent if nothing changed since
    last fire.
  * Bounded output — at most one drift line per heartbeat.
  * Records every fire in the audit chain when one is available.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import state  # type: ignore[import-not-found]  # noqa: E402
from janitor_self_integrity import (  # type: ignore[import-not-found]  # noqa: E402
    INTEGRITY_NOTICE_PREAMBLE,  # noqa: F401  -- re-exported for callers
    AuditChain,
    has_integrity_notice,
    load_or_create_key,
    verify_manifest,
)

_NAME = "janitor-self-integrity"

# Plugin root resolution — this script lives at
# `<plugin-root>/scripts/detectors/janitor-self-integrity.py`, so
# the plugin root is two levels above the script file. We use the
# script's own __file__ (NOT $CLAUDE_PROJECT_DIR) because the
# detector's job is to attest THE JANITOR'S OWN FILES, not the
# user's current project tree.
_PLUGIN_ROOT = _HERE.parent.parent
_MANIFEST_PATH = _PLUGIN_ROOT / ".integrity" / "manifest-sha256.json"
_AUDIT_CHAIN_DEFAULT = "janitor-chain.ndjson"


def _resolve_audit_chain_path() -> Path | None:
    """Audit chain lives in CLAUDE_PLUGIN_DATA (survives plugin updates).

    Returns None if the env var is unset — chain check is silently
    skipped. The first heartbeat after armed-with-data-dir mints the
    chain via the library's AuditChain.append() helper.
    """
    raw = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    if not raw:
        return None
    return Path(raw) / _AUDIT_CHAIN_DEFAULT


def _check_manifest() -> str | None:
    """Return a drift-line body if manifest verification flags drift.

    Returns None if no manifest exists yet (legitimate pre-publish
    state) OR if everything verifies clean.
    """
    if not _MANIFEST_PATH.is_file():
        return None
    try:
        mutated, missing, extra = verify_manifest(_PLUGIN_ROOT, _MANIFEST_PATH)
    except OSError as exc:
        return f"manifest verify failed ({exc!r})"
    if not (mutated or missing or extra):
        return None
    # Cap the per-class file list to keep the drift line under any
    # reasonable terminal width. The full list is in the manifest +
    # the audit log — the line is for humans to glance at.
    def _sample(items: list[str], cap: int = 3) -> str:
        if not items:
            return ""
        sample = ", ".join(state.sanitize_for_drift_line(p) for p in items[:cap])
        if len(items) > cap:
            sample += f", …+{len(items) - cap}"
        return sample
    parts: list[str] = []
    if mutated:
        parts.append(f"mutated={len(mutated)} ({_sample(mutated)})")
    if missing:
        parts.append(f"missing={len(missing)} ({_sample(missing)})")
    if extra:
        parts.append(f"extra={len(extra)} ({_sample(extra)})")
    return (
        "plugin file-hash manifest drift — "
        + "; ".join(parts)
        + " — verify the install or re-publish to refresh "
        ".integrity/manifest-sha256.json"
    )


def _check_audit_chain() -> str | None:
    """Return a drift-line body if the audit chain is broken."""
    chain_path = _resolve_audit_chain_path()
    if chain_path is None or not chain_path.is_file():
        return None
    key = load_or_create_key()
    if key is None:
        return None
    chain = AuditChain(chain_path, key)
    try:
        ok, idx, reason = chain.verify()
    except OSError as exc:
        return f"audit chain verify failed ({exc!r})"
    if ok:
        return None
    safe_reason = state.sanitize_for_drift_line(reason)
    return (
        f"audit-log tamper-evidence broken at entry index {idx} ({safe_reason}) — "
        f"the janitor-chain.ndjson under CLAUDE_PLUGIN_DATA has been "
        f"truncated, reordered, or edited"
    )


def _check_skill_preambles() -> str | None:
    """Return a drift-line body if any janitor SKILL.md lacks the preamble.

    Conservative: we only emit if at least one skill is missing the
    notice. A brand-new plugin install where no skills carry the
    preamble yet would surface every skill on the first fire — that's
    the intended posture-improvement nudge, not a false positive.
    """
    skills_root = _PLUGIN_ROOT / "skills"
    if not skills_root.is_dir():
        return None
    missing: list[str] = []
    for skill_md in sorted(skills_root.glob("janitor-*/SKILL.md")):
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        if not has_integrity_notice(text):
            try:
                missing.append(str(skill_md.relative_to(_PLUGIN_ROOT)))
            except ValueError:
                missing.append(skill_md.name)
    if not missing:
        return None
    cap = 3
    sample = ", ".join(state.sanitize_for_drift_line(p) for p in missing[:cap])
    if len(missing) > cap:
        sample += f", …+{len(missing) - cap}"
    return (
        f"{len(missing)} janitor SKILL.md file(s) missing the INTEGRITY "
        f"NOTICE preamble ({sample}) — prompt-injection attack surface"
    )


def _record_fire(verdict: str) -> None:
    """Best-effort: append a single 'detector.fire' entry to the chain.

    The chain is intentionally append-only — even silent fires get
    logged, so a downstream attacker who later forges a quiet success
    must also forge an unbroken chain of preceding fires.
    """
    chain_path = _resolve_audit_chain_path()
    if chain_path is None:
        return
    key = load_or_create_key()
    if key is None:
        return
    try:
        chain = AuditChain(chain_path, key)
        chain.append({
            "event": "detector.fire",
            "rule_id": _NAME,
            "verdict": verdict,
        })
    except OSError:
        # Append failure is non-fatal; the next fire will still chain
        # from the last successful entry. Logged via state.log_line so
        # post-mortems can correlate.
        state.log_line(_NAME, "audit-chain append failed (OSError)")


def main() -> int:
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_JANITOR_SELF_INTEGRITY_ENABLED",
        False,
    ):
        return 0

    # NOTE: we deliberately do NOT call state.is_self_scan_target() here.
    # This detector's purpose IS to scan the janitor's own files. The
    # self-scan guard exists to silence detectors that would emit
    # findings about the janitor's own test fixtures when the user has
    # cloned the janitor repo as their CLAUDE_PROJECT_DIR — but
    # janitor-self-integrity reads its inputs by `__file__`, not by
    # `state.project_root()`, so it's independent of which project the
    # user happens to be in.

    state.init_state()

    # Content-hash dedupe — if neither the manifest nor any inspected
    # janitor SKILL.md has changed since the last fire, silence. The
    # signature deliberately covers ONLY the *inputs* the detector
    # examines, NOT the audit chain (which the detector itself writes
    # to via `_record_fire`); including the chain would make every
    # fire invalidate its own dedupe key, so the detector would re-emit
    # the same finding on every heartbeat instead of once-per-drift.
    signature_parts: list[str] = []
    if _MANIFEST_PATH.is_file():
        try:
            st = _MANIFEST_PATH.stat()
            signature_parts.append(f"manifest|{st.st_mtime_ns}|{st.st_size}")
        except OSError:
            pass
    # Cheap proxy for SKILL.md preamble drift: count + mtime over all
    # janitor-*/SKILL.md. Path is the full relative path (not just
    # `skill_md.name` which is always "SKILL.md") so each skill is
    # individually addressable in the signature.
    skills_root = _PLUGIN_ROOT / "skills"
    if skills_root.is_dir():
        for skill_md in sorted(skills_root.glob("janitor-*/SKILL.md")):
            try:
                st = skill_md.stat()
                try:
                    rel = skill_md.relative_to(_PLUGIN_ROOT).as_posix()
                except ValueError:
                    rel = skill_md.name
                signature_parts.append(f"skill|{rel}|{st.st_mtime_ns}|{st.st_size}")
            except OSError:
                pass
    signature = "\n".join(signature_parts)

    last_sig_file = state.state_dir() / "janitor-self-integrity-last-sig.txt"
    if last_sig_file.is_file():
        try:
            if last_sig_file.read_text(encoding="utf-8") == signature:
                return 0
        except OSError:
            pass

    # Run the checks in priority order — manifest drift is the
    # highest-signal evidence of tampering; audit-chain break is the
    # tamper-evidence proof of the chain itself; SKILL.md preamble is
    # the lowest-severity attack-surface nudge.
    finding: str | None = None
    finding_class: str = "clean"
    for label, fn in (
        ("manifest", _check_manifest),
        ("audit-chain", _check_audit_chain),
        ("skill-preamble", _check_skill_preambles),
    ):
        try:
            finding = fn()
        except OSError as exc:
            state.log_line(_NAME, f"{label} check raised OSError: {exc!r}")
            continue
        if finding:
            finding_class = label
            break

    state.atomic_write(last_sig_file, signature)
    _record_fire(finding_class)

    if finding:
        print(f"[{_NAME}] {finding}")

    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
