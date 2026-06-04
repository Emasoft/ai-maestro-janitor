"""ML model tampering / supply-chain attack pattern catalogue.

Wave 19 distillation round 5 — angle A. Net-new deterministic detectors
for tampered or attacker-controlled machine-learning model artifacts
(pickle-backed PyTorch checkpoints, safetensors headers, ONNX graphs,
GGUF metadata, HuggingFace `trust_remote_code`, PEFT/LoRA adapters,
MLflow / W&B artifacts). Source catalogue:
`reports/distill-round-5/ml-model-tampering.md`.

Round-4's `pickle-load-from-network` in `parser_format_patterns.py` only
fires when the *same statement window* also contains a network call.
That rule is intentionally complementary — every rule below covers the
much broader shape "model bytes were downloaded ELSEWHERE (cached on
disk, fetched by `hf_hub_download`, pulled by an earlier function)
and then loaded by the flagged call".

What IS here (14 net-new ML-supply-chain rules, regex-only — the
proposal 13 "no sibling manifest" rule belongs in the file-walker
module, not this text scanner):

  * ml-model.torch-load-without-weights-only        (CRITICAL)
  * ml-model.huggingface-trust-remote-code          (CRITICAL)
  * ml-model.hf-cache-load-no-digest                (HIGH)
  * ml-model.safetensors-load-untrusted-path        (MEDIUM)
  * ml-model.onnx-load-no-checker                   (MEDIUM)
  * ml-model.gguf-loader-call-no-size-cap           (MEDIUM)
  * ml-model.peft-adapter-load-untrusted            (HIGH)
  * ml-model.diffusers-no-revision-pin              (MEDIUM)
  * ml-model.mlflow-load-no-run-pin                 (HIGH)
  * ml-model.wandb-artifact-no-version              (MEDIUM)
  * ml-model.readme-pip-install-from-git-url        (HIGH)
  * ml-model.tokenizer-special-token-injection      (MEDIUM)
  * ml-model.shared-cache-dir-writable              (MEDIUM)
  * ml-model.pipeline-model-name-from-network       (HIGH)

OWASP ASI mapping used here:
  ASI-01 — Prompt injection / tokenizer-boundary attacks
  ASI-04 — Insecure data / supply-chain trust
  ASI-06 — Insecure deserialization / model loading

Public surface mirrors `auth_flow_patterns.py` and
`crypto_misuse_patterns.py` exactly:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi)
  * RULES — ordered tuple of every catalogued rule
  * scan_text(text, *, file_kind="source", filename="") -> list[Finding]
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as the sibling pattern modules
    so heartbeat detectors can render either kind uniformly."""

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
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    owasp_asi: str


def _re(pattern: str) -> re.Pattern:
    """Compile with IGNORECASE+MULTILINE+UNICODE — mirrors siblings."""
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.UNICODE)


# ---- Rule 1: ml-model.torch-load-without-weights-only -------------------


# `torch.load(...)` whose argument window does NOT contain
# `weights_only=True`. Until PyTorch 2.6 the default was full pickle
# deserialisation — a malicious checkpoint executes arbitrary Python
# via __reduce__. The bounded negative lookahead caps the scan at the
# next 300 chars of the argument tuple and the trailing `\)` keeps the
# match to a single-paren call.
_TORCH_LOAD_NO_WEIGHTS_ONLY_RE = _re(
    r"\btorch\s*\.\s*load\s*\("
    r"(?![^)]{0,300}\bweights_only\s*=\s*True\b)"
    r"[^)]{0,300}\)"
)

# Same-line / 1-line-above `# trusted-checkpoint` pragma — operator
# vouches for the checkpoint provenance.
_TRUSTED_CHECKPOINT_PRAGMA_RE = _re(
    r"#\s*trusted-checkpoint\b"
)


# ---- Rule 2: ml-model.huggingface-trust-remote-code ---------------------


# AutoModel / AutoTokenizer / AutoConfig / AutoFeatureExtractor /
# AutoProcessor `from_pretrained` invocations, AND `pipeline(...)`
# direct constructor calls — that pass `trust_remote_code=True`
# explicitly. `trust_remote_code=True` makes `transformers` execute
# arbitrary Python from the model's repo on first load.
#
# Two-shape pattern (alternation):
#   1. <AutoXxx>.from_pretrained(... trust_remote_code=True ...)
#   2. pipeline(... trust_remote_code=True ...)  -- top-level call.
_HF_TRUST_REMOTE_CODE_RE = _re(
    r"\b(?:"
    r"AutoModel(?:[A-Z][A-Za-z]*)?"
    r"|AutoTokenizer|AutoConfig|AutoFeatureExtractor|AutoProcessor"
    r")\s*\.\s*from_pretrained\s*\("
    r"[^)]{0,400}\btrust_remote_code\s*=\s*True\b"
    r"|"
    r"\b(?:transformers\s*\.\s*)?pipeline\s*\("
    r"[^)]{0,400}\btrust_remote_code\s*=\s*True\b"
)

