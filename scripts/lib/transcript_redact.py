"""Fail-closed redaction of text and session transcripts before they leave the machine (TRDD-TKQ274RE).

WHY THIS EXISTS: the janitor sent session transcripts to remote models unredacted. The one redaction
rule set is the TypeScript secret-shield core (`hooks/secret-shield/patterns.ts` + `home.ts`); this
module reaches it through `hooks/secret-shield/redact_bridge.ts`, run by bun, so there is no second
copy of the rules to drift. Two bridge ops are used: `redact_texts` runs op "both" over decoded item texts, which reads the plain passes first and then each line of the text that is a JSON object or array as JSON (redactText, TRDD-CAZIKQVH); the transcript copy runs
op "jsonl" over each JSONL line, which decodes every JSON string first so a secret or a home behind a JSON escape is hidden.

EVERY failure here raises `RedactionUnavailable`. There is deliberately no fallback, no "send it
unredacted", no "skip the line": a skipped redaction is a secret sent out. The caller must abort the
remote call. Exception messages are fixed text and never carry transcript content. The one deliberate
exception is `sweep_stale` failing to remove a single old entry: that is a stderr line, not a raise, because
it concerns only already-redacted leftovers and must not block later runs (see its WHY).

Stdlib only: this module is imported from hook-spawned processes that run under `uv run --script`
without dependencies, so it must not import jevctx, httpx, jev_compaction or llm_ext_summary.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import queue
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Generator, Iterable, Iterator
from pathlib import Path

_BRIDGE = Path(__file__).resolve().parents[2] / "hooks" / "secret-shield" / "redact_bridge.ts"
# A hook-spawned detached child lacks the interactive PATH (same reason as `llm_ext_summary.resolve_llm_ext`),
# so bun is looked up on PATH first and then at its usual install locations.
_BUN_FALLBACKS: tuple[str, ...] = ("/opt/homebrew/bin/bun", "/usr/local/bin/bun", "~/.bun/bin/bun")
_SIDECAR_SUFFIX = ".redact-meta.json"
# The bridge op the transcript copy runs: it decodes each JSON string of a line before redacting it, so a secret or a home behind a JSON escape is seen. Part of the sidecar metadata (see `_copy_meta`).
_COPY_OP = "jsonl"


class RedactionUnavailable(RuntimeError):
    """Redaction could not be completed. The caller must NOT send the text anywhere."""


def resolve_bun() -> str:
    """Absolute path of an executable bun, or raise RedactionUnavailable."""
    found = shutil.which("bun")
    if found:
        return found
    for candidate in _BUN_FALLBACKS:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    # WHY raise and never return "": without bun nothing can be redacted, and an unredacted send is the bug this module exists to prevent.
    raise RedactionUnavailable("bun is not installed or not executable; cannot redact")


def _bridge_fingerprint() -> list[list[int | str]]:
    """Size and mtime of every shield core file the bridge runs.

    WHY it is part of the sidecar: a reused copy was redacted by the rules of THAT moment; when a rule
    is added later (a new key shape), reusing the old copy would send what the new rule hides.
    """
    root = _BRIDGE.parent
    files = sorted([*root.glob("*.ts"), *root.glob("rules/*.ts")])
    return [[str(f.relative_to(root)), f.stat().st_size, f.stat().st_mtime_ns] for f in files]


def _bridge_results(bun: str, texts: Iterable[str], homes: list[str], timeout_s: float, *, op: str) -> Generator[str, None, None]:
    """Run one bridge process over `texts` with bridge op `op`, yield each redacted text in order.

    A writer thread feeds stdin while this generator drains stdout, so a pipe buffer filling on
    either side cannot deadlock. Raises RedactionUnavailable on a missing bridge, a spawn failure, a
    timeout (the process is killed), a nonzero exit, an error response, a malformed response or a
    response count different from the request count.
    """
    if not _BRIDGE.is_file():
        raise RedactionUnavailable("redaction bridge script is missing; cannot redact")
    try:
        # stderr to DEVNULL: a crash trace from the bridge could quote the text it was given.
        # cwd is the plugin hooks folder, never the caller folder (TRDD-6E2I17HN): bun reads bunfig.toml
        # (its `preload` runs code) and .env from its WORKING folder, so a bridge started in a project
        # would run that project's preload and could disable redaction before a transcript goes out.
        proc = subprocess.Popen([bun, str(_BRIDGE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=_BRIDGE.parent)
    except OSError:
        raise RedactionUnavailable("redaction bridge could not be started") from None
    if proc.stdin is None or proc.stdout is None:
        # WHY an explicit raise and not an assert: an assert vanishes under python -O (and bandit B101 flags it), which would let the next line fail with an AttributeError instead of failing closed.
        proc.kill()
        proc.wait()
        raise RedactionUnavailable("redaction bridge pipes could not be opened")
    stdin, stdout = proc.stdin, proc.stdout
    timed_out = threading.Event()
    writer_failed = threading.Event()
    sent = 0

    def kill_on_timeout() -> None:
        timed_out.set()
        proc.kill()

    def feed() -> None:
        nonlocal sent
        try:
            for text in texts:
                stdin.write(json.dumps({"op": op, "t": text, "homes": homes}).encode("utf-8") + b"\n")
                sent += 1
        except BaseException:
            # Recorded as a flag only, never the exception: its message can quote the text.
            writer_failed.set()
        finally:
            try:
                stdin.close()
            except OSError:
                writer_failed.set()

    timer = threading.Timer(timeout_s, kill_on_timeout)
    timer.daemon = True
    writer = threading.Thread(target=feed, daemon=True)
    timer.start()
    writer.start()
    received = 0
    try:
        for raw in stdout:
            try:
                response = json.loads(raw)
            except ValueError:
                raise RedactionUnavailable("redaction bridge sent a malformed response") from None
            if not isinstance(response, dict):
                raise RedactionUnavailable("redaction bridge sent a malformed response")
            if "error" in response:
                # The bridge error text is fixed text by design; it never echoes the input.
                raise RedactionUnavailable("redaction bridge reported an error: " + str(response["error"]))
            out = response.get("t")
            if not isinstance(out, str):
                raise RedactionUnavailable("redaction bridge sent a response without text")
            received += 1
            yield out
        proc.wait()
        writer.join()
        # WHY these checks come after EOF and in this order: a kill from the timer ends stdout early with a clean-looking prefix, and a short prefix passed on would send fewer lines than were meant to be redacted, or worse, a partial copy as if complete.
        if timed_out.is_set():
            raise RedactionUnavailable("redaction timed out")
        if writer_failed.is_set():
            raise RedactionUnavailable("redaction input could not be fed to the bridge")
        if proc.returncode != 0:
            raise RedactionUnavailable(f"redaction bridge exited with status {proc.returncode}")
        if received != sent:
            raise RedactionUnavailable("redaction bridge answered a different number of lines than it was sent")
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        writer.join()
        stdout.close()


def redact_texts(texts: list[str], *, homes: list[str] | None = None, timeout_s: float) -> list[str]:
    """Redact secrets, then home paths, in every text; same order, same length, or raise RedactionUnavailable."""
    bun = resolve_bun()
    home_list = [str(Path.home())] if homes is None else homes
    # WHY op "both" (redactText, TRDD-CAZIKQVH): these inputs are decoded item texts (from jev_compaction), not JSONL lines, but one can carry JSON lines whose secret sits behind an escape; op "both" reads the plain passes first, then each JSON line of the text as JSON, so it needs no op "jsonl".
    out = list(_bridge_results(bun, texts, home_list, timeout_s, op="both"))
    if len(out) != len(texts):
        raise RedactionUnavailable("redaction returned a different number of texts than it was given")
    return out


def _copy_meta(src_stat: os.stat_result, homes: list[str]) -> dict[str, object]:
    """The metadata a copy is made under: source size and mtime, homes, bridge op and bridge code.

    WHY one function for the sidecar write and the reuse check: the two can never disagree. WHY the op is in it: a copy made by an older op (plain text, `both`) may still hold a secret behind a JSON escape, so it must not be reused.
    """
    return {"src_size": src_stat.st_size, "src_mtime_ns": src_stat.st_mtime_ns, "homes": homes, "op": _COPY_OP, "bridge": _bridge_fingerprint()}


def _reusable(src_stat: os.stat_result, meta_path: Path, dest: Path, homes: list[str]) -> bool:
    """True when `dest` was made from this exact source, with these homes, by this exact bridge op and code."""
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return bool(dest.is_file() and meta == _copy_meta(src_stat, homes))
    except (OSError, ValueError):
        return False


def _atomic_write_text(dest: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".redact-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def redacted_transcript_copy(src: Path, dest_dir: Path, *, timeout_s: float, homes: list[str] | None = None) -> Path:
    """Write a redacted copy of the JSONL transcript `src` as `dest_dir/<src.name>` and return its path.

    Streams line by line (a transcript can be hundreds of MB; the file is never held whole). Each line goes through
    bridge op "jsonl", which decodes every JSON string of the line before redacting it, so a secret or a home written
    behind a JSON escape is hidden too; a line that is not JSON gets the plain text path. A copy already made from the
    same source size and mtime, the same homes, the same bridge op and the same bridge code is reused.
    On ANY failure the temp file is deleted and RedactionUnavailable is raised: no partial copy is ever
    left at the destination, so a caller that catches nothing cannot send a half-redacted file.
    """
    home_list = [str(Path.home())] if homes is None else homes
    # WHY: every failure here must raise RedactionUnavailable, so one except in the caller catches it; a bare OSError would escape.
    try:
        src_stat = src.stat()
    except OSError:
        raise RedactionUnavailable("transcript source could not be read; cannot redact") from None
    dest = dest_dir / src.name
    meta_path = dest_dir / (src.name + _SIDECAR_SUFFIX)
    if _reusable(src_stat, meta_path, dest, home_list):
        return dest
    bun = resolve_bun()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise RedactionUnavailable("transcript copy directory could not be created; cannot redact") from None
    flags: queue.Queue[tuple[bool, bool]] = queue.Queue()  # per source line: (it parsed as JSON, it ended with a newline)

    def source_lines() -> Iterator[str]:
        with src.open("rb") as fh:
            for raw in fh:
                has_newline = raw.endswith(b"\n")
                body = raw[:-1] if has_newline else raw
                try:
                    text = body.decode("utf-8")
                except UnicodeDecodeError:
                    # WHY refuse: a lossy decode would change what gets redacted, and the original bytes cannot go to the bridge.
                    raise RedactionUnavailable("transcript line is not valid UTF-8; cannot redact") from None
                try:
                    json.loads(text)
                    parsed = True
                except ValueError:
                    parsed = False
                flags.put((parsed, has_newline))
                yield text

    try:
        fd, tmp_name = tempfile.mkstemp(dir=dest_dir, prefix=".redact-", suffix=".tmp")
    except OSError:
        raise RedactionUnavailable("temporary redaction file could not be created; cannot redact") from None
    tmp = Path(tmp_name)
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "wb") as out, contextlib.closing(_bridge_results(bun, source_lines(), home_list, timeout_s, op=_COPY_OP)) as results:  # closing(): a failing loop body must kill the bridge now, not whenever the generator is collected
            for redacted in results:
                parsed, has_newline = flags.get_nowait()
                if parsed:
                    # WHY: a redaction that broke the JSON of a line makes the copy unreadable for the summarizer; refuse rather than ship a corrupt record.
                    try:
                        json.loads(redacted)
                    except ValueError:
                        raise RedactionUnavailable("redaction broke the JSON of a transcript line") from None
                out.write(redacted.encode("utf-8"))
                if has_newline:
                    out.write(b"\n")
        if not flags.empty():
            raise RedactionUnavailable("redacted transcript has fewer lines than the source")
        os.replace(tmp, dest)
    except BaseException as exc:
        tmp.unlink(missing_ok=True)
        if isinstance(exc, (RedactionUnavailable, KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(exc, queue.Empty):
            raise RedactionUnavailable("redacted transcript has more lines than the source") from None
        raise RedactionUnavailable("transcript could not be redacted") from None
    try:
        _atomic_write_text(meta_path, json.dumps(_copy_meta(src_stat, home_list)))
    except OSError:
        raise RedactionUnavailable("redaction metadata could not be written; cannot redact") from None
    return dest


def copy_dir(state_dir: Path) -> Path:
    """The folder under the project state folder that holds per-run redaction workspaces.

    WHY one function: the creator of a workspace (llm_ext_summary) and the sweep must agree on the location,
    and redacted text must live under the project state folder (gitignored `.janitor/state`), never in a
    shared temp folder, so the owner-only mode and the sweep cover everything that was written.
    """
    return state_dir / "redacted-transcripts"


def sidecar_digest(dest: Path) -> str:
    """sha256 hex[:16] of the sidecar bytes of the copy `dest`, or raise RedactionUnavailable.

    WHY: the sidecar records the source size and mtime, the homes and the bridge code the copy was made
    from, so its digest names those exact bytes. A caller that puts the digest in the name of anything
    derived from the copy (an llm-ext checkpoint) pairs the two by construction: a rebuilt copy gets a
    new digest and so a new name, and nothing ever has to be deleted.
    """
    try:
        raw = (dest.with_name(dest.name + _SIDECAR_SUFFIX)).read_bytes()
    except OSError:
        raise RedactionUnavailable("redaction metadata could not be read; cannot pair a checkpoint") from None
    return hashlib.sha256(raw).hexdigest()[:16]


def sweep_stale(dest_dir: Path, *, max_age_s: float = 86400.0) -> None:
    """Delete the entries of `dest_dir` older than `max_age_s`: per-run workspace folders (rmtree) and stray files.

    WHY age-bounded and not "everything": sessions of one project share this folder, and a live run's
    workspace is fresh, so only what a killed run left behind (a workspace its `finally` never reached)
    is old. A missing folder is a no-op, and an entry another run already removed is skipped. A failure to
    LIST the folder raises RedactionUnavailable (fixed text). A failure to remove one old entry does not
    raise: it prints one fixed-text line to stderr and the sweep goes on (see the WHY below).
    """
    try:
        entries = list(dest_dir.iterdir())
    except FileNotFoundError:
        return
    except OSError:
        raise RedactionUnavailable("redacted transcript folder could not be listed; cannot sweep") from None
    cutoff = time.time() - max_age_s
    for entry in entries:
        try:
            info = entry.lstat()
            if info.st_mtime >= cutoff:
                continue
            if stat.S_ISDIR(info.st_mode):
                shutil.rmtree(entry)
            elif stat.S_ISREG(info.st_mode):
                entry.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            # WHY this does NOT raise: one undeletable old entry must not make every later run fail for good
            # (the caller treats a raise as "cannot redact"). What is left is only REDACTED text in the
            # gitignored state folder, and the next run retries. Fixed text on stderr, no path.
            print("stale redaction folder could not be removed; will retry next run", file=sys.stderr)
