"""Filesystem race / TOCTOU / lockfile / archive-extraction attack patterns.

Wave-18 deep-dive distillation round 4, batch B.

A targeted pattern catalogue for FILESYSTEM RACE-CONDITION weaknesses
spanning TOCTOU, lockfile races, archive symlink-escape, atomic-write
gaps, chmod-after-write windows, predictable temp paths, and
catastrophic-delete shapes. Convergent across the corpus surveyed in
`reports/distill-round-4/toctou-race.md`:

  * agentic-threat-hunter   (sandbox_docker.py /tmp/script.py bind-mount)
  * claude-code-cve-gate    (install.sh chmod-after-write)
  * narthex                 (install.py chmod-after-write + audit-log)
  * phantom                 (install.sh tar -xzf without sanitizer)
  * sealed-env              (PID-suffix predictable temp filenames)
  * safenpm                 (symlink-escape auditor reference)
  * sentinel                (File.chmod after File.write)

What is NOT here (already shipped — do NOT duplicate):
  * Predictable temp paths handled in shell-only contexts → bash_specific.
  * Bind-mount of arbitrary host paths into containers → container_patterns.
  * Cross-tenant Docker LPE → covered by container_patterns.

What IS here (15 net-new race / TOCTOU rules, pure regex — proposals
that would require true AST traversal are noted in their docstrings
and skipped):

  * race-py-mktemp-banned                    (HIGH)
  * race-py-namedtemp-delete-false-leak      (MEDIUM)
  * race-tmp-hardcoded-write-path            (HIGH)
  * race-symlink-append-without-nofollow     (HIGH)
  * race-chmod-after-write                   (MEDIUM)
  * race-temp-pid-suffix-predictable         (MEDIUM)
  * race-archive-unsanitized-extract         (CRITICAL)
  * race-copytree-symlinks-follow            (MEDIUM)
  * race-rename-cross-fs                     (LOW)
  * race-bash-rmrf-unset-var                 (CRITICAL)
  * race-lockfile-touch-not-exclusive        (HIGH)
  * race-docker-bindmount-tmp-shared         (HIGH)
  * race-setuid-chmod-after-write            (CRITICAL)
  * race-exists-then-rm                      (MEDIUM)
  * race-parent-dir-attacker-controlled      (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.

OWASP ASI mapping used:
  ASI-04 — Insecure Output / data leak (temp leak, /tmp/ write)
  ASI-05 — Supply-chain / cross-tenant pivot (bind-mount, archive escape)
  ASI-07 — Authority / authorisation gaps (chmod-after, setuid race)

All regexes use bounded quantifiers and no backreferences — RE2-safe.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/agent_config_patterns.Finding
    so heartbeat detectors can render either kind uniformly."""

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
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — mirrors the
    helper in auth_flow_patterns / agent_config_patterns so the surface
    is uniform across rule modules."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


