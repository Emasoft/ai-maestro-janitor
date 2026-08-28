//! `delete-mem-topic` / `delete-mem-atom` — the memory system's DELETE verbs (TRDD-VJL1YTCG
//! Part B). RULE 0: deleting knowledge is never routine and never a plain `rm`/unlink — a page is
//! MOVED into `.trashcan/<timestamp>/<rel-path>` (recoverable with one `mv`), and an atom's
//! footnotes are only ever removed, and renumbered, when the caller says so explicitly.

use crate::md;
use crate::memory::{
    atom_id_matches, atomic_write_page, bump_page_lmd, footnote_integrity_violations,
    locate_atom_body_matching, now_iso_utc, read_page_for_write, reindex_owning_scope, rel,
    rewrite_footnote_labels, today_date,
};
use crate::write_gate::{self, STALE_MSG};
use anyhow::{Context, Result};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

// ─────────────────────────────── shared helpers ───────────────────────────────

/// The nearest ancestor of `page` carrying a `.git` dir — else `page`'s own parent directory.
fn project_root_for(page: &Path) -> PathBuf {
    let real = std::fs::canonicalize(page).unwrap_or_else(|_| page.to_path_buf());
    let start = real.parent().map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from("."));
    let mut dir = start.clone();
    loop {
        if dir.join(".git").is_dir() {
            return dir;
        }
        match dir.parent() {
            Some(p) => dir = p.to_path_buf(),
            None => return start,
        }
    }
}

/// A trashcan destination timestamp, derived from `now_iso_utc()` (`YYYY-MM-DDTHH:MM:SSZ`) with
/// the punctuation stripped: `YYYYMMDD_HHMMSS`. UTC, matching the crate's dependency-free date
/// math (no chrono) — this names a directory, not a report file, so the reports-location rule's
/// local-time-with-offset convention does not apply here.
fn trash_timestamp() -> String {
    let iso = now_iso_utc();
    format!("{}_{}", iso[0..10].replace('-', ""), iso[11..19].replace(':', ""))
}

/// Move `src` into `<project-root>/.trashcan/<timestamp>/<rel-path>` (RULE 0 — knowledge is
/// relocated, never destroyed). `dry_run` computes the destination + restore command without
/// touching the filesystem. Returns `(dest, "mv <dest> <src>")`.
fn move_to_trashcan(src: &Path, dry_run: bool) -> Result<(PathBuf, String)> {
    let root = project_root_for(src);
    let abs = std::fs::canonicalize(src).with_context(|| format!("canonicalize {}", src.display()))?;
    let relp = abs.strip_prefix(&root).unwrap_or(abs.as_path()).to_path_buf();
    let dest = root.join(".trashcan").join(trash_timestamp()).join(&relp);
    let restore = format!("mv {} {}", dest.display(), abs.display());
    if !dry_run {
        if let Some(parent) = dest.parent() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("mkdir -p {}", parent.display()))?;
        }
        std::fs::rename(&abs, &dest)
            .with_context(|| format!("move {} -> {}", abs.display(), dest.display()))?;
    }
    Ok((dest, restore))
}

/// Every `.md` file under `root` (recursive; skips dot-dirs unless `hidden`), excluding the
/// private/transient scope dirs the rest of the crate never indexes either.
fn walk_md_files(root: &Path, hidden: bool) -> Vec<PathBuf> {
    const SKIP: [&str; 3] = ["user-mem", ".maint-staging", ".trashcan"];
    ignore::WalkBuilder::new(root)
        .hidden(!hidden)
        .build()
        .flatten()
        .filter(|e| {
            e.file_type().map(|t| t.is_file()).unwrap_or(false)
                && e.path()
                    .extension()
                    .and_then(|x| x.to_str())
                    .map(|x| x.eq_ignore_ascii_case("md"))
                    .unwrap_or(false)
                && !e.path().components().any(|c| SKIP.iter().any(|s| c.as_os_str() == *s))
        })
        .map(|e| e.path().to_path_buf())
        .collect()
}

