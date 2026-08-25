# The five 3.0.0 board columns — normative meanings (3P-KAN-18/-19)

On-demand reference for `rules/universal-kanban.md`. Canonical text: ai-maestro
`design/specs/3-pillars-spec.md` 3.0.0 (`governance-rules` head `c8b0e9cb`); `PRRD G3.1`–`G10.1`.

- `approval` — the card is with the approver named by its `min-approval-requirement:`
  (chief-of-staff or manager). `backburner` now means only *not yet approved*.
- `design` — the card is expanded IN PLACE with detailed design and specs (3P-TRDD-13: **no
  second file**), by the DESIGNER in a team or the implementer outside one. It sits BEFORE
  `todo` now, so `todo` asserts approved AND designed.
- `design_ai_review` — the design body is reviewed by the COS or the MANAGER.
- `design_human_review` — the human reviews it; a UI design MUST ship a visual artifact to
  annotate. SKIPPED entirely when `min-approval-requirement: none`.
- `verify_assumptions` — every claim in the card is verified; where a fact cannot be checked
  directly a TEST is created to verify it. Passes only when nothing in the card is still an
  assumption.
- `plan` — the implementation is planned by Claude Code's plan-mode steps run
  NON-interactively, every choice made autonomously from verified facts. Passes only when a
  complete plan FILE exists. `dev` gains one obligation (`PRRD G10.1`): the plan's steps are
  ENFORCED — executed and their execution verified — so they persist across sessions.
