"""Rust cargo build.rs + proc-macro RCE patterns.

Wave-36 distillation round 22 — Rust supply-chain attack-class patterns.

Catalogue of 10 build-time / proc-macro RCE patterns distilled in
`reports/distill-round-22/20260528_105702+0200-cargo-build-rs.md`.
Targets `build.rs`, `Cargo.toml`, `.cargo/config.toml`, and proc-macro
`src/lib.rs` surfaces that are executable at `cargo build` / `cargo test`
time and therefore offer pre-install RCE opportunities.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * crg-command-new-env-var            (CRITICAL)
  * crg-command-new-env-var-runtime    (CRITICAL)
  * crg-network-fetch-crate            (CRITICAL)
  * crg-network-tcpstream              (HIGH)
  * crg-outdir-write-env               (HIGH)
  * crg-outdir-write-format            (HIGH)
  * crg-proc-macro-fs-access           (CRITICAL)
  * crg-proc-macro-env-path            (HIGH)
  * crg-patch-crates-io                (HIGH)
  * crg-git-dep-non-https              (HIGH)
  * crg-path-dep-traversal             (MEDIUM)
  * crg-target-runner-string           (HIGH)
  * crg-target-runner-array            (HIGH)
  * crg-shell-command-new              (CRITICAL)
  * crg-shell-arg-c                    (CRITICAL)

Note: pattern 9 (cargo install --git unpinned) uses a negative lookahead
which is NOT RE2-compatible; it is omitted here per the RE2-only contract.
The equivalent is: match `cargo install --git` and check absence of
`--rev`/`--tag`/`--locked` in post-processing.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-05 — Supply-chain / build-time RCE (build.rs env injection,
            shell eval, proc-macro FS, network fetch, patch hijack)
  ASI-02 — Secret leak (proc-macro reading HOME/CARGO_HOME secrets)
  ASI-04 — Information exfiltration (TcpStream in build.rs)
  ASI-06 — Dependency confusion / MITM (non-HTTPS git dep, patch,
            path traversal, target runner injection)

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
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

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


def _re(pattern: str) -> re.Pattern:  # noqa: UP006
    """Compile with MULTILINE+UNICODE — RE2-safe: no nested quantifiers,
    no backreferences, no lookbehind. IGNORECASE intentionally omitted:
    Rust identifiers are case-sensitive."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- crg-command-new-env-var --------------------------------------------
# build.rs calls Command::new(env!("...")) — env macro supplies command path.

_CMD_NEW_ENV_MACRO = _re(
    r"Command\s*::\s*new\s*\(\s*(?:std\s*::\s*)?env\s*!\s*\(\s*\"[^\"]*\"\s*\)"
)

# ---- crg-command-new-env-var-runtime ------------------------------------
# build.rs calls Command::new(env::var("...")) — runtime env lookup.

_CMD_NEW_ENV_VAR = _re(
    r"Command\s*::\s*new\s*\(\s*(?:std\s*::\s*)?env\s*::\s*var\s*\("
)

# ---- crg-network-fetch-crate --------------------------------------------
# Network client crate used inside build.rs (exfil / second-stage dropper).

_NETWORK_FETCH_CRATE = _re(
    r"(?:reqwest|ureq|curl|attohttpc|isahc)\s*::\s*(?:get|blocking|Client)"
)

# ---- crg-network-tcpstream ----------------------------------------------
# Raw TcpStream::connect in build.rs — low-level exfil channel.

_NETWORK_TCPSTREAM = _re(r"TcpStream\s*::\s*connect\s*\(")

# ---- crg-outdir-write-env -----------------------------------------------
# fs::write / File::create with path argument containing env::var() call —
# path traversal out of OUT_DIR sandbox.

_OUTDIR_WRITE_ENV = _re(
    r"(?:fs\s*::\s*write|File\s*::\s*create)\s*\([^)]*env\s*::\s*var\s*\("
)

# ---- crg-outdir-write-format --------------------------------------------
# fs::write / File::create with format!() as path — attacker-influenced
# filename via crate metadata / env vars fed into the format string.

_OUTDIR_WRITE_FORMAT = _re(
    r"(?:fs\s*::\s*write|File\s*::\s*create)\s*\(\s*format!\s*\("
)

# ---- crg-proc-macro-fs-access -------------------------------------------
# std::fs operations inside proc-macro src/lib.rs — can read SSH keys,
# ~/.cargo/credentials.toml, or write backdoors.

_PROC_MACRO_FS = _re(
    r"std\s*::\s*fs\s*::\s*(?:read|write|File|remove|create|copy|rename)"
)

