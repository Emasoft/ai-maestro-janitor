"""Shared TRDD-parsing helpers + the state-reconciliation checks (stdlib-only).

This module hoists the TRDD frontmatter/filename parsing that was duplicated
inline in `scripts/detectors/trdd-drift.py` and `trdd-reminder.py`, so all the
TRDD detectors share ONE source of truth for "what is a TRDD's column" and "what
is its id". It also implements the FOUR pure checks of the state-reconciliation
detector (TRDD-15ECPBSA) — each a pure function over a parsed `TrddRecord` plus
an injectable `commit -> {tags}` map, so they are unit-testable with zero git.

No I/O beyond reading the head of a TRDD file (`parse_trdd_state`); everything
else operates on already-read text + parsed structures.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

try:  # hooks put scripts/ on sys.path → package import
    from lib import memory_scopes
except ImportError:  # detectors/tests put scripts/lib/ on sys.path → flat import
    import memory_scopes  # type: ignore[no-redef]

# ── The two design SCOPES (the SSOT every TRDD consumer must route through) ──
#
# A TRDD's scope IS ITS PATH — exactly like a memory note. There is no `scope:`
# frontmatter field to keep in sync, and therefore none to get wrong:
#
#   PROJECT  <repo>/design/                      git-tracked + PUSHED — shared with
#                                                every contributor.
#   LOCAL    ~/.claude/projects/<slug>/design/   machine-private, OUTSIDE any repo —
#                                                never pushed, and (unlike a gitignored
#                                                in-repo dir) not destroyed by
#                                                `git clean -fdx`.
#
# LOCAL mirrors the repo's `design/` EXACTLY — the same four lifecycle folders
# (`proposals/ tasks/ archived/ refused/`). Mirroring the whole dir, rather than
# hanging a bare `tasks/` off the slug, is what avoids a `tasks/tasks/` once the
# lifecycle folders land (3-pillars spec, decided by its maintainer 2026-07-11).
#
# WHY this is an SSOT and not a constant copied into each caller: before this, all
# eight consumers (trdd-drift, trdd-reminder, trdd-state-reconciliation,
# report-to-trdd-drift, fleet_status, and the session-start / pre-compact /
# post-compact hooks) each hardcoded `project_root / "design" / "tasks"` on their
# own. Adding a second root by copy-paste would silently miss one, and a TRDD
# consumer that cannot see a scope makes that scope's tasks invisible — the same
# "two input paths ≠ SSOT" shape that let the rotator's LOG_FILE diverge from its
# isolated ROOT and append to the production log.
#
# The slug comes from `memory_scopes.project_slug` — the one definition the harness
# agrees with. It is NOT re-derived here: a separators-only translation of the same
# idea once resolved a nonexistent dir and silently emptied the whole LOCAL memory
# subsystem, and a second copy of that logic would put LOCAL design one typo away
# from the same fate.
LOCAL = "local"
PROJECT = "project"

# The four lifecycle folders, in pipeline order. Both scopes carry all four.
DESIGN_FOLDERS = ("proposals", "tasks", "archived", "refused")


def _project_root(project_dir: str | None) -> Path:
    return Path(project_dir or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def project_tasks_dir(project_dir: str | None = None) -> Path | None:
    """The PROJECT tasks dir, honoring `CLAUDE_PLUGIN_OPTION_TRDD_PATH`.

    Returns None when the configured path ESCAPES the project root — a misconfigured
    option (absolute path, `../` escape, or a symlink out of the tree) must never make a
    detector scan outside the project. The well-formed default `design/tasks` always
    passes; only typo'd values fail. This containment check is hoisted verbatim from the
    detectors, which each carried their own copy.
    """
    root = _project_root(project_dir)
    subpath = os.environ.get("CLAUDE_PLUGIN_OPTION_TRDD_PATH", "design/tasks").rstrip("/")
    tasks = root / subpath
    try:
        tasks.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return tasks


def project_design_root(project_dir: str | None = None) -> Path | None:
    """`<repo>/design` — the PROJECT (shared, git-tracked) design root.

    Derived as the PARENT of the resolved tasks dir, so a project that relocated its
    TRDDs via `CLAUDE_PLUGIN_OPTION_TRDD_PATH` keeps its whole lifecycle together (the
    option has only ever governed the tasks dir, and hardcoding `<root>/design` here
    would silently ignore it). None when the option escapes the root.
    """
    tasks = project_tasks_dir(project_dir)
    return None if tasks is None else tasks.parent


def local_design_root(project_dir: str | None = None) -> Path:
    """`~/.claude/projects/<slug>/design` — the LOCAL (machine-private) design root.

    NOT containment-checked against the project root: living OUTSIDE the repo is the
    entire point of this scope, so the check that protects PROJECT would reject LOCAL
    outright. It needs no such check — the path is derived from the project slug, never
    from a user-supplied string, so there is nothing here for a bad option to escape with.
    """
    root = _project_root(project_dir)
    return memory_scopes.resolve_local_dir_for(str(root)).parent / "design"


def design_roots(project_dir: str | None = None) -> list[tuple[str, Path]]:
    """Every design root that EXISTS, as `(scope, root)`, most-specific first.

    LOCAL before PROJECT, mirroring `memory_scopes.resolve_scope_dirs()`. A root that
    does not exist is simply absent — a project with no local design dir is the norm,
    not an error, and must never be reported as drift.
    """
    out: list[tuple[str, Path]] = []
    local = local_design_root(project_dir)
    if local.is_dir():
        out.append((LOCAL, local))
    proj = project_design_root(project_dir)
    if proj is not None and proj.is_dir():
        out.append((PROJECT, proj))
    return out


def scope_folder(scope: str, folder: str, project_dir: str | None = None) -> Path | None:
    """The concrete dir for one (scope, lifecycle-folder) pair, or None if unresolvable.

    PROJECT + `tasks` is the ONE case that cannot be derived by joining a folder name to
    a root: `CLAUDE_PLUGIN_OPTION_TRDD_PATH` names the tasks dir OUTRIGHT, so with
    `TRDD_PATH=docs/trdds` the design root is `docs/` and joining `tasks` onto it would
    look in `docs/tasks` — a dir that does not exist. Take the override's own path.
    """
    if scope == PROJECT:
        if folder == "tasks":
            return project_tasks_dir(project_dir)
        root = project_design_root(project_dir)
        return None if root is None else root / folder
    return local_design_root(project_dir) / folder


def trdd_files(
    folder: str = "tasks", project_dir: str | None = None
) -> list[tuple[str, Path]]:
    """Every `TRDD-*.md` in `folder` across BOTH scopes, as `(scope, path)`.

    This is what a consumer wants 99% of the time: "all the TRDDs on the board",
    regardless of which scope owns them. Sorted within each scope so output is stable.
    """
    out: list[tuple[str, Path]] = []
    for scope, _root in design_roots(project_dir):
        d = scope_folder(scope, folder, project_dir)
        if d is not None and d.is_dir():
            out.extend((scope, p) for p in sorted(d.glob("TRDD-*.md")))
    return out


def ensure_local_design(project_dir: str | None = None) -> Path:
    """Create the LOCAL design root + its four lifecycle folders. Returns the root.

    Only the TRDD-AUTHORING path calls this. Detectors must NOT: a read-only observer
    that materializes the thing it observes would make every project look like it has
    local design, and would write to `~/.claude` on every heartbeat.
    """
    root = local_design_root(project_dir)
    for name in DESIGN_FOLDERS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


# ── Filename id extraction ───────────────────────────────────────────────────
#
# ONE id matcher (TRDD-15ECPBSA consolidated what were briefly two). The modern
# id segment is the full base36 alphabet (UPPER + lower + digits), so an
# UPPERCASE base36 id like `15ECPBSA` is captured verbatim (case preserved). The
# earlier `[0-9a-f]{8}`-only matcher silently DROPPED every uppercase-base36 id
# the current TRDD spec mints, making stale v2 TRDDs invisible to trdd-drift /
# trdd-reminder — so all three TRDD detectors now share this single matcher via
# `extract_uid`.
#   * current spec filename:  TRDD-<YYYYMMDD_HHMMSS±HHMM>-<id8>-<slug>.md
#       → group(1) = the 8-char base36 id (case preserved)
#   * legacy filename:        TRDD-<full-UUID>-<slug>.md
#       → group(2) = the 36-char UUID
# Anchored to exactly 8 id chars + the mandatory `-<slug>.md`, so a stray
# `TRDD-deadbeef.md` (no slug) does NOT match; the timestamp and UUID branches
# are mutually exclusive (a `_` in the timestamp can't appear in a UUID).
_TRDD_ID_RE = re.compile(
    r"^TRDD-"
    r"(?:"
    r"\d{8}_\d{6}[+-]\d{4}-([0-9A-Za-z]{8})"  # current: <timestamp>-<id8 base36>
    r"|([0-9a-fA-F-]{36})"                     # legacy:  <full-uuid>
    r")"
    r"-.+\.md$"
)


def extract_uid(filename: str) -> str | None:
    """Return a TRDD filename's id (UPPERCASE base36 OR legacy UUID), or None.

    This is the SINGLE id matcher every TRDD detector uses. It accepts the
    modern 8-char UPPERCASE base36 id (`A-Z` + `0-9`) the current TRDD spec uses
    AND the legacy lowercase-hex/UUID id, preserving the id's case exactly as
    written so `git log --grep TRDD-<id>` and `git tag --contains` can match it.
    Returns None for a non-TRDD filename.
    """
    m = _TRDD_ID_RE.match(filename)
    if not m:
        return None
    return m.group(1) or m.group(2)


# ── Frontmatter parsing ──────────────────────────────────────────────────────
#
# The canonical TRDD format (~/.claude/rules/trdd-design-tasks.md) puts the task
# state in YAML frontmatter — `status:` (v1) and/or `column:` (v2) — NOT a
# `**Status:**` markdown body line. We parse the frontmatter first and keep the
# legacy `**Status:**` body line as a fallback for pre-frontmatter TRDDs. All
# matches are anchored MULTILINE within the opening `---` block.
FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)
FM_STATUS_RE = re.compile(r"^status:[ \t]*(.+)$", re.MULTILINE)
FM_COLUMN_RE = re.compile(r"^column:[ \t]*(.+)$", re.MULTILINE)
FM_CREATED_RE = re.compile(r"^created:[ \t]*(.+)$", re.MULTILINE)
FM_BLOCKED_BY_RE = re.compile(r"^blocked-by:[ \t]*(.+)$", re.MULTILINE)
FM_IMPL_COMMITS_RE = re.compile(r"^implementation-commits:[ \t]*(.+)$", re.MULTILINE)
# Legacy `**Status:** ...` markdown body line (pre-frontmatter TRDDs only).
LEGACY_STATUS_RE = re.compile(r"^\*\*Status:\*\*[ \t]*(.+)$", re.MULTILINE)

# Read only the head of the file — frontmatter lives at the very top, and a
# legacy `**Status:**` line sits just under the title. 4 KiB covers both
# without slurping a multi-thousand-line TRDD body.
HEAD_BYTES = 4096

# The reconciliation checks need to see the STATE block + checklist prose, which
# can sit well past the first 4 KiB. A larger budget keeps the full STATE head
# (and its NEXT-ACTION / checklist) in view without slurping a huge body.
RECONCILE_BYTES = 24576

# v2 `column:` values that mean "actively in flight". The WIDE set used by
# trdd-drift (any non-terminal column whose git state could have drifted,
# including the parked ENTRY/DESIGN columns). trdd-reminder deliberately uses a
# NARROWER set (only the WORK columns) — it keeps its own local constant.
ACTIVE_COLUMNS = frozenset(
    {"dev", "testing", "backburner", "todo", "dispatch", "ai_review", "human_review"}
)

# v2 `column:` values that mean the TRDD is DONE / closed — a TRDD here has
# already shipped (or been abandoned/replaced), so Check 1 must NOT flag it.
# Superset of the "terminal" columns across all three release-via pipelines plus
# the proposal-stage rejection states (refused/cancelled) from the approval-tier
# rule. `complete` is included: a `complete` TRDD has met its requirements and is
# awaiting ship — re-surfacing it as "shipped but open" would be noise.
TERMINAL_COLUMNS = frozenset(
    {"published", "complete", "live", "failed", "superseded", "cancelled", "refused"}
)

# A blocker is "cleared" when it reaches one of these — a strict subset of
# TERMINAL_COLUMNS: a blocker that `failed`/`refused`/`cancelled` is gone (it is
# not going to land), but the load-bearing case the TRDD calls out is a blocker
# that SHIPPED. We treat any terminal blocker as stale, since none of them will
# ever unblock the dependent by completing.
BLOCKER_CLEARED_COLUMNS = TERMINAL_COLUMNS


def norm_state(value: str) -> str:
    """Normalise a status/column token to lowercase kebab-case.

    Maps the legacy title-case body values (`In progress`, `Not started`) onto
    their frontmatter spellings (`in-progress`, `not-started`) by lowercasing
    and collapsing internal whitespace to a single hyphen, so a single
    membership set covers both formats.
    """
    return "-".join(value.strip().rstrip("\r").lower().split())


def parse_trdd_state(path: Path) -> tuple[str, str]:
    """Return (status, column) for a TRDD, both normalised kebab-case or ''.

    Reads the YAML frontmatter `status:`/`column:` keys (the documented
    location), falling back to a legacy `**Status:**` body line when the
    frontmatter has no `status:`. Returns ('', '') on any read error.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(HEAD_BYTES)
    except (FileNotFoundError, OSError):
        return ("", "")
    return parse_state_text(head)


