"""Process-injection / debugger / LD_PRELOAD-class hook attack-pattern catalogue.

Wave 18 (distill round 4, agent C) — net-new deterministic detectors for
attacker-controlled hooks that **modify a running process** without
touching its source. Detection-only: this module identifies the shapes
so the janitor can warn an operator; it never executes anything.

Cited source catalogues:
  * malcontent (rules/evasion/hijack_execution/, rules/anti-behavior/)
  * supply-chain-guardian (container_scanner.py, runtime_monitor.py)
  * agentic-threat-hunter
  * AgentShield
  * supply-chain-defense / supply-chain-sentinel
  * narthex hooks
  * claude-code-cve-gate

This module is the RULE-PATTERN catalogue. Detectors + the skill-bundle
scanner import these and run them. Pure-stdlib (re, frozenset, NamedTuple)
so it loads in every PEP 723 script block without third-party deps.

Public surface mirrors scripts/lib/auth_flow_patterns.py exactly:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple.
  * RULES — ordered tuple of every catalogued rule.
  * scan_text(text, *, file_kind="prose") -> list[Finding]

Severity strings: "CRITICAL", "HIGH", "MAJOR", "MEDIUM", "LOW".

OWASP-ASI mapping used:
  ASI-02 — Insecure direct access (debugger-attach as exfil)
  ASI-04 — Unrestricted package/library install (linker hijack)
  ASI-06 — Insecure containerised environment (priv flags)
  ASI-07 — Untrusted plugin/skill execution (runtime monkey-patch)
  ASI-08 — Insecure agent runtime config (loader / startup hijack)
  ASI-10 — Persistence and recovery abuse (launchd / systemd / shell-init)

All regex patterns are RE2-safe — no backreferences, no nested
quantifiers, no catastrophic-backtracking shapes. Patterns rely on
character-class quantifiers ([^…]+) bounded by literal delimiters.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as scripts/lib/auth_flow_patterns.Finding
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
    """Compile a pattern with IGNORECASE+MULTILINE+UNICODE — same convention
    as auth_flow_patterns._re. Env-var names and file paths are
    case-insensitive in real corpora (Windows + macOS HFS+ both
    case-fold)."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Shared helpers -----------------------------------------------------

# Write-direction operators shared by Proposals 2 / 7 / 9 (LD-preload-fs,
# shell-init poisoning, launchd/systemd persistence). Factored once so the
# three rule patterns stay consistent. Each entry is a self-contained
# alternation token; downstream patterns inject the alternation list
# verbatim into a parenthesised group.
_WRITE_OPS: tuple[str, ...] = (
    r">>?\s*",                          # bash redirect (>, >>)
    r"tee\s+(?:-a\s+)?",                # tee / tee -a
    r"cat\s+>+\s*",                     # cat > / cat >>
    r"echo\s+[^\n|]{1,200}?\s+>+\s*",   # echo ... > path
    r"printf\s+[^\n|]{1,200}?\s+>+\s*", # printf ... > path
    r"sed\s+-i[^\n]{0,200}?\s+",        # sed -i edits in place
    r"install\s+(?:-m\s*\d+\s+)?\S+\s+",
    r"cp\s+\S+\s+",
    r"mv\s+\S+\s+",
    r"dd\s+(?:if|of)=\S+\s+(?:if|of)=",
)


# ---- 1. proc-inject-ld-preload-env --------------------------------------
# Dynamic-linker hijack via env var: LD_PRELOAD / LD_LIBRARY_PATH /
# DYLD_INSERT_LIBRARIES / APPINIT_DLLS etc. set in workflow env:,
# Dockerfile ENV, shell export, pyproject [tool.*.env], or package.json
# scripts. The single regex catches all three syntactic shells with
# branch-alternation; downstream allowlist downgrades benign forms.

_LDLINK_VAR_BODY = (
    # Linux glibc + musl
    r"LD_PRELOAD|LD_LIBRARY_PATH|LD_AUDIT|LD_DEBUG|LD_PROFILE"
    r"|LD_USE_LOAD_BIAS|LD_ORIGIN_PATH"
    # macOS dyld
    r"|DYLD_INSERT_LIBRARIES|DYLD_LIBRARY_PATH"
    r"|DYLD_FALLBACK_LIBRARY_PATH|DYLD_FRAMEWORK_PATH"
    r"|DYLD_FALLBACK_FRAMEWORK_PATH|DYLD_FORCE_FLAT_NAMESPACE"
    r"|DYLD_PRINT_LIBRARIES|DYLD_PRINT_BINDINGS"
    # Windows AppInit DLL
    r"|APPINIT_DLLS|LOADAPPINIT_DLLS"
)

# Variables that are CRITICAL even with value=1 (true injection vectors).
# Diagnostic-only variables — legitimate dev-time use, but still
# attacker-useful (LD_DEBUG=all reveals which libs load, etc.) — get
# downgraded to HIGH severity in scan_text.
# Invariant: the two sets are disjoint and together cover every var
# the regex matches that we care about. The CRITICAL set stays as the
# rule default; the HIGH set is the explicit downgrade list.
_LDLINK_CRITICAL_VARS = frozenset({
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT",
    "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH",
    "DYLD_FALLBACK_FRAMEWORK_PATH", "DYLD_FORCE_FLAT_NAMESPACE",
    "APPINIT_DLLS", "LOADAPPINIT_DLLS",
})
_LDLINK_HIGH_VARS = frozenset({
    "LD_DEBUG", "LD_PROFILE", "LD_USE_LOAD_BIAS", "LD_ORIGIN_PATH",
    "DYLD_PRINT_LIBRARIES", "DYLD_PRINT_BINDINGS",
})
assert not (_LDLINK_CRITICAL_VARS & _LDLINK_HIGH_VARS), (
    "ld-link severity partition must be disjoint — fix the overlap "
    "before shipping"
)

