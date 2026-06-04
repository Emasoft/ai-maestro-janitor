"""Tests for scripts/lib/crdt_sync_patterns.py.

Pattern-coverage tests for the Wave-30 distill-round-16 CRDT / collaborative
sync engine catalogue (14 rules covering Yjs / Automerge / Liveblocks /
Replicache anti-patterns). Each rule has exactly 2 tests: one positive
(canary that MUST fire) and one negative (safe variant that MUST NOT fire).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import crdt_sync_patterns as csp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 14 documented rule IDs."""
    assert isinstance(csp.RULES, tuple)
    rule_ids = {r.id for r in csp.RULES}
    expected = {
        "crdt-sync-ydoc-no-awareness-cleanup",
        "crdt-sync-ydoc-update-no-origin-guard",
        "crdt-sync-automerge-no-clone-before-mutate",
        "crdt-sync-liveblocks-presence-pii-broadcast",
        "crdt-sync-replicache-push-no-server-auth",
        "crdt-sync-replicache-pull-no-version-check",
        "crdt-sync-ydoc-xml-fragment-xss",
        "crdt-sync-conflict-resolution-last-write-wins",
        "crdt-sync-undomanager-no-scope",
        "crdt-sync-liveblocks-room-id-user-controlled",
        "crdt-sync-replicache-client-id-predictable",
        "crdt-sync-yjs-provider-no-reconnect-limit",
        "crdt-sync-automerge-load-untrusted",
        "crdt-sync-ydoc-getarray-direct-splice",
    }
    assert expected == rule_ids
    assert len(csp.RULES) == 14


