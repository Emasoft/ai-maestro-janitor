//! `merge-mem-topic` / `merge-mem-atom` (TRDD-VJL1YTCG Part B) — fold one wikimem page's whole
//! topic into another (tombstoning the source), or fold one atom into another on the SAME page.
//!
//! Both verbs are the CONSOLIDATION half of the `migrate` family: `migrate` relocates ONE atom
//! between two pages that both survive; these two verbs instead DELETE one side (a whole page, or
//! one atom) into the other, because the two elements turned out to be the same subject. They
//! reuse `migrate`'s own discipline throughout: sorted lock acquisition (deadlock-free), a
//! footnote-integrity pre-flight AND post-build proof (a malformed page must never be built on,
//! and a build must never leave a dangling footnote), and the strict UTF-8 read/atomic write pair.

use crate::md;
use crate::memory::{
    append_footnote_defs, atom_id_matches, atomic_write_page, bump_page_lmd,
    footer_section_line, footnote_integrity_violations, insert_atom_block_before,
    locate_atom_body_matching, next_footnote_label, normalize_keywords, page_description_phrases,
    read_page_for_write, reindex_owning_scope, rel, rewrite_footnote_labels, today_date,
    unique_phrases,
};
use crate::write_gate;
use anyhow::{Context, Result};
use std::collections::{BTreeMap, HashSet};
use std::path::PathBuf;

// ─────────────────────────── shared helpers (both verbs) ───────────────────────────

/// Every `^id [...]` marker's id in DOCUMENT order, deduped, naive line-scan (NOT fence-aware — a
/// false positive inside a code fence costs nothing: `locate_atom_body_matching`, called on each
/// candidate below, is the fence-aware authority that actually resolves an id to a real atom or to
/// nothing, so a candidate with no real match is simply skipped).
fn atom_marker_ids_in_order(text: &str) -> Vec<String> {
    let mut seen = HashSet::new();
    let mut ids = Vec::new();
    for line in text.lines() {
        let t = line.trim_start();
        let Some(rest) = t.strip_prefix('^') else { continue };
        let Some(bracket) = rest.find('[') else { continue };
        let id = rest[..bracket].trim();
        if !id.is_empty() && !id.chars().any(char::is_whitespace) && seen.insert(id.to_string()) {
            ids.push(id.to_string());
        }
    }
    ids
}

/// Set (or insert) a TOP-LEVEL frontmatter scalar `key: value` line — column-0 keys only, mirroring
/// `bump_page_lmd`'s own discipline, so a same-named nested `metadata:` sub-key is never touched.
/// A missing key is inserted right before the closing `---` (every page this runs on already
/// carries `description`/`ocd`/`lmd`/`publish-globally` at top level; the insert path only matters
/// for a hand-edited page missing one).
fn set_frontmatter_scalar(content: &str, key: &str, value: &str) -> String {
    let lines: Vec<&str> = content.lines().collect();
    if lines.first().map(|l| l.trim_end()) != Some("---") {
        return content.to_string();
    }
    let Some(close) = lines.iter().skip(1).position(|l| l.trim_end() == "---").map(|i| i + 1)
    else {
        return content.to_string();
    };
    let trailing_newline = content.ends_with('\n');
    let mut out: Vec<String> = lines.iter().map(|s| s.to_string()).collect();
    let key_at =
        (1..close).find(|&i| lines[i].strip_prefix(key).is_some_and(|rest| rest.starts_with(':')));
    match key_at {
        Some(i) => out[i] = format!("{key}: {value}"),
        None => out.insert(close, format!("{key}: {value}")),
    }
    let mut joined = out.join("\n");
    if trailing_newline {
        joined.push('\n');
    }
    joined
}

/// Split the inside of a `^id [ ... ]` marker on TOP-LEVEL commas — a comma inside a `"..."` quoted
/// value does not split. Narrow reimplementation scoped to ONE purpose (find/replace a single
/// key's value in an EXISTING marker line): the crate's own `split_top_level_commas` is
/// module-private to `memory.rs` and carries bracket-awareness this call site never needs.
fn split_top_level_commas_local(props: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0usize;
    let mut in_quotes = false;
    for (i, c) in props.char_indices() {
        match c {
            '"' => in_quotes = !in_quotes,
            ',' if !in_quotes => {
                out.push(&props[start..i]);
                start = i + 1;
            }
            _ => {}
        }
    }
    out.push(&props[start..]);
    out
}

