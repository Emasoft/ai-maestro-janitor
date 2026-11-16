"""Layers 2 and 3 of issue #354: find the secret VALUES of this process environment in files, and files that
have the shape of an environment dump. Nothing in this module returns, prints, logs or stores a value:
a finding carries the variable NAME, the form, the path, the line and a keyed fingerprint.

The needle table lives in memory only. It holds secret values, so a Matcher never shows them in its repr.
The sweep is bounded (bytes and seconds per pass, the listing included) and incremental (a modification-time cursor), and counts
everything it did not read: silence is not a pass.

The timestamp batches of .trashcan are the exception to the modification-time cursor: a file moved into the trash
keeps its old mtime, so the cursor would never see it. sweep_trash scans them by batch name, newest first, from a
saved per-batch position (see its docstring).
"""
from __future__ import annotations

import base64
import collections
import hashlib
import json
import math
import os
import re
import stat
import time
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import secret_names
import trashcan_names

MIN_LEN = 16
MIN_DISTINCT_CHARS = 8
MAX_FILE_BYTES = 256 * 1024 * 1024  # a larger file is counted, not read (one synthetic measurement, 54 MiB/s: about 5 s alone; TIME_BUDGET_S bounds the pass either way)
MAX_SHAPE_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 4 * 1024 * 1024
BYTE_BUDGET = 256 * 1024 * 1024  # per pass; one synthetic measurement (54 MiB/s, 120 needles, no hits): text with long repeated prefixes may be slower, TIME_BUDGET_S stops the pass
TIME_BUDGET_S = 60.0  # per pass; the detector timeout is 120 s (CLAUDE_PLUGIN_OPTION_DETECTOR_TIMEOUT)
# Listing and stat of the roots, per pass, counted inside TIME_BUDGET_S. The listing of the non-trash roots of this repo took
# 8.6 s on 2026-11-16 (28.1 s of walk minus 19.45 s of .trashcan, which is read by name now): 30 s is about 3.5 times that,
# and it leaves at least half of TIME_BUDGET_S for reads.
# The clock is checked once per folder and every LISTING_CLOCK_EVERY_FILES files inside a folder, so a huge flat folder is bounded too.
LISTING_CLOCK_EVERY_FILES = 1024
LISTING_BUDGET_S = 30.0
MAX_FAIL_RETRIES = 3  # passes a failing file holds the cursor before the sweep goes on without it
_ANCHORS = (b"PATH=", b"HOME=", b"SHELL=", b"USER=", b"LOGNAME=", b"TMPDIR=", b"LANG=", b"PWD=", b"TERM=", b"SHLVL=")
_ASSIGNMENT = re.compile(rb"(?<![A-Za-z0-9_])([A-Z][A-Z0-9_]{2,63})=([^\s\x00]{16,})")
_SEPARATORS = re.compile(r"[^\s:|;,&=]+")
_SKIP_DIRS = {".git", "node_modules", "Pods", "DerivedData", "__pycache__"}
Key = tuple[float, str]  # (modification time, path): the order the sweep reads files in
TrashPos = tuple[str, ...]  # path components below a batch folder; tuple order is the walk order of sweep_trash
TRASH_BYTE_BUDGET = 64 * 1024 * 1024  # per pass, on top of BYTE_BUDGET: the trash tier is a backlog of old files, read after the live folders
TRASH_TIME_BUDGET_S = 15.0  # per pass, listing included; the detector timeout is 120 s
TRASH_SETTLE_S = 120  # a batch younger than this may still be receiving files from the safe-delete run that made it


def live_secrets(environ: Mapping[str, str]) -> dict[str, str]:
    """Variables whose NAME says secret and whose VALUE is long and varied enough to be one."""
    found = {}
    for name, value in environ.items():
        if not secret_names.is_secret_env_name(name):
            continue
        if len(value) < MIN_LEN or len(set(value)) < MIN_DISTINCT_CHARS or value.isdigit() or os.path.exists(value):
            continue
        found[name] = value
    return found


def looks_like_token(part: str) -> bool:
    """A random-looking run: long, and either hex or spread over many different characters."""
    if len(part) < 20:
        return False
    if re.fullmatch(r"[0-9a-fA-F]{32,}", part):
        return True
    counts = collections.Counter(part)
    entropy = -sum(c / len(part) * math.log2(c / len(part)) for c in counts.values())
    return entropy >= 4.0


