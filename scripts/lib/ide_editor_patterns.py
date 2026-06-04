"""IDE / editor-config attack patterns.

Wave 17 of the github-monitoring distillation. Patterns target the
LOCAL developer-machine attack surface that the existing janitor
inventory does NOT cover yet:

  * `.vscode/extensions.json` malicious recommendations
    (homoglyph publishers, typosquats, suspicious TLDs)
  * `.idea/runConfigurations/*.xml` and `.idea/workspace.xml`
    shell-command-in-config (JetBrains XML, never JSON)
  * `.idea/dataSources*.xml` embedded JDBC credentials or
    remote-host phone-home
  * `.editorconfig` non-standard `exec_*` / `command =` directives
    honoured by JetBrains EditorConfig + some VSCode plugins
  * `*.sublime-build` / `*.sublime-project` with `curl | sh` in
    `cmd` / `shell_cmd`
  * Vim modeline `:!shell` escape / `:call system(` / `:py` /
    `:so` from a poisoned file open
  * Emacs `.dir-locals.el` `(eval . (shell-command …))` form

This module is the RULE-PATTERN catalog. Detectors + the post-edit
hook import these and run them. Pure-stdlib (re, NamedTuple) so it
loads in every PEP 723 script block without third-party deps.

Public surface mirrors `agent_config_patterns`:

  * Rule(id, name, severity, description, pattern, owasp_asi)
                                  — single rule record.
  * RULES                         — ordered tuple of every catalogued rule.
  * scan_text(text, *, file_kind="ide") -> list[Finding]
                                  — run every applicable rule, return findings.
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)            — single finding record. Frozen.
  * FILE_KIND_FOR_PATH(path) -> str
                                  — convenience: pick the right `file_kind`
                                    given a path.

Rule severity strings: "CRITICAL", "HIGH", "MEDIUM", "LOW", matching the
existing janitor sentinel/zizmor convention.

Determinism: pure regex. No LLM, no heuristic confidence scoring. Every
rule either matches or doesn't, given the file contents.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as agent_config_patterns.Finding
    so detectors can render either kind uniformly."""

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
    # `applies_to` is a tuple of regex strings (compiled lazily by the
    # caller / scan_text). A finding fires only when the file path
    # matches at least one of these. Empty tuple = "applies everywhere".
    # We deliberately keep this here (not on the Finding) so file-routing
    # logic lives next to the rule that needs it.
    applies_to: tuple[str, ...]


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE. Most IDE configs are
    case-insensitive in practice (Windows filesystems, plugin
    normalisation), so case-folding catches the homoglyph + casing
    attempts attackers use to slip past exact-match scanners."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


def _re_dot(pattern: str) -> re.Pattern:
    """Same flags PLUS DOTALL — used when the pattern spans multiple
    lines (XML / JSON blocks where `\\s*` alone isn't enough because
    `.` should also eat newlines inside `[\\s\\S]` shortcuts)."""
    return re.compile(
        pattern,
        re.IGNORECASE | re.MULTILINE | re.UNICODE | re.DOTALL,
    )


# ---- 1. VSCode extension recommendation rug-pull ------------------------


# `.vscode/extensions.json` `recommendations` array — flag any entry
# whose publisher segment contains a Cyrillic Latin-lookalike
# (а, е, о, р, с, у, х), or matches a known typosquat of a popular
# publisher, or has a zero-width whitespace character anywhere, or
# uses a vanity-TLD-style segment.
#
# The regex matches the dangerous JSON shape directly — a quoted
# string that itself contains the bad pattern. We do NOT first try to
# parse JSON because:
#   (a) Attackers love comments in jsonc, which json.loads chokes on;
#   (b) The pattern needs to fire on the raw file contents so the
#       reported line/column maps back to what the human sees.
_VSCODE_EXT_RUG = _re_dot(
    r'"recommendations"\s*:\s*\['
    r'[^\]]*'
    # capture each suspect-quoted-string match within the array body
    r'"([^"\n]*)"'
)

