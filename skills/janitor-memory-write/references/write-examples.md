# MEMORIZE — worked examples

Three worked routing/shape examples for `/janitor-memory-write`. Moved here
verbatim from the SKILL body (TRDD-82OP4EN9 token-budget move).

## Table of contents

- [Worked examples (aspect / component / user-feedback)](#worked-examples-aspect--component--user-feedback)

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