/// Read one block-prop's raw value out of an existing `^id [...]` marker LINE (quotes stripped),
/// or `None` when the key is absent.
fn marker_field_value(marker: &str, key: &str) -> Option<String> {
    let open = marker.find('[')?;
    let close = marker.rfind(']')?;
    let inside = &marker[open + 1..close];
    for seg in split_top_level_commas_local(inside) {
        let seg_t = seg.trim();
        if let Some(rest) = seg_t.strip_prefix(key) {
            if let Some(v) = rest.trim_start().strip_prefix(':') {
                return Some(v.trim().trim_matches('"').to_string());
            }
        }
    }
    None
}

/// Set (or append) one block-prop `key: value` inside an existing `^id [...]` marker LINE,
/// preserving every other prop byte-for-byte (order, quoting, unrelated fields like `status:` /
/// `claude_mem_ref:` / `trdd:`) — the merge-atom contract only ever touches `keywords` and `lmd`.
///
/// Shared with `mem_split` (TRDD-3AKSYZRV): re-tuning a SPLIT original's recall surface must edit
/// the marker IN PLACE, never rebuild it through `build_atom_marker` — a rebuild resets `ocd` to
/// today and silently drops every prop the builder does not know about (`status:`,
/// `superseded-by:`, `claude_mem_ref:`).
pub(crate) fn set_marker_field(marker: &str, key: &str, value: &str) -> String {
    let Some(open) = marker.find('[') else { return marker.to_string() };
    let Some(close) = marker.rfind(']') else { return marker.to_string() };
    let prefix = &marker[..=open];
    let inside = &marker[open + 1..close];
    let suffix = &marker[close..];
    let mut segs: Vec<String> =
        split_top_level_commas_local(inside).iter().map(|s| s.trim().to_string()).collect();
    let mut found = false;
    for seg in segs.iter_mut() {
        if seg.strip_prefix(key).is_some_and(|rest| rest.trim_start().starts_with(':')) {
            *seg = format!("{key}: {value}");
            found = true;
            break;
        }
    }
    if !found {
        segs.push(format!("{key}: {value}"));
    }
    format!("{prefix}{}{suffix}", segs.join(", "))
}

// ─────────────────────────── `memgrep merge-mem-topic` ───────────────────────────

#[derive(clap::Parser)]
#[command(
    name = "merge-mem-topic",
    about = "fold one wikimem page's atoms+lessons into another page, tombstoning the source",
    after_help = "EXAMPLES:\n\
        \x20 # fold a duplicate/near-duplicate topic page into the page that should own it\n\
        \x20 memgrep merge-mem-topic --from .claude/project/memory/misc-notes.md --into .claude/project/memory/rotator.md\n\
        \x20 # preview the merge without writing anything\n\
        \x20 memgrep merge-mem-topic --from misc-notes.md --into rotator.md --dry-run\n\
        \x20 # guard against --into having changed since you last read it\n\
        \x20 memgrep merge-mem-topic --from misc-notes.md --into rotator.md --base-sha256 $(sha256sum rotator.md | cut -d' ' -f1)\n"
)]
struct MergeTopicArgs {
    /// Source page — every atom + its lessons move OUT of it; the page itself becomes a tombstone.
    #[arg(long = "from")]
    from: PathBuf,
    /// Destination page — receives every atom, its footnotes renumbered to labels free here.
    #[arg(long = "into")]
    into: PathBuf,
    /// Compare-and-swap staleness guard (TRDD-7YHT3FNK), checked against the `--into` page's
    /// current bytes. On mismatch nothing is written and the command fails with the canonical
    /// refusal.
    #[arg(long = "base-sha256")]
    base_sha256: Option<String>,
    /// Compute and print the merge without writing anything.
    #[arg(long = "dry-run")]
    dry_run: bool,
    /// Also descend into hidden files/dirs when reindexing (default off).
    #[arg(long = "hidden")]
    hidden: bool,
}

#[derive(Debug)]
struct MergeTopicResult {
    dest_text: String,
    tombstone_text: String,
    moved_atoms: usize,
}