# Inner classifier — applied to each captured string by scan_text.
# Tracks the four threat shapes from the spec: homoglyph publisher,
# zero-width whitespace, known typosquats, vanity TLD.
# `[\w-]` (with re.UNICODE) allows Latin AND Cyrillic chars; this is
# crucial because a publisher segment like `miсrоsоft` contains
# MULTIPLE Cyrillic homoglyphs interspersed with Latin chars, and a
# Latin-only character class would stop at the first non-Latin char.
_VSCODE_EXT_RUG_INNER = re.compile(
    r"^"
    r"(?:"
    # Cyrillic lookalikes for Latin a/e/o/p/c/y/x — any homoglyph in
    # the publisher segment is enough to fire. We use [\w-] so a
    # string of "Latin-Cyrillic-Latin-Cyrillic-Latin" matches end to
    # end; the trigger is the presence of at least one homoglyph char.
    r"[\w-]*[аеорсух][\w-]*\.[\w-]+"
    # Zero-width chars (ZWSP / ZWNJ / ZWJ / WORD-JOINER / BOM)
    # anywhere in the string.
    r"|.*[​‌‍⁠﻿].*"
    # Known typosquats of popular publishers — append `\.[\w-]+` so
    # the typosquat name as the PUBLISHER segment is matched (the
    # full extension ID is publisher.name).
    r"|(?:ms-pyth0n|ms-pythou|ms-pythno"
    r"|dbaumer|dbeumer|dbeaumer"
    r"|vscode-icons-[a-z]"
    r"|gihub|githu|github\.copil0t"
    r"|anthropic-claude-[a-z]+|antropic)\.[\w-]+"
    # Free-TLDs commonly used by malware — these never appear as
    # publisher segments in legit listings.
    r"|.*\.(?:tk|gq|cf|ml|ga)\b.*"
    r")$",
    re.IGNORECASE | re.UNICODE,
)


# ---- 2. JetBrains run-configuration shell command -----------------------


# Match a JetBrains <configuration> opener whose type names a
# shell-capable runner (Shell, Makefile, Python, JS-debug), followed
# within ~4 KB by an <option name="…" value="…"> whose value is the
# canonical RCE shape (curl|sh, wget|sh, sh -c, python -c, node -e,
# base64 -d | sh, powershell -enc).
#
# Plain `./gradlew test` or `make build` does NOT match — that value
# string has no piped-shell / `-c` / `-e` / base64 shape.
_JETBRAINS_RUNCONFIG = _re_dot(
    r"<configuration\b[^>]*\stype\s*=\s*\""
    r"(?:ShConfigurationType"
    r"|MakefileRunConfiguration"
    r"|PythonConfigurationType"
    r"|JavascriptDebugType)\""
    r"[^>]*>"
    r"[\s\S]{0,4096}?"
    r"<option\s+name\s*=\s*\""
    r"(?:SCRIPT_TEXT|INTERPRETER_PATH|COMMAND|EXECUTABLE_PATH"
    r"|SCRIPT_NAME|PARAMETERS)\""
    r"\s+value\s*=\s*\"[^\"]{0,2048}?"
    r"(?:curl\s+[^\"]*\|\s*(?:ba)?sh"
    r"|wget\s+[^\"]*\|\s*(?:ba)?sh"
    r"|\b(?:ba|z)?sh\s+-c\s+[\"']"
    r"|\bpython3?\s+-c\s+[\"']"
    r"|\bnode\s+-e\s+[\"']"
    r"|\bpowershell\s+-(?:enc|encodedcommand)\b"
    r"|\bbase64\s+(?:-d|--decode)\s*\|\s*(?:ba)?sh)"
)


# ---- 3. JetBrains datasource embedded credentials -----------------------


# Match either:
#   (a) <jdbc-url> with embedded `user=…&password=…` in the connection
#       string, or
#   (b) <jdbc-url> pointing at a non-loopback, non-`.local` host
#       (data-source phoning home), or
#   (c) plaintext `<user-name>` / `<password>` element with non-empty
#       content.
#
# We split these into two patterns because the first two need a
# multi-line <data-source>…</data-source> envelope and DOTALL, while
# the third is a single-line value match.
_JETBRAINS_DATASOURCE_URL = _re_dot(
    r"<data-source\b[^>]*>"
    r"[\s\S]{0,2048}?"
    r"<jdbc-url>\s*"
    r"(?:"
    # (a) JDBC URL with embedded user + password query params.
    r"jdbc:[^<]*[?&](?:user|username)\s*=\s*[^&<]+"
    r"&[^<]*password\s*=\s*[^&<]+"
    # (b) JDBC URL pointing at a public-looking host (anything with
    # a non-.local TLD that is not 127.0.0.1 / localhost / 0.0.0.0).
    # Negative lookahead suppresses loopback, IPv6 loopback,
    # docker-internal, and explicit *.local / *.internal hosts.
    r"|jdbc:[a-z0-9+\-]+://"
    r"(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]"
    r"|host\.docker\.internal)"
    r"[a-z0-9.\-]+\.(?!local\b|internal\b)[a-z]{2,}"
    # (c) Plaintext http:// or ftp:// prefix in the JDBC URL —
    # bootstrap exfiltration even if the JDBC driver later upgrades.
    r"|jdbc:[^<]*://(?:https?|ftp)://"
    r")"
    r"[\s\S]{0,2048}?"
    r"</data-source>"
)