def token_parts(value: str) -> list[str]:
    """The parts of a value that are secret by themselves. In "label:token" the label is not one:
    a partial needle cut from the label matches every place the label is written."""
    return [part for part in _SEPARATORS.findall(value) if looks_like_token(part)]


def variants(value: str) -> dict[bytes, str]:
    """The forms one value takes after a tool has copied it."""
    raw = value.encode()
    forms = {raw: "exact"}
    forms.setdefault(urllib.parse.quote(value, safe="").encode(), "url-quoted")
    forms.setdefault(json.dumps(value)[1:-1].encode(), "json-escaped")
    forms.setdefault(base64.b64encode(raw).rstrip(b"="), "base64")
    forms.setdefault(base64.urlsafe_b64encode(raw).rstrip(b"="), "base64")
    for part in token_parts(value):
        piece = part.encode()
        forms.setdefault(piece, "part")  # the token of "label:token", copied without its label
        if len(piece) >= 40:  # a cut copy: a ps row cut at the screen width, a log prefix
            forms.setdefault(piece[:24], "head")
            forms.setdefault(piece[-24:], "tail")
    return forms


@dataclass(frozen=True)
class Hit:
    name: str  # the variable NAME, never its value
    form: str
    path: str
    line: int
    fingerprint: str  # keyed hash, so two reports of one secret can be joined without the secret


def fingerprint(value: str, salt: bytes) -> str:
    return hashlib.blake2b(value.encode(), key=salt[:64], digest_size=6).hexdigest()


class Matcher:
    """The needles of one environment. Holds secret values: never log it, never store it."""

    def __init__(self, secrets: Mapping[str, str]) -> None:
        self.secrets = dict(secrets)
        self.table: dict[bytes, tuple[str, str]] = {}
        for name, value in self.secrets.items():
            for needle, form in variants(value).items():
                self.table.setdefault(needle, (name, form))
        # Longest first, so at one position the exact value is tried before a head cut from it.
        self.ordered = sorted(self.table, key=len, reverse=True)
        self.keep = max((len(n) for n in self.table), default=1) - 1
        # The forms a file NAME can carry (a cache file named after its token): the value as written, or its token part.
        self.name_needles = [(needle, name) for needle, (name, form) in self.table.items() if form in ("exact", "part")]

    def name_in(self, path: str) -> str | None:
        """The variable whose value (or token part) is written in `path`, or None."""
        raw = os.fsencode(path)
        return next((name for needle, name in self.name_needles if needle in raw), None)

    def __repr__(self) -> str:  # a default repr would print self.secrets
        return f"<Matcher {len(self.table)} needles>"

    __str__ = __repr__


def scan_file(path: str, matcher: Matcher, salt: bytes, chunk: int = CHUNK_BYTES) -> list[Hit]:
    """Reads in chunks with an overlap, so a file of any size is searched and a value on a chunk edge is found.
    One name on one line is one hit, whichever form matched first.

    One bytes.find per needle and chunk, not one regular-expression alternation: measured on 48 MiB of base64-like
    text with 120 needles, the alternation read 1.5 MiB/s because every character can start a branch, while
    bytes.find skips ahead by the needle length.

    The line number of a match is carried forward from the previous match of the same needle. Counting newlines from
    the start of the chunk for every match made a file that holds the value on every line quadratic (2 MiB: 40 s,
    8 MiB: 321 s, past the detector timeout), and the fingerprint is computed once per name, not once per match."""
    fingerprints = {name: fingerprint(value, salt) for name, value in matcher.secrets.items()}
    hits: dict[tuple[str, int], Hit] = {}
    tail, line = b"", 1
    with open(path, "rb") as handle:
        while block := handle.read(chunk):
            data = tail + block
            for needle in matcher.ordered:
                name, form = matcher.table[needle]
                counted_to, row = 0, line
                at = data.find(needle)
                while at != -1:
                    if at + len(needle) > len(tail):  # a match inside the overlap was reported with the chunk before
                        row += data.count(b"\n", counted_to, at)
                        counted_to = at
                        hits.setdefault((name, row), Hit(name, form, path, row, fingerprints[name]))
                    at = data.find(needle, at + 1)
            cut = max(len(data) - matcher.keep, 0)
            line += data.count(b"\n", 0, cut)
            tail = data[cut:]
    return list(hits.values())


