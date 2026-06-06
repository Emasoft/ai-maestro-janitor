//! End-to-end tests: run the real `memgrep` binary against a committed fixture and assert the
//! structural filters behave. Uses `CARGO_BIN_EXE_memgrep` (cargo points it at the built binary),
//! so no extra dev-deps and we exercise the actual CLI a user/agent would invoke.

use std::process::Command;

const FX: &str = "tests/fixtures/sample.md";

fn run(args: &[&str]) -> String {
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let out = Command::new(bin)
        .args(args)
        .output()
        .expect("failed to run memgrep");
    assert!(out.status.success(), "memgrep exited non-zero for {args:?}");
    String::from_utf8_lossy(&out.stdout).into_owned()
}

/// Run memgrep expecting a NON-zero exit (a usage/parse error). Returns nothing — only the failure
/// is asserted.
fn run_fail(args: &[&str]) {
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let out = Command::new(bin)
        .args(args)
        .output()
        .expect("failed to run memgrep");
    assert!(!out.status.success(), "memgrep should have failed for {args:?}");
}

#[test]
fn plain_pattern_finds_prose_and_code() {
    // 3 prose mentions + 1 inside the code block.
    assert_eq!(run(&["security", FX]).lines().count(), 4);
}

#[test]
fn no_code_drops_the_code_block_false_positive() {
    let o = run(&["security", "--no-code", FX]);
    assert_eq!(o.lines().count(), 3, "{o}");
    assert!(!o.contains("echo security"), "code line must be excluded:\n{o}");
}

#[test]
fn code_only_keeps_just_the_code_line() {
    let o = run(&["security", "--code", FX]);
    assert_eq!(o.lines().count(), 1);
    assert!(o.contains("echo security"));
}

#[test]
fn code_lang_filters_by_fence_language() {
    assert_eq!(run(&["security", "--code-lang", "python", FX]).lines().count(), 0);
    assert_eq!(run(&["security", "--code-lang", "bash", FX]).lines().count(), 1);
}

#[test]
fn in_section_scopes_to_chapter_and_subsections() {
    let o = run(&["security", "--no-code", "--in", "Requirements", FX]);
    assert_eq!(o.lines().count(), 1, "{o}");
    assert!(o.contains("requirements discuss security"));
}

#[test]
fn heading_only_lists_all_headings() {
    assert_eq!(run(&["--heading", FX]).lines().count(), 4);
}

#[test]
fn heading_with_positional_regex_matches_heading_text() {
    let o = run(&["Backend", "--heading", FX]);
    assert_eq!(o.lines().count(), 1);
    assert!(o.contains("# 2 Backend"));
}

#[test]
fn level_filter_restricts_to_that_heading_level() {
    assert_eq!(run(&["--heading", "--level", "2", FX]).lines().count(), 2);
    assert_eq!(run(&["--heading", "--level", "1", FX]).lines().count(), 2);
    // lenient range forms
    assert_eq!(run(&["--heading", "--level", ">=2", FX]).lines().count(), 2);
}

#[test]
fn count_and_files_only_modes() {
    assert_eq!(run(&["-c", "security", "--no-code", FX]).trim(), format!("{FX}:3"));
    assert_eq!(run(&["-l", "security", FX]).trim(), FX);
}

const FXFM: &str = "tests/fixtures/sample_fm.md";

#[test]
fn num_prefix_matches_subtree() {
    // headings: [1] [1,2] [1,3] [2]; prefix `1` ⟹ [1],[1,2],[1,3] = 3 headings.
    assert_eq!(run(&["--heading", "--num", "1", FX]).lines().count(), 3);
}

#[test]
fn num_glob_matches_one_level() {
    // `1.*` ⟹ exactly-2-component numbers under 1 = [1,2],[1,3] = 2 headings.
    assert_eq!(run(&["--heading", "--num", "1.*", FX]).lines().count(), 2);
}

