#![allow(dead_code)]
pub(crate) mod notes_section;
pub(crate) mod quote_desc;
pub(crate) mod dedup_keywords;
pub(crate) mod dedup_phrases;
pub(crate) mod superseded_move;
pub(crate) mod unused_noqa;

pub(crate) fn fixer_for(name: &str) -> Option<crate::lint_rules::FixerFn> {
    match name {
        "page-no-notes-section" => Some(notes_section::fix),
        "atom-unquoted-desc" => Some(quote_desc::fix),
        "atom-keywords-duplicated" => Some(dedup_keywords::fix),
        "page-description-duplicated-phrases" => Some(dedup_phrases::fix),
        "superseded-atom-above-delimiter" | "superseded-atom-no-delimiter-heading" => Some(superseded_move::fix),
        "unused-noqa" => Some(unused_noqa::fix),
        _ => None,
    }
}

// Why: the lint `--apply-fixes` pass (TRDD-JD2QR5SQ) feeds fix_page the full fixer set, in rule-table order.
pub(crate) fn registered() -> Vec<(&'static crate::lint_rules::Rule, crate::lint_rules::FixerFn)> {
    crate::rules_gen::RULES.iter().filter_map(|r| fixer_for(r.name).map(|f| (r, f))).collect()
}

// Why: `--apply-fixes` records a refused fix here once, so repeated runs do not grow the ledger.
// Limits: no lock of its own (the caller holds the scope lock).
// Limits: page and reason are flattened to one line (\n, \r, \t become a space) so each call writes one two-column line.
pub(crate) fn record_unfixed(ledger: &std::path::Path, page: &str, reason: &str) -> std::io::Result<bool> {
    use std::io::Write;
    let flat = |s: &str| s.replace(['\n', '\r', '\t'], " ");
    let entry = format!("{}\t{}", flat(page), flat(reason));
    // Bytes + lossy compare: invalid UTF-8 in the ledger must not make every run append again.
    let existing = match std::fs::read(ledger) {
        Ok(b) => String::from_utf8_lossy(&b).into_owned(),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => String::new(),
        Err(e) => return Err(e),
    };
    if existing.lines().any(|l| l == entry) {
        return Ok(false);
    }
    if let Some(p) = ledger.parent() {
        std::fs::create_dir_all(p)?;
    }
    // A ledger lacking a final newline would otherwise get this entry glued onto its last line.
    let sep = if existing.is_empty() || existing.ends_with('\n') { "" } else { "\n" };
    std::fs::OpenOptions::new().create(true).append(true).open(ledger)?.write_all(format!("{sep}{entry}\n").as_bytes())?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lint_rules::Fix;

    #[test]
    fn registered_covers_every_safe_rule() {
        let got: std::collections::BTreeSet<&str> = registered().iter().map(|(r, _)| r.code).collect();
        let want: std::collections::BTreeSet<&str> =
            crate::rules_gen::RULES.iter().filter(|r| r.fix == Fix::Safe).map(|r| r.code).collect();
        assert_eq!(got, want);
    }

    #[test]
    fn record_unfixed_appends_once_per_page_and_reason() {
        let dir = std::env::temp_dir().join(format!("memgrep-unfixed-appends-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let ledger = dir.join("sub").join("ledger.tsv");
        assert!(record_unfixed(&ledger, "a.md", "r1").unwrap());
        assert!(!record_unfixed(&ledger, "a.md", "r1").unwrap());
        assert!(record_unfixed(&ledger, "a.md", "r2").unwrap());
        assert!(record_unfixed(&ledger, "b.md", "r1").unwrap());
        assert!(record_unfixed(&ledger, "a", "r1").unwrap());
        assert_eq!(std::fs::read_to_string(&ledger).unwrap(), "a.md\tr1\na.md\tr2\nb.md\tr1\na\tr1\n");
        // Invalid UTF-8 in the ledger must not make every run append again.
        let bad = dir.join("bad.tsv");
        std::fs::write(&bad, b"\xff\xfe junk\na.md\tr1\n").unwrap();
        assert!(!record_unfixed(&bad, "a.md", "r1").unwrap());
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn record_unfixed_flattens_multiline_reason_and_stays_once_only() {
        let dir = std::env::temp_dir().join(format!("memgrep-unfixed-flatten-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let ledger = dir.join("ledger.tsv");
        assert!(record_unfixed(&ledger, "p.md", "gate: A\nB\tC").unwrap());
        assert!(!record_unfixed(&ledger, "p.md", "gate: A\nB\tC").unwrap());
        assert_eq!(std::fs::read_to_string(&ledger).unwrap(), "p.md\tgate: A B C\n");
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn record_unfixed_handles_ledger_without_final_newline() {
        let dir = std::env::temp_dir().join(format!("memgrep-unfixed-nonl-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let ledger = dir.join("ledger.tsv");
        std::fs::write(&ledger, "x.md\tr0").unwrap();
        assert!(record_unfixed(&ledger, "y.md", "r1").unwrap());
        assert_eq!(std::fs::read_to_string(&ledger).unwrap(), "x.md\tr0\ny.md\tr1\n");
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
