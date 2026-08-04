//! Write-concurrency gate (TRDD-7YHT3FNK, Phase 1) — cross-process, cross-language mutual
//! exclusion for every memgrep verb that MUTATES a wikimem page, plus a compare-and-swap
//! staleness refusal so a write enqueued against stale content never silently clobbers a
//! concurrent edit.
//!
//! This is a byte-for-byte clone of the Python side's locking formula
//! (`scripts/lib/memory_txn.py::_scope_lock_path` + `scripts/lib/global_state.py::global_state_dir`)
//! so a Python wikimem-editor transaction and a Rust memgrep write verb serialize against the
//! SAME lock file for the SAME scope — the whole point of this module. A lock path derived by
//! a different formula would silently be a no-op lock: both sides would happily proceed in
//! parallel while believing they were exclusive.

use anyhow::{Context, Result};
use sha2::{Digest, Sha256};
use std::fs::File;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// The canonical refusal a stale-based (compare-and-swap) write must return, verbatim — the
/// exact wording the USER's directive mandates (TRDD-7YHT3FNK). Callers must not paraphrase
/// this: agents that reread the file on seeing it depend on the literal string.
pub const STALE_MSG: &str =
    "The content of the wikimem file changed since your command was enqueued. Please reread the file first.";

/// Migration marker filename inside the plugin-DATA global-state dir — mirrors
/// `global_state._MIGRATION_MARKER` exactly. Its presence flips resolution from the legacy dir
/// to the DATA dir even when the legacy dir still exists (a one-time, single-writer handover).
const MIGRATION_MARKER: &str = "migrated-from-legacy.ts";

/// Default bound on how long `acquire` blocks trying to take the lock before giving up.
/// Overridable via `MEMGREP_LOCK_TIMEOUT_S` (see `acquire`).
const DEFAULT_LOCK_TIMEOUT_S: u64 = 10;

/// Poll interval while retrying a non-blocking flock attempt inside the timeout window.
const LOCK_POLL_INTERVAL_MS: u64 = 25;

/// The scope root that OWNS `page` — the nearest ancestor directory literally named `memory`
/// (the three canonical scope roots — LOCAL/PROJECT/USER — all end in `.../memory`, and a
/// curated wiki page always lives at `<scope_root>/wikimem/*.md` or directly under
/// `<scope_root>/`). Falls back to the page's own parent directory when no such ancestor
/// exists (a page outside any known scope — e.g. a scratch fixture in a test), so the lock is
/// always well-defined even for content memgrep does not otherwise recognise as a scope.
///
/// Resolves symlinks first (`fs::canonicalize`) so a page reached through a symlinked path
/// still lands on the SAME scope root — and therefore the SAME lock — as the real path. When
/// the page itself does not exist yet (e.g. `new-page`'s target), canonicalize its parent and
/// re-join the filename, since `fs::canonicalize` requires the path to exist.
pub fn scope_root_for(page: &Path) -> PathBuf {
    let real = canonicalize_best_effort(page);
    let mut cur: Option<&Path> = real.parent();
    while let Some(dir) = cur {
        if dir.file_name().map(|n| n == "memory").unwrap_or(false) {
            return dir.to_path_buf();
        }
        cur = dir.parent();
    }
    // No `memory`-named ancestor: fall back to the page's own (real) parent directory, same as
    // the pre-lock behaviour for content outside any recognised scope.
    real.parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."))
}

/// Best-effort realpath: `fs::canonicalize(page)` when the page itself exists; otherwise
/// canonicalize its parent (which must exist for the page to be writable at all) and re-join
/// the file name, so a not-yet-created `new-page` target still resolves through any symlinked
/// ancestor directories. Falls back to the path unchanged if even the parent cannot be
/// canonicalized (e.g. neither exists yet) — the caller still gets a stable, if unresolved,
/// answer rather than an error.
fn canonicalize_best_effort(page: &Path) -> PathBuf {
    if let Ok(real) = std::fs::canonicalize(page) {
        return real;
    }
    let parent = page.parent().filter(|p| !p.as_os_str().is_empty());
    let file_name = page.file_name();
    match (parent, file_name) {
        (Some(parent), Some(name)) => match std::fs::canonicalize(parent) {
            Ok(real_parent) => real_parent.join(name),
            Err(_) => page.to_path_buf(),
        },
        _ => page.to_path_buf(),
    }
}

