---
name: pool-exhaustion
description: "requests hang forever under load / connection pool is exhausted / everything times out at exactly 30 seconds / the database is idle but the app is stuck"
ocd: 2026-07-20
lmd: 2026-07-20
metadata:
  node_type: memory
  type: project
  tier: component
---

How a bounded connection pool starves, and the two failure shapes that look identical from the
outside but need opposite fixes.

^pool-leak-on-early-return [desc: a_handler_that_returns_early_without_releasing_leaks_one_connection_per_request, keywords: requests hang forever under load, connection pool exhausted, pool size never recovers, connections leak on error path, every request times out after a while, type: project, ocd: 2026-07-20, lmd: 2026-07-20]
A handler that returns early on a validation error without releasing its checked-out connection
leaks exactly one connection per failed request. The pool degrades monotonically: healthy at
boot, dead after N bad requests, and it never recovers without a restart. The tell is that pool
utilisation only ever rises and never falls, even while traffic drops.

^slow-query-holds-the-pool [desc: one_slow_query_can_exhaust_a_pool_without_leaking_anything, keywords: everything times out at exactly 30 seconds, database is idle but the app is stuck, pool exhausted but no leak, one slow endpoint took down the whole service, type: project, ocd: 2026-07-20, lmd: 2026-07-20]
A pool can be exhausted with zero leaks: if one endpoint holds a connection for 30s, enough
concurrent calls to it will consume every slot while the database itself sits idle. Utilisation
rises AND falls, which distinguishes it from a leak. The fix is a statement timeout, not a bigger
pool — enlarging the pool moves the cliff without removing it.

^pool-size-is-not-the-fix [desc: raising_max_connections_hides_the_cliff_instead_of_removing_it, keywords: we just increased the pool size, raising max connections did not help, bigger pool still exhausted, type: project, ocd: 2026-07-20, lmd: 2026-07-20]
Raising `max_connections` converts a fast failure into a slow one. The database has its own
connection ceiling, so an oversized app pool relocates the exhaustion from the app to the
database, where it is harder to attribute.

## Notes and lessons learned

[^1]: [id:ATOM-POOL-9K2M, status:valid, keywords:"pool_exhausted_but_no_leak utilisation_only_rises", ocd:2026-07-20, lmd:2026-07-20] DO NOT diagnose pool exhaustion as a leak before looking at whether utilisation ever FALLS, BECAUSE a slow-query exhaustion and a leak present identically at the point of failure but need opposite fixes (a timeout vs a release). DO plot utilisation over time and check for recovery first.
