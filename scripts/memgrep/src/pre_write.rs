//! The shared pre-write gate (TRDD-XI10BA5D A2) — the prepare/commit pipeline behind a page write.
//!
//! Owner's write contract (card STATE): every memgrep write verb runs ONE pipeline before disk —
//! parse, auto-fix safely, format canonically, lint, validate specs — and writes atomically ONLY
//! on a clean result; otherwise it writes nothing and exits non-zero naming each violation.
//!
//! Step 3 wires ONE verb (`update-mem-topic`, `cmd_edit_cli`) through it; the other verbs follow
//! one reviewed commit apiece (card follow-on list). Deliberately NOT here yet: the id-set /
//! ocd / lmd rules, one-sided-link refusal, batch atomicity (`prepare_batch`), stderr disclosure
//! and the sha256 print — each is a later step of the same card, per the reviewed sequence.
//!
//! The prepare / commit split:
//!
//!   * `prepare` validates the PROPOSED final bytes — the full per-page lint catalog runs on the
//!     text that WOULD land, and every finding the classifier refuses on (`write_gate_blocks`,
//!     the card's strict default, NOTE-A) makes the write fail naming all of them. A refusal
//!     means zero bytes written and zero side effects: it fires BEFORE commit is ever entered.
//!   * commit is the existing `atomic_write_page` primitive, unchanged: control-byte refusal
//!     (A1), the `publish-globally:` convergence loop, the junk-symlink sweep. The auto-fix half
//!     of the owner's pipeline therefore already lives at commit — and the findings commit fixes
//!     are exactly the codes the gate GRANDFATHERS (`publish-globally-*`), so prepare never
//!     refuses what commit is about to repair. When a per-page fix pass is added (the reserved
//!     `fix` parameter of `lint_page_text`), it slots into `prepare`; nothing else moves.

use crate::memory::{
    atomic_write_page, collapse_strip_anchors, lint_page_text, parse_block_props,
    raw_footnote_defs, resolve_atoms_from_text, split_note_metadata, write_gate_blocks,
};
use anyhow::Result;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
/// Validate the PROPOSED final bytes of ONE page write against the write-gate floor.
///
/// Runs `lint_page_text` report-only on `proposed` and refuses when ANY finding is classified
/// blocking by `write_gate_blocks` — the refusal names EVERY blocking violation (owner: "exits
/// non-zero naming each violation"), not just the first. A grandfathered ERROR (legacy
/// frontmatter debt, the lint-floor phrase counts, publish-globally states) does NOT refuse:
/// see `write_gate_blocks`' doc comment for the per-code rationale.
///
/// Refusal happens BEFORE any commit step, so a refused write leaves the page byte-identical on
/// disk and runs no normalization, symlink or reindex side effect.
pub(crate) fn prepare(dest: &Path, proposed: &str) -> Result<()> {
    let blocked: Vec<_> = lint_page_text(dest, proposed, false)
        .into_iter()
        .filter(|v| write_gate_blocks(v))
        .collect();
    if blocked.is_empty() {
        return Ok(());
    }
    // Each line reuses lint's exact `SEV path:line [code] — msg` shape, so a refusal is
    // diffable against `memgrep lint` output. No line carries page CONTENT: every lint check
    // is content-snippet-free by construction (a page can hold private material), so a refusal
    // message is safe to print anywhere a verb's stderr already goes.
    let mut msg = format!(
        "write gate refused {}: {} blocking finding(s) in the proposed bytes — nothing was written:",
        dest.display(),
        blocked.len()
    );
    for v in &blocked {
        msg.push_str(&format!(
            // Refusal lines reuse lint's `SEV path:line [code] — msg` shape but stay ANCHOR-FREE:
            // a refused write landed NOTHING, so there is no finding on disk to ticket — the
            // anchor token would imply a ticketable state that does not exist (spec req 5 / A1).
            "\n  {} {}:{} [{}] — {}",
            v.sev.label(),
            dest.display(),
            v.line,
            v.code,
            v.msg
        ));
    }
    anyhow::bail!(msg)
}

/// The per-call policy of a gated write — what the id-set rule may treat as retired by the
/// verb itself. Data-shaped on purpose (no verb names, no allowlists): a caller declares WHICH
/// ids its own write retires; the gate still refuses every other disappearance.
#[derive(Default)]
pub(crate) struct GatePolicy {
    /// Atom/lesson ids this write legitimately removes (only `delete-mem-atom` and
    /// `merge-mem-atom` today — the card's retirement audit: these are the verbs whose
    /// contract IS dropping an id).
    pub retired_ids: BTreeSet<String>,
    /// Skip the id-REUSE (changed-body) check while still enforcing the DROP check. Set only by
    /// the verbs whose contract IS rewriting a body under a SURVIVING id (the brief's
    /// reconciliation of the reuse rule with wave 1): `update-mem-atom`'s body-rewrite path,
    /// `merge-mem-atom` and `split-mem-atom` (the kept atom's body legitimately changes), and
    /// `update-mem-topic` (TRDD-JFIOO9XO CURE 2 — the sanctioned --replace-all control-byte
    /// repair may land inside an atom body).
    pub allow_body_rewrite: bool,
}

/// One id's content identity: the whitespace-collapsed body with `[^N]` anchors AND `See also:`
/// lines stripped. Anchors renumber on every move (migrate/split/merge/add-lesson) and
/// reference-mem-atom appends a `See also: [[…]]` line INSIDE the atom's body span — neither is
/// a content change, so neither may fire the id-reuse refusal.
fn body_fingerprint(text: &str) -> String {
    let prose: Vec<&str> = text
        .lines()
        .filter(|l| !l.trim_start().to_ascii_lowercase().starts_with("see also:"))
        .map(|l| l.trim_start())
        .collect();
    collapse_strip_anchors(&prose.join("\n"))
}

/// Every atom/lesson id a page's text carries, keyed by id, with each id's body fingerprint.
/// Atoms key on the `^id` marker; lessons on the `id:` prop inside the `[^N]:` metadata — NEVER
/// the `[^N]` label, which renumbers freely (the card: a renumbering is not a loss).
///
/// ponytail: `raw_footnote_defs` is fence-blind (a `[^N]:` line inside a fenced example counts),
/// same as the verb computes that produce the proposed bytes; a corpus that fences lesson-shaped
/// lines would need the comrak-backed def scan here.
fn id_inventory(text: &str) -> BTreeMap<String, String> {
    let mut ids: BTreeMap<String, String> = BTreeMap::new();
    for a in resolve_atoms_from_text(text) {
        ids.insert(a.id, body_fingerprint(&a.body));
    }
    let lines: Vec<&str> = text.lines().collect();
    for (_label, raw) in raw_footnote_defs(&lines) {
        let (meta, rest) = split_note_metadata(&raw);
        let Some(meta) = meta else { continue };
        let Some(id) = parse_block_props(&meta).get("id").and_then(|v| v.first()).cloned() else {
            continue; // no stable id — nothing for the rule to pin (lint warns separately)
        };
        ids.insert(id, body_fingerprint(&rest));
    }
    ids
}

