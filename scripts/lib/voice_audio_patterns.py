"""Voice / TTS / Audio supply-chain anti-pattern detectors.

Wave-25 distillation round 11 — voice / TTS / STT / wake-word supply
chain. Catalogue of 7 anti-patterns documented in
`reports/distill-round-11/voice-audio-supply.md`. Targets surfaces no
existing pack covers (round-5 `ml_model_patterns`, `rag_llm_patterns`,
`prompt_injection_patterns`, round-10 `webrtc-turn`).

What is NOT here (already shipped — DO NOT duplicate):

  * Generic `torch.load(weights_only=False)` / `hf_hub_download` +
    pickle pair — `ml_model_patterns.py` (round 5).
  * Vector-DB / retrieval poisoning, embedding-model swap —
    `rag_llm_patterns.py` (round 5).
  * Text prompt injection (system-prompt concat, jailbreak phrases) —
    `prompt_injection_patterns.py` (round 5).
  * WebRTC signalling, TURN credentials, ICE candidates, DTLS-SRTP —
    `webrtc-turn` pack (round 10).

What IS here (7 net-new rules, regex-only, all RE2-safe):

  * voice-hf-model-no-revision-pin                     (HIGH)
  * voice-clone-checkpoint-from-untrusted-url          (HIGH)
  * voice-ssml-injection-speech-synthesis              (HIGH)
  * voice-speech-recognition-config-from-url           (HIGH)
  * voice-audio-worklet-external-url                   (HIGH)
  * voice-decode-audio-data-no-try-catch               (MEDIUM)
  * voice-wake-word-threshold-lowered-from-default     (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors
            webhook_signature_patterns.Finding shape.

OWASP ASI mapping used:
  ASI-04 — Insecure Data / Supply-Chain Trust (untrusted bytes feeding
            a model loader, browser audio decoder, or SSML interpreter)
  ASI-06 — Insecure Deserialization / Model Loading (voice-clone /
            ASR pickle checkpoint pulled without revision pin + sha256)

All regexes are RE2-compatible (no backreferences, no lookbehind on
variable-length subpatterns, no catastrophic backtracking shapes).
Patterns are PRE-COMPILED at module load. Fail-fast: callers receive
structured Finding tuples, never raised exceptions on benign input.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as webhook_signature_patterns.Finding."""

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
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors the helper in
    chat_bot_patterns / webhook_signature_patterns. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind on variable runs."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- V1 : voice-hf-model-no-revision-pin --------------------------------


# Anchor on a HuggingFace / Whisper / pyannote / speechbrain audio
# loader. The voice/TTS/ASR repo cluster is bounded — we list every
# real-world id family explicitly to keep the regex precise.
_VOICE_LOADER_TRIGGER = _re(
    r"\b(?:"
    r"huggingface_hub\s*\.\s*snapshot_download"
    r"|huggingface_hub\s*\.\s*hf_hub_download"
    r"|snapshot_download"
    r"|hf_hub_download"
    r"|TTS\s*\(\s*model_name\s*="
    r"|whisper\s*\.\s*load_model"
    r"|pyannote\s*\.\s*audio\s*\.\s*Pipeline\s*\.\s*from_pretrained"
    r"|speechbrain\s*\.\s*pretrained\s*\.\s*"
    r"(?:EncoderClassifier|EncoderDecoderASR|SpeakerRecognition)"
    r"\s*\.\s*from_hparams"
    r")\s*\("
)

# A bounded look-forward up to the closing paren of the loader call —
# the voice/TTS/ASR repo identifier vocabulary that turns this from a
# generic ML loader into a voice-specific one. Bounded `{0,400}` to
# keep RE2-safe (no greedy unbounded run).
_VOICE_REPO_KEYWORD = _re(
    r"\b(?:"
    r"coqui/XTTS|MeloTTS|melo-tts|seamless|speecht5_tts|bark|StyleTTS"
    r"|metavoiceio|VoiceCraft|RVC|so-vits-svc"
    r"|openai/whisper|whisper-large|distil-whisper|faster-whisper"
    r"|pyannote/speaker|suno/bark|tortoise-tts|fish-speech"
    r"|large-v3|large-v2|tiny|base|small|medium"
    r")\b"
)

