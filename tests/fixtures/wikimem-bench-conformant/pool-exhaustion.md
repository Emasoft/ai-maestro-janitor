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

^pool-leak-on-early-return [desc: a_handler_that_returns_early_without_releasing_leaks_one_connection_per_request, keywords: requests_hang_forever_under_load connection_pool_exhausted pool_size_never_recovers connections_leak_on_error_path every_request_times_out_after_a_while, type: project, ocd: 2026-07-20, lmd: 2026-07-20]
A handler that returns early on a validation error without releasing its checked-out connection
leaks exactly one connection per failed request. The pool degrades monotonically: healthy at
boot, dead after N bad requests, and it never recovers without a restart. The tell is that pool
utilisation only ever rises and never falls, even while traffic drops.

^slow-query-holds-the-pool [desc: one_slow_query_can_exhaust_a_pool_without_leaking_anything, keywords: everything_times_out_at_exactly_30_seconds database_is_idle_but_the_app_is_stuck pool_exhausted_but_no_leak one_slow_endpoint_took_down_the_whole_service, type: project, ocd: 2026-07-20, lmd: 2026-07-20]
A pool can be exhausted with zero leaks: if one endpoint holds a connection for 30s, enough
concurrent calls to it will consume every slot while the database itself sits idle. Utilisation
rises AND falls, which distinguishes it from a leak. The fix is a statement timeout, not a bigger
pool — enlarging the pool moves the cliff without removing it.

^pool-size-is-not-the-fix [desc: raising_max_connections_hides_the_cliff_instead_of_removing_it, keywords: we_just_increased_the_pool_size raising_max_connections_did_not_help bigger_pool_still_exhausted, type: project, ocd: 2026-07-20, lmd: 2026-07-20]
Raising `max_connections` converts a fast failure into a slow one. The database has its own
connection ceiling, so an oversized app pool relocates the exhaustion from the app to the
database, where it is harder to attribute.

## Notes and lessons learned

[^1]: [id:ATOM-POOL-9K2M, status:valid, keywords:"pool_exhausted_but_no_leak utilisation_only_rises", ocd:2026-07-20, lmd:2026-07-20] DO NOT diagnose pool exhaustion as a leak before looking at whether utilisation ever FALLS, BECAUSE a slow-query exhaustion and a leak present identically at the point of failure but need opposite fixes (a timeout vs a release). DO plot utilisation over time and check for recovery first.
