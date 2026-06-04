#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""repo-trust-score — dropper-pattern audit on the current project tree.

The github-monitoring corpus study (May 2026) caught TWO live malicious
repos that shared the same dropper shape:

  * snakebite-main — Windows trojan bundle `image/Software-2.9.zip`
    containing `loader.exe` / `Application.cmd` / `lua51.dll` / `dir.cc`,
    Python file in the main directory was camouflage. README aggressively
    funneled Windows users to the binary.
  * Pipeline-Sentinel-CI-CD-Failure-Analysis-main — three zips with
    `Launcher.cmd` / `Application.bat` → renamed lua.exe → obfuscated
    Lua bytecode infostealer. README was SEO-keyword-stuffed.

This detector fires when the CURRENT project's tree shows the dropper
shape. Use case: the user clones a repo to inspect it, the janitor
heartbeat surfaces "this project matches the dropper pattern" within
one cadence window — giving the user a chance to step away from the
working dir before the LLM is asked to "read README.md" and accidentally
triggers the dropper directives.

Heuristics (each contributes to a trust-deficit score; total > threshold
surfaces a drift line). All deterministic, no network.

  A. Suspicious binary blobs in the repo root or under common
     "samples / examples / images" directories:
       *.zip / *.tar.gz / *.7z / *.rar / *.exe / *.cmd / *.bat / *.dll /
       *.so / *.dylib / *.pyc / *.luac
       (a normal source repo does NOT ship .exe/.cmd/.bat under image/)
  B. README contains a download funnel — direct link or
     reference to a binary in the repo (`see image/Software.zip`,
     `download from <relative-path>.exe`, etc.).
  C. README is suspiciously LONG vs the actual code (camouflage
     ratio > 5x — heavy README, thin code).
  D. README has SEO-keyword anomalies: dense repeated keyword
     paragraphs with low information density.
  E. No tests directory + no CI / no LICENSE + suspicious binaries
     (legitimate repos virtually always have at least one of these).

Heartbeat invariants:
  * Self-scan guard — never scans the janitor's own tree.
  * Content-hash dedupe — silent if the relevant tree hasn't changed.
  * Bounded output — at most one drift line per heartbeat.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import state  # type: ignore[import-not-found]  # noqa: E402

_NAME = "repo-trust-score"

# Score threshold above which a drift line is surfaced. The score scale
# is calibrated against the two known-malicious repos in the corpus:
#   * snakebite: ~14 (4 binaries + funnel + camouflage + no tests)
#   * Pipeline-Sentinel: ~16 (5 binaries + funnel + camouflage + SEO + no tests)
# Legitimate projects typically score 0-3 (the occasional .exe in an
# `examples/` dir is benign on its own).
_THRESHOLD = 8

_SUSPICIOUS_BIN_SUFFIXES = frozenset({
    ".zip", ".tar.gz", ".tgz", ".7z", ".rar",
    ".exe", ".cmd", ".bat", ".ps1",
    ".dll", ".so", ".dylib",
    ".pyc", ".luac", ".class",
})

# Sample/example/image dirs that legitimately CAN hold binaries but
# whose presence in dropper repos is the canonical shape. Score a small
# weight per match.
_SUSPICIOUS_PARENTS = frozenset({
    "image", "images", "img",
    "sample", "samples", "examples", "demo", "demos",
    "downloads", "download", "binaries", "bin",
    "release", "releases",
})

# README download-funnel patterns — language that points the reader at
# a local binary in the repo.
_DOWNLOAD_FUNNEL_PATTERNS = (
    # "Download <name>" — direct CTA
    re.compile(r"\bdownload\s+(?:the|our|this|latest|now|here)\b", re.IGNORECASE),
    # Markdown link to a local binary
    re.compile(r"\]\(\s*[^)]*?\.(?:exe|zip|cmd|bat|tar\.gz|7z|rar)\s*\)", re.IGNORECASE),
    # Direct "see / get / find ... in <path>.zip" pattern
    re.compile(r"\b(?:see|get|find|run|launch|extract)\b[^.]{0,80}?\.(?:zip|exe|cmd|bat|tar\.gz)", re.IGNORECASE),
    # "Click here to" pointing at a binary
    re.compile(r"\bclick\s+(?:here|below)\b[^.]{0,80}?\.(?:exe|zip|cmd|bat)", re.IGNORECASE),
    # Windows / "for windows" alignment with binary
    re.compile(r"\bfor\s+windows\b[^.]{0,200}?\.(?:exe|zip|cmd|bat)", re.IGNORECASE),
)


