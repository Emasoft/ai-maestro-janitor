# USER-MEMORY subsystem core (TRDD-4334aad0) — a PRIVATE, agent-invisible
# user-authored memory store, sibling of the agent memory corpus.
#
# Imported by the janitor's user-mem hooks (not invoked as a script), so no
# PEP 723 metadata block. Stdlib-only at runtime; the search shells out to the
# already-built `memgrep find` engine (the +/- DSL, wildcards, phrases, and the
# --use-index flag all live in the Rust crate — this module never reimplements
# them, it only builds the argv and parses the result lines).
#
# Privacy is enforced at the HOOK layer (the prompt is erased from agent context
# via UserPromptSubmit `decision:block`; results reach the user only via
# `systemMessage`). This module is the storage + numbering + routing engine and
# holds NO agent-facing surface of its own — nothing here ever prints to a
# channel the model reads.

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import fcntl  # POSIX only (macOS + linux — the declared runtime targets)
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

# --- path resolution -------------------------------------------------------
#
# User memories live in their OWN subfolder, a sibling of the agent corpus:
#   $HOME/.claude/projects/<project-slug>/memory/user-mem/
# where <project-slug> is the absolute project path with every "/" replaced by
# "-" (the harness per-project memory-dir convention). Keeping user-mem a
# sibling of (not mixed into) the agent notes is the storage half of the
# privacy contract: the librarian that curates the agent corpus never walks
# into user-mem, and a user-mem search root is ONLY ever this dir.


def _project_slug(project_dir: str) -> str:
    """Harness per-project slug: the absolute path with every separator dashed.

    Mirrors the directory the harness already creates under
    ~/.claude/projects/. A leading separator yields a leading dash, exactly as
    the harness does (so the slug matches the real on-disk directory name).
    """
    # Normalise but do NOT resolve symlinks — the harness keys on the literal
    # path it was launched with, and resolving could diverge from that.
    p = project_dir.replace(os.sep, "-")
    if os.altsep:
        p = p.replace(os.altsep, "-")
    return p


def resolve_user_mem_dir(project_dir: Optional[str] = None) -> Path:
    """Return the user-mem store dir for a project (does not create it).

    `project_dir` defaults to $CLAUDE_PROJECT_DIR. $HOME anchors the harness
    projects tree. The returned path is `<home>/.claude/projects/<slug>/memory/
    user-mem`.
    """
    proj = (project_dir or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).strip()
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    slug = _project_slug(proj)
    return home / ".claude" / "projects" / slug / "memory" / "user-mem"


# --- atomic helpers --------------------------------------------------------


def _atomic_write(target: Path, value: str) -> None:
    """Atomic-by-rename write (tmp + os.replace), so a concurrent reader/another
    session never sees a half-written file. PID-tagged tmp name avoids two
    writers colliding on the temp path."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(value, encoding="utf-8")
    os.replace(tmp, target)


_FM_NUMBER_RE = re.compile(r"^number:\s*(\d+)\s*$", re.MULTILINE)
_FM_SPLIT_RE = re.compile(r"^---\s*$", re.MULTILINE)


def _parse_number_from_text(text: str) -> Optional[int]:
    """Recover the immutable number from a memory file's frontmatter."""
    m = _FM_NUMBER_RE.search(text)
    return int(m.group(1)) if m else None


def _body_from_text(text: str) -> str:
    """Strip the leading `--- … ---` frontmatter block and return the body verbatim.

    The body is stored exactly as the user gave it (a trailing newline added on
    save is removed here so read() round-trips the original text). When no
    frontmatter is present the whole text is the body.
    """
    if text.startswith("---"):
        parts = _FM_SPLIT_RE.split(text, maxsplit=2)
        # parts: ['', '<frontmatter>', '<body>'] when a closing --- exists.
        if len(parts) == 3:
            body = parts[2]
            # The save() format puts exactly one newline after the closing ---
            # before the body; strip a single leading newline + a single
            # trailing newline to recover the user's text byte-for-byte.
            if body.startswith("\n"):
                body = body[1:]
            if body.endswith("\n"):
                body = body[:-1]
            return body
    return text