#[test]
fn num_range_compares_as_version_tuples() {
    // `>=2` ⟹ only [2] (since [1,2] and [1,3] are < [2]) = 1 heading.
    assert_eq!(run(&["--heading", "--num", ">=2", FX]).lines().count(), 1);
}

#[test]
fn depth_caps_numbering_components() {
    // prefix `1` + depth 1 ⟹ only [1] (1 component); [1,2]/[1,3] have 2 = excluded.
    assert_eq!(run(&["--heading", "--num", "1", "--depth", "1", FX]).lines().count(), 1);
}

#[test]
fn num_scopes_content_search() {
    // "security" inside section 1.2, excluding code, = the one prose line.
    let o = run(&["security", "--no-code", "--num", "1.2", FX]);
    assert_eq!(o.lines().count(), 1, "{o}");
    assert!(o.contains("requirements discuss security"));
}

#[test]
fn fm_field_gates_the_file() {
    assert_eq!(run(&["widget", "--fm", "tags=security", FXFM]).lines().count(), 1);
    assert_eq!(run(&["widget", "--fm", "status=dev", FXFM]).lines().count(), 1);
    // a frontmatter field that does not match ⟹ file skipped entirely.
    assert_eq!(run(&["widget", "--fm", "tags=nope", FXFM]).lines().count(), 0);
    // a file lacking the required frontmatter field is excluded.
    assert_eq!(run(&["security", "--fm", "tags=x", FX]).lines().count(), 0);
}

const FXIN: &str = "tests/fixtures/sample_inline.md";

#[test]
fn emphasis_scopes_regex_to_markup() {
    assert_eq!(run(&["--bold", "security", FXIN]).lines().count(), 1);
    // "note" is italic, not bold ⟹ --bold finds nothing.
    assert_eq!(run(&["--bold", "note", FXIN]).lines().count(), 0);
    assert_eq!(run(&["--italic", "note", FXIN]).lines().count(), 1);
    assert_eq!(run(&["--strike", "struck", FXIN]).lines().count(), 1);
    assert_eq!(run(&["--code-span", "blob", FXIN]).lines().count(), 1);
}

#[test]
fn class_keys_or_and_and() {
    assert_eq!(run(&["--class", "security", FXIN]).lines().count(), 1);
    assert_eq!(run(&["--class", "backend", FXIN]).lines().count(), 1);
    assert_eq!(run(&["--class", "nope", FXIN]).lines().count(), 0);
    assert_eq!(run(&["--class-all", "security,backend", FXIN]).lines().count(), 1);
    assert_eq!(run(&["--class-all", "security,missing", FXIN]).lines().count(), 0);
}

#[test]
fn span_class_name_filter() {
    assert_eq!(run(&["--span-class", "note", FXIN]).lines().count(), 1);
    assert_eq!(run(&["--span-class", "mem", FXIN]).lines().count(), 1);
    assert_eq!(run(&["--span-class", "zzz", FXIN]).lines().count(), 0);
}

#[test]
fn list_scope_include_exclude() {
    assert_eq!(run(&["--list", FXIN]).lines().count(), 2); // two bullet lines
    assert_eq!(run(&["widget", "--list", FXIN]).lines().count(), 1);
    assert_eq!(run(&["widget", "--no-list", FXIN]).lines().count(), 0);
}

const FXGFM: &str = "tests/fixtures/sample_gfm.md";

#[test]
fn node_kinds_scope_and_exclude() {
    assert_eq!(run(&["security", "--table", FXGFM]).lines().count(), 1);
    // "security" outside tables = the link line; the table cell is excluded.
    let o = run(&["security", "--no-node", "table", FXGFM]);
    assert_eq!(o.lines().count(), 1, "{o}");
    assert!(o.contains("link to security"));
    assert_eq!(run(&["widget", "--quote", FXGFM]).lines().count(), 1);
    assert_eq!(run(&["widget", "--node", "table,quote", FXGFM]).lines().count(), 1);
}