def _is_binary_suffix(p: Path) -> bool:
    name = p.name.lower()
    # Handle compound .tar.gz / .tar.bz2
    if name.endswith(".tar.gz") or name.endswith(".tar.bz2"):
        return True
    return p.suffix.lower() in _SUSPICIOUS_BIN_SUFFIXES


def _enumerate_suspicious_binaries(root: Path) -> list[Path]:
    """Return every suspicious binary blob in the project, excluding
    common false-positive trees (node_modules, .venv, .git, .trashcan)."""
    out: list[Path] = []
    skip = {"node_modules", ".venv", "venv", "env", ".git", ".trashcan",
            "dist", "build", "target", "__pycache__"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip for part in path.parts):
            continue
        if _is_binary_suffix(path):
            out.append(path)
    return out


def _score_binaries(binaries: list[Path], root: Path) -> tuple[int, list[str]]:
    """Score the binary inventory. Each suspicious blob contributes 1
    point; one in a suspicious parent dir adds another point."""
    score = 0
    notes: list[str] = []
    for b in binaries:
        score += 1
        try:
            rel = b.relative_to(root)
            rel_str = str(rel)
        except ValueError:
            rel_str = str(b)
        parents = {p.lower() for p in b.parts}
        if parents & _SUSPICIOUS_PARENTS:
            score += 1
            notes.append(f"suspicious binary in promo-dir: {rel_str}")
        else:
            notes.append(f"suspicious binary at: {rel_str}")
    return score, notes


def _find_readme(root: Path) -> Path | None:
    for name in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
        cand = root / name
        if cand.is_file():
            return cand
    return None


def _score_readme(readme: Path) -> tuple[int, list[str]]:
    """Score README-level signals: download funnel + length anomaly + SEO."""
    score = 0
    notes: list[str] = []
    try:
        text = readme.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, []
    if not text:
        return 0, []

    # B. Download funnel
    funnel_hits = 0
    for pat in _DOWNLOAD_FUNNEL_PATTERNS:
        if pat.search(text):
            funnel_hits += 1
    if funnel_hits >= 1:
        score += 3 * funnel_hits  # weighted heavily — this is the dropper signature
        notes.append(
            f"README contains {funnel_hits} download-funnel pattern(s) pointing to a binary"
        )

    # D. SEO-keyword stuffing — look for a single non-code-block sentence
    # where one word repeats 6+ times. Real prose rarely does this.
    body = re.sub(r"```[\s\S]*?```", "", text)  # drop code fences
    body = re.sub(r"^#+\s*.*$", "", body, flags=re.MULTILINE)  # drop headings
    for paragraph in re.split(r"\n\s*\n", body):
        words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", paragraph)
        if len(words) < 12:
            continue
        # Count word frequency, ignore stopwords
        stop = {"that", "this", "with", "from", "have", "your", "their",
                "they", "will", "into", "more", "than", "what", "when",
                "where", "which", "while", "would", "could", "should"}
        counts: dict[str, int] = {}
        for w in words:
            lw = w.lower()
            if lw in stop:
                continue
            counts[lw] = counts.get(lw, 0) + 1
        if not counts:
            continue
        top = max(counts.values())
        if top >= 6:
            score += 2
            top_word = max(counts, key=lambda k: counts[k])
            notes.append(
                f"README paragraph repeats '{top_word}' {top}x — SEO stuffing shape"
            )
            break  # one signal is enough; don't double-count

    return score, notes