def env_dump_names(data: bytes) -> list[str]:
    """Secret-named assignments with a token-like value in text that looks like a whole environment, whatever
    separates the entries (newline for env, NUL for /proc/<pid>/environ, a space for a ps row). This finds a dump
    of ANOTHER process or of an earlier session, whose values the exact matcher cannot know. Report-only."""
    anchors = sum(1 for a in _ANCHORS if re.search(rb"(?<![A-Za-z0-9_])" + re.escape(a), data))
    if anchors < 5:
        return []
    names = set()
    for m in _ASSIGNMENT.finditer(data):
        name = m.group(1).decode()
        if secret_names.is_secret_env_name(name) and token_parts(m.group(2).decode("utf-8", "replace")):
            names.add(name)
    return sorted(names)


# "/tmp" is where Claude Code keeps each session's scratch folder (/tmp/claude-<uid>/<project>); the sweep only READS it,
# it creates no temp file there, so bandit B108 (insecure temp file) does not apply.
def agent_writable_roots(project_root: Path, uid: int, tmp_base: str = "/tmp") -> list[str]:  # nosec B108
    """The folders agents write to: reports, reports_dev, every *_dev folder, .janitor, the non-batch children of
    .trashcan, and the session scratch folder of Claude Code for this project (/tmp/claude-<uid>/<project path with /
    as ->), which also holds the output files of sub-agents (links to their transcripts).

    The timestamp batch folders of .trashcan are NOT roots: sweep_trash scans them by batch name. Blind spot that
    remains: a file moved into one of the non-batch children (migrate-memory-scope/ ...) keeps its old modification
    time, so the cursor of the modification-time sweep never sees it."""
    roots = [project_root / name for name in ("reports", "reports_dev", ".janitor")]
    roots += _trash_non_batch_roots(project_root / ".trashcan")
    roots += [p for p in project_root.glob("*_dev") if p.is_dir()]
    roots.append(Path(tmp_base) / f"claude-{uid}" / str(project_root).replace("/", "-"))
    seen: list[str] = []
    for root in roots:
        if root.exists() and str(root) not in seen:
            seen.append(str(root))
    return seen


def _trash_non_batch_roots(trash: Path) -> list[Path]:
    """The children of .trashcan that are NOT timestamp batch folders (README.txt, .gitkeep, the "<batch>.txt"
    manifests, migrate-memory-scope/ ...): they stay in the modification-time sweep. The batch folders are scanned
    by name in sweep_trash instead (the 950,000 files of 26 batches were 69 percent of the walk). A child that is a link to
    a folder is left out too: os.walk would descend into what it points at, while it lists a link without descending.
    A dangling link or a FIFO child is still a root, and the sweep reports it as an unreadable folder (before, as an
    unreadable or not-regular file): still counted, only labelled differently."""
    if not trash.is_dir():
        return []
    try:
        children = sorted(trash.iterdir())
    except OSError:
        return [trash]  # the sweep counts a folder it cannot list: not silent
    return [c for c in children if not (c.is_dir() and (c.is_symlink() or trashcan_names.batch_epoch(c.name) is not None))]