# Same-line / 1-line-above `# trust-remote-code: <reason>` pragma —
# operator MUST justify the override.
_TRUST_REMOTE_CODE_PRAGMA_RE = _re(
    r"#\s*trust-remote-code\s*:\s*\S+"
)


# ---- Rule 3: ml-model.hf-cache-load-no-digest ---------------------------


# `hf_hub_download(...)` / `snapshot_download(...)` (qualified as
# `huggingface_hub.hf_hub_download`, `HfApi().hf_hub_download`, or
# bare-imported via `from huggingface_hub import ...`) followed within
# ~500 chars by a pickle-flavoured loader call (`torch.load`,
# `pickle.load(s)`, `joblib.load`). The file-level guards suppress
# when a `revision=` commit pin OR a `sha256` / `hashlib` digest
# check appears in the file.
#
# Non-greedy `[\s\S]{0,500}?` is bounded — RE2-safe.
_HF_CACHE_LOAD_NO_DIGEST_RE = _re(
    r"\b(?:"
    r"huggingface_hub\s*\.\s*(?:hf_hub_download|snapshot_download)"
    r"|HfApi\s*\(\s*\)\s*\.\s*hf_hub_download"
    r"|hf_hub_download|snapshot_download"
    r")\s*\("
    r"[\s\S]{0,500}?"
    r"(?:"
    r"\btorch\s*\.\s*load\b"
    r"|\bpickle\s*\.\s*loads?\b"
    r"|\bjoblib\s*\.\s*load\b"
    r")"
)

# File-level guards — if any of these appear ANYWHERE in the file we
# treat the hub download as digest-verified and drop the hit.
_HF_DIGEST_FILE_GUARDS: tuple[re.Pattern, ...] = (
    _re(r"\brevision\s*=\s*['\"][a-f0-9]{7,40}['\"]"),
    _re(r"\bsha256\b"),
    _re(r"\bhashlib\b"),
)


# ---- Rule 4: ml-model.safetensors-load-untrusted-path -------------------


# safetensors.{torch,numpy,paddle,flax,tensorflow}.{load_file,load,
# safe_open}(...) where the path argument references an untrusted
# input source. Even though safetensors does not execute pickle, the
# parser still has to consume an attacker-controlled header (declared
# tensor shapes and offsets) — historical integer-overflow gadgets.
_SAFETENSORS_UNTRUSTED_PATH_RE = _re(
    r"\bsafetensors\s*\.\s*"
    r"(?:torch|numpy|paddle|flax|tensorflow)\s*\.\s*"
    r"(?:load_file|load|safe_open)\s*\("
    r"[^)]{0,200}\b"
    r"(?:argv|request\.|input\(|os\.environ|sys\.stdin"
    r"|flask\.request|fastapi|aiohttp\.web|tempfile\.NamedTemporaryFile)"
    r"\b"
)


# ---- Rule 5: ml-model.onnx-load-no-checker ------------------------------


# `onnx.load(...)` NOT followed within ~500 chars by
# `onnx.checker.check_model`. `onnx.load` parses the protobuf without
# validating well-formedness — several historical CVEs in downstream
# ONNX runtimes parsed attacker-supplied node attributes unsafely.
_ONNX_LOAD_NO_CHECKER_RE = _re(
    r"\bonnx\s*\.\s*load\s*\([^)]{0,200}\)"
    r"(?![\s\S]{0,500}\bonnx\s*\.\s*checker\s*\.\s*check_model\b)"
)

# Same-line / 1-line-above `# unchecked-onnx: <reason>` pragma.
_UNCHECKED_ONNX_PRAGMA_RE = _re(
    r"#\s*unchecked-onnx\s*:\s*\S+"
)


# ---- Rule 6: ml-model.gguf-loader-call-no-size-cap ----------------------


