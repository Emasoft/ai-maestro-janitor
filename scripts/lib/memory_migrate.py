# Memory scope-migration core (TRDD-47df698b) — the read-only Phase-1 classifier
# that decides, for each note in a LOCAL memory corpus, whether it could move to
# PROJECT scope (git-tracked + PUSHED) or must stay LOCAL (machine-private).
#
# Split of powers (the USER's cross-project contract): the JANITOR repo only
# WRITES this helper; the OWNING project's Claude RUNS `--apply` in its own
# session. This module is the classifier ONLY — pure, read-only, no mutation. The
# CLI (`scripts/migrate_memory_scope.py`) drives it; Phase 2 (`--apply`) is a
# SEPARATE, deferred build the owning Claude runs after reviewing the plan.
#
# Privacy-FIRST, conservative (the cardinal rules, in order):
#   1. PRIVACY GATE (hard) — ANY machine/user-private datum (local abs path,
#      hostname, PII shape, credential, high-entropy secret) ⇒ LOCAL-stay,
#      regardless of topic. A note may be PROJECT-bound ONLY if it is privacy-clean.
#      The gate REUSES the exact pattern libraries the `memory-scope-leak` detector
#      uses, so the two never disagree (single source of truth for "what leaks").
#   2. TOPIC signal — privacy-clean AND project-structure knowledge ⇒ PROJECT.
#   3. MACHINE/about-user signal ⇒ LOCAL-stay.
#   4. EVERYTHING ELSE / ambiguous ⇒ UNSURE ⇒ LOCAL-stay (the safe scope; the
#      owning Claude can promote later). Mirrors the write-skill "UNSURE → LOCAL".
#
# The classifier surfaces the CLASS of every leak (never the matched secret
# value) so the plan is safe to read and to commit as a report.

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The pattern libraries live in scripts/lib/ (this file's own dir). Insert it so
# the imports resolve whether we are imported as `memory_migrate` or run via the
# CLI that already inserted lib/ — idempotent (sys.path dedupes by membership).
_LIB_DIR = str(Path(__file__).resolve().parent)
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

import cicd_secret_leak_patterns as cicd  # noqa: E402
import cloud_credential_patterns as cloud  # noqa: E402
import memory_scopes  # noqa: E402
import privacy_patterns as privacy  # noqa: E402
import private_path_patterns as ppp  # noqa: E402
import security_helpers as sec  # noqa: E402
from memory_edit_verify import parse_frontmatter  # noqa: E402

# Bound a pathologically large "note" so a corpus can never blow up the scan
# (mirrors memory-scope-leak's `_MAX_BYTES_PER_PAGE`).
_MAX_BYTES_PER_PAGE = 256 * 1024

# Unknown-secret entropy gate — identical constants to memory-scope-leak so the
# two agree on what counts as a high-entropy secret.
_ENTROPY_MIN_LEN = 24
_ENTROPY_MIN_BITS = 4.5
_TOKEN_RE = re.compile(r"[A-Za-z0-9+/_\-=]{%d,512}" % _ENTROPY_MIN_LEN)

# Verdicts.
PROJECT = "PROJECT"
LOCAL = "LOCAL"

# Topic heuristics ------------------------------------------------------------ #
# A note's filename stem signalling project-shared structure (the write-skill's
# own naming convention): a `project_*` note, or a hub/aspect/component page.
_PROJECT_STEM_RE = re.compile(r"^(project[_-]|hub[_-]|aspect[_-]|component[_-])", re.I)
# A note's filename stem signalling a machine/about-user note.
_LOCAL_STEM_RE = re.compile(r"^(local[_-]|user[_-])", re.I)

# Body words that indicate project-shared architecture/convention knowledge any
# contributor needs. Deliberately broad-but-careful: only consulted AFTER the
# privacy gate passes, and only to PROMOTE a privacy-clean note to PROJECT.
_PROJECT_TOPIC_WORDS = (
    "architecture",
    "convention",
    "codebase",
    "module",
    "pipeline",
    "endpoint",
    "schema",
    "interface",
    "component",
    "subsystem",
    "build system",
    "directory layout",
    "file layout",
)


# --------------------------------------------------------------------------- #
# the privacy gate — the SINGLE source of "what leaks", shared with the
# memory-scope-leak detector (same four catalogues + the same entropy gate)
# --------------------------------------------------------------------------- #


def _entropy_labels(text: str) -> list[str]:
    """Class labels for unknown-format high-entropy secrets (deduped per page).

    Mirrors memory-scope-leak's `_entropy_findings`: a base64-ish token at least
    `_ENTROPY_MIN_LEN` chars long with Shannon entropy above `_ENTROPY_MIN_BITS`
    that `looks_like_base64` is a likely secret no named lib caught.
    """
    out: list[str] = []
    seen: set[str] = set()
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0)
        if tok in seen:
            continue
        seen.add(tok)
        if not sec.looks_like_base64(tok, min_len=_ENTROPY_MIN_LEN):
            continue
        if sec.shannon_entropy(tok) < _ENTROPY_MIN_BITS:
            continue
        out.append("high-entropy secret")
    return out


