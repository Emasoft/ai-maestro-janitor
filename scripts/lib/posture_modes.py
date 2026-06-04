"""Three-mode posture matrix supplementing scripts/lib/posture.py.

Implements proposals 1 and 6 from the deep-posture-metrics report
(`reports/study-github-monitoring-deep/*deep-posture-metrics*.md`):

    1. A 3-mode posture matrix — `Strict` / `Balanced` / `Emergency-Exception`
       — sourced from `supply-chain-hardening-main/guidelines/strict-mode.md`.
       Each mode is a NamedTuple of (name, severity_floor, allowed_overrides,
       max_age_days_for_critical_waivers).
    6. A static DOC-only compliance cross-walk from a janitor rule_id to
       SOC2 / ISO 27001 / HIPAA control IDs (no API integration; pure
       lookup so users can answer "what does this finding mean for SOC2?").

The module is **additive** — it does NOT touch the existing
`posture.PostureGrade` / `posture.compute()` engine. The only interaction
point is `apply_mode_to_grade(grade, mode)` which returns a NEW
`PostureGrade` with a letter shifted by ±1 according to mode rules. The
original `compute()` call still produces the same grade it always has;
mode-aware callers opt in by piping that grade through this function.

Why not modify posture.py directly?
    Posture.py is the published heartbeat grader and dozens of tests +
    hooks depend on its exact output. The 3-mode matrix is a separate
    *policy layer* on top, not a new grading algorithm — keeping it in a
    sibling module preserves the no-regression invariant for Wave 6 code.

All values here are deterministic (pure stdlib, no LLM, no network) per
the deep-dive's HARD CONSTRAINT.
"""

from __future__ import annotations

from typing import NamedTuple

# Posture is imported lazily inside apply_mode_to_grade() so this module
# can be inspected (e.g. by tools listing `MODES`) without dragging the
# heartbeat engine in. The import is still cheap when it does happen —
# posture.py has zero non-stdlib deps.


class PostureMode(NamedTuple):
    """One row of the 3-mode posture matrix.

    Fields
    ------
    name
        Canonical kebab-case identifier. Stable; used as a key in
        `.janitor.toml` `[posture] mode = "..."` and in CLI flags.
    severity_floor
        The LOWEST severity that should ride the daily heartbeat drift
        line. `"MAJOR"` means MAJOR + HIGH + CRITICAL surface (MINOR
        stays quiet); `"CRITICAL"` means only CRITICAL surfaces.
        Higher floors = quieter heartbeat.
    allowed_overrides
        Which `.janitor.toml` suppression mechanisms are honoured under
        this mode. A tuple of identifiers so the membership test is a
        single `in` check.
            * `"sha"`        — per-finding SHA suppression
            * `"glob"`       — path-glob suppression
            * `"detector"`   — whole-detector mute
            * `"env"`        — env-var bypass (`JANITOR_SKIP_*`)
            * `"first-run"`  — `.janitor-trusted` marker
        Strict mode keeps only SHA + glob (most narrow); Emergency-
        Exception keeps every override since it is a per-incident
        carve-out. Balanced keeps everything except `"first-run"` so
        a fresh clone still passes through the untrusted-repo guard.
    max_age_days_for_critical_waivers
        How long a `.janitor.toml` suppression of a CRITICAL finding
        stays valid before the heartbeat re-surfaces it. Tied to the
        report's spec — Strict=7, Balanced=30, Emergency-Exception=90.
        The intent is that Strict's short window forces re-review,
        Balanced's medium window matches a normal sprint cadence, and
        Emergency-Exception's long window covers the realistic
        rollback / incident-response timeline for accepted risk.
    """

    name: str
    severity_floor: str
    allowed_overrides: tuple[str, ...]
    max_age_days_for_critical_waivers: int


# Canonical mode definitions. Built once at import time and immutable
# (NamedTuple + module-level tuple).
#
# Order matches the report's narrative order (Strict → Balanced →
# Emergency-Exception) and is preserved in `MODES` so callers iterating
# the tuple see them in escalation order.
STRICT = PostureMode(
    name="strict",
    # Strict surfaces MAJOR+ — the supply-chain-hardening guideline calls
    # out that MAJOR findings under STRICT must be treated like HIGH.
    severity_floor="MAJOR",
    # Only narrow per-finding (SHA) or per-path (glob) suppressions
    # allowed. Whole-detector mutes and env-var bypasses are forbidden
    # under STRICT because they cover too wide a blast radius.
    allowed_overrides=("sha", "glob"),
    max_age_days_for_critical_waivers=7,
)