# GGUF / GGML loader call where `model_path=` (or `model_file=` /
# `gguf_path=` / `filename=`) is a non-literal (variable expression).
# A malicious GGUF header can claim `dim0 = 2^60`, causing the loader
# to `malloc` hundreds of GB before any bounds-check.
_GGUF_LOADER_NON_LITERAL_RE = _re(
    r"\b(?:"
    r"llama_cpp|llama_cpp_python|ctransformers|GGUFReader|gguf\.GGUFReader|Llama"
    r")"
    r"\s*\.?\s*(?:from_pretrained|__init__|load|model_load)?\s*\("
    r"[^)]{0,300}"
    r"\b(?:model_path|model_file|gguf_path|filename)\s*=\s*"
    r"(?!['\"])\w+"
)

# Same-line / 1-line-above `# trusted-gguf: <reason>` pragma.
_TRUSTED_GGUF_PRAGMA_RE = _re(
    r"#\s*trusted-gguf\s*:\s*\S+"
)


# ---- Rule 7: ml-model.peft-adapter-load-untrusted -----------------------


# Any `PeftModel.from_pretrained(...)` (or the task-specific subclasses).
# A LoRA / PEFT adapter is a small `safetensors` / `bin` file applied
# OVER a base model — it can override the weights of the base model's
# safety / refusal layers WITHOUT changing the base model digest. Flag
# every call so the reviewer confirms the adapter source is pinned.
_PEFT_ADAPTER_LOAD_RE = _re(
    r"\b(?:peft\s*\.\s*)?"
    r"PeftModel"
    r"(?:ForCausalLM|ForSeq2SeqLM|ForTokenClassification|ForSequenceClassification)?"
    r"\s*\.\s*from_pretrained\s*\([^)]{0,400}\)"
)

# `# adapter-pinned: <commit-sha>` operator opt-out (within 3 lines above
# the call).
_ADAPTER_PINNED_PRAGMA_RE = _re(
    r"#\s*adapter-pinned\s*:\s*[a-f0-9]{7,40}\b"
)


# ---- Rule 8: ml-model.diffusers-no-revision-pin -------------------------


# Diffusers pipeline `from_pretrained(...)` whose argument window does
# NOT contain `revision="<hex-7-to-40>"`. Without a commit-hex pin the
# pipeline re-resolves every sub-model on every load against `main`,
# so any sub-component (VAE, U-Net, text encoder) on the source repo
# can be silently swapped.
_DIFFUSERS_NO_REVISION_PIN_RE = _re(
    r"\b(?:"
    r"Stable(?:Diffusion|Video|Audio)\w*Pipeline"
    r"|DiffusionPipeline|FluxPipeline|AutoPipeline\w*"
    r")\s*\.\s*from_pretrained\s*\("
    r"(?![^)]{0,400}\brevision\s*=\s*['\"][a-f0-9]{7,40}['\"])"
    r"[^)]{0,400}\)"
)


# ---- Rule 9: ml-model.mlflow-load-no-run-pin ----------------------------


# `mlflow.<flavor>.load_model("<uri>")` where the URI is a string literal
# that is NOT a `runs:/<32-hex>/...` run-id pin and NOT a
# `models:/<name>/<numeric-or-named-version>` artifact pin. URIs like
# `s3://bucket/models/latest` or `models:/sentiment/Production` resolve
# at load time — anyone with write access to the registry or bucket
# can swap the bytes.
_MLFLOW_LOAD_NO_RUN_PIN_RE = _re(
    r"\bmlflow\s*\.\s*"
    r"(?:pyfunc|sklearn|pytorch|tensorflow|keras|xgboost|lightgbm|catboost"
    r"|onnx|spark|h2o|fastai|prophet|statsmodels|transformers"
    r"|sentence_transformers)"
    r"\s*\.\s*load_model\s*\(\s*"
    r"['\"]"
    r"(?!runs:/[0-9a-f]{32}/"
    r"|models:/[A-Za-z0-9_\-]+/(?:[0-9]+|version-[0-9]+))"
    r"[^'\"]*"
    r"['\"]"
)


# ---- Rule 10: ml-model.wandb-artifact-no-version ------------------------


