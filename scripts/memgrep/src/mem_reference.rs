//! `reference-mem-topic` / `reference-mem-atom` (TRDD-VJL1YTCG Part B).
//!
//! Adds a `[[wikilink]]` between two wikimem elements. THE LINK LAW
//! (`rules/markdown-memory-recall.md`) is the whole point of this module: **every link is
//! bidirectional, and both ends are wired in the SAME edit** — a verb that wrote only one end
//! would manufacture exactly the defect `memgrep lint` reports.
//!
//! `#![allow(dead_code)]`: the dispatch wiring in `main.rs` (Step 3 of the build, lead-owned)
//! has not landed yet, so `cmd_reference_topic_cli`/`cmd_reference_atom_cli` have no caller in
//! the binary until then — only their own `#[cfg(test)]` module exercises them today.

use crate::md;
use crate::memory::{
    atom_id_matches, atomic_write_page, bump_page_lmd, fence_step, footer_section_line,
    locate_atom_body_matching, read_page_for_write, reindex_owning_scope, rel, today_date, Fence,
};
use crate::write_gate;
use anyhow::{Context, Result};
use std::path::{Path, PathBuf};

/// The wikilink TARGET NAME `path` resolves under — frontmatter `name:` (alias `topic:`),
/// lowercased, else the file stem lowercased. Mirrors the EXACT key `build_graph` registers
/// first for a page (`memory.rs::build_graph`, issue #49), so a `[[name]]` written anywhere else
/// in the corpus is GUARANTEED to resolve to `path` — no need to re-run the link graph to prove
/// it, only to know that page exists (which reading it for the write already established).
fn page_link_name(path: &Path, text: &str) -> String {
    let fm = md::parse_frontmatter(text);
    fm.get("name")
        .or_else(|| fm.get("topic"))
        .map(|s| s.trim().to_ascii_lowercase())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| {
            path.file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or_default()
                .to_ascii_lowercase()
        })
}

/// True iff `text` already carries a `[[name]]` (or `[[name|alias]]`) wikilink — case-insensitive,
/// so re-running the same reference command is a no-op instead of a duplicate.
fn already_links_to(text: &str, name: &str) -> bool {
    let hay = text.to_ascii_lowercase();
    let plain = format!("[[{name}]]").to_ascii_lowercase();
    let alias = format!("[[{name}|").to_ascii_lowercase();
    hay.contains(&plain) || hay.contains(&alias)
}

/// The 0-based line index of the `## See also` heading, fence-aware, or `None` if absent.
fn see_also_heading_line(text: &str) -> Option<usize> {
    let mut fence: Option<Fence> = None;
    for (i, line) in text.lines().enumerate() {
        if fence_step(line, &mut fence) {
            continue;
        }
        if fence.is_some() {
            continue;
        }
        let t = line.trim_start();
        if t.starts_with('#') && t.trim_start_matches('#').trim().eq_ignore_ascii_case("see also") {
            return Some(i);
        }
    }
    None
}

/// The 0-based line index of the next heading strictly after `start`, fence-aware — the end
/// boundary of the section opened at `start`.
fn next_heading_after(text: &str, start: usize) -> Option<usize> {
    let mut fence: Option<Fence> = None;
    for (i, line) in text.lines().enumerate() {
        if fence_step(line, &mut fence) {
            continue;
        }
        if i <= start || fence.is_some() {
            continue;
        }
        if line.trim_start().starts_with('#') {
            return Some(i);
        }
    }
    None
}

/// Add `- [[name]]` under the page's `## See also` section, creating that section (spliced before
/// the earliest footer heading — `footer_section_line`, same boundary `add-atom` uses) when the
/// page has none. Callers only invoke this once `already_links_to` says a write is needed.
fn add_see_also_entry(text: &str, name: &str) -> String {
    let entry = format!("- [[{name}]]");
    let mut lines: Vec<String> = text.lines().map(str::to_string).collect();
    if let Some(h) = see_also_heading_line(text) {
        let mut at = next_heading_after(text, h).unwrap_or(lines.len());
        // Keep the new entry with the existing list rather than after a trailing blank gap.
        while at > h + 1 && lines.get(at - 1).map(|l| l.trim().is_empty()).unwrap_or(false) {
            at -= 1;
        }
        lines.insert(at, entry);
    } else {
        let block = [
            String::new(),
            "## See also".to_string(),
            String::new(),
            entry,
            String::new(),
        ];
        match footer_section_line(text) {
            Some(idx) => {
                let tail = lines.split_off(idx);
                lines.extend(block);
                lines.extend(tail);
            }
            None => lines.extend(block),
        }
    }
    let mut out = lines.join("\n");
    out.push('\n');
    out
}