_VOICE_REVISION_PIN = _re(
    r"\brevision\s*=\s*['\"][a-f0-9]{7,40}['\"]"
)

_VOICE_SHA256_CHECK = _re(
    r"\b(?:hashlib\s*\.\s*sha256|sha256_hex|sha256sum|\.sha256\b)"
)


# ---- V2 : voice-clone-checkpoint-from-untrusted-url ---------------------


# A direct HTTP fetch of a `.pth` / `.bin` / `.safetensors` / `.ckpt` /
# `.pt` / `.pkl` / `.gguf` / `.onnx` / `.tflite` / `.h5` / `.npz` file
# from one of the known voice-model distribution endpoints. RE2-safe:
# every quantifier is bounded by a small upper limit.
_VOICE_CHECKPOINT_URL_FETCH = _re(
    r"\b(?:"
    r"requests\s*\.\s*get"
    r"|urllib\s*\.\s*request\s*\.\s*urlopen"
    r"|aiohttp\s*\.\s*ClientSession"
    r"|httpx\s*\.\s*(?:get|AsyncClient)"
    r"|urllib3\s*\.\s*PoolManager"
    r")\s*\([^)]{0,300}"
    r"['\"`]https?://[^'\"`]{0,200}"
    r"(?:"
    r"huggingface\.co/[^/'\"`]{1,80}/[^/'\"`]{1,80}/resolve"
    r"|cdn\.discordapp\.com/attachments"
    r"|gateway\.pinata\.cloud"
    r"|civitai\.com/api/download"
    r"|drive\.google\.com/uc"
    r")"
    r"[^'\"`]{0,200}"
    r"\.(?:pth|bin|safetensors|ckpt|pt|pkl|gguf|onnx|tflite|h5|npz)"
    r"['\"`]"
)


# ---- V3 : voice-ssml-injection-speech-synthesis -------------------------


# Anchor: any construction of a `SpeechSynthesisUtterance` or call to
# `speechSynthesis.speak`. The interpolation/concatenation marker is
# enforced as a SECOND pattern within a small forward window so the
# trigger stays cheap and RE2-safe.
_SSML_UTTERANCE_TRIGGER = _re(
    r"\b(?:"
    r"new\s+SpeechSynthesisUtterance\s*\("
    r"|speechSynthesis\s*\.\s*speak\s*\("
    r"|\.text\s*=\s*[`'\"]\s*<speak\b"
    r")"
)

# A bounded run after the trigger may contain a template-literal /
# concat with user-controllable source. The source token list mirrors
# the round-11 catalogue.
_SSML_USER_INPUT_SOURCE = _re(
    r"\b(?:"
    r"userInput|req\.body|req\.query|req\.params|request\.body"
    r"|searchParams|params\.get|location\.search|location\.hash"
    r"|window\.name|document\.referrer|document\.location"
    r"|message\s*\.\s*content|chat\s*\.\s*input"
    r")\b"
)

# Escape / sanitiser guard. If any of these helpers appear in the same
# window as the trigger we treat the call as escaped and suppress.
_SSML_ESCAPE_GUARD = _re(
    r"\b(?:"
    r"escapeXml|escapeHtml|escapeSsml|escape_ssml"
    r"|DOMPurify\s*\.\s*sanitize|he\s*\.\s*encode|he\s*\.\s*escape"
    r"|sanitizeSsml|sanitizeHtml"
    r")\b"
)


# ---- V4 : voice-speech-recognition-config-from-url ----------------------


# Anchor: SpeechRecognition / webkitSpeechRecognition instantiation OR
# any property assignment on a SpeechRecognition-like variable that
# pulls from a URL-derived source. The source list includes the
# `params.get(...)` accessor shape because real code routinely does
# `const params = new URLSearchParams(location.search)` on one line
# and `recog.lang = params.get('lang')` on the next.
_SPEECH_RECOGNITION_PROPERTY_FROM_URL = _re(
    r"\b(?:webkitSpeechRecognition|SpeechRecognition)\b"
    r"[\s\S]{0,400}?"
    r"\.\s*(?:lang|continuous|interimResults|maxAlternatives|serviceURI)"
    r"\s*=\s*"
    r"[^;\n]{0,200}"
    r"\b(?:"
    r"location\s*\.\s*(?:search|hash)"
    r"|URLSearchParams|new\s+URL\s*\("
    r"|window\s*\.\s*name|document\s*\.\s*referrer"
    r"|localStorage\s*\.\s*getItem"
    r"|sessionStorage\s*\.\s*getItem"
    r"|document\s*\.\s*cookie"
    r"|params\s*\.\s*get\s*\("
    r"|searchParams\s*\.\s*get\s*\("
    r")"
)