/// The id-set rule over a write batch (TRDD-XI10BA5D A2, card rules block):
///
/// - an id present on disk (union of the pages being written) but absent from EVERY proposed
///   page refuses, unless the caller's `policy.retired_ids` claims it — a write may not
///   silently drop a memory;
/// - an id that survives with a CHANGED collapsed body refuses: same id must mean same memory.
///
/// The compare is over the batch UNION (the coordinator's shape note: id PERSISTENCE, never
/// verb identity), so migrate/split/merge — which move ids between pages of the same batch —
/// pass with no carve-out. Refusals name ids and counts only, never page content.
fn enforce_id_rules(
    old: &[BTreeMap<String, String>],
    proposed: &[BTreeMap<String, String>],
    policy: &GatePolicy,
) -> Result<()> {
    let mut old_union: BTreeMap<&str, &str> = BTreeMap::new();
    for inv in old {
        for (id, fp) in inv {
            old_union.entry(id).or_insert(fp);
        }
    }
    let mut new_union: BTreeMap<&str, &str> = BTreeMap::new();
    for inv in proposed {
        for (id, fp) in inv {
            new_union.entry(id).or_insert(fp);
        }
    }
    let mut refusals: Vec<String> = Vec::new();
    for (id, _fp) in &old_union {
        if !new_union.contains_key(*id) && !policy.retired_ids.contains(*id) {
            refusals.push(format!(
                "id-set rule: `{id}` is present on disk but absent from the proposed bytes and \
                 this write does not retire it — a write may not silently drop a memory; use the \
                 verb that owns the removal"
            ));
        }
    }
    if !policy.allow_body_rewrite {
        for (id, fp) in &new_union {
            if let Some(old_fp) = old_union.get(id)
                && fp != old_fp
            {
                refusals.push(format!(
                    "id-set rule: `{id}` survives this write with a CHANGED body — an id reused \
                     for new content breaks every citation of it; retire it and mint a new id \
                     instead"
                ));
            }
        }
    }
    if refusals.is_empty() {
        return Ok(());
    }
    refusals.sort();
    refusals.dedup();
    anyhow::bail!(
        "write gate refused (id-set rule; nothing was written; {} violation(s)):\n{}",
        refusals.len(),
        refusals.iter().map(|r| format!("  - {r}")).collect::<Vec<_>>().join("\n")
    )
}

/// Batch-INTERNAL duplicate-id check (TRDD-GD24IL7O part a): refuse an id this write MINTS onto
/// a second page — the count of pages carrying the id must not GROW. Both `id_inventory` and the
/// batch unions collapse a duplicate id into one entry (`or_insert`), so a write that leaves the
/// same atom id on two pages passes DROP (the union still has it) and REUSE (same fingerprint)
/// invisibly — the gate would certify a malformed cross-page state that leaves every citation
/// ambiguous. Compared against the OLD page count, not against "at most one proposed page":
/// an id already duplicated on disk before this write (the batch-union migrate/move contract
/// keeps such a state passing) must stay REPAIRABLE through normal verbs — refusing every write
/// that merely preserves an inherited dup would freeze it forever. The scope-wide inherited-dup
/// question is the cross-BATCH boundary item recorded on TRDD-XI10BA5D, deliberately out of
/// scope here. The refusal names ids, counts and paths only — never page content.
fn refuse_cross_page_duplicate_ids(
    old: &[BTreeMap<String, String>],
    writes: &[(&Path, &str)],
    proposed_inv: &[BTreeMap<String, String>],
) -> Result<()> {
    let mut old_pages: BTreeMap<&str, usize> = BTreeMap::new();
    for inv in old {
        for id in inv.keys() {
            *old_pages.entry(id.as_str()).or_insert(0) += 1;
        }
    }
    let mut pages_per_id: BTreeMap<&str, Vec<&Path>> = BTreeMap::new();
    for ((p, _), inv) in writes.iter().zip(proposed_inv) {
        for id in inv.keys() {
            pages_per_id.entry(id.as_str()).or_default().push(*p);
        }
    }
    let dups: Vec<(&str, Vec<&Path>)> = pages_per_id
        .into_iter()
        // The floor is ONE page: minting a brand-new id onto its first page (0 → 1) is every
        // atom-creating verb's whole job and must pass; only growth BEYOND one page (0 → 2,
        // 1 → 2) mints a duplicate. An id already on 2+ pages preserved as 2+ (1 → 1 moves
        // included) passes — the inherited-dup state stays repairable, per the doc comment.
        .filter(|(id, ps)| ps.len() > old_pages.get(*id).copied().unwrap_or(0).max(1))
        .collect();
    if dups.is_empty() {
        return Ok(());
    }
    let mut msg = format!(
        "write gate refused (duplicate-id rule; nothing was written; {} violation(s)):",
        dups.len()
    );
    for (id, pages) in dups {
        let list = pages
            .iter()
            .map(|p| format!("`{}`", p.display()))
            .collect::<Vec<_>>()
            .join(", ");
        msg.push_str(&format!(
            "\n  - duplicate-id rule: `{id}` ends up on {n} pages of this batch ({list}) but \
             started on {m} — this write mints a duplicate atom id, and an id may live on at \
             most ONE page; a move between pages is legal (it stays one page), so remove the \
             new copy and rewrite",
            n = pages.len(),
            m = old_pages.get(id).copied().unwrap_or(0)
        ));
    }
    anyhow::bail!(msg)
}

/// The batch half of the gate (TRDD-XI10BA5D A2 step 5 wave 2): prepare EVERY page's proposed
/// bytes (lint floor per page, `prepare`), refuse a batch-INTERNAL duplicate id (TRDD-GD24IL7O:
/// an id on two different proposed pages is invisible to the union compare — see
/// `refuse_cross_page_duplicate_ids`), refuse an INTRODUCED one-sided wikilink (step 6 —
/// `refuse_introduced_one_sided_links`) and run the id-set rule over the batch, BEFORE the caller
/// commits anything. A refusal anywhere means zero bytes written anywhere. The caller
/// then commits each page through `atomic_write_page` in ITS OWN order (merge/split/migrate own
/// recoverable-duplicate orderings and partial-failure messages), so the bytes each commit writes
/// are exactly the bytes this function certified.
pub(crate) fn prepare_batch_gated(writes: &[(&Path, &str)], policy: &GatePolicy) -> Result<()> {
    for (dest, proposed) in writes {
        prepare(dest, proposed)?;
    }
    let mut old: Vec<BTreeMap<String, String>> = Vec::with_capacity(writes.len());
    for (p, _) in writes {
        old.push(id_inventory(&read_for_inventory(p)?));
    }
    let proposed_inv: Vec<BTreeMap<String, String>> =
        writes.iter().map(|(_, t)| id_inventory(t)).collect();
    refuse_cross_page_duplicate_ids(&old, writes, &proposed_inv)?;
    refuse_introduced_one_sided_links(&batch_roots_for(writes), writes)?;
    enforce_id_rules(&old, &proposed_inv, policy)
}

/// The scope roots the batch's cross-page checks (duplicate ids, link law) judge the batch over:
/// each write's owning scope root (`owning_scope_root` — the nearest `.memgrep/` ancestor, else
/// the page's own dir), deduplicated, in first-appearance order. The same widening `lint` does
/// for a named page (`link_graph_roots`), so the gate's link verdict and the lint's agree.
fn batch_roots_for(writes: &[(&Path, &str)]) -> Vec<PathBuf> {
    let mut roots: Vec<PathBuf> = Vec::new();
    for (p, _) in writes {
        let root = crate::memory::owning_scope_root_pub(p);
        if !roots.contains(&root) {
            roots.push(root);
        }
    }
    roots
}

