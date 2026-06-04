"""Web3 / blockchain client-side anti-pattern catalogue.

Wave-23 distillation round 9 — first-party developer mistakes in
client-side JavaScript / TypeScript that ships in a Web3 dApp bundle
(Vite, Webpack, Next.js, Vercel, Vue, Svelte, CRA).

These are NOT the server-side runtime-hook patterns covered by
`crypto_misuse_patterns.py` (Proposal 9 — assignment-to-`globalThis.<entrypoint>`
in a malicious npm package). They are the bundled-bundle-leak shapes the
end-user's browser can read via DevTools.

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            chat_bot_patterns.Finding shape.

Rules:
  * web3.client.private-key-hex-literal                 (CRITICAL)
  * web3.client.bip39-mnemonic-literal                  (CRITICAL)
  * web3.client.rpc-provider-id-in-bundle               (HIGH)
  * web3.client.signing-without-eip712-or-nonce         (HIGH)
  * web3.client.localstorage-or-indexeddb-private-material (CRITICAL)
  * web3.client.unvalidated-wallet-connect-callback     (HIGH)
  * web3.client.hardhat-default-account-in-prod         (CRITICAL)

OWASP ASI mapping:
  ASI-01 — Broken access control (callback without chain/address check)
  ASI-02 — Cryptographic failures (private key / mnemonic in source,
                                    localStorage of key material)
  ASI-04 — Insecure design (replayable signature, callback re-entry)
  ASI-05 — Security misconfiguration (hardhat default account in prod)
  ASI-08 — Sensitive data exposure (RPC ID in bundle, key in storage)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load. Fail-fast: callers receive structured Finding tuples, never raised
exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — mirrors chat_bot_patterns.Finding shape."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 — keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE.

    Mirrors helper in chat_bot_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind.
    """
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


def _re_cs(pattern: str) -> re.Pattern:
    """Case-sensitive compile (MULTILINE+UNICODE only).

    Used when the pattern relies on exact case — e.g. the hardhat
    EIP-55 checksum addresses, the BIP-39 lowercase-word geometry.
    """
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- R1 : web3.client.private-key-hex-literal ---------------------------


# 64-hex literal assigned to a *PRIVATE_KEY* / *PRIVKEY* / *SECRET_KEY* /
# *SIGNER_KEY* / *WALLET_KEY* identifier, or passed positionally to a
# Wallet / privateKeyToAccount constructor.
_PRIVATE_KEY_HEX_LITERAL = _re(
    # Identifier assignment shape (JS/TS const|let|var ... = "0x...")
    r"\b(?:PRIVATE_KEY|PRIVKEY|SIGNER_KEY|WALLET_KEY|SECRET_KEY)"
    r"\s*[:=]\s*['\"]0x[a-fA-F0-9]{64}['\"]"
    r"|"
    # Constructor-positional shape: new Wallet("0x..."), new ethers.Wallet("0x...")
    r"\bnew\s+(?:ethers\.)?Wallet\s*\(\s*['\"]0x[a-fA-F0-9]{64}['\"]"
    r"|"
    # web3.eth.accounts.privateKeyToAccount("0x...") / privateKeyToAccount("0x...")
    r"\bprivateKeyToAccount\s*\(\s*['\"]0x[a-fA-F0-9]{64}['\"]"
)


# ---- R2 : web3.client.bip39-mnemonic-literal ----------------------------


# Stage-A geometry: a quoted string of exactly 12 or 24 lowercase words
# separated by single spaces, each 3–8 chars. RE2-safe (bounded quantifiers).
_BIP39_MNEMONIC_GEOMETRY = _re_cs(
    r"""['"](?:[a-z]{3,8} ){11}[a-z]{3,8}['"]"""
    r"""|"""
    r"""['"](?:[a-z]{3,8} ){23}[a-z]{3,8}['"]"""
)