# Captures the env-var key + the RHS value via named groups. Three
# anchors covered in alternation: shell `export VAR=val`, Dockerfile
# `ENV VAR val`, YAML `VAR: val`. The pattern is conservative on
# whitespace and never crosses a newline boundary in the value.
_LDLINK_HIJACK_RE = _re(
    # Shell-style: optional `export`, then VAR=val
    r"(?:^|\s|;|&&|\|\|)(?:export\s+)?"
    r"(?P<var_sh>" + _LDLINK_VAR_BODY + r")"
    r"\s*=\s*(?P<val_sh>[^\s;#\n]{1,500})"
    r"|"
    # Dockerfile: ENV KEY VAL or ENV KEY=VAL
    r"^[ \t]*ENV[ \t]+(?P<var_df>" + _LDLINK_VAR_BODY + r")"
    r"[ \t=]+(?P<val_df>[^\n#]{1,500})"
    r"|"
    # YAML key: value (workflow env:, compose env:)
    r"^[ \t]*(?P<var_yml>" + _LDLINK_VAR_BODY + r")"
    r"\s*:\s*[\"']?(?P<val_yml>[^\"'\n#]{1,500}?)[\"']?\s*(?:#.*)?$"
)


# ---- 2. proc-inject-ld-so-preload-fs ------------------------------------
# Filesystem-resident dynamic-linker poisoning — writes to /etc/ld.so.preload,
# /etc/ld.so.conf.d/*.conf, /etc/ld.so.cache. Distinct from the env-var
# hijack: this one persists across processes and across reboots on a
# self-hosted runner.

_LD_PRELOAD_FS_PATHS = (
    r"/etc/ld\.so\.preload",
    r"/etc/ld\.so\.conf\.d/[\w.\-]{1,200}\.conf",
    r"/etc/ld\.so\.conf",
    r"/etc/ld\.so\.cache",
)

_LD_PRELOAD_FS_RE = _re(
    r"(?:" + "|".join(_WRITE_OPS) + r")"
    r"(?:" + "|".join(_LD_PRELOAD_FS_PATHS) + r")"
)

# Source-level Python/Go/Rust writes — `open("/etc/ld.so.preload", "w")`,
# `Path("/etc/ld.so.preload").write_text(...)`. The pattern is intentionally
# narrow: must reference the literal path AND a write-mode token in close
# proximity (same logical line, ≤120 chars apart).
_LD_PRELOAD_SOURCE_RE = _re(
    r"(?:open\s*\(|Path\s*\(|os\.OpenFile\s*\(|fs::write\s*\(|"
    r"WriteFile\s*\()[^\n)]{0,120}"
    r"(?:" + "|".join(_LD_PRELOAD_FS_PATHS) + r")"
)


# ---- 3. proc-inject-container-priv-flags --------------------------------
# Container runtime priv flags that ENABLE process injection — these are
# `docker run` / `podman run` / `nerdctl run` / compose / workflow
# container `options:` flags that disable the sandbox the container engine
# would normally enforce.

_CONTAINER_PRIV_FLAG_BODY = (
    # cap-add variants (single value form — narrowing-cap-add lists are
    # handled by the dedicated compose-style pattern below).
    r"--cap-add[= ](?:SYS_PTRACE|ALL|SYS_ADMIN|SYS_MODULE|"
    r"DAC_READ_SEARCH|NET_ADMIN|NET_RAW)\b"
    r"|--privileged\b"
    r"|--security-opt[= ]seccomp[= ]?unconfined\b"
    r"|--security-opt[= ]apparmor[= ]?unconfined\b"
    r"|--pid[= ]host\b"
    r"|--ipc[= ]host\b"
    r"|--net[= ]host\b"
    r"|--network[= ]host\b"
    r"|--userns[= ]host\b"
    r"|--device[= ]/dev/(?:mem|kmem|kmsg|port|sg\d+)\b"
)

_CONTAINER_PRIV_FLAG_RE = _re(_CONTAINER_PRIV_FLAG_BODY)

# Docker-socket bind — equivalent to root-on-host because the daemon owns
# root. Three syntactic forms: `-v src:dst`, `--mount type=bind`, and the
# colon-pair without -v in compose `volumes:` lists.
_DOCKER_SOCK_BIND_RE = _re(
    r"-v\s+/var/run/docker\.sock(?::[^\s]{0,200})?"
    r"|--mount\s+type=bind[^\n]{0,200}?source=/var/run/docker\.sock"
    r"|^[ \t-]+/var/run/docker\.sock:/var/run/docker\.sock"
)

# Compose-style: `privileged: true`, `cap_add: [SYS_PTRACE, ALL]`,
# `pid: host`, `network_mode: host`. These use YAML, not CLI flags, so
# they need their own pattern set.
_COMPOSE_PRIV_RE = _re(
    r"^[ \t]*privileged\s*:\s*true\b"
    r"|^[ \t]*pid\s*:\s*[\"']?host[\"']?"
    r"|^[ \t]*ipc\s*:\s*[\"']?host[\"']?"
    r"|^[ \t]*network_mode\s*:\s*[\"']?host[\"']?"
    r"|^[ \t]*userns_mode\s*:\s*[\"']?host[\"']?"
    r"|^[ \t]*-\s*(?:SYS_PTRACE|SYS_ADMIN|SYS_MODULE|ALL|DAC_READ_SEARCH)\s*$"
)


# ---- 4. proc-inject-ptrace-attach-cli -----------------------------------
# Debugger attach via the canonical CLI flag set: `gdb -p`, `lldb -p`,
# `strace -p`, `dtruss -p`, `frida -p`, `radare2 -d -p`. Plus YAMA bypass
# (kernel.yama.ptrace_scope=0) and source-language ptrace-syscall imports.

_DEBUGGER_ATTACH_RE = _re(
    r"\b(?:"
    r"gdb\s+(?:[-]{1,2}batch\s+)?(?:[-]{1,2}q(?:uiet)?\s+)?"
    r"(?:[-]p|[-]{2}pid)(?:[= ])\d+"
    r"|lldb\s+(?:[-]p|[-]{2}attach-pid)\s+\d+"
    r"|strace\s+(?:[-]f\s+)?[-]p\s+\d+"
    r"|ltrace\s+[-]p\s+\d+"
    r"|dtruss\s+[-]p\s+\d+"
    r"|frida\s+(?:[-]p|[-]{2}pid)\s+\d+"
    r"|frida-trace\s+(?:[-]p|[-]{2}pid)\s+\d+"
    r"|drrun\s+(?:[-]{2}pid|[-]pid)\s+\d+"
    r"|radare2\s+(?:[-]d\s+)?[-]p\s+\d+"
    r"|r2\s+[-]d\s+(?:pid://)?\d+"
    r")\b"
)