/// Ensure `page_text` links to `target_name`; returns `(new_text, changed)` — `changed` is false
/// (and `new_text == page_text`) when the link already exists.
fn ensure_topic_link(page_text: &str, target_name: &str) -> (String, bool) {
    if already_links_to(page_text, target_name) {
        (page_text.to_string(), false)
    } else {
        (add_see_also_entry(page_text, target_name), true)
    }
}

#[derive(clap::Parser)]
#[command(
    name = "memgrep reference-mem-topic",
    about = "link two wikimem pages with a bidirectional [[wikilink]] in their `## See also` sections",
    after_help = "EXAMPLES:\n\
        \x20 # THE LINK LAW: wire both ends in one edit\n\
        \x20 memgrep reference-mem-topic --page .claude/project/memory/rotator.md --to .claude/project/memory/janitor-architecture.md\n\
        \x20 # preview without writing\n\
        \x20 memgrep reference-mem-topic --page a.md --to b.md --dry-run\n\
        \x20 # guard against --page having changed since you last read it\n\
        \x20 memgrep reference-mem-topic --page a.md --to b.md --base-sha256 $(sha256sum a.md | cut -d' ' -f1)\n"
)]
struct ReferenceTopicArgs {
    /// The wikimem page to link FROM.
    #[arg(long = "page")]
    page: PathBuf,
    /// The wikimem page to link TO — the reciprocal link is added here too.
    #[arg(long = "to")]
    to: PathBuf,
    /// Also descend into hidden files/dirs when reindexing (default off).
    #[arg(long = "hidden")]
    hidden: bool,
    /// Compare-and-swap staleness guard (TRDD-7YHT3FNK), checked against `--page`'s current
    /// bytes. On mismatch nothing is written and the command fails with the canonical refusal.
    #[arg(long = "base-sha256")]
    base_sha256: Option<String>,
    /// Report what would change without writing anything.
    #[arg(long = "dry-run")]
    dry_run: bool,
}

/// `memgrep reference-mem-topic --page A --to B` — wire `[[B]]` into A's `## See also` and
/// `[[A]]` into B's, in one edit. Idempotent (a link that already exists is a no-op, never
/// duplicated); refuses when either page does not exist, so the link can never dangle.
pub fn cmd_reference_topic_cli(args: &[String]) -> Result<()> {
    use clap::Parser as _;
    let a = ReferenceTopicArgs::parse_from(
        std::iter::once("memgrep reference-mem-topic".to_string()).chain(args.iter().cloned()),
    );
    if a.page == a.to {
        anyhow::bail!("--page and --to are the same page — nothing to link");
    }

    // Deadlock-free two-scope lock, shared with migrate/merge/split — see `write_gate::acquire_two`.
    let (_g1, _g2) = write_gate::acquire_two(&a.page, &a.to)?;

    if let Some(base) = a.base_sha256.as_deref() {
        write_gate::check_base(&a.page, base)?;
    }
    // Reading both pages through the strict, size-capped reader IS the resolve-or-refuse check:
    // a page that fails to read here would otherwise become a dangling [[link]] the graph can
    // never resolve.
    let page_text = read_page_for_write(&a.page).context("--page")?;
    let to_text = read_page_for_write(&a.to).context("--to")?;

    let page_name = page_link_name(&a.page, &page_text);
    let to_name = page_link_name(&a.to, &to_text);

    let (new_page, page_changed) = ensure_topic_link(&page_text, &to_name);
    let (new_to, to_changed) = ensure_topic_link(&to_text, &page_name);

    if !page_changed && !to_changed {
        println!("already linked: {} <-> {}", rel(&a.page), rel(&a.to));
        return Ok(());
    }
    if a.dry_run {
        println!(
            "would link {} <-> {} (page {}, to {})",
            rel(&a.page),
            rel(&a.to),
            if page_changed { "gains a link" } else { "unchanged" },
            if to_changed { "gains a link" } else { "unchanged" },
        );
        return Ok(());
    }

    let today = today_date();
    // Idempotent by construction, unlike `migrate`'s move: a crash between the two writes below
    // self-heals on retry (the already-written side is detected as `already_links_to` and skipped,
    // the other side is written), so there is no B-before-A ordering discipline to preserve here.
    if page_changed {
        atomic_write_page(&a.page, &bump_page_lmd(&new_page, &today))?;
        reindex_owning_scope(&a.page, a.hidden)?;
    }
    if to_changed {
        atomic_write_page(&a.to, &bump_page_lmd(&new_to, &today))?;
        reindex_owning_scope(&a.to, a.hidden)?;
    }
    println!(
        "linked {} <-> {} (page {}, to {})",
        rel(&a.page),
        rel(&a.to),
        if page_changed { "updated" } else { "unchanged" },
        if to_changed { "updated" } else { "unchanged" },
    );
    Ok(())
}