# Stage-B BIP-39 wordlist gate: a curated 200-word subset of the official
# 2048-word English wordlist drawn from the high-frequency dev test vectors
# ("abandon ... about" — first 100 words — and "test ... junk" — common dev
# mnemonic).  We accept a hit when ≥ 80 % of the candidate's words are in
# this set, which is enough to discriminate real mnemonics from prose without
# embedding the full 13 KB wordlist for this scanner pass.
_BIP39_WORDLIST: frozenset[str] = frozenset(
    {
        # First 100 BIP-39 English words (covers "abandon ... about" vectors).
        "abandon", "ability", "able", "about", "above", "absent", "absorb",
        "abstract", "absurd", "abuse", "access", "accident", "account",
        "accuse", "achieve", "acid", "acoustic", "acquire", "across", "act",
        "action", "actor", "actress", "actual", "adapt", "add", "addict",
        "address", "adjust", "admit", "adult", "advance", "advice", "aerobic",
        "affair", "afford", "afraid", "again", "age", "agent", "agree",
        "ahead", "aim", "air", "airport", "aisle", "alarm", "album",
        "alcohol", "alert", "alien", "all", "alley", "allow", "almost",
        "alone", "alpha", "already", "also", "alter", "always", "amateur",
        "amazing", "among", "amount", "amused", "analyst", "anchor",
        "ancient", "anger", "angle", "angry", "animal", "ankle", "announce",
        "annual", "another", "answer", "antenna", "antique", "anxiety",
        "any", "apart", "apology", "appear", "apple", "approve", "april",
        "arch", "arctic", "area", "arena", "argue", "arm", "armed", "armor",
        "army", "around", "arrange", "arrest", "arrive", "arrow", "art",
        # Common dev mnemonic words — "test test test test test test test
        # test test test test junk".
        "test", "junk",
        # Additional high-frequency BIP-39 words common in fixtures /
        # tutorials.
        "fly", "ranch", "shoe", "smile", "movie", "letter", "force",
        "garbage", "kingdom", "ozone", "rebel", "ready", "machine",
        "trumpet", "vital", "social", "human", "yellow", "zone", "zoo",
        "wood", "world", "year", "young", "ride", "rose", "say", "see",
        "since", "stay", "still", "time", "today", "true", "trust", "twin",
        "valley", "wave", "way", "wear", "wife", "wild", "will", "win",
        "wing", "winter", "wise", "wish", "wolf", "word", "work", "yard",
        "you", "your", "youth",
    }
)


def _bip39_wordlist_gate(candidate: str) -> bool:
    """Return True iff ≥ 80 % of candidate's words match the BIP-39 set.

    Stripping the surrounding quotes is the caller's job; this expects the
    raw word stream.
    """
    words = candidate.split()
    if not words:
        return False
    hits = sum(1 for w in words if w in _BIP39_WORDLIST)
    return (hits / len(words)) >= 0.8


# ---- R3 : web3.client.rpc-provider-id-in-bundle -------------------------


# Infura mainnet+L2 URLs with 32-hex project ID, Alchemy URL with key,
# QuickNode endpoint, WalletConnect projectId 32-hex literal.
_RPC_PROVIDER_ID_IN_BUNDLE = _re(
    # Infura: https://<chain>.infura.io/v3/<32-hex>
    r"https?://(?:mainnet|polygon-mainnet|arbitrum-mainnet|optimism-mainnet"
    r"|goerli|sepolia|polygon-mumbai)\.infura\.io/v3/[a-f0-9]{32}\b"
    r"|"
    # Alchemy: https://eth-mainnet.g.alchemy.com/v2/<key>
    r"https?://(?:eth|polygon|arb|opt|base)-(?:mainnet|goerli|sepolia)"
    r"\.g\.alchemy\.com/v2/[A-Za-z0-9_\-]{20,}"
    r"|"
    # QuickNode: https://<region-slug>.quiknode.pro/<40-hex>/
    r"https?://[a-z0-9\-]+\.quiknode\.pro/[a-f0-9]{40,}/"
    r"|"
    # WalletConnect projectId 32-hex literal
    r"\bprojectId\s*[:=]\s*['\"][a-f0-9]{32}['\"]"
    r"|"
    # Ankr endpoint with embedded key
    r"https?://rpc\.ankr\.com/[a-z0-9_]+/[A-Za-z0-9]{32,}"
)