/// A page's current on-disk text for inventory purposes. FAILS CLOSED (TRDD-JFIOO9XO CURE 1):
/// only a not-yet-existing page (`split-mem-topic`'s destination, `new-page`) inventories as
/// EMPTY — the gate judges the write's own blast radius, and a page not yet on disk cannot lose
/// an id in it. Any OTHER read failure (permission error, invalid UTF-8) refuses hard with a
/// RETRYABLE message: inventorying such a page as EMPTY would certify dropping every id on it —
/// the exact corruption class the gate exists for. The message is an instruction to reread and
/// retry (STALE_MSG-style), so a transient EACCES on a race makes the worker retry, not conclude
/// the gate is broken.
fn read_for_inventory(page: &Path) -> Result<String> {
    match std::fs::read_to_string(page) {
        Ok(text) => Ok(text),
        // NotFound is the one safe empty: no page on disk, so no id can be lost in it.
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(String::new()),
        Err(e) => anyhow::bail!(
            "write gate could not read `{}` for the id-set inventory ({e}) — fail-closed, \
             nothing was written; please reread the file first and retry",
            page.display()
        ),
    }
}

/// The single-page gated write WITH the id-set rule (the gated form of `delete-mem-atom`'s
/// write), for callers whose batch is one page but whose verb legitimately retires ids.
pub(crate) fn write_gated_with(dest: &Path, proposed: &str, policy: &GatePolicy) -> Result<()> {
    prepare_batch_gated(&[(dest, proposed)], policy)?;
    // commit — `atomic_write_page` keeps its own control-byte refusal as the last line of
    // defence and owns the publish-globally convergence + symlink reconciliation exactly as it
    // does for every ungated caller today.
    atomic_write_page(dest, proposed)?;
    post_commit_disclosure(dest, proposed)
}

/// The gated write: `prepare` the proposed bytes, then — and only then — commit them through the
/// existing atomic primitive. This is the ONE entry a wired verb calls in place of a bare
/// `atomic_write_page`; every verb not yet wired keeps calling `atomic_write_page` directly and
/// is therefore UNGATED, which is the reviewed sequencing (one verb per commit), not an oversight.
pub(crate) fn write_gated(dest: &Path, proposed: &str) -> Result<()> {
    // The id-set rule is a property of ANY gated write (the card: "over a batch (or a single
    // write)"), so every gated verb gets it by construction — no policy, no retires, no
    // rewrite exemption.
    write_gated_with(dest, proposed, &GatePolicy::default())
}

/// Post-commit disclosure for a gated write (TRDD-XI10BA5D A2 step 6):
///
/// - the new page's sha256 on STDERR — `write verbs print the new sha256` (card rules block), so
///   a chained caller can pass it straight back as `--base-sha256` without re-hashing by hand.
///   STDERR, not stdout: the writing verbs' stdout contracts are load-bearing for existing
///   callers (`add-atom`/`add-lesson`'s first line IS the fresh id, `update-mem-topic`'s line is
///   tab-separated path\tverb-note), and prepending a metadata line would break every
///   first-token parse. The tab-separated `sha256\t<hash>\t<path>` shape keeps `cut` usable on
///   either stream. Hashing the BYTES on disk (not the proposed String) makes the printed value
///   byte-identical to what `write_gate::check_base` will later verify against.
/// - one stderr line when the LANDED bytes differ from the caller's proposed bytes — the commit
///   layer (`atomic_write_page`'s publish-globally convergence loop) auto-fixed something beyond
///   the caller's own edit, and `every auto-fix disclosed on stderr` is a card rule. Diffing the
///   bytes catches a fix that already converged (the re-classified page would look clean); this
///   is why the compare is against `proposed`, not a re-detection. The line names the layer and
///   the field, never page content (the no-leak contract — it is the same refusal surface).
///
/// Best-effort by design: a disclosure read failure must never fail a write that has already
/// landed — that line is skipped, the sha256 too. `pub(crate)` so the BATCH verbs call it after
/// each of their own ordered commits (they run `prepare_batch_gated` + bare `atomic_write_page`
/// calls, so their disclosure would otherwise be lost — same lines, same streams, one page per
/// call).
pub(crate) fn post_commit_disclosure(dest: &Path, proposed: &str) -> Result<()> {
    let landed = std::fs::read_to_string(dest).ok();
    if landed.as_deref() != Some(proposed) {
        eprintln!(
            "write gate: commit auto-fix applied on {} (publish-globally reconciliation rewrote the landed bytes)",
            dest.display()
        );
    }
    if let Ok(hash) = crate::write_gate::sha256_of_file(dest) {
        eprintln!("sha256\t{hash}\t{}", dest.display());
    }
    Ok(())
}

// ── TRDD-XI10BA5D A2 step 6: the one-sided-link refusal ─────────────────────────────────────

/// The card rule: "refuse an introduced one-sided link (no auto-wire, the error names
/// reference-mem-topic)". THE LINK LAW (markdown-memory-recall.md) makes every `[[wikilink]]`
/// bidirectional; the extraction and resolution here are the LINT's own (`build_graph`,
/// issue #49 name-slug resolution, TRDD alias), so the gate's verdict cannot disagree with a
/// later `memgrep lint` on the same corpus.
///
/// INTRODUCED-ONLY by design (the diff-scoped reading the card records for the link rule): an
/// edge that was already one-sided ON DISK passes — such an edge's missing half lives in a file
/// this write does not own, and refusing would freeze the 60+ legacy one-sided edges forever
/// behind every unrelated edit. The refusal fires exactly when the write MINTS a new unreciprocated
/// edge: present in the batch's proposed bytes, absent from the batch's own reciprocal wiring, and
/// absent from the disk's directed edge set. The message names `reference-mem-topic` — the verb
/// that wires both ends in one call.
///
/// A CROSS-SCOPE edge is never a candidate: LOCAL → PROJECT → USER links go strictly UPWARD and
/// are unreciprocated BY LAW — the same exemption the lint's Check 2/4 applies. Downward links
/// stay the scope-wide lint's `link-downward-cross-scope` ERROR, unchanged by this card.
fn refuse_introduced_one_sided_links(
    batch_roots: &[PathBuf],
    writes: &[(&Path, &str)],
) -> Result<()> {
    // The DISK's directed edge set, over the batch's own scope roots (the same widening the lint
    // uses: a named page's cross-page invariant needs the whole scope to judge reciprocity).
    let g = crate::memory::build_graph(batch_roots, false);
    let canon = |p: &Path| p.canonicalize().unwrap_or_else(|_| p.to_path_buf());
    let mut disk_edges: BTreeSet<(PathBuf, PathBuf)> = BTreeSet::new();
    for e in &g.edges {
        if let Some(target) = &e.target {
            disk_edges.insert((canon(&e.from), canon(target)));
        }
    }

    // The BATCH's own proposed directed edges (per page), so a batch that wires both ends itself
    // (merge's tombstone + destination, reference-*, split's see-also pair, migrate
    // --leave-link) certifies itself. Resolution registers the BATCH: a link pointed at the
    // batch's own NEW page (split's not-yet-on-disk destination) resolves to its proposed path
    // instead of coming back unresolved — without this, split's legitimate pair false-refuses.
    let mut batch_edges: BTreeSet<(PathBuf, PathBuf)> = BTreeSet::new();
    for (dest, text) in writes {
        let ctx = crate::md::build_context(text, text.lines().count());
        for l in &ctx.links {
            if let Some((t, _raw)) = resolve_in_graph(&l.url, dest, batch_roots, writes) {
                batch_edges.insert((canon(dest), canon(&t)));
            }
        }
    }

    let mut refusals: Vec<String> = Vec::new();
    for (dest, text) in writes {
        let ctx = crate::md::build_context(text, text.lines().count());
        for l in &ctx.links {
            let Some((target_path, _raw)) = resolve_in_graph(&l.url, dest, batch_roots, writes) else {
                continue; // unresolved (broken) or external — not a LINK-LAW candidate
            };
            let from_c = canon(dest);
            let to_c = canon(&target_path);
            if from_c == to_c {
                continue; // self-link is trivially reciprocal
            }
            // Cross-scope: upward edges are unreciprocated by law; the scope rule owns them.
            if let (Some(fs_), Some(ts_)) = (
                crate::memory::scope_layer(&from_c),
                crate::memory::scope_layer(&to_c),
            ) && fs_ != ts_
            {
                continue;
            }
            let edge = (from_c.clone(), to_c.clone());
            if batch_edges.contains(&(to_c.clone(), from_c.clone()))
                || disk_edges.contains(&(to_c.clone(), from_c.clone()))
            {
                continue; // reciprocated in-batch or already on disk
            }
            if disk_edges.contains(&edge) {
                continue; // PRE-EXISTING one-sided edge — repairable, never frozen (see doc)
            }
            refusals.push(format!(
                "one-sided-link rule: `{from}` links to `{to}` but nothing reciprocates it — \
                 the LINK LAW needs both ends wired in one edit; use `memgrep reference-mem-topic \
                 --page {from} --to {to}` (or `--leave-link` on migrate)",
                from = dest.display(),
                to = target_path.display(),
            ));
        }
    }
    if refusals.is_empty() {
        return Ok(());
    }
    refusals.sort();
    refusals.dedup();
    anyhow::bail!(
        "write gate refused (one-sided-link rule; nothing was written; {} violation(s)):\n{}",
        refusals.len(),
        refusals.iter().map(|r| format!("  - {r}")).collect::<Vec<_>>().join("\n")
    )
}

