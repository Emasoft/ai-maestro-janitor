// `pub fn cmd_split_topic_cli`/`cmd_split_atom_cli` are the whole public surface of this module;
// main.rs's dispatch match wires them in separately (out of this file's ownership per the task
// split), so `cargo build` sees them as dead code until that wiring lands. Same allowance the
// placeholder this file replaces already carried.

//! `memgrep split-mem-topic` / `memgrep split-mem-atom` (TRDD-VJL1YTCG Part B).
//!
//! Two verbs that DIVIDE an over-grown page/atom rather than move a single fact between two
//! already-sized pages (that is `migrate`, in `memory.rs`). Both reuse the same primitives
//! `migrate`/`add-atom`/`new-page` are built from (footnote renumbering, atomic write, the
//! write-concurrency gate) — nothing here reimplements the write path.
//!
//! This module owns NOTHING else in the crate; every helper it needs from `memory.rs` is
//! `pub(crate)` (or fully `pub`) and imported below. Private helpers in `memory.rs`
//! (`atom_segment_end`, `resolve_atoms_from_text`, `Fence`/`fence_step`, …) are not reachable
//! from here by design, so the atom-boundary logic below is rebuilt on top of
//! `locate_atom_body_matching` (which already returns the exact `[marker, last body line]`
//! span) and `md::build_context`'s `footnote_refs`/`footnote_defs` (fence-aware already).

use crate::md;
use crate::memory::{
    append_footnote_defs, atom_id_matches, atomic_write_page, build_atom_marker, bump_page_lmd,
    check_desc, check_keyword_floor, duplicate_phrases, footer_section_line,
    footnote_integrity_violations, generate_unique_atom_id, insert_atom_block_before,
    locate_atom_body_matching, next_footnote_label, normalize_keywords,
    page_description_phrases, read_page_for_write, reindex_owning_scope, rel,
    rewrite_footnote_labels, today_date, unique_phrases,
};
use crate::write_gate;
use anyhow::Result;
use regex::Regex;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

// ─────────────────────────── shared small helpers ───────────────────────────

/// Mirrors `memory.rs`'s private `min_page_phrases()` byte-for-byte (same env var, same
/// default) — a page's `description:` is the recall surface for every fact it will ever hold,
/// so a freshly split-off page must clear the same bar `new-page`/`lint` hold every other page
/// to, or it silently ships under-findable.
fn min_page_phrases() -> usize {
    std::env::var("MEMGREP_MIN_PAGE_PHRASES")
        .ok()
        .and_then(|v| v.trim().parse::<usize>().ok())
        .unwrap_or(15)
}

/// Validate a NEW PAGE's `--description`, exactly like `new-page` does (distinct `/`-separated
/// phrases, no duplicates) — so a page this module scaffolds passes `memgrep lint` on arrival.
fn check_page_description(description: &str) -> Result<()> {
    if description.trim().is_empty() {
        anyhow::bail!("--description must not be empty — it is the PAGE recall surface `recall` ranks on");
    }
    let phrases = page_description_phrases(description);
    let min_p = min_page_phrases();
    if min_p > 0 && unique_phrases(&phrases).len() < min_p {
        anyhow::bail!(
            "--description carries only {} distinct `/`-separated phrase(s); {min_p} is the \
             minimum (MEMGREP_MIN_PAGE_PHRASES) — write alternative phrasings a future session \
             might arrive with, separated by ` / `.",
            unique_phrases(&phrases).len()
        );
    }
    let dupes = duplicate_phrases(&phrases);
    if !dupes.is_empty() {
        anyhow::bail!("--description repeats phrase(s): {dupes:?} — a repeat adds no new way to find the page");
    }
    Ok(())
}

/// Scaffold a brand-new page's text — same frontmatter shape `new-page` emits (component tier,
/// reference type), so the result is provably lint-clean on creation. Always carries the
/// mandatory `## Notes and lessons learned` heading.
fn new_page_skeleton(name: &str, description: &str, today: &str) -> String {
    let desc_flat = description.split_whitespace().collect::<Vec<_>>().join(" ").replace('"', "'");
    format!(
        "---\nname: {name}\ndescription: \"{desc_flat}\"\nocd: {today}\nlmd: {today}\n\
         metadata:\n  node_type: memory\n  type: reference\n  tier: component\n---\n\n\
         # {name}\n\n## Notes and lessons learned\n"
    )
}

/// Add a bidirectional `- [[target]]` link under a `## See also` section (creating one, right
/// before the page's footer, when absent). Idempotent — a link already present is left alone,
/// which is what makes calling this on BOTH ends of a split safe to do unconditionally.
/// `pub(crate)`: also called by `migrate-mem-atom`'s `--leave-link` in `memory.rs`.
pub(crate) fn ensure_see_also_link(text: &str, target_name: &str) -> String {
    let link_line = format!("- [[{target_name}]]");
    if text.lines().any(|l| l.trim() == link_line) {
        return text.to_string();
    }
    let lines: Vec<&str> = text.lines().collect();
    let ctx = md::build_context(text, lines.len());
    let mut see_also_idx: Option<usize> = None;
    for (i, l) in lines.iter().enumerate() {
        if *ctx.in_code.get(i).unwrap_or(&false) {
            continue;
        }
        let t = l.trim_start();
        if t.starts_with('#') && t.to_ascii_lowercase().contains("see also") {
            see_also_idx = Some(i);
            break;
        }
    }
    let mut out_lines: Vec<String> = lines.iter().map(|s| s.to_string()).collect();
    match see_also_idx {
        Some(hidx) => {
            let mut insert_at = hidx + 1;
            if insert_at < out_lines.len() && out_lines[insert_at].trim().is_empty() {
                insert_at += 1;
            }
            out_lines.insert(insert_at, link_line);
        }
        None => {
            let boundary = footer_section_line(text);
            let block = vec![
                String::new(),
                "## See also".to_string(),
                String::new(),
                link_line,
                String::new(),
            ];
            match boundary {
                Some(idx) => {
                    let tail = out_lines.split_off(idx);
                    out_lines.extend(block);
                    out_lines.extend(tail);
                }
                None => out_lines.extend(block),
            }
        }
    }
    let mut out = out_lines.join("\n");
    out.push('\n');
    out
}

/// The page's frontmatter `name:`, else its file stem — used as the wikilink target for the
/// See-also link law. `pub(crate)`: also called by `migrate-mem-atom`'s `--leave-link` in `memory.rs`.
pub(crate) fn page_link_name(path: &Path, text: &str) -> String {
    md::parse_frontmatter(text)
        .get("name")
        .cloned()
        .unwrap_or_else(|| path.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default())
}

/// The bare id payload `migrate`/`atom_id_matches` key on: strip a leading `^`.
fn atom_query(atom: &str) -> String {
    atom.strip_prefix('^').unwrap_or(atom).to_string()
}

