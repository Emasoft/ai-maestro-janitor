"""Tests for scripts/lib/macos_internals_patterns.py.

Pattern-coverage tests for the Wave-23 distill-round-9 macOS
system-internals catalogue (7 macOS-specific abuse primitives covering
Gatekeeper bypass, LaunchAgent persistence, launchctl activation,
spctl disable, Info.plist quarantine flips, sudoers NOPASSWD, and
DYLD_INSERT_LIBRARIES injection). Each rule has at least one positive
test exercising the canary AND at least one negative test exercising
the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import macos_internals_patterns as mip  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(mip.RULES, tuple)
    rule_ids = {r.id for r in mip.RULES}
    expected = {
        "macos-xattr-quarantine-clear",
        "macos-launchagent-plist-persistence",
        "macos-launchctl-activation-primitive",
        "macos-spctl-gatekeeper-disable",
        "macos-info-plist-quarantine-disable",
        "macos-sudoers-nopasswd-injection",
        "macos-dyld-insert-libraries-injection",
    }
    assert expected == rule_ids
    assert len(mip.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in mip.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = mip.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-03",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-03"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert mip.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — xattr -c in shell-string form
        'os.system("xattr -c /tmp/update")\n'
        # Line 2 — sudoers NOPASSWD line
        "runner ALL=(ALL) NOPASSWD:ALL\n"
    )
    findings = mip.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[mip.Finding]:
    return [f for f in mip.scan_text(text) if f.rule_id == rule_id]


# ---------- M1 : macos-xattr-quarantine-clear ----------------------------


def test_m1_positive_xattr_dash_c() -> None:
    """`xattr -c`, `xattr -cr`, `xattr -dr` and `xattr -d com.apple.quarantine` flagged."""
    src = (
        'os.system("xattr -c /tmp/update")\n'
        'os.system("xattr -cr /tmp/payload_bundle")\n'
        'os.system("xattr -dr com.apple.quarantine /payload.app")\n'
        'os.system("xattr -d com.apple.quarantine /tmp/payload")\n'
        '# bash dropper form:\n'
        'xattr -d com.apple.quarantine "$payload"\n'
    )
    hits = _hits("macos-xattr-quarantine-clear", src)
    assert len(hits) >= 4
    assert all(h.severity == "CRITICAL" for h in hits)
    assert all(h.owasp_asi == "ASI-03" for h in hits)


def test_m1_negative_xattr_listing_no_flag() -> None:
    """`xattr -l` (list) and `xattr -p` (print) are read-only — not flagged."""
    src = (
        "# Read-only inspection — should NOT trigger.\n"
        'subprocess.run(["xattr", "-l", "/tmp/file"])\n'
        'os.system("xattr -p com.apple.quarantine /tmp/file")\n'
        "# Also: docstring mentioning the word xattr without a -c/-d flag.\n"
        '"""See the xattr(1) manual for details on attribute handling."""\n'
    )
    hits = _hits("macos-xattr-quarantine-clear", src)
    assert hits == []


# ---------- M2 : macos-launchagent-plist-persistence ---------------------


def test_m2_positive_launchagent_path_and_content() -> None:
    """Both the user-domain plist path AND the RunAtLoad/KeepAlive content trigger."""
    src = (
        'PATH = "~/Library/LaunchAgents/com.user.gh-token-monitor.plist"\n'
        "PLIST_CONTENT = '''\n"
        "<plist version=\"1.0\">\n"
        "<dict>\n"
        "  <key>RunAtLoad</key>  <true/>\n"
        "  <key>KeepAlive</key>  <true/>\n"
        "</dict>\n"
        "</plist>\n"
        "'''\n"
    )
    hits = _hits("macos-launchagent-plist-persistence", src)
    # At least: 1 path hit + 2 content hits (RunAtLoad + KeepAlive)
    assert len(hits) >= 3
    assert all(h.severity == "CRITICAL" for h in hits)


def test_m2_negative_non_launchagent_path_no_flag() -> None:
    """Plist references in unrelated locations (`~/.config`, `Application
    Support`) are not LaunchAgent persistence."""
    src = (
        'CFG = "~/.config/myapp/settings.plist"\n'
        'OTHER = "/Users/foo/Library/Application Support/MyApp/state.plist"\n'
        "# A plist with <false/> for RunAtLoad is a manual-launch app — fine.\n"
        "<key>RunAtLoad</key> <false/>\n"
        "<key>KeepAlive</key> <false/>\n"
    )
    hits = _hits("macos-launchagent-plist-persistence", src)
    assert hits == []


# ---------- M3 : macos-launchctl-activation-primitive --------------------


def test_m3_positive_launchctl_load_and_setenv() -> None:
    """`launchctl load|unload|setenv|bootstrap|kickstart` all trigger."""
    src = (
        "launchctl load ~/Library/LaunchAgents/com.user.persist.plist\n"
        "launchctl unload ~/Library/LaunchAgents/com.user.persist.plist\n"
        "launchctl setenv DYLD_INSERT_LIBRARIES /tmp/inject.dylib\n"
        "launchctl bootstrap gui/501 /tmp/payload.plist\n"
        "launchctl kickstart -k gui/501/com.attacker.persist\n"
    )
    hits = _hits("macos-launchctl-activation-primitive", src)
    assert len(hits) >= 5
    assert all(h.severity == "HIGH" for h in hits)


def test_m3_negative_launchctl_list_no_flag() -> None:
    """`launchctl list`, `launchctl print`, and `launchctl dumpstate` are
    read-only inspection commands — not activation primitives."""
    src = (
        "launchctl list | grep com.apple\n"
        "launchctl print gui/501/com.apple.dock\n"
        "launchctl dumpstate\n"
        "# A comment about launchctl in general should not trigger.\n"
    )
    hits = _hits("macos-launchctl-activation-primitive", src)
    assert hits == []


# ---------- M4 : macos-spctl-gatekeeper-disable --------------------------


def test_m4_positive_spctl_master_disable_and_add() -> None:
    """All three spctl Gatekeeper-disable forms are flagged."""
    src = (
        "sudo spctl --master-disable\n"
        "sudo spctl --add /Applications/SuspiciousApp.app\n"
        "sudo spctl --assess --type install --allow-anywhere /tmp/payload\n"
        "osascript -e 'do shell script \"spctl --master-disable\" "
        "with administrator privileges'\n"
    )
    hits = _hits("macos-spctl-gatekeeper-disable", src)
    # 3 direct spctl matches + 1 osascript-wrapper match
    assert len(hits) >= 4
    assert all(h.severity == "CRITICAL" for h in hits)


def test_m4_negative_spctl_status_no_flag() -> None:
    """`spctl --status` and `spctl --assess <path>` (without
    --allow-anywhere) are inspection / standard verification — not disables."""
    src = (
        "spctl --status\n"
        "spctl --assess --type execute /Applications/Firefox.app\n"
        "spctl --assess --verbose /Applications/Slack.app\n"
        "# A regular ad-hoc verification call.\n"
    )
    hits = _hits("macos-spctl-gatekeeper-disable", src)
    assert hits == []


# ---------- M5 : macos-info-plist-quarantine-disable ---------------------


def test_m5_positive_info_plist_quarantine_disable() -> None:
    """Info.plist quarantine-disabling keys and the imperative flip are flagged."""
    src = (
        "<key>LSFileQuarantineEnabled</key>\n"
        "<false/>\n"
        '<key>LSFileQuarantineExcludedPathPatterns</key>\n'
        "<array><string>/tmp/dropper</string></array>\n"
        '<key>LSQuarantineAgentURL</key>\n'
        "<string>https://benign-source.example/</string>\n"
        "# Python flip:\n"
        'info["LSFileQuarantineEnabled"] = False\n'
    )
    hits = _hits("macos-info-plist-quarantine-disable", src)
    # 3 XML key matches + 1 Python code-path match
    assert len(hits) >= 4
    assert all(h.severity == "HIGH" for h in hits)


def test_m5_negative_unrelated_plist_keys_no_flag() -> None:
    """Unrelated `LS*` Info.plist keys (`LSMinimumSystemVersion`,
    `LSApplicationCategoryType`) do not match."""
    src = (
        "<key>LSMinimumSystemVersion</key>\n"
        "<string>10.15</string>\n"
        "<key>LSApplicationCategoryType</key>\n"
        "<string>public.app-category.developer-tools</string>\n"
        "# A code path with LSFileQuarantineEnabled but set to True — fine:\n"
        'info["LSFileQuarantineEnabled"] = True\n'
    )
    hits = _hits("macos-info-plist-quarantine-disable", src)
    assert hits == []


# ---------- M6 : macos-sudoers-nopasswd-injection ------------------------


def test_m6_positive_sudoers_nopasswd_line_and_write() -> None:
    """Both the file-content line shape AND a write-to-sudoers shell verb are flagged."""
    src = (
        "runner ALL=(ALL) NOPASSWD:ALL\n"
        'echo "attacker ALL=(ALL) NOPASSWD: ALL" | sudo tee -a /etc/sudoers\n'
        'echo "x ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/99-runner\n'
        'echo "y ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/99-runner\n'
    )
    hits = _hits("macos-sudoers-nopasswd-injection", src)
    assert len(hits) >= 4
    assert all(h.severity == "CRITICAL" for h in hits)


def test_m6_negative_sudoers_passwd_line_no_flag() -> None:
    """A sudoers line WITH a password requirement does not match
    `NOPASSWD:ALL`, and unrelated docs mentioning sudoers do not trigger."""
    src = (
        "runner ALL=(ALL) ALL\n"
        "# Docs: the sudoers file controls sudo permissions.\n"
        "# See sudoers(5) for the full syntax.\n"
        "# Even ALL=(ALL) by itself, without the NOPASSWD literal, is OK.\n"
    )
    hits = _hits("macos-sudoers-nopasswd-injection", src)
    assert hits == []


# ---------- M7 : macos-dyld-insert-libraries-injection -------------------


def test_m7_positive_dyld_insert_libraries() -> None:
    """`DYLD_INSERT_LIBRARIES=/tmp/...` and `launchctl setenv DYLD_*` trigger."""
    src = (
        'os.environ["DYLD_INSERT_LIBRARIES"] = "/tmp/.cache/inject.dylib"\n'
        'DYLD_INSERT_LIBRARIES=/tmp/inject.dylib /usr/local/bin/npm install\n'
        "launchctl setenv DYLD_INSERT_LIBRARIES /tmp/.cache/inject.dylib\n"
        "export DYLD_FRAMEWORK_PATH=/tmp/evil\n"
    )
    hits = _hits("macos-dyld-insert-libraries-injection", src)
    assert len(hits) >= 4
    assert all(h.severity == "HIGH" for h in hits)


def test_m7_negative_dyld_with_xcode_instrumentation_no_flag() -> None:
    """DYLD_INSERT_LIBRARIES targeting a recognised instrumentation framework
    (AddressSanitizer / Xcode-installed dylib) is suppressed."""
    src = (
        "# AddressSanitizer instrumentation — legitimate.\n"
        "export DYLD_INSERT_LIBRARIES="
        "/Applications/Xcode.app/Contents/Developer/Toolchains/"
        "XcodeDefault.xctoolchain/usr/lib/clang/15.0.0/lib/darwin/"
        "libclang_rt.asan_osx_dynamic.dylib\n"
        "# Standard instrumentation root.\n"
        "DYLD_INSERT_LIBRARIES=/Library/Developer/CommandLineTools/"
        "usr/lib/libBacktraceRecording.dylib node ./run.js\n"
    )
    hits = _hits("macos-dyld-insert-libraries-injection", src)
    assert hits == []