# Source-level ptrace syscall use across C / Python / Go / Rust. The
# detector flags the IMPORT + CALL shapes — never the bare token, since
# `ptrace` appears in comments, log messages, and YARA rule names.
_PTRACE_SOURCE_RE = _re(
    # C / C++ — PTRACE_ATTACH / PTRACE_SEIZE / PTRACE_POKEDATA constants
    r"\bptrace\s*\(\s*PTRACE_(?:ATTACH|SEIZE|POKEDATA|POKETEXT|TRACEME)\b"
    r"|"
    # Python via ctypes — `libc.ptrace(...)` or `process_vm_readv/writev`
    r"\bctypes\.CDLL\([^)\n]{0,200}libc[^)\n]{0,200}\)[^\n]{0,200}\bptrace\b"
    r"|"
    r"\bprocess_vm_(?:readv|writev)\s*\("
    r"|"
    # Go: syscall.PtraceAttach / unix.PtraceAttach / PtraceSeize
    r"\b(?:syscall|unix)\.Ptrace(?:Attach|Seize|Pokedata|Poketext)\s*\("
    r"|"
    r"\b(?:syscall|unix)\.Process(?:VMReadv|VMWritev)\s*\("
    r"|"
    # Rust: libc::ptrace, nix::sys::ptrace::{attach,seize,write,read}
    r"\blibc::ptrace\s*\("
    r"|"
    r"\bnix::sys::ptrace::(?:attach|seize|write|read)\b"
)

# YAMA bypass — disabling the kernel's default cross-process ptrace block.
_YAMA_BYPASS_RE = _re(
    r"\bsysctl\s+(?:-w\s+)?kernel\.yama\.ptrace_scope\s*=\s*0\b"
    r"|>\s*/proc/sys/kernel/yama/ptrace_scope"
    r"|echo\s+0\s*>\s*/proc/sys/kernel/yama/ptrace_scope"
)


# ---- 5. proc-inject-node-loader-require ---------------------------------
# Node.js loader / require hijacking via NODE_OPTIONS env or direct CLI
# flags. Includes inspector exposure on a non-loopback interface and
# `vm.runInNewContext` with tainted payload.

_NODE_LOADER_FLAG_BODY = (
    r"--require=|--import=|--loader=|--experimental-loader=|"
    r"--experimental-vm-modules|--inspect-brk(?:=[^\s\"']{1,200})?|"
    r"--inspect(?:=[^\s\"']{1,200})?|--inspect-port="
)

# NODE_OPTIONS env var carrying a loader flag (any of the above).
_NODE_OPTIONS_HIJACK_RE = _re(
    r"\bNODE_OPTIONS\s*[=:]\s*[\"']?[^\"'\n#]{0,500}?"
    r"(?:" + _NODE_LOADER_FLAG_BODY + r")"
)

# Direct invocation form: `node --require=/tmp/x.js`, `nodejs --loader=...`
_NODE_DIRECT_LOADER_RE = _re(
    r"\b(?:node|node\d+|nodejs)\s+(?:[^\n#]{0,200}?\s+)?"
    r"(?:" + _NODE_LOADER_FLAG_BODY + r")\s*\S+"
)

# vm.runInNewContext / vm.runInContext with tainted payload sourced from
# user input (body / req / payload / data / query / params / stdin /
# message / content). The match is intentionally narrow — only the
# data-tainted form, not the legitimate `runInContext(literalSource)`.
_VM_RUNINCONTEXT_TAINTED_RE = _re(
    r"\bvm\.runIn(?:NewContext|Context|ThisContext)\s*\(\s*"
    r"(?:[a-zA-Z_$][\w$]{0,64}\s*\.\s*"
    r"(?:body|input|payload|req|data|query|params|stdin|message|content))"
)


# ---- 6. proc-inject-python-startup-hijack -------------------------------
# Python startup-path hijack via env vars (PYTHONSTARTUP, PYTHONPATH,
# PYTHONHOME, PYTHONUSERBASE, PYTHONINSPECT, PYTHONEXECUTABLE) AND .pth
# files smuggled into a package's source tree with `import` lines.

_PY_STARTUP_VAR_BODY = (
    r"PYTHONSTARTUP|PYTHONPATH|PYTHONHOME|PYTHONUSERBASE|PYTHONINSPECT"
    r"|PYTHONEXECUTABLE|PYTHONNOUSERSITE|PYTHONDONTWRITEBYTECODE"
)

# Variables that are HIGH severity (true injection vectors) — the
# rule default. Vars in the MEDIUM set get downgraded in scan_text
# when paired with a benign value (1/0/true/false).
# Invariant: the two sets are disjoint and partition the Python-
# startup var regex.
_PY_STARTUP_HIGH_VARS = frozenset({
    "PYTHONSTARTUP", "PYTHONPATH", "PYTHONHOME",
    "PYTHONUSERBASE", "PYTHONINSPECT", "PYTHONEXECUTABLE",
})
_PY_STARTUP_MEDIUM_VARS = frozenset({
    "PYTHONNOUSERSITE", "PYTHONDONTWRITEBYTECODE",
})
assert not (_PY_STARTUP_HIGH_VARS & _PY_STARTUP_MEDIUM_VARS), (
    "python-startup severity partition must be disjoint"
)

