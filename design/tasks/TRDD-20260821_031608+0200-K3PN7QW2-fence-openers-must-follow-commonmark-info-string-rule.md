---
trdd-id: K3PN7QW2
title: Fence-opener detection is naive — an inline triple-backtick span at line start is read as a fence
column: todo
created: 2026-08-21T03:16:08+0200
updated: 2026-08-21T03:16:08+0200
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