/// The wiki identities `page` answers to: its lowercased file stem, plus frontmatter
/// `name`/`topic` (lowercased) when present — the candidate `[[...]]` targets another page cites.
fn page_identities(page: &Path, text: &str) -> Vec<String> {
    let mut out = Vec::new();
    if let Some(stem) = page.file_stem().and_then(|s| s.to_str()) {
        out.push(stem.to_ascii_lowercase());
    }
    let fm = md::parse_frontmatter(text);
    for key in ["name", "topic"] {
        if let Some(v) = fm.get(key) {
            let v = v.trim().trim_matches('"').to_ascii_lowercase();
            if !v.is_empty() && !out.contains(&v) {
                out.push(v);
            }
        }
    }
    out
}

/// Does the (already-lowercased) `haystack` cite `[[<id>]]` (or `[[<id>#...`/`[[<id>|...`) for
/// any of `ids`?
fn cites_any(haystack: &str, ids: &[String]) -> bool {
    ids.iter().any(|id| {
        haystack.contains(&format!("[[{id}]]"))
            || haystack.contains(&format!("[[{id}#"))
            || haystack.contains(&format!("[[{id}|"))
    })
}

/// Every OTHER `.md` page in `page`'s scope root that wikilinks to it.
fn find_referrers(page: &Path, text: &str, hidden: bool) -> Vec<PathBuf> {
    let ids = page_identities(page, text);
    if ids.is_empty() {
        return Vec::new();
    }
    let root = write_gate::scope_root_for(page);
    let page_abs = std::fs::canonicalize(page).unwrap_or_else(|_| page.to_path_buf());
    let mut out = Vec::new();
    for f in walk_md_files(&root, hidden) {
        let f_abs = std::fs::canonicalize(&f).unwrap_or_else(|_| f.clone());
        if f_abs == page_abs {
            continue;
        }
        let Some(t) = md::read_text(&f) else { continue };
        if cites_any(&t.to_ascii_lowercase(), &ids) {
            out.push(f);
        }
    }
    out
}

// ─────────────────────────────── `memgrep delete-mem-topic` ───────────────────────────────

#[derive(clap::Parser)]
#[command(
    name = "delete-mem-topic",
    about = "delete a wikimem PAGE — moves it to .trashcan/, never unlinks it (RULE 0)",
    after_help = "EXAMPLES:\n\
        \x20 memgrep delete-mem-topic --page .claude/project/memory/obsolete.md --force\n\
        \x20 # preview only, nothing written\n\
        \x20 memgrep delete-mem-topic --page .claude/project/memory/obsolete.md --force --dry-run\n\
        \x20 # guard against the page having changed since you last read it\n\
        \x20 memgrep delete-mem-topic --page p.md --force --base-sha256 $(sha256sum p.md | cut -d' ' -f1)\n"
)]
struct DeleteTopicArgs {
    /// The wikimem page (`.md`) to delete.
    #[arg(long = "page")]
    page: PathBuf,
    /// Required — deleting knowledge is not routine. Also overrides the inbound-wikilink refusal.
    #[arg(long)]
    force: bool,
    /// Print the plan (destination path, referrer warnings) and write nothing.
    #[arg(long = "dry-run")]
    dry_run: bool,
    /// Compare-and-swap staleness guard — see `memgrep edit --help`.
    #[arg(long = "base-sha256")]
    base_sha256: Option<String>,
    /// Also descend into hidden files/dirs when searching for referrers (default off).
    #[arg(long = "hidden")]
    hidden: bool,
}