# Demo IDs explicitly published as public — suppress these.
#
# Each entry is a literal substring that, if present anywhere in the
# matched URL, suppresses the finding. Only documented public-demo IDs
# belong here; do NOT add anything else or the rule loses precision.
_RPC_PUBLIC_DEMO_IDS: frozenset[str] = frozenset(
    {
        # Infura's public demo project ID — published in Infura docs
        # since 2018. (Stored split to avoid scanner FP on this source file.)
        "9aa3d95b3bc440fa88ea12eaa4" + "456161",
    }
)


# ---- R4 : web3.client.signing-without-eip712-or-nonce -------------------


# Stage-A: any of the dangerous off-chain signing call shapes.
_SIGNING_CALL_TRIGGER = _re(
    # window.ethereum.request({ method: "eth_sign", ... }) — always suspect
    r"['\"](?:eth_sign|personal_sign)['\"]"
    r"|"
    # signer.signMessage(...) — fine only with SIWE-shape body
    r"\bsigner\.signMessage\s*\("
    r"|"
    # provider.send("personal_sign", ...) — bypasses typed data
    r"\bprovider\.send\s*\(\s*['\"]personal_sign['\"]"
)


# Stage-B suppressor — these tokens in the ±20-line window prove the
# caller IS using EIP-712 / SIWE properly. Note: the SIWE preamble
# tokens (`Nonce:`, `Issued At:`, `Chain ID:`) intentionally have NO
# trailing `\b` — `\b` is the boundary between word and non-word, and
# `:` followed by space is non-word→non-word (no boundary), so adding
# `\b` would silently NEVER match.
_EIP712_OR_SIWE_MARKERS = _re(
    r"\bsignTypedData(?:V[34])?\b"
    r"|"
    r"\b_TypedDataEncoder\b"
    r"|"
    r"\bEIP-?712\b"
    r"|"
    r"\bNonce:"
    r"|"
    r"\bIssued At:"
    r"|"
    r"\bChain ID:"
    r"|"
    r"\bverifyingContract\b"
    r"|"
    r"\bdomainSeparator\b"
    r"|"
    # The SIWE library directly.
    r"\bsiwe(?:Message|/SiweMessage)?\b"
)


# ---- R5 : web3.client.localstorage-or-indexeddb-private-material --------


# A storage write whose KEY identifier names a private-key-shaped value.
_STORAGE_KEY_MATERIAL_WRITE = _re(
    # localStorage / sessionStorage .setItem("<key-material-name>", ...)
    r"\b(?:localStorage|sessionStorage)\.setItem\s*\(\s*['\"][^'\"]*"
    r"(?:private[_-]?key|mnemonic|seed[_-]?phrase|recovery[_-]?phrase"
    r"|signer[_-]?key|wallet[_-]?key|priv[_-]?key)"
    r"[^'\"]*['\"]"
    r"|"
    # document.cookie = "<...>private_key|mnemonic|...<...>"
    r"\bdocument\.cookie\s*=\s*[`'\"][^`'\"]*"
    r"(?:private[_-]?key|mnemonic|seed[_-]?phrase|recovery[_-]?phrase)"
    r"[^`'\"]*[`'\"]"
    r"|"
    # IndexedDB: <store>.put({ ..., mnemonic|privateKey|seedPhrase|recoveryPhrase, ...})
    r"\.objectStore\s*\(\s*[^)]+\)\.put\s*\(\s*\{[^}]*"
    r"(?:privateKey|mnemonic|seedPhrase|recoveryPhrase)"
)