BALANCED = PostureMode(
    name="balanced",
    # Balanced is the existing janitor default. HIGH+ surfaces;
    # MAJOR/MINOR are part of the score but don't ride the heartbeat
    # individually (consistent with the once-per-day cadence).
    severity_floor="HIGH",
    # Balanced honours every override mechanism EXCEPT `"first-run"` —
    # a freshly-cloned repo should still hit the untrusted-repo guard
    # even under Balanced, per Proposal 7 of the report.
    allowed_overrides=("sha", "glob", "detector", "env"),
    max_age_days_for_critical_waivers=30,
)

EMERGENCY_EXCEPTION = PostureMode(
    name="emergency-exception",
    # Emergency-Exception is a per-command carve-out, never the default.
    # The heartbeat behaviour intentionally matches Balanced — the mode
    # affects what *can be suppressed*, not what *surfaces*.
    severity_floor="HIGH",
    # All five override mechanisms permitted, including `"first-run"`
    # (a triaged incident on an untrusted repo gets the same write-out
    # privilege as any other waiver).
    allowed_overrides=("sha", "glob", "detector", "env", "first-run"),
    max_age_days_for_critical_waivers=90,
)


# Public tuple. Order matters: `MODES[0]` is the strictest, `MODES[-1]`
# is the most lenient. Tests rely on this ordering.
MODES: tuple[PostureMode, ...] = (STRICT, BALANCED, EMERGENCY_EXCEPTION)


# Name → mode lookup. Built once at import time. Using a frozen dict-ish
# pattern (regular dict that we never mutate) so callers get O(1) lookup
# while keeping the module's `from __future__ import annotations` clean.
_BY_NAME: dict[str, PostureMode] = {m.name: m for m in MODES}


def default_mode() -> PostureMode:
    """Return the janitor's default posture mode.

    Balanced is the default because (a) it matches the existing posture
    grading behaviour exactly (no regression for existing users) and
    (b) the deep-posture-metrics report explicitly says Balanced is the
    starting point — Strict is opt-in via `.janitor.toml`, and
    Emergency-Exception is per-incident only, never a default.
    """
    return BALANCED


def select_mode(name: str) -> PostureMode:
    """Look up a `PostureMode` by its canonical kebab-case name.

    Raises
    ------
    KeyError
        If `name` is not one of the three canonical names. We
        deliberately do NOT fall back to BALANCED on an unknown name —
        a typo in `.janitor.toml` (`posture.mode = "stict"`) must be a
        loud failure, not a silent drift back to default. The caller
        decides whether to retry with `default_mode()` after catching
        the KeyError.

    The lookup is case-sensitive on purpose — `posture.mode = "Strict"`
    in TOML is a user mistake and a noisy KeyError is the right
    response. Mode names are documented as lowercase kebab-case in the
    user-facing `.janitor.toml` reference.
    """
    if name not in _BY_NAME:
        # Include the legal names in the error message so the user
        # doesn't have to dig through docs to figure out what to fix.
        legal = ", ".join(m.name for m in MODES)
        msg = f"unknown posture mode {name!r}; expected one of: {legal}"
        raise KeyError(msg)
    return _BY_NAME[name]


# Letter ladder used by `apply_mode_to_grade()`. Order is best-to-worst
# so shifting "down" (`+1` index) makes the grade worse and shifting
# "up" (`-1` index) makes it better. F is the floor; A is the ceiling.
_LETTER_LADDER: tuple[str, ...] = ("A", "B", "C", "D", "F")
_LETTER_INDEX: dict[str, int] = {ch: i for i, ch in enumerate(_LETTER_LADDER)}