/// `memgrep delete-mem-topic --page P --force [--dry-run] [--base-sha256 H]` — delete a whole
/// wikimem page. Refuses without `--force`; refuses when another page in the same scope root
/// still wikilinks to it (a dangling `[[...]]` is corpus corruption) unless `--force` is given.
/// Never unlinks (RULE 0): the page is moved into `.trashcan/`, printing the exact `mv` to
/// restore it.
pub fn cmd_delete_topic_cli(args: &[String]) -> Result<()> {
    use clap::Parser as _;
    let a = DeleteTopicArgs::parse_from(
        std::iter::once("memgrep delete-mem-topic".to_string()).chain(args.iter().cloned()),
    );

    let scope = write_gate::scope_root_for(&a.page);
    let _guard = write_gate::acquire(&scope)?;
    if let Some(base) = a.base_sha256.as_deref() {
        write_gate::check_base(&a.page, base)?;
    }
    let text = if a.page.exists() {
        read_page_for_write(&a.page)?
    } else {
        anyhow::bail!(STALE_MSG)
    };

    let referrers = find_referrers(&a.page, &text, a.hidden);
    if !a.force {
        if !referrers.is_empty() {
            let list: Vec<String> = referrers.iter().map(|p| rel(p)).collect();
            anyhow::bail!(
                "{} page(s) in this scope link to {} via [[...]] (a dangling wikilink is corpus \
                 corruption) — fix the referrer(s) or pass --force to delete anyway: {}",
                referrers.len(),
                rel(&a.page),
                list.join(", ")
            );
        }
        anyhow::bail!(
            "delete-mem-topic refuses without --force — deleting knowledge is not routine"
        );
    }

    let (dest, restore) = move_to_trashcan(&a.page, a.dry_run)?;
    if a.dry_run {
        println!("dry-run: would move {} -> {}\nrestore would be: {restore}", rel(&a.page), dest.display());
    } else {
        println!("{}\tmoved -> {}\nrestore: {restore}", rel(&a.page), dest.display());
    }
    if !referrers.is_empty() {
        let list: Vec<String> = referrers.iter().map(|p| rel(p)).collect();
        println!(
            "warning: {} referrer(s) now dangling (deleted with --force): {}",
            referrers.len(),
            list.join(", ")
        );
    }
    Ok(())
}

// ─────────────────────────────── `memgrep delete-mem-atom` ───────────────────────────────

/// Every distinct `[^label]` REFERENCE inside `text` (an atom's own marker+body segment), in
/// first-appearance order. Skips the rare in-body `[^label]:` def-shaped line so it isn't
/// double-counted as its own reference — mirrors the def/ref overlap skip in the crate's own
/// footnote scanner.
fn referenced_labels(text: &str) -> Vec<String> {
    static REF_RE: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    static DEF_RE: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    let ref_re = REF_RE.get_or_init(|| regex::Regex::new(r"\[\^([^\]\s]+)\]").expect("static regex"));
    let def_re = DEF_RE.get_or_init(|| regex::Regex::new(r"^\s*\[\^([^\]\s]+)\]:").expect("static regex"));
    let mut seen: BTreeSet<String> = BTreeSet::new();
    let mut out = Vec::new();
    for line in text.lines() {
        let def_end = def_re.captures(line).and_then(|c| c.get(0)).map(|m| m.end());
        for c in ref_re.captures_iter(line) {
            let m = c.get(0).expect("group 0 always present");
            if let Some(end) = def_end
                && m.start() < end
            {
                continue; // this is the def marker itself, not a citation of it
            }
            let label = c[1].to_string();
            if seen.insert(label.clone()) {
                out.push(label);
            }
        }
    }
    out
}

/// Renumber every `[^label]:` definition in `text` to a contiguous run `1, 2, 3, …` in the order
/// the defs appear, rewriting every matching reference too. Footnote labels are page-local and
/// expected to renumber on any edit that changes the footnote set (they carry no identity of
/// their own — an atom's stable `id:` is what cross-references actually resolve by).
fn renumber_footnotes_contiguous(text: &str) -> String {
    static DEF_RE: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    let def_re = DEF_RE.get_or_init(|| regex::Regex::new(r"^\s*\[\^([^\]\s]+)\]:").expect("static regex"));
    let mut map: BTreeMap<String, String> = BTreeMap::new();
    let mut next = 1u32;
    for line in text.lines() {
        if let Some(c) = def_re.captures(line) {
            map.entry(c[1].to_string()).or_insert_with(|| {
                let label = next.to_string();
                next += 1;
                label
            });
        }
    }
    rewrite_footnote_labels(text, &map)
}

struct AtomDeleteResult {
    text: String,
    touched_labels: usize,
}