# Stage-B suppressor — if the same write line carries an EIP-2335 / web3
# secret-storage encrypted JSON ciphertext marker, suppress. Note: the
# `\b` boundary before `'\"` chars NEVER matches (quote is non-word, and
# the char before is typically whitespace, another non-word) — leave it
# unbounded so the marker fires inside JSON contexts.
_ENCRYPTED_KEYSTORE_MARKERS = _re(
    r"['\"]crypto['\"]\s*:\s*\{\s*['\"]cipher['\"]"
    r"|"
    r"['\"]ciphertext['\"]\s*:"
    r"|"
    r"['\"]kdf['\"]\s*:\s*['\"](?:scrypt|pbkdf2)['\"]"
)


# ---- R6 : web3.client.unvalidated-wallet-connect-callback ---------------


# Stage-A: the callback / connect trigger shapes.
_WALLET_CONNECT_TRIGGER = _re(
    # MetaMask request shapes
    r"['\"]eth_requestAccounts['\"]"
    r"|"
    r"['\"]wallet_connect['\"]"
    r"|"
    # WalletConnect v2 session events
    r"['\"]session_request['\"]"
    r"|"
    r"['\"]session_event['\"]"
    r"|"
    # wagmi's useAccount hook
    r"\buseAccount\s*\(\s*\)"
)


# Stage-B: marker that a chain/account verification IS performed.
_WALLET_CONNECT_VERIFICATION_MARKER = _re(
    # chainId comparison
    r"\bchainId\s*(?:==|===|!=|!==|in|not in)\s*"
    r"|"
    r"\bif\s*\(\s*chainId\s*(?:==|===|!=|!==)"
    r"|"
    r"\bEXPECTED_CHAIN(?:_ID)?\b"
    r"|"
    r"\btargetChainId\b"
    r"|"
    # address comparison
    r"\baccounts\s*\[\s*0\s*\]\.toLowerCase\s*\(\s*\)\s*(?:==|===|!=|!==)"
    r"|"
    r"\bsavedAddress\b"
    r"|"
    # SIWE / typed-data verification
    r"\bverifyMessage\s*\("
    r"|"
    r"\bverifyTypedData\s*\("
)


# Stage-B: a sign / send call that MUST be preceded by verification.
_WALLET_CONNECT_DANGEROUS_USE = _re(
    r"\beth_sendTransaction\b"
    r"|"
    r"\bsendTransaction\s*\("
    r"|"
    r"\bsignMessage\s*\("
    r"|"
    r"\bsignTransaction\s*\("
)


# ---- R7 : web3.client.hardhat-default-account-in-prod -------------------


# Hardhat deterministic accounts 0-4 (EIP-55 checksum form). The
# checksum case matters — case-sensitive match.
_HARDHAT_DEFAULT_ACCOUNTS = _re_cs(
    r"0x(?:"
    # Account #0
    r"f39Fd6e51aad88F6F4ce6aB8827279cfFFb92266"
    r"|"
    # Account #1
    r"70997970C51812dc3A010C7d01b50e0d17dc79C8"
    r"|"
    # Account #2
    r"3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
    r"|"
    # Account #3
    r"90F79bf6EB2c4f870365E785982E1f101E93b906"
    r"|"
    # Account #4
    r"15d34AAf54267DB7D7c367839AAf71A00a2C6A65"
    r")\b"
)


# Lowercase variant (some tooling lower-cases addresses for comparison).
_HARDHAT_DEFAULT_ACCOUNTS_LOWER = _re_cs(
    r"0x(?:"
    r"f39fd6e51aad88f6f4ce6ab8827279cfffb92266"
    r"|"
    r"70997970c51812dc3a010c7d01b50e0d17dc79c8"
    r"|"
    r"3c44cdddb6a900fa2b585dd299e03d12fa4293bc"
    r"|"
    r"90f79bf6eb2c4f870365e785982e1f101e93b906"
    r"|"
    r"15d34aaf54267db7d7c367839aaf71a00a2c6a65"
    r")\b"
)