/// The PURE core of `merge-mem-topic` (no IO / no locking) — computes both rewritten page texts or
/// fails. Mirrors `migrate_compute`'s contract: both pages footnote-clean before AND after.
fn merge_topic_compute(
    from_text: &str,
    into_text: &str,
    from_name_fallback: &str,
    into_name_fallback: &str,
    today: &str,
) -> Result<MergeTopicResult> {
    for (label, text) in [("--from", from_text), ("--into", into_text)] {
        let v = footnote_integrity_violations(text);
        if !v.is_empty() {
            anyhow::bail!(
                "{label} page has footnote-integrity problems — run `memgrep lint` + repair it \
                 FIRST (merging across a malformed page corrupts both): {}",
                v.join("; ")
            );
        }
    }

    let ids = atom_marker_ids_in_order(from_text);
    if ids.is_empty() {
        anyhow::bail!("--from page has no atoms to move — nothing to merge");
    }

    // Refuse on ANY atom-id collision with the destination — an id is cited elsewhere in the
    // corpus, so silently renaming one on the way in would break every existing citation.
    let mut collisions: Vec<String> = Vec::new();
    for id in &ids {
        if locate_atom_body_matching(into_text, &|s: &str| atom_id_matches(s, id)).is_some() {
            collisions.push(id.clone());
        }
    }
    if !collisions.is_empty() {
        anyhow::bail!(
            "atom id collision(s) already present on --into, nothing written: {}",
            collisions.join(", ")
        );
    }

    let from_lines: Vec<&str> = from_text.lines().collect();
    let ctx = md::build_context(from_text, from_lines.len());

    // Resolve each moving atom's exact (marker, body) via the fence-aware authority, and collect
    // every footnote label any of them REFERENCES (by 1-based line membership in its own range).
    let mut blocks: Vec<(String, String)> = Vec::new();
    let mut all_labels: Vec<String> = Vec::new();
    let mut seen_labels: HashSet<String> = HashSet::new();
    for id in &ids {
        let Some((marker_idx, last_idx)) =
            locate_atom_body_matching(from_text, &|s: &str| atom_id_matches(s, id))
        else {
            continue; // a `^id [` candidate that lived inside a fence — not a real atom
        };
        let block = from_lines[marker_idx..=last_idx].join("\n");
        let (marker, body) = block.split_once('\n').unwrap_or((block.as_str(), ""));
        blocks.push((marker.to_string(), body.to_string()));
        for r in &ctx.footnote_refs {
            if r.line >= marker_idx + 1 && r.line <= last_idx + 1 && seen_labels.insert(r.label.clone()) {
                all_labels.push(r.label.clone());
            }
        }
    }
    if blocks.is_empty() {
        anyhow::bail!("--from page's `^id [` candidates were all inside code fences — nothing to merge");
    }

    // Renumber every moved label to one free on --into (mirrors `migrate`'s contract 3). Every
    // label moves wholesale here — unlike `migrate`, the WHOLE source page is being retired, so
    // no other atom on --from is left behind to keep a def's OTHER user alive.
    let mut label_map: BTreeMap<String, String> = BTreeMap::new();
    let mut next = next_footnote_label(into_text);
    for lbl in &all_labels {
        label_map.insert(lbl.clone(), next.to_string());
        next += 1;
    }

    // Splice every atom into --into, before its footer boundary, in source order.
    let mut dest_text = into_text.to_string();
    for (marker, body) in &blocks {
        let rewritten_marker = rewrite_footnote_labels(marker, &label_map);
        let rewritten_body = rewrite_footnote_labels(body, &label_map);
        let boundary = footer_section_line(&dest_text);
        dest_text = insert_atom_block_before(&dest_text, &rewritten_marker, &rewritten_body, boundary);
    }

    // Carry every referenced def over, renumbered.
    let mut moved_defs: Vec<String> = Vec::new();
    for d in &ctx.footnote_defs {
        if !label_map.contains_key(&d.label) {
            continue;
        }
        let raw = from_lines[d.start - 1..=(d.end - 1).min(from_lines.len() - 1)].join("\n");
        moved_defs.push(rewrite_footnote_labels(&raw, &label_map));
    }
    if !moved_defs.is_empty() {
        dest_text = append_footnote_defs(&dest_text, &moved_defs);
    }

    // Post-build proof (contract 4): the destination must be footnote-clean now.
    let v = footnote_integrity_violations(&dest_text);
    if !v.is_empty() {
        anyhow::bail!(
            "aborting merge — it would leave the destination page with a dangling footnote \
             (nothing written): {}",
            v.join("; ")
        );
    }

    // Frontmatter union: description (phrase union), ocd (earlier), lmd (today),
    // publish-globally (true if either side was).
    let fm_into = md::parse_frontmatter(into_text);
    let fm_from = md::parse_frontmatter(from_text);

    let mut phrases = page_description_phrases(fm_into.get("description").map(String::as_str).unwrap_or(""));
    phrases.extend(page_description_phrases(fm_from.get("description").map(String::as_str).unwrap_or("")));
    let merged_desc = unique_phrases(&phrases).join(" / ");
    dest_text = set_frontmatter_scalar(
        &dest_text,
        "description",
        &format!("\"{}\"", merged_desc.replace('"', "'")),
    );

    let earlier_ocd = match (fm_into.get("ocd"), fm_from.get("ocd")) {
        (Some(a), Some(b)) => {
            if a <= b {
                a.clone()
            } else {
                b.clone()
            }
        }
        (Some(a), None) => a.clone(),
        (None, Some(b)) => b.clone(),
        (None, None) => today.to_string(),
    };
    dest_text = set_frontmatter_scalar(&dest_text, "ocd", &earlier_ocd);
    dest_text = set_frontmatter_scalar(&dest_text, "lmd", today);

    let is_true = |fm: &std::collections::HashMap<String, String>| {
        fm.get("publish-globally").map(|v| v.trim().eq_ignore_ascii_case("true")).unwrap_or(false)
    };
    if is_true(&fm_into) || is_true(&fm_from) {
        dest_text = set_frontmatter_scalar(&dest_text, "publish-globally", "true");
    }

    // Tombstone the source: keep its `name`/`ocd`, replace everything else — the atoms and their
    // defs just left, so keeping stale body content would only leave dangling references behind.
    let from_name = fm_from.get("name").cloned().unwrap_or_else(|| from_name_fallback.to_string());
    let into_name = fm_into.get("name").cloned().unwrap_or_else(|| into_name_fallback.to_string());
    let tomb_ocd = fm_from.get("ocd").cloned().unwrap_or_else(|| today.to_string());
    let tombstone_text = format!(
        "---\nname: {from_name}\ndescription: \"Merged into {into_name}\"\nocd: {tomb_ocd}\nlmd: {today}\n---\n\n\
         # {from_name}\n\nMerged into [[{into_name}]] on {today}.\n\n## Notes and lessons learned\n"
    );

    Ok(MergeTopicResult { dest_text, tombstone_text, moved_atoms: blocks.len() })
}