def apply_mode_to_grade(grade, mode: PostureMode):  # type: ignore[no-untyped-def]
    """Return a new PostureGrade with the letter shifted by the mode.

    Mode semantics:
      * `strict`              — subtract 1 letter of forgiveness, i.e.
                                tighten the grade by one band (A→B, B→C,
                                C→D, D→F, F→F). This models "STRICT
                                requires 0 CRITICAL, 0 HIGH, **0
                                MAJOR**" — under STRICT a finding that
                                would earn B under Balanced earns C.
      * `balanced`            — no shift; grade passes through.
      * `emergency-exception` — add 1 letter of forgiveness (F→D, D→C,
                                C→B, B→A, A→A). This models "the
                                incident is acknowledged, the
                                workaround is logged, do not double-
                                penalise the operator while they
                                execute the rollback plan".

    The MAL-* short-circuit in `posture.compute()` is **respected** — if
    the caller's `grade.mal_advisories > 0`, the letter remains F
    regardless of mode. A known-malicious package installed is an
    emergency that emergency-exception MUST NOT mask.

    Score, severity counts, and the `mal_advisories` field are passed
    through unchanged. Only the letter is mode-adjusted; the numeric
    score still reflects the raw weighted deduction so a quieter letter
    under Emergency-Exception is still backed by a low score the user
    can interrogate.

    Parameters
    ----------
    grade
        A `posture.PostureGrade` instance. Type is annotated dynamically
        via `# type: ignore` so this module avoids the circular import
        at type-check time — the runtime import is lazy and cheap.
    mode
        A `PostureMode` from `MODES` (or returned by `select_mode()` /
        `default_mode()`). Unknown modes go through the no-op branch —
        not raising, because by construction a `PostureMode` can only
        come from `MODES` so an unknown name is impossible. The branch
        exists as a future-proofing belt-and-braces.

    Returns
    -------
    posture.PostureGrade
        New instance — `PostureGrade` is a `NamedTuple` so it's already
        immutable; we use `_replace()` for the letter swap.
    """
    # Lazy import to avoid the circular dep with posture.py at module
    # import time. Cost is one cache hit on subsequent calls.
    # posture is imported inside the function on purpose; see module
    # docstring "Why not modify posture.py directly?" for context.
    from posture import PostureGrade  # type: ignore[import-not-found]  # noqa: PLC0415

    # MAL-* short-circuit — emergency-exception cannot upgrade an F
    # caused by a known-malicious package install. Strict's downgrade
    # is a no-op when the letter is already F. Either way: bail out
    # before any letter math.
    if grade.mal_advisories > 0 or grade.letter == "F" and mode.name == "strict":
        return grade

    # Compute the letter shift. Strict tightens by 1; emergency-
    # exception loosens by 1; balanced (and any unknown mode that
    # somehow slips past `select_mode`) is a no-op.
    if mode.name == "strict":
        shift = +1   # toward F
    elif mode.name == "emergency-exception":
        shift = -1   # toward A
    else:
        shift = 0    # balanced — no change

    if shift == 0:
        return grade

    # Clamp to the bounds of the ladder. The `max(0, ...)` and
    # `min(len-1, ...)` keep A and F as fixed points respectively —
    # strict cannot push past F, emergency-exception cannot lift past A.
    old_idx = _LETTER_INDEX.get(grade.letter, _LETTER_INDEX["A"])
    new_idx = max(0, min(len(_LETTER_LADDER) - 1, old_idx + shift))
    new_letter = _LETTER_LADDER[new_idx]

    if new_letter == grade.letter:
        # No effective change — return the input to keep object identity
        # stable for callers that compare via `is`.
        return grade

    return PostureGrade(
        letter=new_letter,
        score=grade.score,
        critical=grade.critical,
        high=grade.high,
        major=grade.major,
        minor=grade.minor,
        mal_advisories=grade.mal_advisories,
    )


# --------------------------------------------------------------------- #
# Proposal 6 — DOC-only compliance cross-walk.                          #
#                                                                       #
# Static mapping rule_id → { framework: [control_ids] }. No code        #
# integration, no auditor APIs, no evidence collection. Pure lookup.    #
#                                                                       #
# Source: Section "Proposal 6 — Compliance-framework cross-walk         #
# (DOC-ONLY)" of the deep-posture-metrics report. Rows are exactly the  #
# table in that section — we preserve them as data so a future          #
# `/janitor-doctor --with-compliance` flag can render them without a    #
# second source of truth.                                               #
# --------------------------------------------------------------------- #