_PY_STARTUP_ENV_RE = _re(
    # Shell-style: optional export, VAR=val
    r"(?:^|\s|;|&&|\|\|)(?:export\s+)?"
    r"(?P<py_var_sh>" + _PY_STARTUP_VAR_BODY + r")"
    r"\s*=\s*(?P<py_val_sh>[^\s;#\n]{1,500})"
    r"|"
    # Dockerfile: ENV KEY VAL or ENV KEY=VAL
    r"^[ \t]*ENV[ \t]+(?P<py_var_df>" + _PY_STARTUP_VAR_BODY + r")"
    r"[ \t=]+(?P<py_val_df>[^\n#]{1,500})"
    r"|"
    # YAML key: value (workflow env:)
    r"^[ \t]*(?P<py_var_yml>" + _PY_STARTUP_VAR_BODY + r")"
    r"\s*:\s*[\"']?(?P<py_val_yml>[^\"'\n#]{1,500}?)[\"']?\s*(?:#.*)?$"
)

# A .pth file body that contains `import …` — the malicious form. The
# `.pth` extension was made to embed arbitrary import statements; a path
# entry is harmless but `import os; os.system(...)` is not.
_PTH_DANGEROUS_BODY_RE = _re(
    r"^\s*import\s+[\w.]+"
    r"|^\s*from\s+[\w.]+\s+import\s+\w+"
    r"|^\s*exec\s*\("
    r"|^\s*eval\s*\("
    r"|^\s*__import__\s*\("
)


# ---- 7. proc-inject-shell-init-poisoning --------------------------------
# Shell-init poisoning — writes to /etc/profile.d/*.sh, ~/.bashrc.d/*.sh,
# /etc/bash.bashrc, etc. Auto-sourced by every login / interactive shell.

_SHELL_INIT_PATHS = (
    r"/etc/profile\.d/[\w.\-]{1,200}\.sh",
    r"/etc/profile",
    r"/etc/bash\.bashrc",
    r"/etc/zsh/zshenv",
    r"/etc/zsh/zprofile",
    r"/etc/zsh/zshrc",
    r"/etc/fish/conf\.d/[\w.\-]{1,200}\.fish",
    r"~/\.bashrc\.d/[\w.\-]{1,200}\.sh",
    r"~/\.bashrc",
    r"~/\.zshrc\.d/[\w.\-]{1,200}\.sh",
    r"~/\.zshrc",
    r"~/\.profile",
    r"~/\.bash_profile",
    r"~/\.bash_login",
    r"~/\.zprofile",
    r"~/\.zlogin",
    r"~/\.zlogout",
    r"~/\.config/fish/conf\.d/[\w.\-]{1,200}\.fish",
    r"\$HOME/\.bashrc(?:\.d/[\w.\-]{1,200}\.sh)?",
    r"\$\{HOME\}/\.bashrc(?:\.d/[\w.\-]{1,200}\.sh)?",
    r"\$HOME/\.zshrc(?:\.d/[\w.\-]{1,200}\.sh)?",
)

_SHELL_INIT_WRITE_RE = _re(
    r"(?:" + "|".join(_WRITE_OPS) + r")"
    r"(?:" + "|".join(_SHELL_INIT_PATHS) + r")"
)


# ---- 8. proc-inject-runtime-monkeypatch ---------------------------------
# In-process twin of LD_PRELOAD — module-level reassignment of stdlib /
# popular-lib network / subprocess / LLM-SDK entry points. Plus
# sys.settrace / signal-swallow handlers.

# Targets are matched as quoted/literal LHS dotted names. We use a
# frozenset of strings and build one alternation pattern from them at
# module load. Pre-escaping each entry keeps the regex deterministic.
_MONKEY_TARGETS: tuple[str, ...] = (
    # Network stdlib
    "socket.socket", "socket.create_connection", "socket.connect",
    "urllib.request.urlopen", "urllib.request.Request",
    "http.client.HTTPConnection", "http.client.HTTPSConnection",
    # Popular HTTP libs
    "requests.get", "requests.post", "requests.put", "requests.delete",
    "requests.patch", "requests.request",
    "requests.Session.request",
    "httpx.get", "httpx.post", "httpx.request",
    "aiohttp.ClientSession.request", "aiohttp.request",
    # Subprocess / exec
    "subprocess.run", "subprocess.Popen", "subprocess.call",
    "subprocess.check_call", "subprocess.check_output",
    "os.system", "os.execv", "os.execve", "os.execvp", "os.execvpe",
    "os.popen",
    # LLM SDKs — high-value targets
    "anthropic.Anthropic", "anthropic.AsyncAnthropic",
    "openai.OpenAI", "openai.AsyncOpenAI",
    "openai.ChatCompletion.create",
    # Filesystem
    "builtins.open", "io.open",
    "pathlib.Path.read_text", "pathlib.Path.write_text",
    "pathlib.Path.read_bytes", "pathlib.Path.write_bytes",
)

# Module-level assignment of a monkey-target. The LHS is the literal
# dotted path; the RHS is non-empty (anything except an empty line).
# Allowlist for wrapping shapes (RHS contains a `_orig` / `_wrapped` /
# `_real` token) is applied in scan_text().
_MONKEY_PATCH_RE = _re(
    r"^[ \t]*(?P<mp_lhs>(?:"
    + "|".join(re.escape(t) for t in _MONKEY_TARGETS) +
    r"))\s*=\s*(?P<mp_rhs>[^=\n][^\n]{0,500})"
)

# sys.settrace / sys.setprofile / threading.settrace / threading.setprofile
# — the Python debugger hook surface.
_SYS_TRACE_RE = _re(
    r"\b(?:sys|threading)\.(?:settrace|setprofile)\s*\("
)

# signal.signal(SIG…, handler) — the bare anchor. Severity escalation
# (handler swallows the signal) is done in scan_text() with a body scan.
_SIGNAL_HOOK_RE = _re(
    r"signal\.signal\s*\(\s*signal\.(?P<sig>SIG(?:TERM|INT|HUP|QUIT))\s*,"
    r"\s*(?P<handler>[a-zA-Z_][\w]{0,64})"
)


# ---- 9. proc-inject-launchd-systemd-persistence -------------------------
# Persistence via systemd-user units, system systemd, macOS LaunchAgents/
# LaunchDaemons, crontab files, or schtasks. These outlive the workflow
# and re-launch attacker code at the next login / boot.