/// `memgrep merge-mem-topic --from A --into B [--dry-run] [--base-sha256 H] [--hidden]` — move
/// EVERY atom (+ its lessons) from A to B, then tombstone A. Locks both scopes in a fixed order
/// (sorted by lock path, exactly like `migrate`) so two concurrent merges naming the same pair of
/// scopes in opposite order can never deadlock. Writes B (the destination) before A (the
/// tombstone): a crash between the two atomic writes leaves a recoverable DUPLICATE, never a loss.
pub fn cmd_merge_topic_cli(args: &[String]) -> Result<()> {
    use clap::Parser as _;
    let a = MergeTopicArgs::parse_from(
        std::iter::once("memgrep merge-mem-topic".to_string()).chain(args.iter().cloned()),
    );
    if a.from == a.into {
        anyhow::bail!("--from and --into are the same page — nothing to merge");
    }

    // Deadlock-free two-scope lock, shared with migrate/split/reference — see `write_gate::acquire_two`.
    let (_g1, _g2) = write_gate::acquire_two(&a.from, &a.into)?;

    if let Some(base) = a.base_sha256.as_deref() {
        write_gate::check_base(&a.into, base)?;
    }
    let from_text = read_page_for_write(&a.from).context("--from page")?;
    let into_text = read_page_for_write(&a.into).context("--into page")?;

    let today = today_date();
    let from_fallback = a.from.file_stem().and_then(|s| s.to_str()).unwrap_or("from").to_string();
    let into_fallback = a.into.file_stem().and_then(|s| s.to_str()).unwrap_or("into").to_string();
    let r = merge_topic_compute(&from_text, &into_text, &from_fallback, &into_fallback, &today)?;

    if a.dry_run {
        println!(
            "[dry-run] would merge {} atom(s) from {} into {}, tombstoning {}",
            r.moved_atoms,
            rel(&a.from),
            rel(&a.into),
            rel(&a.from)
        );
        return Ok(());
    }

    atomic_write_page(&a.into, &r.dest_text)?;
    // The pair is NOT atomic. Each write is (temp+rename) and both texts were computed before
    // either landed, so only I/O can fail here — but if THIS one does, `--into` already holds the
    // atoms while `--from` still holds them too, and a plain retry is BLOCKED: the destination now
    // collides with itself, so `merge-mem-topic` refuses. Unlike `reference-mem-*`, which is
    // idempotent and self-heals on retry, this state needs a human, so say exactly what happened
    // and what to do rather than surfacing a bare io::Error with no hint that half the merge
    // already committed.
    atomic_write_page(&a.from, &r.tombstone_text).map_err(|e| {
        anyhow::anyhow!(
            "PARTIAL MERGE — `{into}` was written and now holds the atoms, but tombstoning \
             `{from}` FAILED: {e}\nBoth pages now carry the same atom id(s), so a retry will be \
             refused as a collision. Recover by hand: confirm `{into}` is correct, then remove the \
             merged atoms from `{from}` (or restore `{from}` from git). `memgrep lint` reports the \
             duplicate ids until you do.",
            into = a.into.display(),
            from = a.from.display(),
        )
    })?;
    reindex_owning_scope(&a.into, a.hidden)?;
    reindex_owning_scope(&a.from, a.hidden)?;
    println!(
        "merged {} atom(s) from {} into {} (source tombstoned)",
        r.moved_atoms,
        rel(&a.from),
        rel(&a.into)
    );
    Ok(())
}