def parse_state_text(head: str) -> tuple[str, str]:
    """Pure variant of parse_trdd_state over already-read text (the file head)."""
    status = ""
    column = ""
    fm = FRONTMATTER_RE.match(head)
    if fm:
        block = fm.group(1)
        sm = FM_STATUS_RE.search(block)
        if sm:
            status = norm_state(sm.group(1))
        cm = FM_COLUMN_RE.search(block)
        if cm:
            column = norm_state(cm.group(1))

    # Legacy fallback ONLY for a genuine v1 card — i.e. no `status:` key AND no `column:`.
    #
    # The `not column` half is load-bearing (issue #135). LEGACY_STATUS_RE scans the whole
    # head, which includes BODY prose, so on a v2 card whose body happens to contain a
    # `**Status:** …` line — a STATE block, a progress table, a quoted example — this
    # fabricated a v1 status the file does not have. Because the drift gate treats v1 status
    # as authoritative, a `column: complete` card was then reported as
    # `status='not-started'`: a value present nowhere in the file, asserted about a TRDD that
    # §12 forbids editing, so the finding could never be cleared.
    #
    # A card that declares a `column:` IS v2 by construction, and its own column is the only
    # state it has. Body prose must never outrank it.
    if not status and not column:
        lm = LEGACY_STATUS_RE.search(head)
        if lm:
            status = norm_state(lm.group(1))

    return (status, column)