/// The pure compute step behind `delete-mem-atom`: locate the atom, decide what happens to the
/// `[^N]` lessons it references, delete, renumber, and prove the result is footnote-clean before
/// ever touching disk.
fn compute_atom_delete(
    text: &str,
    atom: &str,
    with_lessons: bool,
    keep_lessons: bool,
) -> Result<AtomDeleteResult> {
    let query = atom.strip_prefix('^').unwrap_or(atom).to_string();
    let matcher = |id: &str| atom_id_matches(id, &query);
    let (marker_idx, body_last) = locate_atom_body_matching(text, &matcher)
        .ok_or_else(|| anyhow::anyhow!("no atom answering `{atom}` on the page"))?;

    let lines: Vec<&str> = text.lines().collect();
    let seg_end = body_last + 1; // exclusive
    let atom_text = lines[marker_idx..seg_end].join("\n");
    let labels = referenced_labels(&atom_text);

    if !labels.is_empty() && !with_lessons && !keep_lessons {
        anyhow::bail!(
            "atom `{atom}` owns {} footnote lesson(s) ({}) — pass --with-lessons to delete their \
             definitions too, or --keep-lessons to leave them (e.g. still cited elsewhere); \
             nothing written",
            labels.len(),
            labels.join(", ")
        );
    }

    // Where each referenced label is DEFINED on the page (first def wins, mirroring `migrate`).
    let ctx = md::build_context(text, lines.len());
    let mut def_range: BTreeMap<String, (usize, usize)> = BTreeMap::new();
    for d in &ctx.footnote_defs {
        def_range.entry(d.label.clone()).or_insert((d.start, d.end));
    }

    let mut drop: BTreeSet<usize> = (marker_idx..seg_end).collect();
    if with_lessons {
        for lbl in &labels {
            if let Some(&(s, e)) = def_range.get(lbl) {
                for i in (s - 1)..=(e - 1).min(lines.len() - 1) {
                    drop.insert(i);
                }
            }
        }
    }

    let kept: Vec<&str> = lines
        .iter()
        .enumerate()
        .filter(|(i, _)| !drop.contains(i))
        .map(|(_, l)| *l)
        .collect();
    let mut candidate = kept.join("\n");
    candidate.push('\n');

    let out_text = if labels.is_empty() {
        candidate
    } else {
        renumber_footnotes_contiguous(&candidate)
    };

    let violations = footnote_integrity_violations(&out_text);
    if !violations.is_empty() {
        anyhow::bail!(
            "deleting `{atom}` this way would leave a footnote-integrity problem (nothing \
             written) — try {} instead: {}",
            if with_lessons { "--keep-lessons" } else { "--with-lessons" },
            violations.join("; ")
        );
    }

    Ok(AtomDeleteResult { text: out_text, touched_labels: labels.len() })
}

#[derive(clap::Parser)]
#[command(
    name = "delete-mem-atom",
    about = "delete ONE atom (and, per flag, its lessons) from a wikimem page, renumbering footnotes",
    after_help = "EXAMPLES:\n\
        \x20 # atom has no [^N] lessons — plain delete\n\
        \x20 memgrep delete-mem-atom --page .claude/project/memory/misc.md --atom foo\n\
        \x20 # atom owns lessons nobody else cites — delete their definitions too\n\
        \x20 memgrep delete-mem-atom --page misc.md --atom foo --with-lessons\n\
        \x20 # atom owns a lesson SHARED with another atom on the same page — keep the definition\n\
        \x20 memgrep delete-mem-atom --page misc.md --atom foo --keep-lessons\n\
        \x20 # guard against the page having changed since you last read it\n\
        \x20 memgrep delete-mem-atom --page misc.md --atom foo --base-sha256 $(sha256sum misc.md | cut -d' ' -f1)\n"
)]
struct DeleteAtomArgs {
    /// The wikimem page (`.md`) the atom lives on.
    #[arg(long = "page")]
    page: PathBuf,
    /// The atom to delete: `^name`, its canonical `ATOM-XXXX-XXXX`, or the bare 8-char payload.
    #[arg(long = "atom")]
    atom: String,
    /// Also delete the `[^N]:` definitions the atom references.
    #[arg(long = "with-lessons")]
    with_lessons: bool,
    /// Keep the `[^N]:` definitions the atom references (strips only the now-gone in-body refs).
    #[arg(long = "keep-lessons")]
    keep_lessons: bool,
    /// Compare-and-swap staleness guard — see `memgrep edit --help`.
    #[arg(long = "base-sha256")]
    base_sha256: Option<String>,
    /// Print the plan and write nothing.
    #[arg(long = "dry-run")]
    dry_run: bool,
    /// Also descend into hidden files/dirs when reindexing the scope (default off).
    #[arg(long = "hidden")]
    hidden: bool,
}