// ─────────────────────────── `memgrep merge-mem-atom` ───────────────────────────

#[derive(clap::Parser)]
#[command(
    name = "merge-mem-atom",
    about = "fold one atom's body+keywords into another atom on the SAME page, keeping the destination id",
    after_help = "EXAMPLES:\n\
        \x20 # fold a near-duplicate atom into the one that should survive\n\
        \x20 memgrep merge-mem-atom --page rotator.md --atom ATOM-1111-AAAA --into ATOM-234P-U35Q\n\
        \x20 # preview the merge without writing anything\n\
        \x20 memgrep merge-mem-atom --page rotator.md --atom ATOM-1111-AAAA --into ATOM-234P-U35Q --dry-run\n\
        \x20 # guard against the page having changed since you last read it\n\
        \x20 memgrep merge-mem-atom --page rotator.md --atom ATOM-1111-AAAA --into ATOM-234P-U35Q --base-sha256 $(sha256sum rotator.md | cut -d' ' -f1)\n"
)]
struct MergeAtomArgs {
    /// The page carrying BOTH atoms.
    #[arg(long = "page")]
    page: PathBuf,
    /// The atom being folded away (its marker + body are removed after the fold).
    #[arg(long = "atom")]
    atom: String,
    /// The atom that survives — keeps its id, ocd, desc and type; gains the merged body/keywords.
    #[arg(long = "into")]
    into: String,
    /// Compare-and-swap staleness guard (TRDD-7YHT3FNK), checked against the page's current bytes.
    #[arg(long = "base-sha256")]
    base_sha256: Option<String>,
    /// Compute and print the merge without writing anything.
    #[arg(long = "dry-run")]
    dry_run: bool,
    /// Also descend into hidden files/dirs when reindexing (default off).
    #[arg(long = "hidden")]
    hidden: bool,
}

struct MergeAtomResult {
    new_text: String,
}

