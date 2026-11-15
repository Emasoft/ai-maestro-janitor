"""Layers 2 and 3 of issue #354: find the secret VALUES of this process environment in files, and files that
have the shape of an environment dump. Nothing in this module returns, prints, logs or stores a value:
a finding carries the variable NAME, the form, the path, the line and a keyed fingerprint.

The needle table lives in memory only. It holds secret values, so a Matcher never shows them in its repr.
The sweep is bounded (bytes and seconds per pass) and incremental (a modification-time cursor), and counts
everything it did not read: silence is not a pass.
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

MIN_LEN = 16
MIN_DISTINCT_CHARS = 8
MAX_FILE_BYTES = 256 * 1024 * 1024  # a larger file is counted, not read (one synthetic measurement, 54 MiB/s: about 5 s alone; TIME_BUDGET_S bounds the pass either way)
MAX_SHAPE_BYTES = 8 * 1024 * 1024
CHUNK_BYTES = 4 * 1024 * 1024
BYTE_BUDGET = 256 * 1024 * 1024  # per pass; one synthetic measurement (54 MiB/s, 120 needles, no hits): text with long repeated prefixes may be slower, TIME_BUDGET_S stops the pass
TIME_BUDGET_S = 60.0  # per pass; the detector timeout is 120 s (CLAUDE_PLUGIN_OPTION_DETECTOR_TIMEOUT)
MAX_FAIL_RETRIES = 3  # passes a failing file holds the cursor before the sweep goes on without it
_ANCHORS = (b"PATH=", b"HOME=", b"SHELL=", b"USER=", b"LOGNAME=", b"TMPDIR=", b"LANG=", b"PWD=", b"TERM=", b"SHLVL=")
_ASSIGNMENT = re.compile(rb"(?<![A-Za-z0-9_])([A-Z][A-Z0-9_]{2,63})=([^\s\x00]{16,})")
_SEPARATORS = re.compile(r"[^\s:|;,&=]+")
_SKIP_DIRS = {".git", "node_modules", "Pods", "DerivedData", "__pycache__"}
Key = tuple[float, str]  # (modification time, path): the order the sweep reads files in


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


def agent_writable_roots(project_root: Path, uid: int, tmp_base: str = "/tmp") -> list[str]:
    """The folders agents write to: reports, reports_dev, every *_dev folder, .janitor, .trashcan of the project,
    and the session scratch folder of Claude Code for this project (/tmp/claude-<uid>/<project path with / as ->),
    which also holds the output files of sub-agents (links to their transcripts)."""
    roots = [project_root / name for name in ("reports", "reports_dev", ".janitor", ".trashcan")]
    roots += [p for p in project_root.glob("*_dev") if p.is_dir()]
    roots.append(Path(tmp_base) / f"claude-{uid}" / str(project_root).replace("/", "-"))
    seen: list[str] = []
    for root in roots:
        if root.exists() and str(root) not in seen:
            seen.append(str(root))
    return seen


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



def _note_unreadable_folder(report: SweepReport, matcher: Matcher | None, folder: str) -> None:
    """os.walk could not list `folder`: count it, unless its own name holds a secret (then it is a secret-named path)."""
    if matcher is not None and (leaked := matcher.name_in(folder)) is not None:
        report.secret_named.append((os.path.dirname(folder), leaked))
    else:
        report.unreadable.append(folder)


def sweep(
    roots: list[str],
    matcher: Matcher | None,
    salt: bytes,
    since: Key = (0.0, ""),
    byte_budget: int = BYTE_BUDGET,
    time_budget_s: float = TIME_BUDGET_S,
    give_up: frozenset[str] = frozenset(),
    clock: Callable[[], float] = time.monotonic,
) -> SweepReport:
    """One bounded pass, oldest change first. Everything it did NOT read is counted in the report.
    A root may be a file (the untracked files of a project are passed one by one) or a folder."""
    report = SweepReport()
    changed: dict[str, tuple[float, int]] = {}
    for root in roots:
        # os.walk skips a folder it cannot list without a word: onerror counts it, so silence is not a pass.
        walker = (
            [(os.path.dirname(root), [], [os.path.basename(root)])]
            if os.path.isfile(root)
            else os.walk(root, onerror=lambda error: _note_unreadable_folder(report, matcher, str(error.filename)))
        )
        for folder, dirs, files in walker:
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for name in files:
                path = os.path.join(folder, name)
                leaked = matcher.name_in(path) if matcher is not None else None
                if leaked is not None:  # decided before any stat: every list below holds paths
                    parent = os.path.dirname(path)
                    while matcher is not None and matcher.name_in(parent):  # the folder name can hold it too
                        parent = os.path.dirname(parent)
                    report.secret_named.append((parent, leaked))
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
    started = clock()
    for index, (mtime, path, size) in enumerate(ordered):
        key = (mtime, path)
        if size > MAX_FILE_BYTES:
            report.too_big.append(path)
            report.processed.append(key)
            continue
        if report.scanned and (report.bytes_read + size > byte_budget or clock() - started > time_budget_s):
            report.left_for_next_pass = len(ordered) - index
            break
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
            report.processed.append(key)
        except OSError:
            report.unreadable.append(path)
            if path in give_up:
                report.processed.append(key)  # failed too often: the cursor goes past it, the report still names it
            else:
                report.failed.append(key)
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