def test_every_rule_has_valid_metadata() -> None:
    """Every rule maps to a valid ASI- prefix, known severity, and non-empty strings."""
    for rule in csp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding must expose all required fields and be immutable."""
    f = csp.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-08",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-08"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert csp.scan_text("") == []


def test_scan_text_returns_list_of_findings() -> None:
    """scan_text() must always return a list, never raise on benign input."""
    result = csp.scan_text("// harmless comment\nconsole.log('hello');\n")
    assert isinstance(result, list)


# ---------- C1 : crdt-sync-ydoc-no-awareness-cleanup --------------------


def test_c1_awareness_created_without_destroy_fires() -> None:
    """Awareness created without destroy() call must trigger C1."""
    src = (
        "const awareness = new Awareness(doc);\n"
        "awareness.setLocalStateField('cursor', pos);\n"
        "// component unmounts here without cleanup\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-ydoc-no-awareness-cleanup" in ids


def test_c1_awareness_with_destroy_does_not_fire() -> None:
    """Awareness created AND destroyed must NOT trigger C1."""
    src = (
        "const awareness = new Awareness(doc);\n"
        "awareness.setLocalStateField('cursor', pos);\n"
        "return () => { awareness.destroy(); };\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-ydoc-no-awareness-cleanup" not in ids


# ---------- C2 : crdt-sync-ydoc-update-no-origin-guard ------------------


def test_c2_update_handler_without_origin_guard_fires() -> None:
    """doc.on('update') forwarding applyUpdate without origin check must trigger C2."""
    src = (
        "doc.on('update', (update, origin) => {\n"
        "  Y.applyUpdate(remoteDoc, update);\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-ydoc-update-no-origin-guard" in ids


def test_c2_update_handler_with_origin_guard_does_not_fire() -> None:
    """doc.on('update') that checks origin before forwarding must NOT trigger C2."""
    src = (
        "doc.on('update', (update, origin) => {\n"
        "  if (origin === 'local') return;\n"
        "  Y.applyUpdate(remoteDoc, update);\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-ydoc-update-no-origin-guard" not in ids


# ---------- C3 : crdt-sync-automerge-no-clone-before-mutate -------------


def test_c3_direct_change_without_clone_fires() -> None:
    """Automerge.change(doc, ...) without a clone call must trigger C3."""
    src = (
        "const next = Automerge.change(doc, draft => {\n"
        "  draft.title = newTitle;\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-automerge-no-clone-before-mutate" in ids


def test_c3_change_with_clone_does_not_fire() -> None:
    """Automerge.change() when clone is also called must NOT trigger C3."""
    src = (
        "const base = Automerge.clone(doc);\n"
        "const next = Automerge.change(doc, draft => {\n"
        "  draft.title = newTitle;\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-automerge-no-clone-before-mutate" not in ids


# ---------- C4 : crdt-sync-liveblocks-presence-pii-broadcast ------------


def test_c4_presence_with_email_fires() -> None:
    """updatePresence() with an email field must trigger C4."""
    src = (
        "room.updatePresence({\n"
        "  email: user.email,\n"
        "  cursor: pos,\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-liveblocks-presence-pii-broadcast" in ids


def test_c4_presence_without_pii_does_not_fire() -> None:
    """updatePresence() with only non-PII fields must NOT trigger C4."""
    src = (
        "room.updatePresence({\n"
        "  cursor: { x: 10, y: 20 },\n"
        "  color: '#ff0000',\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-liveblocks-presence-pii-broadcast" not in ids


# ---------- C5 : crdt-sync-replicache-push-no-server-auth ---------------


def test_c5_push_route_without_auth_fires() -> None:
    """Replicache push route without auth middleware must trigger C5."""
    src = (
        "app.post('/api/push', async (req, res) => {\n"
        "  const mutations = req.body.mutations;\n"
        "  await processMutations(mutations);\n"
        "  res.json({});\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-replicache-push-no-server-auth" in ids


def test_c5_push_route_with_auth_does_not_fire() -> None:
    """Replicache push route with auth middleware must NOT trigger C5."""
    src = (
        "app.post('/api/push', authenticate, async (req, res) => {\n"
        "  const mutations = req.body.mutations;\n"
        "  await processMutations(req.user, mutations);\n"
        "  res.json({});\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-replicache-push-no-server-auth" not in ids


# ---------- C6 : crdt-sync-replicache-pull-no-version-check -------------


def test_c6_pull_route_ignoring_version_fires() -> None:
    """Replicache pull handler that ignores lastMutationID must trigger C6."""
    src = (
        "app.get('/api/pull', async (req, res) => {\n"
        "  const allItems = await db.items.findAll();\n"
        "  res.json({ patch: allItems.map(toAddPatch) });\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-replicache-pull-no-version-check" in ids


def test_c6_pull_route_with_version_check_does_not_fire() -> None:
    """Replicache pull handler that reads lastMutationID must NOT trigger C6."""
    src = (
        "app.get('/api/pull', async (req, res) => {\n"
        "  const { lastMutationID, cookie } = req.body;\n"
        "  const patch = await buildPatch(lastMutationID, cookie);\n"
        "  res.json(patch);\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-replicache-pull-no-version-check" not in ids


# ---------- C7 : crdt-sync-ydoc-xml-fragment-xss ------------------------


def test_c7_xml_fragment_to_innerhtml_fires() -> None:
    """Y.XmlFragment content written to innerHTML without sanitize must trigger C7."""
    src = (
        "const fragment = new Y.XmlFragment();\n"
        "const container = document.getElementById('editor');\n"
        "container.innerHTML = fragment.toDOM().innerHTML;\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-ydoc-xml-fragment-xss" in ids


def test_c7_xml_fragment_with_sanitize_does_not_fire() -> None:
    """Y.XmlFragment content sanitized before innerHTML must NOT trigger C7."""
    src = (
        "const fragment = new Y.XmlFragment();\n"
        "const raw = fragment.toDOM().innerHTML;\n"
        "container.innerHTML = DOMPurify.sanitize(raw);\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-ydoc-xml-fragment-xss" not in ids


# ---------- C8 : crdt-sync-conflict-resolution-last-write-wins ----------


def test_c8_lww_without_vector_clock_fires() -> None:
    """LWW merge strategy without vector clock must trigger C8."""
    src = (
        "const replicache = new Replicache({\n"
        "  conflictResolution: 'lww',\n"
        "  pushURL: '/api/push',\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-conflict-resolution-last-write-wins" in ids


def test_c8_lww_with_vector_clock_does_not_fire() -> None:
    """LWW strategy combined with a vector clock discriminator must NOT trigger C8."""
    src = (
        "// Uses Hybrid Logical Clock for tie-breaking\n"
        "const hlcTimestamp = generateHLC();\n"
        "const mergeStrategy = 'lww';\n"
        "const replicache = new Replicache({ mergeStrategy, hlcTimestamp });\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-conflict-resolution-last-write-wins" not in ids


# ---------- C9 : crdt-sync-undomanager-no-scope -------------------------


def test_c9_undomanager_with_doc_root_fires() -> None:
    """Y.UndoManager(doc) without type scope must trigger C9."""
    src = (
        "const undoManager = new Y.UndoManager(doc, {\n"
        "  captureTimeout: 500,\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-undomanager-no-scope" in ids


def test_c9_undomanager_with_specific_type_does_not_fire() -> None:
    """Y.UndoManager with a specific shared type must NOT trigger C9."""
    src = (
        "const yText = doc.getText('content');\n"
        "const undoManager = new Y.UndoManager([yText], {\n"
        "  captureTimeout: 500,\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-undomanager-no-scope" not in ids


# ---------- C10 : crdt-sync-liveblocks-room-id-user-controlled ----------


def test_c10_room_id_from_params_fires() -> None:
    """enterRoom() with room ID from URL params without allowlist must trigger C10."""
    src = (
        "const roomId = req.params.roomId;\n"
        "const room = client.enter(roomId, { defaultPresence: {} });\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-liveblocks-room-id-user-controlled" in ids


def test_c10_room_id_with_allowlist_does_not_fire() -> None:
    """enterRoom() with room ID validated against allowlist must NOT trigger C10."""
    src = (
        "const roomId = req.params.roomId;\n"
        "if (!ROOM_ALLOWLIST.includes(roomId)) throw new Error('invalid room');\n"
        "const room = client.enter(roomId, { defaultPresence: {} });\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-liveblocks-room-id-user-controlled" not in ids


# ---------- C11 : crdt-sync-replicache-client-id-predictable ------------


def test_c11_client_id_from_email_fires() -> None:
    """clientID derived from user email without strong random must trigger C11."""
    src = (
        "const replicache = new Replicache({\n"
        "  clientID: user.email,\n"
        "  pushURL: '/api/push',\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-replicache-client-id-predictable" in ids


def test_c11_client_id_from_crypto_does_not_fire() -> None:
    """clientID from crypto.randomUUID() must NOT trigger C11."""
    src = (
        "const replicache = new Replicache({\n"
        "  clientID: crypto.randomUUID(),\n"
        "  pushURL: '/api/push',\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-replicache-client-id-predictable" not in ids


# ---------- C12 : crdt-sync-yjs-provider-no-reconnect-limit -------------


def test_c12_provider_without_reconnect_limit_fires() -> None:
    """WebsocketProvider without reconnect cap must trigger C12."""
    src = (
        "const provider = new WebsocketProvider(\n"
        "  'wss://example.com', 'my-room', doc\n"
        ");\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-yjs-provider-no-reconnect-limit" in ids


def test_c12_provider_with_reconnect_limit_does_not_fire() -> None:
    """WebsocketProvider with maxReconnectAttempts must NOT trigger C12."""
    src = (
        "const provider = new WebsocketProvider(\n"
        "  'wss://example.com', 'my-room', doc,\n"
        "  { maxReconnectAttempts: 5 }\n"
        ");\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-yjs-provider-no-reconnect-limit" not in ids


# ---------- C13 : crdt-sync-automerge-load-untrusted --------------------


def test_c13_automerge_load_from_req_body_fires() -> None:
    """Automerge.load() on req.body without integrity check must trigger C13."""
    src = (
        "app.post('/sync', async (req, res) => {\n"
        "  const doc = Automerge.load(req.body.data);\n"
        "  processDoc(doc);\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-automerge-load-untrusted" in ids


def test_c13_automerge_load_with_hmac_check_does_not_fire() -> None:
    """Automerge.load() with HMAC verification must NOT trigger C13."""
    src = (
        "app.post('/sync', async (req, res) => {\n"
        "  const signature = req.headers['x-hmac-signature'];\n"
        "  const verified = verifyHMAC(req.body.data, signature);\n"
        "  if (!verified) return res.status(403).send();\n"
        "  const doc = Automerge.load(req.body.data);\n"
        "});\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-automerge-load-untrusted" not in ids


# ---------- C14 : crdt-sync-ydoc-getarray-direct-splice -----------------


def test_c14_getarray_direct_splice_fires() -> None:
    """Y.Array.toArray().splice() without transactional insert/delete must trigger C14."""
    src = (
        "const yArr = doc.getArray('items');\n"
        "const localCopy = yArr.toArray();\n"
        "localCopy.splice(2, 1);\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-ydoc-getarray-direct-splice" in ids


def test_c14_getarray_with_transactional_delete_does_not_fire() -> None:
    """Y.Array with transactional delete must NOT trigger C14."""
    src = (
        "const yArr = doc.getArray('items');\n"
        "// Correct: use transactional API\n"
        "yArr.delete(2, 1);\n"
    )
    ids = {f.rule_id for f in csp.scan_text(src)}
    assert "crdt-sync-ydoc-getarray-direct-splice" not in ids
