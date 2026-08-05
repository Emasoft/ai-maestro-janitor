//! Stamp `--version` with a build identity (janitor#164).
//!
//! `Cargo.toml`'s `version` alone cannot tell two builds apart: CORE's memgrep fork and this
//! plugin's both reported `0.1.0` while their sources had diverged to 12354 vs 4806 LOC, and
//! that divergence went unnoticed until a human happened to diff the binaries. A stale
//! `cargo install` from an old checkout is the same hazard shrunk to one machine — it shadows
//! the release and LOOKS identical. Embedding the commit this binary was built from makes that
//! visible in `--version` output instead of silent.
//!
//! Reads git directly (no crate — the git CLI is already a hard runtime dependency of `memgrep
//! reindex`/`migrate` for their own repo-detection, so this adds no new tool to the build
//! environment). FAILS OPEN: a git-less build environment (a source tarball with no `.git`,
//! `git` missing from PATH) yields the literal string "unknown" for both fields rather than
//! failing the build — a missing build stamp is strictly better than a build that cannot
//! compile outside a git checkout.

use std::process::Command;

/// Run `git <args>` from this crate's own directory and return trimmed stdout, or `None` on
/// any failure (missing binary, non-git-repo, non-zero exit, non-UTF8 output).
fn git_output(args: &[&str]) -> Option<String> {
    let out = Command::new("git").args(args).output().ok()?;
    if !out.status.success() {
        return None;
    }
    let text = String::from_utf8(out.stdout).ok()?;
    let trimmed = text.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn main() {
    let sha = git_output(&["rev-parse", "--short=7", "HEAD"]).unwrap_or_else(|| "unknown".to_string());
    // The COMMIT's own date, not the build machine's clock — deterministic across machines and
    // timezones for the same commit, which matters because this same build.rs runs on four
    // different CI runners (macOS arm64/x64, Linux arm64/x64) for one release tag and their
    // stamps must agree.
    let date = git_output(&["log", "-1", "--format=%cd", "--date=format:%Y-%m-%d"])
        .unwrap_or_else(|| "unknown".to_string());

    println!("cargo:rustc-env=MEMGREP_BUILD_SHA={sha}");
    println!("cargo:rustc-env=MEMGREP_BUILD_DATE={date}");

    // Re-run this script (and so refresh the stamp) whenever HEAD moves to a new commit.
    // Without this, cargo treats build.rs as producing the same output forever and a rebuild
    // after `git commit` would keep reporting the PREVIOUS commit's sha — silently wrong in
    // exactly the way this feature exists to make visible. `--absolute-git-dir` (not
    // `--git-dir`) because `cargo:rerun-if-changed` paths are resolved by cargo, not by this
    // process's cwd — a relative `../../.git` would be ambiguous about what it is relative TO.
    if let Some(git_dir) = git_output(&["rev-parse", "--absolute-git-dir"]) {
        println!("cargo:rerun-if-changed={git_dir}/HEAD");
    }
}