@dataclass
class SweepReport:
    hits: list[Hit] = field(default_factory=list)
    dump_shaped: list[tuple[str, list[str]]] = field(default_factory=list)
    scanned: int = 0
    bytes_read: int = 0
    unreadable: list[str] = field(default_factory=list)
    not_regular: list[str] = field(default_factory=list)  # FIFOs, sockets, devices: open() can wait for ever or never reach EOF
    # (folder, NAME) of a file whose PATH holds a secret. Such a path may not be printed, logged or kept in the cursor
    # file, and the cursor, the retry counts and the give-up list all key on paths, so the file is left out of the pass
    # whole (its content is not read) and reported by its folder; the finding is the name leak itself.
    secret_named: list[tuple[str, str]] = field(default_factory=list)
    too_big: list[str] = field(default_factory=list)
    shape_not_checked: list[str] = field(default_factory=list)
    left_for_next_pass: int = 0
    processed: list[Key] = field(default_factory=list)  # keys read this pass, in order
    failed: list[Key] = field(default_factory=list)  # keys that raised OSError
    # Seconds the listing had run when LISTING_BUDGET_S stopped it; None = the listing completed. A cut pass read nothing.
    listing_cut_after_s: float | None = None

    def absorb_findings(self, other: SweepReport) -> None:
        """Add what `other` found and could not cover, so one report feeds the detector's loops. NOT processed, failed,
        the counters or left_for_next_pass: those are keyed per tier (a cursor key here, a batch position there)."""
        self.hits += other.hits
        self.dump_shaped += other.dump_shaped
        self.unreadable += other.unreadable
        self.not_regular += other.not_regular
        self.secret_named += other.secret_named
        self.too_big += other.too_big
        self.shape_not_checked += other.shape_not_checked


@dataclass
class TrashReport(SweepReport):
    """The trash tier of one pass. `processed`/`failed` stay empty: positions are per batch, not (mtime, path) keys;
    `left_for_next_pass` counts the settled batches not finished (the one cut included)."""

    present: list[str] = field(default_factory=list)  # every batch folder on disk, settled or not
    exhausted: list[str] = field(default_factory=list)  # walked to the end this pass with no read failing and every folder listed
    processed_by_batch: dict[str, list[TrashPos]] = field(default_factory=dict)  # in walk order
    failed_by_batch: dict[str, list[TrashPos]] = field(default_factory=dict)


def _note_unreadable_folder(report: SweepReport, matcher: Matcher | None, folder: str) -> None:
    """os.walk could not list `folder`: count it, unless its own name holds a secret (then it is a secret-named path)."""
    if matcher is not None and (leaked := matcher.name_in(folder)) is not None:
        report.secret_named.append((os.path.dirname(folder), leaked))
    else:
        report.unreadable.append(folder)


def _note_secret_named(report: SweepReport, matcher: Matcher, path: str, leaked: str) -> None:
    """`path` (a file or a folder) holds a secret in its name: report it by the nearest folder above it whose own
    name is clean, never by the path."""
    parent = os.path.dirname(path)
    while matcher.name_in(parent):  # the folder name can hold it too
        parent = os.path.dirname(parent)
    report.secret_named.append((parent, leaked))


def _read_one(report: SweepReport, matcher: Matcher | None, salt: bytes, path: str, size: int, give_up: frozenset[str]) -> bool:
    """Reads one regular file: the exact matcher, then the dump-shape test, and the counters. Shared by the
    modification-time sweep and the trash tier, so the two cannot read differently. True when the file is done with
    (read, too big to read, or failing too often: `give_up`), False when its read failed and it must be retried."""
    if size > MAX_FILE_BYTES:
        report.too_big.append(path)
        return True
    try:
        if matcher is not None and matcher.table:
            report.hits += scan_file(path, matcher, salt)
        if size <= MAX_SHAPE_BYTES:
            with open(path, "rb") as handle:
                names = env_dump_names(handle.read())
            if names:
                report.dump_shaped.append((path, names))
        else:
            report.shape_not_checked.append(path)
        report.scanned += 1
        report.bytes_read += size
        return True
    except OSError:
        report.unreadable.append(path)
        return path in give_up  # failed too often: the position goes past it, the report still names it


