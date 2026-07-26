---
name: object-store-consistency
description: "uploaded file not found immediately after write / listing does not show the new object / read after write returns 404 sometimes"
ocd: 2026-07-25
lmd: 2026-07-25
metadata:
  node_type: memory
  type: project
  tier: component
---

What an object store guarantees after a write, and the one operation that still lags.

^read-after-write-is-strong-now [desc: read_after_write_became_strongly_consistent_so_the_old_retry_advice_is_obsolete, keywords: uploaded_file_not_found_immediately_after_write read_after_write_returns_404_sometimes do_I_need_to_retry_after_upload, type: project, ocd: 2026-07-25, lmd: 2026-07-25, status: superseded, superseded-by: ATOM-OBJ-8W3D]
Read-after-write for new objects is strongly consistent on the major object stores, so a 404
immediately after a successful upload is a bug in the caller (wrong key, wrong bucket, wrong
region endpoint) rather than replication lag. The historical "sleep and retry" advice predates
that guarantee.

^listing-still-lags [desc: list_operations_remain_eventually_consistent_even_where_get_is_strong, keywords: listing_does_not_show_the_new_object object_exists_but_is_missing_from_the_listing list_after_put_is_stale, type: project, ocd: 2026-07-25, lmd: 2026-07-25]
LIST remains eventually consistent even where GET is strong: an object can be fetchable by key
while absent from a listing for a short window. Any workflow that discovers work by listing a
prefix inherits that lag, which is why a queue or a manifest beats a listing as a work source.

## Notes and lessons learned

[^1]: [id:ATOM-OBJ-8W3D, status:valid, keywords:"do_I_need_to_retry_after_upload sleep_and_retry_after_put", ocd:2026-07-25, lmd:2026-07-25] DO NOT add a sleep-and-retry after an object upload, BECAUSE read-after-write is strongly consistent for new keys and the retry converts a real caller bug (wrong key/bucket/region) into an intermittent one that is far harder to find. DO verify the key and endpoint instead. SUPERSEDED BODY: earlier guidance on this page said uploads needed a retry loop because the store was eventually consistent for GET; that was true historically and is no longer.