# --- a single search result ------------------------------------------------


@dataclass(frozen=True)
class SearchResult:
    """One memgrep hit, annotated with the memory's immutable number."""

    number: int
    summary: str
    path: Path


# --- the store -------------------------------------------------------------


class UserMemStore:
    """The on-disk user-memory store: one markdown file per memory + a monotonic,
    never-reused counter.

    NUMBERING INVARIANT (mirrors the PRRD rule-number invariant): the counter
    only ever moves FORWARD. A `.counter` file holds the highest number ever
    assigned; `save()` reads it, increments, writes it back atomically, then
    writes the memory file. `delete()` removes the file but NEVER rewinds the
    counter — a number, once assigned, belongs to that memory forever; deleting
    retires it, never recycles it. This holds across processes (the counter is
    on disk, not in memory) and even when every memory has been deleted.
    """

    COUNTER_NAME = ".counter"
    LOCK_NAME = ".counter.lock"

    def __init__(self, store_dir: Path) -> None:
        self.dir = Path(store_dir)

    # -- counter --

    @property
    def _counter_path(self) -> Path:
        return self.dir / self.COUNTER_NAME

    @property
    def _lock_path(self) -> Path:
        return self.dir / self.LOCK_NAME

    def _read_counter(self) -> int:
        try:
            raw = self._counter_path.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError):
            return 0
        try:
            v = int(raw)
        except ValueError:
            return 0
        return v if v >= 0 else 0

    def _next_number(self) -> int:
        """Atomically claim the next number: counter+1, persisted before use.

        The read-increment-write is wrapped in an EXCLUSIVE cross-process flock
        so two sessions saving at the same instant can never both claim the same
        number (which would otherwise let one overwrite the other's file and
        break the immutable-numbering invariant). The lock makes the increment
        atomic across processes — the same single-writer discipline the daemon
        uses for its own state.

        Persisting BEFORE writing the memory file guarantees the monotonic
        invariant survives a crash between the two writes — worst case a number
        is burned (retired with no file), which is exactly the never-reuse
        behaviour we want, never a reused number.
        """
        self.dir.mkdir(parents=True, exist_ok=True)
        # `fcntl is None` (not a separate bool) so the type-checker NARROWS fcntl
        # to a real module for the rest of the function — a `_HAVE_FCNTL` flag
        # left pyright seeing `module | None` at every flock call below.
        if fcntl is None:  # pragma: no cover - non-POSIX fallback (best-effort)
            n = self._read_counter() + 1
            _atomic_write(self._counter_path, str(n))
            return n
        # Open (create) the lock file and hold an exclusive lock for the whole
        # read-modify-write. The lock fd is separate from the counter file so the
        # atomic rename of the counter never invalidates the held lock.
        fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            n = self._read_counter() + 1
            _atomic_write(self._counter_path, str(n))
            return n
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - defensive
                pass
            os.close(fd)

    # -- file naming --

    def path_for(self, number: int) -> Path:
        """The canonical file path for a memory number (zero-padded, sortable)."""
        return self.dir / f"{number:06d}.md"

    # -- save --

    def save(self, text: str) -> int:
        """Persist `text` as a new memory; return its immutable number.

        Raises ValueError on empty/whitespace-only text (no empty memories —
        fail-fast). The number is claimed first (counter advanced), then the
        file is written atomically with the number in frontmatter so a listing
        can always recover it even if the filename scheme changes.
        """
        if not text or not text.strip():
            raise ValueError("refusing to save an empty user memory")
        self.dir.mkdir(parents=True, exist_ok=True)
        n = self._next_number()
        # ISO-ish created stamp in frontmatter for the user's own reference; the
        # body is the user's text verbatim. node_type marks it as user-private
        # so any future tool can tell it apart from agent notes at a glance.
        frontmatter = f"---\nnumber: {n}\nnode_type: user-memory\n---\n"
        _atomic_write(self.path_for(n), frontmatter + text + "\n")
        return n

    # -- read --

    def read(self, number: int) -> Optional[str]:
        """Return memory #number's body text, or None if it was never assigned /
        has been deleted. The frontmatter is stripped; the body round-trips the
        original text byte-for-byte."""
        path = self.path_for(number)
        try:
            text = path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return None
        return _body_from_text(text)

    # -- delete --

    def delete(self, number: int) -> bool:
        """Remove memory #number's file. Returns True if a file was removed.

        Does NOT touch the counter — the number is retired, never recycled.
        """
        path = self.path_for(number)
        try:
            path.unlink()
            return True
        except (FileNotFoundError, OSError):
            return False

    # -- search --

    def search(self, query: str, *, memgrep: Optional[str] = None, top: int = 50) -> list[SearchResult]:
        """Run `memgrep find <query> <this-dir> --use-index` and return numbered hits.

        Scoped to THIS store dir only (never the agent corpus). Each hit line is
        `<abs-path> — <summary>`; we read the file's frontmatter to recover the
        immutable number. Results lacking a resolvable number (e.g. a stray
        non-memory file) are skipped rather than mis-numbered. On any memgrep
        failure (binary missing, non-zero exit with no hits) an empty list is
        returned — search degrades, never crashes the caller.
        """
        if not self.dir.is_dir():
            return []
        argv = build_search_argv(query, self.dir, memgrep=memgrep, top=top)
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return []
        return self._parse_search_output(proc.stdout)

    def _parse_search_output(self, stdout: str) -> list[SearchResult]:
        results: list[SearchResult] = []
        for line in stdout.splitlines():
            line = line.rstrip("\n")
            if not line.strip():
                continue
            # memgrep find prints `<path> — <summary>` (em-dash, spaced). Split
            # on the FIRST em-dash so a summary containing an em-dash is kept.
            path_part, summary = _split_hit_line(line)
            if path_part is None:
                continue
            p = Path(path_part)
            number = self._number_for_path(p)
            if number is None:
                continue
            results.append(SearchResult(number=number, summary=summary, path=p))
        return results

    def _number_for_path(self, path: Path) -> Optional[int]:
        # Prefer the frontmatter number (authoritative); fall back to the
        # filename stem when the file can't be read for some reason.
        try:
            text = path.read_text(encoding="utf-8")
            n = _parse_number_from_text(text)
            if n is not None:
                return n
        except (FileNotFoundError, OSError):
            pass
        stem = path.stem
        return int(stem) if stem.isdigit() else None


