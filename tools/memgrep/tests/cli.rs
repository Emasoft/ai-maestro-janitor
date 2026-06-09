//! End-to-end tests: run the real `memgrep` binary against a committed fixture and assert the
//! structural filters behave. Uses `CARGO_BIN_EXE_memgrep` (cargo points it at the built binary),
//! so no extra dev-deps and we exercise the actual CLI a user/agent would invoke.

use std::process::Command;

const FX: &str = "tests/fixtures/sample.md";

/// A self-deleting temp file holding generated content, for fixtures too large to commit (the
/// adversarial deeply-nested markdown in H2). Drops remove the file so the test leaves no litter.
struct TempFixture {
    path: std::path::PathBuf,
}

impl TempFixture {
    fn new(name: &str, contents: &str) -> Self {
        // Unique-per-run name (pid + a monotonic counter) so parallel test threads never collide.
        use std::sync::atomic::{AtomicUsize, Ordering};
        static SEQ: AtomicUsize = AtomicUsize::new(0);
        let n = SEQ.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "memgrep-test-{}-{}-{}",
            std::process::id(),
            n,
            name
        ));
        std::fs::write(&path, contents).expect("write temp fixture");
        TempFixture { path }
    }
    fn as_str(&self) -> &str {
        self.path.to_str().expect("utf-8 temp path")
    }
}

impl Drop for TempFixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

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
    assert!(
        !out.status.success(),
        "memgrep should have failed for {args:?}"
    );
}

/// Run memgrep expecting a *clean* non-zero exit — a normal exit code, NEVER a signal kill.
/// `status.code()` is `Some(n)` for an `exit(n)` and `None` when the process died from a signal
/// (SIGSEGV/SIGABRT on a stack-overflow abort). Asserting `code().is_some()` is what distinguishes
/// "rejected the garbage with a Result error" from "crashed on the garbage" — the latter would
/// masquerade as a pass under the looser `run_fail`. Used for the adversarial-depth tests (H1).
fn run_fail_clean(args: &[&str]) {
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let out = Command::new(bin)
        .args(args)
        .output()
        .expect("failed to run memgrep");
    assert!(
        !out.status.success(),
        "memgrep should have failed for {args:?}"
    );
    assert!(
        out.status.code().is_some(),
        "memgrep died from a signal (no exit code) on {args:?} — an abort/crash, not a clean error"
    );
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
    assert!(
        !o.contains("echo security"),
        "code line must be excluded:\n{o}"
    );
}

#[test]
fn code_only_keeps_just_the_code_line() {
    let o = run(&["security", "--code", FX]);
    assert_eq!(o.lines().count(), 1);
    assert!(o.contains("echo security"));
}

#[test]
fn code_lang_filters_by_fence_language() {
    assert_eq!(
        run(&["security", "--code-lang", "python", FX])
            .lines()
            .count(),
        0
    );
    assert_eq!(
        run(&["security", "--code-lang", "bash", FX])
            .lines()
            .count(),
        1
    );
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
    assert_eq!(
        run(&["-c", "security", "--no-code", FX]).trim(),
        format!("{FX}:3")
    );
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
    assert_eq!(
        run(&["--heading", "--num", "1", "--depth", "1", FX])
            .lines()
            .count(),
        1
    );
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
    assert_eq!(
        run(&["widget", "--fm", "tags=security", FXFM])
            .lines()
            .count(),
        1
    );
    assert_eq!(
        run(&["widget", "--fm", "status=dev", FXFM]).lines().count(),
        1
    );
    // a frontmatter field that does not match ⟹ file skipped entirely.
    assert_eq!(
        run(&["widget", "--fm", "tags=nope", FXFM]).lines().count(),
        0
    );
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
    assert_eq!(
        run(&["--class-all", "security,backend", FXIN])
            .lines()
            .count(),
        1
    );
    assert_eq!(
        run(&["--class-all", "security,missing", FXIN])
            .lines()
            .count(),
        0
    );
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
    assert_eq!(
        run(&["widget", "--node", "table,quote", FXGFM])
            .lines()
            .count(),
        1
    );
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
    assert_eq!(
        run(&["fact", "--cat", "security", FXFACTS]).lines().count(),
        2
    );
    assert_eq!(run(&["fact", "--cat", "db", FXFACTS]).lines().count(), 1);
    assert_eq!(
        run(&["fact", "--session", "bbbb2222", FXFACTS])
            .lines()
            .count(),
        1
    );
    // --since excludes the 2026-06-05 fact.
    assert_eq!(
        run(&["fact", "--since", "2026-06-06", FXFACTS])
            .lines()
            .count(),
        2
    );
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
    assert!(
        to.contains("abcd1234-target.md"),
        "wikilink should resolve to the TRDD file:\n{to}"
    );
    assert!(!to.contains("BROKEN"), "{to}");
    assert!(
        run(&["links", "--broken", refr, tgt]).trim().is_empty(),
        "no link should be broken"
    );
}