/// The PURE core of `merge-mem-atom` (no IO / no locking).
fn merge_atom_compute(text: &str, atom_query: &str, into_query: &str, today: &str) -> Result<MergeAtomResult> {
    let v = footnote_integrity_violations(text);
    if !v.is_empty() {
        anyhow::bail!(
            "page has footnote-integrity problems — run `memgrep lint` + repair it FIRST: {}",
            v.join("; ")
        );
    }

    let Some((src_marker_idx, src_last)) =
        locate_atom_body_matching(text, &|s: &str| atom_id_matches(s, atom_query))
    else {
        anyhow::bail!("no atom answering `{atom_query}` (--atom) on this page");
    };
    let Some((dst_marker_idx, dst_last)) =
        locate_atom_body_matching(text, &|s: &str| atom_id_matches(s, into_query))
    else {
        anyhow::bail!("no atom answering `{into_query}` (--into) on this page");
    };
    if src_marker_idx == dst_marker_idx {
        anyhow::bail!("--atom and --into resolve to the same atom — nothing to merge");
    }

    let lines: Vec<&str> = text.lines().collect();
    let src_marker = lines[src_marker_idx];
    let dst_marker = lines[dst_marker_idx];
    let src_body = lines[src_marker_idx + 1..=src_last].join("\n");
    let dst_body = lines[dst_marker_idx + 1..=dst_last].join("\n");

    // Union keywords: dedupe, order-preserving, via `normalize_keywords` (bridging the two
    // whitespace-separated stored lists through the same comma-parsed normaliser the CLI's own
    // `--keywords` flag uses, so a phrase with internal whitespace is handled identically).
    let dst_kw_raw = marker_field_value(dst_marker, "keywords").unwrap_or_default();
    let src_kw_raw = marker_field_value(src_marker, "keywords").unwrap_or_default();
    let combined_csv = format!(
        "{}, {}",
        dst_kw_raw.split_whitespace().collect::<Vec<_>>().join(", "),
        src_kw_raw.split_whitespace().collect::<Vec<_>>().join(", ")
    );
    let merged_keywords = unique_phrases(&normalize_keywords(&combined_csv));
    if merged_keywords.is_empty() {
        anyhow::bail!("neither atom carries any `keywords:` — refusing to write an unfindable merged atom");
    }

    // Keep the destination id and every other prop verbatim; only `keywords` and `lmd` change.
    let mut new_marker = set_marker_field(dst_marker, "keywords", &merged_keywords.join(" "));
    new_marker = set_marker_field(&new_marker, "lmd", today);

    // Concatenate bodies with a blank line. Same-page merge never needs footnote renumbering: a
    // page's footnote labels are already a single unique namespace, so a `[^N]` either side
    // carries keeps pointing at the SAME def it always did.
    let dst_body_trimmed = dst_body.trim_start_matches('\n');
    let src_body_trimmed = src_body.trim_start_matches('\n');
    let merged_body = match (dst_body_trimmed.is_empty(), src_body_trimmed.is_empty()) {
        (true, _) => src_body_trimmed.to_string(),
        (_, true) => dst_body_trimmed.to_string(),
        (false, false) => format!("{dst_body_trimmed}\n\n{src_body_trimmed}"),
    };
    let new_block = format!("{new_marker}\n\n{merged_body}");
    let new_block_lines: Vec<String> = new_block.lines().map(str::to_string).collect();

    let mut out_lines: Vec<String> = lines.iter().map(|s| s.to_string()).collect();
    // Absorb the atom's leading blank separator line (the standard insertion convention: a blank
    // line always precedes a marker) so removing an atom never leaves a widening blank-line gap.
    let src_del_start = if src_marker_idx > 0 && out_lines[src_marker_idx - 1].trim().is_empty() {
        src_marker_idx - 1
    } else {
        src_marker_idx
    };

    // Splice the FURTHER range first so the other range's indices, computed against the ORIGINAL
    // text, stay valid for its own splice call.
    if dst_marker_idx < src_marker_idx {
        out_lines.splice(src_del_start..=src_last, std::iter::empty());
        out_lines.splice(dst_marker_idx..=dst_last, new_block_lines);
    } else {
        out_lines.splice(dst_marker_idx..=dst_last, new_block_lines);
        out_lines.splice(src_del_start..=src_last, std::iter::empty());
    }

    let mut new_text = out_lines.join("\n");
    new_text.push('\n');

    let v = footnote_integrity_violations(&new_text);
    if !v.is_empty() {
        anyhow::bail!(
            "aborting merge — result would carry a dangling footnote (nothing written): {}",
            v.join("; ")
        );
    }

    let new_text = bump_page_lmd(&new_text, today);
    Ok(MergeAtomResult { new_text })
}

/// `memgrep merge-mem-atom --page P --atom SRC --into DST [--dry-run] [--base-sha256 H]
/// [--hidden]` — fold SRC's body+keywords into DST (same page), keep DST's id, remove SRC.
pub fn cmd_merge_atom_cli(args: &[String]) -> Result<()> {
    use clap::Parser as _;
    let a = MergeAtomArgs::parse_from(
        std::iter::once("memgrep merge-mem-atom".to_string()).chain(args.iter().cloned()),
    );

    let _guard = write_gate::acquire(&write_gate::scope_root_for(&a.page))?;
    if let Some(base) = a.base_sha256.as_deref() {
        write_gate::check_base(&a.page, base)?;
    }
    let text = read_page_for_write(&a.page)?;

    let today = today_date();
    let r = merge_atom_compute(&text, &a.atom, &a.into, &today)?;

    if a.dry_run {
        println!("[dry-run] would merge atom {} into {} on {}", a.atom, a.into, rel(&a.page));
        return Ok(());
    }

    atomic_write_page(&a.page, &r.new_text)?;
    reindex_owning_scope(&a.page, a.hidden)?;
    println!("merged atom {} into {} on {}", a.atom, a.into, rel(&a.page));
    Ok(())
}