# Secondary: inline plaintext <user-name> or <password> in a
# data-source XML. JetBrains normally moves these to the keychain;
# committing them inline IS the leak.
_JETBRAINS_DATASOURCE_INLINE_CRED = _re(
    r"<(?:user-name|password)>"
    r"\s*[^<\s][^<]{2,}\s*"
    r"</(?:user-name|password)>"
)


# ---- 4. .editorconfig exec directive ------------------------------------


# EditorConfig core spec has a fixed key set. Any key not in the spec
# is already a yellow flag; matching a shell-shape value on a non-
# standard key is a strong signal. We DON'T need to enumerate every
# possible custom plugin key — we enumerate the disclosed-attack key
# names PLUS treat any `ij_*command` / `ij_*exec` JetBrains-plugin key
# as suspect.
_EDITORCONFIG_EXEC = _re(
    r"^\s*"
    r"(?:ij_[a-z0-9_]*command\b"
    r"|ij_[a-z0-9_]*exec\b"
    r"|command_run_on_save\b"
    r"|exec_helper\b"
    r"|format_command\b"
    r"|run_command\b"
    r"|on_save\b"
    r"|post_save_command\b)"
    r"\s*=\s*"
    # Shell-shape value — pipe-shell, -c/-e exec, decoder pipe,
    # known interpreter, OR command substitution `$(...)`.
    r"[^#\r\n]*"
    r"(?:\bcurl\b|\bwget\b|\bnpx\b|\buvx\b"
    r"|\b(?:ba|z)?sh\b|\bnode\b|\bpython3?\b"
    r"|\bpowershell\b|\bbase64\s+(?:-d|--decode)\b"
    r"|\$\(|\beval\b)"
)


# ---- 5. Sublime build remote command ------------------------------------


# `*.sublime-build` / `*.sublime-project` build_systems block with a
# `cmd` / `shell_cmd` / `windows_cmd` / `osx_cmd` / `linux_cmd` key
# whose value runs a piped-shell / -c / -e / decoder pipeline.
#
# Sublime build files are JSON-with-comments; we operate on raw text
# to avoid being defeated by trailing-comma/comment jsonc syntax.
_SUBLIME_BUILD_REMOTE = _re_dot(
    r'"(?:cmd|shell_cmd|windows_cmd|osx_cmd|linux_cmd)"\s*:\s*'
    r"(?:"
    # String form — `"shell_cmd": "curl … | sh"`.
    r'"(?:[^"\\]|\\.){0,2048}?'
    r"(?:curl\s+[^\"]*\|\s*(?:ba)?sh"
    r"|wget\s+[^\"]*\|\s*(?:ba)?sh"
    r"|\b(?:ba|z)?sh\s+-c\s+"
    r"|\bnode\s+-e\s+"
    r"|\bpython3?\s+-c\s+"
    r"|\bbase64\s+(?:-d|--decode)\s*\|\s*(?:ba)?sh"
    r"|\bpowershell\s+-(?:enc|encodedcommand)\b)"
    r'[^"]{0,512}"'
    r"|"
    # Array form — `["bash", "-c", "<payload>"]` style.
    r'\[[^\]]{0,2048}?"(?:bash|sh|zsh)"[^\]]{0,32}"-c"'
    r'[^\]]{0,2048}?"(?:[^"\\]|\\.){0,2048}?'
    r"(?:curl|wget|eval|\beval\b)[^\]]*\]"
    r")"
)


# ---- 6. Vim modeline shell escape ---------------------------------------


