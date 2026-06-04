"""Tests for scripts/lib/polyglot_files_patterns.py.

Pattern-coverage tests for the Wave-29 distill-round-15 polyglot file
detection catalogue (6 rules covering archive dispatch, file upload,
Content-Type proxy passthrough, nosniff, member decode, and JSON schema
validation). Each rule has at least two tests: one positive (the
vulnerable pattern fires) and one negative (a safe variant is silent).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import polyglot_files_patterns as pfp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must expose all 6 documented rule IDs."""
    assert isinstance(pfp.RULES, tuple)
    rule_ids = {r.id for r in pfp.RULES}
    expected = {
        "poly-extension-only-archive-dispatch",
        "poly-client-filename-written-verbatim",
        "poly-upstream-content-type-passthrough",
        "poly-attachment-missing-nosniff",
        "poly-archive-member-extension-only-decode",
        "poly-json-unsafe-cast-no-schema",
    }
    assert expected == rule_ids
    assert len(pfp.RULES) == 6


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity level."""
    for rule in pfp.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding must mirror webhook_signature_patterns.Finding field layout."""
    f = pfp.Finding(
        rule_id="poly-test",
        line=3,
        column=7,
        matched_text="match",
        severity="HIGH",
        description="desc",
        owasp_asi="ASI-08",
    )
    assert f.rule_id == "poly-test"
    assert f.line == 3
    assert f.column == 7
    assert f.matched_text == "match"
    assert f.severity == "HIGH"
    assert f.description == "desc"
    assert f.owasp_asi == "ASI-08"


def test_empty_text_returns_no_findings() -> None:
    """scan_text('') must short-circuit and return an empty list."""
    assert pfp.scan_text("") == []


# ---------- P1 : poly-extension-only-archive-dispatch --------------------


def test_p1_fires_on_whl_endswith_no_magic() -> None:
    """Extension-only .whl dispatch without magic-byte check triggers P1."""
    src = """
def _archive_type(path):
    name = path.name.lower()
    if name.endswith('.whl'):
        return self._extract_wheel(path)   # zipfile — no magic check
    if name.endswith('.zip'):
        return self._extract_zip(path)
    raise ValueError(f"Unsupported: {name}")
"""
    findings = pfp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "poly-extension-only-archive-dispatch" in ids


def test_p1_silent_when_magic_bytes_checked_nearby() -> None:
    """Extension check alongside a MAGIC_ZIP constant must NOT trigger P1."""
    src = """
MAGIC_ZIP = b"PK\\x03\\x04"
MAGIC_GZ  = b"\\x1f\\x8b"

def _safe_read_archive(self, path):
    header = path.read_bytes()[:4]
    if header[:2] == MAGIC_GZ:
        return self._extract_tar(path)
    if header[:4] == MAGIC_ZIP:
        # also handle .whl extension
        if path.name.endswith('.whl'):
            return self._extract_wheel_or_zip(path)
    raise ValueError(f"Unrecognised magic: {header!r}")
"""
    findings = pfp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "poly-extension-only-archive-dispatch" not in ids


# ---------- P2 : poly-client-filename-written-verbatim -------------------


def test_p2_fires_on_werkzeug_filename_then_write_bytes() -> None:
    """file_obj.filename used then .write_bytes() within 10 lines triggers P2."""
    src = """
def handle_upload(self, request):
    name = request.form.get("name")
    file_obj = request.files.get("content")
    filename = file_obj.filename          # client-controlled!
    data = file_obj.read()
    dest = self._project_index.get_dir(name) / filename
    dest.write_bytes(data)
    return "OK", 200
"""
    findings = pfp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "poly-client-filename-written-verbatim" in ids


def test_p2_silent_when_magic_validation_present() -> None:
    """file_obj.filename with ALLOWED_MAGIC check nearby must NOT trigger P2."""
    src = """
ALLOWED_MAGIC = {b"PK\\x03\\x04": "wheel", b"\\x1f\\x8b": "sdist"}

def safe_store_file(self, request):
    file_obj = request.files.get("content")
    filename = file_obj.filename
    data = file_obj.read()
    header = data[:4]
    if not any(header.startswith(m) for m in ALLOWED_MAGIC):
        raise ValueError(f"Rejected: unrecognised magic {header!r}")
    dest = self.get_project_dir() / filename
    dest.write_bytes(data)
    return dest
"""
    findings = pfp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "poly-client-filename-written-verbatim" not in ids


# ---------- P3 : poly-upstream-content-type-passthrough ------------------


