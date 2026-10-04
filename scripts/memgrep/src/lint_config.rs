//! `.janitor.toml` lint configuration: discovery, loading, CLI precedence, selector matching (TRDD-DSN035UN C11).
#![allow(dead_code)]
use crate::lint_rules::{Fix, Rule};
use anyhow::{Context, Result};
use globset::Glob;
use serde::Deserialize;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct LintConfig {
    pub(crate) select: Vec<String>,
    pub(crate) extend_select: Vec<String>,
    pub(crate) ignore: Vec<String>,
    pub(crate) fixable: Vec<String>,
    pub(crate) unfixable: Vec<String>,
    pub(crate) unsafe_fixes: bool,
    /// (glob pattern, selectors) in file order.
    pub(crate) per_file_ignores: Vec<(String, Vec<String>)>,
    pub(crate) recall_budget_ms: Option<u64>,
    pub(crate) lint_budget_ms: Option<u64>,
    pub(crate) source: Option<PathBuf>,
}

impl Default for LintConfig {
    fn default() -> Self {
        Self {
            select: vec!["ALL".into()],
            extend_select: vec![],
            ignore: vec![],
            fixable: vec!["ALL".into()],
            unfixable: vec![],
            unsafe_fixes: false,
            per_file_ignores: vec![],
            recall_budget_ms: None,
            lint_budget_ms: None,
            source: None,
        }
    }
}

#[derive(Default)]
pub(crate) struct CliOverrides {
    pub(crate) select: Option<Vec<String>>,
    pub(crate) extend_select: Option<Vec<String>>,
    pub(crate) ignore: Option<Vec<String>>,
    pub(crate) fixable: Option<Vec<String>>,
    pub(crate) unfixable: Option<Vec<String>>,
    pub(crate) unsafe_fixes: Option<bool>,
    pub(crate) recall_budget_ms: Option<u64>,
    pub(crate) lint_budget_ms: Option<u64>,
}

// Unknown keys must fail (like ruff) so a typo never silently disables a rule; the file's other
// tables (e.g. janitor's [[suppress]]) are deliberately not modelled here.
#[derive(Deserialize, Default)]
#[serde(rename_all = "kebab-case", deny_unknown_fields)]
struct RawLint {
    select: Option<Vec<String>>,
    extend_select: Option<Vec<String>>,
    ignore: Option<Vec<String>>,
    fixable: Option<Vec<String>>,
    unfixable: Option<Vec<String>>,
    unsafe_fixes: Option<bool>,
    per_file_ignores: Option<std::collections::BTreeMap<String, Vec<String>>>,
}

#[derive(Deserialize, Default)]
#[serde(rename_all = "kebab-case", deny_unknown_fields)]
struct RawPerf {
    recall_budget_ms: Option<u64>,
    lint_budget_ms: Option<u64>,
}

#[derive(Deserialize)]
struct RawFile {
    lint: Option<RawLint>,
    perf: Option<RawPerf>,
}

/// Nearest `.janitor.toml` at or above `start` (a file or a directory).
pub(crate) fn discover(start: &Path) -> Option<PathBuf> {
    let mut cur = if start.is_dir() { Some(start) } else { start.parent() };
    while let Some(d) = cur {
        let p = d.join(".janitor.toml");
        if p.is_file() {
            return Some(p);
        }
        cur = d.parent();
    }
    None
}

pub(crate) fn load(path: &Path) -> Result<LintConfig> {
    let text = std::fs::read_to_string(path).with_context(|| format!("reading {}", path.display()))?;
    let raw: RawFile = toml::from_str(&text).with_context(|| format!("parsing {}", path.display()))?;
    let mut c = LintConfig { source: Some(path.to_path_buf()), ..Default::default() };
    if let Some(l) = raw.lint {
        if let Some(v) = l.select { c.select = v; }
        if let Some(v) = l.extend_select { c.extend_select = v; }
        if let Some(v) = l.ignore { c.ignore = v; }
        if let Some(v) = l.fixable { c.fixable = v; }
        if let Some(v) = l.unfixable { c.unfixable = v; }
        if let Some(v) = l.unsafe_fixes { c.unsafe_fixes = v; }
        if let Some(m) = l.per_file_ignores {
            for (pat, sels) in m {
                Glob::new(&pat).with_context(|| format!("bad per-file-ignores glob {pat:?} in {}", path.display()))?;
                c.per_file_ignores.push((pat, sels));
            }
        }
    }
    if let Some(p) = raw.perf {
        c.recall_budget_ms = p.recall_budget_ms;
        c.lint_budget_ms = p.lint_budget_ms;
    }
    Ok(c)
}