# Vim modeline syntax: `vim:`, `vi:`, or `ex:` near the start/end of a
# file, optionally with `set …` before the option list, separated by
# colons. The dangerous primitives inside a modeline are:
#   * `:!cmd`            — shell escape
#   * `:call system(…)`  — Vimscript shell-out
#   * `:so` / `:source`  — execute another vim file
#   * `:py` / `:python`  — embedded Python
#   * `set modelineexpr` — opts INTO unsafe expression evaluation
#
# The pattern matches the modeline opener plus ANY of the dangerous
# primitives within 200 chars (most modelines are < 100 chars).
_VIM_MODELINE = _re(
    r"(?:^|[^A-Za-z0-9_])"
    r"(?:vim?|ex)\s*[:=]\s*"
    r"(?:set?\s+)?"
    r"[^\"\n]{0,200}"
    r"(?::!"  # shell escape
    r"|autocmd\b[^\"\n]*:!"  # autocmd-wrapped shell escape
    r"|:call\s+system\s*\("  # call system()
    r"|:so(?:urce)?\s+[/~%]"  # :so to absolute / ~/ / %
    r"|set\b[^\"\n]*\bmodelineexpr\s*=\s*1"  # opt into modeline-expr
    r"|:py3?\b"  # :py / :py3
    r"|:python3?\b)"  # :python / :python3
)


# ---- 7. Emacs .dir-locals.el eval form ---------------------------------


# `.dir-locals.el` is Lisp s-exps. The dangerous primitive is an
# `(eval . FORM)` pair inside the alist where FORM calls a
# shell-execution / process-launch / file-load function.
#
# We allow up to ~4 KB between the outer dir-locals shape and the
# inner eval call to handle indented multi-line forms.
_EMACS_DIR_LOCALS_EVAL = _re_dot(
    r"\(\s*"
    # Outer key: `nil`, a major-mode symbol, or a (subdir . path) cons.
    r"(?:nil|[a-z][a-z0-9-]*-mode"
    r"|\([a-z][a-z0-9-]*\s+\.\s+[^)]+\))"
    r"\s*\.\s*\("
    r"[\s\S]{0,4096}?"
    r"\(\s*eval\s*\.\s*\("
    r"[\s\S]{0,2048}?"
    # Dangerous Lisp primitive — anything that touches a subprocess
    # or loads code from disk.
    r"\b(?:shell-command(?:-to-string)?"
    r"|call-process(?:-shell-command|-region)?"
    r"|start-process(?:-shell-command)?"
    r"|make-process"
    r"|async-shell-command"
    r"|url-retrieve(?:-synchronously)?"
    r"|url-copy-file"
    r"|load-file"
    r"|require)\b"
)

# Secondary: `safe-local-eval-function` — attacker pre-registers an
# eval form as "safe" so Emacs stops prompting.
_EMACS_SAFE_LOCAL_EVAL = _re(
    r"\(\s*safe-local-eval-function\s+'[a-z][a-z0-9-]*\)"
)


# ---- File-path → file_kind routing --------------------------------------


