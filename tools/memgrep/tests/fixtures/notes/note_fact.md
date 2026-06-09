---
description: a fact-shaped note that also carries a lesson footnote
tags: [fact, demo]
---
# Facts with a lesson

2026-06-09T10:00:00+0200 #cache @builder :: the cache key includes the lockfile hash.[^1]

## Notes and lessons learned

[^1]: the first key omitted the lockfile and poisoned the cache. Lesson: hash all
  build inputs into the cache key.
