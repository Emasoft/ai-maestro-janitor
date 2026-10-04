//! Fix engine (TRDD-I23YCEW7): pure fixed-point driver over registry fixers.
#![allow(dead_code)]
use crate::lint_rules::{Fix, FixerFn, Rule};
use std::path::Path;

/// Round cap; same value as `PUBLISH_GLOBALLY_MAX_ITERATIONS` (memory.rs:2761), the measured
/// fixed-point precedent: a fixer set not converging in 5 rounds is a fixer bug, not a page problem.
pub(crate) const MAX_ROUNDS: usize = 5;

pub(crate) struct FixOutcome {
    pub(crate) text: String,
    /// Rule codes that changed the text, first-applied order, deduped.
    pub(crate) fixed: Vec<&'static str>,
    pub(crate) rounds: usize,
    pub(crate) converged: bool,
}

pub(crate) fn fix_page(
    path: &Path,
    text: &str,
    fixers: &[(&'static Rule, FixerFn)],
    allow_unsafe: bool,
) -> FixOutcome {
    let mut cur = text.to_string();
    let mut fixed: Vec<&'static str> = Vec::new();
    let mut rounds = 0;
    let mut converged = false;
    while rounds < MAX_ROUNDS {
        rounds += 1;
        let mut changed = false;
        for (rule, f) in fixers {
            let eligible = match rule.fix {
                Fix::Safe => true,
                Fix::Unsafe => allow_unsafe,
                Fix::None => false,
            };
            if !eligible {
                continue;
            }
            if let Some(t) = f(path, &cur)
                && t != cur {
                    cur = t;
                    changed = true;
                    if !fixed.contains(&rule.code) {
                        fixed.push(rule.code);
                    }
                }
        }
        if !changed {
            converged = true;
            break;
        }
    }
    FixOutcome { text: cur, fixed, rounds, converged }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::memory::Severity;

    const fn rule(code: &'static str, fix: Fix) -> Rule {
        Rule { code, name: "t", family: "T", sev: Severity::Info, fix, gate_floor: false, summary: "" }
    }
    static SAFE_A: Rule = rule("T-001", Fix::Safe);
    static SAFE_B: Rule = rule("T-002", Fix::Safe);
    static UNSAFE: Rule = rule("T-003", Fix::Unsafe);
    static NOFIX: Rule = rule("T-004", Fix::None);

    fn a_to_b(_: &Path, t: &str) -> Option<String> {
        t.contains('a').then(|| t.replace('a', "b"))
    }
    fn b_to_c(_: &Path, t: &str) -> Option<String> {
        t.contains('b').then(|| t.replace('b', "c"))
    }
    fn flip_x(_: &Path, t: &str) -> Option<String> {
        Some(t.replace('x', "y"))
    }
    fn flip_y(_: &Path, t: &str) -> Option<String> {
        Some(t.replace('y', "x"))
    }
    fn identity(_: &Path, t: &str) -> Option<String> {
        Some(t.to_string())
    }
    fn p() -> &'static Path {
        Path::new("p.md")
    }

    #[test]
    fn single_fix_converges_in_two_rounds() {
        let o = fix_page(p(), "a", &[(&SAFE_A, a_to_b)], false);
        assert_eq!((o.text.as_str(), o.rounds, o.converged), ("b", 2, true));
        assert_eq!(o.fixed, vec!["T-001"]);
    }

    #[test]
    fn interacting_fixers_converge() {
        // listed in reverse order so the second round is needed for the chain a->b->c
        let o = fix_page(p(), "a", &[(&SAFE_B, b_to_c), (&SAFE_A, a_to_b)], false);
        assert_eq!(o.text, "c");
        assert!(o.converged);
        assert_eq!(o.fixed, vec!["T-001", "T-002"]);
    }

    #[test]
    fn oscillating_pair_stops_at_cap() {
        let o = fix_page(p(), "x", &[(&SAFE_A, flip_x), (&SAFE_B, flip_y)], false);
        assert_eq!(o.rounds, MAX_ROUNDS);
        assert!(!o.converged);
    }

    #[test]
    fn unsafe_skipped_unless_allowed() {
        let off = fix_page(p(), "a", &[(&UNSAFE, a_to_b)], false);
        assert_eq!(off.text, "a");
        assert!(off.fixed.is_empty() && off.converged);
        let on = fix_page(p(), "a", &[(&UNSAFE, a_to_b)], true);
        assert_eq!(on.text, "b");
        assert_eq!(on.fixed, vec!["T-003"]);
    }

    #[test]
    fn nofix_never_applied() {
        let o = fix_page(p(), "a", &[(&NOFIX, a_to_b)], true);
        assert_eq!(o.text, "a");
        assert!(o.fixed.is_empty());
    }

    #[test]
    fn identical_output_not_counted() {
        let o = fix_page(p(), "a", &[(&SAFE_A, identity)], false);
        assert!(o.fixed.is_empty());
        assert_eq!((o.rounds, o.converged), (1, true));
    }

    #[test]
    fn fixed_codes_deduped_and_ordered() {
        let o = fix_page(p(), "a", &[(&SAFE_B, b_to_c), (&SAFE_A, a_to_b)], false);
        assert_eq!(o.fixed, vec!["T-001", "T-002"]);
        let o = fix_page(p(), "x", &[(&SAFE_A, flip_x), (&SAFE_B, flip_y)], false);
        assert_eq!(o.fixed, vec!["T-001", "T-002"]);
    }
}
