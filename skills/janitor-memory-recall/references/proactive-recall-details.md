# Proactive-recall details (relocated from SKILL.md to stay under the token cap)

This file holds the full rationale and background prose for the RECALL skill's
PROACTIVE-USE CONTRACT, the "two axes" recall pattern, the enriched recall flag
list, and the worked examples. SKILL.md keeps only the operational core; this
file is the "why" and the extended detail — read it on demand, not by default.

## A PUSHED row is hop 1 already done for you — take hop 2

Every prompt may arrive with auto-surfaced `<date> <id> <description>` rows. They
are **not** ambient noise: they are a completed hop 1, delivered unasked. The
standing failure is to skim them as decoration and then go derive the answer by
hand.

**Rule: when a pushed row's description matches the question you are holding RIGHT
NOW, run `memgrep recall <that-id> "${ROOTS[@]}"` BEFORE you derive, brief, or
assert anything.** One cheap call, and it either lands the answer or costs you a
few hundred tokens. Re-derivation costs turns — and worse, produces a model built
on your guesses that someone else then has to correct.

Corollary: a row you have seen several fires in a row and still not opened is the
single strongest signal in your context that you are about to redo finished work.

## The trigger is RECONSTRUCTION as well as RISK

The recall triggers people remember are destructive — *before publishing, deleting,
force-pushing, rotating credentials*. Those are necessary and insufficient. The
expensive failure mode is not damage, it is **reconstruction**: spending turns
building an explanation the corpus already holds. Nothing is endangered, so no
risk-shaped trigger fires, and the waste is invisible until someone corrects the
model you derived.

So recall ALSO fires on these, which are observable actions rather than abstract
occasions (you can notice yourself doing them):

| You are about to… | Recall first |
|---|---|
| brief another agent/advisor on how a subsystem works | yes — a brief built on your reconstruction propagates your errors into their answer |
| assert a MECHANISM ("it behaves this way because…") | yes |
| spend more than ~2 turns deriving a model of existing behaviour | yes |
| explain an architecture to the user | yes |
| write a design doc / TRDD about an existing subsystem | yes |

The tell is the sentence forming in your head: *"the way this works is…"*. If you
are about to say that about code you did not just read, recall first.

**Delegating a decision does not exempt you.** Handing a design question to an
advisor or subagent still requires recall BEFORE the handoff — you are choosing
what facts they see, so an unrecalled brief silently caps the quality of their
answer at the quality of your memory.

## Two axes, two recalls — why the CASE page and the METHODOLOGY page are separate

The corpus keeps them apart on purpose — a case page holds facts about ITS subject, and a
transferable way of working (how to diagnose, verify, falsify; the reasoning traps) is owned by
a methodology page such as `debugging-methodology`. That keeps a case page on-topic, but it
also means **a symptom query alone will never surface the methodology**, because the
methodology page does not mention your symptom.

The second recall call (on the methodology axis) is the cheap one that pays: the traps a
methodology page records ("verify before you 'fix'", "absence of evidence is not evidence",
"falsify each layer separately") are exactly the ones a session under pressure re-walks into.
Recall them BEFORE the investigation, not while writing the post-mortem.

## Enriched recall — full flag reference

- `--sort score|ocd|lmd` (default relevance), `--order asc|desc` — `--sort lmd`
  for newest-touched first.
- `--since <ISO>` / `--until <ISO>` over `--date-field ocd|lmd` — "what did we
  decide about X last week".
- `--top N` (default 10); `--use-index` forces the SQLite sidecar (auto-used when
  fresh; results always correct).
- `memgrep find "+TERM -TERM \"phrase\"" "${ROOTS[@]}"` — note-level boolean keyword
  search; add `--only-notes` to search ONLY the lessons.

```bash
memgrep recall "$SYMPTOM" "${ROOTS[@]}" --sort lmd                # newest-touched first
memgrep find "+rotator +keychain -widget" "${ROOTS[@]}"           # AND / exclude
memgrep links --broken "${ROOTS[@]}"                              # context edges to fill (→ MEMORIZE/UPDATE)
```

## Worked examples

<example>
About to edit src/frontend/panels/Login.tsx
→ Entry A: find the `frontend` hub (its globs own src/frontend/**), read it, go to
  the [[login-panel]] component, read its `## Governed by` ([[style-system]],
  [[dialog-forms]]) — load those rulers once — and skip the rest of the tree.
</example>

<example>
User: the oauth rotator failed again and I had to log in manually
→ Entry B: recall "oauth rotator failed had to log in manually" → ranked hits like
  `oauth-rotator.md#rotate-cascade — rotate renew reauth keychain` (one exact fact,
  read it at that anchor) interleaved with `keychain-creds.md — where the creds live`
  (a whole page, lessons appended); read the few you need before touching it.
</example>

<example>
User: what do we know about the frontend before I restyle the dialogs?
→ Entry A from the `frontend` hub → descend into [[dialog-forms]] + [[style-system]].
</example>

## The navigation contract — the full case for "don't over-read"

Surface the TIP, read what the task needs, follow links on demand. Reading an
entire functionality's page tree "to be safe" defeats the wiki — its whole point
is that context spend stays proportional to the task. One hub + the component +
its two or three `## Governed by` rulers is the normal read. **Cache the suns:**
a shared general page (style, protocol) is read ONCE and reused across every
component it governs — so working across many components costs the governors only
once, not per component. That cacheability is why the wiki abstracts shared rules
into radiating pages instead of copying them into each element.