# A UTF-8 BOM, spelled as a code point on purpose. A literal BOM in this source
# would itself be invisible to anyone reading it — precisely the fault the
# function below exists to name. Never replace this with the character itself.
BOM = chr(0xFEFF)


def frontmatter_defect(head: str) -> str | None:
    """Why this TRDD's frontmatter is unreadable, or None when it parses.

    `FRONTMATTER_RE` is `\\A`-anchored, so the YAML block MUST open on byte 0.
    A single line above it — a stray `# title`, a leading blank, a UTF-8 BOM —
    makes EVERY machine field invisible at once: `parse_trdd_state` returns
    ('', ''), so the card silently drops off the board and out of every column
    filter, while `grep '^column:'` still finds the line and reports the file as
    healthy. That divergence is why the defect survives: the greppable view and
    the parsed view disagree, and only the parsed view drives the detectors.

    Learned from TRDD-WEBA1RMF (2026-07-26), authored by hand with its `#` title
    above the frontmatter. Nothing in the pipeline noticed until markdownlint
    reported the closing `---` as an MD003 setext heading and blocked a release
    — an incidental style rule catching a structural fault by luck.
    """
    if FRONTMATTER_RE.match(head):
        return None
    if not head.strip():
        return "file is empty"
    first = head.split("\n", 1)[0].rstrip("\r")
    if first.startswith(BOM):
        return "a UTF-8 BOM precedes the frontmatter"
    if first.strip() == "---":
        return "frontmatter opens on line 1 but never closes"
    return f"frontmatter does not open on line 1 (line 1 is {first[:48]!r})"


