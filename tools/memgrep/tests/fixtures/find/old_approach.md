---
description: the old approach to retry handling we abandoned
tags: [retry, deprecated]
---
# Old approach

We used to retry synchronously — the old approach blocked the event loop.[^5]

## Notes and lessons learned

[^5]: the old approach retried on the calling thread; switch to an async queue so
  a slow retry never stalls the loop.
