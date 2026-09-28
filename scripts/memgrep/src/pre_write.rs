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

use crate::memory::{atomic_write_page, lint_page_text, write_gate_blocks};
use anyhow::Result;
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

/// The gated write: `prepare` the proposed bytes, then — and only then — commit them through the
/// existing atomic primitive. This is the ONE entry a wired verb calls in place of a bare
/// `atomic_write_page`; every verb not yet wired keeps calling `atomic_write_page` directly and
/// is therefore UNGATED, which is the reviewed sequencing (one verb per commit), not an oversight.
pub(crate) fn write_gated(dest: &Path, proposed: &str) -> Result<()> {
    prepare(dest, proposed)?;
    // commit — `atomic_write_page` keeps its own control-byte refusal as the last line of
    // defence and owns the publish-globally convergence + symlink reconciliation exactly as it
    // does for every ungated caller today.
    atomic_write_page(dest, proposed)
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
}
