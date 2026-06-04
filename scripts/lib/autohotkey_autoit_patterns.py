"""AutoHotkey / AutoIt scripting risk patterns.

Wave-33 distillation round 19, AutoHotkey/AutoIt angle.

Catalogue of 10 AHK/AutoIt-specific attack patterns distilled in
`reports/distill-round-19/autohotkey-autoit-risks.md`. Targets `.ahk`
and `.au3` source files, plus inline AHK/AutoIt string literals embedded
in `.py`, `.ps1`, `.bat`, `.cmd` dropper scripts.

Scope guard — NOT duplicated here:
  * Compiled PE/ELF binary detection (MZ magic) — binary_magic_scanner.py.
  * curl|bash / wget|sh shell-piped downloads — supply_chain_fingerprints.py.
  * Claude hook writes — ai_context_poisoning.py.
  * GHA expression injection — workflow_security.py.

What IS here (10 net-new rules, regex-only, all RE2-safe):

  * aha-dllcall-ntdll-syscall            (CRITICAL)
  * aha-guicontrol-hidden-keylogger      (MAJOR)
  * aha-send-raw-credentials             (MAJOR)
  * aha-fileinstall-payload-dropper      (CRITICAL)
  * aha-processclose-edr-evasion         (CRITICAL)
  * aha-com-objcreate-excel-macro        (MAJOR)
  * aha-run-shellexecute-controlled-path (CRITICAL)
  * aha-dllcall-loadlibrary-manual-api   (CRITICAL)
  * aha-winhttp-exfil-c2                 (MAJOR)
  * aha-persistence-schtask-regwrite     (MAJOR)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-02 — Tool misuse / secret abuse (DllCall API abuse, COM automation)
  ASI-03 — Privilege escalation (ProcessClose AV, schtasks persistence)
  ASI-04 — Supply-chain (FileInstall payload dropper)
  ASI-05 — Unexpected code execution (DllCall ntdll, Run/ShellExecute,
                                       LoadLibrary reflective DLL)
  ASI-06 — Sensitive data exposure (keylogger, credential replay, C2 exfil)

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    auth_flow_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# NOTE: All patterns use triple-quoted raw strings (r"""...""") throughout
# to avoid quote-escaping conflicts between the Python string delimiter and
# the regex character classes (e.g. ["'] requires the surrounding string to
# use a delimiter that doesn't terminate on either quote character).

# ---- AAR-01 : DllCall to ntdll / NT API direct syscall ------------------

_DLLCALL_NTDLL_COMBINED = _re(
    r"""(?x)
    \bDllCall\s*\(\s*["']ntdll(?:\.dll)?\s*\\[^"']{3,60}["']
    |
    \bDllCall\s*\([^,)]{0,60}
    (?:NtAllocateVirtualMemory|NtWriteVirtualMemory|NtCreateThreadEx
    |NtProtectVirtualMemory|NtUnmapViewOfSection)\b
    """
)

# ---- AAR-02 : GuiControl / hidden-window input interception -------------

_GUICONTROL_KEYLOGGER_COMBINED = _re(
    r"""(?x)
    \bGui\s*,\s*(?:[+])?(?:LastFound|Show)\b[^`\n]{0,120}
    (?:Hide|Transparent|invisible)
    |
    \bInput\s*,\s*\w+\s*,\s*[^,\n]{0,60}(?:V|L\d{4,})\b
    """
)

# ---- AAR-03 : Send raw keystrokes / credential replay -------------------

# AutoIt ControlSend with variable into named window.
# Quote class ["'] requires triple-quoted string to avoid early termination.
_SEND_CREDENTIALS_COMBINED = _re(
    r"""\bControlSend\s*\(\s*["'][^"']{5,80}["']\s*,\s*["']{1,2}\s*,"""
    r"""\s*["'][^"']{0,30}["']\s*,\s*\$\w+"""
    r"""|"""
    r"""\bWinWaitActive\s*\([^)]{5,100}\)[\s\S]{0,200}"""
    r"""\b(?:SendRaw|SendInput|Send)\s*,\s*%\w+%"""
)

# ---- AAR-04 : FileInstall payload dropper (Aut2Exe) ---------------------

_FILEINSTALL_COMBINED = _re(
    r"""\bFileInstall\s*\(\s*["'][^"']{1,120}"""
    r"""\.(?:exe|dll|ps1|bat|vbs|js|sh)["']"""
    r"""|"""
    r"""\bFileInstall\s*\([^)]{0,200}"""
    r"""@(?:TempDir|AppDataDir|WindowsDir|SystemDir|ProgramsDir)\b"""
)

# ---- AAR-05 : ProcessClose targeting AV/EDR processes -------------------

_PROCESSCLOSE_EDR_COMBINED = _re(
    r"""\bProcessClose\s*\(\s*["'][^"']{0,60}"""
    r"""(?:MsMpEng|avp|egui|bdagent|SentinelAgent|csc|MBAMService|kavts"""
    r"""|ns[a-z]{2})[^"']{0,20}["']"""
    r"""|\bProcess\s*,\s*Close\s*,[^`\n]{0,80}"""
    r"""(?:MsMpEng|avp|egui|bdagent|SentinelAgent|csc|MBAMService|kavts)\b"""
)

# ---- AAR-06 : COM ObjCreate Excel/Office macro launcher -----------------

_COM_OBJCREATE_COMBINED = _re(
    r"""\bObjCreate\s*\(\s*["']"""
    r"""(?:Excel\.Application|Word\.Application|WScript\.Shell"""
    r"""|Shell\.Application|Scripting\.FileSystemObject"""
    r"""|MSXML2\.[A-Za-z]{3,40})["']"""
    r"""|\bCom(?:ObjCreate|Object)\s*\(\s*["']"""
    r"""(?:Excel\.Application|Word\.Application|WScript\.Shell"""
    r"""|Shell\.Application)["']"""
)

# ---- AAR-07 : Run / ShellExecute with controlled path + Hide ------------

_RUN_SHELLEXEC_COMBINED = _re(
    r"""\bRun\s*,\s*%\w+%[^`\n]{0,80}(?:Hide|Minimize)\b"""
    r"""|\b(?:Run|ShellExecute)\s*\(\s*"""
    r"""(?:\$\w+|%\w+%|@(?:TempDir|AppDataDir|WindowsDir|SystemDir))"""
    r"""[^)]{0,100}\)"""
    r"""|\bRun\s*[,(]\s*[^`\n]{0,30}"""
    r"""(?:powershell|cmd)(?:\.exe)?\s+[^`\n]{0,80}"""
    r"""(?:-enc|-EncodedCommand|-e\s)[^`\n]{0,200}"""
)

# ---- AAR-08 : DllCall LoadLibrary / GetProcAddress manual API -----------

_LOADLIB_COMBINED = _re(
    r"""\bDllCall\s*\(\s*["'](?:LoadLibrary[AW]?|GetProcAddress)["']"""
    r"""|\bDllCallAddress\s*\(\s*\w+[^)]{0,200}\bGetProcAddress\b"""
)

# ---- AAR-09 : WinHttp.WinHttpRequest C2 / data exfil --------------------

_WINHTTP_COMBINED = _re(
    r"""\b(?:ObjCreate|ComObjCreate|ComObject)\s*\(\s*["']"""
    r"""WinHttp\.WinHttpRequest[^"']{0,20}["']"""
    r"""|\.(?:Send|Open)\s*\(\s*["']POST["']"""
    r"""|\bDllCall\s*\(\s*["']winhttp(?:\.dll)?\\[^"']{3,60}["']"""
)

# ---- AAR-10 : RegWrite / schtasks persistence install -------------------

_PERSISTENCE_COMBINED = _re(
    r"""\bRegWrite\s*,\s*REG_SZ\s*,"""
    r"""\s*HK(?:CU|LM|EY_CURRENT_USER|EY_LOCAL_MACHINE)[^`\n]{0,100}"""
    r"""CurrentVersion\\Run\b"""
    r"""|\bRegWrite\s*\(\s*["']"""
    r"""HK(?:EY_)?(?:CURRENT_USER|LOCAL_MACHINE)[^"']{0,100}"""
    r"""CurrentVersion\\Run["']"""
    r"""|\b(?:Run|ShellExecute)\s*[,(][^)]{0,200}schtasks[^)]{0,100}/create\b"""
)


# ---- Rule catalogue -----------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="aha-dllcall-ntdll-syscall",
        name="DllCall to ntdll / NT API direct syscall",
        severity="CRITICAL",
        description=(
            "AHK DllCall targeting ntdll.dll NT functions "
            "(NtAllocateVirtualMemory, NtWriteVirtualMemory, NtCreateThreadEx, "
            "NtProtectVirtualMemory, NtUnmapViewOfSection). Used by "
            "AsyncRAT/Remcos AHK loaders to inject shellcode bypassing "
            "user-mode AV hooks at the kernel32/kernelbase layer."
        ),
        pattern=_DLLCALL_NTDLL_COMBINED,
        owasp_asi="ASI-05, ASI-02",
    ),
    Rule(
        id="aha-guicontrol-hidden-keylogger",
        name="GuiControl hidden window input interception",
        severity="MAJOR",
        description=(
            "AHK Gui Show with Hide/Transparent flag combined with Input "
            "command capturing keystrokes. Banking trojans use this pattern "
            "to intercept credentials typed into browser password fields via "
            "an invisible global keylogger window."
        ),
        pattern=_GUICONTROL_KEYLOGGER_COMBINED,
        owasp_asi="ASI-02, ASI-06",
    ),
    Rule(
        id="aha-send-raw-credentials",
        name="ControlSend / SendRaw credential replay into active window",
        severity="MAJOR",
        description=(
            "AutoIt ControlSend or AHK SendRaw/SendInput replaying a "
            "captured variable into a specific named window. Used to inject "
            "harvested credentials into banking/login windows without user "
            "visibility (form-fill / session-hijack primitive)."
        ),
        pattern=_SEND_CREDENTIALS_COMBINED,
        owasp_asi="ASI-06, ASI-02",
    ),
    Rule(
        id="aha-fileinstall-payload-dropper",
        name="FileInstall payload embedding in Aut2Exe compiled EXE",
        severity="CRITICAL",
        description=(
            "AutoIt FileInstall directive embedding an executable (.exe, "
            ".dll, .ps1, .bat, .vbs, .js, .sh) or dropping to system/temp "
            "paths (@TempDir, @AppDataDir). Used by commodity RAT loaders "
            "(AsyncRAT, Remcos, DcRAT) to hide payloads inside an "
            "Aut2Exe-compiled standalone EXE."
        ),
        pattern=_FILEINSTALL_COMBINED,
        owasp_asi="ASI-04, ASI-05",
    ),
    Rule(
        id="aha-processclose-edr-evasion",
        name="ProcessClose targeting AV/EDR process names",
        severity="CRITICAL",
        description=(
            "AutoIt ProcessClose() or AHK Process, Close targeting known "
            "AV/EDR process names (MsMpEng, avp, egui, bdagent, "
            "SentinelAgent, csc, MBAMService, kavts). Used by dropper "
            "scripts to disable endpoint protection before executing payload."
        ),
        pattern=_PROCESSCLOSE_EDR_COMBINED,
        owasp_asi="ASI-03, ASI-05",
    ),
    Rule(
        id="aha-com-objcreate-excel-macro",
        name="COM ObjCreate Excel/Office macro launcher",
        severity="MAJOR",
        description=(
            "AHK ComObjCreate/ComObject or AutoIt ObjCreate instantiating "
            "Excel.Application, Word.Application, WScript.Shell, or "
            "Shell.Application. Used to silently open macro-enabled workbooks "
            "or directly execute VBA, bypassing PowerShell execution policy."
        ),
        pattern=_COM_OBJCREATE_COMBINED,
        owasp_asi="ASI-05, ASI-02",
    ),
    Rule(
        id="aha-run-shellexecute-controlled-path",
        name="Run / ShellExecute with controlled path and Hide flag",
        severity="CRITICAL",
        description=(
            "AHK Run with variable path and Hide/Minimize flag, AutoIt "
            "Run/ShellExecute from system/temp directories, or "
            "cmd.exe/PowerShell launcher with base64-encoded payload. "
            "Final execution stage in AHK dropper chains after FileInstall "
            "or WinHttp download."
        ),
        pattern=_RUN_SHELLEXEC_COMBINED,
        owasp_asi="ASI-05",
    ),
    Rule(
        id="aha-dllcall-loadlibrary-manual-api",
        name="DllCall LoadLibrary / GetProcAddress manual IAT reconstruction",
        severity="CRITICAL",
        description=(
            "AHK DllCall('LoadLibraryA/W') or DllCall('GetProcAddress') "
            "implementing reflective DLL injection / manual import-address-table "
            "reconstruction. Defeats static analysis tools looking for named "
            "DllCall references. Appears in AHK stagers loading payload DLLs "
            "fetched from the network or extracted from resource sections."
        ),
        pattern=_LOADLIB_COMBINED,
        owasp_asi="ASI-05, ASI-02",
    ),
    Rule(
        id="aha-winhttp-exfil-c2",
        name="WinHttp.WinHttpRequest C2 beacon / data exfiltration",
        severity="MAJOR",
        description=(
            "AutoIt ObjCreate or AHK ComObjCreate/ComObject instantiating "
            "WinHttp.WinHttpRequest.5.1, POST send with data variable, or "
            "direct DllCall into winhttp.dll. Used for C2 polling, "
            "second-stage payload download, and credential/clipboard exfiltration "
            "over HTTPS with custom headers."
        ),
        pattern=_WINHTTP_COMBINED,
        owasp_asi="ASI-06, ASI-02",
    ),
    Rule(
        id="aha-persistence-schtask-regwrite",
        name=r"RegWrite CurrentVersion\Run / schtasks persistence install",
        severity="MAJOR",
        description=(
            "AHK RegWrite or AutoIt RegWrite targeting HKCU/HKLM "
            "CurrentVersion\\Run for reboot persistence, or schtasks /create "
            "via Run/ShellExecute for scheduled-task persistence. Most common "
            "persistence mechanism in AHK/AutoIt malware families; requires "
            "no elevated privilege under HKCU."
        ),
        pattern=_PERSISTENCE_COMBINED,
        owasp_asi="ASI-03, ASI-05",
    ),
)