# ---- V5 : voice-audio-worklet-external-url ------------------------------


# Anchor: addModule called with an http(s) URL whose host is NOT
# localhost / 127.0.0.1. The Worklet spec has no integrity= option;
# the only safe form is a same-origin pathname.
_AUDIO_WORKLET_EXTERNAL_URL = _re(
    r"\.audioWorklet\s*\.\s*addModule\s*\(\s*"
    r"['\"`]https?://"
    r"(?!(?:127\.0\.0\.1|localhost|\[::1\]))"
    r"[^'\"`]{1,200}\.js"
    r"['\"`]"
)


# ---- V6 : voice-decode-audio-data-no-try-catch --------------------------


# Anchor: any `decodeAudioData(` call. The bytes-source and the
# try/catch guard are evaluated in a same-function window by the
# Stage-B scanner because the byte buffer is routinely defined on a
# line earlier than the decode call.
_DECODE_AUDIO_DATA_TRIGGER = _re(
    r"\b(?:audioContext|ctx|audio_ctx|this\s*\.\s*context"
    r"|this\s*\.\s*audioCtx|audioCtx|context)"
    r"\s*\.\s*decodeAudioData\s*\("
)

# An untrusted-bytes source signal appearing in a same-function window
# around the decode call. Keeps the rule from flagging
# decodeAudioData of a pre-validated, hash-checked, in-app buffer.
_DECODE_AUDIO_DATA_UNTRUSTED_BYTES = _re(
    r"\b(?:"
    r"await\s+fetch|response\s*\.\s*arrayBuffer"
    r"|\.\s*arrayBuffer\s*\(\s*\)"
    r"|new\s+Uint8Array|atob\s*\("
    r"|location\s*\.|searchParams|params\s*\.|request\s*\.|req\s*\."
    r"|userInput|uploadedFile|file\s*\.\s*arrayBuffer"
    r")"
)

# Same-function guards. A try-block opener or an explicit .catch on
# the decode promise.
_DECODE_AUDIO_DATA_TRY_GUARD = _re(
    r"\btry\s*\{"
    r"|\.\s*catch\s*\("
    r"|window\s*\.\s*addEventListener\s*\(\s*['\"`]unhandledrejection['\"`]"
    r"|window\s*\.\s*onerror\s*="
)


# ---- V7 : voice-wake-word-threshold-lowered-from-default ----------------


# Anchor: a wake-word / deepfake-detector / voiceprint engine call,
# AND a numeric literal strictly below 0.5 (any 0.0 - 0.49 shape).
# The literal pattern uses three explicit alternatives — `0.0X`, `0.[1-4]X`,
# and `.[0-4]X` — to keep the boundary tight (a bare `0` alone would
# false-positive on `threshold=0.9` by matching just the leading `0`).
# `pvporcupine` / `porcupine` are both accepted as the module name.
# RE2-safe: every quantifier is bounded by a small upper limit, no
# nested quantifiers, no lookbehind.
_WAKE_WORD_LOW_THRESHOLD = _re(
    r"\b(?:"
    r"Porcupine\s*\([^)]{0,200}\bsensitivities?\s*="
    r"|(?:pv)?porcupine\s*\.\s*create\s*\([^)]{0,200}\bsensitivities?\s*="
    r"|openwakeword\s*\.\s*[A-Za-z_]{1,40}\s*\([^)]{0,200}\bthreshold\s*="
    r"|OWW\s*\([^)]{0,200}\bthreshold\s*="
    r"|new\s+OpenWakeWord\s*\(\s*\{[^}]{0,300}\bthreshold\s*:"
    r"|detect_deepfake\s*\([^)]{0,200}\bconfidence_threshold\s*="
    r"|DeepfakeDetector\s*\([^)]{0,200}\bthreshold\s*="
    r"|resemble\s*\.\s*detect\s*\([^)]{0,200}\bthreshold\s*="
    r"|pindrop\s*\.\s*[A-Za-z_]{1,40}\s*\([^)]{0,200}\bconfidence\s*="
    r"|speakerVerification\s*\([^)]{0,200}\bthreshold\s*="
    r"|pyannote[^)\n]{0,200}\bmin_speaker_confidence\s*="
    r")"
    r"\s*\[?\s*"
    r"(?:0\.0[0-9]\d{0,3}|0\.[1-4]\d{0,4}|\.[0-4]\d{0,4})"
    r"\b"
)