def privacy_scan(text: str) -> list[str]:
    """Return the sorted, deduped leak-CLASS labels found in `text`.

    Composes the same four catalogues as memory-scope-leak's `_scan_page`
    (private-path, PII shapes, cloud + CI/CD credentials) plus the entropy gate.
    Each finding is reduced to a short class label — NEVER the matched value — so
    the plan can be read/committed safely. An empty list means privacy-clean.
    """
    labels: set[str] = set()

    # 1. Local-path / machine-identity.
    for f in ppp.scan_text(text):
        labels.add(f.kind)  # "local-path" | "machine-host"

    # 2. PII shapes (email/phone/SSN/credit-card/IBAN/passport). Use the named
    #    shapes directly (privacy.scan_text also fires source-only rules like
    #    cookie/CSP that don't apply to a markdown note).
    for shape_name, pattern in privacy.PII_SHAPES.items():
        for m in pattern.finditer(text):
            if shape_name == "credit_card" and not privacy.luhn_valid(m.group(0)):
                continue  # drop non-card 16-digit runs (dates, ids)
            labels.add(f"pii:{shape_name}")
            break  # one label per shape is enough

    # 3. Credential shapes (cloud + CI/CD secret-leak libs).
    for _ in cloud.scan_text(text):
        labels.add("credential")
    for _ in cicd.scan_text(text):
        labels.add("credential")

    # 4. Unknown high-entropy secrets.
    labels.update(_entropy_labels(text))

    return sorted(labels)


# --------------------------------------------------------------------------- #
# the classifier
# --------------------------------------------------------------------------- #


@dataclass
class NoteVerdict:
    """The classification of ONE note. `leak_classes` is empty iff privacy-clean;
    `verdict` is PROJECT only when privacy-clean AND a project-topic signal fired.
    `reason` is the single human-readable deciding reason for the plan."""

    rel_path: str
    verdict: str
    reason: str
    leak_classes: list[str] = field(default_factory=list)


def _frontmatter_str(fm: dict, key: str) -> str:
    """A frontmatter value coerced to a lowercased str (lists → first element)."""
    val = fm.get(key)
    if isinstance(val, list):
        val = val[0] if val else ""
    return str(val or "").strip().lower()


def _topic_says_project(stem: str, fm: dict, body_lower: str) -> bool:
    """True iff a project-structure topic signal fires (consulted ONLY after the
    privacy gate passes — never overrides privacy)."""
    # Explicit frontmatter type/tier.
    if _frontmatter_str(fm, "type") == "project":
        return True
    if _frontmatter_str(fm, "tier") in {"hub", "aspect", "component"}:
        return True
    # Filename convention.
    if _PROJECT_STEM_RE.match(stem):
        return True
    # Body topic words (broad but privacy-gated).
    return any(word in body_lower for word in _PROJECT_TOPIC_WORDS)


def _topic_says_local(stem: str, fm: dict) -> bool:
    """True iff a machine/about-user signal fires."""
    if _frontmatter_str(fm, "type") == "user":
        return True
    return bool(_LOCAL_STEM_RE.match(stem))