# `wandb.Api().artifact("<name>")` / `run.use_artifact("<name>")` —
# matched broadly with a CAPTURE GROUP for the artifact name. The
# Stage-B filter in scan_text() inspects the captured name in Python:
# only `:vN` (digits) is a real pin; bare names and `:alias` references
# are flagged. We capture in Python rather than trying to express
# "ends with `:v<digits>`" as a fixed-width lookbehind (which would
# only handle a fixed number of digits — fragile).
_WANDB_ARTIFACT_CALL_RE = _re(
    r"\b(?:wandb\s*\.\s*)?"
    r"(?:Api\s*\(\s*\)\s*\.\s*artifact|run\s*\.\s*use_artifact)\s*\(\s*"
    r"['\"](?P<artifact_name>[^'\"]+)['\"]"
)

# A pinned-version artifact name ends with `:v<digits>` (case-sensitive
# per W&B convention — `:V3` is NOT a wandb-pin).
_WANDB_PINNED_NAME_RE = re.compile(r":v\d+$")

# Same-line `# wandb-alias-ok: <reason>` opt-out.
_WANDB_ALIAS_OK_PRAGMA_RE = _re(
    r"#\s*wandb-alias-ok\s*:\s*\S+"
)


# ---- Rule 11: ml-model.readme-pip-install-from-git-url ------------------


# `pip install git+https://...` / `pip install https://.../archive/...`
# / raw-wheel URL inside a markdown file. HuggingFace model cards and
# ONNX Model Zoo README files routinely show "to use this model run
# `pip install git+https://github.com/some-author/repo`" — the user
# copy-pastes; the repo at that URL is whatever the publisher set it
# to today, no version pin, no PyPI gate.
_README_PIP_INSTALL_GIT_RE = _re(
    r"\b(?:pip|pip3|python\s+-m\s+pip|uv\s+pip)\s+install\s+"
    r"(?:--upgrade\s+|--user\s+|-U\s+|--force-reinstall\s+)*"
    r"(?:git\+https?://"
    r"|https?://[^/\s]+/[^/\s]+/[^/\s]+/(?:archive|releases|raw)/"
    r"|https?://\S+\.(?:whl|tar\.gz)\b"
    r"|file://"
    r"|/[a-zA-Z][^\s]*\.(?:whl|tar\.gz))"
)

# Markdown model-card signature — at least ONE of these must appear in
# the file for rule 11 to fire. Avoids dragging in generic README
# pip-install hits (those are caught by the round-3
# `markdown-pip-install-curl-pipe-bash` rule).
_MODEL_CARD_SIGNATURES: tuple[re.Pattern, ...] = (
    _re(r"^---\s*$[\s\S]{0,800}^\s*library_name\s*:", ),
    _re(r"^---\s*$[\s\S]{0,800}^\s*pipeline_tag\s*:", ),
    _re(r"^---\s*$[\s\S]{0,800}^\s*tags\s*:\s*\n"),
)

# Prose signal that the snippet is intentionally NOT meant to be run.
_DOC_DISCLAIMER_RE = _re(
    r"\b(?:DO\s+NOT\s+RUN|FOR\s+REFERENCE\s+ONLY|EXAMPLE\s+ONLY)\b"
)


# ---- Rule 12: ml-model.tokenizer-special-token-injection ---------------


# `tokenizer.add_special_tokens(...)` / `tokenizer.add_tokens(...)`
# whose argument expression references attacker-controlled input
# (`input(`, `request.`, `argv`, `os.environ`, `json.loads`). The
# tokenizer's special-token map is the bridge between user-supplied
# strings and model-control tokens (`<|im_start|>`, `<|tool_call|>`).
_TOKENIZER_INJECTION_RE = _re(
    r"\btokenizer\s*\.\s*(?:add_special_tokens|add_tokens)\s*\(\s*"
    r"(?:\[[\s\S]{0,400}|\{[\s\S]{0,400})"
    r"\b(?:input|request|argv|os\.environ|json\.loads)\b"
)


# ---- Rule 13: ml-model.shared-cache-dir-writable ------------------------


# `from_pretrained(..., cache_dir="/tmp/...")` /
# `hf_hub_download(..., cache_dir="/dev/shm/...")` — paths writable
# by other local users / containers. Library does NOT lock the cache
# during load; TOCTOU on the model cache is a textbook 2-process
# attack class.
_SHARED_CACHE_DIR_RE = _re(
    r"\b(?:from_pretrained|load_checkpoint_and_dispatch"
    r"|hf_hub_download|snapshot_download)\s*\("
    r"[^)]{0,400}\bcache_dir\s*=\s*"
    r"['\"](?:/tmp/|/var/tmp/|/dev/shm/|~/\.\.|/mnt/shared/|//[^/]+/)"
    r"[^'\"]*['\"]"
)


