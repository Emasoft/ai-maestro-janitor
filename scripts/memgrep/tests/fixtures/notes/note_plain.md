---
description: widget retry cap memory with a corrected fact and a lesson
tags: [widget, retry]
---
# Widget retries

The widget retries 3× then fails.[^3]
It also backs off exponentially between attempts.[^4]

## Notes and lessons learned

[^3]: earlier this said "retries 5×"; wrong, the cap is 3 — the config key was
  misread as `max_attempts` when it is `max_retries`. Lesson: verify the constant
  against the source, not the variable name.
[^4]: the backoff base was assumed 1s; it is actually 2s. Lesson: read the default,
  don't guess it.