def sweep(
    roots: list[str],
    matcher: Matcher | None,
    salt: bytes,
    since: Key = (0.0, ""),
    byte_budget: int = BYTE_BUDGET,
    time_budget_s: float = TIME_BUDGET_S,
    give_up: frozenset[str] = frozenset(),
    clock: Callable[[], float] = time.monotonic,
    listing_budget_s: float = LISTING_BUDGET_S,
) -> SweepReport:
    """One bounded pass, oldest change first. Everything it did NOT read is counted in the report.
    A root may be a file (the untracked files of a project are passed one by one) or a folder.
    The clock starts before the listing, so time_budget_s covers listing and reads; a listing over listing_budget_s
    is cut (listing_cut_after_s) and nothing is read."""
    report = SweepReport()
    changed: dict[str, tuple[float, int]] = {}
    started = clock()  # before the listing: the read phase gets only what the listing left of time_budget_s
    listed = 0

    def listing_cut() -> bool:
        # An mtime cursor may move only over a COMPLETE listing: a file not yet listed may hold any mtime above the
        # cursor, so advancing it after a cut listing would skip that file for good. Cut means read nothing.
        elapsed = clock() - started
        if elapsed <= listing_budget_s:
            return False
        report.listing_cut_after_s = elapsed
        return True
    for root in roots:
        # os.walk skips a folder it cannot list without a word: onerror counts it, so silence is not a pass.
        walker = (
            [(os.path.dirname(root), [], [os.path.basename(root)])]
            if os.path.isfile(root)
            else os.walk(root, onerror=lambda error: _note_unreadable_folder(report, matcher, str(error.filename)))
        )
        for folder, dirs, files in walker:
            if listing_cut():
                return report
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for name in files:
                listed += 1
                if listed % LISTING_CLOCK_EVERY_FILES == 0 and listing_cut():
                    return report
                path = os.path.join(folder, name)
                if matcher is not None and (leaked := matcher.name_in(path)) is not None:  # decided before any stat: every list below holds paths
                    _note_secret_named(report, matcher, path, leaked)
                    continue
                try:
                    info = os.stat(path)  # follows a link: an agent output file is a link to its transcript
                except OSError:
                    report.unreadable.append(path)
                    continue
                if not stat.S_ISREG(info.st_mode):  # a link to a file passes (stat follows it); a FIFO or a device does not
                    report.not_regular.append(path)
                    continue
                if (info.st_mtime, path) > since:
                    changed[path] = (info.st_mtime, info.st_size)
    ordered = sorted((mtime, path, size) for path, (mtime, size) in changed.items())
    for index, (mtime, path, size) in enumerate(ordered):
        if size <= MAX_FILE_BYTES and report.scanned and (report.bytes_read + size > byte_budget or clock() - started > time_budget_s):
            report.left_for_next_pass = len(ordered) - index
            break
        done = _read_one(report, matcher, salt, path, size, give_up)
        (report.processed if done else report.failed).append((mtime, path))
    return report


def advance_cursor(since: Key, processed: list[Key], holds: list[Key]) -> Key:
    """Where the next pass starts: after the last key read, but never past the first key in `holds`
    (a file that could not be read, or whose finding could not be raised): that one is retried."""
    first_hold = min(holds) if holds else None
    cursor = since
    for key in sorted(processed):
        if first_hold is not None and key >= first_hold:
            break
        cursor = key
    return cursor


def trash_path(trash_root: str, batch: str, position: TrashPos) -> str:
    return os.path.join(trash_root, batch, *position)