/// The system-wide janitor global-state directory — a byte-for-byte clone of
/// `scripts/lib/global_state.py::global_state_dir()`. Resolution order:
///   1. `$JANITOR_GLOBAL_STATE_DIR` (expanduser + resolve) — absolute priority, the escape
///      hatch the whole test suite (both languages) relies on.
///   2. `$XDG_STATE_HOME/janitor` when `XDG_STATE_HOME` is set.
///   3. The plugin DATA dir `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state`
///      once the daemon has stamped `migrated-from-legacy.ts` there, OR when there is no legacy
///      dir to migrate (fresh install).
///   4. The legacy `~/.claude/janitor-global-state/` while a not-yet-migrated install still has
///      one.
fn global_state_dir() -> PathBuf {
    if let Ok(over) = std::env::var("JANITOR_GLOBAL_STATE_DIR")
        && !over.is_empty()
    {
        return resolve_best_effort(&expand_user(&over));
    }
    if let Ok(xdg) = std::env::var("XDG_STATE_HOME")
        && !xdg.is_empty()
    {
        return resolve_best_effort(&expand_user(&xdg)).join("janitor");
    }
    let data = data_global_state_dir();
    let legacy = legacy_global_state_dir();
    if data.join(MIGRATION_MARKER).is_file() || !legacy.is_dir() {
        data
    } else {
        legacy
    }
}

fn legacy_global_state_dir() -> PathBuf {
    home_dir().join(".claude").join("janitor-global-state")
}

fn data_global_state_dir() -> PathBuf {
    home_dir()
        .join(".claude")
        .join("plugins")
        .join("data")
        .join("ai-maestro-janitor-ai-maestro-plugins")
        .join("global-state")
}

/// `$HOME`, mirroring Python's `Path.home()` (which itself reads `$HOME` on POSIX). No fallback
/// to a passwd-db lookup — every process this tool runs in has `$HOME` set, and the Python side
/// makes the same assumption.
fn home_dir() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/"))
}

/// `~`-expand a leading `~` or `~/...`, mirroring Python's `Path.expanduser()`.
fn expand_user(raw: &str) -> PathBuf {
    if let Some(rest) = raw.strip_prefix("~/") {
        return home_dir().join(rest);
    }
    if raw == "~" {
        return home_dir();
    }
    PathBuf::from(raw)
}

/// Mirrors Python `Path.resolve()`: canonicalize when possible (symlinks resolved, made
/// absolute), else return the path as given (Python's `resolve()` does not require the path to
/// exist either — it normalizes lexically when it can't stat).
fn resolve_best_effort(p: &Path) -> PathBuf {
    std::fs::canonicalize(p).unwrap_or_else(|_| p.to_path_buf())
}

/// The per-scope commit-lock PATH — a byte-for-byte clone of `memory_txn._scope_lock_path`:
/// `global_state_dir() / "memory-maint-<first 16 hex of sha256(str(scope_root))>.lock"`.
///
/// `str(scope_root)` on the Python side renders the `Path` via its platform display form (no
/// trailing slash); `scope_root.display()` here renders the same way for the paths this tool
/// resolves (both sides run on the same machine, POSIX paths, forward slashes) — so hashing the
/// `Display` string is the byte-identical counterpart.
pub fn lock_path_for(scope_root: &Path) -> PathBuf {
    let s = scope_root.display().to_string();
    let mut hasher = Sha256::new();
    hasher.update(s.as_bytes());
    let digest = hasher.finalize();
    let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
    let short = &hex[..16];
    global_state_dir().join(format!("memory-maint-{short}.lock"))
}

/// A held exclusive lock on one scope's commit lock file. Releases (unlock + close) on `Drop` —
/// so a write verb that returns early via `?` still releases the lock, and a process crash
/// releases it via the kernel closing the fd, exactly like the Python side's flock.
#[derive(Debug)]
pub struct WriteGuard {
    _file: File,
}

