//! `replace-mem-topic` — the whole-page replace verb (TRDD-XI10BA5D A3 step 1).
//!
//! Owner requirement (card, verbatim): "even if the whole wikimem is going to be rewritten, and
//! the agent passes the whole content of the wikimem as a parameter to the memgrep, the memgrep
//! guarantees that the content will be linted, fixed if possible, formatted correctly, verified
//! against the mandatory rule of 10 key-phrases minimum per atom, and all specs checked and
//! verified, or it will block the edit and return error."
//!
//! The caller supplies the COMPLETE new content of one existing page — frontmatter included —
//! through an EXPLICIT channel (`--content-file F` or `--content -` for stdin; stdin is NEVER
//! implicitly the content, the e6b42169 contract). The proposed bytes go through the ONE shared
//! gate every other write uses (`pre_write::write_gated_with`): lint floors, the id-set rule with
//! `--retire-atom` declarations, the introduced-one-sided-link refusal, and commit's own
//! control-byte defence. A refusal writes nothing and names every violation (ids/counts/paths
//! only — the no-leak contract); a success replaces the page atomically.
//!
//! NO preservation or regeneration logic lives here (A3 step-1 spec amendment i): the verb does
//! not carry over old frontmatter, does not regenerate a TOC, and does not bump `lmd:` — the
//! caller's content IS the page, and the gate's lint/normalize passes decide validity. A missing
//! or stale `lmd:` is a lint finding (grandfathered at the gate), not something this verb fixes
//! behind the caller's back.

use crate::memory::{
    parse_block_props, raw_footnote_defs, read_page_for_write, reindex_owning_scope,
    resolve_atoms_from_text, split_note_metadata,
};
use crate::write_gate;
use anyhow::Result;
use clap::Parser;
use std::collections::BTreeSet;
use std::path::PathBuf;

#[derive(Parser)]
#[command(
    name = "memgrep replace-mem-topic",
    about = "replace a page's COMPLETE content in one gated write — full pre-write gate, or refuse naming every violation",
    after_help = "EXAMPLES:\n\
        \x20 # rewrite a page wholesale — the file IS the new page, frontmatter included\n\
        \x20 memgrep replace-mem-topic --page .claude/project/memory/rotator.md --content-file /tmp/new-page.md\n\
        \x20 # pipe the new content on stdin — `-` is the ONLY stdin form (never implicit)\n\
        \x20 cat /tmp/new-page.md | memgrep replace-mem-topic --page p.md --content -\n\
        \x20 # a rewrite that legitimately dissolves atoms declares each dropped id\n\
        \x20 memgrep replace-mem-topic --page p.md --content-file f.md --retire-atom ATOM-234P-U35Q\n\
        \x20 # guard against a page mutated since you last read it\n\
        \x20 memgrep replace-mem-topic --page p.md --content-file f.md --base-sha256 $(sha256sum p.md | cut -d' ' -f1)\n"
)]
struct ReplaceTopicArgs {
    /// The wikimem page (`.md`) to replace — it must already exist.
    #[arg(long = "page")]
    page: PathBuf,
    /// Path to a file holding the COMPLETE new page content (frontmatter included) — raw bytes,
    /// never interpreted.
    #[arg(long = "content-file")]
    content_file: Option<PathBuf>,
    /// The COMPLETE new page content inline; `-` reads stdin. The content arrives ONLY through
    /// this flag or `--content-file` — stdin is never implicitly the content (the
    /// update-mem-atom contract, TRDD-XI10BA5D A3 / e6b42169).
    #[arg(long = "content")]
    content: Option<String>,
    /// An atom/lesson id this rewrite legitimately DISSOLVES (repeatable). Retired ids are
    /// exempt from the gate's id-persistence check — a whole-page rewrite may dissolve atoms —
    /// and a retired id re-minted ONCE on the proposed page is a legal re-mint. The exemption
    /// does NOT lift within-page uniqueness: the same id twice on one page still refuses.
    #[arg(long = "retire-atom")]
    retire_atom: Vec<String>,
    /// Compare-and-swap staleness guard — see `memgrep update-mem-topic --help`.
    #[arg(long = "base-sha256")]
    base_sha256: Option<String>,
    /// Also descend into hidden files/dirs when reindexing the scope (default off).
    #[arg(long = "hidden")]
    hidden: bool,
}