def _score_code_vs_readme_ratio(root: Path, readme: Path | None) -> tuple[int, list[str]]:
    """C. Camouflage ratio: README is much heavier than the source code.
    Real projects: README is a fraction of total source bytes. Droppers
    invert this — heavy README, thin code (the code is decoration)."""
    if not readme:
        return 0, []
    try:
        readme_bytes = readme.stat().st_size
    except OSError:
        return 0, []
    if readme_bytes < 2048:  # tiny README, ratio doesn't apply
        return 0, []
    source_exts = {".py", ".js", ".ts", ".tsx", ".jsx", ".cjs", ".mjs",
                   ".rs", ".go", ".rb", ".java", ".kt", ".swift", ".cpp",
                   ".cc", ".c", ".h", ".hpp", ".cs", ".php", ".lua", ".sh"}
    skip = {"node_modules", ".venv", "venv", "env", ".git", ".trashcan",
            "dist", "build", "target", "__pycache__"}
    src_bytes = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip for part in path.parts):
            continue
        if path.suffix.lower() in source_exts:
            try:
                src_bytes += path.stat().st_size
            except OSError:
                pass
    if src_bytes == 0:
        # No source code at all + heavy README + binaries → very suspicious.
        return 3, ["README is sizeable but the repo has ZERO source code"]
    ratio = readme_bytes / src_bytes
    if ratio > 5.0:
        return 2, [
            f"README/source camouflage ratio {ratio:.1f}x (README {readme_bytes}B, src {src_bytes}B)"
        ]
    return 0, []


def _score_missing_essentials(root: Path) -> tuple[int, list[str]]:
    """E. Missing CI / tests / LICENSE — combined with other signals,
    catches a dropper masquerading as a project."""
    score = 0
    notes: list[str] = []
    has_ci = (root / ".github" / "workflows").is_dir() or \
             (root / ".gitlab-ci.yml").is_file() or \
             (root / ".circleci" / "config.yml").is_file()
    has_tests = (root / "tests").is_dir() or (root / "test").is_dir() or \
                bool(list(root.rglob("test_*.py"))[:1]) or \
                bool(list(root.rglob("*_test.py"))[:1]) or \
                bool(list(root.rglob("*.test.js"))[:1]) or \
                bool(list(root.rglob("*.test.ts"))[:1])
    has_license = any((root / n).is_file() for n in
                      ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"))
    if not has_ci:
        score += 1
        notes.append("no CI workflows")
    if not has_tests:
        score += 1
        notes.append("no test files")
    if not has_license:
        score += 1
        notes.append("no LICENSE")
    return score, notes


def _content_signature(root: Path) -> str:
    """Cheap dedupe — sizes of README + every binary blob."""
    h = hashlib.sha256()
    readme = _find_readme(root)
    if readme:
        try:
            st = readme.stat()
            h.update(f"{readme}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        except OSError:
            pass
    for b in sorted(_enumerate_suspicious_binaries(root)):
        try:
            st = b.stat()
            h.update(f"{b}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        except OSError:
            pass
    return h.hexdigest()


def main() -> int:
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_REPO_TRUST_SCORE_ENABLED", True,
    ):
        return 0
    if state.is_self_scan_target():
        return 0

    state.init_state()
    project_root = state.project_root()

    combined = _content_signature(project_root)
    last_hash_file = state.state_dir() / "repo-trust-score-last-hash.ts"
    if last_hash_file.is_file():
        try:
            if last_hash_file.read_text(encoding="utf-8").strip() == combined:
                return 0
        except OSError:
            pass

    binaries = _enumerate_suspicious_binaries(project_root)
    bin_score, bin_notes = _score_binaries(binaries, project_root)

    readme = _find_readme(project_root)
    readme_score = 0
    readme_notes: list[str] = []
    if readme:
        readme_score, readme_notes = _score_readme(readme)

    ratio_score, ratio_notes = _score_code_vs_readme_ratio(project_root, readme)
    essentials_score, essentials_notes = _score_missing_essentials(project_root)

    total_score = bin_score + readme_score + ratio_score + essentials_score
    state.atomic_write(last_hash_file, combined)

    if total_score < _THRESHOLD:
        state.rotate_log_if_big(_NAME)
        return 0

    all_notes = bin_notes + readme_notes + ratio_notes + essentials_notes
    cap = 6
    sample = "\n".join(f"  - {state.sanitize_for_drift_line(n)}" for n in all_notes[:cap])
    if len(all_notes) > cap:
        sample += f"\n  - …and {len(all_notes) - cap} more"

    print(
        f"[repo-trust-score] this project matches the dropper-shape pattern "
        f"(trust-deficit score {total_score} ≥ {_THRESHOLD}). The two known-"
        f"malicious repos in our study (snakebite, Pipeline-Sentinel) scored "
        f"14-16 with this exact pattern set. Inspect manually before asking "
        f"the agent to read README.md or execute any code from this tree.\n"
        f"{sample}"
    )
    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
