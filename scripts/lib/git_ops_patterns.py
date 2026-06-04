"""Git-operation attack patterns (Wave 17, distill round 3, agent C).

Detects attacks at the dev-tool / git-layer that fire on `git clone`,
`git pull`, `git checkout`, `git status`, or `git init` **without the
developer ever running a script themselves** — git does the execution.

Net-new only — does NOT overlap with:
  * the integrated zizmor `git-config-global` rule (gates the WRITE
    side via `git config --global` calls),
  * the `pre-bash-safety` block on `.git/hooks/*` writes (closes the
    direct-hook-write path; this catalogue closes the redirected /
    config-driven paths).

Patterns gated by this module are READ-side: they detect that the
dangerous value is already present on disk, regardless of how it
landed there (install script, malicious dependency, manual edit).

Rules (1:1 with proposals C-1 .. C-8 in distill3-c-git-ops.md):

| id                                    | severity | watched file                |
|---------------------------------------|----------|-----------------------------|
| git-ops-gitattributes-filter          | CRITICAL | `.gitattributes`            |
| git-ops-info-attributes-exists        | HIGH     | `.git/info/attributes`      |
| git-ops-hookspath-redirect            | CRITICAL | `.git/config`, `.gitconfig` |
| git-ops-fsmonitor-custom-binary       | HIGH     | `.git/config`, `.gitconfig` |
| git-ops-gitmodules-suspicious-url     | CRITICAL | `.gitmodules`               |
| git-ops-lfs-custom-smudge             | HIGH     | `.git/config`, `.gitconfig` |
| git-ops-init-templatedir-global       | HIGH     | global git config           |
| git-ops-hook-sample-tampered          | MEDIUM   | `.git/hooks/*.sample`       |

Public surface mirrors `scripts/lib/agent_config_patterns.py`:
  * Rule, Finding NamedTuples
  * RULES — ordered tuple
  * scan_text(text, *, file_kind) — entry point

`file_kind` controls which subset of rules runs:
  * "gitattributes"     → C-1 (and C-6 LFS-filter line) on .gitattributes
  * "git-info-attributes" → C-2 (file content of .git/info/attributes)
  * "git-config"        → C-3, C-4, C-6, C-7 on .git/config / ~/.gitconfig
  * "gitmodules"        → C-5 on .gitmodules
  * "git-hook-sample"   → C-8 on .git/hooks/*.sample
  * "any" (default)     → run every rule; caller filters by file path
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as agent_config_patterns.Finding
    so detectors render either kind uniformly."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str  # may be empty; git-layer attacks don't map cleanly to ASI


class Rule(NamedTuple):
    """A rule definition. Patterns are pre-compiled at import time."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - stdlib name
    owasp_asi: str
    # Which file_kind values this rule applies to. "any" matches every kind.
    applies_to: frozenset[str]


