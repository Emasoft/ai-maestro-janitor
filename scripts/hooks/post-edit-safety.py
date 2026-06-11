#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PostToolUse hook — assistant-being-conned write detector.

OPT-IN (CLAUDE_PLUGIN_OPTION_POST_EDIT_SAFETY_ENABLED=true). Fires
AFTER an Edit / Write / NotebookEdit that the agent has already
made, and surfaces `additionalContext` warning text when the write
landed at a sensitive path OR contains a sensitive payload pattern.

The narthex (sweep-A) insight: when an attacker can't get the agent
to EXECUTE malicious code via the pre-bash hook, they can sometimes
convince it to WRITE the same payload into a file the user / CI will
later execute. Pre-bash safety catches `cat ~/.ssh/id_rsa | curl ...`
but does nothing when the agent is talked into producing
`echo $PAYLOAD > .git/hooks/post-commit`. This PostToolUse hook
closes that loop.

What it surfaces

Sensitive-path writes (warn, regardless of content)
    .git/hooks/{pre,post,commit-msg,...}
    ~/.ssh/{authorized_keys, config}
    ~/.aws/credentials
    ~/.npmrc / ~/.pypirc / ~/.netrc / ~/.docker/config.json
    .github/workflows/*.yml, .gitlab-ci.yml, .circleci/
    crontab files, shell rc files (.bashrc/.zshrc/.profile)
    /etc/*

Sensitive-payload writes (warn, regardless of path)
    an eval call wrapping a base64-decoded payload
    curl-piped-to-sh / wget-redirected-to-sh / bash-of-a-curl-subshell
    /dev/tcp / /dev/udp
    long base64 blobs (>200 chars) inside eval / Function / exec
    ssh-rsa / ssh-ed25519 public-key lines being written

Output via `additionalContext` makes the warning visible to the model
on the next turn so it knows to surface the finding to the user
(complementary to the user-visible stderr line).

The hook does NOT block — the edit has already happened. Its job is
to make the post-edit state OBSERVABLE so the agent + user can react.
"""

from __future__ import annotations

import json
import os
import re
import sys

# Paths whose modification deserves a warning regardless of content.
_SENSITIVE_PATH_PATTERNS = (
    re.compile(r"\.git/hooks/(?:pre-commit|post-commit|pre-push|post-push|"
               r"pre-merge-commit|prepare-commit-msg|commit-msg|pre-rebase|"
               r"post-receive|update)\b"),
    re.compile(r"\.ssh/(?:authorized_keys|config|known_hosts)\b"),
    re.compile(r"\.aws/(?:credentials|config)\b"),
    re.compile(r"\.npmrc$|\.pypirc$|\.netrc$|\.gitconfig$"),
    re.compile(r"\.docker/config\.json\b"),
    re.compile(r"\.github/workflows/[^/]+\.ya?ml$"),
    re.compile(r"\.gitlab-ci\.ya?ml$"),
    re.compile(r"\.circleci/config\.ya?ml$"),
    re.compile(r"/etc/(?:cron\.|systemd/|profile|sudoers|passwd|shadow)"),
    re.compile(r"~/\.(?:bashrc|zshrc|profile|bash_profile|zprofile)$"),
    re.compile(r"\.gnupg/"),
    re.compile(r"\.kube/config\b"),
)

# Payloads whose presence in ANY written content is a strong signal.
_SENSITIVE_PAYLOAD_PATTERNS = (
    # a dynamic-exec call wrapping a base64-decode / atob / Buffer.from result
    re.compile(r"eval\s*\(\s*(?:base64\.b64decode|atob|Buffer\.from)"),
    # curl/wget piped to shell
    re.compile(r"\bcurl\s+[^|]+?\|\s*(?:bash|sh|zsh|fish)\b"),
    re.compile(r"\bwget\s+[^|]+?-O\s*-\s*\|\s*(?:bash|sh)\b"),
    re.compile(r"\bbash\s*<\s*\(\s*curl\b"),
    # /dev/tcp /dev/udp — bash's built-in network shape
    re.compile(r"/dev/(?:tcp|udp)/"),
    # ssh authorised-key shape being WRITTEN
    re.compile(r"\bssh-(?:rsa|ed25519|dss|ecdsa)\s+AAAA[A-Za-z0-9+/]{30,}"),
    # Long base64 blob inside a dynamic-exec frame
    re.compile(
        r"(?:eval|Function|exec|os\.system|subprocess\.)"
        r"[^)]{0,200}?[A-Za-z0-9+/]{200,}",
    ),
)


def _is_truthy_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def _scan_path(file_path: str) -> str | None:
    """Return a one-line reason if the file path is sensitive."""
    if not file_path:
        return None
    for pat in _SENSITIVE_PATH_PATTERNS:
        m = pat.search(file_path)
        if m:
            return f"sensitive path: {m.group(0)}"
    return None


def _scan_payload(text: str) -> str | None:
    """Return a one-line reason if the text contains a sensitive payload."""
    if not text:
        return None
    for pat in _SENSITIVE_PAYLOAD_PATTERNS:
        m = pat.search(text)
        if m:
            snippet = m.group(0)
            if len(snippet) > 80:
                snippet = snippet[:77] + "…"
            return f"sensitive payload: `{snippet}`"
    return None


def _gather_written_text(tool: str, tool_input: dict) -> str:
    """Concatenate every write the tool produced. Different tools name
    their content fields differently — handle each shape."""
    parts: list[str] = []
    if tool in ("Write",):
        parts.append(str(tool_input.get("content") or ""))
    elif tool in ("Edit",):
        parts.append(str(tool_input.get("new_string") or ""))
    elif tool in ("MultiEdit",):
        edits = tool_input.get("edits")
        if isinstance(edits, list):
            for ed in edits:
                if isinstance(ed, dict):
                    parts.append(str(ed.get("new_string") or ""))
    elif tool in ("NotebookEdit",):
        parts.append(str(tool_input.get("new_source") or ""))
    return "\n".join(p for p in parts if p)


def _gather_file_path(tool_input: dict) -> str:
    """File path key varies per tool; check the common ones."""
    for key in ("file_path", "filePath", "path", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str) and v:
            return v
    return ""


def main() -> int:
    if not _is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_POST_EDIT_SAFETY_ENABLED", False,
    ):
        return 0
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool = data.get("tool_name", "")
    if tool not in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return 0
    tool_input = data.get("tool_input") or {}

    file_path = _gather_file_path(tool_input)
    payload_text = _gather_written_text(tool, tool_input)

    path_reason = _scan_path(file_path)
    payload_reason = _scan_payload(payload_text)

    if not path_reason and not payload_reason:
        return 0  # silent

    parts = []
    if path_reason:
        parts.append(path_reason)
    if payload_reason:
        parts.append(payload_reason)
    summary = " + ".join(parts)

    # Surface BOTH a stderr line (user-visible) AND additionalContext
    # (visible to the model on the next turn so it raises the issue).
    msg = (
        f"[post-edit-safety] {tool} on `{file_path or '<unknown>'}` triggered: "
        f"{summary}. Review the diff before continuing — this may be the "
        f"model writing attacker code under prompt-injection pressure. The "
        f"janitor's pre-bash hook catches EXECUTION; this hook catches "
        f"WRITING the same class of payload."
    )
    print(msg, file=sys.stderr)
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg,
        },
    }
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