def frontmatter_defect_for(path: Path) -> str | None:
    """File-reading wrapper around `frontmatter_defect`. None on a read error.

    A file we cannot read is not evidence of a malformed TRDD, so it stays
    silent here rather than emitting a defect the author cannot act on.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(HEAD_BYTES)
    except (FileNotFoundError, OSError):
        return None
    return frontmatter_defect(head)


# ── TRDD id references in free text ──────────────────────────────────────────
#
# The STATE prose names blocker TRDDs as `TRDD-<id8>` (e.g. "publish BLOCKED on
# TRDD-3b9b2040"). This grabs the bare 8-char id of every such reference so
# Check 4 can ask whether a prose-named blocker is now terminal. Word-boundaried
# so it doesn't bite into a longer token.
_TRDD_REF_RE = re.compile(r"\bTRDD-([0-9A-Za-z]{8})\b")


def extract_trdd_refs(text: str) -> list[str]:
    """Return every `TRDD-<id8>` id referenced in `text` (order-preserving, deduped)."""
    seen: list[str] = []
    for m in _TRDD_REF_RE.finditer(text):
        uid = m.group(1)
        if uid not in seen:
            seen.append(uid)
    return seen


# ── YAML flow-list parsing (blocked-by / implementation-commits) ─────────────

_TRDD_REF_TOKEN_RE = re.compile(r"TRDD-([0-9A-Za-z]{8})")


def parse_flow_list(raw: str) -> list[str]:
    """Parse a YAML flow-style list value into its raw element strings.

    `[a, b, c]` → ['a', 'b', 'c']; `[]` → []; a bare scalar `x` → ['x'].
    Quotes and surrounding whitespace are stripped from each element. This is
    the grep-first flow-list the TRDD frontmatter invariants guarantee (one
    field per line, flow-style lists), so a tiny splitter beats a YAML dep.
    """
    s = raw.strip().rstrip("\r")
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    out: list[str] = []
    for part in s.split(","):
        tok = part.strip().strip("'\"").strip()
        if tok:
            out.append(tok)
    return out


def blocked_by_ids(raw: str) -> list[str]:
    """Extract the blocker TRDD ids from a `blocked-by:` flow-list value.

    Accepts both the `TRDD-<id8>` spelling and a bare id element. Returns the
    8-char ids (case preserved). An empty list value yields [].
    """
    ids: list[str] = []
    for el in parse_flow_list(raw):
        m = _TRDD_REF_TOKEN_RE.search(el)
        if m:
            ids.append(m.group(1))
        elif re.fullmatch(r"[0-9A-Za-z]{8}", el):
            ids.append(el)
    return ids


def impl_commit_shas(raw: str) -> list[str]:
    """Extract commit SHAs from an `implementation-commits:` flow-list value.

    Keeps only hex tokens of length ≥ 7 (short or full SHAs); ignores `null`,
    placeholders, and anything non-hex.
    """
    out: list[str] = []
    for el in parse_flow_list(raw):
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", el):
            out.append(el)
    return out


# ── The parsed record the checks operate on ──────────────────────────────────


@dataclass
class TrddRecord:
    """Everything the four reconciliation checks need, parsed from ONE TRDD.

    Pure data — no I/O. Build via `parse_trdd_record` (reads a file) or
    `parse_record_text` (over already-read text, for unit tests).
    """

    uid: str | None
    column: str
    status: str
    blocked_by: list[str] = field(default_factory=list)
    impl_commits: list[str] = field(default_factory=list)
    # The STATE / body text the prose-based checks scan (Check 2's NEXT-ACTION,
    # Check 3's "blocked" prose, Check 4's prose-named blockers).
    body: str = ""


def parse_record_text(text: str, *, uid: str | None) -> TrddRecord:
    """Build a TrddRecord from a TRDD's text (frontmatter + body head)."""
    status, column = parse_state_text(text)
    blocked_by: list[str] = []
    impl_commits: list[str] = []
    fm = FRONTMATTER_RE.match(text)
    body = text
    if fm:
        block = fm.group(1)
        body = text[fm.end():]
        bm = FM_BLOCKED_BY_RE.search(block)
        if bm:
            blocked_by = blocked_by_ids(bm.group(1))
        im = FM_IMPL_COMMITS_RE.search(block)
        if im:
            impl_commits = impl_commit_shas(im.group(1))
    return TrddRecord(
        uid=uid,
        column=column,
        status=status,
        blocked_by=blocked_by,
        impl_commits=impl_commits,
        body=body,
    )