# Each rule's `applies_to` is a tuple of *path-shape* regexes — when
# the caller has a file path, scan_text only runs the rules whose
# `applies_to` matches the path. We compile them lazily.
_PATH_VSCODE_EXTENSIONS = (r"(?:^|/)\.vscode/extensions\.json$",)
_PATH_JETBRAINS_RUNCONFIG = (
    r"(?:^|/)\.idea/runConfigurations/[^/]+\.xml$",
    r"(?:^|/)\.idea/workspace\.xml$",
)
_PATH_JETBRAINS_DATASOURCE = (
    r"(?:^|/)\.idea/dataSources\.xml$",
    r"(?:^|/)\.idea/dataSources/[^/]+\.xml$",
    r"(?:^|/)\.idea/dataSources\.local\.xml$",
)
_PATH_EDITORCONFIG = (r"(?:^|/)\.editorconfig$",)
_PATH_SUBLIME_BUILD = (
    r"\.sublime-build$",
    r"\.sublime-project$",
)
_PATH_EMACS_DIR_LOCALS = (
    r"(?:^|/)\.dir-locals(?:-2)?\.el$",
)
# Vim modeline can live in any file — so we leave applies_to empty
# and the caller restricts the scan window (first 5 + last 5 lines).


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="ide-vscode-extension-recommendation-rug",
        name="VSCode extensions.json — homoglyph / typosquat / suspicious TLD",
        severity="HIGH",
        description=(
            "`.vscode/extensions.json` recommends an extension whose "
            "publisher segment contains a Cyrillic Latin-lookalike, a "
            "zero-width whitespace char, a known typosquat of a popular "
            "publisher, or a free-TLD (.tk/.gq/.cf/.ml/.ga). VSCode's "
            "'Install Recommended Extensions' toast turns this into one "
            "click to full keyboard/clipboard/FS/network access."
        ),
        pattern=_VSCODE_EXT_RUG,
        owasp_asi="ASI-05",
        applies_to=_PATH_VSCODE_EXTENSIONS,
    ),
    Rule(
        id="ide-jetbrains-runconfig-shell-command",
        name="JetBrains run-configuration with shell command",
        severity="CRITICAL",
        description=(
            "`.idea/runConfigurations/*.xml` (or workspace.xml inline) "
            "embeds a Sh / Makefile / Python / JS-debug run config "
            "whose SCRIPT_TEXT / COMMAND / etc. value is a piped-shell "
            "(curl|sh, wget|sh), -c / -e exec, base64-decode-pipe-shell, "
            "or powershell -enc. Hotkey-bound → one-keystroke RCE."
        ),
        pattern=_JETBRAINS_RUNCONFIG,
        owasp_asi="ASI-06",
        applies_to=_PATH_JETBRAINS_RUNCONFIG,
    ),
    Rule(
        id="ide-jetbrains-datasource-embedded-credentials",
        name="JetBrains dataSources XML with embedded credentials or remote host",
        severity="HIGH",
        description=(
            "`.idea/dataSources*.xml` either (a) embeds JDBC URL with "
            "inline `user=…&password=…`, (b) points at a non-loopback "
            "public host (data-source phoning home), or (c) carries an "
            "http://-prefixed bootstrap URL. JetBrains usually stores "
            "credentials in the keychain — inline plaintext IS the leak."
        ),
        pattern=_JETBRAINS_DATASOURCE_URL,
        owasp_asi="ASI-04",
        applies_to=_PATH_JETBRAINS_DATASOURCE,
    ),
    Rule(
        id="ide-jetbrains-datasource-inline-password",
        name="JetBrains dataSources XML with plaintext <password> / <user-name>",
        severity="HIGH",
        description=(
            "`.idea/dataSources*.xml` contains a non-empty plaintext "
            "<user-name> or <password> element. Even with dev-only "
            "credentials this is a committed-secret pattern; on prod "
            "fixtures it is a direct credential leak."
        ),
        pattern=_JETBRAINS_DATASOURCE_INLINE_CRED,
        owasp_asi="ASI-04",
        applies_to=_PATH_JETBRAINS_DATASOURCE,
    ),
    Rule(
        id="ide-editorconfig-exec-directive",
        name=".editorconfig non-standard exec / command directive",
        severity="HIGH",
        description=(
            "`.editorconfig` carries a non-spec key (ij_*command, "
            "ij_*exec, command_run_on_save, exec_helper, format_command, "
            "run_command, on_save, post_save_command) whose value runs a "
            "shell command. Loaded silently by every modern editor; "
            "unknown keys are silently honoured by editors that handle "
            "them, silently ignored by editors that don't — the asymmetry "
            "is the attack vector."
        ),
        pattern=_EDITORCONFIG_EXEC,
        owasp_asi="ASI-06",
        applies_to=_PATH_EDITORCONFIG,
    ),
    Rule(
        id="ide-sublime-build-remote-cmd",
        name="Sublime build with curl|sh / -c / base64-decode-pipe-shell",
        severity="CRITICAL",
        description=(
            "`*.sublime-build` / `*.sublime-project` build_systems block "
            "has a `cmd` / `shell_cmd` / OS-specific cmd that pipes "
            "curl/wget into sh, runs `sh -c` / `node -e` / `python -c`, "
            "or decodes base64 into a shell. Triggered by Cmd-B / Ctrl-B "
            "on file open. Not covered by JSON-only scanners."
        ),
        pattern=_SUBLIME_BUILD_REMOTE,
        owasp_asi="ASI-06",
        applies_to=_PATH_SUBLIME_BUILD,
    ),
    Rule(
        id="ide-vim-modeline-shell-escape",
        name="Vim modeline shell escape / :call system / :py / :so",
        severity="HIGH",
        description=(
            "First/last few lines of a file carry a Vim modeline "
            "(`vim:` / `vi:` / `ex:`) whose option list includes the "
            "dangerous primitives `:!shell`, `:call system(`, "
            "`:so` / `:source`, embedded `:py` / `:python`, or "
            "`set modelineexpr=1`. Modeline is on by default for "
            "non-root Vim — opening the file = RCE."
        ),
        pattern=_VIM_MODELINE,
        owasp_asi="ASI-06",
        # Vim modelines can live in any file — caller restricts the
        # scan window. Empty applies_to == "everywhere".
        applies_to=(),
    ),
    Rule(
        id="ide-emacs-dir-locals-eval-form",
        name="Emacs .dir-locals.el (eval . (shell-command …))",
        severity="HIGH",
        description=(
            "`.dir-locals.el` contains an `(eval . FORM)` cell where "
            "FORM calls `shell-command`, `call-process`, "
            "`start-process`, `make-process`, `async-shell-command`, "
            "`url-retrieve`, `url-copy-file`, `load-file`, or "
            "`require`. Emacs prompts ONCE per directory; the 'safe' "
            "decision then persists in custom.el and the form silently "
            "re-runs on every later open in that subtree."
        ),
        pattern=_EMACS_DIR_LOCALS_EVAL,
        owasp_asi="ASI-06",
        applies_to=_PATH_EMACS_DIR_LOCALS,
    ),
    Rule(
        id="ide-emacs-dir-locals-safe-eval-bypass",
        name="Emacs .dir-locals.el safe-local-eval-function declaration",
        severity="HIGH",
        description=(
            "`.dir-locals.el` declares "
            "`(safe-local-eval-function 'NAME)` — the attacker pre-"
            "registers an eval form as 'safe', so Emacs stops prompting "
            "the user before honouring it. Companion to the eval-form "
            "rule; this is the consent-bypass shape."
        ),
        pattern=_EMACS_SAFE_LOCAL_EVAL,
        owasp_asi="ASI-07",
        applies_to=_PATH_EMACS_DIR_LOCALS,
    ),
)