# ---- Helper utilities ---------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)



# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every RULES pattern against `text` and return findings.

    Each rule uses its pre-compiled combined pattern for a single-pass scan.
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

    # AAR-01: DllCall ntdll direct syscall
    rule_01 = rule_by_id["aha-dllcall-ntdll-syscall"]
    for m in _DLLCALL_NTDLL_COMBINED.finditer(text):
        _emit(rule_01, m.start(), m.group(0))

    # AAR-02: GuiControl hidden keylogger
    rule_02 = rule_by_id["aha-guicontrol-hidden-keylogger"]
    for m in _GUICONTROL_KEYLOGGER_COMBINED.finditer(text):
        _emit(rule_02, m.start(), m.group(0))

    # AAR-03: Send / ControlSend credential replay
    rule_03 = rule_by_id["aha-send-raw-credentials"]
    for m in _SEND_CREDENTIALS_COMBINED.finditer(text):
        _emit(rule_03, m.start(), m.group(0))

    # AAR-04: FileInstall payload dropper
    rule_04 = rule_by_id["aha-fileinstall-payload-dropper"]
    for m in _FILEINSTALL_COMBINED.finditer(text):
        _emit(rule_04, m.start(), m.group(0))

    # AAR-05: ProcessClose AV/EDR evasion
    rule_05 = rule_by_id["aha-processclose-edr-evasion"]
    for m in _PROCESSCLOSE_EDR_COMBINED.finditer(text):
        _emit(rule_05, m.start(), m.group(0))

    # AAR-06: COM ObjCreate Excel macro
    rule_06 = rule_by_id["aha-com-objcreate-excel-macro"]
    for m in _COM_OBJCREATE_COMBINED.finditer(text):
        _emit(rule_06, m.start(), m.group(0))

    # AAR-07: Run / ShellExecute controlled path
    rule_07 = rule_by_id["aha-run-shellexecute-controlled-path"]
    for m in _RUN_SHELLEXEC_COMBINED.finditer(text):
        _emit(rule_07, m.start(), m.group(0))

    # AAR-08: DllCall LoadLibrary manual API resolution
    rule_08 = rule_by_id["aha-dllcall-loadlibrary-manual-api"]
    for m in _LOADLIB_COMBINED.finditer(text):
        _emit(rule_08, m.start(), m.group(0))

    # AAR-09: WinHttp C2 / exfil
    rule_09 = rule_by_id["aha-winhttp-exfil-c2"]
    for m in _WINHTTP_COMBINED.finditer(text):
        _emit(rule_09, m.start(), m.group(0))

    # AAR-10: Persistence via RegWrite / schtasks
    rule_10 = rule_by_id["aha-persistence-schtask-regwrite"]
    for m in _PERSISTENCE_COMBINED.finditer(text):
        _emit(rule_10, m.start(), m.group(0))

    return findings
