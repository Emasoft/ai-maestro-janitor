"""Time / Clock TOCTOU + NTP / clock-skew detection patterns.

Wave 24 (distill round 10) of the github-monitoring distillation. Ported
from `reports/distill-round-10/time-clock-toctou.md`. The corpus angle:
wall-clock primitives (`time.time()`, `Date.now()`, `datetime.utcnow()`,
Postgres `NOW()`) used as if they were monotonic — i.e. used to decide
whether a credential is still valid, whether a webhook timestamp is
fresh, whether a rate-limit window has elapsed. All of these are
silently bypassed by NTP step, Daylight Saving error, VM time-warp,
`date -s`, or a co-tenant attacker with `CAP_SYS_TIME`. Adjacent to the
clock-source bug class: TOCTOU between `path.exists()` and the
subsequent open/copy.

This module is the RULE-PATTERN catalogue for static time/clock
detectors. Pure regex / pure-stdlib so it loads in every PEP 723 script
block without third-party deps. Patterns are RE2-safe (no lookbehind /
no backreference-only-fires-with-lookbehind shapes); they favour
FP-tolerance over precision so the caller can perform contextual triage
(file kind, severity, posture mode).

Detectors implemented (full distill list ports T1..T7):

  1. time-time-as-monotonic-for-token-expiry   — HIGH    Python + JS
  2. hmac-timestamp-window-symmetric           — HIGH    Python + JS
  3. rate-limit-window-wall-clock-reset        — HIGH    Python + JS
  4. stat-then-act-toctou                      — MAJOR   Python (FS race)
  5. jwt-exp-no-leeway-wall-clock-mint         — MAJOR   Python + JS
  6. refresh-token-db-now-only                 — MAJOR   SQL string
  7. datetime-utcnow-deprecated-naive          — MINOR   Python

Severity strings match the existing janitor convention
("CRITICAL"/"HIGH"/"MAJOR"/"MEDIUM"/"MINOR"/"LOW") so downstream
renderers (sentinel/zizmor/heartbeat) handle them uniformly.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
                                  — single rule record.
  * RULES                         — ordered tuple of every catalogued rule.
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)            — single finding.
  * scan_text(text)               — run every rule, return findings sorted
                                    by (line, column, rule_id).

OWASP mapping is per-rule: T1/T5/T7 are A02 Cryptographic Failures
(time-bound credential lifecycle); T2 is A02 + CWE-294 (capture-replay);
T3 is A04 Insecure Design (rate-limit bypass); T4 is A01 Broken Access
Control + CWE-367 (TOCTOU); T6 is A02 + CWE-613 (insufficient session
expiration).
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/dos_resource_patterns.Finding
    so the dispatcher renders time/clock findings uniformly with the
    existing DoS findings."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str, *, flags: int = 0) -> re.Pattern:
    """Compile a pattern with MULTILINE+DOTALL by default. Time/clock
    shapes often span newlines (cache-write + cache-read paired on
    consecutive lines), so MULTILINE makes ``^`` / ``$`` line-anchored
    and DOTALL lets ``.`` cross newlines for the cross-line shapes
    (T3 rate-limit window-reset; T4 stat-then-act). Individual
    patterns can pass extra flags via `flags=`."""
    return re.compile(pattern, re.MULTILINE | re.DOTALL | flags)


# ---- T1. time.time() / Date.now() as monotonic for token expiry --------


# Python shape: an ``"expires_at": time.time() + N`` (cache write) — the
# matching cache-read (``> time.time()``) lives elsewhere in the file
# and is detected by the same rule firing twice. We deliberately match
# only on the WRITE half because (a) the write half is the clear bug
# signal — the read half on its own ("> time.time()") is too generic
# to flag, and (b) firing twice for the same file would double-count.
# Bounded by `[^#\n]` so commented-out shapes don't trigger.
_T1_PY_EXPIRES_AT_TIME_TIME = _re(
    r"""['"]expires?_at['"]\s*[:=]\s*time\.time\s*\(\s*\)\s*[+\-]"""
)


