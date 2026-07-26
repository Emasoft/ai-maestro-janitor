---
name: tls-chain-order
description: "certificate works in the browser but fails in curl / SSL handshake fails only on some clients / unable to get local issuer certificate"
ocd: 2026-07-21
lmd: 2026-07-21
metadata:
  node_type: memory
  type: project
  tier: component
---

Why a certificate that a browser accepts is rejected by everything else.

^browsers-repair-a-broken-chain [desc: browsers_fetch_missing_intermediates_so_they_hide_a_misordered_chain, keywords: certificate_works_in_the_browser_but_fails_in_curl SSL_handshake_fails_only_on_some_clients unable_to_get_local_issuer_certificate works_on_my_laptop_but_not_in_CI, type: project, ocd: 2026-07-21, lmd: 2026-07-21]
Browsers cache intermediates from previous sessions and will fetch a missing one via the AIA
extension, so they succeed against a chain that is incomplete or misordered. curl, openssl, and
most language HTTP clients do neither, so they fail on the same certificate. A browser is
therefore never evidence that a chain is correct.

^chain-must-be-leaf-first [desc: the_pem_bundle_must_run_leaf_then_intermediates_never_root_first, keywords: chain_order_wrong root_certificate_first_in_bundle openssl_verify_fails_but_cert_is_valid, type: project, ocd: 2026-07-21, lmd: 2026-07-21]
The bundle must be ordered leaf → intermediate(s), each certificate signed by the next. The root
is omitted entirely: the client already trusts it, and including it wastes handshake bytes.
`openssl s_client -showcerts` prints the chain as served, which is what to verify against.

## Notes and lessons learned

[^1]: [id:ATOM-TLS-4Q7X, status:valid, keywords:"works_in_browser_fails_in_curl", ocd:2026-07-21, lmd:2026-07-21] DO NOT verify a TLS chain with a browser, BECAUSE browsers silently repair broken chains via cached intermediates and AIA fetching, so they prove nothing about what other clients will see. DO verify with `openssl s_client -showcerts` from a machine with no prior session state.