/// Heartbeat-safe load: a malformed config yields defaults plus the error text (C21 reports it as
/// CONFIG-001) so a typo never silently stops all lint. Strict `load` is for explicit `--config`/`--isolated`.
pub(crate) fn load_lenient(path: &Path) -> (LintConfig, Option<String>) {
    match load(path) {
        Ok(c) => (c, None),
        Err(e) => (LintConfig { source: Some(path.to_path_buf()), ..Default::default() }, Some(format!("{e:#}"))),
    }
}

/// CLI over file over defaults; `extend-select` appends to whatever `select` resolved from the file.
pub(crate) fn resolve(cli: &CliOverrides, file: Option<LintConfig>) -> LintConfig {
    let mut c = file.unwrap_or_default();
    if let Some(v) = &cli.select { c.select = v.clone(); }
    if let Some(v) = &cli.extend_select { c.extend_select.extend(v.iter().cloned()); }
    if let Some(v) = &cli.ignore { c.ignore = v.clone(); }
    if let Some(v) = &cli.fixable { c.fixable = v.clone(); }
    if let Some(v) = &cli.unfixable { c.unfixable = v.clone(); }
    if let Some(v) = cli.unsafe_fixes { c.unsafe_fixes = v; }
    if cli.recall_budget_ms.is_some() { c.recall_budget_ms = cli.recall_budget_ms; }
    if cli.lint_budget_ms.is_some() { c.lint_budget_ms = cli.lint_budget_ms; }
    c
}

/// "ALL", a full code, a family, any code prefix, or the kebab name.
pub(crate) fn selector_matches(sel: &str, rule: &Rule) -> bool {
    sel == "ALL" || rule.code.starts_with(sel) || rule.name == sel
}

fn any_matches(sels: &[String], rule: &Rule) -> bool {
    sels.iter().any(|s| selector_matches(s, rule))
}

pub(crate) fn is_enabled(cfg: &LintConfig, rule: &Rule, page: &Path) -> bool {
    if !(any_matches(&cfg.select, rule) || any_matches(&cfg.extend_select, rule)) || any_matches(&cfg.ignore, rule) {
        return false;
    }
    !cfg.per_file_ignores.iter().any(|(pat, sels)| {
        // Patterns were validated in load(); a hand-built config with a bad glob simply never matches.
        Glob::new(pat).is_ok_and(|g| g.compile_matcher().is_match(page)) && any_matches(sels, rule)
    })
}