def classify_text(rel_path: str, text: str) -> NoteVerdict:
    """Classify ONE note from its relative path + full text. Pure (no I/O).

    Order is load-bearing: PRIVACY GATE first (any leak ⇒ LOCAL, with the leak
    classes recorded), then topic-says-PROJECT, then topic-says-LOCAL, else
    UNSURE ⇒ LOCAL.
    """
    leaks = privacy_scan(text)
    if leaks:
        return NoteVerdict(
            rel_path=rel_path,
            verdict=LOCAL,
            reason="privacy: machine/user-private data (" + ", ".join(leaks) + ")",
            leak_classes=leaks,
        )

    fm = parse_frontmatter(text)
    stem = Path(rel_path).stem
    body_lower = text.lower()

    if _topic_says_project(stem, fm, body_lower):
        return NoteVerdict(rel_path, PROJECT, "topic: project-structure knowledge (privacy-clean)")
    if _topic_says_local(stem, fm):
        return NoteVerdict(rel_path, LOCAL, "topic: machine/about-user note")
    return NoteVerdict(rel_path, LOCAL, "unsure → LOCAL (safe scope; promote later)")


# --------------------------------------------------------------------------- #
# corpus walk (read-only)
# --------------------------------------------------------------------------- #


def iter_notes(memdir: Path) -> list[Path]:
    """Every real note `*.md` under `memdir`, via the shared SSOT.

    `memory_scopes.iter_note_files` excludes the generated/index files, the
    detector-proposal reports (`-proposed.md`), and the excluded sub-dirs
    (`user-mem/`, `.memgrep/`, `.maint-staging/`), sorted for a deterministic
    plan. Read-only. The migration's own duplicated exclusion sets are gone —
    one source of truth (TRDD-87935f21 mandate #3)."""
    return memory_scopes.iter_note_files(memdir)


def classify_corpus(memdir: Path) -> list[NoteVerdict]:
    """Classify every real note under `memdir`. Read-only. A note larger than the
    byte bound is skipped (treated as not-a-note for safety, exactly as the leak
    detector does)."""
    verdicts: list[NoteVerdict] = []
    for path in iter_notes(memdir):
        try:
            if path.stat().st_size > _MAX_BYTES_PER_PAGE:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(path.relative_to(memdir))
        verdicts.append(classify_text(rel, text))
    return verdicts


# --------------------------------------------------------------------------- #
# the plan (the reviewable artifact the owning Claude reads before --apply)
# --------------------------------------------------------------------------- #


def render_plan(memdir: Path, verdicts: list[NoteVerdict], *, project_repo: str) -> str:
    """Render the migration PLAN: every note with its verdict, the deciding
    reason, and (when LOCAL-for-privacy) the leak classes. Includes the
    acceptance-critical invariant check: ZERO privacy-flagged notes land in
    PROJECT. NEVER includes a matched secret value — only the class."""
    project = [v for v in verdicts if v.verdict == PROJECT]
    local = [v for v in verdicts if v.verdict == LOCAL]
    privacy_flagged = [v for v in verdicts if v.leak_classes]

    # The acceptance invariant: no privacy-flagged note may be PROJECT-bound.
    leak_in_project = [v for v in project if v.leak_classes]

    lines: list[str] = [
        "# Memory scope-migration plan (LOCAL → PROJECT) — REVIEW BEFORE --apply",
        "",
        f"- Source LOCAL corpus: `{memdir}`",
        f"- Target PROJECT repo: `{project_repo}`",
        f"- Notes classified: {len(verdicts)} ({len(project)} → PROJECT, {len(local)} → LOCAL-stay)",
        f"- Privacy-flagged (forced LOCAL): {len(privacy_flagged)}",
        "",
        "> This is a DRY-RUN plan. No file was moved. The OWNING project's Claude runs `--apply` in its own session after reviewing this plan (cross-project contract).",
        "",
        "## Privacy invariant",
        "",
    ]
    if leak_in_project:
        lines.append(f"- ❌ FAIL: {len(leak_in_project)} privacy-flagged note(s) classified PROJECT — this must be ZERO. (Classifier bug — do NOT apply.)")
    else:
        lines.append("- ✅ PASS: zero privacy-flagged notes are PROJECT-bound.")
    lines.append("")

    lines.append("## → PROJECT (privacy-clean, project-structure knowledge)")
    lines.append("")
    if project:
        for v in project:
            lines.append(f"- `{v.rel_path}` — {v.reason}")
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.append("## → LOCAL-stay")
    lines.append("")
    if local:
        for v in local:
            extra = f"  [leak: {', '.join(v.leak_classes)}]" if v.leak_classes else ""
            lines.append(f"- `{v.rel_path}` — {v.reason}{extra}")
    else:
        lines.append("_(none)_")
    lines.append("")

    return "\n".join(lines) + "\n"