// ─────────────────────────── `memgrep split-mem-topic` ───────────────────────────

#[derive(clap::Parser)]
#[command(
    name = "memgrep split-mem-topic",
    about = "move a set of atoms (with their [^N] lessons) off a page onto a brand-new page, wiring the See-also link both ways",
    after_help = "EXAMPLES:\n\
        \x20 # pull two atoms into their own new page\n\
        \x20 memgrep split-mem-topic --page .claude/project/memory/misc.md \\\n    \
        \x20   --atoms ATOM-1111-2222,ATOM-3333-4444 --into .claude/project/memory/rotator.md \\\n    \
        \x20   --name rotator --description \"how does oauth rotation work / token renew fails / rotator stuck\"\n\
        \x20 # preview the move without writing anything\n\
        \x20 memgrep split-mem-topic --page misc.md --atoms ATOM-1111-2222 --into new.md \\\n    \
        \x20   --name new --description \"...\" --dry-run\n"
)]
struct SplitTopicArgs {
    /// The page the atoms currently live on.
    #[arg(long = "page")]
    page: PathBuf,
    /// Comma-separated atom ids (`^name`, `ATOM-XXXX-XXXX`, or bare 8-char payload) to move.
    #[arg(long = "atoms")]
    atoms: String,
    /// The NEW page's path — refused if it already exists (never overwrites).
    #[arg(long = "into")]
    into: PathBuf,
    /// The new page's `name:` (its `[[name]]` wikilink slug).
    #[arg(long = "name")]
    name: String,
    /// The new page's `description:` — its recall surface.
    #[arg(long = "description")]
    description: String,
    /// Also descend into hidden files/dirs when reindexing (default off).
    #[arg(long = "hidden")]
    hidden: bool,
    /// Compare-and-swap staleness guard against the `--page` bytes as last read.
    #[arg(long = "base-sha256")]
    base_sha256: Option<String>,
    /// Print the plan and mutate nothing.
    #[arg(long = "dry-run")]
    dry_run: bool,
}

/// The pure result of a topic split: both rewritten page texts + counters for the report line.
struct SplitTopicResult {
    dest_text: String,
    source_text: String,
    moved_atoms: usize,
    moved_footnotes: usize,
    shared_footnotes: usize,
}

/// The PURE core of `split-mem-topic` (no IO) — computes both rewritten page texts or fails.
/// `new_page_base` is the destination's skeleton (frontmatter + `## Notes and lessons learned`,
/// no atoms yet); `atom_ids` names the atoms to lift, in any order (they are relocated in the
/// order they actually appear on `src_text`).
fn split_topic_compute(src_text: &str, new_page_base: &str, atom_ids: &[String]) -> Result<SplitTopicResult> {
    let v = footnote_integrity_violations(src_text);
    if !v.is_empty() {
        anyhow::bail!(
            "--page has footnote-integrity problems — run `memgrep lint` + repair it first: {}",
            v.join("; ")
        );
    }

    let mut ranges: Vec<(usize, usize, String)> = Vec::new();
    for id in atom_ids {
        let query = atom_query(id);
        let matcher = |cand: &str| atom_id_matches(cand, &query);
        let (m, b) = locate_atom_body_matching(src_text, &matcher)
            .ok_or_else(|| anyhow::anyhow!("no atom answering `{id}` on --page"))?;
        ranges.push((m, b, id.clone()));
    }
    ranges.sort_by_key(|(m, _, _)| *m);
    for w in ranges.windows(2) {
        if w[1].0 <= w[0].1 {
            anyhow::bail!("--atoms names overlapping or duplicate atoms (`{}` and `{}`)", w[0].2, w[1].2);
        }
    }

    let src_lines: Vec<&str> = src_text.lines().collect();
    let ctx = md::build_context(src_text, src_lines.len());

    let mut def_range: BTreeMap<String, (usize, usize)> = BTreeMap::new();
    for d in &ctx.footnote_defs {
        def_range.entry(d.label.clone()).or_insert((d.start, d.end));
    }

    let moving = |line1based: usize| {
        ranges.iter().any(|(m, b, _)| line1based >= m + 2 && line1based <= b + 1)
    };
    let mut mig_labels: BTreeSet<String> = BTreeSet::new();
    let mut other_labels: BTreeSet<String> = BTreeSet::new();
    for r in &ctx.footnote_refs {
        if moving(r.line) {
            mig_labels.insert(r.label.clone());
        } else {
            other_labels.insert(r.label.clone());
        }
    }

    let mut label_map: BTreeMap<String, String> = BTreeMap::new();
    let mut movable: Vec<String> = Vec::new();
    let mut next = next_footnote_label(new_page_base);
    for lbl in &mig_labels {
        if !def_range.contains_key(lbl) {
            continue; // a ref with no def — pre-flight above would already have refused
        }
        label_map.insert(lbl.clone(), next.to_string());
        next += 1;
        if !other_labels.contains(lbl) {
            movable.push(lbl.clone());
        }
    }

    let mut dest_text = new_page_base.to_string();
    for (m, b, _) in &ranges {
        let block = src_lines[*m..=*b].join("\n");
        let renamed = rewrite_footnote_labels(&block, &label_map);
        let (marker, body) = renamed.split_once('\n').unwrap_or((renamed.as_str(), ""));
        let boundary = footer_section_line(&dest_text);
        dest_text = insert_atom_block_before(&dest_text, marker, body, boundary);
    }
    let mut moved_defs: Vec<String> = Vec::new();
    for lbl in &mig_labels {
        let Some(&(s, e)) = def_range.get(lbl) else { continue };
        let raw_def = src_lines[s - 1..=(e - 1).min(src_lines.len() - 1)].join("\n");
        moved_defs.push(rewrite_footnote_labels(&raw_def, &label_map));
    }
    dest_text = append_footnote_defs(&dest_text, &moved_defs);

    let mut drop: BTreeSet<usize> = BTreeSet::new();
    for (m, b, _) in &ranges {
        for i in *m..=*b {
            drop.insert(i);
        }
    }
    for lbl in &movable {
        if let Some(&(s, e)) = def_range.get(lbl) {
            for i in (s - 1)..=(e - 1).min(src_lines.len() - 1) {
                drop.insert(i);
            }
        }
    }
    let kept: Vec<&str> = src_lines.iter().enumerate().filter(|(i, _)| !drop.contains(i)).map(|(_, l)| *l).collect();
    let mut source_text = kept.join("\n");
    source_text.push('\n');

    for (label, text) in [("destination", &dest_text), ("source", &source_text)] {
        let v = footnote_integrity_violations(text);
        if !v.is_empty() {
            anyhow::bail!(
                "aborting split — it would leave the {label} page with a dangling footnote (nothing written): {}",
                v.join("; ")
            );
        }
    }

    Ok(SplitTopicResult {
        dest_text,
        source_text,
        moved_atoms: ranges.len(),
        moved_footnotes: movable.len(),
        shared_footnotes: label_map.len() - movable.len(),
    })
}