# ---- Rule 14: ml-model.pipeline-model-name-from-network -----------------


# `transformers.pipeline(model=...)` where the `model=` value is a
# non-literal expression referencing CLI / HTTP / env / stdin / JSON-from-
# request inputs. Network-controlled model selection is the
# server-side-request-forgery analogue for ML pipelines.
_PIPELINE_MODEL_FROM_NETWORK_RE = _re(
    r"\btransformers\s*\.\s*pipeline\s*\("
    r"[^)]{0,300}\bmodel\s*=\s*"
    r"(?!['\"])"
    r"(?:"
    r"[a-zA-Z_][\w.]*"
    r"(?:input|argv|environ|request|stdin|payload|body|params|args|json|form|query)"
    r"[\w.]*"
    r"|[a-zA-Z_][\w.]*\.json\(\)"
    r"|[a-zA-Z_][\w.]*\.read\(\)"
    r"|os\.environ\["
    r")"
)


# ---- Cross-rule helpers -------------------------------------------------


# Filename hints used to suppress rules in test / fixture / example
# files. Mirrors the convention in crypto_misuse_patterns.
_TEST_FILENAME_HINTS: tuple[str, ...] = (
    "test", "tests/", "_test.", "fixture", "fixtures/",
    "conftest", "example", "examples/", "tutorial", "tutorials/",
    "demo", "notebook",
)


