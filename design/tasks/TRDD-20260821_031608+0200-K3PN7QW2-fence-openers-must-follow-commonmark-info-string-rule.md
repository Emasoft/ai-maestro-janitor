---
trdd-id: K3PN7QW2
title: Fence-opener detection is naive — an inline triple-backtick span at line start is read as a fence
column: dev
created: 2026-08-21T03:16:08+0200
updated: 2026-08-21T08:15:56+0200
current-owner: janitor-main-session
task-type: bugfix
priority: normal
approval-tier: 0
scope: project
external-refs: [janitor#277, janitor#279]
npt: []
eht: []
---

# A fence OPENER is not "any line starting with three backticks"

## ⏵ STATE — 2026-08-21 08:15: claim REPRODUCED first-hand; design settled; advisor-pending

**The defect is real and I measured it rather than trusting the card.** A throwaway page whose
only backtick line is an inline span AT LINE START:

```text
```fence``` or `inline code` is inert by CommonMark — the info string carries a backtick.
```

with one atom below it produces, on the installed crate:

- `memgrep lint` → **`ERROR … [page-unclosed-fence]` at that line** — a FALSE POSITIVE, because
  by CommonMark a backtick fence's info string may not contain a backtick, so that line opens
  nothing.
- `memgrep recall ATOM-TEST-0001 <dir>` → **does not return the atom.** It degrades to a
  page-level hit. The atom below the phantom fence is invisible, exactly as the card asserts.

**Precision matters in the repro and cost me one attempt:** the same span NOT at line start
(`An inline span: ```fence``` …`) parses fine and lints clean. The bug needs the run of
backticks to be the first non-space characters — which is why it is rare and why it survived.

**This also confirms the mirroring is working as designed** (`e5d642d1`): the lint reports
"unclosed fence" precisely because the walkers believe it. That is why the fix cannot be
partial — correcting the walkers without the lint's counter makes the two disagree, which is
the janitor#227/#250/#260 failure shape.

**DESIGN (settled, not yet implemented).** Replace the boolean toggle with a small state
machine, shared by every walker:

- `fence_run(t) -> Option<(char, usize, &str)>` — the leading run of `` ` `` or `~`, length ≥ 3,
  plus the remainder (the info string).
- `is_fence_open(t) -> Option<Fence>` — a run, EXCEPT that a backtick opener whose info string
  contains a backtick is not an opener (the CommonMark rule this card exists for).
- `closes(t, open) -> bool` — same char, run length ≥ the opener's, and nothing but whitespace
  after (a closer takes no info string).

The walkers then track `Option<Fence>` rather than `bool`, which also fixes a second latent
defect for free: today a `~~~` line closes a ```` ``` ```` fence, because a bare toggle cannot
tell the two characters apart.

**Sites (grep-confirmed): 12 in `memory.rs` across 7 walkers, 1 in `md.rs`, plus the Python twin
`memory_content_precheck.py::_footer_heading_line`.** That is >3 files, so per the project rule
this needs an advisor verdict before implementation. **NEXT ACTION:** consult the advisor (one
is already mid-flight on TRDD-7NSRD8OV — do not spawn a second concurrently), then implement all
sites together with a fixture per branch.

## Why (measured 2026-08-21, janitor#277 + #279)

Every structural walker in `memgrep/src/memory.rs` toggles `in_fence` on any line whose
trimmed start is ```` ``` ```` or `~~~`. By CommonMark that is wrong: for a backtick
fence the info string **may not contain backticks**, so a line like

    ```fence``` or `inline code` is inert

is an INLINE CODE SPAN, not a fence opener. The walkers read it as one, never see a closer,
and every atom and heading below it becomes invisible — which cost two peer agents an
investigation each (#277, #279) before `e5d642d1` shipped detection for the symptom.

`e5d642d1` fixed the PAGE and added `page-unclosed-fence` + a hint on the refusal. It
deliberately did NOT change the parsing rule: the new lint mirrors the walkers' rule on
purpose, so it fires exactly when a walker is confused. Making the walkers correct is a
separate, larger change — and it must land together with the lint's own counter or the two
will disagree, which is the drift the mirroring was chosen to avoid.

## What

1. A single shared `is_fence_delimiter(line) -> Option<FenceKind>` honouring CommonMark:
   an opener's info string carries no backtick for a ```` ``` ```` fence; a closer is
   bare. Replace the ad-hoc `starts_with` toggles at every site.
2. Sites to convert (grep `starts_with("\`\`\`")`): `locate_atom_body_matching`,
   `footer_section_line`, the `page-unclosed-fence` counter, `unclosed_fence_hint`, and any
   other walker the grep finds — they must all move together.
3. **The Python twin must move with them.** `scripts/lib/memory_content_precheck.py`
   (`_footer_heading_line`) carries the same naive rule, and janitor#227/#250/#260 are all
   the same failure: this precheck and the Rust crate disagreeing about page structure, so
   the repair chore re-dispatches forever.
4. Re-run the corpus scan afterwards: pages currently flagged `page-unclosed-fence` that
   contain only an inline span should come back CLEAN without being reflowed.

## Acceptance

- [ ] one shared delimiter predicate; no remaining ad-hoc `starts_with` fence toggle in the crate
- [ ] the Python precheck twin uses the same rule (grep-proven), so the two cannot disagree
- [ ] a page whose only ````-line is an inline span parses fully: its atoms and headings are visible
- [ ] a genuinely unclosed fence is STILL reported by `page-unclosed-fence`
- [ ] cargo test + clippy clean; `uv run pytest -q`, ruff, mypy, pyright clean

## Approval log