_EM_DASH = "—"


def _split_hit_line(line: str) -> tuple[Optional[str], str]:
    """Split a memgrep find hit `<path> — <summary>` into (path, summary).

    Returns (None, "") when the line has no em-dash separator (defensive: an
    unexpected line shape is skipped rather than mis-parsed).
    """
    sep = f" {_EM_DASH} "
    idx = line.find(sep)
    if idx < 0:
        # Some terminals/locales may collapse the spacing; try the bare em-dash.
        idx = line.find(_EM_DASH)
        if idx < 0:
            return None, ""
        return line[:idx].strip(), line[idx + len(_EM_DASH):].strip()
    return line[:idx].strip(), line[idx + len(sep):].strip()


# --- argv builder (kept module-level so a hook/test can assert routing) -----


def build_search_argv(query: str, store_dir: Path, *, memgrep: Optional[str] = None, top: int = 50) -> list[str]:
    """Build the `memgrep find <query> <store_dir> --use-index --top <top>` argv.

    The whole `query` is passed as ONE argv element so memgrep's own parser
    handles the +/- operators, wildcards and quoted phrases (we do NOT split or
    pre-interpret it — the DSL lives entirely in the Rust crate). `store_dir` is
    the SOLE search root, which is what scopes the search to user-mem only.
    """
    binary = memgrep or os.environ.get("MEMGREP_BIN") or "memgrep"
    return [binary, "find", query, str(store_dir), "--use-index", "--top", str(top)]


# --- transcript: recover the previous user message (bare /to-user-mem) ------