# ---- The catalogue ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="ml-model.torch-load-without-weights-only",
        name="torch.load() without weights_only=True",
        severity="CRITICAL",
        description=(
            "`torch.load(...)` called without an explicit "
            "`weights_only=True` in the argument window. Until "
            "PyTorch 2.6, `torch.load` defaulted to full pickle "
            "deserialisation — a malicious checkpoint executes "
            "arbitrary Python on load via `__reduce__` "
            "(CVE-2025-32434). Even on torch 2.6+, many production "
            "pipelines still pass `weights_only=False` for back-compat. "
            "Pair with `# trusted-checkpoint` to opt out."
        ),
        pattern=_TORCH_LOAD_NO_WEIGHTS_ONLY_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ml-model.huggingface-trust-remote-code",
        name="HuggingFace from_pretrained(trust_remote_code=True)",
        severity="CRITICAL",
        description=(
            "`AutoModel.from_pretrained(..., trust_remote_code=True)` "
            "(or AutoTokenizer / pipeline) — `transformers` will "
            "execute arbitrary Python from the model's repo on first "
            "load. An attacker who controls the HuggingFace repo "
            "(or typosquatted name) gets RCE in the consumer's "
            "process. Pair with `# trust-remote-code: <reason>` to "
            "justify the override."
        ),
        pattern=_HF_TRUST_REMOTE_CODE_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ml-model.hf-cache-load-no-digest",
        name="HuggingFace download + pickle-flavour load with no digest",
        severity="HIGH",
        description=(
            "`hf_hub_download` / `snapshot_download` followed within "
            "~500 chars by `torch.load` / `pickle.load(s)` / "
            "`joblib.load` AND no `revision=<commit-hex>` pin AND "
            "no `sha256` / `hashlib` digest check anywhere in the "
            "file. HuggingFace does not verify a caller-supplied "
            "SHA-256 unless `revision=` is explicitly pinned — a "
            "repo compromise that swaps the weights file has zero "
            "defence."
        ),
        pattern=_HF_CACHE_LOAD_NO_DIGEST_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ml-model.safetensors-load-untrusted-path",
        name="safetensors.load_file on attacker-controlled path",
        severity="MEDIUM",
        description=(
            "`safetensors.<backend>.load_file(...)` whose path "
            "argument references CLI / HTTP / env / stdin input. "
            "safetensors cannot execute pickle, but the parser must "
            "still consume an attacker-controlled header declaring "
            "tensor shapes / offsets; Trail of Bits 2023 found "
            "integer-overflow gadgets in third-party wrappers — at "
            "minimum a resource-exhaustion DOS surface."
        ),
        pattern=_SAFETENSORS_UNTRUSTED_PATH_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ml-model.onnx-load-no-checker",
        name="onnx.load() without onnx.checker.check_model() follow-up",
        severity="MEDIUM",
        description=(
            "`onnx.load(path)` parses the protobuf without "
            "validating well-formedness. ONNX node attributes are "
            "strings — several historical CVEs in downstream ONNX "
            "runtimes parsed those strings unsafely. Follow every "
            "`onnx.load` with `onnx.checker.check_model(model)` "
            "within ~500 chars. Pair with `# unchecked-onnx: "
            "<reason>` to opt out."
        ),
        pattern=_ONNX_LOAD_NO_CHECKER_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ml-model.gguf-loader-call-no-size-cap",
        name="GGUF loader call with non-literal model_path",
        severity="MEDIUM",
        description=(
            "GGUF / GGML loader (`llama_cpp`, `ctransformers`, "
            "`GGUFReader`, `Llama`) called with a variable "
            "`model_path=` / `model_file=` / `gguf_path=` / "
            "`filename=` argument. GGUF headers declare tensor "
            "dimensions as `uint64`; a malicious file can claim "
            "`dim0 = 2^60`, causing the loader to `malloc` hundreds "
            "of GB before bounds-checking. Pair with `# trusted-gguf: "
            "<reason>` to opt out."
        ),
        pattern=_GGUF_LOADER_NON_LITERAL_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ml-model.peft-adapter-load-untrusted",
        name="PeftModel.from_pretrained on adapter (audit source pin)",
        severity="HIGH",
        description=(
            "`PeftModel.from_pretrained(...)` (or task-specific "
            "subclass) loads a LoRA / PEFT adapter over a base model. "
            "Adapters override the weights of safety / refusal "
            "layers WITHOUT changing the base model digest — an "
            "attacker who swaps the adapter file silently inserts a "
            "jailbreak into every downstream inference. Pair with "
            "`# adapter-pinned: <commit-sha>` to opt out."
        ),
        pattern=_PEFT_ADAPTER_LOAD_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ml-model.diffusers-no-revision-pin",
        name="Diffusers pipeline from_pretrained without revision pin",
        severity="MEDIUM",
        description=(
            "`StableDiffusionPipeline.from_pretrained(...)` (or any "
            "diffusers `*Pipeline`) without `revision=\"<commit-hex>\"`. "
            "Diffusers pipelines pull multiple sub-models (VAE, "
            "U-Net, text encoder) from HuggingFace by default; "
            "without a commit pin each sub-component re-resolves "
            "against `main` on every load and can be silently "
            "swapped on the source repo. `revision=\"refs/heads/main\"` "
            "is NOT a pin."
        ),
        pattern=_DIFFUSERS_NO_REVISION_PIN_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ml-model.mlflow-load-no-run-pin",
        name="mlflow.<flavor>.load_model without run-id / version pin",
        severity="HIGH",
        description=(
            "`mlflow.<flavor>.load_model(\"<uri>\")` where the URI "
            "is not `runs:/<32-hex>/...` and not "
            "`models:/<name>/<numeric-version>`. Stage-aliased URIs "
            "(`models:/<name>/Production`, "
            "`s3://bucket/models/latest`) resolve at load time — "
            "anyone who can write to the registry or bucket can "
            "swap the bytes."
        ),
        pattern=_MLFLOW_LOAD_NO_RUN_PIN_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ml-model.wandb-artifact-no-version",
        name="W&B use_artifact / Api.artifact without :vN version",
        severity="MEDIUM",
        description=(
            "`run.use_artifact(\"<name>\")` / "
            "`wandb.Api().artifact(\"<name>\")` whose name is bare "
            "or alias-based (`name:latest`, `name:production`). "
            "Only `:vN` (numeric version) pins bytes; aliases "
            "re-resolve and let anyone with write access swap the "
            "artifact. Pair with `# wandb-alias-ok: <reason>` to "
            "opt out."
        ),
        pattern=_WANDB_ARTIFACT_CALL_RE,
        owasp_asi="ASI-06",
    ),
    Rule(
        id="ml-model.readme-pip-install-from-git-url",
        name="pip install git+URL / wheel URL inside ML model card",
        severity="HIGH",
        description=(
            "Markdown model card / README contains `pip install "
            "git+https://...` or `pip install <wheel-url>`. The repo "
            "at that URL is whatever the model publisher sets it to "
            "today — no version pin, no PyPI gate. ML refinement of "
            "the round-3 `markdown-pip-install-curl-pipe-bash` rule: "
            "only fires when the file has HuggingFace model-card "
            "frontmatter (`library_name:`, `pipeline_tag:`, or `tags:`)."
        ),
        pattern=_README_PIP_INSTALL_GIT_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="ml-model.tokenizer-special-token-injection",
        name="tokenizer.add_special_tokens with attacker-controlled input",
        severity="MEDIUM",
        description=(
            "`tokenizer.add_special_tokens(...)` / "
            "`tokenizer.add_tokens(...)` argument references "
            "`input(`, `request.`, `argv`, `os.environ`, or "
            "`json.loads`. The tokenizer's special-token map is the "
            "bridge between user-supplied strings and model-control "
            "tokens (`<|im_start|>`, `<|tool_call|>`); attacker-"
            "controlled additions bypass chat-template safety, end "
            "the user turn early, smuggle tool calls."
        ),
        pattern=_TOKENIZER_INJECTION_RE,
        owasp_asi="ASI-01",
    ),
    Rule(
        id="ml-model.shared-cache-dir-writable",
        name="from_pretrained / hf_hub_download with shared cache_dir",
        severity="MEDIUM",
        description=(
            "`from_pretrained(..., cache_dir=\"/tmp/...\")` / "
            "`hf_hub_download(..., cache_dir=\"/dev/shm/...\")` — "
            "paths writable by other local users / containers. The "
            "library does not lock the cache during load; another "
            "process can swap the bytes after the digest check but "
            "before the file is fully mmapped. Classic TOCTOU on the "
            "model cache."
        ),
        pattern=_SHARED_CACHE_DIR_RE,
        owasp_asi="ASI-04",
    ),
    Rule(
        id="ml-model.pipeline-model-name-from-network",
        name="transformers.pipeline(model=...) name from network / env",
        severity="HIGH",
        description=(
            "`transformers.pipeline(model=<expr>)` where `<expr>` "
            "references CLI / HTTP / env / stdin / "
            "JSON-from-request inputs. `pipeline()` resolves the "
            "model name via HuggingFace at runtime — a "
            "network-controlled name makes the host pull ANY model, "
            "including ones rigged with `trust_remote_code` payloads. "
            "Server-side-request-forgery analogue for ML pipelines."
        ),
        pattern=_PIPELINE_MODEL_FROM_NETWORK_RE,
        owasp_asi="ASI-04",
    ),
)