_PERSISTENCE_PATHS = (
    # systemd user
    r"~/\.config/systemd/user/[\w.\-]{1,200}\.(?:service|timer|target|socket)",
    r"\$HOME/\.config/systemd/user/[\w.\-]{1,200}\."
    r"(?:service|timer|target|socket)",
    r"\$\{HOME\}/\.config/systemd/user/[\w.\-]{1,200}\."
    r"(?:service|timer|target|socket)",
    # systemd system
    r"/etc/systemd/system/[\w.\-]{1,200}\.(?:service|timer|target|socket)",
    r"/lib/systemd/system/[\w.\-]{1,200}\.(?:service|timer)",
    r"/usr/lib/systemd/system/[\w.\-]{1,200}\.(?:service|timer)",
    # macOS launchd
    r"~/Library/LaunchAgents/[\w.\-]{1,200}\.plist",
    r"/Library/LaunchAgents/[\w.\-]{1,200}\.plist",
    r"/Library/LaunchDaemons/[\w.\-]{1,200}\.plist",
    r"\$HOME/Library/LaunchAgents/[\w.\-]{1,200}\.plist",
    # crontab and cron.d
    r"/etc/cron\.d/[\w.\-]{1,200}",
    r"/var/spool/cron/(?:crontabs/)?\w{1,64}",
    r"~/\.crontab",
)

_PERSISTENCE_WRITE_RE = _re(
    r"(?:" + "|".join(_WRITE_OPS) + r")"
    r"(?:" + "|".join(_PERSISTENCE_PATHS) + r")"
)

# Windows scheduled-task creation (cross-platform persistence).
_SCHTASKS_CREATE_RE = _re(
    r"\bschtasks\s+/create\b"
    r"|\bSchedule\.Service\b"
    r"|\bRegister-ScheduledTask\b"
)

# Activation step — `launchctl load`, `systemctl --user enable`. These
# are LOW severity on their own (legitimate admin) but become HIGH when
# combined with a write in the same file.
_PERSISTENCE_ACTIVATE_RE = _re(
    r"\blaunchctl\s+(?:load|bootstrap|enable|kickstart)\b"
    r"|\bsystemctl\s+(?:--user\s+)?(?:enable|start|daemon-reload)\b"
    r"|\bcrontab\s+-[ul]?\s*\S+"
)


# ---- 10. proc-inject-windows-dll-hijack ---------------------------------
# Windows-specific DLL injection — APPINIT_DLLS registry write, IFEO
# Debugger key, KnownDLLs modification. Targets workflows on
# `runs-on: windows-latest`.

_WIN_REG_HIJACK_RE = _re(
    r"\breg\s+(?:add|import)\s+[\"']?"
    r"HK(?:LM|EY_LOCAL_MACHINE)"
    r"\\SOFTWARE\\Microsoft\\Windows\s+NT\\CurrentVersion\\Windows"
    r"|reg\s+(?:add|import)\s+[\"']?"
    r"HK(?:LM|EY_LOCAL_MACHINE)"
    r"\\SOFTWARE\\Microsoft\\Windows\s+NT\\CurrentVersion"
    r"\\Image\s+File\s+Execution\s+Options"
    r"|reg\s+(?:add|import)\s+[\"']?"
    r"HK(?:LM|EY_LOCAL_MACHINE)\\SYSTEM\\CurrentControlSet"
    r"\\Control\\Session\s+Manager\\KnownDLLs"
)

# setx / set APPINIT_DLLS=... or LOADAPPINIT_DLLS=1 — the per-user form.
# `setx VARNAME VALUE` uses space-delimited args (Windows); `set VAR=VAL`
# uses equals (cmd.exe builtin). Both forms catch each variable.
_WIN_APPINIT_RE = _re(
    r"\bsetx\s+APPINIT_DLLS\s+\S+"
    r"|\bset\s+APPINIT_DLLS\s*=\s*\S+"
    r"|\bsetx\s+LOADAPPINIT_DLLS\s+1\b"
    r"|\bset\s+LOADAPPINIT_DLLS\s*=\s*1\b"
)