def _re_cs(pattern: str) -> re.Pattern:
    """Case-sensitive variant for rules where letter case is load-bearing
    (e.g. matching specific syscall flag names like `O_NOFOLLOW` exactly,
    bash variable names that are conventionally uppercase)."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- 1. race-py-mktemp-banned -------------------------------------------


# tempfile.mktemp() returns a name and leaves the open-race to the caller.
# Deprecated since Python 2.3; any occurrence is a regression.
_MKTEMP_BANNED = _re(
    r"(?<![A-Za-z0-9_])tempfile\.mktemp\s*\("
)


# ---- 2. race-py-namedtemp-delete-false-leak -----------------------------


# Stage-A: a NamedTemporaryFile(delete=False) call. Stage-B (in scan_text)
# scans the file for matching unlink/remove of any temp file. If neither
# `os.unlink`, `Path(...).unlink`, `os.remove`, nor a `finally:` block
# with `unlink` appears in the file, fire. A true intraprocedural analysis
# would require AST — we use a file-level approximation per the proposal.
_NAMEDTEMP_DELETE_FALSE = _re(
    r"\bNamedTemporaryFile\s*\([^)]{0,200}\bdelete\s*=\s*False\b"
)

# File-level positive guards — if ANY of these appear in the file we
# trust that the caller handles cleanup.
_NAMEDTEMP_CLEANUP_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\bos\.unlink\s*\("),
    _re(r"\bos\.remove\s*\("),
    _re(r"\.unlink\s*\("),
    _re(r"\bshutil\.rmtree\s*\("),
    _re(r"#\s*leak-ok\b"),
)


# ---- 3. race-tmp-hardcoded-write-path -----------------------------------


# Write/open call targeting a hard-coded /tmp/<name> path. The path is
# predictable on every POSIX box and pre-creatable by any local user.
_TMP_HARDCODED_WRITE = _re(
    r"(?:"
    r"\bopen\s*\(\s*[fF]?['\"]/tmp/[A-Za-z0-9_.\-]+"
    r"|"
    r"\.write_text\s*\(\s*[fF]?['\"]/tmp/[A-Za-z0-9_.\-]+"
    r"|"
    r"\bPath\s*\(\s*[fF]?['\"]/tmp/[A-Za-z0-9_.\-]+"
    r"|"
    r"\bfs\.writeFile(?:Sync)?\s*\(\s*[`'\"]/tmp/[A-Za-z0-9_.\-]+"
    r"|"
    r"\bfopen\s*\(\s*['\"]/tmp/[A-Za-z0-9_.\-]+"
    r"|"
    r"\bofstream\s+[A-Za-z_]\w*\s*\(\s*['\"]/tmp/[A-Za-z0-9_.\-]+"
    r"|"
    r"\bFile\.write\s*\(\s*['\"]/tmp/[A-Za-z0-9_.\-]+"
    r"|"
    r"\bFile\.open\s*\(\s*['\"]/tmp/[A-Za-z0-9_.\-]+"
    r")"
)

# Same-line carve-outs — if these appear on the same line as the hit,
# the literal is documentation / example / test, not production.
_TMP_DOC_MARKERS = _re(
    r"#\s*EXAMPLE\b|//\s*EXAMPLE\b|#\s*DOC\b|//\s*DOC\b"
    r"|#\s*pragma:\s*tmp-ok\b"
)


# ---- 4. race-symlink-append-without-nofollow ----------------------------


# `open(var, "a")` — append mode without O_NOFOLLOW. If `var` resolves
# to a symlink the kernel follows it unconditionally and the auditor's
# append corrupts the symlink target.
_APPEND_NO_NOFOLLOW = _re(
    r"\bopen\s*\(\s*[A-Za-z_][A-Za-z0-9_.]*\s*,\s*['\"]a[+]?b?['\"]"
)

# Window-level guards — if ANY of these appear within 20 lines (above
# or below the hit) we trust the open is symlink-aware.
_NOFOLLOW_WINDOW_GUARDS: tuple[re.Pattern, ...] = (
    _re_cs(r"\bO_NOFOLLOW\b"),
    _re(r"\bis_symlink\s*\("),
    _re(r"\blstat\s*\("),
    _re(r"#\s*audit-log:\s*trusted-path\b"),
)


# ---- 5. race-chmod-after-write ------------------------------------------


# Python: write_text(...) then .chmod(...) within 10 lines on a Path
# expression. Window-based approximation; a precise per-variable trace
# would require AST.
_CHMOD_AFTER_WRITE_PY = _re(
    r"\.write_text\s*\([^)]{0,200}\)[\s\S]{0,400}?\.chmod\s*\("
)

# Python low-level: open(..., 'w') then os.chmod(...) within window.
_CHMOD_AFTER_OPEN_W_PY = _re(
    r"\bopen\s*\(\s*[^,)]+,\s*['\"]w[+]?b?['\"][^\n]*\)[\s\S]{0,400}?(?:os\.chmod|\.chmod)\s*\("
)

# Bash: cp src dst then chmod +x dst within 10 lines.
_CHMOD_AFTER_CP_BASH = _re(
    r"\bcp\s+[\-\w/.\"'$\{\}]+\s+[\-\w/.\"'$\{\}]+[\s\S]{0,400}?\bchmod\s+\+x\b"
)

# Ruby: File.write(...) then File.chmod(...) within window.
_CHMOD_AFTER_WRITE_RB = _re(
    r"\bFile\.write\s*\([^)]{0,200}\)[\s\S]{0,400}?\bFile\.chmod\s*\("
)


# ---- 6. race-temp-pid-suffix-predictable --------------------------------


# Predictable PID-suffixed temp/partial/lock filenames. PIDs are visible
# in /proc, in ps output, and fork-loop-predictable on Linux.
#
# Variants covered:
#   * Node template literal `${process.pid}`         (JS)
#   * Python f-string `{os.getpid()}` / `{getpid()}` (Py)
#   * Bash `${PID}` / `$PID` / `$$`                  (sh)
# The leading sigil family is `\$\{?` for shell/JS and `\{` for Python
# f-strings — accept either.
_PID_SUFFIX_TEMP = _re(
    r"(?:\.tmp|\.partial|\.swp|\.lock)[-_]"
    r"(?:"
    # ${process.pid} or ${PID} (shell/JS brace form)
    r"\$\{(?:process\.pid|PID|\$|getpid\s*\(\s*\))\}"
    r"|"
    # $process.pid / $PID / $$  (shell/JS no-brace form)
    r"\$(?:process\.pid|PID|\$)"
    r"|"
    # Python f-string {os.getpid()} / {getpid()}
    r"\{(?:os\.getpid\s*\(\s*\)|getpid\s*\(\s*\)|process\.pid)\}"
    r")"
)


# ---- 7. race-archive-unsanitized-extract --------------------------------


# Python tarfile/zipfile extractall, or shell tar -xzf without sanitizer
# flags. Pre-Python-3.12, tarfile.extractall has no path-traversal guard
# and a malicious symlink-member can write outside the extraction root.
_UNSANITIZED_EXTRACT = _re(
    r"\btarfile\.open\s*\([^)]{0,200}\)[\s\S]{0,400}?\.extractall\s*\("
    r"|"
    r"\bzipfile\.ZipFile\s*\([^)]{0,200}\)[\s\S]{0,400}?\.extractall\s*\("
    r"|"
    r"\btar\s+(?:-x[zjJ]?f|--extract)\b"
)

# Same-call guards — if `filter="data"` (Python 3.12+) or the bash flags
# `--no-same-owner` / `--no-same-permissions` appear within the same
# 200-char window as the call, treat as safe.
_EXTRACT_SAFE_WINDOW = _re(
    r"\bfilter\s*=\s*['\"]data['\"]"
    r"|"
    r"\-\-no-same-owner\b"
    r"|"
    r"\-\-no-same-permissions\b"
    r"|"
    r"#\s*pragma:\s*extract-ok\b"
)


# ---- 8. race-copytree-symlinks-follow -----------------------------------


# shutil.copytree(...) without symlinks=True follows symlinks during the
# copy. If src is attacker-controlled, a symlink to /etc/ exfils content
# AND amplifies an attacker file into victim-owned copies.
_COPYTREE_TRIGGER = _re(
    r"\bshutil\.copytree\s*\("
)

# Same-call guards — symlinks=True keeps the link as-is, doesn't traverse.
_COPYTREE_SAFE_KWARGS = _re(
    r"\bsymlinks\s*=\s*True\b"
)


# ---- 9. race-rename-cross-fs --------------------------------------------


# rename(src, dst) where src lives in /tmp/ or os.tmpdir(). Cross-fs
# rename falls back to copy-then-delete on Linux, killing atomicity.
_RENAME_CROSS_FS = _re(
    r"(?:fs\.renameSync|os\.rename|os\.replace|shutil\.move|File\.rename)\s*\(\s*"
    r"(?:"
    r"[fF]?['\"]/tmp/[^'\"]+['\"]"
    r"|"
    r"[fF]?['\"]/var/tmp/[^'\"]+['\"]"
    r"|"
    r"[`'\"][^`'\"]*\$\{?(?:os\.tmpdir|tempfile\.gettempdir)"
    r")"
)


# ---- 10. race-bash-rmrf-unset-var ---------------------------------------


# Classic `rm -rf "$VAR"/` — if `$VAR` is unset and `set -u` is not
# active, this becomes `rm -rf /` and nukes the box.
# Match an UPPERCASE bash variable in a rm -rf with trailing slash.
# Allow optional double/single quotes and `${...}` brace form.
_RMRF_UNSET_VAR = _re_cs(
    r"\brm\s+-rf?\s+"
    r"(?:\"\$\{?[A-Z_][A-Z0-9_]*\}?\"|'\$[A-Z_][A-Z0-9_]*'|\$\{?[A-Z_][A-Z0-9_]*\}?)"
    r"/"
)

# File-level safety guards — set -u, set -euo pipefail, or :? default
# operator. If ANY of these appear we trust the script.
_BASH_UNSET_GUARDS: tuple[re.Pattern, ...] = (
    _re_cs(r"\bset\s+-u\b"),
    _re_cs(r"\bset\s+-[eEuxo]+\b"),
    _re_cs(r"set\s+-o\s+nounset\b"),
)


# ---- 11. race-lockfile-touch-not-exclusive ------------------------------


# `if not lock.exists(): lock.touch()` — NOT a lock. Two concurrent
# processes both see `not exists` and both touch. The correct primitive
# is `os.open(lock, O_CREAT|O_EXCL)`.
_LOCKFILE_TOUCH = _re(
    r"if\s+not\s+[A-Za-z_][A-Za-z0-9_.]*\.exists\s*\(\s*\)[\s\S]{0,200}?"
    r"[A-Za-z_][A-Za-z0-9_.]*\.touch\s*\("
)

# Or the os.path.exists(...) variant followed by open(..., 'w') or .touch.
_LOCKFILE_EXISTS_THEN_OPEN_W = _re(
    r"\bos\.path\.exists\s*\([^)]{0,100}\)[\s\S]{0,200}?"
    r"(?:open\s*\(\s*[^,)]+,\s*['\"]w[+]?b?['\"]|Path\s*\([^)]+\)\.touch\s*\()"
)

# Window-level safe shapes — O_EXCL or fcntl.flock within 5 lines.
_LOCK_SAFE_WINDOW = _re_cs(
    r"\bO_EXCL\b"
    r"|"
    r"\bfcntl\.flock\b"
)


# ---- 12. race-docker-bindmount-tmp-shared -------------------------------


# Bind-mount of `/tmp/<predictable>` into a container at another fixed
# path. Two concurrent runs collide; co-tenant can pre-create the mount
# source as a symlink.
_DOCKER_BIND_TMP = _re(
    r"\bvolumes\s*=\s*\{[^}]*['\"]/tmp/[A-Za-z0-9_.\-]+['\"]\s*:"
)

# Container `command=f"... /tmp/<name>"` referencing the bound path.
_DOCKER_COMMAND_TMP = _re(
    r"\bcommand\s*=\s*[fF]?['\"][^'\"]{0,100}\s+/tmp/[A-Za-z0-9_.\-]+['\"]"
)


# ---- 13. race-setuid-chmod-after-write ----------------------------------


# setuid/setgid bits applied via chmod. The setuid bits (0o4000) and
# setgid bits (0o2000) — values like 0o4755, 0o2755, 0o6755 — granted
# AFTER an open(..., 'w') leave a TOCTOU window where an attacker can
# symlink the path to one of their own scripts.
_SETUID_CHMOD = _re(
    r"(?:os\.chmod|\.chmod)\s*\(\s*[^,]+,\s*0o[4567][0-7][0-7][0-7]\s*\)"
)

# Same-file positive context — if a setuid chmod follows a plain
# `open(..., 'w')` or `Path(...).write_text(` anywhere in the file
# (without an atomic os.open with mode= kwarg), flag as CRITICAL.
_SETUID_CONTEXT_WRITE = _re(
    r"\bopen\s*\(\s*[^,)]+,\s*['\"]w[+]?b?['\"]"
    r"|"
    r"\.write_text\s*\("
)

# Atomic-create variant — if os.open(..., O_CREAT, 0o4755) appears we
# trust the call (atomic creation with the mode).
_ATOMIC_OPEN_MODE = _re_cs(
    r"\bos\.open\s*\([^)]{0,200}\bO_CREAT\b[^)]{0,100}0o[4567][0-7][0-7][0-7]"
)


# ---- 14. race-exists-then-rm --------------------------------------------


# os.path.exists(p) immediately before os.unlink(p) or shutil.rmtree(p).
# Check-then-act window. Correct shape is unlink-inside-try +
# except FileNotFoundError.
_EXISTS_THEN_RM = _re(
    r"(?:os\.path\.exists\s*\([^)]{0,100}\)|Path\s*\([^)]+\)\.exists\s*\(\s*\))"
    r"[^\n]{0,80}\n\s*(?:os\.unlink|os\.remove|shutil\.rmtree|"
    r"Path\s*\([^)]+\)\.unlink|Path\s*\([^)]+\)\.rmtree)"
)

# Same-line safety annotation.
_RACE_TOLERATED = _re(
    r"#\s*race-tolerated\b"
)


# ---- 15. race-parent-dir-attacker-controlled ----------------------------


# Files opened inside HOME / user dot-dirs without O_NOFOLLOW. A co-tenant
# can pre-create the dot-dir / dot-file as a symlink to attack the user.
# This is HIGH-severity only when the file holds secrets/credentials.
_HOME_DOTFILE_OPEN = _re(
    r"\bwith\s+open\s*\(\s*os\.path\.join\s*\(\s*os\.environ\.get\s*\(\s*['\"]HOME['\"]"
    r"|"
    r"\bopen\s*\(\s*os\.environ\[\s*['\"]HOME['\"]\s*\]"
    r"|"
    r"\bPath\s*\(\s*os\.environ\[\s*['\"]HOME['\"]\s*\]\s*\)\s*/\s*['\"]\."
    r"|"
    r"\bPath\.home\s*\(\s*\)\s*/\s*['\"]\."
)

# Window-level safe shapes — O_NOFOLLOW or os.fchmod on an open fd.
_HOME_SAFE_WINDOW = _re_cs(
    r"\bO_NOFOLLOW\b"
    r"|"
    r"\bos\.fchmod\s*\("
    r"|"
    r"\blstat\s*\("
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="race-py-mktemp-banned",
        name="Use of deprecated tempfile.mktemp() leaves TOCTOU window",
        severity="HIGH",
        description=(
            "`tempfile.mktemp()` returns a NAME and leaves the open-race "
            "to the caller. Deprecated since Python 2.3 because the gap "
            "between the name allocation and the eventual open() is a "
            "classic TOCTOU window — a co-tenant can pre-create the path "
            "as a symlink. Use `tempfile.mkstemp()` or "
            "`NamedTemporaryFile()` (with proper cleanup) instead."
        ),
        pattern=_MKTEMP_BANNED,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="race-py-namedtemp-delete-false-leak",
        name="NamedTemporaryFile(delete=False) without explicit unlink",
        severity="MEDIUM",
        description=(
            "`NamedTemporaryFile(delete=False)` keeps the file after the "
            "`with` block exits — if the caller forgets the explicit "
            "`os.unlink` / `Path.unlink` in a `finally:` block, the file "
            "leaks. Worse, predictable temp paths can be pre-created by "
            "an attacker as a symlink. The cleanup-guard scan is a "
            "file-level approximation; precise intraprocedural analysis "
            "would require AST."
        ),
        pattern=_NAMEDTEMP_DELETE_FALSE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="race-tmp-hardcoded-write-path",
        name="Hard-coded /tmp/ write path is local-attacker-controllable",
        severity="HIGH",
        description=(
            "`/tmp/` is world-writable on every POSIX system. A "
            "predictable filename there is pre-creatable by any local "
            "user as a dangling symlink. If production code writes "
            "credentials, audit logs, or executable scripts to "
            "`/tmp/<known-name>`, the local-attacker→privilege-escape "
            "chain is direct. Use `tempfile.mkstemp` / `mkdtemp` for "
            "unguessable paths."
        ),
        pattern=_TMP_HARDCODED_WRITE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="race-symlink-append-without-nofollow",
        name="open(path, 'a') without O_NOFOLLOW follows attacker symlinks",
        severity="HIGH",
        description=(
            "Audit-logger / append-mode `open(LOG_PATH, 'a')` without "
            "`O_NOFOLLOW` or an `lstat`/`is_symlink` pre-check. If "
            "`LOG_PATH` is a symlink the attacker placed earlier, every "
            "audit append corrupts the symlink target. On Linux the "
            "kernel follows the symlink unconditionally; only "
            "`O_NOFOLLOW` or pre-`lstat` bails out."
        ),
        pattern=_APPEND_NO_NOFOLLOW,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="race-chmod-after-write",
        name="chmod() called AFTER write — mode-narrowing race window",
        severity="MEDIUM",
        description=(
            "Writing a file creates it with `umask`-default mode "
            "(commonly `0o644`), and only afterwards is `chmod` called "
            "to narrow it. Between those two syscalls another process "
            "can `open()` the file with the wider mode and hold the "
            "handle across the chmod. Even `0o755` is exploitable when "
            "the file is about to be executed. Use atomic creation: "
            "`os.open(path, O_CREAT|O_EXCL, 0o600)` or umask-restrict "
            "before the write."
        ),
        pattern=_CHMOD_AFTER_WRITE_PY,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="race-temp-pid-suffix-predictable",
        name="Temp filename uses PID suffix — predictable by co-tenant",
        severity="MEDIUM",
        description=(
            "Process IDs are not random. On Linux `pid_max` defaults to "
            "32768; a fork-loop predicts the next PID. The PID is also "
            "visible in `/proc/`, `ps`, and syslog. An attacker who "
            "pre-creates `<target>.tmp-<predicted-pid>` as a symlink "
            "defeats the atomic-write helper that uses the predictable "
            "suffix. Use `secrets.token_hex(8)` / `crypto.randomBytes` "
            "for unguessable suffixes."
        ),
        pattern=_PID_SUFFIX_TEMP,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="race-archive-unsanitized-extract",
        name="Archive extraction without path-traversal / symlink filter",
        severity="CRITICAL",
        description=(
            "Python `tarfile.extractall` / `zipfile.ZipFile.extractall` "
            "without `filter='data'` (Python 3.12+) or `tar -xzf` "
            "without `--no-same-owner --no-same-permissions` flags. A "
            "malicious archive entry named `../../etc/cron.d/x` writes "
            "outside the extraction root; a `SYMTYPE` member can plant "
            "a symlink to `/etc/passwd` that the next regular member "
            "writes through. CVE-2007-4559 / safenpm symlink-escape "
            "auditor confirm this is a real attack surface."
        ),
        pattern=_UNSANITIZED_EXTRACT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="race-copytree-symlinks-follow",
        name="shutil.copytree() default follows attacker-controlled symlinks",
        severity="MEDIUM",
        description=(
            "`copytree(src, dst)` with default `symlinks=False` follows "
            "every symlink during the copy. If `src` is "
            "attacker-controlled (e.g. an extracted package directory), "
            "a symlink inside `src` pointing at `/etc/` causes `/etc/` "
            "contents to be COPIED into `dst`. Data exfil channel AND "
            "amplification primitive. Pass `symlinks=True` to preserve "
            "links without traversing, or audit the source tree first."
        ),
        pattern=_COPYTREE_TRIGGER,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="race-rename-cross-fs",
        name="rename() from /tmp/ to non-tmp may lose atomicity",
        severity="LOW",
        description=(
            "`rename(src, dst)` is atomic ONLY when both paths are on "
            "the same filesystem. If `src` is `/tmp/` (typically tmpfs) "
            "and `dst` is `~/Documents/`, on Linux the call falls back "
            "to non-atomic copy-then-delete and the atomicity guarantee "
            "dies. The classic atomic-write idiom requires the temp "
            "path to be on the SAME filesystem as the destination — "
            "typically `dirname(dst) + '/.tmp-<random>'`."
        ),
        pattern=_RENAME_CROSS_FS,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="race-bash-rmrf-unset-var",
        name="rm -rf \"$VAR\"/ without set -u — catastrophic delete risk",
        severity="CRITICAL",
        description=(
            "Classic shell antipattern: `rm -rf \"$TMPDIR\"/` becomes "
            "`rm -rf /` when `$TMPDIR` is unset and `set -u` is not "
            "active. Nukes the box. Even with `set -u`, the trailing "
            "slash on a symlinked target follows the link — safer "
            "patterns include `${VAR:?error}` (bash's built-in unset "
            "guard) and `find \"$VAR\" -mindepth 1 -delete`."
        ),
        pattern=_RMRF_UNSET_VAR,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="race-lockfile-touch-not-exclusive",
        name="Lockfile created via `exists() then touch()` is not atomic",
        severity="HIGH",
        description=(
            "`if not lock.exists(): lock.touch()` IS NOT a lock. Two "
            "concurrent processes both see `not exists` and both touch, "
            "both proceed past the gate. The correct primitive is "
            "`os.open(lock, O_CREAT|O_EXCL)` which fails atomically for "
            "the second contender. `fcntl.flock()` also works but does "
            "not survive across NFS / SMB."
        ),
        pattern=_LOCKFILE_TOUCH,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="race-docker-bindmount-tmp-shared",
        name="Docker bind-mount /tmp/<predictable> shared across runs",
        severity="HIGH",
        description=(
            "Bind-mounting a host `/tmp/<predictable-name>` into a "
            "container at another predictable path means (a) two "
            "concurrent runs collide, (b) any process on the host can "
            "pre-create the mount source as a symlink to `/etc/shadow`, "
            "(c) the container's `mode: ro` does NOT help — it only "
            "restricts the container's view, not the host symlink "
            "resolution that happens before mount. Use mkstemp-derived "
            "paths or `tmpfs` mounts."
        ),
        pattern=_DOCKER_BIND_TMP,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="race-setuid-chmod-after-write",
        name="setuid/setgid chmod() after open(..., 'w') — privilege race",
        severity="CRITICAL",
        description=(
            "setuid bits (0o4000) and setgid bits (0o2000) — masks like "
            "0o4755, 0o2755, 0o6755 — applied via `os.chmod` AFTER a "
            "plain `open(..., 'w')` or `Path.write_text` leave a TOCTOU "
            "window. A co-tenant who pre-creates the output path as a "
            "symlink to one of THEIR scripts has that script become "
            "setuid-owner. Classic Solaris-era LPE pattern. Use "
            "`os.open(path, O_CREAT|O_EXCL, 0o4755)` to set the mode "
            "atomically with the creation."
        ),
        pattern=_SETUID_CHMOD,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="race-exists-then-rm",
        name="os.path.exists() then os.unlink() — TOCTOU window",
        severity="MEDIUM",
        description=(
            "`if os.path.exists(p): os.unlink(p)` — the file can be "
            "unlinked or swapped between the check and the action. The "
            "correct pattern is to call `unlink` directly inside a "
            "`try: ... except FileNotFoundError: pass` block. For "
            "directory trees, `shutil.rmtree(p, ignore_errors=True)` "
            "covers the same case atomically."
        ),
        pattern=_EXISTS_THEN_RM,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="race-parent-dir-attacker-controlled",
        name="File opened under HOME/dot-dir without symlink-aware probe",
        severity="HIGH",
        description=(
            "`~/.claude/`, `~/.config/`, `~/.ssh/` are conventional "
            "dot-dirs that a co-tenant can pre-create as symlinks to "
            "attack the user. A hook that does `Path.home() / "
            "'.claude' / 'secrets.json'` and writes without `O_NOFOLLOW` "
            "writes through any planted symlink. Fix: `lstat` every "
            "parent component and verify ownership + mode `0o700` "
            "before open. Or pass `os.O_NOFOLLOW | os.O_DIRECTORY` to "
            "each parent and `O_NOFOLLOW` to the final open."
        ),
        pattern=_HOME_DOTFILE_OPEN,
        owasp_asi="ASI-07",
    ),
)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of the 1-based line_no without trailing newline."""
    lines = text.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _surrounding_lines(
    text: str,
    line_no: int,
    above: int = 10,
    below: int = 10,
) -> str:
    """Return the concatenation of `above` lines before, the target line,
    and `below` lines after. Used to satisfy rule-4 / rule-15 window scans."""
    lines = text.split("\n")
    start = max(0, line_no - 1 - above)
    end = min(len(lines), line_no + below)
    return "\n".join(lines[start:end])


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