# ---- The composed scanner ------------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _line_text(text: str, line_no: int) -> str:
    """Return the full text of the 1-based line_no without trailing newline."""
    lines = text.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _preceding_lines(text: str, line_no: int, window: int = 3) -> str:
    """Return previous `window` lines + the target line itself."""
    lines = text.split("\n")
    start = max(0, line_no - 1 - window)
    end = min(len(lines), line_no)
    return "\n".join(lines[start:end])


def _file_contains_any(text: str, guards: tuple[re.Pattern, ...]) -> bool:
    """True if ANY of the guard patterns match anywhere in the file."""
    return any(g.search(text) is not None for g in guards)


def _filename_matches_any(filename: str, hints: tuple[str, ...]) -> bool:
    """True if the filename (case-insensitive) contains any hint."""
    if not filename:
        return False
    lower = filename.lower()
    return any(h in lower for h in hints)


def scan_text(
    text: str,
    *,
    file_kind: str = "source",
    filename: str = "",
) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    `file_kind` is either `"source"` (default — Python source) or
    `"model-card"` (markdown model card). Rule 11
    (`ml-model.readme-pip-install-from-git-url`) only fires on
    `model-card` inputs OR when the text itself contains the
    HuggingFace model-card frontmatter signature.

    `filename` is consulted for test / fixture / example file
    suppression on the rules that allow it (matching is
    substring + case-insensitive).

    Per-rule second-pass filters:

      Rule 1 (torch-load-no-weights-only) : test filename hint OR
        `# trusted-checkpoint` pragma in the 3 preceding lines
        suppresses.
      Rule 2 (trust-remote-code)          : test filename hint OR
        `# trust-remote-code: <reason>` pragma suppresses.
      Rule 3 (hf-cache-load-no-digest)    : file-level `revision=`
        commit pin OR `sha256` / `hashlib` presence suppresses.
      Rule 4 (safetensors-untrusted-path) : test filename hint
        suppresses.
      Rule 5 (onnx-load-no-checker)       : test filename hint OR
        `# unchecked-onnx: <reason>` pragma suppresses.
      Rule 6 (gguf-loader)                : test filename hint OR
        `# trusted-gguf: <reason>` pragma suppresses.
      Rule 7 (peft-adapter)               : test filename hint OR
        `# adapter-pinned: <hex>` pragma in 3 preceding lines.
      Rule 8 (diffusers-no-revision)      : test filename hint
        suppresses.
      Rule 9 (mlflow-no-run-pin)          : test filename hint
        suppresses.
      Rule 10 (wandb-no-version)          : test filename hint OR
        `# wandb-alias-ok: <reason>` pragma suppresses.
      Rule 11 (readme-pip-install)        : ONLY fires on
        file_kind="model-card" OR when the text has HF model-card
        frontmatter. `DO NOT RUN` / `FOR REFERENCE ONLY` disclaimer
        on the same line OR 1 line above suppresses.
      Rule 12 (tokenizer-injection)       : test filename hint
        suppresses.
      Rule 13 (shared-cache-dir)          : test filename hint
        suppresses.
      Rule 14 (pipeline-model-from-net)   : test filename hint
        suppresses.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    # Cheap file-level computations (one shot per file).
    hf_digest_present = _file_contains_any(text, _HF_DIGEST_FILE_GUARDS)
    is_model_card = (
        file_kind == "model-card"
        or _file_contains_any(text, _MODEL_CARD_SIGNATURES)
    )
    is_test_file = _filename_matches_any(filename, _TEST_FILENAME_HINTS)

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _add(rule: Rule, m: re.Match, ln: int, col: int) -> None:
        key = (rule.id, ln, col)
        if key in seen:
            return
        seen.add(key)
        matched = m.group(0)
        if len(matched) > 200:
            matched = matched[:200] + "…"
        findings.append(Finding(
            rule_id=rule.id,
            line=ln,
            column=col,
            matched_text=matched,
            severity=rule.severity,
            description=rule.description,
            owasp_asi=rule.owasp_asi,
        ))

    for rule in RULES:
        for m in rule.pattern.finditer(text):
            line, col = _line_col(text, m.start())
            ln_text = _line_text(text, line)
            ctx = _preceding_lines(text, line, window=3)

            # Per-rule Stage-B filters.
            if rule.id == "ml-model.torch-load-without-weights-only":
                if is_test_file:
                    continue
                if _TRUSTED_CHECKPOINT_PRAGMA_RE.search(ctx) is not None:
                    continue
            elif rule.id == "ml-model.huggingface-trust-remote-code":
                if is_test_file:
                    continue
                if _TRUST_REMOTE_CODE_PRAGMA_RE.search(ctx) is not None:
                    continue
            elif rule.id == "ml-model.hf-cache-load-no-digest":
                if hf_digest_present:
                    continue
                if is_test_file:
                    continue
            elif rule.id == "ml-model.safetensors-load-untrusted-path":
                if is_test_file:
                    continue
            elif rule.id == "ml-model.onnx-load-no-checker":
                if is_test_file:
                    continue
                if _UNCHECKED_ONNX_PRAGMA_RE.search(ctx) is not None:
                    continue
            elif rule.id == "ml-model.gguf-loader-call-no-size-cap":
                if is_test_file:
                    continue
                if _TRUSTED_GGUF_PRAGMA_RE.search(ctx) is not None:
                    continue
            elif rule.id == "ml-model.peft-adapter-load-untrusted":
                if is_test_file:
                    continue
                if _ADAPTER_PINNED_PRAGMA_RE.search(ctx) is not None:
                    continue
            elif rule.id == "ml-model.diffusers-no-revision-pin":
                if is_test_file:
                    continue
            elif rule.id == "ml-model.mlflow-load-no-run-pin":
                if is_test_file:
                    continue
            elif rule.id == "ml-model.wandb-artifact-no-version":
                if is_test_file:
                    continue
                if _WANDB_ALIAS_OK_PRAGMA_RE.search(ln_text) is not None:
                    continue
                # Stage B: the captured artifact name must NOT already
                # end with `:v<digits>` (which IS a real version pin).
                name = m.group("artifact_name")
                if _WANDB_PINNED_NAME_RE.search(name) is not None:
                    continue
            elif rule.id == "ml-model.readme-pip-install-from-git-url":
                # Only fires on model-card-shaped markdown.
                if not is_model_card:
                    continue
                if _DOC_DISCLAIMER_RE.search(ctx) is not None:
                    continue
            elif rule.id == "ml-model.tokenizer-special-token-injection":
                if is_test_file:
                    continue
            elif rule.id == "ml-model.shared-cache-dir-writable":
                if is_test_file:
                    continue
            elif rule.id == "ml-model.pipeline-model-name-from-network":
                if is_test_file:
                    continue

            _add(rule, m, line, col)

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
