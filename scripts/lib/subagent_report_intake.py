"""Subagent-report intake (TRDD-V57FEWSK): a report that declares open issues becomes a TRDD card.

Owner directive 2026-11-19: "the janitor itself should convert subagents reports into TRDDs, and
nudge the main agent to fix and complete them." `detectors/subagent-report.py` calls `intake_lines`
once per heartbeat; this module holds the logic so the pure parts can be tested without a detector
subprocess (the detector filename has a hyphen and cannot be imported).

Rules, all from the card:
  * Only a report whose LAST line matching `ISSUES: <n>|none` (at line start) has n > 0 makes a card.
    A report without that line, or with `none` / 0, never does.
  * Scanned: `reports/<dir>/**.md` and `reports_dev/<dir>/**.md` (a file directly in `reports/` has no
    agent folder, so it is skipped: the title could not be built from the folder name).
  * The card TITLE is built ONLY from the agent folder name (whitelisted charset) and the leading
    `YYYYMMDD_HHMMSS` of the file name; the BODY holds the project-relative path and the sha256 only.
    `reports_dev/` is private and `design/` is pushed, so no report text may reach a card or its file name.
  * Dedupe key: a `source-report: <path>#<sha256>` line, searched in every design root and in
    proposals/, tasks/ and archived/. Matching is on the PATH: an edited report (new sha) must not
    mint a second card ("one report never makes two cards").
  * Flood control: a watermark (epoch) is written at the first fire and nothing is carded then; later
    only reports with mtime >= watermark are considered, oldest first, at most MAX_CARDS_PER_FIRE
    cards per fire, and the watermark never advances past a report the cap left uncarded.
  * PROJECT scope only (`--design-dir <project design root>` is ALWAYS passed): measured 2026-11-20,
    `trddgrep` without `--design-dir` lists 168 rows and none under `.claude/local`, so a LOCAL card
    would be invisible on the board. Without the flag trddgrep resolves the corpus from the cwd.
"""

from __future__ import annotations

import fcntl
import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import dedupe
import state
import trdd_common
from exe_path import exe

NAME = "subagent-report"
REPORT_ROOTS = ("reports", "reports_dev")
MAX_CARDS_PER_FIRE = 3
# WHY a distinct prefix: `subagent-report` is an advisory detector, so dispatch drops its lines from
# a quiet heartbeat into the findings ledger. This one line is the nudge that keeps an open intake card
# from being forgotten, so dispatch exempts exactly this prefix (`dispatch._INTAKE_NUDGE_PREFIX`, kept
# equal by tests/test_quiet_heartbeat.py). The older `[subagent-report] ` lines stay advisory.
INTAKE_NUDGE_PREFIX = "[subagent-report-intake] "
WATERMARK_FILE = "subagent-report-intake-watermark.txt"
LOCK_FILE = "subagent-report-intake.lock"
# `trddgrep new` refuses a bare name: the author must be `user`, `main-agent@<project-id>` or
# `<agent-name>#<agent-uuid>`. The card asked for author "janitor"; this is the only form of it the
# tool accepts. A fixed uuid5 so every card the janitor mints carries the same identity.
JANITOR_IDENTITY = "janitor#" + str(uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/Emasoft/ai-maestro-janitor"))

# `[ \t]*`, not `\s*`: `\s` also matches a newline, so "ISSUES:\n3" would read the 3 of the NEXT line.
_ISSUES_RE = re.compile(r"^ISSUES:[ \t]*(\d+|none)\b", re.MULTILINE)
_STAMP_RE = re.compile(r"^(\d{8}_\d{6})")
_AGENT_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_.-]")
# A path outside this set (space, `#`, `:`, quote ...) cannot be written into a YAML plain scalar
# unambiguously, so such a report is skipped rather than escaped.
_SAFE_REL_RE = re.compile(r"[A-Za-z0-9_./+-]+")
_KEY_RE = re.compile(r"^source-report:[ \t]*(\S+)#([0-9a-f]{64})[ \t]*$", re.MULTILINE)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_CREATED_RE = re.compile(r"created\s+([A-Z0-9]{8})\b")
_TAIL_BYTES = 65536