/// `memgrep delete-mem-atom --page P --atom A [--with-lessons | --keep-lessons] [--base-sha256 H]
/// [--dry-run]` — delete one atom's marker+body from a wikimem page. Refuses when the atom owns
/// `[^N]` lesson refs and neither lesson flag is given. Renumbers the page's remaining footnotes
/// to a contiguous run and refuses (writing nothing) if that would leave a dangling reference or
/// an unreferenced definition — the caller's cue to try the other flag.
pub fn cmd_delete_atom_cli(args: &[String]) -> Result<()> {
    use clap::Parser as _;
    let a = DeleteAtomArgs::parse_from(
        std::iter::once("memgrep delete-mem-atom".to_string()).chain(args.iter().cloned()),
    );
    if a.with_lessons && a.keep_lessons {
        anyhow::bail!("--with-lessons and --keep-lessons are mutually exclusive");
    }

    let scope = write_gate::scope_root_for(&a.page);
    let _guard = write_gate::acquire(&scope)?;
    if let Some(base) = a.base_sha256.as_deref() {
        write_gate::check_base(&a.page, base)?;
    }
    let text = if a.page.exists() {
        read_page_for_write(&a.page)?
    } else {
        anyhow::bail!(STALE_MSG)
    };

    let r = compute_atom_delete(&text, &a.atom, a.with_lessons, a.keep_lessons)?;

    if a.dry_run {
        println!(
            "dry-run: would delete atom `{}` from {} ({} footnote label(s) touched)",
            a.atom,
            rel(&a.page),
            r.touched_labels
        );
        return Ok(());
    }

    let out = bump_page_lmd(&r.text, &today_date());
    atomic_write_page(&a.page, &out)?;
    reindex_owning_scope(&a.page, a.hidden)?;
    println!(
        "{}\tdeleted atom `{}` ({} footnote label(s) touched)",
        rel(&a.page),
        a.atom,
        r.touched_labels
    );
    Ok(())
}

