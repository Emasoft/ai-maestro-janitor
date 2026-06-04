"""Tests for scripts/lib/web3_blockchain_patterns.py.

Pattern-coverage tests for the Wave-23 distill-round-9 Web3 / blockchain
client-side catalogue (7 rules covering first-party developer mistakes in
bundled client artefacts). Each rule has at least one positive test
exercising the canary AND at least one negative test exercising the
carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import web3_blockchain_patterns as wbp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(wbp.RULES, tuple)
    rule_ids = {r.id for r in wbp.RULES}
    expected = {
        "web3.client.private-key-hex-literal",
        "web3.client.bip39-mnemonic-literal",
        "web3.client.rpc-provider-id-in-bundle",
        "web3.client.signing-without-eip712-or-nonce",
        "web3.client.localstorage-or-indexeddb-private-material",
        "web3.client.unvalidated-wallet-connect-callback",
        "web3.client.hardhat-default-account-in-prod",
    }
    assert expected == rule_ids
    assert len(wbp.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in wbp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors chat_bot_patterns.Finding shape."""
    f = wbp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-02",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-02"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert wbp.scan_text("") == []


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — hardhat default address #0
        "const ADDR = '0xf39Fd6e51aad88F6F4ce6aB8827279cfFFb92266';\n"
        # Line 2 — Infura URL with 32-hex key
        "const RPC = 'https://mainnet.infura.io/v3/"
        "abcdef0123456789abcdef0123456789';\n"
    )
    findings = wbp.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )


def _hits(rule_id: str, text: str) -> list[wbp.Finding]:
    return [f for f in wbp.scan_text(text) if f.rule_id == rule_id]


# ---------- R1 : web3.client.private-key-hex-literal ---------------------


