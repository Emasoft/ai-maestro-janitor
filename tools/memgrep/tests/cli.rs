//! End-to-end tests: run the real `memgrep` binary against a committed fixture and assert the
//! structural filters behave. Uses `CARGO_BIN_EXE_memgrep` (cargo points it at the built binary),
//! so no extra dev-deps and we exercise the actual CLI a user/agent would invoke.

use std::process::Command;

const FX: &str = "tests/fixtures/sample.md";

fn run(args: &[&str]) -> String {
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let out = Command::new(bin)
        .args(args)
        .output()
        .expect("failed to run memgrep");
    assert!(out.status.success(), "memgrep exited non-zero for {args:?}");
    String::from_utf8_lossy(&out.stdout).into_owned()
}

#[test]
fn plain_pattern_finds_prose_and_code() {
    // 3 prose mentions + 1 inside the code block.
    assert_eq!(run(&["security", FX]).lines().count(), 4);
}

#[test]
fn no_code_drops_the_code_block_false_positive() {
    let o = run(&["security", "--no-code", FX]);
    assert_eq!(o.lines().count(), 3, "{o}");
    assert!(!o.contains("echo security"), "code line must be excluded:\n{o}");
}

#[test]
fn code_only_keeps_just_the_code_line() {
    let o = run(&["security", "--code", FX]);
    assert_eq!(o.lines().count(), 1);
    assert!(o.contains("echo security"));
}

#[test]
fn code_lang_filters_by_fence_language() {
    assert_eq!(run(&["security", "--code-lang", "python", FX]).lines().count(), 0);
    assert_eq!(run(&["security", "--code-lang", "bash", FX]).lines().count(), 1);
}

#[test]
fn in_section_scopes_to_chapter_and_subsections() {
    let o = run(&["security", "--no-code", "--in", "Requirements", FX]);
    assert_eq!(o.lines().count(), 1, "{o}");
    assert!(o.contains("requirements discuss security"));
}

#[test]
fn heading_only_lists_all_headings() {
    assert_eq!(run(&["--heading", FX]).lines().count(), 4);
}

#[test]
fn heading_with_positional_regex_matches_heading_text() {
    let o = run(&["Backend", "--heading", FX]);
    assert_eq!(o.lines().count(), 1);
    assert!(o.contains("# 2 Backend"));
}

#[test]
fn level_filter_restricts_to_that_heading_level() {
    assert_eq!(run(&["--heading", "--level", "2", FX]).lines().count(), 2);
    assert_eq!(run(&["--heading", "--level", "1", FX]).lines().count(), 2);
    // lenient range forms
    assert_eq!(run(&["--heading", "--level", ">=2", FX]).lines().count(), 2);
}

#[test]
fn count_and_files_only_modes() {
    assert_eq!(run(&["-c", "security", "--no-code", FX]).trim(), format!("{FX}:3"));
    assert_eq!(run(&["-l", "security", FX]).trim(), FX);
}

#[test]
fn binary_file_is_skipped_without_crashing() {
    // Point memgrep at its own binary (full of NUL bytes); it must skip, not crash.
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let out = Command::new(bin).args(["the", bin]).output().unwrap();
    assert!(out.status.success(), "must not crash on a binary file");
    assert!(out.stdout.is_empty(), "binary file should yield no matches");
}