// ─────────────────────────────────────── tests ───────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::Mutex;

    // `JANITOR_GLOBAL_STATE_DIR` is a PROCESS-WIDE env var but `cargo test` runs tests in
    // parallel threads of the SAME process — any test that sets it must hold this for its whole
    // body, mirroring `write_gate`'s own test isolation (see its `ENV_MUTEX` for the measured
    // flake this prevents).
    static ENV_MUTEX: Mutex<()> = Mutex::new(());
    static COUNTER: AtomicU64 = AtomicU64::new(0);

    fn env_lock() -> std::sync::MutexGuard<'static, ()> {
        ENV_MUTEX.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    /// A fresh, empty temp dir under the OS temp root — never the real `~/.claude/...` state.
    fn tmpdir(label: &str) -> PathBuf {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!(
            "memgrep-mem-delete-test-{label}-{}-{n}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write_page(dir: &Path, name: &str, body: &str) -> PathBuf {
        let p = dir.join(format!("{name}.md"));
        let text = format!(
            "---\nname: {name}\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"{name}\"\n---\n{body}"
        );
        std::fs::write(&p, text).unwrap();
        p
    }

    #[test]
    fn refuses_topic_delete_when_a_referrer_exists_then_force_moves_it_to_trashcan() {
        let _env = env_lock();
        let dir = tmpdir("topic-refuse");
        unsafe {
            std::env::set_var("JANITOR_GLOBAL_STATE_DIR", dir.join("state"));
        }
        let target = write_page(&dir, "obsolete", "the obsolete fact.\n\n## Notes and lessons learned\n");
        write_page(&dir, "keeper", "see [[obsolete]] for background.\n\n## Notes and lessons learned\n");

        let page_arg = target.display().to_string();
        let err = cmd_delete_topic_cli(&["--page".to_string(), page_arg.clone()])
            .expect_err("must refuse: a referrer links to it and --force was not given");
        assert!(err.to_string().contains("keeper"), "names the referrer: {err}");
        assert!(target.exists(), "refused delete must not touch the page");

        cmd_delete_topic_cli(&["--page".to_string(), page_arg, "--force".to_string()])
            .expect("--force overrides the referrer refusal");
        assert!(!target.exists(), "the page must be gone from its original path");
        let trashcan = dir.join(".trashcan");
        assert!(trashcan.is_dir(), "a .trashcan dir must have been created");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn trashcan_move_preserves_bytes_and_the_printed_mv_restores_it() {
        let dir = tmpdir("trash-roundtrip");
        let page = write_page(&dir, "roundtrip", "some fact worth keeping.\n");
        let original_bytes = std::fs::read(&page).unwrap();

        let (dest, restore) = move_to_trashcan(&page, false).unwrap();
        assert!(!page.exists(), "source must be gone after the move");
        assert!(dest.exists(), "destination must exist");
        assert_eq!(std::fs::read(&dest).unwrap(), original_bytes, "bytes must be preserved exactly");
        assert!(restore.starts_with("mv "), "restore command shape: {restore}");

        // Execute the printed restore command literally (dest -> src), no shortcuts.
        let parts: Vec<&str> = restore.trim_start_matches("mv ").split(' ').collect();
        assert_eq!(parts.len(), 2, "restore command must be exactly `mv <dest> <src>`: {restore}");
        std::fs::rename(parts[0], parts[1]).expect("the printed mv must actually restore the page");
        assert!(page.exists(), "page must be back at its original path");
        assert_eq!(std::fs::read(&page).unwrap(), original_bytes, "restored bytes must be identical");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn delete_atom_with_lessons_renumbers_remaining_footnotes_contiguously() {
        let _env = env_lock();
        let dir = tmpdir("atom-renumber");
        unsafe {
            std::env::set_var("JANITOR_GLOBAL_STATE_DIR", dir.join("state"));
        }
        let page = write_page(
            &dir,
            "misc",
            "^foo [keywords: k]\nfoo fact.[^1]\n\n\
             ^bar [keywords: k]\nbar fact.[^2]\n\n\
             ^baz [keywords: k]\nbaz fact.[^3]\n\n\
             ## Notes and lessons learned\n\
             [^1]: foo lesson.\n\
             [^2]: bar lesson.\n\
             [^3]: baz lesson.\n",
        );

        cmd_delete_atom_cli(&[
            "--page".to_string(),
            page.display().to_string(),
            "--atom".to_string(),
            "bar".to_string(),
            "--with-lessons".to_string(),
        ])
        .expect("bar's lesson is unshared, --with-lessons must succeed");

        let out = std::fs::read_to_string(&page).unwrap();
        assert!(!out.contains("^bar"), "atom gone: {out}");
        assert!(!out.contains("bar lesson."), "its lesson gone: {out}");
        assert!(out.contains("foo fact.[^1]"), "foo's ref untouched: {out}");
        assert!(out.contains("[^1]: foo lesson."), "foo's def untouched: {out}");
        assert!(out.contains("baz fact.[^2]"), "baz's ref renumbered to [^2]: {out}");
        assert!(out.contains("[^2]: baz lesson."), "baz's def renumbered to [^2]: {out}");
        assert!(footnote_integrity_violations(&out).is_empty(), "must be footnote-clean: {out}");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn base_sha256_mismatch_refuses_and_writes_nothing() {
        let _env = env_lock();
        let dir = tmpdir("atom-stale");
        unsafe {
            std::env::set_var("JANITOR_GLOBAL_STATE_DIR", dir.join("state"));
        }
        let page = write_page(&dir, "misc", "^foo [keywords: k]\nfoo fact, no lessons.\n");
        let before = std::fs::read_to_string(&page).unwrap();

        let err = cmd_delete_atom_cli(&[
            "--page".to_string(),
            page.display().to_string(),
            "--atom".to_string(),
            "foo".to_string(),
            "--base-sha256".to_string(),
            "0".repeat(64),
        ])
        .expect_err("a wrong base hash must refuse");
        assert_eq!(err.to_string(), STALE_MSG);
        assert_eq!(std::fs::read_to_string(&page).unwrap(), before, "nothing must be written on a stale base");

        let _ = std::fs::remove_dir_all(&dir);
    }
}
