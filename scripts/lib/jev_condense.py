"""Tool-result condensers applied before Jev scoring (TRDD-RAEGS1D5, condenser design 2026-09-24).

The owner asked for "the results of the tools, not the full output" before a transcript is
handed to Jev. Measured on four real sessions (reports/compaction-replacement/
20260924_133449+0200-condenser-design.md), the rules below cut the scored item tokens by about
15%: a Read of a code/config file down to its line range (13.7%), a task-notification down to
its summary/result/status (1.4%), and test/lint runner noise (≈0.1%, but it turns a kept
all-pass run from 700 bytes of progress dots into `412 passed in 3.1s`).

Every condenser returns a VIEW: verbatim lines selected from the original, never a paraphrase,
followed by one label line in the same `[[...]]` style as Jev's pointers. It returns `None` to
mean "keep the original on the existing path". The caller keeps the item's plain id
(`<uuid>:<n>`), so `jev_compact.py expand <id>` still returns the whole original tool_result
from the transcript. `None` is also the answer whenever a guard is unsure (G4): a wrong
condensation can hide a failure, a missed one only costs tokens.

Only `jev_compaction` may import this module (it pulls `jevctx.tokens`, whose package imports
httpx) — the same in-process boundary tests/test_jev_boundary.py enforces for jev_compaction.
"""

from __future__ import annotations

import re
from typing import Any

from jevctx.tokens import estimate_tokens

__all__ = ["condense_event", "condense_tool", "MIN_SAVED_TOKENS", "PERSISTED_OUTPUT_MARKER"]

# G1: Claude Code already cut such a result to a ~2 KB preview plus the saved file's path. The
# first prototype dropped that path line, the only way back to the full output, so a result
# carrying the marker is never condensed.
PERSISTED_OUTPUT_MARKER = "<persisted-output>"

# G2: below this saving the label and the lost context outweigh the tokens saved; a view must
# also at most halve the item. Measured: 94 of 701 code-file Reads and 557 of 566 test runs
# fall below it and stay whole, because agents already pipe runner output through `tail`.
MIN_SAVED_TOKENS = 150

# --- segment-aware command detection ---------------------------------------------------------
# Scanning the WHOLE command string misclassified a heredoc that merely contained ".log" and a
# `cd x && sed -n ...` view (measured on the prototype). Split into pipeline/list segments, drop
# leading env assignments / `time` / `timeout N`, ignore pieces that are only cd/echo/printf/#.
_SEGMENT_SPLIT_RE = re.compile(r"\n|&&|\|\||;|\|")
_LEAD_WRAPPER_RE = re.compile(r"^(\w+=\S*|time|timeout\s+\S+)\s+")
_INERT_PREFIXES = ("cd ", "echo ", "printf ", "#")

_TEST_CMD_RE = re.compile(
    r"\b(pytest|py\.test|-m unittest|npm (run )?test|pnpm (run )?test|yarn test|jest|vitest"
    r"|cargo test|go test|swift test|bun test|deno test)\b"
)
_LINT_CMD_RE = re.compile(
    r"\b(ruff|mypy|pyright|basedpyright|eslint|tsc|shellcheck|clippy|swiftlint|flake8|pylint|biome)\b"
)
# A runner summary in the OUTPUT also identifies the run (a script that invokes pytest itself).
_TEST_SUMMARY_RE = re.compile(
    r"^=*\s*(\d+ (passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?|rerun)(, )?)+.* in [\d.]+s\b"
    r"|no tests ran in [\d.]+s|^Ran \d+ tests? in [\d.]+s|^test result: (ok|FAILED)\.|^(ok|FAIL)\s+\S+\s+[\d.]+s"
    r"|^\s*Tests?:\s+\d+|^\s*Test Files\s+\d+|Interrupted: \d+ errors? during collection",
    re.M,
)
_LINT_SUMMARY_RE = re.compile(
    r"^All checks passed!|^Found \d+ errors?|^Success: no issues found"
    r"|^\d+ errors?, \d+ warnings?, \d+ (informations?|notes?)|✖ \d+ problems?",
    re.M,
)

