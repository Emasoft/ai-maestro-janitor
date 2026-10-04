//! Environment reads that tests can override PER THREAD instead of per process.
//!
//! WHY this exists: `std::env::set_var` mutates PROCESS-GLOBAL state, but `cargo test` runs every
//! `#[test]` on its own thread in parallel. A test that set `JANITOR_GLOBAL_STATE_DIR` (or
//! `MEMGREP_USER_MEM_ROOT`, `WIKIMEM_*_SCOPE_PATH`, ...) made EVERY concurrently running test —
//! including the many that never touch the variable but reach it through production code such as
//! the write gate — resolve its state dir inside that test's temp dir, which the owner then
//! deleted ("open lock file <another test's dir>/memory-maint-out-of-scope.lock: No such file").
//! Per-module mutexes could not fix it: they were different statics (serializing nothing across
//! modules) and only the SETTERS took them, never the unrelated readers.
//!
//! The fix is to remove the shared state. Production code reads these variables through [`var`];
//! in a test build it consults a thread-local override map first, so a test's override is visible
//! to that test's thread only and vanishes with it (libtest gives each test its own thread).
//! In a release build [`var`] is exactly `std::env::var`. Tests that start their own threads
//! carry the overrides across with [`snapshot`] / [`install`].

pub fn var(name: &str) -> Result<String, std::env::VarError> {
    #[cfg(test)]
    if let Some(over) = test_support::lookup(name) {
        return over.ok_or(std::env::VarError::NotPresent);
    }
    std::env::var(name)
}

#[cfg(test)]
pub use test_support::{install, remove_var, set_var, snapshot};

#[cfg(test)]
mod test_support {
    use std::cell::RefCell;
    use std::collections::HashMap;

    /// `Some(value)` overrides the variable, `None` makes it read as unset.
    pub type Overrides = HashMap<String, Option<String>>;

    thread_local! {
        static OVERRIDES: RefCell<Overrides> = RefCell::new(HashMap::new());
    }

    pub fn lookup(name: &str) -> Option<Option<String>> {
        OVERRIDES.with(|o| o.borrow().get(name).cloned())
    }

    /// Override `key` for the CALLING THREAD only. Declared `unsafe` solely to mirror
    /// `std::env::set_var`'s edition-2024 signature so call sites keep their `unsafe` block; it
    /// touches no process state and has no safety precondition.
    pub unsafe fn set_var(key: &str, value: impl AsRef<std::ffi::OsStr>) {
        let v = value.as_ref().to_string_lossy().into_owned();
        OVERRIDES.with(|o| o.borrow_mut().insert(key.to_string(), Some(v)));
    }

    /// Make `key` read as unset on the CALLING THREAD only (see [`set_var`] for why `unsafe`).
    pub unsafe fn remove_var(key: &str) {
        OVERRIDES.with(|o| o.borrow_mut().insert(key.to_string(), None));
    }

    /// The calling thread's overrides, to hand to a thread the test spawns.
    pub fn snapshot() -> Overrides {
        OVERRIDES.with(|o| o.borrow().clone())
    }

    /// Adopt overrides taken with [`snapshot`] on another thread.
    pub fn install(overrides: Overrides) {
        OVERRIDES.with(|o| *o.borrow_mut() = overrides);
    }
}