# ---- RULES tuple --------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="voice-hf-model-no-revision-pin",
        name="HuggingFace voice/TTS/ASR model fetched with no revision pin",
        severity="HIGH",
        description=(
            "`huggingface_hub.snapshot_download(repo_id)` / "
            "`hf_hub_download` / `whisper.load_model` / "
            "`pyannote.audio.Pipeline.from_pretrained` / "
            "`speechbrain ... from_hparams` called on a voice / TTS / "
            "ASR repository without a `revision=` commit pin and "
            "without a sibling sha256 check. Voice-clone model cards "
            "(coqui/XTTS-v2, MeloTTS, seamless-streaming, speecht5_tts, "
            "pyannote/speaker-diarization-3.1) ship pickle-flavoured "
            "`.pth` / `.bin` / `.gguf` weights — a `__reduce__` gadget "
            "in any of them is RCE on first load. Generic "
            "`ml_model_patterns` covers the loader; this rule targets "
            "the audio-specific repo allowlist."
        ),
        pattern=_VOICE_LOADER_TRIGGER,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="voice-clone-checkpoint-from-untrusted-url",
        name="Voice-clone checkpoint fetched from a raw URL with no integrity check",
        severity="HIGH",
        description=(
            "`requests.get` / `urllib.request.urlopen` / `httpx.get` / "
            "`aiohttp.ClientSession` pulling a `.pth` / `.bin` / "
            "`.safetensors` / `.ckpt` / `.gguf` / `.onnx` / `.tflite` "
            "file from huggingface.co/<user>/<repo>/resolve, "
            "civitai.com, gateway.pinata.cloud, "
            "cdn.discordapp.com/attachments, or drive.google.com — "
            "none of these endpoints expose a server-side SHA256 "
            "manifest. Without a sibling digest check the resulting "
            "pickle is an arbitrary-code-execution sink on "
            "`torch.load(weights_only=False)`. Distinct from "
            "`ml_model_patterns` which catches the load step; this "
            "rule fires on the fetch step."
        ),
        pattern=_VOICE_CHECKPOINT_URL_FETCH,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="voice-ssml-injection-speech-synthesis",
        name="SSML payload built from user input into SpeechSynthesisUtterance",
        severity="HIGH",
        description=(
            "`new SpeechSynthesisUtterance(...)` or "
            "`speechSynthesis.speak(...)` is called with an SSML "
            "string whose `<say-as>` / `<voice>` / `<audio src>` "
            "content is concatenated or template-interpolated from a "
            "user-controllable source (`req.query`, `location.search`, "
            "`window.name`, `document.referrer`) without an SSML / "
            "XML-entity escape. WebKit and recent Chromium honour "
            "`<audio src=...>` — the TTS engine fetches the URL, "
            "leaking data to the attacker's access log. Use "
            "`escapeXml` / `escapeSsml` / `DOMPurify.sanitize` to "
            "neutralise the entity-level payload."
        ),
        pattern=_SSML_UTTERANCE_TRIGGER,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="voice-speech-recognition-config-from-url",
        name="SpeechRecognition.lang / serviceURI / continuous assigned from URL source",
        severity="HIGH",
        description=(
            "`webkitSpeechRecognition` or `SpeechRecognition` has its "
            "`.lang` / `.serviceURI` / `.continuous` / "
            "`.interimResults` property assigned from a URL-derived "
            "source (`location.search`, `URLSearchParams`, "
            "`window.name`, `document.referrer`, `document.cookie`). "
            "An attacker-crafted link to "
            "`?lang=cmn-Hans-CN&svc=https://attacker/asr` routes the "
            "user's microphone audio to a non-default Cloud-Speech "
            "endpoint AND, for the legacy `serviceURI` property, "
            "directly to the attacker. Always pin these settings to "
            "an app-controlled enum, never the URL."
        ),
        pattern=_SPEECH_RECOGNITION_PROPERTY_FROM_URL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="voice-audio-worklet-external-url",
        name="audioWorklet.addModule fetches a JS worklet from an external CDN URL",
        severity="HIGH",
        description=(
            "`audioContext.audioWorklet.addModule(<url>)` called with "
            "a cross-origin `https://...` URL. AudioWorklet modules "
            "run on the realtime audio thread with direct access to "
            "the PCM buffer and `port.postMessage` back to the main "
            "thread. The Worklet spec has NO `integrity:` option, so "
            "the only safe form is a same-origin pathname "
            "(`'/worklets/eq.js'`, `'./worklets/eq.js'`, or a `new "
            "URL('./...', import.meta.url)` constructor). Loading "
            "from a public CDN is a tag-rewriting attack surface with "
            "no SRI defence — self-host or pin the entire CDN path."
        ),
        pattern=_AUDIO_WORKLET_EXTERNAL_URL,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="voice-decode-audio-data-no-try-catch",
        name="decodeAudioData called on attacker-controlled bytes without try/catch",
        severity="MEDIUM",
        description=(
            "`AudioContext.decodeAudioData(arrayBuffer)` parses the "
            "input through the browser's internal Vorbis / FLAC / "
            "MP3 / AAC codec pipeline — every one of those has CVE "
            "history (libvorbis CVE-2018-5146/-10393, libflac "
            "CVE-2017-6888, Chrome CVE-2019-13720). When the bytes "
            "come from `fetch(<url>)`, `response.arrayBuffer()`, "
            "`file.arrayBuffer()` on a user upload, or "
            "`atob(...)` of an untrusted base64, the parse runs on "
            "foreign input. Without a same-function `try { }` opener "
            "or a `.catch(...)` on the returned promise the failure "
            "mode is a hard rejection that, on a stale Android "
            "WebView, can still trigger heap-touch behaviour in the "
            "native codec. Wrap every `decodeAudioData` in "
            "try/catch."
        ),
        pattern=_DECODE_AUDIO_DATA_TRIGGER,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="voice-wake-word-threshold-lowered-from-default",
        name="Wake-word / deepfake-detector confidence threshold below the documented default",
        severity="HIGH",
        description=(
            "Picovoice Porcupine ships `sensitivity=0.5` as the "
            "documented balance default; openWakeWord uses "
            "`threshold=0.5`; ElevenLabs / Resemble.AI / Pindrop "
            "deepfake detectors expose `confidence_threshold` "
            "(typically 0.9 default). A production-code literal "
            "strictly below 0.5 on any of these engines is the "
            "classic 'developer got frustrated with false negatives "
            "during demo and never raised it back' regression. The "
            "result is a wake word that activates on background noise "
            "(microphone opens, audio streamed to cloud STT without "
            "user intent) OR a deepfake detector that lets synthetic "
            "voice authentication bypass the voiceprint gate. Restore "
            "the engine's documented default."
        ),
        pattern=_WAKE_WORD_LOW_THRESHOLD,
        owasp_asi="ASI-04",
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
    """Return up to `backward` lines preceding line_no plus line_no
    itself plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


# ---- The composed scanner ----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * V1 (voice-hf-model-no-revision-pin) — anchor on the audio
        loader call, require a voice-specific repo keyword in the same
        20-line window, AND require ABSENCE of `revision='<sha>'`
        AND ABSENCE of `hashlib.sha256` / `.sha256` in the same file.
      * V3 (voice-ssml-injection-speech-synthesis) — anchor on the
        utterance trigger, require user-input source in a 5-line
        window, AND require ABSENCE of an escape/sanitiser call in
        the same window.
      * V6 (voice-decode-audio-data-no-try-catch) — anchor on the
        decode-with-untrusted-bytes shape, AND require ABSENCE of a
        try-block / `.catch(...)` / `unhandledrejection` listener in
        a small window around the call.

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

    # ---- V1 : voice-hf-model-no-revision-pin ----
    # Stage-B: per-call window must (a) include a voice-specific repo
    # keyword AND (b) NOT include a `revision='<sha>'` pin AND (c) NOT
    # include a `hashlib.sha256` / `.sha256` digest check. Either guard
    # in the window suppresses — matches the report's "if both negatives
    # hold, flag" gate per call site.
    rule_v1 = rule_by_id["voice-hf-model-no-revision-pin"]
    for m in _VOICE_LOADER_TRIGGER.finditer(text):
        line, _ = _line_col(text, m.start())
        # 20-line window — voice repo keyword must appear within the
        # loader call's arguments; the digest check / pin marker is
        # checked in the same window.
        window = _slice_window(text, line, 2, 18)
        if _VOICE_REPO_KEYWORD.search(window) is None:
            continue
        if _VOICE_REVISION_PIN.search(window) is not None:
            continue
        if _VOICE_SHA256_CHECK.search(window) is not None:
            continue
        _emit(rule_v1, m.start(), m.group(0))

    # ---- V2 : voice-clone-checkpoint-from-untrusted-url ----
    rule_v2 = rule_by_id["voice-clone-checkpoint-from-untrusted-url"]
    for m in _VOICE_CHECKPOINT_URL_FETCH.finditer(text):
        line, _ = _line_col(text, m.start())
        # 10-line forward window — a sibling sha256 / .sha256 call is
        # the documented mitigation; suppress if present.
        window = _slice_window(text, line, 0, 10)
        if _VOICE_SHA256_CHECK.search(window) is not None:
            continue
        _emit(rule_v2, m.start(), m.group(0))

    # ---- V3 : voice-ssml-injection-speech-synthesis ----
    rule_v3 = rule_by_id["voice-ssml-injection-speech-synthesis"]
    for m in _SSML_UTTERANCE_TRIGGER.finditer(text):
        line, _ = _line_col(text, m.start())
        # 5-line forward window — interpolation marker must appear
        # near the utterance construction.
        window = _slice_window(text, line, 0, 5)
        if _SSML_USER_INPUT_SOURCE.search(window) is None:
            continue
        if _SSML_ESCAPE_GUARD.search(window) is not None:
            continue
        _emit(rule_v3, m.start(), m.group(0))

    # ---- V4 : voice-speech-recognition-config-from-url ----
    rule_v4 = rule_by_id["voice-speech-recognition-config-from-url"]
    for m in _SPEECH_RECOGNITION_PROPERTY_FROM_URL.finditer(text):
        _emit(rule_v4, m.start(), m.group(0))

    # ---- V5 : voice-audio-worklet-external-url ----
    rule_v5 = rule_by_id["voice-audio-worklet-external-url"]
    for m in _AUDIO_WORKLET_EXTERNAL_URL.finditer(text):
        _emit(rule_v5, m.start(), m.group(0))

    # ---- V6 : voice-decode-audio-data-no-try-catch ----
    rule_v6 = rule_by_id["voice-decode-audio-data-no-try-catch"]
    for m in _DECODE_AUDIO_DATA_TRIGGER.finditer(text):
        line, _ = _line_col(text, m.start())
        # 10-line backward + 5-line forward window — the byte buffer is
        # routinely defined on a line earlier than the decode call.
        window = _slice_window(text, line, 10, 5)
        # Require evidence the bytes come from an untrusted source.
        if _DECODE_AUDIO_DATA_UNTRUSTED_BYTES.search(window) is None:
            continue
        # Require ABSENCE of a try/catch / .catch / unhandledrejection
        # guard in the same window.
        if _DECODE_AUDIO_DATA_TRY_GUARD.search(window) is not None:
            continue
        _emit(rule_v6, m.start(), m.group(0))

    # ---- V7 : voice-wake-word-threshold-lowered-from-default ----
    rule_v7 = rule_by_id["voice-wake-word-threshold-lowered-from-default"]
    for m in _WAKE_WORD_LOW_THRESHOLD.finditer(text):
        _emit(rule_v7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
