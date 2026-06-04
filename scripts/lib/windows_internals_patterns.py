"""Windows system-internals attack-pattern catalogue.

Wave-23 distillation round 9 — Windows runtime-memory + policy-disable
layer (orthogonal to ``process_injection_patterns.py``, whose
``proc-inject-windows-dll-hijack`` rule only covers the registry-loader
hijack triplet ``AppInit_DLLs`` / IFEO / ``KnownDLLs``).

Source report:
``reports/distill-round-9/windows-system-internals.md``.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * winint-lsass-minidump                                       (CRITICAL)
  * winint-amsi-patch                                           (CRITICAL)
  * winint-etw-patch                                            (CRITICAL)
  * winint-direct-syscall                                       (CRITICAL)
  * winint-com-hijack-treatas                                   (HIGH)
  * winint-sedebug-privilege                                    (HIGH)
  * winint-reflective-assembly-load                             (CRITICAL)
  * winint-defender-tamper                                      (HIGH)
  * winint-ps-encoded-cradle                                    (HIGH)
  * winint-motw-strip                                           (MEDIUM)

What is NOT here (already shipped — DO NOT duplicate):

  * Registry-based loader hijack (``AppInit_DLLs``, IFEO, ``KnownDLLs``)
    — ``process_injection_patterns.py`` rule ``proc-inject-windows-dll-hijack``.
  * ``powershell -enc`` inside JetBrains IDE run configs only —
    ``ide_editor_patterns.py``. This module catches the generic
    ``-EncodedCommand`` download cradle anywhere in source.

Public surface:

  * ``Rule(id, name, severity, description, pattern, owasp_asi)``
  * ``RULES`` — ordered tuple of every rule.
  * ``scan_text(text) -> list[Finding]``
  * ``Finding(rule_id, line, column, matched_text, severity,
    description, owasp_asi)`` — frozen NamedTuple, mirrors
    ``chat_bot_patterns.Finding`` / ``webhook_signature_patterns.Finding``.

OWASP ASI mapping used:
  ASI-02 — Insecure direct access (credential material extracted from
                                    memory — LSASS minidump,
                                    SeDebugPrivilege chain).
  ASI-04 — Information leak / unrestricted library install (PowerShell
                                                              download
                                                              cradle,
                                                              MOTW
                                                              strip).
  ASI-06 — Insecure runtime environment (token-privilege elevation
                                          beyond the role the runtime
                                          spec grants).
  ASI-07 — Untrusted plugin/skill execution (reflective .NET load of a
                                              downloaded byte blob).
  ASI-08 — Insecure agent runtime (tampering with the safety hooks the
                                    host expects — AMSI / ETW patch,
                                    direct syscalls, Defender tamper).
  ASI-10 — Persistence and recovery abuse (COM hijack via TreatAs /
                                            InprocServer32 redirect).

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    chat_bot_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- W1 : winint-lsass-minidump -----------------------------------------


# Trigger A — opens a handle / queries the lsass process by name.
_LSASS_HANDLE_OPEN = _re(
    r"\b(?:OpenProcess|GetProcessByName|Get-Process)\s*\(?\s*"
    r"['\"]?lsass(?:\.exe)?['\"]?"
)

# Trigger B — a minidump primitive (MiniDumpWriteDump,
# procdump64.exe -ma, comsvcs.dll, MiniDump, rundll32 ... MiniDump).
_LSASS_DUMP_PRIMITIVE = _re(
    r"\bMiniDumpWriteDump\b"
    r"|"
    r"\bprocdump(?:64)?\.exe\s+(?:[^\n]{0,40}\s)?-ma\b"
    r"|"
    r"\bcomsvcs\.dll\s*,\s*MiniDump\b"
    r"|"
    r"\brundll32(?:\.exe)?\s+\S+comsvcs\.dll[^,\n]*,\s*MiniDump\b"
)

# Telemetry / passive-introspection FP suppression — defenders open
# lsass purely for query-limited-information without VM_READ /
# DUP_HANDLE access rights.
_LSASS_TELEMETRY_ACCESS_ONLY = _re(
    r"\bPROCESS_QUERY_LIMITED_INFORMATION\b"
)

_LSASS_DANGEROUS_ACCESS = _re(
    r"\bPROCESS_VM_READ\b"
    r"|"
    r"\bPROCESS_DUP_HANDLE\b"
    r"|"
    r"\bPROCESS_ALL_ACCESS\b"
)


# ---- W2 : winint-amsi-patch ---------------------------------------------


# Resolves the address of amsi.dll / AmsiScanBuffer / AmsiInitialize.
_AMSI_RESOLVE = _re(
    r"\b(?:GetProcAddress|GetModuleHandle|LoadLibrary(?:Ex)?[AW]?)\s*"
    r"\(\s*[^)]{0,80}\b"
    r"(?:amsi(?:\.dll)?|AmsiScanBuffer|AmsiInitialize)\b"
)

# Memory-write primitive (overwrite the AMSI scan entry-point bytes).
_MEMORY_WRITE_PRIMITIVE = _re(
    r"\bWriteProcessMemory\b"
    r"|"
    r"\bVirtualProtect(?:Ex)?\b"
    r"|"
    r"\bMarshal\s*::\s*Copy\b"
    r"|"
    r"\bMarshal\.Copy\b"
)


# ---- W3 : winint-etw-patch ----------------------------------------------


# Resolves the address of ntdll!EtwEventWrite / EtwEventRegister /
# EtwEventWriteFull / EtwNotificationRegister / NtTraceEvent.
_ETW_RESOLVE = _re(
    r"\b(?:GetProcAddress|GetModuleHandle|LoadLibrary(?:Ex)?[AW]?)\s*"
    r"\(\s*[^)]{0,80}\b"
    r"(?:EtwEventWrite(?:Full)?|EtwEventRegister"
    r"|EtwNotificationRegister|NtTraceEvent)\b"
)


# ---- W4 : winint-direct-syscall -----------------------------------------


# C# P/Invoke of a dangerous ntdll!Nt* function.
_NTDLL_NT_DLLIMPORT = _re(
    r"\[DllImport\s*\(\s*['\"]?ntdll(?:\.dll)?['\"]?[^)]*\)\]"
    r"\s*"
    r"(?:public|private|internal|static|extern|\s)+\s+"
    r"\w+\s+"
    r"Nt(?:AllocateVirtualMemory|ProtectVirtualMemory"
    r"|WriteVirtualMemory|CreateThreadEx|MapViewOfSection"
    r"|UnmapViewOfSection|OpenProcess|QueueApcThread"
    r"|Map(?:User)?PhysicalPages)\b"
)

# D/Invoke-style direct SysCall(0xNN) or DInvoke::DynamicAPIInvoke.
_DIRECT_SYSCALL_KEYWORD = _re(
    r"\bSysCall\s*\(\s*0x[0-9A-Fa-f]{1,3}\b"
    r"|"
    r"\bDInvoke(?:_rs)?\s*::\s*DynamicAPIInvoke\b"
)

# Quartet check — the dangerous user-mode-evasion set.
_NT_DANGEROUS_QUARTET_MEMBER = _re(
    r"\bNt(?:AllocateVirtualMemory|ProtectVirtualMemory"
    r"|WriteVirtualMemory|CreateThreadEx)\b"
)


# ---- W5 : winint-com-hijack-treatas -------------------------------------


# Registry-write primitive (reg.exe / Set-ItemProperty / RegSetValueEx /
# RegCreateKeyEx) hitting a CLSID subkey whose terminal segment is
# TreatAs / InprocServer32 / InprocServer64 / LocalServer32 /
# LocalServer64.
_COM_HIJACK_TREATAS = _re(
    r"\b(?:reg\s+(?:add|import)"
    r"|Set-ItemProperty|New-ItemProperty"
    r"|RegSetValue(?:Ex)?[AW]?|RegCreateKey(?:Ex)?[AW]?)\b"
    r"[^\n]{0,200}\bHK(?:CU|EY_CURRENT_USER|LM|EY_LOCAL_MACHINE)"
    r"(?::\\|\\\\|\\)"
    r"Software(?:\\\\|\\)Classes(?:\\\\|\\)CLSID(?:\\\\|\\)"
    r"\{[0-9A-Fa-f\-]{36}\}(?:\\\\|\\)"
    r"(?:TreatAs|InprocServer(?:32|64)|LocalServer(?:32|64))\b"
)


# ---- W6 : winint-sedebug-privilege --------------------------------------


# Token-API primitive that participates in the AdjustTokenPrivileges
# chain.
_TOKEN_API_PRIMITIVE = _re(
    r"\b(?:OpenProcessToken|GetCurrentProcessToken"
    r"|AdjustTokenPrivileges|SetTokenInformation)\b"
)

# Privilege name lookup — LookupPrivilegeValueA/W or the TOKEN_PRIVILEGES
# struct literal.
_PRIVILEGE_LOOKUP = _re(
    r"\bLookupPrivilegeValue[AW]?\b"
    r"|"
    r"\bTOKEN_PRIVILEGES\b"
)

# The privilege names that have no benign rationale in ordinary
# build/test code.
_DANGEROUS_PRIVILEGE_NAME = _re(
    r"\bSe(?:Debug|Impersonate|Tcb|AssignPrimaryToken"
    r"|TakeOwnership|Restore)Privilege\b"
)

# FP suppression — sysinternals / windbg / dbghelp file paths.
_DEBUG_TOOLING_PATH_HINT = _re(
    r"/sysinternals/"
    r"|"
    r"/procmon/"
    r"|"
    r"/procexp/"
    r"|"
    r"/windbg/"
    r"|"
    r"/dbghelp/"
    r"|"
    r"\bDBG_PRIV_NOTIFY\b"
)


# ---- W7 : winint-reflective-assembly-load -------------------------------


# [Reflection.Assembly]::Load([byte[]] (... DownloadData / etc.))
_REFLECTION_LOAD_INLINE = _re(
    r"\[(?:Reflection\.)?Assembly\]\s*::\s*Load\s*\(\s*"
    r"\[byte\[\]\]\s*\(?[^)]*"
    r"(?:DownloadData|DownloadString|GetByteArrayAsync"
    r"|ReadAllBytes|FromBase64String)"
)

# Assembly.Load(<var>) — Stage-B check that <var> was assigned from a
# download/decode primitive within the prior window. Covers both
# `Assembly.Load(rawAssembly)` (C#) and
# `[Reflection.Assembly]::Load([byte[]]$bytes)` (PowerShell).
_ASSEMBLY_LOAD_VAR = _re(
    r"\bAssembly\.Load\s*\(\s*"
    r"(?:rawAssembly|payload|buffer|bytes|data|asmBytes|dllBytes)\s*\)"
    r"|"
    r"\[(?:Reflection\.)?Assembly\]\s*::\s*Load\s*\(\s*\[byte\[\]\]\s*\$?"
    r"(?:rawAssembly|payload|buffer|bytes|data|asmBytes|dllBytes)\s*\)"
)

_BYTE_SOURCE_PRIMITIVE = _re(
    r"\b(?:DownloadData|DownloadString|GetByteArrayAsync"
    r"|FromBase64String|ReadAllBytes)\b"
)


# ---- W8 : winint-defender-tamper ----------------------------------------


# Set-MpPreference -Disable<X> $true / 1 — disables Defender's
# protection surface.
_DEFENDER_DISABLE = _re(
    r"\bSet-MpPreference\b[^|;\n]*-Disable"
    r"(?:RealtimeMonitoring|BehaviorMonitoring|IOAVProtection"
    r"|ScriptScanning|BlockAtFirstSeen|IntrusionPreventionSystem)\b"
    r"\s+\$?(?:true|1)\b"
)

# Add-MpPreference -ExclusionPath / -ExclusionProcess /
# -ExclusionExtension — carves a hole in Defender's coverage.
_DEFENDER_EXCLUSION = _re(
    r"\bAdd-MpPreference\b[^|;\n]*-"
    r"(?:ExclusionPath|ExclusionProcess|ExclusionExtension)\s+"
)

# MpCmdRun -RemoveDefinitions -All — kills the signature database.
_MPCMDRUN_PURGE = _re(
    r"\bMpCmdRun(?:\.exe)?\b[^\n]{0,40}-RemoveDefinitions\b[^\n]{0,40}-All\b"
)


# ---- W9 : winint-ps-encoded-cradle --------------------------------------


# PowerShell launched with -EncodedCommand / -enc / -e plus a base64-ish
# body of length >= 32.
_PS_ENCODED_LAUNCH = _re(
    r"\b(?:powershell(?:\.exe)?|pwsh(?:\.exe)?)\b[^\n]*"
    r"-(?:e(?:nc(?:odedcommand)?)?)\b"
    r"\s+[A-Za-z0-9+/=]{32,}"
)

# Plain IEX | iwr / Invoke-RestMethod download cradle — no -enc required.
_PS_PLAIN_CRADLE = _re(
    r"\b(?:IEX|Invoke-Expression)\s*\(?\s*\(?\s*"
    r"(?:New-Object\s+Net\.WebClient"
    r"|Invoke-WebRequest|iwr|Invoke-RestMethod|irm)\b"
    r"|"
    r"\b(?:iwr|Invoke-WebRequest|Invoke-RestMethod|irm)\b"
    r"[^\n]{0,200}\|\s*(?:IEX|Invoke-Expression)\b"
)

# FP suppression — well-known bootstrap CDNs (Chocolatey / Scoop /
# aka.ms / dotnet.microsoft.com / azureedge.net / windows.com / PS
# release).
_PS_TRUSTED_HOST = _re(
    r"\bchocolatey\.org\b"
    r"|"
    r"\bcommunity\.chocolatey\.org\b"
    r"|"
    r"\bscoop\.sh\b"
    r"|"
    r"\bget\.scoop\.sh\b"
    r"|"
    r"\baka\.ms\b"
    r"|"
    r"\bdotnet\.microsoft\.com\b"
    r"|"
    r"\bazureedge\.net\b"
    r"|"
    r"\bwindows\.com\b"
    r"|"
    r"\bgithub\.com/PowerShell/PowerShell/releases/"
)


# ---- W10 : winint-motw-strip --------------------------------------------


# Unblock-File / Remove-Item ...:Zone.Identifier / Set-Content
# ...:Zone.Identifier / cmd /c type nul > ...:Zone.Identifier.
_MOTW_STRIP = _re(
    r"\bUnblock-File\b"
    r"|"
    r"\b(?:Remove-Item|Set-Content|Clear-Content)\b[^\n]{0,200}"
    r":Zone\.Identifier\b"
    r"|"
    r"\bcmd(?:\.exe)?\s+/c\s+type\s+nul\s*>\s*['\"]?[^\n'\"]{0,200}"
    r":Zone\.Identifier\b"
)

# Benign-target hint — paths under Program Files / Program Files (x86)
# / UNC share are legit (enterprise-mirrored SDK shape).
_MOTW_BENIGN_PATH = _re(
    r"['\"]?(?:[A-Z]:\\\\?|[A-Z]:\\)Program Files(?:\s*\(x86\))?\\"
    r"|"
    r"\\\\[A-Za-z0-9._\-]+\\[A-Za-z0-9$._\-]+"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="winint-lsass-minidump",
        name="LSASS handle acquired AND minidump primitive invoked",
        severity="CRITICAL",
        description=(
            "Source opens a handle to lsass (or its PID via "
            "Get-Process lsass) AND in the same window writes a "
            "minidump via MiniDumpWriteDump, procdump64.exe -ma, "
            "comsvcs.dll, MiniDump, or rundll32 ... comsvcs.dll, "
            "MiniDump. The minidump contains every credential cached "
            "in memory — classic Mimikatz-grade exfil staging."
        ),
        pattern=_LSASS_HANDLE_OPEN,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="winint-amsi-patch",
        name="In-process patch of amsi.dll!AmsiScanBuffer disabling Defender script-scan",
        severity="CRITICAL",
        description=(
            "Source resolves the address of "
            "amsi.dll!AmsiScanBuffer (or AmsiInitialize) and writes "
            "attacker-controlled bytes — typically `B8 57 00 07 80 "
            "C3` (mov eax, 0x80070057; ret) — using "
            "WriteProcessMemory, VirtualProtect, or Marshal.Copy. "
            "Subsequent scripts are reported as clean to every AMSI "
            "consumer (Defender, Office, PowerShell)."
        ),
        pattern=_AMSI_RESOLVE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="winint-etw-patch",
        name="In-process patch of ntdll!EtwEventWrite silencing kernel telemetry",
        severity="CRITICAL",
        description=(
            "Source resolves ntdll!EtwEventWrite (or "
            "EtwEventRegister / EtwEventWriteFull / "
            "EtwNotificationRegister / NtTraceEvent) and patches its "
            "first byte to 0xC3 (RET) or 0xC2 0x14 0x00 (RET 20). "
            "No ETW provider receives any event from this process — "
            "kernel-side telemetry silenced without driver privilege."
        ),
        pattern=_ETW_RESOLVE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="winint-direct-syscall",
        name="Direct ntdll!Nt* P/Invoke or SysCall opcode bypassing kernel32 hooks",
        severity="CRITICAL",
        description=(
            "C# source uses the SysCall keyword / DInvoke library, "
            "OR P/Invokes ntdll!Nt* directly "
            "(NtAllocateVirtualMemory, NtProtectVirtualMemory, "
            "NtWriteVirtualMemory, NtCreateThreadEx, "
            "NtMapViewOfSection) — bypassing the documented Win32 "
            "wrappers in kernel32 / advapi32 so that EDR user-mode "
            "hooks on kernel32!VirtualAllocEx never fire. Canonical "
            "EDR-evasion shape (Cobalt Strike sleep-mask, "
            "Hell's-Gate, Halo's-Gate)."
        ),
        pattern=_NTDLL_NT_DLLIMPORT,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="winint-com-hijack-treatas",
        name="COM hijack via HKCU\\Software\\Classes\\CLSID\\{...}\\TreatAs redirect",
        severity="HIGH",
        description=(
            "Source writes to HKCU\\Software\\Classes\\CLSID\\{guid}"
            "\\TreatAs (or InprocServer32 / LocalServer32) with an "
            "attacker-controlled path. Whenever any component "
            "instantiates the redirected CLSID it loads the "
            "attacker's DLL / EXE — a user-writable persistence + "
            "execution primitive that survives reboot and requires "
            "no admin."
        ),
        pattern=_COM_HIJACK_TREATAS,
        owasp_asi="ASI-10",
    ),
    Rule(
        id="winint-sedebug-privilege",
        name="SeDebugPrivilege / SeImpersonatePrivilege acquisition chain",
        severity="HIGH",
        description=(
            "Source calls OpenProcessToken + LookupPrivilegeValue + "
            "AdjustTokenPrivileges for SeDebugPrivilege "
            "(or SeImpersonate / SeTcb / SeAssignPrimaryToken / "
            "SeTakeOwnership / SeRestorePrivilege). Acquiring "
            "SeDebugPrivilege is a prerequisite for almost every "
            "post-exploitation move on Windows (LSASS dump, token "
            "impersonation, cross-context process injection). "
            "Ordinary build/test code never requests it."
        ),
        pattern=_TOKEN_API_PRIMITIVE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="winint-reflective-assembly-load",
        name="Assembly.Load of a downloaded / base64-decoded byte blob",
        severity="CRITICAL",
        description=(
            "PowerShell / C# source downloads a byte blob (via "
            "Invoke-WebRequest, Net.WebClient.DownloadData, "
            "HttpClient.GetByteArrayAsync, ReadAllBytes of an "
            "attacker-staged file, or FromBase64String) and "
            "immediately calls [Reflection.Assembly]::Load([byte[]]) "
            "/ Assembly.Load(rawAssembly) / "
            "AppDomain.CurrentDomain.Load(rawAssembly). The "
            "assembly runs entirely in memory — no Add-Type, no "
            "on-disk DLL, no MOTW prompt, no SmartScreen verdict."
        ),
        pattern=_REFLECTION_LOAD_INLINE,
        owasp_asi="ASI-07",
    ),
    Rule(
        id="winint-defender-tamper",
        name="Windows Defender tamper — disable real-time / add exclusion / wipe signatures",
        severity="HIGH",
        description=(
            "Source executes Set-MpPreference "
            "-DisableRealtimeMonitoring $true (or "
            "-DisableBehaviorMonitoring, -DisableIOAVProtection, "
            "-DisableScriptScanning), Add-MpPreference "
            "-ExclusionPath / -ExclusionProcess / "
            "-ExclusionExtension, or MpCmdRun.exe -RemoveDefinitions "
            "-All. All of these disable Defender's protection "
            "surface from inside a target session — the canonical "
            "first-step of an interactive intrusion."
        ),
        pattern=_DEFENDER_DISABLE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="winint-ps-encoded-cradle",
        name="powershell -EncodedCommand or iwr|iex download cradle from untrusted host",
        severity="HIGH",
        description=(
            "A PowerShell command line is launched with "
            "-EncodedCommand / -enc / -e (often combined with "
            "-NoProfile, -WindowStyle Hidden, -ExecutionPolicy "
            "Bypass) whose decoded body contains the classic "
            "download cradle: (New-Object "
            "Net.WebClient).DownloadString(URL) | IEX, "
            "iwr URL | iex, or Invoke-RestMethod URL | IEX. "
            "Plain (un-encoded) iwr|iex from a non-trusted host "
            "also matches."
        ),
        pattern=_PS_ENCODED_LAUNCH,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="winint-motw-strip",
        name="Mark-of-the-Web stripped from a Downloads / Temp path file",
        severity="MEDIUM",
        description=(
            "Source removes the Zone.Identifier Alternate Data "
            "Stream (ADS) from a downloaded file via Unblock-File "
            "-Path, Remove-Item -Path '<file>:Zone.Identifier', "
            "cmd /c type nul > '<file>:Zone.Identifier', or "
            "Set-Content -Path '<file>:Zone.Identifier' -Value ''. "
            "Stripping MOTW suppresses SmartScreen and Office's "
            "Protected-View / MOTW warnings for the downloaded "
            "payload — critical step in phishing → execution on "
            "Windows 10/11."
        ),
        pattern=_MOTW_STRIP,
        owasp_asi="ASI-04",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_forward(text: str, line_no: int, lines: int) -> str:
    """Return the next ``lines`` lines starting at ``line_no`` (1-based)."""
    parts = text.split("\n")
    start = max(0, line_no - 1)
    end = min(len(parts), start + lines)
    return "\n".join(parts[start:end])


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to ``backward`` lines preceding ``line_no`` plus
    ``line_no`` itself plus the next ``forward`` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against ``text`` and return findings.

    Stage-B filters consult adjacent lines for context:

      * W1 (lsass-minidump) — require an LSASS handle-open trigger
        AND a minidump primitive within 30 lines. Suppress when the
        only access right is PROCESS_QUERY_LIMITED_INFORMATION (no
        VM_READ / DUP_HANDLE / ALL_ACCESS).
      * W2 (amsi-patch) — require an amsi.dll / AmsiScanBuffer
        resolve AND a memory-write primitive within 30 lines (~600
        chars).
      * W3 (etw-patch) — require an EtwEventWrite / EtwEventRegister
        resolve AND a memory-write primitive within 30 lines.
      * W4 (direct-syscall) — Stage-A literal `[DllImport("ntdll")]`
        of a dangerous Nt* function is high-precision. Stage-B
        DInvoke / SysCall(0xNN) shapes additionally require a
        dangerous-quartet member elsewhere in the file.
      * W6 (sedebug-privilege) — anchor on the token-API primitive
        AND require BOTH a LookupPrivilegeValue / TOKEN_PRIVILEGES
        marker AND a dangerous-privilege name within 30 lines.
        Suppress when the file path / a comment in the 30-line
        window indicates sysinternals / windbg / dbghelp tooling.
      * W7 (reflective-assembly-load) — literal-shape inline match
        flags immediately. The `Assembly.Load(<var>)` shape requires
        a byte-source primitive in the prior 30 lines (assignment
        of the named buffer / payload / data variable).
      * W8 (defender-tamper) — anchor on Set-MpPreference -Disable,
        Add-MpPreference -Exclusion*, or MpCmdRun -RemoveDefinitions.
      * W9 (ps-encoded-cradle) — Stage-A `-EncodedCommand <b64>`
        always flags. Plain `iwr | iex` flags only when the
        surrounding 600 chars do NOT contain a trusted-CDN host.
      * W10 (motw-strip) — match Unblock-File / Zone.Identifier
        operations, BUT suppress when the same line / surrounding
        80 chars target Program Files / a UNC share (enterprise
        mirror).

    Findings are deduped by (rule_id, line, col).
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

    # ---- W1 : winint-lsass-minidump ----
    rule_w1 = rule_by_id["winint-lsass-minidump"]
    for m in _LSASS_HANDLE_OPEN.finditer(text):
        line, _ = _line_col(text, m.start())
        # 30-line forward window — minidump primitive usually appears
        # below the handle acquisition.
        window = _slice_window(text, line, 5, 30)
        if _LSASS_DUMP_PRIMITIVE.search(window) is None:
            continue
        # Telemetry suppression — if only query-limited access AND no
        # dangerous access right is present, do not flag.
        if (
            _LSASS_TELEMETRY_ACCESS_ONLY.search(window) is not None
            and _LSASS_DANGEROUS_ACCESS.search(window) is None
        ):
            continue
        _emit(rule_w1, m.start(), m.group(0))

    # Also catch the rundll32 / procdump shape directly — those don't
    # require an OpenProcess handle in the same file.
    for m in _LSASS_DUMP_PRIMITIVE.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 5)
        # Only emit the standalone dump-primitive shape when lsass is
        # the literal target — match the primitive text itself for
        # 'lsass' OR confirm presence in the surrounding window.
        primitive_text = m.group(0).lower()
        if "lsass" in primitive_text or "lsass" in window.lower():
            _emit(rule_w1, m.start(), m.group(0))

    # ---- W2 : winint-amsi-patch ----
    rule_w2 = rule_by_id["winint-amsi-patch"]
    for m in _AMSI_RESOLVE.finditer(text):
        line, _ = _line_col(text, m.start())
        # 30-line window (~600 chars) — memory-write primitive must
        # appear nearby.
        window = _slice_window(text, line, 5, 25)
        if _MEMORY_WRITE_PRIMITIVE.search(window) is None:
            continue
        _emit(rule_w2, m.start(), m.group(0))

    # ---- W3 : winint-etw-patch ----
    rule_w3 = rule_by_id["winint-etw-patch"]
    for m in _ETW_RESOLVE.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 25)
        if _MEMORY_WRITE_PRIMITIVE.search(window) is None:
            continue
        _emit(rule_w3, m.start(), m.group(0))

    # ---- W4 : winint-direct-syscall ----
    rule_w4 = rule_by_id["winint-direct-syscall"]
    # Stage-A: literal [DllImport("ntdll")] of an Nt* dangerous fn —
    # always high precision.
    for m in _NTDLL_NT_DLLIMPORT.finditer(text):
        _emit(rule_w4, m.start(), m.group(0))
    # Stage-B: DInvoke / SysCall opcode — require a quartet-member
    # presence anywhere in the file.
    has_quartet_member = _file_contains(text, _NT_DANGEROUS_QUARTET_MEMBER)
    if has_quartet_member:
        for m in _DIRECT_SYSCALL_KEYWORD.finditer(text):
            _emit(rule_w4, m.start(), m.group(0))

    # ---- W5 : winint-com-hijack-treatas ----
    rule_w5 = rule_by_id["winint-com-hijack-treatas"]
    for m in _COM_HIJACK_TREATAS.finditer(text):
        _emit(rule_w5, m.start(), m.group(0))

    # ---- W6 : winint-sedebug-privilege ----
    rule_w6 = rule_by_id["winint-sedebug-privilege"]
    # Per the report: anchor on token-API primitive AND require a
    # LookupPrivilegeValue / TOKEN_PRIVILEGES marker AND a
    # dangerous-privilege name within ~30 lines. Use file-level
    # context for the dangerous privilege name (script style often
    # spreads these declarations).
    has_priv_lookup = _file_contains(text, _PRIVILEGE_LOOKUP)
    has_dangerous_priv = _file_contains(text, _DANGEROUS_PRIVILEGE_NAME)
    has_debug_tooling = _file_contains(text, _DEBUG_TOOLING_PATH_HINT)
    if has_priv_lookup and has_dangerous_priv and not has_debug_tooling:
        for m in _TOKEN_API_PRIMITIVE.finditer(text):
            _emit(rule_w6, m.start(), m.group(0))

    # ---- W7 : winint-reflective-assembly-load ----
    rule_w7 = rule_by_id["winint-reflective-assembly-load"]
    # Stage-A: literal-shape inline match — always flag.
    for m in _REFLECTION_LOAD_INLINE.finditer(text):
        _emit(rule_w7, m.start(), m.group(0))
    # Stage-B: Assembly.Load(<var>) — require a byte-source primitive
    # in the 30-line prior window (variable assignment).
    for m in _ASSEMBLY_LOAD_VAR.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 30, 5)
        if _BYTE_SOURCE_PRIMITIVE.search(window) is not None:
            _emit(rule_w7, m.start(), m.group(0))

    # ---- W8 : winint-defender-tamper ----
    rule_w8 = rule_by_id["winint-defender-tamper"]
    for m in _DEFENDER_DISABLE.finditer(text):
        _emit(rule_w8, m.start(), m.group(0))
    for m in _DEFENDER_EXCLUSION.finditer(text):
        _emit(rule_w8, m.start(), m.group(0))
    for m in _MPCMDRUN_PURGE.finditer(text):
        _emit(rule_w8, m.start(), m.group(0))

    # ---- W9 : winint-ps-encoded-cradle ----
    rule_w9 = rule_by_id["winint-ps-encoded-cradle"]
    # Stage-A: -EncodedCommand <b64> always flags.
    for m in _PS_ENCODED_LAUNCH.finditer(text):
        _emit(rule_w9, m.start(), m.group(0))
    # Stage-B: plain `iwr | iex` flags only when the surrounding 30
    # lines do not contain a trusted-CDN host.
    for m in _PS_PLAIN_CRADLE.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 10, 20)
        if _PS_TRUSTED_HOST.search(window) is not None:
            continue
        _emit(rule_w9, m.start(), m.group(0))

    # ---- W10 : winint-motw-strip ----
    rule_w10 = rule_by_id["winint-motw-strip"]
    for m in _MOTW_STRIP.finditer(text):
        line, _ = _line_col(text, m.start())
        # Same-line context for benign-target suppression — match the
        # line itself.
        parts = text.split("\n")
        line_text = parts[line - 1] if 0 < line <= len(parts) else ""
        if _MOTW_BENIGN_PATH.search(line_text) is not None:
            continue
        _emit(rule_w10, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