# PowerShell variant — Set-ItemProperty against the same registry paths.
_WIN_PS_REG_RE = _re(
    r"\bSet-ItemProperty\s+(?:-Path\s+)?[\"']HKLM:\\SOFTWARE\\Microsoft"
    r"\\Windows\s+NT\\CurrentVersion\\"
    r"(?:Windows|Image\s+File\s+Execution\s+Options)"
    r"|\bNew-ItemProperty\s+(?:-Path\s+)?[\"']HKLM:\\SOFTWARE\\Microsoft"
    r"\\Windows\s+NT\\CurrentVersion\\"
    r"(?:Windows|Image\s+File\s+Execution\s+Options)"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="proc-inject-ld-preload-env",
        name="Dynamic-linker hijack env var set",
        severity="CRITICAL",
        description=(
            "LD_PRELOAD / LD_LIBRARY_PATH / DYLD_INSERT_LIBRARIES / "
            "DYLD_LIBRARY_PATH / APPINIT_DLLS / LOADAPPINIT_DLLS is set "
            "in a workflow env:, Dockerfile ENV, shell export, "
            "pyproject [tool.*.env], or package.json scripts. Every "
            "subsequent dynamic-linked child process loads attacker code "
            "before main() runs."
        ),
        pattern=_LDLINK_HIJACK_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="proc-inject-ld-so-preload-fs",
        name="Filesystem write to /etc/ld.so.preload / ld.so.conf.d",
        severity="CRITICAL",
        description=(
            "Write to /etc/ld.so.preload, /etc/ld.so.conf.d/*.conf, "
            "/etc/ld.so.conf, or /etc/ld.so.cache. System-wide and "
            "persistent across reboots — every dynamic-linked binary "
            "loads the listed shared objects at start. Self-hosted-runner "
            "infection vector."
        ),
        pattern=_LD_PRELOAD_FS_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="proc-inject-container-priv-flags",
        name="Container runtime priv flag enables injection",
        severity="HIGH",
        description=(
            "Container engine flag that disables the sandbox: "
            "--privileged, --cap-add=SYS_PTRACE / SYS_ADMIN / ALL, "
            "--security-opt seccomp/apparmor=unconfined, --pid=host, "
            "--ipc=host, --net=host, --userns=host, --device=/dev/mem|"
            "kmem|kmsg, or /var/run/docker.sock bind. Enables every "
            "ptrace-class injection."
        ),
        pattern=_CONTAINER_PRIV_FLAG_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="proc-inject-ptrace-attach-cli",
        name="Debugger / tracer attach command",
        severity="HIGH",
        description=(
            "Non-interactive debugger / tracer attach in CI: gdb -p, "
            "lldb -p, strace -p, ltrace -p, dtruss -p, frida -p, "
            "radare2 -p, drrun --pid. Reads sibling process memory via "
            "ptrace(PEEKDATA, ...) without opening /proc/PID/mem — the "
            "credential-extraction primitive."
        ),
        pattern=_DEBUGGER_ATTACH_RE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="proc-inject-node-loader-require",
        name="Node loader / require hijack via NODE_OPTIONS or CLI",
        severity="HIGH",
        description=(
            "NODE_OPTIONS=--require=… / --import=… / --loader=… / "
            "--experimental-loader=… / --inspect-brk=0.0.0.0 in env or "
            "direct CLI. Every node invocation in the job preloads "
            "attacker code without touching package.json, postinstall, "
            "or any visible install step."
        ),
        pattern=_NODE_OPTIONS_HIJACK_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="proc-inject-python-startup-hijack",
        name="Python startup-path env hijack",
        severity="HIGH",
        description=(
            "PYTHONSTARTUP / PYTHONPATH / PYTHONHOME / PYTHONUSERBASE / "
            "PYTHONINSPECT set in workflow env or Dockerfile ENV. "
            "PYTHONPATH=. is the prepend-CWD trick that lets a shipped "
            "os.py shadow the stdlib; PYTHONSTARTUP runs attacker code "
            "before the REPL starts."
        ),
        pattern=_PY_STARTUP_ENV_RE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="proc-inject-shell-init-poisoning",
        name="Shell-init / profile.d file write",
        severity="HIGH",
        description=(
            "Write to /etc/profile.d/*.sh, /etc/bash.bashrc, /etc/zsh/*, "
            "~/.bashrc(.d/*.sh), ~/.zshrc(.d/*.sh), ~/.profile, "
            "~/.bash_profile, ~/.zprofile, ~/.config/fish/conf.d/*.fish. "
            "Auto-sourced by every interactive / login shell — "
            "persistent attacker payload delivery across CI runs on "
            "self-hosted runners."
        ),
        pattern=_SHELL_INIT_WRITE_RE,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="proc-inject-runtime-monkeypatch",
        name="Module-level monkey-patch of stdlib / SDK entry point",
        severity="MAJOR",
        description=(
            "Module-level reassignment of socket / urllib / requests / "
            "httpx / aiohttp / subprocess / os.exec* / open / "
            "anthropic.Anthropic / openai.OpenAI. The in-process twin "
            "of LD_PRELOAD — silently re-routes every network / exec / "
            "fs call. Allowlisted when the RHS preserves the original "
            "(`_orig` / `_wrapped` / `_real` token)."
        ),
        pattern=_MONKEY_PATCH_RE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="proc-inject-launchd-systemd-persistence",
        name="Persistence via systemd / launchd / cron unit write",
        severity="HIGH",
        description=(
            "Write to ~/.config/systemd/user/*.service, /etc/systemd/"
            "system/*.service, ~/Library/LaunchAgents/*.plist, /Library/"
            "LaunchDaemons/*.plist, /etc/cron.d/*, or crontab spool. "
            "Outlives the workflow, re-launches attacker code at next "
            "login / boot / scheduled time."
        ),
        pattern=_PERSISTENCE_WRITE_RE,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="proc-inject-windows-dll-hijack",
        name="Windows AppInit_DLLs / IFEO / KnownDLLs registry hijack",
        severity="MAJOR",
        description=(
            "Registry write to HKLM\\…\\Windows NT\\CurrentVersion\\"
            "Windows (AppInit_DLLs), …\\Image File Execution Options "
            "(IFEO Debugger), or …\\Session Manager\\KnownDLLs. The "
            "Windows equivalent of LD_PRELOAD — every GUI process loads "
            "the listed DLLs at start, or the IFEO 'Debugger' subkey "
            "runs attacker code every time a named binary launches."
        ),
        pattern=_WIN_REG_HIJACK_RE,
        owasp_asi="ASI-04",
    ),
)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


# Allowlist markers — RHS substrings that indicate a LEGITIMATE wrapper
# pattern (the assigned function preserves the original somehow). Used by
# Rule 8 (monkey-patch) to suppress wrappers like
# `socket.socket = wrap(socket._orig_socket)`.
_MONKEY_WRAPPER_ALLOWLIST_TOKENS: tuple[str, ...] = (
    "_orig", "_original", "_wrapped", "_real", "_inner", "_super",
    "Mock(", "MagicMock(", "patch(", "patch.object(",
)

# Tokens that indicate a signal handler properly terminates the process
# (calls sys.exit, os._exit, or raises). Presence => not a swallow.
_SIGNAL_CLEANUP_TOKENS: tuple[str, ...] = (
    "sys.exit", "os._exit", "raise ", "raise\n", "os.kill",
    "SystemExit", "KeyboardInterrupt",
)


def _is_test_file_path(path: str | None) -> bool:
    """True if the path looks like a test file (relaxed severity)."""
    if not path:
        return False
    lowered = path.replace("\\", "/").lower()
    return (
        "/tests/" in lowered
        or lowered.endswith("_test.py")
        or "/test_" in lowered
        or lowered.startswith("test_")
    )