pub fn cmd_split_topic_cli(args: &[String]) -> Result<()> {
    use clap::Parser as _;
    let a = SplitTopicArgs::parse_from(
        std::iter::once("memgrep split-mem-topic".to_string()).chain(args.iter().cloned()),
    );

    let atom_ids: Vec<String> = a.atoms.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
    if atom_ids.is_empty() {
        anyhow::bail!("--atoms must name at least one atom id");
    }
    if a.name.trim().is_empty() {
        anyhow::bail!("--name must not be empty");
    }
    if a.page == a.into {
        anyhow::bail!("--page and --into are the same path — nothing to split");
    }
    check_page_description(&a.description)?;

    // Deadlock-free two-scope lock, shared with migrate/merge/reference — see `write_gate::acquire_two`.
    let (_g1, _g2) = write_gate::acquire_two(&a.page, &a.into)?;
    if a.into.exists() {
        anyhow::bail!("{} already exists — split-mem-topic never overwrites an existing page", a.into.display());
    }
    if let Some(base) = a.base_sha256.as_deref() {
        write_gate::check_base(&a.page, base)?;
    }
    let src_text = read_page_for_write(&a.page)?;

    let today = today_date();
    let new_page_base = new_page_skeleton(a.name.trim(), &a.description, &today);
    let r = split_topic_compute(&src_text, &new_page_base, &atom_ids)?;

    let src_name = page_link_name(&a.page, &src_text);
    let dest_text = ensure_see_also_link(&r.dest_text, &src_name);
    let source_text = ensure_see_also_link(&r.source_text, a.name.trim());

    if a.dry_run {
        println!(
            "DRY RUN: would move {} atom(s) from {} to {} ({} footnote(s) moved, {} shared/copied)",
            r.moved_atoms,
            rel(&a.page),
            rel(&a.into),
            r.moved_footnotes,
            r.shared_footnotes
        );
        return Ok(());
    }

    let dest_text = bump_page_lmd(&dest_text, &today);
    let source_text = bump_page_lmd(&source_text, &today);

    if let Some(parent) = a.into.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    // NEW page first, then the source: a crash between the two atomic writes leaves a
    // recoverable duplicate (the atoms exist on both pages) rather than a loss.
    atomic_write_page(&a.into, &dest_text)?;
    // Ordering above makes a mid-pair failure a DUPLICATE rather than a LOSS. Say so at RUNTIME
    // too: the retry is blocked (the new page now exists, so `split-mem-topic` refuses to
    // overwrite it), so the operator must resolve it by hand and a bare io::Error would not tell
    // them the split half-committed.
    atomic_write_page(&a.page, &source_text).map_err(|e| {
        anyhow::anyhow!(
            "PARTIAL SPLIT — `{into}` was created and holds the moved atom(s), but rewriting the \
             source `{page}` FAILED: {e}\nThe atoms now exist on BOTH pages (a duplicate, not a \
             loss) and a retry will be refused because the destination already exists. Recover by \
             hand: confirm `{into}`, then remove the moved atoms from `{page}` (or delete `{into}` \
             and re-run). `memgrep lint` reports the duplicate ids until you do.",
            into = a.into.display(),
            page = a.page.display(),
        )
    })?;
    // BOTH scopes, then the first error — never `?` on the first call. Both pages are already
    // written by this point, so an early return would leave the second scope's index describing
    // a page that no longer exists that way, and `recall` would keep surfacing atoms that just
    // moved. Reindexing is idempotent, so attempting the second costs nothing when the first
    // failed.
    let reindexed = reindex_owning_scope(&a.into, a.hidden).and(reindex_owning_scope(&a.page, a.hidden));
    reindexed?;
    println!(
        "moved {} atom(s) from {} to {} ({} footnote(s) moved, {} shared/copied)",
        r.moved_atoms,
        rel(&a.page),
        rel(&a.into),
        r.moved_footnotes,
        r.shared_footnotes
    );
    Ok(())
}

// ─────────────────────────── `memgrep split-mem-atom` ───────────────────────────

#[derive(clap::Parser)]
#[command(
    name = "memgrep split-mem-atom",
    about = "split ONE over-long atom into two atoms on the same page, dividing its [^N] refs by which half's prose cites them",
    after_help = "EXAMPLES:\n\
        \x20 # split at a literal substring inside the atom's body\n\
        \x20 memgrep split-mem-atom --page .claude/project/memory/p.md --atom ATOM-1111-2222 \\\n    \
        \x20   --at \"the second half starts here\" \\\n    \
        \x20   --desc \"the second half's own triage sentence, 24+ chars long\" \\\n    \
        \x20   --keywords \"phrase one, phrase two, phrase three\"\n\
        \x20 # split at an absolute 1-based file line number instead\n\
        \x20 memgrep split-mem-atom --page p.md --atom ATOM-1111-2222 --at 42 --desc \"...\"\n"
)]
struct SplitAtomArgs {
    /// The page the atom lives on.
    #[arg(long = "page")]
    page: PathBuf,
    /// The atom to split: `^name`, its `ATOM-XXXX-XXXX`, or the bare 8-char payload.
    #[arg(long = "atom")]
    atom: String,
    /// Where to split: either a literal substring found in the atom's body (the second atom
    /// starts at the first body line containing it), or an absolute 1-based file line number.
    #[arg(long = "at")]
    at: String,
    /// `--desc` for the NEW second atom (required).
    #[arg(long = "desc")]
    desc: String,
    /// Keywords for the new second atom (comma-separated phrases). Defaults to the original
    /// atom's own keyword list when omitted.
    #[arg(long = "keywords")]
    keywords: Option<String>,
    /// `type` for the new second atom. Defaults to the original atom's `type` (if any).
    #[arg(long = "type")]
    atom_type: Option<String>,
    /// Re-tune the ORIGINAL (first) atom's `keywords:` — comma-separated phrases, same grammar as
    /// `--keywords`. Needed whenever the split is by TOPIC rather than by size (TRDD-3AKSYZRV):
    /// the original's keyword set was written to serve BOTH topics, so leaving it alone hands the
    /// first half a recall surface half of which belongs to the fact that just moved out — and
    /// `recall` ranks on keywords alone, so the first atom keeps answering queries about the
    /// second. Omit for a size-only decomposition, where both halves are still the same subject.
    #[arg(long = "orig-keywords")]
    orig_keywords: Option<String>,
    /// Re-tune the ORIGINAL (first) atom's `desc:` — same reasoning as `--orig-keywords`, for the
    /// one-line triage surface a `recall` listing shows instead of the body.
    #[arg(long = "orig-desc")]
    orig_desc: Option<String>,
    /// Footnote labels (comma list, e.g. `1,3`) whose lesson belongs to the NEW second atom.
    ///
    /// By DEFAULT every trailing `[^N]` anchor on the original atom's last body line moves to the
    /// FIRST half, because `add-lesson` appends its anchor to whatever the last body line happens
    /// to be — so without this the split would hand EVERY pre-existing lesson to the new atom
    /// regardless of which topic it corrects, and a lesson written with `--supersedes` would end
    /// up anchored to an atom whose id its own `supersedes:` prop does not name. Refs sitting
    /// mid-prose are never touched: they belong to the sentence they are in, and travel with it.
    #[arg(long = "lessons-to-new", value_delimiter = ',')]
    lessons_to_new: Vec<String>,
    /// Also descend into hidden files/dirs when reindexing (default off).
    #[arg(long = "hidden")]
    hidden: bool,
    /// Compare-and-swap staleness guard against the `--page` bytes as last read.
    #[arg(long = "base-sha256")]
    base_sha256: Option<String>,
    /// Print the plan and mutate nothing.
    #[arg(long = "dry-run")]
    dry_run: bool,
}

