#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""UserPromptSubmit hook — the PRIVATE user-memory commands (TRDD-4334aad0).

Intercepts three slash commands and keeps the entire user-memory subsystem
INVISIBLE to the agent, relying on documented Claude Code hook semantics:

  /to-user-mem [<text>]   save a private memory. The prompt is BLOCKED
                          (`decision:block` "erases the prompt" → it never
                          enters the agent context/transcript). The text lands
                          on disk; the user sees only a redacted confirmation
                          via `systemMessage` (+ `reason`). With no argument the
                          WHOLE previous user message (read from transcript_path)
                          is saved instead.

  /search-user-mem <q>    search ONLY the user-mem store via `memgrep find`
                          (the +/- / wildcard / phrase DSL lives in the Rust
                          crate). The prompt is BLOCKED; the numbered results
                          reach the USER via `systemMessage` ONLY — they appear
                          in NO agent-context field, so the agent never reads,
                          recalls, or can leak a user memory.

  /share-user-mem <N>     the ONE explicit gate INTO agent context: memory #N's
                          text is injected via `hookSpecificOutput.additionalContext`
                          (the docs route additionalContext to the model). This
                          is the deliberate, user-initiated opt-in to share.

PRIVACY CONTRACT (verified against the Claude Code hooks docs, 2026-06):
  - `decision:block` → "Blocks prompt processing and erases the prompt": the
    raw command + its text never reach the model.
  - `systemMessage` → "shown to the user": user-facing, NOT agent context.
  - `additionalContext` / plain non-JSON stdout → DO reach the model: used
    ONLY for /share-user-mem; never for save text or search results.

Robustness: any non-user-mem prompt is a fast no-op (exit 0, empty stdout).
Malformed stdin, a missing memgrep, an unreadable transcript — none crash the
session; the hook degrades to a no-op or a best-effort confirmation. Always
exits 0 (the block is expressed via the JSON `decision`, not the exit code, so
the hook never aborts the turn on an internal error).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_user_mem_lib():
    """Import user_mem_lib whether running via the plugin (CLAUDE_PLUGIN_ROOT set)
    or directly (tests). Returns the module, or None if it cannot be found — in
    which case the hook becomes a no-op rather than crashing the session."""
    candidates: list[Path] = []
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if plugin_root:
        candidates.append(Path(plugin_root) / "scripts" / "lib")
    # Fallback: resolve relative to this file (scripts/hooks/ → scripts/lib/).
    candidates.append(Path(__file__).resolve().parent.parent / "lib")
    for lib_dir in candidates:
        if (lib_dir / "user_mem_lib.py").is_file():
            sys.path.insert(0, str(lib_dir))
            try:
                import user_mem_lib  # noqa: E402  -- local module, not PyPI

                return user_mem_lib
            except Exception:  # pragma: no cover - defensive
                return None
    return None


def _emit(obj: dict) -> None:
    """Write one JSON object to stdout (the hook's whole response)."""
    sys.stdout.write(json.dumps(obj))


def _block(reason: str, system_message: str | None = None) -> dict:
    """A UserPromptSubmit response that ERASES the prompt from agent context.

    `reason` is feedback for the user; `systemMessage` (when given) is the
    user-facing surface that carries any content (results / confirmation). NO
    agent-context field is set, so nothing here reaches the model.
    """
    out: dict = {"decision": "block", "reason": reason}
    if system_message is not None:
        out["systemMessage"] = system_message
    return out


def _share(additional_context: str) -> dict:
    """A response that INJECTS text into the agent context (the share gate).

    additionalContext is the documented channel that reaches the model; the
    prompt is NOT blocked so the injected memory continues the turn.
    """
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional_context,
        }
    }


def _handle_to_user_mem(um, argstring: str, payload: dict, store) -> dict:
    """Save a memory (arg text, or the previous user message when bare)."""
    text = argstring
    if not text:
        # Bare form: recover the whole previous user message from the transcript.
        transcript = payload.get("transcript_path")
        if transcript:
            prev = um.previous_user_message(transcript)
            if prev:
                text = prev
    if not text or not text.strip():
        msg = "[user-mem] nothing to save (no text given and no previous message found)."
        return _block(msg, system_message=msg)
    try:
        number = store.save(text)
    except Exception:  # pragma: no cover - disk error; never crash the session
        msg = "[user-mem] save failed (storage error)."
        return _block(msg, system_message=msg)
    char_count = len(text)
    # The confirmation NEVER contains the saved text — only its number + length.
    confirm = f"[user-mem] saved #{number} ({char_count} chars) — content withheld from agent context."
    return _block(confirm, system_message=confirm)


