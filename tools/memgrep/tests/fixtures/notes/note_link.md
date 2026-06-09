---
description: build pipeline cache memory whose lesson carries a url and an image
tags: [build, cache]
---
# Build cache

The cache key must include the lockfile hash.[^2]

## Notes and lessons learned

[^2]: [class:reference] the cache poisoned because the key omitted the lockfile;
  see https://example.com/cache-bug and the diagram ![flow](img/cache-flow.png)
  and the [issue](https://example.com/issues/7). Lesson: key the cache on inputs.