def parse_trdd_record(path: Path) -> TrddRecord:
    """Read a TRDD file and build its TrddRecord (uses RECONCILE_BYTES head)."""
    uid = extract_uid(path.name)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(RECONCILE_BYTES)
    except (FileNotFoundError, OSError):
        return TrddRecord(uid=uid, column="", status="")
    return parse_record_text(head, uid=uid)


# ── The four checks (all PURE) ───────────────────────────────────────────────


def is_terminal_column(column: str) -> bool:
    """True iff `column` is one of the DONE/closed terminal columns."""
    return column in TERMINAL_COLUMNS


# Markers in a STATE block that say the latest work is DONE/SHIPPED. A ✅ /
# DONE / SHIPPED / COMPLETE marker on the most-recent STATE status line means
# the NEXT-ACTION is satisfied — so it does NOT count as remaining work.
_DONE_MARKER_RE = re.compile(
    r"(✅|\bDONE\b|\bSHIPPED\b|\bCOMPLETE\b|\bCOMPLETED\b|\bPUBLISHED\b)",
    re.IGNORECASE,
)
# An unchecked GitHub-style task box `- [ ]` = remaining in-scope work.
_UNCHECKED_BOX_RE = re.compile(r"^[ \t]*[-*][ \t]+\[ \][ \t]", re.MULTILINE)
# A NEXT-ACTION / NEXT STEP line in the STATE block — its presence means the
# author recorded a concrete remaining step. It only counts as "remaining" when
# it is NOT annotated as done.
_NEXT_ACTION_RE = re.compile(r"^.*\bNEXT[ \t-]*ACTION(S)?\b.*$", re.IGNORECASE | re.MULTILINE)
# Prose that asserts a block the frontmatter may not encode (Check 3).
#
# The word must stand on its own as a CURRENT-STATE declaration — not appear
# spliced into a code identifier, script/file name, or path. The original
# letter-only boundary let `block` leak through whenever a code-token connector
# (`- . / _`) glued it to surrounding alnums: `DECOUPLE-BLOCKED` (a greppable
# code-tag), `amp-task-blocked.sh` (a script name), `done/blocked` (a slashed
# token) all fired a spurious prose-frontmatter-mismatch (issue #65 class b). The
# two extra look-arounds reject "block" when an alnum<connector> precedes it
# (mid-identifier left) or a connector<alnum> follows it (mid-identifier /
# filename right) — while still firing on a real sentence-ending "…is blocked."
# (period followed by space/EOL, NOT connector+alnum). Backtick inline-code is
# masked before matching (see `_mask_inline_code`) so a `code sample` mentioning
# block is ignored too. Verified MUST-fire: "BLOCKED on GROUP B", "blocked by the
# migration", "(blocked)", "is blocked."; MUST-NOT: the three code-token cases
# above + `is_blocked_flag`.
_BLOCKED_PROSE_RE = re.compile(
    r"(?<![A-Za-z])"               # original: not glued to a letter on the left
    r"(?<![A-Za-z0-9][-./])"      # NEW: not <alnum><connector>block… (mid-identifier left)
    r"(blocked(?:[ \t]+on| on| by)?|BLOCKED|hostage[ \t]+to|blocked-on)"
    r"(?![A-Za-z])"               # original: not glued to a letter on the right
    r"(?![-_./][A-Za-z0-9])",     # NEW: not block…<connector><alnum> (mid-identifier / filename right)
    re.IGNORECASE,
)