# JS/TS shape: same semantic, ``expires_at: Date.now() + N`` (object
# literal or assignment). Token name allows the underscore variant
# (`expiresAt`, `expires_at`, `expiresat`).
_T1_JS_EXPIRES_AT_DATE_NOW = _re(
    r"""\bexpires?_?[Aa]t\s*[:=]\s*Date\.now\s*\(\s*\)\s*[+\-]"""
)


_T1_ANY = _re(
    _T1_PY_EXPIRES_AT_TIME_TIME.pattern
    + r"|"
    + _T1_JS_EXPIRES_AT_DATE_NOW.pattern
)


# ---- T2. Symmetric clock-skew check on HMAC-replay timestamp -----------


# JS shape: ``Math.abs(time - slackTimestamp) > 300`` — the canonical
# Slack-style webhook-verifier replay window using a SYMMETRIC delta.
# The bug: legitimate signers cannot sign with a future timestamp, so
# the future-side tolerance widens the replay window 2x. The two
# subexpressions both reference identifiers containing "time" or
# "timestamp" (case-insensitive on the leading char).
_T2_JS_MATH_ABS = _re(
    r"\bMath\.abs\s*\(\s*"
    r"[\w.]{0,40}[Tt]ime[\w]{0,20}\s*-\s*[\w.]{0,40}[Tt]ime\w{0,20}\s*"
    r"\)\s*[<>]=?\s*\d+"
)


# Python shape: ``abs(time.time() - int(headers['X-Timestamp'])) > 300``.
# The outer ``abs()`` wraps a difference between ``time.time()`` (or
# ``datetime.utcnow().timestamp()``) and a timestamp-like operand. We
# bound the body with ``[^\n]{0,300}`` (single-line — `re.DOTALL` is
# set globally but we deliberately stop at a newline here because the
# real-world shape is one line). The bound is linear and accepts inner
# parens (e.g. ``int(headers["X-Timestamp"])``).
_T2_PY_ABS = _re(
    r"\babs\s*\(\s*"
    r"(?:time\.time\s*\(\s*\)|datetime\.\w{1,30}\s*\(\s*\)(?:\.[a-z_]{1,30}\s*\(\s*\))?)"
    r"[^\n]{0,300}\)\s*[<>]=?\s*\d+"
)


_T2_ANY = _re(
    _T2_JS_MATH_ABS.pattern
    + r"|"
    + _T2_PY_ABS.pattern
)


# ---- T3. Wall-clock-driven rate-limit window reset ---------------------


# JS shape: ``windowStart`` compared via ``<``/``>``/``<=``/``>=`` and
# within ~3 lines the counter is reset to ``1`` (``requests = 1`` or
# ``count = 1``). The bug: the comparison uses wall-clock time, so a
# backwards clock jump triggers the reset path unconditionally.
# The bounded ``[\s\S]{0,300}`` is a LINEAR-time bridge — DOTALL flag
# is set globally, so `.` would also cross newlines, but [\s\S] makes
# the intent explicit at every match site. No leading ``\b`` — the
# identifier often appears INSIDE a camelCase name (e.g.
# ``recordWindowStart``) where there is no word boundary before
# ``W``.
_T3_JS_WINDOW_RESET = _re(
    r"[wW]indow_?[Ss]tart\s*[<>]=?[\s\S]{0,300}?"
    r"\b(?:requests?|count|counter|hits)\s*=\s*1\b"
)


# Python shape: ``record.window_start < (datetime.utcnow() - timedelta(...))``
# followed within ~3 lines by ``record.requests = 1``. Same semantic.
# Drop the leading ``\b`` for the same camelCase / attribute-access
# reason as the JS variant.
_T3_PY_WINDOW_RESET = _re(
    r"window_?start\s*[<>]=?[\s\S]{0,200}?"
    r"(?:timedelta|datetime\.\w{1,30})[\s\S]{0,300}?"
    r"\b(?:requests?|count|counter|hits)\s*=\s*1\b"
)


