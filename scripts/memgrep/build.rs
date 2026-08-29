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

use std::path::{Path, PathBuf};
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

/// `git rev-parse --git-path X` answers RELATIVE TO THE CWD — measured, it returns
/// `../../.git/HEAD` when run from `scripts/memgrep`. Cargo resolves a `rerun-if-changed`
/// path itself, not through this process, so a `../..`-prefixed path is exactly the
/// ambiguity the original code sidestepped by asking for `--absolute-git-dir`. Resolve it
/// here and the question never arises.
fn absolutize(p: &str) -> Option<PathBuf> {
    let path = Path::new(p);
    if path.is_absolute() {
        Some(path.to_path_buf())
    } else {
        std::env::current_dir().ok().map(|cwd| cwd.join(path))
    }
}

/// The files cargo must watch for the stamp to stay honest.
///
/// The original version watched `<git-dir>/HEAD` alone, and that is why the stamp froze:
/// on a branch, `HEAD` holds the constant text `ref: refs/heads/<branch>`, and a COMMIT
/// never writes it — git writes the resolved ref. So cargo saw an unchanged input, never
/// re-ran this script, and the binary reported the commit that was HEAD the first time the
/// crate was ever built in that checkout. Measured on this repo: `.git/refs/heads/main`
/// advanced with the commit while `.git/HEAD` did not.
fn watch_targets() -> Vec<PathBuf> {
    let mut targets: Vec<PathBuf> = Vec::new();

    // HEAD: still needed. It is the only one of the three that moves on a branch SWITCH or
    // a detach, neither of which touches the ref we were previously on.
    if let Some(p) = git_output(&["rev-parse", "--git-path", "HEAD"]).and_then(|s| absolutize(&s)) {
        targets.push(p);
    }

    // The resolved ref: the file a commit actually writes. Emitted even when it does not
    // exist yet, deliberately. A fresh clone has its branch tip only in `packed-refs` and
    // no loose ref at all; cargo treats a missing watch path as always-changed, so during
    // that window this script re-runs on every build (three git calls) and the stamp stays
    // correct — and the window closes by itself the moment the first commit writes the
    // loose ref. Filtering it out for tidiness would re-create the exact freeze this fix
    // exists to remove, in the one case where nothing else can catch it.
    // `symbolic-ref -q` exits non-zero on a detached HEAD, which yields None here: correct,
    // because a detached HEAD moves `HEAD` itself and is already covered above.
    if let Some(refname) = git_output(&["symbolic-ref", "-q", "HEAD"])
        && let Some(p) =
            git_output(&["rev-parse", "--git-path", &refname]).and_then(|s| absolutize(&s))
    {
        targets.push(p);
    }

    // packed-refs, only when present: it carries the branch tip before the first loose ref
    // is written, and it is rewritten by `git gc`/`git pack-refs`. Unlike the loose ref its
    // ABSENCE tells us nothing worth re-running for, so do not pay the always-changed tax.
    if let Some(p) =
        git_output(&["rev-parse", "--git-path", "packed-refs"]).and_then(|s| absolutize(&s))
        && p.exists()
    {
        targets.push(p);
    }

    targets
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
    // after `git commit` keeps reporting the PREVIOUS commit's sha — silently wrong in
    // exactly the way this feature exists to make visible. That is not hypothetical: it was
    // LIVE from janitor#164 until 2026-08-16, because watching `HEAD` alone watches a file a
    // commit never writes. See `watch_targets` for which three files are the right ones and
    // why one of them is emitted even when it is absent.
    for target in watch_targets() {
        println!("cargo:rerun-if-changed={}", target.display());
    }
}
