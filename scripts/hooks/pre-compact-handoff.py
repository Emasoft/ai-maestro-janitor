#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PreCompact hook — write a FILESYSTEM-GROUNDED handoff before each compaction.

Why this hook exists (the load-bearing reason — the real failure it fixes):
After a compaction the agent treated the compaction SUMMARY as ground truth and
confidently asserted stale/wrong facts (an OAuth account's health %, "published
vs not", whole narratives) it NEVER re-verified — the summary promoted day-old
hypotheses to "fact". A compaction summary is lossy and can PROMOTE a transient
wrong hypothesis to a stated fact.

This hook gives the post-compaction turn an AUTHORITATIVE, un-hallucinatable
re-grounding point. On every PreCompact it writes a handoff built ONLY from
on-disk truth — never transcript prose — to a STABLE path under the project's
janitor state dir (`<state>/precompact-handoff.md`):

  * git HEAD + the last ~12 commits (oneline),
  * `git status --short` (the real working-tree state),
  * the plugin version,
  * the newest in-flight TRDD(s) on the design board, with their `## ⏵ STATE`
    blocks copied VERBATIM,
  * a standing faithfulness instruction (treat the summary as UNVERIFIED).

Because every line is read from disk at compaction time, NONE of it can be
hallucinated. The next session is steered to read this file FIRST: the existing
resume loop (post-compact-resume.py records the directive → dispatch.py emits the
single `[janitor-resume]` cue) prepends a "read precompact-handoff.md FIRST"
pointer when this file exists.

CONTRACT (verified against the official Claude Code hooks docs 2026-06-25 —
https://code.claude.com/docs/en/hooks):
  * PreCompact stdin JSON carries the COMMON fields: `session_id`,
    `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`. The
    `/compact`-vs-auto distinction is the hook MATCHER (`manual`|`auto`); the
    payload is not guaranteed to carry a `trigger` field, so we read it
    opportunistically and never depend on it.
  * PreCompact does NOT support `hookSpecificOutput.additionalContext` — it
    CANNOT inject text into the compacted context. So the faithfulness
    instruction is delivered through the EXISTING [janitor-resume] loop (which
    DOES reach the next turn), not through this hook's output. This hook MAY emit
    a best-effort `systemMessage` pointing at the handoff for the summarizer in
    the SAME turn.
  * Exit 2 OR `decision:"block"` would BLOCK compaction. This hook MUST NEVER
    block — it always exits 0 and never sets `decision`. A hook fault must never
    disrupt compaction, so everything is wrapped and degrades to a
    "(unavailable)" line.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# The stable, in-place handoff file the post-compaction turn must read first.
HANDOFF_FILENAME = "precompact-handoff.md"

# In-flight = a TRDD actively being worked (matches post-compact-resume.py): not
# parked (backburner/todo), not blocked, not terminal, not soak-monitoring.
_INFLIGHT_COLUMNS = frozenset(
    {"design", "dispatch", "dev", "testing", "ai_review", "human_review"}
)

# Canonical TRDD filename shape: TRDD-<YYYYMMDD_HHMMSS±HHMM>-<uid8>-<slug>.md.
_UID_RE = re.compile(r"TRDD-\d{8}_\d{6}[+-]\d{4}-([0-9a-fA-F]{8})-")

# Matches the STATE head heading "## ⏵ STATE …" / "## STATE …" (⏵ = U+23F5).
_STATE_HEADING = re.compile(r"^##\s+(?:⏵\s*)?STATE\b")

MAX_TRDDS = 3              # how many in-flight TRDDs to copy STATE blocks for
MAX_STATE_LINES = 160      # cap STATE lines per TRDD so the handoff stays bounded
MAX_COMMITS = 12           # recent commits in the oneline log
_FRONT = 4000              # bytes of head to scan for frontmatter fields


def _run_git(args: list[str], cwd: Path, *, timeout: float = 5.0) -> str:
    """Run a git command in `cwd`, return stdout or "" on any failure.

    Best-effort and exception-proof: a missing git, a non-repo cwd, or a timeout
    must not break the handoff (the section degrades to "(unavailable)").
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.rstrip("\n")


def _plugin_version(plugin_root: str) -> str:
    """Read the plugin's declared version from .claude-plugin/plugin.json."""
    if not plugin_root:
        return "unknown"
    try:
        data = json.loads(
            (Path(plugin_root) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        return str(data.get("version", "unknown")) if isinstance(data, dict) else "unknown"
    except (OSError, ValueError, TypeError):
        return "unknown"


def _frontmatter_field(head: str, key: str) -> str:
    """First value of a top-level `key:` line in a TRDD frontmatter head.

    maxsplit=1 keeps the colons inside an ISO `updated:` value intact.
    """
    for line in head.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""


def _is_inflight(head: str) -> bool:
    """True iff this TRDD head is actively being worked (v2 column OR v1 status)."""
    column = _frontmatter_field(head, "column")
    if column:
        return column in _INFLIGHT_COLUMNS
    # Legacy v1 fallback: status: in-progress is the in-flight equivalent.
    return _frontmatter_field(head, "status") == "in-progress"


def _state_block(text: str) -> str | None:
    """Extract the `## STATE` head section (until the next `## ` heading), capped."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if _STATE_HEADING.match(ln)), None)
    if start is None:
        return None
    end = next(
        (j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")),
        len(lines),
    )
    block = lines[start:end]
    if len(block) > MAX_STATE_LINES:
        block = block[:MAX_STATE_LINES] + [
            "… (STATE block truncated — read the full TRDD file)"
        ]
    return "\n".join(block).strip()


def _inflight_trdds(project_root: Path) -> list[tuple[str, str, str, str]]:
    """Return in-flight TRDDs as (updated, name, title, full_text), newest first.

    `updated:` is an ISO-8601 string that sorts lexicographically within a shared
    local TZ offset, so a reverse string sort puts the most recently touched
    in-flight task first — the best "what was I just doing" heuristic.
    """
    tasks_dir = project_root / "design" / "tasks"
    if not tasks_dir.is_dir():
        return []
    rows: list[tuple[str, str, str, str]] = []
    for path in tasks_dir.glob("TRDD-*.md"):
        if not _UID_RE.search(path.name):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        head = text[:_FRONT]
        if not _is_inflight(head):
            continue
        updated = _frontmatter_field(head, "updated")
        title = _frontmatter_field(head, "title") or path.name
        rows.append((updated, path.name, title[:80].strip(), text))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows[:MAX_TRDDS]


def _build_handoff(project_root: Path, plugin_root: str, trigger: str) -> str:
    """Compose the filesystem-grounded handoff. Every section is best-effort."""
    now = time.time()
    local = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(now))
    utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    version = _plugin_version(plugin_root)

    head_sha = _run_git(["rev-parse", "HEAD"], project_root) or "(unavailable)"
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], project_root) or "(unavailable)"
    log = _run_git(["log", "-n", str(MAX_COMMITS), "--oneline", "--no-decorate"], project_root)
    status = _run_git(["status", "--short"], project_root)
    trdds = _inflight_trdds(project_root)

    out: list[str] = []
    out.append("# PreCompact ground-truth handoff")
    out.append(
        "_Authoritative, FILESYSTEM-DERIVED state captured at compaction time. "
        "Every line below was read from disk/git — it is un-hallucinatable._"
    )
    out.append("")
    out.append("## ⚠️ FAITHFULNESS INSTRUCTION — read before trusting any summary")
    out.append(
        "A context compaction occurred. The compaction SUMMARY is lossy and may "
        "promote stale or wrong hypotheses (e.g. a service's health %, "
        "\"published vs not\", whole narratives) to \"fact\". Treat EVERY technical "
        "claim in the summary as UNVERIFIED until you have checked it against this "
        "handoff and the TRDD `## STATE` blocks below. Do NOT promote an uncertain "
        "hypothesis to fact. Re-ground here first, then act."
    )
    out.append("")
    out.append("## Capture metadata")
    out.append(f"- Captured (local): {local}")
    out.append(f"- Captured (UTC): {utc}")
    out.append(f"- Compaction trigger: {trigger or 'unknown'}")
    out.append(f"- Project root: {project_root}")
    out.append(f"- ai-maestro-janitor version: {version}")
    out.append("")
    out.append("## Git HEAD")
    out.append(f"- Branch: {branch}")
    out.append(f"- HEAD: {head_sha}")
    out.append("")
    out.append(f"## Recent commits (last {MAX_COMMITS}, oneline)")
    out.append("```")
    out.append(log if log else "(unavailable)")
    out.append("```")
    out.append("")
    out.append("## Working tree (`git status --short`)")
    out.append("```")
    out.append(status if status else "(clean or unavailable)")
    out.append("```")
    out.append("")
    if trdds:
        out.append(
            f"## In-flight TRDD STATE blocks ({len(trdds)}, newest first) — VERBATIM, AUTHORITATIVE"
        )
        for updated, name, title, text in trdds:
            out.append("")
            out.append(f"### design/tasks/{name} — {title}")
            out.append(f"(updated: {updated or 'unknown'})")
            block = _state_block(text)
            if block:
                out.append("")
                out.append(block)
            else:
                out.append("")
                out.append("(no `## STATE` block — read the full TRDD file top-to-bottom)")
    else:
        out.append("## In-flight TRDD STATE blocks")
        out.append("(no in-flight TRDD found on the design board)")
    out.append("")
    return "\n".join(out) + "\n"


def _emit_system_message(handoff_path: Path) -> None:
    """Best-effort breadcrumb for the SAME-turn summarizer.

    PreCompact cannot inject into the compacted context, but a `systemMessage` is
    a supported common field. We NEVER set `decision` (that would block), and we
    always exit 0 — so this is advisory-only.
    """
    payload = {
        "systemMessage": (
            "[janitor] An authoritative filesystem-derived handoff was written to "
            f"{handoff_path}. Prior transcript summaries may contain HALLUCINATED "
            "state — after compaction, treat every technical claim in the summary as "
            "UNVERIFIED until checked against that handoff and the TRDD STATE blocks."
        )
    }
    try:
        print(json.dumps(payload))
    except (OSError, ValueError):
        pass


def main() -> int:
    # Drain stdin (PreCompact delivers a JSON payload there). We rely on
    # CLAUDE_PROJECT_DIR for project resolution, falling back to the payload `cwd`.
    raw = ""
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
    except (OSError, ValueError):
        raw = ""

    cwd_fallback = ""
    trigger = ""
    if raw.strip():
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                cwd_fallback = str(payload.get("cwd", "") or "")
                # `trigger` is read opportunistically — the docs don't guarantee it
                # in the payload (it's the matcher value), so we never depend on it.
                trigger = str(payload.get("trigger", "") or "")
        except (ValueError, TypeError):
            cwd_fallback = ""

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    project_env = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    project_dir = Path(project_env or cwd_fallback or os.getcwd())

    # Prefer the local state lib (atomic_write, state_dir, init_state, log_line) for
    # convention parity. If it can't be imported, fall back to a direct atomic write
    # so the handoff is STILL produced — the whole point is to never silently skip.
    state = None
    if plugin_root:
        sys.path.insert(0, str(Path(plugin_root) / "scripts"))
        try:
            from lib import state as _state  # noqa: E402 - local package, not PyPI

            state = _state
            if cwd_fallback and not project_env:
                # Hand cwd to the state lib as a guarded fallback (set BEFORE the first
                # project_root()/state_dir() call — those lru-cache on first use). Avoids
                # mutating the reserved $CLAUDE_PROJECT_DIR env (which would clobber it
                # session-wide for every other plugin).
                state.set_project_dir_override(cwd_fallback)
        except Exception as exc:  # noqa: BLE001
            print(f"[pre-compact-handoff] state import failed: {exc}", file=sys.stderr)
            state = None

    try:
        if state is not None:
            state.init_state()
            sd = state.state_dir()
            project_dir = state.project_root()
        else:
            sd = project_dir / ".janitor" / "state"
            sd.mkdir(parents=True, exist_ok=True)

        handoff = _build_handoff(project_dir, plugin_root, trigger)
        handoff_path = sd / HANDOFF_FILENAME

        if state is not None:
            state.atomic_write(handoff_path, handoff)
            try:
                state.log_line(
                    "pre-compact-handoff",
                    f"handoff written ({len(handoff)} bytes, trigger={trigger or 'unknown'})",
                )
            except Exception:  # noqa: BLE001
                pass
        else:
            # Inline atomic-by-rename write (mirrors state.atomic_write) so a missing
            # state lib never costs us the handoff.
            tmp = handoff_path.with_suffix(handoff_path.suffix + f".tmp.{os.getpid()}")
            tmp.write_text(handoff, encoding="utf-8")
            os.replace(tmp, handoff_path)

        _emit_system_message(handoff_path)
    except Exception as exc:  # noqa: BLE001 - a hook fault must NEVER block compaction
        # Best-effort log, then swallow. Never raise, never set decision, never exit 2.
        try:
            if state is not None:
                state.log_line("pre-compact-handoff", f"failed: {exc}")
            else:
                print(f"[pre-compact-handoff] {exc}", file=sys.stderr)
        except Exception:  # noqa: BLE001
            print(f"[pre-compact-handoff] {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    # Bare main() — side effects live inside it so the module is import-safe (no
    # module-scope sys.exit), matching the sibling janitor hooks.
    main()