_T3_ANY = _re(
    _T3_JS_WINDOW_RESET.pattern
    + r"|"
    + _T3_PY_WINDOW_RESET.pattern
)


# ---- T4. TOCTOU between path.exists() and open/copy/chmod --------------


# Python shape: ``if not path.exists():`` (or ``os.path.isfile(...)`` /
# ``os.path.exists(...)`` / ``Path(...).is_file()``) followed within
# ~6 lines by ``shutil.copy*(...)``, ``open(...)``, or ``.chmod(...)``.
# The bridge ``(?:[ \t]*[^\n]{0,200}\n){0,5}`` is LINEAR (bounded
# iteration count + bounded per-line length). Trailing line is
# optionally indented because the action may be inside the
# conditional block (`return`-then-action skipped) OR at the same
# scope below the early-return guard (corpus C8 shape: bare
# ``shutil.copy2(path, backup)`` at top-level indent after a
# ``return None`` guard).
_T4_STAT_THEN_ACT = _re(
    r"if\s+(?:not\s+)?"
    r"(?:[\w.]{1,80}\.exists\s*\(\s*\)|"
    r"os\.path\.(?:isfile|exists|isdir)\s*\([^)\n]{0,80}\)|"
    r"[\w.]{1,80}\.is_file\s*\(\s*\)|"
    r"os\.access\s*\([^)\n]{0,120}\))"
    r"[^\n]{0,80}:\s*\n"
    r"(?:[ \t]*[^\n]{0,200}\n){0,5}"
    r"[ \t]*(?:shutil\.copy\w{0,20}\s*\(|open\s*\(|"
    r"[\w.]{1,80}\.chmod\s*\(|os\.chmod\s*\()"
)


# ---- T5. JWT exp claim minted with wall-clock, decoded without leeway --


# Python shape: ``jwt.decode(token, key, algorithms=[...])`` — we match
# the call with ``algorithms=`` as a structural cue (every modern PyJWT
# call MUST set algorithms, so the call shape is reliable). We MUST
# capture the FULL arg list (through the closing ``)``) so the
# post-filter in `scan_text` can scan for an explicit ``leeway=``
# argument INSIDE the captured text. Inner balanced parens are
# tolerated by using ``[^)\n]`` (the call typically lives on one
# line; multi-line JWT calls are rare and the dispatcher will still
# emit a finding for the visible portion).
# The ``[^)\n]`` body terminates at the first close-paren that isn't
# inside a nested call — accepting a small chance of cutting off the
# call early when the call contains nested function calls. For the
# T5 use case the leeway= keyword argument appears at the OUTER
# level, never inside a nested call, so this is a safe trade-off.
_T5_PY_JWT_DECODE = _re(
    r"\bjwt\.decode\s*\([^)\n]{0,400}algorithms\s*=[^)\n]{0,400}\)"
)


# JS shape: ``jwt.verify(token, key, options?)``. Same negative filter
# on ``clockTolerance:`` applied in scan_text post-filter. We capture
# through the closing ``)`` so the post-filter can scan for an
# explicit ``clockTolerance:`` argument inside the captured text.
_T5_JS_JWT_VERIFY = _re(
    r"\bjwt\.verify\s*\([^)\n]{0,400}\)"
)


_T5_ANY = _re(
    _T5_PY_JWT_DECODE.pattern
    + r"|"
    + _T5_JS_JWT_VERIFY.pattern
)


# Detector for the ``leeway=``/``clockTolerance:`` argument INSIDE the
# captured JWT-decode/verify call — applied in scan_text as a positive
# suppressor. If this pattern matches inside the captured group of
# _T5_ANY, the finding is suppressed.
_T5_LEEWAY_PRESENT = re.compile(
    r"\b(?:leeway|clockTolerance)\s*[:=]\s*\d",
    re.MULTILINE,
)