def _window_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match in the given text snippet."""
    return any(g.search(text) is not None for g in guards)


def scan_text(text: str) -> list[Finding]:  # noqa: PLR0912, PLR0915, C901
    """Run every applicable RULES pattern against `text` and return findings.

    Multi-stage rules consult file-level positive guards (NamedTemporaryFile
    leak suppressed when any unlink/remove is present), window-level
    context probes (append-without-nofollow, chmod-after-write, lockfile,
    home-dotfile-open), and same-line carve-outs (documentation markers
    for /tmp paths, atomic-create for setuid chmod, set -u for rm -rf).

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    # File-level guard evaluation (one shot per file for cheap rules).
    namedtemp_cleanup_present = _file_contains_any(text, _NAMEDTEMP_CLEANUP_GUARDS)
    bash_unset_safe = _file_contains_any(text, _BASH_UNSET_GUARDS)
    setuid_context_write_present = _SETUID_CONTEXT_WRITE.search(text) is not None
    atomic_open_with_mode = _ATOMIC_OPEN_MODE.search(text) is not None

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    # Iterate the additional Python-language chmod-after-write patterns
    # alongside the catalogued pattern so they share the same scan loop.
    extra_patterns: tuple[tuple[str, re.Pattern], ...] = (
        ("race-chmod-after-write", _CHMOD_AFTER_OPEN_W_PY),
        ("race-chmod-after-write", _CHMOD_AFTER_CP_BASH),
        ("race-chmod-after-write", _CHMOD_AFTER_WRITE_RB),
        ("race-lockfile-touch-not-exclusive", _LOCKFILE_EXISTS_THEN_OPEN_W),
        ("race-docker-bindmount-tmp-shared", _DOCKER_COMMAND_TMP),
    )

    all_rule_lookup = {r.id: r for r in RULES}

    def _emit(
        rule_id: str,
        match: re.Match[str],
    ) -> None:
        rule = all_rule_lookup[rule_id]
        line, col = _line_col(text, match.start())
        key = (rule_id, line, col)
        if key in seen:
            return

        # Per-rule Stage-B filters.
        if rule_id == "race-py-namedtemp-delete-false-leak":
            if namedtemp_cleanup_present:
                return
        elif rule_id == "race-tmp-hardcoded-write-path":
            ln_text = _line_text(text, line)
            if _TMP_DOC_MARKERS.search(ln_text) is not None:
                return
        elif rule_id == "race-symlink-append-without-nofollow":
            window = _surrounding_lines(text, line, above=20, below=20)
            if _window_contains_any(window, _NOFOLLOW_WINDOW_GUARDS):
                return
        elif rule_id == "race-archive-unsanitized-extract":
            # If the safe-window markers appear in the surrounding 400
            # chars (e.g. filter="data" same call, --no-same-owner same
            # tar invocation), suppress.
            window_text = text[max(0, match.start() - 100): match.end() + 400]
            if _EXTRACT_SAFE_WINDOW.search(window_text) is not None:
                return
        elif rule_id == "race-copytree-symlinks-follow":
            # Inspect the call's arg list — if symlinks=True appears
            # within 400 chars of the call, suppress.
            window_text = text[match.start(): match.end() + 400]
            if _COPYTREE_SAFE_KWARGS.search(window_text) is not None:
                return
        elif rule_id == "race-bash-rmrf-unset-var":
            if bash_unset_safe:
                return
            # Same-line `${VAR:?error}` guard syntax.
            ln_text = _line_text(text, line)
            if re.search(r"\$\{[A-Z_][A-Z0-9_]*:\?", ln_text):
                return
        elif rule_id == "race-lockfile-touch-not-exclusive":
            window = _surrounding_lines(text, line, above=5, below=5)
            if _LOCK_SAFE_WINDOW.search(window) is not None:
                return
        elif rule_id == "race-setuid-chmod-after-write":
            # Only fire when the file has a non-atomic write context AND
            # does NOT already use atomic os.open with mode kwarg.
            if not setuid_context_write_present:
                return
            if atomic_open_with_mode:
                return
        elif rule_id == "race-exists-then-rm":
            ln_text = _line_text(text, line)
            if _RACE_TOLERATED.search(ln_text) is not None:
                return
        elif rule_id == "race-parent-dir-attacker-controlled":
            window = _surrounding_lines(text, line, above=10, below=10)
            if _window_contains_any(window, (_HOME_SAFE_WINDOW,)):
                return

        seen.add(key)
        matched = match.group(0)
        if len(matched) > 200:
            matched = matched[:200] + "…"
        findings.append(Finding(
            rule_id=rule_id,
            line=line,
            column=col,
            matched_text=matched,
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            _emit(rule.id, m)

    for rule_id, pat in extra_patterns:
        for m in pat.finditer(text):
            _emit(rule_id, m)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