#[test]
fn where_link_semijoin_to_from_and_join() {
    // The SQL model: `links-to`/`linked-from` resolve a FILE SET (the subquery), then AND with the
    // content search is the JOIN. trdd_ref links to [[TRDD-abcd1234]] (resolved via the id8 alias).
    let tgt = "tests/fixtures/TRDD-20260101_000000+0000-abcd1234-target.md";
    let refr = "tests/fixtures/trdd_ref.md";
    // files that link TO the abcd1234 note ⟹ trdd_ref.
    assert_eq!(
        run(&["-l", "--where", r#"links-to "abcd1234""#, refr, tgt]).trim(),
        refr
    );
    // files linked FROM trdd_ref (i.e. that note's out-links) ⟹ the abcd1234 target.
    assert_eq!(
        run(&["-l", "--where", r#"linked-from "trdd_ref""#, refr, tgt]).trim(),
        tgt
    );
    // the JOIN — content search restricted to the linking file.
    let j = run(&[
        "--where",
        r#"links-to "abcd1234" and text "rationale""#,
        refr,
        tgt,
    ]);
    assert_eq!(j.lines().count(), 1, "{j}");
    assert!(j.contains("trdd_ref.md"));
    // a needle that matches no note ⟹ empty set ⟹ no file qualifies.
    assert_eq!(
        run(&["--where", r#"links-to "nonesuch""#, refr, tgt])
            .lines()
            .count(),
        0
    );
}

#[test]
fn link_needle_matches_basename_not_directory_substring() {
    // M5: the link needle is scoped to the note BASENAME, not a substring of the whole path. The
    // fixtures live under `tests/fixtures/`, so a needle like "fixtures" or "tests" appears only in
    // a DIRECTORY component — it must NOT match any note (before the fix it pulled in every note via
    // the whole-path substring). A proper basename needle ("trdd_ref") still resolves the file.
    let tgt = "tests/fixtures/TRDD-20260101_000000+0000-abcd1234-target.md";
    let refr = "tests/fixtures/trdd_ref.md";
    for dir_substr in ["fixtures", "tests"] {
        let q = format!(r#"linked-from "{dir_substr}""#);
        assert_eq!(
            run(&["--where", &q, refr, tgt]).lines().count(),
            0,
            "directory substring {dir_substr:?} must not match any note's links"
        );
        let q2 = format!(r#"links-to "{dir_substr}""#);
        assert_eq!(
            run(&["--where", &q2, refr, tgt]).lines().count(),
            0,
            "directory substring {dir_substr:?} must not match any note's links"
        );
    }
    // a real basename needle still works (regression guard that the fix didn't over-restrict).
    assert_eq!(
        run(&["-l", "--where", r#"linked-from "trdd_ref""#, refr, tgt]).trim(),
        tgt
    );
}

#[test]
fn recall_ranks_by_symptom_surface() {
    // `recall` scores notes by symptom-surface (description/title/tags) hits. A phrase in the
    // QUESTION's vocabulary must rank the relevant note first and drop the unrelated one.
    let dir = "tests/fixtures/recall";
    let o = run(&["recall", "oauth rotation failed", dir]);
    let first = o.lines().next().unwrap_or("");
    assert!(
        first.contains("recall_a.md"),
        "oauth note should rank first:\n{o}"
    );
    assert!(
        !o.contains("recall_b.md"),
        "the unrelated tables note must not surface:\n{o}"
    );
    // the printed line carries the note's description (so the agent picks without opening it).
    assert!(
        o.contains("rotation failed"),
        "recall should show the description:\n{o}"
    );
}

#[test]
fn recall_excludes_index_files() {
    // A real memory dir contains a MEMORY.md (and optionally a memory-index.md). Those are MAPS of
    // the notes, not notes — recall must NOT rank them, else a symptom query matches the index's
    // gloss lines and returns the index as noise above the real note. The fixture MEMORY.md
    // contains "oauth rotation failed", so without the exclusion it WOULD surface (non-vacuous).
    let dir = "tests/fixtures/recall";
    let o = run(&["recall", "oauth rotation failed", dir]);
    assert!(
        !o.contains("MEMORY.md"),
        "the index file MEMORY.md must not be ranked as a note:\n{o}"
    );
    assert!(
        o.contains("recall_a.md"),
        "the real note must still surface:\n{o}"
    );
}

#[test]
fn index_emits_title_and_toc() {
    let o = run(&["index", "tests/fixtures/sample.md"]);
    assert!(o.contains("1 Intro"), "title missing:\n{o}");
    assert!(o.contains("toc:"), "toc missing:\n{o}");
}

#[test]
fn broken_pipe_dies_quietly_not_panics() {
    // `memgrep … | head` closes the pipe early; memgrep must die on SIGPIPE like grep/rg, NOT
    // panic with a backtrace. Use a large input so the write-after-close (which triggers EPIPE)
    // definitely happens past the OS pipe buffer.
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let dir = std::env::temp_dir().join(format!("memgrep_bp_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let big = dir.join("big.md");
    std::fs::write(&big, "match this line\n".repeat(40_000)).unwrap(); // ~640 KB ≫ pipe buffer
    let out = Command::new("sh")
        .arg("-c")
        .arg(format!("'{}' match '{}' | head -1", bin, big.display()))
        .output()
        .expect("run pipeline");
    let stderr = String::from_utf8_lossy(&out.stderr);
    std::fs::remove_dir_all(&dir).ok();
    assert!(
        !stderr.contains("panicked"),
        "memgrep panicked on a broken pipe:\n{stderr}"
    );
    assert!(
        !stderr.contains("Broken pipe"),
        "memgrep leaked a broken-pipe error:\n{stderr}"
    );
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
    assert_eq!(
        run(&["--where", r#"text "security" and not code"#, FX])
            .lines()
            .count(),
        3
    );
    // …and `and code` keeps only the in-code line.
    assert_eq!(
        run(&["--where", r#"text "security" and code"#, FX])
            .lines()
            .count(),
        1
    );
}

#[test]
fn where_or_unions_patterns() {
    // "security" is on 4 lines, "widget" on 0 ⟹ their union is 4. (A flat query cannot OR these.)
    assert_eq!(
        run(&["--where", r#"text "security" or text "widget""#, FX])
            .lines()
            .count(),
        4
    );
}

#[test]
fn where_grouping_changes_precedence() {
    // `(a or b) and c`: lines matching (security or nothing) AND in-code = the single code line.
    let o = run(&[
        "--where",
        r#"(text "security" or text "widget") and code"#,
        FX,
    ]);
    assert_eq!(o.lines().count(), 1, "{o}");
    assert!(o.contains("echo security"));
    // without grouping, `a or (b and c)` = security-anywhere(4) OR (widget AND code)(0) = 4.
    assert_eq!(
        run(&[
            "--where",
            r#"text "security" or text "widget" and code"#,
            FX
        ])
        .lines()
        .count(),
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
    assert_eq!(
        run(&["--where", r#"fm.status "dev" and text "widget""#, FXFM])
            .lines()
            .count(),
        1
    );
    // fm is a per-line-constant gate: with -l a matching file is listed, a non-matching one isn't.
    assert_eq!(
        run(&["-l", "--where", r#"fm.status "dev""#, FXFM]).trim(),
        FXFM
    );
    assert_eq!(
        run(&["--where", r#"fm.tags "nope""#, FXFM]).lines().count(),
        0
    );
}

#[test]
fn where_file_globs_and_emphasis() {
    // name/path globs gate the file; the emphasis predicate scopes within it.
    assert_eq!(
        run(&["--where", r#"name "*.md" and bold "security""#, FXIN])
            .lines()
            .count(),
        1
    );
    assert_eq!(
        run(&["--where", r#"name "*.rs" and bold "security""#, FXIN])
            .lines()
            .count(),
        0
    );
    assert_eq!(
        run(&[
            "--where",
            r#"path "**/sample_inline.md" and span-class "note""#,
            FXIN
        ])
        .lines()
        .count(),
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

#[test]
fn where_deep_nesting_exits_cleanly_not_via_signal() {
    // H1: a pathological --where (100k `!` or 100k `(`) must be rejected by the parser's depth guard
    // as a normal non-zero EXIT, never a stack-overflow SIGSEGV/abort (which catch_unwind can't
    // catch). run_fail_clean asserts status.code().is_some() so a signal-kill can't pass as success.
    let bangs = format!("{}text \"code\"", "!".repeat(100_000));
    run_fail_clean(&["--where", &bangs, FX]);
    let parens = format!(
        "{}text \"code\"{}",
        "(".repeat(100_000),
        ")".repeat(100_000)
    );
    run_fail_clean(&["--where", &parens, FX]);
}

#[test]
fn deeply_nested_markdown_greps_without_aborting() {
    // H2: pathologically nested block structure (verified to make comrak 0.52 hang/recurse
    // catastrophically) must NOT reach comrak. The cheap pre-scan degrades the file to plain-grep
    // (empty structural context), so memgrep still searches it and exits 0 — never a SIGSEGV/hang.
    //
    // Shape 1 — accumulating blockquote depth (line i opens i nested `>` containers). At 100k lines
    // this hangs comrak for minutes; even a few thousand levels crosses the pre-scan's nesting cap.
    let mut accum = String::with_capacity(2_000 * 1_500);
    for i in 1..=2_000 {
        accum.push_str(&">".repeat(i));
        accum.push_str(" ACCUM_NEEDLE\n");
    }
    let fx = TempFixture::new("deep-accum-quotes.md", &accum);
    // exit 0 (run() asserts success); plain-grep finds the needle on every line.
    let out = run(&["ACCUM_NEEDLE", fx.as_str()]);
    assert_eq!(
        out.lines().count(),
        2_000,
        "plain-grep should match every line"
    );
    // Degrade proof: comrak was skipped, so the structural `--quote` filter sees an empty context
    // and matches nothing — confirming we took the pre-scan bail, not a (slow) full parse.
    assert_eq!(
        run(&["--quote", "ACCUM_NEEDLE", fx.as_str()])
            .lines()
            .count(),
        0,
        "deeply nested file must degrade to empty context (no structural matches)"
    );

    // Shape 2 — a single line with a very deep `>` run. Same nesting signal, different layout.
    let deep_line = format!("{} DEEP_NEEDLE\n", ">".repeat(50_000));
    let fx2 = TempFixture::new("deep-line-quotes.md", &deep_line);
    let out2 = run(&["DEEP_NEEDLE", fx2.as_str()]);
    assert_eq!(
        out2.lines().count(),
        1,
        "plain-grep should match the single line"
    );
}

#[test]
fn oversized_file_is_skipped_normal_file_works() {
    // M4: a file larger than the 64 MiB cap must be SKIPPED (no read into RAM, no OOM, no output),
    // while an ordinary file still greps. We isolate the SIZE gate from the binary-NUL skip by
    // giving the big file valid text in its first 8 KiB (so the NUL probe would pass) and extending
    // it past the cap with a sparse tail — if it's skipped, only the size gate can be responsible.

    // Sanity: a normal small file with the needle IS found.
    let small = TempFixture::new("small.md", "hello CAP_NEEDLE world\n");
    assert_eq!(
        run(&["CAP_NEEDLE", small.as_str()]).lines().count(),
        1,
        "a normal file must still be searched"
    );

    // Oversized file: 8 KiB of real UTF-8 text (needle included) then a sparse extension to 65 MiB.
    let path =
        std::env::temp_dir().join(format!("memgrep-test-{}-oversized.md", std::process::id()));
    {
        let head = format!("CAP_NEEDLE {}\n", "x".repeat(8 * 1024));
        std::fs::write(&path, head.as_bytes()).expect("write head");
        let f = std::fs::OpenOptions::new()
            .write(true)
            .open(&path)
            .expect("reopen");
        // 65 MiB > the 64 MiB cap. set_len extends with sparse zeros (no real disk/RAM cost).
        f.set_len(65 * 1024 * 1024).expect("set_len");
    }
    // run() asserts exit 0 — the oversized file is skipped gracefully, not an OOM/crash, and the
    // needle in its (unread) head produces NO output.
    let out = run(&["CAP_NEEDLE", path.to_str().unwrap()]);
    assert_eq!(
        out.lines().count(),
        0,
        "oversized file must be skipped (no match emitted):\n{out}"
    );
    let _ = std::fs::remove_file(&path);
}

const NOTES_DIR: &str = "tests/fixtures/notes";

#[test]
fn recall_with_notes_appends_resolved_lessons_by_default() {
    // recall is --with-notes by default: after the ranked note it appends its resolved [^N]
    // lessons as a token-economical `[N] - <WHY>` list, so one recall yields facts + every WHY.
    let o = run(&["recall", "widget retry cap", NOTES_DIR]);
    assert!(o.contains("note_plain.md"), "the note must rank:\n{o}");
    // The two lessons appear as bare-number list entries (NOT the on-disk `[^N]:` form).
    assert!(
        o.contains("[3] - ") && o.contains("[4] - "),
        "resolved lessons must render as `[N] - <text>`:\n{o}"
    );
    assert!(
        o.contains("max_retries"),
        "the lesson WHY text must be inlined:\n{o}"
    );
    // The footnote-definition machinery (`[^3]:`) must NOT leak into the output.
    assert!(
        !o.contains("[^3]:"),
        "the on-disk footnote-def syntax must be normalized away:\n{o}"
    );
}

#[test]
fn recall_no_notes_returns_body_only() {
    // --no-notes is the escape hatch: resolution off, the ranked note prints without its lessons.
    let o = run(&["recall", "widget retry cap", NOTES_DIR, "--no-notes"]);
    assert!(
        o.contains("note_plain.md"),
        "the note must still rank:\n{o}"
    );
    assert!(
        !o.contains("[3] - ") && !o.contains("max_retries"),
        "--no-notes must suppress the resolved lessons:\n{o}"
    );
}

#[test]
fn recall_strips_note_metadata_prefix_by_default() {
    // A lesson's leading `[...]` metadata prefix is recognized + stripped by default — the agent
    // gets the WHY, not the bookkeeping (ocd/lmd/class/...).
    let o = run(&["recall", "rotator keychain", NOTES_DIR]);
    assert!(o.contains("note_meta.md"), "the note must rank:\n{o}");
    assert!(
        o.contains("[9] - ") && o.contains("OS keychain"),
        "the lesson WHY must render:\n{o}"
    );
    assert!(
        !o.contains("ocd:2026-06-01") && !o.contains("class:reference"),
        "the metadata prefix must be stripped by default:\n{o}"
    );
}

#[test]
fn recall_full_notes_restores_metadata_prefix() {
    // --full-notes restores the full form `[N] - [metadata...] <text>` for when the agent wants it.
    let o = run(&["recall", "rotator keychain", NOTES_DIR, "--full-notes"]);
    assert!(
        o.contains("ocd:2026-06-01") && o.contains("lmd:2026-06-09"),
        "--full-notes must restore the metadata prefix:\n{o}"
    );
    assert!(
        o.contains("OS keychain"),
        "the WHY text is still present in full mode:\n{o}"
    );
}

#[test]
fn recall_keeps_urls_and_images_in_minimal_notes() {
    // URLs / markdown links / image links are load-bearing and ALWAYS survive — even in the
    // default minimal render; only the `[...]` metadata prefix is strippable, never resources.
    let o = run(&["recall", "build cache lockfile", NOTES_DIR]);
    assert!(o.contains("note_link.md"), "the note must rank:\n{o}");
    assert!(
        o.contains("https://example.com/cache-bug"),
        "a bare URL in the lesson must survive the minimal render:\n{o}"
    );
    assert!(
        o.contains("![flow](img/cache-flow.png)"),
        "an image link in the lesson must survive:\n{o}"
    );
    assert!(
        o.contains("[issue](https://example.com/issues/7)"),
        "a markdown link in the lesson must survive:\n{o}"
    );
    // But the metadata prefix on THIS note is still stripped by default.
    assert!(
        !o.contains("class:reference"),
        "metadata is still stripped while resources are kept:\n{o}"
    );
}

#[test]
fn fact_with_notes_appends_resolved_lessons() {
    // `fact` also honors --with-notes: after the matched fact line it appends the file's resolved
    // lessons, so a fact lookup carries its WHY too.
    let o = run(&["fact", NOTES_DIR, "--cat", "cache", "--with-notes"]);
    assert!(
        o.contains("note_fact.md") && o.contains("lockfile hash"),
        "the fact must match:\n{o}"
    );
    assert!(
        o.contains("[1] - ") && o.contains("poisoned the cache"),
        "the fact's lesson must be resolved and appended:\n{o}"
    );
    // The inline ref in the emitted fact line renders as bare `[1]`, NOT the on-disk `[^1]`.
    assert!(
        !o.contains("[^1]"),
        "the inline footnote ref must normalize to the bare `[1]` form:\n{o}"
    );
}

#[test]
fn fact_without_with_notes_is_unchanged() {
    // `fact` is body-only unless --with-notes is asked for (it is NOT default-on for fact), so the
    // existing fact behavior is preserved.
    let o = run(&["fact", NOTES_DIR, "--cat", "cache"]);
    assert!(o.contains("lockfile hash"), "the fact must match:\n{o}");
    assert!(
        !o.contains("[1] - ") && !o.contains("poisoned the cache"),
        "without --with-notes the fact must stay body-only:\n{o}"
    );
}

#[test]
fn recall_with_notes_does_not_break_undescribed_corpus() {
    // The recall fixtures dir has notes WITHOUT footnotes; --with-notes (default) must be a no-op
    // there — body-only output, no crash, all 42 existing recall expectations intact.
    let o = run(&["recall", "oauth rotation failed", "tests/fixtures/recall"]);
    assert!(
        o.contains("recall_a.md"),
        "existing recall still works:\n{o}"
    );
    assert!(
        !o.contains("] - "),
        "a corpus with no footnotes yields no notes block:\n{o}"
    );
}

const DATES_DIR: &str = "tests/fixtures/dates";

/// Extract the ordered list of ranked NOTE paths from a recall run, dropping the interleaved
/// `[N] - <lesson>` lines and blank delimiters. A note line is `path — description`; a lesson line
/// starts with `[` and contains `] - `. This lets a sort assertion check note ORDER regardless of
/// any appended lessons block.
fn note_order(out: &str) -> Vec<String> {
    out.lines()
        .filter(|l| !l.trim().is_empty())
        .filter(|l| !(l.trim_start().starts_with('[') && l.contains("] - ")))
        .map(|l| l.split(" — ").next().unwrap_or(l).trim().to_string())
        .collect()
}

#[test]
fn recall_sort_lmd_orders_newest_first_by_default() {
    // --sort lmd reorders the ranked notes by Last-Modified-Date; default order is desc (newest
    // first). ISO-8601 strings compare lexicographically, so 2026-06-01 > 2025-06-01 > 2024-06-01.
    let o = run(&["recall", "ledger element", DATES_DIR, "--sort", "lmd"]);
    let order = note_order(&o);
    let pos = |needle: &str| {
        order
            .iter()
            .position(|p| p.contains(needle))
            .unwrap_or_else(|| panic!("{needle} missing from recall:\n{o}"))
    };
    assert!(
        pos("date_new.md") < pos("date_mid.md") && pos("date_mid.md") < pos("date_old.md"),
        "newest LMD must rank first under --sort lmd (desc default):\n{o}"
    );
    // The alias-dated note (lmd 2023-06-01) is the oldest of all, so it sorts last among the four.
    assert!(
        pos("date_old.md") < pos("date_alias.md"),
        "the 2023 alias-dated note is oldest, sorts after 2024:\n{o}"
    );
}

#[test]
fn recall_sort_lmd_asc_orders_oldest_first() {
    // --order asc flips the LMD sort to oldest-first.
    let o = run(&[
        "recall",
        "ledger element",
        DATES_DIR,
        "--sort",
        "lmd",
        "--order",
        "asc",
    ]);
    let order = note_order(&o);
    let pos = |needle: &str| order.iter().position(|p| p.contains(needle)).unwrap();
    assert!(
        pos("date_alias.md") < pos("date_old.md")
            && pos("date_old.md") < pos("date_mid.md")
            && pos("date_mid.md") < pos("date_new.md"),
        "--order asc must rank oldest LMD first:\n{o}"
    );
}

#[test]
fn recall_sort_ocd_uses_creation_date_and_aliases() {
    // --sort ocd orders by Original-Creation-Date, and the created/updated aliases populate ocd/lmd
    // when ocd/lmd are absent — so the alias note's ocd 2023-01-01 makes it the oldest creation.
    let o = run(&[
        "recall",
        "ledger element",
        DATES_DIR,
        "--sort",
        "ocd",
        "--order",
        "asc",
    ]);
    let order = note_order(&o);
    let pos = |needle: &str| order.iter().position(|p| p.contains(needle)).unwrap();
    assert!(
        pos("date_alias.md") < pos("date_old.md")
            && pos("date_old.md") < pos("date_mid.md")
            && pos("date_mid.md") < pos("date_new.md"),
        "ocd asc with the `created:` alias must rank the 2023 note first:\n{o}"
    );
}

#[test]
fn recall_since_filters_by_lmd() {
    // --since keeps only notes whose LMD (the default date field) is on/after the bound. With
    // 2025-01-01 the 2024 and 2023 notes drop; the 2025 and 2026 notes remain.
    let o = run(&[
        "recall",
        "ledger element",
        DATES_DIR,
        "--since",
        "2025-01-01",
    ]);
    assert!(
        o.contains("date_mid.md") && o.contains("date_new.md"),
        "notes with LMD ≥ since must remain:\n{o}"
    );
    assert!(
        !o.contains("date_old.md") && !o.contains("date_alias.md"),
        "notes with LMD < since must be filtered out:\n{o}"
    );
}

#[test]
fn recall_until_filters_by_lmd() {
    // --until keeps only notes whose LMD is on/before the bound (inclusive). 2024-12-31 keeps the
    // 2024 and 2023 notes, drops 2025/2026.
    let o = run(&[
        "recall",
        "ledger element",
        DATES_DIR,
        "--until",
        "2024-12-31",
    ]);
    assert!(
        o.contains("date_old.md") && o.contains("date_alias.md"),
        "notes with LMD ≤ until must remain:\n{o}"
    );
    assert!(
        !o.contains("date_mid.md") && !o.contains("date_new.md"),
        "notes with LMD > until must be filtered out:\n{o}"
    );
}

#[test]
fn recall_since_until_window_filters_by_lmd() {
    // Both bounds compose into an inclusive [since, until] window on LMD: only the 2025 note's
    // 2025-06-01 falls inside [2025-01-01, 2025-12-31].
    let o = run(&[
        "recall",
        "ledger element",
        DATES_DIR,
        "--since",
        "2025-01-01",
        "--until",
        "2025-12-31",
    ]);
    assert!(
        o.contains("date_mid.md"),
        "the in-window note must remain:\n{o}"
    );
    assert!(
        !o.contains("date_new.md") && !o.contains("date_old.md") && !o.contains("date_alias.md"),
        "out-of-window notes must be filtered:\n{o}"
    );
}

#[test]
fn recall_date_field_ocd_switches_the_filtered_field() {
    // --date-field ocd makes --since/--until compare against OCD instead of LMD. With ocd cut
    // 2026-01-01, only date_new.md (ocd 2026-01-01) survives — even though several have a 2026 LMD.
    let o = run(&[
        "recall",
        "ledger element",
        DATES_DIR,
        "--since",
        "2026-01-01",
        "--date-field",
        "ocd",
    ]);
    assert!(o.contains("date_new.md"), "ocd ≥ since must remain:\n{o}");
    assert!(
        !o.contains("date_mid.md") && !o.contains("date_old.md") && !o.contains("date_alias.md"),
        "earlier-ocd notes must drop under --date-field ocd:\n{o}"
    );
}

#[test]
fn recall_missing_date_excluded_from_range_filter() {
    // A note with NO ocd in frontmatter has no OCD (fs btime is unreliable, so OCD stays None). A
    // date-range filter on the missing field EXCLUDES it (documented choice: no-date ⟹ out of range).
    let o = run(&[
        "recall",
        "ledger element",
        DATES_DIR,
        "--since",
        "2020-01-01",
        "--date-field",
        "ocd",
    ]);
    // date_nodate.md has no ocd ⟹ excluded even by a very permissive since bound.
    assert!(
        !o.contains("date_nodate.md"),
        "a note missing OCD must be excluded from an OCD range filter:\n{o}"
    );
    // …while the dated notes still pass the permissive bound.
    assert!(
        o.contains("date_new.md"),
        "dated notes still pass a permissive since:\n{o}"
    );
}

#[test]
fn recall_missing_date_sorts_last() {
    // Under --sort ocd, a note with no OCD sorts AFTER every dated note (missing date ⟹ last),
    // regardless of order direction. date_nodate.md must be the final entry.
    let o = run(&[
        "recall",
        "ledger element",
        DATES_DIR,
        "--sort",
        "ocd",
        "--order",
        "desc",
    ]);
    let order = note_order(&o);
    assert!(
        order.last().is_some_and(|p| p.contains("date_nodate.md")),
        "the OCD-less note must sort last:\n{o}"
    );
    assert!(
        order.len() >= 5,
        "all dated notes plus the undated one should rank:\n{o}"
    );
}

#[test]
fn recall_default_sort_is_score_unchanged() {
    // Omitting --sort keeps the existing precision-first relevance order (score), NOT a date sort:
    // the most on-topic note ranks first by surface hits, exactly as before this slice. "freshest"
    // appears in ONLY date_new.md's description, so it is the sole surface match ⟹ ranks #1, even
    // though by LMD it is the newest (i.e. the result is NOT date-ordered without --sort).
    let o = run(&["recall", "freshest ledger", DATES_DIR]);
    let order = note_order(&o);
    assert!(
        order.first().is_some_and(|p| p.contains("date_new.md")),
        "default sort stays score-based (the uniquely-matching note ranks first):\n{o}"
    );
}

#[test]
fn recall_rejects_unknown_sort_key() {
    // An unknown --sort value is a clean usage error (not a silent fallback), matching the crate's
    // fail-loud convention for bad inputs.
    run_fail(&["recall", "ledger element", DATES_DIR, "--sort", "bogus"]);
}
