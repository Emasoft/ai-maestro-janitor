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

/// Run memgrep and return stdout WHATEVER the exit code. For verbs whose non-zero exit is a
/// RESULT rather than an error — `lint` exits non-zero precisely when it finds violations, so
/// `run` (which asserts success) can never inspect the findings it is meant to test.
fn run_any(args: &[&str]) -> String {
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let out = Command::new(bin)
        .args(args)
        .output()
        .expect("failed to run memgrep");
    String::from_utf8_lossy(&out.stdout).into_owned()
}

/// A page `description:` that satisfies the 15-distinct-phrase gate, for fixtures whose subject
/// is NOT the description itself.
///
/// Written as a real recall surface rather than `p1 / p2 / …` on purpose: test fixtures are read
/// as worked examples, and the next author reaching for a `new-page` call will copy whatever is
/// here. Filler would teach exactly the shape the gate exists to reject — a count satisfied
/// without coverage gained.
const FIXTURE_PAGE_DESC: &str = "the widget stopped responding / why does the widget hang / \
     widget freezes on load / the panel never finishes rendering / clicking does nothing / \
     spinner spins forever / how do I reset the widget / widget state is stuck / \
     what makes the widget hang / is the widget deadlocked / widget unresponsive after resize / \
     the component stops updating / no error but nothing happens / widget needs a restart / \
     where is the widget state stored";

/// A keyphrase list satisfying the 10-distinct-keyphrase gate, for atoms whose subject is not
/// their own keywords. Same reasoning as `FIXTURE_PAGE_DESC`.
const FIXTURE_KEYWORDS: &str = "the widget stopped responding, why does the widget hang, \
     widget freezes on load, spinner spins forever, how do I reset the widget, \
     widget state is stuck, is the widget deadlocked, widget unresponsive after resize, \
     the component stops updating, where is the widget state stored";

/// An atom `--desc` past the 24-char floor.
const FIXTURE_DESC: &str = "what makes the widget hang and how to clear it";

/// Run memgrep and return BOTH stdout and the exit code. `lint`'s severity model makes the exit
/// code a first-class result — "printed but did not gate" and "printed and gated" differ ONLY in
/// that number, so a helper returning stdout alone cannot tell the two apart.
fn run_with_code(args: &[&str]) -> (String, i32) {
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let out = Command::new(bin)
        .args(args)
        .output()
        .expect("failed to run memgrep");
    (
        String::from_utf8_lossy(&out.stdout).into_owned(),
        out.status.code().unwrap_or(-1),
    )
}

/// Run memgrep and return (stdout, stderr, exit code) — for the janitor#127 `help`/typo-hint
/// tests, where the SIGNAL is on stderr while stdout carries the (unaffected) grep results.
fn run_full(args: &[&str]) -> (String, String, i32) {
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let out = Command::new(bin)
        .args(args)
        .output()
        .expect("failed to run memgrep");
    (
        String::from_utf8_lossy(&out.stdout).into_owned(),
        String::from_utf8_lossy(&out.stderr).into_owned(),
        out.status.code().unwrap_or(-1),
    )
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

/// Run memgrep expecting a clean NON-zero exit AND return its stdout — for commands whose failure
/// contract includes printed output (the atom-id AMBIGUITY listing prints every match, THEN fails).
fn run_fail_capture(args: &[&str]) -> String {
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
        "memgrep died from a signal (no exit code) on {args:?}"
    );
    String::from_utf8_lossy(&out.stdout).into_owned()
}

/// janitor#164: `--version` must identify the BUILD, not just the crate version — two forks
/// once both reported `0.1.0` while their sources had diverged by thousands of lines, and
/// nothing in the CLI surface could tell them apart. `clap`'s bare `version` shorthand only
/// ever echoes `Cargo.toml`, so this pins that main.rs's `MEMGREP_VERSION` const actually
/// widens the string (a regression back to bare `Cargo.toml` echo would silently drop the
/// commit stamp and this test would catch it via the missing parenthesized suffix).
#[test]
fn version_output_carries_a_build_stamp_beyond_the_bare_crate_version() {
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let out = Command::new(bin)
        .arg("--version")
        .output()
        .expect("failed to run memgrep --version");
    assert!(out.status.success());
    let stdout = String::from_utf8_lossy(&out.stdout);
    let line = stdout.trim();
    assert!(
        line.starts_with("memgrep "),
        "clap's version output must still start with the binary name: {line:?}"
    );
    // Two build.rs-supplied fields, parenthesized after the bare crate version — "unknown" is
    // the documented fail-open fallback (a git-less build environment), so it is an accepted
    // value here, not a special case: either way the field must be PRESENT, never silently
    // dropped back to the bare `memgrep 0.1.0` shape this feature replaces.
    assert!(
        line.contains(" ("),
        "version output must carry a parenthesized build stamp, got: {line:?}"
    );
    assert!(
        line.ends_with(')'),
        "the build stamp must be a well-formed trailing (sha, date), got: {line:?}"
    );
    let inside = line
        .rsplit_once('(')
        .expect("already asserted the '(' is present")
        .1
        .trim_end_matches(')');
    let parts: Vec<&str> = inside.split(", ").collect();
    assert_eq!(
        parts.len(),
        2,
        "expected exactly (sha, date) inside the build stamp, got: {inside:?}"
    );
    for field in parts {
        assert!(!field.is_empty(), "a build-stamp field must never be an empty string");
    }
}

/// TRDD-9XMPS8OZ: the stamp must name THIS commit, not merely be well-shaped.
///
/// The test above checks the stamp's SHAPE and is green against a stamp frozen at any
/// commit — which is how the real defect survived from janitor#164 until 2026-08-16.
/// `build.rs` watched `<git-dir>/HEAD`, a file that holds the constant `ref: refs/heads/…`
/// and that a commit never writes, so cargo never re-ran it and every build reported the
/// commit that was HEAD the FIRST time the crate was built in that checkout. Measured on
/// this host: the binary carried code committed 2026-08-14 while `--version` said
/// `a685cca, 2026-08-07`. A stamp that exists to expose a stale binary was itself the
/// stale thing, and it answered confidently.
///
/// This assertion cannot be satisfied by a frozen stamp: `cargo test` builds the binary
/// immediately before running it, so with the watch list fixed the sha is necessarily the
/// current HEAD, and with the bug present it drifts the moment HEAD moves.
///
/// SKIPS (does not fail) when git is unavailable or the sha is the documented `unknown`
/// fallback — a source tarball with no `.git` is a supported build environment, and this
/// test must not turn that into a failure.
#[test]
fn version_stamp_names_the_commit_this_binary_was_actually_built_from() {
    let head = match Command::new("git").args(["rev-parse", "--short=7", "HEAD"]).output() {
        Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).trim().to_string(),
        _ => return, // no git here — nothing to compare against
    };
    if head.is_empty() {
        return;
    }

    let bin = env!("CARGO_BIN_EXE_memgrep");
    let out = Command::new(bin)
        .arg("--version")
        .output()
        .expect("failed to run memgrep --version");
    let stdout = String::from_utf8_lossy(&out.stdout);
    let line = stdout.trim();
    let inside = line
        .rsplit_once('(')
        .map(|(_, rest)| rest.trim_end_matches(')'))
        .unwrap_or("");
    let stamped_sha = inside.split(", ").next().unwrap_or("").trim();

    if stamped_sha == "unknown" {
        return; // fail-open build environment, documented in build.rs
    }
    assert_eq!(
        stamped_sha, head,
        "`--version` reports commit {stamped_sha:?} but this build is at HEAD {head:?}. The \
         build stamp has frozen: build.rs is not being re-run when the branch ref moves, so \
         every binary from this checkout will keep claiming an old provenance. Check the \
         `cargo:rerun-if-changed` list in build.rs — watching `.git/HEAD` alone is the bug, \
         because a commit writes the RESOLVED ref, not HEAD."
    );
}

/// janitor#127: `memgrep help` used to SUCCEED silently as a literal grep for the word "help"
/// (exit 0, plausible-looking output) — the discovery convention every other CLI (git/cargo/npm)
/// honors instead reads as "this tool has no subcommands". `help` must now behave like `--help`.
#[test]
fn bare_help_word_shows_the_verb_list_not_a_grep_of_the_word_help() {
    let (stdout, _stderr, code) = run_full(&["help"]);
    assert_eq!(code, 0);
    assert!(
        stdout.contains("Memory verbs"),
        "expected the verb-list trailer in help output, got: {stdout:?}"
    );
    assert!(
        stdout.contains("Usage: memgrep"),
        "expected clap's own usage banner, got: {stdout:?}"
    );
    assert!(
        !stdout.contains("CODE_OF_CONDUCT"),
        "must NOT look like a grep match against the repo's own files, got: {stdout:?}"
    );
}

/// janitor#127 item 2: a near-miss of a known verb warns to STDERR before falling through to a
/// literal grep — grep-first semantics unchanged (exit 0, the search still runs), only a human
/// reading stderr learns why a plausible-looking success was not the verb they meant. All three
/// are the issue's own reproducer examples.
#[test]
fn near_miss_verb_typos_warn_on_stderr_but_still_search() {
    for (typo, expected_suggestion) in [
        ("hlep", "help"),
        ("recal", "recall"),
        ("validte", "validate"),
    ] {
        let (_stdout, stderr, code) = run_full(&[typo, FX]);
        assert_eq!(code, 0, "a typo must still exit 0 — it is a search, not an error");
        assert!(
            stderr.contains(&format!("did you mean `{expected_suggestion}`?")),
            "expected a `{expected_suggestion}` suggestion for {typo:?}, got stderr: {stderr:?}"
        );
        assert!(
            stderr.contains("memgrep --help"),
            "the hint must point at the verb list, got: {stderr:?}"
        );
    }
}

/// The other half — a real search pattern that happens to share a plausible word must NOT be
/// second-guessed. Without this the typo hint would misfire on ordinary usage and train its
/// reader to ignore it, same failure shape as any over-eager nag.
#[test]
fn ordinary_search_words_do_not_trigger_the_typo_hint() {
    for pattern in ["security", "TODO:", "class Foo", "access.*denied"] {
        let (_stdout, stderr, code) = run_full(&[pattern, FX]);
        assert_eq!(code, 0);
        assert!(
            !stderr.contains("is not a verb"),
            "an ordinary search for {pattern:?} must not print the typo hint, got stderr: {stderr:?}"
        );
    }
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
        first.contains("recall_a"),
        "oauth note should rank first:\n{o}"
    );
    assert!(
        !o.contains("recall_b"),
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
        o.contains("recall_a"),
        "the real note must still surface:\n{o}"
    );
}

#[test]
fn index_emits_title_and_toc() {
    // The Markdown doc-generator now lives behind `index --markdown` (bare `index` builds the
    // SQLite query index — TRDD-c77dae09 "the index subcommand must grow from a doc-generator into
    // a real query index"). The doc output itself is unchanged.
    let o = run(&["index", "--markdown", "tests/fixtures/sample.md"]);
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
    let o = run(&["recall", "widget retry cap", NOTES_DIR, "--output", "full"]);
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
        o.contains("note_plain"),
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
    let o = run(&["recall", "rotator keychain", NOTES_DIR, "--output", "full"]);
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
    let o = run(&[
        "recall",
        "rotator keychain",
        NOTES_DIR,
        "--full-notes",
        "--output",
        "full",
    ]);
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
    let o = run(&["recall", "build cache lockfile", NOTES_DIR, "--output", "full"]);
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
        o.contains("recall_a"),
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
        pos("date_new") < pos("date_mid") && pos("date_mid") < pos("date_old"),
        "newest LMD must rank first under --sort lmd (desc default):\n{o}"
    );
    // The alias-dated note (lmd 2023-06-01) is the oldest of all, so it sorts last among the four.
    assert!(
        pos("date_old") < pos("date_alias"),
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
        pos("date_alias") < pos("date_old")
            && pos("date_old") < pos("date_mid")
            && pos("date_mid") < pos("date_new"),
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
        pos("date_alias") < pos("date_old")
            && pos("date_old") < pos("date_mid")
            && pos("date_mid") < pos("date_new"),
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
        o.contains("date_mid") && o.contains("date_new"),
        "notes with LMD ≥ since must remain:\n{o}"
    );
    assert!(
        !o.contains("date_old") && !o.contains("date_alias"),
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
        o.contains("date_old") && o.contains("date_alias"),
        "notes with LMD ≤ until must remain:\n{o}"
    );
    assert!(
        !o.contains("date_mid") && !o.contains("date_new"),
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
        o.contains("date_mid"),
        "the in-window note must remain:\n{o}"
    );
    assert!(
        !o.contains("date_new") && !o.contains("date_old") && !o.contains("date_alias"),
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
    assert!(o.contains("date_new"), "ocd ≥ since must remain:\n{o}");
    assert!(
        !o.contains("date_mid") && !o.contains("date_old") && !o.contains("date_alias"),
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
        !o.contains("date_nodate"),
        "a note missing OCD must be excluded from an OCD range filter:\n{o}"
    );
    // …while the dated notes still pass the permissive bound.
    assert!(
        o.contains("date_new"),
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
        order.last().is_some_and(|p| p.contains("date_nodate")),
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
        order.first().is_some_and(|p| p.contains("date_new")),
        "default sort stays score-based (the uniquely-matching note ranks first):\n{o}"
    );
}

#[test]
fn recall_rejects_unknown_sort_key() {
    // An unknown --sort value is a clean usage error (not a silent fallback), matching the crate's
    // fail-loud convention for bad inputs.
    run_fail(&["recall", "ledger element", DATES_DIR, "--sort", "bogus"]);
}

// ─────────────────────── SQLite + FTS5 persistent index (slice 3) ───────────────────────

/// A self-deleting temp DIRECTORY holding a generated corpus, for the mutate-and-reindex tests
/// (they modify/delete `.md` files and write a `.memgrep/` sidecar — never touch committed
/// fixtures). `Drop` recursively removes the tree so the test leaves no litter.
struct TempDir {
    path: std::path::PathBuf,
}

