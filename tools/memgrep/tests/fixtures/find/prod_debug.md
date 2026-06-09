---
description: production debugger crash with a stack trace
tags: [production, debug, crash]
---
# Production debugger

The crash happened in the prod-debugger module during a production-debug run.[^1]

## Notes and lessons learned

[^1]: the prod-debug lesson — always attach the debugger before the production
  process forks, never after; the stack trace was empty otherwise.