/// Acquire the EXCLUSIVE write lock for `scope_root`, blocking (with a bounded timeout) until
/// it is free.
///
/// Unlike the Python `commit_lock` (non-blocking, skip-on-contention — appropriate for a
/// best-effort background chore that just re-tries next cycle), an interactive memgrep write
/// verb is a single user-facing command that must not silently no-op on contention: it BLOCKS,
/// retrying a non-blocking `flock(LOCK_EX | LOCK_NB)` on a short poll interval, until either the
/// lock is acquired or `MEMGREP_LOCK_TIMEOUT_S` (default 10s) elapses — at which point it fails
/// with a message naming the timeout, so the caller knows to retry rather than assume the write
/// landed.
#[cfg(unix)]
pub fn acquire(scope_root: &Path) -> Result<WriteGuard> {
    use std::os::unix::io::AsRawFd;

    let lock_path = lock_path_for(scope_root);
    if let Some(parent) = lock_path.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("create global-state dir {}", parent.display()))?;
    }
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        // Never truncate: this is a flock target, not a data file — its content (if any) is
        // meaningless, and truncating on every open would just be pointless I/O.
        .truncate(false)
        .open(&lock_path)
        .with_context(|| format!("open lock file {}", lock_path.display()))?;

    let timeout_s: u64 = std::env::var("MEMGREP_LOCK_TIMEOUT_S")
        .ok()
        .and_then(|v| v.trim().parse().ok())
        .unwrap_or(DEFAULT_LOCK_TIMEOUT_S);
    let deadline = Instant::now() + Duration::from_secs(timeout_s);
    let fd = file.as_raw_fd();

    loop {
        let rc = unsafe { libc::flock(fd, libc::LOCK_EX | libc::LOCK_NB) };
        if rc == 0 {
            return Ok(WriteGuard { _file: file });
        }
        let err = std::io::Error::last_os_error();
        let would_block = err.raw_os_error() == Some(libc::EWOULDBLOCK)
            || err.raw_os_error() == Some(libc::EAGAIN);
        if !would_block {
            anyhow::bail!("flock {}: {err}", lock_path.display());
        }
        if Instant::now() >= deadline {
            anyhow::bail!(
                "timed out after {timeout_s}s waiting for the write lock on {} — another writer is \
                 holding it; retry, or raise MEMGREP_LOCK_TIMEOUT_S",
                lock_path.display()
            );
        }
        std::thread::sleep(Duration::from_millis(LOCK_POLL_INTERVAL_MS));
    }
}

#[cfg(not(unix))]
pub fn acquire(_scope_root: &Path) -> Result<WriteGuard> {
    anyhow::bail!("the write-concurrency gate requires a POSIX flock — unsupported on this platform")
}

impl Drop for WriteGuard {
    fn drop(&mut self) {
        #[cfg(unix)]
        {
            use std::os::unix::io::AsRawFd;
            let fd = self._file.as_raw_fd();
            unsafe {
                libc::flock(fd, libc::LOCK_UN);
            }
        }
        // The fd itself is closed when `_file` drops right after this.
    }
}

/// Compare-and-swap staleness check: hash `page`'s LIVE bytes on disk and compare against
/// `base_sha256` (the hash the caller computed when it last read the page). Must be called
/// while holding the scope's `WriteGuard` — otherwise a concurrent writer could mutate the page
/// between this check and the caller's own write, defeating the whole point of the CAS.
///
/// Fails with `STALE_MSG` verbatim on any mismatch, INCLUDING an unreadable/missing page (a
/// page that vanished since the caller last read it is exactly as stale as one that changed).
pub fn check_base(page: &Path, base_sha256: &str) -> Result<()> {
    let bytes = std::fs::read(page).map_err(|_| anyhow::anyhow!(STALE_MSG))?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    let digest = hasher.finalize();
    let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
    if !hex.eq_ignore_ascii_case(base_sha256.trim()) {
        anyhow::bail!(STALE_MSG);
    }
    Ok(())
}