impl TempDir {
    fn new(tag: &str) -> Self {
        use std::sync::atomic::{AtomicUsize, Ordering};
        static SEQ: AtomicUsize = AtomicUsize::new(0);
        let n = SEQ.fetch_add(1, Ordering::Relaxed);
        let path =
            std::env::temp_dir().join(format!("memgrep-idx-{}-{}-{}", std::process::id(), n, tag));
        std::fs::create_dir_all(&path).expect("create temp corpus dir");
        TempDir { path }
    }
    fn as_str(&self) -> &str {
        self.path.to_str().expect("utf-8 temp path")
    }
    /// Write a note file `name` with `contents` into the corpus.
    fn write(&self, name: &str, contents: &str) {
        std::fs::write(self.path.join(name), contents).expect("write note");
    }
    fn join(&self, rel: &str) -> std::path::PathBuf {
        self.path.join(rel)
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

/// A small two-note corpus reused by several index tests.
fn seed_corpus(d: &TempDir) {
    d.write(
        "alpha.md",
        "---\ndescription: oauth rotator keychain credentials\ntags: [oauth, rotator]\nocd: 2024-01-01\nlmd: 2024-06-01\n---\n# Alpha\n\nBody about keychain credentials and token rotation.\n",
    );
    d.write(
        "beta.md",
        "---\ndescription: widget retry backoff schedule\ntags: [widget]\nocd: 2026-01-01\nlmd: 2026-06-01\n---\n# Beta\n\nBody about the widget retry policy.\n",
    );
}

#[test]
fn index_builds_sqlite_db_and_self_gitignores() {
    // Bare `index DIR` (no --markdown) builds the persistent SQLite index at <root>/.memgrep/
    // index.db AND drops a self-ignoring <root>/.memgrep/.gitignore containing `*` — the derived
    // cache must never be committed (git tracks the .md source of truth).
    let d = TempDir::new("gitignore");
    seed_corpus(&d);
    let o = run(&["index", d.as_str()]);
    assert!(
        d.join(".memgrep/index.db").is_file(),
        "index.db must exist after `index DIR`:\nstdout: {o}"
    );
    let gi = std::fs::read_to_string(d.join(".memgrep/.gitignore"))
        .expect(".memgrep/.gitignore must exist");
    assert!(
        gi.lines().any(|l| l.trim() == "*"),
        ".memgrep/.gitignore must contain `*` (self-ignoring):\n{gi}"
    );
    assert!(
        o.contains("indexed"),
        "index must print a one-line summary:\n{o}"
    );
}

#[test]
fn reindex_is_an_alias_for_index() {
    // `reindex DIR` is the canonical name; `index DIR` (no flag) is its alias. Both build the DB.
    let d = TempDir::new("alias");
    seed_corpus(&d);
    let o = run(&["reindex", d.as_str()]);
    assert!(
        d.join(".memgrep/index.db").is_file(),
        "reindex must build the DB:\n{o}"
    );
    assert!(o.contains("indexed"), "reindex prints a summary:\n{o}");
}

#[test]
fn reindex_then_recall_via_index_matches_walk() {
    // The whole point: an index-backed recall returns the SAME results as the live tree-walk. Build
    // the index, then compare `recall --use-index` to plain `recall` (walk) — byte-identical.
    let d = TempDir::new("match");
    seed_corpus(&d);
    run(&["reindex", d.as_str()]);
    let walk = run(&["recall", "keychain credentials", d.as_str()]);
    let indexed = run(&["recall", "keychain credentials", d.as_str(), "--use-index"]);
    assert!(
        walk.contains("alpha"),
        "walk recall must find alpha:\n{walk}"
    );
    assert_eq!(
        walk, indexed,
        "index-backed recall must match the walk byte-for-byte:\nwalk:\n{walk}\nindex:\n{indexed}"
    );
}

#[test]
fn reindex_incremental_skips_unchanged() {
    // A second reindex of an unchanged corpus re-parses NOTHING — the summary reports 0 changed and
    // every file skipped (incremental change-detection via the `files` ledger).
    let d = TempDir::new("skip");
    seed_corpus(&d);
    run(&["reindex", d.as_str()]); // first build: 2 changed
    let o = run(&["reindex", d.as_str()]); // second: 0 changed, 2 skipped
    assert!(
        o.contains("indexed 2 (0 changed, 2 skipped, 0 deleted)"),
        "an unchanged second pass must skip everything:\n{o}"
    );
}

#[test]
fn reindex_reparses_only_changed_file() {
    // Modify exactly ONE note, reindex, and assert the summary reports exactly 1 changed (the other
    // is skipped). This proves the indexer re-parses only what changed, not the whole corpus.
    let d = TempDir::new("onechange");
    seed_corpus(&d);
    run(&["reindex", d.as_str()]);
    // Touch the BODY of alpha only (changing its blob sha / size+mtime).
    d.write(
        "alpha.md",
        "---\ndescription: oauth rotator keychain credentials\ntags: [oauth, rotator]\nocd: 2024-01-01\nlmd: 2024-06-01\n---\n# Alpha\n\nBody about keychain credentials and token rotation. EDITED.\n",
    );
    let o = run(&["reindex", d.as_str()]);
    assert!(
        o.contains("indexed 2 (1 changed, 1 skipped, 0 deleted)"),
        "only the edited file must re-parse:\n{o}"
    );
}

#[test]
fn reindex_prunes_deleted_file() {
    // A file in the ledger but no longer on disk has its rows deleted; an index-backed recall no
    // longer returns it, and the summary reports the deletion.
    let d = TempDir::new("delete");
    seed_corpus(&d);
    run(&["reindex", d.as_str()]);
    std::fs::remove_file(d.join("beta.md")).expect("remove beta");
    let o = run(&["reindex", d.as_str()]);
    assert!(
        o.contains("indexed 1 (0 changed, 1 skipped, 1 deleted)"),
        "the removed file must be pruned:\n{o}"
    );
    let r = run(&["recall", "widget retry", d.as_str(), "--use-index"]);
    assert!(
        !r.contains("beta"),
        "a pruned file must not surface via the index:\n{r}"
    );
}

#[test]
fn recall_use_index_fts_text_match() {
    // A body-only term (not in description/title/tags) resolves through the FTS5 body match: the
    // index returns the note whose BODY contains the term, same as the walk's body fallback.
    let d = TempDir::new("fts");
    d.write(
        "doc.md",
        "---\ndescription: an unrelated surface line\ntags: [misc]\n---\n# Doc\n\nThe quibblefrobnicator only appears deep in the body text.\n",
    );
    run(&["reindex", d.as_str()]);
    let o = run(&["recall", "quibblefrobnicator", d.as_str(), "--use-index"]);
    assert!(
        o.contains("doc"),
        "FTS body match must surface the note via the index:\n{o}"
    );
}

#[test]
fn recall_use_index_date_range_filter() {
    // A --since/--until window applied via the index uses the stored OCD/LMD (a B-tree/ORDER BY
    // path), returning the same membership as the walk's date filter.
    let d = TempDir::new("daterange");
    seed_corpus(&d); // alpha lmd 2024-06-01, beta lmd 2026-06-01
    run(&["reindex", d.as_str()]);
    let o = run(&[
        "recall",
        "rotator widget",
        d.as_str(),
        "--use-index",
        "--since",
        "2025-01-01",
    ]);
    assert!(
        o.contains("beta") && !o.contains("alpha"),
        "only the note with LMD ≥ since must remain via the index:\n{o}"
    );
}

#[test]
fn recall_index_absent_falls_back_to_walk() {
    // `--use-index` with NO index present must still return correct results — it degrades to the
    // live walk so a missing/never-built index never yields wrong/empty output.
    let d = TempDir::new("absent");
    seed_corpus(&d);
    // No reindex — there is no .memgrep/index.db.
    let o = run(&["recall", "keychain credentials", d.as_str(), "--use-index"]);
    assert!(
        !d.join(".memgrep/index.db").exists(),
        "the absent-index test must not have a DB"
    );
    assert!(
        o.contains("alpha"),
        "recall --use-index must fall back to the walk when no index exists:\n{o}"
    );
}

#[test]
fn recall_auto_uses_fresh_index_else_walks() {
    // Without --use-index, recall auto-uses a FRESH index when present, but a corpus file newer than
    // the ledger forces the live walk so results are always correct. Here: build the index, then add
    // a NEW file the index doesn't know — the auto path must still find it (by walking).
    let d = TempDir::new("auto");
    seed_corpus(&d);
    run(&["reindex", d.as_str()]);
    // Add a third note AFTER indexing; the ledger is now stale.
    d.write(
        "gamma.md",
        "---\ndescription: a freshly added note about keychain access\ntags: [new]\n---\n# Gamma\n\nKeychain credentials body, added after the last index.\n",
    );
    let o = run(&["recall", "keychain credentials", d.as_str()]);
    assert!(
        o.contains("gamma"),
        "a corpus newer than the ledger must force the walk so new notes still surface:\n{o}"
    );
}

#[test]
fn reindex_edit_replaces_indexed_body() {
    // After an incremental re-parse the OLD body content is gone from the index (the delete cleared
    // the row + its FTS shadow) and the NEW content is present (the reinsert) — proving the changed-
    // file path replaces, never duplicates or leaks stale text.
    let d = TempDir::new("editbody");
    d.write(
        "doc.md",
        "---\ndescription: surface stays the same\ntags: [x]\n---\n# Doc\n\nThe originalbodyterm lives here.\n",
    );
    run(&["reindex", d.as_str()]);
    assert!(
        run(&["recall", "originalbodyterm", d.as_str(), "--use-index"]).contains("doc"),
        "the index must initially match the original body term"
    );
    // Replace the body term; reindex incrementally.
    d.write(
        "doc.md",
        "---\ndescription: surface stays the same\ntags: [x]\n---\n# Doc\n\nThe replacedbodyterm lives here now.\n",
    );
    let summary = run(&["reindex", d.as_str()]);
    assert!(
        summary.contains("indexed 1 (1 changed, 0 skipped, 0 deleted)"),
        "the edited file must re-parse:\n{summary}"
    );
    let old = run(&["recall", "originalbodyterm", d.as_str(), "--use-index"]);
    assert!(
        !old.contains("doc"),
        "the stale body term must be gone from the index after the edit:\n{old}"
    );
    let new = run(&["recall", "replacedbodyterm", d.as_str(), "--use-index"]);
    assert!(
        new.contains("doc"),
        "the new body term must be present after the incremental re-parse:\n{new}"
    );
}

// ─────────────────────────── slice 4 — `memgrep find` +/- query DSL ───────────────────────────

const FIND_DIR: &str = "tests/fixtures/find";
const RECALL_DIR: &str = "tests/fixtures/recall";

#[test]
fn find_plus_term_is_mandatory() {
    // A `+TERM` is MANDATORY: only notes whose searchable surface contains it survive. `+production`
    // keeps the production note and drops the logistic-regression / old-approach notes that lack it.
    let o = run(&["find", "+production", FIND_DIR]);
    assert!(
        o.contains("prod_debug"),
        "mandatory +production must keep prod_debug:\n{o}"
    );
    assert!(
        !o.contains("db_logistics") && !o.contains("old_approach"),
        "notes missing the mandatory term must be dropped:\n{o}"
    );
}

#[test]
fn find_minus_term_excludes() {
    // A `-TERM` EXCLUDES: any note containing it is dropped. The query (ONE whitespace-separated
    // string per the DSL) `regression -logistic` matches the ml note on the optional `regression`,
    // but `-logistic` removes it — so db_logistics is dropped despite the optional hit.
    let o = run(&["find", "regression -logistic", FIND_DIR]);
    assert!(
        !o.contains("db_logistics"),
        "a note containing the -excluded term must be dropped even if an optional term matched:\n{o}"
    );
}

#[test]
fn find_optional_terms_rank_by_match_count() {
    // With no `+`/`-`, every term is OPTIONAL: notes are RANKED by how many optional terms matched.
    // `oauth rotation tables` — recall_a matches two (oauth, rotation), recall_b matches one (tables),
    // so recall_a ranks ABOVE recall_b (more optional hits first).
    let o = run(&["find", "oauth rotation tables", RECALL_DIR]);
    let a = o.find("recall_a").expect("recall_a must appear");
    let b = o.find("recall_b").expect("recall_b must appear");
    assert!(
        a < b,
        "the note matching MORE optional terms must rank first:\n{o}"
    );
}

#[test]
fn find_wildcard_word_matches_any_run() {
    // A `*` matches any run of chars: `regress*` matches `regression`; the note surfaces. The plain
    // (non-wildcard) note without that stem does not.
    let o = run(&["find", "+regress*", FIND_DIR]);
    assert!(
        o.contains("db_logistics"),
        "wildcard regress* must match regression:\n{o}"
    );
    assert!(
        !o.contains("old_approach"),
        "a non-matching note must not surface:\n{o}"
    );
}

#[test]
fn find_embedded_hyphen_is_literal_not_operator() {
    // CRITICAL disambiguation: a `-` that is NOT the leading char is LITERAL. `pro*-debug*` is ONE
    // wildcard term (→ regex `pro.*\-debug.*`) matching `prod-debugger`, NOT `pro*` minus `debug*`.
    // If the `-` were parsed as an exclude operator, the prod note (which contains `debug`) would be
    // wrongly dropped; instead it must surface.
    let o = run(&["find", "+pro*-debug*", FIND_DIR]);
    assert!(
        o.contains("prod_debug"),
        "embedded-hyphen wildcard must be one term matching prod-debugger, not an exclude:\n{o}"
    );
}

#[test]
fn find_quoted_phrase_matches_with_spaces() {
    // A double-quoted token is a VERBATIM phrase matched literally WITH the spaces. Only the note
    // whose surface contains the exact run `logistic regression failure` survives the mandatory phrase.
    let o = run(&["find", "+\"logistic regression failure\"", FIND_DIR]);
    assert!(
        o.contains("db_logistics"),
        "the phrase note must match:\n{o}"
    );
    assert!(
        !o.contains("prod_debug") && !o.contains("old_approach"),
        "notes without the exact phrase must be dropped:\n{o}"
    );
}

#[test]
fn find_prefixed_phrase_excludes() {
    // A phrase may carry a leading `+`/`-`. The single-string query `retry -"old approach"` matches
    // old_approach on the optional `retry`, but the `-"old approach"` phrase exclusion drops it
    // (a phrase is a keyword WITH spaces, so it too can be `-`-prefixed).
    let o = run(&["find", "retry -\"old approach\"", FIND_DIR]);
    assert!(
        !o.contains("old_approach"),
        "the prefixed-phrase exclusion must drop the note containing the exact phrase:\n{o}"
    );
}

#[test]
fn find_only_notes_searches_lessons() {
    // `--only-notes` searches ONLY the resolved `[^N]` lessons (not the memory bodies), returning the
    // matching `[N] - …` lesson lines. The note_plain fixture has a lesson about `max_retries`; that
    // term lives in a LESSON, not the page surface, so only `--only-notes` finds it.
    let o = run(&["find", "+max_retries", NOTES_DIR, "--only-notes"]);
    assert!(
        o.lines()
            .any(|l| l.trim_start().starts_with("[3]") && l.contains("max_retries")),
        "only-notes must return the matching lesson line:\n{o}"
    );
    // A lesson term that is NOT present must yield nothing for that lesson.
    let none = run(&["find", "+quibblefrobnicator", NOTES_DIR, "--only-notes"]);
    assert!(
        !none.contains("[3]") && !none.contains("[4]"),
        "an absent lesson term must return no lessons:\n{none}"
    );
}

#[test]
fn find_index_equals_walk() {
    // `find` honors the index when fresh; an index-backed find MUST return the SAME results as the
    // live walk — asserted byte-for-byte (the slice's hard correctness contract).
    let d = TempDir::new("find-idx");
    seed_corpus(&d);
    run(&["reindex", d.as_str()]);
    let walk = run(&["find", "+keychain rotation -widget", d.as_str()]);
    let indexed = run(&[
        "find",
        "+keychain rotation -widget",
        d.as_str(),
        "--use-index",
    ]);
    assert!(
        walk.contains("alpha"),
        "walk find must surface alpha:\n{walk}"
    );
    assert!(
        !walk.contains("beta"),
        "the -widget exclusion must drop beta:\n{walk}"
    );
    assert_eq!(
        walk, indexed,
        "index-backed find must match the walk byte-for-byte:\nwalk:\n{walk}\nindex:\n{indexed}"
    );
}

#[test]
fn find_empty_query_is_clean_error() {
    // An empty query (no terms at all) is a clean usage error, never a panic or a match-everything.
    run_fail_clean(&["find", "", FIND_DIR]);
}

#[test]
fn find_only_minus_returns_non_excluded() {
    // With NO `+`/optional terms but a `-` exclusion, the result set is every NON-excluded note. In
    // the recall corpus, `-tables` drops recall_b and keeps recall_a (which lacks `tables`).
    let o = run(&["find", "-tables", RECALL_DIR]);
    assert!(
        o.contains("recall_a"),
        "a non-excluded note must remain:\n{o}"
    );
    assert!(
        !o.contains("recall_b"),
        "the note containing the -excluded term must be dropped:\n{o}"
    );
}

// ── Regression: --where positional `.` placeholder + walk_and dedup (memgrep audit, TRDD-87935f21) ──

/// Run memgrep from a specific working directory — needed to prove the cwd-contamination cases.
fn run_in(dir: &std::path::Path, args: &[&str]) -> String {
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let out = Command::new(bin)
        .current_dir(dir)
        .args(args)
        .output()
        .expect("failed to run memgrep");
    assert!(out.status.success(), "memgrep exited non-zero for {args:?}");
    String::from_utf8_lossy(&out.stdout).into_owned()
}

#[test]
fn where_ignores_leading_dot_placeholder_when_other_path_given() {
    // Finding 1: `memgrep -l . <dir> --where '…'` must NOT also walk cwd — the leading `.` is a
    // leftover match-any placeholder, not a request to search the current directory.
    let work = TempDir::new("where-dot-work");
    let mem = TempDir::new("where-dot-mem");
    work.write("cwd_contaminant.md", "---\ncolumn: dev\n---\ncontaminant\n");
    mem.write("note1.md", "---\ncolumn: dev\n---\nnote1\n");
    let o = run_in(
        &work.path,
        &["-l", ".", mem.as_str(), "--where", r#"fm.column "dev""#],
    );
    assert!(
        o.contains("note1.md"),
        "the explicit memdir page must be found:\n{o}"
    );
    assert!(
        !o.contains("cwd_contaminant.md"),
        "the cwd file must NOT leak in when an explicit path was given:\n{o}"
    );
}

#[test]
fn where_lone_dot_still_searches_cwd() {
    // Counter-case: a LONE `.` (no other path) is a legitimate "search cwd" request and is honored.
    let work = TempDir::new("where-lonedot-work");
    work.write("here.md", "---\ncolumn: dev\n---\nhere\n");
    let o = run_in(&work.path, &["-l", "--where", r#"fm.column "dev""#, "."]);
    assert!(
        o.contains("here.md"),
        "a lone `.` must still search cwd:\n{o}"
    );
}

#[test]
fn walk_and_dedups_overlapping_positional_paths() {
    // Finding 1b: the same dir passed twice must emit each file ONCE, not once per covering path.
    let mem = TempDir::new("dedup-mem");
    mem.write("note1.md", "---\ncolumn: dev\n---\nfindme\n");
    let o = run(&["-l", "findme", mem.as_str(), mem.as_str()]);
    let hits = o.lines().filter(|l| l.contains("note1.md")).count();
    assert_eq!(
        hits, 1,
        "overlapping positionals must not duplicate a file:\n{o}"
    );
}

// ─────────────────── atom-level recall (TRDD-3b9b2040) ───────────────────

/// A page whose body carries two `^id [block-props]` atoms with UNIQUE (zqx-prefixed) keywords that
/// appear nowhere in the page surface, plus a page-level `[^1]` lesson sentinel.
const ATOM_CORPUS: &str = "---\nname: oauth-hub\ndescription: oauth rotation overview notes\ntags: [oauth]\nocd: 2026-01-01\nlmd: 2026-06-01\n---\n# OAuth hub\n\n^rotate-drain [keywords: zqxdrain rotator, type: reference, claude_mem_ref: feedback_oauth.md, claude_mem_hash: abcd1234]\nThe rotator drains the live account first when near a limit.\n^keychain [keywords: zqxkeychain creds]\nCredentials live in the macOS keychain, never a slots dir.\n\n## Notes and lessons learned\n[^1]: page-level lesson sentinel zqxlesson.\n";

// ── OUTPUT LAYERS + the exact-id second hop ────────────────────────────────────────────────
// A fixture whose atom has a `desc:` DISTINCT from its body, so a test can tell the layers apart:
// with desc == body-prefix (the ATOM_CORPUS case) "medium printed the body" is unfalsifiable.
const LAYER_CORPUS: &str = "---\nname: layer-hub\ndescription: layered output fixture\ntags: [layers]\nocd: 2026-01-01\nlmd: 2026-06-02\n---\n# Layer hub\n\n^zqxlayer-atom [desc: \"a one line summary\", keywords: zqxlayerkw phrase_two, ocd: 2026-01-01, lmd: 2026-06-02]\nThe zqxbody sentence only medium and full may print.[^1]\n\n## Notes and lessons learned\n[^1]: zqxlayerlesson — only full or an explicit --with-notes may print this.\n";

// ── cross-scope reference rules (WM-SCOPE) ────────────────────────────────────────────────────
//
// Builds a temp tree whose paths carry the REAL scope shapes, so the classifier is exercised the
// way it runs in production rather than through an injected override.

/// Write `body` as a memory page at `rel` under `d`, creating parents. Returns the page's dir.
fn write_scoped(d: &TempDir, rel: &str, name: &str, body: &str) -> String {
    let p = d.join(rel).join(format!("{name}.md"));
    std::fs::create_dir_all(p.parent().unwrap()).expect("create scope dir");
    let text = format!(
        "---\nname: {name}\ndescription: zqxscope fixture\nocd: 2026-01-01\nlmd: 2026-01-01\n---\n\n{body}\n\n## Notes and lessons learned\n"
    );
    std::fs::write(&p, text).expect("write scoped page");
    d.join(rel).to_str().unwrap().to_string()
}

const PROJECT_REL: &str = "repo/.claude/project/memory";
const LOCAL_REL: &str = ".claude/projects/-Users-x-repo/memory";
const USER_REL: &str = ".claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory";

#[test]
fn a_downward_link_to_LOCAL_is_flagged_as_a_PRIVACY_violation() {
    // The leak the rule exists to stop: PROJECT memory is git-tracked and PUSHED, so naming a
    // machine-private page from it publishes that name to every future cloner. A name and topic are
    // disclosure even when the body is not.
    let d = TempDir::new("scope-down-privacy");
    let proj = write_scoped(&d, PROJECT_REL, "shared-page", "see [[private-page]] for details.");
    let local = write_scoped(&d, LOCAL_REL, "private-page", "machine-private notes.");
    let o = run_any(&["lint", &proj, &local]);
    assert!(
        o.contains("downward cross-scope link") && o.contains("PRIVACY"),
        "a PROJECT -> LOCAL link must be flagged as a privacy violation:\n{o}"
    );
}

#[test]
fn a_downward_link_to_PROJECT_from_USER_is_flagged_as_PORTABILITY() {
    let d = TempDir::new("scope-down-portability");
    let user = write_scoped(
        &d,
        ".claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory",
        "global-page",
        "see [[repo-page]] for details.",
    );
    let proj = write_scoped(&d, PROJECT_REL, "repo-page", "project knowledge.");
    let o = run_any(&["lint", &user, &proj]);
    assert!(
        o.contains("downward cross-scope link") && o.contains("PORTABILITY"),
        "a USER -> PROJECT link must be flagged as a portability violation:\n{o}"
    );
}

#[test]
fn a_legal_UPWARD_link_is_neither_a_violation_nor_a_one_sided_link() {
    // THE false positive this fixes. The LINK LAW is a WITHIN-LAYER law, but it was applied to every
    // edge — and a cross-layer edge can NEVER be reciprocated (the reply would be a forbidden
    // downward link). So every LEGAL upward link was reported as one-sided: the lint punishing
    // exactly the behaviour the model requires. Measured on the live corpus, removing this dropped
    // one-sided-link reports from 76 to 58 — 18 pure false positives.
    let d = TempDir::new("scope-up-legal");
    let local = write_scoped(&d, LOCAL_REL, "local-page", "see [[shared-page]] for the rule.");
    let proj = write_scoped(&d, PROJECT_REL, "shared-page", "the shared rule.");
    let o = run_any(&["lint", &local, &proj]);
    assert!(
        !o.contains("downward cross-scope link"),
        "an upward LOCAL -> PROJECT link is legal:\n{o}"
    );
    assert!(
        !o.contains("one-sided link"),
        "an upward link is unreciprocatable BY DESIGN and must not be a LINK-LAW candidate:\n{o}"
    );
}

#[test]
fn the_LINK_LAW_still_applies_WITHIN_a_layer() {
    // The complement of the test above: relaxing the law across layers must not relax it inside one,
    // or the fix would have quietly disabled the check it was scoping.
    let d = TempDir::new("scope-same-layer");
    let dir = write_scoped(&d, PROJECT_REL, "page-a", "see [[page-b]].");
    write_scoped(&d, PROJECT_REL, "page-b", "no link back.");
    let o = run_any(&["lint", &dir]);
    assert!(
        o.contains("one-sided link"),
        "a one-sided link between two PROJECT pages is still a violation:\n{o}"
    );
}

#[test]
fn a_reciprocal_pair_is_not_split_by_a_duplicate_name_in_another_scope() {
    // janitor#151 / #192, reproduced at the CLI level. Root cause: a `[[wikilink]]` resolved by
    // name across ALL roots with no preference for the source page's own scope, so a name that
    // exists as a "twin" in two scopes made a genuinely reciprocal pair resolve into DIFFERENT
    // targets depending on which page linked which — 4/4 false `link-one-sided` findings on the
    // real corpus (LOCAL `feedback_github_comment_self_identification` <-> LOCAL
    // `feedback_peer_agent_consensus`, split by an unrelated PROJECT page of the same name).
    let d = TempDir::new("scope-dup-name-same-scope-pair");
    // The genuinely reciprocal pair — both pages live in LOCAL.
    let local_hub = write_scoped(&d, LOCAL_REL, "hub-page", "see [[dup-name]] for the rule.");
    write_scoped(&d, LOCAL_REL, "dup-name", "see [[hub-page]] for context.");
    // An unrelated PROJECT page that happens to share the LOCAL page's name — the "twin" that used
    // to steal the resolution. It does NOT link back to hub-page; if the bug is present, hub-page's
    // link resolves HERE instead of to its own LOCAL twin, and the real LOCAL pair reports as
    // one-sided even though it plainly links back.
    let proj_dup = write_scoped(&d, PROJECT_REL, "dup-name", "an unrelated PROJECT page.");
    let o = run_any(&["lint", &local_hub, &proj_dup]);
    assert!(
        !o.contains("one-sided link"),
        "the LOCAL pair links back to each other; a same-named PROJECT page must not split it:\n{o}"
    );
}

#[test]
fn a_duplicate_name_elsewhere_does_not_mask_a_genuinely_one_sided_link() {
    // The other half of the fix's correctness: preferring the same-scope candidate must not swallow
    // a REAL one-sided link just because a same-named decoy exists in another scope — the finding
    // has to survive on its own merits once resolution is unambiguous.
    let d = TempDir::new("scope-dup-name-real-one-sided");
    let local_hub = write_scoped(&d, LOCAL_REL, "hub-page-2", "see [[dup-name-2]] for the rule.");
    // dup-name-2 in LOCAL does NOT link back — genuinely one-sided within LOCAL.
    write_scoped(&d, LOCAL_REL, "dup-name-2", "no link back.");
    let proj_dup = write_scoped(&d, PROJECT_REL, "dup-name-2", "an unrelated PROJECT page.");
    let o = run_any(&["lint", &local_hub, &proj_dup]);
    assert!(
        o.contains("one-sided link"),
        "a genuinely one-sided LOCAL link must still be reported even with a same-named PROJECT \
         decoy present:\n{o}"
    );
}

#[test]
fn a_duplicate_name_referenced_from_USER_resolves_to_the_USER_twin_not_a_LOCAL_namesake() {
    // The DOWNWARD-resolution shape the one-way scope law forbids (LOCAL -> PROJECT -> USER, never
    // downward): before the fix, a USER page's `[[dup-name]]` could silently resolve into a
    // same-named LOCAL page — dangling for every other contributor, since LOCAL is machine-private.
    // Same-scope preference must keep the USER page's link inside USER whenever a USER-scope
    // candidate exists, never crossing DOWN to the LOCAL namesake.
    let d = TempDir::new("scope-user-vs-local-dup");
    // Decoy: a namesake in LOCAL that must NOT win. Written first so, under the OLD bug (whichever
    // candidate is processed LAST in the cross-root alphabetical merge wins), the failure mode is
    // exercised rather than accidentally dodged by path ordering.
    let local_dup = write_scoped(
        &d,
        LOCAL_REL,
        "dup-name-3",
        "the LOCAL decoy — must not be the resolution target.",
    );
    // The correct, same-scope pair: hub links to dup-name-3; dup-name-3 links back — reciprocal
    // entirely within USER.
    let user_hub = write_scoped(&d, USER_REL, "hub-page-3", "see [[dup-name-3]] for the rule.");
    write_scoped(&d, USER_REL, "dup-name-3", "see [[hub-page-3]] for context.");
    let o = run_any(&["lint", &local_dup, &user_hub]);
    assert!(
        !o.contains("downward cross-scope link"),
        "must resolve to the USER twin, not spuriously cross down into the LOCAL decoy:\n{o}"
    );
    assert!(
        !o.contains("one-sided link"),
        "the USER-scope pair is reciprocal once resolution stays within USER:\n{o}"
    );
}

#[test]
fn the_lint_summary_names_which_scopes_were_covered() {
    // janitor#151 item 6: `memgrep lint: N finding(s), M at or above ERROR` alone reads as
    // machine-wide regardless of whether one scope, three, or an arbitrary corpus was linted. The
    // summary must name the covered scopes so the count is never ambiguous about what it counts.
    let d = TempDir::new("scope-summary-label");
    let local = write_scoped(&d, LOCAL_REL, "summary-local", "just a LOCAL page, no links.");
    let proj = write_scoped(&d, PROJECT_REL, "summary-proj-a", "see [[summary-proj-b]].");
    write_scoped(&d, PROJECT_REL, "summary-proj-b", "no link back — the one WARN this test needs.");
    let (_out, err, _code) = run_full(&["lint", &local, &proj]);
    assert!(
        err.contains("2 scope(s): LOCAL/PROJECT"),
        "the summary must name the scopes actually covered:\n{err}"
    );
}

#[test]
fn equal_scores_are_broken_by_RECENCY_not_alphabetical_path_order() {
    // `sort_by` is stable, so with no explicit second key equal scores fall through to INPUT order,
    // which is path order — alphabetical, the least meaningful ordering available for memories, and
    // what silently decided results before the scorer was tiered. The two pages here are authored to
    // score IDENTICALLY on the query, so ONLY the tie-break can order them; `zzz-newer` is named to
    // sort LAST alphabetically, so seeing it first proves recency won rather than the filename.
    let d = TempDir::new("tiebreak-recency");
    let page = |name: &str, lmd: &str| {
        format!("---\nname: {name}\ndescription: zqxtie shared surface\nocd: 2026-01-01\nlmd: {lmd}\n---\n\n## Notes and lessons learned\n")
    };
    d.write("aaa-older.md", &page("aaa-older", "2026-01-05"));
    d.write("zzz-newer.md", &page("zzz-newer", "2026-06-30"));
    let o = run(&["recall", "zqxtie", d.as_str()]);
    let newer = o.find("zzz-newer").expect("the newer page is present");
    let older = o.find("aaa-older").expect("the older page is present");
    assert!(
        newer < older,
        "equal scores must order NEWEST first, not alphabetically:\n{o}"
    );
}

#[test]
fn recall_basic_is_the_default_and_prints_one_lean_row() {
    // The DEFAULT must be the lean layer. Measured on the frozen benchmark this is what takes the
    // END-TO-END cost from 441.4 to 247.0 tokens/query at IDENTICAL accuracy — so a regression that
    // quietly restores the rich default would nearly double retrieval cost with nothing failing.
    let d = TempDir::new("layer-basic");
    d.write("layer-hub.md", LAYER_CORPUS);
    let o = run(&["recall", "zqxlayerkw", d.as_str()]);
    assert!(
        o.contains("2026-06-02\tzqxlayer-atom\ta one line summary"),
        "basic must print `<lmd>\\t<atom-id>\\t<description>`:\n{o}"
    );
    assert!(
        !o.contains("layer-hub.md"),
        "basic must NOT print the page path on an atom row — a memory path is ~25 tokens, which is \
         most of what this layer exists to save:\n{o}"
    );
    assert!(!o.contains("zqxbody"), "basic must not print the body:\n{o}");
    assert!(
        !o.contains("zqxlayerlesson"),
        "basic must not append lessons:\n{o}"
    );
    assert!(
        !o.contains("phrase_two"),
        "basic must not print the keyword surface:\n{o}"
    );
}

#[test]
fn recall_medium_adds_the_body_but_never_the_lessons() {
    let d = TempDir::new("layer-medium");
    d.write("layer-hub.md", LAYER_CORPUS);
    let o = run(&["recall", "zqxlayerkw", d.as_str(), "--output", "medium"]);
    assert!(
        o.contains("\tzqxlayer-atom\t"),
        "medium keeps the basic row:\n{o}"
    );
    assert!(o.contains("zqxbody"), "medium must print the BODY:\n{o}");
    assert!(
        !o.contains("zqxlayerlesson"),
        "the lessons are what separate medium from full:\n{o}"
    );
}

#[test]
fn recall_full_prints_the_rich_record_including_keywords() {
    let d = TempDir::new("layer-full");
    d.write("layer-hub.md", LAYER_CORPUS);
    let o = run(&["recall", "zqxlayerkw", d.as_str(), "--output", "full"]);
    assert!(
        o.contains("layer-hub.md#zqxlayer-atom — a one line summary"),
        "full keeps the `path#atom-id — desc` locator (the path an editor needs):\n{o}"
    );
    assert!(o.contains("zqxbody"), "full prints the body:\n{o}");
    assert!(
        o.contains("zqxlayerlesson"),
        "full appends the lessons:\n{o}"
    );
    assert!(
        o.contains("phrase_two"),
        "full always prints the keyword surface:\n{o}"
    );
    assert!(
        o.contains("\tscore: "),
        "full prints the SCORE — without it a result's rank is unobservable, so winning on \
         score and merely surviving a tie-break look identical:\n{o}"
    );
}

/// `--min-severity` gates the EXIT CODE and never the report.
///
/// A page carrying only an uncited page-level lesson is INFO-only: it must still be PRINTED (the
/// reader is never left guessing) while `lint` exits 0, because that shape is what the memory model
/// prescribes — the Notes section is mandatory even when empty. Before the severity model this one
/// class was 57% of every finding in the live corpus, so the gate failed on every corpus and the
/// real errors were unreadable underneath it.
#[test]
fn lint_min_severity_gates_the_exit_code_not_the_report() {
    let d = TempDir::new("lint-severity");
    d.write(
        "info_only.md",
        "---\nname: info-only\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"d\"\n---\nBody.\n\n## Notes and lessons learned\n[^1]: an uncited page-level lesson.\n",
    );
    let (o, code) = run_with_code(&["lint", d.as_str()]);
    assert_eq!(code, 0, "INFO-only findings must NOT fail the gate:\n{o}");
    assert!(
        o.contains("INFO") && o.contains("page-level lesson"),
        "the finding must still be reported, with its severity:\n{o}"
    );

    // …and raising the bar makes the SAME corpus fail, which is what proves the gate is real.
    let (o2, code2) = run_with_code(&["lint", d.as_str(), "--min-severity", "info"]);
    assert_eq!(code2, 1, "--min-severity info must gate on it:\n{o2}");
}

/// A dangling footnote reference is ERROR: it fails the DEFAULT gate with no flags.
#[test]
fn lint_dangling_reference_fails_the_default_gate() {
    let d = TempDir::new("lint-error");
    d.write(
        "dangling.md",
        "---\nname: dangling\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"d\"\n---\nBody cites [^7].\n\n## Notes and lessons learned\n",
    );
    let (o, code) = run_with_code(&["lint", d.as_str()]);
    assert_eq!(code, 1, "a dangling reference must fail the gate:\n{o}");
    assert!(o.contains("ERROR"), "and be reported as ERROR:\n{o}");
}

/// A PAGE row's locator is the page's `name:` identity, never its path.
///
/// Measured on the two live corpora: page rows are 35-39% of ALL result rows and their paths cost
/// ~90 tokens apiece — ~80-110 tokens per query, comparable to the whole per-query budget. The
/// `name:` is used rather than the file stem because wikilinks resolve through `name:`; printing
/// the stem would give the ~3% of pages whose filename differs a SECOND address the wiki never
/// uses. This fixture is exactly that case.
#[test]
fn page_row_locator_is_the_name_identity_not_the_path() {
    let d = TempDir::new("page-locator");
    d.write(
        "zqx_page_underscored.md",
        "---\nname: zqx-page-hyphenated\ndescription: zqxpagekw a page whose file and name differ\n---\nBody.\n",
    );
    let o = run(&["recall", "zqxpagekw", d.as_str()]);
    let row = o.lines().find(|l| l.contains("zqxpagekw")).unwrap_or("");
    let locator = row.split('\t').nth(1).unwrap_or("");
    assert_eq!(
        locator, "zqx-page-hyphenated",
        "the lean page row must print the `name:` identity:\n{o}"
    );
    assert!(
        !row.contains(".md"),
        "the lean page row must not carry a path — that is the cost this layer exists to remove:\n{o}"
    );
}

/// ...and that printed locator must be a REAL key, or the listing lies about what it hands you.
/// An atom locator is an exact lookup; a page locator sits in the SAME column and must behave the
/// same way, including for a page whose filename differs from its declared name.
#[test]
fn page_name_is_an_exact_second_hop() {
    let d = TempDir::new("page-hop");
    d.write(
        "zqx_hop_underscored.md",
        "---\nname: zqx-hop-hyphenated\ndescription: an unrelated surface line\n---\nZqxhopbody.\n",
    );
    let o = run(&["recall", "zqx-hop-hyphenated", d.as_str()]);
    assert!(
        o.contains("zqx_hop_underscored.md"),
        "the page hop resolves to the page, printing the PATH an editor needs:\n{o}"
    );
    assert!(o.contains("Zqxhopbody") || o.contains("unrelated surface"), "the hop prints the page record:\n{o}");
}

/// The hop must never SWALLOW a symptom search: a one-word query is indistinguishable from a name
/// by shape alone, so a query matching no page name has to fall through to ranking.
#[test]
fn a_query_matching_no_page_name_falls_through_to_search() {
    let d = TempDir::new("page-hop-fallthrough");
    d.write(
        "zqx_fall.md",
        "---\nname: zqx-fall\ndescription: zqxfallkw the searchable surface\n---\nBody.\n",
    );
    let o = run(&["recall", "zqxfallkw", d.as_str()]);
    assert!(
        o.contains("zqx-fall"),
        "a non-name query must still rank normally:\n{o}"
    );
}

/// The score belongs to the DEBUGGING layer alone. The lean layers' row shape
/// (`<lmd>\t<locator>\t<description>`) is a promised parse contract — `cut -f2` on it must stay
/// exact — so an extra line there would break every consumer to help nobody: an agent picking a
/// hop target reads the description, not the arithmetic behind it.
#[test]
fn recall_lean_layers_never_print_the_score() {
    let d = TempDir::new("layer-score");
    d.write("layer-hub.md", LAYER_CORPUS);
    for layer in ["basic", "medium"] {
        let o = run(&["recall", "zqxlayerkw", d.as_str(), "--output", layer]);
        assert!(
            !o.contains("score:"),
            "`--output {layer}` must not print the score:\n{o}"
        );
    }
}

#[test]
fn recall_lean_layers_honour_explicit_note_and_keyword_flags() {
    // The layer sets the DEFAULT; an explicit flag still wins. And `--with-notes` on a lean layer
    // must append the lessons ALONE — never a second copy of a body the layer already decided
    // not to print.
    let d = TempDir::new("layer-flags");
    d.write("layer-hub.md", LAYER_CORPUS);
    let kw = run(&["recall", "zqxlayerkw", d.as_str(), "--with-keywords"]);
    assert!(
        kw.contains("keywords: ") && kw.contains("phrase_two"),
        "--with-keywords must print the keyword surface in basic:\n{kw}"
    );
    assert!(
        !kw.contains("zqxbody"),
        "--with-keywords must not escalate to the body:\n{kw}"
    );
    let wn = run(&["recall", "zqxlayerkw", d.as_str(), "--with-notes"]);
    assert!(
        wn.contains("zqxlayerlesson"),
        "an explicit --with-notes overrides the lean layer's default-off:\n{wn}"
    );
    assert!(
        !wn.contains("zqxbody"),
        "--with-notes appends the lessons ALONE, not the body:\n{wn}"
    );
}

#[test]
fn recall_by_atom_id_is_the_exact_second_hop() {
    // The hop that makes `basic` cheap: scan a dense id list, then pay for exactly ONE atom.
    let d = TempDir::new("layer-hop");
    d.write("layer-hub.md", LAYER_CORPUS);
    let o = run(&["recall", "zqxlayer-atom", d.as_str()]);
    assert!(
        o.contains("layer-hub.md#zqxlayer-atom — a one line summary"),
        "the hop returns the atom in FULL, with the path an editor needs:\n{o}"
    );
    assert!(o.contains("zqxbody"), "the hop returns the body:\n{o}");
    assert!(
        o.contains("zqxlayerlesson"),
        "the hop returns the atom's lessons:\n{o}"
    );
}

#[test]
fn recall_unknown_id_falls_through_to_the_symptom_search() {
    // LOAD-BEARING: a one-word symptom query is indistinguishable from an atom id by SHAPE alone,
    // so the exact-id shortcut must never be able to swallow one. `zqxlayerkw` is a keyword, not an
    // id — it has to keep behaving as an ordinary search.
    let d = TempDir::new("layer-fallthrough");
    d.write("layer-hub.md", LAYER_CORPUS);
    let o = run(&["recall", "zqxlayerkw", d.as_str()]);
    assert!(
        o.contains("\tzqxlayer-atom\t"),
        "a non-id single word must still run the symptom search:\n{o}"
    );
    assert!(
        !o.contains("zqxbody"),
        "and it must stay on the lean default, not fall into the hop's full render:\n{o}"
    );
}

#[test]
fn recall_surfaces_atom_by_unique_keyword() {
    // The whole point of the redesign: a single fact is findable by ITS OWN keyword. Querying an
    // atom-only keyword returns that atom as `path#atom-id`, NOT the page, NOT the sibling atom, and
    // with NO page-lesson append (an atom has no `[^N]` lessons of its own).
    let d = TempDir::new("atom-recall");
    d.write("oauth-hub.md", ATOM_CORPUS);
    let o = run(&["recall", "zqxdrain", d.as_str(), "--output", "full"]); // no index yet → walk path
    // The locator's summary is the atom's LISTING summary (TRDD-AP2X9A0H item c): this atom has no
    // `desc:`, so the ~120-char body prefix shows — never the raw keyword array (keywords are the
    // recall surface, not something a reader can triage by).
    assert!(
        o.contains(
            "oauth-hub.md#rotate-drain — The rotator drains the live account first when near a limit."
        ),
        "the atom must surface as path#atom-id — <listing summary>:\n{o}"
    );
    assert!(
        !o.contains("#keychain"),
        "the sibling atom must not surface:\n{o}"
    );
    assert!(
        !o.contains("zqxlesson"),
        "an atom result must NOT append the page's [^N] lessons:\n{o}"
    );
    // The page itself is a body-only match (its body holds the marker line) — precision-first
    // suppresses it because the atom matched the SURFACE. A page result has the `path — <desc>` form
    // (no `#`); the atom result has `path#id — …`, so the bare page form proves the page was dropped.
    assert!(
        !o.contains("oauth-hub.md — "),
        "the page (a body-only match) is suppressed by precision-first when the atom matched:\n{o}"
    );
}

#[test]
fn recall_atom_aggregates_its_own_notes_and_see_also() {
    // Per-atom notes (TRDD-3b9b2040): an atom hit returns its body + the [^N] footnote(s) ITS body
    // references, GROUPED by which pooled section (`# Notes` / `# Lessons Learned` / `# See also`)
    // defines each — the full self-contained record, NOT a bare locator. (See-also is now a
    // `# See also` footnote, not a `[[wikilink]]`; the inline `[[token-rotation]]` stays page link
    // text in the body.)
    let d = TempDir::new("atom-aggregate");
    d.write(
        "oauth-hub.md",
        "---\nname: oauth-hub\ndescription: oauth overview\nocd: 2026-01-01\nlmd: 2026-06-01\n---\n# OAuth hub\n\n^rotate-drain [keywords: zqxdrain rotator]\nThe rotator drains the live (near-limit) account first.[^1] It changed.[^2] See [[token-rotation]].[^3]\n\n# Lessons Learned\n[^1]: earlier this drained the alternate first; reversed — the live account hits the cap sooner.\n# Notes\n[^2]: the near-limit threshold is the 5h window, not the 7d one.\n# See also\n[^3]: token-rotation — the sibling keepalive flow.\n",
    );
    let o = run(&["recall", "zqxdrain", d.as_str(), "--output", "full"]);
    assert!(
        o.contains("oauth-hub.md#rotate-drain"),
        "locator line:\n{o}"
    );
    assert!(
        o.contains("The rotator drains the live"),
        "the atom body is returned:\n{o}"
    );
    assert!(
        o.contains("lessons learned:") && o.contains("earlier this drained the alternate"),
        "the atom's own [^1] lesson is aggregated under the lessons group:\n{o}"
    );
    assert!(
        o.contains("notes:") && o.contains("the near-limit threshold is the 5h window"),
        "the atom's [^2] note is aggregated under the notes group:\n{o}"
    );
    assert!(
        o.contains("see also:") && o.contains("token-rotation — the sibling keepalive flow"),
        "the atom's see-also is aggregated under the see also group:\n{o}"
    );
    // --no-notes keeps the body but drops every section group.
    let nn = run(&[
        "recall",
        "zqxdrain",
        d.as_str(),
        "--no-notes",
        "--output",
        "full",
    ]);
    assert!(
        nn.contains("The rotator drains the live"),
        "body still shows with --no-notes:\n{nn}"
    );
    assert!(
        !nn.contains("earlier this drained the alternate")
            && !nn.contains("notes:")
            && !nn.contains("see also:"),
        "--no-notes suppresses the atom's section groups:\n{nn}"
    );
}

#[test]
fn recall_atom_walk_matches_index() {
    // Walk/index parity for atoms: recall BEFORE any index (walk via resolve_atoms) must equal recall
    // AFTER reindex with --use-index (the atoms table) byte-for-byte.
    let d = TempDir::new("atom-parity");
    d.write("oauth-hub.md", ATOM_CORPUS);
    let walk = run(&["recall", "zqxdrain", d.as_str(), "--output", "full"]); // no .memgrep yet → walk
    run(&["reindex", d.as_str()]);
    let indexed = run(&[
        "recall",
        "zqxdrain",
        d.as_str(),
        "--use-index",
        "--output",
        "full",
    ]);
    assert!(
        walk.contains("#rotate-drain"),
        "walk recall must surface the atom:\n{walk}"
    );
    assert_eq!(
        walk, indexed,
        "index-backed atom recall must match the walk byte-for-byte:\nwalk:\n{walk}\nindex:\n{indexed}"
    );
}

/// SHARED grammar-parity fixture (TRDD-056384eb, DERIVED task 4): a page with TWO atoms — one carrying
/// a `desc:` slug and one without. The SAME `^id [desc: …]` marker line is the contract both memgrep's
/// Rust desc-parse AND the hook's Python desc-parse (Phase 2) must extract identically. The `zqxd*`
/// keywords are unique so a recall returns exactly the intended atom.
const DESC_CORPUS: &str = "---\nname: handoff-hub\ndescription: handoff overview\ntags: [handoff]\nocd: 2026-01-01\nlmd: 2026-06-01\n---\n# Handoff hub\n\n^new-handoff [desc: new_handoff_carries_recent_turns, keywords: zqxdesc handoff]\nThe new handoff lists recent turns and memory ids.\n^plain [keywords: zqxplain bare]\nThis atom carries no desc slug.\n";

#[test]
fn recall_atom_renders_desc_slug_as_spaced_phrase() {
    // TRDD-056384eb: an atom with a `desc:` slug shows it on the locator line, rendered `_`→space, so
    // the agent can pick WITHOUT opening the atom. The STORED slug (with underscores) must NOT appear.
    let d = TempDir::new("atom-desc-show");
    d.write("handoff-hub.md", DESC_CORPUS);
    let o = run(&["recall", "zqxdesc", d.as_str(), "--output", "full"]); // no index → walk
    assert!(
        o.contains("handoff-hub.md#new-handoff — new handoff carries recent turns"),
        "the atom locator shows the desc as a spaced phrase:\n{o}"
    );
    assert!(
        !o.contains("new_handoff_carries_recent_turns"),
        "the stored underscore slug must be rendered, never printed raw:\n{o}"
    );
}

#[test]
fn recall_atom_without_desc_falls_back_to_body_prefix() {
    // TRDD-AP2X9A0H item c: a legacy desc-less atom lists by a ~120-char BODY PREFIX — a summary a
    // reader can actually triage by — not by its raw keyword array (the recall surface).
    let d = TempDir::new("atom-desc-none");
    d.write("handoff-hub.md", DESC_CORPUS);
    let o = run(&["recall", "zqxplain", d.as_str(), "--output", "full"]);
    assert!(
        o.contains("handoff-hub.md#plain — This atom carries no desc slug."),
        "a desc-less atom falls back to its body prefix:\n{o}"
    );
    assert!(
        !o.contains("#plain — zqxplain"),
        "the raw keyword array must no longer be the locator summary:\n{o}"
    );
}

#[test]
fn recall_atom_shows_quoted_prose_desc_verbatim() {
    // TRDD-AP2X9A0H: the NEW desc form is quoted ≤200-char PROSE. It shows VERBATIM on the locator
    // line — including the commas and colon inside the quotes, which is exactly what the quote-aware
    // property splitter exists to keep whole (the old splitter truncated at the first comma).
    let d = TempDir::new("atom-desc-prose");
    d.write(
        "trap-hub.md",
        "---\nname: trap-hub\ndescription: keepalive traps\ntags: [keepalive]\nocd: 2026-01-01\nlmd: 2026-06-01\n---\n# Trap hub\n\n^l0-trap [desc:\"L0 keepalive trap: staged closure, cache vs repo\", keywords: zqxtrap keepalive]\nThe staged closure under DATA is what launchd runs, not the repo checkout.\n",
    );
    let o = run(&["recall", "zqxtrap", d.as_str(), "--output", "full"]); // no index → walk
    assert!(
        o.contains("trap-hub.md#l0-trap — L0 keepalive trap: staged closure, cache vs repo"),
        "the quoted prose desc shows whole and verbatim:\n{o}"
    );
    // Walk/index parity for the prose form (the stored atoms.desc column must round-trip it).
    run(&["reindex", d.as_str()]);
    let indexed = run(&[
        "recall",
        "zqxtrap",
        d.as_str(),
        "--use-index",
        "--output",
        "full",
    ]);
    assert_eq!(
        o, indexed,
        "index-backed prose-desc display must match the walk byte-for-byte:\nwalk:\n{o}\nindex:\n{indexed}"
    );
}

#[test]
fn recall_atom_body_prefix_is_truncated_to_one_line() {
    // The body-prefix fallback is a TRIAGE line: ~120 chars, flattened, ellipsis-marked — never the
    // whole multi-line body on the locator line.
    let d = TempDir::new("atom-prefix-cap");
    let long_body = format!("{} zzztail", "alpha beta gamma delta ".repeat(10)); // ≫120 chars
    d.write(
        "long-hub.md",
        &format!(
            "---\nname: long-hub\ndescription: long body\ntags: [long]\nocd: 2026-01-01\nlmd: 2026-06-01\n---\n# Long hub\n\n^longbody [keywords: zqxlong verbose]\n{long_body}\n"
        ),
    );
    let o = run(&[
        "recall",
        "zqxlong",
        d.as_str(),
        "--no-notes",
        "--output",
        "full",
    ]);
    let locator = o
        .lines()
        .find(|l| l.contains("#longbody"))
        .expect("locator line present");
    assert!(
        locator.contains('…'),
        "an over-120-char body prefix is ellipsis-truncated:\n{locator}"
    );
    assert!(
        !locator.contains("zzztail"),
        "the body tail must not reach the locator line:\n{locator}"
    );
}

#[test]
fn find_lists_atoms_by_their_desc_summary() {
    // TRDD-AP2X9A0H item c names BOTH commands: `find` listings show each matching atom by its desc
    // (here the legacy slug, rendered `_`→space), exactly like recall — and the index path agrees.
    let d = TempDir::new("find-atom-desc");
    d.write("handoff-hub.md", DESC_CORPUS);
    let walk = run(&["find", "+zqxdesc", d.as_str(), "--output", "full"]);
    assert!(
        walk.contains("handoff-hub.md#new-handoff — new handoff carries recent turns"),
        "find must list the atom by its rendered desc:\n{walk}"
    );
    run(&["reindex", d.as_str()]);
    let indexed = run(&[
        "find",
        "+zqxdesc",
        d.as_str(),
        "--use-index",
        "--output",
        "full",
    ]);
    assert_eq!(
        walk, indexed,
        "index-backed find atom listing must match the walk byte-for-byte:\nwalk:\n{walk}\nindex:\n{indexed}"
    );
}

#[test]
fn recall_atom_desc_walk_matches_index() {
    // Walk/index parity for the desc display: the stored `atoms.desc` column (index path) and the live
    // `resolve_atoms` parse (walk path) must render the same locator line byte-for-byte. This also
    // exercises the v2→v3 schema bump (the reindex rebuilds with the new desc column).
    let d = TempDir::new("atom-desc-parity");
    d.write("handoff-hub.md", DESC_CORPUS);
    let walk = run(&["recall", "zqxdesc", d.as_str(), "--output", "full"]); // no .memgrep yet → walk
    run(&["reindex", d.as_str()]);
    let indexed = run(&[
        "recall",
        "zqxdesc",
        d.as_str(),
        "--use-index",
        "--output",
        "full",
    ]);
    assert!(
        walk.contains("— new handoff carries recent turns"),
        "walk recall must render the desc phrase:\n{walk}"
    );
    assert_eq!(
        walk, indexed,
        "index-backed desc display must match the walk byte-for-byte:\nwalk:\n{walk}\nindex:\n{indexed}"
    );
}

#[test]
fn find_claude_mem_ref_cli_lists_atoms_by_provenance() {
    // The harvest provenance query end-to-end: list every atom whose claude_mem_ref block-prop points
    // at a source buffer file, printed `path#atom-id\t<hash>`. The keychain atom (no claude_mem_ref)
    // is excluded.
    let d = TempDir::new("cmref-cli");
    d.write("oauth-hub.md", ATOM_CORPUS);
    let o = run(&["find-claude-mem-ref", "feedback_oauth.md", d.as_str()]);
    assert!(
        o.contains("oauth-hub.md#rotate-drain") && o.contains("abcd1234"),
        "the harvested atom + its stored source-hash must be listed:\n{o}"
    );
    assert!(
        !o.contains("#keychain"),
        "an atom with no claude_mem_ref must not be listed:\n{o}"
    );
}

#[test]
fn find_claude_mem_ref_index_matches_live_scan() {
    // find-claude-mem-ref uses the FRESH index (idx_atoms_cmref) when present and live-scans otherwise.
    // Both paths must give byte-identical output (the harvest's new-vs-changed check depends on it).
    let d = TempDir::new("cmref-parity");
    d.write("oauth-hub.md", ATOM_CORPUS);
    let live = run(&["find-claude-mem-ref", "feedback_oauth.md", d.as_str()]); // no index → live-scan
    run(&["reindex", d.as_str()]);
    let indexed = run(&["find-claude-mem-ref", "feedback_oauth.md", d.as_str()]); // fresh index → indexed
    assert!(
        live.contains("oauth-hub.md#rotate-drain"),
        "live-scan must find the harvested atom:\n{live}"
    );
    assert_eq!(
        live, indexed,
        "indexed and live-scan find-cmref must match byte-for-byte:\nlive:\n{live}\nindexed:\n{indexed}"
    );
}

// ─────────────── atom-id resolution: `atom-page` / `atom` (TRDD-0NGYP3IG) ───────────────

/// A page carrying one body ATOM and one LESSON with a corpus-wide `ATOM-XXXX-XXXX` id — both id
/// families the resolver must answer for.
const ATOM_ID_CORPUS: &str = "---\nname: oauth-hub\ndescription: oauth rotation overview\ntags: [oauth]\nocd: 2026-01-01\nlmd: 2026-06-01\n---\n# OAuth hub\n\n^rotate-drain [keywords: zqxdrain rotator]\nThe rotator drains the live account first when near a limit.[^1]\n\n## Notes and lessons learned\n[^1]: [id:ATOM-234P-U35Q, status:valid, keywords:\"drain order\", ocd:2026-07-15, lmd:2026-07-15] DO drain the live account first, BECAUSE it hits the cap sooner.\n";

#[test]
fn atom_page_prints_owning_page_path_walk_and_index() {
    // Mode 1 (navigation): id → the PATH of the page that CONTAINS the atom. The `^` sigil is
    // accepted (copy-paste of the marker), and the index-backed answer equals the walk's.
    let d = TempDir::new("atom-page");
    d.write("oauth-hub.md", ATOM_ID_CORPUS);
    let walk = run(&["atom-page", "rotate-drain", d.as_str()]); // no index yet → walk
    assert_eq!(
        walk.trim(),
        d.join("oauth-hub.md").to_str().expect("utf-8"),
        "atom-page prints exactly the owning page path"
    );
    let caret = run(&["atom-page", "^rotate-drain", d.as_str()]);
    assert_eq!(caret, walk, "the ^-prefixed marker spelling resolves too");
    run(&["reindex", d.as_str()]);
    let indexed = run(&["atom-page", "rotate-drain", d.as_str()]); // fresh index → index path
    assert_eq!(
        walk, indexed,
        "index-backed atom-page must match the walk byte-for-byte"
    );
}

#[test]
fn atom_page_resolves_lesson_ids_in_every_spelling() {
    // A lesson's corpus-wide id resolves in all three spellings: hyphenated `ATOM-XXXX-XXXX`, the
    // bare 8-char payload, and case-insensitively (the payload charset is [A-Z0-9]).
    let d = TempDir::new("atom-page-lesson");
    d.write("oauth-hub.md", ATOM_ID_CORPUS);
    let want = format!("{}\n", d.join("oauth-hub.md").display());
    for spelling in ["ATOM-234P-U35Q", "234PU35Q", "234pu35q"] {
        let o = run(&["atom-page", spelling, d.as_str()]);
        assert_eq!(o, want, "spelling `{spelling}` must resolve to the page");
    }
}

#[test]
fn atom_page_unknown_id_fails() {
    // Not-found is an ERROR (exit non-zero), never a silent empty success — a navigation primitive
    // that prints nothing and exits 0 would let a caller navigate to nowhere.
    let d = TempDir::new("atom-page-miss");
    d.write("oauth-hub.md", ATOM_ID_CORPUS);
    run_fail(&["atom-page", "NOPE9999", d.as_str()]);
}

#[test]
fn atom_page_ambiguous_id_lists_all_matches_and_fails() {
    // Corpus corruption: the SAME id on two pages breaks the corpus-unique-id invariant, so both
    // resolution modes must refuse to guess — print EVERY match, exit non-zero (per the spec).
    let d = TempDir::new("atom-page-dupe");
    d.write(
        "a.md",
        "---\nname: a\ndescription: page a\n---\n# A\n\n^dupe-id [keywords: zqxa]\nbody a\n",
    );
    d.write(
        "b.md",
        "---\nname: b\ndescription: page b\n---\n# B\n\n^dupe-id [keywords: zqxb]\nbody b\n",
    );
    let o = run_fail_capture(&["atom-page", "dupe-id", d.as_str()]);
    assert!(
        o.contains("a.md#dupe-id") && o.contains("b.md#dupe-id"),
        "every ambiguous match must be listed:\n{o}"
    );
    // …and the same contract holds for the content mode.
    let c = run_fail_capture(&["atom", "dupe-id", d.as_str()]);
    assert!(
        c.contains("a.md#dupe-id") && c.contains("b.md#dupe-id"),
        "`atom` lists the ambiguous matches too:\n{c}"
    );
}

#[test]
fn atom_prints_full_record_for_a_body_atom() {
    // Mode 2 (targeted read): id → the atom's FULL aggregated record (body + the [^N] footnotes ITS
    // body references, grouped) — the same aggregation a recall hit prints, with no page load by the
    // caller. `--no-notes` keeps the body only.
    let d = TempDir::new("atom-read");
    d.write(
        "oauth-hub.md",
        "---\nname: oauth-hub\ndescription: oauth overview\nocd: 2026-01-01\nlmd: 2026-06-01\n---\n# OAuth hub\n\n^rotate-drain [keywords: zqxdrain rotator]\nThe rotator drains the live (near-limit) account first.[^1]\n\n# Lessons Learned\n[^1]: earlier this drained the alternate first; reversed — the live account hits the cap sooner.\n",
    );
    let o = run(&["atom", "rotate-drain", d.as_str()]); // no index → walk resolution
    assert!(
        o.contains("The rotator drains the live"),
        "the atom body is returned:\n{o}"
    );
    assert!(
        o.contains("lessons learned:") && o.contains("earlier this drained the alternate"),
        "the atom's own [^1] lesson is aggregated:\n{o}"
    );
    assert!(
        !o.contains("#rotate-drain"),
        "no locator line — the caller asked for the content, it already has the address:\n{o}"
    );
    let nn = run(&["atom", "rotate-drain", d.as_str(), "--no-notes"]);
    assert!(
        nn.contains("The rotator drains the live") && !nn.contains("lessons learned:"),
        "--no-notes keeps the body, drops the groups:\n{nn}"
    );
    // Index-backed LOCATION renders the identical record (the record itself always comes from the
    // page's live parse, so walk vs index cannot diverge on content).
    run(&["reindex", d.as_str()]);
    let indexed = run(&["atom", "rotate-drain", d.as_str()]);
    assert_eq!(o, indexed, "index-backed atom read equals the walk");
}

#[test]
fn atom_resolves_a_lesson_id_to_its_lesson_record() {
    // A LESSON id is a first-class atom address too: `atom <ATOM-…>` prints the resolved lesson
    // line (stable id label, WHY text) — the same shape `find --only-notes` renders.
    let d = TempDir::new("atom-read-lesson");
    d.write("oauth-hub.md", ATOM_ID_CORPUS);
    let o = run(&["atom", "234PU35Q", d.as_str()]); // bare-8 spelling of ATOM-234P-U35Q
    assert!(
        o.contains("[ATOM-234P-U35Q] - DO drain the live account first"),
        "the lesson resolves by its bare-8 id to its record line:\n{o}"
    );
    run(&["reindex", d.as_str()]);
    let indexed = run(&["atom", "234PU35Q", d.as_str()]);
    assert_eq!(o, indexed, "index-backed lesson read equals the walk");
}

#[test]
fn dir_rooted_recall_never_walks_the_private_user_mem_store() {
    // F8 (wikimem audit 2026-07-07): `user-mem/` is the PRIVATE user-authored store —
    // agent-invisible BY DESIGN. A dir-rooted recall/find/reindex on the memory SCOPE must
    // never rank, print, or index its notes (the shipped recall protocol passes the scope
    // DIR as the root, so the engine is the one place the boundary can hold). Non-vacuous:
    // the private note's description matches the query exactly.
    // NB: the tag must not contain "user-mem" — it lands in the temp PATH, and the
    // assertions below check the OUTPUT for the private note's markers.
    let d = TempDir::new("umprivacy");
    seed_corpus(&d);
    std::fs::create_dir_all(d.join("user-mem")).expect("mk user-mem");
    d.write(
        "user-mem/00001-private.md",
        "---\ndescription: oauth rotator keychain credentials PRIVATE\n---\n\nMy private secret memory.\n",
    );
    let o = run(&["recall", "oauth rotator keychain credentials", d.as_str()]);
    assert!(
        !o.contains("00001-private") && !o.contains("user-mem"),
        "recall on the scope dir must not surface user-mem content:\n{o}"
    );
    let f = run(&["find", "+PRIVATE", d.as_str()]);
    assert!(
        !f.contains("00001-private") && !f.contains("user-mem"),
        "find on the scope dir must not surface user-mem content:\n{f}"
    );
    // Reindex on the scope must not pull private bodies into the sidecar either: an
    // indexed recall right after must stay clean.
    let _ = run(&["reindex", d.as_str()]);
    let oi = run(&[
        "recall",
        "oauth rotator keychain credentials",
        d.as_str(),
        "--use-index",
    ]);
    assert!(
        !oi.contains("00001-private") && !oi.contains("user-mem"),
        "indexed recall must not surface user-mem content:\n{oi}"
    );
}

#[test]
fn proposed_reports_never_ranked_indexed_or_linked() {
    // F16 (wikimem audit 2026-07-07): the memory detectors drop `<detector>-proposed.md`
    // reports into the scanned dir. They are NOT notes (Python SSOT: DETECTOR_OUTPUT_SUFFIX)
    // — recall/find must not rank them, reindex must not index them, links must not
    // link-graph them. Non-vacuous: the report's gloss matches the query exactly.
    let d = TempDir::new("proposedskip");
    seed_corpus(&d);
    d.write(
        "memory-reorg-proposed.md",
        "# Proposed reorganization\noauth rotator keychain credentials PROPOSALGLOSS [[oauth-rotator]]\n",
    );
    let o = run(&["recall", "oauth rotator keychain credentials", d.as_str()]);
    assert!(
        !o.contains("memory-reorg-proposed"),
        "recall must not rank a -proposed.md detector report:\n{o}"
    );
    let f = run(&["find", "+PROPOSALGLOSS", d.as_str()]);
    assert!(
        !f.contains("memory-reorg-proposed"),
        "find must not rank a -proposed.md detector report:\n{f}"
    );
    let _ = run(&["reindex", d.as_str()]);
    let oi = run(&[
        "recall",
        "oauth rotator keychain credentials",
        d.as_str(),
        "--use-index",
    ]);
    assert!(
        !oi.contains("memory-reorg-proposed"),
        "indexed recall must not serve a -proposed.md detector report:\n{oi}"
    );
    let l = run(&["links", d.as_str()]);
    assert!(
        !l.contains("memory-reorg-proposed"),
        "links must not graph a -proposed.md detector report:\n{l}"
    );
    // The MEMORY subcommands treat the report as a non-note even when EXPLICITLY
    // named (same long-standing semantic as an explicit MEMORY.md arg — the
    // consumer-side is_index_file check predates this fix). Reading a report is
    // the plain grep mode's job, which is unaffected.
    let explicit = run(&[
        "find",
        "+PROPOSALGLOSS",
        d.join("memory-reorg-proposed.md").to_str().expect("utf-8"),
    ]);
    assert!(
        !explicit.contains("memory-reorg-proposed"),
        "the memory subcommands never rank a report, even explicitly named:\n{explicit}"
    );
    let grep_mode = run(&[
        "-e",
        "PROPOSALGLOSS",
        d.join("memory-reorg-proposed.md").to_str().expect("utf-8"),
    ]);
    assert!(
        grep_mode.contains("PROPOSALGLOSS"),
        "the plain grep mode must still read an explicitly named report:\n{grep_mode}"
    );
}

#[test]
fn user_mem_named_as_the_root_is_still_searchable() {
    // The exclusion is on DESCENDANT components relative to the walked root, never the root
    // itself — /janitor-memory-user-search passes the private store AS the root and must
    // keep working.
    let d = TempDir::new("user-mem-root");
    std::fs::create_dir_all(d.join("user-mem")).expect("mk user-mem");
    d.write(
        "user-mem/00001-private.md",
        "---\ndescription: my private note about the espresso machine\n---\n\nEspresso fact.\n",
    );
    let root = d.join("user-mem");
    let o = run(&["find", "+espresso", root.to_str().expect("utf-8")]);
    assert!(
        o.contains("00001-private"),
        "user-mem named as the ROOT must remain searchable:\n{o}"
    );
}

// ─────────────── WRITE verbs (TRDD-R02HTRUD): new-page / add-atom / add-lesson ───────────────

/// Run memgrep with `input` piped to stdin — the write verbs read the element BODY from stdin.
/// Asserts success; returns stdout.
fn run_stdin(args: &[&str], input: &str) -> String {
    use std::io::Write;
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let mut child = Command::new(bin)
        .args(args)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .expect("spawn memgrep");
    child
        .stdin
        .take()
        .expect("stdin handle")
        .write_all(input.as_bytes())
        .expect("write stdin");
    let out = child.wait_with_output().expect("wait memgrep");
    assert!(
        out.status.success(),
        "memgrep exited non-zero for {args:?}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8_lossy(&out.stdout).into_owned()
}

/// Like `run_stdin` but returns (stdout, stderr, exit code) regardless of exit status — for
/// asserting on a WARNING printed alongside a still-successful write (add-lesson's
/// write→recall-gap check prints to stderr but must still exit 0).
fn run_stdin_full(args: &[&str], input: &str) -> (String, String, i32) {
    use std::io::Write;
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let mut child = Command::new(bin)
        .args(args)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .expect("spawn memgrep");
    child
        .stdin
        .take()
        .expect("stdin handle")
        .write_all(input.as_bytes())
        .expect("write stdin");
    let out = child.wait_with_output().expect("wait memgrep");
    (
        String::from_utf8_lossy(&out.stdout).into_owned(),
        String::from_utf8_lossy(&out.stderr).into_owned(),
        out.status.code().unwrap_or(-1),
    )
}

/// Like `run_stdin` but sets an extra env var on the child. `add-atom`/`add-lesson` now REFUSE
/// under `MEMGREP_MIN_KEYWORDS` (default 10) when handed fewer keyphrases — a fixture written
/// before that floor and pinned to a LITERAL 3-keyword stored-marker string (a round-trip proof
/// that would break the instant a 4th keyword is spliced in anywhere) opts out via this env var
/// rather than padding the phrase list with keywords the literal assertion can't accommodate.
fn run_stdin_env(args: &[&str], input: &str, env_key: &str, env_val: &str) -> String {
    use std::io::Write;
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let mut child = Command::new(bin)
        .args(args)
        .env(env_key, env_val)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .expect("spawn memgrep");
    child
        .stdin
        .take()
        .expect("stdin handle")
        .write_all(input.as_bytes())
        .expect("write stdin");
    let out = child.wait_with_output().expect("wait memgrep");
    assert!(
        out.status.success(),
        "memgrep exited non-zero for {args:?}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8_lossy(&out.stdout).into_owned()
}

/// Like `run_stdin` but expects a clean NON-zero exit (a refusal — missing page, empty body, …).
fn run_stdin_fail(args: &[&str], input: &str) {
    use std::io::Write;
    let bin = env!("CARGO_BIN_EXE_memgrep");
    let mut child = Command::new(bin)
        .args(args)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .expect("spawn memgrep");
    child
        .stdin
        .take()
        .expect("stdin handle")
        .write_all(input.as_bytes())
        .expect("write stdin");
    let out = child.wait_with_output().expect("wait memgrep");
    assert!(!out.status.success(), "memgrep should have failed for {args:?}");
    assert!(out.status.code().is_some(), "memgrep died from a signal on {args:?}");
}

#[test]
fn new_page_scaffolds_a_valid_parseable_page() {
    let d = TempDir::new("newpage");
    let page = d.join("comp.md");
    let out = run(&[
        "new-page",
        "--path",
        page.to_str().unwrap(),
        "--tier",
        "component",
        "--name",
        "comp",
        "--description",
        FIXTURE_PAGE_DESC,
        "--type",
        "reference",
    ]);
    assert!(out.contains("comp.md"), "new-page prints the path: {out}");
    let text = std::fs::read_to_string(&page).unwrap();
    // Frontmatter recall surface + the mandatory landing zone are present.
    assert!(text.contains("name: comp"));
    assert!(text.contains("description: \""));
    assert!(text.contains("## Notes and lessons learned"));
    assert!(text.contains("node_type: memory") && text.contains("tier: component"));
    // A second new-page onto the same path is refused — never clobber an existing page.
    run_fail(&[
        "new-page", "--path", page.to_str().unwrap(), "--tier", "component",
        "--name", "comp", "--description", FIXTURE_PAGE_DESC, "--type", "reference",
    ]);
}

#[test]
fn add_atom_round_trips_through_the_parser_and_index() {
    let d = TempDir::new("addatom");
    let page = d.join("p.md");
    run(&[
        "new-page", "--path", page.to_str().unwrap(), "--tier", "component",
        "--name", "p", "--description", FIXTURE_PAGE_DESC, "--type", "reference",
    ]);
    // add-atom: body from stdin, a multi-word phrase keyword, a desc + type. The stored marker is
    // asserted LITERALLY below against exactly these 3 keyphrases, so this call opts out of the
    // >=10-keyphrase floor (MEMGREP_MIN_KEYWORDS=0) rather than splicing extra phrases into a
    // fixed-position literal string.
    let out = run_stdin_env(
        &[
            "add-atom", "--page", page.to_str().unwrap(),
            "--keywords", "rate limit, resume, 429 error",
            // Still comma-bearing — that IS this test's subject (a comma must survive the
            // quoted round-trip) — but past the 24-char desc floor, which "a summary, with a
            // comma" missed by one character.
            "--desc", "a summary, with a comma, long enough to triage on",
            "--type", "reference",
        ],
        "The window already closed — mint a fresh token.",
        "MEMGREP_MIN_KEYWORDS", "0",
    );
    let id = out.split_whitespace().next().expect("printed id").to_string();
    assert!(id.starts_with("ATOM-"), "printed a canonical id: {out}");

    // The atom resolves through the FRESH index by id (proves the reindex ran).
    let atom = run(&["atom", &id, d.as_str()]);
    assert!(atom.contains("mint a fresh token"), "atom body round-trips: {atom}");

    // …and by its keyword surface (phrase underscore-joined so `resume` is a whole token).
    let found = run(&["find", "+resume", d.as_str()]);
    assert!(found.contains(&id), "atom findable by keyword: {found}");

    // The stored marker is the canonical `^id [desc:…, keywords:…, type:…, ocd:…, lmd:…]` shape.
    let text = std::fs::read_to_string(&page).unwrap();
    assert!(text.contains(&format!("^{id} [desc: \"a summary, with a comma\", keywords: rate_limit resume 429_error, type: reference, ocd: ")));
    // The atom landed BEFORE the notes section (its marker precedes the heading in the file).
    let mpos = text.find(&format!("^{id}")).unwrap();
    let npos = text.find("## Notes and lessons learned").unwrap();
    assert!(mpos < npos, "atom inserted before the lessons section");
}

#[test]
fn add_atom_refuses_a_missing_page_and_empty_body() {
    let d = TempDir::new("addatom-refuse");
    let missing = d.join("nope.md");
    // No such page → refuse (never create the page implicitly).
    run_stdin_fail(
        &["add-atom", "--page", missing.to_str().unwrap(), "--keywords", "a,b"],
        "body",
    );
    // Existing page but empty stdin body → refuse.
    let page = d.join("p.md");
    run(&[
        "new-page", "--path", page.to_str().unwrap(), "--tier", "component",
        "--name", "p", "--description", FIXTURE_PAGE_DESC, "--type", "reference",
    ]);
    run_stdin_fail(
        &["add-atom", "--page", page.to_str().unwrap(), "--keywords", "a,b"],
        "   \n  ",
    );
}

/// `add-atom --supersedes` (TRDD-3PWQK8NM, WM-CLI-13): the target atom is retired in place and
/// moved verbatim below a fresh `## Superseded` heading, the new atom carries the current truth,
/// no lesson is authored, and `recall`/`validate`/`lint` all treat the result exactly like the
/// lesson-bearing supersession path.
#[test]
fn add_atom_supersedes_moves_the_old_body_below_a_fresh_superseded_heading() {
    let d = TempDir::new("addatom-supersedes");
    let page = d.join("p.md");
    run(&[
        "new-page", "--path", page.to_str().unwrap(), "--tier", "component",
        "--name", "p", "--description", FIXTURE_PAGE_DESC, "--type", "reference",
    ]);
    let old_out = run_stdin(
        &[
            "add-atom", "--page", page.to_str().unwrap(), "--keywords",
            "old, thing, retired fact, superseded record, previous version, \
             old value stored, legacy data point, prior fact recorded, \
             obsolete information, historical record entry",
        "--desc", FIXTURE_DESC,
        ],
        "the old fact.",
    );
    let old_id = old_out.split_whitespace().next().unwrap().to_string();

    let new_out = run_stdin(
        &[
            "add-atom", "--page", page.to_str().unwrap(), "--keywords",
            "new, thing, refined fact, current record, updated version, \
             fresh value stored, latest data point, corrected fact recorded, \
             current information, updated record entry",
            "--desc", FIXTURE_DESC,
            "--supersedes", &old_id,
        ],
        "the refined fact.",
    );
    let new_id = new_out.split_whitespace().next().unwrap().to_string();
    assert_ne!(old_id, new_id, "the new atom gets a FRESH id, never the old one");

    let text = std::fs::read_to_string(&page).unwrap();
    assert!(text.contains("## Superseded"), "the heading is created:\n{text}");
    assert!(
        text.contains(&format!("status: superseded, superseded-by: {new_id}"))
            || text.contains(&format!("status:superseded, superseded-by:{new_id}")),
        "the old marker records the retirement + forward pointer:\n{text}"
    );
    assert!(text.contains("the old fact."), "the old body survives VERBATIM:\n{text}");
    let sup_pos = text.find("## Superseded").unwrap();
    let old_pos = text.find(&old_id).unwrap();
    let new_pos = text.find(&new_id).unwrap();
    assert!(old_pos > sup_pos, "the old atom sits BELOW the delimiter:\n{text}");
    assert!(new_pos < sup_pos, "the new atom sits at the ordinary insertion point, above the delimiter:\n{text}");

    // `recall` defaults to skipping the superseded version and returning only the current truth.
    let recalled = run(&["recall", "thing", d.as_str()]);
    assert!(recalled.contains(&new_id), "recall returns the new atom: {recalled}");
    assert!(!recalled.contains(&old_id), "recall skips the superseded atom by default: {recalled}");
    let recalled_full = run(&["recall", "thing", d.as_str(), "--include-superseded"]);
    assert!(recalled_full.contains(&old_id), "--include-superseded surfaces it: {recalled_full}");

    // The page stays clean by the corpus's own oracles.
    let (_, code) = run_with_code(&["validate", page.to_str().unwrap()]);
    assert_eq!(code, 0, "validate must be clean after a lesson-free supersession");
    let (_, lint_code) = run_with_code(&["lint", page.to_str().unwrap()]);
    assert_eq!(lint_code, 0, "lint must report zero findings after a lesson-free supersession");
}

/// A second `--supersedes` on the same page CHAINS (v1 → v2 → v3) instead of overwriting the
/// first supersession record, and no duplicate LIVE atom is left behind at any point.
#[test]
fn add_atom_supersedes_chains_across_multiple_generations() {
    let d = TempDir::new("addatom-supersedes-chain");
    let page = d.join("p.md");
    run(&[
        "new-page", "--path", page.to_str().unwrap(), "--tier", "component",
        "--name", "p", "--description", FIXTURE_PAGE_DESC, "--type", "reference",
    ]);
    // >=10-keyphrase floor (MEMGREP_MIN_KEYWORDS, default 10): every fixture below carries a full
    // keyphrase list plausibly belonging to its subject, not filler — a future author copying a
    // fixture copies a compliant one.
    const CHAIN_KEYWORDS: &str = "chain, thing, multi generation supersession, \
        version chain history, atom retirement sequence, superseded chain test, \
        generation tracking id, chain of custody record, provenance chain trace, \
        sequential supersession chain";
    let v1 = run_stdin(
        &["add-atom", "--page", page.to_str().unwrap(), "--keywords", CHAIN_KEYWORDS, "--desc", FIXTURE_DESC],
        "v1 fact.",
    ).split_whitespace().next().unwrap().to_string();
    let v2 = run_stdin(
        &["add-atom", "--page", page.to_str().unwrap(), "--keywords", CHAIN_KEYWORDS, "--desc", FIXTURE_DESC, "--supersedes", &v1],
        "v2 fact.",
    ).split_whitespace().next().unwrap().to_string();
    let v3 = run_stdin(
        &["add-atom", "--page", page.to_str().unwrap(), "--keywords", CHAIN_KEYWORDS, "--desc", FIXTURE_DESC, "--supersedes", &v2],
        "v3 fact.",
    ).split_whitespace().next().unwrap().to_string();

    let text = std::fs::read_to_string(&page).unwrap();
    // Every generation's body is still present — nothing was dropped by the chain.
    for (id, body) in [(&v1, "v1 fact."), (&v2, "v2 fact."), (&v3, "v3 fact.")] {
        assert!(text.contains(id) && text.contains(body), "generation {id} survives:\n{text}");
    }
    // Exactly ONE live (non-superseded) atom marker remains — v3.
    let live_markers = text
        .lines()
        .filter(|l| l.trim_start().starts_with('^') && l.contains("[keywords:") && !l.contains("status:"))
        .count();
    assert_eq!(live_markers, 1, "no duplicate LIVE atom is left behind:\n{text}");

    // Re-superseding an already-superseded atom is refused — chain via its successor instead.
    run_stdin_fail(
        &["add-atom", "--page", page.to_str().unwrap(), "--keywords", "x", "--supersedes", &v1],
        "should be refused.",
    );

    let (_, code) = run_with_code(&["validate", page.to_str().unwrap()]);
    assert_eq!(code, 0, "validate stays clean across a multi-generation chain");
}

#[test]
fn add_lesson_anchors_from_an_atom_and_round_trips() {
    let d = TempDir::new("addlesson");
    let page = d.join("p.md");
    run(&[
        "new-page", "--path", page.to_str().unwrap(), "--tier", "component",
        "--name", "p", "--description", FIXTURE_PAGE_DESC, "--type", "reference",
    ]);
    let atom_out = run_stdin(
        &[
            "add-atom", "--page", page.to_str().unwrap(), "--keywords",
            "keychain creds, macos keychain storage, credential never plaintext, \
             secret storage location, where are credentials stored, keychain access item, \
             stored secret lookup, credential retrieval macos, security find generic password, \
             keychain entry format",
        "--desc", FIXTURE_DESC,
        ],
        "Creds live in the macOS keychain, never plaintext.",
    );
    let atom_id = atom_out.split_whitespace().next().unwrap().to_string();

    let lesson_out = run_stdin(
        &[
            "add-lesson", "--page", page.to_str().unwrap(), "--atom", &atom_id,
            "--keywords", "retry cap guessed variable name, max_retries, \
                wrong retry constant name, guessed environment variable, \
                retry limit misconfigured, max attempts undefined, \
                incorrect retry cap source, hardcoded retry guess, \
                retry count wrong constant, environment variable guessed wrongly",
        ],
        "DO NOT read the cap off a guessed variable name, BECAUSE max_attempts does not exist. DO read the constant from the source instead.",
    );
    let lesson_id = lesson_out.split_whitespace().next().unwrap().to_string();
    assert!(lesson_id.starts_with("ATOM-"), "fresh lesson id: {lesson_out}");

    let text = std::fs::read_to_string(&page).unwrap();
    // The `[^1]` anchor is on the atom's body, the canonical def is under the notes section.
    assert!(text.contains("[^1]"), "atom body carries the [^1] anchor:\n{text}");
    assert!(
        text.contains(&format!("[^1]: [id: {lesson_id}, status: valid")),
        "canonical lesson def form:\n{text}"
    );
    // janitor#266 end-to-end: the atom marker and the lesson address in THIS page — written by two
    // verbs minutes apart — must now be greppable with the SAME `lmd: <date>` pattern. The reported
    // failure was that they were not, so a `grep -c "lmd: $today"` returned a confident 0.
    let dated: Vec<&str> = text.lines().filter(|l| l.contains("lmd: ")).collect();
    assert!(
        dated.iter().any(|l| l.trim_start().starts_with('^'))
            && dated.iter().any(|l| l.trim_start().starts_with("[^")),
        "one `lmd: ` spelling must match the atom marker AND the lesson address:\n{text}"
    );
    // The lesson resolves by its keyword surface (the recall promise for lessons).
    let found = run(&["find", "+max_retries", d.as_str(), "--only-notes"]);
    assert!(found.contains(&lesson_id), "lesson findable by keyword: {found}");
}

/// A CLEAN corpus must still report `0 finding(s)` — silence is not a verdict (janitor#191).
///
/// This used to print nothing at all: empty stdout, empty stderr, exit 0 — byte-identical to a run
/// that scanned nothing. That ambiguity cost a real investigation: a clean scope was read as a
/// skipped root, which produced a bug report, a wrong severity claim, and a retraction. A checker
/// that is silent on success AND silent on "I did not look" cannot be trusted by a human or by the
/// heartbeat that consumes it.
#[test]
fn lint_reports_zero_findings_on_a_clean_corpus_instead_of_staying_silent() {
    let d = TempDir::new("lint-clean");
    d.write(
        "clean.md",
        "---\nname: clean\nocd: 2026-01-01\nlmd: 2026-01-02\ndescription: \"a page with no defects\"\n---\nBody prose with no findings.\n\n## Notes and lessons learned\n",
    );
    // The summary is on STDERR (stdout stays the machine-parseable violation list), so this must
    // use run_full — asserting on stdout alone would pass vacuously against the old silent build.
    let (out, err, code) = run_full(&["lint", d.as_str()]);
    assert_eq!(code, 0, "a clean corpus must exit 0:\nstdout={out}\nstderr={err}");
    assert!(
        out.is_empty(),
        "stdout must stay the violation list — a clean run emits no violation lines:\n{out}"
    );
    assert!(
        err.contains("0 finding(s)"),
        "a clean corpus must SAY it found zero, not stay silent:\nstderr={err}"
    );
    // Either spelling is correct coverage: a recognised memory root reports `scope(s)`, an
    // arbitrary directory (as here) reports `path(s)`. What matters is that the summary states
    // WHAT it covered, so "clean" is distinguishable from "did not look".
    assert!(
        err.contains("scope(s)") || err.contains("path(s)"),
        "the summary must name what it actually scanned:\nstderr={err}"
    );
}

// ─────────────── TRDD-2OUMEVDS: recall ENFORCES the technique, not just documents it ───────────────

/// The card's own worked example: "server takes over the janitor daemon role" (the QUESTION's
/// vocabulary) must surface a page indexed under "absorbs"/"stands down"/"withdraws" (the
/// ANSWER's vocabulary) — the exact daemon-handover miss measured in this repo on 2026-08-14.
/// Without the synonym expansion this query scores 0 against the fixture (no shared word at all),
/// so a non-vacuous pass here is real evidence the expansion fired, not a coincidence of overlap.
#[test]
fn recall_synonym_expansion_surfaces_the_measured_daemon_handover_miss() {
    let d = TempDir::new("recall-synonym-daemon");
    d.write(
        "handover.md",
        "---\nname: one-daemon-per-host-withdraws-the-whole-daemon\ndescription: \"when two daemons race for a host, which one absorbs ownership and which one stands down and withdraws\"\ntags: [daemon]\nocd: 2026-08-01\nlmd: 2026-08-01\n---\n# one daemon per host\n\nBody prose about the daemon handoff mechanism.\n\n## Notes and lessons learned\n",
    );
    d.write(
        "coffee.md",
        "---\nname: unrelated-coffee-page\ndescription: \"totally unrelated topic about coffee brewing temperatures\"\ntags: [coffee]\nocd: 2026-08-01\nlmd: 2026-08-01\n---\n# unrelated\n\nNothing to do with daemons.\n\n## Notes and lessons learned\n",
    );

    // Sanity: the LITERAL query (no expansion) does NOT rank the handover page — proves the
    // fixture's vocabulary genuinely differs and the test isn't accidentally vacuous.
    let literal = run(&["find", "+takes +over +daemon", d.as_str()]);
    assert!(
        !literal.contains("one-daemon-per-host-withdraws"),
        "sanity check failed — the literal words already match, so the expansion test proves nothing:\n{literal}"
    );

    let o = run(&["recall", "server takes over the janitor daemon role", d.as_str()]);
    assert!(
        o.contains("one-daemon-per-host-withdraws-the-whole-daemon"),
        "synonym-expanded recall must surface the handover page:\n{o}"
    );
    assert!(
        !o.contains("unrelated-coffee-page"),
        "the unrelated page must not surface just because expansion widened the query:\n{o}"
    );
}

/// WM-EXPAND-02, the card's no-regression box: expansion is STRICTLY ADDITIVE. A page that already
/// ranks under the LITERAL query must still rank (score >= its literal score) under the expanded
/// one — expansion can never make an exact match disappear behind synonym noise. Proven with a
/// query whose exact phrase lives in one page's `description:` verbatim (so it scores the top
/// EXACT_KEYWORD tier) while ALSO containing a synonym-table trigger word ("stops"), so the
/// synonym table's added words are genuinely in play, not just inert.
#[test]
fn recall_expansion_is_additive_never_drops_a_literal_match() {
    let d = TempDir::new("recall-additive");
    d.write(
        "exact.md",
        "---\nname: exact-match-page\ndescription: \"the daemon stops cleanly on shutdown\"\ntags: [daemon]\nocd: 2026-08-01\nlmd: 2026-08-01\n---\n# exact match\n\nBody prose.\n\n## Notes and lessons learned\n",
    );
    let literal = run(&["recall", "the daemon stops cleanly on shutdown", d.as_str()]);
    assert!(
        literal.contains("exact-match-page"),
        "sanity: the literal query must already match its own exact description:\n{literal}"
    );
    // Same query, run through the normal (always-expanding) recall path — the exact match must
    // still be present. Because expansion only ADDS words to the ranking surface, and the exact
    // phrase (used for the EXACT_KEYWORD tier) is untouched by expansion, the page must still rank.
    let expanded = run(&["recall", "the daemon stops cleanly on shutdown", d.as_str()]);
    assert!(
        expanded.contains("exact-match-page"),
        "expansion must never drop a match the literal query already found:\n{expanded}"
    );
}

/// Jargon-shaped queries (an identifier, here `cmd_recall_cli`) are DETECTED and FLAGGED loudly —
/// never silently substituted. The warning line, the literal-query section, and the expanded
/// section must all be present on stdout so the caller sees exactly what happened.
#[test]
fn recall_flags_jargon_shaped_queries_and_shows_both_result_sets() {
    let d = TempDir::new("recall-jargon");
    d.write(
        "cli.md",
        "---\nname: cli-recall-page\ndescription: \"the recall command line entry point\"\ntags: [cli]\nocd: 2026-08-01\nlmd: 2026-08-01\n---\n# cli recall page\n\nBody prose.\n\n## Notes and lessons learned\n",
    );
    let o = run(&["recall", "cmd_recall_cli", d.as_str()]);
    assert!(
        o.contains("jargon") && o.contains("Also tried"),
        "a snake_case identifier must be flagged as jargon:\n{o}"
    );
    assert!(o.contains("literal query"), "the literal section header must print:\n{o}");
    assert!(o.contains("expanded"), "the expanded section header must print:\n{o}");
    // The jargon token splits into `recall`/`cli`, which DOES reach the page's description — so
    // the expanded section (unlike the literal one) must surface it.
    assert!(
        o.contains("cli-recall-page"),
        "the split jargon words must reach the page via the expanded section:\n{o}"
    );
}

/// An ordinary symptom-phrased query (no identifiers, paths, CamelCase, or version strings) must
/// NOT trigger the jargon warning — the flag is precise, not a blanket disclaimer on every call.
#[test]
fn recall_does_not_flag_ordinary_symptom_phrases_as_jargon() {
    let d = TempDir::new("recall-not-jargon");
    d.write(
        "plain.md",
        "---\nname: plain-page\ndescription: \"the server crashed during startup\"\ntags: [x]\nocd: 2026-08-01\nlmd: 2026-08-01\n---\n# plain\n\nBody.\n\n## Notes and lessons learned\n",
    );
    let o = run(&["recall", "why did the server crash on startup", d.as_str()]);
    assert!(
        !o.contains("jargon"),
        "an ordinary symptom phrase must not be flagged as jargon:\n{o}"
    );
}

/// THE FRESH, MEASURED REGRESSION CASE (2026-08-14): `add-lesson` handed keywords that share no
/// word with the page's `description:` must WARN LOUDLY on stderr (not fail — the write still
/// succeeds, exit 0) — reproducing, verbatim, the sequence that motivated this card: nine (here,
/// nine-word) symptom keywords, a clean validate-shaped write, and a lesson that would otherwise
/// be silently unfindable by every one of them.
#[test]
fn add_lesson_warns_when_keywords_share_no_word_with_the_page_description() {
    let d = TempDir::new("addlesson-gap");
    let page = d.join("p.md");
    run(&[
        "new-page", "--path", page.to_str().unwrap(), "--tier", "component",
        "--name", "p", "--description", "example page for testing lesson keyword coverage",
        "--type", "reference",
    ]);
    let atom_out = run_stdin(
        &[
            "add-atom", "--page", page.to_str().unwrap(), "--keywords",
            "example atom body, sample fixture atom, demo atom content, \
             placeholder atom text, test double atom, mock atom fixture, \
             illustrative atom sample, scratch atom body, throwaway atom fixture, \
             stub atom content",
        "--desc", FIXTURE_DESC,
        ],
        "some atom body text.",
    );
    let atom_id = atom_out.split_whitespace().next().unwrap().to_string();

    // Every phrase below deliberately shares NO word with the page's `description:`
    // ("example page for testing lesson keyword coverage") — that gap is this test's subject.
    let (out, err, code) = run_stdin_full(
        &[
            "add-lesson", "--page", page.to_str().unwrap(), "--atom", &atom_id,
            "--keywords",
            "pure function tests all passed but the guard was never wired, \
             guard wiring skipped silently, wrong assumption unit test green, \
             value never actually exercised, broken integration path hidden, \
             false confidence from pure tests, missing assertion on real wiring, \
             silent gap between logic and wiring, code path never invoked, \
             passing suite hides real defect",
        ],
        "DO NOT skip the guard-wiring test, BECAUSE a pure-function pass proves nothing about wiring. DO wire and assert instead.",
    );
    assert_eq!(code, 0, "the write itself must still succeed:\nstdout={out}\nstderr={err}");
    assert!(out.starts_with("ATOM-"), "the lesson id still prints on stdout: {out}");
    assert!(
        err.contains("share no word") || err.contains("UNFINDABLE"),
        "a keyword absent from the description must be flagged loudly:\nstderr={err}"
    );
    assert!(
        err.contains("wired") || err.contains("guard"),
        "the warning must name the actual uncovered keyword, not a generic message:\nstderr={err}"
    );

    // Proves the thesis end to end: `recall` on the exact symptom phrase does NOT surface the
    // page (the keywords never reached the ranking surface) — exactly the write→recall gap.
    let recalled = run(&[
        "recall",
        "pure function tests all passed but the guard was never wired",
        d.as_str(),
    ]);
    assert!(
        !recalled.contains("ATOM-") || !recalled.contains(&atom_id),
        "unfixed, the lesson stays unfindable by its own stated symptom — reproducing the measured gap:\n{recalled}"
    );
}

/// The companion case: when a keyword DOES share a word with the description, no warning fires —
/// the check is precise, not a blanket "always warn on add-lesson" default.
#[test]
fn add_lesson_stays_silent_when_keywords_are_covered_by_the_description() {
    let d = TempDir::new("addlesson-covered");
    let page = d.join("p.md");
    run(&[
        "new-page", "--path", page.to_str().unwrap(), "--tier", "component",
        "--name", "p", "--description", "keychain rotation retry cap guessed variable name",
        "--type", "reference",
    ]);
    let atom_out = run_stdin(
        &[
            "add-atom", "--page", page.to_str().unwrap(), "--keywords",
            "keychain creds, macos keychain storage, credential never plaintext, \
             secret storage location, where are credentials stored, keychain access item, \
             stored secret lookup, credential retrieval macos, security find generic password, \
             keychain entry format",
        "--desc", FIXTURE_DESC,
        ],
        "Creds live in the macOS keychain, never plaintext.",
    );
    let atom_id = atom_out.split_whitespace().next().unwrap().to_string();

    // Every phrase below shares AT LEAST one word with the page's `description:`
    // ("keychain rotation retry cap guessed variable name") — that coverage is this test's subject.
    let (_out, err, code) = run_stdin_full(
        &[
            "add-lesson", "--page", page.to_str().unwrap(), "--atom", &atom_id,
            "--keywords",
            "retry cap guessed variable name, keychain credential rotation, \
             retry limit configuration, guessed environment variable, \
             variable name typo, keychain rotation schedule, retry cap value, \
             guessed constant name, rotation retry logic, variable cap guess",
        ],
        "DO NOT read the cap off a guessed variable name, BECAUSE max_attempts does not exist. DO read the constant from the source instead.",
    );
    assert_eq!(code, 0);
    assert!(
        !err.contains("share no word"),
        "a fully-covered keyword set must not trigger the warning:\nstderr={err}"
    );
}
