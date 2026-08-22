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
import memory_edit_verify as mev  # noqa: E402
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

# `publish-globally` (janitor#52) SYMLINKS a PROJECT page into the USER root, so it is
# recalled from EVERY project on the machine. Two consequences the four leak catalogues
# cannot see on their own, because both live in the FRONTMATTER rather than in a secret
# shape:
#
#   * a leak on a PUBLISHED page has fleet-wide blast radius, so the proposal's stock
#     "demote to LOCAL scope" remedy is actively wrong there — demoting one project's
#     copy does not retract what every other project already reads;
#   * only the BARE BOOLEAN may be committed. A value carrying data
#     (`publish-globally: my-secret-project`) or a `published-*` identity key beside the
#     flag publishes a private project name into a pushed file.
_BOOLEAN_LITERALS = frozenset({"true", "false"})
_PUBLISHED_MARKER = "published"
_PUBLISHED_IDENTITY_LEAK = "published-identity-leak"


def _published_state(text: str) -> tuple[bool, bool]:
    """`(is_published, identity_leak)` read from a page's wikimem frontmatter.

    Reuses `memory_edit_verify.parse_frontmatter`, which keeps scalars as verbatim
    (quote-stripped) STRINGS — that is what makes the bare-boolean test possible at all; a
    parser that coerced `true` to a Python bool would erase the distinction this check
    exists to make.

    Note `parse_frontmatter` hoists `metadata:` sub-keys to the top level, so a
    `published-*` key hidden under `metadata:` is caught too — deliberate, not incidental.
    """
    fm = mev.parse_frontmatter(text)
    if not fm:
        return False, False
    published = False
    identity_leak = any(str(k).startswith("published-") for k in fm)
    raw = fm.get("publish-globally")
    if raw is not None:
        val = raw.strip().lower() if isinstance(raw, str) else ""
        if val in _BOOLEAN_LITERALS:
            published = val == "true"
        else:
            # A non-boolean VALUE is itself the leak — the field's whole contract is that
            # it says WHETHER, never WHAT.
            identity_leak = True
    return published, identity_leak

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


# `owner/repo@ref` — a GIT REF SPEC, not an ssh `user@host` (janitor#209). The ssh rule sees the
# `@` and reads `ai-maestro@governance-rules` as account+machine; what precedes it is an `owner/`
# segment, which no ssh target has. The lookbehind rejects `://` and `:` so a genuine
# `ssh://deploy@prod-box` or `scp -P 22:deploy@host` still convicts — only a bare `owner/repo@ref`
# is exempt. Documentation that CITES a repo by ref is routine on a project memory page, and this
# detector is a PRE-PUSH control, so a false positive here costs a real push.
_GIT_REF_OWNER_RE = r"(?<![:/])[A-Za-z0-9._-]+/"


def _is_git_ref_spec(text: str, matched: str) -> bool:
    """True iff `matched` (an ssh-user-host hit) is really the `repo@ref` half of a git ref spec."""
    return re.search(_GIT_REF_OWNER_RE + re.escape(matched) + r"(?::[^\s]+)?", text) is not None


# A FILESYSTEM PATH, never a secret (janitor#209). `/` is in the base64 alphabet, so any long
# enough path satisfies the entropy test — `skills/team-governance/references/GOVERNANCE-RULES.md`
# scored as a pasted token. Requiring BOTH a separator and a real file extension is what keeps this
# from becoming a hole: a base64 secret does not end in `.md`/`.py`, and a token carrying a vendor
# prefix or the generic secret shape is convicted BEFORE this exemption is consulted.
# The extension is checked in the SOURCE TEXT, not in the token: `_TOKEN_RE` excludes `.`, so a
# token can never contain the `.md` that proves it is a filename — an earlier version tested the
# token itself and was therefore unreachable dead code that silently exempted nothing.
_PATH_EXT_AFTER_RE = re.compile(r"\.[A-Za-z0-9]{1,8}(?![A-Za-z0-9])")


def _is_path_shaped(tok: str, text: str, end: int) -> bool:
    """True iff the token at `text[:end]` is a repo-relative file path, not an opaque secret.

    Requires BOTH halves, which is what keeps it from being a hole: at least one `/` separator in
    the token, AND a real file extension immediately following it in the source. A pasted base64
    credential has no `.md`/`.py` suffix, and a token bearing a vendor prefix or the generic secret
    shape is convicted by the caller before this is consulted.
    """
    return "/" in tok and _PATH_EXT_AFTER_RE.match(text, end) is not None