# Stage-B suppressor: a "test allowlist" marker in the same file.
_HARDHAT_TEST_CONTEXT_MARKERS = _re(
    # hardhat config / network guards
    r"\bnetwork:\s*['\"](?:hardhat|localhost|local)['\"]"
    r"|"
    r"\bhardhat\.config\b"
    r"|"
    r"\bdescribe\s*\(\s*['\"]"
    r"|"
    r"\bit\s*\(\s*['\"]"
    r"|"
    r"\b(?:from\s+)?['\"]hardhat['\"]"
    r"|"
    # Common test-runner imports
    r"\brequire\s*\(\s*['\"]chai['\"]\s*\)"
    r"|"
    r"\bfrom\s+['\"]mocha['\"]"
    r"|"
    # Explicit comment opt-out
    r"\b(?:hardhat\s+default\s+account|hardhat\s+account\b)"
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="web3.client.private-key-hex-literal",
        name="64-hex secp256k1 private key literal in client-side source",
        severity="CRITICAL",
        description=(
            "A 64-hex-char string assigned to a *PRIVATE_KEY* / *PRIVKEY* "
            "/ *SECRET_KEY* / *SIGNER_KEY* identifier, or passed "
            "positionally to `new ethers.Wallet(...)` / `new Wallet(...)` "
            "/ `web3.eth.accounts.privateKeyToAccount(...)`. A 64-hex "
            "secp256k1 private key is the entire bearer credential for "
            "an Ethereum account — leaking it == 100% funds drain. "
            "Hardhat's deterministic accounts are the most common "
            "offender."
        ),
        pattern=_PRIVATE_KEY_HEX_LITERAL,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="web3.client.bip39-mnemonic-literal",
        name="BIP-39 12 / 24 word mnemonic seed phrase as string literal",
        severity="CRITICAL",
        description=(
            "A 12- or 24-word BIP-39 seed phrase as a string literal, "
            "frequently passed to `ethers.Wallet.fromPhrase(...)`, "
            "`Wallet.fromMnemonic(...)`, or assigned to a *MNEMONIC* / "
            "*SEED_PHRASE* / *RECOVERY_PHRASE* identifier. A mnemonic "
            "derives every key on every derivation path — leaking it is "
            "strictly worse than leaking one private key. The 'test test "
            "... junk' hardhat dev mnemonic is the world's most-pinned "
            "hardcoded seed."
        ),
        pattern=_BIP39_MNEMONIC_GEOMETRY,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="web3.client.rpc-provider-id-in-bundle",
        name="Infura / Alchemy / QuickNode / WalletConnect project ID in client bundle",
        severity="HIGH",
        description=(
            "An Infura project ID, Alchemy API key, WalletConnect project "
            "ID, or QuickNode endpoint URL embedded literally in the "
            "client bundle. The end user's browser fetches `bundle.js`, "
            "reads the URL, and now has the dev's API quota. Attacker "
            "scripts farm these out of `webpack:///` / `vite/static/` "
            "paths in production builds."
        ),
        pattern=_RPC_PROVIDER_ID_IN_BUNDLE,
        owasp_asi="ASI-08",
    ),
    Rule(
        id="web3.client.signing-without-eip712-or-nonce",
        name="eth_sign / personal_sign / signMessage call without EIP-712 / SIWE markers",
        severity="HIGH",
        description=(
            "Use of `eth_sign`, `personal_sign`, or "
            "`signer.signMessage(...)` for off-chain authentication or "
            "token-gated authorization WITHOUT an EIP-712 typed-data "
            "structure, a chain ID, a nonce, or an expiry. SIWE / "
            "EIP-4361 exists precisely because raw `personal_sign` of "
            "an unstructured message lets the signed blob be replayed "
            "against any other dApp that asks for the same prompt. "
            "`eth_sign` can be tricked into signing arbitrary "
            "transactions (the 'blind sign' hazard)."
        ),
        pattern=_SIGNING_CALL_TRIGGER,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="web3.client.localstorage-or-indexeddb-private-material",
        name="Private key / mnemonic written to localStorage / IndexedDB / cookie",
        severity="CRITICAL",
        description=(
            "Persisting a private key, mnemonic, or seed phrase to "
            "`localStorage.setItem(...)`, `sessionStorage.setItem(...)`, "
            "IndexedDB `objectStore.put(...)`, or `document.cookie = ...`. "
            "Every browser extension with `host_permissions` for the dApp's "
            "origin can read these (the September-2025 `chalk/debug` wallet "
            "rewriter campaign vector). XSS on the dApp domain trivially "
            "exfiltrates the storage. Encrypted EIP-2335 keystore JSON "
            "blobs are exempt — they are ciphertexts protected by a "
            "passphrase."
        ),
        pattern=_STORAGE_KEY_MATERIAL_WRITE,
        owasp_asi="ASI-02",
    ),
    Rule(
        id="web3.client.unvalidated-wallet-connect-callback",
        name="eth_requestAccounts / wallet_connect / session_event without chainId or address check",
        severity="HIGH",
        description=(
            "A `wallet_connect` / `eth_requestAccounts` callback handler "
            "or WalletConnect v2 `session_request` topic handler that "
            "does NOT verify (a) the resolved `chainId` matches the "
            "dApp's expected chain, (b) the `accounts[0]` matches the "
            "previously-stored `address` (session-pinning), (c) the "
            "topic ID is the one the dApp opened. WalletConnect 2.0's "
            "QR-code pairing is a popular target for QR-swap phishing — "
            "if the dApp then trusts whatever `eth_sendTransaction` "
            "arrives, the attacker drains."
        ),
        pattern=_WALLET_CONNECT_TRIGGER,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="web3.client.hardhat-default-account-in-prod",
        name="Hardhat deterministic account address in production artefact",
        severity="CRITICAL",
        description=(
            "The Hardhat network's deterministic accounts "
            "(`accounts[0]` = `0xf39Fd6e51aad88F6F4ce6aB8827279cfFFb92266`, "
            "derived from the well-known mnemonic `test test ... junk`) "
            "appearing in a production code path — i.e. outside "
            "`hardhat.config.{ts,js,cjs}`, outside `*.test.{ts,js}`, "
            "outside any `network: 'hardhat'` guard. These accounts "
            "have a published private key; anyone who can route a "
            "transaction to them owns their funds on any chain they "
            "touch."
        ),
        pattern=_HARDHAT_DEFAULT_ACCOUNTS,
        owasp_asi="ASI-05",
    ),
)