def _format_results(results, query: str) -> str:
    """Render numbered search results for the user (systemMessage payload)."""
    if not results:
        return f'[user-mem] search "{query}" — 0 results.'
    lines = [f'[user-mem] search "{query}" — {len(results)} result(s):']
    for r in results:
        # One line per memory: its immutable number + the memgrep summary. The
        # user picks a number and runs /share-user-mem <N> to bring it into context.
        lines.append(f"  #{r.number}  {r.summary}")
    lines.append("Use /share-user-mem <number> to inject one into context.")
    return "\n".join(lines)


def _handle_search_user_mem(um, argstring: str, store) -> dict:
    """Search the user-mem store; results go to the user via systemMessage only."""
    query = argstring.strip()
    if not query:
        msg = "[user-mem] search needs a query: /search-user-mem <keywords>"
        return _block(msg, system_message=msg)
    memgrep = um.find_memgrep()
    if memgrep is None:
        msg = "[user-mem] search unavailable: memgrep binary not found."
        return _block(msg, system_message=msg)
    results = store.search(query, memgrep=memgrep)
    payload_text = _format_results(results, query)
    # decision:block erases the (search) prompt; systemMessage shows results to
    # the user. The agent sees NEITHER the query echo nor the results.
    return _block(f'[user-mem] search done ({len(results)} result(s)) — results shown to you only.', system_message=payload_text)


def _handle_share_user_mem(argstring: str, store) -> dict:
    """Inject memory #N into the agent context — the single deliberate gate."""
    arg = argstring.strip()
    if not arg.isdigit():
        msg = "[user-mem] usage: /share-user-mem <number> (a memory number from /search-user-mem)."
        return _block(msg, system_message=msg)
    number = int(arg)
    text = store.read(number)
    if text is None:
        msg = f"[user-mem] memory #{number} not found."
        return _block(msg, system_message=msg)
    # The ONE path that puts a user memory into the model's context, by explicit
    # user request. Frame it so the model knows its provenance.
    injected = f"[user-mem #{number} — shared by the user]\n{text}"
    return _share(injected)


def main() -> int:
    # Read + parse stdin defensively; any failure → no-op (never crash the turn).
    try:
        raw = sys.stdin.read()
    except Exception:  # pragma: no cover - stdin closed
        return 0
    if not raw or not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return 0

    # FAST PATH: a cheap string check BEFORE importing the lib, so the common
    # case (any prompt that is not one of our three commands) costs nothing but
    # a startswith — the hook fires on EVERY prompt, so this guard keeps it
    # effectively free except when the user actually invokes a user-mem command.
    if not prompt.lstrip().startswith("/to-user-mem") and not prompt.lstrip().startswith("/search-user-mem") and not prompt.lstrip().startswith("/share-user-mem"):
        return 0

    um = _load_user_mem_lib()
    if um is None:
        # Lib unavailable → cannot safely handle the command; stay a no-op so the
        # prompt flows normally rather than silently disappearing.
        return 0

    # parse_command anchors the match (requires end-of-string or a following
    # space), so a lookalike like `/to-user-memory` that passed the cheap
    # prefix guard above is correctly rejected here.
    command, argstring = um.parse_command(prompt)
    if command is None:
        return 0

    # Resolve the per-project store. The harness memory dir is keyed on the
    # project directory ($CLAUDE_PROJECT_DIR), which resolve_user_mem_dir prefers;
    # the payload `cwd` is only a fallback for the (rare) case the env var is unset.
    project_dir = (os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "").strip() or None
    store_dir = um.resolve_user_mem_dir(project_dir=project_dir)
    store = um.UserMemStore(store_dir)

    if command == "to-user-mem":
        _emit(_handle_to_user_mem(um, argstring, payload, store))
    elif command == "search-user-mem":
        _emit(_handle_search_user_mem(um, argstring, store))
    elif command == "share-user-mem":
        _emit(_handle_share_user_mem(argstring, store))
    return 0


if __name__ == "__main__":
    # Bare main() so the module is safely importable (no module-scope sys.exit);
    # the hook always exits 0 — the block is carried by the JSON decision, not
    # the exit code, so an internal error never aborts the user's turn.
    main()
