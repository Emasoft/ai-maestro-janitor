"""Shared suppression-file loader for janitor detectors.

Reads `.janitor.toml` (preferred) or `.janitorignore` (fallback) from the
project root and exposes a single `is_suppressed(rule_id, file=None,
sha=None)` predicate every detector can consult before surfacing a
finding.

Why a shared library? Each detector emits findings independently; the
suppression table must be SINGLE-SOURCE-OF-TRUTH so a `.janitor.toml`
entry takes effect across every detector + skill that opts in. Lock
acquisition is unnecessary — this is read-only state at the project
root.

`.janitor.toml` schema

  # Suppress a rule entirely.
  [[suppress]]
  rule_id = "shell-injection-expr"
  reason = "internal-only workflow, audited 2026-05"

  # Suppress a rule within a glob.
  [[suppress]]
  rule_id = "missing-permissions"
  paths = [".github/workflows/legacy-*.yml"]
  expires = "2026-12-31"           # ISO-8601 date; required for time-bounded waivers

  # Suppress an exact finding by its content SHA.
  [[suppress]]
  rule_id = "static-aws-credentials"
  sha     = "a4f2e1c8…"             # output by the detector's drift line
  reason  = "test fixture; not a real credential"

Hard rules

  * `rule_id` is REQUIRED — there are no "blanket suppress everything"
    waivers; each entry names exactly one rule.
  * `expires` is OPTIONAL but RECOMMENDED for path/glob suppressions —
    a waiver without expiry rots in the repo forever; the loader logs
    a one-time warning for path-based waivers that omit `expires`.
  * `paths` is a list of git-style globs interpreted relative to the
    project root. Star/double-star + per-segment wildcards supported
    via Python's `pathlib.PurePath.match` (one star = single segment,
    `**` = any subtree).
  * Past `expires` dates are IGNORED (the waiver no longer applies) so
    a forgotten waiver doesn't keep hiding a finding past its review
    deadline. The loader logs the IGNORED entries once per call.

`.janitorignore` fallback

  When `.janitor.toml` is absent BUT `.janitorignore` exists, every
  non-comment line is treated as `<rule-id>` (suppress that rule
  everywhere, no expiry). The simple format exists for users who want a
  one-line opt-out without learning TOML.
"""

from __future__ import annotations

import datetime as _dt
import sys
import tomllib
from pathlib import Path, PurePath


class SuppressionRule:
    """A single, parsed suppression entry."""

    __slots__ = ("rule_id", "paths", "shas", "expires", "reason")

    def __init__(
        self,
        rule_id: str,
        paths: list[str] | None = None,
        shas: list[str] | None = None,
        expires: _dt.date | None = None,
        reason: str = "",
    ) -> None:
        self.rule_id = rule_id
        self.paths = paths or []
        self.shas = shas or []
        self.expires = expires
        self.reason = reason

    def is_expired(self, today: _dt.date | None = None) -> bool:
        if self.expires is None:
            return False
        today = today or _dt.date.today()
        return today > self.expires

    def matches(
        self,
        rule_id: str,
        file: str | None,
        sha: str | None,
    ) -> bool:
        if self.rule_id != rule_id:
            return False
        if self.is_expired():
            return False
        # If both paths AND shas are empty, suppress every occurrence of
        # this rule.
        if not self.paths and not self.shas:
            return True
        if sha and self.shas and sha in self.shas:
            return True
        if file and self.paths:
            pp = PurePath(file)
            for glob in self.paths:
                if pp.match(glob):
                    return True
                # Also accept ** prefix (`**/foo` matches at any depth).
                if "**" in glob:
                    try:
                        if pp.match(glob):
                            return True
                    except ValueError:
                        pass
        return False


