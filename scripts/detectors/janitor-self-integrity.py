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
     Surface "mutated/missing/extra" file counts. SKIPPED when the
     plugin root is a git SOURCE checkout: the manifest is a release
     artifact, so post-release commits are dev work, not tampering
     (tickets T-BR3M3IUU / T-DTTXJGC7).

  2. Audit-chain verification
     If `<FIXED janitor DATA dir>/janitor-chain.ndjson` exists (the SAME
     fixed dir the C3 pin path uses — TRDD-DKEYCHN7; NOT $CLAUDE_PLUGIN_DATA),
     walk the chain and surface the first broken link.

  3. C3 last-good pin currency (TRDD-ZM5LZ24Y)
     If the pin exists but certifies a DIFFERENT version than the one
     we are running, the stub's C3 cross-check is permanently "no
     opinion" and silently degrades to the C2-only gate. Reported
     because a stale anchor and a healthy one look identical.

  4. SKILL.md integrity-notice preamble drift
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

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import state  # type: ignore[import-not-found]  # noqa: E402
import version_update_lib  # type: ignore[import-not-found]  # noqa: E402
from janitor_self_integrity import (  # type: ignore[import-not-found]  # noqa: E402
    INTEGRITY_NOTICE_PREAMBLE,  # noqa: F401  -- re-exported for callers
    AuditChain,
    has_integrity_notice,
    load_or_create_key,
    verify_manifest,
)
from keepalive_stage import is_plugin_source_checkout  # type: ignore[import-not-found]  # noqa: E402

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


def _fixed_data_dir() -> Path | None:
    """The FIXED janitor DATA dir — the SAME dir the C3 pin path uses.

    TRDD-DKEYCHN7: BOTH this detector's HMAC key AND its audit chain used to
    resolve via ``$CLAUDE_PLUGIN_DATA``, which is the foot-gun the project
    CLAUDE.md warns about — that env var points at whichever plugin owns the
    RUNNING turn, so the key + chain scattered into other plugins' data dirs
    and did not match across sessions (the finding-HMAC / chain tamper-evidence
    became unverifiable). We REUSE ``version_update_lib._data_dir()`` — the one
    canonical resolver of the FIXED dir (hard-coded path, ``JANITOR_DATA_DIR``
    test override, NEVER ``${CLAUDE_PLUGIN_DATA}``) so the detector's key + chain
    live in exactly the same place the C3 daemon/stub pin already lives. Do NOT
    re-derive the FIXED dir here — that would re-open the same drift the C3
    constant-parity guard exists to prevent.
    """
    return version_update_lib._data_dir()


def _resolve_audit_chain_path() -> Path | None:
    """Audit chain lives in the FIXED janitor DATA dir (survives plugin updates).

    TRDD-DKEYCHN7: was ``$CLAUDE_PLUGIN_DATA / janitor-chain.ndjson`` (the
    running-turn plugin's dir → scatter + cross-session mismatch); now the FIXED
    janitor dir, keyed by the SAME key as the chain HMAC. Returns None only if
    the FIXED dir is unresolvable (HOME missing) — chain check is then silently
    skipped (fail-open). The first heartbeat with a resolvable dir mints the
    chain via the library's AuditChain.append() helper.

    MIGRATION (documented RESET, fail-open): a chain that a prior buggy session
    wrote under some other plugin's ``$CLAUDE_PLUGIN_DATA`` is intentionally
    ABANDONED in place (we never scan or delete another plugin's data — fragile
    + privacy-invasive). The chain is append-only tamper-evidence keyed by the
    DATA-dir key; re-establishing it fresh in the FIXED dir simply restarts the
    evidence trail there, which is exactly the conservative fail-open posture
    (no key/chain ⇒ "no opinion", never a crash or a false tamper alarm).
    """
    base = _fixed_data_dir()
    if base is None:
        return None
    return base / _AUDIT_CHAIN_DEFAULT