# Backtick-fenced inline-code span: `like this`. Masked to same-length blanks
# before the blocked-prose scan so a "block" inside a `code sample` (a code
# identifier, not a state declaration) cannot trip Check 3 (issue #65 class b).
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


def _mask_inline_code(text: str) -> str:
    """Replace backtick-fenced inline-code spans with same-length spaces.

    Length-preserving (not deletion) so byte offsets of the surrounding prose are
    unchanged. Used by Check 3 so 'block' appearing inside `inline code` (a code
    token quoted as code, never a live block declaration) is not matched.
    """
    return _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), text)


def check1_shipped_but_open(record: TrddRecord, commit_in_released_tag) -> bool:
    """Check 1 — the keystone. Non-terminal TRDD whose commits are in a released tag.

    `commit_in_released_tag(sha) -> bool` is the injectable membership seam (in
    production: `git tag --contains <sha>` returns ≥1 `v*` tag). The commit set
    is the union of `implementation-commits:` and any SHAs the caller resolved
    by grepping `TRDD-<id8>` in commit subjects (passed in via `record.impl_commits`
    — the detector merges both sources before calling).

    Returns True iff the column is NON-terminal AND at least one of the TRDD's
    commits is contained in a released tag.
    """
    if is_terminal_column(record.column):
        return False
    if not record.impl_commits:
        return False
    return any(commit_in_released_tag(sha) for sha in record.impl_commits)