#[derive(clap::Parser)]
#[command(
    name = "memgrep reference-mem-atom",
    about = "add an inline [[wikilink]] inside one atom's body, wiring the reciprocal link on the target page",
    after_help = "EXAMPLES:\n\
        \x20 # cross-reference an atom to the page that owns the related subject\n\
        \x20 memgrep reference-mem-atom --page misc.md --atom ATOM-234P-U35Q --to rotator.md\n\
        \x20 # preview without writing\n\
        \x20 memgrep reference-mem-atom --page misc.md --atom ATOM-234P-U35Q --to rotator.md --dry-run\n\
        \x20 # guard against --page having changed since you last read it\n\
        \x20 memgrep reference-mem-atom --page misc.md --atom ATOM-234P-U35Q --to rotator.md --base-sha256 $(sha256sum misc.md | cut -d' ' -f1)\n"
)]
struct ReferenceAtomArgs {
    /// The page carrying the atom to link FROM.
    #[arg(long = "page")]
    page: PathBuf,
    /// The atom to annotate: `^name`, its canonical `ATOM-XXXX-XXXX`, or the bare 8-char payload.
    #[arg(long = "atom")]
    atom: String,
    /// The wikimem page to link TO — the reciprocal link is added to its `## See also` section.
    #[arg(long = "to")]
    to: PathBuf,
    /// Also descend into hidden files/dirs when reindexing (default off).
    #[arg(long = "hidden")]
    hidden: bool,
    /// Compare-and-swap staleness guard (TRDD-7YHT3FNK), checked against `--page`'s current
    /// bytes. On mismatch nothing is written and the command fails with the canonical refusal.
    #[arg(long = "base-sha256")]
    base_sha256: Option<String>,
    /// Report what would change without writing anything.
    #[arg(long = "dry-run")]
    dry_run: bool,
}