/// sha256-hex of `page`'s current bytes on disk — the value a caller passes back as
/// `--base-sha256` on a LATER write. Test-only: exercises the same hash `check_base` verifies
/// against, from the same bytes-on-disk source of truth (never the possibly lossily-decoded
/// `String` `md::read_text` returns).
#[cfg(test)]
fn sha256_of_file(page: &Path) -> Result<String> {
    let bytes = std::fs::read(page).with_context(|| format!("read {}", page.display()))?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    let digest = hasher.finalize();
    Ok(digest.iter().map(|b| format!("{b:02x}")).collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::Mutex;

    // `JANITOR_GLOBAL_STATE_DIR` / `MEMGREP_LOCK_TIMEOUT_S` are PROCESS-WIDE env vars, but
    // `cargo test` runs every `#[test]` fn in its own thread, in parallel, by default. Any test
    // in this module that sets one of them MUST hold this mutex for its entire body, or a
    // concurrently-running sibling test observes the wrong value mid-run (measured: it does,
    // flakily, exactly this way) — never rely on `--test-threads=1` instead, since that would
    // serialize the WHOLE binary's 150+ unrelated tests just to fix two of them here.
    static ENV_MUTEX: Mutex<()> = Mutex::new(());

    /// Take `ENV_MUTEX` WITHOUT propagating poison.
    ///
    /// `.lock().unwrap()` turns one failing test into three: the first test to panic poisons the
    /// mutex, and every later test that touches it then fails with `PoisonError` instead of its
    /// own verdict — so the run reports a cascade and hides which test actually broke. Observed
    /// exactly that way (3 "failures", 8/8 green when re-run serially), which also makes the
    /// suite look flaky when only one test is at fault.
    ///
    /// Recovering the guard is right HERE specifically because the mutex protects no invariant of
    /// its own: it guards process-global env vars, and every test that takes it sets the vars it
    /// needs before reading them. There is no state a panicking sibling could leave inconsistent.
    fn env_lock() -> std::sync::MutexGuard<'static, ()> {
        ENV_MUTEX.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    static COUNTER: AtomicU64 = AtomicU64::new(0);

    /// A fresh, empty temp dir under the OS temp root — never touches the real
    /// `~/.claude/...` locations (TRDD-7YHT3FNK P1 test isolation).
    fn tmpdir(label: &str) -> PathBuf {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!(
            "memgrep-write-gate-test-{label}-{}-{n}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    // ── lock_path_for parity with the Python formula ────────────────────────────────────────

    #[test]
    fn lock_path_for_matches_python_sha16_formula() {
        let _env = env_lock();
        let state_dir = tmpdir("state");
        unsafe {
            std::env::set_var("JANITOR_GLOBAL_STATE_DIR", &state_dir);
        }

        let scope = PathBuf::from("/tmp/fixed/scope/memory");
        let got = lock_path_for(&scope);

        // Independently computed expected hash: sha256("/tmp/fixed/scope/memory")[:16] hex.
        let mut hasher = Sha256::new();
        hasher.update(scope.display().to_string().as_bytes());
        let digest = hasher.finalize();
        let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
        let expected_short = &hex[..16];

        // `global_state_dir()` resolves the env override through `Path::resolve()` semantics
        // (symlinks included, e.g. macOS's /var -> /private/var), so compare against the SAME
        // canonicalized form rather than the literal path the test created the dir under.
        let canonical_state_dir = std::fs::canonicalize(&state_dir).unwrap();

        unsafe {
            std::env::remove_var("JANITOR_GLOBAL_STATE_DIR");
        }
        let _ = std::fs::remove_dir_all(&state_dir);

        assert_eq!(
            got,
            canonical_state_dir.join(format!("memory-maint-{expected_short}.lock")),
            "lock filename must be memory-maint-<first 16 hex of sha256(str(scope_root))>.lock, \
             matching memory_txn._scope_lock_path exactly"
        );
        // Pin the well-known value for THIS fixed path so a future refactor of the hasher can't
        // silently change the formula without a test noticing the literal digest moved.
        assert_eq!(
            expected_short,
            &hex_sha256("/tmp/fixed/scope/memory")[..16],
            "sanity: the two independent hash computations must agree"
        );
    }

    fn hex_sha256(s: &str) -> String {
        let mut hasher = Sha256::new();
        hasher.update(s.as_bytes());
        hasher.finalize().iter().map(|b| format!("{b:02x}")).collect()
    }

    // ── scope_root_for ───────────────────────────────────────────────────────────────────────

    #[test]
    fn scope_root_for_finds_nearest_ancestor_named_memory() {
        let root = tmpdir("scope-root");
        let memory = root.join("memory");
        let wikimem = memory.join("wikimem");
        std::fs::create_dir_all(&wikimem).unwrap();
        let page = wikimem.join("x.md");
        std::fs::write(&page, "x").unwrap();

        let got = scope_root_for(&page);
        let expected = std::fs::canonicalize(&memory).unwrap();
        let _ = std::fs::remove_dir_all(&root);

        assert_eq!(got, expected);
    }

    #[test]
    #[cfg(unix)]
    fn scope_root_for_resolves_through_a_symlink() {
        let root = tmpdir("scope-root-symlink");
        let memory = root.join("real").join("memory");
        let wikimem = memory.join("wikimem");
        std::fs::create_dir_all(&wikimem).unwrap();
        let page = wikimem.join("x.md");
        std::fs::write(&page, "x").unwrap();

        let link = root.join("link-to-real");
        std::os::unix::fs::symlink(root.join("real"), &link).unwrap();
        let page_via_link = link.join("memory").join("wikimem").join("x.md");

        let direct = scope_root_for(&page);
        let via_link = scope_root_for(&page_via_link);
        let _ = std::fs::remove_dir_all(&root);

        assert_eq!(
            direct, via_link,
            "a page reached through a symlinked ancestor must resolve to the SAME scope root \
             (and therefore the same lock) as the real path"
        );
    }

    #[test]
    fn scope_root_for_falls_back_to_parent_dir_when_no_memory_ancestor() {
        let root = tmpdir("scope-root-fallback");
        let page = root.join("x.md");
        std::fs::write(&page, "x").unwrap();

        let got = scope_root_for(&page);
        let expected = std::fs::canonicalize(&root).unwrap();
        let _ = std::fs::remove_dir_all(&root);

        assert_eq!(got, expected);
    }

    // ── compare-and-swap ─────────────────────────────────────────────────────────────────────

    #[test]
    fn check_base_accepts_matching_hash_and_rejects_stale() {
        let root = tmpdir("cas");
        let page = root.join("p.md");
        std::fs::write(&page, "hello").unwrap();
        let good = sha256_of_file(&page).unwrap();

        assert!(check_base(&page, &good).is_ok());

        std::fs::write(&page, "hello, but edited by someone else").unwrap();
        let err = check_base(&page, &good).unwrap_err();
        let _ = std::fs::remove_dir_all(&root);

        assert_eq!(err.to_string(), STALE_MSG);
    }

    #[test]
    fn check_base_rejects_a_vanished_page() {
        let root = tmpdir("cas-vanished");
        let page = root.join("p.md");
        std::fs::write(&page, "hello").unwrap();
        let good = sha256_of_file(&page).unwrap();
        std::fs::remove_file(&page).unwrap();

        let err = check_base(&page, &good).unwrap_err();
        let _ = std::fs::remove_dir_all(&root);

        assert_eq!(err.to_string(), STALE_MSG);
    }

    // ── acquire: contention + timeout ────────────────────────────────────────────────────────

    #[test]
    fn acquire_serializes_two_concurrent_holders() {
        let _env = env_lock();
        let state_dir = tmpdir("state-contend");
        unsafe {
            std::env::set_var("JANITOR_GLOBAL_STATE_DIR", &state_dir);
        }
        let scope = tmpdir("scope-contend");

        let g1 = acquire(&scope).expect("first acquire must succeed immediately");

        // A second acquire on the SAME scope, in another thread, must block until g1 drops —
        // proven by a shared counter only the lock-holder may increment.
        let order = std::sync::Arc::new(std::sync::Mutex::new(Vec::<&'static str>::new()));
        let order2 = order.clone();
        let scope2 = scope.clone();
        let handle = std::thread::spawn(move || {
            let _g2 = acquire(&scope2).expect("second acquire must eventually succeed");
            order2.lock().unwrap().push("second");
        });

        std::thread::sleep(Duration::from_millis(150));
        order.lock().unwrap().push("first-still-holding");
        drop(g1);
        handle.join().unwrap();

        let seq = order.lock().unwrap().clone();
        unsafe {
            std::env::remove_var("JANITOR_GLOBAL_STATE_DIR");
        }
        let _ = std::fs::remove_dir_all(&state_dir);
        let _ = std::fs::remove_dir_all(&scope);

        assert_eq!(seq, vec!["first-still-holding", "second"]);
    }

    #[test]
    fn acquire_times_out_when_lock_is_held() {
        let _env = env_lock();
        let state_dir = tmpdir("state-timeout");
        unsafe {
            std::env::set_var("JANITOR_GLOBAL_STATE_DIR", &state_dir);
            std::env::set_var("MEMGREP_LOCK_TIMEOUT_S", "1");
        }
        let scope = tmpdir("scope-timeout");

        let _held = acquire(&scope).expect("first acquire must succeed");
        let started = Instant::now();
        let err = acquire(&scope).expect_err("a second acquire must time out while held");
        let elapsed = started.elapsed();

        unsafe {
            std::env::remove_var("JANITOR_GLOBAL_STATE_DIR");
            std::env::remove_var("MEMGREP_LOCK_TIMEOUT_S");
        }
        let _ = std::fs::remove_dir_all(&state_dir);
        let _ = std::fs::remove_dir_all(&scope);

        assert!(err.to_string().to_lowercase().contains("timed out"));
        assert!(elapsed < Duration::from_secs(3), "must not wildly overshoot the 1s timeout");
    }
}