pub(crate) fn is_fixable(cfg: &LintConfig, rule: &Rule) -> bool {
    match rule.fix {
        Fix::None => return false,
        Fix::Unsafe if !cfg.unsafe_fixes => return false,
        _ => {}
    }
    any_matches(&cfg.fixable, rule) && !any_matches(&cfg.unfixable, rule)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::memory::Severity;

    fn rule(code: &'static str, name: &'static str, fix: Fix) -> Rule {
        Rule { code, name, family: code.split('-').next().unwrap(), sev: Severity::Warn, fix, gate_floor: false, summary: "" }
    }
    fn tmp(label: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("memgrep-lintcfg-{label}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }
    fn s(v: &[&str]) -> Vec<String> { v.iter().map(|x| x.to_string()).collect() }

    #[test]
    fn discovery_nearest_ancestor() {
        let root = tmp("disc");
        let sub = root.join("a/b");
        std::fs::create_dir_all(&sub).unwrap();
        std::fs::write(root.join(".janitor.toml"), "").unwrap();
        std::fs::write(root.join("a/.janitor.toml"), "").unwrap();
        std::fs::write(sub.join("p.md"), "").unwrap();
        assert_eq!(discover(&sub.join("p.md")), Some(root.join("a/.janitor.toml")));
        assert_eq!(discover(&root), Some(root.join(".janitor.toml")));
    }

    #[test]
    fn load_parses_and_defaults() {
        let d = tmp("load");
        let f = d.join(".janitor.toml");
        std::fs::write(&f, "[[suppress]]\nx=1\n").unwrap();
        let c = load(&f).unwrap();
        assert_eq!(c.select, s(&["ALL"]));
        std::fs::write(&f, "[lint]\nselect=[\"WM\"]\nunsafe-fixes=true\n[lint.per-file-ignores]\n\"*/archive/*.md\"=[\"WMLESS\"]\n[perf]\nrecall-budget-ms=5\nlint-budget-ms=7\n").unwrap();
        let c = load(&f).unwrap();
        assert_eq!(c.select, s(&["WM"]));
        assert!(c.unsafe_fixes);
        assert_eq!(c.per_file_ignores, vec![("*/archive/*.md".to_string(), s(&["WMLESS"]))]);
        assert_eq!((c.recall_budget_ms, c.lint_budget_ms), (Some(5), Some(7)));
    }

    #[test]
    fn unknown_key_errors() {
        let d = tmp("unk");
        let f = d.join(".janitor.toml");
        std::fs::write(&f, "[lint]\nselct=[\"WM\"]\n").unwrap();
        assert!(load(&f).is_err());
    }

    #[test]
        fn lenient_returns_defaults_and_error() {
            let d = tmp("len");
            let f = d.join(".janitor.toml");
            std::fs::write(&f, "[lint]\nselct=[\"WM\"]\n").unwrap();
            let (c, e) = load_lenient(&f);
            assert_eq!(c.select, s(&["ALL"]));
            assert!(e.is_some());
            std::fs::write(&f, "[lint]\nselect=[\"WM\"]\n").unwrap();
            let (c, e) = load_lenient(&f);
            assert_eq!(c.select, s(&["WM"]));
            assert!(e.is_none());
        }

    #[test]
    fn precedence_and_extend() {
        let file = LintConfig { select: s(&["WM"]), extend_select: s(&["HOOK"]), ..Default::default() };
        let cli = CliOverrides { select: Some(s(&["MGPERF"])), extend_select: Some(s(&["X"])), ..Default::default() };
        let c = resolve(&cli, Some(file.clone()));
        assert_eq!(c.select, s(&["MGPERF"]));
        assert_eq!(c.extend_select, s(&["HOOK", "X"]));
        assert_eq!(resolve(&CliOverrides::default(), Some(file.clone())), file);
        assert_eq!(resolve(&CliOverrides::default(), None).select, s(&["ALL"]));
    }

    #[test]
    fn selectors() {
        let r = rule("WMATOM-010", "atom-unquoted-desc", Fix::Safe);
        for sel in ["ALL", "WMATOM-010", "WMATOM", "WM", "atom-unquoted-desc"] {
            assert!(selector_matches(sel, &r), "{sel}");
        }
        assert!(!selector_matches("HOOK", &r));
        assert!(!selector_matches("atom-unquoted", &r));
    }

    #[test]
    fn enabled_ignore_and_per_file() {
        let r = rule("WMLESS-001", "less-x", Fix::Safe);
        let mut c = LintConfig { select: s(&["WM"]), ..Default::default() };
        assert!(is_enabled(&c, &r, Path::new("/m/a.md")));
        c.ignore = s(&["WMLESS-001"]);
        assert!(!is_enabled(&c, &r, Path::new("/m/a.md")));
        c.ignore = vec![];
        c.select = s(&["HOOK"]);
        assert!(!is_enabled(&c, &r, Path::new("/m/a.md")));
        c.extend_select = s(&["WMLESS"]);
        assert!(is_enabled(&c, &r, Path::new("/m/a.md")));
        c.per_file_ignores = vec![("*/archive/*.md".into(), s(&["WMLESS"]))];
        assert!(!is_enabled(&c, &r, Path::new("/m/archive/a.md")));
        assert!(is_enabled(&c, &r, Path::new("/m/other/a.md")));
    }

    #[test]
    fn fixable_gating() {
        let safe = rule("WM-001", "a", Fix::Safe);
        let uns = rule("WM-002", "b", Fix::Unsafe);
        let nof = rule("WM-003", "c", Fix::None);
        let mut c = LintConfig::default();
        assert!(is_fixable(&c, &safe));
        assert!(!is_fixable(&c, &uns));
        assert!(!is_fixable(&c, &nof));
        c.unsafe_fixes = true;
        assert!(is_fixable(&c, &uns));
        c.unfixable = s(&["WM-002"]);
        assert!(!is_fixable(&c, &uns));
        c.fixable = s(&["HOOK"]);
        assert!(!is_fixable(&c, &safe));
    }
}