# R1/R2 are DENY-lists: drop ONLY known pass/progress/header noise, keep every other line. The
# v1 allow-list lost a `git commit` hash line and other chain output; a deny-list can only hide
# what matches a noise pattern, and none of these matches a failure marker (measured: 0 failure
# lines lost across 910 test and test+lint sources). A progress line may only contain . s x X
# p u, so a line carrying F or E is never noise.
_TEST_NOISE_RE = re.compile(
    r"^\s*$"
    r"|^(\S+\.py\s+)?[.sxXpu]+\s*(\[\s*\d+%\])?\s*$"
    r"|::\S+ PASSED\b"
    r"|^=+ test session starts =+$"
    r"|^platform \w+ -- Python"
    r"|^(rootdir|configfile|plugins|cachedir|testpaths): "
    r"|^collected \d+ items?\s*$|^collecting \.\.\."
    r"|^test \S+ \.\.\. ok$|^running \d+ tests?$|^\s+(Compiling|Finished|Running) "
    r"|^=== RUN|^--- PASS"
    r"|^\s*[✓√] |^PASS\s"
)
_LINT_NOISE_RE = re.compile(
    r"^\s*$|^No configuration file found|^Searching for source files|^Found \d+ source files?|^pyright \d"
)

# R4: a Read of a file that is still on disk. Session scratch and temp files may be gone by
# resume time, so they stay whole; so does anything that is not code/config (reports carry
# worker findings Jev legitimately keeps).
_TMP_PATH_RE = re.compile(r"^(/tmp/|/private/tmp/|/var/folders/|/private/var/folders/)")
_CODE_EXT_RE = re.compile(
    r"\.(py|pyi|ts|tsx|js|mjs|cjs|rs|go|swift|kt|java|c|h|cc|cpp|hpp|rb|sh|bash|zsh"
    r"|toml|ya?ml|json|lock|cfg|ini|css|html)$"
)
# `cat -n` numbering as Claude Code's Read renders it (a tab after the number; an arrow in
# some versions).
_NUMBERED_LINE_RE = re.compile(r"^\s*\d+(\t|→)")

# R5: the same verbatim elements F1 shows inline at render time, plus <status> when the
# sub-agent did NOT complete — the raw transcripts carry 60 `failed` and 40 `killed` statuses
# that the summary/result alone would hide.
_NOTIFICATION_PREFIX = "<task-notification>"
_NOTIFICATION_KEEP_RE = re.compile(
    r"<(summary|result)>.*?</\1>|<status>(?!completed</status>).*?</status>", re.DOTALL
)


def _label(item_id: str, kept: int, total: int, rule: str, extra: str = "") -> str:
    ident = f"id={item_id} " if item_id else ""
    note = f"; {extra}" if extra else ""
    return f"[[excerpt {ident}kept={kept}/{total} lines rule={rule}{note}; expand the id for the full output]]"


def _programs(command: str) -> list[str]:
    """The command's pipeline/list segments with their leading wrappers stripped."""
    out = []
    for piece in _SEGMENT_SPLIT_RE.split(command):
        piece = piece.strip()
        while (m := _LEAD_WRAPPER_RE.match(piece)) is not None:
            piece = piece[m.end():].lstrip()
        if piece and not piece.startswith(_INERT_PREFIXES):
            out.append(piece)
    return out


def _passes_size_guards(original: str, view: str, ceiling_tokens: int, *, min_saved: int) -> bool:
    """G2 (enough saving, at most half) and G3 (the view still fits one unsegmented item)."""
    orig_tokens = estimate_tokens(original)
    view_tokens = estimate_tokens(view)
    if view_tokens > ceiling_tokens:
        return False  # G3: return None so the caller segments the original exactly as today
    return orig_tokens - view_tokens >= min_saved and view_tokens * 2 <= orig_tokens