@dataclass(frozen=True)
class Report:
    rel: str  # project-relative posix path
    path: Path
    mtime: int
    agent: str  # whitelisted agent folder name
    stamp: str  # YYYYMMDD_HHMMSS from the file name


def parse_issues(text: str) -> int | None:
    """The count on the LAST `ISSUES:` line of `text`; `none` is 0; None when no such line."""
    found = _ISSUES_RE.findall(text)
    if not found:
        return None
    last = found[-1]
    return 0 if last == "none" else int(last)


def card_title(agent: str, stamp: str) -> str:
    return f"Findings of {agent} report {stamp}"


def find_reports(root: Path) -> list[Report]:
    """Every scannable `.md` report under reports/ and reports_dev/, oldest first."""
    out: list[Report] = []
    for base in REPORT_ROOTS:
        top = root / base
        if not top.is_dir():
            continue
        for sub in sorted(top.iterdir()):
            if not sub.is_dir() or sub.is_symlink():
                continue
            agent = _AGENT_UNSAFE_RE.sub("", sub.name)[:40]
            if not agent:
                continue
            for f in sorted(sub.rglob("*.md")):
                # A symlink could point outside the project; a name with no leading timestamp
                # cannot give the title its only other ingredient.
                if f.is_symlink() or not f.is_file():
                    continue
                m = _STAMP_RE.match(f.name)
                if m is None:
                    continue
                rel = f.relative_to(root).as_posix()
                if _SAFE_REL_RE.fullmatch(rel) is None:
                    continue
                mtime = state.file_mtime(f)
                if mtime == 0:
                    continue
                out.append(Report(rel=rel, path=f, mtime=mtime, agent=agent, stamp=m.group(1)))
    out.sort(key=lambda r: (r.mtime, r.rel))
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tail_text(path: Path) -> str:
    """The last _TAIL_BYTES of the file: the ISSUES line is the report's last line."""
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - _TAIL_BYTES))
        return fh.read().decode("utf-8", errors="replace")


def _card_files(root: Path, folders: tuple[str, ...]) -> list[Path]:
    return [p for folder in folders for _scope, p in trdd_common.trdd_files(folder, str(root))]