/// `memgrep reference-mem-atom --page P --atom ID --to B` — append `See also: [[B]]` inside the
/// atom's body on P, and wire the reciprocal `[[P]]` into B's `## See also` section. Idempotent
/// and refuses when either the atom or the target page does not resolve.
pub fn cmd_reference_atom_cli(args: &[String]) -> Result<()> {
    use clap::Parser as _;
    let a = ReferenceAtomArgs::parse_from(
        std::iter::once("memgrep reference-mem-atom".to_string()).chain(args.iter().cloned()),
    );
    if a.page == a.to {
        anyhow::bail!("--page and --to are the same page — nothing to link");
    }

    // Deadlock-free two-scope lock, shared with migrate/merge/split — see `write_gate::acquire_two`.
    let (_g1, _g2) = write_gate::acquire_two(&a.page, &a.to)?;

    if let Some(base) = a.base_sha256.as_deref() {
        write_gate::check_base(&a.page, base)?;
    }
    let page_text = read_page_for_write(&a.page).context("--page")?;
    let to_text = read_page_for_write(&a.to).context("--to")?;

    let query = a.atom.strip_prefix('^').unwrap_or(&a.atom).to_string();
    let matcher = |id: &str| atom_id_matches(id, &query);
    let (marker_idx, body_last_idx) = locate_atom_body_matching(&page_text, &matcher)
        .ok_or_else(|| anyhow::anyhow!("no atom answering `{}` on the --page page", a.atom))?;

    let page_name = page_link_name(&a.page, &page_text);
    let to_name = page_link_name(&a.to, &to_text);

    // Idempotency is scoped to the atom's own body span, not the whole page — a link the SAME
    // target already carries elsewhere on the page must not stop this atom from getting its own.
    let lines: Vec<&str> = page_text.lines().collect();
    let body = lines
        .get(marker_idx..=body_last_idx)
        .map(|s| s.join("\n"))
        .unwrap_or_default();
    let atom_changed = !already_links_to(&body, &to_name);
    let new_page = if atom_changed {
        let mut owned: Vec<String> = page_text.lines().map(str::to_string).collect();
        owned.insert(body_last_idx + 1, format!("See also: [[{to_name}]]"));
        let mut out = owned.join("\n");
        out.push('\n');
        out
    } else {
        page_text.clone()
    };

    let (new_to, to_changed) = ensure_topic_link(&to_text, &page_name);

    if !atom_changed && !to_changed {
        println!("already linked: {} (atom {}) <-> {}", rel(&a.page), a.atom, rel(&a.to));
        return Ok(());
    }
    if a.dry_run {
        println!(
            "would link {} (atom {}) <-> {} (atom {}, to {})",
            rel(&a.page),
            a.atom,
            rel(&a.to),
            if atom_changed { "gains a link" } else { "unchanged" },
            if to_changed { "gains a link" } else { "unchanged" },
        );
        return Ok(());
    }

    let today = today_date();
    // Same idempotent-retry reasoning as `reference-mem-topic`: order doesn't matter for
    // correctness, only for which side a mid-crash leaves already-done.
    if to_changed {
        atomic_write_page(&a.to, &bump_page_lmd(&new_to, &today))?;
        reindex_owning_scope(&a.to, a.hidden)?;
    }
    if atom_changed {
        atomic_write_page(&a.page, &bump_page_lmd(&new_page, &today))?;
        reindex_owning_scope(&a.page, a.hidden)?;
    }
    println!(
        "linked {} (atom {}) <-> {} (atom {}, to {})",
        rel(&a.page),
        a.atom,
        rel(&a.to),
        if atom_changed { "updated" } else { "unchanged" },
        if to_changed { "updated" } else { "unchanged" },
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A fresh, uniquely-named temp dir for one test (tag keeps same-process tests from
    /// colliding on the shared `std::process::id()`) — same pattern as `memory.rs::lint_tmpdir`.
    fn ref_tmpdir(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("memgrep_ref_{tag}_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write_page(dir: &Path, filename: &str, name: &str, body: &str) -> PathBuf {
        let path = dir.join(filename);
        let content = format!(
            "---\nname: {name}\ndescription: \"test page {name}\"\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n\n# {name}\n\n{body}\n## Notes and lessons learned\n"
        );
        std::fs::write(&path, content).unwrap();
        path
    }

    #[test]
    fn reference_topic_wires_both_ends_in_one_call() {
        let dir = ref_tmpdir("topic_both");
        let a = write_page(&dir, "a.md", "page-a", "Some prose about A.\n");
        let b = write_page(&dir, "b.md", "page-b", "Some prose about B.\n");

        let args = vec![
            "--page".to_string(),
            a.display().to_string(),
            "--to".to_string(),
            b.display().to_string(),
        ];
        cmd_reference_topic_cli(&args).unwrap();

        let a_text = std::fs::read_to_string(&a).unwrap();
        let b_text = std::fs::read_to_string(&b).unwrap();
        assert!(a_text.to_ascii_lowercase().contains("[[page-b]]"), "A must link to B:\n{a_text}");
        assert!(b_text.to_ascii_lowercase().contains("[[page-a]]"), "B must link back to A:\n{b_text}");
        // The link law, asserted directly: both ends wired, not just one.
        assert!(a_text.contains("## See also"));
        assert!(b_text.contains("## See also"));

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn reference_topic_second_call_is_a_no_op() {
        let dir = ref_tmpdir("topic_idempotent");
        let a = write_page(&dir, "a.md", "page-a", "Prose A.\n");
        let b = write_page(&dir, "b.md", "page-b", "Prose B.\n");
        let args = vec![
            "--page".to_string(),
            a.display().to_string(),
            "--to".to_string(),
            b.display().to_string(),
        ];
        cmd_reference_topic_cli(&args).unwrap();
        let a_after_first = std::fs::read_to_string(&a).unwrap();
        let b_after_first = std::fs::read_to_string(&b).unwrap();

        cmd_reference_topic_cli(&args).unwrap();
        let a_after_second = std::fs::read_to_string(&a).unwrap();
        let b_after_second = std::fs::read_to_string(&b).unwrap();

        assert_eq!(a_after_first, a_after_second, "re-running must add nothing to A");
        assert_eq!(b_after_first, b_after_second, "re-running must add nothing to B");
        // The second call's byte-count of `[[page-b]]`/`[[page-a]]` must stay at exactly one —
        // a duplicated link, not just an unchanged file, is what idempotency actually guards.
        assert_eq!(a_after_second.to_ascii_lowercase().matches("[[page-b]]").count(), 1);
        assert_eq!(b_after_second.to_ascii_lowercase().matches("[[page-a]]").count(), 1);

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn reference_topic_refuses_unresolvable_target() {
        let dir = ref_tmpdir("topic_missing");
        let a = write_page(&dir, "a.md", "page-a", "Prose A.\n");
        let missing = dir.join("does-not-exist.md");
        let args = vec![
            "--page".to_string(),
            a.display().to_string(),
            "--to".to_string(),
            missing.display().to_string(),
        ];
        let result = cmd_reference_topic_cli(&args);
        assert!(result.is_err(), "a --to page that does not exist must be refused, never a dangling link");
        // Nothing must have been written to A on a refused target.
        let a_text = std::fs::read_to_string(&a).unwrap();
        assert!(!a_text.contains("[["), "A must be untouched when --to fails to resolve");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn reference_atom_wires_atom_body_and_target_page() {
        let dir = ref_tmpdir("atom_both");
        let page = write_page(
            &dir,
            "page.md",
            "page-x",
            "^ATOM-TEST-0001 [keywords: something]\n\nAtom body line one.\n\n",
        );
        let target = write_page(&dir, "target.md", "page-y", "Prose Y.\n");

        let args = vec![
            "--page".to_string(),
            page.display().to_string(),
            "--atom".to_string(),
            "ATOM-TEST-0001".to_string(),
            "--to".to_string(),
            target.display().to_string(),
        ];
        cmd_reference_atom_cli(&args).unwrap();

        let page_text = std::fs::read_to_string(&page).unwrap();
        let target_text = std::fs::read_to_string(&target).unwrap();
        assert!(
            page_text.to_ascii_lowercase().contains("see also: [[page-y]]"),
            "the atom body must carry the inline reference:\n{page_text}"
        );
        assert!(
            target_text.to_ascii_lowercase().contains("[[page-x]]"),
            "the target page must carry the reciprocal link back:\n{target_text}"
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn reference_atom_refuses_when_the_atom_does_not_exist() {
        let dir = ref_tmpdir("atom_missing");
        let page = write_page(&dir, "page.md", "page-x", "No atoms here.\n");
        let target = write_page(&dir, "target.md", "page-y", "Prose Y.\n");
        let args = vec![
            "--page".to_string(),
            page.display().to_string(),
            "--atom".to_string(),
            "ATOM-NOPE-0000".to_string(),
            "--to".to_string(),
            target.display().to_string(),
        ];
        let result = cmd_reference_atom_cli(&args);
        assert!(result.is_err(), "a nonexistent atom id must be refused");
        let target_text = std::fs::read_to_string(&target).unwrap();
        assert!(!target_text.contains("[["), "the target page must be untouched when the atom lookup fails");

        let _ = std::fs::remove_dir_all(&dir);
    }
}