def _runner_kept_lines(command: str, result_text: str) -> tuple[str, list[str], list[str]] | None:
    """(rule, kept lines, all lines) for a recognised test/lint run, else None (G4)."""
    programs = _programs(command)
    families = set()
    if any(_TEST_CMD_RE.search(p) for p in programs) or _TEST_SUMMARY_RE.search(result_text):
        families.add("test")
    if any(_LINT_CMD_RE.search(p) for p in programs) or _LINT_SUMMARY_RE.search(result_text):
        families.add("lint")
    if not families:
        return None
    noise = [{"test": _TEST_NOISE_RE, "lint": _LINT_NOISE_RE}[f] for f in sorted(families)]
    lines = result_text.splitlines()
    kept = [ln for ln in lines if not any(rx.search(ln) for rx in noise)]
    return "+".join(sorted(families)) + "-noise", kept, lines


def _condense_runner(command: str, result_text: str, item_id: str, ceiling_tokens: int) -> str | None:
    selected = _runner_kept_lines(command, result_text)
    if selected is None:
        return None  # G4: not a recognised runner
    rule, kept, lines = selected
    if len(kept) == len(lines):
        return None  # nothing to drop
    view = "\n".join([*kept, _label(item_id, len(kept), len(lines), rule)])
    return view if _passes_size_guards(result_text, view, ceiling_tokens, min_saved=MIN_SAVED_TOKENS) else None


def _condense_read(file_path: str, result_text: str, item_id: str, ceiling_tokens: int) -> str | None:
    if not file_path or _TMP_PATH_RE.match(file_path) or not _CODE_EXT_RE.search(file_path):
        return None
    lines = result_text.splitlines()
    numbered = [ln for ln in lines if _NUMBERED_LINE_RE.match(ln)]
    if len(numbered) < 2:
        return None
    label = _label(item_id, 2, len(lines), "read-range",
                   "the file is on disk: re-Read it for its current content")
    view = "\n".join([numbered[0], numbered[-1], label])
    return view if _passes_size_guards(result_text, view, ceiling_tokens, min_saved=MIN_SAVED_TOKENS) else None


def condense_tool(
    name: str, tool_input: dict[str, Any], result_text: str, *, item_id: str = "", ceiling_tokens: int
) -> str | None:
    """The condensed view of one tool_result, or None to keep it on the existing path.

    `tool_input` must be the RAW, untruncated input dict: detection on the 300-character echo
    misclassified commands in the prototype. `ceiling_tokens` is the caller's segmentation
    threshold (G3), passed in so the two can never disagree.
    """
    if PERSISTED_OUTPUT_MARKER in result_text:
        return None  # G1
    if name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return None
        return _condense_runner(command, result_text, item_id, ceiling_tokens)
    if name == "Read":
        file_path = tool_input.get("file_path")
        return _condense_read(file_path if isinstance(file_path, str) else "", result_text,
                              item_id, ceiling_tokens)
    return None  # Grep, Glob, Agent, queries, Edit/Write: their output IS the result


def condense_event(text: str, *, item_id: str = "", ceiling_tokens: int) -> str | None:
    """The condensed view of a <task-notification> event, or None to keep it whole.

    Exempt from G2's 150-token minimum and its "at most half" rule: the dropped wrapper
    (task-id, tool-use-id, output-file path, usage) is ~100 tokens, so G2 would reject almost
    every notification and R5 would save nothing; the measured 1.4% is the any-saving rule.
    The view is still required to be smaller than the original and to fit G3's ceiling.
    """
    if not text.startswith(_NOTIFICATION_PREFIX) or PERSISTED_OUTPUT_MARKER in text:
        return None
    kept = [m.group(0) for m in _NOTIFICATION_KEEP_RE.finditer(text)]
    if not any(k.startswith(("<summary>", "<result>")) for k in kept):
        return None  # G4: an unrecognised notification shape
    body = "\n".join(kept)
    view = "\n".join([body, _label(item_id, len(body.splitlines()), len(text.splitlines()), "notification")])
    if estimate_tokens(view) > ceiling_tokens or estimate_tokens(view) >= estimate_tokens(text):
        return None
    return view