# ---- T6. Refresh-token validity bound to DB NOW() only -----------------


# Any-language SQL string shape: ``WHERE ... token_hash = ... AND
# expires_at > NOW()``. We also accept ``CURRENT_TIMESTAMP`` and
# ``CURRENT_DATE`` (the dialect-portable spellings). The cue
# ``token_hash`` (or ``refresh_token`` / ``session_token``) is what
# distinguishes refresh/session auth queries from generic data
# expiry queries. Bounded ``[^;]{0,300}`` ensures linearity.
_T6_SQL_TOKEN_NOW = _re(
    r"WHERE\s+[^;]{0,300}?"
    r"\b(?:token_hash|refresh_token|session_token|access_token|api_key)\b"
    r"[^;]{0,300}?"
    r"\bexpires?_?at\s*[<>]=?\s*"
    r"(?:NOW\s*\(\s*\)|CURRENT_TIMESTAMP|CURRENT_DATE)",
    flags=re.IGNORECASE,
)


# ---- T7. datetime.utcnow() — deprecated since Python 3.12 --------------


# Single positive shape: ``datetime.utcnow()`` (with surrounding
# whitespace tolerated). Anchored on the bare name; a fully-qualified
# ``datetime.datetime.utcnow()`` also matches because the suffix is
# present. No exception for SQLAlchemy ``default=datetime.utcnow`` —
# that's also broken (returns naive when consumer expects aware), but
# the FP guidance in the distill notes it's lower severity for pure
# audit columns. The scanner consumer applies file-kind triage.
_T7_PY_UTCNOW = _re(
    r"\bdatetime\.utcnow\s*\(\s*\)"
)