/// Pull a block-props value (`keywords:`/`type:`) out of a raw `^id [ … ]` marker line. Used
/// only to INHERIT a value the caller didn't override — a plain regex is enough because the
/// field order `build_atom_marker` emits never nests a `,`/`]` inside `keywords`/`type`.
fn extract_marker_value(marker_line: &str, key: &str) -> Option<String> {
    // `[` belongs in the leading class alongside `,`: the marker line is `^id [k: v, …]`, so the
    // FIRST property is preceded by the bracket and by nothing else. `desc` is optional
    // (`build_atom_marker` omits it when empty), which makes `keywords` the first property on
    // every desc-less atom — and `(?:^|,)` matched neither, so `keywords` came back None and the
    // split fell through to an empty list and a spurious `check_keyword_floor` refusal instead of
    // inheriting the source atom's recall surface.
    let re = Regex::new(&format!(r"(?:^|[,\[])\s*{key}:\s*([^,\]]+)")).ok()?;
    let caps = re.captures(marker_line)?;
    Some(caps[1].trim().trim_matches('"').to_string())
}

/// Everything the split needs to know about the TWO resulting atoms, so `split_atom_build` takes
/// one plan instead of a dozen positional strings nobody can read at the call site.
pub(crate) struct AtomSplitPlan<'a> {
    /// The fresh corpus-unique id for the second atom.
    pub new_id: &'a str,
    /// The second atom's recall surface.
    pub keywords: &'a [String],
    pub atom_type: Option<&'a str>,
    /// Inherited from the source atom — both halves came out of the same decision.
    pub trdd: Option<&'a str>,
    /// The second atom's one-line triage summary.
    pub desc: &'a str,
    /// Re-tuned recall surface for the ORIGINAL (first) atom; `None` leaves it as it was.
    pub orig_keywords: Option<&'a [String]>,
    /// Re-tuned triage summary for the ORIGINAL atom; `None` leaves it as it was.
    pub orig_desc: Option<&'a str>,
    /// Footnote labels whose lesson belongs to the NEW atom (see `--lessons-to-new`).
    pub lessons_to_new: &'a [String],
    pub today: &'a str,
}

/// Strip the run of TRAILING `[^N]` anchors off a body line, returning `(line-without-them,
/// labels-in-source-order)`.
///
/// Only a trailing run is touched, and that boundary is the whole correctness argument.
/// `add-lesson` appends its anchor to the END of the atom's last body line
/// (`memory.rs`, "Anchor the atom"), so a trailing anchor carries NO information about which
/// sentence — or which topic — it belongs to; it is there because it had nowhere else to go. A ref
/// sitting mid-prose is the opposite: an author put it beside the claim it annotates, so it must
/// travel with that prose and is never moved.
fn strip_trailing_anchors(line: &str) -> (String, Vec<String>) {
    let mut rest = line.trim_end().to_string();
    let mut labels: Vec<String> = Vec::new();
    while let Some(close) = rest.strip_suffix(']') {
        let Some(open) = close.rfind("[^") else { break };
        // `[^` must open the LAST bracket group and the label must be non-empty and bracket-free,
        // or this is ordinary prose that happens to end in `]`.
        let label = &close[open + 2..];
        if label.is_empty() || label.contains('[') || label.contains(']') {
            break;
        }
        labels.push(label.to_string());
        rest = close[..open].trim_end().to_string();
    }
    labels.reverse(); // popped right-to-left; restore source order
    (rest, labels)
}