# ---- Path-routing helper ------------------------------------------------


# Cache compiled path regexes — one compile per unique path-shape
# across the whole RULES tuple.
_PATH_RE_CACHE: dict[str, re.Pattern] = {}


def _path_re(pattern: str) -> re.Pattern:
    cached = _PATH_RE_CACHE.get(pattern)
    if cached is not None:
        return cached
    compiled = re.compile(pattern, re.IGNORECASE)
    _PATH_RE_CACHE[pattern] = compiled
    return compiled


def rule_applies_to_path(rule: Rule, path: str | None) -> bool:
    """Return True iff `rule` should run against a file at `path`.

    Empty `applies_to` means the rule has no path restriction (Vim
    modeline lives in any file). Passing `path=None` means the caller
    doesn't know the path yet — in that case we run every rule (the
    detector can re-route later).
    """
    if not rule.applies_to:
        return True
    if path is None:
        return True
    return any(_path_re(p).search(path) for p in rule.applies_to)


# ---- The composed scanner -----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _classify_vscode_recommendations(
    text: str, base_rule: Rule,
) -> list[Finding]:
    """Run the inner classifier over each captured recommendation
    string from `.vscode/extensions.json`. Emits one Finding per bad
    entry; the outer regex is just the array-locator."""
    findings: list[Finding] = []
    for m in _VSCODE_EXT_RUG.finditer(text):
        entry = m.group(1) or ""
        if not entry:
            continue
        if not _VSCODE_EXT_RUG_INNER.match(entry):
            continue
        # Compute the offset of the captured string within the file
        # so the reported line/column points at the bad entry, not
        # the array opener.
        offset = m.start(1)
        line, col = _line_col(text, offset)
        # Truncate match text for the finding (long quoted strings
        # blow up the log). Keep the first 200 chars.
        snippet = entry if len(entry) <= 200 else entry[:200] + "…"
        findings.append(Finding(
            rule_id=base_rule.id,
            line=line,
            column=col,
            matched_text=snippet,
            severity=base_rule.severity,
            description=base_rule.description,
            owasp_asi=base_rule.owasp_asi,
        ))
    return findings