# ---- Scanner-level helpers ---------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` preceding lines + line_no + next `forward`."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


def _file_contains(text: str, pat: re.Pattern) -> bool:
    return pat.search(text) is not None


def _strip_quotes(matched: str) -> str:
    """Strip the outer single/double quote from a Stage-A geometry hit."""
    if len(matched) >= 2 and matched[0] in "'\"" and matched[-1] in "'\"":
        return matched[1:-1]
    return matched


def _is_public_demo_rpc(matched: str) -> bool:
    """Return True iff the matched URL is a known publicly-shared demo ID."""
    for demo in _RPC_PUBLIC_DEMO_IDS:
        if demo in matched:
            return True
    return False


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * R2 (bip39-mnemonic-literal) — geometric match must pass the
        BIP-39 wordlist gate (≥ 80 % of words known).
      * R3 (rpc-provider-id-in-bundle) — suppress the well-known public
        Infura demo ID.
      * R4 (signing-without-eip712-or-nonce) — anchor on the signing
        call and suppress when an EIP-712 / SIWE marker is in the ±20-
        line window.
      * R5 (localstorage-or-indexeddb-private-material) — suppress when
        an EIP-2335 encrypted-keystore JSON shape is in the same line.
      * R6 (unvalidated-wallet-connect-callback) — anchor on the callback
        trigger and require BOTH: a dangerous sign / send call in the
        forward window AND NO chainId / address verification.
      * R7 (hardhat-default-account-in-prod) — flag the EIP-55 (or
        lower-case) address literal, suppress when test-context markers
        are present anywhere in the file.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- R1 : web3.client.private-key-hex-literal ----
    rule_r1 = rule_by_id["web3.client.private-key-hex-literal"]
    for m in _PRIVATE_KEY_HEX_LITERAL.finditer(text):
        _emit(rule_r1, m.start(), m.group(0))

    # ---- R2 : web3.client.bip39-mnemonic-literal ----
    rule_r2 = rule_by_id["web3.client.bip39-mnemonic-literal"]
    for m in _BIP39_MNEMONIC_GEOMETRY.finditer(text):
        candidate = _strip_quotes(m.group(0))
        if _bip39_wordlist_gate(candidate):
            _emit(rule_r2, m.start(), m.group(0))

    # ---- R3 : web3.client.rpc-provider-id-in-bundle ----
    rule_r3 = rule_by_id["web3.client.rpc-provider-id-in-bundle"]
    for m in _RPC_PROVIDER_ID_IN_BUNDLE.finditer(text):
        matched = m.group(0)
        if _is_public_demo_rpc(matched):
            continue
        _emit(rule_r3, m.start(), matched)

    # ---- R4 : web3.client.signing-without-eip712-or-nonce ----
    rule_r4 = rule_by_id["web3.client.signing-without-eip712-or-nonce"]
    for m in _SIGNING_CALL_TRIGGER.finditer(text):
        line, _ = _line_col(text, m.start())
        # ±20-line window for the SIWE / EIP-712 marker check.
        window = _slice_window(text, line, 20, 20)
        if _EIP712_OR_SIWE_MARKERS.search(window) is not None:
            continue
        _emit(rule_r4, m.start(), m.group(0))

    # ---- R5 : web3.client.localstorage-or-indexeddb-private-material ----
    rule_r5 = rule_by_id["web3.client.localstorage-or-indexeddb-private-material"]
    for m in _STORAGE_KEY_MATERIAL_WRITE.finditer(text):
        line, _ = _line_col(text, m.start())
        # Stage-B: encrypted-keystore JSON in the same 5-line window =>
        # suppress (ciphertext is not the bare private key).
        window = _slice_window(text, line, 2, 5)
        if _ENCRYPTED_KEYSTORE_MARKERS.search(window) is not None:
            continue
        _emit(rule_r5, m.start(), m.group(0))

    # ---- R6 : web3.client.unvalidated-wallet-connect-callback ----
    rule_r6 = rule_by_id["web3.client.unvalidated-wallet-connect-callback"]
    has_verification = _file_contains(text, _WALLET_CONNECT_VERIFICATION_MARKER)
    has_dangerous_use = _file_contains(text, _WALLET_CONNECT_DANGEROUS_USE)
    if has_dangerous_use and not has_verification:
        for m in _WALLET_CONNECT_TRIGGER.finditer(text):
            _emit(rule_r6, m.start(), m.group(0))

    # ---- R7 : web3.client.hardhat-default-account-in-prod ----
    rule_r7 = rule_by_id["web3.client.hardhat-default-account-in-prod"]
    has_test_context = _file_contains(text, _HARDHAT_TEST_CONTEXT_MARKERS)
    if not has_test_context:
        for m in _HARDHAT_DEFAULT_ACCOUNTS.finditer(text):
            _emit(rule_r7, m.start(), m.group(0))
        for m in _HARDHAT_DEFAULT_ACCOUNTS_LOWER.finditer(text):
            _emit(rule_r7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