/// Refuse an atom/lesson id carried MORE THAN ONCE on the proposed page.
///
/// VERB-level, deliberately not a gate rule (A3 step-1 constraint: do not widen pre_write.rs):
/// the gate's inventories key by id (`or_insert`), so a twice-carried id is invisible to the
/// id-set rule, and `atom-dup-id` is a corpus-pass finding `lint_page_text` never emits. This is
/// the same shape as migrate's `atom_props_violations` pre-flight — the verb refuses at its own
/// surface before the lock is taken. Retired ids are NOT exempt here (a re-mint is legal ONCE;
/// twice is a duplicate, and the retirement exclusion must not become an over-exclusion).
/// Names ids and counts only — never page content (the no-leak contract).
///
/// `pub(crate)` since A3 step 2: `new-mem-topic`'s content-CREATE mode calls it too — the same
/// blind spot exists on a create (no retires there, so every argument still applies).
pub(crate) fn refuse_duplicate_ids_within_page(text: &str) -> Result<()> {
    let mut seen: std::collections::BTreeMap<String, usize> = std::collections::BTreeMap::new();
    for a in resolve_atoms_from_text(text) {
        *seen.entry(a.id).or_insert(0) += 1;
    }
    let lines: Vec<&str> = text.lines().collect();
    for (_label, raw) in raw_footnote_defs(&lines) {
        let (meta, _rest) = split_note_metadata(&raw);
        let Some(meta) = meta else { continue };
        let Some(id) = parse_block_props(&meta).get("id").and_then(|v| v.first()).cloned()
        else {
            continue; // no stable id — nothing for this check to pin (lint warns separately)
        };
        *seen.entry(id).or_insert(0) += 1;
    }
    let dups: Vec<String> = seen
        .into_iter()
        .filter(|(_, n)| *n > 1)
        .map(|(id, n)| format!("`{id}` ×{n}"))
        .collect();
    if dups.is_empty() {
        return Ok(());
    }
    anyhow::bail!(
        "write refused: the proposed page carries duplicate atom/lesson id(s) — an id may \
         appear at most ONCE on a page, and --retire-atom does not lift within-page uniqueness \
         ({}: {}); nothing was written",
        dups.len(),
        dups.join(", ")
    )
}

/// The EXPLICIT content channel shared by `replace-mem-topic` and `new-mem-topic`'s
/// content-CREATE mode (A3 step 2) — exactly the e6b42169 contract: `--content-file F` /
/// `--content T` / `--content -` (stdin). `None` on both flags ⇒ refuse BEFORE reading stdin, so
/// a terminal-attached caller is never left blocked on a prompt it never agreed to; a
/// piped-but-undeclared stdin is ignored, never implicitly the content. Both flags ⇒ refuse.
/// Empty content ⇒ refuse (the page IS the content).
///
/// Shared because the two verbs' contracts are byte-identical here (A3 step-2 spec: same
/// channels, same refusals); one implementation means one contract, not two that can drift.
pub(crate) fn read_explicit_content(
    content: Option<&str>,
    content_file: Option<&std::path::Path>,
    what: &str,
) -> Result<String> {
    if content.is_some() && content_file.is_some() {
        anyhow::bail!("--content and --content-file are mutually exclusive — pass one");
    }
    match (content, content_file) {
        (Some("-"), _) => {
            use std::io::Read;
            let mut text = String::new();
            std::io::stdin().read_to_string(&mut text)?;
            if text.trim().is_empty() {
                anyhow::bail!("empty content on stdin — pipe the COMPLETE page (--content - reads stdin)");
            }
            Ok(text)
        }
        (Some(text), _) => {
            if text.trim().is_empty() {
                anyhow::bail!("empty content via --content — {what}");
            }
            Ok(text.to_string())
        }
        (_, Some(path)) => {
            let raw = std::fs::read_to_string(path)
                .map_err(|e| anyhow::anyhow!("--content-file {}: {e}", path.display()))?;
            if raw.trim().is_empty() {
                anyhow::bail!("empty content via --content-file {} — {what}", path.display());
            }
            Ok(raw)
        }
        (None, None) => anyhow::bail!(
            "no content channel — pass --content-file F or --content - (stdin is NEVER \
             implicitly the content; TRDD-XI10BA5D A3)"
        ),
    }
}

