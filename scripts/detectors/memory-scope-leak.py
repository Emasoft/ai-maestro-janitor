#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
# pyyaml: cicd_secret_leak_patterns' yaml-structured rules need it (that lib now
# fail-softs without yaml, but declaring the dep keeps those rules ACTIVE here).
"""memory-scope-leak — keep the PUSHED memory scope free of machine/user-private data.

The memory system has THREE scopes (TRDD-c77dae09): LOCAL
(`~/.claude/projects/<slug>/memory/`, per-machine, never pushed), PROJECT
(`<git-root>/.claude/project/memory/`, git-tracked + PUSHED, shared with every
dev), and USER (the janitor PLUGIN_DATA dir `${CLAUDE_PLUGIN_DATA}/memory/`,
global, never pushed). The PROJECT scope is the only one
that LEAVES the machine, so it is the one that can leak: a contributor who pastes
a `/Users/<name>/…` path, an email, a hostname, or a stray token into a PROJECT
page would push that private material to GitHub for everyone to see.

THIS DETECTOR is the load-bearing janitor enforcement piece (the USER's directive
in the THREE-SCOPE addendum). It SURFACES, it never mutates:

  * Scans every `<git-root>/.claude/project/memory/**/*.md` page (the
    would-be-pushed PROJECT scope) with the local-path lib
    (`private_path_patterns`), the PII shapes
    (`privacy_patterns.PII_SHAPES`), the credential shape libs
    (`cloud_credential_patterns`, `cicd_secret_leak_patterns`), and an
    unknown-secret entropy pass (`security_helpers.shannon_entropy` +
    `looks_like_base64`). Each hit becomes a
    `[memory-scope-leak] <file>: <class> — demote to LOCAL scope before push`
    finding: the material belongs in LOCAL, not in the shared page.
  * gitignore guards: PROJECT `.claude/project/memory/` must be TRACKED — but it
    lives under `.claude/`, which is very commonly gitignored, so if a
    `.gitignore` rule swallows it the shared scope would silently never be
    pushed (`git check-ignore`). The fix is a gitignore EXCEPTION
    (`!.claude/project/memory/**`); the guard surfaces that. And a LOCAL-shaped
    store committed INSIDE the repo (a `projects/<slug>/memory/` tree) is itself
    a leak of the local corpus.
  * ZERO mutation of any memory page (RULE 0). It only READS pages and WRITES a
    proposal file (`memory-scope-leak-proposed.md`, NOT a note) + emits one
    heartbeat line.

Graceful no-op (never crashes the heartbeat): not a git repo, no PROJECT
`.claude/project/memory/` dir, an empty corpus, or an unchanged finding set → exit silently with
no output. Project-scoped — never touches user/global scope; the janitor's own
repo is skipped (`state.is_self_scan_target`) unless `CLAUDE_PLUGIN_ALLOW_SELF_SCAN`.

The tool's own `.memgrep/` index sidecar inside `memory/` is NEVER scanned (it
is generated cache, not a note). The LOCAL corpus
(`~/.claude/projects/<slug>/memory/`) lives OUTSIDE the repo by construction, so
it is not scanned here — only what is about to be pushed is policed.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import ai_context_extras as acx  # noqa: E402
import cicd_secret_leak_patterns as cicd  # noqa: E402
import cloud_credential_patterns as cloud  # noqa: E402
import dedupe  # noqa: E402
import privacy_patterns as privacy  # noqa: E402
import private_path_patterns as ppp  # noqa: E402
import security_helpers as sec  # noqa: E402
import state  # noqa: E402

# The detector's own output file — written into the PROJECT memory dir but it is
# NOT a memory note. It lives at the `.claude/project/memory/` root; it is a
# proposal artifact like the librarian's, and is excluded from scanning by name.
PROPOSAL_NAME = "memory-scope-leak-proposed.md"

# Files inside memory/ that are NOT pages and must be skipped (indices + the two
# proposal files the memory detectors write). Compared case-sensitively.
_NON_PAGE_NAMES = frozenset({
    PROPOSAL_NAME,
    "memory-reorg-proposed.md",  # the librarian's proposal
    "MEMORY.md",
    "memory-index.md",
})

# Generated cache dir inside memory/ — never a page (memgrep's SQLite sidecar).
_MEMGREP_DIRNAME = ".memgrep"

# Bounds so a huge corpus can never blow up the heartbeat.
_MAX_PAGES = 2000
_MAX_FINDINGS_LISTED = 60
_MAX_BYTES_PER_PAGE = 256 * 1024  # don't read a pathologically large "page"

# Unknown-secret entropy gate (mirrors security_helpers.shannon_entropy's
# documented convergent threshold): a base64-ish token ≥ this long with entropy
# above this bit/char that no other lib already matched is a likely secret.
_ENTROPY_MIN_LEN = 24
_ENTROPY_MIN_BITS = 4.5
# Candidate token: a run of base64-alphabet chars (std + url-safe). Bounded.
_TOKEN_RE = re.compile(r"[A-Za-z0-9+/_\-=]{%d,512}" % _ENTROPY_MIN_LEN)

# A TRACKED repo path that reproduces the harness LOCAL-corpus shape
# (`…/projects/<x>/memory/…`) — committing one leaks the per-machine store.
_LOCAL_SHAPED_RE = re.compile(r"(?P<dir>(?:^|.+/)projects/[^/]+/memory)/")

# RFC 2606 / RFC 6761 reserve these TLDs (+ mDNS's `.local`, RFC 6762) for
# documentation, testing, and non-routable use — an address on one of them can
# never be a real mailbox that leaked (issue #176). A page quoting
# `alice@default.local` to document an addressing FORMAT is not a leak.
_RESERVED_EMAIL_DOMAIN_SUFFIXES = (".local", ".test", ".example", ".invalid", ".localhost")


def _is_reserved_documentation_email(addr: str) -> bool:
    """True iff `addr`'s domain is a reserved documentation/loopback TLD, so the
    match can never name a real mailbox (issue #176's `pii:email` false positives:
    an address-format spec, all on `.local`)."""
    domain = addr.rsplit("@", 1)[-1].lower().rstrip(".")
    return domain.endswith(_RESERVED_EMAIL_DOMAIN_SUFFIXES)


def _git_toplevel(cwd: Path) -> Path | None:
    """Resolve the repo's top-level dir, or None when `cwd` is not a git repo.

    Robust to worktrees and any checkout dir name (we never assume
    CLAUDE_PROJECT_DIR == the repo root, though it usually is).
    """
    proc = state.run_subprocess(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd, detector_name="memory-scope-leak",
    )
    if proc is None or proc.returncode != 0:
        return None
    top = proc.stdout.strip()
    return Path(top) if top else None


def _is_path_gitignored(root: Path, rel: str) -> bool:
    """True iff `rel` (a repo-relative path) is matched by a .gitignore rule.

    `git check-ignore -q` exits 0 when the path IS ignored. Mirrors
    nested-git-safety.py's usage.
    """
    proc = state.run_subprocess(
        ["git", "check-ignore", "-q", "--", rel],
        cwd=root, detector_name="memory-scope-leak",
    )
    return proc is not None and proc.returncode == 0


def _iter_pages(memdir: Path) -> list[Path]:
    """Every `*.md` page under the PROJECT memory dir, EXCLUDING the `.memgrep/`
    index sidecar and the non-page index/proposal files. Sorted for determinism;
    bounded by `_MAX_PAGES`."""
    pages: list[Path] = []
    for p in sorted(memdir.rglob("*.md")):
        # Skip anything inside a .memgrep/ cache dir at any depth.
        if _MEMGREP_DIRNAME in p.parts:
            continue
        if p.name in _NON_PAGE_NAMES:
            continue
        if not p.is_file():
            continue
        pages.append(p)
        if len(pages) >= _MAX_PAGES:
            break
    return pages


def _entropy_findings(text: str) -> list[str]:
    """Class labels for unknown-format high-entropy secrets in `text`.

    A base64-ish token ≥ `_ENTROPY_MIN_LEN` chars with Shannon entropy above
    `_ENTROPY_MIN_BITS` that looks_like_base64 is a likely secret no named lib
    caught. Returns a (possibly empty) list of `"high-entropy secret"` labels —
    one per distinct offending token (deduped within the page).
    """
    out: list[str] = []
    seen_tokens: set[str] = set()
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0)
        if tok in seen_tokens:
            continue
        seen_tokens.add(tok)
        if not sec.looks_like_base64(tok, min_len=_ENTROPY_MIN_LEN):
            continue
        if sec.shannon_entropy(tok) < _ENTROPY_MIN_BITS:
            continue
        out.append("high-entropy secret")
    return out


def _scan_page(page: Path) -> list[str]:
    """All leak-class labels found in one PROJECT memory page.

    Composes the four catalogues. Each finding is reduced to a short class label
    (the rule kind / PII shape name / credential rule id / entropy) — the
    detector surfaces the CLASS, not the matched secret value (never echo the
    leaked material into the heartbeat or the proposal). Returns a sorted, deduped
    list of `<class>` strings.

    Fenced/inline CODE is masked before any scanner runs (issue #176): a memory
    page routinely QUOTES a format spec, a `git clone git@host:...` example, or a
    filename inside backticks — those are documentation, not live secrets, and
    the leak scanners have no other way to tell "the page states this fact" from
    "the page IS this fact". Masking preserves line/character offsets (same-length
    spaces) so this stays a pure preprocessing step, not a rewrite of `text`.
    """
    try:
        if page.stat().st_size > _MAX_BYTES_PER_PAGE:
            return []
        text = page.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text:
        return []

    masked = acx.mask_markdown_code_blocks(text)
    labels: set[str] = set()

    # 1. Local-path / machine-identity (the new lib).
    for f in ppp.scan_text(masked):
        labels.add(f.kind)  # "local-path" | "machine-host"

    # 2. PII shapes (email/phone/SSN/credit-card/IBAN/passport). We use the named
    #    shapes directly (not privacy.scan_text, which also fires source-only
    #    rules like cookie/CSP that don't apply to a markdown memory page).
    for shape_name, pattern in privacy.PII_SHAPES.items():
        for m in pattern.finditer(masked):
            if shape_name == "credit_card" and not privacy.luhn_valid(m.group(0)):
                continue  # drop non-card 16-digit runs (dates, ids)
            if shape_name == "email" and _is_reserved_documentation_email(m.group(0)):
                continue  # a `.local`/`.test`/`.example`/`.invalid` address can't leak
            labels.add(f"pii:{shape_name}")
            break  # one label per shape is enough to flag the page

    # 3. Credential shapes (cloud + CI/CD secret leak libs).
    for f in cloud.scan_text(masked):
        labels.add("credential")
    for f in cicd.scan_text(masked):
        labels.add("credential")

    # 4. Unknown-format high-entropy secrets.
    for label in _entropy_findings(masked):
        labels.add(label)

    return sorted(labels)


def _gitignore_guards(root: Path, memdir: Path) -> list[str]:
    """Guard findings about the gitignore invariants. Returns guard-line bodies.

    (a) PROJECT `.claude/project/memory/` must be TRACKED — but it lives under
        `.claude/`, which is very commonly gitignored, so a `.gitignore` rule
        easily swallows the present dir and the shared scope would silently never
        be pushed. `memdir` already exists here (the caller only invokes this when
        the dir is present), so an "ignored" verdict means a missing exception:
        the fix is to add `!.claude/project/memory/**` after the `.claude/` rule.
    (b) A LOCAL-shaped store committed inside the repo (a `projects/<slug>/memory`
        tree, i.e. the harness LOCAL corpus checked into the repo) is a leak of
        the entire local corpus.
    """
    guards: list[str] = []
    rel_memdir = memdir.relative_to(root).as_posix() + "/"
    if _is_path_gitignored(root, rel_memdir):
        guards.append(
            "PROJECT .claude/project/memory/ is gitignored — it must be TRACKED "
            "and pushed (the shared scope is silently excluded from the repo). "
            "Since it lives under .claude/ (commonly ignored), add a gitignore "
            "exception: `!.claude/project/`, `!.claude/project/memory/`, then "
            "`!.claude/project/memory/**`"
        )
    # (b) LOCAL-shaped dirs inside the repo: any TRACKED `.../projects/<x>/memory/…`
    # path. The harness LOCAL corpus lives at ~/.claude/projects/<slug>/memory; if
    # such a tree was committed it leaks per-machine private notes.
    #
    # F18 (wikimem audit 2026-07-07): the old `root.rglob("projects")` walked the
    # ENTIRE tree — node_modules, .git, build dirs — unbounded, every fire. On a
    # large repo that alone could exceed dispatch's 120 s detector timeout; the
    # SIGKILL landed AFTER the cadence stamp, silently disabling the whole
    # PROJECT-scope leak scan for that repo forever. `git ls-files` is ONE bounded
    # subprocess, and considering only TRACKED paths matches the threat model
    # exactly (an untracked vendored `projects/<x>/memory/` can't leak via push —
    # which also kills that monorepo false positive).
    proc = state.run_subprocess(
        ["git", "ls-files", "-z"], cwd=root, detector_name="memory-scope-leak",
    )
    if proc is not None and proc.returncode == 0:
        local_shaped: set[str] = set()
        for rel in proc.stdout.split("\0"):
            m = _LOCAL_SHAPED_RE.match(rel)
            if m:
                local_shaped.add(m.group("dir"))
        for rel in sorted(local_shaped)[:5]:
            guards.append(
                f"LOCAL-shaped memory store inside the repo ({rel}) — "
                "the per-machine LOCAL corpus must never be committed"
            )
    return guards


def _render_proposal(
    page_findings: list[tuple[str, list[str]]],
    guards: list[str],
) -> str:
    """Render the human/agent-facing leak proposal. NEVER includes the matched
    secret value — only the page path and the leak class(es)."""
    lines: list[str] = [
        "# Memory scope-leak — PROJECT pages carrying machine/user-private data",
        "",
        "The PROJECT memory scope (`<git-root>/.claude/project/memory/`) is git-tracked",
        "and PUSHED, so it MUST NOT carry machine/user-private material. The pages below",
        "carry a leak class that belongs in the LOCAL scope",
        "(`~/.claude/projects/<slug>/memory/`, never pushed). An AGENT should DEMOTE",
        "the offending fact to LOCAL (move it / rewrite the page portable). The",
        "janitor only SURFACES — it never edits a page (RULE 0).",
        "",
    ]
    if guards:
        lines.append("## gitignore guards")
        lines.append("")
        for g in guards:
            lines.append(f"- {g}")
        lines.append("")
    if page_findings:
        lines.append("## Pages with leak candidates")
        lines.append("")
        shown = 0
        for rel, classes in page_findings:
            lines.append(f"- `{rel}` — {', '.join(classes)} — demote to LOCAL scope")
            shown += 1
            if shown >= _MAX_FINDINGS_LISTED:
                lines.append(f"- … ({len(page_findings) - shown} more pages elided)")
                break
        lines.append("")
    lines.append(
        "_Surfaced by the `memory-scope-leak` detector. Resolve by moving the "
        "private fact to the LOCAL scope (the harness `# Memory` dir), or by "
        "rewriting the PROJECT page to be portable (no usernames/paths/hosts/"
        "secrets). Re-run clears this once the leak is gone._"
    )
    return "\n".join(lines) + "\n"


def _fingerprint(
    page_findings: list[tuple[str, list[str]]],
    guards: list[str],
) -> str:
    """Stable hash of the finding SET (pages+classes + guards) so an unchanged
    leak set is a complete no-op (no heartbeat line, no proposal churn)."""
    h = hashlib.sha256()
    for rel, classes in sorted(page_findings):
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update("|".join(classes).encode("utf-8"))
        h.update(b"\x01")
    h.update(b"\x02")
    for g in sorted(guards):
        h.update(g.encode("utf-8"))
        h.update(b"\x03")
    return h.hexdigest()[:16]


def main() -> int:
    # Hard self-scan guard — the janitor's own repo would otherwise flag the
    # janitor's own (intentional, example) private-path strings.
    if state.is_self_scan_target():
        return 0
    state.init_state()

    cwd = state.project_root()
    root = _git_toplevel(cwd)
    if root is None:
        # Not a git repo → there is no PROJECT (pushed) scope to police.
        state.log_line("memory-scope-leak", "not a git repo — skipping")
        return 0

    memdir = root / ".claude" / "project" / "memory"
    has_memdir = memdir.is_dir()

    # gitignore guards run even when memory/ has no pages yet (an ignored-but-
    # present memory/ is exactly the case we must catch early).
    guards = _gitignore_guards(root, memdir) if has_memdir else []

    page_findings: list[tuple[str, list[str]]] = []
    if has_memdir:
        for page in _iter_pages(memdir):
            classes = _scan_page(page)
            if classes:
                rel = page.relative_to(root).as_posix()
                page_findings.append((rel, classes))

    if not page_findings and not guards:
        # Clean (or absent) PROJECT scope → nothing to surface.
        # F19 (wikimem audit 2026-07-07): the proposal's own footer promises
        # "Re-run clears this once the leak is gone" — honor it. A stale proposal
        # lives IN-REPO in the pushed memory dir, telling every contributor there
        # is a leak forever. It is a regeneratable detector artifact (never a
        # note), so remove it; also drop the dedupe seen-file so an IDENTICAL
        # leak set recurring later re-emits instead of being silently suppressed
        # by the stale fingerprint key.
        if has_memdir:
            stale = memdir / PROPOSAL_NAME
            if stale.is_file():
                try:
                    stale.unlink()
                    (state.state_dir() / "memory-scope-leak-seen.txt").unlink(missing_ok=True)
                    state.log_line("memory-scope-leak", "leak set clean — removed stale proposal")
                except OSError:
                    pass  # best-effort; the next clean run retries
        state.rotate_log_if_big("memory-scope-leak")
        return 0

    # Dedupe BEFORE writing: an unchanged finding set is a complete no-op.
    seen = state.state_dir() / "memory-scope-leak-seen.txt"
    fp = _fingerprint(page_findings, guards)
    n_pages = len(page_findings)
    n_guards = len(guards)
    parts = []
    if n_pages:
        parts.append(f"{n_pages} page(s) with private data")
    if n_guards:
        parts.append(f"{n_guards} gitignore guard(s)")
    msg = (
        f"[memory-scope-leak] {' + '.join(parts)} in PROJECT memory/ "
        f"— see {PROPOSAL_NAME} (demote to LOCAL scope before push)"
    )
    line = dedupe.emit_once(seen, f"scopeleak-{fp}", msg)
    if line is None:
        # Unchanged finding set — silent, no proposal churn (idempotent).
        state.rotate_log_if_big("memory-scope-leak")
        return 0

    proposal = _render_proposal(page_findings, guards)
    try:
        state.atomic_write(memdir / PROPOSAL_NAME, proposal)
    except OSError as exc:
        # Cannot write the proposal (e.g. memory/ vanished mid-run) → do not emit
        # a line pointing at a file that isn't there.
        state.log_line("memory-scope-leak", f"could not write proposal: {exc}")
        return 0

    print(line)
    state.rotate_log_if_big("memory-scope-leak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