#[test]
fn node_kind_structural_only_counts() {
    let count = |args: &[&str]| -> usize { run(args).lines().count() };
    assert_eq!(count(&["--math", FXGFM]), 1);
    assert_eq!(count(&["--url", FXGFM]), 1);
    assert_eq!(count(&["--image", FXGFM]), 1);
    assert_eq!(count(&["--footnote", FXGFM]), 2); // reference + definition
    assert_eq!(count(&["--svg", FXGFM]), 1);
}

const FXFACTS: &str = "tests/fixtures/sample_facts.md";

#[test]
fn fact_filters_by_category_session_and_time() {
    assert_eq!(run(&["fact", "--cat", "security", FXFACTS]).lines().count(), 2);
    assert_eq!(run(&["fact", "--cat", "db", FXFACTS]).lines().count(), 1);
    assert_eq!(run(&["fact", "--session", "bbbb2222", FXFACTS]).lines().count(), 1);
    // --since excludes the 2026-06-05 fact.
    assert_eq!(run(&["fact", "--since", "2026-06-06", FXFACTS]).lines().count(), 2);
    // results are time-sorted (the 14:00 fact precedes the 18:00 one).
    let o = run(&["fact", "--session", "aaaa1111", FXFACTS]);
    let lines: Vec<&str> = o.lines().collect();
    assert!(lines[0].contains("14:00:00") && lines[1].contains("18:00:00"));
}

#[test]
fn links_broken_and_backlinks() {
    let a = "tests/fixtures/link_a.md";
    let b = "tests/fixtures/link_b.md";
    // a → nope.md is the only broken link (a→b and b→a resolve).
    let broken = run(&["links", "--broken", a, b]);
    assert_eq!(broken.lines().count(), 1, "{broken}");
    assert!(broken.contains("nope.md"));
    // backlinks of link_b = link_a (which links to it).
    let from = run(&["links", "--from", "link_b", a, b]);
    assert!(from.contains("link_a.md"), "{from}");
}

#[test]
fn wikilink_resolves_trdd_id8_alias() {
    // A `[[TRDD-abcd1234]]` wikilink must resolve to the file `TRDD-<ts>-abcd1234-<slug>.md`
    // (via the id8 alias) rather than missing on the long file stem and reading as broken.
    let tgt = "tests/fixtures/TRDD-20260101_000000+0000-abcd1234-target.md";
    let refr = "tests/fixtures/trdd_ref.md";
    let to = run(&["links", "--to", "trdd_ref", refr, tgt]);
    assert!(to.contains("abcd1234-target.md"), "wikilink should resolve to the TRDD file:\n{to}");
    assert!(!to.contains("BROKEN"), "{to}");
    assert!(run(&["links", "--broken", refr, tgt]).trim().is_empty(), "no link should be broken");
}