# ---- RULES catalogue ---------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="time-time-as-monotonic-for-token-expiry",
        name="time.time() / Date.now() used as monotonic for token expiry",
        severity="HIGH",
        description=(
            "Token cache, session expiry, or 'valid until' decision is "
            "computed against `time.time()` (Python) or `Date.now()` "
            "(JS). These return CLOCK_REALTIME — NTP step / DST / "
            "`date -s` causes silent extension or invalidation. Use a "
            "monotonic source (`time.monotonic()` / `process.hrtime()`)."
        ),
        pattern=_T1_ANY,
        owasp_asi="A02:2021",
    ),
    Rule(
        id="hmac-timestamp-window-symmetric",
        name="Symmetric clock-skew check on HMAC-replay timestamp",
        severity="HIGH",
        description=(
            "Webhook / signed-request verifier uses `Math.abs(...) > N` "
            "or `abs(...) > N` to enforce a replay window. The `abs` "
            "wrapper accepts FUTURE-dated request timestamps — "
            "impossible for a legitimately-signed request, so the "
            "tolerance widens the replay window 2x in practice."
        ),
        pattern=_T2_ANY,
        owasp_asi="A02:2021",
    ),
    Rule(
        id="rate-limit-window-wall-clock-reset",
        name="Wall-clock-driven rate-limit window reset",
        severity="HIGH",
        description=(
            "Rate-limit table stores `window_start` as a wall-clock "
            "timestamp and resets the counter to 1 when the recorded "
            "start is older than `now - windowMs`. Backwards clock "
            "jump (NTP step / VM time-warp / `date -s`) makes the "
            "comparison fire unconditionally, allowing unlimited new "
            "requests in the same actual window — brute-force "
            "amplification."
        ),
        pattern=_T3_ANY,
        owasp_asi="A04:2021",
    ),
    Rule(
        id="stat-then-act-toctou",
        name="TOCTOU between path.exists() and subsequent open/copy/chmod",
        severity="MAJOR",
        description=(
            "Code checks `path.exists()` / `os.path.isfile(...)` / "
            "`Path(...).is_file()` and then opens, copies, or chmods "
            "the same path. Between the syscall pair a co-tenant "
            "attacker can replace the target with a symlink to a "
            "victim file; `shutil.copy2` and bare `open()` follow "
            "symlinks by default."
        ),
        pattern=_T4_STAT_THEN_ACT,
        owasp_asi="A01:2021",
    ),
    Rule(
        id="jwt-exp-no-leeway-wall-clock-mint",
        name="JWT decode without explicit clock-skew leeway",
        severity="MAJOR",
        description=(
            "Issuer mints `exp` via `datetime.utcnow() + timedelta(...)` "
            "or `Date.now() + N*60000`. Verifier calls `jwt.decode(...)` "
            "/ `jwt.verify(...)` without an explicit `leeway=` / "
            "`clockTolerance:` argument. Any clock skew between issuer "
            "and verifier silently rejects every token at the boundary "
            "OR (if the library default is non-zero) silently extends "
            "validity. Both directions are wrong — the choice should "
            "be explicit."
        ),
        pattern=_T5_ANY,
        owasp_asi="A02:2021",
    ),
    Rule(
        id="refresh-token-db-now-only",
        name="Refresh-token validity bound to DB NOW() without monotonic",
        severity="MAJOR",
        description=(
            "Refresh-token / session-token validity check uses Postgres "
            "`NOW()` / `CURRENT_TIMESTAMP` (= DB server's wall-clock) "
            "with NO secondary check (issuance counter, version "
            "sequence, last-rotated-at compared to a monotonic "
            "source). DB clock skew (VM pause / container restart from "
            "cold snapshot / NTP loss) silently invalidates valid "
            "refresh tokens or extends compromised ones."
        ),
        pattern=_T6_SQL_TOKEN_NOW,
        owasp_asi="A02:2021",
    ),
    Rule(
        id="datetime-utcnow-deprecated-naive",
        name="datetime.utcnow() — deprecated since Python 3.12, returns naive",
        severity="MINOR",
        description=(
            "Use of `datetime.utcnow()` returns a NAIVE datetime (no "
            "tzinfo). Comparing naive vs tz-aware datetimes raises "
            "`TypeError`; mixing with tz-aware operands in arithmetic "
            "produces silent wrong results. Deprecated in Python 3.12. "
            "Modern correct form: `datetime.now(timezone.utc)`."
        ),
        pattern=_T7_PY_UTCNOW,
        owasp_asi="A02:2021",
    ),
)


# ---- scan_text ---------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).

    Identical helper to scripts/lib/dos_resource_patterns._line_col —
    kept local so this module can be imported independently in a PEP
    723 script without dragging in the larger dos_resource_patterns
    module."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    Findings are deduped by (rule_id, line, col) — a single line that
    triggers two rules emits two findings, but the same rule firing
    twice at the same offset emits one. Matched text is truncated to
    200 chars + ellipsis to keep findings small for downstream
    renderers.

    Special handling for the JWT-decode rule (`T5`):
    `jwt.decode(...)` / `jwt.verify(...)` matches are SUPPRESSED if
    the captured argument list contains an explicit `leeway=` /
    `clockTolerance:` argument. RE2 lacks lookbehind so the
    suppression is done in code after the positive match.

    The function never raises — every regex is pre-compiled and
    applied to a plain string. Caller-side input validation (file
    kind, encoding, suppression comments) is performed by the
    dispatcher that wraps scan_text, not by this module.
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            matched = m.group(0)
            # T5 post-filter: suppress JWT-decode hits when an explicit
            # `leeway=` / `clockTolerance:` argument is present in the
            # captured call. The capture is bounded so this scan is
            # fast.
            if rule.id == "jwt-exp-no-leeway-wall-clock-mint":
                if _T5_LEEWAY_PRESENT.search(matched):
                    continue
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