# Frozen lookup table. Keyed by janitor rule_id. Values are dicts of
# framework name → list of control identifiers. Lists (not sets) so the
# order is deterministic and printable — the auditor-facing doc renders
# controls in the order the report lists them.
_COMPLIANCE_MAP: dict[str, dict[str, list[str]]] = {
    "osv_mal_advisories": {
        "OWASP_Agentic": ["A04 Supply chain"],
        "MITRE_ATTACK":  ["T1195.002"],
        "SOC2":          ["CC7.1"],
        "ISO27001":      ["A.14.2.5"],
        "HIPAA":         ["§164.312(c)(1)"],
        "NIST_800_53":   ["SI-3", "SR-3"],
    },
    "mcp_lockfile_drift": {
        "OWASP_Agentic": ["A05 Lifecycle integrity"],
        "MITRE_ATTACK":  ["T1199"],
        "SOC2":          ["CC6.1"],
        "ISO27001":      ["A.9.4.1"],
        "HIPAA":         ["§164.312(a)(2)(iv)"],
        "NIST_800_53":   ["AC-3"],
    },
    "phantom_aiconfig": {
        "OWASP_Agentic": ["A04 Supply chain"],
        "MITRE_ATTACK":  ["T1574.002"],
        "SOC2":          ["CC7.1"],
        "ISO27001":      ["A.12.2.1"],
        "HIPAA":         ["§164.312(b)"],
        "NIST_800_53":   ["SI-7"],
    },
    "cargo_vet_missing": {
        "OWASP_Agentic": ["A04 Supply chain"],
        "MITRE_ATTACK":  ["T1195.001"],
        "SOC2":          ["CC8.1"],
        "ISO27001":      ["A.14.2.7"],
        "HIPAA":         ["§164.308(a)(1)(ii)(D)"],
        "NIST_800_53":   ["SA-12"],
    },
    "gh_actions_unpinned": {
        "OWASP_Agentic": ["A05 Lifecycle integrity"],
        "MITRE_ATTACK":  ["T1078.003"],
        "SOC2":          ["CC8.1"],
        "ISO27001":      ["A.14.2.2"],
        "HIPAA":         ["§164.308(a)(4)(ii)(A)"],
        "NIST_800_53":   ["CM-9"],
    },
    "npm_ignore_scripts_off": {
        "OWASP_Agentic": ["A04 Supply chain"],
        "MITRE_ATTACK":  ["T1059"],
        "SOC2":          ["CC7.1"],
        "ISO27001":      ["A.12.5.1"],
        "HIPAA":         ["§164.312(b)"],
        "NIST_800_53":   ["CM-7"],
    },
    "secret_in_settings_json": {
        "OWASP_Agentic": ["A03 Sensitive info"],
        "MITRE_ATTACK":  ["T1552.001"],
        "SOC2":          ["CC6.3"],
        "ISO27001":      ["A.9.4.4"],
        "HIPAA":         ["§164.312(d)"],
        "NIST_800_53":   ["IA-5"],
    },
}


def compliance_map(rule_id: str) -> dict[str, list[str]]:
    """Return the compliance framework cross-walk for a janitor rule_id.

    DOC-ONLY — there is no runtime evaluation, no compliance scoring,
    no auditor integration. The mapping is a static lookup table built
    once at import time from the deep-posture-metrics report.

    Returns a deep-copied dict so callers can safely mutate the result
    without polluting subsequent lookups. The frameworks present are:
        * `OWASP_Agentic` — OWASP Agentic Top 10 categories
        * `MITRE_ATTACK`  — MITRE ATT&CK technique IDs
        * `SOC2`          — SOC 2 Common Criteria
        * `ISO27001`      — ISO/IEC 27001 Annex A controls
        * `HIPAA`         — HIPAA Security Rule citations
        * `NIST_800_53`   — NIST 800-53 control families

    Parameters
    ----------
    rule_id
        A janitor detector identifier, e.g. `"osv_mal_advisories"`.

    Returns
    -------
    dict
        Framework → list of control IDs. Empty dict if `rule_id` is
        unmapped — we return `{}` rather than raising because callers
        rendering the doctor report will commonly skip the compliance
        column for un-cross-walked rules rather than abort.
    """
    raw = _COMPLIANCE_MAP.get(rule_id)
    if raw is None:
        return {}
    # Defensive copy so callers can mutate without affecting the table.
    return {framework: list(controls) for framework, controls in raw.items()}