# Where the ENTROPY heuristic needs corroboration (ai-maestro-plugins#14: 3 of 3 entropy
# findings in one night were structural false positives — none was a secret):
#   - fenced code blocks and inline `code` spans: documentation cites identifiers and paths in
#     code markup BY CONVENTION, and `statuslineCostUsd`-style camelCase or a `reports/...` path
#     is base64-alphabet text with prose-beating entropy. The better a page documents code, the
#     more reliably raw entropy flags it.
#   - `keywords:`/`desc:` metadata lines and `[^N]: [...]` lesson-address lines: the wikimem
#     format REQUIRES `underscore_joined_phrases` keyword lists — long, mixed-case, no spaces,
#     indistinguishable from a token by entropy. The page author cannot avoid them.
#
# These regions are NOT blanked — that was the first draft, and its own counter-case test caught
# the blind spot: the cloud/CI-CD credential libs carry ZERO pasted-token shape rules (they are
# workflow-misconfiguration scanners), so this entropy pass is the detector's ONLY catcher for a
# real token pasted into a note, and a code fence (a command example) is the single most common
# place one lands. Inside code/metadata regions a candidate must therefore ALSO match a known
# secret shape (the issue's suggestion 2); in prose, entropy alone still suffices, because none
# of the documented false-positive shapes occur there.
_FENCED_CODE_RE = re.compile(r"(?ms)^(?:```|~~~).*?^(?:```|~~~)[ \t]*$")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
# Three metadata line shapes, because the wikimem address grammar has three spellings: a
# frontmatter-style `keywords:`/`desc:` line, a `[^N]:` lesson-address line, and the memgrep atom
# address `anchor [keywords: …]` where the field sits MID-line inside brackets (found by probing a
# real corpus: five 44–406-char underscore phrases in that third form sailed past the first two
# alternatives).
_META_LINE_RE = re.compile(
    r"(?m)^[ \t]*\"?(?:keywords|desc|description)\"?[ \t]*:.*$"
    r"|^\[\^\d+\]:.*$"
    r"|^.*\[(?:keywords?|desc|description)[ \t]*:.*$"
)

# Recognisable secret-token prefixes — each is a documented, vendor-fixed literal, so this list
# trades recall for precision ONLY inside code/metadata regions (prose keeps full recall). A
# camelCase identifier, a repo path, or an underscore_joined keyword phrase can never start with
# one of these.
_SECRET_SHAPE_RE = re.compile(
    r"^(?:"
    r"sk[-_]|pk_live_|rk_live_"      # OpenAI / Stripe key families
    r"|ghp_|gho_|ghu_|ghs_|ghr_|github_pat_"  # GitHub token families
    r"|glpat-|npm_|nvapi-|dop_v1_|pypi-|shpat_|shpss_|hf_"  # GitLab/npm/NVIDIA/DO/PyPI/Shopify/HF
    r"|xox[abops]-"                  # Slack
    r"|AIza|ya29\."                  # Google API / OAuth
    r"|AKIA|ASIA"                    # AWS access key ids
    r"|eyJ"                          # a JWT (base64 of '{"')
    r"|age1|SG\."                    # age recipient / SendGrid
    r")"
)

# The GENERIC conviction path for code/metadata regions — a real credential with a prefix nobody
# listed (the PR-204 review's P1: prefixes-only made this pass blind to unlisted vendors exactly
# where tokens get pasted). The discriminator is MEASURED, not guessed, because the obvious gate
# (mixed case + digits) is falsified by this corpus: a TRDD file citation measures entropy 4.51
# with all 3 character classes — over both bars. What separates it (and every timestamped path)
# from a random secret is a LONG DIGIT RUN: `20260805_130129+0200` carries an 8-digit run, while
# a uniformly random base64 token of realistic length contains 6 consecutive digits with
# probability ≈ n·(10/64)^6 ≈ 0.02% — the same insight as the librarian's date-shaped-number
# filter, applied to tokens. So inside code/metadata a token convicts when entropy ≥ the gate AND
# it uses all 3 character classes AND it has no ≥6-digit run.
_LONG_DIGIT_RUN_RE = re.compile(r"\d{6}")


def _generic_secret_shape(tok: str) -> bool:
    """A shape-based conviction for unlisted-prefix credentials (entropy is checked by the caller)."""
    if _LONG_DIGIT_RUN_RE.search(tok):
        return False  # timestamps/dates/ids — the measured false-positive family
    classes = (
        any(c.islower() for c in tok)
        + any(c.isupper() for c in tok)
        + any(c.isdigit() for c in tok)
    )
    return classes == 3