def scan_text(
    text: str,
    *,
    path: str | None = None,
    vim_modeline_window: int = 5,
) -> list[Finding]:
    """Run every applicable RULES pattern against `text`.

    Args:
      text: file contents.
      path: optional file path. When given, only rules whose
            `applies_to` matches the path run. Pass None to run every
            rule (the caller does file-routing).
      vim_modeline_window: number of lines at the START and END of
            the file scanned by the Vim modeline rule. The classic
            modeline-attack technique hides the directive in a
            top-of-file or bottom-of-file comment so it's invisible
            in normal scrolling. Default 5 matches Vim's own default
            `modelines=5`.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        if not rule_applies_to_path(rule, path):
            continue
        if rule.id == "ide-vscode-extension-recommendation-rug":
            # Inner-classifier rule — handled separately so each bad
            # entry inside the recommendations array produces its
            # own finding pointing at the right offset.
            for f in _classify_vscode_recommendations(text, rule):
                key = (f.rule_id, f.line, f.column)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(f)
            continue
        if rule.id == "ide-vim-modeline-shell-escape":
            # Vim modelines live in the first / last few lines.
            # Restricting the scan window kills the obvious FP
            # (a documentation file talking about vim: modelines in
            # the middle of its body).
            scan_body = _modeline_window(text, vim_modeline_window)
        else:
            scan_body = text
        for m in rule.pattern.finditer(scan_body):
            # Translate the offset within the window back to the
            # offset within the full text. _modeline_window keeps the
            # leading window at offset 0 and the trailing window at
            # its true offset, so we record both with a tag.
            offset = m.start()
            if rule.id == "ide-vim-modeline-shell-escape":
                offset = _resolve_window_offset(
                    text, offset, vim_modeline_window,
                )
            line, col = _line_col(text, offset)
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


def _modeline_window(text: str, n: int) -> str:
    """Return the first `n` + last `n` lines of `text`, joined with a
    NUL separator so the modeline regex still sees newline boundaries
    on each side without crossing them. The NUL is a deliberate
    discontinuity — Vim modelines can't contain NUL bytes.

    We do NOT rebuild the original offsets here; the caller fixes them
    up via _resolve_window_offset.
    """
    lines = text.splitlines(keepends=True)
    if len(lines) <= 2 * n:
        return text
    head = "".join(lines[:n])
    tail = "".join(lines[-n:])
    return head + "\x00" + tail


def _resolve_window_offset(
    text: str, window_offset: int, n: int,
) -> int:
    """Translate a match offset inside the modeline window back to
    the offset in the original text.

    Layout of the window is:
        [ head_chars ] [ '\\x00' ] [ tail_chars ]
    where head_chars = sum(len(lines[:n])).
    """
    lines = text.splitlines(keepends=True)
    if len(lines) <= 2 * n:
        return window_offset
    head_len = sum(len(line) for line in lines[:n])
    if window_offset < head_len:
        return window_offset
    if window_offset == head_len:
        # The match hit the NUL separator — clamp to start of tail.
        return len(text) - sum(len(line) for line in lines[-n:])
    # Match is in the tail — subtract head_len + 1 (the NUL) to get
    # the tail-local offset, then add the tail's true text offset.
    tail_local = window_offset - head_len - 1
    tail_text_offset = len(text) - sum(len(line) for line in lines[-n:])
    return tail_text_offset + tail_local


def file_kind_for_path(path: str) -> str:
    """Classify a file path into a friendly file_kind string. Useful
    for the detector's report-grouping logic. The IDE-pattern module
    itself uses path-shape regexes from `applies_to`; this is purely
    a convenience for outer callers.
    """
    low = path.lower()
    if low.endswith("/.vscode/extensions.json"):
        return "vscode-extensions"
    if "/.idea/runconfigurations/" in low or low.endswith("/.idea/workspace.xml"):
        return "jetbrains-runconfig"
    if "/.idea/datasources" in low:
        return "jetbrains-datasource"
    if low.endswith("/.editorconfig"):
        return "editorconfig"
    if low.endswith(".sublime-build") or low.endswith(".sublime-project"):
        return "sublime-build"
    if low.endswith("/.dir-locals.el") or low.endswith("/.dir-locals-2.el"):
        return "emacs-dir-locals"
    return "generic"