# ---- crg-proc-macro-env-path --------------------------------------------
# env! macro referencing HOME, CARGO_HOME, CARGO_MANIFEST_DIR, or PATH
# inside a proc-macro — used to construct absolute paths to secrets.

_PROC_MACRO_ENV_PATH = _re(
    r"env\s*!\s*\(\s*\"(?:HOME|CARGO_HOME|CARGO_MANIFEST_DIR|PATH)\"\s*\)"
)

# ---- crg-patch-crates-io ------------------------------------------------
# [patch.crates-io] section in Cargo.toml — transparently replaces a
# registry crate with an attacker-controlled git or path source.

_PATCH_CRATES_IO = _re(r"\[patch\.crates-io\]")

# ---- crg-git-dep-non-https ----------------------------------------------
# git = "..." dependency with non-HTTPS scheme — bypasses TLS cert
# validation; susceptible to MITM replacement.

_GIT_DEP_NON_HTTPS = _re(
    r"git\s*=\s*\"(?:git://|ssh://|http://)[^\"]*\""
)

# ---- crg-path-dep-traversal ---------------------------------------------
# path = "../../..." — two or more ../ components exit the workspace root.

_PATH_DEP_TRAVERSAL = _re(r"path\s*=\s*\"(?:\.\./){2,}[^\"]*\"")

# ---- crg-target-runner-string -------------------------------------------
# [target.X.runner] = "binary ..." — arbitrary binary wraps every
# cargo test / cargo run execution.

_TARGET_RUNNER_STRING = _re(r"runner\s*=\s*\"[^\"]{2,}\"")

# ---- crg-target-runner-array --------------------------------------------
# runner = [...] array form — can hide extra arguments after the wrapper.

_TARGET_RUNNER_ARRAY = _re(r"runner\s*=\s*\[")

# ---- crg-shell-command-new ----------------------------------------------
# Command::new("sh") / "bash" / "cmd" etc. — direct shell spawning
# in build.rs or proc-macro.

_SHELL_CMD_NEW = _re(
    r"Command\s*::\s*new\s*\(\s*\"(?:sh|bash|zsh|fish|cmd|powershell)\"\s*\)"
)

# ---- crg-shell-arg-c ----------------------------------------------------
# .arg("-c") following a Command::new — classic sh -c eval pattern.

_SHELL_ARG_C = _re(r"\.arg\s*\(\s*\"-c\"\s*\)")


# ---- Rule catalogue -----------------------------------------------------