def test_p3_fires_on_upstream_ct_forwarded_verbatim() -> None:
    """upstreamResp.headers.get('content-type') without magic probe triggers P3."""
    src = """
const meta = await fetch(upstreamUrl);
const headers = new Headers(meta.headers);
const ct = upstreamResp.headers.get("content-type") ?? "application/json";
return new Response(meta.body, { status: 200, headers: { "content-type": ct } });
"""
    findings = pfp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "poly-upstream-content-type-passthrough" in ids


def test_p3_silent_when_content_type_overridden_safely() -> None:
    """Explicit application/octet-stream override suppresses P3."""
    src = """
const tarResp = await fetch(upstreamTarball);
const buf = await tarResp.arrayBuffer();
const magic = new Uint8Array(buf).slice(0, 4);
const isGzip = magic[0] === 0x1f && magic[1] === 0x8b;
// upstreamResp.headers.get("content-type") is NOT used for the relay
const safeHeaders = new Headers();
safeHeaders.set("content-type", "application/octet-stream");
return new Response(buf, { status: 200, headers: safeHeaders });
"""
    findings = pfp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "poly-upstream-content-type-passthrough" not in ids


# ---------- P4 : poly-attachment-missing-nosniff -------------------------


def test_p4_fires_on_attachment_without_nosniff() -> None:
    """Content-Disposition attachment without nosniff header triggers P4."""
    src = """
precommitRouter.get('/script', async (_req, res) => {
  const script = generateUnixScript();
  res.setHeader('Content-Type', 'text/plain');
  res.setHeader('Content-Disposition', 'attachment; filename="pre-commit"');
  res.send(script);
});
"""
    findings = pfp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "poly-attachment-missing-nosniff" in ids


def test_p4_silent_when_nosniff_present() -> None:
    """X-Content-Type-Options nosniff in forward window suppresses P4."""
    src = """
precommitRouter.get('/script', async (_req, res) => {
  const script = generateUnixScript();
  res.setHeader('Content-Type', 'text/plain; charset=utf-8');
  res.setHeader('Content-Disposition', 'attachment; filename="pre-commit"');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.send(script);
});
"""
    findings = pfp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "poly-attachment-missing-nosniff" not in ids


def test_p4_silent_when_helmet_used_globally() -> None:
    """Global helmet() call suppresses P4 for all attachment routes."""
    src = """
const app = express();
app.use(helmet());

precommitRouter.get('/script', async (_req, res) => {
  res.setHeader('Content-Disposition', 'attachment; filename="hook"');
  res.send(generateScript());
});
"""
    findings = pfp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "poly-attachment-missing-nosniff" not in ids


# ---------- P5 : poly-archive-member-extension-only-decode ---------------


def test_p5_fires_on_member_endswith_py_no_verify() -> None:
    """member.name.endswith('.py') without ast.parse or magic triggers P5."""
    src = """
for member in tf.getmembers():
    _fname = Path(member.name).name
    if member.name.endswith(".py") or _fname == "pyproject.toml":
        content = tf.extractfile(member).read().decode("utf-8", errors="replace")
        submit_to_llm(content)
"""
    findings = pfp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "poly-archive-member-extension-only-decode" in ids


def test_p5_silent_when_ast_parse_applied() -> None:
    """ast.parse call in forward window suppresses P5."""
    src = """
import ast

for member in tf.getmembers():
    if not member.name.endswith(".py"):
        continue
    raw = tf.extractfile(member).read()
    try:
        text = raw.decode("utf-8")
        ast.parse(text)
    except (UnicodeDecodeError, SyntaxError):
        continue
    submit_to_llm(text)
"""
    findings = pfp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "poly-archive-member-extension-only-decode" not in ids


# ---------- P6 : poly-json-unsafe-cast-no-schema -------------------------


def test_p6_fires_on_json_cast_without_schema() -> None:
    """TypeScript `await X.json() as Type` without schema validation triggers P6."""
    src = """
const meta = await fetch(upstreamUrl);
const doc = (await meta.json()) as NpmDoc;
const versions = doc.versions ?? {};
const tb = versions["1.0.0"]?.dist?.tarball;
"""
    findings = pfp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "poly-json-unsafe-cast-no-schema" in ids


def test_p6_silent_when_zod_parse_used() -> None:
    """zod .parse() call in same file suppresses P6."""
    src = """
import { z } from "zod";

const NpmDocSchema = z.object({
    versions: z.record(z.object({
        dist: z.object({ tarball: z.string().url() }).optional(),
    })).optional(),
});

const meta = await fetch(upstreamUrl);
const doc = NpmDocSchema.parse(await meta.json());
"""
    findings = pfp.scan_text(src)
    ids = [f.rule_id for f in findings]
    assert "poly-json-unsafe-cast-no-schema" not in ids
