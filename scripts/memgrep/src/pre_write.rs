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
use std::path::Path;

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
    for (sev, _p, line, m, code) in &blocked {
        msg.push_str(&format!(
            "\n  {} {}:{line} [{code}] — {m}",
            sev.label(),
            dest.display()
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
    /// Skip the id-REUSE (changed-body) check while still enforcing the DROP check. Only
    /// `update-mem-atom`'s body-rewrite path sets it: rewriting a body under a SURVIVING id is
    /// that verb's own contract (the brief's reconciliation of the reuse rule with wave 1).
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

/// The batch half of the gate (TRDD-XI10BA5D A2 step 5 wave 2): prepare EVERY page's proposed
/// bytes (lint floor per page, `prepare`) and run the id-set rule over the batch, BEFORE the
/// caller commits anything. A refusal anywhere means zero bytes written anywhere. The caller
/// then commits each page through `atomic_write_page` in ITS OWN order (merge/split/migrate own
/// recoverable-duplicate orderings and partial-failure messages), so the bytes each commit writes
/// are exactly the bytes this function certified.
pub(crate) fn prepare_batch_gated(writes: &[(&Path, &str)], policy: &GatePolicy) -> Result<()> {
    for (dest, proposed) in writes {
        prepare(dest, proposed)?;
    }
    let old: Vec<BTreeMap<String, String>> =
        writes.iter().map(|(p, _)| id_inventory(&read_for_inventory(p))).collect();
    let proposed_inv: Vec<BTreeMap<String, String>> =
        writes.iter().map(|(_, t)| id_inventory(t)).collect();
    enforce_id_rules(&old, &proposed_inv, policy)
}

/// A page's current on-disk text for inventory purposes. A page that does not exist yet
/// (`split-mem-topic`'s destination, `new-page`) inventories as EMPTY — the gate judges the
/// write's own blast radius, and a page not yet on disk cannot lose an id in it.
fn read_for_inventory(page: &Path) -> String {
    std::fs::read_to_string(page).unwrap_or_default()
}

/// The single-page gated write WITH the id-set rule (the gated form of `delete-mem-atom`'s
/// write), for callers whose batch is one page but whose verb legitimately retires ids.
pub(crate) fn write_gated_with(dest: &Path, proposed: &str, policy: &GatePolicy) -> Result<()> {
    prepare_batch_gated(&[(dest, proposed)], policy)?;
    // commit — `atomic_write_page` keeps its own control-byte refusal as the last line of
    // defence and owns the publish-globally convergence + symlink reconciliation exactly as it
    // does for every ungated caller today.
    atomic_write_page(dest, proposed)
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
            .map(|v| v.4)
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
}