/// The PURE core of `split-mem-atom` (no IO): given `plan`, splits the atom's body in place — the
/// first half keeps the ORIGINAL marker (re-tuned in place when the plan asks, never rebuilt), the
/// second half gets a brand-new marker. Nothing crosses a page boundary, so no footnote label is
/// ever renumbered; the post-build integrity check exists purely as a safety net.
fn split_atom_build(text: &str, atom: &str, at: &str, plan: &AtomSplitPlan<'_>) -> Result<(String, usize)> {
    let v = footnote_integrity_violations(text);
    if !v.is_empty() {
        anyhow::bail!(
            "--page has footnote-integrity problems — run `memgrep lint` + repair it first: {}",
            v.join("; ")
        );
    }

    let query = atom_query(atom);
    let matcher = |id: &str| atom_id_matches(id, &query);
    let (marker_idx, body_last) = locate_atom_body_matching(text, &matcher)
        .ok_or_else(|| anyhow::anyhow!("no atom answering `{atom}` on --page"))?;
    if body_last <= marker_idx {
        anyhow::bail!("atom `{atom}` has no body to split — nothing to divide");
    }

    let lines: Vec<&str> = text.lines().collect();
    let split_idx: usize = if let Ok(n) = at.trim().parse::<usize>() {
        n.checked_sub(1)
            .ok_or_else(|| anyhow::anyhow!("--at line number must be >= 1"))?
    } else {
        let found = lines
            .iter()
            .enumerate()
            .skip(marker_idx + 1)
            .take(body_last.saturating_sub(marker_idx))
            .find(|(_, line)| line.contains(at))
            .map(|(i, _)| i);
        found.ok_or_else(|| {
            anyhow::anyhow!(
                "--at `{at}` does not occur in atom `{atom}`'s body — pass a literal substring \
                 from it, or an absolute 1-based file line number"
            )
        })?
    };
    if split_idx < marker_idx + 2 || split_idx > body_last {
        anyhow::bail!(
            "--at splits atom `{atom}` at file line {}, which would leave one half empty — it \
             must land strictly between the atom's first and last body line (file lines {}-{})",
            split_idx + 1,
            marker_idx + 2,
            body_last + 1
        );
    }

    // Re-tune the ORIGINAL marker IN PLACE. Never through `build_atom_marker`: that rebuilds from
    // scratch, which resets `ocd` to today and drops every prop the builder does not know about
    // (`status:`, `superseded-by:`, `claude_mem_ref:`). `lmd` bumps unconditionally — the original
    // atom's BODY just lost half its content, so a stale `lmd` would assert it had not changed.
    let mut original_marker = lines[marker_idx].to_string();
    if let Some(kw) = plan.orig_keywords {
        original_marker = crate::mem_merge::set_marker_field(&original_marker, "keywords", &kw.join(" "));
    }
    if let Some(d) = plan.orig_desc {
        original_marker =
            crate::mem_merge::set_marker_field(&original_marker, "desc", &format!("\"{}\"", d.replace('"', "'")));
    }
    original_marker = crate::mem_merge::set_marker_field(&original_marker, "lmd", plan.today);

    let mut first_body: Vec<String> =
        lines[marker_idx + 1..split_idx].iter().map(|s| s.to_string()).collect();
    let mut second_body: Vec<String> = lines[split_idx..=body_last].iter().map(|s| s.to_string()).collect();

    // Re-assign the lesson anchors that `add-lesson` parked on the atom's last body line — which
    // is now the LAST line of the second half, so leaving them alone silently hands every existing
    // lesson to the new atom. Default: they follow the id they were authored against (the first
    // half keeps it), and `--lessons-to-new` names the ones that genuinely belong to the new topic.
    let last_second = second_body.len() - 1;
    let (stripped, anchors) = strip_trailing_anchors(&second_body[last_second]);
    if !anchors.is_empty() {
        let (to_new, to_orig): (Vec<String>, Vec<String>) = anchors
            .into_iter()
            .partition(|l| plan.lessons_to_new.iter().any(|w| w.trim() == l));
        let render = |ls: &[String]| ls.iter().map(|l| format!(" [^{l}]")).collect::<String>();
        second_body[last_second] = format!("{stripped}{}", render(&to_new));
        // A line that was ONLY anchors leaves an empty tail line behind; drop it rather than ship
        // a trailing blank inside the atom body — unless it is the half's ONLY line, which would
        // make the new atom empty and is a bad split the caller should hear about.
        if second_body[last_second].trim().is_empty() {
            if second_body.len() == 1 {
                anyhow::bail!(
                    "--at would give the new atom a body of nothing but lesson anchors — pick a \
                     split point with real prose on both sides"
                );
            }
            second_body.pop();
        }
        if !to_orig.is_empty() {
            // The last NON-BLANK line, not merely the last: a paragraph break at the split point
            // makes the first half end in a blank line, and appending there produced an orphan
            // ` [^1]` floating on its own line under an empty paragraph (measured end-to-end).
            let last_first = first_body
                .iter()
                .rposition(|l| !l.trim().is_empty())
                .ok_or_else(|| {
                    anyhow::anyhow!(
                        "--at would leave the original atom with no prose to carry its lesson \
                         anchors — pick a split point with real prose on both sides"
                    )
                })?;
            first_body[last_first] =
                format!("{}{}", first_body[last_first].trim_end(), render(&to_orig));
        }
    }

    let new_marker = build_atom_marker(
        plan.new_id,
        plan.keywords,
        Some(plan.desc),
        plan.atom_type,
        plan.trdd,
        plan.today,
    );

    let mut out_lines: Vec<String> = lines.iter().map(|s| s.to_string()).collect();
    let tail = out_lines.split_off(body_last + 1);
    out_lines.truncate(marker_idx);
    out_lines.push(original_marker);
    out_lines.extend(first_body);
    out_lines.push(String::new());
    out_lines.push(new_marker);
    out_lines.push(String::new());
    out_lines.extend(second_body);
    out_lines.extend(tail);

    let mut out = out_lines.join("\n");
    out.push('\n');

    let v = footnote_integrity_violations(&out);
    if !v.is_empty() {
        anyhow::bail!(
            "aborting split — it would leave the page with a dangling footnote (nothing written): {}",
            v.join("; ")
        );
    }
    Ok((out, split_idx))
}

pub fn cmd_split_atom_cli(args: &[String]) -> Result<()> {
    use clap::Parser as _;
    let a = SplitAtomArgs::parse_from(
        std::iter::once("memgrep split-mem-atom".to_string()).chain(args.iter().cloned()),
    );
    check_desc(Some(&a.desc), "atom")?;

    let _guard = write_gate::acquire(&write_gate::scope_root_for(&a.page))?;
    if let Some(base) = a.base_sha256.as_deref() {
        write_gate::check_base(&a.page, base)?;
    }
    let text = read_page_for_write(&a.page)?;

    let query = atom_query(&a.atom);
    let matcher = |id: &str| atom_id_matches(id, &query);
    let (marker_idx, _) = locate_atom_body_matching(&text, &matcher)
        .ok_or_else(|| anyhow::anyhow!("no atom answering `{}` on --page", a.atom))?;
    let original_marker = text.lines().nth(marker_idx).unwrap_or("").to_string();

    let keywords: Vec<String> = match a.keywords.as_deref() {
        Some(raw) => normalize_keywords(raw),
        None => extract_marker_value(&original_marker, "keywords")
            .map(|v| v.split_whitespace().map(str::to_string).collect())
            .unwrap_or_default(),
    };
    check_keyword_floor(&keywords, "atom")?;
    let atom_type = a.atom_type.clone().or_else(|| extract_marker_value(&original_marker, "type"));
    // The halves of a split fact came out of the SAME decision, so the new atom inherits the
    // source's TRDD backlink. Dropping it here would silently un-source half the corpus every time
    // a chore decomposed an oversized atom — the exact provenance the backlink exists to keep.
    let trdd = extract_marker_value(&original_marker, "trdd");

    // The ORIGINAL half's re-tuned surfaces are held to the SAME floors as the new half's — a
    // topic split that leaves the first atom with two keyphrases has traded one unfindable atom
    // for two.
    let orig_keywords: Option<Vec<String>> = match a.orig_keywords.as_deref() {
        Some(raw) => {
            let kw = normalize_keywords(raw);
            check_keyword_floor(&kw, "atom")?;
            Some(kw)
        }
        None => None,
    };
    if let Some(d) = a.orig_desc.as_deref() {
        check_desc(Some(d), "atom")?;
    }

    let scope_root = write_gate::scope_root_for(&a.page);
    let new_id = generate_unique_atom_id(&[scope_root], a.hidden)?;
    let today = today_date();

    let plan = AtomSplitPlan {
        new_id: &new_id,
        keywords: &keywords,
        atom_type: atom_type.as_deref(),
        trdd: trdd.as_deref(),
        desc: &a.desc,
        orig_keywords: orig_keywords.as_deref(),
        orig_desc: a.orig_desc.as_deref(),
        lessons_to_new: &a.lessons_to_new,
        today: &today,
    };
    let (out, split_idx) = split_atom_build(&text, &a.atom, &a.at, &plan)?;

    if a.dry_run {
        println!(
            "DRY RUN: would split `{}` at file line {} into `{}` (kept) and `{new_id}` (new) on {}",
            a.atom,
            split_idx + 1,
            a.atom,
            rel(&a.page)
        );
        return Ok(());
    }

    let out = bump_page_lmd(&out, &today);
    atomic_write_page(&a.page, &out)?;
    reindex_owning_scope(&a.page, a.hidden)?;
    println!("split `{}` into `{}` (kept) and `{new_id}` (new) on {}", a.atom, a.atom, rel(&a.page));
    Ok(())
}