def check2_has_remaining_work(record: TrddRecord) -> bool:
    """Check 2 — the remaining-work gate that suppresses Check-1 over-claims.

    True iff the TRDD still encodes unfinished in-scope work — ANY of:
      * `column: blocked`;
      * an unchecked `- [ ]` task box in the body;
      * a NEXT-ACTION line whose OWN text carries no DONE/SHIPPED/✅ marker
        (scoped to the line, so a ✅ on a finished SUB-part can't mask a still-
        pending next action).

    This is what separates "closeable candidate" (Check1 & !remaining) from
    "partially shipped, review" (Check1 & remaining) — the exact distinction
    that prevents the audit over-claim the TRDD was written to stop.
    """
    if record.column == "blocked":
        return True
    if _UNCHECKED_BOX_RE.search(record.body):
        return True
    # Scope the done-marker check to the NEXT-ACTION line(s) THEMSELVES, not the
    # whole body: a ✅ on a finished SUB-part (e.g. "g1 ✅ DONE") must not mask a
    # still-pending NEXT-ACTION ("implement the two residuals", a "USER-GATED"
    # item). The real-board smoke test proved the whole-body check mislabeled
    # standing / partly-done TRDDs as closeable (TRDD-15ECPBSA precision fix).
    na_lines = [m.group(0) for m in _NEXT_ACTION_RE.finditer(record.body)]
    if na_lines and not any(_DONE_MARKER_RE.search(ln) for ln in na_lines):
        return True
    return False


def check3_prose_frontmatter_mismatch(record: TrddRecord) -> bool:
    """Check 3 — STATE prose claims a block the machine fields do not encode.

    True iff the body contains blocked/BLOCKED/hostage-to/blocked-on prose, but
    the frontmatter `column != blocked` AND `blocked-by: []` (empty). The human
    prose and the machine state disagree — reconcile one to the other.

    A TERMINAL TRDD is excluded (mirrors Check 4's guard): it is CLOSED, so a
    historical "blocked" mention in its settled STATE is not live board drift.
    The real-board smoke test proved Check 3 was flagging `complete` TRDDs whose
    prose said "blocked on a CPV" (about a long-shipped version) — TRDD-15ECPBSA.
    """
    if is_terminal_column(record.column):
        return False
    if record.column == "blocked":
        return False
    if record.blocked_by:
        return False
    # Mask inline-code before the scan so 'block' inside `code`/code-tags/script
    # names is not read as a live block declaration (issue #65 class b).
    return bool(_BLOCKED_PROSE_RE.search(_mask_inline_code(record.body)))


