"""SessionStart harness self-test (TRDD-B0SABNP8) — fail LOUD when Claude Code changed under us.

The janitor is COUPLED to Claude Code harness internals — plugin-option env-var
DELIVERY, the on-disk statusline context snapshot, the integer-coercion of config
knobs, and the bare-line subagent-spawn marker contract. CC ships minor releases
roughly weekly, and several have BROKEN this coupling SILENTLY (2.1.207 dropped
project-scope option delivery; 2.1.208 briefly reset the context window to 200k;
2.1.211 changed which integer spellings env vars accept). Each was found by a MANUAL
changelog sweep, AFTER the janitor had already been degrading. This module is the
missing startup check: a fast, fail-open self-test the SessionStart hook runs and
SHOUTS about (a drift line + a findings-ledger entry) when the harness moved.

The load-bearing design rule (ATOM-B0SA-EFCY): at least one probe reads a REAL
CC-produced artifact, so the test goes red on an ACTUAL CC change — not only on a
janitor self-edit (which CI already catches). Two probes observe live CC surfaces
(option delivery, the on-disk snapshot schema); two are internal self-consistency
guards, labelled as such so they give no false confidence.

NEVER RAISES. Its I/O is bounded to reading ``os.environ`` + at most three SMALL local
files (the USER settings.json, the on-disk context snapshot, the two detector source
files probe 4 reads) — NO subprocess, NO network, NO ``/roles``, NO transcript read.
Every path is an INJECTED argument (defaulting to the real location, resolved at CALL
time so a frozen ``Path.home()`` module constant can never point at a stale HOME — the
test-isolation trap that once corrupted real state) so tests drive fixtures and assert
zero expensive I/O.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence, TypeGuard

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import state  # noqa: E402  -- sibling lib

# The fixed finding vocabulary for every self-test failure — one code, one src, so the
# ledger + `/janitor-findings` group them and the dedupe stamp keys on the message set.
CODE = "HARNESS-DRIFT"
SRC = "harness-selftest"

# Severities in the UPPERCASE vocabulary the findings ledger + notify channel rank
# (notify pushes at >= HIGH). The two REAL-ARTIFACT probes are HIGH — a silent option
# revert / a destructive /compact on a bogus number both actively degrade the user; the
# two self-consistency guards are MEDIUM — surfaced but not push-worthy on their own.
_SEV_HIGH = "HIGH"
_SEV_MEDIUM = "MEDIUM"

# The subagent-spawn marker vocabulary this probe CARRIES. Two sources of truth
# (ATOM-B0SA-MRKR): the eight memory markers in detectors/memory-maintenance.py::_MARKERS,
# AND the literal [janitor-ticket] in detectors/ticket-dispatch.py — the latter is NOT in
# _MARKERS. Keep this list in sync with both source files (probe 4 asserts exactly that).
_MEMORY_MARKERS = (
    "[janitor-memory-split]",
    "[janitor-memory-repair]",
    "[janitor-memory-atomize]",
    "[janitor-memory-harvest]",
    "[janitor-memory-retro-lesson]",
    "[janitor-memory-consolidate]",
    "[janitor-memory-conflict]",
    "[janitor-memory-enrich]",
)
_TICKET_MARKER = "[janitor-ticket]"

# The plugin-id substring that identifies the janitor's own pluginConfigs block. CC keys
# pluginConfigs by a plugin id whose exact form (bare name vs "name@marketplace") is the
# one CC-internal shape we cannot verify offline, so we match by CONTAINMENT — both known
# forms carry this substring — rather than hard-asserting a format (ATOM-B0SA-EFCY / the
# RESIDUAL-2 robustness directive).
_JANITOR_ID_SUBSTR = "ai-maestro-janitor"

# A probe returns (severity, message) on FAIL, or None on pass / inapplicable.
ProbeResult = Optional[tuple[str, str]]


def selftest_enabled() -> bool:
    """Master opt-out (NEW knob, default true)."""
    return state.is_truthy_env("CLAUDE_PLUGIN_OPTION_HARNESS_SELFTEST_ENABLED", True)


# --------------------------------------------------------------------------------------
# Probe 1 — REAL ARTIFACT: plugin-option DELIVERY (the CC 2.1.207 breakage).
# --------------------------------------------------------------------------------------
def _janitor_option_keys(env: Mapping[str, str]) -> Optional[set[str]]:
    """The janitor's own userConfig keys (lowercase) from its plugin.json under
    CLAUDE_PLUGIN_ROOT, or None when unresolvable (⇒ caller does not intersect).

    Verified mapping (against 5 real knobs; no camelCase env var exists in the tree):
    a userConfig key maps to ``CLAUDE_PLUGIN_OPTION_<UPPER(key)>``.
    """
    root = str(env.get("CLAUDE_PLUGIN_ROOT", "")).strip()
    if not root:
        return None
    try:
        data = json.loads((Path(root) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    uc = data.get("userConfig")
    return {str(k) for k in uc} if isinstance(uc, dict) else None


def probe_option_delivery(
    settings_paths: Sequence[os.PathLike[str] | str],
    env: Mapping[str, str],
    *,
    known_keys: Optional[set[str]] = None,
) -> ProbeResult:
    """REAL-ARTIFACT probe (ATOM-B0SA-2207) — did CC still DELIVER the janitor's options?

    The CC 2.1.207 breakage dropped option DELIVERY: a knob a user declared in the
    janitor's ``pluginConfigs`` block goes ABSENT from the process env. That cannot be
    caught by coercing a literal — ``coerce_int(None)`` → default is intended fail-open —
    so this probe compares DECLARED knobs against actual env presence.

    RESIDUAL-1: it reads ONLY the USER-scope ``~/.claude/settings.json`` (the caller's
    default `settings_paths`). A PROJECT ``.claude/settings.json`` `pluginConfigs` is
    INTENTIONALLY no longer delivered post-2.1.207, so checking it would be a PERMANENT
    false positive on a healthy machine — the caller must never pass a project path.

    RESIDUAL-2 robustness: the pluginConfigs plugin-id key format is the one CC-internal
    shape we cannot verify offline, so we identify the janitor's block by an id CONTAINING
    ``ai-maestro-janitor`` and further scope the checked keys to the janitor's OWN
    userConfig keys (`known_keys`, from plugin.json). No confidently-attributable janitor
    block, or nothing declared → inapplicable → pass (green). Only a knob the janitor
    genuinely declared at USER scope yet CC did not deliver → FAIL.
    """
    if known_keys is None:
        known_keys = _janitor_option_keys(env)
    declared: set[str] = set()
    for sp in settings_paths or ():
        try:
            data = json.loads(Path(sp).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # absent / unreadable / not-JSON user settings → nothing to check
        pc = data.get("pluginConfigs") if isinstance(data, dict) else None
        if not isinstance(pc, dict):
            continue
        for plugin_id, cfg in pc.items():
            if _JANITOR_ID_SUBSTR not in str(plugin_id).lower():
                continue  # attribute the block to the janitor by id, or skip it
            if not isinstance(cfg, dict):
                continue
            for key in cfg:
                k = str(key)
                if known_keys is not None and k not in known_keys:
                    continue  # scope to knobs CC still claims to deliver (a typo/foreign key can't false-fail)
                declared.add(k)
    if not declared:
        return None
    undelivered = sorted(k for k in declared if f"CLAUDE_PLUGIN_OPTION_{k.upper()}" not in env)
    if not undelivered:
        return None
    shown = ", ".join(undelivered[:4]) + (" …" if len(undelivered) > 4 else "")
    return (
        _SEV_HIGH,
        f"plugin-option delivery broke: {len(undelivered)} user-scope knob(s) declared in "
        f"settings.json but CLAUDE_PLUGIN_OPTION_* is absent from env ({shown}) — the CC "
        f"2.1.207-class delivery drop; the janitor is silently running on defaults",
    )


# --------------------------------------------------------------------------------------
# Probe 2 — REAL ARTIFACT: context-snapshot schema (the CC 2.1.208 breakage).
# --------------------------------------------------------------------------------------
def _is_plain_int(v: object) -> TypeGuard[int]:
    """True iff v is a real int — NOT a bool (bool is an int subclass in Python).

    A ``TypeGuard[int]`` (not a plain ``bool``) so the type checker narrows the argument
    to ``int`` in the True branch — the guarded ``tokens >= 0`` / ``tokens > window``
    comparisons below are then provably not run against ``None``.
    """
    return isinstance(v, int) and not isinstance(v, bool)


def probe_context_snapshot_schema(
    snapshot_path: os.PathLike[str] | str | None,
) -> ProbeResult:
    """REAL-ARTIFACT probe (the CC 2.1.208-class breakage) — is the on-disk context
    snapshot still in the schema ``token_meter.resolve_context`` depends on?

    The statusline writes ``.claude/janitor/context-usage.<session_id>.json``; a CC bug
    that reports a bogus window/percentage lands in that ACTUAL file, and the context-usage
    hook then fires ``/compact`` AND denies the tool call — destroying real conversation —
    on the bad number. This reads that file and validates the fields resolve_context reads:
    ``pct`` an int; when present ``tokens``/``window`` positive ints; and the 2.1.208
    signature ``tokens > window`` (impossible in a healthy session) is absent.

    Absent file (fresh session / statusline not yet run) OR an unparseable file (a torn
    write → resolve_context fails open, no destructive action) → inapplicable → pass. Only
    a PARSEABLE dict in the bad shape FAILS. Reading this ONE few-KB JSON (already read
    every PreToolUse by resolve_context) is O(small) and, placed after the SessionStart
    survival writers, cannot delay any resume/renew emission.
    """
    if not snapshot_path:
        return None
    try:
        snap = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # absent / torn write → resolve_context degrades safely → not the bug
    if not isinstance(snap, dict):
        return None
    problems: list[str] = []
    if not _is_plain_int(snap.get("pct")):
        problems.append("pct missing/non-int")
    tokens, window = snap.get("tokens"), snap.get("window")
    tok_ok = _is_plain_int(tokens) and tokens >= 0
    win_ok = _is_plain_int(window) and window > 0
    if "tokens" in snap and not tok_ok:
        problems.append("tokens non-int/negative")
    if "window" in snap and not win_ok:
        problems.append("window absurd (not a positive int)")
    if _is_plain_int(tokens) and _is_plain_int(window) and tokens > window:
        problems.append("tokens > window (the 2.1.208 window-reset signature)")
    if not problems:
        return None
    return (
        _SEV_HIGH,
        f"context snapshot schema broke: {', '.join(problems)} — the CC 2.1.208-class "
        f"anomaly that makes the context guard fire /compact on a bogus number",
    )


# --------------------------------------------------------------------------------------
# Probe 3 — SELF-CONSISTENCY guard: integer spellings (NOT a CC-drift detector).
# --------------------------------------------------------------------------------------
def probe_int_spellings() -> ProbeResult:
    """SELF-CONSISTENCY guard — honest per ATOM-B0SA-EFCY: this catches a JANITOR
    regression that would desync from CC, NOT a CC change itself.

    Asserts ``state.parse_nonneg_int`` still accepts every CC-2.1.211 integer spelling and
    rejects the non-integers, keeping the janitor's ~50 int knobs in lockstep with CC (and
    with tests/test_state_parse_nonneg_int.py — the cases mirror it). Calls the parser via
    the module attribute so a test can monkeypatch it to simulate the regression.
    """
    accept = {
        "270000": 270_000,
        "64_000": 64_000,
        "270_000": 270_000,
        "0": 0,
        "1e6": 1_000_000,
        "2.7e5": 270_000,
        "1.5e6": 1_500_000,
    }
    reject = ("1.5", "-5", "-1e6", "0x10", "1__0", "inf", "nan", "900 seconds", "")
    bad: list[str] = []
    for s, want in accept.items():
        if state.parse_nonneg_int(s) != want:
            bad.append(f"accept {s!r}")
    for s in reject:
        if state.parse_nonneg_int(s) is not None:
            bad.append(f"reject {s!r}")
    if not bad:
        return None
    return (
        _SEV_MEDIUM,
        f"int-coercion desync: parse_nonneg_int no longer matches the CC 2.1.211 spellings "
        f"({', '.join(bad[:5])}) — janitor knobs may silently revert to defaults",
    )


# --------------------------------------------------------------------------------------
# Probe 4 — CONTRACT-SHAPE guard: subagent-spawn marker vocabulary.
# --------------------------------------------------------------------------------------
def _read_text(path: os.PathLike[str] | str | None) -> Optional[str]:
    if not path:
        return None
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def _default_detector_paths(
    memory_maintenance_path: os.PathLike[str] | str | None,
    ticket_dispatch_path: os.PathLike[str] | str | None,
    env: Mapping[str, str],
) -> tuple[Optional[Path], Optional[Path]]:
    root = str(env.get("CLAUDE_PLUGIN_ROOT", "")).strip()
    det = Path(root) / "scripts" / "detectors" if root else None
    mm = Path(memory_maintenance_path) if memory_maintenance_path else (det / "memory-maintenance.py" if det else None)
    td = Path(ticket_dispatch_path) if ticket_dispatch_path else (det / "ticket-dispatch.py" if det else None)
    return mm, td


def probe_marker_path(
    *,
    memory_maintenance_path: os.PathLike[str] | str | None = None,
    ticket_dispatch_path: os.PathLike[str] | str | None = None,
    env: Optional[Mapping[str, str]] = None,
) -> ProbeResult:
    """CONTRACT-SHAPE guard (ATOM-B0SA-MRKR) — honest per ATOM-B0SA-EFCY: it asserts the
    contract SHAPE, it cannot prove Claude will spawn the agent (a rule-driven action, not
    a callable).

    Asserts the marker vocabulary this module carries still matches BOTH sources — the six
    ``[janitor-memory-*]`` markers in detectors/memory-maintenance.py::_MARKERS AND the
    literal ``[janitor-ticket]`` in detectors/ticket-dispatch.py — AND that
    ``state.sanitize_for_drift_line`` still defangs a mimicked ``[janitor-…]`` into
    ``⟦janitor-…⟧`` (the anti-mimicry guarantee dispatch.py's marker protocol relies on).

    A source file that cannot be read is inapplicable for its half (fail-open — a broken
    read is not evidence the marker was renamed).
    """
    env = os.environ if env is None else env
    mm_path, td_path = _default_detector_paths(memory_maintenance_path, ticket_dispatch_path, env)
    problems: list[str] = []

    mm_text = _read_text(mm_path)
    if mm_text is not None:
        missing = [m for m in _MEMORY_MARKERS if m not in mm_text]
        if missing:
            problems.append(f"memory markers absent from memory-maintenance.py: {', '.join(missing)}")

    td_text = _read_text(td_path)
    if td_text is not None and _TICKET_MARKER not in td_text:
        problems.append(f"{_TICKET_MARKER} absent from ticket-dispatch.py")

    if state.sanitize_for_drift_line("[janitor-resume]") != "⟦janitor-resume⟧":
        problems.append("sanitize_for_drift_line no longer defangs a mimicked [janitor-…] marker")

    if not problems:
        return None
    return (_SEV_MEDIUM, "subagent-spawn marker contract drift: " + "; ".join(problems))


# --------------------------------------------------------------------------------------
# Default real-path resolution + the run/format/dedupe surface.
# --------------------------------------------------------------------------------------
def _default_settings_paths(env: Mapping[str, str]) -> list[Path]:
    """USER-scope ``~/.claude/settings.json`` ONLY (RESIDUAL-1). Home resolved at CALL
    time — prefer the HOME env (so a sandboxed subprocess/test is honored) then
    ``Path.home()`` — never a frozen module constant (the test-isolation trap that once
    corrupted real state)."""
    home = str(env.get("HOME", "")).strip()
    base = Path(home) if home else Path.home()
    return [base / ".claude" / "settings.json"]


def _default_snapshot_path(env: Mapping[str, str]) -> Optional[Path]:
    """The real on-disk snapshot path, mirroring ``token_meter.read_context_snapshot``:
    ``$CLAUDE_PROJECT_DIR/.claude/janitor/context-usage.$CLAUDE_CODE_SESSION_ID.json``.
    None when either env var is unset (⇒ probe 2 inapplicable)."""
    project = str(env.get("CLAUDE_PROJECT_DIR", "")).strip()
    sid = str(env.get("CLAUDE_CODE_SESSION_ID", "")).strip()
    if not project or not sid:
        return None
    return Path(project) / ".claude" / "janitor" / f"context-usage.{sid}.json"


def run_selftest(
    *,
    snapshot_path: os.PathLike[str] | str | None = None,
    settings_paths: Optional[Sequence[os.PathLike[str] | str]] = None,
    env: Optional[Mapping[str, str]] = None,
    now: Optional[int] = None,
) -> list[tuple[str, str, str]]:
    """Run every probe (resolving the default paths when not injected) and return the list
    of ``(code, severity, msg)`` failures — empty on all-green. NEVER raises: a probe that
    itself throws is swallowed (fail-open) so the self-test can never break the SessionStart
    survival path placed after it. Returns [] immediately when the feature is opted out."""
    if not selftest_enabled():
        return []
    import time  # noqa: PLC0415 -- stdlib, keep module import-light

    env = os.environ if env is None else env
    if now is None:
        now = int(time.time())
    if settings_paths is None:
        settings_paths = _default_settings_paths(env)
    if snapshot_path is None:
        snapshot_path = _default_snapshot_path(env)

    probes = (
        lambda: probe_option_delivery(settings_paths, env),
        lambda: probe_context_snapshot_schema(snapshot_path),
        lambda: probe_int_spellings(),
        lambda: probe_marker_path(env=env),
    )
    failures: list[tuple[str, str, str]] = []
    for run in probes:
        try:
            res = run()
        except Exception:  # noqa: BLE001 -- a probe fault must never break the self-test
            res = None
        if res is not None:
            sev, msg = res
            failures.append((CODE, sev, msg))
    return failures


def format_drift_line(failures: Sequence[tuple[str, str, str]]) -> str:
    """The one-line stdout drift string for a non-empty failure set. Empty on all-green.

    The content is entirely janitor-authored (fixed prose + a known-vocabulary option-key /
    marker set), so it is NOT re-sanitized — sanitizing would mangle the readable
    ``[ai-maestro-janitor]`` prefix, and no untrusted text reaches it."""
    if not failures:
        return ""
    parts = "; ".join(msg for _, _, msg in failures)
    return (
        f"⚠ [ai-maestro-janitor] harness self-test: {len(failures)} Claude Code "
        f"compatibility probe(s) FAILED — {parts}. The janitor may be silently degraded — "
        f"run /janitor-findings, and check the CC changelog for a breaking release."
    )


def failure_digest(failures: Sequence[tuple[str, str, str]]) -> str:
    """A stable content-hash of the failure SET (ATOM-B0SA-DDUP): sha256 over the sorted
    ``(code, msg)`` pairs. No ``CLAUDE_CODE_VERSION`` exists in-memory and reading the real
    version needs a forbidden subprocess, so the dedupe key is the failure CONTENT alone;
    it self-clears when a CC upgrade empties the set. Empty string for an empty set."""
    if not failures:
        return ""
    h = hashlib.sha256()
    for code, msg in sorted((code, msg) for code, _, msg in failures):
        h.update(code.encode("utf-8"))
        h.update(b"\x00")
        h.update(msg.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()