#[test]
fn where_link_semijoin_to_from_and_join() {
    // The SQL model: `links-to`/`linked-from` resolve a FILE SET (the subquery), then AND with the
    // content search is the JOIN. trdd_ref links to [[TRDD-abcd1234]] (resolved via the id8 alias).
    let tgt = "tests/fixtures/TRDD-20260101_000000+0000-abcd1234-target.md";
    let refr = "tests/fixtures/trdd_ref.md";
    // files that link TO the abcd1234 note ⟹ trdd_ref.
    assert_eq!(run(&["-l", "--where", r#"links-to "abcd1234""#, refr, tgt]).trim(), refr);
    // files linked FROM trdd_ref (i.e. that note's out-links) ⟹ the abcd1234 target.
    assert_eq!(run(&["-l", "--where", r#"linked-from "trdd_ref""#, refr, tgt]).trim(), tgt);
    // the JOIN — content search restricted to the linking file.
    let j = run(&["--where", r#"links-to "abcd1234" and text "rationale""#, refr, tgt]);
    assert_eq!(j.lines().count(), 1, "{j}");
    assert!(j.contains("trdd_ref.md"));
    // a needle that matches no note ⟹ empty set ⟹ no file qualifies.
    assert_eq!(run(&["--where", r#"links-to "nonesuch""#, refr, tgt]).lines().count(), 0);
}

#[test]
fn index_emits_title_and_toc() {
    let o = run(&["index", "tests/fixtures/sample.md"]);
    assert!(o.contains("1 Intro"), "title missing:\n{o}");
    assert!(o.contains("toc:"), "toc missing:\n{o}");
}

#[test]
fn binary_file_is_skipped_without_crashing() {
    // Point memgrep at its own binary (full of NUL bytes); it must skip, not crash.
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let out = Command::new(bin).args(["the", bin]).output().unwrap();
    assert!(out.status.success(), "must not crash on a binary file");
    assert!(out.stdout.is_empty(), "binary file should yield no matches");
}

// ── Phase 6b: the --where boolean DSL (end-to-end through the real binary) ──

#[test]
fn where_and_not_equals_flat_no_code() {
    // `text "security" and not code` reproduces `security --no-code` (3 prose lines)…
    assert_eq!(run(&["--where", r#"text "security" and not code"#, FX]).lines().count(), 3);
    // …and `and code` keeps only the in-code line.
    assert_eq!(run(&["--where", r#"text "security" and code"#, FX]).lines().count(), 1);
}

#[test]
fn where_or_unions_patterns() {
    // "security" is on 4 lines, "widget" on 0 ⟹ their union is 4. (A flat query cannot OR these.)
    assert_eq!(run(&["--where", r#"text "security" or text "widget""#, FX]).lines().count(), 4);
}

#[test]
fn where_grouping_changes_precedence() {
    // `(a or b) and c`: lines matching (security or nothing) AND in-code = the single code line.
    let o = run(&["--where", r#"(text "security" or text "widget") and code"#, FX]);
    assert_eq!(o.lines().count(), 1, "{o}");
    assert!(o.contains("echo security"));
    // without grouping, `a or (b and c)` = security-anywhere(4) OR (widget AND code)(0) = 4.
    assert_eq!(
        run(&["--where", r#"text "security" or text "widget" and code"#, FX]).lines().count(),
        4
    );
}

#[test]
fn where_structural_and_numbering() {
    // headings whose section number is >= 2 ⟹ just `# 2 Backend`.
    let o = run(&["--where", r#"heading and num ">=2""#, FX]);
    assert_eq!(o.lines().count(), 1, "{o}");
    assert!(o.contains("# 2 Backend"));
}

#[test]
fn where_fm_predicate_composes() {
    // sample_fm.md: frontmatter status=dev, tags=[security, oauth]; body mentions "widget".
    assert_eq!(run(&["--where", r#"fm.status "dev" and text "widget""#, FXFM]).lines().count(), 1);
    // fm is a per-line-constant gate: with -l a matching file is listed, a non-matching one isn't.
    assert_eq!(run(&["-l", "--where", r#"fm.status "dev""#, FXFM]).trim(), FXFM);
    assert_eq!(run(&["--where", r#"fm.tags "nope""#, FXFM]).lines().count(), 0);
}

#[test]
fn where_file_globs_and_emphasis() {
    // name/path globs gate the file; the emphasis predicate scopes within it.
    assert_eq!(run(&["--where", r#"name "*.md" and bold "security""#, FXIN]).lines().count(), 1);
    assert_eq!(run(&["--where", r#"name "*.rs" and bold "security""#, FXIN]).lines().count(), 0);
    assert_eq!(
        run(&["--where", r#"path "**/sample_inline.md" and span-class "note""#, FXIN]).lines().count(),
        1
    );
}

#[test]
fn where_rejects_combining_with_flags() {
    // --where is the whole query; combining it with a filter flag or -e is a hard error (a stray
    // positional, by contrast, is treated as a PATH in --where mode, not a conflict).
    run_fail(&["--where", r#"code"#, "--no-code", FX]);
    run_fail(&["--where", r#"code"#, "-e", "x", FX]);
}

#[test]
fn where_parse_errors_are_clean_failures() {
    run_fail(&["--where", r#"(text "a""#, FX]); // unbalanced paren
    run_fail(&["--where", "boguspred \"x\"", FX]); // unknown predicate
}