def check4_stale_blockers(record: TrddRecord, column_of) -> list[str]:
    """Check 4 — blockers (frontmatter OR prose-named) that are now terminal.

    `column_of(uid) -> str` resolves another TRDD's current column (in
    production: parsed from that TRDD's file; '' when unknown). Returns the list
    of blocker ids whose column is now terminal (shipped/cleared) — "blocker
    cleared; re-evaluate / unblock". Only meaningful when the TRDD itself is not
    yet terminal.
    """
    if is_terminal_column(record.column):
        return []
    candidates: list[str] = list(record.blocked_by)
    # Prose-named blockers count only when the TRDD prose actually says blocked
    # (inline-code masked, so a code-tag like `DECOUPLE-BLOCKED` doesn't qualify —
    # issue #65 class b; the same discrimination Check 3 uses).
    if _BLOCKED_PROSE_RE.search(_mask_inline_code(record.body)):
        for uid in extract_trdd_refs(record.body):
            if uid not in candidates and uid != record.uid:
                candidates.append(uid)
    stale: list[str] = []
    for uid in candidates:
        if column_of(uid) in BLOCKER_CLEARED_COLUMNS:
            stale.append(uid)
    return stale


# ── Verdict orchestration ────────────────────────────────────────────────────


@dataclass
class ReconcileVerdict:
    """The reconciliation outcome for ONE TRDD — which checks fired + the label.

    `label` is one of: 'closeable-candidate', 'partially-shipped-review',
    'prose-frontmatter-mismatch', 'stale-blocker', or '' when nothing fired.
    A TRDD can fire multiple checks; `label` is the single most-actionable one,
    but `fired` lists them all and the evidence fields carry the details.
    """

    uid: str | None
    column: str
    label: str
    fired: list[str] = field(default_factory=list)
    shipped: bool = False
    has_remaining: bool = False
    prose_mismatch: bool = False
    stale_blockers: list[str] = field(default_factory=list)
    # Which of the TRDD's commits were found in a released tag (evidence).
    shipped_commits: list[str] = field(default_factory=list)

    @property
    def fires(self) -> bool:
        return bool(self.fired)


def reconcile(record: TrddRecord, commit_in_released_tag, column_of) -> ReconcileVerdict:
    """Run all four checks on one record; return the consolidated verdict.

    `commit_in_released_tag(sha) -> bool` and `column_of(uid) -> str` are the
    two injectable seams (git-backed in production, fakes in tests). The label
    precedence is: shipped+remaining (partially-shipped-review) and
    shipped+clean (closeable-candidate) are the keystone outcomes; the prose
    mismatch and stale-blocker checks are independent signals that also surface.
    """
    # AUTHORITATIVE terminal guard (issue #65 class a): a TRDD in a terminal
    # column (published/complete/live/failed/superseded/cancelled/refused) is
    # DONE — its body is frozen by the TRDD rules and it is NEVER a board-drift
    # candidate. The four checks each carry their own terminal guard, but this
    # single early-return is the SINGLE SOURCE OF TRUTH so a future check added
    # without that guard can't leak a terminal TRDD into the report. Do NOT
    # remove: it is what keeps `published`/`complete` TRDDs (whose settled STATE
    # often mentions a historical block) off the candidate board.
    if is_terminal_column(record.column):
        return ReconcileVerdict(uid=record.uid, column=record.column, label="")

    shipped = check1_shipped_but_open(record, commit_in_released_tag)
    shipped_commits = (
        [sha for sha in record.impl_commits if commit_in_released_tag(sha)]
        if shipped
        else []
    )
    has_remaining = check2_has_remaining_work(record)
    prose_mismatch = check3_prose_frontmatter_mismatch(record)
    stale_blockers = check4_stale_blockers(record, column_of)

    fired: list[str] = []
    if shipped:
        # Check 2 gates the Check-1 verdict: shipped+remaining is a WEAKER
        # "review", shipped+clean is the STRONG "closeable". This is the
        # load-bearing distinction (3b9b2040 / ab232dbd) — never call a
        # still-working TRDD "closeable".
        fired.append("partially-shipped-review" if has_remaining else "closeable-candidate")
    if prose_mismatch:
        fired.append("prose-frontmatter-mismatch")
    if stale_blockers:
        fired.append("stale-blocker")

    label = fired[0] if fired else ""
    return ReconcileVerdict(
        uid=record.uid,
        column=record.column,
        label=label,
        fired=fired,
        shipped=shipped,
        has_remaining=has_remaining,
        prose_mismatch=prose_mismatch,
        stale_blockers=stale_blockers,
        shipped_commits=shipped_commits,
    )