def sweep_trash(
    trash_root: str,
    matcher: Matcher | None,
    salt: bytes,
    positions: Mapping[str, TrashPos],
    done: frozenset[str],
    now_epoch: int,
    byte_budget: int = TRASH_BYTE_BUDGET,
    time_budget_s: float = TRASH_TIME_BUDGET_S,
    settle_s: int = TRASH_SETTLE_S,
    give_up: frozenset[str] = frozenset(),
    clock: Callable[[], float] = time.monotonic,
) -> TrashReport:
    """The timestamp batches of .trashcan, scanned by batch NAME, never by modification time: safe-delete moves a file
    in with its old mtime, so no mtime cursor ever sees an arrival. A batch is written once (one safe-delete run)
    and is not rewritten, so a position inside it stays sound; a restore moves files OUT, which only shrinks it.

    Batches: settled ones only (name older than `settle_s`: a run still moving files into its batch is left alone),
    not already in `done`, newest first. Each unfinished batch has its own saved position, so a newer batch that
    arrives mid-scan is read first and the older one keeps its place.

    Walk: recursive, sorted os.scandir, files and folders interleaved by name, so a position is a tuple of path
    components and the tuple order IS the walk order. Joined strings are NOT: "a-b" sorts before "a/x" as a name
    ("a" < "a-b") but after it as a string ("-" < "/"), and a joined-string compare would skip a file. Resume is by
    PRUNING: at each level the entries before the saved component are skipped without a stat and only the saved
    path is descended, so a batch of 100,000 files is not listed again to find where it stopped.

    The clock starts before the first listing, and either budget stops the walk wherever it is. A secret-named
    file or folder is never read, never descended into and never stored (a position only holds a path that was read),
    and is reported by its folder, as in sweep(). Known gap: a file moved by hand into a batch that is already in
    `done` (or behind the saved position) is not read."""
    report = TrashReport()
    started = clock()
    if not os.path.isdir(trash_root):
        return report
    batches: list[tuple[int, str]] = []
    try:
        with os.scandir(trash_root) as scan:
            for entry in scan:
                epoch = trashcan_names.batch_epoch(entry.name)
                if epoch is None or not entry.is_dir(follow_symlinks=False):
                    continue
                report.present.append(entry.name)
                if now_epoch - epoch >= settle_s and entry.name not in done:
                    batches.append((epoch, entry.name))
    except OSError:
        _note_unreadable_folder(report, matcher, trash_root)
        return report
    report.present.sort()
    batches.sort(reverse=True)  # newest first

    def over(size: int) -> bool:
        # At least one file is read per pass (report.scanned), so a pass always moves the positions forward.
        return report.scanned > 0 and (report.bytes_read + size > byte_budget or clock() - started > time_budget_s)

    listing_failed = False

    def walk(folder: str, after: TrashPos, prefix: TrashPos, batch: str) -> bool:
        """True when a budget stopped the walk inside this folder. `after` is the saved position below `folder`."""
        nonlocal listing_failed
        try:
            with os.scandir(folder) as scan:
                entries = sorted(scan, key=lambda entry: entry.name)
        except OSError:
            _note_unreadable_folder(report, matcher, folder)
            listing_failed = True
            return False
        for entry in entries:
            name = entry.name
            if after and name < after[0]:
                continue  # read in an earlier pass
            resumed = bool(after) and name == after[0]
            path = entry.path
            if matcher is not None and (leaked := matcher.name_in(path)) is not None:
                _note_secret_named(report, matcher, path, leaked)
                continue
            here = (*prefix, name)
            if entry.is_dir(follow_symlinks=False):
                if over(0) or walk(path, after[1:] if resumed else (), here, batch):
                    return True
                continue
            if resumed and len(after) == 1:
                continue  # the saved position itself: already read
            if entry.is_dir():
                continue  # a link to a folder: os.walk lists it without descending, and so does the mtime sweep
            try:
                info = os.stat(path)  # follows a link, as in sweep()
            except OSError:
                report.unreadable.append(path)
                continue
            if not stat.S_ISREG(info.st_mode):
                report.not_regular.append(path)
                continue
            if info.st_size <= MAX_FILE_BYTES and over(info.st_size):
                return True
            target = report.processed_by_batch if _read_one(report, matcher, salt, path, info.st_size, give_up) else report.failed_by_batch
            target.setdefault(batch, []).append(here)
        return False

    for index, (_, batch) in enumerate(batches):
        listing_failed = False
        if walk(os.path.join(trash_root, batch), tuple(positions.get(batch, ())), (), batch):
            report.left_for_next_pass = len(batches) - index
            break
        # A batch whose folder could not be listed is not finished: it is walked again, and counted again, next pass.
        if batch not in report.failed_by_batch and not listing_failed:
            report.exhausted.append(batch)
    return report


def advance_trash(
    positions: Mapping[str, TrashPos],
    processed_by_batch: Mapping[str, list[TrashPos]],
    holds_by_batch: Mapping[str, list[TrashPos]],
) -> dict[str, TrashPos]:
    """Where each batch resumes: after the last path read this pass, but never past the first path in `holds_by_batch`
    (a file that could not be read, or whose finding could not be raised): that one is read again. Same rule as
    advance_cursor, per batch, on component tuples."""
    out = dict(positions)
    for batch, processed in processed_by_batch.items():
        holds = holds_by_batch.get(batch)
        first_hold = min(holds) if holds else None
        position = out.get(batch)
        for key in sorted(processed):
            if first_hold is not None and key >= first_hold:
                break
            position = key
        if position is not None:
            out[batch] = position
    return out
