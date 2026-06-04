# One-pass workflow classifier — google-re2 RegexSet primary, Python re fallback.
#
# Why a single-pass automaton:
#   The naïve scanner runs len(PATTERNS) separate finditer calls per file.
#   On a project with N workflows and P patterns that costs O(N * P * file_size).
#   google-re2's RegexSet compiles every pattern into ONE DFA — one walk per
#   file finds every match across every pattern. The doctor's per-file scan
#   cost drops from O(P) to O(1).
#
# Why a Python re fallback:
#   RE2 deliberately excludes lookaround and backreferences (so the language is
#   regular, with linear-time guaranteed matching). When a future pattern needs
#   either feature, scripts/lib/zizmor_patterns.py flags it via
#   PATTERN_FALLBACK_FLAGS[rule_id] = False; the classifier routes that single
#   pattern through Python's `re` module and keeps every other pattern on the
#   fast RE2 path.
#
# Why fail-soft on missing google-re2:
#   The plugin's PEP 723 entry scripts declare `google-re2` as a uv dep, so
#   `uv run` callers get it on first invocation. When this module is imported
#   from a context that does NOT have re2 available (e.g. a stdlib-only
#   helper or a misconfigured environment), the classifier falls back to
#   pure Python `re` for every pattern. Correctness is preserved; only the
#   single-pass speed-up is lost.

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from .zizmor_patterns import PATTERN_FALLBACK_FLAGS, PATTERNS
from .zizmor_patterns_extra import PATTERN_FALLBACK_FLAGS_EXTRA, PATTERNS_EXTRA

# Single source of truth for the regex tier: the base catalog UNION the
# extension catalog. Merging here (rather than in each consumer — the
# workflow-security detector and doctor_classify) means every caller of
# Classifier gets the extra rules automatically and the wiring cannot
# silently regress (an importer forgetting the union no longer drops the
# CVE-class extra rules). Dict union is collision-safe: a test asserts no
# id appears in both PATTERNS and PATTERNS_EXTRA.
_ALL_PATTERNS = {**PATTERNS, **PATTERNS_EXTRA}
_ALL_FALLBACK_FLAGS = {**PATTERN_FALLBACK_FLAGS, **PATTERN_FALLBACK_FLAGS_EXTRA}

try:
    import re2 as _re2  # type: ignore[import-not-found]  # google-re2 binding (optional)
    _RE2_AVAILABLE = True
except ImportError:
    _re2 = None  # type: ignore[assignment]
    _RE2_AVAILABLE = False


@dataclass(frozen=True)
class Finding:
    rule_id: str
    line: int  # 1-indexed
    col: int  # 1-indexed
    matched_text: str
    severity: str
    description: str


def _rule_id_to_group_name(rule_id: str) -> str:
    # Named groups in alternation patterns. Python and re2 both accept
    # (?P<name>...) but require `name` to match [A-Za-z_][A-Za-z0-9_]*.
    return rule_id.replace("-", "_")


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last_newline = text.rfind("\n", 0, offset)
    col = offset - last_newline if last_newline >= 0 else offset + 1
    return line, col


class Classifier:
    """Single-pass workflow classifier. Build once, reuse across files."""

    def __init__(self) -> None:
        # Split patterns into the RE2 bucket and the Python re fallback bucket.
        # A pattern is routed to the fallback if either (a) the patterns
        # module declares it RE2-incompatible, or (b) RE2 itself rejects it
        # at compile time (defence in depth — a future regex with subtle
        # PCRE-only syntax should not silently break the fast path).
        re2_pairs: list[tuple[str, str]] = []
        fallback_pairs: list[tuple[str, str]] = []

        for rule_id, (pattern, _sev, _desc) in _ALL_PATTERNS.items():
            re2_ok = _RE2_AVAILABLE and _ALL_FALLBACK_FLAGS.get(rule_id, True)
            if re2_ok:
                try:
                    _re2.compile(pattern)  # type: ignore[union-attr]
                except Exception:  # noqa: BLE001 — RE2 raises various error types
                    re2_ok = False
            if re2_ok:
                re2_pairs.append((rule_id, pattern))
            else:
                fallback_pairs.append((rule_id, pattern))

        # Build the RE2 combined alternation. Each branch is a named group so
        # we know which rule fired without re-testing individual patterns.
        # `(?m)` is an inline flag — RE2 has no MULTILINE constant; the
        # inline form works under both google-re2 and Python `re`.
        if re2_pairs and _RE2_AVAILABLE:
            combined = "(?m)" + "|".join(
                f"(?P<{_rule_id_to_group_name(rid)}>{pat})"
                for rid, pat in re2_pairs
            )
            self._re2_combined = _re2.compile(combined)  # type: ignore[union-attr]
            self._re2_group_names: dict[str, str] = {
                _rule_id_to_group_name(rid): rid for rid, _ in re2_pairs
            }
        else:
            self._re2_combined = None
            self._re2_group_names = {}

        # Fallback patterns compile individually under Python re — they're
        # the ones that need lookaround/backrefs (or RE2 wasn't available).
        self._fallback_compiled: list[tuple[str, re.Pattern[str]]] = [
            (rid, re.compile(pat, re.MULTILINE)) for rid, pat in fallback_pairs
        ]

    def classify(self, text: str) -> Iterator[Finding]:
        # Pass 1 — RE2 RegexSet (one DFA walk for every RE2-compatible rule).
        if self._re2_combined is not None:
            for m in self._re2_combined.finditer(text):
                # last group dict lookup — re2 and re both return groupdict()
                gd = m.groupdict()
                for gname, value in gd.items():
                    if value is None:
                        continue
                    rule_id = self._re2_group_names.get(gname)
                    if rule_id is None:
                        continue
                    pattern, severity, description = _ALL_PATTERNS[rule_id]
                    line, col = _line_col(text, m.start())
                    yield Finding(
                        rule_id=rule_id,
                        line=line,
                        col=col,
                        matched_text=value,
                        severity=severity,
                        description=description,
                    )
                    break  # one rule per match position is enough

        # Pass 2 — Python re for any pattern RE2 cannot handle.
        for rule_id, compiled in self._fallback_compiled:
            _pat, severity, description = _ALL_PATTERNS[rule_id]
            for m in compiled.finditer(text):
                line, col = _line_col(text, m.start())
                yield Finding(
                    rule_id=rule_id,
                    line=line,
                    col=col,
                    matched_text=m.group(0),
                    severity=severity,
                    description=description,
                )

    @property
    def re2_active(self) -> bool:
        # Diagnostic property — True iff at least one pattern is on the
        # fast RE2 path. Used by the doctor's report to surface whether
        # the single-pass optimisation was actually applied this run.
        return self._re2_combined is not None