def _code_meta_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of code markup + wikimem metadata lines (merged, sorted)."""
    spans = [m.span() for rx in (_FENCED_CODE_RE, _INLINE_CODE_RE, _META_LINE_RE) for m in rx.finditer(text)]
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _in_spans(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(s <= pos < e for s, e in spans)


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
    spans = _code_meta_spans(text)
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0)
        if tok in seen_tokens:
            continue
        seen_tokens.add(tok)
        if not sec.looks_like_base64(tok, min_len=_ENTROPY_MIN_LEN):
            continue
        if sec.shannon_entropy(tok) < _ENTROPY_MIN_BITS:
            continue
        # Checked BEFORE the region test but AFTER the shape tests below would have run, so a
        # credential is never exempted: a path that also carries a vendor prefix or the generic
        # secret shape is not path-shaped by this regex (those tokens have no `/`+extension).
        if (
            _is_path_shaped(tok, text, m.end())
            and not _SECRET_SHAPE_RE.match(tok)
            and not _generic_secret_shape(tok)
        ):
            continue
        # In code markup / wikimem metadata, entropy alone is not evidence (see the block above
        # _SECRET_SHAPE_RE): identifiers, paths and keyword phrases live there by convention and
        # beat prose entropy. A known vendor prefix convicts, and so does the generic
        # 3-classes-no-digit-run shape (_generic_secret_shape) — the PR-204 review's P1 gap:
        # prefixes alone left unlisted-vendor credentials invisible exactly where they get pasted.
        if (
            _in_spans(m.start(), spans)
            and not _SECRET_SHAPE_RE.match(tok)
            and not _generic_secret_shape(tok)
        ):
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
        if f.rule_id == "private-path.ssh-user-host" and _is_git_ref_spec(masked, f.matched_text):
            continue  # `owner/repo@ref` is a git ref, not an account on a machine (janitor#209)
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

    # 4. Unknown-format high-entropy secrets. Region-aware (ai-maestro-plugins#14):
    #    in prose, entropy alone convicts; in code markup / wikimem metadata a
    #    known secret shape is also required, because entropy is a guesser, not a
    #    recogniser, and identifiers/keywords live there by convention.
    for label in _entropy_findings(text):
        labels.add(label)

    # 5. publish-globally hygiene (janitor#52, TRDD-4GQ94FNJ). The identity leak is a
    #    finding in its own right; being PUBLISHED is not. The marker is added ONLY
    #    alongside a real finding, because publishing is an intentional, approved act and
    #    a detector that flagged a clean published page would nag about the feature
    #    working — which is how a true-positive channel gets ignored.
    published, identity_leak = _published_state(text)
    if identity_leak:
        labels.add(_PUBLISHED_IDENTITY_LEAK)
    if published and labels:
        labels.add(_PUBLISHED_MARKER)

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
        "carry a leak class that MAY belong in the LOCAL scope",
        "(`~/.claude/projects/<slug>/memory/`, never pushed).",
        "",
        "**VERIFY EACH MATCH BEFORE ACTING — these are SHAPE matches, not meaning",
        "matches, and a false positive is COMMON.** Demoting a correctly-PROJECT page",
        "removes it from the pushed corpus every contributor shares, so acting on an",
        "unverified hit DESTROYS shared knowledge. Open the page, find the token, and",
        "confirm it is genuinely machine/user-private. Known systematic collisions:",
        "",
        "- `machine-host` fires on ANY `.local` suffix. Legitimate non-host senses seen",
        "  in practice: scope/team placeholders (`default.local`, `myteam.local`,",
        "  `org.local`) and the FILENAME `settings.local.json` — a page documenting that",
        "  config file is flagged for naming its own subject.",
        "- `pii:us_passport` is `[A-Z]` + 8 digits, which is also the shape of a",
        "  governance/verdict id (`G20260731`) and of many date-suffixed ids. A corpus",
        "  that mints ids in that shape collides with it systematically.",
        "",
        "Only when the hit is REAL: demote the offending fact to LOCAL (move it, or",
        "rewrite the page portable). If the hit is a false positive, leave the page",
        "ALONE — do not 'fix' it, and do not delete the knowledge. The janitor only",
        "SURFACES — it never edits a page (RULE 0), and neither should an agent acting",
        "on an unverified match.",
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
            # A PUBLISHED page's remedy is NOT the stock one: the page is symlinked into
            # the USER root and read by every project, so moving this copy to LOCAL
            # retracts nothing. Say so instead of printing advice that under-states the
            # blast radius. The marker is presentation only — drop it from the class list
            # so the leak CLASSES stay the leak classes.
            if _PUBLISHED_MARKER in classes:
                shown_classes = [c for c in classes if c != _PUBLISHED_MARKER]
                remedy = (
                    "PUBLISHED (`publish-globally: true`) — symlinked into the USER root "
                    "and recalled from EVERY project, so demoting THIS copy retracts "
                    "nothing; fix the page itself, then reconsider whether it should stay "
                    "published"
                )
            else:
                shown_classes = classes
                remedy = "demote to LOCAL scope"
            lines.append(f"- `{rel}` — {', '.join(shown_classes)} — {remedy}")
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