def _re(pattern: str) -> re.Pattern:
    """Compile a regex with MULTILINE+UNICODE. Case-sensitivity matters
    for git config key names (`hooksPath`, `fsmonitor`, etc. are
    case-sensitive in the gitconfig grammar — `HooksPath` is NOT the
    same key), so IGNORECASE is deliberately omitted."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- Proposal C-1: .gitattributes smudge/clean filter directive --------


# Matches a `.gitattributes` line declaring a filter attribute. The line
# shape is `<pattern> filter=<name>` optionally with other attributes.
# Anchored at start-of-line (after whitespace) and the comment-line
# rejection `[^\s#]` ensures we skip blank lines + comments. The
# capture group lets the detector verify against the allowlist
# (`lfs`, `crlf`, `ident`).
_GITATTRIBUTES_FILTER = _re(
    r"^[ \t]*[^\s#].*?[ \t]filter[ \t]*=[ \t]*([A-Za-z0-9_.-]+)"
)


# ---- Proposal C-2: .git/info/attributes content scan -------------------


# Same shape as C-1, but the rule_id differs so detectors can route
# severity / remediation copy independently. The file-existence trigger
# is in the caller (presence of a non-zero-byte file); this regex
# verifies the content actually carries a filter directive.
_GIT_INFO_ATTRIBUTES_FILTER = _re(
    r"^[ \t]*[^\s#].*?[ \t]filter[ \t]*=[ \t]*([A-Za-z0-9_.-]+)"
)


# ---- Proposal C-3: core.hooksPath redirect -----------------------------


# Inside a `[core]` section, `hooksPath = <path>` redirects all hooks.
# We match the key/value on its own — section-awareness is handled by
# the caller doing the scan_text(file_kind="git-config") call (the
# whole config file is fed in, the regex picks up the line).
# The default state is NO `hooksPath` line at all, so any non-empty
# value is a finding. Captures the destination path so detectors can
# tier severity (in-repo path = CRITICAL, ~/.git-hooks = HIGH).
_HOOKSPATH_REDIRECT = _re(
    r"^[ \t]*hooksPath[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$"
)


# ---- Proposal C-4: core.fsmonitor pointing at a custom binary ----------


# Capture EVERY `fsmonitor = <value>` line; the post-match gate in
# scan_text rejects `true`/`false` (the safe IPC-builtin values).
# Negative-lookahead in the regex itself was defeated by backtracking
# (the engine collapsed `[ \t]*` to zero chars to make the lookahead's
# anchor mismatch). A Python-side allowlist gate is both simpler to
# reason about and exhaustively unit-testable.
_FSMONITOR_CUSTOM = _re(
    r"^[ \t]*fsmonitor[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$"
)


# Values that mean "use git's built-in IPC fsmonitor" — anything else
# is a custom-binary execution primitive.
_FSMONITOR_SAFE_VALUES = frozenset({"true", "false"})


# ---- Proposal C-5: .gitmodules suspicious url --------------------------


# Captures `url = <value>` lines inside `.gitmodules`. The detector then
# applies the suspicious-URL gate to the captured value.
# Compiled as two separate patterns: the URL extractor + the danger gate
# tested against the capture group. Keeping them separate lets the unit
# tests assert the gate independently of the line shape.
_GITMODULES_URL = _re(
    r"^[ \t]*url[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$"
)

# Danger gate: file:// scheme, absolute Unix path, absolute Windows path,
# UNC path, argv-injection via leading `-` in the host, or hostnames
# containing shell metacharacters. The detector loops over _GITMODULES_URL
# matches and runs each capture through this regex.
_GITMODULES_URL_DANGER = re.compile(
    r"^(?:"
    r"file://"                    # local file scheme
    r"|/"                         # absolute Unix path (single char)
    r"|[A-Za-z]:[\\/]"            # absolute Windows path (C:\, C:/, ...)
    r"|\\\\"                      # UNC path (\\server\share)
    r"|(?:ssh|git|https?)://-"    # argv-injection on host
    r")"
)

# Hostname plausibility check — anything matching this is SAFE (passes
# the regex above's "first char not -" gate AND has a normal hostname).
# Used by the detector to short-circuit `https://github.com/...` etc.
_GITMODULES_HOSTNAME_OK = re.compile(
    r"^(?:[A-Za-z]+://|git@)[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9](?:[:/]|$)"
)


# ---- Proposal C-6: git lfs custom smudge command -----------------------


# Step 1: locate the `[filter "lfs"]` section header. The section header
# itself is harmless; we use it to bracket the next set of `smudge`,
# `clean`, `process` keys.
_LFS_SECTION_HEADER = _re(
    r'^[ \t]*\[filter[ \t]+"lfs"\][ \t]*$'
)

# Any git-config section header line — `[section]` or `[section "sub"]`,
# possibly leading-indented. Used to bracket the END of an LFS section: a
# `smudge`/`clean`/`process` key only belongs to `[filter "lfs"]` if it
# appears AFTER the lfs header and BEFORE the next section header.
_ANY_SECTION_HEADER = _re(
    r"^[ \t]*\[[^\]\r\n]*\][ \t]*$"
)

# Step 2: any `smudge|clean|process` value inside the LFS block that
# diverges from the canonical command is a finding. The canonical
# values (`git-lfs smudge -- %f`, `git-lfs clean -- %f`,
# `git-lfs filter-process`) are validated in the detector against the
# capture group. Older LFS variant `git-lfs smudge %f` (no `--`) is
# also allowed.
_LFS_FILTER_VALUE = _re(
    r"^[ \t]*(smudge|clean|process)[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$"
)

# Canonical-value verifier — passed when the value matches one of the
# LFS install's three legitimate forms (with or without the `--`).
_LFS_CANONICAL_VALUES = re.compile(
    r"^(?:"
    r"git-lfs[ \t]+smudge(?:[ \t]+--)?[ \t]+%f"
    r"|git-lfs[ \t]+clean(?:[ \t]+--)?[ \t]+%f"
    r"|git-lfs[ \t]+filter-process"
    r")[ \t]*$"
)


# ---- Proposal C-7: init.templateDir planted in global config -----------


# `templateDir = <path>` inside `[init]` section. Any non-empty value is
# a finding because the default git install does NOT write this key —
# absence is the canonical state. The detector tiers severity based on
# whether the captured path is one of the known-safe template dirs
# (system / Homebrew / Apple-Silicon Homebrew).
_INIT_TEMPLATEDIR = _re(
    r"^[ \t]*templateDir[ \t]*=[ \t]*([^\r\n]+?)[ \t]*$"
)

# Known-safe template directories — the detector skips findings whose
# captured path matches one of these exactly.
_INIT_TEMPLATEDIR_SAFE = frozenset({
    "/usr/share/git-core/templates",
    "/usr/local/share/git-core/templates",
    "/opt/homebrew/share/git-core/templates",
})


# ---- Proposal C-8: .git/hooks/*.sample tampered shebang ----------------


# Canonical shebang line for every git-shipped `.sample` file. Anything
# else is a tampering finding. The regex anchors at the start-of-file
# (caller passes the file content, not a stream of files).
_SAMPLE_SHEBANG_CANONICAL = re.compile(
    r"\A#!\s*(?:/bin/sh|/bin/bash|/usr/bin/env\s+(?:sh|bash|perl|python3?))\s*$",
    re.MULTILINE,
)

# Body-content gate — patterns that should NEVER appear in a `.sample`
# file because the file is supposed to be an inert template.
_SAMPLE_BODY_DANGER = _re(
    r"\bcurl\b[^\n|]{0,200}\|[ \t]*(?:sh|bash)\b"
    r"|\bwget\b[^\n|]{0,200}\|[ \t]*(?:sh|bash)\b"
    r"|\bbase64[ \t]+-d\b[^\n|]{0,200}\|[ \t]*(?:sh|bash)\b"
    r"|\beval[ \t]*\"\$\("
)


# ---- The catalogue ------------------------------------------------------


# Rule ordering = severity DESC then proposal order, so the first
# finding rendered to a developer is also the most severe.
RULES: tuple[Rule, ...] = (
    Rule(
        id="git-ops-gitattributes-filter",
        name="`.gitattributes` declares a smudge/clean filter",
        severity="CRITICAL",
        description=(
            "`.gitattributes` declares a `filter=<name>` attribute. Paired "
            "with a configured `filter.<name>.smudge` shell command, every "
            "`git checkout` runs the attacker's code. Allowlisted: lfs, "
            "crlf, ident. CVE class: CVE-2024-32002 family."
        ),
        pattern=_GITATTRIBUTES_FILTER,
        owasp_asi="",
        applies_to=frozenset({"gitattributes", "any"}),
    ),
    Rule(
        id="git-ops-info-attributes-exists",
        name="`.git/info/attributes` carries a filter directive",
        severity="HIGH",
        description=(
            "`.git/info/attributes` is the per-clone local-only override "
            "for `.gitattributes`. It is invisible to PR review and to "
            "`git status`. A filter directive here is supply-chain "
            "injection that landed via a dependency installer."
        ),
        pattern=_GIT_INFO_ATTRIBUTES_FILTER,
        owasp_asi="",
        applies_to=frozenset({"git-info-attributes", "any"}),
    ),
    Rule(
        id="git-ops-hookspath-redirect",
        name="`core.hooksPath` redirects git hooks to a non-default path",
        severity="CRITICAL",
        description=(
            "`core.hooksPath` redirects every lifecycle hook (pre-commit, "
            "post-checkout, post-merge, pre-push) to a chosen directory. "
            "When the directory is in-tree (./scripts, ./.husky), the "
            "attacker controls the hooks via PR and the redirection "
            "lives in `.git/config` which is never reviewed."
        ),
        pattern=_HOOKSPATH_REDIRECT,
        owasp_asi="",
        applies_to=frozenset({"git-config", "any"}),
    ),
    Rule(
        id="git-ops-fsmonitor-custom-binary",
        name="`core.fsmonitor` points at a custom binary",
        severity="HIGH",
        description=(
            "`core.fsmonitor` is git's hook for delegating filesystem-change "
            "detection. Git invokes it on every `git status` and every "
            "tree-walking operation. Built-in IPC fsmonitor (`true`/`false`) "
            "is safe; any path or bare command name is a custom-binary "
            "execution primitive."
        ),
        pattern=_FSMONITOR_CUSTOM,
        owasp_asi="",
        applies_to=frozenset({"git-config", "any"}),
    ),
    Rule(
        id="git-ops-gitmodules-suspicious-url",
        name="`.gitmodules` URL has a suspicious scheme or argv-injection",
        severity="CRITICAL",
        description=(
            "`.gitmodules` URL uses `file://`, absolute path, UNC path, or "
            "has a leading `-` in the host (argv injection). Sources: "
            "CVE-2018-17456 (`ssh://-oProxyCommand=...`), CVE-2022-39253 "
            "(`url = file:///home/victim/.ssh`), CVE-2024-32002 (symlink + "
            "submodule -> hook execution on clone)."
        ),
        pattern=_GITMODULES_URL,
        owasp_asi="",
        applies_to=frozenset({"gitmodules", "any"}),
    ),
    Rule(
        id="git-ops-lfs-custom-smudge",
        name="`filter.lfs.{smudge,clean,process}` diverges from canonical",
        severity="HIGH",
        description=(
            "Git LFS install writes three canonical filter commands. Any "
            "divergence is a smudge-hijack: the attacker swapped the real "
            "`git-lfs` binary for an attacker-supplied script that LFS "
            "runs on every checkout of an LFS-tracked blob."
        ),
        pattern=_LFS_FILTER_VALUE,
        owasp_asi="",
        applies_to=frozenset({"git-config", "any"}),
    ),
    Rule(
        id="git-ops-init-templatedir-global",
        name="`init.templateDir` set in global git config",
        severity="HIGH",
        description=(
            "`init.templateDir` is the directory git copies from on `git "
            "init`. A planted value means every new repo the developer "
            "creates is born with attacker-controlled hooks already in "
            "`.git/hooks/`. System / Homebrew defaults are allowlisted."
        ),
        pattern=_INIT_TEMPLATEDIR,
        owasp_asi="",
        applies_to=frozenset({"git-config", "any"}),
    ),
    Rule(
        id="git-ops-hook-sample-tampered",
        name="`.git/hooks/*.sample` has non-canonical shebang or shell-pipe payload",
        severity="MEDIUM",
        description=(
            "Every git-shipped `.git/hooks/*.sample` file has a canonical "
            "shebang (`/bin/sh`, `/bin/bash`, `/usr/bin/env perl`). Any "
            "other shebang or any `curl|sh` / `wget|sh` / `base64 -d|sh` "
            "body pattern is tampering — the file is supposed to be an "
            "inert template, never to ship payload."
        ),
        pattern=_SAMPLE_BODY_DANGER,
        owasp_asi="",
        applies_to=frozenset({"git-hook-sample", "any"}),
    ),
)


# ---- Helper exports for callers that want to gate captures -------------


def is_lfs_canonical(value: str) -> bool:
    """Return True if `value` is one of the canonical LFS filter command
    strings (`git-lfs smudge -- %f`, `git-lfs clean -- %f`,
    `git-lfs filter-process`, plus the older no-`--` variant)."""
    return _LFS_CANONICAL_VALUES.match(value) is not None


def is_gitmodules_url_dangerous(url: str) -> bool:
    """Return True if a `.gitmodules` URL matches the danger gate
    (file://, absolute path, UNC, argv-injection on host)."""
    url = url.strip()
    if not url:
        return False
    if _GITMODULES_URL_DANGER.match(url):
        return True
    # Last-resort hostname plausibility check for the http(s)/git/ssh
    # schemes that didn't trip the danger gate.
    if "://" in url or url.startswith("git@"):
        return _GITMODULES_HOSTNAME_OK.match(url) is None
    # Anything else (no scheme, no `git@`) is suspicious — submodule URLs
    # are supposed to be fully-qualified.
    return True


def is_gitattributes_filter_allowed(filter_name: str) -> bool:
    """Return True for the three filter names that ship in git itself
    (`lfs`, `crlf`, `ident`). Everything else is a finding."""
    return filter_name in {"lfs", "crlf", "ident"}


def is_init_templatedir_safe(path: str) -> bool:
    """Return True if `path` matches one of the system / Homebrew
    template-directory defaults."""
    return path.strip().rstrip("/") in _INIT_TEMPLATEDIR_SAFE


def has_canonical_sample_shebang(content: str) -> bool:
    """Return True if the `.sample` file's first line is one of the
    canonical git-shipped shebangs."""
    if not content:
        return False
    return _SAMPLE_SHEBANG_CANONICAL.match(content) is not None


def has_lfs_section(content: str) -> bool:
    """Return True if the gitconfig content contains a `[filter "lfs"]`
    section header. Used by the LFS-filter rule to decide whether to
    apply canonical-value gating."""
    return _LFS_SECTION_HEADER.search(content) is not None


def _lfs_section_spans(text: str) -> list[tuple[int, int]]:
    """Return [start, end) offset ranges covering every `[filter "lfs"]` body.

    A git-config section runs from the end of its header line until the
    next section header (any `[...]` line) or end-of-text. The LFS rule
    only treats a `smudge`/`clean`/`process` key as an LFS filter command
    when its match offset falls inside one of these spans — a custom,
    NON-lfs filter (`[filter "myredact"]`) with its own smudge command is
    a different finding class and must NOT be reported as an LFS hijack.
    """
    headers = [(m.start(), m.end()) for m in _ANY_SECTION_HEADER.finditer(text)]
    spans: list[tuple[int, int]] = []
    for idx, (h_start, h_end) in enumerate(headers):
        if _LFS_SECTION_HEADER.match(text, h_start) is None:
            continue
        # Body starts right after this header line and ends at the next
        # section header (whichever it is) or EOF.
        body_start = h_end
        body_end = headers[idx + 1][0] if idx + 1 < len(headers) else len(text)
        spans.append((body_start, body_end))
    return spans


def _offset_in_spans(offset: int, spans: list[tuple[int, int]]) -> bool:
    """True if `offset` lies within any [start, end) span."""
    return any(start <= offset < end for start, end in spans)


# ---- Scanner ------------------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str, *, file_kind: str = "any") -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` selects which rule subset to apply (mirrors the
    file-on-disk routing the heartbeat detector does):

    * `gitattributes`        — `.gitattributes` content
    * `git-info-attributes`  — `.git/info/attributes` content
    * `git-config`           — `.git/config`, `~/.gitconfig`, system config
    * `gitmodules`           — `.gitmodules`
    * `git-hook-sample`      — body of a `.git/hooks/*.sample` file
    * `any` (default)        — run every rule; caller is responsible for
                                routing by file path
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    # Computed lazily the first time the LFS rule needs it (None = not yet).
    lfs_spans: list[tuple[int, int]] | None = None

    for rule in RULES:
        if file_kind != "any" and file_kind not in rule.applies_to:
            continue
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            # Apply rule-specific allowlist gates against the capture group.
            # These gates are NOT in the regex itself because they would
            # bloat the pattern and harm testability; gating in Python is
            # clearer and lets unit tests assert each gate independently.
            captured = m.group(1) if m.groups() else ""
            if rule.id == "git-ops-gitattributes-filter":
                if is_gitattributes_filter_allowed(captured):
                    continue
            elif rule.id == "git-ops-info-attributes-exists":
                if is_gitattributes_filter_allowed(captured):
                    continue
            elif rule.id == "git-ops-init-templatedir-global":
                if is_init_templatedir_safe(captured):
                    continue
            elif rule.id == "git-ops-fsmonitor-custom-binary":
                if captured.strip() in _FSMONITOR_SAFE_VALUES:
                    continue
            elif rule.id == "git-ops-gitmodules-suspicious-url":
                if not is_gitmodules_url_dangerous(captured):
                    continue
            elif rule.id == "git-ops-lfs-custom-smudge":
                # Section-gate FIRST: a smudge/clean/process key is only an
                # LFS-filter command when it lives inside a `[filter "lfs"]`
                # block. A custom NON-lfs filter (`[filter "myredact"]`) with
                # its own smudge command is a different finding class and must
                # NOT be mislabelled as an LFS-binary swap. Without this gate
                # the rule fired on every custom filter section.
                if lfs_spans is None:
                    lfs_spans = _lfs_section_spans(text)
                if not _offset_in_spans(m.start(), lfs_spans):
                    continue
                # Inside an LFS section: the second capture is the command
                # value; canonical LFS commands are allowlisted.
                if len(m.groups()) >= 2:
                    value = m.group(2)
                    if is_lfs_canonical(value):
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