class SuppressionTable:
    """The full set of suppression entries for a project root."""

    __slots__ = ("entries", "expired_entries", "warnings")

    def __init__(
        self,
        entries: list[SuppressionRule] | None = None,
        expired_entries: list[SuppressionRule] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self.entries = entries or []
        self.expired_entries = expired_entries or []
        self.warnings = warnings or []

    def is_suppressed(
        self,
        rule_id: str,
        file: str | None = None,
        sha: str | None = None,
    ) -> bool:
        for entry in self.entries:
            if entry.matches(rule_id, file, sha):
                return True
        return False


def _parse_expires(value: object) -> _dt.date | None:
    if value is None:
        return None
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _parse_toml(path: Path) -> tuple[list[SuppressionRule], list[SuppressionRule], list[str]]:
    """Return (active, expired, warnings) for a `.janitor.toml` file."""
    active: list[SuppressionRule] = []
    expired: list[SuppressionRule] = []
    warnings: list[str] = []
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        warnings.append(f".janitor.toml unreadable: {exc}")
        return active, expired, warnings
    try:
        data = tomllib.loads(raw_bytes.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        warnings.append(f".janitor.toml parse failed: {exc}")
        return active, expired, warnings

    entries = data.get("suppress")
    if entries is None:
        return active, expired, warnings
    if not isinstance(entries, list):
        warnings.append(".janitor.toml: `suppress` must be an array of tables")
        return active, expired, warnings

    today = _dt.date.today()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            warnings.append(f".janitor.toml: suppress[{i}] is not a table — skipped")
            continue
        rule_id = entry.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id:
            warnings.append(
                f".janitor.toml: suppress[{i}] missing required `rule_id` — skipped"
            )
            continue
        paths_raw = entry.get("paths") or []
        if not isinstance(paths_raw, list):
            warnings.append(
                f".janitor.toml: suppress[{i}].paths must be a list of strings — skipped"
            )
            continue
        paths = [str(p) for p in paths_raw if isinstance(p, str)]
        shas_raw = entry.get("sha") or entry.get("shas") or []
        if isinstance(shas_raw, str):
            shas_raw = [shas_raw]
        if not isinstance(shas_raw, list):
            warnings.append(
                f".janitor.toml: suppress[{i}].sha must be a string or list — skipped"
            )
            continue
        shas = [str(s) for s in shas_raw if isinstance(s, str)]
        expires = _parse_expires(entry.get("expires"))
        reason = entry.get("reason") or ""
        if not isinstance(reason, str):
            reason = ""

        rule = SuppressionRule(
            rule_id=rule_id, paths=paths, shas=shas,
            expires=expires, reason=reason,
        )
        if rule.is_expired(today):
            expired.append(rule)
            continue
        if paths and expires is None:
            warnings.append(
                f".janitor.toml: suppress[{i}] (rule_id={rule_id}) has a "
                f"path waiver with no `expires` — recommend setting an "
                f"ISO date to force periodic review"
            )
        active.append(rule)
    return active, expired, warnings


def _parse_janitorignore(path: Path) -> list[SuppressionRule]:
    """One rule-id per line; no globs, no expiry. Lines starting with `#`
    are comments."""
    out: list[SuppressionRule] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(SuppressionRule(rule_id=s))
    return out


def load(project_root: Path) -> SuppressionTable:
    """Load the project's suppression table.

    `.janitor.toml` is preferred; `.janitorignore` is a simpler fallback.
    The loader emits one-time warnings for expired entries / missing
    expires on path waivers — printed to stderr so they show up in the
    detector's log without polluting stdout's drift channel.
    """
    toml_path = project_root / ".janitor.toml"
    if toml_path.is_file():
        active, expired, warnings = _parse_toml(toml_path)
        for w in warnings:
            print(f"[suppression] {w}", file=sys.stderr)
        for e in expired:
            print(
                f"[suppression] expired waiver IGNORED: rule_id={e.rule_id} "
                f"(expired {e.expires}) — reason: {e.reason or 'n/a'}",
                file=sys.stderr,
            )
        return SuppressionTable(
            entries=active, expired_entries=expired, warnings=warnings,
        )

    ignore_path = project_root / ".janitorignore"
    if ignore_path.is_file():
        return SuppressionTable(entries=_parse_janitorignore(ignore_path))

    return SuppressionTable()