def existing_source_paths(root: Path) -> set[str]:
    """Report paths that already have a card, in every design root and in archived/ too."""
    known: set[str] = set()
    for p in _card_files(root, ("proposals", "tasks", "archived")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        known.update(m.group(1) for m in _KEY_RE.finditer(text))
    return known


def count_open_intake_cards(root: Path) -> int:
    """Intake cards (carrying `source-report:`) not yet in a terminal column."""
    n = 0
    for p in _card_files(root, ("proposals", "tasks")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _KEY_RE.search(text) is None:
            continue
        _status, column = trdd_common.parse_state_text(text[:4096])
        if not trdd_common.is_terminal_column(column):
            n += 1
    return n


def _read_watermark(f: Path) -> int | None:
    try:
        raw = f.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return int(raw) if raw.isdigit() else None


def _mint(root: Path, design: Path, rep: Report, sha: str) -> bool:
    """Create the card through trddgrep. False (logged) when trddgrep is absent or refuses."""
    key = f"{rep.rel}#{sha}"
    # The body repeats the key on purpose: `new` has no flag for a custom field, so `set` runs after it,
    # and if that second step fails the card must still be found by the dedupe scan next fire.
    body = f"Subagent report declaring open issues.\nsource-report: {key}\n"
    proc = state.run_subprocess(
        [
            exe("trddgrep"), "--design-dir", str(design), "new",
            "--title", card_title(rep.agent, rep.stamp), "--task-type", "bugfix",
            "--author", JANITOR_IDENTITY, "--assignee", JANITOR_IDENTITY,
            "--column", "todo", "--body", body,
        ],
        timeout=30, cwd=root, detector_name=NAME,
    )
    if proc is None or proc.returncode != 0:
        why = "not run" if proc is None else f"exit {proc.returncode}: {_ANSI_RE.sub('', proc.stderr).strip()}"
        state.log_line(NAME, f"intake: trddgrep new failed for {rep.rel}: {why}")
        return False
    m = _CREATED_RE.search(_ANSI_RE.sub("", proc.stdout))
    if m is None:
        state.log_line(NAME, f"intake: trddgrep new printed no card id for {rep.rel}")
        return True  # the card exists and carries the key in its body
    set_proc = state.run_subprocess(
        [exe("trddgrep"), "--design-dir", str(design), "set", m.group(1), "source-report", key, "--no-bump"],
        timeout=30, cwd=root, detector_name=NAME,
    )
    if set_proc is None or set_proc.returncode != 0:
        state.log_line(NAME, f"intake: trddgrep set source-report failed on {m.group(1)}; the body key still dedupes")
    return True


def mint_new_cards(root: Path, now: int) -> tuple[int, bool]:
    """One intake pass. Returns (cards minted, a mint failed). Caller holds no lock; this takes it."""
    tasks = trdd_common.project_tasks_dir(str(root))
    design = trdd_common.project_design_root(str(root))
    if tasks is None or design is None or not tasks.is_dir():
        return 0, False
    sd = state.state_dir()
    wm_file = sd / WATERMARK_FILE
    # The lock is the one-session lease: the read-dedupe-mint-advance sequence must not interleave with
    # another session's fire, or both would pass the dedupe check and mint the same report twice. A
    # fire that finds it held skips; the next fire picks the reports up (the watermark did not move).
    with open(sd / LOCK_FILE, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0, False
        wm = _read_watermark(wm_file)
        if wm is None:
            # First enable (or an unreadable stamp): nothing older than now is carded. Starting from 0
            # would card every report ever written; missing a report is the safe side.
            state.atomic_write(wm_file, str(now))
            return 0, False
        reports = [r for r in find_reports(root) if r.mtime >= wm]
        if not reports:
            return 0, False
        known = existing_source_paths(root)
        minted = 0
        failed = False
        new_wm = wm
        for rep in reports:
            if rep.rel not in known:
                sha = ""
                try:
                    count = parse_issues(_tail_text(rep.path))
                    sha = _sha256(rep.path) if count else sha
                except OSError as exc:
                    state.log_line(NAME, f"intake: cannot read {rep.rel}: {exc!r}")
                    count = None
                if count:
                    if minted >= MAX_CARDS_PER_FIRE:
                        break  # the cap: this report and every later one wait for the next fire
                    if not _mint(root, design, rep, sha):
                        failed = True
                        break
                    known.add(rep.rel)
                    minted += 1
            new_wm = max(new_wm, rep.mtime)
        if new_wm != wm:
            state.atomic_write(wm_file, str(new_wm))
    return minted, failed


def intake_lines(root: Path, now: int, seen: Path) -> list[str]:
    """Run one intake pass and return the heartbeat lines: count-only, no paths, no ids."""
    minted, failed = mint_new_cards(root, now)
    lines: list[str] = []
    if failed:
        line = dedupe.emit_once(
            seen, f"intake-failed@d{now // 86400}",
            f"[subagent-report] a report with open issues could not be turned into a card (see subagent-report.log); {minted} created this fire.",
        )
        if line is not None:
            lines.append(line)
    open_cards = count_open_intake_cards(root)
    if open_cards:
        # One line per day per count: it repeats daily while cards stay open and re-fires when the count moves.
        line = dedupe.emit_once(
            seen, f"intake-open@{open_cards}@d{now // 86400}",
            f"{INTAKE_NUDGE_PREFIX}{open_cards} open card(s) made from subagent reports await a fix or a close.",
        )
        if line is not None:
            lines.append(line)
    return lines
