"""Shared TRDD-parsing helpers + the state-reconciliation checks (stdlib-only).

This module hoists the TRDD frontmatter/filename parsing that was duplicated
inline in `scripts/detectors/trdd-drift.py` and `trdd-reminder.py`, so all the
TRDD detectors share ONE source of truth for "what is a TRDD's column" and "what
is its id". It also implements the FIVE pure checks of the state-reconciliation
detector: the original FOUR (TRDD-15ECPBSA) — each a pure function over a parsed
`TrddRecord` plus an injectable `commit -> {tags}` map — plus Check 5
(TRDD-FDV1RQEB), which flags a STATE block citing a code symbol the tree no
longer has, via an injectable `token -> bool` seam. All are unit-testable with
zero git.

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
# `npt:` (Necessary Prerequisite Tasks) — a card that must finish these BEFORE `dev` is
# legitimately stalled in `backburner`/`todo` on its own dependency chain, not forgotten
# (trdd-drift narrowing, janitor#189: a card with a stated precondition is not "drift").
FM_NPT_RE = re.compile(r"^npt:[ \t]*(.+)$", re.MULTILINE)
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

# The ratified column vocabulary: 14 lifecycle + 3 exception (universal-kanban), plus the
# `proposal`/`planned` intake pair and the terminal archive values that BRACKET the pipeline.
# Any other value in a `column:`/`status:` is NOT a pipeline state.
ALL_COLUMNS = frozenset(
    {
        "backburner", "todo", "design", "dispatch", "dev", "testing", "ai_review",
        "human_review", "complete", "publish", "published", "deploy", "live",
        "live_auditing",
        "blocked", "failed", "superseded",
        "proposal", "planned", "refused", "cancelled", "completed", "archived",
    }
)

# The v1 `status:` spellings of a PIPELINE state, and their v2 column. This map is the ONLY
# licence to read anything out of `status:` (3P-TRDD-09, spec 1.3.0).
V1_PIPELINE_STATUS_TO_COLUMN = {
    "not-started": "todo",
    "in-progress": "dev",
    "completed": "complete",
}


def is_pipeline_state_value(value: str) -> bool:
    """True iff `value` names a PIPELINE state — in either the v1 or the v2 spelling.

    THE PREDICATE EVERY `status:` READER MUST GATE ON (3P-TRDD-09). `status:` is a DISTINCT
    field, not a retired alias of `column:`: v1 spelled the pipeline state in it, v2 moved
    THAT ASPECT to `column:`, and the field itself stayed live for other aspects — the
    3-pillars spec documents carry `status: normative` right now.

    So the residue is a VALUE, never the field NAME. Keying on the name is the shape that
    cost ai-maestro a data-loss bug in `trdd-doctor.ts` (issue #135): it treated `status:`
    itself as retired and marked the rule autofixable, so its fixer deleted the line whatever
    it held, or rewrote it into a `column:` with an invented value when no column was present.
    Nothing was lost only because every live value happened to be a pipeline state.

    Centralised deliberately: their linter and fixer each had their own idea of the vocabulary
    and had already drifted, so the fixer repaired cases the report never mentioned — and the
    report is the only thing a human reviews before `--fix`.
    """
    v = norm_state(value)
    return v in V1_PIPELINE_STATUS_TO_COLUMN or v in ALL_COLUMNS

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


def has_blocked_by_value(head: str) -> bool:
    """True iff the frontmatter declares a NON-EMPTY `blocked-by:`, whatever the elements look like.

    Deliberately NOT `blocked_by_ids`, and the difference is the whole reason this exists: that
    function extracts TRDD-SHAPED ids only, so every non-TRDD blocker this board actually uses —
    `ai-maestro#102`, `publish-of-7ceab3f`, `user-decision-run-the-clear` — parses to an EMPTY
    list and reads as "names no blocker". Measured 2026-08-13: 5 of 9 blocked cards name a
    non-TRDD condition, so any check keyed on the id list fires on a majority of correctly-filled
    cards, which is how a check gets switched off (TRDD-F4IBIDB6).

    A blocker that is not another card is a legitimate, common shape — an upstream issue, a
    pending release, a decision only the user can make. What matters for "is the stall
    EXPLAINED" is that something is named, not that a resolver can chase it.
    """
    fm = FRONTMATTER_RE.match(head)
    if not fm:
        return False
    bm = FM_BLOCKED_BY_RE.search(fm.group(1))
    return bool(bm and parse_flow_list(bm.group(1)))


def has_stated_precondition(head: str) -> bool:
    """True iff `head` declares WHY it is stalled — a non-empty `blocked-by:` or `npt:`.

    trdd-drift narrowing (janitor#189): a `backburner`/`todo` card whose staleness is
    EXPLAINED — it is waiting on another TRDD (`blocked-by:`) or on its own prerequisite
    tasks (`npt:`) — is not "forgotten work", it is correctly parked pending that stated
    condition. A card with neither field populated has no on-file excuse and stays
    drift-eligible: this narrows the false-positive shape (issue #189's 31/32) without
    exempting the whole column, so a genuinely-forgotten backburner card still fires.
    """
    fm = FRONTMATTER_RE.match(head)
    if not fm:
        return False
    block = fm.group(1)
    # ANY non-empty blocked-by value, not just TRDD-shaped ids (see `has_blocked_by_value`):
    # keying on the id list made `blocked-by: [ai-maestro#102]` read as "no on-file excuse" and
    # left a correctly-parked card drift-eligible — the same defect, in the older caller.
    bm = FM_BLOCKED_BY_RE.search(block)
    if bm and parse_flow_list(bm.group(1)):
        return True
    nm = FM_NPT_RE.search(block)
    if nm and parse_flow_list(nm.group(1)):
        return True
    return False


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
    # Whether `blocked-by:` carries ANY element — TRDD-shaped or not (`ai-maestro#102`,
    # `publish-of-7ceab3f`). `blocked_by` above holds only the resolvable TRDD ids, so it is
    # empty for the majority of this board's real blockers; Check 6 needs the raw fact.
    declares_blocker: bool = False


def parse_record_text(text: str, *, uid: str | None) -> TrddRecord:
    """Build a TrddRecord from a TRDD's text (frontmatter + body head)."""
    status, column = parse_state_text(text)
    blocked_by: list[str] = []
    impl_commits: list[str] = []
    declares_blocker = False
    fm = FRONTMATTER_RE.match(text)
    body = text
    if fm:
        block = fm.group(1)
        body = text[fm.end():]
        bm = FM_BLOCKED_BY_RE.search(block)
        if bm:
            blocked_by = blocked_by_ids(bm.group(1))
        declares_blocker = bool(bm and parse_flow_list(bm.group(1)))
        im = FM_IMPL_COMMITS_RE.search(block)
        if im:
            impl_commits = impl_commit_shas(im.group(1))
    return TrddRecord(
        uid=uid,
        column=column,
        status=status,
        blocked_by=blocked_by,
        declares_blocker=declares_blocker,
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

    The length-preserving property is also what lets Check 4 slice the ORIGINAL
    body at offsets computed on the MASKED body (see `_paragraph_spans`).
    """
    return _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), text)


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """`(start, end)` offsets of the blank-line-separated paragraphs in `text`.

    Offsets rather than substrings because the caller matches on the MASKED body
    and extracts ids from the ORIGINAL one; `_mask_inline_code` preserves length,
    so one set of offsets indexes both.
    """
    spans: list[tuple[int, int]] = []
    start: int | None = None
    pos = 0
    for line in text.splitlines(keepends=True):
        if line.strip():
            if start is None:
                start = pos
        elif start is not None:
            spans.append((start, pos))
            start = None
        pos += len(line)
    if start is not None:
        spans.append((start, pos))
    return spans


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
    #
    # ANY-PENDING, not NONE-DONE (TRDD-N7NZOYAK). This was `not any(done)` — i.e.
    # "remaining only if NONE of these lines is done" — so ONE done-marked
    # next-action line masked every still-pending one, which is the same masking
    # the per-line scoping above was added to stop, just one level down. A STATE
    # block that records progress normally carries both shapes at once, so the
    # trigger is ordinary authoring, and the failure direction is the expensive
    # one: nobody re-reads a card the board has labelled closeable.
    na_lines = [m.group(0) for m in _NEXT_ACTION_RE.finditer(record.body)]
    if any(not _DONE_MARKER_RE.search(ln) for ln in na_lines):
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
    #
    # SCOPED TO THE PARAGRAPH, not the whole body (TRDD-FR4NS7I4). The two
    # conditions used to be asked independently of the entire body — "does the
    # prose say blocked ANYWHERE" and "is an id mentioned ANYWHERE" — so on a card
    # that IS legitimately held, every id it cited became one of its blockers.
    # Measured on the live corpus: 52 prose-named candidates -> 23, with the two
    # open held cards going to zero (TRDD-2C8XFOW9 4 -> 0, TRDD-AM8JD9SG 8 -> 0)
    # while the corpus's true positive survives (TRDD-3XS3PDCF -> ab232dbd).
    #
    # A paragraph, NOT a line: that true positive wraps — "stays BLOCKED … see
    # TRDD-xxxx" spans two lines — which is the ordinary shape of a real blocker
    # declaration, so a same-line rule would have dropped the one case the
    # widening exists for.
    masked = _mask_inline_code(record.body)
    if _BLOCKED_PROSE_RE.search(masked):
        spans = _paragraph_spans(masked)
        for i, (lo, hi) in enumerate(spans):
            if not _BLOCKED_PROSE_RE.search(masked[lo:hi]):
                continue
            # Match on the masked slice, read ids from the ORIGINAL one: masking is
            # length-preserving, so the same offsets index both.
            ids_here = [
                uid for uid in extract_trdd_refs(record.body[lo:hi]) if uid != record.uid
            ]
            # ADJACENT-LIST fallback (2026-08-02 review finding): "blocked by the
            # following:" with the ids as a LIST in the NEXT paragraph is an
            # ordinary declaration shape the paragraph scoping dropped entirely.
            # Gated THREE ways so the measured FP wins of the scoping (52→23; the
            # held cards' scattered reuse citations) stay excluded: the blocked
            # paragraph names no ids itself, only the single immediately-following
            # paragraph is read, and — the discriminator — the blocked paragraph
            # must END WITH THE ANNOUNCING COLON. A prose sentence ("BLOCKED on an
            # upstream answer.") ends with a period and never takes the fallback;
            # only a declaration that syntactically promises a list does.
            if not ids_here and masked[lo:hi].rstrip().endswith(":") and i + 1 < len(spans):
                nlo, nhi = spans[i + 1]
                ids_here = [
                    uid
                    for uid in extract_trdd_refs(record.body[nlo:nhi])
                    if uid != record.uid
                ]
            for uid in ids_here:
                if uid not in candidates:
                    candidates.append(uid)
    stale: list[str] = []
    for uid in candidates:
        if column_of(uid) in BLOCKER_CLEARED_COLUMNS:
            stale.append(uid)
    return stale


# ── Check 5 — STATE block cites a symbol the tree no longer has ─────────────
#
# STATE header per trdd-design-tasks.md rule 10: '## ⏵ STATE — READ THIS FIRST
# ON RESUME ...'. The ⏵ is optional in the match (some authored TRDDs predate the
# glyph convention or lose it to encoding) — the load-bearing anchor is
# 'STATE' immediately after a top-level '##' heading.
_STATE_HEADER_RE = re.compile(r"^##[ \t]+\S*[ \t]*STATE\b.*$", re.MULTILINE)
# Any top-level '## ' heading — used to find where the STATE block ENDS (the
# next top-level heading after the STATE header itself, or EOF).
_TOP_HEADING_RE = re.compile(r"^##[ \t]+\S", re.MULTILINE)
# A backtick-fenced token that is EXACTLY identifier-shaped: starts with a
# letter/underscore, then 4+ more letters/digits/underscores (min length 5, per
# the TRDD spec) — no dots, slashes, or spaces, so a file path (`scripts/x.py`)
# or a quoted prose phrase (`the old behavior`) never matches. The backticks
# must wrap the token EXACTLY (no trailing junk) so `foo()` or `foo.bar` are
# rejected outright rather than partially matched.
_BACKTICK_TOKEN_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]{4,})`")

# A deletion verb that, on the SAME LINE as a cited token, means the card is
# RECORDING the death rather than relying on the symbol still existing
# (TRDD-Q4AMWYCY). Deliberately narrow (the exact vocabulary the spec named) —
# widening this risks swallowing a genuine "should be removed" instruction.
_OBITUARY_VERB_RE = re.compile(
    r"\b(?:deleted|removed|retired|gutted|gone)\b|no longer exists?",
    re.IGNORECASE,
)
# A commit SHA (7-40 hex chars) on the token's own line — citing the commit
# that removed a symbol is, by construction, already "done the homework".
_COMMIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)


@dataclass
class DeadSymbolCitation:
    """One backtick-quoted token in a STATE block that the tree no longer has.

    `severity` is `'high'` when the citation sits inside the STATE block's
    NEXT-ACTION paragraph (it blocks the card), `'low'` otherwise (it only
    misleads — e.g. a worked-example illustration).
    """

    token: str
    severity: str


def extract_state_block(body: str) -> str:
    """Return the TRDD's `## ⏵ STATE` block substring of `body`, or `""` if absent.

    Runs from just after the STATE header line to the next top-level `## `
    heading (or EOF) — i.e. the whole STATE section, NEXT-ACTION included.
    """
    m = _STATE_HEADER_RE.search(body)
    if not m:
        return ""
    start = m.end()
    nxt = _TOP_HEADING_RE.search(body, start)
    end = nxt.start() if nxt else len(body)
    return body[start:end]


def _line_span(text: str, pos: int) -> tuple[int, int]:
    """The `(start, end)` offsets of the single line in `text` that contains `pos`.

    `end` excludes the trailing newline (if any) — the line's own text only.
    Used to check a citation for an obituary marker LINE-SCOPED, not
    paragraph-scoped (TRDD-Q4AMWYCY): widening the window to the paragraph
    would silence a genuine stale NEXT ACTION that merely sits near an
    unrelated obituary.
    """
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    return (start, end)


def _is_obituary_line(line: str) -> bool:
    """True iff `line` already RECORDS a deletion rather than citing live code.

    A deletion verb (`deleted`, `removed`, `retired`, `gutted`, `gone`, "no
    longer exists") or a commit SHA (7-40 hex chars) on the token's own line
    means the card has already done the finding's job — repeating "cites an
    absent symbol" is noise, not signal (TRDD-Q4AMWYCY).
    """
    return bool(_OBITUARY_VERB_RE.search(line) or _COMMIT_SHA_RE.search(line))


def _next_action_span(state_block: str) -> tuple[int, int] | None:
    """The paragraph span (within `state_block`) that carries a NEXT-ACTION line.

    Paragraph-scoped (like Check 4's blocker paragraph) so a token cited in the
    SAME paragraph as "NEXT ACTION" — not merely anywhere in the STATE block —
    earns the higher severity. Returns None when the STATE block names no
    NEXT-ACTION line at all.
    """
    m = _NEXT_ACTION_RE.search(state_block)
    if not m:
        return None
    for lo, hi in _paragraph_spans(state_block):
        if lo <= m.start() < hi:
            return (lo, hi)
    return None


def check5_dead_symbol_citations(record: TrddRecord, token_is_dead) -> list[DeadSymbolCitation]:
    """Check 5 — a STATE block cites a code symbol the tree no longer has (TRDD-FDV1RQEB).

    `token_is_dead(token) -> bool` is the injectable git seam (in production: the
    token is ABSENT from `scripts/`+`tests/` at HEAD, AND was found once via
    `git log -S<token>` — i.e. deleted, not a typo or an external name; see the
    detector for the real implementation). Only backtick-quoted, identifier-shaped
    tokens (`[A-Za-z_][A-Za-z0-9_]{4,}` — no dots/slashes/spaces, so a path or a
    prose phrase never qualifies) inside the TRDD's own STATE block are considered;
    a TRDD with no STATE block yields nothing.

    Severity depends on WHERE the token sits (the prototype's refinement, measured
    2026-08-12): a dead symbol inside the STATE block's NEXT-ACTION paragraph
    blocks the card outright (`high`) — a dead symbol elsewhere in the STATE block
    (e.g. a worked-example illustration) only misleads (`low`). A token cited more
    than once takes the HIGHEST severity of any of its occurrences.

    An occurrence whose OWN LINE is an obituary — it already names a deletion
    verb or a commit SHA — is excluded entirely (TRDD-Q4AMWYCY): the card has
    already said the thing this check exists to tell it, so counting that
    occurrence would only produce dismissible noise. This is line-scoped, not
    paragraph-scoped, on purpose: a genuine stale NEXT ACTION a few lines below
    an unrelated obituary must still fire. A token with SOME genuine (non-
    obituary) occurrence still fires normally on those occurrences.

    Returns [] for a terminal TRDD (mirrors every other check's terminal guard) or
    a TRDD whose body carries no STATE block at all.
    """
    if is_terminal_column(record.column):
        return []
    state_block = extract_state_block(record.body)
    if not state_block:
        return []
    na_span = _next_action_span(state_block)

    order: list[str] = []
    in_next_action: dict[str, bool] = {}
    for m in _BACKTICK_TOKEN_RE.finditer(state_block):
        token = m.group(1)
        line_lo, line_hi = _line_span(state_block, m.start())
        if _is_obituary_line(state_block[line_lo:line_hi]):
            continue
        hit_in_na = bool(na_span and na_span[0] <= m.start() < na_span[1])
        if token not in in_next_action:
            order.append(token)
            in_next_action[token] = hit_in_na
        elif hit_in_na:
            in_next_action[token] = True

    findings: list[DeadSymbolCitation] = []
    for token in order:
        if not token_is_dead(token):
            continue
        findings.append(
            DeadSymbolCitation(
                token=token,
                severity="high" if in_next_action[token] else "low",
            )
        )
    return findings


# ── Verdict orchestration ────────────────────────────────────────────────────


@dataclass
class ReconcileVerdict:
    """The reconciliation outcome for ONE TRDD — which checks fired + the label.

    `label` is one of: 'closeable-candidate', 'partially-shipped-review',
    'prose-frontmatter-mismatch', 'stale-blocker', 'blocked-without-blocker', or
    '' when nothing fired. A TRDD can fire multiple checks; `label` is the single
    most-actionable one, but `fired` lists them all and the evidence fields carry
    the details.
    """

    uid: str | None
    column: str
    label: str
    fired: list[str] = field(default_factory=list)
    shipped: bool = False
    has_remaining: bool = False
    prose_mismatch: bool = False
    stale_blockers: list[str] = field(default_factory=list)
    # Check 6: `column: blocked` naming no blocker at all.
    unnamed_blocker: bool = False
    # Which of the TRDD's commits were found in a released tag (evidence).
    shipped_commits: list[str] = field(default_factory=list)

    @property
    def fires(self) -> bool:
        return bool(self.fired)


def check6_blocked_without_blocker(record: TrddRecord) -> bool:
    """Check 6 — `column: blocked` while naming NO blocker (TRDD-F4IBIDB6).

    `blocked` is the board's one licence to sit still, and the pipeline rule states the price of
    it: the claim must be TRUE — a non-empty `blocked-by:` naming something that is itself still
    open. A blocked card that names nothing is indistinguishable from an abandoned one, and it is
    worse than an unstarted card, because the column asserts that the stall is understood.

    Exact, and needs no threshold — which is why it ships ahead of the staleness half of that
    card. Measured on this corpus 2026-08-13: 2 of 9 blocked cards failed it, one of them written
    an hour earlier by the session that then had to notice it by hand.

    Prose is deliberately NOT consulted. Check 3 already reads prose-declared blocks, and a card
    whose BODY explains the hold while its frontmatter stays empty is exactly the case this
    exists to surface: the board is greppable, the prose is not.
    """
    if is_terminal_column(record.column):
        return False
    return norm_state(record.column) == "blocked" and not record.declares_blocker


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
    unnamed_blocker = check6_blocked_without_blocker(record)
    if unnamed_blocker:
        fired.append("blocked-without-blocker")

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
        unnamed_blocker=unnamed_blocker,
    )
