# UPDATE — the CORRECT and RESHAPE procedures

Loaded on demand by `/janitor-memory-update`. The skill body carries THE UPDATE
INVARIANT (what supersession is, and when a lesson is warranted); this file carries the
two long procedures, which are only needed once you know which one you are doing.

## 2. CORRECT a memory — the 2-step NON-DESTRUCTIVE protocol

When a new discovery CONTRADICTS an existing memory, an AGENT must change it
(never the janitor), in exactly two steps — so the FACTS stay clean but the ERROR
is never lost (RULE 0 + the Bug-Autopsy directive: every fixed mistake becomes a
guardrail):

1. **Clean the fact in place.** Replace the wrong statement in the body with the
   correct one. The body is always the current truth — no "we used to think X"
   clutter inline. Two sanctioned paths (TRDD-7YHT3FNK — never raw shell, which has
   neither lock nor staleness guard): `memgrep edit --page <page> --old-file F1
   --new-file F2` (scope-locked, applies only on an exact unique match of the
   original text; on its changed-since-enqueued refusal, re-read and retry), or the
   harness Edit tool (its own old-string + changed-on-disk guards). Hand the heavier
   reshapes of §3 to the `janitor-memory-subconscious-agent`.
2. **Demote the error to a dated lesson — the WHY is the point.** Add it with
   `memgrep add-lesson --page <page> --atom <atom-id> --keywords "<recall phrase>"`
   (the DO-NOT/BECAUSE/DO text on stdin) — the tool files the numbered entry under
   `## Notes and lessons learned`, anchors the corrected fact's atom to it with a
   `[^N]` footnote, and guarantees the grammar; you never hand-write it. The
   load-bearing content is *why the previous statement was wrong* — the root
   cause. A lesson without a WHY cannot stop the next repeat.

### THE LESSON FORM — mandatory metadata, then one terse shape

A lesson is a first-class ATOM OF MEMORY, exactly like a body atom — a GUARDRAIL,
not a story. Write every `[^N]` in exactly this form:

```
[^N]: [keywords:"<key_phrase> <key_phrase> …", ocd:<YYYY-MM-DD>, lmd:<YYYY-MM-DD>] DO NOT <X>, BECAUSE <why>. DO <Y> instead.
```

All three metadata keys REQUIRED (the block is the lesson's ADDRESS); `keywords:` is
the RECALL SURFACE, written as underscore_joined key-phrases (the SEARCH words, not
your prose's own words — a lesson with none is findable only by accident of phrasing).
`ocd:`/`lmd:` are REQUIRED dates intrinsic to the lesson (survive the librarian moving
it between pages, so they — not file mtime — are its authoritative age; `--since`/
`--until` read them). Then the prose: **ONE lesson = ONE mistake**, **≤3 lines / ~40
words** (an unread guardrail guards nothing — cut chronology, the BODY already carries
current truth), and all three parts mandatory — `DO NOT` names the act, `BECAUSE` is
the WHY, `DO … instead` is the exit. Full grammar + rationale:
[the lesson form](../../janitor-memory-write/references/wikimem-model.md#the-lesson-form--mandatory-metadata-then-one-terse-shape).

```markdown
The widget retries 3× then fails.[^3] Tune via the `max_retries` config key.

## Notes and lessons learned
[^3]: [keywords:"retry_cap guessed_variable_name constant_lookup", ocd:2026-06-09, lmd:2026-06-09]
  DO NOT read a constant off a guessed variable name, BECAUSE `max_attempts` does not exist
  and the real cap is `max_retries` = 3, not the 5 this page used to claim. DO read the
  constant from the source instead.
```

memgrep strips the `[ocd:… lmd:…]` prefix in the default render and restores it
under `--full-notes`. A subject's lessons collect in its own page, recallable
with `memgrep find "<symptom>" "${ROOTS[@]}" --only-notes`.

## 3. RESHAPE — the page outgrew its tier (keep the pyramid honest)

Editing reveals a page is the wrong shape. Three moves (each = a real content
move + relink, NOT a silent copy):

- **EXPAND (extract a now-shared rule):** a `component` page accumulated a rule
  that other components ALSO follow. Move that rule OUT into a new RADIATING
  `aspect` page; replace it in the component with a `## Governed by` link UP to
  the aspect; and on the aspect's `## Applies to`, radiate DOWN to that component
  AND every other follower (find them:
  `memgrep -l "$MEMDIR" --where 'fm.tier "component" and fm.functionality "<fn>"' | sort -u`).
  Now the rule has one home and every follower points up to it — the duplication
  is gone.
- **REDUCE (push element-specific detail down):** a general page (`aspect`/`hub`)
  collected detail that affects only ONE element. Move it INTO that element's
  `component` page (create it if absent). If the general page still governs the
  element for OTHER rules, keep the `## Applies to`/`## Governed by` edge;
  otherwise the moved detail is purely the component's own (no edge). The general
  page stays general.
- **MERGE (heal fragmentation):** two pages describe the SAME element from
  different subjects (`login-panel-style` + `login-panel-behavior`). Merge into
  the single `component` page (`login-panel`), make the subjects SECTIONS within
  it, repoint every inbound `[[link]]` to the survivor, and delete the duplicate
  ONLY after it is committed (RULE 0). Prefer handing large merges to the janitor
  librarian, which deduplicates corpus-wide. On PROJECT pages the survivor's
  `publish-globally:` is `true` if EITHER source was `true` — merging must never
  silently un-publish a fact another project already relies on; `memgrep lint
  normalization then reconciles the symlink.
- **RENAME (inbound links FIRST):** renaming a page breaks EVERY inbound
  `[[link]]` at once. Order: (1) list who points at it —
  `memgrep links --from <old-name> <memdir>`; (2) repoint every inbound
  `[[old-name]]` → `[[new-name]]` on those pages; (3) rename the file AND its
  frontmatter `name:` (must stay equal), then `memgrep reindex <memdir>` (do NOT
  touch `MEMORY.md`); (4) re-audit — `memgrep links --broken <memdir>` must show
  nothing new. Never rename by just moving the file — that strands the inbound web.

After any reshape: fix See-also on BOTH endpoints, update the hub's parts map,
bump `lmd:` on every touched page, and re-run `memgrep links --broken` to confirm
you left no dangling edge.

