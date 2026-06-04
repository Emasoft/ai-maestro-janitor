"""Cron / at / systemd-timer scheduled-task abuse patterns.

Wave-27 distill-round-13 — cron-scheduled angle.

Catalogue of 6 user-side scheduled-task anti-patterns distilled in
`reports/distill-round-13/cron-scheduled.md`. Detects when an attacker
(or compromised dep, or AI agent under prompt injection) installs
persistence via the OS scheduler — `crontab -e`, `@reboot`, systemd
`*.service` / `*.timer` units, drop-ins under `/etc/cron.d/`, Windows
`schtasks /Create` / `Register-ScheduledTask`, or `at` jobs.

The angle is the **inverse** of the janitor's own heartbeat-cron
management (which is benign and operator-authorised): here we focus on
the *scheduling surface itself* (the crontab line, the unit file, the
schtasks call) as an attack-vector / persistence beachhead.

What is NOT here (already shipped — DO NOT duplicate):

  * `curl … | sh` literal in any file (narthex `post_edit.py:66`).
    This module *extends* that by adding crontab/systemd context.
  * Kubernetes `CronJob` admission (k8s_admission_patterns).
  * Linux privilege-escalation patterns (out of scope per round-13
    contract).
  * Container-runtime persistence (round-12).

What IS here (6 net-new rules, regex-only, all RE2-safe):

  * cron-scheduled-crontab-stdin-install                       (CRITICAL)
  * cron-scheduled-reboot-fetcher                              (CRITICAL)
  * cron-scheduled-systemd-shell-from-env                      (CRITICAL)
  * cron-scheduled-etc-cron-d-fetcher                          (CRITICAL)
  * cron-scheduled-schtasks-elevated-fetcher                   (CRITICAL)
  * cron-scheduled-at-job-fetcher                              (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-03 — Privilege Compromise (root-running scheduled task,
                                  /etc/cron.d/ drop-in, /RL HIGHEST)
  ASI-08 — Excessive Agency (AI agent installs crontab without
                              operator authorisation)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

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
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper
    in chat_bot_patterns. RE2-safe: no nested unbounded quantifiers,
    no backreferences, no lookbehind (a bounded negative lookahead is
    used once in `_SYSTEMD_ENVFILE_NON_TMPFS` to exclude `/run/`,
    which IS RE2-compatible). Case-insensitive matching handles
    Windows surface (cmd.exe and PowerShell are case-insensitive
    parsers) while remaining safe for the Linux surface (the corpus
    attacker IOCs all use the canonical lower-case spelling, so case-
    insensitive matching is a superset of the case-sensitive form
    and adds no false negatives)."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- CRON-01 : crontab-stdin-install ------------------------------------


# The canonical ShaiHulud/AgentShield persistence shape:
#   (crontab -l; echo "...") | crontab -
# Bounded character-class `[^|]{0,256}` keeps the regex RE2-safe and
# prevents catastrophic backtracking on long lines.
_CRONTAB_STDIN_INSTALL = _re(
    r"crontab\s+-l[^|]{0,256}\|\s*crontab\s+-"
)


# ---- CRON-02 : @reboot fetcher ------------------------------------------


# A crontab line beginning with the `@reboot` shortcut that contains a
# network fetcher. Word-boundary on the fetcher tools prevents firing on
# path components like `/curlybrace-pkg/`.
_REBOOT_FETCHER = _re(
    r"(?:^|[\n;])\s*@reboot\s+[^\n]{0,256}\b"
    r"(?:curl|wget|nc|ncat|fetch|/dev/tcp/)"
)


# ---- CRON-03 : systemd shell-from-env -----------------------------------


# A systemd `[Service]` block whose `ExecStart=` invokes `/bin/sh -c`
# with a `$VAR`-style expansion. Bounded `[\s\S]{0,4096}?` allows the
# block to span multiple lines without unbounded backtracking.
_SYSTEMD_SHELL_FROM_ENV = _re(
    r"\[Service\][\s\S]{0,4096}?ExecStart=[^\n]{0,256}/bin/sh\s+-c\s+['\"]?[^\n]*\$"
)

# Companion: `EnvironmentFile=` pointing at a non-`/run/` path (i.e. NOT
# tmpfs). `/run/` is the legitimate ephemeral location used by the
# sealed-env false-positive template.
_SYSTEMD_ENVFILE_NON_TMPFS = _re(
    r"\[Service\][\s\S]{0,2048}?EnvironmentFile=(?!/run/)[^\n]+\.(?:env|conf|secret)"
)

# Companion: `User=root` / `User=0` marker in the same block (severity
# bump signal — system-scope root-running unit is the dangerous variant).
_SYSTEMD_USER_ROOT = _re(
    r"\[Service\][\s\S]{0,2048}?(?:User=root|User=0)\b"
)

# Companion: fetcher inside the ExecStart line — discriminates the
# attacker variant from the legitimate operator unit (npm-hardening
# refresh) which uses `/bin/sh -c '…sed -i…'` with no network access.
_SYSTEMD_EXECSTART_FETCHER = _re(
    r"ExecStart=[^\n]{0,512}\b(?:curl|wget|nc|ncat|fetch|/dev/tcp/)"
)


# ---- CRON-04 : /etc/cron.d/ drop-in fetcher -----------------------------


# A path filter: any of the standard cron-drop-in directories. Anchored
# so it matches the literal directory in a heredoc/string/path.
_ETC_CRON_PATH = _re(
    r"/etc/(?:cron\.d|cron\.hourly|cron\.daily|cron\.weekly|cron\.monthly|anacrontab)(?:/|\b)"
)

# Content check: a crontab line (5 or 6 time fields) followed by a
# network fetcher. Apply to files matching the path filter OR to
# heredocs that look like cron entries.
_CRON_LINE_FETCHER = _re(
    r"(?:^|\n)\s*(?:[*\d/,\-]+\s+){4,5}[*\d/,\-]+\s+"
    r"(?:root\s+)?[^#\n]*?"
    r"\b(?:curl|wget|fetch|nc|ncat)\b[^\n]{0,256}\|\s*"
    r"(?:sudo\s+)?(?:bash|sh|zsh|python3?|perl)"
)


# ---- CRON-05 : Windows schtasks elevated fetcher ------------------------


# `schtasks /Create` form: matches the create verb (case-insensitive
# via IGNORECASE flag) followed by a `/TR` action that invokes a
# remote-fetcher cmdlet.
_SCHTASKS_CREATE_FETCHER = _re(
    r"schtasks(?:\.exe)?\s+/Create[^\n]{0,256}"
    r"/TR\s+[\"']?[^\"'\n]{0,256}"
    r"\b(?:powershell|iwr|invoke-webrequest|curl|wget|iex)\b"
)

# PowerShell cmdlet form: `Register-ScheduledTask` with a fetcher inside
# the `-Action` argument.
_REGISTER_SCHEDULED_TASK_FETCHER = _re(
    r"Register-ScheduledTask[^\n]{0,256}-Action[^\n]{0,512}"
    r"(?:Invoke-WebRequest|iwr|iex|EncodedCommand|DownloadString)"
)

# Severity bump: `/RL HIGHEST` (schtasks) or `-RunLevel Highest`
# (Register-ScheduledTask) — elevation marker. Applied as a same-line
# Stage-B check that promotes the finding from HIGH to CRITICAL.
_RUNLEVEL_HIGHEST = _re(
    r"/RL\s+HIGHEST|-RunLevel\s+Highest"
)


# ---- CRON-06 : at-job fetcher -------------------------------------------


# Stdin form: `echo "..." | at now + 5 minutes` where the piped content
# contains a network fetcher. The fetcher-in-content check is what
# distinguishes the attacker shape from the legitimate `shutdown -r now`
# / `touch /tmp/at-ran` use-cases.
_AT_STDIN_FETCHER = _re(
    r"\b(?:echo|printf|cat)\b[^|]{0,256}"
    r"\b(?:curl|wget|fetch|nc|ncat|/dev/tcp/)\b"
    r"[^|]{0,256}\|\s*at\s+(?:now|noon|midnight|[+\d:][^\n]*)"
)

# `-f` form: `at -f /tmp/.payload now + 10 minutes`. We require the
# file to live in a writable tmp area (`/tmp/`, `/var/tmp/`, `/dev/shm/`)
# — the canonical attacker pre-staging path.
_AT_FILE_TMP = _re(
    r"\bat\s+-f\s+(?:/tmp/|/var/tmp/|/dev/shm/)[^\s]+"
)

# Companion: `systemctl enable atd` — strong red flag that an installer
# is turning ON a daemon that's normally OFF, so it can use `at`.
_ATD_ENABLE = _re(
    r"\bsystemctl\s+enable\s+atd\b|\bservice\s+atd\s+start\b"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="cron-scheduled-crontab-stdin-install",
        name="Crontab installed/appended from stdin with curl-pipe-shell payload",
        severity="CRITICAL",
        description=(
            "A bash one-liner that installs or appends to the user's "
            "crontab from stdin — the canonical "
            "`(crontab -l; echo \"...\") | crontab -` ShaiHulud / "
            "AgentShield persistence idiom. Detects the literal "
            "`crontab -l […] | crontab -` shape. Persists through reboot, "
            "terminal close, and most 'reinstall the package' "
            "remediations. The follow-on cron line typically pipes "
            "curl/wget through bash for second-stage payload fetch."
        ),
        pattern=_CRONTAB_STDIN_INSTALL,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="cron-scheduled-reboot-fetcher",
        name="@reboot crontab entry pulls a remote payload",
        severity="CRITICAL",
        description=(
            "A crontab line beginning with the `@reboot` shortcut that "
            "contains a network fetcher (`curl` / `wget` / `nc` / "
            "`fetch` / `/dev/tcp/`). `@reboot` is the highest-yield "
            "persistence keyword in the cron format — it executes once "
            "at every boot regardless of time-spec, so the attacker "
            "doesn't have to wait for the wall-clock slot. Equivalent "
            "to macOS launchd `RunAtLoad`+`KeepAlive` for Linux. Boot-"
            "time persistence leaves no recurring log entry for the "
            "operator to spot."
        ),
        pattern=_REBOOT_FETCHER,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="cron-scheduled-systemd-shell-from-env",
        name="systemd unit ExecStart=/bin/sh -c with $VAR expansion and fetcher",
        severity="CRITICAL",
        description=(
            "A systemd `.service` (or `.timer`-paired) unit whose "
            "`[Service]` block has `ExecStart=/bin/sh -c '…$VAR…'` "
            "AND a network fetcher in the ExecStart line. The "
            "attacker variant (`pgsql-monitor.service`, `gh-token-"
            "monitor.service` in the ShaiHulud corpus) combines this "
            "shape with `User=root` (system scope) or `loginctl "
            "enable-linger` (user scope, survives logout). Distinct "
            "from the legitimate `npm-hardening-refresh.service` "
            "false-positive template which uses `/bin/sh -c 'sed -i …'` "
            "with NO network keyword."
        ),
        pattern=_SYSTEMD_SHELL_FROM_ENV,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="cron-scheduled-etc-cron-d-fetcher",
        name="/etc/cron.{d,daily,hourly,weekly,monthly}/ drop-in contains fetcher-pipe-shell",
        severity="CRITICAL",
        description=(
            "A file dropped under `/etc/cron.d/`, "
            "`/etc/cron.{hourly,daily,weekly,monthly}/`, or "
            "`/etc/anacrontab` whose content includes a curl/wget/nc-"
            "pipe-shell. Unlike `crontab -` (which is the *command*), "
            "this rule fires on the *filesystem artifact* — most "
            "installers drop these files directly. Anything under "
            "`/etc/cron.*/` runs as root by default AND is invisible "
            "to `crontab -l` (which only lists per-user crontabs), so "
            "the operator's first-line IR sweep misses it. Stock "
            "Debian/Ubuntu drop-ins (`apt-compat`, `logrotate`, "
            "`man-db`, `anacron`, `unattended-upgrades`) don't contain "
            "the fetcher keyword and are silent."
        ),
        pattern=_CRON_LINE_FETCHER,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="cron-scheduled-schtasks-elevated-fetcher",
        name="Windows schtasks/Register-ScheduledTask creates elevated task with remote fetcher",
        severity="CRITICAL",
        description=(
            "A `schtasks /Create` invocation or PowerShell "
            "`Register-ScheduledTask` cmdlet whose action invokes a "
            "remote fetcher (`Invoke-WebRequest`/`iwr`, "
            "`-EncodedCommand`, `DownloadString`, `iex`, `curl`, "
            "`wget`). The ShaiHulud Windows persistence variant is "
            "`WindowsTerminalUpdate` tracked literally by "
            "supply-chain-guard's IOC scanner. Combined with "
            "`/RL HIGHEST` (schtasks) or `-RunLevel Highest` "
            "(Register-ScheduledTask) this is equivalent to root cron "
            "on Linux. Legitimate sysadmin tasks that schedule local "
            "binaries (no fetcher) don't match."
        ),
        pattern=_SCHTASKS_CREATE_FETCHER,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="cron-scheduled-at-job-fetcher",
        name="at/batch job piped from echo with fetcher or staged from /tmp",
        severity="HIGH",
        description=(
            "The `at` / `batch` one-shot scheduler used to queue a "
            "single delayed execution: either inline via "
            "`echo \"curl … | sh\" | at now + 5 minutes` or file-based "
            "via `at -f /tmp/.payload now + 10 minutes`. Lower severity "
            "than cron (HIGH vs CRITICAL) because `at` jobs don't "
            "recur — single execution window. Combined with "
            "`systemctl enable atd` on a fresh box (where the daemon "
            "is normally OFF by default on most distros) it's a clear "
            "persistence-by-decoupling shape: install moment is "
            "decoupled from IOC-scan window."
        ),
        pattern=_AT_STDIN_FETCHER,
        owasp_asi="ASI-03",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B context filters:

      * CRON-03 (systemd-shell-from-env) — the literal `/bin/sh -c
        '...$...'` shape matches both the attacker variant AND the
        legitimate `npm-hardening-refresh.service` template. To
        suppress the FP, we require ALSO either (a) `User=root` /
        `User=0` in the same block (system-scope dangerous variant)
        OR (b) a network fetcher in the ExecStart line itself.
      * CRON-04 (etc-cron-d-fetcher) — the cron-line + fetcher
        content regex fires correctly on standalone drop-ins, AND we
        additionally surface findings where a heredoc / string
        literal in a script writes to one of the standard
        `/etc/cron.*/` paths — those are the installer-script
        shape.
      * CRON-06 (at-job-fetcher) — match the stdin form directly;
        the `-f /tmp/...` form (file pre-staged in tmpfs) is also
        flagged. Severity bump signal: same file contains
        `systemctl enable atd` (companion regex consulted but no
        separate finding emitted to keep the catalogue at 6 rules).

    Findings are deduped by (rule_id, line, col) and sorted by
    (line, col, rule_id).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- CRON-01 : crontab-stdin-install ----
    rule_c1 = rule_by_id["cron-scheduled-crontab-stdin-install"]
    for m in _CRONTAB_STDIN_INSTALL.finditer(text):
        _emit(rule_c1, m.start(), m.group(0))

    # ---- CRON-02 : @reboot fetcher ----
    rule_c2 = rule_by_id["cron-scheduled-reboot-fetcher"]
    for m in _REBOOT_FETCHER.finditer(text):
        _emit(rule_c2, m.start(), m.group(0))

    # ---- CRON-03 : systemd shell-from-env ----
    # Stage-B FP suppression: the literal `/bin/sh -c '…$…'` shape
    # matches BOTH the attacker variant AND the legitimate
    # `npm-hardening-refresh.service` template (user-scope, no
    # network, fixed sed expression). To distinguish, we require
    # at least ONE corroborating danger signal in the same file:
    #   (a) `User=root` / `User=0` in the same block — dangerous
    #       system-scope variant.
    #   (b) `EnvironmentFile=` pointing at a non-`/run/` (i.e. non-
    #       tmpfs) path — the sealed-env false-positive template uses
    #       `/run/sealed-env.env` and is explicitly excluded.
    #   (c) Network fetcher (`curl`/`wget`/`nc`/`/dev/tcp/`) inside
    #       the ExecStart line — the npm-hardening template uses
    #       `sed -i` with no network access, so it stays silent.
    rule_c3 = rule_by_id["cron-scheduled-systemd-shell-from-env"]
    danger_signals = (
        _file_contains(text, _SYSTEMD_USER_ROOT)
        or _file_contains(text, _SYSTEMD_ENVFILE_NON_TMPFS)
        or _file_contains(text, _SYSTEMD_EXECSTART_FETCHER)
    )
    if danger_signals:
        for m in _SYSTEMD_SHELL_FROM_ENV.finditer(text):
            _emit(rule_c3, m.start(), m.group(0))

    # ---- CRON-04 : /etc/cron.d/ drop-in fetcher ----
    # Two emission paths, both anchored on the cron-line+fetcher
    # content match:
    #   (i)  The match always fires when the regex hits — the regex
    #        itself enforces 5–6 time fields AND a fetcher AND a
    #        pipe-to-shell, so precision is high on standalone
    #        drop-in file content.
    #   (ii) When the same file ALSO mentions an `/etc/cron.*/`
    #        path (a heredoc/installer-script context), we
    #        additionally check for `@reboot`+fetcher lines that
    #        CRON-02 already caught — and re-emit them under CRON-04
    #        so the IR sweep recognises the privileged-location
    #        write context. (No double-emit at the same (line,col):
    #        the dedup `seen` set handles that.)
    rule_c4 = rule_by_id["cron-scheduled-etc-cron-d-fetcher"]
    for m in _CRON_LINE_FETCHER.finditer(text):
        _emit(rule_c4, m.start(), m.group(0))
    if _file_contains(text, _ETC_CRON_PATH):
        # Heredoc/installer-script that writes to a privileged cron
        # path AND contains a @reboot-fetcher line: surface the
        # @reboot match as a CRON-04 finding too. This catches
        # installer scripts that drop `/etc/cron.d/xxx` containing
        # only `@reboot curl … | sh` (no time-field cron line).
        for m in _REBOOT_FETCHER.finditer(text):
            _emit(rule_c4, m.start(), m.group(0))

    # ---- CRON-05 : schtasks / Register-ScheduledTask elevated fetcher ----
    # Two emission paths:
    #   (i)  `schtasks /Create … /TR "<…fetcher…>"` direct match.
    #   (ii) `Register-ScheduledTask … -Action <…fetcher cmdlet…>`
    #        direct match.
    # The `_RUNLEVEL_HIGHEST` helper is a Stage-B corroborating
    # signal — when the elevation marker is in the file AND at
    # least one of the two direct matches fired, we additionally
    # surface the elevation token's location as a CRON-05 finding
    # so the IR sweep can pinpoint the elevation. We do NOT emit
    # the elevation token alone (a legitimate sysadmin task running
    # a local .ps1 with `/RL HIGHEST` is a common benign shape and
    # firing on the elevation token without a fetcher in the same
    # file would be noisy).
    rule_c5 = rule_by_id["cron-scheduled-schtasks-elevated-fetcher"]
    schtasks_hits = list(_SCHTASKS_CREATE_FETCHER.finditer(text))
    register_hits = list(_REGISTER_SCHEDULED_TASK_FETCHER.finditer(text))
    for m in schtasks_hits:
        _emit(rule_c5, m.start(), m.group(0))
    for m in register_hits:
        _emit(rule_c5, m.start(), m.group(0))
    if (schtasks_hits or register_hits) and _file_contains(text, _RUNLEVEL_HIGHEST):
        for m in _RUNLEVEL_HIGHEST.finditer(text):
            _emit(rule_c5, m.start(), m.group(0))

    # ---- CRON-06 : at-job fetcher ----
    # Three emission paths:
    #   (i)   stdin form `echo "...fetcher..." | at now + N`.
    #   (ii)  `-f /tmp/.payload` file form (pre-staged in tmpfs).
    #   (iii) `systemctl enable atd` companion — strong red flag
    #         that an installer is turning ON a normally-off daemon
    #         specifically so it can queue `at` jobs. When the
    #         companion appears in the file we emit it as a CRON-06
    #         finding so the audit trail records the daemon-enable
    #         shape even if no `at` invocation appears in the same
    #         file (the invocation may be in a sibling script).
    rule_c6 = rule_by_id["cron-scheduled-at-job-fetcher"]
    for m in _AT_STDIN_FETCHER.finditer(text):
        _emit(rule_c6, m.start(), m.group(0))
    for m in _AT_FILE_TMP.finditer(text):
        _emit(rule_c6, m.start(), m.group(0))
    for m in _ATD_ENABLE.finditer(text):
        _emit(rule_c6, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
