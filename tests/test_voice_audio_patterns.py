"""Tests for scripts/lib/voice_audio_patterns.py.

Pattern-coverage tests for the Wave-25 distill-round-11 voice / TTS /
audio supply-chain catalogue (7 anti-patterns). Each rule has at least
one positive test exercising the canary AND at least one negative test
exercising the carve-out or context filter.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import voice_audio_patterns as vap  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 7 documented rule IDs."""
    assert isinstance(vap.RULES, tuple)
    rule_ids = {r.id for r in vap.RULES}
    expected = {
        "voice-hf-model-no-revision-pin",
        "voice-clone-checkpoint-from-untrusted-url",
        "voice-ssml-injection-speech-synthesis",
        "voice-speech-recognition-config-from-url",
        "voice-audio-worklet-external-url",
        "voice-decode-audio-data-no-try-catch",
        "voice-wake-word-threshold-lowered-from-default",
    }
    assert expected == rule_ids
    assert len(vap.RULES) == 7


def test_every_rule_has_valid_owasp_and_severity() -> None:
    """Every rule maps to a valid ASI- prefix and a known severity."""
    for rule in vap.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert rule.description.strip(), rule.id
        assert rule.name.strip(), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding mirrors webhook_signature_patterns.Finding shape."""
    f = vap.Finding(
        rule_id="r",
        line=1,
        column=2,
        matched_text="m",
        severity="HIGH",
        description="d",
        owasp_asi="ASI-04",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-04"


def test_empty_text_returns_empty_findings() -> None:
    """Empty input must short-circuit to []."""
    assert vap.scan_text("") == []


def _hits(rule_id: str, text: str) -> list[vap.Finding]:
    return [f for f in vap.scan_text(text) if f.rule_id == rule_id]


# ---------- V1 : voice-hf-model-no-revision-pin --------------------------


def test_v1_xtts_snapshot_download_no_pin_flags() -> None:
    """coqui/XTTS-v2 fetched without revision= → HIGH hit."""
    src = (
        "from huggingface_hub import snapshot_download\n"
        "local = snapshot_download(\n"
        "    repo_id='coqui/XTTS-v2',\n"
        "    cache_dir='/var/cache/voice-models',\n"
        ")\n"
    )
    hits = _hits("voice-hf-model-no-revision-pin", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_v1_whisper_load_no_pin_flags() -> None:
    """whisper.load_model('large-v3', ...) with no sha256 → HIGH hit."""
    src = (
        "import whisper\n"
        "model = whisper.load_model('large-v3', download_root='/tmp/whisper')\n"
    )
    hits = _hits("voice-hf-model-no-revision-pin", src)
    assert hits


def test_v1_revision_pin_suppresses() -> None:
    """`revision='<sha>'` in same call → no hit."""
    src = (
        "from huggingface_hub import snapshot_download\n"
        "local = snapshot_download(\n"
        "    repo_id='coqui/XTTS-v2',\n"
        "    revision='abc1234def5678abc1234def5678abc1234def56',\n"
        ")\n"
    )
    assert not _hits("voice-hf-model-no-revision-pin", src)


def test_v1_non_voice_repo_does_not_flag() -> None:
    """Generic LLM repo (no voice keyword) → no hit even without pin."""
    src = (
        "from huggingface_hub import snapshot_download\n"
        "local = snapshot_download(repo_id='mistralai/Mistral-7B-v0.1')\n"
    )
    assert not _hits("voice-hf-model-no-revision-pin", src)


# ---------- V2 : voice-clone-checkpoint-from-untrusted-url ---------------


def test_v2_civitai_pth_download_flags() -> None:
    """requests.get of civitai .pth → HIGH hit."""
    src = (
        "import requests\n"
        "ckpt = requests.get(\n"
        "    'https://civitai.com/api/download/models/12345?type=Model&format=PickleTensor.pth'\n"
        ").content\n"
    )
    hits = _hits("voice-clone-checkpoint-from-untrusted-url", src)
    assert hits


def test_v2_huggingface_resolve_pt_download_flags() -> None:
    """requests.get hitting HF resolve/.pt → HIGH hit."""
    src = (
        "r = requests.get(\n"
        "    'https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/hubert_base.pt'\n"
        ")\n"
    )
    assert _hits("voice-clone-checkpoint-from-untrusted-url", src)


def test_v2_sha256_check_in_window_suppresses() -> None:
    """A sibling hashlib.sha256 check → no hit."""
    src = (
        "import requests, hashlib\n"
        "r = requests.get(\n"
        "    'https://huggingface.co/some/voice/resolve/main/clone.safetensors'\n"
        ")\n"
        "assert hashlib.sha256(r.content).hexdigest() == EXPECTED_SHA\n"
    )
    assert not _hits("voice-clone-checkpoint-from-untrusted-url", src)


def test_v2_local_file_load_does_not_flag() -> None:
    """No network fetch → no hit."""
    src = (
        "with open('/srv/voice/clone.pth', 'rb') as f:\n"
        "    state = torch.load(f)\n"
    )
    assert not _hits("voice-clone-checkpoint-from-untrusted-url", src)


# ---------- V3 : voice-ssml-injection-speech-synthesis -------------------


def test_v3_ssml_with_template_userinput_flags() -> None:
    """SSML built with `${req.query...}` interpolation → HIGH hit."""
    src = (
        "const text = req.query.message;\n"
        "const utter = new SpeechSynthesisUtterance(\n"
        "  `<speak><say-as interpret-as=\"digits\">${req.query.x}</say-as></speak>`\n"
        ");\n"
        "speechSynthesis.speak(utter);\n"
    )
    hits = _hits("voice-ssml-injection-speech-synthesis", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_v3_ssml_text_assignment_with_location_search_flags() -> None:
    """`.text = '<speak>...${location.search}'` → HIGH hit."""
    src = (
        "const u = new SpeechSynthesisUtterance();\n"
        "u.text = `<speak>${location.search}</speak>`;\n"
        "speechSynthesis.speak(u);\n"
    )
    assert _hits("voice-ssml-injection-speech-synthesis", src)


def test_v3_ssml_with_escape_guard_suppresses() -> None:
    """An escapeXml / DOMPurify guard on the user input → no hit."""
    src = (
        "const safe = escapeXml(req.query.message);\n"
        "const utter = new SpeechSynthesisUtterance(`<speak>${safe}</speak>`);\n"
        "speechSynthesis.speak(utter);\n"
    )
    assert not _hits("voice-ssml-injection-speech-synthesis", src)


def test_v3_plain_static_text_does_not_flag() -> None:
    """Static literal text → no hit."""
    src = "speechSynthesis.speak(new SpeechSynthesisUtterance('Hello world'));\n"
    assert not _hits("voice-ssml-injection-speech-synthesis", src)


# ---------- V4 : voice-speech-recognition-config-from-url ----------------


def test_v4_lang_from_urlsearchparams_flags() -> None:
    """SpeechRecognition.lang = URLSearchParams.get(...) → HIGH hit."""
    src = (
        "const recog = new webkitSpeechRecognition();\n"
        "const params = new URLSearchParams(location.search);\n"
        "recog.lang = params.get('lang') || 'en-US';\n"
        "recog.start();\n"
    )
    hits = _hits("voice-speech-recognition-config-from-url", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_v4_serviceuri_from_location_flags() -> None:
    """SpeechRecognition.serviceURI = ... location.search → HIGH hit."""
    src = (
        "const recog = new SpeechRecognition();\n"
        "recog.serviceURI = new URL(location.search).searchParams.get('svc');\n"
    )
    assert _hits("voice-speech-recognition-config-from-url", src)


def test_v4_static_lang_does_not_flag() -> None:
    """Static-string `.lang = 'en-US'` → no hit."""
    src = (
        "const recog = new webkitSpeechRecognition();\n"
        "recog.lang = 'en-US';\n"
        "recog.continuous = true;\n"
    )
    assert not _hits("voice-speech-recognition-config-from-url", src)


# ---------- V5 : voice-audio-worklet-external-url ------------------------


def test_v5_addmodule_external_cdn_flags() -> None:
    """addModule with external https:// → HIGH hit."""
    src = (
        "const ctx = new AudioContext();\n"
        "await ctx.audioWorklet.addModule('https://cdn.audio-vendor.example/dsp/eq-v3.js');\n"
    )
    hits = _hits("voice-audio-worklet-external-url", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_v5_addmodule_self_hosted_does_not_flag() -> None:
    """addModule with same-origin pathname → no hit."""
    src = (
        "const ctx = new AudioContext();\n"
        "await ctx.audioWorklet.addModule('/worklets/eq.js');\n"
    )
    assert not _hits("voice-audio-worklet-external-url", src)


def test_v5_addmodule_localhost_does_not_flag() -> None:
    """addModule against localhost dev URL → no hit."""
    src = (
        "await ctx.audioWorklet.addModule('http://localhost:3000/dsp/eq.js');\n"
    )
    assert not _hits("voice-audio-worklet-external-url", src)


# ---------- V6 : voice-decode-audio-data-no-try-catch --------------------


def test_v6_decode_from_filearraybuffer_no_try_flags() -> None:
    """decodeAudioData on file.arrayBuffer() without try → MEDIUM hit."""
    src = (
        "async function previewUserAudio(file) {\n"
        "  const buf = await file.arrayBuffer();\n"
        "  const ctx = new AudioContext();\n"
        "  const decoded = await ctx.decodeAudioData(buf);\n"
        "  ctx.createBufferSource().buffer = decoded;\n"
        "}\n"
    )
    hits = _hits("voice-decode-audio-data-no-try-catch", src)
    assert hits
    assert hits[0].severity == "MEDIUM"


def test_v6_decode_from_fetch_response_flags() -> None:
    """decodeAudioData on response.arrayBuffer() without try → MEDIUM hit."""
    src = (
        "const resp = await fetch(attackerUrl);\n"
        "const buf = await response.arrayBuffer();\n"
        "const decoded = await audioContext.decodeAudioData(buf);\n"
    )
    assert _hits("voice-decode-audio-data-no-try-catch", src)


def test_v6_decode_inside_try_block_suppresses() -> None:
    """decodeAudioData wrapped in try/catch → no hit."""
    src = (
        "try {\n"
        "  const buf = await file.arrayBuffer();\n"
        "  const decoded = await ctx.decodeAudioData(buf);\n"
        "} catch (e) {\n"
        "  console.error('bad audio', e);\n"
        "}\n"
    )
    assert not _hits("voice-decode-audio-data-no-try-catch", src)


def test_v6_decode_with_promise_catch_suppresses() -> None:
    """decodeAudioData(...).catch(...) → no hit."""
    src = (
        "const buf = await file.arrayBuffer();\n"
        "ctx.decodeAudioData(buf).catch(err => console.error(err));\n"
    )
    assert not _hits("voice-decode-audio-data-no-try-catch", src)


# ---------- V7 : voice-wake-word-threshold-lowered-from-default ----------


def test_v7_porcupine_sensitivity_low_flags() -> None:
    """pvporcupine.create(..., sensitivities=[0.2]) → HIGH hit."""
    src = (
        "import pvporcupine\n"
        "porcupine = pvporcupine.create(\n"
        "    access_key=os.environ['PV_ACCESS_KEY'],\n"
        "    keywords=['hey sentinel'],\n"
        "    sensitivities=[0.2],\n"
        ")\n"
    )
    hits = _hits("voice-wake-word-threshold-lowered-from-default", src)
    assert hits
    assert hits[0].severity == "HIGH"


def test_v7_deepfake_threshold_low_flags() -> None:
    """DeepfakeDetector(threshold=0.3) → HIGH hit."""
    src = (
        "from deepfake_detect import DeepfakeDetector\n"
        "det = DeepfakeDetector(threshold=0.3)\n"
    )
    assert _hits("voice-wake-word-threshold-lowered-from-default", src)


def test_v7_openwakeword_low_threshold_flags() -> None:
    """new OpenWakeWord({ threshold: 0.15 }) → HIGH hit."""
    src = (
        "const oww = new OpenWakeWord({\n"
        "  model: 'hey_jarvis',\n"
        "  threshold: 0.15,\n"
        "});\n"
    )
    assert _hits("voice-wake-word-threshold-lowered-from-default", src)


def test_v7_default_threshold_does_not_flag() -> None:
    """Porcupine sensitivities=[0.5] → no hit (within documented band)."""
    src = (
        "porcupine = pvporcupine.create(\n"
        "    keywords=['hey sentinel'],\n"
        "    sensitivities=[0.5],\n"
        ")\n"
    )
    assert not _hits("voice-wake-word-threshold-lowered-from-default", src)


def test_v7_high_threshold_does_not_flag() -> None:
    """DeepfakeDetector(threshold=0.9) → no hit."""
    src = "det = DeepfakeDetector(threshold=0.9)\n"
    assert not _hits("voice-wake-word-threshold-lowered-from-default", src)


# ---------- Cross-rule determinism ---------------------------------------


def test_findings_sorted_by_line_then_column() -> None:
    """Ordering must be deterministic — (line, col, rule_id)."""
    src = (
        # Line 1 — V4 anchor: SpeechRecognition instantiation
        "const recog = new webkitSpeechRecognition();\n"
        # Line 2 — V5 external worklet
        "await ctx.audioWorklet.addModule('https://cdn.evil.example/dsp/eq.js');\n"
        # Line 3 — V4 lang from URL (paired with line-1 anchor)
        "recog.lang = new URLSearchParams(location.search).get('lang');\n"
    )
    findings = vap.scan_text(src)
    assert len(findings) >= 2
    for i in range(len(findings) - 1):
        assert (findings[i].line, findings[i].column) <= (
            findings[i + 1].line,
            findings[i + 1].column,
        )
