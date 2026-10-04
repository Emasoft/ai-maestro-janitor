//! Issue-code registry types (TRDD-DSN035UN). FROZEN: rules_gen.rs only emits data rows into this shape.
#![allow(dead_code)]
use crate::memory::Severity;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Fix {
    Safe,
    Unsafe,
    None,
}
pub(crate) type FixerFn = fn(&std::path::Path, &str) -> Option<String>;
#[derive(Debug)]
pub(crate) struct Rule {
    /// FAMILY-NNN
    pub(crate) code: &'static str,
    /// kebab name, e.g. atom-no-ocd
    pub(crate) name: &'static str,
    pub(crate) family: &'static str,
    pub(crate) sev: Severity,
    pub(crate) fix: Fix,
    pub(crate) gate_floor: bool,
    pub(crate) summary: &'static str,
}
pub(crate) fn rule_by_name(name: &str) -> Option<&'static Rule> {
    crate::rules_gen::RULES.iter().find(|r| r.name == name)
}
pub(crate) fn rule_by_code(code: &str) -> Option<&'static Rule> {
    crate::rules_gen::RULES.iter().find(|r| r.code == code)
}
