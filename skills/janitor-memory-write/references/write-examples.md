# MEMORIZE — worked examples

Three worked routing/shape examples for `/janitor-memory-write`. Moved here
verbatim from the SKILL body (TRDD-82OP4EN9 token-budget move).

## Table of contents

- [Worked examples (aspect / component / user-feedback)](#worked-examples-aspect--component--user-feedback)
- [WRITE-the-page: full memgrep verb reference](#write-the-page-full-memgrep-verb-reference)

## Worked examples (aspect / component / user-feedback)

<example>
Decision: "all destructive dialogs use a red secondary 'Delete' button, primary is Cancel."
→ general rule shared by many dialogs ⇒ EXPAND ⇒ RADIATING aspect `dialog-forms`
  (functionality: frontend). `## Applies to`: [[login-panel]], [[settings-panel]],
  … every dialog. Reciprocal: each of those gets `dialog-forms` in its
  `## Governed by`. Linked from the `frontend` hub's parts map.
</example>

<example>
Decision: "the checkout endpoint is idempotent on the Idempotency-Key header."
→ specific to one element ⇒ REDUCE ⇒ RECEIVING component `checkout-endpoint`
  (functionality: backend). `## Governed by`: [[error-envelope]] (the protocol it
  obeys); `## See also`: [[order-model]], [[payment-gateway]] (lateral). Reciprocal:
  `error-envelope`'s `## Applies to` gains `checkout-endpoint`. If
  `checkout-endpoint` already exists ⇒ UPDATE it instead.
</example>

<example>
User: remember that automating my own paid Claude accounts is fine, don't over-flag ToS
→ type: feedback, USER scope, component page; description carries the QUESTION
  "is it ok to automate / rotate my own Claude accounts".
</example>

## WRITE-the-page: full memgrep verb reference

Moved here verbatim from the SKILL body (CPV body-token-limit trim). This is the
full detail for SKILL.md's "### 4. WRITE the page — memgrep verbs, never
hand-authored" step.

**Never hand-write a wikimem `.md` again.** memgrep OWNS the syntax — the
frontmatter, the `^id [keywords: …]` atom markers, and the `[^N]: […]` lesson
grammar are all synthesised by the write verbs, so a mistyped block-property, a
missing `ocd:`, or a malformed footnote is now impossible. Do NOT open the page
with the Write/Edit tool and do NOT type `^id [...]` or `[^N]: [...]` yourself; the
tool mints the id, the dates, and the canonical shape. The GRAMMAR is the tool's
job — your job is the JUDGMENT (which fact, which keywords, which desc).

**Scaffold the page** with the tier / name / description / type you decided in
steps 1 & 3 (hubs also carry `--globs`; a hub or component may carry
`--functionality`). This emits valid frontmatter + the mandatory
`## Notes and lessons learned` section, and REFUSES to clobber an existing page:

```bash
memgrep new-page --path "$MEMDIR/wikimem/<name>.md" \
  --tier hub|aspect|component --name <name> \
  --description "<the symptom words a future search will carry>" \
  --type project|user|feedback|reference \
  [--functionality <fn>] [--globs "src/frontend/**,..."]   # --globs: hubs only
```

**Add one atom per durable body fact** (`memgrep add-atom`, the fact on stdin).
`--keywords` is the atom's RECALL SURFACE — comma-separated key-phrases carrying
the SYMPTOM / the question a future session will search with, NOT the answer's
jargon. `--desc` is REQUIRED: a ≤200-char PROSE summary of the body (memgrep LISTS
hits by `desc`, not full body, so the reader triages by desc and opens only the one
atom worth reading; a missing/weak desc makes the atom invisible-at-a-glance). A
real summary, never a slug:

```bash
printf '%s' "<the durable fact, in full>" | memgrep add-atom \
  --page "$MEMDIR/wikimem/<name>.md" \
  --keywords "<symptom phrase A>, <symptom phrase B>" \
  --desc "<≤200-char prose summary of this fact>" [--type <t>]
```

Full page schema, tier semantics, and atom grammar (to READ, never to hand-write):
[atom-authoring.md](atom-authoring.md).

The frontmatter `new-page` writes carries `name`, `description` (symptom-indexed),
`ocd`, `lmd`, `metadata.{node_type: memory, type, tier}` (+ `functionality`; +
`globs` on hubs). The tier's edge sections — `## Applies to` on hub/aspect
(radiating), `## Governed by` on component (receiving); `## See also` optional on
any tier — you add in step 5 when you WIRE the context. The standing
`## Notes and lessons learned` section is always present (`new-page` emits it even
when empty).

**THE LESSON FORM.** A lesson is a first-class atom — a GUARDRAIL, not a story. Add
it with `memgrep add-lesson` (the DO-NOT/BECAUSE/DO text on stdin), anchored to the
atom it annotates; the tool emits the canonical
`[^N]: [id:…, status:valid, keywords:…, ocd:…, lmd:…] <text>` and wires the atom's
`[^N]` reference — you never type that grammar. The JUDGMENT is yours: `--keywords`
= the recall surface (the SEARCH words, underscore-joined phrases, not your prose's
own words); ONE lesson = ONE mistake, **≤3 lines / ~40 words**, all three prose
parts mandatory — `DO NOT` names the act, `BECAUSE` is the WHY, `DO … instead` is
the exit. Full grammar + WHY: [wikimem-model.md — THE LESSON
FORM](wikimem-model.md#the-lesson-form--mandatory-metadata-then-one-terse-shape).

```bash
printf '%s' "DO NOT <X>, BECAUSE <why>. DO <Y> instead." | memgrep add-lesson \
  --page "$MEMDIR/wikimem/<name>.md" --atom <atom-id> \
  --keywords "<recall phrase>" [--desc "<≤200-char context>"]
```