// ─────────────────────────── tests ───────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    // `cmd_merge_topic_cli`/`cmd_merge_atom_cli` touch a PROCESS-WIDE env var
    // (`JANITOR_GLOBAL_STATE_DIR`, read by `write_gate`) while `cargo test` runs tests in parallel
    // threads by default — mirrors `memory::tests::EDIT_ENV_MUTEX` exactly (same reasoning: hold
    // this for the WHOLE body of any test that sets the env var).
    static MERGE_ENV_MUTEX: Mutex<()> = Mutex::new(());

    fn tmpdir(label: &str) -> PathBuf {
        use std::sync::atomic::{AtomicU64, Ordering};
        static COUNTER: AtomicU64 = AtomicU64::new(0);
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir()
            .join(format!("memgrep-mem-merge-test-{label}-{}-{n}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn merge_topic_refuses_on_atom_id_collision() {
        let from = "---\nname: a\ndescription: \"a\"\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n\
                    ^ATOM-AAAA-AAAA [keywords: foo]\n\nbody a\n\n## Notes and lessons learned\n";
        let into = "---\nname: b\ndescription: \"b\"\nocd: 2026-01-02\nlmd: 2026-01-02\n---\n\
                    ^ATOM-AAAA-AAAA [keywords: bar]\n\nbody b\n\n## Notes and lessons learned\n";
        let err = merge_topic_compute(from, into, "a", "b", "2026-02-01").unwrap_err();
        assert!(err.to_string().contains("ATOM-AAAA-AAAA"), "must name the colliding id: {err}");
    }

    #[test]
    fn merge_topic_renumbers_footnotes_and_stays_clean() {
        let from = "---\nname: a\ndescription: \"a\"\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n\
                    ^ATOM-AAAA-AAAA [keywords: foo]\n\nbody with a lesson[^1]\n\n\
                    ## Notes and lessons learned\n\n\
                    [^1]: [id: L1 status: valid keywords: foo] DO NOT x, BECAUSE y. DO z.\n";
        let into = "---\nname: b\ndescription: \"b\"\nocd: 2026-01-02\nlmd: 2026-01-02\n---\n\
                    ^ATOM-BBBB-BBBB [keywords: bar]\n\nbody with another[^1]\n\n\
                    ## Notes and lessons learned\n\n\
                    [^1]: [id: L2 status: valid keywords: bar] DO NOT p, BECAUSE q. DO r.\n";
        let r = merge_topic_compute(from, into, "a", "b", "2026-02-01").expect("merge succeeds");
        assert_eq!(footnote_integrity_violations(&r.dest_text), Vec::<String>::new());
        assert!(r.dest_text.contains("ATOM-AAAA-AAAA"), "moved atom must be present:\n{}", r.dest_text);
        // The moved atom's reference must have been renumbered to a label free on --into (`1` was
        // already taken there, so it must now read `[^2]`).
        assert!(r.dest_text.contains("[^2]"), "moved reference must be renumbered:\n{}", r.dest_text);
        assert_eq!(r.moved_atoms, 1);
    }

    #[test]
    fn merge_topic_frontmatter_union_takes_earlier_ocd_and_unions_publish_globally() {
        let from = "---\nname: a\ndescription: \"symptom one\"\nocd: 2026-01-05\nlmd: 2026-01-05\n\
                    publish-globally: true\n---\n\n^ATOM-AAAA-AAAA [keywords: foo]\n\nbody a\n\n\
                    ## Notes and lessons learned\n";
        let into = "---\nname: b\ndescription: \"symptom two\"\nocd: 2026-01-10\nlmd: 2026-01-10\n---\n\n\
                    ^ATOM-BBBB-BBBB [keywords: bar]\n\nbody b\n\n## Notes and lessons learned\n";
        let r = merge_topic_compute(from, into, "a", "b", "2026-02-01").expect("merge succeeds");
        let fm = md::parse_frontmatter(&r.dest_text);
        assert_eq!(fm.get("ocd").map(String::as_str), Some("2026-01-05"), "earlier ocd wins");
        assert_eq!(fm.get("lmd").map(String::as_str), Some("2026-02-01"), "lmd bumps to today");
        assert_eq!(fm.get("publish-globally").map(String::as_str), Some("true"), "true if either was");
        let desc = fm.get("description").cloned().unwrap_or_default();
        assert!(desc.contains("symptom one") && desc.contains("symptom two"), "description union: {desc}");
        // The tombstone keeps the SOURCE's own name + ocd, never the merged values.
        let tomb_fm = md::parse_frontmatter(&r.tombstone_text);
        assert_eq!(tomb_fm.get("name").map(String::as_str), Some("a"));
        assert_eq!(tomb_fm.get("ocd").map(String::as_str), Some("2026-01-05"));
        assert!(r.tombstone_text.contains("Merged into [[b]]"));
    }

    #[test]
    fn merge_topic_cli_writes_tombstone_and_destination_gains_the_atom() {
        let _env = MERGE_ENV_MUTEX.lock().unwrap();
        let scope = tmpdir("topic-cli");
        let memory_dir = scope.join("memory");
        std::fs::create_dir_all(&memory_dir).unwrap();
        let state_dir = tmpdir("topic-cli-state");
        unsafe {
            std::env::set_var("JANITOR_GLOBAL_STATE_DIR", &state_dir);
        }

        let from_path = memory_dir.join("from.md");
        let into_path = memory_dir.join("into.md");
        std::fs::write(
            &from_path,
            "---\nname: from-page\ndescription: \"a\"\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n\n\
             ^ATOM-CCCC-CCCC [keywords: alpha]\n\nsource body\n\n## Notes and lessons learned\n",
        )
        .unwrap();
        std::fs::write(
            &into_path,
            "---\nname: into-page\ndescription: \"b\"\nocd: 2026-01-02\nlmd: 2026-01-02\n---\n\n\
             ^ATOM-DDDD-DDDD [keywords: beta]\n\ndest body\n\n## Notes and lessons learned\n",
        )
        .unwrap();

        let args = vec![
            "--from".to_string(),
            from_path.to_str().unwrap().to_string(),
            "--into".to_string(),
            into_path.to_str().unwrap().to_string(),
        ];
        let res = cmd_merge_topic_cli(&args);
        // Read the on-disk result BEFORE cleanup removes the tempdirs.
        let from_after = res.is_ok().then(|| std::fs::read_to_string(&from_path).unwrap());
        let into_after = res.is_ok().then(|| std::fs::read_to_string(&into_path).unwrap());

        unsafe {
            std::env::remove_var("JANITOR_GLOBAL_STATE_DIR");
        }
        let _ = std::fs::remove_dir_all(&scope);
        let _ = std::fs::remove_dir_all(&state_dir);
        res.expect("merge-mem-topic succeeds");

        let into_after = into_after.unwrap();
        let from_after = from_after.unwrap();
        assert!(into_after.contains("ATOM-CCCC-CCCC"), "destination must gain the moved atom:\n{into_after}");
        assert!(into_after.contains("ATOM-DDDD-DDDD"), "destination must keep its own atom:\n{into_after}");
        assert!(into_after.contains("source body") && into_after.contains("dest body"));
        assert!(
            from_after.contains("Merged into [[into-page]]") && !from_after.contains("ATOM-CCCC-CCCC"),
            "source must be a tombstone with no atoms left:\n{from_after}"
        );
    }

    #[test]
    fn merge_atom_unions_keywords_and_concatenates_bodies_keeping_dest_id() {
        let text = "---\nname: p\ndescription: \"p\"\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n\n\
                    ^ATOM-1111-AAAA [desc: \"the source\", keywords: foo bar, ocd: 2026-01-01, lmd: 2026-01-01]\n\n\
                    source body\n\n\
                    ^ATOM-2222-BBBB [desc: \"the dest\", keywords: bar baz, ocd: 2026-01-02, lmd: 2026-01-02]\n\n\
                    dest body\n\n## Notes and lessons learned\n";
        let r = merge_atom_compute(text, "ATOM-1111-AAAA", "ATOM-2222-BBBB", "2026-02-01")
            .expect("merge succeeds");
        assert!(!r.new_text.contains("ATOM-1111-AAAA"), "source atom must be gone:\n{}", r.new_text);
        assert!(r.new_text.contains("ATOM-2222-BBBB"), "destination id must survive:\n{}", r.new_text);
        assert!(r.new_text.contains("dest body") && r.new_text.contains("source body"));
        assert!(r.new_text.contains("keywords: bar baz foo"), "union+dedupe keywords:\n{}", r.new_text);
        assert!(r.new_text.contains("ocd: 2026-01-02"), "ocd must stay the DEST's original:\n{}", r.new_text);
        assert!(r.new_text.contains("desc: \"the dest\""), "desc must stay the DEST's own:\n{}", r.new_text);
        // page-level lmd bump
        let fm = md::parse_frontmatter(&r.new_text);
        assert_eq!(fm.get("lmd").map(String::as_str), Some("2026-02-01"));
    }
}