def _check_manifest() -> str | None:
    """Return a drift-line body if manifest verification flags drift.

    Returns None if everything verifies clean, if the plugin root is a git SOURCE
    CHECKOUT (see the guard below), or if a SOURCE checkout simply has no manifest yet
    (legitimate pre-publish state).

    An INSTALLED root with no manifest is NOT silence-worthy — see below.
    """
    if not _MANIFEST_PATH.is_file():
        # A source checkout legitimately has none: the manifest is a RELEASE artifact,
        # so a pre-publish tree not having one is dev state, not tampering.
        if is_plugin_source_checkout(_PLUGIN_ROOT):
            return None
        # An INSTALLED root must carry one, and its absence is the worst case rather
        # than the empty one: it is the verification ANCHOR itself being gone, which
        # silently disables every hash check below. Returning None here treated "I
        # cannot check" as "nothing is wrong".
        #
        # MEASURED 2026-08-07 (janitor#229's sibling). A plugin install interrupted
        # under memory pressure removed `agents/`, `commands/`, `hooks/`,
        # `.claude-plugin/plugin.json` AND this manifest together. Because the manifest
        # went with them, this function returned None, so the mutilated install ran
        # silently on EVERY session on the machine — every `[janitor-memory-*]` marker
        # naming an agent that was no longer on disk — until a peer happened to need
        # one and refused to substitute. The one check that existed to catch a partial
        # install was disabled by the very event it existed to catch.
        return (
            "plugin integrity manifest MISSING from an installed plugin root "
            f"({state.sanitize_for_drift_line(str(_MANIFEST_PATH))}) — file-hash "
            "verification is DISABLED, so a partial or tampered install cannot be "
            "detected at all. Most likely an INTERRUPTED INSTALL (check for missing "
            "agents/, commands/, hooks/): compare this dir against the release tag, "
            "then re-install the plugin rather than patching it in place."
        )
    # SOURCE-CHECKOUT guard (tickets T-BR3M3IUU, T-DTTXJGC7). The manifest is a
    # RELEASE artifact — publish.py regenerates it at each release — so in a git
    # source checkout every legitimate post-release commit touching an
    # instruction file makes the tree differ from the manifest. That is dev
    # work under git's own integrity (every "mutation" is a tracked commit),
    # not tampering — yet this check read it as "mutated" and raised a false
    # CRITICAL SELFINT-001 ticket after every release. Installed roots (the
    # version cache, the DATA stage) are never git work trees, so the guard
    # cannot silence a real install. Security note: this does not weaken the
    # posture — an attacker who could plant a fake `.git/` in the cache could
    # already rewrite this same-tree UNSIGNED manifest directly; the anchor
    # against cache tampering is the dispatcher stub's C3 HMAC pin (keyed from
    # the DATA dir), not this check.
    if is_plugin_source_checkout(_PLUGIN_ROOT):
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
    # TRDD-DKEYCHN7: key MUST come from the FIXED dir (same dir as the chain),
    # NOT $CLAUDE_PLUGIN_DATA — otherwise the verify key wouldn't match the key
    # the chain was written with.
    key = load_or_create_key(_fixed_data_dir())
    if key is None:
        return None
    chain = AuditChain(chain_path, key)
    try:
        ok, idx, reason = chain.verify()
    except OSError as exc:
        return f"audit chain verify failed ({exc!r})"
    if ok:
        return None
    # F4 (audit 2026-07-13): before this detector's appends were locked, two projects'
    # heartbeats could read the same `prev_hmac` and both chain to it. The chain is
    # append-only, so such a fork is PERMANENT — and it is NOT tampering: every entry is
    # still key-signed and every parent is still present (nothing was removed). Alarming
    # on it forever, in every project, is precisely how a user learns to ignore the real
    # alarm. `concurrent_fork_only` is strict — a truncation, edit, reorder, or splice
    # makes it False and the alarm below fires — so this stays silent ONLY for the
    # provably-benign artifact of the now-fixed race.
    if chain.concurrent_fork_only():
        return None
    safe_reason = state.sanitize_for_drift_line(reason)
    return (
        f"audit-log tamper-evidence broken at entry index {idx} ({safe_reason}) — "
        f"the janitor-chain.ndjson in the janitor DATA dir has been "
        f"truncated, reordered, or edited"
    )