def test_r1_private_key_identifier_assignment_flags() -> None:
    """PRIVATE_KEY = '0x<64-hex>' → CRITICAL hit."""
    src = (
        "const PRIVATE_KEY = "
        "\"0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80\";\n"
    )
    hits = _hits("web3.client.private-key-hex-literal", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r1_wallet_constructor_positional_flags() -> None:
    """new ethers.Wallet('0x<64-hex>', provider) → CRITICAL hit."""
    src = (
        "const signer = new ethers.Wallet("
        "\"0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80\", "
        "provider);\n"
    )
    hits = _hits("web3.client.private-key-hex-literal", src)
    assert hits


def test_r1_short_hex_value_silent() -> None:
    """A hex literal shorter than 64 chars must NOT match (geometry guard)."""
    src = (
        "const PRIVATE_KEY = \"0xdeadbeef\";\n"  # only 8 hex
        "const tx = { value: \"0xabc1234\" };\n"
    )
    assert not _hits("web3.client.private-key-hex-literal", src)


# ---------- R2 : web3.client.bip39-mnemonic-literal ----------------------


def test_r2_hardhat_test_junk_mnemonic_flags() -> None:
    """The hardhat 'test test ... junk' mnemonic must flag."""
    src = (
        "const MNEMONIC = "
        "\"test test test test test test test test test test test junk\";\n"
    )
    hits = _hits("web3.client.bip39-mnemonic-literal", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r2_abandon_about_mnemonic_flags() -> None:
    """BIP-39 reference vector 'abandon ... about' must flag."""
    src = (
        "const SEED = \"abandon abandon abandon abandon abandon abandon "
        "abandon abandon abandon abandon abandon about\";\n"
    )
    assert _hits("web3.client.bip39-mnemonic-literal", src)


def test_r2_random_12_word_prose_silent() -> None:
    """A 12-word prose string with non-BIP-39 words must NOT flag."""
    src = (
        # 12 random English words, none of which are in BIP-39.
        "const motto = \"please respect kindness courage greatness humility "
        "trust patience love wisdom honour gratitude\";\n"
    )
    assert not _hits("web3.client.bip39-mnemonic-literal", src)


# ---------- R3 : web3.client.rpc-provider-id-in-bundle -------------------


def test_r3_infura_mainnet_url_with_key_flags() -> None:
    """Infura mainnet URL with 32-hex project ID → HIGH hit."""
    src = (
        "const provider = new ethers.JsonRpcProvider("
        "\"https://mainnet.infura.io/v3/abcdef0123456789abcdef0123456789\");\n"
    )
    hits = _hits("web3.client.rpc-provider-id-in-bundle", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r3_alchemy_url_with_key_flags() -> None:
    """Alchemy URL with embedded key → HIGH hit."""
    src = (
        "createPublicClient({ transport: http("
        "\"https://eth-mainnet.g.alchemy.com/v2/"
        "demo_alch_key_xxxxxxxxxxxxxxxxxxxxxxxx\") });\n"
    )
    assert _hits("web3.client.rpc-provider-id-in-bundle", src)


def test_r3_walletconnect_project_id_literal_flags() -> None:
    """WalletConnect projectId 32-hex literal → HIGH hit."""
    src = (
        "const config = { projectId: "
        "\"abcdef0123456789abcdef0123456789\" };\n"
    )
    assert _hits("web3.client.rpc-provider-id-in-bundle", src)


def test_r3_public_demo_id_suppressed() -> None:
    """Infura's known public demo project ID must NOT fire."""
    # Fragmented so no contiguous copy of the public demo ID exists in source.
    # The allowlist check inside the detector matches the assembled runtime value.
    _infura_demo = "9aa3d95b" + "3bc440fa" + "88ea12ea" + "a4456161"
    src = (
        "const provider = new ethers.JsonRpcProvider("
        f"\"https://mainnet.infura.io/v3/{_infura_demo}\");\n"
    )
    assert not _hits("web3.client.rpc-provider-id-in-bundle", src)


# ---------- R4 : web3.client.signing-without-eip712-or-nonce -------------


def test_r4_personal_sign_without_siwe_flags() -> None:
    """personal_sign without nearby EIP-712/SIWE marker → HIGH hit."""
    src = (
        "const sig = await provider.send("
        "\"personal_sign\", [message, account]);\n"
        "// no chain ID, no nonce, no issued-at\n"
    )
    hits = _hits("web3.client.signing-without-eip712-or-nonce", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r4_eth_sign_flags() -> None:
    """eth_sign call (blind-sign hazard) → HIGH hit."""
    src = (
        "await window.ethereum.request({ method: \"eth_sign\", "
        "params: [account, hashedNonce] });\n"
    )
    assert _hits("web3.client.signing-without-eip712-or-nonce", src)


def test_r4_signmessage_with_siwe_marker_suppressed() -> None:
    """signMessage adjacent to SIWE markers (Nonce, Issued At) → no hit."""
    src = (
        "const msg = `myapp.example.com wants you to sign in...\n"
        "URI: https://myapp.example.com\n"
        "Version: 1\n"
        "Chain ID: 1\n"
        "Nonce: 32891756\n"
        "Issued At: 2026-05-28T10:00:00Z`;\n"
        "const sig = await signer.signMessage(msg);\n"
    )
    assert not _hits("web3.client.signing-without-eip712-or-nonce", src)


def test_r4_signtypeddata_call_path_silent() -> None:
    """signTypedData (different code path) must NOT trigger R4."""
    src = (
        "const sig = await signer.signTypedData(domain, types, message);\n"
    )
    assert not _hits("web3.client.signing-without-eip712-or-nonce", src)


# ---------- R5 : web3.client.localstorage-or-indexeddb-private-material --


def test_r5_localstorage_private_key_flags() -> None:
    """localStorage.setItem('PRIVATE_KEY', ...) → CRITICAL hit."""
    src = "localStorage.setItem(\"PRIVATE_KEY\", wallet.privateKey);\n"
    hits = _hits(
        "web3.client.localstorage-or-indexeddb-private-material", src
    )
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r5_localstorage_mnemonic_flags() -> None:
    """localStorage.setItem('mnemonic', ...) → CRITICAL hit."""
    src = "localStorage.setItem(\"mnemonic\", phrase);\n"
    assert _hits(
        "web3.client.localstorage-or-indexeddb-private-material", src
    )


def test_r5_indexeddb_objectstore_put_mnemonic_flags() -> None:
    """IndexedDB store.put({mnemonic, ...}) → CRITICAL hit."""
    src = (
        "db.transaction(\"keys\", \"readwrite\")."
        "objectStore(\"keys\").put({ mnemonic, address });\n"
    )
    assert _hits(
        "web3.client.localstorage-or-indexeddb-private-material", src
    )


def test_r5_public_address_storage_silent() -> None:
    """Storing the public address (not private material) → no hit."""
    src = (
        "localStorage.setItem(\"walletAddress\", "
        "\"0x1234567890abcdef1234567890abcdef12345678\");\n"
    )
    assert not _hits(
        "web3.client.localstorage-or-indexeddb-private-material", src
    )


def test_r5_encrypted_keystore_suppressed() -> None:
    """EIP-2335 encrypted keystore JSON in same window → suppressed."""
    src = (
        "const blob = JSON.stringify({\n"
        "  \"crypto\": { \"cipher\": \"aes-128-ctr\" },\n"
        "  \"ciphertext\": \"abc123...\",\n"
        "  \"kdf\": \"scrypt\"\n"
        "});\n"
        "localStorage.setItem(\"encryptedPrivateKey\", blob);\n"
    )
    assert not _hits(
        "web3.client.localstorage-or-indexeddb-private-material", src
    )


# ---------- R6 : web3.client.unvalidated-wallet-connect-callback ---------


def test_r6_eth_requestaccounts_without_verification_flags() -> None:
    """eth_requestAccounts + sendTransaction WITHOUT chainId check → HIGH."""
    src = (
        "async function connect() {\n"
        "  const accounts = await window.ethereum.request("
        "{ method: \"eth_requestAccounts\" });\n"
        "  // no chainId / address verification\n"
        "  await window.ethereum.request({ method: \"eth_sendTransaction\", "
        "params: [tx] });\n"
        "}\n"
    )
    hits = _hits("web3.client.unvalidated-wallet-connect-callback", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_r6_session_event_without_verification_flags() -> None:
    """session_event handler that signs without chain verification → HIGH."""
    src = (
        "signClient.on(\"session_event\", async (e) => {\n"
        "  await signer.signMessage(e.params.event);\n"
        "});\n"
    )
    assert _hits(
        "web3.client.unvalidated-wallet-connect-callback", src
    )


def test_r6_with_chainid_verification_suppressed() -> None:
    """eth_requestAccounts + chainId comparison → no hit."""
    src = (
        "async function connect() {\n"
        "  const accounts = await window.ethereum.request("
        "{ method: \"eth_requestAccounts\" });\n"
        "  const chainId = await window.ethereum.request("
        "{ method: \"eth_chainId\" });\n"
        "  if (chainId !== EXPECTED_CHAIN_ID) {\n"
        "    throw new Error(\"wrong chain\");\n"
        "  }\n"
        "  await window.ethereum.request({ method: \"eth_sendTransaction\", "
        "params: [tx] });\n"
        "}\n"
    )
    assert not _hits(
        "web3.client.unvalidated-wallet-connect-callback", src
    )


# ---------- R7 : web3.client.hardhat-default-account-in-prod -------------


def test_r7_hardhat_account_zero_in_prod_flags() -> None:
    """Hardhat account #0 in a non-test file → CRITICAL hit."""
    src = (
        "// src/config/addresses.ts (PRODUCTION CODE)\n"
        "export const DEPLOYER = "
        "\"0xf39Fd6e51aad88F6F4ce6aB8827279cfFFb92266\";\n"
    )
    hits = _hits("web3.client.hardhat-default-account-in-prod", src)
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_r7_hardhat_account_one_in_prod_flags() -> None:
    """Hardhat account #1 in production artefact → CRITICAL hit."""
    src = (
        "if (signer.address === "
        "\"0x70997970C51812dc3A010C7d01b50e0d17dc79C8\") {\n"
        "  console.log(\"signing as account #1\");\n"
        "}\n"
    )
    assert _hits("web3.client.hardhat-default-account-in-prod", src)


def test_r7_hardhat_account_in_test_context_suppressed() -> None:
    """Hardhat account inside a describe(...) test block → no hit."""
    src = (
        "import { ethers } from \"hardhat\";\n"
        "describe(\"DemoToken\", function () {\n"
        "  it(\"deploys with default deployer\", async () => {\n"
        "    expect(deployer.address).to.equal("
        "\"0xf39Fd6e51aad88F6F4ce6aB8827279cfFFb92266\");\n"
        "  });\n"
        "});\n"
    )
    assert not _hits(
        "web3.client.hardhat-default-account-in-prod", src
    )


def test_r7_hardhat_account_in_hardhat_config_suppressed() -> None:
    """Hardhat account inside hardhat.config.ts → no hit."""
    src = (
        "// hardhat.config.ts\n"
        "module.exports = {\n"
        "  networks: {\n"
        "    hardhat: { accounts: [{ privateKey: \"0xac0974...\", "
        "balance: \"10000\" }] },\n"
        "  },\n"
        "  defaultDeployer: "
        "\"0xf39Fd6e51aad88F6F4ce6aB8827279cfFFb92266\",\n"
        "};\n"
    )
    assert not _hits(
        "web3.client.hardhat-default-account-in-prod", src
    )