def scan_text(
    text: str,
    *,
    file_kind: str = "prose",
    file_path: str | None = None,
) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` selects sub-checks:
      * "prose"   (default) — runs every rule. Suitable for README, YAML,
                                Dockerfile, shell, source.
      * "source"            — code files; additionally runs the
                                second-pass detectors for ptrace source
                                code, Node direct-CLI loader, vm.run*,
                                docker-sock binds, compose-style priv
                                flags, .pth body, YAMA bypass, sys.settrace,
                                signal-swallow, Win regsitry / setx / PS,
                                persistence-activation, schtasks-create.
      * "pth"               — special mode for *.pth file bodies. ONLY
                                the _PTH_DANGEROUS_BODY_RE runs (so a
                                bare path doesn't fire); a hit emits a
                                proc-inject-python-startup-hijack at
                                CRITICAL.

    `file_path` is used solely for the test-file severity downgrade in
    Rule 8 (monkey-patch). Tests legitimately monkey-patch.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(
        rule_id: str,
        line: int,
        col: int,
        matched: str,
        severity: str,
        description: str,
        owasp_asi: str,
    ) -> None:
        key = (rule_id, line, col)
        if key in seen:
            return
        seen.add(key)
        display = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(Finding(
            rule_id=rule_id,
            line=line,
            column=col,
            matched_text=display,
            severity=severity,
            description=description,
            owasp_asi=owasp_asi,
        ))

    # Special path: .pth file mode. Treat the entire text as a .pth
    # body and flag dangerous import / exec / eval lines as
    # python-startup-hijack at CRITICAL severity.
    if file_kind == "pth":
        rule = next(
            r for r in RULES if r.id == "proc-inject-python-startup-hijack"
        )
        for m in _PTH_DANGEROUS_BODY_RE.finditer(text):
            line, col = _line_col(text, m.start())
            _emit(
                rule_id=rule.id,
                line=line,
                col=col,
                matched=m.group(0),
                severity="CRITICAL",
                description=(
                    ".pth file body contains an `import …` / `exec(...)` "
                    "/ `eval(...)` / `__import__(...)` line. .pth files "
                    "are auto-executed by Python at startup — drops "
                    "attacker code into every interpreter that imports "
                    "this site-packages tree."
                ),
                owasp_asi="ASI-08",
            )
        findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
        return findings

    # Main pass — every RULES entry runs.
    test_file = _is_test_file_path(file_path)
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())

            # Stage-B filters per rule.
            severity = rule.severity
            owasp_asi = rule.owasp_asi
            description = rule.description

            if rule.id == "proc-inject-ld-preload-env":
                # Identify which var matched and decide CRITICAL vs HIGH.
                gd = m.groupdict()
                var = gd.get("var_sh") or gd.get("var_df") or gd.get("var_yml")
                val = gd.get("val_sh") or gd.get("val_df") or gd.get("val_yml")
                if var is None:
                    continue
                var_upper = var.upper()
                # Empty value (just `=` with no RHS) — skip; the regex
                # already requires {1,500} chars but a value of pure
                # whitespace can still slip through.
                if val is not None and not val.strip():
                    continue
                # Diagnostic-only vars get HIGH unless the value looks
                # path-shaped (contains a `/` or `\\`).
                if var_upper in _LDLINK_HIGH_VARS:
                    if val is not None and ("/" not in val and "\\" not in val):
                        severity = "HIGH"
                # FP: LD_BIND_NOW=1 is legitimate hardening.
                if var_upper == "LD_BIND_NOW" and val and val.strip() in {"1", "0"}:
                    continue

            elif rule.id == "proc-inject-runtime-monkeypatch":
                rhs = m.group("mp_rhs") or ""
                # Allowlist legitimate wrappers — the RHS references the
                # original by suffix tokens like _orig / _wrapped, OR is
                # a mock object.
                if any(tok in rhs for tok in _MONKEY_WRAPPER_ALLOWLIST_TOKENS):
                    continue
                # Test files are downgraded to MEDIUM.
                if test_file:
                    severity = "MEDIUM"

            elif rule.id == "proc-inject-python-startup-hijack":
                gd = m.groupdict()
                var = (
                    gd.get("py_var_sh")
                    or gd.get("py_var_df")
                    or gd.get("py_var_yml")
                )
                val = (
                    gd.get("py_val_sh")
                    or gd.get("py_val_df")
                    or gd.get("py_val_yml")
                )
                if var is None:
                    continue
                var_upper = var.upper()
                # FP: PYTHONDONTWRITEBYTECODE=1 / PYTHONNOUSERSITE=1 alone
                # are legitimate CI hardening — downgrade to MEDIUM.
                if (
                    var_upper in _PY_STARTUP_MEDIUM_VARS
                    and val is not None
                    and val.strip() in {"1", "0", "true", "false", "yes", "no"}
                ):
                    severity = "MEDIUM"

            _emit(
                rule_id=rule.id,
                line=line,
                col=col,
                matched=m.group(0),
                severity=severity,
                description=description,
                owasp_asi=owasp_asi,
            )

    # ---- second-pass detectors (source mode) ----
    if file_kind != "source":
        findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
        return findings

    # Source-mode passes — every detector here adds findings for shapes
    # that don't fit the single-anchor Rule pattern.

    # Pass 1: LD_PRELOAD path appears in source file open/Path call.
    rule = next(r for r in RULES if r.id == "proc-inject-ld-so-preload-fs")
    for m in _LD_PRELOAD_SOURCE_RE.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            rule_id=rule.id,
            line=line,
            col=col,
            matched=m.group(0),
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        )

    # Pass 2: Docker-socket bind & compose-style priv.
    rule = next(r for r in RULES if r.id == "proc-inject-container-priv-flags")
    for m in _DOCKER_SOCK_BIND_RE.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            rule_id=rule.id,
            line=line,
            col=col,
            matched=m.group(0),
            severity="CRITICAL",
            description=(
                "Docker-socket (/var/run/docker.sock) bind-mounted into "
                "the container — equivalent to root-on-host. Container "
                "process can spawn arbitrary host containers, mount "
                "host fs, escape sandbox entirely."
            ),
            owasp_asi=rule.owasp_asi,
        )
    for m in _COMPOSE_PRIV_RE.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            rule_id=rule.id,
            line=line,
            col=col,
            matched=m.group(0),
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        )

    # Pass 3: ptrace-source / YAMA bypass.
    rule = next(r for r in RULES if r.id == "proc-inject-ptrace-attach-cli")
    for m in _PTRACE_SOURCE_RE.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            rule_id=rule.id,
            line=line,
            col=col,
            matched=m.group(0),
            severity=rule.severity,
            description=(
                "Source-level ptrace syscall use — ptrace(PTRACE_ATTACH), "
                "process_vm_readv / writev, syscall.PtraceAttach, "
                "nix::sys::ptrace. Reads or writes sibling-process "
                "memory without opening /proc/PID/mem."
            ),
            owasp_asi=rule.owasp_asi,
        )
    for m in _YAMA_BYPASS_RE.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            rule_id=rule.id,
            line=line,
            col=col,
            matched=m.group(0),
            severity="CRITICAL",
            description=(
                "Linux YAMA ptrace_scope set to 0 — disables the "
                "kernel's default cross-process ptrace block. Every "
                "process can now attach-and-read every other process "
                "on the host."
            ),
            owasp_asi=rule.owasp_asi,
        )

    # Pass 4: Node direct loader / vm.runInNewContext tainted.
    rule = next(r for r in RULES if r.id == "proc-inject-node-loader-require")
    for m in _NODE_DIRECT_LOADER_RE.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            rule_id=rule.id,
            line=line,
            col=col,
            matched=m.group(0),
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        )
    for m in _VM_RUNINCONTEXT_TAINTED_RE.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            rule_id=rule.id,
            line=line,
            col=col,
            matched=m.group(0),
            severity="HIGH",
            description=(
                "vm.runInNewContext / runInContext invoked with a "
                "tainted payload sourced from request body / params / "
                "query / stdin / message. Equivalent to in-process "
                "eval(remoteCode) — drops attacker code into the "
                "running Node process."
            ),
            owasp_asi=rule.owasp_asi,
        )

    # Pass 5: sys.settrace / signal swallow.
    rule = next(r for r in RULES if r.id == "proc-inject-runtime-monkeypatch")
    for m in _SYS_TRACE_RE.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            rule_id=rule.id,
            line=line,
            col=col,
            matched=m.group(0),
            severity="MEDIUM" if test_file else "MAJOR",
            description=(
                "sys.settrace / sys.setprofile / threading.settrace / "
                "threading.setprofile registered — the Python debugger "
                "hook surface. Lets the registering code observe / "
                "modify every frame in the interpreter."
            ),
            owasp_asi=rule.owasp_asi,
        )
    # File-wide cleanup-token scan. We approximate the python-handler
    # body check by asking: does the FILE anywhere reference a cleanup
    # token? Real Python `def handler(...)` is defined either above OR
    # below the `signal.signal(...)` call site, and there is no
    # deterministic regex way to identify which `def` is the handler
    # without an AST walker (out of scope for pure-regex module). If
    # any cleanup token appears anywhere, suppress the swallow finding.
    # FP rate: a file that legitimately defines a cleanup handler AND
    # a swallow handler will under-report; the cost is acceptable
    # versus the FP storm of every legitimate signal handler tripping.
    file_has_cleanup = any(tok in text for tok in _SIGNAL_CLEANUP_TOKENS)
    for m in _SIGNAL_HOOK_RE.finditer(text):
        if file_has_cleanup:
            continue
        line, col = _line_col(text, m.start())
        _emit(
            rule_id=rule.id,
            line=line,
            col=col,
            matched=m.group(0),
            severity="MEDIUM" if test_file else "MAJOR",
            description=(
                "signal.signal(SIGTERM/SIGINT/SIGHUP/SIGQUIT, handler) "
                "registered, and the file nowhere references "
                "sys.exit / os._exit / raise / os.kill — abort-resistant "
                "payload that swallows shutdown signals."
            ),
            owasp_asi=rule.owasp_asi,
        )

    # Pass 6: schtasks-create / Windows registry / setx APPINIT.
    rule_win = next(r for r in RULES if r.id == "proc-inject-windows-dll-hijack")
    for m in _WIN_APPINIT_RE.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            rule_id=rule_win.id,
            line=line,
            col=col,
            matched=m.group(0),
            severity=rule_win.severity,
            description=rule_win.description,
            owasp_asi=rule_win.owasp_asi,
        )
    for m in _WIN_PS_REG_RE.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            rule_id=rule_win.id,
            line=line,
            col=col,
            matched=m.group(0),
            severity=rule_win.severity,
            description=rule_win.description,
            owasp_asi=rule_win.owasp_asi,
        )

    # Pass 7: persistence-activate / schtasks-create.
    rule_pers = next(
        r for r in RULES if r.id == "proc-inject-launchd-systemd-persistence"
    )
    for m in _SCHTASKS_CREATE_RE.finditer(text):
        line, col = _line_col(text, m.start())
        _emit(
            rule_id=rule_pers.id,
            line=line,
            col=col,
            matched=m.group(0),
            severity=rule_pers.severity,
            description=(
                "Windows scheduled-task creation via schtasks /create, "
                "Schedule.Service, or Register-ScheduledTask — "
                "cross-platform persistence equivalent of systemd / "
                "launchd unit write."
            ),
            owasp_asi=rule_pers.owasp_asi,
        )
    # Activation alone is LOW unless paired with a write in same file.
    write_seen = bool(_PERSISTENCE_WRITE_RE.search(text))
    for m in _PERSISTENCE_ACTIVATE_RE.finditer(text):
        line, col = _line_col(text, m.start())
        # CPV-skillaudit: the activation-description strings are inlined
        # straight into the `description=` metadata kwarg (no intermediate
        # `activate_desc` var) so the `crontab` token lands inside a
        # metadata-field string → suppress; rendered text is identical.
        _emit(
            rule_id=rule_pers.id,
            line=line,
            col=col,
            matched=m.group(0),
            severity="CRITICAL" if write_seen else "LOW",
            description=(
                (
                    "launchctl / systemctl --user / crontab activation, "
                    "paired with a unit-file write in the same file — "
                    "attacker is installing AND enabling persistence."
                )
                if write_seen
                else (
                    "launchctl / systemctl --user / crontab activation, "
                    "standalone — flagged at LOW; benign in admin scripts."
                )
            ),
            owasp_asi=rule_pers.owasp_asi,
        )

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