def _check_last_good_pin() -> str | None:
    """Return a drift-line body when the C3 last-good pin does not certify the
    version we are RUNNING — i.e. the tamper anchor is stale.

    WHY THIS NEEDS A DETECTOR AT ALL. The stub's C3 gate (`_pin_rejects`) can
    only have an opinion when the pin names the SAME version it is about to
    exec; every other state returns False — "no opinion" — and falls through to
    C2. That fail-open is correct (uncertainty must never block a heartbeat) but
    it is INVISIBLE: a pin left naming an old version disables C3 permanently
    and is byte-indistinguishable from a healthy one. Silent absence of a guard
    is the failure mode this whole detector exists for.

    ROOT CAUSE (verified 2026-08-14, TRDD-ZM5LZ24Y). `pin_good_version` has
    exactly ONE caller — `daemon.py`, inside `if updated:` — so the pin advances
    only when the DAEMON performs the self-update. A `claude plugin update` run
    by hand installs a version that is never certified, and C3 goes quiet for
    good. This project's CLAUDE.md now tells the agent to run that manual command
    on every CI pass, so the stale state is not an edge case: it is the norm.

    Conservative by construction: reports ONLY when a pin EXISTS and names a
    different version than the running one. No pin (never updated, unreadable,
    malformed) is "no opinion", never a finding — the same posture as the stub.
    """
    # A git source checkout has no version-stamped cache dir and no pin
    # relationship — same dev-state reasoning as the guard in _check_manifest.
    if is_plugin_source_checkout(_PLUGIN_ROOT):
        return None
    try:
        pin = version_update_lib.read_last_good()
    except OSError:
        return None
    if pin is None:
        return None
    pinned = (pin.get("version") or "").strip()
    running = _PLUGIN_ROOT.name
    # `running` is the version-stamped cache dir name. When this build executes
    # from somewhere NOT version-stamped (a DATA stage, a relocated tree), there
    # is nothing to compare — no opinion beats a false alarm.
    if not pinned or not running or "." not in running or not running[0].isdigit():
        return None
    if pinned == running:
        return None
    return (
        f"C3 last-good pin certifies {pinned}, but the janitor is RUNNING "
        f"{running} — the HMAC tamper anchor is STALE, so the dispatcher stub "
        "silently falls back to its C2-only gate (a same-tree UNSIGNED manifest, "
        "which an attacker holding cache write access could rewrite wholesale). "
        "C2 still verifies every exec, so this is a DEGRADED defense, not an open "
        "door. Cause: the pin advances only when the daemon self-updates, so a "
        "manual `claude plugin update` never re-certifies. There is no user-side "
        "re-pin command today — TRDD-ZM5LZ24Y tracks the fix."
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
    # TRDD-DKEYCHN7: key from the FIXED dir so the chain we APPEND to is signed
    # with the same key a later session VERIFIES it with (was $CLAUDE_PLUGIN_DATA).
    key = load_or_create_key(_fixed_data_dir())
    if key is None:
        return
    try:
        chain = AuditChain(chain_path, key)
        chain.append({
            "event": "detector.fire",
            "rule_id": _NAME,
            "verdict": verdict,
        })
        # S4 (TRDD-7IUTRX29): an append-per-fire chain grows unbounded AND makes each
        # full verify() walk longer every heartbeat. trim() is amortised (no-op under
        # the byte cap) and keeps verify() green via the key-signed trim-anchor.
        chain.trim()
    except OSError:
        # Append failure is non-fatal; the next fire will still chain
        # from the last successful entry. Logged via state.log_line so
        # post-mortems can correlate.
        state.log_line(_NAME, "audit-chain append failed (OSError)")


_TICKET_CODES = {
    "manifest": "SELFINT-001",
    "audit-chain": "SELFINT-002",
    "skill-preamble": "SELFINT-003",
}
# `last-good-pin` is DELIBERATELY absent — the omission is the design, not an
# oversight (`_raise_ticket` returns silently on an unmapped class, so an
# accidental gap here would be invisible; this comment is what makes it not one).
# A ticket dispatches the repair agent to fix the finding autonomously, and the
# only fix for a stale C3 pin is to re-certify a version as trusted. An agent
# that silently rewrites the trust anchor it was asked to audit has destroyed the
# property the anchor exists to provide. So this finding surfaces as a drift line
# for a human and stops there; TRDD-ZM5LZ24Y carries the actual fix.


def _raise_ticket(finding_class: str, finding: str) -> None:
    """Open a HARNESS ticket for a self-integrity finding — the janitor repairing its own machinery.

    This is the one detector whose subject IS the janitor, so it dispatches with no human in the loop.
    The `where` is the finding CLASS, not the finding's text: the text quotes a path that may have been
    chosen by whoever tampered with the file, and a dedupe key built from an attacker's string is a key
    an attacker can vary to open one ticket per fire.
    """
    code = _TICKET_CODES.get(finding_class)
    if not code:
        return
    try:
        import issue_catalog  # noqa: PLC0415 — only imported on the (rare) finding path

        r = issue_catalog.raise_issue(
            code,
            where=finding_class,
            evidence=[str(_MANIFEST_PATH)],
            path=finding,
            detail=finding,
        )
        if r.first_seen and r.line:
            print(r.line)
        elif not r.ok:
            state.log_line(_NAME, f"could not raise {code}: {r.why}")
    except Exception as exc:  # noqa: BLE001 — a ticket fault must never silence the finding itself
        state.log_line(_NAME, f"could not raise {code}: {exc}")


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
    # The C3 pin check reads inputs NOTHING above covers (the pin file and the
    # running version dir). Without this part the stale-pin finding would be
    # deduped away on every fire where the manifest and skills were untouched —
    # i.e. silenced in exactly the steady state it exists to report. A guard that
    # only fires when something ELSE changed is not a guard.
    try:
        _pin = version_update_lib.read_last_good()
    except OSError:
        _pin = None
    signature_parts.append(
        f"pin|{(_pin or {}).get('version', '')}|{_PLUGIN_ROOT.name}",
    )

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
    # The pin check sits ABOVE skill-preamble: a stale tamper anchor degrades a
    # real defense, while a missing preamble notice is an attack-surface nudge.
    # It cannot mask the preamble finding forever — the dedupe signature now
    # covers the pin, so once reported the whole detector goes quiet until one of
    # its inputs actually changes.
    for label, fn in (
        ("manifest", _check_manifest),
        ("audit-chain", _check_audit_chain),
        ("last-good-pin", _check_last_good_pin),
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
        _raise_ticket(finding_class, finding)

    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