RULES: tuple[Rule, ...] = (
    Rule(
        id="crg-command-new-env-var",
        name="build.rs Command::new from env! macro",
        severity="CRITICAL",
        description=(
            "build.rs passes an env! macro value as the command to "
            "Command::new. An attacker who controls the build environment "
            "(CI injection, .env poisoning) executes an arbitrary binary."
        ),
        pattern=_CMD_NEW_ENV_MACRO,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="crg-command-new-env-var-runtime",
        name="build.rs Command::new from env::var() lookup",
        severity="CRITICAL",
        description=(
            "build.rs constructs the Command path by reading a runtime "
            "environment variable via env::var(). Attacker-controlled env "
            "vars redirect execution to an arbitrary binary."
        ),
        pattern=_CMD_NEW_ENV_VAR,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="crg-network-fetch-crate",
        name="build.rs uses network client crate (reqwest/ureq/curl/…)",
        severity="CRITICAL",
        description=(
            "A network client crate is used inside build.rs. Malicious "
            "build scripts use these to exfiltrate environment secrets or "
            "download and execute a second-stage payload into OUT_DIR."
        ),
        pattern=_NETWORK_FETCH_CRATE,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="crg-network-tcpstream",
        name="build.rs raw TcpStream::connect",
        severity="HIGH",
        description=(
            "build.rs opens a raw TCP connection via TcpStream::connect. "
            "Low-level exfiltration channel that bypasses higher-level "
            "HTTP client detection."
        ),
        pattern=_NETWORK_TCPSTREAM,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="crg-outdir-write-env",
        name="build.rs writes OUT_DIR file with env::var() in path",
        severity="HIGH",
        description=(
            "fs::write or File::create uses a path argument containing "
            "env::var(). An attacker controlling the variable can inject "
            "path traversal sequences to write files outside OUT_DIR."
        ),
        pattern=_OUTDIR_WRITE_ENV,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="crg-outdir-write-format",
        name="build.rs writes OUT_DIR file with format!() path",
        severity="HIGH",
        description=(
            "fs::write or File::create uses format!() to build the "
            "destination path. External input fed into format strings "
            "can produce path-traversal escapes out of the OUT_DIR sandbox."
        ),
        pattern=_OUTDIR_WRITE_FORMAT,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="crg-proc-macro-fs-access",
        name="proc-macro uses std::fs I/O",
        severity="CRITICAL",
        description=(
            "std::fs operations in a proc-macro run inside the compiler "
            "process and can read secrets (SSH keys, ~/.cargo/credentials) "
            "or write backdoors to arbitrary filesystem locations."
        ),
        pattern=_PROC_MACRO_FS,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="crg-proc-macro-env-path",
        name="proc-macro reads HOME/CARGO_HOME/PATH via env!",
        severity="HIGH",
        description=(
            "env! macro referencing HOME, CARGO_HOME, CARGO_MANIFEST_DIR, "
            "or PATH inside a proc-macro. Used to construct absolute paths "
            "to credential files or inject into shell-expansion sinks."
        ),
        pattern=_PROC_MACRO_ENV_PATH,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="crg-patch-crates-io",
        name="Cargo.toml [patch.crates-io] dependency substitution",
        severity="HIGH",
        description=(
            "[patch.crates-io] transparently replaces a registry crate with "
            "a git URL or local path. An attacker controlling the patch "
            "target silently substitutes malicious code for a legitimate dep."
        ),
        pattern=_PATCH_CRATES_IO,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="crg-git-dep-non-https",
        name="Cargo.toml git dependency with non-HTTPS scheme",
        severity="HIGH",
        description=(
            "A git = dependency using git://, ssh://, or http:// skips "
            "TLS certificate validation. Attacker with DNS or network "
            "control can serve a trojaned crate via MITM."
        ),
        pattern=_GIT_DEP_NON_HTTPS,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="crg-path-dep-traversal",
        name="Cargo.toml path dependency with ../../ traversal",
        severity="MEDIUM",
        description=(
            "path = with two or more ../ components exits the workspace "
            "root, potentially referencing attacker-controlled directories "
            "such as sibling repos or mounted network shares."
        ),
        pattern=_PATH_DEP_TRAVERSAL,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="crg-target-runner-string",
        name=".cargo/config.toml target.X.runner arbitrary binary (string)",
        severity="HIGH",
        description=(
            "runner = \"binary\" wraps every cargo test and cargo run "
            "invocation with an arbitrary command. An attacker controlling "
            "this field executes arbitrary code on every test run."
        ),
        pattern=_TARGET_RUNNER_STRING,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="crg-target-runner-array",
        name=".cargo/config.toml target.X.runner arbitrary binary (array)",
        severity="HIGH",
        description=(
            "runner = [...] array form can hide extra arguments after the "
            "wrapper binary and is harder to detect than the string form."
        ),
        pattern=_TARGET_RUNNER_ARRAY,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="crg-shell-command-new",
        name="build.rs / proc-macro spawns a shell via Command::new",
        severity="CRITICAL",
        description=(
            "Command::new with a shell name (sh, bash, zsh, fish, cmd, "
            "powershell) is the most direct RCE pattern in a build script "
            "or proc-macro. Even a hardcoded command string may be "
            "constructed at runtime from crate metadata or environment."
        ),
        pattern=_SHELL_CMD_NEW,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="crg-shell-arg-c",
        name="build.rs / proc-macro uses .arg(\"-c\") shell eval",
        severity="CRITICAL",
        description=(
            ".arg(\"-c\") following a Command::new is the classic sh -c "
            "pattern for arbitrary shell command evaluation. Execution "
            "payload is passed as a subsequent argument."
        ),
        pattern=_SHELL_ARG_C,
        owasp_asi="ASI-05",
    ),
)


# ---- Public API ---------------------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Scan *text* against every rule and return a list of Finding tuples.

    Line numbers are 1-based; column numbers are 0-based byte offsets within
    the line, matching the convention used by webhook_signature_patterns.
    """
    findings: list[Finding] = []
    lines = text.splitlines(keepends=True)
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            # Determine 1-based line number and 0-based column.
            start = m.start()
            # Count newlines before match start for line number.
            line_no = text.count("\n", 0, start) + 1
            # Column = offset from the start of the current line.
            line_start = text.rfind("\n", 0, start) + 1
            col = start - line_start
            findings.append(
                Finding(
                    rule_id=rule.id,
                    line=line_no,
                    column=col,
                    matched_text=m.group(),
                    severity=rule.severity,
                    description=rule.description,
                    owasp_asi=rule.owasp_asi,
                )
            )
    # Stable sort: by line then column for deterministic test output.
    findings.sort(key=lambda f: (f.line, f.column))
    _ = lines  # referenced to silence the unused-variable linter note
    return findings