/// `memgrep replace-mem-topic --page P (--content-file F | --content T|‑) [--retire-atom ID]…
/// [--base-sha256 H] [--hidden]` — replace a page's COMPLETE content (TRDD-XI10BA5D A3 step 1).
///
/// The proposed bytes run the full shared gate (`pre_write::write_gated_with`) and land
/// atomically, or nothing is written and every violation is named. The verb adds nothing of its
/// own to the bytes: no frontmatter carry-over, no TOC regeneration, no `lmd:` bump (spec
/// amendment i — the caller's content IS the page; every other content verb's preserve-or-stamp
/// logic is deliberately absent here).
pub fn cmd_replace_topic_cli(args: &[String]) -> Result<()> {
    let a = ReplaceTopicArgs::parse_from(
        std::iter::once("memgrep replace-mem-topic".to_string()).chain(args.iter().cloned()),
    );

    // EXPLICIT channels only (the e6b42169 contract) — the shared reader refuses BEFORE reading
    // stdin when no flag is present (a terminal caller is never left blocked on a prompt it
    // never agreed to), and ignores a piped-but-undeclared stdin.
    let proposed = read_explicit_content(
        a.content.as_deref(),
        a.content_file.as_deref(),
        "the replacement IS the whole page",
    )?;

    // Within-page id uniqueness at the verb's own surface (see the fn's doc comment): the gate
    // cannot see a twice-carried id, and the --retire-atom exemption must not become one.
    refuse_duplicate_ids_within_page(&proposed)?;

    // Lock BEFORE reading the live page, held through the write + reindex (family contract).
    let _guard = write_gate::acquire(&write_gate::scope_root_for(&a.page))?;
    if let Some(base) = a.base_sha256.as_deref() {
        write_gate::check_base(&a.page, base)?;
    }
    // A VANISHED page is stale (the CAS says the same); anything else gets its real cause —
    // same shape as update-mem-topic's read.
    let text = if a.page.exists() {
        read_page_for_write(&a.page)?
    } else {
        anyhow::bail!(write_gate::STALE_MSG)
    };
    if text == proposed {
        anyhow::bail!("proposed content is byte-identical to the page — nothing to do");
    }

    // THE gate: one write_gated_with call on the complete proposed page (spec amendment ii —
    // not a batch). TRADEOFF on record (mirrors update-mem-topic's JFIOO9XO CURE-2): the verb's
    // CONTRACT is rewriting bodies under surviving ids, so allow_body_rewrite is unconditional —
    // a whole-page rewrite legitimately changes every atom's body. The DROP half still enforces:
    // an id on disk that vanishes refuses unless --retire-atom declared it.
    crate::pre_write::write_gated_with(
        &a.page,
        &proposed,
        &crate::pre_write::GatePolicy {
            retired_ids: a.retire_atom.iter().cloned().collect::<BTreeSet<String>>(),
            allow_body_rewrite: true,
        },
    )?;
    reindex_owning_scope(&a.page, a.hidden)?;
    // First stdout line is the page's identity line — the family's first-token contract (the
    // sha256 and any auto-fix disclosure go to STDERR via post_commit_disclosure, never ahead
    // of this line on stdout).
    println!("{}\treplaced (whole page)", crate::memory::rel(&a.page));
    Ok(())
}