# Slash form → canonical command id. The PRIMARY names are the
# `/janitor-memory-user-*` family; the three `/…-user-mem` forms are LEGACY
# aliases kept (deprecated) for one reason only: privacy. The UserPromptSubmit
# hook BLOCKS (erases) these prompts before the model sees them — an
# UNRECOGNISED command form is NOT blocked, so dropping the old names would leak
# a user who still types them. Every form maps to the same canonical id, so the
# hook dispatch keys on "add"/"search"/"share" regardless of which name was used.
_COMMAND_ALIASES: dict[str, str] = {
    "/janitor-memory-user-add": "add",
    "/janitor-memory-user-search": "search",
    "/janitor-memory-user-share": "share",
    "/to-user-mem": "add",  # legacy alias (deprecated) — kept blocked, never leaks
    "/search-user-mem": "search",  # legacy alias (deprecated)
    "/share-user-mem": "share",  # legacy alias (deprecated)
}

# Every slash form we recognise (new + legacy). Used by previous_user_message to
# skip our own command lines so a bare /…-add never files the command itself.
_COMMAND_PREFIXES = tuple(_COMMAND_ALIASES)


def _content_to_text(content: object) -> str:
    """Flatten a transcript message `content` (str OR list of blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                # text blocks carry {"type":"text","text":...}; ignore tool/image blocks.
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def previous_user_message(transcript_path: Path | str) -> Optional[str]:
    """Return the text of the user message immediately BEFORE the save-command line.

    The transcript is JSONL (one event per line). We walk it, collecting the
    text of genuine user messages, skipping:
      - non-user events,
      - meta entries (`isMeta`),
      - entries whose content IS one of our slash commands — any of the six
        recognised forms in `_COMMAND_PREFIXES` (new or legacy) — so the bare
        save-command line itself is never returned as its own memory.
    The LAST surviving user message is the one to file. Returns None when the
    transcript is missing/unreadable or holds no eligible user message (the hook
    then reports nothing-to-save instead of crashing).
    """
    path = Path(transcript_path)
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    last_text: Optional[str] = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "user":
            continue
        if entry.get("isMeta"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        text = _content_to_text(message.get("content")).strip()
        if not text:
            continue
        # Skip our own command lines so the bare command is never the memory.
        if any(text == pfx or text.startswith(pfx + " ") for pfx in _COMMAND_PREFIXES):
            continue
        last_text = text
    return last_text


# --- command-line parsing helpers (shared by the hook) ---------------------


def parse_command(prompt: str) -> tuple[Optional[str], str]:
    """Classify a submitted prompt as one of our commands.

    Returns (command, argstring) where `command` is the CANONICAL id —
    "add" / "search" / "share" — that BOTH the new `/janitor-memory-user-*`
    names AND the three legacy `/…-user-mem` aliases map to (so the hook
    dispatch keys on the canonical id regardless of which slash form was typed),
    or None if the prompt is not one of ours. `argstring` is the trimmed
    remainder after the command word. The match is anchored at the start and
    requires either end-of-string or a following space/newline, so a longer
    lookalike (e.g. `/to-user-memory`, `/janitor-memory-user-adder`) is NOT
    misclassified as one of ours.
    """
    if not prompt:
        return None, ""
    stripped = prompt.strip()
    # Longest token first so a name that is a prefix of another can never shadow
    # the longer one (defensive — the current set has no such overlap, but this
    # keeps the anchoring correct if names are ever added).
    for token in sorted(_COMMAND_ALIASES, key=len, reverse=True):
        canonical = _COMMAND_ALIASES[token]
        if stripped == token:
            return canonical, ""
        if stripped.startswith(token + " ") or stripped.startswith(token + "\n"):
            return canonical, stripped[len(token):].strip()
    return None, ""


def find_memgrep() -> Optional[str]:
    """Resolve the memgrep binary path (env override → PATH → cargo bin)."""
    override = os.environ.get("MEMGREP_BIN")
    if override and Path(override).exists():
        return override
    found = shutil.which("memgrep")
    if found:
        return found
    cargo_bin = Path(os.environ.get("HOME") or os.path.expanduser("~")) / ".cargo" / "bin" / "memgrep"
    if cargo_bin.exists():
        return str(cargo_bin)
    return None