// ─────────────────────────── tests ───────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::Mutex;

    // `JANITOR_GLOBAL_STATE_DIR` (read by `write_gate`) is process-wide, and `cargo test` runs
    // tests in parallel threads by default — mirrors `memory.rs`'s own `EDIT_ENV_MUTEX` pattern
    // so these tests never race each other or touch the real `~/.claude/...` lock files.
    static ENV_MUTEX: Mutex<()> = Mutex::new(());
    static COUNTER: AtomicU64 = AtomicU64::new(0);

    /// A two-line-bodied atom carrying every prop class a re-tune must not disturb: an `ocd` older
    /// than "today", a `type`, and a `trdd` backlink.
    const PAGE: &str = "---\nname: p\n---\n\n# p\n\n^ATOM-5555-5555 [desc: \"the original two-topic summary\", keywords: alpha beta, type: reference, trdd: TRDD-M7BZ4X1Q, ocd: 2026-08-01, lmd: 2026-08-01]\nfirst half line one\nSPLIT-HERE second half line one\n\n## Notes and lessons learned\n";

    /// The common `AtomSplitPlan` for these tests — only the fields under test vary.
    fn plan<'a>(
        keywords: &'a [String],
        orig_keywords: Option<&'a [String]>,
        orig_desc: Option<&'a str>,
        lessons_to_new: &'a [String],
    ) -> AtomSplitPlan<'a> {
        AtomSplitPlan {
            new_id: "ATOM-6666-6666",
            keywords,
            atom_type: Some("reference"),
            trdd: Some("TRDD-M7BZ4X1Q"),
            desc: "the second half's own triage sentence right here",
            orig_keywords,
            orig_desc,
            lessons_to_new,
            today: "2026-08-28",
        }
    }

    fn tmp_scope(label: &str) -> PathBuf {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!("memgrep-split-test-{label}-{}-{n}", std::process::id()));
        let memory_dir = dir.join("memory");
        std::fs::create_dir_all(&memory_dir).unwrap();
        memory_dir
    }

    fn write_page(dir: &Path, name: &str, content: &str) -> PathBuf {
        let p = dir.join(name);
        std::fs::write(&p, content).unwrap();
        p
    }

    fn with_state_dir<F: FnOnce()>(state_dir: &Path, f: F) {
        unsafe {
            std::env::set_var("JANITOR_GLOBAL_STATE_DIR", state_dir);
        }
        f();
        unsafe {
            std::env::remove_var("JANITOR_GLOBAL_STATE_DIR");
        }
    }

    #[test]
    fn marker_values_are_extracted_from_the_first_property_too() {
        // `desc` is optional, so `keywords` is the FIRST property on a desc-less atom — preceded
        // by `[`, not by a comma. The leading class must admit the bracket or split-mem-atom
        // silently fails to inherit the source atom's recall surface and then refuses on the
        // keyword floor.
        let bare = "^ATOM-1111-1111 [keywords: alpha beta, ocd: 2026-08-01, lmd: 2026-08-01]";
        assert_eq!(extract_marker_value(bare, "keywords").as_deref(), Some("alpha beta"));
        let full = "^ATOM-2222-2222 [desc: \"a summary\", keywords: gamma, type: reference, \
                    trdd: TRDD-M7BZ4X1Q, ocd: 2026-08-01, lmd: 2026-08-01]";
        assert_eq!(extract_marker_value(full, "keywords").as_deref(), Some("gamma"));
        assert_eq!(extract_marker_value(full, "type").as_deref(), Some("reference"));
        assert_eq!(extract_marker_value(full, "trdd").as_deref(), Some("TRDD-M7BZ4X1Q"));
        assert_eq!(extract_marker_value(bare, "type"), None, "an absent key stays None");
    }

    #[test]
    fn help_examples_are_present_for_both_verbs() {
        use clap::CommandFactory;
        for help in [SplitTopicArgs::command().render_long_help().to_string(), SplitAtomArgs::command().render_long_help().to_string()] {
            assert!(help.contains("EXAMPLES:"), "verb help must carry an EXAMPLES section:\n{help}");
        }
    }

    #[test]
    fn split_topic_moves_atom_and_its_lesson_leaving_both_pages_integrity_clean() {
        let _env = ENV_MUTEX.lock().unwrap_or_else(|e| e.into_inner());
        let scope = tmp_scope("topic-basic");
        let state_dir = scope.join("state");
        let src_body = "---\nname: misc\ndescription: \"a grab bag of stuff / misc notes\"\n---\n\
             ^ATOM-1111-1111 [desc: \"unrelated atom stays put\", keywords: unrelated_stuff, ocd: 2026-08-01, lmd: 2026-08-01]\n\
             unrelated body text\n\n\
             ^ATOM-2222-2222 [desc: \"the atom being moved, with a lesson\", keywords: moving_fact, ocd: 2026-08-01, lmd: 2026-08-01]\n\
             the moving atom's body, cites [^1]\n\n\
             ## Notes and lessons learned\n\n\
             [^1]: [id:L1 status:active] DO NOT skip this, BECAUSE it breaks things. DO the right thing instead.\n";
        let src = write_page(&scope, "misc.md", src_body);
        let into = scope.join("split-off.md");

        let args = vec![
            "--page".to_string(), src.to_str().unwrap().to_string(),
            "--atoms".to_string(), "ATOM-2222-2222".to_string(),
            "--into".to_string(), into.to_str().unwrap().to_string(),
            "--name".to_string(), "split-off".to_string(),
            "--description".to_string(),
            "why did the moving atom move / where did the lesson go / split off topic reasons / recall symptom one / recall symptom two / recall symptom three / recall symptom four / recall symptom five / recall symptom six / recall symptom seven / recall symptom eight / recall symptom nine / recall symptom ten / recall symptom eleven / recall symptom twelve".to_string(),
        ];

        let mut res = None;
        with_state_dir(&state_dir, || res = Some(cmd_split_topic_cli(&args)));
        let res = res.unwrap();
        // Read the written pages BEFORE tearing down `scope` — it holds both `src` and `into`.
        let dest = std::fs::read_to_string(&into);
        let source = std::fs::read_to_string(&src);
        let _ = std::fs::remove_dir_all(&scope);
        let _ = std::fs::remove_dir_all(&state_dir);

        assert!(res.is_ok(), "split-mem-topic must succeed: {res:?}");
        let dest = dest.unwrap();
        let source = source.unwrap();
        assert!(dest.contains("ATOM-2222-2222"), "moved atom lands on the new page:\n{dest}");
        assert!(dest.contains("DO NOT skip this"), "the atom's lesson travels WITH it:\n{dest}");
        assert!(!source.contains("ATOM-2222-2222"), "moved atom leaves the source page:\n{source}");
        assert!(!source.contains("DO NOT skip this"), "the orphaned lesson leaves the source page too:\n{source}");
        assert!(source.contains("ATOM-1111-1111"), "the untouched atom stays on the source page:\n{source}");
        assert!(footnote_integrity_violations(&dest).is_empty(), "dest page must be footnote-clean:\n{dest}");
        assert!(footnote_integrity_violations(&source).is_empty(), "source page must be footnote-clean:\n{source}");
    }

    #[test]
    fn split_topic_refuses_when_the_destination_page_already_exists() {
        let _env = ENV_MUTEX.lock().unwrap_or_else(|e| e.into_inner());
        let scope = tmp_scope("topic-exists");
        let state_dir = scope.join("state");
        let src = write_page(
            &scope,
            "misc.md",
            "---\nname: misc\ndescription: \"d\"\n---\n^ATOM-3333-3333 [keywords: k, ocd: 2026-08-01, lmd: 2026-08-01]\nbody\n",
        );
        let into = write_page(&scope, "already-there.md", "---\nname: already-there\ndescription: \"d\"\n---\n# already-there\n");

        let args = vec![
            "--page".to_string(), src.to_str().unwrap().to_string(),
            "--atoms".to_string(), "ATOM-3333-3333".to_string(),
            "--into".to_string(), into.to_str().unwrap().to_string(),
            "--name".to_string(), "already-there".to_string(),
            "--description".to_string(), "one / two / three / four / five / six / seven / eight / nine / ten / eleven / twelve / thirteen / fourteen / fifteen".to_string(),
        ];

        let mut res = None;
        with_state_dir(&state_dir, || res = Some(cmd_split_topic_cli(&args)));
        let res = res.unwrap();
        let _ = std::fs::remove_dir_all(&scope);
        let _ = std::fs::remove_dir_all(&state_dir);

        let err = res.expect_err("must refuse an existing --into target");
        assert!(err.to_string().contains("already exists"), "wrong refusal: {err}");
    }

    #[test]
    fn split_topic_wires_the_see_also_link_both_ways() {
        let _env = ENV_MUTEX.lock().unwrap_or_else(|e| e.into_inner());
        let scope = tmp_scope("topic-links");
        let state_dir = scope.join("state");
        let src = write_page(
            &scope,
            "hub.md",
            "---\nname: hub\ndescription: \"a hub page / lots of topics\"\n---\n\
             ^ATOM-4444-4444 [desc: \"this one is leaving\", keywords: leaving_topic, ocd: 2026-08-01, lmd: 2026-08-01]\nbody\n\n\
             ## Notes and lessons learned\n",
        );
        let into = scope.join("leaf.md");
        let args = vec![
            "--page".to_string(), src.to_str().unwrap().to_string(),
            "--atoms".to_string(), "ATOM-4444-4444".to_string(),
            "--into".to_string(), into.to_str().unwrap().to_string(),
            "--name".to_string(), "leaf".to_string(),
            "--description".to_string(), "one / two / three / four / five / six / seven / eight / nine / ten / eleven / twelve / thirteen / fourteen / fifteen".to_string(),
        ];

        let mut res = None;
        with_state_dir(&state_dir, || res = Some(cmd_split_topic_cli(&args)));
        let res = res.unwrap();
        // Read the written pages BEFORE tearing down `scope` — it holds both `src` and `into`.
        let dest = std::fs::read_to_string(&into);
        let source = std::fs::read_to_string(&src);
        let _ = std::fs::remove_dir_all(&scope);
        let _ = std::fs::remove_dir_all(&state_dir);

        assert!(res.is_ok(), "split must succeed: {res:?}");
        let dest = dest.unwrap();
        let source = source.unwrap();
        assert!(dest.contains("[[hub]]"), "new page must link back to the source:\n{dest}");
        assert!(source.contains("[[leaf]]"), "source page must link forward to the new page:\n{source}");
    }

    #[test]
    fn split_atom_produces_a_unique_second_id_and_stays_footnote_clean() {
        let _env = ENV_MUTEX.lock().unwrap_or_else(|e| e.into_inner());
        let scope = tmp_scope("atom-split");
        let state_dir = scope.join("state");
        let src = write_page(
            &scope,
            "p.md",
            "---\nname: p\ndescription: \"d\"\n---\n\
             ^ATOM-5555-5555 [desc: \"an atom that grew too long\", keywords: first_half second_half, ocd: 2026-08-01, lmd: 2026-08-01]\n\
             first half line one\nfirst half line two\nSPLIT-HERE second half line one\nsecond half line two\n\n\
             ## Notes and lessons learned\n",
        );

        let args = vec![
            "--page".to_string(), src.to_str().unwrap().to_string(),
            "--atom".to_string(), "ATOM-5555-5555".to_string(),
            "--at".to_string(), "SPLIT-HERE".to_string(),
            "--desc".to_string(), "the second half's own triage sentence right here".to_string(),
            "--keywords".to_string(), "second_half_only, a_new_phrase, phrase_three, phrase_four, phrase_five, phrase_six, phrase_seven, phrase_eight, phrase_nine, phrase_ten".to_string(),
        ];

        let mut res = None;
        with_state_dir(&state_dir, || res = Some(cmd_split_atom_cli(&args)));
        let res = res.unwrap();
        let text = std::fs::read_to_string(&src).unwrap();
        let _ = std::fs::remove_dir_all(&scope);
        let _ = std::fs::remove_dir_all(&state_dir);

        assert!(res.is_ok(), "split-mem-atom must succeed: {res:?}");
        assert!(text.contains("ATOM-5555-5555"), "the original id is kept on the first half:\n{text}");
        assert!(text.contains("first half line one"), "first half prose stays under the original marker:\n{text}");
        assert!(text.contains("SPLIT-HERE second half line one"), "second half prose survives:\n{text}");
        let ids: Vec<&str> = text
            .lines()
            .filter_map(|l| l.trim_start().strip_prefix('^'))
            .filter_map(|l| l.split_whitespace().next())
            .collect();
        assert_eq!(ids.len(), 2, "the page now carries exactly two atom markers:\n{text}");
        assert_ne!(ids[0], ids[1], "the second atom got a genuinely NEW id, not a copy: {ids:?}");
        assert!(footnote_integrity_violations(&text).is_empty(), "page must stay footnote-clean:\n{text}");
    }

    /// A split inherits the source atom's TRDD backlink (TRDD-YMDE95LT).
    ///
    /// Both halves came out of the SAME decision, so dropping it on the new half would silently
    /// un-source half the corpus every time a chore decomposed an oversized atom — the provenance
    /// this field exists to keep, lost by the maintenance that was meant to improve the page.
    #[test]
    fn split_inherits_the_source_atoms_trdd_backlink() {
        let kw = vec!["alpha".to_string(), "beta".to_string()];
        let (out, _) = split_atom_build(PAGE, "ATOM-5555-5555", "SPLIT-HERE", &plan(&kw, None, None, &[]))
            .expect("split must succeed");
        assert!(
            out.contains("^ATOM-6666-6666 [") && out.matches("trdd: TRDD-M7BZ4X1Q").count() == 2,
            "both halves cite the decision they came from:\n{out}"
        );
    }

    /// A topic split RE-TUNES the original atom's recall surface in place (TRDD-3AKSYZRV).
    ///
    /// In place, not rebuilt: the original marker's `ocd` and its unrelated props (`type`, `trdd`,
    /// and anything a future field adds) must survive byte-for-byte, or "improve the keywords"
    /// quietly becomes "reset the atom's history".
    #[test]
    fn orig_keywords_and_desc_are_retuned_without_rebuilding_the_marker() {
        let kw = vec!["gamma".to_string(), "delta".to_string()];
        let orig_kw = vec!["alpha".to_string(), "beta".to_string()];
        let (out, _) = split_atom_build(
            PAGE,
            "ATOM-5555-5555",
            "SPLIT-HERE",
            &plan(&kw, Some(&orig_kw), Some("the first half's own triage sentence"), &[]),
        )
        .expect("split must succeed");
        let orig_line = out
            .lines()
            .find(|l| l.starts_with("^ATOM-5555-5555 "))
            .expect("original marker survives");
        assert!(orig_line.contains("keywords: alpha beta"), "keywords re-tuned: {orig_line}");
        assert!(
            orig_line.contains("desc: \"the first half's own triage sentence\""),
            "desc re-tuned: {orig_line}"
        );
        assert!(orig_line.contains("ocd: 2026-08-01"), "ocd is NOT reset by a re-tune: {orig_line}");
        assert!(orig_line.contains("lmd: 2026-08-28"), "lmd bumps — the body changed: {orig_line}");
        assert!(orig_line.contains("type: reference"), "unrelated props preserved: {orig_line}");
        assert!(orig_line.contains("trdd: TRDD-M7BZ4X1Q"), "provenance preserved: {orig_line}");
    }

    /// `add-lesson` parks its `[^N]` on the atom's LAST body line, so a naive split hands EVERY
    /// pre-existing lesson to the new half. Default: they stay with the id they were authored
    /// against; `--lessons-to-new` moves the ones that belong to the new topic (TRDD-3AKSYZRV).
    #[test]
    fn trailing_lesson_anchors_follow_the_original_unless_assigned_to_the_new_atom() {
        let kw = vec!["gamma".to_string(), "delta".to_string()];
        let text = PAGE
            .replace("SPLIT-HERE second half line one", "SPLIT-HERE second half line one [^1] [^2]")
            .replace(
                "## Notes and lessons learned\n",
                "## Notes and lessons learned\n[^1]: DO NOT do X, BECAUSE y. DO z instead.\n[^2]: DO NOT do P, BECAUSE q. DO r instead.\n",
            );

        let (out, _) = split_atom_build(&text, "ATOM-5555-5555", "SPLIT-HERE", &plan(&kw, None, None, &[]))
            .expect("split must succeed");
        let first_half = out.split("^ATOM-6666-6666").next().unwrap();
        assert!(
            first_half.contains("first half line one [^1] [^2]"),
            "both anchors follow the kept id by default:\n{out}"
        );
        // Scope to the new atom's BODY — everything after its marker and before the notes section,
        // which legitimately holds the `[^N]:` DEFINITIONS and would make a whole-tail scan vacuous.
        let new_body = out
            .split_once("^ATOM-6666-6666")
            .unwrap()
            .1
            .split_once("## Notes and lessons learned")
            .unwrap()
            .0;
        assert!(!new_body.contains("[^"), "no anchor left on the new half:\n{out}");

        // …and one of them can be assigned to the new topic deliberately.
        let (out2, _) = split_atom_build(
            &text,
            "ATOM-5555-5555",
            "SPLIT-HERE",
            &plan(&kw, None, None, &["2".to_string()]),
        )
        .expect("split must succeed");
        let (before, after) = out2.split_once("^ATOM-6666-6666").unwrap();
        let new_body2 = after.split_once("## Notes and lessons learned").unwrap().0;
        assert!(before.contains("first half line one [^1]") && !before.contains("[^2]"), "1 stays:\n{out2}");
        assert!(new_body2.contains("[^2]") && !new_body2.contains("[^1]"), "2 moves:\n{out2}");
    }

    /// A moved anchor must land on PROSE, not on the blank line a paragraph break leaves behind.
    #[test]
    fn a_paragraph_break_at_the_split_point_does_not_orphan_the_moved_anchors() {
        // Measured end-to-end before the fix: the first half ended in the BLANK line separating
        // the paragraphs, so the moved ` [^1]` landed alone on its own line under an empty
        // paragraph instead of on the prose it now annotates.
        let kw = vec!["gamma".to_string(), "delta".to_string()];
        let text = PAGE
            .replace(
                "first half line one\nSPLIT-HERE second half line one",
                "first half line one\n\nSPLIT-HERE second half line one [^1]",
            )
            .replace(
                "## Notes and lessons learned\n",
                "## Notes and lessons learned\n[^1]: DO NOT do X, BECAUSE y. DO z instead.\n",
            );
        let (out, _) = split_atom_build(&text, "ATOM-5555-5555", "SPLIT-HERE", &plan(&kw, None, None, &[]))
            .expect("split must succeed");
        assert!(out.contains("first half line one [^1]"), "anchor lands on the prose:\n{out}");
        assert!(!out.contains("\n [^1]"), "no orphan anchor line:\n{out}");
    }

    /// A ref sitting MID-PROSE is an authored anchor — it belongs to the sentence it is in and
    /// must travel with that prose, never be swept to the other half by the trailing-anchor rule.
    #[test]
    fn a_mid_prose_footnote_ref_is_never_moved() {
        let kw = vec!["gamma".to_string(), "delta".to_string()];
        let text = PAGE
            .replace("SPLIT-HERE second half line one", "SPLIT-HERE second [^3] half line one")
            .replace(
                "## Notes and lessons learned\n",
                "## Notes and lessons learned\n[^3]: DO NOT do X, BECAUSE y. DO z instead.\n",
            );
        let (out, _) = split_atom_build(&text, "ATOM-5555-5555", "SPLIT-HERE", &plan(&kw, None, None, &[]))
            .expect("split must succeed");
        let after = out.split_once("^ATOM-6666-6666").unwrap().1;
        assert!(after.contains("second [^3] half"), "mid-prose ref stays put:\n{out}");
    }
}