/// Resolve ONE raw link URL to a target page through the REAL per-root name maps (the graph's own
/// resolution, re-run standalone: `resolve` needs `per_root`/`global`, which only `build_graph`
/// assembles). Builds the maps once per call — the batch is small (2-4 pages) and the map build
/// is one walk of the scope, the same cost `build_graph` already paid above.
///
/// `batch` pages are REGISTERED too: a name matching one of the batch's own destinations
/// resolves to that destination even when it does not exist on disk yet (split's new page), so
/// a link pointed at the batch's own output resolves to its PROPOSED path. The batch is inserted
/// AFTER the disk walk (first-wins `or_insert` keeps disk entries otherwise), so a batch page
/// OVERRIDES a same-named disk page — the imminent write supersedes what is on disk.
fn resolve_in_graph(
    url: &str,
    from: &Path,
    roots: &[PathBuf],
    batch: &[(&Path, &str)],
) -> Option<(PathBuf, String)> {
    let url = url.split('#').next().unwrap_or(url).trim();
    if url.is_empty() || url.contains("://") || url.starts_with("mailto:") {
        return None; // pure anchor or external — never a LINK-LAW candidate
    }
    if url.contains('/') || url.ends_with(".md") {
        let joined = from.parent().unwrap_or(Path::new(".")).join(url);
        return joined.canonicalize().ok().map(|t| (t, url.to_string()));
    }
    // Bare wikilink name: same key derivations as `build_graph` (stem, `_`→`-` normalized, the
    // frontmatter `name:`/`topic:` slug, the TRDD-id8 alias), same-scope first, then global.
    // The key derivation lives inside `memory::resolve` — never duplicated here.
    let files = crate::memory::collect_md(roots, false);
    let mut global: BTreeMap<String, PathBuf> = BTreeMap::new();
    let mut per_root: Vec<BTreeMap<String, PathBuf>> = vec![BTreeMap::new(); roots.len()];
    for p in &files {
        let canon_p = p.canonicalize().unwrap_or_else(|_| p.clone());
        let ridx = roots
            .iter()
            .enumerate()
            .filter(|(_, r)| {
                let rc = r.canonicalize().unwrap_or_else(|_| (*r).clone());
                canon_p.starts_with(&rc)
            })
            .max_by_key(|(_, r)| r.as_os_str().len())
            .map(|(i, _)| i);
        let mut keys: Vec<String> = Vec::new();
        if let Some(stem) = p.file_stem().and_then(|s| s.to_str()) {
            let stem_l = stem.to_ascii_lowercase();
            keys.push(stem_l.clone());
            let norm = stem_l.replace('_', "-");
            if norm != stem_l {
                keys.push(norm);
            }
        }
        if let Some(slug) = crate::memory::read_note(p).and_then(|n| n.name) {
            keys.push(slug);
        }
        if let Some(name) = p.file_name().and_then(|s| s.to_str())
            && let Some(c) = crate::memory::trdd_id8_re().captures(name)
        {
            keys.push(format!("trdd-{}", c[1].to_ascii_lowercase()));
        }
        for k in keys {
            global.entry(k.clone()).or_insert_with(|| p.clone());
            if let Some(i) = ridx {
                per_root[i].entry(k).or_insert_with(|| p.clone());
            }
        }
    }
    // REGISTER THE BATCH: same key derivations over each write's PROPOSED frontmatter `name:`,
    // inserted last so they win the first-wins race against disk. Relative-path links land
    // above, so only the bare-name form needs this.
    for (p, text) in batch {
        let mut keys: Vec<String> = Vec::new();
        if let Some(stem) = p.file_stem().and_then(|s| s.to_str()) {
            let stem_l = stem.to_ascii_lowercase();
            keys.push(stem_l.clone());
            let norm = stem_l.replace('_', "-");
            if norm != stem_l {
                keys.push(norm);
            }
        }
        let fm = crate::md::parse_frontmatter(text);
        if let Some(slug) = fm
            .get("name")
            .or_else(|| fm.get("topic"))
            .map(|s| s.trim().to_ascii_lowercase())
            .filter(|s| !s.is_empty())
        {
            keys.push(slug);
        }
        for k in keys {
            global.insert(k.clone(), (*p).to_path_buf());
            if let Some(i) = roots.iter().position(|r| {
                let rc = r.canonicalize().unwrap_or_else(|_| (*r).clone());
                let pc = (*p).canonicalize().unwrap_or_else(|_| (*p).to_path_buf());
                pc.starts_with(&rc)
            }) {
                per_root[i].insert(k, (*p).to_path_buf());
            }
        }
    }
    let home = roots.iter().position(|r| {
        let rc = r.canonicalize().unwrap_or_else(|_| r.clone());
        from.canonicalize().unwrap_or_else(|_| from.to_path_buf()).starts_with(&rc)
    });
    let (target, external) = crate::memory::resolve(url, from, home, &per_root, &global);
    if external {
        return None;
    }
    target.map(|t| (t, url.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The refusal names EVERY blocking violation, not just the first (owner: "naming each
    /// violation"). Two independent floor codes in the proposed bytes — an unclosed code fence
    /// and a keyword-less atom — must both appear, with the count. Pure `prepare` test: commit
    /// is never reached, so no env or disk setup is needed (the publish-globally check skips a
    /// path that does not exist, and nothing here mutates process state).
    #[test]
    fn prepare_names_every_blocking_violation_not_just_the_first() {
        let path = Path::new("/nonexistent/fixture/gate.md");
        // The atom comes BEFORE the unclosed fence: an unclosed fence deliberately suppresses
        // every structural finding BELOW it ("everything under it is invisible" — the check's
        // own refusal message), so the fence cannot be first in a fixture that needs two codes.
        let proposed = "---\nname: p\n---\n^ATOM-N [ocd: 2026-01-01]\nbody\n\n```\nunclosed fence\n";
        let err = prepare(path, proposed).expect_err("two floor violations must refuse");
        let msg = err.to_string();
        assert!(msg.contains("write gate refused"), "{msg}");
        assert!(msg.contains("2 blocking finding"), "the count must be named: {msg}");
        assert!(msg.contains("nothing was written"), "{msg}");
        assert!(msg.contains("page-unclosed-fence"), "fence code must be named: {msg}");
        assert!(msg.contains("atom-no-keywords"), "keyword code must be named: {msg}");
    }

    /// A page whose ONLY ERROR findings are GRANDFATHERED codes (here: legacy thin description,
    /// missing ocd/lmd/Notes) must pass prepare — grandfathering is a gate decision, not a lint
    /// omission, and prepare must wire the classifier, not re-implement "any ERROR refuses"
    /// (that stricter reading is what step 2's floor reconciliation deliberately replaced).
    #[test]
    fn prepare_does_not_refuse_grandfathered_findings() {
        let path = Path::new("/nonexistent/fixture/grandfathered.md");
        let proposed = "---\nname: p\n---\nbody text\n";
        prepare(path, proposed).expect("grandfathered-only findings must not refuse");
    }

    // ── TRDD-XI10BA5D A2 step 4: the two step-3 review tests (binding) ─────────────────────────

    /// Step-3 review NOTE 1 (binding): the gate's verdict is a function of the PROPOSED bytes
    /// alone — `lint_page_text` must read the text it is PASSED, never the disk at `dest`. The
    /// fixture makes the two hypotheses predict OPPOSITE refusals, so the evidence discriminates:
    /// the bytes ON DISK carry only an unclosed fence, the PROPOSED bytes carry only a
    /// keyword-less atom. A text-reading lint refuses `atom-no-keywords`; a disk-reading one
    /// refuses `page-unclosed-fence`. The second half pins the other direction of the same
    /// property: the identical verdict is reachable by writing the proposed bytes and linting
    /// what actually landed — "verdict on proposed == verdict on written", byte-for-byte.
    // keep contrastive: disk and proposed must classify DIFFERENTLY or the test degenerates.
    #[test]
    fn gate_verdict_tracks_the_proposed_bytes_not_the_disk_state() {
        let dir = std::env::temp_dir()
            .join(format!("memgrep_gate_dest-purity-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let page = dir.join("p.md");
        let on_disk = "---\nname: p\n---\n```\nunclosed fence on disk\n";
        std::fs::write(&page, on_disk).unwrap();
        let proposed = "---\nname: p\n---\n^ATOM-N [ocd: 2026-01-01]\nbody\n\n## Notes and lessons learned\n";

        let err = prepare(&page, proposed).expect_err("the proposed bytes must refuse");
        let msg = err.to_string();
        assert!(
            msg.contains("[atom-no-keywords]"),
            "the refusal must name the PROPOSED bytes' violation: {msg}"
        );
        assert!(
            !msg.contains("page-unclosed-fence"),
            "the disk page's own violation must be invisible to the gate — prepare reads the \
             passed text, never `dest`: {msg}"
        );

        // The same verdict from the written side: the proposed bytes, once written, lint to the
        // identical blocking set the refusal named.
        let written = dir.join("written.md");
        std::fs::write(&written, proposed).unwrap();
        let landed = std::fs::read_to_string(&written).unwrap();
        let blocking_written: Vec<&str> = lint_page_text(&written, &landed, false)
            .into_iter()
            .filter(|v| write_gate_blocks(v))
            .map(|v| v.code)
            .collect();
        let refused: Vec<&str> = crate::memory::write_gate_floors()
            .iter()
            .copied()
            .filter(|c| msg.contains(&format!("[{c}]")))
            .collect();
        assert_eq!(
            refused, blocking_written,
            "the gate's verdict on the proposed bytes must equal a lint of those same bytes \
             once written"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Step-3 review NOTE 2 (binding): a refusal must never carry page CONTENT. Every lint check
    /// is content-snippet-free by construction; this pins the refusal END-TO-END so the first
    /// helpful lint message that starts quoting a fragment fails here instead of leaking page
    /// prose to whatever stderr a verb's refusal reaches. The canaries sit where page text lives
    /// — body prose, atom props, inside a fenced block. The atom ID is deliberately canary-free:
    /// naming ids in refusals IS the design (the step-5 id-set rule is required to name them).
    #[test]
    fn refusal_message_carries_no_page_body_content() {
        let path = Path::new("/nonexistent/fixture/no-leak.md");
        let prose_canary = "quarantine ledger ninebyte sealed envelope";
        let desc_canary = "hexdump manifesto 9f2a";
        let fenced_canary = "fenced vault notebook";
        let proposed = format!(
            "---\nname: p\n---\n^ATOM-LEAKPROBE [desc: \"{desc_canary}\"]\n\
             body cites {prose_canary}\n\n```\n{fenced_canary}\n"
        );
        let err = prepare(path, &proposed).expect_err("the fixture must refuse");
        let msg = err.to_string();
        assert!(
            msg.contains("write gate refused"),
            "a real refusal, so the leak assertions are not vacuously true: {msg}"
        );
        assert!(
            !msg.contains(prose_canary),
            "body prose leaked into the refusal: {msg}"
        );
        assert!(
            !msg.contains(desc_canary),
            "atom props leaked into the refusal: {msg}"
        );
        assert!(
            !msg.contains(fenced_canary),
            "fenced content leaked into the refusal: {msg}"
        );
    }

    // ── TRDD-XI10BA5D A2 step 5, wave 1 (binding): the PER-FLOOR-CODE no-leak sweep ─────────────

    /// The step-3 review carry-forward: "widen the no-leak test to a per-floor-code sweep when
    /// the batch verbs' refusal paths land". One BLOCKING fixture per floor code
    /// (`write_gate_floors()`, enumerated from the classifier itself so a code added later joins
    /// the sweep automatically), each refused, each refusal asserted to share NO substring with
    /// the page body. The substring oracle is deliberately fragment-based — each fixture's body
    /// carries one distinctive fragment (a word a snippet-quoting message would echo), plus the
    /// canary-bearing prop values — because a WHOLE-body containment check would pass a message
    /// that quotes one sentence. On its first run the sweep caught THREE quoting emitters
    /// (`page-description-duplicated-phrases` and `atom-keywords-duplicated` echoed the repeated
    /// phrase, `atom-dropped-props` echoed the dropped segment) — all three now report counts
    /// only; a future emitter that starts quoting page content fails here.
    #[test]
    fn every_floor_code_refuses_without_quoting_page_content() {
        // Per-code fixture: `(code, proposed_page, leak_fragments)`. The fragments are the page
        // content the message must NOT echo — the body prose canary (every fixture) plus the
        // code-specific prop values. Fixture shapes mirror the completeness test's fixtures
        // (memory.rs `every_error_code_lint_page_text_emits_is_classified`), each verified to
        // fire its code and ONLY grandfathered findings beside it.
        let fixtures: Vec<(&str, String, Vec<String>)> = vec![
            (
                "control-byte-in-page",
                "---\nname: p\n---\nbackspace\x08canary\n".into(),
                vec!["backspace".into(), "canary".into()],
            ),
            (
                "page-unclosed-fence",
                // The body canary must not reuse the message's own fixed vocabulary (the message
                // legitimately says "unclosed code fence") — a canary that collides with it would
                // false-positive on prose, so the fragment tests a WORD a quoter would echo.
                "---\nname: p\n---\n```\nfencecanary\n".into(),
                vec!["fencecanary".into()],
            ),
            (
                "page-description-duplicated-phrases",
                "---\nname: p\ndescription: \"dupcanary / other phrase / dupcanary\"\nocd: c\nlmd: l\n---\nbodyb\n\n## Notes and lessons learned\n".into(),
                vec!["dupcanary".into(), "other phrase".into()],
            ),
            (
                "footnote-dangling-ref",
                "---\nname: p\ndescription: \"d\"\nocd: c\nlmd: l\n---\ndanglingcanary[^9]\n\n## Notes and lessons learned\n".into(),
                vec!["danglingcanary".into()],
            ),
            (
                "atom-bad-bracket",
                "---\nname: p\ndescription: \"d\"\nocd: c\nlmd: l\n---\n^ATOM-X ⟦keywords: manglecanary⟧\nbody\n\n## Notes and lessons learned\n".into(),
                vec!["manglecanary".into()],
            ),
            (
                "atom-unclosed-props",
                "---\nname: p\ndescription: \"d\"\nocd: c\nlmd: l\n---\n^ATOM-U [keywords: opencanary\nopen\n\n## Notes and lessons learned\n".into(),
                vec!["opencanary".into()],
            ),
            (
                "atom-unquoted-desc",
                "---\nname: p\ndescription: \"d\"\nocd: c\nlmd: l\n---\n^ATOM-Q [desc: Unquoted canaryprop, keywords: k]\nbody\n\n## Notes and lessons learned\n".into(),
                vec!["canaryprop".into()],
            ),
            (
                "atom-dropped-props",
                "---\nname: p\ndescription: \"d\"\nocd: c\nlmd: l\n---\n^ATOM-D [keywords: k, dropper canary]\nbody\n\n## Notes and lessons learned\n".into(),
                vec!["dropper".into()],
            ),
            (
                "atom-keywords-duplicated",
                "---\nname: p\ndescription: \"d\"\nocd: c\nlmd: l\n---\n^ATOM-K [keywords: kwcanary kwcanary kwcanary]\nbody\n\n## Notes and lessons learned\n".into(),
                vec!["kwcanary".into()],
            ),
            (
                "atom-no-keywords",
                "---\nname: p\ndescription: \"d\"\nocd: c\nlmd: l\n---\n^ATOM-N [ocd: 2026-01-01]\nnocankb\n\n## Notes and lessons learned\n".into(),
                vec!["nocankb".into()],
            ),
            (
                "lesson-bad-bracket",
                "---\nname: p\ndescription: \"d\"\nocd: c\nlmd: l\n---\nbody[^1]\n\n## Notes and lessons learned\n\n[^1]: ⟦broken⟧\n".into(),
                vec!["broken".into()],
            ),
            (
                "lesson-empty-body",
                "---\nname: p\ndescription: \"d\"\nocd: c\nlmd: l\n---\nbody[^1]\n\n## Notes and lessons learned\n\n[^1]: [id: L status: valid keywords: k] \n".into(),
                vec![], // the body is whitespace — nothing content-bearing to leak
            ),
            (
                "lesson-unquoted-desc",
                "---\nname: p\ndescription: \"d\"\nocd: c\nlmd: l\n---\nbody[^1]\n\n## Notes and lessons learned\n\n[^1]: [id: L status: valid keywords: k, desc: Unquoted]\nunqucanary\n".into(),
                vec!["unqucanary".into()],
            ),
            (
                "lesson-superseded-no-body",
                "---\nname: p\ndescription: \"d\"\nocd: c\nlmd: l\n---\nbody[^1]\n\n## Notes and lessons learned\n\n[^1]: [id: L status: superseded, supersedes: ATOM-X, keywords: k] supcanary\n".into(),
                vec!["supcanary".into()],
            ),
        ];
        let path = Path::new("/nonexistent/fixture/sweep.md");
        let mut covered: Vec<&str> = Vec::new();
        for (code, proposed, fragments) in &fixtures {
            let msg = match prepare(path, proposed) {
                Err(e) => e.to_string(),
                Ok(()) => panic!(
                    "fixture for `{code}` must actually REFUSE (a sweep row whose fixture \
                     stopped firing is a dead sweep row)"
                ),
            };
            assert!(
                msg.contains(&format!("[{code}]")),
                "the refusal must name `{code}` (fixture drift — the fixture fired a \
                 different code first): {msg}"
            );
            for frag in fragments {
                assert!(
                    !msg.contains(frag.as_str()),
                    "the `{code}` refusal leaked the page fragment `{frag}`: {msg}"
                );
            }
            covered.push(code);
        }
        // The sweep is TOTAL: every floor code in `write_gate_floors()` was exercised. A code
        // added to the floors later joins the sweep or the sweep fails — no silent gap.
        let mut expected: Vec<&str> = crate::memory::write_gate_floors().to_vec();
        expected.sort_unstable();
        covered.sort_unstable();
        assert_eq!(
            covered, expected,
            "the sweep's fixture set and write_gate_floors() have drifted apart"
        );
    }

    // ── TRDD-JFIOO9XO CURE 1: read_for_inventory fails CLOSED ─────────────────────────────────

    /// CURE 1 (TRDD-JFIOO9XO): an unreadable page must REFUSE, not inventory as EMPTY — the old
    /// `unwrap_or_default` made the DROP half certify dropping every id on a permission-error or
    /// invalid-UTF-8 page. Real files, real mode bits: a mode-000 page makes `read_to_string`
    /// fail for real; the refusal must be RETRYABLE (a reread-and-retry instruction, so a
    /// transient EACCES makes the worker retry rather than conclude the gate is broken). The
    /// nonexistent-path half pins the ONE safe empty: NotFound inventories as empty, because
    /// split-mem-topic's not-yet-existing destination cannot lose an id.
    #[cfg(unix)]
    #[test]
    fn unreadable_page_refuses_retryable_and_missing_page_inventories_empty() {
        let dir = std::env::temp_dir()
            .join(format!("memgrep_cure1_inventory-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();

        // NotFound: the one EMPTY case — a page not on disk cannot lose an id in it.
        let missing = dir.join("not-there.md");
        assert_eq!(read_for_inventory(&missing).unwrap(), String::new());

        // Any other io error refuses hard, with a retryable (reread-and-retry) message.
        let locked = dir.join("mode-000.md");
        std::fs::write(&locked, "---\nname: p\n---\n^ATOM-SECRET [ocd: 2026-01-01]\nbody\n").unwrap();
        let mut perms = std::fs::metadata(&locked).unwrap().permissions();
        use std::os::unix::fs::PermissionsExt;
        perms.set_mode(0o000);
        std::fs::set_permissions(&locked, perms).unwrap();
        let err = read_for_inventory(&locked)
            .expect_err("an unreadable page must fail CLOSED, never inventory as EMPTY");
        let msg = err.to_string();
        assert!(
            msg.contains("fail-closed"),
            "the refusal must name fail-closed: {msg}"
        );
        assert!(
            msg.contains("reread the file first and retry"),
            "the refusal must be RETRYABLE (STALE_MSG-style instruction): {msg}"
        );

        // The refusal propagates through the batch entry: a gated batch touching an unreadable
        // page writes NOTHING (fails before commit), naming the read failure — not certifying
        // the dropped ids as retired.
        let dest = dir.join("dest.md");
        let proposed = "---\nname: p\n---\nbody\n";
        let err = prepare_batch_gated(&[(&dest, proposed), (&locked, proposed)], &GatePolicy::default())
            .expect_err("a batch over an unreadable page must refuse");
        let msg = err.to_string();
        assert!(
            msg.contains("fail-closed"),
            "the batch refusal must carry the read failure, not certify drops: {msg}"
        );
        assert!(
            !msg.contains("id-set rule"),
            "the id-set rule must never run on an EMPTY inventory of an unreadable page: {msg}"
        );

        // Cleanup: restore readability so remove_dir_all can succeed.
        let mut perms = std::fs::metadata(&locked).unwrap().permissions();
        perms.set_mode(0o644);
        std::fs::set_permissions(&locked, perms).unwrap();
        let _ = std::fs::remove_dir_all(&dir);
    }

    // ── TRDD-JFIOO9XO CURE 3: the REUSE half is falsifiable ───────────────────────────────────

    /// CURE 3 (TRDD-JFIOO9XO): a SURVIVING id with a CHANGED body must refuse under DEFAULT
    /// policy, naming the id; the same write with `allow_body_rewrite: true` must pass (the DROP
    /// half is untouched); and an UNCHANGED body must pass under default — this last assertion
    /// guards against the fingerprint collapsing every body to equal, which would silently
    /// disable the REUSE half while keeping this test's refusal arm green only via the other
    /// fixture. Exercises the PUBLIC entry (`write_gated_with` end to end, real disk pages) so
    /// the test discriminates the policy plumbing, not just the pure compare.
    #[test]
    fn surviving_id_with_changed_body_refuses_under_default_and_passes_with_allow_body_rewrite() {
        let dir = std::env::temp_dir()
            .join(format!("memgrep_cure3_reuse-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let page = dir.join("p.md");
        let old_text =
            "---\nname: p\n---\n^ATOM-R [ocd: 2026-01-01, keywords: cure3] \noriginal body text\n";
        std::fs::write(&page, old_text).unwrap();

        // CHANGED body under the SURVIVING id, DEFAULT policy → refuse, naming the id.
        let changed =
            "---\nname: p\n---\n^ATOM-R [ocd: 2026-01-01, keywords: cure3] \nrewritten different body\n";
        let err = write_gated(&page, changed)
            .expect_err("a surviving id with a changed body must refuse under DEFAULT policy");
        let msg = err.to_string();
        assert!(
            msg.contains("CHANGED body"),
            "the refusal must be the REUSE (changed-body) arm: {msg}"
        );
        assert!(
            msg.contains("ATOM-R"),
            "the refusal must name the id: {msg}"
        );

        // Same write with allow_body_rewrite: true → pass (DROP half still enforced separately).
        write_gated_with(
            &page,
            changed,
            &GatePolicy { allow_body_rewrite: true, ..Default::default() },
        )
        .expect("allow_body_rewrite must exempt the changed body");

        // UNCHANGED body under DEFAULT → pass: guards against the fingerprint collapsing every
        // body to equal (which would make the refusal arm above vacuous for real changes).
        std::fs::write(&page, old_text).unwrap();
        let same_body_lmd_bumped = "---\nname: p\n---\n^ATOM-R [ocd: 2026-01-01, keywords: cure3] \noriginal body text\n\n## Notes and lessons learned\n";
        write_gated(&page, same_body_lmd_bumped)
            .expect("an unchanged body must pass under DEFAULT policy");
        let _ = std::fs::remove_dir_all(&dir);
    }

    // ── TRDD-GD24IL7O part (a): the batch-INTERNAL duplicate-id check ─────────────────────────

    /// The same atom id carried by TWO proposed pages of one batch must REFUSE, naming the id
    /// and BOTH pages. The fixture makes the union compare blind on purpose: neither page holds
    /// the id on disk (A's old bytes have no id, B does not exist), so DROP and REUSE both PASS
    /// and only the duplicate check can refuse — the exact hole this closes. Ids and paths are
    /// the only leakable things by design; the pages' body and prop fragments must not appear.
    #[test]
    fn id_on_two_pages_of_one_batch_refuses_naming_both_pages() {
        let dir = std::env::temp_dir()
            .join(format!("memgrep_gd24il7o_dup-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let a = dir.join("dup-a.md");
        let b = dir.join("dup-b.md");
        std::fs::write(&a, "---\nname: p\n---\nplain body\n").unwrap();
        let proposed = |kw: &str, body: &str| {
            format!(
                "---\nname: p\n---\n^ATOM-DUPX [ocd: 2026-01-01, keywords: {kw}]\n{body}\n\n## Notes and lessons learned\n"
            )
        };
        let err = prepare_batch_gated(
            &[
                (&a, &proposed("kay-one", "frag-a-canary")),
                (&b, &proposed("kay-two", "frag-b-canary")),
            ],
            &GatePolicy::default(),
        )
        .expect_err("an id on two proposed pages of one batch must refuse");
        let msg = err.to_string();
        assert!(
            msg.contains("nothing was written"),
            "the refusal must carry the zero-write guarantee: {msg}"
        );
        assert!(
            msg.contains("duplicate-id rule"),
            "the refusal must be the DUPLICATE arm, not a floor or id-set finding: {msg}"
        );
        assert!(
            msg.contains("ATOM-DUPX"),
            "the duplicated id must be named: {msg}"
        );
        assert!(
            msg.contains("dup-a.md") && msg.contains("dup-b.md"),
            "BOTH pages carrying the id must be named: {msg}"
        );
        // No-leak: page content (bodies, prop values) must never reach the refusal.
        assert!(!msg.contains("frag-a-canary"), "page A's body leaked: {msg}");
        assert!(!msg.contains("frag-b-canary"), "page B's body leaked: {msg}");
        assert!(!msg.contains("kay-one"), "page A's props leaked: {msg}");
        assert!(!msg.contains("kay-two"), "page B's props leaked: {msg}");
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// The LEGAL move: the id leaves page A's proposed bytes and lands on page B's — present in
    /// exactly ONE proposed page — must pass the whole batch gate (lint floors, duplicate check,
    /// and the DROP/REUSE union compare with an unchanged fingerprint). Guards against the
    /// duplicate check over-refusing migrate/split/merge, the batch's whole reason to exist.
    #[test]
    fn id_moved_between_pages_of_one_batch_passes() {
        let dir = std::env::temp_dir()
            .join(format!("memgrep_gd24il7o_move-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let a = dir.join("mv-a.md");
        let b = dir.join("mv-b.md");
        let atom = "^ATOM-MVX [ocd: 2026-01-01, keywords: mvkey]\nmove body\n";
        std::fs::write(&a, format!("---\nname: p\n---\n{atom}")).unwrap();
        let a_new = "---\nname: p\n---\nplain body after the move\n";
        let b_new = format!("---\nname: p\n---\n{atom}\n## Notes and lessons learned\n");
        prepare_batch_gated(&[(&a, a_new), (&b, &b_new)], &GatePolicy::default())
            .expect("an id MOVED from page A to page B (one proposed page carries it) must pass");
        let _ = std::fs::remove_dir_all(&dir);
    }

    // ── TRDD-XI10BA5D A2 step 6: the one-sided-link refusal ─────────────────────────────────────

    /// An edit that ADDS a `[[target]]` wikilink whose page does not link back must REFUSE,
    /// naming both pages and the verb to use, with nothing written. The target exists on disk
    /// WITHOUT a backlink, so neither the batch's own wiring nor the disk edge set can
    /// reciprocate — the mint of a new unreciprocated edge is exactly what the rule refuses.
    /// The refusal is content-snippet-free (paths only — the no-leak contract).
    #[test]
    fn introduced_one_sided_link_refuses_naming_both_pages_and_the_verb() {
        let dir = std::env::temp_dir()
            .join(format!("memgrep_step6_one-sided-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let page = dir.join("editor.md");
        let target = dir.join("target.md");
        std::fs::write(&page, "---\nname: editor\n---\nplain body\n").unwrap();
        std::fs::write(&target, "---\nname: target\n---\ntarget body\n").unwrap();
        let proposed =
            "---\nname: editor\n---\nsee [[target]] for the rule\n\n## Notes and lessons learned\n";
        let err = write_gated(&page, proposed)
            .expect_err("a NEW one-sided link must refuse");
        let msg = err.to_string();
        assert!(
            msg.contains("one-sided-link rule"),
            "the refusal must be the link arm: {msg}"
        );
        assert!(msg.contains("nothing was written"), "{msg}");
        assert!(
            msg.contains("editor.md") && msg.contains("target.md"),
            "BOTH ends of the edge must be named: {msg}"
        );
        assert!(
            msg.contains("reference-mem-topic"),
            "the refusal must name the verb that wires both ends: {msg}"
        );
        // No-leak: the pages' body fragments must not reach the refusal.
        assert!(!msg.contains("target body"), "page content leaked: {msg}");
        assert!(!msg.contains("plain body"), "page content leaked: {msg}");
        let on_disk = std::fs::read_to_string(&page).unwrap();
        assert_eq!(
            on_disk, "---\nname: editor\n---\nplain body\n",
            "a refused write leaves the page byte-identical"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// The LEGAL shapes must all pass the link arm: (a) the batch wires both ends itself
    /// (split's pair — the target page does not even exist yet, so only in-batch wiring can
    /// reciprocate); (b) the backlink already sits on disk (adding the SECOND end of a pair);
    /// (c) a PRE-EXISTING one-sided edge on disk is preserved, not frozen — repairable, never
    /// refused; (d) a cross-scope upward link is unreciprocated by law and never a candidate.
    #[test]
    fn reciprocal_preexisting_and_cross_scope_links_pass_the_link_arm() {
        let dir = std::env::temp_dir()
            .join(format!("memgrep_step6_legal-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();

        // (a) in-batch reciprocation over a NEW page: A links [[b]], B (not on disk) links [[a]].
        let a = dir.join("pair-a.md");
        let b = dir.join("pair-b.md");
        std::fs::write(&a, "---\nname: pair-a\n---\nplain\n").unwrap();
        prepare_batch_gated(
            &[
                (&a, "---\nname: pair-a\n---\nsee [[pair-b]]\n"),
                (&b, "---\nname: pair-b\n---\nsee [[pair-a]]\n"),
            ],
            &GatePolicy::default(),
        )
        .expect("a batch that wires BOTH ends must pass");

        // (b) the backlink is already on disk: adding the forward end completes the pair.
        let c = dir.join("fwd.md");
        let d = dir.join("back.md");
        std::fs::write(&c, "---\nname: fwd\n---\nplain\n").unwrap();
        std::fs::write(&d, "---\nname: back\n---\nsee [[fwd]]\n").unwrap();
        prepare_batch_gated(
            &[(&c, "---\nname: fwd\n---\nsee [[back]] now\n")],
            &GatePolicy::default(),
        )
        .expect("completing an existing disk pair must pass");

        // (c) a PRE-EXISTING one-sided edge survives an unrelated rewrite of its carrier page.
        let e = dir.join("legacy.md");
        let f = dir.join("distant.md");
        std::fs::write(&e, "---\nname: legacy\n---\nsee [[distant]]\n").unwrap();
        std::fs::write(&f, "---\nname: distant\n---\nno backlink here\n").unwrap();
        prepare_batch_gated(
            &[(&e, "---\nname: legacy\n---\nsee [[distant]]\nrewritten body\n")],
            &GatePolicy::default(),
        )
        .expect("a PRE-EXISTING one-sided edge must stay repairable, never frozen");

        // (d) cross-scope (LOCAL upward into a PROJECT-shaped path is not simulable here without
        // the real roots; instead pin the THIRD legal shape: a self-link is trivially reciprocal).
        let s = dir.join("self.md");
        std::fs::write(&s, "---\nname: self\n---\nplain\n").unwrap();
        prepare_batch_gated(
            &[(&s, "---\nname: self\n---\nsee [[self]]\n")],
            &GatePolicy::default(),
        )
        .expect("a self-link must pass (trivially reciprocal)");
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// The step-6 sha256 + auto-fix disclosure contract (step 6, part 1): after a gated write,
    /// STDERR carries the tab-separated `sha256\t<hash>\t<path>` line whose hash equals the
    /// bytes on disk — byte-identical to what `write_gate::check_base` verifies against, so a
    /// chained caller can pass the printed value straight back as `--base-sha256`. STDERR (not
    /// stdout) is itself load-bearing: the writing verbs' first stdout line IS an id, and a
    /// metadata line ahead of it broke ten CLI tests before the stream was moved.
    #[test]
    fn gated_write_prints_the_new_sha256_matching_the_landed_bytes() {
        let dir = std::env::temp_dir()
            .join(format!("memgrep_step6_sha-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let page = dir.join("hashed.md");
        std::fs::write(&page, "---\nname: hashed\n---\nplain body\n").unwrap();
        write_gated(&page, "---\nname: hashed\n---\nrewritten body\n")
            .expect("the clean rewrite must land");
        let landed = std::fs::read_to_string(&page).unwrap();
        // The disclosure function itself is best-effort; assert it succeeds on a real page. It
        // prints to stderr/stdout (untestable in-process without a pipe) — the hash-oracle
        // contract below pins the VALUE, and the CLI-level test in tests/cli.rs pins the LINE.
        post_commit_disclosure(&page, &landed).expect("disclosure must not fail a landed write");
        let disk_hash = crate::write_gate::sha256_of_file(&page).unwrap();
        // check_base ACCEPTS the on-disk hash — the exact promise the printed line makes.
        crate::write_gate::check_base(&page, &disk_hash)
            .expect("the printed hash's oracle (bytes on disk) must verify as a fresh base");
        assert!(landed.contains("rewritten body"), "{landed}");
        let _ = std::fs::remove_dir_all(&dir);
    }
}
